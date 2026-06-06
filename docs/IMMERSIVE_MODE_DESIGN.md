# Immersive Mode — Technical Design Document

**Project:** RescueTrails with Lexi  
**Branch:** (immersive mode branch)  
**Status:** Approved for implementation  
**Last Updated:** 2026-04-15

---

## 1. Overview

### Goal
Replace the current text-only simulation layout with a tactile, UI-driven "Immersive Mode" that drastically reduces typing and shifts cognitive load to clinical decision-making. Students tap equipment, body regions, and pre-written question chips instead of typing commands — while the existing chat, STT, and Lexi remain available for graded communication.

### What This Is Not
- A separate parallel engine. This is a permanent augmentation of the existing `#screen-sim` layout.
- A backend change. All features route through the existing `sendMessage()` → `/api/chat` → Groq pipeline.
- A mode toggle. There is no "switch back" to the old layout. The new layout IS the sim screen.

---

## 2. Guiding Principles

| Principle | Decision |
|---|---|
| Single source of truth | `state` object in `app.js` is unchanged. No new session/state engine. |
| Backend transparency | All UI actions call existing `sendMessage()`. Groq receives natural language strings regardless of input source. |
| Debrief compatibility | Because all actions enter via `sendMessage()`, XP scoring, intervention detection, and debrief grading inherit the new UI for free. |
| Desktop layout | 3-column grid preserved (`sim-panel-left` / `sim-panel-center` / `sim-panel-right`). Lexi stays always-visible on desktop. |
| Mobile layout | Tabbed system extended. "Notes" tab renamed "Exams & Gear". Chat and Lexi tabs unchanged. |
| PCR tag parser | Existing `processAiTags()` unchanged. `pcr-*` element IDs relocate into the Patient Briefing Card markup. No JS redirect layer. |

---

## 3. Layout Architecture

### Desktop (≥ 768px breakpoint)

```
┌─────────────────────┬──────────────────────┬────────────────────┐
│   sim-panel-left    │  sim-panel-center    │  sim-panel-right   │
│   (ACTION ZONE)     │  (CHAT — unchanged)  │  (LEXI — unchanged)│
│                     │                      │                    │
│  ┌───────────────┐  │                      │                    │
│  │ Patient       │  │  chat-messages feed  │  lexi-messages     │
│  │ Briefing Card │  │                      │  sendLexiMessage() │
│  │               │  │  [chip row — 40px]   │                    │
│  │ pcr-vitals    │  │  chat-input + STT    │                    │
│  │ pcr-exam      │  │                      │                    │
│  │ pcr-history   │  │                      │                    │
│  │ pcr-treatments│  │                      │                    │
│  └───────────────┘  │                      │                    │
│  ┌───────────────┐  │                      │                    │
│  │  Jump Bag     │  │                      │                    │
│  │  (CSS Grid)   │  │                      │                    │
│  └───────────────┘  │                      │                    │
└─────────────────────┴──────────────────────┴────────────────────┘
```

**Phase 4 change (desktop):** Patient Briefing Card shrinks to a compact sticky top-bar inside `sim-panel-left`, yielding vertical space to the SVG Body Map above the Jump Bag grid.

---

### Mobile (< 768px)

Tab bar layout (existing `--sim-mobile-tabs-h` variable preserved):

```
Tab: [ Exams & Gear ] [ Chat ] [ Lexi ]
```

**"Exams & Gear" tab:**
```
┌────────────────────────┐
│  Patient Briefing Card │  ← 75% vertical space
│  (pcr-vitals, exams,   │    (Phase 4: replaced by Body Map,
│   history, treatments) │     Briefing Card → compact top-bar)
├────────────────────────┤
│  Jump Bag Hotbar       │  ← 25% vertical space
│  [🩺][💨][💉][🩸][🌡️]→ │    horizontal scroll, gradient fade right
└────────────────────────┘
```

**"Chat" tab:** Unchanged. Quick-Tap chip row (40px) sits above chat input. Collapses when all chips are consumed.

**FAB anchor:** `position: fixed`, bottom-right, above tab bar, below modal z-index. Ships empty in Phase 1; button dropped in during Phase 2.

