class YoutubeMusicConnectorBase extends HTMLElement {
  constructor() {
    super();
    this._progressTicker = null;
    this._targetMenuId = null;
    this._draftVolumeByTarget = {};
    this._draftSeek = null;
    this._pendingPlayback = null;
    this._pendingPlaybackTimeout = null;
    this._selectedTarget = "";
  }

  setConfig(config) {
    this.config = config || {};
    this._renderSignature = "";
    this._pendingRenderSignature = null;
    this._interactionHandlersBound = false;
  }

  set hass(hass) {
    this._hass = hass;
    this._syncSelectedTargetFromState();
    this._bindInteractionTracking();
    this._syncProgressTicker();
    this._syncPendingPlaybackState();
    const nextSignature = this._renderStateSignature();
    if (nextSignature !== this._renderSignature) {
      if (this._isInteracting()) {
        this._pendingRenderSignature = nextSignature;
        return;
      }
      this._renderSignature = nextSignature;
      this.render();
    }
  }

  get integrationEntity() {
    const configured = this.config.entity || "media_player.youtube_music_connector";
    if (configured && configured !== "media_player.youtube_music_connector" && this._looksLikeConnectorEntity(configured)) {
      return configured;
    }
    return this._discoverConnectorEntity() || configured;
  }

  get entityState() {
    return this._hass?.states?.[this.integrationEntity];
  }

  _looksLikeConnectorEntity(entityId) {
    if (!entityId) {
      return false;
    }
    const state = this._hass?.states?.[entityId];
    if (!state) {
      return false;
    }
    if (entityId.startsWith("media_player.youtube_music_connector")) {
      return true;
    }
    const attrs = state.attributes || {};
    if (attrs.is_youtube_music_connector === true) {
      return true;
    }
    if (attrs.icon === "mdi:youtube-music") {
      return true;
    }
    return (
      Array.isArray(attrs.search_results)
      || Array.isArray(attrs.available_target_players)
      || Object.prototype.hasOwnProperty.call(attrs, "current_item")
      || Object.prototype.hasOwnProperty.call(attrs, "target_entity_id")
    );
  }

  _discoverConnectorEntity() {
    const candidates = Object.keys(this._hass?.states || {})
      .filter((entityId) => entityId.startsWith("media_player."))
      .filter((entityId) => this._looksLikeConnectorEntity(entityId))
      .sort((left, right) => {
        const scoreDelta = this._connectorEntityScore(right) - this._connectorEntityScore(left);
        if (scoreDelta !== 0) {
          return scoreDelta;
        }
        const updatedDelta = this._entityLastUpdated(right) - this._entityLastUpdated(left);
        if (updatedDelta !== 0) {
          return updatedDelta;
        }
        return left.localeCompare(right, "de", { sensitivity: "base" });
      });
    return candidates[0] || "";
  }

  _entityLastUpdated(entityId) {
    return Date.parse(this._hass?.states?.[entityId]?.last_updated || "") || 0;
  }

  _connectorEntityScore(entityId) {
    const state = this._hass?.states?.[entityId];
    const attrs = state?.attributes || {};
    let score = 0;
    if (attrs.is_youtube_music_connector === true) {
      score += 1000;
    }
    if (entityId === this.config?.entity && entityId !== "media_player.youtube_music_connector") {
      score += 500;
    }
    score += Math.min(100, Number(attrs.search_count || 0));
    score += Math.min(100, Array.isArray(attrs.search_results) ? attrs.search_results.length : 0);
    score += Math.min(200, Array.isArray(attrs.available_target_players) ? attrs.available_target_players.length * 10 : 0);
    if (attrs.target_entity_id) {
      score += 50;
    }
    if (attrs.current_item && Object.keys(attrs.current_item).length > 0) {
      score += 25;
    }
    if (state?.state && state.state !== "unavailable" && state.state !== "unknown") {
      score += 25;
    }
    return score;
  }

  getCardSize() {
    return 4;
  }

  disconnectedCallback() {
    this._clearProgressTicker();
    if (this._pendingPlaybackTimeout) {
      window.clearTimeout(this._pendingPlaybackTimeout);
      this._pendingPlaybackTimeout = null;
    }
  }

  _beginPendingPlayback({ mode, itemType = "", itemId = "", targetEntityId = "" } = {}) {
    if (this._pendingPlaybackTimeout) {
      window.clearTimeout(this._pendingPlaybackTimeout);
    }
    this._pendingPlayback = {
      mode,
      itemType,
      itemId,
      targetEntityId,
      beforeKey: this._currentPlaybackKey(this.entityState),
      lastError: this.entityState?.attributes?.last_error || "",
      startedAt: Date.now(),
    };
    this._pendingPlaybackTimeout = window.setTimeout(() => {
      this._clearPendingPlayback();
      this.render();
    }, 15000);
    this.render();
  }

  _clearPendingPlayback() {
    if (this._pendingPlaybackTimeout) {
      window.clearTimeout(this._pendingPlaybackTimeout);
      this._pendingPlaybackTimeout = null;
    }
    if (!this._pendingPlayback) {
      return;
    }
    this._pendingPlayback = null;
  }

  _syncPendingPlaybackState() {
    const pending = this._pendingPlayback;
    if (!pending) {
      return;
    }
    const entity = this.entityState;
    if (!entity) {
      if (Date.now() - pending.startedAt > 15000) {
        this._clearPendingPlayback();
      }
      return;
    }
    const currentItem = entity.attributes?.current_item || {};
    const currentKey = this._currentPlaybackKey(entity);
    const currentId = currentItem.id || "";
    const currentError = entity.attributes?.last_error || "";
    const isPlaying = entity.state === "playing";
    if (currentError && currentError !== pending.lastError) {
      this._clearPendingPlayback();
      return;
    }
    if (Date.now() - pending.startedAt > 15000) {
      this._clearPendingPlayback();
      return;
    }
    if (pending.mode === "transport") {
      if (isPlaying) {
        this._clearPendingPlayback();
      }
      return;
    }
    if (pending.itemType === "song" && pending.itemId && currentId === pending.itemId && isPlaying) {
      this._clearPendingPlayback();
      return;
    }
    if (isPlaying && currentKey && currentKey !== pending.beforeKey) {
      this._clearPendingPlayback();
    }
  }

  _isPendingPlaybackActive() {
    return !!this._pendingPlayback;
  }

  _isPendingResult(itemType, itemId) {
    return !!this._pendingPlayback
      && this._pendingPlayback.mode === "result"
      && this._pendingPlayback.itemType === itemType
      && this._pendingPlayback.itemId === itemId;
  }

  _sanitizeLimitInput(value) {
    return String(value ?? "").replace(/\D+/g, "").slice(0, 2);
  }

  _normalizeLimitValue(value) {
    const sanitized = this._sanitizeLimitInput(value);
    const numeric = Number(sanitized);
    if (!sanitized || !Number.isInteger(numeric) || numeric < 1 || numeric > 99) {
      return "5";
    }
    return String(numeric);
  }

