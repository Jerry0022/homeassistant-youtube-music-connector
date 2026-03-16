---
name: homeassistant-youtube-modern
description: Implement or update the Home Assistant YouTube Music Connector repository with modern Home Assistant integration patterns, companion add-on changes, brand assets, and mandatory version bumps. Use when working in this repository on the custom integration, the companion add-on, release/version hygiene, HACS compatibility, or repository branding.
---

# Home Assistant YouTube Modern

## Overview

Use modern Home Assistant patterns for both shipped surfaces in this repository:
- the `youtube_music_connector` custom integration
- the `youtube_music_connector_companion` add-on

Keep changes HACS-compatible, add-on-repository-compatible, and versioned in the same commit.

## Workflow

1. Read `AGENTS.md` before making changes.
2. Treat `custom_components/youtube_music_connector/manifest.json` and `youtube_music_connector_companion/config.yaml` as release-critical files.
3. Bump versions for every shipped change:
   - patch for fixes, docs, brand assets, and maintenance
   - minor for new functionality
   - major only on explicit owner request
4. Prefer `python scripts/bump_versions.py --part <patch|minor|major>` instead of editing version strings manually.
5. Keep the panel cache-busting query string aligned with the integration version.
6. Keep add-on branding in `youtube_music_connector_companion/` and integration branding in `custom_components/youtube_music_connector/brand/`.
7. If branding changes, regenerate the PNG files with `python scripts/generate_branding_assets.py`.
8. Keep README instructions accurate for both installation paths:
   - HACS custom integration
   - Home Assistant add-on repository

## Implementation Rules

- Use config entries, async-first I/O, and current Home Assistant APIs.
- Keep the add-on safe to re-run against an existing Home Assistant configuration directory.
- Do not hardcode secrets or tokens.
- Keep repository and skill documentation in English by default.
- Keep integration and add-on versions aligned.

## Checklist

- [ ] `AGENTS.md` rules were followed.
- [ ] Integration and add-on versions were bumped together.
- [ ] `python scripts/bump_versions.py --check` passes.
- [ ] Brand assets still exist in both shipped locations.
- [ ] README still matches the actual install/update flow.
