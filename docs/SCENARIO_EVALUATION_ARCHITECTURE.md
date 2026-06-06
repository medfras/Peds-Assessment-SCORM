# Scenario Evaluation Architecture

**Project:** RescueTrails EMS Simulator
**Status:** Active Implementation — Phase 1 complete; Phase 2 fully complete (2026-04-24)
**Audience:** Developers and AI coding agents implementing debrief and scoring changes
**Depends on:** `AI_ARCHITECTURE.md`, `SCENARIO_DESIGN_EMS.md`, `DEVELOPMENT_GUIDELINES.md`

> **Target Architecture Notice:** This document describes the current (Phase 2) implementation, including transitional elements. The next-generation unified checklist scoring engine is defined in [`SCORING_ENGINE_ARCHITECTURE.md`](SCORING_ENGINE_ARCHITECTURE.md). Supersession is element-by-element — this document remains authoritative for every scoring component that has not yet been explicitly migrated and validated against the new design. During mixed-state phases, both documents are active. Defer to this document for any element not yet marked migrated in `SCORING_ENGINE_ARCHITECTURE.md`.

This document defines the target architecture for scenario evaluation and debrief scoring. It supersedes the current implicit approach (single LLM pass as both adjudicator and feedback writer) and establishes the migration path toward a hardened, auditable scoring system consistent with §3.1 of `DEVELOPMENT_GUIDELINES.md`.

---

## 1. Problem Statement

The current debrief architecture asks a single LLM call to simultaneously:

1. Determine what happened (adjudication) — which interventions were applied, what vitals were recorded, whether documentation matches the run
2. Determine whether it was correct (scoring) — was the O2 method appropriate, did the DMIST cover all components
3. Explain why it mattered and coach the learner (feedback writing)

Conflating these three roles produces systematic failures that have been directly observed across multiple test runs:

| Failure mode | Root cause |
|---|---|
| Hallucinated vital values ("high 90s" when run showed 94%) | LLM substitutes clinical expectation for run data |
| Inverted PAT feedback ("automated result was SICK" when run shows NOT SICK) | LLM confuses "what was recorded" with "what was correct" |
| Credit for undone actions in What Was Done Well | LLM pulls from submitted docs instead of run evidence |
| DMIST/narrative scores too high despite unsupported claims | Corroboration rules present but not directive enough to override LLM softening |
| Inconsistent rule application across runs | Same prompt produces different scoring decisions on equivalent evidence |
| O2 method penalty applied to system-generated contradiction | LLM cannot distinguish partner ambiguity from student error without partner turn in transcript |

These failures erode student trust when they notice the feedback contradicts what they actually did. They also undermine the clinical determinism mandate in `DEVELOPMENT_GUIDELINES.md §3.1`.

---

## 2. Design Principles

These principles govern all decisions in this architecture. They derive from `DEVELOPMENT_GUIDELINES.md §3` and the observed failure modes above.

**Adjudication is deterministic.** What happened during a run is a fact question answerable from backend records: the intervention timeline, the vitals engine, the findings rows, the session messages. The LLM must not re-derive these facts from prose — it reads them from a structured input.

**Scoring authority follows source of truth.** If the source of truth is a backend record, scoring from that record is backend responsibility. If the source of truth is a semantic judgment (was the narrative adequate, was the tone appropriate), scoring is AI responsibility.

**AI explains adjudicated facts; it does not generate them.** The LLM's role is to convert pre-computed deductions and evidence into coaching language a student will learn from — not to decide what the deductions are.

**Evidence is three-layered: performed, documented, corroborated.** Every fact claim in the debrief must be classified by its layer:
- *Performed* — what happened in the run (intervention timeline, vitals, transcript). The source of truth for clinical performance scoring.
- *Documented* — what the student wrote in their DMIST and narrative. The source of truth for documentation scoring only.
- *Corroborated* — whether a documented claim is supported by run evidence. Unsupported documentation claims are penalized, not protected.

These three layers must never be blurred. The LLM cannot use documented claims as evidence for run performance, and cannot use run performance as a substitute for documentation completeness.

**Every deduction must have a traceable source.** Either a scenario rule, a run record comparison, or an explicit AI judgment. Deductions without traceable sources are audit failures.

**Scoring uses a three-layer architecture: universal base, scenario-specific, and scope.** The application contains a Universal Base Standard — the procedural assessment structure expected on every EMS call (scene size-up, primary survey, vitals, reassessment, documentation). This fires for every scenario without per-scenario authoring. Professionalism is not part of the Universal Base Standard — it is scored as a qualitative AI dimension with a hardened ceiling, not as a universal presence check. Scenario JSON adds clinical criteria specific to this presentation (PAT expectations, required interventions, grace items, educational content). Protocol/MCA files provide scope authority, resolved at runtime. Clinical criteria the application cannot know — whether PAT applies to this specific patient, which interventions are required for this presentation, what the grace items are — must live in the scenario file, not hardcoded in the application engine. Universal elements can be suppressed by explicit scenario declaration when they do not apply.

**Authored educational content is authoritative; AI contextualizes it.** Clinical education content — condition background, pathophysiology, key teaching points, common mistakes, treatment rationale — is authored in the scenario JSON and reviewed for clinical accuracy and protocol alignment. The AI does not regenerate this content from scratch. Its role is to present authored content and connect it to what this specific student did or missed in this run. Generated content cannot be reviewed by a medical director; authored content can.

**Scope resolution is a prerequisite, not an input.** The evidence packet builder receives the *adapted* scenario — the runtime-resolved output of `adapt_scenario_to_context()`. It must never read base scenario JSON directly. What counts as a required intervention, what is out of scope, and what the active protocol requires are all scope-resolved facts, not static scenario values.

**Migration is incremental.** The target architecture must be reachable in phases without breaking existing runs. Each phase must leave the system in a valid, deployable state.

---

## 3. Current Architecture

```
[session + scenario + submitted docs]
          |
          v
  _build_debrief_prompt()
  (assembles everything into one large prompt)
          |
          v
      LLM call
  (adjudicates + scores + writes feedback)
          |
          v
  debrief markdown + subscores JSON
```

Partially hardened pre-computed blocks already exist as advisory context:
- `scene_entry_block` — PPE cap and PAT result (pre-computed but not enforced as ceiling)
- `required_interventions_block` — required intervention status (pre-computed but AI can override)
- `_build_documentation_conflict_block()` — O2 type and documentation mismatches (detected but not deducted deterministically)

The problem is that all of these are advisory — the LLM reads them as context but retains the authority to score contrary to them. Evidence from test runs shows it does so regularly.

---

## 4. Target Architecture

```
[session + adapted_scenario + submitted docs]
          |
          v
  _build_evidence_packet(adapted_scenario, ...)   ← new deterministic layer
  (uses scope-resolved scenario — never base JSON)
  (adjudicates all factual claims;
   activates sections based on scenario_type;
   produces structured scoring packet)
          |
          v
  _build_debrief_prompt()           ← restructured
  (injects evidence packet as hard constraints;
   asks LLM only for explanation and judgment
   on dimensions it is authority over)
          |
          v
      LLM call
  (writes prose; explains deductions;
   scores qualitative dimensions only)
          |
          v
  debrief markdown + subscores JSON
  (subscores partially pre-filled from
   evidence packet before LLM sees them)
```

The evidence packet is a structured Python object built from backend records before the LLM call. It is the single source of truth for all factual claims in the debrief. The LLM cannot contradict it.

**Multi-tenant guarantee:** `_build_evidence_packet()` always receives the adapted scenario returned by `adapt_scenario_to_context(session)`. Required interventions, scope checks, and out-of-scope deductions are all derived from the scope-resolved protocol state, not from static scenario fields. The same scenario JSON run by an EMT-B and a Paramedic under different MCAs produces different evidence packets reflecting the different required interventions and scope limits for each.

---

## 4A. Scoring Specification Architecture

This section defines the three-layer scoring architecture that governs all evaluation decisions. It is the authoritative reference for where each type of scoring logic lives.

### Overview

```
Layer 1 — Application: Universal Base Standard
  Procedural structure expected on every EMS call.
  Consistent evaluation without per-scenario authoring.
  Can be suppressed by explicit scenario declaration.

Layer 2 — Scenario JSON: Scenario-Specific Criteria
  Clinical criteria for this specific presentation.
  Overrides and extends the universal base.
  Grace items, required interventions, PAT expectations,
  level-specific expectations, educational content.

Layer 3 — Protocol/MCA: Scope Authority
  What is in scope at each level for this MCA.
  Resolved at runtime by adapt_scenario_to_context().
  This IS the override mechanism — no separate system needed.
```

---

### Layer 1 — Universal Base Standard (Application)

The Universal Base Standard defines the procedural assessment structure expected on every EMS call, regardless of scenario type, agency, or protocol. These elements apply universally because they are foundational to EMS practice, not clinical criteria specific to a presentation.

**Universal elements evaluated for every scenario:**

| Element | What is evaluated | Detected by | Edge case / risk |
|---|---|---|---|
| Scene safety addressed | Any scene safety, hazard, or environmental awareness statement | Transcript keyword match (BSI, gloves on, scene safe, any safety language) | Low false-miss risk; almost all students mention this |
| PPE selected | At least minimum PPE (gloves) applied before patient contact | `scene_entry` record (explicit UI action) | Clean — driven by backend record, not transcript |
| Primary survey | Any opening patient assessment: LOC check, general impression, or ABC-type statement | Transcript keyword match + intervention timeline (any exam-type action in first 2 minutes) | **Highest risk element — see detection note below** |
| History attempted | At least one SAMPLE/OPQRST-type question directed at patient or family | Transcript keyword match (what happened, any history, allergies, medications, onset) | May fire on dispatch recap — detection must require a *question*, not a statement |
| Vitals obtained | At least one numeric vital recorded | Vitals engine record (any vitals entry) | Clean — driven by backend record |
| Reassessment | Any vitals or patient status check occurring after an intervention | `vital_check` SessionEvent (source=`backend_auto`/`instructor_note`) after an `intervention_applied` event (preferred); fallback to vitals record timestamp vs. intervention timeline | `frontend_explicit` vital_check events are stored but not treated as authoritative — only backend-emitted or instructor-confirmed events qualify. Fallback path fires when no authoritative SessionEvents are present. |
| Disposition addressed | Transport intent, ALS intercept call, or handoff reference stated | Transcript keyword match (transport, going to, ALS, calling for, hospital) + intervention timeline (ALS intercept applied) | Varies by scenario type — see disposition note below |
| Documentation submitted | Required handoff document (DMIST or pre-arrival report) submitted via UI | Session submission record (backend flag) | Clean — backend event, not inferred |
| ~~Professionalism baseline~~ | *Not a universal element* — greeting is computed as a hardened fact (§5.7) and constrains qualitative AI scoring, but is not a universal presence-check deduction | — | Removed from universal base; see professionalism note below |

The application computes these for every run. No scenario authoring is required for them to fire. Each universal element is a **presence check only** — it answers *was this done at all*, not *was it done correctly for this specific presentation*. Clinical correctness and specific requirements are Layer 2 scenario criteria.

**Detection notes for highest-risk elements:**

*Primary survey presence* — the most difficult to detect reliably. The definition for the universal presence check is intentionally broad: any opening patient assessment action (exam tag, vitals action, or clear assessment statement in the first 2–3 minutes). The universal check does not evaluate primary survey completeness or sequence — that is Layer 2 via `scoring.required_assessments` and the NREMT phase structure. False misses are more acceptable here than false positives, because the Layer 2 clinical performance scoring evaluates what was done in detail. The universal check guards against a student who performed no assessment at all.

*Disposition addressed* — detection definition must match scenario context. For ALS-turnover scenarios: ALS intercept called (intervention timeline) OR explicit ALS/handoff reference in transcript. For hospital scenarios: transport stated OR pre-arrival communication sent. For non-transport agency scenarios: ALS turnover reference. The scenario's `turnover_target` field drives which detection rule applies. This is one of the few universal elements that requires scenario-context to detect correctly — not a general keyword match.

*Professionalism baseline* — **moved out of the Universal Base Standard**. Greeting detection is scenario-context-sensitive (some scenarios the student arrives mid-scene, some have informal call openings) and the deduction for absence is better handled as a qualitative AI judgment within the professionalism dimension than as a universal binary. The evidence packet still computes `greeting_detected` as a hardened fact (see §5.7) and constrains the LLM, but it is not a universal presence-check deduction. It is a hardened input to qualitative AI scoring.

**What the Universal Base Standard does NOT contain:**
- Whether the scene is safe or unsafe, and what hazards are present (scenario-authored)
- Which PPE items are specifically required beyond the minimum (scenario-authored)
- Which vitals are clinically critical for this presentation (scenario-authored)
- Which specific exams or assessments are expected (scenario-authored)
- Which specific interventions are required (scenario-authored)
- Whether PAT is applicable or what impression is correct (scenario-authored)
- Grace items for any specific scenario (scenario-authored)

**Opt-out mechanism:**

Any universal element can be suppressed by the scenario file with an explicit declaration:

```json
"scoring": {
  "suppress_universal": ["scene_size_up", "history_assessment"]
}
```

Suppression should be rare and requires documented clinical rationale. A scenario that suppresses a universal element does not evaluate students on that element — no credit, no deduction, no mention in debrief. Example valid use: a scenario where the student arrives to a pre-packaged patient with full handoff documentation already present may suppress scene size-up evaluation.

