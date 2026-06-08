from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    connect_args={
        "server_settings": {
            "lock_timeout": settings.db_lock_timeout,
            "statement_timeout": settings.db_statement_timeout,
        }
    },
)

# expire_on_commit=False prevents attributes from being expired after a commit,
# which is critical for async code that reads ORM objects after awaiting a commit.
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    async with async_session_factory() as db:
        yield db


async def init_db():
    """Create all tables on startup, then run additive column migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Additive migrations — safe to run repeatedly; IF NOT EXISTS guards each one
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP"
        ))
        await conn.execute(text(
            "ALTER TABLE agencies ADD COLUMN IF NOT EXISTS "
            "is_active BOOLEAN NOT NULL DEFAULT TRUE"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS xp INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS treats INTEGER NOT NULL DEFAULT 3"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS badges JSONB NOT NULL DEFAULT '[]'"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS peds_count INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS peds_trauma_count INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS treat_tokens JSONB NOT NULL DEFAULT '[]'"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS drill_xp_day DATE"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS drill_xp_today INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS drill_runs_today INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS drill_paid_ids JSONB NOT NULL DEFAULT '[]'"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS pat_xp_day DATE"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS pat_xp_today INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS pat_runs_today INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS pat_total_correct INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS pat_total_cards INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS pat_best_accuracy INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS dev_sort_xp_day DATE"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS dev_sort_xp_today INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS dev_sort_runs_today INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS dev_sort_total_correct INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS dev_sort_total_cards INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS dev_sort_best_accuracy INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS lexi_group_treat_day DATE"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS lexi_group_treats_today INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS xp_gross INTEGER"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS xp_earned INTEGER"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS treats_earned INTEGER"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS new_badges JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS elapsed_min INTEGER"
        ))
        await conn.execute(text(
            "ALTER TABLE agencies ADD COLUMN IF NOT EXISTS config JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
            "is_active BOOLEAN NOT NULL DEFAULT TRUE"
        ))
        await conn.execute(text(
            "ALTER TABLE challenges ADD COLUMN IF NOT EXISTS requirements JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE challenges ADD COLUMN IF NOT EXISTS repeatable BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE challenges ADD COLUMN IF NOT EXISTS time_goal_minutes INTEGER"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS scene_entry JSONB"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS lexi_rounds (
                id             SERIAL PRIMARY KEY,
                user_id        VARCHAR REFERENCES users(id) NOT NULL,
                played_at      TIMESTAMP DEFAULT NOW(),
                score          INTEGER NOT NULL,
                xp_earned      INTEGER NOT NULL DEFAULT 0,
                provider_level VARCHAR,
                mca            VARCHAR
            )
        """))
        # Challenges table — created via metadata if not exists
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS challenges (
                id VARCHAR PRIMARY KEY,
                agency_id VARCHAR REFERENCES agencies(id),
                name VARCHAR NOT NULL,
                description TEXT,
                icon VARCHAR,
                scenario_ids JSONB NOT NULL DEFAULT '[]',
                min_score INTEGER NOT NULL DEFAULT 70,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                repeatable BOOLEAN NOT NULL DEFAULT FALSE,
                time_goal_minutes INTEGER,
                created_by VARCHAR REFERENCES users(id),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS challenge_attempts (
                id VARCHAR PRIMARY KEY,
                challenge_id VARCHAR NOT NULL REFERENCES challenges(id),
                agency_id VARCHAR NOT NULL REFERENCES agencies(id),
                user_id VARCHAR NOT NULL REFERENCES users(id),
                attempt_number INTEGER NOT NULL DEFAULT 1,
                status VARCHAR(24) NOT NULL DEFAULT 'active',
                started_at TIMESTAMP NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMP,
                completion_summary JSONB
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS feed_events (
                id           SERIAL PRIMARY KEY,
                agency_id    VARCHAR REFERENCES agencies(id) NOT NULL,
                user_id      VARCHAR REFERENCES users(id) NOT NULL,
                display_name VARCHAR NOT NULL,
                event_type   VARCHAR NOT NULL,
                event_label  VARCHAR NOT NULL,
                event_icon   VARCHAR,
                created_at   TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS lexi_group_sessions (
                id                       VARCHAR PRIMARY KEY,
                agency_id                VARCHAR REFERENCES agencies(id) NOT NULL,
                host_user_id             VARCHAR REFERENCES users(id) NOT NULL,
                room_code                VARCHAR NOT NULL UNIQUE,
                status                   VARCHAR NOT NULL DEFAULT 'lobby',
                phase                    VARCHAR NOT NULL DEFAULT 'lobby',
                round_index              INTEGER NOT NULL DEFAULT 1,
                max_rounds               INTEGER NOT NULL DEFAULT 3,
                current_question_index   INTEGER NOT NULL DEFAULT 0,
                phase_started_at         TIMESTAMP,
                phase_ends_at            TIMESTAMP,
                effective_provider_level VARCHAR,
                mca                      VARCHAR,
                participants             JSONB NOT NULL DEFAULT '[]',
                rounds                   JSONB NOT NULL DEFAULT '[]',
                started_at               TIMESTAMP,
                ended_at                 TIMESTAMP,
                created_at               TIMESTAMP DEFAULT NOW(),
                updated_at               TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agency_groups (
                id          VARCHAR PRIMARY KEY,
                agency_id   VARCHAR REFERENCES agencies(id) NOT NULL,
                name        VARCHAR NOT NULL,
                group_type  VARCHAR NOT NULL DEFAULT 'custom',
                created_by  VARCHAR REFERENCES users(id),
                is_system   BOOLEAN NOT NULL DEFAULT FALSE,
                is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                created_at  TIMESTAMP DEFAULT NOW(),
                updated_at  TIMESTAMP DEFAULT NOW(),
                CONSTRAINT uq_agency_group_name UNIQUE (agency_id, name)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agency_group_members (
                id         SERIAL PRIMARY KEY,
                group_id   VARCHAR REFERENCES agency_groups(id) NOT NULL,
                user_id    VARCHAR REFERENCES users(id) NOT NULL,
                role       VARCHAR NOT NULL DEFAULT 'member',
                joined_at  TIMESTAMP DEFAULT NOW(),
                CONSTRAINT uq_agency_group_user UNIQUE (group_id, user_id)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS challenge_teams (
                id                     VARCHAR PRIMARY KEY,
                agency_id              VARCHAR REFERENCES agencies(id) NOT NULL,
                name                   VARCHAR NOT NULL,
                join_code              VARCHAR NOT NULL UNIQUE,
                challenge_type         VARCHAR NOT NULL DEFAULT 'lexi_group',
                created_by_user_id     VARCHAR REFERENCES users(id) NOT NULL,
                representative_user_id VARCHAR REFERENCES users(id) NOT NULL,
                min_members            INTEGER NOT NULL DEFAULT 2,
                max_members            INTEGER NOT NULL DEFAULT 5,
                status                 VARCHAR NOT NULL DEFAULT 'forming',
                created_at             TIMESTAMP DEFAULT NOW(),
                locked_at              TIMESTAMP,
                ended_at               TIMESTAMP,
                metadata_json          JSONB NOT NULL DEFAULT '{}'::jsonb
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS challenge_team_members (
                id         SERIAL PRIMARY KEY,
                team_id    VARCHAR REFERENCES challenge_teams(id) NOT NULL,
                user_id    VARCHAR REFERENCES users(id) NOT NULL,
                role       VARCHAR NOT NULL DEFAULT 'member',
                joined_at  TIMESTAMP DEFAULT NOW(),
                is_active  BOOLEAN NOT NULL DEFAULT TRUE,
                left_at    TIMESTAMP,
                CONSTRAINT uq_challenge_team_user UNIQUE (team_id, user_id)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS team_invites (
                id              VARCHAR PRIMARY KEY,
                agency_id       VARCHAR REFERENCES agencies(id) NOT NULL,
                challenge_type  VARCHAR NOT NULL DEFAULT 'lexi_group',
                match_id        VARCHAR,
                source_team_id  VARCHAR REFERENCES challenge_teams(id) NOT NULL,
                target_team_id  VARCHAR REFERENCES challenge_teams(id) NOT NULL,
                created_by      VARCHAR REFERENCES users(id) NOT NULL,
                status          VARCHAR NOT NULL DEFAULT 'pending',
                created_at      TIMESTAMP DEFAULT NOW(),
                expires_at      TIMESTAMP NOT NULL,
                responded_at    TIMESTAMP,
                responded_by    VARCHAR REFERENCES users(id)
            )
        """))
        await conn.execute(text(
            "ALTER TABLE team_invites ADD COLUMN IF NOT EXISTS match_id VARCHAR"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS team_matches (
                id                 VARCHAR PRIMARY KEY,
                agency_id          VARCHAR REFERENCES agencies(id) NOT NULL,
                challenge_type     VARCHAR NOT NULL DEFAULT 'lexi_group',
                host_team_id       VARCHAR REFERENCES challenge_teams(id) NOT NULL,
                host_user_id       VARCHAR REFERENCES users(id) NOT NULL,
                status             VARCHAR NOT NULL DEFAULT 'forming',
                started_session_id VARCHAR REFERENCES lexi_group_sessions(id),
                created_at         TIMESTAMP DEFAULT NOW(),
                ready_at           TIMESTAMP,
                started_at         TIMESTAMP,
                ended_at           TIMESTAMP,
                metadata_json      JSONB NOT NULL DEFAULT '{}'::jsonb
            )
        """))
        await conn.execute(text(
            "ALTER TABLE team_matches ADD COLUMN IF NOT EXISTS ready_at TIMESTAMP"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS team_match_participants (
                id          SERIAL PRIMARY KEY,
                match_id    VARCHAR REFERENCES team_matches(id) NOT NULL,
                team_id     VARCHAR REFERENCES challenge_teams(id) NOT NULL,
                invite_id   VARCHAR REFERENCES team_invites(id),
                is_host     BOOLEAN NOT NULL DEFAULT FALSE,
                accepted_at TIMESTAMP,
                status      VARCHAR NOT NULL DEFAULT 'accepted',
                CONSTRAINT uq_team_match_team UNIQUE (match_id, team_id)
            )
        """))
        # ── Index migrations — idempotent, safe to run on every startup ──────────
        # Composite: sessions by user+agency (dashboard queries)
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_sessions_user_agency "
            "ON sessions (user_id, agency_id)"
        ))
        # Leaderboard: sessions ordered by end time per agency
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_sessions_agency_ended "
            "ON sessions (agency_id, ended_at DESC NULLS LAST)"
        ))
        # Feed ticker: most recent events per agency
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_feed_events_agency_created "
            "ON feed_events (agency_id, created_at DESC)"
        ))
        # Lexi history: rounds per user ordered by recency
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_lexi_rounds_user_played "
            "ON lexi_rounds (user_id, played_at DESC)"
        ))
        # Challenges: active challenges per agency
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_challenges_agency_active "
            "ON challenges (agency_id, is_active)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_challenge_attempt_user_challenge "
            "ON challenge_attempts (user_id, challenge_id, started_at)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_challenge_attempt_agency_challenge "
            "ON challenge_attempts (agency_id, challenge_id, status)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_lexi_group_sessions_agency_created "
            "ON lexi_group_sessions (agency_id, created_at DESC)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_lexi_group_sessions_status_phase_end "
            "ON lexi_group_sessions (status, phase_ends_at)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_lexi_group_sessions_status_updated "
            "ON lexi_group_sessions (status, updated_at)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_lexi_group_sessions_status_created "
            "ON lexi_group_sessions (status, created_at)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_agency_groups_agency_active "
            "ON agency_groups (agency_id, is_active)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_agency_group_members_group "
            "ON agency_group_members (group_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_agency_group_members_user "
            "ON agency_group_members (user_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_challenge_teams_agency_status "
            "ON challenge_teams (agency_id, status, created_at DESC)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_challenge_teams_creator_status "
            "ON challenge_teams (created_by_user_id, status)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_challenge_team_members_team "
            "ON challenge_team_members (team_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_challenge_team_members_user "
            "ON challenge_team_members (user_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_team_invites_target_status_expires "
            "ON team_invites (target_team_id, status, expires_at)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_team_invites_source_created "
            "ON team_invites (source_team_id, created_at DESC)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_team_invites_match "
            "ON team_invites (match_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_team_matches_agency_status_created "
            "ON team_matches (agency_id, status, created_at DESC)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_team_match_participants_match_team "
            "ON team_match_participants (match_id, team_id)"
        ))
        # ── Narrative / Random Call schema additions ──────────────────────────
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS assessment_score INTEGER"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS narrative_score INTEGER"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS narrative_attempted "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS session_type "
            "VARCHAR NOT NULL DEFAULT 'scenario'"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS assessment_xp INTEGER"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS narrative_xp INTEGER"
        ))
        await conn.execute(text(
            "ALTER TABLE agencies ADD COLUMN IF NOT EXISTS narrative_required "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS rc_xp_day DATE"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS rc_xp_today "
            "INTEGER NOT NULL DEFAULT 0"
        ))

        # ── Toy Chest gamification schema ─────────────────────────────────────
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS "
            "treats_spent INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS toy_series (
                series_tag   VARCHAR PRIMARY KEY,
                display_name VARCHAR NOT NULL,
                published_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS toy_categories (
                id                         VARCHAR PRIMARY KEY,
                name                       VARCHAR NOT NULL UNIQUE,
                display_name               VARCHAR NOT NULL,
                scenario_categories        JSONB   NOT NULL DEFAULT '[]',
                default_mastery_threshold  INTEGER NOT NULL DEFAULT 85
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS toys (
                id                    VARCHAR PRIMARY KEY,
                category_id           VARCHAR NOT NULL REFERENCES toy_categories(id),
                series_tag            VARCHAR NOT NULL REFERENCES toy_series(series_tag),
                name                  VARCHAR NOT NULL,
                display_name          VARCHAR NOT NULL,
                rarity                VARCHAR NOT NULL,
                image_key             VARCHAR,
                duplicate_treat_value INTEGER NOT NULL DEFAULT 1,
                is_shop_only          BOOLEAN NOT NULL DEFAULT FALSE,
                is_earn_only          BOOLEAN NOT NULL DEFAULT FALSE,
                shop_price            INTEGER,
                is_active             BOOLEAN NOT NULL DEFAULT TRUE,
                created_at            TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_toys (
                id           SERIAL PRIMARY KEY,
                user_id      VARCHAR NOT NULL REFERENCES users(id),
                toy_id       VARCHAR NOT NULL REFERENCES toys(id),
                granted_at   TIMESTAMP DEFAULT NOW(),
                grant_source VARCHAR NOT NULL,
                CONSTRAINT uq_user_toy UNIQUE (user_id, toy_id)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS toy_grant_log (
                id             SERIAL PRIMARY KEY,
                user_id        VARCHAR NOT NULL REFERENCES users(id),
                toy_id         VARCHAR NOT NULL REFERENCES toys(id),
                session_id     VARCHAR REFERENCES sessions(id),
                grant_source   VARCHAR NOT NULL,
                is_duplicate   BOOLEAN NOT NULL DEFAULT FALSE,
                treats_awarded INTEGER NOT NULL DEFAULT 0,
                created_at     TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_pity_counters (
                id                          SERIAL PRIMARY KEY,
                user_id                     VARCHAR NOT NULL REFERENCES users(id),
                category_id                 VARCHAR NOT NULL REFERENCES toy_categories(id),
                attempts_since_last_common  INTEGER NOT NULL DEFAULT 0,
                attempts_since_last_rare    INTEGER NOT NULL DEFAULT 0,
                attempts_since_last_epic    INTEGER NOT NULL DEFAULT 0,
                CONSTRAINT uq_user_pity_category UNIQUE (user_id, category_id)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_series_views (
                id         SERIAL PRIMARY KEY,
                user_id    VARCHAR NOT NULL REFERENCES users(id),
                series_tag VARCHAR NOT NULL REFERENCES toy_series(series_tag),
                viewed_at  TIMESTAMP DEFAULT NOW(),
                CONSTRAINT uq_user_series_view UNIQUE (user_id, series_tag)
            )
        """))
        # Toy chest indexes
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_toys_category_rarity "
            "ON toys (category_id, rarity) WHERE is_active = TRUE"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_user_toys_user "
            "ON user_toys (user_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_toy_grant_log_user_session "
            "ON toy_grant_log (user_id, session_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_user_pity_user "
            "ON user_pity_counters (user_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_user_series_views_user "
            "ON user_series_views (user_id)"
        ))

        # ── Seed Series 1 (idempotent ON CONFLICT DO NOTHING) ─────────────────
        await conn.execute(text("""
            INSERT INTO toy_series (series_tag, display_name, published_at)
            VALUES ('series_1', 'Series 1', '2026-04-16 00:00:00')
            ON CONFLICT (series_tag) DO NOTHING
        """))

        # ── Seed Toy Categories (districts) ───────────────────────────────────
        await conn.execute(text("""
            INSERT INTO toy_categories
                (id, name, display_name, scenario_categories, default_mastery_threshold)
            VALUES
                ('cat_puppy_park',       'puppy_park',       'Puppy Park',
                 '["pediatric_medical","pediatric_trauma"]'::jsonb,  85),
                ('cat_neighborhood',     'neighborhood_walk', 'Neighborhood Walk',
                 '["adult_medical"]'::jsonb,                         85),
                ('cat_doggy_daycare',    'doggy_daycare',    'Doggy Daycare',
                 '["adult_trauma"]'::jsonb,                          85),
                ('cat_dog_park',         'dog_park',         'Dog Park',
                 '["scenario"]'::jsonb,                              85)
            ON CONFLICT (name) DO NOTHING
        """))

        # ── Agency schema: open-join support ─────────────────────────────────
        # Drop the NOT NULL constraint on agency_join_code (open agencies have no code)
        await conn.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'agencies'
                      AND column_name = 'agency_join_code'
                      AND is_nullable = 'NO'
                ) THEN
                    ALTER TABLE agencies ALTER COLUMN agency_join_code DROP NOT NULL;
                END IF;
            END$$
        """))
        # Add is_open_join column if missing
        await conn.execute(text(
            "ALTER TABLE agencies ADD COLUMN IF NOT EXISTS "
            "is_open_join BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        # Make agency_file nullable (DB-only agencies created via admin API need no file)
        await conn.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'agencies'
                      AND column_name = 'agency_file'
                      AND is_nullable = 'NO'
                ) THEN
                    ALTER TABLE agencies ALTER COLUMN agency_file DROP NOT NULL;
                END IF;
            END$$
        """))

        # ── Seed placeholder toys for Series 1, Puppy Park ────────────────────
        # Real art/names to be swapped in when catalog is finalized.
        await conn.execute(text("""
            INSERT INTO toys
                (id, category_id, series_tag, name, display_name, rarity,
                 image_key, duplicate_treat_value, is_shop_only, is_earn_only,
                 shop_price, is_active)
            VALUES
                ('toy_pp_s1_common_1', 'cat_puppy_park', 'series_1',
                 'pp_plush_puppy', 'Plush Puppy', 'common',
                 'toybox-blue', 1, FALSE, FALSE, 5, TRUE),
                ('toy_pp_s1_rare_1', 'cat_puppy_park', 'series_1',
                 'pp_stethoscope_pup', 'Stethoscope Pup', 'rare',
                 'toybox-red', 3, FALSE, FALSE, NULL, TRUE),
                ('toy_pp_s1_epic_1', 'cat_puppy_park', 'series_1',
                 'pp_chief_pup', 'Chief Pup', 'epic',
                 'toybox-yellow', 5, FALSE, TRUE, NULL, TRUE),
                ('toy_nw_s1_common_1', 'cat_neighborhood', 'series_1',
                 'nw_retriever', 'Golden Retriever', 'common',
                 'toybox-orange', 1, FALSE, FALSE, 5, TRUE),
                ('toy_nw_s1_rare_1', 'cat_neighborhood', 'series_1',
                 'nw_medic_dog', 'Medic Dog', 'rare',
                 'toybox-red', 3, FALSE, FALSE, NULL, TRUE),
                ('toy_nw_s1_epic_1', 'cat_neighborhood', 'series_1',
                 'nw_rescue_ranger', 'Rescue Ranger', 'epic',
                 'toybox-yellow', 5, FALSE, TRUE, NULL, TRUE)
            ON CONFLICT (id) DO NOTHING
        """))

        # ── Session findings and adjudicated outcomes (upgrade safety) ────────
        # create_all handles new deployments; these IF NOT EXISTS statements
        # ensure upgraded databases that already ran create_all without these
        # tables also get them.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS session_findings (
                id           SERIAL PRIMARY KEY,
                session_id   VARCHAR NOT NULL REFERENCES sessions(id),
                finding_type VARCHAR NOT NULL,
                key          VARCHAR NOT NULL,
                value        VARCHAR NOT NULL,
                source       VARCHAR,
                captured_at  TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS adjudicated_outcomes (
                id                   SERIAL PRIMARY KEY,
                session_id           VARCHAR NOT NULL REFERENCES sessions(id),
                reason_type          VARCHAR NOT NULL,
                reason_notes         VARCHAR,
                adjudicated_by       VARCHAR NOT NULL REFERENCES users(id),
                corrected_score      INTEGER,
                corrected_subscores  JSONB,
                created_at           TIMESTAMP DEFAULT NOW()
            )
        """))

        # Drop any previous constraint/index variants from earlier schema iterations.
        # uq_session_finding_key — full-table constraint (short-lived, never in prod)
        # uq_session_finding_exam_history_key — exam+history partial (superseded below)
        await conn.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_session_finding_key'
                      AND conrelid = 'session_findings'::regclass
                ) THEN
                    ALTER TABLE session_findings DROP CONSTRAINT uq_session_finding_key;
                END IF;
            END$$
        """))
        await conn.execute(text(
            "DROP INDEX IF EXISTS uq_session_finding_exam_history_key"
        ))

        # Remove history duplicates before adding the partial unique index.
        # Keeps the latest row (highest id) for each (session_id, 'history', key).
        # Exam and vital rows are left intact — repeated assessments are intentionally kept
        # to preserve disease progression and treatment response in debrief context.
        await conn.execute(text("""
            DELETE FROM session_findings
            WHERE finding_type = 'history'
              AND id NOT IN (
                SELECT MAX(id)
                FROM session_findings
                WHERE finding_type = 'history'
                GROUP BY session_id, finding_type, key
              )
        """))

        # Partial unique index: only history findings are deduplicated per key.
        # Exam and vital findings accumulate over the session to track progression.
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_session_finding_history_key "
            "ON session_findings (session_id, finding_type, key) "
            "WHERE finding_type = 'history'"
        ))

        # Expression index: exam and vital dedup within the same clock minute.
        # Prevents concurrent identical posts (UI retries, double tag emissions) from
        # creating duplicate rows without a SELECT+INSERT race. Two identical readings
        # more than ~60 seconds apart fall into different minute buckets and are both kept.
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_session_finding_minute_bucket "
            "ON session_findings (session_id, finding_type, key, value, date_trunc('minute', captured_at)) "
            "WHERE finding_type IN ('exam', 'vital')"
        ))
        # ── Phase 3 evidence packet persistence ───────────────────────────────
        # Nullable JSONB — populated at debrief time with the full adjudication
        # record so instructors and audit processes can inspect why each score
        # was assigned without re-running the debrief.
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS evidence_packet JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE adjudicated_outcomes ADD COLUMN IF NOT EXISTS override_findings JSONB"
        ))
        # SessionEvent: authoritative backend-emitted action events — migration target for
        # tag-derived SessionFinding. Prefer these over session_findings in the evidence packet.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS session_events (
                id           SERIAL PRIMARY KEY,
                session_id   VARCHAR NOT NULL REFERENCES sessions(id),
                event_type   VARCHAR NOT NULL,
                event_key    VARCHAR NOT NULL,
                event_data   JSONB,
                source       VARCHAR NOT NULL DEFAULT 'backend_auto',
                occurred_at  TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_session_events_session_id "
            "ON session_events (session_id)"
        ))
        # ── Phase 1 unified scoring engine columns ────────────────────────────
        # All five added together so the adjudication layer is never in a
        # partial-column state.  Reading code checks packet_schema_version
        # inside each JSONB payload before deserializing.
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS effective_context JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS effective_checklist_hash VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS checklist_states JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS evidence_references JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS score_snapshot JSONB"
        ))
        # ── Protocol profile foundation (Phase 1B) ──────────────────────────
        # Profiles are agency-approved training configurations for a base
        # protocol set. They intentionally do not ingest free-text local SOPs;
        # Phase 2 adds reviewed custom protocol content additively.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agency_protocol_profiles (
                id VARCHAR PRIMARY KEY,
                agency_id VARCHAR REFERENCES agencies(id),
                display_name VARCHAR NOT NULL,
                profile_type VARCHAR NOT NULL DEFAULT 'agency_local',
                base_protocol_set VARCHAR NOT NULL DEFAULT 'NASEMSO',
                official_mca_id VARCHAR,
                is_default BOOLEAN NOT NULL DEFAULT FALSE,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_by VARCHAR REFERENCES users(id),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_profiles ADD COLUMN IF NOT EXISTS agency_id VARCHAR REFERENCES agencies(id)"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_profiles ADD COLUMN IF NOT EXISTS display_name VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_profiles ADD COLUMN IF NOT EXISTS profile_type VARCHAR NOT NULL DEFAULT 'agency_local'"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_profiles ADD COLUMN IF NOT EXISTS base_protocol_set VARCHAR NOT NULL DEFAULT 'NASEMSO'"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_profiles ADD COLUMN IF NOT EXISTS official_mca_id VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_profiles ADD COLUMN IF NOT EXISTS active_protocol_snapshot_id VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_profiles ADD COLUMN IF NOT EXISTS last_compile_status VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_profiles ADD COLUMN IF NOT EXISTS last_compile_error VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_profiles ADD COLUMN IF NOT EXISTS last_compiled_at TIMESTAMP"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_profiles ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_profiles ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_profiles ADD COLUMN IF NOT EXISTS created_by VARCHAR REFERENCES users(id)"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()"
        ))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_agency_protocol_profile_name
            ON agency_protocol_profiles (agency_id, display_name)
            WHERE agency_id IS NOT NULL
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_agency_protocol_profiles_default
            ON agency_protocol_profiles (agency_id, is_default)
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agency_protocol_selections (
                id VARCHAR PRIMARY KEY,
                protocol_profile_id VARCHAR NOT NULL REFERENCES agency_protocol_profiles(id),
                agency_id VARCHAR REFERENCES agencies(id),
                mca_id VARCHAR,
                protocol_id VARCHAR NOT NULL,
                selection_id VARCHAR NOT NULL,
                is_selected BOOLEAN NOT NULL DEFAULT FALSE,
                base_protocol_version VARCHAR,
                updated_by VARCHAR REFERENCES users(id),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_selections ADD COLUMN IF NOT EXISTS mca_id VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_selections ADD COLUMN IF NOT EXISTS base_protocol_version VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_protocol_selections ADD COLUMN IF NOT EXISTS selected_value JSONB"
        ))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_agency_protocol_selection
            ON agency_protocol_selections (protocol_profile_id, protocol_id, selection_id)
        """))
        await conn.execute(text(
            "ALTER TABLE agencies ADD COLUMN IF NOT EXISTS default_protocol_profile_id VARCHAR REFERENCES agency_protocol_profiles(id)"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_members ADD COLUMN IF NOT EXISTS protocol_profile_id VARCHAR REFERENCES agency_protocol_profiles(id)"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_members ADD COLUMN IF NOT EXISTS protocol_profile_assignment_source VARCHAR NOT NULL DEFAULT 'default'"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agency_audit_logs (
                id VARCHAR PRIMARY KEY,
                agency_id VARCHAR REFERENCES agencies(id),
                user_id VARCHAR REFERENCES users(id),
                action VARCHAR NOT NULL,
                previous_state JSONB,
                new_state JSONB,
                ip_address VARCHAR,
                timestamp TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_agency_audit_logs_agency_time "
            "ON agency_audit_logs (agency_id, timestamp)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_agency_audit_logs_action "
            "ON agency_audit_logs (action)"
        ))
        # ── Protocol snapshot immutability (Phase 1A foundation) ─────────────
        # Snapshots are idempotent by content hash. Two partial unique indexes
        # are required because agency_id is nullable and PostgreSQL treats NULL
        # values as distinct in ordinary unique constraints.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS protocol_snapshots (
                id VARCHAR PRIMARY KEY,
                agency_id VARCHAR REFERENCES agencies(id),
                mca_id VARCHAR NOT NULL,
                compiled_json JSONB NOT NULL,
                content_hash VARCHAR NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                superseded_at TIMESTAMP
            )
        """))
        await conn.execute(text(
            "ALTER TABLE protocol_snapshots ADD COLUMN IF NOT EXISTS mca_id VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE protocol_snapshots ADD COLUMN IF NOT EXISTS compiled_json JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE protocol_snapshots ADD COLUMN IF NOT EXISTS content_hash VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE protocol_snapshots ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMP"
        ))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_protocol_snapshots_agency_mca_hash
            ON protocol_snapshots (agency_id, mca_id, content_hash)
            WHERE agency_id IS NOT NULL
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_protocol_snapshots_base_mca_hash
            ON protocol_snapshots (mca_id, content_hash)
            WHERE agency_id IS NULL
        """))
        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'fk_agency_protocol_profiles_active_snapshot'
                ) THEN
                    ALTER TABLE agency_protocol_profiles
                    ADD CONSTRAINT fk_agency_protocol_profiles_active_snapshot
                    FOREIGN KEY (active_protocol_snapshot_id) REFERENCES protocol_snapshots(id);
                END IF;
            END $$;
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS protocol_change_notifications (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES users(id),
                agency_id VARCHAR REFERENCES agencies(id),
                snapshot_id VARCHAR REFERENCES protocol_snapshots(id),
                summary_markdown TEXT NOT NULL,
                seen_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_protocol_change_notifications_user_seen "
            "ON protocol_change_notifications (user_id, seen_at, created_at)"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS protocol_snapshot_id VARCHAR REFERENCES protocol_snapshots(id)"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS protocol_profile_id VARCHAR REFERENCES agency_protocol_profiles(id)"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS protocol_hash VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS legacy_protocol BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        # ── Phase 2A local SOP/session audit scaffolding ────────────────────
        # Stored but deliberately not authoritative yet. Runtime prompt,
        # scoring, debrief, and Medical Control paths must not consume these
        # fields until SME review closes and Phase 2B enables that behavior.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agency_sops (
                id VARCHAR PRIMARY KEY,
                agency_id VARCHAR NOT NULL REFERENCES agencies(id),
                protocol_profile_id VARCHAR NOT NULL REFERENCES agency_protocol_profiles(id),
                version_id VARCHAR NOT NULL,
                rule_type VARCHAR NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'draft',
                extracted_rule TEXT NOT NULL,
                source_quote TEXT,
                source_label VARCHAR,
                page_number INTEGER,
                clinical_concept_tags JSONB NOT NULL DEFAULT '[]',
                intervention_action_ids JSONB NOT NULL DEFAULT '[]',
                patch_operations JSONB,
                sme_review_status VARCHAR NOT NULL DEFAULT 'pending',
                submitted_by VARCHAR REFERENCES users(id),
                submitted_at TIMESTAMP,
                approved_by VARCHAR REFERENCES users(id),
                approved_at TIMESTAMP,
                rejected_by VARCHAR REFERENCES users(id),
                rejected_at TIMESTAMP,
                superseded_at TIMESTAMP,
                metadata_json JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "ALTER TABLE agency_sops ADD COLUMN IF NOT EXISTS protocol_profile_id VARCHAR REFERENCES agency_protocol_profiles(id)"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_sops ADD COLUMN IF NOT EXISTS version_id VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_sops ADD COLUMN IF NOT EXISTS rule_type VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_sops ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'draft'"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_sops ADD COLUMN IF NOT EXISTS clinical_concept_tags JSONB NOT NULL DEFAULT '[]'"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_sops ADD COLUMN IF NOT EXISTS intervention_action_ids JSONB NOT NULL DEFAULT '[]'"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_sops ADD COLUMN IF NOT EXISTS patch_operations JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_sops ADD COLUMN IF NOT EXISTS sme_review_status VARCHAR NOT NULL DEFAULT 'pending'"
        ))
        await conn.execute(text(
            "ALTER TABLE agency_sops ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_agency_sops_agency_status "
            "ON agency_sops (agency_id, status)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_agency_sops_profile_status "
            "ON agency_sops (protocol_profile_id, status)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_agency_sops_sme_review "
            "ON agency_sops (sme_review_status)"
        ))
        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'ck_agency_sops_no_self_approval'
                ) THEN
                    ALTER TABLE agency_sops
                    ADD CONSTRAINT ck_agency_sops_no_self_approval
                    CHECK (approved_by IS NULL OR submitted_by IS NULL OR approved_by <> submitted_by);
                END IF;
            END $$;
        """))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS active_sop_ids JSONB NOT NULL DEFAULT '[]'"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS effective_protocol_excerpt JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS debrief_markdown TEXT"
        ))
        await conn.execute(text("""
            UPDATE sessions
            SET legacy_protocol = TRUE
            WHERE protocol_snapshot_id IS NULL
              AND COALESCE(legacy_protocol, FALSE) = FALSE
        """))
        # ── Adjudication revision history (Phase 4 audit contract) ────────────
        # Append-only archive of superseded adjudication packets.
        # adjudicate_and_persist() writes a row here before overwriting the live
        # checklist_states / score_snapshot / evidence_references columns so that
        # reruns on changed inputs preserve the full adjudication history.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS adjudication_revisions (
                id                  SERIAL PRIMARY KEY,
                session_id          VARCHAR NOT NULL REFERENCES sessions(id),
                superseded_at       TIMESTAMP NOT NULL DEFAULT NOW(),
                input_hash          VARCHAR NOT NULL,
                checklist_states    JSONB,
                score_snapshot      JSONB,
                evidence_references JSONB
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_adjudication_revisions_session_id "
            "ON adjudication_revisions (session_id)"
        ))
        # ── User notes ────────────────────────────────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_notes (
                id          VARCHAR   PRIMARY KEY DEFAULT gen_random_uuid()::text,
                user_id     VARCHAR   NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                session_id  VARCHAR   REFERENCES sessions(id) ON DELETE SET NULL,
                scenario_id VARCHAR,
                title       VARCHAR(200) NOT NULL,
                body        TEXT      NOT NULL,
                tags        JSONB     NOT NULL DEFAULT '[]',
                created_at  TIMESTAMP NOT NULL DEFAULT now(),
                updated_at  TIMESTAMP NOT NULL DEFAULT now()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_user_notes_user_id "
            "ON user_notes (user_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_user_notes_scenario_id "
            "ON user_notes (user_id, scenario_id) WHERE scenario_id IS NOT NULL"
        ))

        # Phase 1B: DMIST primary impression
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS "
            "dmist_primary_impression TEXT"
        ))

        # Phase 1A: SM-2 spaced repetition history for Random Call selection
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS student_scenario_history (
                id          VARCHAR PRIMARY KEY,
                user_id     VARCHAR NOT NULL REFERENCES users(id),
                agency_id   VARCHAR NOT NULL REFERENCES agencies(id),
                scenario_id VARCHAR NOT NULL,
                interval_days FLOAT NOT NULL DEFAULT 1.0,
                ease_factor   FLOAT NOT NULL DEFAULT 2.5,
                last_random_call_date TIMESTAMP,
                last_rc_score INTEGER,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now(),
                CONSTRAINT uq_student_scenario UNIQUE (user_id, agency_id, scenario_id)
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_student_scenario_history_user_agency "
            "ON student_scenario_history (user_id, agency_id)"
        ))
        # Rename best_rc_score → last_rc_score for DBs created before the rename.
        # undefined_column is caught so this is a no-op on fresh databases.
        await conn.execute(text("""
            DO $$ BEGIN
                ALTER TABLE student_scenario_history
                    RENAME COLUMN best_rc_score TO last_rc_score;
            EXCEPTION WHEN undefined_column THEN NULL;
            END $$
        """))

        # ── Pediatric map progression (Scout's Toy Quest) ─────────────────────
        # Toy gate: which peds map must be completed before this toy is purchasable.
        await conn.execute(text(
            "ALTER TABLE toys ADD COLUMN IF NOT EXISTS map_gate_id VARCHAR"
        ))

        # Per-user completion record for gateway and convergence map nodes
        # (pm1, pt1, pm7, pt8) that cannot be tracked via scenario completion.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS peds_map_progress (
                id           SERIAL PRIMARY KEY,
                user_id      VARCHAR NOT NULL REFERENCES users(id),
                map_id       VARCHAR NOT NULL,
                completed_at TIMESTAMP DEFAULT now(),
                CONSTRAINT uq_peds_map_progress UNIQUE (user_id, map_id)
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_peds_map_progress_user "
            "ON peds_map_progress (user_id)"
        ))

        # Per-user Scout's Toy Quest convergence keys.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS peds_keys (
                id        SERIAL PRIMARY KEY,
                user_id   VARCHAR NOT NULL REFERENCES users(id),
                key_id    VARCHAR NOT NULL,
                earned_at TIMESTAMP DEFAULT now(),
                CONSTRAINT uq_peds_key UNIQUE (user_id, key_id)
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_peds_keys_user "
            "ON peds_keys (user_id)"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS minigame_results (
                id          SERIAL PRIMARY KEY,
                user_id     VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                game_id     VARCHAR(64) NOT NULL,
                run_id      VARCHAR(128),
                score       INTEGER DEFAULT 0,
                total       INTEGER DEFAULT 0,
                correct     INTEGER DEFAULT 0,
                elapsed_sec INTEGER DEFAULT 0,
                xp_earned   INTEGER DEFAULT 0,
                created_at  TIMESTAMP DEFAULT now()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_minigame_results_user_game "
            "ON minigame_results (user_id, game_id)"
        ))
        # Partial unique index — prevents double-XP on retry when run_id is provided.
        # Rows with run_id IS NULL (legacy/anonymous plays) are not covered.
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_minigame_run "
            "ON minigame_results (user_id, game_id, run_id) "
            "WHERE run_id IS NOT NULL"
        ))
        # Additive migrations — safe to run on existing DBs; no-ops if columns exist.
        await conn.execute(text(
            "ALTER TABLE minigame_results "
            "ADD COLUMN IF NOT EXISTS mistake_tags JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE minigame_results "
            "ADD COLUMN IF NOT EXISTS mode VARCHAR(64)"
        ))
        await conn.execute(text(
            "ALTER TABLE minigame_results "
            "ADD COLUMN IF NOT EXISTS hint_count INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE minigame_results "
            "ADD COLUMN IF NOT EXISTS sequence_data JSONB"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS minigame_reference_cards (
                id          SERIAL PRIMARY KEY,
                user_id     VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                card_id     VARCHAR(128) NOT NULL,
                unlocked_at TIMESTAMP NOT NULL DEFAULT now(),
                CONSTRAINT uq_minigame_reference_card UNIQUE (user_id, card_id)
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_minigame_reference_cards_user "
            "ON minigame_reference_cards (user_id)"
        ))

        # ── Orientation map (first-login onboarding) ─────────────────────────
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
            "orientation_completed_at TIMESTAMP"
        ))
        # Backfill: mark users who have at least one session as already oriented
        # so existing users are not forced through orientation on next login.
        await conn.execute(text("""
            UPDATE users
            SET orientation_completed_at = created_at
            WHERE orientation_completed_at IS NULL
              AND id IN (SELECT DISTINCT user_id FROM sessions)
        """))

        # ── Notebook entries ──────────────────────────────────────────────────
        # condition entries: unlocked when a learner correctly identifies the
        # primary impression; stores the condition + treatment reference markdown.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notebook_condition_entries (
                id             SERIAL PRIMARY KEY,
                user_id        VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                scenario_id    VARCHAR NOT NULL,
                scenario_title VARCHAR NOT NULL,
                condition_name VARCHAR NOT NULL,
                reference_md   TEXT    NOT NULL,
                unlocked_at    TIMESTAMP NOT NULL DEFAULT now(),
                CONSTRAINT uq_nb_condition UNIQUE (user_id, scenario_id)
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_nb_condition_user "
            "ON notebook_condition_entries (user_id)"
        ))
        # learning entries: unlocked after completing a mini-game that has a
        # learning_page.md; stores the rendered markdown for the learning page.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notebook_learning_entries (
                id          SERIAL PRIMARY KEY,
                user_id     VARCHAR    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                game_id     VARCHAR(64) NOT NULL,
                game_title  VARCHAR    NOT NULL,
                content_md  TEXT       NOT NULL,
                unlocked_at TIMESTAMP  NOT NULL DEFAULT now(),
                CONSTRAINT uq_nb_learning UNIQUE (user_id, game_id)
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_nb_learning_user "
            "ON notebook_learning_entries (user_id)"
        ))
        await conn.execute(text(
            "ALTER TABLE session_findings ADD COLUMN IF NOT EXISTS source VARCHAR NULL"
        ))
        # ── CeTimeLog idempotency constraint ──────────────────────────────────
        # Partial unique index on rows where source_id is set (all idempotency-
        # relevant rows). Prevents race-condition duplicates from flaky networks
        # or retried requests from writing two CE rows for the same activity.
        # Rows without source_id (NULL) are orientation awards and are exempt —
        # they are guarded at the application layer via orientation_completed_at.
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ce_time_log_source "
            "ON ce_time_log (user_id, source_id, activity_type) "
            "WHERE source_id IS NOT NULL"
        ))
        # ── SCORM duplicate launch marker ───────────────────────────────────
        # Used only for soft learner warnings when the same Moodle user opens
        # the same SCORM attempt in multiple windows. It never blocks writes.
        await conn.execute(text(
            "ALTER TABLE scorm_attempts ADD COLUMN IF NOT EXISTS active_launch_id VARCHAR(64)"
        ))
        await conn.execute(text(
            "ALTER TABLE scorm_attempts ADD COLUMN IF NOT EXISTS active_launch_owner VARCHAR(128)"
        ))
        await conn.execute(text(
            "ALTER TABLE scorm_attempts ADD COLUMN IF NOT EXISTS active_launch_seen_at TIMESTAMP"
        ))
