# CE Certification Design

**Status:** Reference — not an active sprint
**Last Updated:** 2026-05-17
**Scope:** Architecture decisions and future-readiness design for CE certification through challenges. This document is a design reference, not an implementation checklist. Build items here only when pursuing certification.

---

## 1. Purpose

This document tracks the design decisions needed to make the platform CE-certifiable without locking in a specific certifying agency or building premature infrastructure. All naming and architecture must remain agency-agnostic. No CAPCE-specific strings belong in code, DB columns, or UI copy.

The goal during active development is to **not paint yourself into a corner** — keep the architecture CE-compatible as the platform grows, so certification is an additive layer rather than a rework.

---

## 2. What Is Already in Place

These pieces are CE-compatible by design and should not be changed in ways that undermine them.

### 2.1 Time Tracking — `CeTimeLog`

Append-only DB table (`ce_time_log`). Every CE-eligible activity adds a row — no updates, no deletes.

| Field | Description |
|-------|-------------|
| `activity_type` | `"orientation"` \| `"scenario"` \| `"drill"` \| `"debrief"` |
| `source_id` | `session_id` or `run_id` — used for idempotency deduplication |
| `scenario_id` | optional context |
| `seconds` | duration of this block; may be negative for admin compensating rows |

**Idempotency constraint:** A partial unique index `uq_ce_time_log_source` on `(user_id, source_id, activity_type) WHERE source_id IS NOT NULL` is enforced at the DB level (added in `database.py` `init_db()`). This prevents race-condition duplicates from retried requests. Rows without a `source_id` (orientation awards) are guarded at the application layer via `orientation_completed_at`.

**Compensating rows:** If an admin correction is needed, add a row with negative `seconds` — do not update or delete the original. The floor rounding function (`_ce_round_hours`) must always be applied **after** summing all rows, not per-row. Summing first then flooring is already how `_get_user_ce_breakdown()` works; preserve this pattern in any admin tooling.

**Phase caps (server-side, not frontend):**

| Activity | Cap | Rationale |
|----------|-----|-----------|
| Feedback/drill review | 120 s (2 min) | Expected active read time for short drill debrief |
| Scenario debrief | 480 s (8 min) | Expected active read time for full debrief |
| Orientation debrief | 300 s (5 min) | Expected active read time for orientation walkthrough |

Caps are constants in `app/main.py`: `CE_FEEDBACK_REVIEW_CAP_SECONDS`, `CE_SCENARIO_DEBRIEF_CAP_SECONDS`, `CE_ORIENTATION_DEBRIEF_CAP_SECONDS`. Adjust only with pilot telemetry evidence.

### 2.2 Hour Rounding — `_ce_round_hours()`

`math.floor((seconds / 3600) * 4) / 4` — floors to nearest completed 0.25-hour increment. No partial credit. Matches standard certifying-agency granularity. Do not switch to `round()`.

### 2.3 CE Summary Endpoint

`GET /api/me/ce-summary` returns:
- `total_seconds`, `total_minutes`, `total_hours` — raw totals
- `total_hours_ce` — floored to 0.25 h units (the reportable figure)
- `by_activity` — breakdown by `activity_type`
- `orientation_completed`, `orientation_completed_at`

### 2.4 Debrief Timer — `_activeReviewTimer`

Frontend IIFE in `app.js`. Tracks active foreground time on review/debrief screens. Pauses on 90s idle or tab hidden. Submits via `POST /api/me/progress` with `debrief_only: true` after the learner closes the debrief modal. Idempotent via `source_id = "{session_id}:debrief"`.

### 2.5 SCORM CE Challenge Gate — `_peds_ce_challenge()`

Server-side check in `app/routers/scorm.py`. Enforces:
- Orientation completed
- Both required drills (`drill_pat` + `drill_dev`)
- PM1: any 2 of 4 scenarios
- PT1: any 2 of 5 scenarios
- CPR scenario (`scen_cpr`)
- Optional games: any 2 of 3
- Total CE time ≥ 3600 s (60 min)
- Minimum XP ≥ 1100

Returns `complete: bool` plus per-criterion status for frontend display.

