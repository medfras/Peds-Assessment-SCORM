# Scoring Hardening Roadmap

**Purpose:** Navigation document for remaining scoring architecture work. Tracks what's done, what's in flight, and what must complete before catalog expansion is safe at each scale threshold.

**Detail lives in:** `docs/SCORING_IMPROVEMENT_PLAN.md`, `docs/SCORING_ENGINE_ARCHITECTURE.md`

---

## Current State (as of 2026-05-19)

| Area | Status |
|---|---|
| Calibration fixtures 1–15 | ✅ Complete |
| Group A — debrief validation, subscore ranges | ✅ Complete |
| Group B — EVALUATE elimination | ✅ Complete |
| Group C1/C2 — corroboration prepass | ✅ Complete |
| Group C3 — deterministic corroboration shadow | ✅ Wired; flip pending staging validation |
| Group F — NASEMSO call-type rubric | ✅ Complete — all runs done, overlays authored, semantic migration complete |
| Tier 2 CI gate | ✅ 515 tests passing (scenario_contracts + rubric_smoke + tier2_matchers + scoring_service + rubric_loader + debrief_renderer + timeline_scoring_deference) |
| Rubric smoke harness | ✅ Wired; grows automatically as new scenarios are authored |
| Group E — deterministic debrief renderer | ✅ E1–E4 complete; calibration validated on peds_asthma_01 and peds_croup_01 |
| Timeline/scoring unification | ✅ Complete — _build_session_timeline() defers to checklist_states.item_states for STATUS; 9 regression tests in CI |
| Scoring globalization pass — DMIST policy drift | ✅ Complete — see decision record below |
| Tier 1 expansion (AVPU, history) | ❌ Not started |
| Group D — QA/QI readiness | ❌ Deferred |

**What "catalog expansion safe" means now:** New scenario items with `tier1_match` are smoke-tested on commit. New Tier 2 items require positive/negative samples or CI fails. Rubric misconfiguration is caught before a browser session. Scoring engine adjudication is deterministic. These are the gates that matter most for early expansion.

---

## Scoring Globalization Pass — Decision Record (2026-05-19)

**What was done:** Two passes eliminated scenario JSON from re-authoring global scoring policy.

**Pass 1 — `overall_considerations` / `narrative_considerations` boilerplate:**
Removed repeated policy strings from 12 scenarios (ALS co-dispatch rules, PAT acronym policy, CHART format, vital fabrication rules). CI gate added to `test_scenario_contracts.py`.

**Pass 2 — DMIST component drift:**
- `dmist_components.I` re-authored as interventions: fixed in 10 scenarios; CI gate rejects via `_is_legacy_intervention_i_config()`.
- `dmist_components.*.scoring_note` containing grading formulas ("Award X/Y if," "fabricates"): fixed in 9 scenarios; CI gate added.
- `dmist_components.T.required_elements` containing bare "ALS readiness": removed from 6 scenarios + fixed incorrect "transported to ED" in NAT scenario; CI gate added.
- `_run_documentation_extraction` in `ai_client.py` now receives `turnover_target` and generates a dynamic T rule (ALS handoff / direct hospital transport / scene-close) instead of a static "For ALS turnover:" clause.
- Canonical DMIST model (D/M/I/S/T definitions, authoring errors, corroboration_source rules) documented in `docs/SCENARIO_DESIGN_EMS.md`.

**Decision — acceptable repetition vs. prohibited drift:**
Structural repetition across scenario files is acceptable when content is clinically contextual (specific to this call type, this patient, or this intervention). It is prohibited when it re-authors global engine policy. The canonical boundary:
- `scope_no_iv_io*` checklist items: **leave as-is** — feedback names the specific BLS alternative for each call; the repetition is clinical, not policy drift.
- `by_level` scope prose that restates EMT/AEMT scope rules without scenario-specific context: **minor hygiene**, worth a future lint if volume grows, not blocking.
- Reusable call-type checklist extraction (e.g., BGL check for all AMS scenarios): **engine-layer work** — belongs in the scoring engine roadmap (call-type rubric layer), not in a cleanup pass.

**See also:** `docs/SCENARIO_DESIGN_EMS.md` § "Acceptable repetition vs. prohibited drift" for the authoring-level rule.

---

## Phase 1 — Finish In-Flight Work
**Threshold: complete before adding more than 5 new scenarios**

