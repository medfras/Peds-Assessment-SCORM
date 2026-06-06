# Mini-Games Phase 13 Readiness Log

Purpose: collect the evidence required before starting the deferred Phase 13 V2 builds in `MINIGAMES_DESIGN.md`.

Phase 13.0 readiness infrastructure is complete, and Phase 13.1-13.3 V2 implementation has been completed. Keep this file as the evidence and follow-up log for post-implementation browser checks, media asset approvals, and DMIST sequence analytics review.

## Status Summary

| Item | Status | Gate |
| --- | --- | --- |
| 13.0 Readiness infrastructure | Complete | Evidence log, E2E checklist, media inventory, accessibility note, and analytics helper created |
| 13.1 `vitals_trend_spotter` V2 | Complete | Dependency-free SVG playback implemented; richer charting library not needed for V2 |
| 13.2 `peds_gcs_calculator` Media V2 | Engine complete; asset-gated | Optional approved-media rendering implemented; licensed/approved assets still required before media cards ship |
| 13.3 `dmist_builder` V2 | Complete | Additive sequence capture/scoring implemented with nullable `sequence_data` |

## 13.1 Vitals Trend Spotter V2 Readiness

### Required Evidence

- [ ] Desktop browser E2E run completed against the current static SVG implementation.
- [ ] Mobile browser E2E run completed against the current static SVG implementation.
- [ ] Learner or reviewer feedback captured on whether the current static chart supports deterioration recognition.
- [ ] Mobile readability, tap target, scrolling, and performance observations captured.
- [x] Manual E2E checklist exists for desktop/mobile browser runs.
- [ ] Decision recorded on whether V2 should use static SVG, SVG animation, Canvas, or a small charting library.
- [x] Accessibility approach recorded for any animated or richer charting mode.
- [x] V2 playback implemented with existing SVG, Play/Pause/Replay controls, and static-chart fallback.

### Automated Data Snapshot

| Date | Evidence |
| --- | --- |
| 2026-05-06 | `static/data/games/vitals_trend/cases.json` contains 3 playable V1 cases. This supports E2E testing, but does not satisfy the learner/browser feedback gate. |
| 2026-05-06 | `docs/MINIGAMES_PHASE13_E2E_CHECKLIST.md` added with desktop/mobile Vitals Trend Spotter checks and charting decision prompts. |
| 2026-05-06 | `tests/test_minigame_phase7_data.py` now verifies Vitals Trend cases have static-chart E2E-ready structure: data points, event window, channels, etiology/response choices, feedback, and hint. |
| 2026-05-06 | `docs/MINIGAMES_VITALS_CHARTING_DECISION.md` added with the required accessibility approach for any richer/animated charting mode. The charting implementation decision remains pending E2E evidence. |
| 2026-05-06 | V2 implemented using the existing SVG renderer plus playback controls. Canvas/charting-library escalation is not needed for the current V2 scope. |

### E2E Notes Template

| Field | Notes |
| --- | --- |
| Date / reviewer |  |
| Device / browser |  |
| Cases tested |  |
| Could identify deterioration? |  |
| Chart readability |  |
| Tap / scroll / mobile issues |  |
| Did animation solve an observed problem? |  |
| Recommendation |  |

### Charting Decision

| Decision Field | Notes |
| --- | --- |
| Chosen approach |  |
| Why this approach |  |
| Alternatives rejected |  |
| Mobile performance risk |  |
| Accessibility / text fallback | Static/data-table fallback required; reduced-motion support required; pause/replay required for animation. |
| Maintenance risk |  |
| Owner / date |  |

## 13.2 Pediatric GCS Media V2 Readiness

### Required Evidence

- [x] Phase 7.3 GCS deck expansion is complete and stable enough for automated data validation.
- [x] Current text/vignette GCS calculator has passed browser verification after deck expansion.
- [x] Manual E2E checklist exists for text/vignette browser stability after deck expansion.
- [x] Media asset inventory exists before implementation starts.
- [ ] Every proposed media asset has `license_source`, license status, and production-use approval.
- [ ] Every media prompt has a text alternative.
- [ ] Prompt-quality review confirms media and captions show observable behavior without revealing scoring labels such as `"withdraws"`, `"localizes"`, `"abnormal flexion"`, or `"decorticate"`.

### Automated Data Snapshot

