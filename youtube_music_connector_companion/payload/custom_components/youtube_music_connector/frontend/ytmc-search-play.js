/**
 * <ytmc-search-play> — YouTube Music Connector: Device Selector + Search + Results
 *
 * Usage:
 *   const el = document.createElement("ytmc-search-play");
 *   el.entityId = "media_player.youtube_music_connector";
 *   el.hass = hassObject;
 *   container.appendChild(el);
 *
 * CSS custom properties — same as <ytmc-player>:
 *   --ytmc-bg, --ytmc-surface, --ytmc-text, --ytmc-text-secondary,
 *   --ytmc-accent, --ytmc-accent-active, --ytmc-radius, --ytmc-font-family
 */
class YtmcSearchPlay extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._entityId = "";
    this._hass = null;
    this._renderSig = "";
    this._draft = { query: "", filters: new Set(), limit: 5 }; // empty = all
    this._selectedTargets = new Set(); // multi-select device chips
    this._recentTargets = []; // sorted by last selection
    this._showAllDevices = false;
    this._searchLoading = false;
    this._interacting = false;
    this._excludeDevices = [];
  }

  /* ── Lovelace card interface ── */
  static getConfigElement() { return document.createElement("ytmc-search-play-editor"); }
  static getStubConfig() { return { entity: "media_player.youtube_music_connector" }; }
  setConfig(config) {
    this._config = config;
    if (config.entity) this.entityId = config.entity;
    if (Array.isArray(config.exclude_devices)) this._excludeDevices = config.exclude_devices;
  }
  getCardSize() { return 5; }

  set entityId(val) { this._entityId = val; this._tryRender(); }
  get entityId() { return this._entityId; }
  set excludeDevices(val) { this._excludeDevices = Array.isArray(val) ? val : []; this._tryRender(); }
  get excludeDevices() { return this._excludeDevices; }
  set hass(hass) { this._hass = hass; if (!this._interacting) this._tryRender(); }
  get hass() { return this._hass; }

  /* ── state helpers ── */
  get _entity() { return this._hass?.states?.[this._entityId]; }
  get _attrs() { return this._entity?.attributes || {}; }

  _isTargetActive(tid, fallback) {
    if (this._selectedTargets.size > 0) return this._selectedTargets.has(tid);
    return tid === fallback;
  }

  _syncGroupFromBackend() {
    const backendGroup = this._attrs.group_targets || [];
    const primary = this._attrs.target_entity_id;
    if (this._selectedTargets.size === 0 && backendGroup.length > 0) {
      if (primary) this._selectedTargets.add(primary);
      backendGroup.forEach(t => this._selectedTargets.add(t));
    }
  }

  _targetFriendly(tid) {
    if (!tid) return tid;
    const s = this._hass?.states?.[tid];
    return s?.attributes?.friendly_name || tid.replace("media_player.", "");
  }

  /* ── service calls ── */
  async _search() {
    if (!this._draft.query.trim()) return;
    this._searchLoading = true;
    this._render();
    try {
      await this._hass.callService("youtube_music_connector", "search", {
        entity_id: this._entityId,
        query: this._draft.query.trim(),
        search_type: this._effectiveSearchType(),
        limit: this._draft.limit,
      });
    } catch (err) { console.error("ytmc search failed", err); }
    finally { this._searchLoading = false; this._renderSig = ""; this._tryRender(); }
  }

  async _loadMore() { this._draft.limit = Math.min(this._draft.limit + 5, 25); await this._search(); }

  async _play(itemType, itemId) {
    const targets = this._activeTargets();
    if (targets.length === 0) return;
    // First target: normal play (sets manager state, autoplay context)
    await this._hass.callService("youtube_music_connector", "play", {
      entity_id: this._entityId, item_type: itemType, item_id: itemId,
      target_entity_id: targets[0],
    });
    // Additional targets: play_on (stream only, no state change)
    for (let i = 1; i < targets.length; i++) {
      await this._hass.callService("youtube_music_connector", "play_on", {
        entity_id: this._entityId, item_type: itemType, item_id: itemId,
        target_entity_id: targets[i],
      });
    }
  }

  _activeTargets() {
    // If multi-select has entries, use those; otherwise fall back to connector's current target
    if (this._selectedTargets.size > 0) return [...this._selectedTargets];
    const t = this._attrs.target_entity_id;
    return t ? [t] : [];
  }

  async _toggleTarget(entityId) {
    if (this._selectedTargets.size === 0) {
      const current = this._attrs.target_entity_id;
      if (current && current !== entityId) this._selectedTargets.add(current);
      this._selectedTargets.add(entityId);
    } else if (this._selectedTargets.has(entityId)) {
      this._selectedTargets.delete(entityId);
      if (this._selectedTargets.size === 0) {
        await this._hass.callService("youtube_music_connector", "set_group_targets", { entity_id: this._entityId, group_targets: [] });
        this._renderSig = "";
        this._tryRender();
        return;
      }
    } else {
      this._selectedTargets.add(entityId);
    }
    this._recentTargets = [entityId, ...this._recentTargets.filter(t => t !== entityId)];
    const targets = [...this._selectedTargets];
    const primary = targets[0];
    const group = targets.slice(1);
    await this._hass.callService("media_player", "select_source", { entity_id: this._entityId, source: primary });
    await this._hass.callService("youtube_music_connector", "set_group_targets", { entity_id: this._entityId, group_targets: group });
    this._renderSig = "";
    this._tryRender();
  }

  _sortedSources(sources, activeTarget) {
    const recent = this._recentTargets.filter(t => sources.includes(t));
    const rest = sources.filter(t => !recent.includes(t));
    const sorted = [...recent, ...rest];
    if (activeTarget && sorted.includes(activeTarget)) {
      const idx = sorted.indexOf(activeTarget);
      if (idx > 0) { sorted.splice(idx, 1); sorted.unshift(activeTarget); }
    }
    return sorted;
  }

  _renderDeviceChips(sources, activeTarget) {
    const sorted = this._sortedSources(sources, activeTarget);
    const visible = this._showAllDevices ? sorted : sorted.slice(0, 3);
    const hiddenCount = sorted.length - visible.length;
    return `
      <div class="chips-row">
        ${visible.map((t) => `
          <button class="chip ${this._isTargetActive(t, activeTarget) ? "active" : ""}" data-target="${this._esc(t)}">
            <span class="chip-icon">
              <ha-icon icon="mdi:${t.includes("chromecast") || t.includes("tv") ? "television" : "speaker"}"></ha-icon>
            </span>
            ${this._esc(this._targetFriendly(t))}
          </button>
        `).join("")}
        ${hiddenCount > 0 ? `
          <button class="chip more-chip" data-action="show-more-devices">
            +${hiddenCount}
          </button>
        ` : ""}
      </div>
    `;
  }

  async _setAutoplay(enabled) {
    await this._hass.callService("youtube_music_connector", "set_autoplay", { entity_id: this._entityId, enabled });
  }

  /* ── render gate ── */
  _effectiveSearchType() {
    const f = this._draft.filters;
    if (f.size === 0 || f.size === 3) return "all";
    if (f.size === 1) return f.values().next().value;
    return "all"; // multiple active = search all, filter client-side
  }

  _sig() {
    const a = this._attrs;
    return JSON.stringify([a.target_entity_id, a.available_target_players, a.search_results?.length, a.search_query, a.search_type, a.autoplay_enabled, this._searchLoading, [...this._draft.filters].sort().join(), [...this._selectedTargets].sort().join(), a.group_targets]);
  }
  _tryRender() { const s = this._sig(); if (s === this._renderSig) return; this._renderSig = s; this._render(); }

  /* ── render ── */
  _render() {
    const entity = this._entity;
    if (!entity) { this.shadowRoot.innerHTML = ""; return; }
    this._syncGroupFromBackend();
    const a = this._attrs;
    const targets = (a.available_target_players || []).filter(t => !this._excludeDevices.includes(t));
    const activeTarget = a.target_entity_id || "";
    const results = a.search_results || [];
    const autoplayOn = !!a.autoplay_enabled;
    const activeFilters = this._draft.filters;
    const filterTypes = [
      { key: "songs", label: "Songs" },
      { key: "artists", label: "Artists" },
      { key: "playlists", label: "Playlists" },
    ];
    const visibleResults = activeFilters.size === 0 ? results : results.filter((r) => {
      if (activeFilters.has("songs") && r.type === "song") return true;
      if (activeFilters.has("artists") && r.type === "artist") return true;
      if (activeFilters.has("playlists") && r.type === "playlist") return true;
      return false;
    });

    this.shadowRoot.innerHTML = `
      <style>${this._css()}</style>
      <div class="root">
        <!-- Device chips -->
        <div class="section">
          ${this._renderDeviceChips(targets, activeTarget)}
        </div>

        <!-- Search -->
        <div class="section">
          <div class="search-bar">
            <div class="search-icon"><ha-icon icon="mdi:magnify"></ha-icon></div>
            <input type="text" class="search-input" placeholder="Song, Artist oder Playlist suchen..."
                   value="${this._esc(this._draft.query)}" />
            <div class="filter-tags">
              ${filterTypes.map((f) => `
                <button class="filter-tag ${activeFilters.has(f.key) ? "active" : ""}" data-filter="${f.key}">
                  ${f.label}
                </button>
              `).join("")}
            </div>
            <button class="search-btn" data-action="search" title="Suchen">
              <ha-icon icon="mdi:arrow-right"></ha-icon>
            </button>
          </div>
        </div>

        <!-- Results -->
        <div class="results-section">
          ${this._searchLoading ? `
            <div class="state-msg">
              <ha-icon icon="mdi:loading" class="spin"></ha-icon>
              <span>Suche l\u00E4uft...</span>
            </div>
          ` : visibleResults.length === 0 ? `
            <div class="state-msg muted">
              ${a.search_query ? "Keine Ergebnisse" : "Suchbegriff eingeben"}
            </div>
          ` : `
            <div class="results-list">
              ${visibleResults.map((item, i) => this._renderItem(item, i === visibleResults.length - 1)).join("")}
            </div>
          `}

          ${!this._searchLoading && results.length > 0 && results.length >= this._draft.limit && this._draft.limit < 25 ? `
          <div class="load-more-wrap">
            <button class="load-more-btn" data-action="loadmore" title="Mehr laden">
              <ha-icon icon="mdi:arrow-right"></ha-icon>
              <span>Mehr laden</span>
            </button>
          </div>` : ""}
        </div>
      </div>
    `;
    this._bindEvents();
  }

  _renderItem(item, isLast) {
    const typeLabel = item.type === "song" ? "Song" : item.type === "artist" ? "Artist" : item.type === "playlist" ? "Playlist" : item.type || "";
    const title = item.title || item.name || "";
    const subtitle = [item.artist || item.owner || "", typeLabel, item.year || ""].filter(Boolean).join(" \u00B7 ");
    const imageUrl = item.image_url || item.thumbnail || "";

    return `
      <div class="result-item ${isLast ? "" : "bordered"}">
        <div class="result-thumb">
          ${imageUrl
            ? `<img src="${imageUrl}" alt="" loading="lazy" />`
            : `<div class="thumb-placeholder"><ha-icon icon="mdi:music-note"></ha-icon></div>`}
        </div>
        <div class="result-meta">
          <div class="result-title">${this._esc(title)}</div>
          <div class="result-subtitle">${this._esc(subtitle)}</div>
        </div>
        <button class="result-play" data-play-type="${item.type}" data-play-id="${this._esc(item.id)}" title="Abspielen">
          <ha-icon icon="mdi:play"></ha-icon>
        </button>
      </div>
    `;
  }

  _esc(s) { if (!s) return ""; const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

  _bindEvents() {
    const root = this.shadowRoot;
    const input = root.querySelector(".search-input");
    if (input) {
      input.addEventListener("focus", () => { this._interacting = true; });
      input.addEventListener("blur", () => { this._interacting = false; });
      input.addEventListener("input", (e) => { this._draft.query = e.target.value; });
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") { this._draft.limit = 5; this._search(); } });
    }
    root.querySelectorAll("[data-filter]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.dataset.filter;
        if (this._draft.filters.has(key)) this._draft.filters.delete(key);
        else this._draft.filters.add(key);
        this._draft.limit = 5;
        this._renderSig = "";
        this._tryRender();
        if (this._draft.query.trim()) this._search();
      });
    });
    const searchBtn = root.querySelector("[data-action='search']");
    if (searchBtn) searchBtn.addEventListener("click", () => { this._draft.limit = 5; this._search(); });
    root.querySelectorAll("[data-target]").forEach((btn) => btn.addEventListener("click", () => this._toggleTarget(btn.dataset.target)));
    const moreBtn = root.querySelector("[data-action='show-more-devices']");
    if (moreBtn) moreBtn.addEventListener("click", () => { this._showAllDevices = !this._showAllDevices; this._renderSig = ""; this._tryRender(); });

    root.querySelectorAll("[data-play-type]").forEach((btn) => btn.addEventListener("click", () => this._play(btn.dataset.playType, btn.dataset.playId)));
    const loadMore = root.querySelector("[data-action='loadmore']");
    if (loadMore) loadMore.addEventListener("click", () => this._loadMore());
  }

  /* ── styles ── */
  _css() {
    return `
      :host {
        display: block;
        font-family: var(--ytmc-font-family, inherit);
        color: var(--ytmc-text, #f8fafc);
        --_bg: var(--ytmc-bg, #0f1923);
        --_surface: var(--ytmc-surface, rgba(255,255,255,0.06));
        --_text: var(--ytmc-text, #f8fafc);
        --_text2: var(--ytmc-text-secondary, rgba(248,250,252,0.72));
        --_accent: var(--ytmc-accent, #4a9eff);
        --_accent-active: var(--ytmc-accent-active, #2d7fe0);
        --_radius: var(--ytmc-radius, 18px);
      }
      *, *::before, *::after { box-sizing: border-box; }

      .root {
        background: var(--_bg);
        border-radius: var(--_radius);
        border: 1px solid rgba(255,255,255,0.06);
        box-shadow: 0 8px 32px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.04);
        padding: 24px 28px;
        display: grid;
        gap: 22px;
      }

      .section { display: grid; gap: 10px; }

      /* ── section labels ── */
      .section-label {
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--_text2);
      }

      /* ── device chips ── */
      .chips-row {
        display: flex;
        flex-wrap: nowrap;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
        gap: 8px;
      }
      .chips-row::-webkit-scrollbar { display: none; }
      .chip {
        all: unset;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 9px 18px 9px 12px;
        border-radius: 999px;
        font-size: 0.84rem;
        font-weight: 500;
        background: rgba(255,255,255,0.04);
        color: var(--_text2);
        border: 1px solid rgba(255,255,255,0.08);
        transition: all 0.18s ease;
        white-space: nowrap;
      }
      .chip:hover {
        background: rgba(255,255,255,0.08);
        border-color: rgba(255,255,255,0.14);
        color: var(--_text);
      }
      .chip.active {
        background: var(--_accent);
        color: #fff;
        border-color: var(--_accent);
        box-shadow: 0 2px 12px rgba(74,158,255,0.25);
      }
      .chip-icon {
        display: flex;
        align-items: center;
        opacity: 0.7;
      }
      .chip.active .chip-icon { opacity: 1; }
      .chip-icon ha-icon { --mdc-icon-size: 16px; }
      .more-chip {
        font-weight: 700;
        font-size: 0.78rem;
        padding: 9px 14px;
        letter-spacing: 0.02em;
      }

      /* ── search bar ── */
      .search-bar {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 6px 8px 6px 18px;
        border-radius: 16px;
        border: 1px solid rgba(255,255,255,0.08);
        background: rgba(255,255,255,0.04);
        transition: border-color 0.18s, background 0.18s;
      }
      .search-bar:focus-within {
        border-color: var(--_accent);
        background: rgba(255,255,255,0.06);
        box-shadow: 0 0 0 3px rgba(74,158,255,0.1);
      }
      .search-icon { color: var(--_text2); display: flex; flex-shrink: 0; }
      .search-icon ha-icon { --mdc-icon-size: 22px; }
      .search-input {
        flex: 1;
        padding: 14px 0;
        min-height: 48px;
        border: none;
        background: transparent;
        color: var(--_text);
        font-size: 1.05rem;
        font-family: inherit;
        outline: none;
      }
      .search-input::placeholder { color: var(--_text2); }

      /* ── inline filter tags ── */
      .filter-tags {
        display: flex;
        gap: 6px;
        flex-shrink: 0;
      }
      .filter-tag {
        all: unset;
        cursor: pointer;
        padding: 9px 16px;
        min-height: 40px;
        border-radius: 10px;
        font-size: 0.82rem;
        font-weight: 600;
        color: var(--_text2);
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        transition: all 0.15s;
        white-space: nowrap;
        display: inline-flex;
        align-items: center;
      }
      .filter-tag:hover { background: rgba(255,255,255,0.08); color: var(--_text); }
      .filter-tag.active {
        background: rgba(74,158,255,0.18);
        border-color: var(--_accent);
        color: var(--_accent);
      }

      /* ── search button ── */
      .search-btn {
        all: unset;
        cursor: pointer;
        width: 52px; height: 52px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 14px;
        background: var(--_accent);
        color: #fff;
        flex-shrink: 0;
        transition: all 0.15s;
        box-shadow: 0 2px 10px rgba(74,158,255,0.3);
      }
      .search-btn:hover { background: var(--_accent-active); transform: scale(1.05); box-shadow: 0 4px 16px rgba(74,158,255,0.4); }
      .search-btn:active { transform: scale(0.94); }
      .search-btn ha-icon { --mdc-icon-size: 24px; }

      /* ── results ── */
      .results-section {
        display: grid;
        gap: 8px;
      }
      .results-list {
        background: rgba(255,255,255,0.02);
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,0.04);
        overflow: hidden;
      }
      .result-item {
        display: grid;
        grid-template-columns: 56px 1fr 44px;
        gap: 14px;
        align-items: center;
        padding: 12px 14px;
        transition: background 0.12s;
      }
      .result-item.bordered {
        border-bottom: 1px solid rgba(255,255,255,0.04);
      }
      .result-item:hover {
        background: rgba(255,255,255,0.04);
      }
      .result-thumb {
        width: 56px; height: 56px;
        border-radius: 10px;
        overflow: hidden;
        background: rgba(255,255,255,0.04);
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }
      .result-thumb img {
        width: 100%; height: 100%;
        object-fit: cover;
      }
      .thumb-placeholder { color: rgba(255,255,255,0.2); }
      .thumb-placeholder ha-icon { --mdc-icon-size: 26px; }
      .result-meta { min-width: 0; }
      .result-title {
        font-weight: 700;
        font-size: 0.9rem;
        line-height: 1.3;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: var(--_text);
      }
      .result-subtitle {
        font-size: 0.78rem;
        color: var(--_text2);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        margin-top: 2px;
      }

      .result-play {
        all: unset;
        cursor: pointer;
        width: 40px; height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        color: var(--_text2);
        border: 1px solid rgba(255,255,255,0.08);
        background: rgba(255,255,255,0.03);
        transition: all 0.15s;
      }
      .result-play:hover {
        background: var(--_accent);
        border-color: var(--_accent);
        color: #fff;
        box-shadow: 0 2px 12px rgba(74,158,255,0.3);
        transform: scale(1.08);
      }
      .result-play:active { transform: scale(0.94); }
      .result-play ha-icon { --mdc-icon-size: 20px; }

      /* ── loading / empty ── */
      .state-msg {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        padding: 40px 16px;
        color: var(--_text2);
        font-size: 0.88rem;
      }
      .state-msg.muted { opacity: 0.5; }
      @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      .spin { animation: spin 1s linear infinite; display: inline-flex; }

      /* ── load more ── */
      .load-more-wrap { display: flex; justify-content: center; margin-top: 4px; }
      .load-more-btn {
        all: unset;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 22px;
        border-radius: 12px;
        font-size: 0.82rem;
        font-weight: 600;
        color: #fff;
        background: var(--_accent);
        transition: all 0.15s;
      }
      .load-more-btn:hover { background: var(--_accent-active); transform: scale(1.03); }
      .load-more-btn:active { transform: scale(0.96); }
      .load-more-btn ha-icon { --mdc-icon-size: 16px; }

      @media (max-width: 480px) {
        .root { padding: 18px 16px; gap: 16px; }
        .chips-row { padding-bottom: 4px; }
        .search-bar {
          display: grid;
          grid-template-columns: auto 1fr;
          grid-template-rows: auto auto;
          gap: 8px 10px;
          padding: 10px 10px 10px 16px;
          align-items: center;
        }
        .search-icon { grid-row: 1; grid-column: 1; }
        .search-input { grid-row: 1; grid-column: 2; min-width: 0; }
        .filter-tags { grid-row: 2; grid-column: 1 / -1; display: flex; gap: 6px; }
        .search-btn { grid-row: 2; grid-column: 2; justify-self: end; }
        .result-item { grid-template-columns: 46px 1fr 44px; gap: 10px; padding: 10px; }
        .result-thumb { width: 46px; height: 46px; }
        .result-play { width: 44px; height: 44px; }
      }
    `;
  }
}