**Virtual keyboard note:** When a student taps the chat input on the "Chat" tab, the virtual keyboard reduces the visible viewport height. The "Exams & Gear" tab is inactive at that moment, so the hotbar is not visible and the Briefing Card / Body Map layout is not affected. CSS `min-height` rules on the hotbar and Briefing Card sections should prevent any layout collapse if the tab is switched while the keyboard is open. The existing `_syncSimMobileOffsets()` pattern already accounts for viewport height changes — no additional handling anticipated, but verify during Phase 1 device testing.

---

## 4. Data Structures

All defined as `const` in `app.js`. No changes to scenario JSON files.

### 4a. BASE_ASSESSMENT_TOOLS

Standard diagnostic gear always present in every scenario regardless of level or medications available.

```javascript
const BASE_ASSESSMENT_TOOLS = [
  { id: "auscultate",    label: "Auscultate",    icon: "🩺", payload: "I am auscultating lung sounds bilaterally." },
  { id: "bp_cuff",       label: "BP",            icon: "💪", payload: "I am obtaining a blood pressure reading." },
  { id: "pulse_ox",      label: "SpO2",          icon: "🩸", payload: "I am applying the pulse oximeter." },
  { id: "glucometer",    label: "BGL",            icon: "🩸", payload: "I am checking the blood glucose level." },
  { id: "thermometer",   label: "Temp",           icon: "🌡️", payload: "I am obtaining a temperature." },
  { id: "penlight",      label: "Pupils",         icon: "👁️", payload: "I am assessing pupils for size, equality, and reactivity." },
  { id: "monitor_leads", label: "12-Lead",        icon: "📋", payload: "I am applying the cardiac monitor leads." },
];
```

### 4b. INTERVENTION_ICONS

Lookup map from intervention ID (as defined in scenario JSON `available_interventions`) to emoji. Keeps presentation concerns out of JSON files. Jump Bag builder merges this with `Object.values(_interventionById)`.

```javascript
const INTERVENTION_ICONS = {
  o2_nrb:          "💨",
  o2_nc:           "💨",
  albuterol_svn:   "🌫️",
  epi_im:          "💉",
  diphenhydramine: "💊",
  dextrose:        "🍬",
  nitroglycerin:   "💊",
  aspirin:         "💊",
  naloxone:        "💉",
  activated_charcoal: "⬛",
  // fallback for unmapped IDs: "💊"
};
```

### 4c. BASE_ASSESSMENT_CHIPS

Quick-Tap question chips. `label` is displayed in the UI; `payload` is the natural language string sent to the LLM via `sendMessage()`.

```javascript
const BASE_ASSESSMENT_CHIPS = [
  // OPQRST
  { id: "onset",       label: "Onset",      payload: "When did this start? Did it come on suddenly or gradually?" },
  { id: "provocation", label: "Provocation", payload: "Does anything make it better or worse?" },
  { id: "quality",     label: "Quality",    payload: "Can you describe what it feels like? Is it sharp, dull, tight, or pressure-like?" },
  { id: "radiation",   label: "Radiation",  payload: "Does the pain or discomfort travel or spread anywhere?" },
  { id: "severity",    label: "Severity",   payload: "On a scale of 0 to 10, how would you rate your pain right now?" },
  { id: "time",        label: "Duration",   payload: "How long have you been feeling this way?" },
  // SAMPLE
  { id: "signs",       label: "Signs",      payload: "Have you noticed any other symptoms along with this?" },
  { id: "allergies",   label: "Allergies",  payload: "Do you have any known allergies to medications, foods, or anything else?" },
  { id: "medications", label: "Meds",       payload: "Are you currently taking any medications, prescribed or over the counter?" },
  { id: "pmhx",        label: "Hx",         payload: "Do you have any significant medical history or prior surgeries?" },
  { id: "last_oral",   label: "Last Oral",  payload: "When did you last eat or drink anything?" },
  { id: "events",      label: "Events",     payload: "What were you doing when this started? Can you walk me through what happened?" },
];
```

---

## 5. Function Signatures & Contracts

### 5a. `sendMessage(overrideText, options)`

