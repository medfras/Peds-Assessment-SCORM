# RescueTrails UI Style Guide

This guide formalizes the UI design principles, components, and theming for the **RescueTrails** application. It ensures a consistent, high-quality experience that balances a warm companion-guided learning environment with the operational urgency of EMS and fire-rescue simulation.

## 1. Design Philosophy & Theming

RescueTrails uses a **Dual-Theme Design System** to psychologically separate the training dashboard from the active simulation.

### Station Dashboard (Menu / Home / Learning)

Used for the home screen, category navigation, history, and all non-simulation screens.

> **Feel:** Station wall board · field notebook · operations planning board
> **Not:** storybook parchment, toy shelf, sterile enterprise portal

Base palette is off-white/paper with steel-gray surfaces, slate-charcoal dark panels, and fire-red/EMS-blue as purposeful accents. The goal is professional, warm, and prehospital — readable by training officers and learners equally.

### Operational Dark (Active Simulation)

Used for all active simulations including dispatch, the main scenario interface, and intervention modals.

> **Feel:** Dark console · apparatus bay · command screen
> **Not:** warm brown-black, generic dark mode

Base palette is cool dark gray/near-black with white text, red for critical alerts, and blue for operational accents. Structurally distinguishes the FTO/evaluation surface from the Lexi/coaching surface.

### Theme Role Split

| Layer | Role | Tone |
|---|---|---|
| Lexi | Companion, coaching, debrief voice | Warm, supportive, non-judgmental |
| FTO / System | Evaluation, scoring, official record | Professional, concise, objective |
| District world | Training-space framing and navigation | Operational, prehospital |
| Rewards | Progression and identity display | Professional, collectable |

Lexi is not the formal scorer. The FTO is not the mascot. These surfaces must be visually distinguishable.

---

## 2. Color Palette

### Station Dashboard Palette

| Role | Hex | CSS Variable | Usage |
|:---|:---|:---|:---|
| Page Background | `#f2f0eb` | `--hv2-page-bg` | Main background for all menu/home screens |
| Card Surface | `#ffffff` | `--hv2-card-bg` | Cards, elevated panels |
| Card Border | `#d5d2cb` | `--hv2-card-bdr` | Standard card borders |
| Nav Background | `#161c23` | `--hv2-nav-bg` | Left navigation panel |
| Topbar / Bottombar | `#1b2028` | `--hv2-topbar-bg` | Top and bottom chrome |
| Call Board | `#1e252e` | `--hv2-call-bg` | Right call board panel |
| Text — Primary | `#1b2028` | `--hv2-text` | Main headings and body text on light bg |
| Text — Secondary | `#4b5563` | `--hv2-text-2` | Descriptions, meta on light bg |
| Text — Muted | `#6b7280` | `--hv2-text-muted` | Helper text, disabled states |
| Text — Light | `#f0ede7` | `--hv2-text-light` | Primary text on dark surfaces |
| Text — Dim | `#9ca3af` | `--hv2-text-dim` | Meta text on dark surfaces |

### Operational Dark Palette (Simulation)

| Role | Hex | CSS Variable | Usage |
|:---|:---|:---|:---|
| Page Background | `#1b2028` | `--ui-sim-bg` | Main simulation background |
| Panel Surface | `#20272f` | `--ui-sim-panel` | Side panel surfaces |
| Text — Primary | `#f0ede7` | `--ui-sim-text` | High-contrast scenario text |
| Text — Muted | `#9ca3af` | `--ui-sim-muted` | Timestamps, secondary info |
| Border | `rgba(255,255,255,0.09)` | `--ui-sim-border` | Panel dividers |

### Semantic & Accent Colors

