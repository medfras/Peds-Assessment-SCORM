# Practice Insights Dashboard Design

**Status:** Baseline implemented — Phase 1, initial drill-performance endpoint, and initial Lexi Practice Coach  
**Scope:** `screen-progress` — learner coaching and practice insights  
**Audience:** Engineering, instructional design

---

## 1. Purpose, Tone, and Scope

The Practice Insights Dashboard is a learner-facing coaching surface that surfaces **skill quality** derived from scored scenario sessions, drill results, and (in future phases) trivia performance. It is explicitly **not** a progress tracker — completion counts, XP, maps cleared, and unlock milestones belong to a separate Progress surface.

The core question the dashboard answers:

> "What am I building well, what needs another rep, and what should I practice next?"

This distinction matters because activity volume and skill quality are not the same thing. A learner who has run twenty scenarios at 55% is not performing better than one who has run five at 80%. Blending progress metrics into a performance view obscures this.

This dashboard must feel like a supportive FTO or coach helping the learner choose their next best rep, not like a punitive LMS gradebook. It should encourage practice, reinforce strengths, and connect gaps directly to resources in Training Center and Notebook.

### 1.0 The FTO & Lexi Synergy
This dashboard acts as the literal handoff point between the platform's two core personas:
- **The FTO (Objective Data):** The charts, trend lines, focus areas, and strengths represent the objective, formal evaluation of the learner's clinical performance.
- **Lexi (Coaching & Next Steps):** The recommended next reps and action links represent Lexi stepping in to say, "I see the data — here is exactly how we're going to practice and improve those areas."

### 1.1 Learner-Facing Naming

Recommended learner-facing labels:

- Primary page title: **Practice Insights**
- Sidebar label: **My Practice**
- Section labels: **Recommended Next Reps**, **Focus Areas From Recent Calls**, **Strengths You're Building**, **Skill Patterns**, **Drill Performance**

Avoid learner-facing labels like "deficiencies," "weaknesses," "QA failure," "QI variance," or "remediation" unless the product is explicitly in an instructor/admin QA mode.

### 1.2 QA/QI and FTO Language

EMS learners understand QA/QI and FTO language, but those terms can change the emotional meaning of the page from coaching to evaluation. Use them selectively:

- Learner-facing dashboard: avoid **QA/QI** as a label. Use **Practice Insights**, **FTO-style feedback**, or **coaching notes** instead.
- Scenario debriefs: **FTO Evaluation** is acceptable because it matches the simulation framing and gives structured feedback after a call.
- Instructor/admin analytics: QA/QI language is appropriate there, because that surface is operational oversight rather than learner self-coaching.
- If an agency wants formal FTO framing later, expose it as configurable copy, not a hard-coded learner-wide label.

---

## 2. Guiding Principles

**2.1 Backend is authoritative.** All aggregate scores, category breakdowns, and trend data are computed server-side from `score_snapshot` and `checklist_states`. The frontend renders, it does not compute.

**2.2 Deterministic data first.** The scoring engine produces two adjudication methods: `deterministic` (Phase 1+) and `legacy_ai` (pre-Phase 1 sessions). Performance views must tag or filter by adjudication method. Comparing a `legacy_ai` score to a deterministic one is not valid.

**2.3 Separate categories, do not blend.** The five scored rubric categories (`clinical_performance`, `protocols_treatment`, `scope_adherence`, `documentation`, `professionalism`) are independent dimensions. Do not reduce them to a single number for the performance view — the composite scenario score is already displayed in history. The dashboard's value is in disaggregation.

**2.4 Surface evidence, not verdicts.** Where possible, show the user *which actions need another rep*, not just that a category score was low. The focus-area list is more actionable than a bar chart.

**2.5 Confidence calibration is the long-term goal.** The most instructionally valuable metric is the gap between self-assessed confidence and scored performance. Phase 5 of this design requires a pre-scenario confidence field that does not yet exist. Design for it.

**2.6 Resources beside gaps.** Every focus area should point somewhere useful: a drill, Notebook reference card, similar scenario, or Lexi debrief. Do not surface a gap without a path to improve it.

