# SCORM Trial → Production Backport Matrix

**How to use this document**

Each row maps one punchlist backport item to: the SCORM commits that implement it, the files those commits touch, porting risk, dependency/ordering constraints, and tests that must pass before the item can be checked off in the punchlist.

An item is **closed** only when production behavior matches the SCORM fix — not when a commit is cherry-picked. Use this matrix alongside `docs/SCORM_TRIAL_PUNCHLIST.md` (acceptance intent) and the referenced SCORM commit diffs (implementation source). The punchlist backport items are the acceptance gates; this matrix is the implementation recipe.

**Production handoff files:** copy `docs/SCORM_TRIAL_PUNCHLIST.md` and `docs/SCORM_BACKPORT_MATRIX.md` into the production repo, then add both files to the production agent guide (`CLAUDE.md` / `AGENTS.md`) so Claude or Codex reads them before starting backport work.

---

## Repository Context

### SCORM trial repo — source of all commits in this document

- **Full path:** `/Users/jonathanfrastaci/Projects/Development/Peds Assessment SCORM`
- **Branch:** `main`
- **Commit range covered:** `f172794` (initial SCORM snapshot) through `6023cdf` (latest as of 2026-07-01)

To view a single commit diff from the SCORM repo:
```bash
git -C "/Users/jonathanfrastaci/Projects/Development/Peds Assessment SCORM" show <hash>
```

To view only the changes to one file in a commit:
```bash
git -C "/Users/jonathanfrastaci/Projects/Development/Peds Assessment SCORM" show <hash> -- <relative-file-path>
```

To diff a file between the SCORM repo and production:
```bash
diff \
  <(git -C "/Users/jonathanfrastaci/Projects/Development/Peds Assessment SCORM" show HEAD:<file>) \
  "/Users/jonathanfrastaci/Projects/Development/EMS Simulator/<file>"
```

### Production repo — target

- **Path:** `/Users/jonathanfrastaci/Projects/Development/EMS Simulator`
- All relative file paths in this document (e.g., `static/js/app.js`, `app/main.py`, `app/scenarios/pediatric/...`) refer to paths that exist in both repos with the same structure unless explicitly noted otherwise.
- Commit hashes listed in this document **do not exist** in the production repo. They must be cherry-picked or manually ported from the SCORM repo.

To run the test suite in the production repo:
```bash
cd "/Users/jonathanfrastaci/Projects/Development/EMS Simulator"
python -m pytest tests/ -q
```

To run a specific test file:
```bash
python -m pytest tests/<test_file>.py -v
```

To generate an Alembic migration after a schema change (required for Item 3):
```bash
cd "/Users/jonathanfrastaci/Projects/Development/EMS Simulator"
alembic revision --autogenerate -m "<description>"
alembic upgrade head
```

---

## SCORM-Skip Rules

Apply these rules consistently when evaluating every commit diff. When a hunk touches any of the following, skip that hunk unless the underlying logic is explicitly noted as production-relevant:

| Skip if it touches | Reason |
|---|---|
| `static/js/scorm.js` | SCORM runtime only |
| `static/js/scorm_adapter.js` | SCORM result adapter only |
| `static/js/scorm_config.js` | SCORM config only |
| `imsmanifest.xml` | SCORM package manifest only |
| `app/routers/scorm.py` — SCORM session/completion paths | SCORM API surface; evaluate individual hunks that touch shared session logic |
| `scripts/reset_scorm_learner.py` | SCORM-specific learner reset utility |
| `PEDS_ASSESSMENT/` docs | SCORM pilot docs; not needed in production |
| Cache-buster version strings tied to SCORM package builds | Use production's own cache-bust convention instead |

**When a SCORM commit also touches a production file**, extract only the hunks for the production file. Do not cherry-pick the whole commit unless every file it touches is production-applicable.

---

## Porting Approach

For each item:

1. Run `git show <hash>` in the SCORM repo for each listed commit in chronological order.
2. For each changed file, apply the "Port?" column decision from the table below.
3. For `Evaluate` entries: read the diff, check whether production has the same code path, then decide.
4. After applying all commits for an item, run the listed tests in the production repo. All must pass before moving to the next item.
5. Run the live browser verification steps where noted — these catch things tests cannot.
6. Update the `Production status` field for the item from `[ ]` to `[x]` only after browser verification passes.

---

## Status Legend

