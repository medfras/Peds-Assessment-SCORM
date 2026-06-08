/**
 * scorm.js — SCORM 1.2 wrapper for RescueTrails Station 1 pilot
 *
 * NOT loaded by the main app's index.html.
 * The SCORM branch index.html includes this file before app.js.
 *
 * Public API (on window.RescueTrails.scorm):
 *   init(config)                → Promise<ResumeState>
 *   submitNodeResult(nodeId, result) → Promise<AttemptSummary>
 *   getAttemptSummary()         → Promise<AttemptSummary>
 *   finish(summary)             → void
 *
 * Local dev adapter: when window.API (SCORM 1.2 API object) is not found,
 * falls back to sessionStorage so the full flow can be tested outside an LMS.
 *
 * cmi.suspend_data shape (compact mirror — never stores transcripts or AI output):
 * {
 *   "v": 3,
 *   "attempt": "<attempt_id>",
 *   "scores": { "drill_pat": 87, "drill_dev": 0, ... },
 *   "completed": { "drill_pat": true, "drill_dev": false, ... },
 *   "unlocks": { "scenarios": false, "map3": false },
 *   "status": "incomplete",
 *   "ce": { "complete": false, ... },
 *   "ui": { "location": "orientation" | "home" | "peds", "map": "map_0" | "pm1" | "pt1", "orientationComplete": true }
 * }
 */

