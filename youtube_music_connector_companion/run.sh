#!/usr/bin/with-contenv bashio
set -euo pipefail

REPOSITORY="$(bashio::config 'repository')"
REF="$(bashio::config 'ref')"
INSTALL_INTEGRATION="$(bashio::config 'install_integration')"
INSTALL_LOVELACE="$(bashio::config 'install_lovelace')"
OVERWRITE_EXISTING="$(bashio::config 'overwrite_existing')"

WORKDIR="/tmp/youtube-music-connector"
INTEGRATION_SOURCE="$WORKDIR/custom_components/youtube_music_connector"
LOVELACE_SOURCE="$WORKDIR/www/community/youtube-music-connector/youtube-music-connector.js"
INTEGRATION_TARGET="/config/custom_components/youtube_music_connector"
LOVELACE_TARGET_DIR="/config/www/community/youtube-music-connector"
LOVELACE_TARGET="$LOVELACE_TARGET_DIR/youtube-music-connector.js"

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

cleanup() {
    rm -rf "$WORKDIR"
}

trap cleanup EXIT

bashio::log.info "Cloning repository: $REPOSITORY (ref: $REF)"
git clone --depth 1 --branch "$REF" "$REPOSITORY" "$WORKDIR"

if bashio::var.true "${INSTALL_INTEGRATION}"; then
    if [ ! -d "$INTEGRATION_SOURCE" ]; then
        bashio::log.fatal "Integration source not found in repository: $INTEGRATION_SOURCE"
    fi

    bashio::log.info "Installing custom integration into /config/custom_components"
    copy_tree "$INTEGRATION_SOURCE" "$INTEGRATION_TARGET"
fi

if bashio::var.true "${INSTALL_LOVELACE}"; then
    if [ ! -f "$LOVELACE_SOURCE" ]; then
        bashio::log.fatal "Lovelace asset not found in repository: $LOVELACE_SOURCE"
    fi

    bashio::log.info "Installing Lovelace asset into /config/www/community"
    copy_file "$LOVELACE_SOURCE" "$LOVELACE_TARGET"
fi

bashio::log.warning "Installation complete. Restart Home Assistant before configuring the integration."