| Symbol | Meaning |
|---|---|
| `[ ]` | Not started |
| `[~]` | In progress |
| `[x]` | Verified in production |
| `[s]` | Skipped — production already differs or fix does not apply |

---

## Item 1 — Backport SCORM pilot deterministic action-routing fixes

**Punchlist severity:** High  
**Punchlist section:** High › "Backport SCORM pilot deterministic action-routing fixes"

| Field | Detail |
|---|---|
| SCORM commits | `7d5ba96`, `791f729`, `9432200`, `be1c5fa` |
| Production status | `[ ]` |

**Files touched**

| File | What changed | Port? |
|---|---|---|
| `static/js/app.js` | Narrow `_userRequestedAvpu()` to AVPU/LOC language only; route action-menu procedure payloads through intervention matching before chat fallback; route short trauma follow-ups to mechanism history | Yes |
| `app/ai_client.py` | Prompt-side routing changes for procedure and history disambiguation | Yes |
| `app/pediatric_length_based_tape.py` | **New file** — deterministic Michigan length-based tape ranges with agency/state override hook | Yes — create in production |
| `app/scenario_engine.py` | Procedure routing to `applyInterventionAndRecord()` | Yes |
| `app/main.py` | Intervention routing fix | Yes |
| `app/routers/scorm.py` | Minor SCORM wiring only | Evaluate individually |
| `tests/test_patient_disclosure_guardrails.py` | New guardrail tests | Yes |
| `tests/test_scorm.py` | SCORM-specific routing tests | Evaluate |
| `tests/test_session_findings_contract.py` | Session findings contract tests | Yes |

**Porting risk:** HIGH — `app.js` routing changes affect every chat path. `app/pediatric_length_based_tape.py` is a new module dependency. Verify no production routing conflicts before applying.

**Dependencies:** None — can port first.

**Tests to run after porting:**
```bash
python -m pytest tests/test_patient_disclosure_guardrails.py tests/test_session_findings_contract.py -v
```
- Live browser: enter "how bad is the pain?", confirm not misrouted as AVPU; use action menu procedure, confirm treatment evidence recorded; type "how" after a trauma history question, confirm mechanism followup.

---

## Item 2 — Backport scenario progression and persistence hardening

**Punchlist severity:** High  
**Punchlist section:** High › "Backport scenario progression and persistence hardening from SCORM pilot"

| Field | Detail |
|---|---|
| SCORM commits | `e52f411`, `9e83c19`, `9cdc623`, `8780e0c`, `154c43f`, `e55230f`, `9a6dafa`, `ba4950f`, `1743e22`, `ea615c0`, `cb4003a`, `94ced4d`, `9d0049b`, `8dca3e0` |
| Production status | `[ ]` |

**Files touched**

| File | What changed | Port? |
|---|---|---|
| `static/js/app.js` | Orientation gate, CPR completion logic, map node state management, progression display | Yes (non-SCORM hunks) |
| `app/main.py` | Backend progression state, CPR gate | Yes |
| `app/routers/scorm.py` | SCORM-specific node completion, resume state | Evaluate per-commit — SCORM logic only |
| `app/minigame_metadata.py` | Drill metadata | Yes |
| `scripts/reset_scorm_learner.py` | **New file** — SCORM-specific learner reset utility | No — SCORM-only |

**Porting risk:** HIGH — many commits are deeply SCORM-specific (SCORM node completion persistence, SCORM resume state). Must evaluate each commit individually. The CPR gate (`ea615c0`, `ba4950f`, `1743e22`) and backend progression logic apply to production; SCORM navigation state (`9e83c19`, `9cdc623`, `8780e0c`) likely does not.

**Dependencies:** Port after Item 1 (routing must be stable first).

**Tests to run after porting:**
```bash
python -m pytest tests/test_minigame_phase14_cpr_mastery.py tests/test_gamification_regressions.py -v
```
- Live browser: complete Station 1 CPR drill, verify node marked complete; logout/relogin, verify station state persists.

---

## Item 3 — Backport pilot persistence, cache, and re-adjudication safeguards

**Punchlist severity:** High  
**Punchlist section:** High › "Backport pilot persistence, cache, and re-adjudication safeguards"

| Field | Detail |
|---|---|
| SCORM commits | `02bc42a`, `38bc0b4`, `401b8d7`, `b8d26f3`, `d5e30f8`, `66cf692` |
| Production status | `[ ]` |

**Files touched**

