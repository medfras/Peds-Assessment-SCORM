# Scenario Engine Architecture
**Status:** Active Implementation
**Last Updated:** 2026-04-24 (added §5.4 evidence packet target architecture)

---

## 1. Overview

The RescueTrails Scenario Engine is designed around a strict separation of concerns: **Static Content** vs. **Dynamic State**. 

Because the application is multi-tenant, a single scenario JSON file must be playable by an EMT student at a non-transport fire department in Michigan, and a Paramedic student at a transport ambulance agency in another state, without duplicating the scenario file.

The engine achieves this by using the scenario JSON as a *generic template*, which is then dynamically adapted at runtime based on the user's **Agency**, **Provider Level**, and **Medical Control Authority (MCA)**.

---

## 2. The Runtime Lifecycle

When a student clicks "Play Scenario", the following pipeline executes:

### Phase 1: Immutable Load
`load_scenario(scenario_id)` reads the raw JSON from disk and caches it in memory via an `@lru_cache`. This base dictionary is treated as immutable and is never modified.

### Phase 2: Context Adaptation
`adapt_scenario_to_context(scenario, agency, mca)` creates a shallow copy of the scenario and weaves in the active user's environment:
*   **Dispatch Injection:** Replaces `{unit}` placeholders with the agency's actual unit designator (e.g., "Squad 1").
*   **Transport Mode:** Overrides ALS arrival times and transport capabilities based on the agency's `service_type`.
*   **MCA Expansions:** Checks the session's MCA config for optional scope expansions (e.g., `cpap_bls`). If the scenario requires an expansion the MCA hasn't authorized, the engine dynamically strips that intervention from the student's BLS scope and adds a protocol warning.

### Phase 3: Session Initialization
The backend creates a `SimSession` row in the database. This row stores the exact `provider_level` and `mca` active at that exact second, freezing them so mid-scenario agency config changes do not break the active run.

---

## 3. The Deterministic Vitals Engine

RescueTrails uses a deterministic math engine (`vitals_engine.py`) rather than relying on the LLM to hallucinate vital signs. The AI *reads* the vitals, but the application *calculates* them.

### 3.1 Numeric Deterioration
Every time vitals are queried, the engine calculates the time elapsed since the scenario started.
*   If the scenario defines a `rates` block (e.g., `spo2: -0.4`), the engine calculates: `baseline + (rate * minutes_elapsed)`.
*   The engine enforces hard limits via the `caps` block so patients don't reach impossible states (e.g., SpO2 dropping below 0%).
*   Dependencies can be modeled: `trigger_spo2_below` prevents the GCS from dropping until the SpO2 crosses a critical threshold.

### 3.2 Intervention Effects
When a student applies a treatment, it is logged in the `interventions` table with a timestamp. The vitals engine plays back the timeline to calculate the current state:
*   **Immediate Change:** A one-time bump (e.g., applying O2 immediately adds +4 to SpO2).
*   **Rate Modifier:** Changes the trajectory (e.g., giving Albuterol applies a `0.15` rate modifier to the SpO2 deterioration, flattening the curve).

### 3.3 String Thresholds & Milestones
Vitals aren't just numbers; they include qualitative descriptions (Skin, Lung Sounds, Work of Breathing).
As the numeric math runs, the engine checks `string_thresholds`. If SpO2 drops below 88%, the engine automatically replaces the Skin vital string with "Cyanotic — lips and fingernails."

### 3.4 Session Milestones

Session milestones are named backend events that trigger scenario features (e.g., the impression challenge). They are evaluated server-side by comparing authoritative session state against declared criteria. Narrative descriptions and time-based heuristics are not acceptable milestone definitions — every milestone must name a specific data signal.

#### `primary_survey_complete`

**Definition:** All scenario-declared primary survey checklist items are satisfied.

**Authoritative rule:** The scoring engine's checklist evaluator compares the session's `SessionEvent` records (source `backend_auto` or `instructor_note` only) and intervention timeline against the scenario's `scoring.required_assessments` entries tagged with `phase: "primary_survey"`. The milestone fires the moment the last unmet item in that phase is satisfied.

**Fallback (scenarios with no `phase: "primary_survey"` items declared):** Milestone fires when both of the following are true:
1. At least one authoritative `explicit_assessment` `SessionEvent` is recorded.
2. At least one vital sign entry exists in the session's vitals record.

**Time-based heuristics are not used.** Do not fire a milestone based on elapsed time alone — this produces false positives when a student goes idle or false negatives in fast-moving sessions.

**Scenarios that use `trigger_milestone: "primary_survey_complete"` must declare at least one `phase: "primary_survey"` item in `scoring.required_assessments`** to guarantee deterministic milestone evaluation. Scenarios relying on the fallback path are acceptable during initial rollout but should be upgraded to explicit phase declarations before production.

---

## 4. Scope and Clinical Guardrails

A major feature of the engine is enforcing scope of practice. This is handled through a combination of application logic and structured prompting.

### 4.1 The Effective Level
A Paramedic taking a shift at a BLS-only agency is legally restricted to EMT scope. The system computes the `_effective_level` by taking the minimum of the student's personal license and the agency's primary provider level ceiling. 

