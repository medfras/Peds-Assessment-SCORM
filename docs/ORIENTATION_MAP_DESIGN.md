# Orientation Map — Station 1 Firehouse

**Status:** Planning  
**Last Updated:** 2026-04-30  
**Scope:** First-login orientation experience — firehouse interior map, two mini-game nodes, one dialogue node, one guided scenario node, first-login routing, home-page replay button.

---

## 1. Purpose and Principles

New users arrive with no context for the platform controls, the chat interface, or the scenario loop. The orientation map gives them a safe, zero-stakes first experience before entering any graded district.

**Design rules:**
- No competitive scoring. Orientation scenario completion is binary: done or not done.
- The "patient" is a fellow provider, not a real emergency. The setting is a station drill.
- Lexi provides explicit step-by-step coaching during the scenario — more directive than normal coaching, framed as platform guidance rather than clinical instruction.
- After orientation completes, the user is never forced back. Replay is opt-in from the home page.
- The orientation map uses the same map rendering system, node structure, and Lexi walk mechanics as all other maps. No new map engine is needed.

---

## 2. First-Login Detection and Routing

### Backend

Add a nullable `orientation_completed_at` column (DateTime) to the `users` table via a non-destructive migration. NULL means orientation has never been completed.

```python
orientation_completed_at = Column(DateTime, nullable=True, default=None)
```

The existing `/api/me` endpoint includes this field in the user profile response:

```json
{
  "orientation_completed_at": null
}
```

When orientation is completed (scenario narrative submitted), the backend sets `orientation_completed_at = utcnow()` on the user row via:

```
POST /api/me/orientation/complete
Body: { "session_id": "<session uuid>" }
```

The endpoint validates that the session belongs to the authenticated user and that its `scenario_id` is `"orientation_01"`. Idempotent — calling it again when already set is a no-op returning 200. All reward logic (XP, treats, badge) lives here, gated on the NULL→timestamp transition.

### Existing User Backfill

When this feature deploys, every existing user will have `orientation_completed_at = NULL` and would be forced into orientation. That is wrong — veterans should not be redirected.

The Alembic migration must include a data fix:

```sql
UPDATE users
SET orientation_completed_at = created_at
WHERE id IN (
  SELECT DISTINCT user_id FROM sim_sessions
);
```

This sets the timestamp to the user's account creation date (a reasonable proxy for "this person already knows the platform") for any user who has at least one session on record. New users with no sessions remain NULL and will go through orientation. Superusers are excluded from the NULL check on the frontend — they can always reach the home screen regardless of orientation status.

### Frontend

After login, before rendering the home page, the client checks the `/api/me` response:

```javascript
if (!user.orientation_completed_at && !user.is_superuser) {
  // Navigate directly to orientation map, bypassing home screen
  loadOrientationMap();
}
```

The home screen is never shown until orientation is marked complete. If the user closes the browser mid-orientation, they return to the orientation map on next login until completion is recorded.

---

## 3. Home Page Replay Button

When `orientation_completed_at` is non-null, a low-prominence button appears at the bottom of the home page:

> **Replay Orientation** — _Return to Station 1 for a refresher anytime._

Tapping it routes to the orientation map in replay mode. In replay mode:
- Lexi coaching cues are suppressed.
- The orientation scenario (`orientation_01`) awards no XP, treats, or badge — the completion endpoint is not called again.
- The mini-games (Nodes 2 and 3) run normally and award standard XP/treats if the user chooses to replay them. Mini-game rewards are independent of orientation status.

### Reward Summary

| Context | XP | Treats | Badge | Learning card |
|---|---|---|---|---|
| Mini-game (first run, orientation) | Standard | Standard | — | Yes — any submitted run |
| Mini-game (replay, any context) | Standard | Standard | — | Already awarded |
| Orientation scenario (first completion) | 50 flat | 3 flat | `orientation_complete` | — |
| Orientation scenario replay | 0 | 0 | — | — |

