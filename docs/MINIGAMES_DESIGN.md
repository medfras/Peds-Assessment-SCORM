# Mini-Games Design

**Status:** Active Design  
**Last Updated:** 2026-05-05 (open decisions resolved)  
**Scope:** Focused learning mini-games used by the main RescueTrails application and derivative training packages.

This document defines the mini-game catalog, shared design rules, scoring expectations, and implementation boundaries for RescueTrails. It consolidates the pediatric-map mini-game direction and adds the new games introduced by the Peds Assessment SCORM Lite plan.

This document does **not** redesign currently developed games. `PAT Doorway Dash` and `Lexi's Development Toy Box` retain their existing designs and implementation behavior unless a future change request explicitly targets them.

---

## 1. Design Principles

Mini-games are short, deterministic learning reps. They prime a cognitive skill before the learner applies that skill in a scenario.

The primary audience is continuing education for learners who have already been exposed to the material. Mini-games may also support initial education, but they are supplemental practice, not the primary instructional vehicle. The default design posture is therefore retrieval, recognition, judgment, and transfer into field action rather than lecture, passive reveal, or definition recall.

**Mini-games should:**
*   Train one clearly named skill at a time.
*   Use deterministic scoring from authored answer keys.
*   Finish quickly enough to be replayed without fatigue.
*   Produce stable result records that can drive progression, treats, debrief next-action routing, and instructor analytics.
*   Use existing engines where practical: swipe/card classification, drag/sort, scored-order sort, calculation, body-map tap, audio matching, or case vignette. Each engine is extended via data configuration, not by forking the engine code. Extensions must not change the defaults of any existing game.
*   Prefer clinical implications over abstract definitions. For example, ask how a pediatric anatomy difference changes airway positioning rather than asking the learner to sort a naked anatomy fact.
*   Use experimentation with immediate feedback. A wrong answer should help the learner test the boundary of a concept, not simply reveal an answer key.
*   Ask for priority, implication, or next-best question when a rote classification would be too easy for an experienced provider.
*   Use Socratic string feedback as the default remediation pattern. Feedback should guide the learner from cue → reasoning → contrast with distractor → corrected principle, rather than only naming the right answer.
*   Offer learner-requested hints during play. Hints are free and should reduce confusion, but must not give away the answer, identify the correct option, or remove the need to reason through the task.
*   Treat reference cards as earned learning artifacts. Full learning/reference cards should remain locked until the learner passes the relevant game or mastery sequence at least once. Before unlock, the UI may provide lightweight hints, Socratic prompts, or brief definitions, but not the complete reference card.
*   Chain related games into short mastery flows when one game scaffolds another. For example, a mnemonic recognition game should flow directly into an application/phrasing game before awarding the reference card. The learner should experience this as a guided path, not a disconnected menu.
*   Use soft time pressure where field decision speed is part of the clinical skill. A visible countdown or progress indicator with score implications (not a hard cutoff) signals that pattern recognition rather than deliberate recall is the target, matching the cognitive demand of real assessment. Do not use time pressure as a punitive mechanic. If a game's core skill does not benefit from speed (e.g., medication dose calculation), omit it. **Accessibility rule:** timers may affect bonus or efficiency credit but must never hard-fail a game or block submission. Learners using assistive technology or slower devices should still be evaluated primarily on clinical judgment, not input speed.
*   Bridge to scenario context. Frame each game with a brief pre-play prompt naming the scenario type where this skill applies, and offer a direct scenario launch from the post-game results screen. Transfer is strongest when a primed skill can be applied immediately. The intended loop — mini-game → scenario → debrief → targeted mini-game — should be surfaced in learner-facing UX, not left implicit. **Routing rule:** only route to scenarios that are unlocked and available to the learner. If the ideal scenario is locked, show it as a "recommended when unlocked" label and surface the best available alternative so the learner loop does not dead-end.

**Mini-games should not:**
*   Use the LLM for grading.
*   Establish authoritative scenario facts.
*   Replace scenario performance scoring.
*   Gate clinical truth, protocol scope, interventions, or debrief scoring from frontend-only state.

The backend may record mini-game completion, best score, attempt count, XP/treat awards, and analytics. The frontend may provide immediate interaction and feedback, but persisted progression must be backend-confirmed in the main SaaS app.

### Feedback Standard

Mini-game feedback should be short, specific, and Socratic. The goal is to reinforce the reasoning path the learner should reuse in a scenario.

Effective feedback should:
*   Name the observable cue the learner should have used.
*   Explain why that cue points toward the correct concept or action.
*   Contrast the nearest plausible distractor when the learner misses by one step.
*   Connect the concept to field care, protocol selection, or documentation when appropriate.
*   Avoid immediately highlighting the correct answer in retry-until-correct modes unless the learner has exhausted the authored retry limit.

Example: if a learner chooses pediatric GCS motor 4 instead of motor 5, feedback should not only say "M5 is correct." It should prompt the reasoning: "The patient reached across midline to push your hand away. Does that describe withdrawing from pain, or localizing the painful stimulus?"

**Socratic string template:** When a game can support richer feedback, use this four-step pattern:
1. Identify what the learner selected or built.
2. Ask which clinical cue, mnemonic component, or rule should drive the decision.
3. Contrast the learner's choice with the closest plausible distractor.
4. Confirm the corrected answer and explain how it changes assessment, treatment, transport, or documentation.

**Speed-game exception:** Rapid pattern-recognition games such as `pat_dash`, `ten4_facesp`, Shock Spotter, and other swipe/tap drills should not interrupt every card with a long Socratic explanation. During the active round, use micro-Socratic nudges that preserve cadence, such as "Notice the retractions?" or "Age plus torso bruising matters here." Save the full four-step explanation for the end-of-round missed-card review, where the learner can slow down without breaking the doorway-assessment flow. **Dependency note:** PAT Doorway Dash and TEN-4 FACESp do not currently have a missed-card end-of-round review screen; this review screen must be designed and added to those game designs before the speed-game exception can be fully realized. Until then, brief card-level feedback on the round result screen is the minimum acceptable display for missed cards.

### Hint Standard

Hints are learner-requested supports, not penalties and not answer reveals.

Hint behavior should:
*   Be available from the game screen before submission or while retrying.
*   Point to the relevant cue, rule, component, or reasoning lens.
*   Avoid naming the correct answer, highlighting the correct option, or eliminating all distractors.
*   Be authored per card/case when possible; generic fallback hints are acceptable only when they still preserve the reasoning task.
*   Be logged for analytics when practical (`hint_count`) but should not reduce the base score unless a future game explicitly awards a separate no-hint bonus.

Example: for a lung sound card, a hint may say "Decide whether the sound is upper-airway harsh/crowing or lower-airway musical/continuous." It should not say "This is stridor."

### Earned Reference Cards and Mastery Flows

Reference cards are rewards for demonstrated retrieval, not pre-game answer sheets.

Shared rules:
*   A full reference card unlocks only after the learner passes the associated game at least once.
*   If a skill has a scaffold game and an application game, the reference card unlocks only after both pass conditions are met.
*   Multi-step flows should guide the learner from the scaffold step into the application step automatically when appropriate.
*   The earned-card reveal should summarize the reusable framework, common traps, and 2–3 high-quality field examples.
*   After unlock, the reference card may be available from the learning area, game result screen, and debrief next-action view.
*   Before unlock, show only brief hints and Socratic prompts, not the full card content.

### Instructional Design Recommendations

The current catalog is strongest where the learner has to recognize patterns, test multiple plausible answers, or calculate from a vignette. Preserve the core loops for `pat_dash`, `ten4_facesp`, `ams_aeioutips`, `peds_gcs_calculator`, and the audio lung-sound games.

The main improvement area is to avoid CE games that only ask learners to sort definitions into buckets. When a game starts to feel like "teach then test," prefer one of these upgrades:
*   Convert fact cards into clinical implication cards.
*   Convert mnemonic sorting into "what is the most important missing information?" prompts.
*   Convert normal-development recall into red-flag or regression recognition.
*   Add a second-step implication prompt after a correct identification.

For CE learners who show consistent proficiency — three or more sessions above 80% on a given skill tag — the game or next-action routing should progress toward harder card variants, implication-first prompts, or scenario practice rather than replaying beginner card banks. Adaptive difficulty must be driven by mistake-tag analytics, not applied globally. The goal is to keep experienced providers in a zone of productive challenge rather than reviewing content they have already mastered.

When a game uses a scored-order or sequence mechanic (e.g., BLS Sequence), the learner should commit to and submit the full sequence before the correct order is revealed. Per-step confirmation converts the game into guided discovery, reducing the cognitive cost of committing to a mental model and weakening the learning effect. Reveal the whole answer at once so the learner can compare their full reasoning against the correct sequence.

Rapid matching and live/timed modes should include light anti-guessing friction. If an incorrect selection can be retried immediately, add a short lockout, animation, or efficiency penalty so learners cannot rapid-tap their way to the answer. This friction should be brief enough to preserve pace, but noticeable enough to make reading the clinical cue faster than guessing.

---

## 2. Result Contract

Every mini-game submits the same result shape. Games with legacy route-specific payloads should migrate to this shape.

```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "minigame_id": "pat_dash",
  "mode": "ce",
  "score": 86,
  "max_score": 100,
  "correct_count": 6,
  "total_count": 7,
  "mistake_tags": ["upper_vs_lower_airway"],
  "hint_count": 1,
  "completed": true,
  "duration_seconds": 92
}
```

**Required fields:**
*   `run_id` — client-generated UUID, stable for the duration of a single play attempt. The backend deduplicates on `(user_id, minigame_id, run_id)` and must not double-award treats, XP, toys, or progression on a duplicate submission.
*   `minigame_id` — stable ID, not display label.
*   `score` — integer 0–100 unless a game-specific design explicitly declares another scale.
*   `completed` — `true` when the run counts for progression. Each game's design section declares its completion threshold (e.g. "any submitted run", "score ≥ 70", "all cards seen"). If not declared, any submitted run with `score > 0` counts as completed.

**Recommended fields:**
*   `correct_count` and `total_count`.
*   `mistake_tags` — per-game vocabulary declared in each game's design section. All mistake tags in use anywhere in the catalog are also listed in §8 for analytics cross-reference.
*   `hint_count` for learner-requested hints used during the attempt.
*   `duration_seconds` for instructional tuning.
*   `mode` — optional string identifying the variant or difficulty tier played within a single `minigame_id`. Examples: `"foundation"` vs `"interview_builder"` for History Maker, `"scaffold"` vs `"ce"` for Adult vs. Child A&P. The backend stores `mode` alongside the result record so adaptive routing and analytics can distinguish mode-level performance without requiring separate `minigame_id` values. Games with only one mode omit this field. Add `mode` before CE/scaffold deck variants ship; mixing untagged and tagged runs for the same game ID will corrupt adaptive tier routing.

### Completion Threshold Policy

Every game must declare one of the following in its design section:

| Threshold type | Example declaration |
|---|---|
| Any submission | "Any submitted run counts as completed." |
| Score floor | "Completed when score ≥ 70." |
| Full coverage | "Completed when all cards or components are seen at least once." |

Games that do not explicitly declare a threshold use **any submitted run with `score > 0`** as the default.

### Pass Threshold Policy

`completed` and `passed` are separate concepts.

*   `completed` means the attempt counts for progression, analytics, and replay history.
*   `passed` means the learner demonstrated enough proficiency to unlock reference cards, satisfy mastery-flow gates, or count toward adaptive-proficiency calculations.

Every game or mode that can unlock a reference card must declare a `pass_threshold` in static metadata. Default pass threshold is `score >= 80` unless the game section declares a different threshold. Do not use `completed: true` by itself to unlock earned reference cards.

### Static Game Metadata

Each mini-game also needs static metadata used by learning navigation, reference-card unlocks, and deterministic debrief routing. This is authored once per game or per game mode; it is not submitted as mutable per-run learner data.

Static metadata should include:
*   `skill_tags` — reusable skill vocabulary used for analytics and adaptive difficulty.
*   `rubric_category_mapping` — exact scenario rubric category IDs the game directly remediates. This powers Learning Design Priority 5 routing. Do not recommend a mini-game for a failed rubric category unless this mapping explicitly includes that category. Current top-level category IDs include `clinical_performance`, `protocols_treatment`, `narrative`, `dmist`, `professionalism`, and `scope_adherence`; item-level IDs may be added later as the scoring engine exposes them.
*   `pass_threshold` — score and mode criteria required for the run to count as a pass for reference-card unlocks and mastery flows.
*   `hint_policy` — where hints appear, what reasoning lens they point to, and what they must not reveal.
*   `reference_card` — reference card ID, unlock condition, outline of card content, and whether unlock depends on a mastery flow.
*   `mastery_flow` — predecessor or successor games/modes, if the skill has a scaffold → application sequence.
*   `adaptive_next_step` — what changes after demonstrated proficiency, defined as three or more runs at or above 80% unless a game declares a different threshold.

Example:

```json
{
  "minigame_id": "history_maker",
  "mode": "interview_builder",
  "skill_tags": ["history_taking"],
  "rubric_category_mapping": ["clinical_performance", "narrative"],
  "pass_threshold": {"score_gte": 80},
  "hint_policy": "Point to the target OPQRST/SAMPLE component and patient cue; do not identify the correct chunk sequence.",
  "reference_card": {
    "id": "ref_opqrst_sample_peds",
    "unlock_condition": "pass history_maker/foundation and history_maker/interview_builder",
    "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"]
  },
  "mastery_flow": {
    "previous": "history_maker/foundation",
    "next": "reference_card/ref_opqrst_sample_peds"
  },
  "adaptive_next_step": "After proficiency, route to scenario practice or caregiver/complex-source Interview Builder cases."
}
```

Reference-card content should use a consistent schema:

```json
{
  "card_id": "ref_breath_sounds_actions",
  "title": "Breath Sounds & Field Actions",
  "framework_summary": ["..."],
  "common_traps": ["..."],
  "field_examples": ["..."],
  "related_game_ids": ["lung_sounds_matcher", "sound_check"],
  "unlock_condition": {"all_passed": ["lung_sounds_matcher:audio_id", "lung_sounds_matcher:implication"]},
  "review_status": "draft|clinical_review_pending|approved"
}
```

### Idempotency

Result submission must be idempotent. The backend upserts on `(user_id, minigame_id, run_id)`. On a duplicate `run_id`, the backend updates stored analytics fields but does not re-award treats, XP, progression records, or toy notifications. The frontend should generate a fresh `run_id` at the start of each new play attempt, not on retry of the same attempt.

### ID Policy

The main app and SCORM packages use the same stable `minigame_id` for the same game. Package-specific node IDs may still exist for map placement or SCORM suspend-data keys, but they are aliases that point to the shared `minigame_id`.

Example: SCORM node `med_lung_sounds` launches mini-game `lung_sounds_matcher`.

### SCORM Result → Main-App Progression

SCORM Lite packages do not directly write to the main app's backend. Progression credit (gateway completion, toy notifications, treat awards) only applies in the main SaaS app when the learner plays through the main-app interface. SCORM completion data is not automatically imported into a learner's main-app `PedsMapProgress`, toy chest, or treat balance.

If a product decision later requires SCORM-to-main-app credit sync, that integration must be explicitly designed with a server-side sync endpoint, a deduplication contract, and an audit trail. Until that design exists, treat SCORM results and main-app results as independent records.

---

## 3. Existing Games

### PAT Doorway Dash

**Status:** Existing design. Do not redesign in this document.  
**Stable ID:** `pat_dash`  
**Primary engine:** PAT swipe engine  
**Primary skill:** Rapid Pediatric Assessment Triangle impression: sick vs. not sick.

Current behavior remains authoritative for this game. Future work may add data-only extensions to the same engine, such as configurable labels or audio cards, but must not alter the base PAT game flow unless explicitly scoped.

**Completion threshold:** Any submitted run counts as completed.  
**Main-app placement:** Map 0 entrance.  
**SCORM Lite placement:** Gateway, node `gw_pat`.

### Lexi's Development Toy Box

**Status:** Existing design. Do not redesign in this document.  
**Stable ID:** `dev_sort`  
**Primary engine:** Drag/sort engine  
**Primary skill:** Match pediatric developmental milestones to age groups.

Current buckets, card behavior, completion rules, and reward behavior remain unchanged unless explicitly scoped.

**Future CE variant — Developmental Red Flags (`dev_flags`):** Add a separate mini-game (separate stable ID, separate progression tracking) that presents an age plus behavior and asks whether it is expected, concerning/regression, or needs further assessment. This is the CE-primary interaction for the developmental domain — recognizing delay, regression, communication mismatch, and safety concerns transfers directly to field triage decisions. Milestone-to-age-bucket sorting (the existing Toy Box) remains the scaffold/initial-education form. The Red Flags game uses the same swipe or drag/sort engine but with a three-way classification and authored implication feedback explaining why the finding warrants documentation or escalation.

**CE routing note:** Do not route continuing-education learners to `dev_sort` from scenario debriefs when the deterministic gap is developmental judgment. Route CE learners to `dev_flags`. `dev_sort` remains appropriate for initial education, onboarding, and remediation when milestone recall itself is the gap.

**Mastery flow:** `dev_sort` → `dev_flags` → earned developmental-stage/red-flags reference card. The shared reference card unlocks only after both scaffold milestone recall and red-flag application conditions are met, unless an instructor explicitly assigns the scaffold-only path for initial education.

**Completion threshold:** Existing behavior (first-ever completed play writes `PedsMapProgress("pm1")` via `submit_dev_sort_result`).  
**Main-app placement:** PM1 Intro Medical gateway. Completion writes `PedsMapProgress("pm1")`, which unlocks PM2, PM3, and PM4 simultaneously.  
**SCORM Lite relationship:** Covers the same instructional domain as the new `gw_ap` Adult vs. Child A&P primer, but it is not replaced by that primer.

---

## 4. New Games From Peds Assessment Plan

These games were introduced by the Peds Assessment SCORM Lite plan. They should be treated as reusable main-app mini-game concepts, not SCORM-only throwaways.

### Adult vs. Child A&P

**Proposed stable ID:** `adult_child_ap_swipe`  
**SCORM Lite node ID:** `gw_ap`  
**Primary engine:** PAT swipe engine with three-way configurable labels  
**Primary skill:** Identify clinically relevant anatomical and physiological differences between adults and pediatric patients, especially how those differences change assessment and care.

