# YouTube Music Connector

This Home Assistant add-on installs or updates the `youtube_music_connector` custom integration together with its shipped UI surfaces from this repository into your Home Assistant configuration directory.

## What it does

- Copies `custom_components/youtube_music_connector` into `/config/custom_components`
- Copies `www/community/youtube-music-connector/youtube-music-connector.js` into `/config/www/community/youtube-music-connector`
- Includes the built-in sidebar panel UI that is shipped inside the integration frontend
- Lets you pin a branch or tag through the `ref` option

## Typical usage

1. Add this repository to the Home Assistant app/add-on store.
2. Install **YouTube Music Connector**.
3. Leave the default options in place unless you want a different branch or tag.
4. Start the add-on once to copy the files into `/config`.
5. Restart Home Assistant.
6. Add the integration from Settings -> Devices & Services.

## Notes

- This add-on installs the integration files, including the sidebar search/playback UI and the Lovelace widget.
- If you prefer HACS, you can install the integration directly from the same GitHub repository instead.
