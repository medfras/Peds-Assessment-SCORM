# Implementation Plan — Learning System Features

**Status:** Active Planning  
**Last Updated:** 2026-04-28 (Phases 1–4 complete; Phase 4 unit tests added; Phases 5–7 staged)  
**Scope:** Phased implementation of the learning system roadmap (PUNCHLIST.md §Implementation Roadmap). Each phase is a shippable unit. Do not begin a phase until the preceding phase is deployed and passing CI.

**Roadmap reorder note:** Items 5 and 6 in the original PUNCHLIST roadmap are swapped here. The shared challenge shell must be built before the primary impression challenge, since the impression challenge uses the single-choice plugin. The PUNCHLIST.md roadmap table already reflects this reordered sequence.

---

## Phase 1A — Random Call Spaced Retrieval (SM-2)
**Parallel with Phase 1B. No dependencies on any other phase.**

### Design gate check
- [x] Deterministic authority: SM-2 update formula is pure math, no LLM involvement
- [x] Trigger event: post-completion of a Random Call session (session_type == "random_call", ended_at set)
- [x] Schema defined: three new fields on new `StudentScenarioHistory` table
- [x] UI component strategy: no new component (selection is backend-only)
- [x] Priority assigned: Roadmap item 1

### Backend — models.py
- [x] Create `StudentScenarioHistory` model with fields:
  - `id` (String, UUID primary key)
  - `user_id` (String, FK → users)
  - `agency_id` (String, FK → agencies)
  - `scenario_id` (String)
  - `interval_days` (Float, default 1.0)
  - `ease_factor` (Float, default 2.5)
  - `last_random_call_date` (DateTime, nullable)
  - `last_rc_score` (Integer, nullable — most recent RC assessment score; overwrites on every RC completion)
  - Unique constraint on `(user_id, agency_id, scenario_id)`

### Backend — database.py
- [x] Add `CREATE TABLE IF NOT EXISTS student_scenario_history` migration in `init_db()`
- [x] Add unique index on `(user_id, agency_id, scenario_id)`
- [x] Add `DO $$ BEGIN ... EXCEPTION WHEN undefined_column THEN NULL; END $$` rename guard for DBs created before the `best_rc_score → last_rc_score` rename

### Backend — main.py
- [x] Add helper `_get_rc_history(user_id, agency_id, scenario_ids, db)` → `dict[scenario_id, StudentScenarioHistory]`
- [x] Replace `random.choice(pool)` in `start_random_call` with weighted selection:
  - Query `StudentScenarioHistory` for current user/agency
  - Build weight map: `review_due ≤ today` → 4, never in history → 2, otherwise → 1
  - Use `random.choices(population, weights, k=1)[0]`
  - Preserves existing anti-repeat `RC_NO_REPEAT_WINDOW` filter (applied before weighting)
- [x] Add `_update_rc_history(user_id, agency_id, scenario_id, score_pct, db)`:
  - Score tier: ≥ 85% → `interval × ease_factor`, ease += 0.1 (max 3.0)
  - Score tier: 70–84% → `interval × 1.8`, ease unchanged
  - Score tier: < 70% → `interval = 1`, ease -= 0.2 (min 1.3)
  - Sets `last_random_call_date = now`, `last_rc_score = score_pct` (always overwritten)
  - Upserts into `StudentScenarioHistory`
- [x] Wire `_update_rc_history()` into `submit_narrative` and `skip_narrative` (gated on `session.session_type == "random_call"`)

### Tests
- [ ] Weighted selection: overdue items appear at 4× rate
- [ ] Weighted selection: never-played items appear at 2× rate
- [ ] SM-2 update: score ≥ 85% → interval grows, ease increases (capped at 3.0)
- [ ] SM-2 update: score 70–84% → interval × 1.8, ease unchanged
- [ ] SM-2 update: score < 70% → interval resets to 1, ease decreases (floor at 1.3)
- [ ] Upsert behavior: creates new record on first RC, updates on subsequent
- [ ] Anti-repeat window still applies after weighting