These are items that are started and will create merge conflicts or confusion if left open.

### F: NASEMSO Rubric Active Run Cleanup

- [x] **Run 2: `peds_croup_01`** — overlay created (`app/scenarios/overlays/peds_croup_01.json`); suppresses `scene_safety_ppe` and `als_request_if_severe`; Call Specific items scored correctly in live run
- [x] **Run 3: `peds_asthma_01`** — full playthrough complete. Overlay suppresses `scene_safety_ppe` and `general_impression`. Bugs found and fixed: (1) second lung-sound challenge was not transitioning to post-albuterol config — fixed in `_lungSoundConfigForCurrentState()` in `app.js` to key off `state.interventionsApplied` rather than treatment labels; (2) `resp_distress.o2_therapy_indicated` in NASEMSO rubric updated so albuterol_svn counts as Tier 1 alternative for O2 when SVN is the delivery method (O2-driven at 6 LPM). Protocol interpretation lives in the NASEMSO rubric — not hardcoded in scenario JSON
- [x] **`als_request_if_indicated` decision** — resolved: ALS-request rubric items use `applicable_if: { "als_codispatched": false }`, with `als_codispatched` derived from the active agency configuration during scenario adaptation. Do not suppress these items in scenario overlays.
- [x] **Semantic duplicate migration** — `peds_diabetic_emergency_01`: BGL check, swallow assessment, and oral glucose are now owned by the NASEMSO hypoglycemia call-type rubric. Removed duplicate scenario checklist items and unsuppressed the corresponding call-type items.

### Incomplete Draft Scenarios

- [x] **`peds_trauma_07_head_injury`** — protocol file authored: `app/protocols/MI/02_Trauma_Environmental/02-3_head_spine_trauma.json`
- [x] **`peds_trauma_08_nat`** — protocol file authored: `app/protocols/MI/02_Trauma_Environmental/02-9_child_abuse_mandatory_reporting.json`

### CI Wiring

- [x] **`test_rubric_smoke.py` in CI** — `.github/workflows/tests.yml` created; runs `test_rubric_smoke.py`, `test_tier2_matchers.py`, `test_scoring_service.py`, and `test_rubric_loader.py` on every push and PR

---

## Phase 2 — Deterministic Corroboration Flip
**Threshold: when 20 staging/pilot runs have accumulated**

This retires the LLM prepass for documentation checking and closes SCORE-01. It's gate-driven, not time-driven.

- [ ] **Accumulate 20 staging runs** — any scenario, any student, with `shadow_deterministic_corroboration=true` already active
- [ ] **Review shadow comparison logs** — check that deterministic prepass agreement rate is high; investigate any systematic disagreements before flipping. Log field: `shadow_corroboration_agreement` in structured session logs
- [ ] **Flip flag**: `use_deterministic_corroboration = True` in `app/config.py`
- [ ] **Retire LLM prepass function** — remove or gate with `use_deterministic_corroboration` check; do not leave both active simultaneously
- [ ] **C4 regression** — rerun all 15 calibration fixtures, confirm no score changes
- [ ] **Close SCORE-01** in `docs/SAAS_HARDENING_PLAN.md`

---

## Phase 3 — Deterministic Debrief Renderer (Group E)
**Threshold: complete before 20 scenarios or before institutional use**

This is the highest-leverage remaining structural fix. Currently the LLM writes the Clinical Performance and Protocols sections, which means:
- Identical adjudicated scores can produce different explanatory text across runs
- The LLM can mis-attribute gaps (assessment miss labeled as protocol deduction)
- The LLM can mention missed items in a way that implies partial credit

Group E renders those sections from adjudicated item states and authored per-item metadata. The LLM scope narrows to coaching-only prose (what went well, key takeaways, reflection).

### E1 — Feedback Metadata Schema

- [x] Add to `ChecklistItem` in `app/checklist.py`: `done_feedback: str`, `missed_feedback: str`, `clinical_rationale: str | None`, `common_error: str | None` — all `Optional`, default `None`; backward-compatible with all existing scenario JSON
- [x] Add soft validation warning in `validate_scenario()` when required scenario-authored items are missing `done_feedback`/`missed_feedback`; skips base rubric items and debrief_exempt scenarios; not a hard error until renderer is active
- [x] Update `docs/SCENARIO_DESIGN_EMS.md` authoring guide — new "Debrief feedback metadata" section with field table, authoring rules, and full example item

