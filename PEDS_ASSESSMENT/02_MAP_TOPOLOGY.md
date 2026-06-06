# Map Topology: Station 1 Pediatric Assessment Training

## 1. Structural Overview

The SCORM package launches into a Station 1 orientation first, then proceeds directly into this four-map structure with a gated progression chain. There are no other stations, maps, hubs, or course branches in the package.

- **Map 0 — Foundation Drills:** Entry point. Two required drills gate progression to the scenario maps. One optional drill is available at any time.
- **PM1 — Pediatric Medical:** Four medical scenarios. Unlocked once both required drills are complete. Learner must complete any 2 of 4 to meet CE requirements and unlock Map 3.
- **PT1 — Pediatric Trauma:** Five trauma scenarios. Unlocked at the same time as PM1. Learner must complete any 2 of 5 to meet CE requirements and unlock Map 3.
- **Map 3 — CPR:** One required scenario. Unlocked when both PM1 and PT1 minimums are met (2 PM1 + 2 PT1). Must be completed to satisfy CE challenge.

Optional games are accessible from a sidebar or launcher and can be completed in any order.

---

## 2. Map 0: Foundation Drills

### Required (gate scenarios — unlock PM1 + PT1)

- **PAT Drill**
    - *Node ID:* `drill_pat`
    - *Activity:* PAT Doorway Dash — rapid sick/not-sick triage using the Pediatric Assessment Triangle.
    - *App ID:* `pat`
    - *Gate role:* Required — must be `completed=true` alongside `drill_dev` to unlock PM1 and PT1.

- **Developmental Stages Drill**
    - *Node ID:* `drill_dev`
    - *Activity:* Developmental Stages — match pediatric developmental stage to expected behavior, communication approach, and vital sign norms.
    - *App ID:* `dev_sort`
    - *Gate role:* Required — must be `completed=true` alongside `drill_pat` to unlock PM1 and PT1.

### Optional (contributes to grade, does not gate)

- **GCS Calculator**
    - *Node ID:* `drill_gcs`
    - *Activity:* Pediatric GCS Calculator — calculate eye, verbal, and motor subscores and interpret the total score clinically.
    - *App ID:* `peds_gcs_calculator`
    - *Gate role:* Optional — available from the start; does not gate any map; counts toward drill grade if it is in the learner's best 2.

**Progression Rule:** `drill_pat` AND `drill_dev` must each reach `completed=true` to unlock PM1 and PT1. `drill_gcs` can be completed before or after scenarios.

---

## 3. PM1: Pediatric Medical Scenarios

Unlocked when both required drills are complete. Complete any 2 of 4 to satisfy CE requirements and contribute to unlocking Map 3.

- **Croup**
    - *Node ID:* `scen_croup`
    - *App scenario:* `peds_croup_01`
    - *Focus:* Stridor assessment, racemic epinephrine, humidity/positioning, PAT sick impression.

- **Asthma Exacerbation**
    - *Node ID:* `scen_asthma`
    - *App scenario:* `peds_asthma_01`
    - *Focus:* Respiratory assessment, bronchodilator administration, work-of-breathing grading.

- **Diabetic Emergency**
    - *Node ID:* `scen_diabetes`
    - *App scenario:* `peds_diabetic_emergency_01`
    - *Focus:* Blood glucose screen, swallow assessment, oral glucose sequence, AMS differentiation.

- **Febrile Seizure**
    - *Node ID:* `scen_seizure`
    - *App scenario:* `peds_febrile_seizure_01`
    - *Focus:* Post-ictal assessment, fever/temperature history, airway positioning, ALS handoff decision.

**Minimum for CE:** Any 2 of 4 completed. Completing additional scenarios beyond 2 counts toward the scenario average and XP but does not change the CE gate.

---

## 4. PT1: Pediatric Trauma Scenarios

