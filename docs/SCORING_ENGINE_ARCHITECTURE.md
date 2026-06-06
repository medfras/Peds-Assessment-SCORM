# Scoring Engine Architecture

**Project:** RescueTrails EMS Simulator
**Status:** Hybrid live state — deterministic checklist engine active for core clinical/protocol scoring; documentation and professionalism remain AI-assisted in the production pipeline
**Audience:** Developers and AI coding agents implementing the next-generation scoring system
**Depends on:** `DEVELOPMENT_GUIDELINES.md`, `SCENARIO_EVALUATION_ARCHITECTURE.md`, `SCENARIO_DESIGN_EMS.md`, `AI_ARCHITECTURE.md`

This document defines the target architecture for the unified checklist-based scoring engine. It does not supersede `SCENARIO_EVALUATION_ARCHITECTURE.md` wholesale — supersession is element-by-element. `SCENARIO_EVALUATION_ARCHITECTURE.md` remains authoritative for any scoring element that has not yet been explicitly migrated and tested against this design. When a specific component (e.g., a checklist item type, a satisfaction tier, a score arithmetic rule) is implemented and validated, the corresponding section of the current architecture doc is retired and this document becomes the canonical reference for that component. During the current hybrid state, both docs are active: deterministic checklist adjudication is live for core clinical/protocol buckets, while documentation extraction and professionalism review still rely on the focused AI paths described in the current evaluation architecture.

---

## 1. Core Principle

**Code owns adjudicated facts. AI owns explanation and language.**

Every determination that can be made deterministically — what was done, when, whether it was in scope, whether documentation matches the run — is owned by the backend. The AI receives locked results and uses them to generate instructor-like feedback, clinical education, and qualitative review. The AI never decides whether something happened. It explains what the code established, or as a narrow last resort, classifies whether a specific student message satisfies a pre-defined checklist item.

This separation is what enables feedback that reads like a real instructor: because the AI is not spending tokens inferring what happened, it can spend them explaining why it matters clinically — specific, grounded, and direct.

---

## 2. Design Goals

| Goal | How the architecture achieves it |
|---|---|
| **Reliable and consistent** | Score arithmetic is code; identical runs always produce identical scores |
| **Accurate** | Factual determination from structured records, not LLM inference |
| **Adaptable** | Context resolution handles level/MCA/agency variation without scenario re-authoring |
| **Scalable** | Universal base + family templates + scenario-specific deltas; authoring cost is proportional to clinical novelty |
| **Instructor-like feedback** | AI explains locked facts with clinical depth; never hedges about what happened |

---

## 3. Non-Goals

These are explicit architectural exclusions. Implementing them would undermine the reliability guarantees this system is designed to provide.

- **AI does not decide whether care occurred.** If something cannot be confirmed from structured events, deterministic matching, or a constrained Tier 3 classification, it is not credited. The AI does not make this judgment in coaching prose.
- **Checklist items do not capture abstract clinical judgment.** "Recognized severity appropriately" is not a checklist item. It belongs in AI coaching commentary. Items must be observable behaviors.
- **Tier 3 is not a substitute for weak Tier 1/Tier 2 coverage.** If many items regularly resolve at Tier 3, the deterministic layers need expansion — Tier 3 is a last resort for genuinely ambiguous natural language, not a general-purpose parser.
- **`EVALUATE` is a scoring debt marker, not a design pattern.** Items that reach the debrief prompt as `EVALUATE`-tagged (pass/fail to be determined by the LLM from transcript) violate the backend authority rule. Every such item represents a Tier 1 or Tier 2 path that has not yet been built. No new scenarios or critical actions should be authored that would default to `EVALUATE`. The goal is zero `EVALUATE` items in production scoring. See `SAAS_HARDENING_PLAN.md SCORE-02`.
- **Bonus items do not offset required misses.** A student who misses a required critical action cannot compensate for it by completing bonus items.
- **Documentation evidence cannot rescue clinical performance credit.** If an action has no run evidence, the DMIST or narrative cannot back-credit it for clinical performance purposes.

---

## 4. Relationship to Existing Architecture

The current evidence packet model (`SCENARIO_EVALUATION_ARCHITECTURE.md`) is the foundation this architecture builds on. Key continuities:

- The evidence packet becomes the **persisted adjudicated output** of the checklist engine, not just a prompt input.
- The existing `critical_actions`, `required_assessments`, and `required_screens` structures are migrated into the unified checklist schema — their intent is preserved, their implementation is formalized.
- Existing structured event sources (intervention records, session findings, scene_entry, session events) become Tier 1 satisfaction sources.
- The existing keyword/regex matching in `_build_evidence_packet` becomes the Tier 2 foundation.
- The Tier 2 / Tier 3 classifier distinction supersedes the current Tier 2 LLM pre-pass for corroboration.

No current session data is invalidated. Migration is additive.

---

## 5. Phase 0 — Context Resolution

Before any scoring runs, the session context is resolved once and persisted. All subsequent scoring operates against this resolved context.

**Resolution order:**
1. Student licensed provider level
2. Agency level cap → **effective operating level**
3. MCA for this session → **active scope expansions**
4. Agency-specific overrides and SOP flags
5. Scenario context (peds vs adult, ALS co-dispatch, monitoring availability, turnover target, agency SOPs)

**Output:** A persisted effective checklist — the exact set of items that apply to this student, in this agency, under this MCA, for this scenario. Computed at session start. The same scenario produces a different effective checklist for an EMT under one MCA than a paramedic under another, without any scenario re-authoring.

**Scalability guarantee:** Adding a new agency, a new MCA with new scope expansions, or a new provider level requires no changes to existing scenarios. Item conditions handle the filtering. Future domain types (fire/hazmat/law enforcement) define their own context dimensions using the same resolution model.

### 5.2 Base Patient-Care Rubric Families

Before scenario-specific overlays are applied, each session resolves a **base patient-care rubric family** appropriate to the scenario domain.

For EMS scenarios, the base families are:

- **Medical base rubric** — derived from the NREMT EMT `Patient Assessment/Management – Medical (E202)` sheet. The inherited medical base totals **48 clinical-performance points** before scenario-specific overlays, including patient name and patient age/date-of-birth verification.
- **Trauma base rubric** — derived from the NREMT trauma patient-assessment sheet used for EMT/EMR trauma-style assessment flows. The inherited trauma base totals **44 clinical-performance points** before scenario-specific overlays, including patient name and patient age/date-of-birth verification.
- **Cardiac arrest/AED base rubric** — derived from the NREMT cardiac arrest/AED station. Primary arrest scenarios use this as their `base_patient_care_rubric`. Medical or trauma scenarios that later deteriorate into arrest keep their presenting-complaint base rubric and add this family through `additional_patient_care_rubrics`, so both pre-arrest assessment and arrest management are scored.

Combined-presentation scenarios may compose more than one patient-care family. The dominant presenting complaint remains the primary `base_patient_care_rubric`; additional families are declared in `additional_patient_care_rubrics`. Secondary base rubrics suppress duplicate shared assessment items such as PPE, scene safety, demographics, generic ABC assessment, vital signs, and reassessment, while preserving the clinically distinct items from the secondary station.

These base rubrics are not copied literally into every scenario. Instead, the checklist engine resolves:

1. universal cross-scenario items
2. applicable base patient-care items from the resolved rubric family
3. applicable secondary base-rubric items from `additional_patient_care_rubrics`
4. scenario-specific overlays authored in the scenario JSON

The resulting effective checklist is therefore:

`universal base + primary rubric-family applicable items + secondary rubric-family applicable items + scenario-specific overlays`

This distinction matters:

- The **base patient-care rubric** is what makes scoring feel nationally standardized and instructor-like across different calls.
- A **secondary base rubric** is used only when a scenario has an authored combined presentation or state change that makes a second national-registry-style station applicable, such as a medical/trauma call or a medical/trauma call deteriorating into cardiac arrest.
- The **scenario overlay** is what makes a croup call score differently from syncope or anaphylaxis.

### 5.3 Base Rubric Applicability Rule

Base rubric items are **filtered by scenario applicability** before scoring. The engine must not require irrelevant items simply because they appear on the source NREMT sheet.

Examples:

- A respiratory medical call should not require irrelevant body-system exam items from a broader physical assessment form.
- A known-weight pediatric patient should not be penalized for not using a Broselow-style estimation workflow.
- A non-trauma medical call should not inherit trauma-specific body-region exam items.

The architectural intent is: **national-registry-style structure, scenario-specific relevance**.

### 5.1 Domain Expansion Constraints

Before expanding to new scenario families (adult trauma, fire/hazmat, MCI/RTF), the following constraints apply:

**`ItemCategory` Literal extensibility:** `ItemCategory` in `app/checklist.py` is a closed `Literal` type (`clinical_performance | protocols_treatment | scope_adherence | documentation | professionalism`). Adding categories for a new domain (e.g., `incident_command`, `hazmat_operations`) requires a Literal change and a `CURRENT_SCHEMA_VERSION` bump. This is intentional — categories are not dynamic strings. New domains that map naturally to the existing categories require no schema change.

**`legacy_ai_categories` scenario field:** Each scenario JSON declares which categories remain `method="legacy_ai"` via a top-level `legacy_ai_categories` array. All 13 current EMS scenarios carry `["documentation", "professionalism"]`. New-domain scenarios that want all categories deterministic from day one set `legacy_ai_categories: []`. The fallback default matches historical EMS behavior so existing scenarios without the field continue to work unmodified. This field is the mechanism for expanding deterministic coverage per domain without a global flag change.

**MCI / multi-patient:** The current data model is single-session = single-patient. MCI scenarios cannot be authored by stretching this model. Before any MCI scenario work begins, a new session type design is required that addresses: multiple concurrent patient tracks within one session, per-patient triage decisions producing separate item states, and mass-casualty-specific scoring categories. Do not author MCI scenarios until this design exists.

**`scene_entry` PPE path:** The current Tier 1 `scene_entry` source reads a specific dot-path (`ppe.required_complete`) that reflects the current PFD scene_entry data shape. If a new domain uses a different PPE structure in its scene_entry JSONB, new path configs are needed rather than hard-coded paths in matching logic.

### 5.5 NASEMSO Call-Type Rubric Layer

A portable, environment-agnostic scoring rubric layer lives at `app/rubrics/nasemso/`. These files encode nationally standardized scoring expectations for specific EMS call types, independent of training simulator internals.

**Key properties:**
- **Schema-enforced:** `ems_call_type_rubric.schema.json` defines the contract; `tests/test_call_type_rubric_schema.py` validates all rubric files in CI — structural correctness, ID uniqueness, cross-reference integrity, source role consistency, non-empty feedback, and safety item coverage.
- **Environment-agnostic:** rubric files contain no references to training simulator session state, gamification systems, or UI concepts. The same rubric file can score a training session or a real ePCR by resolving concrete source strings from `source_role_map` at deployment time.
- **Source role abstraction:** checklist items reference abstract roles (`ems_measured_vital`, `ems_performed_exam`, `history_obtained`) mapped to concrete source strings per deployment context. In training simulation: `"authored_vitals"`. In QA/QI ePCR review: `"epcr_vital"`, `"monitor_import"`. Same rubric, different source resolution — no re-authoring for QA/QI deployment.

**Overlay architecture:**

```
NASEMSO base rubric
  → state overlay
    → agency overlay
      → scenario overlay
```

