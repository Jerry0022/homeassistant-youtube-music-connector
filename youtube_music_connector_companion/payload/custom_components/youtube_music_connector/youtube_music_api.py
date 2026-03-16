"""Custom YouTube Music API client using browser header auth."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from aiohttp import ClientError

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import SUPPORTED_LANGUAGES, YTM_API_KEY, YTM_BASE_API, YTM_DOMAIN, YTM_USER_AGENT

FILTER_PARAMS = {
    "songs": "EgWKAQIIAWoMEA4QChADEAQQCRAF",
    "artists": "EgWKAQIgAWoMEA4QChADEAQQCRAF",
    "playlists": "EgWKAQIoAWoMEA4QChADEAQQCRAF",
}

ALLOWED_BROWSER_HEADERS = {
    "accept",
    "accept-encoding",
    "accept-language",
    "authorization",
    "content-type",
    "cookie",
    "origin",
    "referer",
    "user-agent",
    "x-goog-authuser",
    "x-goog-visitor-id",
    "x-origin",
    "x-youtube-bootstrap-logged-in",
    "x-youtube-client-name",
    "x-youtube-client-version",
}

REQUIRED_BROWSER_HEADERS = {
    "authorization",
    "cookie",
    "content-type",
    "x-goog-authuser",
    "x-origin",
}


class YoutubeMusicApiClient:
    """Minimal YouTube Music client using direct youtubei calls and browser headers."""

    def __init__(self, hass, header_path: str, language: str) -> None:
        self.hass = hass
        self.language = language if language in SUPPORTED_LANGUAGES else "de"
        self.header_path = Path(header_path)
        self._session = async_get_clientsession(hass)
        self._visitor_id: str | None = None
        self._headers_cache: dict[str, str] | None = None

    async def async_search(self, query: str, filter_name: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"query": query}
        if filter_name in FILTER_PARAMS:
            body["params"] = FILTER_PARAMS[filter_name]
        payload = await self._post("search", body)
        items = self._parse_search_response(payload, filter_name, limit)
        return items[:limit]

    async def async_get_playlist(self, playlist_id: str, limit: int = 1) -> dict[str, Any]:
        browse_id = playlist_id if playlist_id.startswith("VL") else f"VL{playlist_id}"
        payload = await self._post("browse", {"browseId": browse_id})
        playlist = {
            "id": playlist_id,
            "title": self._first_text_for_key(payload, "title"),
            "author": self._first_author(payload),
            "thumbnails": self._first_thumbnail_group(payload),
            "tracks": [],
        }
        for item in self._iter_music_responsive_items(payload):
            parsed = self._parse_search_item(item, "songs")
            if parsed and parsed.get("videoId"):
                playlist["tracks"].append(parsed)
                if len(playlist["tracks"]) >= limit:
                    break
        return playlist

    async def async_get_up_next(
        self,
        video_id: str,
        playlist_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"videoId": video_id, "isAudioOnly": True}
        if playlist_id:
            body["playlistId"] = playlist_id if playlist_id.startswith("VL") else playlist_id
        payload = await self._post("next", body)
        items = self._parse_next_response(payload, current_video_id=video_id, limit=limit)
        return items[:limit]

    async def async_validate(self, query: str) -> list[dict[str, Any]]:
        return await self.async_search(query=query, filter_name="songs", limit=1)

    async def async_validate_with_details(self, query: str) -> tuple[list[str], list[dict[str, Any]]]:
        """Validate browser auth and return detailed checkpoints."""

        steps: list[str] = []
        raw_headers = self._load_browser_header_file()
        steps.append("Header file found.")

        headers = self._normalize_browser_headers(raw_headers)
        steps.append("Header file loaded.")

        headers = await self._finalize_headers(headers)
        steps.append("Required browser headers verified.")

        payload = await self._post(
            "search",
            {"query": query, "params": FILTER_PARAMS["songs"]},
            headers=headers,
        )
        steps.append("YouTube Music search request accepted.")

        results = self._parse_search_response(payload, "songs", 1)
        if not results:
            raise HomeAssistantError("Search test completed but returned no song results.")

        steps.append("Search test returned at least one song result.")
        return steps, results

    async def _post(
        self,
        endpoint: str,
        body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = headers or await self._build_headers()
        request_body = {**body, **self._build_context(headers)}
        url = f"{YTM_BASE_API}{endpoint}?alt=json&key={YTM_API_KEY}"
        try:
            async with self._session.post(url, json=request_body, headers=headers) as response:
                payload = await response.json(content_type=None)
                if response.status >= 400:
                    error = payload.get("error", {}).get("message", response.reason or "unknown error")
                    raise HomeAssistantError(
                        f"Server returned HTTP {response.status}: {response.reason}. {error}"
                    )
                return payload
        except ClientError as err:
            raise HomeAssistantError(f"YouTube Music request failed: {err}") from err

    async def _build_headers(self) -> dict[str, str]:
        if self._headers_cache is not None:
            return dict(self._headers_cache)

        payload = self._load_browser_header_file()
        headers = self._normalize_browser_headers(payload)
        headers = await self._finalize_headers(headers)
        self._headers_cache = headers
        return dict(headers)

    def _load_browser_header_file(self) -> dict[str, Any]:
        if not self.header_path.exists():
            raise HomeAssistantError(f"Header file not found: {self.header_path}")

        try:
            payload = json.loads(self.header_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            raise HomeAssistantError(f"Header file is not valid JSON: {err.msg}") from err

        if not isinstance(payload, dict):
            raise HomeAssistantError("Header file must contain a JSON object.")

        return payload

    def _normalize_browser_headers(self, payload: dict[str, Any]) -> dict[str, str]:
        headers = {str(key).lower(): str(value) for key, value in payload.items() if value}
        unexpected = sorted(set(headers.keys()) - ALLOWED_BROWSER_HEADERS)
        if unexpected:
            raise HomeAssistantError(f"Unexpected browser header keys: {', '.join(unexpected)}")

        missing = sorted(key for key in REQUIRED_BROWSER_HEADERS if not headers.get(key))
        if missing:
            raise HomeAssistantError(
                f"Browser header file is missing required keys: {', '.join(missing)}"
            )

        return headers

    async def _finalize_headers(self, headers: dict[str, str]) -> dict[str, str]:
        headers = dict(headers)
        headers.setdefault("user-agent", YTM_USER_AGENT)
        headers.setdefault("accept", "*/*")
        headers.setdefault("content-type", "application/json")
        headers.setdefault("origin", headers.get("x-origin", YTM_DOMAIN))
        headers.setdefault("referer", YTM_DOMAIN + "/")
        headers["x-goog-request-time"] = str(int(time.time()))
        headers["x-goog-visitor-id"] = headers.get("x-goog-visitor-id") or await self._get_visitor_id()
        return headers

    def _build_context(self, headers: dict[str, str]) -> dict[str, Any]:
        return {
            "context": {
                "client": {
                    "clientName": "WEB_REMIX",
                    "clientVersion": headers.get("x-youtube-client-version", f"1.{time.strftime('%Y%m%d', time.gmtime())}.01.00"),
                    "hl": self.language,
                },
                "user": {},
            }
        }

    async def _get_visitor_id(self) -> str:
        if self._visitor_id:
            return self._visitor_id
        async with self._session.get(YTM_DOMAIN, headers={"user-agent": YTM_USER_AGENT, "accept": "*/*"}) as response:
            text = await response.text()
        matches = re.findall(r"ytcfg\.set\s*\(\s*({.+?})\s*\)\s*;", text)
        if not matches:
            raise HomeAssistantError("Could not retrieve YouTube Music visitor id")
        ytcfg = json.loads(matches[0])
        self._visitor_id = ytcfg.get("VISITOR_DATA", "")
        if not self._visitor_id:
            raise HomeAssistantError("YouTube Music visitor id is empty")
        return self._visitor_id

    def _parse_search_response(
        self, payload: dict[str, Any], filter_name: str | None, limit: int
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in self._iter_music_responsive_items(payload):
            parsed = self._parse_search_item(item, filter_name)
            if parsed:
                items.append(parsed)
            if len(items) >= limit:
                break
        return items

    def _parse_next_response(
        self,
        payload: dict[str, Any],
        current_video_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = {current_video_id}
        for item in self._iter_playable_items(payload):
            parsed = self._parse_playable_item(item)
            if not parsed:
                continue
            video_id = parsed.get("videoId")
            if not video_id or video_id in seen:
                continue
            seen.add(video_id)
            items.append(parsed)
            if len(items) >= limit:
                break
        return items

    def _iter_music_responsive_items(self, node: Any):
        if isinstance(node, dict):
            if "musicResponsiveListItemRenderer" in node:
                yield node["musicResponsiveListItemRenderer"]
            for value in node.values():
                yield from self._iter_music_responsive_items(value)
        elif isinstance(node, list):
            for value in node:
                yield from self._iter_music_responsive_items(value)

    def _iter_playable_items(self, node: Any):
        if isinstance(node, dict):
            if "playlistPanelVideoRenderer" in node:
                yield node["playlistPanelVideoRenderer"]
            if "musicResponsiveListItemRenderer" in node:
                yield node["musicResponsiveListItemRenderer"]
            for value in node.values():
                yield from self._iter_playable_items(value)
        elif isinstance(node, list):
            for value in node:
                yield from self._iter_playable_items(value)

    def _parse_search_item(self, renderer: dict[str, Any], filter_name: str | None) -> dict[str, Any] | None:
        columns = self._extract_columns(renderer)
        if not columns:
            return None

        title = columns[0]
        subtitle = columns[1] if len(columns) > 1 else ""
        browse_id = self._extract_browse_id(renderer)
        video_id = self._extract_video_id(renderer)
        playlist_id = self._extract_playlist_id(renderer)
        thumbnails = self._extract_thumbnails(renderer)

        if filter_name == "songs":
            if video_id:
                return {
                    "resultType": "song",
                    "videoId": video_id,
                    "title": title,
                    "artists": self._subtitle_to_artists(subtitle),
                    "thumbnails": thumbnails,
                    "browseId": browse_id,
                    "playlistId": playlist_id,
                }
            return None
        if filter_name == "artists":
            if browse_id and (browse_id.startswith("UC") or browse_id.startswith("MPLA")):
                return {
                    "resultType": "artist",
                    "browseId": browse_id,
                    "artist": title,
                    "title": title,
                    "thumbnails": thumbnails,
                }
            return None
        if filter_name == "playlists":
            if playlist_id or (browse_id and browse_id.startswith(("VL", "RD"))):
                resolved_playlist_id = playlist_id or (browse_id[2:] if browse_id.startswith("VL") else browse_id)
                return {
                    "resultType": "playlist",
                    "browseId": browse_id,
                    "playlistId": resolved_playlist_id,
                    "title": title,
                    "author": subtitle.split(" • ")[0] if subtitle else "",
                    "thumbnails": thumbnails,
                }
            return None
        if video_id:
            return {
                "resultType": "song",
                "videoId": video_id,
                "title": title,
                "artists": self._subtitle_to_artists(subtitle),
                "thumbnails": thumbnails,
            }
        if browse_id and (browse_id.startswith("UC") or browse_id.startswith("MPLA")):
            return {
                "resultType": "artist",
                "browseId": browse_id,
                "artist": title,
                "title": title,
                "thumbnails": thumbnails,
            }
        if playlist_id or (browse_id and browse_id.startswith(("VL", "RD"))):
            resolved_playlist_id = playlist_id or (browse_id[2:] if browse_id.startswith("VL") else browse_id)
            return {
                "resultType": "playlist",
                "browseId": browse_id,
                "playlistId": resolved_playlist_id,
                "title": title,
                "author": subtitle.split(" • ")[0] if subtitle else "",
                "thumbnails": thumbnails,
            }
        return None

    def _parse_playable_item(self, renderer: dict[str, Any]) -> dict[str, Any] | None:
        video_id = self._extract_video_id(renderer)
        if not video_id:
            return None
        columns = self._extract_columns(renderer)
        title = columns[0] if columns else self._first_text_for_key(renderer, "title")
        subtitle = columns[1] if len(columns) > 1 else self._first_text_for_key(renderer, "longBylineText")
        browse_id = self._extract_browse_id(renderer)
        playlist_id = self._extract_playlist_id(renderer)
        return {
            "resultType": "song",
            "videoId": video_id,
            "title": title or "",
            "artists": self._subtitle_to_artists(subtitle or ""),
            "thumbnails": self._extract_thumbnails(renderer),
            "browseId": browse_id,
            "playlistId": playlist_id,
        }

    def _extract_columns(self, renderer: dict[str, Any]) -> list[str]:
        columns: list[str] = []
        for key in ("flexColumns", "fixedColumns"):
            for column in renderer.get(key, []):
                runs = column.get("musicResponsiveListItemFlexColumnRenderer", {}).get("text", {}).get("runs", [])
                if not runs:
                    runs = column.get("musicResponsiveListItemFixedColumnRenderer", {}).get("text", {}).get("runs", [])
                text = "".join(run.get("text", "") for run in runs).strip()
                if text:
                    columns.append(text)
        return columns

    def _extract_browse_id(self, node: Any) -> str:
        if isinstance(node, dict):
            browse = node.get("browseEndpoint", {}).get("browseId")
            if browse:
                return browse
            for value in node.values():
                found = self._extract_browse_id(value)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = self._extract_browse_id(value)
                if found:
                    return found
        return ""

    def _extract_video_id(self, node: Any) -> str:
        if isinstance(node, dict):
            watch = node.get("watchEndpoint", {}).get("videoId")
            if watch:
                return watch
            for value in node.values():
                found = self._extract_video_id(value)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = self._extract_video_id(value)
                if found:
                    return found
        return ""

    def _extract_playlist_id(self, node: Any) -> str:
        if isinstance(node, dict):
            playlist_id = node.get("watchEndpoint", {}).get("playlistId")
            if playlist_id:
                return playlist_id
            playlist_id = node.get("watchPlaylistEndpoint", {}).get("playlistId")
            if playlist_id:
                return playlist_id
            for key, value in node.items():
                if key in {
                    "menu",
                    "menuRenderer",
                    "items",
                    "menuNavigationItemRenderer",
                    "menuServiceItemRenderer",
                }:
                    continue
                found = self._extract_playlist_id(value)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = self._extract_playlist_id(value)
                if found:
                    return found
        return ""

    def _extract_thumbnails(self, node: Any) -> list[dict[str, Any]]:
        if isinstance(node, dict):
            if "thumbnail" in node and isinstance(node["thumbnail"], dict):
                thumbs = node["thumbnail"].get("musicThumbnailRenderer", {}).get("thumbnail", {}).get("thumbnails")
                if thumbs:
                    return thumbs
                thumbs = node["thumbnail"].get("croppedSquareThumbnailRenderer", {}).get("thumbnail", {}).get("thumbnails")
                if thumbs:
                    return thumbs
            if "thumbnails" in node and isinstance(node["thumbnails"], list):
                return node["thumbnails"]
            for value in node.values():
                found = self._extract_thumbnails(value)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = self._extract_thumbnails(value)
                if found:
                    return found
        return []

    def _subtitle_to_artists(self, subtitle: str) -> list[dict[str, Any]]:
        parts = [part.strip() for part in subtitle.split("•") if part.strip()]
        artists: list[dict[str, Any]] = []
        for part in parts:
            if part.isdigit():
                continue
            if ":" in part:
                continue
            artists.append({"name": part})
        return artists

    def _first_text_for_key(self, node: Any, key: str) -> str:
        if isinstance(node, dict):
            if key in node and isinstance(node[key], dict):
                runs = node[key].get("runs")
                if runs:
                    return "".join(run.get("text", "") for run in runs).strip()
                text = node[key].get("simpleText")
                if text:
                    return text
            for value in node.values():
                found = self._first_text_for_key(value, key)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = self._first_text_for_key(value, key)
                if found:
                    return found
        return ""

    def _first_author(self, node: Any) -> str:
        if isinstance(node, dict):
            runs = node.get("subtitle", {}).get("runs")
            if runs:
                return "".join(run.get("text", "") for run in runs).strip()
            for value in node.values():
                found = self._first_author(value)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = self._first_author(value)
                if found:
                    return found
        return ""

    def _first_thumbnail_group(self, node: Any) -> list[dict[str, Any]]:
        return self._extract_thumbnails(node)
