# User Notes — Feature Design Document

**Project:** RescueTrails with Lexi  
**Status:** Phase 1 + Phase 2 implemented  
**Last Updated:** 2026-04-26 (rev 3 — Phase 2 complete)

---

## 1. Overview

### Goal

Let students capture personal learning notes after a scenario run and organize them into a searchable Notebook. Notes serve as a study aid, reinforcing debrief feedback and letting students track patterns in their own performance across scenarios.

### What This Is Not

- A social or shared feature. Notes are strictly personal — no sharing, no instructor visibility, no agency scope.
- A replacement for the debrief or feedback system. Notes supplement; they do not replace scored feedback.
- An LLM feature at launch. AI search and summarization are deferred until the base feature is stable and validated.

---

## 2. Phased Scope

The feature request mixed a concrete MVP with at least three speculative extensions. This doc splits it into four phases with clear phase gates.

### Phase 1 — MVP (target)

- Note creation button on the post-scenario debrief/feedback page
- Auto-populated `scenario_id` and `session_id` from the active debrief context
- Plain text body with title; 200-char title cap, 2 000-char body cap
- Comma-separated tags input (max 10 tags, 50 chars each); no tag management UI
- Notes viewable from the scenario history page (per-run count badge + inline list)
- CRUD API: create, read, update, delete

**Phase 1 is the design target for this document.** Phases 2–4 are scoped here for architectural awareness but are not designed to implementation detail.

### Phase 2 — Notebook Page ✅ Implemented (2026-04-26)

- `screen-notebook` screen added to `showScreen()` hide list; entry via **📓 Notebook** button on the home screen bottom utility row
- Note cards with title, scenario label, relative timestamp, `line-clamp-3` body preview, and tag chips
- Filter bar: keyword search (250ms debounce, client-side), scenario dropdown (populated from note metadata × `state.allScenarios`), tag chip toggles with active highlight — all client-side after full fetch
- Standalone note creation from Notebook "+ New Note" button (no `session_id`; optionally picks `scenario_id` from active filter)
- Save handler refreshes Notebook page when it is the active screen
- See §5.3 for full layout, wireframes, card anatomy, and modal designs

**Implementation note:** Filter is client-side (full fetch of `GET /api/notes`, filter in JS) rather than server-driven `ILIKE` as originally scoped. This is correct for Phase 2 note counts (expected to be small). If a user accumulates hundreds of notes, migrate to server-side pagination + `ILIKE` in a future pass.

### Phase 3 — Rich Text and AI

- Markdown input with live preview (reuse existing `renderMarkdown` pipeline)
- Body cap raised to 10 000 chars
- AI-assisted search or summarization (LLM output treated as untrusted; never used for scoring)
- Minigame education page integration into Notebook (deferred until minigame content is stable)

### Phase 4 — Gamification Hooks

- Small XP or treat award for first note on a new scenario (encourages review behavior)
- "Notebook streak" badge concept
- Design gated on Phase 2 validation data showing engagement with the note feature

---

## 3. Data Model

### New table: `user_notes`

```sql
CREATE TABLE user_notes (
    id          VARCHAR   PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id     VARCHAR   NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id  VARCHAR   REFERENCES sessions(id) ON DELETE SET NULL,
    scenario_id VARCHAR   NULL,           -- denormalized from session for fast filtering
    title       VARCHAR(200) NOT NULL,
    body        TEXT      NOT NULL,
    tags        JSONB     NOT NULL DEFAULT '[]',
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX ix_user_notes_user_id     ON user_notes(user_id);
CREATE INDEX ix_user_notes_scenario_id ON user_notes(user_id, scenario_id)
    WHERE scenario_id IS NOT NULL;
```

### Design decisions

**`session_id` vs. `scenario_id`:** Three valid link states exist:

| State | `session_id` | `scenario_id` | Created from |
|-------|-------------|--------------|--------------|
| Session note | set | set (copied from session) | Debrief page |
| Scenario note | null | set (user-supplied) | Notebook Phase 2 |
| Free note | null | null | Notebook Phase 2 |

`session_id` is nullable and points to the specific run that prompted the note. `scenario_id` is denormalized onto the row for direct filtering without a join. When both are present, `scenario_id` must match `session.scenario_id` (validated on create). A standalone note may carry a `scenario_id` without a `session_id` — this is intentional for study notes written outside an active run.