---

## Phase 1B — DMIST Primary Impression Field
**Parallel with Phase 1A. No dependencies on any other phase.**

### Design gate check
- [x] Deterministic authority: field is stored as-is; no adjudication
- [x] Trigger event: DMIST modal submit (`POST /api/sessions/{id}/dmist`)
- [x] Schema defined: nullable DB column (migration safety for existing rows); required on new API submissions
- [x] UI component strategy: required text input with validation gate inside existing DMIST modal
- [x] Priority assigned: Roadmap item 2

**Required vs. nullable clarification:** The DMIST impression field is required for all new submissions (LEARNING_DESIGN.md §7.3 Component 2: "explicit required field"). The DB column is nullable only to preserve historical rows that predate the feature. The API endpoint enforces the field as required — existing sessions without it remain readable; new submissions without it are rejected.

### Backend — models.py
- [x] Add `dmist_primary_impression: str | None` (nullable String) column to `SimSession` — nullable for migration safety only

### Backend — database.py
- [x] Add `ALTER TABLE sessions ADD COLUMN IF NOT EXISTS dmist_primary_impression TEXT` migration

### Backend — main.py
- [x] Update `DmistRequest`: add `primary_impression: str` (required — no default, no `None`)
- [x] Update `submit_dmist`: store `session.dmist_primary_impression = req.primary_impression.strip()`
- [x] Update `submit_dmist` validation: reject if `primary_impression` is empty after strip (422); also trim and reject empty `report` (422)
- [x] Made `TreatmentRequest.primary_impression` `Optional[str] = None`; removed placeholder strings from auto-submit payloads (turnover + drill flows)

### Backend — ai_client.py
- [x] In `_build_evidence_packet()`: include `dmist_primary_impression` from session as `impression_at_handoff` in the evidence packet return dict (informational — feeds LLM coaching, not hardened scoring)

### Frontend — static/index.html
- [x] Added required text input `id="dmist-primary-impression"` with label, required indicator, and inline error div above DMIST textarea

### Frontend — static/js/app.js
- [x] DMIST submit handler: validates `dmist-primary-impression` field (non-empty required), sends `primary_impression` in POST body
- [x] Reset function clears field and hides inline error on new session

### Tests
- [ ] Submit DMIST with valid impression → stored in `dmist_primary_impression`
- [ ] Submit DMIST with empty impression → 422 rejected (API enforcement)
- [ ] Frontend: empty impression field blocks submit and shows error
- [ ] Existing sessions without `dmist_primary_impression` remain readable (migration safety)
- [ ] Evidence packet includes `impression_at_handoff` when field is present

---

## Phase 2 — Debrief Structured Output Contract + BLUF Restructure + Next Action Routing
**Requires Phases 1A and 1B complete. Items 3 and 4 from roadmap — implemented together.**

### Design gate check
- [x] Deterministic authority: routing target computed by backend decision table; LLM generates phrasing only
- [x] Trigger event: debrief generation (existing debrief pipeline endpoint)
- [x] Schema defined: SCENARIO_EVALUATION_ARCHITECTURE.md §13 — full contract documented
- [x] UI component strategy: BLUF restructure of existing debrief modal; no new components
- [x] Priority assigned: Roadmap items 3 and 4

### Backend — main.py
- [x] Implement `_compute_reasoning_flags(evidence_packet, student_history)`:
  - `impression_challenge_result`: null (Phase 4 wires this)
  - `missed_critical_item`: enforce=True ceiling at 0, or required_assessments gaps → "clinical_performance"
  - `overdue_random_call`: most overdue scenario from StudentScenarioHistory