---

### Layer 2 — Scenario-Specific Criteria (Scenario JSON)

The scenario file contains all clinical criteria specific to this presentation. It extends the Universal Base Standard — it does not replace it.

**Fields already present in scenario JSON:**

| Field | Purpose |
|---|---|
| `scene_entry_scoring.ppe` | Which PPE items are required/recommended and deduction amounts |
| `scene_entry_scoring.pat` | Whether PAT is applicable, expected impression, deduction |
| `scoring.overall_considerations` | Scenario-specific guidance, grace items, non-penalizable behaviors |
| `scoring.dmist_considerations` | DMIST-specific criteria and grace items |
| `scoring.narrative_considerations` | Narrative/CHART criteria and grace items |
| `scoring.by_level` | Level-specific required behaviors, additional expectations, grace items |
| `scoring_rubric` | Per-dimension max points and full/partial/minimal credit descriptors |
| `correct_treatment.required_interventions` | Interventions required for this scenario |
| `correct_treatment.out_of_scope_bls` | Scenario-specific out-of-scope items (supplements protocol scope rules) |
| `debrief_info.condition_background` | Authored pathophysiology and BLS challenge summary |
| `debrief_info.key_teaching_points` | Ordered authored teaching points |
| `debrief_info.common_mistakes` | Authored common errors specific to this condition |

**New fields to be added (Phase 2):**

| Field | Purpose |
|---|---|
| `scene_entry_scoring.scene_safety` | Scene safe/unsafe status, hazards present, correct response, deduction |
| `scene_entry_scoring.pat.expected_impression` | `"SICK"` or `"NOT_SICK"` — required when `pat.enabled == true` |
| `scene_entry_scoring.pat.incorrect_impression_deduction` | Point deduction for wrong impression |
| `scoring.critical_vitals` | Which vitals are clinically critical for this presentation |
| `scoring.required_assessments` | Physical exam and clinical assessments expected for this presentation |
| `scoring.required_screens` | Condition-specific differential screens (distinct from routine assessments) |
| `scoring.dmist_components` | Per-component definitions for DMIST corroboration |
| `scoring.corroboration_rules` | Deduction ranges for unsupported documentation claims |
| `scoring.suppress_universal` | Opt-out list for universal elements not applicable to this scenario |

These fields are described in detail in §4B below.

**The key rule:** Criteria that cannot be generalized across scenarios — whether the scene is unsafe, which vitals matter, which exams are expected, which behaviors are grace items — must live here. The application reads and applies these fields; it never infers clinical criteria from scenario category or type.

**Sensible defaults — authoring is additive, not mandatory.** New scenario JSON fields introduced in Phase 2 have engine-level defaults so that an unaugmented scenario degrades gracefully to baseline evaluation rather than failing. Scenario authors only need to add a field when their scenario deviates from the standard EMS baseline.

| Field | Engine default when absent |
|---|---|
| `scene_entry_scoring.scene_safety` | `scene_is_safe: true`, no hazards, no deduction |
| `scene_entry_scoring.pat` | `enabled: false` — PAT not evaluated |
| `scoring.critical_vitals` | `required: ["hr", "rr", "spo2"]`, no others — standard EMS baseline |
| `scoring.required_assessments` | Empty — no specific assessments required beyond universal base |
| `scoring.required_screens` | Empty — no condition-specific screens required |
| `scoring.dmist_components` | Standard generic DMIST rubric (D: demographics, M: chief complaint, I: interventions, S: signs/vitals, T: treatment/disposition) |
| `scoring.corroboration_rules` | Conservative defaults (structural omission: 2pts; factual contradiction: 2pts; max per document: 6pts) |
| `scoring.suppress_universal` | Empty — all universal elements active |

This means a scenario without any Phase 2 fields is still fully evaluatable using universal base standard evaluation plus the existing `scoring_rubric`, `scoring.by_level`, and `scene_entry_scoring.ppe`. Phase 2 fields are enrichment, not requirements.

---

### Layer 3 — Protocol/MCA: Scope Authority

Protocol files in `app/protocols/` define what is clinically in scope at each licensure level for this MCA. These are resolved at runtime into the adapted scenario's `protocol_config` by `adapt_scenario_to_context()`.

**This is the override mechanism.** There is no separate override system. The protocol hierarchy (National → State → MCA → Agency) resolves scope, and the adapted scenario already carries the resolved result before the evidence packet builder runs. MCA-specific scoring variations are authoring concerns for `scoring.by_level` and `scoring.overall_considerations`, not a separate runtime override layer.

Protocol scope determines:
- Which interventions are in scope at each level
- What drugs are authorized, with dosages
- The `out_of_scope_bls` list for scope adherence scoring
- Clinical protocol steps injected into the AI prompt

The evidence packet builder always receives the adapted scenario, never the base scenario JSON. All scope checks, required-intervention lists, and out-of-scope deductions use scope-resolved state. See §2 (scope resolution principle).

#### Planned Configuration: NASEMSO + Generic EMS Agency (Initial Education Students)

Students who are not affiliated with a real agency (e.g., early EMS students without an employer) need a coherent first-class configuration. The planned setup for this population:

| Layer | Planned Config | Status |
|---|---|---|
| Layer 1 — Universal Base | NREMT assessment structure (scene size-up, primary survey, history, treatment, reassessment) | Defined in application |
| Layer 2 — Scenario Criteria | Scenario JSON as authored (PAT, required vitals, screens, etc.) | Existing |
| Layer 3 — Protocol/Scope | NASEMSO national clinical guidelines + NREMT scope floors by level | **Not yet defined — content gap** |

Under this three-layer resolution, a student in this configuration is naturally evaluated to NREMT standards:
- The Universal Base enforces the NREMT assessment sequence and documentation disciplines
- NASEMSO provides nationally-recognized clinical protocols (what to do for each condition, drug formulary, dosages)
- NREMT scope floors by licensure level determine which interventions are in-scope and which trigger scope-adherence deductions

This is **not an architectural gap** — the three-layer architecture supports this configuration as-is. It is a **content/configuration task**: define a `nasemso_national` protocol set in `app/protocols/` and a `generic_ems_agency` agency config referencing it. Until those artifacts exist, the Generic EMS Agency configuration is unavailable.

---

### Interaction Between All Three Layers

```
Protocol file (scope + clinical protocol steps)
        ↓ resolved by adapt_scenario_to_context()
Adapted scenario (universal opt-outs + scenario criteria + resolved protocol)
        ↓ read by _build_evidence_packet()
Evidence packet:
  - Universal Base results (fired unless suppressed)
  - Scenario-specific results (PAT, required interventions, screens, grace items)
  - Scope-resolved results (out-of-scope deductions, scope adherence)
        ↓ injected into debrief prompt with authored educational content
LLM (explains deductions; contextualizes authored content to run gaps; scores AI-retained dimensions)
```

The evidence packet builder reads Layer 1 (universal elements), Layer 2 (scenario criteria), and Layer 3 (scope-resolved protocol) and computes a single unified evidence packet. The LLM sees the result of all three layers as pre-computed facts — it never adjudicates from raw scenario JSON or protocol files directly.

---

## 4B. Scenario Config Reference — Scene Entry and Assessment Criteria

This section defines the scenario JSON config structure for the four scenario-specific scoring areas that extend the Universal Base Standard. Each field pair follows the same pattern: the Universal Base answers *was this done*, the scenario config answers *was the right thing done for this presentation*.

---

### Scene Safety

The universal base checks whether the student addressed scene safety at all. The scenario config defines what makes this scene safe or unsafe and what the correct response is.

```json
"scene_entry_scoring": {
  "scene_safety": {
    "scene_is_safe": true,
    "hazards": [],
    "correct_response": null,
    "proceeding_unsafe_deduction": 0
  }
}
```

For scenarios with an unsafe scene:

```json
"scene_entry_scoring": {
  "scene_safety": {
    "scene_is_safe": false,
    "hazards": ["potential domestic violence", "unsecured bystander"],
    "correct_response": "Request law enforcement before full patient approach; maintain awareness of bystander positions",
    "proceeding_unsafe_deduction": 5,
    "note": "Scene safety failure in a potential violence scenario is a patient and provider safety issue — deduct from professionalism/scene management, not clinical performance"
  }
}
```

When `scene_is_safe: true`, the universal check fires but no scenario-specific deduction applies. When `scene_is_safe: false`, the scenario declares the hazards, the expected response, and the deduction for proceeding without addressing them.

Most scenarios will have `scene_is_safe: true` with empty hazards — the universal presence check is sufficient and the scenario config is minimal.

---

### Required PPE

Already exists as `scene_entry_scoring.ppe`. Shown here for completeness in the context of the universal base interaction.

The universal base defaults to "gloves required" if no PPE config is present. The scenario config specifies the actual requirements:

```json
"scene_entry_scoring": {
  "ppe": {
    "required": ["gloves"],
    "recommended": ["eye_protection"],
    "missing_required_penalty": 3,
    "missing_recommended_penalty": 1,
    "max_score": 10
  }
}
```

For a scenario with infection risk or airway involvement, `required` would include `["gloves", "eye_protection"]` or `["gloves", "n95_mask"]`. The scenario author determines what's clinically appropriate for the exposure risk.

---

### Critical Vitals

The universal base checks that *some* vitals were obtained. The scenario config declares which vitals are clinically critical for this specific presentation — meaning their absence is a meaningful clinical gap, not just an incomplete workup.

```json
"scoring": {
  "critical_vitals": {
    "required": ["spo2", "rr", "work_of_breathing"],
    "important": ["hr", "skin_color", "cap_refill"],
    "optional": ["temp", "gcs", "bgl"],
    "missing_required_deduction": 2,
    "missing_important_deduction": 1,
    "note": "SpO2 and work of breathing are the primary monitoring parameters for croup — their absence is a direct clinical performance gap"
  }
}
```

| Tier | Meaning | Deduction |
|---|---|---|
| `required` | Clinically essential for this presentation; absence is a scored gap | `missing_required_deduction` per missed vital |
| `important` | Clinically relevant; absence is noted but weighted less | `missing_important_deduction` per missed vital |
| `optional` | Available and appropriate if obtained; absence is not penalized | None |

For an ACS scenario, `required` would include `["hr", "bp", "spo2", "12_lead_ecg"]`. For a diabetic emergency, `required` would include `["bgl", "hr", "spo2", "gcs"]`. The scenario author determines what's clinically critical based on the presentation.

---

### Required Assessments and Screens

Two distinct field types serve different purposes:

**`required_assessments`** — physical exam and clinical assessments expected as standard workup for this type of presentation. These are actions a competent provider should perform regardless of what they find.

**Detection order:** (1) `explicit_assessment` SessionEvent with `source=backend_auto` or `instructor_note` whose `event_key` matches the assessment `id` or a keyword — authoritative. (2) Transcript keyword match. (3) `SessionFinding` record keyword match. (4) Submitted DMIST or narrative text keyword match. `frontend_explicit` events are stored for analytics but are not credited as authoritative evidence; they fall through to text-based matching only.

```json
"scoring": {
  "required_assessments": [
    {
      "id": "lung_sound_auscultation",
      "description": "Auscultate lung sounds",
      "detection": "lung_sound_challenge_completed OR transcript_keyword",
      "keywords": ["lung sounds", "breath sounds", "auscultate", "listen"],
      "missing_deduction": 2,
      "note": "Distinguishing stridor from wheeze requires auscultation — this is the central clinical decision point"
    },
    {
      "id": "wob_assessment",
      "description": "Assess work of breathing (retractions, nasal flaring, positioning)",
      "detection": "transcript_keyword OR findings_logged",
      "keywords": ["retractions", "work of breathing", "WOB", "nasal flaring"],
      "missing_deduction": 1
    }
  ]
}
```

**`required_screens`** — condition-specific differential diagnosis screenings. These are active clinical reasoning steps — ruling in or out a dangerous alternative diagnosis.

```json
"scoring": {
  "required_screens": [
    {
      "id": "epiglottitis_differential",
      "description": "Epiglottitis differential screening",
      "keywords": ["epiglottitis", "drooling", "tripod", "high fever", "toxic appearance"],
      "detection": "transcript_keyword OR findings_logged",
      "missing_deduction": 2,
      "note": "Epiglottitis is a life-threatening mimic of croup — failure to screen is a clinical reasoning gap, not just an exam omission"
    }
  ]
}
```

**The distinction matters for debrief feedback.** A missed required assessment gets feedback like "you should have auscultated lung sounds on a pediatric respiratory call." A missed required screen gets feedback like "you did not rule out epiglottitis — here is why that matters clinically." The evidence packet flags each separately so the LLM can generate appropriately targeted coaching.

**Detection methods** (how the evidence packet determines presence):
- `transcript_keyword` — keyword match in student chat messages
- `findings_logged` — finding appears in the session's `SessionFinding` records
- `submitted_docs` — keyword match in submitted DMIST or narrative text (students who document clinical reasoning in submitted docs without explicitly stating it in chat still receive credit)
- `intervention_applied` — a specific intervention was applied (e.g., lung sound challenge completed)
- `any` — any of the above

Detection searches in priority order: authoritative event key → transcript → findings → submitted DMIST/narrative. The first positive match wins.

---

### Summary: Universal Base vs. Scenario Config by Scoring Element

