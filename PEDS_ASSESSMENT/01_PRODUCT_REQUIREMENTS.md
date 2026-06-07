# Product Requirements Document: Station 1 Pediatric Assessment Training

**Project:** Station 1 Pediatric Assessment Training — PFD/Kent County SCORM Module
**Target Audience:** EMTs, PFD agency, Kent County protocols
**Deployment:** SCORM 1.2 package, Moodle Cloud native SCORM activity, hosted backend

## 1. Overview

This module is a configured deployment of the main RescueTrails application, not a separate codebase or a stripped-down lite build. The same backend, scoring engine, scenario runtime, and debrief pipeline run identically to the main app. What differs is configuration, API tier, UI surface, and navigation path.

The module covers: Pediatric Assessment Triangle (PAT), pediatric developmental stages, GCS calculation, diabetic emergency, asthma, closed head injury, and febrile seizure — all at BLS/EMT scope under Kent County/Michigan protocols.

## 2. Learning Objectives

By the end of this module, the EMT will be able to:

1. Rapidly formulate a "sick vs. not sick" clinical impression using the Pediatric Assessment Triangle.
2. Match pediatric developmental stage to expected behavior, appropriate communication approach, and normal vital sign ranges.
3. Calculate pediatric GCS with eye, verbal, and motor subscores and explain what the score means clinically.
4. Differentiate between diabetic, respiratory, neurological, and seizure emergencies using BLS assessment tools.
5. Apply Kent County protocols for SMR, oxygen delivery, oral glucose, and ALS handoff decisions.

## 3. What Is the Same as the Main App

- All backend services: session management, vitals engine, intervention engine, deterministic scoring, checklist evaluation, debrief generation, evidence packet
- All scenario JSON, checklist items, and rubric logic
- All minigame mechanics
- SCORM auth bridge (JWT, attempt tracking, suspend-data mirror)
- AI chat and debrief generation pipeline
- Immersive scenario UI

## 4. What Is Different from the Main App

### 4.1 Agency and Protocol Configuration

PFD agency settings and Kent County protocols are hard-coded in the SCORM deployment configuration. The learner does not select an agency or protocol set. There is no agency picker. The MCA binding is fixed.

| Setting | Value |
|---|---|
| Agency | PFD |
| MCA / Protocol set | Kent County / `mi_base` |
| Provider level | EMT |
| Jurisdiction | Michigan |

These are deployment-time config values, not runtime user selections. The backend SCORM auth endpoint provisions attempts with these values baked in.

### 4.2 API Tier

SCORM deployment uses free API keys with appropriate rate limits and guardrails:

- **Per-session budget:** A fixed token cap per scenario session prevents any single session from exhausting daily limits.
- **Per-minute rate limit:** Chat requests are rate-limited server-side per active session to avoid burst exhaustion.
- **Daily cap monitoring:** Provider key usage is monitored against free-tier daily limits. Graceful degradation fires before the limit is hit.
- **Graceful degradation:** On rate-limit (`429`) or provider timeout: scenario UI shows a clear "AI temporarily unavailable" message; the node remains resumable; minigames and map navigation continue to work without AI.
- **No background AI calls** during map navigation or drill transitions.

Groq free-tier assumptions for 2–5 simultaneous learners: short scene-chat prompts, compact scenario context, debrief only after completion. Actual limits must be verified in the Groq console before any department-wide rollout.

### 4.3 Station Dashboard UI

The station dashboard is trimmed to the minimum surface needed for training navigation and LMS reporting. Features present in the main app but not in the SCORM deployment:

| Feature | Main app | SCORM deployment |
|---|---|---|
| Map navigation | ✓ | ✓ (Station 1 pediatric flow only) |
| Logout / sign out | ✓ | ✗ (Moodle owns launch/session exit) |
| Station 1 / scenario launch | ✓ | ✓ |
| Challenges | ✓ | ✓ (agency challenges only) |
| Training Center | ✓ | ✓ (pilot-safe drills only) |
| Trivia | ✓ | ✓ |
| Leaderboard | ✓ | ✓ (same SCORM agency; Moodle-provisioned learner names) |
| Store / toy purchasing | ✓ | ✗ |
| Treat economy | ✓ | ✓ (pilot reward rules only) |
| XP and rewards display | ✓ | ✓ |
| Home page map / hub | ✓ | ✓ (production Home after orientation) |
| Agency/protocol picker | ✓ | ✗ |
| User registration | ✓ | ✗ (LMS identity) |
| History archive | ✓ | ✓ (learner-facing completed attempts; no account notes) |

### 4.4 Navigation Flow