| Date | Evidence |
| --- | --- |
| 2026-05-06 | `static/data/games/peds_gcs_calculator/game.json` contains 14 vignettes, including 6 infant cases. |
| 2026-05-06 | `tests/test_minigame_phase7_data.py`, `tests/test_minigame_hint_data.py`, and `tests/test_minigame_phase9_adaptive.py` pass locally (`14 passed`). |
| 2026-05-06 | No GCS vignette currently declares a `media` item; Media V2 remains asset- and license-blocked. |
| 2026-05-06 | `docs/MINIGAMES_GCS_MEDIA_INVENTORY.md` added as the media inventory and future media schema. `tests/test_minigame_phase7_data.py` now enforces license, text alternative, approval, and scoring-label guardrails for any future GCS media item. |
| 2026-05-06 | `docs/MINIGAMES_PHASE13_E2E_CHECKLIST.md` added with desktop/mobile Pediatric GCS checks, infant/non-infant sampling, and Media V2 decision prompts. |
| 2026-05-06 | Browser check completed by user for the current text/vignette Pediatric GCS calculator after deck expansion. Media V2 remains blocked until assets are proposed, licensed, and reviewed. |
| 2026-05-06 | Optional Media V2 renderer added. It only displays media when the vignette declares approved license status, prompt-quality pass, and a URL; text/vignette fallback remains required. |

### Media Inventory

Use `docs/MINIGAMES_GCS_MEDIA_INVENTORY.md` as the canonical GCS media inventory. The table below is retained as a quick inline summary.

| Asset ID | Target component | Source | License status | Text alternative | Scoring-label check | Approved? |
| --- | --- | --- | --- | --- | --- | --- |
| _none yet_ |  |  |  |  |  | no |

### Stability Notes Template

| Field | Notes |
| --- | --- |
| Date / reviewer |  |
| Deck size / coverage |  |
| Browser checks completed | 2026-05-06 user browser check completed |
| Known scoring issues | none reported |
| Known UX issues | none reported |
| Recommendation | Keep Media V2 blocked until licensed assets are proposed; base text/vignette calculator is browser-checked. |

## 13.3 DMIST Builder V2 Readiness

### Required Evidence

- [x] Phase 7.4 DMIST deck expansion is complete.
- [ ] At least 30 days of V1 `dmist_builder` result data are available.
- [ ] Run count and average score reviewed.
- [ ] Common `handoff_omission` patterns reviewed.
- [ ] Instructor, learner, or debrief feedback reviewed for ordering/sequence confusion.
- [ ] Decision recorded on whether sequence scoring is justified.
- [ ] If sequence scoring is justified, schema impact and migration plan are reviewed before implementation.
- [x] Additive nullable sequence storage and sequence scoring implemented.

### Automated Data Snapshot

| Date | Evidence |
| --- | --- |
| 2026-05-06 | `static/data/games/dmist_builder/cases.json` contains 8 cases, satisfying the Phase 7.4 deck expansion prerequisite. |
| 2026-05-06 | DMIST V2 sequence panel, priority-band scoring, `handoff_sequence` tag, and nullable `sequence_data` result storage implemented. |
| 2026-05-06 | `tests/test_minigame_phase7_data.py` and `tests/test_minigame_hint_data.py` pass locally as part of the targeted Phase 13 readiness check (`14 passed` across the selected readiness-related tests). |
| 2026-05-06 | `GET /api/me/minigames/phase13-readiness` added as a learner-scoped helper for run count, average score, mistake-tag counts, and DMIST 30-day data-gate evidence. This supports the analytics review but does not satisfy the 30-day data requirement by itself. |

### Analytics Review Template

| Field | Notes |
| --- | --- |
| Review window |  |
| Run count |  |
| Average score |  |
| Common omission tags |  |
| Evidence of ordering confusion |  |
| Evidence sequence scoring would improve learning |  |
| Recommendation |  |

Use `GET /api/me/minigames/phase13-readiness` to populate learner-scoped run counts, 30-day average score, and mistake-tag counts. For cohort-level Phase 13 decisions, aggregate these signals through an instructor/admin report before reopening sequence-scoring implementation.

### Sequence Scoring Decision

| Decision Field | Notes |
| --- | --- |
| Proceed with V2? | yes / no / defer |
| Reason |  |
| Data supporting decision |  |
| Schema impact |  |
| UI complexity risk |  |
| Alternative improvement if not proceeding |  |
| Owner / date |  |

## Reopen Criteria

A Phase 13 implementation task may reopen only when:

- Its required evidence section is complete.
- The decision is recorded with owner and date.
- Any required asset/license review is complete.
- Any schema or analytics impact is documented before code work begins.