- [x] Implement `_compute_next_action_routing(evidence_packet, student_history, session, adapted_scenario)`:
  - Priority 1: enforce=True ceiling at 0 OR missed critical action → `("scenario", current_id)`
  - Priority 2: impression_challenge result == "incorrect" → `("scenario", current_id)` (Phase 4)
  - Priority 3: overdue RC scenario → `("random_call", overdue_id)`
  - Priority 4: lowest last_rc_score < 70% → `("random_call", low_score_id)`
  - Priority 5: mini-game mapping deferred (rubric_category_mapping registry not built)
  - Fallback: `("none", None)`
- [x] Routing computed post-EP (after evidence packet is available from LLM call); injected into _extras

### Backend — ai_client.py
- [x] Extended `_parse_debrief_response_payload` to return 4-tuple including `structured_extras` dict
- [x] Extended `evaluate_and_generate_debrief` signature: `routing_data` param; returns 5-tuple
- [x] Updated `_extract_debrief_payload` to handle 4-tuple parse result
- [x] Added `_routing_context_block` injected into prompt with pre-populated `next_action_target_type` and `next_action_target_id`
- [x] Extended RESPONSE FORMAT instruction: LLM must return `top_takeaways` (array), `reflection_prompts` (array), `next_action` (string)
- [x] `structured_extras` assembles LLM output + backend routing fields before return
- [x] `_generate_debrief_with_retry` updated to accept and forward `routing_data`

### Frontend — static/index.html
- [x] Layer 2: `debrief-takeaways-section` with `debrief-takeaways-list` — always visible when takeaways present
- [x] Layer 3: `debrief-full-section` — collapsible accordion wrapping existing `debrief-content` (starts collapsed), with `debrief-reflection-section` inside
- [x] Layer 4: `debrief-next-action-section` with text + conditional CTA button `btn-debrief-next-action`

### Frontend — static/js/app.js
- [x] `processDebrief` / `showDebrief` accept `blufData` param
- [x] Updated `skip_narrative` and `submit_narrative` callers to pass `blufData`
- [x] Layer 2: renders `topTakeaways` as `<li>` items in `debrief-takeaways-list`
- [x] Layer 3: collapse toggle bound on `btn-toggle-full-debrief` (guarded with `_blufBound` to prevent duplicate listeners); `reflection_prompts` rendered inside
- [x] Layer 4: `nextAction` text rendered; CTA button shown/hidden and wired to navigate by target type

### Tests
- [ ] `_compute_next_action_routing`: each priority level fires correctly
- [ ] Tie-break: highest rubric weight selected when multiple categories fail
- [ ] Fallback: `("none", None)` when no condition applies
- [ ] Mini-game rec: only fires when exact category mapping declared
- [ ] Debrief prompt: backend-populated fields present in prompt before LLM call
- [x] Response validation: missing `top_takeaways` or `reflection_prompts` → error
- [ ] BLUF layer ordering: Layer 1 and 4 present in DOM without user interaction
- [ ] Layer 3 collapsed by default; expands on click

---

## Phase 3 — Shared Challenge Modal Shell
**Requires Phase 2 complete. Builds before any new challenge type.**

### Design gate check
- [x] Deterministic authority: all challenge scoring is declared in scenario JSON, evaluated backend
- [x] Trigger event: varies per challenge — student explicit action; handled by shell contract
- [x] Schema defined: LEARNING_DESIGN.md §8.2 contract; 4 plugin types defined
- [x] UI component strategy: one shared shell, 4 pluggable renderers
- [x] Priority assigned: Roadmap item 6 (reordered before item 5)

**Challenge result authority:** `challenge_completed` SessionEvent is the single authoritative record. `_build_evidence_packet()` reads from SessionEvents — it does not write to or read from `evidence_packet` JSONB directly for challenge data. This keeps the evidence packet deterministically recomputable from session state and avoids an authority split between the event log and the stored packet.

### Backend — main.py
- [x] Add `POST /api/sessions/{id}/challenge-response` endpoint:
  - Accepts: `challenge_type`, `challenge_id`, `student_answer`
  - Validates answer against scenario-declared correct/acceptable arrays (read from adapted scenario)
  - Returns: `result` ("correct" | "acceptable" | "incorrect")
  - Emits `challenge_completed` SessionEvent (source: `backend_auto`) with full result payload: `challenge_type`, `challenge_id`, `student_answer`, `correct_answer`, `result`, `timestamp`
  - Does NOT write directly to `evidence_packet` JSONB
  - Does NOT pause the vitals engine