Unlocked at the same time as PM1. Complete any 2 of 5 to satisfy CE requirements and contribute to unlocking Map 3.

- **Scalp Laceration**
    - *Node ID:* `scen_laceration`
    - *App scenario:* `peds_trauma_01_soft_tissue`
    - *Focus:* Bleeding control, wound assessment, MOI, parental reassurance.

- **Closed Head Injury / TBI**
    - *Node ID:* `scen_head`
    - *App scenario:* `peds_trauma_07_head_injury`
    - *Focus:* GCS, pupils, SMR decision, TBI protocol (O2 via NRB for altered mental status).

- **Extremity Fracture / Bleeding**
    - *Node ID:* `scen_bleeding`
    - *App scenario:* `peds_trauma_03_extremity`
    - *Focus:* Angulated forearm fracture, bleeding control, splinting, neurovascular check.

- **Partial Airway Obstruction**
    - *Node ID:* `scen_airway`
    - *App scenario:* `peds_trauma_02_partial_choking`
    - *Focus:* Partial vs. complete obstruction differentiation, age-appropriate airway maneuver decision.

- **Anaphylaxis**
    - *Node ID:* `scen_anaph`
    - *App scenario:* `peds_anaphylaxis_01`
    - *Focus:* Allergen identification, epinephrine auto-injector, airway monitoring, transport decision.

**Minimum for CE:** Any 2 of 5 completed. Same additional-credit rules as PM1.

---

## 5. Map 3: CPR (Required)

Unlocked when 2 PM1 scenarios AND 2 PT1 scenarios are completed.

- **Pediatric Cardiac Arrest — BLS/AED**
    - *Node ID:* `scen_cpr`
    - *App scenario:* `peds_cardiac_arrest_01_bls`
    - *Focus:* High-quality CPR, AED operation, BLS sequence, ROSC recognition.

**Requirement:** Must be completed (not just unlocked) to satisfy the CE challenge.

---

## 6. Optional Games

Available from any map at any time. Complete any 2 of 3 to satisfy the CE games requirement.

| Node ID | App ID | Game |
|---|---|---|
| `game_vitals` | `vitals_trend_spotter` | Vitals Trend Spotter |
| `game_lung_sounds` | `lung_sounds_matcher` | Lung Sounds Matcher |
| `game_bls` | `cpr_bls_sequence` | CPR/BLS Sequence Game |

---

## 7. Unlock Chain Summary

```
Map 0 (drills)
  └─ drill_pat completed AND drill_dev completed
       ├─▶ PM1 unlocked (scen_croup, scen_asthma, scen_diabetes, scen_seizure)
       └─▶ PT1 unlocked (scen_laceration, scen_head, scen_bleeding, scen_airway, scen_anaph)

PM1 ≥ 2 completed AND PT1 ≥ 2 completed
  └─▶ Map 3 unlocked (scen_cpr)
```

Backend `unlocks` object:
- `unlocks.scenarios` — `true` when both required drills complete (gates PM1 + PT1)
- `unlocks.map3` — `true` when PM1 ≥ 2 AND PT1 ≥ 2 complete (gates CPR)

---

## 8. Scoring and Grading

**Drill grade:** Best 2 of 3 drill scores. Completing `drill_gcs` above either required drill score improves the average; scoring below does not hurt it.

**Scenario average:** Average of all completed scenario scores (PM1 + PT1 + CPR), once the minimum CE scenario criteria are met (2 PM1 + 2 PT1 + CPR). Null until that threshold is met.

**Grade formula:** `(drill_grade × 0.20) + (scenario_avg × 0.80)`

| Component | Weight | Rule |
|---|---|---|
| Drills | 20% | Best 2 of 3 drill scores |
| Scenarios | 80% | Average of all completed scenario scores |

**Node pass threshold:** 70%. `passed` is tracked per node and affects XP rewards. Completion (not a passing score) is the gate criterion for unlock progression.