### 2.6 Session Progress — `POST /api/me/progress`

Supports `debrief_only: bool` and `debrief_elapsed_sec: int`. When `debrief_only=True`, bypasses XP pipeline and records only capped debrief CE time. Old frontend (without these fields) works identically — backward-compatible defaults.

---

## 3. Design Rules — Apply During Active Development

These are **standing constraints**, not future work. Apply them whenever touching the relevant systems.

1. **Time caps live server-side.** Never enforce CE time limits in frontend-only logic.
2. **`CeTimeLog` is append-only.** No `UPDATE` or `DELETE` on existing rows. Corrections go in as compensating rows.
3. **Eligibility gates belong server-side.** If a "take assessment" or "unlock content" UI element is ever added, the backend decides; the frontend renders the response.
4. **Keep `Challenge` (gamification) separate from any CE module registry.** The `Challenge` model is for badges, teams, and leaderboard — not for CE compliance tracking. If a module definition table is ever built, it is its own table (`CeModule`), not an extension of `Challenge`.
5. **Completion events that touch `CeTimeLog` must be idempotent.** Use `source_id` deduplication consistently for any new activity types.
6. **Any CE completion status must be a snapshot, not a derived view.** When a `CeAwardRecord` is eventually built, it stores a point-in-time snapshot of seconds, score, scenarios completed, and post-test score — not a live recalculation.
7. **All naming is agency-agnostic.** No CAPCE-specific strings in code, DB, or UI. Use "CE", "credit hours", "certification" as generic terms.
8. **Post-test answers store `answer_id`, not array index.** If a question's options are reordered in a future version, an index-based record loses audit meaning. Each option in `CePostTest.questions` must carry a stable `id`; `CePostTestAttempt.answers` maps `{question_id: answer_id}`.
9. **Future hardening — debrief timer wall-clock cross-check.** The current design caps frontend-reported debrief time server-side (e.g. max 480 s). A determined actor could POST the cap immediately on debrief open. Proper hardening requires the backend to record `debrief_started_at` on the session and credit `min(reported, wall_clock_elapsed, cap)`. Do not implement until the session model is extended; note this as a gap if pursuing formal certification before then.

---

## 4. Six-Step Certification Path (Reference)

These steps define the full path to CE certification. They are documented here as a design reference, not an active sprint. Build a step only when pursuing certification.

### Step 1 — CE Module Registry (`CeModule`)

**Purpose:** A DB-level definition of what constitutes a CE course — content requirements, minimum time, approval metadata.

**Status:** Not built. `Challenge.requirements` JSONB partially captures completion criteria but lacks CE-specific metadata.

**Schema (when built):**
```python
class CeModule(Base):
    __tablename__ = "ce_modules"
    id             = Column(String, primary_key=True, default=new_uuid)
    agency_id      = Column(String, ForeignKey("agencies.id"), nullable=True)  # null = platform-wide
    module_key     = Column(String(64), nullable=False, unique=True)  # e.g. "pfd_station1"
    title          = Column(String, nullable=False)
    description    = Column(String, nullable=True)
    min_ce_seconds = Column(Integer, nullable=False, default=3600)
    requirements   = Column(JSONB, nullable=False, default=dict)
    approved_by    = Column(String, nullable=True)  # medical director name/ref
    approved_at    = Column(DateTime, nullable=True)
    is_active      = Column(Boolean, nullable=False, default=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
```

`requirements` shape mirrors `_peds_ce_challenge()` criteria:
```json
{
  "required_drills": ["drill_pat", "drill_dev"],
  "required_scenario_groups": [
    {"group": "pm1", "min_count": 2, "nodes": ["scen_croup", ...]},
    {"group": "pt1", "min_count": 2, "nodes": ["scen_laceration", ...]}
  ],
  "required_nodes": ["scen_cpr"],
  "required_games_min": 2,
  "min_ce_seconds": 3600,
  "min_xp": 1100
}
```

**Dependency:** Everything else in this section references `CeModule`.

---

### Step 2 — Content Gating Endpoint

**Purpose:** Server-side eligibility check before allowing summative test access.

