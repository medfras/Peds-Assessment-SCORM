# Pediatric Map Design V2

**Project:** RescueTrails  
**Status:** Planning Draft  
**Purpose:** A refined pediatric district plan that builds on `PEDIATRIC_MAP_DESIGN.md` with clearer theming, cleaner instructional progression, and more intentional visual/world design notes for each map.

---

## 1. V2 Intent

This V2 plan keeps the core progression architecture from the original pediatric map while refining three things:

1. **Instructional clarity**
   The learner should understand why each map exists, what skill family it trains, and how it prepares them for the next layer of complexity.

2. **World coherence**
   The pediatric district should feel like one believable training world, not a collection of disconnected JPEGs with scenarios dropped on top.

   Because this is an EMS training product, that world should be primarily **prehospital**: homes, schools, daycares, playgrounds, athletic spaces, roadsides, parks, pools, and community settings where EMS actually encounters pediatric patients.

3. **Market-facing polish**
   The map should still feel warm and memorable, but the thematic framing should support a professional EMS training product.

This document is planning-only. It does not replace the current authoritative progression contract in `PEDIATRIC_MAP_DESIGN.md`. It is a recommended content/world-design evolution layer for the pediatric district.

---

## 2. V2 Design Principles

### 2.1 Instructional Principles

- **Assessment before action**
  Early maps should reinforce pediatric assessment habits before branching into domain-specific treatment decisions.

- **Branch identity must be obvious**
  Each medical and trauma branch should have a strong clinical identity so learners can form useful mental categories without the maps feeling repetitive.

- **Convergence should feel earned**
  PM7, PT8, PE1, and PE2 should clearly feel like synthesis and progression milestones, not just more nodes in the same loop.

- **Map completion should mean mastery of the map’s core lesson**
  Each map should have one dominant teaching objective and one clear completion signal.

### 2.2 UX / World Principles

- **Professional outer framing, warm inner tone**
  The district and map naming should feel more like a training environment than a toy park, while still leaving room for Lexi and Scout as companion characters.

- **Each map needs a strong visual silhouette**
  Learners should be able to tell maps apart at a glance.

- **The map should signal clinical domain without becoming literal clip art**
  Respiratory maps can suggest activity zones, playground exertion, isolation pickups, or outdoor triggers without resorting to giant lungs or hospital rooms.

- **Scene-first realism**
  Pediatric maps should mostly represent places prehospital providers are actually called: schools, daycare pickup lanes, playgrounds, sports fields, parking lots, neighborhoods, family homes, campsites, pool decks, and public events.

- **Difficulty should be legible**
  Beginner maps should feel open and readable. Advanced maps should feel more compressed, urgent, and layered.

---

## 3. Recommended V2 World Framing

### 3.1 District Frame

Instead of presenting the pediatric district primarily as a whimsical dog-park world or a clinic/hospital complex, V2 recommends presenting it as a **pediatric community response district** with themed prehospital sub-areas.

Suggested top-level framing:

- `Map 0` → **Pediatric Community Basics**
- `PM` maps → **Medical Response District**
- `PT` maps → **Trauma Response District**
- `PE` maps → **Pediatric Emergencies District**

Lexi remains the in-world companion. Scout remains the shopkeeper. The environment becomes more professional and simulation-forward.

### 3.2 Tone Guidance

- **Lexi:** training companion, guide, map character
- **Scout:** reward/shop personality
- **FTO/System:** formal evaluation layer

This keeps the district warm without making the entire progression system feel juvenile.

### 3.3 Recommended Collectible System

V2 recommends moving away from toy-style collectibles and replacing them with a more EMS-authentic reward layer:

1. **Challenge coins** — primary map-completion collectibles
2. **Station / unit patches** — branch and convergence milestone rewards
3. **Pins / decals** — lighter-weight side rewards for mini-games, streaks, or special accomplishments

**Why this works better**
- reads as more professional to agencies and instructors
- fits real EMS / fire culture better than toys or medals
- preserves collectibility and visual variety
- avoids the “too formal / unearned” problem that medals or ribbons can create

**Recommended role split**
- **Challenge coins:** one signature collectible per major map completion
- **Station/unit patches:** awarded at major branch or convergence milestones
- **Pins/decals:** smaller recognition items for mini-games, precision, replay, or category mastery

