# Map Gameplay — Improvement Design

**Status:** Direct node navigation implemented · Lexi map avatar/movement removed
**Last Updated:** 2026-05-07
**Scope:** Map UX improvements — requires topology contract extraction for unlock/fog state; no scoring or clinical changes implied

> **Dev/test state:** All map nodes are currently unlocked unconditionally. Fog of war, prerequisite gates, and unlock logic are not yet enforced. These will be implemented from the topology contract before release.

---

## 1. Decisions Recorded

| Question | Decision |
|---|---|
| Fog of war unlock trigger | Current scenario completion rules as defined in `PEDIATRIC_MAP_DESIGN.md` |
| Ambient animation style | Removed — static maps only |
| Map navigation model | User navigates by clicking/tapping map nodes directly |
| Node tap behavior | Opens a node detail popup immediately with scenario/game details and take/retake options |
| Lexi map avatar | Removed from map screens — no avatar layer, node-to-node movement, trail following, position persistence, bark interaction, or walking animation |
| Node visual priority | Nodes remain the primary interaction target; minimum 48x48px tap target |
| Map entry behavior | Entering a district shows the map directly; no avatar placement or map-entry anchor |
| Station 1 orientation flow | `Lexi Intro` → `Orientation Tour` → `CPR Drill` → `Station 1 Complete` → main map |

---

## 2. Feature Descriptions

### 2a. Fog of War

Locked map areas are obscured by a semi-transparent overlay. As a student completes scenarios and satisfies prerequisite gates, overlays dissolve with an animated reveal. Fog state is derived entirely from the existing completion/unlock rules defined in `PEDIATRIC_MAP_DESIGN.md` — no new scoring logic is introduced.

**Unlock types requiring distinct fog states:**

| State | Description | Visual treatment |
|---|---|---|
| Fully locked | No prerequisites met | Full fog overlay, node icons hidden |
| Partially accessible | Convergence maps (PM7, PT8) — any one feeder complete | Fog lifted but locked feeder routes shown dimmed within the map |
| Fully unlocked | All prerequisites met | No fog |
| Pending (PE1 two-key gate) | PM7 complete but PT8 not, or vice versa | Fog on PE1; progress indicator shows 1/2 keys |

**Fog reveal moment:** The animated reveal plays when the student returns to the map after completing a scenario that satisfies a prerequisite. The map entry transition (debrief → map) checks for newly unlocked nodes since the last map visit and plays a single ambient reveal sweep — all newly unlocked nodes reveal simultaneously, not sequentially. Sequential per-node reveals risk blocking the debrief → replay loop, which is one of the highest-frequency flows in the product.

**Topology data requirement:** The prerequisite chains currently live in `PEDIATRIC_MAP_DESIGN.md` as prose and ASCII diagrams. Before fog rendering can be implemented, these chains must be extracted into a code-level data structure — a map of `node_id → [prerequisite_node_ids]` — that the frontend can query against the user's completion state. This is a prerequisite for Phase 1 implementation. See Section 5 (Topology Contract) for the proposed structure.

---

### 2b. Direct Node Navigation

Students navigate the map by clicking or tapping a node. Node selection opens a detail popup immediately; there is no Lexi avatar, no node-to-node movement delay, no trail-following animation, and no visited-node localStorage state.

**Node popup behavior:**

| Node type | Popup content | Primary actions |
|---|---|---|
| Scenario node | Scenario title, brief description/dispatch framing, completion status, last score or last result summary when available | `Take Scenario`, `Retake Scenario`, `View Last Results` when prior completion exists |
| Mini-game node | Game title, skill focus, completion/proficiency status, reference-card unlock status when applicable | `Play`, `Replay`, `View Learning Card` when unlocked |
| Locked node | Locked state, prerequisite explanation, progress toward unlock | Disabled primary action; optional `View Requirements` |
| District/shop/special node | Short explanation of destination or feature | `Open` or destination-specific action |

**Interaction rules:**

- Node popup opens on the first tap/click; do not delay behind avatar movement or other decorative animation.
- Node tap targets must be at least 48x48px, regardless of visual node size.
- Nodes must remain unobstructed by decorative elements.
- Clicking outside the popup or pressing the close button returns to the same map position.
- Replaying a completed scenario must use the same popup path as taking it the first time, with copy updated from `Take Scenario` to `Retake Scenario`.
- The popup may show a compact last-results summary, but full debrief viewing remains a separate action.

