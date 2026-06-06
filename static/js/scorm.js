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
 *   "ce": { "complete": false, ... }
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
    // PM1 — Medical scenarios (any 2 of 4 satisfy CE requirement)
    "scen_asthma", "scen_croup", "scen_diabetes", "scen_seizure",
    // PT1 — Trauma scenarios (any 2 of 5 satisfy CE requirement)
    "scen_airway", "scen_anaph", "scen_bleeding", "scen_head", "scen_laceration",
    // Map 3 — CPR (required)
    "scen_cpr",
    // Optional games (any 2 of 3 satisfy CE requirement)
    "game_bls", "game_lung_sounds", "game_vitals",
  ];

  // ── Internal state ──────────────────────────────────────────────────────────

  let _api = null;          // SCORM 1.2 API object (or local dev adapter)
  let _attemptId = null;    // bound after init()
  let _token = null;        // JWT returned by /api/scorm/auth
  let _initialized = false;

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

  function _writeSuspendData(summary) {
    if (!_api) return;
    const scores = {};
    _ALL_NODES.forEach((n) => { scores[n] = summary.node_scores ? (summary.node_scores[n] || 0) : 0; });
    const completed = {};
    _ALL_NODES.forEach((n) => { completed[n] = summary.node_completed ? !!summary.node_completed[n] : false; });
    const cc = summary.peds_ce_challenge || {};
    const mirror = {
      v:        _SUSPEND_DATA_VERSION,
      attempt:  _attemptId,
      scores,
      completed,
      unlocks:  summary.unlocks || { scenarios: false, map3: false },
      status:   summary.lesson_status || "incomplete",
      ce: {
        complete:            !!cc.complete,
        ce_seconds:          cc.ce_seconds || 0,
        pm1_completed:       cc.pm1_completed || 0,
        pm1_required:        cc.pm1_required  || 2,
        pt1_completed:       cc.pt1_completed || 0,
        pt1_required:        cc.pt1_required  || 2,
        cpr_done:            !!cc.cpr_done,
        opt_games_completed: cc.optional_games_completed || 0,
        opt_games_required:  cc.optional_games_required  || 2,
      },
    };
    _api.LMSSetValue("cmi.suspend_data", JSON.stringify(mirror));
    _api.LMSCommit("");
  }

  // ── Backend fetch helper ────────────────────────────────────────────────────

  async function _apiFetch(path, opts = {}) {
    const headers = { "Content-Type": "application/json" };
    if (_token) headers["Authorization"] = `Bearer ${_token}`;
    const resp = await fetch(_backendBase + path, {
      credentials: "include",
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

    // Locate SCORM API or fall back to local dev adapter
    _api = _findScormApi(window) || _buildLocalDevAdapter();
    _api.LMSInitialize("");

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
      }),
    });

    _token     = authResp.access_token;
    _attemptId = authResp.scorm_attempt_id;
    _initialized = true;

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
    if (summary) {
      const ceComplete = !!(summary.peds_ce_challenge && summary.peds_ce_challenge.complete);
      if (ceComplete && summary.final_score !== null && summary.final_score !== undefined) {
        _api.LMSSetValue("cmi.core.score.raw", String(summary.final_score));
      }
      _api.LMSSetValue("cmi.core.lesson_status", ceComplete ? "passed" : "incomplete");
    }
    _api.LMSFinish("");
  }

  // ── Export ──────────────────────────────────────────────────────────────────

  window.RescueTrails = window.RescueTrails || {};
  window.RescueTrails.scorm = { init, submitNodeResult, getAttemptSummary, finish };

})();