Overlay operations: `add_item`, `modify_item`, `suppress_item`, `add_to_item`. Overlay schema is defined at `app/rubrics/nasemso/ems_call_type_overlay.schema.json`. Every op requires `reason` and `protocol_ref`; `suppress_item` additionally requires `approved_by` at the file level. `modify_item` is restricted to `point_value`, `required`, and `applicable_levels` — structural fields (description, evidence_requirements, feedback) can only be changed in the base rubric. State and agency overlay content can now be authored against this schema.

**Authored rubric files:**
- `respiratory_distress_v1.json` — 18 items (17 EMT-applicable), `domain: medical`
- `pediatric_croup_v1.json` — 15 items (14 EMT-applicable, 1 Paramedic-only), `domain: pediatric`
- `hypoglycemia_v1.json` — 16 items (all EMT-applicable), `domain: medical`
- `head_injury_v1.json` — 8 reusable focused head-injury items, `domain: trauma`

**Scenarios with authored `call_type`:**
- `peds_diabetic_emergency_01` → `hypoglycemia`
- `peds_croup_01` → `pediatric_croup`
- `peds_asthma_01` → `respiratory_distress`
- `peds_trauma_07_head_injury` → `head_injury`

`call_type` is validated at scenario load time by `validate_scenario()`: the value must resolve to at least one rubric file in `app/rubrics/nasemso/`. Clinical-category scenarios without `call_type` receive a load-time warning. The validator uses `get_known_call_types()` from `rubric_loader.py` — no hardcoded strings.

**Feature flags:**
- `SHADOW_CALL_TYPE_RUBRIC` (default `true`) — shadow composition always runs; report persisted in `checklist_states['shadow_composition']` with `_diagnostic_only: true`
- `USE_CALL_TYPE_RUBRIC` (default `false`) — activates scored composition; shadow report suppressed; `overlay_audit` (list of overlay mutations applied, empty if none) persisted in `checklist_states['overlay_audit']`

**Denominator behavior on activation:** *Scores may shift because applicable NASEMSO call-type rubric items are now included in the effective checklist; this is an intentional denominator expansion, not a scoring regression.* Enabling `USE_CALL_TYPE_RUBRIC=true` increases the effective checklist size for scenarios with a matching `call_type`. This changes the maximum score (denominator). The change is deterministic: only items with `applicable_levels` including the session's provider level are added. Level-excluded items (e.g., `nebulized_epi_severe` for Paramedic-only) do not appear in the active checklist and do not affect max score. Instructors should expect raw and percentage scores to shift when comparing pre- and post-activation runs. This reflects items that were previously unscored, not a scoring regression. The `call_type_item_count` and `level_excluded_item_count` fields in the composition report document the exact source of the change.

**`requirement_logic: "all"` semantics:** Items with `requirement_logic: "all"` require every sub-requirement to be independently satisfied by Tier 1 structured evidence. A single Tier 2 transcript match cannot substitute. The converter sets `allowed_tiers=[1]` on these items (primary guard) and the adjudicator has a defense-in-depth `_is_all_logic` check that blocks Tier 2 even if `allowed_tiers` is later patched. This applies to all safety-critical dual-evidence items such as `reassess_bgl_loc` (BGL + LOC) and `rr_wob_assessed` (RR + work of breathing).

This layer is distinct from the NREMT-derived base patient-care rubric (§5.2) — that rubric covers generic patient assessment/management structure. The call-type rubric covers condition-specific clinical expectations. Both compose into the effective checklist at session start.

**Relationship to scenario-specific overlays:** Call-type rubric items represent what any competent provider should do for this call type regardless of scenario specifics. Scenario-specific overlays customize point values, add case-specific items (e.g., a specific mechanism of injury, a pre-existing condition that changes management), or suppress inapplicable base items. The authoring rule is: if it belongs on every hypoglycemia or head-injury call, author it in the call-type rubric; if it only belongs on this specific patient presentation, author it in the scenario overlay. Scenario JSON should provide clinical truth and patient-specific findings; reusable focused-exam requirements such as head-injury GCS, pupils, LOC/vomiting history, and head/scalp DCAP-BTLS belong in the call-type rubric.

---

## 6. Unified Checklist Schema

One schema. Every scored item is an instance of it. Internal `subtype` preserves semantic structure without splitting authoring contracts or scoring logic.

### 6.1 Item Subtypes

| Subtype | Covers |
|---|---|
| `scene_entry` | Scene safety, PPE, PAT — evaluated via popup, not transcript |
| `assessment` | Vitals, primary survey elements, specific exams, SpO2, lung sounds |
| `screen` | Condition-specific differential reasoning (epiglottitis, aortic dissection, NAT/abuse screen) |
| `intervention` | Procedures, medications, positioning, environmental actions |
| `reassessment` | Post-intervention rechecks, serial vitals, reassessment timing |
| `transport` | Transport decision, destination communication, pre-arrival notification, handoff |
| `documentation_handoff` | DMIST / turnover report — D/M/I/S/T structure, verbal handoff content |
| `documentation_narrative` | PCR narrative — C/H/A/R/T structure, prose accuracy |
| `professionalism` | Communication quality, patient/family address, consent, self-introduction |

`documentation_handoff` and `documentation_narrative` are distinct subtypes. They use different structural frameworks (D/M/I/S/T vs C/H/A/R/T), draw from different evidence sources, and apply different evaluation rules. Treating them as one subtype would produce awkward scoring logic at scale.

### 6.1.1 Rubric Provenance

Checklist items may originate from four provenance layers:

- **universal_base** — authored centrally; applies across scenarios when context allows
- **base_patient_care_rubric** — inherited from the resolved rubric family (for EMS medical scenarios, this is the E202-derived medical rubric)
- **call_type_rubric** — portable NASEMSO call-type rubric for this call type (e.g., `hypoglycemia_v1.json`); environment-agnostic and QA/QI-portable; source roles resolved from the rubric's `source_role_map` per deployment context; see §5.5
- **scenario_overlay** — authored directly in the scenario JSON to represent case-specific customization not covered by the call-type rubric (specific mechanism, pre-existing conditions, altered point weights)

This provenance exists so the scoring engine and debrief layer can distinguish:

- missed core patient-assessment mechanics (universal_base, base_patient_care_rubric)
- missed nationally standardized condition-specific expectations (call_type_rubric)
- missed scenario-specific clinical expectations (scenario_overlay)
- documentation / professionalism items

### 6.2 Item Fields

```
id                        Stable identifier — never changes once in production use
description               Observable behavior in plain language (see §6.3)
subtype                   One of the subtypes in §6.1
category                  clinical_performance | protocols_treatment | scope_adherence | documentation | professionalism
provenance                universal_base | base_patient_care_rubric | call_type_rubric | scenario_overlay | overlay
point_value               Maximum points this item can contribute
partial_credit_rule       Required if item supports partial state — see §8
required                  required | optional | bonus
applicable_levels         Empty = all levels; otherwise list of effective level keys
requires_mca_expansion    Expansion ID if item only applies under specific MCA scope
agency_applicable         true | false | list of agency IDs
applicable_if             Optional structured applicability filter (complaint/system/domain flags)
timing_constraint         Optional — see §9
allowed_tiers             Explicit list: [1], [1,2], or [1,2,3]
preferred_tier            Which tier should satisfy this item in the normal case
tier3_permitted           Explicit boolean — default false; must be set true for Tier 3 to apply
schema_version            Version of the checklist schema definition at time of authoring (see §6.4)
```

**Category membership is one-to-one.** Every item belongs to exactly one `category`. An item cannot contribute to multiple categories simultaneously. The deduction stacking described in §11 (e.g., a clinical miss that also produces a documentation accuracy deduction) is implemented as two separate items — one in `clinical_performance` and one in `documentation` — not as a single item with dual category membership.

**Protocols/treatment and scope are intentionally separate.** Use `protocols_treatment` for in-scope treatment choices, protocol alignment, contraindicated care, oxygen/medication/positioning choices, and missed indicated interventions. Use `scope_adherence` only for true scope-of-practice issues: out-of-scope attempts, actions outside the student's effective provider level, active refusal of clearly indicated in-scope care because of scope misunderstanding, or MCA scope expansion errors. A scenario may contain both categories; the assessment total sums both deterministic buckets. Do not hide routine treatment quality inside `scope_adherence`.

### 6.3 The Observable Behavior Constraint

Every `description` must describe something externally verifiable — something done, logged, or explicitly stated by the student. Items that require clinical interpretation belong in AI coaching commentary, not in the scored checklist.

**Valid (scorable):**
- "Obtained SpO2 reading"
- "Auscultated lung sounds"
- "Verbalized epiglottitis as a differential consideration"
- "Applied supplemental oxygen within 5 minutes of scene contact"
- "Communicated transport destination to receiving facility"

**Invalid (belongs in AI coaching, not checklist):**
- "Recognized severity appropriately"
- "Demonstrated situational awareness"
- "Showed sound clinical judgment"
- "Understood airway compromise"

This constraint is enforced by schema validation at authoring time, not by convention. Items with descriptions that cannot be mapped to a satisfaction rule do not pass validation.

### 6.4 Versioning and Migration Safety

The `schema_version` field on every item records the version of the checklist schema definition at authoring time. This allows historical sessions to remain auditable against the rules that were active when they ran.

**Policy:**
- Once an item's `id` is in production use, it is permanent. Items are deprecated (`deprecated: true`) but never deleted.
- Changes to `point_value`, timing rules, or satisfaction tiers on an existing item require a version increment. The previous definition is archived; the updated definition retains the same `id` with an incremented `schema_version`. Historical session records reference the version they were adjudicated against.
- The context resolution phase stores the `schema_version` hash of the effective checklist used for this session. Score recalculation for a historical session uses the checklist definitions that were active at session time — not the current definitions.
- The persisted adjudication packet stores the concrete effective checklist definitions used for the session. Historical re-adjudication prefers that stored snapshot over the current base-rubric registry so inherited NREMT rubric updates do not retroactively re-grade prior runs.
- Breaking changes to the schema structure (new required fields, changed field semantics) require a major version bump and a migration script that backfills existing item definitions.

**Version granularity:** These are two distinct versioning mechanisms. `schema_version` on each item tracks that item's individual definition history — it changes when a specific item's rules change. The checklist hash stored at session start is a composite fingerprint derived from all included items' current `schema_version` values; it identifies the exact bundle of rules the session was adjudicated against. Per-item versioning enables fine-grained audit trails; the session-level hash enables efficient reconstruction of any historical rule set without storing full item snapshots per session.

---

## 7. Checklist State Machine

Every item resolves to exactly one state after the satisfaction cascade runs.

| State | Meaning | Scoring consequence |
|---|---|---|
| `satisfied` | Fully evidenced by run data | Full credit per `point_value` |
| `partial` | Partially met per `partial_credit_rule` | Partial credit per rule (see §8) |
| `not_satisfied` | Applicable item; no evidence it was performed; not documented | Deduction or zero per item definition |
| `contradicted` | Documentation claims the item; run evidence directly contradicts it | Documentation accuracy deduction |
| `unsupported_by_run` | Documentation claims the item; no run evidence supports it | Documentation accuracy deduction |
| `not_applicable` | Filtered out by level / MCA / agency context resolution | Excluded from scoring entirely |
| `ambiguous` | Tier 3 extraction result below confidence threshold | Default not credited; logged; surfaced for instructor review |

### 7.1 Critical Distinction: `not_satisfied` vs `unsupported_by_run`

These two states are fundamentally different and must never be conflated.

**`not_satisfied`** — the item was applicable to this session, no evidence exists that it was performed, and the student did not document it. The student simply did not do it. This is a clinical performance gap. Consequence: clinical performance deduction.

