# Changelog

## Update notes
- After clicking `Update`, start the add-on once so the bundled integration files are copied into `/config`.
- Restart Home Assistant after the add-on run.
- Hard-reload the browser afterwards so Home Assistant picks up the latest frontend files.

## 0.3.34
- Only pause the previous target on target switches when the connector itself started the currently playing stream there.

## 0.3.33
- Hide autoplay, shuffle, and repeat controls until an actual item is active.

## 0.3.32
- Remove the user-facing `overwrite_existing` option and always overwrite installed files during add-on runs.

## 0.3.31
- Harden panel and widget rendering against non-string values after playback state changes.

## 0.3.30
- Prefer `get_watch_playlist(...)` when `get_playlist(...)` returns tracks without playable `videoId` values.

## 0.3.29
- Improve playlist playback resolution by trying `get_watch_playlist(...)` before falling back to album-style lookup.

## 0.3.28
- Add persistent update instructions above the changelog so the required post-update steps are always visible.

## 0.3.0
- Add direct browser-auth import to the integration config flow.
- Allow pasting `Copy as fetch`, raw request headers, or JSON without manually creating a `browser.json` file first.
- Store imported browser auth automatically in `/config/.storage/` before validation.

## 0.2.3
- Stop cloning GitHub at add-on runtime.
- Install the bundled integration and Lovelace widget directly from the add-on package.
- Add payload sync tooling so add-on releases ship the same files as the repository sources.

## 0.2.1
- Rename the visible Home Assistant add-on to `YouTube Music Connector`.
- Clarify in documentation that the repository already ships the sidebar panel UI and Lovelace widget.

## 0.2.0
- Add initial Home Assistant companion add-on packaging.
- Add synchronized branding assets for the add-on and custom integration.
- Add shared version-bump tooling and repository agent guidance.