The "any submitted run" threshold for learning cards during orientation is an explicit orientation-context rule. In all other contexts (Dog Park, Notebook), the standard threshold applies (see §9 Q2).

---

## 4. Map — Station 1 Firehouse

### Visual Direction

**Art style:** Interior view of a fire station, consistent with the existing JPEG map art style used across RescueTrails districts. Warm, slightly stylized — not photorealistic. The scene shows the apparatus bay in the background with the PFD Engine visible, and the foreground showing a corridor leading to the training room and day room.

**Dimensions and format:** Same aspect ratio and format as existing district maps. A single non-pannable (or gently pannable) JPEG background. Lexi scale factor: `0.9` (interior spaces read as tighter).

**Mood:** Comfortable and familiar. This is a safe space — not an emergency scene. Morning light through bay doors. Equipment neatly stowed.

### Node Layout

Five nodes. Linear path — no branching. Lexi starts at the entry anchor on first load.

```
[Entry Anchor — Bay Door]
        |
        ▼ trail
[Node 1 — Lexi Introduction]
        |
        ▼ trail
[Node 2 — Orientation Tour Scenario]
        |
        ▼ trail
[Node 3 — CPR Metrics Drill]
        |
        ▼ trail
[Node 4 — Challenges Briefing]
        |
        ▼ trail
[Node 5 — Lexi Wrap-up]
        |
        ▼ (completion → home page)
```

**Node count rationale:** The Station 1 map is a guided onboarding path. The orientation scenario teaches the scenario UI, the CPR metrics drill satisfies the Station 1 CPR requirement, the challenges briefing introduces the pass requirements, and the wrap-up marks Station 1 complete.

#### Node 1 — Day Room: Lexi Introduction

- **Type:** Dialogue node (no scenario, no mini-game)
- **Interaction:** Tapping opens a modal. Lexi speaks to the user — introducing herself, the platform, and what's ahead in orientation.
- **Completion:** Auto-completes when the user dismisses the modal.
- **Unlock:** Available immediately on map load.

**Lexi dialogue (Run Room modal):**
> "Hey! I'm Lexi — the [agency name] dog and your Field Training Officer. I'll be with you through every scenario, offering coaching and feedback as you run calls.
>
> Before we hit the streets, let's get you oriented right here at Station 1. The Training Officer set up a quick skills drill in the training room — you'll run an assessment on your partner Jake.
>
> First, let's head into the main bay and grab your gear bag."

#### Node 2 — Training Room: Orientation Tour Scenario

- **Type:** Scenario node
- **Scenario ID:** `orientation_01`
- **Unlock:** Unlocks after Node 1 completes.
- **Completion trigger:** Narrative submitted → `POST /api/me/orientation/complete` called → debrief screen shows with a **"Start your shift"** button.

#### Node 3 — Main Bay: CPR Metrics Drill

- **Type:** Mini-game node
- **Game:** `cpr_bls_concepts` (AHA CPR metric pair match — depth, rate, ratios, CCF)
- **Rationale:** CPR is the single skill every EMS provider uses before any other. The metrics drill introduces the key numeric targets before the student enters any graded district.
- **Completion threshold:** Score at least 70%.
- **XP/treats:** Standard mini-game awards apply.
- **Unlock:** Unlocks after Node 2 completes.

**Node tap dialogue (before starting):**
> "CPR metrics. Every call — pediatric, adult, trauma — can become a cardiac arrest. Match each CPR parameter to its AHA target. Complete the drill to earn a reference card for your notebook."

#### Node 4 — Challenges Briefing

- **Type:** Dialogue node
- **Interaction:** Tapping opens the Station 1 pass/complete challenge briefing.
- **Completion:** Auto-completes when the briefing is dismissed.
- **Unlock:** Unlocks after Node 3 completes.

**Node tap dialogue (before starting):**
> "Let's review what counts for your Pediatric Patient Assessment challenge before you head into the district maps."

#### Node 5 — Lexi Wrap-up