**`unsupported_by_run`** — the student documented the item in their DMIST or narrative, but no run evidence supports the claim. The student documented care they did not perform. This is a documentation integrity failure. Consequence: documentation accuracy deduction, separate from and additive to any clinical performance consequence.

In feedback terms: "you didn't screen for epiglottitis" is `not_satisfied`. "You documented that you screened for epiglottitis but there is no evidence in the run that you did" is `unsupported_by_run`. These are different problems requiring different coaching.

### 7.2 `ambiguous` Is an Exception Path

`ambiguous` exists to handle genuine uncertainty — not as a comfortable middle ground. Every `ambiguous` result is logged with its full Tier 3 artifact. If a scenario regularly produces `ambiguous` for the same item, that signals Tier 2 matching needs expansion. `ambiguous` is a coverage gap indicator, not a steady state.

Default behavior when `ambiguous`: **not credited**. The instructor review queue shows all `ambiguous` items so an instructor can override if warranted.

**Ambiguity frequency monitoring:** The system tracks `ambiguous` rates per item, per scenario family, and in aggregate. Items with persistently high `ambiguous` rates are flagged for Tier 2 coverage expansion. An elevated aggregate `ambiguous` rate is a health signal that the deterministic layers need attention — not an acceptable operating condition. See §20 for observability metrics.

---

## 8. Partial-Credit Mechanics

`partial` is valid only when an item explicitly defines one of three bounded models. Items without one of these models are binary (satisfied / not_satisfied) and do not support partial credit.

**Model 1 — Subcriteria:** The item defines named sub-elements, each worth a fraction of `point_value`. Credit is proportional to subcriteria satisfied. Example: a SAMPLE history item has six subcriteria; satisfying four of six yields `round(4/6 × point_value)` or a defined stepped value.

**Model 2 — Fixed partial score:** A single `partial_score` value applies whenever the item is partially met, regardless of degree. Example: reassessment performed but outside the required time window — always worth 1 of 3 points.

**Model 3 — Percentage bands:** Subcriteria percentage thresholds map to defined scores. Example: ≥75% → full credit, 40–74% → defined partial score, <40% → not_satisfied.

The three-model constraint prevents `partial` from becoming a vague middle ground that reintroduces scoring subjectivity.

---

## 9. Sequence-Aware Items

Some items matter partly because of when they occurred relative to other events. The schema supports timing and ordering constraints without special-case code per scenario.

```
timing_constraint:
  type:                    within_minutes | before_item | after_item | ordered_set
  value:                   N  (for within_minutes — minutes from scene contact)
  reference_item_id:       "..."  (for before_item / after_item)
  items:                   [...]  (for ordered_set — must be satisfied in this order)
  violation_consequence:   partial | deduction_override | informational
```

**Violation consequence selection guide:**
- `partial` — the item was still meaningfully completed; timing was late but the care occurred. Use when "late but done" has educational value and partial credit is appropriate.
- `deduction_override` — the timing violation is severe enough that the item's normal point calculation is replaced by a specific deduction. Use when late is nearly as harmful as never (e.g., scene safety checked after patient contact — the protective window has already passed).
- `informational` — the ordering is notable for coaching but does not change the score. Use for protocol preference violations that don't rise to clinical consequence.

**Examples:**
- `oxygen_applied` with `within_minutes: 5` — resolves `satisfied` if applied; resolves `partial` (per partial_credit_rule) if applied after 5 minutes
- `reassess_after_intervention` with `after_item: oxygen_applied` — only credited if reassessment timestamp follows intervention timestamp
- `scene_safety` with `before_item: patient_contact` — informational flag (or deduction_override) if patient contact record precedes scene safety record

Timing evaluation runs against timestamped backend records. No AI judgment involved.

**Implementation status (2026-05-03):** `before_item`, `after_item`, and `ordered_set` constraints are evaluated by the deterministic adjudicator using item evidence timestamps. `within_minutes` remains gated on scene-contact elapsed-time normalization and should not be used as score-bearing until that runtime anchor is available.

**Clock normalization requirement:** Sequence evaluation normalizes all temporal events to elapsed seconds from `session.start_time` before comparing. Tier 1 source timestamps (database records), Tier 2 source timestamps (chat message `created_at`), and session event timestamps all use the same UTC wall-clock, but the elapsed-time normalization ensures comparison is consistent even when there are minor clock skew or storage latency differences. Any event without a recoverable timestamp is excluded from sequence evaluation and treated as unordered — it can satisfy the item's content requirement but does not satisfy a timing constraint.

**Causal ordering for near-simultaneous events:** Wall-clock timestamps cannot reliably order events that arrive within the same second or that invert due to async processing (e.g., a chat message reaching the server slightly before a UI button POST that the user intended first). For `before_item` and `after_item` constraints, when two events have timestamps within a configurable jitter window (default: 2 seconds), the system falls back to the monotonic `SessionEvent` primary key as the causal ordering signal. Sequence IDs are assigned at DB insert time and reflect the actual order server-side processing received the events, providing a more reliable causal ordering than wall-clock alone for close events.

---

## 10. The Satisfaction Cascade

Each item's `allowed_tiers` declares which tiers apply. The cascade stops at the first positive match.

### Tier 1 — Structured Backend Events

**Sources:** intervention records, scene_entry popup data, session findings logged via exam/vitals UI, session events, challenge completions, transport records, handoff records.

No parsing. No inference. If an intervention is in the intervention table, it happened. Highest-confidence source, zero maintenance cost.

Maximizing Tier 1 coverage is the highest-leverage investment in the entire architecture. Every item that can be satisfied from a structured event should be — before investing in lower tiers.

`TierOneMatchSpec.source = "session_event"` matches a backend `SessionEvent` by required `event_type` and optional `event_key_pattern`. This is the preferred path for backend-confirmed actions that are not interventions, such as successful medical-control contact.

**Source eligibility filtering:** When a `finding` or `post_intervention_finding` match spec includes `eligible_source_roles`, the scoring engine resolves those abstract roles to concrete source strings using the session's active `source_role_map` (from the call-type rubric). A `SessionFinding` record satisfies the match only if its `source` field appears in the resolved concrete source set. `SessionFinding` records with `source = NULL` (legacy / untyped) always pass eligibility — backward compatibility is preserved for sessions predating source typing. This mechanism enforces clinically important distinctions at the rubric level: a BGL item requiring `ems_measured_vital` is not satisfied by a `history_obtained` finding reporting a caregiver-stated CGM value, even when the finding key matches. The `eligible_sources` list on `TierOneMatchSpec` carries the already-resolved concrete source strings for the active deployment context; the `eligible_source_roles` list in the rubric file is the portable form resolved at session start.

**Challenge-domain source gating:** Interactive challenge completions (lung sound auscultation, GCS calculator, glucometer check) are the highest-integrity evidence source for the clinical actions they assess. Rubric items that require these interactions are authored with `allowed_tiers: [1]` and an `eligible_source_roles` entry that maps to a challenge-specific concrete source. This enforces a three-layer boundary:

1. **Routing layer** — frontend routing guards (`_userExplicitlyRequestedLungSounds`, `_userRequestedGcs`) intercept the relevant requests and open the challenge modal before any AI response is generated
2. **AI prompt layer** — when a challenge is enabled for the scenario, the AI system prompt instructs Alex to emit the finding tag but suppress prose reveals of the finding (no "I hear wheezing" or "GCS is 9" in response text)
3. **Scoring layer** — rubric items requiring challenge completion use a source role that resolves only to the challenge completion source; AI-tagged findings and caregiver/history-reported findings cannot satisfy the item

| Abstract source role | Concrete source (training) | Challenge |
|---|---|---|
| `challenge_performed_exam` | `lung_sound_challenge` | Lung sound auscultation challenge |
| `challenge_calculated_gcs` | `gcs_modal` | GCS component calculator modal |
| `challenge_measured_bgl` | `glucometer_check` | Glucometer/BGL check flow |

These roles intentionally exclude `ai_roleplay_tag`, `authored_vitals`, `history_obtained`, and `caregiver_reported` — the sources through which the same finding might arrive if no challenge gate existed. The Tier 2 fallback path is blocked for these items (`allowed_tiers: [1]` only), so a student who obtains the information conversationally receives no scoring credit; only the structured challenge interaction earns the point.

**Evidence reference stored:**
```json
{
  "tier": 1,
  "source_type": "intervention_record | session_finding | scene_entry | session_event | transport_record",
  "source_id": "<database record id>",
  "timestamp": "<ISO timestamp>"
}
```

### Tier 2 — Deterministic Transcript and Findings Matching

**Sources:** student chat messages and session findings text.

Regex or keyword rules applied to student-generated text. Rules are authored per item — typically a curated list of natural language variants the student might use. Conservative by design: a match requires the intent to be clearly expressed, not just a keyword present in context. Negative test cases are as important as positive ones.

**Coverage requirement:** Every Tier 2 rule requires test coverage before deployment. Positive samples (phrasings that should match) and negative samples (phrasings that should not) are authored alongside the item. The coverage harness runs in CI. Adding an item with `allowed_tiers` including tier 2 but without test coverage fails validation.

**Known reliability limitation:** Tier 2 transcript matching is evidence that a matching string appeared in the chat — not independent evidence that a clinical action occurred. A student who types the right words without performing the action can satisfy a Tier 2 item. A student who performs the action without using the expected phrasing will miss credit. This is a structural limitation of text-based evidence, not a bug in the regex. The mitigation path is to expand Tier 1 coverage: every assessment action that matters enough to score should have a structured UI interaction that emits a `SessionEvent` backend record, creating an authoritative Tier 1 path. Tier 2 then becomes a corroborating fallback rather than the primary evidence source. This expansion is a prerequisite for QA/QI use — see `docs/QAQI_READINESS.md`.

**Source eligibility by subtype:** Not all subtypes may use all Tier 2 sources.

| Source type | Eligible subtypes |
|---|---|
| `student_transcript` | All subtypes |
| `session_finding_text` | `assessment`, `reassessment` |
| `submitted_document_text` | `documentation_handoff`, `documentation_narrative` only |

**`submitted_document_text` does not satisfy `screen` items in this simulator.** In a QA/QI context where DMIST is written by a student without AI assistance, a named differential in the DMIST is unambiguous evidence of reasoning. In the training simulator context, the DMIST may contain LLM-generated text or text the student did not personally author. Crediting a clinical reasoning item from DMIST text would allow AI-generated documentation to award clinical performance credit — the exact false-credit risk this architecture is designed to prevent. The correct evidence for `screen` items is the live student transcript (Tier 2) or a structured Tier 1 event/finding. Documentation may separately score well for naming the differential in the `documentation_handoff` or `documentation_narrative` categories, but that is a documentation quality credit, not a clinical performance credit for the reasoning itself.

**`session_finding_text` does not satisfy `screen` items either.** Session finding records include AI-generated clinical notes (type `clinical_note`) that the student did not author. Allowing finding text to satisfy a `screen` item would let a system-generated note back-credit a clinical reasoning action — the same false-credit risk as DMIST. `screen` items require live student transcript (Tier 2) or a structured Tier 1 event. Finding text may satisfy `assessment` and `reassessment` subtypes because those are value-bearing measurement findings (e.g., blood glucose level, SpO₂ reading) that the system records as a direct consequence of a student-initiated action.

`intervention`, `transport`, `scene_entry`, and `professionalism` subtypes may never use `submitted_document_text` as Tier 2 evidence. Documentation of an action is not evidence the action occurred.