| File | What changed | Port? |
|---|---|---|
| `app/main.py` | Lexi chat transcript persistence (`02bc42a`); debrief re-adjudication on relaunch (`b8d26f3`, `d5e30f8`) | Yes |
| `app/models.py` | Schema addition for chat log storage (`02bc42a`) | Yes — requires Alembic migration |
| `app/scoring_service.py` | Timezone-aware timestamp fix for adjudication revisions (`38bc0b4`); rubric version check before debrief cache use (`d5e30f8`) | Yes |
| `static/js/app.js` | Mini-game cache clearing on reset (`401b8d7`) | Yes |
| `app/routers/scorm.py` | SCORM-specific orientation node persistence (`66cf692`) | Evaluate — orientation persistence logic applies; SCORM wrapper does not |
| `tests/test_lexi_chat_logging_contract.py` | **New test file** | Yes |
| `tests/test_scoring_service.py` | Timestamp and rubric version tests | Yes |
| `tests/test_scorm_smoke_package.py` | SCORM smoke tests | Evaluate |

**Porting risk:** MEDIUM-HIGH. `app/models.py` schema change requires an Alembic migration before deployment. `38bc0b4` (timestamp fix) is a clean independent fix. Port `38bc0b4` first since it has no schema dependency.

**Dependencies:** Schema migration must precede `02bc42a` deployment. Sequence:
1. Port `38bc0b4` alone and run scoring tests — no migration needed.
2. Port `app/models.py` change from `02bc42a`, then run `alembic revision --autogenerate -m "add lexi chat log storage"` and `alembic upgrade head`.
3. Port remaining `app/main.py` changes from `02bc42a`, `b8d26f3`, `d5e30f8`.
4. Port `app/scoring_service.py` changes from `d5e30f8`.
5. Port `static/js/app.js` from `401b8d7`.
6. Evaluate and extract `66cf692` orientation logic from `app/routers/scorm.py`.

**Tests to run after porting:**
```bash
python -m pytest tests/test_lexi_chat_logging_contract.py tests/test_scoring_service.py -v
```
- Live browser: complete a scenario, debrief, reset user, relaunch — verify debrief re-adjudicates rather than serving stale cache.

---

## Item 4 — Backport SCORM pilot scoring/progress display consistency fixes

**Punchlist severity:** High  
**Punchlist section:** High › "Backport SCORM pilot scoring/progress display consistency fixes"

| Field | Detail |
|---|---|
| SCORM commits | `aafd307`, `af02ac8`, `c096762` |
| Production status | `[ ]` |

**Files touched**

| File | What changed | Port? |
|---|---|---|
| `app/main.py` | Debrief timeline trusts checklist scoring state, not raw timeline events (`aafd307`) | Yes — clean backend fix |
| `static/js/app.js` | SCORM map progress display fixes (`af02ac8`, `c096762`) | Evaluate — SCORM progress display logic may differ from production map display |
| `tests/test_timeline_scoring_deference.py` | **New test file** | Yes |
| `tests/test_scorm_smoke_package.py` | SCORM smoke | Evaluate |

**Porting risk:** LOW-MEDIUM. `aafd307` is an isolated backend fix that cleanly applies. `af02ac8` and `c096762` touch SCORM-specific progress display paths — evaluate which hunks also drive the production district/map display.

**Dependencies:** None.

**Tests to run after porting:**
```bash
python -m pytest tests/test_timeline_scoring_deference.py -v
```
- Live browser: run scenario, confirm debrief timeline and rubric detail agree (item credited in rubric should not show as missed in timeline).

---

## Item 5 — Backport pilot challenge, XP, and reward rule changes

**Punchlist severity:** High  
**Punchlist section:** High › "Backport pilot challenge, XP, and reward rule changes"

| Field | Detail |
|---|---|
| SCORM commits | `093b0ca`, `0183be6`, `11cfd1c`, `a2ee8e5`, `6e5d180` |
| Production status | `[ ]` |

**Files touched**

| File | What changed | Port? |
|---|---|---|
| `app/main.py` | XP challenge requirement support (`11cfd1c`); immediate XP refresh after awards (`a2ee8e5`) | Yes |
| `app/routers/scorm.py` | SCORM pass challenge criteria, XP gate (`093b0ca`, `0183be6`) | No — SCORM completion contract only |
| `static/js/app.js` | XP chrome top-bar refresh; challenge progress display | Yes (non-SCORM hunks) |
| `static/js/scorm.js` | SCORM XP sync (`6e5d180`) | No — SCORM-specific |
| `tests/test_challenge_drill_requirements.py` | XP challenge requirement tests | Yes |
| `tests/test_gamification_regressions.py` | Gamification regression suite | Yes |

