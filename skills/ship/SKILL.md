---
name: ship
description: "Ship completed work in this repo: patch-bump all version files, sync payload, commit, push, PR, merge, cleanup. Extends global §Completion Flow with automatic patch versioning for every fix/feature."
---

# Ship — homeassistant-youtube-music-connector

**Extends (global §Completion Flow):** Adds automatic patch version bump before every ship. Every merged change gets a version increment — no commits land on `main` without a version bump.

## Flow

Follow the global §Completion Flow with these project-specific additions:

### 1. Version bump (before creating the ship commit)

After all code changes are done and quality gates pass:

```bash
python scripts/bump_versions.py --part patch
python scripts/sync_addon_payload.py
```

- For **fixes and small changes**: always `--part patch` (automatic, no user prompt needed)
- For **new features** (minor) or **breaking changes** (major): ask the user which part to bump via AskUserQuestion
- The bump script updates: `manifest.json`, `const.py` (PANEL_MODULE_PATH query param), `config.yaml`
- The sync script copies the integration into the companion add-on payload
- After bumping, also update:
  - `README.md` — version badge line
  - `CHANGELOG.md` — new section with date and summary of changes since last version

### 2. Commit message

Use the version bump as the commit (or amend into the feature commit if there's only one):

- Single fix: `fix(scope): description` — one commit with both the fix and the bump
- Multiple changes since last version: `chore: bump version to X.Y.Z` as a separate commit after the feature commit(s)

### 3. Release (GitHub Release + tag)

After the PR is merged to `main`:

```bash
gh release create vX.Y.Z --title "vX.Y.Z" --generate-notes
```

- Always create a GitHub Release for every version bump
- Use `--generate-notes` to auto-generate release notes from merged PRs
- The HA add-on auto-detects the new version for manual user update

### 4. Continue with global flow

After the release: update local `main`, aggressive cleanup (zero leftover branches/worktrees).

## Summary of differences from global flow

| Step | Global | This repo |
|------|--------|-----------|
| Version bump | Only for major/minor | **Every ship** (patch by default) |
| Bump method | Manual | `python scripts/bump_versions.py` + `sync_addon_payload.py` |
| Release | User-triggered | **Automatic** after every merge (`gh release create`) |
| CHANGELOG | On major/minor | **Every ship** |