**Current behavior:** `sendMessage()` takes zero arguments. It reads input strictly from the DOM: `const input = el("chat-input"); const message = input.value.trim();`

**New signature:** `async function sendMessage(overrideText = null, options = { chipId: null, isAction: false })`

**Behavioral contract:**
- If `overrideText` is a non-empty string, use it as the message payload directly (Jump Bag, Chip, FAB, Body Map calls)
- If `overrideText` is `null` or omitted, fall back to reading `el("chat-input").value.trim()` exactly as today

**PointerEvent guard (critical):** `btn-send` is currently wired as `el("btn-send").addEventListener("click", sendMessage)`. JavaScript event listeners automatically pass the `Event` object (a `PointerEvent` or `MouseEvent`) as the first argument to the callback. Without a guard, clicking the send button passes the event object into `overrideText`, which would then be sent to the Groq LLM.

The first line of the refactored function body must be:
```javascript
if (overrideText instanceof Event || typeof overrideText !== "string") overrideText = null;
```

This is safe, backward-compatible, and handles: no argument passed (null → null), event object passed (Event → null), and valid string passed (used as payload).

This keeps all existing `btn-send` click and `Enter` key listeners fully backward-compatible with zero changes to those listeners.

| Option | Type | Effect |
|---|---|---|
| `chipId` | `string \| null` | If set, stamps `data-chip-id` on the resulting user bubble. Used by reconnect chip check. |
| `isAction` | `boolean` | If true, calls `appendUserAction()` instead of `appendUserMessage()` for the DOM bubble. LLM payload is identical either way. |

**Phase 1 task:** Audit every existing `sendMessage()` call site in `app.js` before modifying the function body. Confirm no call currently passes any argument (expected: all calls are bare `sendMessage()` with no arguments).

---

### 5b. `appendUserAction(text, chipId)`

New DOM injector for UI-fired actions. Functionally parallel to `appendUserMessage()`.

**Differences from `appendUserMessage()`:**
- Wrapper element gets classes: `msg-user msg-user-action`
- If `chipId` is provided, bubble element gets attribute: `data-chip-id="{chipId}"`
- Visual treatment: subtle background tint or small indicator icon to distinguish from typed messages in the transcript

**LLM impact:** None. The same text string enters the Groq conversation history as a standard user turn.

---

### 5c. `getPatientSilhouetteType(age)`

Returns the correct Body Map SVG variant based on patient age from `state.scenarioData.patient.age`.

```
age < 2   → "infant"
age 2–12  → "pediatric"
age ≥ 13  → "adult"
```

`parseInt()` guard applied to `age` parameter for future-proofing against string values.

**Wired in Phase 1** (stamps `data-variant` on Body Map container). SVG assets and switching logic activated in Phase 4.

---

## 6. Component Specifications

### 6a. Patient Briefing Card

**Purpose:** Replaces Notes tab content. Displays static patient data on mount; auto-populates with live AI tag output as the scenario progresses.

**Mounts in:**
- Desktop: top portion of `sim-panel-left`
- Mobile: top 75% of "Exams & Gear" tab

**Contains (reusing existing IDs — no JS changes to tag parser):**
- Deferred header (all clinical scenarios): shows `category_display` as title and `dispatch.text` as subtitle on launch; patient name, age, DOB, and weight appear only after the learner obtains them via patient-scoped history tags (`[[HISTORY: Patient Name=...]]`, etc.)
- `#pcr-vitals` — populated by `[[VITAL:]]` tags
- `#pcr-exam` — populated by `[[EXAM:]]` tags
- `#pcr-history` — populated by `[[HX:]]` tags
- `#pcr-treatments` — populated by `[[TX:]]` tags

**Phase 4 behavior:** When Body Map is active, Briefing Card transitions to a compact sticky top-bar (name, age, SpO2, HR) via CSS class. Full vitals collapse or move to a scroll region below the Body Map.

---

### 6b. Jump Bag

**Purpose:** One-tap equipment and assessment actions. Fires `sendMessage(payload, { isAction: true })`.

**Inventory:** `BASE_ASSESSMENT_TOOLS` concatenated with `Object.values(_interventionById)` mapped through `INTERVENTION_ICONS`. Unmapped intervention IDs fall back to `💊`.

