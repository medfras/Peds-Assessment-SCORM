---
name: resp_dx_1q frontend display score is intentional
description: Frontend computes a local score for UX display in resp_dx_1q; backend discards it and recomputes from case_evidence. This split is approved.
type: feedback
---

For `resp_dx_1q` (Differential Detective: Resp-Dx), the frontend computes a local `score/maxScore` and `acc%` for immediate UX feedback in the results panel. The backend ignores these values and recomputes the authoritative score from `case_evidence` via `_process_resp_dx_submission`.

**Why:** Backend authority is maintained for persistence and XP; frontend display score is acceptable as a non-authoritative UX convenience.

**How to apply:** Do not flag the frontend display score computation as a violation of backend-authority rules. The pattern is: frontend shows something immediately, backend stores something authoritative. The two can differ without issue as long as the backend never trusts the frontend-computed value for persistence.
