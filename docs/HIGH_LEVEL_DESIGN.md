# RescueTrails EMS Simulator — High-Level Design (HLD)
**Status:** Active Implementation
**Last Updated:** 2026-04-30 (reward/theme direction and district-map framing updated)

---

## 1. System Overview

**RescueTrails** is an AI-powered, highly interactive Emergency Medical Services (EMS) training simulator. It allows EMTs, Paramedics, and EMS students to run realistic, dynamic patient care scenarios in a browser-based environment. 

The platform uniquely blends **Strict Clinical Determinism** (state-based math engines for vitals and protocols) with **Generative AI** (for natural language roleplay and real-time coaching). It is built as a multi-tenant SaaS, supporting specific agencies, regional Medical Control Authorities (MCAs), and provider licensure levels.

### Target Audience
- **Students/Providers:** Play through scenarios, earn XP, collect district-based training rewards, and compete on leaderboards.
- **Instructors/Training Officers:** Monitor student performance, review AI-generated debriefs, and identify clinical blind spots.
- **Agency Admins:** Manage rosters, agency-specific SOPs, and equipment loadouts.

---

## 2. Architecture & Tech Stack

The application follows a modern, decoupled client-server architecture relying heavily on real-time streaming protocols.

### 2.1 Backend (API & Engine)
- **Framework:** Python / FastAPI
- **Database:** PostgreSQL (via SQLAlchemy 2.0 AsyncIO)
- **Authentication:** JWT (JSON Web Tokens) with base/active contextual scoping.
- **AI Inference:** Groq API (Async) using high-parameter open-source models for ultra-low latency.
- **Concurrency:** `asyncio` for non-blocking I/O, WebSockets, and Server-Sent Events (SSE).
- **Rate Limiting:** `slowapi` (Redis/Memory-backed) for abuse prevention.

### 2.2 Frontend (Client)
- **Stack:** HTML5, Vanilla JavaScript (ES6+), and Tailwind CSS.
- **Architecture:** Single-Page Application (SPA) feel, utilizing dynamic DOM manipulation and a state-driven approach (`state` object).
- **Real-Time Comm:** 
  - **SSE (Server-Sent Events):** Used for streaming AI chat tokens smoothly to the UI.
  - **WebSockets:** Used for real-time Vitals syncing and Multiplayer Live Team Challenges.
- **UI/UX System:** "Dual-Theme" design (Warm Parchment for menus/learning, Urgency Dark for active clinical simulations).

### 2.3 Planned Home / Navigation Direction

The planned home experience is evolving from a generic menu into a **station dashboard** that presents the major training areas as districts on a map.

Planned characteristics:
- **Station dashboard framing:** home screen reads as a firehouse / EMS station operations board rather than a game menu
- **District-map navigation:** major content categories are laid out as districts rather than flat cards
- **Professional outer framing:** visible district labels should read as EMS training areas, not whimsical biomes
- **Companion-preserved tone:** Lexi remains the companion and coach; the home IA becomes more operational and buyer-facing

Planned top-level districts:

| District | Theme | Content family |
|---|---|---|
| Pediatric Community Response District | Schools, daycares, homes, playgrounds, pediatric public/community calls | Pediatric content |
| Adult Medical Response District | Adult illness, collapse, respiratory, cardiac, neuro, and medical ops calls | Adult medical content |
| Adult Trauma Response District | Injury, roadway, industrial, recreational, environmental, and violence-related trauma calls | Adult trauma content |
| Complex Incident Response District | High-acuity, multi-system, convergence, advanced and mixed-domain incidents | Advanced / complex content |

---

## 3. Core System Components

### 3.1 The Scenario Engine
Scenarios are generic JSON templates (e.g., `peds_asthma_01.json`). At runtime, the Scenario Engine adapts the template based on the active user's **Agency**, **MCA**, and **Provider Level** (e.g., restricting ALS drugs if the user is operating under BLS constraints).

### 3.2 The Vitals Engine
To prevent AI medical hallucinations, the LLM does *not* invent vital signs. Instead, a deterministic math engine calculates the patient's state based on:
1. **Time Elapsed:** Configurable deterioration rates (e.g., SpO2 drops 0.4% per minute).
2. **Interventions Applied:** Treatments inject immediate bumps or rate modifiers (e.g., Albuterol slows respiratory deterioration).
3. **String Thresholds:** As numbers cross thresholds, physical presentation strings automatically update (e.g., SpO2 < 85% → "Cyanotic lips").

