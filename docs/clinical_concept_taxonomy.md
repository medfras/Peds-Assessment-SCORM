# Clinical Concept Taxonomy and Intervention Action IDs

**Status:** SME reviewed — approved with revisions addressed for vocabulary contract; production prompt/scoring wiring remains gated.
**Last Updated:** 2026-05-03
**Canonical code registry:** `app/scenarios/vocabulary.py`
**Protocol concept index:** `app/protocol_concept_index.py`

---

## 1. Purpose

This document defines the stable IDs Phase 2 will use for protocol tree-shaking, scenario tagging, local SOP tagging, and deterministic scope analysis.

The key design rule is simple:

**Clinical concept IDs describe what the scenario/protocol is about. Intervention action IDs describe what the student did.**

Do not use display labels, protocol prose, or button text as authoritative identifiers. Labels can change; IDs must remain stable.

**Current authority limit:** The vocabulary contract has SME approval after the 2026-05-03 revisions below. Tags and action IDs may still only feed production scoring, Medical Control, debrief deductions, or production prompt excerpts after Phase 2B wiring is implemented, tested, and explicitly enabled. Existing preview/admin tooling remains non-authoritative.

---

## 2. Authority Boundaries

| Concern | Uses | Authority |
|---|---|---|
| Scenario/protocol relevance | `clinical_context.concepts`, protocol node tags, SOP tags | `CLINICAL_CONCEPTS` |
| Scope analysis | intervention events, protocol scope tables, debrief scope facts | `INTERVENTION_ACTIONS` |
| UI button labels | `vitals.interventions` | `INTERVENTIONS` |
| Existing BLS out-of-scope scenario hints | `correct_treatment.out_of_scope_bls` | `OUT_OF_SCOPE` |

`INTERVENTION_ACTIONS` and `INTERVENTIONS` are related but not identical. A single action can map to multiple UI interventions, and some future action IDs may not have a one-click UI equivalent.

Example:

```text
Action ID: oxygen_supplemental
Maps to UI intervention IDs: o2_supplemental, o2_nc, o2_blowby
```

---

## 3. ID Format

- IDs are flat `snake_case`.
- IDs are stable once used in production data.
- Do not use dot notation.
- Do not include jurisdiction names in IDs unless the concept is inherently jurisdictional.
- Prefer clinical meaning over UI phrasing.

Good:

```text
anaphylaxis
pediatric_respiratory_distress
epinephrine_im_administer
spinal_motion_restriction_apply
```

Avoid:

```text
kent_county_epi_rule
click_epi_button
MI_protocol_04_5
```

---

## 4. Clinical Concept Tags

Clinical concepts are used to match a scenario, protocol node, or SOP rule to the relevant clinical domain.

### Current Initial Registry

| Category | Concept IDs |
|---|---|
| Assessment | `scene_safety`, `ppe_precautions`, `primary_survey`, `patient_assessment`, `vital_signs` |
| Operations | `transport_decision`, `medical_control`, `documentation_handoff` |
| Infectious Disease / Operations | `sepsis`, `infectious_disease_precautions` |
| Airway / Breathing | `airway_management`, `oxygen_therapy`, `ventilation_support`, `respiratory_distress`, `bronchospasm`, `pulmonary_edema`, `croup`, `upper_airway_obstruction`, `foreign_body_airway_obstruction`, `tension_pneumothorax` |
| Cardiovascular | `cardiac_arrest`, `chest_pain_acs`, `stemi`, `syncope`, `stroke`, `bradycardia`, `tachycardia`, `shock`, `cardiac_monitoring` |
| Neurologic | `altered_mental_status`, `seizure`, `febrile_seizure` |
| Metabolic | `hypoglycemia`, `blood_glucose` |
| Toxicology | `toxins_overdose`, `opioid_overdose` |
| Behavioral / Psychiatric | `behavioral_psychiatric_crisis`, `severe_agitation`, `chemical_restraint` |
| Obstetrics / Gynecology | `obstetric_emergency`, `imminent_delivery`, `neonatal_resuscitation`, `postpartum_hemorrhage`, `preeclampsia_eclampsia` |
| Allergy / Immunology | `anaphylaxis`, `allergic_reaction` |
| Trauma | `trauma`, `bleeding_control`, `soft_tissue_injury`, `extremity_injury`, `fracture_splinting`, `burns`, `spinal_motion_restriction`, `head_injury`, `abdominal_trauma`, `multisystem_trauma` |
| Environmental | `hypothermia`, `hypothermia_prevention`, `frostbite`, `heat_illness`, `heat_exposure` |
| Pediatrics | `pediatric_patient`, `pediatric_respiratory_distress`, `pediatric_cardiac_arrest`, `pediatric_trauma`, `child_abuse_neglect` |
| Operations / System | `interfacility_transfer`, `quality_improvement_review` |