**Desktop layout:** CSS grid inside `sim-panel-left`, below Briefing Card.

**Mobile layout:** Horizontal scroll hotbar, bottom 25% of "Exams & Gear" tab.
- `mask-image: linear-gradient(to right, black 85%, transparent 100%)` on trailing edge
- Dynamic left-side fade when scroll offset > 0

**Item structure rendered:**
```html
<button class="jump-bag-item" data-action-id="{id}">
  <span class="jump-bag-icon">{icon}</span>
  <span class="jump-bag-label">{label}</span>
</button>
```

---

### 6c. Quick-Tap Chip Row

**Purpose:** One-tap OPQRST/SAMPLE history-taking. Sends natural language question to LLM and removes chip from view.

**Source:** `BASE_ASSESSMENT_CHIPS`

**Placement:** 40px horizontal scroll strip, positioned above `chat-input` in the Communication Zone. Visible on both desktop (above chat input in `sim-panel-center`) and mobile (Chat tab).

**Chip lifecycle:**
1. Render on scenario start
2. On tap: call `sendMessage(chip.payload, { chipId: chip.id, isAction: true })`; remove chip element from DOM
3. Call `_syncSimMobileOffsets()` immediately after chip removal so the chat feed viewport recalculates its bottom offset against the new (shorter) input wrapper height
4. When the last chip is consumed and the row CSS-transitions to `height: 0`, call `_syncSimMobileOffsets()` again on `transitionend` to fully reclaim the collapsed 40px for the chat feed
5. Row collapses automatically via CSS when empty (`height: 0`, `overflow: hidden`, `transition`)

**Mobile height sync note:** `_syncSimMobileOffsets()` in `app.js` measures `.sim-chat-input-wrap` and writes the result to `--sim-mobile-input-h`. Because the chip row sits inside or directly above that wrapper, any dynamic height change (chip removed, row collapsed) must trigger this function or the chat feed will underlap the input area by the chip row's height.

**Reconnect initialization:** On mount, query `document.querySelectorAll('[data-chip-id]')` to collect all chip IDs already present in the message history. Do not render those chips. Searches only `data-chip-id` attributes (not text content) to avoid LLM response false positives.

**Chip element rendered:**
```html
<button class="quick-tap-chip" data-chip-id="{id}">{label}</button>
```

---

### 6d. Partner Command FAB (Phase 2)

**Purpose:** One-tap partner delegation without typing. Fires `sendMessage(command, { isAction: true })`.

**Anchor:** `<div id="fab-anchor">` — `position: fixed`, bottom-right, above `--sim-mobile-tabs-h`, `z-index` below modals.

**Behavior:** FAB button opens an expandable panel listing static delegation commands. Each command fires `sendMessage()` and closes the panel.

**Initial command list (expandable):**
- "Alex, please get a full set of vitals."
- "Alex, prepare the nebulizer."
- "Alex, apply the cardiac monitor."
- "Alex, establish IV access."
- "Alex, prepare the BVM."

---

### 6e. Audio Engine (Phase 3)

**Initialization:** On `btn-respond` click (Begin Scenario on dispatch screen). Stores reference as `state.audioContext`.

**Cardiac monitor beep:**
- Generated via Web Audio API oscillator — no audio file required
- Frequency: fixed tone (e.g., 880 Hz), short attack/release envelope
- BPM: driven by heart rate value from `vitalsWs.onmessage`
- Rhythm: schedules next beep via `setTimeout` calculated from current HR
- Degraded states (bradycardia, tachycardia, arrest) reflected in beep tempo

**Radio chirps:**
- `squelch_open.mp3`: plays when Medical Control modal opens
- `squelch_close.mp3`: plays when Medical Control modal dismisses
- Loaded via `<audio>` element or `AudioContext.decodeAudioData`

**Teardown:** `state.audioContext.close(); state.audioContext = null;`
- In `btn-dispatch-back` listener (student backs out before scenario starts)
- In `processDebrief()` (scenario completes normally)