**2.7 Strengths matter.** The dashboard should always include positive reinforcement when data exists. Show what the learner is doing well so the page feels balanced and motivating.

**2.8 Use coaching language.** Prefer "needs another rep," "still building," and "ready to reinforce" over "weak," "failed," or "deficient." The page should make practice feel possible.

**2.9 Lexi can coach, but not adjudicate.** Lexi may explain patterns, connect the learner to relevant protocols, suggest unlocked drills/scenarios, and help plan the next rep. Lexi must not rescore calls, change completion state, award XP, unlock content, override scope rules, or present herself as the source of clinical truth. Authoritative state remains backend-derived.

**2.10 Encouraging does not mean vague.** Lexi should be warm and confidence-building, but honest. A good coaching response names one strength, one evidence-backed focus area, and one specific next action. Avoid empty reassurance when recent records show a real pattern.

---

## 3. Data Model and Sources

### 3.1 Available Today

| Source | Fields | Notes |
|--------|--------|-------|
| `SimSession.score_snapshot` | `categories[cat].total`, `categories[cat].max`, `categories[cat].method` | Canonical scoring record. Use over `narrative_data.subscores` when both exist. |
| `SimSession.checklist_states` | `item_states[].item_id`, `item_states[].state`, `item_states[].category` | Only populated on sessions after 2026-04-24. Gracefully degrade for older records. |
| `SimSession.narrative_data.subscores` | Per-category total and `_maxes` | Fallback for sessions without `score_snapshot`. |
| `SimSession` columns | `score`, `assessment_score`, `narrative_score`, `critical_failure`, `provider_level`, `elapsed_min`, `ended_at` | Base session record. |
| `GET /api/me/performance` | `score_trend`, `category_averages`, `most_missed_items`, `completed_sessions` | Existing aggregation endpoint. Extend, do not replace. |
| `MinigameResult` | `game_id`, `score`, `correct`, `total`, `mistake_tags`, `elapsed_sec`, `created_at`, `mode` | Per-drill play record. |

### 3.2 Rubric Categories (Scored)

| Category Key | Display Name | Adjudication |
|---|---|---|
| `clinical_performance` | Clinical Performance | Deterministic (Phase 1) |
| `protocols_treatment` | Protocol / Treatment | Deterministic (Phase 1) |
| `scope_adherence` | Scope of Practice | Deterministic (Phase 1) |
| `documentation` | Communication / Handoff | Legacy AI (current scenarios) |
| `professionalism` | Professionalism | Legacy AI (current scenarios) |

> The `method` field in `score_snapshot.categories[cat]` must be checked before including a category in trend comparisons. Do not compare `legacy_ai` sessions to deterministic ones in the same trend line.

### 3.3 Skill Domain Taxonomy

The eight clinical domains used in Practice Insights map to rubric categories and drill types as follows. These domains are the user-facing axis labels — they do not replace internal rubric keys.

| Display Domain | Primary Rubric Category | Related Game Types |
|---|---|---|
| Assessment | `clinical_performance` | `pat`, `dev_sort`, `dev_flags`, `history_maker`, `diff_dash_ams`, `diff_dash_resp` |
| Airway / Breathing | `clinical_performance`, `protocols_treatment` | `lung_sounds_matcher`, `sound_check`, `diff_dash_resp` |
| Circulation / Shock | `clinical_performance`, `protocols_treatment` | `shock_spotter_med`, `shock_spotter_trauma`, `vitals_trend_spotter` |
| CPR / Cardiac Arrest | `protocols_treatment` | `bls_sequence` |
| Trauma | `clinical_performance`, `protocols_treatment` | `ten4_facesp`, `rule_of_nines`, `stop_the_bleed`, `moi_mapper` |
| Communication / Handoff | `documentation` | `dmist_builder`, `history_maker` |
| Protocol / Scope | `scope_adherence`, `protocols_treatment` | `protocol_pivot`, `peds_gcs_calculator` |
| Professionalism | `professionalism` | — |

> **Implementation note:** This mapping is currently declarative (frontend constant). The canonical mapping should eventually live in the backend game/rubric config so it can be queried, not inferred. A future schema addition to `ChecklistItem` should include `skill_domain: str | None` alongside `category`.

