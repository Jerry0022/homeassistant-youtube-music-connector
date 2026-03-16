"""Browser auth import helpers for youtube_music_connector."""

from __future__ import annotations

import json
import re
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import STORAGE_DIR

from .youtube_music_api import ALLOWED_BROWSER_HEADERS, REQUIRED_BROWSER_HEADERS

DEFAULT_IMPORT_FILENAME = "browser_youtube_music_connector.json"


def parse_browser_auth_input(raw_text: str) -> dict[str, str]:
    """Parse Copy as fetch, raw request headers, or direct JSON into browser.json data."""

    text = raw_text.strip()
    if not text:
        raise HomeAssistantError("No browser auth input was provided.")

    if text.startswith("fetch("):
        headers = _parse_fetch_headers(text)
    elif text.startswith("{"):
        headers = _parse_json_headers(text)
    else:
        headers = _parse_raw_headers(text)

    normalized = {str(key).lower(): str(value) for key, value in headers.items() if value}
    filtered = {key: value for key, value in normalized.items() if key in ALLOWED_BROWSER_HEADERS}

    missing = sorted(key for key in REQUIRED_BROWSER_HEADERS if not filtered.get(key))
    if missing:
        raise HomeAssistantError(
            f"Imported browser auth is missing required keys: {', '.join(missing)}"
        )

    return filtered


def write_browser_auth_file(hass: HomeAssistant, file_name: str, headers: dict[str, str]) -> tuple[str, str]:
    """Write parsed browser auth to .storage and return host path plus /config path."""

    safe_name = Path(file_name or DEFAULT_IMPORT_FILENAME).name
    if not safe_name.endswith(".json"):
        safe_name = f"{safe_name}.json"

    host_path = Path(hass.config.path(STORAGE_DIR, safe_name))
    host_path.write_text(json.dumps(headers, ensure_ascii=False, indent=2), encoding="utf-8")
    config_path = f"/config/.storage/{safe_name}"
    return str(host_path), config_path


def _parse_fetch_headers(text: str) -> dict[str, str]:
    match = re.search(r'"headers"\s*:\s*({.*?})\s*,\s*"referrer"', text, re.DOTALL)
    if not match:
        raise HomeAssistantError("Could not extract the headers object from the fetch snippet.")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as err:
        raise HomeAssistantError(f"Fetch headers are not valid JSON: {err.msg}") from err


def _parse_json_headers(text: str) -> dict[str, str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as err:
        raise HomeAssistantError(f"Browser auth JSON is invalid: {err.msg}") from err

    if not isinstance(payload, dict):
        raise HomeAssistantError("Browser auth JSON must contain an object.")

    if "headers" in payload and isinstance(payload["headers"], dict):
        return payload["headers"]

    return payload


def _parse_raw_headers(text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in text.splitlines():
        raw_line = line.strip()
        if not raw_line or ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        headers[key.strip()] = value.strip()

    if not headers:
        raise HomeAssistantError("Could not parse any HTTP headers from the provided text.")

    return headers
