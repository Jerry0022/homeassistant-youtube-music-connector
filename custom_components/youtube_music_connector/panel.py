"""Sidebar panel registration for youtube_music_connector."""

from __future__ import annotations

from homeassistant.components import panel_custom
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PANEL_COMPONENT_NAME,
    PANEL_ICON,
    PANEL_MODULE_PATH,
    PANEL_TITLE,
    PANEL_URL_PATH,
)

STATIC_BASE = "/api/youtube_music_connector/static"
LOVELACE_COMPONENTS = [
    f"{STATIC_BASE}/ytmc-player.js",
    f"{STATIC_BASE}/ytmc-search-play.js",
]


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register custom sidebar panel."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                "/api/youtube_music_connector/static",
                hass.config.path("custom_components", DOMAIN, "frontend"),
                True,
            )
        ]
    )

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_COMPONENT_NAME,
        frontend_url_path=PANEL_URL_PATH,
        module_url=PANEL_MODULE_PATH,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        require_admin=False,
        config={"domain": DOMAIN},
    )

    for url in LOVELACE_COMPONENTS:
        add_extra_js_url(hass, url)


async def async_unregister_panel(hass: HomeAssistant) -> None:
    """Unregister custom sidebar panel."""
    panel_custom.async_unregister_panel(hass, PANEL_URL_PATH)