**Status:** SCORM product gate already exists in `_peds_ce_challenge()`. Main web product has no equivalent endpoint.

**When built:** `GET /api/me/ce-eligibility/{module_key}` — returns `eligible: bool` plus list of unmet requirements. The summative test endpoint (Step 3) calls this internally; the frontend uses the response for display only.

**Dependency:** Step 1 (`CeModule`) must exist first.

---

### Step 3 — Summative Assessment

**Purpose:** Post-test / final assessment before CE credit is awarded.

**Status:** Not built. No model, no question bank.

**Blocked on:** Medical director review and approval of question content. Build the schema and endpoint shell now (if pursuing), but do not ship without reviewed questions loaded.

**Schema (when built):**
```python
class CePostTest(Base):
    __tablename__ = "ce_post_tests"
    id           = Column(String, primary_key=True, default=new_uuid)
    module_id    = Column(String, ForeignKey("ce_modules.id"), nullable=False, index=True)
    version      = Column(Integer, nullable=False, default=1)
    questions    = Column(JSONB, nullable=False)  # list of question objects with answer key
    passing_score = Column(Integer, nullable=False, default=70)
    is_active    = Column(Boolean, nullable=False, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)

class CePostTestAttempt(Base):
    __tablename__ = "ce_post_test_attempts"
    id           = Column(String, primary_key=True, default=new_uuid)
    user_id      = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    post_test_id = Column(String, ForeignKey("ce_post_tests.id"), nullable=False)
    answers      = Column(JSONB, nullable=False)   # {question_id: answer_id} — use answer_id not index position
    score        = Column(Integer, nullable=True)  # 0-100, null until scored
    passed       = Column(Boolean, nullable=True)
    started_at   = Column(DateTime, nullable=False, default=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
```

Scoring is deterministic — answer key embedded in `questions` JSONB, evaluated server-side. No LLM involvement in scoring.

**Dependency:** Steps 1 + 2.

---

### Step 4 — Evaluation Form

**Purpose:** Learner satisfaction survey. Most certifying agencies require one before issuing credit.

**Status:** Not built.

**Blocked on:** Evaluation form question content (needs review; not as strict as post-test but should be intentional).

**Schema (when built):**
```python
class CeEvaluationForm(Base):
    __tablename__ = "ce_evaluation_forms"
    id         = Column(String, primary_key=True, default=new_uuid)
    module_id  = Column(String, ForeignKey("ce_modules.id"), nullable=False, index=True)
    version    = Column(Integer, nullable=False, default=1)
    questions  = Column(JSONB, nullable=False)  # [{id, text, type: "rating"|"text"|"choice", options?}]
    is_active  = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class CeEvaluationResponse(Base):
    __tablename__ = "ce_evaluation_responses"
    id           = Column(String, primary_key=True, default=new_uuid)
    user_id      = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    form_id      = Column(String, ForeignKey("ce_evaluation_forms.id"), nullable=False)
    answers      = Column(JSONB, nullable=False)  # {question_id: answer_value}
    submitted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
```

Can be built in parallel with Step 3 once Step 1 exists.

---

### Step 5 — Lock Audit Records (`CeAwardRecord`)

**Purpose:** Immutable snapshot of the CE completion event. The actual audit artifact.

**Status:** Not built. `CeTimeLog` is append-only (good), but there is no capstone award record yet.

**Design rules:**
- Insert-only. No `UPDATE` on audit columns after creation. Admin void path only writes `voided_at` + `voided_reason`.
- `certificate_number` is deterministic: `{user_id[:8]}-{module_key}-{awarded_at:%Y%m%d%H%M%S}`. Reconstructible from first principles. Using seconds-granularity prevents collision on same-day void-and-retake (a date-only format would collide).
- Store a point-in-time snapshot of CE seconds, scenario scores, and post-test score — not live FK-derived values.

