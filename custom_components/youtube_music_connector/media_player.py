"""Media player entity for youtube_music_connector."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import MediaPlayerEntityFeature, MediaType

from .const import ITEM_TYPE_ARTIST, ITEM_TYPE_PLAYLIST, ITEM_TYPE_SONG
from .manager import YoutubeMusicConnectorManager


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up the media player from a config entry."""
    manager: YoutubeMusicConnectorManager = hass.data["youtube_music_connector"][entry.entry_id]
    async_add_entities([YoutubeMusicConnectorMediaPlayer(manager)], update_before_add=True)


class YoutubeMusicConnectorMediaPlayer(MediaPlayerEntity):
    """Media player facade for the connector."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:youtube-music"
    def __init__(self, manager: YoutubeMusicConnectorManager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{manager.entry.entry_id}_player"
        self._attr_name = manager.entry.data.get("name", "youtube_music_connector")
        self._unsubscribe = None

    async def async_added_to_hass(self) -> None:
        await self._manager.async_set_entity_id(self.entity_id)
        self._unsubscribe = self._manager.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()

    @property
    def state(self):
        return self._manager.state

    @property
    def source(self):
        return self._manager.target_entity_id

    @property
    def source_list(self):
        return self._manager.source_list

    @property
    def media_title(self):
        return self._manager.media_title

    @property
    def media_artist(self):
        return self._manager.media_artist

    @property
    def media_image_url(self):
        return self._manager.media_image_url

    @property
    def media_duration(self):
        return self._manager.media_duration

    @property
    def media_position(self):
        return self._manager.media_position

    @property
    def media_position_updated_at(self):
        return self._manager.media_position_updated_at

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        supported = (
            MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.SELECT_SOURCE
            | MediaPlayerEntityFeature.PLAY_MEDIA
        )
        if self._manager.target_supports_seek:
            supported |= MediaPlayerEntityFeature.SEEK
        if self._manager.has_next_track:
            supported |= MediaPlayerEntityFeature.NEXT_TRACK
        if self._manager.has_previous_track:
            supported |= MediaPlayerEntityFeature.PREVIOUS_TRACK
        return supported

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._manager.extra_state_attributes

    async def async_select_source(self, source: str) -> None:
        await self._manager.async_set_selected_devices([source])

    async def async_media_pause(self) -> None:
        await self._manager.async_media_pause()

    async def async_media_play(self) -> None:
        await self._manager.async_media_play()

    async def async_media_stop(self) -> None:
        await self._manager.async_media_stop()

    async def async_media_seek(self, position: float) -> None:
        await self._manager.async_media_seek(position)

    async def async_media_next_track(self) -> None:
        await self._manager.async_next_track()

    async def async_media_previous_track(self) -> None:
        await self._manager.async_previous_track()

    async def async_play_media(self, media_type: MediaType | str, media_id: str, **kwargs: Any) -> None:
        item_type = kwargs.get("item_type")
        if not item_type:
            if media_type in {MediaType.PLAYLIST, "playlist"}:
                item_type = ITEM_TYPE_PLAYLIST
            elif media_type in {MediaType.ARTIST, "artist"}:
                item_type = ITEM_TYPE_ARTIST
            else:
                item_type = ITEM_TYPE_SONG
        await self._manager.async_play(
            kwargs.get("target_entity_id") or self._manager.target_entity_id,
            item_type,
            media_id,
        )