**No agency column.** Notes are user-personal. They persist across agency changes and are not visible to instructors or admins. This keeps the trust model simple.

**`tags` as JSONB array.** No separate tags table at this scale. Tags are user-defined strings stored as a JSON array. Validated at the API layer: max 10 elements, max 50 chars each, deduplicated on write.

**`body` as plain `TEXT`.** Phase 1 enforces a 2 000-char cap at the API layer, not via a column constraint, so Phase 3 can raise the cap without a migration. The column itself is unconstrained.

**No `body_format` column in Phase 1.** All Phase 1 bodies are plain text. Phase 3 will add a `body_format VARCHAR(20) NOT NULL DEFAULT 'plain'` column (additive migration) and begin accepting `'markdown'`. Until then, the column is absent and rendering is always plain text.

**`updated_at` maintenance.** The SQLAlchemy ORM column is declared with `onupdate=datetime.utcnow` so every `session.flush()` on a dirty `UserNote` instance automatically refreshes the timestamp. Route handlers do not set it manually. No DB trigger is needed.

---

## 4. API Surface

All endpoints require an authenticated user (`current_user` from the existing JWT dependency). All queries scope to `current_user.id` — no cross-user access is possible.

**Agency context.** Notes are intentionally outside agency context. The `get_current_user` dependency (JWT auth only) is sufficient; `get_active_context` is not required and not used. Notes are personal records that persist across agency membership changes. The only place agency context touches notes is indirectly: `session_id` ownership is validated against `session.user_id`, and sessions do carry an `agency_id`. That check confirms the user owns the session; it does not gate on agency membership.

### 4.1 Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/notes` | Create a note |
| `GET` | `/api/notes` | List the current user's notes (filterable) |
| `GET` | `/api/notes/{note_id}` | Get a single note |
| `PUT` | `/api/notes/{note_id}` | Full update (title, body, tags) |
| `DELETE` | `/api/notes/{note_id}` | Delete a note |

### 4.2 Request / Response shapes

**POST `/api/notes`**

```json
{
  "title": "...",
  "body": "...",
  "session_id": "uuid-or-null",
  "scenario_id": "peds_trauma_01_soft_tissue-or-null",
  "tags": ["airway", "pediatric"]
}
```

Response: `201` with the created note object.

All note responses include a derived read-only field `scenario_display_name` (string or null) resolved server-side from the scenario catalog. This is never persisted — it is computed on every read from the scenario JSON title. If the `scenario_id` is not found in the catalog (e.g. a future scenario not yet shipped), the field returns null and the client falls back to displaying the raw `scenario_id`.

**GET `/api/notes`** — query parameters

| Param | Type | Description |
|-------|------|-------------|
| `session_id` | string | Filter to notes for a specific run (Phase 1 history page use) |
| `scenario_id` | string | Filter to notes for a scenario across all runs (Phase 2 Notebook use) |
| `tags` | comma-separated | Notes that contain ALL listed tags |
| `q` | string | Case-insensitive keyword search (title + body) |
| `limit` | int (default 50, max 200) | Pagination |
| `offset` | int (default 0) | Pagination |

`session_id` and `scenario_id` filters are mutually exclusive. If both are provided, return `400`.

**PUT `/api/notes/{note_id}`**

```json
{
  "title": "...",
  "body": "...",
  "tags": ["updated", "tags"]
}
```

`session_id` and `scenario_id` are immutable after creation.

### 4.3 Validation rules (enforced server-side)

- `title`: required, 1–200 chars after strip
- `body`: required, 1–2 000 chars after strip (Phase 1)
- `tags`: array, max 10 elements, each 1–50 chars after normalization; normalization is lowercase + strip whitespace, applied before dedup — `["Airway ", " airway", "AIRWAY"]` all collapse to `["airway"]`
- `session_id`: if provided, must belong to `current_user` (verify on create; 404 otherwise)
- `scenario_id`: if provided alongside `session_id`, must match `session.scenario_id`; if provided without a `session_id`, accepted as-is (user-supplied, not verified against scenario catalog)

### 4.4 Rate limiting

Create/update/delete share `rate_limit_session_write/min` (existing config). List and get endpoints are read-only user-scoped queries — no rate limit needed.

---

## 5. UI Integration Points

### 5.1 Debrief page (Phase 1)

A **"Add Note"** button is placed below the scoring summary, before the "Play Again / Home" controls. Clicking it opens a modal with:

- Title field (pre-populated with scenario name as a suggestion, editable)
- Body textarea (plain text, character counter showing remaining of 2 000)
- Tags field (comma-separated plain text input; validated and split server-side)
- Save / Cancel

On save, `POST /api/notes` fires with `session_id` and `scenario_id` from the active debrief context. Success shows a brief inline confirmation; failure shows an inline error (not a toast that overlays the score).

### 5.2 History page (Phase 1)

**Phase 1 history integration is session-centric.** Each history row represents a specific run. The notes badge on a row reflects notes for that session only, fetched with `GET /api/notes?session_id=<session_id>`. This means two rows for the same scenario correctly show independent counts and independent note lists.

Each history row gains a **notes count badge** (e.g., "2 notes") when `GET /api/notes?session_id=X` returns results for that run. Clicking the badge expands an inline list of note titles + timestamps. Clicking a note title opens the note in a read/edit modal.

Scenario-level aggregation ("all notes I've ever written about this scenario across runs") is a Phase 2 Notebook concern, accessible via `GET /api/notes?scenario_id=X`.

Notes are fetched lazily on expand, not on history page load, to avoid N+1 on initial render.

### 5.3 Notebook page (Phase 2)

#### Entry point — home screen bottom row

The Notebook button is added to the existing utility row at the bottom of `screen-menu`, alongside History and Sign out:

```html
<!-- existing row, lines ~290-297 of index.html -->
<div class="mt-6 flex items-center gap-4 flex-wrap">
  <button id="btn-menu-history"  class="menu-action-btn ui-btn ui-btn--ghost">📋 History</button>
  <button id="btn-menu-notebook" class="menu-action-btn ui-btn ui-btn--ghost">📓 Notebook</button>
  <button id="btn-admin-dashboard" class="hidden menu-action-btn menu-action-btn--admin ui-btn ui-btn--amber">🛡 Dashboard</button>
  <button id="btn-menu-logout"   class="menu-action-btn ui-btn ui-btn--ghost">Sign out</button>
</div>
```

`showScreen()` gains `"screen-notebook"` in its hide list. `btn-menu-notebook` calls `showScreen("notebook")` and triggers a note list fetch.

---

#### Screen layout

`screen-notebook` follows the Warm Parchment theme (same as `screen-menu` and `screen-history`). It uses the same `max-w-4xl mx-auto p-6` container.

```
┌──────────────────────────────────────────────────────────┐
│  ← Back       📓 Notebook            [+ New Note]        │  header row
├──────────────────────────────────────────────────────────┤
│  🔍 Search…                   [Scenario ▾]               │  filter bar
│  Tags:  [airway ×]  [pediatric ×]  [all tags shown]      │
├──────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ Note title   │  │ Note title   │  │ Note title   │   │  note cards
│  │ scenario·ago │  │ scenario·ago │  │ scenario·ago │   │  (2-col md,
│  │ body preview │  │ body preview │  │ body preview │   │   1-col sm)
│  │ [tag] [tag]  │  │ [tag] [tag]  │  │ [tag] [tag]  │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
│  … (paginated, "Load more" at bottom)                     │
└──────────────────────────────────────────────────────────┘
```

**Header row:** Back button (`← menu`, calls `showScreen("menu")`), screen title, and a **+ New Note** button (`.ui-btn.ui-btn--amber`, right-aligned) that opens the standalone note modal.

**Filter bar:**
- Search input: debounced 300 ms, sends `q` param to `GET /api/notes`
- Scenario dropdown: populated from unique `scenario_id` values in the user's notes. Backend resolves `scenario_display_name` as a derived read-only field in the note response (loaded from scenario JSON; not stored in DB). Shows "All scenarios" as the default option.
- Tag chips: unique tags from the user's full note set, rendered as toggleable pill chips below the search row. Active tag chips are highlighted amber; selecting multiple tags sends them as `tags=tag1,tag2` (AND logic). An "× clear" control appears when any tag is active.

All filters are additive and drive a fresh `GET /api/notes` call. Client does not filter locally — always queries the server to stay consistent with pagination.

**Sort order:** Most recently updated first. No sort control in Phase 2.

**Pagination:** Default limit 50. A "Load more" button appends the next page rather than replacing the list. Infinite scroll is deferred.

---

#### Note card anatomy

Cards use the existing `menu-card` / `faf2e0` card surface pattern.

