"""Initialize youtube_music_connector."""

from __future__ import annotations

import logging
from typing import Any
from pathlib import Path

import voluptuous as vol
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .auth_import import DEFAULT_IMPORT_FILENAME, parse_browser_auth_input, write_browser_auth_file
from .const import (
    ATTR_ENABLED,
    ATTR_ARTIST_ID,
    ATTR_ITEM_ID,
    ATTR_ITEM_TYPE,
    ATTR_LIMIT,
    ATTR_PLAY,
    ATTR_PLAYLIST_ID,
    ATTR_QUERY,
    ATTR_REPEAT_MODE,
    ATTR_SEARCH_TYPE,
    ATTR_SHUFFLE_ENABLED,
    ATTR_SONG_ID,
    ATTR_TARGET_ENTITY_ID,
    ATTR_VOLUME_PERCENT,
    ATTR_YOUTUBE_URL,
    ACCEPTED_REPEAT_MODES,
    DOMAIN,
    PLATFORMS,
    SEARCH_TYPE_ALL,
    SEARCH_TYPES,
    SERVICE_EXECUTE,
    SERVICE_PLAY,
    SERVICE_RESOLVE_STREAM,
    SERVICE_SEARCH,
    SERVICE_SET_REPEAT_MODE,
    SERVICE_SET_SHUFFLE,
    SERVICE_STOP,
    SERVICE_SET_AUTOPLAY,
)
from .manager import YoutubeMusicConnectorManager
from .panel import async_register_panel, async_unregister_panel

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    _log_runtime_diagnostics()
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    _log_runtime_diagnostics()
    manager = YoutubeMusicConnectorManager(hass, entry)
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[entry.entry_id] = manager
    await manager.async_setup()
    if not domain_data.get("views_registered"):
        hass.http.register_view(YoutubeMusicConnectorImportView(hass))
        domain_data["views_registered"] = True
    if not domain_data.get("proxy_view_registered"):
        hass.http.register_view(YoutubeMusicConnectorProxyView(hass))
        domain_data["proxy_view_registered"] = True
    await async_register_panel(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data = hass.data[DOMAIN]
        domain_data.pop(entry.entry_id, None)
        await async_unregister_panel(hass)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SEARCH):
        return

    async def search_service(call: ServiceCall) -> dict[str, Any]:
        manager = _manager_from_entity_id(hass, call.data["entity_id"])
        return await manager.async_search(
            call.data[ATTR_QUERY],
            call.data.get(ATTR_SEARCH_TYPE, SEARCH_TYPE_ALL),
            call.data.get(ATTR_LIMIT, 5),
        )

    async def resolve_stream_service(call: ServiceCall) -> dict[str, Any]:
        manager = _manager_from_entity_id(hass, call.data["entity_id"])
        return await manager.async_resolve_stream(call.data[ATTR_ITEM_TYPE], call.data[ATTR_ITEM_ID])

    async def play_service(call: ServiceCall) -> dict[str, Any]:
        manager = _manager_from_entity_id(hass, call.data["entity_id"])
        return await manager.async_play(
            call.data.get(ATTR_TARGET_ENTITY_ID, ""),
            call.data[ATTR_ITEM_TYPE],
            call.data[ATTR_ITEM_ID],
        )

    async def stop_service(call: ServiceCall) -> dict[str, Any]:
        manager = _manager_from_entity_id(hass, call.data["entity_id"])
        return await manager.async_stop(call.data.get(ATTR_TARGET_ENTITY_ID))

    async def set_autoplay_service(call: ServiceCall) -> dict[str, Any]:
        manager = _manager_from_entity_id(hass, call.data["entity_id"])
        return await manager.async_set_autoplay(call.data[ATTR_ENABLED])

    async def set_shuffle_service(call: ServiceCall) -> dict[str, Any]:
        manager = _manager_from_entity_id(hass, call.data["entity_id"])
        return await manager.async_set_shuffle(call.data[ATTR_SHUFFLE_ENABLED])

    async def set_repeat_mode_service(call: ServiceCall) -> dict[str, Any]:
        manager = _manager_from_entity_id(hass, call.data["entity_id"])
        return await manager.async_set_repeat_mode(call.data[ATTR_REPEAT_MODE])

    async def execute_service(call: ServiceCall) -> dict[str, Any]:
        manager = _manager_from_entity_id(hass, call.data["entity_id"])
        return await manager.async_execute(dict(call.data))

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEARCH,
        search_service,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Required(ATTR_QUERY): cv.string,
                vol.Optional(ATTR_SEARCH_TYPE, default=SEARCH_TYPE_ALL): vol.In(SEARCH_TYPES),
                vol.Optional(ATTR_LIMIT, default=5): vol.Coerce(int),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESOLVE_STREAM,
        resolve_stream_service,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Required(ATTR_ITEM_TYPE): cv.string,
                vol.Required(ATTR_ITEM_ID): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PLAY,
        play_service,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Optional(ATTR_TARGET_ENTITY_ID): cv.entity_id,
                vol.Required(ATTR_ITEM_TYPE): cv.string,
                vol.Required(ATTR_ITEM_ID): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP,
        stop_service,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Optional(ATTR_TARGET_ENTITY_ID): cv.entity_id,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_AUTOPLAY,
        set_autoplay_service,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Required(ATTR_ENABLED): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SHUFFLE,
        set_shuffle_service,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Required(ATTR_SHUFFLE_ENABLED): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_REPEAT_MODE,
        set_repeat_mode_service,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Required(ATTR_REPEAT_MODE): vol.In(ACCEPTED_REPEAT_MODES),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXECUTE,
        execute_service,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Optional(ATTR_TARGET_ENTITY_ID): cv.entity_id,
                vol.Optional(ATTR_QUERY): cv.string,
                vol.Optional(ATTR_SEARCH_TYPE, default=SEARCH_TYPE_ALL): vol.In(SEARCH_TYPES),
                vol.Optional(ATTR_LIMIT, default=5): vol.Coerce(int),
                vol.Optional(ATTR_PLAY, default=False): cv.boolean,
                vol.Optional(ATTR_ITEM_TYPE): cv.string,
                vol.Optional(ATTR_ITEM_ID): cv.string,
                vol.Optional(ATTR_SONG_ID): cv.string,
                vol.Optional(ATTR_PLAYLIST_ID): cv.string,
                vol.Optional(ATTR_ARTIST_ID): cv.string,
                vol.Optional(ATTR_YOUTUBE_URL): cv.string,
                vol.Optional("autoplay_enabled"): cv.boolean,
                vol.Optional(ATTR_SHUFFLE_ENABLED): cv.boolean,
                vol.Optional(ATTR_REPEAT_MODE): vol.In(ACCEPTED_REPEAT_MODES),
                vol.Optional(ATTR_VOLUME_PERCENT): vol.Coerce(int),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )


