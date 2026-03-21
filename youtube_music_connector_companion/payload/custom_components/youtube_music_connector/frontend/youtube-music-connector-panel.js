/**
 * Sidebar panel for YouTube Music Connector.
 *
 * Embeds <ytmc-player>, <ytmc-search-play>, and a Browser Auth Assistant
 * for initial setup and credential refresh.
 */
class YoutubeMusicConnectorPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._entityId = null;
    this._rendered = false;
    this._importText = "";
    this._fileName = "browser_youtube_music_connector.json";
    this._assistantStatus = "";
    this._assistantError = "";
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

  /* ── Browser Auth Import ── */

  async _importBrowserAuth() {
    const text = this._importText.trim();
    if (!text) {
      this._setAssistantError("Paste a \"Copy as fetch\" snippet or raw request headers from music.youtube.com.");
      return;
    }

    this._setAssistantStatus("Extracting and saving...");
    this._setAssistantError("");

    try {
      const resp = await fetch("/api/youtube_music_connector/import_browser_auth", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${this._hass?.auth?.data?.access_token || ""}`,
        },
        body: JSON.stringify({ raw_text: text, file_name: this._fileName }),
      });

      if (!resp.ok) {
        const errText = await resp.text();
        this._setAssistantError(errText || `HTTP ${resp.status}`);
        this._setAssistantStatus("");
        return;
      }

      const data = await resp.json();
      this._setAssistantStatus(`Saved to ${data.config_path || data.host_path}`);
      this._setAssistantError("");
      this._importText = "";
      const ta = this.shadowRoot.querySelector("#import_text");
      if (ta) ta.value = "";
    } catch (err) {
      this._setAssistantError(String(err));
      this._setAssistantStatus("");
    }
  }

  _setAssistantStatus(msg) {
    this._assistantStatus = msg;
    const el = this.shadowRoot.querySelector("#assistant_status");
    if (el) el.textContent = msg;
  }

  _setAssistantError(msg) {
    this._assistantError = msg;
    const el = this.shadowRoot.querySelector("#assistant_error");
    if (el) {
      el.textContent = msg;
      el.style.display = msg ? "block" : "none";
    }
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
        h1 { font-size: 1.6rem; font-weight: 600; margin: 0 0 8px; }
        .subtitle { color: var(--ytmc-text-muted); font-size: 0.9rem; margin: 0 0 24px; }

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

        /* Browser Auth Assistant */
        .auth-card {
          background: var(--ytmc-surface);
          border: 1px solid var(--ytmc-border);
          border-radius: var(--ytmc-radius);
          padding: 20px;
          margin-bottom: 24px;
        }
        .auth-card h2 { font-size: 1.1rem; font-weight: 600; margin: 0 0 12px; }
        .auth-card .note {
          background: rgba(255,68,68,0.08);
          border-left: 3px solid var(--ytmc-accent);
          padding: 12px 16px;
          border-radius: 0 8px 8px 0;
          margin-bottom: 16px;
          font-size: 0.85rem;
          line-height: 1.5;
        }
        .auth-card .note strong { color: var(--ytmc-text); }
        .auth-card ol {
          padding-left: 20px;
          margin: 0 0 16px;
          font-size: 0.88rem;
          line-height: 1.7;
          color: var(--ytmc-text-muted);
        }
        .auth-card ol code {
          background: rgba(255,255,255,0.06);
          padding: 1px 5px;
          border-radius: 4px;
          font-size: 0.82rem;
        }
        .auth-card ol kbd {
          display: inline-block;
          background: rgba(255,255,255,0.1);
          border: 1px solid rgba(255,255,255,0.2);
          border-radius: 4px;
          padding: 1px 6px;
          font-family: monospace;
          font-size: 0.82rem;
          box-shadow: 0 1px 0 rgba(255,255,255,0.1);
        }
        .auth-card textarea {
          width: 100%;
          min-height: 120px;
          background: var(--ytmc-bg);
          color: var(--ytmc-text);
          border: 1px solid var(--ytmc-border);
          border-radius: 8px;
          padding: 12px;
          font-family: monospace;
          font-size: 0.82rem;
          resize: vertical;
          box-sizing: border-box;
          margin-bottom: 12px;
        }
        .auth-card textarea::placeholder { color: var(--ytmc-text-muted); }
        .auth-card textarea:focus { outline: none; border-color: var(--ytmc-accent); }
        .file-row {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 16px;
          font-size: 0.85rem;
        }
        .file-row input {
          flex: 1;
          background: var(--ytmc-bg);
          color: var(--ytmc-text);
          border: 1px solid var(--ytmc-border);
          border-radius: 8px;
          padding: 8px 12px;
          font-size: 0.85rem;
        }
        .file-row input:focus { outline: none; border-color: var(--ytmc-accent); }
        .file-row .hint { color: var(--ytmc-text-muted); white-space: nowrap; }
        .import-btn {
          display: block;
          width: 100%;
          padding: 12px;
          background: linear-gradient(135deg, var(--ytmc-accent), #cc3333);
          color: #fff;
          border: none;
          border-radius: 8px;
          font-size: 0.95rem;
          font-weight: 600;
          cursor: pointer;
          transition: opacity 0.15s;
        }
        .import-btn:hover { opacity: 0.9; }
        .status-msg {
          margin-top: 12px;
          font-size: 0.85rem;
          color: var(--ytmc-text-muted);
        }
        .error-msg {
          margin-top: 12px;
          padding: 10px 14px;
          background: rgba(255,68,68,0.1);
          border: 1px solid rgba(255,68,68,0.3);
          border-radius: 8px;
          font-size: 0.85rem;
          color: #ff6666;
          display: none;
        }
        .guide-link {
          display: inline-block;
          margin-top: 12px;
          color: var(--ytmc-accent);
          font-size: 0.85rem;
          text-decoration: none;
        }
        .guide-link:hover { text-decoration: underline; }

        @media (max-width: 900px) {
          .grid { grid-template-columns: 1fr; }
          .panel-container { padding: 16px; }
        }
      </style>
      <div class="panel-container">
        <h1>YouTube Music</h1>
        <p class="subtitle">Search, play, and control music across your devices.</p>

        <div class="auth-card">
          <h2>Browser Auth Assistant</h2>
          <div class="note">
            <strong>Automatic header extraction after Google login is not technically reliable inside Home Assistant.</strong>
            Google session cookies and request headers stay inside the browser context. The robust approach is: capture one authenticated request in DevTools, paste it here, let the app extract and store the valid browser.json automatically.
          </div>
          <ol>
            <li>Open <a href="https://music.youtube.com" target="_blank" rel="noopener" style="color:var(--ytmc-accent)">music.youtube.com</a> and log in.</li>
            <li>Open DevTools (<kbd>F12</kbd>), switch to the <strong>Network</strong> tab.</li>
            <li>On the YouTube Music page, browse or search something so requests appear.</li>
            <li>Filter by <code>youtubei/v1</code> and click any request (e.g. <code>browse</code> or <code>search</code>).</li>
            <li>In Chromium: go to the <strong>Headers</strong> tab \u2192 <strong>Request Headers</strong> section. Right-click the request and choose <code>Copy as fetch</code>, or manually copy the raw <code>Request Headers</code>.</li>
            <li>Paste the text below and click <strong>Extract and Save</strong>.</li>
            <li>Use the saved <code>/config/.storage/...json</code> path in the integration config or reconfigure flow.</li>
          </ol>
          <textarea id="import_text" placeholder="Paste Copy as fetch or raw Request Headers here\n\nExample (raw Request Headers):\n\nAccept: */*\nAccept-Language: de,en-US;q=0.9,en;q=0.8\nAuthorization: SAPISIDHASH 1234567890_abc...\nContent-Type: application/json\nCookie: HSID=AaBbCc...; SSID=DdEeFf...; SID=GgHhIi...; SAPISID=JjKkLl...; __Secure-1PSID=MmNnOo...; __Secure-3PSID=PpQqRr...; LOGIN_INFO=...\nOrigin: https://music.youtube.com\nReferer: https://music.youtube.com/\nUser-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...\nX-Goog-AuthUser: 0\nX-Goog-Visitor-Id: CgtABC123..."></textarea>
          <div class="file-row">
            <input type="text" id="file_name" value="${this._fileName}">
            <span class="hint">Saved in <code>/config/.storage/</code></span>
          </div>
          <button class="import-btn" id="import_btn">Extract and Save</button>
          <div class="status-msg" id="assistant_status">${this._assistantStatus}</div>
          <div class="error-msg" id="assistant_error" style="display:${this._assistantError ? "block" : "none"}">${this._assistantError}</div>
          <a class="guide-link" href="https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html" target="_blank" rel="noopener">Open official browser-auth guide</a>
        </div>

        ${this._entityId
          ? `<div class="grid">
               <ytmc-player></ytmc-player>
               <ytmc-search-play></ytmc-search-play>
             </div>`
          : `<div class="no-entity">No YouTube Music Connector entity found. Please set up the integration first.</div>`
        }
      </div>
    `;

    // Bind auth assistant events
    root.querySelector("#import_text")?.addEventListener("input", (e) => { this._importText = e.target.value; });
    root.querySelector("#file_name")?.addEventListener("input", (e) => { this._fileName = e.target.value; });
    root.querySelector("#import_btn")?.addEventListener("click", () => this._importBrowserAuth());

    // Pass hass + entityId to child components
    if (this._entityId && this._hass) {
      const player = root.querySelector("ytmc-player");
      const search = root.querySelector("ytmc-search-play");
      if (player) { player.entityId = this._entityId; player.hass = this._hass; }
      if (search) { search.entityId = this._entityId; search.hass = this._hass; }
    }
  }
}

customElements.define("youtube-music-connector-panel", YoutubeMusicConnectorPanel);
