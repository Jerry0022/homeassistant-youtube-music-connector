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

### Option 1: Home Assistant app / add-on

Add this GitHub repository to the Home Assistant app/add-on store as a repository, install `YouTube Music Connector Companion`, then start it once. The app copies the integration files into your Home Assistant `/config` directory so you can add the integration normally afterward.

### Option 2: HACS custom repository

Add this repository to HACS as an `Integration`, then install `YouTube Music Connector`.

### Option 3: Manual install

Copy `custom_components/youtube_music_connector` into your Home Assistant `custom_components` folder.

### Lovelace widget

If you install manually or through HACS, copy `www/community/youtube-music-connector/youtube-music-connector.js` into your Home Assistant `www/community/youtube-music-connector/` folder and add this resource:

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

## Repository Types

This repository now supports both Home Assistant installation paths:

- HACS custom integration repository
- Home Assistant app / add-on repository via `repository.yaml`

## Documentation

Detailed integration documentation is available here:

- [docs/youtube_music_connector.md](docs/youtube_music_connector.md)