- [x] Add `challenge_results` section to `_build_evidence_packet()` — reads `challenge_completed` SessionEvents (source: `backend_auto`) and projects them into structured challenge result blocks

### Frontend — static/js/app.js
- [x] Build `_openChallengeModal(challengeType, challengeData, challengeId, onResult)`:
  - Renders shared shell: title bar, dismiss button, content area, submit button
  - Dismiss stores `result: "skipped"` via `__skipped__` sentinel to challenge-response endpoint
  - Vitals engine continues (modal open does not affect vitals WebSocket)
  - After submit: calls `onResult(result)` so scenario flow can react
- [x] Build `_renderSingleChoicePlugin(container, data)` → returns getAnswer() closure:
  - Renders `data.prompt` as question text; optional `data.image_url` above options
  - Renders `data.options` as radio button list (supports string or `{id, label}` objects)
  - Returns selected value on submit; null if nothing selected
- [x] Build `_renderNumericInputPlugin(container, data)` → returns getAnswer() closure:
  - Renders problem statement and optional `data.context` key-value table
  - Numeric input with optional `data.unit` label
  - Returns trimmed string value; null if empty
- [x] Build `_renderFreeTextPlugin(container, data)` → returns getAnswer() closure:
  - Renders prompt; textarea with 500-char limit
  - Returns trimmed text; null if empty
- [x] Scaffold `_renderSequencingPlugin(container, data)` → returns getAnswer() closure:
  - Renders shuffled steps; student assigns position numbers
  - Returns comma-joined ordered step-ID string; null if any step unassigned
  - No challenge type currently uses this plugin

### Frontend — static/index.html
- [x] Add shared challenge modal container (`id="modal-challenge"`) with shell structure

### Tests
- [ ] Shell dismiss → `result: "skipped"` written to evidence
- [ ] Single-choice plugin: correct answer → "correct"; acceptable → "acceptable"; other → "incorrect"
- [ ] Numeric plugin: within ±5% tolerance → "correct"
- [ ] Vitals engine not paused during challenge modal open
- [ ] `challenge_results` block populated in evidence packet

---

## Phase 4 — Primary Impression Challenge
**Requires Phase 3 (shared shell) complete. Requires target scenarios to have `phase: "primary_survey"` items.**

### Design gate check
- [x] Deterministic authority: correct/acceptable declared in scenario JSON, evaluated backend
- [x] Trigger event: `primary_survey_complete` milestone (SCENARIO_ENGINE_ARCHITECTURE.md §3.4)
- [x] Schema defined: LEARNING_DESIGN.md §7.3 Component 1 JSON contract
- [x] UI component strategy: shared shell + single-choice plugin (Phase 3)
- [x] Priority assigned: Roadmap item 5 (reordered after shell)

### Pre-build gate — scenario authoring
- [x] Audit all scenarios with `impression_challenge.enabled: true` targets
- [x] Verify each has at least one `scoring.required_assessments` item with `phase: "primary_survey"`
- [x] If missing: add `phase` field to relevant required_assessments items before build begins

### Backend — ai_client.py / scoring_service.py
- [x] Implement `primary_survey_complete` milestone detection:
  - After any SessionEvent write, check if all `phase: "primary_survey"` required_assessment items are satisfied
  - Authoritative path: `explicit_assessment` SessionEvents with matching keys (source: backend_auto or instructor_note)
  - Fallback: any `explicit_assessment` event + at least one vitals entry
  - On milestone fire: emit `milestone_fired` SessionEvent with `key: "primary_survey_complete"`
  - Idempotent: only fires once per session

