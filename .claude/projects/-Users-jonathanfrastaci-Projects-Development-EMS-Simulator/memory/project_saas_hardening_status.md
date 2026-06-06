---
name: SaaS Hardening — Current Status
description: Which hardening phases are code-complete vs. pending gate validation, and what's next
type: project
---

Phases 1a, 1b, and 2 are code-complete as of 2026-05-12. SAAS_HARDENING_PLAN.md was refreshed to reflect this.

**Resolved (code deployed):** CORS allowlist, httpOnly cookie auth, WebSocket ticket auth, API docs disabled in prod, security headers (CSP report-only), python-multipart CVE, Sentry with PHI scrubber, background task supervision (`_supervised()`), global 500 handler, structlog in ai_client.py, non-root Docker, health probes (`/live`/`/ready`), JWT TTL 60min + refresh token rotation, Caddyfile + docker-compose.prod.yml.

**Pending Phase 2 gate validation (code exists, smoke tests not run):** TLS via Caddy against a real domain, Sentry live smoke test (trigger exception, verify no PHI in payload), explicit `sentry_sdk.capture_exception()` in `_supervised()` and global 500 handler, structlog request_id in ai_client logs, container security checks (`id`, file ownership), backup/DR drill.

**Open (Phase 3+):** DB-01 Alembic migrations, SC-01 Redis rate limiting, SC-02 Redis pub/sub + cache, SC-03 vitals push model, DB-02 pagination.

**Next highest-leverage:** Phase 4 — backend router extraction first (one router at a time, test after each), then frontend module/build decomposition. Phase 4 frontend decomposition is the gate for: `no-unsanitized` ESLint rule → CSP enforcement mode (closes S-04 and S-08 fully).

**Why:** QA-07 (stale comments) and remaining S-04/S-08 CSP work both resolve as byproducts of Phase 4. Doing them before Phase 4 would create conflicts.
