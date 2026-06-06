# CPR Challenge Design

**Status:** Phase 2 implementation in progress  
**Last Updated:** 2026-05-04  
**Scope:** Scenario-triggered CPR / high-performance CPR challenge for RescueTrails EMS scenarios, including adult, pediatric/infant, and later-phase neonatal resuscitation modes.

This document defines the planned CPR challenge that opens during cardiac-arrest scenarios when the learner initiates CPR. The challenge is intended to reinforce AHA-aligned high-quality CPR, code leadership, compression discipline, rhythm-check timing, and scenario-appropriate arrest management.

This remains the implementation contract. Phase 1 BLS/AED implementation is in
place with HUD trigger path, backend challenge attempt anchoring, deterministic
timeline scoring, post-ROSC vitals handoff, and evidence-packet bridging. Phase 2
pediatric mode is in progress with a pediatric BLS/AED scenario, ratio scoring,
and pediatric debrief facts. ALS/PALS/NRP extensions remain future phases unless
explicitly marked otherwise below.

---

## 1. Design Intent

The CPR challenge should train the learner to manage the choreography of a resuscitation, not physically perform compressions. The interface cannot measure real compression depth, recoil, hand placement, or ventilation volume, so it should not pretend to. Instead, the challenge should evaluate the cognitive and team-leadership behaviors that can be measured digitally:

- keeping compressions active
- minimizing pauses
- checking rhythm at appropriate intervals
- resuming CPR immediately after rhythm checks or shocks
- selecting the correct compression-to-ventilation strategy
- applying AED/monitor logic correctly
- timing medications appropriately when in scope and carried
- recognizing when advanced-airway placement changes ventilation/compression workflow
- maintaining a clear timestamped code log

The pedagogical focus is **high-performance CPR as code leadership**.

---

## 2. Guideline Anchors

The challenge should be built around the following AHA-aligned anchors:

| Domain | Design rule |
|---|---|
| Compression rate | Represent target rate as 100-120/min. The UI cannot measure real rate, so rate is a displayed coaching target, not an input unless a future metronome/tap mechanic is added. |
| Compression fraction | Use live Chest Compression Fraction (CCF) as the primary measurable HPCPR metric. Target >= 80%; >60-79% partial ramp; <=60% major gap. |
| Compression pauses | Rhythm/pulse checks should be <= 10 seconds. Pauses longer than 10 seconds trigger deductions and debrief coaching. |
| Rhythm checks | Default rhythm-check cadence is approximately every 2 minutes. |
| Adult ratio without advanced airway | 30:2. |
| Pediatric/infant ratio without advanced airway | Assume an EMS crew of 2 or more by default; use 15:2. 30:2 is only for explicitly authored single-rescuer teaching exceptions. |
| Adult advanced airway | Continuous compressions with ventilations about every 6 seconds. |
| Pediatric advanced airway | Continuous compressions with ventilations about every 2-3 seconds, avoiding hyperventilation. Teach this as 20-30/min with 30/min as the ceiling, not as "ventilate as fast as possible." |
| Defibrillation | Shock VF/pVT; do not shock PEA/asystole. Resume compressions immediately after shock/no-shock decision. |

**References:**

- AHA High-Quality CPR components: compression rate/depth, recoil, minimizing interruptions, avoiding excessive ventilation. See: https://cpr.heart.org/en/resuscitation-science/high-quality-cpr
- AHA pediatric BLS/PALS guidance: pediatric pauses under 10 seconds, rhythm checks about every 2 minutes, 30:2 or 15:2 without advanced airway, pediatric advanced-airway ventilation 20-30/min. See: https://cpr.heart.org/en/resuscitation-science/cpr-and-ecc-guidelines/pediatric-basic-life-support
- AHA adult BLS/ALS guidance: adult high-quality CPR and adult advanced-airway ventilation around 10/min. See: https://cpr.heart.org/en/resuscitation-science/cpr-and-ecc-guidelines/adult-basic-and-advanced-life-support
- AHA neonatal resuscitation guidance: ventilation-first newborn resuscitation, compressions when HR remains < 60/min despite effective ventilation, coordinated 3:1 compression-to-ventilation workflow, thermal management, oxygen titration, and escalation to epinephrine when indicated. See: https://cpr.heart.org/en/resuscitation-science/cpr-and-ecc-guidelines/neonatal-resuscitation

---

## 3. Non-Goals

The CPR challenge should not:

- simulate physical compression quality beyond what the app can measure
- let the LLM grade rhythm interpretation, medication timing, CCF, or pause duration
- require ALS-only interventions from BLS learners or agencies
- require medications/equipment not carried by the active agency
- turn every arrest into a full ACLS/PALS megacode if the scenario objective is BLS arrest care
- use frontend-only state as the authoritative scoring source
- replace the main scenario scoring engine; it should feed deterministic challenge results into the evidence packet
- mix free-text chat commands with timed HUD state transitions in V1

---

## 4. Trigger Conditions

The challenge opens only for scenarios that explicitly declare a CPR challenge block.

Abbreviated example. It is valid enough to show trigger configuration, but §10 is the full authoring contract and should be used for production scenarios.

```json
{
  "cpr_challenge": {
    "enabled": true,
    "challenge_id": "peds_arrest_01_cpr",
    "arrest_type": "pediatric",
    "algorithm": "pediatric_bls",
    "team_model": "ems_team",
    "initial_rhythm": "pulseless_vt",
    "rhythm_sequence": ["pulseless_vt", "vf", "pea"],
    "cycle_seconds": 120,
    "rosc_criteria": {
      "eligible_after_cycles": 3,
      "max_cycles_before_rosc": 5,
      "hard_stop_cycle": 5,
      "min_ccf": 0.80,
      "min_ccf_window": "consecutive_eligible_cycles",
      "aha_compliance_gates": [
        "ccf",
        "rhythm_decisions",
        "post_decision_resume",
        "ventilation_ratio",
        "no_critical_failure"
      ]
    },
    "allow_aed": true,
    "allow_manual_defib": false,
    "allow_precharge": false,
    "allow_advanced_airway": true,
    "allow_medications": true,
    "rubric_integration": {
      "dimension": "clinical_performance",
      "item_id": "cpr_challenge_management",
      "weight_points": 20
    }
  }
}
```

Trigger events:

- learner selects `CPR - Begin Compressions`
- learner types a clear CPR initiation command
- learner applies AED/defibrillator before CPR in a confirmed arrest scenario, in which case the challenge may open with a prompt to begin compressions
- patient transitions to pulseless state per authoritative scenario/vitals engine, in which case the challenge opens as a witnessed deterioration/arrest event

The trigger must be mediated by backend session state. The frontend may open the HUD for immediate interaction, but the resulting challenge timeline must be submitted and evaluated server-side.

### 4.1 Authoritative CPR Event Path

In CPR-challenge-enabled scenarios, the CPR challenge is the authoritative path for CPR arrest-management events.

The existing `cpr_initiate` intervention action ID remains valid for normal scenarios and for non-challenge documentation, but it must not create duplicate scoring credit in CPR-challenge-enabled scenarios.

Required implementation behavior:

- `Begin Compressions` opens/starts the CPR challenge.
- Backend records CPR start as part of the challenge event timeline.
- The evidence packet reads CPR initiation from the challenge result for CPR-enabled scenarios.
- If a normal `cpr_initiate` intervention row also exists, the evidence packet must deduplicate it and not award CPR-initiation credit twice.

Recommended backend rule: when `scenario.cpr_challenge.enabled === true`, `cpr_started` from the validated CPR challenge timeline supersedes standard `cpr_initiate` for arrest-management scoring.

If a standard `cpr_initiate` SessionEvent row is created before or during a CPR challenge, do not delete it. Preserve it for auditability, but mark it as non-scoring/superseded in deterministic consumers:

```json
{
  "superseded_by_challenge_attempt_id": "attempt_abc123",
  "scoring_status": "superseded"
}
```

Evidence packets, ePCR narrative generation, analytics, and debrief logic must prefer the validated CPR challenge `cpr_started` event when this marker is present. Raw audit views may still show the original user action.

### 4.2 Chat Lockout During the HUD

In V1, the CPR HUD should run as a full-screen or dominant modal state. Free-text chat input should be disabled while the HUD is active.

Reason: cardiac-arrest management is timing-sensitive. Allowing both NLP chat commands and HUD button commands to manipulate CPR state creates avoidable race conditions:

- student types "shock" while a rhythm-check modal is open
- chat response lags behind current compression state
- timer state and chat-driven actions disagree
- LLM output appears to perform an action the deterministic HUD did not record

V1 rule: **all code-management actions happen through HUD controls.** This lockout applies to the main chat, Lexi chat/debrief surfaces, partner free-text prompts, and any other AI-response surface that could answer "what rhythm is this?" or "should I shock?" during the assessment. Chat can resume after ROSC, termination, or explicit challenge exit.

The HUD may still display short partner prompts such as "Ready to analyze" or "Resume compressions," but those prompts are UI feedback, not LLM-controlled actions.

Frontend usability rule: if the HUD opens while the learner has unsent text in a chat input, cache that draft before disabling chat. Restore it when the learner returns to standard Immersive Mode so a sudden arrest transition does not erase a partially typed question or command.

### 4.2.1 Challenge Exit / Abandonment

If the learner exits the CPR HUD before ROSC or an authored termination endpoint, the challenge result should be marked `abandoned`.

V1 score treatment:

- CPR challenge component score = 0 for the CPR challenge.
- Scenario completion is not blocked.
- Evidence packet includes `timestamp_integrity: "abandoned"`, `outcome: "abandoned"`, and the partial timeline collected before exit.
- Debrief explains that leaving an active arrest is treated as abandonment, not an incomplete optional mini-game.

Do not exclude an abandoned CPR challenge from the denominator. A CPR-enabled arrest scenario declares arrest management as an expected objective.

### 4.3 AED Before CPR Ordering

The backend validator must accept `aed_applied` before `cpr_started`.

Reason: learners may correctly apply the AED/defibrillator immediately after recognizing arrest or may select AED from the action menu before pressing `Begin Compressions`. This should start the challenge context and prompt immediate compressions, not reject the timeline.

Valid ordering example:

```text
00:00 challenge_started
00:00 aed_applied
00:04 cpr_started
02:04 rhythm_check_started
```

CCF denominator still starts at `cpr_started`, not `aed_applied` or HUD open.

Code-log timestamps still start at `challenge_started`. In the example above, AED application appears at `00:00` and CPR begins at `00:04`; CCF/pause scoring begins at `00:04`.

The validator must also allow AED analysis/shock before `cpr_started` when the authored flow supports it.

Valid AED-first shock example:

```text
00:00 aed_applied
00:08 rhythm_identified
00:10 shock_delivered
00:12 cpr_started
```

This is valid timeline ordering, but the debrief should still coach immediate CPR after shock. CCF denominator starts at `cpr_started`; AED analysis time before compressions does not artificially lower CCF.

### 4.4 DOA / No-CPR Exclusions

Some scenarios should not launch the CPR HUD even if the learner selects CPR.

Use `cpr_challenge: { "enabled": false }` for obvious-death / no-resuscitation scenarios such as:

- dependent lividity
- rigor mortis
- decapitation or injuries incompatible with life
- valid DNR / POST / termination-of-resuscitation teaching cases where CPR is not indicated

If the learner attempts CPR in a DOA/no-CPR scenario, record it through the normal scenario evidence packet as a clinical error. Do not open the CPR challenge HUD.

---

## 5. Domain Boundaries

### Adult Arrest

Adult arrest mode supports:

- 30:2 before advanced airway
- continuous compressions after advanced airway
- ventilations about every 6 seconds after advanced airway
- AED or monitor/defibrillator pathway based on equipment and level
- medication timing when ALS scope/equipment allows in Phase 3

### Pediatric Arrest

Pediatric arrest mode supports:

- default EMS crew size is 2 or more
- 15:2 before advanced airway
- 30:2 only when a scenario explicitly authors a single-rescuer exception
- team-model transition from 30:2 to 15:2 only for explicit single-rescuer-to-crew teaching cases
- infant arrest using the pediatric BLS/PALS pathway unless the scenario is specifically a newborn/perinatal resuscitation scenario
- AED/defib with pediatric pads/attenuator when available
- continuous compressions after advanced airway
- ventilations about every 2-3 seconds after advanced airway
- stronger emphasis on oxygenation/ventilation because pediatric arrests are often respiratory or shock-driven

### Neonatal Resuscitation

Neonatal resuscitation should be included as a distinct later-phase mode, not as a small variation of the adult/pediatric CPR HUD.

Reason: newborn resuscitation is ventilation-first and uses different decision points than adult/pediatric cardiac arrest. The learner is managing transition physiology, thermoregulation, stimulation, airway positioning/suction only when indicated, PPV effectiveness, HR reassessment, oxygen titration, and escalation to compressions/epinephrine if HR remains < 60/min despite effective ventilation.

Neonatal mode supports:

- newborn/perinatal scenario context, separate from infant arrest after the newborn period
- warm/dry/stimulate/position sequence
- ventilation-first workflow with PPV effectiveness checks
- HR reassessment gates rather than routine 2-minute rhythm-check cycles
- 3:1 coordinated compressions/ventilations when indicated
- oxygen titration / pulse oximetry prompts when authored
- delayed cord/OB context when scenario-relevant
- epinephrine/volume escalation only when in scope, carried, and authored

Neonatal mode should use `algorithm: "neonatal_nrp"` and `arrest_type: "neonatal"`. It should not share CCF/rhythm-decision scoring buckets wholesale with adult/pediatric CPR. It should have its own ventilation effectiveness, HR reassessment, thermoregulation, and escalation scoring model.

Implementation phase: neonatal is not part of Phase 1 BLS AED. It should be planned as Phase 5 after the core adult/pediatric CPR manager is stable, unless the product roadmap prioritizes OB/newborn scenarios earlier.

### 5.1 Rhythm Sequence Determinism

`rhythm_sequence` is actor-independent in V1 by design.

The authored rhythm advances deterministically at rhythm-check/cycle boundaries. Learner decisions are scored as correct or incorrect, but they do not branch the authored rhythm sequence. ROSC is handled separately by deterministic performance-gated criteria.

Example:

```json
"rhythm_sequence": ["vf", "vf", "pea"]
```

If the learner incorrectly selects `No Shock` for VF in cycle 1, the action is scored as a rhythm-decision error. The sequence still advances to the next authored rhythm at the next cycle boundary. It does not create a separate "untreated VF persists forever" branch unless a future version explicitly implements branchable rhythm trees.

Reason: V1 prioritizes deterministic scoring, authoring simplicity, and auditable outcomes. Branching arrest physiology is deferred.

---

## 6. UX Layout: Code Commander HUD

When CPR is initiated, the scenario should shift into a focused Code Commander HUD. The learner needs rapid, structured controls rather than free-text typing. In V1, chat input is disabled while the HUD is active; after ROSC/exit, the learner returns to standard Immersive Mode for post-arrest care and documentation.

### 6.1 Top Bar: Clocks and CPR Status

Required elements:

- **Total Code Time:** counts up from CPR initiation.
- **Cycle Timer:** 2:00 countdown; warns at 0:10.
- **Compression Status:** `COMPRESSIONS ACTIVE` or `COMPRESSIONS PAUSED`.
- **Live CCF:** current chest compression fraction.
- **Current Mode:** `30:2`, `15:2`, `Continuous + ventilations (1 per 6 sec)`, or `Continuous + ventilations (1 per 2-3 sec)`.

Design behavior:

- CCF should update live.
- Paused state should be visually urgent.
- Cycle timer should not obscure the more important rule: resume compressions quickly.
- Continuous ventilation labels must be scenario-parameterized so adult advanced-airway mode and pediatric advanced-airway mode are visibly distinct.

### 6.2 Center / Left: Rhythm and Shock Panel

Required controls:

- monitor display
- `Pause for Rhythm Check`
- `Resume Compressions`
- `Shock`
- `No Shock / Resume CPR`
- optional `Pre-charge Monitor` for Phase 3 manual-defibrillator scenarios only

Behavior:

- Rhythm should be hidden or artifact-obscured while compressions are active unless `allow_continuous_rhythm_display: true` is explicitly authored.
- Pressing `Pause for Rhythm Check` starts a pause timer.
- `Shock` and `No Shock` decisions must be made during the rhythm-check window.
- After shock/no-shock, the UI should immediately emphasize `Resume Compressions`.

### 6.3 Right Panel: Interventions

Controls should be filtered by:

- scenario challenge configuration
- provider level
- agency equipment and medication inventory
- active MCA / protocol profile

Possible controls:

- CPR ratio selector
- AED apply/analyze
- ventilation mode command
- advanced airway placement
- waveform capnography
- epinephrine
- antiarrhythmic menu
- fluid bolus
- reversible causes checklist
- request ALS / request additional resources
- assign compressor / rotate compressor

V1 should keep interventions intentionally limited. Do not build a generic medication vending machine.

### 6.3.1 Ventilation Abstraction

Ventilations are **not** a repeated click task in V1.

The learner is acting as code leader. They should select the correct team/partner ventilation mode, then the simulated partner carries out that mode:

- `Partner: 30:2`
- `Partner: 15:2`
- `Partner: continuous compressions + ventilate every 6 sec`
- `Partner: continuous compressions + ventilate every 2-3 sec`

The challenge scores whether the learner selected the correct mode for:

- adult vs pediatric patient
- single-rescuer vs two-rescuer/team model
- advanced airway absent vs present
- agency/scope/equipment context

Do not require the learner to tap a "ventilate" button every cycle. That would add UI fatigue without measuring the target skill.

### 6.4 Bottom Panel: Code Log

The code log should be timestamped and visible during the challenge.

Time-zero anchor: the learner-facing code log is anchored to `challenge_started_at`, which corresponds to HUD open / challenge context start, not necessarily `cpr_started`.

Reason: AED-first flows are valid. If the learner applies the AED before starting compressions, the log must show that AED event without negative timestamps or misleading event order. CCF and pause scoring still use `cpr_started` as their denominator anchor; the code log uses the broader challenge timeline anchor for clinical documentation.

Contract: `challenge_started_at` is the only display anchor for code-log timestamps. Do not render a separate CPR-anchored log in AED-first flows. If a design needs "time since CPR started," display it as a separate CPR elapsed timer, not as the log timestamp.

Example:

```text
00:00 CPR challenge opened
00:00 AED applied
00:04 CPR initiated
02:04 Rhythm check started
02:10 VF identified
02:12 Shock delivered
02:13 CPR resumed
04:06 Rhythm check started
04:12 PEA identified
04:13 CPR resumed
04:19 Epinephrine given
```

The code log is not just cosmetic. It is the learner-facing view of the deterministic event timeline submitted for scoring.

After ROSC, the same log should support post-arrest handoff and documentation. At minimum, the evidence packet should preserve the key arrest timestamps so the debrief and CHART/ePCR narrative can reference:

- CPR start
- first AED/monitor application
- rhythm-check times
- shocks/no-shock decisions
- medication times, when applicable
- ROSC time

Roadmap note: a future post-arrest handoff panel should let the learner review these times before giving report. This should reuse the validated CPR timeline rather than asking the learner to reconstruct the code from memory.

---

## 7. Functional Mechanics

### 7.1 Compression State

The challenge has two primary compression states:

- `compressions_active`
- `compressions_paused`

State transitions drive CCF and pause scoring.

CCF formula:

```text
compression_active_seconds / total_challenge_seconds
```

Only challenge time after CPR initiation counts. Pre-CPR dispatch/assessment time belongs to the scenario, not the CPR challenge.

Authoritative denominator:

```text
total_challenge_seconds = last_scored_event_timestamp - cpr_started_timestamp
```

`last_scored_event_timestamp` is the backend-accepted endpoint for timing-sensitive CPR scoring:

| Outcome | `last_scored_event_timestamp` |
|---|---|
| `rosc` | timestamp of the accepted `rosc` event |
| `criteria_not_met` | timestamp of backend-derived `challenge_ended` at `hard_stop_cycle` |
| `terminated` | timestamp of accepted `termination_of_resuscitation` |
| `abandoned` | timestamp of learner exit / backend abandonment record |
| `incomplete_unverified` | not used; timing metrics are `null` |
| `rejected_invalid` | not used; timing metrics are `null` |

HUD-open time before `cpr_started` does not count against CCF. If a learner applies the AED first and then starts CPR, the pre-CPR AED time may be scored under "delayed CPR initiation" if the scenario declares that item, but it is not part of the CCF denominator.

Pause scoring also starts at `cpr_started`. Pre-CPR AED analysis, charging, shock, or setup time must not be included in the pause discipline bucket. If the scenario wants to penalize delayed CPR initiation, that is a separate parent-scenario or challenge flag, not a CCF/pause calculation artifact.

Medical control calls from the CPR HUD are score-neutral timing exclusions. When the learner opens Medical Control during active compressions, the HUD records `medical_control_auto_started`, optional `medical_control_auto_cycle`, and `medical_control_auto_ended` events while the displayed cycle counter continues advancing with no shocks. The backend removes that interval from CPR timing metrics, minimum-cycle gates, CCF, pause discipline, and cycle discipline. The raw events remain in the submitted timeline/code log for audit and debrief context. If the learner receives a medical-control response, the HUD records `medical_control_consulted`; that event is not timing-scored, but it can satisfy termination-of-resuscitation requirements.

Per-cycle CCF is required for ROSC eligibility when `min_ccf_window` uses cycle windows.

Cycle CCF formula:

```text
cycle_ccf = cycle_compression_active_seconds / cycle_scored_seconds
```

Cycle bounds:

- Cycle 1 starts at `cpr_started_timestamp`.
- Later cycles start when compressions resume after the prior shock/no-shock decision.
- A cycle ends at the next `rhythm_check_started`, `rosc`, `termination_of_resuscitation`, or backend-derived `challenge_ended`, whichever comes first.
- `cycle_scored_seconds` excludes pre-CPR AED time and any explicitly system-excluded interval such as backend-authored UI lockout time.

The scoring result should store both total-run CCF and `ccf_by_cycle`. Total-run CCF drives the 30-point CCF bucket unless a scenario explicitly chooses cycle-weighted CCF. `ccf_by_cycle` drives ROSC gate eligibility for `min_ccf_window: "consecutive_eligible_cycles"`.

### 7.2 Cycle Timer

The default cycle timer is 2 minutes.

Expected behavior:

- timer starts when CPR begins
- warning appears at 10 seconds remaining
- learner should prepare for rhythm check before the cycle ends
- rhythm check should be brief
- timer resets to `cycle_seconds` only when compressions resume after the shock/no-shock decision

The cycle timer should not automatically pause compressions. The learner must initiate the rhythm check.

Post-decision delay time does not belong to the next cycle timer. The next compression cycle starts at `compressions_resumed`, matching §7.1 cycle bounds and §7.5 post-shock CPR behavior.

If the timer reaches 0:00 and the learner has not initiated a rhythm check:

- timer holds at 0:00; it does not auto-restart
- visual urgency increases, e.g. flashing timer and `Check rhythm when ready`
- compressions continue to be treated as active until the learner pauses them
- a new cycle starts only after the learner completes the rhythm decision and resumes compressions

Cycle discipline scoring window:

| Rhythm-check timing from last cycle start | Score treatment |
|---|---|
| 1:45-2:15 | Full credit |
| 1:30-1:44 or 2:16-2:30 | Partial credit |
| < 1:30 or > 2:30 | No cycle-discipline credit for that cycle unless an authored exception applies |

Exceptions may be scenario-authored for AED prompts, unsafe scene interruption, or instructor-designed teaching cases. Early rhythm checks should not be penalized when the scenario declares a clinically justified reason, such as a visible authored rhythm change within the exception window. Do not infer this from frontend state or learner chat.

Do not author `sudden_rosc` as a V1 cycle-discipline exception. V1 ROSC is deterministic and boundary-based, so mid-cycle sudden ROSC is not a supported event. If a future phase adds mid-cycle ROSC, it must define a new exception type and scoring rule.

### 7.3 Rhythm Check

Rhythm check sequence:

1. Learner taps `Pause for Rhythm Check`.
2. Compressions pause and pause timer starts.
3. Monitor reveals current rhythm.
4. Learner chooses shock or no shock.
5. Learner resumes compressions.

Scoring should track:

- pause duration
- whether rhythm check happened at an appropriate cycle point
- whether shock/no-shock decision matched the rhythm
- time from shock/no-shock decision to resumed compressions

### 7.3.1 UI Grace and Pause Scoring

The challenge should acknowledge that digital interfaces add friction that is not present in a real resuscitation. A learner must visually parse the rhythm, move a cursor/finger, and tap a button. If pause scoring uses a hard 10.0-second cutoff with no tolerance, the app may punish UI handling instead of clinical decision-making.

Recommended scoring:

| Pause duration | Score treatment |
|---|---|
| <= 10 sec | Full credit |
| > 10 and <= 15 sec | Minor/UI-grace deduction or partial credit |
| > 15 sec | Meaningful deduction |
| > 20 sec | Severe pause flag |

The debrief should still teach the AHA target of keeping pauses under 10 seconds. The grace band exists to prevent the interface from becoming the real test.

The cycle timer may pause while the rhythm-decision UI is open, but CCF and pause duration must continue tracking until compressions resume. Do not hide actual off-chest time.

In-challenge feedback:

- pause > 10 sec: visual urgency state, e.g. timer turns amber/red and displays `Resume compressions`.
- pause > 20 sec: brief rule-based text prompt, e.g. `Compressions have been paused too long - resume now.`

This feedback is deterministic UI coaching, not LLM output.

### 7.4 Pre-Charge Mechanic

If a monitor/defibrillator is available, the challenge should support pre-charging in shockable rhythms.

Pre-charge is not implied by `allow_manual_defib`. It has its own authoring flag: `allow_precharge`.

Reasons:

- AEDs do not support pre-charge.
- Manual defibrillator pre-charge may be ALS/Paramedic-only depending on MCA and agency policy.
- Some scenarios may allow manual defib but intentionally withhold pre-charge to simplify the first teaching rep.

Phase note: pre-charge is **not** part of Phase 1 BLS AED scope. It belongs with Phase 3 manual-defibrillator / ALS-PALS extensions unless a later Phase 1 decision explicitly changes scope.

Phase 3 optional behavior:

- `Pre-charge Monitor` becomes available near end of the 2-minute cycle.
- If pre-charged, the shock workflow is near-instant: rhythm decision -> shock -> resume prompt, with no added charge delay.
- If not pre-charged, shock introduces a mandatory 5-8 second "charging..." lockout while compressions remain paused.

This reinforces choreography without requiring a complex monitor simulator.

### 7.5 Post-Shock CPR

After shock delivery, the learner should resume compressions immediately. Waiting to reassess the monitor should reduce CCF and trigger feedback.

The UI should not ask "Did it work?" after shock. It should ask, implicitly and visually: "Are compressions back on the chest?"

Cycle timer rule: after every shock delivery or no-shock decision, the next compression cycle starts fresh when compressions resume. The learner should receive a full `cycle_seconds` interval before the next routine rhythm-check prompt. Do not carry over the pre-shock timer remainder.

### 7.6 CPR Ratio and Advanced Airway

Before advanced airway:

- adult: 30:2
- pediatric/infant EMS crew: 15:2
- pediatric/infant single-rescuer exception: 30:2 only when explicitly authored

After advanced airway:

- continuous compressions
- adult ventilation target: about every 6 seconds
- pediatric ventilation target: about every 2-3 seconds

The challenge should prompt the learner to switch mode after advanced airway placement, but should not auto-credit the switch unless the learner selects/acknowledges it.

### 7.7 Reversible Causes

Use an H's and T's checklist as a cognitive aid, not a primary scoring engine in V1.

Recommended V1 behavior:

- Learner can open/check reversible causes.
- Scenario may mark one or two causes as relevant.
- Checking the relevant cause can produce bonus/partial credit only if the learner does not bulk-check the list.
- Missing it should not dominate CCF/rhythm/CPR scoring unless the scenario is specifically about that cause.

Scoring guardrail:

- full reversible-cause credit requires all authored relevant cause IDs
- learner may check no more than 2 non-relevant causes by default
- checking the entire list earns no reversible-cause credit

