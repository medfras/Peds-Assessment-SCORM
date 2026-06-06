# Product Improvement Direction

**Status:** Active product planning  
**Created:** 2026-05-11  
**Scope:** Near-term product improvements that preserve the current RescueTrails direction: adaptive EMS scenarios, instructor-created challenges, skill drills, map progression, badges, and protocol-aware debriefing.  
**Related docs:** [LEARNING_DESIGN.md](LEARNING_DESIGN.md), [PERFORMANCE_DASHBOARD_DESIGN.md](PERFORMANCE_DASHBOARD_DESIGN.md), [MINIGAMES_DESIGN.md](MINIGAMES_DESIGN.md), [REWARDS.md](REWARDS.md), [SCENARIO_EVALUATION_ARCHITECTURE.md](SCENARIO_EVALUATION_ARCHITECTURE.md), [SAAS_HARDENING_PLAN.md](SAAS_HARDENING_PLAN.md)

---

## 1. Product Positioning

RescueTrails should not become a plain chat-based AI patient simulator. Its strongest product shape is:

> An interactive EMS training map where learners run adaptive calls, complete focused drills, and build protocol-specific readiness through instructor-visible practice.

The core differentiators to preserve are:

- structured scenario actions and modals, not chat-only interaction
- deterministic scoring and backend-authoritative evidence
- instructor-created challenges as assignment, practice, and readiness containers
- targeted drills connected to scenario performance
- protocol, scope, agency, and MCA awareness
- warm map-based progression with professional EMS framing
- badges and readiness milestones instead of a generic game economy

The next product phase should tighten existing loops rather than add large disconnected feature families.

---

## 2. Current Direction Summary

The following product ideas are already present or planned and should be treated as foundation, not new scope.

| Area | Current direction |
|---|---|
| Instructor assignments | Instructor-created challenges already cover much of this role |
| Remediation | Partially in place through debrief routing, drills, and challenge mechanics |
| Protocol-aware feedback | Valuable differentiator; needs further exploration |
| Scenario replay variation | Planned |
| Instructor notes | Recommended addition |
| Rewards | Badges already exist; challenge coins should be removed from future direction |
| Skill ledger | Challenges and performance surfaces cover part of this role |
| Instructor dashboard | In development |
| Timeline feedback | Score feedback already includes a timeline |
| Confidence calibration | Present in concept but currently underused; needs to become meaningful |

---

## 3. Design Principles

### 3.1 Preserve The Training Loop

The product should keep the loop:

1. Learner runs an adaptive scenario.
2. Backend generates deterministic score evidence.
3. Debrief surfaces critical misses, timeline, and next action.
4. Learner is routed into a targeted drill, replay, or instructor challenge.
5. Progress is reflected through badges, readiness states, and instructor analytics.

This loop is stronger than a generic "score and reward" loop because every motivational element points back to practice.

### 3.2 Professionalize, Do Not Sterilize

The map, companion tone, and game-based learning layer are useful. The product should feel approachable and motivating, but buyer-facing language should use EMS training terms:

| Current / legacy language | Preferred direction |
|---|---|
| Games | Drills |
| Mini-games | Skill drills |
| Rewards | Badges, patches, readiness milestones |
| Coins | Remove from future direction |
| Toy-facing unlocks | Professional badges or district readiness markers |
| Deficiencies | Focus areas or needs another rep |

The goal is not to remove fun. The goal is to make the fun legible as professional training.

### 3.3 Backend Authority Still Wins

Product improvements must preserve the architecture rules:

- scoring stays deterministic and backend-authoritative
- protocol/scope enforcement stays server-side
- LLM output can coach, explain, and summarize, but cannot adjudicate final truth
- confidence ratings are learner self-assessment signals, not scoring inputs
- challenge completion and readiness gates must be persisted server-side

### 3.4 Evidence-Gathering First, Expansion Second

Before adding content or features, get real usage data. Even 5–10 real learners through a live session will surface more signal than another week of speculative hardening. Each product expansion phase should begin by defining what questions the evidence will answer, not by building the content that answers assumed questions.

Application of this principle to the current roadmap:

- The SCORM pilot must run before the adult scenario wave is built.
- The web pilot with the initial education program must run before building institutional features for that mode.
- Scenario anomaly data (NLP-miss vs. learner-error, CE-time distribution, session lengths) should drive which scoring gaps get fixed next.
- Transport workflow validation (`turnover_target: "hospital"`) must be confirmed working before authoring a wave of hospital-handoff scenarios.

---

## 4. Improvement Themes

## 4.1 Challenges As The Central Instructor Object