**Important tone note**
- Avoid formal commendation language like “medal” or “ribbon” for routine progression rewards.
- These should feel like earned training memorabilia or station culture items, not acts-of-valor decorations.

### 3.4 Station-Side Reward Framing

Because the maps themselves now represent realistic field scenes, the reward and mini-game layer should be framed as happening **back at station**, **in the rig**, or as **training-space overlays**, not literally in the middle of emergency scenes.

Recommended fiction:
- scenario maps = field calls
- gateway mini-games = pre-shift or training-bay drills
- Scout checkpoints = station-side gear / memorabilia display
- convergence rewards = end-of-branch recognition and progression verification

---

## 4. Recommended V2 Map Sequence

The map IDs and broad instructional order stay the same. The changes are primarily:

- clearer themes
- stronger visual identity
- stronger distinction between gateway, branch, and convergence spaces
- better alignment between map environment and clinical learning goal

### 4.1 Prerequisite Chain (Medical)

```text
Map 0 → PM1 (School & Daycare Intake) ─┬─→ PM2 (Playground & Breathing Calls) ──→ PM5 (Daycare & Sick Child Calls) ────────┐
                                       │─→ PM3 (Community Collapse Calls) ──────────────────────────────────────────────→ PM7 [Medical Key] → PE1 → PE2
                                       └─→ PM4 (Home & Classroom Behavior Calls) ──→ PM6 (Home Safety & Custody Calls) ───┘
```

*PM1 unlocks all three medical branches simultaneously on gateway mini-game completion.*  
*PM7 remains a convergence/key-award hub. It becomes reachable through any completed feeder branch path, but the Medical Key is awarded only when all required medical challenge coins have been collected.*

### 4.2 Prerequisite Chain (Trauma)

```text
Map 0 → PT1 (Playground & Recreation Gateway) ─┬─→ PT2 (Street & Sports Injury Calls) ──→ PT5 (Serious Trauma Progression) ────────┐
                                               │─→ PT3 (Head Injury & Airway Calls) ──→ PT6 (Water & Chest Rescue Calls) ─────→ PT8 [Trauma Key] → PE1 → PE2
                                               └─→ PT4 (Burns, Heat & Exposure Calls) ──→ PT7 (Outdoor Exposure & Animal Calls) ──┘
```

*PT1 unlocks all three trauma branches simultaneously on gateway mini-game completion.*  
*PT8 remains a convergence/key-award hub. It becomes reachable through any completed feeder branch path, but the Trauma Key is awarded only when all required trauma challenge coins have been collected.*

### 4.3 Map Navigation

```text
                    ┬─ PT4 ── PT7 ───────────────────┐
                    │   │                            │
 PT1 ────────────── │─ PT3 ── PT6 ──────────────── PT8 ────┐
  │                 │   │                            │      │
  │                 └─ PT2 ── PT5 ───────────────────┘      │
Map 0 ──                                                   PE1 ── PE2
  │                 ┬─ PM2 ── PM5 ───────────────────┐      │
  │                 │   │                            │      │
 PM1 ────────────── │─ PM3 ── PM6 ───────────────── PM8 ────┘
                    │   │                            │
                    └─ PM4 ── PM7 ───────────────────┘
```

### 4.4 Convergence Gate

```text
PM7 (Medical Response Hub)
              ↘
               PE1 → PE2
              ↗
PT8 (Trauma Response Hub)
```

### 4.5 Progression Logic Notes

- `Map 0` remains the only mixed-domain beginner map.
- `PM1` and `PT1` remain scenario-free gateway maps with mini-games only.
- `PM7` and `PT8` remain convergence/key-award hubs with no scenarios.
- `PE1` and `PE2` remain the advanced synthesis layer.
- Challenge coins are the primary branch collectibles; patches and pins/decals are secondary recognition layers.
- The structural prerequisite logic stays aligned with the original progression contract; V2 changes the **presentation and content framing**, not the unlock architecture.

---

## 5. Map-by-Map V2 Recommendations

## Map 0 — Pediatric Community Basics

**Recommended display name:** `Pediatric Community Basics`  
**Current role:** Entrance  
**Instructional role:** Foundational pediatric scene entry, PAT, first-contact assessment  
**Difficulty:** Beginner

**Theme**
- First contact with pediatric patients
- Core observation before intervention
- “Read the room before you act”