**Evidence reference stored:**
```json
{
  "tier": 2,
  "source_type": "student_transcript | session_finding_text | submitted_document_text",
  "document_type": "<dmist | narrative — only when source_type is submitted_document_text>",
  "matched_text": "<exact matched text span>",
  "match_rule": "<rule id that matched>",
  "message_timestamp": "<ISO timestamp if available>"
}
```

### Tier 3 — Constrained AI Extraction

Used only for items where `tier3_permitted: true` is explicitly set. High-stakes clinical action items default to `tier3_permitted: false`.

**Scope is strictly bounded:** classify whether a specific student message satisfies a specific pre-defined checklist item. The model answers one binary question: "Does this text satisfy item X?" It is not asked what happened, not asked to assess quality, not asked to infer intent beyond the item definition. Tier 3 does not create new facts — it only evaluates whether a pre-existing item is satisfied by existing text evidence.

**Tier 3 artifact (always persisted):**
```json
{
  "tier": 3,
  "item_id": "<checklist item id>",
  "matched_text": "<exact student text span evaluated>",
  "matched": true,
  "confidence": 0.87,
  "rationale": "Student explicitly mentions ruling out epiglottitis by name.",
  "needs_review": false
}
```

**Confidence derivation:** The `confidence` value must not be a self-reported number in the model's output. LLMs systemically overstate self-reported confidence, making a model-generated `0.87` meaningless as a threshold signal. Instead, confidence is derived from the model's token-level log probabilities for the binary classification token (`True` / `False`). The log probability of the `True` token, converted to a linear probability, is the mathematically grounded confidence score. This requires using the API's `logprobs` feature rather than prompting the model to emit a number. Tier 3 prompts must be structured to elicit a single classifying token — not a JSON blob that includes a confidence field authored by the model.

**Model capability gate for Tier 3:** Logprob availability is not uniform across Groq-hosted models — it varies by model version and API configuration. Tier 3 is a deployment-time eligibility decision, not an item-level one:
- A model may only be used for Tier 3 adjudication if it has been verified to return usable per-token logprobs for single-token binary responses in the Groq API
- Verification runs as part of deployment validation: a test classification prompt is sent, and the response is checked for a valid `logprobs` field on the target token
- Models that pass verification are listed in a `tier3_eligible_models` configuration list; models not on the list cannot be used for Tier 3 regardless of item configuration
- If the configured Tier 3 model is ineligible or verification fails at startup, all items with `tier3_permitted: true` default to `ambiguous` (not `not_satisfied`) until a verified model is configured — the system degrades gracefully rather than silently disabling a scoring path

`needs_review: true` when confidence falls below the configured threshold. The item resolves to `ambiguous` and appears in the instructor review queue. Below-threshold results are never automatically credited.

**Threshold configuration:** The confidence threshold is defined at three levels, applied in priority order:
1. **Per-item override** — `tier3_confidence_threshold: 0.85` on the checklist item. Use when a specific item has known calibration characteristics.
2. **Per-subtype default** — each subtype (`screen`, `assessment`, etc.) defines a default threshold. High-stakes subtypes use higher defaults.
3. **Global system default** — a single configured value applied when no per-item or per-subtype value is set. Starting value: `0.80`.

This layered design allows calibration of individual high-variance items without changing global behavior, and allows subtype-level tuning as confidence data accumulates from the gold-standard evaluation set.

### Per-Item Tier Declarations

The cascade is global in structure but each item explicitly declares which tiers are permitted. This prevents the fallback path from becoming permissive by default.

```
allowed_tiers: [1]          # Tier 1 only — structured event required
allowed_tiers: [1, 2]       # Structured event or deterministic match
allowed_tiers: [1, 2, 3]    # All tiers; Tier 3 as last resort
tier3_permitted: false       # Explicit — even if allowed_tiers includes 3
tier1_match:
  source: session_event
  event_type: medical_control_contact
  event_key_pattern: medical_control_contacted
```

High-stakes items (scene safety, critical interventions, transport decision) default to `[1]` or `[1, 2]`. Abstract clinical screening items that may be expressed in varied natural language are candidates for `[1, 2, 3]` with `tier3_permitted: true`.

---

## 11. Score Arithmetic Policy

Score computation is code. No AI involvement.

### 11.0 Score Families

For EMS scenarios, score reporting should distinguish between:

- **Base patient-care score** — the scenario-applicable NREMT-derived patient assessment/management items (48-point medical base or 42-point trauma base)
- **Scenario-specific clinical overlay score** — condition-specific expectations beyond the generic patient assessment scaffold
- **Documentation score** — DMIST and narrative quality/accuracy
- **Professionalism score** — communication / bedside manner

The key policy rule is:

- **Pass / on-track status must be determined from base patient care plus required clinical overlays, not from documentation bonus.**

Documentation quality remains valuable and visible, but it must not visually or mathematically disguise a failing core patient-care performance.

### Assessment Status Bands

Status labels are based on the normalized assessment percentage, using the active engine-computed denominator from `score_snapshot` / `_maxes`. Do not compare raw points directly because effective denominators change as base rubrics, call-type rubrics, and overlays are composed.

| Normalized assessment % | Student-facing label | Meaning |
|---:|---|---|
| 92-100 | Excellent Rep | High-quality rep with only minor or no meaningful gaps |
| 85-91 | Strong Rep | Solid clinical performance with some refinement areas |
| 70-84 | On Track | Passing assessment performance, but several important gaps may remain |
| 60-69 | Needs Work | Below passing; learner completed parts of the call but needs targeted remediation |
| < 60 | Growth Opportunity | Foundational gaps; replay or scaffolded practice recommended |

Critical misses override the percentage label and display as `Critical Misses`.

### Arithmetic model

Scoring is **additive from zero.** Each session starts at 0 points in every category. Satisfied items add their `point_value`; partial items add the partial-credit amount per §8; required items that are `not_satisfied` subtract a per-item deduction (defined on the item, or a category default); `contradicted` and `unsupported_by_run` items subtract their documentation accuracy deduction. Every category total is then bounded to `[0, category_max]`. There is no "start at full credit and deduct" mode. This ensures that unusual or bonus-heavy sessions cannot accidentally invert expected scoring behavior, and that the score at any intermediate point in adjudication is always the earned total, not a remainder.

### Category score computation
Each category score is the sum of satisfied and partial credit for items in that category, minus deductions for `not_satisfied` required items, minus deductions for `contradicted` and `unsupported_by_run` documentation items. Category scores are bounded: minimum 0, maximum computed from the effective checklist category total. EMS clinical-performance maximums are dynamic because the inherited NREMT base (48 medical / 42 trauma) is combined with scenario-specific clinical overlays.

### Deduction stacking
Deductions stack across categories for the same underlying clinical miss when the miss has distinct consequences in each category:

- A student who did not perform care (`not_satisfied`) **and** documented performing it (`unsupported_by_run`) receives **both** a clinical performance deduction and a documentation accuracy deduction. These are different failures: one is a care gap, one is a documentation integrity failure.
- A student who performed care incorrectly (`contradicted`) receives a documentation accuracy deduction only — the care was performed, but documented inaccurately.

Stacking is intentional: it reflects that falsifying documentation of care not rendered is worse than simply not rendering it.

### Bonus items
Bonus items (`required: bonus`) add to the category score but the category total cannot exceed its defined maximum. Bonus items reward exceptional care but do not offset required misses. A student who misses a required critical action cannot compensate for it by completing bonus items.

### Scope adherence
Scope deductions apply only to: out-of-scope interventions attempted, or active refusal of clearly indicated in-scope care. Missed in-scope opportunities that were never attempted are clinical performance gaps, not scope gaps. A student who missed an intervention but never went out of scope should score near-full on scope adherence.

---

## 12. Evidence Packet — Persisted Adjudicated Record

The evidence packet is the session's adjudicated truth — a persisted record, not a prompt convenience object.

### Contents
- Resolved effective checklist with context resolution inputs documented
- Each item's final state, source evidence reference, and tier used
- Tier 3 artifacts where applicable
- Computed scores per category with itemized deduction trail
- Timing violation records
- Instructor override log (when applicable)

### Lifecycle
1. Context resolution → effective checklist computed and persisted
2. Checklist engine runs → each item assigned state with evidence reference
3. Score arithmetic runs → category scores computed from adjudicated states
4. Evidence packet persisted on the session
5. AI debrief call receives locked packet as read-only input
6. AI generates coaching and educational content from packet contents — does not modify it

### Instructor Override
An instructor can change an item's state (e.g., `ambiguous` → `satisfied` with a note), trigger score recalculation, and log a rationale. The original adjudication is preserved alongside the override. This gives instructors a structured correction path without bypassing the system or losing the audit trail. Override history is available for QA review.

**Dual-state resolution for documentation items:** When an instructor overrides an `unsupported_by_run` or `contradicted` item, the override UI must force explicit resolution of two distinct questions — not just a single state change:
1. **Clinical state** — "Did the student actually perform this care?" (`satisfied` / `not_satisfied`)
2. **Documentation state** — "Is the documentation being forgiven?" (`documentation_forgiven` / `documentation_deduction_upheld`)

These are separate determinations. An instructor may conclude the student did perform the care but the system missed the evidence (clinical `satisfied`, documentation `forgiven`) — or that the student didn't perform it but the documentation error is being excused for training context (clinical `not_satisfied`, documentation `forgiven`). Collapsing these into a single state change would produce incorrect scoring regardless of which state is chosen. The override record stores both resolutions and the rationale.

### Override and Debrief Immutability

The AI debrief text is generated once from the locked evidence packet and is not automatically regenerated when an instructor overrides an item. This creates a potential dissonance: if an instructor overrides a `not_satisfied` item to `satisfied`, the score increases but the AI coaching text still contains a gap explanation for an issue the instructor just resolved.

The defined policy:

**Phase 6 (initial):** Debrief text remains immutable. When an instructor override changes the score, an **Instructor Correction block** is appended to the debrief UI — visible to the student, clearly attributed, distinct from the AI-generated content:

> *Instructor [Name] adjusted adjudication for [item label]. Reason: [rationale]. This overrides the system evaluation for this item.*

The AI coaching text is not edited. The student sees both the original coaching and the instructor's explicit correction. This is intentionally transparent — the instructor's reasoning is on the record, not silently absorbed into the score.

**Phase 7+ (optional enhancement):** A `POST /api/sessions/{id}/re-debrief` endpoint, manually triggered by an instructor, regenerates the AI coaching section for overridden items only, using the updated evidence packet. Full regeneration is rate-limited and logged. It is never automatic — an instructor must deliberately decide to regenerate. Original coaching and the override rationale are preserved in the audit trail even after regeneration.

This policy prevents silent score-coaching dissonance while keeping debrief generation costs predictable.

### Minimum Data Model

The following records must exist before adjudication runs (session start):

| Record | Contents |
|---|---|
| Effective context snapshot | Student level, agency ID, MCA ID, scenario ID — the inputs to context resolution |
| Effective checklist | The filtered item set for this session, with `schema_version` hash of all included definitions |
| Effective checklist snapshot | The exact checklist item definitions used for this adjudication, persisted so historical sessions remain tied to the rubric bundle they originally ran against |

After adjudication completes, the following records must be persisted before the AI debrief call is made:

| Record | Contents |
|---|---|
| Item state records | Per item: `id`, final state, tier used, adjudication timestamp |
| Evidence references | Per item: structured source reference as defined in §10 |
| Score snapshot | Per-category: earned sum, deduction sum, bounded total, and per-item contributions — stored separately so the UI can display the breakdown, not just the final number |
| Critical failure status | Structured station-fail / safety-fail flag when a configured hard-fail checklist item is missed |
| Override records | Per instructor override: original state, new state, rationale, instructor ID, timestamp |