- **Type:** Dialogue node
- **Interaction:** Tapping opens Lexi's Station 1 completion message.
- **Completion:** Marks Station 1 complete and routes to the home page/district map.
- **Unlock:** Unlocks after Node 4 completes.

---

## 5. Orientation Scenario — `orientation_01`

### Premise

The Training Officer has set up a skills drill. Your partner Jake is playing the role of a "patient" for a station assessment review. Jake is a healthy 28-year-old EMT. He has no complaints and normal vitals — this is a training exercise, not a real emergency.

The goal is not to diagnose or treat anything. The goal is to walk through the full platform workflow: chat → vitals → exams → treatments → turnover report → narrative.

### Patient

| Field | Value |
|---|---|
| Name | Jake Moreno |
| Age | 28 |
| Role | Fellow EMT playing a training patient |
| Chief complaint | "None — I'm your guinea pig today." |
| Vitals baseline | All normal (HR 72, BP 118/76, RR 14, SpO2 99%, GCS 15, Temp 98.6°F) |
| Vitals deterioration | None — flat (no time-based changes) |
| Lung sounds | Clear bilaterally |
| Skin | Normal color, warm, dry |
| Weight | 83 kg |
| PAT appearance | Normal |

### Characters

- **Jake Moreno** — the training patient. Cooperative, slightly amused at playing the patient role. Responds naturally to assessment questions. Knows he's healthy and will say so. Does not perform distress or symptoms.
- **Training Officer (NPC voice)** — station Training Officer. Appears only in the scenario description and one SSE nudge at the start. Not an interactive chat character.
- **Alex (partner)** — present and available to assist, same as all scenarios.

### Scoring

Orientation scenario scoring is **completion-based only**. There is no point total, no XP from clinical performance, and no debrief score breakdown. The debrief is a short congratulatory message from Lexi confirming the user has completed orientation.

The standard debrief LLM call is **not** made for this scenario. Instead, on narrative submission, the backend detects `scenario_id = "orientation_01"` and returns a static debrief:

```json
{
  "feedback": "You've completed your orientation at Station 1. You know the controls, you've run your first assessment, and you've submitted your first report. You're ready for the field.",
  "cta_label": "Start your shift",
  "score": null,
  "subscores": null,
  "teaching_points": [],
  "is_orientation": true
}
```

**Reward gating:** XP, treats, and badge are awarded inside `POST /api/me/orientation/complete` only when the column transitions from NULL to a timestamp. The narrative submit handler does not award anything directly — it calls the completion endpoint and the endpoint guards against double-award. Replay runs (where `orientation_completed_at` is already set) call a different code path that skips the completion endpoint entirely, so there is no farm vector through the static debrief.

XP awarded: 50 XP flat (new-user welcome reward, not clinical performance XP).  
Treats awarded: 3 treats (enough to explore the platform).  
Badge: `orientation_complete` — "Station 1 Cleared."

### Scenario JSON Outline (`orientation_01.json`)

> **Note:** This outline is illustrative. Before authoring, cross-reference every field against the canonical schema in [docs/SCENARIO_DESIGN_EMS.md](SCENARIO_DESIGN_EMS.md). Fields like `dispatch` and `scene` should match the exact structure the scenario engine expects. The `is_orientation` and `orientation_guidance` fields are new extensions that will need to be registered.