Instructor-created challenges should become the main container for assignment, remediation, and readiness.

### Product roles

| Role | Description |
|---|---|
| Assignment | Instructor assigns a scenario/drill bundle with due date, target score, and cohort visibility |
| Remediation | Instructor or system routes a learner to a challenge after missed skills |
| Readiness | Challenge completion validates a district, topic, or skill family |
| Review | Instructor dashboard shows challenge completion and who needs another rep |

### Recommended refinements

- Add optional instructor-facing title, objective, and notes to challenges.
- Add due date and recommended completion order where feasible.
- Add challenge type labels: assignment, remediation, readiness, practice.
- Let debrief next-action routing point to a challenge when a suitable challenge exists.
- Display challenge progress as a training commitment, not just a game objective.
- Allow instructor-created challenges to be marked repeatable when the same skill bundle should be re-run for additional practice or recurring competency checks.

### Do not overbuild yet

Avoid building a full LMS scheduler in the near term. Challenges should solve the immediate training flow without expanding into clinical rotation scheduling, attendance, preceptor signatures, or compliance documentation.

### Repeatable challenge attempts

The challenge definition can carry an instructor-facing `repeatable` flag. Repeatable challenges use learner-scoped attempt rows so a learner can start the same challenge again and have only new work count.

Target behavior:

- A repeatable challenge shows a `Start` action before the first run and a `Start Again` action after completion.
- Each run has its own `started_at`, optional `completed_at`, status, and attempt number.
- Scenario/drill completions and CE time count only when they occur after the active attempt starts.
- A completed attempt remains immutable for audit; later failed or incomplete work does not undo it.
- The learner may retake the same required scenarios/drills in a later attempt and earn another completion/time block.
- Non-repeatable challenges keep the one-time badge behavior.

Implementation status:

- Implemented: `ChallengeAttempt` model/table with attempt number, status, start/end timestamps, and completion summary.
- Implemented: learner start/resume endpoint for repeatable challenge attempts.
- Implemented: repeatable progress filters completed scenarios and CE time to the active/latest attempt window.
- Implemented: repeatable completions create immutable completed attempts; the badge remains first-completion recognition and does not block later attempts.
- Implemented: learner challenge cards show attempt state, time goal, time remaining, and `Start Again` after completion.
- Implemented: instructor dashboard counts repeatable challenge completions from completed attempts instead of badge state.
- Deferred: direct `challenge_attempt_id` foreign keys on `CeTimeLog`/sessions. Current implementation scopes by timestamps; direct linkage remains preferred if audit needs become stricter.

---

## 4.2 Instructor Notes

Instructor notes are a high-leverage addition because they make prebuilt content feel locally owned without requiring full custom scenario authoring.

### First implementation target

Attach instructor notes to challenges first.

Suggested fields:

- objective
- local protocol emphasis
- common mistakes
- debrief discussion prompt
- remediation instructions
- optional private instructor-only note

### Later targets

After challenge notes are useful, consider extending notes to:

- individual scenarios
- drill bundles
- district readiness gates
- cohort-level training plans

### Authority boundary

Instructor notes should not alter scenario scoring unless they are later promoted into a formal rubric or protocol configuration path. Notes are instructional context, not scoring logic.

---

## 4.3 Protocol-Aware Debriefing

Protocol awareness is one of RescueTrails' strongest potential differentiators. It should be explored first as debrief-only feedback before changing gameplay.

### Initial product surface

Add a debrief panel:

> Protocol / Scope Notes

This panel can explain:

- actions that were in scope or out of scope for the learner's provider level
- interventions that required Medical Control
- local MCA or agency differences that affected the expected care path
- how the same scenario might differ under another configured protocol profile

### Recommended examples

- "Under this agency profile, this intervention requires Medical Control before administration."
- "This action is appropriate for Paramedic scope but not EMT scope in the selected profile."
- "Your care path matched the national base guideline, but this MCA override expects a different destination decision."

### Guardrails

- Do not let the LLM invent protocol differences.
- The backend must provide structured protocol/scope findings before the coaching text is generated.
- If protocol evidence is incomplete, show a clear diagnostic or omit the panel rather than guessing.

---

## 4.4 Remediation Pathways

Remediation should become the connective tissue between scenarios, drills, and challenges.

### Target loop

1. Scenario detects missed competency.
2. Debrief names the gap.
3. Backend maps the gap to a drill, replay, or instructor challenge.
4. Learner completes the targeted activity.
5. Practice Insights reflects whether performance improved.

### Recommended routing targets

