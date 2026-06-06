# Scoring Improvement Plan

**Status:** Implementation in progress — Groups A/B complete, C1/C2 complete, C3 wired for shadow validation, F flag live (runs 2–3 pending), E not started
**Created:** 2026-05-11  
**Revised:** 2026-05-14 (Tier 2 CI gate fixed; rubric smoke harness added; use_call_type_rubric active; croup/fever/lung-sound evidence paths corrected)
**Scope:** Eliminate remaining LLM adjudication paths, harden scoring integrity, close SCORE findings from `SAAS_HARDENING_PLAN.md`. SaaS hardening (security, infrastructure, migrations) is paused for this sprint.  
**Related docs:** `SAAS_HARDENING_PLAN.md` (SCORE-01 through SCORE-05), `AI_ARCHITECTURE.md §3.6`, `SCORING_ENGINE_ARCHITECTURE.md`, `QAQI_READINESS.md`
**Navigation summary:** See `docs/SCORING_HARDENING_ROADMAP.md` for a phase-gated checklist of remaining work and the per-scenario authoring checklist.

---

## Corrections From Codex Review

The following were errors or overstatements in the original review. Corrected before planning:

**SCORE-05 (Temperature) — False finding, close it.** The debrief LLM call uses `temperature=0.4`, not 0.7. The 0.7 is on the Lexi companion call only, which produces no scored output. No code change needed. Update docs and close.

**A2 — DMIST range was wrong.** `SCENARIO_DESIGN_EMS.md §1559` and Phase 6 extraction code (`min(10, ...)`) both confirm DMIST is 0–10, not 0–20. The plan's hardcoded ranges were incorrect. Corrected below.

**A2 — Dynamic clamping already exists.** Phase 6 extraction already clamps DMIST to `max(0, min(10, ...))` and narrative to `max(0, min(20, ...))`. There is no current unbounded score-corruption risk. Parser-level validation is still worthwhile as defense-in-depth, but the original framing overstated the severity.

**A1 — Wrong field path.** The field is `scenario["debrief"]` (accessed as `debrief_info = scenario["debrief"]` at `ai_client.py:4592`), not `scenario.get("debrief_info", {})`. Direct dict access already raises `KeyError` if `scenario["debrief"]` is absent entirely. The real gap is sub-fields: `key_teaching_points` and `common_mistakes` raise `KeyError` when missing (lines 5518–5519), while `condition_background` silently degrades via `.get("condition_background", {})` (line 5520). The silent degradation path is the actual bug.

**Phase 6 AI override note.** Phase 6 documentation and professionalism extraction is still AI-derived and then overrides main debrief values. The claim "AI never modifies scoring output" is too broad. This is a known architectural transitional state, not a hidden bug — but it should be stated accurately in any review.

---

## Pre-Implementation Workstream: Calibration Fixtures

**This must be created before any Group A, B, or C code is written.**

A calibration fixture set is the bridge between "architecturally correct" and "clinically defensible." Without it, changes to scoring logic cannot be validated against known expected outcomes — only run against live behavior that may itself be wrong.

### What calibration fixtures are

Each fixture is a fully-specified simulated run with:
- a snapshot of session state (interventions applied, findings recorded, scene_entry, DMIST, narrative, transcript)
- a declared expected scoring outcome per category
- a declared expected evidence packet state (which critical actions are credited, which are missed, which claims are flagged)

Fixtures are deterministic — the same session snapshot always produces the same expected result. They are not end-to-end integration tests of the full stack; they test the scoring and evidence packet logic specifically.

### Minimum fixture set

| # | Fixture | Key coverage |
|---|---|---|
| 1 | Excellent run — all items satisfied | True positive: nothing should be flagged |
| 2 | Missed critical intervention (e.g., no oxygen applied) | `LIKELY_MISSED`, clinical deduction |
| 3 | Fabricated DMIST intervention (documented but not applied) | Corroboration unsupported claim |
| 4 | Sparse but accurate narrative (minimal text, all claims correct) | No false corroboration flags |
| 5 | Polished but inaccurate narrative (full text, wrong vitals documented) | Corroboration flags on vital fabrication |
| 6 | Poor professionalism — no greeting, no consent language | Professionalism deduction via hardened sub-inputs |
| 7 | No scene entry recorded (PPE/PAT skipped) | Scene entry items → `LIKELY_MISSED`, not `EVALUATE` (after B2 fix) |
| 8 | ALS auto-dispatch scenario | ALS critical actions → `ALS_GRACE`, not `EVALUATE` |
| 9 | Respiratory medical scenario (standard case) | Albuterol, PPE, oxygen, DMIST to ALS |
| 10 | Pediatric scenario — weight, PAT, peds-specific items | PAT pre-credit, pediatric scope items |

Additional fixtures for Group C validation:
| # | Fixture | Key coverage |
|---|---|---|
| 11 | Legitimate paraphrase in DMIST ("breathing treatment" for albuterol SVN) | No false corroboration flag |
| 12 | Vital documented in DMIST but never assessed during run | Corroboration flag: `vital_not_assessed` |
| 13 | Demographic contradiction in DMIST | Corroboration flag: `demographic_mismatch` |
| 14 | All DMIST claims supported by run evidence | Zero unsupported claims |
| 15 | Empty DMIST submitted | Structural gap only; no corroboration flags |

### Implementation

Fixtures 1–10 live in `tests/fixtures/scoring/`. The Group C corroboration
fixtures 11–15 are unit-level cases in `tests/test_corroboration.py` because
they exercise the standalone `check_documentation_claims()` interface rather
than the full evidence-packet integration path. Each scoring fixture JSON file
contains:
```json
{
  "fixture_id": "excellent_run",
  "description": "All required items satisfied — baseline for regression",
  "session_snapshot": { ... },
  "expected_scores": {
    "clinical_performance": { "total": 85, "method": "deterministic" },
    "dmist": { "total": 9, "method": "deterministic" }
  },
  "expected_evidence_packet": {
    "critical_actions_classified": [
      { "description": "Administered albuterol SVN", "tag": "DONE_EVIDENCED" }
    ],
    "corroboration": {
      "dmist_unsupported": [],
      "narrative_unsupported": []
    }
  }
}
```

A test runner in `tests/test_scoring_fixtures.py` loads each fixture, runs the relevant scoring and evidence-packet functions, and asserts against expected outcomes.

### Checklist

- [x] `tests/fixtures/scoring/` directory created
- [x] Fixtures 1–10 authored (minimum set before Group A/B coding)
- [x] `tests/test_scoring_fixtures.py` test runner written
- [x] All 10 minimum fixtures pass against current code as baseline
- [x] Fixtures 11–15 authored before Group C coding begins (`tests/test_corroboration.py` unit fixtures)
- [ ] CI configured to run `test_scoring_fixtures.py` on every commit

---

## Group A — Quick Fixes

Implement after calibration fixtures baseline is established. All three are single-file or doc-only changes.

---

### A1 — SCORE-03: Pre-debrief authored content validation gate

**What:** Add explicit validation that the three required authored content sub-fields are present before the debrief LLM call. Add the same validation to scenario startup tests and CI.

**Corrected field path:** `scenario["debrief"]` (not `scenario.get("debrief_info")`). The local variable in `evaluate_and_generate_debrief()` is already named `debrief_info = scenario["debrief"]`.

**Current behavior:**
- `scenario["debrief"]` absent → already raises `KeyError` at line 4592 (fail loud — good)
- `scenario["debrief"]["key_teaching_points"]` absent → raises `KeyError` at line 5518 (fail loud — good, but late and opaque)
- `scenario["debrief"].get("condition_background", {})` absent → **silently degrades to `{}`** at line 5520 — this is the real gap

