# Changelog

## 0.7.3 — 2026-03-21

### Improved
- **Browser Auth Assistant instructions**: `music.youtube.com` is now a clickable link, added F12 keyboard hint, added Chromium-specific step for finding Request Headers in the Network tab, and textarea placeholder now shows an example of the expected header format.

## 0.7.2 — 2026-03-21

### Fixed
- **Volume targeting wrong device after restart**: First device click now replaces the synced default selection instead of adding to it, preventing stale devices from receiving volume commands.
- **Volume sent to devices without volume support**: Added `supported_features` check (bit 4) to skip devices that don't support `volume_set`.
- **Search enabled without target device**: Search input, filter tags, and search button are now disabled when no target device is selected; results area shows a prompt to select a device first.

## 0.7.1 — 2026-03-21

### Added
- **Restart via Repairs system**: After add-on update, a repair issue appears in Settings > System > Repairs with a one-click restart button (replaces persistent notification approach).
- **Device auto-power-on**: Playing on an off/standby device now turns it on automatically (up to 15 s wait) before starting playback.
- **Prev/next buttons always visible**: Transport controls now show skip-previous and skip-next buttons at all times (disabled state when no history/queue).

### Fixed
- **Volume targeting wrong device**: Player and search cards now always sync device selection from backend state, preventing stale local selections after restart or cross-card interactions.
- **Search-play device selection not reflected in player**: Both cards now share device state via backend `selected_devices` attribute with 2 s debounce after user interaction.
- **Multi-device play only playing on one device**: All selected devices are now turned on in parallel, stream resolved once, then played on all ready devices simultaneously.
- **Changing device selection stopped existing playback**: Selecting or deselecting devices no longer auto-pauses running streams; only explicit pause stops playback.
- **Missing album art in player**: Added `entity_picture` fallback for image URL resolution.
- **Search-play toggle not syncing immediately**: Device chip toggles in search now call `set_selected_devices` instantly (not only on play).
- **Add-on restart notification retry loop**: Replaced 150 s retry loop with single marker-file write; integration polls every 60 s.

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
