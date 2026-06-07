# SCORM Pilot Readiness Checklist

This checklist defines when the Station 1 Pediatric Assessment Training module is ready to branch into a standalone package repo.

It is a pilot gate, not a full SaaS launch gate. The goal is to preserve the clinical/scoring architecture while narrowing the product surface enough to test scenarios, drills, map progression, and LMS behavior safely.

**Deployment target:** Moodle Cloud (2026-05-17)
**Topology:** Production Station 1 + pediatric Map 0/PM1/PT1/CPR pilot nodes, mirrored through 16-node SCORM suspend data
**Last updated:** 2026-06-06

**Bleed-over rule:** No SCORM-specific configuration (hardcoded agency/protocol, trimmed UI, free API keys, guardrails, navigation overrides) is introduced into this repo. All of that lives exclusively in the SCORM branch. Changes in this repo must remain safe for the main program.

## 1. Branch Gate

The branch gate is intentionally narrow. Do not branch until these items are true. Everything else (trimmed UI, SCORM adapters, API guardrails, map art, packaging, staging-run calibration) is in-branch build work, not a branch prerequisite.

### Pre-branch gate (3 items)

- [x] **Deployment target chosen** — Moodle Cloud (2026-05-17)

- [x] **Pilot scenario validation baseline complete** — Recent main-app/manual validation covered the priority pilot scenarios and the final current-run checks for febrile seizure, anaphylaxis, extremity fracture, and head injury. This does not replace SCORM package-path validation.

- [x] **PAT SCORM vertical slice works** — The contract proof. Flow: SCORM launch → scoped auth/JWT → PAT drill result submitted → backend attempt summary returned → `cmi.suspend_data` written → map unlock/progression state correct. Verified in MoodleCloud smoke run on 2026-06-06: `drill_pat` submitted with `unlocks.scenarios = false`, `drill_dev` submitted with `unlocks.scenarios = true`, refresh returned persisted state, and `LMSFinish` was called.

### Architecture gates (already satisfied — do not re-open)

- [x] Standards target fixed: Moodle Cloud native SCORM 1.2 only; no SCORM 2004, xAPI, or SCORM Cloud/Rustici plugin dependency
- [x] Stable node IDs final in `04_SCENARIO_AUTHORING.md` and `02_MAP_TOPOLOGY.md`
- [x] Scoring contract matrix complete for every required node
- [x] SCORM attempt topology implemented: `unlocks.scenarios` (pilot gate) + `unlocks.map3` (2 PM1 + 2 PT1 gate CPR), while learner UI reuses the production Station 1 and pediatric map surfaces
- [x] SCORM pass challenge gate implemented: 2 PM1 + 2 PT1 passing/on-track scenarios + ≥3600 s training time from orientation/scenarios/drills
- [x] `_SUSPEND_DATA_VERSION = 3` with 16-node shape and CE block
- [x] `scorm.js finish()` corrected: gates on `peds_ce_challenge.complete`, writes `"incomplete"` not `"failed"` for in-progress learners
- [x] Scoring engine hardened:
  - [x] Professionalism subscore variance resolved (2026-05-15)
  - [x] Tier 3 scoring stub: zero production impact; deferred to Phase 7+
  - [x] Key Takeaways hallucination fixed (2026-05-15)
  - [x] Deterministic baseline vitals split from AVPU/LOC (2026-05-17)
  - [x] Neuro assessment package requires formal GCS + LOC + vomiting history (2026-05-17)
  - [x] `als_codispatched` applicability flag implemented (2026-05-17)
  - [x] `\bmedic\b` word-boundary false-positive fixed (2026-05-17)
  - [x] Case Summary vital fabrication guard added (2026-05-17)
  - [x] DMIST scoring globalization pass complete (2026-05-19): scoring_note grading formulas removed from all 9 affected scenarios; T component ALS handoff derived from `turnover_target` in engine; bare "ALS readiness" removed from 7 scenario `required_elements`; 3 CI gates added; 2309 tests pass
  - [x] Gold standard adjudication fixtures added for `peds_trauma_07_head_injury` and `peds_cardiac_arrest_01_bls` (2026-05-19) — all 10 pilot scenarios now have CI-enforced adjudication coverage
- [x] SCORM auth contract final: `POST /api/scorm/auth` shape, JWT scoping, attempt-scoped token, untrusted LMS identity
- [x] Backend attempt summary shape defined: node scores, dual unlock keys, CE challenge block, final grade
- [x] `cmi.suspend_data` v3 mirror shape confirmed under 4,096 characters with all 16 nodes and CE block
- [x] Scenario scoring contract independent of frontend-only tags

### Deferred to in-branch (do not block branch creation)

These items are build work, not pre-branch gates. See Section 10 for the full sequenced build checklist.

- [ ] DMIST calibration validated on live session data (needs 20 staging runs)
- [ ] 20 staging runs with shadow corroboration; `USE_DETERMINISTIC_CORROBORATION=True` flip pending
- [ ] SCORM-specific config: hardcoded PFD/Kent County provisioning, LMS launch -> production Station 1 orientation or last pediatric map, Moodle-account history/storage policy, free API guardrails — **all in SCORM branch only**
- [ ] Optional TTS gated: `TTS_PROVIDER=browser` default; toggle off sends no paid provider calls; TTS failures do not block scenario completion
- [ ] AI provider failures return safe `provider_error` frontend diagnostic (already implemented in main app; verify SCORM token path also returns it)
- [ ] All 16 nodes wired through `_onScormNodeComplete` and validated in package path
- [ ] Confirm SCORM package reuses production Station 1, Map 0, PM1, and PT1 art/node positioning exactly
- [ ] SCORM packaging, tiny MoodleCloud SCO same-origin smoke test, Moodle Cloud upload