### Backend — main.py
- [x] Add milestone check call after intervention/finding/assessment events that could complete primary survey
- [x] On `primary_survey_complete` milestone: if `scenario.impression_challenge.enabled`, push challenge to frontend
  - New SSE event type: `{"type": "challenge_available", "challenge_type": "impression", "challenge_data": {...}}`
  - Or: include in next AI response as structured flag
- [x] Wire impression challenge result into evidence packet:
  - `impression_challenge.student_answer`
  - `impression_challenge.correct`
  - `impression_challenge.acceptable`
  - `impression_challenge.result` ("correct" | "acceptable" | "incorrect" | "skipped")
  - `impression_challenge.timestamp_relative_to_first_intervention` (seconds)

### Frontend — static/js/app.js
- [x] Handle `challenge_available` event in SSE/websocket stream: call `_openChallengeModal("impression", challengeData, onResult)`
- [x] On challenge result: POST to `challenge-response` endpoint
- [x] Debrief three-way comparison: render early impression / final impression / correct impression table (Phase 2 BLUF Layer 3)

### Scenario JSON — target scenarios
- [x] Author `impression_challenge` block for initial set (suggest: `peds_asthma_01`, `peds_croup_01`, `peds_anaphylaxis_01`)
- [x] Validate distractors against authoring standard (LEARNING_DESIGN.md §7.3 Component 1)

### Backend — debrief contract consistency (cross-session fixes)
- [x] Persist BLUF fields (`top_takeaways`, `reflection_prompts`, `next_action`, `next_action_target_type`, `next_action_target_id`) to `session.narrative_data` in fresh narrative and skip paths so cached re-serves are authoritative without re-running the LLM
- [x] Cached narrative return path: read BLUF fields from `stored` (i.e., `session.narrative_data`)
- [x] Cached skip return path: same
- [x] Re-debrief path: persist and return fresh BLUF fields from `_extras` (re-debrief always re-runs LLM, so `_extras` is always fresh)
- [x] All debrief paths (narrative, skip, re-debrief, drill) now return `impression_challenge` and `dmist_primary_impression`; drill returns `None` for both (drill bypasses DMIST and milestone trigger)
- [x] Add `acceptable` field to `event_data` on `challenge_completed` SessionEvent (stored at challenge submission time) and to `impression_challenge_ep` in `_build_evidence_packet()` — closes contract gap with IMPLEMENTATION_PLAN.md §248
- [x] `_compute_reasoning_flags()`: read `impression_challenge_result` from `evidence_packet.impression_challenge.result` instead of hardcoded `None` — Priority 2 routing rule (incorrect impression → replay scenario) now fires correctly

### Frontend — debrief contract consistency (cross-session fixes)
- [x] `debriefEntry` stores full BLUF fields (`topTakeaways`, `reflectionPrompts`, `nextAction`, `nextActionTargetType`, `nextActionTargetId`) and Phase 4 impression fields (`impressionChallenge`, `dmistPrimaryImpression`)
- [x] `_openHistoryDebriefModal` renders Key Takeaways block and Reflection Prompts collapsible from stored entry fields
- [x] Drill debrief frontend caller now passes full `blufData` (with `null` impression fields) to `processDebrief`

### Tests
- [x] `primary_survey_complete` milestone fires when all phase items satisfied — `test_milestone_fires_with_intervention_and_three_messages` (gamification_regressions)
- [x] Milestone does not fire twice per session — `test_milestone_idempotent_already_fired`
- [x] Fallback path fires when no explicit phase items declared — intervention_proxy path covered by milestone tests (no phase items means fallback = intervention proxy, same logic)
- [x] Challenge result written to evidence packet with correct timestamp, including `acceptable` list — `TestImpressionChallengeEP` (test_evidence_packet)
- [x] Challenge skipped → `result: "skipped"` in evidence packet — `TestImpressionChallengeEP.test_skipped_result_in_ep`
- [ ] Three-way debrief comparison renders correctly for correct, acceptable, and incorrect answers — requires browser/JS test; not coverable by pytest
- [ ] Cached narrative re-serve returns BLUF fields from `narrative_data` — requires API integration test; not coverable by unit tests
- [ ] Re-debrief response includes BLUF fields — requires API integration test; not coverable by unit tests
- [ ] History debrief entry renders takeaways and reflection prompts — requires browser/JS test; not coverable by pytest