**Validation severity — three-phase policy (approved):**

| Phase | Context | Behavior |
|---|---|---|
| Now (authoring validation) | Clinical scenario, missing sub-field | Warning-level log in `validate_scenario()` — non-blocking while content is being migrated |
| Now (runtime guard) | Clinical scenario, missing sub-field at debrief time | Hard fail — `ValueError` raised, debrief blocked; becomes 503 in production |
| After migration cutover | Clinical scenario, missing sub-field | `ScenarioVocabularyError` at load time — CI fails, startup blocked |
| Any phase | Orientation / non-clinical scenario with `"debrief_exempt": true` | Exempt from all validation; no check performed |

`"debrief_exempt": true` is the only exemption mechanism. Do not hardcode any scenario ID in `ai_client.py` or validation code.

**Implementation:**

Add to `app/scenarios/vocabulary.py` (scenario validation at load time):
```python
def _validate_debrief_content(scenario: dict, scenario_id: str) -> list[str]:
    """Return list of missing required authored debrief content fields."""
    if scenario.get("debrief_exempt"):
        return []
    debrief = scenario.get("debrief") or {}
    missing = []
    if not debrief.get("condition_background"):
        missing.append("debrief.condition_background")
    if not debrief.get("key_teaching_points"):
        missing.append("debrief.key_teaching_points")
    if not debrief.get("common_mistakes"):
        missing.append("debrief.common_mistakes")
    return missing
```

Call from `validate_scenario()` — emit a `ScenarioVocabularyError` (or warning depending on migration policy) for each missing field.

Add to `evaluate_and_generate_debrief()` as a runtime guard:
```python
if not scenario.get("debrief_exempt"):
    _missing = _validate_debrief_content(scenario, scenario.get("id", "unknown"))
    if _missing:
        _log.error("ai.debrief.authored_content_missing",
                   scenario_id=scenario.get("id"), missing=_missing)
        raise ValueError(f"Scenario missing required authored content: {_missing}")
```

In production the `ValueError` becomes a 503 from the calling endpoint — the debrief does not silently continue with LLM-generated clinical content.

**Pre-work required:** Audit existing scenario JSON files before adding the validation rule:
- Confirm `orientation_01.json` has `"debrief_exempt": true` or add it
- Confirm any other non-clinical scenarios are similarly exempted
- Confirm all clinical scenarios have all three sub-fields (checking `newborn_resus_01_nrp.json` and others named by Codex)

**Tests to write:**
- Clinical scenario with all three fields → no error, debrief proceeds
- Clinical scenario missing `condition_background` only → ERROR log, `ValueError` raised
- Clinical scenario missing all three → ERROR log, `ValueError` raised
- Orientation scenario with `"debrief_exempt": true` → no validation, debrief proceeds

**Checklist:**
- [x] Existing scenario JSONs audited for debrief sub-field completeness
- [x] `orientation_01.json` and any non-clinical scenarios have `"debrief_exempt": true`
- [x] Any clinical scenarios missing sub-fields updated with authored content
- [x] `_validate_debrief_content()` in `vocabulary.py`
- [x] `validate_scenario()` calls it (warn-only initially; escalate to error once all scenarios pass)
- [x] Runtime guard in `evaluate_and_generate_debrief()` — fail loudly on missing fields
- [x] Tests written and passing against calibration fixtures
- [x] Calibration fixtures still pass after change

---

### A2 — SCORE-04: Subscores range and type validation

**What:** Add explicit range validation in `_extract_required_debrief_subscores()`. Phase 6 extraction already clamps per-category values before they reach this function, so this is defense-in-depth — but it closes the gap for the main debrief LLM path where `legacy_ai` values are not yet pre-clamped.

**Corrected ranges (from SCENARIO_DESIGN_EMS.md and Phase 6 code):**
```python
_SUBSCORE_RANGES: dict[str, tuple[int, int]] = {
    "clinical_performance": (0, 100),   # scenario-dynamic; 100 is sanity ceiling
    "scope_adherence":      (0, 100),
    "protocols_treatment":  (0, 100),
    "dmist":                (0, 10),    # confirmed 0–10 per SCENARIO_DESIGN_EMS.md §1559
    "professionalism":      (0, 10),
    "narrative":            (0, 20),
}
```

**Dynamic maxima (approved decision):** `evaluate_and_generate_debrief()` already computes `_clinical_max`, `_dmist_max`, `_professionalism_max`, `_treatment_maxes`, and `_narrative_max`. Pass these as an optional `subscore_maxima: dict[str, int] | None` parameter into `_extract_required_debrief_subscores()`. When a dynamic max is available, use it as the upper bound. Fall back to the global sanity ceiling only when a dynamic max is not passed.

The `_SUBSCORE_RANGES` dict becomes the fallback table only; the signature becomes:

```python
def _extract_required_debrief_subscores(
    raw: str,
    authoritative_fallbacks: dict,
    subscore_maxima: dict[str, int] | None = None,
) -> dict[str, int]:
    ...
    lo, hi = _SUBSCORE_RANGES.get(key, (0, 100))
    if subscore_maxima and key in subscore_maxima:
        hi = subscore_maxima[key]
    ...
```

**Malformed value handling (corrected from original plan):** An out-of-range value that passes `int(value)` cast is not a "missing key" — it is a malformed value. The correct behavior is:
- Reject the malformed value
- Fall through to the **authoritative fallback** (`authoritative_fallbacks` dict, which contains pre-scored deterministic values) — not the regex fallback
- If no authoritative fallback exists, fall through to regex as last resort
- Log at ERROR level (not WARNING) — an LLM returning 150 for a 0–10 scale is a prompt or model failure

```python
lo, hi = _SUBSCORE_RANGES.get(key, (0, 100))
if not (lo <= int_val <= hi):
    _log.error(
        "ai.debrief.subscore_out_of_range",
        key=key, value=int_val, expected=(lo, hi)
    )
    continue  # Fall to authoritative fallback, then regex
subscores[key] = int_val
```

**Tests to write:**
- Value in range → accepted
- Value above range (e.g., `dmist: 15`) → ERROR log, authoritative fallback used
- Value below range (e.g., `dmist: -1`) → ERROR log, authoritative fallback used
- Non-integer string → existing `int()` cast error path
- Authoritative fallback present → fallback value used after range rejection
- No authoritative fallback → regex fallback attempted

**Checklist:**
- [x] `_SUBSCORE_RANGES` dict defined with corrected values
- [x] Range check added after `int(value)` cast
- [x] ERROR log on out-of-range (not warning)
- [x] Falls to authoritative fallback first, regex second
- [x] Tests written and passing
- [x] Calibration fixtures still pass

---

### A3 — SCORE-05: Close as false finding, update docs

**What:** Correct documentation only. No code change.

**Confirmed:** `evaluate_and_generate_debrief()` uses `temperature=0.4` at lines 5831 and 5841. Lexi uses 0.7, which is appropriate for prose and produces no scored output.

**Files to update:**
- `docs/SAAS_HARDENING_PLAN.md` — SCORE-05: mark closed, explain why
- `docs/AI_ARCHITECTURE.md §3.6` — remove or correct temperature paragraph

**Checklist:**
- [x] SCORE-05 in hardening plan updated to: "Closed — false finding. Debrief uses `temperature=0.4`. No change needed."
- [x] `AI_ARCHITECTURE.md §3.6` corrected

---

