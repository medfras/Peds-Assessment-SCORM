# Repo Setup & Migration Guide (SCORM Lite)

This document is the step-by-step technical playbook for spinning off the main RescueTrails SaaS repository into the standalone `peds-assessment-scorm` project.

Before creating the standalone repo, complete the branch gate in
[`07_PILOT_READINESS_CHECKLIST.md`](07_PILOT_READINESS_CHECKLIST.md). That
checklist locks the scoring contracts, vertical-slice requirements, SCORM auth
shape, and hosted-backend pilot gate so the fork does not inherit ambiguous
product or architecture decisions.

---

## What is already implemented in the main repo

Do not re-implement these. Carry them forward into the SCORM branch as-is.

| Component | Location | Description |
|---|---|---|
| SCORM backend router | `app/routers/scorm.py` | `POST /api/scorm/auth`, `POST /api/scorm/attempts/{id}/nodes/{id}/result`, `GET /api/scorm/attempts/{id}/summary` — all three contract endpoints |
| SCORM JS wrapper | `static/js/scorm.js` | SCORM 1.2 API finder, local dev adapter, suspend_data read/write, `init`, `submitNodeResult`, `getAttemptSummary`, `finish` |
| Auth helpers | `app/auth.py` | `ScormContext`, `_create_scorm_token`, `get_scorm_context`, `_extract_scorm_token` |
| Attempt model | `app/models.py` | `ScormAttempt` table |
| Config | `app/config.py` | `scorm_integration_key`, `scorm_agency_file`, `scorm_module_id` |
| All 10 pilot scenarios | `app/scenarios/pediatric/` | Complete JSON, validated by CI |
| Agency config | `PEDS_ASSESSMENT/pfd.json` | PFD/Kent County agency profile for the SCORM deployment |
| SCORM build config | `PEDS_ASSESSMENT/scorm_config.example.json` | `module_id`, `integration_key`, `backend_base` template; copy to an environment-specific config in the SCORM branch |

---

## Phase 0: Pre-branch vertical slice gate

Do not create the standalone repo until the PAT vertical slice is verified end-to-end under real runtime conditions. This confirms the contract before any branch-specific build work begins.

**Verification steps:**

1. Start the backend locally.
2. From the browser console, call `RescueTrails.scorm.init()` with dev config. The local dev adapter in `scorm.js` activates automatically when `window.API` is not found.
3. Submit a `drill_pat` result:
   ```javascript
   await RescueTrails.scorm.submitNodeResult("drill_pat", {
     activity_type: "minigame", score: 85, completed: true, passed: true
   });
   ```
4. Confirm the returned summary has `unlocks.scenarios = false` (drill_dev not yet done).
5. Submit `drill_dev` result. Confirm `unlocks.scenarios = true`.
6. Verify suspend_data was written: check `sessionStorage["rescuetrails_scorm_dev"]` in the browser.
7. Reload the page. Confirm `init()` returns the resume state with `drill_pat` and `drill_dev` completed.

**Pass criteria:** all seven steps succeed without backend errors, unlock chain is correct, and suspend_data round-trips across a page reload.

---

## Phase 1: The "Clean Break" Repository Setup

Do not attempt to build the SCORM version on a branch of the main repository. The amount of code deletion required will make future merges impossible and risky.

**1. Duplicate and isolate:**
Open your terminal, navigate to your parent development folder, and run:
```bash
cp -r "EMS Simulator" peds-assessment-scorm
cd peds-assessment-scorm
```

**2. Sever the Git history:**
```bash
rm -rf .git
git init
git add .
git commit -m "Initial commit: Base clone from main SaaS repo"
```

**3. Link to a new remote (Optional):**
Create a new empty repo on GitHub/GitLab and push:
```bash
git remote add origin <your-new-repo-url>
git push -u origin main
```

---

## Phase 2: Ruthless Deletion

The SCORM package needs the `static/` frontend shell and a way to talk to a hosted backend. The uploaded MoodleCloud ZIP must own the learner-facing DOM and SCORM API access. We will keep the Python backend in this repo *only* for local development and eventual deployment to your server as an API/scoring service, but we will strip out SaaS features.

Deletion should happen in two passes:
1.   **Frontend packaging pass:** Remove screens/assets that cannot appear in the LMS module.
2.   **Backend hardening pass:** Remove or disable unused SaaS endpoints only after the SCORM scenario path works end-to-end.

Do not delete scenario engine, vitals engine, scoring/evidence packet code, intervention persistence, or AI guardrail code. Those are the pieces this lite deployment is meant to test for the full product.