If this guardrail is not implemented, reversible causes should remain an unscored cognitive aid.

### 7.8 ROSC / Exit Flow

ROSC should be deterministic and performance-gated, not random and not merely a fixed authored cycle.

Default adult/pediatric ROSC rule:

- learner completes at least 3 CPR cycles
- ROSC becomes available between cycles 3 and 5
- CCF is at or above target, default `min_ccf: 0.80`
- rhythm/shock decisions comply with the authored AHA-aligned algorithm
- post-shock/no-shock CPR resumes within the defined timing threshold
- ventilation/ratio mode is appropriate for patient age, team model, and airway status
- no active critical-failure cap is present

ROSC eligibility uses `min_ccf_window: "consecutive_eligible_cycles"` by default. That means the learner must meet or exceed `min_ccf` for the required eligible cycle window, not merely improve during the last few seconds and not necessarily overcome a poor early cycle with total-run averaging. V1 default: target CCF must be sustained for the current eligible cycle and the immediately preceding cycle once `eligible_after_cycles` is reached.

`aha_compliance_gates` should be explicit. Do not use a vague boolean such as `require_aha_compliance`. V1 default gates:

- `ccf`
- `rhythm_decisions`
- `post_decision_resume`
- `ventilation_ratio`
- `no_critical_failure`

Gate pass criteria:

| Gate | Pass rule |
|---|---|
| `ccf` | Meets `min_ccf` over the configured `min_ccf_window`. V1 default: current eligible cycle plus immediately preceding cycle. |
| `rhythm_decisions` | No incorrect shock/no-shock decision during the current eligibility window. |
| `post_decision_resume` | Every scored post-shock/no-shock resume in the eligibility window is <= 10 sec; <= 5 sec is still required for full scoring credit. |
| `ventilation_ratio` | Correct adult/pediatric ratio or continuous-compression ventilation mode is active for the current patient/team/airway state. |
| `no_critical_failure` | No active critical-failure cap is present. |

Gate evaluation is pass/fail for ROSC eligibility, even when the related scoring bucket has partial credit. Partial credit can improve the challenge score, but it does not satisfy a ROSC gate unless the gate's pass rule is met.

If a scoring bucket is not applicable and removed from the denominator, the corresponding ROSC gate must also be removed from the effective gate list for that attempt. This prevents Phase 1/BLS configurations without ventilation mode selection UI from making ROSC impossible solely because `ventilation_ratio` appears in a template gate list.

The backend must compute and persist `gate_results` for the effective ROSC gate list. The debrief reads `gate_results`; it must not infer failed gates from prose or raw metrics.

Example:

```json
"gate_results": {
  "ccf": {"passed": true, "basis": "cycles_3_4", "values": [0.83, 0.86]},
  "rhythm_decisions": {"passed": true},
  "post_decision_resume": {"passed": false, "basis": "cycle_3_resume_12_sec"},
  "ventilation_ratio": {"passed": true},
  "no_critical_failure": {"passed": true}
}
```

Recommended V1 scoring-to-gate bridge:

- `ccf` passes only when the configured `min_ccf` window passes.
- `rhythm_decisions` passes only when no rhythm/shock severity cap is active in the eligibility window.
- `post_decision_resume` passes only when no scored resume in the eligibility window exceeds 10 seconds.
- `ventilation_ratio` passes only when all required ventilation/ratio states in the eligibility window score full credit.
- `no_critical_failure` passes only when the challenge has no active critical-failure flags.

If the learner maintains AHA-compliant management and target CCF for 3-5 cycles, the backend should trigger ROSC at the next eligible cycle boundary.

If `hard_stop_cycle == max_cycles_before_rosc` and ROSC criteria are not met by `max_cycles_before_rosc`, the challenge enters the V1 bounded no-ROSC outcome:

1. HUD locks arrest controls.
2. Banner displays `ROSC CRITERIA NOT MET`.
3. Code log records challenge end.
4. Evidence packet stores `rosc.achieved: false` and `basis: "criteria_not_met"`.
5. Learner proceeds to debrief with full timeline-based coaching.

`hard_stop_cycle` controls the absolute end of the challenge. V1 default: `hard_stop_cycle = max_cycles_before_rosc`.

If `hard_stop_cycle > max_cycles_before_rosc`, the HUD must **not** lock at `max_cycles_before_rosc`. The cycles between `max_cycles_before_rosc + 1` and `hard_stop_cycle` are an authored extended no-ROSC phase. That phase must define termination, transport, escalation, or continued-arrest coaching behavior. If no extended-phase behavior is authored, load-time validation should reject the scenario. The hard no-ROSC terminal outcome fires at `hard_stop_cycle`, not at `max_cycles_before_rosc`.

ALS adaptation: for ALS/PALS scenarios, ROSC criteria may include medication timing, manual defib/pre-charge, advanced airway, capnography, and reversible-cause management only when those interventions are in scope, carried by the agency, and enabled by the scenario. These ALS criteria must not be required for BLS learners, BLS agencies, or BLS scenarios with ALS auto-dispatch.

When deterministic ROSC criteria are met, the HUD should transition deliberately rather than disappearing.

Recommended ROSC sequence:

1. HUD locks CPR controls.
2. Prominent banner displays: `PULSE DETECTED - ROSC`.
3. Code log records ROSC timestamp.
4. HUD shows a short post-ROSC prompt: airway, oxygenation/ventilation, BP support, 12-lead when appropriate, transport/handoff.
5. Learner taps `Return to Patient Care`.
6. Standard Immersive Mode resumes for post-arrest care.

ROSC should not be probabilistic in V1. It should be determined by the authored `rosc_criteria` plus backend-scored CPR performance.

The post-ROSC prompt is informational in the CPR challenge. It should not create additional CPR challenge score deductions if the learner immediately taps `Return to Patient Care`. Any post-ROSC assessment/treatment requirements belong to the main scenario scoring engine after the learner returns to standard Immersive Mode.

Scenarios that begin as normal medical or trauma calls and then deteriorate into arrest must compose both scoring authorities. Keep the presenting call's primary base rubric (`nremt_e202_medical_v1` or `nremt_trauma_v1`) and add `nremt_cardiac_arrest_aed_v1` through `additional_patient_care_rubrics`. Combined medical/trauma calls that can deteriorate into arrest may include both the non-primary medical/trauma family and `nremt_cardiac_arrest_aed_v1` in `additional_patient_care_rubrics`. The CPR HUD evidence satisfies the secondary arrest rubric items for arrest recognition, CPR quality, AED operation, pulse-check discipline, and CPR resumption, while the original rubric continues to score the pre-arrest assessment, history, focused exam, and post-ROSC care. Do not replace the primary medical/trauma base with the arrest base for deterioration scenarios.

### 7.8.1 Vitals Engine Handoff

ROSC is a cross-system state transition. The CPR challenge must not announce ROSC while the parent scenario/vitals engine continues showing arrest physiology.

Required behavior:

- Backend emits an authoritative `cpr_rosc` / `cpr_challenge_ended` result with timestamp, ROSC status, and challenge attempt ID.
- Parent scenario state consumes that result before returning to Immersive Mode.
- On ROSC, the vitals engine transitions to a scenario-authored `post_rosc` physiology profile, e.g. recovering HR, weak/returning pulse, improving SpO2, and BP support needs.
- On no-ROSC hard stop, the default path is immediate transition to the feedback/debrief flow with `outcome: "criteria_not_met"`. If the scenario authors a termination/transport branch, use that branch instead. Do not return to routine patient-care mode with contradictory arrest vitals unless the scenario explicitly authors continued arrest care.
- The evidence packet stores both the CPR result and the resulting vitals transition so the debrief can explain the handoff.

Phase 1 deliverable: implement the ROSC-to-vitals handoff for the first BLS AED scenario. Do not defer this to analytics or Phase 4.

---

## 8. Event Timeline Contract

The frontend challenge records a local HUD timeline, then submits it to the backend. The backend evaluates the timeline and writes authoritative `SessionEvent` rows for accepted CPR events. The CPR challenge should not create a siloed alternate event store.

### 8.0 Timestamp Trust Model

Frontend timestamps are not authoritative for scoring by themselves.

The frontend may record relative event times for responsive HUD behavior, but CCF, pause duration, cycle timing, and rhythm-check timing affect score. A submitted timeline that merely has plausible ordering is not enough; it could be fabricated or distorted by client clock manipulation.

Required server-side anchors:

- backend records `challenge_started_at_server` when the CPR HUD/session is authorized
- backend records `challenge_ended_at_server` when the challenge is submitted or abandoned
- frontend submits monotonic relative timestamps only; backend maps them into the server-anchored challenge window
- backend rejects timelines whose final timestamp materially exceeds the server-observed wall-clock duration plus a small network/UI tolerance; this is `rejected_invalid`, not `incomplete_unverified`
- backend rejects negative timestamps, non-monotonic timestamps, impossible compression/pause overlap, or event gaps inconsistent with the heartbeat/keepalive record

Recommended V1 integrity pattern:

- client sends periodic CPR HUD heartbeat/keepalive events while active, e.g. every 10-15 seconds
- backend stores last heartbeat time for the active challenge
- submitted timeline must fit within `challenge_started_at_server` and the last heartbeat/submission window
- allow a heartbeat grace window before invalidating timing integrity; recommended V1 grace is up to 45 seconds without heartbeat, as long as final submission wall-clock duration still matches the server-observed challenge window
- if heartbeat gaps exceed the grace window because the browser crashed or the network dropped, mark the challenge `incomplete_unverified` rather than accepting precise CCF/pause scoring from client-only timestamps

Outcome distinction:

- `rejected_invalid`: impossible or fabricated timeline, including material server-window mismatch, non-monotonic timestamps, impossible overlaps, or unauthorized events.
- `incomplete_unverified`: plausible partial timeline, but server heartbeat/anchor evidence is incomplete enough that precise timing cannot be scored authoritatively.

`incomplete_unverified` is not the same as learner abandonment. It means the system cannot confidently score timing-sensitive metrics because the server anchor/heartbeat record is incomplete. V1 behavior should surface a clear diagnostic, preserve the partial timeline for review, and avoid presenting precise CCF/pause scores as authoritative.

This does not need to become anti-cheat theater. The goal is ordinary scoring integrity: backend scoring may use frontend event order and relative timing only when constrained by server-observed wall-clock anchors.

Recommended integration:

1. Frontend records a local timeline for responsive HUD behavior.
2. Frontend submits the timeline to the backend challenge endpoint.
3. Backend validates ordering, timestamps against the server-side anchor/heartbeat window, scope/equipment context, and allowed event types.
4. Backend writes normalized `SessionEvent` rows with `source="backend_auto"`.
5. Evidence packet reads the normalized SessionEvents, not arbitrary frontend state.

This preserves the existing event architecture and keeps `_build_evidence_packet()` from needing a one-off parser that bypasses session authority.

Example:

```json
{
  "challenge_type": "cpr_manager",
  "challenge_id": "peds_arrest_01_cpr",
  "started_at_ms": 0,
  "ended_at_ms": 390000,
  "events": [
    {"t_ms": 0, "type": "cpr_started"},
    {"t_ms": 1000, "type": "ventilation_mode_set", "mode": "15:2"},
    {"t_ms": 12000, "type": "aed_applied"},
    {"t_ms": 120000, "type": "compressions_paused", "reason": "rhythm_check"},
    {"t_ms": 120000, "type": "rhythm_check_started"},
    {"t_ms": 123000, "type": "rhythm_identified", "rhythm": "vf"},
    {"t_ms": 127000, "type": "shock_delivered", "dose_category": "pediatric_initial"},
    {"t_ms": 129000, "type": "compressions_resumed", "reason": "post_shock"},
    {"t_ms": 255000, "type": "medication_given", "medication_id": "epinephrine_cardiac"},
    {"t_ms": 390000, "type": "rosc"},
    {"t_ms": 390000, "type": "challenge_ended", "outcome": "rosc"}
  ]
}
```

AED-first partial ordering example:

```json
{
  "challenge_type": "cpr_manager",
  "challenge_id": "adult_arrest_01_cpr",
  "started_at_ms": 0,
  "ended_at_ms": 245000,
  "events": [
    {"t_ms": 0, "type": "aed_applied"},
    {"t_ms": 8000, "type": "rhythm_identified", "rhythm": "vf"},
    {"t_ms": 10000, "type": "shock_delivered", "dose_category": "adult_default"},
    {"t_ms": 12000, "type": "cpr_started"},
    {"t_ms": 132000, "type": "compressions_paused", "reason": "rhythm_check"},
    {"t_ms": 132000, "type": "rhythm_check_started"}
  ]
}
```

Supported event types:

This list means the validator must know how to process these event types. It does **not** mean every valid submission must contain each event at least once. Required presence depends on outcome and authored flow.

- `cpr_started`
- `compressions_paused`
- `compressions_resumed`
- `rhythm_check_started`
- `rhythm_identified`
- `shock_delivered`
- `no_shock_selected`
- `challenge_ended`

Optional event types:

- `aed_applied`
- `monitor_applied`
- `precharge_started`
- `advanced_airway_placed`
- `ventilation_mode_set`
- `ventilation_mode_changed`
- `pulse_check_started`
- `pulse_check_completed`
- `team_model_changed`
- `medication_given`
- `reversible_cause_checked`
- `rosc`
- `termination_of_resuscitation`
- `als_requested`

Backend scoring must ignore unknown event types or reject them with a clear validation error. Do not silently treat unknown event types as scored facts.

`challenge_ended` definition:

- The frontend may include `challenge_ended` when the HUD reaches a terminal learner-visible state, e.g. ROSC banner accepted, criteria-not-met hard stop, valid termination, or explicit exit.
- The backend is authoritative for `challenge_ended_at_server`; client `challenge_ended.t_ms` is advisory and must fit within the server anchor window.
- `challenge_ended` is distinct from `rosc`. `rosc` records clinical return of spontaneous circulation; `challenge_ended` records the end of the CPR HUD attempt.
- For abandonment, the backend may create the terminal `challenge_ended`/abandonment record even if the frontend does not submit one.
- Payload should include `outcome`: `rosc`, `criteria_not_met`, `abandoned`, `terminated`, `incomplete_unverified`, or `rejected_invalid`.

