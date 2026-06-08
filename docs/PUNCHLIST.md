# Punchlist

**Purpose:** Track known issues, technical debt, compliance gaps, and planned enhancements in one place.  
**Usage:** Add items under the appropriate severity section. Keep entries short, actionable, and easy to scan.

---

## How To Use

- Put production risks, compliance gaps, regressions, and blocking defects here.
- Keep feature ideas and polish work here only if they are concrete enough to act on.
- Link to the relevant file, doc, PR, issue, or test when possible.
- Move completed items out rather than leaving stale resolved entries in place.
- Reassess severity when impact, scope, or urgency changes.

Suggested item format:

```md
- [ ] Short title
  - Type: Bug | Enhancement | Tech Debt | Security | Compliance | Performance
  - Area: Backend | Frontend | AI | Data | Infra | Docs
  - Summary: One or two sentences.
  - Impact: What breaks, regresses, or remains risky.
  - Next step: Concrete action to take.
  - References: [file](/abs/path) or doc/PR/endpoint/test name
```

If you want a lighter format, this is also acceptable:

```md
- [ ] Short title — one-line summary and next action.
```

---

## Severity Definitions

### Critical

Use for issues that:

- block production deployment
- create severe security/privacy exposure
- break core clinical/scoring/tenant integrity
- cause data corruption or loss
- make a core workflow unusable for most users

Target response: immediate triage and fix planning.

### High

Use for issues that:

- significantly affect correctness, security, or reliability
- break an important workflow with a workaround or partial recovery
- create serious maintainability or migration risk if left unresolved
- materially weaken production readiness

Target response: prioritize in the next active work cycle.

### Medium

Use for issues that:

- affect non-core workflows
- create noticeable UX, performance, or maintainability problems
- represent important but non-blocking standards/compliance gaps
- should be fixed soon but are not emergency work

Target response: schedule into normal planning.

### Low

Use for issues that:

- are real but low-impact
- affect edge cases, minor polish, or internal ergonomics
- are worth doing when nearby work touches the same area

Target response: opportunistic or backlog work.

### Trivial

Use for issues that:

- are cosmetic
- are wording/docs cleanup
- are tiny developer-experience improvements
- have very low risk and low impact

Target response: batch with cleanup passes.

---

## Critical

- [ ] No items currently recorded.

## High

- [ ] Pilot release gate — disable pediatric dev unlock before real learner cohort
  - Type: Release Gate
  - Area: Frontend / Progression
  - Summary: `PEDS_MAP_DEV_UNLOCKED` is currently enabled, which intentionally unlocks pediatric map navigation for testing.
  - Impact: Useful while manually validating every pilot scenario, but it would invalidate progression/unlock behavior for a real pilot cohort if left enabled.
  - Next step: Before inviting learners, set the pediatric map to normal progression mode and run a quick orientation → Pediatric Park → PM1/PT1 unlock smoke test.
  - References: [`static/js/app.js`](static/js/app.js) (`PEDS_MAP_DEV_UNLOCKED`)

- [ ] `_hideNavigationOverlays()` scope is too broad
  - Type: Tech Debt
  - Area: Frontend
  - Summary: `showScreen()` calls `_hideNavigationOverlays()` which hides ALL `[id^='modal-']` elements. Any screen transition silently closes any open modal, regardless of whether it is related to the transition.
  - Impact: Future features that open a modal and then trigger a screen transition (e.g., a jurisdiction warning mid-flow, or a loading overlay) will lose the modal with no error. Already produced one "went back to map" class of bug during orientation/scenario-launch work.
  - Next step: Replace the blanket `[id^='modal-']` selector with an explicit `_TRANSIENT_MODALS` set and a `_PRESERVE_MODALS` allowlist (similar to `_hideScreenTransitionModals`). Modals that should survive screen transitions (e.g. `modal-jurisdiction-warning`, any future loading overlay) must be on the preserve list.
  - References: [`static/js/app.js:4715`](static/js/app.js)

- [ ] Parallel debrief/result surfaces with overlapping responsibilities
  - Type: Tech Debt
  - Area: Frontend
  - Summary: Four surfaces handle post-session feedback: `modal-last-results`, `modal-history-debrief`, `modal-debrief`, and `screen-debrief-lexi`. They share overlapping data shapes but have separate styling, back-navigation rules, and button wiring. Each was added incrementally and the contracts between them are implicit.
  - Impact: Inconsistent feedback display; divergent CSS theming between surfaces (currently papered over by 80+ lines of `!important` overrides); recurring bugs when one surface is updated but the others are not. New debrief features must be implemented in multiple places.
  - Next step: Audit which surfaces are still in active use and which are zombie paths. Consolidate into two canonical surfaces: one in-scenario (Lexi screen) and one history/replay (last-results modal). Remove or tombstone the rest. Align data shape and theme before adding any new debrief UI.
  - References: [`static/js/app.js:14750`](static/js/app.js), [`docs/PUNCHLIST.md`](docs/PUNCHLIST.md)

- [ ] Orientation-gated navigation must be source-aware
  - Type: Bug / Release Gate
  - Area: Frontend / Navigation
  - Summary: SCORM pilot testing found that opening History from an incomplete Station 1 orientation and pressing Back routed to the production Home screen. The immediate SCORM package fix made History source-aware, but the broader production pattern remains: screens and modals opened from an orientation-gated map can call `buildMenu()` / `showScreen("menu")` or launch off-orientation content without checking whether orientation is complete.
  - Impact: Learners can accidentally bypass required onboarding/orientation flows, and future modal/screen additions can reintroduce the same bug unless return targets are centralized.
  - Findings to audit:
    - `History`: fixed in SCORM package; back returns to orientation while incomplete.
    - `Notebook`: opened from category sidebar; Back returns to category, but empty-state/start shortcuts can still route to Home.
    - `Training Center`: opened from category sidebar and can launch drills before orientation is complete unless gated.
    - `Daily Trivia` / Lexi challenges and repeatable Challenges: can be opened from the category sidebar and may launch off-orientation content.
    - `Leaderboard`, `Badges`, and simple close-only modals are low risk if close only hides the modal, but should be classified explicitly.
    - Category Home button must remain hidden/disabled while orientation is incomplete.
  - Next step: Add a shared `returnTarget` / orientation-gate helper for all screen-opening surfaces. While `orientation_completed_at` is false, any Back/Home/Start/Close path from an orientation-origin surface must return to `showCategoryScreen("station_1")` or remain in-place; off-orientation launch buttons should be hidden/disabled.
  - References: [`static/js/app.js`](static/js/app.js), [`PEDS_ASSESSMENT/07_PILOT_READINESS_CHECKLIST.md`](PEDS_ASSESSMENT/07_PILOT_READINESS_CHECKLIST.md)

- [ ] Backport SCORM pilot deterministic action-routing fixes
  - Type: Bug / Backport
  - Area: Frontend / Scenario Runtime / Scoring Evidence
  - Summary: MoodleCloud pilot testing exposed two deterministic routing gaps that should be carried into production: pain-history questions could be misclassified as AVPU/LOC because the LOC detector matched standalone `pain`, and procedure menu actions could fail to record a treatment unless the learner phrased the same action through Alex/chat.
  - Impact: Learners can get the wrong authored finding ("Level of Consciousness") when asking about pain, and treatment evidence can be missing from notes/scoring even though the learner used an explicit action control.
  - Next step: Backport the SCORM fixes and tests: narrow `_userRequestedAvpu()` to AVPU/LOC language only; route action-menu/body-map procedure payloads through scenario intervention matching and `applyInterventionAndRecord()` before chat fallback; confirm dressing/pressure actions credit the right intervention IDs in soft-tissue and burn scenarios.
  - References: [`static/js/app.js`](static/js/app.js), `tests/test_patient_disclosure_guardrails.py`, SCORM commits `7d5ba96`, `791f729`

- [ ] Backport scenario progression and persistence hardening from SCORM pilot
  - Type: Bug / Release Gate
  - Area: Backend / Frontend / Progression
  - Summary: Pilot testing found progress-reset and premature-clear risks: Station 1 could display cleared when not all requirements were complete, Pediatric Community Response could unlock before Station 1 completion, orientation/node completion could disappear after logout/relogin, and local UI flags could make wrap-up nodes appear complete or unlocked on a fresh attempt.
  - Impact: Learners may bypass required work or lose earned progress, which undermines course completion validity and instructor trust.
  - Next step: Make backend state the only authority for Station 1 complete, node complete, map unlocks, and challenge completion. Audit logout/relogin, browser refresh, sidebar navigation, history/back navigation, and repeated attempts for all orientation, Map 0, PM1, PT1, CPR, optional games, and challenge nodes.
  - References: [`static/js/app.js`](static/js/app.js), [`app/routers/scorm.py`](app/routers/scorm.py), [`PEDS_ASSESSMENT/07_PILOT_READINESS_CHECKLIST.md`](PEDS_ASSESSMENT/07_PILOT_READINESS_CHECKLIST.md)