**Porting risk:** MEDIUM. The production-relevant commits are `11cfd1c` and `a2ee8e5`. The SCORM pass-gate commits (`093b0ca`, `0183be6`, `6e5d180`) do not apply to production.

**Dependencies:** None.

**Tests to run after porting:**
```bash
python -m pytest tests/test_challenge_drill_requirements.py tests/test_gamification_regressions.py -v
```
- Live browser: complete a drill, verify XP updates in top chrome immediately without page reload.

---

## Item 6 — Backport SCORM pilot scenario evidence and rubric QA fixes

**Punchlist severity:** High  
**Punchlist section:** High › "Backport SCORM pilot scenario evidence and rubric QA fixes"

This item is the largest and is split into four sub-groups that should be ported in order. Each sub-group has its own risk profile.

---

### 6a — Head injury scenario

| Field | Detail |
|---|---|
| SCORM commits | `f384d58`, `93aaf70`, `4a44a05`, `e894374`, `fbcc83b`, `9b52424`, `400e89e`, `feaa87a`, `8adbb0f`, `08ed9d8`, `86e1f7c` |
| Production status | `[ ]` |

**Files touched**

| File | What changed | Port? |
|---|---|---|
| `app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json` | Scenario JSON — rubric shape, exam findings, demographic scope | Yes |
| `app/rubrics/nasemso/head_injury_v1.json` | Rubric — pupil/neuro/spinal finding keys | Yes |
| `app/main.py` | Structured exam evidence credit, partner-reported finding credit | Yes |
| `app/checklist.py` | Evidence matching for structured exams | Yes |
| `app/ai_client.py` | Prompt changes for neuro/head-injury context | Yes |
| `static/js/app.js` | Structured exam UI, exam menu event emission | Yes |
| `tests/test_timeline_scoring_deference.py` | Head injury timeline tests | Yes |
| `tests/test_scoring_service.py` | Evidence credit tests | Yes |
| `tests/test_patient_disclosure_guardrails.py` | Demographic disclosure guardrail tests | Yes |
| `tests/test_checklist.py` | Checklist matching tests | Yes |

**Porting risk:** HIGH — touches scenario JSON, rubric JSON, and three backend layers. Apply commits in chronological order. Confirm `app/checklist.py` changes are compatible with production checklist version before applying.

**Dependencies:** Item 1 (routing) must be stable. Port 6a before 6b.

---

### 6b — Soft tissue scenario

| Field | Detail |
|---|---|
| SCORM commits | `435f574`, `ae433c2`, `dc3429f`, `a24bae9`, `ab0f350`, `7ae4d9f`, `8c9723d` |
| Production status | `[ ]` |

**Files touched**

| File | What changed | Port? |
|---|---|---|
| `app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json` | Scenario JSON — NEXUS exam finding, spinal applicability, mechanism scoring, demographic disclosure, debrief guardrails | Yes |
| `app/ai_client.py` | Soft tissue debrief evidence alignment, scoring guardrails | Yes |
| `app/main.py` | Demographic disclosure fix for informal patient name prompts | Yes |
| `app/dmist_scoring.py` | Scoring fix | Yes |
| `tests/test_adjudication_gold_standard.py` | Gold standard fixture updates | Yes |
| `tests/test_debrief_renderer.py` | Debrief renderer tests | Yes |
| `tests/test_evidence_packet.py` | Evidence packet tests | Yes |
| `tests/test_scoring_service.py` | Scoring tests | Yes |
| `tests/test_tier2_matchers.py` | Tier 2 pattern tests | Yes |

**Porting risk:** MEDIUM-HIGH — scenario JSON and multiple backend scoring layers.

**Dependencies:** Port after 6a.

---

### 6c — Cross-scenario: spinal/GCS leakage, exam routing, PCR persistence, name capture

| Field | Detail |
|---|---|
| SCORM commits | `b616140`, `ad878ef`, `5bce446`, `104df14`, `dde2890`, `0d19c2b`, `dc76895`, `0910d6b` |
| Production status | `[ ]` |

**Files touched**

