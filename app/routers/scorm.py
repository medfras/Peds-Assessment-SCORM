"""SCORM integration endpoints.

Three endpoints form the contract proof for the PAT SCORM vertical slice:

  POST /api/scorm/auth
      Unauthenticated. Validates the integration key, provisions or resumes a
      ScormAttempt + shadow User + AgencyMember, issues a scorm-scoped JWT, and
      returns the attempt ID and resume state.

  POST /api/scorm/attempts/{attempt_id}/nodes/{node_id}/result
      Records a drill or scenario node result against the attempt. Updates
      node_scores (best-score semantics) and node_completed. Returns the updated
      attempt summary so the caller can write cmi.suspend_data immediately.

  GET /api/scorm/attempts/{attempt_id}/summary
      Returns the full attempt summary: per-node scores, unlock state, drill
      grade, scenario average, final score (null until all four scenarios done),
      and lesson status.

Bleed-over rule: no SCORM-specific UI config, hardcoded agency/protocol,
free-API guardrails, or history/storage policy lives in this file. Those belong
exclusively in the SCORM branch.
"""

import re
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    ScormContext,
    _assign_agency_default_protocol_profile,
    _create_scorm_token,
    _hash_password,
    _set_auth_cookies,
    get_scorm_context,
    limiter,
)
from app.config import settings
from app.database import get_db
from app.models import Agency, AgencyMember, CeTimeLog, ScormAttempt, User

router = APIRouter()

# ── Node registry ─────────────────────────────────────────────────────────────
#
# 16 nodes total across 4 maps:
#   Map 0  — 3 drill nodes  (PAT + DEV unlock PM1/PT1; GCS optional)
#   PM1    — 4 medical scenario nodes  (any 2 of 4 required for SCORM pass)
#   PT1    — 5 trauma scenario nodes   (any 2 of 5 required for SCORM pass)
#   Map 3  — 1 CPR scenario node       (available after PM1/PT1 minimums)
#   Optional games — 3 nodes
#
# Unlock chain:
#   drill_pat + drill_dev completed → PM1 + PT1 available
#   2 PM1 + 2 PT1 completed        → Map 3 (CPR) available

_DRILL_NODES: frozenset[str] = frozenset({"drill_pat", "drill_dev", "drill_gcs"})
_REQUIRED_DRILLS: frozenset[str] = frozenset({"drill_pat", "drill_dev"})

# PM1 — Medical scenarios (any 2 of 4 satisfy SCORM pass requirement)
_PM1_NODES: frozenset[str] = frozenset({
    "scen_croup",    # Pediatric Croup
    "scen_asthma",   # Pediatric Asthma
    "scen_diabetes", # Pediatric Diabetic Emergency
    "scen_seizure",  # Febrile Seizure
})
_PEDS_CE_MIN_PM1: int = 2

# PT1 — Trauma scenarios (any 2 of 5 satisfy SCORM pass requirement)
_PT1_NODES: frozenset[str] = frozenset({
    "scen_laceration", # Scalp Laceration (soft tissue trauma)
    "scen_head",       # Closed Head Injury / TBI
    "scen_bleeding",   # Angulated Forearm Fracture / extremity bleeding
    "scen_airway",     # Partial Airway Obstruction (Grape)
    "scen_anaph",      # Anaphylaxis
})
_PEDS_CE_MIN_PT1: int = 2

# Map 3 — CPR (optional for Moodle completion)
_CPR_NODES: frozenset[str] = frozenset({"scen_cpr"})

_SCENARIO_NODES: frozenset[str] = _PM1_NODES | _PT1_NODES | _CPR_NODES

_OPTIONAL_GAME_NODES: frozenset[str] = frozenset({
    "game_vitals",      # Vitals Trend Spotter
    "game_lung_sounds", # Lung Sounds Matcher
    "game_bls",         # CPR/BLS Sequence
})
_PEDS_CE_MIN_OPT_GAMES: int = 2

_ALL_NODES: frozenset[str] = _DRILL_NODES | _SCENARIO_NODES | _OPTIONAL_GAME_NODES

# Maps SCORM node ID → app scenario/game ID for frontend launch routing
_SCENARIO_NODE_MAP: dict[str, str] = {
    "scen_croup":      "peds_croup_01",
    "scen_asthma":     "peds_asthma_01",
    "scen_diabetes":   "peds_diabetic_emergency_01",
    "scen_seizure":    "peds_febrile_seizure_01",
    "scen_laceration": "peds_trauma_01_soft_tissue",
    "scen_head":       "peds_trauma_07_head_injury",
    "scen_bleeding":   "peds_trauma_03_extremity",
    "scen_airway":     "peds_trauma_02_partial_choking",
    "scen_anaph":      "peds_anaphylaxis_01",
    "scen_cpr":        "peds_cardiac_arrest_01_bls",
}

