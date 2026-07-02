# Production Transition Plan

**Purpose:** End-to-end execution guide for moving from the SCORM trial to the production EMS Simulator. Written for Claude/Codex execution. Read this document fully before starting any phase.

**Repos:**
- SCORM trial (source of fixes): `/Users/jonathanfrastaci/Projects/Development/Peds Assessment SCORM`
- Production (target): `/Users/jonathanfrastaci/Projects/Development/EMS Simulator`

**Key sub-documents** (all should be present in the production repo after handoff):
- `docs/SCORM_TRIAL_PUNCHLIST.md` — acceptance gates for Phase 1 backport items
- `docs/SCORM_BACKPORT_MATRIX.md` — file-level porting instructions, commit hashes, test commands
- `docs/PRODUCTION_TRANSITION_PLAN.md` — this file

---

## Phase Status

| Phase | Branch | Status |
|---|---|---|
| 1 — Port SCORM trial fixes | `post-scorm-testing` | `[ ]` Not started |
| 2 — Shared web + SCORM backend architecture | `lms-integrations` | `[ ]` Not started |
| 3 — Render / production changeover | `main` (deploy) | `[ ]` Not started |

Update these rows as work progresses. Phase 2 design work may proceed in parallel with Phase 1, but the `lms-integrations` implementation branch must not start until Phase 1 is merged to `main`. Do not begin Phase 3 until Phase 1 is merged and Phase 2 is either complete or explicitly deferred.

---

## Phase 1 — Port SCORM Trial Fixes Into Production

### Branch setup

```bash
cd "/Users/jonathanfrastaci/Projects/Development/EMS Simulator"
git checkout main
git pull
git checkout -b post-scorm-testing
```

### Commit the handoff docs

These files should already be present in the repo root after handoff. Stage and commit them first so all subsequent work has a clean baseline.

```bash
git add AGENTS.md CLAUDE.md docs/SCORM_TRIAL_PUNCHLIST.md docs/SCORM_BACKPORT_MATRIX.md docs/PRODUCTION_TRANSITION_PLAN.md
git commit -m "Add SCORM trial backport plan and transition docs"
```

### Execution

Work through `docs/SCORM_BACKPORT_MATRIX.md` one item at a time in the **Recommended Port Order** at the bottom of that document. The port order is:

1. Item 8 audit (read-only — no code change)
2. Item 4 — Timeline scoring deference
3. Item 9b — History endpoint read-only
4. Item 9c — History resilience
5. Item 1 — Deterministic action routing
6. Item 3 — Persistence/cache/re-adjudication (requires Alembic migration)
7. Item 5 — XP/challenge rules (two commits only: `11cfd1c`, `a2ee8e5`)
8. Item 2 — Progression/persistence hardening (evaluate per-commit)
9. Items 6a–6d — Scenario evidence and rubric QA fixes
10. Item 7 — FTO debrief structure
11. Item 9a — Debrief missed-points contrast
12. Item 9d — Score normalization
13. Item 10 — Vitals trending audit

**For each item:**
1. Read the item's section in `docs/SCORM_BACKPORT_MATRIX.md`
2. Run `git -C "/Users/jonathanfrastaci/Projects/Development/Peds Assessment SCORM" show <hash>` for each commit
3. Apply production-applicable hunks per the Port? column; skip SCORM-specific files per the SCORM-Skip Rules table
4. Run the item's test command from the matrix
5. Update the item's `Production status` field in `docs/SCORM_BACKPORT_MATRIX.md`:
   - Set to `[~]` after tests pass
   - Set to `[x]` only after browser verification also passes (for items with a browser verification step)
   - Items with no browser verification step may go directly to `[x]` after tests pass
6. Commit with a message referencing the matrix item (e.g., `"Port Item 1: deterministic action-routing fixes"`)

### After all items are complete

```bash
python -m pytest tests/ -q
```

All tests must pass. Then run the live browser checks from the matrix for every item marked with a browser verification step.

### Review and merge

Have Claude review the full diff before merging:

```bash
git diff main...post-scorm-testing
```

Merge only after Claude review passes and all browser checks are complete:

```bash
git checkout main
git merge --no-ff post-scorm-testing -m "Merge post-scorm-testing: port SCORM trial fixes to production"
```

