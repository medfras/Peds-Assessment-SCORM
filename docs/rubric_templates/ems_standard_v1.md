# EMS Standard Rubric — v1

**Template ID:** `ems_standard_v1`  
**Applies to:** Single-provider BLS/ALS pediatric scenarios. This is an authoring scaffold, not a specification — treat the structural framing as a starting point, not a constraint. The taxonomy table below identifies which fields require scenario-specific judgment and which follow a consistent pattern.  
**Last updated:** 2026-04-22

---

## How to use this template

When authoring a new scenario, copy the scaffold below into `scoring_rubric` and fill in every `[AUTHOR: ...]` placeholder. The structural framing (partial/minimal language that is identical across scenarios) is pre-written — do not reword it unless there is a specific clinical reason. Preserve the band label names (`full_credit`, `partial_credit`, `minimal_credit`) and the point values exactly.

This template governs the rubric text only. It does **not** replace scenario-level deterministic scoring metadata. New pediatric scenarios should also:
- define `scene_entry_scoring` for PPE / BSI expectations
- mark scene-entry-only `critical_actions` with `scene_entry_credited: true` (typically scene safety / PPE and PAT)
- add `protocol_indicated` + `evidence` to critical assessments that should become deterministic misses when omitted
- ensure `protocols_treatment` checklist items score the scenario's protocol-defining treatment decision, not optional supportive care

**Taxonomy of what is fixed vs. authored:**

| Part | Status | Rule |
|---|---|---|
| Scoring weights (`max`) | Fixed baseline | Default baseline: clinical_performance 40, narrative 20, treatment/scope bucket 20, dmist 10, professionalism 10. If a scenario splits treatment/scope into both `protocols_treatment` and `scope_adherence`, the effective checklist maxes are authoritative. |
| Band label names | Fixed | Always `full_credit`, `partial_credit`, `minimal_credit` |
| `clinical_performance` all three bands | Scenario-authored | 100% scenario-specific clinical content. No template framing applies. |
| `narrative` full_credit | Scenario-authored | The CHART content is condition-specific. Use the CHART scaffold but fill it fully. |
| `narrative` partial | Structural framing | Use template framing; fill in the specific missing element. |
| `narrative` minimal | Mostly structural | The opener "Narrative present but" is standard. What follows is scenario-specific. For scenarios where the minimal failure is documenting a contraindicated action (not merely omitting content), write it specifically rather than using the template opener. |
| `protocols_treatment` all three bands | Scenario-authored when used | In-scope treatment choices, protocol alignment, contraindicated care, oxygen/medication/positioning decisions, and missed indicated interventions. |
| `scope_adherence` all three bands | Scenario-authored when used | True scope-of-practice/provider-level/MCA-scope issues only: out-of-scope attempts, actions outside effective level, or active refusal of indicated in-scope care due to scope misunderstanding. |
| `dmist` full_credit | Scenario-authored | The D/M/I/S/T values are scenario-specific. Use the DMIST scaffold. |
| `dmist` partial/minimal | Structural framing | Pre-written. Fill in the clinically critical missing element only. |
| `professionalism` full_credit | Scenario-authored | The specific communication actions and family dynamics are scenario-specific. |
| `professionalism` partial | Structural framing | Fill in the specific deficit. |
| `professionalism` minimal | Scenario-authored | **Not verbatim-copyable.** The minimal failure depends on the scene dynamic. For medical scenarios with distressed families the failure is communication absence. For trauma scenarios with family management demands the failure is scene control. For scenarios where the student's clinical judgment is influenced by patient demeanor the failure is dismissiveness. Write to the scene, not to a generic formula. |
| `by_level` all content | Scenario-authored | Level-specific critical focus is entirely condition-specific. |

---

## "Do not template" list

These must remain scenario-authored. Flattening them to template language will erase clinically meaningful nuance:

1. `clinical_performance` — all three bands. This is the clinical heart of the scenario. Every word should reflect the specific condition, patient, critical intervention, and common mistakes for this particular call.
2. The specific drug names, doses, routes, and timing requirements that appear in any band.
3. Level-based `critical_focus` content — what an EMT must do for an asthma exacerbation is different from what an EMT must do for decompensated shock.
4. `protocols_treatment` and `scope_adherence` bands — do not collapse these together. Treatment quality/protocol alignment goes in `protocols_treatment`; true provider-level scope violations go in `scope_adherence`.
5. `professionalism` minimal_credit — the scene dynamic determines what this failure looks like. Do not default to "focused only on clinical tasks." Write to the actual minimal failure: scene control collapse (high-acuity trauma), dismissiveness of patient minimizing (subtle presentation), harsh interaction (altered/frightened patient), or failure to prepare patient for a painful procedure.
6. Patient and family names, specific scene dynamics, and condition-specific communication challenges in `professionalism` full/partial bands.
7. DMIST full_credit D/M/I/S/T values — patient demographics, mechanism, intervention details, current status, and transport plan are all scenario-specific.
8. `narrative` minimal_credit when the minimal failure is documenting a contraindicated action — write it specifically (e.g. "Documents wet dressings applied"), not as a generic omission failure.

## Protocol-defining treatment guardrail

Before authoring `protocols_treatment`, identify the scenario's primary protocol decision: the intervention or safety check that changes patient outcome for this presentation. The required treatment checklist item should match that decision.

Examples:

| Presentation | Required `protocols_treatment` focus | Do not accidentally require as sole treatment score |
|---|---|---|
| Pediatric hypoglycemia with BG < 60 and intact swallow | Oral glucose after eligibility/swallow confirmation | Supplemental O2 when SpO2 is normal and breathing is unlabored |
| Croup with stridor | Least-agitating oxygen, upright caregiver positioning, calm environment, ALS/racepinephrine readiness | Forced mask placement or an oxygen flow that conflicts with local protocol |
| Anaphylaxis | Epinephrine dose/route/timing | O2/positioning alone |
| Asthma exacerbation | Bronchodilator therapy and reassessment | O2 alone when bronchodilator is indicated |

Supportive care can be required when the physiology supports it, but the checklist item must state the indication. Avoid generic language such as "Supplemental O2 applied per protocol" unless O2 is truly required by the scenario state. If O2 is acceptable but not mandatory, place it in `recommended_actions`, grace items, or rubric prose instead of making it the only `protocols_treatment` item.

When a `critical_actions` entry duplicates a checklist item, align the IDs by suffix and add `intervention_ids` or `evidence`. Example: critical action `oral_glucose` should map to checklist item `scenario_id.oral_glucose`; avoid unrelated aliases like `bg_awareness` for `scenario_id.blood_glucose_check`.

---

## Scoring scaffold (copy into scenario `scoring_rubric`)