| Element | Universal Base checks | Scenario config adds |
|---|---|---|
| Scene safety | *Was safety addressed?* | Specific hazards, unsafe scene flag, correct response, deduction |
| PPE | *Were minimum gloves applied?* | Which items are required/recommended, deduction amounts |
| Vitals | *Were any vitals obtained?* | Which vitals are required/important/optional for this presentation |
| Physical exam | *Was a primary survey done?* | Which specific assessments are required for this presentation |
| Differential screens | *(none — not universal)* | Which condition-specific screens are expected and why |
| PAT | *(none — not universal)* | Whether applicable, expected impression, deduction |
| Required interventions | *(none — not universal)* | Which treatments are required for this presentation |

---

## 5. Evidence Packet

The evidence packet is built by `_build_evidence_packet()` in `ai_client.py`. It contains the following sections. Fields marked `[hardened]` are used to derive hard scoring constraints the LLM cannot override. Fields marked `[context]` inform LLM judgment but do not determine scores.

Active sections are driven by what the scenario scoring specification declares — not by application inference from scenario category.

### 5.0 Scenario Context

The scenario context block is always present. It is read directly from the adapted scenario — not derived by application inference. `pat_applicable` is read from `scene_entry_scoring.pat.enabled` in the scenario file. `dmist_applicable` is read from `turnover_target`. Section activation follows what the scenario declares, not what the application infers from category.

```python
scenario_context: {
    "scenario_id": "peds_croup_01",
    "scenario_type": "pediatric_medical",       # from scenario.category

    # Provider and scope context — all scope-resolved at runtime from adapted scenario
    "provider_level": "emt_basic",              # [hardened] — from session / adapted scenario
    "mca": "MI_Region_4",                       # [hardened] — scope-resolved at runtime
    "mca_expansions": ["cpap_bls"],             # [hardened] — active BLS scope expansions for this MCA/agency
    "mca_specialist_expansions": [],            # [hardened] — active specialist scope expansions

    # Agency operational context — from adapted scenario (derived from agency config)
    "non_transport_agency": False,              # [hardened] — True for fire/first-responder units that do not transport
    "als_auto_dispatched": True,                # [hardened] — True when agency.als_dispatch is active for this call type
    "als_arrival_minutes": 6,                   # [hardened] — from agency.als_dispatch.arrival_minutes
    "unit_carries_als_equipment": False,        # [hardened] — whether this unit carries ALS-level equipment

    # Handoff and evaluation activation
    "turnover_target": "als",                   # [hardened] — from scenario.turnover_target
    "pat_applicable": True,                     # [hardened] — from scene_entry_scoring.pat.enabled
    "dmist_applicable": True,                   # [hardened] — True when turnover_target == "als"
    "pre_arrival_report_applicable": False,     # [hardened] — True when turnover_target == "hospital"
    "transport_decision_applicable": True,      # [hardened] — True for transport agencies; modified for non-transport (see note)

    # Scoring spec for active provider level
    "scoring_by_level": { ... },                # from scoring.by_level for active provider_level
    "grace_items": [ ... ]                      # merged from scoring.overall_considerations and by_level[active_level]
}
```

**How agency operational context affects evaluation:**

`non_transport_agency` changes what "disposition addressed" means. For transport agencies: loaded the patient, confirmed transport destination, called receiving facility. For non-transport agencies: requested transport (ALS intercept, ambulance, or hospital notification), handed off patient, communicated with receiving crew. The evidence packet's §5.6 Transport and Disposition evaluates the appropriate actions for the agency type — not a universal transport expectation.

`als_auto_dispatched` suppresses "ALS requested" as a required evaluation point. If ALS is co-dispatched with the call, the student cannot be scored for whether they requested ALS — it was already dispatched before they arrived. The evidence packet derives this from `als_arrival_minutes` being set on the agency config. Scenario authors do not need to write a grace item for this; it fires automatically from the agency context. What the student *is* still evaluated on: whether they prepared an appropriate ALS handoff (DMIST), updated ALS en route, and communicated relevant clinical findings.

`mca_expansions` and `mca_specialist_expansions` determine which interventions are in scope above the base provider level. An EMT-B with CPAP expansion can be scored on CPAP application; an EMT-B without it cannot. Required intervention evaluation uses the scope-resolved list, which already reflects these expansions via `adapt_scenario_to_context()`. The `mca_expansions` field in `scenario_context` makes this explicit so the evidence packet builder does not need to re-derive it.

**Section activation rules:**

| Section | Activated when |
|---|---|
| PAT (§5.1) | `scene_entry_scoring.pat.enabled == true` in scenario file |
| DMIST corroboration (§5.4) | `turnover_target == "als"` |
| Pre-arrival report corroboration (§5.4) | `turnover_target == "hospital"` |
| MOI fields (§5.5.2) | `scenario_type` contains `trauma` OR scenario declares `moi_required: true` |
| Hemorrhage control (§5.5.1) | Scenario declares `hemorrhage_control` in required interventions |
| C-spine consideration (§5.5.1) | Scenario declares `cspine` in assessment screens |
| Full ABCDE emphasis | `scenario_type` contains `trauma` (default); medical defaults to immediate life threats |

**The activation table above describes defaults only.** Scenarios can override by explicitly declaring fields. The application engine reads explicit declarations first; the default by category is a fallback when no declaration exists.

`scenario_type` (from `category`) is used for default lookup only. Explicit scenario fields always take precedence.

---

### 5.1 Scene Entry

```python
scene_entry: {
    "ppe_selected": ["gloves"],                      # [hardened]
    "ppe_required": ["gloves"],                      # [hardened] — scope-resolved
    "ppe_recommended": ["eye_protection"],           # [hardened] — scope-resolved
    "ppe_deduction": 1,                              # [hardened]
    "professionalism_cap": 9,                        # [hardened]

    # PAT — present only when scenario_context.pat_applicable == True
    "pat_recorded": "NOT_SICK",                      # [hardened]
    "pat_expected": "SICK",                          # [hardened] from scenario
    "pat_correct": False,                            # [hardened]
    "pat_deduction": 2,                              # [hardened] from scenario
    "pat_note": "Patient has SpO2 93%, retractions, audible stridor — SICK impression required"
}
```

`pat_expected` and `pat_deduction` are new fields added to `scene_entry_scoring.pat`. See §8.1. They are required only when `scene_entry_scoring.pat.enabled == true`. The scenario author determines whether PAT is applicable — not the application, and not the category tag. An adolescent scenario may have PAT disabled even though `category == "pediatric_*"`. An unusual presentation may have a NOT_SICK expected impression where most pediatric calls would be SICK. The grace rule "PAT acronym not required, credit if components assessed" lives in `scoring.by_level.EMT.grace_items` and is surfaced in the evidence packet's `grace_items` field — the LLM applies it, but as a declared fact, not an inference.

---

### 5.2 Intervention Record

```python
interventions: {
    "applied": [
        {"id": "o2_nrb", "label": "High-flow O2 via secured NRB mask (15 LPM)", "elapsed_min": 0.7}
    ],
    "required": [
        {"id": "o2_blowby", "label": "Supplemental O2 — blow-by", "applied": False},  # [hardened]
        {"id": "neuro_assessment", "label": "Neurological Assessment", "applied": False}
    ],
    "missing_required_labels": ["Supplemental O2 — blow-by", "Neurological Assessment"],
    "applied_ids": {"o2_nrb"},
    "partner_ambiguity_flags": [
        "o2: partner narrated 'blow-by', system registered secured NRB mask — popup discrepancy"
    ]                                                # [context] — noted but not student-penalized
}
```

`interventions.required` is derived from the scope-resolved protocol for the active session — not from a static scenario list. An EMT-B session may require different interventions than a Paramedic session for the same scenario. See §2 (scope resolution principle).

---

### 5.3 Vital Record

```python
vitals: {
    "recorded": {
        "spo2": [{"value": 93, "elapsed_min": 0.5}, {"value": 94, "elapsed_min": 0.9}],
        "hr": [{"value": 162, "elapsed_min": 0.5}]
    },
    "peak_spo2": 94,           # [hardened] — LLM cannot claim higher
    "trough_spo2": 93,         # [hardened]
    "final_spo2": 94,          # [hardened]
    "reassessment_occurred": True,
    "reassessment_after_intervention": True
}
```

The LLM is constrained: any vital value it cites in the debrief must appear in `vitals.recorded`. It cannot infer improvement trends beyond what the record shows.

---

### 5.4 Corroboration Index

The corroboration index maps each claim in the submitted DMIST or pre-arrival report and narrative against supporting evidence in the run. It enforces the three-layer evidence principle from §2: performed vs. documented vs. corroborated.

```python
corroboration: {
    "dmist_claims": [                             # populated when dmist_applicable == True
        {
            "component": "I",
            "claim": "Blow-by O2 at 15 LPM with infant in mother's arms",
            "layer": "documented",                # [hardened] — source is submitted doc
            "supported": False,                   # [hardened] — no matching run evidence
            "evidence": "intervention timeline shows secured NRB mask; o2_blowby not registered",
            "conflict_type": "method_mismatch",
            "deduction_eligible": True
        },
        {
            "component": "I",
            "claim": "Calm, low-stimulation environment maintained",
            "layer": "documented",
            "supported": False,
            "evidence": "calm_environment not in intervention timeline; not in transcript",
            "conflict_type": "unsupported_claim",
            "deduction_eligible": True
        }
    ],
    "pre_arrival_claims": [],                     # populated when pre_arrival_report_applicable == True
    "narrative_claims": [
        {
            "chart_element": "Rx/Treatment",
            "claim": "Calm, low-stimulation environment maintained",
            "layer": "documented",
            "supported": False,
            "evidence": "calm_environment not registered; not in transcript",
            "deduction_eligible": True
        }
    ],
    "unsupported_dmist_count": 3,                 # [hardened] — drives DMIST ceiling
    "unsupported_narrative_count": 2              # [hardened] — drives narrative ceiling
}
```

**Corroboration sources by claim type:**
- `"intervention_timeline"` — claimed intervention must appear in the DB timeline
- `"vitals_and_findings"` — claimed value must appear in the vitals record or findings rows
- `"scenario_patient_fields"` — claimed demographics must match the scenario's patient block
- `"any"` — claim accepted as present if it appears in the submitted document; no run corroboration required

**Hard deductions apply only to:**
- Structural omissions (entire DMIST component or CHART section absent)
- Clear factual contradictions (documented blow-by when a secured NRB mask is registered)

**Flagging without automatic deduction applies to:**
- Clinical paraphrasing variations (LLM evaluates whether paraphrase is clinically adequate)
- Terminology differences that may be valid equivalents

**Implementation approach — two-tier corroboration:**

The corroboration index uses two distinct mechanisms depending on the type of check required. Free-text narrative and DMIST cannot be reliably parsed with Python regex alone — medical language is too variable.

*Tier 1 — Structural and factual checks (deterministic Python):*
- DMIST component presence: does each of D, M, I, S, T have any content? (string empty check)
- Factual contradiction: does the documented intervention ID directly conflict with a registered intervention ID? (e.g., documented `o2_blowby`, registered secured-mask `o2_nrb`) — this comparison is ID-level, not text-level. Blow-by using NRB mask hardware held near the face is not the same as a secured NRB mask.
- Vital value contradiction: does the documented SpO2 value differ from the vitals record? (numeric comparison)

*Tier 2 — Semantic adequacy (LLM extraction pass):*
For claims that require semantic judgment (paraphrasing, adequacy, completeness), `_build_evidence_packet()` calls a small, fast, low-temperature LLM extraction pass *before* the main debrief call. This extraction prompt is narrow and structured:
- Input: the submitted DMIST or narrative text + the intervention timeline IDs + vitals record
- Output: a JSON array of extracted clinical claims, each tagged with a `supported: true/false` based on the timeline and vitals record
- The extraction LLM does not write prose, score, or coach — it classifies only

The extraction output is what populates `corroboration.dmist_claims` and `corroboration.narrative_claims`. The main debrief LLM then reads the pre-classified claims as hardened facts and explains them in coaching language.

This approach maintains the architectural boundary: deterministic Python for ID-level facts, LLM extraction for semantic classification, debrief LLM for explanation only. The debrief LLM never adjudicates corroboration — it reads it.

---

### 5.5 Assessment Phases

Assessment is structured around NREMT assessment phases, not a flat list. Active phases and their emphasis vary by `scenario_type`. This structure is the scoring backbone for the `clinical_performance` subscore.

**Important:** NREMT phases define *what to assess and when*. MCA protocol defines *what correct care is* within each phase. The LLM feedback should use practical clinical language — not exam-station language — when explaining gaps to students.

#### 5.5.1 Primary Survey

```python
primary_survey: {
    # All scenario types
    "general_impression_obtained": True,     # [hardened] — any opening assessment statement
    "loc_assessed": True,                    # [hardened] — AVPU or equivalent in transcript
    "airway_addressed": True,                # [hardened] — airway-related action or statement
    "breathing_assessed": True,              # [hardened]
    "circulation_assessed": True,            # [hardened] — HR, skin, bleeding check

    # Trauma types additionally
    "hemorrhage_control_performed": False,   # [hardened] — trauma only; from intervention timeline
    "cspine_considered": None,               # [hardened] — trauma only; True/False/None (n/a)
    "disability_assessed": False,            # [hardened] — GCS, LOC, pupils
    "exposure_performed": False,             # [hardened] — systematic body survey documented

    # Emphasis flag — drives LLM coaching weight
    "emphasis": "immediate_life_threats"     # "immediate_life_threats" | "full_abcde"
                                             # medical → immediate_life_threats
                                             # trauma → full_abcde
}
```

