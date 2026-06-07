# UI Style & Immersive Mode Design — Station 1 SCORM

## 1. Design Philosophy
The SCORM package retains the "Dual-Theme" design system from the main SaaS product but completely removes the gamification overlays (Treats, Toy Chest, XP bars).

*   **Warm Parchment (Light Mode):** Used for the Station 1 orientation, the 4 static map screens (Map 0, PM1, PT1, Map 3), and debrief modals.
*   **Urgency Dark (Sim Mode):** Used when actively treating a patient inside a scenario to simulate focus and reduce glare.

## 1.1 SCORM Course Shell

The LMS package launches directly into this single course flow:

`LMS launch → silent SCORM auth → Station 1 orientation → Map 0 Foundation Drills → PM1/PT1 branches → Map 3 CPR`

There is no landing page, login page, home hub, station selector, broader adventure map, or second module inside the package. On resume, incomplete orientation returns to the orientation screen; completed orientation resumes directly to the current Station 1 map state.

## 2. Immersive Mode Retention
To reduce typing fatigue and cognitive load, the SCORM module heavily utilizes the **Immersive Mode** mechanics.

### The Action Zone (Left Panel / Mobile Tab)
*   **Patient Briefing Card:** Displays Age, Weight, and dynamically updates with Vitals and Exam findings as they are collected.
*   **Jump Bag:** A CSS grid of available tools (Stethoscope, BP Cuff, Pulse Ox) and protocol-approved medications (Epi, Albuterol).
*   **Body Map:** An SVG silhouette of a pediatric patient. Tapping regions (e.g., Head, Chest, Abdomen) fires an immediate assessment action without typing.

### The Communication Zone (Center Panel)
*   **Quick-Tap Chips:** The 40px horizontal scrolling row above the chat input containing OPQRST and SAMPLE history-taking prompts.
*   **Chat Input:** Remains available for custom questions and free-text commands.

## 3. Pruned UI Elements (Do Not Port to SCORM Repo)
To keep the SCORM `.zip` file small and compliant, the following UI components must be ruthlessly stripped from the frontend code:

*   **Login & Registration Views:** SCORM bypasses this. The UI initializes directly to Station 1 orientation, then Map 0 after orientation completion.
*   **Agency / MCA Pickers:** Hardcoded in JS state.
*   **Leaderboards & Team Dashboards:** Social features are incompatible with standalone SCORM packages.
*   **Lexi the Mascot Avatar:** To align with departmental compliance training, the cartoon mascot is removed. AI coaching messages remain, but the avatar is replaced with a generic "Medical Director" or "Instructor" badge. The floating Lexi animation on the map is also removed.
*   **Toy Chest & Treat Wallet:** The top-right header economy displays are removed.

## 4. Map Navigation UI
Instead of the full SaaS map stack, the UI uses 4 distinct Station 1 HTML map views with CSS background images or lightweight positioned node layouts.

*   **Node Buttons:** HTML buttons placed over map locations for drills, scenarios, CPR, and optional games.
*   **State Indicators:** A green checkmark (✅) overlay appears on a door when `cmi.suspend_data` indicates a score > 0 for that node.
*   **Global Tracker:** A fixed header replaces the XP bar and shows Station 1 progress. Moodle completion is driven by PM1 count, PT1 count, and eligible training time; drills, CPR, optional games, and XP may display as progress/reward telemetry but do not block SCORM completion.

The UI should read node IDs from the SCORM manifest/config and backend attempt summary rather than hardcoding display strings. Labels and artwork can change without changing stored progress or backend attempt summaries.

## 5. AI Capacity States

When the hosted backend reports AI capacity problems, the UI should:
*   Keep the learner on the current map or scenario shell.
*   Show a clear temporary-unavailable state for live AI scenarios.
*   Preserve current progress and allow retry.
*   Continue allowing deterministic minigames and map navigation where possible.

Do not present provider failures as clinical feedback or debrief results.
