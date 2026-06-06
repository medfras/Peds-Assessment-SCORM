# Theme Update V2

**Status:** Planning Draft  
**Last Updated:** 2026-04-30  
**Purpose:** Consolidate the planned presentation/theme changes for RescueTrails into one design reference. This document covers category naming, district framing, reward presentation, badge/challenge/swag role separation, color direction, home-page direction, and migration guidance. It is planning-only and does not change current live implementation by itself.

---

## 1. V2 Intent

Theme Update V2 is meant to solve a specific product tension:

- the platform needs to remain warm, supportive, and engaging for repeated learner use
- the outer framing needs to feel more professional, prehospital, and agency-purchasable across **EMS and fire/rescue operations**

The goal is **not** to remove personality from the product. The goal is to move the overall presentation from a whimsical game shell toward a **station dashboard + district map** training environment while preserving:

- Lexi as the companion and coaching presence
- deterministic backend authority
- progression clarity
- collectibility and learner motivation

V2 should read as:

- **serious EMS / fire-rescue training product**
- **warm companion-guided experience**
- **prehospital scene-based world**

not:

- childish mascot game
- sterile compliance portal
- hospital-floor simulator

### 1.1 Product Name Reframing

V2 does **not** require a product rename.

`RescueTrails` still works if the meaning of **Trails** is reframed away from literal dog-walking and toward:

- training pathways
- response pathways
- district progression routes
- guided routes to readiness

The product name should therefore be treated as a **meaning migration**, not an automatic rebrand:

- old implied meaning: walking with Lexi through playful trails
- planned V2 meaning: progressing through rescue training pathways across districts

This lets the platform keep brand continuity while modernizing the surrounding fiction.

---

## 2. Core Theme Principles

### 2.1 What Must Stay

- **Lexi remains the learner companion**
  Lexi continues to support navigation, encouragement, and debrief coaching.

- **The FTO/system remains the formal evaluator**
  The score, pass/fail framing, and official evaluation language should remain formal and authoritative.

- **Scenarios remain prehospital**
  The world should be dominated by calls EMS and fire/rescue agencies actually run: homes, schools, playgrounds, roadways, public spaces, workplaces, community events, sports/recreation settings, rescue environments, and hazard scenes.

- **Backend progression and reward logic remain authoritative**
  This is a presentation/theme update, not a move of authority into the UI.

### 2.2 What Must Change

- **Outer product framing**
  Menus, districts, categories, and rewards should look like a station/training ecosystem rather than a toy shelf.

- **Category naming**
  High-level categories should read like prehospital response domains and scene families, not just hospital-adjacent medical buckets.

- **Reward presentation**
  Visible collectible language should shift away from toys toward EMS / fire-rescue-authentic memorabilia.

- **Home-page information architecture**
  The home experience should feel like a station dashboard with major districts laid out on a map.

- **Supporting language around the product name**
  Product copy should explain trails as training routes, readiness pathways, and district progression rather than pet-walking metaphors.

---

## 3. Theme Role Split

V2 works best if different layers of the experience have clearly different jobs.

| Layer | Planned role | Tone |
|---|---|---|
| Lexi | Companion, guide, coach, debrief voice | Warm, supportive, non-judgmental |
| FTO/System | Evaluation, scoring, official progress record | Professional, concise, objective |
| District world | Training-space framing and navigation | Operational, prehospital, memorable |
| Rewards | Progression and identity display | Professional, collectable, culturally authentic |

This separation prevents role confusion:

- Lexi is not the formal scorer
- the FTO is not the mascot
- rewards are not the same thing as assessment mechanics

### 3.1 Locked Theme Decisions

The following V2 theme decisions are now treated as the planned direction unless superseded by a later design revision:

- **Treats remain the visible currency name**
- **Dog Park maps forward to a Training Center / drill hub concept, not the Complex Incident district**
- **The platform palette moves away from the current brown-forward theme**
- **Simulation mode follows that shift and moves toward a dark gray / black operational base rather than warm brown-black**

---

## 4. Planned Category Names and Themes

These are the recommended top-level planned categories for the home page and district-map navigation.

### 4.1 Top-Level Districts

