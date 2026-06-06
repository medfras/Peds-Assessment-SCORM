# QA/QI Readiness Requirements

**Status:** Pre-readiness — training simulator in active development
**Created:** 2026-05-11
**Scope:** Requirements that must be met before RescueTrails scoring and feedback output can be used in real-world EMS QA/QI review contexts (ePCR review, agency protocol compliance, clinical performance adjudication). This document does not apply to the training simulator product itself — those requirements are tracked in `SAAS_HARDENING_PLAN.md`.

---

## 1. What QA/QI Use Means

QA/QI use means the scoring and feedback engine output is used beyond training simulation — for example:

- Agency medical directors reviewing scored run data to identify training gaps
- Protocol compliance reports used in provider performance reviews
- Automated flagging of real ePCR records against protocol expectations
- Scored evidence used in provider appeals, corrective action, or certification decisions

This is distinct from a training product where a student receives a score and coaching on a simulated run. In QA/QI use, scored output may be used in official reviews, may be shared with regulatory bodies, and may affect provider employment or certification. The reliability, traceability, and defensibility bar is materially higher.

**Current status:** RescueTrails is not ready for QA/QI use. This document tracks what must change before that bar can be claimed.

---

## 2. Gaps That Must Close Before QA/QI Use

### 2.1 LLM Adjudication Must Be Eliminated from All Scored Paths

**Status:** Open — two active LLM adjudication paths remain.

For QA/QI use, every scored outcome must be traceable to a deterministic code path. LLM output can be used for explanation and coaching text, but it must not produce or influence any value that flows into the final score.

**Remaining LLM adjudication paths:**

| Path | Location | Gap | Required fix |
|---|---|---|---|
| Corroboration prepass | `_run_corroboration_prepass()` | LLM determines whether documented claims are supported by the run | Replace with direct evidence-record comparison (see `SAAS_HARDENING_PLAN.md SCORE-01`) |
| `EVALUATE` critical actions | evidence packet classification | LLM determines pass/fail for items tagged `EVALUATE` | Define Tier 1 or Tier 2 path for every item; eliminate `EVALUATE` tag (see `SAAS_HARDENING_PLAN.md SCORE-02`) |
| Documentation quality | `_run_documentation_extraction()` | LLM extracts and scores DMIST/narrative claims | Structured DMIST entry + deterministic completeness checks (see §2.3) |
| Professionalism score | `_run_professionalism_review()` | LLM holistic assessment produces the professionalism score | Behavioral rubric with Tier 1/Tier 2 paths for all observable items (see `SCORING_ENGINE_ARCHITECTURE.md §14`) |

Until all four paths are replaced, any system output labeled as QA/QI findings must include a disclosure that the score was produced with AI-assisted components.

### 2.2 Every Scored Item Requires a Traceable Evidence Chain

**Status:** Partially in place — evidence references exist for Tier 1 items; Tier 2 and legacy-AI items have weaker traceability.

For QA/QI use, every item in the evidence packet must produce a human-readable statement linking the scored outcome to a specific, verifiable record:

> "Scene safety confirmed: student stated 'scene is safe, BSI taken' at 0:32 (message ID 42)."

> "Oxygen delivery not documented: no `albuterol_svn` or `o2_nrb` Intervention record found; DMIST did not reference oxygen administration."

This statement must be generated deterministically from the evidence reference, not by the LLM in prose. It is the audit trail that a medical director or appeals reviewer can read without needing to interpret AI coaching language.

**Required work:**
- Add a `_render_evidence_chain()` function that converts each `ChecklistItemState` + evidence reference into a one-sentence structured finding
- Include the evidence chain in the evidence packet output (separate from coaching prose)
- Evidence chains must be stored immutably alongside the score snapshot — they are the forensic record
- QA/QI-facing views should display evidence chains as primary content; coaching prose as secondary

### 2.3 Structured Documentation Entry

**Status:** Not built — DMIST and narrative are currently free-text inputs.

Free-text DMIST and narrative entry requires regex parsing and LLM extraction to produce scored findings. Both approaches have error rates that are unacceptable for QA/QI use.

**Required work:**
- DMIST entry must become a structured form with separate fields for each component (D, M, I, S, T)
- Each component field is scored independently: present and non-empty + content accuracy check against evidence packet
- The LLM is no longer needed for documentation claim extraction; scoring becomes deterministic
- Narrative entry may remain free-text for prose quality feedback but accuracy claims must be validated against a structured claim registry extracted at submission time, not at debrief time
- This is a prerequisite for documentation scoring to carry `method="deterministic"` in the evidence packet

