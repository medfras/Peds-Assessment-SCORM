---
name: A&O LLM Current-Events Issue
description: LLMs cannot accurately answer current-events A&O questions (president, holidays, date) and could mislead students about orientation scores
type: project
---

LLMs cannot accurately answer patient A&O current-events questions.

**Why:** When simulated patients are asked common A&O IV orientation probes — "Who is the president?", "What day is it?", "What holiday did we have recently?" — the LLM persona cannot accurately answer these (knowledge cutoff, date unawareness). A wrong or hallucinated answer could mislead the student into scoring the patient as disoriented when they are oriented, or vice versa.

**How to apply:** Before adding or expanding A&O IV assessment scenarios, decide on a handling strategy: (1) hardcode authored responses for common A&O probes in the persona's `lexi_guardrails` or `patient_responses`, (2) instruct the LLM to give a plausible in-character response that does not claim to know real current events (e.g., "I think it's… something in the fall?"), or (3) flag these question types so the UI or Lexi can remind the student that current-events answers are patient-dependent and not autoscored. Do NOT leave the LLM to answer these questions without guardrails.