---

## Phase 5 — ECG / Rhythm Strip Challenge
**Requires Phase 3 (shared shell) complete. Phase 4 should be complete first (establishes milestone/challenge pipeline pattern).**

### Design gate check
- [x] Deterministic authority: correct answer declared in scenario JSON; no LLM evaluation
- [x] Trigger event: student requests ECG or 12-lead, or sends a message matching ECG request patterns
- [x] Schema defined: LEARNING_DESIGN.md §8.3
- [x] UI component strategy: shared shell + single-choice plugin (image variant)
- [x] Priority assigned: Roadmap item 7
- [ ] Static asset hosting plan confirmed: ECG strip images served from `/static/img/ecg/`
- [ ] At least one target scenario identified with `ecg_challenge` block authored

### Backend — main.py
- [ ] Add ECG trigger detection in the chat endpoint: after AI message is saved, check if the student message or last bot turn contains an ECG request (regex patterns: "run a strip", "12-lead", "ECG", "rhythm", "EKG") AND `scenario.ecg_challenge.enabled == true` AND no `ecg_challenge` SessionEvent yet for this session
- [ ] On trigger: emit `challenge_available` SSE event with `challenge_type: "ecg"` and `challenge_data` from `scenario.ecg_challenge` (excluding `post_treatment` variant until its trigger condition is met)
- [ ] Post-treatment variant: if `ecg_challenge.post_treatment.requires_intervention_id` has been applied (check session interventions), serve the post-treatment `image_url` and `correct` instead of the initial block on subsequent ECG requests
- [ ] `challenge-response` endpoint already handles `ecg` type via `_evaluate_challenge_answer`; verify `ecg_challenge` block structure is compatible with existing evaluator
- [ ] Add `ecg_challenge` to `_CHALLENGE_TYPES` set

### Backend — ai_client.py
- [ ] Add `ecg_challenge` block to `_build_evidence_packet()` challenge_results section: reads `challenge_completed` SessionEvents where `challenge_type == "ecg"`, populates `{ student_answer, correct, result, image_url, timestamp_relative_to_first_intervention }`

### Frontend — static/js/app.js
- [ ] SSE handling: when `challenge_available.challenge_type == "ecg"`, call `_openChallengeModal("ecg", challengeData, challengeId, onResult)`
- [ ] `_renderSingleChoicePlugin` must support an optional image above the option list: if `challengeData.image_url` is present, inject `<img src="..." class="w-full rounded mb-3">` before the options
- [ ] On submit: POST to `challenge-response` with `challenge_type: "ecg"`
- [ ] Post-treatment re-challenge: if a second `challenge_available` event fires with `challenge_id: "post_treatment"`, show fresh modal with new image and options

### Scenario JSON
- [ ] Author `ecg_challenge` block for `adult_acs_01_stemi` (initial strip: rate-dependent, rhythm visible) with post-treatment variant after aspirin/nitro
- [ ] Validate option list against LEARNING_DESIGN.md §8.3 authoring standard (3–4 options; plausible distractors; correct answer matches `ecg_challenge.correct`)
- [ ] Static ECG strip images added to `/static/img/ecg/` with stable filename conventions

### Tests
- [ ] ECG trigger fires when student message matches regex AND `ecg_challenge.enabled`
- [ ] ECG trigger does not fire a second time if challenge already completed (idempotent)
- [ ] Post-treatment variant serves only after `requires_intervention_id` applied
- [ ] `ecg_challenge` block present in evidence packet after completion
- [ ] Challenge skipped → `result: "skipped"` recorded
- [ ] Image URL included in evidence packet

---

