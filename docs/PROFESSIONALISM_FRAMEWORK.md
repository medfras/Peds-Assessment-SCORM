# Professionalism Evaluation Framework

**Status:** Active Reference  
**Created:** 2026-05-18  
**Scope:** How the 11 NASEMSO affective domain attributes from the National Guidelines for Educating EMS Instructors (2002) map to observable behaviors in RescueTrails scenario sessions. This framework governs how the professionalism scoring category is structured, what criteria the LLM uses when adjudicating professionalism, and what behaviors authors should describe in professionalism rubric bands.

**Related docs:** [docs/LEARNING_DESIGN.md](LEARNING_DESIGN.md), [docs/rubric_templates/ems_standard_v1.md](rubric_templates/ems_standard_v1.md), [docs/SCENARIO_EVALUATION_ARCHITECTURE.md](SCENARIO_EVALUATION_ARCHITECTURE.md)

---

## 1. Source Framework

The National Guidelines for Educating EMS Instructors (NASEMSO, August 2002, Appendix V) define eleven affective domain characteristics for evaluating EMS student professional behavior. These attributes derive from the 1998 EMT-Paramedic National Standard Curricula and represent the national consensus standard for affective competency evaluation in EMS education.

The eleven attributes are:

1. Integrity
2. Empathy
3. Self-Motivation
4. Appearance and Personal Hygiene
5. Self-Confidence
6. Communications
7. Time Management
8. Teamwork and Diplomacy
9. Respect
10. Patient Advocacy
11. Careful Delivery of Service

---

## 2. Applicability to Simulation

Not all eleven attributes are observable in a text-based scenario simulation. The table below categorizes each attribute by its simulation applicability and scoring home.

| Attribute | Observable in Simulation | Scoring Home |
|---|---|---|
| Integrity | Partially — documentation accuracy, no fabricated findings | Narrative / CHART |
| Empathy | Yes — tone, family response, patient address | Professionalism |
| Self-Motivation | Partially — initiative in assessment and history | Clinical Performance |
| Appearance and Personal Hygiene | No — not applicable to text simulation | Not scored |
| Self-Confidence | Yes — decisiveness, clarity of direction | Professionalism |
| Communications | Yes — direction quality, family explanation, DMIST/CHART | Professionalism |
| Time Management | Partially — sequencing of critical vs. non-critical actions | Clinical Performance (sequencing) |
| Teamwork and Diplomacy | Yes — partner direction, team coordination | Professionalism |
| Respect | Yes — naming, language, patient dignity | Professionalism |
| Patient Advocacy | Yes — patient-centered decisions, no bias, confidentiality | Professionalism |
| Careful Delivery of Service | Partially — protocol adherence, safe technique | Protocols/Treatment + Scope (primary) |

### Attributes That Drive the Professionalism Score

The professionalism scoring category (10 points) should reflect these six attributes:

1. **Empathy** — interpersonal warmth and appropriate response to patient and family distress
2. **Communications** — clarity and adjustment of communication for the scene dynamic
3. **Teamwork and Diplomacy** — effective, respectful direction of the EMS partner
4. **Respect** — use of patient and family names, professional language, preservation of dignity
5. **Patient Advocacy** — patient-centered decision-making, no bias-influenced clinical choices
6. **Self-Confidence** — decisive and clear direction-giving; demonstrates clinical certainty appropriate to the situation

### Attributes Scored Elsewhere (Do Not Double-Count)

- **Integrity** in the documentation sense — whether the student charts what was actually done — is the primary determinism check in the narrative/CHART scoring category. Do not re-score it under professionalism.
- **Careful Delivery of Service** — protocol adherence, scope compliance, safety technique — is the core of `protocols_treatment` and `scope_adherence`. Do not re-score it under professionalism.
- **Time Management** — sequencing of critical vs. non-critical actions — is implicitly captured in the clinical performance scoring (late actions reduce the clinical evidence trail). It is not a primary professionalism signal in the rubric.
- **Self-Motivation** — initiative in assessment and history — is captured in clinical performance completeness (did they obtain the full history, perform the expected assessments?).
- **Appearance and Personal Hygiene** — not measurable.

---

## 3. Observable Behaviors by Attribute

This section defines the observable simulation behaviors for each professionalism-scored attribute. Authors should reference this when writing professionalism rubric bands for new scenarios. LLM adjudicators should evaluate against these criteria.

### 3.1 Empathy

**What it means in simulation:**  
The learner demonstrates compassion and appropriate emotional awareness when interacting with patients, families, and caregivers. This is not warmth for its own sake — it is recognizing and responding to the human dimension of the call.