- [ ] Audit treatment-response vitals trending across all scenarios
  - Type: Bug / Clinical Correctness
  - Area: Scenario Runtime / Vitals Engine
  - Summary: In the diabetic emergency scenario, oral glucose improved GCS but initially did not trend BGL until the SCORM branch fix. Similar post-intervention vitals paths may be silently incomplete in other scenarios.
  - Impact: Learners may not see physiologic response to correct treatment, and debrief/scoring evidence may not reflect the authored clinical trajectory.
  - Next step: Backport the diabetic treatment-response fix, then audit all scenarios with post-treatment profiles (`post_treatment`, intervention effects, CPR/ROSC, O2/medication response, reassessment prompts) to ensure affected vitals update deterministically after the required intervention.
  - References: [`app/scenarios/pediatric`](app/scenarios/pediatric), [`static/js/app.js`](static/js/app.js), `tests/test_scoring_service.py`

- [x] Restrict overly permissive CORS policy — **Resolved (2026-05-12).** Allowlist-based CORS with `allow_credentials=True`; `settings.allowed_origins` loads the explicit origin list; browser preflight verified. Punchlist entry was not updated when the item was closed in `docs/SAAS_HARDENING_PLAN.md` (S-01).

- [ ] SCORM pilot — result adapter wiring (branch gate blocker)
  - Type: Enhancement / Release Gate
  - Area: Frontend
  - Summary: The SCORM backend (auth endpoint, attempt model, attempt summary, `cmi.suspend_data` mirror, `finish()` LMS reporting) is complete. The one remaining code gap is the frontend result adapter: drills and scenarios must call `RescueTrails.scorm.submitNodeResult(nodeId, result)` on completion so the backend attempt record is updated and the suspend data mirror is written. Until this is wired, the PAT vertical slice gate cannot be verified and the branch is premature.
  - Remaining work (in `app.js`, SCORM branch only):
    - On drill completion: call `RescueTrails.scorm.submitNodeResult(nodeId, { activity_type: "minigame", score, completed, passed, mistake_tags })`
    - On scenario debrief close: call `RescueTrails.scorm.submitNodeResult(nodeId, { activity_type: "scenario", session_id, score, completed, passed })`
    - On module exit / LMS finish: call `RescueTrails.scorm.finish(summary)` with the latest attempt summary
  - Pre-branch gate items still open:
    - `peds_febrile_seizure_01` live validation (automated: PASS — 1705 tests, gold standard adjudication, tier2 matchers, disclosure guardrails, static assets all verified; remaining: live browser session to confirm UI rendering, lung sound challenge audio, chat personas, and debrief generation)
    - PAT SCORM vertical slice end-to-end (launch → auth → drill result → suspend data → map unlock)
  - Architecture complete (do not re-open):
    - 4-map 16-node topology (`unlocks.scenarios`, `unlocks.map3`), v3 suspend data
    - CE challenge gate (`_peds_ce_challenge()`), `finish()` correctness (passes `"incomplete"` not `"failed"`)
    - `scorm.js` local dev adapter, `_writeSuspendData()`, `submitNodeResult()` API
  - References: `PEDS_ASSESSMENT/03_SCORM_ARCHITECTURE.md`, `PEDS_ASSESSMENT/07_PILOT_READINESS_CHECKLIST.md`, `static/js/scorm.js`