The machine-readable registry lives in `CLINICAL_CONCEPTS` in `app/scenarios/vocabulary.py`.

---

## 5. Scenario Tagging Contract

Phase 2 scenarios should add a top-level `clinical_context` block:

```json
{
  "clinical_context": {
    "jurisdiction": "national",
    "concepts": [
      "pediatric_patient",
      "pediatric_respiratory_distress",
      "upper_airway_obstruction"
    ],
    "protocol_focus": [
      "airway_management",
      "oxygen_therapy"
    ]
  }
}
```

### Field Rules

| Field | Required? | Meaning |
|---|---:|---|
| `jurisdiction` | Yes in Phase 2 | `national`, state code such as `MI`, or a future agency/profile-specific marker |
| `concepts` | Yes in Phase 2 | Broad clinical tags for protocol/SOP relevance |
| `protocol_focus` | Optional | Narrower tags used when a broad scenario could otherwise pull too much protocol content |

### Authoring Rules

- Use enough tags to identify the clinical problem, not every possible differential.
- Include `pediatric_patient` for pediatric cases.
- Use `national` when the case is clinically portable across jurisdictions.
- Use state/jurisdiction tags only when the scenario depends on a jurisdiction-specific protocol rule.
- Use `interfacility_transfer` for IFT scenarios where staffing level, facility-initiated infusions, transport acceptance/refusal, or scope during transfer is part of the teaching objective.
- Use `quality_improvement_review` only when the scenario/debrief intentionally needs QI/PSRO/protocol-deviation consequences surfaced. Do not make QI policy score-bearing by default.

---

## 6. Protocol Tagging Contract

Protocol JSON nodes now have an initial indexed tag retrofit for the current scenario-relevant subset. These tags are mirrored from the static mapping layer and are **not SME-final**.

| Option | Description | Tradeoff |
|---|---|---|
| Inline tags | Add `clinical_context.concepts` directly to protocol JSON nodes | Most explicit; highest authoring work |
| Derived index | Build concept-to-protocol mappings at compile time | Keeps protocol files cleaner; index logic must be validated |
| Static mapping layer | Maintain a separate mapping file | Fastest to pilot; easiest to drift |

**Current pilot decision:** use the static mapping layer in `app/protocol_concept_index.py` as the source for the initial protocol JSON tag retrofit.

Reason: protocol JSON files are still provisional and the concept/action taxonomy has not yet been validated against enough real scenarios. A static index lets Phase 2 tree-shaking be tested while keeping tag provenance clear. The indexed protocol files now carry:

```json
"clinical_context": {
  "concepts": ["..."],
  "tag_source": "initial_static_mapping",
  "sme_review_status": "pending"
}
```

Current coverage:

- 48 Michigan protocol files tagged from the static index
- 19 NASEMSO protocol files tagged from the static index
- Remaining protocol files are intentionally untagged until either they become scenario-relevant or a full SME tagging pass is scheduled

Drift control:

- Every concept referenced by the static index must exist in `CLINICAL_CONCEPTS`.
- Every protocol ID referenced by the static index must exist in the MI or NASEMSO base sets.
- Every indexed protocol file must carry `clinical_context.concepts` matching the static index, with `tag_source: "initial_static_mapping"` and `sme_review_status: "pending"`.
- Tests enforce these conditions.

---

## 7. Intervention Action IDs

Intervention action IDs normalize what the learner did for scope classification. They are the bridge between UI events, protocol scope permissions, and evidence-packet scope facts.

Examples from the initial registry:

| Action ID | Meaning | Example UI Intervention IDs |
|---|---|---|
| `oxygen_supplemental` | Apply supplemental oxygen | `o2_supplemental`, `o2_nc`, `o2_blowby` |
| `oxygen_high_flow_nrb` | Apply high-flow oxygen by NRB | `high_flow_o2`, `o2_nrb` |
| `ventilation_bvm` | Provide BVM ventilation | `bvm` |
| `cpr_initiate` | Initiate CPR | Future cardiac arrest UI |
| `pulse_check` | Check pulse | Future cardiac arrest / assessment UI |
| `aed_apply_use` | Apply/use AED | Future cardiac arrest UI |
| `oral_airway_opa_insert` / `opa_insert` | Insert oral airway / OPA | Future airway adjunct UI |
| `nasal_airway_npa_insert` / `npa_insert` | Insert nasal airway / NPA | Future airway adjunct UI |
| `supraglottic_airway_insertion` | Insert supraglottic airway | Future ALS/AEMT UI |
| `supraglottic_airway_insert` | Insert supraglottic airway | Alias for future scope analysis compatibility |
| `endotracheal_intubation` | Perform endotracheal intubation | Future paramedic UI |
| `cricothyrotomy` | Perform cricothyrotomy | Future surgical/needle airway UI |
| `albuterol_administer` | Administer albuterol | `albuterol_svn`, `albuterol_mdi_patient_assisted` |
| `epinephrine_im_administer` | Administer IM epinephrine | `epinephrine_im`, `epi_draw_up` |
| `naloxone_administer` | Administer naloxone | `naloxone_in`, `naloxone_im` |
| `narcotic_analgesia_administer` | Administer narcotic analgesia | Future analgesia UI |
| `benzodiazepine_administer` | Administer benzodiazepine | Future seizure/sedation UI |
| `antiarrhythmic_administer` | Administer antiarrhythmic | Future cardiac UI |
| `blood_glucose_check` | Check blood glucose | `blood_glucose_check` |
| `intravenous_access_establish` | Establish IV access | Future ALS/AEMT UI |
| `intraosseous_access_establish` | Establish IO access | Future ALS/AEMT UI |
| `cardiac_monitor_apply` | Apply cardiac monitor | `ekg_monitoring` |
| `twelve_lead_ecg_acquire` | Acquire 12-lead ECG | `12_lead_ecg` |
| `waveform_capnography_apply` | Apply waveform capnography | `waveform_capnography` |
| `defibrillation_aed` | Defibrillate using AED | Future cardiac arrest UI |
| `defibrillation_manual` | Defibrillate manually | Future ALS UI |
| `synchronized_cardioversion` | Perform synchronized cardioversion | Future ALS UI |
| `transcutaneous_pacing` | Perform transcutaneous pacing | Future ALS UI |
| `bleeding_control_direct_pressure` | Control bleeding with direct pressure | `direct_pressure` |
| `tourniquet_apply` | Apply tourniquet | Future hemorrhage-control UI |
| `wound_packing_hemostatic` | Pack wound with hemostatic gauze | Future hemorrhage-control UI |
| `chest_seal_apply` | Apply chest seal | Future penetrating chest trauma UI |
| `splint_apply` | Apply splint | `splinting` |
| `traction_splint_apply` | Apply traction splint | Future femur-fracture UI |
| `spinal_motion_restriction_apply` | Apply spinal motion restriction | `smr` |
| `rapid_transport_initiate` | Initiate rapid transport | `rapid_transport`, `load_and_go` |
| `pat_perform` | Perform Pediatric Assessment Triangle | Future pediatric assessment UI |

The complete machine-readable registry lives in `INTERVENTION_ACTIONS` in `app/scenarios/vocabulary.py`.

---

## 8. Scope Classification Output

Scope analysis must return one of the classifications already recorded in `multi_tenant_protocol_architecture.md`:

| Classification | Meaning |
|---|---|
| `in_scope` | Allowed and appropriate for this provider level |
| `out_of_scope` | Above the provider's licensure level |
| `requires_medical_control` | Allowed only with prior medical control authorization |
| `not_carried` | In scope but unavailable per agency equipment configuration |
| `not_indicated` | In scope but not appropriate for this clinical presentation |
| `contraindicated` | Clinically incorrect regardless of scope |
| `available_but_not_expected` | In scope and available, but not required by this scenario |

Do not use `below_scope`.

---

## 9. Implementation Sequence