**iOS silent switch:** When the device hardware silent switch is toggled on, iOS may suppress or behave unpredictably with Web Audio API output even after a successful `AudioContext.resume()` unlock. Because the cardiac monitor is synthesized (not a required instructional element) and the radio chirps are supplementary feedback, audio failure in this state is gracefully silent — no crash, no broken state. The app must not block on audio playback or throw uncaught errors if the context fails to produce sound. Wrap audio scheduling in `try/catch` during Phase 3 implementation. Document in QA notes as a known hardware limitation.

---

### 6f. Interactive Body Map (Phase 4)

**SVG structure:**
```
<svg id="body-map" data-variant="adult">
  <g id="bm-visual">     <!-- visible anatomy, non-interactive -->
    ...drawing paths...
  </g>
  <g id="bm-hitboxes">   <!-- invisible, interactive -->
    <g data-region="chest" class="bm-region">...</g>
    <g data-region="head"  class="bm-region">...</g>
    ...
  </g>
</svg>
```

**Hitbox rules:**
- Minimum touch target: 48×48dp per Google Material Design / Apple HIG
- Hitbox paths are visually invisible (`fill: transparent`, `stroke: none`)
- Hitbox bounds are intentionally larger than visible anatomy outlines

**Regions and default action payloads:**

| Region | Payload sent to `sendMessage()` |
|---|---|
| Head | "I am assessing the patient's head, checking pupils for size, equality, and reactivity, and assessing level of consciousness." |
| Neck | "I am assessing the neck for tracheal deviation, JVD, and cervical tenderness." |
| Chest | "I am auscultating lung sounds bilaterally and assessing chest rise and symmetry." |
| Abdomen | "I am palpating the abdomen for tenderness, rigidity, guarding, or distension." |
| Pelvis | "I am assessing the pelvis for instability and tenderness." |
| L/R Upper Arm | "I am assessing the {side} upper arm for deformity, swelling, and distal pulse." |
| L/R Forearm | "I am assessing the {side} forearm and wrist for deformity and distal pulse." |
| L/R Hand | "I am checking the {side} hand for capillary refill and motor/sensory function." |
| L/R Thigh | "I am assessing the {side} thigh for deformity, swelling, and distal pulse." |
| L/R Lower Leg | "I am assessing the {side} lower leg for deformity and distal pulse." |
| L/R Foot | "I am checking the {side} foot for capillary refill and pedal pulse." |

**Tap interaction:**
1. `sendMessage(payload, { isAction: true })` fires immediately (non-blocking)
2. CSS class `.tapped` added to tapped `<g>` element (amber fill, 300ms)
3. `setTimeout(300ms)`: remove `.tapped` class; if mobile, flip to Chat tab
4. Chest region: after `sendMessage()`, existing `_shouldTriggerLungSoundChallenge()` gate applies — 30-second debounce, resets when an intervention is applied

**Variant switching:** `getPatientSilhouetteType(state.scenarioData.patient.age)` called on sim start; result sets `data-variant` on `#body-map`. CSS `[data-variant="pediatric"] #bm-visual` selects the correct SVG layer. Adding a new variant requires only a new SVG asset and one CSS rule.

---

## 7. Phase Roadmap

### Phase 1 — Scaffolding + Core Input Layer
**Risk:** Low  
**Files touched:** `static/index.html`, `static/js/app.js`, `static/css/style.css`

Tasks:
1. Audit all `sendMessage()` call sites; confirm no existing call passes a second argument
2. Expand `sendMessage()` signature to `sendMessage(text, options = { chipId: null, isAction: false })`
3. Add `appendUserAction()` DOM injector
4. Gut `sim-panel-left` content; build Patient Briefing Card with relocated `pcr-*` IDs
5. Build Jump Bag component (desktop grid + mobile hotbar, scroll affordance)
6. Define `BASE_ASSESSMENT_TOOLS` and `INTERVENTION_ICONS` constants
7. Build Quick-Tap chip row with `BASE_ASSESSMENT_CHIPS`
8. Chip reconnect initialization loop
9. Rename "Notes" mobile tab display text to "Exams & Gear" in HTML only. All underlying IDs (`btn-sim-tab-notes`, `tab-notes`, `coach-mobile-notes`) remain unchanged to avoid rewriting `_setSimMobileTab()` and related JS logic; wire Briefing Card + Jump Bag hotbar into `tab-notes` panel
10. Add `<div id="fab-anchor">` with correct positioning
11. Define `getPatientSilhouetteType()` and stamp `data-variant` on Body Map container placeholder
12. CSS: `.msg-user-action` tint, chip row collapse, hotbar scroll affordance, Action Zone layout

