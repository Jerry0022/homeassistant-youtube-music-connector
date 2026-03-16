# Changelog

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