### 3.4 What Requires New Backend Work

| Feature | Required Change | Priority |
|---|---|---|
| Category averages by scenario family (medical vs. trauma) | Group `score_snapshot` by scenario prefix + category in `/api/me/performance` | High |
| Drill proficiency trends over time | Time-series query on `MinigameResult` by `game_id`, grouped by `created_at` week | High |
| Focus Areas (frequently missed checklist items) | Already implemented in `/api/me/performance` as `most_missed_items` — expose with coaching language | High |
| Drill mistake tag aggregation | Group `MinigameResult.mistake_tags` across plays per `game_id` | Medium |
| Provider-level performance split | Filter `score_snapshot` by `SimSession.provider_level` in aggregate query | Medium |
| Subskill tags on checklist items | Add `skill_domain` field to `ChecklistItem` schema + backfill all 13 scenarios | Future |
| Pre-scenario confidence rating | Add `pre_scenario_confidence: int (1–5)` to `SimSession` or `narrative_data` | Future |
| Confidence calibration score | Compare confidence to actual score per session, aggregate gap metric | Future |

---

## 4. Dashboard Layout

### 4.1 Screen Structure

```
┌─ tc-header ──────────────────────────────────────────────────┐
│  ← Back    📊 Practice Insights              [tab: Scenarios | Drills]  │
└───────────────────────────────────────────────────────────────┘
┌─ tc-body ─────────────────────────────────────────────────────┐
│                                                               │
│  [Coach note: evidence-based practice suggestions]            │
│                                                               │
│  [Summary row: scenario count · recent form · strongest area] │
│                                                               │
│  ── Lexi's Recommended Next Reps ────────────────────────── │
│  [Top 3 scenario/drill/notebook actions + Lexi reasoning]     │
│                                                               │
│  ── Top Focus Areas ──────────  ── Consistent Strengths ── │
│  [Top 3 missed items + Link to   [Top 3 perfected items]   │
│   Notebook card or Drill]                                  │
│                                                               │
│  ── Skill Patterns ─────────────────────────────────────── │
│  [5 category bars with score, trend arrow, and session count] │
│                                                               │
│  ── Recent Trend ──────────────────────────────────────── │
│  [Sparkline of last 10 sessions, color-coded by category]    │
│                                                               │
│  ── Drills ─────────────────────────────────────────────── │
│  [Per-drill last score + trend, organized by domain]         │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

The Scenarios / Drills tab split is the primary navigation. Both tabs are under the same Practice Insights header. There is no Progress tab in this screen.

### 4.1.1 Coach Note

Short static copy near the top:

> "These insights are here to guide your next practice rep. They are based on recent calls and drills, not a permanent grade."

This reduces the cold LMS feel and clarifies that the dashboard is formative.

### 4.2 Summary Row

Three inline stats, always visible:

- **Scenarios run** — count of scored (non-drill) sessions with a `score_snapshot`
- **Average score** — mean of `score` across same sessions, last 10 runs
- **Strongest area** — the rubric category with the highest average pct (category_total / category_max), label only

These are not gamification rewards — they are baseline context for interpreting the content below.

### 4.3 Recommended Next Reps

This is the highest-priority learner-facing section. It should appear before category bars.

Each recommendation includes:

- Action type: `Practice Drill`, `Retake Similar Call`, `Open Notebook Card`, or `Debrief With Lexi`
- Title
- Reason in plain language, e.g. "Recent calls show airway reassessment is still building."
- CTA button

If recommendation data is unavailable, show a friendly placeholder: "Run a few calls or drills and Lexi will help pick your next best rep."

### 4.4 Coach With Lexi

Add a **Coach with Lexi** action to the Practice Insights header and to focus-area rows when enough evidence exists. This opens a bounded coaching chat modal, not the general scenario chat.

The modal should include:

- A short context banner: "Lexi is using your recent scored calls, drill results, unlocked practice options, and agency protocol context."
- Suggested prompts: "What should I practice next?", "Why is this a focus area?", "Which protocols should I review?", "Show me a 10-minute practice plan."
- Inline links to relevant unlocked drills, accessible scenarios, Notebook cards, and recent-call debriefs.
- A visible usage indicator, e.g. "Coaching turns left today: 8."

Lexi's default response pattern:

1. Affirm a concrete strength from the evidence.
2. Name the pattern honestly, using learner-facing language.
3. Explain why it matters clinically.
4. Recommend one next rep and one resource.
5. Invite a focused follow-up question.

Example tone:

> "Your scene setup and patient communication are becoming a strong pattern. The next thing to tighten is OPQRST timing — it showed up in 4 of your recent calls. That matters because onset and progression often change the protocol path. I'd review the respiratory distress protocol, then run the Croup call again and focus only on the first 90 seconds of history."

---

## 5. Scenarios Tab

### 5.1 Skill Patterns

One row per category. Each row shows:

- Category label (display name from taxonomy above)
- Percentage: `avg(category.total / category.max) × 100` across last N sessions where `method = "deterministic"` for that category
- A narrow horizontal bar scaled 0–100%
- A trend indicator: ▲ / ▼ / — comparing last 5 sessions vs. prior 5, where N ≥ 10
- Number of sessions used in the average, shown in learner language (for example, `Based on 12 calls`, not `n=12`)
- If `legacy_ai`: muted label "Score not yet deterministic" — no trend arrow

Learner-facing status tiers:
- ≥ 85%: **Strong pattern** — green (`#059669`)
- 70–84%: **Developing** — amber (`#d97706`)
- < 70%: **Needs another rep** — muted rose (`#be5b63`)

