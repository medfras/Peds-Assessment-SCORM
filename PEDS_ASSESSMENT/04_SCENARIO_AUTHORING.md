# Scenario Authoring Contract — Station 1 Pediatric Assessment

This document defines the content contract for the Station 1 Pediatric Assessment SCORM pilot. It follows the current 4-map, 16-node topology in `02_MAP_TOPOLOGY.md` and `app/routers/scorm.py`.

The older SCORM Lite school-wing node IDs (`gw_pat`, `med_asthma`, `tr_head`, `cap_ams`, etc.) are superseded. Do not use them for new content, map state, suspend data, or attempt summaries.

## 1. Authoring Goals

The Station 1 scenario set should:

- Exercise the full-app scenario runtime, deterministic vitals/interventions, evidence packet, scoring, and debrief pipeline.
- Keep each scenario short enough for LMS training while still requiring real EMS assessment decisions.
- Preserve backend authority for scoring, persistence, SCORM attempt summaries, and readiness.
- Avoid criteria that depend on frontend-only tags or client-trusted claims as the sole source of truth.
- Use stable IDs so map state, SCORM suspend data, backend attempts, scenario JSON, and minigame launch logic do not depend on display labels.

## 2. Stable Node IDs

These IDs are the contract between the Station 1 map, SCORM suspend data, backend attempt summaries, and launch routing.

| Node ID | Type | Map | App ID | CE Role |
|---|---|---|---|---|
| `drill_pat` | Drill | Map 0 | `pat` | Required gate |
| `drill_dev` | Drill | Map 0 | `dev_sort` | Required gate |
| `drill_gcs` | Drill | Map 0 | `peds_gcs_calculator` | Optional drill; best-2 drill grade |
| `scen_croup` | Scenario | PM1 | `peds_croup_01` | Any 2 of PM1 |
| `scen_asthma` | Scenario | PM1 | `peds_asthma_01` | Any 2 of PM1 |
| `scen_diabetes` | Scenario | PM1 | `peds_diabetic_emergency_01` | Any 2 of PM1 |
| `scen_seizure` | Scenario | PM1 | `peds_febrile_seizure_01` | Any 2 of PM1 |
| `scen_laceration` | Scenario | PT1 | `peds_trauma_01_soft_tissue` | Any 2 of PT1 |
| `scen_head` | Scenario | PT1 | `peds_trauma_07_head_injury` | Any 2 of PT1 |
| `scen_bleeding` | Scenario | PT1 | `peds_trauma_03_extremity` | Any 2 of PT1 |
| `scen_airway` | Scenario | PT1 | `peds_trauma_02_partial_choking` | Any 2 of PT1 |
| `scen_anaph` | Scenario | PT1 | `peds_anaphylaxis_01` | Any 2 of PT1 |
| `scen_cpr` | Scenario | Map 3 | `peds_cardiac_arrest_01_bls` | Required |
| `game_vitals` | Game | Optional | `vitals_trend_spotter` | Any 2 of optional games |
| `game_lung_sounds` | Game | Optional | `lung_sounds_matcher` | Any 2 of optional games |
| `game_bls` | Game | Optional | `cpr_bls_sequence` | Any 2 of optional games |

Display names can change. Node IDs should not change after pilot data exists.

## 3. Scenario Set

### PM1 Medical Scenarios

#### `peds_croup_01`

Primary objectives:
- Recognize upper-airway respiratory distress and croup pattern.
- Characterize stridor and screen for epiglottitis/foreign body red flags.
- Use least-agitating oxygen support and caregiver-held positioning.
- Reassess oxygenation and work of breathing after intervention.

Backend-authoritative evidence should include oxygen delivery, respiratory assessment findings, relevant history tags, and reassessment findings.

#### `peds_asthma_01`

Primary objectives:
- Recognize lower-airway bronchospasm and moderate asthma exacerbation.
- Obtain focused respiratory history and medication availability.
- Administer albuterol within BLS/EMT scope when indicated.
- Reassess lung sounds, work of breathing, and SpO2 after treatment.

Backend-authoritative evidence should include albuterol intervention, SpO2/respiratory reassessment, lung sound findings, and medication/history evidence.

#### `peds_diabetic_emergency_01`

Primary objectives:
- Differentiate altered mental status from hypoglycemia using BLS tools.
- Obtain blood glucose and oral-intake/diabetes history.
- Assess ability to swallow before oral glucose.
- Reassess mental status and glucose/clinical response.

Backend-authoritative evidence should include blood glucose check, oral glucose when indicated and safe, swallow/airway assessment, and post-treatment reassessment.

#### `peds_febrile_seizure_01`

Primary objectives:
- Manage an actively seizing or post-ictal infant/child with airway priority.
- Turn laterally/recovery position and suction visible secretions when indicated.
- Protect from injury without restraint or objects in the mouth.
- Obtain focused seizure, fever, illness, and first-seizure history.

Backend-authoritative evidence should include lateral/recovery positioning, suction when indicated, seizure safety intervention, temperature assessment, seizure-history tags, and oxygen/reassessment when clinically indicated.

### PT1 Trauma Scenarios

#### `peds_trauma_01_soft_tissue`

Primary objectives:
- Manage pediatric soft-tissue trauma with bleeding control and wound assessment.
- Obtain mechanism, LOC, neuro, and relevant SAMPLE history.
- Communicate with caregiver/patient while maintaining scene control.

Backend-authoritative evidence should include bleeding-control intervention, wound/head assessment findings, vital signs, and relevant history.

#### `peds_trauma_07_head_injury`