The AI debrief call receives this persisted packet as a read-only input. If any required records are absent when the debrief call is attempted, the call fails loudly rather than proceeding with incomplete data. Silent degradation on missing adjudication data is not acceptable.

---

## 13. AI Role — Generating Instructor-Like Feedback

### Why the architecture enables authentic instructor tone

A real instructor knows exactly what happened before giving feedback. With the evidence packet, the AI also knows exactly what happened — it does not need to hedge ("it appears you may have...") or infer from context. It can be specific: "You applied oxygen at +3 minutes and did not reassess until +8 minutes — on a pediatric respiratory patient that 5-minute gap matters because subglottic edema can progress rapidly and the patient's work-of-breathing is your most sensitive indicator." That level of specificity, grounded in verified timestamped facts, is what sounds like a real instructor.

### What AI does (current state)

- Generates concise coaching prose explaining the highest-yield gaps and strengths, using evidence packet facts as ground truth
- Writes "what went well" / "what could be better" as top-3-to-5 coaching synthesis from adjudicated checklist items — never inferred from documentation
- Keeps deep clinical education (pathophysiology, protocol rationale, treatment mechanisms, common errors) in a collapsible Learn More reference rather than the main debrief body
- Evaluates professionalism from student transcript, constrained by hardened sub-inputs (see §14)
- Extracts structured claims from DMIST/narrative for documentation scoring comparison
- Generates the full debrief — the educational, instructor-voiced output the student receives

### Target state (Phase 8) — Deterministic Section Rendering

The current AI role is broader than the target architecture requires. The LLM still writes the scored sections (Clinical Performance, Protocols & Treatment, DMIST, Narrative), which means it can mis-bucket a gap, over-credit an action, or explain a score using a rationale that doesn't match the actual adjudication. This is the root cause of all category-boundary leaks and score explanation drift.

**Target AI scope — coaching and education only:**

| Debrief section | Target author | Source |
|---|---|---|
| What Went Well | Deterministic renderer | Top satisfied, clinically meaningful item list with administrative defaults filtered out |
| What Could Be Better | Deterministic renderer | Top missed/partial item list with one-sentence clinical rationale, capped to prevent rubric dumps |
| Protocols & Treatments | Deterministic renderer | Relevant protocol/treatment checklist states only; reference-line format, no explanatory essay |
| Handoff & Communication | Hybrid: verdict deterministic, prose LLM-assisted | DMIST score/corroboration facts + submitted text; professionalism cap + transcript; narrative score/corroboration facts |
| Case Study | LLM | Curated facts: scenario context, student-obtained findings/vitals, interventions applied; no fabricated values |
| Learn More | Deterministic/reference renderer | Authored condition background, teaching points, and common errors in a collapsible reference |
| Key Takeaways | LLM | Constrained input: top missed items from adjudication |
| Reflection Prompts | LLM | Constrained input: most significant gaps |
| Next Action | Deterministic routing | Miss patterns, calibration data |

**Why this is stable at scale:** When the scored sections are rendered from adjudicated facts + authored metadata, adding 100 scenarios means adding rubric metadata (`done_feedback`, `missed_feedback`, `clinical_rationale`, `common_error`) — not adding prompt exceptions or regex sanitizers. The boundary between scoring and coaching is structural, not instructional.

**Prerequisite — per-item feedback metadata:** Each checklist item must carry reusable authored fields:
```json
{
  "done_feedback": "Patient positioned upright with parent — this is first-line management for croup.",
  "missed_feedback": "Upright positioning with the parent was not documented. Separation and supine positioning worsen stridor by increasing agitation and reducing upper airway caliber.",
  "clinical_rationale": "Agitation increases oxygen demand and laryngospasm; parent hold and calm environment are therapeutic interventions, not just comfort measures.",
  "common_error": "Laying the infant flat for assessment — this triggers crying and worsens stridor acutely."
}
```

**Migration path:** Incremental by category. Clinical Performance and Protocols & Treatment are the first targets because they are fully adjudicated by the checklist engine and have the highest mis-bucketing risk. DMIST and Narrative remain hybrid until structured DMIST entry replaces free-text submission (see `docs/QAQI_READINESS.md`). The LLM debrief call shrinks each phase; it is not removed all at once.

**Documentation claim extraction failure policy:** If AI-assisted extraction of DMIST or narrative claims fails (API error, timeout, structurally unparseable output), the behavior is **fail closed**: documentation accuracy items for that document type default to a `documentation_review_incomplete` state. This state does not credit documentation accuracy items, does not apply documentation accuracy deductions, and surfaces a flag for instructor review. It does not block debrief generation — the rest of the scoring and coaching proceeds normally. The student is notified that documentation review is pending instructor completion. This prevents both false credits (AI hallucinating a clean documentation review) and false deductions (penalizing the student for a system extraction failure).

**Partial extraction completeness check (Groq fast-model concern):** Outright failure is not the only risk. Groq-hosted fast models can return syntactically valid JSON that is structurally complete but has silently low recall — missing claims from sections that were present in the submitted document. Partial extraction that passes silently is worse than outright failure because it produces documentation deductions based on an incomplete evidence set. Extraction output must pass a completeness check before being accepted:
- For DMIST: all five sections (D/M/I/S/T) that are present in the submitted text must have at least one extracted claim
- For narrative: all sections in the expected structure template that have corresponding text must be represented
- If the completeness check fails, the extraction result is discarded and the document type is downgraded to `documentation_review_incomplete` — not silently scored on partial claims

This check is code, not AI. The completeness threshold is authoring-time configurable per document type.

**Arithmetic rule for `documentation_review_incomplete`:** Because scoring is additive from zero, withholding documentation credits without applying deductions produces a 0 for that category — which penalizes the student for a backend failure. The correct behavior is a **dynamic denominator**: when any documentation category items are in `documentation_review_incomplete` state, that category's maximum is excluded from the session's total possible score until the review is completed by an instructor. The session is scored and displayed as "X / Y pts (documentation review pending)" where Y excludes the documentation category maximum. This is neither a penalty nor an unearned credit — the category is simply deferred until it can be evaluated honestly.

### What AI does not do

- Decide whether a clinical action occurred
- Modify or re-adjudicate any item in the evidence packet
- Infer care from documentation content ("the narrative mentions X, so they probably did X")
- Source feedback claims from system-generated partner confirmations, AI roleplay responses, or dispatch messages
- Assign category score numbers (they arrive locked in the packet)
- Re-open factual questions the packet has already answered

### AI Task Separation (Groq operational requirement)

The three AI responsibilities listed above are **separate API calls with separate prompts.** They are never bundled into a single call. This is an operational requirement, not a stylistic preference — Groq-hosted fast models produce more consistent output when each call has a single, narrow objective.

| Call | Purpose | Output contract |
|---|---|---|
| `documentation_extraction` | Extract structured claims from a submitted DMIST or narrative | Schema-validated JSON (D/M/I/S/T or C/H/A/R/T fields); fails closed if output doesn't parse |
| `professionalism_review` | Evaluate communication quality against hardened sub-inputs | Structured assessment with hardened-input constraints enforced before calling |
| `debrief_generation` | Generate instructor-voiced coaching from the locked evidence packet | Free-form prose; receives facts, never asked to derive them |

**The debrief prompt must never be asked to both extract facts and coach in the same pass.** Extraction and coaching are distinct cognitive tasks — bundling them in one prompt produces outputs where the model infers facts it should only be explaining, which is the exact failure mode this architecture is designed to prevent.

### One-directional fact flow

The one-directional fact flow is architectural, not instructional. The AI receives the packet after scoring is complete. It cannot reopen questions the packet has answered. This is enforced by call sequence — not by prompt rules that the model could drift from.

### Feedback quality standards

"Instructor-like" is a product standard, not just a prompt goal. Debrief output must consistently be:

- **Specific** — cites actual evidence from the run, not generic protocol recitation
- **Evidence-grounded** — every gap claim is traceable to a checklist item state in the packet
- **Clinically explanatory** — explains why each gap matters, not just that it was missed
- **Proportionate** — major gaps receive proportionate coaching depth; minor gaps are noted briefly
- **Not repetitive** — each gap is addressed once; the same point is not made across multiple sections
- **Not vague** — avoids softening language ("you may want to consider...") for items the packet marked as gaps
- **Not punitive** — tone is coaching, not prosecutorial; feedback on what to do better, not shame for what was missed

Debrief quality should be evaluated periodically against these standards (see §20 Calibration). Prompt design, evidence packet structure, and AI model selection are all levers for maintaining this standard.

### Learner-level tone adaptation

The evidence packet includes the student's effective operating level (from context resolution). The AI coaching layer should adapt tone and teaching depth accordingly:

- **Newer providers (EMT/EMR):** emphasize foundational reasoning, explain clinical significance from first principles, use accessible language
- **Intermediate providers (AEMT):** assume foundational knowledge, focus on decision points and protocol rationale
- **Advanced providers (Paramedic):** peer-level clinical discussion, focus on nuance, differential reasoning, and pharmacology depth

This is a coaching quality standard, not a scoring standard. The same checklist items apply at all levels within the effective scope — only the depth and framing of the explanation adapts.

---

## 14. Professionalism — Hardened Sub-Inputs

Professionalism remains primarily AI-evaluated because it requires interpretation of language quality, tone, and communication approach. However, certain observable facts are detected by code and fed to the AI as constraints, preventing it from contradicting things the backend has already established.

**Hardened sub-inputs fed to the AI alongside the transcript:**

| Input | Detected by |
|---|---|
| `greeting_detected: true/false` | Regex/keyword on opening messages |
| `agency_intro_detected: true/false` | Regex/keyword on opening messages |
| `patient_name_used: true/false` | Name reference detection in transcript |
| `explanation_phrases_detected: true/false` | Consent/explanation language patterns |
| `family_addressed: true/false` | Family address detection (peds scenarios) |
| `ppe_cap: N/10` | From scene_entry scoring — hard ceiling on professionalism score |

If `greeting_detected: true`, the AI cannot say the student failed to introduce themselves. The AI's qualitative role is to assess the quality and appropriateness of communication within the bounds these facts establish — not to re-decide facts the code already determined.

**Target direction — behavioral rubric for professionalism:** The current hardened sub-inputs cover the most binary observable behaviors (greeting present/absent, PPE ceiling). The full professionalism evaluation remains an LLM holistic assessment, which is inherently variable and difficult to audit. The target direction is to expand the hardened sub-input set to cover all observable professionalism behaviors as checklist items, so the LLM's role narrows to explaining coaching text within a framework that code has already scored. Candidate items for Tier 1 or Tier 2 expansion:

| Behavior | Target path |
|---|---|
| Patient or guardian consent obtained | Tier 2 — transcript keyword |
| Age/weight documented for pediatric patients | Tier 1 — session finding or DMIST record |
| Transport destination communicated to patient/family | Tier 2 — transcript keyword |
| Patient addressed by name (after it is known) | Tier 1 — existing `patient_name_used` detection → promote to checklist item |
| Scene management language during handoff | Tier 2 — transcript keyword near DMIST submission |

This expansion is a Phase 6+ improvement. Until then, the AI holistic review remains the scoring mechanism, bounded by the hardened sub-inputs above. For QA/QI use, all professionalism items should be Tier 1 or Tier 2 before scores are used in clinical review contexts. See `docs/QAQI_READINESS.md`.

---

## 15. Scenario Authoring Model

### Template Precedence

Checklist composition follows a defined precedence order. Lower layers add to or override higher layers; they do not replace them:

1. **Universal base items** — defined once, apply to all scenarios by default (scene safety, PAT for peds, primary survey phases, vital signs, reassessment, transport decision, handoff)
2. **Family template** — pre-configured item sets for common scenario shapes (peds_respiratory, adult_cardiac, trauma, etc.)
3. **Call-type rubric** — portable NASEMSO rubric for this call type; sourced from `app/rubrics/nasemso/`; condition-specific items standardized across all instances of this call type regardless of scenario, agency, or simulator context; see §5.5
4. **Scenario-specific delta** — items unique to this case presentation (specific mechanism of injury, named pre-existing condition altering management, point value adjustments for local protocol emphasis)
5. **Context filtering** — level/MCA/agency conditions applied at session start, filtering the composed checklist to the effective checklist for this student

Scenario authors write only the scenario-specific delta layer. They do not re-author base items, family template items, or call-type rubric items unless they need to override a base item's behavior for case-specific clinical reasons (and that override is explicit, not silent). Items that belong on every call of this type — not just this specific case — belong in the call-type rubric, not the scenario delta.

### Authoring Burden Mitigation

**Universal base items authored once:** Scene safety, PAT (peds), primary survey phases, vital signs, reassessment, transport decision, and handoff do not need to be authored per scenario. Scenario authors opt out of base items that are clinically inappropriate rather than opting in to everything.

**Family templates reduce delta authoring:** A `peds_respiratory` template pre-configures items common to all pediatric respiratory presentations (lung auscultation, SpO2, work-of-breathing assessment, oxygen delivery with timing). An author building a new peds respiratory scenario starts from the template and adds only the condition-specific items.

**Validation tooling catches authoring errors early:**
- Missing required fields → validation error
- `description` that doesn't describe an observable behavior → warning
- Items with `allowed_tiers` including tier 2 but without test coverage → validation error
- `tier3_permitted: true` without a rationale note → warning
- Items referencing intervention IDs not in the scenario's intervention set → error
- `partial_credit_rule` absent on an item that supports `partial` state → error

**Authoring guide:** Documents the observable behavior constraint with annotated examples of valid vs invalid item descriptions. One-page reference, not a manual.

**Author-facing tooling (Phase 5+):**
- **Checklist preview** — renders the effective checklist for a given level/MCA/agency combination so authors can verify context filtering without running a session
- **Matcher test generator** — scaffolds the positive/negative sample set file for a new Tier 2 rule from a list of phrasing examples, reducing the manual overhead of coverage harness setup
- **Family-template inheritance view** — shows which items an in-progress scenario inherits from its family template and which are overridden, so authors can confirm the delta layer is correct before authoring redundant items
- **Validation output with fix hints** — validation errors include the rule violated and an example of a valid value, not just the field name
- **Sibling item linking** — when a clinical item and its documentation counterpart are authored as separate items (per §6.2 one-to-one category rule), the authoring tool groups them visually and warns if a clinical intervention item has no corresponding documentation item authored — preventing the common omission of the documentation deduction counterpart

---

## 16. Transitional Data Handling

The current system includes transitional tag-derived sources (AI-emitted `[[INTERVENTION:]]`, `[[EXAM:]]`, `[[VITAL:]]`, `[[HISTORY:]]` tags parsed from response text). During migration, the following rules apply:

- **Structured backend events always outrank tag-derived sources.** If an intervention record exists, that is the authoritative fact. A tag-derived finding for the same action is redundant and does not add credit.
- **Tag-derived findings may support Tier 2 matching as supplemental text** but never satisfy a Tier 1 requirement.
- **Tag-derived findings never override Tier 1.** A tag claiming an action was performed does not credit the action if the corresponding structured record is absent.
- **`frontend_explicit` session events are stored for analytics but are not credited** as authoritative evidence in any tier of the satisfaction cascade.

Migration is complete for a given item when Tier 1 coverage exists and tag-derived fallbacks are no longer needed. Items should be migrated to structured event satisfaction as Tier 1 coverage expands.

**Mixed-state coexistence rules:**
- Current evidence-packet outputs remain valid during migration. Sessions scored under the legacy path are not invalidated.
- Migrated checklist-backed items and legacy-scored items may coexist within the same session during the transition period.
- **An item must not be scored by both paths simultaneously.** When a checklist item is migrated, the corresponding legacy scoring path for that item is disabled. The migration flag on the item is the switch — legacy and new paths are mutually exclusive per item. Scoring the same item via both paths produces double-credit or double-deduction and is treated as a migration bug, not acceptable mixed-state behavior.

---

## 17. Audit Example

The following illustrates how a single checklist item flows through the full system.

**Scenario:** Pediatric croup — EMT student, PFD agency, Michigan BLS MCA
**Item:** Epiglottitis differential screen

**`screen` items are satisfied from live evidence, not post-call documentation:**

`screen` items differ categorically from `intervention` items — there is no button press or intervention table row for "considered epiglottitis." However, in the training simulator context, the DMIST may contain AI-generated or partner-generated text that the student did not personally compose. Permitting DMIST to satisfy a `screen` item would allow auto-generated documentation to award clinical performance credit without the student ever reasoning through the differential during the live call.

**Correct evidence hierarchy for `screen` items:**
1. **Tier 1** — a structured session finding or event that represents the reasoning (e.g., temperature vital obtained for a fever-screen item; explicit assessment event key)
2. **Tier 2 transcript** — student explicitly names or discusses the differential in the live chat

Submitted DMIST/narrative text does NOT satisfy `screen` items. Naming a differential in the DMIST may contribute to documentation quality scoring (`documentation_handoff` credit) — but that is a documentation credit, not a clinical performance credit for the reasoning. This distinction must be kept clear in item authoring: `intervention` and `screen` subtypes do not get Tier 2 `submitted_document_text` credit.

**Checklist item definition:**
```json
{
  "id": "epiglottitis_differential",
  "description": "Verbalized epiglottitis as a differential consideration",
  "subtype": "screen",
  "category": "clinical_performance",
  "point_value": 3,
  "required": "required",
  "applicable_levels": [],
  "allowed_tiers": [1, 2, 3],
  "preferred_tier": 2,
  "tier3_permitted": true,
  "timing_constraint": null,
  "partial_credit_rule": null
}
```

*Note: The description says "verbalized" — not "in chat, findings, DMIST, or narrative." Source enumeration belongs in the item's Tier 2 matching rules, not in the observable behavior description. The description describes the behavior; the tier rules describe where evidence is sought.*

**Satisfaction cascade result:**
- Tier 1: no structured event record for epiglottitis differential → not satisfied at Tier 1
- Tier 2: submitted DMIST/narrative text is not eligible for `screen` items → not satisfied
- Tier 3: not permitted for clinical reasoning screens unless explicitly enabled with test coverage → not evaluated

**Adjudicated state:** `not_satisfied`

**Evidence reference stored in packet:**
```json
{
  "tier": null,
  "source_type": null,
  "document_type": null,
  "matched_text": null,
  "match_rule": null,
  "message_timestamp": null,
  "diagnostic": "screen items require live student transcript or structured Tier 1 evidence; submitted documentation does not back-credit clinical reasoning"
}
```

**Score consequence:** 0 pts to clinical_performance

**How AI uses this in feedback:**
The AI receives the packet showing `epiglottitis_differential: not_satisfied` with the diagnostic. It does not infer live clinical reasoning from the submitted DMIST. It writes coaching such as: "Your DMIST names epiglottitis, but I do not have live run evidence that you performed that screen during the call. Documentation can improve handoff quality, but clinical performance credit requires asking, assessing, or otherwise documenting the screen in live evidence."

If the item had resolved `satisfied` from live transcript, the evidence reference would point to `student_transcript`, for example: "I am checking for drooling, tripod positioning, toxic appearance, and high fever." The AI could then credit the screen without relying on submitted documentation.

---

## 18. Implementation Phasing

Order matters. Resist the temptation to implement Tier 3 before Tier 1 and Tier 2 are solid. Each phase boundary is a stable, shippable state — no phase leaves the system in a partially-broken condition.

### Current state at time of planning

- Score arithmetic is LLM-generated. The AI emits a `SCORES_JSON:` line; the backend regex-parses it. No Python scorer exists.
- `_build_evidence_packet()` builds a prompt-context dict that is not persisted and not authoritative.
- 13 scenarios use `required_assessments` / `required_screens` with keyword lists and `missing_deduction` values. No `critical_actions` are populated. No unified `checklist` array exists.
- Tier 2 matching is keyword-only with no test coverage and no CI validation.
- Tier 1 structured records exist (intervention table, session findings, scene_entry, transport) but are not formally wired to an adjudication layer.

### Starting point

Phase 1 (`app/checklist.py` + DB migration + pilot scenario) and Phase 4 scaffolding (`app/scoring_service.py` with `compute_scores` unit-tested against mock data) may run in parallel. Phase 4 is unblocked the moment Phase 1 defines `ChecklistItem`, `ChecklistItemState`, and `CategoryScore`. Phase 1 is the authoring contract. Phase 4 is the reliability win.

---

### Phase 1 — Schema formalization and persistence foundation ✓ Complete

**No behavior changes. Existing logic continues to run. Produces the contract all later phases build against.**

**New file: `app/checklist.py`**

`ChecklistItem` Pydantic model with the complete §6.2 field set. All fields must be present now — adding them later requires a breaking schema reshuffle:

```
id, description, subtype, category, point_value,
partial_credit_rule, required, applicable_levels,
requires_mca_expansion, agency_applicable,
timing_constraint, allowed_tiers, preferred_tier,
tier3_permitted, tier3_confidence_threshold, schema_version
```

Supporting types: `ChecklistItemState`, `EvidenceReference`, `CategoryScore`, `EffectiveContext`.

`load_checklist(scenario, level, mca, agency) → list[ChecklistItem]` — context resolution, returns the effective checklist for this session.

**DB migration — all five columns added in Phase 1, not deferred:**

```
sim_sessions.effective_context        JSONB nullable
sim_sessions.effective_checklist_hash VARCHAR nullable
sim_sessions.checklist_states         JSONB nullable
sim_sessions.evidence_references      JSONB nullable
sim_sessions.score_snapshot           JSONB nullable
```

Every JSONB payload includes a top-level `packet_schema_version` field so stored adjudications remain interpretable if the packet shape evolves. Reading code checks this version before deserializing; unknown versions surface a diagnostic rather than silently misreading stale data.

**Pilot scenario migration:** Add a `checklist` array to `peds_croup_01.json` alongside the legacy `required_assessments` / `required_screens`. Both coexist per §16 migration rules. Croup is the edge-case validation target — use `peds_syncope_01.json` or a structurally simple trauma as the canonical base-pattern scenario for establishing normal behavior. Croup's screen/documentation/reassessment complexity should stress-test the engine after base patterns are proven, not define them.

**`scripts/validate_scenario.py`** — checks all `checklist` items against the full schema, reports missing fields and observable-behavior violations. Run manually in Phase 1; CI-integrated in Phase 3.

---

### Phase 2 — Tier 1 coverage audit and evidence reference wiring ✓ Complete

Audit all 13 scenarios. For each checklist item: does a structured backend record exist that satisfies it? Produces a coverage map: Tier 1 satisfiable | needs Tier 2 | no coverage path yet.

Wire `EvidenceReference` format to existing Tier 1 sources: intervention records, session findings, scene_entry popup data, transport records. Each reference stores `source_type`, `source_id`, and `timestamp`.