```json
{
  "id": "orientation_01",
  "title": "Station Skills Drill",
  "is_orientation": true,
  "impression_challenge": { "enabled": false },
  "dispatch": "Training Exercise — practice scenario with your partner Jake in the training room. No patient complaint. Normal vitals expected.",
  "scene": "Station 1 training room. Mats on the floor. Jake is seated on the bench, arms crossed, grinning. The Training Officer leans against the doorframe.",
  "patient": {
    "name": "Jake Moreno",
    "age": 28,
    "age_display": "28 y/o",
    "weight_kg": 83,
    "weight_display": "83 kg (183 lb)",
    "sex": "Male",
    "chief_complaint": "None — training patient",
    "history": {
      "allergies": "None",
      "medications": "None",
      "pmh": "None",
      "last_oral_intake": "Coffee, 20 minutes ago",
      "events": "This is a planned station skills drill.",
      "signs_symptoms": "None — healthy adult"
    }
  },
  "orientation_guidance": [
    {
      "trigger": "session_start",
      "delay_seconds": 8,
      "message": "Start by introducing yourself and your agency to Jake in the chat. Type something like: \"Hi Jake, I'm [your name] with [agency name]. I'll be doing your assessment today.\""
    },
    {
      "trigger": "after_first_message",
      "message": "Good. Now tap the **Vitals** button in the action bar at the bottom to take Jake's initial vitals."
    },
    {
      "trigger": "after_first_vitals",
      "message": "Vitals are logged. Tap **Exams** to perform your physical assessment — head-to-toe, lung sounds, whatever you want to practice."
    },
    {
      "trigger": "after_first_exam",
      "message": "Nice work. If you have any assessments or treatments to add, tap **Treatments**. When you're satisfied with your assessment, tap the orange readiness button to move to your report."
    },
       {
      "trigger": "after_first_treatment",
      "message": "Nice work. Now give Medical control a call by tapping the **Med Control** button."
    },
    {
      "trigger": "after_first_med_control",
      "message": "Take a look around and familiarize yourself with the other options. If you ever need guidance or have any questions, you can always chat with me in the Lexi panel. I can offer hints, but use them sparingly — hints don't earn credit."
    },
    {
      "trigger": "on_readiness_ready",
      "message": "You're ready to document. Tap the orange button to open your turnover report, then write your narrative. These are your patient care records."
    },
    {
      "trigger": "on_narrative_open",
      "message": "Last step — write your narrative. Tell the story of the call in plain language, start to finish."
    }
  ]
}
```

---

## 6. Lexi Orientation Guidance System

### How Guidance Cues Are Delivered

Orientation cues are **frontend-driven**, triggered by state transitions already tracked in `state`. They are not LLM-generated. Lexi renders them as a distinct message type in the chat — visually differentiated (e.g., a small coach badge, amber left border) so the user reads them as UI instructions, not roleplay.

A new module-level array `_orientationGuidance` is populated from `state.scenarioData.orientation_guidance` when `scenario.is_orientation` is true. Each step is consumed once — once a trigger fires, that step is removed from the pending list and never re-shown.

### Trigger Conditions

| Trigger key | Fires when |
|---|---|
| `session_start` | `delay_seconds` after SSE stream opens (timer-based) |
| `after_first_message` | User's first chat message is sent |
| `after_first_vitals` | First vitals action is recorded in `state.vitalsLog` |
| `after_first_exam` | First exam/body-map action is recorded |
| `after_first_treatment` | First treatment action is recorded |
| `after_first_med_control` | First message is **sent** via the Med Control modal (not on modal open — open without sending is not a completed action) |
| `on_readiness_ready` | `checkReadiness()` first shows the orange button as available |
| `on_narrative_open` | Narrative input screen is shown |

### Trigger Ordering

**The guidance system is permissive, not locking.** No UI elements are disabled to enforce cue sequence. Users may take vitals before chatting, or jump straight to exams — that is acceptable. Cues fire as their triggers are hit regardless of order; earlier-step cues that haven't fired yet remain pending and fire when their trigger eventually occurs.

**Flush on readiness unlock:** When `on_readiness_ready` fires (the orange button first appears), all still-pending cues with triggers `after_first_message`, `after_first_vitals`, `after_first_exam`, `after_first_treatment`, and `after_first_med_control` are silently discarded. At that point the student has clearly done enough to proceed — injecting missed step reminders after the fact adds noise rather than guidance.