  _bindLimitInput(input, onCommit, onEnter = null) {
    if (!input) {
      return;
    }
    input.addEventListener("input", (event) => {
      const sanitized = this._sanitizeLimitInput(event.target.value);
      if (event.target.value !== sanitized) {
        event.target.value = sanitized;
      }
      onCommit(sanitized);
    });
    input.addEventListener("blur", (event) => {
      const normalized = this._normalizeLimitValue(event.target.value);
      event.target.value = normalized;
      onCommit(normalized);
    });
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") {
        return;
      }
      const normalized = this._normalizeLimitValue(event.target.value);
      event.target.value = normalized;
      onCommit(normalized);
      if (onEnter) {
        onEnter();
      }
    });
  }

  _bindInteractionTracking() {
    if (this._interactionHandlersBound || !this.shadowRoot) {
      return;
    }
    this.shadowRoot.addEventListener("focusout", () => {
      window.setTimeout(() => {
        if (!this._isInteracting() && this._pendingRenderSignature !== null) {
          this._renderSignature = this._pendingRenderSignature;
          this._pendingRenderSignature = null;
          this.render();
        }
      }, 0);
    });
    this._interactionHandlersBound = true;
  }

  _isInteracting() {
    const active = this.shadowRoot?.activeElement;
    return !!active && ["INPUT", "SELECT", "TEXTAREA"].includes(active.tagName);
  }

  _renderStateSignature() {
    const entity = this.entityState;
    if (!entity) {
      return "missing";
    }
    const attrs = entity.attributes || {};
    const effectiveTarget = this._resolveCurrentTarget(attrs.target_entity_id || "");
    return JSON.stringify({
      state: entity.state,
      search_results: attrs.search_results || [],
      search_query: attrs.search_query || "",
      search_type: attrs.search_type || "",
      search_count: attrs.search_count || 0,
      target_entity_id: attrs.target_entity_id || "",
      available_target_players: attrs.available_target_players || [],
      current_item: attrs.current_item || {},
      last_error: attrs.last_error || "",
      target_volume: this._targetVolumeLevel(effectiveTarget || ""),
      media_duration: attrs.media_duration || 0,
      media_position: attrs.media_position || 0,
      media_position_updated_at: attrs.media_position_updated_at || "",
      supported_features: attrs.supported_features || 0,
      autoplay_enabled: attrs.autoplay_enabled || false,
      autoplay_queue_length: attrs.autoplay_queue_length || 0,
      shuffle_enabled: attrs.shuffle_enabled || false,
      repeat_mode: attrs.repeat_mode || "off",
      config: this.config || {}
    });
  }

  _style() {
    return `
      :host {
        --ymc-bg: linear-gradient(180deg, rgba(12,18,26,0.98), rgba(19,27,38,0.96));
        --ymc-accent: #f15152;
        --ymc-accent-soft: rgba(241, 81, 82, 0.18);
        --ymc-border: rgba(255,255,255,0.08);
        --ymc-text: #f8fafc;
        --ymc-muted: rgba(248,250,252,0.72);
        --ymc-radius: 24px;
        display: block;
      }
      ha-card {
        background: radial-gradient(circle at top right, rgba(241,81,82,0.14), transparent 34%), var(--ymc-bg);
        border: 1px solid rgba(255,255,255,0.04);
        border-radius: var(--ymc-radius);
        box-shadow: 0 18px 40px rgba(0,0,0,0.16);
        color: var(--ymc-text);
        overflow: hidden;
      }
      .shell {
        padding: 16px;
        display: grid;
        gap: 14px;
      }
      .section-title {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }
      .headline {
        font-size: 1.05rem;
        font-weight: 700;
        letter-spacing: 0.01em;
      }
      .headline-row {
        display: inline-flex;
        align-items: center;
        gap: 8px;
      }
      .headline-row ha-icon {
        --mdc-icon-size: 20px;
        color: #ff6b5f;
      }
      .subline {
        font-size: 0.84rem;
        color: var(--ymc-muted);
      }
      .controls, .row {
        display: grid;
        gap: 10px;
      }
      .query-row {
        display: grid;
        grid-template-columns: minmax(0, 1fr) max-content;
        gap: 10px;
        align-items: center;
      }
      .query-field {
        display: flex;
        align-items: center;
        gap: 12px;
        border: 1px solid rgba(255,255,255,0.12);
        background: rgba(255,255,255,0.06);
        border-radius: 16px;
        padding: 10px 14px;
        box-sizing: border-box;
      }
      .query-field input {
        flex: 1 1 auto;
        min-width: 0;
        min-height: auto;
        border: 0;
        background: transparent;
        box-shadow: none;
        padding: 0;
        font-size: 1rem;
      }
      .query-field input:focus {
        outline: none;
      }
      .filter-strip {
        flex: 0 0 auto;
        display: flex;
        flex-wrap: wrap;
        justify-content: flex-end;
        gap: 8px;
        max-width: 260px;
      }
      .row.compact {
        grid-template-columns: 1fr auto;
      }
      .target-picker {
        position: relative;
      }
      .target-trigger {
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        border: 1px solid rgba(255,255,255,0.1);
        background: rgba(255,255,255,0.06);
        color: var(--ymc-text);
        border-radius: 16px;
        padding: 12px 14px;
        min-height: 46px;
        box-shadow: none;
      }
      .target-trigger:hover {
        background: rgba(255,255,255,0.1);
        filter: none;
        box-shadow: 0 10px 22px rgba(0,0,0,0.16);
      }
      .target-trigger-main {
        min-width: 0;
        display: inline-flex;
        align-items: center;
        gap: 10px;
      }
      .target-trigger-label {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        text-align: left;
      }
      .target-trigger ha-icon,
      .target-option ha-icon {
        --mdc-icon-size: 18px;
        flex: 0 0 auto;
      }
      .target-menu {
        position: absolute;
        z-index: 20;
        top: calc(100% + 8px);
        left: 0;
        right: 0;
        display: grid;
        gap: 6px;
        padding: 8px;
        border-radius: 16px;
        background: linear-gradient(180deg, rgba(29,38,51,0.98), rgba(21,29,40,0.96));
        border: 1px solid rgba(255,255,255,0.08);
        box-shadow: 0 18px 32px rgba(0,0,0,0.24);
      }
      .target-menu[hidden] {
        display: none;
      }
      .target-option {
        width: 100%;
        display: flex;
        align-items: center;
        gap: 10px;
        min-height: 42px;
        padding: 0 12px;
        border-radius: 12px;
        background: rgba(255,255,255,0.04);
        box-shadow: none;
      }
      .target-option.active {
        background: rgba(241,81,82,0.18);
      }
      .target-option-label {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        text-align: left;
      }
      input, select, button {
        font: inherit;
      }
      input, select {
        width: 100%;
        box-sizing: border-box;
        border: 1px solid rgba(255,255,255,0.1);
        background: rgba(255,255,255,0.06);
        color: var(--ymc-text);
        border-radius: 16px;
        padding: 12px 14px;
        min-height: 46px;
      }
      input[type="range"] {
        width: 100%;
        padding: 0;
        min-height: auto;
        border: 0;
        background: transparent;
        accent-color: var(--ymc-accent);
      }
      select option {
        background: #1d2633;
        color: var(--ymc-text);
      }
      button {
        border: 0;
        border-radius: 16px;
        min-height: 46px;
        padding: 0 14px;
        background: linear-gradient(135deg, var(--ymc-accent), #ff875b);
        color: white;
        font-weight: 700;
        cursor: pointer;
        transition: transform 120ms ease, filter 120ms ease, box-shadow 120ms ease, background 120ms ease;
        box-shadow: 0 10px 24px rgba(241,81,82,0.18);
      }
      button:hover {
        filter: brightness(1.06);
        box-shadow: 0 14px 28px rgba(241,81,82,0.24);
      }
      button:active {
        transform: translateY(1px) scale(0.99);
        filter: brightness(0.96);
        box-shadow: 0 6px 16px rgba(241,81,82,0.18);
      }
      button.secondary {
        background: rgba(255,255,255,0.08);
        box-shadow: none;
      }
      button.secondary:hover,
      button.icon-toggle:hover {
        background: rgba(255,255,255,0.14);
        filter: none;
        box-shadow: 0 10px 22px rgba(0,0,0,0.16);
      }
      button.secondary:active,
      button.icon-toggle:active {
        transform: translateY(1px) scale(0.99);
        background: rgba(255,255,255,0.1);
        box-shadow: 0 4px 14px rgba(0,0,0,0.14);
      }
      button.icon-toggle {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        min-height: 38px;
        padding: 0 12px;
        border-radius: 12px;
        background: rgba(255,255,255,0.08);
        box-shadow: none;
      }
      button.icon-toggle.active {
        background: linear-gradient(135deg, var(--ymc-accent), #ff875b);
        box-shadow: 0 10px 24px rgba(241,81,82,0.18);
      }
      button.icon-toggle ha-icon {
        --mdc-icon-size: 18px;
      }
      button.filter-chip {
        min-height: 28px;
        padding: 0 10px;
        border-radius: 999px;
        background: rgba(255,255,255,0.08);
        color: var(--ymc-text);
        font-size: 0.72rem;
        font-weight: 700;
        box-shadow: none;
      }
      button.filter-chip.active {
        background: var(--ymc-accent-soft);
        color: #ffd5d5;
        box-shadow: inset 0 0 0 1px rgba(241,81,82,0.24);
      }
      button.filter-chip:hover {
        background: rgba(255,255,255,0.14);
        filter: none;
        box-shadow: 0 10px 22px rgba(0,0,0,0.16);
      }
      button.filter-chip.active:hover {
        background: rgba(241,81,82,0.24);
      }
      button.filter-chip:active {
        transform: translateY(1px) scale(0.99);
        box-shadow: 0 4px 14px rgba(0,0,0,0.14);
      }
      button.button-loading {
        pointer-events: none;
      }
      .button-content {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
      }
      .button-spinner {
        width: 14px;
        height: 14px;
        border-radius: 50%;
        border: 2px solid rgba(255,255,255,0.28);
        border-top-color: rgba(255,255,255,0.96);
        animation: ymc-spin 0.8s linear infinite;
        flex: 0 0 auto;
      }
      .search-submit {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        width: fit-content;
        max-width: 100%;
        min-width: 0;
        justify-self: end;
        min-height: 46px;
        padding: 6px;
        box-sizing: border-box;
        border-radius: 16px;
        background: linear-gradient(135deg, var(--ymc-accent), #ff875b);
        box-shadow: 0 10px 24px rgba(241,81,82,0.18);
        cursor: pointer;
        transition: transform 120ms ease, filter 120ms ease, box-shadow 120ms ease;
      }
      .search-submit:hover {
        filter: brightness(1.04);
        box-shadow: 0 14px 28px rgba(241,81,82,0.24);
      }
      .search-submit:active {
        transform: translateY(1px) scale(0.99);
        box-shadow: 0 6px 16px rgba(241,81,82,0.18);
      }
      .search-submit.loading {
        opacity: 0.82;
      }
      .search-submit-title,
      .search-submit-label {
        color: white;
        font-size: 0.82rem;
        font-weight: 700;
        white-space: nowrap;
      }
      .search-submit input {
        width: 42px;
        min-height: 34px;
        padding: 0 6px;
        text-align: center;
        border-radius: 10px;
        border: 0;
        background: rgba(255,255,255,0.16);
        box-shadow: none;
        appearance: textfield;
        -moz-appearance: textfield;
        outline: none;
      }
      .search-submit input::-webkit-outer-spin-button,
      .search-submit input::-webkit-inner-spin-button {
        -webkit-appearance: none;
        margin: 0;
        display: none;
      }
      .search-submit input:focus {
        outline: none;
        box-shadow: none;
      }
      .results {
        display: grid;
        gap: 18px;
      }
      .item {
        display: grid;
        grid-template-columns: 64px 1fr;
        gap: 12px;
        padding: 10px;
        padding-top: 24px;
        margin-top: 10px;
        border-radius: 18px;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.06);
        align-items: stretch;
        position: relative;
        overflow: visible;
      }
      .item.empty-item {
        grid-template-columns: 1fr;
        padding-top: 10px;
        margin-top: 0;
      }
      .item img {
        width: 100%;
        height: 100%;
        min-height: 84px;
        aspect-ratio: 1 / 1;
        object-fit: cover;
        border-radius: 14px;
        background: rgba(255,255,255,0.06);
      }
      .meta {
        min-width: 0;
        display: grid;
        gap: 6px;
      }
      .meta-main {
        min-width: 0;
        display: grid;
        gap: 6px;
        padding-right: 156px;
      }
      .result-title,
      .result-subtitle {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .result-badge {
        position: absolute;
        top: -14px;
        right: -2px;
        display: grid;
        gap: 6px;
        width: 144px;
        padding: 10px 12px;
        border-radius: 16px;
        background: linear-gradient(180deg, rgba(29,38,51,0.98), rgba(21,29,40,0.96));
        border: 1px solid rgba(255,255,255,0.08);
        box-shadow: 0 14px 28px rgba(0,0,0,0.2);
      }
      .badge-type {
        font-size: 0.88rem;
        font-weight: 800;
        color: #ffd5d5;
        letter-spacing: 0.01em;
      }
      .pill {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 4px 8px;
        border-radius: 999px;
        font-size: 0.72rem;
        background: var(--ymc-accent-soft);
        color: #ffd5d5;
        width: fit-content;
      }
      .code-chip {
        width: 100%;
        max-width: 100%;
        min-height: 34px;
        padding: 8px 10px;
        border-radius: 12px;
        background: rgba(255,255,255,0.06);
        color: var(--ymc-text);
        font-size: 0.74rem;
        font-weight: 700;
        line-height: 1.2;
        text-align: left;
        white-space: normal;
        word-break: break-all;
        font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
        box-shadow: none;
      }
      .code-chip:hover {
        background: rgba(255,255,255,0.14);
        filter: none;
        box-shadow: 0 10px 22px rgba(0,0,0,0.16);
      }
      .code-chip:active {
        transform: translateY(1px) scale(0.99);
        background: rgba(255,255,255,0.1);
        box-shadow: 0 4px 14px rgba(0,0,0,0.14);
      }
      .main {
        font-weight: 700;
        line-height: 1.2;
        word-break: break-word;
      }
      .muted {
        color: var(--ymc-muted);
        font-size: 0.84rem;
        line-height: 1.25;
      }
      .actions {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .actions button {
        min-height: 38px;
        padding: 0 12px;
        border-radius: 12px;
      }
      .empty-item-copy {
        display: grid;
        gap: 6px;
      }
      .cover {
        display: grid;
        gap: 14px;
      }
      .art-wrap {
        display: grid;
        grid-template-columns: 84px 1fr;
        gap: 14px;
        align-items: center;
      }
      .art-wrap img {
        width: 84px;
        height: 84px;
        object-fit: cover;
        border-radius: 20px;
        background: rgba(255,255,255,0.06);
      }
      .transport {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 10px;
      }
      @media (max-width: 680px) {
        .results {
          gap: 12px;
        }
        .item {
          grid-template-columns: 112px minmax(0, 1fr);
          gap: 12px;
          padding: 12px;
          padding-top: 12px;
          margin-top: 0;
          align-items: start;
        }
        .item img {
          width: 112px;
          height: 112px;
          min-height: 112px;
        }
        .result-badge {
          display: none;
        }
        .meta {
          gap: 8px;
          align-content: start;
        }
        .meta-main {
          padding-right: 0;
          gap: 4px;
        }
        .result-title,
        .result-subtitle {
          white-space: normal;
          display: -webkit-box;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
        .result-title {
          -webkit-line-clamp: 2;
        }
        .result-subtitle {
          -webkit-line-clamp: 2;
        }
        .actions {
          display: grid;
          grid-template-columns: 1fr;
          gap: 8px;
        }
        .actions button {
          width: 100%;
          min-height: 42px;
          justify-content: center;
          text-align: center;
        }
        .row.compact {
          grid-template-columns: 1fr;
        }
        .query-row {
          display: grid;
          grid-template-columns: 1fr;
          gap: 10px;
        }
        .search-submit {
          width: 100%;
          max-width: 100%;
          min-width: 0;
          justify-self: stretch;
        }
        .query-field {
          align-items: stretch;
          flex-direction: column;
          gap: 10px;
        }
        .query-field input {
          width: 100%;
        }
        .filter-strip {
          width: 100%;
          max-width: none;
          justify-content: flex-start;
        }
        .art-wrap {
          grid-template-columns: 72px 1fr;
        }
      }
    `;
  }

  _targetState(entityId) {
    return entityId ? this._hass?.states?.[entityId] : null;
  }

  _targetStorageKey() {
    return `youtube-music-connector.target.${this.integrationEntity}`;
  }

  _targetUsageStorageKey() {
    return `youtube-music-connector.target-usage.${this.integrationEntity}`;
  }

  _getStoredTarget() {
    try {
      return window.localStorage.getItem(this._targetStorageKey()) || "";
    } catch (_error) {
      return "";
    }
  }

  _getStoredTargetUsage() {
    try {
      return JSON.parse(window.localStorage.getItem(this._targetUsageStorageKey()) || "{}");
    } catch (_error) {
      return {};
    }
  }

  _persistTargetPreference(entityId) {
    if (!entityId) {
      return;
    }
    try {
      window.localStorage.setItem(this._targetStorageKey(), entityId);
      const usage = this._getStoredTargetUsage();
      usage[entityId] = Date.now();
      window.localStorage.setItem(this._targetUsageStorageKey(), JSON.stringify(usage));
    } catch (_error) {
      return;
    }
  }

  _targetRecentScore(entityId) {
    const usage = this._getStoredTargetUsage();
    const localTimestamp = Number(usage?.[entityId] || 0);
    const stateTimestamp = Date.parse(this._targetState(entityId)?.last_updated || "") || 0;
    return Math.max(localTimestamp, stateTimestamp);
  }

  _sortedTargetSources(selectedValue = "") {
    const sources = this.entityState?.attributes?.available_target_players || [];
    return [...sources].sort((left, right) => {
      if (left === selectedValue) {
        return -1;
      }
      if (right === selectedValue) {
        return 1;
      }
      const scoreDelta = this._targetRecentScore(right) - this._targetRecentScore(left);
      if (scoreDelta !== 0) {
        return scoreDelta;
      }
      return this._friendlyTarget(left, sources).localeCompare(this._friendlyTarget(right, sources), "de", { sensitivity: "base" });
    });
  }

  _resolveCurrentTarget(fallbackTarget = "") {
    const sources = this.entityState?.attributes?.available_target_players || [];
    const storedTarget = this._getStoredTarget();
    const preferred = this._selectedTarget || storedTarget || fallbackTarget || this.config.target_entity_id || "";
    if (sources.includes(preferred)) {
      return preferred;
    }
    if (sources.includes(fallbackTarget)) {
      return fallbackTarget;
    }
    return preferred;
  }

  _syncSelectedTargetFromState() {
    const fallbackTarget = this.entityState?.attributes?.target_entity_id || "";
    const resolvedTarget = this._resolveCurrentTarget(fallbackTarget);
    if (resolvedTarget) {
      this._selectedTarget = resolvedTarget;
    }
  }

  _targetIcon(entityId) {
    const state = this._targetState(entityId);
    const explicitIcon = state?.attributes?.icon;
    if (explicitIcon) {
      return explicitIcon;
    }
    const deviceClass = String(state?.attributes?.device_class || "").toLowerCase();
    if (deviceClass === "tv") {
      return "mdi:television";
    }
    if (deviceClass === "speaker") {
      return "mdi:speaker";
    }
    if (deviceClass === "receiver") {
      return "mdi:audio-video";
    }
    const haystack = [
      entityId,
      state?.attributes?.friendly_name,
      state?.attributes?.app_name,
      state?.attributes?.source,
      state?.attributes?.media_title,
      state?.attributes?.model_name,
      state?.attributes?.manufacturer,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (/(chromecast|google cast|cast)/.test(haystack)) {
      return "mdi:cast";
    }
    if (/(nest|speaker|audio|homepod|sonos|echo)/.test(haystack)) {
      return "mdi:speaker-wireless";
    }
    if (/(tablet|ipad|fire tablet)/.test(haystack)) {
      return "mdi:tablet-dashboard";
    }
    if (/(projector|beamer)/.test(haystack)) {
      return "mdi:projector";
    }
    if (/(tv|television|display|monitor|cinema)/.test(haystack)) {
      return "mdi:television";
    }
    if (/(receiver|amplifier|avr)/.test(haystack)) {
      return "mdi:audio-video";
    }
    return "mdi:play-network-outline";
  }

  _targetDisambiguator(entityId) {
    const rawName = entityId?.split(".").pop() || entityId || "";
    const normalizedName = rawName.replace(/[_-]+/g, " ").trim();
    return normalizedName || rawName || entityId || "";
  }

  _friendlyTarget(entityId, entityIds = null) {
    if (!entityId) {
      return "Kein Ziel";
    }
    const state = this._targetState(entityId);
    const rawBaseName = state?.attributes?.friendly_name || entityId || "Kein Ziel";
    const baseName = rawBaseName.replace(/^Player\s+/i, "").trim() || rawBaseName;
    const sources = entityIds || this.entityState?.attributes?.available_target_players || [];
    const duplicateCount = sources.filter((source) => {
      const sourceState = this._targetState(source);
      const sourceName = (sourceState?.attributes?.friendly_name || source || "").replace(/^Player\s+/i, "").trim() || source;
      return sourceName === baseName;
    }).length;
    const duplicateSuffix = duplicateCount > 1 ? ` (${this._targetDisambiguator(entityId)})` : "";
    return `${baseName}${duplicateSuffix}`;
  }

  _targetVolumeLevel(entityId) {
    const state = this._targetState(entityId);
    const volume = state?.attributes?.volume_level;
    return typeof volume === "number" ? volume : null;
  }

  _supportsVolume(entityId) {
    const state = this._targetState(entityId);
    if (!state) {
      return false;
    }
    const supported = Number(state.attributes?.supported_features || 0);
    return (supported & 4) === 4;
  }

  _targetVolumePercent(entityId) {
    const volume = this._targetVolumeLevel(entityId);
    return volume === null ? 0 : Math.round(volume * 100);
  }

  _effectiveTargetVolumePercent(entityId) {
    const draft = entityId ? this._draftVolumeByTarget?.[entityId] : null;
    if (draft && Date.now() - draft.updatedAt < 2000) {
      return draft.value;
    }
    return this._targetVolumePercent(entityId);
  }

  async _setTargetVolume(entityId, volumePercent) {
    if (!entityId) {
      return;
    }
    const normalizedVolume = Math.max(0, Math.min(100, Number(volumePercent)));
    this._draftVolumeByTarget[entityId] = {
      value: normalizedVolume,
      updatedAt: Date.now(),
    };
    this.render();
    await this._hass.callService("media_player", "turn_on", {
      entity_id: entityId,
    });
    await this._hass.callService("media_player", "volume_set", {
      entity_id: entityId,
      volume_level: normalizedVolume / 100
    });
  }

  async _setAutoplay(enabled) {
    await this._hass.callService("youtube_music_connector", "set_autoplay", {
      entity_id: this.integrationEntity,
      enabled
    });
  }

  async _togglePlayPause() {
    const state = this.entityState?.state;
    const action = state === "playing" ? "media_pause" : "media_play";
    if (action === "media_pause") {
      this._clearPendingPlayback();
    } else {
      const current = this.entityState?.attributes?.current_item || {};
      this._beginPendingPlayback({
        mode: "transport",
        itemType: current.type || "",
        itemId: current.id || "",
        targetEntityId: this._selectedTarget || this.entityState?.attributes?.target_entity_id || ""
      });
    }
    try {
      await this._hass.callService("media_player", action, {
        entity_id: this.integrationEntity
      });
    } catch (error) {
      this._clearPendingPlayback();
      this.render();
      throw error;
    }
  }

  async _setShuffle(enabled) {
    await this._hass.callService("youtube_music_connector", "set_shuffle", {
      entity_id: this.integrationEntity,
      shuffle_enabled: enabled
    });
  }

  async _cycleRepeatMode(currentMode) {
    const nextMode = currentMode === "off" ? "forever" : currentMode === "forever" ? "once" : "off";
    await this._hass.callService("youtube_music_connector", "set_repeat_mode", {
      entity_id: this.integrationEntity,
      repeat_mode: nextMode
    });
  }

  _repeatIcon(mode) {
    if (mode === "once") {
      return "mdi:repeat-once";
    }
    if (mode === "forever") {
      return "mdi:repeat";
    }
    return "mdi:repeat-off";
  }

  _repeatTitle(mode) {
    if (mode === "once") {
      return "Repeat Once";
    }
    if (mode === "forever") {
      return "Repeat Forever";
    }
    return "Repeat Off";
  }

  _clearProgressTicker() {
    if (this._progressTicker) {
      window.clearInterval(this._progressTicker);
      this._progressTicker = null;
    }
  }

  _syncProgressTicker() {
    const entity = this.entityState;
    const duration = Number(entity?.attributes?.media_duration || 0);
    const isPlaying = entity?.state === "playing";
    if (!isPlaying || duration <= 0) {
      this._clearProgressTicker();
      return;
    }
    if (this._progressTicker) {
      return;
    }
    this._progressTicker = window.setInterval(() => {
      if (!this._hass) {
        this._clearProgressTicker();
        return;
      }
      if (this._isInteracting()) {
        return;
      }
      this.render();
    }, 1000);
  }

  _supportsSeek() {
    const supported = Number(this.entityState?.attributes?.supported_features || 0);
    return (supported & 2) === 2;
  }

  _currentPlaybackKey(entity = this.entityState) {
    const current = entity?.attributes?.current_item || {};
    return current.id || current.url || current.title || "";
  }

  _currentMediaPosition(entity = this.entityState) {
    const duration = Number(entity?.attributes?.media_duration || 0);
    const playbackKey = this._currentPlaybackKey(entity);
    const draft = this._draftSeek;
    const hasDraft = draft && draft.key === playbackKey && Date.now() - draft.updatedAt < 15000;
    const basePosition = hasDraft ? Number(draft.position || 0) : Number(entity?.attributes?.media_position || 0);
    if (!duration) {
      return 0;
    }
    const playbackState = hasDraft ? draft.state : entity?.state;
    if (playbackState !== "playing") {
      return Math.max(0, Math.min(duration, basePosition));
    }
    const updatedAtValue = hasDraft ? draft.updatedAt : entity?.attributes?.media_position_updated_at;
    if (!updatedAtValue) {
      return Math.max(0, Math.min(duration, basePosition));
    }
    const updatedAtMs = typeof updatedAtValue === "number" ? updatedAtValue : Date.parse(updatedAtValue);
    if (Number.isNaN(updatedAtMs)) {
      return Math.max(0, Math.min(duration, basePosition));
    }
    const elapsed = Math.max(0, (Date.now() - updatedAtMs) / 1000);
    return Math.max(0, Math.min(duration, basePosition + elapsed));
  }

  _formatDuration(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    if (hours > 0) {
      return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }
    return `${minutes}:${String(secs).padStart(2, "0")}`;
  }

  _progressMarkup(entity = this.entityState) {
    const duration = Number(entity?.attributes?.media_duration || 0);
    if (duration <= 0) {
      return "";
    }
    const position = this._currentMediaPosition(entity);
    return `
      <div class="progress-block">
        <input
          id="progress_slider"
          type="range"
          min="0"
          max="${Math.round(duration)}"
          step="1"
          value="${Math.round(position)}"
          ${this._supportsSeek() ? "" : "disabled"}
        />
        <div class="progress-meta">
          <span id="progress_current">${this._escape(this._formatDuration(position))}</span>
          <span>${this._escape(this._formatDuration(duration))}</span>
        </div>
      </div>
    `;
  }

  _setDraftSeek(position) {
    const entity = this.entityState;
    this._draftSeek = {
      key: this._currentPlaybackKey(entity),
      position: Math.max(0, Number(position) || 0),
      updatedAt: Date.now(),
      state: entity?.state || "idle",
    };
  }

  _previewSeek(position) {
    const entity = this.entityState;
    const duration = Number(entity?.attributes?.media_duration || 0);
    this._setDraftSeek(position);
    const current = this.shadowRoot?.querySelector("#progress_current");
    if (current) {
      current.textContent = this._formatDuration(Math.max(0, Math.min(duration, Number(position) || 0)));
    }
  }

  async _seekCurrent(position) {
    if (!this._supportsSeek()) {
      return;
    }
    this._setDraftSeek(position);
    this.render();
    await this._hass.callService("media_player", "media_seek", {
      entity_id: this.integrationEntity,
      seek_position: Number(position)
    });
  }

  _targetOptions(selectedValue = "") {
    const sources = this._sortedTargetSources(selectedValue);
    return `
      <option value="">Zielplayer waehlen</option>
      ${sources.map(source => `<option value="${source}" ${source === selectedValue ? "selected" : ""}>${this._escape(this._friendlyTarget(source, sources))}</option>`).join("")}
    `;
  }

  _targetPickerMarkup(selectedValue = "", pickerId = "target_player", placeholder = "Zielplayer waehlen") {
    const sources = this._sortedTargetSources(selectedValue);
    const isOpen = this._targetMenuId === pickerId;
    const selectedLabel = selectedValue ? this._friendlyTarget(selectedValue, sources) : placeholder;
    const selectedIcon = selectedValue ? this._targetIcon(selectedValue) : "mdi:play-network-outline";
    return `
      <div class="target-picker">
        <button class="target-trigger secondary" id="${pickerId}_trigger" data-target-trigger="${pickerId}" type="button">
          <span class="target-trigger-main">
            <ha-icon icon="${this._escape(selectedIcon)}"></ha-icon>
            <span class="target-trigger-label">${this._escape(selectedLabel)}</span>
          </span>
          <ha-icon icon="${isOpen ? "mdi:chevron-up" : "mdi:chevron-down"}"></ha-icon>
        </button>
        <div class="target-menu" ${isOpen ? "" : "hidden"}>
          ${sources.length ? sources.map((source) => `
            <button
              class="target-option secondary ${source === selectedValue ? "active" : ""}"
              data-target-option="${pickerId}"
              data-target-value="${this._escape(source)}"
              type="button"
            >
              <ha-icon icon="${this._escape(this._targetIcon(source))}"></ha-icon>
              <span class="target-option-label">${this._escape(this._friendlyTarget(source, sources))}</span>
            </button>
          `).join("") : `<div class="muted">Keine Zielplayer verfuegbar</div>`}
        </div>
      </div>
    `;
  }

  _bindTargetPickerEvents(onSelect) {
    this.shadowRoot.querySelectorAll("[data-target-trigger]").forEach((button) => {
      button.addEventListener("click", () => {
        const pickerId = button.dataset.targetTrigger;
        this._targetMenuId = this._targetMenuId === pickerId ? null : pickerId;
        this.render();
      });
    });
    this.shadowRoot.querySelectorAll("[data-target-option]").forEach((button) => {
      button.addEventListener("click", async () => {
        const value = button.dataset.targetValue || "";
        this._targetMenuId = null;
        await onSelect(value);
      });
    });
  }

  async _handleTargetSelection(value) {
    this._selectedTarget = value;
    this._persistTargetPreference(value);
    await this._hass.callService("media_player", "select_source", {
      entity_id: this.integrationEntity,
      source: value
    });
  }

  _syncQueryFieldSpacing() {
    return;
  }

  _resultMarkup(item) {
    const subtitle = item.type === "artist" ? "" : (item.artist || item.playlist_name || "");
    const code = this._resultCode(item);
    const category = this._resultCategoryLabel(item.type);
    const isPending = this._isPendingResult(item.type, item.id);
    return `
      <div class="item">
        <div class="result-badge">
          <div class="badge-type">${this._escape(category)}</div>
          ${code ? `<button class="code-chip" data-copy-code="${this._escape(code)}" title="Copy ${this._escape(category)} code">${this._escape(this._displayResultCode(code))}</button>` : ""}
        </div>
        <img src="${this._escape(this._imageSrc(item.image_url))}" alt="" />
        <div class="meta">
          <div class="meta-main">
            <div class="main result-title" title="${this._escape(item.title || item.playlist_name || item.artist || item.id)}">${this._escape(item.title || item.playlist_name || item.artist || item.id)}</div>
            ${subtitle ? `<div class="muted result-subtitle" title="${this._escape(subtitle)}">${this._escape(subtitle)}</div>` : ""}
          </div>
          <div class="actions">
            <button class="${isPending ? "button-loading" : ""}" data-play-type="${this._escape(item.type)}" data-play-id="${this._escape(item.id)}" ${isPending ? "disabled" : ""}>
              <span class="button-content">
                ${isPending ? `<span class="button-spinner"></span><span>Starting...</span>` : `<span>Play</span>`}
              </span>
            </button>
            <button class="secondary" data-open-url="${this._escape(item.url || "")}">Go to YouTube Music</button>
          </div>
        </div>
      </div>
    `;
  }

  _imageSrc(value) {
    if (typeof value === "string" && value) {
      return value;
    }
    return "data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 96 96'%3E%3Crect width='96' height='96' rx='20' fill='%23242d39'/%3E%3Cpath d='M33 28v40l34-20-34-20z' fill='%23f15152'/%3E%3C/svg%3E";
  }

  _statusImageSrc(value, statusKind = "unknown_playback") {
    if (typeof value === "string" && value) {
      return value;
    }
    if (statusKind === "idle_empty") {
      return "data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 96 96'%3E%3Crect width='96' height='96' rx='20' fill='%23242d39'/%3E%3Cpath d='M28 50h24' stroke='%23f8fafc' stroke-width='6' stroke-linecap='round'/%3E%3Ccircle cx='62' cy='34' r='8' fill='none' stroke='%23f15152' stroke-width='6'/%3E%3Cpath d='m68 40 8 8' stroke='%23f15152' stroke-width='6' stroke-linecap='round'/%3E%3C/svg%3E";
    }
    return this._imageSrc("");
  }

  _typeLabel(value) {
    return ({
      all: "All",
      songs: "Songs",
      artists: "Artists",
      playlists: "Playlists"
    })[value] || value;
  }

  _resultCategoryLabel(value) {
    return ({
      song: "Song",
      artist: "Artist",
      playlist: "Playlist"
    })[value] || value;
  }

  _resultCode(item) {
    return item?.id || "";
  }

  _displayResultCode(value) {
    const normalized = value == null ? "" : String(value);
    if (!normalized) {
      return "";
    }
    return normalized.length > 5 ? `${normalized.slice(0, 5)}...` : normalized;
  }

  _asObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  _asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  _asString(value) {
    return value == null ? "" : String(value);
  }

  _activeResultFilters() {
    return Object.entries(this._filterSelection || {})
      .filter(([, enabled]) => !!enabled)
      .map(([type]) => type);
  }

  _visibleResults(results) {
    results = this._asArray(results);
    const activeFilters = this._activeResultFilters();
    if (!activeFilters.length) {
      return results;
    }
    return results.filter((item) => activeFilters.includes(item.type));
  }

  _toggleResultFilter(type) {
    this._filterSelection = {
      ...(this._filterSelection || {}),
      [type]: !(this._filterSelection || {})[type]
    };
    this.render();
  }

  async _copyText(value) {
    if (!value) {
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
    } catch (_error) {
      const input = document.createElement("textarea");
      input.value = value;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    }
  }

  _escape(value) {
    const normalized = value == null ? "" : String(value);
    return normalized.replace(/[&<>"']/g, (match) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;"
    }[match]));
  }
}