**State signals — keep them separate:**

| Signal | Drives | Source | Authority |
|---|---|---|---|
| Scenario completion | Fog unlock, node status, PE1 gate, take/retake state | Backend session history | Backend (authoritative) |
| Node unlock state | Whether a node is accessible, locked, or partially accessible | Topology + backend completion history | Frontend display derived from backend-authoritative facts |
| Popup display state | Which node popup is currently open | In-memory only | Frontend (ephemeral UI state) |

**Rationale:** Direct node navigation is faster, easier to debug, and better aligned with the primary learning loop: pick a scenario, train, debrief, and replay. Removing avatar movement also eliminates a class of timing bugs where clicks, modals, and map state become coupled to animation state.

### 2b.1 Station 1 Orientation Tour

Station 1 is a direct-node tour on the main map, not a separate login or fullscreen onboarding workflow.

**Required node order:**

| Step | Node | Behavior |
|---|---|---|
| 1 | Lexi Intro | Opens a node popup explaining the tour; acknowledging the popup unlocks the Orientation Drill node |
| 2 | Orientation Drill | Launches `orientation_01`; Lexi's first instructional prompt appears immediately in chat at scenario start |
| 3 | CPR Drill | Launches the CPR mastery game flow from the Station 1 map |
| 4 | Station 1 Complete | Shows the completion message and sends the learner back to the main map |

**Implementation notes:**

- Station 1 nodes use the same dot-style map interaction as the pediatric maps. Do not render text labels on the map itself; labels belong in the popup/title/ARIA text.
- Lexi-message nodes (`Lexi Intro`, `Station 1 Complete`) render the Lexi avatar inside the circular node instead of a generic dot.
- Station 1 renders one lightweight Lexi chat bubble on the map pointing to the current unlocked step. Initial copy: "Click here to begin." After each prerequisite unlocks, the bubble moves to the next node and instructs the learner what to click next.
- Prerequisites are sequential: Lexi Intro unlocks Orientation Drill; Orientation Drill unlocks CPR Drill; CPR Drill unlocks Station 1 Complete.
- The Lexi Intro popup must not start the drill directly. It only marks the intro as seen and returns to Station 1; the learner starts the drill by clicking the Orientation Drill node.
- The orientation instructional cue uses `delay_seconds: 0`; the app must treat zero as immediate, not as a fallback delay.
- The backend remains authoritative for the Station 1 completion award. The map flow guides the learner through CPR after the scenario drill, but it must not move scoring or completion authority into frontend-only state.
- Returning from the orientation drill should land the learner back on Station 1 so the next visible action is the CPR drill.
- Drill result screens launched from MAP0, PM1, or PT1 must not show the generic "Try a Scenario" bridge. Those gateway maps use drills as standalone skill reps; scenario progression remains controlled by the map nodes themselves.

---

### 2c. Removed Lexi Map Avatar Scope

Lexi remains available in chat, debrief, coaching, and other non-map guidance surfaces. She is not rendered as a map avatar.

The following are explicitly removed from the map design:

- Lexi avatar layer on district maps
- Lexi idle position, resting offset, and map-specific scale
- Lexi node-to-node movement
- Trail path walking and follow-cam behavior
- Lexi position persistence or inference from completion history
- Visited-node localStorage for walk duration
- Bark interaction from tapping the map avatar
- Avatar movement state machines, animation locks, and tap-to-skip behavior

Completion history is still required for node status, retake state, last-results summaries, and fog/unlock calculations. It is no longer used to place an avatar.

---

### 2d. Ambient Animations

Removed from the current map direction. Maps should use static JPEG backgrounds plus clickable nodes and lock/fog state only. Do not add decorative leaf, butterfly, smoke, ripple, cloud, mist, path, or avatar-motion layers unless a future design explicitly reintroduces them.

---

## 3. Implementation Phases

### Phase 1 — Fog of War + Direct Node Popups
*Target direction updated.*

- `MAP_TOPOLOGY` constant — canonical prerequisite chains, 19 maps
- `_computeMapUnlockState()` — full/partial/locked state for all maps; `null` when `PEDS_MAP_DEV_UNLOCKED`
- Exit button lock indicators (🔒 / ◑→) and fog reveal animation (sessionStorage-tracked)
- District exit lock indicators; Emergencies button shows `X/2 🔑` PE1 gate counter
- Node click/tap opens a detail popup immediately
- Scenario popup supports take, retake, and view-last-results actions
- Locked node popup explains prerequisites and progress toward unlock
- No Lexi avatar layer or movement state