Minimum event presence by outcome:

| Outcome | Minimum accepted events |
|---|---|
| `rosc` | `cpr_started`, at least one completed rhythm decision cycle unless AED-first shock ROSC is explicitly authored, `rosc`, `challenge_ended` |
| `criteria_not_met` | `cpr_started`, `challenge_ended` |
| `abandoned` | any accepted partial timeline plus backend abandonment record |
| `terminated` | `cpr_started`, accepted `termination_of_resuscitation`, `challenge_ended` |
| `incomplete_unverified` | partial timeline may be incomplete; timing metrics are null |
| `rejected_invalid` | no minimum accepted clinical events; submission failed validation |

Validator ordering rule: AED-first flows may emit `aed_applied`, `rhythm_identified`, and `shock_delivered` before `cpr_started` when the authored scenario allows AED-first analysis. Required event validation must not assume every required event occurs after `cpr_started`.

Rhythm-check ordering rule:

- `compressions_paused` with `reason: "rhythm_check"` must precede or share the same timestamp as `rhythm_check_started`.
- `rhythm_check_started` without a corresponding rhythm-check pause is invalid unless the scenario explicitly authors continuous rhythm display and no compression pause.
- `compressions_paused` and `rhythm_check_started` are not equivalent. The first records the compression state transition; the second records the start of the rhythm-decision workflow.

AED-first rhythm decision scoring:

- Pre-CPR rhythm decisions are included in `scored_decisions` when they occur inside an authored AED-first flow.
- Correct pre-CPR shock/no-shock decisions earn rhythm/shock credit.
- Incorrect pre-CPR decisions trigger the same rhythm/shock severity caps as later decisions.
- Pre-CPR rhythm decisions do not affect CCF or pause discipline denominators unless the scenario separately scores delayed CPR initiation.

Pulse-check hold interaction:

- When the CPR HUD exposes a pulse-check control before CPR initiation or during a rhythm-check pause, it must be a press-and-hold action.
- Initial pulse check should be visually first in the HUD sequence. After the initial pulse check, starting compressions and applying the AED may occur in either order because real two-rescuer care performs these tasks in parallel.
- The pulse-check control should remain visible and available from challenge start. If the learner already checked pulse in the scenario before opening the CPR HUD, skipping the initial HUD pulse check should not create a Phase 1 scoring penalty.
- The CPR HUD must not auto-start compressions on open and must not pre-highlight a default compression ratio. The learner starts CPR by selecting a compression mode/ratio button; only the active compression mode should be highlighted.
- Compression/ventilation ratio buttons should remain broadly available (`3:1`, `15:2`, `30:2`, `CONT`). `CONT` is the compact HUD label for the underlying `Continuous` mode. The learner is expected to know which ratio fits the patient age, team model, and airway state. The scorer/debrief may evaluate the selected ratio when that bucket is enabled.
- The pause control should remain visible and available. When compressions are paused, the pause state should be visually highlighted so the learner can distinguish `30:2 active` from `paused` at a glance.
- AED power-on/pad attachment should show a clear prompt sequence: `Press Power Button`, `Applying Pads`, `Analyzing. Stop Motion`, then either `Shock Advised. Push Shock Button` or `No Shock Advised. Start CPR`.
- Phase 1 should delay analysis for approximately 10 seconds after AED power-on/pad application. When pads are applied, the AED enters the analyzing state and prompts stop motion.
- The cycle timer is learner-facing elapsed AED/CPR cycle time and should count up, not down. It starts when CPR begins after a shock/no-shock decision, does not reset for early manual pauses, and ends/freezes when AED analysis begins.
- Phase 1 AED analysis should hold the analyzing state for approximately 7 seconds without displaying a countdown. The learner should use this pause to perform the 5-10 second pulse check.
- AED prompts should mimic AED voice prompts without inventing manual-defib behavior. Phase 1 AED text should use states such as "Shock advised. Push shock button" or "No shock advised. Start CPR"; it should not display "charging" language. The shock button should visually flash only while shock is advised.
- AED state should not block compressions except during the active analyzing window. If shock is advised and the learner restarts compressions before pressing shock, the HUD should continue flashing the shock button and showing the shock-advised prompt while allowing compressions to run.
- Provide an `End Code` control for stopping resuscitation. When a terminal no-shock rhythm check produces a valid pulse-present finding, relabel this control as `ROSC / End Code`; clicking it submits the terminal ROSC attempt instead of forcing CPR to restart. If ROSC is not present, the HUD must require medical-control consultation before termination unless a scenario-authored DNR/POST/withholding context has been documented.
- After shock delivery, the learner should restart CPR immediately by pressing a compression mode button; do not require a post-shock pulse check. For a no-shock AED decision, the HUD may require/check for a pulse before restarting CPR when the scenario remains pulseless.
- When a valid pulse check finds no pulse, the pulse-check button should switch to a red/no-pulse state rather than a green/success state.
- The CPR panel should not duplicate compression state above and below the mode buttons. Keep one clear state indicator and use the lower text line for hints, nudges, and reminders.
- A valid pulse check is 5-10 seconds.
- Releasing before 5 seconds records no completed pulse check and prompts the learner to try again.
- At 5+ seconds, the HUD should display the pulse finding (for Phase 1 adult arrest: no central pulse before ROSC).
- Holding past 10 seconds does not auto-complete or restart compressions. It continues timing, displays a "too long" warning, and records the final duration/status when the learner releases.
- After releasing a valid or long pulse check with no pulse, the learner must explicitly restart CPR by pressing one of the compression-mode buttons. If the terminal no-shock pulse check finds a pulse, the learner should not restart CPR; they should click `ROSC / End Code`.
- `pulse_check_started` and `pulse_check_completed` are timeline facts for debrief/UI audit. Rhythm-analysis pulse checks may satisfy the NREMT cardiac-arrest pulse-check item. Initial pulse checks before CPR initiation are arrest-confirmation evidence only; a long or duplicated initial check must not penalize rhythm-analysis pulse-check discipline.
- If the learner already documented pulselessness in the parent scenario before opening the HUD, the frontend may submit `pre_challenge_pulse_check_confirmed` at HUD start. This satisfies initial pulse-confirmation audit context but does not replace required rhythm-analysis pulse checks.
- `pulse_check_completed.data.phase` should distinguish `initial` from `rhythm_check`.
- `pulse_check_completed.data.status` should be `too_short`, `valid`, or `too_long`, with `valid: true` only for 5-10 seconds.
- If the learner attempts to restart compressions before AED analysis is complete, before delivering an advised shock, or before completing the required pulse check, record `premature_compressions_attempted` with the current cycle and reason. These events are debrief/scoring hooks for later versions.
- Pulse-check events must occur before CPR initiation or while compressions are paused for a rhythm-check workflow; they are invalid during active compressions.

`compressions_paused` must carry a reason so pause scoring does not infer context from fragile event adjacency:

```json
{"t_ms": 120000, "type": "compressions_paused", "reason": "rhythm_check"}
```

Allowed `compressions_paused.reason` values:

- `rhythm_check`
- `equipment_application`
- `team_transition`
- `manual_pause`
- `authored_interruption`

`compressions_resumed` must carry a reason so scoring does not infer context from fragile event adjacency:

```json
{"t_ms": 129000, "type": "compressions_resumed", "reason": "post_shock"}
```

Allowed `compressions_resumed.reason` values:

- `post_shock`
- `post_no_shock`
- `manual_resume`

Do not use `rhythm_check` as a `compressions_resumed.reason`. In adult/pediatric CPR, a rhythm check should resolve through a shock or no-shock decision before compressions resume. If the learner resumes without making a decision, record `manual_resume`, flag `rhythm_check_aborted_without_decision`, and score it as a rhythm-decision/protocol error when applicable.

`ventilation_mode_set` records the learner's initial ventilation/ratio command. `ventilation_mode_changed` records later transitions.

If the ventilation/ratio bucket is applicable, the timeline must include either:

- `ventilation_mode_set` at or after `cpr_started`, or
- a scenario-authored default that explicitly gives no learner-selection credit.

Do not silently infer full ventilation/ratio credit from the algorithm default. If the UI asks the learner to manage ventilation strategy, the learner's initial selection must be represented in the challenge timeline.

`rhythm_identified` should use the current rhythm from `rhythm_sequence`. If the authored `rhythm_sequence` is exhausted before ROSC/no-ROSC endpoint, the backend uses `default_ongoing_rhythm` if provided; otherwise it repeats the last rhythm in `rhythm_sequence`. Load-time validation should reject an empty rhythm sequence for adult/pediatric CPR modes.

`cycle_completed` should not be accepted as a required frontend-submitted timing fact. Cycle completion is a backend-derived fact produced when the meaningful sequence is complete:

```text
rhythm_check_started -> rhythm_identified -> shock/no-shock decision -> compressions_resumed
```

Timer expiry at 0:00 is not a completed cycle. It is only an overdue-cycle UI state.

### 8.1 Timestamp Integrity Enum

`timestamp_integrity` should be a documented enum:

| Value | Meaning | Score behavior |
|---|---|---|
| `server_anchored` | Timeline fits within server start/end and heartbeat bounds. | Timing-sensitive metrics may be scored. |
| `incomplete_unverified` | Server anchor/heartbeat record is incomplete or inconsistent. | Preserve partial timeline; do not present precise CCF/pause score as authoritative. |
| `abandoned` | Learner exited before ROSC/termination endpoint. | CPR component score = 0; preserve partial timeline. |
| `rejected_invalid` | Timeline is structurally invalid or appears fabricated: non-monotonic timestamps, impossible overlaps, invalid ordering, or impossible server-window mismatch. | Score is null; do not write scored CPR facts; surface diagnostic. |

`incomplete_unverified` result object behavior:

- `score`: `null`
- `max_score`: `null`
- timing-sensitive metrics (`ccf`, `average_pause_sec`, `longest_pause_sec`, `post_shock_resume_sec_avg`) are set to `null`
- non-timing facts that can still be trusted from accepted event order may be included with `verified: false`
- `flags` must include `timestamp_integrity_unverified`

Do not convert `incomplete_unverified` into a zero. It is a system integrity state, not proof of learner failure.

Parent rubric behavior for `incomplete_unverified`:

- CPR sub-component score is `null`, not 0.
- Parent scenario score should be marked `score_status: "incomplete_unverified"` and should not be presented as an authoritative final score.
- Learner-facing UI should offer retry/replay or explain that timing integrity was lost.
- If the platform must display a session row, show "Needs review" or "Unverified" rather than folding null CPR credit into the numeric total.

`rejected_invalid` result object behavior:

- `score`: `null`
- `max_score`: `null`
- all timing and decision metrics are `null`
- evidence packet includes `timestamp_integrity: "rejected_invalid"` and a non-PII diagnostic reason
- debrief should say the CPR challenge could not be scored due to invalid timing/event data, not that the learner clinically failed

### 8.2 SessionEvent Projection

Accepted CPR events should be projected into standard SessionEvent records.

Example projection:

```json
{
  "event_type": "challenge_completed",
  "event_key": "cpr_manager",
  "source": "backend_auto",
  "event_data": {
    "challenge_id": "peds_arrest_01_cpr",
    "score": 82,
    "ccf": 0.84,
    "average_pause_sec": 8.2,
    "longest_pause_sec": 13.4,
    "events": [
      {"t_ms": 0, "type": "cpr_started"},
      {"t_ms": 120000, "type": "rhythm_check_started"},
      {"t_ms": 127000, "type": "shock_delivered"}
    ]
  }
}
```

If the existing `challenge_completed` event path is used, only the backend challenge endpoint may write it. The generic client event endpoint must not be allowed to forge CPR challenge results.

### 8.2.1 Challenge Submission Authorization

The CPR challenge submission endpoint must enforce session-scoped authorization before validating or writing any result.

Required checks:

- Authenticated user must own the session or be authorized for that session through agency/instructor role.
- Session must be in an active CPR challenge state or accepting a terminal retry for the same active `challenge_attempt_id`.
- Submitted `challenge_id` must match the CPR challenge configured on the active scenario for that session.
- Submitted `challenge_attempt_id` must match the backend-issued active attempt ID.
- Duplicate submissions for the same `challenge_attempt_id` must be idempotent: return the existing accepted result if payload hash matches; reject conflicting payloads.
- Tenant/agency context must be derived from the session, not from client-submitted agency fields.
- Generic `/events` endpoints must reject forged CPR `challenge_completed` / `cpr_challenge_ended` writes.

These checks are part of the deterministic scoring boundary. The frontend may manage a local HUD, but it cannot authorize its own CPR result.

### 8.3 Replay / Attempt Semantics

Each CPR challenge attempt must be stored as its own attempt record or distinct `challenge_completed` event payload.

Rules:

- Do not overwrite prior CPR challenge attempts.
- Each attempt gets a stable `challenge_attempt_id`.
- Recommended `challenge_attempt_id` derivation: `{session_id}:{scenario_id}:{challenge_id}:{attempt_sequence}` or an opaque database UUID with those fields stored separately.
- Do not derive tenant identity from `challenge_id`. Tenant/agency separation comes from session ownership and backend authorization.
- The active scenario debrief uses the latest completed attempt for that session unless the user opens attempt history.
- Scenario replay creates a new session and therefore a new CPR challenge attempt history entry.
- Instructor/analytics views may compare attempts over time, e.g. previous CCF vs current CCF.
- Leaderboards/rewards must explicitly choose their aggregation rule (`latest`, `best`, or `first_clear`) rather than relying on whichever attempt was written last.

Completed attempt definition:

| Outcome | Completed attempt? | Active debrief selection |
|---|---|---|
| `rosc` | yes | eligible as latest completed attempt |
| `criteria_not_met` | yes | eligible as latest completed attempt |
| `terminated` | yes | eligible as latest completed attempt when termination was valid |
| `abandoned` | yes, failed | eligible as latest completed attempt and maps CPR sub-component to 0 |
| `incomplete_unverified` | no authoritative scored attempt | show diagnostic; do not replace latest scored attempt unless this is the only attempt |
| `rejected_invalid` | no | show diagnostic; do not replace latest scored attempt |