---

## Phase 2 — Shared Web + SCORM Backend Architecture

### Branch setup

Start from main after Phase 1 is merged:

```bash
cd "/Users/jonathanfrastaci/Projects/Development/EMS Simulator"
git checkout main
git pull
git checkout -b lms-integrations
```

### Goal

The production backend and database become the single source of truth for both the web frontend and any future SCORM/LMS frontends. SCORM `suspend_data` is a resume/cache layer only — it never overrides backend state.

### New database models

Add the following to `app/models.py` and generate Alembic migrations for each table. All foreign keys reference existing `agencies` and `users` tables.

> **Convention note:** The snippets below show the intended schema shape. Before writing code, read the existing `app/models.py` to match: import style, `Base` declaration, naming conventions for constraints (use named constraints for FK and unique constraints to make Alembic diffs stable), `JSONB` server_default style (check whether existing models use `text("{}")` or `"{}"` directly), and timestamp patterns. Do not assume these snippets are copy-paste-ready — adapt them to the production codebase conventions.

#### `agency_lms_integrations`

```python
class AgencyLmsIntegration(Base):
    __tablename__ = "agency_lms_integrations"
    id = Column(Integer, primary_key=True)
    agency_id = Column(Integer, ForeignKey("agencies.id"), nullable=False, index=True)
    provider = Column(String, nullable=False)          # e.g. "moodle"
    base_url = Column(String, nullable=False)          # e.g. "https://pfdu.moodlecloud.com"
    enabled = Column(Boolean, default=True, nullable=False)
    settings_json = Column(JSONB, nullable=False, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
```

#### `external_user_mappings`

```python
class ExternalUserMapping(Base):
    __tablename__ = "external_user_mappings"
    id = Column(Integer, primary_key=True)
    agency_id = Column(Integer, ForeignKey("agencies.id"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("agency_lms_integrations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    external_user_id = Column(String, nullable=False)
    external_username = Column(String)
    external_email = Column(String)
    linked_by_user_id = Column(Integer, ForeignKey("users.id"))
    linked_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("integration_id", "external_user_id"),)
```

#### `lms_launches`

```python
class LmsLaunch(Base):
    __tablename__ = "lms_launches"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("agency_lms_integrations.id"), nullable=False)
    package_id = Column(Integer, ForeignKey("learning_packages.id"))
    launch_token_hash = Column(String, nullable=False, unique=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    metadata_json = Column(JSONB, nullable=False, server_default="{}")
```

#### `learning_packages`

```python
class LearningPackage(Base):
    __tablename__ = "learning_packages"
    id = Column(Integer, primary_key=True)
    package_key = Column(String, nullable=False, unique=True)  # e.g. "peds_assessment_v1"
    title = Column(String, nullable=False)
    frontend_type = Column(String, nullable=False)             # "web" or "scorm"
    config_json = Column(JSONB, nullable=False, server_default="{}")
```

#### `package_requirements`

```python
class PackageRequirement(Base):
    __tablename__ = "package_requirements"
    id = Column(Integer, primary_key=True)
    package_id = Column(Integer, ForeignKey("learning_packages.id"), nullable=False, index=True)
    requirement_type = Column(String, nullable=False)  # e.g. "scenario", "challenge", "xp_threshold"
    target_id = Column(String)                         # scenario_id, challenge_key, etc.
    threshold = Column(Float)                          # pass score, XP amount, etc.
```

### Alembic migrations

Generate one migration per logical group:

```bash
cd "/Users/jonathanfrastaci/Projects/Development/EMS Simulator"
alembic revision --autogenerate -m "add agency_lms_integrations and external_user_mappings"
alembic revision --autogenerate -m "add lms_launches learning_packages package_requirements"
alembic upgrade head
```

Verify no data is affected by running migrations against a local copy of the production database before deploying.

### New API endpoints

