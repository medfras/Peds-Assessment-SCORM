# Mini-Games Phase 13 Browser E2E Checklist

Purpose: capture manual browser evidence for the Phase 13 readiness gates in `MINIGAMES_PHASE13_READINESS.md`.

This checklist does not authorize Phase 13.1-13.3 implementation by itself. Copy findings back into the readiness log with reviewer, device/browser, date, and recommendation.

## Vitals Trend Spotter V1 E2E

Game: `vitals_trend_spotter`

Required runs:

- [ ] Desktop browser run completed.
- [ ] Mobile browser run completed.

Cases to sample:

- [ ] `vt_sepsis_compensation_01`
- [ ] One respiratory deterioration case.
- [ ] One non-sepsis/non-respiratory case, if available in the deck.

Desktop checks:

- [ ] Game opens from Dog Park / mini-game catalog.
- [ ] SVG/static chart renders without clipping.
- [ ] Time axis and channel labels are readable.
- [ ] Learner can identify the deterioration window without animation.
- [ ] Etiology question renders after timeline selection.
- [ ] Response question renders after etiology selection.
- [ ] Feedback explains timeline cue, etiology, and response.
- [ ] Hint is available and does not reveal the answer.
- [ ] Result submission succeeds.

Mobile checks:

- [ ] Game screen scrolls normally.
- [ ] Chart remains readable without horizontal confusion.
- [ ] Tap targets are usable with thumb input.
- [ ] No fixed header/footer blocks the chart or answer controls.
- [ ] Result screen is reachable without layout overlap.

Decision prompts:

- Did the learner struggle because the chart was static, or because the clinical reasoning was hard?
- Would real-time playback solve an observed learning problem?
- Would animation make the game more realistic without making it slower or less accessible?
- Recommendation: keep static SVG, add SVG animation, use Canvas, use charting library, or defer V2.

## Pediatric GCS Text/Vignette E2E

Game: `peds_gcs_calculator`

Required runs:

- [ ] Desktop browser run completed after Phase 7.3 deck expansion.
- [ ] Mobile browser run completed after Phase 7.3 deck expansion.
- [ ] At least one infant vignette encountered and completed.
- [ ] At least one pediatric/non-infant vignette encountered and completed.

Desktop checks:

- [ ] Game opens from Dog Park / mini-game catalog.
- [ ] Vignette text is readable.
- [ ] Eye, verbal, and motor selectors require all components before submit.
- [ ] Total score updates correctly after selections.
- [ ] Incorrect submission shows component-level Socratic feedback.
- [ ] Hint is available and does not reveal the answer.
- [ ] Adaptive mode still works when proficiency conditions are met.
- [ ] Result submission succeeds.

Mobile checks:

- [ ] Selectors fit without horizontal scrolling.
- [ ] Tapping selectors is responsive.
- [ ] Submit button is reachable after selections.
- [ ] Feedback remains readable and scrollable.
- [ ] No media placeholder appears before Media V2 assets are authored.

Decision prompts:

- Is the base text/vignette calculator stable enough that media would add observation fidelity rather than hide unresolved UX/scoring issues?
- Which vignettes would benefit most from visual or audio media?
- Are any current vignette descriptions too answer-revealing and therefore poor candidates for media conversion?