- [ ] Pilot anomaly logging — NLP-miss vs. learner-error distinction
  - Type: Observability / Pilot Gate
  - Area: Scoring | Debrief | Pilot Telemetry
  - Summary: The debrief surfaces `missed_items` (what wasn't done), but does not distinguish between two distinct causes: (1) learner skipped the action, (2) learner attempted the action with a phrasing variant that the tier 2 matcher didn't catch. In pilot data these look identical, which means NLP misses will be misattributed as learner errors. Before the pilot produces actionable telemetry, confirm whether the scoring output carries enough signal to separate these cases — or add lightweight instrumentation.
  - Confirm before pilot launch:
    - Does the structured scoring output (`checklist_states`, `evidence_packet`) include any record of near-miss or unmatched text for checklist items that ended `"missed"`?
    - If not: add a lightweight `unmatched_attempts` field to the evidence packet — a list of learner transcript lines that were evaluated against tier 2 patterns and produced no match. This does not require showing it in the debrief UI; it only needs to be queryable server-side.
  - Pilot monitoring: after each run, look for patterns where learners typed an intervention but received no credit. These are NLP gaps, not rubric gaps, and should drive tier 2 pattern expansion rather than rubric changes.
  - References: `docs/SCORING_ENGINE_ARCHITECTURE.md`, `docs/SCORING_HARDENING_ROADMAP.md`, `PEDS_ASSESSMENT/07_PILOT_READINESS_CHECKLIST.md`

- [x] Review rate-limiting coverage on public state-mutating endpoints — **Resolved (2026-04-24; Lexi limit tightened 2026-05-07).** Added `@limiter.limit` + `request: Request` to all AI-calling and session-creation endpoints: `POST /api/register` and `POST /api/token` (IP-keyed, `rate_limit_auth/min`), `POST /api/sessions` (`rate_limit_session_start/min`), `POST /api/lexi` (`rate_limit_lexi/min`), `POST /api/sessions/{id}/interventions` (`rate_limit_session_write/min`), `POST /api/sessions/{id}/findings` (`rate_limit_session_write*2/min`), `POST /api/sessions/{id}/drill-debrief` (`rate_limit_debrief/min`), and `POST /api/sessions/{id}/narrative/skip` (`rate_limit_debrief/min`). submit_narrative was already limited. Endpoints explicitly exempt (once-per-session guards, no LLM): scene_entry, treatment, DMIST submission — exemptions documented inline. Three new config fields added to `app/config.py`: `rate_limit_auth`, `rate_limit_session_start`, `rate_limit_session_write`. All 138 tests pass.

- [x] Review whether debrief regex fallback is still acceptable under structured-output standards — **Resolved (2026-04-24).** Decision: keep Layer 1 (in `_extract_required_debrief_subscores`) as a legitimate resilience measure for API-level JSON mode failures (HTTP 400 from model); added `_log.warning(...)` so regex recovery is visible in production logs. Removed Layer 2 duplicate regex fallback from both route handlers in `main.py` — it was dead code since `_extract_required_debrief_subscores` already guarantees all required keys or raises `ValueError` (→ 503). The pipeline is now: JSON mode → plain text fallback on HTTP 400 → regex recovery with warning → `ValueError` hard fail if still missing.

- [x] Review deployment config hardening for public SaaS readiness — **Resolved (2026-04-24).** Three validators added to `app/config.py`: (1) `app_secret_key` in production now also requires minimum 32 chars (previously only rejected "changeme"); (2) `database_url` in production hard-fails if the URL contains "changeme"; (3) cross-field `model_validator` rejects `superuser_username` without `superuser_password` in all environments, and rejects weak superuser passwords in production. Also: migrated `class Config` → `model_config = SettingsConfigDict(...)` (pydantic v2 pattern), added `extra = "ignore"` to absorb docker-compose .env vars like `POSTGRES_USER` that are not Settings fields (was a latent startup failure in local dev). `_log_startup_config()` added to lifespan startup — logs `WARNING` with issue list when any setting is weak, in all environments, so operators see misconfigs before they reach production. 13 new tests in `tests/test_config_hardening.py`. All 151 tests pass.

- [x] Design protocol-context resolution before serious multi-agency scenario expansion — **Resolved.** Explicit decision record written to `docs/AI_ARCHITECTURE.md` Section 5 (2026-04-22). Status: single-jurisdiction (PFD/Michigan) confirmed. Decision is review-gated with named triggers. Author constraints documented. Multi-tenant resolver deferred until a real second-agency need fires.

- [x] Design a scalable rubric/template system for scenario grading consistency — **Resolved.** Taxonomy design pass completed (2026-04-22). Base template `ems_standard_v1` created at `docs/rubric_templates/ems_standard_v1.md` with copy-ready JSON scaffolds for all 5 scoring dimensions and all 4 provider levels. Taxonomy section added to `SCENARIO_DESIGN_EMS.md` Section 15 documenting what is fixed vs. scenario-authored, including an explicit "do not template" list to prevent flattening clinically meaningful nuance. Fixed scoring weights (clinical_performance 40, narrative 20, scope_adherence 20, dmist 10, professionalism 10) are encoded in the template and must never be changed in individual scenarios. New scenario authors start from the template scaffold.

- [x] Reduce exact-string and free-text coupling in scenario authoring/runtime linking — **Resolved.** Vocabulary registry created at `app/scenarios/vocabulary.py` with stable IDs for all interventions, rubric dimensions, and out-of-scope categories. Load-time validation wired into `load_scenario()`. `requires_intervention_id` replaces deprecated `requires_treatment_label`. All 11 existing scenarios migrated: `out_of_scope_bls` arrays converted from free-text to vocabulary IDs (2026-04-22), `requires_treatment_label` removed from both scenarios that carried it, `_schema` added to the 3 scenarios missing it, `rubric_template` provenance added to all 11, and validation now errors on unregistered `out_of_scope_bls` IDs (2026-04-22).

## Medium

- [ ] Default `pytest` collects provider smoke script
  - Type: Tech Debt
  - Area: Tests / Tooling
  - Summary: Running bare `pytest` attempts to collect `scripts/test_gemini_tts.py`, which imports optional Google Cloud TTS dependencies not installed in the normal app/test environment.
  - Impact: `venv/bin/python -m pytest tests -q` passes, but the default command exits during collection. This can confuse pilot-readiness checks or future CI setup.
  - Next step: Rename the script so pytest does not collect it, move it under a non-test filename, or add pytest collection config that limits automated tests to `tests/`.
  - References: [`scripts/test_gemini_tts.py`](scripts/test_gemini_tts.py), [`pytest.ini`](pytest.ini)

- [ ] Pilot live-validation checklist for each shipped scenario
  - Type: QA / Pilot Readiness
  - Area: Scenario Runtime
  - Summary: Automated tests cover contracts, disclosure guardrails, tier2 patterns, adjudication fixtures, maps, drills, and notebook/challenge flows, but each pilot scenario still needs a live browser pass for rendering, persona routing, audio/media, debrief generation, and learner-facing feedback quality.
  - Impact: Not a code blocker while you are actively testing, but live-only issues can still appear after automated coverage passes.
  - Next step: Track one row per pilot scenario with: map launch, image/media render, vitals/exam/history response, treatment path, impression challenge, debrief, notebook/ref updates, and challenge progress.
  - References: [`app/scenarios/pediatric`](app/scenarios/pediatric), [`static/js/app.js`](static/js/app.js), [`PEDS_ASSESSMENT/07_PILOT_READINESS_CHECKLIST.md`](PEDS_ASSESSMENT/07_PILOT_READINESS_CHECKLIST.md)

- [ ] Backport SCORM pilot UI and learner-experience fixes
  - Type: Bug / UX / Backport
  - Area: Frontend / Maps / Scenario Runtime
  - Summary: SCORM package testing exposed several production-app polish/regression fixes that are not SCORM-specific.
  - Findings to backport or verify:
    - Scenario desktop layout: full-width desktop/new-window sessions must not collapse into the mobile layout; quick action buttons, chat input, Lexi controls, and turnover controls must stay visible at common laptop sizes.
    - Scenario arrival image preload: scene/patient presentation image should preload before or during launch to avoid a blank/slow-loading opening moment.
    - Map fog/cloud overlay: remove or gate fog-of-war overlay if it obscures learner map art or conflicts with the current production design.
    - Leaderboard modal: use an opaque, challenge-modal-like surface so text is readable over map art.
    - Active Challenges progress: requirement rows may count correctly while overall progress still shows `0%`; progress percent must aggregate visible requirement state.
    - Pediatric Doorway Dash: remove empty image placeholders and vertically center text when no image is available.
    - Home/background assets: missing Home or orientation images should be caught by build/test checks before release.
    - TTS persona QA: verify deployed voice mapping for male/female patients and partners, especially Jake/Leo-style pediatric orientation and trauma scenes.
  - Impact: These issues do not all block scoring, but they can make the learner experience look broken or make a scenario effectively unusable.
  - Next step: Create focused browser checks or screenshot tests for each finding, then backport the SCORM fixes to the production branch where the same code paths exist.
  - References: [`static/js/app.js`](static/js/app.js), [`static/css/style.css`](static/css/style.css), [`PEDS_ASSESSMENT/07_PILOT_READINESS_CHECKLIST.md`](PEDS_ASSESSMENT/07_PILOT_READINESS_CHECKLIST.md)

- [ ] Backport SCORM pilot learner-history and leaderboard identity checks
  - Type: Bug / UX / Backport
  - Area: Frontend / Backend / Identity
  - Summary: The pilot keeps learners out of the normal login flow while still allowing history and leaderboard access through the Moodle-backed account. Production should preserve the same invariant for any external-identity or SSO launch path.
  - Impact: History/back navigation can route to the wrong screen, leaderboard rows can show a placeholder or wrong name, and account/signout links can appear in contexts where the learner cannot use them.
  - Next step: Audit History, Last Results, Debrief Review, Leaderboard, My Progress, sidebar items, Account Settings, and Sign Out under SCORM/SSO-style auth. Ensure learner name comes from the authoritative profile/launch identity and that unavailable account-management actions are hidden or re-routed.
  - References: [`static/js/app.js`](static/js/app.js), `app/routers/scorm.py`, `app/auth.py`

- [ ] TTS latency and cost optimization follow-up
  - Type: Performance / Enhancement
  - Area: Frontend / Backend / Scenario Runtime
  - Summary: OpenAI TTS is working for realistic voices, but live generation can still add noticeable delay and intermittent provider stalls. Current mitigations are MP3 output, scenario-aware cache keys, styled-request retry with compact instructions, skip-on-provider-failure to avoid robotic voice mismatch, and initial deterministic-line prewarming when TTS is enabled.
  - Impact: Learners may see text several seconds before audio on uncached lines; provider stalls can skip optional audio. Broad SaaS use could create avoidable cost if deterministic lines are regenerated instead of reused.
  - Next step: Design static authored audio packs for pilot-stable scenarios. Add usage logging that distinguishes static audio, cache hit, prewarm generation, and live provider generation.
  - References: [docs/TTS_UPGRADE_PLAN.md](docs/TTS_UPGRADE_PLAN.md), [static/js/app.js](static/js/app.js), [app/services/tts_service.py](app/services/tts_service.py), [app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json](app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json)

- [ ] Debrief theme mismatch — dark Tailwind classes in light-themed modals
  - Type: Tech Debt
  - Area: Frontend
  - Summary: `_buildCoachFeedbackHtml()` and related helpers emit hard-coded dark-theme Tailwind classes (`text-gray-400`, `bg-gray-800`, `text-yellow-400`, etc.). The history/replay modals (`modal-last-results`, `modal-history-debrief`) are light-themed, so `style.css` currently uses 80+ `!important` overrides to re-map those classes. Any new color, background, or inline style added by JS can become illegible without a matching override.
  - Impact: Visual mismatches between in-scenario feedback and history feedback; fragile — each UI addition requires a paired CSS patch; hard to audit and test.
  - Next step: Add a `theme: "light" | "dark"` parameter to `_buildCoachFeedbackHtml()`. Emit semantic CSS class names (`coach-label`, `coach-section`, etc.) instead of Tailwind utilities; define theme variants in `style.css`. Remove all `!important` overrides for debrief modals once the semantic classes are in place.
  - References: [`static/js/app.js:14798`](static/js/app.js), [`static/css/style.css:4950`](static/css/style.css)

- [ ] Secure WebSocket token transmission
  - Type: Security
  - Area: Infra / Backend
  - Summary: JWTs are passed via query strings for WebSocket connections (`?token=...`).
  - Impact: Active tokens may be logged in plaintext by reverse proxies or load balancers.
  - Next step: Configure reverse proxy (Nginx/AWS ALB) to mask or strip the `?token=` parameter from access logs, or implement a short-lived ticket-based handshake.
  - References: `app/main.py`, `static/js/app.js`

- [x] Add explicit PHI / PII warnings to free-text inputs — **Resolved (2026-05-15).** Added "Training simulator — do not enter real patient identifiers or PHI" disclaimer text below the chat input, DMIST textarea, and narrative textarea in `static/index.html`. Styled to match existing hint text (gray-600/gray-700, text-xs) to be visible without disrupting the scenario UI.

- [x] Author first CPR-challenge scenario — **Resolved (2026-05-04).** Added `adult_cardiac_arrest_01_bls` as the Phase 1 BLS/AED pilot with a `cpr_challenge` block, public scenario exposure, deterministic post-ROSC vitals profile, and regression tests for scenario loading plus post-ROSC vitals handoff. Manual browser verification still recommended before calling CPR Phase 1 fully complete.

- [ ] CPR / newborn resuscitation challenge manual browser verification
  - Type: Release Verification
  - Area: Frontend | Backend | Scenario Runtime
  - Summary: Automated CPR/NRP scorer tests pass, but the scenario HUD flows still need manual browser E2E checks against real session state, modal behavior, event submission, debrief rendering, and post-ROSC/post-improvement vitals display.
  - Acceptance checks:
    - `adult_cardiac_arrest_01_bls`: CPR HUD opens, AED/pulse/compression controls behave correctly, `/cpr-challenge/start` returns an attempt ID, `/response` accepts timeline, ROSC and criteria-not-met debriefs render, and post-ROSC vitals show HR 96 / BP 92/58 with ROSC presentation text.
    - `peds_cardiac_arrest_01_bls`: pediatric CPR HUD uses 15:2 scoring expectations, ratio feedback appears in debrief, ROSC/no-ROSC paths submit cleanly, and post-ROSC vitals show HR 118 / BP 86/50.
    - `newborn_resus_01_nrp`: neonatal HUD opens from Map 0, initial steps / PPV / MR SOPA / HR reassessment / 3:1 escalation events submit, neonatal-specific debrief language appears, and post-improvement vitals show HR 90 with newborn-improving presentation text.
  - Next step: Run all three scenarios in browser with one known-good and one intentionally flawed attempt; record any HUD/debrief/vitals defects before calling CPR Phase 5 closed.
  - References: [docs/CPR_CHALLENGE_DESIGN.md](docs/CPR_CHALLENGE_DESIGN.md), [tests/test_cpr_challenge.py](tests/test_cpr_challenge.py), [app/scenarios/pediatric/medical/newborn_resus_01_nrp.json](app/scenarios/pediatric/medical/newborn_resus_01_nrp.json)

- [ ] CPR challenge deferred follow-ups
  - Type: Enhancement / Deferred Scope
  - Area: Frontend | Backend | Rewards | Scenario Authoring
  - Summary: CPR phases 1-5 have a working deterministic path for adult BLS, pediatric BLS, and first-pass neonatal/NRP testing. Several deliberately deferred items remain outside the current closeout scope.
  - Deferred items:
    - Build rich instructor-facing pause graph and cycle-review UI using `metrics.analytics.pause_graph` and `metrics.analytics.cycle_review`.
    - Register CPR/AED mini-game remediation targets once those mini-games exist; current Next Action routing correctly falls back to replaying the source scenario.
    - Define optional reward/challenge-coin rules for CPR outcomes using `cpr_challenge_summary`; the summary is available, but award rules are not designed.
    - Defer ALS/PALS pilot scenarios until needed; current ALS/PALS medication, antiarrhythmic, manual-defib, precharge, and advanced-airway facts are backend-supported where enabled but no ALS pilot scenario is being shipped now.
    - Defer medication dose / joules validation to the future medication-administration challenge; CPR challenge may log dose fields but must not score dose arithmetic.
    - Extend neonatal mode later with authored oxygen/SpO2 targets, epinephrine/volume escalation, and neonatal medication flows only when scope/equipment/med-admin challenge contracts are ready.
    - Expand `nrp_newborn_v1` rubric beyond CPR-challenge-event items to cover the full NRP algorithm via tier2 text patterns: initial assessment (term/tone/breathing/cry), initial steps (warm/dry/stimulate/position), PPV (rate, chest rise, effectiveness), HR reassessment timing, MR SOPA corrective steps, thermoregulation, and ALS/transport handoff. Newborn resus is out of scope for the pilot; defer until post-pilot NRP track.
  - Next step: Revisit after manual E2E verification and after CPR/AED or medication-administration mini-game planning resumes.
  - References: [docs/CPR_CHALLENGE_DESIGN.md](docs/CPR_CHALLENGE_DESIGN.md), [docs/MINIGAMES_DESIGN.md](docs/MINIGAMES_DESIGN.md)

- [x] Mini-games Phase 13 V2 closeout — **Resolved (2026-05-06).** Phase 13.0 readiness infrastructure and Phase 13.1–13.3 V2 implementation are complete.
  - Type: Deferred Scope / Release Verification
  - Area: Frontend | Mini-games | Analytics | External Assets
  - Summary: Phase 13 readiness setup and V2 implementation are complete. GCS media remains asset-gated; no unlicensed media has been added.
  - Ready-to-proceed scope:
    - Phase 13.0 readiness infrastructure is complete.
    - Phase 13.1 Vitals Trend Spotter SVG playback is complete.
    - Phase 13.2 Pediatric GCS optional approved-media renderer is complete.
    - Phase 13.3 DMIST sequence scoring/capture is complete.
  - Completed readiness evidence:
    - `docs/MINIGAMES_PHASE13_READINESS.md` created as the Phase 13 evidence log.
    - `docs/MINIGAMES_PHASE13_E2E_CHECKLIST.md` created for Vitals Trend Spotter and Pediatric GCS desktop/mobile browser verification.
    - `docs/MINIGAMES_VITALS_CHARTING_DECISION.md` created with accessibility requirements for any richer/animated Vitals charting mode.
    - `peds_gcs_calculator` deck expansion verified: 14 vignettes, including 6 infant cases; targeted readiness tests pass.
    - `peds_gcs_calculator` text/vignette browser check completed after deck expansion.
    - `docs/MINIGAMES_GCS_MEDIA_INVENTORY.md` created and future GCS media guardrails added for license/source/accessibility/scoring-label checks.
    - `dmist_builder` deck expansion verified: 8 cases; targeted readiness tests pass.
    - `GET /api/me/minigames/phase13-readiness` added as a learner-scoped analytics helper for Phase 13 evidence collection.
    - `vitals_trend_spotter` V2 implemented with dependency-free SVG Play/Pause/Replay controls and static-chart fallback.
    - `peds_gcs_calculator` Media V2 renderer implemented; it only displays media with approved license status, prompt-quality pass, URL, and text alternative.
    - `dmist_builder` V2 sequence panel, priority-band scoring, `handoff_sequence` tag, and nullable `sequence_data` result storage implemented.
  - Remaining follow-up:
    - Author or acquire licensed GCS visual/audio assets before enabling media cards.
    - Continue browser/learner E2E checks for Vitals playback and DMIST sequence UX during normal QA.
  - References: [docs/MINIGAMES_DESIGN.md](docs/MINIGAMES_DESIGN.md) §Phase 13, [docs/MINIGAMES_PHASE13_READINESS.md](docs/MINIGAMES_PHASE13_READINESS.md)

- [x] Migrate EMS scenarios to NREMT-derived base patient-care rubric families — **Resolved (2026-04-26); expanded (2026-05-02).** All scenarios now declare a base rubric and carry overlay checklists. Medical scenarios (`peds_croup_01`, `peds_asthma_01`, `peds_anaphylaxis_01`, `peds_diabetic_emergency_01`, `peds_febrile_seizure_01`, `peds_syncope_01`, `adult_acs_01_stemi`, `peds_ams_tox_01`) use `nremt_e202_medical_v1`; pediatric trauma scenarios use `nremt_trauma_v1`. The inherited base rubrics now align to NREMT station-sheet totals: Medical 48 clinical-performance points, Trauma 42 clinical-performance points, before scenario-specific overlays. Clinical-performance denominators are dynamic and are carried through structured subscore `_maxes` instead of assuming a fixed 50-point CP bucket.

- [x] Rubric-family migration plan for existing scenarios — **Resolved (2026-04-26).** Full migration sequence complete:
    1. ✅ `peds_croup_01` — pilot
    2. ✅ `peds_asthma_01` — (also fixed `\bED\b`/`\bER\b`/`\bals\b` word-boundary bug in `ems.medical.handoff`)
    3. ✅ `peds_anaphylaxis_01`, `peds_diabetic_emergency_01`, `peds_febrile_seizure_01`, `peds_syncope_01`
    4. ✅ `adult_acs_01_stemi`
    5. ✅ All 6 pediatric trauma scenarios (`peds_trauma_01` – `peds_trauma_06`), using `nremt_trauma_v1` base; SA gaps resolved by adding `scope_hemorrhage_control`, upgrading `scope_o2_blowby`, and adding `scope_immobilization_applied` and `scope_bvm_required` where needed. `pat_assessment` tier1 migrated from `finding/vital` to `scene_entry/pat_assessment` across all trauma scenarios.

- [ ] Phase 6 scoring calibration validation
  - Type: Tech Debt
  - Area: AI | Backend
  - Summary: The per-component DMIST scoring model, per-CHART narrative fidelity deductions, student-assessed vitals distinction, and professionalism tiered scale were implemented and doc'd in Phase 6 but have not yet been validated against live runs. Calibration is deferred until all scenario migrations are stable.
  - Impact: Scoring anchors and deduction weights are well-reasoned but untested against real student behavior. May require adjustment after observing actual run data.
  - Next step: Run 2–3 live scenarios with known-good and known-poor runs after scenario migration is complete. Compare Phase 6 scores against instructor expectation. Adjust calibration anchors in `_run_documentation_extraction()` and `_run_professionalism_review()` prompts as needed.
  - References: [app/ai_client.py](app/ai_client.py) (`_run_documentation_extraction`, `_run_corroboration_prepass`, `_run_professionalism_review`)

- [x] Audit frontend `innerHTML` and trust-boundary hotspots for XSS safety — **Resolved (2026-04-24).** Full audit of all 172 `innerHTML` sinks in `static/js/app.js`. Found and fixed 5 sinks that wrote AI-tag-parsed content without `escapeHTML`: `flushVitalsBlock` (vital label/value from `[[VITAL:]]` tags), `addPcrExam` (from `[[EXAM:]]` tags), `addPcrExamRaw` (same), `addPcrHistory` (from `[[HISTORY:]]` tags), `addPcrTreatment` (treatment labels from `[[INTERVENTION:]]` tags). All five are in the PCR note-capture pipeline that parses AI response tags. The `_buildCurrentPcrSnapshotHtml` PCR snapshot (which reads `innerHTML` from these same elements) is now safe by transitivity — after escaping at write time, HTML serialization round-trips safely. All other high-volume sinks confirmed safe: `renderMarkdown` (escapes before applying structural tags), `renderAiText`/`appendUserMessage` (all use `escapeHTML`), leaderboard/team/challenge renderers (all use `escapeHTML` on user display fields). 151 tests pass.

- [x] Migrate readiness and debrief inputs away from frontend tag-derived transitional capture — **Phase 1 complete (2026-04-24).** `SessionEvent` model and `session_events` table are live. `_build_evidence_packet()` accepts `session_events` and prefers authoritative events over tag-derived `SessionFinding` fallbacks for reassessment detection (via `vital_check`/`intervention_applied` event timeline) and required assessments (via `explicit_assessment` event keys). Both intervention endpoints (`POST /api/sessions/{id}/interventions` and `_auto_detect_interventions()`) auto-emit `intervention_applied` events (`source=backend_auto`). `POST /api/sessions/{id}/events` endpoint added for `frontend_explicit` and `instructor_note` sources. Gate 1 has not fired — no current scenario depends on multi-step reassessment producing materially wrong scoring. `AI_ARCHITECTURE.md §3.1` updated with concrete gate criteria. 7 new regression tests (199 total passing). The `SessionFinding` bridge remains active as a fallback — both paths run in parallel until Gate 1 fires.

- [x] Security and trust-boundary hardening pass (Codex review) — **Resolved (2026-04-24).** Multiple fixes applied across three review rounds: (1) `intervention_applied` type blocked from client submission to `POST /api/sessions/{id}/events`; `instructor_note` source gated behind `admin`/`instructor`/superuser role check; `instructor_note` submissions use agency-scoped session lookup so instructors can annotate learner sessions within their agency. (2) `frontend_explicit` events are stored but NOT treated as authoritative in `_build_evidence_packet()` — `_explicit_assessment_keys`, `_authoritative_reassessment` (vital_check), and `_event_iv_times` all filter to `source in (backend_auto, instructor_note)` only; two new regression tests enforce this boundary. (3) Rate limits added to `POST /api/sessions/{id}/adjudications` (`rate_limit_debrief/min`) and `GET /api/sessions/{id}/adjudications` (`rate_limit_session_write/min`). (4) Raw exception details removed from all client-facing 503 and stream error responses (chat stream, medical control, both debrief routes) — full exception details logged server-side via `log.error()`; clients receive generic retry messages. (5) `turnover_target` missing/`dynamic` now logs loudly in `_build_system_prompt()` and `_coachLexiContextPrompt()` (cannot raise on streaming path; `_build_evidence_packet()` raises `ValueError` on the non-streaming path). (6) Cached debrief responses in both `submit_narrative` and `skip_narrative` now return `_effective_score()` / `_effective_subscores()` instead of stored raw values, ensuring post-adjudication views are consistent. (7) `_SESSION_EVENT_TYPES` and sibling constants moved before `SessionEventRequest` to eliminate forward-reference ordering risk. 205 tests pass.

- [x] Content audit — scenario production readiness across all 12 scenarios — **Resolved (2026-04-24).** Full field audit confirmed: `debrief` (condition_background, key_teaching_points, common_mistakes), `exemplar_dmist`, `exemplar_narrative`, `scoring_rubric`, `dmist_considerations`, `narrative_considerations`, and `required_assessments` are present and complete for all 12 scenarios. `dmist_components` is present for 11/12 — `adult_acs_01_stemi` is a hospital-turnover scenario using verbal handoff format, so `dmist_components` is intentionally absent. `required_screens` is present for 7/12 — the 5 scenarios without it have no dangerous differential with a clinically distinct BLS treatment path; absence is intentional and documented. `corroboration_rules` added to the 5 high-stakes scenarios (`peds_anaphylaxis_01`, `peds_trauma_04_burn`, `adult_acs_01_stemi`, `peds_trauma_03_extremity`, `peds_trauma_05_auto_ped`); 2-pt default is appropriate for the remaining 7. 192/192 tests pass.

- [x] Consolidate scenario authoring documentation and reduce stub indirection — **Resolved.** Stub at `app/scenarios/scenario_design_ems.md` retained as redirect only (already correct). Canonical-source header added to `docs/SCENARIO_DESIGN_EMS.md`. Link hygiene audited across `DEVELOPMENT_GUIDELINES.md`, `AI_ARCHITECTURE.md`, and `multi_tenant_protocol_architecture.md`. Section 14 of DEVELOPMENT_GUIDELINES.md now lists all canonical companion docs with paths.

## Medium

- [x] Gold-standard fixtures for all scenario families — **Resolved (2026-04-25).** All 13 scenario families now have fixtures in `tests/test_adjudication_gold_standard.py`. 48 gold-standard tests total: full-credit and key-gap fixtures for every scenario, plus scope-violation fixtures for scenarios with out-of-scope intervention guards. Structural enforcement test (`test_all_fixture_items_have_expected_coverage`) is now parametrized over all 13 scenarios — adding a checklist item to any covered scenario will fail CI until a fixture expectation is added. Two edge cases fixed during authoring: `peds_asthma_01` exam finding key changed to avoid false T2 match on `reassess_post_albuterol` via finding-text path; `peds_trauma_02_partial_choking` gap fixture uses empty messages because `rapid_transport` T2 pattern matches "go" as a substring. 574/574 tests pass.

- [x] Debrief prose hallucination — Key Takeaways overcredits unsupported reasoning — **Partially resolved (2026-05-15).** Non-renderer-active Key Takeaways instruction now constrained to `## CLINICAL_PERFORMANCE_GAPS` and `## PROTOCOL_TREATMENT_GAPS` evidence blocks only — matching the renderer-active constraint. Eliminates open-ended sourcing from scenario/condition background. Racepinephrine croup fabrication risk remains until Phase 8 E3 renderer is live (structural fix).
  - References: [docs/SCORING_ENGINE_ARCHITECTURE.md §13](docs/SCORING_ENGINE_ARCHITECTURE.md), [docs/SCORING_IMPROVEMENT_PLAN.md Group E](docs/SCORING_IMPROVEMENT_PLAN.md), [app/ai_client.py](app/ai_client.py)

- [ ] Debrief Section 7 protocol gap specificity — missed actions not named explicitly
  - Type: Enhancement
  - Area: AI
  - Summary: After the category-separated evidence block fix, croup Section 7 (Protocols & Treatment) no longer cross-contaminates assessment gaps, but it still fails to clearly name the missed protocol gap (`positioning_calm`: parent-held upright, calm environment, ALS handoff readiness). The section is accurate in structure but too generic to drive targeted remediation.
  - Impact: Students reading the debrief cannot easily identify which specific protocol action they missed. Reduces actionability of the debrief, especially for novice learners.
  - Next step: Add `missed_feedback` metadata to the `positioning_calm` checklist item per the Phase 8 E1/E2 schema (`done_feedback`, `missed_feedback`, `clinical_rationale`, `common_error`). Once E2 (author metadata) is complete for croup, this will feed the Phase 8 renderer directly.
  - References: [docs/SCORING_IMPROVEMENT_PLAN.md Group E](docs/SCORING_IMPROVEMENT_PLAN.md), [app/scenarios/pediatric/medical/peds_croup_01.json](app/scenarios/pediatric/medical/peds_croup_01.json)

- [x] Professionalism subscore variance — same sparse chat scoring 3 vs 5 across runs — **Resolved (2026-05-15).** `_run_professionalism_review()` now anchors to a deterministic baseline (`hardened_ceiling`) and asks the LLM only for a ±1 tone-quality adjustment. Maximum variance is ±1 point instead of ±4.
  - References: [app/ai_client.py](app/ai_client.py) (`_run_professionalism_review`), [docs/SCORING_IMPROVEMENT_PLAN.md](docs/SCORING_IMPROVEMENT_PLAN.md)

- [ ] Tier 3 async implementation — `_try_tier3()` in `scoring_service.py` is currently a stub that returns `None`. Items with `tier3_permitted: true` route to `ambiguous` instead of being adjudicated. Full implementation requires making `adjudicate()` async (Phase 7+ per architecture doc).
  - Type: Tech Debt
  - Area: Backend / AI
  - Summary: No items currently use `tier3_permitted: true` in production scenarios, so this has no runtime impact. When Tier 3 items are authored, they will all route to `ambiguous` until this is implemented.
  - Impact: `tier3_permitted` items cannot be credited or deducted; they appear in the instructor review queue on every session.
  - Next step: Implement async `adjudicate()` with logprob-based binary classification before authoring any `tier3_permitted` items.
  - References: [app/scoring_service.py](app/scoring_service.py), [docs/SCORING_ENGINE_ARCHITECTURE.md §12](docs/SCORING_ENGINE_ARCHITECTURE.md)

- [ ] MCI / multi-patient session model design gate
  - Type: Tech Debt
  - Area: Backend / Data
  - Summary: The current data model is single-session = single-patient. MCI scenarios (mass-casualty, RTF) cannot be authored until a new session type is designed that supports multiple concurrent patient tracks, per-patient triage decisions, and mass-casualty-specific scoring categories.
  - Impact: No MCI scenario can be authored or run correctly under the current model; stretching the existing model would produce data integrity problems.
  - Next step: Design the multi-patient session model before any MCI scenario authoring begins. Document the design in a new `docs/MCI_SESSION_ARCHITECTURE.md` and add an explicit gate check here when ready.
  - References: [docs/SCORING_ENGINE_ARCHITECTURE.md §5.1](docs/SCORING_ENGINE_ARCHITECTURE.md)

## Low

- [ ] Migrate JWT storage from LocalStorage to HttpOnly cookies
  - Type: Security / Tech Debt
  - Area: Frontend / Backend
  - Summary: The active JWT is currently stored in browser `localStorage`.
  - Impact: Vulnerable to exfiltration if a Cross-Site Scripting (XSS) payload bypasses current sanitization.
  - Next step: Refactor backend to set HttpOnly, Secure cookies for auth, and update frontend fetch logic to include credentials.
  - References: `static/js/app.js`, `app/main.py`

- [x] `scene_entry` PPE path generalization — **Resolved.** `_try_tier1` now uses `TierOneMatchSpec.scene_entry_path` for generic dot-path navigation of the scene_entry JSONB. `"ppe"` remains a special case for list-intersection logic. All other paths resolve via a simple dot-path walk to a truthy leaf. Covered by `tests/test_scoring_service.py`.

- [x] Update stale `SessionFinding` model documentation to match current dedupe behavior — **Resolved.** Comment updated to document the partial-index / minute-bucket enforcement for exam/vital and upsert behavior for history.

- [x] Change Admin dashboard color scheme to match the color guide using the dark brown theme.

- [ ] `_sanitize_protocol_treatment_section()` hardcoded vocabulary is a code smell — retire after Phase 8 E3
  - Type: Tech Debt
  - Area: Backend / AI
  - Summary: `_sanitize_protocol_treatment_section()` in `app/ai_client.py` carries a hardcoded vocabulary list keyed to croup clinical facts (racepinephrine, etc.) to prevent ALS drug references from bleeding into protocol deduction prose. It was added as defense-in-depth after the category-separated evidence blocks structural fix. The problem is that adding any new scenario with a similar overcredit risk requires editing application code, not the scenario file. The `common_error` field on the relevant checklist item (Phase 8 E2 authoring) is the correct mechanism — scenario authors maintain the guardrail in JSON, not in the engine.
  - Impact: Every new scenario with an overcredit risk silently requires a code change to the sanitizer. The split authority (JSON metadata + engine code) is exactly the failure mode Phase 8 exists to prevent. Currently low-risk because scenario count is small and the structural evidence-block fix is the primary defense; becomes a real maintenance burden as the scenario library grows.
  - Next step: Author `common_error` for `racepinephrine_als` in `peds_croup_01` as part of Phase 8 E2. Once E3 (`_compose_scored_section()`) is active and the croup renderer produces correct output without the sanitizer, remove `_sanitize_protocol_treatment_section()` entirely. Do not remove it before E3 is validated.
  - References: [app/ai_client.py](app/ai_client.py) (`_sanitize_protocol_treatment_section`), [docs/SCORING_IMPROVEMENT_PLAN.md Group E](docs/SCORING_IMPROVEMENT_PLAN.md), [app/scenarios/pediatric/medical/peds_croup_01.json](app/scenarios/pediatric/medical/peds_croup_01.json)

- [ ] Remove Team Challenges from Generic Agencies so only people associated with an Agency can see other agency members and not all users.

- [ ] Tier 2 pattern miss on minor transcript typos — "andy better" vs "any better"
  - Type: Low
  - Area: Backend / Scoring
  - Summary: 3-round croup testing revealed a 1-point clinical swing where "andy better" (likely autocorrect artifact) failed to match the Tier 2 pattern for "any better" (response-to-treatment evaluation). The adjudicator correctly returned `None` — the text does not match. The issue is whether minor OCR/autocorrect typos should be handled by pattern fuzzing.
  - Impact: At most a 1-point swing per transcript error. Acceptable in isolation; worth noting as a class of edge case.
  - Next step: Assess whether the `reassess_post_treatment` Tier 2 pattern in `peds_croup_01` should add a broader synonym pattern to catch "andy"/"adn"/"teh" class autocorrect errors. If Tier 2 patterns are broad enough, individual typo patterns are unnecessary overhead. Flag for review when touching Tier 2 pattern authoring.
  - References: [app/scoring_service.py](app/scoring_service.py), [app/scenarios/pediatric/medical/peds_croup_01.json](app/scenarios/pediatric/medical/peds_croup_01.json)

- [ ] `_get_unlocked_drill_ids` / `_get_completed_scenario_ids` load all sessions in Python
  - Type: Performance / Tech Debt
  - Area: Backend
  - Summary: Both helpers fetch every ended session for the user+agency and filter in Python: skip drill sessions (JSONB `narrative_data["drill"]` check) and skip orientation scenarios (requires `load_scenario()` call). The JSONB check could move to SQL, but the orientation check cannot without a denormalized column. Together they run on every `/api/me/drills/status` and `/api/me/random-call/status` request.
  - Impact: Acceptable at current scale (<50 sessions/user). Becomes a latency concern as session counts grow — O(n) Python loop per status request.
  - Next step: Add a `is_drill BOOLEAN` column to `SimSession` (Alembic migration, populated on session create). Add an `is_orientation BOOLEAN` column or maintain a server-side set of orientation scenario IDs. Both helpers can then push the full filter to SQL with a single indexed WHERE clause.
  - References: [app/main.py](app/main.py) (`_get_unlocked_drill_ids`, `_get_completed_scenario_ids`)

- [ ] O2 delivery UI behavior inconsistency across croup scenario runs
  - Type: Bug
  - Area: Frontend / Scenario Runtime
  - Summary: 3-round croup consistency testing found that Round 2 auto-spoke blow-by oxygen delivery while Rounds 1 and 3 used the setup/confirm flow. The same scenario and provider level should produce the same UI interaction path on every run.
  - Impact: Inconsistent workflow experience; if scoring depends on the interaction event sequence, the auto-speak path may produce different evidence than the confirm-flow path.
  - Next step: Audit the blow-by O2 auto-speak trigger in `app.js` and identify the condition that differs between rounds. Verify that the `intervention_applied` event is emitted regardless of which path fires, and that both paths produce identical evidence-packet entries.
  - References: [static/js/app.js](static/js/app.js), [app/main.py](app/main.py)

## Trivial

- [ ] No items currently recorded.

## Implementation Roadmap — Learning System

This is the frozen implementation order for the learning system features. Items must be implemented in this sequence. Do not begin an item until the preceding item is shipped and stable. Do not skip ahead to lower-priority items because they seem simpler or more visible.

**Rationale for order:** highest instructional yield first, lowest dependency first. Items 1 and 2 have no shared dependencies and can be worked in parallel on separate branches.

**Detailed task checklists for all phases:** [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)

| Phase | Feature | Status | Parallel? | Design gates |
|---|---|---|---|---|
| 1A | Random Call spaced retrieval (SM-2) | ✅ Complete | ✅ Parallel with 1B | ✅ All passed |
| 1B | DMIST primary impression field | ✅ Complete | ✅ Parallel with 1A | ✅ All passed |
| 2 | Debrief contract + BLUF restructure + Next Action routing | ✅ Complete | No | ✅ All passed |
| 3 | Shared challenge modal shell | ✅ Complete | No | ✅ All passed |
| 4 | Primary impression challenge | ✅ Complete | No | ✅ All passed |
| 5 | ECG / rhythm strip challenge | Not started | No | Phase 3 ✅; static ECG images needed; target scenario identified |
| 6 | Medication math challenge | Not started | No | Phase 3 ✅; `patient.weight_kg` required in target scenarios |
| 7 | Capnography interpretation challenge | Not started | No | Phase 3 ✅; ALS-only; static waveform images needed |

**Note:** Items 5 and 6 from the original roadmap are swapped — shared shell (Phase 3) must precede the impression challenge (Phase 4). The impression challenge uses the single-choice plugin from the shell.

**Pre-build requirements for Phases 5–7:**

- **Phase 5 (ECG):** Author `ecg_challenge` JSON block in at least one cardiac scenario. Add ECG strip images to `/static/img/ecg/`. Confirm image serving is covered by existing static file handler. Verify `adult_acs_01_stemi` is a viable first target. See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) §Phase 5 for full pre-build gate checklist.
- **Phase 6 (Med Math):** Confirm `patient.weight_kg` is declared in target scenario patient records (`peds_anaphylaxis_01`, `peds_asthma_01`). Author `med_math_challenge` blocks. Critical: intervention must be logged *after* challenge emit — do not block intervention on challenge result. See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) §Phase 6.
- **Phase 7 (Capnography):** Add waveform images to `/static/img/capnography/`. Scope-gate to ALS provider levels — BLS students must not receive capnography challenges. Author `capnography_challenge` blocks in ALS respiratory scenarios. See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) §Phase 7.