**Core interaction:** Learners see a short clinical implication, vignette, image, or carefully selected statement and swipe/tap upward for "Both/Shared", left for "Adult", or right for "Child". The three-way interaction is part of the design, not an optional variant. CE rounds should favor implication cards over naked anatomy facts; fact-only cards are acceptable as initial-education scaffold or remediation.

**Content authoring gate:** The CE-default card bank must consist of at least 70% implication cards before the game ships to a CE audience. Fact-only cards (e.g., "larger occiput" → Child) are authored as a scaffold or remediation variant. A card that could appear in a first-year anatomy textbook without modification belongs in the scaffold bank, not the CE-default deck. Do not ship a large card bank to CE learners by padding with anatomy facts; if implication cards have not been authored, ship a smaller deck.

**Mobile UX requirement:** Because upward swipes can conflict with browser scroll or pull-to-refresh gestures, the tri-choice UI must always provide prominent tap buttons for Adult, Both/Shared, and Child. The swipe card container should suppress native gesture handling where safe, such as with `touch-action: none` on the card interaction surface, without blocking page-level accessibility or keyboard navigation.

**Example card themes:**
*   A 3-month-old with severe nasal congestion has increased respiratory risk because infants are obligate nose breathers.
*   Supine positioning can flex an infant's airway because the occiput is proportionally larger; neutral positioning may require a shoulder roll.
*   Children can maintain blood pressure during compensated shock and then decompensate abruptly.
*   Respiratory failure is a common pathway to pediatric arrest, so early work-of-breathing recognition matters.
*   Assessment language and consent/comfort strategies should match developmental stage.

**Scoring:** Deterministic card classification answer key. Partial credit by correct cards. Mistake tags should distinguish airway, circulation, communication, and medication/dosing concepts.

**Hints:** Per-card hints should point to the clinical effect of age, not the category label. Example: "Think about how a proportionally large occiput changes airway position." Do not say "This is pediatric."

**Adaptive V2 direction:** After proficiency, flip from population classification to consequence selection: present a pediatric or adult patient finding and ask what changes in assessment, positioning, dosing, communication, or transport because of age.

**Reference card:** Unlock an "Adult vs. Pediatric Assessment Differences" card after passing the CE implication deck at least once. Card content: airway/positioning differences, shock compensation, communication/source considerations, dosing/weight traps, and 2–3 field examples.

**Completion threshold:** Any submitted run counts as completed.  
**Main-app fit:** Pediatric entrance or optional remediation after poor pediatric assessment performance.

### Lung Sounds Matcher

**Proposed stable ID:** `lung_sounds_matcher`  
**SCORM Lite node ID:** `med_lung_sounds`  
**Related main-map game:** PM2 Sound Check (`sound_check`) uses the same interaction model and engine. They are separate game instances with separate authored content.  
**Primary engine:** Audio matching component plus scope-filtered intervention-choice round  
**Primary skill:** Differentiate clinically meaningful breath sounds and connect them to provider-scope-appropriate field interventions.

**Core interaction:** The game runs as two distinct rounds. Round 1 presents a real audio file only, with no text description of the sound. The learner plays the clip and taps the best match from a fixed option set: Clear, Crackles, Wheezes, Rhonchi, Stridor, and Pleural Friction Rub. Round 2 presents short clinical respiratory vignettes tied to those sounds and asks the learner to choose the best intervention available in their provider scope.

**UX requirement:** Keep lung-sound answering tap-first. Do not convert V1 into drag-and-drop. Large, fixed tap targets keep the learner's cognitive load on audio discrimination rather than mobile pointer precision.

**Required answer dimensions:**
*   Sound identification: clear, crackles, wheezes, rhonchi, stridor, pleural friction rub.
*   Intervention selection: each prompt includes respiratory rate, work of breathing, oxygenation, and relevant signs/symptoms. Choices may include oxygen, BVM ventilations, CPAP, epinephrine, albuterol, suction, needle decompression, positioning, or related protocol actions.

**Intervention scoring:** Round 2 is scope filtered. The frontend only shows choices whose `min_scope` is at or below the learner's provider level. The available denominator for a card is the highest score among visible choices. Best/most appropriate visible interventions earn full available credit; clinically acceptable but less optimal choices earn partial credit; inappropriate choices earn zero and emit the authored intervention mistake tag. This prevents BLS learners from being penalized for ALS-only options while still expecting them to choose the best care within scope.

**Feedback requirement:** When the learner selects an incorrect sound, do not immediately reveal the correct option in retry-until-correct modes. Feedback should describe the discriminating cue, such as "Stridor is harsh and usually inspiratory from the upper airway; wheezes are musical and usually lower-airway."

**Hints:** Round 1 hints should describe the listening cue or airway level without naming the sound. Example: "Decide whether this is upper-airway harsh/crowing or lower-airway musical/continuous." Round 2 hints should point to the treatment branch (oxygenation, ventilation, bronchospasm, upper-airway swelling, secretions, pleural-space emergency) without naming the intervention.

**Adaptive direction:** Do not skip Round 2 for proficient learners. Future adaptive work may increase case acuity or add mixed-scope protocol nuance, but the two-round structure remains the default mastery flow.

**Reference card:** Unlock a "Breath Sounds & Field Actions" card only after the learner passes the two-round flow at least once. Card content: sound descriptions, upper vs. lower airway cues, common confusions, associated conditions, and field action examples.

**Scoring:** Deterministic authored answer key. Round 1 awards one point per correct sound label. Round 2 awards the scoped maximum for the best visible intervention, partial credit for acceptable alternatives, and zero for unsafe or mismatched interventions. Mistake tags should include sound-confusion tags such as `wheeze_vs_stridor`, `rhonchi_vs_crackles`, `pleural_rub_vs_crackles`, and `normal_vs_abnormal`, plus intervention tags such as `wheeze_intervention`, `crackles_intervention`, `rhonchi_intervention`, `stridor_intervention`, and `pleural_rub_intervention`.

**Completion threshold:** All Round 1 clips and Round 2 intervention prompts seen and answered at least once.

**Audio asset requirement:** V1 uses real lung sound audio files. Audio files must be licensed for public deployment before release. Each audio asset must declare its license source in the game data using the `license_source` field (see §7 Audio Matching Component). Text/finding cards are accessibility fallbacks and development fixtures, not the primary shipped experience.

**Audio licensing resolution path:** Stridor and any other unresolved clips remain production-blocked until replaced with public-deployment-safe assets. Acceptable paths are commissioned recordings/simulations with explicit ownership, purchased clinical audio libraries with redistribution rights, or public-domain/CC assets with verified license metadata. Do not ship active audio cards with placeholder or unresolved `license_source` values.

**Training definitions:**
*   Clear: Expected air movement without adventitious breath sounds.
*   Crackles: Historically known as rales. Discontinuous popping, clicking, or bubbling sounds, usually during inspiration, caused by air opening closed alveoli or passing through fluid. Fine crackles are high-pitched and associated with CHF or pulmonary fibrosis. Coarse crackles are lower-pitched wet bubbling sounds associated with severe pneumonia or pulmonary edema.
*   Wheezes: High-pitched, continuous, musical whistling or hissing sounds, usually expiratory but sometimes inspiratory, caused by narrowed lower airways such as asthma, anaphylaxis, or COPD.
*   Rhonchi: Low-pitched, continuous, sonorous snoring, moaning, or gurgling sounds from larger airways partially obstructed by thick mucus or fluid. They can sometimes temporarily clear with coughing.
*   Stridor: Loud, harsh, high-pitched crowing or whistling, usually inspiratory, indicating critical upper-airway narrowing or obstruction.
*   Pleural friction rub: Harsh, grating, or creaking sound from inflamed pleural membranes rubbing during inspiration and expiration; a hallmark of pleurisy.

### The History Maker

**Proposed stable ID:** `history_maker`  
**SCORM Lite node ID:** `med_history`  
**Shipped flow:** Two-round sequence under one stable game identity. Round 1 — OPQRST/SAMPLE Pair Match using `PairMatchGame` (`mode: "foundation"`). Round 2 — Interview Builder using `SentenceBuilderGame` (`mode: "interview_builder"`). Field Priorities experiment — InfoGapGame (`mode: "field_priorities"`, preserved in code for historical results but removed from production navigation — do not expand this deck).  
**V2 status:** Interview Builder is the CE-primary round.  
**Primary skill:** Construct clinically specific OPQRST/SAMPLE interview questions tailored to a pediatric patient's exact presentation.

**Round 1 implementation (shipped):** The screen displays six mixed cards at a time: three OPQRST/SAMPLE category cards and three patient-clue cards. The learner taps a category and its matching clue, similar to the AMS AEIOUTIPS PairMatch interaction. Correct pairs clear from the board and show a brief explanation; mismatches add `missed_<category>` and `false_positive_<category>` signals where possible. `history/game.json` is authored as 12 explicit 1:1 pairs, one for each OPQRST/SAMPLE component, so no round can contain duplicate categories with ambiguous matches.

**Round 1 instructional role and scope:** Pair matching is the scaffold: it refreshes the OPQRST/SAMPLE framework without turning the interaction into a passive category menu. It is still not the whole CE learning objective. The learner should flow directly into Round 2, where they must produce the patient-specific question.

**Retired experiment note:** A Field Priorities / Information Gap mode was previously implemented using authored vignettes and "highest-priority question" ranking. That interaction is retired as the forward CE design because priority ranking is too open to interpretation and opinion-dependent for deterministic scoring. Keep any existing stored `field_priorities` result records for analytics history, but do not use that mode as the production CE path or expand its content bank.

**Round 2 target interaction (Interview Builder — primary CE round):** 
The screen displays a brief patient presentation (e.g., "4yo male, barking cough, stridor") and a specific history target (e.g., "Construct a question to assess **P - Provocation / Palliation**"). 
Below the prompt is an empty sentence block and a bank of 5–8 phrase chunks (e.g., "Does his breathing get worse...", "Did the cough start...", "...when he lays flat or cries?", "...suddenly while eating?").

The learner taps the phrase chunks in order to build the question. 
*   **Why this works:** Handing experienced providers a fully formed question gives away the cognitive work (recognition). Forcing them to piece together the stem and the clinical context tests their ability to map an abstract mnemonic (Provocation) to a specific disease's pathophysiology (Croup + supine positioning/agitation).
*   **Distractor design:** Distractor chunks should represent either the wrong mnemonic letter (e.g., building an "Onset" question instead of a "Provocation" question) or the wrong differential diagnosis (e.g., building a foreign-body aspiration question for a croup presentation).
*   **Chunk granularity:** Phrase chunks should be clinically meaningful clauses, not 1–2 word grammar pieces. The target interaction is clinical synthesis under light pressure, not a syntax puzzle. Prefer chunks like "Does his breathing get worse..." and "...when he lays flat or cries?" over atomized words such as "does", "worse", "when", or "cries".
*   **Syntax parity:** Distractor chunks must be grammatically plausible completions of the sentence. Do not let capitalization, punctuation, verb tense, singular/plural agreement, or obviously mismatched syntax reveal the correct answer. The learner should reject a distractor because it asks the wrong clinical question, targets the wrong mnemonic component, uses the wrong information source, or fits the wrong differential — never because it is the only chunk that does or does not "sound right."
*   **Mobile correction affordance:** The assembled sentence block must support easy correction before Submit. Preferred pattern: tapping a selected chunk in the assembled sentence returns it to the chunk bank. A dedicated Undo/Backspace control is acceptable as a secondary affordance. Fat-finger errors should not become clinical penalties.
*   **Feedback:** If the student builds an incorrect question, feedback directly addresses the error: "You built a great question to check for Foreign Body Aspiration (Onset), but we need to know what makes this patient's Croup better or worse (Provocation)."

**Interaction deviation rationale:** Round 1 exercises mnemonic recognition with low-friction pair matching. Round 2 better matches the continuing-education goal by forcing learners to actively produce clinical phrasing rather than passively recognizing it.

**Variability & Generation (V2):** Cases are authored with a target sentence broken into 2–3 clinically meaningful chunks, alongside 3–4 distractor chunks. Each case should declare accepted chunk-ID sequences rather than one brittle text string. Accepted alternates may differ in clause order or wording when they preserve the target mnemonic component, clinical context, safety, and developmentally appropriate source. Do not accept grammatically valid sentences that ask the wrong clinical question.

**Authoring quality gate:** Every Interview Builder case must pass a syntax-trap review before release. All correct and distractor chunks should be grammatically usable in at least one plausible sentence path. If the correct answer can be identified by grammar, capitalization, or punctuation without reading the clinical presentation, the case must be revised.

**Scoring:** Deterministic evaluation of the assembled phrase sequence against authored accepted sequences and component flags. Award credit for correct mnemonic target, correct clinical context, safe/complete phrasing, and developmentally appropriate wording or information source. Do not require one brittle exact sentence when an authored alternate sequence is clinically equivalent.

Future Interview Builder mistake tags should include:
*   `wrong_mnemonic_focus` (built a question for the wrong letter)
*   `wrong_clinical_context` (built a question for the wrong differential)
*   `developmentally_mismatched_language` (used phrasing inappropriate for a pediatric caregiver)
*   `wrong_information_source` (asked the wrong person/source for the scenario context)

**Socratic feedback string (Interview Builder):** Feedback should guide the learner through the reasoning chain rather than simply naming the correct chunk. Each incorrect submission should:
1. Identify the question the learner actually built.
2. Ask what the target mnemonic component is supposed to clarify for this presentation.
3. Contrast the learner's wording with the intended clinical question.
4. Confirm the corrected phrasing and why it changes assessment, treatment, transport, or documentation.

**Two-step progression and earned reference card:** History Maker should behave like a short mastery sequence, not a menu of disconnected games.
1. **Step 1 — Foundation:** Learner completes the OPQRST/SAMPLE Pair Match round and demonstrates mnemonic recognition.
2. **Step 2 — Interview Builder:** Learner immediately flows into Interview Builder, where they use the same mnemonic framework to construct clinically specific questions.
3. **Earned reference card:** The learning/reference card is locked until the learner passes both steps in the same sequence or within an authored recent-completion window. After both steps are passed, show an "Earned Reference Card" reveal containing the OPQRST/SAMPLE interview framework, pediatric source/wording reminders, and 2–3 example high-quality questions. Do not show the full reference card before completion; use only lightweight hints during play.

**Completion threshold — Foundation (Round 1):** Any submitted PairMatch run with `score > 0` counts as completed.  
**Completion threshold — Field Priorities experiment (current code):** All vignettes in the deck are presented; any submitted run counts as completed. Current deck: 8 vignettes, no sampling — every session plays all 8, giving no replay variety. Do not expand this deck; replay variety and deck reduction belong in the Interview Builder content design.  
**Completion threshold — Interview Builder (V2):** All authored prompts in the session are submitted. Do not require every SAMPLE and OPQRST component in a single session; select prompts for clinical relevance, not checklist coverage. Target 7–9 authored cases with random selection of 5–6 per session for replay variety.  
**Main-app fit:** Remediation target for weak history-taking or documentation performance.

### Pediatric GCS Calculator

**Proposed stable ID:** `peds_gcs_calculator`  
**SCORM Lite node ID:** `tr_gcs`  
**Related main-map game:** PT3 GCS Matcher uses this game directly (`peds_gcs_calculator`).  
**Primary engine:** Calculation component  
**Primary skill:** Calculate GCS from eye, verbal, and motor findings using the correct pediatric or infant scale.

**Core interaction:** Learners receive a pediatric or infant neuro vignette, select the correct scale when needed, select or enter the E, V, and M component scores, and the total GCS calculates live as selections are made. The UI should show the component labels, accepted score ranges for the selected scale, and the running total before submission.

**Submit safety:** The Submit button must stay disabled until scale requirements are satisfied and all three E/V/M components are selected. Do not score an incomplete component set as an incorrect GCS; incomplete input is a UI state, not a clinical error.

**Scoring:** Deterministic scale-selection, component, and arithmetic scoring. Award component-level credit so a learner who correctly identifies eye and motor but misses verbal receives partial credit. Score the final total separately so the game can distinguish clinical component errors from math errors. Mistake tags should include `scale_selection`, `eye_component`, `verbal_component`, `motor_component`, and `total_math`.

**Feedback requirement:** Component feedback should use the Socratic feedback standard in §1. For near-misses, contrast the selected component against the correct component using the vignette cue. Example: if the learner selects motor 4 when the vignette describes reaching across midline to push the examiner away, feedback should ask whether that behavior is withdrawal or localization before confirming the correct score.

**Hints:** Hints should point to the observed behavior and scale-selection cue without naming the numeric score. Example: "The child reaches across midline toward the painful stimulus; decide whether that is withdrawal or localization." Do not reveal the component number.

**Soft time pressure:** Add an efficiency timer or progress indicator for CE mode. It may affect bonus or efficiency credit only; it must not hard-fail the calculator or block deliberate learners.

**Adaptive V2 direction:** After proficiency, remove explicit scale prompting. The learner must infer infant vs. pediatric scale from age and presentation before selecting E/V/M values.

**Media V2 direction:** GCS is ultimately visual and auditory, not just textual. After the text-vignette calculator is stable, add silent looping clips, short audio clips, or image sequences for selected E/V/M findings. Media prompts should show observable behavior without using scoring labels such as "withdraws" or "abnormal flexion" in the prompt. Text alternatives remain required for accessibility.

**Reference card:** Unlock a pediatric/infant GCS card after passing the calculator at least once. Card content: scale selection, component cues, common verbal/motor traps, and 2–3 vignette examples.

**Deck authoring:** Maintain enough vignettes to prevent case memorization. Target at least 8–10 authored vignettes with random sampling for routine CE sessions.

**Completion threshold:** Vignette answered and submitted (any score).  
**Design note:** This supersedes a pure `GCS Matcher` interaction when the learning objective is calculation. Descriptor matching can still appear inside the calculator as component selection, but the learner must ultimately produce E/V/M values and the total score.

### TEN-4 FACESp

**Proposed stable ID:** `ten4_facesp`  
**SCORM Lite node ID:** `tr_ten4`  
**Related main-map game:** PM6 TEN-4 FACES uses this game directly (`ten4_facesp`). There is one game, one stable ID; the map placement is a data configuration, not a fork.  
**Primary engine:** PAT swipe engine (binary labels)  
**Primary skill:** Identify bruising/injury red flags concerning for non-accidental trauma using TEN-4 FACESp.

**Core interaction:** The screen displays a picture of a bruising/injury pattern and a brief description. The learner swipes right for "Concerning (TEN-4 positive)" or left for "Common Accidental Injury".