### 3.3 AI & Roleplay Subsystem
The AI orchestrates multi-persona roleplay (Patient, Bystanders, EMS Partner). 
*   **Input Guardrails:** User inputs are truncated and sanitized to prevent prompt-stuffing.
*   **Strict Partner Rules:** The virtual EMS partner ("Alex") is strictly constrained to act only when commanded, adhering to the exact same licensure level as the student.
*   **Tagging Boundary (Cosmetic vs. Authoritative):** The LLM emits structured tags inline (e.g., `[[VITAL: HR=120]]`, `[[INTERVENTION: label]]`). The frontend parses these **strictly for cosmetic UI enrichment** (e.g., populating a visual "Patient Care Record" clipboard). **`[[INTERVENTION:]]` tags are display-only and never create backend `Intervention` DB rows** — intervention persistence requires an explicit user action (UI button press or popup confirmation) that triggers a discrete API call. *(Target Architecture Note: While currently coupled to some frontend readiness gates, the strict design mandates these tags never affect backend scoring, the vitals engine, intervention persistence, or state progression. Authoritative clinical state must be driven entirely by the backend.)*
*   **Output Formats:** The system uses a hybrid approach:
    - *Freeform Streaming:* Used for conversational roleplay to minimize perceived latency.
    - *Structured JSON Output:* Strictly enforced for **any machine-consumed authoritative output** (e.g., Debrief scoring, system state events) to guarantee schema reliability.

### 3.4 Multi-Tenant Protocol & Scope System
*   **Hierarchy:** National Base → State Base → MCA Overrides → Agency SOPs.
*   **Scope Floors:** Hard limits prevent downstream agencies from expanding scope beyond state law.
*   **Compile-on-Write:** Protocol patch operations are flattened and compiled into an immutable JSON blob when an admin saves them, ensuring O(1) read latency during simulations.

### 3.5 Event Ordering & Synchronization
Because simulations involve concurrent data streams (UI clicks via REST, Vitals via WebSockets, Chat via SSE), the system enforces strict causal ordering to prevent race conditions (e.g., a medication applied while an AI response is mid-stream).
- **Contract:** Every authoritative action must be processed in a guaranteed sequence against the latest system state. **Authoritative actions are user messages and intervention POSTs only.** Model (LLM) responses are outputs of the sequence — they are generated against committed state and do not themselves require sequencing guarantees.
- **Ordering Sequence:** User message saved → auto-detection fires in same transaction → LLM called against current committed state → response streamed and saved. No LLM call begins with stale state relative to preceding user actions or intervention commits.
- **Mechanism:** Handled via backend session row-locking, idempotency keys, or an append-only event log, ensuring "Medication Applied" strictly precedes "AI generates next response." *(Scope Note: As a practical first-pass choice, terminal phase-gates like DMIST and Narrative submissions are excluded from strict concurrent sequencing, as they do not suffer from mid-stream chat races. A unified session audit log may encompass these in the future.)*

### 3.6 Scoring & Debrief Pipeline
When a scenario concludes (after Treatment, DMIST, and Narrative submissions), the LLM generates a comprehensive debrief.
- **Pre-Scored Input Block:** Before calling the LLM, the backend compiles a structured input block from authoritative DB state: which critical actions are present in `Intervention` rows, which are absent, intervention timestamps, scenario-defined PPE/PAT pre-computed point adjustments, and the treatment plan built from DB rows (not frontend-assembled lists). The LLM evaluates against this pre-organized record.
- **Dual Debrief Inputs:** The pre-scored block handles objective facts (what was applied, when, what was missed). The student chat transcript is retained as supporting context for qualitative evaluation — communication quality, scene management language, clinical reasoning — and is not replaced by structured findings.
- **Absolute Authority (Structured Output):** The LLM is required to return a strict JSON envelope: `{ "subscores": { "clinical_performance": N, "narrative": N, "scope_adherence": N, "dmist": N, "professionalism": N }, "feedback": {...}, "teaching_points": [...] }`. The backend natively parses this JSON and performs the final score summation itself, preventing LLM arithmetic errors and brittle text extraction. A per-key regex fallback fills any subscore key absent from the structured parse; missing keys floor to 0.
- **Session Findings (Transitional Bridge):** A `SessionFinding` persistence layer captures structured assessment findings (exam, history, vitals logged) during the simulation as a supporting debrief input. *This layer is explicitly transitional ingestion — findings originate from frontend tag-parsing and are not independently verified facts.* The `SessionEvent` model (`session_events` table, live as of 2026-04-24) is the migration target: authoritative backend-emitted events (intervention_applied, vital_check, explicit_assessment, clinical_decision) are preferred over tag-derived findings in the evidence packet builder when both are present. Both paths run in parallel until the frontend emits events explicitly and the tag bridge is retired. See `AI_ARCHITECTURE.md §3.1` for gate criteria.
- **Target Architecture — Evidence Packet:** *(See `SCENARIO_EVALUATION_ARCHITECTURE.md` for implementation phases and full specification.)* The single-LLM-pass debrief is the transitional state. The target separates adjudication from coaching: a deterministic `_build_evidence_packet()` pre-computes hardened facts and deductions from DB state before the LLM call; the LLM acts as feedback writer rather than adjudicator. Scoring draws from three layers: (1) Universal Base — application-defined assessment milestones for every scenario; (2) Scenario Criteria — declared per-scenario in JSON; (3) Protocol/Scope — resolved at runtime by `adapt_scenario_to_context()`. A two-tier corroboration index (deterministic Python + constrained LLM extraction pre-pass) checks DMIST and narrative claims against run evidence and injects hardened findings before the debrief call. The evidence packet is the forensic record of why each score was assigned.