### E2 — Author Metadata for All 17 Scenarios

- [x] All 19 scenarios — 113 required scenario-authored checklist items authored with `done_feedback`, `missed_feedback`, `clinical_rationale`, and `common_error`; applied via patch script; 551 CI tests passing with no regressions

### E3 — Section Renderer

- [x] Implement `_compose_scored_section()` in `app/ai_client.py` — renders per-item credited/missed/partial blocks from adjudicated item states using authored `done_feedback`/`missed_feedback`/`clinical_rationale`/`common_error`; falls back to description when metadata absent
- [x] Implement `_compose_reference_section()` for condition/treatment content — renders from `debrief.condition_background`, `key_teaching_points`, `common_mistakes`; returns clean student-facing markdown
- [x] **Placeholder injection architecture** — calibration run revealed "present verbatim" instruction fails (LLM rewrites content and leaked `[BACKEND-RENDERED]` markers into output). Fix: LLM outputs sentinel strings (`{{SECTION1_CLINICAL_PERFORMANCE}}`, `{{SECTION2_PROTOCOLS_TREATMENT}}`, `{{CONDITION_TREATMENT_REFERENCE}}`); post-processing replaces them with actual rendered content. Rendered content never goes through the LLM. Fallback: prepend-to-header if LLM drops placeholder (logged at WARNING).
- [x] Unit tests: 20 tests covering all-credited, all-missed, mixed partial, missing metadata fallback, not-applicable exclusion, wrong-category exclusion, empty-state edge cases, protocols_treatment category, score-line-ends-output, output-ends-with-authored-content — in `tests/test_debrief_renderer.py`; 571 CI tests passing
- [x] **Calibration fixtures validated** — `peds_asthma_01` and `peds_croup_01` live runs completed. Three bugs found and fixed: (1) `_rubric_item_to_checklist_item()` in `rubric_loader.py` was dropping `done_feedback`/`missed_feedback` from NASEMSO rubric items; (2) Treatment Reference sub-section was repeating condition background instead of writing protocol prose; (3) `**` bold markers in `_compose_reference_section()` subsection labels collided with section heading markers, producing `Female/Male********` artifact — fixed by removing `**` from plain-text labels.

### E4 — Narrow LLM to Coaching Scope

- [x] Debrief prompt rewritten for coaching-only scope: added `_coaching_scope_note` block (when renderer active) clarifying LLM role is coaching presenter; `_key_takeaways_block` updated to lead from pre-rendered gap content and connect to authored teaching points
- [x] Evidence packet annotated: `_evidence_packet_context` prepends "RENDERED SECTIONS ACTIVE — use for coaching context only" header to gap lists when renderer is active; raw lists remain for Scope/DMIST/Key Takeaways context
- [x] **Retired `_sanitize_protocol_treatment_section()`** — verified croup `scope_no_albuterol.common_error` covers racepinephrine framing; function and all four associated regex constants removed; `_sanitize_credited_item_contradictions()` remains active
- [x] `docs/AI_ARCHITECTURE.md §8` (new section) documents current LLM scope: what the LLM generates, what it does not do, pre-rendered content architecture, and retired guards
- [x] **Calibration fixtures re-validated** — `peds_asthma_01` and `peds_croup_01` runs confirmed: condition background duplication resolved; NASEMSO rubric `done_feedback`/`missed_feedback` propagating correctly; treatment reference section writes protocol prose only

---

## Phase 4 — Structural Consistency Improvements
**Threshold: parallelizable with catalog expansion; prioritize before 30 scenarios**

These address known inconsistency sources that Phase 3 does not fully cover.

### Timeline/Scoring Unification

The session timeline in `app/main.py` and the scoring engine in `app/scoring_service.py` currently derive evidence independently. When source restrictions are added to scoring, the timeline must be manually updated to match (we already saw this with the lung-sounds bug).

- [x] `_build_session_timeline()` defers to `checklist_states.item_states` for STATUS (applied/missed) when scoring engine has adjudicated an item — critical actions, recommended actions, and lung-sound row all check `_item_state_value()` first
- [ ] Remove independent `_first_lung_sound_time()` and analogous helpers — timeline rows driven from adjudicated item timestamps instead (TIMESTAMP still derives from findings; full replacement deferred)
- [x] Regression tests: 9 tests in `test_timeline_scoring_deference.py` covering recommended-action deference, critical-action deference, and lung-sound deference; wired in CI