## Group B — SCORE-02: Eliminate EVALUATE Items

Solid as originally planned with one added guard. Implement after Group A fixtures and fixes are complete and passing.

---

### B1 — Audit EVALUATE-producing paths

*(Unchanged from original plan)*

Four EVALUATE-producing paths in `_build_evidence_packet()` at lines 3734–3756:

| Path | Condition | Fix |
|---|---|---|
| P1 | Scene entry ID, `_se_recorded` is False | B2 |
| P2 | ALS/intercept ID, no grace, not in checklist | B3 |
| P3 | `scene_entry_credited` flag, `_se_recorded` is False | B2 |
| P4 | General fallback — no checklist, no evidence, no fuzzy match | B4 |

**Confirmed scope — all 17 files to audit (approved):**

```
app/scenarios/adult/medical/adult_acs_01_stemi.json
app/scenarios/adult/medical/adult_cardiac_arrest_01_bls.json
app/scenarios/pediatric/medical/newborn_resus_01_nrp.json
app/scenarios/pediatric/medical/peds_ams_tox_01.json
app/scenarios/pediatric/medical/peds_anaphylaxis_01.json
app/scenarios/pediatric/medical/peds_asthma_01.json
app/scenarios/pediatric/medical/peds_cardiac_arrest_01_bls.json
app/scenarios/pediatric/medical/peds_croup_01.json
app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json
app/scenarios/pediatric/medical/peds_febrile_seizure_01.json
app/scenarios/pediatric/medical/peds_syncope_01.json
app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json
app/scenarios/pediatric/trauma/peds_trauma_02_partial_choking.json
app/scenarios/pediatric/trauma/peds_trauma_03_extremity.json
app/scenarios/pediatric/trauma/peds_trauma_04_burn.json
app/scenarios/pediatric/trauma/peds_trauma_05_auto_ped.json
app/scenarios/pediatric/trauma/peds_trauma_06_handlebar.json
```

Audit all 17 regardless of current live/dev status — prevents new content from inheriting scoring debt.

**Checklist:**
- [x] All 17 scenario JSONs audited for `correct_treatment.critical_actions`
- [x] Per-action classification path documented for each action across all 17 files
- [x] P4 fallback actions identified by scenario and action_id

**Audit findings:** All 96 `critical_actions` across 17 scenario files have non-empty `id` fields. Current routing is deterministic:
- 29 scene-entry/PAT-style actions route through the pre-credit path.
- 3 ALS coordination actions route through the P2 ALS branch by `id: "als_intercept"`.
- 64 remaining actions route through evidence dictionaries.

**Summary by scenario (96 total critical actions):**

| Scenario | Total | PRE_CREDITED | P2 → ALS branch | DONE_EVIDENCED | EVALUATE_RISK |
|---|---:|---:|---:|---:|---:|
| adult_acs_01_stemi | 7 | 1 | 0 | 6 | 0 |
| adult_cardiac_arrest_01_bls | 3 | 1 | 0 | 2 | 0 |
| newborn_resus_01_nrp | 3 | 1 | 0 | 2 | 0 |
| peds_ams_tox_01 | 7 | 2 | 1 | 4 | 0 |
| peds_anaphylaxis_01 | 5 | 2 | 1 | 2 | 0 |
| peds_asthma_01 | 7 | 2 | 0 | 5 | 0 |
| peds_cardiac_arrest_01_bls | 3 | 1 | 0 | 2 | 0 |
| peds_croup_01 | 6 | 2 | 1 | 3 | 0 |
| peds_diabetic_emergency_01 | 7 | 2 | 0 | 5 | 0 |
| peds_febrile_seizure_01 | 8 | 2 | 0 | 6 | 0 |
| peds_syncope_01 | 6 | 1 | 0 | 5 | 0 |
| peds_trauma_01_soft_tissue | 4 | 2 | 0 | 2 | 0 |
| peds_trauma_02_partial_choking | 6 | 2 | 0 | 4 | 0 |
| peds_trauma_03_extremity | 6 | 2 | 0 | 4 | 0 |
| peds_trauma_04_burn | 6 | 2 | 0 | 4 | 0 |
| peds_trauma_05_auto_ped | 6 | 2 | 0 | 4 | 0 |
| peds_trauma_06_handlebar | 6 | 2 | 0 | 4 | 0 |
| **TOTAL** | **96** | **29** | **3** | **64** | **0** |

**PRE_CREDITED = P1 + P3 (29 total):**
- **P1 (`id` in `_SCENE_ENTRY_IDS_CA`):** 17 — scene-entry actions matched by the `id` field in production code.
- **P3 (`scene_entry_credited` flag):** 12 — actions with the `scene_entry_credited: true` flag that route through the pre-credit path.

**P2 (ALS/intercept ID):** 3 — all ALS coordination actions use `id: "als_intercept"` and route to the ALS branch.  
**P4 EVALUATE risk:** 0 for the current 17-scenario set.

> **Audit note:** An early draft of this audit read `ca.get("action_id")` instead of `ca.get("id")` and incorrectly reported P1=0 with 3 EVALUATE_RISK items. The production adjudicator reads the `id` field. Re-running with the correct field name confirms 17 P1-PRE_CREDITED, 0 EVALUATE_RISK.

**ALS coordination note (not an EVALUATE risk):**

The three ALS coordination actions are deterministically routed by `id: "als_intercept"`. ALS co-dispatch is not scenario-authored content; it is derived from the active agency configuration (`agency.als_dispatch.auto_dispatched` or `agency.als_dispatch.co_dispatched`) during scenario adaptation. Scenario and call-type ALS request checklist items should use `applicable_if: { "als_codispatched": false }` rather than overlay suppression or scenario-local grace flags.

| Scenario | Description | Current route | Grace source |
|---|---|---|---|
| peds_ams_tox_01 | Confirm ALS involvement when indicated by active agency configuration | P2 via `id: "als_intercept"` | Agency-derived `als_codispatched` applicability |
| peds_anaphylaxis_01 | Confirm ALS involvement when indicated by active agency configuration | P2 via `id: "als_intercept"` | Agency-derived `als_codispatched` applicability |
| peds_croup_01 | Confirm ALS involvement when indicated by active agency configuration | P2 via `id: "als_intercept"` | Agency-derived `als_codispatched` applicability |

No evidence dict is needed for these actions because they do not reach the P4 evidence fallback.

---

### B2 — Fix P1/P3: scene entry EVALUATE → LIKELY_MISSED

*(Unchanged from original plan)*

**Additional guard (from Codex feedback):** When scene entry is absent on a session that has already completed scoring (i.e., `ended_at` is set), this may indicate a session-state defect rather than a learner miss. Add a diagnostic log so these can be distinguished:

```python
if _ca_id in _SCENE_ENTRY_IDS_CA:
    if _se_recorded:
        _ca_tag = "PRE_CREDITED"
    else:
        if getattr(session, "ended_at", None):
            _log.warning(
                "ai.debrief.scene_entry_absent_on_completed_session",
                session_id=session.id,
                action_id=_ca_id,
            )
        _ca_tag = "LIKELY_MISSED"
```

Same pattern for P3 (`scene_entry_credited` flag).

**Checklist:**
- [x] P1 path: `EVALUATE` → `LIKELY_MISSED` with diagnostic log
- [x] P3 path: same
- [x] Tests: se recorded → PRE_CREDITED; se absent, session not ended → LIKELY_MISSED; se absent, session ended → LIKELY_MISSED + warning log
- [x] Calibration fixture 7 (no scene entry) passes with `LIKELY_MISSED`

---