**Scoring:** Deterministic swipe answer key. The game should reward objective recognition and documentation posture, not accusatory language.

**Completion threshold:** All cards seen and answered at least once.

**Safety note:** This game must be authored carefully and reviewed by a medical director before public deployment. It teaches red-flag screening, not diagnosis of abuse. Feedback should use language like "concerning for non-accidental trauma" and "requires objective documentation/reporting per policy," not "this is abuse" as a definitive finding.

**Deployment review gate:** Medical director review status must be tracked before public deployment. Until review is complete, the game may remain available only in development/internal QA contexts.

**Hints:** Hints should point to the objective TEN-4 FACESp criterion or injury-location reasoning without declaring the classification. Example: "Check the child's age and whether this bruise is on torso, ear, neck, frenulum, angle of jaw, cheeks, eyelids, subconjunctivae, or patterned."

**Adaptive V2 direction:** After proficiency, add a documentation-language follow-up: choose the phrase that objectively documents the finding and reporting concern without diagnosing abuse.

**Reference card:** Unlock a TEN-4 FACESp card after passing the recognition deck and documentation-language follow-up, once implemented. Card content: criteria, objective documentation examples, common accidental patterns, and reporting posture.

### AMS: AEIOUTIPS Differential Mapper

**Proposed stable ID:** `ams_aeioutips`  
**Primary engine:** Pair Matcher (New engine `PairMatchGame`)  
**Primary skill:** Rapidly associate specific AMS signs and symptoms to their primary AEIOUTIPS differential categories.

**Core interaction:** 
The game consists of 3 distinct rounds. In each round, 6 cards are randomly shuffled and displayed face-up on the screen: 3 AEIOUTIPS category cards (e.g., "O - Overdose") and 3 corresponding sign/symptom cards (e.g., "Pinpoint pupils"). 

The learner taps a card to select it, then taps a second card to attempt a match.
*   If the pair is a correct match, both cards briefly animate (e.g., turn green) and disappear from the screen.
*   If the pair is incorrect, both cards flash red with an "X" for 1 second, then unselect so the user can try again.
*   When all 3 pairs (6 cards) are cleared, the round ends. After a brief success message, the next round of 6 cards deals automatically. The game completes after Round 3.

**Data & Solvability Constraints:**
Because AMS symptoms heavily overlap (e.g., diaphoresis fits Hypoglycemia and Alcohol Withdrawal), the game data must be authored as explicit 1:1 pairs, or the engine must select 3 pairs whose correct categories do not overlap within the 6-card set. To keep the UI clear and eliminate ambiguity, there will only ever be **1 correct matching category** on the screen for each symptom card displayed in that specific round.

**Clinical reasoning guardrail:** Pair matching is a UI simplification, not a claim that AMS findings have only one possible cause. Each cleared pair should include a brief explanation such as, "Primary match for this drill; in the field, also consider hypoxia and toxidromes when supported by vitals or scene findings." This preserves the fast interaction while preventing over-anchoring on a single diagnosis.

**Scoring:**
- Completion requires clearing all 9 pairs, so raw pair completion is not the final score.
- Final score is efficiency-based: `round((correct_pairs / total_attempts) × 100)`, where `correct_pairs` is 9 when the run is completed.
- First-attempt clears may be displayed as a secondary performance stat, but should not replace the efficiency score.
- Incorrect attempts emit mistake tags based on the wrong category selected for a given finding and the correct category missed.

**Completion threshold:** All 3 rounds (9 pairs) cleared.

**Skill tags:** `ams_differential`, `aeioutips_recall`

**Mistake tags:**

| Tag | Meaning |
|:---|:---|
| `missed_A` | Failed to connect a finding to Alcohol or Acidosis when that was the authored primary match |
| `missed_E` | Failed to connect a finding to Epilepsy or Electrolytes when that was the authored primary match |
| `missed_I` | Failed to connect a finding to Insulin or Infection when that was the authored primary match |
| `missed_O` | Failed to connect a finding to Overdose or Oxygen/Hypoxia when that was the authored primary match |
| `missed_U` | Failed to connect a finding to Uremia when that was the authored primary match |
| `missed_T` | Failed to connect a finding to Trauma, Temperature, or Toxins when that was the authored primary match |
| `missed_P` | Failed to connect a finding to Psychiatric causes when that was the authored primary match |
| `missed_S` | Failed to connect a finding to Stroke, Shock, or Seizure/Postictal when that was the authored primary match |
| `false_positive_<letter>` | Selected a non-matching AEIOU-TIPS category for a finding; use the selected category's letter group, such as `false_positive_U` |
| `invalid_pair_selection` | Both tapped cards were the same type (cat+cat or finding+finding); no AEIOU letter is determinable from this error, but repeated occurrences indicate UI/reasoning confusion |

**Round-level clinical action nudge:** After each 3-pair round, show one short application prompt before the next deal, for example: "What do you check or treat first based on these matches?" Authored answers should connect recall to EMS action such as glucose check, oxygenation/ventilation, naloxone, stroke screen, trauma assessment, seizure precautions, temperature management, or sepsis recognition. Keep this as a lightweight teaching nudge, not a separate scored question in V1.

**Hints:** Hints should point to the discriminating finding class or immediate safety check without naming the matching AEIOUTIPS category. Example: "Is this finding most tied to oxygenation, glucose, toxidrome, seizure activity, trauma, or infection?"

**Adaptive V2 direction:** After proficiency, flip from pair matching to treatment-priority prompts. Present the finding or short AMS vignette and ask for the first EMS action: glucose check, oxygenation/ventilation, naloxone when indicated, stroke screen, trauma assessment, seizure precautions, temperature management, or sepsis recognition.

**Reference card:** Unlock an "AEIOU-TIPS Field Actions" card after passing the pair-match game and at least one action-priority round once V2 exists. Card content: differential categories, discriminating clues, first checks/treatments, and over-anchoring traps.

**Main-app fit:** Dog Park (available without map progression gating) and debrief next-action for any scenario with weak assessment performance and an AMS presentation.

**Implementation notes:**
- Requires a new `PairMatchGame` engine in `app.js`.
- The engine needs a simple 2-click state machine (`selection1` and `selection2`).
- Grid layout: 2 columns by 3 rows, or a scattered layout. Card positions should be completely randomized each round so categories and symptoms are mixed, requiring the user to scan the whole board.
- Feedback: Visual lock/shake with red "X" overlay for 1 second on mismatch. No "Submit" button required—action resolves immediately upon the second card tap.
- Result payload should submit `total = total_attempts`, `correct = correct_pairs`, and `score = round((correct_pairs / total_attempts) × 100)` through the shared mini-game result endpoint. This keeps XP, proficiency, and mistake-tag routing aligned with the efficiency score.

### Differential Detective: Resp-Dx

**Proposed stable ID:** `resp_dx_1q`  
**Primary engine:** `DifferentialDetectiveGame` (new branching case vignette engine)  
**Primary skill:** Differentiate between major pediatric respiratory emergencies — Asthma, Croup, Epiglottitis, Anaphylaxis, and Foreign Body Airway Obstruction (FBAO) — by selecting the highest-yield single assessment or history question.

**Core interaction loop:**

1. **Presentation:** A brief, intentionally ambiguous doorway impression or chief complaint is displayed. Example: "A 4-year-old male presents with sudden respiratory distress, coughing, and mild stridor."
2. **Investigation (ask 1 question):** A bank of 4–5 assessment or history options is displayed. The learner selects one before any diagnosis is offered. Examples: Auscultate Lungs, Check Temperature, Ask about Onset/Events, Assess Skin/Face.
3. **Finding reveal:** The selected investigation result is shown. Example (Onset/Events selected): "Caregiver states he was playing with his older brother's Lego set when he suddenly started choking and coughing."
4. **Diagnosis attempt:** The investigation bank is replaced by the 5 differentials. The learner selects a diagnosis.
5. **Feedback and loop:**
   - **Correct:** Socratic success message explaining why that finding confirmed the diagnosis and why the nearest competitors are ruled out.
   - **Incorrect:** Brief contrast feedback naming the mismatch (e.g., "You selected Croup, but croup does not begin with sudden choking while playing"). The investigation stage reloads with the previously revealed clue retained and greyed out, so the learner can add a second investigation before guessing again.

**Instructional design rationale:** Real-world EMS differential diagnosis is an exercise in information economy — experienced providers identify the one finding that resolves the differential fastest. Restricting the learner to a single initial investigation forces them to prioritize, then recover from a poor choice rather than simply being told the answer. Clue retention across attempts trains the same updating behavior as Protocol Pivot without requiring a scripted mid-case injection.

**Authoring rules:**

- Each case must be deterministically solvable from the initial presentation plus any single high-yield investigation. If the correct diagnosis cannot be confidently identified from those two data points, the case is underspecified and must be revised.
- Every investigation must produce a finding that is clinically real and accurate for the authored etiology.
- `is_high_yield: true` marks the investigation whose finding most narrowly identifies the correct diagnosis among the 5 differentials in that case. Exactly one investigation per case should carry this flag.
- Investigations marked `anchoring_trap` are specifically designed to surface a finding that plausibly supports a wrong diagnosis and should be accompanied by authored `anchoring_trap_target` (the wrong diagnosis a learner is most likely to anchor on after seeing this finding) and explicit contrast feedback.
- Do not write cases where the initial presentation alone is sufficient to diagnose without any investigation — the learner must always need to ask before they can confidently choose.
- Target 8–10 authored cases to prevent case memorization. Use random sampling of 4–5 cases per session.

**Example case structure:**

```json
{
  "id": "resp_dx_anaphylaxis_01",
  "presentation": "7-year-old female, difficulty breathing, audible expiratory wheezing, anxious.",
  "correct_diagnosis": "anaphylaxis",
  "differentials": ["asthma", "croup", "epiglottitis", "anaphylaxis", "fbao"],
  "investigations": [
    {
      "id": "inv_skin",
      "label": "Assess Skin & Face",
      "finding": "Flushed face, urticaria on chest and neck, swollen lower lip.",
      "is_high_yield": true
    },
    {
      "id": "inv_lungs",
      "label": "Auscultate Lungs",
      "finding": "Bilateral expiratory wheezing, diminished at the bases.",
      "is_high_yield": false,
      "anchoring_trap": true,
      "anchoring_trap_target": "asthma"
    },
    {
      "id": "inv_pmh",
      "label": "Past Medical History",
      "finding": "No history of asthma. Patient is normally healthy.",
      "is_high_yield": false
    }
  ],
  "feedback": {
    "correct_high_yield": "Urticaria and angioedema with lower-airway bronchospasm is anaphylaxis until proven otherwise. Epinephrine is the priority — not bronchodilator alone.",
    "correct_other": "You got the right diagnosis, but the investigation you chose requires ruling out more possibilities. Try to identify the single finding that separates anaphylaxis from asthma at first glance.",
    "incorrect_after_trap": "You heard wheezing and anchored on Asthma. Wheezing only tells you there is bronchospasm — it does not tell you the cause. Check another system.",
    "incorrect_generic": "That diagnosis does not fit the full clinical picture. Gather another finding."
  }
}
```

**Scoring:** Per-case score based on number of investigations needed: high-yield investigation + correct diagnosis = 3 pts; 2 investigations + correct = 2 pts; 3+ investigations + correct = 1 pt; incorrect final diagnosis = 0 pts. Normalize to 0–100: `score = round((earned_points / max_points) × 100)` where `max_points = 3 × cases_played`. Submit through shared result contract with `total = cases_played` and `correct = cases_answered_correctly`.

**Completion threshold:** Any submitted run counts as completed (design spec default).

**Mistake tags:**

| Tag | Meaning |
|:---|:---|
| `poor_investigation_choice` | Learner selected a low-yield investigation whose finding cannot differentiate the correct diagnosis from its nearest competitors in this case |
| `etiology_misidentification` | Learner selected a high-yield investigation and received a discriminating finding, but still chose the wrong diagnosis |
| `impression_anchoring` | Learner selected an investigation marked `anchoring_trap: true`, then chose the `anchoring_trap_target` diagnosis (same tag used by `protocol_pivot` for the same cognitive failure) |

**Scoring authority note:** `is_high_yield` and `anchoring_trap` flags are authored in the case data. The backend evaluates these during result processing to determine per-case points. The frontend never calculates or asserts the point value — it sends the raw investigation ID chosen and the diagnosis selected.

**Hints:** Hints should identify the category of clinical system most likely to differentiate the differentials in this case without naming the finding or the diagnosis. Example: "Think about what differs between upper- and lower-airway involvement, or between local and systemic allergic responses."

**Adaptive V2 direction:** After proficiency, introduce dual-pathology presentations where two competing differentials are both partially supported by the presentation and neither can be ruled out from a single investigation — the learner must select two complementary investigations before diagnosing. Alternatively, introduce adult-population respiratory differentials (pulmonary embolism, COPD exacerbation, CHF) using the same engine.

**Reference card:** Unlock a "Respiratory Differential — Discriminating Clues" card after passing the game at least once. Card content: high-yield differentiators for each of the 5 differentials, common anchoring traps, and first-priority EMS action for each confirmed diagnosis.

**Map placement:** PM5 node. Replaces `diff_dash_resp` as the primary CE respiratory differential game at PM5. `diff_dash_resp` remains available in the Dog Park for learners who benefit from the simpler pair-match warm-up, but `resp_dx_1q` is the CE-primary PM5 interaction.

**Main-app fit:** PM5, Dog Park (assessment category), and debrief next-action for any scenario with weak respiratory assessment or differential-diagnosis performance.

### AHA BLS CPR Mastery Flow

**Proposed stable IDs:** `cpr_bls_sequence` (Round 1) → `cpr_bls_concepts` (Round 2) → `drill_peds_cpr_mannequin` (Round 3)  
**Primary engines:** `SequenceOrderGame` → `PairMatchGame` → CPR Challenge HUD (via Scenario Wrapper)  
**Primary skill:** AHA BLS CPR algorithm sequence, critical metrics (ratios/depths), and high-performance code execution.

**Core interaction loop & Mastery Flow:**
The learner experiences this as a single 3-round gauntlet. Passing one round immediately unlocks and routes to the next.

1.  **Round 1: Chain of Survival (Order of Operations)**
    *   **Engine:** `SequenceOrderGame`
    *   **Interaction:** The learner is presented with 6–7 mixed steps of the AHA BLS Pediatric/Adult algorithm. They must drag or assign numbers to place them in the exact correct order. Full sequence commit before reveal. Partial credit for steps in the correct position.
2.  **Round 2: Key Concepts (The Numbers)**
    *   **Engine:** `PairMatchGame`
    *   **Interaction:** 3 rapid-fire boards of 6 cards (3 pairs each). The learner must pair the patient/rescuer context with the correct AHA metric (e.g., *Adult Compression Ratio* ↔ *30:2*).
3.  **Round 3: Practical Application (Mannequin Drill)**
    *   **Engine:** CPR Challenge HUD (via Scenario Wrapper)
    *   **Interaction:** The "Next Round" button from Round 2 launches a lightweight, text-light scenario (e.g., `drill_peds_cpr_mannequin`). The dispatch sets the scene in the Station Training Room. The learner physically executes the knowledge they just reviewed using the CPR Challenge HUD.

**Reward:** Passing the final HUD drill triggers the `newly_unlocked_reference_cards` system to award the **"AHA CPR & Resuscitation Guide"**.

**Implementation strategy:** 
Because the CPR HUD relies deeply on the `SimSession` backend timeline validation, Round 3 is built as a standard scenario. On the Round 2 "Results" screen, the Next Action button is configured to call `startScenario("drill_peds_cpr_mannequin")`, fulfilling the 3-round design seamlessly without a massive architectural rewrite.

---

## 5. Effectiveness Review and Improvement Priorities

The current catalog is effective overall for continuing education because most games ask learners to act before receiving explanation. That matches the intended use: short reps that refresh and sharpen previously learned concepts before scenario application.

**Preserve as designed:**
*   `pat_dash` and `ten4_facesp` are strong rapid-pattern-recognition games. Time pressure and binary decisions fit the real-world cognitive demand of doorway impressions and injury red-flag screening.
*   `ams_aeioutips` is a strong experimentation-with-feedback design when implemented as PairMatch: learners rapidly test sign/category associations, receive immediate correction, and see clinical-action nudges that prevent the exercise from becoming alphabet recall.
*   `peds_gcs_calculator` is strong because it uses clinical vignettes, component-level decisions, and arithmetic instead of asking learners to memorize isolated descriptors.
*   `lung_sounds_matcher` is strong if it uses real audio and follows identification with reasoning-rich feedback.

**Improve before expanding similar games:**
*   Adult vs. Child A&P cards should prioritize care implications over abstract facts. A CE learner gains more from deciding how a larger occiput changes airway positioning than from sorting "larger occiput" into a pediatric bucket. The 70% implication-card gate (§4) must be met before the CE deck ships.
*   Adult vs. Child A&P must protect the mobile tri-swipe interaction with visible tap buttons and touch-safe card handling; the interaction should not depend on an upward swipe working perfectly on every browser.
*   History Maker V2 Interview Builder should be treated as urgent, not deferred. For CE learners, V1 is the weakest game in the catalog against engagement and transfer criteria — it reveals the answer structure (OPQRST/SAMPLE grid) before the question is asked. Do not expand the V1 card bank until Interview Builder is on the implementation roadmap.
*   Developmental learning should use the Developmental Red Flags game (`dev_flags`, §6) as the CE-primary mode. The existing Toy Box remains the scaffold/initial-education form. These are separate stable mini-game IDs with separate progression tracking.
*   Lung sounds should ship V2 implication follow-up prompts alongside V1, not as a future retrofit. For CE learners who can already identify sounds, the identification step alone provides low transfer value.
*   Lung Sounds should use a mastery flow: audio identification → clinical implication follow-up → earned "Breath Sounds & Field Actions" reference card. Do not expose the full breath-sounds reference card before the learner has passed both steps at least once.
*   Lung sounds should remain tap-first on mobile; drag-and-drop would add pointer friction without improving the clinical learning objective.
*   Differential Dash — AMS and Differential Dash — Difficulty Breathing should not ship as CE-primary drag/sort bucket games. Use `PairMatchGame` or a short case-vignette interaction where the learner connects findings to likely etiologies and then receives or answers a clinical-action implication prompt.
*   Stop the Bleed should train escalation and wound-location reasoning, not category sorting. Prefer scored-order or case escalation: direct pressure, wound packing/hemostatic dressing, tourniquet, junctional-wound constraints, reassessment, and transport priority.
*   Temp Check should train treatment priority and risk recognition, not hypothermia/hyperthermia definition sorting. Prefer case vignettes asking for passive vs. active rewarming/cooling, sepsis screening, environmental exposure management, altered mental status significance, and transport priority.
*   Rule of Nines is acceptable as a body-map calculation game, but should add a follow-up implication prompt for CE use: burn severity, airway risk, special-area concern, fluid/transport threshold, or pediatric transfer priority.
*   MOI Mapper should ask for injury suspicion and care implications from a mechanism, not just the mechanism category. Cards should connect mechanism to hidden injury, SMR consideration, hemorrhage risk, or transport concern.
*   BLS Sequence should reveal the correct order after the learner submits their full sequence, not per-step. Reveal on submit preserves the value of committing to a complete mental model before seeing the answer.
*   For games where field decision speed is a clinical skill — GCS assessment, medical shock recognition, trauma shock recognition, PAT impression — add soft time pressure with score implications. A visible progress indicator without a hard cutoff matches field cognitive demand without punishing deliberate learners.
*   Add scenario bridge prompts on game results screens. Name the scenario type where the primed skill applies and offer a direct launch. The mini-game → scenario → debrief → next-mini-game loop is the platform's core engagement and retention mechanism; make it visible.