The `emphasis` field tells the LLM how to weight primary survey gaps in feedback. A missed hemorrhage control step on a trauma call is a higher-severity gap than the same omission on a medical call.

#### 5.5.2 History and Secondary Assessment

```python
history_secondary: {
    # Medical types
    "history_attempted": True,               # [hardened] — any SAMPLE/OPQRST-type question
    "sample_obtained": True,                 # [context] — S/A/M/P/L/E in transcript or findings
    "opqrst_obtained": False,                # [context] — for complaint-specific history

    # Trauma types
    "rapid_trauma_performed": False,         # [hardened] — trauma only; systematic assessment
    "moi_documented": True,                  # [hardened] — trauma only; from transcript/findings

    # All types
    "vitals_obtained": True,                 # [hardened]
    "findings_logged": ["Stridor", "WOB", "Skin", "Cap Refill"],

    # Scenario-specific screen — populated from scenario's required_screens list
    "required_screens": [
        {
            "id": "epiglottitis_differential",
            "description": "Epiglottitis differential screening",
            "in_transcript": False,           # [hardened] — run evidence
            "in_dmist": True,                 # [context] — documentation only
            "in_narrative": True              # [context] — documentation only
        }
    ]
}
```

The `in_transcript` vs. `in_dmist`/`in_narrative` distinction enforces the three-layer principle: clinical performance credit requires transcript or intervention evidence. Documentation credit is separate and subject to corroboration.

#### 5.5.3 Reassessment

```python
reassessment: {
    "occurred": True,                                # [hardened]
    "after_intervention": True,                      # [hardened]
    "vitals_repeated": True,                         # [hardened]
    "response_documented": False                     # [context] — in narrative or DMIST
}
```

---

### 5.6 Transport and Disposition

Transport decision is active for all scenario types, with higher scoring weight for trauma. What "transport decision" means depends on the agency type — this is derived from `scenario_context.non_transport_agency`.

```python
transport: {
    "transport_decision_applicable": True,        # from scenario_context
    "non_transport_agency": False,                # [hardened] — from scenario_context; changes evaluation shape

    # Transport agency fields (non_transport_agency == False)
    "transport_decision_made": True,              # [hardened] — loaded patient or stated transport intent
    "destination_documented": False,              # [context]
    "transport_mode": "emergent",                 # [context] — from transcript if stated

    # Non-transport / intercept fields (always evaluated; primary for non_transport_agency == True)
    "als_intercept_considered": True,             # [hardened] — from transcript or intervention
    "als_intercept_called": True,                 # [hardened] — from intervention timeline
    "als_auto_dispatched": True,                  # [hardened] — from scenario_context; suppresses "requested ALS" as required action
    "als_handoff_prepared": True,                 # [hardened] — DMIST submitted or verbal handoff stated
    "pre_arrival_notification_sent": False,       # [hardened] — from intervention timeline

    # Documentation layer (both agency types)
    "disposition_in_dmist": True,                 # [context] — documented only
    "disposition_in_narrative": True,             # [context] — documented only

    # Scoring weight — drives LLM coaching emphasis
    "weight": "high"   # "high" for trauma; "moderate" for medical
}
```

**Transport vs. non-transport evaluation:**

For **transport agencies**: the primary disposition question is whether the student made a transport decision (loaded, stated destination, chose transport mode). ALS intercept and pre-arrival notification are secondary — relevant but not the primary disposition metric.

For **non-transport agencies**: "loading the patient" is not an available action. The primary disposition question is whether the student called for appropriate resources (ALS intercept, ambulance), prepared a handoff (DMIST or verbal), and communicated clinical findings to the receiving crew. The LLM coaching language changes accordingly — "you should have loaded the patient" is never appropriate feedback for a non-transport agency run.

**ALS auto-dispatch suppression:** When `als_auto_dispatched == True`, the evidence packet marks "requesting ALS" as non-scoreable. A student who did not explicitly request ALS is not penalized — ALS was already dispatched. The student is still evaluated on whether they prepared an ALS handoff and communicated with the incoming unit. This fires from the agency config automatically; scenario authors do not need to author a grace item for this.

---

### 5.7 Greeting and Professionalism

```python
professionalism: {
    "greeting_detected": True,         # [hardened] — regex on first student message
    "greeting_text": "hi, whats going on",
    "name_given": False,
    "agency_given": False,
    "message_count": 4
}
```

The LLM is not allowed to claim "no self-introduction" when `greeting_detected` is True. It can note the greeting was informal and name/agency were absent — but not misstate the fact.

---

### 5.8 In-Scenario Challenge Results

Challenge results from the shared challenge modal (Phase 3+) are written as `challenge_completed` SessionEvents (`source: backend_auto`) during the session and projected into the evidence packet at debrief time.

```python
challenge_results: [
    {
        "challenge_type":   "impression",          # | "ecg" | "med_math" | "capnography"
        "challenge_id":     "default",             # block key within the challenge dict
        "student_answer":   "Reactive airway disease / asthma exacerbation",
        "correct_answer":   "Reactive airway disease / asthma exacerbation",
        "acceptable":       ["Anaphylaxis with bronchospasm"],
        "result":           "correct",             # "correct" | "acceptable" | "incorrect" | "skipped"
        "occurred_at":      "<ISO timestamp>"
    },
    ...
]
```

### 5.8a Impression Challenge (dedicated field)

The impression challenge also appears in a dedicated top-level field for use by the debrief three-way comparison and the `_compute_reasoning_flags` routing logic:

```python
impression_challenge: {
    "student_answer":   "<student's selected option or None>",
    "correct":          "<scenario's authoritative correct answer string>",
    "acceptable":       ["<list of acceptable-credit answers>"],
    "result":           "correct" | "acceptable" | "incorrect" | "skipped" | None,
    "timestamp_relative_to_first_intervention": <float seconds or None>
}
```

`impression_challenge` is `None` when no impression challenge was run for the session (scenario does not have `impression_challenge.enabled: true`, or no milestone fired before treatment submission).

**`acceptable`** — the list of answers that earn partial credit (result: "acceptable"). Stored in the `challenge_completed` SessionEvent at submission time alongside `correct_answer` so the evidence packet can reproduce the full scoring context without re-reading scenario JSON.

**Routing use:** `_compute_reasoning_flags()` reads `evidence_packet.impression_challenge.result`. A result of `"incorrect"` activates the Priority 2 routing rule: replay the current scenario in the Next Action recommendation.

---

## 6. Scoring Authority Split

This table defines which scoring dimensions are hardened (backend-computed) vs. AI-retained (LLM judgment). It is the authoritative reference for what the LLM is and is not allowed to determine.

### 6.1 Hardened Dimensions

| Dimension | Authority | Basis |
|---|---|---|
| PPE deduction | **Hardened** | Scope-resolved PPE rules vs. scene_entry record |
| Professionalism cap | **Hardened** | PPE deduction applied as ceiling before LLM scores |
| PAT correctness | **Hardened** | `pat_expected` from scenario vs. `pat_recorded` from session |
| PAT deduction | **Hardened** | `pat_deduction` from scenario |
| Required intervention presence | **Hardened** | Intervention timeline vs. scope-resolved required list |
| Vital value claims | **Hardened** | LLM may only cite values from `vitals.recorded` |
| Documentation conflict flags | **Hardened** | Corroboration index |
| Partner ambiguity flags | **Hardened** | Noted in debrief; student not penalized |
| What Was Done Well | **Hardened anchor** | Only items in intervention timeline or transcript |
| Timeline classification | **Hardened** | Applied vs. missed vs. performed incorrectly |
| Primary survey phase completion | **Hardened** | Phase fields in §5.5.1 from transcript/timeline |
| Hemorrhage control performed | **Hardened** | Trauma only; from intervention timeline |
| C-spine considered | **Hardened** | Trauma only; from transcript or intervention |
| MOI documented | **Hardened** | Trauma only; from transcript or findings |
| Reassessment occurred | **Hardened** | From vitals record and transcript |
| ALS intercept called | **Hardened** | From intervention timeline |
| Pre-arrival notification sent | **Hardened** | From intervention timeline |
| ALS auto-dispatched status | **Hardened** | From agency config via adapted scenario; suppresses "requested ALS" as scored action |
| Non-transport agency status | **Hardened** | From agency config via adapted scenario; changes transport evaluation shape |
| Active MCA scope expansions | **Hardened** | From adapted scenario `mca_expansions`; affects which interventions are in-scope above base level |
| Turnover target | **Hardened** | From scenario (scope-resolved) |
| Scope-resolved required interventions | **Hardened** | From adapted scenario; never static list |

### 6.2 AI-Retained Dimensions

AI retains authority over dimensions that require semantic reading, clinical judgment, or synthesis across multiple evidence sources. These are genuine judgment tasks — not fact checks that belong in the evidence packet.

| Dimension | Authority | What AI evaluates | What AI cannot do |
|---|---|---|---|
| Narrative CHART element presence | **AI** | Semantic read — is the element meaningfully present, even if phrased differently | Cannot accept a CHART element that has no clinical content |
| Narrative CHART element adequacy | **AI** | Is the content clinically adequate, specific, and objective | Cannot inflate adequacy to protect documentation scores when content is missing |
| DMIST component adequacy | **AI** | Is the component content accurate and clinically complete | Cannot award full credit for a component the corroboration index flagged as unsupported |
| Clinical reasoning quality | **AI** | Did the student demonstrate understanding of the presentation — differential thinking, recognition of clinical significance, appropriate prioritization | Cannot credit reasoning that contradicts the run record |
| Professionalism tone | **AI** | Communication quality, patient rapport, partner coordination language — within the hardened professionalism cap | Cannot award full professionalism when the cap is below full due to PPE deduction |
| Assessment sequence quality | **AI** | Did the student follow a logical, organized assessment order relative to the presentation | Cannot credit sequence quality when required assessments are absent |
| Coaching prioritization | **AI** | Which gaps in the evidence packet matter most for this student's learning at this level | Must weight coaching toward clinical safety gaps first |
| Debrief prose — all sections | **AI** | Write clear, practical coaching language for each debrief section based on evidence packet and authored content | Cannot introduce clinical facts not present in the evidence packet or authored scenario fields |
| Teaching point connection | **AI** | Which authored teaching points are most relevant to this student's specific run gaps | Cannot claim a teaching point is irrelevant to avoid uncomfortable feedback |
| Key Takeaways | **AI** | Synthesize the 3–5 most important learning outcomes from this specific run | Must ground takeaways in evidence packet gaps, not generic condition facts |

**Professionalism scoring — explicit scope:**
The AI evaluates: communication tone, patient-directed language, scene management language (calm, organized), partner coordination, use of appropriate titles/pronouns. It does not evaluate whether a greeting occurred (hardened) or whether the professionalism cap was correctly applied (hardened). It scores within the ceiling the evidence packet sets.

**Documentation quality scoring — explicit scope:**
The AI evaluates: CHART element narrative completeness and objectivity; DMIST component clinical adequacy; whether documentation is concise vs. rambling; whether language is objective vs. subjective. It does not determine whether documentation claims are corroborated by run evidence (hardened corroboration index). It scores within the ceiling that corroboration deductions establish.

**Critical boundary — documentation quality is not a factual inference path.** When evaluating documentation quality, the AI evaluates the quality of what was written — not the factual truth of what was implied. A student who writes "applied blow-by O2 with patient in mother's arms and maintained a calm environment" has produced documentation that can be evaluated for clarity and completeness. Whether blow-by actually occurred and whether a calm environment was maintained are facts determined by the evidence packet — not by reading the documentation. The AI must not award clinical performance credit or reduce corroboration deductions because documentation implies an event; it evaluates only the documentation dimension within its hardened ceiling.

**Clinical reasoning scoring — explicit scope:**
The AI evaluates: the transcript holistically for evidence of differential thinking, recognition of clinical significance, appropriate escalation decisions, and understanding of the condition. It does not award clinical reasoning credit for interventions that do not appear in the intervention timeline. It is the only AI-retained dimension that reads the full student transcript rather than a structured evidence packet field.

**Critical boundary — clinical reasoning is not a factual inference path.** When evaluating clinical reasoning, the AI evaluates the quality of reasoning demonstrated in the student's messages — not whether the reasoning implies that an event occurred. A student who says "I think we should apply blow-by since this is an agitated infant" has demonstrated good reasoning; whether blow-by was then registered in the intervention timeline is a separate, hardened fact. The AI must not use clinical reasoning quality as a basis for backdating credit to actions that do not appear in the evidence packet.

### 6.3 Hybrid Dimensions

These require both a hardened constraint and LLM judgment:

| Dimension | Hardened part | AI part |
|---|---|---|
| DMIST score | Ceiling derived from `unsupported_dmist_count` | Score within ceiling; explain what was missing |
| Narrative score | Ceiling derived from `unsupported_narrative_count` | Score within ceiling; evaluate CHART adequacy |
| Clinical Performance | Deductions for missing required interventions, wrong PAT, missing primary survey phases | Score remaining points based on clinical reasoning and assessment quality |
| Transport decision | Whether decision was made and ALS intercept occurred (hardened) | Whether the decision was appropriate for the presentation (AI) |

### 6.4 Explicit "LLM Cannot Infer" List

