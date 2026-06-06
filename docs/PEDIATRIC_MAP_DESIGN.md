# Pediatric Map Design — RescueTrails Progression

**Project:** RescueTrails with Lexi  
**Status:** Active Design  
**Last Updated:** 2026-04-28 (Scout's Toy Quest overhaul: treat-purchase mechanic, 2-key structure, PM1/PT1 as mini-game gateways, scenario redistribution to branches)  

---

## 1. Overview

The pediatric district in RescueTrails is a structured, prerequisite-gated progression spanning three levels: an entrance map, six medical branches and seven trauma branches, and a two-stage advanced emergency convergence.

**Core Principles:**
- **Single Entrance**: Map 0 introduces all core pediatric mechanics before branching.
- **Parallel Tracks**: Medical (PM1–PM6) and Trauma (PT1–PT7) tracks unlock independently from Map 0.
- **Path-Gated Progression**: Each path between maps is blocked by a single designated scenario. Completing that scenario opens the path and makes the destination map accessible. Students do not need to finish every scenario on a map before advancing — just the gate scenario for the path they want to take.
- **Scout's Toy Quest**: Scout's Toy Shops appear at five nodes across the map. Completing a map triggers a Scout notification; the player purchases that map's toy at any shop using treats earned through scenarios, challenges, and mini-games. Collecting all medical-track toys unlocks the Medical Key at PM7; collecting all trauma-track toys unlocks the Trauma Key at PT8. PE1 requires both keys. See §3 for full Toy Quest rules.
- **Mini-Game Priming**: Each map has one mini-game placed before the first scenario, activating the target clinical concept.
- **Difficulty Ramp**: Beginner (Map 0, PM1, PT1) → Intermediate (PM2–PM6, PT2–PT7) → Advanced (PE1, PE2).

---

## 2. Existing Scenario Placement

All existing scenarios are placed before new content is authored.

### Medical Scenarios

| Scenario ID | Title | Map Placement |
|---|---|---|
| `peds_croup_01` | Croup — 10-Month-Old Female | Map 0 (Entrance) |
| `peds_diabetic_emergency_01` | Diabetic Emergency — 8-Year-Old Male | Map 0 (Entrance) |
| `peds_asthma_01` | Asthma — 4-Year-Old Male | PM2 (Respiratory/Airway) |
| `peds_febrile_seizure_01` | Febrile Seizure — 2-Year-Old Female | PM4 (AMS/Behavioral) — branch intro case |
| `peds_syncope_01` | Syncope — 14-Year-Old Female | PM3 (Cardiac/AMS) — branch intro case |
| `peds_anaphylaxis_01` | Anaphylaxis — 8-Year-Old Male | PM2 (Respiratory/Airway) |

### Trauma Scenarios

| Scenario ID | Title | Map Placement |
|---|---|---|
| `peds_trauma_01_soft_tissue` | Soft Tissue — Scalp Laceration | Map 0 (Entrance) |
| `peds_trauma_02_partial_choking` | Partial Airway Obstruction | Map 0 (Entrance) |
| `peds_trauma_03_extremity` | Extremity Fracture | PT3 (Neuro/Airway) — branch intro case |
| `peds_trauma_04_burn` | Burns — 2-Year-Old | PT4 (Environmental & Toxins) — branch intro case |
| `peds_trauma_05_auto_ped` | Auto-Pedestrian — 7-Year-Old | PT3 (Neuro/Airway) |
| `peds_trauma_06_handlebar` | Handlebar Abdominal Injury — 9-Year-Old | PT2 (Blunt Force/Bleeding Control) |

---

## 3. Scout's Toy Quest

Scout is a shopkeeper character who runs a chain of toy shops across the Puppy Park district. His shops appear at five nodes on the map: the entrance fork (introduction), the medical and trauma mid-point hubs (purchases), and the two convergence nodes where keys are awarded.

### How the Quest Works

1. **Earn toys with treats.** Completing a map (mini-game or final scenario) triggers a Scout notification: "A new toy is available at Scout's shop!" The player travels to any Scout shop location and purchases the toy using treats. Treats are earned through scenario completions, challenge bonuses, and mini-game scores.
2. **No buyback.** Toys cannot be sold back. Treat farming through resale is not possible.
3. **Collect all toys → get the key.** At the convergence shops (PM7 for medical, PT8 for trauma), Scout checks the player's Toy Chest. When all toys for that track are present, Scout congratulates the player and awards the track key. The key unlocks PE1 (both keys required).
4. **Toys are kept.** All purchased toys remain in the player's personal Toy Chest permanently after purchase.

### Treat Economy Note

Treat earn rates must be calibrated so a student completing each map through normal play accrues enough treats to purchase that map's toy without surplus grinding. Target: one map's worth of treats per map completed. This is a balance requirement before ship.

### Existing Implementation

Scout's shop modal, SVG avatar, dialogue system, treat display, Toy Chest, and the purchase/deduct-treats flow are **already fully built** in `static/index.html` and `static/js/app.js`. No new UI components are needed for the shop itself. The `is_new_arrival` series flag on the Toy Chest already exists and can drive the "new toy available" badge/notification.

The current toy grant system uses **probabilistic drops** from `_process_toy_grants` (random chance per scenario completion). The pediatric progression system requires **deterministic map-linked toys** — one specific toy becomes available to purchase after each map is completed. This is the primary backend work needed: map completion must flag the relevant toy as purchasable for that user, and the shop API must filter availability accordingly. The random-drop system for other districts can remain unchanged.

No "sell" or buyback button exists in the shop. Duplicate purchases already return treats (existing behavior) — this is fine and intentional. No code change needed on buyback.

### Shop Locations and Purpose

| Node | Shop Type | Purpose |
|---|---|---|
| Map 0 — Entrance fork | Introduction shop | Scout introduces himself and the Toy Quest; shows empty Toy Chest; no purchases yet |
| PM3 — Medical mid-point | Purchase shop | Toy purchases available for any notified toys the player hasn't yet bought |
| PT3 — Trauma mid-point | Purchase shop | Toy purchases available for any notified toys the player hasn't yet bought |
| PM7 — Medical convergence | Key award shop | Scout verifies all 6 medical-track toys are in Toy Chest; awards Medical Key |
| PT8 — Trauma convergence | Key award shop | Scout verifies all 7 trauma-track toys are in Toy Chest; awards Trauma Key |

PE1 unlocks when both the Medical Key and Trauma Key have been awarded.

### Toy Inventory

One toy is associated with each map completion. Medical-track toys (6 total, one per PM1–PM6) are verified at PM7; trauma-track toys (7 total, one per PT1–PT7) are verified at PT8. Each toy's name and design anchor directly to the clinical domain of its source map.

**Medical-track toys — verified at PM7:**

| Toy Name | Design Concept | Clinical Anchor | Awarded after |
|---|---|---|---|
| Milestone Measuring-Stick Chew | Rubber chew shaped like a pediatric length-based tape / growth chart | Developmental stages, pediatric sizing | PM1 mini-game |
| Breathing Bear Squeaker | Plush bear that squeaks when squeezed | Airway obstruction, wheeze, stridor | PM2 |
| Heartbeat Hound Plush | Plush dog with stitched heart and ECG rhythm across chest | Arrhythmias, syncope, cardiac output | PM3 |
| Brain-Teaser Puzzle Ball | Colorful interlocking puzzle ball (Kong-style enrichment toy) | AMS, psychiatric presentation, neurological differentials | PM4 |
| Thermometer Tug-Rope | Tug rope with plush thermometer reading high fever on one end | Infectious illness, febrile presentations | PM5 |
| Guardian Retriever Plush | Noble Golden Retriever in a safety shield / patrol harness | Mandatory reporting, patient advocacy, scene documentation | PM6 |

**Trauma-track toys — verified at PT8:**

| Toy Name | Design Concept | Clinical Anchor | Awarded after |
|---|---|---|---|
| Patchwork Puppy Plush | Plush puppy stitched in colored patches mapping Rule of Nines body regions | BSA estimation, trauma fundamentals | PT1 mini-game |
| Tourniquet Tug-Rope | Woven rope styled as a tactical tourniquet and pressure bandage | Hemorrhage control, blunt trauma | PT2 |
| C-Collar Corgi Plush | Plush Corgi wearing a fitted, rigid cervical collar | Spinal motion restriction, GCS, traumatic airway | PT3 |
| Cooling-Vest Dachshund | Plush dog in a bright blue reflective cooling vest | Burns, heat emergencies, toxicological exposures | PT4 |
| Traction-Splint Fetch Stick | Fetch stick styled as a Hare/Sager traction splint | Femur fracture, vascular compromise, hemorrhagic shock | PT5 |
| Life-Preserver Ring Toy | Classic red-and-white nautical life preserver throw ring | Submersion injury, hypoxia, thoracic trauma | PT6 |
| Snow-Rescue St. Bernard | St. Bernard plush with iconic neck barrel styled as a warming flask | Hypothermia, frostbite, animal bites, environmental emergencies | PT7 |

### Keys

Keys are visually and mechanically distinct from toys — metallic, EMS-themed objects that don't appear in the Toy Chest. They occupy a separate "Key Ring" UI element.

| Key | Name | Design | Awarded at | Requirement |
|---|---|---|---|---|
| Medical Key | The Golden Stethoscope Key | Metallic gold key; bow shaped as stethoscope earpieces and bell | PM7 — Scout's key award shop | All 6 medical-track toys in Toy Chest |
| Trauma Key | The Silver Trauma Shears Key | Sleek silver key; handle styled as bent EMS trauma shear handles | PT8 — Scout's key award shop | All 7 trauma-track toys in Toy Chest |

Both keys are required to unlock PE1.

### Visual Identity

- The Toy Chest UI shows purchased toys and empty silhouette slots for toys not yet purchased
- The Key Ring UI shows two slots (Medical Key, Trauma Key) — empty metallic outlines until awarded
- Scout's shop at PM7 and PT8 shows a toy checklist filling in as Scout verifies each item before awarding the key
- Toy names and clinical anchors are surfaced in the Toy Chest card tooltips so students can connect their collection to what they learned

---

## 4. Map 0 — Entrance

**Category:** `pediatric_entrance`  
**Theme:** Pediatric Assessment Fundamentals  
**Prerequisites:** None  
**Difficulty:** Beginner  

**Mini-game:** PAT Doorway Dash *(existing)*  
**Scout's Toy Shop:** Introduction shop at the fork. Scout greets the student, explains the Toy Quest, and shows the key ring UI. No purchases, exchanges, or key delivery available yet.

**Scenarios:**
- `peds_croup_01` — respiratory distress basics, hands-off approach, PAT
- `peds_diabetic_emergency_01` — AMS, blood glucose, oral glucose
- `peds_trauma_01_soft_tissue` — hemorrhage control, wound management
- `peds_trauma_02_partial_choking` — partial airway obstruction, back blows/thrusts

**Temporary QA nodes:** Map 0 also carries CPR verification launch nodes for `adult_cardiac_arrest_01_bls`, `peds_cardiac_arrest_01_bls`, and `newborn_resus_01_nrp` until the CPR HUD has automated browser coverage. These are test access points only and are not part of the pediatric progression contract.

**Focus:** Core pediatric assessment mechanics, PAT, scene approach. Introduces both medical and trauma presentation types before the tracks split.

**Unlocks:** PM1 and PT1 (parallel — learner chooses which track to start). Each outgoing path from Map 0 is gated by a single designated scenario.

---

## 5. Medical Track (PM1–PM7)

All medical maps require Map 0 completion. PM2–PM7 have additional intra-track prerequisites as noted. Each path between maps is blocked by one designated scenario on the source map.

---

### PM1 — Intro Medical

**Category:** `pediatric_medical`  
**Theme:** Introduction to Pediatric Medical Assessment  
**Prerequisites:** Map 0  
**Difficulty:** Beginner  

**Mini-game:** Lexi's Development Toy Box *(existing — Dev Sort)*  
**Scenarios:** None — PM1 is a mini-game-only gateway node.  
**Scout's Toy Quest:** Completing the PM1 mini-game triggers the first medical toy notification (Medical Toy 1).

**Gateway mechanic:** Completing the Dev Sort mini-game unlocks PM2, PM3, and PM4 simultaneously. All three branches open at once; the learner chooses where to start.

> **Scenario redistribution note:** `peds_febrile_seizure_01`, `peds_syncope_01`, and the Allergic Reaction scenario have moved to PM4, PM3, and PM2 respectively, where their clinical themes align with each branch. PM1 is intentionally scenario-free so the three branches each begin with an accessible introductory case.

**Unlocks:** PM2, PM3, PM4 (all unlock on mini-game completion).

---

### PM2 — Respiratory/Airway

**Category:** `pediatric_medical_resp`  
**Theme:** Advanced Respiratory Presentations  
**Prerequisites:** PM1  
**Difficulty:** Intermediate  

**Mini-game:** Sound Check *(lung sound identification — audio extension of PAT swipe engine)*  
**Scenarios:**
- *(New)* Allergic Reaction — mild allergic reaction (urticaria only, no anaphylaxis); watchful waiting, scope decision, observation vs. transport *(branch introductory case — moved from PM1)*
- `peds_asthma_01` — moderate asthma exacerbation; albuterol SVN, nebulizer setup, SpO2 monitoring, ALS triggers
- *(New)* Epiglottitis — critical differentiation from croup (drooling, tripod, high fever, no bark, hands-off management)
- `peds_anaphylaxis_01` — respiratory-dominant anaphylaxis, epinephrine timing, wheeze vs. stridor

> **Authoring note for `peds_asthma_01`:** The scenario JSON must include explicit `overall_considerations` confirming this is a moderate presentation, and a tight `out_of_scope_bls` list blocking Magnesium Sulfate, Epinephrine (systemic), and CPAP unless the patient deteriorates to a defined threshold. The AI must not reward ALS-level interventions for a patient who is alert, talking in short sentences, and maintaining SpO2 ≥ 90% on O2.

> **Progression note:** Allergic Reaction → Anaphylaxis is an intentional severity ramp within PM2 — urticaria-only first, then anaphylaxis. The mild allergic reaction serves as the branch entry case before patients start decompensating.

**Focus:** Allergic spectrum (mild → anaphylaxis), respiratory pathology differentiation (asthma vs. anaphylaxis vs. croup vs. epiglottitis), airway management, ALS handoff criteria for respiratory failure.

---

### PM3 — Cardiac/AMS

**Category:** `pediatric_medical_cardiac`  
**Theme:** Cardiac Emergencies and Circulatory Compromise  
**Prerequisites:** PM1  
**Difficulty:** Intermediate  

**Mini-game:** Shock Spotter *(compensated vs. decompensated shock identification — PAT swipe engine)*  
**Scout's Toy Shop:** Purchase shop. Toy purchases available for any notified toys the player hasn't yet bought.

**Scenarios:**
- `peds_syncope_01` — adolescent syncopal episode, vasovagal vs. cardiac differential, prodrome history, supine positioning, glucose check, ALS decision *(branch introductory case — moved from PM1; authored 2026-04-24)*
- *(New)* Pediatric Bradycardia — symptomatic bradycardia with poor perfusion, congenital history, ALS priority
- *(New)* Pediatric Tachycardia — SVT vs. sinus tachycardia, perfusion assessment, vagal maneuver, ALS
- *(New)* Pediatric Sepsis — early sepsis recognition (fever + tachycardia + altered behavior + poor perfusion without obvious source), transport priority

> **Progression note:** Syncope is the branch entry case — it establishes vasovagal/cardiac differential and foundational cardiovascular assessment before the patient acuity escalates in subsequent scenarios.

**Focus:** Pediatric cardiovascular assessment spectrum (syncope → bradycardia → tachycardia → septic shock), recognition of shock states with preserved BP (compensated shock), rhythm recognition at BLS level, ALS handoff under circulatory compromise.

**Unlocks:** PM7 (convergence node). Path gated by one designated scenario.

---

### PM4 — AMS/Behavioral

**Category:** `pediatric_medical_ams_behavioral`  
**Theme:** Altered Mental Status and Behavioral Emergencies  
**Prerequisites:** PM1  
**Difficulty:** Intermediate  

**Mini-game:** Differential Dash — AMS Edition *(sorting game: match presentation to AMS etiology — metabolic, neurologic, behavioral, toxic)*  
**Scenarios:**
- `peds_febrile_seizure_01` — post-ictal AMS, seizure management, fever workup *(branch introductory case — moved from PM1)*
- *(New)* Meningitis — meningeal signs, photophobia, petechiae, non-blanching rash, aggressive transport framing
- *(New)* Suicidal Adolescent — safe scene approach, risk assessment framing, 5150/mental health hold, caregiver dynamics
- *(New)* Unattended teen refusal — minor refusing care without caregiver present, mature minor doctrine framing, medical control consultation, documentation, provider safety and liability considerations

> **Progression note:** Febrile Seizure is the branch entry case — it introduces AMS in a relatively controlled neurological context (fever → seizure → post-ictal) before the branch escalates to meningitis, psychiatric presentations, and legal/ethical complexity.

**Focus:** Neurological emergency recognition (seizure → meningitis), psychiatric emergencies, behavioral de-escalation, communication in high-stress family dynamics, documentation for mental health holds, medicolegal considerations for minors.

**Unlocks:** PM6.

---

### PM5 — Respiratory (Infectious)

**Category:** `pediatric_medical_resp_infectious`  
**Theme:** Infectious Respiratory Illness  
**Prerequisites:** PM2  
**Difficulty:** Intermediate  

**Mini-game:** Differential Dash — Difficulty Breathing Edition *(sorting game: match clinical finding to respiratory condition)*  
**Key awarded:** Respiratory Key — earned on completion of PM5's final scenario.

**Scenarios:**
- *(New)* Pneumonia — fever, productive cough, decreased breath sounds, hypoxia, antibiotic timing framing
- *(New)* Bronchiolitis — infant with RSV-pattern illness, wheezing, feeding difficulty, high-flow O2
- *(New)* Pertussis — paroxysmal cough, post-tussive vomiting, whooping inspiratory phase, isolation framing

**Focus:** Infectious airway and pulmonary illness differentiation, O2 delivery in infants, isolation and transport decision-making, reporting considerations.

---

### PM6 — Pediatric Operations

**Category:** `pediatric_medical_operations`  
**Theme:** Child Safety, Reporting, and Provider Decision-Making  
**Prerequisites:** PM4  
**Difficulty:** Intermediate  

**Mini-game:** TEN-4 FACES *(child abuse identification tool — structured visual/case-based screening for abusive injury patterns)*  
**Key awarded:** AMS/Operations Key — earned on completion of PM6's final scenario.  

> **TEN-4 FACES** is a validated clinical decision tool for identifying abusive head trauma and skin injuries in children. The mini-game presents case vignettes with injury descriptions and photos; students identify which findings are concerning for non-accidental trauma using the TEN-4 FACES criteria. Engine: new case-based vignette component (similar to Right Call structure).

**Scenarios:**
- *(New)* Child Abuse — non-accidental trauma presentation, injury inconsistent with history, mandatory reporting obligations, scene documentation, law enforcement interaction
- *(New)* Child Neglect — medical neglect recognition, chronic vs. acute presentation, age-appropriate developmental assessment, reporting framing
- *(New)* Refusal of Treatment for a Minor — caregiver refusing care, communication, medical control consultation, documentation, legal framing for minors

**Focus:** Mandatory reporting, medicolegal documentation, communication with law enforcement and child protective services, provider decision-making under uncertainty.

---

### PM7 — Medical Convergence (Scout's Toy Shop — Key Award)

**Category:** `pediatric_medical_convergence`  
**Theme:** Medical Track Completion  
**Prerequisites:** PM3, PM5, PM6 *(accessible as soon as any one is complete; Medical Key not awarded until all 6 medical toys are in Toy Chest)*  
**Difficulty:** N/A — no scenarios  

**Mini-game:** None  
**Scout's Toy Shop:** Key award shop. Scout displays a checklist of all 6 medical-track toys. As the student checks in, Scout verifies the Toy Chest. When all 6 medical toys are present, Scout congratulates the student and awards the Medical Key. PE1 unlocks once the Trauma Key is also awarded at PT8.

> **Partial access:** PM7 becomes navigable as soon as PM3, PM5, or PM6 is first completed. The toy checklist shows which toys are collected and which are outstanding, guiding the learner back to incomplete branches.

> **No synthesis scenarios here:** PE1 and PE2 are the multi-system boss fights. PM7 is the collection gate, not a difficulty layer.

---

## 6. Trauma Track (PT1–PT8)

All trauma maps require Map 0 completion. PT2–PT8 have additional intra-track prerequisites as noted. Each path between maps is blocked by one designated scenario on the source map.

---

### PT1 — Intro Trauma

**Category:** `pediatric_trauma`  
**Theme:** Introduction to Pediatric Trauma Assessment  
**Prerequisites:** Map 0  
**Difficulty:** Beginner  

**Mini-game:** Rule of Nines *(pediatric BSA estimation — body map tap puzzle)*  
**Scenarios:** None — PT1 is a mini-game-only gateway node.  
**Scout's Toy Quest:** Completing the PT1 mini-game triggers the first trauma toy notification (Trauma Toy 1).

**Gateway mechanic:** Completing the Rule of Nines mini-game unlocks PT2, PT3, and PT4 simultaneously. All three branches open at once; the learner chooses where to start.

> **Scenario redistribution note:** The Bleeding Control scenario, `peds_trauma_03_extremity`, and `peds_trauma_04_burn` have moved to PT2, PT3, and PT4 respectively, where their clinical themes align with each branch. PT1 is intentionally scenario-free so the three branches each begin with an accessible introductory case.

**Unlocks:** PT2, PT3, PT4 (all unlock on mini-game completion).

---

### PT2 — Blunt Force / Bleeding Control

**Category:** `pediatric_trauma_blunt`  
**Theme:** Blunt Mechanism Injuries and Hemorrhage Control  
**Prerequisites:** PT1  
**Difficulty:** Intermediate  

**Mini-game:** Stop the Bleed *(hemorrhage control intervention selection — sorting game)*  
**Scenarios:**
- *(New)* Bleeding Control — arterial hemorrhage from an extremity; direct pressure → wound packing → tourniquet decision-making *(branch introductory case — moved from PT1)*
- `peds_trauma_06_handlebar` — handlebar abdominal injury, internal injury suspicion without external confirmation
- *(New)* Abdominal Blunt Trauma — seatbelt sign, guarding, mechanism-based injury suspicion, transport priority
- *(New)* Penetrating Trauma — stab wound or impalement, wound sealing, evisceration management, do-not-remove decision

> **Progression note:** Bleeding Control is the branch entry case — establishes the hemorrhage control spectrum (direct pressure → packing → tourniquet) in a straightforward extremity context before internal injury complexity is introduced.

> **Note on penetrating in a blunt force map:** Penetrating mechanism is grouped here because the primary skill emphasis (hemorrhage control, wound management, internal injury suspicion) is shared with blunt abdominal trauma. A future PT split may separate these if scenario volume warrants it.

**Focus:** Hemorrhage control spectrum, mechanism-based injury pattern recognition, internal injury suspicion without external confirmation, hemorrhage control in complex wounds, pain management within BLS scope.

**Unlocks:** PT5 (after PT2).

---

### PT3 — Neuro/Airway

**Category:** `pediatric_trauma_neuro`  
**Theme:** Neurological Trauma and Airway Management  
**Prerequisites:** PT1  
**Difficulty:** Intermediate  

**Mini-game:** GCS Matcher *(drag-to-match GCS component scoring puzzle)*  
**Scout's Toy Shop:** Purchase shop. Toy purchases available for any notified toys the player hasn't yet bought.

**Scenarios:**
- `peds_trauma_03_extremity` — extremity fracture; immobilization, neurovascular assessment (distal pulse/motor/sensation), pain management within BLS scope *(branch introductory case — moved from PT1)*
- `peds_trauma_05_auto_ped` — high-MOI auto-pedestrian, GCS assessment, spinal precautions
- *(New)* Traumatic Brain Injury — decreasing GCS, Cushing's triad awareness, airway management planning, ALS priority
- *(New)* Unconscious Patient with Vomiting — airway management with C-spine precautions, suction decision, recovery position vs. log roll

> **Progression note:** Extremity Fracture is the branch entry case — introduces neurovascular assessment (distal PMS checks) in a stable, accessible context before C-spine, GCS, and unconscious airway complexity escalate. The neurovascular assessment angle connects extremity injury to PT3's neuro theme.

> **Airway scope note:** Airway in PT3 is trauma-mechanism airway (unconscious, vomit, C-spine). Foreign body and medical airway obstruction belong in Map 0 and PM2 respectively.

**Focus:** Neurovascular extremity assessment, GCS assessment, spinal motion restriction, neurological deterioration recognition, airway management under cervical precaution constraints.

**Unlocks:** PT6 (after PT3).

---

### PT4 — Environmental & Toxins

**Category:** `pediatric_trauma_env_tox`  
**Theme:** Environmental Emergencies and Toxic Exposures  
**Prerequisites:** PT1  
**Difficulty:** Intermediate  

**Mini-game:** MOI Mapper *(mechanism → injury suspicion categorization — PAT swipe engine)*  
**Scenarios:**
- `peds_trauma_04_burn` — burn assessment (Lund-Browder), fluid considerations, transport priority *(branch introductory case — moved from PT1)*
- *(New)* Heat Emergency — exertional hyperthermia or heat stroke in a toddler, cooling measures, ALS triggers
- *(New)* Accidental Ingestion/Poisoning — household product or OTC medication, poison control consultation framing, activated charcoal decision
- *(New)* Insect Bite/Envenomation — allergic vs. anaphylactic presentation, localized vs. systemic response, epi decision

> **Progression note:** Burns is the branch entry case — it grounds the thermal/environmental theme before escalating to toxicological complexity. Burns also reinforces the Rule of Nines and BSA estimation introduced in PT1's mini-game.

**Focus:** Thermal and environmental injury recognition and assessment, decontamination principles, toxin-specific BLS interventions, poison control consultation, allergic vs. anaphylactic differentiation.

**Unlocks:** PT7 (after PT4).

---

### PT5 — Hemorrhage and Shock

**Category:** `pediatric_trauma_hemorrhage`  
**Theme:** Hemorrhagic Shock and Multi-Site Injury  
**Prerequisites:** PT2  
**Difficulty:** Intermediate  

**Mini-game:** Shock Spotter — Trauma Edition *(compensated vs. decompensated shock, trauma context — PAT swipe engine)*  
**Key awarded:** Hemorrhage/Shock Key — earned on completion of PT5's final scenario.

**Scenarios:**
- *(New)* Hemorrhagic Shock — multi-site trauma with evolving shock physiology, hemorrhage control prioritization, ALS intercept urgency
- *(New)* Shock Management — compensated shock recognition with preserved BP (early), treatment sequencing, transport decision
- *(New)* Complex Extremity Fracture — femur fracture with vascular compromise, traction splint decision, neurovascular check

**Focus:** Shock recognition and progression, hemorrhage control under time pressure, priority sequencing when multiple injuries compete, traction splinting.

---

### PT6 — Thoracic and Drowning

**Category:** `pediatric_trauma_thoracic`  
**Theme:** Thoracic Injuries and Submersion  
**Prerequisites:** PT3  
**Difficulty:** Intermediate  

**Mini-game:** BLS Sequence *(correct-order BLS algorithm puzzle — CPR/airway sequence matching)*  
**Key awarded:** Neuro/Airway Key — earned on completion of PT6's final scenario.

**Scenarios:**
- *(New)* Chest Injury / Pneumothorax — mechanism-based suspicion, tension pneumothorax recognition, needle decompression awareness (ALS scope), occlusive dressing
- *(New)* Near-Drowning / Submersion — cold vs. warm water, hypothermia layering, airway and oxygenation priorities

> **Third scenario:** Rib fractures with respiratory compromise — paradoxical movement, splinting, pain management, pneumothorax suspicion, ALS priority framing.

**Focus:** Thoracic trauma recognition, pneumothorax clinical presentation, BLS management boundaries before ALS arrival, submersion physiology and hypothermia layering.

---

### PT7 — Environmental & Toxins (Advanced)

**Category:** `pediatric_trauma_env_tox_adv`  
**Theme:** Complex Environmental Presentations  
**Prerequisites:** PT4  
**Difficulty:** Intermediate  

**Mini-game:** Temp Check *(sort clinical signs/symptoms into hypothermia vs. hyperthermia — Sort Engine)*  
**Key awarded:** Environmental Key — earned on completion of PT7's final scenario.

**Scenarios:**
- *(New)* Dog Bite / Animal Attack — wound classification, infection risk, rabies exposure framing, mandatory reporting
- *(New)* Hypothermia / Frostbite — cold exposure, core temperature staging, rewarming principles, do-not-rub rule
- *(New)* Dehydration — pediatric dehydration from illness or environmental exposure, clinical signs, oral rehydration scope, ALS for IV access decision

**Focus:** Advanced environmental injury patterns, wound management with infection and reporting considerations, thermoregulatory emergency management.

---

### PT8 — Trauma Convergence (Scout's Toy Shop — Key Award)

**Category:** `pediatric_trauma_convergence`  
**Theme:** Trauma Track Completion  
**Prerequisites:** PT5, PT6, PT7 *(accessible as soon as any one is complete; Trauma Key not awarded until all 7 trauma toys are in Toy Chest)*  
**Difficulty:** N/A — no scenarios  

**Mini-game:** None  
**Scout's Toy Shop:** Key award shop. Scout displays a checklist of all 7 trauma-track toys. As the student checks in, Scout verifies the Toy Chest. When all 7 trauma toys are present, Scout congratulates the student and awards the Trauma Key. PE1 unlocks once the Medical Key is also awarded at PM7.

> **Partial access:** PT8 becomes navigable as soon as PT5, PT6, or PT7 is first completed. The toy checklist shows which toys are collected and which are outstanding, guiding the learner back to incomplete branches.

> **No synthesis scenarios here:** PE1 and PE2 are the multi-system boss fights. PT8 is the collection gate, not a difficulty layer.

---

## 7. Convergence (PE1–PE2)

**Prerequisites:** The Medical Key (awarded at PM7 when all 6 medical-track toys are collected) AND the Trauma Key (awarded at PT8 when all 7 trauma-track toys are collected) must both be held before PE1 unlocks. PM7 and PT8 can be reached in either order or in parallel.

> Learners can enter PM7 or PT8 as soon as any single feeder path to each is complete. The toy checklists at each shop show what remains. PE1 opens automatically once the second key is awarded.

### Intentional Cognitive Load Spike at PE1

PM1–PM6 and PT1–PT7 are siloed by clinical domain — learners working within a branch know the answer space is narrow (e.g., PM2 scenarios are respiratory calls). This is blocked practice. PE1 is the first map requiring interleaved practice: learners must differentiate across all systems without domain cues. PM7 and PT8 have no scenarios, so PE1 is the immediate follow-on after key collection — the jump in cognitive load is real and deliberate.

**Framing:** When Scout awards the second key and PE1 unlocks, his dialogue should prepare the learner's metacognition rather than imply PE1 is just the next step. Example: *"You've learned every trail. But PE1 doesn't tell you what's wrong. You'll have to figure that out yourself. Good luck."* Lexi can reinforce this in the map UI with a short unlock message noting that multi-system calls are different from single-domain practice.

---

### PE1 — Pediatric Emergencies 1

**Category:** `pediatric_emergency`  
**Theme:** Integrated Pediatric Emergencies  
**Prerequisites:** Medical Key (awarded at PM7) AND Trauma Key (awarded at PT8)  
**Difficulty:** Advanced  

**Mini-game:** None  
**Scenarios:**
- *(New)* Vehicle Accident — multi-injury MVC, mechanism assessment, triage decisions, ALS coordination
- *(New)* Difficulty Breathing — complex respiratory presentation requiring differential diagnosis under time pressure (asthma vs. anaphylaxis vs. cardiac)
- *(New)* Altered Mental Status — multi-etiology AMS (toxic, metabolic, neurologic, behavioral) requiring structured differential
- *(New)* Respiratory Arrest — impending or early respiratory arrest, BVM, ALS priority, family communication

**Focus:** Integrated assessment across all prior systems, differential reasoning under urgency, treatment sequencing when multiple problems are present.

---

### PE2 — Pediatric Emergencies 2

**Category:** `pediatric_emergency`  
**Theme:** High-Acuity Multi-System Crisis  
**Prerequisites:** PE1  
**Difficulty:** Advanced  

**Mini-game:** Priority Stack *(drag-to-rank simultaneous clinical problems — final synthesis check)*  

> **Position:** Priority Stack is placed **after** the final PE2 scenario as a culminating synthesis check, not a primer.

**Scenarios:**
- *(New)* Crashing Patient — previously stable patient deteriorating on scene, recognition of decompensation, treatment pivots under pressure
- *(New)* Multi-System Trauma — high-acuity pediatric MVC with hemorrhage, airway, and neurological threats competing simultaneously
- *(New)* Pediatric Cardiac Arrest — infant/child CPR, AED, compression depth and rate, family presence, team coordination

**Focus:** Multi-system integration, resource prioritization, ALS handoff under complex conditions, treatment sequencing when problems directly compete, team communication at highest acuity.

---

## 8. Map and Scenario Summary

### Map Count

| Level | Maps | Difficulty |
|---|---|---|
| Entrance | 1 (Map 0) | Beginner |
| Medical Track | 7 (PM1–PM7) | Beginner (PM1) / Intermediate (PM2–PM6) / Shop node (PM7) |
| Trauma Track | 8 (PT1–PT8) | Beginner (PT1) / Intermediate (PT2–PT7) / Shop node (PT8) |
| Convergence | 2 (PE1–PE2) | Advanced |
| **Total** | **18** | |

### Scenario Count

| Level | Existing | New Needed | Total |
|---|---|---|---|
| Map 0 | 4 | 0 | 4 |
| PM1 | 0 | 0 | 0 (mini-game gateway) |
| PM2–PM6 | 3 | ~18 | ~21 |
| PM7 | 0 | 0 | 0 (key award shop) |
| PT1 | 0 | 0 | 0 (mini-game gateway) |
| PT2–PT7 | 4 | ~20 | ~24 |
| PT8 | 0 | 0 | 0 (key award shop) |
| PE1–PE2 | 0 | ~7 | ~7 |
| **Total** | **11** | **~45** | **~56** |

> **Note:** Existing scenario counts include PM1/PT1 scenarios redistributed to their branch maps (Syncope, Febrile Seizure, Allergy → PM3, PM4, PM2; Bleeding Control, Extremity Fracture, Burns → PT2, PT3, PT4).

### Prerequisite Chain (Medical)

```
Map 0 → PM1 (mini-game) ─┬─→ PM2 ──→ PM5 ────────┐
                         │─→ PM3 ─────────────→ PM7 [Medical Key] → PE1 → PE2
                         └─→ PM4 ──→ PM6 ────────┘
```

*PM1 unlocks all three branches simultaneously on mini-game completion.*  
*PM7 requires any one of PM3/PM5/PM6 to enter, but awards the Medical Key only when all 6 medical-track toys are in the Toy Chest.*

### Prerequisite Chain (Trauma)

```
Map 0 → PT1 (mini-game) ─┬─→ PT2 ──→ PT5 ────────┐
                         │─→ PT3 ──→ PT6 ─────→ PT8 [Trauma Key] → PE1 → PE2
                         └─→ PT4 ──→ PT7 ────────┘
```

*PT1 unlocks all three branches simultaneously on mini-game completion.*  
*PT8 requires any one of PT5/PT6/PT7 to enter, but awards the Trauma Key only when all 7 trauma-track toys are in the Toy Chest.*


### Map Navigation

```
              ┬─ PT4 ── PT7 ───────┐
              │   │                │     
       PT1 ── │─ PT3 ── PT6 ───── PT8 ────┐
        │     │   │                │      │
        │     └─ PT2 ── PT5 ───────┘      │
Map 0 ──│                                PE1 ── PE2
        │     ┬─ PM2 ── PM5 ───────┐      │
        │     │   │                │      │     
       PM1 ── │─ PM3 ──────────── PM7 ────┘
              │   │                │      
              └─ PM4 ── PM6 ───────┘      

```

### Convergence Gate

```
PM7 (medical convergence)
              ↘
               PE1 → PE2
              ↗
PT8 (trauma convergence)
```

---

## 9. Mini-Game and Shop Placement Summary

See `MINIGAMES_DESIGN.md` for the shared mini-game catalog, engine requirements, result contract, and the Peds Assessment additions. The placement table below remains the pediatric map progression reference; the mini-game design doc owns reusable game design and implementation patterns.

| Map | Mini-Game | Scout's Shop | Engine |
|---|---|---|---|
| Map 0 | PAT Doorway Dash | Introduction shop (Scout intro + quest start, Toy Chest preview) | PAT swipe (existing) |
| PM1 | Lexi's Development Toy Box | — | Sorting (existing) |
| PM2 | Sound Check | — | Audio matching component (`sound_check`) |
| PM3 | Shock Spotter | Purchase shop (buy available notified toys) | PAT swipe (data only) |
| PM4 | Differential Dash — AMS | — | Sorting (data only) |
| PM5 | Differential Dash — Difficulty Breathing | — | Sorting (data only) |
| PM6 | TEN-4 FACES | — | PAT swipe engine (`ten4_facesp` — same game as SCORM `tr_ten4`, data-configured for PM6) |
| PM7 | None | Key award shop (medical — 6-toy checklist → Medical Key) | — |
| PT1 | Rule of Nines | — | New body map tap component |
| PT2 | Stop the Bleed | — | Sorting (data only) |
| PT3 | GCS Matcher | Purchase shop (buy available notified toys) | Calculation component (`peds_gcs_calculator` — same game as SCORM `tr_gcs`) |
| PT4 | MOI Mapper | — | PAT swipe (data only) |
| PT5 | Shock Spotter — Trauma Edition | — | PAT swipe (data only) |
| PT6 | BLS Sequence | — | Sort Engine (repurposed) |
| PT7 | Temp Check | — | Sort Engine (repurposed) |
| PT8 | None | Key award shop (trauma — 7-toy checklist → Trauma Key) | — |
| PE1 | None | — | — |
| PE2 | Priority Stack | — | Sort Engine (repurposed — drag-to-rank, after final scenario) |

### Engine Work Required

| Extension | Scope | Affects |
|---|---|---|
| New: Audio matching component (play/pause, drop-zone, answer key, `license_source` per clip) | New component | Sound Check (`sound_check`), Lung Sounds Matcher (`lung_sounds_matcher`) |
| Make PAT decision labels data-configurable | ~5 lines | MOI Mapper, Shock Spotter, TEN-4 FACES (`ten4_facesp`) |
| Add 3-option tap to PAT engine | ~30 lines | Adult vs. Child A&P, Right Call (if added) |
| New: Calculation component (scale selection, E/V/M inputs, deferred auto-sum) | New component | GCS Matcher (`peds_gcs_calculator`) |
| Add data config: scored-order mode to Sort Engine | ~20 lines | BLS Sequence |
| Add data config: ranked-list mode with reveal to Sort Engine | ~20 lines | Priority Stack |
| New: Body map tap + region accumulator + BSA calculator | New component | Rule of Nines (`rule_of_nines`) |
| Backend: map-completion → toy availability (`map_gate_id` on Toy, `PedsMapProgress` filter in shop API) | Implemented | All PM/PT toy notifications |
| Backend: shop API filter — show peds toys only when their map is completed | ~20 lines | `/api/toys/shop` |
| Backend: PM7/PT8 key-award endpoint — verify toy checklist → award Medical/Trauma Key | New endpoint | PM7, PT8 |
| Backend: PE1 gate — check both keys present before unlocking | Gate check logic | PE1 |

> **Engine reuse note (V1):** GCS Matcher, BLS Sequence, and Priority Stack all shoehorn into the existing `DragSortGameEngine`. No new drag/match components needed for V1 — only data-config extensions to the sort engine (~40 lines total vs. 3 new components).
>
> **Scout shop reuse note:** Scout's shop modal, SVG avatar, dialogue, Toy Chest, treat display, and purchase flow are fully built. No new shop UI components needed — only backend work to drive the peds progression mechanic.

---

## 10. Progression Contract

This section is the authoritative implementation contract for map unlocking, toy awards, and key gating. All backend state machines and frontend topology objects must derive from these tables, not from the prose descriptions above.

---

### 10.1 User Progression States

Every map node has exactly one of the following states for a given user. State is stored server-side; the frontend reads it and renders accordingly.

| State | Meaning | Applies to |
|---|---|---|
| `locked` | Prerequisites not met; node not visible or greyed out | All maps |
| `accessible` | Prerequisites met; content is available | All maps |
| `completed` | Map completion rule satisfied; outgoing edge(s) open; toy notification sent | Branch maps, gateway nodes, Map 0, PE1 |
| `key_awarded` | All required toys verified; track key awarded | PM7, PT8 only |
| `pe1_unlocked` | Both keys held; PE1 is open | Derived state — not stored separately |

> **Gateway nodes (PM1, PT1):** transition from `accessible` → `completed` on minigame completion, not scenario completion.  
> **Convergence nodes (PM7, PT8):** transition from `accessible` → `key_awarded` when Scout verifies the toy checklist. `completed` is not used for these nodes.  
> **PE1:** transitions `locked` → `accessible` when both `PM7.state == key_awarded` AND `PT8.state == key_awarded`.

---

### 10.2 Map Completion Rules

Defines what event transitions each map from `accessible` → `completed` and triggers the toy notification.

| Map | Map Type | Completion Rule | Trigger Event |
|---|---|---|---|
| Map 0 | entrance | Each outgoing edge has its own designated gate scenario (see §10.3). Map 0 itself has no single completion event. | Per-edge gate scenario completion |
| PM1 | gateway | `dev_sort` minigame score submitted | Minigame completion |
| PM2 | branch | Final scenario in ordered scenario list completed | Scenario completion |
| PM3 | branch | Final scenario in ordered scenario list completed | Scenario completion |
| PM4 | branch | Final scenario in ordered scenario list completed | Scenario completion |
| PM5 | branch | Final scenario in ordered scenario list completed | Scenario completion |
| PM6 | branch | Final scenario in ordered scenario list completed | Scenario completion |
| PM7 | convergence | All 6 medical-track toys present in Toy Chest (verified at key-award shop) | Toy checklist verification |
| PT1 | gateway | `rule_of_nines` minigame score submitted | Minigame completion |
| PT2 | branch | Final scenario in ordered scenario list completed | Scenario completion |
| PT3 | branch | Final scenario in ordered scenario list completed | Scenario completion |
| PT4 | branch | Final scenario in ordered scenario list completed | Scenario completion |
| PT5 | branch | Final scenario in ordered scenario list completed | Scenario completion |
| PT6 | branch | Final scenario in ordered scenario list completed | Scenario completion |
| PT7 | branch | Final scenario in ordered scenario list completed | Scenario completion |
| PT8 | convergence | All 7 trauma-track toys present in Toy Chest (verified at key-award shop) | Toy checklist verification |
| PE1 | advanced | Final scenario in ordered scenario list completed | Scenario completion |
| PE2 | advanced | Final scenario in ordered scenario list completed | Scenario completion |

> **"Final scenario in ordered scenario list"** means the scenario designated as position N in the map's authored scenario order. The backend enforces this order; learners cannot play scenario N before N−1. The scenario in the last position is the gate scenario for the outgoing edge. Gate scenario IDs are assigned at content authoring time and registered in the map topology config.

---

### 10.3 Edge Table (Path Gating)

Every directed edge in the map graph with its gate type, gate ID, and access condition.

| from_map | to_map | gate_type | gate_id | access_condition | notes |
|---|---|---|---|---|---|
| — | Map 0 | none | — | always accessible | District entry |
| Map 0 | PM1 | scenario | `peds_diabetic_emergency_01` | single gate | Medical scenario gates medical track entry |
| Map 0 | PT1 | scenario | `peds_trauma_02_partial_choking` | single gate | Trauma scenario gates trauma track entry |
| PM1 | PM2 | minigame | `dev_sort` | single gate (all three branches open simultaneously) | |
| PM1 | PM3 | minigame | `dev_sort` | same gate as PM1→PM2 | Same minigame completion opens all three |
| PM1 | PM4 | minigame | `dev_sort` | same gate as PM1→PM2 | |
| PM2 | PM5 | scenario | `[gate scenario — final in PM2 list]` | single gate | |
| PM3 | PM7 | scenario | `[gate scenario — final in PM3 list]` | single gate | PM7 accessible when any of PM3/PM5/PM6 gate is open |
| PM4 | PM6 | scenario | `[gate scenario — final in PM4 list]` | single gate | |
| PM5 | PM7 | scenario | `[gate scenario — final in PM5 list]` | single gate | PM7 accessible when any of PM3/PM5/PM6 gate is open |
| PM6 | PM7 | scenario | `[gate scenario — final in PM6 list]` | single gate | PM7 accessible when any of PM3/PM5/PM6 gate is open |
| PM7 | PE1 | key_pair | `key_peds_med_golden_stethoscope` | requires BOTH keys | PE1 accessible only when PM7 key_awarded AND PT8 key_awarded |
| PT1 | PT2 | minigame | `rule_of_nines` | single gate (all three branches open simultaneously) | |
| PT1 | PT3 | minigame | `rule_of_nines` | same gate as PT1→PT2 | |
| PT1 | PT4 | minigame | `rule_of_nines` | same gate as PT1→PT2 | |
| PT2 | PT5 | scenario | `[gate scenario — final in PT2 list]` | single gate | |
| PT3 | PT6 | scenario | `[gate scenario — final in PT3 list]` | single gate | |
| PT4 | PT7 | scenario | `[gate scenario — final in PT4 list]` | single gate | |
| PT5 | PT8 | scenario | `[gate scenario — final in PT5 list]` | single gate | PT8 accessible when any of PT5/PT6/PT7 gate is open |
| PT6 | PT8 | scenario | `[gate scenario — final in PT6 list]` | single gate | PT8 accessible when any of PT5/PT6/PT7 gate is open |
| PT7 | PT8 | scenario | `[gate scenario — final in PT7 list]` | single gate | PT8 accessible when any of PT5/PT6/PT7 gate is open |
| PT8 | PE1 | key_pair | `key_peds_trm_silver_shears` | requires BOTH keys | PE1 accessible only when PM7 key_awarded AND PT8 key_awarded |
| PE1 | PE2 | scenario | `[gate scenario — final in PE1 list]` | single gate | |

> **Map 0 gate scenario rationale:** `peds_diabetic_emergency_01` (medical — AMS/glucose) gates PM1; `peds_trauma_02_partial_choking` (trauma — airway intervention decision) gates PT1. These are slightly harder than the first scenarios on their respective maps and establish the assessment pattern used throughout each track. `peds_croup_01` and `peds_trauma_01_soft_tissue` are accessible without gating.

---

### 10.4 Toy Award Table

Each toy is tied to exactly one map. Map completion sends the Scout notification; the learner purchases the toy at any Scout shop using treats.

| toy_id | Display Name | Map | Awarded on | Track |
|---|---|---|---|---|
| `toy_peds_med_milestone_chew` | Milestone Measuring-Stick Chew | PM1 | PM1 minigame (`dev_sort`) completion | Medical |
| `toy_peds_med_breathing_bear` | Breathing Bear Squeaker | PM2 | PM2 final scenario completion | Medical |
| `toy_peds_med_heartbeat_hound` | Heartbeat Hound Plush | PM3 | PM3 final scenario completion | Medical |
| `toy_peds_med_braingame_ball` | Brain-Teaser Puzzle Ball | PM4 | PM4 final scenario completion | Medical |
| `toy_peds_med_thermometer_rope` | Thermometer Tug-Rope | PM5 | PM5 final scenario completion | Medical |
| `toy_peds_med_guardian_retriever` | Guardian Retriever Plush | PM6 | PM6 final scenario completion | Medical |
| `toy_peds_trm_patchwork_puppy` | Patchwork Puppy Plush | PT1 | PT1 minigame (`rule_of_nines`) completion | Trauma |
| `toy_peds_trm_tourniquet_rope` | Tourniquet Tug-Rope | PT2 | PT2 final scenario completion | Trauma |
| `toy_peds_trm_ccollar_corgi` | C-Collar Corgi Plush | PT3 | PT3 final scenario completion | Trauma |
| `toy_peds_trm_cooling_vest_dach` | Cooling-Vest Dachshund | PT4 | PT4 final scenario completion | Trauma |
| `toy_peds_trm_traction_stick` | Traction-Splint Fetch Stick | PT5 | PT5 final scenario completion | Trauma |
| `toy_peds_trm_life_preserver` | Life-Preserver Ring Toy | PT6 | PT6 final scenario completion | Trauma |
| `toy_peds_trm_stbernard_rescue` | Snow-Rescue St. Bernard | PT7 | PT7 final scenario completion | Trauma |

> **Notification mechanic:** Map completion writes a `toy_available` event for the user. The shop API checks these events when filtering which peds toys to show, presenting only toys the learner has unlocked (map completed) but not yet purchased. The `is_new_arrival` flag on the toy's series is set to true, which drives the "NEW" badge in the Toy Chest UI.

---

### 10.5 Key Award Table

| key_id | Display Name | Awarded at | Requirement | Unlocks |
|---|---|---|---|---|
| `key_peds_med_golden_stethoscope` | The Golden Stethoscope Key | PM7 | All 6 medical-track toys present in Toy Chest: `toy_peds_med_milestone_chew`, `toy_peds_med_breathing_bear`, `toy_peds_med_heartbeat_hound`, `toy_peds_med_braingame_ball`, `toy_peds_med_thermometer_rope`, `toy_peds_med_guardian_retriever` | PE1 (when paired with Trauma Key) |
| `key_peds_trm_silver_shears` | The Silver Trauma Shears Key | PT8 | All 7 trauma-track toys present in Toy Chest: `toy_peds_trm_patchwork_puppy`, `toy_peds_trm_tourniquet_rope`, `toy_peds_trm_ccollar_corgi`, `toy_peds_trm_cooling_vest_dach`, `toy_peds_trm_traction_stick`, `toy_peds_trm_life_preserver`, `toy_peds_trm_stbernard_rescue` | PE1 (when paired with Medical Key) |

> **PE1 gate check:** server-side only. `PE1.state = accessible` when `user.key_peds_med_golden_stethoscope == true AND user.key_peds_trm_silver_shears == true`. Frontend derives PE1 lock state from the API; it does not compute this locally.

---

## 11. Open Questions

| Question | Status |
|---|---|
| PT7 mini-game: Temp Check — hypothermia vs. hyperthermia signs/symptoms sort | Confirmed |
| PT6 third scenario slot | Confirmed — rib fractures with respiratory compromise |
| PM4 third/fourth scenario slot | Confirmed — unattended teen refusal (mature minor doctrine) |
| PM7 mechanic: 6-toy checklist → Medical Key award | Resolved (2026-04-28) |
| PT8 mechanic: 7-toy checklist → Trauma Key award | Resolved (2026-04-28) |
| Scout's Toy Quest: notify → purchase with treats → 2 keys at convergence shops | Resolved (2026-04-28) |
| PM1/PT1 as mini-game-only gateway nodes; scenarios redistributed to branches | Resolved (2026-04-28) |
| Sound Check audio licensing — confirm all lung sound files cleared for public use | Open |
| Treat economy calibration — earn rates must support purchasing all track toys through normal play | Open — balance pass required before ship |
| Toy buyback removal — no sell button exists in current code; duplicate purchase returns treats (intentional, no change needed) | Resolved — no code change required |
| Toy names and clinical anchors (all 13 toys named and clinically anchored) | Resolved (2026-04-28) — see §3 Toy Inventory |
| Key names and visual design (Golden Stethoscope Key + Silver Trauma Shears Key) | Resolved (2026-04-28) — see §3 Keys |
| Scout character art and shop UI component | Resolved — Scout SVG avatar and shop modal are fully built in static/index.html |
| Toy visual art assets (13 toy illustrations matching names in §3) | Open — design/asset work |
| PE1 framing dialogue — Scout line warning learner about interleaved difficulty spike | Open — content/narrative work |
| Path gate scenario designation: branch maps use the final scenario in ordered list; Map 0 gate IDs are fixed (see §10.3) | Resolved (2026-04-28) — see §10.3 |
| Map completion rule definition: what does "complete" mean in code? | Resolved (2026-04-28) — see §10.2 |
| User progression state enum | Resolved (2026-04-28) — see §10.1 |
| Toy_id naming convention and database slugs | Resolved (2026-04-28) — see §10.4 |
| Key_id naming convention | Resolved (2026-04-28) — see §10.5 |
| Branch start-order recommendation at split point (PM1→PM2/PM3/PM4 and PT1→PT2/PT3/PT4) | Open — UX suggestion only; no gate enforcement |
| XP/rewards integration for new maps | Follow existing architecture |

---

## 12. Known Gaps and Deferred Content

| Gap | Priority | Notes |
|---|---|---|
| Neonatal / OB scenarios | Phase 2 | APGAR, birth complications, meconium aspiration — requires OB scenario architecture and partner role redesign |
| Mild allergic reaction (urticaria only, no anaphylaxis) | Phase 2 | Watchful waiting / scope decision — candidate for PM4 or PM6 |
| Pediatric MCI / triage | Phase 3 | Blocked by single-patient architecture |
| Cross-district scenarios (adult + child) | Phase 3 | Requires multi-patient structural changes |
| Cultural / language barrier scenarios | Phase 3 | Interpreter, caregiver language barrier, health equity contexts |
| Category-adaptive AI prompt rules | Tier 2 (code) | Behavioral health and OB scenarios need category-specific AI role rules — currently a structural gap |
| Procedural skills emphasis | Phase 2 | Airway maneuver, needle decompression, IO access — may suit mini-game or puzzle format |