```json
"scoring_rubric": {
  "clinical_performance": {
    "max": 40,
    "full_credit": "[AUTHOR: Describe all critical actions required for full credit. Name the scene safety step, the PAT or initial impression, the primary assessment finding, the key intervention (with dose/route if applicable), the reassessment step, and any condition-specific clinical decision. This is the most important rubric field — every word should reflect the clinical reality of this specific scenario.]",
    "partial_credit": "[AUTHOR: Describe what constitutes adequate but incomplete management. Name the specific action that is missing or done incorrectly at this band. Usually: primary intervention completed but reassessment missing, or one critical assessment step omitted.]",
    "minimal_credit": "[AUTHOR: Describe critically deficient management. This band describes a student who performed basic scene management but missed the single most important clinical action for this condition. Name that action explicitly.]"
  },
  "narrative": {
    "max": 20,
    "full_credit": "CHART complete: [AUTHOR: dispatch reason], [AUTHOR: presenting condition and key assessment findings — vitals, signs, PAT result], [AUTHOR: key intervention with drug/dose/route/time if applicable], [AUTHOR: patient response to treatment], [AUTHOR: disposition and transport destination or ALS handoff]",
    "partial_credit": "Most CHART elements present but [AUTHOR: name the single most clinically important missing element for this scenario — what the receiving facility or ALS crew needs most] absent or undocumented",
    "minimal_credit": "Narrative present but [AUTHOR: describe the fundamental failure — wrong treatment documented, wrong condition framed, critical assessment finding absent, or intervention with contraindication documented as correct]"
  },
  "protocols_treatment": {
    "max": 20,
    "full_credit": "[AUTHOR: Name the expected in-scope treatment choices, protocol-aligned escalation, contraindicated care avoided, and any condition-specific treatment priorities.]",
    "partial_credit": "[AUTHOR: Name the specific in-scope treatment/protocol gap: suboptimal oxygen method, missed medication/procedure within level, contraindicated care, premature intervention, weak transport/escalation decision, or delayed indicated treatment.]",
    "minimal_credit": "[AUTHOR: Name the severe protocol/treatment failure: key indicated intervention omitted, contraindicated care performed, or treatment plan materially inconsistent with protocol.]"
  },
  "scope_adherence": {
    "max": 20,
    "full_credit": "Stayed within authorized scope for effective provider level and MCA rules; no out-of-scope attempts or orders",
    "partial_credit": "[AUTHOR: Name the specific scope reasoning issue if applicable, such as uncertainty about MCA-expanded scope or failure to recognize an indicated in-scope option because of scope misunderstanding.]",
    "minimal_credit": "[AUTHOR: Name the specific out-of-scope intervention attempted or ordered. If no true scope issue exists in this scenario, omit this category rather than using it for routine treatment quality.]"
  },
  "dmist": {
    "max": 10,
    "full_credit": "D: [AUTHOR: patient name, age or date of birth, sex, weight in kg]; M: [AUTHOR: condition/mechanism, 2–3 key clinical details most important for ALS continuation of care]; I: [AUTHOR: key interventions with drug/dose/route/time and patient response]; S: [AUTHOR: current vitals and status at handoff]; T: [AUTHOR: transport decision, ALS notification, receiving facility if applicable]",
    "partial_credit": "3–4 of 5 DMIST components present; [AUTHOR: name the single most clinically critical missing component for this specific handoff — what an ALS crew cannot safely continue care without] absent",
    "minimal_credit": "2 or fewer DMIST components, or [AUTHOR: name the most critical element] completely absent from handoff"
  },
  "professionalism": {
    "max": 10,
    "scoring_attributes": [
      "empathy — acknowledged patient/family distress, responded with appropriate compassion",
      "communications — clear directions to partner, explained interventions to family, DMIST/CHART readable",
      "teamwork_diplomacy — partner directed specifically and effectively, tasks coordinated",
      "respect — patient and family addressed by name, professional language, patient dignity preserved",
      "patient_advocacy — patient-centered decisions, no unwarranted bias or delays",
      "self_confidence — decisive and clear direction-giving, appropriate clinical certainty"
    ],
    "full_credit": "[AUTHOR: Name 3–4 specific observable professional behaviors for this scenario. Map to the attributes above. Examples: 'Addressed [patient] by name throughout care; explained [key intervention] to [family member] before performing it; acknowledged [family member]'s panic with calm reassurance; directed Alex by specific task name.' Name the concrete scene-specific communication challenge this scenario presents and how it should be met.]",
    "partial_credit": "[AUTHOR: Name the single most common professionalism gap for this scenario — the one attribute that is most likely to be missed while clinical tasks are performed. Examples: 'Patient and family never addressed by name despite knowing both names'; 'Partner never directed — all tasks performed solo'; 'Family member in obvious distress never acknowledged before clinical questions'; 'Partner directions vague and repeated without confirmation.']",
    "minimal_credit": "[AUTHOR: Write the minimal failure that fits this scene dynamic. Do not default to the generic formula. Examples: 'Panicked parent never acknowledged — clinical care performed over family distress without any communication' (high-distress family scene); 'Dismissive of [patient name]'s minimizing — treated as probably fine based on calm demeanor' (subtle presentation); 'Harsh or dismissive interaction with frightened child or confused patient' (altered/pediatric); '[Patient] never addressed by name and interventions performed without explanation' (any procedural scenario). Match the minimal failure to the professionalism risk this call presents.]",
    "_framework_ref": "docs/PROFESSIONALISM_FRAMEWORK.md — NASEMSO 2002 affective domain; Integrity and Careful Delivery of Service scored in narrative and protocols_treatment/scope_adherence respectively"
  }
}
```

