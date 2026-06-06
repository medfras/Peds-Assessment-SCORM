# PFD EMS Simulator — Rewards System Rules

All award logic is **server-authoritative**. The client receives values from `/api/me/progress` and displays them; it never computes final XP, treat, or collectible amounts.

> **Status note:** This document records the **current live reward mechanics** and also the **planned V2 presentation direction** where noted. Current live implementation still uses treats and toy terminology in several places. Planned V2 direction re-themes the visible collectible layer toward station-authentic rewards: **challenge coins**, **station/unit patches**, and **pins/decals**.

---

## 0. Planned V2 Reward Direction *(planning; not live yet)*

The planned direction is to preserve the existing reward architecture while updating the player-facing fiction and category framing.

### 0.1 Collectible hierarchy

Recommended visible collectible types:

- **Challenge coins** — primary district / map completion collectibles
- **Station / unit patches** — branch and convergence milestone rewards
- **Pins / decals** — smaller side rewards for mini-games, streaks, or category mastery

### 0.2 Why this direction

- better fit with EMS / fire culture than toys, medals, or ribbons
- stronger B2B optics for training officers, chiefs, and agencies
- more professional presentation without removing collectibility
- more visual variety than ribbon-only systems

### 0.3 Planned district/category framing

The live district labels are whimsical and map to the current toy shelf architecture. Planned V2 category framing should shift toward a station dashboard + district map model:

| Planned district name | Theme | Current broad content |
|---|---|---|
| Pediatric Community Response District | Schools, daycares, playgrounds, homes, pediatric public/community calls | Pediatric Medical + Pediatric Trauma |
| Adult Medical Response District | Homes, workplaces, public collapse/illness scenes, adult non-trauma calls | Adult Medical |
| Adult Trauma Response District | Roadways, industrial spaces, sports/recreation, violence/injury scenes | Adult Trauma |
| Complex Incident Response District | Multi-system, high-acuity, mixed-domain, advanced and convergence content | Advanced / Complex Scenarios |

The goal is to let the **home page function like a station dashboard**, with districts laid out on a map rather than as abstract shelves.

---

## 1. XP

### 1.1 Full Scenario

XP is split into two components computed by the server.

#### Assessment XP (max 500)

| Assessment score (0–80) | XP awarded |
|-------------------------|------------|
| 80 (100%)               | 500        |
| 72–79 (90–99%)          | 375        |
| 64–71 (80–89%)          | 250        |
| 56–63 (70–79%)          | 165        |
| 48–55 (60–69%)          | 100        |
| < 48 (< 60%)            | 0          |

#### Narrative XP (max 100)

Linear: `round(narrative_score / 20 × 100)`. Narrative score is 0–20.

#### Best-attempt delta rule

`xp_gross = assessment_xp + narrative_xp`

`xp_earned = max(0, xp_gross − best_prior_xp_for_this_scenario)`

Only the improvement over your previous best run for that scenario (at the same agency) counts toward your total. Running the same scenario again only earns XP if you score higher.

**First completion** of a scenario: `best_prior_xp = 0`, so full `xp_gross` is credited.

There is no daily cap on full-scenario XP.

---

### 1.2 Drill Mode

| Metric | Value |
|---|---|
| XP formula | `_xp_for_score(score) ÷ 2` (legacy score table, halved) |
| Per-run ceiling | 75 XP |
| Daily cap | 150 XP |
| Delta rule | Same as full scenario but compared only against prior drill attempts |
| Badges / treats / toys | **None** |

---

### 1.3 Random Call

| Metric | Value |
|---|---|
| Assessment max | 200 XP |
| Narrative max | 100 XP |
| Daily cap | 600 XP |
| Badges / treats / toys | **None** |

XP formulas are the same as full scenario but with lower maximums. The daily cap is shared across all random calls that day.

---

### 1.4 Lexi Challenge (solo rounds)

| Metric | Value |
|---|---|
| Rounds that earn XP per day | 3 |
| XP per round | `score × 2` (score 0–5); doubled to `score × 4` on a perfect 5/5 |
| Max per perfect round | 20 XP |
| Max per day (solo) | 60 XP |

---

### 1.5 Lexi Group Session

Same per-round XP formula as solo Lexi, capped at the same 3-round daily limit.

**Round winner bonus:** +10 XP per round won. This bonus is outside the normal daily cap.

---

### 1.6 PAT Mini-game (Peds Map — Entrance)

| Metric | Value |
|---|---|
| Formula | `round(accuracy% / 100 × 30)` |
| Per-run max | 30 XP |
| Daily cap | 30 XP |
| Treats | +1 treat, once per 24-hour window (see §2.2) |