### Tier 1 Expansion — High-Value Items

Items that currently rely on Tier 2 transcript matching for high-stakes clinical decisions. Each structured UI interaction added here eliminates a class of "typed the right words but didn't do it" false credit.

- [x] **AVPU** — `avpu_quick_action` UI stamp wired; backend finding stored with `source="avpu_quick_action"`; existing `ems.medical.loc` item updated with `require_source=True`
- [x] **History items** (allergies, medications, PMH, last oral, events) — `ems.medical.sample_*` items now have tier1_match on `finding_type="history"` key patterns matching AI-tagged SAMPLE history findings; name/DOB were already tier1; tier2 patterns remain as fallback
- [x] **Epiglottitis/differential screen** — `peds_croup_01.croup_recognition` credits via `challenge_completed` session event with `event_data_result="correct"`; fully covered by `test_scoring_service.py` and `test_adjudication_gold_standard.py`; CI validated

---

## Phase 5 — QA/QI Readiness (Group D)
**Threshold: required before institutional/clinical review use; not required for training platform**

All scoring items must be Tier 1 or Tier 2 before scores can be used in clinical performance reviews. This is a separate standard from the training platform threshold above.

- [ ] **Professionalism checklist expansion** — current: PPE ceiling deterministic, communication LLM-holistic. Target: all observable professionalism behaviors as Tier 1/Tier 2 items (greeting, consent language, empathy, scene management)
- [ ] **Transport documentation items** — destination communicated, pre-arrival report delivered, ALS handoff content
- [ ] **Full Tier 2 coverage audit** — for every item in every scenario: if Tier 2 is the only path, it must have positive/negative samples and a documented rationale for why Tier 1 is not yet achievable
- [ ] **Ambiguity rate monitoring** — wire `ambiguous` adjudication outcomes to structured metrics; items with persistently high `ambiguous` rates flagged for Tier 2 expansion
- [ ] **QA/QI deployment gate review** — review `docs/QAQI_READINESS.md` and confirm all items are addressed before enabling QA/QI mode for any agency

---

## Authoring Checklist for New Scenarios

Use this when adding any new scenario to the catalog.

**Before authoring:**
- [ ] Does the scenario's call type have a NASEMSO rubric file? If not, run without `call_type` field or author one
- [ ] Are all referenced protocol files present in `app/protocols/`?
- [ ] Does the scenario have all required `debrief` sub-fields: `condition_background`, `key_teaching_points`, `common_mistakes`?

**After authoring JSON:**
- [ ] Run `venv/bin/python -m pytest tests/test_rubric_smoke.py tests/test_tier2_matchers.py -q` — must pass 0 failures
- [ ] Run `venv/bin/python -c "from app.scenario_engine import load_scenario; load_scenario('your_id')"` — must load without error
- [ ] Run `venv/bin/python -c "from app.scenarios.vocabulary import validate_scenario; from app.scenario_engine import load_scenario; print(validate_scenario(load_scenario('your_id')))"` — must return empty list
- [ ] If `call_type` is set: run shadow composition validation (`scripts/validate_shadow_composition.py`) and check for unexpected duplicates
- [ ] At least one full playthrough with rubric review — confirm all expected checklist items show ✅ when student performs the expected actions

**For Tier 2 items specifically:**
- [ ] Every item with `tier2_patterns` must have positive and negative samples in `tests/test_tier2_matchers.py` — CI will catch this if missed

**For call-type rubric items specifically:**
- [ ] Author `done_feedback` and `missed_feedback` on every rubric item (required by schema)
- [ ] Run active composition validation to check for structural duplicates with scenario JSON items
- [ ] Create overlay file if duplicates found

---

## What Remains Manually Verified (Structural Limits)

Even with all phases complete, these require a human run to validate:

| Item | Why manual | Mitigation |
|---|---|---|
| Debrief prose quality | LLM output is non-deterministic until Phase 3 complete | Calibration fixtures; Phase 3 makes this deterministic |
| Lexi hint relevance | Hint selection is LLM-driven; no structured output to test | Author `lexi_guardrails` and review one session per scenario |
| Edge-case vitals presentation | TTS and chat formatting depend on authored values | One playthrough per new scenario |
| Clinical accuracy of scenario content | Content correctness is out of scope for CI | Protocol review before publishing |