**New game directions:**
*   **Vitals Trend Spotter** (`vitals_trend_spotter`): Present a 2–3 minute timeline of HR, SpO2, RR, and BP values. Learner identifies the earliest sign of deterioration, selects the most likely etiology from authored options, and names the most appropriate immediate response. This is the closest equivalent to a data-simulator learning pattern and directly serves CE providers who need to read trends under time pressure. CE-primary; no equivalent exists in the current catalog.
*   **Protocol Pivot** (`protocol_pivot`): Present an initial vignette and ask for impression and priority action. Then introduce a new finding (new vital, bystander report, or clinical sign) and ask whether the initial impression holds or must change, and what changes. Trains cognitive flexibility — updating a mental model mid-call — which is a critical CE skill not exercised by any current game. Designed as a case vignette with authored mid-case update, not a MCQ.
*   **DMIST Builder** (`dmist_builder`): Given a patient encounter summary, select and sequence the most clinically important DMIST handoff elements. Bridges mini-game practice to scenario documentation and handoff skills. Scored on element selection, sequence, and omission of irrelevant detail.

**Remaining implementation priorities:**
*   High: enforce GCS incomplete-input protection so learners cannot submit until all required E/V/M components are selected.
*   High: create the static mini-game metadata registry so hints, reference-card gates, mastery flows, and Priority 5 routing have one authoritative source.
*   Medium: specify BLS Sequence post-sequence feedback model before implementation begins.
*   Medium: add soft time pressure (score-implication timer) to `peds_gcs_calculator`, `shock_spotter_med`, and `shock_spotter_trauma`.
*   Medium: update planned pediatric-map games away from CE-primary bucket sorting: `diff_dash_ams`, `diff_dash_resp`, `stop_the_bleed`, and `temp_check`.
*   Medium: add per-card/per-case hint data and `hint_count` submission across all actively shipped games.
*   Medium: implement earned reference-card gates and mastery-flow unlocks for History Maker, Developmental, Lung Sounds, GCS, AEIOU-TIPS, DMIST, and Protocol Pivot.
*   Medium: implement Priority 5 debrief routing from declared `rubric_category_mapping`; keep recent mistake-tag routing as lower-priority remediation.
*   Medium: resolve Lung Sounds stridor audio licensing or production filtering before public launch.
*   Medium: design Vitals Trend Spotter as a new Dog Park / PM3 CE game after the rendering spike.
*   Low: wire mistake tags into spaced-retrieval and Random Calls weighting once that recommendation engine is designed.

**Completed priority items now tracked in the checklist:** Socratic feedback for GCS, Adult vs. Child A&P implication cards, Lung Sounds V2 prompts for licensed cards, PairMatchGame for AEIOUTIPS, scenario bridge prompts, Protocol Pivot, DMIST Builder, Developmental Red Flags, History Maker Interview Builder, retired Field Priorities navigation removal, Phase 5 mistake-tag routing, and the proficiency/recommended endpoints.

---

## 6. Planned Pediatric Map Games

The broader pediatric map identifies additional mini-games. Their placement remains governed by `PEDIATRIC_MAP_DESIGN.md`; this section records stable IDs, engines, and gateway wiring so they can be implemented consistently.

| Game | Stable ID | Map | Engine | Gateway wiring | Notes |
|---|---|---|---|---|---|
| Sound Check | `sound_check` | PM2 | Audio matching component + implication follow-up | None — map unlock gate | Same audio-only identification model as `lung_sounds_matcher`; separate authored content. Ship with V2 implication follow-ups alongside audio clips. Part of the breath-sounds mastery flow; unlock the reference card only after audio ID and implication steps are both passed. |
| Shock Spotter | `shock_spotter_med` | PM3 | PAT swipe with configurable labels | None | Compensated vs. decompensated shock recognition. Add soft time pressure (score-implication timer) to match doorway-impression cognitive demand. |
| Differential Dash — AMS | `diff_dash_ams` | PM4 | PairMatchGame or case vignette | None | CE-primary version should connect AMS findings to likely etiologies under light pressure, then show or ask a clinical-action implication prompt. Drag/sort is acceptable only as scaffold/remediation, not the main CE interaction. |
| Differential Detective — Resp-Dx | `resp_dx_1q` | PM5 | `DifferentialDetectiveGame` (new) | None | CE-primary respiratory differential game at PM5. Replaces `diff_dash_resp` as the PM5 interaction. Branching case vignette: learner asks one investigation, receives a finding, and must diagnose from the 5 core differentials. Scored on information economy (investigations needed per correct diagnosis). |
| Differential Dash — Difficulty Breathing | `diff_dash_resp` | Dog Park | PairMatchGame | None | Demoted from PM5 CE-primary to Dog Park warm-up after `resp_dx_1q` was adopted as the PM5 CE interaction. Still useful as a pair-match scaffold for learners who need simpler pattern recognition before tackling the branching differential. |
| TEN-4 FACES | `ten4_facesp` | PM6 | PAT swipe (binary) | None | Same game as §4 TEN-4 FACESp; data-configured for PM6 placement. |
| Rule of Nines | `rule_of_nines` | PT1 | Body-map tap component + implication follow-up | Writes `PedsMapProgress("pt1")` after a passing mini-game result; auto-complete-on-visit has been removed. | Pediatric BSA estimation plus one deterministic follow-up on severity, airway/special-area concern, fluid/transport threshold, or burn-center priority. Reference card unlocks after a passing run. |
| Stop the Bleed | `stop_the_bleed` | PT2 | Scored-order or case escalation | None | Hemorrhage-control escalation for a specific wound type: direct pressure, wound packing/hemostatic dressing, tourniquet when appropriate, reassessment, and transport priority. Do not ship as CE-primary bucket sorting. |
| GCS Matcher | `peds_gcs_calculator` | PT3 | Calculation component | None | Same game as §4 Pediatric GCS Calculator; descriptor matching embedded in calculation flow. |
| MOI Mapper | `moi_mapper` | PT4 | PAT swipe with configurable labels | None | Mechanism to injury suspicion and care implications. Cards should connect mechanism to hidden injury, SMR consideration, hemorrhage risk, transport concern, or body-region assessment priority. |
| Shock Spotter — Trauma | `shock_spotter_trauma` | PT5 | PAT swipe with configurable labels | None | Shock recognition in trauma context. Add soft time pressure (score-implication timer) to match the time-critical nature of trauma shock recognition. |
| BLS Sequence | `bls_sequence` | PT6 | Scored-order sort | None | Correct-order BLS algorithm puzzle. **Feedback model: post-sequence reveal.** The learner submits their full sequence before the correct order is shown. Do not use per-step confirmation. |
| Temp Check | `temp_check` | PT7 | Case vignette or implication swipe | None | Temperature-emergency treatment priority and risk recognition: passive vs. active rewarming/cooling, sepsis screening, environmental exposure management, altered mental status significance, and transport priority. Drag/sort is acceptable only as scaffold/remediation, not the main CE interaction. |
| Priority Stack | `priority_stack` | PE2 | Ranked-list sort | None | Final synthesis after advanced emergency scenario. |
| Vitals Trend Spotter | `vitals_trend_spotter` | Dog Park / PM3 | Temporal data component | None | Present a 2–3 min vitals timeline (HR, SpO2, RR, BP). Learner identifies the earliest deterioration sign, selects the most likely etiology, and names the immediate response. CE-primary; no equivalent exists in the current catalog. Fills the "data simulator" pattern gap. |
| Protocol Pivot | `protocol_pivot` | Dog Park | Case vignette with mid-case update | None | Initial impression → new finding arrives (new vital, bystander report, or clinical sign) → learner confirms or updates assessment and priority action. Trains mid-call cognitive flexibility. CE-primary. Uses case vignette component with authored mid-case branch. |
| DMIST Builder | `dmist_builder` | Dog Park / PM5 | Ranked-select component | None | Given a patient encounter summary, select and sequence the most important DMIST handoff elements. Scored on element selection, sequence, and omission of irrelevant detail. Bridges mini-game practice to scenario handoff skills. |
| Developmental Red Flags | `dev_flags` | PM1 | PAT swipe with three-way labels | None | Age plus behavior → Expected / Concerning-regression / Needs further assessment. CE-primary variant of the developmental domain. Separate stable ID from `dev_sort` for independent progression tracking. Feedback explains the clinical significance of delay, regression, or mismatch. |

### Gateway Wiring Pattern

When a map is a gateway node (PM1, PT1), completing its mini-game must write a `PedsMapProgress` record to unlock the child maps. The wiring is:

1.  Mini-game submits result to `POST /api/me/minigames/result` (or the game-specific endpoint during migration).
2.  Backend writes `PedsMapProgress(map_id)` on the first `completed: true` submission for that user.
3.  Frontend calls `_loadProgressFromServer()` after result submission to refresh `pedsMapCompleted`.
4.  `_computeMapUnlockState` detects the new `PedsMapProgress` entry and unlocks the child maps.

PM1 (`dev_sort`) already implements this. PT1 (`rule_of_nines`) now uses the functional Rule of Nines mini-game as the gateway; the former auto-complete-on-visit placeholder has been removed.

---

## 7. Engine Requirements

Engine extensions must be data-driven and must not change the defaults of any currently shipped game. Any extension to the PAT swipe engine must not change PAT Doorway Dash behavior. Any extension to the drag/sort engine must preserve Dev Sort buckets, card data, and reward behavior.

All new or substantially revised engines should support the shared design standards in §1:
*   A hint affordance that can show authored non-answer hints.
*   Socratic feedback fields or templates.
*   Result metadata for `hint_count` when hints are used.
*   Reference-card unlock hooks when a game or mastery sequence has an associated learning card.
*   Optional "continue to next step" routing for multi-step mastery flows.

### PAT Swipe Engine

Existing PAT Doorway Dash behavior remains unchanged.

Allowed extensions:
*   Data-configurable decision labels (enables Shock Spotter, MOI Mapper, and TEN-4 FACESp variants).
*   Optional audio card mode.
*   Three-choice tap mode for Adult vs. Child A&P (up = Both/Shared, left = Adult, right = Child).

### Drag/Sort Engine

Existing Dev Sort behavior remains unchanged.

Allowed extensions:
*   Reusable bucket/card configs for scaffold or remediation variants where the learning objective is basic category recognition.
*   Do not use drag/sort as the CE-primary interaction for Differential Dash, Stop the Bleed, or Temp Check unless the authored task requires genuine prioritization, escalation, or sequence reasoning rather than sorting signs into buckets.
*   Scored-order mode for BLS Sequence.
*   Ranked-list mode for Priority Stack.

### PairMatchGame — Two-Card Match Mode

Used by `ams_aeioutips`. Independent engine; do not extend TapChoiceGame because the interaction resolves immediately on the second card tap and has no Submit button.

Required behavior:
*   Each round deals matched category/finding pairs into a mixed card grid.
*   Learner taps one card, then taps a second card to attempt a match.
*   Correct pairs animate green and leave the board.
*   Incorrect pairs flash red briefly, emit mistake tags, then unselect so the learner can try again.
*   Incorrect pairs impose brief anti-guessing friction, such as a 1–2 second lockout/shake animation or efficiency penalty. The goal is not punishment; it is to make reading the clinical cue more efficient than rapid-tapping guesses.
*   Round completes when all pairs are cleared.
*   Scoring is efficiency-based: `correct_pairs / total_attempts × 100`.
*   After each round, show a brief unscored clinical-action nudge connecting the matched findings to EMS assessment or treatment priorities.
*   Mobile layout must keep the active 6-card grid usable without forced scrolling on small phones. Use responsive sizing, container queries where practical, compact copy, and a fixed maximum header/stats footprint. If the grid cannot fit in `100dvh`, reduce padding/text scale before allowing scroll.

### Case Vignette Component

Useful for History Maker variants and future protocol judgment drills. TEN-4 FACESp and TEN-4 FACES (PM6) use brief vignette cards as content, but their primary interaction remains swipe classification.

Minimum capabilities:
*   Authored vignette text.
*   Optional image/body-map cue.
*   One or more deterministic questions.
*   Per-choice feedback.
*   Mistake tags for analytics.
*   Optional sentence-construction prompt mode for Interview Builder variants.
*   Feedback fields that can explain why the assembled question does or does not match the requested mnemonic component, clinical context, and age-appropriate information source.

### Body-Map Tap Component

Needed for Rule of Nines and potentially trauma assessment drills.

Minimum capabilities:
*   Click/tap regions with accessible labels.
*   Region accumulator and clear/reset controls.
*   Deterministic expected-region and percentage scoring.
*   Mobile-safe target sizes.

### Audio Matching Component

Used for Lung Sounds Matcher and Sound Check.

Minimum capabilities:
*   Play/pause/replay controls.
*   Fixed ordered answer buttons for Clear, Crackles, Wheezes, Rhonchi, Stridor, and Pleural Friction Rub.
*   Transcript/fallback text for accessibility.
*   Authored answer key.
*   Per-audio-asset `license_source` field in game data (e.g. `"license_source": "Freesound CC0 #12345"`). Any audio asset without a populated `license_source` is treated as unlicensed and must not ship in production builds. This field is the enforcement gate for audio licensing; do not ship a build where any audio clip in an active game has a null or placeholder `license_source`.
*   Graceful licensed-deck fallback: production builds may filter out unlicensed audio cards. The engine must complete normally with the remaining licensed cards, even when the active deck is smaller than the authored maximum. Do not fail a round because the licensed deck is below the ideal deck size; surface a diagnostics warning for authors instead.

### Temporal Data Component

Needed for Vitals Trend Spotter. Reusable for any game that presents a time-series clinical data set and asks learners to identify patterns, trends, or decision points.

Minimum capabilities:
*   Authored time-series data with labeled axes (time, vital parameter).
*   Configurable vital channels: HR, SpO2, RR, BP, EtCO2, GCS, or others.
*   Learner tap/click to mark a point on the timeline as the identified event (earliest deterioration, clinical decision moment).
*   Fixed multiple-choice follow-up prompts: etiology and immediate response, authored per scenario.
*   Deterministic scoring: marking the correct time window (±authored tolerance), selecting the correct etiology, selecting the correct response.
*   Mistake tags distinguishing early-vs-late identification, etiology misidentification, and incorrect response selection.
*   Timeline playback mode: optionally reveal the data incrementally rather than all at once, to simulate real-time monitoring decision pressure.

### Calculation Component

Needed for Pediatric GCS Calculator and reusable for future dose, drip, or burn-percentage arithmetic drills.

Minimum capabilities:
*   Scenario/vignette prompt with the data needed to calculate the answer.
*   Scale selection when more than one clinical scale applies, such as pediatric vs. infant GCS.
*   Component inputs with validation ranges.
*   Final answer input submitted separately from component inputs.
*   Deterministic answer key for both component correctness and arithmetic correctness.
*   Feedback that distinguishes "selected the wrong component score" from "added correctly selected components incorrectly."

---

## 8. Analytics and Rewards

Mini-games can contribute to:
*   **Map progression** — Gateway maps (PM1, PT1) require mini-game completion to write a `PedsMapProgress` record. This record is checked by `_computeMapUnlockState` server-side and returned in `GET /api/me/progress` as `pedsMapCompleted`. See §6 Gateway Wiring Pattern.
*   **Toy availability** — Peds toys carry a `map_gate_id` column. `GET /api/toys/shop` filters toys by `map_gate_id` against the user's `PedsMapProgress` records. A toy only appears in the shop after the player has completed the map that gates it. Mini-game completion on a gateway map is therefore also the trigger that makes the track's first toy purchasable.
*   **Treat earning** — Subject to economy caps defined in `REWARDS.md`.
*   **Debrief next-action routing** — Priority 5 routing uses declared `rubric_category_mapping` from §8 Game Metadata Matrix. A mini-game may be recommended for a failed scenario category only when the mapping explicitly includes that category. Recent mini-game mistake-tag gaps remain useful as a lower-priority signal and should not replace rubric-category routing.
*   **Future spaced retrieval** — Mistake tags are the preferred input for any future SM-2-style spaced-repetition or Random Calls weighting engine. For example, repeated `scale_selection` misses should increase exposure to GCS/TBI/auto-pedestrian practice, while repeated `rhonchi_vs_crackles` misses should increase lung-sound and respiratory assessment practice.
*   **Instructor analytics** — By skill tag and mistake tag.

### Skill Tags

Mini-games should declare one or more `skill_tags`:

*   `pat_impression`
*   `developmental_stage`
*   `developmental_red_flags`
*   `pediatric_anatomy`
*   `lung_sound_identification`
*   `history_taking`
*   `gcs_calculation`
*   `non_accidental_trauma_screening`
*   `shock_recognition`
*   `bsa_estimation`
*   `hemorrhage_control`
*   `moi_recognition`
*   `bls_sequence`
*   `temperature_regulation`
*   `ams_differential`
*   `aeioutips_recall`
*   `differential_ams`
*   `differential_respiratory`
*   `vitals_trend_reading`
*   `clinical_impression_update`
*   `handoff_communication`

### Game Metadata Matrix

This matrix is the authoritative checklist for applying the §1 principles across the catalog. Detailed card/case hints still live in game data, but every game must declare the hint lens, reference-card gate, mastery/adaptive direction, and rubric mapping here before new CE content ships. Unless a game-specific metadata record overrides it, the default pass threshold for every matrix entry is `score >= 80`.