---

### Phase 2 — Partner Command FAB
**Risk:** Low  
**Files touched:** `static/index.html`, `static/js/app.js`, `static/css/style.css`

Tasks:
1. Drop FAB button and command panel into `#fab-anchor`
2. FAB toggle open/close logic
3. Each command button calls `sendMessage(command, { isAction: true })`
4. CSS: FAB animation, panel expand/collapse

---

### Phase 3 — Audio Engine
**Risk:** Medium  
**Files touched:** `static/js/app.js`, `static/audio/`

Tasks:
1. Add `squelch_open.mp3` and `squelch_close.mp3` to `static/audio/`
2. On `btn-respond` click: instantiate `AudioContext`, store as `state.audioContext`; immediately call `state.audioContext.resume()` and play a silent 0.1-second buffer to fully unlock the audio engine on iOS Safari (which aggressively suspends contexts not unlocked within the originating gesture)
3. Build cardiac monitor oscillator; schedule BPM from `vitalsWs.onmessage` HR value
4. Wire radio chirp playback to Medical Control modal open/close
5. Add `state.audioContext` teardown to `btn-dispatch-back` listener
6. Add `state.audioContext` teardown to `processDebrief()`

---

### Phase 4 — Interactive Body Map
**Risk:** High  
**Files touched:** `static/index.html`, `static/js/app.js`, `static/css/style.css`, `static/img/` (new SVG assets)

Dependencies: SVG assets must be available before Phase 4 begins.

Tasks:
1. Mount SVG body map in Action Zone (desktop: `sim-panel-left`; mobile: "Exams & Gear" tab)
2. Wire region click handlers to `sendMessage()` + 300ms flash + mobile tab flip
3. Activate variant switching via `data-variant` (already wired from Phase 1)
4. Transition Patient Briefing Card to compact top-bar mode when Body Map is active
5. Chest region: integrate with existing `_shouldTriggerLungSoundChallenge()` debounce

---

## 8. Asset Specifications

### SVG Body Maps

Three variants required. Each SVG must contain two `<g>` layer groups:
- `#bm-visual` — visible anatomical drawing (non-interactive, decorative)
- `#bm-hitboxes` — invisible interactive paths with `data-region` attributes

**Hitbox `data-region` values (all three variants):**  
`head`, `neck`, `chest`, `abdomen`, `pelvis`, `arm-upper-left`, `arm-upper-right`, `arm-lower-left`, `arm-lower-right`, `hand-left`, `hand-right`, `leg-upper-left`, `leg-upper-right`, `leg-lower-left`, `leg-lower-right`, `foot-left`, `foot-right`

**Touch target requirement:** Every hitbox path bounding box must be ≥ 48×48dp at the intended render size. Head, hands, and feet require extra attention — these are small on a standing silhouette and must have enlarged invisible hit areas.

| File | Variant | Age Range |
|---|---|---|
| `static/img/body-map-adult.svg` | Adult | ≥ 13 years |
| `static/img/body-map-pediatric.svg` | Pediatric | 2–12 years |
| `static/img/body-map-infant.svg` | Infant | < 2 years |

**Launch note:** Phase 4 can launch with only the adult silhouette if pediatric/infant assets are not ready. The variant-switching logic is already wired; adding new variants requires only dropping the SVG file and adding one CSS `[data-variant]` rule.

---

### Audio Files

| File | Use | Duration | Notes |
|---|---|---|---|
| `static/audio/squelch_open.mp3` | Plays when Medical Control modal opens | ~0.5–1 sec | Standard PTT radio chirp/squelch sound |
| `static/audio/squelch_close.mp3` | Plays when Medical Control modal dismisses | ~0.3–0.5 sec | PTT release squelch |