## Phase 6 — Medication Math Challenge
**Requires Phase 3 (shared shell) complete. High priority for pediatric scenarios.**

### Design gate check
- [x] Deterministic authority: backend computes `correct_volume` from scenario data; ±`tolerance_pct`% comparison; no LLM involvement
- [x] Trigger event: student selects an intervention whose ID matches `med_math_challenge.triggered_by_intervention_id`
- [x] Schema defined: LEARNING_DESIGN.md §8.3
- [x] UI component strategy: shared shell + numeric-input plugin
- [x] Priority assigned: Roadmap item 8
- [ ] Patient weight sourcing confirmed: drawn from `scenario.patient.weight_kg`; challenge must not fire if field absent

### Backend — main.py
- [ ] Add med-math trigger hook in the intervention-application path (wherever the student's intervention selection is processed): check if the applied intervention ID matches `scenario.med_math_challenge.triggered_by_intervention_id` AND `med_math_challenge.enabled` AND no `med_math_challenge` SessionEvent yet
- [ ] On trigger: read `patient.weight_kg` from session (or scenario); if absent, log a warning and skip (do not block intervention logging)
- [ ] Compute `correct_volume = (weight_kg × dose_per_kg) / concentration_mg_per_ml` and attach to `challenge_data` sent to frontend
- [ ] Emit `challenge_available` SSE event with `challenge_type: "med_math"`, `challenge_data` including `drug_name`, `weight_kg`, `dose_per_kg`, `concentration_mg_per_ml`, `unit`, `tolerance_pct`
- [ ] **Critical ordering:** the intervention is logged and the session state is updated AFTER the challenge is emitted; the challenge fires before the intervention registers in the timeline so the student cannot work backward from "intervention applied" confirmation
- [ ] `challenge-response` endpoint: when `challenge_type == "med_math"`, `_evaluate_challenge_answer` performs numeric comparison: `abs(student_float - correct_float) / correct_float ≤ tolerance_pct / 100`; `correct_volume` is re-computed server-side from scenario data — not trusted from client
- [ ] Add `med_math` to `_CHALLENGE_TYPES` set

### Backend — ai_client.py
- [ ] Add `med_math_challenge` block to `_build_evidence_packet()`: `{ triggered_by_intervention_id, patient_weight_kg, student_answer, correct_answer, within_tolerance, result, timestamp_relative_to_first_intervention }`

### Frontend — static/js/app.js
- [ ] SSE handling: when `challenge_available.challenge_type == "med_math"`, call `_openChallengeModal("med_math", challengeData, challengeId, onResult)`
- [ ] `_renderNumericInputPlugin` must render: drug name, patient weight with unit, dose/kg, concentration, unit label on input field
- [ ] Accept decimal input; validate numeric before submit; do not round client-side (backend validates)
- [ ] On submit: POST with `challenge_type: "med_math"`, `student_answer` as string representation of entered number

### Scenario JSON
- [ ] Author `med_math_challenge` blocks for weight-based pediatric medications in at least: `peds_anaphylaxis_01` (epinephrine IM), `peds_asthma_01` (albuterol or epinephrine depending on severity)
- [ ] Confirm `patient.weight_kg` is present in target scenario patient records
- [ ] Set `tolerance_pct: 5` (default) unless clinical reason for tighter tolerance

### Tests
- [ ] Trigger fires when matching intervention selected AND `enabled`
- [ ] Trigger does not fire if `patient.weight_kg` absent (logs warning; intervention still logged)
- [ ] Trigger does not fire twice for the same challenge ID (idempotent)
- [ ] Correct calculation within tolerance → `"correct"`; outside → `"incorrect"`
- [ ] `correct_volume` computed server-side — client-supplied value not trusted
- [ ] Intervention is logged in session timeline after challenge, regardless of result
- [ ] Evidence packet includes `patient_weight_kg`, `student_answer`, `correct_answer`, `within_tolerance`, `result`

---

## Phase 7 — Capnography Interpretation Challenge
**Requires Phase 3 (shared shell) complete. ALS-primary — trigger only for ALS provider levels or ALS-capable agencies.**

### Design gate check
- [x] Deterministic authority: correct interpretation declared in scenario JSON; no LLM involvement
- [x] Trigger event: student requests ETCO2, end-tidal, or capnography
- [x] Schema defined: LEARNING_DESIGN.md §8.3
- [x] UI component strategy: shared shell + single-choice plugin (waveform image + ETCO2 value variant)
- [x] Priority assigned: Roadmap item 9
- [ ] Scope enforcement confirmed: challenge fires only when provider level is ALS or MCA expansion permits capnography; BLS students do not see capnography challenges
- [ ] Static asset hosting plan confirmed: waveform images served from `/static/img/capnography/`

### Backend — main.py
- [ ] Add capnography trigger detection in chat endpoint: after AI message saved, check if student message matches capnography request patterns ("ETCO2", "end-tidal", "capnography", "waveform") AND `scenario.capnography_challenge.enabled` AND provider level is ALS (or MCA expansion permits) AND no `capnography_challenge` SessionEvent yet
- [ ] On trigger: emit `challenge_available` SSE event with `challenge_type: "capnography"`, `challenge_data` from `scenario.capnography_challenge` (`waveform_image`, `etco2_value`, `options`, `correct`)
- [ ] `challenge-response` endpoint: `capnography` type handled by existing string-comparison evaluator via `_evaluate_challenge_answer`
- [ ] Add `capnography` to `_CHALLENGE_TYPES` set

### Backend — ai_client.py
- [ ] Add `capnography_challenge` block to `_build_evidence_packet()`: `{ student_answer, correct, etco2_value, result, timestamp_relative_to_first_intervention }`

### Frontend — static/js/app.js
- [ ] SSE handling: `challenge_type == "capnography"` → `_openChallengeModal("capnography", challengeData, challengeId, onResult)`
- [ ] `_renderSingleChoicePlugin` already supports images; confirm `waveform_image` renders above options; add `etco2_value` display (e.g., "ETCO₂: 28 mmHg") between image and options
- [ ] On submit: POST with `challenge_type: "capnography"`

### Scenario JSON
- [ ] Author `capnography_challenge` blocks for ALS respiratory scenarios with abnormal waveforms: target `peds_asthma_01` (bronchospasm / shark fin), adult STEMI or cardiac arrest variant (low ETCO2 during compressions)
- [ ] Waveform images added to `/static/img/capnography/` with stable filename conventions
- [ ] Option list drawn from standard interpretation set (LEARNING_DESIGN.md §8.3)

### Tests
- [ ] Challenge fires on capnography request AND ALS provider level
- [ ] Challenge does not fire for BLS-only students
- [ ] Challenge does not fire twice per session (idempotent)
- [ ] Waveform image URL and ETCO2 value present in `challenge_data` SSE payload
- [ ] Evidence packet populated with `etco2_value` and `result`
- [ ] Challenge skipped → `"skipped"` recorded

---

## Out of Scope for This Plan

- **Remove Team Challenges from Generic Agencies** (PUNCHLIST.md line 170) — separate feature, no dependency on learning system. Track separately; implement when touching team/agency authorization code.
- **Treat Management economy changes** (PUNCHLIST.md) — backend-only, no dependency on this plan. Can be scheduled independently.
- **Confidence calibration** (LEARNING_DESIGN.md §5) — deferred; no design gates passed yet.
- **Random Call scenario variation** (patient name/image surface changes) — deferred decision; does not block SM-2 algorithm.

---

## Cross-Phase Checklist

Before declaring any phase complete:
- [ ] All phase-specific tests pass
- [ ] `node --check static/js/app.js` passes (no syntax errors)
- [ ] Full test suite passes (`pytest`)
- [ ] Relevant design doc updated to reflect implementation status
- [ ] PUNCHLIST.md roadmap table status column updated