| Missed area | Possible next action |
|---|---|
| Assessment sequencing | focused assessment drill or scenario replay |
| Respiratory recognition | respiratory differential drill |
| Medication timing | scenario replay with medication/treatment focus |
| Handoff weakness | DMIST builder drill |
| Documentation weakness | narrative practice or CHART review |
| Protocol/scope issue | protocol pivot drill or protocol note review |
| Low confidence / high score | reinforcement scenario |
| High confidence / low score | instructor-visible coaching flag |

### Implementation note

Use deterministic mappings from rubric items, checklist items, and drill metadata. The LLM may phrase the recommendation, but the target should come from backend data.

---

## 4.5 Scenario Replay Variation

Scenario variation is planned and should remain a priority because it increases content value without requiring a fully new scenario for every practice rep.

### Variation types

- starting vitals variation within safe scenario-defined bounds
- different caregiver or bystander history
- different treatment response curve
- alternate distractor or scene hazard
- transport wrinkle
- confounding but clinically plausible finding
- time-pressure variant

### Requirements

- Scenario JSON must declare allowed variation ranges.
- Variants must not change the core learning objective unless explicitly declared.
- Debrief should identify the variant only if it affects expected reasoning.
- Variation must remain deterministic after session creation so auditability is preserved.

---

## 4.6 Badges And Readiness Language

Badges should become the primary visible competency signal. Challenge coins should be removed from future product direction.

### Recommended badge families

- Assessment Ready
- Airway Ready
- Breathing Ready
- Circulation Ready
- Trauma Ready
- Pediatric Ready
- Handoff Ready
- Documentation Ready
- Protocol Ready
- Team Ready

### Badge rules

- Badges should reflect demonstrated competency, not playtime alone.
- Badge descriptions should name the clinical or operational skill represented.
- District completion should communicate readiness in a training area.
- Badge earning criteria should be auditable from completed scenarios, drills, and challenges.

### Visual direction

Prefer EMS-friendly presentation such as:

- station/unit patches
- readiness badges
- district completion markers
- pins or decals for lower-stakes drill accomplishments

Avoid currency-like presentation unless it has a clear instructional role.

---

## 4.7 Confidence Calibration

Confidence prompts should become meaningful before they return to the product. The standalone dispatch confidence check has been removed; do not add it to new scenarios until it is persisted and connected to debriefs and instructor analytics.

### Minimum useful version

For each scenario, only after the feature has an end-to-end use:

1. Ask pre-scenario confidence.
2. Ask post-debrief confidence.
3. Compare confidence to actual score.
4. Surface calibration patterns to learner and instructor.

### Useful signals

| Pattern | Product meaning |
---|---|
| High confidence / high score | reinforced readiness |
| Low confidence / high score | learner may need encouragement or repetition |
| High confidence / low score | coaching priority; potential safety risk |
| Low confidence / low score | remediation and guided practice needed |

### Learner display

Use coaching language:

- "You were more ready than you thought."
- "Your confidence rose after the debrief."
- "This is a good area for another rep."

### Instructor display

Instructor dashboard should flag confidence-score mismatch as a coaching cue, not a punitive label.

---

## 4.8 Timeline Feedback Refinement

The score feedback timeline already exists. The next improvement is to make it more actionable and easier to scan.

### Recommended timeline layers

- performed actions
- missed expected actions
- late actions
- out-of-sequence actions
- protocol/scope notes
- reassessment opportunities
- handoff/documentation milestones

### Presentation guidance

The timeline should answer:

- What did the learner do?
- What was expected at this point?
- What changed because of the learner's action or inaction?
- Which item should they practice next?

Avoid turning the timeline into a long transcript. It should be a clinical replay, not an archive.

---

## 4.9 Instructor Dashboard Priorities

The instructor dashboard should prioritize triage over exhaustive analytics.

### First questions to answer

- Who needs attention?
- Which assigned challenges are incomplete?
- Which learners have repeated misses in the same skill area?
- Which skills are weak across the cohort?
- Which learners show high confidence but low performance?
- Which scenarios or drills are causing repeated misses?

### Recommended first panels

- Needs Review
- Challenge Completion
- Cohort Focus Areas
- Confidence Calibration
- Recent Critical Misses
- Skill Drill Performance

### Avoid initially

- overly complex dashboards
- broad analytics without action links
- raw data tables as the primary view
- punitive language in learner-facing summaries

---

## 4.10 Instructor-Authored Scenario Authoring

Instructors should eventually be able to create scenarios without writing JSON directly. The mechanism is guided AI generation: the instructor provides structured inputs and the backend uses an LLM to produce a complete scenario that conforms to the scenario design contract.