---

## Feature and Change Requests

- [ ] Multi-tenant protocol Phase 2 readiness
  - Type: Architecture / Product Gate
  - Area: Protocol Profiles, Agency Admin, Scenario Authoring, Scoring
  - Summary: Phase 1 protocol profile infrastructure is complete for pilot use. Before Phase 2 custom SOP ingestion, tree-shaking, or scope analysis begins, complete the closeout follow-up tracker in `multi_tenant_protocol_architecture.md`: pilot validation, user acquisition path, clinical concept taxonomy, intervention action ID vocabulary, protocol tagging contract, scenario tagging retrofit, compile/fan-out scaling plan, and SME/legal review gates.
  - Reason: Phase 2 depends on stable clinical/action vocabularies and governance rules. Starting with free-text local protocol UI before those contracts are settled would reintroduce ambiguity into scoring, debriefs, and tenant-specific protocol authority.
  - Progress: Initial `docs/clinical_concept_taxonomy.md` contract and `vocabulary.CLINICAL_CONCEPTS` / `vocabulary.INTERVENTION_ACTIONS` registries created (2026-05-02); SME review approved the contract with revisions addressed (2026-05-03). Added missing OB/GYN, behavioral/psychiatric, infectious disease/sepsis, pulmonary edema, croup, tension pneumothorax, cardiac arrest, stroke, dysrhythmia, hypothermia/frostbite/heat illness, BLS resuscitation, airway adjunct, hemorrhage-control, chest-seal, traction-splint, pediatric assessment, ALS airway, vascular access, electrical therapy, and high-risk ALS medication IDs. Initial protocol tagging strategy chosen: static mapping layer in `app/protocol_concept_index.py`, with inline protocol JSON tags recommended for long-term drift control. Existing EMS scenarios now carry initial `clinical_context` and `jurisdiction` tags with regression coverage for known concepts and at least one non-authoritative protocol preview match per scenario. Indexed protocol JSON tag retrofit is complete for the current scenario-relevant subset: 48 MI and 19 NASEMSO protocol files now carry `clinical_context.concepts` with `sme_review_status: pending`. A non-authoritative protocol excerpt preview helper, admin-only preview endpoint, and MCA/Protocols dashboard preview panel exist for testing/admin inspection. These are not yet consumed authoritatively.
  - Phase 2A progress: Non-authoritative storage/API/UI scaffolding is complete. `agency_sops` model/table exists with profile association, review-state fields, clinical concept/action IDs, patch payload storage, and `sme_review_status`; `sessions` has `active_sop_ids`, `effective_protocol_excerpt`, and immutable `debrief_markdown` storage fields. Admin APIs and the MCA/Protocols dashboard tab support SOP draft creation/editing, submit-for-review, and second-person review with submitter ≠ approver enforcement.
  - Phase 2B progress: Runtime excerpt wiring is active for the pilot. Approved SOP rows are promoted to `active`; session start builds `session.effective_protocol_excerpt` from the immutable protocol snapshot plus active SOP rows; chat and debrief prompts consume the session-pinned excerpt; the evidence packet includes deterministic protocol/scope classifications from canonical intervention action IDs; active SOP `scope_restriction` rules generate deterministic `protocol_scope` checklist overlay items in `scope_adherence`; active SOP `contraindication` and `not_carried` rules generate deterministic `protocol_scope` checklist overlay items in `protocols_treatment`.
  - Resolved governance/infrastructure sequencing: SOP approval separation, one-person agency external review path, template-only protocol change summaries, write-time plus compile-time patch validation, initial tiering, no-PHI/BAA posture, and compile/fan-out sequencing are now documented in the architecture plan.
  - Deferred follow-up: Move pilot static mappings toward inline protocol JSON tags as protocol/scenario coverage expands. Legal/security review remains required before enterprise sales/BAA commitments.
  - Scenario authoring follow-up: Add an IFT "trap" scenario using `interfacility_transfer` where a BLS crew must recognize that a facility-initiated infusion or transfer requirement exceeds BLS transport criteria and request ALS/qualified facility staff instead of accepting the transfer. Use `quality_improvement_review` only to surface realistic QI/PSRO consequences in debrief for protocol deviations, out-of-scope interventions, pediatric advanced airways, or other authored 100% review triggers; QI policy should not become hidden score math until explicit overlay rules exist.
  - Phase split: Phase 2A non-authoritative persistence/workflow scaffolding is complete; Phase 2B runtime tree-shaking, active-SOP filtering, prompt/debrief excerpt use, deterministic evidence-packet scope analysis, and initial active-SOP scoring overlays are implemented for pilot use. Phase 2C scale/paid-tier expansion covers PDF extraction and fan-out queue and is deferred until usage volume or paid onboarding demand justifies it.
  - Next step: Begin Phase 3 Ohio (OH) planning. Determine whether Ohio should be authored as a NASEMSO fork/diff or full state base, identify/confirm the Ohio clinical SME review path, and create the first-state authoring checklist. Continue broadening Phase 2B scoring only after structured contracts exist for broad equipment-policy prose and protocol-derived non-SOP rules. Do not infer those from prose. Medical-control contact now has a trusted backend `medical_control_contact` `SessionEvent`; Tier 1 scoring can match session events generally; timestamped `before_item` / `after_item` / `ordered_set` constraints are evaluated by the adjudicator. Score-bearing "medical control required before intervention" rules still need an explicit active-SOP overlay generator before they should be enabled.
  - References: [docs/multi_tenant_protocol_architecture.md](docs/multi_tenant_protocol_architecture.md) §Phase 1 Closeout Follow-Up Tracker