"Latest completed attempt" means the latest attempt with a terminal learner outcome, including abandonment. Integrity-failure states are preserved for audit but should not silently overwrite the debrief's latest authoritative scored CPR result.

---

## 9. Deterministic Scoring

The CPR challenge should produce a deterministic result object.

Example:

```json
{
  "challenge_type": "cpr_manager",
  "score": 82,
  "max_score": 100,
  "metrics": {
    "ccf": 0.84,
    "average_pause_sec": 8.2,
    "longest_pause_sec": 13.4,
    "rhythm_decision_accuracy": 1.0,
    "post_shock_resume_sec_avg": 2.1,
    "medication_timing": {"status": "not_applicable"},
    "timestamp_integrity": "server_anchored"
  },
  "flags": [
    "one_pause_over_10_sec"
  ]
}
```

### 9.1 Suggested Point Model

| Metric | Points | Notes |
|---|---:|---|
| Chest Compression Fraction | 30 | Full >= 80%; partial ramp above 60% through 79%; zero <= 60%. |
| Pause discipline | 20 | Full <= 10 sec; partial grace through 15 sec; severe flags above 20 sec. |
| Rhythm/shock decisions | 20 | Shock VF/pVT; no shock PEA/asystole. Score per rhythm decision with critical-error caps below. |
| Cycle discipline | 10 | Rhythm checks around 2-minute cycles; no unnecessary early/late checks. |
| Post-shock/no-shock resume | 10 | Resume compressions immediately. |
| Ventilation/ratio management | 5 | Correct ratio/mode for adult/peds/advanced airway. |
| Medication timing | 5 | Only when medications are in scope and carried. Otherwise not applicable. |

The denominator should shrink when a metric is not applicable. Example: BLS AED-only arrest should not lose medication-timing points.

Denominator rule:

```text
raw_points_earned = sum(points earned for applicable metrics)
raw_points_possible = sum(max points for applicable metrics)
normalized_score = round((raw_points_earned / raw_points_possible) * 100)
```

Example: if medication timing is not applicable, the available denominator becomes 95. If the learner earns 76 of those 95 applicable points, the stored challenge score is `round(76 / 95 * 100) = 80`.

Do not leave the max score at 100 while simply omitting N/A points. That would punish learners for non-applicable metrics and make BLS AED-only arrests look artificially worse than ALS arrests.

CCF bucket formula:

```text
if ccf >= 0.80: ccf_points = 30
elif ccf >= 0.60: ccf_points = round(((ccf - 0.60) / 0.20) * 30)
else: ccf_points = 0
```

Examples:

- `0.80` -> 30/30
- `0.70` -> 15/30
- `0.60` -> 0/30

The ramp intentionally starts above 60%. Exactly 60% is the floor of the ramp and earns 0/30, while values above 60% earn increasing partial credit.

Pause discipline bucket:

```text
pause_points = 20
for each scored pause where pause_start >= cpr_started_timestamp:
  pause_sec = scored_pause_end_timestamp - pause_start
  if pause_sec <= 10: no deduction
  elif pause_sec <= 15: deduct 2
  elif pause_sec <= 20: deduct 5
  else: deduct 8 and add severe_pause flag
pause_points = max(0, pause_points)
```

Scored pause rule: rhythm-check pauses count in the pause discipline bucket. Post-shock/no-shock delay intervals are scored in the post-decision resume bucket, not again as independent pause-discipline deductions. This prevents a single post-shock delay from being triple-counted through pause discipline, resume timing, and critical-failure caps.

`scored_pause_end_timestamp` rules:

- `compressions_paused.reason == "rhythm_check"`: end at the first subsequent `shock_delivered` or `no_shock_selected` decision timestamp. The post-decision interval belongs to the resume bucket.
- Aborted rhythm check: if the learner resumes without a shock/no-shock decision, end at `compressions_resumed`, add `rhythm_check_aborted_without_decision`, and score the missing decision through rhythm/protocol error handling.
- `compressions_paused.reason == "equipment_application"`: end at `compressions_resumed`, minus any backend-labeled `system_lockout_seconds`.
- `compressions_paused.reason == "team_transition"`: end at `compressions_resumed`, unless the scenario marks the transition as an authored non-scored interruption.
- `compressions_paused.reason == "manual_pause"`: end at `compressions_resumed`.
- `compressions_paused.reason == "authored_interruption"`: score according to the authored interruption rule; default is not scored.

If no valid end event exists before abandonment or invalid submission, the scoring service should not fabricate a pause duration. Use the terminal outcome rules instead.

Phase 3 charging lockout rule:

- Mandatory monitor/defibrillator charging time is system-imposed time, not learner-delay time.
- CCF should still reflect real off-chest time unless a future clinical decision explicitly excludes it, because the patient is not receiving compressions.
- Pause discipline and post-decision resume scoring should subtract or separately label `system_lockout_seconds` so the learner is not penalized for a mandatory UI/device delay.
- Debrief may still explain that pre-charge improves CCF by preventing avoidable charging pauses when pre-charge is in scope and available.

Post-shock/no-shock resume bucket:

| Resume time after shock/no-shock decision | Score treatment |
|---|---|
| <= 5 sec | Full credit |
| > 5 and <= 10 sec | Partial credit |
| > 10 sec | No credit for that resume event and add delayed_resume flag |

Bucket formula:

```text
resume_weight(event):
  if assistive_interaction_mode and event.resume_sec <= 10: return 1.0
  if event.resume_sec <= 5: return 1.0
  if event.resume_sec <= 10: return 0.5
  return 0.0

post_decision_resume_points =
  round((sum(resume_weight(event)) / scored_resume_events) * 10)
```

Only resume events after `cpr_started` with `compressions_resumed.reason` in `{post_shock, post_no_shock}` are scored in this bucket.

`scored_resume_events` definition:

```text
scored_resume_events =
  count(compressions_resumed where reason in {"post_shock", "post_no_shock"})
```

`manual_resume` events are not included in this denominator. They are scored through the error/flag that created the manual resume, e.g. `rhythm_check_aborted_without_decision`.

If `scored_resume_events == 0`, the bucket is not applicable and is removed from the denominator.

`assistive_interaction_mode` source:

- Boolean session/user accessibility setting resolved server-side at challenge start.
- It may come from the learner profile, an instructor accommodation setting, or a session accessibility toggle.
- The frontend may display the accommodation state, but the backend-scored value must come from server-side session context.
- It adjusts interaction timing thresholds only; it does not alter clinical expectations, rhythm decisions, scope rules, or authored scenario requirements.

Cycle discipline bucket:

```text
cycle_weight(cycle):
  if cycle has authored exception: return 1.0
  if rhythm_check_timing is 1:45-2:15 from cycle start: return 1.0
  if rhythm_check_timing is 1:30-1:44 or 2:16-2:30: return 0.5
  return 0.0

cycle_discipline_points =
  round((sum(cycle_weight(cycle)) / scored_cycles) * 10)
```

Cycle 1 starts at `cpr_started_timestamp`. Later cycles start when compressions resume after the previous shock/no-shock decision. Only cycles after `cpr_started` are scored. If `scored_cycles == 0`, the bucket is not applicable and is removed from the denominator.

Ventilation/ratio management bucket:

```text
expected_ventilation_mode =
  scenario.expected_ventilation_mode override, else
  neonatal_nrp/neonatal -> "3:1", else
  pediatric/infant EMS team -> "15:2", else
  pediatric/infant single_rescuer_exception -> "30:2", else
  adult -> "30:2"

ventilation_state_weight(state):
  if selected mode matches expected mode for patient age, team model, and airway state: return 1.0
  if selected mode is clinically safe but not preferred: return 0.5
  return 0.0

ventilation_ratio_points =
  round((sum(ventilation_state_weight(state)) / scored_ventilation_states) * 5)
```

Expected V1 modes:

- adult without advanced airway: `30:2`
- pediatric/infant EMS crew without advanced airway: `15:2`
- adult advanced airway: continuous compressions + ventilate about every 6 sec
- pediatric/infant advanced airway: continuous compressions + ventilate every 2-3 sec, avoiding hyperventilation

Examples of clinically safe but not preferred:

- Pediatric two-rescuer EMS crew selects `30:2` before advanced airway instead of preferred `15:2`. This is not the preferred EMS-team ratio, but it is still a recognized pediatric BLS ratio in a single-rescuer context.
- Adult arrest without advanced airway selects `continuous_6sec` before an advanced airway is placed. This is premature and not preferred; whether it is safe enough for partial credit should be scenario-authored.

Examples that should not receive partial credit:

- Adult without advanced airway selects `15:2` or `3:1`.
- Pediatric two-rescuer team selects `3:1` outside neonatal resuscitation.
- Pediatric advanced airway with excessive ventilation faster than every 2 seconds.
- Any mode that causes prolonged compression pauses beyond the pause-scoring thresholds.

Scored ventilation states should be created only when the learner has a meaningful opportunity to select or acknowledge the mode:

- initial CPR mode after `cpr_started`
- team-model transition, if authored
- advanced-airway placement, if available and performed
- return from single-rescuer exception to normal EMS crew model, if authored

All ratio buttons may remain visible. The learner is responsible for selecting the clinically correct ratio. If `score_ventilation_ratio: true` or the effective `aha_compliance_gates` includes `ventilation_ratio`, the selected ratio is scored and exposed in the evidence packet for debrief.

If ventilation/ratio scoring is not enabled for the scenario, this bucket is not applicable and is removed from the denominator.

If `scored_ventilation_states == 0`, the bucket is not applicable and is removed from the denominator.

When this bucket is not applicable, the effective ROSC gate list must also remove `ventilation_ratio`. Do not allow a template `aha_compliance_gates` list to block ROSC with a gate the learner had no UI path to satisfy.

Rhythm/shock decision scoring:

```text
rhythm_decision_points = round((correct_decisions / scored_decisions) * 20)
```

If `scored_decisions == 0`, the rhythm/shock decision bucket is not applicable and is removed from the denominator. Do not divide by zero. For abandoned or very short attempts, the parent outcome/abandonment handling determines the CPR sub-component result.

Authoring note for fallback rhythms: decisions after `rhythm_sequence` exhaustion are scored if they are part of the authored attempt, but they may make the rhythm/shock bucket easier if `default_ongoing_rhythm` is non-shockable. Authors should not use a short sequence plus persistent PEA/asystole fallback unless that is the intended teaching design. For rhythm-decision-heavy scenarios, author enough rhythm entries to cover the expected cycles or set a shockable/non-shockable mix intentionally.

Decision severity caps:

- Shock delivered for asystole: critical rhythm-decision error; rhythm/shock bucket max 5/20 and scenario may apply a critical-failure score cap if authored.
- Shock delivered for PEA: major rhythm-decision error; rhythm/shock bucket max 10/20.
- Failure to shock VF/pVT when AED/defib is available: major rhythm-decision error; rhythm/shock bucket max 10/20, or max 5/20 if repeated.
- Correct no-shock for PEA/asystole and correct shock for VF/pVT: full decision credit.

These caps apply after the proportional decision score. Example: 3 correct of 4 decisions yields 15/20, but if the missed decision was shocking asystole, the bucket is capped at 5/20.

`repeated` means two or more missed shock decisions for VF/pVT in the same CPR challenge attempt.

Repeated VF/pVT threshold for the 5/20 cap:

- missed shockable-rhythm decision #1 in an attempt: rhythm/shock bucket max 10/20
- missed shockable-rhythm decision #2 or later in the same attempt: rhythm/shock bucket max 5/20
- applies whether the missed decisions occur on the same persistent shockable rhythm or on separate shockable rhythm checks
- does not carry across replay attempts; each `challenge_attempt_id` is scored independently

Reversible-cause scoring, when enabled:

```text
if checked_non_relevant_count > allowed_non_relevant_count:
  reversible_cause_points = 0
else:
  reversible_cause_points =
    round((relevant_checked_count / relevant_required_count) * max_points)
```

Default `allowed_non_relevant_count`: 2. If the scenario does not assign explicit reversible-cause points, the checklist remains an unscored cognitive aid.

### 9.1.1 Medication Timing Simplification

Medication scoring should stay simple in the first ALS/PALS extension. Do not initially grade "perfectly every 3-5 minutes" as a continuous timing problem.

Recommended first-pass ALS/PALS rules:

- VF/pVT: epinephrine after the second shock when indicated by the authored algorithm.
- PEA/asystole: epinephrine as soon as feasible after compressions/airway/monitor workflow is established.
- Repeat epinephrine: allow 3-5 minute windows only after the first med-timing pass is stable.
- Persistent/refractory VF/pVT: antiarrhythmic first dose after the third shock when medication is in scope, carried, and enabled by the authored algorithm.
- Antiarrhythmic choices should be scenario/protocol constrained, e.g. amiodarone or lidocaine. The scoring service should grade timing/indication, not free-form drug preference, unless the scenario explicitly tests protocol-specific medication selection.
- Repeat antiarrhythmic dosing is deferred until first-dose timing is stable and protocol-specific dose intervals are modeled.

This produces deterministic, teachable grading while avoiding premature complexity.

ALS adaptation rule:

- ALS/PALS controls appear only when enabled by algorithm/scenario and allowed by provider scope, MCA, and agency carried equipment/medications.
- ALS/PALS scoring buckets are applicable only when the learner/agency is expected to perform those interventions.
- For BLS scenarios with ALS auto-dispatch, score BLS responsibilities: CPR quality, AED use, ventilation/BVM, request/prepare ALS, and handoff readiness.
- Do not require BLS learners to administer epinephrine, antiarrhythmics, perform manual defib, place advanced airways, interpret capnography, or perform other ALS-only actions.
- Debrief language should distinguish "not available to your crew" from "missed intervention."

Do not score generic "recognition" inside the CPR challenge unless it is tied to an observable challenge event. Arrest recognition before the HUD opens belongs to the parent scenario. Rhythm recognition is already scored by rhythm/shock decisions. ALS-need recognition is scored by `als_requested` or handoff-readiness events when authored.

### 9.2 Critical Failures

Potential critical failures:

- repeated prolonged pauses
- shock delivered for asystole/PEA
- failure to shock repeated VF/pVT when defib/AED is available
- failure to resume compressions after shock/no-shock decision

Critical failures should not automatically zero the entire scenario unless the scenario contract declares that behavior. Prefer score caps plus explicit debrief flags.