Do not show a category if the user has zero scored sessions with it populated. Do not show `legacy_ai` categories in trend comparisons.

Avoid showing the raw category rows as a "report card." The row copy should emphasize practice direction, not judgment.

### 5.2 Recent Trend

A small sparkline showing total `score` for the last 10 scored sessions, ordered by `ended_at`. Points are color-coded by the same softened tiers. A `criticalFailure = true` point is marked with an ×.

Hover/tap on a point shows: scenario title, score, date. Clicking navigates to the session debrief (reusing the existing debrief modal).

If fewer than 3 sessions, show a placeholder: "Run at least 3 scenarios to see your score trend."

### 5.3 Focus Areas From Recent Calls

Source: `GET /api/me/performance` → `most_missed_items`. Top 5 by `miss_rate`.

Each row:
- Checklist item label (truncated at 60 chars)
- Practice signal as a percentage (e.g., `Seen in 9 calls · needs reps in 6`)
- Seen count in learner language (for example, `Seen in 9 calls`)
- Category badge matching the item's rubric category
- Suggested next action, if known: Training Center drill, Notebook reference, similar scenario, or Lexi debrief

If `checklist_states` is not available for enough sessions (< 3), show: "More scenario data needed to identify patterns."

This section converts vague "your clinical_performance score is low" into a coaching action like "Practice airway reassessment after intervention."

### 5.4 Strengths You're Building

Source: checklist items or rubric categories with consistently satisfied evidence over the recent window.

Each row:
- Strength label
- Evidence summary, e.g. `Satisfied in 8 of last 9 calls`
- Optional "Keep it sharp" drill or scenario link

This section should appear next to Focus Areas when space allows. If there is not enough data, hide it rather than showing a low-value empty state.

### 5.5 Performance by Scenario Family

Once the backend adds grouping by scenario type (medical vs. trauma vs. pediatric subspecialties), this section shows per-family category averages. It answers: "Do I score better in trauma than medical?"

**Deferred until `/api/me/performance` is extended.** Stub with a placeholder.

---

## 6. Drills Tab

### 6.1 Per-Drill Performance Summary

Source: `MinigameResult` records aggregated by `game_id` for the current user.

For each drill the user has played at least once:

- Drill label (from `DOG_PARK_GAME_GROUPS`)
- Domain chip (from skill domain taxonomy)
- Best score (max `score` across plays)
- Last score
- Play count
- A micro-trend: last 3 scores as dots using the same softened tiers as scenarios
- If `mistake_tags` are present: the top 1–2 most frequent tags (e.g., "Timing", "Sequence")

Organized into domain shelves matching the 8-domain taxonomy. Within each shelf, order drills by coaching value: active recommendations first, then developing scores, then stale strong scores.

