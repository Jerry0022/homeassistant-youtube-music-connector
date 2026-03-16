#!/usr/bin/with-contenv bashio
set -euo pipefail

OVERWRITE_EXISTING="$(bashio::config 'overwrite_existing')"

INTEGRATION_SOURCE="/payload/custom_components/youtube_music_connector"
LOVELACE_SOURCE="/payload/www/community/youtube-music-connector/youtube-music-connector.js"
INTEGRATION_TARGET="/config/custom_components/youtube_music_connector"
LOVELACE_TARGET_DIR="/config/www/community/youtube-music-connector"
LOVELACE_TARGET="$LOVELACE_TARGET_DIR/youtube-music-connector.js"
SOURCE_MANIFEST="$INTEGRATION_SOURCE/manifest.json"
TARGET_MANIFEST="$INTEGRATION_TARGET/manifest.json"
SOURCE_AUTH_IMPORT="$INTEGRATION_SOURCE/auth_import.py"
TARGET_AUTH_IMPORT="$INTEGRATION_TARGET/auth_import.py"

copy_tree() {
    local source="$1"
    local target="$2"

    if bashio::var.true "${OVERWRITE_EXISTING}"; then
        rm -rf "$target"
    elif [ -e "$target" ]; then
        bashio::log.fatal "Target already exists and overwrite_existing is false: $target"
    fi

    mkdir -p "$(dirname "$target")"
    cp -R "$source" "$target"
}

copy_file() {
    local source="$1"
    local target="$2"

    if bashio::var.true "${OVERWRITE_EXISTING}"; then
        rm -f "$target"
    elif [ -e "$target" ]; then
        bashio::log.fatal "Target already exists and overwrite_existing is false: $target"
    fi

    mkdir -p "$(dirname "$target")"
    cp "$source" "$target"
}

read_version() {
    local manifest="$1"
    if [ ! -f "$manifest" ]; then
        echo "missing"
        return
    fi
    sed -n 's/.*"version":[[:space:]]*"\([^"]*\)".*/\1/p' "$manifest" | head -n 1
}

has_diagnostics_marker() {
    local file="$1"
    if [ ! -f "$file" ]; then
        echo "missing"
        return
    fi
    if grep -q "Detected allowed keys" "$file"; then
        echo "yes"
    else
        echo "no"
    fi
}

if [ ! -d "$INTEGRATION_SOURCE" ]; then
    bashio::log.fatal "Bundled integration payload not found: $INTEGRATION_SOURCE"
fi

if [ ! -f "$LOVELACE_SOURCE" ]; then
    bashio::log.fatal "Bundled Lovelace payload not found: $LOVELACE_SOURCE"
fi

bashio::log.info "Bundled integration version: $(read_version "$SOURCE_MANIFEST")"
bashio::log.info "Bundled auth import diagnostics marker: $(has_diagnostics_marker "$SOURCE_AUTH_IMPORT")"
bashio::log.info "Installed integration version before copy: $(read_version "$TARGET_MANIFEST")"
bashio::log.info "Installed auth import diagnostics marker before copy: $(has_diagnostics_marker "$TARGET_AUTH_IMPORT")"

bashio::log.info "Installing bundled custom integration into /config/custom_components"
copy_tree "$INTEGRATION_SOURCE" "$INTEGRATION_TARGET"

bashio::log.info "Installing bundled Lovelace asset into /config/www/community"
copy_file "$LOVELACE_SOURCE" "$LOVELACE_TARGET"

bashio::log.info "Installed integration version after copy: $(read_version "$TARGET_MANIFEST")"
bashio::log.info "Installed auth import diagnostics marker after copy: $(has_diagnostics_marker "$TARGET_AUTH_IMPORT")"

bashio::log.warning "Installation complete. Restart Home Assistant before configuring the integration."