---

## 2. Scoring Contract Matrix

**Phase 1 status:** Updated 2026-05-17 to reflect 4-map 16-node topology.

### 2.1 Shared Result Envelope

Every node reports through the same backend attempt-summary contract. Drills may calculate the initial score client-side, but the backend stores the result, resolves the weighted grade, and returns the canonical state.

Drill/minigame result submitted to backend:
```json
{
  "node_id": "drill_pat",
  "activity_type": "minigame",
  "score": 87,
  "completed": true,
  "passed": true,
  "mistake_tags": ["missed_work_of_breathing"]
}
```

Scenario result submitted to backend:
```json
{
  "node_id": "scen_head",
  "activity_type": "scenario",
  "scenario_id": "peds_trauma_07_head_injury",
  "session_id": "session_uuid",
  "score": 86,
  "completed": true,
  "passed": true,
  "score_snapshot": {},
  "evidence_packet_id": "session_uuid"
}
```

Backend attempt summary response (condensed — all 16 node scores present):
```json
{
  "attempt_id": "scorm_pfd_2026_000001",
  "node_scores": {
    "drill_pat": 87, "drill_dev": 0, "drill_gcs": 0,
    "scen_asthma": 0, "scen_croup": 0, "scen_diabetes": 0, "scen_seizure": 0,
    "scen_airway": 0, "scen_anaph": 0, "scen_bleeding": 0, "scen_head": 86, "scen_laceration": 0,
    "scen_cpr": 0,
    "game_bls": 0, "game_lung_sounds": 0, "game_vitals": 0
  },
  "node_completed": {
    "drill_pat": true, "drill_dev": false, ...
  },
  "unlocks": {
    "scenarios": false,
    "map3": false
  },
  "drill_grade": 43.5,
  "scenario_avg": null,
  "final_score": null,
  "lesson_status": "incomplete",
  "peds_ce_challenge": {
    "complete": false,
    "ce_seconds": 0,
    "pm1_completed": 0, "pm1_required": 2,
    "pt1_completed": 0, "pt1_required": 2,
    "cpr_done": false,
    "optional_games_completed": 0, "optional_games_required": 2
  }
}
```

### 2.2 Completion and Grade Rules

**Map unlock chain:**

| Gate | Condition |
|------|-----------|
| PM1 + PT1 unlock | `drill_pat` AND `drill_dev` both `completed=true` → `unlocks.scenarios = true` |
| Map 3 (CPR) unlock | PM1 ≥ 2 completed AND PT1 ≥ 2 completed → `unlocks.map3 = true` |
| LMS `"passed"` | All SCORM pass challenge criteria met → `peds_ce_challenge.complete = true` |

**CE challenge criteria (all must be met):**

| Criterion | Requirement |
|-----------|-------------|
| PM1 scenarios | Any 2 of 4 completed with passing/on-track scores or higher |
| PT1 scenarios | Any 2 of 5 completed with passing/on-track scores or higher |
| Total training time | ≥ 3600 s (60 min), counted from orientation, scenarios, and drills |

**Grade formula (backend-computed):** `scenario_avg`

- `scenario_avg` = average of all completed PM1 + PT1 scenario scores; null until 2 PM1 + 2 PT1 are complete
- CPR, drills, optional games, orientation, and XP remain progress/reward telemetry but are not Moodle pass requirements.

**LMS reporting:**
- `cmi.core.lesson_status` = `"passed"` when `peds_ce_challenge.complete === true`, otherwise `"incomplete"`
- `cmi.core.score.raw` = `final_score` (written only when CE challenge complete)

**Node pass threshold:** 70%. `passed` is tracked per node and affects XP; it is not a gate criterion for unlock or CE progression. Completion (not passing score) is what gates maps and CE.

**Replay policy:** Best-score semantics — a replay that scores lower does not overwrite the current best. Additional CE time accumulated on replay counts toward the CE total.

### 2.3 Node Contracts