**Implementation cleanup complete:** Lexi map avatar constants, layers, CSS classes, state machines, event handlers, localStorage visit keys, path debug overlays, and movement animation code have been removed from the frontend.

---

### Phase 2 — Map Avatar Removal + Node Handler Simplification
*Complete.*

- Remove `district-lexi-layer` / `adventure-lexi-layer` from map markup if present
- Remove map avatar render functions and Lexi map CSS
- Remove `_pedsLexiMapState`, `_pedsLexiInferPosition`, `_lexiAnimateWalk`, `_lexiHandleNodeTap`, `_lexiFinishWalk`, visited-node helpers, and related state
- Route all scenario/game/shop node handlers directly to their popup openers
- Ensure nodes remain clickable during all normal map states; only the active popup should capture modal focus
- Remove trail SVG path requirements if they exist only to support avatar movement
- Keep fog/unlock logic independent from this cleanup

---

### Phase 3 — Ambient Animations
*Removed.*

Ambient map animations were removed from the application direction. The shipped map should not include `MAP_AMBIENT_DATA`, SVG animation generators, an ambient DOM layer, decorative CSS keyframes, or visibility/modal animation controllers.

---

### Phase 4 — World Map Pan/Zoom
*Deferred. Warranted only when district count makes button-navigation untenable.*

- CSS Grid tile stitching of district JPEGs (no image merging)
- Choke-point transitions between districts (not CSS blending)
- Drag-to-pan with `transform: translate3d()` (GPU composited)
- Lazy-load district tiles on pan proximity

**Not started until:** 3+ districts exist and the current navigation model is confirmed to be hurting UX.

---

## 4. What Is Explicitly Not Being Built

**Easter eggs with random tap rewards.** Rewarding random screen-tapping decouples rewards from clinical performance. The existing gamification system (badges, treats, leaderboards) is tied to clinical achievement. Easter eggs would undermine that. Decorative map animations are not part of the current direction.

**Free-roaming joystick/WASD movement.** Virtual joysticks on mobile conflict with browser scroll, require a continuous render loop, and create an empty-space problem (student wastes time walking across map rather than getting into clinical reps).

**Single merged JPEG.** One massive image file causes excessive mobile RAM usage and initial load time. District tiles remain separate; CSS Grid handles layout.

---

## 5. Topology Contract (Required Before Phase 1)

The prerequisite chains currently exist as prose and ASCII diagrams in `PEDIATRIC_MAP_DESIGN.md`. Before fog rendering and node unlock state can be built, they must be extracted into a machine-readable data structure. **This structure becomes the canonical gameplay progression source — not a second copy.** Once implemented, `PEDIATRIC_MAP_DESIGN.md` should reference the code structure as authoritative and remove any redundant prose encoding of the same rules. Maintaining two representations in sync is a maintenance trap.

Proposed format:

```js
// Each key is a map/node ID. Value describes its unlock rule.
const MAP_TOPOLOGY = {
  "map0":  { requires: [],              partial_requires: null },
  "pm1":   { requires: ["map0"],        partial_requires: null },
  "pm2":   { requires: ["pm1"],         partial_requires: null },
  "pm3":   { requires: ["pm1", "pm2"],  partial_requires: null },
  "pm4":   { requires: ["pm3"],         partial_requires: null },
  "pm5":   { requires: ["pm2"],         partial_requires: null },
  "pm6":   { requires: ["pm4"],         partial_requires: null },
  // PM7: partial access when any one of pm3/pm5/pm6 complete;
  //      full access (PE1 gate satisfied) requires all three
  "pm7":   { requires: ["pm3", "pm5", "pm6"], partial_requires: ["pm3", "pm5", "pm6"] },
  "pt1":   { requires: ["map0"],        partial_requires: null },
  "pt2":   { requires: ["pt1"],         partial_requires: null },
  "pt3":   { requires: ["pt1", "pt2"],  partial_requires: null },
  "pt4":   { requires: ["pt3"],         partial_requires: null },
  "pt5":   { requires: ["pt2"],         partial_requires: null },
  "pt6":   { requires: ["pt3"],         partial_requires: null },
  "pt7":   { requires: ["pt4"],         partial_requires: null },
  // PT8: same partial-access rule as PM7
  "pt8":   { requires: ["pt5", "pt6", "pt7"], partial_requires: ["pt5", "pt6", "pt7"] },
  // PE1: two-key gate — requires PM7 AND PT8 fully satisfied
  "pe1":   { requires: ["pm7", "pt8"],  partial_requires: ["pm7", "pt8"] },
  "pe2":   { requires: ["pe1"],         partial_requires: null },
};
```

