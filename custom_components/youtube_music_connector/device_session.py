"""Per-device playback session for youtube_music_connector."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.components.media_player.const import MediaPlayerState
from homeassistant.core import Event
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ITEM_TYPE_SONG,
    REPEAT_MODE_FOREVER,
    REPEAT_MODE_OFF,
    REPEAT_MODE_ONCE,
    normalize_repeat_mode,
)

if TYPE_CHECKING:
    from .manager import ResolvedPlayback, YoutubeMusicConnectorManager

_LOGGER = logging.getLogger(__name__)


class DeviceSession:
    """Owns per-device playback state for a single target media_player entity."""

    def __init__(self, manager: YoutubeMusicConnectorManager, entity_id: str) -> None:
        self._manager = manager
        self.entity_id = entity_id

        self._current_resolved: ResolvedPlayback | None = None
        self._current_item: dict[str, Any] = {}
        self._current_playback_target_entity_id: str = ""
        self._autoplay_enabled = False
        self._autoplay_queue: list[dict[str, Any]] = []
        self._autoplay_context: dict[str, Any] = {}
        self._advancing_autoplay = False
        self._suppress_next_autoplay_once = False
        self._shuffle_enabled = False
        self._repeat_mode = REPEAT_MODE_OFF
        self._playback_history: list[ResolvedPlayback] = []
        self._target_listener_unsub: Callable[[], None] | None = None
        self._last_error: str = ""

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def current_item(self) -> dict[str, Any]:
        from copy import deepcopy
        return deepcopy(self._current_item)

    @property
    def current_resolved(self) -> ResolvedPlayback | None:
        return self._current_resolved

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def autoplay_enabled(self) -> bool:
        return self._autoplay_enabled

    @property
    def shuffle_enabled(self) -> bool:
        return self._shuffle_enabled

    @property
    def repeat_mode(self) -> str:
        return self._repeat_mode

    @property
    def autoplay_queue_length(self) -> int:
        return len(self._autoplay_queue)

    @property
    def has_next_track(self) -> bool:
        return bool(self._autoplay_queue) or self._autoplay_enabled

    @property
    def has_previous_track(self) -> bool:
        return bool(self._playback_history)

    @property
    def state(self) -> str | None:
        """Return the media player state of the target device."""
        if not self.entity_id:
            return None
        state = self._manager.hass.states.get(self.entity_id)
        return state.state if state else None

    @property
    def media_title(self) -> str | None:
        from .const import ITEM_TYPE_ARTIST, ITEM_TYPE_PLAYLIST
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
        from .const import ITEM_TYPE_ARTIST
        if not self._current_item:
            return None
        item_type = self._current_item.get("type")
        if item_type == ITEM_TYPE_ARTIST:
            return None
        return self._current_item.get("artist") or None

    @property
    def media_image_url(self) -> str | None:
        return self._current_item.get("image_url") or None

    def summary_dict(self) -> dict[str, Any]:
        """Return a summary dict for use in extra_state_attributes."""
        return {
            "entity_id": self.entity_id,
            "state": self.state,
            "current_item": self._current_item,
            "autoplay_enabled": self._autoplay_enabled,
            "autoplay_queue_length": len(self._autoplay_queue),
            "shuffle_enabled": self._shuffle_enabled,
            "repeat_mode": self._repeat_mode,
            "has_next_track": self.has_next_track,
            "has_previous_track": self.has_previous_track,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def async_bind(self) -> None:
        """Bind state listener for the target device."""
        await self._async_rebind_target_listener()

    def async_unbind(self) -> None:
        """Remove state listener."""
        if self._target_listener_unsub:
            self._target_listener_unsub()
            self._target_listener_unsub = None

    # ------------------------------------------------------------------
    # Playback commands
    # ------------------------------------------------------------------

    async def async_play(self, item_type: str, item_id: str) -> dict[str, Any]:
        """Resolve and start playback of item_type/item_id on this session's device."""
        resolved = await self._manager._async_resolve_playback(item_type, item_id)
        await self._async_start_resolved_playback(resolved)
        await self._async_prepare_autoplay_context(item_type, item_id, resolved.playable_id)
        self._last_error = ""
        self._manager.async_notify()
        return {
            "target_entity_id": self.entity_id,
            "resolved": {
                "item_type": resolved.item_type,
                "item_id": resolved.item_id,
                "playable_id": resolved.playable_id,
                "title": resolved.title,
                "artist": resolved.artist,
                "image_url": resolved.image_url,
                "url": resolved.url,
                "stream_url": resolved.stream_url,
                "proxy_url": resolved.proxy_url,
            },
        }

    async def async_stop(self) -> None:
        """Stop playback on this device."""
        self._suppress_next_autoplay_once = True
        await self.async_media_stop()

    async def async_next_track(self) -> dict[str, Any]:
        """Skip to the next track."""
        next_item = await self._async_pop_next_autoplay_track()
        if not next_item:
            raise HomeAssistantError("No next track available")
        video_id = next_item.get("videoId")
        if not video_id:
            raise HomeAssistantError("Next track has no video ID")
        resolved = await self._manager._async_resolve_playback(ITEM_TYPE_SONG, video_id)
        from .manager import ResolvedPlayback
        resolved = ResolvedPlayback(
            item_type=ITEM_TYPE_SONG,
            item_id=video_id,
            playable_id=resolved.playable_id,
            title=next_item.get("title") or resolved.title,
            artist=self._manager._extract_artists(next_item) or resolved.artist,
            image_url=self._manager._extract_thumbnail(next_item) or resolved.image_url,
            url=f"https://music.youtube.com/watch?v={video_id}",
            stream_url=resolved.stream_url,
            proxy_url=self._manager._build_proxy_url(resolved.playable_id, ITEM_TYPE_SONG, video_id),
        )
        await self._async_start_resolved_playback(resolved)
        await self._async_refresh_autoplay_queue(resolved.playable_id)
        self._last_error = ""
        self._manager.async_notify()
        return {"title": resolved.title, "artist": resolved.artist}

    async def async_previous_track(self) -> dict[str, Any]:
        """Go back to the previous track or restart current."""
        if self._playback_history:
            previous = self._playback_history.pop()
            await self._async_start_resolved_playback(previous)
            self._last_error = ""
            self._manager.async_notify()
            return {"title": previous.title, "artist": previous.artist}
        await self.async_media_seek(0)
        return {"action": "restarted"}

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
        self._manager.async_notify()
        return {"enabled": self._autoplay_enabled, "queue_length": len(self._autoplay_queue)}

    async def async_set_shuffle(self, enabled: bool) -> dict[str, Any]:
        self._shuffle_enabled = bool(enabled)
        if self._current_resolved and self._should_continue_after_track():
            await self._async_refresh_autoplay_queue(self._current_resolved.playable_id, force=True)
        elif self._autoplay_queue:
            self._shuffle_queue_in_place()
        self._manager.async_notify()
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
        self._manager.async_notify()
        return {"repeat_mode": self._repeat_mode}

    async def async_media_pause(self) -> None:
        if not self.entity_id:
            return
        hass = self._manager.hass
        await hass.services.async_call(
            "media_player",
            "media_pause",
            {"entity_id": self.entity_id},
            blocking=True,
        )
        await asyncio.sleep(0.2)
        device_state = self.state
        if device_state != MediaPlayerState.PLAYING:
            return
        await hass.services.async_call(
            "media_player",
            "media_play_pause",
            {"entity_id": self.entity_id},
            blocking=True,
        )

    async def async_media_play(self) -> None:
        if not self.entity_id:
            return
        hass = self._manager.hass
        target_state_obj = hass.states.get(self.entity_id)
        target_media_id = target_state_obj.attributes.get("media_content_id") if target_state_obj else None

        if self._current_resolved and (
            self._current_playback_target_entity_id != self.entity_id
            or target_state_obj is None
            or target_state_obj.state not in {MediaPlayerState.PLAYING, MediaPlayerState.PAUSED}
            or target_media_id != self._current_resolved.proxy_url
        ):
            await self._async_start_resolved_playback(self._current_resolved)
            self._last_error = ""
            self._manager.async_notify()
            return

        await hass.services.async_call(
            "media_player",
            "media_play",
            {"entity_id": self.entity_id},
            blocking=True,
        )

    async def async_media_stop(self) -> None:
        if self.entity_id:
            await self._manager.hass.services.async_call(
                "media_player",
                "media_stop",
                {"entity_id": self.entity_id},
                blocking=True,
            )

    async def async_media_seek(self, position: float) -> None:
        if self.entity_id:
            await self._manager.hass.services.async_call(
                "media_player",
                "media_seek",
                {
                    "entity_id": self.entity_id,
                    "seek_position": max(0.0, float(position)),
                },
                blocking=True,
            )
            self._manager.async_notify()

    # ------------------------------------------------------------------
    # Internal playback helpers
    # ------------------------------------------------------------------

    async def _async_start_resolved_playback(self, resolved: ResolvedPlayback) -> None:
        """Start playback on this session's device and update session state."""
        await self._manager._async_start_resolved_playback_on(resolved, self.entity_id)
        if self._current_resolved and self._current_resolved.item_id != resolved.item_id:
            self._playback_history.append(self._current_resolved)
            if len(self._playback_history) > 20:
                self._playback_history = self._playback_history[-20:]
        self._current_resolved = resolved
        self._current_playback_target_entity_id = self.entity_id
        from .const import ITEM_TYPE_PLAYLIST
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

    async def _async_rebind_target_listener(self) -> None:
        if self._target_listener_unsub:
            self._target_listener_unsub()
            self._target_listener_unsub = None
        if not self.entity_id:
            return
        self._target_listener_unsub = async_track_state_change_event(
            self._manager.hass,
            [self.entity_id],
            self._async_handle_target_state_change,
        )

    async def _async_handle_target_state_change(self, event: Event) -> None:
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if not old_state or not new_state:
            return
        self._manager.async_notify()
        if old_state.state != MediaPlayerState.PLAYING:
            return
        if new_state.state not in {MediaPlayerState.IDLE, MediaPlayerState.OFF}:
            return
        if self._suppress_next_autoplay_once:
            self._suppress_next_autoplay_once = False
            return
        if not self._should_continue_after_track() or self._advancing_autoplay:
            return
        self._manager.hass.async_create_task(self._async_advance_autoplay())

    async def _async_advance_autoplay(self) -> None:
        if not self._should_continue_after_track() or not self.entity_id:
            return
        self._advancing_autoplay = True
        try:
            if self._repeat_mode == REPEAT_MODE_ONCE and self._current_resolved:
                self._repeat_mode = REPEAT_MODE_OFF
                await self._async_start_resolved_playback(self._current_resolved)
                self._last_error = ""
                self._manager.async_notify()
                return

            next_track = await self._async_pop_next_autoplay_track()
            if not next_track:
                return
            video_id = next_track.get("videoId")
            if not video_id:
                return

            resolved = await self._manager._async_resolve_playback(ITEM_TYPE_SONG, video_id)
            from .manager import ResolvedPlayback
            resolved = ResolvedPlayback(
                item_type=ITEM_TYPE_SONG,
                item_id=video_id,
                playable_id=resolved.playable_id,
                title=next_track.get("title") or resolved.title,
                artist=self._manager._extract_artists(next_track) or resolved.artist,
                image_url=self._manager._extract_thumbnail(next_track) or resolved.image_url,
                url=f"https://music.youtube.com/watch?v={video_id}",
                stream_url=resolved.stream_url,
                proxy_url=self._manager._build_proxy_url(resolved.playable_id, ITEM_TYPE_SONG, video_id),
            )
            await self._async_start_resolved_playback(resolved)
            await self._async_refresh_autoplay_queue(resolved.playable_id)
            self._last_error = ""
            self._manager.async_notify()
        except Exception as err:
            self._last_error = f"Autoplay failed: {err}"
            self._manager.async_notify()
            _LOGGER.exception("Autoplay advance failed for session %s", self.entity_id)
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

    async def _async_prepare_autoplay_context(self, item_type: str, item_id: str, playable_id: str) -> None:
        if not self._should_continue_after_track():
            self._autoplay_queue = []
            self._autoplay_context = {}
            return
        from .const import ITEM_TYPE_PLAYLIST
        api = await self._manager.async_ensure_api()
        queue: list[dict[str, Any]] = []
        context: dict[str, Any] = {
            "source_type": item_type,
            "source_id": item_id,
        }
        if item_type == ITEM_TYPE_PLAYLIST:
            playlist_id = self._manager._normalize_playlist_id(item_id)
            browse_id = self._manager._search_index.get((item_type, item_id), {}).get("browse_id")
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

    async def _async_refresh_autoplay_queue(self, current_video_id: str, force: bool = False) -> None:
        if not self._should_continue_after_track():
            self._autoplay_queue = []
            return
        from .const import ITEM_TYPE_PLAYLIST
        api = await self._manager.async_ensure_api()
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
                    track for track in tracks
                    if track.get("videoId") and track.get("videoId") != current_video_id
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
