# Technical Architecture: SCORM 1.2 Integration

## 1. Architecture Principle

The SCORM module is a configured deployment of the main RescueTrails application — not a separate lite build or forked codebase. The same backend, scenario runtime, scoring engine, and debrief pipeline run identically to the main app. What changes is:

- Agency and protocol config (PFD/Kent County, hard-coded — **SCORM branch only**)
- API tier (free keys with guardrails — **SCORM branch only**)
- UI surface (station dashboard trimmed to map navigation + logout — **SCORM branch only**)
- Navigation path (LMS launch → Station 1 orientation → Map 0 → PM1/PT1 branches — **SCORM branch only**)
- History/storage policy (abbreviated — **SCORM branch only**)

**Bleed-over rule:** None of the SCORM-specific configuration above is introduced into the main repo (`main` branch). Changes in the main repo must remain safe for the main program. The SCORM branch diverges only on configuration, UI surface, and LMS wiring — not on scoring logic, scenario content, or backend architecture.

**LMS:** Moodle Cloud using native SCORM 1.2. The SCORM package is a ZIP uploaded to Moodle Cloud and served from the Moodle Cloud domain. The hosted backend is a separate API/scoring service only; it must not be the learner-facing SCORM launch page.

**Standards decision:** Station 1 ships as SCORM 1.2 only. Do not target SCORM 2004 or xAPI for the pilot. Moodle Cloud core does not fully support SCORM 2004 Navigation and Sequencing, and xAPI requires third-party launch/reporting plugins. The pilot must avoid plugin-dependent delivery.

The uploaded SCO contains the learner-facing Station 1 frontend shell: `index.html`, JavaScript, CSS, maps, and any static assets needed to render the orientation/map/scenario UI inside Moodle's SCORM player. The SCORM client handles LMS lifecycle (initialize, commit, finish), mirrors compact progress state for resume, and calls the hosted backend over HTTPS for clinical runtime services. All clinical state, scoring, and grade calculation live in the hosted backend.

**Same-origin constraint:** SCORM JavaScript can call Moodle's `window.API` only when the SCO page itself is served by Moodle Cloud. CORS does not allow a remotely hosted page to access Moodle's parent-frame SCORM API. Therefore the pilot must not use a Moodle SCORM package that simply redirects to, iframes, or launches `https://our-backend/...` as the primary app. External hosting is allowed only for backend API endpoints and ordinary fetch/WebSocket calls from the Moodle-served SCO.

---

## 1.1 Moodle Cloud Package Requirements

The Station 1 package must satisfy Moodle Cloud's native SCORM 1.2 expectations:

- Package format: ZIP file containing `imsmanifest.xml` at the ZIP root.
- SCO structure: single SCO launched from root `index.html`; the internal Station 1 orientation/map flow is handled inside the SCO.
- Frontend hosting: `index.html` and the learner-facing app shell are served from the uploaded MoodleCloud ZIP. Do not point the manifest at an external URL, iframe the hosted backend app, or rely on a remote page to access `window.API`.
- Manifest: SCORM 1.2 manifest only, with schema-valid resource and launch references.
- Paths: use forward slashes (`/`) in all manifest and asset paths. Do not use Windows backslashes (`\`), which can fail on Android/Moodle App playback.
- Runtime API: locate the SCORM 1.2 `API` JavaScript object from the parent/opener frame chain and use `LMSInitialize`, `LMSGetValue`, `LMSSetValue`, `LMSCommit`, and `LMSFinish`.
- Data model: use SCORM 1.2 `cmi.core.*` values, including `cmi.core.lesson_status` and `cmi.core.score.raw`.
- Suspend data: keep `cmi.suspend_data` under the 4,096-character SCORM 1.2 limit.
- JavaScript: learners must have JavaScript enabled.
- Mobile/app compatibility: do not rely on `window.open()` calls from inside the SCO. Prefer embedded/same-window flow.
- Moodle activity launch mode: configure launch as embedded/same-window iframe for the pilot. Do not rely on Moodle "new window" launch mode, because pop-up blockers commonly prevent launch.
- Moodle App configuration: if the Moodle App SCORM player is required, Moodle Cloud's "Protect package downloads" setting must be disabled so the app can download and play the uploaded ZIP.

Non-goals for the pilot:

- No SCORM 2004 `API_1484_11`, `Initialize`, `Terminate`, `cmi.completion_status`, or `cmi.score.scaled` dependency.
- No SCORM 2004 sequencing/navigation dependency.
- No xAPI/Tin Can launch or LRS reporting dependency.
- No remote `imsmanifest.xml` URL; the full ZIP must be uploaded.
- No external/remote SCO launch page. Use LTI or AICC HACP instead if the learner-facing app must be hosted entirely off-domain.

---

## 2. Authentication Bridge

Users authenticate through the LMS. No second login is required.

1. SCORM package initializes and reads `cmi.core.student_id` and `cmi.core.student_name` from the LMS.
2. Moodle-served frontend makes a silent `POST /api/scorm/auth` to the hosted backend with: LMS student fields, a non-secret integration identifier, and the module ID.
3. Backend provisions or resumes a SCORM attempt bound to that LMS student ID, PFD agency, Kent County MCA, and EMT provider level. Returns a short-lived JWT.
4. All subsequent scenario, chat, debrief, and attempt-summary requests use the JWT.
5. On resume, the backend returns `resume_state` reflecting current node scores and unlock status, which the Moodle-served frontend applies to the map before the learner sees it.

**Auth response shape:**
```json
{
  "access_token": "jwt...",
  "token_type": "bearer",
  "expires_in_seconds": 3600,
  "scorm_attempt_id": "scorm_pfd_2026_000001",
  "tenant": "pfd_station1",
  "agency": "pfd",
  "mca": "mi_base",
  "provider_level": "EMT",
  "resume_state": {
    "scores": {
      "drill_pat": 87, "drill_dev": 0, "drill_gcs": 0,
      "scen_asthma": 0, "scen_croup": 0, "scen_diabetes": 0, "scen_seizure": 0,
      "scen_airway": 0, "scen_anaph": 0, "scen_bleeding": 0, "scen_head": 0, "scen_laceration": 0,
      "scen_cpr": 0,
      "game_bls": 0, "game_lung_sounds": 0, "game_vitals": 0
    },
    "completed": {
      "drill_pat": true, "drill_dev": false, "drill_gcs": false,
      "scen_asthma": false, "scen_croup": false, "scen_diabetes": false, "scen_seizure": false,
      "scen_airway": false, "scen_anaph": false, "scen_bleeding": false, "scen_head": false, "scen_laceration": false,
      "scen_cpr": false,
      "game_bls": false, "game_lung_sounds": false, "game_vitals": false
    },
    "unlocks": { "scenarios": false, "map3": false },
    "status": "incomplete",
    "peds_ce_challenge": { "complete": false }
  }
}
```

**Trust boundary:** Any value bundled inside SCORM JavaScript is visible to the learner. The integration identifier is not a secret. Backend security relies on: strict CORS/origin checks, tenant binding, rate limits, short token lifetimes, and SCORM JWTs scoped to the SCORM tenant only (no admin, agency-management, leaderboard, store, or notes APIs).

**SCORM API locator:** `static/js/scorm.js` must find the SCORM 1.2 `API` object by walking parent frames first, then opener frames when present, with a bounded traversal depth and safe failure diagnostics. It must not assume `window.API` is directly available.

**Cross-origin boundary:** The API locator only searches Moodle parent/opener windows from the Moodle-served SCO. Backend API responses are never expected to expose, proxy, or access `window.API`. CORS is for backend `fetch`/WebSocket calls only; it does not solve SCORM API parent-frame access for remote pages.

**LMS identity fallback:** `cmi.core.student_id` is required for attempt binding. `cmi.core.student_name` is optional and may be empty, null, or a placeholder in Moodle. The auth request and backend must tolerate missing names and fall back to a safe display label derived from `student_id` or a generic learner label. Never reject an otherwise valid launch solely because `student_name` is absent.

---

## 3. Course and Navigation Flow

**LMS launch → Silent auth → Station 1 orientation → Map 0 — Foundation Drills → PM1/PT1 branches → Map 3 CPR**

There is no home page, hub, station selection screen, broader RescueTrails map, or second course shell in the SCORM deployment. After silent auth, the learner immediately enters the Station 1 orientation. When orientation is completed, the learner proceeds directly to the current Map 0 Foundation Drills screen.

The entire SCORM package is this Station 1 course flow:

| Map | Unlock condition | Nodes |
|-----|-----------------|-------|
| Map 0 — Foundation Drills | Always available | `drill_pat`, `drill_dev`, `drill_gcs` |
| PM1 — Pediatric Medical | `unlocks.scenarios = true` (both required drills complete) | `scen_croup`, `scen_asthma`, `scen_diabetes`, `scen_seizure` |
| PT1 — Pediatric Trauma | `unlocks.scenarios = true` (same gate) | `scen_laceration`, `scen_head`, `scen_bleeding`, `scen_airway`, `scen_anaph` |
| Map 3 — CPR | `unlocks.map3 = true` (PM1 ≥ 2 + PT1 ≥ 2 complete) | `scen_cpr` |

Optional games (`game_vitals`, `game_lung_sounds`, `game_bls`) are accessible from any map at any time via a sidebar or launcher.

No other main-app navigation surfaces are rendered: no Training Center, challenges, trivia, leaderboard, store, or XP display.

On LMS resume: if orientation is incomplete, the learner returns to the Station 1 orientation. If orientation is complete, the SCORM wrapper reads `cmi.suspend_data`, parses `unlocks.scenarios` and `unlocks.map3`, applies unlock state to the map, and presents the appropriate Station 1 map — no home page, hub, or station picker.

---

## 4. Persistent State (`cmi.suspend_data`)

SCORM 1.2 limits `cmi.suspend_data` to 4,096 characters. The mirror stores only compact visible progress. The backend attempt record is authoritative.

**Suspend data shape (v3 — 16 nodes, well under 4,096 characters):**
```json
{
  "v": 3,
  "attempt": "scorm_pfd_2026_000001",
  "scores": {
    "drill_pat": 87, "drill_dev": 0, "drill_gcs": 0,
    "scen_asthma": 0, "scen_croup": 0, "scen_diabetes": 0, "scen_seizure": 0,
    "scen_airway": 0, "scen_anaph": 0, "scen_bleeding": 0, "scen_head": 86, "scen_laceration": 0,
    "scen_cpr": 0,
    "game_bls": 0, "game_lung_sounds": 0, "game_vitals": 0
  },
  "completed": {
    "drill_pat": true, "drill_dev": false, "drill_gcs": false,
    "scen_asthma": false, "scen_croup": false, "scen_diabetes": false, "scen_seizure": false,
    "scen_airway": false, "scen_anaph": false, "scen_bleeding": false, "scen_head": false, "scen_laceration": false,
    "scen_cpr": false,
    "game_bls": false, "game_lung_sounds": false, "game_vitals": false
  },
  "unlocks": {
    "scenarios": false,
    "map3": false
  },
  "status": "incomplete",
  "ce": {
    "complete": false,
    "ce_seconds": 0,
    "pm1_completed": 0, "pm1_required": 2,
    "pt1_completed": 0, "pt1_required": 2,
    "cpr_done": false,
    "opt_games_completed": 0, "opt_games_required": 2
  }
}
```

**Version note:** `"v": 3` — bumped when 4-map 16-node topology was adopted. Any suspend data with `v < 3` is discarded on resume and the learner starts from the backend's authoritative attempt state.

**Save trigger:** After every node result submitted — `LMSSetValue("cmi.suspend_data", ...)` + `LMSCommit("")`.

**Load trigger:** At `index.html` load — `LMSGetValue("cmi.suspend_data")`, parse and validate version, apply `unlocks` and `completed` state to map.

**Hard constraints — never write to `cmi.suspend_data`:**
- Chat transcripts
- Debrief markdown or AI-generated text
- Raw AI output or prompt content
- Scenario JSON or clinical audit evidence
- Free-text narrative content
- Provider error messages

---

## 5. History and Storage Policy

The SCORM deployment does not store full session history. This limits backend storage costs and keeps the data footprint appropriate for a training deployment where the LMS is the system of record.

| Data type | Main app | SCORM deployment |
|---|---|---|
| Chat transcript | Stored | Not persisted after debrief generation |
| Debrief text | Stored | Returned to client; not stored server-side |
| Session full log | Stored | Not stored |
| Attempt record | Full | Scores, timestamps, completion flags, mistake tags only |
| Evidence packets | Long retention | Time-limited retention (TBD before pilot launch) |
| Node scores | Stored | Stored (required for grading) |
| `cmi.suspend_data` | N/A | Compact v3 mirror only (see Section 4) |

---

## 6. LMS Status Reporting

Lesson status and score are written to the LMS when the CE challenge is complete. The CE challenge is the authoritative pass condition — not a raw numeric grade threshold.

**CE challenge criteria (all must be met):**
- Orientation completed
- `drill_pat` + `drill_dev` both completed
- PM1: any 2 of 4 scenarios completed
- PT1: any 2 of 5 scenarios completed
- `scen_cpr` completed
- Any 2 of 3 optional games completed
- Total CE time ≥ 3600 s (60 min)
- Minimum XP ≥ 1100

**Grade formula (backend-computed, written to `cmi.core.score.raw` when CE complete):**
`(drill_grade × 0.20) + (scenario_avg × 0.80)`

- `drill_grade` = best 2 of 3 drill scores
- `scenario_avg` = average of all completed scenario scores (PM1 + PT1 + CPR); null until 2 PM1 + 2 PT1 + CPR all complete

**LMS status reporting (from `scorm.js finish()`):**

```javascript
function finish(summary) {
  if (!_api) return;
  if (summary) {
    const ceComplete = !!(summary.peds_ce_challenge && summary.peds_ce_challenge.complete);
    if (ceComplete && summary.final_score !== null && summary.final_score !== undefined) {
      _api.LMSSetValue("cmi.core.score.raw", String(summary.final_score));
    }
    _api.LMSSetValue("cmi.core.lesson_status", ceComplete ? "passed" : "incomplete");
  }
  _api.LMSFinish("");
}
```

**Status values:**
- `"passed"` — CE challenge complete (`peds_ce_challenge.complete === true`)
- `"incomplete"` — learner is still in progress (never `"failed"` for in-progress)

Intermediate node completions trigger `LMSSetValue("cmi.suspend_data", ...)` + `LMSCommit("")` to persist progress but do not write `lesson_status` until `finish()` is called.

---

## 7. Free API Key Guardrails

The SCORM deployment uses free-tier API keys (Groq or equivalent). Guardrails are required to prevent a single learner from exhausting shared daily limits.

| Guardrail | Mechanism |
|---|---|
| Per-session token budget | Backend enforces a max token count per scenario session; rejects requests over the cap |
| Per-minute rate limit | Backend rate-limits chat requests per active JWT session |
| Daily cap monitoring | Backend monitors provider key usage; activates graceful degradation before the limit is hit |
| No background AI calls | Map navigation, drill transitions, and unlock state changes produce no AI calls |

**Degradation behavior on `429` or provider timeout:**
- Scenario UI shows a clear "AI temporarily unavailable — please try again in a moment" message
- Current node remains resumable (no progress lost)
- Minigames and map navigation continue to work
- Backend logs the provider failure with a structured diagnostic code
- Raw provider errors are never returned to the SCORM client

---

## 8. Security Constraints

- SCORM JWTs are scoped to the `pfd_station1` tenant and the current attempt only. They cannot access admin, agency-management, notes, toys, teams, leaderboard, or store APIs.
- Auth endpoint is rate-limited independently of chat/debrief endpoints.
- LMS student name and ID are treated as untrusted strings — they identify the attempt but do not grant permissions.
- CORS is restricted to the Moodle Cloud SCO origin and approved local development origins for backend API calls.
- The hosted backend is API-only for the pilot package path. It does not need to be iframe-embedded by Moodle, and the SCO must not iframe backend-hosted UI pages.
- If any backend-served diagnostic/test UI is intentionally embedded during development, configure CSP narrowly for that test path only. Do not treat CSP iframe allowances as a substitute for serving the SCO from Moodle Cloud.
- Backend auth must work from the Moodle-served SCO without depending on third-party cookies. Prefer explicit SCORM JWT bearer headers for API calls; cookies may be blocked in LMS iframes by modern browser privacy settings.
- No internal IDs, prompt bodies, stack traces, or raw provider errors are returned to the SCORM client.
- Provider failure events are logged server-side with structured diagnostics; the frontend receives only safe diagnostic codes.