**SessionEvent trust boundary — explicit:**
- Events written by the server when an action is confirmed (e.g., `POST /api/sessions/{id}/interventions` writing an `Intervention` row and `SessionEvent`) are **server-authored records**. Source value `student_confirmed` or `backend_auto` — both carry Tier 1 authority because the server confirmed the action occurred.
- `frontend_explicit` session events are client-asserted claims about intent. They are **never** authoritative for scoring adjudication regardless of content. The distinction: did the server confirm the action occurred, or did the client declare it happened?

---

### Phase 3 — Coverage tooling ✓ Complete

**Must complete before Phase 5. Items without test coverage cannot enter Tier 2 expansion.**

Schema additions to `ChecklistItem`: `positive_samples: list[str]`, `negative_samples: list[str]`. Required when `allowed_tiers` includes 2.

**`tests/test_tier2_matchers.py`** — loads per-item samples, runs match rules, fails by item name. CI-enforced: items with `allowed_tiers` including 2 that have no samples are a validation error, not a warning.

**`scripts/generate_matcher_samples.py`** — scaffolds sample files from phrasing lists.

`scripts/validate_scenario.py` gains CI integration in this phase.

---

### Phase 4 — Score arithmetic lock ✓ Complete

**Highest immediate reliability impact.**

**Reframed scope:** This phase locks score computation for deterministically adjudicable inputs. It does not complete the scoring-authority transfer for documentation accuracy (still depends on AI claim extraction) or professionalism (still depends on AI evaluation path). Those categories complete the transfer in Phase 6. Phase 4 is the arithmetic lock milestone, not the full scoring-authority milestone.

**New file: `app/scoring_service.py`** — the adjudication layer. Adjudication and score computation happen here, before prompt construction. `ai_client.py` consumes the persisted output; it does not originate it.

```python
def resolve_context(session) -> EffectiveContext

def adjudicate(
    effective_checklist: list[ChecklistItem],
    interventions: list[Intervention],
    session_findings: list[SessionFinding],
    session_events: list[SessionEvent],
    chat_messages: list[ChatMessage],  # structured with timestamps — not a flat string
    scene_entry: dict | None,
    submitted_dmist: str | None,
    submitted_narrative: str | None,
) -> list[ChecklistItemState]

def compute_scores(
    item_states: list[ChecklistItemState],
    effective_checklist: list[ChecklistItem],
) -> dict[str, CategoryScore]

async def adjudicate_and_persist(session, db) -> AdjudicatedPacket
```

Inputs are structured objects with timestamps throughout. `chat_messages` is `list[ChatMessage]` so Tier 2 matching stores exact matched spans with message IDs and timestamps — the right shape for evidence references and sequence evaluation.

**Two named structures — kept distinct:**

- **`AdjudicationSnapshot`** — factual engine output: item states, evidence references, tiers used, timing violations. Never bounded, never display-formatted. The source of truth. Stored in `checklist_states` + `evidence_references`. If there is ever a discrepancy, `AdjudicationSnapshot` wins and `ScoreSnapshot` is recomputed from it.
- **`ScoreSnapshot`** — user-facing bounded category totals derived from `AdjudicationSnapshot`. Stores `earned`, `deducted`, `total` (bounded), `max`, and `method` per category. Always computed from `AdjudicationSnapshot` by `compute_scores()` — never authored independently.

**Score arithmetic:** additive from zero; `not_satisfied` deductions per item definition; stacked clinical + documentation deductions for care-gap-plus-fabrication; `contradicted` documentation deduction; bonus items; `[0, category_max]` per category. See §11 for the full policy.

**`adjudicate_and_persist()` idempotency policy:**
- *No prior adjudication:* runs, writes all five columns, records `adjudicated_at`.
- *Re-run, same inputs:* no-op. Detected by comparing a stored `adjudication_input_hash` — a deterministic hash over `effective_checklist_hash` + sorted intervention IDs/timestamps + session finding keys/values (content, not just counts) + chat message IDs in order + scene_entry blob + SHA-256 of submitted docs. Covers content changes that don't move timestamps.
- *Re-run, changed inputs:* replaces all five columns atomically. Archives the prior packet in `adjudication_revisions` JSONB with the original `adjudicated_at`. Prior state is never deleted.
- *Instructor override:* does NOT call `adjudicate_and_persist()`. Writes a separate override record and calls `recompute_scores_from_overrides()`, which patches `ScoreSnapshot` without touching `AdjudicationSnapshot`.

**Phase 4 hybrid score contract:**

Documentation accuracy and professionalism are not yet deterministic. The `ScoreSnapshot` marks them explicitly:

```json
{
  "clinical_performance": { "earned": 28, "deducted": 4, "total": 24, "max": 40, "method": "deterministic" },
  "scope_adherence":      { "earned": 18, "deducted": 0, "total": 18, "max": 20, "method": "deterministic" },
  "documentation":        { "total": null, "max": 10, "method": "legacy_ai", "pending": true },
  "professionalism":      { "total": null, "max": 10, "method": "legacy_ai", "pending": true }
}
```

`legacy_ai` categories set `total: null` — not a number. Consumers that skip the `method` check will fail loudly rather than silently using a stale value. Every consumer of `score_snapshot` — display, pass/fail gating, rewards, ranking — must check `method` before using `total`. `pending: true` categories are excluded from totals, thresholds, and reward calculations until Phase 6.

**`main.py` changes:** Debrief endpoint calls `scoring_service.adjudicate_and_persist()` first, then `ai_client.evaluate_and_generate_debrief()`.

**`ai_client.py` changes:** `evaluate_and_generate_debrief()` reads the persisted packet from the session. Removes `SCORES_JSON:` regex parsing entirely. Debrief prompt receives locked scores and item states as facts to explain — no score-generation instruction.

Debrief quality may shift slightly as the AI transitions from inferring facts to explaining them. Expected and acceptable.

---

### Phase 5 — Tier 2 expansion ✓ Core complete

Coverage tooling active and enforced in CI (Phase 3). `_try_tier2` now searches three source layers per the §10 source eligibility table:

1. **student_transcript** — all subtypes (original behaviour)
2. **session_finding_text** — `assessment`, `reassessment` subtypes only; source_id = matching finding record ID. `screen` items excluded — session findings include AI-generated clinical notes and must not back-credit clinical reasoning actions.
3. **submitted_document_text** — `documentation_handoff`, `documentation_narrative` subtypes only; DMIST searched before narrative. `screen` items excluded for the same reason.

Source priority: transcript > finding_text > document_text. First match wins; higher-confidence sources are never overridden by lower-confidence ones.

`EvidenceReference.source_type` Literal extended with `"session_finding_text"`. `TierOneMatchSpec.scene_entry_path` now used for generic dot-path navigation in addition to the `"ppe"` special case, resolving the Low PUNCHLIST item.

Remaining Phase 5 work (non-blocking): migrate legacy `required_assessments.keywords` / `required_screens.keywords` in `_build_evidence_packet()` to proper T2 patterns as those scenario families onboard to the unified engine. Current EMS scenarios already have T2 patterns covering this content. Legacy path continues to run in parallel per §16 until explicitly retired per item.

---

### Phase 6 — Full scoring-authority transfer, evidence packet hardening, Tier 3 ✓ Complete

**Completes what Phase 4 started. After this phase all four scoring categories are deterministic.**

Phase 1 already added all required DB columns. No second DB reshuffle.

**Separated AI calls** (each isolated with a single objective — see §13):
- `_run_documentation_extraction()` — focused JSON-mode call using `groq_extraction_model`. Scores DMIST (0–10) and narrative (0–20) against the same rubric as the main debrief. Fail-closed: returns `{"review_complete": False, ...}` on any timeout or API error. Results are injected as LOCKED values into the main debrief prompt and enforced post-call via hard override (not just a ceiling clip).
- `_run_corroboration_prepass()` — Tier 2 LLM pre-pass that identifies unsupported DMIST/narrative claims before main extraction. Receives scenario `dmist_components` and `corroboration_rules` to apply per-component deduction caps.
- `_run_professionalism_review()` — focused JSON-mode call using `groq_extraction_model`. Scores professional communication 0–10, capped at `prof_ceiling` (PPE-derived cap from scene_entry scoring). Returns `score` and `breakdown` for prompt injection. Fail-closed same pattern.
- All three calls (prepass + doc extraction + prof review) run concurrently via `asyncio.gather(return_exceptions=True)`. Exception results sanitize to their respective fallback dicts.
- Post-call enforcement: `_p6_dmist`, `_p6_narrative`, `_p6_prof` override whatever the main debrief LLM returned (analogous to existing ceiling enforcement, but unconditional when Phase 6 succeeds). Existing evidence-packet ceiling enforcement runs first and still takes precedence.

**Scoring model — universal across scenarios:**

`_run_documentation_extraction()` applies a per-component DMIST model and per-CHART-element narrative model. These rules are universal; the scenario provides context via `dmist_components`, `corroboration_rules`, and `dmist_considerations`/`narrative_considerations` fields.

*DMIST (0–10) — D/M/I/S/T each ~2 pts:*
- **D** (demographics): patient identifiers and demographics. Pediatric patients require weight when relevant to dosing or ALS handoff; adult patients do not require weight by default.
- **M** (MOI / chief complaint): mechanism of injury for trauma OR chief complaint / nature of illness for medical.
- **I** (injuries / illness): trauma injuries OR medical illness details/history. Do not score treatments under I.
- **S** (signs/symptoms): current status, assessment findings, and vitals validated against **student-assessed vitals** (SessionFinding vital rows only) — not the scenario baseline. SpO2 is exempt as passively observable. Claiming full vital set when only SpO2 was assessed = 0/2.
- **T** (treatment / transport): treatments performed, response, and transport/turnover plan. Treatments are validated against applied intervention records. MCA-critical treatment fabricated or misrepresented = 0/2 for T.
- Calibration anchor: template DMIST with accurate D/M but fabricated S/T → 4–5/10.

*Narrative (0–20) — C/H/A/R/T each ~4 pts:*
- **A** element: fabricated vitals → −2 to −3 pts.
- **R** element: fabricated intervention → −2 pts; MCA-required treatment fabricated → full R deduction.

**Student-assessed vitals source:** Built from SessionFinding vital rows before the Phase 6 calls and passed as a dedicated `student_assessed_vitals` parameter. The scenario's `vitals.baseline` is reference data for the AI — it is never used as the corroboration source for S-component validation and is not credited to the student automatically.

**Professionalism (0–10) — tiered scale:** 9–10 engaged/compassionate throughout; 7–8 adequate with one gap; 5–6 task-focused with little engagement; 3–4 minimal/task-only; 1–2 poor/curt/alarming. Passive communication that avoids errors but never engages the patient or family scores 5–6. This replaces the legacy "thinness ≠ deduction" model.

**Denominator fix (Phase 6):** When deterministic locked scores are present, `_clinical_max` and `_treatment_max` derive from `score_snapshot.max` (the engine-computed actual category max), not from the rubric JSON `max` field. These can diverge when base rubric items and overlay items together differ from the declared rubric max — using `score_snapshot.max` prevents the debrief denominator from misrepresenting actual scoring scale.

**Client denominator propagation:** The debrief response carries `_maxes` inside the structured subscores object so frontend score displays, progress bars, and pass/on-track percentages use the same engine-computed denominator as the backend. The frontend must not assume clinical performance is always 40 or 50 points.

**Config additions:** `groq_extraction_model` (default: lexi model) and `groq_tier3_model` (default: debrief model) added to `app/config.py`.