| Planned district | Core theme | Content family | Environment cues |
|---|---|---|---|
| **Pediatric Community Response District** | Pediatric calls in community settings | Pediatric medical, pediatric trauma, pediatric emergencies | Schools, daycares, playgrounds, homes, parks, public events |
| **Adult Medical Response District** | Adult illness and collapse response | Respiratory, cardiac, neuro, endocrine, infectious, general adult medical | Homes, workplaces, apartments, public buildings, sidewalks, transit |
| **Adult Trauma & Rescue Response District** | Adult injury, mechanism-driven, and rescue-oriented calls | MVCs, falls, bleeding, industrial, violence, environmental trauma, rescue/extrication contexts | Roadways, job sites, recreation areas, alleys, sidewalks, industrial lots, vehicle rescue scenes |
| **Complex Incident Response District** | Mixed-domain, convergence, advanced/high-acuity training | Multi-system emergencies, command-heavy incidents, advanced decision-making, synthesis content | Multi-patient scenes, chaotic public settings, complex transport/command environments, fireground-adjacent operations |

### 4.2 District Independence

All four districts are **fully independent and parallel**. There is no required order, no dependency chain, and no relationship between districts. Learners may enter any district at any time after orientation. Progress in one district has no bearing on access to another.

This is a deliberate instructional design choice:

- agencies can assign specific districts without requiring learners to complete unrelated content first
- learners self-direct based on their own clinical growth areas
- platform IA should reflect this — there is no “district 1 → district 2” hierarchy

### 4.3 District Design Notes

#### Pediatric Community Response District
- Should feel readable, community-based, and family-facing
- Best fit for the prehospital pediatrics direction already being developed in `PEDIATRIC_MAP_DESIGN_V2.md`
- Should emphasize schools, homes, community recreation, and public pediatric spaces rather than hospitals

#### Adult Medical Response District
- Should feel more civilian, everyday, and medically varied
- Good fit for apartment complexes, office buildings, retail settings, sidewalks, gyms, houses, public transportation
- Visual tone can be calmer and more observational than trauma districts

#### Adult Trauma & Rescue Response District
- Should feel more kinetic, mechanism-driven, and operational
- Use roadways, industrial sites, sports/recreation, violence-adjacent environments, environmental hazards, and rescue/extrication contexts
- This district can carry sharper contrast, more hazard striping, more night/dusk variants, and more urgency cues

#### Complex Incident Response District
- Should feel like synthesis, not just “harder versions” of the other districts
- Good fit for scenes with multiple competing priorities, noisy environments, handoff complexity, scene management, mixed-domain uncertainty, and command/rescue coordination
- This district should visually communicate escalation and convergence

---

## 5. Reward System Role Clarification

One of the main V2 goals is to stop rewards from feeling muddy.

### 5.1 Planned Role Split

| System | Purpose | Learner meaning |
|---|---|---|
| **Challenges** | Assessment interactions inside scenarios or drills | “What skill did I demonstrate right now?” |
| **Badges** | Achievement/competency markers | “What meaningful milestone or pattern have I earned?” |
| **Swag** | Collection/progression/identity layer | “Which districts, branches, and specialties have I completed?” |

### 5.2 Challenges

Challenges should remain:

- assessment mechanics
- skill checks
- evidence generators for scoring/debrief

Challenges are **not** the collectible layer and should not be presented as loot.

Examples:

- impression challenge
- medication math challenge
- ECG interpretation challenge
- sequencing challenge

### 5.3 Badges

Badges should become more clearly **achievement and competency markers**, not generic collectibles.

Recommended badge functions:

- first no-hint mastery run
- repeated high performance in a skill family
- clean documentation streak
- strong differential reasoning
- consistent airway or med-math accuracy

Badges should answer:

> “What notable thing has this learner demonstrated?”

#### Badge Redesign — Planned Work

The current badge system needs a redesign pass to make badge roles, triggers, and visual identity clearly distinct from swag. This is a **planned work item** that needs a dedicated design document before implementation. The redesign should define:

- the complete badge taxonomy (what badge families exist, what triggers each)
- how badge display differs from swag display in the UI
- how badges are earned relative to district progression vs. skill demonstration
- visual language for badges vs. coins vs. patches

Do not implement badge changes under V2 until this design pass is complete.

### 5.4 Swag

Swag should become the visible collection and identity layer.

Recommended swag hierarchy:

- **Challenge coins** — primary district/map completion collectibles
- **Station/unit patches** — branch and convergence milestone rewards
- **Pins/decals** — smaller side rewards for mini-games, streaks, category mastery, or specialty accomplishments

Swag should answer:

> “Where has this learner progressed, and what kind of provider identity is taking shape?”

### 5.5 Are They Complementary or Overlapping?

They should be **complementary**.