**Observable behaviors (positive):**
- Acknowledges family distress or fear without dismissing it ("I can see how scared you are — we're taking care of her right now")
- Uses reassuring but honest language — does not provide false reassurance
- Addresses frightened or distressed family members before launching into clinical questions
- Explains what is happening in terms the family can understand
- Adjusts tone and pacing to the emotional state of the scene

**Observable behaviors (negative / missed):**
- Asks clinical questions immediately without acknowledging obvious family panic or distress
- Provides false reassurance ("she's going to be fine") before clinical information supports that claim
- Treats family as an obstacle to care rather than a source of history and a person who deserves communication
- Ignores frightened family member entirely during scene management

### 3.2 Communications

**What it means in simulation:**  
The learner communicates clearly and effectively with all scene participants — patient, family, partner, and (on handoff) ALS or receiving crew. This includes speaking with appropriate clarity, adjusting language to the audience, and using active communication to move care forward rather than creating confusion.

**Observable behaviors (positive):**
- Gives the EMS partner (Alex) specific, clear directions rather than vague commands
- Explains interventions to the patient and family in non-technical terms
- Asks focused, direct questions to obtain history
- Adjusts communication to the specific scene dynamic (panicked parent needs reassurance before questions; alert adult patient can be addressed clinically)
- Delivers a clear, organized DMIST with complete elements
- CHART narrative uses objective, organized, readable language

**Observable behaviors (negative / missed):**
- Vague or ambiguous partner directions ("go check on her")
- Technical jargon with family without explanation
- Rapid-fire questions that prevent family from answering
- DMIST missing critical elements or presented in disorganized sequence
- Narrative containing fabricated findings, excessive subjectivity, or poor organization

### 3.3 Teamwork and Diplomacy

**What it means in simulation:**  
The learner treats the EMS partner as a professional colleague, delegates effectively, maintains scene team cohesion, and coordinates care without being dismissive, overbearing, or undermining.

**Observable behaviors (positive):**
- Delegates specific tasks to Alex using clear, concise direction ("Alex, apply oxygen NRB 15 LPM")
- Acknowledges partner inputs and confirms actions
- Does not issue contradictory directions
- Coordinates assessment and treatment tasks between self and partner without creating confusion
- Adjusts plan when partner reports unexpected findings

**Observable behaviors (negative / missed):**
- Ignores the partner entirely — treats the scene as a solo effort
- Issues impossible, contradictory, or excessively vague directions
- Disregards or overrides partner findings without clinical rationale
- Monopolizes all tasks rather than delegating appropriately

### 3.4 Respect

**What it means in simulation:**  
The learner maintains the dignity of the patient and family. This includes using names, professional language, and appropriate clinical descriptions. Disrespectful behavior in simulation — even in text — demonstrates a pattern of behavior that must be addressed.

**Observable behaviors (positive):**
- Addresses the patient by name (not just "the patient" or "she")
- Addresses family members by name or appropriate title ("Jennifer," "Sir," "Mom")
- Uses professional language throughout — no derogatory or dismissive descriptions
- Describes clinical findings objectively without dehumanizing language
- Preserves patient dignity in assessment and treatment descriptions

**Observable behaviors (negative / missed):**
- Refers to patient only as "the patient," "the kid," or similar without ever using the patient's name
- Uses dismissive or derogatory language about patient or family
- Assessment descriptions that depersonalize or demean
- Discussing patient clinical details in ways that would be inappropriate in front of the patient or family

### 3.5 Patient Advocacy

**What it means in simulation:**  
The learner places patient needs above personal interest, efficiency, or assumption. This means not letting patient presentation, demeanor, or caregiver history bias clinical assessment, and not delaying care for reasons unrelated to clinical judgment.

**Observable behaviors (positive):**
- Does not dismiss a patient's symptom because it seems mild
- Does not withhold or delay care because of patient demographics, behavior, or caregiver presentation
- Protects patient information — does not volunteer patient details outside the clinical necessity of the call
- Advocates for the appropriate scope of care regardless of resource constraints
- Does not allow family pressure to override clinical protocol

**Observable behaviors (negative / missed):**
- Delays or withholds indicated care based on patient behavior or presentation demeanor
- Dismisses parent/caregiver concern without clinical rationale
- Prematurely reassures family that the patient is fine before adequate assessment
- Allows the scenario presentation to bias toward a diagnosis without appropriate differential consideration

### 3.6 Self-Confidence

**What it means in simulation:**  
The learner demonstrates appropriate clinical certainty. This does not mean overconfidence — it means the learner makes decisions, communicates them clearly, and follows through rather than hedging indefinitely or abandoning clinical judgment under pressure.

