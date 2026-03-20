# Reusable Web Components

Two standalone Web Components for embedding YouTube Music Connector controls in any Home Assistant dashboard or custom panel.

Both components are **Shadow DOM** isolated, **themeable via CSS custom properties**, and require only two properties: `hass` and `entityId`.

## Resource Registration

Both components are **automatically registered as Lovelace resources** when the integration loads. No manual resource configuration needed — just use the elements in any dashboard.

The scripts are served from:
- `/api/youtube_music_connector/static/ytmc-player.js`
- `/api/youtube_music_connector/static/ytmc-search-play.js`

## Quick Start

```html
<!-- Both elements are globally available after integration setup -->
<ytmc-player></ytmc-player>
<ytmc-search-play></ytmc-search-play>
```

```javascript
// Wire up in your panel or card
const player = document.querySelector("ytmc-player");
player.entityId = "media_player.youtube_music_connector";
player.hass = hassObject;

const search = document.querySelector("ytmc-search-play");
search.entityId = "media_player.youtube_music_connector";
search.hass = hassObject;
```

## Interactive Preview

Open `custom_components/youtube_music_connector/frontend/preview.html` in a browser to see both components rendered with mock data. The preview includes state presets (Fresh Start, Playing, Paused, External Playback, Searching) and a theme customizer.

---

## `<ytmc-player>`

Now-playing bar with device selection, transport controls, volume, and progress/seek.

**Source:** `custom_components/youtube_music_connector/frontend/ytmc-player.js`

### Properties

| Property   | Type     | Description                                          |
|------------|----------|------------------------------------------------------|
| `entityId` | `string` | The connector's `media_player` entity ID             |
| `hass`     | `object` | The Home Assistant connection object                 |

### Layout

```
┌──────────────────────────────────────────────────────────────┐
│  [Device chips ...]                              🔊 ━━━━━━  │
│                                                              │
│  Track Title                        (blurred album art bg)   │
│  Artist — Target Device                                      │
│                                                              │
│  [⏮] [⏯] [⏭]              [autoplay] [shuffle] [repeat]    │
│                                                              │
│  2:14  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6:28   │
└──────────────────────────────────────────────────────────────┘
```

### Conditional Visibility

| Element              | Visible when                                                     |
|----------------------|------------------------------------------------------------------|
| Device chips         | Always (when entity exists)                                      |
| Volume slider        | Target device supports volume (feature flag 4)                   |
| Track info           | `media_title` exists                                             |
| Transport controls   | Track is loaded; play/pause always visible if target has media   |
| Previous button      | `has_previous_track` attribute is `true`                         |
| Next button          | `has_next_track` attribute is `true`                             |
| Autoplay icon        | Track is loaded                                                  |
| Shuffle icon         | Track is loaded (hidden for external playback sources)           |
| Repeat icon          | Track is loaded (hidden for external playback sources)           |
| Progress bar         | Entity is active OR target is playing, AND `media_duration` > 0  |
| Seek interaction     | Target device supports seek (feature flag 16)                    |

### Entity Attributes Read

| Attribute                  | Usage                                      |
|----------------------------|--------------------------------------------|
| `target_entity_id`         | Currently active playback device            |
| `available_target_players` | List of selectable devices                  |
| `media_title`              | Track title display                         |
| `media_artist`             | Artist name display                         |
| `media_image_url`          | Album artwork / blurred background          |
| `media_duration`           | Track length (seconds)                      |
| `media_position`           | Current playback position (seconds)         |
| `media_position_updated_at`| Timestamp for position interpolation        |
| `shuffle_enabled`          | Shuffle button highlight                    |
| `repeat_mode`              | `off` / `forever` / `once`                  |
| `has_next_track`           | Show/hide next button                       |
| `has_previous_track`       | Show/hide previous button                   |
| `autoplay_enabled`         | Autoplay icon highlight                     |
| `autoplay_queue_length`    | Queued item count                           |

### Services Called

| Action           | HA Service                              | Parameters                          |
|------------------|-----------------------------------------|-------------------------------------|
| Select device    | `media_player.select_source`            | `entity_id`, `source` (target ID)   |
| Play / Pause     | `media_player.media_play` / `media_pause`| `entity_id`                        |
| Next track       | `youtube_music_connector.next_track`    | `entity_id`                         |
| Previous track   | `youtube_music_connector.previous_track`| `entity_id`                         |
| Toggle autoplay  | `youtube_music_connector.set_autoplay`  | `entity_id`, `enabled`              |
| Toggle shuffle   | `youtube_music_connector.set_shuffle`   | `entity_id`, `enabled`              |
| Cycle repeat     | `youtube_music_connector.set_repeat_mode`| `entity_id`, `mode` (off/forever/once)|
| Set volume       | `media_player.volume_set`               | `entity_id` (target), `volume_level`|
| Seek             | `media_player.media_seek`              | `entity_id` (target), `seek_position`|

### Device Chips

- Shows up to **3 most recently used** devices by default
- A "+N" button reveals all remaining devices
- Active device is highlighted with the accent color
- Icon: television for Chromecast/TV entities, speaker for others

### Progress Bar

- Updates every 1 second while playing (interpolated from `media_position` + elapsed time)
- Click/drag to seek (only if target supports seek)
- Displays current position and total duration as `m:ss`

---

## `<ytmc-search-play>`

Search input with inline filter tabs, multi-device selection, and result list with play buttons.

**Source:** `custom_components/youtube_music_connector/frontend/ytmc-search-play.js`

### Properties