Primary objectives:
- Calculate and apply pediatric GCS with E/V/M subscores.
- Identify concerning head-injury findings, including unequal/sluggish pupils.
- Apply spinal motion restriction for mechanism plus altered mental status.
- Apply high-flow oxygen per suspected TBI/head injury protocol.
- Reassess GCS and pupils during transport when completed in-session.

Backend-authoritative evidence should include GCS, LOC/vomiting history, pupil assessment, head DCAP-BTLS, SMR intervention, O2 NRB intervention, and neuro reassessment only when both GCS and pupils are repeated after intervention.

#### `peds_trauma_03_extremity`

Primary objectives:
- Assess angulated pediatric forearm fracture and distal CMS.
- Identify vascular compromise cues such as delayed cap refill, pallor, and paresthesia.
- Attempt one gentle realignment when indicated before splinting.
- Splint appropriately and reassess CMS after splinting.

Backend-authoritative evidence should include pre-splint CMS, realignment when indicated, splint intervention, post-splint CMS, and stable anatomical left/right body-map behavior.

#### `peds_trauma_02_partial_choking`

Primary objectives:
- Differentiate partial from complete airway obstruction.
- Avoid aggressive maneuvers while the child can cough/cry/move air.
- Monitor for deterioration and intervene appropriately if complete obstruction develops.

Backend-authoritative evidence should include airway/breathing assessment, cough/air-movement findings, correct avoidance or use of obstruction maneuvers, and reassessment.

#### `peds_anaphylaxis_01`

Primary objectives:
- Recognize anaphylaxis from allergen exposure plus respiratory/circulatory involvement.
- Confirm pediatric weight/dose range before epinephrine when feasible.
- Administer epinephrine IM within BLS/EMT scope.
- Provide oxygen and positioning per protocol when indicated.
- Reassess respiratory status, vitals, and treatment response.

Backend-authoritative evidence should include weight/dosing evidence, epinephrine intervention, O2/positioning when performed, respiratory findings, and post-epi reassessment.

### Map 3 CPR Scenario

#### `peds_cardiac_arrest_01_bls`

Primary objectives:
- Recognize pediatric cardiac arrest.
- Run high-quality BLS CPR/AED sequence.
- Maintain BLS scope and avoid ALS-only interventions.
- Document CPR challenge results and ROSC/non-ROSC outcome.

Backend-authoritative evidence should include CPR challenge events, AED/CPR sequence results, scope adherence, and outcome/reassessment state.

## 4. Minigame Authoring Requirements

Minigames can score client-side for immediate interaction, but node completion and best score must still be submitted to the backend attempt summary endpoint in the SCORM branch.

Each minigame needs:
- Stable `node_id`.
- Stable reusable app/minigame ID.
- Score from 0-100.
- Completion flag.
- Attempt timestamp.
- Optional compact mistake categories for feedback and pilot telemetry.
- No LLM dependency unless explicitly approved.

The main repo must not call `RescueTrails.scorm` directly. SCORM coupling belongs in the SCORM branch adapter. Main-app completion events and backend endpoints must remain stable so the adapter can submit node results.

## 5. Scenario JSON Requirements

New or adapted scenarios must follow `docs/SCENARIO_DESIGN_EMS.md`.

Minimum required content:
- Stable scenario `id`, `display_title`, and clinical context tags.
- Patient age, weight, baseline vitals, deterioration/reassessment rules, and intervention effects.
- Persona rules for patient/caregiver/bystander and EMS partner.
- `correct_treatment.critical_actions` and intervention IDs using stable vocabulary.
- Scenario-specific required assessments and screens where applicable.
- `scene_entry_scoring.ppe` and PAT applicability for pediatric scenarios.
- Authored condition background, key teaching points, and common mistakes.
- History response map entries that do not reveal names, DOB, or hidden clinical findings before the learner obtains them.
- Standard exam findings for focused assessments that should be deterministic.

Do not author scoring criteria that depend on frontend-only tags as the sole source of truth. If a clinical criterion requires explicit assessment evidence, the UI/backend flow must emit a backend-recognized event or persist an authoritative record.

## 6. Debrief and Scoring Policy

The Station 1 module uses the same scoring philosophy as the SaaS app:
- Backend records establish what happened.
- Deterministic scoring handles factual, protocol, checklist, and scope criteria where possible.
- The LLM writes coaching feedback and evaluates bounded qualitative dimensions.
- Authored clinical education content is surfaced by the LLM, not invented by it.

Station 1 pass criteria and raw score formula are defined in `02_MAP_TOPOLOGY.md` and `03_SCORM_ARCHITECTURE.md`:

`scenario_avg`

- `scenario_avg` = average of all completed PM1 + PT1 scenario scores after the 2 PM1 + 2 PT1 scenario minimum is met.
- `peds_ce_challenge.complete` requires 2 PM1 + 2 PT1 passing/on-track scenarios, 60 minutes of eligible training time, and 950 XP.
- Final LMS pass is based on `peds_ce_challenge.complete`, not a raw score alone.

## 7. Content Review Checklist

Before a scenario is included in the SCORM pilot:
- IDs match `02_MAP_TOPOLOGY.md` and `app/routers/scorm.py`.
- Clinical content fits EMT/BLS level for Kent County/PFD use.
- Required interventions use registered vocabulary IDs.
- Out-of-scope actions are explicitly listed where likely.
- Vitals and intervention effects are deterministic.
- Debrief education content is authored and reviewable.
- The scenario can fail gracefully if the AI provider is rate-limited.
- The scenario does not require a frontend tag bridge for authoritative scoring.
- Any TTS metadata is optional and non-blocking.