---

## 4. Gamification & Social Layers

RescueTrails utilizes an extensive gamification loop to drive engagement and spaced repetition.

### 4.1 XP, Levels, and Treats / Reward Economy
- **XP (Experience Points):** Earned via scenario scores (up to 600/run). Drives leveling (Recruit → Chief).
- **Treats (Currency):** Current live currency. Earned through gameplay. Can be spent on collectible unlocks or used mid-scenario to ask Lexi for a direct hint.
- **Planned visible reward layer:** The current toy-facing presentation is planned to shift toward **challenge coins**, **station/unit patches**, and **pins/decals** without changing the core server-authoritative reward architecture.

### 4.2 Minigames & Drills
- **Doorway Dash (PAT):** Binary swipe game (Sick vs. Not Sick) based on visual/text cues.
- **Stages of Development:** Drag-and-drop sorting game.
- **Quick Drills:** Legacy abbreviated scenario mode. *(Candidate for deprecation in favor of Random Call; architectural investment is currently frozen.)*
- **Random Call:** Daily randomized replay of cleared scenarios for capped XP.

**Planned framing note:** Minigames and collectible/reward moments are moving toward a **station-side drill** and **station dashboard** presentation, while field scenarios remain explicitly prehospital scene-based.

### 4.3 Planned Reward Presentation Direction

The planned reward presentation direction is:

- **Challenge coins** as the primary district/map completion collectible
- **Station / unit patches** as branch and convergence milestone rewards
- **Pins / decals** as lower-stakes rewards for mini-games, streaks, or focused mastery

This is intended to:
- improve B2B optics
- better match EMS / fire culture
- preserve collectibility without relying on toy-themed presentation

### 4.4 Multiplayer: Live Team Challenges
- **State Machine:** Orchestrates a strict progression: Lobby → Question Phase → Feedback/Readiness Phase → Results.
- **Room Ownership:** Host-managed lobbies and challenge invitations, with "Representatives" acting on behalf of an entire agency team.
- **Real-Time Comm:** Synchronous, WebSocket-driven state broadcasts with HTTP polling fallbacks for mobile reconnect resilience.
- **Cross-Tenant Isolation:** Validates team membership, active agency context, and handles cross-agency matchmaking without leaking roster data.

---

## 5. Data Flow: Typical Scenario Lifecycle

The scenario lifecycle is structured as a sequence of operational phases. Not all phases are active for every scenario — non-transport agencies skip transport/hospital phases; non-ALS scenarios skip the ALS intercept phase. The `turnover_target` field (root-level in the scenario JSON) declares which receiving party receives the handoff and drives debrief framing accordingly.

**Supported phases (current implementation):**

1. **Session Start:** User clicks "Play". Backend validates unlocks, creates a `SimSession` row with the current immutable Protocol Snapshot, and starts the clock.
2. **Scene Entry:** User selects PPE and makes an initial PAT (Pediatric Assessment Triangle) judgment. Sent via API to pre-compute scenario-backed professionalism/clinical score caps.
3. **Simulation Loop (WebSockets & SSE):**
   - Vitals engine ticks continuously, broadcasting updates via `ws://.../vitals`.
   - User chats/performs actions. SSE stream returns the AI's roleplay responses.
   - Frontend captures UI actions (applying meds) and posts to `/interventions`.
