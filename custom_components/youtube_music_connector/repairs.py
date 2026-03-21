"""Repairs integration for youtube_music_connector."""

from __future__ import annotations

from homeassistant.components.repairs import RepairsFlow


class RestartRequiredFixFlow(RepairsFlow):
    """Repair flow that restarts Home Assistant when the user confirms."""

    async def async_step_init(self, user_input=None):
        """Handle the confirmation step."""
        if user_input is not None:
            await self.hass.services.async_call("homeassistant", "restart")
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="init")


async def async_create_fix_flow(hass, issue_id, data):
    """Create repair fix flows for this integration."""
    if issue_id == "restart_required":
        return RestartRequiredFixFlow()