Add to `app/routers/` (do not add to `app/main.py`):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/agency/integrations` | List integrations for agency |
| `POST` | `/api/agency/integrations` | Create integration (admin only) |
| `PUT` | `/api/agency/integrations/{id}` | Update integration |
| `DELETE` | `/api/agency/integrations/{id}` | Disable integration |
| `GET` | `/api/agency/integrations/{id}/users` | List external user mappings |
| `POST` | `/api/agency/integrations/{id}/users` | Link external user to EMS account |
| `DELETE` | `/api/agency/integrations/{id}/users/{mapping_id}` | Unlink user |
| `POST` | `/api/lms/launch` | Receive LMS launch, issue token |
| `GET` | `/api/lms/launch/{token}/status` | Return pass/completion status for LMS callback |

Integration management endpoints (`/api/agency/integrations`) require **agency admin** role. User-mapping endpoints (`/api/agency/integrations/{id}/users`) require **agency admin** only — do not grant instructors user-account linking authority unless an explicit user-management permission is added to the role model. The `/api/lms/launch` endpoint is unauthenticated at the HTTP level (called by the SCORM package before a session token exists) but must validate launch authenticity as described below before mapping any identity.

### Launch authenticity requirement

**A SCORM launch is not inherently identity-secure.** The `POST /api/lms/launch` endpoint must not map an external learner to an EMS user based on `provider + base_url + external_user_id` alone — those values can be spoofed by any caller.

Before Phase 2 implementation begins, choose and document one of the following authenticity mechanisms:

| Option | Description | Recommendation |
|---|---|---|
| **HMAC shared secret** | Agency admin sets a secret in `settings_json`; Moodle signs the launch payload; backend verifies the HMAC before accepting any identity claim | Simplest for Moodle integrations; implement first |
| **LTI 1.3** | OAuth 2.0 / JWKS-signed launch from Moodle; backend verifies JWT signature against Moodle's JWKS endpoint | Most standards-compliant; higher implementation cost |
| **Backend-issued launch token** | Admin pre-generates a single-use token from the EMS backend; SCORM package carries the token; backend validates it on first call | Works without Moodle LTI support; token must be short-lived and single-use |

The chosen mechanism must be stored in `agency_lms_integrations.settings_json` and verified server-side on every `/api/lms/launch` request before any identity mapping or token issuance occurs. Document the chosen mechanism in `docs/AI_ARCHITECTURE.md` §5 before writing any launch endpoint code.

### Backend launch flow

1. SCORM package launches from Moodle with learner identity + signed launch parameters
2. `POST /api/lms/launch` receives provider, base_url, external_user_id, and launch authenticity proof (HMAC signature, LTI JWT, or pre-issued token)
3. Backend looks up `agency_lms_integrations` by provider + base_url → finds agency and retrieves shared secret / JWKS URL
4. Backend **verifies launch authenticity** — reject with 401 if verification fails; do not proceed to identity mapping
5. Backend looks up `external_user_mappings` for that integration + external_user_id → finds EMS user; reject with 403 if no mapping exists
6. Backend creates `LmsLaunch` record with hashed token, short expiry (≤1 hour)
7. Backend returns token to frontend
8. Frontend calls production APIs using token (same session endpoints as web frontend)
9. Progress, history, scores, unlocks stored in shared DB under the EMS user account
10. On completion check, `GET /api/lms/launch/{token}/status` queries backend completion state and returns pass/completion for Moodle to record

### Admin UI workflow

In the agency admin panel (Integrations tab):

1. Admin selects provider: **Moodle**
2. Admin enters Moodle base URL: `https://pfdu.moodlecloud.com`
3. Backend saves `AgencyLmsIntegration` record
4. Admin opens user mapping panel: sees list of external Moodle users (populated from launch history or manual entry)
5. Admin links each external user to an existing EMS Simulator account
6. Future Moodle launches for that external user resolve to the linked EMS account automatically

### Sequencing constraint

Phase 2 **design** (schema, API contracts, authenticity mechanism selection) may proceed in parallel with Phase 1 review. The `lms-integrations` implementation branch must not start until Phase 1 is merged to `main`. Phase 2 is independently deferrable — if it takes longer than expected, Phase 1 and Phase 3 can proceed without it.

---

## Phase 3 — Render / Production Changeover

### Prerequisite checks

Before touching Render:

1. Confirm which Render service currently pulls from which repo and branch:
   - Expected current: **Peds Assessment SCORM** repo, `main` branch
   - Target: **EMS Simulator** repo, `main` (or a release branch)

2. Confirm `DATABASE_URL` in both Render services points to the same Postgres instance. The database must not change — all learner progress and history lives there.