### B3 — Fix P2: ALS EVALUATE with checklist check

*(Unchanged from original plan)*

**Checklist:**
- [x] ALS branch checks `_checklist_done_ca()` before falling to `LIKELY_MISSED`
- [x] Calibration fixture 8 (ALS auto-dispatch) passes with `ALS_GRACE`

---

### B4 — Require evidence metadata on all critical actions

*(Unchanged from original plan)*

**Checklist:**
- [x] All P4 fallback actions updated with `evidence` dicts in scenario JSONs
- [x] `validate_scenario()` warns on actions without `evidence` field
- [x] P4 fallback log warning added in code
- [x] Full debrief fixture test: zero `EVALUATE` tags confirmed
- [x] SCORE-02 updated in hardening plan

---

## Group C — SCORE-01: Deterministic Corroboration

**Reframed from original plan based on Codex feedback.** The goal is not to make the deterministic path "as good as" the LLM prepass — it is to make it more reliable for the claims it can handle confidently, and explicitly conservative on everything else.

**Core policy shift:**
- Deterministic evidence matching first — match claim types against DB records directly
- Conservative extraction — only extract high-confidence claim types (interventions applied, vital types, demographics); do not attempt to extract all claim types the LLM handled
- No deduction unless high confidence — ambiguous or unclear claims produce no deduction
- Ambiguous → silence, not penalty — if the extractor cannot confidently classify a claim, it does not flag it
- Structured DMIST entry remains the correct long-term fix — the deterministic prepass is a better interim path, not a permanent solution

**Group C acceptance rule (approved):**

> Deterministic corroboration may under-flag ambiguous claims, but it must not over-flag supported claims.

For clinical defensibility, false positives — flagging a claim that is actually supported by the run — are more damaging than missing a low-confidence documentation issue. Conservative extraction policy is the correct instinct. When in doubt, do not flag.

**Do not start Group C until:**
- Groups A and B are complete and passing
- Calibration fixtures 1–15 are authored and passing against current code as baseline
- The claim extraction design (C1) has been reviewed and approved separately before C2 is coded

---

### C1 — Claim extraction design (review gate)

**What:** Define the claim types the deterministic extractor will handle, write the extraction rules, and get design approval before any C2 code is written.

**Claim types in scope (high-confidence only):**

| Claim type | Example | Extraction approach | Evidence source |
|---|---|---|---|
| Intervention applied | "administered albuterol" | Pattern match against vocabulary label set | `Intervention.intervention_key` / label |
| Intervention method | "via nasal cannula" | Pattern match against delivery-method vocabulary | `Intervention` label cross-check |
| Vital sign type present | "HR 96", "SpO2 94%" | Numeric + unit extraction | `SessionFinding` vital type set |
| Patient demographics | "4-year-old male, 18kg" | Age/sex/weight extraction | Scenario `patient` block |

**Claim types out of scope for this version (too ambiguous for confident deterministic extraction):**
- Clinical response language ("work of breathing improved", "calm environment maintained")
- Transport or handoff details that are not directly evidenced
- Differential reasoning or clinical assessment language

**Conservative deduction policy:**
- A claim is flagged only when the extracted entity is unambiguously absent from the evidence records
- Paraphrases that are clinically equivalent are not flagged — this requires an intervention equivalence map
- When extraction produces a low-confidence match (ambiguous phrasing), the claim is not flagged

**Intervention equivalence map design (approved):**
Paraphrase patterns live in `app/scenarios/vocabulary.py` as a separate top-level dict — not embedded in the current `INTERVENTIONS: dict[str, str]` which is `str -> str` and would require a broad refactor to enrich:

```python
# In vocabulary.py — keyed by stable intervention ID
INTERVENTION_PARAPHRASE_PATTERNS: dict[str, list[str]] = {
    "albuterol_svn": ["albuterol", "breathing treatment", "nebulizer", "svn", "neb"],
    "o2_nrb": ["non-rebreather", "nrb", "high-flow oxygen", "15l"],
    # ...
}
```

This keeps vocabulary ownership centralized without forcing a broader INTERVENTIONS dict refactor. Migrate `INTERVENTIONS` to richer metadata in a later pass if needed.

**DMIST segmentation approach:**
Accept imperfect segmentation. Use header keyword detection (`"D:"`, `"Demographics:"`, `"I:"`, `"Interventions:"`, etc.) as a best-effort segmentation, but apply the full claim type extractors to the entire document as a fallback when segmentation is uncertain. Do not penalize for claims that appear in the "wrong" section — only penalize for claims that cannot be matched to evidence regardless of section.

**Design review checklist (before C2):**
- [x] Claim types in scope documented with positive and negative test examples
- [x] Intervention equivalence map design reviewed and approved
- [x] DMIST segmentation approach reviewed and approved
- [x] Conservative deduction policy written into `app/corroboration.py` module docstring
- [x] Design doc / PR description reviewed before coding begins

---

### C2 — Evidence matcher implementation

**File:** `app/corroboration.py` (new module)

#### Interface decision (approved: Option A — dataclasses + adapter)

The module uses structured dataclasses as its public API. A separate adapter converts
`CorroborationResult` to the existing `prepass_result` dict shape that
`_build_evidence_packet()` already reads. This keeps the deterministic module clean
and avoids coupling the new design to the old LLM dict schema.

```python
@dataclass
class UnsupportedClaim:
    document: str           # "dmist" | "narrative"
    component: str          # DMIST letter (D/M/I/S/T) or CHART letter (C/H/A/R/T)
    claim: str              # exact matched text span
    reason: str             # deterministic explanation
    claim_type: str         # "intervention_not_applied" | "vital_not_assessed" | "demographic_mismatch"
    confidence: str         # "high" | "medium" — only "high" appears in unsupported lists

@dataclass
class CorroborationResult:
    available: bool
    dmist_unsupported: list[UnsupportedClaim]      # high-confidence only
    narrative_unsupported: list[UnsupportedClaim]  # high-confidence only
    method: str             # "deterministic"
    ambiguous_count: int    # medium-confidence detections: logged, never deduct

def check_documentation_claims(
    *,
    dmist_text: str,
    narrative_text: str,
    applied_intervention_ids: list[str],   # stable IDs from vocabulary.INTERVENTIONS
    assessed_vital_types: set[str],        # vital types the student actually assessed
    patient: dict,                         # scenario patient block (age, sex, weight_kg)
) -> CorroborationResult:
    ...

def to_prepass_result(result: CorroborationResult) -> dict:
    """Adapter: convert CorroborationResult to the prepass_result dict shape
    that _build_evidence_packet() reads during shadow mode."""
    return {
        "available": result.available,
        "dmist_unsupported": [
            {"component": c.component, "claim": c.claim, "reason": c.reason}
            for c in result.dmist_unsupported
        ],
        "narrative_unsupported": [
            {"chart_element": c.component, "claim": c.claim, "reason": c.reason}
            for c in result.narrative_unsupported
        ],
    }
```

#### Passive vitals exemption (approved)

Define in `app/corroboration.py` — this is documentation-corroboration policy, not global vocabulary:

```python
# Vital types that may be passively observed from monitoring without a formal
# assessment interaction. Claims for these types are never flagged as
# vital_not_assessed even when absent from SessionFinding records.
PASSIVELY_MONITORED_VITAL_TYPES: frozenset[str] = frozenset({"spo2"})
```

#### Coverage boundary (required in module docstring before first line of C2 code)

