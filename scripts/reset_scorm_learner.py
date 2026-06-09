#!/usr/bin/env python3
"""Reset one SCORM pilot learner's backend progress.

This intentionally does not delete the User row or agency membership. It clears
attempt/progress/result rows and restores learner counters so a Moodle learner
can retest the SCORM package from a clean backend state.

Usage from the Render web-service shell, from the repo root:

    python scripts/reset_scorm_learner.py --list-recent
    python scripts/reset_scorm_learner.py --lms-student-id 12345
    python scripts/reset_scorm_learner.py --lms-student-id 12345 --confirm

You still need to delete/reset the matching Moodle SCORM attempt separately,
because Moodle stores its own attempt/suspend_data.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import bindparam, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import async_session_factory


MODULE_ID = "pfd_station1"


SESSION_CHILD_TABLES = (
    "adjudication_revisions",
    "adjudicated_outcomes",
    "session_events",
    "session_findings",
    "interventions",
    "chat_messages",
    "toy_grant_log",
)

USER_PROGRESS_TABLES = (
    "scorm_attempts",
    "challenge_attempts",
    "minigame_results",
    "minigame_reference_cards",
    "notebook_condition_entries",
    "notebook_learning_entries",
    "ce_time_log",
    "peds_map_progress",
    "peds_keys",
    "student_scenario_history",
    "lexi_chat_messages",
    "user_notes",
    "user_toys",
    "user_pity_counters",
    "user_series_views",
    "lexi_rounds",
    "feed_events",
    "ws_tickets",
    "refresh_tokens",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reset one learner's SCORM/backend pilot progress. Dry-run by default.",
    )
    parser.add_argument(
        "--list-recent",
        action="store_true",
        help="List recent SCORM attempts and exit. Useful for finding lms_student_id.",
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--lms-student-id", help="Moodle SCORM student id from scorm_attempts.")
    group.add_argument("--user-id", help="Backend users.id to reset.")
    group.add_argument("--username", help="Backend users.username to reset.")
    parser.add_argument("--module-id", default=MODULE_ID, help=f"SCORM module id. Default: {MODULE_ID}")
    parser.add_argument("--confirm", action="store_true", help="Actually delete/reset rows.")
    return parser


async def _scalar_list(db, sql: str, params: dict) -> list[str]:
    result = await db.execute(text(sql), params)
    return [str(row[0]) for row in result.fetchall() if row[0] is not None]


async def _count(db, table: str, column: str, values: Iterable[str]) -> int:
    values = list(values)
    if not values:
        return 0
    stmt = text(f"SELECT COUNT(*) FROM {table} WHERE {column} IN :values").bindparams(
        bindparam("values", expanding=True)
    )
    result = await db.execute(stmt, {"values": values})
    return int(result.scalar_one() or 0)


async def _delete(db, table: str, column: str, values: Iterable[str]) -> int:
    values = list(values)
    if not values:
        return 0
    stmt = text(f"DELETE FROM {table} WHERE {column} IN :values").bindparams(
        bindparam("values", expanding=True)
    )
    result = await db.execute(stmt, {"values": values})
    return int(result.rowcount or 0)


async def _resolve_user_ids(db, args) -> list[str]:
    if args.user_id:
        return await _scalar_list(db, "SELECT id FROM users WHERE id = :user_id", {"user_id": args.user_id})
    if args.username:
        return await _scalar_list(db, "SELECT id FROM users WHERE username = :username", {"username": args.username})
    return await _scalar_list(
        db,
        """
        SELECT DISTINCT user_id
        FROM scorm_attempts
        WHERE module_id = :module_id
          AND lms_student_id = :lms_student_id
          AND user_id IS NOT NULL
        """,
        {"module_id": args.module_id, "lms_student_id": args.lms_student_id},
    )


async def _list_recent_attempts(db, module_id: str) -> list[dict]:
    result = await db.execute(
        text(
            """
            SELECT attempt_id, lms_student_id, lms_student_name, module_id, user_id, status, updated_at
            FROM scorm_attempts
            WHERE module_id = :module_id
            ORDER BY updated_at DESC
            LIMIT 25
            """
        ),
        {"module_id": module_id},
    )
    return [dict(row._mapping) for row in result.fetchall()]


async def _describe_users(db, user_ids: list[str]) -> list[dict]:
    if not user_ids:
        return []
    stmt = text(
        """
        SELECT u.id, u.username, u.first_name, u.last_name, u.xp, u.treats,
               u.orientation_completed_at,
               sa.lms_student_id, sa.lms_student_name, sa.module_id, sa.status
        FROM users u
        LEFT JOIN scorm_attempts sa ON sa.user_id = u.id
        WHERE u.id IN :user_ids
        ORDER BY u.username, sa.updated_at DESC NULLS LAST
        """
    ).bindparams(bindparam("user_ids", expanding=True))
    result = await db.execute(stmt, {"user_ids": user_ids})
    return [dict(row._mapping) for row in result.fetchall()]


async def _reset_user_counters(db, user_ids: list[str]) -> int:
    if not user_ids:
        return 0
    stmt = text(
        """
        UPDATE users
        SET xp = 0,
            treats = 3,
            badges = '[]'::jsonb,
            peds_count = 0,
            peds_trauma_count = 0,
            treat_tokens = '[]'::jsonb,
            orientation_completed_at = NULL,
            drill_xp_day = NULL,
            drill_xp_today = 0,
            drill_runs_today = 0,
            drill_paid_ids = '[]'::jsonb,
            rc_xp_day = NULL,
            rc_xp_today = 0,
            pat_xp_day = NULL,
            pat_xp_today = 0,
            pat_runs_today = 0,
            pat_total_correct = 0,
            pat_total_cards = 0,
            pat_best_accuracy = 0,
            dev_sort_xp_day = NULL,
            dev_sort_xp_today = 0,
            dev_sort_runs_today = 0,
            dev_sort_total_correct = 0,
            dev_sort_total_cards = 0,
            dev_sort_best_accuracy = 0,
            lexi_group_treat_day = NULL,
            lexi_group_treats_today = 0
        WHERE id IN :user_ids
        """
    ).bindparams(bindparam("user_ids", expanding=True))
    result = await db.execute(stmt, {"user_ids": user_ids})
    return int(result.rowcount or 0)


async def main() -> int:
    args = _parser().parse_args()

    if not args.list_recent and not (args.lms_student_id or args.user_id or args.username):
        print("Choose --list-recent, --lms-student-id, --user-id, or --username.")
        return 2

    async with async_session_factory() as db:
        if args.list_recent:
            rows = await _list_recent_attempts(db, args.module_id)
            if not rows:
                print(f"No SCORM attempts found for module_id={args.module_id!r}.")
                return 0
            print(f"Recent SCORM attempts for module_id={args.module_id!r}:")
            for row in rows:
                print(
                    f"- lms_student_id={row['lms_student_id']} "
                    f"lms_student_name={row.get('lms_student_name')} "
                    f"user_id={row.get('user_id')} status={row.get('status')} "
                    f"updated_at={row.get('updated_at')}"
                )
            return 0

        user_ids = await _resolve_user_ids(db, args)
        if not user_ids:
            print("No matching backend user found.")
            print("Tip: list recent SCORM attempts with:")
            print("  python scripts/reset_scorm_learner.py --lms-student-id YOUR_MOODLE_ID")
            return 2

        session_stmt = text("SELECT id FROM sessions WHERE user_id IN :user_ids").bindparams(
            bindparam("user_ids", expanding=True)
        )
        result = await db.execute(session_stmt, {"user_ids": user_ids})
        session_ids = [str(row[0]) for row in result.fetchall() if row[0] is not None]

        print("Matched learner rows:")
        for row in await _describe_users(db, user_ids):
            print(
                f"- user_id={row['id']} username={row['username']} "
                f"name={(row.get('first_name') or '')} {(row.get('last_name') or '')} "
                f"lms_student_id={row.get('lms_student_id')} "
                f"lms_student_name={row.get('lms_student_name')} "
                f"scorm_status={row.get('status')} xp={row.get('xp')} treats={row.get('treats')}"
            )

        print("\nRows that will be cleared:")
        for table in SESSION_CHILD_TABLES:
            print(f"- {table}: {await _count(db, table, 'session_id', session_ids)}")
        print(f"- sessions: {len(session_ids)}")
        for table in USER_PROGRESS_TABLES:
            print(f"- {table}: {await _count(db, table, 'user_id', user_ids)}")

        if not args.confirm:
            print("\nDry run only. Re-run with --confirm to reset this learner.")
            print("After backend reset, also delete/reset this learner's Moodle SCORM attempt.")
            return 0

        for table in SESSION_CHILD_TABLES:
            await _delete(db, table, "session_id", session_ids)
        await _delete(db, "sessions", "id", session_ids)
        for table in USER_PROGRESS_TABLES:
            await _delete(db, table, "user_id", user_ids)
        updated = await _reset_user_counters(db, user_ids)
        await db.commit()

        print(f"\nReset complete. Updated {updated} user row(s).")
        print("Now delete/reset the matching Moodle SCORM attempt before retesting.")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