class YoutubeMusicBrowserCard extends YoutubeMusicConnectorBase {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._searchLoading = false;
    this._draftQuery = null;
    this._draftLimit = null;
    this._emptySearchPrompt = false;
    this._filterSelection = {
      song: false,
      artist: false,
      playlist: false
    };
  }

  async _runSearch() {
    const query = (this._draftQuery ?? this.shadowRoot.querySelector("#query")?.value ?? "").trim();
    const limit = Number(this._normalizeLimitValue(this._draftLimit ?? this.shadowRoot.querySelector("#limit")?.value ?? 5));
    if (!query) {
      this._emptySearchPrompt = true;
      this.render();
      return;
    }
    this._draftQuery = query;
    this._draftLimit = String(limit);
    this._emptySearchPrompt = false;
    this._searchLoading = true;
    this.render();
    try {
      await this._hass.callService("youtube_music_connector", "search", {
        entity_id: this.integrationEntity,
        query,
        search_type: "all",
        limit
      });
    } finally {
      this._searchLoading = false;
      this.render();
    }
  }

  async _loadMoreResults() {
    const currentLimit = Number(this._normalizeLimitValue(this._draftLimit ?? this.shadowRoot.querySelector("#limit")?.value ?? 5));
    const nextLimit = Math.min(99, currentLimit + 5);
    this._draftLimit = String(nextLimit);
    await this._runSearch();
  }

  async _play(itemType, itemId) {
    const target = this._selectedTarget || this.entityState?.attributes?.target_entity_id || "";
    this._beginPendingPlayback({
      mode: "result",
      itemType,
      itemId,
      targetEntityId: target
    });
    try {
      await this._hass.callService("youtube_music_connector", "play", {
        entity_id: this.integrationEntity,
        target_entity_id: target,
        item_type: itemType,
        item_id: itemId
      });
    } catch (error) {
      this._clearPendingPlayback();
      this.render();
      throw error;
    }
  }

  async _setTarget(value) {
    await this._handleTargetSelection(value);
  }

  async _stop() {
    const target = this._selectedTarget || this.entityState?.attributes?.target_entity_id || "";
    await this._hass.callService("youtube_music_connector", "stop", {
      entity_id: this.integrationEntity,
      target_entity_id: target
    });
  }

  render() {
    if (!this._hass) {
      return;
    }

    const entity = this.entityState;
    const attrs = entity?.attributes || {};
    const results = this._asArray(attrs.search_results);
    const currentItem = this._asObject(attrs.current_item);
    const currentTarget = this._resolveCurrentTarget(this._asString(attrs.target_entity_id));
    const query = this._asString(this._draftQuery ?? attrs.search_query ?? this.config.default_query ?? "");
    const fallbackLimit = attrs.search_count ? Math.max(results.length, Number(this.config.limit || 5)) : Number(this.config.limit || 5);
    const limit = this._draftLimit ?? String(fallbackLimit);
    const type = this._asString(attrs.search_type || this.config.search_type || "all");
    const hasCurrentItem = !!(currentItem.id || currentItem.title || currentItem.playlist_name || currentItem.artist);
    const lastError = this._asString(attrs.last_error);
    const volumePercent = this._effectiveTargetVolumePercent(currentTarget);
    const supportsVolume = this._supportsVolume(currentTarget);
    const autoplayEnabled = !!attrs.autoplay_enabled;
    const autoplayQueueLength = Number(attrs.autoplay_queue_length || 0);
    const shuffleEnabled = !!attrs.shuffle_enabled;
    const repeatMode = this._asString(attrs.repeat_mode) || "off";
    const state = this._asString(entity?.state) || "off";
    const hasUnknownExternalPlayback = !hasCurrentItem && state === "playing";
    const title = hasCurrentItem
      ? (currentItem.title || currentItem.playlist_name || currentItem.artist)
      : hasUnknownExternalPlayback
        ? "Wiedergabe aktiv"
        : "Noch nichts ausgewaehlt";
    const subtitle = hasCurrentItem
      ? (currentItem.artist || (currentItem.type ? `${currentItem.type} bereit` : ""))
      : hasUnknownExternalPlayback
        ? "Auf dem Zielgeraet laeuft bereits Audio. Titel ist dem Connector nicht bekannt."
        : "Suche starten oder Treffer abspielen";
    const image = this._statusImageSrc(
      currentItem.image_url || "",
      hasUnknownExternalPlayback ? "unknown_playback" : "idle_empty"
    );
    const pendingPlayback = this._isPendingPlaybackActive();
    const transportLabel = pendingPlayback ? "Starting..." : state === "playing" ? "Pause" : "Play";
    const transportIcon = pendingPlayback ? "" : state === "playing" ? "mdi:pause" : "mdi:play";
    const visibleResults = this._visibleResults(results);
    const limitNumber = Number(this._normalizeLimitValue(limit));
    const canLoadMore = !this._searchLoading && query.trim() !== "" && results.length >= limitNumber && limitNumber < 99;

    this.shadowRoot.innerHTML = `
      <style>${this._style()}
        .feature-block {
          display: grid;
          gap: 14px;
          padding: 0;
          background: transparent;
          border: 0;
        }
        .feature-block + .feature-block {
          padding-top: 18px;
          border-top: 1px solid rgba(255,255,255,0.06);
        }
        .block-label {
          font-size: 0.76rem;
          font-weight: 800;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: rgba(248,250,252,0.58);
        }
        .status-band {
          display: grid;
          gap: 8px;
          padding: 12px 14px;
          border-radius: 18px;
          background: rgba(255,255,255,0.035);
          border: 0;
        }
        .status-band.error {
          background: rgba(241,81,82,0.14);
        }
        .status-header-controls {
          display: grid;
          grid-template-columns: minmax(0, 1fr);
          gap: 10px;
          align-items: center;
          margin-bottom: 4px;
        }
        .status-header-controls .target-picker {
          width: 100%;
        }
        .status-grid {
          display: grid;
          grid-template-columns: 118px 1fr;
          gap: 14px;
          align-items: stretch;
        }
        .status-controls {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 10px;
          align-items: center;
        }
        .status-mode-actions {
          display: inline-flex;
          flex-wrap: wrap;
          gap: 10px;
          align-items: center;
        }
        .status-grid img {
          width: 100%;
          height: 100%;
          min-height: 100%;
          aspect-ratio: 1 / 1;
          align-self: stretch;
          object-fit: cover;
          border-radius: 20px;
          background: rgba(255,255,255,0.06);
        }
        .volume-row {
          display: grid;
          grid-template-columns: 72px 1fr 48px;
          gap: 10px;
          align-items: center;
        }
        .progress-block {
          display: grid;
          gap: 8px;
          margin-top: 6px;
        }
        .progress-meta {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          color: var(--ymc-muted);
          font-size: 0.82rem;
          font-variant-numeric: tabular-nums;
        }
        .loading {
          display: grid;
          justify-items: center;
          gap: 10px;
          padding: 18px 14px;
          border-radius: 18px;
          background: rgba(255,255,255,0.025);
          border: 0;
        }
        .spinner {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          border: 3px solid rgba(255,255,255,0.18);
          border-top-color: var(--ymc-accent);
          animation: ymc-spin 0.8s linear infinite;
        }
        @keyframes ymc-spin {
          to {
            transform: rotate(360deg);
          }
        }
        .empty-prompt {
          display: grid;
          justify-items: center;
          gap: 10px;
          padding: 24px 16px;
          border-radius: 18px;
          background: rgba(255,255,255,0.025);
          border: 1px dashed rgba(255,255,255,0.08);
          text-align: center;
        }
        .empty-prompt-text {
          color: var(--ymc-muted);
          font-size: 0.9rem;
          animation: ymc-pulse 1.8s ease-in-out infinite;
        }
        .load-more-wrap {
          display: flex;
          justify-content: center;
          padding-top: 4px;
        }
        .load-more-btn {
          min-width: 160px;
        }
        @keyframes ymc-pulse {
          0%, 100% {
            opacity: 0.48;
            transform: translateY(0);
          }
          50% {
            opacity: 1;
            transform: translateY(-1px);
          }
        }
        @media (max-width: 680px) {
          .status-header-controls {
            grid-template-columns: 1fr;
            justify-items: stretch;
          }
          .status-controls {
            grid-template-columns: 1fr;
          }
          .status-grid {
            grid-template-columns: 1fr;
          }
          .status-grid img {
            width: 92px;
            height: 92px;
            min-height: 92px;
          }
        }
      </style>
      <ha-card>
        <div class="shell">
          <div class="feature-block">
            <div class="status-band ${lastError ? "error" : ""}">
              <div class="status-header-controls">
                ${this._targetPickerMarkup(currentTarget, "target_player", "Zielplayer waehlen")}
              </div>
              <div class="status-grid">
                <img src="${this._escape(image)}" alt="" />
                <div class="meta">
                  <div class="main">${this._escape(title)}</div>
                  <div class="muted">${this._escape(subtitle)}</div>
                  <div class="status-controls">
                    ${hasCurrentItem ? `
                      <div class="status-mode-actions">
                        <button class="secondary ${pendingPlayback ? "button-loading" : ""}" id="play_pause_btn" title="${transportLabel}" ${pendingPlayback ? "disabled" : ""}>
                          <span class="button-content">
                            ${pendingPlayback ? `<span class="button-spinner"></span>` : `<ha-icon icon="${transportIcon}"></ha-icon>`}
                            <span>${transportLabel}</span>
                          </span>
                        </button>
                        <button class="icon-toggle ${autoplayEnabled ? "active" : ""}" id="autoplay_btn" title="${autoplayEnabled ? `Autoplay On (${autoplayQueueLength} queued)` : "Autoplay Off"}">
                          <ha-icon icon="mdi:playlist-play"></ha-icon>
                        </button>
                        <button class="icon-toggle ${shuffleEnabled ? "active" : ""}" id="shuffle_btn" title="${shuffleEnabled ? "Shuffle On" : "Shuffle Off"}">
                          <ha-icon icon="mdi:shuffle-variant"></ha-icon>
                        </button>
                        <button class="icon-toggle ${repeatMode !== "off" ? "active" : ""}" id="repeat_btn" title="${this._repeatTitle(repeatMode)}">
                          <ha-icon icon="${this._repeatIcon(repeatMode)}"></ha-icon>
                        </button>
                      </div>
                    ` : ""}
                    ${supportsVolume ? `
                      <div class="volume-row">
                        <div class="muted">Volume</div>
                        <input id="volume_slider" type="range" min="0" max="100" step="1" value="${volumePercent}" ${currentTarget ? "" : "disabled"} />
                        <div class="muted">${volumePercent}%</div>
                      </div>
                    ` : `<div></div>`}
                  </div>
                  ${lastError ? `<div class="muted">${this._escape(lastError)}</div>` : ``}
                  ${this._progressMarkup(entity)}
                </div>
              </div>
            </div>
          </div>

          <div class="feature-block">
            <div class="block-label">Suche</div>
            <div class="controls">
              <div class="query-row">
                <div class="query-field">
                  <input id="query" type="text" placeholder="Suche nach Song, Artist oder Playlist" value="${this._escape(query)}" />
                  <div class="filter-strip">
                    <button class="filter-chip ${this._filterSelection.song ? "active" : ""}" data-filter-type="song" title="Filter songs">Songs</button>
                    <button class="filter-chip ${this._filterSelection.artist ? "active" : ""}" data-filter-type="artist" title="Filter artists">Artists</button>
                    <button class="filter-chip ${this._filterSelection.playlist ? "active" : ""}" data-filter-type="playlist" title="Filter playlists">Playlists</button>
                  </div>
                </div>
                ${this._searchLoading ? "" : `
                  <div class="search-submit" id="run_search">
                    <span class="search-submit-title">Suche</span>
                    <input id="limit" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="2" value="${limit}" />
                    <span class="search-submit-label">Ergebnisse</span>
                  </div>
                `}
              </div>
            </div>
            <div class="results">
              ${this._searchLoading ? `
                <div class="loading">
                  <div class="spinner"></div>
                  <div class="subline">Ergebnisse werden geladen...</div>
                </div>
              ` : this._emptySearchPrompt ? `
                <div class="empty-prompt">
                  <div class="empty-prompt-text">Bitte etwas in die Suche eingeben.</div>
                </div>
              ` : visibleResults.length ? visibleResults.map((item) => this._resultMarkup(item)).join("") : results.length ? `
                <div class="item empty-item">
                  <div class="empty-item-copy">
                    <div class="main">Keine Treffer fuer den aktiven Filter</div>
                    <div class="muted">Songs, Artists oder Playlists anpassen, damit passende Suchergebnisse sichtbar werden.</div>
                  </div>
                </div>
              ` : `
                <div class="item empty-item">
                  <div class="empty-item-copy">
                    <div class="main">Noch keine Suchergebnisse</div>
                    <div class="muted">Suche starten, Filter waehlen und einen Zielplayer setzen. Danach erscheinen Treffer genau hier.</div>
                  </div>
                </div>
              `}
              ${canLoadMore ? `
                <div class="load-more-wrap">
                  <button class="secondary load-more-btn" id="load_more_btn">Mehr laden</button>
                </div>
              ` : ""}
            </div>
          </div>
        </div>
      </ha-card>
    `;

    this.shadowRoot.querySelector("#run_search")?.addEventListener("click", (event) => {
      if (event.target?.id === "limit") {
        return;
      }
      this._runSearch();
    });
    this.shadowRoot.querySelector("#query")?.addEventListener("input", (event) => {
      this._draftQuery = event.target.value;
      if (event.target.value.trim()) {
        this._emptySearchPrompt = false;
      }
    });
    this.shadowRoot.querySelector("#query")?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        this._runSearch();
      }
    });
    this._bindLimitInput(this.shadowRoot.querySelector("#limit"), (value) => {
      this._draftLimit = value;
    }, () => this._runSearch());
    this.shadowRoot.querySelectorAll("[data-filter-type]").forEach((button) => {
      button.addEventListener("click", () => this._toggleResultFilter(button.dataset.filterType));
    });
    this._bindTargetPickerEvents((value) => this._setTarget(value));
    this.shadowRoot.querySelector("#volume_slider")?.addEventListener("input", (event) => this._setTargetVolume(currentTarget, event.target.value));
    this.shadowRoot.querySelector("#progress_slider")?.addEventListener("input", (event) => this._previewSeek(event.target.value));
    this.shadowRoot.querySelector("#progress_slider")?.addEventListener("change", (event) => this._seekCurrent(event.target.value));
    this.shadowRoot.querySelector("#autoplay_btn")?.addEventListener("click", () => this._setAutoplay(!this.entityState?.attributes?.autoplay_enabled));
    this.shadowRoot.querySelector("#shuffle_btn")?.addEventListener("click", () => this._setShuffle(!this.entityState?.attributes?.shuffle_enabled));
    this.shadowRoot.querySelector("#repeat_btn")?.addEventListener("click", () => this._cycleRepeatMode(this.entityState?.attributes?.repeat_mode || "off"));
    this.shadowRoot.querySelector("#play_pause_btn")?.addEventListener("click", () => this._togglePlayPause());
    this.shadowRoot.querySelector("#load_more_btn")?.addEventListener("click", () => this._loadMoreResults());
    this.shadowRoot.querySelectorAll("[data-play-type]").forEach((button) => {
      button.addEventListener("click", () => this._play(button.dataset.playType, button.dataset.playId));
    });
    this.shadowRoot.querySelectorAll("[data-open-url]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.openUrl) {
          window.open(button.dataset.openUrl, "_blank", "noopener");
        }
      });
    });
    this.shadowRoot.querySelectorAll("[data-copy-code]").forEach((button) => {
      button.addEventListener("click", () => this._copyText(button.dataset.copyCode));
    });
    this._syncQueryFieldSpacing();
  }
}