They become overlapping only if:

- the same exact event grants both a badge and a swag item with the same meaning
- both systems are presented as generic collectibles
- users cannot tell which system reflects skill versus progression

### 5.6 V2 Recommendation

Do **not** collapse badges and swag into one system.

Instead:

- keep **badges** as competency/achievement markers
- keep **swag** as district progression and identity collectibles
- keep **challenges** as assessment mechanics only

That gives each layer a distinct motivational job.

---

## 6. Planned Reward Presentation

### 6.1 Recommended Visible Collectible Types

1. **Challenge coins**
2. **Station/unit patches**
3. **Pins/decals**

### 6.2 Why These Work

- stronger fit with EMS / fire-rescue culture than toys, ribbons, or medals
- better B2B optics for chiefs, training officers, and agencies
- more visual variety than ribbons alone
- avoids “stolen valor” or overclaim problems that medals can create

### 6.3 Recommended Use

| Reward type | Recommended use |
|---|---|
| Challenge coin | Signature collectible for a district/map completion or clinically meaningful map milestone |
| Station/unit patch | Branch completion, convergence completion, specialty identity |
| Pin/decal | Mini-games, streaks, side achievements, focused mastery |

### 6.4 Station-Side Framing

Because the district maps are increasingly scene-authentic, the reward and drill layer should feel **station-side**, not literally embedded in active emergency scenes.

Recommended fiction:

- scenarios = field calls
- district navigation = training coverage map / response district board
- mini-games = pre-shift drills / training bay / en route review
- swag display = station board, locker wall, challenge coin case, patch panel

### 6.5 Treats Stay

V2 keeps **Treats** as the visible currency name.

Rationale:

- Treats still fit the Lexi/Scout companion fiction
- the term is less procurement-sensitive than toys or toy chest language
- keeping treats avoids unnecessary economy churn while other presentation layers are being modernized

The visible fiction should be:

- Scout accepts treats
- treats help unlock hints or station swag access
- treats belong to the companion/quartermaster layer, not the formal evaluation layer

So the recommended V2 split is:

- **Treats** stay
- **Toys** go away
- **Swag / challenge coins / patches / pins** replace the visible collectible layer

---

## 7. Planned Home Page Direction

### 7.1 Core Home Concept

The home page should evolve into a **station dashboard** with the major category areas laid out on a **district map**.

It should feel closer to:

- operations board
- station map
- training readiness dashboard

than to:

- card carousel
- generic app launcher
- toy shelf

### 7.2 Home Page Structure

The home page **must** be built around a district map as the primary navigation surface. All four districts appear on the map simultaneously with equal visual weight. No district is presented as a prerequisite for another.

#### Primary center area
- **District map** is the main navigation object — a top-down or isometric board showing all four response districts
- Each district is labeled with its full V2 name
- Each district shows visible progress state (percent complete, node status, or coverage ring)
- Districts are directly clickable from the map — no intermediate menu layer

#### Supporting panels
- `Next Rep` — surfaced as a specific recommended next scenario or drill, not a generic "keep going" CTA
- XP / rank / streak summary — compact, top-of-panel, does not compete visually with the map
- Badge highlights — single most recent or notable badge, link to full badge wall
- Swag display — one or two recent collectibles (coin or patch), link to full station display
- Training Center shortcut — labeled as Training Center, positioned as a sidebar or fixed panel action rather than a district on the map

#### Orientation entry point
- After orientation is complete: display a small "Replay orientation" link at the bottom of the home page — unobtrusive, not a primary CTA
- Before orientation is complete: learner is routed directly to the orientation firehouse and does not see the main home page

### 7.3 Home Page Tone

- professional, warm, clearly EMS / fire-rescue training-oriented
- not sterile, not whimsical-first
- Lexi can appear with a short contextual nudge (e.g. next rep suggestion or streak acknowledgment) but should not dominate the layout
- the station-dashboard frame carries the first impression; Lexi supports it

### 7.4 Home Page Copy Direction

Prefer:

- district
- response area
- training board
- readiness
- progression
- next rep
- field guide
- training trail
- response pathway
- readiness route
- challenge coin / patch / decal

Avoid centering language like:

- toy chest
- treat shelf
- puppy park
- walking the dog
- dog walk
- pet trail
- playful biome names as primary IA

---

## 7A. Orientation Map

The **Station 1 Firehouse Orientation** is a fully separate first-login experience, not a district.

Key facts:

- Automatically triggered on first login; the learner never sees the main home page until orientation is complete
- Firehouse map theme — distinct from the four response districts
- Contains a guided mini-game node and a sample orientation scenario (`orientation_01`)
- `orientation_01` is a low-stakes, station-side practice scenario (not a real patient call)
- Orientation guidance cues from Lexi walk the learner through core UI interactions during the scenario
- After completing the orientation scenario, a **"Start your shift"** CTA navigates to the main home page
- Orientation is marked complete on the server via a nullable `orientation_completed_at` timestamp on the user record
- Replay is available via a small link at the bottom of the home page after first completion; replay does not re-award XP/treats/badge
- Full design specification: [docs/ORIENTATION_MAP_DESIGN.md](docs/ORIENTATION_MAP_DESIGN.md)

---

## 8. Planned Color Direction

V2 should be an **evolution**, not a total visual reboot.

The current warm palette is a strength. The update should make it feel more operational and station-authentic without collapsing into generic gray enterprise UI.

### 8.1 Theme Direction

Keep the dual-theme principle:

- **Menu / dashboard / learning mode**
- **Active simulation / urgency mode**

Move the whole system away from the current brown-forward theme:

- dashboard/menu mode becomes **station board / field notebook / operations board**
- simulation mode becomes **dark operational console / apparatus bay / command-screen**

These are the committed directions for V2. The current warm brown should not persist as the default base color for either mode.

### 8.2 Menu / Dashboard Palette

**Base colors:**

- off-white / paper white as primary background
- steel gray / silver as mid-tone surface
- slate-charcoal as dark surface and panel contrast
- neutral black accents

**Operational accents:**

- deep fire red — primary brand action color
- rescue / EMS blue — secondary operational accent
- restrained gold / brass — progression signals and premium states
- restrained amber — warning and highlight utility only; not decorative

**Visual character target:**

- less “storybook parchment”
- less warm brown dominance
- more “station wall board,” “field notebook,” or “incident planning board”
- more steel, slate, painted apparatus, console, and operations-board cues

### 8.3 Simulation Palette

The current brown-black simulation direction is **not** the V2 target. Replace it with:

**Base:**
- dark gray / near-black background
- cool charcoal panels and surfaces
- white / off-white primary text

**Functional accents:**
- red — critical alerts only
- blue — operational and informational accents
- amber — caution states only; not ambient color
- silver / graphite — structural surfaces and dividers

**Refinement targets:**
- cleaner panel hierarchy between FTO evaluation surfaces and Lexi coaching surfaces
- consistent accent usage across scenario view, debrief, and challenge modals
- FTO surfaces should read as formal/authoritative; Lexi surfaces should read as warm/conversational — these must be visually distinguishable

### 8.4 District Accent Color Strategy

Each district gets a consistent accent family applied to its map tile, progress indicators, and district-level UI chrome. These are guidance accents, not full-screen washes.

| District | Accent family |
|---|---|
| Pediatric Community Response | sky blue / teal + restrained gold |
| Adult Medical Response | deep blue + muted cyan |
| Adult Trauma & Rescue Response | fire red + hazard amber |
| Complex Incident Response | slate + command gold |

No district should be visually dominant over the others on the home-page map. Equal visual weight is the goal.

### 8.5 Reward Presentation Colors

Reward display should feel premium but grounded:

- challenge coins = brushed metal / enamel color accents
- patches = stitched fabric-inspired surfaces
- pins/decals = smaller bright accents

Avoid:

- candy gloss
- toy-plastic visual language
- overly formal military-decoration aesthetics

---

## 9. Naming Migration Direction

### 9.1 High-Level District Rename Path

| Current live framing | Planned V2 framing |
|---|---|
| Puppy Park | Pediatric Community Response District |
| Neighborhood Walk | Adult Medical Response District |
| Doggy Daycare | Adult Trauma & Rescue Response District |
| Dog Park | Training Center |

### 9.2 Training Center Direction

The former `Dog Park` concept becomes the **Training Center** — an on-demand training area, not a map or a district.

**What the Training Center is:**

- a centralized hub for repeatable mini-games and quick drills
- content is organized by skill family or category (e.g. airway, med-math, ECG, sequencing), not by a quest structure or progression route
- no overall journey or completion arc — learners pick what they want to practice
- accessible at any time, from any point in the product
- no fog-of-war, no node unlocking, no district map

**What it is not:**

- a district on the home-page map
- a fourth training route with its own progression
- a place to run full patient scenarios

**Content it holds:**