**Tier 3 infrastructure stub:** `_tier3_model_verified` module flag, `verify_tier3_model_capability()` async startup check, and `_try_tier3()` stub added to `app/scoring_service.py`. Items with `tier3_permitted=True` that exhaust Tier 1/2 now route to `ambiguous` rather than `not_satisfied`. Full async Tier 3 implementation (logprob-based binary classification) is Phase 7+, requiring `adjudicate()` to become async.

**Instructor review queue:** `GET /api/sessions/{id}/review-queue` — surfaces checklist items in `ambiguous` state with scenario metadata. Requires instructor/admin role; agency-scoped.

**Instructor override:** `POST /api/sessions/{id}/override` — resolves `ambiguous` items to `satisfied` or `not_satisfied`. Recomputes `compute_scores()` from updated `checklist_states`, persists an `AdjudicatedOutcome` (reason_type: `instructor_override`), and returns updated subscores.

**Phase 6 re-debrief:** `POST /api/sessions/{id}/re-debrief` — instructor-triggered only, rate-limited (`rate_limit_debrief/minute`), audited via `AdjudicatedOutcome` (reason_type: `instructor_re_debrief`). Re-runs `adjudicate_and_persist()` to pick up any instructor overrides, then regenerates coaching via `evaluate_and_generate_debrief()`. Updates `session.feedback`, `session.narrative_data`, and score fields atomically.

---

### Phase 7 — Calibration and longitudinal coaching ✓ Complete

**Observability logging:** `adjudicate_and_persist()` emits a structured JSON log line after every adjudication with per-item tier resolution counts (`tier1`, `tier2`, `tier3`, `ambiguous`, `not_satisfied`, `legacy_ai`), `ambiguous_ids`, scenario_id, session_id, and provider_level. Production log aggregators can parse and aggregate these for dashboards.

**Gold-standard evaluation harness:** `tests/test_adjudication_gold_standard.py` — parametrized fixtures for `peds_syncope_01` covering full-credit, clinical gap, scope violation, PPE gap, and documentation-vs-live-evidence screen scenarios. Includes a structural enforcement test (`test_all_fixture_items_have_expected_coverage`) that fails if a new checklist item is added to a scenario without a corresponding fixture expectation. Adding new scenario checklists requires a corresponding fixture in this file.

**Calibration CLI:** `scripts/calibration_metrics.py` — queries completed sessions for tier resolution rates, miss rates, ambiguous rates, override rates, and score distributions by scenario and level. Outputs table or JSON. Options: `--scenario`, `--level`, `--min-sessions`, `--format`, `--top`. Used for recurring calibration review (§20).

**Longitudinal student performance:**
- `GET /api/me/performance` — student view of own performance (last 50 completed sessions): score trend, per-category averages from score_snapshot, top 10 most-missed checklist items
- `GET /api/students/{user_id}/performance` — instructor view of a specific student (agency-scoped; superuser can view any student)
- Both endpoints read from `checklist_states` and `score_snapshot` columns — no additional DB writes required

### Phase 8 — Deterministic Debrief Composer (planned)

**Goal:** Remove the LLM from scored section authorship. Clinical Performance and Protocols & Treatment sections are rendered deterministically from adjudicated item states and per-item feedback metadata. The LLM debrief call narrows to coaching and education only.

**Prerequisites:**
- Per-item feedback metadata fields authored for all scenarios: `done_feedback`, `missed_feedback`, `clinical_rationale`, `common_error` (schema addition, no migration needed — fields are optional until renderer is active). **Note:** The NASEMSO call-type rubric schema (`ems_call_type_rubric.schema.json`) already requires and CI-validates `done_feedback` and `missed_feedback` on every item in that layer. The authored rubric files (`respiratory_distress_v1.json`, `pediatric_croup_v1.json`, `hypoglycemia_v1.json`, `head_injury_v1.json`) demonstrate the pattern. Step 1 and 2 below extend the same contract to in-scenario checklist items.
- Category-separated evidence blocks in `_format_evidence_packet_for_prompt()` — **complete as of 2026-05-11** (see `app/ai_client.py`)
- Section 4 and Section 7 source constraints wired to category blocks — **complete as of 2026-05-11**

**Implementation steps:**
1. Extend `ChecklistItem` Pydantic model in `app/checklist.py` with feedback metadata fields (nullable, backward-compatible), matching the field names already in use in the NASEMSO call-type rubric schema
2. Author `done_feedback` / `missed_feedback` / `clinical_rationale` / `common_error` for all items across the current 17-scenario set
3. Implement `_compose_scored_section(category, item_states, definitions)` — renders a category section as a scored bullet list from adjudicated facts and authored metadata, with no LLM call
4. Wire `_compose_scored_section()` for Clinical Performance and Protocols & Treatment sections; inject rendered text into the debrief prompt as locked content (read-only — LLM must not rewrite it)
5. Update the debrief LLM prompt to receive only: patient context, clinical education request, takeaway request, reflection prompt request — not the full evidence packet
6. Validate against calibration fixtures; confirm rendered content matches expected gap coverage and score explanation

**Intermediate state (current):** Category-separated blocks (`## CLINICAL_PERFORMANCE_GAPS`, `## PROTOCOL_TREATMENT_GAPS`) in the evidence packet plus section-level source constraints in the prompt give the LLM typed inputs per category. The `_sanitize_protocol_treatment_section()` post-processor provides defense-in-depth against section boundary leaks. This intermediate state is not the target — the source constraints are still prompt-instructional and can drift. Phase 8 makes the boundary structural.

**DMIST and Narrative:** Remain hybrid after Phase 8. The deterministic corroborator identifies contradictions; the LLM explains the specific discrepancy in plain language, bounded by the contradiction list. Structured DMIST entry (QA/QI track) is the long-term fix for full determinism here.

---

## 19. What This Achieves

Every recurring scoring reliability problem — AI crediting non-evidenced care, wrong scope/clinical score split, partner text attributed to student, documentation softening, inconsistent scores across identical runs — is eliminated when factual determination moves to code and AI is restricted to explanation.

The feedback reads like a real instructor because the AI knows exactly what happened before it writes a word of coaching. It can cite specific evidence ("you applied O2 at +3 minutes but did not reassess until +8"), explain clinical significance without hedging, and give direct gap feedback without softening. The evidence packet gives the AI the same situational awareness a field training officer would have reviewing a documented run.

Scalability is structural. Universal base + family templates + scenario-specific deltas keeps authoring cost proportional to clinical novelty, not to system complexity. Level, MCA, and agency variation is handled by context resolution and item conditions — adding a new context variant requires no changes to existing scenarios.

---

## 20. Quality Assurance and Observability

A strong architecture without a quality feedback loop will drift. This section defines the mechanisms that keep the system accurate and improvable over time.

### Gold-Standard Evaluation Set

A curated bank of representative sessions with known-correct expected outputs. For each session in the set:
- Full student transcript
- Expected checklist adjudication per item (state + tier + evidence reference)
- Expected documentation deductions
- Expected category scores and final score
- Expected debrief quality characteristics (gap coverage, coaching specificity)

This evaluation set is the regression benchmark. Changes to item satisfaction rules, score arithmetic, or AI prompting are validated against it before deployment. The set grows over time as new scenario families and edge cases are encountered.

### Calibration Process

Periodic review comparing system adjudications and scores against independent instructor evaluations of the same sessions. Calibration targets:
- Items that score too harshly relative to instructor judgment → adjust deduction weight or satisfaction rule
- Items that score too leniently relative to instructor judgment → tighten satisfaction criteria or add negative test cases
- Items with high override rates → candidates for Tier 2 expansion or satisfaction rule revision
- Scoring disagreements tracked by scenario family, not just globally — family-level drift indicates a template or base item problem

Calibration is not a one-time activity. It is a recurring process throughout the system's active life.

### Operational Observability Metrics

Production health signals that must be monitored:

| Metric | Purpose |
|---|---|
| Tier 1 / Tier 2 / Tier 3 resolution rate by item type | Measure deterministic coverage; flag items over-reliant on Tier 3 |
| `ambiguous` item rate — overall and per item | Coverage gap indicator; elevated rate = Tier 2 expansion needed |
| Instructor override rate — overall and per item | High override rate on an item = adjudication rule needs revision |
| Most-overridden items | Direct input to calibration review |
| Most-missed checklist items by scenario family | Informs authoring quality and teaching point priorities |
| Documentation contradiction frequency | Measures corroboration accuracy; high rate may indicate scenario realism issues |
| Score distribution by scenario and level | Detects scoring drift; unexpected shifts signal a rule or prompt change impact |
| Debrief generation failures and fallback rates | Operational reliability signal for the AI coaching layer |

These metrics do not require real-time dashboards immediately — logging at the session and item level from Phase 4 onward provides the data needed for batch analysis. Dashboards are a Phase 6/7 concern.

---

## 21. Known Failure Modes and Architecture Safeguards

The architecture is designed around specific recurring failures observed in the current system. This section maps each failure mode to the safeguard that eliminates it.

| Failure mode | Root cause | Safeguard |
|---|---|---|
| **AI credits non-evidenced care ("What Was Done Well" cites undocumented interventions)** | AI inferred care from documentation or context rather than run evidence | §13: AI receives locked satisfied-item list; "what was done well" sourced only from `satisfied` checklist items with evidence references — never inferred from DMIST or narrative |
| **Documentation softening (DMIST with unsupported claims described as "accurate")** | AI lacked a structured distinction between care gaps and documentation integrity failures | §7.1: `unsupported_by_run` state separates documentation integrity failure from clinical performance gap; both trigger explicit deductions and specific coaching, neither is softened |
| **Partner/system text attributed to student** | AI sourced "what was done well" from full transcript including AI-generated roleplay responses | §13: AI debrief call receives student-only transcript; system-generated partner, dispatch, and AI response text are excluded from the packet the AI evaluates |
| **Scope score too low for a run with no out-of-scope actions** | AI conflated missed in-scope care with scope violations | §11 scope adherence rule: deductions apply only to out-of-scope attempts or active refusal; missed opportunities are clinical performance gaps, never scope gaps |
| **Timeline shows PAT/BSI as missed despite scene_entry data** | Scene entry data read from a stale SQLAlchemy session attribute after a long async LLM call | §12 lifecycle: context resolution and checklist adjudication run before the AI call; scene_entry is locked in the evidence packet at adjudication time, not re-read from session after the LLM call |
| **Inconsistent scores across identical runs** | Score arithmetic delegated to AI inference rather than code | §11 and §1: score computation is entirely in code; AI receives the locked score and generates coaching from it — identical runs always produce identical scores |
| **AI hallucinated reassessment credit** | AI awarded reassessment credit based on its own roleplay response text rather than backend records | Tier 1 satisfaction for reassessment items requires a timestamped session finding or session event; AI response text is not a valid Tier 1 or Tier 2 source for reassessment items |
| **Timing/order mistakes (item credited before prerequisite)** | No sequence enforcement; all items treated as unordered | §9: `timing_constraint` fields with `before_item`/`after_item`/`ordered_set` enforce sequence; violations produce `partial` or `deduction_override` per item definition — evaluated against timestamped backend records, not AI inference |
| **Assessment gap cited as Protocol/Treatment deduction (category mis-bucketing)** | LLM received a mixed evidence packet without category labels; inferred which section to place each gap | Intermediate: category-separated blocks (`## CLINICAL_PERFORMANCE_GAPS`, `## PROTOCOL_TREATMENT_GAPS`) in evidence packet; section 4 and 7 source constraints; `_sanitize_protocol_treatment_section()` post-processor as defense-in-depth. Target (Phase 8): deterministic section renderer sources directly from typed adjudicated item states — no LLM section-placement decision |