This feature is distinct from unrestricted scenario generation. The authoring surface is constrained, vocabulary validation runs before any scenario is saved, and every instructor-authored scenario requires an explicit publish step before it becomes playable.

### Authoring input surface

The instructor provides:

- chief complaint and scene context
- patient demographics (age, sex, weight)
- target provider level and scope
- primary learning objective
- key teaching point
- one or two critical must-do interventions
- difficulty level
- optional local protocol note or MCA context

The backend assembles these inputs into a prompt that includes the `SCENARIO_DESIGN_EMS.md` contract and the registered vocabulary. The LLM generates the full scenario JSON. The system runs vocabulary validation against the output before the scenario is saved. Validation failures surface to the instructor as specific errors.

### Non-negotiable guardrails

- **AI fills a contract, it does not write its own.** The scoring rubric fields, vitals intervention keys, and vocabulary IDs must resolve to registered entries. The LLM is not authorized to invent new scoring dimensions or intervention IDs.
- **Vocabulary validation runs before save.** A scenario with an unregistered intervention key or rubric dimension is rejected, not saved with a silent fallback.
- **Draft → Review → Published lifecycle.** Every instructor-authored scenario starts as a draft. The instructor must explicitly publish before the scenario is playable. Published scenarios are immutable; changes require a new version.
- **Tenant-scoped by default.** An instructor's scenario is visible only to their agency. Promotion to the platform catalog requires explicit platform admin action.
- **Deterministic scoring still applies.** The vitals engine and scoring architecture run identically against instructor-authored and platform scenarios. The LLM is not involved in adjudication.
- **LLM does not set scoring arithmetic.** Point weights, critical action lists, and scope floors come from the instructor's declared inputs and the scenario contract. The LLM populates fields; it does not set values the scoring engine will treat as authoritative.

### Infrastructure prerequisite

Instructor-authored scenarios are DB-resident from the start. They cannot be implemented on top of the current file-based scenario loader without creating two incompatible scenario sources. Before this feature is built, platform scenarios must be migrated to a DB-seeded catalog:

1. A seed process imports all platform JSON scenarios into a `scenarios` table with `source = 'platform'` on deploy.
2. Instructor-authored scenarios write to the same table with `source = 'instructor'` and a `tenant_id`.
3. The scenario engine's `load_scenario()` becomes a DB lookup. The in-process `lru_cache` is replaced with a short-TTL Redis cache or per-request DB lookup.
4. Platform JSON files remain the authoritative authoring source and stay version-controlled in the repo. The DB is the runtime source of truth.

This migration should be completed as a standalone step before instructor authoring is built — not as part of the same implementation sprint.

### What this feature does not include in v1

- instructors editing vitals math or deterioration curves directly
- instructors overriding scope floors or rubric weights
- generating scenarios with clinical findings or interventions not yet registered in the vocabulary
- unrestricted freeform scenario generation without a structured input form
- automatic publishing without instructor review

---

## 5. Priority Recommendations

### Priority 1 — Coherence

Make challenges the central object for assignments, remediation, and readiness.

Deliverables:

- challenge purpose/type labels
- optional instructor notes
- dashboard challenge completion summary
- debrief next-action routing to challenge when applicable

### Priority 2 — Confidence Calibration

Connect confidence prompts to real outputs.

Deliverables:

- pre-scenario confidence capture
- post-debrief confidence capture
- confidence-score mismatch display
- instructor dashboard coaching cue

### Priority 3 — Protocol-Aware Debrief Panel

Explore protocol difference feedback in debrief only.

Deliverables:

- backend protocol/scope finding structure
- debrief panel for protocol/scope notes
- no LLM-invented protocol claims

### Priority 4 — Professional Language Pass

Rebrand game-facing terms without removing the engagement layer.

Deliverables:

- games -> drills
- mini-games -> skill drills
- coins removed from future direction
- rewards reframed as badges/readiness markers
- learner-facing copy aligned with station/dashboard training theme

### Priority 5 — Replay Variation

Implement declared scenario variation after the above loops are coherent.

Deliverables:

- scenario JSON variation contract
- deterministic variant selection at session start
- debrief awareness of variant-specific expectations

### Priority 6 — Scenario DB Migration (prerequisite for instructor authoring)

Migrate platform scenarios from file-based loading to a DB-seeded catalog. This is an infrastructure prerequisite — not a user-facing feature — but it must land before instructor-authored scenario generation is built.

Deliverables:

- `scenarios` table with `source`, `tenant_id`, `status` (draft/published), and `scenario_json` columns
- seed process that imports platform JSON files into the table on deploy
- `load_scenario()` updated to query DB; in-process `lru_cache` replaced with short-TTL Redis cache
- platform JSON files remain version-controlled as the authoring source; DB is the runtime source of truth