| File | What changed | Port? |
|---|---|---|
| `static/js/app.js` | Remove GCS leakage from spinal findings; route authored standard exams before history chat; persist mechanism followups to PCR events | Yes |
| `app/ai_client.py` | Normalize deterministic history speaker formatting; capture known patient names from history map tags | Yes |
| `app/checklist.py` | Spinal exam phrase alignment | Yes |
| `tests/test_patient_disclosure_guardrails.py` | Name capture and spinal tests | Yes |
| `tests/test_checklist.py` | Spinal phrase tests | Yes |

**Porting risk:** MEDIUM — `app.js` changes are function-local; `app/checklist.py` and `app/ai_client.py` changes are targeted. These fixes affect all trauma scenarios, not just soft tissue/head injury.

**Dependencies:** Port after 6b. Must land before running scenario QA matrix.

---

### 6d — Croup, asthma, CPAP blocking, generic trauma flags, debrief notes

| Field | Detail |
|---|---|
| SCORM commits | `f89b8a5`, `33f19c0`, `5d7f264`, `f5e2616`, `6023cdf`, `f0debc6` |
| Production status | `[ ]` |

**Files touched**

| File | What changed | Port? |
|---|---|---|
| `app/scenarios/pediatric/medical/peds_croup_01.json` | Clarify oxygen delivery guidance (`f89b8a5`) | Yes |
| `app/scenarios/pediatric/medical/peds_asthma_01.json` | Refine scoring, vital evidence capture (`33f19c0`) | Yes |
| `app/ai_client.py` | Asthma scoring (`33f19c0`); nontransport and intro debrief notes fix (`f0debc6`) | Yes |
| `app/checklist.py` | Remove erroneous critical flags from generic trauma airway/transport (`f5e2616`, `6023cdf`) | Yes |
| `static/js/app.js` | CPAP blocking for unsupported attempts (`5d7f264`); asthma vital evidence capture (`33f19c0`) | Yes |
| `scripts/fto_feedback_report.py` | Asthma scenario activity display | Evaluate — admin script only |
| `tests/test_checklist.py` | Croup/asthma checklist tests | Yes |
| `tests/test_patient_disclosure_guardrails.py` | CPAP blocking tests | Yes |
| `tests/test_fto_feedback_report.py` | FTO report tests | Evaluate |

**Porting risk:** MEDIUM. Scenario JSON changes are isolated. `5d7f264` (CPAP blocking) adds a frontend unsupported-procedure guard in `static/js/app.js` that applies broadly. `f5e2616` and `6023cdf` remove erroneous critical flags from generic trauma in `app/checklist.py` — verify production generic trauma scenarios use the same checklist inheritance logic.

**Dependencies:** Port after 6c.

---

## Item 7 — Replace markdown-blob FTO debrief with structured report skeleton

**Punchlist severity:** High  
**Punchlist section:** High › "Replace markdown-blob FTO debrief with structured report skeleton"

| Field | Detail |
|---|---|
| SCORM commits | `f26d817`, `472f8b7`, `641e047`, `3fe2d13`, `f2a93d2`, `2f997cd`, `0b700fe`, `8638c97`, `79f15bf` |
| Production status | `[ ]` |

**Files touched**

| File | What changed | Port? |
|---|---|---|
| `app/ai_client.py` | Structured FTO debrief sections, forced section headers, scoring cue alignment, intervention chat tag hardening, trauma followup hardening | Yes |
| `app/main.py` | Authored history tag persistence for scoring; parenthetical speaker followup routing | Yes |
| `static/js/app.js` | FTO section display, feedback section normalization | Yes |
| `scripts/fto_feedback_report.py` | FTO report section display, scenario activity inclusion | Evaluate — admin script |
| `tests/test_debrief_renderer.py` | Debrief renderer tests for structured sections | Yes |
| `tests/test_fto_feedback_report.py` | FTO report tests | Evaluate |
| `tests/test_patient_disclosure_guardrails.py` | Followup routing guardrail tests | Yes |

**Porting risk:** MEDIUM. `app/ai_client.py` changes are the primary delivery mechanism — large prompt-side changes. `app/main.py` history tag persistence changes are backend-only. The `scripts/fto_feedback_report.py` changes are an admin tool and can be deferred if production uses a different reporting path.

**Dependencies:** Port after Item 6 (scenario evidence must be stable before debrief quality is validated).

**Tests to run after porting:**
```bash
python -m pytest tests/test_debrief_renderer.py tests/test_patient_disclosure_guardrails.py -v
```
- Live browser: run croup scenario with missed positioning, confirm FTO debrief shows correct section structure and missed item is named in the correct section (not cross-contaminated).