**1. Strip the Frontend (`static/`)**
Delete the following files/folders as they are incompatible with corporate LMS training:
- `static/js/auth.js` (or any login/registration logic)
- `static/js/gamification.js` (Treats, Toy Chest, XP grinds)
- `static/img/lexi/` (Mascot assets)
- `static/img/toys/` (Toy assets)
- `static/img/map/` (The old adventure map SVG and assets)

**2. Strip the Backend (`app/`)**
Remove endpoints and models that are no longer needed to reduce attack surface and clutter:
- `app/routers/` related to teams, leaderboards, toy purchases, and user notes.
- In `app/models.py`, you can eventually prune tables like `ChallengeTeam`, `Toy`, `UserToy`, `FeedEvent`. *(Note: Do this later once the frontend is stable, to avoid breaking API dependencies prematurely).*

For the first pilot, prefer feature flags or route non-registration over deep model deletion. The fastest way to lose test value is to fork scoring/runtime behavior away from the SaaS app too early.

---

## Phase 3: SCORM API & State Refactor

Because the frontend will be unzipped and launched directly from MoodleCloud (not served by FastAPI), it cannot rely on relative paths like `/api/chat` or same-origin session cookies.

**1. Configure the existing SCORM Wrapper (`static/js/scorm.js`)**
`static/js/scorm.js` already exists in the main repo and should be carried forward into the SCORM branch. It needs to keep handling:
- `API.LMSInitialize("")` on load.
- `API.LMSGetValue("cmi.suspend_data")` to read saved map progress.
- `API.LMSSetValue("cmi.suspend_data", JSON.stringify(state))` to save map progress.
- `API.LMSSetValue("cmi.core.score.raw", finalScore)` when the Station 1 CE challenge is complete.
- `API.LMSSetValue("cmi.core.lesson_status", "passed")` when the Station 1 CE challenge is complete; otherwise keep in-progress learners `"incomplete"`.
- `API.LMSFinish("")` on exit.

The wrapper also needs:
- Defensive LMS API discovery for popup/iframe launch modes.
- API lookup must walk parent frames first, then opener frames when present, with a bounded traversal depth and safe failure diagnostics. Do not assume `window.API` is directly available.
- SCORM 1.2 only: use the `API` object and `LMS*` functions, not SCORM 2004 `API_1484_11`.
- `LMSGetLastError`, `LMSGetErrorString`, and safe console diagnostics for failed commits.
- Compact state serialization with a `v` version field.
- A fallback local development adapter for testing outside an LMS.
- No dependency on `window.open()` from inside the package; Moodle App/mobile playback can block it.

**2. Update API Routing (`static/js/app.js` or `api.js`)**
Change all relative API calls to absolute URLs pointing to your hosted backend.

Do **not** configure MoodleCloud SCORM as a remote wrapper around the hosted backend app. Moodle's SCORM `window.API` is available only to the uploaded, Moodle-served SCO page. CORS does not let a page hosted on another domain reach into Moodle's parent frame and call `LMSSetValue()` or `LMSCommit()`. The hosted backend is API-only for this pilot.

```javascript
// Change this:
// const response = await fetch("/api/chat", {...});

// To this:
const API_BASE_URL = "https://your-hosted-backend.com";
const response = await fetch(`${API_BASE_URL}/api/chat`, {...});
```

**3. SCORM bootstrap path in app.js**

Add a SCORM launch branch at the top of the app bootstrap, before the normal login flow. In the SCORM branch only:

```javascript
// At app bootstrap — SCORM branch only
if (window.RescueTrails?.scorm && window.SCORM_CONFIG) {
  const resumeState = await RescueTrails.scorm.init(window.SCORM_CONFIG);
  _applyScormResumeState(resumeState); // restore node completions + unlocks
  showScreen("scorm-station1");         // show 4-map shell, not login
} else {
  showScreen("login"); // normal SaaS path
}
```

`_applyScormResumeState(resumeState)` reads `resumeState.scores`, `resumeState.unlocks`, and `resumeState.peds_ce_challenge` and applies them to the map state. This is the only place resume state enters the frontend — do not read `cmi.suspend_data` directly in `app.js`.

**Pre-flight check:** `POST /api/scorm/auth` returns a short-lived SCORM JWT. Confirm all subsequent `authFetch` calls send `Authorization: Bearer <token>` so the SCORM path does not depend on third-party cookies inside the Moodle iframe. The SCORM token type (`"scorm"`) is accepted by `get_active_context()` in `app/auth.py`, so existing scenario/chat/debrief API calls work with the SCORM bearer token.

