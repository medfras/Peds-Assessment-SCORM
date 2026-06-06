# Learning Design — GBL Principles & Improvement Roadmap

**Status:** Active Reference
**Last Updated:** 2026-04-30
**Scope:** Game-based learning principles as applied to RescueTrails; instructional design gaps and improvement recommendations. This document does not supersede subsystem architecture docs — it frames the *why* behind design decisions and surfaces gaps for future work.

---

## 1. Design Rules

These rules govern how game mechanics, UI decisions, and content are evaluated for pedagogical soundness. When a proposed feature conflicts with one of these rules, the conflict should be made explicit before proceeding.

**Rule 1 — Structural mechanics must carry a learning function.**
Not every element of the game loop requires a direct clinical objective. Low-cost atmosphere, delight, and polish are acceptable when they support motivation, orientation, and return behavior without adding cognitive interference to the learning task. The rule targets *structural* mechanics: how progression is gated, how rewards are earned, and how feedback is sequenced. A decorative ambient animation needs no learning rationale; an earning mechanic that lets a student bypass practice does.

**Rule 2 — Cognitive cost must match cognitive gain.**
Friction in the UI (tab switching, typing, modal depth) and cost in the economy (treats, replay effort) must be proportional to the learning value of what they gate. Unearned friction is extraneous cognitive load. Deliberate friction — paying a treat for a hint — is desirable difficulty.

**Rule 3 — Feedback before the student asks for it.**
Debrief architecture must lead with the most actionable signal. Actionable information buried at the bottom of a long modal is not feedback — it is an archive. Adults in high-stakes fields close windows.

**Rule 4 — Challenge calibrated to demonstrated competence.**
Difficulty should scale with evidence of mastery, not elapsed playtime. A student who aces five respiratory scenarios in a row should encounter harder cases, not the same difficulty tier.

**Rule 5 — Distributed practice beats massed practice.**
Reviewing five scenarios once each over five days outperforms reviewing five scenarios back-to-back in one session (Ebbinghaus, spacing effect). System design should structurally reinforce distribution, not just allow it.

**Rule 6 — Mixing beats matching.**
Scenarios encountered in varied context — different chief complaints, different patient demographics, different acuity — produce more durable knowledge than the same scenario type repeated in sequence (interleaved vs. blocked practice). Pure trail-blocking is a pedagogical tradeoff, not a free choice.

**Rule 7 — Deterministic authority cannot be diluted by generative output.**
Any scoring, progression gate, or clinical fact must be resolved by deterministic logic. LLM output is coaching and narrative, never adjudication. This is already the architectural core; it is listed here so future feature proposals are evaluated against it explicitly.

**Rule 8 — The platform trains cognition, not performance.**
RescueTrails explicitly develops clinical decision-making, protocol knowledge, assessment sequencing, and documentation. It does not develop psychomotor execution, spatial scene navigation, physical team coordination, or stress inoculation. This scope must be stated clearly in onboarding and instructor materials. Learners who graduate to real calls believing this platform has trained their hands are a patient safety risk.

**Rule 9 — Collection reflects competence, not playtime.**
Rewards and collectibles should be meaningful indicators of demonstrated clinical skill, not time investment. The Epic drop mechanic (mastery + zero hints) already enforces this for the top rarity tier. The principle should propagate throughout the reward architecture.

**Rule 10 — Metacognition is a trainable skill.**
The platform should prompt self-assessment and confidence evaluation alongside performance measurement. Miscalibrated confidence — high certainty in wrong answers — is the failure mode that harms patients. Surfacing calibration data to learners and instructors is a clinical safety intervention, not a feature nicety.

---

## 2. Debrief Architecture

### 2.1 Current State
The debrief is structured as a sequential multi-section markdown document, with Key Takeaways at the end. This violates Rule 3. Most adult learners in high-acuity fields close a long modal after the score and the first visible feedback block. Everything after that is sunk.

### 2.2 Target Presentation Order

| Layer | Content | Interaction |
|---|---|---|
| 1 — The Hook | Score banner, pass/fail, critical failure flag if applicable | Always visible |
| 2 — The Lesson | Critical misses (any rubric item failed) + Top 3 takeaways | Always visible, concise |
| 3 — The Detail | Full clinical breakdown: pathophysiology, timeline, CHART review, AI qualitative commentary | Collapsed accordion, opt-in |
| 4 — Next Action | Specific actionable recommendation: retry scenario, play a specific minigame, review a protocol area | Always visible |

The goal is that a student who closes the modal after 15 seconds has still received the most important clinical feedback. The detail layer is for students who want depth — it should not be the container for the most important information.

### 2.3 Actionable Next Step
The debrief's final element should always be a specific call to action generated by the AI within the structured output, not a generic "review your protocols." Examples:

- "You missed the anaphylaxis criteria on two assessments. The PAT Doorway Dash has an anaphylaxis recognition module — I'd run that before your next call."
- "Your scene safety and primary survey were excellent. The clinical gap was medication dosing. Consider replaying the Anaphylaxis scenario focusing specifically on drug selection."

The recommendation *target* — which scenario to replay, which mini-game to run, which protocol area to review — must be derived from deterministic performance signals: missed rubric categories, unvisited content, low-confidence domains. The LLM handles phrasing only. This keeps instructional routing auditable and prevents advice that sounds tailored but was pedagogically arbitrary. The structured output includes a routing target field populated by backend logic before the LLM call; the AI wraps it in natural language.

**Next Action Decision Table**

The backend evaluates conditions in strict priority order. The first matching rule wins.