The following facts must never be determined by LLM judgment. If the evidence packet does not contain a value, the debrief prompt must treat it as unknown and say so explicitly — not infer it from context, pattern-match it from documentation, or substitute clinical expectation.

- PAT recorded result
- PPE items selected
- Professionalism score cap
- Any vital sign value
- Whether reassessment occurred
- Whether an intervention appears in the intervention timeline
- Whether a DMIST or narrative claim is supported by run evidence
- Whether a greeting was present in the transcript
- Whether ALS intercept was called
- Whether pre-arrival notification was sent
- Scope-resolved required interventions for the session
- Whether an intervention or assessment "probably happened" based on how the student described it in documentation or transcript — if it is not in the intervention timeline or a corroborated run record, it did not happen for scoring purposes
- Whether the student should have transported the patient — this depends on `non_transport_agency` from the agency config, not LLM judgment about the scenario
- Whether requesting ALS was required — this depends on `als_auto_dispatched` from the agency config; if ALS was co-dispatched, the LLM cannot penalize for not requesting it
- Whether a scope expansion was active — `mca_expansions` determines this; the LLM cannot assume an EMT had CPAP or IV access without this field confirming it

The LLM can *explain* any of these facts in prose. It cannot *determine* them.

**The implied-fact rule:** This constraint applies inside qualitative scoring tasks, not just in debrief fact claims. When evaluating documentation quality, the AI must not infer that an event occurred from the content of the documentation. When evaluating clinical reasoning, the AI must not backdate credit to actions not in the evidence packet based on the student's stated intent or reasoning. Documentation implies; the evidence packet decides.

---

## 7. Implementation Phases

### Phase 1 — Constraint Enforcement (no schema changes required)

Convert existing advisory blocks into hard constraints. The evidence packet does not yet exist as a formal structure; instead, the pre-computed blocks that already exist become binding on the LLM.

**Changes to `ai_client.py`:**
- Scene entry block: rewrite to state PPE deduction and PAT result as non-negotiable facts, not observations for the LLM to verify
- PAT framing: explicitly distinguish "recorded impression" from "correct expected impression" — eliminate the inversion failure. Frame PAT section as inactive/N/A for adult scenario types.
- Vital value constraint block: inject the actual recorded vital values as a lookup table; instruct the LLM that it may not cite values absent from this table
- What Was Done Well: rewrite section instructions to require run evidence (intervention timeline or student transcript) for every bullet; explicitly prohibit using submitted DMIST or narrative as evidence
- Greeting constraint: inject `greeting_detected` as a hardened fact; LLM cannot claim no greeting when one is detected
- Three-layer evidence framing: add explicit instruction that run performance and documentation quality are scored separately; the LLM must not use one to rescue the other

**Changes to scenario JSON:**
- Add `pat_expected` field to `scene_entry_scoring` (required when PAT popup is enabled)
- Add `pat_deduction` field to `scene_entry_scoring`

**Phase 1 scope:** Closes the PAT inversion bug, vital hallucination, greeting misfact, and What Was Done Well documentation bleed. Does not yet require the evidence packet builder. Scenario-type awareness is implicit — the debrief prompt already receives scenario `category`, which can be used to conditionally include/exclude PAT framing.

**Phase 1 implementation status: COMPLETE (2026-04-24)**

---

### Phase 2 — Evidence Packet Builder

Implement `_build_evidence_packet()` as a Python function in `ai_client.py`. The function takes the *adapted* session scenario, submitted docs, and findings rows and returns a structured dict following the schema in §5.

**Changes to `ai_client.py`:**
- Implement `_build_evidence_packet(adapted_scenario, session, submitted_docs, findings)`
- Populate `scenario_context` (§5.0) from adapted scenario — including scenario_type, provider_level, mca, turnover_target
- Replace individual pre-computed block builders with evidence packet sections
- Restructure debrief prompt to inject evidence packet as the primary scoring input using **delta-only injection** — see prompt engineering principle below
- Add score ceiling logic: pre-fill clinical performance, DMIST, and narrative subscores with hardened floors/ceilings before LLM sees them; LLM adjusts only within the allowed range
- Populate `assessment_phases` (§5.5) and `transport` (§5.6) from transcript and intervention timeline
- Implement two-tier corroboration: Tier 1 (structural/factual — deterministic Python), Tier 2 (semantic adequacy — LLM extraction pass). See §5.4 implementation approach.

**Phase 2 Tier 1 implementation status: COMPLETE (2026-04-24)**

Implemented in `ai_client.py`:
- `_build_evidence_packet()` — populates §5.0 (scenario_context), Universal Base gaps (7 presence checks from transcript + backend records), §5.2 (intervention record), §5.4 Tier 1 corroboration (DMIST D/M/I/S/T and narrative C/H/A/R/T structural presence checks), `required_assessments` detection (scenario-declared exam steps checked against transcript, findings, and submitted DMIST/narrative), `required_screens` detection (scenario-declared differential screens checked against transcript, findings, and submitted DMIST/narrative), §5.7 (professionalism/greeting)
- `_format_evidence_packet_for_prompt()` — delta-only injection (gaps, structural flags, required assessment and screen gaps with per-gap deduction annotations; does not duplicate PPE/PAT/greeting/O2 contradiction/required-intervention blocks already present)
- Score ceiling logic — post-LLM hard enforcement for no-submission cases (`dmist_enforce=True`, `narrative_enforce=True`); prompt-guided ceiling for structural gap cases (`dmist_enforce=False`)
- Module-level detection patterns: `_SCENE_SAFETY_RE`, `_PRIMARY_SURVEY_RE`, `_HISTORY_RE`, `_DISPOSITION_RE`, `_REASSESSMENT_RE_UB`, `_DMIST_COMPONENT_PATTERNS`, `_CHART_ELEMENT_PATTERNS`

Implemented in scenario JSON (all 12 scenarios):
- `scoring.required_assessments` added to all 12 scenarios (11 pediatric + adult STEMI) — clinical exam steps specific to each presentation (lung sounds, WOB, BG check, temp, CMS pre/post, neuro assessment, inhalation screen, BSA estimation, shock signs, 12-lead ECG, etc.)
- `scoring.required_screens` added to 6 scenarios: `peds_croup_01.json` (epiglottitis, −3 pts), `peds_febrile_seizure_01.json` (meningitis, −2 pts), `peds_diabetic_emergency_01.json` (AMS differential, −2 pts), `peds_asthma_01.json` (foreign body aspiration, −2 pts), `peds_trauma_04_burn.json` (NAT/abuse screen, −2 pts), `peds_trauma_06_handlebar.json` (solid organ injury, −3 pts)
- Adult STEMI `required_screens`: aortic dissection screen (−2 pts)
- `scene_entry_scoring.pat.expected_impression` and `incorrect_impression_deduction` added to all 11 pediatric scenarios (Phase 1 complete)

**Previously pending (deferred to Phase 3) — now resolved:**
- §5.5 Assessment Phases — **COMPLETE (2026-04-24).** `primary_survey`, `history_secondary`, and `reassessment` populated from transcript regex matching; trauma vs. medical branching from `category`; 13 new regex constants (`_LOC_RE`, `_AIRWAY_RE`, `_BREATHING_RE`, `_CIRCULATION_RE`, `_HEMORRHAGE_RE`, `_CSPINE_RE`, `_DISABILITY_RE`, `_MOI_RE`, `_SAMPLE_RE`, `_OPQRST_RE`, `_TRANSPORT_DECISION_RE`, `_ALS_INTERCEPT_RE`, `_DISPOSITION_DMIST_RE`)
- §5.6 Transport/Disposition — **COMPLETE (2026-04-24).** `transport` dict populated from agency config (`non_transport_agency`, `als_auto_dispatched`) and transcript detection; weight field reflects trauma vs. medical priority; `_format_evidence_packet_for_prompt()` updated with delta-only gap rendering for both sections

**Phase 3 remaining items: COMPLETE (2026-04-24)**
- Full prompt restructure — **COMPLETE.** Consolidation of all three standalone builders into evidence packet complete; see Phase 3 implementation status block below.
- `corroboration_rules` field — **COMPLETE.** Per-scenario claim-deduction ranges annotated on all Tier 2 claims; 2-pt default when no scenario rule; `peds_anaphylaxis_01` and `peds_trauma_04_burn` updated with scenario-specific rules.
- `scoring.suppress_universal` — schema defined in `SCENARIO_DESIGN_EMS.md`; no scenarios currently need suppression (not a blocking Phase 3 item).

**Score ceiling pre-filling — COMPLETE (2026-04-24):**
- For `enforce=True` ceilings (no-submission cases): `_dmist_locked` and `_narrative_locked` flags are computed from the evidence packet before the debrief prompt is assembled. The score breakdown template injects `0/10 (locked)` / `0/20 (locked)` instead of `X/10` / `X/20` so the LLM is not asked to score a dimension with a deterministic result. The subscores JSON format in the RESPONSE FORMAT instruction pre-fills the locked value (`"dmist": 0`) so the LLM returns the correct value directly.
- The post-LLM clip (`min(old, ceiling)`) is retained as a belt-and-suspenders safety net for any case where the model ignores the pre-fill instruction.
- Debrief regex fallback resolved: removed redundant Layer 2 regex fallback from both route handlers in `main.py` (dead code — `_extract_required_debrief_subscores` already guarantees all required keys or raises `ValueError`). Added `_log.warning()` to Layer 1 in `_extract_required_debrief_subscores` so regex recovery is visible in production logs.

**Phase 2 Tier 2 implementation status: COMPLETE (2026-04-24)**

Implemented in `ai_client.py`:
- `_run_corroboration_prepass()` — async function; 12-second hard timeout via `asyncio.wait_for`; uses `groq_lexi_model` (20b) at temperature 0.1 with JSON mode; validates output schema before accepting claims; silent fallback to Tier 1 only on any failure (timeout, API error, malformed JSON)
- Pre-pass prompt: detects claims for interventions not in timeline (fabrication), wrong intervention method (contradiction), out-of-range vital values, and wrong patient demographics. Deliberately conservative — paraphrasing and equivalent clinical terminology are explicitly protected. False positives are treated as worse than false negatives.
- Optional `dmist_components` parameter: when the scenario has `scoring.dmist_components`, the pre-pass receives per-component corroboration source guidance (demographics → patient record, interventions → timeline, vitals → findings record) making detection more scenario-aware
- Final vitals trajectory included in vitals summary: "arrival X → run-end Y" format lets the LLM detect when documented values exceed the run's actual range
- `_build_evidence_packet()` now accepts `prepass_result` and incorporates `dmist_unsupported_claims` and `narrative_unsupported_claims` into the corroboration section; `tier` field reflects 1 or 2 based on pre-pass availability
- `_format_evidence_packet_for_prompt()` renders Tier 2 findings as quoted claim + reason pairs with explicit "do not award credit for these contradicted claims" instruction; renders a clean "no contradictions detected" confirmation when pre-pass ran clean
- Call site in `evaluate_and_generate_debrief`: patient summary + baseline-to-final vitals trajectory compiled inline; `scoring.dmist_components` passed when present; pre-pass called before evidence packet build; result passed as `prepass_result`

Implemented in scenario JSON:
- `scoring.dmist_components` added to all 11 ALS-turnover scenarios — with corroboration source annotations per component (scenario_patient_fields, intervention_timeline, vitals_and_findings, any). Hospital-turnover STEMI correctly omits this field. Each component includes patient-specific `required_elements` and `corroboration_source` to guide the pre-pass LLM toward the right evidence source per claim type. Critical notes added for scenarios where a specific intervention method must match the timeline (e.g., epinephrine route in anaphylaxis, CMS pre/post in extremity fracture, dressing type in burns).

Also completed in this phase:
- `required_assessments` and `required_screens` added to all 12 scenarios (11 pediatric + adult STEMI)
- Adult STEMI `required_assessments`: 12-lead ECG (−5 pts), cardiac history (−2 pts), aspirin safety check (−2 pts)
- Adult STEMI `required_screens`: aortic dissection screen (−2 pts)

**Prompt engineering principle — delta-only injection:**

The debrief LLM does not need a complete audit of every correct step. Injecting the full evidence packet wastes context window and risks "lost in the middle" degradation where the LLM ignores instructions buried in large prompts.

The evidence packet injected into the debrief prompt contains only:
- **Gaps** — universal base elements that were absent or failed
- **Deductions** — hardened deductions with their traceable source (scenario rule + run record comparison)
- **Flags** — corroboration index items flagged for AI evaluation (not auto-deducted)
- **Ceilings** — pre-computed score ceilings for hybrid dimensions
- **Context** — scenario type, provider level, turnover target, grace items (needed for AI to frame feedback correctly)

Correct steps are excluded from the injected packet. The LLM's instruction is "explain and coach from the gaps and flags in this packet." It does not need to know that the student correctly obtained vitals at minute 2 — it needs to know that reassessment did not occur after the intervention. Token budget is reserved for authored educational content and transcript context, not a full run audit.

**Changes to scenario JSON:**
- Add `pat_expected` and `pat_deduction` (if not done in Phase 1)
- Add `dmist_components` field — describes what counts as D, M, I, S, T for this specific scenario (used for corroboration index generation). See §8.2.
- Add `corroboration_rules` to `scoring` — defines which DMIST/narrative claim types are deduction-eligible and what the per-violation deduction range is
- Add `required_screens` to scenario — scenario-specific clinical screens expected in assessment (e.g., epiglottitis differential for croup)