Do not list out-of-scope/unavailable ALS medication administration as a normal clinical critical failure for BLS learners. If such an event appears in a BLS learner's CPR timeline, it is a validation/security/configuration problem handled under §9.3, because the HUD should not expose that control.

Avoid double-jeopardy with the post-decision resume bucket:

- Slow resume is handled by the 10-point post-decision resume bucket and the `delayed_resume` flag.
- `failure_to_resume` critical failure applies only when compressions are not resumed before the next required state transition, an abandonment, or an authored timeout threshold.
- V1 default timeout for true failure to resume: > 20 seconds after shock/no-shock decision without `compressions_resumed`.
- A single 8-second resume earns partial resume credit but should not trigger a critical-failure cap.

`repeated_prolonged_pauses` threshold:

- A prolonged pause is any scored pause > 15 seconds.
- Repeated prolonged pauses means two or more prolonged pauses in the same CPR challenge attempt.
- Severe pauses > 20 seconds still receive the stronger pause deduction and may separately trigger `failure_to_resume` only if compressions are not resumed as defined above.

`CPR not initiated in a confirmed arrest scenario` belongs to the main scenario scoring engine, not the CPR challenge scoring service. The challenge may never open if the learner fails to initiate CPR after a vitals-engine arrest transition, so the parent scenario must detect and score that failure.

### 9.3 Scope and Equipment Rules

The challenge must use the same effective context as the scenario:

- provider level
- agency level cap
- MCA / protocol profile
- agency equipment and medication inventory
- non-transport / ALS co-dispatch context

If the learner is BLS and ALS is auto-dispatched:

- do not require ALS medications
- do score AED/CPR discipline, airway/BVM, request/prepare handoff, and readiness for ALS arrival
- debrief should say "not available to your crew" rather than "you should have given..."

If a medication or device is not carried:

- it should not appear in the CPR HUD
- it should not be required for score
- if requested after the HUD closes and chat is available again, the system should state it is not carried, separate from scope

Out-of-scope or unavailable ALS medication events in the CPR timeline are defense-in-depth validation failures, not normal reachable gameplay. If the HUD filtering is correct, a BLS learner should never see or submit these controls.

Server behavior:

- Reject forged or malformed ALS medication events when the learner/agency/MCA does not permit them.
- Mark the attempt `rejected_invalid` when the event indicates tampering or impossible client state.
- Mark the scenario/admin diagnostic as a configuration defect if the server determines the event came from an incorrectly exposed HUD control.
- Do not treat this as an ordinary clinical critical failure unless the scenario intentionally authors an in-scope-but-dangerous medication decision.

### 9.4 Missing Required Equipment at Session Start

If a CPR-enabled scenario declares `required_equipment_ids` or `required_medication_ids` that are unavailable to the active agency, the session must not silently proceed into a broken challenge.

V1 behavior:

- Scenario start should fail with a clear diagnostic if required challenge equipment/medications are missing.
- The user-facing message should say the scenario is unavailable for the active agency configuration.
- The developer/admin diagnostic should list the missing IDs.

Example:

```text
CPR challenge unavailable for this agency: missing required equipment aed.
```

Rationale: falling through to standard scoring would hide a scenario-authoring/configuration error, while continuing without AED scoring would change the instructional objective. If a BLS no-AED arrest scenario is desired, author it explicitly without `aed` in `required_equipment_ids`.

---

## 10. Scenario Authoring Contract

Each CPR-enabled scenario declares:

```json
{
  "cpr_challenge": {
    "enabled": true,
    "challenge_id": "peds_arrest_01_cpr",
    "arrest_type": "adult|pediatric|neonatal",
    "algorithm": "adult_bls|adult_als|pediatric_bls|pediatric_pals|neonatal_nrp",
    "team_model": "ems_team|two_rescuer|single_rescuer_exception",
    "team_transition_events": [
      {"cycle": 2, "team_model": "ems_team"}
    ],
    "initial_rhythm": "vf|pulseless_vt|pea|asystole",
    "rhythm_sequence": ["vf", "vf", "pea"],
    "rhythm_sequence_notes": "Each entry is the AED/monitor rhythm for that cycle; vf and pulseless_vt are shockable, pea and asystole are non-shockable.",
    "default_ongoing_rhythm": "pea",
    "cycle_seconds": 120,
    "rosc_criteria": {
      "eligible_after_cycles": 3,
      "max_cycles_before_rosc": 5,
      "hard_stop_cycle": 5,
      "min_ccf": 0.80,
      "min_ccf_window": "consecutive_eligible_cycles",
      "aha_compliance_gates": [
        "ccf",
        "rhythm_decisions",
        "post_decision_resume",
        "ventilation_ratio",
        "no_critical_failure"
      ],
      "als_requirements_policy": "omit_unavailable"
    },
    "allow_aed": true,
    "allow_manual_defib": false,
    "allow_precharge": false,
    "allow_continuous_rhythm_display": false,
    "allow_advanced_airway": false,
    "allow_medications": false,
    "reversible_causes": ["hypoxia"],
    "required_equipment_ids": ["aed", "bvm_adult_peds_infant"],
    "required_medication_ids": [],
    "shock_dose_mode": "adult_default|pediatric_initial|pediatric_subsequent|authored",
    "authored_shock_doses": [
      {"cycle": 1, "dose_category": "pediatric_initial"},
      {"cycle": 2, "dose_category": "pediatric_subsequent"}
    ],
    "post_rosc_vitals_profile_id": "post_rosc_default",
    "termination_allowed": false,
    "termination_criteria": [],
    "feedback_focus": ["ccf", "pause_discipline"],
    "rubric_integration": {
      "dimension": "clinical_performance",
      "item_id": "cpr_challenge_management",
      "weight_points": 20
    }
  }
}
```

Common required fields:

- `enabled`
- `challenge_id`
- `arrest_type`
- `algorithm`
- `team_model`
- `rubric_integration`

Adult/pediatric CPR required fields:

- `initial_rhythm`
- `rhythm_sequence`
- `cycle_seconds`
- `rubric_integration`

Neonatal required fields:

- `neonatal_initial_status`
- `hr_reassessment_gates`
- `ventilation_escalation_steps`

Validation rule: adult/pediatric CPR scenarios must declare `rosc_criteria` unless `termination_allowed: true` and `termination_criteria` is non-empty. Load-time validation should reject CPR challenge configs that have neither deterministic ROSC criteria nor an explicit termination path.

Validation rules:

- `challenge_id` must be unique within the scenario definition namespace, not globally across all tenants. Recommended canonical namespace: `{scenario_id}:{challenge_id}`. Two agencies may run the same scenario JSON with the same `challenge_id`; tenant/session identity comes from the session and attempt records, not from the challenge ID string alone.
- `cycle_seconds` must be between 60 and 300 for adult/pediatric CPR modes.
- `cycle_seconds` does not apply to neonatal NRP mode unless a neonatal-specific cycle model is explicitly authored.
- `hard_stop_cycle` must be >= `max_cycles_before_rosc`; V1 default is equal to `max_cycles_before_rosc`.
- If `hard_stop_cycle > max_cycles_before_rosc`, the scenario must author explicit extended no-ROSC behavior. Otherwise validation fails.
- `rhythm_sequence` must not be empty for adult/pediatric CPR modes. If the sequence exhausts before ROSC/no-ROSC endpoint, use `default_ongoing_rhythm` or repeat the last rhythm.
- Scenario authors must define the rhythm sequence intentionally. Each index maps to the rhythm presented at that AED/monitor analysis cycle. The engine determines shockability from canonical rhythm IDs: `vf` and `pulseless_vt`/`pvt` are shockable; `pea` and `asystole` are non-shockable. Example: `["vf", "vf", "pea"]` means the first and second analyses should advise shock; the third should advise no shock.
- If ROSC can be obtained, authors must declare `rosc_criteria` and `post_rosc_vitals_profile_id`. The deterministic backend decides ROSC from CPR performance gates and the authored cycle window, not from the frontend or LLM.
- `algorithm` sets default capabilities; explicit `allow_*` flags may override defaults downward but may not expand beyond provider scope, agency equipment, MCA, or scenario requirements.
- Example: `algorithm: "adult_als", allow_medications: false` is valid for an ALS rhythm/defib scenario that intentionally excludes medication timing. `algorithm: "adult_bls", allow_medications: true` does not make ALS medications available.
- `als_requirements_policy` enum values: `omit_unavailable` (default), `require_if_available`, `disabled`. V1 default `omit_unavailable` means ALS gates are scored only when the learner's provider level, agency equipment/medications, MCA, and scenario config all make that intervention available and expected. BLS learners and BLS agencies never fail ROSC eligibility for omitted ALS interventions.
- Do not use a free-form `als_requirements` string. `als_requirements_policy` is the canonical field.
- `omit_unavailable`: remove unavailable ALS metrics from the denominator and ROSC gate list.
- `require_if_available`: score ALS metrics only when available to this learner/agency/MCA; omitted ALS actions are misses only in that available context.
- `disabled`: do not expose or score ALS-specific controls even if the algorithm would normally support them.
- `team_model` defaults to `ems_team`. Do not author `single_rescuer_exception` unless the scenario is specifically teaching public/lay rescuer or isolated-provider CPR rather than normal EMS crew response.
- Adult/pediatric CPR scenarios must declare either `rosc_criteria` or structured termination criteria.
- Neonatal scenarios must declare neonatal-specific HR/ventilation escalation gates instead of adult/pediatric rhythm-cycle requirements.

Optional fields:

- `rosc_criteria`
- `default_ongoing_rhythm`
- `additional_action_menu`
- `termination_allowed`
- `termination_criteria`
- `allow_aed`
- `allow_manual_defib`
- `allow_precharge`
- `allow_continuous_rhythm_display`
- `allow_advanced_airway`
- `allow_medications`
- `score_ventilation_ratio`
- `expected_ventilation_mode`
- `reversible_causes`
- `required_equipment_ids`
- `required_medication_ids`
- `team_transition_events`
- `shock_dose_mode`
- `authored_shock_doses`
- `post_rosc_vitals_profile_id`
- `post_rosc_vitals_profiles`
- `feedback_focus`

Authoring rule: do not use this challenge for vague "patient might arrest" scenarios unless CPR is actually expected to occur. The challenge is for active cardiac arrest management.

`additional_action_menu` schema:

```json
"additional_action_menu": {
  "enabled": true,
  "phase": "during_arrest|post_rosc|both",
  "sections": [
    {
      "id": "actions",
      "label": "Actions",
      "kind": "action",
      "actions": [
        {"id": "reassess_airway_bvm", "label": "Reassess Airway / BVM", "action_id": "airway_bvm_reassess", "finding": "Airway remains patent with BVM support; bilateral chest rise is present with ventilations. Avoid excessive ventilation."},
        {"id": "suction_airway", "label": "Suction Airway", "action_id": "airway_suction", "finding": "Airway suction performed. No significant secretions or vomitus are present; continue BVM ventilation."},
        {"id": "place_supraglottic_airway", "label": "Place Supraglottic Airway", "action_id": "supraglottic_airway_insert", "finding": "Supraglottic airway placed successfully. Continue ventilations and avoid hyperventilation."},
        {"id": "check_bgl", "label": "Check BGL", "action_id": "blood_glucose_check", "finding": "Blood glucose is 118 mg/dL. Hypoglycemia is not driving this arrest."},
        {"id": "check_pupils", "label": "Check Pupils", "action_id": "pupil_assessment", "finding": "No opioid toxidrome is evident: pupils are mid-position and sluggish, and the history is sudden exertional collapse."}
      ]
    },
    {
      "id": "meds",
      "label": "Meds",
      "kind": "medication",
      "actions": [
        {"id": "consider_naloxone", "label": "Consider Naloxone if Opioid Suspected", "action_id": "naloxone_consider", "finding": "Naloxone is considered only if opioid overdose is suspected and the medication is available. This scenario has no opioid toxidrome evidence; continue CPR/AED and ventilation."}
      ]
    }
  ]
}
```

Purpose: give the learner a structured menu for arrest adjuncts, reversible-cause investigation, medications, and post-ROSC care without cluttering the core CPR/AED controls. The HUD should show top-level `Actions` and `Meds` buttons, then scenario-authored options under each. Assessment-style actions should include a deterministic `finding` response so the learner receives immediate feedback without the frontend inventing clinical data. Examples include BGL check, pupil assessment, airway adjunct checks, naloxone when opioid cause is plausible and in scope/carried, temperature management, 12-lead after ROSC, BP support prompts, and transport/handoff readiness.

The action menu should also expose Medical Control. This opens the standard medical-control modal rather than a CPR-specific chat path. CPR continues visually in automatic, score-neutral background mode using the selected compression ratio; auto-completed cycles increment the displayed cycle counter but do not satisfy minimum-cycle requirements or alter CPR score. If the learner is consulting medical control to stop CPR and declare time of death, the consultation response must be captured before `termination_of_resuscitation` is accepted unless a valid DNR/POST/withholding context is documented.

Guideline alignment:

- Adult BLS/AED scenarios should expose only BLS-compatible arrest actions: high-quality CPR, AED use, airway opening/BVM/oxygen support, suction, supraglottic airway when carried/authorized, pulse checks during rhythm-analysis pauses, and reversible-cause screening that does not require ALS equipment. Naloxone may appear only as an opioid-suspected/available branch; do not present oral glucose, ACLS epinephrine, antiarrhythmics, IV/IO, manual defibrillation, or endotracheal intubation as BLS options.
- Adult ACLS scenarios may add `Meds` for epinephrine cardiac dosing and amiodarone/lidocaine when the algorithm, provider scope, MCA, and agency medication list allow them. ACLS `Actions` may add IV/IO access, manual defibrillation/pre-charge, advanced airway, waveform capnography, and H's/T's reversible-cause management.
- Scenario-authored findings should explain when an option is considered but not indicated (for example, no opioid toxidrome evidence) rather than treating every button press as a successful/indicated intervention.

Phase 1 default: this menu may be present as an unscored event logger unless the scenario explicitly maps actions into scoring. Do not penalize BLS learners for ALS-only adjuncts that are not in scope or not carried by the agency.

