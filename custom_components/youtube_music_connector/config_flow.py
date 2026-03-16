"""Config flow for youtube_music_connector using browser auth."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import selector
from homeassistant.helpers.storage import STORAGE_DIR

from .auth_import import DEFAULT_IMPORT_FILENAME, parse_browser_auth_input, write_browser_auth_file
from .const import (
    CONFIG_STEP_RECONFIGURE,
    CONFIG_STEP_USER,
    CONF_BROWSER_AUTH_FILE_NAME,
    CONF_BROWSER_AUTH_INPUT,
    CONF_DEFAULT_TARGET_MEDIA_PLAYER,
    CONF_HEADER_PATH,
    CONF_LANGUAGE,
    CONF_NAME,
    DEFAULT_LANGUAGE,
    DEFAULT_NAME,
    DOMAIN,
    ERROR_AUTH,
    ERROR_MISSING_HEADER,
    ERROR_NO_RESULTS,
    SUPPORTED_LANGUAGES,
    TITLE_PREFIX,
)
from .youtube_music_api import YoutubeMusicApiClient

BROWSER_AUTH_GUIDE_URL = "https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html"
VALIDATION_QUERY = "Bodo Wartke"


@config_entries.HANDLERS.register(DOMAIN)
class YoutubeMusicConnectorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the browser-auth config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self.data: dict = {}
        self._errors: dict[str, str] = {}
        self._last_error_detail = ""
        self._last_validation_status = "No test run yet."

    async def async_step_user(self, user_input=None):
        if user_input is None:
            self.data = self._default_data()
            return await self._async_show_setup_form(CONFIG_STEP_USER)

        self.data.update(user_input)
        header_path = await self._async_prepare_header_path()
        if not header_path:
            self._errors = {"base": ERROR_MISSING_HEADER}
            return await self._async_show_setup_form(CONFIG_STEP_USER)
        self.data[CONF_HEADER_PATH] = header_path

        unique_id = self._build_unique_id(header_path)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        validated = await self._async_validate_and_store_status(self.data)
        if validated is None:
            return await self._async_show_setup_form(CONFIG_STEP_USER)

        self._last_error_detail = ""
        title_suffix = self.data.get(CONF_NAME, DEFAULT_NAME).replace(DOMAIN, "").strip("_ ")
        title = f"{TITLE_PREFIX}{title_suffix}".strip()
        return self.async_create_entry(title=title, data=validated)

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_active_entry()
        if entry is None:
            return self.async_abort(reason="reconfigure_failed")

        if user_input is None:
            self.data = dict(entry.options or entry.data)
            self.data.setdefault(CONF_BROWSER_AUTH_INPUT, "")
            self.data.setdefault(CONF_BROWSER_AUTH_FILE_NAME, DEFAULT_IMPORT_FILENAME)
            return await self._async_show_setup_form(CONFIG_STEP_RECONFIGURE)

        self.data.update(user_input)
        header_path = await self._async_prepare_header_path()
        if not header_path:
            self._errors = {"base": ERROR_MISSING_HEADER}
            return await self._async_show_setup_form(CONFIG_STEP_RECONFIGURE)
        self.data[CONF_HEADER_PATH] = header_path

        if self._is_duplicate_header_path(header_path, exclude_entry_id=entry.entry_id):
            self._errors = {"base": "already_configured"}
            self._last_validation_status = "Validation skipped because this header file is already configured."
            return await self._async_show_setup_form(CONFIG_STEP_RECONFIGURE)

        validated = await self._async_validate_and_store_status(self.data)
        if validated is None:
            return await self._async_show_setup_form(CONFIG_STEP_RECONFIGURE)

        self.hass.config_entries.async_update_entry(
            entry,
            title=self._build_title(validated),
            data={**entry.data, **validated},
            options={**entry.options, **validated},
        )
        return self.async_abort(reason="reconfigure_successful")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return YoutubeMusicConnectorOptionsFlow(config_entry)

    async def _async_prepare_header_path(self) -> str:
        raw_input = str(self.data.get(CONF_BROWSER_AUTH_INPUT, "")).strip()
        if raw_input:
            file_name = str(self.data.get(CONF_BROWSER_AUTH_FILE_NAME, DEFAULT_IMPORT_FILENAME)).strip()
            try:
                headers = parse_browser_auth_input(raw_input)
                _host_path, config_path = write_browser_auth_file(self.hass, file_name, headers)
            except HomeAssistantError as err:
                self._errors = {"base": ERROR_AUTH}
                self._last_error_detail = str(err)
                self._last_validation_status = f"Browser auth import failed: {self._last_error_detail}"
                return ""
            self._last_error_detail = ""
            self._last_validation_status = f"Browser auth saved to {config_path}"
            self.data[CONF_BROWSER_AUTH_FILE_NAME] = Path(config_path).name
            self.data[CONF_BROWSER_AUTH_INPUT] = ""
            return config_path

        header_path = str(self.data.get(CONF_HEADER_PATH, "")).strip()
        if not header_path:
            self._last_validation_status = "Header file path is empty."
        return header_path

    async def _async_validate_and_store_status(self, data: dict) -> dict | None:
        self._errors = {}
        self._last_validation_status = "Validation started."
        try:
            api = YoutubeMusicApiClient(
                self.hass,
                data[CONF_HEADER_PATH],
                data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
            )
            checkpoints, results = await api.async_validate_with_details(VALIDATION_QUERY)
            self._last_validation_status = " | ".join(checkpoints)
            if not results:
                self._errors["base"] = ERROR_NO_RESULTS
                self._last_error_detail = "Search request succeeded but returned no matching songs."
                return None
        except Exception as err:
            self._last_error_detail = str(err).strip() or err.__class__.__name__
            self._last_validation_status = self._append_failure_status(self._last_validation_status, err)
            self._errors["base"] = ERROR_AUTH
            return None

        return {
            CONF_NAME: data.get(CONF_NAME, DEFAULT_NAME),
            CONF_LANGUAGE: data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
            CONF_HEADER_PATH: data[CONF_HEADER_PATH],
            CONF_DEFAULT_TARGET_MEDIA_PLAYER: data.get(CONF_DEFAULT_TARGET_MEDIA_PLAYER, ""),
        }

    async def _async_show_setup_form(self, step_id: str):
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(await self._async_create_form()),
            errors=self._errors,
            description_placeholders={
                "browser_auth_guide_url": BROWSER_AUTH_GUIDE_URL,
                "last_error": self._last_error_detail or "No error.",
                "validation_status": self._last_validation_status,
                "example_header_path": self.hass.config.path(STORAGE_DIR, "browser_youtube_music_connector.json"),
            },
        )

    async def _async_create_form(self) -> OrderedDict:
        data_schema: OrderedDict = OrderedDict()
        languages = sorted(SUPPORTED_LANGUAGES or {DEFAULT_LANGUAGE})
        data_schema[vol.Required(CONF_NAME, default=self.data.get(CONF_NAME, DEFAULT_NAME))] = str
        data_schema[vol.Required(CONF_LANGUAGE, default=self.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE))] = selector(
            {"select": {"options": languages, "mode": "dropdown"}}
        )
        data_schema[vol.Required(CONF_HEADER_PATH, default=self.data.get(CONF_HEADER_PATH, ""))] = str
        data_schema[
            vol.Optional(
                CONF_BROWSER_AUTH_FILE_NAME,
                default=self.data.get(CONF_BROWSER_AUTH_FILE_NAME, DEFAULT_IMPORT_FILENAME),
            )
        ] = str
        data_schema[
            vol.Optional(
                CONF_BROWSER_AUTH_INPUT,
                default=self.data.get(CONF_BROWSER_AUTH_INPUT, ""),
            )
        ] = selector({"text": {"multiline": True, "type": "text"}})
        data_schema[
            vol.Optional(
                CONF_DEFAULT_TARGET_MEDIA_PLAYER,
                default=self.data.get(CONF_DEFAULT_TARGET_MEDIA_PLAYER, ""),
            )
        ] = selector(
            {
                "entity": {
                    "filter": [{"domain": MEDIA_PLAYER_DOMAIN}],
                    "multiple": False,
                }
            }
        )
        return data_schema

    def _default_data(self) -> dict:
        return {
            CONF_NAME: DEFAULT_NAME,
            CONF_LANGUAGE: DEFAULT_LANGUAGE,
            CONF_HEADER_PATH: self.hass.config.path(STORAGE_DIR, "browser_youtube_music_connector.json"),
            CONF_BROWSER_AUTH_FILE_NAME: DEFAULT_IMPORT_FILENAME,
            CONF_BROWSER_AUTH_INPUT: "",
            CONF_DEFAULT_TARGET_MEDIA_PLAYER: "",
        }

    def _build_unique_id(self, header_path: str) -> str:
        return str(Path(header_path).expanduser()).lower()

    def _build_title(self, data: dict) -> str:
        title_suffix = data.get(CONF_NAME, DEFAULT_NAME).replace(DOMAIN, "").strip("_ ")
        return f"{TITLE_PREFIX}{title_suffix}".strip()

    def _append_failure_status(self, status: str, err: Exception) -> str:
        detail = str(err).strip() or err.__class__.__name__
        if not status:
            return f"Validation failed: {detail}"
        return f"{status} | Validation failed: {detail}"

    def _get_active_entry(self):
        entry_id = self.context.get("entry_id")
        if not entry_id:
            return None
        return self.hass.config_entries.async_get_entry(entry_id)

    def _is_duplicate_header_path(self, header_path: str, exclude_entry_id: str | None = None) -> bool:
        normalized = self._build_unique_id(header_path)
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if exclude_entry_id and entry.entry_id == exclude_entry_id:
                continue
            configured_path = entry.options.get(CONF_HEADER_PATH, entry.data.get(CONF_HEADER_PATH, ""))
            if configured_path and self._build_unique_id(configured_path) == normalized:
                return True
        return False


class YoutubeMusicConnectorOptionsFlow(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry
        self.data = dict(config_entry.options or config_entry.data)
        self.data.setdefault(CONF_BROWSER_AUTH_INPUT, "")
        self.data.setdefault(CONF_BROWSER_AUTH_FILE_NAME, DEFAULT_IMPORT_FILENAME)
        self._errors: dict[str, str] = {}
        self._last_error_detail = ""
        self._last_validation_status = "No test run yet."

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            self.data.update(user_input)
            header_path = await self._async_prepare_header_path()
            if not header_path:
                self._errors = {"base": ERROR_MISSING_HEADER}
            elif self._is_duplicate_header_path(header_path):
                self._errors = {"base": "already_configured"}
                self._last_validation_status = "Validation skipped because this header file is already configured."
            else:
                self.data[CONF_HEADER_PATH] = header_path
                validated = await self._async_validate_options()
                if validated is not None:
                    return self.async_create_entry(data=validated)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(self._build_schema()),
            errors=self._errors,
            description_placeholders={
                "browser_auth_guide_url": BROWSER_AUTH_GUIDE_URL,
                "last_error": self._last_error_detail or "No error.",
                "validation_status": self._last_validation_status,
                "example_header_path": self.hass.config.path(
                    STORAGE_DIR, "browser_youtube_music_connector.json"
                ),
            },
        )

    async def _async_prepare_header_path(self) -> str:
        raw_input = str(self.data.get(CONF_BROWSER_AUTH_INPUT, "")).strip()
        if raw_input:
            file_name = str(self.data.get(CONF_BROWSER_AUTH_FILE_NAME, DEFAULT_IMPORT_FILENAME)).strip()
            try:
                headers = parse_browser_auth_input(raw_input)
                _host_path, config_path = write_browser_auth_file(self.hass, file_name, headers)
            except HomeAssistantError as err:
                self._errors = {"base": ERROR_AUTH}
                self._last_error_detail = str(err)
                self._last_validation_status = f"Browser auth import failed: {self._last_error_detail}"
                return ""
            self._last_error_detail = ""
            self._last_validation_status = f"Browser auth saved to {config_path}"
            self.data[CONF_BROWSER_AUTH_FILE_NAME] = Path(config_path).name
            self.data[CONF_BROWSER_AUTH_INPUT] = ""
            return config_path

        header_path = str(self.data.get(CONF_HEADER_PATH, "")).strip()
        if not header_path:
            self._last_validation_status = "Header file path is empty."
        return header_path

    async def _async_validate_options(self) -> dict | None:
        self._errors = {}
        self._last_validation_status = "Validation started."
        try:
            api = YoutubeMusicApiClient(
                self.hass,
                self.data[CONF_HEADER_PATH],
                self.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
            )
            checkpoints, results = await api.async_validate_with_details(VALIDATION_QUERY)
            self._last_validation_status = " | ".join(checkpoints)
            if not results:
                self._errors["base"] = ERROR_NO_RESULTS
                self._last_error_detail = "Search request succeeded but returned no matching songs."
                return None
        except Exception as err:
            self._last_error_detail = str(err).strip() or err.__class__.__name__
            self._last_validation_status = (
                f"{self._last_validation_status} | Validation failed: {self._last_error_detail}"
            )
            self._errors["base"] = ERROR_AUTH
            return None

        self._last_error_detail = ""
        return {
            CONF_NAME: self.data.get(CONF_NAME, DEFAULT_NAME),
            CONF_LANGUAGE: self.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
            CONF_HEADER_PATH: self.data[CONF_HEADER_PATH],
            CONF_DEFAULT_TARGET_MEDIA_PLAYER: self.data.get(CONF_DEFAULT_TARGET_MEDIA_PLAYER, ""),
        }

    def _is_duplicate_header_path(self, header_path: str) -> bool:
        normalized = str(Path(header_path).expanduser()).lower()
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == self.config_entry.entry_id:
                continue
            configured_path = entry.options.get(CONF_HEADER_PATH, entry.data.get(CONF_HEADER_PATH, ""))
            if configured_path and str(Path(configured_path).expanduser()).lower() == normalized:
                return True
        return False

    def _build_schema(self) -> OrderedDict:
        languages = sorted(SUPPORTED_LANGUAGES or {DEFAULT_LANGUAGE})
        schema = OrderedDict()
        schema[vol.Required(CONF_NAME, default=self.data.get(CONF_NAME, DEFAULT_NAME))] = str
        schema[vol.Required(CONF_LANGUAGE, default=self.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE))] = selector(
            {"select": {"options": languages, "mode": "dropdown"}}
        )
        schema[vol.Required(CONF_HEADER_PATH, default=self.data.get(CONF_HEADER_PATH, ""))] = str
        schema[
            vol.Optional(
                CONF_BROWSER_AUTH_FILE_NAME,
                default=self.data.get(CONF_BROWSER_AUTH_FILE_NAME, DEFAULT_IMPORT_FILENAME),
            )
        ] = str
        schema[
            vol.Optional(
                CONF_BROWSER_AUTH_INPUT,
                default=self.data.get(CONF_BROWSER_AUTH_INPUT, ""),
            )
        ] = selector({"text": {"multiline": True, "type": "text"}})
        schema[
            vol.Optional(
                CONF_DEFAULT_TARGET_MEDIA_PLAYER,
                default=self.data.get(CONF_DEFAULT_TARGET_MEDIA_PLAYER, ""),
            )
        ] = selector(
            {
                "entity": {
                    "filter": [{"domain": MEDIA_PLAYER_DOMAIN}],
                    "multiple": False,
                }
            }
        )
        return schema