1. Create this taxonomy and code registry. **Complete for initial Phase 2 contract.**
2. Choose the protocol tagging strategy. **Complete for pilot: static mapping layer.**
3. Add `clinical_context` and `jurisdiction` tags to existing scenarios. **Initial current-library pass complete.**
4. Tag or index protocol nodes. **Initial static index and indexed protocol JSON tag retrofit complete for pilot; full SME-final corpus tagging deferred.**
5. Add validation for scenario `clinical_context.concepts`. **Test coverage exists; runtime enforcement deferred.**
6. Build protocol tree-shaking from scenario concepts to protocol excerpt. **Non-authoritative preview helper and admin preview endpoint exist; production use deferred until SME review.**
7. Build intervention action mapping in the evidence packet.
8. Add deterministic scope classification against the resolved protocol profile.

Steps 7-8 are intentionally deferred until Phase 2B wiring is ready. The concept/action ID contract has been revised after SME review, but production use still requires implementation tests and an explicit enablement decision.

---

## 10. SME Review Package

SME review is the release gate that turns these IDs/tags from design-validation metadata into production-authoritative inputs. The initial vocabulary contract has been reviewed and revised, but current admin previews remain non-authoritative until Phase 2B production wiring is complete.

### Review Inputs

| Artifact | Purpose |
|---|---|
| `docs/clinical_concept_taxonomy.md` | Human-readable taxonomy, tagging contract, and review criteria |
| `app/scenarios/vocabulary.py` | Machine-readable `CLINICAL_CONCEPTS` and `INTERVENTION_ACTIONS` registries |
| `app/protocol_concept_index.py` | Static protocol-to-concept mapping used by preview/tree-shaking prototypes |
| Scenario JSON `clinical_context` blocks | Scenario-level relevance tags and protocol focus tags |
| Protocol JSON `clinical_context` blocks | Initial mirrored protocol tags with `sme_review_status: pending` |
| MCA/Protocols admin preview panel | Visual review aid for scenario-to-protocol matches |

### Review Questions

- Are the clinical concept IDs clinically meaningful, stable, and broad/narrow enough for protocol relevance filtering?
- Are any needed concepts missing for the current scenario library?
- Are any concepts too broad and likely to pull unsafe or noisy protocol context?
- Do intervention action IDs map cleanly to what learners can actually do in the simulator?
- Are action IDs granular enough for scope classification without becoming display-label aliases?
- Are scenario `clinical_context.concepts` and `protocol_focus` tags clinically accurate?
- Do protocol mappings include the protocol sections/medication references a provider would reasonably need for each scenario?
- Do any preview matches reveal over-inclusion that would bloat prompts or under-inclusion that would omit clinically important protocol context?
- Are any tags jurisdiction-specific when they should be national/portable?

### Acceptance Criteria

- `CLINICAL_CONCEPTS` approved for production use or unresolved concepts listed with required edits.
- `INTERVENTION_ACTIONS` approved for production use or unresolved action IDs listed with required edits.
- Current scenario tags approved or corrected.
- Static protocol mappings approved for initial authoritative tree-shaking or replaced by a reviewed inline/derived mapping strategy.
- Indexed protocol JSON tags either approved and moved beyond `sme_review_status: pending`, or left pending with production use blocked.
- Any disagreement between scenario tags and protocol mappings is documented before implementation proceeds.

### Sign-Off Record

| Field | Value |
|---|---|
| Reviewer | Emergency Medical Physician / EMS Medical Director |
| Review date | 2026-05-03 |
| Review status | Approved with revisions |
| Revisions addressed | Added missing OB/GYN, behavioral/psychiatric, infectious disease/sepsis concepts; added pulmonary edema, croup, tension pneumothorax, cardiac arrest, stroke, bradycardia, tachycardia, hypothermia, frostbite, and heat illness concepts; added ALS airway, BLS airway adjunct, resuscitation, vascular access, electrical therapy, hemorrhage-control, chest-seal, traction-splint, pediatric assessment, and high-risk medication action IDs. |
| Approved for authoritative prompt excerpts? | Vocabulary contract approved; production excerpt wiring still requires Phase 2B implementation/tests and explicit enablement. |
| Approved for deterministic scoring/scope analysis? | Vocabulary contract approved; deterministic scope analysis still requires Phase 2B implementation/tests and explicit enablement. |
| Follow-up issues | Move from static mapping to inline protocol JSON tags for Phase 2B where practical; legacy `high_flow_o2` remains loadable but now aliases to canonical `o2_nrb` for future evidence-packet matching; consider splitting positioning actions as scenario UI evolves; continue SME review for future state/base protocol expansions. |