```
The deterministic corroborator intentionally under-flags.
It adjudicates only high-confidence claim types:
  - Interventions applied (matched via vocabulary.INTERVENTION_PARAPHRASE_PATTERNS)
  - Vital sign types actually assessed (matched via SessionFinding records)
  - Patient demographics (age, sex, weight matched against scenario patient block)

It does NOT currently adjudicate:
  - Response-to-treatment claims ("work of breathing improved")
  - Environmental or positioning language ("kept upright in mom's arms")
  - Nuanced assessment or clinical reasoning claims
  - Transport or handoff details not directly evidenced
  - Intervention method variations not in INTERVENTION_PARAPHRASE_PATTERNS

Ambiguous claims do not deduct — they increment ambiguous_count only.
False positives (flagging a supported claim) are more damaging than false negatives.
When in doubt, do not flag.
```

Only claims with `confidence: "high"` are included in `dmist_unsupported` and
`narrative_unsupported`. Medium-confidence detections are counted in `ambiguous_count`
for observability but do not deduct.

**Checklist:**
- [x] `UnsupportedClaim` and `CorroborationResult` dataclasses defined
- [x] `PASSIVELY_MONITORED_VITAL_TYPES` constant defined
- [x] Coverage boundary written into module docstring (copy template above verbatim)
- [x] Intervention claim extractor (using `vocabulary.INTERVENTION_PARAPHRASE_PATTERNS`)
- [x] Intervention evidence matcher (paraphrase → ID → check against applied_intervention_ids)
- [x] Vital sign type claim extractor (HR, RR, BP, GCS, temp, BG — not SpO2)
- [x] Vital evidence matcher (vital type claimed → check against assessed_vital_types)
- [x] Demographic claim extractor (age, sex, weight from DMIST text)
- [x] Demographic matcher (against `patient` block)
- [x] `to_prepass_result()` adapter implemented
- [x] Conservative policy enforced: ambiguous → count only, never deduct
- [x] All 15 calibration fixtures pass (`tests/test_corroboration.py`)

---

### C3 — Shadow mode integration and rollout

**Corrected shadow mode policy (from Codex feedback):** Shadow mode is observe-only — it does not affect scoring. The deterministic path runs alongside the LLM prepass, results are logged and compared, but the LLM prepass result is used for scoring until the feature flag is explicitly flipped after fixture validation.

```python
# Shadow mode: run both, use LLM result for scoring, log comparison
_llm_prepass_result = await _run_corroboration_prepass(...)
if settings.shadow_deterministic_corroboration:
    _det_result = check_documentation_claims(...)
    _log.info(
        "ai.corroboration.shadow_comparison",
        llm_flags=len(_llm_prepass_result.get("dmist_unsupported", [])),
        det_flags=len(_det_result.dmist_unsupported),
        agreement=_compare_results(_llm_prepass_result, _det_result),
    )
# Always use LLM result until flag is flipped
_prepass_result = _llm_prepass_result
```

Flip to deterministic only after all three conditions are met:
1. All 15 calibration fixtures pass against the deterministic path
2. At least 20 staging/pilot debrief runs completed across different scenario families — fixture replay alone is not sufficient; real or staging sessions expose messy real-world phrasing that fixtures do not cover
3. Shadow logs have been manually reviewed for false positive rate — deterministic path must not over-flag supported claims (false positives are more damaging than missed low-confidence documentation issues)

Do not flip in broad production until shadow logs are reviewed. Flag flip is an explicit decision, not automatic after reaching session count.

**Checklist:**
- [x] Shadow mode flag `shadow_deterministic_corroboration` in settings (enabled 2026-05-15)
- [x] Shadow logging comparing LLM and deterministic output (`ai.corroboration.shadow_comparison`)
- [x] Feature flag `use_deterministic_corroboration` in settings (default: `False`)
- [x] Log review script: `scripts/review_shadow_corroboration.py` — pipe app logs to get flip readiness report
- [ ] Shadow validation: 20+ sessions, results reviewed (`grep ai.corroboration.shadow_comparison app.log | python3 scripts/review_shadow_corroboration.py`)
- [ ] Flag flipped to deterministic after shadow validation passes
- [ ] LLM prepass function removed after flag is stable
- [ ] SCORE-01 updated in hardening plan

---

### C4 — Validation

*(Unchanged from original plan, calibration fixtures 11–15 are the test cases)*

**Checklist:**
- [x] All 15 calibration fixtures pass with deterministic path
- [ ] Shadow comparison log reviewed and agreement documented
- [ ] `tests/test_evidence_packet.py` no regressions
- [x] `tests/test_corroboration.py` all unit tests pass

---

## Group D — QA/QI Readiness (Deferred)

Tracked in `docs/QAQI_READINESS.md`. Not in scope for this sprint.

| Item | Status |
|---|---|
| Evidence chain rendering | Deferred |
| Structured DMIST entry | Deferred — correct long-term fix for C |
| Professionalism behavioral rubric | Deferred |
| Tier 1 expansion (assessment SessionEvents) | Ongoing per scenario |
| Labeled output structure | Deferred |

---

## Group E — Deterministic Debrief Composer (Phase 8)

**Goal:** Remove the LLM from scored section authorship and static clinical-reference authorship. Clinical Performance and Protocols & Treatment sections are rendered from adjudicated item states and per-item feedback metadata. Condition and treatment reference sections are rendered from authored scenario JSON and protocol references. The debrief LLM call narrows to run-specific coaching only. See `docs/SCORING_ENGINE_ARCHITECTURE.md §13` (target state) and Phase 8 for full design.

**Why:** The current LLM-authored scored sections can mis-bucket gaps (assessment item cited as protocol deduction), over-credit actions, or explain scores inconsistently across identical runs. This is a structural problem — prompt rules that enumerate assessment vocabulary are not stable at 100+ scenarios. The fix is typed inputs and a deterministic renderer.

**Intermediate state (complete as of 2026-05-11):**
- [x] Category-separated evidence blocks: `## CLINICAL_PERFORMANCE_GAPS`, `## PROTOCOL_TREATMENT_GAPS`, `## CLINICAL_PERFORMANCE_CREDITED`, `## PROTOCOL_TREATMENT_CREDITED` — wired in `_format_evidence_packet_for_prompt()`
- [x] `category` field on each classified critical action — sourced from checklist item lookup with flag-based fallback
- [x] Section 4 source constraint: must cite only `## CLINICAL_PERFORMANCE_GAPS`
- [x] Section 7 source constraint: must cite only `## PROTOCOL_TREATMENT_GAPS`
- [x] `_sanitize_protocol_treatment_section()` post-processor as defense-in-depth against section boundary leaks
- [x] Architecture documented: `SCORING_ENGINE_ARCHITECTURE.md §13` (target state), Phase 8, §21 failure mode

---

### E1 — Per-item feedback metadata schema

**What:** Add nullable fields to the in-scenario checklist item schema in `app/checklist.py`: `done_feedback`, `missed_feedback`, `clinical_rationale`, `common_error`. No migration needed — fields are optional until the renderer is active.

**Reference implementation (NASEMSO rubric layer):** The NASEMSO call-type rubric schema (`ems_call_type_rubric.schema.json`) already requires and CI-validates `done_feedback` and `missed_feedback` on every item. Authored rubric files demonstrate the pattern: `respiratory_distress_v1.json`, `pediatric_croup_v1.json`, `hypoglycemia_v1.json`, `head_injury_v1.json`. The field names are intentionally aligned so both layers share the same per-item metadata contract when the renderer is active.