`rubric_integration` schema:

```json
"rubric_integration": {
  "dimension": "clinical_performance",
  "item_id": "cpr_challenge_management",
  "weight_points": 20
}
```

Allowed fields:

- `dimension`: required parent rubric dimension, usually `clinical_performance` for BLS CPR/AED scenarios.
- `item_id`: required stable rubric item ID.
- `weight_points`: required positive number representing how many parent-rubric points the normalized CPR challenge score maps into.

Mapping formula:

```text
cpr_parent_points = round((cpr_challenge.normalized_score / 100) * weight_points)
```

`weight_points` is an absolute point cap inside the named parent rubric dimension, not a percentage. Example: if `weight_points` is 20 and the CPR challenge normalized score is 82, the parent rubric item earns `round(0.82 * 20) = 16` points. The parent dimension denominator includes those 20 authored points.

Adult/pediatric CPR challenge configs with `enabled: true` must include `rubric_integration`; missing integration is a load-time validation error.

If `shock_dose_mode: "authored"`, the scenario must provide `authored_shock_doses`. Load-time validation should reject authored dose mode without authored dose data.

`authored_shock_doses` schema:

```json
[
  {"cycle": 1, "dose_category": "pediatric_initial"},
  {"cycle": 2, "dose_category": "pediatric_subsequent"}
]
```

Allowed fields:

- `cycle`: required positive integer, matching the rhythm-check cycle where the dose applies.
- `dose_category`: required value from `adult_default`, `pediatric_initial`, `pediatric_subsequent`, or `authored`.
- `joules`: optional display-only number when the author wants the log to show a specific energy.
- `min_joules` / `max_joules`: optional validation range for later manual-defib phases; not required for Phase 1 AED.

If `dose_category: "authored"` is used inside an authored dose entry, the entry must include either `joules` or both `min_joules` and `max_joules`.

Completeness rule for `shock_dose_mode: "authored"`:

- Every authored shockable rhythm cycle must have a matching `authored_shock_doses` entry, or a wildcard fallback entry.
- If a shockable rhythm can occur after `rhythm_sequence` exhaustion because `default_ongoing_rhythm` is shockable, the fallback must cover those cycles too.
- Missing dose coverage is a load-time validation error, not a scoring-time fallback.

Optional wildcard fallback:

```json
{"cycle": "*", "dose_category": "pediatric_subsequent"}
```

Do not silently apply `adult_default` or pediatric defaults when `shock_dose_mode` is `authored`.

`team_transition_events` behavior:

- The event is a scenario-authored background state change, not a learner action.
- At the specified cycle boundary, the HUD prompts the learner that team model has changed.
- From that point forward, expected ventilation/ratio scoring uses the new `team_model`.
- The learner must acknowledge/select the new ventilation mode to earn full ventilation/ratio credit.
- Missing the switch affects the ventilation/ratio bucket; it does not create a separate critical failure unless authored.

`feedback_focus` schema:

```json
"feedback_focus": ["ccf", "pause_discipline", "rhythm_decisions"]
```

Allowed values are the deterministic debrief areas the author wants emphasized: `ccf`, `pause_discipline`, `cycle_discipline`, `post_decision_resume`, `rhythm_decisions`, `ventilation_ratio`, `reversible_causes`, `als_scope`, `post_rosc_transition`. This field affects debrief prioritization only. It must not change deterministic scoring.

`post_rosc_vitals_profile_id` references a scenario-authored vitals profile. If omitted, `post_rosc_default` may be used only when the scenario defines a matching default profile.

Minimum post-ROSC vitals profile schema:

```json
"post_rosc_vitals_profiles": {
  "post_rosc_default": {
    "transition_seconds": 30,
    "vitals": {
      "hr": 118,
      "pulse_present": true,
      "bp": "86/50",
      "rr": 18,
      "spo2": 94,
      "mental_status": "unresponsive_with_pulse"
    },
    "trend": {
      "bp": "improving",
      "spo2": "improving",
      "mental_status": "slow_improvement"
    }
  }
}
```

The vitals engine consumes this profile after the backend accepts the ROSC event. The profile must make arrest physiology impossible after ROSC, e.g. no HR 0, no absent pulse, no persistent pulseless rhythm unless the scenario explicitly authors re-arrest as a later event.

### 10.1 Neonatal Authoring Extension

Neonatal/newborn scenarios should add a neonatal-specific block rather than forcing the adult/pediatric `rhythm_sequence` model.

Example:

```json
{
  "cpr_challenge": {
    "enabled": true,
    "challenge_id": "newborn_resus_01_nrp",
    "arrest_type": "neonatal",
    "algorithm": "neonatal_nrp",
    "team_model": "ems_team",
    "neonatal_initial_status": {
      "gestational_age_weeks": 39,
      "tone": "poor",
      "breathing": "apneic",
      "initial_hr": 80
    },
    "hr_reassessment_gates": [
      {"after": "initial_steps", "hr_at_gate": 70},
      {"after": "effective_ppv", "hr_at_gate": 80},
      {"after": "compressions", "hr_at_gate": 90}
    ],
    "ventilation_escalation_steps": [
      "warm_dry_stimulate_position",
      "ppv_start",
      "mr_sopa_corrective_steps",
      "alternate_airway_when_indicated",
      "compressions_3_to_1_when_hr_under_60"
    ],
    "required_equipment_ids": ["bvm_neonatal", "neonatal_mask", "stethoscope"],
    "required_medication_ids": []
  }
}
```

Neonatal scoring should prioritize:

- timely initial steps
- effective PPV and corrective steps
- HR reassessment accuracy
- correct escalation to 3:1 compressions when HR remains < 60/min
- avoiding unnecessary suctioning or delayed ventilation
- thermoregulation
- oxygen/SpO2 use when authored
- epinephrine/volume escalation only after ventilation/compression steps are effective and when in scope/carried

`hr_at_gate` represents the authored scenario vital sign value at that reassessment point, not the clinical target. Effective PPV should generally improve HR; if HR remains < 60/min despite effective PPV, that is the escalation trigger for coordinated compressions.

### 10.2 Shock Dose Representation

The event schema should avoid requiring the scoring service to compute pediatric joules from raw weight in V1.

Recommended event field:

```json
{"t_ms": 127000, "type": "shock_delivered", "dose_category": "pediatric_initial"}
```

Allowed `dose_category` values:

- `adult_default`
- `pediatric_initial`
- `pediatric_subsequent`
- `authored`

If joules are also logged for display, they are reference data. Scoring should use `dose_category` or authored dosing rules unless a future version explicitly implements weight-based arithmetic.

### 10.3 Termination of Resuscitation

Termination of resuscitation is deferred beyond V1 unless a scenario explicitly declares criteria.

Do not accept a loose `termination_of_resuscitation` event as valid simply because the learner clicks it. If ROSC has not occurred, termination requires either documented medical-control consultation before termination or an authored DNR/POST/withholding context. Missing both is a deterministic critical failure under the `no_critical_failure` gate.

Example:

```json
{
  "termination_allowed": true,
  "termination_criteria": {
    "mode": "all",
    "criteria": [
      {"id": "no_rosc_after_elapsed_seconds", "elapsed_seconds": 1200},
      {"id": "no_shockable_rhythm_for_cycles", "cycles": 3},
      {"id": "medical_control_contacted"}
    ]
  }
}
```

V1 recommendation: set `termination_allowed: false` and use ROSC-based exits only.

Termination criteria schema:

- `mode`: `all` or `any`; V1 default is `all`.
- `criteria`: array of structured criterion objects.

Allowed V1 criterion IDs:

| Criterion ID | Required fields | Satisfaction rule |
|---|---|---|
| `no_rosc_after_elapsed_seconds` | `elapsed_seconds` | Code time since `cpr_started` is >= `elapsed_seconds` and ROSC has not occurred. |
| `no_shockable_rhythm_for_cycles` | `cycles` | Last N rhythm decisions were non-shockable rhythms. |
| `medical_control_contacted` | none | Validated event `medical_control_consulted` or legacy `medical_control_contacted` exists before `termination_of_resuscitation`. |
| `authored_no_termination_context` | `reason` | Scenario-specific criterion; must include author-facing explanation and should be avoided in V1 unless reviewed. |

Do not accept unknown bare-string criteria. Unknown criterion IDs are load-time validation errors.

---

## 11. Evidence Packet and Debrief

The backend should evaluate the CPR timeline and write hardened facts into the evidence packet.

### 11.0 Parent Scenario Rubric Integration

The CPR challenge score is a sub-component of the parent scenario rubric, not a separate replacement score.

V1 integration rule:

- Parent scenario declares a dedicated rubric item or dimension, e.g. `cpr_challenge_management`.
- The CPR challenge normalized score maps into that item according to the parent scenario's authored weight.
- Default placement is `clinical_performance` for BLS CPR/AED scenarios.
- `protocols_treatment` may receive separate deterministic flags for scope/protocol violations, e.g. shocking asystole or out-of-scope ALS medication.
- `abandoned` maps to 0 for the CPR challenge sub-component, not automatically 0 for the entire scenario unless the parent scenario explicitly declares a critical-failure cap.
- `incomplete_unverified` and `rejected_invalid` should not silently produce numeric CPR rubric credit. The parent scenario should surface a diagnostic and avoid presenting an authoritative CPR score.

Authoring requirement:

```json
"rubric_integration": {
  "dimension": "clinical_performance",
  "item_id": "cpr_challenge_management",
  "weight_points": 20
}
```

If `cpr_challenge.enabled: true` and `rubric_integration` is missing, adult/pediatric CPR scenarios should fail load-time validation. This prevents a standalone 0-100 CPR score from floating outside the parent scenario's deterministic score model.

Phase 0 must define the first scenario's exact parent-rubric weight before implementation.

Suggested evidence packet section:

```json
{
  "cpr_challenge": {
    "completed": true,
    "timestamp_integrity": "server_anchored",
    "outcome": "rosc",
    "ccf": 0.84,
    "ccf_by_cycle": [
      {"cycle": 1, "ccf": 0.78, "compression_active_sec": 94, "scored_sec": 120},
      {"cycle": 2, "ccf": 0.82, "compression_active_sec": 98, "scored_sec": 120},
      {"cycle": 3, "ccf": 0.86, "compression_active_sec": 103, "scored_sec": 120}
    ],
    "average_pause_sec": 8.2,
    "longest_pause_sec": 13.4,
    "cycle_discipline": [
      {"cycle": 1, "rhythm_check_sec_from_cycle_start": 120, "credit": 1.0},
      {"cycle": 2, "rhythm_check_sec_from_cycle_start": 126, "credit": 1.0},
      {"cycle": 3, "rhythm_check_sec_from_cycle_start": 121, "credit": 1.0}
    ],
    "rhythm_decisions": [
      {"cycle": 1, "rhythm": "vf", "decision": "shock", "correct": true},
      {"cycle": 2, "rhythm": "pea", "decision": "no_shock", "correct": true},
      {"cycle": 3, "rhythm": "pea", "decision": "no_shock", "correct": true}
    ],
    "medication_timing": {"status": "not_applicable"},
    "ventilation_modes": [
      {"at_cycle": 1, "mode": "15:2"},
      {"at_cycle": 3, "mode": "continuous_2_3_sec"}
    ],
    "score": 82,
    "rosc": {
      "achieved": true,
      "triggered_at_boundary": 4,
      "triggered_after_cycle": 3,
      "basis": "performance_gated",
      "criteria": {
        "eligible_after_cycles": 3,
        "max_cycles_before_rosc": 5,
        "hard_stop_cycle": 5,
        "min_ccf": 0.80,
        "min_ccf_window": "consecutive_eligible_cycles",
        "aha_compliance_gates": [
          "ccf",
          "rhythm_decisions",
          "post_decision_resume",
          "ventilation_ratio",
          "no_critical_failure"
        ],
        "gate_results": {
          "ccf": {"passed": true, "basis": "cycles_2_3"},
          "rhythm_decisions": {"passed": true},
          "post_decision_resume": {"passed": true},
          "ventilation_ratio": {"passed": true},
          "no_critical_failure": {"passed": true}
        }
      }
    },
    "flags": ["one_pause_over_10_sec"]
  }
}
```

ROSC boundary fields:

- `triggered_after_cycle`: last completed compression/rhythm-check cycle with scored CCF and cycle-discipline data.
- `triggered_at_boundary`: boundary where ROSC was triggered after evaluating the completed cycle window.

Do not treat `triggered_at_boundary` as an additional completed cycle. It does not require a matching `ccf_by_cycle` entry and does not add to `scored_cycles`.

No-ROSC / criteria-not-met evidence shape:

```json
{
  "cpr_challenge": {
    "completed": true,
    "timestamp_integrity": "server_anchored",
    "outcome": "criteria_not_met",
    "ccf": 0.72,
    "ccf_by_cycle": [
      {"cycle": 1, "ccf": 0.68, "compression_active_sec": 82, "scored_sec": 120},
      {"cycle": 2, "ccf": 0.74, "compression_active_sec": 89, "scored_sec": 120},
      {"cycle": 3, "ccf": 0.76, "compression_active_sec": 91, "scored_sec": 120}
    ],
    "average_pause_sec": 12.4,
    "longest_pause_sec": 18.1,
    "cycle_discipline": [
      {"cycle": 1, "rhythm_check_sec_from_cycle_start": 138, "credit": 0.5},
      {"cycle": 2, "rhythm_check_sec_from_cycle_start": 126, "credit": 1.0},
      {"cycle": 3, "rhythm_check_sec_from_cycle_start": 141, "credit": 0.5}
    ],
    "rhythm_decisions": [
      {"cycle": 1, "rhythm": "vf", "decision": "shock", "correct": true},
      {"cycle": 2, "rhythm": "pea", "decision": "no_shock", "correct": true},
      {"cycle": 3, "rhythm": "pea", "decision": "no_shock", "correct": true}
    ],
    "medication_timing": {"status": "not_applicable"},
    "ventilation_modes": [],
    "score": 61,
    "rosc": {
      "achieved": false,
      "triggered_at_boundary": null,
      "triggered_after_cycle": null,
      "basis": "criteria_not_met",
      "criteria": {
        "eligible_after_cycles": 3,
        "max_cycles_before_rosc": 3,
        "hard_stop_cycle": 3,
        "min_ccf": 0.80,
        "min_ccf_window": "consecutive_eligible_cycles",
        "aha_compliance_gates": [
          "ccf",
          "rhythm_decisions",
          "post_decision_resume",
          "no_critical_failure"
        ],
        "gate_results": {
          "ccf": {"passed": false, "basis": "cycles_2_3", "values": [0.74, 0.76]},
          "rhythm_decisions": {"passed": true},
          "post_decision_resume": {"passed": true},
          "no_critical_failure": {"passed": true}
        }
      }
    },
    "flags": ["rosc_criteria_not_met"]
  }
}
```

