# Home Assistant YouTube Music Connector

Custom Home Assistant integration for browsing YouTube Music, playing results on compatible media players, and controlling playback from a sidebar app and Lovelace widget.

## Features

- Browser-auth based YouTube Music access via `browser.json`
- Search across songs, artists, and playlists
- Direct playback on compatible `media_player` entities
- Autoplay, shuffle, and repeat controls
- Sidebar app for browsing and playback
- Lovelace widget for searching and playing from dashboards
- Script / automation friendly service interface via `youtube_music_connector.execute`

## Repository Layout

This repository contains two Home Assistant artifacts:

- Integration: [`custom_components/youtube_music_connector`](custom_components/youtube_music_connector)
- Lovelace widget: [`www/community/youtube-music-connector/youtube-music-connector.js`](www/community/youtube-music-connector/youtube-music-connector.js)

## Installation

### Custom component

Copy `custom_components/youtube_music_connector` into your Home Assistant `custom_components` folder.

### Lovelace widget

Copy `www/community/youtube-music-connector/youtube-music-connector.js` into your Home Assistant `www/community/youtube-music-connector/` folder and add this resource:

```yaml
url: /local/community/youtube-music-connector/youtube-music-connector.js
type: module
```

## Configuration

The integration uses browser authentication via a `browser.json` file. The expected format follows the official browser-auth approach documented by `ytmusicapi`:

- [ytmusicapi browser setup](https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html)

Required keys:

- `authorization`
- `cookie`
- `content-type`
- `x-goog-authuser`
- `x-origin`

The integration config flow validates the file immediately with a real song search.

## Services

Main service for automations and scripts:

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

Supported repeat modes:

- `off`
- `once`
- `forever`

## Publishing

This repository is structured so you can initialize Git directly at the root and publish it as its own GitHub repository.

Recommended repository name:

- `homeassistant-youtube-music-connector`

## Documentation

Detailed integration documentation is available here:

- [docs/youtube_music_connector.md](docs/youtube_music_connector.md)