- all repeatable mini-games
- quick skill drills and challenge types (med-math, ECG, sequencing, impression drills)
- learning-card practice
- daily/next-rep drill surfacing (optional)

**Navigation:**

- Training Center should be accessible as a persistent sidebar action or fixed shortcut on the home page
- it should not be presented as equal-weight with the four response districts
- visual treatment should feel like a "drill bay" or "training room" — adjacent to the station, not the same thing as a field response district

### 9.3 Reward Rename Path

| Current live term | Planned V2 term |
|---|---|
| Toys | Swag / collectibles |
| Toy chest | Coin case / patch board / station display |
| Toy shop | Station supply / memorabilia board / Scout’s station display |
| Toy drop | Collectible drop |

### 9.4 Currency Direction

| Current live term | Planned V2 direction |
|---|---|
| Treats | **Keep Treats** |

Treats remain the currency name. The surrounding collectible and district fiction evolves; the currency does not need to.

### 9.5 Guidance on Lexi/Scout

- keep **Lexi**
- keep **Scout**
- shift the surrounding nouns and category structure to a more professional EMS / fire-rescue frame

Recommended Scout framing:

- station quartermaster personality
- keeper of the challenge coin case / patch board
- guardian of the training-center swag wall

### 9.6 Product Name Guidance

Keep the product name **RescueTrails**.

Planned interpretation:

- `Rescue` = EMS / fire-rescue operational identity
- `Trails` = the learner’s guided progression across districts, branches, and response pathways

Do not build new primary copy around the older implied metaphor of physically walking a dog through trails. Instead, supporting copy should reinforce:

- training trails
- response pathways
- progression routes
- routes to readiness

This preserves the name while updating what it means in the user’s mental model.

This is a better balance than removing the companion layer entirely.

---

## 10. Migration Strategy

### 10.1 Recommended Migration Order

1. **Terminology and docs**
   - adopt new district names in planning and IA docs
   - reframe `RescueTrails` language around training pathways rather than dog-walking metaphors
   - define reward role split clearly

2. **Home-page framing**
   - shift to station dashboard concept
   - district map as primary category navigator (all four districts, equal weight, parallel)

3. **Reward presentation migration**
   - visible toy language replaced with coin/patch/pin language
   - keep backend logic structurally similar where possible

4. **District art refresh**
   - progressively migrate district visuals toward prehospital scene families
   - do not require all-new bespoke art at once

5. **Badge redesign**
   - pending: requires dedicated design pass before implementation (see §5.3)

6. **Training Center build-out**
   - on-demand drill hub, organized by skill family, no quest structure
   - implementation sequencing to be planned separately

### 10.2 What Does Not Need to Change First

- scoring logic
- challenge evaluation logic
- progression authority model
- Lexi companion presence

This is mostly a **presentation architecture** and **theme framing** migration, not a scoring-system rewrite.

### 10.3 Implementation Planning — Pending Work

The migration order above is a recommended sequence, not an implementation spec. Each step needs a dedicated implementation plan before work begins.

Specifically:

- **Home-page district map**: requires map rendering generalization work (the current `_renderPedsMap` function must be refactored to accept a generic map data object before a multi-district home map can render)
- **Training Center**: requires content inventory (which mini-games exist, which need to be built) and an organization scheme by skill family
- **Badge redesign**: requires a separate design doc (see §5.3)
- **Color migration**: should be done in a single coordinated CSS pass, not incrementally per-feature, to avoid prolonged inconsistency
- **Reward rename**: copy changes should be batched and rolled out together, not scattered across releases

Implementation plans for each step should be authored before work begins. Do not treat this document as the implementation spec.

---

## 11. Non-Goals

V2 should **not** do the following:

- turn the product into a sterile enterprise dashboard
- remove Lexi’s warmth from the experience
- replace all reward motivation with formal commendation language
- push the world toward hospital-floor settings when the product is for prehospital providers
- blur the distinction between badges, challenges, and swag

---

## 12. Summary Recommendation

Theme Update V2 should produce a product that feels like:

- a **station-based training platform**
- with **district-map navigation**
- grounded in **prehospital scenes**
- using **challenge coins, patches, and pins/decals**
- where **badges mark achievement**, **swag marks progression/identity**, and **challenges assess skill**
- with **Lexi preserved as companion/coaching layer**
- and **formal evaluation clearly owned by the FTO/system**

That is the target balance between:

- learner engagement
- instructional clarity
- professional optics
- and marketability.