**Design notes**
- Keep this map open, readable, and welcoming.
- Use broad paths, clear sight lines, and obvious community landmarks.
- This map should feel like a neighborhood orientation space, not a maze or a hospital campus.
- Visually, this is where the district should introduce the prehospital aesthetic language of the whole pediatric world.

**Environmental identity**
- Playground, apartment courtyard, school edge, family park, or neighborhood commons
- Pediatric-friendly but not cartoonish
- Color balance should be lighter and clearer than later maps

**Mini-game**
- `PAT Doorway Dash`

**Scenarios**
- `peds_croup_01` — apartment / home call with barking cough, stridor, and caregiver anxiety
- `peds_diabetic_emergency_01` — school, community center, or neighborhood activity collapse with AMS and glucose decision-making
- `peds_trauma_01_soft_tissue` — playground / yard scalp laceration with bleeding control and wound framing
- `peds_trauma_02_partial_choking` — daycare / family gathering choking event with partial obstruction

**Unlocks**
- PM1 and PT1

**Scenario notes**
- The four opening cases work well as mixed-orientation calls.
- Keep cases short-to-medium and highly legible.
- The point here is not depth; it is “see, assess, orient, begin.”

**V2 recommendation**
- Keep this map as the only mixed-domain beginner map.
- Make PAT Doorway Dash feel explicitly like a pre-branch calibration moment.

---

## PM1 — Medical Gateway

**Recommended display name:** `School & Daycare Intake`  
**Current role:** Medical gateway  
**Instructional role:** Pediatric medical orientation and developmental framing  
**Difficulty:** Beginner

**Theme**
- Foundations of pediatric medical thinking
- Developmental context before symptom interpretation

**Design notes**
- This should feel like a school/daycare pickup and intake environment where developmental context matters.
- Compared with Map 0, it should feel slightly more structured and routine-driven.
- Strong signage and branching paths should make the three medical branches feel intentional.

**Environmental identity**
- Daycare check-in area, preschool yard, school front office, pickup lane, developmental-age visual cues
- More “community child setting” than “clinic”

**Mini-game notes**
- Dev Sort fits well here and should remain the gateway mechanic.
- This is one of the maps where the mini-game identity should visually dominate because there are no scenarios.

**Mini-game**
- `Lexi's Development Drill (Dev Sort)`

**Scenarios**
- None — gateway mini-game only

**Unlocks**
- PM2, PM3, PM4

**V2 recommendation**
- Use PM1 to visually and narratively tell the learner: “You are entering pediatric medical reasoning.”

---

## PM2 — Respiratory / Airway

**Recommended display name:** `Playground & Breathing Calls`  
**Instructional role:** Respiratory differentiation and airway escalation  
**Difficulty:** Intermediate

**Theme**
- The child who looks like they can crash through breathing failure
- Differentiating upper airway, lower airway, allergic, and infectious patterns

**Design notes**
- This map should feel tense but not chaotic.
- Visually, use exertion and breathing-trigger cues: playground equipment, outdoor air, sports corners, daycare nap areas, pickup urgency.
- The environment should suggest a child who suddenly looks like they might be tiring out.

**Environmental identity**
- Playground, recess yard, daycare room, school nurse overflow, sports sideline
- Breathing-trigger and observation cues rather than hospital-bay cues
- Slightly cooler palette than PM1

**Mini-game**
- `Sound Check`

**Scenarios**
- `Allergic Reaction` — school cafeteria, party, or snack-time exposure scene
- `peds_asthma_01` — recess, sports, or playground-triggered asthma exacerbation
- `Epiglottitis` — home or daycare pickup child with drooling, tripod, and hands-off airway concern
- `peds_anaphylaxis_01` — field anaphylaxis call with escalation under time pressure

**Unlocks**
- PM5

**Scenario notes**
- This is a very strong branch clinically and should feel like one of the flagship pediatric maps.
- Mild allergy → asthma → epiglottitis/anaphylaxis creates a good escalation ladder.

**V2 recommendation**
- Make this one of the most polished and visually distinct maps in the district because respiratory differentiation is a high-yield EMS learning area.

---

## PM3 — Cardiac / Perfusion

**Recommended display name:** `Community Collapse Calls`  
**Instructional role:** Syncopal, rhythm, perfusion, and early shock recognition  
**Difficulty:** Intermediate

