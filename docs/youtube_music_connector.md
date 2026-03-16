# YouTube Music Connector

## Purpose

`youtube_music_connector` is a custom Home Assistant integration for three core functions:

1. Browse YouTube Music without a fixed type filter
2. Browse YouTube Music for a specific type: songs, artists, or playlists
3. Play or stop an audio stream on any compatible Home Assistant media player
4. Continue playback automatically with YouTube Music up-next suggestions
5. Control autoplay, shuffle, and repeat from the widget or sidebar app

The integration uses browser header authentication via a `browser.json` file. It does not depend on `ytmusicapi` at runtime.

## Authentication

The integration expects a `browser.json` file based on the official browser-auth setup:

- [ytmusicapi browser setup](https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html)

Required keys in the JSON file:

- `authorization`
- `cookie`
- `content-type`
- `x-goog-authuser`
- `x-origin`

Recommended additional keys:

- `accept`
- `accept-language`
- `origin`
- `referer`
- `user-agent`
- `x-goog-visitor-id`
- `x-youtube-bootstrap-logged-in`
- `x-youtube-client-name`
- `x-youtube-client-version`

The file must contain a single JSON object. Unknown header keys are rejected on purpose so malformed files fail early and visibly.

## Configuration Flow

The initial setup screen supports these fields:

- `Name`
- `Language`
- `Header file`
- `Default target player`

The flow validates the integration immediately with a real song search for `Bodo Wartke`.

Validation checkpoints shown in the flow:

- Header file found
- Header file loaded
- Required browser headers verified
- YouTube Music search request accepted
- Search test returned at least one song result

If validation fails, the flow shows:

- the latest completed validation checkpoints
- the concrete error message returned by the failed step

## App Assistant

The integration also exposes a sidebar app surface that now includes a browser-auth assistant.

What it does:

- explains the required DevTools capture steps
- accepts either `Copy as fetch`, raw request headers, or a direct JSON payload
- extracts the supported browser headers automatically
- writes a valid `browser.json` file into `.storage`
- tells you the resulting `/config/.storage/...json` path to use in the integration

Important limit:

The assistant cannot fully auto-detect YouTube Music headers directly after a Google login. Home Assistant and its frontend cannot read cross-site Google session cookies or authenticated request headers out of the browser automatically. That is a browser security boundary, not a missing UI feature.

Because of that, the implemented best-practice onboarding flow is:

1. log in at `music.youtube.com`
2. capture one authenticated `youtubei/v1/browse` or `youtubei/v1/search` request in DevTools
3. paste that capture into the sidebar assistant
4. let the app generate and store `browser.json`
5. use that saved file path in the integration config or reconfigure flow

## Supported Home Assistant Flow Actions

The integration supports the Home Assistant flow actions that are appropriate for this type of integration:

- Initial setup via the standard config flow
- Options flow for changing auth path, language, or default target player
- Reconfigure flow for editing the existing entry with the same validation as the initial setup

Important limitation:

Home Assistant config flows do not support arbitrary custom inline buttons inside the form body. In practice, the relevant built-in actions are:

- `Submit`
- `Cancel`
- `Reconfigure` from the integration entry
- `Configure` / `Options` from the integration entry

Because of that, this integration intentionally uses guided text, validation checkpoints, and built-in flow actions instead of custom form buttons or icon buttons inside the config dialog.

## Services

### `youtube_music_connector.search`

Browse YouTube Music.

Inputs:

- `entity_id`
- `query`
- `search_type`: `all`, `songs`, `artists`, `playlists`
- `limit`

Behavior:

- `all` performs a broad browse across songs, artists, and playlists
- specific types limit the result set accordingly

### `youtube_music_connector.resolve_stream`

Resolve a playable audio stream for a selected item.

Inputs:

- `entity_id`
- `item_type`
- `item_id`

### `youtube_music_connector.play`

Resolve a stream and send it to a target media player.

Inputs:

- `entity_id`
- `target_entity_id`
- `item_type`
- `item_id`

### `youtube_music_connector.stop`

Stop playback on the target player.

Inputs:

