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
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.network import get_url

from .const import (
    ATTR_LIMIT,
    ATTR_PROXY_URL,
    ATTR_QUERY,
    ATTR_RESULTS,
    ATTR_SEARCH_TYPE,
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
    """Owns API access, current state and cached search results."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        self._api: YoutubeMusicApiClient | None = None
        self._listeners: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()
        self._target_entity_id: str = entry.options.get(
            CONF_DEFAULT_TARGET_MEDIA_PLAYER,
            entry.data.get(CONF_DEFAULT_TARGET_MEDIA_PLAYER, ""),
        )
        self._last_search_payload: dict[str, Any] = {
            ATTR_QUERY: "",
            ATTR_SEARCH_TYPE: SEARCH_TYPE_ALL,
            ATTR_LIMIT: DEFAULT_LIMIT,
            ATTR_RESULTS: [],
            "count": 0,
        }
        self._search_index: dict[tuple[str, str], dict[str, Any]] = {}
        self._current_item: dict[str, Any] = {}
        self._current_resolved: ResolvedPlayback | None = None
        self._current_playback_target_entity_id: str = ""
        self._last_error: str = ""
        self._entity_id: str = ""
        self._autoplay_enabled = False
        self._autoplay_queue: list[dict[str, Any]] = []
        self._autoplay_context: dict[str, Any] = {}
        self._advancing_autoplay = False
        self._suppress_next_autoplay_once = False
        self._target_listener_unsub: Callable[[], None] | None = None
        self._shuffle_enabled = False
        self._repeat_mode = REPEAT_MODE_OFF
        self._playback_history: list[ResolvedPlayback] = []
        self._group_targets: list[str] = []
        self._exclude_devices: set[str] = set(
            entry.options.get(CONF_EXCLUDE_DEVICES, entry.data.get(CONF_EXCLUDE_DEVICES, []))
        )

    @property
    def name(self) -> str:
        return self.entry.title or self.entry.data.get(CONF_NAME, "YouTube Music")

    @property
    def state(self) -> str:
        target_state = self.target_state
        if target_state in {MediaPlayerState.PLAYING, MediaPlayerState.PAUSED, MediaPlayerState.IDLE}:
            return target_state
        if self._current_item:
            return MediaPlayerState.IDLE
        return MediaPlayerState.OFF

    @property
    def target_entity_id(self) -> str:
        return self._target_entity_id

    @property
    def group_targets(self) -> list[str]:
        return list(self._group_targets)

    @property
    def entity_id(self) -> str:
        return self._entity_id

    @property
    def target_state(self) -> str | None:
        if not self._target_entity_id:
            return None
        state = self.hass.states.get(self._target_entity_id)
        return state.state if state else None

    @property
    def current_item(self) -> dict[str, Any]:
        return deepcopy(self._current_item)

    @property
    def search_payload(self) -> dict[str, Any]:
        return deepcopy(self._last_search_payload)

    @property
    def last_error(self) -> str:
        return self._last_error

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
        if not self._current_item:
            return None
        item_type = self._current_item.get("type")
        if item_type == ITEM_TYPE_PLAYLIST:
            return self._current_item.get("playlist_name") or self._current_item.get("artist")
        if item_type == ITEM_TYPE_ARTIST:
            return self._current_item.get("artist")
        return self._current_item.get("title") or self._current_item.get("artist")

    @property
    def media_artist(self) -> str | None:
        if not self._current_item:
            return None
        item_type = self._current_item.get("type")
        if item_type == ITEM_TYPE_ARTIST:
            return None
        return self._current_item.get("artist") or None

    @property
    def media_image_url(self) -> str | None:
        return self._current_item.get("image_url") or None

    @property
    def media_duration(self) -> float | None:
        duration = self._target_state_attr("media_duration")
        return float(duration) if isinstance(duration, (int, float)) else None

    @property
    def media_position(self) -> float | None:
        if self._should_reset_position_on_idle():
            return 0.0
        position = self._target_state_attr("media_position")
        return float(position) if isinstance(position, (int, float)) else None

    @property
    def media_position_updated_at(self) -> datetime | None:
        updated_at = self._target_state_attr("media_position_updated_at")
        return updated_at if isinstance(updated_at, datetime) else None

    @property
    def target_supports_seek(self) -> bool:
        state = self._target_state_object()
        if not state:
            return False
        supported = int(state.attributes.get("supported_features", 0))
        return bool(supported & MediaPlayerEntityFeature.SEEK)

    @property
    def has_next_track(self) -> bool:
        return bool(self._autoplay_queue) or self._autoplay_enabled

    @property
    def has_previous_track(self) -> bool:
        return bool(self._playback_history)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = {
            "search_results": self._last_search_payload.get(ATTR_RESULTS, []),
            "search_query": self._last_search_payload.get(ATTR_QUERY, ""),
            "search_type": self._last_search_payload.get(ATTR_SEARCH_TYPE, SEARCH_TYPE_ALL),
            "search_count": self._last_search_payload.get("count", 0),
            "target_entity_id": self._target_entity_id,
            "available_target_players": self.source_list,
            "current_item": self._current_item,
            "last_error": self._last_error,
            "is_youtube_music_connector": True,
            "autoplay_enabled": self._autoplay_enabled,
            "autoplay_queue_length": len(self._autoplay_queue),
            "shuffle_enabled": self._shuffle_enabled,
            "repeat_mode": self._repeat_mode,
            "has_next_track": self.has_next_track,
            "has_previous_track": self.has_previous_track,
            "group_targets": list(self._group_targets),
        }
        if self._current_resolved:
            attrs["resolved_stream"] = {
                "playable_id": self._current_resolved.playable_id,
                ATTR_PROXY_URL: self._current_resolved.proxy_url,
            }
        return attrs

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def async_notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    async def async_setup(self) -> None:
        try:
            await self.async_ensure_api()
            await self._async_rebind_target_listener()
            self._last_error = ""
        except Exception as err:
            self._last_error = str(err)
            self.async_notify()
            raise

    async def async_set_target(self, entity_id: str) -> None:
        if entity_id in self._exclude_devices:
            raise HomeAssistantError(f"Device {entity_id} is excluded from playback")
        previous_target = self._target_entity_id
        if previous_target and previous_target != entity_id:
            if self._should_pause_previous_target_on_switch(previous_target):
                await self.hass.services.async_call(
                    "media_player",
                    "media_pause",
                    {"entity_id": previous_target},
                    blocking=True,
                )
        self._target_entity_id = entity_id
        if entity_id in self._group_targets:
            self._group_targets.remove(entity_id)
        await self._async_rebind_target_listener()
        self.async_notify()

    async def async_set_group_targets(self, targets: list[str]) -> dict[str, Any]:
        self._group_targets = [t for t in targets if t != self._target_entity_id and t not in self._exclude_devices]
        self.async_notify()
        return {"group_targets": list(self._group_targets)}

    async def _async_mirror_to_group(self, domain: str, service: str, data: dict[str, Any]) -> None:
        if not self._group_targets:
            return
        tasks = []
        for target in self._group_targets:
            call_data = dict(data)
            call_data["entity_id"] = target
            tasks.append(
                self.hass.services.async_call(domain, service, call_data, blocking=True)
            )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for target, result in zip(self._group_targets, results):
            if isinstance(result, Exception):
                _LOGGER.warning("Mirror %s.%s to %s failed: %s", domain, service, target, result)

    async def _async_mirror_playback_to_group(self, resolved: ResolvedPlayback) -> None:
        if not self._group_targets:
            return
        tasks = [
            self._async_start_resolved_playback_on(resolved, target)
            for target in self._group_targets
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for target, result in zip(self._group_targets, results):
            if isinstance(result, Exception):
                _LOGGER.warning("Mirror playback to %s failed: %s", target, result)

    def _should_pause_previous_target_on_switch(self, previous_target: str) -> bool:
        if not previous_target or previous_target != self._current_playback_target_entity_id:
            return False
        if not self._current_resolved:
            return False
        previous_state = self.hass.states.get(previous_target)
        if not previous_state or previous_state.state != MediaPlayerState.PLAYING:
            return False
        return previous_state.attributes.get("media_content_id") == self._current_resolved.proxy_url

    async def async_set_entity_id(self, entity_id: str) -> None:
        self._entity_id = entity_id
        self.async_notify()

    async def async_set_autoplay(self, enabled: bool) -> dict[str, Any]:
        self._autoplay_enabled = bool(enabled)
        if not self._should_continue_after_track():
            self._autoplay_queue = []
            self._autoplay_context = {}
        elif self._current_resolved:
            await self._async_prepare_autoplay_context(
                self._current_resolved.item_type,
                self._current_resolved.item_id,
                self._current_resolved.playable_id,
            )
        self.async_notify()
        return {"enabled": self._autoplay_enabled, "queue_length": len(self._autoplay_queue)}

    async def async_set_shuffle(self, enabled: bool) -> dict[str, Any]:
        self._shuffle_enabled = bool(enabled)
        if self._current_resolved and self._should_continue_after_track():
            await self._async_refresh_autoplay_queue(self._current_resolved.playable_id, force=True)
        elif self._autoplay_queue:
            self._shuffle_queue_in_place()
        self.async_notify()
        return {"shuffle_enabled": self._shuffle_enabled}

    async def async_set_repeat_mode(self, repeat_mode: str) -> dict[str, Any]:
        self._repeat_mode = normalize_repeat_mode(repeat_mode)
        if not self._should_continue_after_track():
            self._autoplay_queue = []
            self._autoplay_context = {}
        elif self._current_resolved:
            await self._async_prepare_autoplay_context(
                self._current_resolved.item_type,
                self._current_resolved.item_id,
                self._current_resolved.playable_id,
            )
        self.async_notify()
        return {"repeat_mode": self._repeat_mode}

    async def async_next_track(self) -> dict[str, Any]:
        """Skip to the next track in the autoplay queue."""
        if not self._target_entity_id:
            raise HomeAssistantError("No target media player selected")
        next_item = await self._async_pop_next_autoplay_track()
        if not next_item:
            raise HomeAssistantError("No next track available")
        video_id = next_item.get("videoId")
        if not video_id:
            raise HomeAssistantError("Next track has no video ID")
        resolved = await self._async_resolve_playback(ITEM_TYPE_SONG, video_id)
        resolved = ResolvedPlayback(
            item_type=ITEM_TYPE_SONG,
            item_id=video_id,
            playable_id=resolved.playable_id,
            title=next_item.get("title") or resolved.title,
            artist=self._extract_artists(next_item) or resolved.artist,
            image_url=self._extract_thumbnail(next_item) or resolved.image_url,
            url=f"https://music.youtube.com/watch?v={video_id}",
            stream_url=resolved.stream_url,
            proxy_url=self._build_proxy_url(resolved.playable_id, ITEM_TYPE_SONG, video_id),
        )
        await self._async_start_resolved_playback(resolved)
        await self._async_refresh_autoplay_queue(resolved.playable_id)
        self._last_error = ""
        self.async_notify()
        return {"title": resolved.title, "artist": resolved.artist}

    async def async_previous_track(self) -> dict[str, Any]:
        """Go back to the previous track, or restart the current one."""
        if not self._target_entity_id:
            raise HomeAssistantError("No target media player selected")
        if self._playback_history:
            previous = self._playback_history.pop()
            await self._async_start_resolved_playback(previous)
            self._last_error = ""
            self.async_notify()
            return {"title": previous.title, "artist": previous.artist}
        await self.async_media_seek(0)
        return {"action": "restarted"}

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

        response: dict[str, Any] = {
            "selected": selected_item,
            "search": search_payload,
            "autoplay_enabled": self._autoplay_enabled,
            "shuffle_enabled": self._shuffle_enabled,
            "repeat_mode": self._repeat_mode,
            "target_entity_id": self._target_entity_id,
        }

        if selected_item is None:
            return response

        if should_play:
            play_result = await self.async_play(
                self._target_entity_id,
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

    async def async_play(self, target_entity_id: str, item_type: str, item_id: str) -> dict[str, Any]:
        if target_entity_id:
            await self.async_set_target(target_entity_id)
        if not self._target_entity_id:
            raise HomeAssistantError("No target media player selected")

        try:
            resolved = await self._async_resolve_playback(item_type, item_id)
            await self._async_start_resolved_playback(resolved)
            await self._async_prepare_autoplay_context(item_type, item_id, resolved.playable_id)
            self._last_error = ""
            self.async_notify()
            return {
                "target_entity_id": self._target_entity_id,
                "resolved": {
                    "item_type": resolved.item_type,
                    "item_id": resolved.item_id,
                    "playable_id": resolved.playable_id,
                    "title": resolved.title,
                    "artist": resolved.artist,
                    "image_url": resolved.image_url,
                    "url": resolved.url,
                    "stream_url": resolved.stream_url,
                    ATTR_PROXY_URL: resolved.proxy_url,
                },
            }
        except Exception as err:
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
            self._target_entity_id = target_entity_id
            await self._async_rebind_target_listener()
        if not self._target_entity_id:
            raise HomeAssistantError("No target media player selected")
        self._suppress_next_autoplay_once = True
        await self.async_media_stop()
        self._last_error = ""
        self.async_notify()
        return {"target_entity_id": self._target_entity_id, "stopped": True}

    async def _async_start_resolved_playback_on(self, resolved: ResolvedPlayback, target_entity_id: str) -> None:
        """Start playback on a specific target without updating manager state."""
        media_types = self._playback_media_types_for(resolved.item_type)
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

    async def _async_start_resolved_playback(self, resolved: ResolvedPlayback) -> None:
        media_types = self._playback_media_types_for(resolved.item_type)
        last_error: Exception | None = None
        for media_type in media_types:
            try:
                await self.hass.services.async_call(
                    "media_player",
                    "play_media",
                    {
                        "entity_id": self._target_entity_id,
                        "media_content_id": resolved.proxy_url,
                        "media_content_type": media_type,
                        "enqueue": "replace",
                    },
                    blocking=True,
                )
                last_error = None
                break
            except Exception as err:
                last_error = err
                _LOGGER.debug(
                    "play_media failed for %s on %s with media type %s: %s",
                    resolved.item_id,
                    self._target_entity_id,
                    media_type,
                    err,
                )
        if last_error is not None:
            raise last_error
        if self._current_resolved and self._current_resolved.item_id != resolved.item_id:
            self._playback_history.append(self._current_resolved)
            if len(self._playback_history) > 20:
                self._playback_history = self._playback_history[-20:]
        self._current_resolved = resolved
        self._current_playback_target_entity_id = self._target_entity_id
        self._current_item = {
            "type": resolved.item_type,
            "id": resolved.item_id,
            "artist": resolved.artist,
            "title": resolved.title if resolved.item_type == ITEM_TYPE_SONG else "",
            "playlist_name": resolved.title if resolved.item_type == ITEM_TYPE_PLAYLIST else "",
            "image_url": resolved.image_url,
            "url": resolved.url,
            "proxy_url": resolved.proxy_url,
        }
        await self._async_mirror_playback_to_group(resolved)

    def _playback_media_types_for(self, item_type: str) -> list[str]:
        primary = str(MEDIA_TYPE_MAP.get(item_type, "music"))
        target_preferences = self._target_playback_media_type_preferences()
        ordered = [*target_preferences, primary, "music", "audio/mpeg", "audio", "video", "url"]
        seen: set[str] = set()
        return [media_type for media_type in ordered if not (media_type in seen or seen.add(media_type))]

    def _target_playback_media_type_preferences(self) -> list[str]:
        target_state = self._target_state_object()
        device_class = str(target_state.attributes.get("device_class", "")).lower() if target_state else ""
        if device_class == "speaker":
            return ["music"]
        if device_class == "tv":
            return ["video", "music"]

        registry = er.async_get(self.hass)
        entry = registry.async_get(self._target_entity_id) if self._target_entity_id else None
        original_device_class = str(entry.original_device_class or "").lower() if entry else ""
        if original_device_class == "speaker":
            return ["music"]
        if original_device_class == "tv":
            return ["video", "music"]

        haystack = " ".join(
            part for part in [
                self._target_entity_id or "",
                str(target_state.attributes.get("friendly_name", "")) if target_state else "",
                str(target_state.attributes.get("app_name", "")) if target_state else "",
                str(target_state.attributes.get("source", "")) if target_state else "",
            ] if part
        ).lower()
        if any(token in haystack for token in ("tv", "chromecast_tv", "projector", "display", "monitor", "cinema")):
            return ["video", "music"]
        return ["music", "video"]

    async def _async_prepare_autoplay_context(self, item_type: str, item_id: str, playable_id: str) -> None:
        if not self._should_continue_after_track():
            self._autoplay_queue = []
            self._autoplay_context = {}
            return

        api = await self.async_ensure_api()
        queue: list[dict[str, Any]] = []
        context: dict[str, Any] = {
            "source_type": item_type,
            "source_id": item_id,
        }

        if item_type == ITEM_TYPE_PLAYLIST:
            playlist_id = self._normalize_playlist_id(item_id)
            browse_id = self._search_index.get((item_type, item_id), {}).get("browse_id")
            playlist = await api.async_get_playlist(playlist_id, limit=25, browse_id=browse_id)
            tracks = playlist.get("tracks") or []
            queue = [track for track in tracks if track.get("videoId") and track.get("videoId") != playable_id]
            context["playlist_id"] = playlist_id
            if browse_id:
                context["playlist_browse_id"] = browse_id
        else:
            queue = await api.async_get_up_next(playable_id, limit=12)

        self._autoplay_context = context
        self._autoplay_queue = self._apply_queue_modes(queue)

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
        if (
            self._current_resolved
            and self._current_resolved.item_type == item_type
            and self._current_resolved.item_id == item_id
            and (playable_id is None or self._current_resolved.playable_id == playable_id)
        ):
            return self._current_resolved.stream_url
        resolved = await self._async_resolve_playback(item_type, item_id)
        self._current_resolved = resolved
        self.async_notify()
        return resolved.stream_url

    async def async_media_pause(self) -> None:
        if not self._target_entity_id:
            return

        await self.hass.services.async_call(
            "media_player",
            "media_pause",
            {"entity_id": self._target_entity_id},
            blocking=True,
        )

        await asyncio.sleep(0.2)
        target_state = self.target_state
        if target_state != MediaPlayerState.PLAYING:
            await self._async_mirror_to_group("media_player", "media_pause", {})
            self.async_notify()
            return

        await self.hass.services.async_call(
            "media_player",
            "media_play_pause",
            {"entity_id": self._target_entity_id},
            blocking=True,
        )
        await self._async_mirror_to_group("media_player", "media_pause", {})
        self.async_notify()

    async def async_media_play(self) -> None:
        if not self._target_entity_id:
            return

        target_state = self._target_state_object()
        target_media_id = target_state.attributes.get("media_content_id") if target_state else None

        # If a track is already selected but the newly selected target is not holding
        # that media item, start the known item on the selected target instead of
        # sending a plain resume command that would no-op on many players.
        if self._current_resolved and (
            self._current_playback_target_entity_id != self._target_entity_id
            or
            target_state is None
            or target_state.state not in {MediaPlayerState.PLAYING, MediaPlayerState.PAUSED}
            or target_media_id != self._current_resolved.proxy_url
        ):
            await self._async_start_resolved_playback(self._current_resolved)
            self._last_error = ""
            self.async_notify()
            return

        await self.hass.services.async_call(
            "media_player",
            "media_play",
            {"entity_id": self._target_entity_id},
            blocking=True,
        )
        await self._async_mirror_to_group("media_player", "media_play", {})

    async def async_media_stop(self) -> None:
        if self._target_entity_id:
            await self.hass.services.async_call(
                "media_player",
                "media_stop",
                {"entity_id": self._target_entity_id},
                blocking=True,
            )
            await self._async_mirror_to_group("media_player", "media_stop", {})

    async def async_media_seek(self, position: float) -> None:
        if self._target_entity_id:
            await self.hass.services.async_call(
                "media_player",
                "media_seek",
                {
                    "entity_id": self._target_entity_id,
                    "seek_position": max(0.0, float(position)),
                },
                blocking=True,
            )
            self.async_notify()

    async def _async_rebind_target_listener(self) -> None:
        if self._target_listener_unsub:
            self._target_listener_unsub()
            self._target_listener_unsub = None

        if not self._target_entity_id:
            return

        self._target_listener_unsub = async_track_state_change_event(
            self.hass,
            [self._target_entity_id],
            self._async_handle_target_state_change,
        )

    async def _async_handle_target_state_change(self, event: Event) -> None:
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if not old_state or not new_state:
            return
        self.async_notify()
        if old_state.state != MediaPlayerState.PLAYING:
            return
        if new_state.state not in {MediaPlayerState.IDLE, MediaPlayerState.OFF}:
            return

        if self._suppress_next_autoplay_once:
            self._suppress_next_autoplay_once = False
            return

        if not self._should_continue_after_track() or self._advancing_autoplay:
            return

        self.hass.async_create_task(self._async_advance_autoplay())

    async def _async_advance_autoplay(self) -> None:
        if not self._should_continue_after_track() or not self._target_entity_id:
            return
        self._advancing_autoplay = True
        try:
            if self._repeat_mode == REPEAT_MODE_ONCE and self._current_resolved:
                self._repeat_mode = REPEAT_MODE_OFF
                await self._async_start_resolved_playback(self._current_resolved)
                self._last_error = ""
                self.async_notify()
                return

            next_track = await self._async_pop_next_autoplay_track()
            if not next_track:
                return
            video_id = next_track.get("videoId")
            if not video_id:
                return

            resolved = await self._async_resolve_playback(ITEM_TYPE_SONG, video_id)
            resolved = ResolvedPlayback(
                item_type=ITEM_TYPE_SONG,
                item_id=video_id,
                playable_id=resolved.playable_id,
                title=next_track.get("title") or resolved.title,
                artist=self._extract_artists(next_track) or resolved.artist,
                image_url=self._extract_thumbnail(next_track) or resolved.image_url,
                url=f"https://music.youtube.com/watch?v={video_id}",
                stream_url=resolved.stream_url,
                proxy_url=self._build_proxy_url(resolved.playable_id, ITEM_TYPE_SONG, video_id),
            )
            await self._async_start_resolved_playback(resolved)
            await self._async_refresh_autoplay_queue(resolved.playable_id)
            self._last_error = ""
            self.async_notify()
        except Exception as err:
            self._last_error = f"Autoplay failed: {err}"
            self.async_notify()
            _LOGGER.exception("Autoplay advance failed")
        finally:
            self._advancing_autoplay = False

    async def _async_pop_next_autoplay_track(self) -> dict[str, Any] | None:
        if self._autoplay_queue:
            return self._autoplay_queue.pop(0)
        if self._current_resolved:
            await self._async_refresh_autoplay_queue(self._current_resolved.playable_id)
        if self._autoplay_queue:
            return self._autoplay_queue.pop(0)
        return None

    async def _async_refresh_autoplay_queue(self, current_video_id: str, force: bool = False) -> None:
        if not self._should_continue_after_track():
            self._autoplay_queue = []
            return
        api = await self.async_ensure_api()
        source_type = self._autoplay_context.get("source_type")
        if source_type == ITEM_TYPE_PLAYLIST and self._autoplay_context.get("playlist_id"):
            if force or not self._autoplay_queue:
                playlist = await api.async_get_playlist(
                    self._autoplay_context["playlist_id"],
                    limit=25,
                    browse_id=self._autoplay_context.get("playlist_browse_id"),
                )
                tracks = playlist.get("tracks") or []
                queue = [
                    track for track in tracks if track.get("videoId") and track.get("videoId") != current_video_id
                ]
                self._autoplay_queue = self._apply_queue_modes(queue)
            return
        queue = await api.async_get_up_next(current_video_id, limit=12)
        if not queue and self._repeat_mode == REPEAT_MODE_FOREVER and current_video_id:
            queue = await api.async_get_up_next(current_video_id, limit=12)
        self._autoplay_queue = self._apply_queue_modes(queue)

    def _apply_queue_modes(self, queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
        queue = list(queue)
        if self._shuffle_enabled and len(queue) > 1:
            random.shuffle(queue)
        return queue

    def _pick_initial_track(self, tracks: list[dict[str, Any]]) -> dict[str, Any]:
        valid_tracks = [track for track in tracks if track.get("videoId")]
        if not valid_tracks:
            return {}
        if self._shuffle_enabled:
            return random.choice(valid_tracks)
        return valid_tracks[0]

    def _shuffle_queue_in_place(self) -> None:
        if self._shuffle_enabled and len(self._autoplay_queue) > 1:
            random.shuffle(self._autoplay_queue)

    def _should_continue_after_track(self) -> bool:
        return self._autoplay_enabled or self._repeat_mode in {REPEAT_MODE_FOREVER, REPEAT_MODE_ONCE}

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

    async def _async_set_programmatic_volume(self, volume_percent: int) -> None:
        if not self._target_entity_id:
            raise HomeAssistantError("No target media player selected for volume control")
        await self.hass.services.async_call(
            "media_player",
            "volume_set",
            {
                "entity_id": self._target_entity_id,
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

    def _target_state_object(self):
        if not self._target_entity_id:
            return None
        return self.hass.states.get(self._target_entity_id)

    def _should_reset_position_on_idle(self) -> bool:
        if not self._current_item or self._should_continue_after_track():
            return False
        target_state = self.target_state
        return target_state in {MediaPlayerState.IDLE, MediaPlayerState.OFF}

    def _target_state_attr(self, key: str) -> Any:
        state = self._target_state_object()
        if not state:
            return None
        return state.attributes.get(key)