class YoutubeMusicSearchCard extends YoutubeMusicConnectorBase {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  async _runSearch() {
    const query = this.shadowRoot.querySelector("#query")?.value?.trim() || "";
    const searchType = this.shadowRoot.querySelector("#search_type")?.value || "all";
    const limit = Number(this._normalizeLimitValue(this.shadowRoot.querySelector("#limit")?.value || 5));
    if (!query) {
      return;
    }
    await this._hass.callService("youtube_music_connector", "search", {
      entity_id: this.integrationEntity,
      query,
      search_type: searchType,
      limit
    });
  }

  async _play(itemType, itemId) {
    const target = this._selectedTarget || this.entityState?.attributes?.target_entity_id || "";
    this._beginPendingPlayback({
      mode: "result",
      itemType,
      itemId,
      targetEntityId: target
    });
    try {
      await this._hass.callService("youtube_music_connector", "play", {
        entity_id: this.integrationEntity,
        target_entity_id: target,
        item_type: itemType,
        item_id: itemId
      });
    } catch (error) {
      this._clearPendingPlayback();
      this.render();
      throw error;
    }
  }

  render() {
    if (!this._hass) {
      return;
    }
    const entity = this.entityState;
    const attrs = entity?.attributes || {};
    const results = attrs.search_results || [];
    const currentTarget = this._resolveCurrentTarget(attrs.target_entity_id || "");
    const query = attrs.search_query || this.config.default_query || "";
    const limit = this.config.limit || 5;
    const type = attrs.search_type || this.config.search_type || "all";

    this.shadowRoot.innerHTML = `
      <style>${this._style()}</style>
      <ha-card>
        <div class="shell">
          <div class="section-title">
            <div>
              <div class="headline">YouTube Music Suche</div>
              <div class="subline">Songs, Artists und Playlists direkt in Home Assistant</div>
            </div>
          </div>
          <div class="controls">
            <div class="row">
              <input id="query" type="text" placeholder="Suche nach Song, Artist oder Playlist" value="${this._escape(query)}" />
            </div>
            <div class="row compact">
              <select id="search_type">
                ${["all", "songs", "artists", "playlists"].map(option => `<option value="${option}" ${option === type ? "selected" : ""}>${this._typeLabel(option)}</option>`).join("")}
              </select>
                <input id="limit" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="2" value="${limit}" />
              <button id="run_search">Suchen</button>
            </div>
            <div class="row">
              ${this._targetPickerMarkup(currentTarget, "target_player", "Zielplayer waehlen")}
            </div>
          </div>
          <div class="results">
            ${results.length ? results.map((item) => this._resultMarkup(item)).join("") : `<div class="subline">Noch keine Treffer. Suche starten, um Ergebnisse und direkte Play-Aktionen zu sehen.</div>`}
          </div>
        </div>
      </ha-card>
    `;

    this.shadowRoot.querySelector("#run_search")?.addEventListener("click", () => this._runSearch());
    this._bindLimitInput(this.shadowRoot.querySelector("#limit"), (value) => {
      this.shadowRoot.querySelector("#limit").value = value === "" ? "" : value;
    }, () => this._runSearch());
    this._bindTargetPickerEvents((value) => this._handleTargetSelection(value));
    this.shadowRoot.querySelectorAll("[data-play-type]").forEach((button) => {
      button.addEventListener("click", () => this._play(button.dataset.playType, button.dataset.playId));
    });
    this.shadowRoot.querySelectorAll("[data-open-url]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.openUrl) {
          window.open(button.dataset.openUrl, "_blank", "noopener");
        }
      });
    });
    this.shadowRoot.querySelectorAll("[data-copy-code]").forEach((button) => {
      button.addEventListener("click", () => this._copyText(button.dataset.copyCode));
    });
  }
}