| Game | Hint lens | Reference card unlock | Mastery/adaptive direction | `rubric_category_mapping` |
|---|---|---|---|---|
| `pat_dash` | Point to appearance, work of breathing, or circulation cue; do not say sick/not sick. | PAT doorway impression card after first pass. | After 3+ runs ≥80%, add implication follow-up: highest-priority first action for the PAT pattern. | `clinical_performance` |
| `dev_sort` | Point to age range/developmental domain; do not name the bucket. | Shared developmental card only after `dev_sort` + `dev_flags`. | Scaffold only; CE routing should prefer `dev_flags`. | `clinical_performance`, `professionalism` |
| `dev_flags` | Point to expected vs. regression vs. further-assessment cue; do not name classification. | Shared developmental card after `dev_sort` + `dev_flags`. | CE-primary developmental game; feedback must include documentation/communication implication. | `clinical_performance`, `professionalism` |
| `adult_child_ap_swipe` | Point to physiologic/assessment consequence; do not name adult/child/both. | Adult vs. pediatric assessment differences card after CE implication deck pass. | After proficiency, use clinical-consequence questions instead of classification swipe. | `clinical_performance`, `protocols_treatment` |
| `lung_sounds_matcher` / `sound_check` | Point to sound quality, airway level, or treatment branch; do not name sound or intervention. | Breath Sounds & Field Actions card after audio ID + intervention round. | Lung Sounds uses two distinct rounds: identify sound, then choose scope-filtered intervention with partial/full credit. | `clinical_performance`, `protocols_treatment` |
| `history_maker` | Point to OPQRST/SAMPLE target and patient cue; do not reveal chunk sequence. | OPQRST/SAMPLE card after Foundation + Interview Builder. | Foundation → Interview Builder → reference card. Hide Field Priorities from production navigation. | `clinical_performance`, `narrative` |
| `peds_gcs_calculator` | Point to observed E/V/M behavior or scale cue; do not reveal number. | Pediatric/infant GCS card after calculator pass. | After proficiency, infer scale from age/presentation without explicit prompt. | `clinical_performance`, `narrative` |
| `ten4_facesp` | Point to objective age/location/pattern criterion; do not name classification. | TEN-4 FACESp card after recognition + documentation-language follow-up. | Add documentation-language follow-up after recognition. Medical director review required before public deployment. | `clinical_performance`, `professionalism`, `narrative` |
| `ams_aeioutips` | Point to finding class or first safety check; do not name category. | AEIOU-TIPS Field Actions card after PairMatch + action-priority V2. | After proficiency, ask first treatment/assessment priority from finding/vignette. | `clinical_performance`, `protocols_treatment` |
| `dmist_builder` | Point to receiving-team need or DMIST section; do not identify include/skip. | DMIST handoff card after selection pass; sequence examples added after V2. | Expand to 8+ cases; add sequence scoring and soft time pressure. | `dmist`, `narrative` |
| `protocol_pivot` | Point to the new finding type; do not reveal updated impression. | Cognitive pivot/anchoring traps card after pass. | Always allow Act 2 after wrong Act 1; score wrong→correct as meaningful recovery. Expand to 8–10 cases. | `clinical_performance`, `protocols_treatment` |
| `rule_of_nines` | Point to region boundary or special-area implication; do not name percentage. | Pediatric burns card after BSA estimate + implication follow-up. | Add CE implication prompt: airway, special area, fluid/transport, burn center. | `clinical_performance`, `protocols_treatment`, `narrative` |
| `stop_the_bleed` | Point to wound type/location and whether current intervention is failing; do not name next step. | Hemorrhage-control escalation card after sequence/case pass. | CE-primary escalation/case sequence; not bucket sorting. | `protocols_treatment`, `clinical_performance` |
| `moi_mapper` | Point to energy transfer/body region; do not reveal injury concern. | MOI-to-hidden-injury card after implication deck pass. | Mechanism → injury suspicion/SMR/transport implication. | `clinical_performance`, `protocols_treatment` |
| `shock_spotter_med` / `shock_spotter_trauma` | Point to perfusion trend or compensation/decompensation cue; do not name shock state. | Shock recognition card after pass. | Soft time pressure; after proficiency ask first management priority. | `clinical_performance`, `protocols_treatment` |
| `bls_sequence` | Point to algorithm phase; do not reveal order. | BLS sequence card after full-sequence pass. | Full sequence submitted before reveal; no per-step confirmation. | `protocols_treatment`, `clinical_performance` |
| `temp_check` | Point to exposure, mental status, skin/temp trend, or sepsis risk; do not reveal treatment priority. | Temperature-emergency care card after vignette pass. | CE-primary treatment-priority vignette; not hot/cold bucket sorting. | `clinical_performance`, `protocols_treatment` |
| `vitals_trend_spotter` | Point to trend direction and earliest abnormality; do not identify event time. | Vitals trend interpretation card after pass. | Increase complexity with more channels and delayed reveals. | `clinical_performance`, `protocols_treatment` |
| `resp_dx_1q` | Point to the highest-yield differentiator or systemic signs; do not name the diagnosis. | Respiratory Differential Reference card after pass. | Increase ambiguity or introduce dual-diagnosis cases. | `clinical_performance`, `protocols_treatment` |
| `priority_stack` | Point to competing priorities; do not reveal rank. | Final synthesis card after pass. | Ranked-list final synthesis; scenario bridge required. | `clinical_performance`, `protocols_treatment`, `professionalism` |
| `cpr_bls_sequence` | Point to safety or dependency rules; do not reveal exact position. | AHA CPR & Resuscitation Guide after full flow completion. | Round 1 of CPR Mastery flow. | `protocols_treatment` |
| `cpr_bls_concepts` | Point to physiologic rationale; do not name the exact metric. | AHA CPR & Resuscitation Guide after full flow completion. | Round 2 of CPR Mastery flow. | `protocols_treatment` |

### Mistake Tag Catalog

Mistake tags from all games are collected here for analytics cross-reference. Each tag should appear in both this list and the relevant game's design section.

| Tag | Game(s) |
|---|---|
| `upper_vs_lower_airway` | pat_dash, lung_sounds_matcher, sound_check |
| `wheeze_vs_stridor` | lung_sounds_matcher, sound_check |
| `rhonchi_vs_crackles` | lung_sounds_matcher, sound_check |
| `pleural_rub_vs_crackles` | lung_sounds_matcher, sound_check |
| `normal_vs_abnormal` | lung_sounds_matcher, sound_check |
| `wrong_mnemonic_focus` | history_maker — Interview Builder (`SentenceBuilderGame`, `mode: "interview_builder"`) |
| `wrong_clinical_context` | history_maker — Interview Builder (`SentenceBuilderGame`, `mode: "interview_builder"`) |
| `wrong_information_source` | history_maker — reserved for future Interview Builder cases involving source selection; not currently emitted by the initial Phase 3 deck |
| `developmentally_mismatched_language` | history_maker — Interview Builder (`SentenceBuilderGame`, `mode: "interview_builder"`) |
| `missed_time_critical` | history_maker — Field Priorities experiment (`InfoGapGame`, `mode: "field_priorities"`); generated by current shipped code; may appear in recent records |
| `missed_medication_hx` | history_maker — Field Priorities experiment (`InfoGapGame`, `mode: "field_priorities"`); generated by current shipped code; may appear in recent records |
| `missed_pertinent_hx` | history_maker — Field Priorities experiment (`InfoGapGame`, `mode: "field_priorities"`); generated by current shipped code; may appear in recent records |
| `missed_events_mechanism` | history_maker — Field Priorities experiment (`InfoGapGame`, `mode: "field_priorities"`); generated by current shipped code; may appear in recent records |
| `scale_selection` | peds_gcs_calculator |
| `eye_component` | peds_gcs_calculator |
| `verbal_component` | peds_gcs_calculator |
| `motor_component` | peds_gcs_calculator |
| `total_math` | peds_gcs_calculator |
| `airway_ap` | adult_child_ap_swipe |
| `circulation_ap` | adult_child_ap_swipe |
| `communication_ap` | adult_child_ap_swipe |
| `medication_dosing_ap` | adult_child_ap_swipe |
| `shock_recognition` | shock_spotter_med, shock_spotter_trauma |
| `moi_recognition` | moi_mapper |
| `bsa_estimation` | rule_of_nines |
| `hemorrhage_control` | stop_the_bleed |
| `bls_sequence` | bls_sequence |
| `missed_A` | ams_aeioutips |
| `missed_E` | ams_aeioutips |
| `missed_I` | ams_aeioutips |
| `missed_O` | ams_aeioutips |
| `missed_U` | ams_aeioutips |
| `missed_T` | ams_aeioutips |
| `missed_P` | ams_aeioutips |
| `missed_S` | ams_aeioutips |
| `false_positive_<letter>` | ams_aeioutips |
| `invalid_pair_selection` | ams_aeioutips |
| `early_vs_late_deterioration` | vitals_trend_spotter |
| `etiology_misidentification` | vitals_trend_spotter, resp_dx_1q |
| `response_misprioritization` | vitals_trend_spotter |
| `impression_anchoring` | protocol_pivot, resp_dx_1q — same cognitive failure in different game mechanics: failing to update a working diagnosis when new evidence contradicts it |
| `missed_pivot_finding` | protocol_pivot |
| `poor_investigation_choice` | resp_dx_1q — selected a low-yield investigation that cannot differentiate the correct diagnosis from its nearest competitors in this case |
| `handoff_omission` | dmist_builder |
| `handoff_sequence` | dmist_builder |
| `developmental_regression_missed` | dev_flags |
| `developmental_mismatch_missed` | dev_flags |
| `bls_sequence_error` | cpr_bls_sequence |
| `cpr_metric_confusion` | cpr_bls_concepts |

Next-action routing may recommend a mini-game only when its explicit rubric-category mapping matches the learner's failed rubric category, or when lower-priority mistake-tag routing is intentionally being used as a separate remediation signal.

---

## 9. Implementation Order

1.  Preserve existing `pat_dash` and `dev_sort` behavior.
2.  Add `run_id` to result submissions for new games; migrate legacy endpoints to the shared contract incrementally.
3.  Add data-configurable extensions to PAT swipe and drag/sort engines (see §7 constraint: must not change existing game defaults).
4.  Author CE-aligned content before expanding large card banks: Adult vs. Child A&P implication cards (enforce 70% gate before CE deck ships), GCS Socratic feedback templates, Lung Sounds V2 implication prompts (author alongside V1 audio clips, not as a retrofit), and History Maker V2 Interview Builder prompts.
5.  Implement History Maker V2 Interview Builder as the CE-primary mode. Do not expand the V1 card bank further until V2 is on the active implementation schedule.
6.  Implement new SCORM-derived games in the main catalog: Adult vs. Child A&P (CE deck only), Lung Sounds Matcher (with V2 follow-ups), History Maker V2, Pediatric GCS Calculator, TEN-4 FACESp.
7.  Implement `PairMatchGame` for `ams_aeioutips`; add game to Dog Park catalog.
8.  Implement Rule of Nines with gateway wiring to replace the former PT1 auto-complete-on-visit. ✓ Complete.
9.  Implement Developmental Red Flags (`dev_flags`) as a separate game on the PM1 area of the map.
10. Add scenario bridge prompts to game results screens across the catalog. Wire debrief next-action routing to mini-game launch.
11. Design and implement Vitals Trend Spotter and Protocol Pivot as Dog Park CE games.
12. Implement broader pediatric-map games as their maps become playable, using CE-aligned interaction models: Shock Spotter with soft time pressure, Differential Dash as PairMatch/case vignette rather than bucket sorting, MOI Mapper as mechanism-to-injury implication, Stop the Bleed as escalation/sequence reasoning, Temp Check as treatment-priority vignette, and BLS Sequence with post-sequence reveal.
13. Add static game metadata for all games: `skill_tags`, `rubric_category_mapping`, hint policy, reference-card gate, mastery flow, and adaptive next step.
14. Implement Learning Design Priority 5 debrief routing from `rubric_category_mapping`. Keep recent mistake-tag routing as a lower-priority remediation signal.
15. Wire mistake tags into spaced-retrieval and adaptive difficulty once the recommendation engine is designed.

---

## 10. Open Decisions

| Decision | Status |
|---|---|
| Whether Lung Sounds Matcher ships with audio in V1 or text/finding cards first | Resolved: V1 ships with real audio files; text/finding cards are fallback/dev fixtures |
| Adult vs. Child A&P interaction | Resolved: three-way swipe/tap; up = Both/Shared |
| GCS scale coverage | Resolved: includes pediatric and infant GCS scales |
| Sound Check vs. Lung Sounds Matcher interaction | Resolved: both use the audio matching component with real audio files and fixed ordered answer buttons |
| TEN-4 FACESp interaction | Resolved: swipe with image and brief description |
| Whether History Maker should include caregiver-phone scenarios in Foundation | Resolved: no by-phone mode; Foundation is OPQRST/SAMPLE PairMatch. CE remediation should move directly from PairMatch into Interview Builder rather than phone or priority-ranking variants |
| Whether TEN-4 FACESp requires medical director review before public deployment | Resolved: yes, required before public deployment |
| Whether SCORM Lite node IDs become aliases or primary IDs in the main app | Resolved: use the same stable mini-game IDs in both main app and SCORM packages |
| Whether SCORM completions credit main-app progression | Resolved: no automatic sync; SCORM and main-app results are independent records until a sync integration is explicitly designed |
| History Maker V2 entry point | Resolved: one stable `history_maker` game identity with a guided two-round flow — Foundation PairMatch first, then Interview Builder. Do not present Field Priorities or Interview Builder as separate intro choices; Field Priorities is retired because highest-priority-question ranking is too ambiguous and opinion-dependent for deterministic scoring. |
| History Maker V2 content source | Resolved: author fresh Interview Builder cases first. Do not pull from scenario content yet. Fresh cases allow tuning of target mnemonic, clinical context, acceptable phrase chunks, distractors, feedback, and mistake tags without coupling mini-game content to scenario runtime or leaking scenario answers. Scenario-linked prompts may be added later with explicit `related_scenario_ids`. |
| DMIST Builder ordering strictness | Resolved: loose priority-band scoring. EMS handoffs have valid variation; exact rank order would feel brittle. Score required element inclusion heavily, then score relative order within priority bands (critical demographics/mechanism/problem → key findings → interventions → response/trends → transport/ETA). Penalize omissions and unsafe sequencing, not harmless ordering variation within a band. |
| DMIST Builder V1 interaction model | Resolved: batch-classify (tap-to-toggle Include/Skip tiles), not drag-to-reorder. V1 scores correct required/omit decisions across all 12 elements per case. Sequence scoring (`handoff_sequence` tag) deferred to V2 — needed infrastructure (ordered sequence column, reorder UX) not justified before Phase 5 routing is live. |
| `dev_flags` data folder naming | Resolved: data files at `static/data/games/dev_red_flags/` (agent-authored path); game ID remains `dev_flags` per stable spec. Folder name is internal; only the game ID is exposed to the backend, Dog Park, and map nodes. |
| Protocol Pivot pivot-finding visibility in Act 2 | Resolved: the pivot finding panel stays visible during Act 2 answer selection. Hiding it would turn the mechanic into a memory test rather than a model-updating exercise. Act 1 feedback is cleared on Act 2 render; the finding panel is not. |

---

## 11. Implementation Plan

This section tracks the phased implementation of game updates and new games. Check items off as they are completed. Phases are ordered by dependency — earlier phases unblock later ones.

**Current status:** 12 games are fully playable — `pat_dash`, `dev_sort`, `ten4_facesp`, `adult_child_ap_swipe`, `lung_sounds_matcher`, `history_maker` (Foundation plus Interview Builder; Field Priorities preserved only for historical records), `peds_gcs_calculator`, `ams_aeioutips`, `dev_flags`, `dmist_builder`, `protocol_pivot`, and `vitals_trend_spotter`. Phases 1–9 are complete. Phase 9 adds CE adaptive V2 rounds for A&P, Lung Sounds, GCS, TEN-4, AEIOUTIPS, and PAT after demonstrated proficiency. LSM stridor cards (4 of 12) remain production-blocked on audio licensing unless filtered from production decks.

---

### Phase 1 — Foundation Fixes

These are correctness and contract issues that affect all subsequent phases. Complete before authoring any new card content.

- [x] **1.1 Fix `ams_aeioutips` result submission**
  - `app/main.py` — add `"ams_aeioutips"` to `_ALLOWED_MINIGAME_IDS`
  - Without this, XP, analytics, and debrief routing for the strongest CE game in the catalog are silently broken

- [x] **1.1a Wire `ams_aeioutips` mistake tags from the frontend**
  - Current shipped implementation collects missed letter-tags (`missed_A`–`missed_S`) and false-positive tags from the existing game flow, then deduplicates and passes `mistakeTags` to `_mgSubmitResult()`
  - PairMatch redesign should preserve the same remediation routing contract while emitting more specific selected-category tags such as `false_positive_U`

- [x] **1.2 Add `mistake_tags` to the result contract**
  - `app/main.py` — add optional `mistake_tags: list[str]` to the `POST /api/me/minigames/result` request model; store in `MinigameResult` (JSON column)
  - `static/js/app.js` — update `_mgSubmitResult()` to accept and forward a `mistakeTags` array parameter
  - Must be in place before any new card content ships so all new cards generate analytics from day one
  - **Deferred:** PAT and dev_sort use dedicated user columns (not `MinigameResult`) — `mistake_tags` for those endpoints is tracked in Phase 5 alongside adaptive routing

- [x] **1.2a Add DB migration for `mistake_tags` and `mode` columns**
  - `app/database.py` — `ALTER TABLE minigame_results ADD COLUMN IF NOT EXISTS mistake_tags JSONB` and `mode VARCHAR(64)` added to `init_db()` as safe additive migrations (no-ops on already-migrated DBs)

- [x] **1.3 Move GCS vignettes from `app.js` to a data file**
  - Create `static/data/games/peds_gcs_calculator/game.json` with the vignette array currently hardcoded in `app.js`
  - `static/js/app.js` (`PedsGcsGame`) — load vignettes from URL instead of inline array
  - Required before Phase 2.3 (Socratic feedback) can be authored as data