**Rationale for permissive over locked:** Locking action bar buttons until a cue sequence is satisfied would require the orientation system to know about and modify unrelated UI components (action bar, chat input), creating coupling that makes the system fragile and hard to maintain. The cues serve as advisory prompts, not mandatory gates. A student who discovers the Vitals button before Lexi says to tap it has learned the interface faster — that's a good outcome.

### Rendering

Orientation cues render in the Lexi chat panel as a styled aside — not part of the roleplay transcript. They use `renderMarkdown()` for inline formatting (bold, etc.). Visual treatment: amber left border, "Lexi" byline, slightly smaller font than chat messages.

Cues are not sent to the LLM — they are injected client-side into the DOM only.

### Replay Mode

When the user replays orientation from the home page (`replay=true` URL param or state flag), `orientation_guidance` is not loaded. The scenario runs as a normal (non-guided) session.

---

## 7. Backend Changes Summary

| Change | File | Notes |
|---|---|---|
| Add `orientation_completed_at` column | `app/models.py` | Nullable DateTime, default None |
| Migration | new Alembic migration | Additive only |
| Include in `/api/me` response | `app/main.py` | Add field to user profile dict |
| `POST /api/me/orientation/complete` | `app/main.py` | Validates session belongs to `orientation_01`, sets timestamp, idempotent |
| Static debrief path for `orientation_01` | `app/main.py` (narrative submit handler) | Detect `is_orientation` in scenario JSON; skip LLM call; return static debrief; call `POST /api/me/orientation/complete` with session_id — all reward logic lives in that endpoint, not here |
| `orientation_01.json` | `app/scenarios/` | New scenario file; `is_orientation: true` flag |

---

## 8. Frontend Changes Summary

| Change | Notes |
|---|---|
| First-login check after `/api/me` | If `orientation_completed_at` is null and not superuser, call `loadOrientationMap()` instead of showing home screen |
| Map renderer generalization | `_renderPedsMap` currently couples map rendering to `PEDS_MAP_DATA` and `MAP_TOPOLOGY` constants and applies pediatric fog-of-war and prerequisite gate logic inline. Before the firehouse map can render, the renderer must be refactored to accept a generic map data object. The firehouse map must bypass the peds fog/gate logic entirely — it has no fog, no prerequisites, and no connection to the pediatric completion graph. This refactor is a prerequisite for all firehouse map work. |
| Orientation map definition | New SVG layout, 4 nodes, trail paths, entry anchor |
| Firehouse JPEG background | Art asset needed — interior firehouse, matches existing map style |
| Home page replay button | Shown when `orientation_completed_at` is non-null; routes to orientation map with `replay=true` |
| `_orientationGuidance` system | Module-level; populated only when `scenario.is_orientation` is true; fires cues based on state triggers; renders as styled Lexi aside in chat |
| Orientation debrief rendering | Detect `is_orientation` in debrief response; suppress score display; show completion message; render primary CTA as **"Start your shift"** (sourced from `cta_label` in debrief payload) navigating to home screen |
| Orientation map node completion state | On map load, derive per-node done/not-done from: Node 1 — localStorage key `pfd_orientation_node1_<user_id>`; Nodes 2 & 3 — user's mini-game completion records (already fetched for notebook); Node 4 — `orientation_completed_at` non-null. Render completed nodes with a checkmark; tapping still opens them but they are not required to replay. |

---

## 9. Decisions