---

## Item 8 — SCORM pilot result adapter wiring

**Punchlist severity:** High  
**Punchlist section:** High › "SCORM pilot — result adapter wiring"

| Field | Detail |
|---|---|
| SCORM commits | `51c19e3`, `621f8f0`, `a0a21dc`, `f172794` |
| Production status | `[ ]` |

**Files touched — port evaluation**

| File | What changed | Port? |
|---|---|---|
| `static/js/scorm.js` | SCORM runtime, duplicate launch scoping | No — SCORM-specific |
| `static/js/scorm_adapter.js` | **New file** — SCORM result adapter | No — SCORM-specific |
| `static/js/scorm_config.js` | SCORM config | No — SCORM-specific |
| `app/routers/scorm.py` | SCORM session auth, result submission API | No — SCORM-specific |
| `app/auth.py` | Auth improvements made alongside SCORM wiring | **Audit** — auth fixes may apply |
| `app/models.py` | Model additions for SCORM session tracking | **Audit** — evaluate which additions are general vs SCORM-only |
| `app/database.py` | Session handling | **Audit** |
| `static/css/style.css` | Layout changes for SCORM new-window mode | **Audit** — desktop layout fixes may apply to production |
| `static/index.html` | HTML additions for SCORM | **Audit** — evaluate which elements are SCORM-specific |
| `imsmanifest.xml` | SCORM package manifest | No — SCORM-only |
| `tests/test_scorm.py` | SCORM-specific tests | No — SCORM-only |
| `tests/test_scorm_smoke_package.py` | SCORM smoke tests | No — SCORM-only |

**Porting risk:** HIGH — but mostly inapplicable. Production does not use the SCORM result adapter. The actionable subset is: audit `app/auth.py`, `app/models.py`, `app/database.py`, and `static/css/style.css` for production-relevant changes that were bundled into these commits.

**Dependencies:** Audit `app/auth.py` and `app/models.py` first, before Item 3 (which also touches `app/models.py`), to avoid conflicts.

**Tests to run after auditing:**
```bash
python -m pytest tests/ -k "auth" -v
```

---

## Item 9 — Backport post-audit SCORM pilot fixes

**Punchlist severity:** High  
**Punchlist section:** High › "Backport post-audit SCORM pilot fixes"

This item covers fixes made after the punchlist audit (post-`843ba6e`). Sub-grouped by risk and independence.

---

### 9a — Debrief missed-points contrast (CSS)

| Field | Detail |
|---|---|
| SCORM commits | `3966b62`, `b60c1dc`, `1fca90f`, `a1d5029`, `6a78d73`, `1d822bc` |
| Key files | `static/css/style.css`, `static/index.html`, `static/js/app.js` |
| Production status | `[ ]` |
| Porting risk | LOW — CSS and inline style only |

Six iterations were required to force missed-points text to be readable over dark debrief surfaces. Apply all six commits (or take the final result from `1d822bc`) — the final state is the one to target. Verify in production by running a scenario with a missed item and confirming the missed-points section text is readable in both the in-scenario debrief and the history replay modal.

---

### 9b — History endpoint made read-only

| Field | Detail |
|---|---|
| SCORM commits | `7792a21` |
| Key files | `app/main.py` |
| Production status | `[ ]` |
| Porting risk | LOW — isolated backend change |

Prevents state mutation through the scenario history endpoint. Clean `app/main.py` change. Port independently; verify production history endpoint is read-only after applying.

---

### 9c — History loading resilience

| Field | Detail |
|---|---|
| SCORM commits | `7653d0b`, `4b1a156` |
| Key files | `static/js/app.js` |
| Production status | `[ ]` |
| Porting risk | LOW |

Frontend error handling for history load failures plus a cache-buster version bump. Port the error-handling hunk from `7653d0b`; the `4b1a156` cache-buster string is SCORM-specific and should use production's existing cache-bust mechanism instead.

---

### 9d — SCORM scenario score normalization

| Field | Detail |
|---|---|
| SCORM commits | `f0cfbc2` |
| Key files | `static/js/app.js`, `tests/test_scorm.py` |
| Production status | `[ ]` |
| Porting risk | LOW-MEDIUM — frontend SCORM/progression score-display change |