---

### 1.7 Dev Sort Mini-game (Peds Map — Medical Trail)

| Metric | Value |
|---|---|
| Formula | `round(accuracy% / 100 × 30)` |
| Per-run max | 30 XP |
| Daily cap | 30 XP |
| Treats | +1 treat, once per 24-hour window (see §2.2) |

---

### 1.8 Levels

| Level | XP required | Title |
|---|---|---|
| 1 | 0 | Recruit 🪖 |
| 2 | 250 | Trainee 🎯 |
| 3 | 800 | Probie 🚒 |
| 4 | 2,700 | Fully Certified ✅ |
| 5 | 3,800 | Team Lead 👥 |
| 6 | 5,200 | Field Training Officer ⭐ |
| 7 | 6,900 | Instructor 📘 |
| 8 | 8,900 | Incident Commander 🦺 |
| 9 | 11,200 | Supervisor 🧭 |
| 10 | 13,800 | Chief 👑 |

---

## 2. Treats 🦴

Treats are the in-game currency used to spend on Lexi hints during a session and to purchase toys in the shop.

### 2.1 Earning treats — full scenario

Treats are earned at the end of a full scenario via four sources. Drill and Random Call award no treats.

| Source | Amount |
|---|---|
| XP milestone | `xp_gross ÷ 1000` (integer division, one treat per 1,000 gross XP) |
| New badge unlocked | +1 per badge earned that run |
| Level-up | +1 per level gained that run |
| Toy duplicate | +`toy.duplicate_treat_value` (usually 1) per duplicate toy rolled |

### 2.2 Earning treats — mini-games

Each mini-game awards **+1 treat** on first completion within a 24-hour window. Replaying the same mini-game on the same calendar day earns no additional treats. Each mini-game tracks its daily window independently.

| Mini-game | Treat per 24h window |
|---|---|
| PAT Mini-game | 1 |
| Dev Sort Mini-game | 1 |

This rewards genuine engagement with optional learning content without enabling treat farming through repetition.

### 2.3 Earning treats — Lexi Group Session

| Source | Amount |
|---|---|
| Completing a group session | 1 treat |
| Daily cap | 1 treat per day |

### 2.4 Wallet cap

The maximum treats a user can hold at any time is **15 treats**. Treats that would be earned beyond the cap are not credited. The cap creates natural spend pressure — players must buy toys or use hints before they can accumulate further treats.

The wallet cap is enforced server-side on all earn events.

### 2.5 Spending treats

Treats can be spent in three ways:

- **Lexi hint during a session** — pay treats to ask Lexi for a hint on the current call. The cost increases with each hint used within the same session:

  | Hint number (within session) | Cost |
  |---|---|
  | 1st hint | 1 treat |
  | 2nd hint | 2 treats |
  | 3rd hint and beyond | 3 treats |

  The hint counter resets at the start of each new scenario session. Spending any treat sets the `treats_spent` flag on the session, which disables Epic toy drops for that run (see §3).

- **Toy shop purchase** — spend the listed price to add a shop toy to your collection directly.

- **Toy sell-back** — sell a toy from your collection back to the shop for treats (see §3.5). This is intended as an emergency lever, not a routine conversion strategy; the sell-back rate ensures a real loss.

### 2.6 Starting treats

New users begin with **3 treats**.

---

## 3. Toys (Lexi's Toy Box) — Current Live System

Toys are collectibles tied to scenario categories. Each scenario category maps to a **Toy District** (toy category). Only **full scenario** completions are eligible for toy drops.

### 3.1 Eligibility check order

The server evaluates conditions in strict priority order. The **first matching rule wins** — only one toy is granted per session.

| Priority | Condition | Result |
|---|---|---|
| 1 | **First-time clear** — no prior completed session for this scenario (supersedes and does not stack with personal best) | Guaranteed **Common** |
| 2 | **Mastery + No-hint** — mastery threshold met AND exactly `0` treats spent (enforced strictly server-side) | Roll for **Epic** (25% chance); guaranteed **Rare** on miss |
| 3 | **Mastery only** — mastery threshold met (treat was spent) | Guaranteed **Rare** |
| 4 | **Pity: Rare** — 6+ eligible runs in this district without a Rare drop | Guaranteed **Rare** |
| 5 | **Pity: Common** — 3+ eligible runs in this district without any drop | Guaranteed **Common** |
| 6 | **Personal best** — improved score over prior best (not first clear) | 40% chance of **Common** |
| 7 | **Standard eligible** — non-farming run, none of the above | 40% chance of **Common** |
| —  | **Anti-farm block** — same scenario, same calendar day, score is equal to or lower than the day's best (legitimate same-day improvement triggers Personal Best instead) | **No drop** (pity does not increment) |