Main app flow: Login → Home → (hub) → Station selection → Map.

SCORM flow: LMS launch → Silent auth → Station 1 orientation → production Home → Station 1 pediatric maps (Map 0, PM1, PT1, Map 3 CPR). Moodle owns identity; the SCORM package does not expose login, registration, account settings, sign out, agency switching, or protocol selection.

On LMS resume, incomplete orientation returns to the Station 1 orientation. Once orientation is complete, the SCORM wrapper reads `cmi.suspend_data`, restores node completion state, and returns the learner to the production Home or last saved pediatric map state.

### 4.5 History and Storage Policy

Learners can view their own completed scenario history/debrief summaries in the SCORM deployment. Full raw session logs are still not stored as a learner-facing archive:

- **Chat transcripts:** Used for debrief generation, then not persisted beyond the session. Not stored in the LMS.
- **Debrief summaries:** Available to the learner through the completed-attempt history surface.
- **Attempt records:** Backend stores node scores, timestamps, completion flags, and mistake tags only. No full conversation log.
- **Evidence packets:** Stored with time-limited retention (duration TBD before pilot launch); used for scoring audit only.
- **`cmi.suspend_data`:** Compact node-score + unlock mirror only. No transcripts, debrief markdown, AI output, or clinical evidence (see `03_SCORM_ARCHITECTURE.md`).

This policy limits backend storage costs and keeps the data footprint appropriate for a training deployment that is not the system of record. The LMS is the system of record for completion and final grade.

## 5. Authority Boundaries

The SCORM client is not an authoritative clinical system. It handles LMS lifecycle and mirrors progress state; the backend computes all scores and grades.

**SCORM client owns:**
- LMS launch, `LMSInitialize`, `LMSCommit`, `LMSFinish`
- Map rendering, node buttons, local UI state, progress display
- Mirroring backend attempt results into `cmi.suspend_data`, `cmi.core.score.raw`, `cmi.core.lesson_status`

**Hosted backend owns:**
- SCORM attempt creation, resume, and final grade calculation
- Scenario session state, deterministic vitals, intervention persistence, scoring, debrief
- AI provider calls, retry behavior, rate limits, and diagnostics
- SCORM pass challenge and final score: 2 PM1 + 2 PT1 passing/on-track scenarios, 60 minutes of eligible training time, and 950 XP; `scenario_avg` is written as the LMS raw score when complete

**LMS owns:**
- Learner launch identity (`cmi.core.student_id`, `cmi.core.student_name`)
- Final completion/pass/fail record
- Course enrollment and reporting outside the simulator

## 6. Success Criteria

- **LMS Compatibility:** Module uploads cleanly to a SCORM 1.2 compliant LMS.
- **Moodle Cloud Compatibility:** Module runs in Moodle Cloud's native SCORM 1.2 player without SCORM 2004, xAPI, or SCORM Cloud/Rustici plugin dependency.
- **Package Structure:** ZIP contains `imsmanifest.xml` at the root, uses forward-slash paths, and launches a single SCO from `index.html`.
- **Runtime API:** Client finds the SCORM 1.2 `API` object and uses `LMSInitialize`, `LMSGetValue`, `LMSSetValue`, `LMSCommit`, and `LMSFinish`.
- **Launch Mode:** Moodle activity is configured for embedded/same-window launch for the pilot, not new-window launch, to avoid pop-up blocker failures.
- **Mobile/Moodle App Constraints:** Package does not rely on internal `window.open()` calls; "Protect package downloads" is verified disabled if Moodle App SCORM playback is required.
- **MoodleCloud Same-Origin:** The uploaded ZIP serves the learner-facing SCO from MoodleCloud so SCORM JavaScript can access Moodle's `window.API`. The hosted backend is API-only; CORS allows only the target MoodleCloud SCO origin(s) plus approved local development origins.
- **LMS Identity Robustness:** Launch/auth succeeds when `cmi.core.student_name` is empty or missing by falling back to `cmi.core.student_id` or a generic learner label.
- **Persistence:** A user can close the browser mid-training, relaunch from the LMS, and resume on the Station 1 map with all prior node completion preserved.
- **API Capacity:** AI responses generate in under 3 seconds during peak load (2–5 simultaneous users) using the free-tier backend. Graceful degradation fires before daily limit exhaustion.
- **Protocol Accuracy:** All scoring, feedback, and protocol references reflect Kent County / Michigan / `mi_base` MCA settings.
- **UI Clarity:** The trimmed station dashboard presents only map navigation and logout; no dead-end links, hidden features, or main-app UI elements that are non-functional in this deployment.