- [x] **1.4 Add `mode` field to the result contract**
  - `app/main.py` — add optional `mode: str | None` to the `POST /api/me/minigames/result` request model; store in `MinigameResult`
  - `static/js/app.js` — update `_mgSubmitResult()` to accept and forward an optional `mode` parameter
  - Must be in place before History Maker V2 (Phase 3) and CE/scaffold deck variants (Phase 2.1, 5.2) ship. Mixing untagged and mode-tagged runs for the same `minigame_id` will corrupt adaptive tier analytics.

---

### Phase 2 — Existing Game Content Improvements

No new engines. Data authoring and minor frontend changes only. Can be done in parallel once Phase 1 is complete.

- [x] **2.1 Adult vs. Child A&P — author implication cards**
  - `static/data/games/ap/cards.json` — replaced all 20 anatomy-fact cards with 20 CE-level implication cards (100% implication rate, exceeds 70% gate)
  - All cards have `mistake_tag` field: 7 `airway_ap`, 5 `circulation_ap`, 4 `medication_dosing_ap`, 4 `communication_ap`
  - `static/js/app.js` (`SwipeGameEngine`) — `_submitAnswer()` now collects `card.mistake_tag` on wrong answers; `_finishRound()` deduplicates and passes `mistakeTags` to `onRoundComplete`; `_apEngine.normalizeCard` passes through `mistake_tag`; `onRoundComplete` forwards `mistakeTags` to `_mgSubmitResult`

- [x] **2.2 Lung Sounds Matcher — two-round intervention flow** ⚠️ 4 stridor cards blocked on audio licensing
  - `static/data/games/lsm/cards.json` — rewrote to 12 cards; all cards now have identification data plus `follow_up: { prompt, choices[{id,label,score,min_scope,feedback}], feedback, mistake_tag, hint }` for the separate intervention round
  - `static/js/app.js` (`TapChoiceGame`) — Lung Sounds now runs Round 1 audio identification, then Round 2 scope-filtered intervention selection. Intervention choices are filtered by provider level; available denominator shrinks to visible in-scope choices; acceptable answers can earn partial credit and best in-scope answers earn full credit.
  - **Audio licensing resolved for 8 of 12 cards:**
    - 6 cards: Mendeley HLS-CMDS (CC BY 4.0) — `LS/*.wav` files confirmed
    - 1 card (`lsm_crackles_pneumonia`): Wikimedia `Crackles_pneumonia.mp3` (CC BY-SA 3.0) — added as new 12th card
    - 1 card (`lsm_normal_01`): Local asset with no known external source
  - **Production blocker (4 cards):** `lsm_stridor_01`, `lsm_stridor_02` (theSimTech), `lsm_stridor_03`, `lsm_stridor_04` — Mendeley HLS-CMDS contains no stridor recordings; source and license unresolved; `license_source` set to `"UNRESOLVED"` in cards.json; these cards display in-game but must not ship to production until audio is cleared or replaced

- [x] **2.3 Pediatric GCS Calculator — Socratic feedback**
  - `static/data/games/peds_gcs_calculator/game.json` — added `feedback: { e, v, m }` per vignette; each string names the observable cue, maps it to the correct score, and contrasts the nearest distractor
  - `static/js/app.js` (`PedsGcsGame.submit()`) — on wrong submission, collects feedback for each incorrect component (E, V, M independently), joins them with " · " separator, and sets the `gcs-feedback` element; `_renderVignette()` already clears it on advance

- [x] **2.4 Scenario bridge prompts — all game results screens**
  - `static/index.html` — added `<div class="mg-bridge">` with framing text and `btn-{prefix}-try-scenario` button to all 6 results panels (ten4, ap, lsm, hm, aeiou, gcs); each framing sentence names the specific scenario context where the primed skill applies
  - `static/css/style.css` — added `.mg-bridge`, `.mg-bridge-text`, `.mg-bridge-btn` (teal, full-width, below existing btn-row)
  - `static/js/app.js` — wired all 6 bridge buttons to their respective `_exit{Game}ToMap()` functions, routing the learner to the category/map screen to select a scenario
  - Phase 5.3 will extend these to use debrief routing data for mistake-tag-based scenario targeting

---

### Phase 3 — History Maker V2 Direction (Urgent CE Priority)

Foundation now uses PairMatch rather than statement-to-category MCQ. The prior Field Priorities / Information Gap experiment is retired because "highest-priority question" ranking is too ambiguous and opinion-dependent for deterministic continuing-education scoring. The forward CE round is Interview Builder: learners construct clinically specific OPQRST/SAMPLE questions from authored phrase chunks.

**Entry point (resolved):** one `history_maker` game identity with a required two-round flow: Foundation PairMatch (`mode: "foundation"`) → Interview Builder (`mode: "interview_builder"`). **Content source (resolved):** author fresh Interview Builder cases; do not pull from scenario content yet. See §10 for full rationale.

- [x] **3.1 Author Interview Builder case data**
  - Create authored cases with patient presentation, target mnemonic component, target question assembled from 2–3 chunks, acceptable alternate chunks, distractor chunks, and feedback.
  - Keep chunks at clause-level granularity. Avoid word-by-word assembly that turns the activity into a grammar puzzle instead of clinical synthesis.
  - Enforce syntax parity: distractors must be grammatically plausible, with no capitalization, punctuation, verb-tense, or agreement clues that reveal the correct path.
  - Distractors should represent wrong mnemonic focus, wrong clinical context/differential, or developmentally mismatched wording.
  - Do not use highest-priority-question ranking as the core mechanic.
  - Target 7–9 cases; select 5–6 randomly per session so replays see different case sets. The current Field Priorities deck (8 vignettes, always all 8) has no replay variety — do not replicate that pattern.
  - Do not adapt or recycle Field Priorities vignettes (`vignettes.json`) for Interview Builder; the interaction model is fundamentally different (phrase-chunk assembly vs. choice ranking). Author fresh cases.

- [x] **3.2 Implement `SentenceBuilderGame` engine**
  - Interaction: presentation + target component → phrase chunk bank → learner taps chunks into a sentence block → deterministic submit.
  - Score correct mnemonic target, clinical context, safe/complete phrasing, and developmentally appropriate wording.
  - Support authored acceptable alternate chunk-ID sequences so correct field wording is not overly brittle.
  - Allow learners to remove selected chunks before Submit, preferably by tapping a chunk in the assembled sentence block to return it to the bank.
  - Incorrect submission feedback must use the Socratic feedback string from §3: identify learner intent, ask what the target component clarifies, contrast wording, then confirm the corrected question.

- [x] **3.3 Replace Field Priorities mode switcher with guided two-round flow**
  - History Maker intro starts Round 1 Foundation PairMatch; Interview Builder is entered from the Round 1 result panel, not from a mode menu.
  - Do not default learners directly into Interview Builder from the intro; the reference-card earning path depends on both rounds.
  - Remove or hide the Field Priorities entry point from production navigation.

- [x] **3.4 Wire Interview Builder to result endpoint**
  - Submit through the shared mini-game result endpoint with `mode: "interview_builder"`.
  - Continue submitting Foundation runs as `mode: "foundation"`.
  - Emit mistake tags: `wrong_mnemonic_focus`, `wrong_clinical_context`, and `developmentally_mismatched_language`.

- [ ] **3.5 Add earned reference-card gate**
  - **Phase 3 complete for playable flow:** Foundation can now sequence directly into Interview Builder from the result panel.
  - **Backend unlock remains Phase 6.3:** Lock the OPQRST/SAMPLE reference card until both Foundation and Interview Builder pass conditions are met.
  - After unlock, show an earned-card reveal and make the card available from the History Maker result screen and learning area.
  - Before unlock, allow only brief hints or Socratic prompts; do not expose the full reference card.

---

### Phase 4 — New Games

In order of implementation complexity, lightest first.

#### 4.1 Developmental Red Flags (`dev_flags`) — Light

Uses the existing `TriSwipeGameEngine`. Primarily a content authoring and wiring task.

- [x] **Author card data**
  - Created `static/data/games/dev_red_flags/cards.json` (20 cards, df_01–df_20)
  - Three-way answers: expected (7) / concerning (8) / further_assessment (5)
  - Age span 2 months–7 years; domains: gross motor, language, social, fine motor, cognitive
  - Three regression cards (df_07, df_12, df_17) always `concerning` with `developmental_regression_missed`
  - All other cards carry `developmental_mismatch_missed`

- [x] **Author learning page**
  - Created `static/data/games/dev_red_flags/learning_page.md`
  - Note: data files in `dev_red_flags/` folder; game ID is `dev_flags` per stable spec

- [x] **Wire engine and screen**
  - `static/js/app.js` — `_dfEngine` (`TriSwipeGameEngine`), `_openDfGameScreen()`, `_exitDfToMap()`, added to `_MG_TYPES`, `_MG_LEARNING_PAGES`, `_playMinigameSelection()`, `_startMinigameRoundFromIntro()`, event listeners
  - `static/index.html` — `screen-df-game` panel with intro overlay, swipe stamps, 3-choice buttons, bridge prompt
  - `app/main.py` — `"dev_flags"` in `_ALLOWED_MINIGAME_IDS`
  - PM1 converted from `game:` to `games:` array with both `dev_sort` and `dev_flags`; Dog Park `foundations` group updated

#### 4.2 DMIST Builder (`dmist_builder`) — Medium

Implemented as `DmistBuilderGame` (batch-classify engine). Players tag each handoff element Include or Skip; scoring on required/omit correctness. Sequence scoring deferred to V2.

- [x] **Author case data**
  - Created `static/data/games/dmist_builder/cases.json` (4 cases: STEMI, peds asthma, trauma, opioid OD)
  - Each case: 12 elements — 7 required, 2–3 optional, 2 omit
  - All 5 priority bands covered per case
  - Omit elements are realistic non-clinical details (social circumstances, legal matters, property damage)

- [x] **Author learning page**
  - Created `static/data/games/dmist_builder/learning_page.md`

- [x] **Implement `DmistBuilderGame` engine**
  - `static/js/app.js` — new `DmistBuilderGame` class; tap-to-toggle tiles (untagged → include → skip → untagged); submit scores required/omit decisions; per-case feedback with missed required and incorrectly included omit elements; mistake tags `handoff_omission`
  - `static/index.html` — `screen-dmist-game` panel with intro overlay, element tile grid, submit button, bridge prompt
  - `app/main.py` — `"dmist_builder"` in `_ALLOWED_MINIGAME_IDS`
  - Added to Dog Park `assessment` group; PM3 QA group updated
  - Note: PM5 placement deferred (placeholder `_ph_diff_dash_resp` retained); sequence scoring (`handoff_sequence` tag) deferred to V2

- [x] **Add to Dog Park catalog and PM3 QA group (PM5 placement deferred)**

#### 4.3 Protocol Pivot (`protocol_pivot`) — Medium

New `ProtocolPivotGame` engine: two-act case vignette with mid-case finding injection.

- [x] **Author case data**
  - Created `static/data/games/protocol_pivot/cases.json` (5 cases)
  - Cases: COPD→cardiogenic edema, ACS→aortic dissection, stable trauma→tension pneumo, hypoglycemia→Wernicke's, febrile seizure→meningococcal sepsis
  - Act 1 correct: 1 point; Act 2 correct: 2 points; max 15 points per round
  - Each Act 2 wrong-answer set includes one `missed_pivot_finding` anchoring trap

- [x] **Author learning page**
  - Created `static/data/games/protocol_pivot/learning_page.md`

- [x] **Implement `ProtocolPivotGame` engine**
  - `static/js/app.js` — new `ProtocolPivotGame` class; two-act state machine; pivot_finding panel revealed after Act 1 submission; `continueToAct2()` transitions to Act 2; weighted scoring (1+2); mistake tags `impression_anchoring`, `missed_pivot_finding`
  - `static/index.html` — `screen-pivot-game` panel with intro overlay, act label badge, pivot finding panel, bridge prompt
  - `app/main.py` — `"protocol_pivot"` in `_ALLOWED_MINIGAME_IDS`
  - Added to Dog Park `assessment` group; PM3 QA group updated

- [x] **Add to Dog Park catalog**

#### 4.4 Vitals Trend Spotter (`vitals_trend_spotter`) — Large — **Complete**

Implemented as an SVG-based temporal data component. Learner taps the deterioration point on a multi-channel vitals trend, then answers deterministic etiology and response follow-ups.

- [x] **Author case data**
  - Created `static/data/games/vitals_trend/cases.json` with 3 cases: sepsis compensation failure, asthma fatigue, and dehydration/hypovolemic shock
  - Each case defines `duration_sec`, `data_points`, `event_window_ms`, etiology choices, response choices, and authored feedback
  - Mistake tags: `early_vs_late_deterioration`, `etiology_misidentification`, `response_misprioritization`

- [x] **Author learning page**
  - Created `static/data/games/vitals_trend/learning_page.md`

- [x] **Implement `VitalsTrendGame` engine**
  - `static/js/app.js` — new `VitalsTrendGame` class
  - Chart component renders HR, SpO2, RR, and SBP as SVG polylines; tap/click on the timeline marks the learner's identified event point
  - After timeline identification: authored etiology and immediate-response questions
  - Scoring: 1 point each for timeline accuracy, etiology, and response per case
  - `static/index.html` — `screen-vitals-trend-game` panel and intro overlay
  - `app/main.py` — `"vitals_trend_spotter"` added to `_ALLOWED_MINIGAME_IDS`

- [x] **Add to Dog Park catalog and PM3 map placement**
  - Added to Dog Park assessment group, PM3 QA testing placement, learning-page registries, and debrief mini-game opener map

---

### Phase 5 — Analytics and Routing Infrastructure

Complete after at least 3 games are generating `mistake_tags` in production.

- [x] **5.1 Mistake-tag-based debrief routing (V1 approximation — see Phase 6.4 for Priority 5 upgrade)**
  - `app/main.py` — added `_get_recent_mistake_tags(user_id, db, days=30)` async helper; V1 groups recent `mistake_tags` by the originating `game_id`, which is already the remediation game for the current mini-game catalog; all 3 debrief call sites fetch gaps and pass via `minigame_gaps=` kwarg to `_generate_debrief_with_retry`
  - `app/ai_client.py` — `evaluate_and_generate_debrief` accepts `minigame_gaps`; injects as `mini_game_gaps` into evidence packet audit record; passes to `_compute_next_action_routing`; `_compute_next_action_routing` adds **priority 7** (last resort): if `minigame_gaps` non-empty and no higher-priority routing applies, returns `("minigame", game_id)` for the game with most distinct recent tags; routing prompt block includes `minigame_name` and `minigame_skill_gaps` context when target is a mini-game
  - `static/js/app.js` — debrief next-action handler maps `naId` (game_id) to `_openXxxGameScreen()` opener; button label changes to "Practice Now ▶" for minigame routing
  - **Routing signal:** this routes based on recent mini-game mistake-tag gaps, not on which rubric category was failed in the current scenario. Phase 6.4 adds the stronger LEARNING_DESIGN.md Priority 5 signal (`rubric_category_mapping` against failed category); the mistake-tag signal remains as the lower-priority fallback.

- [x] **5.2 Adaptive card tier routing**
  - `app/main.py` — added `GET /api/me/minigames/proficiency` endpoint returning `{ game_id: { runs_30d, avg_score_30d, last_score } }` for the last 30 days; powers frontend tier selection and future CE deck gating
  - Tier-based card filtering deferred to V2 (CE card deck authoring prerequisite) — proficiency signal is live and queryable

- [x] **5.3 Scenario bridge prompt — scenario launch wiring**
  - `app/main.py` — added `GET /api/me/minigames/recommended` endpoint returning top 1–2 mini-games by distinct mistake-tag count (last 30 days) with `display_name` for UI rendering
  - `static/js/app.js` — debrief "Practice Now ▶" button routes to the recommended game's intro screen via `_openXxxGameScreen()`; game_id→opener mapping covers all 9 mistake-tag-capable games

---

### Phase 6 — Metadata, Hints, Reference Cards, and Priority 5 Routing

These are the implementation tasks introduced by the §1 design principle updates (Hint Standard, Earned Reference Cards, Mastery Flows) and the LEARNING_DESIGN.md §2.3 routing architecture. They depend on Phase 5 being live so there are result records to test against.

- [x] **6.0 Create static mini-game metadata registry**
  - `app/minigame_metadata.py` — canonical backend registry containing `skill_tags`, `rubric_category_mapping`, `pass_threshold`, `hint_policy`, `reference_card`, `mastery_flow`, and `adaptive_next_step` for every generic `MinigameResult` game ID currently accepted by the backend
  - `app/main.py` — `_ALLOWED_MINIGAME_IDS` is now derived from the metadata registry, and startup validation fails loudly if an accepted game lacks metadata or carries malformed routing/unlock configuration
  - Recommended mini-game display names now come from the metadata registry instead of a duplicate local mapping
  - Top-level rubric categories are used for the initial pass; the metadata shape remains extensible for item-level rubric IDs when the scoring engine exposes them
  - Regression coverage added for registry validation: missing game metadata fails loudly; missing `pass_threshold` defaults to `score >= 80`; invalid `rubric_category_mapping` values are rejected
  - Learner-submitted result rows remain performance evidence only; they are not used as authoritative game configuration

- [x] **6.1 Add `hint_count` to result contract and database**
  - `app/database.py` — `ALTER TABLE minigame_results ADD COLUMN IF NOT EXISTS hint_count INTEGER NOT NULL DEFAULT 0` added to `init_db()` as a safe additive migration
  - `app/models.py` — `MinigameResult.hint_count` column added so ORM reads/writes the stored value
  - `app/main.py` — optional `hint_count: int | None` added to the `POST /api/me/minigames/result` request model; omitted values store as 0 and submitted values are clamped to a safe analytics range
  - `static/js/app.js` — `_mgSubmitResult()` accepts and forwards optional `hintCount`
  - Regression coverage added for optional request parsing, hint-count normalization/defaulting, and ORM column presence
  - Individual game engines incrementing and submitting non-zero hint counts happens in Phase 6.2 when per-card/per-case hint UI is wired

- [x] **6.2 Add per-card/per-case hint data to shipped games**
  - Authored `hint` fields per card/pair/case across shipped generic-result games: A&P, Lung Sounds, Developmental Red Flags, AMS AEIOUTIPS, History Maker Foundation/Interview Builder/legacy Field Priorities, DMIST Builder, Protocol Pivot, and Vitals Trend Spotter
  - `peds_gcs_calculator` uses `play_hint` for learner-requested hints so the existing post-submit `hint` answer-reveal text remains unchanged and does not leak the score before submission
  - `static/js/app.js` — shared hint controls are injected near each game's feedback area; hint button reveals authored hint text and increments a per-attempt `hintCount` once per card/case/act
  - `_mgSubmitResult()` forwards `hintCount` to the backend result contract from engines that support hints
  - All hints point to a reasoning lens without naming the correct answer (Hint Standard, §1)
  - Regression coverage added to verify shipped game data includes the expected hint fields