**Replay policy:** Replay is permitted. Best-score semantics — a replay that scores lower than the current best does not overwrite it. Additional time accumulated on replay counts toward CE time.

---

## 9. CE Challenge Requirements (All Must Be Met)

| Criterion | Requirement |
|---|---|
| Orientation | Completed |
| Required drills | `drill_pat` + `drill_dev` completed |
| PM1 scenarios | Any 2 of 4 completed |
| PT1 scenarios | Any 2 of 5 completed |
| CPR scenario | `scen_cpr` completed |
| Optional games | Any 2 of 3 completed |
| Total CE time | ≥ 60 minutes |
| Minimum XP | ≥ 1100 XP |

`lesson_status` resolves to `"passed"` when all CE challenge criteria are met; otherwise `"incomplete"`.

---

## 10. Node Summary

| Node ID | Type | Map | CE Role | App ID |
|---|---|---|---|---|
| `drill_pat` | Drill | Map 0 | Required gate | `pat` |
| `drill_dev` | Drill | Map 0 | Required gate | `dev_sort` |
| `drill_gcs` | Drill | Map 0 | Optional | `peds_gcs_calculator` |
| `scen_croup` | Scenario | PM1 | Any 2 of 4 | `peds_croup_01` |
| `scen_asthma` | Scenario | PM1 | Any 2 of 4 | `peds_asthma_01` |
| `scen_diabetes` | Scenario | PM1 | Any 2 of 4 | `peds_diabetic_emergency_01` |
| `scen_seizure` | Scenario | PM1 | Any 2 of 4 | `peds_febrile_seizure_01` |
| `scen_laceration` | Scenario | PT1 | Any 2 of 5 | `peds_trauma_01_soft_tissue` |
| `scen_head` | Scenario | PT1 | Any 2 of 5 | `peds_trauma_07_head_injury` |
| `scen_bleeding` | Scenario | PT1 | Any 2 of 5 | `peds_trauma_03_extremity` |
| `scen_airway` | Scenario | PT1 | Any 2 of 5 | `peds_trauma_02_partial_choking` |
| `scen_anaph` | Scenario | PT1 | Any 2 of 5 | `peds_anaphylaxis_01` |
| `scen_cpr` | Scenario | Map 3 | Required | `peds_cardiac_arrest_01_bls` |
| `game_vitals` | Game | Optional | Any 2 of 3 | `vitals_trend_spotter` |
| `game_lung_sounds` | Game | Optional | Any 2 of 3 | `lung_sounds_matcher` |
| `game_bls` | Game | Optional | Any 2 of 3 | `cpr_bls_sequence` |

---

## 11. Suspend Data Mirror Shape

```json
{
  "v": 3,
  "attempt": "scorm_pfd_2026_000001",
  "scores": {
    "drill_pat": 87, "drill_dev": 75, "drill_gcs": 0,
    "scen_asthma": 0, "scen_croup": 0, "scen_diabetes": 0, "scen_seizure": 0,
    "scen_airway": 0, "scen_anaph": 0, "scen_bleeding": 0, "scen_head": 0, "scen_laceration": 0,
    "scen_cpr": 0,
    "game_bls": 0, "game_lung_sounds": 0, "game_vitals": 0
  },
  "completed": {
    "drill_pat": true, "drill_dev": true, "drill_gcs": false,
    ...
  },
  "unlocks": {
    "scenarios": true,
    "map3": false
  },
  "status": "incomplete",
  "ce": {
    "complete": false,
    "ce_seconds": 1200,
    "pm1_completed": 0,
    "pm1_required": 2,
    "pt1_completed": 0,
    "pt1_required": 2,
    "cpr_done": false,
    "opt_games_completed": 0,
    "opt_games_required": 2
  }
}
```

Do not store chat transcripts, debrief markdown, raw AI output, prompts, clinical audit evidence, or free-text content in `cmi.suspend_data`.