**4. Implement Silent Auth**

`scorm.js`'s `init(config)` handles auth automatically:
- Reads `cmi.core.student_id` and `cmi.core.student_name` from the LMS (or falls back to dev config values)
- POSTs to `POST /api/scorm/auth` with `lms_student_id`, `lms_student_name`, `module_id`, `integration_key`
- Backend provisions/resumes a `ScormAttempt`, issues a scoped JWT, sets the auth cookie, and returns resume state
- `student_name` may be empty or null; `_provision_scorm_user` in `app/routers/scorm.py` already handles this by falling back to `student_id` as the display name

Do not treat `integration_key` as a secret. Security relies on CORS origin checks, rate limits, tenant binding, and short JWT lifetimes.

**5. Add Attempt Summary Calls**

After each drill, scenario, or optional game completes, submit the result through the SCORM adapter. Implement this helper in `app.js` (SCORM branch only):

```javascript
// SCORM branch only — reverse of _SCENARIO_NODE_MAP from the backend
const _APP_TO_SCORM_NODE = {
  // Drills
  "pat":                        "drill_pat",
  "dev_sort":                   "drill_dev",
  "peds_gcs_calculator":        "drill_gcs",
  // PM1 medical scenarios
  "peds_croup_01":              "scen_croup",
  "peds_asthma_01":             "scen_asthma",
  "peds_diabetic_emergency_01": "scen_diabetes",
  "peds_febrile_seizure_01":    "scen_seizure",
  // PT1 trauma scenarios
  "peds_trauma_01_soft_tissue": "scen_laceration",
  "peds_trauma_07_head_injury": "scen_head",
  "peds_trauma_03_extremity":   "scen_bleeding",
  "peds_trauma_02_partial_choking": "scen_airway",
  "peds_anaphylaxis_01":        "scen_anaph",
  // CPR
  "peds_cardiac_arrest_01_bls": "scen_cpr",
  // Optional games
  "vitals_trend_spotter":       "game_vitals",
  "lung_sounds_matcher":        "game_lung_sounds",
  "cpr_bls_sequence":           "game_bls",
};

async function _onScormNodeComplete(appId, score, completed, mistakeTags = []) {
  if (!window.RescueTrails?.scorm) return;
  const nodeId = _APP_TO_SCORM_NODE[appId];
  if (!nodeId) return;
  const isDrill = nodeId.startsWith("drill_") || nodeId.startsWith("game_");
  try {
    const summary = await RescueTrails.scorm.submitNodeResult(nodeId, {
      activity_type: isDrill ? "minigame" : "scenario",
      score: Math.round(score),
      completed,
      passed: score >= 70,
      mistake_tags: mistakeTags,
    });
    _applyScormResumeState({ scores: summary.node_scores, unlocks: summary.unlocks });
    _renderScormHeader(summary);
  } catch (err) {
    console.warn("[SCORM] Node result submission failed:", nodeId, err);
    // Non-fatal: map state may be stale until next successful submit or resume
  }
}
```

Call `_onScormNodeComplete` at the completion point for each content type:

- **Drills (`drill_pat`, `drill_dev`, `drill_gcs`):** After the minigame submits to its `/api/me/minigames/*/submit` endpoint and receives a score back.
- **Scenarios (all PM1, PT1, CPR):** After the debrief evaluation response returns a `final_score` from the scoring pipeline.
- **Optional games (`game_vitals`, `game_lung_sounds`, `game_bls`):** After each game's submit endpoint returns.
- **`finish()` call:** On explicit logout and on `beforeunload` (best-effort): `RescueTrails.scorm.finish(await RescueTrails.scorm.getAttemptSummary())`.

**CE time tracking:** CE time accrues via the existing `CeTimeLog` endpoint. Confirm `POST /api/sessions/ce-time` (or equivalent) is reachable with SCORM-scoped tokens. If not, add `ce_time` to the SCORM token's allowed scope in `get_active_context()`.

---

## Phase 4: UI & Map Topology Refactor

**1. Reuse the production Station 1 and pediatric map surfaces**
Do not build a separate SCORM-only map shell. The SCORM package should launch
into the same learner-facing UI used by the current production app:

- First launch / incomplete orientation: `showCategoryScreen("station_1")`, using the existing Station 1 direct-node flow (`Lexi Intro` -> `Orientation Tour` -> `CPR Drill` -> `Station 1 Complete`).
- Orientation complete: `showCategoryScreen("pediatrics")`, using the existing pediatric map renderer for Map 0, PM1, PT1, and connected navigation.
- Map art, node positions, popups, locked-node handling, and production copy come from the existing `static/js/app.js` map definitions and `static/css/style.css`; SCORM must not maintain a second set of map layouts.
- Moodle/SCORM identity and resume state provide auth and LMS persistence only. Backend profile, history, progress, and CE state remain tied to the Moodle-backed SCORM learner account.

**2. Keep SCORM progress as the data bridge, not a replacement UI**
The SCORM attempt summary continues to mirror node completion, unlocks, lesson
status, and `cmi.suspend_data`. It should not replace the production map header,
node popup, Toy Quest, badge, history, or orientation UI unless a future scoped
trim explicitly removes those features.

---

## Phase 5: MoodleCloud same-origin, CORS, and auth configuration

**SCORM branch only.** MoodleCloud must serve the SCO `index.html` from the uploaded ZIP. Do not iframe, redirect to, or externally host the learner-facing app on the backend domain. A remote page cannot call Moodle's SCORM `window.API` because of browser same-origin policy, and CORS does not change that DOM-access rule.

The hosted backend is used only for API calls from the Moodle-served SCO. The critical backend configuration is CORS and token auth, not iframe embedding.

In `.env` (SCORM branch):

```
ALLOWED_ORIGINS=["https://<pfd>.moodlecloud.com","http://localhost:8000"]
```

Replace `<pfd>` with the actual PFD Moodle Cloud subdomain once confirmed. If MoodleCloud serves SCORM content from a more specific plugin/file origin, use the exact browser `Origin` header observed during the smoke test.

Backend requirements:

- `/api/scorm/auth` accepts requests from the MoodleCloud origin.
- Scenario, chat, debrief, and attempt-summary endpoints accept the SCORM JWT via explicit `Authorization: Bearer <token>` headers.
- Do not require third-party cookies for the SCORM API path; browser privacy settings may block cookies in LMS iframes.
- Backend responses do not need to be frameable for the pilot package path. Keep main-app `frame-ancestors 'none'` unless a specific backend-served diagnostic page is intentionally embedded during development.

**Moodle smoke test:** before building the full course, upload a tiny SCORM ZIP containing only `index.html`, `scorm.js`, and config. Confirm from the Moodle-served page:

1. `LMSInitialize` succeeds against Moodle's `window.API`.
2. `POST /api/scorm/auth` succeeds against the hosted backend.
3. A test node result submits to the backend.
4. `LMSSetValue("cmi.suspend_data", ...)` and `LMSCommit()` succeed.

This smoke test is the hard viability gate. Do it before UI trimming, map art, or scenario packaging polish.

---

## Phase 6: SCORM Packaging

### `imsmanifest.xml`

Create this file at the root of `scorm_build/` before packaging:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<manifest
  identifier="com.rescuetrails.pfd.station1"
  version="1.0"
  xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="
    http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd
    http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">

  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>1.2</schemaversion>
  </metadata>

  <organizations default="pfd_station1_org">
    <organization identifier="pfd_station1_org">
      <title>Station 1: Pediatric Assessment Training</title>
      <item identifier="item_station1" identifierref="resource_station1">
        <title>Station 1: Pediatric Assessment Training</title>
        <adlcp:masteryscore>70</adlcp:masteryscore>
      </item>
    </organization>
  </organizations>

  <resources>
    <resource
      identifier="resource_station1"
      type="webcontent"
      adlcp:scormtype="sco"
      href="index.html">
      <file href="index.html"/>
      <file href="js/scorm.js"/>
      <file href="js/app.js"/>
      <file href="css/style.css"/>
    </resource>
  </resources>
</manifest>
```

Rules: all paths use forward slashes (`/`); no backslashes. `imsmanifest.xml` at ZIP root, not inside a subfolder. Single SCO pointing to the local packaged `index.html`, not an external URL.

### Build script

```bash
#!/bin/bash
# build_scorm.sh — SCORM branch only

SCORM_CONFIG_FILE="${SCORM_CONFIG_FILE:-PEDS_ASSESSMENT/scorm_config.local.json}"

# 1. Build into scorm_build/
rm -rf scorm_build
cp -r static/ scorm_build/

