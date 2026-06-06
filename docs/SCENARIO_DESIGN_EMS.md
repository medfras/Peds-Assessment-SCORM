# EMS Simulator — Scenario Design Reference

> **Canonical source.** This is the single authoritative reference for all scenario authoring. The stub at `app/scenarios/scenario_design_ems.md` redirects here. All cross-document links to scenario authoring must point to this file.

Scenarios are standalone JSON files that drive the simulation engine. This document covers every field the engine reads, in the order they appear in a scenario file.

---

## Identifier and Vocabulary Contract

Scenario JSON uses **stable IDs** as keys. Display labels may change without breaking scoring or runtime logic. Never compare against labels in code — always use the ID as the lookup key.

### ID groups

IDs are flat snake_case keys — e.g. `albuterol_svn`, `clinical_performance`. The groups below are logical, not literal key prefixes. Do not use dot-notation in scenario JSON.

| Group | Used in | Registry |
|---|---|---|
| Interventions | `vitals.interventions` keys, `requires_intervention_id` | `vocabulary.INTERVENTIONS` |
| Rubric dimensions | `scoring_rubric` keys | `vocabulary.RUBRIC_DIMENSIONS` |
| Out-of-scope categories | `correct_treatment.out_of_scope_bls` items (migrating from free text) | `vocabulary.OUT_OF_SCOPE` |
| Clinical concepts | Future `clinical_context.concepts` tags for protocol/SOP relevance | `vocabulary.CLINICAL_CONCEPTS` |
| Intervention actions | Future evidence-packet scope analysis and protocol action matching | `vocabulary.INTERVENTION_ACTIONS` |

### Rules for authors

1. **`vitals.interventions` keys must be registered** in `vocabulary.INTERVENTIONS` before use. Add the ID there first, then reference it in the scenario. Load-time validation will reject unknown keys.
2. **`scoring_rubric` keys must be registered** in `vocabulary.RUBRIC_DIMENSIONS`. New rubric dimensions require a vocabulary entry.
3. **`requires_intervention_id`** is the stable field for `lung_sound_challenge.post_treatment`. Use the ID from `vocabulary.INTERVENTIONS`. The deprecated `requires_treatment_label` field is still supported but must not be used in new scenarios.
4. **`out_of_scope_bls`** — new scenarios should use IDs from `vocabulary.OUT_OF_SCOPE` instead of free-text strings. Existing scenarios still use free-text (not yet validated). Migrate when editing.
5. **`clinical_context.concepts`** is the Phase 2 scenario/protocol tagging path. Do not invent new concept IDs inline; add them to `vocabulary.CLINICAL_CONCEPTS` and document them in `docs/clinical_concept_taxonomy.md`.
6. **Intervention action IDs** are not UI button IDs. Use `vocabulary.INTERVENTION_ACTIONS` when building protocol scope analysis or evidence-packet action matching.

### Adding a new intervention

1. Add the ID and display label to `vocabulary.INTERVENTIONS` in `app/scenarios/vocabulary.py`. This is the authoritative label.
2. Add the `vitals.interventions` block to the scenario using the ID as the key.
3. Set `label` in the block to the same string. Load-time validation will warn if they diverge.

**The vocabulary is the authoritative source for labels.** If a label must change, update `vocabulary.INTERVENTIONS` first, then update any scenario JSON that carries the old label.

### Phase 2 clinical context tags

Clinical context tags are not yet required at load time, but they are now the planned contract for protocol tree-shaking, local SOP tagging, and deterministic scope analysis. See [`docs/clinical_concept_taxonomy.md`](clinical_concept_taxonomy.md).

Future scenarios should use this shape once Phase 2 validation is enabled:

```json
"clinical_context": {
  "jurisdiction": "national",
  "concepts": ["pediatric_patient", "pediatric_respiratory_distress", "upper_airway_obstruction"],
  "protocol_focus": ["croup", "upper_airway_obstruction"]
}
```

Do not use `clinical_context` tags as hidden diagnostic truth for Medical Control. Medical Control remains blinded to scenario tags.

`clinical_context.concepts` and `clinical_context.protocol_focus` serve different purposes:

- `concepts` is the broad scenario taxonomy. Include population, support, and operational tags such as `pediatric_patient`, `airway_management`, `oxygen_therapy`, `medical_control`, and `vital_signs` when they are true and useful for SOP overlays or reporting.
- `protocol_focus` is the narrow base-protocol selector. It must include at least one condition/protocol-specific tag such as `croup`, `hypoglycemia`, `febrile_seizure`, `anaphylaxis`, `burns`, or `upper_airway_obstruction`.

Generic support tags in `protocol_focus` are intentionally ignored for base protocol excerpt selection when a more specific focus tag is present. For example, `["croup", "upper_airway_obstruction", "oxygen_therapy", "airway_management"]` matches using `croup` and `upper_airway_obstruction`; `oxygen_therapy` and `airway_management` remain useful in `concepts` but do not pull base protocols by themselves. This prevents broad tags from causing unrelated protocol excerpts to appear.

---

## Runtime Architecture

Scenarios are **generic by design** — they adapt at runtime to the active session's agency, provider level, and MCA. Do not hardcode agency-specific values in scenario JSON.

```
load_scenario(id)                    ← lru_cache — fast, immutable base
        ↓
adapt_scenario_to_context(scenario, agency, mca)
        ↓
adapted scenario                     ← used by AI prompts, scoring, and UI
```

`adapt_scenario_to_context()` in `scenario_engine.py` fills in agency values per request. The cached base is never mutated.

**Debrief scoring draws from layered sources applied to the adapted scenario output:**

| Layer | Source | Authored here? |
|---|---|---|
| Layer 1 — Universal Base | Application — fires for every scenario: scene safety, PPE, primary survey, history, vitals, reassessment, disposition, documentation | No — no scenario authoring required |
| Layer 2 — Call-Type + Scenario Criteria | Call-type rubric for reusable condition expectations; scenario JSON only for case-specific deltas such as PAT nuance, unique findings, and scenario-only critical criteria | Yes, but reusable expectations belong in the call-type rubric first |
| Layer 3 — Protocol/Scope | Resolved from `protocol_config` by `adapt_scenario_to_context()` — in-scope interventions, out-of-scope deductions, clinical protocol steps | No — authors set `protocol` reference; engine resolves the rest |

See `SCENARIO_EVALUATION_ARCHITECTURE.md` for the full scoring architecture, implementation phases, and the authority split between deterministic pre-computed scoring and AI qualitative evaluation.

### Base Patient-Care Rubric Inheritance

EMS scenarios do not define their full clinical checklist from scratch. They inherit a **base patient-care rubric family**, compose the dominant **call-type rubric**, and then add only scenario-specific overlays.

For EMS authoring:

- **Medical scenarios** inherit the NREMT EMT `Patient Assessment/Management – Medical (E202)` structure as their base rubric. The inherited base contributes 48 clinical-performance points before scenario overlays, including patient name and patient age/date-of-birth verification.
- **Trauma scenarios** inherit the trauma patient-assessment structure as their base rubric. The inherited base contributes 44 clinical-performance points before scenario overlays, including patient name and patient age/date-of-birth verification.
- **Cardiac arrest/AED scenarios** inherit the NREMT cardiac arrest/AED structure as their base rubric (`nremt_cardiac_arrest_aed_v1`) instead of the general medical assessment sheet. The inherited base contributes 17 clinical-performance points: PPE, scene safety, responsiveness, EMS assistance, simultaneous breathing/pulse check, immediate CPR, high-quality CPR, AED operation, clear verbal safety, shock delivery when indicated, and immediate CPR resumption.

If a scenario has a combined medical/trauma presentation, keep the dominant presenting complaint as `base_patient_care_rubric` and add the other family through `additional_patient_care_rubrics`. For example, a hypoglycemic fall with meaningful injury assessment might use `base_patient_care_rubric: "nremt_e202_medical_v1"` plus `additional_patient_care_rubrics: ["nremt_trauma_v1"]`. The secondary rubric contributes clinically distinct items from the other assessment sheet while suppressing duplicate scene entry, demographics, generic ABC, vital-sign, and reassessment items already owned by the primary base.

If a scenario starts as a normal medical or trauma call and later deteriorates into cardiac arrest, keep the presenting complaint's base rubric as the primary `base_patient_care_rubric` and add the arrest rubric through `additional_patient_care_rubrics: ["nremt_cardiac_arrest_aed_v1"]`. Combined medical/trauma scenarios that can deteriorate into arrest may list both secondary families, e.g. `additional_patient_care_rubrics: ["nremt_trauma_v1", "nremt_cardiac_arrest_aed_v1"]`. This composes the original patient-assessment rubric with clinically distinct secondary rubric items and arrest recognition/CPR/AED items. The loader suppresses duplicate arrest PPE and scene-safety items when the arrest rubric is secondary, because scene entry is already scored by the primary medical/trauma base.

For isolated, low-energy trauma scenarios, do not let the inherited NREMT trauma secondary survey over-penalize body regions that the authored mechanism would not reasonably affect. Keep the base primary survey, vitals, focused affected-region exam, neuro/spine items when clinically indicated, and scenario-specific treatment items. For any fall with head impact, keep C-spine consideration and a focused neck/cervical-spine assessment even if other full-body survey rows are suppressed. Suppress irrelevant inherited full-body survey rows by overriding the inherited item ID in `checklist` with `deprecated: true` and a short clinical rationale in `description`. Do not suppress those rows for high-energy mechanisms, multi-system trauma, unclear mechanisms, suspected abuse, altered mental status, or any scenario where the objective is a complete trauma assessment.

Authors should think in three layers:

1. **Universal base** — scene entry, professionalism caps, always-on infrastructure items
2. **Base patient-care rubric** — applicable NREMT-style assessment/management items, including secondary rubrics for authored deterioration events
3. **Call-type rubric** — reusable condition-specific expectations such as croup stridor differentiation, hypoglycemia BGL/LOC reassessment, or head-injury GCS/pupils/LOC-vomiting history
4. **Scenario overlays** — what is clinically unique to this exact patient

Do not re-author the whole national-registry-style assessment flow in every scenario JSON. The scenario should define only:

- applicability or exclusion notes where needed
- scenario-specific overlay items not reusable across the call type
- scenario-specific critical criteria

### Authoring Rule: Applicable, Not Literal

The NREMT base rubric is a structural scaffold, not a literal requirement list.

Authors must include only the **applicable** patient-care items for the call. Examples:

- A pediatric respiratory scenario should inherit breathing, oxygen, focused pulmonary assessment, vitals, history taking, transport decision, reassessment, and verbal report.
- It should **not** require irrelevant body-system assessment items simply because they exist on the original national registry sheet.
- A trauma scenario should inherit the trauma base workflow, but only the body-region and management elements relevant to the complaint/mechanism.

### Authoring Rule: Overlay Items Are the Clinical Fingerprint

Call-type rubrics own reusable condition requirements. Scenario overlays are what make the call distinct from the base and call-type rubric.

Examples:

- **Croup call type:** stridor vs wheeze differentiation, epiglottitis screen, least-agitating oxygen choice, upright with caregiver, calm environment, ALS/racepinephrine readiness
- **Hypoglycemia call type:** measured BGL, swallow/airway eligibility, oral glucose, repeat BGL/LOC
- **Head injury call type:** formal GCS with E/V/M components, pupils, LOC/vomiting history, focused head DCAP-BTLS, SMR, oxygenation, transport priority
- **Scenario overlay:** a one-off exposure, local device, patient-specific deterioration branch, or unique scene constraint that is not true of the call type generally

Base-rubric items should never be used as a substitute for condition-specific call-type requirements. Scenario JSON should provide patient data and clinical truth; reusable scoring logic belongs in the call-type rubric.

### Scenario applicability flags — set explicitly in scenario JSON

These five boolean flags gate specific inherited base-rubric items. Always set all five explicitly on every clinical scenario — do not rely on concept-based inference or dispatch-text fallback, which are compatibility paths for legacy scenarios only. ALS co-dispatch is agency operational context; it is injected at runtime from the agency configuration and must not be authored into scenario JSON.

| Flag | Type | Gates | Rule |
|---|---|---|---|
| `spinal_injury_possible` | `bool` | `ems.trauma.spine_protection`, `ems.medical.spine_considered` | `true` for any trauma MOI that could involve spinal injury, or any mechanism with significant force or altered LOC |
| `non_transport_agency` | `bool` | `ems.medical.priority_transport`, `ems.medical.transport_reevaluated`, `ems.trauma.priority_transport` | `false` for all transport-capable agencies (the common case); `true` only for fire-only or non-transport fire departments |
| `multiple_patients_possible` | `bool` | `ems.trauma.patient_count`, `ems.medical.patient_count` | `true` for MVCs, multi-patient incidents, or any scene where other patients are plausible; `false` for single-patient residential/playground calls |
| `opqrst_radiation_relevant` | `bool` | `ems.medical.opqrst_radiation` | `true` only for chest pain, ACS, and abdominal pain calls where radiation pattern is clinically meaningful; `false` for respiratory, altered mental status, pediatric calls |
| `diagnostics_indicated` | `bool` | `ems.medical.diagnostics` | `true` when blood glucose, 12-lead ECG, or capnography is a required standard workup step; `false` for isolated trauma, pediatric respiratory without capnography indication, or scenarios where those diagnostics are optional/nice-to-have |

`als_codispatched` is derived during `adapt_scenario_to_context()` from `agency.als_dispatch.co_dispatched` or `agency.als_dispatch.auto_dispatched`. It removes the inherited “request ALS/additional help” item from the effective checklist when ALS was already sent. Scenario authors must not set it directly; doing so would make one agency's dispatch policy leak into every deployment of the scenario.

**Example — pediatric trauma with spinal precaution:**
```json
"spinal_injury_possible": true,
"non_transport_agency": false,
"multiple_patients_possible": false,
"diagnostics_indicated": false,
"opqrst_radiation_relevant": false,
```

**Example — chest pain/ACS with 12-lead:**
```json
"spinal_injury_possible": false,
"non_transport_agency": false,
"multiple_patients_possible": false,
"diagnostics_indicated": true,
"opqrst_radiation_relevant": true,
```

### Fields derived at runtime — do NOT set in scenario JSON

| Field | Derived from |
|---|---|
| `als_arrival_minutes` | `agency.als_dispatch.arrival_minutes` |
| `als_codispatched` | `agency.als_dispatch.co_dispatched` or `agency.als_dispatch.auto_dispatched` |
| `als_unit_name` (in adapted output) | `agency.als_dispatch.unit_name` |
| `dispatch.unit` | `agency.unit_designator` via `{unit}` placeholder |
| `protocol_config` | Resolved from the `protocol` field by `_resolve_protocol()` |
| `mca_expansions` | BLS expansion keys active for the session MCA |
| `mca_specialist_expansions` | Specialist expansion keys active for the session MCA |

### `protocol_config` structure

The resolved `protocol_config` block is what the AI actually reads. Its fields are defined in the protocol JSON file under `app/protocols/`:

| Field | Purpose |
|---|---|
| `id` | Protocol identifier |
| `mca`, `mca_display` | MCA this protocol belongs to |
| `level`, `level_display` | Protocol level category (e.g. `"Pediatric"`) |
| `condition` | Clinical condition name |
| `protocol_reference` | Citation string injected into the AI prompt |
| `sections` | Array of `{ title, reference, points[] }` — the clinical steps |
| `key_drugs` | Array of drug names to highlight in scope prompts |
| `out_of_scope_bls` | Intervention categories that are out of BLS scope per this protocol |
| `deterioration_flags` | Optional clinical warnings injected into deterioration context |

Authors do not write `protocol_config` directly — they set `protocol` to the file path and the engine resolves the rest. Use scenario-level `correct_treatment.out_of_scope_bls` (and the AEMT/Paramedic variants below) for scenario-specific out-of-scope overrides.

### Placeholders

Use `{unit}` in dispatch fields wherever the agency's unit designator should appear:

```json
"dispatch": {
  "unit": "{unit}",
  "text": "{unit}, respond to 123 Main Street for a 4-year-old male with difficulty breathing.",
  "priority": "Priority 1",
  "time": "14:22",
  "cross_streets": "Main St and Oak Ave",
  "response_time_minutes": 4
}
```

`adapt_scenario_to_context()` replaces `{unit}` with `agency.unit_designator` (e.g., `"Squad 1"`). Use `{unit}` anywhere the unit name appears in dispatch text or scene description.

---

## Table of Contents