3. Run any pending Alembic migrations from Phase 1 and Phase 2 against the live database **before** switching the Render source. Never let the app start against an unmigrated schema.

### Environment variable checklist

Verify these are set correctly in the target Render service before switching:

| Variable | Notes |
|---|---|
| `DATABASE_URL` | Must match current production DB — do not change |
| `APP_SECRET_KEY` | Must be ≥32 chars, not "changeme" |
| `OPENAI_API_KEY` | Required for TTS and AI calls |
| `ALLOWED_ORIGINS` | Must include production web origin and any Moodle iframe origin |
| `RATE_LIMIT_AUTH` | Confirm not inadvertently loosened |
| `RATE_LIMIT_LEXI` | Confirm not inadvertently loosened |
| `SUPERUSER_USERNAME` / `SUPERUSER_PASSWORD` | Must be set; password must be strong in production |
| LMS integration secrets (Phase 2) | Add after Phase 2 is deployed |

### Staging first

Before switching production:

1. Create a staging Render service pointing at `EMS Simulator` repo, `post-scorm-testing` or `main` after merge
2. Connect staging to a copy of the production database (or a recent snapshot)
3. Run the staging smoke checklist below
4. Only switch production after staging passes

### Staging smoke checklist

- [ ] Existing user can log in
- [ ] `ahosmer` / `ahorter` (or equivalent known test accounts) progress is visible
- [ ] Scenario history loads for existing attempts
- [ ] Map unlocks are correct for existing progress
- [ ] New scenario attempt scores correctly and generates debrief
- [ ] Debrief missed-points text is readable (contrast fix from Phase 1)
- [ ] FTO report shows correct sections and scoring cues
- [ ] SCORM package can still launch from Moodle if still in active use
- [ ] No 500 errors in Render logs during normal workflow

### Production Render switch

After staging passes:

1. In Render dashboard, update the production service:
   - **Repo:** `EMS Simulator`
   - **Branch:** `main` (or release branch)
2. Trigger a manual deploy
3. Watch deploy logs for migration errors or startup failures
4. Confirm `_log_startup_config()` output shows no weak-setting warnings

### Post-deploy smoke checks

Run these immediately after deploy:

- [ ] Existing users can log in
- [ ] `ahosmer` / `ahorter` progress still visible
- [ ] Scenario history loads
- [ ] Map unlocks correct
- [ ] New attempt scores and debriefs correctly
- [ ] Debrief missed-points readable
- [ ] SCORM package launches if still active
- [ ] No new errors in Render logs after 15 minutes of traffic

### Rollback plan

Rollback is only safe if all migrations applied before the changeover are **additive and backward-compatible** (adding columns/tables with defaults; no column drops, renames, or type changes). If any migration is destructive or changes a column the old code depends on, the old app code cannot safely run against the migrated schema.

**Before the changeover:**
- Review every migration from Phase 1 and Phase 2 and confirm each is additive-only
- Take a verified database snapshot/backup immediately before switching Render source
- Document the backup location and restore procedure before proceeding

**If post-deploy checks fail and migrations were additive:**
1. In Render dashboard, revert the service source back to **Peds Assessment SCORM** repo
2. Trigger redeploy — old code runs against the migrated schema safely because migrations were additive
3. Diagnose the failure before re-attempting the switch

**If post-deploy checks fail and a migration was not fully backward-compatible:**
1. Do not revert Render source — old code cannot safely use the current schema
2. Restore from the pre-changeover database snapshot
3. Revert Render source only after the database is restored
4. Treat the failed migration as a blocking issue before reattempting

---

## Sequencing Rules

Do not mix these branches:

| Branch | Contains |
|---|---|
| `post-scorm-testing` | Phase 1 — SCORM trial fix ports only |
| `lms-integrations` | Phase 2 — shared backend / LMS architecture |
| `main` | Production-stable code only |

Merge order: `post-scorm-testing` → `main` → (Phase 2 if ready) `lms-integrations` → `main` → Phase 3 deploy.

This keeps rollback clean. Phase 2 can be deferred without blocking Phase 1 or Phase 3.

---

*Created: 2026-07-02. Source: SCORM trial repo at `/Users/jonathanfrastaci/Projects/Development/Peds Assessment SCORM`.*