```
┌──────────────────────────────────────────────┐
│ Note title                          [⋯ menu] │  title + overflow menu
│ Peds Soft Tissue Trauma  ·  2 days ago        │  scenario name + relative time
│                                               │
│ Body preview, word-bounded ellipsis…         │  body preview (plain text)
│                                               │
│ [airway]  [pediatric]                         │  tag chips (amber pill, text-xs)
└──────────────────────────────────────────────┘
```

- **Overflow menu (⋯):** Edit, Delete. Delete prompts a one-line inline confirmation ("Delete this note? [Yes] [No]") — no modal needed.
- **Clicking the card body** opens the note in the edit modal.
- **`scenario_display_name`** is shown if present; omitted if the note has no `scenario_id`.
- **Body preview** uses Tailwind `line-clamp-3` on the preview container — CSS handles word boundaries and the ellipsis natively, adapts to card width on mobile without JS string truncation.
- **Relative time** ("2 days ago", "just now") based on `updated_at`.

---

#### New Note modal (standalone — no session context)

Triggered by "+ New Note" from the Notebook header. Identical to the debrief modal (§5.1) except:

- Title field is blank (no pre-population)
- A **Scenario** selector replaces the auto-populated `scenario_id` — an optional dropdown of scenario names (same list as the filter dropdown). Defaults to "None (general note)".
- `session_id` is always null for notes created here.

On save, `POST /api/notes` is called with `scenario_id` from the selector (or null) and no `session_id`.

---

#### Note edit modal (opened from card)

Pre-populated with existing note data. Uses `PUT /api/notes/{id}` on save. `scenario_id` and `session_id` are shown as read-only metadata ("from: Peds Soft Tissue Trauma — Run on Apr 25") but are not editable.

---

#### Empty state

When the user has no notes at all:
```
📓
You haven't taken any notes yet.
Notes you add after a scenario run appear here.
[Start a scenario]
```
"Start a scenario" calls `showScreen("menu")`.

When filters are active but return no results:
```
No notes match your filters.  [Clear filters]
```

---

## 6. Security and Trust Boundaries

- **User-scoped only.** Every DB query for notes includes `WHERE user_id = :current_user_id`. There is no admin/instructor endpoint to read another user's notes.
- **No LLM in Phase 1–2.** Note body and title are user content. They are never passed to the LLM until Phase 3 AI search is designed and explicitly authorized.
- **Rendering.** Phase 1: note body is displayed as plain text, with `escapeHTML` before any `innerHTML` assignment. Phase 3: body rendered with existing `renderMarkdown`, which already escapes before applying structural tags.
- **Tag display.** Tags are user strings. Always apply `escapeHTML` before rendering into the DOM.
- **`session_id` ownership check.** On create, if a `session_id` is provided, look up the session and verify `session.user_id === current_user.id` before persisting. Return `404` on mismatch (do not leak whether the session exists).
- **No `scenario_id` catalog validation.** A user can attach a free-form `scenario_id` string to a standalone note (useful for future scenarios not yet in the catalog). The backend stores it as-is. It is never used for routing or scoring.

---

## 7. Open Questions

1. **Character cap for Phase 3.** 2 000 chars is tight for a meaningful study note. 10 000 is proposed for Phase 3 markdown mode. Should Phase 2 raise the cap before markdown is introduced, or keep it at 2 000 until markdown is ready?

2. ~~**Tags in Phase 1.**~~ **Decided:** Include a comma-separated tags input in Phase 1. No tag management UI until Phase 2.

3. ~~**Instructor visibility.**~~ **Decided:** Notes are permanently private. No `shared` flag, no instructor endpoint. The data model needs no additional column.

4. **Note count on scenario card (map/home screen).** Show note count badge on the scenario map card in addition to the history page? Low effort but may add visual noise.

5. ~~**Deletion behavior when session is deleted.**~~ **Decided:** `ON DELETE SET NULL` — notes survive session deletion, `session_id` is nulled. Notes are personal records; losing the session link does not invalidate the note.

---

## 8. Punchlist Updates Required

When Phase 1 is ready to implement:

- Replace the current open "User Notes" item in `PUNCHLIST.md` with two items: one for Phase 1 MVP and one for Phase 2 Notebook.
- Add a reference to this doc in `CLAUDE.md` under Canonical Docs.
- Add the `user_notes` migration to the migration sequence in `docs/DEVELOPMENT_GUIDELINES.md`.
