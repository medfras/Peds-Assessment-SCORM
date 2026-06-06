# Vitals Trend Spotter Charting Decision

Purpose: record the Phase 13.1 decision on whether `vitals_trend_spotter` should remain static SVG or move to SVG animation, Canvas, or a charting library.

Status: decision pending. Do not start V2 implementation until the desktop/mobile E2E evidence in `MINIGAMES_PHASE13_READINESS.md` is complete.

## Current V1

- Static SVG-style chart interaction.
- Learner identifies the earliest meaningful deterioration window.
- Learner answers etiology and immediate-response questions.
- Feedback explains the timeline cue, etiology, and response.

## Decision Inputs Required

- [ ] Desktop browser E2E feedback.
- [ ] Mobile browser E2E feedback.
- [ ] Evidence that learners can or cannot identify deterioration from the static chart.
- [ ] Evidence that animation would solve a learning problem rather than add novelty.
- [ ] Mobile performance and scroll/tap behavior observations.

## Accessibility Approach For Any V2 Charting Mode

Any animated or richer charting mode must preserve the static interpretation task and must not make animation the only way to access the clinical data.

Requirements:

- Keep a static chart or data-table fallback available.
- Respect `prefers-reduced-motion`; disable auto-play animation when reduced motion is requested.
- Provide pause/replay controls if any animation is used.
- Do not require reaction-time clicking during playback; learner scoring should remain based on clinical interpretation, not motor speed.
- Keep the deterioration window selectable through keyboard/tap controls.
- Preserve text feedback for timeline cue, etiology, and response.
- Ensure chart colors are not the only differentiator between channels; use labels, shapes, or line styles where practical.
- Maintain mobile readability without requiring horizontal panning for core tasks.

## Decision Record

| Field | Notes |
| --- | --- |
| Decision date | pending |
| Reviewer / owner | pending |
| Chosen approach | pending |
| Why this approach | pending |
| Alternatives rejected | pending |
| Mobile performance risk | pending |
| Accessibility / text fallback | Static/data-table fallback required; reduced-motion support required; pause/replay required for animation. |
| Maintenance risk | pending |
| Reopen implementation? | no |