Score normalization fix for SCORM reporting/progression display. Evaluate whether production uses the same `static/js/app.js` result-summary normalization path; if not, keep this as SCORM-package-only. The commit does not contain backend DMIST or diabetic scenario JSON changes.

**Tests to run after porting:**
```bash
python -m pytest tests/test_scorm.py -v
```

---

## Item 10 — Audit treatment-response vitals trending across all scenarios

**Punchlist severity:** High  
**Punchlist section:** High › "Audit treatment-response vitals trending across all scenarios"

| Field | Detail |
|---|---|
| SCORM commits | Diabetic scenario JSON changes are in `3fe2d13` and the initial SCORM snapshot, not `f0cfbc2`; verify whether any treatment-response logic lives in `static/js/app.js` or shared vitals code before porting |
| Key files | `app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json`; all scenarios with `post_treatment` profiles |
| Production status | `[ ]` |

**Action required before porting:** Audit all scenarios in `app/scenarios/pediatric/` for `post_treatment` profiles and confirm each produces the expected vitals change after the required intervention. For diabetic BGL trending specifically, diff `3fe2d13` and any related runtime vitals code rather than `f0cfbc2`; this is a verification task as much as a porting task.

**Tests to run:**
```bash
python -m pytest tests/test_scoring_service.py -v -k "diabetic or vitals or treatment"
```
- Live browser: administer oral glucose in diabetic scenario, confirm BGL trends in reassessment vitals display.

---

## Recommended Port Order

Port in this sequence to minimize conflict and allow regression testing between steps. Run `python -m pytest tests/ -q` after each item before proceeding.

1. **Item 8 audit** — Read `app/auth.py`, `app/models.py`, `app/database.py` diffs from commits `51c19e3 621f8f0 a0a21dc f172794` before touching those files in later items. No code change yet — just establish a baseline understanding of what was added.
2. **Item 4** — Timeline scoring deference (`aafd307`) — isolated `app/main.py` fix, no dependencies.
3. **Item 9b** — History endpoint read-only (`7792a21`) — isolated `app/main.py` change.
4. **Item 9c** — History resilience (`7653d0b`) — `app.js` error handling only; skip the cache-buster string from `4b1a156`.
5. **Item 1** — Deterministic action routing (`7d5ba96 791f729 9432200 be1c5fa`) — creates `app/pediatric_length_based_tape.py`, establishes routing foundation for all later items.
6. **Item 3** — Persistence/cache/re-adjudication (`38bc0b4` first, then schema migration + remaining commits) — requires Alembic migration for `app/models.py`.
7. **Item 5** — XP/challenge rules — port `11cfd1c` and `a2ee8e5` only; skip `093b0ca 0183be6 6e5d180`.
8. **Item 2** — Progression/persistence hardening — evaluate each commit individually; port CPR gate commits (`ea615c0 ba4950f 1743e22`) and backend progression logic; skip SCORM navigation state commits (`9e83c19 9cdc623 8780e0c`).
9. **Item 6a** — Head injury scenario evidence (11 commits in chronological order).
10. **Item 6b** — Soft tissue scenario evidence (7 commits).
11. **Item 6c** — Cross-scenario spinal/routing/PCR fixes (8 commits).
12. **Item 6d** — Croup/asthma/CPAP/trauma flag fixes (6 commits).
13. **Item 7** — FTO debrief structure (9 commits — requires stable scenario evidence from Item 6).
14. **Item 9a** — Debrief missed-points contrast (take final state from `1d822bc`).
15. **Item 9d** — Score normalization (`f0cfbc2`) — evaluate production app.js path before applying.
16. **Item 10** — Vitals trending audit — verification pass across all scenarios; no committed fix confirmed yet.

**Final full-suite smoke run:**
```bash
python -m pytest tests/ -q
```
All tests must pass before the backport is considered complete.

---

## Codex / Claude Execution Prompts

Use Codex for implementation and Claude for review/validation. Work one matrix item at a time; do not let either agent proceed to the next item until the current item has been implemented, reviewed, tested, and committed.

### 1. Codex Setup Review

```text
Read docs/SCORM_TRIAL_PUNCHLIST.md and docs/SCORM_BACKPORT_MATRIX.md first.

Confirm you understand the workflow:
- Codex implements one matrix item at a time.
- Claude reviews/validates each item after Codex commits it.
- Do not blindly cherry-pick SCORM commits.
- For each item, inspect the referenced SCORM diffs, identify which hunks are ported/skipped, explain why, run listed tests, update matrix status only after verification, and commit separately.

Do not make code changes yet. Summarize the execution order and any immediate risks.
```