(function () {
  "use strict";

  // ── Config ──────────────────────────────────────────────────────────────────

  let _backendBase = "";             // same origin; override via SCORM_CONFIG.backend_base
  const _SUSPEND_DATA_VERSION = 3;   // bumped: 4-map topology, 16 nodes (PM1/PT1/CPR split)
  const _ALL_NODES = [
    // Map 0 — drills (PAT + DEV required gates; GCS optional)
    "drill_pat", "drill_dev", "drill_gcs",
    // PM1 — Medical scenarios (any 2 of 4 satisfy SCORM pass requirement)
    "scen_asthma", "scen_croup", "scen_diabetes", "scen_seizure",
    // PT1 — Trauma scenarios (any 2 of 5 satisfy SCORM pass requirement)
    "scen_airway", "scen_anaph", "scen_bleeding", "scen_head", "scen_laceration",
    // Map 3 — CPR (optional for Moodle completion)
    "scen_cpr",
    // Optional games (telemetry/enrichment)
    "game_bls", "game_lung_sounds", "game_vitals",
  ];

  // ── Internal state ──────────────────────────────────────────────────────────

  let _api = null;          // SCORM 1.2 API object (or local dev adapter)
  let _attemptId = null;    // bound after init()
  let _token = null;        // JWT returned by /api/scorm/auth
  let _initialized = false;
  let _uiState = null;
  let _launchId = null;
  let _duplicateLaunchWarning = null;
  let _heartbeatTimer = null;
  let _launchClosed = false;

  // ── SCORM 1.2 API finder ────────────────────────────────────────────────────

  function _findScormApiInChain(win) {
    let attempts = 0;
    while (win && attempts <= 7) {
      try {
        if (win.API) return win.API;
        if (!win.parent || win.parent === win) break;
        win = win.parent;
      } catch (_) {
        break;
      }
      attempts += 1;
    }
    return null;
  }

  function _findScormApi(win) {
    return _findScormApiInChain(win) || _findScormApiInChain(win && win.opener);
  }

  function _makeLaunchId() {
    try {
      const bytes = new Uint8Array(16);
      window.crypto.getRandomValues(bytes);
      return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    } catch (_) {
      return `launch_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    }
  }

  function _emitDuplicateLaunchWarning(warning) {
    if (!warning) return;
    _duplicateLaunchWarning = warning;
    try {
      window.dispatchEvent(new CustomEvent("rt:scormDuplicateLaunch", { detail: warning }));
    } catch (_) {
      console.warn("[SCORM] Duplicate launch warning", warning);
    }
  }

  function isLmsLaunch() {
    return !!_findScormApi(window);
  }

  // ── Local dev adapter ───────────────────────────────────────────────────────
  // Mirrors the SCORM 1.2 API surface using sessionStorage so the flow works
  // outside an LMS during development and vertical-slice testing.

  const _LOCAL_DEV_STORAGE_KEY = "rescuetrails_scorm_dev";

  function _buildLocalDevAdapter() {
    const store = {};
    const _load = () => {
      try {
        return JSON.parse(sessionStorage.getItem(_LOCAL_DEV_STORAGE_KEY) || "{}");
      } catch (_) { return {}; }
    };
    const _save = (data) => {
      try {
        sessionStorage.setItem(_LOCAL_DEV_STORAGE_KEY, JSON.stringify(data));
      } catch (_) {}
    };

    Object.assign(store, _load());

    return {
      LMSInitialize: (_) => { console.info("[SCORM dev] LMSInitialize"); return "true"; },
      LMSGetValue:   (k) => { const v = store[k] || ""; console.debug("[SCORM dev] LMSGetValue", k, "→", v); return v; },
      LMSSetValue:   (k, v) => { store[k] = v; _save(store); console.debug("[SCORM dev] LMSSetValue", k, "=", v); return "true"; },
      LMSCommit:     (_) => { console.info("[SCORM dev] LMSCommit"); return "true"; },
      LMSFinish:     (_) => { console.info("[SCORM dev] LMSFinish"); return "true"; },
      LMSGetLastError: () => "0",
      LMSGetErrorString: (_) => "",
      LMSGetDiagnostic: (_) => "",
    };
  }

  // ── suspend_data helpers ────────────────────────────────────────────────────

  function _readSuspendData() {
    if (!_api) return null;
    const raw = _api.LMSGetValue("cmi.suspend_data");
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      // Accept current version only; older v1 data is discarded (node set changed)
      if (parsed && parsed.v === _SUSPEND_DATA_VERSION) return parsed;
    } catch (_) {}
    return null;
  }

  function _sanitizeUiState(ui) {
    if (!ui || typeof ui !== "object") return null;
    const location = ui.location === "home"
      ? "home"
      : ui.location === "peds" ? "peds" : ui.location === "orientation" ? "orientation" : "";
    if (!location) return null;
    const map = ["map_0", "pm1", "pt1"].includes(ui.map) ? ui.map : "map_0";
    const sanitized = { location, map };
    if (ui.orientationComplete === true) sanitized.orientationComplete = true;
    return sanitized;
  }

  function _writeSuspendData(summary) {
    if (!_api) return;
    const scores = {};
    _ALL_NODES.forEach((n) => { scores[n] = summary.node_scores ? (summary.node_scores[n] || 0) : 0; });
    const completed = {};
    _ALL_NODES.forEach((n) => { completed[n] = summary.node_completed ? !!summary.node_completed[n] : false; });
    const cc = summary.peds_ce_challenge || {};
    const ccId = cc.id || "pfd_station1_scorm_pass";
    const mirror = {
      v:        _SUSPEND_DATA_VERSION,
      attempt:  _attemptId,
      scores,
      completed,
      unlocks:  summary.unlocks || { scenarios: false, map3: false },
      status:   summary.lesson_status || "incomplete",
      ce: {
        id:                  ccId,
        title:               ccId === "pfd_station1_scorm_pass" ? "Pediatric Patient Assessment" : (cc.title || "Pediatric Patient Assessment"),
        complete:            !!cc.complete,
        ce_seconds:          cc.ce_seconds || 0,
        training_time_done:   !!cc.training_time_done,
        xp:                  cc.xp || 0,
        xp_required:         ccId === "pfd_station1_scorm_pass" ? 1200 : (cc.xp_required || 1200),
        xp_ok:               !!cc.xp_ok,
        pm1_completed:       cc.pm1_completed || 0,
        pm1_required:        cc.pm1_required  || 2,
        pt1_completed:       cc.pt1_completed || 0,
        pt1_required:        cc.pt1_required  || 2,
        cpr_done:            !!cc.cpr_done,
        opt_games_completed: cc.optional_games_completed || 0,
        opt_games_required:  cc.optional_games_required  || 2,
      },
    };
    if (_uiState) mirror.ui = _uiState;
    _api.LMSSetValue("cmi.suspend_data", JSON.stringify(mirror));
    const ceComplete = !!(summary.peds_ce_challenge && summary.peds_ce_challenge.complete);
    if (ceComplete && summary.final_score !== null && summary.final_score !== undefined) {
      _api.LMSSetValue("cmi.core.score.raw", String(summary.final_score));
      _api.LMSSetValue("cmi.core.score.min", "0");
      _api.LMSSetValue("cmi.core.score.max", "100");
    }
    _api.LMSSetValue("cmi.core.lesson_status", ceComplete ? "passed" : "incomplete");
    _api.LMSCommit("");
  }

  function _writeUiState(ui) {
    if (!_api) return;
    _uiState = _sanitizeUiState(ui);
    const mirror = _readSuspendData() || { v: _SUSPEND_DATA_VERSION };
    mirror.v = _SUSPEND_DATA_VERSION;
    if (_attemptId) mirror.attempt = _attemptId;
    if (_uiState) mirror.ui = _uiState;
    _api.LMSSetValue("cmi.suspend_data", JSON.stringify(mirror));
    _api.LMSCommit("");
  }

  // ── Backend fetch helper ────────────────────────────────────────────────────

  async function _apiFetch(path, opts = {}) {
    const headers = { "Content-Type": "application/json" };
    if (_token) headers["Authorization"] = `Bearer ${_token}`;
    const resp = await fetch(_backendBase + path, {
      credentials: "omit",
      ...opts,
      headers: { ...headers, ...(opts.headers || {}) },
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      const msg = body.detail || `HTTP ${resp.status}`;
      throw new Error(`SCORM API error ${resp.status}: ${msg}`);
    }
    return resp.json();
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  /**
   * init(config) — call once at page load.
   *
   * config: {
   *   backend_base:      string,   (absolute hosted backend URL; optional for same-origin/local dev)
   *   lms_student_id:   string,
   *   lms_student_name: string,   (from cmi.core.student_name)
   *   module_id:        string,   (e.g. "pfd_station1")
   *   integration_key:  string,   (non-secret module identifier)
   * }
   *
   * Returns the resume_state from the backend so the caller can restore map state.
   */
  async function init(config = {}) {
    _backendBase = (config.backend_base || config.backendBase || "").replace(/\/+$/, "");
    _launchId = _makeLaunchId();

    // Locate SCORM API or fall back to local dev adapter
    _api = _findScormApi(window) || _buildLocalDevAdapter();
    _api.LMSInitialize("");
    const priorSuspendData = _readSuspendData();
    _uiState = _sanitizeUiState(priorSuspendData && priorSuspendData.ui);

    // Read student identity from LMS if not passed explicitly
    const lms_student_id   = config.lms_student_id   || _api.LMSGetValue("cmi.core.student_id")   || "dev_student";
    const lms_student_name = config.lms_student_name  || _api.LMSGetValue("cmi.core.student_name") || "";

    // Authenticate with the backend
    const authResp = await _apiFetch("/api/scorm/auth", {
      method: "POST",
      body: JSON.stringify({
        lms_student_id,
        lms_student_name,
        module_id:       config.module_id || "pfd_station1",
        integration_key: config.integration_key,
        launch_id:       _launchId,
      }),
    });

    _token     = authResp.access_token;
    _attemptId = authResp.scorm_attempt_id;
    _initialized = true;
    if (authResp.launch_warning) _emitDuplicateLaunchWarning(authResp.launch_warning);
    _startLaunchHeartbeat();

    // Write any existing backend state into suspend_data for consistency
    _writeSuspendData({
      node_scores:   authResp.resume_state.scores,
      node_completed: authResp.resume_state.completed,
      unlocks:       authResp.resume_state.unlocks,
      lesson_status: authResp.resume_state.status,
      peds_ce_challenge: authResp.resume_state.peds_ce_challenge,
    });

    return authResp.resume_state;
  }

  function _startLaunchHeartbeat() {
    if (_heartbeatTimer) clearInterval(_heartbeatTimer);
    if (!_attemptId || !_launchId) return;
    _heartbeatTimer = setInterval(async () => {
      try {
        const resp = await _apiFetch(`/api/scorm/attempts/${encodeURIComponent(_attemptId)}/launch-heartbeat`, {
          method: "POST",
          body: JSON.stringify({ launch_id: _launchId }),
        });
        if (resp && resp.active === false && resp.warning) {
          _emitDuplicateLaunchWarning(resp.warning);
        }
      } catch (err) {
        console.warn("[SCORM] Launch heartbeat failed", err);
      }
    }, 60 * 1000);
  }

  function _stopLaunchHeartbeat() {
    if (_heartbeatTimer) {
      clearInterval(_heartbeatTimer);
      _heartbeatTimer = null;
    }
  }

  function _notifyLaunchClosed() {
    if (_launchClosed || !_attemptId || !_launchId || !_token) return;
    _launchClosed = true;
    _stopLaunchHeartbeat();
    const url = `${_backendBase}/api/scorm/attempts/${encodeURIComponent(_attemptId)}/launch-close`;
    const body = JSON.stringify({ launch_id: _launchId });
    try {
      if (navigator.sendBeacon) {
        const blob = new Blob([body], { type: "application/json" });
        if (navigator.sendBeacon(`${url}?token=${encodeURIComponent(_token)}`, blob)) return;
      }
    } catch (_) {}
    try {
      fetch(url, {
        method: "POST",
        credentials: "omit",
        keepalive: true,
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${_token}`,
        },
        body,
      }).catch(() => {});
    } catch (_) {}
  }

  window.addEventListener("pagehide", _notifyLaunchClosed);
  window.addEventListener("beforeunload", _notifyLaunchClosed);

  /**
   * submitNodeResult(nodeId, result) — submit a drill or scenario score.
   *
   * result: {
   *   activity_type: "minigame" | "scenario",
   *   score:         number 0–100,
   *   completed:     boolean,
   *   passed:        boolean   (optional),
   *   mistake_tags:  string[]  (optional),
   * }
   *
   * Returns the updated AttemptSummary and writes cmi.suspend_data.
   */
  async function submitNodeResult(nodeId, result) {
    if (!_initialized) throw new Error("RescueTrails.scorm.init() must be called first.");
    const summary = await _apiFetch(
      `/api/scorm/attempts/${_attemptId}/nodes/${nodeId}/result`,
      { method: "POST", body: JSON.stringify(result) },
    );
    _writeSuspendData(summary);
    return summary;
  }

  /**
   * getAttemptSummary() — fetch the current attempt summary from the backend.
   * Returns AttemptSummary and refreshes cmi.suspend_data.
   */
  async function getAttemptSummary() {
    if (!_initialized) throw new Error("RescueTrails.scorm.init() must be called first.");
    const summary = await _apiFetch(`/api/scorm/attempts/${_attemptId}/summary`);
    _writeSuspendData(summary);
    return summary;
  }

  /**
   * finish(summary) — write final grade and lesson_status to the LMS, then LMSFinish.
   * Writes "passed" and cmi.core.score.raw only when peds_ce_challenge.complete is true.
   * Writes "incomplete" (never "failed") while the learner is still in progress.
   */
  function finish(summary) {
    if (!_api) return;
    _notifyLaunchClosed();
    if (summary) {
      const ceComplete = !!(summary.peds_ce_challenge && summary.peds_ce_challenge.complete);
      if (ceComplete && summary.final_score !== null && summary.final_score !== undefined) {
        _api.LMSSetValue("cmi.core.score.raw", String(summary.final_score));
        _api.LMSSetValue("cmi.core.score.min", "0");
        _api.LMSSetValue("cmi.core.score.max", "100");
      }
      _api.LMSSetValue("cmi.core.lesson_status", ceComplete ? "passed" : "incomplete");
      _api.LMSCommit("");
    }
    _api.LMSFinish("");
  }

  function getAccessToken() {
    return _token;
  }

  function getAttemptId() {
    return _attemptId;
  }

  function getDuplicateLaunchWarning() {
    return _duplicateLaunchWarning;
  }

  function getUiState() {
    return _uiState;
  }

  function setUiState(ui) {
    _writeUiState(ui);
  }

  // ── Export ──────────────────────────────────────────────────────────────────

  window.RescueTrails = window.RescueTrails || {};
  window.RescueTrails.scorm = {
    isLmsLaunch,
    init,
    submitNodeResult,
    getAttemptSummary,
    finish,
    getAccessToken,
    getAttemptId,
    getDuplicateLaunchWarning,
    getUiState,
    setUiState,
  };

})();