| Node ID | App ID | Map | CE Role | Score source | Pass threshold | Readiness |
|---------|--------|-----|---------|--------------|:---:|-----------|
| `drill_pat` | `pat` | Map 0 | Required gate | Deterministic answer key | 70 | Game exists; SCORM adapter pending |
| `drill_dev` | `dev_sort` | Map 0 | Required gate | Deterministic answer key | 70 | Existing game; SCORM adapter/contract validation pending |
| `drill_gcs` | `peds_gcs_calculator` | Map 0 | Optional | Deterministic component + arithmetic | 70 | Game exists; SCORM adapter pending |
| `scen_croup` | `peds_croup_01` | PM1 | Any 2 of 4 | Backend checklist + debrief pipeline | 70 | Existing; SCORM end-to-end pending |
| `scen_asthma` | `peds_asthma_01` | PM1 | Any 2 of 4 | Backend checklist + debrief pipeline | 70 | Existing; validation passed |
| `scen_diabetes` | `peds_diabetic_emergency_01` | PM1 | Any 2 of 4 | Backend checklist + debrief pipeline | 70 | Existing; validation passed |
| `scen_seizure` | `peds_febrile_seizure_01` | PM1 | Any 2 of 4 | Backend checklist + debrief pipeline | 70 | Manual validation pass; SCORM end-to-end pending |
| `scen_laceration` | `peds_trauma_01_soft_tissue` | PT1 | Any 2 of 5 | Backend checklist + debrief pipeline | 70 | Existing; validation status TBD |
| `scen_head` | `peds_trauma_07_head_injury` | PT1 | Any 2 of 5 | Backend checklist + debrief pipeline | 70 | Manual validation pass; SCORM end-to-end pending |
| `scen_bleeding` | `peds_trauma_03_extremity` | PT1 | Any 2 of 5 | Backend checklist + debrief pipeline | 70 | Manual validation pass; SCORM end-to-end pending |
| `scen_airway` | `peds_trauma_02_partial_choking` | PT1 | Any 2 of 5 | Backend checklist + debrief pipeline | 70 | Existing; validation status TBD |
| `scen_anaph` | `peds_anaphylaxis_01` | PT1 | Any 2 of 5 | Backend checklist + debrief pipeline | 70 | Manual validation pass; SCORM end-to-end pending |
| `scen_cpr` | `peds_cardiac_arrest_01_bls` | Map 3 | Required | Backend checklist + debrief pipeline | 70 | Existing; CPR package-path validation pending |
| `game_vitals` | `vitals_trend_spotter` | Optional | Any 2 of 3 | Deterministic | 70 | Existing game; SCORM adapter pending |
| `game_lung_sounds` | `lung_sounds_matcher` | Optional | Any 2 of 3 | Deterministic | 70 | Existing game; SCORM adapter pending |
| `game_bls` | `cpr_bls_sequence` | Optional | Any 2 of 3 | Deterministic | 70 | Existing game; SCORM adapter pending |

### 2.4 Node ID Mapping

| Node ID | App ID | Status |
|---------|--------|--------|
| `drill_pat` | `pat` | Existing minigame; SCORM adapter pending |
| `drill_dev` | `dev_sort` | Existing minigame; SCORM adapter/contract validation pending |
| `drill_gcs` | `peds_gcs_calculator` | Existing minigame; SCORM adapter pending |
| `scen_croup` | `peds_croup_01` | Existing scenario |
| `scen_asthma` | `peds_asthma_01` | Existing scenario |
| `scen_diabetes` | `peds_diabetic_emergency_01` | Existing scenario |
| `scen_seizure` | `peds_febrile_seizure_01` | Existing scenario; manual validation pass; SCORM package-path pending |
| `scen_laceration` | `peds_trauma_01_soft_tissue` | Existing scenario |
| `scen_head` | `peds_trauma_07_head_injury` | Existing scenario |
| `scen_bleeding` | `peds_trauma_03_extremity` | Existing scenario |
| `scen_airway` | `peds_trauma_02_partial_choking` | Existing scenario |
| `scen_anaph` | `peds_anaphylaxis_01` | Existing scenario |
| `scen_cpr` | `peds_cardiac_arrest_01_bls` | Existing scenario |
| `game_vitals` | `vitals_trend_spotter` | Existing game |
| `game_lung_sounds` | `lung_sounds_matcher` | Existing game |
| `game_bls` | `cpr_bls_sequence` | Existing game |

### 2.5 Suspend Data Mirror (v3)

16-node shape with CE block. Well under 4,096 characters.

```json
{
  "v": 3,
  "attempt": "scorm_pfd_2026_000001",
  "scores": {
    "drill_pat": 87, "drill_dev": 0, "drill_gcs": 0,
    "scen_asthma": 0, "scen_croup": 0, "scen_diabetes": 0, "scen_seizure": 0,
    "scen_airway": 0, "scen_anaph": 0, "scen_bleeding": 0, "scen_head": 86, "scen_laceration": 0,
    "scen_cpr": 0,
    "game_bls": 0, "game_lung_sounds": 0, "game_vitals": 0
  },
  "completed": {
    "drill_pat": true, "drill_dev": false, "drill_gcs": false,
    "scen_asthma": false, "scen_croup": false, "scen_diabetes": false, "scen_seizure": false,
    "scen_airway": false, "scen_anaph": false, "scen_bleeding": false, "scen_head": false, "scen_laceration": false,
    "scen_cpr": false,
    "game_bls": false, "game_lung_sounds": false, "game_vitals": false
  },
  "unlocks": {
    "scenarios": false,
    "map3": false
  },
  "status": "incomplete",
  "ce": {
    "complete": false,
    "ce_seconds": 0,
    "pm1_completed": 0, "pm1_required": 2,
    "pt1_completed": 0, "pt1_required": 2,
    "cpr_done": false,
    "opt_games_completed": 0, "opt_games_required": 2
  }
}
```

Do not store chat transcripts, debrief markdown, raw AI output, prompts, clinical audit evidence, or free-text content in `cmi.suspend_data`.

---

## 3. Scenario Readiness

Each scenario must pass this checklist before end-to-end testing:

- [ ] Scenario JSON validates with `scripts/validate_scenario.py`
- [ ] Scenario ID maps to the intended SCORM node ID (see Section 2.4)
- [ ] Patient age, weight, setting, dispatch, and scene are appropriate
- [ ] Vitals and intervention effects are deterministic
- [ ] Required interventions use stable vocabulary IDs
- [ ] Required assessments/screens have backend-recognized evidence paths
- [ ] Checklist items use observable behavior, not vague clinical judgment
- [ ] Documentation-scored items have explicit evidence expectations
- [ ] Debrief education is authored and clinically reviewable
- [ ] AI narrator instructions avoid unsafe role behavior, unsupported facts, or hidden scoring authority
- [ ] If TTS is enabled, persona `tts` metadata is authored and common lines are pre-warmed or accepted as live-generation latency
- [ ] Provider failure during chat or debrief leaves the node resumable

**Per-scenario status:**

| Scenario | JSON valid | Checklist authored | Debrief reviewed | End-to-end tested |
|---|---|---|---|---|
| `peds_croup_01` | CI | ✓ | Partial | Existing; SCORM package-path pending |
| `peds_asthma_01` | CI | ✓ | ✓ | Main-app validation passed; SCORM package-path pending |
| `peds_diabetic_emergency_01` | CI | ✓ | ✓ | Main-app validation passed; SCORM package-path pending |
| `peds_febrile_seizure_01` | CI | ✓ | ✓ | Manual validation pass; SCORM package-path pending |
| `peds_trauma_01_soft_tissue` | CI | ✓ | Partial | Existing; SCORM package-path pending |
| `peds_trauma_07_head_injury` | CI | ✓ | ✓ | Manual validation pass; SCORM package-path pending |
| `peds_trauma_03_extremity` | CI | ✓ | ✓ | Manual validation pass; SCORM package-path pending |
| `peds_trauma_02_partial_choking` | CI | ✓ | Partial | Existing; SCORM package-path pending |
| `peds_anaphylaxis_01` | CI | ✓ | ✓ | Manual validation pass; SCORM package-path pending |
| `peds_cardiac_arrest_01_bls` | CI | ✓ | Partial | Existing; CPR package-path pending |

---

## 4. Drill Readiness

Each drill must pass this checklist:

- [ ] Uses a stable `node_id`
- [ ] Uses or maps to a stable reusable `minigame_id`
- [ ] Can run without LLM calls
- [ ] Produces score 0-100
- [ ] Produces `completed` flag
- [ ] Produces compact mistake categories useful for feedback
- [ ] Submits result to backend attempt summary endpoint via `RescueTrails.scorm.submitNodeResult()`
- [ ] Can mirror its result into `cmi.suspend_data`
- [ ] Fails locally without breaking map navigation or LMS commit

**Per-drill status:**

| Drill | Minigame exists | SCORM adapter | Notes |
|---|---|---|---|
| `drill_pat` (`pat`) | ✓ | Pending | Required gate |
| `drill_dev` (`dev_sort`) | ✓ | Pending | Required gate; validate current answer key and completion event in SCORM package |
| `drill_gcs` (`peds_gcs_calculator`) | ✓ | Pending | Optional node |

---

## 5. Map and Node Positioning

Four-map structure. Positioning values are placeholders — finalize when map art is ready.

```json
[
  {
    "map_id": "map0_drills",
    "nodes": [
      { "node_id": "drill_pat", "activity_type": "minigame", "unlock_rule": "always" },
      { "node_id": "drill_dev", "activity_type": "minigame", "unlock_rule": "always" },
      { "node_id": "drill_gcs", "activity_type": "minigame", "unlock_rule": "always" }
    ]
  },
  {
    "map_id": "pm1_medical",
    "unlock_rule": "scenarios_unlocked",
    "nodes": [
      { "node_id": "scen_croup",    "activity_type": "scenario" },
      { "node_id": "scen_asthma",   "activity_type": "scenario" },
      { "node_id": "scen_diabetes", "activity_type": "scenario" },
      { "node_id": "scen_seizure",  "activity_type": "scenario" }
    ]
  },
  {
    "map_id": "pt1_trauma",
    "unlock_rule": "scenarios_unlocked",
    "nodes": [
      { "node_id": "scen_laceration", "activity_type": "scenario" },
      { "node_id": "scen_head",       "activity_type": "scenario" },
      { "node_id": "scen_bleeding",   "activity_type": "scenario" },
      { "node_id": "scen_airway",     "activity_type": "scenario" },
      { "node_id": "scen_anaph",      "activity_type": "scenario" }
    ]
  },
  {
    "map_id": "map3_cpr",
    "unlock_rule": "map3_unlocked",
    "nodes": [
      { "node_id": "scen_cpr", "activity_type": "scenario" }
    ]
  }
]
```

Optional games (`game_vitals`, `game_lung_sounds`, `game_bls`) are accessible from any map at any time via sidebar or launcher.

Map readiness checklist:

- [ ] Four map backgrounds exist
- [ ] Nodes positioned by stable `node_id`, not display label
- [ ] Map 0 drill nodes visible and accessible from the start
- [ ] PM1 and PT1 maps locked until `unlocks.scenarios = true`
- [ ] Map 3 (CPR) locked until `unlocks.map3 = true`
- [ ] `drill_gcs` accessible from the start (not gated)
- [ ] Optional game launcher accessible from any map
- [ ] Node buttons are accessible HTML buttons, not image-only hotspots
- [ ] Maps usable at common LMS iframe sizes

---