_GAME_NODE_MAP: dict[str, str] = {
    "drill_pat":        "pat",
    "drill_dev":        "dev_sort",
    "drill_gcs":        "peds_gcs_calculator",
    "game_vitals":      "vitals_trend_spotter",
    "game_lung_sounds": "lung_sounds_matcher",
    "game_bls":         "cpr_bls_sequence",
}

_NODE_PASS_THRESHOLD = 70
_SCORM_DUPLICATE_LAUNCH_WINDOW_SECONDS = 5 * 60

# SCORM pass challenge thresholds
_PEDS_CE_TARGET_SECONDS: int = 3600  # 1 hour total
_PEDS_CE_MIN_XP: int = 950  # orientation + 4 passing scenarios, or optional drill/Lexi stretch work
_PEDS_CE_ALLOWED_TIME_TYPES: tuple[str, ...] = ("orientation", "scenario", "drill")


# ── Summary computation (pure — no DB) ────────────────────────────────────────

def _peds_ce_challenge(
    *,
    required_drills_done: bool,
    pm1_completed_count: int,
    pt1_completed_count: int,
    cpr_done: bool,
    optional_games_done_count: int,
    orientation_done: bool,
    ce_seconds: int,
    user_xp: int,
) -> dict:
    """Return the SCORM course pass challenge status object.

    Completion criteria (all must be true):
      - Any 2 of 4 PM1 medical scenarios completed
      - Any 2 of 5 PT1 trauma scenarios completed
      - >= 1 hour (3600 s) accumulated training time
      - >= 950 XP

    Training time is the same authoritative CE ledger used by challenges, but
    scoped to orientation, scenario, and drill activity rows only.
    """
    pm1_ok   = pm1_completed_count >= _PEDS_CE_MIN_PM1
    pt1_ok   = pt1_completed_count >= _PEDS_CE_MIN_PT1
    cpr_ok   = cpr_done
    games_ok = optional_games_done_count >= _PEDS_CE_MIN_OPT_GAMES
    ce_ok    = ce_seconds >= _PEDS_CE_TARGET_SECONDS
    xp_ok    = user_xp >= _PEDS_CE_MIN_XP
    complete = pm1_ok and pt1_ok and ce_ok and xp_ok
    return {
        "id":                         "pfd_station1_scorm_pass",
        "title":                      "Station 1 Pediatric Assessment Pass",
        "complete":                   complete,
        "orientation_done":           orientation_done,
        "drills_done":                required_drills_done,
        "pm1_completed":              pm1_completed_count,
        "pm1_required":               _PEDS_CE_MIN_PM1,
        "pm1_done":                   pm1_ok,
        "pt1_completed":              pt1_completed_count,
        "pt1_required":               _PEDS_CE_MIN_PT1,
        "pt1_done":                   pt1_ok,
        "cpr_done":                   cpr_ok,
        "optional_games_completed":   optional_games_done_count,
        "optional_games_required":    _PEDS_CE_MIN_OPT_GAMES,
        "optional_games_done":        games_ok,
        "cpr_required":               False,
        "optional_games_required_for_pass": False,
        "ce_seconds":                 ce_seconds,
        "ce_target_seconds":          _PEDS_CE_TARGET_SECONDS,
        "ce_minutes":                 round(ce_seconds / 60, 1),
        "ce_target_minutes":          round(_PEDS_CE_TARGET_SECONDS / 60, 1),
        "training_time_done":         ce_ok,
        "xp":                         user_xp,
        "xp_required":                _PEDS_CE_MIN_XP,
        "xp_ok":                      xp_ok,
    }