| Role | Hex | Usage |
|:---|:---|:---|
| **Fire Red (Primary Brand)** | `#c41e3a` | Primary actions, brand mark, rank badges |
| **EMS Blue (Secondary)** | `#1a56db` | Secondary actions, info accents, active tabs |
| **Gold / Brass (Progression)** | `#b8970f` | XP bars, rank progression, premium states |
| **Success** | `#16a34a` | Correct answers, pass, completed |
| **Danger / Critical** | `#dc2626` | Critical vitals, incorrect answers, destructive |
| **Amber (Warning only)** | `#d97706` | Caution states only — not decorative |

### District Accent Families

Each district gets a consistent accent color applied to its map tile, progress indicators, and card chrome.

| District | Accent |
|:---|:---|
| Pediatric Community Response | Sky blue `#0284c7` |
| Adult Medical Response | Deep blue `#1d4ed8` |
| Adult Trauma & Rescue Response | Fire red `#b91c1c` |
| Complex Incident Response | Slate `#334155` |

These are guidance accents — not full-screen washes. All four districts carry equal visual weight on the home map.

---

## 3. Typography

### Font Families

- **Display / Section Headers:** `Barlow Condensed` (500, 600, 700) — district names, board titles, district card names, button labels in operational contexts
- **Body / UI Text:** `Inter` (300–800) — all body copy, labels, meta, form fields
- **Data:** Monospace (`font-mono`) — vital signs, timers, scores

Both display fonts are loaded via Google Fonts.

### Hierarchy

| Element | Font | Size | Weight | Case |
|:---|:---|:---|:---|:---|
| App Title / Logo | Barlow Condensed | 15–21px | 700 | Title Case |
| Board / District Title | Barlow Condensed | 18–22px | 700 | UPPERCASE |
| District Card Name | Barlow Condensed | 17px | 700 | UPPERCASE |
| Section Label (kicker) | Inter | 9.5–10px | 600 | UPPERCASE · tracked |
| Body / Nav Label | Inter | 12–13px | 400–600 | Sentence case |
| Data (vitals, timers) | Monospace | varies | — | — |

---

## 4. Home Screen Layout

### Station Dashboard Structure

```
[TOPBAR]  Logo · On-Shift pill · Rank + XP bar · Treats
[BODY ROW]
  [LEFT NAV — 52px collapsed / 224px expanded]
    Profile, Streak, Leaderboard, Challenges,
    Collectibles, Training Center, Notebook,
    Admin, Settings, Sign Out
  [MAIN BOARD — flex:1]
    District Grid (2×2 — all four districts, equal weight)
  [RIGHT CALL BOARD — 258px]
    Lexi bubble, Active call, Call history, Receive Dispatch
[BOTTOM BAR]  Replay orientation link
```

### Key Layout Rules

- District grid is the primary navigation surface on the home screen
- All four districts appear at equal visual weight — no district is a prerequisite for another
- Left nav starts collapsed (icon-only, 52px); expands to 224px on toggle
- Training Center is a nav item, not a district card
- Orientation replay is a small unobtrusive link in the bottom bar

---

## 5. UI Components

### District Cards

District cards are generated by JS into `#menu-categories`. Each card uses:

- `data-district` attribute to scope accent color via CSS custom property `--d-acc`
- Top accent bar (4px solid, `--d-acc` color)
- Barlow Condensed district name in UPPERCASE
- District description, stats row (Scenarios / Completed / Mastered), progress bar, Enter button
- Hover: `translateY(-1px)` lift + elevated shadow

Planned districts use `--d-acc: #475569` (slate) and are visually dimmed.

### Navigation Items

Left nav items share a consistent pattern:

- 32×32px icon container with subtle background
- Label + optional sub-label (hidden when nav collapsed)
- Collapsed state: icon only + red badge dot for items with counts
- Expanded state: full label, sub-label, badge count

### Buttons

- **Primary (Fire Red):** `background: var(--hv2-red)` — Enter District, Receive Dispatch
- **Secondary (EMS Blue):** `background: var(--hv2-blue)` — Continue Call, secondary actions
- **Ghost / Outline:** `border: 1px solid rgba(255,255,255,0.18)` on dark surfaces — Training Center, Settings
- **Danger:** `border-color: #ef4444; color: #ef4444` — Sign Out, destructive actions
- Hover: `filter: brightness(1.1)` on solid buttons; `background: rgba(255,255,255,0.08)` on ghost buttons