### 3.2 Mastery threshold

Default mastery threshold: **85%** of the maximum assessment score (80 points), meaning an assessment score of ≥ 68 out of 80.

Individual scenarios can override the threshold via `mastery_threshold_override` in the scenario JSON.

*Note: This threshold should be periodically calibrated against real-world `SimSession` data (e.g., targeting the 80th-90th percentile) to ensure stability against AI grading variance.*

### 3.3 Pity timers

Pity counters are tracked **per user, per toy district**. All counters increment on any non-drop eligible run. Any toy grant resets the counters for that rarity **and all rarities below it** (cascade reset rule):

- Epic granted → resets epic, rare, and common counters
- Rare granted → resets rare and common counters
- Common granted → resets common counter only

Pity does **not** increment on anti-farm-blocked runs.

### 3.4 Duplicates

If the randomly selected toy is already in your collection, you receive **no second copy** of the toy but instead earn a treat payout equal to the toy's `duplicate_treat_value` (default: 1 treat). The duplicate treat payout is included in `treats_earned` on the debrief screen.

### 3.5 Shop purchases

Some toys are available to buy directly in the Toy Shop for a fixed treat price. Earn-only Epic toys (`is_earn_only = true`) cannot be purchased. If you buy a toy you already own, you receive the duplicate treat payout instead of a second copy.

### 3.6 Toy sell-back

Any toy in your collection that has a listed shop purchase price can be sold back to the shop for treats. The sell-back payout is:

`sell_back_treats = max(1, floor(purchase_price × 0.35))`

| Purchase price | Sell-back payout |
|---|---|
| 1–2 treats | 1 treat |
| 3–5 treats | 1 treat |
| 6–8 treats | 2 treats |
| 9–11 treats | 3 treats |

Earn-only toys (`is_earn_only = true`) cannot be sold back. Selling a toy permanently removes it from your collection; it must be re-earned or re-purchased to recover it.

Sell-back is designed as an emergency action — a deliberate sacrifice to fund a critical hint — not a routine farming loop. The 35% recovery rate ensures selling always feels costly.

### 3.7 Toy districts (categories)

Toy shelves map 1:1 with the `ADVENTURE_DISTRICTS` defined in the application.

| District | Scenario categories covered |
|---|---|
| Puppy Park | Pediatric Medical, Pediatric Trauma |
| Neighborhood Walk | Adult Medical |
| Doggy Daycare | Adult Trauma |
| Dog Park | Advanced / Complex Scenarios |

Exact category mappings are stored in the `toy_categories` database table.

### 3.7a Planned V2 district rename mapping *(planning; not live yet)*

The underlying category mapping can remain structurally similar even if the visible fiction changes. Planned rename path:

| Current live label | Planned V2 label |
|---|---|
| Puppy Park | Pediatric Community Response District |
| Neighborhood Walk | Adult Medical Response District |
| Doggy Daycare | Adult Trauma Response District |
| Dog Park | Complex Incident Response District |

### 3.8 Rarity

| Rarity | Drop method |
|---|---|
| Common ⬜ | First-time clear, pity, personal best, standard RNG (40%), shop |
| Rare 🟦 | Mastery run, pity (6 runs), Epic miss on mastery+no-hint run, shop |
| Epic ✨ | 25% roll on mastery + no-hint run only; never farmable via RNG alone |

### 3.9 Series & Content Expansion (DLC Gap)

To prevent the "moving goalpost" problem when new scenarios are added to an existing district, toys are grouped by a `series_tag` (e.g., `series_1`). When a user collects all toys in Series 1, that shelf is permanently marked completed. New content is released as Series 2, giving completionists a new goal without invalidating their prior achievements.

---

## 4. Instructor Visibility *(Planned — not yet implemented)*

Instructors and Admins will have a read-only view of a student's collectible case on the Instructor Dashboard. In current live terminology this is the Toy Chest; in planned V2 framing this becomes a **challenge coin / patch / pin display**. Either way, it provides a visual heat map of the student's clinical exposure and mastery. A shelf or district rich in **Rare** and **Epic** drops signals stronger demonstrated competence in those domains than one consisting only of **Common** rewards.

---

## 5. Phase 5: "Next Best Action" Engine

To ensure the collection system drives pedagogical value rather than cosmetic grinding, a future Phase 5 will implement an automated study pathway. Lexi will analyze incomplete district collections and recommend specific un-mastered scenarios to players (e.g., "You still haven't earned the rare airway coin from the Pediatric Asthma scenario."), acting as an automated tutor that targets a student's weak points.