### Priority 7 — Instructor-Authored Scenario Generation

Build guided AI scenario authoring after Priority 6 is complete and at least one cohort of instructors is actively using challenges.

Deliverables:

- structured authoring form in instructor dashboard
- backend prompt assembly using `SCENARIO_DESIGN_EMS.md` contract and registered vocabulary
- vocabulary validation before save, with instructor-facing error surface
- draft/review/published lifecycle
- tenant-scoped by default; platform promotion requires admin action

---

## 6. Product Non-Goals For This Phase

Do not expand into these areas until the core loop is tighter:

- full LMS replacement
- clinical rotation scheduling
- preceptor sign-offs
- attendance tracking
- compliance document management
- unrestricted instructor-authored scenario generation (no validation gate, no vocabulary enforcement, no review step)
- learner-to-learner social feeds unrelated to training
- rewards that can be earned primarily through time spent rather than demonstrated competency

These may become future opportunities, but they should not distract from the near-term differentiated product: adaptive scenario practice, drills, challenges, readiness, and protocol-aware coaching.

**Note on instructor-authored scenarios:** Guided AI scenario authoring — where an instructor provides structured inputs that feed an AI generator constrained to the scenario design contract, with vocabulary validation and an instructor review gate — is a planned near-term feature and is not covered by the unrestricted generation non-goal above. See section 4.10.

---

## 7. Success Criteria

The improvements are working when:

- learners understand what to practice next after a scenario
- instructors can assign and review challenge-based work without extra explanation
- drills feel like targeted remediation, not side games
- badges communicate clinical readiness
- confidence prompts produce visible coaching value
- protocol-aware notes make the product feel locally relevant
- the map/progression layer still feels motivating but reads as professional EMS training

---

## 8. Future Strategy: Enterprise QA/QI And Multi-Domain

The near-term product should remain focused on the simulation training loop. However, several current architectural choices also create optionality for future enterprise QA/QI and Fire/Rescue expansion. These are strategic directions, not current product promises.

### 8.1 Separate Enterprise QA/QI Product Fork

The scoring architecture should continue moving toward generic evidence models: `SessionEvent`, `Intervention`, `ChatMessage`, `ChecklistItem`, protocol snapshots, and adjudicated outcomes. That direction keeps the core evaluator from being locked to a browser simulation.

If RescueTrails proves successful and the scoring system is validated as reliable, accurate, and clinically defensible, the scoring and feedback architecture should be considered for a separate enterprise product fork. This fork would not be a student training game. It would be an agency operations platform for real-world QA/QI, analytics, protocol compliance review, and agency data management.

The fork should reuse the scoring, evidence packet, protocol snapshot, feedback, and analytics concepts from RescueTrails while replacing simulated session inputs with real-world agency data.

### 8.1.1 Core Product Concept

The future product would allow EMS and Fire/Rescue agencies to connect operational systems through APIs, imports, or partner integrations, then use the scoring and feedback engine to evaluate real-world calls against agency protocols, medical control rules, and operational benchmarks.

Primary product jobs:

- ingest real-world call records from ePCR and related agency systems
- normalize incoming data into generic evidence models
- score calls against protocol, rubric, scope, sequence, and documentation expectations
- generate QA/QI review packets with evidence, flags, feedback, and confidence levels
- display agency-wide operational analytics in a Metabase-like dashboard experience
- serve as a DBMS for agency configuration, personnel, protocol profiles, units, stations, response areas, and review workflows
- support human review, adjudication, appeals, and training follow-up

### 8.1.2 EMS ePCR Review

| Capability | Future direction |
|---|---|
| Data ingestion | Import ePCR records through NEMSIS-aligned APIs, exports, webhooks, or partner integrations |
| Evidence translation | Map ePCR procedures, medications, assessments, timestamps, and narrative elements into generic evidence models |
| Protocol context | Evaluate against the MCA or agency protocol snapshot active at the time of the real call |
| QA/QI review | Flag cases for human review, identify protocol variance, and support training recommendations |
| Auditability | Preserve the evidence packet, protocol snapshot, and adjudication trail behind each score or flag |

This should be framed as **decision support and review acceleration**, not full replacement of human clinical QA. Real-world ePCR narratives are incomplete, ambiguous, and legally sensitive. The product should surface evidence-backed findings, confidence levels, and review queues rather than silently issuing final clinical judgments.

### 8.1.3 Agency DBMS And Analytics Layer

The QA/QI fork should also function as an agency data-management and analytics platform. It should not only score individual calls; it should help an agency understand its system.