### 6.2 Requires: New Backend Endpoint

A new `GET /api/me/drill-performance` endpoint is needed that returns:

```json
[
  {
    "game_id": "lung_sounds_matcher",
    "play_count": 7,
    "best_score": 92,
    "last_score": 78,
    "scores": [65, 71, 78, 80, 82, 90, 78], // Capped at last 10 scores to prevent bloat
    "top_mistake_tags": ["Identification", "Laterality"],
    "last_played_at": "2026-05-01T14:22:00Z"
  }
]
```

Query: aggregate `MinigameResult` by `game_id` where `user_id = current`, sorted by `created_at`. Include all plays (not just passing ones) for trend purposes.

### 6.3 Drill Score Status

Same softened tiers as scenario scores:
- ≥ 85: Strong pattern
- 70–84: Developing
- < 70: Needs another rep

Below passing threshold (`< 70`) should use a subtle left border and coaching text, not an alarm state.

---

## 7. Recommendation Logic (Future)

Practice Insights feeds the Recommended shelf in Training Center. The recommendation algorithm reads from this screen's data. It is **not implemented in the dashboard UI itself** — it runs server-side and is rendered in the Training Center surface.

Priority order for future recommendation engine:

1. **Rubric focus patterns** — categories with `avg < 70%` over last 5 deterministic sessions, sorted by gap size
2. **Drill mistake tag frequency** — top recurring mistake tags across all `MinigameResult.mistake_tags`, mapped to drills that target that tag
3. **Stale mastered skills** — drills with best score ≥ 85 but `last_played_at > 30 days ago`
4. **Developing domain scores** — cross-scenario domain focus areas (once subskill tags exist)

"New and unplayed" drills (accessible but never played) are shown as a **separate shelf** in Training Center ("Available to Try"), not as remediation recommendations.

---

## 8. Lexi Practice Coach Context and Guardrails

Lexi's Practice Coach mode is a learner support feature. It should feel like a thoughtful FTO sitting beside the learner after reviewing recent records, not like an LMS punishment panel or an unlimited general-purpose AI chat.

### 8.1 Backend-Curated Context Packet

The frontend must not decide what Lexi knows. The backend builds a scoped context packet for the current authenticated user and agency.

Recommended context packet contents:

- Recent scenario performance summary: last 10 scored calls, category trends, focus areas, strengths, and relevant debrief snippets.
- Drill performance summary: unlocked drills, passed drills, recent drill scores, recurring mistake tags, and recommended drills.
- Available practice options: unlocked maps, unlocked scenarios, visible drills, Notebook cards, and reference cards earned by the learner.
- Agency and protocol context: agency name, provider level, MCA/protocol profile, scope constraints, and relevant protocol references selected by deterministic mapping.
- Coaching constraints: daily turn limit remaining, context date range, and whether legacy AI-scored sessions are included.

Context minimization rules:

- Send summaries and selected evidence, not full transcripts by default.
- Include only records for the current user and current agency membership.
- Include only unlocked/visible drills and scenarios unless Lexi is explaining how to unlock the next step.
- If a protocol reference is not in the provided packet, Lexi should say she does not have enough protocol context rather than inventing one.

### 8.2 Lexi Coaching Boundaries

Lexi may:

- Explain why a focus area appeared.
- Highlight strengths and patterns from recent calls.
- Recommend unlocked drills, scenarios, Notebook cards, and earned reference cards.
- Reference agency/provider-level protocol context provided by the backend.
- Help build a short practice plan.

Lexi must not:

- Rescore a scenario or reinterpret the scoring engine's authoritative result.
- Mark drills/scenarios complete, unlock content, award XP, or change progress.
- Override provider scope, protocol rules, or agency configuration.
- Diagnose or advise on real-world patient care outside the simulator/training context.
- Claim certainty when the evidence packet is incomplete.

Protocol phrasing should be careful:

> "Based on your configured agency/protocol profile, the relevant review area is..."

Avoid:

> "Your protocol definitely requires..." unless the exact protocol text or deterministic protocol mapping is included in the packet.

### 8.3 Abuse and Cost Guardrails

Practice Coach should have hard backend limits. Frontend-only limits are not sufficient.