**Checklist:**
- [x] Schema field additions in `ChecklistItem` Pydantic model in `app/checklist.py` (`done_feedback`, `missed_feedback`, `clinical_rationale`, `common_error`)
- [x] `validate_scenario()` warns when `done_feedback`/`missed_feedback` absent on required scenario-overlay items (soft warning, load-time only)
- [x] `SCENARIO_DESIGN_EMS.md` authoring guide updated with field descriptions, rules, and example (§14+)

---

### E2 — Feedback metadata authored for current scenario set

**What:** Author `done_feedback`, `missed_feedback`, `clinical_rationale`, `common_error` for all checklist items across the current 17-scenario set. This is domain-expert work, not engineering work — but it must be done before E3 can go live.

**Critical design note:** `common_error` is the mechanism that replaces scenario-specific prompt guardrails. Today, `_sanitize_protocol_treatment_section()` in `app/ai_client.py` carries a hardcoded vocabulary list to prevent ALS drug references (e.g., racepinephrine) from bleeding into protocol deduction prose. That list must be updated in application code every time a new scenario has a similar overcredit risk. The correct fix is authoring a `common_error` on the relevant checklist item (e.g., `racepinephrine_als` in `peds_croup_01`: `"common_error": "Do not credit ALS medication acknowledgment unless the student explicitly stated racepinephrine is ALS-only in their transcript"`). Once E3 renders from that field, the engine code never needs to know which scenarios have which overcredit risks — the scenario file does. New scenarios with similar risks are handled by authoring, not code changes.

**Checklist:**
- [ ] All items in the 8 pediatric medical scenarios authored
- [ ] All items in the 6 pediatric trauma scenarios authored
- [ ] All items in the 3 adult/newborn scenarios authored
- [ ] Priority: `peds_croup_01` `racepinephrine_als` `common_error` authored first — this is the active sanitizer target. Use "ALS/Paramedic-level" (not "ALS-only") to match current scenario/protocol wording for racepinephrine.
- [ ] Authoring review: clinical rationale consistent with MCA protocol references
- [ ] Regression: calibration fixtures still pass after metadata added

---

### E3 — Section renderer implementation

**What:** Implement `_compose_scored_section(category, item_states, definitions)` that renders a debrief section as structured prose + scored bullet list from adjudicated facts and authored metadata, with no LLM call. Wire for Clinical Performance and Protocols & Treatment. Also implement `_compose_reference_section(scenario, protocol_refs)` to render Condition and Treatment Reference content from authored `debrief.condition_background`, `key_teaching_points`, `common_mistakes`, and protocol references instead of asking the LLM to regenerate static clinical education.

**Checklist:**
- [ ] `_compose_scored_section()` implemented in `app/ai_client.py`
- [ ] Unit tests covering: all-credited, all-missed, mixed partial, missing metadata fallback
- [ ] Renderer output injected into debrief prompt as locked content (LLM receives as read-only context, not a task)
- [ ] Section 4 and Section 7 prompt rules updated: LLM instructed to present the pre-rendered content, not rewrite it
- [ ] `_compose_reference_section()` implemented for current sections 8–9; LLM-generated condition/treatment prose removed from the debrief prompt
- [ ] Full debrief numbering remains contiguous after reference sections are extracted into the Condition / Treatment Reference accordion
- [ ] Calibration fixtures validated: rendered section content matches expected gap coverage
- [ ] Content-boundary regression: scenario/condition/treatment-specific feedback comes from scenario item metadata or protocol references, not hardcoded renderer branches or prompt exceptions
- [ ] `_sanitize_protocol_treatment_section()` **retired** — once `_compose_scored_section()` renders Protocols & Treatment from adjudicated item states and `common_error` metadata, the vocabulary blocklist is redundant. Verify with a croup debrief run: no racepinephrine prose appears in the rendered output without a corresponding `common_error` authored flag. Then remove the sanitizer. Do not leave it active alongside the renderer — split guardrail authority between JSON metadata and engine code is the failure mode this entire effort exists to prevent.

---

### E4 — LLM debrief prompt scope reduction

**What:** Once E3 is active for scored sections and reference sections, reduce the debrief LLM call to coaching-only sections: Patient Overview, What Went Well / What To Improve framing, Key Takeaways, and Reflection Prompts. Static clinical education (condition/pathophysiology/treatment reference) is rendered deterministically from authored JSON/protocol content, not generated by the LLM. Evidence packet passed to LLM is curated, not the full packet.

**Checklist:**
- [ ] Debrief prompt rewritten for coaching-only scope
- [ ] Evidence packet slimmed: LLM receives scored summary + session context, not raw gap lists
- [ ] Token budget reduced accordingly
- [ ] Legacy condition-specific scored-section guardrails removed or downgraded to documented defense-in-depth only after renderer parity is validated
- [ ] `AI_ARCHITECTURE.md §13` updated to reflect actual LLM scope post-Phase 8
- [ ] Calibration fixtures re-validated with new prompt scope

---

## Group F — NASEMSO Call-Type Rubric Integration (Complete — pending local active run)

**Goal:** Wire the NASEMSO call-type rubric layer (`app/rubrics/nasemso/`) into the session scoring pipeline so that call-type rubric items are resolved and composed into the effective checklist at session start, alongside universal base and scenario-overlay items.

**Current state (2026-05-13):** All F1/F2a/F2b/F3 implementation complete. Three call types authored in scenario JSON (`peds_diabetic_emergency_01` → `hypoglycemia`, `peds_croup_01` → `pediatric_croup`, `peds_asthma_01` → `respiratory_distress`). Shadow composition fires on those three scenarios in default mode. Active composition available behind `USE_CALL_TYPE_RUBRIC=true`. 141 scoring/rubric/overlay tests passing, flag-stable. Pre-activation local run with real session data is the only remaining gate.

**Why this is not a simple load step:** The rubric uses abstract `eligible_source_roles` that must be resolved to concrete source strings against the session's deployment context before scoring runs. The overlay architecture (NASEMSO base → state → agency → scenario) is not yet specified; its schema (`ems_call_type_overlay.schema.json`) must be defined before any state or agency content is authored. Until that design is settled, the scoring pipeline should load and compose only the base NASEMSO rubric layer.

---

### F1 — Call-type rubric loader and source role resolver

**What:** Add `load_call_type_rubric(call_type, deployment_context) → list[ChecklistItem]` to `app/scoring_service.py`. This function:
1. Locates the correct rubric file in `app/rubrics/nasemso/` by `call_type`
2. Resolves `eligible_source_roles` to concrete `eligible_sources` lists using the rubric's `source_role_map` and the `deployment_context` key (`"training"` or `"qaqi"`)
3. Returns a list of `ChecklistItem` objects compatible with the existing adjudicator

**Deployment context resolution:** `resolve_context()` already produces the `EffectiveContext`. Add a `deployment_context` field (`"training"` default) so the source role resolver has the correct key.

**Source stamping state (verified 2026-05-13) — must handle before F1 goes live:**

| Abstract role | `training` sources (schema) | Actively stamped by frontend? |
|---|---|---|
| `ems_measured_vital` | `authored_vitals` | ✅ Yes — scene entry and vitals monitor |
| `ems_performed_exam` | `authored_vitals` | ⚠️ No effective path — `authored_vitals` findings carry `finding_type: "vital"`, not `"exam"`. Exam items resolve at Tier 2 via `tier2_patterns`. |
| `caregiver_reported` | `caregiver_reported_history` | ❌ Not stamped — source accepted by backend (`_VALID_FINDING_SOURCES` in `main.py`) but never emitted by `app.js`. Falls to Tier 2. |
| `patient_reported` | `patient_reported_history` | ❌ Not stamped — same status as `caregiver_reported`. Falls to Tier 2. |
| `history_obtained` | `caregiver_reported_history`, `patient_reported_history` | ❌ Neither source is emitted. Falls to Tier 2. |
| `scene_entry_data` | `scene_entry` | ✅ Yes — scene entry popup data is structured and submitted. |

