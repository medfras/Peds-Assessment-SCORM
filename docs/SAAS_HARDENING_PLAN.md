# SaaS Hardening Plan

**Project:** EMS Simulator / RescueTrails  
**Review type:** Production readiness — multi-tenant SaaS deployment  
**Review perspective:** Senior software engineer, software architect, DBA  
**Sources:** Internal code review (Claude), Gemini review, Codex review  
**Date:** 2026-05-10  
**Last revised:** 2026-05-14 — Challenge-domain scoring source enforcement complete for lung sounds, GCS, and BGL (hypoglycemia call type); three-layer boundary (routing + AI suppression + scoring source) now enforced for all three; 126 tests pass

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Findings Register](#2-findings-register)
3. [Findings Detail](#3-findings-detail)
   - [3.1 Security](#31-security)
   - [3.2 Database & Schema Management](#32-database--schema-management)
   - [3.3 Infrastructure & Deployment](#33-infrastructure--deployment)
   - [3.4 Scalability & State Architecture](#34-scalability--state-architecture)
   - [3.5 Performance](#35-performance)
   - [3.6 Code Quality & Maintainability](#36-code-quality--maintainability)
   - [3.7 Observability & Operations](#37-observability--operations)
   - [3.8 Dependencies & Supply Chain](#38-dependencies--supply-chain)
   - [3.9 Business Operations](#39-business-operations)
4. [Phased Implementation Plan](#4-phased-implementation-plan)
   - [Phase 1a: Immediate Security Fixes](#phase-1a-immediate-security-fixes-days-1-3)
   - [Phase 1b: Auth Architecture](#phase-1b-auth-architecture-week-1-2)
   - [Phase 2: Deployment & Operations](#phase-2-deployment--operations-week-2-3)
   - [Phase 3: Scalability & State](#phase-3-scalability--state-week-4-6)
   - [Phase 4: Code Quality & Account Lifecycle](#phase-4-code-quality--account-lifecycle-month-2-3)
   - [Phase 5: Performance & Optimization](#phase-5-performance--optimization-month-3)
5. [Architectural Strengths](#5-architectural-strengths)

---

## 1. Executive Summary

The EMS Simulator codebase reflects serious, disciplined engineering effort. The domain model is well-designed, async patterns are used correctly, the AI/code authority boundary is architecturally sound, and the system documentation is exceptional. The scoring, protocol, and scenario engines are at a production-quality level.

The application previously had several security vulnerabilities exploitable without authorization; the most critical of these (CORS, JWT storage, WebSocket tokens, API docs exposure, dependency CVE) have been resolved in Phases 1a/1b. Remaining hardening gaps — CSP enforcement, account lifecycle, Alembic migrations, in-process scalability state, and the two monoliths — are concentrated and solvable. These are execution items, not systemic design failures.

**Estimated production readiness: 75–80%** *(updated 2026-05-12 after Phases 1a/1b/2 code complete)*

| Category | Status |
|----------|--------|
| Security | **Substantially hardened** — Phase 1a/1b critical vulnerabilities resolved (CORS, JWT storage, WebSocket, API docs, security headers, CVE). CSP still in report-only mode. Account lifecycle (password reset, lockout) and CSP enforcement remain open. |
| Database / Schema | **Blocked** — no versioned migrations (DB-01); startup DDL still in use; Alembic adoption deferred to Phase 3. |
| Infrastructure | **Substantially hardened** — reverse proxy (Caddyfile), non-root Docker, health probes, Sentry with privacy scrubber, and container restart policy all deployed. TLS/staging/backup-DR gate validation still pending. |
| Scalability | **Blocked for multi-instance** — in-process rate limiting, WebSocket state, and background workers still in place; Redis externalization deferred to Phase 3. Single-instance operation is stable. |
| Observability | **Improved** — structlog consistent throughout (ai_client migrated); Sentry implemented with PHI scrubber. Live smoke test, OTel tracing, and APM metrics still open. |
| Code quality | **Known debt, planned** — two monoliths (main.py, app.js) actively growing; decomposition planned for Phase 4 with concrete done criteria; CSP enforcement gates on Phase 4 frontend work. |
| Dependencies | **Improved** — CVE fixed, pip-audit in CI. Dependabot/image scanning/supply-chain hardening deferred to Phase 3. |
| Business operations | **Absent** — billing enforcement, transactional email, cloud file storage, and data offboarding not yet implemented. |

---

## 2. Findings Register

**Launch Gate legend:**
- **Public** — blocks any internet-accessible deployment; a security or data-loss risk to existing users
- **SaaS** — blocks a public or paid SaaS launch; acceptable for a private, monitored pilot with known users and disposable data
- **Scale** — blocks horizontal scaling; a single-server deployment is unaffected
- **Pilot** — acceptable for a monitored private pilot only with known users and explicit awareness of the gap; address before broad rollout

| ID | Category | Severity | Title | Launch Gate |
|----|----------|----------|-------|-------------|
| S-01 | Security | HIGH | ~~CORS must be restricted before cookie auth and production launch~~ **Resolved (2026-05-12).** Allowlist-based CORS with `allow_credentials=True`; `settings.allowed_origins`; browser preflight verified. | — |
| S-02 | Security | HIGH | ~~JWT tokens stored in localStorage~~ **Resolved (2026-05-12).** httpOnly cookie auth deployed; `localStorage` writes removed; Bearer-header fallback removed in Phase 2. | — |
| S-03 | Security | HIGH | ~~WebSocket JWT passed in URL query string~~ **Resolved (2026-05-12).** `POST /api/ws-ticket` 30-second TTL tickets deployed; JWTs no longer appear in any WebSocket URL. | — |
| S-04 | Security | HIGH | ~~Hundreds of `innerHTML` assignment sites — wide XSS surface~~ **Substantially addressed (2026-05-12).** AI-text and user-input render paths (`renderAiText`, `renderMarkdown`) confirmed safe — all use `escapeHTML()`. `no-unsanitized` ESLint rule installed (warn on 161 legacy `.map().join()` patterns; 0 errors). CSP enforced (flipped from report-only). Remaining 161 ESLint warnings are tech debt to remediate in Phase 4 monolith decomposition. | — |
| S-05 | Security | MEDIUM | ~~FastAPI `/docs` and `/redoc` exposed in production~~ **Resolved (2026-05-12).** Docs/redoc/openapi disabled when `_IS_PROD`. | — |
| S-06 | Security | MEDIUM | ~~Production secret validation gated on `ENV=production` only~~ **Resolved (2026-05-12).** Validation extended to `staging` and `preview` environments. | — |
| S-07 | Security | MEDIUM | ~~JWT access token expires in 24 hours with no refresh flow~~ **Resolved (2026-05-12).** TTL reduced to 60 minutes; server-side refresh token rotation and revocation deployed. | — |
| S-08 | Security | MEDIUM | ~~Missing security response headers~~ **Resolved (2026-05-12).** HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy all deployed. CSP flipped from report-only to enforce mode after staging validation. Gate: zero CSP violations in staging browser session required before rollout. | — |
| S-09 | Security | MEDIUM | Account lifecycle gaps (password reset, lockout, session revocation) | SaaS |
| S-10 | Security | LOW | Password minimum length is 8 characters | Pilot |
| DB-01 | Database | HIGH | No versioned migration tool — startup DDL only; conflicts with `DEVELOPMENT_GUIDELINES.md` | SaaS |
| DB-02 | Database | MEDIUM | Unbounded list endpoints — no pagination | Scale |
| DB-03 | Database | MEDIUM | JSONB protocol snapshot blobs may trigger TOAST pressure | Scale |
| DB-04 | Database | MEDIUM | Mixed DB session management patterns — no rollback guards on manual sessions | Pilot |
| DB-05 | Database | MEDIUM | No database backup, PITR, or disaster recovery strategy | SaaS |
| DB-06 | Database | LOW | No database-level constraints for critical business rules | Pilot |
| INF-01 | Infrastructure | HIGH | ~~No error tracking service (Sentry / equivalent)~~ **Resolved (2026-05-12).** `sentry-sdk[fastapi]` installed; PHI scrubber (`_scrub_sentry_event`) implemented; global exception handler wired. Live smoke test still pending. | — |
| INF-02 | Infrastructure | HIGH | Single-worker Uvicorn in Dockerfile — **must not be changed to multi-worker until Phase 3** | SaaS |
| INF-03 | Infrastructure | MEDIUM | ~~No reverse proxy or TLS termination in deployment config~~ **Partially addressed (2026-05-12).** `Caddyfile` and `docker-compose.prod.yml` created. TLS validation, static-file-via-Caddy, and WebSocket-over-wss gate checks still pending. | Public |
| INF-04 | Infrastructure | MEDIUM | ~~No liveness or readiness health check endpoints~~ **Resolved (2026-05-12).** `/live` (process-only) and `/ready` (DB ping) added; `HEALTHCHECK` in Dockerfile. Orchestrator probe wiring is an infra/ops task. | — |
| INF-05 | Infrastructure | MEDIUM | ~~Docker image runs as root with no non-root user~~ **Resolved (2026-05-12).** UID 1001 `appuser` added to Dockerfile; `docker-compose.prod.yml` created. | — |
| INF-06 | Infrastructure | LOW | ~~PostgreSQL port 5432 exposed to host in docker-compose~~ **Resolved (2026-05-12).** Port removed from `docker-compose.prod.yml`. | — |
| INF-07 | Infrastructure | LOW | ~~Source-code bind-mounts present in docker-compose~~ **Resolved (2026-05-12).** Bind-mounts absent from `docker-compose.prod.yml`. | — |
| INF-08 | Infrastructure | LOW | ~~Test dependencies installed in production container~~ **Resolved (2026-05-12).** `requirements-dev.txt` created; test deps removed from production image. | — |
| SC-01 | Scalability | HIGH | In-process SlowAPI rate limiting — fails under horizontal scaling | Scale |
| SC-02 | Scalability | HIGH | In-process `lru_cache` and `_LEXI_GROUP_WS` WebSocket state — no cross-replica invalidation | Scale |
| SC-03 | Scalability | MEDIUM | Vitals WebSocket opens a new DB session every 3 seconds per connection | Scale |
| SC-04 | Scalability | MEDIUM | Background workers run per-process with no supervision or deduplication | SaaS |
| SC-05 | Scalability | MEDIUM | LLM calls have retry backoff but no concurrency cap, circuit breaker, or queue | Scale |
| SC-06 | Scalability | LOW | No API versioning strategy | Pilot |
| PERF-01 | Performance | MEDIUM | `authFetch` forces `cache: "no-store"` on all authenticated GETs | Pilot |
| PERF-02 | Performance | MEDIUM | Static asset versioning (`?v=`) — 1-year immutable cache with no automatic invalidation | Pilot |
| PERF-03 | Performance | MEDIUM | Notebook condition unlock scans full session history in Python | Scale |
| PERF-04 | Performance | LOW | Media assets served without CDN | Pilot |
| QA-01 | Code Quality | HIGH | `app/main.py` — 15,556-line monolith (175 routes, 222 async functions, 78 Pydantic models) — current as of 2026-05-12 | Pilot |
| QA-02 | Code Quality | HIGH | `static/js/app.js` — 28,827-line monolith with global mutable state — current as of 2026-05-12 | Pilot |
| QA-03 | Code Quality | MEDIUM | ~~Background task crash exits silently — no restart, no alert~~ **Resolved (2026-05-12).** `_supervised()` wrapper deployed; both workers log via structlog and restart. Explicit `sentry_sdk.capture_exception()` still pending. | — |
| QA-04 | Code Quality | MEDIUM | ~~No global HTTP 500 exception handler~~ **Resolved (2026-05-12).** Global handler returns `{"detail": "Internal server error"}` (500); logs full exception server-side. Explicit Sentry capture pending. | — |
| QA-05 | Code Quality | MEDIUM | Client-side game progress stored in localStorage only — no server reconciliation | Pilot |
| QA-06 | Code Quality | MEDIUM | LLM structured output has no schema validation layer | Scale |
| QA-07 | Code Quality | LOW | Stale code comments no longer reflect current implementation (e.g., auth comment still references localStorage) | Pilot |
| OBS-01 | Observability | HIGH | ~~No error tracking service configured~~ **Resolved (2026-05-12).** See INF-01. | — |
| OBS-02 | Observability | MEDIUM | ~~`ai_client.py` uses stdlib `logging` — inconsistent with structlog standard~~ **Resolved (2026-05-12).** Replaced with `from app.logging_config import get_logger`; all 22 call sites updated. | — |
| OBS-03 | Observability | MEDIUM | No distributed tracing (OpenTelemetry) | Pilot |
| OBS-04 | Observability | MEDIUM | No APM / metrics dashboard | Pilot |
| DEP-01 | Dependencies | HIGH | ~~`python-multipart==0.0.9` — known CVEs (DoS), safe version is ≥0.0.27~~ **Resolved (2026-05-12).** Updated to `>=0.0.27`; `pip-audit` clean; CI step added. | — |
| DEP-02 | Dependencies | MEDIUM | No automated dependency scanning or supply-chain hardening | SaaS |
| BIZ-01 | Business Operations | MEDIUM | No billing or entitlements infrastructure — subscription limits not enforced architecturally | SaaS |
| BIZ-02 | Business Operations | MEDIUM | User file uploads processed on-server — no cloud storage, no malware scanning | SaaS |
| BIZ-03 | Business Operations | MEDIUM | No transactional email provider — password reset and notifications cannot be delivered | SaaS |
| BIZ-04 | Business Operations | LOW | No full-text search strategy — `ILIKE` queries will cause full table scans at scale | Scale |
| BIZ-05 | Business Operations | MEDIUM | No data privacy offboarding: no account deletion, anonymization, or export strategy | SaaS |
| BIZ-06 | Business Operations | HIGH | Scenario content depth is insufficient for a paid launch — one playable scenario exists | SaaS |
| SCORE-01 | Scoring Integrity | HIGH | ~~Corroboration prepass is an LLM call making adjudication decisions~~ **Pending live validation (2026-05-12).** Deterministic corroborator implemented (`app/corroboration.py`); 99 contract + fixture tests pass. Shadow mode enabled by default in `.env.example` (`SHADOW_DETERMINISTIC_CORROBORATION=true`). Flip `USE_DETERMINISTIC_CORROBORATION=true` after live shadow runs confirm ≥80% agreement and no false positives on clean runs (check `ai.corroboration.shadow_comparison` structlog events). | SaaS |
| SCORE-02 | Scoring Integrity | HIGH | ~~`EVALUATE`-tagged critical actions pass to LLM~~ **Closed for current scenario set.** Groups B2/B3/B4 eliminated current `EVALUATE` paths: 29 pre-credit actions, 3 ALS/intercept actions routed through P2 by `id`, and 64 evidence-backed actions. Authoring validator warns on new required actions without evidence. | — |
| SCORE-03 | Scoring Integrity | MEDIUM | ~~No pre-debrief gate for authored content~~ **Fixed.** `_validate_debrief_content()` in `app/scenarios/vocabulary.py`; runtime guard in `evaluate_and_generate_debrief()`. Tests pass. | — |
| SCORE-04 | Scoring Integrity | MEDIUM | ~~Subscores JSON from LLM has no range/type validation~~ **Fixed.** `_SUBSCORE_RANGES`, `_extract_required_debrief_subscores()` range validation with ERROR log, authoritative fallback, range-validated regex recovery, `subscore_maxima` includes treatment bucket maxes. 17 tests pass in `test_subscore_validation.py`. | — |
| SCORE-05 | Scoring Integrity | LOW | ~~Temperature 0.7 applies to structured subscores output~~ **CLOSED — false finding.** Debrief call confirmed at `temperature=0.4`. No change needed. | — |
| SCORE-06 | Scoring Integrity | HIGH | ~~Challenge-gated clinical findings (lung sounds, GCS, BGL) were satisfiable via AI free-text transcript fallback~~ **Fixed (2026-05-14).** Three-layer enforcement: (1) frontend routing guards intercept requests and open challenge modals, (2) AI system prompt suppresses prose reveals when challenge is enabled, (3) scoring rubric items use challenge-specific source roles (`challenge_performed_exam` → `lung_sound_challenge`; `challenge_calculated_gcs` → `gcs_modal`; `challenge_measured_bgl` → `glucometer_check`) with `allowed_tiers=[1]`; Tier 2 transcript fallback is blocked. Regression tests confirm AI/null-source findings do not satisfy challenge-gated items. 126 tests pass. | SaaS |

---

## 3. Findings Detail

### 3.1 Security

---

#### S-01 — CORS must be restricted before cookie auth and production launch (HIGH)

**Status (2026-05-12):** Resolved. `settings.allowed_origins` allowlist in use; `allow_credentials=True`; explicit methods and headers. Browser preflight verified.

**Location:** `app/main.py:817-820`

```python
CORSMiddleware,
allow_origins=["*"],
allow_methods=["*"],
allow_headers=["*"],
```

**Precise risk:** `allow_origins=["*"]` combined with `allow_credentials=True` is rejected by browsers outright. However, the current configuration does not set `allow_credentials=True`, so browsers allow cross-origin requests — but without credentials. The real exploit chain is: (1) XSS injects script that reads the JWT from `localStorage` (S-02), (2) that script posts the token to an attacker-controlled origin, (3) the attacker replays it from any server without browser CORS involvement at all. A secondary future risk: once cookies are adopted (S-07), setting `allow_origins=["*"]` with `allow_credentials=True` would be rejected by browsers — so CORS must be corrected before the cookie auth migration anyway.

**Recommendation:** Restrict to the exact production domain(s). Use an environment-driven allowlist.

```python
# config.py
allowed_origins: list[str] = ["http://localhost:8000"]

# main.py
CORSMiddleware,
allow_origins=settings.allowed_origins,
allow_credentials=True,
allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
```

**`.env` format note:** Pydantic-settings parses `list[str]` fields from environment variables as JSON by default. Set the value as a JSON array string in `.env`:
```
ALLOWED_ORIGINS=["http://localhost:8000","https://app.example.com"]
```
If you prefer a comma-separated format (`ALLOWED_ORIGINS=http://localhost:8000,https://app.example.com`), add a custom `field_validator` using `v.split(",")`. Pick one format, document it in `.env.example`, and test startup — this is the most common silent misconfiguration in Pydantic settings with list fields.

---

#### S-02 — JWT tokens stored in localStorage (HIGH)

**Status (2026-05-12):** Resolved. httpOnly cookie auth deployed (`pfd_ems_session`); `localStorage.setItem` removed from `app.js`; `Authorization: Bearer` header injection removed from `authFetch`; Bearer-header fallback removed from `_extract_token` in Phase 2. The stale comment at `app.js:22` (`authToken: null, // JWT stored here and in localStorage`) is now incorrect — tracked as QA-07.

**Location:** `static/js/app.js:5033`, `app.js:22`

```js
localStorage.setItem("pfd_ems_token", token);
authToken: null,  // JWT stored here and in localStorage
```

`localStorage` is readable by any JavaScript running on the page — including injected scripts, browser extensions, and third-party widgets. A single XSS payload can silently exfiltrate a 24-hour token and replay it from an attacker's machine. `httpOnly` cookies are the correct storage mechanism: invisible to JavaScript, automatically sent with same-origin requests, and immune to XSS-based token theft.

**Recommendation:**

1. Issue tokens as `httpOnly; Secure; SameSite=Strict` cookies from the login endpoint.
2. Remove all `localStorage` reads/writes for the auth token.
3. Remove the `Authorization: Bearer` header from `authFetch` — the browser sends the cookie automatically.
4. Add CSRF protection for state-changing requests. Use a **signed double-submit token**: the server generates a per-session CSRF token, signs it with `APP_SECRET_KEY` (HMAC-SHA256), sets it as a non-httpOnly cookie, and validates the signature on the incoming `X-CSRF-Token` header rather than doing a naive cookie-equals-header comparison (which is vulnerable to cookie-forcing attacks on subdomains). `SameSite=Strict` provides the primary protection in modern browsers; the signed token covers older browsers and sub-domain trust boundary edge cases.
5. Note for future LMS/SCORM/SSO integrations: `SameSite=Strict` blocks cookies on cross-site redirects, which will break OAuth/SAML SSO flows and LMS launch sequences if those are added later. At that point, auth cookies for those flows may need `SameSite=Lax` on specific endpoints combined with the signed CSRF token as the primary protection.

This is a coordinated backend/frontend change — see Phase 1b.

---

#### S-03 — WebSocket JWT passed in URL query string (HIGH)

**Status (2026-05-12):** Resolved. `POST /api/ws-ticket` issues 30-second TTL tickets stored in `ws_tickets` DB table; vitals and Lexi Group WebSocket connections use `?ticket=<uuid>` — no JWT in any URL. Expired ticket cleanup wired into `_ttl_scrub_worker`.

**Location:** `app/main.py:10683`, `app/main.py:10762`

```python
token = websocket.query_params.get("token")
```

Tokens in query strings are recorded verbatim in server access logs, load balancer logs (AWS ALB, GCP, Cloudflare), browser history, and any monitoring proxy. A token in a URL is a token in plaintext in every log aggregation system the platform uses.

**Recommendation:**

1. Add `POST /api/ws-ticket` — returns a signed, 30-second-TTL ticket UUID stored server-side (Redis or DB).
2. Client fetches a ticket before opening the WebSocket and passes the UUID in the URL.
3. Server validates the ticket on WebSocket open, marks it consumed, and maps it to the user session.
4. The primary JWT never appears in a URL.

---

#### S-04 — Hundreds of `innerHTML` assignment sites — wide XSS surface (HIGH)

**Status (2026-05-12):** Partially addressed. `grep -c "innerHTML" static/js/app.js` returns 334 raw occurrences. A full audit classified 172 as risky sinks (those writing content derived from AI responses, user input, or external data); the remaining 162 are structural/safe (static string templates, empty-string clears). Of the 172 risky sinks, 5 AI-tag-parsed sinks were fixed (`flushVitalsBlock`, `addPcrExam`, `addPcrExamRaw`, `addPcrHistory`, `addPcrTreatment`). CSP deployed in report-only mode. Full mitigation path: Phase 4 frontend decomposition → `no-unsanitized/property` ESLint rule in CI (enforces escape-by-default at the tool level, not by manual audit) → switch CSP from report-only to enforcement mode.

**Reproducibility:** Run `grep -c "innerHTML" static/js/app.js` to get the current count. At time of this review: hundreds of occurrences.

The frontend extensively uses `innerHTML` for component rendering. Although `escapeHTML()` exists, the volume of injection points is too large to audit manually for every future change. One missed escape on a single instructor- or student-provided string (DMIST narrative, notebook entry, team name) would compromise the session.

**Recommendation:**

- Add a Content Security Policy header (see S-08) as an immediate damage-limiting layer.
- Adopt a templating approach that escapes by default: `textContent` for text, `createElement` + `appendChild` for structure, or a minimal sanitizing template library (DOMPurify).
- As part of the frontend decomposition (QA-02), enforce ESLint `no-unsanitized/property` in CI to flag new unsafe `innerHTML` usage automatically.
- Audit existing `innerHTML` assignments that include user-provided strings and migrate to `textContent`.

---

#### S-05 — FastAPI `/docs` and `/redoc` exposed in production (MEDIUM)

**Status (2026-05-12):** Resolved. `docs_url=None`, `redoc_url=None`, `openapi_url=None` set when `_IS_PROD`. Verified: `/docs` returns 404 under `ENV=production`.

**Location:** `app/main.py:811`

FastAPI enables interactive API documentation at `/docs` and `/redoc` by default. These expose the complete API surface, all request/response schemas, and the authentication flow to unauthenticated visitors in production.

**Recommendation:**

```python
app = FastAPI(
    title="LexiSim",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/docs" if not _IS_PROD else None,
    redoc_url="/redoc" if not _IS_PROD else None,
    openapi_url="/openapi.json" if not _IS_PROD else None,
)
```

---

#### S-06 — Production secret validation gated on `ENV=production` only (MEDIUM)

**Status (2026-05-12):** Resolved. Secret strength validation extended to `staging` and `preview` environments. `_log_startup_config()` records `ENV=<value>` on startup.

**Location:** `app/config.py:6-7`

The weak-secret validators only hard-fail when `_ENV == "production"`. A staging environment deployed with `ENV=staging` silently accepts `changeme` credentials.

**Recommendation:** Apply secret strength validation to any non-`development` environment. Reject `changeme` when `ENV` is `staging`, `preview`, or `production`.

---

#### S-07 — JWT access tokens expire in 24 hours with no refresh flow (MEDIUM)

**Status (2026-05-12):** Resolved. TTL reduced to 60 minutes. `POST /api/token/refresh` implemented with atomic consume-and-rotate; `refresh_tokens` table tracks server-side revocation; logout revokes the refresh token; `authFetch` extended with silent 401→refresh→retry.

**Location:** `app/config.py:14`

A 24-hour window with no revocation means a stolen token is valid for up to a day with no recourse. Standard practice is 15–60 minute access tokens with a separate refresh token stored as an `httpOnly` cookie, revocable at the server.

**Recommendation:** Reduce access token TTL to 60 minutes. Implement `POST /api/token/refresh`. Issue refresh tokens as `httpOnly; Secure; SameSite=Strict` cookies with a 7-day TTL, tracked in a server-side revocation table.

---

#### S-08 — Missing security response headers (MEDIUM)

**Status (2026-05-12):** Partially addressed. `SecurityHeadersMiddleware` deployed: HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy all present. CSP is still in `Content-Security-Policy-Report-Only` mode — zero violations confirmed for the full login→sim→debrief workflow. Switch to enforcement after Phase 4 frontend decomposition passes the `no-unsanitized/property` ESLint rule.

No security-oriented HTTP response headers are set. This is a quick, high-value addition that hardens the browser's security posture before a single line of application logic changes.

**Recommendation:** Add the following headers via a middleware or the reverse proxy:

| Header | Recommended Value |
|--------|------------------|
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains` — do not add `preload` until the production domain, all subdomains, and HTTPS coverage are confirmed and stable; HSTS preload list submission is irreversible for the domain |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'` |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |

Add a `SecurityHeadersMiddleware` to `app/main.py` or configure these in the Nginx/Caddy reverse proxy config.

---

#### S-09 — Account lifecycle gaps (MEDIUM)

Several account management flows expected in a production SaaS are absent or incomplete:

- **Password reset:** No `POST /api/auth/forgot-password` / `POST /api/auth/reset-password` flow with time-limited tokens. Users who forget their password have no self-service path.
- **Email verification:** Registration accepts any email address without verifying ownership, enabling impersonation and email-based abuse.
- **Account lockout / adaptive throttling:** The rate limiter guards the login endpoint by IP/user but there is no progressive lockout (e.g., 10 failed attempts → 15-minute lockout) or alerting on repeated failures for a single account.
- **Session revocation:** No mechanism to invalidate all active sessions for a user (required for compromised-account response).
- **Refresh token rotation:** Refresh tokens should be single-use; each use should issue a new refresh token and invalidate the old one.
- **Admin impersonation audit:** The impersonation endpoint must write an immutable audit log entry containing: original actor user ID, impersonated user ID, target agency ID, session start time, session end time, stated reason, and the request ID. A visible UI indicator must be shown throughout the impersonation session (e.g., a persistent banner) so the admin cannot forget they are acting as another user.
- **Disabled-user token invalidation:** When an account is deactivated, any outstanding JWTs should be invalidated. Currently, a disabled user's token remains valid until expiry.

---

#### S-10 — Password minimum length is 8 characters (LOW)

NIST SP 800-63B recommends a 15-character minimum for user-chosen passwords. The current 8-character minimum is susceptible to offline dictionary attacks if the database is exposed.

**Recommendation:** Raise minimum to 12 characters for new accounts. Optionally integrate the HaveIBeenPwned range API for breach-password checking on registration.

---

### 3.2 Database & Schema Management

---

#### DB-01 — No versioned migration tool — startup DDL only; conflicts with `DEVELOPMENT_GUIDELINES.md` (HIGH)

**Location:** `app/database.py:25-200+` — 201 `text()` `ALTER TABLE ... IF NOT EXISTS` statements

**Policy conflict:** `DEVELOPMENT_GUIDELINES.md` section 4.2 (line 100) explicitly mandates the `init_db()` additive pattern and states: *"DO NOT put schema migration SQL in any file other than `app/database.py`."* This review recommends Alembic, which contradicts the current canonical standard. **The guideline must be updated before Alembic is adopted.** Changing the tool without changing the policy leaves engineers with conflicting guidance.

**Problems with the current approach:**

- No version history — you cannot determine what schema version any environment is running
- No rollback mechanism for failed migrations
- Multi-replica race risk: two containers starting simultaneously both execute DDL concurrently
- Non-trivial startup latency (201 DB roundtrips before the first request is served)
- Incompatible with zero-downtime blue/green deployments
- `ALTER TABLE` takes `AccessExclusiveLock` on PostgreSQL, blocking reads and writes during migration

**Recommendation:**

1. Update `DEVELOPMENT_GUIDELINES.md` section 4.2 to endorse Alembic for production migration management.
2. Migrate to Alembic: the current `init_db()` becomes the baseline migration. Subsequent schema changes go through `alembic revision --autogenerate` and are applied by a one-time migration job — not the application process on startup.
3. Retain `create_all` behind an `ENV=development` guard for local convenience.
4. Add `alembic upgrade head` to the deployment runbook.

---

#### DB-02 — Unbounded list endpoints — no pagination (MEDIUM)

**Location:**
- `app/main.py:8390` — `/api/me/sessions` — loads all user sessions, no limit
- `app/main.py:14034` — `/api/admin/sessions` — loads all agency sessions, no limit
- `app/main.py:14173` — `/api/admin/users` — loads all users, no limit

A student with 500 completed sessions causes `/api/me/sessions` to load 500 rows, join agency names, call `load_scenario()` for each, and serialize the full result. An agency with 10,000 members causes the admin users endpoint to load 10,000 rows.

**Recommendation:** Add `limit` and `cursor`/`offset` parameters. Return a `{"items": [...], "total": N, "next_cursor": "..."}` envelope. Default page size: 25–50 items.

---

#### DB-03 — JSONB protocol snapshot blobs may trigger TOAST pressure (MEDIUM)

Protocol configurations compiled into `protocol_snapshots.compiled_json` may reach 500KB–1MB. PostgreSQL stores values exceeding ~2KB in TOAST tables. Frequent concurrent reads of large TOAST rows during simulation starts will add I/O and memory pressure at classroom scale.

**Recommendation:** Log average and maximum `compiled_json` size at startup. Set a hard cap (512KB) in the protocol compiler. If blobs routinely exceed this, split snapshots into header (metadata) and body (full protocol data) columns.

---

#### DB-04 — Mixed DB session patterns — manual sessions lack rollback guards (MEDIUM)

**Location:** `app/main.py:410`, `app/main.py:10713-10729`

HTTP endpoints use `Depends(get_db)` with automatic cleanup. Background tasks and WebSocket handlers use `async with async_session_factory() as db:` directly, which does not automatically roll back on exception.

**Recommendation:** Add explicit `try / except / await db.rollback()` guards around all manual `async_session_factory()` usages, or create a shared context manager that wraps the session with automatic rollback.

---

#### DB-05 — No database backup, PITR, or disaster recovery strategy (MEDIUM)

There is no documented or automated strategy for:
- **Automated backups:** No scheduled `pg_dump`, no WAL archiving
- **Point-in-time recovery (PITR):** No WAL archive means recovery to a specific moment is impossible
- **Restore drills:** No evidence that a restore has been tested — untested backups are not backups
- **Retention policy:** No definition of how long backups are kept
- **DB monitoring:** No bloat monitoring, index health checks, or slow-query alerting
- **Connection pool limits:** No `max_connections` tuning relative to pool size

**Recommendation:**

- Managed PostgreSQL (RDS, Cloud SQL, Supabase, Neon) provides automated backups, PITR, and read replicas out of the box. Strongly preferred over self-managed for a small team.
- If self-managed: configure WAL archiving + daily `pg_dump` to object storage. Document and periodically test the restore procedure.
- Add `pg_stat_activity` and `pg_stat_user_tables` monitoring (pganalyze, Datadog Postgres integration, or a self-hosted PgHero).
- Set `statement_timeout` and `lock_timeout` at the application connection level to prevent runaway queries from blocking the pool.
- Run `VACUUM ANALYZE` regularly; configure autovacuum thresholds for high-churn tables (sessions, events, interventions).

---

#### DB-06 — No database-level constraints for critical business rules (LOW)

Provider level ordering, role validation, and score range boundaries are enforced only in application code. Database-level `CHECK` constraints and `UNIQUE` constraints on join codes add a safety net that survives application-layer bugs.

---

### 3.3 Infrastructure & Deployment

---

#### INF-01 — No error tracking service (HIGH)

**Status (2026-05-12):** Resolved. `sentry-sdk[fastapi]` installed; `_scrub_sentry_event` scrubs all request context, medical free text, and AI pipeline data before transmission; `send_default_pii=False`; `sentry_sdk.init()` called in lifespan when `SENTRY_DSN` is set. Global `@app.exception_handler(Exception)` wired. **Pending:** Live smoke test — trigger a deliberate exception in dev, verify appearance in Sentry dashboard with no PHI in payload.

There is no Sentry, Rollbar, or equivalent integration. The first notice of an unhandled production exception will be a user complaint.

**Recommendation:** Install `sentry-sdk[fastapi]`. Configure with privacy guardrails appropriate for a platform handling simulated medical free text and user-entered narratives:

```python
sentry_sdk.init(
    dsn=settings.sentry_dsn,
    traces_sample_rate=0.1,
    send_default_pii=False,           # Do not send IP, username, cookies by default
    before_send=_scrub_sentry_event,  # Custom scrubber for request bodies and narratives
)
```

Implement `_scrub_sentry_event` to strip the following from every Sentry event payload before transmission — Sentry must never become a secondary sink for PHI or sensitive user content:

- **Request context:** all request headers (including `Authorization`, `Cookie`), request body, query parameters
- **Medical free text:** any field named `message`, `narrative`, `dmist_report`, `notes`, and any key matching `*_text`, `*_content`, `*_narrative`
- **AI pipeline data:** `prompt`, `prompt_payload`, and any field containing LLM input or output — neither user chat messages nor model responses should reach Sentry
- **File content:** text extracted from uploaded PDFs or any uploaded file contents

The scrubber applies to all events, not just exceptions from specific routes. `send_default_pii=False` disables IP and username capture at the SDK level, but it does not scrub request bodies or custom fields — the `before_send` hook is required for those.

---

#### INF-02 — Single-worker Uvicorn; do not add workers before Phase 3 (HIGH)

**Location:** `Dockerfile:15`

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Single-worker Uvicorn is not a production process manager — it uses one CPU core and a crash takes down the service. However: **switching to multi-worker Gunicorn before Phase 3 in-process state is externalized will break the application.** `_LEXI_GROUP_WS`, the `lru_cache` entries, per-process background workers, and in-process rate limiting all assume a single process. Adding a second worker inside one container is equivalent to adding a second replica.

**Correct sequencing:**
- Phase 2: Keep single-worker Uvicorn. Add a container orchestrator restart policy (e.g., `restart: always` in compose, or Kubernetes liveness probe restart).
- Phase 3: After SC-01 (Redis rate limiting), SC-02 (Redis pub/sub and cache), SC-04 (distributed background workers) are complete — then switch to Gunicorn with `UvicornWorker`.

---

#### INF-03 — No reverse proxy or TLS termination (MEDIUM)

**Status (2026-05-12):** Partially addressed. `Caddyfile` and `docker-compose.prod.yml` created with reverse proxy service, WebSocket proxying, 300s timeout, and static asset serving. **Pending Phase 2 gate:** TLS validation against a real domain (SSL Labs A+), `wss://` WebSocket verification, static files served via Caddy (not Uvicorn).

A production deployment requires TLS termination, request buffering, WebSocket proxying, and static asset serving at the proxy layer.

**Recommendation:** Add a Caddy or Nginx configuration to the repository. Caddy is lowest-friction for TLS (automatic Let's Encrypt). Provide a `docker-compose.prod.yml` that includes the reverse proxy and removes source-code volumes.

---

#### INF-04 — No liveness or readiness health check endpoints (MEDIUM)

**Status (2026-05-12):** Resolved. `/live` (process-only, 200 OK) and `/ready` (DB ping via `SELECT 1`) added; `HEALTHCHECK CMD curl -f http://localhost:8000/live` in Dockerfile. Orchestrator probe wiring (Kubernetes/ECS) is an infra/ops task outside the codebase.

A single `/health` endpoint that performs a DB ping is problematic: a brief DB blip causes liveness check failures and triggers unnecessary container restarts. The correct pattern separates concerns:

- `/live` — process health only (returns 200 if the process is running; no DB call). Used for liveness probes. A failure here means restart the container.
- `/ready` — dependency health (DB ping, Redis ping). Used for readiness probes. A failure here means stop routing traffic but do not restart.

**Recommendation:**

```python
@app.get("/live", include_in_schema=False)
async def liveness():
    return {"status": "ok"}

@app.get("/ready", include_in_schema=False)
async def readiness(db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}
```

Add `HEALTHCHECK CMD curl -f http://localhost:8000/live || exit 1` to the Dockerfile.

---

#### INF-05 — Docker image runs as root (MEDIUM)

**Status (2026-05-12):** Resolved. UID 1001 `appuser` added to Dockerfile; files chowned to `appuser`; `USER appuser` set.

**Location:** `Dockerfile`

No `USER` instruction is set. If a container escape vulnerability is exploited, the attacker has root on the host kernel namespace.

**Recommendation:**

```dockerfile
RUN useradd -r -u 1001 -g root appuser && chown -R appuser /app
USER appuser
```

---

#### INF-06/07/08 — docker-compose production hygiene (LOW)

- Port 5432 exposed to host — remove in production; Postgres should only be reachable from the app container network
- Source-code bind-mounts — development convenience only; use `docker-compose.prod.yml` without them
- Test dependencies (`pytest`, `pytest-asyncio`) in production container — move to `requirements-dev.txt`

---

### 3.4 Scalability & State Architecture

---

#### SC-01 — In-process rate limiting fails under horizontal scaling (HIGH)

**Location:** `app/main.py:322`

SlowAPI stores rate limit counters in process memory. Two containers each maintain independent counters — users get `N × rate_limit` where N is the number of instances. The per-user AI rate limits protecting Groq API spend become meaningless the moment a second replica is deployed.

**Recommendation:** Configure SlowAPI with a Redis backend:

```python
limiter = Limiter(key_func=_rate_limit_key, storage_uri=settings.redis_url)
```

---

#### SC-02 — In-process WebSocket state and caches cannot invalidate across replicas (HIGH)

**Location:** `app/main.py:4078`, `app/protocol_engine.py:34-237`, `app/main.py:89`

```python
_LEXI_GROUP_WS: dict[str, dict[WebSocket, str]] = {}  # in-process only
@lru_cache(maxsize=256)  # per-process, no cross-replica TTL
```

Three distinct problems:

1. **Lexi Group WebSocket membership** — participants connecting to different replicas cannot exchange messages.
2. **Agency config cache** — mutable config updated via the UI serves stale data on other replicas until their process restarts.
3. **Background workers** — run per-process; with N replicas the TTL scrub and Lexi phase advancement run N times, causing duplicate writes.

**Recommendation:**

- Move Lexi Group real-time messaging to Redis Pub/Sub.
- Move mutable agency config cache to Redis with a 60-second TTL; keep `lru_cache` for static protocol files.
- Move background workers to a singleton task queue (ARQ or Redis distributed lock) so only one instance runs them.

**Migration coupling note:** `app/scenario_engine.py` uses `lru_cache(maxsize=32)` on `load_scenario()`, which caches scenario dicts keyed by file path. This works correctly while scenarios are platform-only JSON files. When instructor-authored scenarios are built (DB-resident, per-tenant), the file-path-keyed `lru_cache` cannot serve them and will require replacement with a short-TTL Redis cache or a per-request DB lookup. Do not build instructor-authored scenario storage on top of the current file-based loader — migrate to the DB-seeded catalog (see BIZ-06) before that feature is implemented.

---

#### SC-03 — Vitals WebSocket opens a new DB session every 3 seconds per connection (MEDIUM)

**Location:** `app/main.py:10713-10729`

50 concurrent simulations → 1,000 DB queries/minute just for vitals polling before any user actions. At 200 concurrent sessions the connection pool saturates.

**Recommendation:** Push vitals updates from the intervention write path to a Redis channel keyed by `session_id`. The WebSocket handler subscribes and forwards. A 30-second heartbeat handles new subscribers. Eliminates the polling loop entirely.

---

#### SC-04 — Background task crash exits silently (MEDIUM)

**Location:** `app/main.py:782-805`

If `_ttl_scrub_worker` or `_lexi_group_phase_worker` raises an unhandled exception, the asyncio Task is abandoned with no alert. The TTL scrub stops running (free-text data accumulates). Lexi groups get stuck.

**Recommendation:** Wrap each worker in a supervisor:

```python
async def _supervised(name: str, factory):
    while True:
        try:
            await factory()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.error(f"{name}.crashed", exc_info=True)
            sentry_sdk.capture_exception()
            await asyncio.sleep(30)
```

---

#### SC-05 — LLM calls have retry logic but no concurrency cap or circuit breaker (MEDIUM)

**Location:** `app/ai_client.py:35`, `app/ai_client.py:645`

During a thundering herd (40 students finishing a scenario simultaneously), retry queues fire concurrently without bound. The retry storm amplifies load on Groq rather than absorbing it.

**Recommendation:**

- Add `asyncio.Semaphore` per model tier (debrief cap = 8, chat cap = 20).
- Add a circuit breaker that opens after sustained error rates and returns a friendly degraded response.
- Consider an asyncio queue with a worker pool for debrief calls specifically.

---

### 3.5 Performance

---

#### PERF-01 — `authFetch` forces `cache: "no-store"` on all authenticated GETs (MEDIUM)

**Location:** `static/js/app.js:4984`

Every dashboard load, progress fetch, notebook read, and reference card forces a full server round-trip with no caching.

**Recommendation:** Use endpoint-specific `Cache-Control` headers from the server. Dashboard and progress data: `Cache-Control: private, max-age=30`. Scenarios and reference cards: ETags with conditional GET. `no-store` stays on live session endpoints only.

---

#### PERF-02 — Static asset version cache fragility (MEDIUM)

**Location:** `app/main.py:15147-15150`

Any URL with `?v=` gets `max-age=31536000, immutable`. A file deployed without a version bump is served stale for a year. This already surfaced in the map-image issue.

**Recommendation:** Generate `?v=` parameters from a content hash (`sha256(file_content)[:8]`) at build time, not from a manually incremented string. Content-addressed versioning is guaranteed to change when the file changes.

---

#### PERF-03 — Notebook unlock validation scans full session history (MEDIUM)

**Location:** `app/main.py:14882`

Unlock conditions load every qualifying session for a user/scenario in Python. This becomes a full table scan per unlock check as session histories grow.

**Recommendation:** Express each condition as a bounded DB query (`EXISTS` or `COUNT ... LIMIT 1`). Add a composite index on `(user_id, scenario_id, ended_at)`.

---

### 3.6 Code Quality & Maintainability

---

#### QA-01 — `app/main.py` is a 15,556-line monolith (HIGH) *(current as of 2026-05-12)*

Contains: startup seeding, JWT auth, middleware, 175 route handlers, 222 async functions, 78 Pydantic models, and utility helpers. Every merge conflict touches the whole file; CI diffs are unreviewed noise. Directly conflicts with the repo rule in `CLAUDE.md`: *"Do not add new routes or Pydantic models to `main.py`."*

**Recommendation:** Decompose into routers (Phase 4 checklist):

```
app/
  routers/
    auth.py         # /api/register, /api/token, /api/token/switch, /api/me, /api/auth/*
    sessions.py     # /api/sessions, /api/chat, /api/interventions, /api/findings, debrief
    scenarios.py    # /api/scenarios, /api/protocols, /api/ws-ticket
    lexi.py         # /api/lexi/*, /ws/lexi-group/*, /ws/vitals/*
    minigames.py    # /api/me/minigames/*, /api/me/drills/*
    agency.py       # /api/agency/*, /api/admin/*, /api/scorm/*
    notes.py        # /api/notes/*, /api/me/notebook/*
  schemas.py        # All Pydantic request/response models (currently inline in main.py)
  dependencies.py   # get_active_context, get_instructor_context, _extract_token, etc.
```

**Done criteria (Phase 4 gate):**
- `wc -l app/main.py` is under 500 lines
- `grep -c "@app\." app/main.py` returns 0 route handlers — only `app.include_router()` calls and bootstrap wiring remain
- `grep -c "class.*BaseModel" app/main.py` returns 0 — all Pydantic models moved to `app/schemas.py`
- Full test suite (`pytest`) passes with no regressions after all router extractions
- CI enforces: a linter rule or pre-commit hook rejects new `@app.get/post/put/delete/patch` decorators directly in `main.py`

**Migration discipline:** Extract one router at a time. Run the full test suite after each extraction before starting the next. Never move more than one router in a single PR — diffs must be reviewable.

---

#### QA-02 — `static/js/app.js` is a 28,827-line global-state monolith (HIGH) *(current as of 2026-05-12)*

Mixes state management, API fetching, WebSocket/SSE lifecycle, DOM manipulation, game engines, and routing in a single file. UI desync bugs are likely when WebSocket frames drop or SSE streams reconnect. Frontend logic is untestable without a DOM environment. The file also contains stale comments that no longer reflect current implementation (tracked as QA-07).

**Recommendation:** Introduce a build step (esbuild or Vite — no framework required). Decompose into modules (Phase 4 checklist):

```
static/src/
  api.js            # authFetch, _silentRefresh, API constants, base URLs
  auth.js           # Login/logout, token lifecycle, CSRF token management
  state.js          # Canonical global state object (replaces scattered let/var globals)
  screens.js        # showScreen(), navigation, overlay management
  session.js        # Scenario session lifecycle, chat, SSE stream, debrief rendering
  vitals.js         # Vitals WebSocket, HUD updates
  games/
    cpr.js          # CPR challenge engine
    gcs.js          # GCS calculator engine
    dmist.js        # DMIST builder engine
    vitals_trend.js # Vitals trend spotter engine
  map.js            # Map rendering, prerequisite gates, fog-of-war
  lexi.js           # Lexi Group WebSocket, companion chat
  logic/            # Pure functions (no DOM), testable with Vitest
    scoring.js      # Score display calculations
    gcs_calc.js     # GCS arithmetic
    timing.js       # Timer/interval utilities
```

**Done criteria (Phase 4 gate):**
- `static/js/app.js` no longer exists as a hand-authored monolith (it may exist as a generated bundle, but `static/src/` is the source of truth)
- `static/src/` directory exists with clearly named modules matching the structure above
- `npm test` (Vitest) passes for all pure-logic functions in `static/src/logic/` with no DOM dependency
- ESLint `no-unsanitized/property` rule is enabled and passes on all `static/src/` code with zero violations
- Once `no-unsanitized` passes cleanly: switch CSP from `Content-Security-Policy-Report-Only` to `Content-Security-Policy` enforcement mode (this is the gate for closing S-04 and S-08 fully)

**Migration discipline:** The current `app.js` continues to serve users until the modular build is complete and tested end-to-end. Do not ship half-decomposed source — the build output must replace the monolith atomically.

---

#### QA-03/04 — No background task supervision; no global 500 handler (MEDIUM)

**Status (2026-05-12):** Resolved. `_supervised(name, coro_fn)` wrapper deployed; `_lexi_group_phase_worker` and `_ttl_scrub_worker` both wrapped — catches non-`CancelledError` exceptions, logs via structlog `log.exception("background_task.crashed", task=name)`, sleeps 30s and restarts. Note: no explicit `sentry_sdk.capture_exception()` call in `_supervised()` — background task crashes surface in structlog only; Sentry capture for background crashes is pending (add `sentry_sdk.capture_exception()` after the `log.exception` call). Global `@app.exception_handler(Exception)` returns `{"detail": "Internal server error"}` with status 500; full exception logged server-side via `log.exception("unhandled_exception", ...)`. Note: no explicit `sentry_sdk.capture_exception(exc)` in the handler either — Sentry's FastAPI ASGI integration may capture these automatically, but explicit capture should be added for certainty.

See SC-04 for supervision detail. For the global exception handler:

```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_exception", path=request.url.path)
    sentry_sdk.capture_exception(exc)  # add explicit capture — ASGI integration may not catch all paths
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
```

---

#### QA-07 — Stale code comments no longer reflect current implementation (LOW)

**Location:** `static/js/app.js:22` and other accumulated comment debt throughout the codebase

**Problem:** Several comments describe behavior that has been superseded. The most concrete example is:
```js
authToken: null,  // JWT stored here and in localStorage
```
This comment was accurate before Phase 1b (S-02) moved auth to httpOnly cookies and removed all `localStorage` JWT storage. The comment now actively misleads any developer reading it into thinking JWT storage still works via `localStorage`. Similar residue exists throughout `app.js` and `main.py` where architectural changes (auth, CORS, WebSocket ticketing) were made but surrounding comments were not updated.

**Why this matters beyond cosmetics:** When the codebase is dense and the files are large, future developers — and AI coding agents — make decisions based on comments. A wrong comment on a security-sensitive code path is a latent mistake vector. The `authToken` comment is the clearest example, but any comment describing a superseded auth or trust-boundary mechanism is in the same risk category.

**Recommendation:** Sweep stale comments as part of Phase 4 decomposition work — not before, because touching the monolith files now would create unnecessary conflicts with the pending router and module extraction work. Specifically:
- Remove or correct all comments referencing localStorage JWT storage
- Remove or correct all comments describing the Bearer-header auth flow (now cookie-only)
- Remove or correct all comments describing wildcard CORS (now allowlist-based)
- Search for other "stored here and in" / "fallback to" / "TODO: migrate" patterns that may describe superseded transitional behavior
- As part of the `no-unsanitized` ESLint pass, add a comment-hygiene note to the PR checklist

**Done criteria:** No comment in production-serving files describes a security mechanism that no longer applies. Verified as part of Phase 4 code review.

---

#### QA-05 — Client-side game progress stored in localStorage only (MEDIUM)

Progress flags that gate learning pathways (map unlocks, phase advancement) must be server-authoritative. `localStorage` is acceptable only as a fast local cache, reconciled against server state on login.

---

#### QA-06 — LLM structured output has no schema validation (MEDIUM)

LLM responses expected as structured JSON (debrief, extraction) have no validation before use. Model drift or unexpected formats produce silent downstream corruption. This is marked MEDIUM (not LOW) because structured LLM output feeds scoring, debrief coaching, and evidence packets — malformed output is a production stability and auditability risk, not cosmetic cleanup.

**Recommendation:** Parse all structured LLM output through a Pydantic model immediately after receipt. On `ValidationError`:
- Do **not** log any portion of the raw LLM response to structlog or Sentry — even a truncated prefix can contain the start of a narrative or DMIST entry, making error tracking a secondary PHI sink.
- Log a redacted diagnostic only: model name, response character length, SHA-256 hash of the raw output (for deduplication without exposing content), and the first validation error message. Apply the same scrubber function used in the Sentry `before_send` hook.
- If a local diagnostic path is needed (e.g., a temporary file on disk or a dedicated secure log stream), make its retention policy explicit (maximum 24 hours) and route it separately from general application logs.
- Return a graceful fallback to the client.

---

### 3.7 Observability & Operations

---

#### OBS-01 — No error tracking service (HIGH)

**Status (2026-05-12):** Resolved. See INF-01.

Covered under INF-01. Repeated here because it is both an infrastructure and an observability gap.

---

#### OBS-02 — `ai_client.py` uses stdlib `logging` instead of structlog (MEDIUM)

**Status (2026-05-12):** Resolved. `import logging` / `logging.getLogger` replaced with `from app.logging_config import get_logger` / `get_logger("app.ai_client")`; all 22 `_log.*` call sites updated to structlog keyword-argument style. **Pending:** Live smoke test — confirm `ai_client.py` log lines carry `request_id` in a request context.

**Location:** `app/ai_client.py:8`, `app/ai_client.py:16`

```python
import logging
_log = logging.getLogger(__name__)
```

`ai_client.py` emits unstructured text logs that will not carry request IDs or be parseable as structured events by log aggregators.

**Recommendation:** Replace with `from structlog import get_logger` / `log = get_logger("app.ai_client")` throughout.

---

#### OBS-03 — No distributed tracing (MEDIUM)

The `request_id_middleware` is the correct foundation but there are no trace spans across DB calls, LLM API calls, or background tasks.

**Recommendation:** Add OpenTelemetry with FastAPI and SQLAlchemy auto-instrumentation. Export to a backend (Jaeger, Grafana Tempo, Honeycomb, or Datadog).

---

#### OBS-04 — No APM or metrics dashboard (MEDIUM)

No response time percentiles, error rates, or LLM latency histograms. Performance regressions will be noticed by users before the team.

**Recommendation:** Expose a Prometheus `/metrics` endpoint. Alert on p99 latency > 2s, error rate > 1%, LLM failure rate > 10%.

---

### 3.8 Dependencies & Supply Chain

---

#### DEP-01 — `python-multipart==0.0.9` has known CVEs (HIGH)

**Status (2026-05-12):** Resolved. Updated to `python-multipart>=0.0.27`; `pip-audit -r requirements.txt` exits clean; CI audit step added.

**Location:** `requirements.txt:15`

Affected by multiple denial-of-service vulnerabilities (CVE-2026-42561, CVE-2026-40347). Safe version: ≥0.0.27. One-line fix with no API impact.

---

#### DEP-02 — No automated dependency scanning or supply-chain hardening (MEDIUM)

There is no automated process to detect newly published CVEs against pinned dependencies, no image scanning, and no SBOM. A vulnerability in any dependency will not be surfaced until manually checked.

**Recommendation:**

- **Dependabot or Renovate:** Enable in the GitHub repository to auto-open PRs for dependency updates. Configure with a weekly schedule and grouping to reduce noise.
- **pip-audit in CI:** Add `pip-audit -r requirements.txt` as a CI check. Fails the build if a known CVE exists in any pinned version.
- **Docker image scanning:** Add `docker scout cves` or Trivy to the CI pipeline to scan the built image.
- **Pinned hashes:** Consider `pip-compile` with `--generate-hashes` to produce a `requirements.lock` with content-addressed pins, preventing dependency substitution attacks.
- **SBOM generation:** Add `cyclonedx-bom` or `syft` to the release pipeline to produce a Software Bill of Materials for regulatory and enterprise sales purposes.

---

### 3.9 Business Operations

---

#### BIZ-01 — No billing or entitlements infrastructure (MEDIUM)

The application references subscription tiers (Open/Free, Pro Agency, Enterprise) and tier-restricted features (e.g., PDF extractions capped at 5/month for Pro). There is no architectural plan for enforcing these limits or for integrating a billing provider. Subscription-gated logic added without this foundation will be scattered across route handlers with no central enforcement point.

**Recommendation:**

1. **Billing provider:** Integrate Stripe. Handle `customer.subscription.updated` and `invoice.payment_failed` webhooks to update `agencies.subscription_status` and `agencies.plan` in the database. Make the webhook handler idempotent using Stripe's `event.id` for deduplication.

2. **Centralized entitlements helper:** Create a single `has_feature(agency: Agency, feature: str) -> bool` function that reads the agency's plan from the database (Redis-cached via SC-02a). Gate restricted endpoints with this function — do not scatter plan checks across route handlers.

   ```python
   if not has_feature(agency, "pdf_extraction"):
       raise HTTPException(403, "Feature not available on your plan")
   ```

3. **Usage counters:** Track per-agency, per-month usage for metered features in the database. Reset counters on billing cycle boundaries triggered by the billing webhook.

---

#### BIZ-02 — File uploads processed on-server without cloud storage or malware scanning (MEDIUM)

Agency admins can upload SOP PDFs for AI extraction. Processing and storing user-supplied files directly on the application server creates risks: disk exhaustion, file-type confusion attacks, and malware reaching the AI processing pipeline.

**Recommendation:**

1. **Pre-signed upload URL:** Use AWS S3 or GCP Cloud Storage. On upload request, the backend generates a short-lived pre-signed PUT URL and returns it to the client. The client uploads directly to cloud storage — the file never passes through the application server.

2. **Backend fetch for processing:** After upload, the backend fetches the object from cloud storage for AI extraction. The file never lands on the app container filesystem.

3. **Malware scanning:** Before AI processing, run the file through ClamAV (self-hosted) or a cloud scanning API. Reject and quarantine files that fail the scan. Do not pass unscanned files to the LLM.

4. **File type validation:** Validate MIME type server-side using `python-magic` to verify the file header matches `application/pdf` — do not trust the client-supplied `Content-Type`.

5. **Object lifecycle:** Set an S3/GCS lifecycle policy to delete processed objects after 30 days (or after extraction is confirmed complete), aligned with the existing PHI TTL scrub policy.

---

#### BIZ-03 — No transactional email provider (MEDIUM)

Phase 4 adds password reset and email verification (S-09), which require sending transactional emails. There is no email infrastructure currently planned. Without it, Phase 4 S-09 work cannot be completed.

**Recommendation:**

1. **Provider:** AWS SES (cheapest at scale), Resend (developer-friendly, generous free tier), or SendGrid. Choose one before starting Phase 4 S-09 work.

2. **Bounce and complaint webhooks:** Configure the provider's webhook to write `email_bounce` and `email_complaint` events to the database. Flag the affected user account. A training officer who silently stops receiving protocol-change notifications because their email bounced is a product failure — the system must know about delivery failures.

3. **Settings fields:** Add `email_from: str = ""` and `email_provider_key: str = ""` to `Settings`. When `email_from` is empty, email-dependent flows return a clear error rather than silently failing.

4. **Template management:** Store email subject and body templates as Jinja2 templates in `app/email_templates/`. Render them server-side — never construct email HTML by string concatenation.

5. **Rate limiting:** Apply per-user rate limiting to password-reset and verification requests to prevent email abuse.

---

#### BIZ-04 — No full-text search strategy (LOW)

As session history, user notes, and training records accumulate, agency admins will need to search across historical data (e.g., find sessions for a student by name, search debrief summaries by keyword). `ILIKE '%text%'` queries cause full table scans and will degrade performance at scale.

**Recommendation:** PostgreSQL built-in full-text search is sufficient — no need for Elasticsearch.

1. Add `tsvector` columns to `sim_sessions` and `user_notes` (the primary search targets).
2. Create `GIN` indexes on those columns.
3. Populate via an Alembic migration that runs `to_tsvector('english', ...)` on existing data.
4. Use triggers or application-level updates to keep `tsvector` columns current on write.
5. Replace any `ILIKE '%text%'` queries on these tables with `@@ plainto_tsquery('english', :query)`.

---

#### BIZ-05 — No data privacy offboarding or account deletion strategy (MEDIUM)

The application has no mechanisms for user account deletion or agency offboarding. These are required for GDPR (EU) and CCPA (California) compliance before any public launch with real user data.

**Key problem:** Hard-deleting a user row violates referential integrity — the user's ID is referenced in immutable debrief records, SOP approvals, and audit logs. The correct pattern is anonymization, not deletion.

**Recommendation:**

1. **Anonymization as deletion:** Define a `DELETE` action as anonymization:
   - Set `first_name = "Deleted"`, `last_name = "User"`, `email = "deleted_<uuid>@redacted.invalid"`
   - Store an HMAC-SHA256 of the original email in a lookup column so GDPR deletion can be confirmed without storing the original value
   - Revoke all refresh tokens immediately
   - Preserve the `user_id` UUID in all historical records for referential integrity

2. **Self-service deletion:** Add `POST /api/me/delete-account` that initiates the anonymization flow after re-authentication (confirm password required).

3. **Agency offboarding:** Define what happens when an agency cancels:
   - 30-day read-only grace period before data is purged
   - Bulk data export available during grace period
   - After grace period: anonymize all user records, delete agency-specific content

4. **Data export:** Add `GET /api/agency/export` (admin-only) that produces a downloadable ZIP of agency training records as CSV/JSON. Required for GDPR data portability and for enterprise customers who want their training data.

5. **Privacy policy alignment:** Before launching publicly, confirm the implementation matches any published privacy policy. If HIPAA BAAs are in scope, engage legal before finalizing the deletion/retention policy.

---

#### SCORE-01 — Corroboration prepass is an LLM making adjudication decisions (HIGH)

**Status (2026-05-11):** Partially addressed. Deterministic corroborator implemented in `app/corroboration.py`; shadow mode (observe-only) wired in `app/ai_client.py` behind `shadow_deterministic_corroboration` flag. LLM prepass remains active for scoring. Flip to deterministic pending: 20-session shadow run + manual log review. See `docs/SCORING_IMPROVEMENT_PLAN.md` Group C for rollout criteria.

**Location:** `app/ai_client.py` — `_run_corroboration_prepass()`

The corroboration prepass sends student DMIST and narrative text to an LLM and asks it to identify "unsupported claims" — i.e., things documented by the student that are not supported by the run evidence. The resulting `dmist_unsupported_claims` and `narrative_unsupported_claims` are used to calculate score deductions.

**Precise risk:** This is a scoring adjudication decision (did the student document something they did not do?) being made by an LLM rather than by code. LLM comparison of a student claim against evidence provided in a prompt has meaningful false positive and false negative rates and will vary run-to-run for the same inputs, undermining the "identical runs → identical scores" guarantee. If the prepass fails or times out, the system falls back to `_PREPASS_FALLBACK` which skips corroboration entirely — silently reducing documentation accuracy scoring to structural checks only.

**Correct approach:** The corroboration comparison is fully deterministic. For each claim type:
- Documented an intervention → check against `Intervention` records directly by `intervention_key`
- Documented a vital finding → check against `SessionFinding` vitals records by type and timestamp
- Documented an assessment → check against `SessionEvent` `explicit_assessment` records by `event_key`

Replace the LLM prepass with a direct evidence packet lookup: "this claim appears in the DMIST — does a corresponding Tier 1 record exist?" If yes, supported. If no, unsupported. No LLM call required. The prepass call can be retired after the deterministic replacement is validated against the existing test suite.

**Priority:** Address before public launch. This is a scoring integrity gap, not just a code quality issue.

---

#### SCORE-02 — `EVALUATE`-tagged critical actions pass to LLM for determination (HIGH)

**Status (2026-05-11; updated 2026-05-16):** Closed for the current scenario set. B1/B4 audit confirmed all 96 critical actions now have deterministic paths: 29 pre-credit actions, 3 ALS/intercept actions routed through P2 by `id: "als_intercept"`, and 64 evidence-backed actions. There are no current P4 `EVALUATE_RISK` actions. ALS co-dispatch is now derived from active agency configuration during scenario adaptation and consumed through deterministic `applicable_if` gates; scenarios and overlays should not encode co-dispatch grace locally. Authoring validator now warns on new required actions without an evidence dict. See `docs/SCORING_IMPROVEMENT_PLAN.md` B1 audit table for the full breakdown.

**Location:** `app/ai_client.py` — `_build_evidence_packet()` critical actions classification

Critical actions classified as `EVALUATE` are passed to the debrief LLM with the instruction that "determination is from scene transcript only." This means the LLM is making a pass/fail adjudication decision for these items, not explaining a pre-determined result.

**Precise risk:** `EVALUATE` is a hidden LLM adjudication path. For any item in this state, the scoring outcome depends on LLM inference rather than deterministic evidence — directly violating the backend authority rule in `SCORING_ENGINE_ARCHITECTURE.md §1`. Identical runs can produce different scores. Instructor appeals cannot be traced to a specific evidence record.

**Correct approach:** Every item currently reaching `EVALUATE` status must have a defined Tier 1 or Tier 2 path:
- If the action should produce a backend record → define the `SessionEvent` emission and create a Tier 1 match spec
- If the action can only be inferred from transcript → write a deterministic Tier 2 regex rule and add test coverage per `SCORING_ENGINE_ARCHITECTURE.md §10`
- `EVALUATE` should be treated as a scoring debt marker that represents items needing Tier 1/2 work, not a permanent design pattern

**Priority:** Audit all current `EVALUATE` items and assign a Tier 1 or Tier 2 path to each. Block authoring of new scenarios with critical actions that would default to `EVALUATE`.

---

#### SCORE-03 — No pre-debrief gate for authored content fields (MEDIUM)

**Status (2026-05-11):** Fixed. `_validate_debrief_content()` added to `app/scenarios/vocabulary.py`; runtime guard added in `evaluate_and_generate_debrief()` — raises on missing `condition_background`, `key_teaching_points`, or `common_mistakes` in dev; logs ERROR and falls back to explicit no-hallucination instruction block in production. All 17 scenario JSONs validated. Tests passing.

**Location:** `app/ai_client.py` — `evaluate_and_generate_debrief()`

The debrief prompt uses `debrief_info.condition_background`, `key_teaching_points`, and `common_mistakes` from the scenario JSON as authored clinical content. If these fields are absent, the prompt silently omits the corresponding sections and the LLM generates clinical background from its training data.

**Precise risk:** LLM-generated clinical background in a debrief is the primary hallucination surface in the coaching output. The authored content policy (`AI_ARCHITECTURE.md §3.5`) explicitly prohibits LLM-generated pathophysiology, drug mechanisms, and treatment rationale — but silent omission defeats this policy without any code enforcement. As scenario count grows, missing fields are guaranteed to occur and will not be caught until a student or instructor notices incorrect clinical content.

**Fix:** Add a pre-debrief validation call before the LLM debrief is triggered:
```python
def _validate_authored_content(scenario: dict) -> list[str]:
    missing = []
    debrief_info = scenario.get("debrief_info", {})
    if not debrief_info.get("condition_background"):
        missing.append("debrief_info.condition_background")
    if not debrief_info.get("key_teaching_points"):
        missing.append("debrief_info.key_teaching_points")
    if not debrief_info.get("common_mistakes"):
        missing.append("debrief_info.common_mistakes")
    return missing
```
If `missing` is non-empty, surface the scenario authoring error to the debrief pipeline and log at ERROR level. In development, raise. In production, fall back to a prompted instruction block that explicitly forbids the LLM from generating clinical background for the missing sections, rather than letting it fill silently. Flag the session for instructor review.

**Priority:** Quick fix — implement the validation gate before adding new scenarios.

---

#### SCORE-04 — Subscores LLM output has no range or type validation (MEDIUM)

**Status (2026-05-11):** Fixed. `_SUBSCORE_RANGES` dict added with per-category `(min, max)` bounds; range check added in `_extract_required_debrief_subscores()` — out-of-range values log ERROR, trigger the existing per-key regex fallback, and are never passed to score arithmetic. Tests passing; all calibration fixtures unaffected.

*(See also QA-06 — this finding escalates its severity from Scale to SaaS for scoring integrity reasons.)*

**Location:** `app/ai_client.py` — subscores JSON parsing after debrief LLM call

The current parser checks for required key presence but does not validate that returned values are integers, are within valid ranges (0–100 per category), or match the declared category maximums. The LLM could return `"clinical_performance": 150`, `"dmist": -5`, or `"professionalism": "excellent"` and these would pass the current check.

**Precise risk:** For `legacy_ai` categories (documentation, professionalism), the LLM fills in the actual score integers. These values flow directly into score arithmetic. An out-of-range or wrong-type value produces a nonsensical final score with no error surfaced to the operator.

**Fix:** Add a Pydantic validation model for the subscores response:
```python
class SubscoresResponse(BaseModel):
    clinical_performance: int = Field(ge=0, le=100)
    narrative: int = Field(ge=0, le=20)
    scope_adherence: int = Field(ge=0, le=100)
    dmist: int = Field(ge=0, le=20)
    professionalism: int = Field(ge=0, le=10)
```
Reject out-of-range values as a parsing failure rather than accepting them silently. Fall back to the existing per-key regex fallback on parse failure so the retry path is preserved.

---

#### SCORE-05 — CLOSED: False finding

**Status:** Closed — no code change needed.

Code review of `app/ai_client.py` lines 5831 and 5841 confirmed the debrief `evaluate_and_generate_debrief()` call uses `temperature=0.4`, not 0.7. The 0.7 temperature appears only on the Lexi companion chat call (`ai_client.py:2233`), which produces no scored output. The finding was based on an incorrect temperature assumption. `AI_ARCHITECTURE.md §3.6` has been corrected.

---

#### BIZ-06 — Scenario content depth is insufficient for a paid launch (HIGH)

The platform currently has one playable scenario (`orientation_01.json`). The protocol library is deep, but the scenarios are the product — they are what an instructor assigns, what a learner practices, and what the debrief and remediation loop operates on. A hardened, instrumented deployment with one scenario has no retention and cannot be sold to an agency.

**Target before any paid or public launch:** 20–30 coherent playable scenarios distributed across the four planned districts:

| District | Minimum scenarios |
|---|---|
| Pediatric Community Response | 6–8 |
| Adult Medical Response | 6–8 |
| Adult Trauma Response | 5–7 |
| Complex Incident Response | 3–5 |

Each scenario must conform to `docs/SCENARIO_DESIGN_EMS.md`, pass vocabulary validation, and include a complete scoring rubric before it is considered launch-ready.

**Prerequisite for instructor-authored scenarios:** Before building instructor-authored scenario generation, migrate platform scenarios to a DB-seeded catalog (see SC-02 migration coupling note). Platform JSON files remain the authoritative authoring source and stay version-controlled; a seed process imports them into the `scenarios` table on deploy. Instructor-authored scenarios write to the same table with `source = 'instructor'` and a `tenant_id`. This unifies the runtime path and avoids two incompatible scenario sources at query time.

**Content gap is not a code problem**, but it is a launch gate in the same way missing billing enforcement is. Address it in parallel with the Phase 1–2 hardening work, not after.

---

### 3.10 Scope Authority & Rubric Cascades (Deferred — Post-SCORM)

These three gaps were identified in a Codex architectural review (2026-05-18) and confirmed against the live codebase.  All three are explicitly deferred until after the SCORM/pilot launch.  They are documented here to prevent future work from partially addressing them incorrectly without the full design context.

#### SCOPE-01 — Provider scope is partially scenario-authored (P1)

**Location:** `app/scoring_service.py` `_intervention_in_scope()` reads `within_bls_scope`, `within_aemt_scope`, `within_mfr_scope` from scenario intervention data.

**What this means:** Base scope flags for non-expansion interventions are authored in scenario JSON rather than derived from a central protocol/scope registry.  The MCA expansion adaptation path in `adapt_scenario_to_context()` correctly overrides `within_bls_scope` for expansion-gated items at runtime; the gap is that genuinely ALS-only interventions carry their scope authorization in scenario content instead of a canonical protocol action registry.

**Why it is acceptable for the pilot:** Scope is authored once per intervention under reviewer oversight, and `test_scenario_contracts.py::TestInterventionScope` enforces that expansion-gated items cannot be mis-authored.  The gap is a provenance question (where is scope truth?), not a runtime correctness question for the current single-jurisdiction deployment.

**Target architecture:** A central `scope_resolver(action_id, provider_level, protocol_snapshot, agency_carried_equipment, mca_expansions)` that returns scope classification.  Requires a protocol action ID registry (Phase 2C) and agency carried-equipment table (Phase 4).  Do not start until both prerequisites exist.

**Trigger to start:** Second agency onboard with different BLS/AEMT scope than Michigan, OR legal/compliance review identifies scope provenance as an audit risk.

---

#### SCOPE-02 — Multi-tenant rubric overlay cascade is not fully active (P2b)

**Location:** `app/rubric_loader.py` `load_scenario_overlay()` resolves only `overlays/{scenario_id}.json`.  The generalized state → MCA → agency/profile → scenario cascade is not implemented.

**What this means:** Rubric customization is currently limited to scenario-level overlays.  State-level or agency-level rubric modifications (e.g., a state that adds a mandatory Narcan documentation item to every respiratory scenario) cannot be expressed without a scenario-level file.

**Why it is acceptable for the pilot:** Active SOP scoring overlays (generated from `effective_protocol_excerpt` by `_apply_protocol_scope_checklist_overlay()`) cover the agency scope differences that matter for the Michigan/PFD pilot.  The overlay cascade is not needed until a second agency with different rubric requirements onboards.

**Target architecture:** A layered resolver: `load_cascaded_overlay(scenario_id, call_type, state_id, mca_id, agency_id)` that composes ops from all applicable overlay files in priority order (scenario overrides agency overrides MCA overrides state).

**Trigger to start:** Agency onboards with a documented rubric customization requirement that cannot be expressed via SOP overlays or scenario-level overlay files.

---

#### SCOPE-03 — Direct protocol file resolution is agency-agnostic (P3)

**Location:** `app/protocol_engine.py` `get_resolved_protocol()` accepts `agency_id` but deletes it immediately.  Protocol content is file-backed and not yet agency-aware.

**What this means:** All agencies see the same protocol file content for a given protocol ID.  Agency-specific protocol variations (e.g., a state formulary difference) cannot be expressed without a separate protocol file.

**Why it is acceptable for the pilot:** Scoring always operates on `session.effective_protocol_excerpt` (the session-pinned snapshot), not live protocol file reads.  The `agency_id` parameter is frozen into the interface now so callers do not need to change when Phase 2 snapshot resolution is implemented.  The risk of future code accidentally bypassing the excerpt for scoring is mitigated by the existing `authoritative` flag check in `_apply_protocol_scope_checklist_overlay()`.

**Target architecture:** `get_resolved_protocol(agency_id, protocol_id)` resolves from a DB-backed protocol snapshot table filtered by agency, compiled on protocol publish.  Requires the Phase 2C protocol compile/fan-out pipeline.

**Trigger to start:** Agency onboards with a documented protocol variation requirement, or Phase 2C compile pipeline is prioritized.

---

## 4. Phased Implementation Plan

Phases are ordered by risk reduction. Phase 1a can be completed in days with no architectural coordination. Phase 1b is a coordinated auth architecture change — do not attempt it without backend/frontend pairing. Phases 2 and 3 can overlap in parallel tracks. **Do not add Gunicorn workers until Phase 3 in-process state is externalized.**

---

### Phase 1a: Immediate Security Fixes (Days 1–3)

*Target: Eliminate the known CVE, close the open CORS policy, disable production API docs, and add security headers. These are low-coordination changes with high impact.*

#### Checklist

**DEP-01 — python-multipart CVE**
- [x] Update `requirements.txt`: `python-multipart>=0.0.27`
- [x] Run `pip install -r requirements.txt`, verify no conflicts
- [x] Run full test suite; confirm no regressions

**S-01 — CORS**
- [x] Add `allowed_origins: list[str] = ["http://localhost:8000"]` to `Settings` in `config.py`
- [x] Decide `.env` format before implementing: Pydantic-settings expects JSON array by default (`ALLOWED_ORIGINS=["http://localhost:8000"]`); if comma-separated is preferred, add a custom `field_validator` first — do not leave this ambiguous or startup will fail silently in unexpected environments
- [x] Add `ALLOWED_ORIGINS` to `.env.example` with a format comment showing the chosen format
- [x] Update `CORSMiddleware` to use `settings.allowed_origins`, `allow_credentials=True`, explicit methods and headers
- [x] Verify browser preflight (OPTIONS) requests succeed in dev tools after change

**S-05 — Disable API docs in production**
- [x] Set `docs_url=None`, `redoc_url=None`, `openapi_url=None` when `_IS_PROD`
- [x] Confirm `/docs` returns 404 in a local `ENV=production` run

**S-08 — Security response headers**
- [x] Before enforcing CSP, inventory all inline scripts, inline event handlers (`onclick=`, `onload=`, etc.), CDN-hosted fonts or stylesheets, `<audio>` / `<video>` / `<img>` sources, and any `eval()` / `new Function()` usage in `app.js`
- [x] For each inline script or style that cannot be immediately removed, generate a nonce or hash and add it to the `script-src` / `style-src` directive — do not leave CSP disabled while this work is in progress
- [x] Add `SecurityHeadersMiddleware` (or Nginx/Caddy config) setting: HSTS, CSP (with nonces/hashes as needed), X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy
- [x] Deploy CSP in report-only mode first (`Content-Security-Policy-Report-Only: ...; report-uri <endpoint>`) before switching to enforcement mode; choose a collection target — options in ascending complexity: (a) browser console only during local testing (omit `report-uri`, check DevTools), (b) Sentry's built-in CSP endpoint (`https://sentry.io/api/<project>/security/?sentry_key=<key>`), (c) a minimal internal `POST /api/csp-report` endpoint that logs to structlog
- [x] Verify all six headers appear in browser dev tools Network tab
- [x] Confirm no CSP violations appear in the browser console during a full user workflow (login → sim start → debrief)

**DEP-02 (partial) — pip-audit in CI**
- [x] Add `pip-audit -r requirements.txt` step to CI workflow
- [x] Confirm it runs clean after the `python-multipart` update above

#### Phase 1a Gate — Validation Checks

*All of the following must pass before moving to Phase 1b. These checks can be run in under 30 minutes.*

**Dependency CVE**
- [x] `pip-audit -r requirements.txt` exits 0 with no findings
- [x] CI pipeline runs the audit step and is green

**CORS**
- [x] `curl -s -o /dev/null -w "%{http_code}" -H "Origin: https://evil.com" http://localhost:8000/api/me` — confirm no `Access-Control-Allow-Origin: *` in response headers
- [x] `curl -I -H "Origin: http://localhost:8000" http://localhost:8000/api/me` — confirm `Access-Control-Allow-Origin: http://localhost:8000` is present
- [x] Browser preflight (OPTIONS) request to any API endpoint succeeds with correct origin in response

**API docs disabled in production**
- [x] Start app with `ENV=production`; `curl http://localhost:8000/docs` returns 404
- [x] `curl http://localhost:8000/redoc` returns 404
- [x] `curl http://localhost:8000/openapi.json` returns 404

**Security headers**
- [x] `curl -I http://localhost:8000/` shows five enforcement headers: `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`
- [x] The same response shows `Content-Security-Policy-Report-Only` (not `Content-Security-Policy`) — CSP is in report-only mode at this stage; switching to enforcement is a later step after the workflow is confirmed clean
- [x] Note: `Strict-Transport-Security` will appear in the response but has no browser effect until the site is served over HTTPS — verify its presence here; validate browser enforcement in the Phase 2 TLS gate
- [x] Browser console shows zero CSP violations during a full workflow: login → scenario start → chat → end session

---

### Phase 1b: Auth Architecture (Week 1–2)

*Target: Move JWT tokens from localStorage to httpOnly cookies, implement WebSocket ticket auth, and add CSRF protection. This is a coordinated backend/frontend change — plan a dedicated pairing session.*

#### Checklist

**S-02 — Cookie-based auth**
- [x] Change `POST /api/token` (login) to `Set-Cookie: pfd_ems_session=<jwt>; HttpOnly; Secure; SameSite=Strict; Path=/`
- [x] Return minimal JSON body — `access_token` removed from all auth responses (Phase 2); frontend uses `_storeAuthFromContext(data)` instead of decoding the JWT from response body
- [x] Add `POST /api/auth/logout` endpoint that clears the session cookie (`Set-Cookie: pfd_ems_session=; Max-Age=0`)
- [x] Remove `localStorage.setItem("pfd_ems_token", ...)` from `app.js`
- [x] Remove `Authorization: Bearer` header injection from `authFetch`
- [x] **OAuth2PasswordBearer dependency:** Replaced all 6 `Depends(oauth2_scheme)` sites with `Depends(_extract_token)`. `_extract_token` reads `pfd_ems_session` cookie first, falls back to `Authorization: Bearer` header. `oauth2_scheme` variable retained but unused.
- [x] Add a signed CSRF double-submit token: HMAC-SHA256 signed `pfd_ems_csrf` non-httpOnly cookie; `csrf_middleware` validates on POST/PUT/DELETE/PATCH when session cookie is present; naive string equality avoided (uses `hmac.compare_digest`)
- [x] `POST /api/auth/logout` is explicitly exempt from CSRF — rationale: logout is idempotent and CSRF-safe (an attacker forcing a logout causes only a denial of convenience, not data loss or privilege escalation; the exemption is consistent with OWASP guidance). No `/api/token/refresh` endpoint exists in Phase 1b.
- [x] **Migration transition window closed (Phase 2):** Bearer-header fallback removed from `_extract_token`; cookie is the sole auth mechanism.
- [x] All 6 auth dependency sites updated; all protected endpoints accept cookie-based auth via `_extract_token` dependency
- [x] **Phase 1b ships with the current 24-hour JWT TTL in the cookie** — token is now in an `httpOnly` cookie and inaccessible to JavaScript. TTL tightened to 60 minutes in Phase 2 (S-07) when refresh token flow is implemented.
- [ ] Smoke-test login, session start, chat, debrief, logout in a browser

**S-03 — WebSocket ticket auth**
- [x] **Storage choice:** `ws_tickets` DB table (`ticket_id UUID PK`, `user_id FK`, `agency_id`, `expires_at TIMESTAMP`, `consumed BOOLEAN`). Auto-created via `Base.metadata.create_all` in database.py lifespan.
- [x] Add `POST /api/ws-ticket` endpoint: inserts a row with a 30-second TTL, returns `{"ticket": "<uuid>"}`
- [x] Update vitals WebSocket client code to fetch a ticket before connecting; pass `?ticket=<uuid>` in URL
- [x] Update vitals WebSocket server handler: atomic `UPDATE ws_tickets SET consumed=TRUE WHERE ... RETURNING user_id, agency_id` — zero rows = reject. No SELECT+UPDATE two-step.
- [x] Repeat for Lexi Group WebSocket
- [x] Expired ticket cleanup added to `_ttl_scrub_worker` (runs inside the existing `async with db:` session)
- [ ] Confirm that opening browser network tab shows no JWT in WebSocket URL

**INF-01 — Error tracking with privacy guardrails**
- [x] Add `sentry-sdk[fastapi]` to `requirements.txt` (and regenerated `requirements.lock`)
- [x] Add `SENTRY_DSN: str = ""` to `Settings` (no-op when empty)
- [x] Implement `_scrub_sentry_event(event, hint)` scrubbing all request context (headers, cookies, body, query_string, env) and any field matching PHI key set or `*_text/*_content/*_narrative` pattern, recursively across `extra`, `contexts`, and breadcrumb data; breadcrumb messages are fully redacted
- [x] `sentry_sdk.init(dsn=..., send_default_pii=False, before_send=_scrub_sentry_event, traces_sample_rate=0.1)` called in lifespan when DSN is set
- [x] Global `@app.exception_handler(Exception)` handler logging to structlog and returning generic 500
- [ ] Trigger a test exception in dev; verify it appears in Sentry and contains no medical free text

**QA-03/04 — Task supervision and global 500**
- [x] `_supervised(name, coro_fn)` wrapper: catches all non-`CancelledError` exceptions, logs to structlog, sleeps 30s and restarts
- [x] Both `_lexi_group_phase_worker` and `_ttl_scrub_worker` wrapped with `_supervised` in lifespan
- [ ] Confirm uncaught exceptions in supervised tasks appear in Sentry (requires DSN configured in test env)

#### Phase 1b Gate — Validation Checks

*All of the following must pass before moving to Phase 2. Run against a staging environment, not local-only.*

**Token storage — no JWT visible to JavaScript**
- [x] Log in; open browser console; run `document.cookie` — output must not contain `pfd_ems_session` (cookie is httpOnly and invisible to JS)
- [x] Run `localStorage.getItem("pfd_ems_token")` in console — must return `null`
- [x] Open Network tab; make any authenticated API call — confirm no `Authorization: Bearer` header is sent

**Cookie attributes**
- [ ] Inspect the `Set-Cookie` header on the login response — confirm all four attributes are present: `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`
- [ ] Confirm `Secure` flag is set (requires HTTPS; test against the staging proxy, not plain localhost)

**Transition window — bearer still accepted** _(Phase 1b historical — Bearer fallback was removed in Phase 2; this gate no longer applies)_
- [x] `curl -H "Authorization: Bearer <valid_jwt>" http://localhost:8000/api/me` — returns 200 (transition window is open) _(was valid during Phase 1b; Phase 2 removed Bearer support — same request now returns 401)_

**CSRF protection**
- [x] `curl -X POST http://localhost:8000/api/sessions -b "pfd_ems_session=<cookie>"` (no `X-CSRF-Token` header) — returns 403
- [x] `curl -X PUT http://localhost:8000/api/agency/members/<id> -b "pfd_ems_session=<cookie>"` (no CSRF token) — returns 403
- [x] Repeat with a valid signed CSRF token in the header — returns 200 or 422 (not 403)

**WebSocket ticket — no JWT in URL**
- [x] Open browser Network tab; trigger a vitals WebSocket connection — confirm the URL is `ws://host/ws/vitals/<id>?ticket=<uuid>` with no JWT present
- [x] Copy the ticket UUID; attempt to open a second WebSocket connection with the same ticket UUID — server rejects with an error (consumed)
- [x] Fetch a ticket but wait 35 seconds before using it — server rejects with expired error

**Sentry — functional and privacy-compliant**
- [ ] Trigger a deliberate test exception (e.g., a temporary `raise RuntimeError("sentry-test")` in a route); confirm it appears in the Sentry dashboard
- [ ] Inspect the Sentry event payload — confirm it contains no cookies, no `Authorization` header, no request body, no fields named `message`, `narrative`, `dmist`, `notes`, `prompt`, or `prompt_payload`; confirm no LLM input or output text is present anywhere in the payload (check `extra`, `contexts`, `request.data`, and `breadcrumbs` sections)
- [ ] Remove the test exception

**Background task supervision**
- [ ] Add a temporary `raise RuntimeError("crash-test")` to `_ttl_scrub_worker`; deploy; observe structlog for the `*.crashed` log entry followed by a restart log within 30 seconds
- [ ] Confirm the crash appears in Sentry
- [ ] Remove the test raise

**Global 500 handler**
- [ ] Hit a route with a deliberate unhandled exception; confirm the HTTP response body is exactly `{"detail": "Internal server error"}` with status 500 — no stack trace, no internal detail in the response body

---

### Phase 2: Deployment & Operations (Week 2–3)

*Target: The application is deployable to a production host with TLS, health probes, non-root container, and operational logging consistency. Single-worker Uvicorn is retained until Phase 3.*

#### Checklist

**INF-03 — Reverse proxy**
- [x] Create `Caddyfile` in repository root
- [x] Configure TLS termination (Caddy: automatic Let's Encrypt)
- [x] Configure WebSocket proxy (Caddy handles upgrades automatically via `reverse_proxy`)
- [x] Set 300s timeout for SSE and long-lived WebSocket connections (`response_header_timeout 300s`)
- [x] Serve `static/` from Caddy directly — not through FastAPI
- [x] Add reverse proxy service (`proxy`) to `docker-compose.prod.yml`

**INF-02 — Container restart (single-worker for now)**
- [x] Add `restart: always` to the `app` service in `docker-compose.prod.yml`
- [x] Document in `docs/DEPLOYMENT.md`: Gunicorn multi-worker is deferred to Phase 3; do not add workers before in-process state is externalized

**INF-04 — Liveness and readiness endpoints**
- [x] Add `GET /live` — process-only check, 200 OK, no DB call
- [x] Add `GET /ready` — DB ping via `SELECT 1`, 200 OK or 503 on failure
- [x] Add `HEALTHCHECK CMD curl -f http://localhost:8000/live || exit 1` to `Dockerfile`
- [ ] Configure orchestrator liveness probe → `/live`, readiness probe → `/ready` (infra/ops task)

**INF-05/06/07/08 — Docker hardening**
- [x] Add non-root user to `Dockerfile` (UID 1001, `appuser`)
- [x] Create `docker-compose.prod.yml` without bind-mounts; Postgres port not exposed to host
- [x] Create `requirements-dev.txt` for `pytest`, `pytest-asyncio`; removed from production `requirements.txt`

**DB-05 — Backup and DR**
- [ ] Evaluate managed PostgreSQL (RDS, Cloud SQL, Neon) — strongly preferred over self-managed
- [ ] If self-managed: configure WAL archiving; set up daily `pg_dump` to object storage (S3 or GCS)
- [ ] Define and document backup retention policy (minimum: 30-day daily, 7-day hourly)
- [ ] Perform and document a restore drill in a staging environment before launch
- [ ] Measure actual query durations for debrief, report generation, and admin analytics endpoints before tightening timeouts
- [x] Set `lock_timeout` and `statement_timeout` at the asyncpg connection level via `connect_args` in `app/database.py` (DB-05); configurable via `.env`
- [x] Start conservatively (`statement_timeout = 60s`); document in `docs/DEPLOYMENT.md` how to tighten per-endpoint
- [ ] Confirm autovacuum is enabled on the PostgreSQL cluster

**S-06 — Staging secret validation**
- [x] Extend secret strength check to reject `changeme` when `ENV` is `staging` or `preview`
- [x] Startup log line recording `ENV=<value>` already emitted by `_log_startup_config()`

**S-07 — JWT TTL and refresh flow**
- [x] Reduce `jwt_expire_minutes` to 60
- [x] Add `POST /api/token/refresh` endpoint with atomic consume and rotation
- [x] Issue refresh tokens as `httpOnly` cookie (`pfd_ems_refresh`) with 7-day TTL, scoped to `/` so logout, agency switch, and impersonation can revoke/rotate it
- [x] Add `refresh_tokens` table in `app/models.py` for server-side revocation tracking
- [x] Implement refresh token rotation: each `/api/token/refresh` call issues a new refresh token and revokes the previous one
- [x] Implement token revocation on logout: mark the current refresh token as revoked
- [x] Bearer-header fallback removed from `_extract_token` (Phase 1b transition window closed)
- [x] `access_token` removed from all auth response bodies — frontend uses `_storeAuthFromContext(data)`
- [x] Frontend `authFetch` extended with 401→`_silentRefresh()`→retry pattern

**OBS-02 — structlog in ai_client.py**
- [x] Replace `import logging` / `logging.getLogger` with `from app.logging_config import get_logger` / `get_logger("app.ai_client")`
- [x] Updated all 22 `_log.*` calls to structlog keyword-argument style
- [ ] Verify log lines from `ai_client.py` carry `request_id` when called within a request context (requires live smoke test)

#### Phase 2 Gate — Validation Checks

*All of the following must pass before moving to Phase 3. Phase 3 introduces Redis and multi-worker execution — if any Phase 2 item is incomplete, it compounds under load.*

**TLS and reverse proxy**
- [ ] `curl http://yourhost/` redirects to `https://yourhost/` (HTTP → HTTPS redirect is enforced by the proxy)
- [ ] `curl https://yourhost/api/me` returns 200 — TLS termination is working
- [ ] Check SSL Labs (`ssllabs.com/ssltest`) once the production domain is live — target grade A or A+
- [ ] WebSocket connection over `wss://` succeeds for vitals and Lexi Group streams
- [ ] Static files (`/static/js/app.js`) are served with `Server: caddy` or `Server: nginx` — not Uvicorn — confirming the proxy handles static assets directly

**Liveness and readiness probes**
- [ ] `curl http://localhost:8000/live` returns `{"status":"ok"}` with 200 — even when Postgres is unreachable (stop the DB container and re-test)
- [ ] `curl http://localhost:8000/ready` returns 200 with Postgres running; returns 503 with Postgres stopped (`docker stop ems_db`)
- [ ] `docker inspect ems_app` shows a `HEALTHCHECK` using `/live`; `docker ps` shows status `healthy` after startup

**Container security**
- [ ] `docker exec ems_app id` — output shows UID 1001 or non-zero UID, not `uid=0(root)`
- [ ] `docker exec ems_app ls -la /app` — files are owned by the app user, not root
- [ ] From the host, `psql -h localhost -p 5432` connection is refused (Postgres port is not exposed)

**Backup and DR**
- [ ] Restore drill completed: restore a backup to a scratch environment; run `SELECT count(*) FROM users` and at least one other table to confirm data integrity — document the result and date
- [ ] Automated backup job is running and has produced at least one successful backup artifact
- [x] Restore procedure is documented in `docs/DEPLOYMENT.md` with step-by-step commands

**Token TTL and refresh flow**
- [x] Decode a freshly issued access token; confirm `exp` is 3600 seconds from issue time (60 minutes, not 1440)
- [x] `POST /api/token/refresh` with a valid refresh cookie returns a new session cookie and a new refresh cookie
- [x] Reuse the original refresh cookie after rotation — server returns 401 (token has been invalidated)
- [x] `POST /api/auth/logout` clears both the session and refresh cookies (inspect `Set-Cookie: ...; Max-Age=0` in response)

**Staging secret enforcement**
- [x] Start app with `ENV=staging` and `APP_SECRET_KEY=changeme` — application refuses to start with a clear validation error
- [ ] Startup log line explicitly records `ENV=staging` (visible in `docker logs ems_app`)

**structlog consistency**
- [ ] Send a chat message during a simulation; inspect JSON logs — confirm `ai_client.py` log lines contain `request_id`, `event`, and are valid JSON (not plain-text `INFO:ai_client:...` format)
- [ ] `grep "INFO:app" <logfile>` returns no output (no stdlib logging escaping the structured logger)

---

### Phase 3: Scalability & State (Week 4–6)

*Target: The application can run with N replicas behind a load balancer. Only after this phase is complete should multi-worker Gunicorn be enabled.*

#### Checklist

**SC-01 — Redis-backed rate limiting**
- [ ] Add `redis` and `limits[redis]` to `requirements.txt`
- [ ] Add `redis_url: str = "redis://localhost:6379"` to `Settings`
- [ ] Update `Limiter` instantiation with `storage_uri=settings.redis_url`
- [ ] Add Redis service to `docker-compose.yml` and `docker-compose.prod.yml`
- [ ] Smoke test: verify rate limit counters are shared between two local app instances

**SC-02a — Redis agency config cache**
- [ ] Wrap `load_agency()` with a Redis cache (60-second TTL)
- [ ] Call Redis cache invalidation (not just local `lru_cache`) in `invalidate_agency_cache()`
- [ ] Keep `lru_cache` for static protocol file reads

**SC-02b — Lexi Group WebSocket via Redis Pub/Sub**
- [ ] Replace `_LEXI_GROUP_WS` with Redis Pub/Sub channels keyed by `group_session_id`
- [ ] Each replica subscribes to channels for groups it is hosting; publish events to Redis
- [ ] Verify multi-container group session works in a local two-container test

**SC-02c — Background worker deduplication**
- [ ] Implement Redis distributed lock (setnx + TTL) or use ARQ task queue to elect a single TTL scrub worker
- [ ] Apply same pattern to Lexi phase advancement worker
- [ ] Verify both workers run exactly once under two running containers

**SC-03 — Vitals push model**
- [ ] Publish vitals diff to Redis channel whenever an intervention or finding is recorded
- [ ] Rewrite `vitals_ws` to subscribe to the channel; remove 3-second polling loop
- [ ] Add 30-second heartbeat that sends current vitals snapshot for new subscribers

**DB-01 — Alembic migration (policy conflict resolved first)**
- [ ] Update `DEVELOPMENT_GUIDELINES.md` section 4.2 to endorse Alembic for production deployments
- [ ] `pip install alembic`, add to `requirements.txt`
- [ ] `alembic init alembic/`
- [ ] Create baseline migration from current `Base.metadata`
- [ ] Move all `ALTER TABLE` statements from `init_db()` into ordered Alembic migration files
- [ ] Remove DDL from `init_db()`; retain `create_all` behind `ENV=development` guard only
- [ ] Add `alembic upgrade head` to deployment runbook
- [ ] Document migration workflow in `docs/DEPLOYMENT.md`

**DB-02 — Pagination**
- [ ] Add `limit`/`cursor` to `/api/me/sessions`; add `limit`/`offset` to `/api/admin/sessions` and `/api/admin/users`
- [ ] Return `{"items": [...], "total": N, "next_cursor": "..."}` envelope
- [ ] Update frontend dashboard to use page controls or infinite scroll

**SC-05 — LLM concurrency cap**
- [ ] Add `asyncio.Semaphore` per model tier (debrief = 8, chat = 20)
- [ ] Add simple circuit breaker (open after 5 consecutive failures, reset after 30s)
- [ ] Log semaphore wait time to structlog

**INF-02 — Enable Gunicorn (only after SC-01, SC-02a, SC-02b, SC-02c are complete)**
- [ ] Confirm Redis rate limiting, Redis pub/sub, and distributed workers are tested and stable
- [ ] Add `gunicorn` to `requirements.txt`
- [ ] Update `Dockerfile` CMD to `gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 --bind 0.0.0.0:8000 --timeout 120`
- [ ] Load test with two workers; confirm no state conflicts

**DEP-02 — Supply chain hardening**
- [ ] Enable Dependabot or Renovate in the GitHub repository with a weekly schedule
- [ ] Add Docker image scanning (Trivy or `docker scout cves`) to CI pipeline
- [ ] Generate SBOM with `syft` or `cyclonedx-bom` as part of the release pipeline
- [ ] Evaluate `pip-compile --generate-hashes` for hash-pinned lockfile

#### Phase 3 Gate — Validation Checks

*All of the following must pass before enabling Gunicorn multi-worker or adding a second container replica. These tests specifically validate cross-process state isolation — run them with two container instances active simultaneously.*

**Redis rate limiting — cross-process**
- [ ] Start two app containers on ports 8001 and 8002; exhaust the login rate limit (`rate_limit_auth`) by sending requests to port 8001 only; confirm the next request to port 8002 with the same user is also rate-limited (not allowed through)
- [ ] `redis-cli -h localhost -p 6379 keys "LIMITS:*"` — confirm rate limit keys exist in Redis, confirming counters are Redis-backed and not in-process

**Lexi Group WebSocket — cross-replica**
- [ ] Connect user A's browser to container 1 (`ws://localhost:8001/ws/lexi-group/<group>`); connect user B's browser to container 2 (`ws://localhost:8002/ws/lexi-group/<group>`)
- [ ] Trigger a group event (answer submission, phase transition) from user A; confirm user B's WebSocket receives the broadcast within 1 second

**Background worker deduplication**
- [ ] Run two app containers for at least 5 minutes; collect logs from both; search for TTL scrub worker log entries — confirm the scrub executed on only one container per cycle (not on both)
- [ ] Introduce a test event that the TTL scrub should delete; confirm it is deleted exactly once and not duplicated

**Vitals push latency**
- [ ] Record an intervention on an active simulation while the vitals WebSocket is connected; measure the time from the API response to receipt of the vitals update in the WebSocket stream — must be under 1 second (not the previous 3-second polling interval)
- [ ] Confirm `app/main.py` contains no `asyncio.sleep(3)` loop in the vitals WebSocket handler

**Alembic migration integrity**
- [ ] `alembic history` on all environments (local, staging) shows an identical, unbroken chain with the same head revision
- [ ] `alembic current` on staging reports the same revision as local
- [ ] Run `alembic downgrade -1` on a scratch DB, then `alembic upgrade head` — no errors
- [ ] Start the app and inspect startup logs — confirm no `ALTER TABLE` statements are executed (SQLAlchemy echo or log grep); only `create_all` runs under `ENV=development`

**Pagination**
- [ ] `GET /api/me/sessions` with no query params returns at most 50 results and includes `next_cursor` in the response body
- [ ] Follow the cursor: `GET /api/me/sessions?cursor=<value>` returns the next page — results do not overlap with the first page
- [ ] `GET /api/admin/sessions` and `GET /api/admin/users` both enforce the page limit under a superuser token

**DB connection pool under load**
- [ ] During a load test with 20 concurrent active simulations, run `SELECT count(*), state FROM pg_stat_activity WHERE datname = 'ems_sim' GROUP BY state` — confirm the active connection count does not exceed `db_pool_size + db_max_overflow` (30)

**DB timeout enforcement**
- [ ] Connect directly to Postgres as the app user; run `SHOW lock_timeout` — confirms `10s`; `SHOW statement_timeout` — confirms the configured value (not 0 or default)
- [ ] Verify these settings are present on a connection acquired from the pool mid-operation, not just at session start (check `pg_stat_activity.query` for a pooled connection to confirm settings persist)

**Gunicorn multi-worker (final check before enabling)**
- [ ] Run full Lexi Group scenario (create group, join, multiple rounds) with Gunicorn `--workers 2` and two users whose requests may hit different workers — confirm no state split and no errors

---

### Phase 4: Code Quality & Account Lifecycle (Month 2–3)

*Target: Two engineers can work on the backend simultaneously without constant conflicts. Critical account lifecycle flows are in place for launch of real user accounts.*

#### Checklist

**BIZ-03 — Transactional email (prerequisite for S-09)**
- [ ] Select transactional email provider (AWS SES, Resend, or SendGrid) and add SDK to `requirements.txt`
- [ ] Add `email_from: str = ""` and `email_provider_key: str = ""` to `Settings`
- [ ] Create `app/email_templates/` with Jinja2 templates for: password reset, email verification, account lockout notification
- [ ] Configure provider bounce and complaint webhooks; add `email_events` table to record bounces and complaints
- [ ] Flag user accounts with bounced email addresses so subsequent sends are skipped (not silently attempted)
- [ ] Apply rate limiting to all email-triggering endpoints (password reset, verification resend)

**S-09 — Account lifecycle**
- [ ] Implement `POST /api/auth/forgot-password`: accepts email, issues a signed 1-hour reset token, sends email
- [ ] Implement `POST /api/auth/reset-password`: validates token, sets new password, invalidates token
- [ ] Implement email verification on registration: send verification link; mark account `email_verified=True` on click
- [ ] Add progressive account lockout: track failed login attempts per user; lock account for 15 minutes after 10 failures
- [ ] Add `POST /api/auth/revoke-all-sessions` endpoint (admin and self-service) that invalidates all refresh tokens for a user
- [ ] Ensure refresh token rotation is enforced (see Phase 2 / S-07)
- [ ] Add immutable audit log entry for every admin impersonation event (`AgencyAuditLog` or equivalent), recording: original actor user ID, impersonated user ID, target agency ID, start time, end time, stated reason, and request ID
- [ ] Add a persistent UI banner displayed throughout the impersonation session so the admin cannot forget they are acting as another user
- [ ] On account deactivation, immediately mark all refresh tokens as revoked so outstanding access tokens cannot be refreshed

**QA-01 — Backend decomposition**
- [x] Create `app/routers/` directory
- [ ] Extract one router at a time, running the test suite after each extraction:
  - [x] `app/routers/auth.py` — auth/account-session routes extracted; `/live` and `/ready` moved to `app/routers/health.py` as part of the first slice
  - [ ] `app/routers/sessions.py`
  - [ ] `app/routers/agency.py`
  - [ ] `app/routers/lexi.py`
  - [ ] `app/routers/minigames.py`
  - [ ] `app/routers/notes.py`
- [ ] Move all Pydantic models to `app/schemas.py`
- [ ] Move all `Depends(...)` factories to `app/dependencies.py`
- [x] Register routers in `main.py` with `app.include_router()` — initial routers registered: `tts`, `auth`, `health`

**BIZ-02 — Secure file upload and cloud storage**
- [ ] Select cloud storage provider (AWS S3 or GCP Cloud Storage) and add SDK to `requirements.txt`
- [ ] Add `storage_bucket: str = ""` and `storage_region: str = ""` to `Settings`
- [ ] Create `POST /api/uploads/presign` endpoint: validates user authorization, returns a short-lived (5-minute) pre-signed PUT URL targeting cloud storage
- [ ] Update the PDF upload flow in the frontend to PUT directly to the pre-signed URL; do not POST the file to the backend
- [ ] After upload, backend fetches the object from cloud storage for AI extraction — file never lands on app container filesystem
- [ ] Add `python-magic` to `requirements.txt`; validate uploaded MIME type is `application/pdf` before presigning
- [ ] Integrate ClamAV or a cloud antivirus hook; reject files that fail the scan before they reach the LLM pipeline
- [ ] Set S3/GCS lifecycle policy to delete processed objects after 30 days, aligned with PHI TTL scrub

**BIZ-05 — Data privacy, offboarding, and account deletion**
- [ ] Define and document anonymization-as-deletion policy: what fields are overwritten, what is preserved
- [ ] Add HMAC-SHA256 lookup column for original email (for GDPR deletion confirmation without storing original)
- [ ] Implement `POST /api/me/delete-account`: requires re-authentication; triggers anonymization and refresh token revocation
- [ ] Define agency offboarding lifecycle: 30-day read-only grace period, then anonymize users and delete agency content
- [ ] Implement `GET /api/agency/export` (admin-only): produces a downloadable ZIP of agency training records as CSV/JSON
- [ ] Write an Alembic migration for the new columns (HMAC lookup, account deletion tracking)
- [ ] Confirm implementation aligns with any published privacy policy before public launch

**QA-02 — Frontend build step and decomposition**
- [ ] Add esbuild or Vite as dev dependency
- [ ] Create `static/src/` module structure
- [ ] Extract `authFetch`, token management, API constants to `api.js`
- [ ] Extract game engines and each game to separate modules
- [ ] Extract pure business logic to `logic/` subdirectory
- [ ] Write unit tests for pure functions with Vitest (no DOM required)
- [ ] Add ESLint `no-unsanitized/property` rule to CI
- [ ] Build outputs to `static/dist/`; update `index.html` references

**QA-07 — Stale comment sweep**
- [ ] Search `static/js/app.js` for all comments referencing `localStorage`, `Bearer`, `Authorization header`, or `wildcard CORS` — remove or correct each one
- [ ] Search `app/main.py` and `app/ai_client.py` for `TODO: migrate`, `fallback to`, `stored here and in`, or `transition window` comments describing superseded behavior — remove or update
- [ ] Add a PR checklist note for future auth/security changes: update nearby comments atomically with the code change
- [ ] Confirm: `grep -n "localStorage" static/js/app.js` returns no results in security-sensitive comment blocks (auth state, token storage)

**QA-05 — Server-side game progress**
- [ ] Audit all `localStorage` flags that gate learning path progression
- [ ] Confirm server-side persistence in `MinigameResult` or equivalent for each gating flag
- [ ] Reconcile `localStorage` against server state on login; server wins
- [ ] `localStorage` for non-gating UI preferences only

**QA-06 — LLM output schema validation**
- [ ] Define Pydantic models for each structured LLM response type (debrief, extraction, impression)
- [ ] Parse all structured LLM output immediately after receipt
- [ ] On `ValidationError`: log a redacted diagnostic — model name, response character length, SHA-256 hash of the raw output (for deduplication without exposing content), and the first validation error message only. Do not log any prefix of the raw response, even truncated, as the first characters of a debrief or narrative output may contain patient-derived text; apply the same scrubber used for the Sentry `before_send` hook.
- [ ] Return a graceful fallback to the client; emit the validation failure to Sentry as a non-PII event using only the redacted fields above

**OBS-03/04 — Tracing and metrics**
- [ ] Add `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-sqlalchemy` to requirements
- [ ] Configure OTLP export
- [ ] Expose `GET /metrics` (restrict to internal network)
- [ ] Configure alerts: p99 latency > 2s, error rate > 1%, LLM failure rate > 10%

#### Phase 4 Gate — Validation Checks

*All of the following must pass before moving to Phase 5. Phase 4 items are organizational and lifecycle changes — their gate confirms correctness and completeness, not performance.*

**Backend decomposition**
- [ ] `wc -l app/main.py` — result is under 500 lines (all routes extracted to routers)
- [ ] `grep -c "@app\." app/main.py` — result is 0 or only `app.include_router` calls; no route handlers remain directly in `main.py`
- [ ] Full test suite (`pytest`) passes with no regressions after all router extractions

**Frontend decomposition**
- [ ] `static/js/app.js` no longer exists as a monolithic file (or is now a generated bundle, not the source)
- [ ] `static/src/` directory exists with clearly named modules
- [ ] `npm test` (or `vitest run`) passes for all pure logic unit tests with no DOM dependency
- [ ] ESLint `no-unsanitized/property` rule is configured; `npx eslint static/src/` runs with 0 errors on new code

**Account lifecycle**
- [ ] Password reset: request a reset link via `POST /api/auth/forgot-password`, follow the link, set a new password, log in with the new password — confirm success end-to-end
- [ ] Password reset link expiry: wait past the token TTL (1 hour); attempt to use the link — server returns an appropriate error (link expired)
- [ ] Account lockout: POST 11 consecutive failed login attempts for the same username; confirm the 11th returns a lockout error; wait the lockout window and confirm login succeeds again
- [ ] Session revocation: Log in on two browser tabs; call `POST /api/auth/revoke-all-sessions` from tab 1; make an API call from tab 2 — confirm 401

**Admin impersonation audit**
- [ ] Admin impersonates a user; query `AgencyAuditLog` (or equivalent) — confirm a record exists with actor user ID, target user ID, agency ID, `start_time`, `reason`, and `request_id` populated
- [ ] Confirm a visible UI indicator (persistent banner) is displayed while the impersonation is active
- [ ] End the impersonation session; confirm `end_time` is recorded in the audit log

**LLM output validation**
- [ ] Mock a Groq response that is valid JSON but does not match the expected Pydantic schema (e.g., missing a required field); confirm the API endpoint returns a graceful fallback response (not a 500 or corrupted data)
- [ ] Inspect the Sentry event triggered by that `ValidationError` — confirm the payload contains model name, response length, and SHA-256 hash only; confirm it contains no raw response text or medical content

**Server-side game progress**
- [ ] Complete a minigame that gates a learning path unlock; clear browser `localStorage`; reload — confirm the unlock is still present (server-side persistence working)
- [ ] Open a private browsing window; log in as the same user — confirm progress is visible (not localStorage-dependent)

**Transactional email delivery**
- [ ] Trigger a password reset for a real email address; confirm the email is received with a working link
- [ ] Trigger the same reset twice in rapid succession; confirm the second attempt is rate-limited (too many requests)
- [ ] Simulate a bounce event via the provider's test webhook; confirm the user's account is flagged in the database and a subsequent email send is skipped

**File upload security**
- [ ] Upload a PDF via the UI; open browser Network tab; confirm the file is PUT directly to cloud storage (the request URL is the pre-signed cloud storage URL, not the app backend)
- [ ] Attempt to upload a non-PDF file (e.g., rename a `.txt` to `.pdf`); confirm the server rejects with an appropriate error before presigning
- [ ] Confirm cloud storage lifecycle policy is set: list objects in the bucket more than 30 days old — they should be absent

**Data privacy and offboarding**
- [ ] Call `POST /api/me/delete-account` (with re-auth); confirm `first_name`, `last_name`, and `email` fields are overwritten on the user record
- [ ] Confirm the HMAC-SHA256 lookup column is populated for the deleted account
- [ ] Confirm all refresh tokens for the deleted user are revoked (subsequent token refresh returns 401)
- [ ] Confirm the user's `user_id` UUID still exists in historical debrief records (referential integrity preserved)
- [ ] Call `GET /api/agency/export`; confirm the response is a downloadable ZIP containing CSV/JSON of training records

---

### Phase 5: Performance & Optimization (Month 3+)

*Target: The application handles classroom-scale concurrent load without DB or API degradation.*

#### Checklist

**PERF-01 — Conditional caching**
- [ ] Add `ETag` / `Last-Modified` headers to scenario list, reference cards, protocol endpoints
- [ ] Update `authFetch` to pass `If-None-Match` on cacheable reads
- [ ] Remove blanket `no-store`; apply selectively to live session endpoints only
- [ ] Add `Cache-Control: private, max-age=30` to dashboard and progress endpoints

**PERF-02 — Content-addressed static versioning**
- [ ] Add a build script that computes `sha256(file)[:8]` for each static asset
- [ ] Emit a manifest JSON mapping `filename → filename?v=<hash>`
- [ ] Reference manifest in HTML build step; remove manually maintained version strings

**PERF-03 — Notebook unlock query optimization**
- [ ] Profile the notebook condition unlock check against a synthetic history of 500 sessions
- [ ] Rewrite each condition as a bounded DB query (`EXISTS`, `COUNT ... LIMIT 1`)
- [ ] Add composite index on `(user_id, scenario_id, ended_at)` on `sim_sessions`

**DB-03 — JSONB blob monitoring**
- [ ] Add startup check logging `AVG` and `MAX` of `compiled_json` size
- [ ] Alert if any blob exceeds 512KB
- [ ] If average exceeds 256KB, evaluate header/body split

**DB-05 — Operational DBA**
- [ ] Enable `pg_stat_statements` extension; configure slow-query alerting (> 500ms)
- [ ] Monitor `pg_stat_user_tables` for bloat; tune autovacuum thresholds on high-churn tables
- [ ] Review and tune indexes quarterly

**PERF-04 — CDN for media**
- [ ] Configure CDN origin for `static/audio/` and `static/img/`
- [ ] Reference CDN base URL via environment variable in HTML/JS
- [ ] Set `Cache-Control: public, max-age=604800` for CDN-served assets

**BIZ-01 — Billing and entitlements infrastructure**
- [ ] Integrate Stripe: add `stripe` SDK to `requirements.txt`; add `stripe_secret_key: str = ""` and `stripe_webhook_secret: str = ""` to `Settings`
- [ ] Add `subscription_status` and `plan` columns to `agencies` table (Alembic migration)
- [ ] Create `POST /api/webhooks/stripe` endpoint: verify Stripe signature; handle `customer.subscription.updated`, `invoice.payment_failed`, and `customer.subscription.deleted` events; make handler idempotent using `event.id`
- [ ] Create centralized `has_feature(agency: Agency, feature: str) -> bool` helper; gate all tier-restricted endpoints through this function
- [ ] Add per-agency usage counter table for metered features (e.g., monthly PDF extraction count); reset on billing cycle via webhook
- [ ] Remove any scattered inline plan checks from route handlers; replace with `has_feature()` calls

**BIZ-04 — Full-text search strategy**
- [ ] Identify the highest-value search targets (start with `sim_sessions` and `user_notes`)
- [ ] Add `search_vector tsvector` columns via Alembic migration
- [ ] Create `GIN` indexes on the new `tsvector` columns
- [ ] Populate existing rows via `UPDATE ... SET search_vector = to_tsvector('english', ...)` in the migration
- [ ] Add application-level `search_vector` updates on new writes (or use a Postgres trigger)
- [ ] Replace any `ILIKE '%text%'` queries on these tables with `@@ plainto_tsquery('english', :query)`
- [ ] Confirm `EXPLAIN ANALYZE` shows `Bitmap Index Scan` on the GIN index (not a `Seq Scan`)

**SC-06 — API versioning**
- [ ] Evaluate whether `/api/v1/` prefix is warranted before significant external integrations
- [ ] If SCORM or LMS integrations are planned, version those endpoints first
- [ ] Document policy in `docs/DEVELOPMENT_GUIDELINES.md`

**S-10 — Password strength**
- [ ] Raise minimum length from 8 to 12 characters for new accounts
- [ ] Optionally integrate HaveIBeenPwned range API on registration
- [ ] Do not retroactively invalidate existing accounts

#### Phase 5 Gate — Validation Checks

*Phase 5 is optimization work with no hard successor phase. These checks confirm the targeted improvements actually delivered the expected gains — run before treating any item as "done."*

**Caching and ETag validation**
- [ ] `curl -I https://host/api/scenarios` — response contains an `ETag` header
- [ ] Repeat with `If-None-Match: <etag>` — response is `304 Not Modified` with no body
- [ ] `curl -I https://host/api/sessions` (live session endpoint) — response is `Cache-Control: no-store` (live endpoints still bypass cache)

**Content-addressed static assets**
- [ ] Inspect `index.html` — all `<script src="...">` and `<link href="...">` tags reference URLs containing `?v=<8-char-hash>`
- [ ] Modify one source asset file and rebuild; confirm the hash in the URL changes
- [ ] Modify a different asset file; confirm the first asset's hash is unchanged (only changed files get new hashes)

**Notebook unlock query performance**
- [ ] Create a test user with 500 completed sessions (or seed via script); call `POST /api/me/notebook/conditions`; confirm response time is under 100ms (check structlog timing or add a timing log temporarily)
- [ ] Run `EXPLAIN ANALYZE` on the unlock check query in Postgres — confirm it uses the `(user_id, scenario_id, ended_at)` index and does not perform a sequential scan

**JSONB blob monitoring**
- [ ] Start the app; inspect startup logs — confirm a log line exists with `avg_compiled_json_bytes` and `max_compiled_json_bytes`
- [ ] Confirm no value exceeds 524,288 bytes (512KB)

**Load test — classroom scale**
- [ ] Run a 10-minute load test (locust, k6, or equivalent) simulating 50 concurrent users each running a complete scenario (login → session start → 10 chat turns → debrief)
- [ ] p99 API response time is under 2 seconds
- [ ] Zero 5xx errors during the test
- [ ] Groq API error rate is under 2% (check Sentry or structlog)
- [ ] DB connection count stays within pool limits throughout (check `pg_stat_activity`)

**CDN and media delivery**
- [ ] Request a `.wav` or `.mp3` audio file; confirm the `Server` response header is the CDN edge (not Uvicorn or Caddy)
- [ ] Check `Cache-Control` on the CDN response — confirms `public, max-age=604800`
- [ ] A second request to the same audio file returns `X-Cache: HIT` (or CDN-equivalent header) — file is cached at the edge

**DB operational monitoring**
- [ ] `SELECT * FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10` — top 10 queries are known and expected; no surprise full-table scans in the list
- [ ] At least one slow-query alert is configured and tested (trigger a known slow query; confirm an alert fires or is logged in the monitoring tool)

**Billing and entitlements**
- [ ] Simulate a Stripe `invoice.payment_failed` webhook event (use Stripe CLI `stripe trigger invoice.payment_failed`); confirm `agencies.subscription_status` updates to `past_due` in the database
- [ ] Simulate the same event twice with the same `event.id`; confirm the agency row is updated only once (idempotency check — query the database and verify no duplicate audit records)
- [ ] As a Pro-tier agency user, call a tier-restricted endpoint (e.g., PDF extraction); confirm it succeeds; downgrade the agency to Free in the database; repeat the call — confirm it returns 403 with a plan-upgrade message
- [ ] Confirm `has_feature()` is the only place subscription checks occur: `grep -r "subscription_status\|plan ==" app/routers/` returns results only from the entitlements helper, not scattered across route handlers

**Full-text search**
- [ ] `EXPLAIN ANALYZE SELECT ... FROM sim_sessions WHERE search_vector @@ plainto_tsquery('english', 'cardiac arrest')` — execution plan shows `Bitmap Index Scan on sim_sessions_search_vector_idx` (not `Seq Scan`)
- [ ] Search returns relevant results for a known keyword present in a historical session narrative
- [ ] Add a new session; confirm the new `search_vector` value is populated immediately on write (not requiring a manual update)

---

## 5. Architectural Strengths

The following patterns are explicitly correct and should be preserved as the platform scales.

| Pattern | Why it matters |
|---------|----------------|
| AI/code authority boundary (AI explains, code adjudicates) | Eliminates the primary risk in medical AI: hallucinated clinical facts affecting scores or protocol decisions |
| Protocol compile-on-write (immutable snapshots at session start) | Prevents live protocol changes from corrupting in-flight simulations; enables deterministic replay |
| Evidence packet approach to scoring | Full audit trail of why each score was assigned; supports appeals, instructor review, debugging |
| Async-first with asyncpg and SQLAlchemy 2.0 | Correct pattern for I/O-bound SaaS; scales well within a single process |
| Pydantic settings with startup validation | Catches misconfiguration before the first request; `_log_startup_config()` especially good |
| Structured JSON logging with structlog | Machine-parseable from day one; ready for log aggregation without transformation |
| Multi-tier LLM scoring (deterministic → regex → AI) | Minimizes AI involvement in authoritative scoring; AI only used when deterministic methods cannot resolve |
| 30-day TTL scrub on free-text inputs | Wise PHI/HIPAA surface reduction; limits liability before BAA compliance is fully hardened |
| Per-user rate limiting keyed by JWT sub (not IP) | Prevents shared-IP classrooms from having students interfere with each other's rate budgets |
| Request ID middleware with structlog context propagation | All log lines within a request are correlated; foundational for later distributed tracing |

---

*This document supersedes ad-hoc security notes in `PUNCHLIST.md` for items covered above. Cross-reference `PUNCHLIST.md` for items not covered here. Update this document as phases complete. When DB-01 (Alembic) is adopted, update `DEVELOPMENT_GUIDELINES.md` section 4.2 first. BIZ-01 (billing) should be evaluated against the timeline for paid tier launch — it is not required for a monitored free pilot but must be complete before any commercial rollout.*