class YoutubeMusicPlayerCard extends YoutubeMusicConnectorBase {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  async _transport(action) {
    await this._hass.callService("media_player", action, {
      entity_id: this.integrationEntity
    });
  }

  async _setTarget(value) {
    await this._hass.callService("media_player", "select_source", {
      entity_id: this.integrationEntity,
      source: value
    });
  }

  render() {
    if (!this._hass) {
      return;
    }
    const entity = this.entityState;
    const attrs = entity?.attributes || {};
    const current = attrs.current_item || {};
    const currentTarget = this._resolveCurrentTarget(attrs.target_entity_id || "");
    const state = entity?.state || "off";
    const hasCurrentItem = !!(current.id || current.title || current.playlist_name || current.artist);
    const hasUnknownExternalPlayback = !hasCurrentItem && state === "playing";
    const title = hasCurrentItem
      ? (current.title || current.playlist_name || current.artist)
      : hasUnknownExternalPlayback
        ? "Wiedergabe aktiv"
        : "Noch nichts ausgewaehlt";
    const subtitle = hasCurrentItem
      ? (current.artist || (current.type ? `${current.type} bereit` : ""))
      : hasUnknownExternalPlayback
        ? "Auf dem Zielgeraet laeuft bereits Audio. Titel ist dem Connector nicht bekannt."
        : "Bereit fuer Wiedergabe";
    const image = this._statusImageSrc(
      current.image_url || "",
      hasUnknownExternalPlayback ? "unknown_playback" : "idle_empty"
    );
    const volumePercent = this._effectiveTargetVolumePercent(currentTarget);
    const supportsVolume = this._supportsVolume(currentTarget);
    const pendingPlayback = this._isPendingPlaybackActive();
    const transportLabel = pendingPlayback ? "Starting..." : state === "playing" ? "Pause" : "Play";
    const transportIcon = pendingPlayback ? "" : state === "playing" ? "mdi:pause" : "mdi:play";

    this.shadowRoot.innerHTML = `
      <style>${this._style()}</style>
      <ha-card>
        <div class="shell">
          <div class="section-title">
            <div>
              <div class="headline">YouTube Music Player</div>
              <div class="subline">Status, Zielplayer und Transportsteuerung</div>
            </div>
            <div class="pill">${this._escape(entity?.state || "off")}</div>
          </div>
          <div class="cover">
            <div class="art-wrap">
              <img src="${this._escape(image)}" alt="" />
              <div class="meta">
                <div class="main">${this._escape(title)}</div>
                <div class="muted">${this._escape(subtitle)}</div>
              </div>
            </div>
            <div class="row">
              ${this._targetPickerMarkup(currentTarget, "target_source", "Zielplayer waehlen")}
            </div>
            ${supportsVolume ? `
              <div class="volume-row">
                <div class="muted">Volume</div>
                <input id="target_volume" type="range" min="0" max="100" step="1" value="${volumePercent}" ${currentTarget ? "" : "disabled"} />
                <div class="muted">${volumePercent}%</div>
              </div>
            ` : ""}
            ${this._progressMarkup(entity)}
            <div class="transport">
              <button class="${pendingPlayback ? "button-loading" : ""}" id="play_pause_btn" ${pendingPlayback ? "disabled" : ""}>
                <span class="button-content">
                  ${pendingPlayback ? `<span class="button-spinner"></span>` : `<ha-icon icon="${transportIcon}"></ha-icon>`}
                  <span>${transportLabel}</span>
                </span>
              </button>
              <button class="secondary" id="stop_btn">Stop</button>
            </div>
          </div>
        </div>
      </ha-card>
    `;

    this.shadowRoot.querySelector("#play_pause_btn")?.addEventListener("click", () => this._togglePlayPause());
    this.shadowRoot.querySelector("#stop_btn")?.addEventListener("click", () => this._transport("media_stop"));
    this._bindTargetPickerEvents((value) => this._setTarget(value));
    this.shadowRoot.querySelector("#target_volume")?.addEventListener("input", (event) => this._setTargetVolume(currentTarget, event.target.value));
    this.shadowRoot.querySelector("#progress_slider")?.addEventListener("change", (event) => this._seekCurrent(event.target.value));
  }
}

customElements.define("youtube-music-browser-card", YoutubeMusicBrowserCard);
customElements.define("youtube-music-search-card", YoutubeMusicSearchCard);
customElements.define("youtube-music-player-card", YoutubeMusicPlayerCard);