**Cardiac monitor beep:** Synthesized via Web Audio API oscillator. No audio file required.

---

## 9. Extensibility: Future Categories

The Immersive Mode architecture is designed to support expansion beyond EMS into Fire Operations, Hazmat, and Professional Development without requiring changes to the core engine. The Communication Zone (chat feed, STT, Lexi, `sendMessage()` pipeline, `processDebrief()`) is category-agnostic and reused unchanged. Only the **Action Zone** — the left panel on desktop and the "Exams & Gear" tab on mobile — is category-specific.

### How Expansion Works

**Scenario JSONs** already define category via `scenario.category` (which maps to `CATEGORY_DEFS` in `app.js`). A fire ops scenario JSON would have `available_interventions` populated with fire operations actions (SCBA donning, hoseline deployment, search patterns) instead of medications. The Jump Bag reads from `_interventionById`, so it automatically surfaces only category-appropriate items.

**Category-aware constants** replace the global `BASE_ASSESSMENT_TOOLS` and `BASE_ASSESSMENT_CHIPS` for non-EMS categories. Rather than a single global array, these become a lookup keyed by category:

```javascript
const CATEGORY_TOOLS = {
  ems:   BASE_ASSESSMENT_TOOLS,   // stethoscope, BP cuff, pulse ox, etc.
  fire:  FIRE_ASSESSMENT_TOOLS,   // SCBA, TIC, hoseline, PPV fan, etc.
  hazmat: HAZMAT_TOOLS,           // ERG reference, air monitor, PPE levels, etc.
  prodev: PRODEV_TOOLS,           // scenario-specific reference tools
};

const CATEGORY_CHIPS = {
  ems:    BASE_ASSESSMENT_CHIPS,  // OPQRST / SAMPLE
  fire:   FIRE_SIZE_UP_CHIPS,     // COAL WAS WEALTH size-up prompts
  hazmat: HAZMAT_CHIPS,           // recognition, isolation, notification steps
  prodev: PRODEV_CHIPS,           // category-specific prompts
};
```

The Jump Bag and chip row builders reference `CATEGORY_TOOLS[state.scenarioData.category]` and `CATEGORY_CHIPS[state.scenarioData.category]` respectively. Adding a new category requires only defining its tools/chips arrays and adding a key to these maps — zero changes to the rendering logic.

**Action Zone layouts** can diverge by category when appropriate. The `sim-panel-left` (desktop) and `tab-notes` panel (mobile) accept a `data-category` attribute stamped at sim start. CSS `[data-category="fire"]` rules can deliver a completely different visual layout for the Action Zone while the Communication Zone remains untouched. In Phase 4, the Body Map is EMS-specific; fire ops might substitute a building/floor plan SVG, hazmat a placard identification panel — each wired to `sendMessage()` exactly the same way.

### Anticipated Category Layouts

| Category | Action Zone Content | Chips |
|---|---|---|
| EMS | Patient Briefing Card → Body Map (Phase 4), Jump Bag | OPQRST / SAMPLE |
| Fire Ops | Building/scene briefing card, tactical tool cache, ICS role panel | COAL WAS WEALTH size-up, tactical benchmarks |
| Hazmat | ERG reference panel, PPE level selector, air monitor readouts | Recognition/isolation/notification checklist |
| Professional Development | Reference material panel, scenario-specific decision aids | Topic-specific prompts |

### What Is Never Category-Specific
- `sendMessage()` and the Groq pipeline
- `processDebrief()` and all scoring/XP logic
- The Communication Zone (chat, STT, Lexi)
- Mobile tab structure and `_setSimMobileTab()`
- `appendUserAction()` and `data-chip-id` stamping

---

## 10. Out of Scope for This Implementation

- New backend API endpoints (all actions use existing `/api/chat`)
- Changes to scenario JSON structure (no `icon` or `assessment` fields added)
- Dynamic LLM-generated Quick-Tap chips (static `BASE_ASSESSMENT_CHIPS` only)
- Voice-synthesized AI patient responses (audio output, not input)
- Multiplayer or shared session state changes
- New debrief/scoring logic (existing `processDebrief()` inherits all actions automatically)