| Priority | Condition | Recommendation target type | Recommendation target |
|---|---|---|---|
| 1 | Highest-weight rubric category failed (score < 60% of that category's max) | `scenario` | Replay the current scenario with debrief focus on the failed category |
| 2 | Impression challenge answered incorrectly | `scenario` | Replay the current scenario; debrief surfaces correct impression and differential |
| 3 | Overdue Random Call review item (`review_due ≤ today`) | `random_call` | Trigger a Random Call weighted toward the overdue scenario |
| 4 | Oldest uncleared required scenario in the student's accessible pool | `scenario` | Navigate to and start that scenario |
| 5 | Mini-game exists with a declared rubric-category mapping matching the failed category | `minigame` | Recommend the mapped mini-game |
| — | None of the above (clean run, no overdue items, no uncleared scenarios) | `none` | Generic "here's what's next on your trail" — no specific target |

**Tie-break rule:** If multiple conditions at the same priority level are satisfied simultaneously (e.g., two rubric categories both failed below threshold), select the category with the highest point weight in the scoring rubric. If weights are equal, use alphabetical category ID order.

**Mini-game recommendation constraint:** Priority 5 only fires when a mini-game with a declared `rubric_category_mapping` field exactly matches the failed category. Do not recommend a mini-game as a proxy for a gap it does not directly target.

**Fallback safety:** If the backend cannot compute a recommendation (missing data, first-ever run with no history), emit `next_action_target_type: "none"` and let the AI generate a generic encouraging message. Never hallucinate a specific target ID.

### 2.4 Guided Reflection Prompts

The presentation order in §2.2 improves how feedback is *delivered*. Reflection prompts engage a different cognitive mechanism — they require the student to *process* the feedback rather than just receive it. Strong GBL debriefs combine performance feedback with brief guided reflection.

The debrief AI should include 1–2 reflection prompts generated as structured output alongside the coaching narrative, drawn from the student's actual decisions in that run:

- "What was your first clue that this patient was deteriorating?"
- "What finding almost led you toward a different diagnosis?"
- "What assessment would you add in the first two minutes if you ran this call again?"

These prompts do not require a written response — they are prompts for internal processing. Display them in the collapsed Layer 3 (The Detail) so they are available for students who engage deeply with the debrief without adding scroll burden for students who close after the BLUF. The prompts must vary based on run data, not be static templates.

---

## 3. Random Call — Spaced Repetition Algorithm

### 3.1 Current State
Random Call selects from the student's accessible scenario pool without weighting. This misses the most powerful retention mechanism available: surfacing scenarios at the moment the student is at maximum risk of forgetting them.

### 3.2 Target Algorithm
Each played scenario in a student's history maintains two values:

- `interval_days` — how many days until the scenario should be reviewed
- `ease_factor` — how quickly the interval grows (default 2.5)

After each Random Call completion, these update based on score:

| Score | Interval update | Ease factor update |
|---|---|---|
| ≥ 85% | `interval × ease_factor` | ease_factor += 0.1 (max 3.0) |
| 70–84% | `interval × 1.8` | no change |
| < 70% | interval = 1 day | ease_factor -= 0.2 (min 1.3) |

Scenarios with `review_due ≤ today` are weighted **4×** in the Random Call selection pool. Scenarios the student has never played are weighted **2×** (encourage first contact with new content before drilling mastered content). All other eligible scenarios have weight 1×.

This is a simplified SM-2 model (Leitner/Anki family). Implementation requires a new `StudentScenarioHistory` junction table with a unique constraint on `(user_id, agency_id, scenario_id)`. The `SimSession` model tracks per-run data and is not the right storage unit for SM-2 state, which is per-user-per-scenario aggregate state that must survive across multiple runs. The three SM-2 fields — `interval_days`, `ease_factor`, and `last_random_call_date` — live on this new table alongside a `best_rc_score` field used to drive updates.

### 3.3 What This Does Not Include
Pre-brief injection of prior notes and missed items is deferred pending a separate decision about Random Call scenario variation (whether patient demographics are modified to create surface-level novelty). That feature's design affects how retrieval cues should be surfaced. The spaced repetition selection algorithm is independent of that decision and can be built first.

### 3.4 The Learning Unit — Current Constraint and Target

The algorithm above treats the *whole scenario* as the memory unit. A student who fails a scenario for documentation reasons receives the same "review due" weight as one who missed a critical clinical intervention. These are different competencies and conflating them risks reinforcing the wrong thing.

**Current constraint:** Use scenario-level score as the scheduling unit, since per-skill data does not yet exist. Mitigate by ensuring the debrief clearly separates score contributors by rubric domain (assessment sequencing, medication selection, documentation quality, diagnostic reasoning) so the student can attribute the "review due" signal to a specific skill gap — even if the scheduler cannot yet do so automatically.

**Target (future):** Tag subskills to individual rubric items (`assessment_sequencing`, `medication_selection`, `documentation_quality`, `diagnostic_reasoning`, `medication_math`). The scheduler surfaces scenarios weighted toward the student's weakest tagged subskills, not just lowest-scoring scenarios overall. This requires a skill-tag model on rubric items and is a future data model extension, not a current constraint.

---

## 4. Reward Architecture — Collectible-to-Competency Mapping

### 4.1 Current State
The live implementation uses toys grouped by district (Puppy Park, Neighborhood Walk, etc.), which maps to scenario category. That coarseness is useful for an instructor heat map view, but the presentation layer is drifting away from the professional/product direction now planned. The underlying instructional problem remains the same: at the individual collectible level, the reward needs to communicate clinical meaning. A student who earns a top-tier collectible from the pediatric district should understand *which* clinical domain it represents, not just that they got “some pediatric reward.”

### 4.2 Target State
The planned visible collectible layer is:

- **Challenge coins** — primary district/map completion collectibles
- **Station / unit patches** — branch and convergence milestone rewards
- **Pins / decals** — smaller side rewards for mini-games, streaks, or special accomplishments

Regardless of which visible collectible type is used, each collectible should carry a `primary_pathophysiology` tag that maps to the scenario or map competency it represents (e.g., `"bronchospasm"`, `"anaphylaxis"`, `"septic_shock"`). This tag drives:

- **Collectible description/flavor text** — A sentence connecting the coin, patch, or pin to the clinical concept it represents.
- **Instructor heat map granularity** — Rather than “Pediatric district: 8 rewards,” the instructor sees which specific pathophysiologies are well represented (deep Rare/Epic coverage) vs. thin or absent.
- **Phase 5 "Next Best Action" routing** (per REWARDS.md §5) — Lexi's recommendations become pathophysiology-specific: "You have no coverage in bronchiolitis — want to try that next?"

This requires no fundamental change to the reward-selection logic. It is primarily a metadata and presentation change.

### 4.3 Thematic Coherence Within Districts
The planned district-map framing is more professionally aligned: pediatric community response, adult medical response, adult trauma response, and complex incident response. That is a better outer frame for an EMS training product than whimsical biome naming. The collectible layer should reinforce that frame rather than compete with it.

Recommended alignment:

- **Challenge coins** represent district or map mastery
- **Patches** represent branch identity or convergence completion
- **Pins / decals** represent focused side accomplishments

This is a content-design decision more than a scoring-engine change, but it matters instructionally because rewards shape what learners believe the platform values.

### 4.4 Station Dashboard Framing

The planned home experience is shifting toward a **station dashboard** with districts laid out on a map. From a learning-design perspective, this is a good move if handled carefully:

- it improves market-facing professionalism
- it strengthens orientation and mental mapping of content areas
- it keeps progression visible without requiring a flat list of categories

The key requirement is that district names and visuals stay tied to **prehospital scene families**, not hospital departments or abstract game biomes. That means:

- pediatric district = schools, daycares, homes, playgrounds, family/public community calls
- adult medical district = homes, workplaces, public collapse/illness settings
- adult trauma district = roadway, industrial, recreational, violence/injury settings
- complex incident district = high-acuity, multi-system, convergence, advanced events

This supports both learner orientation and buyer credibility without weakening the platform’s warm companion tone.

---

## 5. Confidence Calibration

### 5.1 The Problem
Research in medical education consistently shows that miscalibrated confidence — high certainty in wrong clinical judgments — is a more dangerous failure mode than low confidence. A student who knows they don't know something will look it up. A student who is confidently wrong will not. The current platform measures performance but not calibration.

### 5.2 Deferred Mechanic
Do not add a pre-scenario confidence check to new scenarios or the dispatch/pre-scene flow until confidence data is connected to a visible learner or instructor outcome. The previous standalone dispatch prompt was removed because it created friction without affecting coaching, scoring, or analytics.

If confidence calibration is reintroduced, the minimum viable prompt is:

> *"How confident are you assessing a patient with [chief complaint category]?"*
> ○ 1 — Not confident  ○ 2  ○ 3  ○ 4  ○ 5 — Very confident

The data must then be used after the debrief:

> *"You rated confidence 4/5 going in. Your assessment score was 71% (Cleared). Calibration: slightly overconfident."*

Track this over time. Aggregate calibration score by clinical category should be visible to the student on their profile and to instructors on the dashboard.

### 5.3 What Not to Do
- Do not gate scenario entry on confidence rating (friction without value)
- Do not use confidence as a scoring input (the score must remain purely performance-based)
- Do not ship a standalone confidence prompt that is not persisted, displayed, or used for coaching/analytics
- Do not show the confidence prompt on replays unless the student hasn't played this specific scenario in 30+ days (it becomes annoying noise on familiar content)

### 5.4 Strengthening the Signal

A single pre-scenario confidence rating by chief complaint category captures affect and familiarity more than true calibration. It is the minimum viable signal and should be built first, but the instructor-facing calibration view is meaningfully stronger with additional data points:

- **Post-case confidence on the final impression** — prompt the student to rate confidence in their primary impression just before narrative submission. Pairs a rating with a specific clinical judgment rather than a general readiness feeling.
- **Per-challenge confidence** — ECG and capnography challenges can include a secondary "How sure were you?" field after selection. Generates calibration data at the granularity of specific clinical skills (rhythm recognition, waveform interpretation) rather than general case confidence.
- **Impression challenge comparison** — the early/final/correct three-way comparison in §7.3 Component 3 is itself a calibration measurement, expressed structurally rather than numerically. No additional prompt is needed to generate this data.

Do not make instructor-facing calibration claims based solely on the coarse pre-scenario rating. Label the confidence data as directional self-report until the higher-granularity measures are in place.

---

## 6. Practice Structure — Interleaving vs. Blocking

### 6.1 The Tradeoff
The trail topology creates blocked practice: all respiratory scenarios before advancing to cardiac, all trauma before emergencies. Blocked practice feels more productive because each case feels familiar — but research (Rohrer & Pashler, 2010) consistently shows interleaved practice produces better retention and transfer, precisely because the student must re-identify the problem category on each encounter rather than relying on context.

This is a deliberate architectural tradeoff. The trail structure serves narrative coherence, progression clarity, and prerequisite gating. It is not wrong — but its cost should be understood and mitigated elsewhere.

### 6.2 Where Interleaving Already Exists
- **Random Call** is the primary interleaving mechanism. If its selection algorithm is upgraded per §3, it becomes a strong distributed interleaving tool.
- **Convergence maps** (PM7, PT8, PE1) create mixed-context assessment gates. This is structurally correct.

### 6.3 Future Mitigation
- A **"Blended Shift" mode** — a curated daily or weekly set that explicitly interleaves one medical, one trauma, and one edge-case scenario — would provide deliberate interleaving without restructuring the map topology.
- **Cross-trail bonus scenarios** at hub maps could introduce scenario types outside the trail's primary domain, creating interleaving opportunities within the map progression.

**The Random Call algorithm fix (§3) is the highest-priority interleaving intervention** — it affects all returning students immediately and requires no map topology change. The Blended Shift mode and cross-trail bonus scenarios are medium-priority and should be scheduled after the Random Call algorithm is live, not as replacements for it.

The blocked practice problem is not a future concern — it affects every student progressing through the current map today. Interleaving mitigation should not wait for challenge catalog implementation or other lower-urgency features.

---

## 7. Diagnostic Reasoning & Primary Impression

### 7.1 Current State

Every rubric item is outcome-based: intervention applied or not, required assessment completed or not. The system captures *what* the student did but not *how they reasoned*. A student who gives oxygen reflexively scores the same as a student who correctly identified hypoxia from a deteriorating SpO2 trend and applied oxygen as a targeted intervention.

The primary impression field now exists on both completion paths, but the larger instructional gap remains:

- In the **narrative path** (BLS / non-transport): the impression is a required free-text field in Step 3 of the narrative modal. It is still primarily used as part of the narrative/debrief package rather than as a high-authority structured reasoning checkpoint.
- In the **DMIST path** (ALS / transport): the treatment/turnover flow now captures a required free-text `dmist_primary_impression`, which fixes the old placeholder problem and gives both paths a final documented impression.
- The remaining timing issue is unchanged: both fields are captured *after treatment has been delivered*. That makes them valuable final-impression documentation, but still weaker than an earlier reasoning capture point. Without an early checkpoint, the system cannot cleanly compare what the student thought was happening before treatment versus what they concluded at handoff.

### 7.2 The Gap

Clinical reasoning — hypothesis formation before treatment commitment, differential ruling, recognizing the mechanism driving deterioration — is the core cognitive competency EMS education targets. It is currently underassessed relative to its clinical importance for two reasons:

1. **Timing**: capturing the impression after treatment tells you the student can label the diagnosis they just treated. Capturing it before treatment tells you whether they understood the patient well enough to commit to a correct path.
2. **Structure**: a free-text impression evaluated by the LLM as part of a narrative block is lower-authority adjudication than a structured selection compared against a declared correct answer (Rule 7). It also cannot generate the debrief comparison that makes the gap visible to the student.

### 7.3 Target State

Three components, each independent and incrementally valuable:

#### Component 1 — Mid-Scenario Primary Impression Challenge

A structured prompt fires at a defined evidence packet milestone — after the primary survey is completed, or at a scenario-declared trigger point. The student selects their working clinical impression from a short list of 3–4 plausible differentials declared by the scenario author.

**Why structured selection instead of free text:** Rhythms, diagnoses, and impressions have canonical names. Free text at this point creates a fuzzy-match scoring problem and LLM dependency. A structured list is deterministic, faster for the student, and easier to author. It also implicitly teaches the student which diagnoses belong in the differential for a given presentation — the distractor options are themselves educational content.

**Authoring contract — scenario JSON:**
```json
"impression_challenge": {
  "enabled": true,
  "trigger_milestone": "primary_survey_complete",
  "prompt": "Based on your initial assessment, what is your primary clinical impression?",
  "options": [
    "Reactive airway disease / asthma exacerbation",
    "Anaphylaxis with bronchospasm",
    "Foreign body obstruction",
    "Croup / upper airway infection"
  ],
  "correct": "Reactive airway disease / asthma exacerbation",
  "acceptable": ["Anaphylaxis with bronchospasm"]
}
```

The `acceptable` array allows partial credit for reasonable differentials. Selecting anaphylaxis when asthma is correct is a different clinical error than selecting croup — the system should distinguish them.

**Distractor authoring standard:** The diagnostic value of the impression challenge depends entirely on distractor quality. Distractors that are obviously implausible, from clearly different acuity bands, or easily ruled out by visible patient data turn the challenge into a test-taking exercise rather than a clinical reasoning task. Authors must ensure:

- All distractors are plausibly correct given the chief complaint and initial presentation at the time the challenge fires
- At least one distractor overlaps substantially in mechanism or presentation with the correct answer
- No distractor is obviously inconsistent with patient age, vital signs, or mechanism as presented
- Distractor sets should be reviewed periodically — students who replay a scenario are at risk of learning the option set rather than reasoning from the patient

**Scoring:** Correct selection earns a dedicated clinical reasoning point in the evidence packet. Acceptable earns partial credit. Incorrect earns zero and sets a flag the debrief AI can reference. No penalty worse than zero — the goal is reasoning assessment, not punishment for clinical uncertainty.

**Evidence packet fields added:** `impression_challenge: { student_answer, correct, acceptable, timestamp_relative_to_first_intervention, result }`

The timestamp relative to first intervention is the meaningful signal: if the student answered correctly *before* administering treatment, that confirms their treatment decisions were hypothesis-driven. If they answered correctly *after*, it may indicate they reasoned backward from treatment response.

#### Component 2 — DMIST Modal Impression Field

The DMIST radio report modal should include an explicit required "Primary impression" text field, replacing the `"(from narrative)"` placeholder in the treatment record submission. This makes impression capture consistent across both paths and is authentic to practice — the radio report always includes the provider's clinical impression.

This is a smaller change than Component 1 and can be built independently.

#### Component 3 — Debrief Three-Way Comparison

With both an early impression (Component 1) and a final impression (Component 2 / narrative modal), the debrief gains a new element:

| | Student's answer | Score |
|---|---|---|
| Early impression (after primary survey) | Anaphylaxis with bronchospasm | Acceptable (partial) |
| Final impression (at transport / narrative) | Reactive airway disease / asthma exacerbation | Correct |
| Correct impression | Reactive airway disease / asthma exacerbation | — |

Narrative coaching the AI can generate from this pattern: *"You started with anaphylaxis as your working impression — a reasonable differential given the presentation — but refined it correctly before transport. That's good clinical reasoning under uncertainty. One thing to watch: your treatment pathway (albuterol, positioning) was correct for asthma but would have been inadequate for true anaphylaxis. In a higher-acuity version of this presentation, starting with the right impression matters more."*

This level of reasoning feedback is not possible from the current architecture. It is the highest-value output of this feature set.

---

## 8. In-Scenario Modal Challenges

### 8.1 Current State

Two challenge modals exist:

- **Lung sound challenge**: Triggered by explicit student auscultation request when `lung_sound_challenge.enabled` is set in the scenario. Presents an audio recording; student identifies what they hear in free text. Supports a post-treatment variant (e.g., wheezes clearing after albuterol). Finding fed back into AI context and evidence packet.
- **Med admin challenge**: Medication confirmation modal presented when the student selects a drug from the jump bag.

These establish the authoring and runtime pattern all future challenges should follow.

### 8.2 The Pattern (Contract for All Challenge Types)

Every challenge — existing and future — adheres to this contract:

1. **Opt-in**: `[challenge_type]_challenge.enabled: true` in scenario JSON. No scenario is required to use any challenge.
2. **Trigger**: explicit student action matching a recognized intent (request for the relevant assessment or intervention selection). Challenges are never passive interruptions.
3. **Determinism**: the correct answer is declared in the scenario JSON and evaluated by the backend. No LLM is involved in scoring a challenge result.
4. **Evidence**: result (student answer, correct answer, pass/fail, timestamp) written to the evidence packet.
5. **AI context**: result injected into the AI's next response so Alex/Lexi can react appropriately to what the student identified.
6. **Dismissible**: the modal can be closed without answering. A skipped challenge records `result: "skipped"` in the evidence packet — not a failure, but a signal. Forcing completion creates a friction wall inconsistent with the lung sound precedent.
7. **Vitals independence**: challenge modals do not pause the vitals engine. The clock continues while the student is engaged with the challenge.

### 8.3 Challenge Catalog

#### ECG / Rhythm Strip — Priority: High

**What it assesses:** Cardiac rhythm recognition — rate, regularity, rhythm name, and clinical significance.

**Current state:** No ECG challenge exists. Rhythm interpretation is only assessed via free-text conversation or implicitly through treatment selection.

**Trigger:** Student requests an ECG or 12-lead assessment, or asks Alex to "run a strip."

**Challenge format:** Displays a rhythm strip image. Student selects the correct rhythm from 3–4 labeled options. Multiple-choice is intentional — rhythm names have canonical forms, and free text at this step is an unnecessary NLP problem.

**Post-treatment variant:** Scenario can declare a second rhythm config (e.g., post-cardioversion result) that replaces the initial challenge on subsequent requests.

**Scenario JSON fields:**
```json
"ecg_challenge": {
  "enabled": true,
  "image_url": "/static/img/ecg/svt_narrow.png",
  "options": ["Sinus tachycardia", "SVT", "Atrial flutter", "AVNRT"],
  "correct": "SVT",
  "post_treatment": {
    "requires_intervention_id": "adenosine_6mg",
    "image_url": "/static/img/ecg/normal_sinus.png",
    "correct": "Normal sinus rhythm"
  }
}
```

**Evidence packet:** `ecg_challenge: { student_answer, correct, result, timestamp }`

---

#### Medication Math — Priority: High (pediatric scenarios)

**What it assesses:** Weight-based dose calculation — the highest-error-rate clinical skill in pediatric EMS. An error here is directly patient-harmful.

**Current state:** No medication math challenge exists. Dosing is assessed only via intervention selection (right drug selected) but not calculation accuracy (right dose computed).

**Trigger:** Student selects a weight-based medication from the jump bag when `med_math_challenge.enabled` is set. The challenge fires *before* the medication is administered and the intervention is logged.

**Challenge format:** Displays patient weight, drug name, concentration, and ordered dose/kg. Student enters the calculated volume to draw up. Backend computes the correct answer from scenario data and validates within ±5% tolerance.

**Why this is high priority:** A student who selects "epinephrine" correctly but administers 10× the pediatric dose has made the most dangerous type of error in EMS — and the current system cannot detect it. This challenge closes that gap with no LLM dependency.

**Scenario JSON fields:**
```json
"med_math_challenge": {
  "enabled": true,
  "triggered_by_intervention_id": "epinephrine_im",
  "dose_per_kg": 0.01,
  "concentration_mg_per_ml": 1.0,
  "unit": "ml",
  "tolerance_pct": 5
}
```
Patient weight is drawn from the scenario's existing patient record. The backend computes `correct_volume = (weight_kg × dose_per_kg) / concentration`.

**Evidence packet:** `med_math_challenge: { triggered_by, patient_weight_kg, student_answer, correct_answer, within_tolerance, result }`

---

#### Capnography Interpretation — Priority: Medium (ALS-primary)

**What it assesses:** ETCO2 waveform and value interpretation — a critical ALS assessment tool for ventilation monitoring, airway confirmation, and CPR quality.

**Current state:** No capnography challenge exists. ETCO2 values surface in the vitals panel but interpretation is not assessed.

**Trigger:** Student requests ETCO2 or end-tidal CO2 assessment.

**Challenge format:** Displays a waveform image and numeric value. Student selects the correct clinical interpretation from a structured list.

**Interpretation options (standard set):**
- Normal ventilation
- Hypoventilation (ETCO2 elevated, normal waveform)
- Bronchospasm (shark fin waveform)
- CPR quality issue (low ETCO2 during compressions)
- No waveform — possible esophageal placement
- Metabolic acidosis (gradual sustained decline in ETCO2)

**Scenario JSON fields:**
```json
"capnography_challenge": {
  "enabled": true,
  "waveform_image": "/static/img/capnography/shark_fin.png",
  "etco2_value": 28,
  "options": ["Normal ventilation", "Bronchospasm", "Hypoventilation", "Esophageal placement"],
  "correct": "Bronchospasm"
}
```

**Evidence packet:** `capnography_challenge: { student_answer, correct, etco2_value, result, timestamp }`

---

#### Spinal Motion Restriction (SMR) Decision — Priority: Medium

**What it assesses:** Application of current spinal motion restriction criteria — a high-controversy, frequently-updated area of EMS protocol that generates significant clinical errors in both directions (over-application and under-application).

**Current state:** No SMR decision challenge exists. Spinal immobilization is treated as a binary intervention (applied / not applied) with no assessment of whether the clinical criteria were met.

**Trigger:** Student attempts to apply spinal motion restriction or cervical collar.

**Challenge format:** Before the intervention is logged, presents the patient's reported mechanism, exam findings (midline tenderness, neuro deficits, distracting injury), GCS, and complaint. Student selects: "SMR indicated" or "SMR not indicated" and identifies the primary criterion driving their decision.

**Why this matters:** The wrong answer in either direction is a patient harm event. Over-application immobilizes patients who don't meet criteria; under-application may miss unstable injuries. Protocol standards have changed materially in the last decade and continue to vary by MCA.

**Scenario JSON fields:**
```json
"smr_challenge": {
  "enabled": true,
  "indicated": false,
  "displayed_criteria": [
    "GCS 14 — mild alteration",
    "No midline tenderness on palpation",
    "No neurological deficits",
    "Mechanism: low-speed MVA, ambulatory at scene"
  ],
  "correct_decision": "not_indicated",
  "correct_criterion": "Mechanism does not meet SMR threshold per current protocol"
}
```

**Evidence packet:** `smr_challenge: { student_decision, correct_decision, correct_criterion, result, timestamp }`

---

#### Procedure Sequencing — Priority: Lower (higher development cost)

**What it assesses:** Correct procedural order for multi-step interventions — IO access, needle decompression, RSI checklist preparation.

**Current state:** No procedure sequencing challenge exists.

**Challenge format:** Student orders a set of procedural steps presented in shuffled order (numbered selection or drag-and-drop). The correct order is declared in the scenario JSON as an ordered array.

**Architecture note:** This requires a new reusable UI component (a generic sequencing challenge renderer) that scenario JSON populates with a step array. It should not be a custom modal per procedure — the renderer handles layout and interaction, the scenario data drives the content. **Defer until the higher-priority challenges above are stable.** Build the renderer as a shared component so ECG, capnography, and sequencing challenges all use the same modal shell.

### 8.4 Shared Challenge Shell — Architecture Decision

All in-scenario challenges use a single reusable modal shell with pluggable content types. This is a firm architectural decision, not a cleanup preference. Building the shell before the second challenge prevents the expensive refactor of independently-built modals.

**Shell responsibility:** layout, header, dismiss behavior, evidence packet write, AI context injection, timing, animation. The shell is challenge-type-agnostic.

**Content type plugins** (each is a renderer the shell calls with challenge data):

| Plugin | Used by |
|---|---|
| `single-choice` | ECG/rhythm strip, capnography, impression challenge, SMR decision |
| `numeric-input` | Medication math |
| `multi-step-sequencing` | Procedure sequencing (deferred) |
| `free-text` | Future types where production is the assessed skill |

The shell passes a `challenge_type` and `challenge_data` block from the scenario JSON to the appropriate plugin renderer. The plugin returns a rendered DOM subtree. The shell handles everything outside the content area.

ECG, med math, and capnography must all be built against this shell. Do not build any of the three as an independent modal.

### 8.6 Universal Non-Negotiables

- **Immersive mode compatibility**: challenge modals overlay the current tab, not a different one. Opening a challenge must not force a tab switch or cause the student to lose context.
- **Replay behavior**: on second and subsequent plays of a scenario, the challenge appears every time (consistent experience). The visited-node concept from the adventure map does not apply here — the challenge is the point, not a one-time novelty.
- **Partial credit design**: where applicable, declare `acceptable` answers that earn partial credit. Do not make every challenge binary pass/fail when the clinical reality is that some wrong answers are more wrong than others.
- **No time pressure**: challenge modals do not have countdown timers. The vitals engine continues, but the student is not penalized for reading carefully. Adding artificial time pressure to a modal interaction creates extraneous load without simulating a realistic field pressure.
- **Recognition-first is appropriate for acquisition; it is not sufficient for durable transfer.** The challenge catalog is structured-choice by design — recognition tasks are developmentally correct for this platform's primary use case (initial and mid-training). As a design policy: prefer structured selection wherever deterministic scoring is required. Reserve constructed response for tasks where production is the actual clinical skill (radio report phrasing, narrative documentation). Do not force selection format onto a task where the student's ability to *generate* the answer — not choose it — is what matters.

---

## 9. Ecological Validity — Explicit Scoping

### 9.1 What This Platform Trains
- Clinical decision-making: assessment sequencing, differential recognition, intervention selection
- Protocol knowledge: scope of practice, medication indications and contraindications, documentation standards
- Situational awareness: deterioration recognition, critical failure pattern identification
- Communication: DMIST radio report structure, CHART narrative completeness

### 9.2 What This Platform Does Not Train
- Psychomotor execution: IV placement, airway management, tourniquet application
- Spatial scene management: approach, positioning, extraction
- Physical team coordination: verbal handoffs under stress, role assignment
- Stress inoculation under sensory load: noise, bystanders, time pressure with physical task demands

### 9.3 Why This Matters
A student who believes this platform has fully trained them for field calls has developed a positive-transfer assumption that becomes a negative-transfer artifact when the psychomotor and environmental demands of a real call are encountered for the first time. The platform should explicitly frame itself in onboarding, in the instructor dashboard, and in any marketing materials as the *cognitive layer* of a complete blended training program — designed to sit alongside, not replace, skills labs and supervised field experience.

### 9.4 Recommended Companion Modalities

For instructors using RescueTrails as part of a structured program, the following companion modalities address the competency gaps in §9.2:

| Gap | Recommended companion |
|---|---|
| Psychomotor execution (BLS/ALS skills) | Skills lab with manikin and equipment |
| Airway management | High-fidelity airway manikin sessions |
| IV/IO access | Task trainer with supervised repetitions |
| Team coordination under stress | Simulation-based team scenario exercises |
| Stress inoculation | High-fidelity simulation with time pressure, noise, and bystander load |
| Field application | Supervised clinical precepting (ambulance ride-alongs, ALS shadow shifts) |

This table belongs in instructor onboarding materials and program integration guides. RescueTrails is the cognitive layer of a complete blended program. A student who progresses exclusively through this platform without complementary hands-on training has addressed cognition but not field competence.

---

## 10. Affective Domain — Professional Behavior Evaluation

### 10.1 Framework Foundation

RescueTrails professionalism scoring is grounded in the NASEMSO National Guidelines for Educating EMS Instructors (2002, Appendix V), which define eleven affective domain characteristics for evaluating EMS student professional behavior. This framework is the national consensus standard used by EMS educational programs for student professional behavior evaluation.

The canonical attribute-to-simulation mapping lives in [docs/PROFESSIONALISM_FRAMEWORK.md](PROFESSIONALISM_FRAMEWORK.md). That doc governs:
- which attributes are observable in simulation vs. measured elsewhere
- what specific behaviors count as evidence of each attribute
- how the LLM adjudicator should weight partial credit
- the relationship between single-session scoring and programmatic affective evaluation

### 10.2 Attribute Distribution Across Scoring Categories

The eleven NASEMSO attributes are distributed across scoring categories, not all assigned to the professionalism bucket:

| NASEMSO Attribute | Scoring Category |
|---|---|
| Empathy | Professionalism |
| Communications | Professionalism |
| Teamwork and Diplomacy | Professionalism |
| Respect | Professionalism |
| Patient Advocacy | Professionalism |
| Self-Confidence | Professionalism |
| Integrity (documentation accuracy) | Narrative / CHART |
| Self-Motivation (assessment initiative) | Clinical Performance |
| Time Management (sequencing) | Clinical Performance (implicitly) |
| Careful Delivery of Service (protocol) | Protocols/Treatment + Scope |
| Appearance and Personal Hygiene | Not scored — simulation limitation |

This distribution prevents double-counting. Careful Delivery of Service (following protocols, safe technique) is already the core of `protocols_treatment` and `scope_adherence`. Integrity in documentation is already evaluated in the narrative/CHART category. Scoring them again under professionalism inflates the category and dilutes its interpersonal signal.

### 10.3 Design Rules for Affective Evaluation

**Rule A — Patterns, not instances.**  
A single session is a data point, not a competency determination. The NASEMSO framework explicitly requires multiple independent evaluations across time before competency or non-competency conclusions. Session-level professionalism scores should feed a cumulative view for instructors, not serve as pass/fail gates on their own.

**Rule B — Specific behaviors, not general labels.**  
Rubric bands must describe observable behaviors ("addressed Jennifer by name before asking clinical questions") not attribute labels ("demonstrated empathy"). The LLM adjudicator cannot adjudicate labels — it needs behavioral anchors.

**Rule C — Scene-specific authoring.**  
The minimal failure text must be written to the actual professionalism risk the scenario presents. A panicked parent scene fails on empathy and communication silence. A subtle presentation scene fails on patient advocacy (dismissiveness). A high-acuity procedural scene fails on family preparation. Do not use generic minimal-credit language across scenarios.

**Rule D — Integrity and documentation are primarily a narrative concern.**  
Do not re-score documentation fabrication under professionalism. The narrative/CHART scoring category already penalizes fabricated findings. Professionalism should score the interpersonal human dimensions of the call, not double-penalize documentation quality.

**Rule E — Initial education programs need higher affective visibility.**  
For Initial Education mode users, the six-attribute professionalism breakdown should be surfaced to instructors in the performance dashboard, not just as a total. Cumulative patterns (consistently high empathy but low partner teamwork) are more instructionally valuable than a single 10-point session total. This is a future dashboard feature — not current implementation.

### 10.4 Relationship to Formal Program Evaluation

The Professional Behavior Evaluation instrument in the NASEMSO framework requires:
- Regular completion by faculty AND preceptors
- Multiple independent evaluations per student
- A defined program cut score
- Documentation of "not yet competent" ratings with specific behavioral examples

RescueTrails cannot replace this — it is not a faculty observation tool. What it can provide:
- Scenario-level professionalism performance data aggregated across multiple runs
- Identification of consistent attribute gaps (e.g., partner coordination weak across five sessions)
- Input data that instructors can weigh alongside clinical rotation and classroom observations

The Professional Behavior Counseling Record process — for documenting incidents and remediation of behavioral patterns — is a programmatic function entirely outside the simulator's scope.

---

## 11. Design Readiness Checklist

Before implementation planning begins for any learning feature, all five items below must be resolved. A feature that cannot answer all five is not ready for a sprint.

| # | Gate | Question to answer | Where to document the answer |
|---|---|---|---|
| 1 | Deterministic authority defined | What facts does this feature adjudicate, and how are they resolved without LLM judgment? | Feature subsystem doc or this doc |
| 2 | Trigger event defined | What specific backend event or milestone causes this feature to fire? Narrative descriptions are not acceptable — name the data signal. | `SCENARIO_ENGINE_ARCHITECTURE.md` for milestones; route handler for API triggers |
| 3 | Structured output / schema defined | If the feature involves AI output or a new data field, what is the exact schema? Are new DB columns or JSON fields required? | `SCENARIO_EVALUATION_ARCHITECTURE.md` for debrief output; relevant model file for DB schema |
| 4 | UI component strategy defined | Does this feature require a new component? If so, is it a shared component or a one-off? Document the decision before building. | This doc §8.4 for challenge shell; feature design doc otherwise |
| 5 | Implementation priority assigned | Where does this feature fall in the frozen implementation order (§12)? If it is not in the order, it is not scheduled. | `PUNCHLIST.md` implementation roadmap |

A feature that passes all five gates moves to planning. A feature that cannot pass gate 1 or 2 should not be designed further until the blocking decision is made — implementation will drift without a firm anchor.

---

## 12. Decisions Recorded

| Question | Decision | Date |
|---|---|---|
| Lexi persona — split adventure map mascot from in-scenario clinical partner voice | **Rejected.** Lexi's coherence as a unified character is intentional; the persona ambiguity is acceptable given the product's tone and audience. | 2026-04-28 |
| Pre-brief injection of prior notes/missed items before Random Call or replay | **Deferred.** Pending decision on whether Random Call scenarios are modified to create surface novelty (patient name, age, image changes). Pre-brief design depends on that framing. | 2026-04-28 |
| Random Call → spaced repetition selection algorithm | **Direction set** (§3). Implementation deferred. Algorithm is independent of the scenario variation decision. | 2026-04-28 |
| Primary impression — narrative modal free text vs. structured impression challenge | **Direction set** (§7.3). Three-component target: mid-scenario impression challenge (structured selection, deterministic scoring), DMIST modal impression field (replace placeholder), debrief three-way comparison. Components are independent and can be built incrementally. | 2026-04-29 |
| In-scenario challenge catalog — scope and priority | **Direction set** (§8). Priority order: ECG/rhythm strip, medication math, capnography interpretation, SMR decision, procedure sequencing (deferred — requires generic sequencing renderer). All follow the established lung sound challenge authoring contract. | 2026-04-28 |
| Rule 1 absolutism — "no mechanic should be purely cosmetic" | **Softened.** Rule 1 now targets structural mechanics (gating, earning, feedback sequencing) rather than all elements. Low-cost atmosphere and delight are acceptable when they support motivation without adding cognitive interference. | 2026-04-28 |
| Spaced repetition learning unit — whole scenario vs. subskills | **Clarified** (§3.4). Current constraint: whole-scenario score as scheduling unit. Target: per-rubric-item skill tags enabling subskill-weighted scheduling. Debrief rubric domain separation is the interim mitigation. | 2026-04-28 |
| Next Best Action routing — LLM-generated vs. deterministic | **Constrained** (§2.3). Routing *target* (which scenario/minigame) must come from deterministic backend signals. LLM generates phrasing only. Keeps recommendations auditable. | 2026-04-28 |
| Confidence calibration — coarseness of single pre-scenario rating | **Acknowledged** (§5.4). Single pre-scenario rating is minimum viable. Strengthen with post-case impression confidence and per-challenge confidence fields. Do not make instructor-facing calibration claims on coarse self-report alone. | 2026-04-28 |
| Debrief reflection prompts — operationalizing Rule 10 | **Added** (§2.4). 1–2 AI-generated run-specific reflection prompts in Layer 3 (collapsed detail). No written response required. Must vary by run data, not static templates. | 2026-04-28 |
| Impression challenge distractor quality | **Standard added** (§7.3 Component 1). Distractors must be plausible given presentation at trigger time, include at least one mechanism-overlapping option, and exclude anything obviously inconsistent with visible patient data. Periodic review required to prevent memorization. | 2026-04-28 |
| Challenge catalog — recognition vs. generation bias | **Framed** (§8.4). Recognition-first is correct for acquisition; insufficient for durable transfer if overused. Policy: structured selection where determinism is required; constructed response where generation is the actual clinical skill. | 2026-04-28 |
| Interleaving mitigation urgency | **Elevated** (§6.3). Random Call algorithm fix is highest-priority interleaving intervention, not a future concern. Blended Shift mode and cross-trail bonuses are medium-priority post-launch features. | 2026-04-28 |
| Ecological validity — companion modalities | **Added** (§9.4). Specific recommended companion modalities table for instructors integrating RescueTrails into a blended program. | 2026-04-28 |
| Next Action routing logic — decision table | **Defined** (§2.3). 5-priority ordered rule set: (1) highest-weight rubric category fail, (2) incorrect impression challenge, (3) overdue Random Call review, (4) oldest uncleared required scenario, (5) mini-game mapped to failed category. Tie-break by rubric weight. Mini-game rec only when exact category mapping declared. Fallback emits `none`. | 2026-04-28 |
| Shared challenge modal shell | **Decided** (§8.4). Single reusable shell with pluggable content renderers: single-choice, numeric-input, multi-step-sequencing, free-text. All challenges (ECG, med math, capnography, and all future types) must use the shell. Shell before second challenge — not as cleanup. | 2026-04-28 |
| primary_survey_complete milestone — definition | **Defined** (SCENARIO_ENGINE_ARCHITECTURE.md §3.4). Fires when all scenario-declared primary survey checklist items are satisfied per the scoring engine. Scenarios that declare no explicit primary survey items fall back to: any authoritative `explicit_assessment` SessionEvent recorded + at least one vital captured. Time-based heuristics not used. | 2026-04-28 |
| Debrief structured output contract | **Published** (SCENARIO_EVALUATION_ARCHITECTURE.md §8). New fields: `top_takeaways`, `reflection_prompts`, `next_action`, `next_action_target_type`, `next_action_target_id`, optional `reasoning_flags`. Backend populates routing fields before LLM call; AI receives them as hard inputs and generates phrasing only. | 2026-04-28 |
| Design readiness checklist | **Added** (§10). 5-gate checklist required before implementation planning for any learning feature. | 2026-04-28 |
| Implementation priority order | **Frozen** (PUNCHLIST.md §Implementation Roadmap). Phases 1–4 complete (2026-04-28): (1) Random Call SM-2, (2) DMIST primary impression field, (3) debrief BLUF restructure + Next Action routing, (4) shared challenge shell, (5) primary impression challenge. Remaining: (6) ECG/rhythm strip, (7) medication math, (8) capnography interpretation. See IMPLEMENTATION_PLAN.md for full task checklists. | 2026-04-28 |