def _compute_attempt_summary(
    attempt,
    *,
    ce_seconds: int = 0,
    orientation_done: bool = False,
    user_xp: int = 0,
) -> dict:
    """Compute the full attempt summary from stored node state.

    Drill grade:   best 2 of 3 completed DRILL node scores. GCS is optional.
    Scenario avg:  average of completed PM1/PT1 scenario scores, once the
                   minimum SCORM pass scenario criteria are met (2 PM1 + 2 PT1);
                   null until then.
    Final score:   rounded scenario_avg; null until the minimum scenario
                   threshold is met.
    lesson_status: "passed" when peds_ce_challenge.complete, else "incomplete".

    Unlock chain:
      unlocks.scenarios — PM1 + PT1 available once both required drills done.
      unlocks.map3      — CPR available once 2 PM1 + 2 PT1 completed.
    """
    scores: dict    = attempt.node_scores    or {}
    completed: dict = attempt.node_completed or {}

    # Required drills gate
    required_drills_done = all(_stored_node_counts_complete(scores, completed, d) for d in _REQUIRED_DRILLS)

    # Map-specific scenario counts
    pm1_completed = [s for s in _PM1_NODES if _stored_node_counts_complete(scores, completed, s)]
    pt1_completed = [s for s in _PT1_NODES if _stored_node_counts_complete(scores, completed, s)]
    pm1_completed_count = len(pm1_completed)
    pt1_completed_count = len(pt1_completed)
    cpr_done = _stored_node_counts_complete(scores, completed, "scen_cpr")

    pm1_met = pm1_completed_count >= _PEDS_CE_MIN_PM1
    pt1_met = pt1_completed_count >= _PEDS_CE_MIN_PT1

    # Unlock chain
    unlocks = {
        "scenarios": required_drills_done,      # PM1 + PT1 available
        "map3":      pm1_met and pt1_met,        # CPR available
    }

    # Drill grade — best 2 of 3 completed drill scores
    completed_drill_scores = sorted(
        (scores.get(d, 0) for d in _DRILL_NODES if _stored_node_counts_complete(scores, completed, d)),
        reverse=True,
    )
    if len(completed_drill_scores) >= 2:
        drill_grade = sum(completed_drill_scores[:2]) / 2
    elif len(completed_drill_scores) == 1:
        drill_grade = completed_drill_scores[0] / 2  # one drill contributes half weight
    else:
        drill_grade = 0.0

    # Scenario average: non-null only when minimum SCORM pass criteria are met
    all_completed_scenarios = pm1_completed + pt1_completed
    min_scenarios_met = pm1_met and pt1_met
    if min_scenarios_met:
        scenario_avg: Optional[float] = (
            sum(scores.get(s, 0) for s in all_completed_scenarios) / len(all_completed_scenarios)
        )
    else:
        scenario_avg = None

    # Optional game completions
    optional_games_done_count = sum(
        1 for g in _OPTIONAL_GAME_NODES if _stored_node_counts_complete(scores, completed, g)
    )

    # Final score and lesson_status
    final_score: Optional[int] = round(scenario_avg) if scenario_avg is not None else None

    ce_challenge = _peds_ce_challenge(
        required_drills_done=required_drills_done,
        pm1_completed_count=pm1_completed_count,
        pt1_completed_count=pt1_completed_count,
        cpr_done=cpr_done,
        optional_games_done_count=optional_games_done_count,
        orientation_done=orientation_done,
        ce_seconds=ce_seconds,
        user_xp=user_xp,
    )
    lesson_status = "passed" if ce_challenge["complete"] else "incomplete"

    return {
        "attempt_id":          attempt.attempt_id,
        "node_scores":         {n: scores.get(n, 0) for n in sorted(_ALL_NODES)},
        "node_completed":      {n: bool(completed.get(n, False)) for n in sorted(_ALL_NODES)},
        "unlocks":             unlocks,
        "drill_grade":         round(drill_grade, 1),
        "scenario_avg":        round(scenario_avg, 1) if scenario_avg is not None else None,
        "final_score":         final_score,
        "lesson_status":       lesson_status,
        "peds_ce_challenge":   ce_challenge,
        "scenario_node_map":   _SCENARIO_NODE_MAP,
        "game_node_map":       _GAME_NODE_MAP,
    }


# ── CE time helpers ───────────────────────────────────────────────────────────

async def _get_ce_context(user_id: str, db: AsyncSession) -> "tuple[int, bool, int]":
    """Return (ce_seconds, orientation_done, user_xp) for a SCORM shadow user."""
    ce_result = await db.execute(
        select(func.sum(CeTimeLog.seconds)).where(
            CeTimeLog.user_id == user_id,
            CeTimeLog.activity_type.in_(_PEDS_CE_ALLOWED_TIME_TYPES),
        )
    )
    ce_seconds = int(ce_result.scalar() or 0)
    user = await db.get(User, user_id)
    orientation_done = (user.orientation_completed_at is not None) if user else False
    user_xp = int((user.xp or 0)) if user else 0
    return ce_seconds, orientation_done, user_xp