**Unlock logic using this structure:**

- A node is **fully unlocked** when all IDs in `requires` are themselves fully unlocked AND have at least one completed scenario
- A node with `partial_requires` is **partially accessible** (navigable, locked feeders visible) when at least one ID in `partial_requires` is fully unlocked, even if others are not
- Fog is fully removed only on full unlock; partially accessible nodes show reduced fog with locked-feeder indicators

**Scope of this structure:** It does not affect backend scoring, session authority, or any deterministic clinical logic. It governs UI unlock state and fog rendering only. If the topology changes (new maps added, prerequisites revised), the data structure is the primary update target; `PEDIATRIC_MAP_DESIGN.md` is updated to match, not the reverse.

**Design for future API swappability:** For Phase 1, `MAP_TOPOLOGY` lives as a static JS object in the frontend. As the platform scales, the backend may eventually serve topology (or a fully resolved unlock state) via an endpoint like `GET /api/me/map-state`. Implement all topology-consuming functions to accept the topology data structure as a parameter rather than importing it directly — this makes the source swappable to an API response without touching call sites.

---

## 6. Node Detail Popup Contract

The node detail popup is the canonical navigation surface for map interactions. It replaces avatar-driven arrival behavior.

**Required fields for scenario nodes:**

| Field | Purpose |
|---|---|
| `scenario_id` | Stable scenario identifier used by `startScenario()` and history lookup |
| `title` | Human-readable title displayed in the popup |
| `summary` or dispatch brief | Short framing text so the learner knows what they are about to take |
| `status` | `not_started`, `completed`, `locked`, or equivalent derived state |
| `last_result_key` | Optional key for opening the last-results modal |
| `completion_summary` | Optional score/date summary for completed nodes |
| `unlock_requirements` | Required for locked nodes so the popup explains what to do next |

**Popup action rules:**

- `Take Scenario` appears when the node is unlocked and has no completion.
- `Retake Scenario` appears when the node is unlocked and completed.
- `View Last Results` appears only when `last_result_key` is available.
- Locked nodes do not start scenarios; they show requirements and progress.
- Popup actions must call the same scenario/history functions used elsewhere in the app; do not create map-only duplicate launch or debrief logic.

**Visual rules:**

- Popup should appear immediately on node tap.
- Popup should use the same modal styling system as scenario preview/last-results surfaces.
- Popup close returns to the map without re-rendering or moving the viewport unless the underlying map state changed.

---

## 7. Mobile Considerations

| Concern | Mitigation |
|---|---|
| Tap targets on clustered nodes | All node interactive areas minimum 48×48px regardless of visual size |
| Node popup conflicts with scroll | Popup is modal; map remains stationary behind it; closing returns to the same map position |
| Decorative map animation distraction | Ambient animation layer removed; maps stay static behind clickable nodes and popups |
| Fog overlay render cost | Fog is a single semi-transparent `div` per locked node — not a canvas operation |

---

## 8. Open Items

| Item | Status |
|---|---|
| Topology data structure review against `PEDIATRIC_MAP_DESIGN.md` prerequisite chains | Needs verification pass — draft in Section 5 above |
| PM3 prerequisite: doc says "requires PM1 and PM2" — confirm | Open (doc section 4 says "Prerequisites: PM1, PM2") |
| `PEDIATRIC_MAP_DESIGN.md` prose de-duplication after topology is extracted | Required after Phase 1 — topology code becomes canonical, prose becomes reference only |
| Confirm session history API returns `scenario_id` and stable history key with each completion record | Required for node completion state, retake state, and last-results popup |
| Remove Lexi map avatar implementation from frontend | Complete — avatar layers, movement state, walk animation CSS, bark handler, path debug overlays, and visited-node localStorage removed |
| Verify every node opens the correct popup immediately | Required — scenario, game, shop/special, locked, and completed/retake states |
| Ambient animation art direction for each district | Removed from current direction |
| Battery Status API | Not applicable — decorative map animations removed |
| Adult district map topology (if/when added) | Not designed — topology structure above covers pediatric only |
