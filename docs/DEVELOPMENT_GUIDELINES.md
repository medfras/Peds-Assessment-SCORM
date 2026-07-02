# Development Guidelines & AI Agent Context

**Project:** RescueTrails EMS Simulator  
**Audience:** Human developers and AI coding agents  
**Purpose:** Durable engineering context for planning, implementation, review, and refactoring  
**Status:** Active

This document defines the project-level standards, guardrails, and expectations that apply to all code changes in the RescueTrails codebase. It is intentionally focused on durable policy and implementation standards rather than low-level subsystem design. Detailed technical architecture, data models, and feature-specific behavior belong in separate design documents.

---

## 1. Project Objectives

RescueTrails is being built as a publicly deployable, multi-tenant SaaS application for EMS education and simulation. Contributions must support the following engineering goals:

- **Production readiness:** Code should be safe to deploy publicly, observable in production, and resilient under failure.
- **Clinical determinism:** Clinical truth, scoring inputs, and scope enforcement must be backend-authoritative and auditable.
- **Maintainability:** Changes should improve or preserve clarity, cohesion, and long-term ease of modification.
- **Scalability:** New agencies, protocols, scenarios, and users must be supportable without ad hoc architectural drift.
- **Tenant safety:** Agency data, permissions, and analytics must remain isolated and enforceable.
- **Operational durability:** Changes should be testable, backward-compatible when feasible, and safe to migrate incrementally.

When a local implementation convenience conflicts with one of these objectives, the objective wins.

---

## 2. Scope of This Document

This file is the **project standards and execution policy** document. It should answer:

- What must always remain true about the system?
- What coding standards and change-management rules apply to all work?
- What should AI agents optimize for when planning and implementing changes?

This file should **not** become the primary home for:

- feature-specific technical designs
- endpoint-by-endpoint behavior
- low-level schema detail
- prompt bodies
- provider-specific SDK mechanics

Those belong in architecture and design docs such as `HIGH_LEVEL_DESIGN.md`, `SCENARIO_ENGINE_ARCHITECTURE.MD`, `AI_ARCHITECTURE.md`, and future feature-specific design files.

---

## 3. Core Architectural Mandates

### 3.1 Clinical Determinism Over AI Generation

- **DO NOT** use the LLM to generate or maintain authoritative clinical truth such as vital signs, disease progression, protocol rules, scope limits, or final scoring math.
- **DO** keep backend state engines, protocol logic, and persisted intervention records as the source of truth.
- **DO** treat AI as a narrative, coaching, and evaluation assistant that reads authoritative state but does not define it.
- **DO** use structured machine-consumed outputs (JSON envelopes, not text scraping) for any authoritative AI result the system needs to parse, validate, persist, or score against.
- **DO NOT** rely on brittle text formatting assumptions for critical data extraction.

### 3.2 UI Boundary vs Authoritative State

- **DO NOT** allow client-side parsing, UI helpers, or AI text tags to mutate authoritative simulation state, scoring, permissions, or readiness gates.
- **DO** treat frontend tag parsing and UI enrichment as advisory presentation behavior unless the backend separately confirms and persists the same information through an explicit contract.
- **DO** route all authoritative state changes through explicit backend write paths (POST endpoints, not SSE tag side-effects).

### 3.3 Event Ordering and Concurrency

- **DO NOT** assume REST, SSE, WebSocket, and background work execute in the order the user experiences them.
- **DO** define and preserve causal ordering for state-mutating actions.
- **DO** use `SELECT ... FOR UPDATE` (`with_for_update()` in SQLAlchemy) on the `SimSession` row for any endpoint that reads-then-writes authoritative session state (chat, interventions, treatment submission). This is the project's approved concurrency control for session mutations.
- **DO** design state transitions to be idempotent or conflict-aware where practical. Use `ON CONFLICT DO NOTHING` or `ON CONFLICT DO UPDATE` rather than SELECT-then-INSERT two-step patterns.

### 3.4 Immutability and Auditability

- **DO NOT** overwrite historical outcomes when upstream rules, prompts, or protocols change.
- **DO** preserve immutable historical records for debriefs, scoring context, and protocol snapshots.
- **DO** model corrections, appeals, and revocations as append-only adjudication or supersession records (see `AdjudicatedOutcome`).
- **DO** favor designs that preserve historical truth and explainability over convenience.

### 3.5 Multi-Tenant Isolation