4. **ALS Intercept / Advanced Care Phase** *(when applicable):* User requests ALS (or ALS arrives automatically if co-dispatched), and the student prepares a DMIST handoff to the ALS crew. When `als_phase.auto_dispatched: true`, ALS arrival is narrated at the appropriate elapsed time without student action; when `auto_dispatched: false`, the student must explicitly request it.
5. **Transport Phase** *(when applicable):* Transport-capable unit packages and moves the patient. AI narrates transport packaging when the student signals readiness. Pre-arrival hospital communication occurs during this phase if `prearrival_report.required: true`.
6. **Patient Turnover / Verbal Report:** User submits a structured Treatment Plan and a verbal handoff — DMIST to an ALS crew, or pre-arrival radio report plus receiving-facility handoff for hospital transport. The DMIST scoring dimension evaluates this submission and is framed conditionally based on `turnover_target`.
7. **ePCR:** User writes the final CHART narrative.
8. **Evaluation:** Backend compiles the pre-scored input block from DB state (including transport decision and ALS intercept decisions from the Treatment Plan), triggers the LLM debrief, natively parses the structured JSON subscores from the response, calculates final XP / badges / collectible drops (current live implementation still uses toy drops), and caches the debrief immutably.

**Deferred — not yet implemented:**

- **During-Transport Simulation Phase:** Full interactive simulation of in-transport events — patient changes en route, events requiring student response, scored in-transport actions. Requires new UI, new endpoint, `transport_started_at` session state, runtime processing of `transport_phase.transport_events`, and an extended debrief section. The `transport_events` schema field is a design metadata placeholder until this phase is built.
- **ECG / Capnography Image Challenges:** Mini-game where the student is shown a rhythm strip or waveform image and must interpret it (analogous to PAT/Doorway Dash). The `image_asset` field in `vitals.baseline` monitoring entries reserves a linkage slot. Challenge infrastructure is deferred.

---

## 6. Security & Guardrails

- **Anti-Prompt Injection:** Every AI system prompt begins with a non-negotiable security header explicitly forbidding the model from revealing instructions or breaking character.
- **Data Privacy & Compliance (V1):** 
  - *Classification:* The system handles simulated training data, explicitly prohibiting real Protected Health Information (PHI). This is enforced via Terms of Service.
  - *External Boundaries:* Free-text inputs are sent to third-party LLM APIs strictly for roleplay evaluation. No real patient data is authorized for transmission.
  - *Retention:* Simulation records are subjected to strict Time-To-Live (TTL) deletion windows (e.g., 30 days) managed by a dedicated background worker. To minimize liability surfaces, this TTL scrub deletes granular `ChatMessage` rows, free-text `dmist_report` inputs, and `narrative_data` submissions. Scored metadata and generated debriefs may be retained longer for agency analytics. **Tradeoff:** Deleting raw transcripts limits long-term auditability and prevents instructors from reviewing the exact source evidence of a student's performance after 30 days. This is an intentional product decision prioritizing PHI/liability reduction over perpetual historical forensics.
  - *Tenant Isolation:* Strict DB-level Role-Based Access Control (RBAC) isolates agency data.
- **Immutability & Adjudication:** 
  - Debriefs and Protocol Snapshots are immutable. Historical sessions are always audited against the exact rules active at the time of the run.
  - *Protocol Revocation & Appeals:* If an agency publishes a factually incorrect protocol snapshot, or a student successfully appeals a grade, the historical session is *never overwritten*. Instead, corrected scores are recorded as a **separate, append-only adjudicated outcome record** linked to the target session. The schema explicitly enforces a **reason taxonomy** (e.g., `protocol_revocation`, `human_appeal`, `system_error`) to clearly differentiate the evidence standard and trigger for the re-score.
- **RBAC (Role-Based Access Control):** Separation of duties is enforced at the DB level. An Agency Admin can extract SOPs, but a separate Training Officer must certify them before they affect scoring.

---

## 7. Future Extensibility

- **Custom Scenario Authoring:** Expanding the JSON engine to allow agency-authored content (pending HIPAA/PHI compliance audits).
- **State Base Fan-Out:** Message broker integration (e.g., Celery/Redis) to handle protocol recompilation for thousands of agencies when a state publishes new base guidelines.