### 2.4 Tier 2 Transcript Matching Is Not Sufficient as Primary Evidence for QA/QI

**Status:** Active dependency — many assessment items currently resolve at Tier 2 only.

Tier 2 matches text, not actions. A student can satisfy a Tier 2 item without performing the action, and can miss credit while performing it. For training simulation, this is an acceptable approximation. For QA/QI use where scored output may be used in provider reviews, Tier 2 should be a corroborating signal, not the primary evidence source.

**Source eligibility filtering addresses the most critical distinction:** The `eligible_source_roles` mechanism on NASEMSO call-type rubric items already enforces source-level constraints at Tier 1. For example, a BGL item with `eligible_source_roles: ["ems_measured_vital"]` is not satisfied by a caregiver-reported CGM finding, even if the finding key matches. This is the deterministic equivalent of the "measured vs. reported" distinction that matters most for QA/QI. Items without `eligible_source_roles` remain subject to the Tier 2 text-matching limitation until they gain a Tier 1 structured event path.

**Required work:**
- All assessment items currently resolving at Tier 2 that are safety-critical or clinically significant must have a Tier 1 path defined
- Tier 1 path requires structured UI interaction emitting a `SessionEvent` with `source=backend_auto`
- Items that cannot be given a Tier 1 path (genuinely only expressible in natural language) must be explicitly declared `tier3_permitted: true` with a rationale note — and Tier 3 requires logprob-validated confidence (see `SCORING_ENGINE_ARCHITECTURE.md §10`)
- The Tier 2 / Tier 1 coverage ratio per scenario must be reportable; scenarios with high Tier 2 dependency should be flagged as lower-confidence for QA/QI use

### 2.5 Base Rubric Compound Items Need Sub-item Evidence Source Requirements

**Status:** Known gap — flagged 2026-05-14.

Several base NREMT rubric items award a single credit for multiple distinct clinical actions that have different defensible evidence sources. The most visible example is `ems.medical.circulation` ("Assesses circulation: major bleeding, skin, and pulse"). All three sub-actions are bundled into one item with shared Tier 1 and Tier 2 match logic, which allows caregiver-reported skin observations to satisfy a credit that also implies EMS pulse assessment.

**Proposed fix:** Split compound items into explicit sub-requirements with per-requirement `eligible_source_roles`:

| Sub-requirement | Acceptable sources |
|---|---|
| Skin signs (color, temperature, condition) | EMS observation, caregiver/patient report, authored vitals |
| Major bleeding | Scene observation, partner exam, explicit denial |
| Pulse | EMS assessment (`ems_measured_vital`) or authored vitals only — caregiver-reported pulse does not satisfy |

In training simulation, caregiver-reported skin observations are a legitimate proxy for skin assessment (the student observed and received the information). Pulse, however, implies EMS action and should require a structured assessment event. The distinction matters for QA/QI: a caregiver saying "he looks pale" is not the same clinical act as the provider checking a radial pulse.

**Why deferred for now:** Implementing this cleanly requires the base rubric items in `checklist.py` to support a `sub_requirements` structure with per-requirement source eligibility, mirroring the `requirement_logic: "all"` pattern already in the NASEMSO call-type rubric. That is a non-trivial schema extension to the base rubric layer. The fix should be done once, consistently, for all affected compound items — not patched per-scenario.

**Immediate mitigation:** In active training runs, the item will occasionally over-credit when caregiver skin description matches without an explicit pulse check. This is a known approximation in the training product. Flag it in QA/QI readiness reviews rather than treating the current score as authoritative for pulse assessment.

### 2.6 LLM Debrief Prose Must Be Clearly Labeled as AI-Generated Commentary

**Status:** Not differentiated — scored items and coaching prose are currently delivered as a single markdown document.

For QA/QI use, the output must structurally distinguish:

- **Adjudicated findings:** scored items with evidence chains — produced deterministically
- **AI coaching commentary:** clinical education, gap explanation, teaching points — produced by LLM

Mixing these in a single document without labeling creates the impression that all content is equally authoritative. A medical director reviewing a QA/QI report must be able to see clearly which statements are code-derived and which are LLM-generated interpretation.

**Required work:**
- Evidence packet output (adjudicated findings + evidence chains) must be a separate, signed artifact from the coaching prose
- QA/QI-facing report views must present these as distinct sections with explicit authorship labels
- The evidence packet artifact should be signable or hashable so its integrity can be verified independently of the coaching layer
- Instructor and QA/QI reviewer workflows should default to the evidence packet view; coaching prose is supplementary