**Schema (when built):**
```python
class CeAwardRecord(Base):
    __tablename__ = "ce_award_records"
    __table_args__ = (UniqueConstraint("user_id", "module_id", "awarded_at", name="uq_ce_award"),)

    id                     = Column(String, primary_key=True, default=new_uuid)
    user_id                = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    module_id              = Column(String, ForeignKey("ce_modules.id"), nullable=False, index=True)
    post_test_attempt_id   = Column(String, ForeignKey("ce_post_test_attempts.id"), nullable=False)
    evaluation_response_id = Column(String, ForeignKey("ce_evaluation_responses.id"), nullable=False)
    awarded_at             = Column(DateTime, nullable=False, default=datetime.utcnow)
    ce_seconds             = Column(Integer, nullable=False)       # snapshot at time of award
    ce_hours               = Column(Numeric(5, 2), nullable=False) # floored 0.25 h units
    scenarios_completed    = Column(JSONB, nullable=False)         # {node_id: score} snapshot
    post_test_score        = Column(Integer, nullable=False)
    certificate_number     = Column(String(64), nullable=False, unique=True)
    voided_at              = Column(DateTime, nullable=True)        # admin-only
    voided_reason          = Column(String, nullable=True)
```

**Dependency:** Steps 3 + 4 must both be completable (have real data to reference).

---

### Step 6 — Certificate/Export Layer

**Purpose:** Exportable CE completion record.

**Status:** Not built.

**Start with JSON, not PDF.** A structured JSON export is sufficient for the pilot and gives you a data contract before committing to a PDF format. Add PDF rendering (WeasyPrint or cloud render) only when a certifying agency specifies what fields they need.

**Export endpoint (when built):** `GET /api/me/ce-awards/{award_id}/certificate`

```json
{
  "certificate_number": "abc12345-pfd_station1-20260517",
  "awarded_at": "2026-05-17T14:30:00Z",
  "learner_name": "Jane Smith",
  "module_title": "Pediatric Assessment — Station 1",
  "ce_hours": 1.25,
  "post_test_score": 85,
  "scenarios_completed": { "scen_croup": 88, "scen_asthma": 76 },
  "approved_by": "Medical Director Name",
  "export_format": "json/v1"
}
```

**Dependency:** Step 5 (`CeAwardRecord`) must exist.

---

## 5. Step Dependencies

```
Step 1 (Module Registry)
  └─▶ Step 2 (Content Gating)
  └─▶ Step 3 (Summative Assessment) ── blocked: content needs medical director review
  └─▶ Step 4 (Evaluation Form)      ── blocked: form questions need review
                                           │
                          Steps 3 + 4 both completable
                                           │
                                     Step 5 (Lock Audit)
                                           │
                                     Step 6 (Certificate)
```

Steps 3 and 4 can be built in parallel once Step 1 is in place. Step 5 gates on both producing real data rows. Step 6 is the last piece.

---

## 6. What This Means for the SCORM Pilot

The SCORM pilot does **not** need Steps 1–6. The pilot's CE-related output is:

- `CeTimeLog` rows recording active time per node
- `ScormAttempt` node completion + score state
- `_peds_ce_challenge()` gate result in the attempt summary (`complete: bool`)
- `cmi.core.lesson_status` written to the LMS (`"passed"` when CE challenge complete, `"incomplete"` otherwise)

For the pilot, the LMS is the system of record for completion — not a `CeAwardRecord`. The certification path is additive on top of the pilot infrastructure.

### `finish()` contract (fixed 2026-05-17)

`scorm.js finish()` gates on `peds_ce_challenge.complete`, not on `final_score !== null`. It writes `"incomplete"` (never `"failed"`) for in-progress learners. A static assertion test in `tests/test_scorm.py` (`test_scorm_js_finish_semantics`) prevents this from drifting back.

---

## 7. Pilot Telemetry to Collect

These data points from the pilot will inform the future CE path:

| Metric | Use |
|--------|-----|
| Median active scenario session time | Validates the 60-min CE time floor |
| Median debrief view time | Validates the 8-min debrief cap |
| Median drill view time | Validates the 2-min drill feedback cap |
| Scenario pass rates | Informs post-test difficulty calibration |
| Scenarios replayed | Informs replay-time CE credit policy |

Review these after the 2–5 learner pilot run before adjusting any caps or time thresholds.