- **DO NOT** assume object ownership from a raw user identifier alone.
- **DO** enforce agency/tenant boundaries on every read and write path that touches tenant-owned data.
- **DO** require explicit role validation for privileged or configuration-changing operations. Use `get_instructor_context` or `get_admin_context` dependencies — never bypass them with manual role checks.
- **DO** design new features so tenant isolation remains enforceable in both the database layer and the application layer.

### 3.6 Enterprise QA/QI Portability
- **DO NOT** couple the core deterministic scoring engine (`scoring_service.py`) to simulator-specific concepts like `scenario.json`, XP, treats, or map nodes.
- **DO** ensure the scoring engine accepts only generic evidence models (`SessionEvent`, `Intervention`, `ChatMessage`, `ChecklistItem`) so it can later accept translated real-world ePCR data (NEMSIS).
- **DO** map new entries in `vocabulary.INTERVENTION_ACTIONS` and `vocabulary.CLINICAL_CONCEPTS` to standard EMS ontologies (e.g., NEMSIS eProcedures, eMedications, ICD-10) conceptually, avoiding game-only terminology in the clinical vocabulary.
- **DO NOT** let gamification logic bleed into `evidence_packet` generation. Gamification wraps the evaluation; it does not participate in it.

### 3.7 Multi-Domain (Fire/Rescue) Extensibility
- **DO NOT** hardcode EMS-specific assumptions (like the guaranteed presence of a "patient" or "Medical Control") into core engine data structures. Fire, Hazmat, and Technical Rescue incidents may focus on incident command, hazard mitigation, or structure status.
- **DO** treat the scoring engine as a generic compliance and sequence evaluator. It must evaluate `ChecklistItem` satisfaction against timeline events regardless of whether the domain is clinical medicine or fire suppression.
- **DO** plan for dual-ontology ingestion in the future QA/QI platform. EMS data will arrive via NEMSIS standards; Fire data will arrive via NFIRS or NERIS. The ingestion layer must map both into our unified generic evidence models (`SessionEvent`, `Action/Intervention`, `Finding`).
- **DO** namespace vocabulary additions. Keep `vocabulary.py` organized so that EMS terms (`INTERVENTION_ACTIONS`) and future Fire/Rescue terms (e.g., `TACTICAL_ACTIONS` or `INCIDENT_BENCHMARKS`) do not improperly collide, ensuring clean domain-specific tree-shaking.
- **DO NOT** use "provider level" interchangeably with "role" across the codebase. EMS uses rigid licensure levels (EMT, Paramedic). Fire/Rescue relies heavily on dynamic incident roles (Incident Commander, Safety Officer, Entry Team) and specialized qualifications (Hazmat Tech).

---

## 4. Production Readiness Standards

### 4.1 Testing and Verification

- **DO** run the automated test suite when changes could affect covered behavior. The project standard test harness is Python 3.10+ with `pytest`.
- **DO** add or update automated tests for bug fixes, regressions, critical-path logic, authorization rules, scoring behavior, and other business rules where practical.
- **DO** manually verify the golden path and important edge cases when automated coverage is missing or incomplete.
- **DO** run syntax validation on modified Python files when a full automated run is not possible.
- **DO** call out residual risk explicitly when a change cannot be fully verified — name the specific scenario that is not covered and why.
- **DO NOT** claim a change is verified when only a syntax check or spot check was run. Distinguish what was checked from what was assumed.

### 4.2 Database and Migration Safety

- **DO NOT** make destructive schema changes by default.
- **DO** use Alembic for all schema migrations. Generate revisions using `alembic revision --autogenerate` and apply them via deployment runbooks.
- **DO NOT** use the `init_db()` `ALTER TABLE` pattern in `app/database.py` for schema evolution.
- **DO** account for existing data when adding constraints: dedup rows before creating unique indexes, use `DO $$...$$` blocks to safely drop old constraint variants before creating replacements.
- **DO** preserve existing data unless removal is explicitly approved and operationally safe.

### 4.3 Observability and Diagnostics

- **DO** use `structlog` (`from app.logging_config import get_logger`) for all server-side logging. Do not use `print()` or the stdlib `logging` module directly.
- **DO** emit structured log events for state changes, failures, and privileged actions using `log.info(...)`, `log.warning(...)`, `log.exception(...)` with keyword arguments as fields.
- **DO NOT** log secrets, raw tokens, full prompts, or tenant-sensitive free-text in production log events.
- **DO** make error paths diagnosable: include the operation name, relevant IDs, and the failure reason in log events.
- **DO** preserve audit-relevant traces for grading, protocol, and authorization-sensitive actions.
- **DO** configure error tracking (e.g., Sentry) with strict PHI scrubbing hooks (`before_send`) to ensure free-text medical narratives, chat logs, and LLM prompts/outputs never reach third-party exception trackers.