**Theme**
- “The patient may not look catastrophic yet, but perfusion is telling the truth.”

**Design notes**
- This map should feel more controlled and observational than PM2.
- Visual language should suggest collapse in public or supervised spaces where bystanders, caregivers, and activity context matter.
- This is a good map for cleaner geometry and stronger “something is wrong in a public place” motifs.

**Environmental identity**
- Gym, recital hall, church/community center, school hallway, after-school event space
- Public-setting collapse cues rather than monitored-clinic cues
- Good place for Scout’s checkpoint because it sits at a structural midpoint

**Mini-game**
- `Shock Spotter`

**Scenarios**
- `peds_syncope_01` — school hallway, recital, or sports-side collapse with prodrome and differentiation
- `Pediatric Bradycardia` — supervised public setting with poor perfusion and caregiver concern
- `Pediatric Tachycardia` — activity or illness-associated rapid rate requiring rhythm framing
- `Pediatric Sepsis` — subtle but concerning sick child in community setting with evolving perfusion changes

**Scout / Shop note**

**Unlocks**
- PM8

**Scenario notes**
- This branch can easily become “misc medical.” Guard against that by keeping perfusion/circulation as the identity anchor.

**V2 recommendation**
- Rename the map theme away from `Cardiac/AMS` and more toward **perfusion/circulation** so it feels less blended and more intentional.

---

## PM4 — AMS / Behavioral / Neuro

**Recommended display name:** `Home & Classroom Behavior Calls`  
**Instructional role:** Pediatric altered mental status, neurologic red flags, behavioral complexity  
**Difficulty:** Intermediate

**Theme**
- “What is driving the altered presentation?”

**Design notes**
- This map should feel less purely clinical and more cognitively uneasy.
- Use visual layering, mild asymmetry, and more compressed layouts to reflect diagnostic ambiguity.
- Avoid making it “dark” or horror-coded; it should feel complex, not ominous.

**Environmental identity**
- Classroom, bedroom, counselor office, after-school room, family living space
- Family/stress dynamics more visible
- Slightly more enclosed than PM2/PM3

**Mini-game**
- `Differential Dash — AMS Edition`

**Scenarios**
- `peds_febrile_seizure_01` — home or daycare seizure/post-ictal scene
- `Meningitis` — sick child at home/classroom with fever, neck stiffness, rash concern
- `Suicidal Adolescent` — bedroom, school counseling, or family crisis setting
- `Unattended Teen Refusal` — public or school-adjacent refusal without clear guardian availability

**Unlocks**
- PM6

**Scenario notes**
- Febrile seizure is a strong branch intro.
- This branch benefits from the widest emotional range of the medical maps.

**V2 recommendation**
- Make this the most diagnostically ambiguous medical branch before operations/legal complexity appears in PM6.

---

## PM5 — Infectious Respiratory

**Recommended display name:** `Daycare & Sick Child Calls`  
**Instructional role:** Respiratory infection differentiation and transport framing  
**Difficulty:** Intermediate

**Theme**
- “This child is sick, but why are they sick and how fast can they get worse?”

**Design notes**
- This map should feel more contained and more isolation-aware than PM2.
- It should be visually related to PM2 but not redundant.
- Use pickup-room, daycare illness corner, school exclusion, and outbreak cues rather than airway-only cues.

**Environmental identity**
- Daycare illness room, classroom pickup area, family shelter, crowded community setting
- A more contained, monitored feeling
- Good place for exposure, isolation, and contagion logic

**Mini-game**
- `Differential Dash — Difficulty Breathing Edition`

**Scenarios**
- `Pneumonia` — daycare/school exclusion call with fever, cough, and hypoxia concern
- `Bronchiolitis` — infant home or daycare illness with feeding difficulty and increased work of breathing
- `Pertussis` — prolonged coughing illness in family/community environment with contagion framing

**Scenario notes**
- This is a good example of a branch that is narrower clinically but still high-value educationally.

**V2 recommendation**
- Use map language and art to distinguish “infectious respiratory” from “airway emergency” so PM2 and PM5 do not blur together.

---

## PM7 — Child Safety / Operations

**Recommended display name:** `Home Safety & Custody Calls`  
**Instructional role:** Mandatory reporting, refusal/legal complexity, child protection  
**Difficulty:** Intermediate

