# CLAUDE.md

This file is the repo-level operating guide for Claude-based coding agents working in this project.

It is intentionally short. It does not replace the canonical standards and design docs. Use it as the startup guide, then consult the referenced docs before planning or editing.

## Project Purpose

EMS Simulator is being built as a production-ready, publicly deployable SaaS training platform for EMS education.

Primary engineering goals:
- maintainable, scalable code
- safe multi-tenant operation
- deterministic scoring and auditability where correctness matters
- clear architectural boundaries between simulation state, UI display, and LLM-generated content
- production-readiness over prototype shortcuts

## Canonical Docs

Read these before making substantial changes:

- Standards and engineering policy: [docs/DEVELOPMENT_GUIDELINES.md](docs/DEVELOPMENT_GUIDELINES.md)
- System direction and target architecture: [docs/HIGH_LEVEL_DESIGN.md](docs/HIGH_LEVEL_DESIGN.md)
- AI behavior, prompting, and authority boundaries: [docs/AI_ARCHITECTURE.md](docs/AI_ARCHITECTURE.md)
- Scenario runtime and debrief behavior: [docs/SCENARIO_ENGINE_ARCHITECTURE.md](docs/SCENARIO_ENGINE_ARCHITECTURE.md)
- Debrief scoring authority and evidence packet architecture (current): [docs/SCENARIO_EVALUATION_ARCHITECTURE.md](docs/SCENARIO_EVALUATION_ARCHITECTURE.md)
- Unified checklist scoring engine (target architecture): [docs/SCORING_ENGINE_ARCHITECTURE.md](docs/SCORING_ENGINE_ARCHITECTURE.md)
- Multi-tenant protocol and MCA architecture: [docs/multi_tenant_protocol_architecture.md](docs/multi_tenant_protocol_architecture.md)
- SaaS Hardening and production readiness plan: [docs/SAAS_HARDENING_PLAN.md](docs/SAAS_HARDENING_PLAN.md)
- Scenario authoring contract: [docs/SCENARIO_DESIGN_EMS.md](docs/SCENARIO_DESIGN_EMS.md)
- Shared rubric scaffold for new scenarios: [docs/rubric_templates/ems_standard_v1.md](docs/rubric_templates/ems_standard_v1.md)
- UI style guide and theming: [docs/STYLE_GUIDE.md](docs/STYLE_GUIDE.md)
- Immersive mode layout and components: [docs/IMMERSIVE_MODE_DESIGN.md](docs/IMMERSIVE_MODE_DESIGN.md)
- CPR Challenge mechanics and scoring: [docs/CPR_CHALLENGE_DESIGN.md](docs/CPR_CHALLENGE_DESIGN.md)
- Mini-games design and mechanics: [docs/MINIGAMES_DESIGN.md](docs/MINIGAMES_DESIGN.md)
- Gamification and rewards rules: [docs/REWARDS.md](docs/REWARDS.md)
- Pediatric map progression design: [docs/PEDIATRIC_MAP_DESIGN.md](docs/PEDIATRIC_MAP_DESIGN.md)
- Map gameplay and navigation rules: [docs/MAP_GAMEPLAY_DESIGN.md](docs/MAP_GAMEPLAY_DESIGN.md)
- Open issues and planned work: [docs/PUNCHLIST.md](docs/PUNCHLIST.md)
- GBL principles, instructional design rules, and improvement roadmap: [docs/LEARNING_DESIGN.md](docs/LEARNING_DESIGN.md)
- Product improvement direction and near-term product loop priorities: [docs/PRODUCT_IMPROVEMENT_DIRECTION.md](docs/PRODUCT_IMPROVEMENT_DIRECTION.md)
- Phased implementation checklist (learning system features): [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)

## How To Use The Docs

- Use `DEVELOPMENT_GUIDELINES.md` as the standards source of truth.
- Use `HIGH_LEVEL_DESIGN.md` for platform-level architectural direction.
- Use subsystem docs for implementation-specific constraints.
- If a change affects a cross-cutting rule, update the canonical doc instead of inventing a local convention.
- If a change is feature-specific or subsystem-specific, document it in the relevant design doc, not here.

## Non-Negotiable Rules

- Backend state is authoritative. Frontend-derived UI state and model tags are never the source of truth for scoring, persistence, or readiness.
- Deterministic logic must stay deterministic. Do not move arithmetic, scope enforcement, session authority, or other authoritative rules into LLM judgment.
- Treat all model output and user content as untrusted.
- Enforce tenant boundaries and authorization server-side.
- Prefer additive, migration-safe schema changes.
- Prefer additive, migration-safe schema changes managed via Alembic.
- Enforce auth securely using HttpOnly cookies and CSRF tokens; never store JWTs in localStorage.
- Do not silently degrade when authoritative structured data is missing; fail loudly or surface a clear diagnostic.
- Keep scenario content aligned with the scenario authoring contract and vocabulary rules.
- Keep the deterministic scoring engine strictly decoupled from simulator-specific gamification (XP, treats, maps) and hardcoded EMS-only concepts to maintain Enterprise QA/QI portability and Fire/Rescue extensibility.

## Scenario Authoring Rules

- New scenarios must follow [docs/SCENARIO_DESIGN_EMS.md](docs/SCENARIO_DESIGN_EMS.md).
- Use stable vocabulary IDs, not brittle display strings, wherever the schema requires them.
- Use [docs/rubric_templates/ems_standard_v1.md](docs/rubric_templates/ems_standard_v1.md) as an authoring scaffold, not as permission to over-template clinically specific content.
- Do not author new scenarios that depend on transitional tag-derived findings as authoritative scoring truth.
- If a scenario depends on architecture that is explicitly transitional or deferred, stop and document the dependency before proceeding.

## Coding Expectations

- Keep business logic out of route handlers when practical.
- Prefer clear service/helper boundaries over growing monolithic files further.
- Do not add new routes or Pydantic models to `main.py`; use the `app/routers/` and `app/schemas.py` modular structure.
- Preserve backward compatibility intentionally; remove deprecated paths only when the contract is clearly ready.
- Add or update regression tests for bug fixes when practical.
- For production-impacting behavior, prefer explicit validation and observability over “best effort” silent fallback.

## Review And Verification

- Before finishing, verify the change against the relevant canonical docs.
- If tests exist for the affected area, run them.
- If a change cannot be fully verified, say so clearly.
- Surface architectural conflicts, standards drift, and hidden coupling rather than working around them silently.

## When To Escalate

Pause and call out the issue before proceeding if:
- the request conflicts with `DEVELOPMENT_GUIDELINES.md`
- the change would make the frontend or LLM more authoritative than the backend
- the scenario contract and runtime behavior disagree
- a requested shortcut would reduce production readiness, security, or auditability
- a new scenario requires architecture that the docs mark as deferred or transitional

## Scope Of This File

Keep this file concise and operational.

Do not turn `CLAUDE.md` into:
- a duplicate of the architecture docs
- a feature-specific implementation notebook
- a long procedural manual

If guidance here becomes detailed, move that detail into the canonical doc and keep this file as the pointer and summary.
