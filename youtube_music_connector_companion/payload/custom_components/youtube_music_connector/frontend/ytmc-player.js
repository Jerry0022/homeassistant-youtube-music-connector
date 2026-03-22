/**
 * <ytmc-player> — YouTube Music Connector: Now Playing + Transport
 *
 * Usage:
 *   const el = document.createElement("ytmc-player");
 *   el.entityId = "media_player.youtube_music_connector";
 *   el.hass = hassObject;
 *   container.appendChild(el);
 *
 * CSS custom properties (set on host or ancestor):
 *   --ytmc-bg              Background color           (default: #0f1923)
 *   --ytmc-surface         Card / overlay surface      (default: rgba(255,255,255,0.06))
 *   --ytmc-text            Primary text color          (default: #f8fafc)
 *   --ytmc-text-secondary  Secondary / muted text      (default: rgba(248,250,252,0.72))
 *   --ytmc-accent          Accent / highlight color    (default: #4a9eff)
 *   --ytmc-accent-active   Active state accent         (default: #2d7fe0)
 *   --ytmc-radius          Border radius               (default: 18px)
 *   --ytmc-font-family     Font family                 (default: inherit)
 */
class YtmcPlayer extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._entityId = "";
    this._hass = null;
    this._progressTicker = null;
    this._draftSeek = null;
    this._renderSig = "";
    this._recentTargets = []; // sorted by last selection, most recent first
    this._selectedTargets = new Set(); // multi-select device chips
    this._showAllDevices = false;
    this._excludeDevices = [];
    this._lastToggleTime = 0;
    this._lastSyncKey = "";
    this._userHasToggled = false;
  }

  /* ── Lovelace card interface ── */
  static getConfigElement() { return document.createElement("ytmc-player-editor"); }
  static getStubConfig() { return { entity: "media_player.youtube_music_connector" }; }
  setConfig(config) {
    this._config = config;
    if (config.entity) this.entityId = config.entity;
    if (Array.isArray(config.exclude_devices)) this._excludeDevices = config.exclude_devices;
  }
  getCardSize() { return 4; }

  set entityId(val) { this._entityId = val; this._tryRender(); }
  get entityId() { return this._entityId; }
  set excludeDevices(val) { this._excludeDevices = Array.isArray(val) ? val : []; this._tryRender(); }
  get excludeDevices() { return this._excludeDevices; }
  set hass(hass) { this._hass = hass; this._syncProgressTicker(); this._tryRender(); }
  get hass() { return this._hass; }
  disconnectedCallback() { this._clearTicker(); }

  /* ── state helpers ── */
  get _entity() { return this._hass?.states?.[this._entityId]; }
  get _attrs() { return this._entity?.attributes || {}; }
  get _state() { return this._entity?.state || "off"; }
  get _isPlaying() { return this._state === "playing"; }
  get _isPaused() { return this._state === "paused"; }
  get _isActive() { return this._isPlaying || this._isPaused; }

  _targetFriendlyName() {
    const tid = this._attrs.target_entity_id;
    if (!tid) return "";
    const s = this._hass?.states?.[tid];
    return s?.attributes?.friendly_name || tid.replace("media_player.", "");
  }

  /* ── progress ── */
  _mediaDuration() {
    const d = this._attrs.media_duration ?? this._hass?.states?.[this._attrs.target_entity_id]?.attributes?.media_duration;
    return typeof d === "number" ? d : null;
  }
  _mediaPosition() {
    if (this._draftSeek !== null) return this._draftSeek;
    const tid = this._attrs.target_entity_id;
    const target = tid ? this._hass?.states?.[tid] : null;
    const pos = target?.attributes?.media_position;
    if (typeof pos !== "number") return null;
    if (target.state !== "playing") return pos;
    const updatedAt = target.attributes.media_position_updated_at;
    if (!updatedAt) return pos;
    const elapsed = (Date.now() - new Date(updatedAt).getTime()) / 1000;
    return Math.min(pos + elapsed, this._mediaDuration() || Infinity);
  }
  _syncProgressTicker() {
    if (this._isPlaying && !this._progressTicker) {
      this._progressTicker = setInterval(() => this._updateProgress(), 1000);
    } else if (!this._isPlaying && this._progressTicker) {
      this._clearTicker();
    }
  }
  _clearTicker() { if (this._progressTicker) { clearInterval(this._progressTicker); this._progressTicker = null; } }
  _updateProgress() {
    const bar = this.shadowRoot.querySelector(".progress-fill");
    const posEl = this.shadowRoot.querySelector(".pos-current");
    if (!bar || !posEl) return;
    const dur = this._mediaDuration();
    const pos = this._mediaPosition();
    if (dur && pos != null) {
      bar.style.width = `${Math.min((pos / dur) * 100, 100)}%`;
      posEl.textContent = this._fmtTime(pos);
    }
  }
  _fmtTime(s) {
    if (s == null || isNaN(s)) return "0:00";
    s = Math.max(0, Math.floor(s));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  /* ── service calls ── */
  _sortedSources(sources, activeTarget) {
    // Put recently selected first, then rest alphabetically
    const recent = this._recentTargets.filter(t => sources.includes(t));
    const rest = sources.filter(t => !recent.includes(t));
    // Ensure activeTarget is always first if not already
    const sorted = [...recent, ...rest];
    if (activeTarget && sorted.includes(activeTarget)) {
      const idx = sorted.indexOf(activeTarget);
      if (idx > 0) { sorted.splice(idx, 1); sorted.unshift(activeTarget); }
    }
    return sorted;
  }

  _isTargetActive(tid) {
    if (this._selectedTargets.size > 0) return this._selectedTargets.has(tid);
    return tid === this._attrs.target_entity_id;
  }

  _syncSelectedFromBackend() {
    // Skip sync briefly after user toggle to avoid visual flicker
    if (this._lastToggleTime && Date.now() - this._lastToggleTime < 2000) return;
    const backendSelected = this._attrs.selected_devices || [];
    const key = JSON.stringify(backendSelected);
    if (key !== this._lastSyncKey) {
      this._selectedTargets = new Set(backendSelected);
      this._lastSyncKey = key;
      this._userHasToggled = false;
    }
  }

  async _toggleTarget(entityId) {
    this._lastToggleTime = Date.now();
    if (!this._userHasToggled) {
      // First explicit interaction: switch to this device only
      this._userHasToggled = true;
      this._selectedTargets.clear();
      this._selectedTargets.add(entityId);
    } else if (this._selectedTargets.has(entityId)) {
      this._selectedTargets.delete(entityId);
    } else {
      this._selectedTargets.add(entityId);
    }
    this._recentTargets = [entityId, ...this._recentTargets.filter(t => t !== entityId)];
    const targets = [...this._selectedTargets];
    await this._hass.callService("youtube_music_connector", "set_selected_devices", { entity_id: this._entityId, selected_devices: targets });
    this._renderSig = "";
    this._tryRender();
  }
  async _togglePlayPause() {
    await this._hass.callService("media_player", this._isPlaying ? "media_pause" : "media_play", { entity_id: this._entityId });
  }
  async _nextTrack() { await this._hass.callService("youtube_music_connector", "next_track", { entity_id: this._entityId }); }
  async _previousTrack() { await this._hass.callService("youtube_music_connector", "previous_track", { entity_id: this._entityId }); }
  async _setAutoplay(enabled) { await this._hass.callService("youtube_music_connector", "set_autoplay", { entity_id: this._entityId, enabled }); }
  async _setShuffle(enabled) { await this._hass.callService("youtube_music_connector", "set_shuffle", { entity_id: this._entityId, shuffle_enabled: enabled }); }
  async _cycleRepeat() {
    const order = ["off", "forever", "once"];
    const cur = this._attrs.repeat_mode || "off";
    await this._hass.callService("youtube_music_connector", "set_repeat_mode", { entity_id: this._entityId, repeat_mode: order[(order.indexOf(cur) + 1) % order.length] });
  }
  async _setVolume(val) {
    const targets = this._allActiveTargets();
    const promises = targets.map(async (tid) => {
      const state = this._hass?.states?.[tid];
      // Skip devices that don't support volume_set (bit 4 = SUPPORT_VOLUME_SET)
      const features = parseInt(state?.attributes?.supported_features || 0);
      if (!(features & 4)) return;
      if (state?.state === "off" || state?.state === "standby") {
        await this._hass.callService("media_player", "turn_on", { entity_id: tid });
        await new Promise(r => setTimeout(r, 3000));
      }
      await this._hass.callService("media_player", "volume_set", { entity_id: tid, volume_level: val / 100 });
    });
    await Promise.all(promises);
  }

  _allActiveTargets() {
    if (this._selectedTargets.size > 0) return [...this._selectedTargets];
    const tid = this._attrs.target_entity_id;
    return tid ? [tid] : [];
  }

  _groupVolumePct() {
    const targets = this._allActiveTargets();
    if (targets.length === 0) return 50;
    let maxVol = 0;
    for (const tid of targets) {
      const s = this._hass?.states?.[tid];
      const v = s?.attributes?.volume_level;
      if (typeof v === "number" && v > maxVol) maxVol = v;
    }
    return Math.round(maxVol * 100);
  }
  async _seekTo(pos) {
    const tid = this._attrs.target_entity_id;
    if (!tid) return;
    this._draftSeek = null;
    await this._hass.callService("media_player", "media_seek", { entity_id: tid, seek_position: pos });
  }

  /* ── render gate ── */
  _sig() {
    const e = this._entity;
    if (!e) return "";
    const a = e.attributes || {};
    const tid = a.target_entity_id;
    const t = tid ? this._hass?.states?.[tid] : null;
    const tState = t?.state;
    const tVol = t?.attributes?.volume_level;
    const tDur = t?.attributes?.media_duration;
    const tPosUp = t?.attributes?.media_position_updated_at;
    const selectedDevices = a.selected_devices || [];
    const groupVols = selectedDevices.length > 1
      ? selectedDevices.map(id => this._hass?.states?.[id]?.attributes?.volume_level).join()
      : "";
    return JSON.stringify([e.state, a.media_title, a.media_artist, a.media_image_url, tid, a.available_target_players, a.shuffle_enabled, a.repeat_mode, a.has_next_track, a.has_previous_track, a.autoplay_enabled, a.autoplay_queue_length, a.selected_devices, tState, tVol, tDur, tPosUp, groupVols]);
  }
  _tryRender() { const s = this._sig(); if (s === this._renderSig) return; this._renderSig = s; this._render(); }

  /* ── render ── */
  _render() {
    const entity = this._entity;
    if (!entity) { this.shadowRoot.innerHTML = ""; return; }
    this._syncSelectedFromBackend();
    const a = this._attrs;
    const state = this._state;
    const isGroupMode = this._selectedTargets.size > 1;
    const title = a.media_title || a.current_item?.title || "";
    const artist = a.media_artist || a.current_item?.artist || "";
    const imageUrl = a.media_image_url || a.entity_picture || a.current_item?.image_url || "";
    const targetName = this._targetFriendlyName();
    const autoplayOn = !!a.autoplay_enabled;
    const shuffleOn = !!a.shuffle_enabled;
    const repeatMode = a.repeat_mode || "off";
    const repeatIcon = repeatMode === "once" ? "mdi:repeat-once" : "mdi:repeat";
    const repeatActive = repeatMode !== "off";
    const hasNext = !!a.has_next_track;
    const hasPrev = !!a.has_previous_track;
    const dur = this._mediaDuration();
    const pos = this._mediaPosition();
    const pct = dur && pos != null ? Math.min((pos / dur) * 100, 100) : 0;
    const tid = a.target_entity_id;
    const target = tid ? this._hass?.states?.[tid] : null;
    const vol = target?.attributes?.volume_level;
    const supportsVolume = isGroupMode ? this._allActiveTargets().length > 0 : target && (parseInt(target.attributes?.supported_features || 0) & 4);
    const supportsSeek = !isGroupMode && target && (parseInt(target.attributes?.supported_features || 0) & 16);
    const volPct = isGroupMode ? this._groupVolumePct() : (vol != null ? Math.round(vol * 100) : 50);
    // Detect if target is playing something (even if not from this connector)
    const targetState = target?.state;
    const targetIsPlaying = targetState === "playing" || targetState === "paused";
    const targetDur = target?.attributes?.media_duration;
    const hasTrack = !!title;

    // Device selector options
    const sources = (a.available_target_players || []).filter(s => !this._excludeDevices.includes(s));

    this.shadowRoot.innerHTML = `
      <style>${this._css()}</style>
      <div class="player ${this._isActive ? "active" : ""}">
        ${imageUrl ? `<div class="bg-art" style="background-image:url('${imageUrl}')"></div>` : ""}
        <div class="bg-overlay"></div>
        <div class="content">
          <!-- Device chips + volume — top row -->
          <div class="top-row">
            ${this._renderDeviceChips(sources, tid)}
            ${supportsVolume ? `
            <div class="volume">
              <ha-icon icon="${volPct === 0 ? "mdi:volume-off" : volPct < 50 ? "mdi:volume-medium" : "mdi:volume-high"}"></ha-icon>
              <input type="range" class="vol-slider" min="0" max="100" value="${volPct}" data-action="volume" />
            </div>` : ""}
          </div>

          ${hasTrack ? `
          <div class="track-info">
            <div class="track-title">${this._esc(title)}</div>
            <div class="track-subtitle">${this._esc(artist) || "\u00A0"}</div>
          </div>` : ""}

          ${hasTrack || targetIsPlaying || this._selectedTargets.size > 0 ? `
          <div class="controls-row">
            ${hasTrack ? `
            <div class="transport">
              <button class="transport-btn ${hasPrev ? '' : 'disabled'}" data-action="prev" title="Previous"><ha-icon icon="mdi:skip-previous"></ha-icon></button>
              <button class="transport-btn play-btn" data-action="playpause" title="${this._isPlaying ? "Pause" : "Play"}">
                <ha-icon icon="${this._isPlaying ? "mdi:pause" : "mdi:play"}"></ha-icon>
              </button>
              <button class="transport-btn ${hasNext ? '' : 'disabled'}" data-action="next" title="Next"><ha-icon icon="mdi:skip-next"></ha-icon></button>
            </div>` : `
            <div class="transport">
              <button class="transport-btn ${hasPrev ? '' : 'disabled'}" data-action="prev" title="Previous"><ha-icon icon="mdi:skip-previous"></ha-icon></button>
              <button class="transport-btn play-btn" data-action="playpause" title="${targetState === "playing" ? "Pause" : "Play"}">
                <ha-icon icon="${targetState === "playing" ? "mdi:pause" : "mdi:play"}"></ha-icon>
              </button>
              <button class="transport-btn ${hasNext ? '' : 'disabled'}" data-action="next" title="Next"><ha-icon icon="mdi:skip-next"></ha-icon></button>
            </div>`}
          </div>` : ""}

          ${(this._isActive || targetIsPlaying) && dur && !isGroupMode ? `
          <div class="progress-row">
            <span class="pos-current">${this._fmtTime(pos)}</span>
            <div class="progress-track ${supportsSeek ? "" : "no-seek"}" ${supportsSeek ? 'data-action="seek"' : ""}>
              <div class="progress-fill" style="width:${pct}%"></div>
            </div>
            <span class="pos-total">${this._fmtTime(dur)}</span>
            ${hasTrack ? `
            <button class="mini-btn ${autoplayOn ? "on" : ""}" data-action="autoplay" title="Autoplay">
              <ha-icon icon="mdi:playlist-play"></ha-icon>
            </button>
            <button class="mini-btn ${repeatActive ? "on" : ""}" data-action="repeat" title="Repeat: ${repeatMode}">
              <ha-icon icon="${repeatIcon}"></ha-icon>
            </button>
            <button class="mini-btn ${shuffleOn ? "on" : ""}" data-action="shuffle" title="Shuffle">
              <ha-icon icon="mdi:shuffle-variant"></ha-icon>
            </button>` : ""}
          </div>` : ""}
        </div>
      </div>
    `;
    this._bindEvents();
  }

  _renderDeviceChips(sources, activeTarget) {
    const sorted = this._sortedSources(sources, activeTarget);
    const visible = this._showAllDevices ? sorted : sorted.slice(0, 3);
    const hiddenCount = sorted.length - visible.length;
    return `
      <div class="device-chips">
        ${visible.map((s) => `
          <button class="dev-chip ${this._isTargetActive(s) ? "active" : ""}" data-target="${this._esc(s)}">
            <ha-icon icon="mdi:${s.includes("chromecast") || s.includes("tv") ? "television" : "speaker"}"></ha-icon>
            ${this._esc(this._friendlyName(s))}
          </button>
        `).join("")}
        ${hiddenCount > 0 ? `
          <button class="dev-chip more-chip" data-action="show-more-devices">
            +${hiddenCount}
          </button>
        ` : ""}
      </div>
    `;
  }

  _friendlyName(entityId) {
    const s = this._hass?.states?.[entityId];
    return s?.attributes?.friendly_name || entityId.replace("media_player.", "");
  }

  _esc(s) { if (!s) return ""; const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

  _bindEvents() {
    this.shadowRoot.querySelectorAll("[data-target]").forEach((btn) => {
      btn.addEventListener("click", () => this._toggleTarget(btn.dataset.target));
    });
    this.shadowRoot.querySelectorAll("[data-action]").forEach((el) => {
      const action = el.dataset.action;
      if (action === "show-more-devices") { el.addEventListener("click", () => { this._showAllDevices = !this._showAllDevices; this._renderSig = ""; this._tryRender(); }); return; }
      if (action === "playpause") el.addEventListener("click", () => this._togglePlayPause());
      else if (action === "next") el.addEventListener("click", () => this._nextTrack());
      else if (action === "prev") el.addEventListener("click", () => this._previousTrack());
      else if (action === "autoplay") el.addEventListener("click", () => this._setAutoplay(!this._attrs.autoplay_enabled));
      else if (action === "shuffle") el.addEventListener("click", () => this._setShuffle(!this._attrs.shuffle_enabled));
      else if (action === "repeat") el.addEventListener("click", () => this._cycleRepeat());
      else if (action === "volume") el.addEventListener("change", (e) => this._setVolume(Number(e.target.value)));
      else if (action === "seek") el.addEventListener("click", (e) => {
        const rect = el.getBoundingClientRect();
        const dur = this._mediaDuration();
        if (dur) this._seekTo(Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)) * dur);
      });
    });
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

      .player {
        position: relative;
        overflow: hidden;
        border-radius: var(--_radius);
        background: var(--_bg);
        border: 1px solid rgba(255,255,255,0.06);
        box-shadow: 0 8px 32px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.04);
      }

      /* blurred album art background */
      .bg-art {
        position: absolute; inset: -30px;
        background-size: cover;
        background-position: center;
        filter: blur(50px) brightness(0.4) saturate(1.4);
        transform: scale(1.4);
        z-index: 0;
      }
      .bg-overlay {
        position: absolute; inset: 0;
        background: linear-gradient(180deg,
          rgba(15,25,35,0.45) 0%,
          rgba(15,25,35,0.7) 50%,
          rgba(15,25,35,0.88) 100%);
        z-index: 1;
      }

      .content {
        position: relative; z-index: 2;
        padding: 28px 32px 24px;
        display: grid;
        gap: 16px;
      }

      /* ── top row: devices + volume ── */
      .top-row {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
      }

      /* ── device chips ── */
      .device-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .dev-chip {
        all: unset;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 9px 18px 9px 12px;
        border-radius: 999px;
        font-size: 0.84rem;
        font-weight: 500;
        background: rgba(0,0,0,0.25);
        color: var(--_text2);
        border: 1px solid rgba(255,255,255,0.08);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        transition: all 0.18s ease;
        white-space: nowrap;
      }
      .dev-chip:hover {
        background: rgba(255,255,255,0.08);
        border-color: rgba(255,255,255,0.14);
        color: var(--_text);
      }
      .dev-chip.active {
        background: var(--_accent);
        color: #fff;
        border-color: var(--_accent);
        box-shadow: 0 2px 12px rgba(74,158,255,0.25);
      }
      .dev-chip ha-icon { --mdc-icon-size: 16px; opacity: 0.7; }
      .dev-chip.active ha-icon { opacity: 1; }
      .more-chip {
        font-weight: 700;
        font-size: 0.78rem;
        padding: 9px 14px;
        letter-spacing: 0.02em;
      }

      /* ── track info ── */
      .track-info { padding: 4px 0; }
      .track-title {
        font-size: 1.6rem;
        font-weight: 800;
        line-height: 1.2;
        color: var(--_text);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        text-shadow: 0 2px 12px rgba(0,0,0,0.3);
      }
      .track-subtitle {
        font-size: 0.92rem;
        color: var(--_text2);
        margin-top: 4px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      /* ── controls row ── */
      .controls-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        flex-wrap: wrap;
        margin-top: 4px;
      }
      .transport {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      button {
        all: unset;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        transition: all 0.18s ease;
      }
      button:active { transform: scale(0.9); }

      .transport-btn {
        width: 46px; height: 46px;
        color: var(--_text);
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.06);
      }
      .transport-btn:hover {
        background: rgba(255,255,255,0.1);
        border-color: rgba(255,255,255,0.12);
      }
      .transport-btn ha-icon { --mdc-icon-size: 24px; }
      .transport-btn.disabled {
        opacity: 0.3;
        pointer-events: none;
        cursor: default;
      }

      .play-btn {
        width: 54px; height: 54px;
        background: var(--_accent);
        color: #fff;
        border: none;
        box-shadow: 0 4px 16px rgba(74,158,255,0.3);
      }
      .play-btn:hover {
        background: var(--_accent-active);
        box-shadow: 0 4px 20px rgba(74,158,255,0.45);
        transform: scale(1.06);
      }
      .play-btn:active { transform: scale(0.94); }
      .play-btn ha-icon { --mdc-icon-size: 28px; }

      /* ── volume ── */
      .volume {
        display: flex;
        align-items: center;
        gap: 10px;
        color: var(--_text2);
        flex-shrink: 0;
      }
      .volume ha-icon { --mdc-icon-size: 20px; }
      .vol-slider {
        -webkit-appearance: none;
        appearance: none;
        width: 110px;
        height: 5px;
        border-radius: 3px;
        background: rgba(255,255,255,0.12);
        outline: none;
        cursor: pointer;
      }
      .vol-slider::-webkit-slider-thumb {
        -webkit-appearance: none;
        width: 16px; height: 16px;
        border-radius: 50%;
        background: var(--_accent);
        box-shadow: 0 2px 8px rgba(74,158,255,0.35);
        cursor: pointer;
      }
      .vol-slider::-moz-range-thumb {
        width: 16px; height: 16px;
        border-radius: 50%;
        background: var(--_accent);
        border: none;
        box-shadow: 0 2px 8px rgba(74,158,255,0.35);
        cursor: pointer;
      }

      /* ── progress ── */
      .progress-row {
        display: flex;
        align-items: center;
        gap: 12px;
        font-size: 0.8rem;
        font-variant-numeric: tabular-nums;
        color: var(--_text2);
        margin-top: 2px;
      }
      .progress-track {
        flex: 1;
        height: 5px;
        border-radius: 3px;
        background: rgba(255,255,255,0.1);
        cursor: pointer;
        position: relative;
        overflow: hidden;
      }
      .mini-btn {
        width: 30px; height: 30px;
        color: var(--_text2);
        flex-shrink: 0;
      }
      .mini-btn ha-icon { --mdc-icon-size: 16px; }
      .mini-btn:hover { background: rgba(255,255,255,0.06); }
      .mini-btn.on { color: var(--_accent); }
      .progress-track:not(.no-seek):hover { height: 7px; }
      .progress-track.no-seek { cursor: default; opacity: 0.7; }
      .progress-fill {
        height: 100%;
        border-radius: 3px;
        background: linear-gradient(90deg, var(--_accent), var(--_accent-active));
        transition: width 0.3s linear;
        box-shadow: 0 0 8px rgba(74,158,255,0.3);
      }

      @media (max-width: 480px) {
        .content { padding: 20px 18px 18px; gap: 12px; }
        .track-title { font-size: 1.2rem; }
        .controls-row { flex-direction: column; align-items: flex-start; }
        .vol-slider { width: 80px; }
      }
    `;
  }
}

customElements.define("ytmc-player", YtmcPlayer);

/* ── Card editor for HA UI ── */
class YtmcPlayerEditor extends HTMLElement {
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
customElements.define("ytmc-player-editor", YtmcPlayerEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ytmc-player",
  name: "YouTube Music Player",
  description: "Now-playing card with album art, transport controls, volume, progress/seek, and multi-device group playback.",
  documentationURL: "https://github.com/Jerry0022/homeassistant-youtube-music-connector/blob/main/docs/components.md",
});