**Theme**
- “Being right clinically is not enough; you also have to act responsibly.”

**Design notes**
- This map should feel more administrative, observational, and socially complex.
- It should visually communicate that the challenge here is not just physiology.
- This is a strong place for more environmental storytelling.

**Environmental identity**
- Homes, custody exchange locations, school pickup conflicts, neglected living environments
- Documentation, accountability, and situational judgment cues
- Less “treatment bay,” more “provider judgment under uncertainty”

**Mini-game**
- `TEN-4 FACES`

**Scenarios**
- `Child Abuse` — home or caregiver scene with inconsistent history
- `Child Neglect` — living environment / failure-to-thrive / chronic concern call
- `Refusal of Treatment for a Minor` — parent or guardian conflict scene requiring judgment and consultation

**Scenario notes**
- This branch is important for real EMS relevance and differentiates the platform from treatment-only sims.

**V2 recommendation**
- Treat PM6 as one of the signature “this product understands EMS beyond interventions” maps.


## PM6 — Pediatric Cardiac Arrest

**Recommended display name:** `Pediatric Cardiac Arrest`  
**Instructional role:** Advanced resuscitation and safe sleep scenes  
**Difficulty:** Advanced

**Theme**
- "High performance under the ultimate stress test."

**Scenarios**
- `Infant Safe Sleep / SUIDI` — scene management, SIDS/SUIDI response, caregiver support, documentation
- `VFib Arrest` — pediatric shockable rhythm, AED application, CPR ratio management

**Unlocks**
- PM8


## PM8 — Medical Convergence

**Recommended display name:** `Medical Response Hub`  
**Instructional role:** Medical-track closure and readiness check  
**Difficulty:** N/A

**Theme**
- Medical-track completion
- Consolidation before advanced convergence

**Design notes**
- This should feel distinct from branch maps.
- More ceremonial, more hub-like, more clearly a progression checkpoint.
- The learner should immediately understand: “this is a milestone space.”

**Environmental identity**
- Community command plaza / response hub / milestone checkpoint
- Scout’s presence should feel more important here than at ordinary checkpoints

**Mini-game**
- None

**Scenarios**
- None — convergence/key-award hub only

**V2 recommendation**
- Keep this scenario-free.
- Let coin/patch verification own the identity of the space.
- This is a good place to award the **Medical Key** plus a branch-completion patch once the medical collection requirements are satisfied.

---

## PT1 — Trauma Gateway

**Recommended display name:** `Playground & Recreation Gateway`  
**Instructional role:** Pediatric trauma orientation and body-region framing  
**Difficulty:** Beginner

**Theme**
- “Trauma starts with mechanism, body region, and threat prioritization.”

**Design notes**
- This should parallel PM1 structurally but feel more kinetic and mechanism-oriented.
- Visuals should suggest falls, impacts, play equipment, and body-region thinking.

**Environmental identity**
- Playground, bike area, recreation zone, schoolyard edge
- More rugged than PM1
- Good visual cues for body mapping and injury zones

**Mini-game notes**
- Rule of Nines is a clean gateway tool here.

**Mini-game**
- `Rule of Nines`

**Scenarios**
- None — gateway mini-game only

**Unlocks**
- PT2, PT3, PT4

**V2 recommendation**
- Make the PM1/PT1 contrast obvious: medical gateway = patient context, trauma gateway = mechanism/body mapping.

---

## PT2 — Bleeding / Blunt Trauma

**Recommended display name:** `Street & Sports Injury Calls`  
**Instructional role:** Hemorrhage control and internal injury suspicion  
**Difficulty:** Intermediate

**Theme**
- “What is bleeding, and what might be bleeding where you can’t see it?”

**Design notes**
- This map should feel grounded and physical.
- Use stronger impact/mechanism environmental cues than the medical side.
- This is a good branch for bold visual pathways and visible injury-energy storytelling.

**Environmental identity**
- Backyard play structures, sports field edge, curbside, bike trail, driveway, skate area
- Impact, force, and bleeding-control cues
- Slightly harsher palette than the medical maps

**Mini-game**
- `Stop the Bleed`