Recommended initial limits:

- Daily quota: configurable per agency, default 10 coaching turns per learner per day.
- Session quota: default 5 turns per opened coaching modal.
- Cooldown: after limit is reached, show the next reset time and offer static resources instead.
- Context cap: last 10 calls, last 20 drill runs, top 5 focus areas, top 5 strengths.
- Token cap: backend truncates or summarizes before sending to the model.
- Audit record: store timestamp, user_id, agency_id, turn count, token estimate, and selected focus/context IDs. Do not store more conversational content than needed for safety/debugging policy.
- Rate limit: enforce per-user and per-agency throttles to prevent repeated refresh/chat loops.

If the learner reaches the limit, the UI should remain supportive:

> "Lexi's coaching limit is reached for today, but your next best rep is still available: run the Lung Sounds drill or review the Airway/Breathing notebook card."

### 8.4 Prompt and Response Guardrails

The system prompt for Practice Coach should require:

- Encouraging but honest coaching.
- Evidence anchoring: mention the record pattern when making a recommendation.
- No punitive language.
- No rescoring or authoritative overrides.
- Protocol humility when protocol excerpts are absent.
- Concrete next actions over generic advice.

Bad response:

> "You are weak at assessment. Study more."

Good response:

> "Assessment is still building, especially history timing. In 3 recent calls, onset/progression details were incomplete. Let's make the next rep narrow: run one respiratory call and focus on OPQRST before treatment decisions."

---

## 9. Confidence Calibration (Phase 5)

This is the highest-value future feature. It requires:

1. A pre-scenario confidence field: `pre_scenario_confidence: int (1–5)` collected in the dispatch/scenario-start flow only when the full calibration feature is implemented; the standalone prompt is currently disabled
2. A backend aggregation that computes `avg(score) - avg(confidence × 20)` by domain
3. A "Confidence Check" chart showing: claimed confidence vs. actual performance per domain

A learner who is highly confident in trauma but consistently scores 55% on trauma scenarios has a specific coaching opportunity. This data does not require new scored rubrics — it requires one new input field at scenario start.

**Not designed in this phase.** Flagged here for schema planning.

---

## 10. API Surface Requirements

### Existing (extend, do not replace)

**`GET /api/me/performance`** — already returns `score_trend`, `category_averages`, `most_missed_items`, `completed_sessions`. Extend with:

- `sessions_by_type` — count of sessions by scenario family prefix (medical, trauma, pediatric sub-type)
- `category_by_type` — per-category averages grouped by scenario family
- `deterministic_session_count` — count of sessions where at least one category has `method = "deterministic"` (for "not enough deterministic data" gating)

### New Endpoint

**`GET /api/me/drill-performance`**  
Returns per-game play history aggregated for the current user. See §6.2 for shape.

Implementation: query `MinigameResult` group by `game_id`, sorted by `created_at`. Include `mistake_tags` aggregation (mode of tags across plays). Enforce tenant boundary via `user_id = current_user.id`.

No new models required. This is a read aggregation over an existing table.

**Implementation status:** initial learner-scoped endpoint is implemented. Future phases can expand it with richer domain tags or server-side recommendation ranking.

### New Practice Coach Endpoints

**`GET /api/me/practice-coach/context`**  
Returns a backend-curated, tenant-scoped context packet for Lexi Practice Coach. The packet should include recent performance summaries, unlocked drills/scenarios, relevant Notebook/reference cards, agency/provider context, selected protocol references, and quota status.

**`POST /api/me/practice-coach/chat`**  
Accepts a learner message plus optional context selectors (`focus_item_id`, `session_ids`, `drill_ids`). The backend composes the final model prompt from authoritative stored data and enforces rate limits. The frontend must not send arbitrary full debrief records as the source of truth.

Model: use `settings.groq_practice_coach_model`, not `settings.groq_lexi_model`. The dashboard coach performs cross-record synthesis and protocol/resource routing, so it should use the stronger model tier while staying bounded by quotas and backend-curated context.

Required safeguards:

- Authenticated user and agency membership check.
- Backend quota/rate-limit enforcement.
- Server-side context selection and truncation.
- No scoring/progress side effects.
- Clear error response when quota is exhausted.

