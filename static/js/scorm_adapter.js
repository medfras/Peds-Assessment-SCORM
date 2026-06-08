/**
 * scorm_adapter.js — thin frontend facade between app.js and scorm.js.
 *
 * app.js depends on this stable adapter surface instead of coupling directly
 * to RescueTrails.scorm. The adapter remains intentionally tiny: SCORM runtime
 * details stay in scorm.js, while app.js only asks whether a launch is active
 * and retrieves the bearer token needed for normal API calls.
 */
(function () {
  "use strict";

  function _runtime() {
    return window.RescueTrails && window.RescueTrails.scorm;
  }

  function isLaunch() {
    const runtime = _runtime();
    return !!(runtime && (window.SCORM_CONFIG || runtime.isLmsLaunch?.()));
  }

  async function init() {
    const runtime = _runtime();
    if (!runtime) throw new Error("SCORM runtime is not loaded.");
    return runtime.init(window.SCORM_CONFIG || {});
  }

  function getAccessToken() {
    return _runtime()?.getAccessToken?.() || "";
  }

  function getAttemptId() {
    return _runtime()?.getAttemptId?.() || "";
  }

  function getDuplicateLaunchWarning() {
    return _runtime()?.getDuplicateLaunchWarning?.() || null;
  }

  async function submitNodeResult(nodeId, result) {
    const runtime = _runtime();
    if (!runtime) throw new Error("SCORM runtime is not loaded.");
    return runtime.submitNodeResult(nodeId, result);
  }

  async function getAttemptSummary() {
    const runtime = _runtime();
    if (!runtime) throw new Error("SCORM runtime is not loaded.");
    return runtime.getAttemptSummary();
  }

  function finish(summary) {
    const runtime = _runtime();
    if (!runtime) return;
    runtime.finish(summary);
  }

  function getUiState() {
    return _runtime()?.getUiState?.() || null;
  }

  function setUiState(ui) {
    const runtime = _runtime();
    if (!runtime) return;
    runtime.setUiState?.(ui);
  }

  window.RescueTrails = window.RescueTrails || {};
  window.RescueTrails.scormAdapter = {
    isLaunch,
    init,
    getAccessToken,
    getAttemptId,
    getDuplicateLaunchWarning,
    submitNodeResult,
    getAttemptSummary,
    finish,
    getUiState,
    setUiState,
  };
})();