Potential managed entities:

- agencies and divisions
- stations and response zones
- units and apparatus
- personnel, roles, certifications, and qualifications
- protocol profiles and historical protocol snapshots
- call records and imported ePCR references
- QA/QI cases, review assignments, adjudications, and corrective actions
- training recommendations linked back to RescueTrails-style drills or scenarios

Potential dashboard areas:

- protocol compliance trends
- high-risk call review queue
- documentation quality trends
- medication and procedure variance
- response-type and acuity patterns
- provider, unit, station, and agency-level aggregate views
- recurring training needs
- Fire/Rescue incident benchmarks after those engines exist

The analytics experience can be inspired by BI tools like Metabase: filterable dashboards, saved questions, drill-down tables, charts, cohort comparisons, and exportable reports. Unlike a generic BI tool, the platform's advantage would be that the underlying data model is already protocol-aware and QA/QI-aware.

### 8.1.4 Human Review And Governance Requirements

Any production version of this fork would need:

- strict tenant isolation and authorization
- PHI-aware storage, logging, redaction, and retention controls
- business associate agreement readiness where applicable
- integration audit logs
- imported-data provenance
- human reviewer workflows
- appeal and adjudication records
- false-positive/false-negative tracking
- validation against historical human chart review
- clear separation between automated flags and final QA determinations

The fork should become trusted by first being useful to reviewers, not by pretending to remove reviewers.

### 8.2 Fire/Rescue Extensibility

Future expansion into Fire, Hazmat, Technical Rescue, or broader public safety QA/QI depends on avoiding hardcoded EMS-only assumptions in shared engines. The same product fork should be able to review Fire calls after Fire/Rescue content, evidence models, scoring rubrics, and incident benchmarks are built.

Recommended architectural posture:

- Treat timeline events as generic compliance and sequence milestones, not only medical interventions.
- Preserve a generic checklist/evidence evaluator that can assess incident command benchmarks, hazard mitigation, communications, safety actions, and patient care actions.
- Plan for EMS data to map through NEMSIS concepts and Fire/Rescue data to map through NFIRS or NERIS concepts where applicable.
- Distinguish EMS licensure levels from incident roles and qualifications. Fire/Rescue evaluation may depend on dynamic roles such as Incident Commander, Safety Officer, Entry Team, Pump Operator, or Hazmat Technician.
- Keep gamification and learner progression separate from the core scoring engine so the evaluator remains portable to non-simulation and non-EMS domains.

Future Fire/Rescue review areas could include:

- incident command benchmark completion
- safety officer actions
- initial size-up and scene reports
- hazard identification and mitigation
- water supply, ventilation, search, and suppression sequence benchmarks
- MAYDAY, accountability, and personnel safety events
- Hazmat isolation, identification, notification, and decontamination steps
- technical rescue sequence and role compliance

This strategy reinforces the current rule: the deterministic scoring engine must stay decoupled from simulator-specific reward logic and hardcoded EMS-only concepts.

---

## 9. Market Comparison And Competitive Advantage

Based on public product positioning reviewed on 2026-05-11, RescueTrails sits between several existing categories rather than matching one directly. This section is a positioning guide, not a claim that competitors lack private roadmap features.

Reference examples:

- CaseLab positions around AI-powered EMS patient simulation, instructor case creation, automated feedback, and performance analytics.
- Medceptor positions around EMT test prep, AI patient simulation, NREMT-style questions, audible symptoms, and debriefing.
- SimX positions around high-fidelity VR medical and EMS simulation, immersive environments, multiplayer training, and large scenario libraries.
- Platinum Planner / EMSTesting positions around institutional scheduling, skills tracking, testing, documentation, reporting, and accreditation support.

### 9.1 AI Patient Simulation Platforms

**Market pattern:** AI patient simulators emphasize scalable practice, conversational patient interaction, automated feedback, case creation, and analytics.

**RescueTrails opportunity:** Compete on structured interaction and auditability:

- deterministic vitals and scenario state
- explicit treatment/action modals instead of chat-only intent parsing
- backend-compiled evidence packets
- protocol, scope, MCA, and agency context
- debrief prose generated after structured scoring inputs are assembled

The claim should not be that other AI platforms are unusable or inherently unsafe. The stronger claim is that RescueTrails is designed around a clearer authority boundary: AI can coach and roleplay, while backend systems own clinical state, scoring evidence, and protocol context.

### 9.2 Test-Prep And Individual Study Apps

**Market pattern:** Test-prep tools emphasize individual learner readiness, practice questions, exam-style feedback, and lightweight simulation.