# ── Request/response schemas ──────────────────────────────────────────────────

class ScormAuthRequest(BaseModel):
    lms_student_id:   str
    lms_student_name: Optional[str] = None
    module_id:        str
    integration_key:  str
    launch_id:        Optional[str] = None


class ScormNodeResultRequest(BaseModel):
    activity_type: str               # "minigame" | "scenario"
    score:         int               # 0–100
    completed:     bool
    passed:        Optional[bool] = None
    mistake_tags:  Optional[List[str]] = None


def _node_result_counts_complete(body: ScormNodeResultRequest, score: int) -> bool:
    """Return whether a submitted node result satisfies SCORM completion."""
    passed = body.passed if body.passed is not None else score >= _NODE_PASS_THRESHOLD
    return bool(body.completed and passed and score >= _NODE_PASS_THRESHOLD)


def _stored_node_counts_complete(scores: dict, completed: dict, node_id: str) -> bool:
    """Return whether persisted node state satisfies completion."""
    return bool(completed.get(node_id, False)) and int(scores.get(node_id, 0) or 0) >= _NODE_PASS_THRESHOLD


def _sanitize_launch_id(raw: str | None) -> str | None:
    """Produce a bounded browser-window launch marker for soft duplicate warnings."""
    if not raw:
        return None
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "", raw)
    return safe[:64] or None


def _scorm_launch_owner(lms_student_id: str | None, lms_student_name: str | None) -> str:
    """Return a bounded owner key for duplicate-window warnings.

    Moodle should provide a unique student_id, but pilot testing showed that
    some launch modes can surface blank/shared values. Include the display name
    so the warning never crosses visibly different Moodle users.
    """
    raw = f"{lms_student_id or ''}|{lms_student_name or ''}".strip("|")
    safe = re.sub(r"[^a-zA-Z0-9_\-|]", "", raw)
    return safe[:128]


def _duplicate_launch_warning(
    attempt: ScormAttempt,
    launch_id: str | None,
    now: datetime,
    launch_owner: str | None = None,
) -> dict | None:
    """Return an advisory duplicate-window warning for the same SCORM attempt."""
    if not launch_id or not attempt.active_launch_id:
        return None
    if attempt.active_launch_id == launch_id:
        return None
    active_owner = getattr(attempt, "active_launch_owner", None)
    if launch_owner:
        # Legacy attempts may not have owner data yet. Suppress the first warning
        # and bind the current launch instead of risking a cross-user false alarm.
        if not active_owner or active_owner != launch_owner:
            return None
    seen_at = attempt.active_launch_seen_at
    if not seen_at:
        return None
    if now - seen_at > timedelta(seconds=_SCORM_DUPLICATE_LAUNCH_WINDOW_SECONDS):
        return None
    return {
        "code": "duplicate_scorm_launch",
        "message": (
            "This SCORM activity appears to already be open in another window. "
            "Continuing here is allowed, but use only one window to avoid progress confusion."
        ),
        "previous_seen_at": seen_at.isoformat(),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitize_username(raw: str) -> str:
    """Produce a safe username from an arbitrary LMS student ID."""
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw)
    return safe[:64] or "student"


def _parse_lms_student_name(raw: str) -> tuple[str, str | None]:
    """Normalize Moodle's student name for display-only profile fields."""
    name = re.sub(r"\s+", " ", (raw or "").strip()).strip(" ,")
    if not name:
        return "Student", None

    # Moodle often exposes cmi.core.student_name as "Last, First".
    if "," in name:
        last, first = [part.strip(" ()") for part in name.split(",", 1)]
        if first:
            return first, last or None
        if last:
            return last, None

    parts = [part.strip(" ()") for part in name.split(" ") if part.strip(" ()")]
    if not parts:
        return "Student", None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