### 4.4 Configuration and Secrets

- **DO NOT** hardcode secrets, environment-specific settings, or production credentials. All configuration lives in `app/config.py` as Pydantic `Settings` fields sourced from environment variables.
- **DO** add new configuration values to `Settings` with sensible defaults and document the purpose.
- **DO** design features so local development, test, and production can run with distinct settings.

### 4.5 API and Contract Stability

- **DO NOT** casually break internal or external contracts used by the frontend, background workers, or integrations.
- **DO** maintain compatibility or provide an explicit migration path when changing payload shapes, persistence assumptions, or agent-visible contracts.
- **DO** keep machine-consumed interfaces explicit. Prefer typed Pydantic request/response models over raw `dict` returns for any endpoint that the frontend or a downstream system depends on.

### 4.6 Performance and Reliability

- **DO NOT** introduce avoidable latency or query-count regressions in hot paths such as session startup, chat streaming, vitals updates, debrief generation, and dashboard loading.
- **DO** think about timeouts, retries, duplicate prevention, and degraded behavior when integrating with LLMs, background tasks, and real-time transports.
- **DO** make failure behavior safe: partial outages and upstream failures must degrade predictably rather than corrupting state or producing duplicate authoritative writes.

### 4.7 Dependency and Supply-Chain Hygiene

- **DO NOT** add new dependencies casually when existing project tooling can solve the problem cleanly.
- **DO** prefer well-maintained libraries with clear operational value and predictable maintenance.
- **DO** evaluate new dependencies for security posture, maintenance risk, runtime cost, and long-term lock-in.
- **DO NOT** introduce libraries that obscure critical business logic or weaken security review without explicit justification.

---

## 5. Security Standards

### 5.1 Authentication and Authorization

- **DO NOT** implement ad hoc role checks inline in route handlers. Use the established FastAPI dependency chain: `get_current_user` → `get_active_context` → `get_instructor_context` / `get_admin_context`.
- **DO** validate that every resource access confirms tenant ownership in addition to authentication. Ownership is confirmed when `session.user_id == ctx.user_id` and `session.agency_id == ctx.agency_id`.
- **DO NOT** use base JWTs (no locked agency context) for any endpoint that touches tenant-specific data. Active context tokens are required.
- **DO** use `get_instructor_context` for any endpoint that reads another user's data or writes scoring/adjudication records.
- **DO** use `HttpOnly; Secure; SameSite=Strict` cookies for session management alongside double-submit signed CSRF tokens.
- **DO NOT** store JWTs in `localStorage` or pass WebSocket tokens via URL query parameters.

### 5.2 Input Sanitization and Injection Prevention

- **DO** truncate all free-text user inputs before forwarding to the LLM. Apply the project's approved truncation limits (see `AI_ARCHITECTURE.md`).
- **DO NOT** construct SQL queries by string interpolation. Use SQLAlchemy ORM expressions exclusively.
- **DO NOT** inject raw user content into HTML or JavaScript. Escape or use safe DOM APIs in the frontend.
- **DO** treat all LLM-generated text as untrusted when it enters an HTML context.

### 5.3 Rate Limiting

- **DO** apply `@limiter.limit(...)` to every new public-facing endpoint. Choose the appropriate rate category: `settings.rate_limit_chat` for LLM-calling endpoints, lower limits for write endpoints, standard limits for read endpoints.
- **DO NOT** add endpoints without rate limiting under the assumption that they are "internal only."

### 5.4 Secrets and Data Exposure

- **DO NOT** return internal IDs, stack traces, or raw exception messages to the client. Surface safe user-facing messages and log the detail server-side.
- **DO NOT** include full prompt bodies, agency config blobs, or other configuration details in API error responses.

### 5.5 Vulnerability Prevention

- **DO NOT** trade away basic security practices for speed of implementation.
- **DO** design with least privilege, explicit validation, safe defaults, and defense in depth.
- **DO** treat broken access control, insecure direct object references, injection, XSS, secret leakage, and cross-tenant data exposure as high-severity risks.
- **DO** review security-sensitive changes with extra scrutiny, especially anything affecting auth, tenant isolation, grading integrity, protocol management, or privileged settings.