- [x] **6.3 Implement earned reference-card gates and mastery-flow unlock**
  - `app/database.py` — `minigame_reference_cards` table added: `(user_id, card_id, unlocked_at)` with unique constraint on `(user_id, card_id)`
  - `app/models.py` — `MinigameReferenceCard` ORM model added for deterministic earned-card persistence
  - `app/minigame_metadata.py` — reference-card content added to the metadata registry using the §2 schema: title, framework summary, common traps, field examples, related games, unlock condition, and review status
  - `app/main.py` — `GET /api/me/minigames/reference-cards` returns earned cards plus locked-card summaries; `POST /api/me/minigames/result` evaluates unlock conditions and returns `newly_unlocked_reference_cards`
  - Unlock conditions are declared per game in the metadata registry; backend evaluates them deterministically using `pass_threshold`, not `completed: true` alone — no LLM involvement
  - `static/js/app.js` — result submission shows a lightweight unlock toast when a new reference card is earned
  - Full reference-card library/modal UI remains Phase 10.4; Phase 6.3 provides the authoritative backend gate and learner-facing unlock notification hook
  - Regression coverage added for reference-card metadata content, missing-content validation, and the unique user/card persistence contract

- [x] **6.4 Implement Priority 5 debrief routing from `rubric_category_mapping`**
  - `app/ai_client.py` — `_compute_next_action_routing()` now checks static `rubric_category_mapping` against the highest-weight failed rubric category before falling back to recent mistake-tag routing
  - Failed category is computed from backend `session.score_snapshot.categories` using the Learning Design threshold: category score below 60% of category max; highest max-point category wins, then alphabetical category ID
  - A mini-game may only be recommended if its static metadata explicitly includes the failed category; legacy PAT/dev-sort reference metadata does not participate in this generic debrief-routing path unless a future opener and route are added
  - Deterministic tie-breaks are implemented: prefer mapped games with recent mistake-tag gaps for that learner; otherwise use category-specific preferred order; otherwise alphabetical game ID
  - Priority 5 fires before Priority 7 mistake-tag fallback, and Priority 7 remains available when no failed rubric category can be mapped
  - Regression coverage added for direct category → mini-game routing and mapped-game preference when recent gaps exist

- [x] **6.5 Protocol Pivot — Act 1 wrong → Act 2 recovery scoring**
  - `static/js/app.js` (`ProtocolPivotGame`) — Act 2 renders after every Act 1 submission regardless of correctness; score wrong→correct remains 0+2 rather than collapsing to 0+0
  - `static/data/games/protocol_pivot/cases.json` — current case format supports independent Act 2 scoring because each act has its own authored choices, correctness, feedback, and mistake tags
  - Recovery analytics added via `pivot_recovered_after_initial_miss` and `pivot_anchored_after_initial_miss` mistake tags so debrief/routing can distinguish wrong→correct cognitive flexibility from persistent anchoring

---

### Phase 7 — Shipped Game Polish

Lightweight improvements to already-shipped games. Can run in parallel with Phase 3 and Phase 6. No open-phase dependencies.

- [x] **7.1 Remove History Maker Field Priorities from production navigation**
  - `static/js/app.js` — Field Priorities is no longer selected from the History Maker intro; underlying `InfoGapGame` engine and `vignettes.json` remain for historical result legibility
  - `static/index.html` — intro now presents a guided two-round flow instead of a mode toggle

- [x] **7.2 Enforce GCS incomplete-input protection**
  - `static/js/app.js` (`PedsGcsGame`) — Submit remains disabled until E, V, and M are all selected; `submit()` also guards incomplete input and gives a UI prompt instead of scoring it as a clinical error
  - Verified as a correctness closeout: incomplete input is a UI state, not a wrong GCS submission

- [x] **7.3 Expand GCS vignette deck**
  - `static/data/games/peds_gcs_calculator/game.json` — expanded to 10 vignettes with additional child and infant cases; includes multiple infant-scale cases and near-miss combinations across E/V/M
  - `static/js/app.js` (`PedsGcsGame`) — rounds now sample a shuffled 6-vignette subset from the authored pool so learners do not always see every case in the same order

- [x] **7.4 Expand DMIST Builder case deck**
  - `static/data/games/dmist_builder/cases.json` — expanded from 4 to 8 cases; added pediatric respiratory distress, stroke/CVA, anaphylaxis, and blunt trauma
  - New cases follow the 12-element structure with required/optional/omit items and cover DMIST priority bands 1–5
  - `static/js/app.js` (`DmistBuilderGame`) — rounds now sample a shuffled 4-case subset from the authored pool so learners do not see every case every session

- [x] **7.5 Expand Protocol Pivot case deck and add session sampling**
  - `static/data/games/protocol_pivot/cases.json` — expanded from 5 to 8 cases; added evolving ACS/STEMI, pediatric upper-airway pivot, and masked sepsis presentations
  - New cases have distinct Act 1 and Act 2 answer sets; Act 2 renders regardless of Act 1 correctness (see Phase 6.5)
  - `static/js/app.js` (`ProtocolPivotGame`) — rounds now sample a shuffled 4-case subset from the authored pool so replay sessions see different case combinations

- [ ] **7.6 Resolve LSM stridor audio licensing**
  - Locate or commission cleared audio for `lsm_stridor_01` through `lsm_stridor_04`; acceptable sources: commissioned recordings with ownership documentation, licensed clinical audio library with redistribution rights, or verified CC0/PD assets with confirmed metadata
  - `static/data/games/lsm/cards.json` — update `license_source` and `audio_src` for the 4 stridor cards once assets are cleared; until resolved, stridor cards must be excluded from production builds per §7 Audio Matching Component enforcement gate
  - Graceful degradation is implemented: unresolved stridor cards remain `license_cleared: false`, `TapChoiceGame` filters unavailable/unlicensed cards from active play, and the game still completes with the licensed subset while logging an author-facing warning. Licensing itself remains externally blocked.

- [x] **7.7 Add soft time pressure to GCS CE mode**
  - `static/js/app.js` (`PedsGcsGame`) — added a calm per-vignette efficiency timer; it resets per vignette, never blocks submission, and tracks efficient completions as local performance feedback only
  - `static/index.html` — added accessible `aria-live` efficiency status to the GCS stat row
  - Timer uses neutral "calm pace / take your time" copy rather than flashing red countdown behavior

---

### Phase 8 — Speed-Game End-of-Round Review Screen

Required before the §1 speed-game exception can be fully realized. PAT Doorway Dash and TEN-4 FACESp currently deliver brief card-level feedback on the round result screen. Full 4-step Socratic explanations for missed cards must move to a dedicated review screen between rounds so learners can engage without breaking the doorway-assessment flow of active play. This phase is a prerequisite for Phase 9.6 (PAT adaptive V2) and Phase 9.4 (TEN-4 adaptive V2) to deliver meaningful adaptive feedback.

- [x] **8.1 Design missed-card review screen spec**
  - Screen structure: result-panel section listing missed cards from the round; each entry shows the card image when present, cue/prompt text, learner-selected classification, correct classification, and Socratic feedback
  - For single-round speed games, the review appears inside the round result panel before Play Again / Back to Map. If a future multi-round version is added, this same component can be shown between rounds before continuing.
  - If no cards were missed, the review panel stays hidden so perfect/clean rounds preserve cadence
  - Feedback source: prefer authored `socratic_feedback`; otherwise generate a four-step Socratic review from existing card explanation, expected decision, selected decision, and game-specific cue label. This gives complete coverage now while preserving the schema path for richer per-card authoring.

- [x] **8.2 Implement missed-card review for PAT Doorway Dash**
  - `static/js/app.js` (`SwipeGameEngine`) — collects missed cards during the timed round and renders missed-card review entries after the round result
  - `static/index.html` — PAT result panel now includes `pat-review` / `pat-review-list`
  - `static/css/style.css` — shared `.mg-review-*` styles added for speed-game missed-card review
  - PAT card schema now supports optional `socratic_feedback`; current implementation falls back to generated Socratic review text from existing explanation so base PAT flow remains unchanged

- [x] **8.3 Implement missed-card review for TEN-4 FACESp**
  - `static/js/app.js` (`SwipeGameEngine`) — same shared missed-card collection/rendering path as PAT
  - `static/index.html` — TEN-4 result panel now includes `ten4-review` / `ten4-review-list`
  - TEN-4 card schema now supports optional `socratic_feedback`; current implementation falls back to generated Socratic review text from existing explanation
  - Medical director review is still required before adding richer authored TEN-4 `socratic_feedback` text for production clinical/legal wording; fallback review uses already-authored card explanations

---

### Phase 9 — Adaptive V2 Modes

CE proficiency tier interactions for games where basic recognition is mastered by experienced providers. Depends on Phase 5.2 (proficiency endpoint — already live ✓). Game-specific adaptive content can be authored in parallel with engine wiring. Each game's adaptive direction is documented in its §3–4 design section; this phase is the implementation checklist. Submit all adaptive runs with `mode: "ce_adaptive"` to distinguish from baseline records.

- [x] **9.1 A&P Adaptive V2 — clinical-consequence selection**
  - `static/data/games/ap/cards.json` — author CE adaptive cards: age-specific finding → learner selects care consequence (airway positioning, dosing, communication, shock compensation); target 10–12 adaptive cards; mark each with `"tier": "adaptive"` to separate from baseline CE deck
  - `static/js/app.js` (A&P / `SwipeGameEngine` variant) — after proficiency detection (3+ runs ≥80% in the last 30 days via `GET /api/me/minigames/proficiency`), serve adaptive consequence cards; submit with `mode: "ce_adaptive"`

- [x] **9.2 Lung Sounds V2 — two-round scope-filtered intervention mode**
  - `static/data/games/lsm/cards.json` — intervention prompts authored for all cards; each prompt includes respiratory rate, work of breathing, oxygenation, and relevant signs/symptoms; choices declare `min_scope` and `score`
  - `static/js/app.js` (`TapChoiceGame` / LSM variant) — always runs the two-round flow and submits with `mode: "two_round_scope"`; adaptive implication-first mode is intentionally retired for Lung Sounds so proficient learners still practice intervention selection

- [x] **9.3 GCS Adaptive V2 — scale inference without prompting**
  - `static/data/games/peds_gcs_calculator/game.json` — add vignettes where the scale type (infant vs. pediatric) is not labeled in the prompt; learner must infer scale from age and clinical presentation before selecting E/V/M components; mark each with `"tier": "adaptive"`
  - `static/js/app.js` (`PedsGcsGame`) — after proficiency detection, serve scale-inference vignettes and suppress the explicit scale-select prompt; submit with `mode: "ce_adaptive"`

- [x] **9.4 TEN-4 Adaptive V2 — documentation-language follow-up**
  - `static/data/games/ten4/cards.json` — author documentation-language follow-up questions: after correct classification, learner selects the best objective documentation phrase (e.g., "bruising to the right pinna, location and pattern concerning for non-accidental trauma per TEN-4 FACESp criteria — reported per policy")
  - `static/js/app.js` (TEN-4 engine / shared swipe adaptive panel) — after proficiency detection, serve documentation-language follow-up cards; submit with `mode: "ce_adaptive"`
  - **Medical director review required** for documentation-language follow-up content before this ships to production; track review status alongside base card review

- [x] **9.5 AEIOUTIPS Adaptive V2 — action-priority vignette mode**
  - `static/data/games/ams_aeioutips/game.json` — author action-priority cases: short AMS vignette → learner selects the first EMS assessment or treatment priority (glucose check, oxygenation/ventilation, naloxone, stroke screen, trauma assessment, temperature management, sepsis recognition); author at least 8 vignette cases
  - `static/js/app.js` (`PairMatchGame`) — after proficiency detection, offer action-priority mode as an alternate round type or standalone session; submit with `mode: "ce_adaptive"`

- [x] **9.6 PAT Adaptive V2 — implication follow-up**
  - Add `implication_prompt` and `implication_choices` fields to PAT card data; author highest-priority first-action implication follow-up for each card (airway, oxygenation, vascular access, rapid transport, or specific intervention cue based on the PAT pattern)
  - `static/js/app.js` (PAT swipe engine / shared swipe adaptive panel) — after proficiency detection (3+ runs ≥80%), serve implication follow-up cards; submit with `mode: "ce_adaptive"`
  - Requires Phase 8.2 review screen to be complete so adaptive feedback can use the full Socratic pattern during missed-card review

---

### Phase 10 — Mastery Flow UI

Learner-facing navigation connecting scaffold → application → reference card unlock. Backend unlock logic is in Phase 6.3; this phase is the UI wiring and the library view that surfaces earned cards. Task 10.1's Foundation → Interview Builder continuation is complete as part of Phase 3; its reference-card reveal portion remains blocked on Phase 6.3. Tasks 10.2–10.4 are independent.

- [x] **10.1 History Maker mastery flow — Foundation → Interview Builder transition**
  - [x] `static/js/app.js` — after Foundation pass, show "Continue to Interview Builder ▶" button on the Foundation result screen; transition into Interview Builder mode when learner accepts; learner should experience this as a guided path, not a separate menu item
  - [x] `static/index.html` — add mastery-flow continuation button to History Maker Foundation result panel
  - [x] Add earned OPQRST/SAMPLE reference-card reveal after Phase 6.3 backend unlock endpoint exists — newly unlocked cards toast immediately after result submission and appear in the Notebook Learning reference-card library

- [x] **10.2 Developmental mastery flow — dev_sort → dev_flags transition**
  - `static/js/app.js` — after dev_sort first completion, show "Continue to Red Flags ▶" on the dev_sort result screen; wire to `_openDfGameScreen()` (already implemented in Phase 4.1 ✓)
  - `static/index.html` — add mastery-flow continuation button to dev_sort result panel
  - Shared developmental reference card unlock condition (§8 Game Metadata Matrix) requires both `dev_sort` and `dev_flags` pass; Phase 6.3 backend enforces this; this task is the UX bridge

- [x] **10.3 Lung Sounds mastery flow — audio identification → implication follow-up**
  - Current flow is audio identification → scope-filtered intervention selection in one session; the result screen states both skill areas are required for Breath Sounds mastery
  - Reference-card unlock remains tied to passing the unified two-round Lung Sounds run

- [x] **10.4 Reference card library view**
  - `static/index.html` — add a reference card library screen accessible from the learning area or learner profile; show earned cards with full authored content (framework summary, common traps, field examples); show locked cards greyed out with the unlock condition description and which game(s) must be passed
  - `static/js/app.js` — fetch `GET /api/me/minigames/reference-cards` (Phase 6.3) on library open; render unlocked card content inline or in a modal; show locked cards with unlock-condition labels
  - Reference card authored content lives in game data (Phase 6.3); this task is the UI surface that makes it accessible after unlock

---

### Phase 11 — New Map Games: Configuration-Only

Games that use already-built engines (PAT swipe, `PairMatchGame`, audio matching, case vignette, or `TapChoiceGame`). Each requires content authoring, engine configuration, static metadata, and map node wiring. No new engine code required for this phase. Proceed as the relevant maps become playable. New generic result IDs are authorized through `app/minigame_metadata.py` (`MINIGAME_METADATA` / `get_allowed_minigame_ids()`), not a route-local allowlist. Each new game must add static metadata from Phase 6.0 before it is exposed in production; otherwise hints, reference-card gates, Priority 5 routing, and adaptive behavior will require retrofitting.

- [x] **11.1 Sound Check PM2 (`sound_check`)**
  - `static/data/games/sound_check/` — audio card data file created using the same schema as `lsm/cards.json`; all active assets declare a valid `license_source`, `license_cleared: true`, `follow_up` implication prompts, and per-card `hint` text
  - `static/js/app.js` — existing audio matching engine configured for `sound_check`; wired to Dog Park, PM2 map node, learning page, debrief opener map, intro preview, and notebook learning references
  - `app/minigame_metadata.py` — `"sound_check"` added to canonical metadata/allowed-ID registry with hint policy, rubric mappings, reference-card unlock, and adaptive next-step contract
  - `app/main.py` — notebook learning registry entry added for `sound_check`

- [x] **11.2 Shock Spotter Med PM3 (`shock_spotter_med`)**
  - `static/data/games/shock_spotter_med/` — PAT swipe card data created with "Compensated Shock" / "Decompensated Shock" classification labels; authored 12 cards covering hemodynamic and perfusion findings, soft time pressure, per-card `hint` text, and selective implication follow-ups
  - `static/js/app.js` — PAT swipe engine configured with `shock_spotter_med` labels and soft timer; wired to PM3 map node, Dog Park catalog, learning page, preview routing, and debrief opener map
  - `app/minigame_metadata.py` — `"shock_spotter_med"` added to canonical metadata/allowed-ID registry with hint policy, rubric mappings, reference-card unlock, and adaptive next-step contract

- [x] **11.3 Differential Dash AMS PM4 (`diff_dash_ams`)**
  - `static/data/games/diff_dash_ams/` — `PairMatchGame` data created; pairs connect AMS findings to likely etiologies under light pressure; authored clinical-action implication nudges per round; 12 pairs across 4 rounds; CE-primary interaction is pair-matching, not bucket sorting
  - `static/js/app.js` — `PairMatchGame` generalized for configurable game IDs/prefixes and configured for `diff_dash_ams`; wired to PM4 map node, Dog Park catalog, learning page, preview routing, and debrief opener map; existing AEIOUTIPS pair-match behavior preserved through default config
  - `app/minigame_metadata.py` — `"diff_dash_ams"` added to canonical metadata/allowed-ID registry with hint policy, rubric mappings, reference-card unlock, and adaptive next-step contract

- [x] **11.4 Differential Dash Resp PM5 (`diff_dash_resp`)**
  - `static/data/games/diff_dash_resp/` — same pattern as 11.3; pairs connect respiratory findings to likely etiologies and immediate care implications; covers wheeze-based, crackle-based, obstructive, allergic, infectious, traumatic, toxin, and fatigue differentials; authored 12 pairs across 4 rounds
  - `static/js/app.js` — configured `PairMatchGame` engine for `diff_dash_resp`; wired to PM5 map node, Dog Park catalog, learning page, preview routing, and debrief opener map; uses the same 6-card grid pattern as `diff_dash_ams`
  - `app/minigame_metadata.py` — `"diff_dash_resp"` added to canonical metadata/allowed-ID registry with hint policy, rubric mappings, reference-card unlock, and adaptive next-step contract