customElements.define("ytmc-search-play", YtmcSearchPlay);

/* ── Card editor for HA UI ── */
class YtmcSearchPlayEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
  }
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) { this._hass = hass; }

  _render() {
    const entity = this._config.entity || "";
    const exclude = (this._config.exclude_devices || []).join(", ");
    this.shadowRoot.innerHTML = `
      <style>
        .editor { display: grid; gap: 12px; padding: 8px 0; }
        label { font-size: 0.85rem; font-weight: 500; display: grid; gap: 4px; }
        input { padding: 8px; border: 1px solid var(--divider-color, #ccc); border-radius: 6px; font-size: 0.9rem; background: var(--card-background-color, #fff); color: var(--primary-text-color, #000); }
        .hint { font-size: 0.75rem; color: var(--secondary-text-color, #666); }
      </style>
      <div class="editor">
        <label>
          Entity
          <input type="text" id="entity" value="${entity}" placeholder="media_player.youtube_music_connector" />
        </label>
        <label>
          Exclude devices (comma-separated entity IDs)
          <input type="text" id="exclude" value="${exclude}" placeholder="media_player.kitchen, media_player.office" />
          <span class="hint">Hide these devices from the device selector</span>
        </label>
      </div>
    `;
    this.shadowRoot.getElementById("entity").addEventListener("change", (e) => {
      this._config = { ...this._config, entity: e.target.value.trim() };
      this._dispatch();
    });
    this.shadowRoot.getElementById("exclude").addEventListener("change", (e) => {
      const val = e.target.value.trim();
      this._config = { ...this._config, exclude_devices: val ? val.split(",").map(s => s.trim()).filter(Boolean) : [] };
      this._dispatch();
    });
  }
  _dispatch() {
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config } }));
  }
}
customElements.define("ytmc-search-play-editor", YtmcSearchPlayEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ytmc-search-play",
  name: "YouTube Music Search & Play",
  description: "Search YouTube Music and play results on selected devices with multi-device group playback.",
  documentationURL: "https://github.com/Jerry0022/homeassistant-youtube-music-connector/blob/main/docs/components.md",
});