---

## 6. Backend Standards (Python / FastAPI / SQLAlchemy)

### 6.1 Approved Tech Stack

The following are the project's established libraries and versions. Do not introduce alternatives without explicit approval:

| Concern | Library / Pattern |
|---|---|
| Web framework | FastAPI (async) |
| Database ORM | SQLAlchemy 2.0 AsyncIO (`async_session_factory`, `AsyncSession`) |
| Database | PostgreSQL via `asyncpg` |
| Schema migrations | `init_db()` in `app/database.py` — additive SQL via `text()` |
| Request validation | Pydantic v2 (`BaseModel`) |
| Auth tokens | PyJWT (`jwt`) |
| Structured logging | `structlog` via `app/logging_config.py` |
| Rate limiting | `slowapi` |
| LLM inference | Groq async SDK (`AsyncGroq`) |
| Password hashing | `passlib` (`CryptContext`) |
| Retry logic | `tenacity` (`_groq_retry` decorator in `ai_client.py`) |
| Frontend | Vanilla JS (ES6+), Tailwind CSS — no build step, no framework |
| Real-time | SSE for chat streaming, WebSockets for vitals and multiplayer |

### 6.2 Async and I/O Discipline

- **DO NOT** block the async request path with synchronous I/O, `time.sleep()`, or CPU-bound loops.
- **DO** use `await` consistently. Never call async functions without `await`.
- **DO** keep latency-sensitive paths (chat, vitals) predictable and bounded.

### 6.3 SQLAlchemy Patterns

- **DO** use `select(Model).where(...)` with `await db.execute(...)` — the SQLAlchemy 2.0 async style. Do not use legacy `session.query(...)`.
- **DO** use `lazy="selectin"` for relationships that are always needed in endpoint responses. Avoid `lazy="dynamic"` or implicit lazy-loading that fails in async contexts.
- **DO** call `flag_modified(obj, "field_name")` after mutating a JSONB column in place, so SQLAlchemy tracks the change.
- **DO** use `expire_on_commit=False` (already set on `async_session_factory`) — do not re-configure session factories locally.
- **DO** use `with_for_update()` when loading a row that will be mutated in the same transaction and concurrent writes on the same row are possible.
- **DO** use `pg_insert(Model).values(...).on_conflict_do_update(...)` or `.on_conflict_do_nothing()` for upsert patterns — never SELECT-then-INSERT.

### 6.4 Module Ownership

Each module has a clear responsibility boundary. Place new code in the correct module:

| Module | Owns |
|---|---|
| `app/main.py` | Application lifespan, middleware, CORS, background task wiring, and top-level router inclusion |
| `app/routers/*.py` | Grouped FastAPI route handlers by domain (auth, sessions, scenarios, etc.) |
| `app/schemas.py` | Pydantic request and response models |
| `app/models.py` | SQLAlchemy ORM models and relationships |
| `app/database.py` | Engine setup and session factory |
| `alembic/versions/` | Versioned schema migration scripts |
| `app/ai_client.py` | All Groq API calls, prompt assembly, response parsing |
| `app/scenario_engine.py` | Scenario loading, adaptation, and listing |
| `app/scoring_service.py` | Deterministic checklist evaluation, core math, and evidence packet generation |
| `app/clinical_data.py` | Agency config loading and caching |
| `app/config.py` | Application settings (Pydantic `Settings`) |

- **DO NOT** put business logic that belongs in a service module directly into route handler bodies if it exceeds ~20 lines of non-glue code.
- **DO NOT** put Groq calls, prompt strings, or LLM response parsing in `main.py`. That logic belongs in `app/ai_client.py`.
- **DO NOT** add new route handlers to `main.py`. Place them in the appropriate domain router under `app/routers/`.
- **DO NOT** use `init_db()` for schema evolution. All schema migrations must use Alembic.
- **DO NOT** import `scenario_engine.py` into `scoring_service.py`. The scoring service must remain agnostic to how the clinical expectations were authored.

### 6.5 Error Handling

- **DO NOT** swallow exceptions in critical paths without a clearly documented safety reason.
- **DO** return appropriate HTTP status codes: 400 for invalid input, 403 for authorization failures, 404 for missing resources, 409 for state conflicts, 503 for upstream (LLM) failures.
- **DO** surface state conflicts, authorization failures, and invalid inputs clearly with actionable `detail` messages.
- **DO NOT** re-raise raw upstream exceptions to the client. Wrap Groq errors in a 503 with a safe message.

