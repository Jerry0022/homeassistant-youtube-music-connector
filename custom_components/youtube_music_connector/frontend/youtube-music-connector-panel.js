/**
 * Sidebar panel for YouTube Music Connector.
 *
 * Thin wrapper that discovers the connector entity and embeds
 * <ytmc-player> and <ytmc-search-play> side by side.
 */
class YoutubeMusicConnectorPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._entityId = null;
    this._rendered = false;
  }

  set hass(hass) {
    this._hass = hass;
    this._resolveEntity();

    const player = this.shadowRoot.querySelector("ytmc-player");
    const search = this.shadowRoot.querySelector("ytmc-search-play");
    if (player) player.hass = hass;
    if (search) search.hass = hass;

    if (!this._rendered) this._render();
  }

  /* ── Entity discovery ── */

  _resolveEntity() {
    const states = this._hass?.states;
    if (!states) return;

    // Already resolved and still valid
    if (this._entityId && states[this._entityId]) return;

    const candidates = Object.keys(states)
      .filter((id) => id.startsWith("media_player."))
      .filter((id) => this._isConnector(id));

    this._entityId = candidates[0] || null;
  }

  _isConnector(entityId) {
    const s = this._hass?.states?.[entityId];
    if (!s) return false;
    if (entityId.startsWith("media_player.youtube_music_connector")) return true;
    const a = s.attributes || {};
    return (
      a.is_youtube_music_connector === true ||
      Array.isArray(a.available_target_players) ||
      Object.prototype.hasOwnProperty.call(a, "target_entity_id")
    );
  }

  /* ── Render ── */

  _render() {
    this._rendered = true;
    const root = this.shadowRoot;

    root.innerHTML = `
      <style>
        :host {
          display: block;
          --ytmc-bg: #0e1117;
          --ytmc-surface: #161b22;
          --ytmc-surface-hover: #1c2129;
          --ytmc-border: #30363d;
          --ytmc-text: #e6edf3;
          --ytmc-text-muted: #8b949e;
          --ytmc-accent: #ff4444;
          --ytmc-accent-hover: #ff6666;
          --ytmc-radius: 12px;
          background: var(--ytmc-bg);
          color: var(--ytmc-text);
          min-height: 100vh;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        .panel-container {
          max-width: 1400px;
          margin: 0 auto;
          padding: 24px;
        }
        h1 {
          font-size: 1.6rem;
          font-weight: 600;
          margin: 0 0 8px;
        }
        .subtitle {
          color: var(--ytmc-text-muted);
          font-size: 0.9rem;
          margin: 0 0 24px;
        }
        .grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 24px;
          align-items: start;
        }
        .no-entity {
          color: var(--ytmc-text-muted);
          text-align: center;
          padding: 48px 16px;
          font-size: 1.1rem;
        }
        @media (max-width: 900px) {
          .grid {
            grid-template-columns: 1fr;
          }
          .panel-container {
            padding: 16px;
          }
        }
      </style>
      <div class="panel-container">
        <h1>YouTube Music</h1>
        <p class="subtitle">Search, play, and control music across your devices.</p>
        ${this._entityId
          ? `<div class="grid">
               <ytmc-player></ytmc-player>
               <ytmc-search-play></ytmc-search-play>
             </div>`
          : `<div class="no-entity">No YouTube Music Connector entity found. Please set up the integration first.</div>`
        }
      </div>
    `;

    if (this._entityId && this._hass) {
      const player = root.querySelector("ytmc-player");
      const search = root.querySelector("ytmc-search-play");
      if (player) {
        player.entityId = this._entityId;
        player.hass = this._hass;
      }
      if (search) {
        search.entityId = this._entityId;
        search.hass = this._hass;
      }
    }
  }
}

customElements.define("youtube-music-connector-panel", YoutubeMusicConnectorPanel);