### 2.7 PHI, Data Retention, and Regulatory Readiness

**Status:** Not in scope for training product — real ePCR data is explicitly prohibited by Terms of Service.

For a QA/QI product that ingests real ePCR records or real agency call data:

- HIPAA Business Associate Agreement (BAA) readiness is required before any real patient data is processed
- PHI-aware storage, logging, redaction, and retention controls must be implemented
- All imported data must carry provenance records (source system, import timestamp, import method)
- Data retention policies must be agency-configurable and auditable
- LLM API calls must not transmit identifiable patient information — de-identification must occur before any data reaches a third-party inference endpoint
- Integration audit logs must record every data ingestion event

These are not improvements to the current training product. They are requirements for a separate QA/QI product that does not yet exist. They are documented here so architecture decisions in the training product do not inadvertently foreclose the QA/QI path.

---

## 3. What Is Already QA/QI-Ready

These components of the current architecture meet the QA/QI bar as-is or require only minor hardening:

| Component | Status | Notes |
|---|---|---|
| Score arithmetic (`compute_scores()`) | Ready | Pure Python; identical inputs → identical outputs |
| Tier 1 satisfaction (structured records) | Ready | Intervention records, SessionEvents, scene_entry — authoritative by design |
| Evidence packet immutability | Ready | Written once at session close; append-only adjudication revisions |
| Instructor override trail | Ready | Separate `AdjudicatedOutcome` table; original packet preserved |
| Protocol snapshot immutability | Ready | Sessions always evaluated against the protocol active at the time of the run |
| Context resolution | Ready | Effective level, MCA, agency ceiling resolved and persisted at session start |
| Hard score ceilings | Ready | Enforced before LLM call; cannot be overridden by coaching prose |
| Session event trust hierarchy | Ready | `backend_auto` / `instructor_note` authoritative; `frontend_explicit` analytic only |
| Schema versioning (`packet_schema_version`) | Ready | Evidence packet carries version for future migration safety |
| NASEMSO call-type rubric source role abstraction | Foundation ready | `source_role_map` in rubric files separates abstract roles from concrete sources per deployment context; same rubric file scores training sessions or real ePCRs by switching context key (`"training"` vs. `"qaqi"`). Pipeline integration (Group F) is pending. |
| Evidence source typing (`SessionFinding.source`) | Foundation ready | `source` field on `SessionFinding` records which path captured each finding; `eligible_source_roles` on match specs filters which sources satisfy an item. Enforces EMS-measured vs. patient/caregiver-reported distinctions at the rubric level. Backward-compatible (NULL source always passes). |

---

## 4. Sequencing — What Must Happen First

The readiness gaps above are not independent. A recommended sequencing:

1. **Eliminate `EVALUATE` items and corroboration prepass** (SCORE-01, SCORE-02) — these are the most direct LLM adjudication paths and are actionable within the current architecture
2. **Integrate NASEMSO call-type rubric layer into scoring pipeline** (Group F) — `load_call_type_rubric()`, source role resolver, and effective checklist composition; this is the first step that makes the portable rubric files operationally meaningful for scoring
3. **Add evidence chain rendering** (§2.2) — deterministic, no new data required, high value for audit trail
4. **Structured DMIST entry** (§2.3) — required before documentation scoring can be `method="deterministic"`; also improves training product quality
5. **Professionalism behavioral rubric** (§2.1, `SCORING_ENGINE_ARCHITECTURE.md §14`) — expand hardened sub-inputs to cover all observable behaviors; retire holistic LLM review
6. **Tier 1 expansion for assessment items** (§2.4) — ongoing as new scenario types are authored; every new scenario should target Tier 1 paths for all safety-critical items
7. **Base rubric compound item splits** (§2.5) — implement `sub_requirements` with per-source eligibility for compound NREMT items; start with `ems.medical.circulation`
8. **Labeled output structure** (§2.6) — implement before any QA/QI-facing reporting surface is built

PHI and regulatory readiness (§2.6) is a separate workstream that begins only when a QA/QI product is formally scoped.

---

## 5. Relationship to Other Docs

- For near-term scoring integrity fixes (actionable now): `docs/SAAS_HARDENING_PLAN.md` SCORE-01 through SCORE-05
- For the target scoring engine architecture: `docs/SCORING_ENGINE_ARCHITECTURE.md`
- For AI role boundaries: `docs/AI_ARCHITECTURE.md`
- For the long-term enterprise QA/QI product concept: `docs/PRODUCT_IMPROVEMENT_DIRECTION.md §8`