- [x] **11.5 MOI Mapper PT4 (`moi_mapper`)**
  - `static/data/games/moi_mapper/` — authored 12 PAT-swipe mechanism cards with high-risk vs focused-assessment implication labels; cards connect blunt, penetrating, environmental, and pediatric mechanisms to hidden injury, SMR, hemorrhage, and transport concerns
  - `static/js/app.js` — configured PAT swipe engine with `moi_mapper` implication labels; wired to PT4 map node, Dog Park catalog, learning page, preview routing, and debrief opener map
  - `app/minigame_metadata.py` — `"moi_mapper"` added to canonical metadata/allowed-ID registry with hint policy, rubric mappings, reference-card unlock, and adaptive next-step contract

- [x] **11.6 Shock Spotter Trauma PT5 (`shock_spotter_trauma`)**
  - `static/data/games/shock_spotter_trauma/` — authored 12 trauma-context shock recognition cards with compensated/decompensated decisions, hints, Socratic explanations, and mistake tags
  - `static/js/app.js` — configured PAT swipe engine for `shock_spotter_trauma`; wired to PT5 map node, Dog Park catalog, learning page, preview routing, and debrief opener map with soft time pressure matching trauma shock decision-making
  - `app/minigame_metadata.py` — `"shock_spotter_trauma"` added to canonical metadata/allowed-ID registry with hint policy, rubric mappings, reference-card unlock, and adaptive next-step contract

- [x] **11.7 Temp Check PT7 (`temp_check`)**
  - `static/data/games/temp_check/` — authored 8 CE-primary case vignettes covering hypo/hyperthermia stages, sepsis screening, environmental exposure management, altered mental status significance, and transport priority
  - `static/js/app.js` — configured `TapChoiceGame` case-vignette component for `temp_check`; wired to PT7 map node, Dog Park catalog, learning page, preview routing, and debrief opener map
  - `app/minigame_metadata.py` — `"temp_check"` added to canonical metadata/allowed-ID registry with hint policy, rubric mappings, reference-card unlock, and adaptive next-step contract

---

### Phase 12 — New Map Games: New Engine or Major Extension Required

Games that require engine development beyond what Phase 11 reuses. Complete Phase 11 content authoring first to reduce scope risk and reuse any shared scored-order infrastructure across 12.2, 12.3, and 12.4.

#### 12.1 Rule of Nines + PT1 Gateway (`rule_of_nines`)

- [x] **Author game data**
  - `static/data/games/rule_of_nines/` — body-region configuration includes region labels, standard Rule of Nines percentages, pediatric BSA adjustment notes, and 6 burn vignettes with marked region answer keys plus deterministic implication follow-up questions covering airway risk, special-area concern, transport priority, and burn-care priorities
  - Reference card unlocks after a passing `rule_of_nines` run; static metadata is registered before production exposure

- [x] **Implement `BodyMapGame` engine**
  - `static/js/app.js` — `BodyMapGame` uses a pediatric patient visual map plus per-region +/- controls cycling through 0%, 1%, 9%, and 18%; selected/burned regions are colored on the SVG, the total TBSA updates live, and incorrect BSA submissions tell the learner to try again without revealing the answer
  - `static/index.html` — `screen-rule-of-nines-game` includes the pediatric SVG body map, per-region percentage controls, bottom total calculation, reset button, Submit button, implication follow-up area, results, bridge prompt, and intro learning controls
  - Region controls are button-based with accessible labels and keyboard-compatible fallback behavior; the SVG regions are a visual/tap shortcut, not the only input path

- [x] **Wire PT1 gateway and remove auto-complete placeholder**
  - `app/main.py` — `"rule_of_nines"` added through canonical metadata/allowed-ID registry; passing `rule_of_nines` results write `PedsMapProgress("pt1")` idempotently
  - `static/js/app.js` — removed PT1 auto-complete-on-visit placeholder; generic mini-game result submission already refreshes `_loadProgressFromServer()` after successful result submission
  - PT1 map node now opens the functional Rule of Nines game instead of a placeholder

#### 12.2 Stop the Bleed PT2 (`stop_the_bleed`)

- [x] **Author escalation sequence data**
  - `static/data/games/stop_the_bleed/` — authored 5 hemorrhage-control escalation cases with wound type/context, correct sequence, hints, mistake tags, and post-sequence explanations
  - Cases cover extremity laceration, junctional wound, torso penetrating wound, pediatric partial amputation, and controlled scalp bleeding/over-escalation
  - Static metadata from Phase 6.0 is registered before production exposure

- [x] **Implement scored-order escalation mode**
  - `static/js/app.js` — implemented shared `SequenceOrderGame`; learners build the full sequence before reveal, partial credit is awarded per correctly positioned step, and per-step confirmation is prohibited
  - `static/index.html` — added `screen-stop-bleed-game` panel; wired to PT2 map node
  - `app/main.py` — `"stop_the_bleed"` accepted through canonical metadata/allowed-ID registry

#### 12.3 BLS Sequence PT6 (`bls_sequence`)

- [x] **Author sequence data**
  - `static/data/games/bls_sequence/` — authored 3 BLS variants: adult arrest, pediatric two-rescuer arrest, and AED-first witnessed collapse
  - Correct step order and scoring model are aligned to the existing CPR Challenge/AHA-informed project design: rapid recognition, help/AED, CPR, analysis pause, shock/no-shock decision, immediate resumption
  - Static metadata from Phase 6.0 is registered before production exposure

- [x] **Implement ranked-list scored-order mode**
  - `static/js/app.js` — reused shared `SequenceOrderGame`; learner assembles the full step sequence, Submit activates only when all steps are placed, and correct order is revealed alongside learner order
  - `static/index.html` — added `screen-bls-sequence-game` panel; wired to PT6 map node
  - `app/main.py` — `"bls_sequence"` accepted through canonical metadata/allowed-ID registry
  - Shared scored-order engine extension is implemented once and reused by Stop the Bleed, BLS Sequence, and Priority Stack

#### 12.4 Priority Stack PE2 (`priority_stack`)

- [x] **Author ranked-list synthesis data**
  - `static/data/games/priority_stack/` — authored 4 high-acuity cases where learners rank competing treatment/transport priorities; cases cover trauma shock, respiratory failure, anaphylaxis, and AMS/glucose screening
  - Static metadata from Phase 6.0 is registered before production exposure

- [x] **Implement `PriorityStackGame`**
  - `static/js/app.js` — reused shared `SequenceOrderGame`; full-sequence submission before reveal with partial credit per correctly positioned priority and hint support that does not reveal rank
  - `static/index.html` — added `screen-priority-stack-game` panel; wired to PE2 map node with scenario bridge prompt
  - `app/main.py` — `"priority_stack"` accepted through canonical metadata/allowed-ID registry

#### 12.5 Differential Detective — Resp-Dx (`resp_dx_1q`)

- [x] **Author branching case data**
  - `static/data/games/resp_dx/cases.json` — author 8–10 cases covering the 5 core differentials: Asthma, Croup, Epiglottitis, Anaphylaxis, FBAO; include at least 2 cases per differential to prevent over-fitting to a single presentation pattern
  - Each case must declare: `presentation`, `correct_diagnosis`, `differentials` array (always all 5), `investigations` array (4–5 options, exactly 1 with `is_high_yield: true`), and `feedback` object with `correct_high_yield`, `correct_other`, `incorrect_after_trap`, and `incorrect_generic` strings
  - Investigations with `anchoring_trap: true` must also declare `anchoring_trap_target` (the wrong diagnosis the learner is most likely to select after seeing this finding)
  - All authored case data must be clinically reviewed before production deployment; the 5-differential set overlaps heavily with NAT, sepsis, and toxidrome presentations — authoring quality gate is mandatory
  - Session sampling: select 4–5 cases randomly per session so replay sessions see different case sets

- [x] **Implement `DifferentialDetectiveGame` engine**
  - `static/js/app.js` — new `DifferentialDetectiveGame` class; state machine: `investigation` → `diagnosis` → (if wrong) back to `investigation` with retained clues; investigation bank hides answered options; diagnosis bank shows all 5 differentials after each investigation
  - Frontend sends raw `investigation_id` chosen and `diagnosis_chosen` to the result endpoint — never calculates points or evaluates `is_high_yield` itself
  - Anti-guessing friction: after an incorrect diagnosis, brief lockout (1–2 seconds) before investigation bank re-activates; prevents rapid re-guess without adding an investigation
  - Clue retention: previously revealed investigation findings stay visible and greyed out across guess attempts so the learner can compare accumulating evidence
  - `static/index.html` — `screen-resp-dx-game` panel with presentation block, investigation bank, retained-clues panel, and diagnosis bank
  - `app/main.py` — add `"resp_dx_1q"` to `_ALLOWED_MINIGAME_IDS`; backend evaluates `is_high_yield` and `anchoring_trap` flags during result processing to compute per-case points; normalize to `score = round((earned/max) × 100)` before storing

- [x] **Wire PM5 map node and Dog Park placement**
  - `resp_dx_1q` replaces `diff_dash_resp` as the CE-primary PM5 game; update map node data to point to `resp_dx_1q`
  - `diff_dash_resp` moves to Dog Park warm-up category; update Dog Park catalog to include both

---

### Phase 13 — Deferred Large Work

These items were originally deferred pending infrastructure decisions, external review, or Phase 5–6 analytics maturity. They are now implemented with conservative V2 scope: dependency-free Vitals SVG playback, optional approved-media GCS rendering, and additive DMIST sequence capture/scoring.

- [x] **13.0 Phase 13 readiness infrastructure and evidence setup**
  - Phase 13.0 is complete as a readiness setup phase. It created the evidence logs, browser checklists, guardrails, and analytics helper used to bound the V2 work and preserve post-implementation review evidence.
  - [x] Use `docs/MINIGAMES_PHASE13_READINESS.md` as the canonical evidence log and decision template for this phase.
  - [x] Use `docs/MINIGAMES_PHASE13_E2E_CHECKLIST.md` as the manual browser checklist for Vitals Trend Spotter and Pediatric GCS readiness runs.
  - [x] `vitals_trend_spotter`: record the accessibility approach required for any animated or richer charting mode.
  - [x] `peds_gcs_calculator`: confirm Phase 7.3 deck expansion coverage before media authoring.
  - [x] `peds_gcs_calculator`: confirm browser/production stability before media authoring. Media V2 may not begin until the base text/vignette calculator is stable enough that media adds observation fidelity rather than masking unresolved scoring or UX issues.
  - [x] `peds_gcs_calculator`: create a media asset inventory before code work begins.
  - [x] `peds_gcs_calculator`: add automated guardrails requiring each future media item to declare source, license status, accessibility fallback, and a prompt-quality check confirming it shows observable behavior without using scoring labels such as `"withdraws"` or `"abnormal flexion"`.
  - [x] `dmist_builder`: confirm Phase 7.4 deck expansion before sequence-scoring work begins.
  - [x] `dmist_builder`: expose learner-scoped Phase 13 readiness analytics helper for run counts, average score, mistake-tag counts, and 30-day data-gate evidence.
  - Remaining field evidence lives on 13.1–13.3 below and does not keep 13.0 open: Vitals desktop/mobile E2E and charting decision, GCS licensed media assets, and DMIST 30-day V1 analytics.
  - Reopen a 13.1–13.3 implementation task only after its readiness evidence is documented in the punchlist or a release-readiness note with owner/date/decision.

- [x] **13.1 Vitals Trend Spotter V2 — real-time playback and richer charting**
  - Implemented as dependency-free SVG playback rather than Canvas or a charting library. This keeps the V1 static chart as the accessible fallback while adding Play/Pause/Replay controls and a visible playhead for incremental reveal.
  - `static/index.html` — added playback controls and live playback label.
  - `static/js/app.js` (`VitalsTrendGame`) — added replayable 2-4x-style incremental reveal, pause/replay controls, and cleanup when leaving/resetting the game.
  - `static/css/style.css` — added playback control and playhead styling.
  - Higher-complexity case authoring remains a future content task; the V2 interaction shell is complete.

- [x] **13.2 GCS Media V2 — visual and audio E/V/M findings**
  - Implemented optional approved-media rendering without adding unlicensed assets. Existing text/vignette prompts remain the primary fallback and no vignette is required to declare media.
  - `static/index.html` — added `gcs-media` container before vignette text.
  - `static/js/app.js` (`PedsGcsGame`) — renders approved `video`, `audio`, or `image_sequence` media only when `license_status: "approved"`, `prompt_quality_review: "pass"`, and `url` are present.
  - `static/css/style.css` — added responsive media card styling.
  - `static/data/games/peds_gcs_calculator/game.json` — media remains absent until licensed visual/audio assets are selected and approved; guardrail tests continue to block scoring-label leaks and unlicensed assets.

- [x] **13.3 DMIST Builder V2 — sequence scoring and reorder UI**
  - Implemented as an additive V2 layer after the V1 Include/Skip selection: learners order included handoff elements with accessible Up/Down controls, then submit sequence.
  - `app/database.py` / `app/models.py` — added nullable `sequence_data` JSONB column for additive storage; existing V1 records remain valid with null sequence data.
  - `app/main.py` / `app/minigame_results.py` — result contract accepts `sequence_data`; readiness analytics now report `handoff_sequence` counts.
  - `static/index.html` / `static/js/app.js` / `static/css/style.css` — added DMIST sequence panel, priority-band sequence scoring, sequence result capture, and `handoff_sequence` mistake tag for out-of-band ordering.

---

### Phase 14 — AHA BLS CPR Mastery Flow

- [x] **Author sequence and pair-match data**
  - `static/data/games/cpr_bls_sequence/cases.json` — 3 cases: adult single-rescuer, infant two-rescuer, EMS takeover.
  - `static/data/games/cpr_bls_concepts/game.json` — 3 rounds × 3 pairs: compression mechanics, C:V ratios, code quality metrics.
- [ ] **Author micro-scenario wrapper**
  - `drill_peds_cpr_mannequin.json` — lightweight text scenario triggering `cpr_challenge` in pediatric mode.
- [x] **Wire the 3-Round Gauntlet routing**
  - `cpr_bls_sequence` score ≥ 70 shows "Round 2: CPR Metrics →" button routing to `cpr_bls_concepts`.
  - `cpr_bls_concepts` score ≥ 70 shows "Round 3: Mannequin Drill →" button (shows "coming soon" toast until drill scenario is authored).
- [x] **Register metadata and reference card**
  - `cpr_bls_sequence` and `cpr_bls_concepts` registered in `app/minigame_metadata.py` with `ref_aha_cpr_guide` reference card (unlocks after both games passed).

---

### Dependencies and Sequencing Notes

- Phase 1 must complete before any Phase 2+ content ships. `mistake_tags` must be in the result contract before new cards go live, otherwise early play data is untagged and unrecoverable. ✓ **Complete.**
- Phase 1.3 (GCS to JSON) must complete before Phase 2.3 (GCS Socratic feedback). ✓ **Complete.**
- Phase 3 (History Maker V2) is independent of Phase 4 games but should not be delayed until after them. It is the highest-CE-impact item in the catalog. ✓ **Playable Interview Builder flow complete (3.1–3.4). Reference-card unlock gate remains Phase 6.3 infrastructure.**
- Phase 4 games can be implemented in any order relative to each other. ✓ **Complete.** `dev_flags`, `dmist_builder`, `protocol_pivot`, and `vitals_trend_spotter` are playable and wired.
- **Phase 5 complete.** Routing infrastructure is live. Next work: Phase 6 (static metadata registry, hints, reference cards, Priority 5 routing) and CE card tier authoring (prerequisite for 5.2 tier filtering).
- Phase 6 depends on Phase 5 being live (result records needed to test unlock conditions and routing) and Phase 2 content being authored (hint data requires authored cards). Phase 6.0 should land first because the metadata registry is the shared source for unlocks, routing, and frontend learning surfaces; 6.1–6.4 can proceed in parallel once 6.0 is stable enough to load.
- Phase 6 is the architectural gate for new CE surfaces that need hints, reference-card unlocks, or Priority 5 debrief routing. New games can be authored before Phase 6 completes, but should not be exposed broadly in production without Phase 6.0 metadata.
- **Phase 7 (quick wins) can continue immediately,** in parallel with Phase 6. No open-phase dependencies. Phase 7.1 is complete; Phase 7.2 (GCS incomplete-input protection) is a correctness fix and should not wait for Phase 6 infrastructure.
- **Phase 8 (speed-game review screen)** can begin immediately. Completing Phase 8 before Phase 9 is recommended: PAT and TEN-4 adaptive V2 modes (9.4, 9.6) require the review screen to deliver meaningful adaptive feedback between rounds.
- **Phase 9 (adaptive V2 modes)** depends on Phase 5.2 (proficiency endpoint — already live ✓). Content authoring for each game's adaptive cards can proceed in parallel with engine wiring. Phase 9.4 (TEN-4 documentation language) requires medical director review before production; track review status separately.
- **Phase 10 (mastery flow UI):** Task 10.1 (History Maker mastery flow) is blocked until Phase 3 (tasks 3.1–3.4) is complete. Tasks 10.2 (dev mastery flow) and 10.4 (reference card library) are unblocked now. Task 10.4 depends on Phase 6.3 (reference card backend).
- **Phase 11 (new map games, configuration-only)** can proceed as maps become playable. Adding a new `minigame_id` to `MINIGAME_METADATA` / `get_allowed_minigame_ids()`, static metadata from Phase 6.0, and routing is required before any result submission for that game can be accepted in production. Mistake-tag analytics will not flow until Phase 1 is confirmed for each new game ID.
- **Phase 12 complete.** Rule of Nines/PT1 gateway uses a functional body-map game and no longer auto-completes on map visit. Stop the Bleed, BLS Sequence, and Priority Stack share one `SequenceOrderGame` full-order commit/reveal engine with static metadata, learning pages, map wiring, and regression coverage.
- **Phase 13 complete.** Phase 13.0 readiness infrastructure, 13.1 Vitals SVG playback, 13.2 optional approved-media support for GCS, and 13.3 DMIST sequence scoring/capture are implemented. GCS media asset authoring remains gated by license/source approval; additional Vitals/DMIST content tuning should be driven by browser and learner analytics rather than new schema work.
