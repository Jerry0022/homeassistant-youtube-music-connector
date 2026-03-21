# Changelog

## 0.7.0 — 2026-03-20

### Added
- **Per-device DeviceSession architecture**: Each target media player now gets its own independent playback stream with separate queue, history, autoplay, shuffle, and repeat mode. Playing on device A no longer affects device B.
- **`set_selected_devices` service**: Single service call to set all selected devices at once, replacing the `select_source` + `set_group_targets` two-call pattern.
- **Recently played on empty search**: Pressing Enter or clicking search with an empty query shows the most recently played items (up to 5 songs, 5 playlists, 5 artists). Filter tags work on recent items too.
- **Browser Auth Assistant** restored in sidebar panel after panel refactor.
- **Sidebar panel icon** (`mdi:music`) for the YouTube Music menu entry.

### Changed
- Transport commands (play/pause/stop) now route to ALL selected devices in parallel.
- Track navigation (next/previous) routes to the primary selected device only.
- `set_group_targets` service is now deprecated (still works as a compatibility alias).

### Fixed
- Add-on restart notification: added `hassio_api` permission and marker-file fallback for persistent notifications.
- YAML `off` parsing error in `services.yaml` (bare `off` interpreted as boolean).
- Missing `await` on `async_register_panel()` in `panel.py`.