**Changes to `SCENARIO_DESIGN_EMS.md`:**
- New section documenting `scene_entry_scoring.pat` fields
- New section documenting `scene_entry_scoring.scene_safety` structure and when to use `scene_is_safe: false`
- New section documenting `scoring.critical_vitals` tiers (required / important / optional)
- New section documenting `scoring.required_assessments` and `scoring.required_screens` — distinction between routine exam expectations and differential screening
- New section documenting `scoring.dmist_components` structure
- New section documenting `scoring.suppress_universal` with guidance on when suppression is appropriate
- Scoring specification architecture overview (three-layer model from §4A, §4B)
- Authored content requirements for new scenarios
- Updated authoring checklist

**Changes to `AI_ARCHITECTURE.md`:**
- New section: Evidence Packet — what it contains, how it constrains the LLM
- Updated debrief section: redefine LLM's role as feedback writer, not adjudicator
- Update scoring authority table
- Add three-layer evidence principle to AI behavioral constraints

**Phase 2 scope:** Closes the corroboration scoring inflation failure. Provides the structural foundation for Phase 3. Scenario-type activation is fully operational.

---

### Phase 3 — Full Restructure (target state)

The debrief prompt is restructured around the evidence packet as the single source of truth. Subscores for hardened dimensions are pre-computed before the LLM call. The LLM's prompt changes from "evaluate this run" to "given these adjudicated facts, explain the case and coach the learner."

**Changes to `ai_client.py`:**
- `_build_evidence_packet()` outputs a Pydantic model, not a raw dict
- Pre-filled subscores are passed to the LLM as constraints, not computed by it
- LLM is asked to: (a) write prose for each debrief section, (b) fill qualitative subscores within hardened ceilings, (c) produce coaching language for each gap in the evidence packet
- DMIST and narrative evaluations become focused AI tasks: "given that these claims are unsupported, explain what was missing and why it matters" — not "decide whether these claims are supported"
- Clinical performance feedback is structured by NREMT phase: scene, primary survey, history/secondary, treatment, reassessment. LLM output language should be practical and clinical, not exam-station.

**Changes to `models.py`:**
- Consider persisting the evidence packet as a JSON column on the session or debrief record — enables audit trails, instructor review, and future appeals
- The persisted packet is the forensic record of why each score was assigned

**Phase 3 scope:** Full separation of adjudication from feedback writing. At this point the LLM is genuinely operating as a feedback writer over adjudicated facts.

**Phase 3 implementation status: COMPLETE (2026-04-24)**

Completed:
- §5.5 Assessment Phases added to `_build_evidence_packet()` — `primary_survey` (LOC, airway, breathing, circulation; plus hemorrhage, C-spine, disability, MOI for trauma), `history_secondary` (SAMPLE, OPQRST), `reassessment` (after-intervention check, response documented from narrative)
- §5.6 Transport/Disposition added to `_build_evidence_packet()` — agency config fields (`non_transport_agency`, `als_auto_dispatched`), transcript-detected transport decision and ALS intercept, disposition from DMIST, trauma/medical weight differentiation
- 13 new module-level regex constants for §5.5/§5.6 transcript detection
- `_format_evidence_packet_for_prompt()` updated to render §5.5 and §5.6 gap rows (delta-only injection)
- 27 new tests in `tests/test_evidence_packet.py`
- **Full prompt restructure — COMPLETE (2026-04-24).** Critical actions classification (formerly `_build_critical_actions_block`), protocol-indicated assessment detection (formerly `_build_protocol_indicated_assessment_block`), and O2 delivery conflict detection (formerly `_build_documentation_conflict_block`) migrated into `_build_evidence_packet()`. All three standalone builder functions removed. `_format_evidence_packet_for_prompt()` now renders `## CORRECT CRITICAL ACTIONS` and `## DOCUMENTATION CONFLICTS` sections. The evidence packet is the single source of truth for the debrief prompt — no standalone adjudication blocks remain. IMPORTANT SCORING RULES updated to reference the EVIDENCE PACKET instead of named standalone blocks. Tests in `test_gamification_regressions.py` updated to test via `_build_evidence_packet` + `_format_evidence_packet_for_prompt`. 30/30 regression tests pass.
- **Evidence packet persistence — COMPLETE (2026-04-24).** `evaluate_and_generate_debrief` now returns `(debrief_text, subscores, evidence_packet)` as a 3-tuple. `SimSession.evidence_packet` added as a nullable JSONB column; migration added to `database.py::init_db()` (`ALTER TABLE sessions ADD COLUMN IF NOT EXISTS evidence_packet JSONB`). Both `submit_narrative` and `skip_narrative` route handlers persist the evidence packet at the same DB commit that writes the debrief text and subscores. The persisted packet contains the full Phase 3 adjudication record: scenario context, universal base results, intervention record, corroboration (Tier 1 + Tier 2 + O2 conflicts), required assessment and screen results, assessment phases, transport/disposition, professionalism, score ceilings, and critical actions classification.
- **`corroboration_rules` — COMPLETE (2026-04-24).** `_build_evidence_packet()` reads `scoring.corroboration_rules` and annotates each Tier 2 unsupported DMIST and narrative claim with `max_deduction` (defaults to 2 if no scenario rule) and `rule_note`. `_format_evidence_packet_for_prompt()` renders the cap inline: `"[I] \"claim\" — reason — deduct up to 3 pts from DMIST"`. `corroboration_rules` added to `peds_anaphylaxis_01.json` (DMIST I: 3 pts; Narrative A, R: 2 pts each) and `peds_trauma_04_burn.json` (DMIST I: 3 pts; Narrative A, T: 2 pts each). Schema documented in `SCENARIO_DESIGN_EMS.md §14`. 2 new regression tests added; 30/30 total pass.

---

**Phase 4 — Learning System implementation status: COMPLETE (2026-04-28)**

Completed (learning system features, not evidence packet evaluation phases):

- **§5.8 Challenge results — COMPLETE.** `challenge_results` list and `impression_challenge` dedicated field added to `_build_evidence_packet()`. Challenge outcomes are read from `challenge_completed` SessionEvents (`source: backend_auto`). `impression_challenge_ep` includes `student_answer`, `correct`, `acceptable`, `result`, and `timestamp_relative_to_first_intervention`. `acceptable` is stored in the SessionEvent at challenge submission time so the ep can reproduce full scoring context without re-reading scenario JSON.
- **Next Action routing — COMPLETE.** `_compute_reasoning_flags()` reads `impression_challenge_result` from `evidence_packet.impression_challenge.result` (was hardcoded `None`). Priority 2 routing rule (incorrect impression → replay current scenario) now fires correctly.
- **Primary survey milestone detection — COMPLETE.** `_check_and_fire_primary_survey_milestone()` in `main.py`: authoritative path checks all `phase: "primary_survey"` required_assessment items against `explicit_assessment` SessionEvents; fallback fires when any authoritative EA + interventions or ≥4 user messages. Idempotent (guarded by `milestone_fired` SessionEvent). Wired into chat SSE stream; emits `challenge_available` SSE event when impression challenge is enabled.
- **Shared challenge shell — COMPLETE (Phase 3, 2026-04-28).** `POST /api/sessions/{id}/challenge-response` uses adapted scenario (not base); `_evaluate_challenge_answer` returns `(result, resolved_block)` tuple; `challenge_completed` event excluded from `_SESSION_EVENT_TYPES` (not client-submittable).
- **Debrief response contract consistency — COMPLETE.** All debrief paths (narrative fresh, narrative cached, skip fresh, skip cached, re-debrief, drill) now return `impression_challenge`, `dmist_primary_impression`, `top_takeaways`, `reflection_prompts`, `next_action*`. BLUF fields (`top_takeaways`, `reflection_prompts`, `next_action`, `next_action_target_type`, `next_action_target_id`) are persisted to `session.narrative_data` at debrief write time so cached re-serves are consistent without re-running the LLM.
- **Three-way impression comparison — COMPLETE.** Debrief modal (live and history) renders early impression (challenge), final impression (DMIST field), and correct impression (scenario) in a comparison table. History `debriefEntry` persists all BLUF and impression fields for reopened sessions.
- **Scenario authoring — COMPLETE.** `peds_asthma_01`, `peds_croup_01`, `peds_anaphylaxis_01` receive `impression_challenge` blocks and `phase: "primary_survey"` tags on relevant `required_assessments` items.

---

### Performance, Scalability, and Error Handling

#### Latency Profile

The new architecture adds one step to the debrief path: the **Tier 2 corroboration pre-pass** (a small, low-temperature LLM call that classifies DMIST and narrative claims before the debrief call runs). Everything else in the evidence packet builder is pure Python computation — stateless, sub-100ms, negligible latency.

| Step | Type | Latency Impact |
|---|---|---|
| Evidence packet builder | Python (deterministic) | Negligible — sub-100ms |
| Tier 1 corroboration | Python (deterministic) | Negligible |
| Tier 2 corroboration pre-pass | LLM API call (small, constrained) | New — est. 2–5s |
| Debrief LLM call | LLM API call | Neutral to slight decrease (delta-only input is smaller than current raw-data prompt) |

The debrief is not real-time chat. Users already wait for it. A few added seconds for the Tier 2 pre-pass is acceptable. Net wall-clock time for the full debrief pipeline is expected to increase modestly — primarily the Tier 2 pre-pass duration.

**Delta-only injection reduces debrief input tokens.** The current debrief prompt sends raw vital log arrays, raw intervention lists, and redundant scenario data. The evidence packet replaces these with compact structured findings. The debrief prompt input should be neutral to smaller despite the richer structure. The chat transcript remains (qualitative dimensions still need it) — it is the dominant token consumer and does not change.

#### Scalability

The evidence packet builder introduces no new shared state and no new database bottlenecks. It reads from existing tables (interventions, vitals, session) that are already accessed during debrief. It scales horizontally with the application servers under FastAPI's existing async architecture.

The Tier 2 pre-pass is a new LLM API call per scenario completion. At low user counts this is immaterial. At scale:

- **Debrief events are low-frequency** relative to in-scenario chat messages. One debrief per scenario run vs. many chat turns per run. This is not a high-throughput path.
- **The pre-pass is cheap per call** — small input, constrained output, low temperature. Rate limit budget impact is minor.
- **No synchronous bottleneck** — both the pre-pass and the debrief call are async under the existing FastAPI/asyncio pattern. Concurrent debrief requests do not block each other.
- **Phase 2 instrumentation required** — measure actual token usage and latency per call at scale before adjusting any limits. Do not pre-optimize.

Token limits should not be adjusted in advance of Phase 2 measurement. If the debrief output benefits from more room for richer coaching prose (the LLM is now freed from adjudication work), increase the debrief output limit based on observed output quality — not based on assumption.

#### Error Handling and Graceful Degradation

The new architecture has two LLM calls at debrief time. Both must be handled independently.

**Tier 2 corroboration pre-pass failure policy:**

The pre-pass must have a firm, short timeout. If it fails or times out, the system does **not** fail the debrief. It falls back to Tier 1 corroboration only and notes the pre-pass was unavailable in the evidence packet. The debrief still runs with hardened Tier 1 facts. This is materially better than no debrief.

| Pre-pass outcome | Behavior |
|---|---|
| Success — valid structured JSON | Tier 2 findings injected into evidence packet |
| Partial output — schema validation fails on some claims | Accept valid claim classifications; mark remainder as `unverifiable`; proceed |
| Timeout or API error | Fallback to Tier 1 only; flag in evidence packet; debrief proceeds |
| Retry exhausted | Fallback to Tier 1 only; debrief proceeds |

**Debrief LLM call failure policy:**

Same as today — async retry with exponential backoff, configurable max retries. If retries are exhausted, surface a clear error to the user. The debrief is not written as a partial result; it either succeeds or fails clearly. Do not silently surface an incomplete debrief.

**Tier 2 output validation:**

The pre-pass output is a structured JSON claim classification. It must be schema-validated before injection into the evidence packet. A malformed or incomplete response is treated as a partial failure — accept what validates, mark the rest as `unverifiable`. The debrief LLM is never given raw, unvalidated Tier 2 output.

**Retry strategy summary:**

| Call | Timeout | Retries | Failure behavior |
|---|---|---|---|
| Tier 2 pre-pass | Short (10–15s) | 1–2 with backoff | Fallback to Tier 1 only; debrief proceeds |
| Debrief call | Existing timeout | Existing retry config | Surface error to user if exhausted |

---

## 8. Required Scenario Schema Changes

These new fields are required for Phase 2. Phase 1 requires only `pat_expected` and `pat_deduction`.

Full field schemas for scene safety, PPE, critical vitals, required assessments, and required screens are defined in §4B. This section captures the complete list of changes needed and cross-references §4B for schema detail.

**Phase 1 additions (scenario JSON):**
- `scene_entry_scoring.pat.expected_impression`
- `scene_entry_scoring.pat.incorrect_impression_deduction`

**Phase 2 additions (scenario JSON):**
- `scene_entry_scoring.scene_safety` — see §4B Scene Safety
- `scoring.critical_vitals` — see §4B Critical Vitals
- `scoring.required_assessments` — see §4B Required Assessments
- `scoring.required_screens` — see §4B Required Screens
- `scoring.dmist_components` — see §8.2
- `scoring.corroboration_rules` — see §8.3
- `scoring.suppress_universal` — opt-out list for universal elements