**Consequence for F1:** In training context, `ems_performed_exam`, `caregiver_reported`, `patient_reported`, and `history_obtained` items have no Tier 1 path. They resolve at Tier 2 (transcript pattern match). This is expected and correct interim behavior. `tier2_patterns` are present on all unsafe items. The resolver must not treat missing Tier 1 sources as an error — log a debug trace at session start listing which abstract roles have no concrete sources in the current training context.

**Long-term exam source gap:** `ems_performed_exam` currently has no effective Tier 1 training source even after stamping is wired. The long-term fix is a dedicated `student_stated_exam` source emitted when a student announces a structured exam finding (e.g., "I listen to breath sounds — decreased on the right"). Until that UI exists, `ems_performed_exam` items should carry `tier2_patterns` targeting structured exam phrases in the transcript.

**Checklist:**
- [x] `load_call_type_rubric()` implemented — `app/rubric_loader.py` (2026-05-13)
- [x] Source role resolution: abstract roles → concrete sources per deployment context (2026-05-13)
- [x] `EffectiveContext` gains `deployment_context` field (default `"training"`) (2026-05-13)
- [x] Call-type detected from scenario metadata (`call_type` field in scenario JSON) — `_shadow_load_call_type_rubric()` in `scoring_service.py` (2026-05-13)
- [x] Graceful handling when no rubric exists for the call type (log + skip, not hard error) (2026-05-13)
- [x] Debug trace at session start listing resolved abstract roles and their concrete source counts — `log_shadow_rubric()` (2026-05-13)
- [x] Unit tests: source role resolution for training and qaqi contexts; missing rubric handling; roles with no training sources resolve to empty list (not error) — `tests/test_rubric_loader.py`, 21 tests (2026-05-13)
- [x] Shadow wired into `adjudicate_and_persist()` via `_shadow_load_call_type_rubric()` — logs trace, does not affect scores (2026-05-13)

**Design note (confirmed during implementation):** The loader resolves roles to concrete sources as specified in the rubric source_role_map. The `authored_vitals`-for-exam semantic gap (authored_vitals findings carry `finding_type="vital"`, not `"exam"`) is a **scoring engine** concern, not a loader concern. The loader correctly reports `authored_vitals` as a resolved source for `ems_performed_exam`; Tier 1 match failure happens at adjudication time when the engine filters by `finding_type`. The correct test for this layer is that `finding_type="exam"` items using `ems_performed_exam` must have `tier2_patterns` as their effective fallback — which is tested and enforced.

---

### F2 — Compose call-type rubric items into effective checklist

**What:** Update `adjudicate_and_persist()` to include call-type rubric items in the effective checklist, with `provenance: "call_type_rubric"`. Items are added after base rubric items and before scenario-specific overlay items.

**Checklist:**
- [x] `adjudicate_and_persist()` calls `load_call_type_rubric()` and merges result into effective checklist — `compose_active_checklist()` in `rubric_loader.py`, wired into F2b path (2026-05-13)
- [x] `provenance` field on each item set to `"call_type_rubric"` — hardcoded in `_rubric_item_to_checklist_item()` (2026-05-13)
- [x] Scenario overlay can suppress or modify a call-type item via explicit overlay ops with governance fields — `ems_call_type_overlay.schema.json`, enforced in F3 (2026-05-13)
- [ ] Calibration fixtures updated or new fixtures added for at least one call type with rubric coverage — deferred; local active run with real session data is the current gate
- [x] Tests confirm call-type items appear with correct `provenance` — `test_active_checklist_items_have_call_type_rubric_provenance` in `test_scoring_service.py` (2026-05-13)

**Denominator change note (pre-activation release note):** When `USE_CALL_TYPE_RUBRIC=true`, the effective checklist gains applicable call-type rubric items. This increases the maximum score (denominator) for any scenario with a matching `call_type`. The increase is deterministic and predictable: only items with `applicable_levels` including the provider's level are added; Paramedic/AEMT-only items are excluded from EMT sessions. Instructors should expect raw and percentage scores to shift when comparing pre- and post-activation session runs. This is expected — the denominator change reflects items that were previously unscored, not a scoring regression. `call_type_item_count` and `level_excluded_item_count` in `shadow_composition` (or `overlay_audit` in active mode) document exactly which items were added and which were excluded, providing an auditable explanation for the shift.

---

### F3 — Overlay schema definition (prerequisite for state/agency content)

**What:** Define `ems_call_type_overlay.schema.json` with four operations: `add_item`, `modify_item` (point value, required, applicable_levels), `suppress_item` (by ID), `add_to_item` (append tier2_patterns or evidence_requirements). This schema must exist before any state or agency rubric content is authored — without it, overlay files will silently diverge in structure.

**Checklist:**
- [x] `ems_call_type_overlay.schema.json` defined and committed to `app/rubrics/nasemso/` (2026-05-13)
- [x] Overlay validator in `tests/test_call_type_overlay_schema.py` — 19 tests, 11 negative (2026-05-13)
- [x] Example overlay `app/rubrics/nasemso/examples/mi_hypoglycemia_state_overlay.json` — all four ops illustrated (2026-05-13)

**Governance design:**
- `reason` and `protocol_ref` are required on every operation (cannot be omitted or empty)
- `approved_by` is required at the overlay file level whenever any `suppress_item` op is present
- `modify_item` only allows `point_value`, `required`, `applicable_levels` — structural changes (description, evidence_requirements, feedback) are forbidden in overlays and must be made in the base rubric
- `suppress_item` of a non-existent base item fails validation (prevents silently targeting renamed IDs)
- `add_item` IDs must not collide with any NASEMSO base item ID
- All ops are intended for audit trail recording even when superseded by higher-precedence overlays (precedence: scenario > agency > state > nasemso_base)

---

## Full Implementation Checklist

### Pre-work: Calibration Fixtures
- [x] `tests/fixtures/scoring/` directory created
- [x] Fixtures 1–10 authored (baseline before Group A/B)
- [x] `tests/test_scoring_fixtures.py` runner written
- [x] All fixtures pass against current code

### Group A
- [x] **A1** — Scenario JSON audit complete; exemptions and missing fields resolved
- [x] **A1** — `_validate_debrief_content()` in `vocabulary.py`
- [x] **A1** — Runtime guard in `evaluate_and_generate_debrief()`
- [x] **A1** — Tests passing; calibration fixtures unaffected
- [x] **A2** — `_SUBSCORE_RANGES` with corrected values
- [x] **A2** — Range check with ERROR log and authoritative fallback path
- [x] **A2** — Tests passing; calibration fixtures unaffected
- [x] **A3** — SCORE-05 closed in hardening plan; `AI_ARCHITECTURE.md` corrected

### Group B
- [x] **B1** — Audit table complete
- [x] **B2** — P1/P3 fixed with diagnostic log; calibration fixture 7 passes
- [x] **B3** — P2 fixed; calibration fixture 8 passes
- [x] **B4** — Evidence dicts added; authoring validator rule added; zero EVALUATE confirmed
- [x] SCORE-02 closed in hardening plan