- [x] SME review — Phase 2 protocol taxonomy, action IDs, and tag mappings — **Resolved with revisions addressed (2026-05-03).**
  - Type: Clinical Review / Release Gate
  - Area: Protocol Profiles, Scenario Authoring, Scope Analysis, Debrief Evidence
  - Scope: Review and approve the initial Phase 2 clinical concept taxonomy, intervention action ID vocabulary, scenario `clinical_context` tags, static protocol mapping index, and the mirrored initial protocol JSON tags.
  - Current package: `docs/clinical_concept_taxonomy.md`, `app/scenarios/vocabulary.py`, `app/protocol_concept_index.py`, current scenario JSON `clinical_context` blocks, and indexed protocol JSON `clinical_context` blocks.
  - Current coverage: Current EMS scenario library is tagged and preview-tested. Indexed protocol JSON tag retrofit covers 48 Michigan and 19 NASEMSO files with `sme_review_status: pending`.
  - Acceptance criteria: SME signs off taxonomy/action IDs as stable enough for production data; scenario tags are clinically accurate; static protocol mappings and mirrored protocol JSON tags are clinically appropriate for initial tree-shaking; unresolved items are documented before any authoritative prompt/scoring/scope/debrief usage.
  - Review outcome: Approved with revisions. Required additions/corrections were pulmonary edema, croup, tension pneumothorax, cardiac arrest, stroke, bradycardia/tachycardia, hypothermia/frostbite/heat illness, OB/GYN, behavioral/psychiatric, infectious disease/sepsis concepts; BLS resuscitation, AED, tourniquet, hemostatic packing, airway adjunct, chest seal, traction splint, pediatric assessment, ALS airway, vascular access, electrical therapy, and high-risk ALS medication action IDs; static mapping fixes for abdominal pain, FBAO, ETCO2; and scenario tag fixes for croup, anaphylaxis, febrile seizure, burn, auto-pedestrian trauma, ACS, and extremity trauma. These have been added to `app/scenarios/vocabulary.py`, `app/protocol_concept_index.py`, mirrored protocol JSON tags, scenario `clinical_context` blocks, and documented in `docs/clinical_concept_taxonomy.md`.
  - Hard boundary: This review gate is complete, but tag-based excerpts still remain limited to tests/admin preview/design validation until Phase 2B runtime wiring and regression coverage explicitly enable production scoring, Medical Control, debrief deductions, or prompt excerpts.
  - References: [docs/clinical_concept_taxonomy.md](docs/clinical_concept_taxonomy.md), [docs/multi_tenant_protocol_architecture.md](docs/multi_tenant_protocol_architecture.md) §Phase 2 prerequisites