**Scenarios**
- `Bleeding Control` — sports/playground or bike crash hemorrhage-control intro
- `peds_trauma_06_handlebar` — bike / driveway / park-trail handlebar abdominal injury
- `Abdominal Blunt Trauma` — sports or recreation blunt-force abdominal mechanism
- `Penetrating Trauma` — yard / park / public-space wound management and internal injury suspicion

**Unlocks**
- PT5

**Scenario notes**
- Branch intro via Bleeding Control is strong and intuitive.

**V2 recommendation**
- Keep the map tightly focused on hemorrhage and blunt-force reasoning so it does not become a generic trauma bucket.

---

## PT3 — Neuro / Airway Trauma

**Recommended display name:** `Head Injury & Airway Calls`  
**Instructional role:** Neurovascular checks, GCS, spinal concerns, trauma airway  
**Difficulty:** Intermediate

**Theme**
- “The trauma patient who may deteriorate neurologically or lose the airway.”

**Design notes**
- This should feel more severe and more tightly controlled than PT2.
- Visual language should suggest head/spine/airway vigilance.
- This is a good place for more constrained routing and stronger clinical tension.

**Environmental identity**
- Roadside, pool deck, skate park, fall zone, parking lot edge
- Spine/airway/neuro cues
- More compressed than PT2
- Good location for the trauma-side checkpoint

**Mini-game**
- `GCS Matcher`

**Scenarios**
- `peds_trauma_03_extremity` — playground / sports / curbside fracture with neurovascular checks
- `peds_trauma_05_auto_ped` — roadside or parking-lot high-MOI auto-pedestrian
- `Traumatic Brain Injury` — fall, collision, or recreational head-injury call with decreasing mentation
- `Unconscious Patient with Vomiting` — airway-with-C-spine scene in a public or outdoor location

**Scout / Shop note**
- Midpoint reward/checkpoint node also fits naturally here as the trauma-side structural checkpoint, but again should read as a station/training interaction rather than an in-scene vendor.

**Unlocks**
- PT6

**Scenario notes**
- Extremity fracture as the intro works if the neurovascular framing remains explicit.

**V2 recommendation**
- Keep emphasizing that this is not “general trauma,” but neuro/airway trauma specifically.

---

## PT4 — Environmental / Toxins

**Recommended display name:** `Burns, Heat & Exposure Calls`  
**Instructional role:** Burns, heat, poisoning, stings/envenomation  
**Difficulty:** Intermediate

**Theme**
- “The environment or exposure is part of the patient problem.”

**Design notes**
- This map should have the widest environmental contrast of the trauma branches.
- Use stronger location variety and visual cues that make it feel distinct from the force-based trauma maps.

**Environmental identity**
- Campsite, fairground, picnic shelter, garage, chemical storage edge, summer event space
- Heat, chemical, burn, and exposure cues
- More environmental storytelling than PT2/PT3

**Mini-game**
- `MOI Mapper`

**Scenarios**
- `peds_trauma_04_burn` — grill, campfire, kitchen spill, or public-event burn intro
- `Heat Emergency` — sports field, playground, parked-car, or summer event overheat scene
- `Accidental Ingestion/Poisoning` — home, garage, or public venue exposure call
- `Insect Bite/Envenomation` — park, campsite, or fairground allergic/envenomation scene

**Unlocks**
- PT7

**Scenario notes**
- Burns remains a strong branch intro because it anchors both thermal injury and the Rule of Nines connection.

**V2 recommendation**
- Keep this branch broad, but make the unifying idea “exposure changes the patient” rather than “misc trauma.”

---

## PT5 — Shock / Multi-Site Injury

**Recommended display name:** `Serious Trauma Progression`  
**Instructional role:** Hemorrhagic shock, progression, and competing priorities  
**Difficulty:** Intermediate

**Theme**
- “This child is losing compensation.”

**Design notes**
- This map should feel more urgent than PT2.
- It should visually signal progression and deterioration.
- Use tighter paths and stronger acuity cues.

**Environmental identity**
- Larger public injury scenes, roadside chaos, multi-injury outdoor spaces
- Deterioration / shock / urgency
- More compressed and high-stakes than early trauma maps

**Mini-game**
- `Shock Spotter — Trauma Edition`

**Scenarios**
- `Hemorrhagic Shock` — major outdoor/public injury with evolving shock physiology
- `Shock Management` — compensated shock recognition in a field trauma context
- `Complex Extremity Fracture` — femur / vascular compromise scene with competing priorities