---

## 7. Frontend Standards (Vanilla JS / Tailwind CSS)

### 7.1 State Management

- **DO NOT** scatter authoritative UI state across unrelated globals or DOM-derived assumptions.
- **DO** keep session-related frontend state in the `state` object and intentionally reset it on scenario exit, retry, or teardown.
- **DO** treat `state` as the UI source of truth, not the DOM.
- **DO NOT** use frontend-assembled lists (e.g., `state.detectedTreatmentLabels`) as authoritative inputs to backend scoring. The backend derives authoritative lists from DB records.

### 7.2 DOM Safety and Rendering Discipline

- **DO NOT** inject raw user or model content into the DOM via `innerHTML` without sanitization.
- **DO** escape or safely render all untrusted dynamic text.
- **DO** prefer explicit DOM construction when interaction complexity or event lifecycle makes string assembly error-prone.

### 7.3 Real-Time Resilience

- **DO NOT** assume SSE streams and WebSockets are perfectly reliable.
- **DO** handle disconnects, retries, and partial responses gracefully.
- **DO** design chat, vitals, and coaching flows so temporary transport failures do not corrupt `state`.

#### Canonical SSE read loop pattern

All streaming chat readers (`/api/chat`, `/api/lexi`, `/api/coach`) must use this pattern. The `if (done) break` early-exit pattern is a known bug — it exits the loop before flushing the TextDecoder's internal buffer, silently dropping the final content chunk and any tag that arrived in the same read as the stream end.

```javascript
const decoder = new TextDecoder();
let buffer = "";
let doneSeen = false;

while (true) {
  const { done, value } = await reader.read();
  if (done) {
    buffer += decoder.decode();           // flush TextDecoder internal buffer
  } else {
    buffer += decoder.decode(value, { stream: true });
  }

  const lines = buffer.split("\n");
  buffer = done ? "" : lines.pop();       // keep partial line for next iteration

  const dataLines = done
    ? _extractSseDataLines(lines.join("\n"))   // recovery pass on final buffer
    : lines.map(l => l.trim()).filter(l => l.startsWith("data: ")).map(l => l.slice(6));

  for (const data of dataLines) {
    if (data === "[DONE]") {
      doneSeen = true;
      // ... finalize display, parse tags ...
      break;
    }
    try {
      const parsed = JSON.parse(data);
      if (parsed.text) { /* accumulate */ }
    } catch { /* ignore non-JSON lines */ }
  }

  if (done || doneSeen) break;
}
```

Required invariants:
- **Decoder flush on `done`:** `decoder.decode()` (no args) flushes any multi-byte sequence held in the decoder's internal state. Skipping this can corrupt UTF-8 characters split across two reads.
- **`_extractSseDataLines` recovery pass:** When `done` is true and `[DONE]` was never seen in the normal flow, this utility does a final scan of the remaining buffer to recover any `data:` lines that were not terminated with `\n` before the stream closed.
- **`doneSeen` flag:** Allows clean exit without depending on the transport `done` signal — guards against streams that close without sending `[DONE]`.
- **`buffer = done ? "" : lines.pop()`:** Preserves partial lines across reads in the normal path; discards on final flush so nothing is double-processed.

### 7.4 Responsive and Accessible UI

- **DO NOT** treat mobile support as an afterthought.
- **DO** preserve the intended desktop/mobile interaction model.
- **DO** keep contrast, readability, tap targets, and keyboard/focus behavior acceptable for production UI.

---

## 8. AI Integration Standards

### 8.1 Prompt Assembly and Context Management

- **DO NOT** forward raw chat history into prompts without structure, limits, or purpose.
- **DO** apply the project's approved truncation limits before any user content reaches the LLM.
- **DO** distinguish between authoritative structured context (protocol data, DB-backed intervention records, pre-computed scoring blocks) and qualitative conversational context (transcript excerpts). Feed both in clearly labeled sections.

### 8.2 Prompt Injection and Trust Boundaries

- **DO NOT** treat prompt text alone as a sufficient security boundary.
- **DO** sanitize and truncate user-supplied content before it enters a system prompt or user turn.
- **DO** validate machine-consumed model output server-side before it affects persistence, scoring, or user-visible critical state.
- **DO NOT** use LLM-emitted tags (e.g., `[[INTERVENTION:]]`) as authoritative write triggers. They are cosmetic enrichment only.