**RescueTrails opportunity:** Move beyond individual test prep into agency and instructor workflows:

- instructor-created challenges
- skill drills connected to scenario misses
- cohort and dashboard views
- local protocol and scope context
- readiness badges tied to demonstrated performance

This does not replace NREMT-style study. It complements it by training applied decision-making, handoff, documentation, and local-protocol reasoning.

### 9.3 High-Fidelity VR Simulation

**Market pattern:** VR platforms emphasize immersion, spatial realism, multiplayer team training, and high-fidelity simulated environments.

**RescueTrails opportunity:** Own the high-frequency cognitive-rep lane:

- browser access on common devices
- quick drills and short scenario reps
- spaced repetition through Random Call and targeted remediation
- low setup burden for between-class, between-shift, or homework practice

VR remains stronger for spatial scene management, team dynamics, and immersive high-acuity simulation. RescueTrails should not claim to replace that. The stronger position is that RescueTrails supports frequent cognitive practice where VR is too heavy for daily use.

### 9.4 Compliance, Scheduling, And Skills Tracking Platforms

**Market pattern:** Institutional platforms emphasize documentation, scheduling, skills tracking, student/preceptor workflows, testing, and reporting.

**RescueTrails opportunity:** Be the training engine that generates structured performance evidence:

- interactive scenarios and drills
- deterministic score snapshots
- debrief timelines
- challenge completion records
- instructor review queues
- future QA/QI evidence packets

RescueTrails should avoid becoming a full LMS or clinical rotation tracker in the near term. The product can integrate with those systems later, but its near-term value is creating better practice data and better remediation loops.

### 9.5 Defensible Product Thesis

The defensible product thesis is:

> RescueTrails combines accessible browser-based scenario reps, structured action capture, deterministic scoring evidence, local protocol context, and instructor-visible remediation loops.

That combination is more durable than "AI patient chat" alone and more practical for daily practice than high-fidelity simulation alone. The long-term enterprise opportunity is to make the same evidence and protocol architecture useful beyond simulation, but only after the training product is hardened, validated, and trusted.

---

## 10. Two-Mode Product Strategy

RescueTrails now has two distinct deployment contexts with different content requirements, scoring profiles, and LMS integration needs. Both modes run on the same platform and codebase; the distinction is configuration, content scope, and packaging.

### 10.1 Department SCORM Mode

**Target buyer:** Single EMS agency or department (initial reference: PFD/Kent configuration).

**Characteristics:**

| Dimension | Department SCORM mode |
|---|---|
| LMS integration | SCORM 1.2 package, Moodle or similar LMS |
| Protocol profile | Agency-specific (ALS scope, local MCA, county protocols) |
| Curriculum | 4-map 16-node peds map; CE challenge as completion gate |
| Turnover model | ALS turnover (hospital handoff out of scope for this mode) |
| CE credit model | Peds CE challenge, time-gated, LMS-reported as passed/incomplete |
| Content depth | 1–3 scenarios per topic area, focused on agency protocol alignment |
| Instructor features | Challenge authoring, challenge coins, readiness badges |
| Learner scale | Department cohort (10–50 learners per pilot) |

**Current gate:** SCORM event adapter branch (scorm_adapter.js), febrile seizure validation, PAT vertical slice, Moodle packaging.

### 10.2 Initial Education Mode

**Target buyer:** EMS initial education program (academy, community college, EMT/Paramedic program).

**Characteristics:**

| Dimension | Initial education mode |
|---|---|
| LMS integration | Web-first, direct enrollment; SCORM optional later |
| Protocol profile | NASEMSO national base guidelines; NREMT-aligned content |
| Curriculum | Broad adult and pediatric call types; not agency-specific |
| Turnover model | Both ALS turnover and hospital handoff; transport decision included |
| CE credit model | Not applicable in v1 of this mode |
| Content depth | Full call-type breadth: medical, trauma, OB, pediatric, cardiac arrest |
| Instructor features | Cohort assignment, progress visibility, challenge authoring |
| Learner scale | Program cohort (20–100+ learners per class) |

**Current gate:** Validate `turnover_target: "hospital"` workflow before authoring hospital-handoff scenarios. Build transport decision support into debrief path. Confirm NASEMSO protocol profile coverage.

### 10.3 Mode Separation Rules

- Protocol profile, scope floor, and turnover target are scenario-level and tenant-level config — not mode-gated by code branch.
- Do not build a "mode toggle" feature. The modes are operationalized through content, config, and packaging, not a runtime switch.
- CE challenge mechanics are Department SCORM mode-specific. Keep CE logic behind the `peds_ce_challenge` config key, not hardcoded into shared runtime paths.
- NASEMSO content must not hardcode PFD/Kent protocol assumptions. Use generic national base guideline vocabulary wherever possible.