---

## Level-based scaffold (copy into scenario `scoring.by_level`)

```json
"by_level": {
  "MFR": {
    "critical_focus": [
      "Scene safety and BSI/PPE prior to patient contact.",
      "[AUTHOR: PAT or initial impression appropriate for this patient presentation]",
      "[AUTHOR: List the highest-priority BLS actions within MFR scope — typically O2, positioning, airway support. MFR scope is more limited than EMT; do not include EMT-only interventions such as albuterol SVN.]",
      "Recognize need for ALS and document ALS status."
    ],
    "additional_expectations": [
      "[AUTHOR: Any additional assessment or history expectations at MFR level. Remove if none beyond critical_focus.]"
    ],
    "grace_items": [
      "[AUTHOR: Items that would be expected at higher scope but are not required at MFR level. What should the AI give credit for attempting even if not required?]"
    ]
  },
  "EMT": {
    "critical_focus": [
      "Scene safety and BSI/PPE.",
      "[AUTHOR: PAT and primary assessment steps]",
      "[AUTHOR: Key EMT-scope interventions in order of priority — name the critical intervention for this condition, including drug/dose/route if applicable]",
      "[AUTHOR: History requirements — OPQRST and SAMPLE or focused history]",
      "[AUTHOR: Reassessment requirement — what must be reassessed and documented after intervention]",
      "[AUTHOR: DMIST preparation or hospital notification if applicable]"
    ],
    "additional_expectations": [
      "[AUTHOR: Anything expected at EMT level beyond the critical_focus list]"
    ],
    "grace_items": [
      "[AUTHOR: Items that EMT should not be penalized for — common errors the AI might flag that are actually acceptable at EMT scope]"
    ]
  },
  "AEMT": {
    "critical_focus": [
      "All EMT expectations above.",
      "[AUTHOR: AEMT-specific scope additions — IV access, additional medications, or expanded assessment. If AEMT scope adds nothing meaningful for this presentation, state that explicitly.]"
    ],
    "additional_expectations": [
      "[AUTHOR: AEMT-level additional expectations. May be empty if AEMT and EMT expectations are identical for this presentation.]"
    ],
    "grace_items": [
      "Same grace items as EMT level."
    ]
  },
  "Paramedic": {
    "critical_focus": [
      "All EMT/AEMT expectations above.",
      "[AUTHOR: Paramedic-specific scope additions — advanced airway, additional drug options, ALS-only assessments, medication dosing nuances, clinical decision criteria for deterioration]"
    ],
    "additional_expectations": [
      "[AUTHOR: Paramedic-level additional expectations — what a Paramedic should recognize or anticipate that lower levels would not be expected to manage]"
    ],
    "grace_items": [
      "Same EMT grace items apply."
    ]
  }
}
```

---

## ALS and transport scenario rubric guidance

This section provides authoring guidance for the scoring dimensions when writing rubrics for ALS-capable or transport-capable scenarios. The fixed weights (40/20/20/10/10) never change — this section only governs what the rubric language should cover in each band.

### `clinical_performance` — ALS and transport additions

When the scenario involves ALS-capable monitoring or a transport phase, the `clinical_performance` bands must explicitly address:

- **Advanced monitoring:** Whether obtaining cardiac monitoring, 12-lead ECG, or capnography was clinically appropriate, and whether the student used it. Full credit requires monitoring obtained when indicated; partial credit if monitoring was available but not used when it would have changed management.
- **Transport decision:** Whether the student made the correct transport decision (load-and-go vs. treat on scene) — scored based on `transport_phase.priority` and `als_phase.indicated`. Full credit requires the correct decision with appropriate rationale; partial credit if the decision was correct but rationale was absent or weak.
- **ALS intercept:** When `als_phase.auto_dispatched: false` and ALS is indicated — did the student recognize and request it? Use the `als_phase.indicated` field to determine whether this is a full-credit, partial-credit, or minimal-credit driver.
- **Transport reassessment:** If the scenario has `transport_phase.reassessment_expectations`, full credit requires evidence of reassessment (in chat, DMIST, or narrative). Do not penalize for reassessment not documented if the student verbalized it in the DMIST.

### `protocols_treatment` — protocol-aligned treatment decisions

Use `protocols_treatment` for in-scope treatment quality: oxygen method, medication/procedure selection within the student's level, contraindicated care, missed indicated interventions, positioning, calming measures, and protocol-aligned escalation decisions. Do not score these as scope violations unless the student attempted or ordered care outside their effective level.

### `scope_adherence` — ALS-only interventions

When the scenario includes ALS-only interventions (IV/IO access, advanced airway, antiarrhythmics, vasopressors, etc.), the `scope_adherence` bands should name the specific ALS-only interventions that are out of scope for the student's effective level. Use `out_of_scope_bls` / `out_of_scope_aemt` vocabulary IDs. Routine missed treatment, suboptimal oxygen choices, or contraindicated-but-in-scope care belongs in `protocols_treatment`, not `scope_adherence`.

### `dmist` — turnover-target-conditional framing

The `dmist` scoring dimension covers "patient turnover / verbal report" — the specific framing depends on `turnover_target`:

- **`turnover_target: "als"`** — Standard DMIST framing. Evaluate D, M, I, S, T components for completeness and clinical usefulness to an ALS crew. Full credit: all 5 components present with ALS-continuation-relevant content. Partial: 3–4 components. Minimal: ≤2 or critical missing element.
- **`turnover_target: "hospital"`** — Evaluate the pre-arrival radio report and receiving-facility verbal handoff. Full credit: patient demographics, chief complaint, mechanism/etiology, current vitals, interventions and response, ETA, any activation flag. Partial: 3–4 of those elements. Minimal: ≤2 or no pre-arrival communication evidence.
- **`turnover_target: "none"`** — Mark the section not applicable. The `"dmist": 0` subscore returned in this case is an N/A result, not a performance failure. The rubric `full_credit` / `partial_credit` / `minimal_credit` text should note this explicitly so the student does not misread a zero as a graded miss.
- **`turnover_target: "dynamic"`** — Write rubric language that covers both ALS and hospital framing, then note that the debrief will conditionally apply one based on the resolved value at runtime.

The DMIST scaffold in the scoring scaffold section applies to all turnover targets — authors should adapt the D/M/I/S/T template language for the specific receiving party (ALS crew vs. hospital charge nurse).

### `narrative` — transport T element

For transport scenarios, the CHART `T` (Transport/Transfer) element should cover:
- **ALS handoff:** who the patient was transferred to, condition at handoff
- **Hospital transport:** destination, patient condition en route, any pre-arrival communication made, disposition at receiving facility

The rubric `full_credit` band for narrative should specify which of these applies. The `partial_credit` opener ("Most CHART elements present but...") should name the transport/disposition element if it is the most likely missing piece for this scenario.

---

## Override contract

A scenario may override any field in this template with scenario-specific language. There is no override syntax — simply replace the pre-written framing with your scenario-specific content if needed. The template framing is a starting point that prevents drift, not a constraint that prevents specificity.

Override examples that are **not** appropriate:
- Changing `dmist` point value away from 10.
- Adding a sixth scoring dimension.
- Changing band labels (`full_credit` etc.) to non-standard names.
