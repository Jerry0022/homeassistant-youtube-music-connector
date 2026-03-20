# YouTube Music Connector

This Home Assistant add-on installs or updates the `youtube_music_connector` custom integration together with its shipped UI surfaces from the versioned add-on package into your Home Assistant configuration directory.

## What it does

- Copies `custom_components/youtube_music_connector` into `/config/custom_components`
- Copies `www/community/youtube-music-connector/youtube-music-connector.js` into `/config/www/community/youtube-music-connector`
- Includes the built-in sidebar panel UI that is shipped inside the integration frontend
- Uses the files bundled in the add-on release, so Home Assistant version updates are tied to the add-on version
- Shows a persistent notification after update, reminding you to restart Home Assistant

## Typical usage

1. Add this repository to the Home Assistant app/add-on store.
2. Install **YouTube Music Connector**.
3. Leave the default options in place unless you want to disable overwriting an existing manual install.
4. Start the add-on once to copy the files into `/config`.
5. Restart Home Assistant.
6. Add the integration from Settings -> Devices & Services.

## Lovelace Cards

The integration ships two Lovelace cards that are automatically registered as resources. You can add them to any dashboard.

### ytmc-player — Now Playing + Transport

Full player card with album art background, transport controls, volume, progress/seek, and device selection.

```yaml
type: custom:ytmc-player
entity: media_player.youtube_music_connector
exclude_devices:
  - media_player.kitchen_display
  - media_player.office_tv
```

**Config parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `entity` | string | *(required)* | Entity ID of the YouTube Music Connector media player |
| `exclude_devices` | string[] | `[]` | List of `media_player` entity IDs to hide from the device selector |

### ytmc-search-play — Search + Play

Search YouTube Music and play results on selected devices.

```yaml
type: custom:ytmc-search-play
entity: media_player.youtube_music_connector
exclude_devices:
  - media_player.kitchen_display
```

**Config parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `entity` | string | *(required)* | Entity ID of the YouTube Music Connector media player |
| `exclude_devices` | string[] | `[]` | List of `media_player` entity IDs to hide from the device selector |

### Multi-device group playback

Both cards support selecting **multiple devices** for synchronized playback. Click multiple device chips to form a group — all play, pause, stop, and track-change operations will be mirrored to all group members.

In group mode:
- **Volume** controls all selected devices (slider shows the highest level)
- **Play/Pause/Stop** is mirrored to all targets
- **Next/Previous track** plays the new track on all targets
- Progress bar, seek, shuffle, and repeat are hidden (not applicable across devices)

Deselect devices until only one remains to return to single-device mode.

### CSS theming

Both cards support CSS custom properties for theming:

```yaml
type: custom:ytmc-player
entity: media_player.youtube_music_connector
style: |
  :host {
    --ytmc-bg: #1a1a2e;
    --ytmc-accent: #e94560;
    --ytmc-text: #eaeaea;
    --ytmc-text-secondary: rgba(234,234,234,0.7);
    --ytmc-radius: 12px;
  }
```

| CSS Property | Default | Description |
|---|---|---|
| `--ytmc-bg` | `#0f1923` | Background color |
| `--ytmc-surface` | `rgba(255,255,255,0.06)` | Card surface |
| `--ytmc-text` | `#f8fafc` | Primary text color |
| `--ytmc-text-secondary` | `rgba(248,250,252,0.72)` | Secondary text |
| `--ytmc-accent` | `#4a9eff` | Accent / highlight |
| `--ytmc-accent-active` | `#2d7fe0` | Active state accent |
| `--ytmc-radius` | `18px` | Border radius |
| `--ytmc-font-family` | `inherit` | Font family |

## Services

### Main automation service

```yaml
action: youtube_music_connector.execute
data:
  entity_id: media_player.youtube_music_connector
  target_entity_id: media_player.living_room_speaker
  query: "nature sounds birds"
  search_type: all
  limit: 5
  play: true
  autoplay_enabled: true
  shuffle_enabled: false
  repeat_mode: forever
```

### Group playback service

```yaml
action: youtube_music_connector.set_group_targets
data:
  entity_id: media_player.youtube_music_connector
  group_targets:
    - media_player.kitchen_nest
    - media_player.bedroom_nest
```

### All available services

| Service | Description |
|---------|-------------|
| `search` | Search YouTube Music by query |
| `play` | Play an item on the active target |
| `play_on` | Play on a specific target without switching the active target |
| `stop` | Stop playback |
| `next_track` | Skip to next track |
| `previous_track` | Go back to previous track |
| `set_autoplay` | Enable/disable autoplay |
| `set_shuffle` | Enable/disable shuffle |
| `set_repeat_mode` | Set repeat mode (`off`, `once`, `forever`) |
| `set_group_targets` | Set additional targets for group playback |
| `resolve_stream` | Resolve a playable audio stream URL |
| `execute` | Unified entrypoint for automations |

## Notes

- This add-on installs the integration files, including the sidebar search/playback UI and the Lovelace cards.
- If you prefer HACS, you can install the integration directly from the same GitHub repository instead.
- After an add-on update, a persistent notification will remind you to restart Home Assistant.