- [x] User Notes — Phase 1 MVP — **Resolved (2026-04-26).** `UserNote` model, `user_notes` table DDL (with `user_id` and `user_id/scenario_id` partial indexes), and 5 CRUD endpoints (`POST/GET/GET{id}/PUT/DELETE /api/notes`) implemented with tag normalization, session ownership validation, and rate limiting. "📓 Add a Note" ghost button added to debrief modal; note create/edit modal with title, body, and tags. History page patched to inject a per-run "📓 Notes" button that lazy-fetches and expands inline with edit/delete. "📓 Notebook" placeholder button added to home screen bottom row. 559 tests pass.

- [x] User Notes — Phase 2 Notebook — **Resolved (2026-04-26).** `screen-notebook` screen implemented with header (← Back, + New Note), filter bar (keyword search with 250ms debounce, scenario dropdown populated from note metadata cross-referenced against `state.allScenarios`, tag chip toggles with active-state highlight), note card grid with `line-clamp-3` body preview, scenario label, relative timestamp, Edit/Delete (3-second inline confirm), and empty state. `buildNotebookPage()` fetches `GET /api/notes` (all-user), `_buildNotebookScenarioFilter()` / `_buildNotebookTagChips()` / `_renderNotebookCards()` are all client-side and composable. Save handler now calls `buildNotebookPage()` when the Notebook screen is visible. `btn-menu-notebook` routes to `showScreen("notebook")` + `buildNotebookPage()`.

