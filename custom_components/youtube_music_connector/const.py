"""Constants for youtube_music_connector."""

from homeassistant.components.media_player.const import MediaType
from homeassistant.const import CONF_LANGUAGE, CONF_NAME

DOMAIN = "youtube_music_connector"
PLATFORMS = ["media_player"]

DEFAULT_NAME = "youtube_music_connector"
DEFAULT_LANGUAGE = "de"
DEFAULT_LIMIT = 5
DEFAULT_SEARCH_TYPE = "all"
DEFAULT_PROXY_PATH_PREFIX = "/api/youtube_music_connector/proxy"
DEFAULT_TOKEN_FILENAME_PREFIX = "youtube_music_connector_"
YTM_DOMAIN = "https://music.youtube.com"
YTM_BASE_API = YTM_DOMAIN + "/youtubei/v1/"
YTM_API_KEY = "AIzaSyC9XL3ZjWddXya6X74dJoCTL-WEYFDNX30"
YTM_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:88.0) Gecko/20100101 Firefox/88.0 Cobalt/Version"
SUPPORTED_LANGUAGES = {
    "ar", "cs", "de", "en", "es", "fr", "hi", "it", "ja", "ko", "nl", "pt", "ru", "tr", "ur", "zh_CN", "zh_TW"
}

CONF_HEADER_PATH = "header_path"
CONF_DEFAULT_TARGET_MEDIA_PLAYER = "default_target_media_player"

ATTR_QUERY = "query"
ATTR_SEARCH_TYPE = "search_type"
ATTR_LIMIT = "limit"
ATTR_RESULTS = "results"
ATTR_TARGET_ENTITY_ID = "target_entity_id"
ATTR_ITEM_TYPE = "item_type"
ATTR_ITEM_ID = "item_id"
ATTR_PLAY = "play"
ATTR_SONG_ID = "song_id"
ATTR_PLAYLIST_ID = "playlist_id"
ATTR_ARTIST_ID = "artist_id"
ATTR_YOUTUBE_URL = "youtube_url"
ATTR_VOLUME_PERCENT = "volume_percent"
ATTR_STREAM_URL = "stream_url"
ATTR_PROXY_URL = "proxy_url"
ATTR_ENABLED = "enabled"
ATTR_SHUFFLE_ENABLED = "shuffle_enabled"
ATTR_REPEAT_MODE = "repeat_mode"

SERVICE_SEARCH = "search"
SERVICE_RESOLVE_STREAM = "resolve_stream"
SERVICE_PLAY = "play"
SERVICE_STOP = "stop"
SERVICE_SET_AUTOPLAY = "set_autoplay"
SERVICE_SET_SHUFFLE = "set_shuffle"
SERVICE_SET_REPEAT_MODE = "set_repeat_mode"
SERVICE_EXECUTE = "execute"

REPEAT_MODE_OFF = "off"
REPEAT_MODE_FOREVER = "forever"
REPEAT_MODE_ONCE = "once"
LEGACY_REPEAT_MODE_ALL = "all"
LEGACY_REPEAT_MODE_ONE = "one"
REPEAT_MODES = [REPEAT_MODE_OFF, REPEAT_MODE_FOREVER, REPEAT_MODE_ONCE]
ACCEPTED_REPEAT_MODES = REPEAT_MODES + [LEGACY_REPEAT_MODE_ALL, LEGACY_REPEAT_MODE_ONE]


def normalize_repeat_mode(value: str | None) -> str:
    """Map public and legacy repeat values to the public runtime values."""
    if value == LEGACY_REPEAT_MODE_ALL:
        return REPEAT_MODE_FOREVER
    if value == LEGACY_REPEAT_MODE_ONE:
        return REPEAT_MODE_ONCE
    if value in REPEAT_MODES:
        return value
    return REPEAT_MODE_OFF

SEARCH_TYPE_ALL = "all"
SEARCH_TYPE_SONGS = "songs"
SEARCH_TYPE_ARTISTS = "artists"
SEARCH_TYPE_PLAYLISTS = "playlists"
SEARCH_TYPES = [
    SEARCH_TYPE_ALL,
    SEARCH_TYPE_SONGS,
    SEARCH_TYPE_ARTISTS,
    SEARCH_TYPE_PLAYLISTS,
]

ITEM_TYPE_SONG = "song"
ITEM_TYPE_ARTIST = "artist"
ITEM_TYPE_PLAYLIST = "playlist"
ITEM_TYPES = [ITEM_TYPE_SONG, ITEM_TYPE_ARTIST, ITEM_TYPE_PLAYLIST]

MEDIA_TYPE_MAP = {
    ITEM_TYPE_SONG: MediaType.MUSIC,
    ITEM_TYPE_ARTIST: MediaType.MUSIC,
    ITEM_TYPE_PLAYLIST: MediaType.PLAYLIST,
}

CONFIG_STEP_USER = "user"
CONFIG_STEP_RECONFIGURE = "reconfigure"

ERROR_AUTH = "auth"
ERROR_MISSING_HEADER = "missing_header"
ERROR_NO_RESULTS = "no_results"

TITLE_PREFIX = "YouTube Music Connector "

PANEL_URL_PATH = "youtube-music-connector"
PANEL_TITLE = "YouTube Music"
PANEL_ICON = "mdi:youtube-music"
PANEL_COMPONENT_NAME = "youtube-music-connector-panel"
PANEL_MODULE_PATH = "/api/youtube_music_connector/static/youtube-music-connector-panel.js?v=0.2.0"