| Property   | Type     | Description                                          |
|------------|----------|------------------------------------------------------|
| `entityId` | `string` | The connector's `media_player` entity ID             |
| `hass`     | `object` | The Home Assistant connection object                 |

### Layout

```
┌──────────────────────────────────────────────────────────────┐
│  [Device chips ... (multi-select)]                           │
│                                                              │
│  ┌─ 🔍 Search query ──── [Songs][Artists][Playlists] [➤] ─┐ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌ Track Title ──────────────────────────────── [▶] ───────┐ │
│  │ Artist · Type · Year                                    │ │
│  ├ Another Track ────────────────────────────── [▶] ───────┤ │
│  │ Artist · Type · Year                                    │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                    [Load more]               │
└──────────────────────────────────────────────────────────────┘
```

### Conditional Visibility

| Element          | Visible when                                              |
|------------------|-----------------------------------------------------------|
| Device chips     | Always (when entity exists)                               |
| Search bar       | Always                                                    |
| Filter tags      | Always (inline in search bar)                             |
| Loading spinner  | Search request in progress                                |
| Results list     | Results exist (filtered by active filter tags)             |
| Empty state      | Query submitted but no results                            |
| Placeholder      | No search query yet ("Suchbegriff eingeben")              |
| Load more button | Results count >= current limit AND limit < 25             |

### Filter Behavior

Three inline filter tags: **Songs**, **Artists**, **Playlists**

| Active Filters | Behavior                                             |
|----------------|------------------------------------------------------|
| None           | Search type `all`, show all results                  |
| 1 filter       | Search with that specific type (e.g. `songs`)        |
| 2 filters      | Search type `all`, filter results client-side         |
| All 3 filters  | Same as none — show all results                      |

Filters toggle on click. Active filters are highlighted with the accent color.

### Device Chips (Multi-Select)

- Click chips to **toggle selection** (multiple devices can be selected)
- First selected device becomes the connector's active target
- When playing: first target receives the `play` call, additional targets receive `play_on` (streaming only)
- Same visual style and "+N" overflow as `<ytmc-player>`

### Entity Attributes Read

| Attribute                  | Usage                                |
|----------------------------|--------------------------------------|
| `target_entity_id`         | Default active device (fallback)     |
| `available_target_players` | List of selectable devices           |
| `search_results`           | Array of result objects              |
| `search_query`             | Current search term                  |
| `search_type`              | Last search type used                |
| `autoplay_enabled`         | Autoplay state                       |

### Search Result Object

Each item in `search_results`:

| Field       | Description                            |
|-------------|----------------------------------------|
| `type`      | `song`, `artist`, or `playlist`        |
| `id`        | YouTube Music item ID                  |
| `title`     | Track/playlist title (or `name`)       |
| `artist`    | Artist name (or `owner` for playlists) |
| `year`      | Release year (if available)            |
| `image_url` | Thumbnail URL (or `thumbnail`)         |

### Services Called

| Action           | HA Service                              | Parameters                                    |
|------------------|-----------------------------------------|-----------------------------------------------|
| Search           | `youtube_music_connector.search`        | `entity_id`, `query`, `search_type`, `limit`  |
| Play (primary)   | `youtube_music_connector.play`          | `entity_id`, `item_type`, `item_id`, `target_entity_id` |
| Play (additional)| `youtube_music_connector.play_on`       | `entity_id`, `item_type`, `item_id`, `target_entity_id` |
| Select device    | `media_player.select_source`            | `entity_id`, `source` (target ID)             |
| Toggle autoplay  | `youtube_music_connector.set_autoplay`  | `entity_id`, `enabled`                        |

### Pagination

- Initial search loads **5 results**
- "Load more" adds 5 more per click (max **25**)
- Limit resets to 5 on new search or Enter key

---

## Theming

Both components share the same CSS custom properties. Set them on the component element or any ancestor.

### CSS Custom Properties

| Property                | Default                    | Description                |
|-------------------------|----------------------------|----------------------------|
| `--ytmc-bg`             | `#0f1923`                  | Background color           |
| `--ytmc-surface`        | `rgba(255,255,255,0.06)`   | Card / overlay surface     |
| `--ytmc-text`           | `#f8fafc`                  | Primary text color         |
| `--ytmc-text-secondary` | `rgba(248,250,252,0.72)`   | Secondary / muted text     |
| `--ytmc-accent`         | `#4a9eff`                  | Accent / highlight color   |
| `--ytmc-accent-active`  | `#2d7fe0`                  | Active state accent        |
| `--ytmc-radius`         | `18px`                     | Border radius              |
| `--ytmc-font-family`    | `inherit`                  | Font family                |

### Example: Light Theme

```css
ytmc-player, ytmc-search-play {
  --ytmc-bg: #ffffff;
  --ytmc-surface: rgba(0, 0, 0, 0.04);
  --ytmc-text: #1a1a2e;
  --ytmc-text-secondary: rgba(26, 26, 46, 0.6);
  --ytmc-accent: #1db954;
  --ytmc-accent-active: #169c46;
  --ytmc-radius: 12px;
}
```

### Example: HA Card Integration

```html
<ha-card>
  <div style="padding: 16px;">
    <ytmc-player
      style="--ytmc-bg: var(--card-background-color);
             --ytmc-text: var(--primary-text-color);
             --ytmc-accent: var(--primary-color);">
    </ytmc-player>
  </div>
</ha-card>
```

---

## Responsive Behavior

Both components adapt to narrow viewports (< 480px):

- **Player:** Stacked layout, smaller font sizes, compact volume slider
- **Search:** Device chips scroll horizontally, search bar splits into two rows (input + filters/button)