`completed` relationship to `outcome`:

| Outcome | `completed` |
|---|---|
| `rosc` | `true` |
| `criteria_not_met` | `true` |
| `terminated` | `true` when termination criteria were valid |
| `abandoned` | `true` as a terminal failed attempt |
| `incomplete_unverified` | `false` |
| `rejected_invalid` | `false` |

`completed` means the attempt reached a terminal state usable by scenario flow. It does not mean the learner succeeded.

Allowed `outcome` values:

- `rosc`
- `criteria_not_met`
- `abandoned`
- `terminated`
- `incomplete_unverified`
- `rejected_invalid`

`abandoned` should be represented as `timestamp_integrity: "abandoned"` plus `outcome: "abandoned"`, not as a separate top-level `abandoned: true` boolean. This keeps timestamp/result state consistent across §4.2.1, §8.1, and the evidence packet.

Debrief should explain:

- how CCF affected perfusion
- whether ROSC was achieved through sustained AHA-compliant management and target CCF
- where pauses occurred and why they mattered
- whether rhythm decisions matched the algorithm
- whether compression mode/ratio matched adult/peds/airway context
- for pediatric advanced-airway ventilation, that 20-30/min is a ceiling-bounded range and hyperventilation is harmful
- whether medication timing was appropriate, if applicable
- what the learner should do next time

Outcome-specific debrief requirements:

- `rosc.achieved: true`: show ROSC timing, strongest contributing behaviors, and any remaining improvement targets.
- `criteria_not_met`: show full verified CCF/pause/rhythm/ventilation metrics, identify which `aha_compliance_gates` failed, and explicitly explain what prevented ROSC eligibility.
- `abandoned`: show the partial timeline, state that leaving an active arrest is abandonment, and still list the last verified clinical gaps before exit.
- `incomplete_unverified`: do not show precise timing metrics as authoritative; explain that timing integrity was lost and show only non-timing facts with `verified: false`.
- `rejected_invalid`: do not provide clinical scoring from the CPR challenge; explain that the timeline was invalid and the challenge could not be scored.

Debrief should not:

- invent physical compression depth or recoil observations
- criticize unavailable/out-of-scope interventions as if they were expected
- let the LLM recompute CCF or pause times

ROSC flow:

- After the CPR HUD submits a ROSC outcome, the learner returns to normal scenario care for post-ROSC assessment, treatment, DMIST, narrative, and disposition.
- The HUD must not auto-open the debrief on ROSC in scenario runs.
- CPR metrics are carried into the normal debrief as deterministic HUD evidence and a CPR feedback summary.

---

## 12. Mobile Layout

Mobile should not attempt to show the full desktop HUD at once.

Recommended mobile tabs:

- **Code:** cycle timer, compression status, CCF, resume/pause controls
- **Monitor:** rhythm display, shock/no-shock controls
- **Actions:** airway, meds, reversible causes
- **Log:** timestamped code log

The `Resume Compressions` action should be sticky and always visible whenever compressions are paused.

---

## 13. Accessibility and Usability

Requirements:

- large tap targets
- color plus text for active/paused/correct/incorrect states
- no information conveyed by color alone
- code log readable by screen readers
- timer warnings with text and visual state, not sound alone
- no rapid-tap mechanics required for learners with motor limitations

Optional:

- metronome audio toggle
- visual compression-rate pulse indicator
- reduced-motion mode

Accessibility scoring accommodation: post-shock/no-shock resume timing should support an accessibility-adjusted threshold when assistive interaction mode is enabled. The standard full-credit threshold is <= 5 seconds; the accommodated threshold may extend to <= 10 seconds while preserving the same clinical teaching message in debrief. Do not make repeated rapid tapping the primary measure of clinical competence.

---

## 14. Implementation Phases

### Phase 0: Design Readiness

- approve this design contract
- decide first target scenario: adult BLS arrest, pediatric BLS arrest, or ALS arrest
- define first scenario's `cpr_challenge` JSON block
- confirm action IDs for CPR, AED, shock, airway, meds, and ROSC
- confirm neonatal action IDs for initial steps, PPV, MR SOPA/corrective ventilation, 3:1 compressions, and HR reassessment before Phase 5
- confirm backend event schema
- confirm CPR challenge is authoritative for `cpr_started` in CPR-enabled scenarios and cannot double-credit `cpr_initiate`
- confirm actor-independent `rhythm_sequence` behavior is acceptable for V1
- confirm normalized denominator scoring for non-applicable metrics
- confirm explicit bucket formulas for CCF, pause discipline, post-decision resume, cycle discipline, ventilation/ratio management, rhythm/shock decisions, and reversible causes
- confirm missing `required_equipment_ids` / `required_medication_ids` blocks scenario start with a clear diagnostic
- confirm deterministic `rosc_criteria` validation and 3-5 cycle performance-gated ROSC behavior
- confirm no-ROSC hard stop behavior and `hard_stop_cycle`
- confirm exhausted `rhythm_sequence` fallback behavior
- confirm `aha_compliance_gates` list and CCF eligibility window
- confirm per-gate pass/fail thresholds for ROSC eligibility
- confirm `als_requirements_policy` enum behavior and removal of free-form `als_requirements`
- confirm CPR challenge score maps into the parent scenario rubric through `rubric_integration`
- confirm `rubric_integration.weight_points` absolute point-cap mapping formula
- confirm exact parent scenario rubric dimension/item/weight for the first implementation scenario
- confirm non-ROSC, abandoned, `incomplete_unverified`, and `rejected_invalid` debrief behavior
- confirm `last_scored_event_timestamp` endpoint mapping for each scored outcome
- confirm `compressions_paused.reason` and `compressions_resumed.reason` contracts
- confirm `ventilation_mode_set` captures initial ventilation/ratio selection when the bucket is applicable
- confirm `incomplete_unverified` null-score result behavior
- confirm `rejected_invalid` result behavior
- confirm CPR-to-vitals-engine ROSC handoff and post-ROSC vitals profile
- confirm AED-first pre-CPR validation ordering
- confirm replay/attempt storage semantics
- confirm authored shock dose contract when `shock_dose_mode: "authored"`
- confirm `allow_continuous_rhythm_display` behavior
- confirm pause and cycle-discipline scoring windows
- confirm server-side timestamp anchor/heartbeat integrity rule
- confirm server-window mismatch maps to `rejected_invalid`, while incomplete heartbeat evidence maps to `incomplete_unverified`
- confirm abandoned HUD score treatment
- confirm Lexi/AI-response lockout during active CPR HUD
- confirm chat draft caching/restoration when HUD interrupts standard Immersive Mode
- confirm timer expiry holds at 0:00 and resets only after rhythm decision plus compression resume
- confirm DOA/no-CPR scenarios disable the CPR HUD and score erroneous CPR through the parent scenario
- confirm heartbeat grace period before marking a challenge `incomplete_unverified`
- confirm sticky `Resume Compressions` control and accessibility-adjusted resume timing threshold

### Phase 1: BLS CPR / AED Challenge

Build the smallest useful version:

- CPR active/paused state
- Start CPR quick action available near the LOC/Breathing/Pulse assessment controls; it opens the HUD but does not auto-start compressions
- learner-selected compression mode starts CPR
- 2-minute cycle timer
- CCF calculation
- AED power-on/pad attachment immediately starts analysis
- rhythm check
- shock/no-shock decision
- immediate resume
- no ventilation mode selector in the first implementation scenario
- ventilation/ratio bucket is not applicable in Phase 1 unless the first scenario explicitly adds a mode selector
- `ventilation_ratio` ROSC gate is removed from the effective gate list when the ventilation/ratio bucket is not applicable
- code log
- structured `additional_action_menu` event logging for AHA-aligned BLS actions such as airway/BVM reassessment, suction, supraglottic airway when carried/authorized, BGL/pupil reversible-cause screening, and naloxone consideration only when opioid overdose is suspected/available; unscored unless a scenario explicitly maps actions into scoring
- in-challenge pause warnings at > 10 sec and > 20 sec
- AED-before-CPR ordering support
- server-anchored challenge start/end and keepalive validation
- abandoned/incomplete/unverified challenge states
- deterministic backend scoring
- post-arrest evidence packet facts for debrief and handoff/narrative use

No ALS medications in Phase 1.

### Phase 2: Pediatric Mode

Add:

- pediatric team model
- infant arrest handling under the pediatric BLS/PALS model; only neonate/newborn/perinatal resuscitation uses the separate neonatal/NRP pathway
- pediatric ratio/debrief support so learners can select from the shared ratio controls and be evaluated against the correct pediatric `15:2` EMS crew workflow when the ventilation/ratio bucket is enabled
- optional single-rescuer exception only for explicitly authored teaching cases
- pediatric AED/pads/attenuator references
- pediatric debrief language
- pediatric scenario authoring examples

Progress toward closeout (2026-05-04):

- [x] Pediatric BLS/AED scenario authored: `peds_cardiac_arrest_01_bls`
- [x] Pediatric team model configured as `ems_team`
- [x] Shared ratio controls used with pediatric expected mode `15:2`
- [x] `ventilation_ratio` score bucket and ROSC gate enabled for the pediatric scenario
- [x] Pediatric CPR scenario placed on PM3 Cardiac/AMS map for testing
- [x] Pediatric post-ROSC vitals profile authored and regression-tested
- [x] Pediatric cardiac arrest concept added to the clinical taxonomy
- [x] Pediatric AED pads/attenuator references included in scenario objectives/scoring language
- [x] Manual browser E2E for `peds_cardiac_arrest_01_bls`
- [x] Infant arrest model decision recorded: infant uses pediatric BLS/PALS; only neonate/newborn/perinatal resuscitation is different

### Phase 3: ALS / PALS Extensions

Add:

- manual defib
- pre-charge
- epinephrine timing
- antiarrhythmic timing
- advanced airway mode change
- adult vs pediatric ventilation targets after advanced airway
- protocol/scope/equipment filtering for all advanced controls

### Phase 4: Analytics and Instructor Review

Add:

- detailed pause graph
- cycle-by-cycle review
- instructor-facing CCF trend
- common error tags
- remediation routing to AED/CPR mini-games or specific arrest scenarios
- rewards/gamification integration review: confirm REWARDS can consume challenge-level outcomes, not only session/scenario-level completion

### Phase 5: Neonatal / Newborn Resuscitation

Add a distinct neonatal mode:

- newborn/perinatal scenario trigger
- warm/dry/stimulate/position workflow
- PPV effectiveness challenge
- HR reassessment gates
- 3:1 coordinated compressions/ventilations when indicated
- neonatal oxygen/SpO2 prompts when authored
- neonatal epinephrine/volume escalation when in scope and carried
- neonatal-specific evidence packet and debrief section

### HUD Parity Contract

Adult BLS CPR, pediatric BLS CPR, and neonatal NRP may differ in clinical workflow, but they must stay aligned on shared runtime behavior:

- Use the same `modal-challenge` shell and submit through `/cpr-challenge/response`.
- Return to normal scenario care after ROSC/improvement instead of jumping directly to debrief.
- Record a PCR treatment row for the completed challenge.
- Preserve code/resuscitation-log scroll position while adding new events.
- Block scenario microphone/STT while the challenge modal is open.
- Surface deterministic CPR/NRP feedback in the normal debrief path.

Workflow-specific differences belong inside the algorithm branch only: adult/pediatric CPR owns rhythm cycles, AED actions, pulse-check timing, compression ratio, and shock/no-shock decisions; neonatal NRP owns initial steps, PPV effectiveness, MR SOPA, HR reassessment gates, and 3:1 escalation. Bug fixes to shared modal lifecycle, submission, debrief integration, logging, PCR handoff, mic blocking, or post-challenge return behavior must be applied to both branches and covered by regression tests.

---

## 15. Open Decisions

| Decision | Recommendation |
|---|---|
| First scenario target | Start with BLS AED arrest. It exercises CCF, pause discipline, AED logic, and resume discipline without ALS med complexity. |
| ROSC handling | Resolved for V1: deterministic performance-gated ROSC after 3-5 AHA-compliant cycles with CCF at/above target. Do not make ROSC probabilistic. |
| Failed challenge behavior | Do not block scenario completion. Feed results into scoring/debrief and allow replay. Abandoned active-arrest HUD = 0 for CPR challenge component. |
| Med timing in V1 | Defer. Add only after BLS flow is stable. |
| Termination of resuscitation | Defer unless a scenario declares structured `termination_criteria`; do not accept loose learner-initiated termination as valid. |
| Pediatric team transition | Default is EMS crew of 2 or more using 15:2. Only support 30:2 -> 15:2 transition for explicitly authored single-rescuer exceptions. |
| Manual defib shock joules | Not a Phase 1 issue. AED-only Phase 1 does not score joules; manual defib dosing belongs to Phase 3. |
| Neonatal arrest | Include as Phase 5 neonatal/newborn mode with `algorithm: "neonatal_nrp"`; do not include in Phase 1 BLS AED. |
| Visual style | Use dark station/monitor theme aligned with current V2 UI; do not mimic any third-party app visually. |

---

## 16. Summary

The CPR challenge should be a deterministic, scenario-triggered code-management HUD focused on high-performance CPR. Its strongest instructional value is showing learners that successful resuscitation is not just "knowing the algorithm" but maintaining compression discipline while coordinating rhythm checks, shocks, airway/ventilation, and team actions.

The first implementation should stay narrow: BLS CPR/AED with live CCF, pause timing, rhythm decisions, and a code log. ALS/PALS medication, advanced-airway complexity, and neonatal/newborn resuscitation should come after the core HPCPR loop feels reliable and teachable.