### 8.3 Structured Output Contracts

- **DO** use `response_format={"type": "json_object"}` for any LLM call whose output must be machine-parsed (debrief scoring, structured evaluation).
- **DO** include a graceful fallback in case the model or API rejects `response_format` (catch HTTP 400, retry without the parameter).
- **DO NOT** rely on brittle text conventions (appended score lines, regex extraction) as the primary parsing strategy for authoritative outputs.
- **DO** have the backend perform all final arithmetic (score summation, XP calculation) natively — never trust the model's computed totals.

### 8.4 LLM Limits

- **DO NOT** trust the model for arithmetic, permissions, scope enforcement, or final authoritative scoring.
- **DO** use pre-computed deterministic blocks (required intervention checklists, PPE deductions, PAT point adjustments) as authoritative inputs to the debrief prompt so the LLM evaluates against facts rather than deriving them.
- **DO** implement authoritative scoring deductions as pre-computed evidence packet entries — not as open-ended LLM adjudication. The LLM receives pre-classified facts and explains them; it does not discover or add new deductions independently.
- **DO NOT** allow the debrief LLM to evaluate factual accuracy of DMIST or narrative claims directly from free text. Accuracy checks must run through the corroboration index before the debrief call and be injected as hardened findings.
- **DO** keep model behavior bounded by explicit contracts where the output matters to the system.
- See `SCENARIO_EVALUATION_ARCHITECTURE.md §6` for the complete authority split between hardened, AI-retained, and hybrid scoring dimensions.

### 8.5 UI Action Payload Convention — Request Form vs. Announcement Form

Any frontend payload that requires Alex (or the scene AI) to **report back a value or finding** must use **request form**, never announcement form.

| Form | Pattern | AI behavior |
|---|---|---|
| **Request form** ✅ | "Alex, please report the blood pressure." / "Alex, auscultate bilateral lung sounds and report what you hear." | AI responds with the finding and emits the appropriate `[[VITAL:]]` or `[[EXAM:]]` tag. |
| **Announcement form** ❌ | "I am obtaining blood pressure." / "I am auscultating lung sounds bilaterally." | AI interprets this as a student status update and acknowledges ("Copy, obtaining now.") without providing a finding or emitting a tag. No PCR update, no popup trigger. |

This applies to **all** payloads on:
- Jump bag / equipment buttons (BP cuff, pulse ox, glucometer, thermometer, penlight, auscultate)
- Exam menu selections (lung sounds left/right/bilateral, body map assessment buttons)
- Single-vital and multi-vital selection paths
- Any future "Quick Action" shortcut that expects a reported value or physical exam finding

**Why this matters:** The lung sound challenge popup (`_shouldTriggerLungSoundChallenge`) requires both a `[[EXAM: Lung Sounds=...]]` tag in the AI response AND that `_userExplicitlyRequestedLungSounds()` returned true. Announcement-form payloads produce neither — the AI acknowledges without reporting, so no tag is emitted and no popup fires. The same gap silently prevents VITAL and EXAM tags from populating the PCR.

**Rule:** If the payload ends with the student performing an action on themselves, rewrite it so Alex is performing the action and reporting back.

#### Intervention popup modals triggered from the quick action menu

Some intervention modals (currently the O₂ administration modal) can be opened directly from the quick action menu **without any preceding chat message**. When the student confirms one of these modals, the intervention is recorded via `applyInterventionAndRecord()` — but there is no AI response in the chat, so the student gets no clinical feedback on the intervention's effect.

**Rule:** Any intervention popup that can be triggered from the quick action menu (not from a chat-driven `[[INTERVENTION:]]` tag) must send a follow-up chat message after recording the intervention, so the AI can describe the patient's response. Use request form directed at Alex:

```javascript
await applyInterventionAndRecord(interventionId, pcrLabel);
sendMessage(`I've applied ${pcrLabel}. Alex, what changes are you observing in the patient?`, { isAction: true });
```

Because the intervention is already in the session's applied list when this message is sent, the AI will not re-emit `[[INTERVENTION:]]`. It will describe the patient's clinical response to the intervention instead.

**Do not add this follow-up to medication popups** — medication popups are always triggered by a chat-driven `[[INTERVENTION:]]` tag (the student first types or selects the medication, the AI responds, and the popup is the dose-confirmation step). There is already an AI response in the chat before the popup appears.

#### Subscores extraction fallback

The debrief LLM occasionally returns a partial `subscores` JSON (e.g., only `{"narrative": 5}`) rather than all five categories. The backend subscores extraction runs the regex fallback **per key** — not only when the entire dict is empty. Any key absent from the structured JSON is filled via regex against the debrief markdown text, with an explicit `0` floor if the regex also fails. **Do not revert this to an `if not subscores:` guard** — that pattern treats any partial result as fully parsed and leaves the missing categories as `undefined` in the frontend score breakdown.

---

## 9. Compliance and Liability Guardrails

### 9.1 PHI / PII Risk

- **DO NOT** design features that encourage real patient data entry.
- **DO** assume free-text fields are high-risk for accidental PHI/PII insertion.
- **DO** respect the 30-day TTL retention policy: `ChatMessage` rows, `dmist_report`, `narrative_data["narrative"]`, `SessionFinding` rows, and `SessionEvent` rows are scrubbed by the background TTL worker. `SessionEvent` rows are operational run audit data — no free-text user input, TTL scrub is appropriate. Do not add new free-text persistence without evaluating TTL applicability.

### 9.2 Clinical Scope Enforcement

- **DO NOT** allow the system to silently upgrade scope of practice.
- **DO** enforce user scope and agency ceiling restrictions consistently across menus, AI behavior, scoring, and intervention availability.

### 9.3 Historical Integrity

- **DO NOT** erase evidence of prior grading, protocol state, or adjudication decisions.
- **DO** preserve a trustworthy historical record for review, appeals, and auditing. Use `AdjudicatedOutcome` for corrections — never overwrite `SimSession.score` or `SimSession.feedback`.

---

## 10. Code Organization and Maintainability Rules

### 10.1 Cohesion

- **DO NOT** add unrelated responsibilities to an already overloaded module without strong reason.
- **DO** prefer cohesive changes that keep related logic together and unrelated logic separate.
- **DO** refactor opportunistically when a change would otherwise deepen an already fragile code path.

### 10.2 Naming and Clarity

- **DO NOT** rely on cleverness or implicit behavior when explicit naming would reduce confusion.
- **DO** name functions, modules, and state fields according to what they actually do.
- **DO** add comments only where they clarify intent, invariants, or non-obvious reasoning — not to describe what the code does.

### 10.3 Temporary vs Permanent Patterns

- **DO NOT** let transitional bridges silently harden into permanent architecture. Every transitional pattern must be named as such (e.g., `SessionFinding` is marked TRANSITIONAL INGESTION in its docstring).
- **DO** document temporary capture paths, compatibility shims, and migration-stage logic clearly.
- **DO** align new code with the target architecture documented elsewhere, not with the transitional state of the current code.

---

## 11. Execution Policy for AI Coding Agents

When AI agents plan or implement work in this repository, they must follow these rules in order:

1. **Read memory and governing docs first.** Check project memory files, `CLAUDE.md`, and the relevant design docs (`HIGH_LEVEL_DESIGN.md`, `AI_ARCHITECTURE.md`, etc.) before making structural changes. Do not repeat decisions already resolved in memory.
2. **Protect the core mandates.** If a request conflicts with clinical determinism, auditability, tenant isolation, or scope enforcement, stop and propose a compliant alternative rather than implementing the request as stated.
3. **Check for existing patterns before introducing new ones.** If the codebase already solves a similar problem (auth, locking, upsert, migration), use that pattern. Do not introduce a second approach to the same problem.
4. **Prefer additive, reviewable changes.** Avoid destructive edits unless explicitly requested and operationally safe. When in doubt, preserve and extend rather than replace.
5. **Preserve backward compatibility where practical.** Favor migrations and staged rollouts over abrupt contract changes. When changing a schema or API contract, account for in-flight requests and partially upgraded environments.
6. **Verify before concluding.** Run syntax checks on every modified Python file. State clearly what was verified and what was not. Do not claim a change is complete if only syntax was checked.
7. **Call out risks honestly.** If a change leaves open migration concerns, race conditions, testing gaps, or operational risk, name them explicitly and describe the impact. Do not bury risks in optimistic framing.

---

## 12. Code Review Standards

Code review is a required quality gate, whether performed by a human reviewer, an AI reviewer, or both.

- **DO NOT** treat review as a style-only pass.
- **DO** prioritize correctness, tenant isolation, security, regression risk, maintainability, and operational safety.
- **DO** review changes against this document and the relevant design docs for architectural drift.
- **DO** call out missing tests, unsafe migrations, brittle parsing, weak validation, hidden coupling, and incomplete rollback planning.
- **DO** treat auth, grading, protocol, billing, privacy, and data-retention changes as higher-scrutiny review areas.

---

## 13. Relationship to Design Documents

Use this document together with the project's detailed design docs:

- `HIGH_LEVEL_DESIGN.md` — system-level architecture, authority boundaries, data flow
- `SCENARIO_ENGINE_ARCHITECTURE.md` — scenario execution and debrief behavior
- `AI_ARCHITECTURE.md` — model integration patterns, prompt design, and constraints
- `SCENARIO_DESIGN_EMS.md` — canonical scenario authoring reference: all JSON fields, scoring rubric, vocabulary contract, ALS vitals, rubric template system
- `docs/rubric_templates/ems_standard_v1.md` — base rubric template and scaffold for all scenarios
- `SCORM_TRIAL_PUNCHLIST.md` — known issues, tech debt, compliance gaps, and in-progress work
- feature-specific design docs — deeper subsystem mechanics

**Tiebreaker:** If a design doc is silent on a decision, default to the most conservative interpretation of this document's mandates and explicitly call out the gap so the design doc can be updated. Do not fill gaps by drifting toward convenience.

**Conflict resolution:** If a detailed design doc conflicts with this file, resolve the conflict deliberately rather than drifting silently. This document is the durable standards layer. Subsystem docs carry the changing implementation detail and should be updated to match when the standard wins.

---

## 14. Recommended Companion Documents

### Canonical authoring references (exist now)

| Document | Path | What it covers |
|---|---|---|
| Scenario Design Reference | `docs/SCENARIO_DESIGN_EMS.md` | Every scenario JSON field, runtime architecture, scoring rubric, PAT, personas, exemplars, pre-publish checklist |
| Rubric Template (base) | `docs/rubric_templates/ems_standard_v1.md` | Copy-ready JSON scaffold for `scoring_rubric` and `scoring.by_level`; taxonomy of fixed vs. authored rubric content |
| AI Architecture | `docs/AI_ARCHITECTURE.md` | LLM integration, prompt assembly, debrief pipeline, protocol scope decision record |
| Scenario Engine Architecture | `docs/SCENARIO_ENGINE_ARCHITECTURE.md` | Vitals engine, scope enforcement, multi-tenant adaptation, session lifecycle |
| Scenario Evaluation Architecture | `docs/SCENARIO_EVALUATION_ARCHITECTURE.md` | Evidence packet builder, three-layer scoring architecture, debrief authority split, corroboration index, implementation phases |
| Multi-Tenant Protocol Architecture | `docs/multi_tenant_protocol_architecture.md` | Protocol resolver, jurisdiction hierarchy, phased rollout plan |
| High-Level Design | `docs/HIGH_LEVEL_DESIGN.md` | Full system overview, component map, data flow, security model |
| UI Style Guide | `docs/STYLE_GUIDE.md` | Dual-theme design, color palette, typography, components |
| Immersive Mode Design | `docs/IMMERSIVE_MODE_DESIGN.md` | UI layout, jump bag, body map, and quick-action architecture |
| Gamification & Rewards | `docs/REWARDS.md` | XP math, treat drops, toy rarity, and pity timer rules |
| Pediatric Map Design | `docs/PEDIATRIC_MAP_DESIGN.md` | Scenario progression, convergence gates, and mini-game placement |
| Punchlist | `docs/SCORM_TRIAL_PUNCHLIST.md` | Known issues, technical debt, and planned enhancements by severity |

When adding a new scenario, an agent or contributor's first read should be `docs/SCENARIO_DESIGN_EMS.md`. All other scenario-authoring references must link there, not to `app/scenarios/scenario_design_ems.md` (which is a redirect stub only).

### Future companion documents (create when needed)

- `TESTING_GUIDELINES.md` for test strategy, fixture conventions, and validation workflow
- `SECURITY_GUIDELINES.md` for auth/authz rules, secrets handling, threat modeling, and incident-sensitive practices
- `CODE_REVIEW_GUIDELINES.md` for review workflow, severity conventions, and merge expectations

This file should remain the top-level standards and guardrails document that points to those deeper references.