### Modals

All menu-context modals (Challenges, Badges, Collectibles, Leaderboard, Edit Profile) use the **Warm-Light Modal System** regardless of whether the simulation dark theme is active.

- Backdrop: `bg-black/75` to `bg-black/90`
- Shell: warm cream gradient body — `rgba(255,252,245,0.99)` — with subtle amber tint, `1.5px` amber border, `rounded-xl`, `shadow-2xl`
- CSS classes: `.lexi-modal-shell`, `.modal-form-shell`, `.menu-modal-shell`, `.toy-chest-shell`, `#modal-edit-profile`

### Lexi Bubble (Home / Call Board)

On the home screen, Lexi appears at the top of the right call board as a small avatar + speech bubble. Bubble style on dark surfaces:

- Background: `rgba(255,255,255,0.08)`
- Border: `rgba(255,255,255,0.10)`
- Border radius: `8px` with `2px` top-left (tail position)
- Text: `#c9cdd4` body, `#f0ede7` strong

### Call Board

The right sidebar operates as a CAD-style call list:

- **Lexi bubble** — top of panel, coaching nudge
- **Current district badge** — shows active district with accent dot
- **Last active card** — in-progress call with Continue button
- **Call history** — compact log with left accent bar, district tag, result badge
- **Receive Dispatch** — fire red CTA button at bottom, dispatches random call from current district

### Reward Presentation (Collectibles)

| Type | Purpose | Visual language |
|:---|:---|:---|
| Challenge coins | District/map completion collectibles | Brushed metal / enamel accents |
| Station/unit patches | Branch and convergence milestones | Stitched fabric-inspired |
| Pins/decals | Streaks, mastery, mini-game rewards | Smaller bright accents |

Avoid candy gloss, toy-plastic language, or overly formal military-decoration aesthetics.

---

## 6. Layout & Grid

- **Home:** Full-viewport fixed layout (`height: 100vh; overflow: hidden`) with three-column flex body
- **District Grid:** CSS Grid `1fr 1fr` / `1fr 1fr` — 4 cards filling available height
- **Simulation Workspace:** Three-column flex on desktop; bottom-tabbed on `< 1024px`
  1. Left (27rem): Reference panel (PCR, notes, scene)
  2. Center (fluid): Primary action (chat)
  3. Right (72px–12rem): Lexi tools
- **Modal max-widths:** `max-w-md` (focused), `max-w-lg` (form), `max-w-3xl` (collection views)

---

## 7. Motion & Interaction

Animation is purposeful and respects `@media (prefers-reduced-motion: reduce)`.

- **Nav expand/collapse:** `width` transition `0.22s cubic-bezier(.4,0,.2,1)`
- **District card hover:** `translateY(-1px)` + shadow — `0.14s`
- **Lexi idle:** 4s floating translation (`lexi-login-idle`)
- **Lexi excited/thinking:** rapid rotation/scale sequences
- **Score reveal:** pop/scale spring animation (`score-pop`)
- **Toasts:** slide-up fade-in (`toast-in`)
- **Vitals pulse:** red pulse at 1.5s for critical values

---

## 8. UX Principles

1. **Clear affordance:** Buttons look clickable; disabled states use `opacity-40` + `cursor-not-allowed`
2. **Progressive disclosure:** Complex procedures hide step-by-step detail behind collapsible toggles
3. **Role clarity:** Lexi surfaces (warm, speech-bubble) are visually distinct from FTO evaluation surfaces (formal, structured)
4. **Error prevention:** Medication administration requires explicit 6-Rights checkbox confirmation
5. **Feedback:** Every action produces immediate visual response — green flash, toast, Lexi expression change
6. **Authority boundary:** Backend state is always authoritative — frontend never derives scoring, session authority, or readiness from UI state alone