**V2 recommendation**
- Make PT5 feel like a true second-tier trauma branch, not just PT2 with harder cases.

---

## PT6 — Thoracic / Submersion

**Recommended display name:** `Water & Chest Rescue Calls`  
**Instructional role:** Thoracic threat recognition and oxygenation rescue  
**Difficulty:** Intermediate

**Theme**
- “Air and breathing are now failing because of trauma or submersion.”

**Design notes**
- This branch should feel different from PT3 even though both include airway elements.
- PT3 is neuro/airway trauma management; PT6 is oxygenation rescue and thoracic consequence.

**Environmental identity**
- Pool deck, lakeside edge, marina walkway, riverside park, chest-injury rescue context
- Water / chest / rescue / respiratory compromise cues
- This branch benefits from strong visual rhythm and rescue-space identity

**Mini-game**
- `BLS Sequence`

**Scenarios**
- `Chest Injury / Pneumothorax` — bike, sports, vehicle, or fall chest-trauma call
- `Near-Drowning / Submersion` — pool, pond, beach, or lakeside rescue call
- `Rib Fractures with Respiratory Compromise` — impact injury with worsening breathing in the field

**V2 recommendation**
- Distinguish PT6 from PT3 through rescue/oxygenation identity rather than generic airway language.

---

## PT7 — Advanced Environmental

**Recommended display name:** `Outdoor Exposure & Animal Calls`  
**Instructional role:** Hypothermia, bites, dehydration, advanced environmental decision-making  
**Difficulty:** Intermediate

**Theme**
- “The environment keeps shaping the patient after the initial problem.”

**Design notes**
- This should feel more remote, more exposed, and more situational than PT4.
- PT4 is exposure category-building; PT7 is consequence management and escalation.

**Environmental identity**
- Trailhead, snowy park, wooded edge, dog park perimeter, remote recreation area
- Cold, exposure, animal, wilderness-adjacent cues
- Strong thematic contrast from the more contained medical maps

**Mini-game**
- `Temp Check`

**Scenarios**
- `Dog Bite / Animal Attack` — neighborhood yard, park, or trailhead animal injury
- `Hypothermia / Frostbite` — winter outdoor exposure or underdressed-child cold scene
- `Dehydration` — heat, illness, or prolonged outdoor event pediatric dehydration call

**V2 recommendation**
- Make PT7 feel like a late-branch environment map, not a leftover collection of cases.

---

## PT8 — Trauma Convergence

**Recommended display name:** `Trauma Response Hub`  
**Instructional role:** Trauma-track closure and readiness check  
**Difficulty:** N/A

**Theme**
- Trauma-track completion
- Readiness to enter mixed high-acuity pediatric emergencies

**Design notes**
- Mirror PM7 in structural purpose but not necessarily art details.
- Should feel like a progression checkpoint with more rugged energy than PM7.

**Environmental identity**
- Community command plaza / trauma response hub / key checkpoint

**Mini-game**
- None

**Scenarios**
- None — convergence/key-award hub only

**V2 recommendation**
- Keep this scenario-free and treat it as a progress-verification space, not a teaching map.
- This is a good place to award the **Trauma Key** plus a trauma branch-completion patch once the trauma collection requirements are satisfied.

---

## PE1 — Integrated Pediatric Emergencies

**Recommended display name:** `Complex Community Emergencies`  
**Instructional role:** First true interleaving and multi-system differentiation  
**Difficulty:** Advanced

**Theme**
- “The map no longer tells you what category this is.”

**Design notes**
- This should feel like a real escalation in complexity.
- It should visually signal convergence, urgency, and uncertainty.
- Use less branch-specific symbolism and more high-acuity integrated world cues.

**Environmental identity**
- Multi-system community emergency scenes: MVC zones, public venues, housing clusters, mixed-access response spaces
- Less playful, more serious
- Tighter routing and stronger high-acuity atmosphere

**Mini-game**
- None

**Scenarios**
- `Vehicle Accident` — multi-injury community MVC scene
- `Difficulty Breathing` — ambiguous high-acuity pediatric respiratory call without obvious branch identity
- `Altered Mental Status` — multi-etiology community AMS scene
- `Respiratory Arrest` — impending/early arrest with family pressure and rapid escalation