---

## 11. Visual Language and Styling

Reuses the `tc-screen`, `tc-header`, `tc-back-btn` shell from Training Center.

**Practice bars** — narrow horizontal bars (`4px` height), color-coded by softened tier. Not pie charts, not radar/spider charts (radar makes focus areas visually dramatic in misleading ways).

**Trend arrows** — ▲ up, ▼ down, — flat. Use green for improving, muted rose for declining, and gray for flat. Only shown when N ≥ 10 sessions. Do not show arrows for `legacy_ai` categories.

**Domain chips** — same `tc-domain-chip` classes used in Training Center. Consistent across surfaces.

**Score cells** — monospaced weight, right-aligned. Percentage format (e.g., `78%`), not decimal or raw points.

**Focus-area badges** — muted rose chip (e.g., `Needs reps in 6/9`), not a warning icon. This is information, not an alarm.

**Empty states** — informative, not apologetic. "Run at least 3 scenarios to see category trends" is correct. "No data yet — go play!" is not appropriate for a performance tool.

**Language guardrails** — avoid punitive wording in learner-facing copy:

| Avoid | Use Instead |
|---|---|
| Weakness | Focus area |
| Failed | Needs another rep |
| Missed | Still building / needs reps |
| Deficiency | Practice opportunity |
| Remediation | Recommended next rep |
| QA/QI issue | Coaching note / practice signal |

---

## 12. Out of Scope

These are explicitly excluded from this design:

- XP balance, treat counts, badge inventory — those live in Progress
- Map completion status, district unlock counts — Progress
- Leaderboard position — separate surface
- Instructor-facing analytics — separate admin dashboard (different auth, different scope)
- Real-time in-scenario feedback — that's a scenario runtime feature, not a post-hoc surface
- Absolute score benchmarks or normative comparisons (how learner compares to peers) — requires multi-tenant aggregation and privacy review
- Formal QA/QI workflow language in the learner dashboard — reserved for instructor/admin analytics
- AI-based rescoring, unlock decisions, XP awards, or completion changes — Practice Coach is advisory only

---

## 13. Implementation Phases

**Phase 1 — Available Now (implemented baseline)**
- Summary row (session count, avg score from existing cache)
- Coach note and Recommended Next Reps placeholder
- Skill pattern bars from `/api/me/performance` `category_averages`
- Score sparkline from `score_trend`
- Top Focus Areas from `most_missed_items` (top 5)
- **Update API:** Add `consistent_strengths` to `/api/me/performance`
- Strengths You're Building placeholder or hide if data unavailable
- Drills tab stub: last score per drill from client-side `MinigameResult` if cached, else placeholder

**Phase 2 — Add drill-performance endpoint (initial endpoint implemented)**
- Full drills tab with play count, best/last score, micro-trend, mistake tags
- Domain shelf organization in drills tab
- Extend `/api/me/performance` with `deterministic_session_count` gate

**Phase 2.5 — Lexi Practice Coach (initial implementation complete)**
- [x] Add backend-curated `/api/me/practice-coach/context`
- [x] Add rate-limited `/api/me/practice-coach/chat`
- [x] Add Coach with Lexi modal with suggested prompts and usage counter
- [x] Include unlocked scenario drills, played/visible drills, relevant protocols, agency/provider context, focus areas, and recent-call summaries
- [x] Enforce advisory-only guardrails: no rescoring, no unlocks, no XP, no progress writes
- [x] Add daily and per-conversation turn caps
- [ ] Replace in-process quota ledger with durable DB-backed usage table before production billing controls depend on it

**Phase 3 — Extend performance endpoint**
- Per-scenario-family category breakdowns
- "Skill Patterns by Scenario Type" section in Scenarios tab
- Provider-level filter (EMT vs. AEMT vs. Paramedic)

**Phase 4 — Subskill tags**
- Add `skill_domain` to `ChecklistItem` schema
- Backfill all current scenarios
- Enable domain-level breakdown within categories (e.g., "within clinical_performance, you miss medication-math items 72% of the time")

**Phase 5 — Confidence calibration**
- Pre-scenario confidence input
- Calibration chart
