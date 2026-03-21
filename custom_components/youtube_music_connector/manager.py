"""Manager for youtube_music_connector."""

from __future__ import annotations

import asyncio
import logging
import random
from urllib.parse import parse_qs, urlparse
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pytubefix import YouTube

from homeassistant.components.media_player.const import MediaPlayerEntityFeature, MediaPlayerState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.network import get_url

from .const import (
    ATTR_LIMIT,
    ATTR_PROXY_URL,
    ATTR_QUERY,
    ATTR_RESULTS,
    ATTR_SEARCH_TYPE,
    ATTR_SELECTED_DEVICES,
    CONF_DEFAULT_TARGET_MEDIA_PLAYER,
    CONF_EXCLUDE_DEVICES,
    CONF_HEADER_PATH,
    CONF_LANGUAGE,
    CONF_NAME,
    DEFAULT_LANGUAGE,
    DEFAULT_LIMIT,
    DEFAULT_PROXY_PATH_PREFIX,
    ITEM_TYPE_ARTIST,
    ITEM_TYPE_PLAYLIST,
    ITEM_TYPE_SONG,
    MEDIA_TYPE_MAP,
    REPEAT_MODE_FOREVER,
    REPEAT_MODE_OFF,
    REPEAT_MODE_ONCE,
    SEARCH_TYPE_ALL,
    SEARCH_TYPE_ARTISTS,
    SEARCH_TYPE_PLAYLISTS,
    SEARCH_TYPE_SONGS,
    normalize_repeat_mode,
)
from .youtube_music_api import YoutubeMusicApiClient

_LOGGER = logging.getLogger(__name__)


@dataclass
class ResolvedPlayback:
    """Resolved playback details."""

    item_type: str
    item_id: str
    playable_id: str
    title: str
    artist: str
    image_url: str
    url: str
    stream_url: str
    proxy_url: str