async def _provision_scorm_user(
    db: AsyncSession, *, lms_student_id: str, lms_student_name: str, module_id: str
) -> "tuple[User, AgencyMember, Agency]":
    """Return (user, membership, agency), creating rows as needed.

    The SCORM user account is a shadow account — it carries a random password
    hash so it cannot be used for normal login. The account is bound to the
    agency identified by settings.scorm_agency_file.
    """
    # Locate the SCORM agency
    result = await db.execute(
        select(Agency).where(Agency.agency_file == settings.scorm_agency_file)
    )
    agency = result.scalar_one_or_none()
    if not agency:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SCORM agency not configured on this server.",
        )

    # Provision shadow user
    username = f"scorm_{module_id}_{_sanitize_username(lms_student_id)}"
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    first_name, last_name = _parse_lms_student_name(lms_student_name)
    if not user:
        user = User(
            username=username,
            hashed_password=_hash_password(secrets.token_hex(32)),
            first_name=first_name,
            last_name=last_name,
            is_superuser=False,
        )
        db.add(user)
        await db.flush()
    elif lms_student_name:
        # Keep leaderboard/profile display aligned if Moodle later sends a
        # cleaner name than the original launch.
        if user.first_name != first_name:
            user.first_name = first_name
        if user.last_name != last_name:
            user.last_name = last_name

    # Provision agency membership
    result = await db.execute(
        select(AgencyMember).where(
            AgencyMember.user_id == user.id,
            AgencyMember.agency_id == agency.id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        agency_config = agency.config or {}
        membership = AgencyMember(
            user_id=user.id,
            agency_id=agency.id,
            role="student",
            provider_level="EMT",
            mca=agency_config.get("mca", settings.default_mca),
        )
        db.add(membership)
        await db.flush()
        await _assign_agency_default_protocol_profile(db, agency=agency, membership=membership)

    return user, membership, agency


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/scorm/auth")
@limiter.limit(f"{settings.rate_limit_auth}/minute")
async def scorm_auth(
    request: Request,
    response: Response,
    body: ScormAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    """Provision or resume a SCORM attempt and return a scoped JWT.

    The integration_key is a non-secret module identifier that prevents
    arbitrary callers from provisioning accounts. Security relies on CORS/origin
    checks, tenant binding, rate limits, and short token lifetimes — not on
    keeping the key secret.
    """
    if body.integration_key != settings.scorm_integration_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid integration key.")

    if body.module_id != settings.scorm_module_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown module ID.")

    user, membership, agency = await _provision_scorm_user(
        db,
        lms_student_id=body.lms_student_id,
        lms_student_name=body.lms_student_name or "",
        module_id=body.module_id,
    )

    # Provision or resume ScormAttempt
    result = await db.execute(
        select(ScormAttempt).where(
            ScormAttempt.lms_student_id == body.lms_student_id,
            ScormAttempt.module_id == body.module_id,
        )
    )
    attempt = result.scalar_one_or_none()
    if not attempt:
        attempt = ScormAttempt(
            lms_student_id=body.lms_student_id,
            lms_student_name=body.lms_student_name,
            module_id=body.module_id,
            user_id=user.id,
            node_scores={},
            node_completed={},
        )
        db.add(attempt)
        await db.flush()
    else:
        # Update display name if changed
        if body.lms_student_name and body.lms_student_name != attempt.lms_student_name:
            attempt.lms_student_name = body.lms_student_name

    launch_id = _sanitize_launch_id(body.launch_id)
    launch_owner = _scorm_launch_owner(body.lms_student_id, body.lms_student_name)
    now = datetime.utcnow()
    launch_warning = _duplicate_launch_warning(attempt, launch_id, now, launch_owner)
    if launch_id:
        attempt.active_launch_id = launch_id
        attempt.active_launch_owner = launch_owner
        attempt.active_launch_seen_at = now
        attempt.updated_at = now

    await db.commit()
    await db.refresh(attempt)

    token = _create_scorm_token(
        user, membership, agency,
        attempt_id=attempt.attempt_id,
        module_id=body.module_id,
        launch_owner=launch_owner,
    )
    _set_auth_cookies(response, token)

    ce_seconds, orientation_done, user_xp = await _get_ce_context(user.id, db)
    summary = _compute_attempt_summary(
        attempt, ce_seconds=ce_seconds, orientation_done=orientation_done, user_xp=user_xp
    )

    return {
        "access_token":     token,
        "token_type":       "bearer",
        "expires_in_seconds": settings.jwt_expire_minutes * 60,
        "scorm_attempt_id": attempt.attempt_id,
        "tenant":           body.module_id,
        "agency":           settings.scorm_agency_file,
        "mca":              membership.mca,
        "provider_level":   membership.provider_level,
        "launch_warning":   launch_warning,
        "resume_state": {
            "scores":       summary["node_scores"],
            "completed":    summary["node_completed"],
            "unlocks":      summary["unlocks"],
            "status":       attempt.status,
            "peds_ce_challenge": summary["peds_ce_challenge"],
        },
    }


class ScormLaunchHeartbeatRequest(BaseModel):
    launch_id: str


@router.post("/api/scorm/attempts/{attempt_id}/launch-heartbeat")
@limiter.limit("30/minute")
async def scorm_launch_heartbeat(
    request: Request,
    attempt_id: str,
    body: ScormLaunchHeartbeatRequest,
    ctx: ScormContext = Depends(get_scorm_context),
    db: AsyncSession = Depends(get_db),
):
    """Refresh/check this browser window's SCORM launch marker.

    active=false means another recent window has claimed the same LMS attempt.
    This is advisory only and must not block learner progress.
    """
    if attempt_id != ctx.scorm_attempt_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Attempt ID mismatch.")
    launch_id = _sanitize_launch_id(body.launch_id)
    if not launch_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid launch_id.")

    result = await db.execute(
        select(ScormAttempt).where(ScormAttempt.attempt_id == attempt_id)
    )
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")

    now = datetime.utcnow()
    launch_owner = ctx.scorm_launch_owner
    if not attempt.active_launch_id or attempt.active_launch_id == launch_id:
        attempt.active_launch_id = launch_id
        attempt.active_launch_owner = launch_owner
        attempt.active_launch_seen_at = now
        attempt.updated_at = now
        await db.commit()
        return {"active": True, "warning": None}

    if launch_owner and getattr(attempt, "active_launch_owner", None) != launch_owner:
        attempt.active_launch_id = launch_id
        attempt.active_launch_owner = launch_owner
        attempt.active_launch_seen_at = now
        attempt.updated_at = now
        await db.commit()
        return {"active": True, "warning": None}

    return {
        "active": False,
        "warning": _duplicate_launch_warning(attempt, launch_id, now, launch_owner),
    }


@router.post("/api/scorm/attempts/{attempt_id}/nodes/{node_id}/result")
@limiter.limit("30/minute")
async def record_node_result(
    request: Request,
    attempt_id: str,
    node_id: str,
    body: ScormNodeResultRequest,
    ctx: ScormContext = Depends(get_scorm_context),
    db: AsyncSession = Depends(get_db),
):
    """Record a node result and return the updated attempt summary.

    Score updates use best-score semantics — a replay that scores lower than
    the current best does not overwrite it. completed=True is sticky once set.
    """
    if node_id not in _ALL_NODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown node_id '{node_id}'. Valid nodes: {sorted(_ALL_NODES)}",
        )
    if attempt_id != ctx.scorm_attempt_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Attempt ID mismatch.")

    result = await db.execute(
        select(ScormAttempt).where(ScormAttempt.attempt_id == attempt_id)
    )
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")

    score = max(0, min(100, int(body.score)))

    scores = dict(attempt.node_scores or {})
    completed = dict(attempt.node_completed or {})
    mistake_tags = dict(attempt.node_mistake_tags or {})

    # Best-score semantics
    scores[node_id] = max(scores.get(node_id, 0), score)
    # completed is sticky, but only passing/on-track node results count.
    if _node_result_counts_complete(body, score):
        completed[node_id] = True
    if body.mistake_tags is not None:
        mistake_tags[node_id] = body.mistake_tags

    attempt.node_scores = scores
    attempt.node_completed = completed
    attempt.node_mistake_tags = mistake_tags
    attempt.updated_at = datetime.utcnow()

    ce_seconds, orientation_done, user_xp = await _get_ce_context(ctx.user_id, db)
    summary = _compute_attempt_summary(
        attempt, ce_seconds=ce_seconds, orientation_done=orientation_done, user_xp=user_xp
    )
    attempt.status = summary["lesson_status"]

    await db.commit()
    await db.refresh(attempt)

    return summary


@router.get("/api/scorm/attempts/{attempt_id}/summary")
async def get_attempt_summary(
    attempt_id: str,
    ctx: ScormContext = Depends(get_scorm_context),
    db: AsyncSession = Depends(get_db),
):
    """Return the current attempt summary. Used to populate cmi.suspend_data."""
    if attempt_id != ctx.scorm_attempt_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Attempt ID mismatch.")

    result = await db.execute(
        select(ScormAttempt).where(ScormAttempt.attempt_id == attempt_id)
    )
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")

    ce_seconds, orientation_done, user_xp = await _get_ce_context(ctx.user_id, db)
    return _compute_attempt_summary(
        attempt, ce_seconds=ce_seconds, orientation_done=orientation_done, user_xp=user_xp
    )