- [ ] Map prerequisite locks — implement before release
  - Type: Pre-release Gate
  - Area: Frontend, Map Gameplay
  - Summary: All map navigation paths are currently unlocked unconditionally for development and testing. Fog of war, prerequisite gates, and PE1 two-key gate enforcement must be implemented from the topology contract before public release.
  - Impact: Without enforcement, learners can access any scenario regardless of progression readiness. Prerequisite gates exist to sequence clinical complexity — bypassing them undermines the pedagogical design.
  - Next step: Extract topology contract from `PEDIATRIC_MAP_DESIGN.md` into `MAP_TOPOLOGY` code structure (Section 5 of `MAP_GAMEPLAY_DESIGN.md`), then implement fog rendering and gate logic against it. This is Phase 1 of the map gameplay plan.
  - References: [docs/MAP_GAMEPLAY_DESIGN.md](docs/MAP_GAMEPLAY_DESIGN.md), [docs/PEDIATRIC_MAP_DESIGN.md](docs/PEDIATRIC_MAP_DESIGN.md)

- [ ] Treat Management — economy redesign
  - Type: New Feature
  - Area: Backend, UI/UX, Rewards
  - Summary: Implement decided treat economy changes: (1) wallet cap of 15 treats enforced server-side on all earn events, (2) mini-game treat earning (+1 per mini-game per 24h window, per-game independent), (3) progressive in-scenario hint cost (1/2/3 treats for successive hints within a session, counter resets per session), (4) toy sell-back at 35% of purchase price rounded down, minimum 1, earn-only toys excluded.
  - Reason: Limit hint-chaining without flat economy; incentivize optional learning via mini-game play; make toy selling feel like a real sacrifice.
  - References: [docs/REWARDS.md](docs/REWARDS.md) §2.2, §2.4, §2.5, §3.6