class YoutubeMusicConnectorManager:
    """Owns API access, per-device sessions and cached search results."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        self._api: YoutubeMusicApiClient | None = None
        self._listeners: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()

        default_target: str = entry.options.get(
            CONF_DEFAULT_TARGET_MEDIA_PLAYER,
            entry.data.get(CONF_DEFAULT_TARGET_MEDIA_PLAYER, ""),
        )
        # selected_device_ids: ordered list; first entry is the primary session.
        self._selected_device_ids: list[str] = [default_target] if default_target else []

        self._last_search_payload: dict[str, Any] = {
            ATTR_QUERY: "",
            ATTR_SEARCH_TYPE: SEARCH_TYPE_ALL,
            ATTR_LIMIT: DEFAULT_LIMIT,
            ATTR_RESULTS: [],
            "count": 0,
        }
        self._search_index: dict[tuple[str, str], dict[str, Any]] = {}
        self._last_error: str = ""
        self._entity_id: str = ""
        self._exclude_devices: set[str] = set(
            entry.options.get(CONF_EXCLUDE_DEVICES, entry.data.get(CONF_EXCLUDE_DEVICES, []))
        )

        # Per-device sessions, lazily created via get_or_create_session().
        self._sessions: dict[str, DeviceSession] = {}

        # Recently played cache — max 5 per type, sorted by most recent first.
        self._recent_songs: list[dict[str, Any]] = []
        self._recent_playlists: list[dict[str, Any]] = []
        self._recent_artists: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def get_or_create_session(self, entity_id: str) -> "DeviceSession":
        """Return the existing session or create a new one for entity_id."""
        if entity_id not in self._sessions:
            from .device_session import DeviceSession
            session = DeviceSession(self, entity_id)
            self._sessions[entity_id] = session
        return self._sessions[entity_id]

    @property
    def primary_session(self) -> "DeviceSession | None":
        """Return the session for the first selected device, if any."""
        if not self._selected_device_ids:
            return None
        return self.get_or_create_session(self._selected_device_ids[0])

    @property
    def selected_device_ids(self) -> list[str]:
        return list(self._selected_device_ids)

    # ------------------------------------------------------------------
    # Basic properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self.entry.title or self.entry.data.get(CONF_NAME, "YouTube Music")

    @property
    def state(self) -> str:
        session = self.primary_session
        if session:
            target_state = session.state
            if target_state in {MediaPlayerState.PLAYING, MediaPlayerState.PAUSED, MediaPlayerState.IDLE}:
                return target_state
            if session._current_item:
                return MediaPlayerState.IDLE
        return MediaPlayerState.OFF

    @property
    def target_entity_id(self) -> str:
        """Primary selected device entity_id (legacy compat)."""
        return self._selected_device_ids[0] if self._selected_device_ids else ""

    # Legacy compat: group_targets = selected_device_ids[1:]
    @property
    def group_targets(self) -> list[str]:
        return list(self._selected_device_ids[1:])

    @property
    def entity_id(self) -> str:
        return self._entity_id

    @property
    def target_state(self) -> str | None:
        """State of the primary target device."""
        session = self.primary_session
        return session.state if session else None

    @property
    def current_item(self) -> dict[str, Any]:
        session = self.primary_session
        return session.current_item if session else {}

    @property
    def search_payload(self) -> dict[str, Any]:
        return deepcopy(self._last_search_payload)

    @property
    def last_error(self) -> str:
        session = self.primary_session
        return session.last_error if session else self._last_error

    @property
    def source_list(self) -> list[str]:
        sources: list[str] = []
        for state in self.hass.states.async_all("media_player"):
            if state.entity_id == self._entity_id:
                continue
            if state.entity_id.startswith("media_player.youtube_music_connector"):
                continue
            if state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN}:
                continue
            if bool(state.attributes.get("restored")):
                continue
            if state.entity_id in self._exclude_devices:
                continue
            sources.append(state.entity_id)
        return sorted(set(sources))

    @property
    def media_title(self) -> str | None:
        session = self.primary_session
        return session.media_title if session else None

    @property
    def media_artist(self) -> str | None:
        session = self.primary_session
        return session.media_artist if session else None

    @property
    def media_image_url(self) -> str | None:
        session = self.primary_session
        return session.media_image_url if session else None

    @property
    def media_duration(self) -> float | None:
        duration = self._primary_target_state_attr("media_duration")
        return float(duration) if isinstance(duration, (int, float)) else None

    @property
    def media_position(self) -> float | None:
        if self._should_reset_position_on_idle():
            return 0.0
        position = self._primary_target_state_attr("media_position")
        return float(position) if isinstance(position, (int, float)) else None

    @property
    def media_position_updated_at(self) -> datetime | None:
        updated_at = self._primary_target_state_attr("media_position_updated_at")
        return updated_at if isinstance(updated_at, datetime) else None

    @property
    def target_supports_seek(self) -> bool:
        state = self._primary_target_state_object()
        if not state:
            return False
        supported = int(state.attributes.get("supported_features", 0))
        return bool(supported & MediaPlayerEntityFeature.SEEK)

    @property
    def has_next_track(self) -> bool:
        session = self.primary_session
        return session.has_next_track if session else False

    @property
    def has_previous_track(self) -> bool:
        session = self.primary_session
        return session.has_previous_track if session else False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        session = self.primary_session
        current_item = session._current_item if session else {}
        autoplay_enabled = session._autoplay_enabled if session else False
        autoplay_queue_length = len(session._autoplay_queue) if session else 0
        shuffle_enabled = session._shuffle_enabled if session else False
        repeat_mode = session._repeat_mode if session else REPEAT_MODE_OFF
        last_error = session._last_error if session else self._last_error

        attrs = {
            "search_results": self._last_search_payload.get(ATTR_RESULTS, []),
            "search_query": self._last_search_payload.get(ATTR_QUERY, ""),
            "search_type": self._last_search_payload.get(ATTR_SEARCH_TYPE, SEARCH_TYPE_ALL),
            "search_count": self._last_search_payload.get("count", 0),
            "target_entity_id": self.target_entity_id,
            "available_target_players": self.source_list,
            "current_item": current_item,
            "last_error": last_error,
            "is_youtube_music_connector": True,
            "autoplay_enabled": autoplay_enabled,
            "autoplay_queue_length": autoplay_queue_length,
            "shuffle_enabled": shuffle_enabled,
            "repeat_mode": repeat_mode,
            "has_next_track": self.has_next_track,
            "has_previous_track": self.has_previous_track,
            # New attribute: full ordered list of selected devices
            ATTR_SELECTED_DEVICES: list(self._selected_device_ids),
            # Legacy: group_targets = all except first
            "group_targets": list(self._selected_device_ids[1:]),
            # Active sessions summary
            "active_sessions": {eid: s.summary_dict() for eid, s in self._sessions.items()},
            # Recently played counts per type
            "recent_items_count": len(self._recent_songs) + len(self._recent_playlists) + len(self._recent_artists),
        }
        if session and session._current_resolved:
            attrs["resolved_stream"] = {
                "playable_id": session._current_resolved.playable_id,
                ATTR_PROXY_URL: session._current_resolved.proxy_url,
            }
        return attrs

    # ------------------------------------------------------------------
    # Listener management
    # ------------------------------------------------------------------

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def async_notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        try:
            await self.async_ensure_api()
            # Bind listener for the default target if configured
            if self._selected_device_ids:
                session = self.get_or_create_session(self._selected_device_ids[0])
                await session.async_bind()
            self._last_error = ""
        except Exception as err:
            self._last_error = str(err)
            self.async_notify()
            raise

    # ------------------------------------------------------------------
    # Device / target selection
    # ------------------------------------------------------------------

    async def async_set_selected_devices(self, device_ids: list[str]) -> dict[str, Any]:
        """Set the full ordered list of selected devices. First = primary."""
        filtered = [d for d in device_ids if d not in self._exclude_devices]
        previous_primary = self._selected_device_ids[0] if self._selected_device_ids else ""
        new_primary = filtered[0] if filtered else ""

        # Pause previous primary if it was actively playing our stream
        if previous_primary and previous_primary != new_primary:
            old_session = self._sessions.get(previous_primary)
            if old_session and self._should_pause_session_on_switch(old_session):
                await self.hass.services.async_call(
                    "media_player",
                    "media_pause",
                    {"entity_id": previous_primary},
                    blocking=True,
                )

        self._selected_device_ids = filtered

        # Ensure primary session is bound
        if new_primary:
            session = self.get_or_create_session(new_primary)
            await session.async_bind()

        self.async_notify()
        return {ATTR_SELECTED_DEVICES: list(self._selected_device_ids)}

    async def async_set_target(self, entity_id: str) -> None:
        """Legacy: set a single primary target device."""
        if entity_id in self._exclude_devices:
            raise HomeAssistantError(f"Device {entity_id} is excluded from playback")
        # Build new selected list: [entity_id] + existing non-primary devices
        existing_secondary = [d for d in self._selected_device_ids[1:] if d != entity_id]
        await self.async_set_selected_devices([entity_id] + existing_secondary)

    async def async_set_group_targets(self, targets: list[str]) -> dict[str, Any]:
        """Deprecated: set additional targets alongside the current primary."""
        primary = self._selected_device_ids[0] if self._selected_device_ids else ""
        new_list = ([primary] if primary else []) + [
            t for t in targets if t != primary and t not in self._exclude_devices
        ]
        await self.async_set_selected_devices(new_list)
        return {"group_targets": list(self._selected_device_ids[1:])}

    def _should_pause_session_on_switch(self, session: "DeviceSession") -> bool:
        if not session._current_resolved:
            return False
        state = self.hass.states.get(session.entity_id)
        if not state or state.state != MediaPlayerState.PLAYING:
            return False
        return state.attributes.get("media_content_id") == session._current_resolved.proxy_url

    async def async_set_entity_id(self, entity_id: str) -> None:
        self._entity_id = entity_id
        self.async_notify()

    # ------------------------------------------------------------------
    # Playback mode setters — applied to all selected sessions
    # ------------------------------------------------------------------

    async def async_set_autoplay(self, enabled: bool) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for device_id in self._selected_device_ids:
            session = self.get_or_create_session(device_id)
            result = await session.async_set_autoplay(enabled)
        return result

    async def async_set_shuffle(self, enabled: bool) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for device_id in self._selected_device_ids:
            session = self.get_or_create_session(device_id)
            result = await session.async_set_shuffle(enabled)
        return result

    async def async_set_repeat_mode(self, repeat_mode: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for device_id in self._selected_device_ids:
            session = self.get_or_create_session(device_id)
            result = await session.async_set_repeat_mode(repeat_mode)
        return result

    # ------------------------------------------------------------------
    # Track navigation — primary session only
    # ------------------------------------------------------------------

    async def async_next_track(self) -> dict[str, Any]:
        session = self.primary_session
        if not session:
            raise HomeAssistantError("No target media player selected")
        return await session.async_next_track()

    async def async_previous_track(self) -> dict[str, Any]:
        session = self.primary_session
        if not session:
            raise HomeAssistantError("No target media player selected")
        return await session.async_previous_track()

    # ------------------------------------------------------------------
    # Transport — applied to all selected sessions
    # ------------------------------------------------------------------

    async def async_media_pause(self) -> None:
        tasks = [
            self.get_or_create_session(d).async_media_pause()
            for d in self._selected_device_ids
        ]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for device_id, result in zip(self._selected_device_ids, results):
                if isinstance(result, Exception):
                    _LOGGER.warning("media_pause failed for %s: %s", device_id, result)
        self.async_notify()

    async def async_media_play(self) -> None:
        tasks = [
            self.get_or_create_session(d).async_media_play()
            for d in self._selected_device_ids
        ]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for device_id, result in zip(self._selected_device_ids, results):
                if isinstance(result, Exception):
                    _LOGGER.warning("media_play failed for %s: %s", device_id, result)

    async def async_media_stop(self) -> None:
        tasks = [
            self.get_or_create_session(d).async_media_stop()
            for d in self._selected_device_ids
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def async_media_seek(self, position: float) -> None:
        """Seek on primary session only."""
        session = self.primary_session
        if session:
            await session.async_media_seek(position)

    # ------------------------------------------------------------------
    # Play / stop
    # ------------------------------------------------------------------

    async def async_play(self, target_entity_id: str, item_type: str, item_id: str) -> dict[str, Any]:
        if target_entity_id:
            await self.async_set_target(target_entity_id)
        session = self.primary_session
        if not session:
            raise HomeAssistantError("No target media player selected")
        try:
            result = await session.async_play(item_type, item_id)
            # Mirror to all secondary selected sessions
            secondary = self._selected_device_ids[1:]
            if secondary and session._current_resolved:
                mirror_tasks = [
                    self._async_start_resolved_playback_on(session._current_resolved, d)
                    for d in secondary
                ]
                mirror_results = await asyncio.gather(*mirror_tasks, return_exceptions=True)
                for d, r in zip(secondary, mirror_results):
                    if isinstance(r, Exception):
                        _LOGGER.warning("Mirror playback to %s failed: %s", d, r)
            self._last_error = ""
            # Record to recently played cache after successful playback
            if session._current_resolved:
                try:
                    self._record_recent_play(item_type, item_id, session._current_resolved)
                except Exception:
                    pass  # Never let cache recording break playback
            return result
        except Exception as err:
            if session:
                session._last_error = f"Playback failed: {err}"
            self._last_error = f"Playback failed: {err}"
            self.async_notify()
            _LOGGER.exception("Failed to start playback for %s/%s", item_type, item_id)
            raise HomeAssistantError(f"Could not start playback: {err}") from err

    async def async_play_on(self, target_entity_id: str, item_type: str, item_id: str) -> dict[str, Any]:
        """Play on a specific target without switching the manager's active target."""
        if not target_entity_id:
            raise HomeAssistantError("No target media player specified")
        resolved = await self._async_resolve_playback(item_type, item_id)
        await self._async_start_resolved_playback_on(resolved, target_entity_id)
        return {"target_entity_id": target_entity_id, "title": resolved.title}

    async def async_stop(self, target_entity_id: str | None = None) -> dict[str, Any]:
        if target_entity_id:
            await self.async_set_target(target_entity_id)
        session = self.primary_session
        if not session:
            raise HomeAssistantError("No target media player selected")
        await session.async_stop()
        # Stop secondary devices too
        secondary_tasks = [
            self.get_or_create_session(d).async_media_stop()
            for d in self._selected_device_ids[1:]
        ]
        if secondary_tasks:
            await asyncio.gather(*secondary_tasks, return_exceptions=True)
        self._last_error = ""
        self.async_notify()
        return {"target_entity_id": self.target_entity_id, "stopped": True}

    # ------------------------------------------------------------------
    # Low-level stream playback (shared utility)
    # ------------------------------------------------------------------

    async def _async_start_resolved_playback_on(self, resolved: ResolvedPlayback, target_entity_id: str) -> None:
        """Start playback on a specific target without updating session state."""
        media_types = self._playback_media_types_for(resolved.item_type, target_entity_id)
        last_error: Exception | None = None
        for media_type in media_types:
            try:
                await self.hass.services.async_call(
                    "media_player",
                    "play_media",
                    {
                        "entity_id": target_entity_id,
                        "media_content_id": resolved.proxy_url,
                        "media_content_type": media_type,
                        "enqueue": "replace",
                    },
                    blocking=True,
                )
                return
            except Exception as err:
                last_error = err
        if last_error is not None:
            raise last_error

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    async def async_ensure_api(self) -> YoutubeMusicApiClient:
        async with self._lock:
            if self._api is not None:
                return self._api
            language = self.entry.options.get(CONF_LANGUAGE, self.entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE))
            try:
                self._api = YoutubeMusicApiClient(
                    self.hass,
                    self.entry.options.get(CONF_HEADER_PATH, self.entry.data[CONF_HEADER_PATH]),
                    language,
                )
                await self._api.async_validate("Bodo Wartke")
            except Exception as err:
                self._last_error = f"API initialization failed: {err}"
                _LOGGER.exception("Failed to initialize youtube_music_connector API")
                raise HomeAssistantError("YouTube Music API could not be initialized") from err
            return self._api

    # ------------------------------------------------------------------
    # Recently played cache
    # ------------------------------------------------------------------

    def _record_recent_play(self, item_type: str, item_id: str, resolved: ResolvedPlayback) -> None:
        """Record a played item in the per-type recent history (max 5 each)."""
        import time
        entry: dict[str, Any] = {
            "type": item_type,
            "id": item_id,
            "title": resolved.title,
            "artist": resolved.artist,
            "playlist_name": "",
            "image_url": resolved.image_url,
            "url": resolved.url,
            "played_at": time.time(),
        }
        # Enrich with search index data if available (e.g. playlist_name for playlists)
        index_entry = self._search_index.get((item_type, item_id))
        if index_entry:
            entry["playlist_name"] = index_entry.get("playlist_name", "")
            if not entry["title"] and index_entry.get("title"):
                entry["title"] = index_entry["title"]
            if not entry["artist"] and index_entry.get("artist"):
                entry["artist"] = index_entry["artist"]
            if not entry["image_url"] and index_entry.get("image_url"):
                entry["image_url"] = index_entry["image_url"]

        if item_type == ITEM_TYPE_SONG:
            target_list = self._recent_songs
        elif item_type == ITEM_TYPE_PLAYLIST:
            target_list = self._recent_playlists
        elif item_type == ITEM_TYPE_ARTIST:
            target_list = self._recent_artists
        else:
            return

        # Remove duplicate by id, then prepend
        target_list[:] = [e for e in target_list if e.get("id") != item_id]
        target_list.insert(0, entry)
        # Trim to max 5
        del target_list[5:]

    def get_recent_items(self, filter_type: str | None = None, limit: int = 5, offset: int = 0) -> list[dict[str, Any]]:
        """Return recently played items, optionally filtered by type."""
        if filter_type in (SEARCH_TYPE_SONGS, ITEM_TYPE_SONG):
            return self._recent_songs[offset: offset + limit]
        if filter_type in (SEARCH_TYPE_ARTISTS, ITEM_TYPE_ARTIST):
            return self._recent_artists[offset: offset + limit]
        if filter_type in (SEARCH_TYPE_PLAYLISTS, ITEM_TYPE_PLAYLIST):
            return self._recent_playlists[offset: offset + limit]
        # Merge all three lists, sort by played_at descending, paginate
        merged = self._recent_songs + self._recent_playlists + self._recent_artists
        merged.sort(key=lambda e: e.get("played_at", 0), reverse=True)
        return merged[offset: offset + limit]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def async_search(self, query: str, search_type: str, limit: int) -> dict[str, Any]:
        query = query.strip()
        limit = max(1, min(int(limit or DEFAULT_LIMIT), 25))
        payload: dict[str, Any] = {
            ATTR_QUERY: query,
            ATTR_SEARCH_TYPE: search_type,
            ATTR_LIMIT: limit,
            ATTR_RESULTS: [],
            "count": 0,
        }
        self._last_error = ""

        if not query:
            # Return recently played items instead of an empty result set
            recent = self.get_recent_items(filter_type=search_type, limit=limit, offset=0)
            payload[ATTR_RESULTS] = recent
            payload["count"] = len(recent)
            payload["source"] = "recent"
            self._last_search_payload = payload
            self.async_notify()
            return payload

        try:
            api = await self.async_ensure_api()
            raw_results: list[dict[str, Any]] = []
            if search_type == SEARCH_TYPE_ALL:
                raw_results = await api.async_search(query=query, filter_name=None, limit=limit * 3)
            else:
                raw_results = await api.async_search(query=query, filter_name=search_type, limit=limit)

            normalized: list[dict[str, Any]] = []
            self._search_index.clear()
            for item in raw_results:
                normalized_item = self._normalize_result(item)
                if not normalized_item:
                    continue
                normalized.append(normalized_item)
                self._search_index[(normalized_item["type"], normalized_item["id"])] = normalized_item

            normalized = self._rank_results(normalized, query)
            normalized = normalized[:limit]

            payload[ATTR_RESULTS] = normalized
            payload["count"] = len(normalized)
            self._last_search_payload = payload
            self._last_error = ""
            self.async_notify()
            return deepcopy(payload)
        except Exception as err:
            self._last_search_payload = payload
            self._last_error = f"Search failed: {err}"
            self.async_notify()
            _LOGGER.exception("YouTube Music search failed for query '%s'", query)
            raise HomeAssistantError(f"YouTube Music search failed: {err}") from err

    @staticmethod
    def _rank_results(results: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        """Re-rank results by how many query tokens match across all fields."""
        tokens = [t.lower() for t in query.split() if t]
        if not tokens:
            return results

        def score(item: dict[str, Any]) -> float:
            text = " ".join([
                item.get("title", ""),
                item.get("artist", ""),
                item.get("playlist_name", ""),
            ]).lower()
            matched = sum(1 for t in tokens if t in text)
            return matched / len(tokens)

        return sorted(results, key=score, reverse=True)

    def _normalize_result(self, item: dict[str, Any]) -> dict[str, Any] | None:
        result_type = item.get("resultType")
        if result_type not in {ITEM_TYPE_SONG, ITEM_TYPE_ARTIST, ITEM_TYPE_PLAYLIST}:
            return None
        image_url = self._extract_thumbnail(item)
        if result_type == ITEM_TYPE_SONG:
            item_id = item.get("videoId")
            if not item_id:
                return None
            artist = self._extract_artists(item)
            title = item.get("title", "") or ""
            return {
                "type": ITEM_TYPE_SONG,
                "id": item_id,
                "artist": artist,
                "title": title,
                "playlist_name": "",
                "image_url": image_url,
                "url": f"https://music.youtube.com/watch?v={item_id}",
            }
        if result_type == ITEM_TYPE_ARTIST:
            item_id = item.get("browseId")
            artist_name = item.get("artist") or item.get("title") or ""
            if not item_id and item.get("artists"):
                item_id = item["artists"][0].get("id", "")
                artist_name = item["artists"][0].get("name", artist_name)
            if not item_id:
                return None
            return {
                "type": ITEM_TYPE_ARTIST,
                "id": item_id,
                "artist": artist_name,
                "title": "",
                "playlist_name": "",
                "image_url": image_url,
                "url": self._build_artist_url(item_id),
            }
        item_id = self._normalize_playlist_id(item.get("playlistId") or item.get("browseId") or "")
        if not item_id:
            return None
        owner = item.get("author") or self._extract_artists(item)
        playlist_name = item.get("title", "") or ""
        return {
            "type": ITEM_TYPE_PLAYLIST,
            "id": item_id,
            "browse_id": item.get("browseId", ""),
            "artist": owner,
            "title": "",
            "playlist_name": playlist_name,
            "image_url": image_url,
            "url": self._build_playlist_url(item_id),
        }

    async def async_resolve_stream(self, item_type: str, item_id: str) -> dict[str, Any]:
        try:
            resolved = await self._async_resolve_playback(item_type, item_id)
            self._last_error = ""
            self.async_notify()
            return {
                "item_type": resolved.item_type,
                "item_id": resolved.item_id,
                "playable_id": resolved.playable_id,
                "title": resolved.title,
                "artist": resolved.artist,
                "image_url": resolved.image_url,
                "url": resolved.url,
                "stream_url": resolved.stream_url,
                ATTR_PROXY_URL: resolved.proxy_url,
            }
        except Exception as err:
            self._last_error = f"Resolve failed: {err}"
            self.async_notify()
            _LOGGER.exception("Failed to resolve stream for %s/%s", item_type, item_id)
            raise HomeAssistantError(f"Could not resolve stream: {err}") from err

    async def async_execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        target_entity_id = payload.get("target_entity_id", "")
        if target_entity_id:
            await self.async_set_target(target_entity_id)

        if "autoplay_enabled" in payload:
            await self.async_set_autoplay(bool(payload["autoplay_enabled"]))
        if "shuffle_enabled" in payload:
            await self.async_set_shuffle(bool(payload["shuffle_enabled"]))
        if "repeat_mode" in payload:
            await self.async_set_repeat_mode(str(payload["repeat_mode"]))

        query = str(payload.get("query", "") or "").strip()
        search_type = str(payload.get("search_type", SEARCH_TYPE_ALL) or SEARCH_TYPE_ALL)
        limit = int(payload.get("limit", DEFAULT_LIMIT) or DEFAULT_LIMIT)
        should_play = bool(payload.get("play", False))

        direct_item = self._resolve_programmatic_item(payload)
        search_payload: dict[str, Any] | None = None
        selected_item: dict[str, Any] | None = None

        if direct_item is not None:
            item_type, item_id = direct_item
            selected_item = {"type": item_type, "id": item_id}
        elif query:
            search_payload = await self.async_search(query, search_type, limit)
            results = search_payload.get(ATTR_RESULTS, [])
            if results:
                selected_item = results[0]
        else:
            raise HomeAssistantError(
                "No executable input provided. Use query, song_id, playlist_id, artist_id, item_type/item_id, or youtube_url."
            )

        session = self.primary_session
        response: dict[str, Any] = {
            "selected": selected_item,
            "search": search_payload,
            "autoplay_enabled": session._autoplay_enabled if session else False,
            "shuffle_enabled": session._shuffle_enabled if session else False,
            "repeat_mode": session._repeat_mode if session else REPEAT_MODE_OFF,
            "target_entity_id": self.target_entity_id,
        }

        if selected_item is None:
            return response

        if should_play:
            play_result = await self.async_play(
                self.target_entity_id,
                selected_item["type"],
                selected_item["id"],
            )
            response["playback"] = play_result
        else:
            response["resolved"] = await self.async_resolve_stream(
                selected_item["type"],
                selected_item["id"],
            )

        if payload.get("volume_percent") is not None:
            await self._async_set_programmatic_volume(int(payload["volume_percent"]))
            response["volume_percent"] = int(payload["volume_percent"])

        return response

    # ------------------------------------------------------------------
    # Stream resolution (shared, uses API)
    # ------------------------------------------------------------------

    async def _async_resolve_playback(self, item_type: str, item_id: str) -> ResolvedPlayback:
        api = await self.async_ensure_api()
        normalized = self._search_index.get((item_type, item_id), {})
        playable_id = item_id
        image_url = normalized.get("image_url", "")
        title = normalized.get("title") or normalized.get("playlist_name") or normalized.get("artist") or item_id
        artist = normalized.get("artist", "")
        public_url = normalized.get("url", "")

        if item_type == ITEM_TYPE_PLAYLIST:
            playlist_id = self._normalize_playlist_id(item_id)
            browse_id = normalized.get("browse_id")
            playlist = await api.async_get_playlist(playlist_id, limit=25, browse_id=browse_id)
            tracks = [track for track in (playlist.get("tracks") or []) if track.get("videoId")]
            track = self._pick_initial_track(tracks)
            playable_id = track.get("videoId", "")
            title = playlist.get("title", title)
            raw_author = playlist.get("author", artist)
            if isinstance(raw_author, dict):
                artist = raw_author.get("name", "") or artist
            else:
                artist = str(raw_author) if raw_author else artist
            image_url = self._extract_thumbnail(playlist) or image_url
            public_url = self._build_playlist_url(playlist_id)
        elif item_type == ITEM_TYPE_ARTIST:
            artist_name = normalized.get("artist") or item_id
            songs = await api.async_search(query=artist_name, filter_name=SEARCH_TYPE_SONGS, limit=10)
            track = self._pick_initial_track(songs)
            playable_id = track.get("videoId", "")
            title = track.get("title", title)
            artist = self._extract_artists(track) or artist_name
            image_url = self._extract_thumbnail(track) or image_url
            public_url = self._build_artist_url(item_id)
        else:
            public_url = public_url or f"https://music.youtube.com/watch?v={item_id}"

        if not playable_id:
            raise HomeAssistantError("No playable song could be resolved")

        stream_url = await self.hass.async_add_executor_job(self._resolve_audio_stream, playable_id)
        proxy_url = self._build_proxy_url(playable_id, item_type, item_id)
        return ResolvedPlayback(
            item_type=item_type,
            item_id=item_id,
            playable_id=playable_id,
            title=title,
            artist=artist,
            image_url=image_url,
            url=public_url or f"https://music.youtube.com/watch?v={playable_id}",
            stream_url=stream_url,
            proxy_url=proxy_url,
        )

    def _resolve_audio_stream(self, video_id: str) -> str:
        try:
            yt = YouTube(f"https://music.youtube.com/watch?v={video_id}")
            stream = yt.streams.filter(only_audio=True).order_by("abr").last()
        except Exception as err:
            raise HomeAssistantError(f"Audio stream lookup failed for {video_id}: {err}") from err
        if stream is None:
            raise HomeAssistantError(f"No audio stream found for {video_id}")
        return stream.url

    def _build_proxy_url(self, playable_id: str, item_type: str, item_id: str) -> str:
        base = get_url(self.hass, allow_internal=True, allow_external=True)
        return f"{base}{DEFAULT_PROXY_PATH_PREFIX}/{self.entry.entry_id}/{item_type}/{item_id}?video_id={playable_id}"

    async def async_get_proxy_stream_url(self, item_type: str, item_id: str, playable_id: str | None = None) -> str:
        # Check all active sessions first
        for session in self._sessions.values():
            cr = session._current_resolved
            if (
                cr
                and cr.item_type == item_type
                and cr.item_id == item_id
                and (playable_id is None or cr.playable_id == playable_id)
            ):
                return cr.stream_url
        resolved = await self._async_resolve_playback(item_type, item_id)
        # Cache on primary session if available
        session = self.primary_session
        if session:
            session._current_resolved = resolved
        self.async_notify()
        return resolved.stream_url

    # ------------------------------------------------------------------
    # Media type helpers
    # ------------------------------------------------------------------

    def _playback_media_types_for(self, item_type: str, target_entity_id: str = "") -> list[str]:
        primary = str(MEDIA_TYPE_MAP.get(item_type, "music"))
        target_preferences = self._target_playback_media_type_preferences(target_entity_id)
        ordered = [*target_preferences, primary, "music", "audio/mpeg", "audio", "video", "url"]
        seen: set[str] = set()
        return [media_type for media_type in ordered if not (media_type in seen or seen.add(media_type))]

    def _target_playback_media_type_preferences(self, target_entity_id: str = "") -> list[str]:
        eid = target_entity_id or self.target_entity_id
        target_state = self.hass.states.get(eid) if eid else None
        device_class = str(target_state.attributes.get("device_class", "")).lower() if target_state else ""
        if device_class == "speaker":
            return ["music"]
        if device_class == "tv":
            return ["video", "music"]

        registry = er.async_get(self.hass)
        entry = registry.async_get(eid) if eid else None
        original_device_class = str(entry.original_device_class or "").lower() if entry else ""
        if original_device_class == "speaker":
            return ["music"]
        if original_device_class == "tv":
            return ["video", "music"]

        haystack = " ".join(
            part for part in [
                eid or "",
                str(target_state.attributes.get("friendly_name", "")) if target_state else "",
                str(target_state.attributes.get("app_name", "")) if target_state else "",
                str(target_state.attributes.get("source", "")) if target_state else "",
            ] if part
        ).lower()
        if any(token in haystack for token in ("tv", "chromecast_tv", "projector", "display", "monitor", "cinema")):
            return ["video", "music"]
        return ["music", "video"]

    # ------------------------------------------------------------------
    # Queue helpers (used by DeviceSession._async_resolve_playback)
    # ------------------------------------------------------------------

    def _pick_initial_track(self, tracks: list[dict[str, Any]]) -> dict[str, Any]:
        """Pick the initial track from a list, using primary session shuffle setting."""
        session = self.primary_session
        shuffle = session._shuffle_enabled if session else False
        valid_tracks = [track for track in tracks if track.get("videoId")]
        if not valid_tracks:
            return {}
        if shuffle:
            return random.choice(valid_tracks)
        return valid_tracks[0]

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    async def _async_set_programmatic_volume(self, volume_percent: int) -> None:
        if not self.target_entity_id:
            raise HomeAssistantError("No target media player selected for volume control")
        await self.hass.services.async_call(
            "media_player",
            "volume_set",
            {
                "entity_id": self.target_entity_id,
                "volume_level": max(0, min(100, int(volume_percent))) / 100,
            },
            blocking=True,
        )

    def _extract_thumbnail(self, item: dict[str, Any]) -> str:
        thumbs = item.get("thumbnails") or []
        if thumbs and isinstance(thumbs, list):
            return thumbs[-1].get("url", "") or ""
        if isinstance(item.get("thumbnail"), dict):
            thumbs = item["thumbnail"].get("thumbnails") or []
            if thumbs:
                return thumbs[-1].get("url", "") or ""
        return ""

    def _extract_artists(self, item: dict[str, Any]) -> str:
        if isinstance(item.get("artist"), str):
            return item["artist"]
        artists = item.get("artists") or []
        if isinstance(artists, list):
            return ", ".join(artist.get("name", "") for artist in artists if artist.get("name"))
        return ""

    def _normalize_playlist_id(self, playlist_id: str) -> str:
        if playlist_id.startswith("VL"):
            return playlist_id[2:]
        return playlist_id

    def _build_playlist_url(self, playlist_id: str) -> str:
        normalized = self._normalize_playlist_id(playlist_id)
        if normalized.startswith(("PL", "RD", "LM", "OLAK")):
            return f"https://music.youtube.com/playlist?list={normalized}"
        return f"https://music.youtube.com/browse/{playlist_id}"

    def _build_artist_url(self, artist_id: str) -> str:
        if artist_id.startswith("UC"):
            return f"https://music.youtube.com/channel/{artist_id}"
        return f"https://music.youtube.com/browse/{artist_id}"

    def _primary_target_state_object(self):
        target = self.target_entity_id
        if not target:
            return None
        return self.hass.states.get(target)

    def _primary_target_state_attr(self, key: str) -> Any:
        state = self._primary_target_state_object()
        if not state:
            return None
        return state.attributes.get(key)

    def _should_reset_position_on_idle(self) -> bool:
        session = self.primary_session
        if not session or not session._current_item:
            return False
        if session._should_continue_after_track():
            return False
        target_state = self.target_state
        return target_state in {MediaPlayerState.IDLE, MediaPlayerState.OFF}

    def _resolve_programmatic_item(self, payload: dict[str, Any]) -> tuple[str, str] | None:
        if payload.get("song_id"):
            return ITEM_TYPE_SONG, str(payload["song_id"])
        if payload.get("playlist_id"):
            return ITEM_TYPE_PLAYLIST, str(payload["playlist_id"])
        if payload.get("artist_id"):
            return ITEM_TYPE_ARTIST, str(payload["artist_id"])
        if payload.get("item_type") and payload.get("item_id"):
            return str(payload["item_type"]), str(payload["item_id"])
        if payload.get("youtube_url"):
            return self._parse_youtube_music_url(str(payload["youtube_url"]))
        return None

    def _parse_youtube_music_url(self, url: str) -> tuple[str, str]:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if query.get("list"):
            return ITEM_TYPE_PLAYLIST, query["list"][0]
        if query.get("v"):
            return ITEM_TYPE_SONG, query["v"][0]
        path = parsed.path.strip("/")
        if path.startswith("channel/"):
            return ITEM_TYPE_ARTIST, path.split("/", 1)[1]
        if path.startswith("browse/"):
            browse_id = path.split("/", 1)[1]
            if browse_id.startswith(("VL", "PL", "RD", "LM")):
                return ITEM_TYPE_PLAYLIST, browse_id
            return ITEM_TYPE_ARTIST, browse_id
        raise HomeAssistantError(f"Unsupported YouTube Music URL: {url}")