| Question | Decision |
|---|---|
| Should orientation award the `orientation_complete` badge visually in the debrief? | Yes — displayed in the orientation debrief congratulations screen, consistent with normal badge awards. |
| Does the orientation map appear in the district selector after completion? | No — standalone entry only. The replay button is the only post-completion access path. |
| Should instructors be able to reset orientation status? | Yes — `DELETE /api/admin/users/{user_id}/orientation` nulls the column. Useful for testing and re-onboarding. |
| What happens if the user navigates away mid-orientation? | `orientation_completed_at` remains null → orientation map loads again on next login. Partially completed session is abandoned, same as any incomplete scenario. |
| Is `orientation_01` blocked from normal scenario browsers and random-call selection? | Yes — `is_orientation: true` excludes the scenario from any endpoint or UI that returns a playable scenario list. It can still be started via direct session API call (useful for testing/replay) but must not appear in any browsing UI. |
| Does orientation map fog of war apply? | No. All four nodes are visible from the start. Nodes unlock sequentially but are always visible — no fog overlay. |
| **Q1 — Orientation mini-game rewards** | Standard XP and treats apply for both History Maker and GCS Calculator. Learning cards are awarded on any submitted run during orientation (see Q2). |
| **Q2 — Learning card threshold during orientation** | Any submitted run awards the learning card, regardless of score. Rationale: the goal is to introduce the feature, not gate reference material behind performance. The standard 70%+ threshold applies everywhere else (Dog Park, Notebook). This is an explicit orientation-context exception, documented in §3 (Reward Summary). |
| **Q3 — Existing users with zero sessions** | Accounts with zero sessions and `orientation_completed_at = NULL` will be routed into orientation. This is the correct behavior — a registered account with no completed sessions genuinely hasn't used the platform. Admin-created bulk/test accounts are handled via the superuser bypass (superusers are never routed to orientation) or by the admin reset endpoint. No account-age logic is added. |
| **Q4 — `orientation_01` in scenario selection** | Blocked from all browsing UIs. The `is_orientation: true` flag is the authoritative gate — any endpoint that lists or randomly selects scenarios must filter it out. |
| **Q5 — Turnover flow vs old DMIST** | Orientation teaches the current "turnover patient care when ready" flow: orange readiness button → turnover report → narrative. The old DMIST screen is not referenced. Guidance cues and the premise text have been updated accordingly. |
| **Q6 — Orientation node completion persistence** | Each node tracks its own completion state, derived from existing server-side records where possible. **Node 1** (intro dismiss) and **Node 4** (challenges briefing dismiss) are local Station 1 progression flags. **Node 2** (`orientation_01`) is complete when the orientation scenario completion record exists. **Node 3** (`cpr_bls_concepts`) is complete when the best CPR metrics drill score is at least 70%. **Node 5** (wrap-up) is complete when `orientation_completed_at` is non-null. On the map, completed nodes render a visual checkmark/done state. Tapping a completed node still opens it — replay is always allowed — but the node does not need to be re-completed to progress. |

---

## 10. Implementation Order

1. **Map renderer generalization** — refactor `_renderPedsMap` to accept a generic map data object; extract peds-specific fog/gate logic so the firehouse map bypasses it cleanly. This unblocks all map work.
2. **Backend schema** — add `orientation_completed_at` to User model; write Alembic migration with backfill for users who have existing sessions.
3. **`orientation_01.json`** — author scenario file per canonical schema; include `orientation_guidance` array; set `is_orientation: true`; verify fields against SCENARIO_DESIGN_EMS.md before use.
4. **Scenario exclusion** — filter `is_orientation: true` scenarios from all scenario-list endpoints and UI selectors.
5. **`POST /api/me/orientation/complete`** endpoint — accepts `{ session_id }`, validates session belongs to current user and `scenario_id = "orientation_01"`, transitions NULL→timestamp, awards XP/treats/badge in that transition only.
5. **Static debrief path** — detect `is_orientation` in narrative submit handler; skip LLM; return static debrief; invoke completion endpoint.
6. **First-login routing** — frontend check after `/api/me`; bypass home screen when null and not superuser.
7. **Orientation map SVG and nodes** — firehouse layout, 4 nodes, entry anchor, trail paths.
8. **Firehouse JPEG art** — coordinate with art direction; placeholder acceptable for dev.
9. **`_orientationGuidance` system** — trigger detection (permissive), flush on readiness, message injection, styled rendering.
10. **Orientation debrief view** — static completion screen with badge and CTA.
11. **Home page replay button** — conditional on `orientation_completed_at` non-null.
12. **Superuser reset endpoint** — low priority; add after core flow is working.