---

## 11. Content Expansion Wave

This section tracks the planned content expansion, its prerequisites, and authoring priorities. Expansion is gated on evidence — do not build the full wave before running the initial education pilot.

### 11.1 Transport Workflow Validation (Prerequisite)

Before building hospital-handoff scenarios at scale:

- Confirm `turnover_target: "hospital"` works end-to-end in a live session.
- Confirm hospital pre-arrival notification renders correctly.
- Confirm hospital handoff debrief section generates without errors.
- Reference scenario: `adult_acs_01_stemi.json` (the only current hospital-handoff scenario).
- If issues are found, fix them on `adult_acs_01_stemi.json` before authoring additional hospital-handoff scenarios.

### 11.2 Existing Scenarios To Validate

These scenarios already exist and should be validated before being promoted to the initial education curriculum.

| Scenario | Turnover | Status |
|---|---|---|
| `adult_acs_01_stemi.json` | hospital | validate transport path |
| `adult_cardiac_arrest_01_bls.json` | als | validate BLS content |
| `peds_febrile_seizure_01.json` | als | pre-branch gate — validate next |

### 11.3 Adult Scenario Wave (Initial Education)

Author these after transport validation is confirmed and at least one initial education program session has been run.

**Priority 1 — highest clinical frequency and NREMT weight:**

| Chief complaint | Turnover | Notes |
|---|---|---|
| Stroke / CVA | hospital | BEFAST, Cincinnati scale, stroke alert, time-to-CT emphasis |
| Respiratory distress | als or hospital | Covers CHF, COPD exacerbation, asthma; differential required |
| AMS / altered mental status | als or hospital | Glucose, AEIOUTIPS differential, GCS, stroke screen |
| Seizure (adult) | als | Post-ictal assessment, seizure duration, ALS intervention decision |

**Priority 2 — volume and scope breadth:**

| Chief complaint | Turnover | Notes |
|---|---|---|
| Anaphylaxis | als | Epi timing, airway threat, secondary reactions |
| Diabetic emergency / hypoglycemia | als | Glucose check as critical action, oral vs. IV route decision |
| Fall / hip fracture | als | MOI, pain management, spine assessment decision |
| MVC / trauma (adult) | als | Mechanism assessment, full trauma, transport decision |

**Priority 3 — cardiac arrest series:**

| Chief complaint | Turnover | Notes |
|---|---|---|
| Adult cardiac arrest — ALS | als | Rhythm-guided ACLS; `adult_cardiac_arrest_01_bls.json` is BLS baseline |
| Adult cardiac arrest — STEMI post-ROSC | hospital | ROSC management, 12-lead interpretation, cardiac cath destination |

### 11.4 Pediatric Scenario Pipeline

The peds curriculum currently covers febrile seizure. The next pediatric scenarios should expand the 4-map peds content and serve both Department SCORM and Initial Education modes.

Candidates:
- respiratory (croup, bronchiolitis, asthma)
- trauma (falls, MVC, non-accidental)
- cardiac arrest (pediatric BLS/ALS)
- anaphylaxis
- altered mental status / hypoglycemia

Pediatric scenarios default to `turnover_target: "als"`. Hospital-handoff peds scenarios (e.g., pediatric stroke, STEMI equivalent) are out of scope until the adult hospital-handoff path is fully validated.

### 11.5 NASEMSO Protocol Profile

Initial education content must operate against a generic national base guideline profile, not the PFD/Kent agency config.

Required before initial education pilot:

- Confirm that `protocol_profile: "nasemso_base"` (or equivalent) resolves correctly at session start.
- Confirm that scope floors and intervention keys use NASEMSO terminology where scenarios are authored for initial education.
- Confirm that no initial-education scenario references a PFD/Kent-specific MCA rule, destination policy, or county protocol key.
- Document the NASEMSO profile in the relevant protocol config file.

### 11.6 Authoring Watchouts

- Do not override `turnover_target` mid-scenario (transport decision is end-of-scenario).
- Hospital-handoff scenarios require the pre-arrival notification checklist in the rubric. Do not author a hospital-handoff scenario without it.
- NASEMSO scenarios must not include agency-specific medication formularies or destination policies.
- Each new scenario must follow [docs/SCENARIO_DESIGN_EMS.md](docs/SCENARIO_DESIGN_EMS.md) and use registered vocabulary IDs.
- Do not author new scenarios that depend on architecture marked as transitional or deferred in the scoring hardening roadmap.