## 6. SCORM Runtime Gate

- [ ] Package is a SCORM 1.2 single-SCO ZIP; no SCORM 2004 sequencing/navigation or xAPI dependency
- [ ] `imsmanifest.xml` exists at ZIP root
- [ ] `imsmanifest.xml` validates against SCORM 1.2 schema expectations
- [ ] Manifest and asset paths use forward slashes (`/`), never Windows backslashes (`\`)
- [ ] Manifest launch resource points to root `index.html`
- [ ] `index.html` launches without server-relative asset paths
- [ ] SCORM API wrapper initializes, commits, finishes, and reports errors
- [ ] SCORM API wrapper uses SCORM 1.2 `API` and `LMS*` functions, not SCORM 2004 `API_1484_11`
- [ ] SCORM API wrapper discovers the `API` object in parent/opener frame chains for Moodle embedded and popup launch modes
- [ ] SCORM API wrapper has bounded API-search depth and safe diagnostics when the `API` object is not found
- [ ] Local development adapter works outside an LMS
- [ ] `cmi.suspend_data` v3 save/restore works after closing and relaunching
- [ ] `cmi.suspend_data` remains under 4,096 characters after all 16 nodes and CE block are populated
- [ ] Map unlock state (`unlocks.scenarios`, `unlocks.map3`) correctly restored on resume
- [ ] CE challenge block in suspend data correctly restored on resume
- [ ] Final score writes to `cmi.core.score.raw` only when `peds_ce_challenge.complete === true`
- [ ] Lesson status writes `"passed"` when CE challenge complete; `"incomplete"` otherwise (never `"failed"` for in-progress)
- [ ] Backend remains the source of truth for final grade
- [ ] No transcripts, debrief text, AI output, or clinical evidence written to `cmi.suspend_data`
- [ ] No internal package flow depends on `window.open()`; Moodle owns the New Window launch
- [ ] Moodle activity launch mode verified as New Window for microphone/full-size pilot playback
- [ ] Moodle opener-frame SCORM API bridge verified: `LMSInitialize`, `LMSCommit`, `LMSFinish`, and resume all work from New Window
- [ ] Learner/admin instruction added near SCORM activity: allow popups for the MoodleCloud site if launch is blocked
- [ ] Chrome microphone permission prompt verified from inside the New Window scenario screen
- [ ] Embedded Additional HTML microphone patch documented as attempted/fallback record, not active pilot path
- [ ] Learner/admin instructions state JavaScript must be enabled
- [ ] Moodle App readiness verified if app playback is in scope: "Protect package downloads" disabled in Moodle Cloud Site Administration

---

## 7. Hosted Backend Pilot Gate

- [ ] HTTPS API endpoint available for the MoodleCloud-served SCORM frontend
- [ ] WSS/SSE behavior works from the MoodleCloud-served SCO if the SCORM branch keeps streaming transport enabled
- [ ] PFD/Kent County Moodle Cloud origin identified and recorded
- [ ] CORS allows only the Moodle Cloud SCO origin(s) and approved local development origins
- [ ] Learner-facing SCORM shell is served from the uploaded MoodleCloud ZIP; backend is API-only
- [ ] No manifest, redirect, iframe, or remote-launch wrapper points the learner-facing SCO at the hosted backend app
- [ ] Backend API path does not require third-party cookies; SCORM JWT bearer headers work from the MoodleCloud iframe
- [ ] SCORM auth tolerates empty/null `cmi.core.student_name` and falls back to `student_id` or a generic learner label
- [ ] SCORM auth endpoint rate-limited
- [ ] Chat/debrief endpoints rate-limited
- [ ] SCORM JWTs cannot access admin, agency-management, notes, toys, teams, or store APIs
- [ ] SCORM JWTs can access learner history and agency leaderboard APIs for the Moodle-provisioned learner account
- [ ] Per-session token budget enforced server-side (prevents single session from exhausting free-tier daily limits)
- [ ] Provider errors return safe diagnostic codes — no raw provider errors to SCORM client
- [ ] Graceful degradation fires before daily API limit is reached
- [ ] TTS provider errors are non-fatal: scenario text still displays, no raw provider error exposed
- [ ] TTS cost controls verified: toggle off produces no `/api/tts` requests
- [ ] History/storage policy confirmed live: chat transcripts not persisted after debrief; attempt records store summary data only
- [ ] Sentry or equivalent error tracking configured with PHI/free-text scrubbing before any outside-user pilot
- [ ] Database backup/export plan exists for pilot attempt records

---

## 8. Pilot Observability Gate

Before the 2–5 learner pilot produces actionable data, confirm these signals are reachable. These are not build items — they are verification checks against existing output.

### 8.1 Scoring anomaly visibility

- [ ] **NLP-miss vs. learner-error distinction** — The debrief surfaces `missed_items` but does not distinguish "learner skipped the action" from "learner attempted with an unrecognized phrasing variant." Confirm whether `checklist_states` or `evidence_packet` carries any near-miss or unmatched-transcript signal for missed items. If not, add a lightweight `unmatched_attempts` field to the evidence packet before the pilot (see PUNCHLIST — Pilot anomaly logging).
- [ ] **CE time anomaly baseline** — `CeTimeLog` entries are visible via `GET /api/me/ce-summary`. Confirm this endpoint is accessible in the SCORM deployment and produces readable output for a known pilot learner account.

### 8.2 Pilot telemetry targets

Collect these during the 2–5 learner run. Use to calibrate CE caps and NLP patterns before broader rollout:

| Signal | Source | Use |
|--------|--------|-----|
| Median active scenario session time | `CeTimeLog` `activity_type=scenario` | Validates 60-min CE floor |
| Median debrief view time | `CeTimeLog` `activity_type=debrief` | Validates 8-min debrief cap |
| Missed items where learner clearly attempted | Evidence packet / session transcript | NLP gap detection |
| Scenarios replayed | `ScormAttempt` `node_completed` + replay flag | CE replay-time policy validation |
| Scenario pass rates | `node_scores` in attempt summary | Post-test difficulty calibration |

---

## 9. What Can Wait Until After Branch


- Full SaaS Alembic migration adoption
- Redis/distributed rate limiting for multi-instance scaling
- Billing and entitlements
- Transactional email
- Account deletion/offboarding
- Full router decomposition of the SaaS app
- Full frontend module decomposition, unless needed to safely package the SCORM build
- CDN/media optimization
- Full APM/OpenTelemetry
- Extra optional-game polishing beyond the selected pilot path. Optional game result adapters are useful telemetry but no longer block Moodle completion.
- CE certification steps 1–6 (see `docs/CE_CERTIFICATION_DESIGN.md`) — the LMS is the system of record for the pilot

---

## 10. Build Checklist (Phase 0–8)

This is the sequenced implementation checklist for the SCORM branch. Items in Sections 3–9 are the content/runtime gates for each individual node or subsystem; this section is the build-order checklist for the branch as a whole.

### Phase 0 — Repo and vertical slice gate
- [x] PAT vertical slice verified: `init()` → `drill_pat` result submitted → suspend_data written → `unlocks.scenarios = false`
- [x] `drill_dev` submitted → `unlocks.scenarios = true` confirmed
- [ ] Page reload with dev adapter restores prior completion state correctly
- [ ] Standalone repo created (`cp -r "EMS Simulator" peds-assessment-scorm`), git history severed, pushed to new remote

### Phase 1 — SCORM launch wiring
- [x] MoodleCloud same-origin smoke test built as tiny SCO: local packaged `index.html` + `scorm.js` only
- [x] Tiny SCO uploaded to MoodleCloud and `LMSInitialize` succeeds from the Moodle-served page
- [x] Tiny SCO calls hosted `/api/scorm/auth` successfully from the MoodleCloud origin
- [x] Tiny SCO submits one test node result and commits `cmi.suspend_data` to Moodle
- [x] `SCORM_CONFIG` (`backend_base`, `module_id`, `integration_key`) injected from environment-specific SCORM config at page load — not hardcoded in `scorm.js`
- [x] `scorm.js` reads hosted backend URL from `SCORM_CONFIG.backend_base`; wrapper source is not patched with `sed`
- [ ] SCORM bootstrap path in `app.js` — `if window.RescueTrails.scorm` skips login and calls `init()`
- [ ] `_applyScormResumeState()` restores map completions and unlock state from `resume_state`
- [ ] SCORM JWT accepted by `authFetch` for scenario, chat, and debrief calls via explicit `Authorization: Bearer <token>` headers
- [ ] Silent auth succeeds in both LMS iframe and local dev adapter

### Phase 2 — Production Home and Map UI
- [ ] SCORM launch keeps preboot active during silent auth; no login or old SCORM shell flash
- [ ] First launch / incomplete orientation opens the production Station 1 orientation map
- [ ] Completing Station 1 orientation routes to the production Home screen
- [ ] Relaunch after orientation complete opens the production Home screen
- [ ] Home button remains visible in production map views and returns to Home
- [ ] Pediatric maps use the production renderer, art, node placement, popups, and locked-node handling
- [ ] Map 0 foundation drill nodes submit SCORM progress without replacing the production map UI
- [ ] PM1/PT1/CPR progression follows production navigation and backend unlock state
- [ ] Optional games remain accessible through the production map/sidebar surfaces
- [ ] Scenario and drill screens work in Moodle New Window mode at desktop size

### Phase 3 — Completion event wiring
- [ ] `_APP_TO_SCORM_NODE` reverse map covers all 16 nodes
- [ ] `_onScormNodeComplete(appId, score, completed, mistakeTags)` helper implemented
- [ ] `drill_pat` completion wired (PAT doorway dash submit response)
- [ ] `drill_dev` completion wired (dev_sort submit response)
- [ ] `drill_gcs` completion wired (GCS calculator submit response)
- [ ] `scen_croup` debrief wired — final score from evaluate response
- [ ] `scen_asthma` debrief wired
- [ ] `scen_diabetes` debrief wired
- [ ] `scen_seizure` debrief wired
- [ ] `scen_laceration` debrief wired
- [ ] `scen_head` debrief wired
- [ ] `scen_bleeding` debrief wired
- [ ] `scen_airway` debrief wired
- [ ] `scen_anaph` debrief wired
- [ ] `scen_cpr` debrief wired (CPR challenge + debrief pipeline)
- [ ] `game_vitals` completion wired
- [ ] `game_lung_sounds` completion wired
- [ ] `game_bls` completion wired
- [ ] `RescueTrails.scorm.finish(summary)` called on logout and `beforeunload`
- [ ] CE time accrual endpoint reachable with SCORM-scoped token
- [ ] Map re-renders immediately after each node submission (unlock chain applies without refresh)

### Phase 4 — UI trimming
- [ ] Login and registration screens removed
- [ ] Agency / MCA / protocol picker removed
- [ ] Lexi mascot avatar retained for Station 1 orientation and learner coaching
- [ ] XP bar and treat wallet retained with pilot reward rules
- [ ] Toy chest and store removed
- [ ] Leaderboard retained; team dashboards removed
- [ ] Learner history retained; account notes hidden from SCORM history
- [ ] Training Center and My Progress screens audited for pilot-safe links
- [ ] Home hub retained after orientation complete
- [ ] Home and map navigation audited for SCORM-appropriate links
- [ ] No dead-end links to removed features remain visible

### Phase 5 — MoodleCloud same-origin, CORS, and auth
- [x] Uploaded ZIP serves the learner-facing SCO from MoodleCloud; no remote SCO launch page is used
- [x] `ALLOWED_ORIGINS` in `.env` includes the exact Moodle Cloud SCO origin
- [x] `/api/scorm/auth` confirmed in CORS-exempt list in `app/main.py`
- [x] SCORM API endpoints accept bearer-token auth without relying on cross-site cookies
- [x] Tiny MoodleCloud SCO smoke test passes: `LMSInitialize`, backend auth, test node result, `LMSSetValue("cmi.suspend_data", ...)`, and `LMSCommit`
- [x] Any CSP work is limited to optional backend-served diagnostic pages; backend UI iframe embedding is not part of the pilot architecture

### Phase 6 — `imsmanifest.xml` and packaging
- [x] `imsmanifest.xml` created; validates against SCORM 1.2 schema
- [x] All manifest paths use forward slashes — no backslashes
- [x] Single SCO pointing to packaged local `index.html`; `adlcp:masteryscore` = 70
- [x] Manifest does not point to an external URL and package does not redirect/iframe to the hosted backend app
- [x] `build_scorm.sh` builds ZIP with `imsmanifest.xml` at root
- [x] ZIP spot-checked: `unzip -l pfd_station1_scorm.zip | head -5` shows manifest at root
- [x] `cmi.suspend_data` full 16-node v3 mirror serialized to JSON and confirmed under 4,096 chars
- [x] No `window.open()` calls in the package path

### Phase 7 — Backend deployment
- [x] SCORM-specific `.env` values: `SCORM_INTEGRATION_KEY`, `SCORM_AGENCY_FILE`, `SCORM_MODULE_ID`, `ALLOWED_ORIGINS`, `TTS_PROVIDER`
- [x] PFD agency JSON exists; `scorm_agency_file` value matches its `agency_file` field
- [ ] PFD agency JSON equipment/SOP inventory matches the pilot Postgres agency config before final SCORM packaging
- [x] `scorm_attempts` table in production DB (Alembic migration run)
- [x] `/live` and `/ready` return 200 over HTTPS
- [x] `POST /api/scorm/auth` smoke test returns valid JWT and `scorm_attempt_id`
- [x] Node result submission returns correct summary with unlock chain
- [ ] Sentry (or equivalent) configured; PHI/free-text scrubbing confirmed before outside-user pilot
- [ ] Per-session token budget enforced; graceful degradation tested with simulated 429
- [ ] TTS failure does not block scenario text from displaying

### Phase 8 — Moodle Cloud upload and verification
- [x] ZIP uploaded; activity configured: New Window, highest-attempt grading, completion status tracking
- [ ] "Protect package downloads" verified disabled if Moodle App is in scope
- [ ] Moodle Cloud subdomain confirmed; backend CORS updated with exact SCO origin
- [ ] Test launch: no SCORM API errors and no backend CORS/auth errors in browser console
- [ ] `LMSInitialize` fires (visible in Network or SCORM adapter log)
- [ ] Orientation runs end-to-end, transitions to Map 0
- [ ] `drill_pat` completes → node result submits → `unlocks.scenarios` flips → PM1/PT1 unlock on screen
- [ ] Full scenario: launches, chats, debriefs, scores, node result submitted to SCORM backend
- [ ] Scenario microphone button visible and tested in Chrome New Window playback
- [ ] Scenario screen usable at full-size New Window dimensions; no critical controls below/behind Moodle chrome
- [ ] Optional lung-sounds package-path validation: confirm all LSM/Sound Check referenced audio files are present before testing `game_lung_sounds`
- [ ] Resume test: close browser mid-session, relaunch from LMS, map state restored from `cmi.suspend_data`
- [ ] CE challenge complete: `cmi.core.lesson_status = "passed"` written; score visible in Moodle gradebook
- [ ] Confirmed: no main-app UI elements (login, Lexi, XP bar, toy chest) visible in the package

### Phase 9 — Production backport findings from SCORM pilot
These items came from MoodleCloud package testing and should be folded back into the production program where the same issue exists.

- [ ] Orientation guide recovery: add a learner-facing "What's next?" / next-missing-step control that reads the existing readiness criteria and re-displays the next unmet instruction without changing completion logic.
- [ ] Orientation guidance order: keep guidance cues advisory only; readiness/completion must continue to require introduction, vitals, exam, treatment, Medical Control, Lexi use, and minimum scene time even if the learner completes steps out of order.
- [ ] First-launch gate: first startup should enter Station 1 orientation; after legitimate orientation completion, route to the production Home screen and preserve normal Home/map navigation.
- [ ] Resume marker: store and restore a trusted orientation-complete UI marker alongside backend orientation state so incomplete orientation does not accidentally resume to Home.
- [ ] Preboot/launch polish: keep the launch/preboot surface active until auth and route selection finish so learners do not see a login flash or stale SCORM shell flash.
- [ ] Desktop layout detection: ensure full-width Moodle New Window playback and ordinary desktop browsers use the desktop scenario layout; reserve mobile layout for genuinely compact viewports.
- [ ] Scenario viewport fit: keep quick action buttons, chat input, Lexi controls, and turnover actions visible at common laptop and Moodle New Window dimensions.
- [ ] Microphone support: document Chrome as the supported pilot browser for speech-to-text; keep a fallback note for Brave/iframe permission limitations.
- [ ] Moodle iframe fallback: retain the embedded-player microphone fallback plan (`allow="microphone *"` injection) as a contingency, but prefer New Window for full-size simulator playback when pilot settings allow it.
- [ ] Asset integrity gate: package/build checks should fail or warn loudly when referenced images/audio are missing, including orientation images, Home background art, and LSM audio cards.
- [ ] Asset pruning policy: keep the 47 MB SCORM package trim list, but codify "do not remove referenced assets" checks before further compression.
- [ ] Station 1 wrap-up gate: final orientation wrap-up must remain locked until intro, orientation drill, CPR drill, and challenge list are all genuinely complete for the current user/attempt.
- [ ] Attempt-scoped local UI flags: any local "seen" or map helper flags used in SCORM should be scoped by learner/attempt to avoid one Moodle attempt unlocking another.
- [ ] TTS voice QA: verify scenario persona TTS voice mappings in the deployed browser path, especially male partner/patient voices such as Jake.
- [ ] Orientation sidebar gate: while Station 1 orientation is incomplete, production sidebar items must not route learners to Home or off-orientation content. Audit Home, History, Notebook, Training Center, Daily Trivia, Challenges, Leaderboard, My Progress, and map sidebar buttons as a single gate.
- [ ] Return-target hardening: any screen opened from the orientation map must record its source and return to Station 1 orientation until backend orientation completion is true. History now has this pattern; apply the same rule to Notebook, Training Center, Progress, challenge/trivia flows, and future modal-to-screen transitions.
- [ ] Read-only modal classification: leaderboard, badges, and simple close-only modals can remain available during orientation if desired, but their close/back paths must not call `buildMenu()` or `showScreen("menu")` while orientation is incomplete.
- [ ] Off-orientation launch classification: Training Center drills, Daily Trivia/Lexi challenges, repeatable challenges, retake buttons, and notebook "Start" shortcuts should be hidden, disabled, or explicitly re-routed until orientation is complete.
- [ ] SCORM-only UI trim: hide or re-route SaaS-only surfaces only where needed for SCORM; production Home and map surfaces should remain the canonical UI after orientation.
- [ ] Optional-game data gap: restore or remap `static/audio/lung sounds/LS/F_FC_LLA.wav` before validating the lung-sounds optional game path.

---

### Sequencing summary

| Week | Focus |
|---|---|
| 1 | Phase 0 (vertical slice) + Phase 1 (launch wiring) |
| 1–2 | Phase 2 (4-map UI) + Phase 3 (drill wiring first, then scenarios) |
| 2 | Phase 3 complete (all 16 nodes) + Phase 4 (UI trim) |
| 2–3 | Phase 5 (MoodleCloud same-origin/CORS/auth) + Phase 6 (manifest + packaging) + Phase 7 (backend deploy) |
| 3 | Phase 8 (Moodle upload + pilot run) |

---

## 11. Open Authoring Decisions

- [ ] **`drill_dev` pilot suitability:** Existing `dev_sort` is the mapped required drill. Confirm the content, answer key, scoring scale, and completion event are appropriate for Station 1 before package-path validation.
- [x] **`peds_febrile_seizure_01` validation:** Main-app/manual validation baseline complete; remaining work is SCORM package-path validation.
- [ ] **PT1 / optional scenario validation priority:** Head injury, extremity fracture, and anaphylaxis have recent manual passes. Soft tissue, partial choking, and CPR still need package-path validation if they are included in the pilot learner path.
- [ ] **Optional games SCORM adapter:** `game_vitals`, `game_lung_sounds`, `game_bls` each need a `submitNodeResult()` call for optional progress telemetry, but they do not block Moodle completion.
- [ ] **LSM audio asset gap:** `static/data/games/lsm/cards.json` references `audio/lung sounds/LS/F_FC_LLA.wav` for `lsm_crackles_02`, but that file is not present in the repo/package. Restore the asset or remap the card before validating `game_lung_sounds`; this is a pre-existing optional-game data gap and does not block the shell/PAT/DEV full-package gate.
- [x] **Replay policy:** Additional replay time counts toward CE total; replay scores use best-score semantics and do not overwrite a higher prior score.
- [ ] **Evidence packet retention period:** Define time-limited retention duration for SCORM deployment evidence packets before pilot launch.
- [ ] **CE challenge progress display:** Decide whether and how to surface per-criterion CE progress to the learner on the map (e.g. "2/4 PM1 complete", time remaining to 60 min).