def _manager_from_entity_id(hass: HomeAssistant, entity_id: str) -> YoutubeMusicConnectorManager:
    managers = list(_manager_entries(hass).values())
    for manager in managers:
        if manager.entity_id == entity_id:
            return manager
    if len(managers) == 1:
        return managers[0]
    raise HomeAssistantError(f"No youtube_music_connector manager found for {entity_id}")


def _manager_entries(hass: HomeAssistant) -> dict[str, YoutubeMusicConnectorManager]:
    domain_data = hass.data.get(DOMAIN, {})
    return {
        entry_id: manager
        for entry_id, manager in domain_data.items()
        if isinstance(manager, YoutubeMusicConnectorManager)
    }


class YoutubeMusicConnectorProxyView(HomeAssistantView):
    """Serve proxied stream URLs."""

    url = "/api/youtube_music_connector/proxy/{entry_id}/{item_type}/{item_id}"
    name = "api:youtube_music_connector:proxy"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str, item_type: str, item_id: str) -> web.Response:
        manager: YoutubeMusicConnectorManager | None = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if manager is None:
            raise web.HTTPNotFound()
        playable_id = request.query.get("video_id")
        try:
            stream_url = await manager.async_get_proxy_stream_url(item_type, item_id, playable_id)
        except Exception as err:
            _LOGGER.exception("Failed to resolve proxied stream")
            raise web.HTTPBadGateway(text=str(err)) from err
        raise web.HTTPFound(location=stream_url)


class YoutubeMusicConnectorImportView(HomeAssistantView):
    """Import browser auth text and store it as browser.json."""

    url = "/api/youtube_music_connector/import_browser_auth"
    name = "api:youtube_music_connector:import_browser_auth"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception as err:
            raise web.HTTPBadRequest(text=f"Invalid JSON body: {err}") from err

        raw_text = str(payload.get("raw_text", "")).strip()
        file_name = str(payload.get("file_name", DEFAULT_IMPORT_FILENAME)).strip() or DEFAULT_IMPORT_FILENAME
        if not raw_text:
            raise web.HTTPBadRequest(text="No browser auth input was provided.")

        try:
            headers = parse_browser_auth_input(raw_text)
            host_path, config_path = write_browser_auth_file(self.hass, file_name, headers)
        except HomeAssistantError as err:
            raise web.HTTPBadRequest(text=str(err)) from err

        return self.json(
            {
                "saved": True,
                "host_path": host_path,
                "config_path": config_path,
                "keys": sorted(headers.keys()),
                "missing_required_keys": sorted(
                    key for key in ("authorization", "cookie", "content-type", "x-goog-authuser", "x-origin")
                    if not headers.get(key)
                ),
            }
        )


def _log_runtime_diagnostics() -> None:
    manifest_version = "unknown"
    manifest_path = Path(__file__).with_name("manifest.json")
    try:
        import json

        manifest_version = json.loads(manifest_path.read_text(encoding="utf-8")).get("version", "unknown")
    except Exception as err:  # pragma: no cover - diagnostics only
        manifest_version = f"unreadable:{err.__class__.__name__}"

    auth_import_path = Path(parse_browser_auth_input.__code__.co_filename)
    diagnostics_marker = "missing"
    try:
        diagnostics_marker = (
            "present"
            if "Detected allowed keys" in auth_import_path.read_text(encoding="utf-8")
            else "absent"
        )
    except Exception as err:  # pragma: no cover - diagnostics only
        diagnostics_marker = f"unreadable:{err.__class__.__name__}"

    _LOGGER.warning(
        "Runtime diagnostics: package=%s manifest=%s auth_import=%s marker=%s",
        __file__,
        manifest_version,
        auth_import_path,
        diagnostics_marker,
    )