---

### 8.1 Scene Entry Scoring — PAT Fields

Required only when `scene_entry_scoring.pat.enabled == true`. The scenario author determines whether PAT applies — not the category tag.

```json
"scene_entry_scoring": {
  "ppe": { ... },
  "scene_safety": { ... },
  "pat": {
    "enabled": true,
    "expected_impression": "SICK",
    "incorrect_impression_deduction": 2,
    "note": "Patient has SpO2 93%, audible stridor at rest, subcostal retractions — SICK impression required"
  }
}
```

| Field | Required | Description |
|---|---|---|
| `enabled` | yes | Whether PAT is used in this scenario; scenario author decides, not category |
| `expected_impression` | yes, when enabled | `"SICK"` or `"NOT_SICK"` |
| `incorrect_impression_deduction` | yes, when enabled | Points deducted from Clinical Performance for wrong impression |
| `note` | recommended | Clinical rationale — injected into debrief as hardened explanation |

### 8.2 DMIST Component Definitions

Required when `turnover_target == "als"`. Describes what counts as each DMIST component for this specific scenario, driving the corroboration index.

```json
"dmist_components": {
  "D": {
    "description": "Patient demographics",
    "required_elements": ["patient name or 'Lily'", "age or '10-month'", "weight or '9 kg'"],
    "corroboration_source": "scenario_patient_fields"
  },
  "M": {
    "description": "Mechanism and chief complaint",
    "required_elements": ["croup", "stridor", "barking cough"],
    "corroboration_source": "any"
  },
  "I": {
    "description": "Interventions performed",
    "required_elements": ["oxygen delivery method"],
    "corroboration_source": "intervention_timeline",
    "note": "Oxygen delivery method must match what is registered in the intervention timeline"
  },
  "S": {
    "description": "Signs — current patient status",
    "required_elements": ["SpO2", "work of breathing", "stridor severity"],
    "corroboration_source": "vitals_and_findings"
  },
  "T": {
    "description": "Treatment status and disposition",
    "required_elements": ["current condition", "ALS readiness"],
    "corroboration_source": "any"
  }
}
```

For hospital-turnover scenarios, a `pre_arrival_components` field with analogous structure replaces `dmist_components`.

### 8.3 Scoring — Corroboration Rules

```json
"scoring": {
  "corroboration_rules": {
    "dmist_unsupported_claim_deduction": [1, 2],
    "narrative_unsupported_claim_deduction": [2, 4],
    "max_dmist_deduction_from_unsupported": 4,
    "max_narrative_deduction_from_unsupported": 8
  }
}
```

These ranges become hardened ceiling inputs for the hybrid DMIST and narrative scoring dimensions.

### 8.4 Required Screens

Scenario-specific clinical screens that are expected as part of a complete assessment. Presence is tracked by layer (transcript vs. documentation).

```json
"required_screens": [
  {
    "id": "epiglottitis_differential",
    "description": "Epiglottitis differential screening",
    "keywords": ["epiglottitis", "drooling", "tripod", "jaw thrust position"],
    "credit_scope": "clinical_performance",
    "note": "Failure to screen for epiglottitis in a pediatric stridor presentation is a clinical gap"
  }
]
```

---

## 9. Open Questions

These questions must be resolved before or during Phase 2 implementation. They are not blockers for Phase 1.

**O2 popup disconnect:** The most persistent source of documentation conflicts is the popup registering a different O2 method than what the student said in chat. The evidence packet will correctly flag this as a system-generated discrepancy (via `partner_ambiguity_flags`), but the root cause — popup defaulting to a different device than what was said — remains a frontend UX problem. Phase 2 implementation should treat O2 popup discrepancies as non-student-penalized flags, not deductions, until the popup pre-population issue is resolved.

**Evidence packet persistence:** Should the evidence packet be persisted as a JSON column on the session or debrief record? Arguments for: enables instructor review, audit trails, appeals, analytics on common failure modes. Arguments against: adds schema complexity and migration. Recommendation: add as an optional/nullable column in Phase 2 and populate it; use it for diagnostics before making it load-bearing.

**DMIST component corroboration precision — resolved:** The two-tier corroboration approach in §5.4 resolves this. Tier 1 (deterministic Python) handles structural omissions and factual contradictions where IDs and numeric values can be compared directly. Tier 2 (LLM extraction pass) handles semantic adequacy — a small, low-temperature LLM call extracts structured claims from the free-text DMIST/narrative and compares them against the intervention timeline. This extraction LLM is not the debrief LLM; it only classifies, and its output is what the debrief LLM reads as hardened corroboration facts. This approach avoids both the brittleness of pure regex and the adjudication drift risk of leaving corroboration entirely to the debrief LLM.

**Backward compatibility:** Existing scenarios do not have `pat_expected`, `dmist_components`, or `corroboration_rules`. The evidence packet builder must degrade gracefully when these fields are absent — falling back to the current advisory-only behavior for unaugmented scenarios. New scenarios must include these fields. A validation warning (not error) is appropriate for missing fields during Phase 2.

**NREMT phase language vs. practical language:** The evidence packet uses NREMT phase structure internally (scene size-up, primary survey, history, treatment, reassessment). The LLM feedback output should use practical clinical language that students and working providers recognize — not exam-station language. Phase 3 prompt design should include guidance on how to translate phase gaps into natural coaching language.

**Instructor override — COMPLETE (2026-04-24):** `AdjudicatedOutcome` model extended with `override_findings JSONB` column (cites specific evidence packet dimensions being corrected). Input validation added to `create_adjudication`: score range 0–100, valid subscore keys, at least one correction required, `reason_notes` required for `human_appeal`. `_effective_score()` and `_effective_subscores()` helpers compute the live-effective grade from the latest adjudication or original session. `GET /api/sessions/{session_id}/adjudications` added (instructor-only, returns original score, effective score, and full adjudication history with adjudicator usernames). `GET /api/admin/sessions/{session_id}` updated to include `evidence_packet`, `adjudications`, `effective_score`, `effective_subscores`, `has_adjudication`. `GET /api/admin/sessions` list updated to include `effective_score` and `has_adjudication`. `GET /api/me/sessions` updated to surface `effectiveScore`, `adjudicated`, and corrected subscores to students. Superuser cross-agency access respected on all instructor endpoints. 12 new regression tests; 192/192 pass.

**Pre-arrival report corroboration:** For hospital-turnover scenarios, the handoff format is a radio pre-arrival report rather than DMIST. The corroboration index structure should support both. The `pre_arrival_components` field (§8.2) defines the analogous structure, but the LLM evaluation task differs — radio report adequacy is more about brevity and priority ordering than component completeness.

**`scoring.by_level` grace items and hardened deductions:** The `scoring.by_level` field contains level-specific grace items that directly affect what can and cannot be penalized. For example, the croup scenario's EMT-level grace items state that PAT need not be named by acronym and that a failed history attempt should not be penalized. These grace items must be surfaced to the LLM in the evidence packet — but they also interact with hardened deductions. If a hardened deduction fires for something a grace item protects, the deduction must be suppressed. The Phase 2 evidence packet builder must read grace items from `scoring.by_level[active_level].grace_items` and apply them before finalizing hardened deductions. This is a non-trivial resolution step and must be designed carefully.

**Condition background completeness across scenarios:** The authored content policy (§11) requires `condition_background`, `key_teaching_points`, and `common_mistakes` for all production scenarios. Current scenarios vary in completeness. A content audit should precede the Phase 2 prompt restructure so the new prompt can rely on these fields being present.

**Documentation scoring calibration — don't over-harden early:** The corroboration model is architecturally correct but can become too punitive if deduction thresholds are set too aggressively. EMS documentation legitimately contains information the student did not verbalize in chat — a student who assessed and treated correctly but wrote concisely should not be penalized the same as one who fabricated care. The implementation rule: keyword-level mismatches and paraphrasing differences should be flagged for AI evaluation, not auto-deducted. Hard deductions apply only to structural omissions (entire component absent) or clear factual contradictions (documented intervention not in timeline). Calibration should begin conservatively and tighten after observing real runs. Error on the side of under-deducting in Phase 2; tighten in Phase 3 after audit data is available.

**Detection heuristic validation and the UI-button alternative:** Several evidence packet fields rely on transcript keyword matching that has not yet been tested at scale. Medical roleplay language is too varied for regex to reliably detect complex intents (e.g., "so talk me through what happened" may be a valid history attempt that no keyword set catches cleanly). Before Phase 2 makes transcript-based detections load-bearing, two paths should be evaluated in parallel:

*Path A — Keyword validation:* Run detection rules against a corpus of real session transcripts. Measure false-positive and false-miss rates. Adjust keyword sets before enabling deductions. Highest-risk surfaces: primary survey presence, history attempted, disposition addressed, required assessment detection.

*Path B — UI-driven milestone signals (preferred where feasible):* Immersive Mode's action bar can provide explicit clinical milestone buttons (Primary Survey, Obtain History, Reassess Patient). A student clicking these buttons produces an authoritative backend signal — no transcript parsing required. Where Immersive Mode is the primary interface, prefer UI signals over transcript detection for universal base elements. Transcript detection remains as a fallback for students who skip the button and verbalize instead.

Path B eliminates the brittleness problem entirely for the elements it covers. It should be the priority investment for the highest-risk detection surfaces.

**Trauma and transport scenario generalization — reserved for explicit design pass:** The current plan is compatible with adult trauma, hospital-turnover, and transport-capable scenarios, but most examples and defaults are still pediatric-medical-forward. Before the first trauma or hospital-turnover scenario enters the evidence packet system, a dedicated design pass is needed to finalize: MOI-specific evidence fields, trauma primary survey ABCDE weighting, transport destination decision scoring, hospital pre-arrival communication corroboration, and receiving-target-specific handoff adequacy. This is an explicit implementation watchpoint — do not apply the current evidence packet schema to trauma scenarios without this design pass.

---

## 10. Impact on Other Documents

The following documents require updates when the phases above are implemented.

| Document | What changes | When |
|---|---|---|
| `AI_ARCHITECTURE.md` | Add evidence packet section; redefine LLM debrief role as feedback writer; add three-layer evidence principle; update scoring authority table; document vital value constraint; document authored content policy (§11) | Phase 1 (partial), Phase 2 (full) |
| `SCENARIO_DESIGN_EMS.md` | Add §§ for `scene_entry_scoring.pat`, `dmist_components`, `scoring.corroboration_rules`, `required_screens`, `suppress_universal`; add scoring specification architecture overview (three-layer model from §4A); add authored content requirements for new scenarios; update authoring checklist | Phase 2 |
| `SCENARIO_ENGINE_ARCHITECTURE.md` | Document evidence packet as a new engine output; update debrief flow diagram; document adapted scenario as required input to evidence packet builder | Phase 2 |
| `DEVELOPMENT_GUIDELINES.md` | No structural changes needed — this architecture is consistent with existing mandates in §3.1 | — |

Existing scenario JSON files will need `pat_expected` and `pat_deduction` added to `scene_entry_scoring.pat` before Phase 2 scoring becomes fully hardened for PAT. This is a scenario content migration, not a code migration. Scenarios where `pat.enabled == false` or the field is absent do not need PAT deduction fields. Adult scenario files must not have `pat.enabled: true`.

All scenarios lacking `debrief_info.condition_background`, `key_teaching_points`, or `common_mistakes` should have these authored before Phase 2 goes to production — the debrief prompt change in §11.4 will expose the gap if content is missing.

---

## 11. Authored vs. Generated Educational Content

### 11.1 Policy

Clinical education content in the debrief is authored in the scenario file and surfaced by the AI — not generated by the AI from scratch. This applies to:

- Condition background and pathophysiology
- Protocol rationale and treatment reference
- Key teaching points
- Common mistakes for this condition

The AI's role for these sections is to **present and connect** — not to generate. Specifically:
- Present the authored content (may rephrase for natural prose, but does not add or subtract clinical facts)
- Connect teaching points to gaps identified in the evidence packet ("your missed epiglottitis screen is directly relevant to teaching point #3 in this scenario...")
- Frame the condition in terms of what the student's specific gaps indicate about their understanding

### 11.2 What Already Exists

These fields already exist in scenario JSON and contain reviewed, authored content:

| Field | Content |
|---|---|
| `debrief_info.condition_background` | Pathophysiology, clinical presentation, BLS challenge summary, most common errors |
| `debrief_info.key_teaching_points` | Ordered list of the most important clinical lessons for this scenario |
| `debrief_info.common_mistakes` | Common errors specific to this condition — what students typically misunderstand |
| `scoring.overall_considerations` | Scoring-focused clinical guidance, including what should and should not be penalized |

The `condition_background` field in the croup scenario is an example of the target quality level — it covers pathophysiology, the BLS challenge, what racepinephrine does and why it's not on BLS units, and the most common diagnostic error (albuterol for stridor). This is clinical content that cannot be generated reliably by an LLM and should not be.

### 11.3 What the AI Generates

The AI generates only content that requires connecting authored facts to this specific run:

- **Run-specific narrative** — "In this run, you correctly identified stridor but did not perform an epiglottitis screen" — requires knowing what actually happened
- **Score explanations** — why each hardened deduction was applied, in coaching language
- **Coaching prioritization** — which gaps matter most given the overall pattern in the evidence packet
- **Qualitative scoring** — adequacy of the narrative and DMIST within hardened ceilings