**Scenario notes**
- This is where the blocked-practice structure intentionally gives way to interleaving.
- The map should feel like the learner has entered a new mode of thinking.

**V2 recommendation**
- Make PE1 feel like the first true “boss map,” even before PE2.

---

## PE2 — High-Acuity Pediatric Emergencies

**Recommended display name:** `High-Acuity Pediatric Crisis Zone`  
**Instructional role:** Final high-acuity synthesis and prioritization  
**Difficulty:** Advanced

**Theme**
- “Multiple threats are present, and the order of your thinking matters.”

**Design notes**
- This should be the tightest, most urgent, and most serious map in the district.
- Visual clutter should increase only in a controlled way; readability still matters.
- This is where the district should feel most like a true advanced sim environment.

**Environmental identity**
- Final-stage prehospital crisis environment with layered scene pressure, multiple priorities, and constrained access
- Dense, urgent, high-acuity, but still legible

**Mini-game notes**
- Priority Stack after final scenario remains a strong capstone position.

**Mini-game**
- `Priority Stack` — post-scenario synthesis capstone

**Scenarios**
- `Crashing Patient` — initially stable child who deteriorates on scene
- `Multi-System Trauma` — high-acuity pediatric trauma with competing airway, hemorrhage, and neuro threats
- `Pediatric Cardiac Arrest` — field arrest with CPR, AED, family presence, and team-priority pressure

**V2 recommendation**
- Treat PE2 as the instructional and emotional payoff of the whole district.

---

## 6. Recommended V2 Naming Pattern

If you want a more professional-facing version without fully renaming the IDs, use:

- `Map 0` → Pediatric Community Basics
- `PM1` → School & Daycare Intake
- `PM2` → Playground & Breathing Calls
- `PM3` → Community Collapse Calls
- `PM4` → Home & Classroom Behavior Calls
- `PM5` → Daycare & Sick Child Calls
- `PM6` → Home Safety & Custody Calls
- `PM7` → Medical Response Hub
- `PT1` → Playground & Recreation Gateway
- `PT2` → Street & Sports Injury Calls
- `PT3` → Head Injury & Airway Calls
- `PT4` → Burns, Heat & Exposure Calls
- `PT5` → Serious Trauma Progression
- `PT6` → Water & Chest Rescue Calls
- `PT7` → Outdoor Exposure & Animal Calls
- `PT8` → Trauma Response Hub
- `PE1` → Complex Community Emergencies
- `PE2` → High-Acuity Pediatric Crisis Zone

This preserves the internal IDs while making the visible map language more polished.

---

## 7. V2 High-Level Recommendations

### Keep

- Single entrance map
- Dual medical/trauma track structure
- Mini-game gateways at PM1/PT1
- PM7/PT8 as convergence/key hubs
- PE1/PE2 as integrated high-acuity maps

### Strengthen

- branch-specific visual identity
- professional-facing display names
- distinction between branch maps and convergence hubs
- environmental storytelling tied to clinical learning objective
- station-authentic collectible language such as challenge coins, patches, and decals

### Avoid

- making every map equally whimsical
- letting similar maps visually blur together
- turning convergence maps into ordinary scenario nodes
- over-literal iconography that cheapens the sim tone

---

## 8. Suggested Next Planning Step

Use this V2 document as the basis for a **map art brief** and **content sequencing brief**.

Recommended follow-on artifacts:

1. **Visual brief per map**
   palette, atmosphere, landmark objects, density, path style, Scout/Lexi placement

2. **Instructional brief per map**
   dominant learning goal, branch identity, convergence purpose, emotional tone

3. **Naming pass**
   finalize learner-facing display names while keeping current internal IDs stable

4. **Map-by-map production priority**
   identify which maps most need redesign first based on learner impact and distinctiveness

---

## 9. Summary

The original pediatric map design has a strong progression backbone. V2 does not replace that backbone. It refines the district into a more coherent, marketable, and instructionally legible world.

The biggest V2 ideas are:

- keep the progression structure
- professionalize the visible map framing
- anchor the district in believable prehospital pediatric scenes
- replace toy-style rewards with challenge coins, patches, and pins/decals
- give each map a clearer instructional and visual identity
- make convergence spaces feel like real milestones
- preserve Lexi and Scout as companion characters without making the district itself feel childlike