# 2. Copy environment-specific SCORM config.
# index.html must load this JSON (or an equivalent generated JS config) before
# calling RescueTrails.scorm.init(window.SCORM_CONFIG).
cp "${SCORM_CONFIG_FILE}" scorm_build/scorm_config.json

# 3. Copy manifest to root
cp imsmanifest.xml scorm_build/

# 4. Package — imsmanifest.xml must be at ZIP root
cd scorm_build
zip -r ../pfd_station1_scorm.zip . -x "*.DS_Store" -x "__MACOSX/*"
cd ..

# 5. Verify manifest is at ZIP root
echo "Verifying manifest position:"
unzip -l pfd_station1_scorm.zip | grep imsmanifest.xml
```

**Packaging checklist:**
- SCORM 1.2 only; no SCORM 2004 sequencing/navigation or xAPI dependency
- `imsmanifest.xml` at ZIP root, not inside a subfolder
- Manifest and asset paths use forward slashes — never backslashes
- Single SCO pointing to `index.html`; all Station 1 map flow happens inside that SCO
- Learner-facing Station 1 shell is included in the ZIP and served by MoodleCloud; backend is API-only
- `SCORM_CONFIG.backend_base` injected from environment-specific config at build/load time — not hardcoded in source control
- `scorm.js` reads `backend_base` from `SCORM_CONFIG`; do not patch wrapper source with `sed`
- `index.html` does not depend on server-relative asset paths
- No redirect, iframe, or remote-launch wrapper for the hosted backend app
- `cmi.suspend_data` serialized form spot-checked to be under 4,096 characters
- No `window.open()` calls in the package flow
- Moodle activity configured for New Window launch for microphone/full-size pilot playback; verify popup behavior before learner pilot

### MoodleCloud microphone playback decision

MoodleCloud embedded SCORM playback did not expose microphone access reliably.
The pilot therefore uses Moodle's **New Window** SCORM display mode for the
scenario simulator. This gives the SCO a top-level browser context so Chrome can
request microphone permission normally, and it also restores a larger/full-size
player surface for the production scenario UI.

**Active pilot path: New Window launch**

1. In the SCORM activity settings, set **Display package** to **New window**.
2. Keep **Grading** as Highest attempt / score from SCO.
3. Keep **Completion tracking** as Completion status (passed/failed).
4. Launch in Chrome and allow the popup if prompted.
5. Verify `LMSInitialize`, `LMSCommit`, and resume still work through Moodle's
   opener-frame SCORM API bridge.
6. Open a scenario and confirm Chrome prompts for microphone permission when the
   mic button is clicked.

**Operational risk:** popup blockers may prevent launch for some learners. Add a
learner instruction near the SCORM activity: allow popups for the MoodleCloud
site if the module does not open after clicking launch.

**Embedded fallback record: Additional HTML iframe permission patch**

The guarded Additional HTML patch remains documented for auditability and for a
possible future embedded-mode retry. It was not adopted as the active pilot path
because the embedded iframe did not provide reliable microphone behavior.

1. In MoodleCloud, go to **Site administration -> Appearance -> Additional HTML**.
2. Paste the contents of
   [`moodlecloud_scorm_microphone_additional_html.html`](moodlecloud_scorm_microphone_additional_html.html)
   into **Before BODY is closed**.
3. Save changes and relaunch the SCORM activity in Chrome.
4. Confirm the SCORM iframe has an `allow` attribute containing `microphone *`.
5. Click the simulator mic button and confirm Chrome prompts for microphone permission.

The snippet is intentionally guarded:

- It only runs on `/mod/scorm/player.php`.
- It targets Moodle's SCORM iframe, normally `#scorm_object`.
- It reloads the iframe only once per page load so the browser registers the new
  permission policy.

**Risk:** the one-time iframe reload can race Moodle's SCORM player initialization
on some MoodleCloud builds. If the activity starts showing duplicate auth,
missing `LMSInitialize`, lost suspend data, or inconsistent `LMSCommit`, remove
the Additional HTML snippet and keep New Window as the pilot path.

### Uploading to Moodle Cloud

1. Log in to Moodle Cloud as admin.
2. Create a SCORM activity in the target course.
3. Upload `pfd_station1_scorm.zip`.
4. Set **Display:** New window.
5. Set **Grading:** Highest attempt; score from SCO.
6. Set **Completion tracking:** Completion status (passed/failed).
7. If Moodle App playback is in scope: disable "Protect package downloads" in Site Administration.
8. Launch as a test learner. Open dev tools → Console. Check for SCORM API errors and backend CORS/auth failures.