**Observable behaviors (positive):**
- Gives clear, direct directions without excessive hedging ("Turn her on her side" not "maybe we could try turning her")
- Makes clinical decisions and states them clearly
- Demonstrates appropriate decisiveness under time pressure
- Recognizes and states clinical scope limitations clearly when applicable ("That's outside my scope — I'm communicating that to ALS")
- Does not abandon a correct clinical decision under family pressure without new clinical information

**Observable behaviors (negative / missed):**
- Hedging or indefinite language when clear direction is clinically indicated
- Unable to state a clinical impression or plan when the scenario calls for one
- Abandoning a correct plan under family or bystander pressure without new information
- Asking for guidance on actions that are clearly within the learner's scope and competency level

---

## 4. Professionalism Rubric Band Guidance

Use this guidance when authoring professionalism rubric text in scenario JSON files. The full/partial/minimal credit bands should reflect the observable attribute behaviors above.

### Full Credit (8–10 points)

All applicable simulation-observable attributes demonstrated:
- Empathy: acknowledged family/patient distress, responded appropriately
- Communications: clear partner directions, explained interventions to family, DMIST/CHART complete and clear
- Teamwork: partner directed specifically, tasks coordinated effectively
- Respect: patient and family addressed by name, professional language throughout
- Patient Advocacy: patient-centered decisions, no unwarranted bias or delays
- Self-Confidence: decisive direction, clear clinical communication

Name the specific positive behaviors in the rubric text — don't use these generic terms. "Addressed Chloe by name and explained suction to Jennifer before performing it" is more useful than "demonstrated respect and communications."

### Partial Credit (4–7 points)

One or two specific attribute gaps — name the gap explicitly in the rubric text. The most common partial-credit scenarios:
- Clinical tasks performed well but family never addressed or reassured
- Partner directions vague or frequently repeated without being completed
- Patient name never used despite knowing it
- DMIST clear but family communication absent
- Empathy present but communications with partner disorganized

### Minimal Credit (0–3 points)

Multiple attribute failures, or a single severe failure. The minimal failure must be scene-specific — do not default to the generic "focused only on clinical tasks" language. Examples:
- Family member in obvious panic never acknowledged while learner performs clinical actions
- Partner never directed — scene treated as solo with no team coordination
- Patient and family never addressed by name despite knowing both names throughout the scenario
- Harsh, dismissive, or dehumanizing language used toward patient or family
- Fabricated or inaccurate documentation that misrepresents what was done

---

## 5. Attribute Weight Within the Professionalism Score

All six professionalism-scored attributes are weighted equally within the 10-point bucket. The LLM adjudicator should consider:

- **6/6 attributes clearly demonstrated** → 9–10
- **5/6 attributes demonstrated** → 7–8
- **4/6 attributes demonstrated** → 5–6
- **3/6 or fewer, or one severe failure** → 0–4

The adjudicator should not require perfection. A learner who communicated well with family and partner, used patient and family names, and demonstrated clinical decisiveness — but gave one vague partner direction — is still demonstrating professional behavior and should not be penalized to the partial-credit band for a single minor gap.

---

## 6. Relationship to Formal Program Evaluation

This framework maps a simulation scoring rubric to the NASEMSO affective domain model, but it does not reproduce the full rigor of a programmatic affective evaluation.

Important distinctions:
- A single simulation session cannot determine **competence** in any affective attribute — only whether a specific observable behavior was present in that session. The NASEMSO model explicitly requires patterns across multiple evaluations before competency or non-competency determinations.
- The simulator does not measure attributes that require longitudinal observation: self-motivation trends, time management patterns across shifts, or appearance and hygiene.
- The simulator does not replace instructor-observed affective evaluations. It surfaces data points that should inform instructor evaluation, not substitute for it.
- The Professional Behavior Counseling Record process (for incident documentation and remediation) is a programmatic function — not a simulation feature.

For initial education programs using RescueTrails: the professionalism score from individual sessions should feed into a cumulative picture of the learner's affective performance, alongside clinical rotations and classroom instructor observations. A single session's professionalism score is a data point, not a competency determination.

---

## 7. Future Deterministic Professionalism Items

Currently, all professionalism scoring is LLM-adjudicated. In future, deterministic checklist items can be added for the most reliably pattern-matchable behaviors:

| Candidate behavior | Candidate tier | Pattern type |
|---|---|---|
| Patient addressed by name at least once | Tier 2 | Transcript pattern: patient name in a communication context |
| Family member addressed by name or role | Tier 2 | Transcript pattern: family name/role in a communication context |
| Explicit reassurance or empathy statement | Tier 2 | Transcript pattern: reassurance phrasing |
| Partner directed at least once | Tier 2 | Transcript pattern: direction to Alex/partner |

These items should only be added when the tier 2 patterns can be authored without high false-positive risk. They are candidates, not commitments.