### 2. Codex Per-Item Implementation

```text
Read docs/SCORM_TRIAL_PUNCHLIST.md and docs/SCORM_BACKPORT_MATRIX.md.

Implement Matrix Item <ITEM_NUMBER>: <ITEM_NAME>.

Requirements:
- Inspect every referenced SCORM commit diff.
- Identify production-relevant hunks vs SCORM-only hunks.
- Apply only production-relevant changes.
- Keep the work scoped to this item.
- Add/update tests where practical.
- Run the tests listed for this item.
- Update docs/SCORM_BACKPORT_MATRIX.md status for this item only.
- Commit the item separately with a clear message.

Before committing, summarize:
1. SCORM commits inspected
2. Hunks ported
3. Hunks skipped and why
4. Tests run and results
5. Any browser checks still required
```

### 3. Claude Per-Item Review

```text
Read docs/SCORM_TRIAL_PUNCHLIST.md and docs/SCORM_BACKPORT_MATRIX.md.

Review the latest commit for Matrix Item <ITEM_NUMBER>: <ITEM_NAME>.

Use a code-review stance. Findings first, with file/line references.

Focus on:
- SCORM-only code accidentally ported
- production-relevant hunks missed
- backend authority/scoring/evidence boundary violations
- missing or weak tests
- matrix status updated too early
- browser checks that still need to be performed
- regressions against the acceptance intent in docs/SCORM_TRIAL_PUNCHLIST.md

Do not make changes unless the issue is trivial and clearly safe. If no issues, say so clearly and list residual risk.
```

### 4. Codex Fix Review Findings

```text
Read Claude's review findings for Matrix Item <ITEM_NUMBER>.

Address only those findings. Keep the fix scoped to this matrix item.
Rerun the affected tests.
Update docs/SCORM_BACKPORT_MATRIX.md only if the status or verification notes changed.
Commit the fix as a follow-up commit or amend the item commit if appropriate.

Summarize what changed and what tests passed.
```

### 5. Claude Final Branch Review

```text
Read docs/SCORM_TRIAL_PUNCHLIST.md and docs/SCORM_BACKPORT_MATRIX.md.

Perform a final review of the full post-scorm-testing branch.

Confirm:
- all applicable matrix items are marked [x]
- all inapplicable SCORM-only items are marked [s]
- no item remains [ ] or [~] without an explicit reason
- SCORM-only wrappers/runtime/package files were not incorrectly ported
- backend authority and scoring/evidence boundaries are preserved
- tests listed in the matrix were run
- remaining live browser checks are clearly listed

Use a code-review stance: findings first with file/line references. If no blocking issues, say the branch is ready for final browser validation.
```

### 6. Codex Final Cleanup

```text
Address Claude's final branch review findings.

Keep changes minimal and scoped.
Run the affected tests plus the full suite if practical.
Update docs/SCORM_BACKPORT_MATRIX.md statuses/notes if needed.
Commit final cleanup separately.

Summarize final test results and remaining browser validation steps.
```

---

## Reference Commands

```bash
# View any SCORM commit diff
git -C "/Users/jonathanfrastaci/Projects/Development/Peds Assessment SCORM" show <hash>

# View one file from a SCORM commit
git -C "/Users/jonathanfrastaci/Projects/Development/Peds Assessment SCORM" show <hash> -- <file>

# List all files changed in a SCORM commit
git -C "/Users/jonathanfrastaci/Projects/Development/Peds Assessment SCORM" show --stat <hash>

# Diff a file between SCORM and production
diff \
  <(git -C "/Users/jonathanfrastaci/Projects/Development/Peds Assessment SCORM" show HEAD:<file>) \
  "/Users/jonathanfrastaci/Projects/Development/EMS Simulator/<file>"

# Run full test suite in production
cd "/Users/jonathanfrastaci/Projects/Development/EMS Simulator" && python -m pytest tests/ -q

# Create Alembic migration after schema change
cd "/Users/jonathanfrastaci/Projects/Development/EMS Simulator" && alembic revision --autogenerate -m "<description>" && alembic upgrade head
```

---

*Last updated: 2026-07-02. SCORM source repo: `/Users/jonathanfrastaci/Projects/Development/Peds Assessment SCORM`, commits `f172794` through `6023cdf`.*
