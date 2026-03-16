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
INSTALL_STATE_PATH="/config/.storage/youtube_music_connector_installer.json"

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

write_install_state() {
    local source_version="$1"
    local target_version="$2"
    local diagnostics_marker="$3"
    local lovelace_exists="$4"

    mkdir -p "$(dirname "$INSTALL_STATE_PATH")"
    cat > "$INSTALL_STATE_PATH" <<EOF
{
  "installer": "youtube_music_connector_companion",
  "timestamp_utc": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "source_version": "$source_version",
  "target_version": "$target_version",
  "auth_import_diagnostics_marker": "$diagnostics_marker",
  "lovelace_asset_present": $lovelace_exists
}
EOF
}

verify_install() {
    local source_version="$1"
    local target_version="$2"
    local diagnostics_marker="$3"

    if [ "$target_version" != "$source_version" ]; then
        bashio::log.fatal "Integration copy verification failed: source version $source_version, target version $target_version"
    fi

    if [ "$diagnostics_marker" != "yes" ]; then
        bashio::log.fatal "Integration copy verification failed: auth import diagnostics marker missing in target"
    fi

    if [ ! -f "$INTEGRATION_TARGET/__init__.py" ] || [ ! -f "$INTEGRATION_TARGET/config_flow.py" ]; then
        bashio::log.fatal "Integration copy verification failed: critical integration files are missing in target"
    fi

    if [ ! -f "$LOVELACE_TARGET" ]; then
        bashio::log.fatal "Lovelace copy verification failed: target asset missing"
    fi
}

if [ ! -d "$INTEGRATION_SOURCE" ]; then
    bashio::log.fatal "Bundled integration payload not found: $INTEGRATION_SOURCE"
fi

if [ ! -f "$LOVELACE_SOURCE" ]; then
    bashio::log.fatal "Bundled Lovelace payload not found: $LOVELACE_SOURCE"
fi

SOURCE_VERSION="$(read_version "$SOURCE_MANIFEST")"

bashio::log.info "Bundled integration version: $SOURCE_VERSION"
bashio::log.info "Bundled auth import diagnostics marker: $(has_diagnostics_marker "$SOURCE_AUTH_IMPORT")"
bashio::log.info "Installed integration version before copy: $(read_version "$TARGET_MANIFEST")"
bashio::log.info "Installed auth import diagnostics marker before copy: $(has_diagnostics_marker "$TARGET_AUTH_IMPORT")"

bashio::log.info "Installing bundled custom integration into /config/custom_components"
copy_tree "$INTEGRATION_SOURCE" "$INTEGRATION_TARGET"

bashio::log.info "Installing bundled Lovelace asset into /config/www/community"
copy_file "$LOVELACE_SOURCE" "$LOVELACE_TARGET"

TARGET_VERSION="$(read_version "$TARGET_MANIFEST")"
TARGET_DIAGNOSTICS_MARKER="$(has_diagnostics_marker "$TARGET_AUTH_IMPORT")"

bashio::log.info "Installed integration version after copy: $TARGET_VERSION"
bashio::log.info "Installed auth import diagnostics marker after copy: $TARGET_DIAGNOSTICS_MARKER"

verify_install "$SOURCE_VERSION" "$TARGET_VERSION" "$TARGET_DIAGNOSTICS_MARKER"
write_install_state "$SOURCE_VERSION" "$TARGET_VERSION" "$TARGET_DIAGNOSTICS_MARKER" true
bashio::log.info "Wrote installer state to $INSTALL_STATE_PATH"

bashio::log.warning "Installation complete. Restart Home Assistant before configuring the integration."