The AI does **not** generate:
- Pathophysiology explanations (authored)
- Drug mechanism or dosage references (authored)
- Protocol rationale (authored or in protocol file)
- Common mistakes for this condition (authored)

### 11.4 Phase 2 Debrief Prompt Change

In Phase 2, the debrief prompt restructure must reflect this policy. The current prompt asks the AI to "write a comprehensive debrief including condition background and treatment reference." This must change to:

> "The following condition background, teaching points, and common mistakes are authored for this scenario. Present this content and connect it to the gaps identified in the evidence packet. Do not generate pathophysiology or treatment facts not present in the authored sections below."

### 11.5 New Scenarios

New scenario authors must write `condition_background`, `key_teaching_points`, and `common_mistakes` for every new scenario before the scenario is marked ready for production. These fields are not optional. A scenario without authored educational content cannot produce accurate or consistent debrief education regardless of how well the evidence packet is built.

---

## 13. Debrief Structured Output Contract

This section defines the complete JSON schema the AI must return at the end of a debrief call. All fields are required unless marked optional. Fields populated by the backend before the LLM call are marked `[backend-populated]` — the AI receives them as hard inputs and generates phrasing only.

The debrief UI, backend route handlers, and AI prompt must all reference this contract. Do not add new debrief output fields without updating this schema and the sections below.

### 13.1 Schema

```json
{
  "clinical_performance": <int>,
  "narrative": <int>,
  "scope_adherence": <int>,
  "dmist": <int>,
  "professionalism": <int>,

  "top_takeaways": [
    "<string — run-specific takeaway grounded in evidence packet gaps>",
    "<string>",
    "<string>"
  ],

  "reflection_prompts": [
    "<string — run-specific prompt for internal processing; no response required>",
    "<string — optional second prompt>"
  ],

  "next_action": "<string — AI-generated phrasing of the next recommended action, written around next_action_target_type and next_action_target_id>",

  "next_action_target_type": "<backend-populated: 'scenario' | 'random_call' | 'minigame' | 'none'>",

  "next_action_target_id": "<backend-populated: scenario_id, minigame_id, or null>",

  "reasoning_flags": {
    "impression_challenge_result": "<'correct' | 'acceptable' | 'incorrect' | 'skipped' | null>",
    "missed_critical_item": "<rubric_category_id of the highest-weight failed category, or null>",
    "overdue_random_call": "<scenario_id of overdue item, or null>"
  }
}
```

### 13.2 Field Specifications

**`top_takeaways`** — AI-generated, 2–4 items. Must be grounded in evidence packet gaps for this specific run. Generic condition facts that do not reflect what this student did or missed are not acceptable. The AI must not recycle authored `key_teaching_points` verbatim — takeaways should connect the authored content to the student's specific performance.

**`reflection_prompts`** — AI-generated, 1–2 items. Run-specific prompts for internal processing (no response required from the student). Must vary based on what actually happened in the run. Static templates are not acceptable. Examples of valid prompts:
- "What was your first clue that this patient was deteriorating?"
- "What finding almost led you toward a different diagnosis?"
- "What assessment would you add in the first two minutes if you ran this call again?"

**`next_action`** — AI-generated phrasing. The AI receives `next_action_target_type` and `next_action_target_id` as hard inputs and wraps them in natural coaching language. It must not generate a different target than what the backend provided. If `next_action_target_type` is `"none"`, the AI generates an encouraging forward-looking message with no specific target.

**`next_action_target_type`** — `[backend-populated]`. Set by the deterministic Next Action routing logic (LEARNING_DESIGN.md §2.3) before the LLM call. The AI cannot override this value.

**`next_action_target_id`** — `[backend-populated]`. The specific scenario_id, minigame_id, or null. The AI uses this to name the specific target in `next_action` phrasing.

**`reasoning_flags`** — `[backend-populated]`, optional dict. Contextual flags injected by the backend that the AI can reference in takeaways and coaching prose. These flags do not change scoring — they inform prose framing only. The AI can reference these flags but cannot alter their values.

### 13.3 Backend Population Sequence

The backend populates routing and flag fields before the LLM call:

```
1. Build evidence packet
2. Compute Next Action routing (LEARNING_DESIGN.md §2.3 decision table)
   → sets next_action_target_type, next_action_target_id
   → reads impression_challenge_result from evidence_packet.impression_challenge.result
3. Compute reasoning_flags from evidence packet
   → impression_challenge_result from evidence_packet.impression_challenge.result
   → missed_critical_item from highest-weight failed category
   → overdue_random_call from student history
4. Inject all backend-populated fields into debrief prompt as hard constraints
5. LLM call — AI generates phrasing for next_action, reflection_prompts, top_takeaways
   within the hard constraints
6. Parse structured output; validate top_takeaways and reflection_prompts present
   (ValueError → 503 retry if either is missing or empty)
7. Post-clip hardened subscores; persist to DB
8. Persist BLUF fields (top_takeaways, reflection_prompts, next_action,
   next_action_target_type, next_action_target_id) to session.narrative_data
   so cached re-serves of the debrief return consistent data without re-running the LLM
```

**Debrief response contract — all paths must return the full field set.** Fresh narrative, fresh skip, cached narrative, cached skip, re-debrief, and drill-debrief all return `top_takeaways`, `reflection_prompts`, `next_action*`, `impression_challenge`, and `dmist_primary_impression`. Cached paths read BLUF fields from `session.narrative_data` (persisted at step 8 above). Re-debrief re-runs the LLM and re-persists fresh BLUF fields. Drill-debrief returns `null` for impression fields (drill bypasses DMIST and milestone trigger).

### 13.4 Prompt Instruction for Backend-Populated Fields

The debrief prompt must include explicit instructions:

> `next_action_target_type` and `next_action_target_id` have been pre-populated by the system based on your performance data. You must write `next_action` as coaching language that naturally references the provided target. Do not suggest a different scenario, minigame, or action than what is specified. If `next_action_target_type` is `"none"`, write a brief encouraging statement with no specific recommendation.

> `reasoning_flags` are contextual signals from the backend. You may reference them in `top_takeaways` and coaching prose. You must not alter their values.

---

## 12. Success Criteria

The architecture is correctly implemented when all of the following hold:

**Evidence accuracy:**
- The debrief cannot cite a vital value that does not appear in the session's vitals record
- The PAT feedback correctly states what the student recorded and what the correct impression was — never inverted
- PAT is mentioned only when the scenario's `scene_entry_scoring.pat.enabled == true` — not for all pediatric scenarios, and not inferred from category
- What Was Done Well contains only actions evidenced in the intervention timeline or student transcript — never from submitted DMIST or narrative

**Scoring integrity:**
- Universal Base Standard elements (scene size-up, primary survey, vitals, reassessment, documentation) are evaluated for every scenario without per-scenario authoring; they fire unless explicitly suppressed. Professionalism is qualitatively scored by AI within a hardened ceiling — it is not a universal binary presence check.
- An unsupported DMIST claim (no intervention timeline entry, no transcript evidence) reduces the DMIST score rather than receiving primary source protection
- A system-generated O2 method contradiction (partner ambiguity) is flagged but not charged to the student as a documentation error
- A greeting in the transcript is never described as absent, even if the greeting lacks name or agency
- Clinical Performance is scored from run evidence; submitted documentation does not rescue it for actions not in the timeline or transcript
- All hardened deductions are traceable to a scenario rule and a run record comparison

**Scenario-authored criteria:**
- Scoring criteria are read from the scenario file — the application does not hardcode clinical criteria by scenario type or category
- Grace items from `scoring.by_level` and `scoring.overall_considerations` are surfaced to the LLM as declared facts, not re-derived
- The same scenario run by an EMT-B and a Paramedic under different MCAs produces different required-intervention lists in the evidence packet reflecting the scope-resolved protocol for each

**Scenario type coverage:**
- Transport and disposition feedback is present for all scenario types, with weight appropriate to scenario declaration
- DMIST feedback is present only when `turnover_target == "als"`; pre-arrival report feedback only when `turnover_target == "hospital"`
- Clinical performance feedback is structured by assessment phase; a student missing primary survey actions receives phase-specific coaching, not a generic score reduction

**Educational content:**
- Condition background, key teaching points, and common mistakes in the debrief come from the scenario's authored fields — not generated by the LLM
- The AI connects authored teaching points to evidence packet gaps; it does not generate pathophysiology or treatment facts not present in authored content
- A scenario cannot reach production-ready status without authored `condition_background`, `key_teaching_points`, and `common_mistakes`

**AI qualitative scoring:**
- AI-retained qualitative dimensions (clinical reasoning, documentation adequacy, professionalism tone, assessment sequence) are evaluated against the boundaries defined in §6.2
- Professionalism scoring operates within the hardened cap — the AI cannot award full professionalism when PPE deductions have reduced the ceiling
- Documentation adequacy scoring operates within corroboration ceilings — the AI cannot award full DMIST or narrative credit when the corroboration index has flagged unsupported claims
- Detection heuristics for universal base elements produce no false positives in known-good session transcripts

---

## 13. AI Role in Debrief

This section addresses what the AI continues to do under the target architecture and why those tasks still require AI.

### 13.1 What Changed

Under the current architecture, a single LLM call tries to do three things:
1. Determine what happened (adjudication of facts)
2. Score it (applying clinical criteria)
3. Explain it (coaching the learner)

The target architecture removes role 1 entirely from the LLM (evidence packet handles it) and constrains role 2 to qualitative dimensions only (hardened ceilings constrain the range). The LLM retains role 3 fully, and retains role 2 for dimensions that genuinely require judgment.

### 13.2 What the AI Still Does — and Why It Can't Be Replaced

**Writing all debrief prose.** Every section of the debrief is AI-written. The evidence packet provides pre-computed facts; the AI converts those facts into coaching language a student will learn from. This requires natural language generation, clinical tone calibration, and synthesis across multiple evidence dimensions. This is substantial work that is genuinely AI-appropriate.

**Evaluating documentation quality within hardened ceilings.** The corroboration index tells the AI which claims are unsupported and sets the score ceiling. Within that ceiling, the AI evaluates: Is the DMIST concise or rambling? Is the narrative objective or subjective? Does it capture the clinical picture? Are the CHART sections meaningful or cursory? This is semantic judgment — not keyword detection — and it's one of the most clinically important dimensions of the debrief.

**Evaluating clinical reasoning.** Did the student demonstrate that they understood the presentation? Did they differentiate stridor from wheeze? Did they recognize the need for ALS? Did they make appropriate priority decisions? This requires reading the full transcript holistically and forming a judgment about clinical understanding — the one dimension where AI's natural language comprehension is most valuable and where no deterministic rule can substitute.

**Professionalism tone and communication quality.** Within the hardened professionalism cap, the AI evaluates communication quality, scene management language, patient rapport, and partner coordination. These are genuinely qualitative — a provider can say "I'm going to put some oxygen on you, okay?" and another can say "O2 now" and both might be clinically correct but professionally different. AI reads this naturally.

**Coaching prioritization.** Given all the gaps identified in the evidence packet, which ones should receive the most coaching emphasis for this student at this level? A student who missed the epiglottitis screen and also used the wrong O2 method — which gap is more important to lead with? This requires understanding clinical significance hierarchy and student level, and it's what makes the debrief feel like coaching rather than a checklist.

**Connecting authored teaching points to run gaps.** The AI receives the scenario's authored teaching points and explains which ones are most relevant to what this specific student did and missed. A generic teaching point ("always screen for epiglottitis in pediatric stridor") becomes personalized feedback ("you recognized the croup triad but did not rule out epiglottitis — here is why that screen matters clinically for patients presenting like Lily"). The connection is AI-generated even if the content is authored.

**Scoring qualitative dimensions within ranges.** For hybrid dimensions (DMIST, narrative, clinical performance), the AI assigns a score within the ceiling the evidence packet sets. A DMIST that is complete but vague scores lower than one that is complete and clinically specific. A narrative that covers all CHART elements but uses subjective language scores lower than one that is objective and accurate. These are genuine judgment calls the AI makes within hardened constraints.

### 13.3 What the AI No Longer Does

Under the target architecture, the AI no longer:
- Determines whether a vital value improved or worsened (evidence packet holds the values)
- Decides whether a PAT impression was correct (hardened from scenario + session records)
- Decides whether an intervention was applied (intervention timeline is authoritative)
- Decides whether a DMIST claim is supported by run evidence (corroboration index is authoritative)
- Decides whether a greeting occurred (regex on first message is authoritative)
- Decides whether required interventions were performed (evidence packet contains the required list and the applied list)
- Generates condition background, pathophysiology, or drug rationale (authored scenario fields are authoritative)
- Determines what the student should have done — the scoring spec contains the clinical requirements; the AI explains them
- Infers that an event "probably occurred" from documentation content or stated student intent — this applies inside qualitative tasks too, not just in debrief fact claims. A student's written narrative or chat reasoning does not constitute run evidence regardless of which scoring dimension the AI is currently evaluating.

### 13.4 The Net Effect

The AI does less adjudication and more coaching. Its outputs become more reliable because it is no longer asked to determine facts it cannot reliably determine from prose alone. Its coaching quality improves because it is working from pre-computed, accurate evidence rather than trying to reconstruct the run from a transcript. The debrief remains rich, personal, and clinically informed — the AI's natural language strength is fully engaged, just directed at the right task.