### Group C (after fixtures 11–15 authored)
- [x] **C1** — Design reviewed and approved before coding
- [x] **C2** — `app/corroboration.py` implemented; all corroboration fixture/unit tests pass
- [x] **C3** — Shadow mode wired (flags + observe-only logging complete)
- [ ] **C3** — Shadow validation, flag flip, and LLM prepass retirement pending
- [ ] **C4** — Full regression clean
- [ ] SCORE-01 closed in hardening plan

### Group E — Deterministic Debrief Composer (Phase 8)
- [x] Category-separated evidence blocks wired in `_format_evidence_packet_for_prompt()` (2026-05-11)
- [x] `category` field on classified critical actions (2026-05-11)
- [x] Section 4 and Section 7 source constraints (2026-05-11)
- [x] `_sanitize_protocol_treatment_section()` defense-in-depth (Codex, 2026-05-11)
- [x] Architecture documented in `SCORING_ENGINE_ARCHITECTURE.md` Phase 8 and §21 (2026-05-11)
- [x] NASEMSO call-type rubric schema requires `done_feedback`/`missed_feedback` and CI-validates them (2026-05-13) — reference implementation for E1
- [ ] **E1** — Feedback metadata schema added to `ChecklistItem` in `app/checklist.py`
- [ ] **E2** — Metadata authored for all 17-scenario checklist items
- [ ] **E3** — `_compose_scored_section()` renderer implemented and wired
- [ ] **E4** — LLM debrief prompt reduced to coaching-only scope

### Group F — NASEMSO Call-Type Rubric Integration
- [x] Schema authored: `ems_call_type_rubric.schema.json` (2026-05-13)
- [x] Validator: `tests/test_call_type_rubric_schema.py`, 22 tests incl. 6 negative validator tests (2026-05-13)
- [x] Rubric files: `respiratory_distress_v1.json`, `pediatric_croup_v1.json`, `hypoglycemia_v1.json`, `head_injury_v1.json` (2026-05-19)
- [x] Evidence source typing: `SessionFinding.source`, `eligible_source_roles` on match specs, source filter in `scoring_service.py` (2026-05-13)
- [x] **F1** — `load_call_type_rubric()`, source role resolver, shadow wired into `adjudicate_and_persist()`; `EffectiveContext.deployment_context`; `tests/test_rubric_loader.py` 21 tests (2026-05-13)
- [x] **F2a** — Shadow composition (`compose_shadow_checklist()`): conflict detection, added_items, all_logic, empty_role, level_excluded, suspected_duplicate traces; report persisted in `checklist_states['shadow_composition']`; 9 composition tests added (2026-05-13)
- [x] **F3** — Overlay schema (`ems_call_type_overlay.schema.json`) defined; all four ops (suppress_item, modify_item, add_to_item, add_item) with mandatory governance fields; `tests/test_call_type_overlay_schema.py` 19 tests incl. 11 negative; example `examples/mi_hypoglycemia_state_overlay.json` (2026-05-13)
- [x] **F2b** — Scored composition behind `use_call_type_rubric` flag (default off); `compose_active_checklist()` with overlay audit; `requirement_logic`/`tier1_matches` added to `ChecklistItem`; AND adjudication in `_try_tier1_all()`; 12 F2b tests (2026-05-13)
- [x] **Tier 2 guard** — `requirement_logic="all"` items have `allowed_tiers=[1]` (primary guard in converter) and defense-in-depth `_is_all_logic` check in `adjudicate()`; 4 guard tests in `test_scoring_service.py` (2026-05-13)
- [x] **Scenario contract** — `call_type` field authored in `peds_diabetic_emergency_01`, `peds_croup_01`, `peds_asthma_01`; validated against rubric file existence by `validate_scenario()`; clinical-scenario warning if absent; `get_known_call_types()` in `rubric_loader.py` (2026-05-13)
- [x] **Level exclusion fix** — Shadow `compose_shadow_checklist()` now matches active `compose_active_checklist()`: level-excluded items tracked in `level_excluded_items`, not inflated into `added_items` or `composed_item_count` (2026-05-13)
- [x] **Shadow validation matrix** — `scripts/validate_shadow_composition.py` covers all three call types; all checks green (no duplicate IDs, correct all-logic counts, correct level exclusions) (2026-05-13)
- [x] **F2b behavioral tests** — 6 tests in `test_scoring_service.py`: shadow returns report for authored call_type, skips when absent, skips unknown; `_diagnostic_only` set by caller not function; `provenance="call_type_rubric"` on composed items; `overlay_audit=[]` without ops; level-excluded items absent from active checklist (2026-05-13)
- [x] **Local active run gate — run 1 complete** (2026-05-14, `peds_diabetic_emergency_01`): denominator expanded correctly (Clinical Performance 68→93, Protocols 10→16, Scope 10→14); `reassess_bgl_loc` all-logic guard confirmed working; three integration issues found — flag stays off until resolved (see below)
- [x] **Integration cleanup — run 1 (post-overlay, 2026-05-14):** 8 structural/semantic duplicates suppressed via `app/rubrics/nasemso/overlays/peds_diabetic_emergency_01.json`; post-overlay run confirmed no contradictions; rubric shows clean "General Assessment (NREMT Rubric)" + "Call Specific" sections
- [ ] **Integration cleanup — remaining:**
  - [x] Suppress structural duplicates (scene safety, general impression, LOC, airway) — done via overlay ops
  - [x] Fix `reassess_bgl_loc` LOC evidence path — changed LOC sub-requirement from `finding_type=exam, ems_performed_exam` to `finding_type=vital, ems_measured_vital` in `hypoglycemia_v1.json`; root cause was GCS stored as vital (not exam) in `authored_vitals`; aligns with established codebase pattern (`ems.medical.treatment_response`); 141 scoring tests pass, shadow matrix still green (2026-05-14)
  - [ ] Re-run `peds_diabetic_emergency_01` with `reassess_bgl_loc` fix to confirm it credits when student asks for repeat GCS/BGL after oral glucose
  - [x] Decide on `als_request_if_indicated`: keep the item required when ALS is clinically indicated, but gate it with `applicable_if: { "als_codispatched": false }` so agency co-dispatch policy suppresses it through adapted scenario context rather than scenario overlay content
  - [ ] Semantic duplicate migration: BGL check, swallow assessment, oral glucose still owned by both scenario JSON items and suppressed call-type items — remove from scenario JSON and let call-type rubric own them once evidence paths fully confirmed
  - [ ] Runs 2 and 3 (`peds_croup_01`, `peds_asthma_01`) — create overlays if duplicate patterns found

---

## Approved Decisions

All open questions resolved. Decisions are incorporated inline in the relevant sections above. Summary for reference:

| # | Decision | Resolution |
|---|---|---|
| A1 — Exemption | `"debrief_exempt": true` in scenario JSON | Approved. Applies to orientation, tutorials, future non-clinical scenarios. Never hardcoded by ID. |
| A1 — Severity | Three-phase: warning now / hard runtime fail now / load-time error after cutover | Approved. |
| A2 — Dynamic maxima | Pass `subscore_maxima: dict[str, int] | None` into `_extract_required_debrief_subscores()` | Approved. Use actual max from `evaluate_and_generate_debrief()` locals; fall back to global sanity ceiling. |
| B1 — Scope | 17 specific scenario files | Approved. Audit all 17 regardless of live/dev status. |
| C1 — Paraphrase map | Separate `INTERVENTION_PARAPHRASE_PATTERNS` dict in `vocabulary.py` | Approved. Do not embed in current `INTERVENTIONS: dict[str, str]`. |
| C3 — Shadow mode | All 15 fixtures passing + 20 staging/pilot runs + manual log review | Approved. Fixture replay alone is not sufficient. |
