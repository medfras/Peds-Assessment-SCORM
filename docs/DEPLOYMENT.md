# Deployment Guide

## Architecture

Single-worker Uvicorn behind a Caddy reverse proxy, backed by PostgreSQL.
Multi-worker mode is deferred until Phase 3 (requires in-process state to be
externalized to Redis). Do not add Gunicorn workers before Phase 3 is complete.

```
Browser → Caddy (TLS, static files) → FastAPI/Uvicorn → PostgreSQL
```

## Prerequisites

- Docker + Docker Compose v2
- A domain name pointing to the server (for automatic TLS)
- Ports 80 and 443 open on the host firewall

## First-Time Setup

**1. Clone the repository and create the env file:**
```bash
cp .env.example .env   # or create .env from scratch
```

**2. Fill in required secrets in `.env`:**
```
ENV=production
GROQ_API_KEY=<your-groq-api-key>
APP_SECRET_KEY=<generated-with-secrets.token_hex(32)>
POSTGRES_PASSWORD=<strong-random-password>
DATABASE_URL=postgresql+asyncpg://ems_user:<POSTGRES_PASSWORD>@postgres:5432/ems_sim
SUPERUSER_USERNAME=admin
SUPERUSER_PASSWORD=<strong-password>
ALLOWED_ORIGINS=["https://example.com"]
SENTRY_DSN=<optional-sentry-dsn>
```

Generate a strong secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**3. Edit `Caddyfile` — replace `example.com` with your domain.**

**4. Start services:**
```bash
docker compose -f docker-compose.prod.yml up -d
```

**5. Verify health:**
```bash
curl https://example.com/live   # → {"status":"ok"}
curl https://example.com/ready  # → {"status":"ok"}
docker ps                       # ems_app shows "healthy"
```

## Upgrade Procedure

```bash
git pull
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d --no-deps app
```

Schema migrations run automatically on startup via `init_db()`.

## Database Backup and Restore

**Strongly preferred:** Use a managed PostgreSQL service (AWS RDS, Cloud SQL,
Neon, Supabase) that handles automated backups, PITR, and failover. Connect
via `DATABASE_URL` — no self-managed backup scripts needed.

**If self-managed:** Configure WAL archiving and a daily `pg_dump` to object storage:
```bash
docker exec ems_postgres pg_dump -U ems_user ems_sim | gzip > backup_$(date +%Y%m%d).sql.gz
```
Retention policy: minimum 30-day daily backups, 7-day hourly.

**Restore drill (run before launch):**
```bash
# Restore to a scratch environment
docker exec -i ems_postgres psql -U ems_user ems_sim < backup_YYYYMMDD.sql
# Verify data integrity
docker exec ems_postgres psql -U ems_user ems_sim -c "SELECT count(*) FROM users; SELECT count(*) FROM sim_sessions;"
```
Document the result and date of the last successful restore drill.

## Container Security Gates (Phase 2 validation)

```bash
# Confirm non-root execution
docker exec ems_app id              # must show uid=1001, NOT uid=0(root)
docker exec ems_app ls -la /app     # files owned by appuser

# Confirm Postgres is not exposed to host
psql -h localhost -p 5432           # must be refused

# Confirm static files served by Caddy (not Uvicorn)
curl -I https://example.com/static/js/app.js | grep Server  # Server: Caddy
```

## Multi-Worker (Phase 3 — DO NOT enable before Phase 3)

The application currently holds session state in-process (WebSocket
connection maps, Lexi group state). Adding Gunicorn workers before this
state is externalized to Redis will cause race conditions and split-brain.

When Phase 3 is complete, replace the CMD in Dockerfile with:
```
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "4", "--bind", "0.0.0.0:8000"]
```