- `entity_id`
- `target_entity_id`

### `youtube_music_connector.set_autoplay`

Enable or disable automatic playback of the next suggested track.

Inputs:

- `entity_id`
- `enabled`

Behavior:

- for a selected song, the integration fetches YouTube Music up-next suggestions
- for a selected playlist, the integration continues through playlist tracks
- for a selected artist, the integration starts from the chosen artist result and then continues with YouTube Music suggestions based on the active track

### `youtube_music_connector.set_shuffle`

Enable or disable shuffle for the current session.

Inputs:

- `entity_id`
- `shuffle_enabled`

Behavior:

- playlist playback can start from a random track when shuffle is enabled
- artist playback can start from a random matching song when shuffle is enabled
- queued upcoming tracks are shuffled when possible

### `youtube_music_connector.set_repeat_mode`

Set repeat mode for autoplay handling.

Inputs:

- `entity_id`
- `repeat_mode`: `off`, `once`, `forever`

Behavior:

- `off`: stop after the queue is exhausted
- `once`: replay the currently active track one more time and then switch back to `off`
- `forever`: rebuild the queue when needed and continue

### `youtube_music_connector.execute`

Unified programmatic entrypoint for scripts and automations.

Inputs:

- `entity_id`
- optional `target_entity_id`
- optional `query`
- optional `search_type`
- optional `limit`
- optional `play`
- optional `item_type`
- optional `item_id`
- optional `song_id`
- optional `playlist_id`
- optional `artist_id`
- optional `youtube_url`
- optional `autoplay_enabled`
- optional `shuffle_enabled`
- optional `repeat_mode`
- optional `volume_percent`

Resolution order:

1. `song_id`
2. `playlist_id`
3. `artist_id`
4. `item_type` + `item_id`
5. `youtube_url`
6. `query`

Behavior:

- if `query` is used, the integration performs a search and selects the first normalized result
- if `play: true`, the selected item is played immediately
- if `play: false`, the selected item is only resolved and returned
- `youtube_url` supports direct YouTube Music song, playlist, and artist URLs
- `autoplay_enabled`, `shuffle_enabled`, `repeat_mode`, and `volume_percent` can be set in the same command

Example automation action:

```yaml
action: youtube_music_connector.execute
data:
  entity_id: media_player.youtube_music_connector
  target_entity_id: media_player.chromecast_tv
  query: "Bodo Wartke"
  search_type: songs
  limit: 5
  play: true
  autoplay_enabled: true
  shuffle_enabled: false
  repeat_mode: forever
  volume_percent: 35
```

Example with direct playlist URL:

```yaml
action: youtube_music_connector.execute
data:
  entity_id: media_player.youtube_music_connector
  target_entity_id: media_player.chromecast_tv
  youtube_url: "https://music.youtube.com/playlist?list=PL..."
  play: true
  autoplay_enabled: true
  shuffle_enabled: true
  repeat_mode: forever
```

## Runtime Notes

- Search and browse use direct `youtubei/v1` requests against YouTube Music.
- Playback stream resolution is handled separately through `pytubefix`.
- The integration caches validated browser headers in memory after the first successful load.
- If the browser header file changes, use `Reconfigure` or `Options` so the integration retests the updated file.
- Target player lists only include media players that advertise Home Assistant `play_media` support and are currently real, available entities, not restored leftovers.
- Autoplay is event-driven: when the selected target player moves from `playing` to `idle` or `off`, the integration can start the next suggested track automatically.
- Shuffle and repeat are runtime controls and can be changed while playback is already active.

## Troubleshooting

### Header file not found

Check the full absolute path entered in the flow.

### Header file is not valid JSON

The file content must be valid JSON and start with a top-level `{ ... }` object.

### Unexpected browser header keys

Remove stray keys from the exported file. This is a common reason for opaque YouTube Music request failures.

### Search request fails with HTTP 400

Check that the browser headers were copied from an authenticated `music.youtube.com` session and still represent a valid logged-in session.

### Search request succeeds but returns no results

Re-export the browser headers. The request was accepted, but the auth or account context is not useful enough for stable search responses.
