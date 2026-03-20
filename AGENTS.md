# AGENTS instructions for this repository

## Scope
These instructions apply to the whole repository.

## Product and platform rules
- This repository hosts both a Home Assistant custom integration and a companion Home Assistant add-on.
- Keep the custom integration HACS-compatible.
- Keep the add-on repository-compatible through `repository.yaml` and a valid add-on folder at the repository root.
- Always prefer current Home Assistant architecture:
  - Config entries and UI config flows
  - Async-first Python code
  - No deprecated Home Assistant APIs
  - Sidebar UI through Home Assistant panel APIs, not legacy frontend patterns

## Code standards
- Python: type hints, focused modules, constants in `const.py`, and no blocking I/O in async code.
- Frontend: modern web component patterns only.
- Add-on logic must be deterministic and safe to re-run against an existing Home Assistant config directory.
- Never hardcode secrets; browser auth and user credentials must stay in Home Assistant-managed storage.

## Versioning and release hygiene
- For every repository change that affects shipped files, bump versions in both:
  - `custom_components/youtube_music_connector/manifest.json`
  - `youtube_music_connector_companion/config.yaml`
- Keep the integration and add-on versions aligned.
- Use semantic versioning:
  - bump patch for fixes, docs, repo maintenance, and branding-only changes
  - bump minor for new functionality
  - bump major only when explicitly requested
- Prefer using `python scripts/bump_versions.py --part <patch|minor|major>` instead of editing version strings manually. This script also syncs the add-on payload automatically.
- Treat version updates as mandatory release hygiene:
  1. Bump both shipped versions in the same change.
  2. Keep `PANEL_MODULE_PATH` cache-busting aligned with the integration version.
  3. Check the repo for stale version strings before finishing.

## Release checklist
Every change that affects shipped files must go through this full flow:
1. **Version bump**: Run `python scripts/bump_versions.py --part <patch|minor|major>` (syncs payload automatically).
2. **Verify alignment**: Run `python scripts/bump_versions.py --check` and `python scripts/sync_addon_payload.py --check`.
3. **Commit, push, PR, merge**: Create a PR against `main`, merge it.
4. **GitHub Release**: Create a release with `gh release create vX.Y.Z --target main` — this is required for:
   - **HACS** to detect the new integration version.
   - **HA add-on store** to offer the update to users.
5. **Verify end-to-end**: After the release, both the add-on AND the integration must show the new version in Home Assistant. The add-on's `run.sh` copies the payload to `/config/custom_components/`, so a stale payload means the integration stays on the old version even when the add-on updates.

Skipping any step (especially the GitHub Release or payload sync) will cause version mismatches between add-on and integration.

## Branding rules
- Keep add-on icons in `youtube_music_connector_companion/`.
- Keep integration brand assets in `custom_components/youtube_music_connector/brand/`.
- When updating the visual identity, regenerate all derived PNG files from `scripts/generate_branding_assets.py` so add-on and integration branding stay in sync.

## Add-on payload rules
- The companion add-on must install bundled files from `youtube_music_connector_companion/payload/`, not clone the repository at runtime.
- After changing `custom_components/youtube_music_connector/` or `www/community/youtube-music-connector/`, run `python scripts/sync_addon_payload.py`.
- Before finishing, verify payload sync with `python scripts/sync_addon_payload.py --check`.
- Do not directly copy or patch repository files into a live Home Assistant config directory such as `H:\custom_components` or `H:\www`.
- Treat the live Home Assistant installation as a deployment target, not a development workspace.
- For add-on and integration changes, rely on the normal Home Assistant update/install flow instead of local filesystem injection unless the user explicitly asks for one-off emergency recovery.

## Documentation rules
- Keep README practical and installation-focused.
- Document both install channels:
  - HACS integration
  - Home Assistant add-on repository
- Keep repository and skill documentation in English by default.

## Skills in this repository
- Keep reusable Codex guidance in `skills/`.
- Repository skills must reinforce modern Home Assistant patterns and mandatory version bumps.