### 4.2 The Intervention Dictionary
Every scenario defines an `interventions` dictionary. Each intervention has flags like `within_bls_scope`. 
If an intervention is out-of-scope for the student's effective level, the AI is explicitly instructed:
> *"That is within your Paramedic scope, but Plainfield Fire operates at the EMT-Basic level — it is not available here."*

### 4.3 Missing Equipment
Agencies can configure `not_carried` equipment. The engine injects this list into the prompt, explicitly separating a *Scope Error* (you aren't licensed to do this) from an *Equipment Error* (you are licensed, but we don't have the gear on the truck).

---

## 5. The Scoring and Debrief Pipeline

The debrief generation (`evaluate_and_generate_debrief`) represents the final phase of the scenario lifecycle. To guarantee clinical accuracy and leaderboard integrity, scoring is a hybrid of **Pre-Computed Constraints** and **AI Evaluation**.

### 5.1 Deterministic Pre-Scoring
Before the AI is called, the application evaluates specific actions that the LLM is historically bad at evaluating:
*   **PPE/BSI:** Scored directly from the scene-entry popup against the scenario's `scene_entry_scoring` contract. Current pediatric scenarios require gloves and recommend eye protection, so a gloves-only selection hard-caps Professionalism at 9/10. The cap is computed server-side and injected into the debrief prompt as a non-negotiable constraint.
*   **Required Interventions:** Scenarios may declare `scoring.required_interventions` (or per-level variants in `scoring.by_level[level].required_interventions`). The backend compares these IDs against the session's DB `Intervention` records and passes an `[APPLIED]` / `[MISSING]` checklist to the debrief prompt. The AI is instructed to treat these as pre-scored facts rather than re-evaluating them from the transcript.
*   **Lexi Treats:** If a student spent gamification currency to buy a direct hint, the backend flags those subsequent interventions as "No Credit" so the AI doesn't reward them for being told what to do.
*   **PAT:** Handled via the doorway swipe UI, passed to the AI as a forced ±3 / −2 Clinical Performance point adjustment.

### 5.2 The Prompt Assembly
The AI receives a massive context block containing:
1. The student's chat transcript (capped to 40 turns).
2. The DMIST turnover and CHART narrative.
3. The gold-standard `correct_treatment` block.
4. The grading rubric and grace items.

### 5.3 Authority of Math
When the AI returns the debrief, it uses Structured Outputs to provide a strict JSON schema containing the subscores (e.g., `{"clinical_performance": 38, ...}`) alongside the markdown body. 

*Crucially, the application backend natively parses these subscores and does the final math itself.* LLMs are poor calculators, so the application acts as the absolute authority, guaranteeing that the final score written to the database perfectly matches the sum of the extracted sub-categories.

### 5.4 Target Architecture — Evidence Packet Builder
*(Planned — see `SCENARIO_EVALUATION_ARCHITECTURE.md` for implementation phases and full specification)*

The current scoring pipeline (§5.1–5.3) is the transitional state. The target architecture adds an evidence packet builder stage before the LLM call:

**`_build_evidence_packet(adapted_scenario, session, submitted_docs, findings)`** — a deterministic Python function that compiles hardened facts from DB state into a structured packet. The adapted scenario (output of `adapt_scenario_to_context()`) is the required input — the builder never reads the base scenario JSON. The evidence packet becomes the authoritative adjudication record.

Scoring draws from three layers the packet builder resolves:
1. **Universal Base** — application-defined assessment milestones that fire for every scenario without authoring (scene safety, PPE, primary survey, history, vitals, reassessment, disposition, documentation)
2. **Scenario Criteria** — declared in scenario JSON (`pat`, required vitals by tier, required assessments, required screens)
3. **Protocol/Scope** — resolved by `adapt_scenario_to_context()` before the builder runs

A two-tier corroboration index checks DMIST and narrative claims against run evidence. Tier 1 is deterministic Python (structural checks, ID-level mismatches). Tier 2 is a small LLM extraction pre-pass (short timeout, fallback to Tier 1 on failure) that classifies claims as supported, contradicted, or unverifiable. Pre-pass output is schema-validated before injection into the evidence packet.

The debrief LLM receives only the delta from the packet (gaps, deductions, flags, ceilings) rather than a full run audit, preserving context window budget for authored educational content and qualitative evaluation.

---

## 6. Real-Time Interactions

### 6.1 The Action Pipeline
When a user selects an action from the UI (like giving a medication):
1. The frontend hits `POST /api/sessions/{id}/interventions`.
2. The backend records it.
3. The frontend injects an artificial action message `🩺 Action · now` into the chat log.
4. The vitals engine recalculates based on the new intervention.
5. The Vitals WebSocket pushes the updated vitals to the frontend.

### 6.2 Dialogue Parsing
The AI generates a single block of text containing multiple characters speaking and performing actions. The frontend uses `_parseAiDialogueChunks` to break this string apart into distinct visual bubbles:
*   `*Alex:* Let's get moving.` → Renders as a spoken dialogue bubble.
*   `[PROTOCOL NOTE: ...]` → Renders as a yellow warning box.
*   `[[EXAM: ...]]` / `[[VITAL: ...]]` → Silently stripped from the chat window and routed to the PCR Notes clipboard. *Note: These parsed tags are purely for cosmetic UI enrichment. They do NOT affect the authoritative backend simulation state.*