1. [File Location & Naming](#1-file-location--naming)
2. [Metadata & Configuration](#2-metadata--configuration)
3. [Readiness Criteria](#3-readiness-criteria)
4. [Lung Sound Challenge](#4-lung-sound-challenge)
5. [Dispatch & Scene](#5-dispatch--scene)
6. [Patient](#6-patient)
7. [History](#7-history)
8. [Vitals — Baseline](#8-vitals--baseline)
9. [Vitals — Deterioration](#9-vitals--deterioration)
10. [Vitals — Interventions](#10-vitals--interventions)
11. [Vitals — Improvement](#11-vitals--improvement)
12. [Personas](#12-personas)
13. [Correct Treatment](#13-correct-treatment)
14. [Scoring](#14-scoring)
15. [Scoring Rubric](#15-scoring-rubric) — see also [`docs/rubric_templates/ems_standard_v1.md`](rubric_templates/ems_standard_v1.md)
15a. [Checklist Items](#15a-checklist-items)
16. [Exemplars](#16-exemplars)
17. [Debrief](#17-debrief)
18. [Turnover Target](#18-turnover-target)
19. [Advanced Monitoring](#19-advanced-monitoring)
20. [ALS Phase](#20-als-phase)
21. [Transport Phase](#21-transport-phase)
22. [Pre-Arrival Report](#22-pre-arrival-report)

---

## 1. File Location & Naming

```
app/scenarios/<category>/<scenario_id>.json
```

Examples:
- `app/scenarios/pediatric/medical/peds_croup_01.json`
- `app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json`

The engine discovers all scenario files recursively — subdirectory depth doesn't matter. Scenario ID must match the filename (without `.json`).

---

## 2. Metadata & Configuration

```json
{
  "_schema": "pfd_scenario_v1",
  "id": "peds_asthma_01",
  "title": "Pediatric Asthma — 4-Year-Old Male",
  "display_title": "Pediatric Respiratory Distress",
  "subtitle": "4-Year-Old Male, Difficulty Breathing",
  "category": "pediatric_medical",
  "category_display": "Pediatric Medical Assessment",
  "version": "1.1",
  "difficulty": "beginner | easy | intermediate | advanced",
  "scenario_number": 4,
  "prerequisites": ["peds_croup_01"],

  "als_unit_name": "Medic 1",

  "protocol": "MI/04_OB_Pediatrics/04-5_respiratory_distress",

  "mca_expansions": [],
  "mca_specialist_expansions": [],

  "agency_context": "",

  "scene_entry_scoring": {
    "ppe": {
      "required": ["gloves"],
      "recommended": ["eye_protection"],
      "missing_required_penalty": 3,
      "missing_recommended_penalty": 1,
      "max_score": 10
    }
  },

  "chat_placeholder": "Speak to Liam, Mom (Sarah), or partner Alex...",
  "chat_address_hint": "Address by name: Liam · Mom/Sarah · Alex (partner/vitals)",

  "debrief_lexi_hints": [
    { "label": "Review asthma clues", "msg": "What findings made this asthma rather than croup or foreign-body aspiration?" },
    { "label": "Medication review",  "msg": "Walk me through why albuterol was appropriate here and what response I should document." }
  ],

  "objectives": [
    "Identify signs and severity of pediatric respiratory distress using PAT",
    "Administer albuterol via SVN per protocol",
    "Perform an effective DMIST turnover to ALS crew"
  ]
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `_schema` | yes | Always `"pfd_scenario_v1"` |
| `id` | yes | Must match filename. Snake_case. |
| `title` | yes | Full clinical title shown in the app |
| `display_title` | yes | Shorter title for list/map views |
| `subtitle` | no | One-liner shown under display_title on map |
| `category` | yes | `pediatric_medical`, `pediatric_trauma`, etc. |
| `category_display` | yes | Human-readable category label shown in the HUD header when `pcr_demographics_deferred` is active (e.g. `"Pediatric Medical Assessment"`, `"Pediatric Trauma Assessment"`, `"Adult Medical Emergency"`) |
| `version` | no | Semver string for change tracking |
| `difficulty` | yes | `beginner`, `easy`, `intermediate`, `advanced` |
| `scenario_number` | yes | Controls sort order on the map |
| `prerequisites` | yes | Array of scenario IDs required before unlock. Empty array = no prerequisites. |
| `als_unit_name` | no | Override the ALS unit display name in debrief/DMIST (e.g. `"Medic 1"`). **Omit in most cases** — `adapt_scenario_to_context()` always sets this from `agency.als_dispatch.unit_name`, which takes precedence. Only set here if this specific scenario needs a different ALS unit name than the agency default (e.g. a specialty transport scenario). ALS timing and transport mode are always agency-derived — do not set those here. |
| `protocol` | yes | Reference to the protocol JSON file. Two forms supported — see below. |
| `mca_expansions` | runtime | **Do not set.** Written by `adapt_scenario_to_context()` from the session MCA config. Lists active BLS expansion keys (e.g. `"cpap_bls"`). Read by AI prompts to describe available scope. |
| `mca_specialist_expansions` | runtime | **Do not set.** Same as above for specialist expansions. |
| `agency_context` | no | Agency-specific context string injected into the AI prompt. Usually empty. |
| `scene_entry_scoring` | no | Scenario-defined scene-entry scoring contract. Use this to define PPE / BSI expectations and penalties instead of relying on hardcoded debrief logic. |
| `chat_placeholder` | no | Placeholder text shown in the chat input box |
| `chat_address_hint` | no | Hint shown near the chat input listing addressable personas |
| `debrief_lexi_hints` | no | Scenario-specific Lexi coaching chips shown only after the run in Debrief with Lexi. Use these for diagnosis/protocol-specific prompts that would reveal too much during the live scenario. Array of `{ label, msg }`. |
| `lexi_hints` | legacy | Backward-compatible alias for `debrief_lexi_hints`. Runtime ignores scenario-authored `lexi_hints` for live scenario chat. In-scenario Lexi always shows the same generic chips: `What can you do?`, `Next Step?`, `Missing Info?`, `BLS Scope?`. |
| `objectives` | no | Learning objectives shown on the scenario screen |

### `protocol` field forms

**Simple reference (recommended):**
```json
"protocol": "MI/04_OB_Pediatrics/04-5_respiratory_distress"
```

**Reference with scenario-specific overrides:**
```json
"protocol": {
  "ref": "MI/04_OB_Pediatrics/04-5_respiratory_distress",
  "overrides": { "scope_notes": ["CPAP unavailable — not on this unit"] }
}
```

The engine resolves `protocol` to an internal `protocol_config` object and never stores the raw path string downstream. If both `protocol` and `protocol_config` are present in a file, `protocol` wins. At runtime, `adapt_scenario_to_context()` may re-resolve to a session-MCA-specific protocol file if one exists.

### MCA expansion scope (`required_expansion`)

Interventions that depend on an optional BLS or Specialist expansion carry a `required_expansion` key on the intervention entry:

```json
"cpap": {
  "label": "CPAP",
  "within_bls_scope": true,
  "required_expansion": "cpap_bls",
  ...
}
```

At adaptation time, if the session MCA has not selected that expansion, `within_bls_scope` is flipped to `false` and `expansion_not_selected: true` is added. The AI prompt is updated accordingly — the student will be told the skill is out of scope. **Do not set `required_expansion` unless the intervention genuinely requires an MCA board selection to be in scope.** For universally-scoped interventions, omit the key.

---

## 3. Readiness Criteria

Controls when the **ALS Turnover** button unlocks. All checks must pass.

Do not add pre-scenario confidence checks to new scenario definitions or dispatch UI. Confidence calibration is deferred until it has an end-to-end learner/instructor use; standalone confidence prompts add friction without improving scoring or feedback.

```json
"readiness_criteria": {
  "min_minutes": 3,
  "checks": [
    { "id": "messages", "label": "5 messages sent",    "type": "message_count", "min": 5 },
    { "id": "vitals",   "label": "Vitals assessed",    "type": "vitals_logged" },
    { "id": "exam",     "label": "Exam/history obtained", "type": "exam_logged" },
    { "id": "treatment","label": "Treatment applied",  "type": "treatment_logged" }
  ]
}
```

| Check type | Meaning |
|------------|---------|
| `message_count` | Student has sent at least `min` chat messages |
| `vitals_logged` | At least one vitals panel read logged |
| `exam_logged` | At least one exam/history exchange logged |
| `treatment_logged` | At least one intervention applied |

---

## 4. Lung Sound Challenge

An interactive audio module. When the AI generates a `[[EXAM: Lung Sounds=...]]` tag, the chat pauses and presents an audio clip for the student to identify before resuming.

```json
"lung_sound_challenge": {
  "enabled": true,
  "audio_file": "/static/audio/lung sounds/AsthmaWheezing.mp3",
  "prompt": "Listen carefully — what lung sounds do you hear?",
  "accepted_answers": ["wheeze", "wheezing", "expiratory wheeze", "bilateral wheeze"],
  "finding": "Expiratory wheeze bilateral, decreased air movement at bases",
  "feedback_correct": "Correct — bilateral expiratory wheeze...",
  "feedback_incorrect": "Not quite. Listen again — this is an expiratory wheeze...",

  "post_treatment": {
    "requires_intervention_id": "albuterol_svn",
    "audio_file": "/static/audio/lung sounds/clear.mp3",
    "prompt": "Re-auscultate — what do you hear now?",
    "accepted_answers": ["clear", "clear bilateral", "no wheeze", "wheeze resolved"],
    "finding": "Lung sounds clear bilaterally, good air movement throughout",
    "feedback_correct": "Correct — the albuterol worked...",
    "feedback_incorrect": "Listen again — the bronchospasm has resolved..."
  }
}
```

`post_treatment` is optional — it triggers a second lung sound challenge after the student applies the specified intervention. Use `requires_intervention_id` with a key from `vocabulary.INTERVENTIONS`. The deprecated `requires_treatment_label` field (free-text label match) is still accepted but must not be used in new scenarios.

**Scoring source enforcement:** When `lung_sound_challenge.enabled` is true, the following boundary is enforced end-to-end:

1. **Routing** — `_userExplicitlyRequestedLungSounds()` intercepts lung sound requests and opens the challenge; free-text AI does not reveal the finding
2. **AI prompt** — Alex emits the `[[EXAM: Lung Sounds=finding]]` tag but is instructed to suppress all prose description of the finding (no "I hear wheezing", no "lungs are clear" in response text)
3. **Scoring** — call-type rubric items that credit lung sound auscultation (e.g. `resp_distress.lung_sounds`) require `source=lung_sound_challenge` via the `challenge_performed_exam` abstract role and set `allowed_tiers=[1]`; AI-tagged findings do not satisfy these items

The runtime provides a default lung-sound challenge for the Exam menu even when a scenario does not author a `lung_sound_challenge` block: clear bilateral lung sounds for routine patients, and absent breath sounds for respiratory/cardiac arrest presentations. Author a scenario-specific `lung_sound_challenge` block whenever the actual finding matters clinically, uses non-default audio, changes after treatment, or is scored. Scenarios that use `lung_sound_challenge.enabled=true` should have matching call-type rubric items that require `challenge_performed_exam`. The scenario validator warns if the call type's rubric has a lung sounds item but `lung_sound_challenge` is not enabled.

---

## 5. Dispatch & Scene

```json
"dispatch": {
  "unit": "Squad 1",
  "text": "Squad 1, respond to 2847 Maple Street for a 4-year-old male with difficulty breathing.",
  "priority": "Priority 1",
  "time": "14:32",
  "cross_streets": "Maple Street and Oak Avenue",
  "response_time_minutes": 4
},

"scene": {
  "description": "You arrive at a well-kept single-family home...",
  "image": null,
  "video": null,
  "hazards": [],
  "bystanders": [
    { "name": "Sarah", "relation": "mother", "age": 32 },
    { "name": "Mike",  "relation": "father", "age": 35 }
  ]
}
```

`scene.bystanders` is a lightweight list used to populate the scene context in the AI prompt. Full persona behavior is defined separately in the `personas` block.

---

## 6. Patient

```json
"patient": {
  "name": "Liam",
  "age": 4,
  "age_days": null,
  "age_months": null,
  "dob_month_day": "March 22",
  "age_display": "4-year-old male",
  "sex": "male",
  "weight_kg": 18,
  "weight_display": "40 lbs (approximately 18 kg)",
  "pcr_demographics_deferred": true,
  "chief_complaint": "Difficulty breathing, audible wheezing",
  "general_impression": "Small boy sitting upright on the couch in a tripod position...",
  "gcs_assessment": {
    "e": 4,
    "v": 5,
    "m": 6,
    "total": 15,
    "rationale": "Eyes open spontaneously, answers appropriately for age, and obeys commands.",
    "challenge_description": "GCS challenge vignette for the initial patient state.",
    "after_interventions": [
      {
        "intervention": "scenario_intervention_id",
        "e": 4,
        "v": 5,
        "m": 6,
        "total": 15,
        "rationale": "Why the post-intervention GCS is correct.",
        "challenge_description": "GCS challenge vignette for the improved patient state."
      }
    ],
    "deterioration_descriptions": [
      {
        "gcs_below": 8,
        "description": "GCS challenge vignette for the deteriorated patient state."
      }
    ]
  },
  "image": "/static/images/asthma_4yom.jpeg",
  "video": null,
  "pat": {
    "impression": "One-sentence doorway impression the responder would form using PAT.",
    "appearance": "AVPU level, tone, cry quality, interaction — is the child alert, interactive, limp, or unresponsive?",
    "work_of_breathing": "Visible respiratory effort — retractions, nasal flaring, audible sounds, positioning.",
    "circulation": "Skin color and perfusion — pallor, cyanosis, mottling, diaphoresis, urticaria.",
    "expected": "sick | not_sick",
    "teaching": "What the PAT should communicate clinically and why. Explain which component(s) drove the impression and the clinical significance."
  }
}
```

Use `age_days`, `age_months`, and `age_display` for patients younger than two years so the UI and AI prompt do not render infants as `0-year-old`. Use days for patients younger than one month, months for patients younger than one year, and a clear authored `age_display` whenever the natural display should differ, such as `newborn female`.

All clinical scenarios must author a DOB source. Use `patient.dob_month_day` with a month/day string such as `"March 22"` for patients who are at least 18 months old and whose birthday should be known. The UI derives the DOB year from the authored patient age at runtime, so scenario files stay stable over calendar years. For patients younger than 18 months, use `patient.dob_relative`, such as `"10 months before today's date"` or `"today"`, because a fixed month/day can drift into an impossible infant age as calendar time advances. Do not leave DOB unknown unless not knowing is an intentional clinical finding, and document that exception in the patient/persona behavior; parents and caregivers should know or be able to state the pediatric patient’s DOB source unless the scenario explicitly says otherwise.

PCR header behavior is intentionally universal:

- **All clinical scenarios must set `pcr_demographics_deferred: true`.** This is the required default, not an opt-in. The HUD header shows `category_display` as its title and the dispatch text as its subtitle until the learner obtains patient demographics. Patient identity, DOB, and weight appear in the PCR header only after the learner obtains them via patient-scoped history tags. Runtime capture treats `patient` as the only authority for the PCR header values.
- Do not set `pcr_demographics_deferred: false`. The non-deferred path (pre-populated name, age, and weight in the header on launch) is not used by clinical scenarios.
- Patient identity, DOB, and weight must be revealed through patient-scoped history tags only: `[[HISTORY: Patient Name=...]]`, `[[HISTORY: Patient Age=...]]`, `[[HISTORY: Patient Date of Birth=...]]`, `[[HISTORY: Patient Weight=...]]`. DOB dialogue should say the known month/day for patients at least 18 months old, for example “His birthday is May 13.” For patients younger than 18 months, use an age-relative DOB phrase such as “She was born about 10 months ago.” Unknown DOB is allowed only when explicitly authored as a symptom or scenario constraint.
- PCR header demographics are part of the patient care record and should not be scored as missing from the CHART narrative solely because they are not repeated in free text. DMIST/turnover is a separate verbal handoff artifact: pediatric weight may still be required in the submitted DMIST if the handoff component says so.

`general_impression` is injected directly into the AI's scene-opening context. Write it as a first-person visual observation — what the responder sees on arrival. It should be consistent with `vitals.baseline` values.

**`patient.gcs_assessment`** — Optional, but required for scenarios that enable or expect the in-scenario GCS challenge. This is the authored answer key that prevents the frontend or LLM from inferring components from loose prose. When present, keep it aligned with `vitals.baseline.gcs.value`, and make the `rationale` describe the observable eye, verbal, and motor findings clearly enough for the learner to calculate the score. Include `challenge_description` for the initial state; if interventions or deterioration can change the expected GCS, also author `after_interventions[].challenge_description` and/or `deterioration_descriptions[]` so the modal vignette changes with the expected answer.

For pediatric patients, use age-appropriate verbal interpretation. Crying, words, or sounds should still map to a component intentionally. Do not pair a total with conflicting prose, such as `E2V3M5 = 10` while describing “incomprehensible sounds” (`V2`). If the patient is a newborn or CPR/arrest patient where GCS is clinically secondary, still author the object if the challenge can appear, and state the clinical caveat in `rationale`.

**`patient.avpu_assessment`** — Optional, but strongly recommended whenever LOC/AVPU is clinically important or likely to be requested. This is the authored answer key for AVPU/LOC requests and keeps level-of-consciousness findings deterministic. When present, use one of: `"alert"`, `"verbal"`, `"pain"`, or `"unresponsive"`. Include a plain-language `description` that Alex can report to the learner and a `rationale` explaining why that AVPU level fits the observed behavior.

AVPU/LOC and GCS are related but separate interaction paths. A learner request for “AVPU,” “LOC,” or “level of consciousness” should return only the authored AVPU/plain mental-status description and an `LOC` exam tag. Numeric GCS should only be revealed after the learner explicitly asks for GCS/Glasgow Coma Scale or completes the in-scenario GCS challenge.

**`standard_exam_findings`** — Optional, but recommended for any standard Exam-menu item that could be clinically meaningful, abnormal, scored, or confusing if left to model inference. This block gives the runtime an authored answer key for physical exam findings outside the vitals engine and mental-status locks. Use it for region/system findings such as DCAP-BTLS by body region, abdominal exam, pelvic stability, motor/sensory checks, distal pulses, bleeding sites, and other routine physical exam actions.

Body-map region names are patient anatomical left/right for a front-facing patient. Screen-left is the patient's right side; screen-right is the patient's left side. If an asset is mirrored or redrawn, update the hitbox `data-region` values so tapping the patient's anatomical left arm opens the left-arm exam menu. Extremity findings should be authored in patient anatomical left/right terms and should include movement/motor status when that region or a PMS/CMS check is clinically relevant. For extremity injury scenarios, include pre- and post-intervention CMS/PMS findings with distal circulation, sensation, and movement/motor function so the runtime does not have to infer whether movement is intact or impaired.

When a learner performs a standard exam that is not covered by `standard_exam_findings`, `patient.gcs_assessment`, `patient.avpu_assessment`, `vitals.baseline`, or another authored challenge/lock, the runtime should return a neutral default finding such as “no scenario-specific abnormal finding noted” rather than inventing a new abnormality. Therefore, if the finding matters to the case, author it here.

```json
"standard_exam_findings": {
  "dcap_btls_head": {
    "label": "DCAP-BTLS Head",
    "exam_key": "DCAP-BTLS Head",
    "aliases": ["DCAP-BTLS head", "head DCAP", "inspect and palpate head"],
    "finding": "contusion, laceration, tenderness, swelling; no deformity, abrasion, puncture, burn",
    "notes": "Use actual DCAP-BTLS terms separately; do not conflate abrasion and laceration."
  },
  "abdomen": {
    "label": "Abdominal Exam",
    "exam_key": "Abdomen",
    "aliases": ["abdominal exam", "belly exam"],
    "finding": "soft, non-distended, non-tender; no guarding or rigidity"
  }
}
```

| Field | Notes |
|---|---|
| `label` | Human-readable name for authors and prompt context |
| `exam_key` | Exact `[[EXAM: ...]]` key to emit and display in PCR notes |
| `aliases` | Natural-language request phrases that should map to this finding |
| `finding` | Authoritative finding text shown to the learner and stored in PCR notes |
| `notes` | Optional author-only guidance for avoiding ambiguous wording |

**GCS scoring source enforcement:** When a scenario has `patient.gcs_assessment.challenge_description`, formal GCS credit is gated behind the modal:

1. **Routing** — `_userRequestedGcs()` intercepts GCS requests and opens the modal; the quick-action GCS button always routes to the modal
2. **Display scrubbing** — `processAiTagsForDisplay()` strips GCS total and E/V/M component patterns from AI response text
3. **Scoring** — call-type rubric items requiring formal GCS calculation (e.g. `hypoglycemia.gcs_calculated`) use the `challenge_calculated_gcs` abstract role, resolving to `source=gcs_modal`; they set `allowed_tiers=[1]` so transcript fallback cannot credit the item

`challenge_description` is required for the GCS modal to display a meaningful clinical vignette. Scenarios without it will show placeholder text. The `ems.medical.loc` / `ems.trauma.loc` base rubric items remain separately satisfiable at Tier 2 for basic “determined responsiveness” credit — AVPU verbal assessment earns LOC credit; formal GCS calculation earns the separate `gcs_calculated` call-type credit.

**`patient.pat`** — Required for all pediatric scenarios. Drives the PAT popup shown at scene entry and the scored PAT assessment in the debrief. When `patient.pat` is present, the student is prompted to judge SICK vs. NOT SICK before the simulation begins, and the debrief scores their judgment against `expected` (±3 pts correct, −2 pts incorrect). If a scenario has no `patient.pat` block, no PAT popup appears and no PAT scoring occurs. All pediatric scenarios should define this block.

| Field | Notes |
|---|---|
| `impression` | First-person doorway view — what the responder sees before touching the patient |
| `appearance` | Alertness, tone, cry, interaction — is the child behaving appropriately? |
| `work_of_breathing` | Visible/audible signs of respiratory effort |
| `circulation` | Skin color and peripheral perfusion signs |
| `expected` | `"sick"` or `"not_sick"` — the correct PAT judgment |
| `teaching` | Clinical explanation shown in debrief; explain which component drove the impression |

---

## 7. History

```json
"history": {
  "allergies": "NKDA",
  "medications": ["Albuterol MDI — prescribed, at grandmother's house"],
  "pmh": ["Asthma (diagnosed age 2, 2 prior ER visits — last 6 months ago)"],
  "last_oral_intake": "Lunch approximately 2 hours ago",
  "events_leading_to_call": "Liam was playing outside...",
  "hpi": "30-minute onset of progressive wheezing after outdoor play..."
}
```

`medications` and `pmh` may be either a **string** or an **array of strings** — both are valid. `hpi` (History of Present Illness) is optional; it supplements `events_leading_to_call` with clinical detail. The AI uses all history fields to answer SAMPLE/OPQRST questions, mediated through persona `what_they_know` lists.

### 7.1 Initial Complaint

`initial_complaint` is the required broad-opener answer for patient/family/bystander history. Use it to keep the first response realistic but intentionally incomplete, so learners must ask targeted follow-up questions to earn OPQRST/SAMPLE details.

```json
"initial_complaint": {
  "speaker": "Sarah",
  "lay_summary": "She has a bad cough and she's having trouble breathing.",
  "allowed_in_opener": true,
  "do_not_include": [
    "onset time",
    "diagnosis",
    "clinical terms",
    "treatment suggestions",
    "negative findings",
    "full OPQRST/SAMPLE"
  ]
}
```

Authoring rules:
- Every scenario must define `initial_complaint` unless it has no live chat interaction.
- Keep `lay_summary` vague: chief concern only, in plain family/patient language.
- Do not include OPQRST/SAMPLE details such as onset time, duration, fever, medications, allergies, last oral intake, prior episodes, or critical negatives.
- Do not include diagnosis labels, treatment requests, protocol language, or differential clues beyond what the learner can observe or must ask about.
- For respiratory complaints, prefer “bad cough” or “trouble breathing” over “stridor,” “wheeze,” “barking,” or “high-pitched” unless the scenario intentionally makes that sound obvious from doorway observation.
- `do_not_include` must explicitly include `full OPQRST/SAMPLE` and should include scenario-specific spoilers such as mechanism details, medication names, prior episodes, clinical terms, differential clues, and treatment suggestions.

Runtime protection:
- Broad openers such as “what’s going on?”, “what happened?”, “why did you call?”, or “how can we help?” use `initial_complaint.lay_summary` when present.
- The live chat prompt instructs characters not to add hidden OPQRST/SAMPLE details or emit tags for details that were not specifically requested.
- Scenario-specific persona notes must not conflict with the universal patient/family/bystander disclosure contract. If they do, the universal contract wins.

### 7.2 Scenario-Specific History Response Map

`history_response_map` is an optional authoring aid for high-value OPQRST/SAMPLE elements. It gives the live chat prompt precise lay-language answers, trigger examples, and required tags for common learner phrasings without fully scripting the scenario.

Use this for:
- Scenario-defining OPQRST/SAMPLE elements that must be recorded reliably.
- Common reflective confirmations, such as “you said it was a barky cough,” that should count as `Quality`.
- Critical negatives, such as no choking event, no allergies, no prior episode, or no medication given.

Do not use this to override the universal patient/family/bystander disclosure contract. Characters still reveal only the element the learner asked for and must not volunteer diagnosis, differentials, treatment plans, or extra OPQRST/SAMPLE details.

```json
"history_response_map": {
  "quality": {
    "label": "OPQRST Quality",
    "triggers": [
      "can you describe it",
      "what does it sound like",
      "you said it's a loud barking cough with a high pitch"
    ],
    "answer": "Yes. It sounds harsh and barky, and the noisy part is when she breathes in.",
    "tag": "[[EXAM: Quality=harsh bark-like cough with high-pitched noisy breathing on inhale]]",
    "do_not_include": [
      "onset time",
      "fever",
      "prior episodes",
      "diagnosis",
      "treatment suggestions"
    ]
  }
}
```

Field guidance:

| Field | Notes |
|---|---|
| `label` | Human-readable label for prompt clarity |
| `triggers` | Natural-language examples; not deterministic regexes |
| `answer` | Preferred lay answer, in the persona’s voice |
| `tag` / `tags` | Required structured tag(s) to emit when this element is requested |
| `do_not_include` | Explicit boundaries to prevent over-disclosure |
| `notes` | Optional implementation/authoring clarification |

Compound OPQRST/SAMPLE prompts need an explicit broad entry when the scenario has high-value history that learners commonly ask for in one sentence. Author entries such as `opqrst_full` and `sample_full` with all relevant tags in the canonical display order:

- OPQRST: `Onset`, `Provocation`, `Quality`, `Radiation`, `Severity`, `Time`
- SAMPLE: `Signs and Symptoms`, `Allergies`, `Medications`, `PMH`, `Last Oral Intake`, `Events`

For `sample_full`, use `[[HISTORY: Signs and Symptoms=...]]` rather than `[[EXAM: ...]]`; this keeps the PCR history section ordered with the rest of SAMPLE. If narrower entries such as allergies/medications/PMH also exist, add a `notes` value marking the full entry as the priority for multi-component SAMPLE questions, and note on narrower entries that they should be used only when the learner asks those components alone.

---

#### 7.2.1 Patient-Scoped PCR Header Tags

All clinical scenarios use `patient.pcr_demographics_deferred: true`. Tags that populate the PCR header must be explicitly patient-scoped:

- Use `[[HISTORY: Patient Name=...]]`, `[[HISTORY: Patient Age=...]]`, `[[HISTORY: Patient Date of Birth=...]]`, and `[[HISTORY: Patient Weight=...]]` as appropriate. `Patient Age` is valid scoring/history evidence; the PCR header still displays the authored age segment and does not duplicate age inside the DOB value.
- Do not emit these tags for family, caregivers, bystanders, callers, witnesses, or reporting parties. If the learner asks a parent or bystander for their own name, DOB, age, or weight, record it only as ordinary history with a non-patient key such as `Parent Name`, `Mother Name`, or `Bystander Contact`, and do not use PCR-header keys.
- Patient-scoped header values must match the scenario `patient` fields. The frontend ignores deferred-header demographic tags that are family/bystander-scoped or whose name/weight does not match the authored patient.
- Patient-scoped header facts may be captured when they are volunteered before the learner asks, but only when the content clearly identifies the authored patient. A family member saying “Marcus was born...” can populate Marcus's DOB; the family member's own demographics must not.
- `Patient Date of Birth` should use the authored month/day value for patients at least 18 months old, such as `[[HISTORY: Patient Date of Birth=May 13]]`. The UI derives the year from `patient.dob_month_day` and the patient age at runtime. Patients younger than 18 months must use an age-relative value such as `[[HISTORY: Patient Date of Birth=10 months before today's date]]`, and newborn delivery scenarios may use `[[HISTORY: Patient Date of Birth=born today]]` with `patient.dob_relative: "today"`. Do not use age-relative DOB tag values for patients 18 months or older; the age belongs in the patient age display segment, not duplicated inside the DOB value.
- `Chief Complaint` may populate the complaint line only from patient complaint/history context. Do not use family/bystander complaints, fears, or goals as the patient's chief complaint.

---

## 8. Vitals — Baseline

Sets the patient's physiological state on arrival.

```json
"vitals": {
  "baseline": {
    "hr": {
      "label": "Heart Rate",
      "value": 128,
      "unit": "bpm",
      "display": "128 bpm — tachycardic (expected with distress)"
    },
    "rr": { "label": "Resp Rate",   "value": 32,    "unit": "breaths/min" },
    "spo2": { "label": "SpO2",      "value": 94,    "unit": "%" },
    "bp":   { "label": "Blood Pressure", "value": "98/60", "unit": "mmHg" },
    "temp": { "label": "Temperature", "value": 100.0, "unit": "°F" },
    "gcs":  { "label": "GCS",       "value": 15,    "unit": "/15", "detail": "E4V5M6 — alert, answers appropriately, obeys commands" },
    "blood_glucose": { "label": "Blood Glucose", "value": 98, "unit": "mg/dL" },
    "skin_color": {
      "label": "Skin",
      "value": "Pale, slightly diaphoretic",
      "numeric": false
    },
    "cap_refill": { "label": "Cap Refill", "value": 2.5, "unit": "sec" },
    "pupils": { "label": "Pupils", "value": "PERRL 4mm", "numeric": false },
    "lung_sounds": {
      "label": "Lung Sounds",
      "value": "Expiratory wheeze bilateral, decreased air movement at bases",
      "numeric": false
    },
    "work_of_breathing": {
      "label": "Work of Breathing",
      "value": "Moderate — intercostal retractions, nasal flaring, tripod position",
      "numeric": false
    }
  }
}
```

**Authoritative vital fields:**

Vitals are authored data, not AI-generated content. Every scenario must define a complete baseline set, even when a value is not clinically required for scoring. The live chat/runtime must report authored values first; AI may only answer non-standard or unanticipated assessment requests that are not represented in scenario data.

Required baseline keys for every scenario:

| Field | Notes |
|-------|-------|
| `hr` | Heart rate or pulse rate. Use `0` with display text for cardiac arrest. |
| `rr` | Respiratory rate. Use `0` with display text for apnea/arrest. |
| `spo2` | Pulse oximetry. If waveform would be poor, still author the expected displayed value and qualify it in `display`. |
| `bp` | Blood pressure. If unobtainable, use a non-numeric string such as `"No palpable pulse / unable to obtain BP"`. |
| `temp` | Temperature. Use clinically plausible values; newborns/arrest/exposure scenarios should still author it. |
| `gcs` | Numeric total and component detail. Must match `patient.gcs_assessment.total`. |
| `blood_glucose` | Blood glucose in mg/dL, even when not indicated. Use clinically plausible normal/stress/low values. |
| `skin_color` | Color, temperature, and condition. |
| `cap_refill` | Capillary refill. Numeric or descriptive string accepted. |
| `pupils` | Pupil size/reactivity or a scenario-appropriate note if not clinically assessed during initial resuscitation. |
| `lung_sounds` | Authored auscultation finding. If a lung-sound challenge is used, this must align with the challenge finding. |
| `work_of_breathing` | Respiratory effort/rhythm/quality. |

Required physiologic state authoring:

- `vitals.baseline` is the arrival/initial state.
- `vitals.deterioration` must describe what changes without treatment using rates, caps, and string thresholds.
- `vitals.improvement` or another explicit post-treatment profile must describe expected improvement when a scenario has a meaningful treatment response.
- CPR/NRP scenarios may use `vitals.post_rosc_profiles` or equivalent authored profiles for post-ROSC/post-improvement states.
- Do not rely on the LLM to invent degraded or improved vital signs. If a value can be displayed to the learner, it should be represented in authored vitals or an authored transition rule.

**Optional vital object fields:**

| Field | Purpose |
|-------|---------|
| `display` | Overrides the raw value with a richer display string (e.g., adds clinical context) |
| `numeric` | Set `false` on string-valued vitals (skin, lungs, WOB, pupils). Tells the engine not to do math on them. |
| `detail` | Extra detail appended to the display (e.g., `"E4V5M6"` on GCS) |

Standard numeric vitals: `hr`, `rr`, `spo2`, `temp`, `cap_refill`, `gcs`, `blood_glucose`.
Standard string vitals: `skin_color`, `lung_sounds`, `work_of_breathing`, `pupils`, `bp`.

`blood_glucose` is the canonical key for blood glucose. Do not use legacy aliases such as `bgl` in new scenario JSON.

When `vitals.baseline.gcs` is present, its `value` must match `patient.gcs_assessment.total`. Prefer a `display` or `detail` that includes both the component score and the observable behavior, for example `"E4V3M6 — eyes open, confused words, obeys commands slowly"`.

### ALS monitoring vitals

These fields are **not** always available — they are revealed when the student applies the corresponding monitoring intervention. Set them in `vitals.baseline` so the AI knows what to report when the student attaches the monitor or capnography; the AI is instructed to withhold these findings until the monitoring intervention is applied.

```json
"cardiac_rhythm": {
  "label": "Cardiac Rhythm (4-Lead)",
  "value": "Sinus tachycardia at 128 bpm — no ectopy, normal intervals",
  "numeric": false,
  "image_asset": null
},
"etco2": {
  "label": "ETCO2 (Capnography)",
  "value": "38 mmHg — normal rectangular waveform",
  "numeric": false,
  "image_asset": null
},
"ecg_findings": {
  "label": "12-Lead ECG",
  "value": "Normal sinus rhythm, no ST changes, no bundle branch block, QTc within normal limits",
  "numeric": false,
  "image_asset": null
}
```

All three use the **standard baseline object envelope** (same format as any other non-numeric vital). This eliminates special-case handling in the vitals engine, prompt builder, and validation layer. The `image_asset` field reserves a linkage slot for future ECG and capnography image challenges — it is `null` until the challenge system is built. **The challenge system, not the vitals engine, owns display and interpretation workflow.** A non-null `image_asset` does not activate any runtime behavior until the challenge infrastructure exists.

| Field | Revealed by | AI tag emitted |
|---|---|---|
| `cardiac_rhythm` | `ekg_monitoring` (4-lead monitor) | `[[EXAM: ECG=rhythm description]]` |
| `etco2` | `waveform_capnography` | `[[VITAL: ETCO2=value]]` |
| `ecg_findings` | `12_lead_ecg` | `[[EXAM: 12-Lead=findings]]` |

**ETCO2 — numeric vs. string:** The standard form above treats ETCO2 as a non-numeric string describing both the value and waveform character. For scenarios where ETCO2 must deteriorate continuously over time (e.g., rising ETCO2 in a hypoventilating patient), set `"numeric": true` and use a plain number value with `"unit": "mmHg"`. Numeric ETCO2 participates in `deterioration.rates` and `deterioration.caps`. Use `string_thresholds` to change the qualitative description at clinical thresholds. Both forms are supported — choose based on whether continuous numeric tracking or qualitative description is more important for the scenario.

**`cardiac_rhythm`** describes the 4-lead monitor strip — rate, rhythm name, and any notable findings (ectopy, blocks, aberrancy). Write it as a brief clinical description. If the scenario has a relevant dysrhythmia, this is where it is defined.

**`etco2`** is a numeric value (mmHg). Normal range 35–45 mmHg. Low ETCO2 indicates hyperventilation or poor perfusion; high ETCO2 indicates hypoventilation.

**`ecg_findings`** is the full 12-lead interpretation. Only relevant for AEMT/Paramedic scenarios. Write it as a complete one-paragraph read: rhythm, rate, axis, intervals, ST changes, T-wave morphology, and clinical impression. For pediatric scenarios or basic cardiac monitoring, omit `ecg_findings` and rely on `cardiac_rhythm` alone.

---

## 9. Vitals — Deterioration

Defines what happens if the student does nothing.

```json
"deterioration": {
  "note": "Untreated, this patient will progressively worsen. Rates are per minute of elapsed time.",
  "rates": {
    "hr":   1.5,
    "rr":   0.5,
    "spo2": -0.3,
    "gcs":  0,
    "cap_refill": 0.05
  },
  "caps": {
    "hr":  { "max": 180, "min": 80 },
    "rr":  { "max": 52,  "min": 18 },
    "spo2": { "min": 80, "max": 100 },
    "gcs": { "min": 8, "trigger_spo2_below": 88 },
    "cap_refill": { "max": 4.0, "min": 1.0 }
  },
  "string_thresholds": {
    "skin_color": [
      { "spo2_below": 90, "value": "Pale, diaphoretic, cyanotic tinge to lips" },
      { "spo2_below": 85, "value": "Cyanotic — lips and fingernails" }
    ],
    "lung_sounds": [
      { "rr_above": 44, "value": "Markedly decreased air movement, faint wheeze — near-silent chest" }
    ],
    "work_of_breathing": [
      { "rr_above": 40, "value": "Severe — supraclavicular retractions, head bobbing, abdominal breathing" },
      { "spo2_below": 82, "value": "Agonal — child going limp, jaw thrust needed" }
    ]
  }
}
```

### `rates`
Per-minute change applied to numeric vitals. Positive = rising, negative = falling. Zero = no change. Omit a vital to leave it static.

### `caps`
Min/max boundaries to prevent unrealistic values. `trigger_spo2_below` on a vital means: don't allow GCS to drop until SpO2 falls below that threshold.

### `string_thresholds`
Automatic text updates for string vitals when conditions are met. **Rules are evaluated in order — first matching rule wins.**

**Supported condition keys:**

| Key | Meaning |
|-----|---------|
| `spo2_below` | Fires when current SpO2 < this value |
| `spo2_above` | Fires when current SpO2 > this value |
| `rr_above` | Fires when current RR > this value |
| `rr_below` | Fires when current RR < this value |
| `gcs_above` | Fires when current GCS > this value |

Multiple conditions in one rule create an AND — all must be true for the rule to fire.

---

## 10. Vitals — Interventions

Maps treatment IDs to clinical effects and UI behavior.

```json
"interventions": {
  "albuterol_svn": {
    "label": "Albuterol 2.5 mg via SVN (nebulizer)",
    "within_bls_scope": true,
    "detection_patterns": ["\\bsvn\\b", "\\bnebulizer\\b", "albuterol.*neb"],
    "effects": {
      "spo2": { "immediate_change": 5, "rate_modifier": 0.15 },
      "rr":   { "immediate_change": -8, "rate_modifier": 0.25 },
      "hr":   { "immediate_change": 10, "rate_modifier": 1.15 }
    },
    "notes": "Albuterol 2.5 mg unit-dose nebulized at 6 LPM...",
    "requires_popup": true,
    "popup_type": "medication",
    "popup_config": { ... },

    "unavailable_in_scenario": false,
    "unavailable_reason": ""
  },

  "o2_blowby": {
    "label": "Blow-by Oxygen via mask held near face",
    "within_bls_scope": true,
    "detection_patterns": ["blow.?by", "blow by"],
    "effects": {
      "spo2": { "immediate_change": 4, "rate_modifier": 0.4 }
    },
    "requires_popup": true,
    "popup_type": "oxygen",
    "popup_default": { "device": "blowby", "flow": 15 },
    "notes": "Protocol-specific fallback when a child will not tolerate nasal cannula or a secured mask. Under Michigan pediatric oxygen guidance, blow-by uses mask hardware held close to the face at high flow, not nasal cannula tubing."
  }
}
```

### Effect fields

| Field | Meaning |
|-------|---------|
| `immediate_change` | One-time jump applied when the intervention is logged |
| `rate_modifier` | Multiplier applied to the ongoing deterioration rate (< 1 = slows deterioration, > 1 = accelerates) |
| `string_override` | Object — directly sets one or more string vitals when the intervention is applied. Use for monitor-revealed findings (e.g., setting `cardiac_rhythm` when the cardiac monitor is placed) or intervention-driven state transitions (e.g., epinephrine changing a bradycardia rhythm). **Not a general-purpose escape hatch** — use only for findings that genuinely change as a direct result of applying this intervention. |

**`string_override` example:**
```json
"ekg_monitoring": {
  "effects": {
    "string_override": {
      "cardiac_rhythm": "Sinus Tachycardia — rate 128, regular, no ectopy"
    }
  }
}
```

`string_override` writes directly to the vitals result dict after numeric effects are resolved. It can set any string vital key defined in `vitals.baseline`. It does not interact with `deterioration.string_thresholds` — both can coexist, with string_thresholds continuing to apply after the override is set.

### Intervention scope flags

The scope engine uses these flags to determine which interventions appear in a student's available list:

| Flag | Default (if absent) | Meaning |
|---|---|---|
| `within_bls_scope` | `true` | Available to EMT and below |
| `within_mfr_scope` | inherits `within_bls_scope` | Set `false` to exclude MFR when the skill is EMT-only |
| `within_aemt_scope` | inherits `within_bls_scope` | Set `true` to allow AEMT when `within_bls_scope: false` |
| *(Paramedic)* | always `true` | Paramedics can do everything — no flag needed |

**Common patterns:**

```json
// EMT and above (default — no flags needed):
{ "within_bls_scope": true }

// AEMT and above only:
{ "within_bls_scope": false, "within_aemt_scope": true }

// Paramedic only:
{ "within_bls_scope": false, "within_aemt_scope": false }

// All levels except MFR (EMT-only minimum):
{ "within_bls_scope": true, "within_mfr_scope": false }
```

### ALS monitoring interventions

Monitoring interventions (4-lead, 12-lead, ETCO2/capnography) differ from treatment interventions: they **reveal information** rather than change vitals. Author them with minimal or no `effects`, and rely on the `cardiac_rhythm`, `etco2`, and `ecg_findings` baseline fields to define what the AI reports when the monitor is applied.

**4-lead cardiac monitor (`ekg_monitoring`):**

```json
"ekg_monitoring": {
  "label": "Cardiac Monitor — 4-Lead",
  "within_bls_scope": false,
  "within_aemt_scope": true,
  "detection_patterns": [
    "cardiac monitor", "4.?lead", "ekg", "ecg monitor", "attach.*monitor",
    "monitor.*cardiac", "heart monitor", "rhythm strip"
  ],
  "effects": {},
  "notes": "Attach 4-lead cardiac monitor. Report rhythm from scenario baseline. Normal sinus tachycardia in this patient — no dysrhythmia.",
  "requires_popup": false
}
```

The AI reads `cardiac_rhythm` from `vitals.baseline` and emits `[[EXAM: ECG=...]]` when the student applies or requests cardiac monitoring. Set `notes` to briefly state the expected rhythm so the AI has it immediately available.

**12-lead ECG (`12_lead_ecg`):**

```json
"12_lead_ecg": {
  "label": "12-Lead ECG",
  "within_bls_scope": false,
  "within_aemt_scope": false,
  "detection_patterns": [
    "12.?lead", "twelve lead", "12 lead ecg", "12.?lead.*ecg", "acquire.*12"
  ],
  "effects": {},
  "notes": "Acquire 12-lead ECG. Report ecg_findings from baseline — normal sinus rhythm, no ST changes.",
  "requires_popup": false
}
```

The AI reads `ecg_findings` from `vitals.baseline` and emits `[[EXAM: ECG=12-lead: ...]]`. Paramedic-only by default (both `within_bls_scope` and `within_aemt_scope` false). Include `ecg_findings` in `vitals.baseline` when this intervention is present.

**Waveform capnography (`waveform_capnography`):**

```json
"waveform_capnography": {
  "label": "Waveform Capnography (ETCO2)",
  "within_bls_scope": false,
  "within_aemt_scope": true,
  "detection_patterns": [
    "capnography", "capnograph", "etco2", "end.?tidal", "co2 monitor",
    "waveform.*cap", "capnometry"
  ],
  "effects": {},
  "notes": "Attach waveform capnography. ETCO2 baseline is 38 mmHg — normal. Normal shark-fin waveform.",
  "requires_popup": false
}
```

The AI reads `etco2` from `vitals.baseline` and emits `[[VITAL: ETCO2=X mmHg]]`. Include `etco2` in the `deterioration.rates` block if ETCO2 should change over time (e.g., rising ETCO2 in a hypoventilating patient).

**Deterioration example for ETCO2:**

```json
"deterioration": {
  "rates": {
    "etco2": 1.5
  },
  "caps": {
    "etco2": { "min": 20, "max": 70 }
  }
}
```

### `required_expansion`

If an intervention is only within scope when the session MCA has selected a specific BLS or Specialist expansion, add `required_expansion` to the intervention entry:

```json
"required_expansion": "cpap_bls"
```

At runtime, `adapt_scenario_to_context()` checks the session MCA's expansion list. If the expansion is not active, `within_bls_scope` is flipped to `false` automatically. Do not set this key on universally-scoped interventions.

### Popup types

| `popup_type` | Used for | Key `popup_config` / `popup_default` fields |
|---|---|---|
| `"oxygen"` | O2 delivery selection | `popup_default: { device, flow }` — see device options below |
| `"medication"` | Full 6-rights cross-check modal | See below |

**Oxygen device options** (`popup_default.device`):

| Device key | Display label | Typical flow range |
|---|---|---|
| `"nrb"` | Non-rebreather mask | 10–15 LPM |
| `"nc"` | Nasal cannula | 1–6 LPM |
| `"blowby"` | Blow-by oxygen | Protocol-specific; under Michigan pediatric oxygen guidance use mask hardware held near the face at high flow (~15 LPM), not nasal cannula tubing |
| `"bvm"` | BVM with O2 | 15 LPM |
| `"cpap"` | CPAP | 10–15 LPM (PEEP set separately) |

`popup_default` pre-selects device and flow when the modal opens. Example: `{ "device": "blowby", "flow": 15 }` when local protocol specifies high-flow blow-by. Authoring must keep local terminology precise: if the protocol defines blow-by as mask hardware held near the face, do not author nasal cannula tubing as blow-by. After the student confirms, the selected device and flow rate are recorded in the PCR and logged as an applied intervention. A follow-up chat message is sent automatically asking the partner to report observed patient changes.

### Medication popup (`popup_type: "medication"`)

```json
"popup_config": {
  "drug": "Albuterol Sulfate",
  "concentration": "2.5 mg / 3 mL NS",
  "dose": "2.5 mg / 3 mL NS",
  "route": "SVN nebulized — O₂ at 6 LPM driving gas",
  "scope": "EMT — WMRMCC approved (Section 9-12R)",
  "procedure_ref": "mi_wmrmcc_kent/bls/medication_administration",
  "drug_ref": "mi_wmrmcc_kent/bls/albuterol",
  "cross_check_notice": "WMRMCC 9-1(S): Verbally state drug name, concentration, and dose to your partner before administering.",
  "cross_checks": [
    { "label": "Right Patient — indication confirmed: bronchospasm/wheezing per protocol", "right": "patient" },
    { "label": "Right Medication — label reads Albuterol Sulfate 2.5 mg / 3 mL NS", "right": "medication" },
    { "label": "Right Dose — 2.5 mg / 3 mL NS", "right": "dose" },
    { "label": "Right Route — SVN nebulized; O₂ at 6 LPM driving gas", "right": "route" },
    { "label": "Right Time — baseline vitals obtained; no known hypersensitivity", "right": "time" },
    { "label": "Medication cross-check verbalized to partner (WMRMCC 9-1S)", "right": "crosscheck" }
  ],
  "procedure_steps": [
    "Obtain vital signs and auscultate lung sounds (prerequisite)",
    "Place 3 mL unit-dose vial contents in lower nebulizer chamber; assemble unit",
    "Attach nebulizer to T piece; connect pediatric mask or mouthpiece",
    "Connect O₂ tubing to nebulizer and O₂ source; set flow to 6 LPM",
    "Instruct patient to breathe normally with deep breath every 4–5 breaths",
    "Continue until all medication delivered; tap reservoir gently if needed",
    "Reassess: obtain full set of vitals and lung sounds post-treatment"
  ]
}
```

### Unavailable interventions

An intervention can be listed but blocked in this specific scenario:

```json
"albuterol_mdi_patient_assisted": {
  "label": "Patient-assisted albuterol MDI (patient's own prescription)",
  "unavailable_in_scenario": true,
  "unavailable_reason": "Liam's albuterol MDI is at his grandmother's house. Use the nebulizer from your drug kit."
}
```

The intervention still appears in the UI with a lock icon and the reason displayed on hover/click.

---

## 11. Vitals — Improvement

Defines qualitative improvements as vitals normalize with treatment. This block is entirely separate from `deterioration`.

```json
"improvement": {
  "note": "With O2 and albuterol, bronchospasm resolves over several minutes.",
  "requires_intervention": "albuterol_svn",
  "string_thresholds": {
    "lung_sounds": [
      {
        "spo2_above": 98,
        "rr_below": 24,
        "value": "Markedly improved — bilateral air movement good, expiratory wheeze greatly diminished"
      },
      {
        "spo2_above": 96,
        "rr_below": 30,
        "value": "Improving — air movement increased bilaterally, wheeze decreased in intensity"
      },
      {
        "spo2_above": 95,
        "value": "Slight improvement — wheeze still present but air movement better than on arrival"
      }
    ],
    "work_of_breathing": [
      {
        "rr_below": 24,
        "spo2_above": 98,
        "value": "Mild — retractions nearly resolved, breathing more comfortably"
      }
    ],
    "skin_color": [
      { "spo2_above": 98, "value": "Pink and warm, diaphoresis resolved" }
    ]
  },
  "presentation_milestones": [
    {
      "spo2_above": 98,
      "rr_below": 24,
      "text": "Liam is noticeably more comfortable. He has relaxed from his strict tripod position..."
    },
    {
      "spo2_above": 95,
      "text": "Liam shows early signs of improvement — slightly less anxious, breathing marginally less labored."
    }
  ]
}
```

### Key fields

| Field | Purpose |
|-------|---------|
| `requires_intervention` | The intervention ID that must be applied before improvement rules activate |
| `string_thresholds` | Same structure as `deterioration.string_thresholds` — text updates for string vitals as they improve |
| `presentation_milestones` | Narrative text injected into the AI's context when conditions are met — describes the patient's visible improvement |

**Milestone condition keys:** Same as `string_thresholds` — `spo2_above`, `spo2_below`, `rr_below`, `rr_above`, `gcs_above`. Multiple keys in one rule = AND logic.

---

## 12. Personas

Instructs the LLM on how to roleplay each character on scene.

```json
"personas": {
  "patient": {
    "name": "Liam",
    "age": 4,
    "role": "patient",
    "sex": "male",
    "aliases": ["Liam", "the child", "the boy", "the patient", "buddy"],
    "tts": {
      "enabled": true,
      "voice_role": "patient",
      "gender": "male",
      "age_band": "child",
      "provider_voice": "fable",
      "speed": 0.95,
      "demeanor": "frightened, tired, working to breathe",
      "delivery": "short childlike phrases with pauses for breathing",
      "avoid": "do not sound like an adult, narrator, clinician, or parent"
    },
    "description": "4-year-old boy who is scared and working hard to breathe...",
    "speaking_style": "Short 2-3 word phrases. May say 'it hurts' or 'can't breathe good'.",
    "what_he_knows": [
      "He was playing outside",
      "His chest hurts and it's hard to breathe"
    ],
    "what_he_doesnt_know": "Anything medical. He cannot report his own medical history."
  },

  "mother_sarah": {
    "name": "Sarah",
    "age": 32,
    "role": "family",
    "relation": "mother",
    "sex": "female",
    "aliases": ["Sarah", "mom", "mother", "ma'am"],
    "tts": {
      "enabled": true,
      "voice_role": "bystander",
      "gender": "female",
      "age_band": "adult",
      "provider_voice": "coral",
      "demeanor": "anxious, protective, near tears, cooperative",
      "delivery": "worried parent speaking quickly but clearly",
      "avoid": "do not sound physically ill, sedated, playful, clinical, or like the patient"
    },
    "description": "Liam's mother. Anxious and tearful but cooperative...",
    "speaking_style": "Anxious, speaks quickly. 'Is he going to be okay?'",
    "what_she_knows": [
      "Full asthma history — diagnosed age 2, 2 prior ER visits",
      "His albuterol MDI is at grandma's house",
      "He was playing outside for about 45 minutes before symptoms started"
    ]
  },

  "lily": {
    "name": "Lily",
    "role": "patient",
    "sex": "female",
    "aliases": ["Lily", "the baby", "the infant", "baby"],
    "tts": {
      "enabled": false,
      "voice_role": "patient",
      "gender": "female",
      "age_band": "infant",
      "demeanor": "frightened, clingy, intermittently crying",
      "delivery": "non-verbal infant; display observable behavior only",
      "avoid": "do not synthesize spoken words for Lily"
    },
    "description": "10-month-old female with croup. Cannot speak — communicates through crying, reaching, and facial expressions.",
    "speaking_style": "Non-verbal. Communicates through crying, whimpering, reaching, arching back.",
    "clinical_state_instructions": "Do not give verbal responses as Lily. Describe her behavior in third person... If student applies NRB: 'Lily starts screaming and arching her back, fighting the mask — the stridor becomes significantly louder.'",
    "persona_rules": [
      "Always describe Lily's state through observable behavior, never verbal responses",
      "Worsening = screaming, arching, fighting equipment, stridor louder",
      "Any forced assessment triggers worsening"
    ]
  },

  "alex": {
    "name": "Alex",
    "role": "ems_partner",
    "sex": "male",
    "aliases": ["Alex", "partner", "crew"],
    "tts": {
      "enabled": true,
      "voice_role": "alex",
      "gender": "male",
      "age_band": "adult",
      "provider_voice": "echo",
      "speed": 1.22,
      "demeanor": "calm, competent, practical, reassuring",
      "delivery": "concise EMT partner in the room, natural field tone",
      "avoid": "do not sound like a narrator, instructor, parent, or patient"
    },
    "description": "Your EMT partner on Squad 1. Competent and professional.",
    "speaking_style": "Professional, calm, brief. Reports vitals clearly in EMS format.",
    "capabilities": [
      "Report individual vitals when asked",
      "Report full vital set when asked",
      "Set up and administer albuterol SVN"
    ]
  }
}
```

### Role values

| Role | Behavior |
|------|----------|
| `"patient"` | The patient. Knows only what's in `what_he_knows` / `what_she_knows`. Never volunteers; answers when appropriately prompted. |
| `"family"` | Family member / bystander with `relation`. Provides SAMPLE history from `what_she_knows` when asked. |
| `"bystander"` | Non-family bystander. Same knowledge-silo rules as family. |
| `"ems_partner"` / `"partner"` | The student's EMS partner. Reports vitals and assists when explicitly commanded. **Never volunteers or recommends interventions, assessments, oxygen devices, transport decisions, protocol steps, or next actions.** If a command is incomplete, asks one narrow clarification question instead of choosing independently. |

### Key persona fields

| Field | Required | Notes |
|-------|----------|-------|
| `name` | yes | Display name |
| `role` | yes | See table above |
| `aliases` | yes | All names the student might use to address this persona in chat |
| `description` | yes | Background and personality. Injected into AI system prompt. |
| `speaking_style` | yes | Tone, vocabulary, and example phrases |
| `what_he/she_knows` | for patients/family | Information revealed only when student asks the right questions |
| `what_he/she_doesnt_know` | no | Explicit knowledge gaps |
| `clinical_state_instructions` | no | Detailed behavioral rules for non-verbal or complex patients — overrides general description for specific situations |
| `persona_rules` | no | Bullet list of strict behavioral constraints for the AI |
| `capabilities` | for partner | Explicit list of what the partner can do when commanded |

For titled bystanders or professionals, include both punctuation and no-punctuation aliases, for example `"Ms. Hernandez"` and `"Ms Hernandez"` or `"Dr. Patel"` and `"Dr Patel"`. Runtime chat rendering handles common honorifics, but the no-period alias improves matching for speech recognition and learner typing.

Do not expose unrevealed bystander names in `chat_placeholder` or `chat_address_hint`; use role labels such as `teacher`, `mother`, `father`, `school staff`, or `partner Alex` until the learner obtains the name in the scenario. The scenario chat roster should likewise render role placeholders immediately (`patient`, `teacher`, `mother`, etc.) and replace the placeholder with the name only after the learner obtains or uses that name. Partner names may appear immediately because the learner arrives with their partner. Roster order is always partner(s), patient(s), caregiver/family contact(s), then other bystander(s).

### Persona TTS metadata

Scenario personas should include a `tts` object when cloud TTS should use a deliberate voice, tone, or delivery. These fields are presentation metadata only. They support audio realism and accessibility, but they are not authoritative for scoring, clinical state, tenant boundaries, readiness, or persistence.

| Field | Required | Notes |
|-------|----------|-------|
| `enabled` | yes | `false` for non-verbal patients or characters that should never be synthesized |
| `voice_role` | yes | Runtime role for voice selection: `patient`, `bystander`, `alex`, `lexi`, or `physician` |
| `gender` | yes | Voice-selection hint: `male` or `female` |
| `age_band` | recommended | Voice-selection hint: `infant`, `child`, `adult`, or `elderly`. Infants/non-verbal toddlers should usually set `enabled: false` |
| `provider_voice` | recommended | OpenAI voice identifier such as `coral`, `nova`, `echo`, `onyx`, `fable`, or `shimmer`. Use scenario-specific voice choices for recurring named characters. |
| `speed` | no | Per-persona speech-rate multiplier. Use modest adjustments; partner speech can be faster than anxious family or altered patients. |
| `demeanor` | recommended | Emotional affect: frightened parent, calm partner, confused child, etc. |
| `delivery` | recommended | Pacing and communication style. Example: "short childlike phrases with pauses" |
| `avoid` | recommended | Negative constraints to prevent wrong role, tone, or clinical sound. Example: "do not sound physically ill or like the patient" |

Author TTS emotion as specific performance direction, not a generic mood label. Symptomatic pediatric patients should not be described as using a "neutral kid voice"; describe the clinically appropriate sound instead, such as breathless strain, tearful pain, foggy confusion, post-ictal nonverbal behavior, or frightened short phrases. Anxious parents/caregivers should include urgency markers such as faster pace, tremble, breath-catching worry, protective tone, and a clear transition to partial relief only after effective reassurance or clinical improvement. The `avoid` field should explicitly block the common failure mode for that role, especially "calm", "flat", "detached", "clinical", adult-sounding children, or wrong accent when those defects reduce realism.

Alex/partner TTS should remain calm and professional, but not sleepy or flat. Use "brisk", "engaged", and "clear EMS cadence" for partner delivery while keeping persona rules clear that Alex follows student commands and does not coach unless the scenario specifically authorizes a narrow clarification.

TTS cache keys include the scenario id plus model, voice, speed, format, persona styling, clinical cues, and text. This prevents identical names or lines in different scenarios from accidentally sharing audio while still allowing repeat lines within the same scenario to reuse cached speech.

Do not encode race or ethnicity as a voice-selection instruction. If cultural, language, accent, or interpreter needs are educationally relevant, author them explicitly in `description`, `speaking_style`, and scenario objectives with appropriate care and clinical relevance.

### Partner oxygen clarification rule (required when multiple O2 interventions exist)

If a scenario defines more than one oxygen delivery intervention (e.g., `o2_blowby`, `o2_nc`, `o2_nrb`, `high_flow_o2`), the partner character **must not** choose a default delivery method for a generic student command such as "admin O2" or "give oxygen." The active scene is a simulation surface, not a coaching surface. Alex may carry out a specific order or ask one narrow clarification question, but must not recommend the clinically preferred oxygen device.

This rule prevents two common failures:

- The partner narrates two mutually exclusive delivery methods in one response, which can register both interventions and create a documentation contradiction.
- Scenario content or broad detection patterns turn a system hint into an apparent learner action, making it look as if oxygen was administered when the learner did not select it.

**Pattern to follow**:
```json
"description": "... OXYGEN CLARIFICATION RULE: If the student gives any generic oxygen command without specifying a method, ask which delivery method they want. Do not recommend or choose a device independently. Never describe two delivery methods in the same response.",
"persona_rules": [
  "When the student gives any generic oxygen command, ask one clarification question: Which oxygen delivery method?",
  "Do not choose or recommend an oxygen device unless the student specified it.",
  "Never describe two mutually exclusive oxygen delivery methods in the same response."
]
```

Detection patterns for device-specific oxygen interventions must also be device-specific. Do **not** put broad phrases such as `"oxygen"`, `"o2"`, or `"supplemental oxygen"` on `o2_nc`, `o2_nrb`, blow-by, or other device-specific interventions. Broad oxygen language should prompt clarification or an explicit oxygen-selection UI, not silently map to one device.

---

## 13. Correct Treatment

Defines the gold standard the scoring engine compares against.

```json
"correct_treatment": {
  "critical_actions": [
    {
      "id": "scene_safety",
      "description": "Scene safety and BSI/PPE prior to patient contact",
      "required": true,
      "scene_entry_credited": true
    },
    {
      "id": "pat",
      "description": "Pediatric Assessment Triangle",
      "required": true,
      "scene_entry_credited": true
    },
    {
      "id": "neuro_assessment",
      "description": "Perform neurological assessment — GCS/AVPU, pupils, ask about LOC and vomiting",
      "required": true,
      "protocol_indicated": true,
      "evidence": {
        "finding_types": ["exam", "vital"],
        "finding_key_patterns": ["\\bpupils?\\b", "\\bgcs\\b", "\\bloc\\b", "vomit"],
        "transcript_patterns": ["\\bpupils?\\b", "\\bgcs\\b", "loss of consciousness", "vomit"],
        "min_matches": 2
      }
    }
  ],
  "recommended_actions": [
    {
      "id": "hospital_notification",
      "description": "Notify receiving hospital of incoming pediatric respiratory patient",
      "required": false
    }
  ],
  "out_of_scope_bls": [
    "iv_io_access",
    "endotracheal_intubation",
    "epinephrine_nebulized_als"
  ],
  "clinical_decision_points": {
    "als_trigger": "ALS/intercept expectations are determined by the active agency configuration; prepare a clear handoff when ALS is involved.",
    "bvm_trigger": "Apnea, GCS < 10, SpO2 < 88% unresponsive to O2 and albuterol",
    "destination": "Nearest appropriate emergency department with pediatric capability"
  }
}
```

- **`critical_actions`** — Actions the student must perform. Missed items deduct from Clinical Performance score and appear in the debrief as missed steps. `required: true` is implicit but can be set explicitly.
  - **`scene_entry_credited: true`** — Marks actions evaluated via the scene-entry UI (e.g. scene safety / PPE, PAT). The backend will pre-credit these so the AI does not invent misses because the student failed to verbalize them in chat or turnover.
  - **`protocol_indicated: true`** — Marks an in-scope assessment/action whose omission should count against the student if there is no evidence it was done.
  - **`evidence`** — Optional deterministic evidence contract used to pre-check protocol-indicated assessments from transcript + findings. Use this for assessments like neuro checks, lung sounds, or reassessment where missing them should cost points.
  - For scenario-specific trauma screens that require multiple history components (for example mechanism details plus loss-of-consciousness status), prefer structured evidence over a single broad transcript regex. Author focused `history_response_map` entries that emit separate `[[HISTORY: Events=...]]`, `[[HISTORY: LOC=...]]`, `[[HISTORY: Vomiting=...]]`, or similar tags, then score the checklist row with `requirement_logic: "all"` and `tier1_matches`. Do not require the learner to gather all components in one sentence; real history-taking often collects mechanism, surface/impact, LOC, and vomiting in separate questions.
- **`recommended_actions`** — Good practice but not strictly required. Bonus credit territory. These are debrief/scoring context only. Runtime scene chat, actors, Alex, and scene UI must not surface `recommended_actions` as live suggestions during the call.
- **`out_of_scope_bls`** — IDs from `vocabulary.OUT_OF_SCOPE` listing intervention categories the AI should flag if a student attempts them. Applied when the student's level is MFR or EMT. Use the stable ID (e.g. `"iv_io_access"`), not a free-text string. Existing scenarios still use free-text strings and are supported for now, but new scenarios must use vocabulary IDs. Migrate old entries when editing a scenario.
- **`out_of_scope_aemt`** — Same format as `out_of_scope_bls`. Required on every scenario. Use an explicit empty list `[]` when AEMT has no additional restrictions beyond BLS, or list only the intervention IDs that remain out of scope for AEMT. Do not rely on omission fallback; omission is a legacy behavior and can produce incorrect AEMT scoring in multi-level deployments.
- **`out_of_scope_paramedic`** — Same format. Required on every scenario. Use an explicit empty list `[]` when no Paramedic-level interventions are out of scope for this scenario, or list field-inappropriate procedures that should still be flagged. Do not omit this field; omission removes Paramedic scope enforcement and makes the scenario non-portable across provider levels.
- **`clinical_decision_points`** — Named decision thresholds injected into the AI prompt as context. Keys can be anything descriptive.

---

## 14. Scoring

### 14.0 Base Rubric Mapping Rule

Scenario scoring should be interpretable in two clinical layers:

- **Base patient-care layer** — applicable NREMT-style assessment/management items
- **Scenario-specific layer** — condition-specific expectations and pitfalls

For medical scenarios, the default base mapping should align to E202-style domains:

- scene size-up / PPE
- nature of illness
- general impression
- responsiveness / AVPU
- chief complaint / apparent life threats
- airway / breathing assessment
- circulation / skin
- oxygen therapy
- patient priority / transport decision
- history taking
- focused secondary assessment of the affected system
- vital signs
- field impression
- reassessment
- verbal report

Authors should use scenario overlays to represent the complaint-specific expectations that go beyond this base structure.

Provides the AI with explicit grading guidance.

> **Three-Layer Architecture — Layer 2:** The fields in this section are the scenario's contribution to the debrief scoring architecture. Layer 1 (Universal Base — application-defined presence checks) fires automatically for every scenario. The fields below — `overall_considerations`, `dmist_considerations`, `narrative_considerations`, `by_level`, and `required_interventions` — are **Layer 2 (Scenario Criteria)**: condition-specific scoring guidance and per-level requirements that the evidence packet builder and debrief LLM read as scenario-specific facts. Layer 3 (Protocol/Scope) is resolved at runtime from the `protocol` reference. See `SCENARIO_EVALUATION_ARCHITECTURE.md §4A` for the full architecture.

```json
"scoring": {
  "overall_considerations": [
    "Primary focus: recognition of reactive airway disease and initiation of albuterol SVN and O2.",
    "Albuterol SVN 2.5 mg is the critical BLS intervention — single most important action for this scenario."
  ],
  "dmist_considerations": [
    "D: Should clearly identify pediatric asthma exacerbation and severity.",
    "M: Age, weight, known asthma history, no MDI available.",
    "I: O2 via NRB, albuterol SVN 2.5 mg — include time administered and patient response.",
    "S: RR, SpO2, current wheeze quality (improved vs. persistent).",
    "T: Current patient status, response to treatment, transport destination.",
    "Reward focused, targeted information for each component. Do NOT penalize brevity."
  ],
  "narrative_considerations": [
    "Do NOT require medications, allergies, or complete vitals tables — those belong in other PCR fields.",
    "Evaluate objectivity: flag vague phrases and suggest objective replacements.",
    "Evaluate accuracy: details should match simulation events."
  ],
  "by_level": {
    "MFR": {
      "critical_focus": ["Scene safety and BSI", "Recognize respiratory distress", "Apply supplemental O2"],
      "additional_expectations": [],
      "grace_items": [
        "Albuterol SVN is NOT within MFR scope — do not penalize for not administering it."
      ]
    },
    "EMT": {
      "critical_focus": ["Scene safety and BSI", "PAT", "High-flow O2 via NRB", "Albuterol SVN 2.5 mg"],
      "additional_expectations": [
        "Recognize that tachycardia post-albuterol is expected — do not withhold treatment due to baseline tachycardia."
      ],
      "grace_items": [
        "Broselow tape NOT required — weight already known from parents.",
        "ALS request is governed by the active agency configuration; do not encode co-dispatch assumptions in the scenario."
      ]
    },
    "AEMT": { "critical_focus": ["All EMT expectations", "Consider IV access if patient deteriorates"] },
    "Paramedic": { "critical_focus": ["All EMT/AEMT expectations", "Consider repeat albuterol SVN"] }
  }
}
```

### `overall_considerations`
Array of scenario-specific clinical guidance for the debrief evaluator. Use these for case-specific emphasis, edge cases, and clinical facts that are true for this presentation.

Do **not** re-author global scoring policy here. The engine/base rubrics already own ALS co-dispatch applicability, PAT acronym credit, student-assessed vital credit, and CHART format. Scenario files must not include boilerplate such as "ALS request scoring follows the active agency configuration," "Do NOT penalize for not naming PAT," "Credit any vitals verbally requested," or "CHART format only." CI rejects those strings so the scenario remains clinical content instead of shadow documentation of engine behavior.

---

### Acceptable repetition vs. prohibited drift

Structural repetition across scenario files is **acceptable** when the content is clinically contextual — specific to this call type, this patient, or this intervention — even if the pattern recurs across many scenarios.

**Acceptable (clinically contextual, leave in scenario JSON):**
- `scope_no_iv_io*` checklist items that name the specific BLS alternative for this call (e.g., "albuterol SVN," "naloxone IN," "oral glucose"). The feedback is scenario-specific even though the pattern recurs.
- `dmist_components.T.required_elements` that describe scenario-specific transport decisions ("rapid transport decision," "ALS intercept or rendezvous decision," "mandatory report"). These add content beyond the universal ALS handoff rule.
- `dmist_components.*.scoring_note` entries that identify which clinical signs are primary for this call type ("Primary S elements for hypoglycemia: BGL and mental status"). These are condition-specific grading context, not a re-authored grading model.
- `by_level` scope or expectation language that differentiates provider expectations for this specific call type.

**Prohibited drift (global engine policy re-authored in scenario JSON):**
- Any `scoring_note` that contains "Award X/Y if," "Award 0/2 only if," or "fabricates" — grading formulas belong in `ai_client.py`, not in scenario files.
- Any `overall_considerations` or `narrative_considerations` text that repeats engine-owned rules (ALS co-dispatch applicability, PAT acronym policy, CHART format, vital fabrication penalty). CI rejects these strings.
- `dmist_components.T.required_elements` containing bare `"ALS readiness"` when `turnover_target == "als"` — ALS handoff readiness is universal engine policy and must not be listed as a scenario-specific requirement.
- `dmist_components.I` authored as interventions performed rather than injuries/illness details. CI rejects this via `_is_legacy_intervention_i_config()`.

The distinction to preserve: **scenario JSON describes the patient and the scene; the engine decides what clinical documentation matters and how to score it.** When those responsibilities blur, the scenario becomes a shadow copy of engine documentation that drifts independently.

---

### `dmist_considerations`
DMIST-component-by-component grading guidance. One bullet per DMIST letter.

### `narrative_considerations`
Scenario-specific CHART content guidance. The CHART format itself is universal and engine-owned; this field should only describe what clinical details matter for this scenario, what facts must match the run, and any scenario-specific objectivity/accuracy concerns.

### `by_level`
Provider-level-specific grading. **All four levels (MFR, EMT, AEMT, Paramedic) are required for every new scenario.** "EMT at minimum" was the legacy bar — new scenarios must cover all levels so that AEMT and Paramedic students receive appropriate expectations rather than generic EMT feedback.

Each level object has:

| Field | Purpose |
|-------|---------|
| `critical_focus` | Actions this level is primarily graded on. AEMT adds IV consideration on top of EMT focus. Paramedic adds advanced airway, hemodynamics, and pharmacology. |
| `additional_expectations` | Higher-order thinking expected at this level. Escalates with level. |
| `grace_items` | Things NOT to penalize at this level. Typically consistent across EMT/AEMT with Paramedic adding pharmacologic grace nuances. |
| `required_interventions` | Per-level override for deterministic scoring — see below |

**AEMT pattern:** Start with "All EMT expectations above," then add IV/IO access considerations, monitoring escalation triggers, and what to do if the patient deteriorates beyond BLS scope.

**Paramedic pattern:** Start with "All EMT and AEMT expectations above," then add advanced airway plan, pharmacologic options, hemodynamic targets, and any hospital-level interventions to explicitly exclude from field scope.

**Multi-tenant note:** `by_level` is the primary mechanism for adapting feedback to the tenant's provider level. A tenant deploying exclusively at EMT level will only consume EMT feedback, but the other levels must be authored so the scenario is portable to multi-level deployments without re-authoring.

### `required_interventions` (deterministic pre-scoring)

The debrief engine can check specific interventions against the database record **before** passing the transcript to the LLM. This bypasses AI judgment for mandatory treatments — the result is objective and cannot be hallucinated.

```json
"scoring": {
  "required_interventions": ["albuterol_svn", "o2_nrb"],
  "by_level": {
    "MFR": {
      "required_interventions": ["o2_nrb"]
    },
    "EMT": {
      "required_interventions": ["albuterol_svn", "o2_nrb"]
    }
  }
}
```

**Resolution order:** `by_level[level].required_interventions` → `scoring.required_interventions` → `[]` (neither required). The per-level list completely replaces the top-level list — it does not append.

The debrief prompt receives a `REQUIRED INTERVENTIONS` block showing `[APPLIED]` or `[MISSING]` for each ID, confirmed against the DB session record. The AI is instructed to treat these as pre-scored facts and not re-evaluate them from the chat transcript.

**Use `required_interventions` for:** interventions that are unambiguously mandatory at a given scope level and where AI re-evaluation from transcript alone is unreliable (e.g., a treatment the student could have applied silently via the action menu rather than chatting about it).

**Do not use for:** interventions that require contextual judgment (e.g., whether a specific dose was appropriate), recommended but non-mandatory actions, or items that can reasonably be evaluated from the transcript.

### `scoring.required_assessments` — Scenario-declared clinical exam steps

`required_assessments` declares the physical exam and clinical assessment steps that are expected standard workup for this specific presentation — things a competent provider should perform regardless of what they find. These are **what to check**, not **what to do** (which belongs in `required_interventions`).

```json
"scoring": {
  "required_assessments": [
    {
      "id": "lung_sound_auscultation",
      "description": "Auscultate lung sounds (stridor vs. wheeze distinction)",
      "keywords": ["lung sounds", "breath sounds", "auscultate", "listen", "wheeze", "stridor"],
      "missing_deduction": 3,
      "note": "Distinguishing stridor from wheeze is the central clinical decision point — reaching for albuterol without auscultation is the most common dangerous error."
    }
  ]
}
```

| Field | Required | Description |
|---|---|---|
| `id` | yes | Stable identifier (snake_case) |
| `description` | yes | Plain-language description of the expected assessment |
| `keywords` | yes | Keyword list — any match in transcript or findings records confirms presence |
| `missing_deduction` | yes | Points deducted from Clinical Performance when absent |
| `note` | recommended | Clinical rationale injected into the evidence packet as scoring context |

**Detection:** The evidence packet checks each keyword (word-boundary match) against the student chat transcript and session findings records. Presence in either source confirms the assessment occurred. If no keyword matches, the assessment is flagged as a scored gap.

**Back-credit rule:** A missed `required_assessments` item cannot be credited from the submitted DMIST or narrative. Documentation of an assessment is not evidence that the assessment occurred during the run — only transcript or findings evidence counts.

**Keyword authoring guidance:**
- Include synonyms and common phrasings (students rarely use clinical terminology verbatim in chat)
- Include relevant numeric values when they would appear in the transcript (e.g., `"38"` for a specific BG value)
- Avoid overly broad terms that would match unrelated content
- 5–10 keywords per item is typical; more is better for high-variability language

---

### `scoring.required_screens` — Scenario-declared differential diagnosis screens

`required_screens` declares condition-specific differential reasoning steps — active clinical decisions to rule in or rule out a dangerous alternative diagnosis. These are distinct from `required_assessments` (which are standard exam steps) because a missed screen reflects a failure of *clinical reasoning*, not just a missed exam action.

```json
"scoring": {
  "required_screens": [
    {
      "id": "epiglottitis_screen",
      "description": "Epiglottitis differential screen (rule out drooling, tripod positioning, toxic appearance)",
      "keywords": ["epiglottitis", "drool", "drooling", "tripod", "toxic appear"],
      "missing_deduction": 3,
      "note": "Epiglottitis is a life-threatening mimic of croup. Active ruling-out is expected clinical reasoning at the EMT level and above."
    }
  ]
}
```

Schema is identical to `required_assessments`. The distinction matters for debrief language: a missed required assessment gets "you should have auscultated lung sounds"; a missed required screen gets "you did not rule out epiglottitis — here is why that matters clinically."

**When to add `required_screens`:** Only when there is a dangerous differential that a competent provider at the target level should actively consider given this specific presentation. Not every scenario warrants `required_screens`. Current examples: croup (epiglottitis), febrile seizure (meningitis), AMS (alternate etiology screening).

---

### `scoring.corroboration_rules` — Per-scenario deduction caps for Tier 2 violations

`corroboration_rules` annotates Tier 2 corroboration findings with explicit per-scenario deduction ceilings. Without this field, each unsupported claim defaults to a 2-point deduction cap. Use `corroboration_rules` when a specific DMIST component or narrative chart element carries higher or lower clinical stakes than the default allows.

```json
"scoring": {
  "corroboration_rules": {
    "dmist": {
      "I": {
        "max_deduction_per_violation": 3,
        "note": "Epinephrine route (IM vs auto-injector) is clinically critical — wrong route in the DMIST is a significant documentation error"
      }
    },
    "narrative": {
      "R": {
        "max_deduction_per_violation": 2,
        "note": "Treatment response claims must match the actual patient trajectory recorded in findings"
      }
    }
  }
}
```

| Field | Required | Description |
|---|---|---|
| `dmist` | no | Map of DMIST component letter → rule. Keys are the single-letter component identifiers (`D`, `M`, `I`, `S`, `T`). |
| `narrative` | no | Map of CHART element letter → rule. Keys match the narrative chart elements (`C`, `H`, `A`, `R`, `T`). |
| `max_deduction_per_violation` | yes (within a rule) | Maximum points the LLM may deduct per unsupported claim in this component/element. Integer 1–5. |
| `note` | recommended | Clinical rationale injected into the scoring guidance for this rule. |

**Default behavior:** Any unsupported claim without a matching rule in `corroboration_rules` defaults to `max_deduction_per_violation: 2`. This default is conservative — increase only when a wrong claim carries direct patient-safety consequence (e.g., wrong drug route or dose documented in the DMIST handoff).

**When to override the default:**
- Increase to 3–4 for documentation errors that would cause a receiving provider to take a harmful action (e.g., wrong epi route/dose, wrong dressing type on large burn).
- Decrease to 1 for elements where a minor inaccuracy is expected (e.g., imprecise BSA estimate, approximate timing).
- Leave absent for standard documentation expectations where the 2-point default is appropriate.

**Relationship to Tier 2 pre-pass:** `corroboration_rules` only applies when the Tier 2 LLM pre-pass runs and returns unsupported claims. If the pre-pass is unavailable (API timeout, fallback), Tier 1 structural corroboration applies and `corroboration_rules` has no effect.

---

### Canonical DMIST model

> **CRITICAL authoring rule enforced by CI gate (`test_scenario_contracts.py::TestDmistComponentContracts`).**
> Any scenario that authors DMIST I as "interventions performed" will fail CI. Fix the content — do not skip the test.

The canonical meaning of each DMIST component is:

| Letter | Meaning | What belongs here |
|---|---|---|
| **D** | Demographics | Patient name, age, sex, weight. Pediatric patients must include weight when relevant to dosing/Broselow. |
| **M** | Mechanism / Chief complaint | How the emergency happened or what the patient is presenting with. Onset, mechanism, context. |
| **I** | **Injuries or illness details** | The clinical problem itself: injury findings, illness details, presenting symptoms, relevant history, and clinical assessment results (e.g., BGL, pupil status). **NOT treatments or interventions.** |
| **S** | Signs and symptoms | Objective signs at handoff: GCS, SpO2, HR, RR, BP, key exam findings. |
| **T** | Treatment, response, and transport | What was done, patient response to treatment, and disposition/transport plan. |

**The most common authoring error** is placing treatments and interventions under I instead of T. Examples of things that belong under **T**, not I:
- "naloxone 2 mg IN administered"
- "albuterol MDI given via spacer"
- "splint applied to left forearm"
- "patient positioned supine with legs elevated"
- "dry dressing applied"

These are treatments. DMIST I is for the **problem** (injuries, illness), not the **response** (treatments). The CI gate enforces this by running `_is_legacy_intervention_i_config()` against every authored I config.

### `scoring.dmist_components` — Per-component DMIST authoring expectations

`dmist_components` provides scenario-specific definitions of what each DMIST component should contain. The Phase 6 documentation pre-pass uses this to apply per-component corroboration checks against run evidence.

```json
"scoring": {
  "dmist_components": {
    "D": {
      "description": "Patient demographics",
      "required_elements": ["name", "age", "weight"],
      "corroboration_source": "scenario_patient_fields"
    },
    "M": {
      "description": "Mechanism and chief complaint",
      "required_elements": ["chief complaint or diagnosis", "onset or mechanism"],
      "corroboration_source": "any"
    },
    "I": {
      "description": "Illness details — [describe the clinical problem, not the treatment]",
      "required_elements": [
        "key illness/injury finding 1",
        "key illness/injury finding 2",
        "relevant assessment result (e.g., BGL, pupil status, BSA estimate)"
      ],
      "corroboration_source": "history_and_findings",
      "note": "I is illness/injury, not interventions. Treatments belong under T."
    },
    "S": {
      "description": "Signs — current patient status",
      "required_elements": ["key vital(s) or clinical findings for this presentation"],
      "corroboration_source": "vitals_and_findings"
    },
    "T": {
      "description": "Treatment, response, and transport",
      "required_elements": [
        "intervention(s) performed with method/dose/route",
        "patient response to treatment",
        "transport plan and readiness"
      ],
      "corroboration_source": "any"
    }
  }
}
```

| Field | Required | Description |
|---|---|---|
| `description` | yes | Plain-language label for this component in this scenario context |
| `required_elements` | yes | Minimum elements expected in this component — scenario-specific |
| `corroboration_source` | yes | Evidence source the Phase 6 pre-pass uses to validate claims |
| `note` | recommended | Clinical rationale for the corroboration rule — especially for I and S |

**`corroboration_source` values:**

| Value | Valid for | Meaning |
|---|---|---|
| `scenario_patient_fields` | D | Validated against the scenario's patient fields (name, age, weight, chief complaint) |
| `history_and_findings` | I | Validated against patient history and clinical assessment findings |
| `scenario_vitals_and_exam` | I | Validated against scenario-defined exam and vitals baseline |
| `vitals_and_findings` | S | Validated against **student-assessed** vitals only (SessionFinding vital rows) — not the scenario baseline |
| `vitals_engine` | S | Same as vitals_and_findings; legacy alias |
| `any` | M, T | Cross-validated against run context — clearly inconsistent claims are flagged |
| `intervention_timeline` | **T only** | **Do NOT use for I.** Validated against applied intervention records. CI gate rejects `intervention_timeline` on the I component. |
| `intervention_record` | **T only** | **Do NOT use for I.** Legacy alias for `intervention_timeline`. CI gate rejects this on I. |

**S component authoring note:** `vitals_and_findings` validation uses only the vital types the student actually obtained during the run. SpO2 is exempt as passively observable. A student who claims full vital set in the DMIST but only obtained SpO2 during the run loses S-component credit for the fabricated values. Author `required_elements` to reflect the most clinically relevant vital(s) for this specific complaint, not the full panel.

---

### `scoring.suppress_universal` — Universal Base opt-out

The Universal Base Standard fires 7 presence checks for every scenario (scene safety, PPE, primary survey, history, vitals, reassessment, disposition, documentation). Any element can be suppressed with an explicit declaration:

```json
"scoring": {
  "suppress_universal": ["scene_size_up", "history_assessment"]
}
```

**Valid suppression IDs:** `scene_safety`, `ppe`, `primary_survey`, `history`, `vitals`, `reassessment`, `disposition`, `documentation`

Suppression removes the element from both presence-check evaluation AND debrief feedback. A suppressed element does not appear in the evidence packet gaps or the LLM's scoring guidance.

**Suppression is rare and requires documented clinical rationale** in `scoring.overall_considerations`. Example valid use: a scenario where the student arrives to a pre-packaged patient with a complete handoff already in progress may suppress `scene_safety` and `primary_survey` evaluation. If you suppress an element without documenting why, future scenario review will treat it as an authoring error.

Most scenarios leave this field absent (empty suppression list is the default).

### Scene entry fields (deterministic professionalism scoring)

Three fields are captured via UI popups at scene entry and fed into the debrief as verified data:

| Field | Values | Scoring effect |
|---|---|---|
| `ppe_donned` | Array — `["Gloves", "Eye Protection"]` etc. | If gloves and eye protection are not both present: Professionalism score is hard-capped at 9/10 by the backend before the LLM grades |
| `scene_approach` | `"direct_contact"` or `"waited_for_pd"` | Injected as a scene safety fact — influences Clinical Performance scoring for scene safety |
| `pat_assessment` | `"sick"`, `"not_sick"`, or `null` (non-peds) | Scored ±3 pts (correct) or −2 pts (incorrect) against `patient.pat.expected`; adjustment is forced onto the LLM as a hard value |

These fields are not authored in scenario JSON — they are captured from the student at scene entry. However, they affect scoring meaningfully and scenario authors must account for them when writing `scoring.overall_considerations` and `by_level.grace_items`. For example: if PPE is always correctly donned in testing, it should not need to be in grace_items. If the scenario involves a scene safety nuance (e.g. hazmat — scene approach matters), note it in `scoring.overall_considerations`.

---

### Phase 6 Scoring Model — Universal Rules

The following rules are applied universally by the Phase 6 documentation and professionalism scoring passes. They are **not scenario-specific** — the scenario provides context (via `dmist_components`, `corroboration_rules`, `dmist_considerations`, `narrative_considerations`) that makes these universal rules apply correctly per call. Authors do not change the scoring model; they configure the inputs.

Authoring boundary:

- ALS request/intercept credit is resolved from active agency configuration and scenario applicability gates. Do not document co-dispatch assumptions in scenario JSON.
- PAT is credited from the captured assessment of appearance, work of breathing, and circulation to skin. Do not add scenario boilerplate saying the learner need not say the acronym.
- Vitals credit is based on run evidence for what the learner requested or obtained. Do not repeat that rule in `overall_considerations`.
- CHART is the universal narrative model. Scenario `narrative_considerations` should describe scenario-specific content, not restate the CHART format.

#### DMIST (0–10) — Per-component

D/M/I/S/T each score at approximately 2 points:

| Component | Full (2 pts) | Partial (1 pt) | Zero (0 pts) |
|---|---|---|---|
| D — Demographics | Accurate, complete; pediatric patients include weight when relevant to handoff/dosing | Missing one element | Absent or wrong |
| M — MOI / chief complaint | Mechanism of injury for trauma OR chief complaint / nature of illness for medical | Partial or vague | Absent |
| I — Injuries / illness | Trauma injuries OR medical illness details/history relevant to this call | Partial | Absent or clearly wrong |
| S — Signs / symptoms | Current signs, symptoms, assessment findings, and assessed vitals | Partial status without key findings | Absent or fabricated |
| T — Treatment / transport | Treatments performed, response, and transport/turnover plan as applicable | Partial treatment or disposition | Absent or fabricated |

**Calibration:** 10 = all accurate; 7–9 = minor gap; 4–6 = one component absent/fabricated; 1–3 = two+ absent/fabricated. Template DMIST with accurate D/M but fabricated S/T → 4–5/10.

#### Narrative (0–20) — Per-CHART-element

C/H/A/R/T each score at approximately 4 points:

| Element | Full credit | Key deductions |
|---|---|---|
| C — Chief complaint | Accurate, specific | Vague or absent |
| H — History | Accurate event/history | Inaccurate or absent |
| A — Assessment | Matches run-obtained findings | Fabricated vitals: −2 to −3 pts |
| R — Treatments | Matches applied interventions | Fabricated intervention: −2 pts; MCA-critical treatment fabricated: full R deduction |
| T — Transport/Transfer | Consistent with transport decision | Fabricated or contradicted |

**Calibration:** 18–20 = all accurate; 13–17 = one gap; 8–12 = two elements or A/R fabricated; 0–7 = mostly absent/fabricated. Subjective language without objective data (e.g., "vitals stable") = −1 to −2 pts across affected elements.

**PCR header rule:** The PCR header is part of the patient care record. If the header already contains patient name, age/DOB, and weight from valid patient-scoped tags obtained during the session, do not penalize the CHART narrative for not repeating those demographics in the prose. This does not change DMIST scoring; DMIST remains the submitted verbal handoff text and must include any D-component details required for the receiving crew.

#### Professionalism (0–10) — Tiered scale

| Score | Description |
|---|---|
| 9–10 | Engaged, professional, compassionate throughout |
| 7–8 | Adequate with one gap |
| 5–6 | Mixed — task-focused with little patient/caregiver engagement |
| 3–4 | Minimal — task-only, no warmth or explanation |
| 1–2 | Poor — curt, alarming, or dismissive |

Passive communication that avoids errors but never engages the patient or family scores 5–6, not 8–10. This replaces the legacy "thinness ≠ deduction" policy.

#### Student-assessed vitals distinction

Phase 6 S-component corroboration uses only the vital types the student actually obtained (SessionFinding vital rows). The scenario's baseline vitals define what is *clinically correct* — they do not credit the student automatically. SpO2 is exempt as passively observable.

This matters for documentation integrity: a student who claims "HR 148, RR 44, SpO2 93%, BP 90/60" in their DMIST but only ran SpO2 during the run documented vitals they did not assess. The deduction applies to the S component of the DMIST, not as a general documentation penalty.

#### Trauma scenarios — Adaptation guidance

When migrating trauma scenarios, the per-component DMIST model adapts its emphasis:

- **D**: Same (demographics; weight for peds)
- **M**: Mechanism of injury, kinetic forces, and scene findings replace chief-complaint framing
- **I**: Hemorrhage control, spinal precautions, specific trauma interventions; weight-based drug dosing if peds
- **S**: GCS/AVPU, vital trend, and mechanism-specific exam findings take priority over isolated individual vital values
- **T**: Transport urgency, destination (trauma center activation), en-route care plan

Narrative emphasis also shifts: R focuses on hemorrhage control, packaging, and pain management; T on transport decision, trauma activation communication, and en-route reassessment expectations.

Declare `base_patient_care_rubric: "nremt_trauma_v1"` (not the medical E202 base) for all trauma scenarios.

---

## 15. Scoring Rubric

Point distribution for the 100-point scale. The AI uses `full_credit`, `partial_credit`, and `minimal_credit` descriptions to place the student.

```json
"scoring_rubric": {
  "clinical_performance": {
    "max": 40,
    "full_credit": "Scene safety, PAT completed, high-flow O2 via NRB applied early, albuterol SVN administered, OPQRST/SAMPLE obtained, vitals reassessed and documented",
    "partial_credit": "O2 and assessment completed but albuterol delayed or omitted; or post-treatment reassessment not documented",
    "minimal_credit": "Scene safety and basic assessment only — albuterol (the critical BLS intervention) not administered"
  },
  "narrative": {
    "max": 20,
    "full_credit": "CHART complete: why called, what found (tripod, wheeze, SpO2 94%), what done (NRB + albuterol with dose/time), patient response, disposition. Objective throughout.",
    "partial_credit": "Most CHART elements present but missing treatment response or disposition",
    "minimal_credit": "Narrative present but missing multiple CHART elements"
  },
  "protocols_treatment": {
    "max": 20,
    "full_credit": "Protocol-aligned treatment plan: high-flow O2 applied early, albuterol SVN administered when indicated, reassessment performed, and escalation/turnover prepared.",
    "partial_credit": "O2 and assessment completed but albuterol delayed or omitted; or treatment response/reassessment not acted on.",
    "minimal_credit": "Critical indicated treatment omitted or treatment plan materially inconsistent with protocol."
  },
  "scope_adherence": {
    "max": 20,
    "full_credit": "Stayed within authorized scope; no out-of-scope attempts or MCA expansion errors",
    "partial_credit": "No dangerous out-of-scope intervention, but scope reasoning was incomplete or an MCA-specific scope requirement was misunderstood",
    "minimal_credit": "Out-of-scope intervention attempted or ordered"
  },
  "dmist": {
    "max": 10,
    "full_credit": "D: 4-year-old male, 40 lbs; M: asthma exacerbation, no MDI; I: NRB + albuterol SVN with time and response; S: RR, SpO2 trend, wheeze; T: current status and disposition",
    "partial_credit": "3–4 of 5 components present",
    "minimal_credit": "2 or fewer components present, or critical treatment information absent"
  },
  "professionalism": {
    "max": 10,
    "full_credit": "Introduced self, explained procedures to parent and child, addressed child by name, communicated treatment plan and side effects, used age-appropriate language",
    "partial_credit": "Communication present but mechanical; child not addressed directly",
    "minimal_credit": "Focused only on medical tasks without patient or family interaction"
  }
}
```

**Total: 100 points.**
- Clinical Performance: 40
- Narrative: 20
- Protocols & Treatment and/or Scope Adherence: 20
- DMIST: 10
- Professionalism: 10

`protocols_treatment` and `scope_adherence` are distinct deterministic categories. Put in-scope treatment quality, protocol alignment, contraindicated care, oxygen/medication/positioning decisions, and missed indicated interventions in `protocols_treatment`. Reserve `scope_adherence` for true scope-of-practice issues: out-of-scope attempts, provider-level violations, active refusal of indicated in-scope care due to scope misunderstanding, or MCA expansion errors. A scenario may use one or both categories; the assessment denominator is resolved from the effective checklist, not from a hardcoded assumption that only one treatment bucket exists.

### Rubric template system

All scenarios use the base template `ems_standard_v1` defined in `docs/rubric_templates/ems_standard_v1.md`. Read that document before authoring a scoring rubric. It provides:

- The complete JSON scaffold to copy into `scoring_rubric` and `scoring.by_level`
- Pre-written structural framing for the bands where language is consistent across scenarios (DMIST partial/minimal, narrative partial opener)
- An explicit taxonomy of what is fixed vs. scenario-authored
- The "do not template" list — fields that must remain scenario-specific

**Summary of what is fixed and what you must write:**

| Field | What to do |
|---|---|
| `scoring_rubric` point values | Copy from template unless the effective checklist contract explicitly defines a different dynamic category split |
| `clinical_performance` all bands | Write from scratch — 100% scenario-specific |
| `narrative` full_credit | Write the specific CHART content for this condition |
| `narrative` partial/minimal | Use template framing; fill in the specific missing element |
| `protocols_treatment` all bands | Write from scratch when used — this is for in-scope treatment quality, protocol alignment, contraindicated care, and missed indicated interventions |
| `scope_adherence` all bands | Write from scratch when used — this is only for true scope-of-practice/provider-level/MCA-scope issues |
| `dmist` full_credit | Write the D/M/I/S/T for this patient and presentation |
| `dmist` partial/minimal | Use template framing; fill in the critical missing DMIST element |
| `professionalism` full_credit | Write the specific communication actions for this scenario |
| `professionalism` partial | Use template framing; fill in the specific deficit |
| `professionalism` minimal_credit | Write to the scene dynamic — not verbatim-copyable. Medical scenarios: communication absence. Trauma with family: scene control. Subtle presentation: dismissiveness. Painful procedure: failure to prepare. |
| `by_level.MFR/EMT/AEMT/Paramedic` | Write condition-specific critical_focus; use template scaffold for structure |

---

## 15a. Checklist Items

The `checklist` array is the scenario's contribution to the deterministic scoring engine. Every item here becomes part of the effective checklist resolved at session start — alongside base rubric items inherited from `base_patient_care_rubric` and any `additional_patient_care_rubrics` (if declared).

**The scoring engine computes `category_max` from checklist items at runtime.** The rubric's declared max has no effect on actual scoring. The debrief and frontend must use the engine-computed max carried in the session score snapshot / structured subscore `_maxes`, not a hardcoded rubric number.

### Category sum rule (non-negotiable)

For every deterministically scored category, the sum of `point_value` for all non-`bonus` checklist items in that category — including items inherited from `base_patient_care_rubric` — is the authoritative category maximum.

```
sum(item.point_value for item in effective_checklist
    if item.category == cat and item.required != "bonus")
== score_snapshot.categories[cat].max
```

**Validate this before merging any scenario.** The easiest way to verify:

```bash
python3 - <<'EOF'
import json, sys
sys.path.insert(0, 'app')
from app.checklist import load_checklist
with open('app/scenarios/path/to/your_scenario.json') as f:
    d = json.load(f)
items = load_checklist(d, 'EMT', 'mi_base', None)
rubric = d.get('scoring_rubric', {})
for cat in ('clinical_performance', 'protocols_treatment', 'scope_adherence'):
    item_sum = sum(i.point_value for i in items if i.category == cat and i.required != 'bonus')
    rub_max = (rubric.get(cat) or {}).get('max')
    if rub_max and item_sum != rub_max:
        print(f'FAIL {cat}: items={item_sum} rubric={rub_max}')
    elif rub_max:
        print(f'ok   {cat}: {item_sum}')
EOF
```

### Clinical performance coverage requirements

Clinical performance checklist items must cover the full NREMT E202-equivalent assessment flow. The easiest path is to declare `base_patient_care_rubric: "nremt_e202_medical_v1"` (medical) or `"nremt_trauma_v1"` (trauma) — the base rubric provides these items for free. Primary cardiac-arrest/AED scenarios should declare `base_patient_care_rubric: "nremt_cardiac_arrest_aed_v1"`. Combined medical/trauma scenarios should keep one primary base and add the other through `additional_patient_care_rubrics`. Medical/trauma scenarios that deteriorate into arrest should add `"nremt_cardiac_arrest_aed_v1"` to `additional_patient_care_rubrics` so both the pre-arrest assessment and arrest management standards are scored. Scenarios without a base rubric must author equivalent items explicitly.

**Required CP coverage regardless of approach:**

| Domain | Base rubric item | Min point value |
|---|---|---|
| Scene safety / PPE | `ems.medical.scene_safety` / `ems.trauma.scene_safety` | 3–5 pts |
| Patient demographics | `ems.medical.patient_name` + `ems.medical.patient_age_dob` / `ems.trauma.patient_name` + `ems.trauma.patient_age_dob` | 2 pts |
| Primary assessment | `ems.medical.primary_assessment` / `ems.trauma.primary_assessment` | 4–6 pts |
| History taking | `ems.medical.history_attempt` / `ems.trauma.mechanism_assessment` | 3–5 pts |
| Focused secondary assessment | `ems.medical.focused_assessment` / trauma atomic secondary items (`ems.trauma.head_*`, `ems.trauma.neck_*`, `ems.trauma.chest_*`, extremity PMS/CMS, posterior/lumbar, wounds) | 2–19 pts |
| Reassessment post-intervention | `ems.medical.reassessment` | 2–4 pts |
| Handoff / transport disposition | `ems.medical.handoff` / `ems.trauma.transport_handoff` | 1–3 pts |

Condition-specific CP items (recognition, differential screening, critical clinical actions) are on top of these universal items. If a base rubric provides one of the above, do not re-author it as an overlay — the base item already covers it.

If a base rubric item is clinically inappropriate for a specific scenario (e.g., `hemorrhage_control` on a syncope scenario), suppress it using the `applicable_if` filter on the item definition or file a base rubric override. Do not omit a required domain without an explicit reason.

### Protocols & Treatment / Scope Adherence coverage requirements

PT/SA items define the protocol compliance obligations for the call. Rules:

1. **Items must sum to the rubric max** (see category sum rule above).
2. **Every contraindicated treatment for this complaint and level must have a required item.** If albuterol is contraindicated for croup, there must be a `required` item penalizing its administration — not just a note in `out_of_scope_bls`.
3. **Scope violation items must be `required`** with a non-trivial point value (≥ 5 pts for a clear scope violation). Optional scope items are appropriate only for actions that are in-scope but suboptimal.
4. **Do not use optional items to fill a coverage gap.** If you need 20 pts of PT/SA and only have 10 pts of clear required items, add more required items — do not pad with optional items that will never be `not_satisfied` for a typical student.

### Protocol-defining intervention rule

The `protocols_treatment` category must score the **protocol-defining treatment decision for the scenario**, not merely a generic supportive-care action.

For each scenario, identify the primary treatment question:

| Scenario pattern | Protocol-defining treatment item | Supportive care handling |
|---|---|---|
| Pediatric hypoglycemia, BG < 60, able to swallow | Oral glucose after eligibility/swallow confirmation | O2 is optional/supportive unless hypoxia or respiratory distress is present |
| Croup with stridor and agitation | Least-agitating oxygen strategy, upright with caregiver, calm environment, ALS/racepinephrine readiness | Delivery method and flow must match local protocol; do not require forced mask placement |
| Asthma with wheeze/bronchospasm | Bronchodilator therapy, oxygen when indicated, reassessment after treatment | Oxygen alone is not the defining treatment if albuterol is indicated |
| Anaphylaxis | Epinephrine timing/dose/route and airway/circulation support | O2/positioning are supportive but should not replace epi scoring |
| Seizure/AMS with normal oxygenation | Airway protection, glucose/temperature/etiology checks, indicated medication by level | O2 is supportive only when clinically indicated |

If a supportive action is acceptable but not required for the presented physiology, do **not** make it the only required `protocols_treatment` checklist item. This creates misleading failures such as scoring a normoxic hypoglycemia patient as `0/10 Protocols & Treatment` because O2 was not applied, even when oral glucose was correctly administered.

Use this authoring pattern instead:

```json
{
  "id": "scenario_id.protocol_primary_treatment",
  "description": "Protocol-aligned treatment — [primary indicated intervention] performed after [required eligibility/safety checks]; [supportive action] is optional unless clinically indicated",
  "subtype": "intervention",
  "category": "protocols_treatment",
  "point_value": 10,
  "required": "required",
  "tier1_match": {
    "source": "intervention",
    "intervention_key": "[primary_intervention_id]"
  }
}
```

Supportive-care actions can still appear as:

- a separate lower-value required item when the scenario physiology truly requires them (for example documented hypoxia),
- a `recommended_actions` item when they are good practice but not mandatory,
- a grace item in `scoring.by_level.*.grace_items` when the AI might otherwise over-penalize their absence,
- or part of the rubric prose as acceptable but not required.

When oxygen is used as a required checklist item, the description must include the clinical indication: hypoxia, respiratory distress, shock, poor perfusion, altered airway protection, or another protocol-specific reason. Avoid bare descriptions like “Supplemental O2 applied per protocol” unless O2 is truly the protocol-defining action for that scenario.

### Critical actions and checklist alignment

If an item appears in `correct_treatment.critical_actions` and is also scored in `checklist`, the IDs must intentionally align so timeline/debrief displays cannot contradict deterministic scoring.

Preferred pattern:

```json
"correct_treatment": {
  "critical_actions": [
    {
      "id": "oral_glucose",
      "description": "Administer oral glucose gel per protocol",
      "intervention_ids": ["oral_glucose"],
      "required": true
    }
  ]
},
"checklist": [
  {
    "id": "scenario_id.oral_glucose",
    "description": "Oral glucose gel administered per protocol after confirming eligibility criteria",
    "category": "clinical_performance",
    "tier1_match": { "source": "intervention", "intervention_key": "oral_glucose" }
  }
]
```

The critical action ID (`oral_glucose`) should match the suffix of the checklist item ID (`scenario_id.oral_glucose`) or include explicit `evidence` / `intervention_ids`. Do not use a different synonym such as `bg_awareness` when the checklist item is `blood_glucose_check`; that causes the debrief timeline to treat an already-credited item as possibly missed.

### Critical failure designation

If there is a NREMT-equivalent automatic-fail condition for this scenario — an action whose omission or commission represents an immediate patient safety failure regardless of overall performance — set `critical_failure: true` on that checklist item.

The base rubric scene_safety item already carries `critical_failure: true`. Add it to scenario overlay items for conditions like:

- Administering a clearly contraindicated medication (e.g., albuterol for upper airway obstruction/croup)
- Failing to treat a life-threatening finding that was identified (e.g., no O2 for documented hypoxia with SpO2 < 90%)

`critical_failure: true` surfaces a "Critical Safety Failure" badge in the debrief. It does not automatically zero the entire score — it is a prominent clinical flag for the student and instructor, in addition to the standard point deduction.

Do not overuse `critical_failure`. Reserve it for genuine patient-safety failures that an NREMT examiner would call a critical criterion failure. Missed bonus interventions, suboptimal technique, or protocol preference violations are not critical failures.

### Debrief feedback metadata

Four optional fields on every checklist item power the Phase 3 deterministic debrief renderer. When the renderer is active, it uses these instead of asking the LLM to generate per-item explanations — producing identical debrief text for identical performance.

| Field | Purpose | Required before Phase 3 E3 |
|---|---|---|
| `done_feedback` | One sentence shown when the item is credited: confirms what the student did and why it mattered. | Yes (required items only) |
| `missed_feedback` | One sentence shown when the item is missed: states what was expected and the consequence. | Yes (required items only) |
| `clinical_rationale` | The clinical why behind this item — shown in the item's detail row. | Recommended |
| `common_error` | The typical student mistake for this item — surfaced as a coaching note. | Recommended |

**Authoring rules:**

- `done_feedback` and `missed_feedback` must be factual, not motivational. "Bilateral lung sounds auscultated — correct; identifies wheeze, sets treatment baseline" not "Great job listening to lung sounds!"
- `missed_feedback` must state the specific gap, not a generic reminder. "Lung sounds not auscultated before treatment — wheeze character and air movement are required to differentiate asthma from croup or foreign body" not "Remember to assess lung sounds."
- `common_error` applies when a specific wrong action is predictable. For croup's racepinephrine item: `"Ordering racepinephrine as an EMT — this is an ALS/Paramedic medication; EMTs prepare and support ALS but cannot administer it independently."` Do not author generic common_error text that applies to every item.
- Base rubric items (`ems.medical.*`, `ems.trauma.*`) do not need these fields in scenario JSON — they receive centrally authored feedback in the base rubric definition.

**Example:**

```json
{
  "id": "peds_asthma_01.albuterol_svn",
  "description": "Albuterol 2.5 mg via SVN administered per protocol for bronchospasm",
  "category": "protocols_treatment",
  "subtype": "intervention",
  "point_value": 10,
  "required": "required",
  "done_feedback": "Albuterol SVN administered — correct first-line bronchodilator; expect SpO₂ improvement within 5–10 minutes.",
  "missed_feedback": "Albuterol SVN not administered — bronchospasm is the primary reversible cause of wheeze in a known asthmatic; withholding it leaves the airway obstruction untreated.",
  "clinical_rationale": "Beta-2 agonist bronchodilation is the protocol-mandated first-line treatment for asthma exacerbation.",
  "common_error": "Waiting for SpO₂ to drop below 90% before administering albuterol — treat bronchospasm on clinical signs of wheeze and distress, not just oximetry.",
  "tier1_match": { "source": "intervention", "intervention_key": "albuterol_svn" }
}
```

Until Phase 3 E3 is active, missing `done_feedback` / `missed_feedback` on required items generates a load-time warning (not an error). Add these fields incrementally using Phase 3 E2 priority order.

### Tier assignment rules

| Item subtype | Allowed tiers | Notes |
|---|---|---|
| `scene_entry` | `[1]` only | Backed by scene_entry popup — structured record required |
| `intervention` | `[1]` or `[1, 2]` | Prefer Tier 1; Tier 2 only if intervention cannot be captured via the action button (verbal-only actions) |
| `assessment` | `[1, 2]` | Tier 1 when a session finding record exists; Tier 2 for transcript confirmation |
| `screen` | `[1, 2]` by default; `[1, 2, 3]` only with explicit `tier3_permitted: true` and test coverage | Clinical reasoning must be evidenced live: structured Tier 1 event/finding or student transcript. Submitted DMIST/narrative does **not** satisfy `screen` items; documentation can improve DMIST/narrative quality but must not back-credit clinical reasoning. |
| `reassessment` | `[1, 2]` | Tier 1 preferred (session event); Tier 2 for transcript confirmation |
| `transport` | `[1, 2]` | Tier 1 preferred; Tier 2 for transcript confirmation |

**Never set `allowed_tiers: [3]` alone.** Tier 3 is a last resort; Tier 1 and Tier 2 must be attempted first.

### Minimum viable checklist

A valid scenario checklist (including base rubric items) must have at least:

- 1 scene_safety item (Tier 1, `critical_failure: true`)
- 1 primary assessment item
- 1 history / mechanism item
- 1 condition-specific recognition or clinical action item
- 1 reassessment item
- 1 transport or handoff item
- 1 PT/SA item covering the primary protocol compliance obligation for this scenario

Scenarios that declare `base_patient_care_rubric` automatically satisfy the first six requirements from the base.

---

## 16. Exemplars

Benchmarks for a perfect DMIST and CHART narrative. The AI compares the student's submission against these to calculate sub-scores.

```json
"exemplar_dmist": "D — Liam, 4-year-old male, 40 lbs (18 kg) per parents.\nM — Acute asthma exacerbation / difficulty breathing.\nI — Known asthma since age 2, wheezing after outdoor play on a high-pollen day, no MDI available.\nS — Initial SpO2 94%, RR 32, HR 128, GCS 15, bilateral expiratory wheeze with decreased air movement. Post-treatment SpO2 99%, RR 22, wheeze markedly reduced bilaterally.\nT — High-flow O2 via NRB at 15 LPM on arrival. Albuterol 2.5 mg via small-volume nebulizer at 6 LPM administered approximately 8 minutes ago. Patient clinically improved, monitoring for rebound, ready for transport.",

"exemplar_narrative": "Squad 1 was dispatched to 2847 Maple Street for a 4-year-old male with difficulty breathing. Upon arrival, patient Liam, a 4-year-old male weighing approximately 40 lbs, was found seated in a tripod position on the living room couch. Audible expiratory wheeze was noted from the doorway. Mother reported onset approximately 30 minutes prior following outdoor play on a high-pollen day. Known asthma, two prior ED visits, last 6 months ago. Albuterol MDI not available. NKDA.\n\nPrimary assessment: SpO2 94%, RR 32 with intercostal retractions and nasal flaring, HR 128, GCS 15. Bilateral expiratory wheeze, decreased air movement at bases. High-flow O2 via NRB at 15 LPM applied. Albuterol 2.5 mg via SVN at 6 LPM administered per WMRMCC protocol — 5-rights verbalized to partner.\n\nPost-treatment: SpO2 99%, RR 22, lung sounds cleared bilaterally. Patient transferred to Medic 1 ALS crew with full DMIST."
```

Write exemplars as multi-line strings (use `\n` for line breaks). DMIST should follow D/M/I/S/T letter headings. Narrative should follow CHART structure.

---

## 17. Debrief

Static teaching content delivered after the scenario regardless of performance.

```json
"debrief": {
  "condition_background": "Liam is a 4-year-old with known asthma who developed acute bronchospasm after outdoor play on a high-pollen day. His albuterol MDI was unavailable, making EMS nebulized albuterol the critical treatment...",
  "key_teaching_points": [
    "Tripod position — leaning forward, hands on knees — is a classic sign of significant respiratory distress",
    "Albuterol causes expected tachycardia — monitor but don't withhold treatment",
    "A near-silent chest (loss of wheeze in a wheezing patient) is a late ominous sign indicating critically reduced air movement"
  ],
  "common_mistakes": [
    "Laying the patient flat — always allow position of comfort for respiratory distress",
    "Delaying O2 while obtaining history — O2 first, THEN history",
    "Not reassessing and documenting vitals after interventions"
  ]
}
```

| Field | Purpose |
|-------|---------|
| `condition_background` | Pathophysiology and clinical context paragraph. Shown in the Condition section of debrief. |
| `key_teaching_points` | High-yield bullets for future calls. Shown in Key Takeaways. |
| `common_mistakes` | Frequent errors for this specific scenario. Shown in What Could Be Done Better if not already addressed. |

**Authored content policy:** All three fields — `condition_background`, `key_teaching_points`, and `common_mistakes` — are **required authored clinical content**. They are not generated by the AI at debrief time. The AI presents and connects this content to run-specific gaps; it does not generate pathophysiology, drug mechanisms, or treatment rationale from its own training data.

- Content must be authored by a clinical SME and reviewed for accuracy before publication.
- The `condition_background` field in `peds_croup_01.json` is the target quality level — it covers pathophysiology, the BLS challenge, relevant drug context, and the most common diagnostic error for that condition.
- All three fields must be present before the Phase 2 debrief prompt restructure goes to production. Missing content will be exposed in debrief output.
- See `AI_ARCHITECTURE.md §3.5` for the full authored vs. generated content policy.

---

---

## 18. Turnover Target

Declares who receives the final patient handoff. This is a **root-level, single-authority field** — it is the only place `turnover_target` may be set. Phase blocks (`als_phase`, `transport_phase`) describe their domain but do not carry a competing `turnover_target` sub-field. The root value is what the debrief prompt, DMIST framing, Lexi coaching, and AI narration read.

```json
"turnover_target": "als"
```

| Value | Meaning |
|---|---|
| `"als"` | Patient is handed off to an ALS crew on scene |
| `"hospital"` | Transport agency delivers patient directly to the receiving facility |
| `"none"` | No formal handoff occurs (e.g., patient refused transport, on-scene resolution) |
| `"dynamic"` | Runtime-determined — e.g., transport BLS that may or may not intercept ALS based on student action |

**`"dynamic"` resolution contract:** Runtime code must resolve `"dynamic"` to a concrete value before any surface that reads it, in this order: (1) turnover UI copy renders, (2) `_build_system_prompt()` injects operational context, (3) `_coachLexiContextPrompt()` builds coaching context, (4) `evaluate_and_generate_debrief()` is called. `"dynamic"` must never leak into prompt logic as a pseudo-value — if unresolved at debrief time, fail loudly.

**DMIST scoring when `turnover_target: "none"`:** The debrief marks the turnover section not applicable and returns `"dmist": 0` in the subscore JSON. This is an N/A result — the debrief text must explicitly state that no formal turnover occurred, so a zero score is not misread as a missed DMIST. The key is preserved in the JSON schema with no structural change.

---

## 19. Advanced Monitoring

Declares what monitoring equipment is physically present on this unit. This block answers **one question only**: is the device available? It does not encode what the device shows, whether using it is appropriate, or when using it is scored.

```json
"advanced_monitoring": {
  "cardiac_monitor_4lead": true,
  "ecg_12lead": true,
  "capnography": true
}
```

**Three-layer separation — authors must follow this:**

| Layer | Where it lives | What it encodes |
|---|---|---|
| Equipment presence | `advanced_monitoring` | Is the device on this unit? |
| What the device reveals | `vitals.baseline` (`cardiac_rhythm`, `ecg_findings`, `etco2`) | What the monitor shows when applied |
| Scoring appropriateness | Prompt / scoring rubric | Was using it clinically appropriate? |

Do not put interpretation rules, clinical criteria, or scoring language into the `advanced_monitoring` block. Authors who stuff those here break the separation and cause maintenance problems.

**v1 note:** These flags are booleans for now. Future scenarios may need finer granularity — e.g., equipment present but not standard on all units, available only after ALS intercept arrives, or available but outside the student's scope for this crew. Doc wording intentionally avoids implying booleans are permanent. When a scenario requires that nuance, bring it to the design team before authoring.

---

## 20. ALS Phase

Describes ALS intercept expectations. Relevant for non-transport agencies (student hands off to ALS on scene) and for transport agencies where ALS intercept occurs en route.

```json
"als_phase": {
  "indicated": true,
  "auto_dispatched": false,
  "on_student_request_only": true,
  "expected_communication": [
    "patient age/sex and chief complaint",
    "current vitals",
    "interventions performed and response",
    "scene location and ETA"
  ],
  "als_continuation_expected": [
    "IV access",
    "fluid bolus consideration",
    "12-lead acquisition"
  ]
}
```

| Field | Purpose |
|---|---|
| `indicated` | Whether ALS intercept is clinically indicated for this scenario |
| `auto_dispatched` | `true` = ALS co-dispatched by default (no student action needed; grace rule applies in debrief). `false` = student must explicitly request ALS. |
| `on_student_request_only` | If `true`, ALS does not arrive unless the student requests it — even if indicated |
| `expected_communication` | What the student should communicate when requesting or meeting ALS |
| `als_continuation_expected` | ALS-level interventions expected after the handoff — used by Lexi coaching and DMIST framing |

**`als_phase` does not contain `turnover_target`.** ALS intercept is a workflow — the handoff target is declared at root (§18).

**Debrief grace rule:** When `auto_dispatched: true`, the debrief engine tags ALS-related critical actions `[ALS-GRACE]` and does not penalize the student for not explicitly requesting ALS. When `auto_dispatched: false` and `indicated: true`, a missed ALS request is tagged `[LIKELY MISSED]` and evaluated under `clinical_performance`.

---

## 21. Transport Phase

Describes transport-capable unit expectations. Present only when the agency `service_type.transport` is true or the scenario explicitly models a transport workflow.

```json
"transport_phase": {
  "applicable": true,
  "destination": "Nearest ED with pediatric capability",
  "priority": "emergent",
  "reassessment_expectations": [
    "Reassess SpO2, RR, and work of breathing at least once en route",
    "Document patient response to treatment"
  ],
  "transport_events": []
}
```

| Field | Purpose |
|---|---|
| `applicable` | Whether this scenario involves a transport phase |
| `destination` | Plain-text destination for v1. **Evolution note:** future transport scoring may require structured fields — facility type, specialty capability, activation relevance, destination rationale. Do not author scenarios as if `destination` will always remain a string. |
| `priority` | `"emergent"` or `"non-emergent"` — affects scoring of transport decision appropriateness |
| `reassessment_expectations` | What the student is expected to reassess and document en route |
| `transport_events` | Placeholder array for future in-transport simulation events — **see below** |

**`transport_events` is design metadata — it is runtime-inert.** Until a true transport simulation phase is built, this field is not processed by the runtime, and the debrief must not infer that any event "happened" based solely on this field's content. Authors may populate it to document anticipated clinical events for design purposes; it will not affect scoring until the transport simulation phase is implemented.

**`transport_phase` does not contain `turnover_target`.** Transport is a workflow — the handoff target is declared at root (§18).

---

## 22. Pre-Arrival Report

Describes expectations for pre-arrival hospital communication. This is a separate scored concept from transport logistics — applicable any time a student should contact the receiving facility before arrival.

```json
"prearrival_report": {
  "required": true,
  "trigger_conditions": [
    "emergent transport",
    "pediatric patient"
  ],
  "required_elements": [
    "patient age/sex",
    "chief complaint",
    "mechanism or etiology",
    "current vitals",
    "interventions and response",
    "ETA"
  ],
  "recommended_elements": [
    "trauma activation flag",
    "special resource request"
  ]
}
```

| Field | Purpose |
|---|---|
| `required` | Whether pre-arrival communication is expected for this scenario |
| `trigger_conditions` | Conditions that make a pre-arrival report clinically appropriate — referenced in scoring rubric guidance |
| `required_elements` | Elements the student must include for full communication credit |
| `recommended_elements` | Elements that earn bonus credit if included |

**Scoring is transitional:** Pre-arrival communication is currently evaluated from the student's chat transcript and DMIST report — the debrief looks for evidence of hospital notification in the student's verbal behavior. This is an acceptable interim model. The target architecture replaces transcript inference with a backend-submitted pre-arrival report form (similar to the DMIST submission) that enables deterministic scoring. Until that UI exists, this is explicitly a transitional evaluation path, not the final deterministic model.

---

## 23. CI Authoring Gate

Every scenario must pass `tests/test_scenario_contracts.py` before merge.  The
suite runs in under a second and enforces contracts that are tedious to catch
manually and catastrophic to miss in production.

Run it locally after authoring or editing a scenario:

```bash
python -m pytest tests/test_scenario_contracts.py -v
```

### What the gate checks

| Contract | Test class | What fails |
|---|---|---|
| Required top-level fields | `TestScenarioRequiredFields` | Missing `id`, `title`, `category`, `turnover_target`, `vitals`, `checklist`, `exemplar_narrative` |
| `id` matches filename | `TestScenarioRequiredFields` | `scenario.id` doesn't equal the `.json` filename stem |
| `turnover_target` is a valid enum | `TestScenarioRequiredFields` | Any value outside `{"hospital", "als", "none"}` |
| `exemplar_dmist` non-empty when present | `TestScenarioRequiredFields` | Empty string or non-string value |
| `debrief` present unless exempt | `TestScenarioRequiredFields` | Missing `debrief` on non-orientation scenarios |
| `protocol_focus` present and specific | `TestClinicalContext` | Missing/empty `clinical_context.protocol_focus`, or focus contains only generic support concepts |
| No duplicate checklist IDs | `TestChecklistIntegrity` | Two items share the same `id` in `checklist[]` |
| Authored feedback strings non-empty | `TestChecklistIntegrity` | `done_feedback` or `missed_feedback` key exists but is empty or whitespace |
| Lung sound `correct_choice_id` | `TestLungSoundChallenge` | `lung_sound_challenge.enabled: true` without `correct_choice_id`; same for `post_treatment` |
| FTO-trigger notes need `indication_gate` | `TestIndicationGate` | Notes contain "not indicated", "contraindicated", or "not recommended" but no `indication_gate` dict |
| `indication_gate` schema valid | `TestIndicationGate` | Missing `status`/`reason`/`allowed_when`; `status` not in `{"not_indicated_now", "contraindicated"}` |
| HRM entries have `answer` and `triggers` | `TestHistoryResponseMap` | Active HRM entry missing `answer` or empty `triggers` list |
| Rich HRM has compound SAMPLE priority entry | `TestHistoryResponseMap` | ≥8 HRM entries with ≥3 SAMPLE-component keys and no priority entry |
| No duplicate call-type rubric item IDs | `TestCallTypeRubricIntegrity` | Duplicate `id` in a call-type rubric's `checklist_items` |
| Call-type rubric items complete | `TestCallTypeRubricIntegrity` | Missing required schema fields or empty feedback strings in `checklist_items` |

### Workflow for new scenarios

1. **Author the scenario JSON** following the Field Checklist below.
2. **Run the CI gate** — fix all failures before proceeding.
3. **Run the full suite** — `python -m pytest tests/ -q` — to confirm no regressions.
4. **Playtest for clinical realism** — manual testing focuses only on: correct AI behavior, clinical plausibility, persona quality, FTO card accuracy.  The gate has already verified structural completeness.
5. **Merge** — the gate is the merge bar for structure.  Clinical review is the merge bar for content.

### Adding a new contract

When a new structural invariant is identified during authoring or review, add it to `tests/test_scenario_contracts.py` as a parametrized test and update the table above.  Do not document the rule here without a corresponding test — documentation without enforcement drifts.

---

## Appendix: Field Checklist

Use this when creating a new scenario to verify completeness.

> **Before merging, run `python -m pytest tests/test_scenario_contracts.py -v` and confirm all tests pass.**  The checklist below covers authoring completeness; the CI gate covers structural correctness.  Both are required.

**Required:**
- [ ] `_schema`, `id`, `title`, `display_title`, `category`, `category_display`, `difficulty`, `scenario_number`
- [ ] `prerequisites` (array, can be empty)
- [ ] `protocol`
- [ ] `dispatch` (unit, text, priority, time, cross_streets, response_time_minutes)
- [ ] `scene` (description)
- [ ] `patient` (name, age, sex, weight_kg, weight_display, chief_complaint, general_impression, **`pcr_demographics_deferred: true`** — required on all clinical scenarios; hides patient identity from HUD header until obtained)
- [ ] `patient.pat` (impression, appearance, work_of_breathing, circulation, expected, teaching) — **required for all pediatric scenarios**
- [ ] `history` (allergies, medications, pmh, last_oral_intake, events_leading_to_call)
- [ ] `standard_exam_findings` for any Exam-menu physical findings that are abnormal, scored, clinically meaningful, or should not use the neutral default
- [ ] `vitals.baseline` (hr, rr, spo2, bp, gcs, skin_color, cap_refill, lung_sounds, work_of_breathing; add `bgl` for AMS/diabetic/peds scenarios)
- [ ] `vitals.baseline.cardiac_rhythm` — required if `ekg_monitoring` intervention is present
- [ ] `vitals.baseline.etco2` — required if `waveform_capnography` intervention is present
- [ ] `vitals.baseline.ecg_findings` — required if `12_lead_ecg` intervention is present
- [ ] `vitals.deterioration` (rates, caps)
- [ ] `vitals.interventions` (at least the scope-appropriate treatments)
- [ ] `personas` (patient + partner; family members as needed)
- [ ] `call_type` — NASEMSO call-type rubric slug (e.g. `"nremt_trauma"`, `"respiratory_distress"`, `"hypoglycemia"`, `"head_injury"`). Required on all clinical scenarios; must resolve to a file in `app/rubrics/nasemso/`. Choose the most specific reusable call type available; do not leave a head-injury scenario on generic `nremt_trauma` if the `head_injury` rubric applies. Run `validate_scenario()` to confirm no `call_type` error.
- [ ] Five scenario applicability flags — set all five explicitly on every clinical scenario (do not rely on concept inference or dispatch-text fallback):
  - [ ] `spinal_injury_possible: true/false`
  - [ ] `non_transport_agency: false` (default for transport agencies; only `true` for fire-only departments)
  - [ ] `multiple_patients_possible: true/false`
  - [ ] `diagnostics_indicated: true/false` (BGL, 12-lead ECG, or capnography as required standard workup)
  - [ ] `opqrst_radiation_relevant: true/false` (chest pain and abdominal pain only)
- [ ] `correct_treatment` (critical_actions, out_of_scope_bls — use `vocabulary.OUT_OF_SCOPE` IDs, not free-text strings; add `scene_entry_credited` / `protocol_indicated` / `evidence` where applicable)
- [ ] `correct_treatment.out_of_scope_aemt` — required on all scenarios; use empty list `[]` if AEMT has no additional restrictions beyond BLS
- [ ] `correct_treatment.out_of_scope_paramedic` — required on all scenarios; use empty list `[]` if Paramedic has no additional out-of-scope items (omitting entirely removes all Paramedic scope enforcement)
- [ ] `scoring.overall_considerations`, `scoring.by_level` — **all four levels (MFR, EMT, AEMT, Paramedic) required**; EMT-only authoring is no longer sufficient
- [ ] `scoring.overall_considerations` and `scoring.narrative_considerations` contain only scenario-specific clinical guidance — no ALS co-dispatch boilerplate, PAT acronym boilerplate, student-assessed vitals boilerplate, or CHART-format boilerplate
- [ ] `scoring.dmist_considerations` and `scoring.narrative_considerations` — scenario-specific guidance for per-component DMIST and per-CHART-element narrative scoring (see §14 Phase 6 Scoring Model)
- [ ] `scoring.dmist_components` — D/M/I/S/T component definitions with `required_elements` and `corroboration_source` per component (see §14 `scoring.dmist_components`)
- [ ] `scoring_rubric` (all 5 categories)
- [ ] `checklist` array with items covering **all** deterministically scored categories; run the category sum validator (see §15a) before merging
- [ ] `base_patient_care_rubric` declared (`"nremt_e202_medical_v1"` for medical scenarios, `"nremt_trauma_v1"` for trauma scenarios, `"nremt_cardiac_arrest_aed_v1"` for primary cardiac arrest/AED scenarios) — or equivalent CP coverage authored as overlay items covering all six required domains (§15a)
- [ ] **Mixed call-type scenarios** — declare `additional_patient_care_rubrics` when the presentation crosses assessment domains:
  - **Medical + Trauma** (e.g. diabetic patient with a fall injury): `base_patient_care_rubric: "nremt_e202_medical_v1"` + `additional_patient_care_rubrics: ["nremt_trauma_v1"]`. The secondary trauma rubric adds head-to-toe and injury management items; duplicate scene entry / generic ABC / vitals / reassessment items are suppressed automatically.
  - **Medical or Trauma deteriorating to arrest**: add `"nremt_cardiac_arrest_aed_v1"` to `additional_patient_care_rubrics`. The arrest rubric adds arrest recognition, CPR, and AED items; duplicate PPE and scene-safety items are suppressed.
  - **Medical + Trauma + Arrest**: `additional_patient_care_rubrics: ["nremt_trauma_v1", "nremt_cardiac_arrest_aed_v1"]`.
  - **Pure trauma or pure medical with no deterioration to arrest**: omit `additional_patient_care_rubrics` — the base rubric is sufficient.
  - Also set `call_type` to the dominant NASEMSO call-type rubric for the primary presenting complaint. If a secondary NASEMSO call-type overlay is clinically warranted, create a scenario overlay file in `app/rubrics/nasemso/overlays/` using `add_item` or `add_to_item` ops rather than a second `call_type`.
- [ ] `exemplar_dmist`, `exemplar_narrative`
- [ ] `debrief` (condition_background, key_teaching_points, common_mistakes)

**ALS and transport scenarios — required:**
- [ ] `turnover_target` — one of `"als"`, `"hospital"`, `"none"`, `"dynamic"` (root-level, single authority — see §18)
- [ ] `advanced_monitoring` — presence flags for `cardiac_monitor_4lead`, `ecg_12lead`, `capnography` (see §19)
- [ ] `als_phase` — when ALS intercept is part of the scenario (see §20)
- [ ] `transport_phase` — when a transport-capable agency workflow is involved (see §21)
- [ ] `prearrival_report` — when hospital pre-arrival communication is expected (see §22)
- [ ] `vitals.baseline.cardiac_rhythm` (with `image_asset: null`) — required when `advanced_monitoring.cardiac_monitor_4lead: true`
- [ ] `vitals.baseline.etco2` (with `image_asset: null`) — required when `advanced_monitoring.capnography: true`
- [ ] `vitals.baseline.ecg_findings` (with `image_asset: null`) — required when `advanced_monitoring.ecg_12lead: true`

**Strongly recommended:**
- [ ] `subtitle`, `version`, `objectives`
- [ ] `rubric_template: "ems_standard_v1"` — required for all new scenarios; enables future migration tooling
- [ ] `scoring.required_interventions` (and per-level variants) — for any mandatory intervention where AI re-evaluation from transcript alone is unreliable
- [ ] `readiness_criteria`
- [ ] `chat_placeholder`, `chat_address_hint`, `debrief_lexi_hints`
- [ ] `lung_sound_challenge` (if a respiratory or airway scenario)
- [ ] `vitals.improvement` (any scenario with a treatable condition)
- [ ] `correct_treatment.clinical_decision_points`
- [ ] `correct_treatment.recommended_actions`
- [ ] `scoring.dmist_considerations`, `scoring.narrative_considerations`
- [ ] Persona `aliases`, `clinical_state_instructions`, `persona_rules`

**CI contract checklist — run `python -m pytest tests/test_scenario_contracts.py -v` and confirm each passes:**
- [ ] `scenario.id` equals the `.json` filename stem (no extension)
- [ ] `turnover_target` is `"hospital"`, `"als"`, or `"none"`
- [ ] `exemplar_dmist` is a non-empty string if the key is present
- [ ] `debrief` is present (unless `is_orientation: true` or `debrief_exempt: true`)
- [ ] No two items in `checklist[]` share the same `id`
- [ ] Every `checklist` item that declares `done_feedback` or `missed_feedback` has a non-empty string value
- [ ] Every `lung_sound_challenge` with `enabled: true` has a non-empty `correct_choice_id` (check `post_treatment` separately)
- [ ] Every `vitals.interventions` entry whose `notes` contains "not indicated", "contraindicated", or "not recommended" has an `indication_gate` dict with `status`, `reason`, and `allowed_when`
- [ ] Every `indication_gate.status` is `"not_indicated_now"` or `"contraindicated"`
- [ ] Every active HRM entry has a non-empty `answer` and at least one `triggers` item
- [ ] If the HRM has ≥8 entries and ≥3 SAMPLE-component keys, there is a priority entry covering compound SAMPLE questions

**Best practices:**
1. `general_impression` must match `vitals.baseline` — if it says "pale and diaphoretic," `skin_color` must reflect that.
2. List `grace_items` for anything the AI might unfairly penalize — explicit protection is better than hoping the AI figures it out.
3. `out_of_scope_bls` entries must be IDs from `vocabulary.OUT_OF_SCOPE` (e.g. `"iv_io_access"`), not free-text strings. If the needed category is missing from the vocabulary, add it there first.
4. Write `detection_patterns` as regex — escape backslashes (`\\b`, `\\s`). Test against likely student phrasing.
5. The partner persona (`role: "ems_partner"`) must never volunteer or recommend interventions, assessments, oxygen devices, transport decisions, protocol steps, or next actions. The partner only follows direct commands or asks one narrow clarification question when the command is incomplete.
6. `persona_rules` and `clinical_state_instructions` are the most direct way to control AI behavior — use them for complex or non-verbal patients.
7. Scene entry data (PPE, scene approach, PAT) is captured by UI, not scenario JSON. Remember: missed PPE hard-caps Professionalism at 9/10; wrong PAT judgment applies a −2 Clinical Performance penalty. Mention these explicitly in `scoring.overall_considerations` if the scenario has any edge case (e.g., a scenario where waiting for PD is the correct scene approach).
8. Use `scoring.required_interventions` for treatments that are unambiguously mandatory — this ensures scoring accuracy even if the student applied the intervention silently via the action menu without discussing it in chat.
9. If authoring a multi-level scenario (EMT + AEMT + Paramedic), author `out_of_scope_aemt` and `out_of_scope_paramedic` explicitly. Do not assume AEMT inherits all BLS restrictions or that Paramedics have no restrictions — both assumptions can produce incorrect debrief scoring.
10. ALS monitoring interventions (`ekg_monitoring`, `waveform_capnography`, `12_lead_ecg`) must have a corresponding baseline vital field (`cardiac_rhythm`, `etco2`, `ecg_findings`) — the AI reads those fields to know what to report when the student applies the monitor. If the field is absent, the AI will improvise the finding, which breaks scenario determinism.
11. Set scope flags explicitly on every ALS-only intervention (`within_bls_scope: false, within_aemt_scope: false` for Paramedic-only; `within_bls_scope: false, within_aemt_scope: true` for AEMT+). Do not rely on absence of a flag to restrict scope — the default for a missing flag is permissive (in scope).
12. Do not author broad treatment phrases as device-specific detection patterns. For oxygen, phrases like `"oxygen"`, `"o2"`, and `"supplemental oxygen"` must not map to one device such as nasal cannula or NRB. Broad commands should require clarification or explicit learner selection.