- [ ] Agency Equipment Management
  - Type: Change Request
  - Area: Agency Management, AI (prompt context), Backend (agency config API)
  - Summary: Replace free-text equipment and meds entry with a curated master list per category. Each item gets a binary carried/not-carried toggle. Custom add buttons remain for items not on the master list, capped at 10 total custom items across all categories combined (prompt-budget constraint, not a storage constraint). Quantity limits, conditional access, and provider-level restrictions are out of scope here — those are handled by the protocol and scope-adherence layers.
  - Reason: Standardize equipment naming across agencies, ensure completeness accountability (explicit "not carried" vs. never entered), and bound prompt token cost.
  - Impact clarification: This feature affects AI prompt context only. `scoring_service.py` and `checklist.py` do not read agency equipment config — scope-adherence scoring uses scenario JSON, not the agency config. There is no deterministic scoring impact. The change does affect what the AI considers available during a session and what appears in the "NOT CARRIED — not available on this unit" prompt enforcement block.
  - Authoritative stored schema — `agencies.config["equipment"]` target shape:
    ```json
    {
      "items": [
        {"id": "bvm_adult_peds_infant",    "carried": true,  "source": "master"},
        {"id": "albuterol_svn_unit_dose",  "carried": true,  "source": "master"},
        {"id": "epi_autoinjector_adult",   "carried": false, "source": "master"},
        {"id": "custom_abc123",            "carried": true,  "source": "custom", "label": "My Custom Item"},
        {"id": "custom_unresolved_xyz",    "carried": true,  "source": "custom", "label": "Old free text entry", "needs_review": true, "original_text": "Old free text entry"}
      ]
    }
    ```
    Master items not present in the list are treated as not carried by default. Items with `carried: false` are injected into the AI's "NOT CARRIED" enforcement block. Items with `needs_review: true` are still treated as carried and still feed the prompt — they retain pre-migration behavior until the admin resolves them. `needs_review` is advisory only and does not block saving or session operation.
  - Design decisions:
    - **Master list vocabulary:** All curated items must use canonical names and IDs from `app/scenarios/vocabulary.py`. The registry must be extended with an `EQUIPMENT_CATALOG` (keyed by category: airway, monitoring, trauma, other), a `MEDICATIONS_CATALOG`, and an `EQUIPMENT_ALIASES` dict mapping common abbreviations and variants to canonical IDs.
    - **Custom item cap:** 10 items total across all categories combined. Enforced server-side on `PUT /api/agency/config`. This is a prompt-budget constraint.
    - **Migration strategy for existing free-text data:** Three-pass auto-match at startup (idempotent — skipped if `items` key already present): (1) exact canonical name match after normalization → auto-confirm, `source: "master"`; (2) alias lookup against `EQUIPMENT_ALIASES` → auto-confirm, `source: "master"`; (3) substring/prefix match against canonical labels → `needs_review: true`, requires admin confirmation. Unresolved entries become custom items with `needs_review: true`. Items from the old `not_carried` list follow the same three passes but migrate with `carried: false`. Migration also sweeps the old UI-saved `equipment.carried` flat list (pre-existing schema inconsistency where the UI wrote `carried` but the AI read `airway/monitoring/trauma/other`).
    - **Migration behavior for unresolved items:** Unresolved items are immediately treated as carried and feed the AI prompt (preserves pre-migration behavior). Unresolved `not_carried` items continue to feed the "NOT CARRIED" enforcement block. `needs_review` surfaces as a warning banner in the agency config UI on next admin login — it does not block saving or session operation.
    - **AI prompt reader:** `_build_agency_prompt_block` in `ai_client.py` must be updated to read the new `items` schema. A fallback for the old `airway/monitoring/trauma/other` schema must be retained during the transition window. Prompt output format (carried semicolon list, not-carried list) does not change — only how those lists are assembled.
    - **Seed JSON files:** Open-join agency seed JSON files must be updated to the new `items` schema after the master catalog is finalized, so fresh deployments seed correctly.
  - Next steps (in order):
    1. Finalize master catalog contents and extend `vocabulary.py` with `EQUIPMENT_CATALOG`, `MEDICATIONS_CATALOG`, and `EQUIPMENT_ALIASES` — this is the foundation all other phases depend on. As part of this step, define the exact prompt-format output strings for: (a) carried curated items, (b) carried custom items, and (c) explicit not-carried items. Writing this down before touching `ai_client.py` keeps the migration/fallback behavior crisp and directly testable.
    2. Write and test the migration function (`_migrate_equipment_config`) as a pure function before wiring it to startup.
    3. Update `_build_agency_prompt_block` with new schema reader and old-schema fallback.
    4. Add/update API endpoints: catalog endpoint, config validation with cap enforcement, review queue and resolution endpoints.
    5. Replace equipment UI with catalog checkbox grid, custom item flow, and migration review banner.
    6. Update open-join agency seed JSON files.
    7. Write regression tests covering: vocabulary helpers, migration passes, prompt injection, cap enforcement, and review resolution.
  - References: [app/scenarios/vocabulary.py](app/scenarios/vocabulary.py), [app/ai_client.py](app/ai_client.py), [app/main.py](app/main.py), [docs/AI_ARCHITECTURE.md](docs/AI_ARCHITECTURE.md)

- [ ] Agency SOPs
  - Type: Change Request
  - Area: Agency Management
  - Summary: Limit number of SOPs and CHAR add limits.
  - Reason: Limit data, prevent token bloat, minimize logic/performance issues.
  - References: None

- [ ] Add learning cards to notebook
  - Type: Change Request
  - Area: Noetbook
  - Summary: Add the learning info from minigames to the notebook in a new section - organize
  - Reason: Consolidate learning notes in one place for easy review.
  - References: None

- [ ] Add link to debrief history in the notes
  - Type: Change Request
  - Area: Notebook
  - Summary: When opening a notes page that was created in a scenario the debrief from that scenario should be easily accessible from the note page.
  - Reason: Add context and reference link to the note.
  - References: None

- [ ] Transport-aware turnover messaging
  - Type: Future Change
  - Area: Scenario Runtime, Lexi, Transport Modules
  - Summary: When transport modules are added, update Lexi turnover prompts so "turnover patient care" is phase-aware. Current ALS-arrival scenarios can prompt turnover when ALS arrives, but transport-enabled scenarios should reserve turnover language until hospital arrival and handoff to ED staff.
  - Reason: Prevent future mismatch between Lexi guidance and the active care phase once simulations include transport and ED arrival.
  - References: None

---

## Triage Rules

- If an item affects security, tenant isolation, grading integrity, clinical determinism, or public SaaS readiness, start by considering `Critical` or `High`.
- If an item is primarily polish or readability with no correctness or safety impact, it is usually `Low` or `Trivial`.
- If unsure between two severities, use the higher one until reviewed.

---

## Review Cadence

- Review `Critical` and `High` items before release decisions.
- Review `Medium` items during normal sprint or milestone planning.
- Batch `Low` and `Trivial` items during cleanup passes or when touching the same code area.
