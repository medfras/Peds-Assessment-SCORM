import asyncio
from collections import Counter, defaultdict, deque
import hashlib
import json
import random
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any, List, Optional, Literal

import jwt
import sentry_sdk
import structlog
from fastapi import FastAPI, Depends, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import select, update, func, or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings, _IS_PROD
from app.auth import (
    ActiveContext,
    _assign_agency_default_protocol_profile,
    _auth_response,
    _count_memberships,
    _create_active_token,
    _create_base_token,
    _create_superuser_token,
    _decode_token,
    _extract_token,
    _generate_csrf_token,
    _hash_password,
    _issue_refresh_token,
    _resolve_member_mca,
    _resolve_member_provider_level,
    _set_auth_cookies,
    _set_refresh_cookie,
    _verify_csrf_token,
    _verify_password,
    get_active_context,
    get_admin_context,
    get_current_user,
    get_instructor_context,
    get_superuser_context,
    limiter,
    pwd_context,
)
from app.routers import auth as auth_router
from app.routers import health as health_router
from app.routers import scorm as scorm_router
from app.routers import tts as tts_router
from app.logging_config import configure_logging, get_logger
from app.database import get_db, init_db, async_session_factory
from app.models import (
    User,
    Agency,
    AgencyMember,
    AgencyAuditLog,
    AgencyProtocolProfile,
    AgencyProtocolSelection,
    AgencySOP,
    SimSession,
    Intervention,
    ChatMessage,
    SessionFinding,
    AdjudicatedOutcome,
    SessionEvent,
    Challenge,
    ChallengeAttempt,
    LexiRound,
    LexiGroupSession,
    FeedEvent,
    AgencyGroup,
    AgencyGroupMember,
    ChallengeTeam,
    ChallengeTeamMember,
    TeamInvite,
    TeamMatch,
    TeamMatchParticipant,
    ToySeries,
    ToyCategory,
    Toy,
    UserToy,
    ToyGrantLog,
    UserPityCounter,
    UserSeriesView,
    UserNote,
    StudentScenarioHistory,
    PedsMapProgress,
    PedsKey,
    MinigameResult,
    MinigameReferenceCard,
    NotebookConditionEntry,
    NotebookLearningEntry,
    ProtocolChangeNotification,
    WsTicket,
    RefreshToken,
    CeTimeLog,
)
from app.scenario_engine import load_scenario, list_scenarios, get_public_scenario_data, adapt_scenario_to_context, list_mcas, build_intervention_clinical_snapshot
from app.scenarios.vocabulary import (
    equipment_id_for_canonical_name,
    equipment_id_for_alias,
    equipment_label_for_id,
    is_known_equipment_id,
    all_equipment_items,
    all_medication_items,
    is_medication_id,
    EQUIPMENT_CATALOG,
    MEDICATIONS_CATALOG,
)
from app.clinical_data import load_agency, invalidate_agency_cache
from app.protocol_engine import (
    available_base_protocol_sets,
    build_protocol_excerpt_locked,
    build_protocol_excerpt_preview,
    create_protocol_snapshot,
    get_effective_protocol_profile,
    materialize_protocol_profile_snapshot,
    protocol_selection_options_for_base_set,
    warmup_protocol_caches,
)
from app.cpr_challenge import CPRChallengeError, CPRScoreContext, score_cpr_challenge
from app.procedure_engine import load_procedure, list_procedures
from app.vitals_engine import calculate_vitals
from app.dmist_utils import extract_primary_impression_from_dmist
from app.ai_client import stream_chat_response, evaluate_and_generate_debrief, get_lexi_response, generate_lexi_questions, get_medical_control_response, simple_completion, get_practice_coach_response, _effective_level, AiProviderError, _compose_reference_section
from app.scoring_service import adjudicate_and_persist, extract_deterministic_subscores, compute_scores, _compute_critical_failure_status
from app.checklist import load_checklist, ChecklistItem, ChecklistItemState
from app.minigame_metadata import (
    get_allowed_minigame_ids,
    get_minigame_display_name,
    get_minigame_metadata,
    get_reference_card_catalog,
    get_reference_card_definition,
    validate_minigame_metadata,
)
from app.minigame_results import sanitize_minigame_hint_count, summarize_phase13_readiness
from app.intervention_suggestions import detection_match_is_confident as _detection_match_is_confident

async def _propagate_agency_default_protocol_profile(
    db: AsyncSession,
    *,
    agency_id: str,
    profile_id: str,
) -> int:
    """Move default-inherited memberships to the agency's current default profile."""
    result = await db.execute(
        select(AgencyMember).where(
            AgencyMember.agency_id == agency_id,
            or_(
                AgencyMember.protocol_profile_assignment_source.is_(None),
                AgencyMember.protocol_profile_assignment_source == "default",
            ),
        )
    )
    changed = 0
    for membership in result.scalars().all():
        if membership.protocol_profile_id != profile_id:
            changed += 1
        membership.protocol_profile_id = profile_id
        membership.protocol_profile_assignment_source = "default"
        db.add(membership)
    return changed


# ── Startup seeding ───────────────────────────────────────────────────────────

async def _seed_superuser():
    su_username = settings.superuser_username
    su_password = settings.superuser_password
    if not su_username or not su_password:
        return
    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.username == su_username))
        if result.scalar_one_or_none():
            return
        user = User(
            id=str(uuid.uuid4()),
            username=su_username,
            hashed_password=_hash_password(su_password),
            is_superuser=True,
        )
        db.add(user)
        await db.commit()
        log.info("startup.superuser_created", username=su_username)


async def _seed_agency():
    """Optionally seed a default agency from .env on first run."""
    name      = settings.seed_agency_name
    join_code = settings.seed_agency_join_code
    file_stem = settings.seed_agency_file
    if not name or not join_code or not file_stem:
        return
    async with async_session_factory() as db:
        result = await db.execute(
            select(Agency).where(Agency.agency_join_code == join_code)
        )
        if result.scalar_one_or_none():
            return
        agency = Agency(
            id=str(uuid.uuid4()),
            name=name,
            agency_join_code=join_code,
            agency_file=file_stem,
        )
        db.add(agency)
        await db.commit()
        log.info("startup.agency_seeded", name=name, join_code=join_code)


async def _seed_agency_configs():
    """Populate agencies.config JSONB from JSON files for any agency missing config."""
    agencies_dir = Path(__file__).parent / "agencies"
    async with async_session_factory() as db:
        result = await db.execute(select(Agency))
        agencies = result.scalars().all()
        needs_seeding = [a for a in agencies if a.config is None]
        if not needs_seeding:
            return
        for agency in needs_seeding:
            json_path = agencies_dir / f"{agency.agency_file}.json"
            if not json_path.exists():
                continue
            with open(json_path, "r") as f:
                data = json.load(f)
            data.pop("_schema", None)
            data.pop("_comment", None)
            agency.config = data
            db.add(agency)
            log.info("startup.agency_config_seeded", agency=agency.name, file=json_path.name)
        await db.commit()


# Open-join generic agencies — no join code required; student selects one during registration.
# Each file stem must match the agency's "id" field in the JSON.
_OPEN_AGENCY_FILES = [
    "generic_ems_transport",
    "generic_ems_nontransport",
    "generic_fire",
    "generic_fire_ems_transport",
    "generic_fire_ems_nontransport",
]


async def _seed_open_agencies():
    """
    Ensure all open-join generic agency rows exist with config populated.
    Open agencies have no join code — students join them by agency ID during
    registration. All impose no provider level ceiling (primary: Paramedic),
    so students operate at their own self-reported license level.
    Safe to run on every startup; only creates/updates rows that are missing.
    """
    agencies_dir = Path(__file__).parent / "agencies"
    async with async_session_factory() as db:
        for file_stem in _OPEN_AGENCY_FILES:
            json_path = agencies_dir / f"{file_stem}.json"
            if not json_path.exists():
                log.warning("startup.open_agency_file_missing", path=str(json_path))
                continue
            with open(json_path, "r") as f:
                raw = json.load(f)
            agency_id   = raw.get("id", file_stem)
            agency_name = raw.get("display_name", file_stem)
            config_data = {k: v for k, v in raw.items() if not k.startswith("_")}

            result = await db.execute(select(Agency).where(Agency.id == agency_id))
            agency = result.scalar_one_or_none()
            if agency is None:
                agency = Agency(
                    id=agency_id,
                    name=agency_name,
                    agency_join_code=None,   # open — no join code
                    agency_file=file_stem,
                    is_open_join=True,
                    config=config_data,
                )
                db.add(agency)
                log.info("startup.open_agency_created", id=agency_id)
            else:
                dirty = False
                if not agency.is_open_join:
                    agency.is_open_join = True
                    dirty = True
                if agency.config is None:
                    agency.config = config_data
                    dirty = True
                if dirty:
                    db.add(agency)
                    log.info("startup.open_agency_updated", id=agency_id)
        await db.commit()


async def _migrate_member_scope():
    """
    One-time migration: correct any AgencyMember rows whose mca or provider_level
    exceeds their agency's configured ceiling. Runs on every startup but only
    modifies rows that are out of compliance. Safe to run repeatedly.
    """
    async with async_session_factory() as db:
        result = await db.execute(
            select(AgencyMember, Agency)
            .join(Agency, AgencyMember.agency_id == Agency.id)
            .where(Agency.config.isnot(None))
        )
        rows = result.all()
        changed = 0
        for member, agency in rows:
            cfg = agency.config or {}
            correct_mca   = _resolve_member_mca(None, cfg)
            correct_level = _resolve_member_provider_level(member.provider_level, cfg)
            dirty = False
            if member.mca != correct_mca:
                log.info(
                    "startup.member_mca_corrected",
                    user_id=member.user_id,
                    old=member.mca,
                    new=correct_mca,
                )
                member.mca = correct_mca
                dirty = True
            if member.provider_level != correct_level:
                log.info(
                    "startup.member_level_corrected",
                    user_id=member.user_id,
                    old=member.provider_level,
                    new=correct_level,
                )
                member.provider_level = correct_level
                dirty = True
            if dirty:
                db.add(member)
                changed += 1
        if changed:
            await db.commit()
            log.info("startup.member_scope_migration_complete", corrected=changed)


def _migrate_equipment_config(config: dict) -> dict:
    """
    Pure function. Converts an agency config dict from the old equipment schema
    (category-keyed string lists) to the new items-list schema.

    Old schema keys swept: airway, monitoring, trauma, other, carried, medications, not_carried.
    New schema: config["equipment"] = {"items": [{id, carried, source, label?, needs_review?}]}

    Three-pass match per free-text string:
      Pass 1 — exact canonical label match (normalized) → auto-confirm, source=master
      Pass 2 — alias lookup in EQUIPMENT_ALIASES → auto-confirm, source=master
      Pass 3 — substring/prefix of any canonical label → needs_review=True, source=master
      Unresolved → source=custom, needs_review=True, original_text preserved

    Idempotent: returns config unchanged if equipment.items already present.
    Migration data loss note: compound strings like "Suction unit (portable and on-board)"
    map to the primary item only; secondary items land in the needs_review queue.
    """
    equip = config.get("equipment", {})
    if isinstance(equip, dict) and "items" in equip:
        return config  # already migrated

    # Collect all carried strings from every old schema variant
    carried_strings: list[str] = []
    not_carried_strings: list[str] = []
    if isinstance(equip, list):
        carried_strings.extend(str(i) for i in equip)
    elif isinstance(equip, dict):
        for cat in ("airway", "monitoring", "trauma", "other"):
            carried_strings.extend(equip.get(cat, []))
        carried_strings.extend(equip.get("carried", []))   # UI-saved flat list
        carried_strings.extend(equip.get("medications", []))
        not_carried_strings = list(equip.get("not_carried", []))

    # Build a flat label→id map for Pass 3 substring matching
    _all_labels: list[tuple[str, str]] = [
        (label.lower(), item_id)
        for item_id, label in {
            **{iid: lbl for cat in EQUIPMENT_CATALOG.values() for iid, lbl in cat.items()},
            **MEDICATIONS_CATALOG,
        }.items()
    ]

    def _resolve(text: str) -> dict:
        norm = re.sub(r"\s+", " ", text.strip()).lower()
        # Pass 1 — exact canonical name
        matched = equipment_id_for_canonical_name(norm)
        if matched:
            return {"id": matched, "source": "master"}
        # Pass 2 — alias lookup
        matched = equipment_id_for_alias(norm)
        if matched:
            return {"id": matched, "source": "master"}
        # Pass 3 — substring/prefix of a canonical label (first match wins)
        candidates = [iid for lbl, iid in _all_labels if norm in lbl or lbl.startswith(norm)]
        if len(candidates) == 1:
            return {"id": candidates[0], "source": "master", "needs_review": True}
        # Unresolved → custom item
        slug = re.sub(r"[^a-z0-9]+", "_", norm).strip("_")[:40]
        return {
            "id": f"custom_{slug}",
            "source": "custom",
            "label": text.strip(),
            "needs_review": True,
            "original_text": text.strip(),
        }

    items_by_id: dict[str, dict] = {}

    def _add(text: str, carried: bool) -> None:
        if not text or not text.strip():
            return
        resolved = _resolve(text)
        item_id = resolved["id"]
        existing = items_by_id.get(item_id)
        if existing:
            # Preserve explicit "not carried" intent if the same item appears in both sources.
            if carried is False:
                existing["carried"] = False
            return
        items_by_id[item_id] = {**resolved, "carried": carried}

    for s in carried_strings:
        _add(s, carried=True)
    for s in not_carried_strings:
        _add(s, carried=False)

    new_config = {**config, "equipment": {"items": list(items_by_id.values())}}
    return new_config


def _validate_equipment_items_payload(items: object) -> None:
    """Validate the authoritative equipment.items payload before it is persisted."""
    if not isinstance(items, list):
        raise HTTPException(status_code=422, detail="equipment.items must be a list")

    custom_count = 0
    seen_ids: set[str] = set()
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail=f"equipment.items[{idx}] must be an object")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise HTTPException(status_code=422, detail=f"equipment.items[{idx}] missing required field: id")
        if item_id in seen_ids:
            raise HTTPException(status_code=422, detail=f"equipment.items[{idx}] duplicates item id {item_id!r}")
        seen_ids.add(item_id)

        if "carried" not in item or not isinstance(item["carried"], bool):
            raise HTTPException(status_code=422, detail=f"equipment.items[{idx}] missing required boolean field: carried")

        source = item.get("source")
        if source not in {"master", "custom"}:
            raise HTTPException(status_code=422, detail=f"equipment.items[{idx}] source must be 'master' or 'custom'")

        if source == "master":
            if not (is_known_equipment_id(item_id) or is_medication_id(item_id)):
                raise HTTPException(status_code=422, detail=f"equipment.items[{idx}] unknown master inventory id {item_id!r}")
        else:
            if not item.get("label", "").strip():
                raise HTTPException(status_code=422, detail=f"equipment.items[{idx}]: custom items must have a non-empty label")
            custom_count += 1

    if custom_count > 10:
        raise HTTPException(status_code=422, detail=f"Custom equipment items cannot exceed 10 total (submitted {custom_count})")


def _has_equipment_config(config: dict) -> bool:
    """
    Return True when an agency has explicitly entered the equipment-config domain.

    This is intentionally different from "has carried items": an empty migrated
    list is still a configured inventory and should filter menus down to nothing
    rather than fail-open and show every possible item.
    """
    equip = (config or {}).get("equipment")
    if isinstance(equip, dict):
        return "items" in equip or any(k in equip for k in ("airway", "monitoring", "trauma", "other", "carried", "medications", "not_carried"))
    return isinstance(equip, list)


async def _migrate_equipment_configs() -> None:
    """
    Startup migration: convert any agency equipment config still on the old
    category-keyed string schema to the new items-list schema. Idempotent —
    agencies already on the new schema are skipped without a DB write.
    A single failing agency does not abort migration of the rest.
    """
    async with async_session_factory() as db:
        result = await db.execute(select(Agency).where(Agency.config.isnot(None)))
        agencies = result.scalars().all()
        # Quick pre-check: skip entirely if all agencies are already migrated
        needs_migration = [
            a for a in agencies
            if (
                isinstance((a.config or {}).get("equipment"), list)
                or (
                    isinstance((a.config or {}).get("equipment"), dict)
                    and "items" not in (a.config or {}).get("equipment", {})
                )
            )
        ]
        if not needs_migration:
            return
        changed = 0
        for agency in needs_migration:
            try:
                new_config = _migrate_equipment_config(agency.config)
                if new_config is not agency.config:
                    agency.config = new_config
                    flag_modified(agency, "config")
                    db.add(agency)
                    changed += 1
            except Exception:
                log.exception("startup.equipment_migration_failed", agency_id=agency.id)
        if changed:
            await db.commit()
            log.info("startup.equipment_migration_complete", migrated=changed)


# ── Sentry ────────────────────────────────────────────────────────────────────

_PHI_SCRUB_KEYS = frozenset({
    "message", "narrative", "dmist_report", "notes", "prompt", "prompt_payload",
})
_PHI_SCRUB_PATTERN = re.compile(r"(_text|_content|_narrative)$")


def _scrub_sentry_event(event: dict, hint: dict) -> dict:
    """Strip request context and PHI fields from Sentry events before transmission."""
    req = event.get("request", {})
    for key in ("headers", "cookies", "data", "query_string", "env"):
        if key in req:
            req[key] = "[scrubbed]"

    def _scrub(obj):
        if isinstance(obj, dict):
            return {
                k: "[scrubbed]" if k in _PHI_SCRUB_KEYS or _PHI_SCRUB_PATTERN.search(k) else _scrub(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_scrub(item) for item in obj]
        return obj

    for section in ("extra", "contexts"):
        if section in event:
            event[section] = _scrub(event[section])

    # Scrub breadcrumb messages and data payloads (can contain LLM I/O or PHI)
    for crumb in event.get("breadcrumbs", {}).get("values", []):
        if isinstance(crumb, dict):
            if "message" in crumb:
                crumb["message"] = "[scrubbed]"
            if "data" in crumb and isinstance(crumb["data"], dict):
                crumb["data"] = _scrub(crumb["data"])

    return event


# ── Background task supervisor ────────────────────────────────────────────────

async def _supervised(name: str, coro_fn) -> None:
    """Restart a background coroutine after unhandled exceptions, logging to Sentry."""
    while True:
        try:
            await coro_fn()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("background_task.crashed", task=name)
            await asyncio.sleep(30)


# ── Lifespan ──────────────────────────────────────────────────────────────────

def _log_startup_config() -> None:
    """Emit a startup log entry summarizing security-relevant config state.

    Pydantic validators hard-fail weak secrets when ENV=production. This
    function runs in all environments so operators can see what isn't hardened
    even in dev/staging, before a misconfigured deployment reaches production.
    """
    import os
    env = os.getenv("ENV", "development")
    weak: list[str] = []
    if settings.app_secret_key in ("", "changeme") or len(settings.app_secret_key) < 32:
        weak.append("app_secret_key is weak or default")
    if "changeme" in settings.database_url:
        weak.append("database_url contains default 'changeme' password")
    if settings.superuser_username and settings.superuser_password in ("", "changeme"):
        weak.append("superuser_password is weak or default")
    if weak:
        log.warning("startup.config_weak", env=env, issues=weak)
    else:
        log.info("startup.config_ok", env=env)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _lexi_group_phase_task, _ttl_scrub_task
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            send_default_pii=False,
            before_send=_scrub_sentry_event,
            traces_sample_rate=0.1,
        )
    _log_startup_config()
    await init_db()
    await _seed_superuser()
    await _seed_agency()
    await _seed_open_agencies()
    await _seed_agency_configs()
    await _migrate_member_scope()
    await _migrate_equipment_configs()
    asyncio.create_task(asyncio.to_thread(warmup_protocol_caches))
    _lexi_group_phase_task = asyncio.create_task(_supervised("lexi_phase", _lexi_group_phase_worker))
    _ttl_scrub_task = asyncio.create_task(_supervised("ttl_scrub", _ttl_scrub_worker))
    try:
        yield
    finally:
        for task in (_lexi_group_phase_task, _ttl_scrub_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        _lexi_group_phase_task = None
        _ttl_scrub_task = None


configure_logging()
log = get_logger("app.main")


def _debrief_lexi_hints_for_client(scenario: dict, *, condition_unlocked: bool = True) -> list[dict]:
    """Return scenario-authored Lexi chips for post-run coaching only."""
    if not condition_unlocked:
        return []
    raw_hints = scenario.get("debrief_lexi_hints")
    if raw_hints is None:
        raw_hints = scenario.get("lexi_hints") or []
    hints: list[dict] = []
    for hint in raw_hints if isinstance(raw_hints, list) else []:
        if not isinstance(hint, dict):
            continue
        label = str(hint.get("label") or "").strip()
        msg = str(hint.get("msg") or "").strip()
        if label and msg:
            hints.append({"label": label[:80], "msg": msg[:500]})
    return hints

app = FastAPI(
    title="LexiSim",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/docs" if not _IS_PROD else None,
    redoc_url="/redoc" if not _IS_PROD else None,
    openapi_url="/openapi.json" if not _IS_PROD else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(tts_router.router)
app.include_router(auth_router.router)
app.include_router(health_router.router)
app.include_router(scorm_router.router)

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        path=request.url.path,
        method=request.method,
    )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    # HSTS — browsers honor this only over HTTPS; harmless over HTTP
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    # Tailwind and Google Fonts are loaded from CDN — must be in allowlist until
    # they are bundled locally (Phase 4 / QAQI-01).
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "media-src 'self' blob:; "
        "object-src 'none'; "
        "frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Voice input uses the browser SpeechRecognition API and needs same-origin
    # microphone access. Camera/geolocation stay disabled for the SaaS surface.
    response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
    return response


_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CSRF_EXEMPT_PATHS = frozenset({
    "/api/token", "/api/register", "/api/auth/logout", "/api/token/refresh",
    "/api/scorm/auth",   # unauthenticated cross-origin LMS call; no session cookie present
})


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    if (
        request.method not in _CSRF_SAFE_METHODS
        and request.url.path not in _CSRF_EXEMPT_PATHS
        and request.cookies.get("pfd_ems_session")
    ):
        csrf_header = request.headers.get("X-CSRF-Token", "")
        session_token = request.cookies["pfd_ems_session"]
        if not csrf_header or not _verify_csrf_token(csrf_header, session_token):
            return JSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})
    return await call_next(request)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_exception", path=request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ── Request / Response models ─────────────────────────────────────────────────

class StartSessionRequest(BaseModel):
    scenario_id: str = "peds_asthma_01"
    start_drill: bool = False
    drill_source: Optional[str] = None


class ChatRequest(BaseModel):
    message:    str
    session_id: str
    last_scene_speaker: Optional[str] = None


class InterventionRequest(BaseModel):
    intervention_name: str
    source: str = "backend_auto"


class SceneEntryRequest(BaseModel):
    ppe_donned:      list[str]          # e.g. ["Gloves", "Eye Protection"]
    scene_approach:  str                # "direct_contact" | "waited_for_pd"
    pat_assessment:  Optional[str] = None  # "sick" | "not_sick" | null (non-peds)


class TreatmentRequest(BaseModel):
    primary_impression:      Optional[str] = None
    interventions_performed: list[str]
    transport_decision:      bool
    transport_rationale:     str
    als_intercept:           bool
    als_rationale:           str
    additional_notes:        Optional[str] = ""


class DmistRequest(BaseModel):
    primary_impression: Optional[str] = None
    report: str


class NarrativeRequest(BaseModel):
    narrative:          str
    lexi_assist_labels: list[str] = []


class MedControlRequest(BaseModel):
    message: str
    history: list[dict] = []


class LexiRequest(BaseModel):
    session_id: str
    message:    str
    history:    list[dict] = []
    treat_hint: bool = False
    mode: Literal["chat", "debrief"] = "chat"


class PracticeCoachRequest(BaseModel):
    message: str
    history: list[dict] = []
    focus_title: Optional[str] = None
    session_ids: list[str] = []
    conversation_id: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    first_name: Optional[str] = None
    last_name:  Optional[str] = None
    email:      Optional[str] = None
    password:   Optional[str] = None


class GamificationStateRequest(BaseModel):
    """Full gamification state — written whenever the client saves progress."""
    xp:               int
    treats:           int
    badges:           list[str] = []
    pedsCount:        int = 0
    pedsTraumaCount:  int = 0
    sessions:         int = 0   # informational only; server derives count from DB


class SessionProgressRequest(BaseModel):
    """Minimal session completion signal — server computes all awards from DB state."""
    session_id:          str
    elapsed_min:         int = 0
    is_drill:            bool = False
    debrief_elapsed_sec: int = 0    # seconds on debrief/feedback view; 0 = not instrumented
    debrief_only:        bool = False  # skip XP; record only capped debrief CE (idempotent)
    session_active_sec:  int = 0    # total active seconds from launch to debrief close (5-min idle)


class PatGameSubmitRequest(BaseModel):
    total_cards: int
    correct: int
    best_streak: int = 0
    elapsed_sec: int = 0
    run_id: Optional[str] = None         # client-generated UUID for :session dedup
    session_elapsed_sec: int = 0         # launch-to-close time (includes intro/results)


class DevSortGameSubmitRequest(BaseModel):
    total_cards: int
    correct: int
    elapsed_sec: int = 0
    run_id: Optional[str] = None         # client-generated UUID for :session dedup
    session_elapsed_sec: int = 0         # launch-to-close time (includes intro/results)


class MinigameResultRequest(BaseModel):
    game_id: str
    run_id: Optional[str] = None
    score: int = 0       # 0–100
    total: int = 0
    correct: int = 0
    elapsed_sec: int = 0
    session_elapsed_sec: int = 0         # launch-to-close time (includes intro/results)
    mistake_tags: Optional[List[str]] = None
    mode: Optional[str] = None
    hint_count: Optional[int] = None
    sequence_data: Optional[dict] = None
    case_evidence: Optional[List[dict]] = None  # raw evidence for backend-scored games (e.g. resp_dx_1q)


class UpdateMembershipRequest(BaseModel):
    agency_id:      Optional[str] = None   # target membership; falls back to ctx.agency_id
    provider_level: Optional[str] = None
    mca:            Optional[str] = None


class AdminAddMemberRequest(BaseModel):
    username:       str
    role:           str = "student"
    provider_level: str = "EMT"
    mca:            Optional[str] = None   # None → inherit from agency config


class AdminUpdateMemberRequest(BaseModel):
    first_name:     Optional[str] = None
    last_name:      Optional[str] = None
    email:          Optional[str] = None
    provider_level: Optional[str] = None
    mca:            Optional[str] = None
    protocol_profile_id: Optional[str] = None
    is_active:      Optional[bool] = None


class AdminResetPasswordRequest(BaseModel):
    new_password: str


class CreateAgencyRequest(BaseModel):
    name:             str
    agency_join_code: str
    agency_file:      str


class UpdateMemberRoleRequest(BaseModel):
    role: str  # must be one of: "student" | "instructor" | "admin"


class UpdateAgencyRequest(BaseModel):
    name:             Optional[str] = None
    agency_join_code: Optional[str] = None


class AgencyConfigUpdate(BaseModel):
    """Clinical config stored in agencies.config JSONB. All arrays default to [] (not None)."""
    display_name:                Optional[str]  = None
    unit_designator:             Optional[str]  = None
    mca:                         Optional[str]  = None
    available_mcas:              list[str]      = []
    provider_levels:             Optional[dict] = None
    service_type:                Optional[dict] = None
    ai_prompt_context:           Optional[str]  = None
    equipment:                   Optional[dict] = None
    training_and_certifications: Optional[dict] = None
    sops:                        list[dict]     = []


class ProtocolProfileCreateRequest(BaseModel):
    display_name: str
    base_protocol_set: str = "NASEMSO"
    official_mca_id: Optional[str] = None
    profile_type: str = "agency_local"
    is_default: bool = False


class ProtocolProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    base_protocol_set: Optional[str] = None
    official_mca_id: Optional[str] = None
    profile_type: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class ProtocolSelectionUpdate(BaseModel):
    protocol_id: str
    selection_id: str
    is_selected: bool
    selected_value: Optional[Any] = None
    base_protocol_version: Optional[str] = None


class ProtocolSelectionsUpdateRequest(BaseModel):
    selections: list[ProtocolSelectionUpdate] = []


class AgencySOPCreateRequest(BaseModel):
    rule_type: str = "local_sop"
    extracted_rule: str
    source_quote: Optional[str] = None
    source_label: Optional[str] = None
    page_number: Optional[int] = None
    clinical_concept_tags: list[str] = []
    intervention_action_ids: list[str] = []
    patch_operations: Optional[list[dict]] = None
    metadata_json: dict = {}


class AgencySOPUpdateRequest(BaseModel):
    rule_type: Optional[str] = None
    extracted_rule: Optional[str] = None
    source_quote: Optional[str] = None
    source_label: Optional[str] = None
    page_number: Optional[int] = None
    clinical_concept_tags: Optional[list[str]] = None
    intervention_action_ids: Optional[list[str]] = None
    patch_operations: Optional[list[dict]] = None
    metadata_json: Optional[dict] = None


class AgencySOPReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: Optional[str] = None


class ProtocolNotificationSeenRequest(BaseModel):
    notification_id: str


class ToggleActiveRequest(BaseModel):
    is_active: bool


class LexiQuestionsRequest(BaseModel):
    provider_level: str = "EMT"
    mca:            str = "mi_base"


class LexiRoundRequest(BaseModel):
    score:          int              # 0–5 correct
    provider_level: Optional[str] = None
    mca:            Optional[str] = None
    question_keys: Optional[list[str]] = None
    missed_question_keys: Optional[list[str]] = None


class LexiGroupJoinRequest(BaseModel):
    room_code: str


class LexiGroupSessionRequest(BaseModel):
    session_id: str


class LexiGroupAnswerRequest(BaseModel):
    session_id: str
    choice: int


class LexiGroupFeedbackReadyRequest(BaseModel):
    session_id: str


class LexiGroupKickRequest(BaseModel):
    session_id: str
    user_id: str


class AgencyGroupCreateRequest(BaseModel):
    name: str
    group_type: str = "custom"   # station|shift|crew|custom
    is_system: bool = False


class ChallengeTeamCreateRequest(BaseModel):
    name: str
    challenge_type: str = "lexi_group"
    min_members: int = 2
    max_members: int = 5


class ChallengeTeamJoinRequest(BaseModel):
    join_code: str


class ChallengeTeamSessionRequest(BaseModel):
    team_id: str


class ChallengeTeamRemoveMemberRequest(BaseModel):
    user_id: str


class TeamPresenceRequest(BaseModel):
    team_id: str


class TeamInviteCreateRequest(BaseModel):
    source_team_id: str
    target_team_ids: list[str]
    challenge_type: str = "lexi_group"
    timeout_sec: int = 60


class TeamInviteRespondRequest(BaseModel):
    accept: bool


class TeamMatchStartRequest(BaseModel):
    match_id: str


class ChallengeCreateRequest(BaseModel):
    name:              str
    description:       Optional[str] = None
    icon:              Optional[str] = None
    requirements:      list[dict]   = []   # [{type, scenario_ids, count?, label?}]
    time_goal_minutes: Optional[int] = None
    repeatable:        bool = False


class ChallengeUpdateRequest(BaseModel):
    name:              Optional[str]       = None
    description:       Optional[str]       = None
    icon:              Optional[str]       = None
    requirements:      Optional[list[dict]] = None
    is_active:         Optional[bool]      = None
    time_goal_minutes: Optional[int]       = None   # 0 = clear goal; positive = set goal
    repeatable:        Optional[bool]      = None



# ── Game levels (mirror of JS LEVELS array) ──────────────────────────────────

_GAME_LEVELS = [
    (0,    "Recruit",               "🪖"),
    (250,  "Trainee",               "🎯"),
    (800,  "Probie",                "🚒"),
    (2700, "Fully Certified",       "✅"),
    (3800, "Team Lead",             "👥"),
    (5200, "Field Training Officer","⭐"),
    (6900, "Instructor",            "📘"),
    (8900, "Incident Commander",    "🦺"),
    (11200, "Supervisor",           "🧭"),
    (13800, "Chief",                "👑"),
]


def _xp_to_level(xp: int) -> tuple[str, str]:
    """Return (level_name, icon) for a given XP total."""
    level_name, icon = _GAME_LEVELS[0][1], _GAME_LEVELS[0][2]
    for threshold, name, ic in _GAME_LEVELS:
        if xp >= threshold:
            level_name, icon = name, ic
        else:
            break
    return level_name, icon


async def _write_feed_event(
    agency_id: str, user: "User", event_type: str,
    event_label: str, event_icon: str, db: "AsyncSession"
) -> None:
    """Append a single accomplishment to the feed_events table."""
    if not agency_id:
        return
    first = user.first_name or user.username
    last  = user.last_name
    display = f"{first} {last[0]}." if first and last else first
    db.add(FeedEvent(
        agency_id    = agency_id,
        user_id      = user.id,
        display_name = display,
        event_type   = event_type,
        event_label  = event_label,
        event_icon   = event_icon,
    ))


# ── Gamification helpers ─────────────────────────────────────────────────────

PASSING_SCORE = 70       # normalized 0-100 threshold
PASSING_PCT   = 0.70     # 70% — used to compute passing on any scale

_PILOT_PEDIATRIC_CHAMPION_SCENARIOS = frozenset({
    "peds_croup_01",
    "peds_asthma_01",
    "peds_diabetic_emergency_01",
    "peds_febrile_seizure_01",
    "peds_trauma_01_soft_tissue",
    "peds_trauma_07_head_injury",
    "peds_trauma_03_extremity",
    "peds_trauma_02_partial_choking",
    "peds_anaphylaxis_01",
})


def _assessment_max_from_subscores(subscores: dict | None) -> int:
    """Return the assessment denominator implied by the stored subscore shape."""
    maxes = (subscores or {}).get("_maxes") if isinstance(subscores, dict) else None
    if isinstance(maxes, dict):
        keys = [
            "clinical_performance",
            "protocols_treatment",
            "scope_adherence",
            "dmist",
            "professionalism",
        ]
        try:
            return sum(int(maxes[k]) for k in keys if k in maxes)
        except (TypeError, ValueError):
            pass
    if subscores and "protocols_treatment" in subscores:
        return 100
    return 80


def _assessment_pct(score_raw: Optional[int], subscores: dict | None = None) -> int:
    """Normalize a raw assessment score onto a 0-100 scale for pass/on-track reporting."""
    if score_raw is None:
        return 0
    denom = _assessment_max_from_subscores(subscores)
    return round((max(0, min(score_raw, denom)) / float(denom)) * 100)


def _synchronize_debrief_scores(
    debrief_text: str,
    subscores: dict[str, int],
    scenario: dict,
    *,
    include_narrative: bool,
) -> str:
    """Force the markdown debrief's printed score lines to match backend truth."""
    if not debrief_text:
        return debrief_text

    rubric = scenario.get("scoring_rubric") or {}
    treatment_keys = [
        key for key in ("protocols_treatment", "scope_adherence")
        if key in subscores
    ]
    treatment_labels = {
        "protocols_treatment": ("Protocols/Treatment", "Protocols & Treatment"),
        "scope_adherence": ("Scope", "Scope Adherence"),
    }
    subscore_maxes = subscores.get("_maxes") if isinstance(subscores.get("_maxes"), dict) else {}
    clinical_max = int(subscore_maxes.get("clinical_performance") or (rubric.get("clinical_performance") or {}).get("max", 40))
    dmist_max = int(subscore_maxes.get("dmist") or (rubric.get("dmist") or {}).get("max", 10))
    professionalism_max = int(subscore_maxes.get("professionalism") or (rubric.get("professionalism") or {}).get("max", 10))
    narrative_max = int(subscore_maxes.get("narrative") or (rubric.get("narrative") or {}).get("max", 20))
    assessment_max = _assessment_max_from_subscores(subscores)
    assessment_score = _compute_assessment_score_from_subscores(subscores) or 0

    replacements: list[tuple[str, str]] = [
        (r"(?im)^Clinical Performance score:\s*\d+/\d+\s*$", f"Clinical Performance score: {subscores.get('clinical_performance', 0)}/{clinical_max}"),
        (r"(?im)^DMIST score:\s*\d+/\d+\s*$", f"DMIST score: {subscores.get('dmist', 0)}/{dmist_max}"),
        (r"(?im)^Professionalism score:\s*\d+/\d+\s*(?:\(locked\))?\s*$", f"Professionalism score: {subscores.get('professionalism', 0)}/{professionalism_max}"),
        (r"(?im)^- Clinical Performance:\s*\d+/\d+\s*$", f"- Clinical Performance: {subscores.get('clinical_performance', 0)}/{clinical_max}"),
        (r"(?im)^- DMIST Quality:\s*\d+/\d+\s*$", f"- DMIST Quality: {subscores.get('dmist', 0)}/{dmist_max}"),
        (r"(?im)^- Professionalism:\s*\d+/\d+.*$", f"- Professionalism: {subscores.get('professionalism', 0)}/{professionalism_max}"),
        (r"(?im)^\*{0,2}ASSESSMENT SCORE:\s*\d+/\d+.*$", f"ASSESSMENT SCORE: {assessment_score}/{assessment_max}"),
        (r"(?im)^ASSESSMENT\s*$", f"ASSESSMENT SCORE: {assessment_score}/{assessment_max}"),
    ]

    if include_narrative and "narrative" in subscores:
        replacements.extend([
            (r"(?im)^Narrative score:\s*\d+/\d+\s*$", f"Narrative score: {subscores.get('narrative', 0)}/{narrative_max}"),
            (r"(?im)^- Narrative Quality:\s*\d+/\d+.*$", f"- Narrative Quality: {subscores.get('narrative', 0)}/{narrative_max}"),
        ])
    for key in treatment_keys:
        line_label, breakdown_label = treatment_labels[key]
        max_val = int(subscore_maxes.get(key) or (rubric.get(key) or {}).get("max", 20))
        replacements.extend([
            (rf"(?im)^{re.escape(line_label)} score:\s*\d+/\d+\s*$", f"{line_label} score: {subscores.get(key, 0)}/{max_val}"),
            (rf"(?im)^- {re.escape(breakdown_label)}:\s*\d+/\d+\s*$", f"- {breakdown_label}: {subscores.get(key, 0)}/{max_val}"),
        ])

    out = debrief_text
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out)

    out = re.sub(
        r"(?im)^- Greeted the crew:(.*)$",
        r"- Greeted the patient/caregiver:\1",
        out,
    )
    # Bottom score summaries are redundant with the structured score card in the UI.
    # Keep section-local score lines, but strip any trailing SCORE BREAKDOWN / ASSESSMENT footer.
    out = re.sub(
        r"(?ims)\n?\*{0,2}SCORE BREAKDOWN:?\*{0,2}\s*$.*$",
        "",
        out,
    )
    out = re.sub(
        r"(?im)^\*{0,2}ASSESSMENT SCORE:\s*\d+/\d+.*$",
        "",
        out,
    )
    out = re.sub(
        r"(?im)^ASSESSMENT\s*$",
        "",
        out,
    )
    out = out.rstrip()

    return out


async def _generate_debrief_with_retry(
    session,
    scenario: dict,
    treatment_data: dict,
    narrative_data: dict,
    dmist_report: str,
    *,
    agency_dict: dict | None = None,
    lexi_assist_labels: list | None = None,
    include_narrative: bool = True,
    scene_entry: dict | None = None,
    student_history=None,
    minigame_gaps: dict | None = None,
    retries: int = 1,
    retry_delay_seconds: float = 1.0,
):
    """Retry full debrief generation once at the application layer.

    This sits above the lower-level Groq retries so transient failures in any
    part of the broader debrief pipeline still get one fresh end-to-end retry
    before the route returns a 503 to the client.
    """
    last_exc: Exception | None = None
    total_attempts = max(1, int(retries) + 1)
    for attempt in range(1, total_attempts + 1):
        try:
            return await evaluate_and_generate_debrief(
                session,
                scenario,
                treatment_data,
                narrative_data,
                dmist_report,
                agency_dict=agency_dict,
                lexi_assist_labels=lexi_assist_labels,
                include_narrative=include_narrative,
                scene_entry=scene_entry,
                student_history=student_history,
                minigame_gaps=minigame_gaps,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= total_attempts:
                break
            log.warning(
                "Debrief generation attempt %d/%d failed for session %s: %s: %s — retrying",
                attempt,
                total_attempts,
                getattr(session, "id", "(unknown)"),
                type(exc).__name__,
                exc,
            )
            await asyncio.sleep(retry_delay_seconds)

    assert last_exc is not None
    raise last_exc


def _store_session_debrief(session: SimSession, debrief_text: str) -> None:
    """Persist latest feedback while preserving the first generated debrief."""
    session.feedback = debrief_text
    if not getattr(session, "debrief_markdown", None):
        session.debrief_markdown = debrief_text


# ── Assessment XP (raw assessment score → scaled XP) ─────────────────────────
def _xp_for_assessment(score_raw: Optional[int], max_raw: int, max_xp: int = 500) -> int:
    """Convert a raw assessment score to XP using its scenario-appropriate denominator."""
    if score_raw is None or max_raw <= 0: return 0
    pct = score_raw / float(max_raw)
    if pct >= 1.00: return max_xp
    if pct >= 0.90: return round(max_xp * 0.75)
    if pct >= 0.80: return round(max_xp * 0.50)
    if pct >= 0.70: return round(max_xp * 0.33)
    if pct >= 0.60: return round(max_xp * 0.20)
    return 0

# ── Narrative XP (0-20 raw score → scaled XP) ────────────────────────────────
def _xp_for_narrative(score_20: Optional[int], max_xp: int = 100) -> int:
    """Linear mapping of 0-20 narrative score to 0-max_xp."""
    if score_20 is None: return 0
    return round(max(0, min(score_20, 20)) / 20.0 * max_xp)

# Legacy wrapper — kept for backward compat on old drill path (removed later)
def _xp_for_score(score: Optional[int]) -> int:
    if score is None:   return 0
    if score >= 100:    return 600
    if score >= 90:     return 450
    if score >= 80:     return 300
    if score >= 70:     return 200
    if score >= 60:     return 120
    return 0

# Level thresholds — mirrors JS LEVELS array
_LEVEL_THRESHOLDS = [0, 250, 800, 2700, 3800, 5200, 6900, 8900, 11200, 13800]

def _level_index(xp: int) -> int:
    """0-based index into _LEVEL_THRESHOLDS for the given XP total."""
    idx = 0
    for i, t in enumerate(_LEVEL_THRESHOLDS):
        if xp >= t:
            idx = i
    return idx


# Drill XP controls (legacy — drill mode being retired)
DRILL_DAILY_CAP_XP   = 150
DRILL_PER_RUN_MAX_XP = 75

# Random Call XP controls (server-authoritative)
RC_DAILY_CAP_XP         = 600
RC_ASSESSMENT_MAX_XP    = 200
RC_NARRATIVE_MAX_XP     = 100
DRILL_MIN_UNLOCKED_FOR_RANDOM = 5
DRILL_NO_REPEAT_WINDOW = 3
RC_MIN_COMPLETED_FOR_RANDOM = 5
RC_NO_REPEAT_WINDOW = 3
PAT_DAILY_CAP_XP = 30
PAT_PER_RUN_MAX_XP = 30
DEV_SORT_DAILY_CAP_XP = 30
DEV_SORT_PER_RUN_MAX_XP = 30


def _drill_day_utc() -> date:
    return datetime.utcnow().date()


def _current_drill_ledger(user: User) -> tuple[date, int, int, list[str]]:
    """Return today's drill ledger values; stale day values read as zero."""
    today = _drill_day_utc()
    if user.drill_xp_day != today:
        return today, 0, 0, []
    return (
        today,
        user.drill_xp_today or 0,
        user.drill_runs_today or 0,
        list(user.drill_paid_ids or []),
    )


def _ensure_drill_ledger_today(user: User) -> tuple[int, int, list[str]]:
    """Normalize stale drill ledger fields in-place for write paths."""
    today, xp_today, runs_today, paid_ids = _current_drill_ledger(user)
    if user.drill_xp_day != today:
        user.drill_xp_day = today
        user.drill_xp_today = 0
        user.drill_runs_today = 0
        user.drill_paid_ids = []
        return 0, 0, []
    return xp_today, runs_today, paid_ids


def _current_pat_ledger(user: User) -> tuple[date, int, int]:
    today = _drill_day_utc()
    if user.pat_xp_day != today:
        return today, 0, 0
    return today, user.pat_xp_today or 0, user.pat_runs_today or 0


def _ensure_pat_ledger_today(user: User) -> tuple[int, int]:
    today, xp_today, runs_today = _current_pat_ledger(user)
    if user.pat_xp_day != today:
        user.pat_xp_day = today
        user.pat_xp_today = 0
        user.pat_runs_today = 0
        return 0, 0
    return xp_today, runs_today


def _current_dev_sort_ledger(user: User) -> tuple[date, int, int]:
    today = _drill_day_utc()
    if user.dev_sort_xp_day != today:
        return today, 0, 0
    return today, user.dev_sort_xp_today or 0, user.dev_sort_runs_today or 0


def _ensure_dev_sort_ledger_today(user: User) -> tuple[int, int]:
    today, xp_today, runs_today = _current_dev_sort_ledger(user)
    if user.dev_sort_xp_day != today:
        user.dev_sort_xp_day = today
        user.dev_sort_xp_today = 0
        user.dev_sort_runs_today = 0
        return 0, 0
    return xp_today, runs_today


async def _get_unlocked_drill_ids(user_id: str, agency_id: Optional[str], db: AsyncSession) -> list[str]:
    """Return scenario_ids eligible for drills (full, passing, non-drill completion)."""
    if not agency_id:
        return []
    rows_result = await db.execute(
        select(SimSession.scenario_id, SimSession.score, SimSession.narrative_data).where(
            SimSession.user_id == user_id,
            SimSession.agency_id == agency_id,
            SimSession.ended_at.isnot(None),
        )
    )
    unlocked = set()
    for row in rows_result.all():
        nd = row.narrative_data or {}
        if nd.get("drill"):
            continue
        if (row.score or 0) < PASSING_SCORE:
            continue
        # Keep list resilient to deleted/renamed scenario files.
        try:
            sc = load_scenario(row.scenario_id)
        except Exception:
            continue
        if sc.get("is_orientation"):
            continue
        unlocked.add(row.scenario_id)
    return sorted(unlocked)


async def _get_completed_scenario_ids(user_id: str, agency_id: Optional[str], db: AsyncSession) -> list[str]:
    """Return scenario_ids the user has completed at least once (non-drill, any score).
    Used for Random Call pool eligibility."""
    if not agency_id:
        return []
    rows_result = await db.execute(
        select(SimSession.scenario_id, SimSession.narrative_data).where(
            SimSession.user_id   == user_id,
            SimSession.agency_id == agency_id,
            SimSession.ended_at.isnot(None),
        )
    )
    completed = set()
    for row in rows_result.all():
        nd = row.narrative_data or {}
        if nd.get("drill"):
            continue
        if row.scenario_id in completed:
            continue
        try:
            sc = load_scenario(row.scenario_id)
        except Exception:
            continue
        if sc.get("is_orientation"):
            continue
        completed.add(row.scenario_id)
    return sorted(completed)


def _resolve_requirements(ch: "Challenge") -> list[dict]:
    """Return the canonical requirements list for a challenge.
    Falls back to legacy scenario_ids when requirements column is empty."""
    reqs = ch.requirements
    if reqs:
        return reqs
    legacy = ch.scenario_ids or []
    if legacy:
        return [{"type": "specific", "scenario_ids": legacy}]
    return []


def _req_scenario_ids(req: dict) -> list[str]:
    return req.get("scenario_ids") or []


def _req_drill_ids(req: dict) -> list[str]:
    return req.get("drill_ids") or []


def _canonical_challenge_drill_id(drill_id: str) -> str:
    aliases = {
        "drill_pat": "pat",
        "pat_dash": "pat",
        "drill_dev": "dev_sort",
    }
    return aliases.get(str(drill_id), str(drill_id))


def _challenge_drill_activity_ids(drill_id: str) -> set[str]:
    canonical = _canonical_challenge_drill_id(drill_id)
    aliases = {str(drill_id), canonical}
    if canonical == "pat":
        aliases.update({"pat_dash", "drill_pat"})
    elif canonical == "dev_sort":
        aliases.update({"dev_sort", "drill_dev"})
    return aliases


def _challenge_drill_pass_threshold(drill_id: str) -> int:
    metadata = get_minigame_metadata(_canonical_challenge_drill_id(drill_id)) or {}
    return int((metadata.get("pass_threshold") or {}).get("score_gte", _MINIGAME_LEARNING_PASSING_SCORE))


def _challenge_scenario_title(scenario_id: str, *, reveal_full: bool = False) -> str:
    """Return the learner-facing challenge title for a scenario.

    Incomplete challenge requirements use the scenario's default/map-facing
    display title so the menu does not reveal the diagnosis-specific title
    before the learner has completed the case.
    """
    try:
        scenario = load_scenario(scenario_id)
    except Exception:
        return scenario_id
    if reveal_full:
        return scenario.get("title") or scenario.get("display_title") or scenario_id
    return scenario.get("display_title") or scenario.get("title") or scenario_id


def _challenge_scenario_titles(scenario_ids: list[str], revealed_scenario_ids: set[str]) -> dict[str, str]:
    return {
        sid: _challenge_scenario_title(sid, reveal_full=sid in revealed_scenario_ids)
        for sid in scenario_ids
    }


def _check_requirement_met(
    req: dict,
    best_scores: dict,
    *,
    user: "User | None" = None,
    ce_seconds: int = 0,
    best_drill_scores: dict | None = None,
) -> bool:
    """Return True if a single requirement is satisfied.

    Score-based types (specific, any_n) use best_scores keyed by scenario_id.
    Time-based and completion-based types use the extra keyword arguments.
    """
    rtype = req.get("type", "specific")

    if rtype == "orientation_complete":
        return user is not None and user.orientation_completed_at is not None

    if rtype == "min_ce_minutes":
        return ce_seconds >= int(req.get("minutes", 0)) * 60

    ids = _req_scenario_ids(req)
    drill_ids = _req_drill_ids(req)
    best_drill_scores = best_drill_scores or {}
    if not ids and not drill_ids:
        return False
    drill_done = [
        did for did in drill_ids
        if best_drill_scores.get(_canonical_challenge_drill_id(did), 0) >= _challenge_drill_pass_threshold(did)
    ]
    if rtype == "specific":
        return (
            all(best_scores.get(sid, 0) >= PASSING_SCORE for sid in ids)
            and len(drill_done) == len(drill_ids)
        )
    elif rtype == "any_n":
        needed    = req.get("count", 1)
        completed = sum(1 for sid in ids if best_scores.get(sid, 0) >= PASSING_SCORE) + len(drill_done)
        return completed >= needed
    return False


def _challenge_activity_ids(requirements: list[dict]) -> set[str]:
    activity_ids: set[str] = set()
    for req in requirements:
        activity_ids.update(_req_scenario_ids(req))
        for drill_id in _req_drill_ids(req):
            activity_ids.update(_challenge_drill_activity_ids(drill_id))
    return activity_ids


async def _best_challenge_drill_scores(
    *,
    user: User,
    db: AsyncSession,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> dict[str, int]:
    filters = [MinigameResult.user_id == user.id]
    if started_at is not None:
        filters.append(MinigameResult.created_at >= started_at)
    if ended_at is not None:
        filters.append(MinigameResult.created_at <= ended_at)
    rows = await db.execute(
        select(MinigameResult.game_id, func.max(MinigameResult.score))
        .where(*filters)
        .group_by(MinigameResult.game_id)
    )
    best = {
        _canonical_challenge_drill_id(game_id): int(score or 0)
        for game_id, score in rows.all()
    }

    # PAT and the original developmental sort use legacy aggregate columns.
    # When an attempt window is present, require at least one in-window drill time
    # entry so old completions do not satisfy a new repeat attempt by themselves.
    legacy_aliases = {
        "pat": {"pat", "pat_dash", "drill_pat"},
        "dev_sort": {"dev_sort", "drill_dev"},
    }
    if started_at is not None:
        ce_filters = [
            CeTimeLog.user_id == user.id,
            CeTimeLog.scenario_id.in_(sorted({a for aliases in legacy_aliases.values() for a in aliases})),
            CeTimeLog.source_id.like("%:session"),
            CeTimeLog.created_at >= started_at,
        ]
        if ended_at is not None:
            ce_filters.append(CeTimeLog.created_at <= ended_at)
        ce_rows = await db.execute(select(CeTimeLog.scenario_id).where(*ce_filters))
        in_window = {
            canonical
            for raw_id in ce_rows.scalars().all()
            for canonical, aliases in legacy_aliases.items()
            if raw_id in aliases
        }
    else:
        in_window = set(legacy_aliases)

    if "pat" in in_window:
        best["pat"] = max(best.get("pat", 0), int(user.pat_best_accuracy or 0))
    if "dev_sort" in in_window:
        best["dev_sort"] = max(best.get("dev_sort", 0), int(user.dev_sort_best_accuracy or 0))
    return best


def _challenge_attempt_out(attempt: ChallengeAttempt | None) -> dict | None:
    if not attempt:
        return None
    return {
        "id": attempt.id,
        "challenge_id": attempt.challenge_id,
        "attempt_number": attempt.attempt_number,
        "status": attempt.status,
        "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
        "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
        "completion_summary": attempt.completion_summary or None,
    }


async def _latest_challenge_attempts(
    user_id: str,
    challenge_ids: list[str],
    db: AsyncSession,
) -> dict[str, ChallengeAttempt]:
    if not challenge_ids:
        return {}
    rows = await db.execute(
        select(ChallengeAttempt)
        .where(
            ChallengeAttempt.user_id == user_id,
            ChallengeAttempt.challenge_id.in_(challenge_ids),
        )
        .order_by(ChallengeAttempt.challenge_id, ChallengeAttempt.started_at.desc())
    )
    latest: dict[str, ChallengeAttempt] = {}
    for attempt in rows.scalars().all():
        latest.setdefault(attempt.challenge_id, attempt)
    return latest


async def _challenge_progress_for_window(
    *,
    ch: Challenge,
    user_id: str,
    agency_id: str,
    db: AsyncSession,
    user: User | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    revealed_scenario_ids: set[str] | None = None,
) -> dict:
    requirements = _resolve_requirements(ch)

    session_filters = [
        SimSession.user_id == user_id,
        SimSession.agency_id == agency_id,
        SimSession.ended_at.isnot(None),
    ]
    if started_at is not None:
        session_filters.append(SimSession.ended_at >= started_at)
    if ended_at is not None:
        session_filters.append(SimSession.ended_at <= ended_at)

    sessions_result = await db.execute(
        select(SimSession.scenario_id, SimSession.score, SimSession.narrative_data)
        .where(*session_filters)
    )
    best_scores: dict[str, int] = {}
    completed_scenario_ids: set[str] = set()
    for row in sessions_result.all():
        sid, score, nd = row.scenario_id, (row.score or 0), (row.narrative_data or {})
        if nd.get("drill"):
            continue
        completed_scenario_ids.add(sid)
        best_scores[sid] = max(best_scores.get(sid, 0), score)
    label_reveal_ids = revealed_scenario_ids if revealed_scenario_ids is not None else completed_scenario_ids
    best_drill_scores: dict[str, int] = {}
    if user is not None:
        best_drill_scores = await _best_challenge_drill_scores(
            user=user,
            db=db,
            started_at=started_at,
            ended_at=ended_at,
        )

    activity_ids = _challenge_activity_ids(requirements)
    ce_seconds = 0
    if activity_ids:
        ce_filters = [
            CeTimeLog.user_id == user_id,
            CeTimeLog.scenario_id.in_(list(activity_ids)),
            CeTimeLog.source_id.like("%:session"),
        ]
        if started_at is not None:
            ce_filters.append(CeTimeLog.created_at >= started_at)
        if ended_at is not None:
            ce_filters.append(CeTimeLog.created_at <= ended_at)
        ce_result = await db.execute(select(func.sum(CeTimeLog.seconds)).where(*ce_filters))
        ce_seconds = int(ce_result.scalar() or 0)

    req_progress = []
    total_needed = total_done = 0
    for req in requirements:
        ids = _req_scenario_ids(req)
        drill_ids = _req_drill_ids(req)
        rtype = req.get("type", "specific")
        done = [sid for sid in ids if best_scores.get(sid, 0) >= PASSING_SCORE]
        drill_done = [
            did for did in drill_ids
            if best_drill_scores.get(_canonical_challenge_drill_id(did), 0) >= _challenge_drill_pass_threshold(did)
        ]
        item_count = len(ids) + len(drill_ids)
        needed = req.get("count", item_count) if rtype == "any_n" else item_count
        if rtype in ("orientation_complete", "min_ce_minutes"):
            needed = 1
            completed_count = 1 if _check_requirement_met(req, best_scores, user=user, ce_seconds=ce_seconds, best_drill_scores=best_drill_scores) else 0
        else:
            completed_count = len(done) + len(drill_done)
        req_progress.append({
            "type":          rtype,
            "label":         req.get("label", ""),
            "scenario_ids":  ids,
            "scenario_titles": _challenge_scenario_titles(ids, label_reveal_ids),
            "drill_ids":     drill_ids,
            "completed_ids": done,
            "completed_drill_ids": drill_done,
            "completed":     min(completed_count, needed),
            "needed":        needed,
        })
        total_done += min(completed_count, needed)
        total_needed += needed

    score_requirements = [
        req for req in requirements
        if _req_scenario_ids(req) or _req_drill_ids(req) or req.get("type") in ("orientation_complete", "min_ce_minutes")
    ]
    requirements_met = bool(requirements) and (
        all(
            _check_requirement_met(req, best_scores, user=user, ce_seconds=ce_seconds, best_drill_scores=best_drill_scores)
            for req in score_requirements
        )
        if score_requirements
        else bool(activity_ids) and ce_seconds > 0
    )
    time_goal_seconds = int(ch.time_goal_minutes or 0) * 60
    time_goal_met = time_goal_seconds <= 0 or ce_seconds >= time_goal_seconds

    return {
        "requirements_progress": req_progress,
        "scenarios_completed": total_done,
        "scenarios_total": total_needed,
        "challenge_ce_seconds": ce_seconds,
        "requirements_met": requirements_met,
        "time_goal_met": time_goal_met,
        "complete": requirements_met and time_goal_met,
    }


def _empty_challenge_progress(ch: Challenge, revealed_scenario_ids: set[str] | None = None) -> dict:
    requirements = _resolve_requirements(ch)
    revealed_scenario_ids = revealed_scenario_ids or set()
    req_progress = []
    total_needed = 0
    for req in requirements:
        ids = _req_scenario_ids(req)
        drill_ids = _req_drill_ids(req)
        item_count = len(ids) + len(drill_ids)
        needed = req.get("count", item_count) if req.get("type") == "any_n" else item_count
        if req.get("type") in ("orientation_complete", "min_ce_minutes"):
            needed = 1
        total_needed += needed
        req_progress.append({
            "type": req.get("type", "specific"),
            "label": req.get("label", ""),
            "scenario_ids": ids,
            "scenario_titles": _challenge_scenario_titles(ids, revealed_scenario_ids),
            "drill_ids": drill_ids,
            "completed_ids": [],
            "completed_drill_ids": [],
            "completed": 0,
            "needed": needed,
        })
    return {
        "requirements_progress": req_progress,
        "scenarios_completed": 0,
        "scenarios_total": total_needed,
        "challenge_ce_seconds": 0,
        "requirements_met": False,
        "time_goal_met": not bool(ch.time_goal_minutes),
        "complete": False,
    }


async def _complete_repeatable_attempt_if_ready(
    *,
    ch: Challenge,
    attempt: ChallengeAttempt,
    user: User,
    db: AsyncSession,
    revealed_scenario_ids: set[str] | None = None,
) -> dict:
    ended_at = attempt.completed_at if attempt.status == "completed" else None
    progress = await _challenge_progress_for_window(
        ch=ch,
        user_id=user.id,
        agency_id=ch.agency_id,
        db=db,
        user=user,
        started_at=attempt.started_at,
        ended_at=ended_at,
        revealed_scenario_ids=revealed_scenario_ids,
    )
    if attempt.status == "active" and progress["complete"]:
        attempt.status = "completed"
        attempt.completed_at = datetime.utcnow()
        attempt.completion_summary = {
            "requirements_progress": progress["requirements_progress"],
            "scenarios_completed": progress["scenarios_completed"],
            "scenarios_total": progress["scenarios_total"],
            "challenge_ce_seconds": progress["challenge_ce_seconds"],
            "time_goal_minutes": ch.time_goal_minutes,
        }
        badge_id = f"ch_{ch.id}"
        existing_badges = set(user.badges or [])
        if badge_id not in existing_badges:
            existing_badges.add(badge_id)
            user.badges = list(existing_badges)
            await _write_feed_event(ch.agency_id, user, "badge", ch.name, ch.icon or "🏅", db)
        progress = {
            **progress,
            "attempt": _challenge_attempt_out(attempt),
            "earned": True,
        }
    return progress


async def _complete_active_repeatable_challenges(
    *,
    user: User,
    agency_id: str | None,
    db: AsyncSession,
) -> None:
    if not agency_id:
        return
    await db.flush()
    rows = await db.execute(
        select(Challenge, ChallengeAttempt)
        .join(ChallengeAttempt, ChallengeAttempt.challenge_id == Challenge.id)
        .where(
            Challenge.agency_id == agency_id,
            Challenge.is_active == True,  # noqa: E712
            Challenge.repeatable == True,  # noqa: E712
            ChallengeAttempt.user_id == user.id,
            ChallengeAttempt.status == "active",
        )
    )
    for ch, attempt in rows.all():
        await _complete_repeatable_attempt_if_ready(
            ch=ch,
            attempt=attempt,
            user=user,
            db=db,
        )


_SYSTEM_BADGE_DEFS = [
    {"id": "first_alarm",    "name": "First Alarm",          "icon": "🔔"},
    {"id": "by_the_book",    "name": "By the Book",          "icon": "📖"},
    {"id": "chart_ace",      "name": "Narrative Ace",        "icon": "✍️"},
    {"id": "smooth_handoff", "name": "Smooth Handoff",       "icon": "🤝"},
    {"id": "honor_roll",     "name": "Honor Roll",           "icon": "⭐"},
    {"id": "perfect_run",    "name": "Perfect Run",          "icon": "🏆"},
    {"id": "speed_demon",    "name": "Speed Demon",          "icon": "⚡"},
    {"id": "frequent_flyer", "name": "Frequent Flyer",       "icon": "🚑"},
    {"id": "road_warrior",   "name": "Road Warrior",         "icon": "🛣️"},
    {"id": "peds_first",     "name": "Peds First",           "icon": "🧒"},
    {"id": "peds_pro",       "name": "Peds Pro",             "icon": "👶"},
    {"id": "peds_champion",  "name": "Pediatric Champion",   "icon": "👶"},
    {"id": "lexi_rookie",        "name": "Lexi's Rookie",      "icon": "🐾"},
    {"id": "lexi_ace",           "name": "Lexi's Ace",         "icon": "🏅"},
    {"id": "orientation_complete", "name": "Station 1 Cleared", "icon": "🚒"},
]


async def _maybe_write_level_up(
    agency_id: str, user: "User", xp_before: int, xp_after: int, db: "AsyncSession"
) -> None:
    """Write a level_up feed event if the XP increase crossed a level threshold."""
    name_before, _ = _xp_to_level(xp_before)
    name_after,  icon_after = _xp_to_level(xp_after)
    if name_after != name_before:
        await _write_feed_event(agency_id, user, "level_up", name_after, icon_after, db)


def _record_ce_time(
    db: "AsyncSession",
    *,
    user_id: str,
    activity_type: str,
    seconds: int | float,
    source_id: str | None = None,
    scenario_id: str | None = None,
) -> None:
    """Append one CE time entry. No-op for zero/negative durations."""
    secs = int(seconds)
    if secs <= 0:
        return
    db.add(CeTimeLog(
        user_id=user_id,
        activity_type=activity_type,
        source_id=source_id,
        scenario_id=scenario_id,
        seconds=min(secs, _CE_SESSION_MAX_SECONDS),
    ))


async def _get_user_ce_seconds(user_id: str, db: "AsyncSession") -> int:
    """Return total accumulated CE seconds for a user."""
    result = await db.execute(
        select(func.sum(CeTimeLog.seconds)).where(CeTimeLog.user_id == user_id)
    )
    return int(result.scalar() or 0)


async def _get_challenge_ce_seconds(user_id: str, scenario_ids: list[str], db: "AsyncSession") -> int:
    """Return total CE seconds logged for a specific set of scenario IDs (challenge-scoped time)."""
    if not scenario_ids:
        return 0
    result = await db.execute(
        select(func.sum(CeTimeLog.seconds)).where(
            CeTimeLog.user_id == user_id,
            CeTimeLog.scenario_id.in_(scenario_ids),
        )
    )
    return int(result.scalar() or 0)


def _ce_round_hours(seconds: int) -> float:
    """Floor CE seconds to the nearest completed 0.25 hour for credit reporting.

    Only fully-earned quarter-hours count: 13 minutes does not count as 0.25 h;
    15 minutes does. 0.25-hour increments are the standard unit across CE
    certifying agencies.
    """
    import math
    return math.floor((seconds / 3600) * 4) / 4


async def _get_user_ce_breakdown(user_id: str, db: "AsyncSession") -> dict:
    """Return CE time grouped by activity_type plus a total.

    Returns:
        {
          "total_seconds": int,
          "by_activity": {"orientation": int, "scenario": int, "drill": int, ...}
        }
    """
    rows = await db.execute(
        select(CeTimeLog.activity_type, func.sum(CeTimeLog.seconds))
        .where(CeTimeLog.user_id == user_id)
        .group_by(CeTimeLog.activity_type)
    )
    by_activity: dict[str, int] = {}
    total = 0
    for activity_type, seconds in rows.all():
        s = int(seconds or 0)
        by_activity[activity_type] = s
        total += s
    return {"total_seconds": total, "by_activity": by_activity}


async def _check_and_award_challenges(
    user: User, agency_id: Optional[str], db: AsyncSession
) -> list[str]:
    """Check all active agency challenges and award any newly completed ones.

    Returns list of newly awarded challenge badge IDs (prefixed 'ch_').
    Safe to call repeatedly — idempotent.
    """
    if not agency_id:
        return []

    challenges_result = await db.execute(
        select(Challenge).where(
            Challenge.agency_id == agency_id,
            Challenge.is_active == True,  # noqa: E712
        )
    )
    challenges = challenges_result.scalars().all()
    if not challenges:
        return []

    # Best score per scenario_id for this user at this agency
    # Drill sessions are excluded from score-based requirements (they have no real score)
    sessions_result = await db.execute(
        select(SimSession.scenario_id, SimSession.score, SimSession.narrative_data).where(
            SimSession.user_id   == user.id,
            SimSession.agency_id == agency_id,
            SimSession.ended_at.isnot(None),
        )
    )
    best_scores: dict[str, int] = {}
    for row in sessions_result.all():
        sid, score, nd = row.scenario_id, (row.score or 0), (row.narrative_data or {})
        if nd.get("drill"):
            continue  # drill sessions don't satisfy score-based prerequisites
        best_scores[sid] = max(best_scores.get(sid, 0), score)

    # Total CE seconds — used by min_ce_minutes requirement type
    ce_seconds = await _get_user_ce_seconds(user.id, db)
    best_drill_scores = await _best_challenge_drill_scores(user=user, db=db)

    existing_badges = set(user.badges or [])
    newly_awarded: list[str] = []

    for ch in challenges:
        if ch.repeatable:
            continue  # repeatable challenges are completed through ChallengeAttempt rows
        badge_id = f"ch_{ch.id}"
        if badge_id in existing_badges:
            continue  # already earned

        requirements = _resolve_requirements(ch)
        if not requirements:
            continue

        if all(
            _check_requirement_met(req, best_scores, user=user, ce_seconds=ce_seconds, best_drill_scores=best_drill_scores)
            for req in requirements
        ):
            existing_badges.add(badge_id)
            newly_awarded.append(badge_id)
            await _write_feed_event(
                agency_id, user, "badge",
                ch.name, ch.icon or "🏅", db
            )

    if newly_awarded:
        user.badges = list(existing_badges)

    return newly_awarded


# ── Profile endpoints ─────────────────────────────────────────────────────────

@app.get("/api/me")
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Column projection — avoids loading Agency ORM objects and their selectin children
    agency_ids = [m.agency_id for m in current_user.memberships]
    agency_map: dict[str, str] = {}
    if agency_ids:
        a_result = await db.execute(
            select(Agency.id, Agency.name).where(Agency.id.in_(agency_ids))
        )
        agency_map = {row.id: row.name for row in a_result.all()}

    return {
        "username":     current_user.username,
        "first_name":   current_user.first_name or "",
        "last_name":    current_user.last_name  or "",
        "email":        current_user.email      or "",
        "is_superuser": current_user.is_superuser,
        "orientation_completed_at": (
            current_user.orientation_completed_at.isoformat()
            if current_user.orientation_completed_at else None
        ),
        "features": {
            "team_challenge_enabled": bool(getattr(settings, "team_challenge_enabled", False)),
        },
        "memberships": [
            {
                "agency_id":      m.agency_id,
                "agency_name":    agency_map.get(m.agency_id, m.agency_id),
                "role":           m.role,
                "provider_level": m.provider_level,
                "mca":            m.mca,
                "protocol_profile_id": m.protocol_profile_id,
                "protocol_profile_assignment_source": m.protocol_profile_assignment_source,
            }
            for m in current_user.memberships
        ],
    }


@app.get("/api/me/agency-equipment")
async def get_my_agency_equipment(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return the active agency's carried equipment/med inventory for UI filtering."""
    if not ctx.agency_id:
        return {"configured": False, "equipment_ids": [], "medication_ids": [], "custom_labels": []}

    result = await db.execute(select(Agency).where(Agency.id == ctx.agency_id))
    agency = result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    config = _migrate_equipment_config(agency.config or {})
    configured = _has_equipment_config(agency.config or {})
    items = (((config.get("equipment") or {}).get("items")) or [])
    if not items and agency.is_open_join and agency.agency_file:
        seed_path = Path(__file__).parent / "agencies" / f"{agency.agency_file}.json"
        if seed_path.exists():
            try:
                with open(seed_path, "r") as f:
                    seed_config = json.load(f)
                seed_config = {k: v for k, v in seed_config.items() if not k.startswith("_")}
                seed_config = _migrate_equipment_config(seed_config)
                items = (((seed_config.get("equipment") or {}).get("items")) or [])
                configured = configured or _has_equipment_config(seed_config)
            except Exception:
                log.exception("agency_equipment.open_agency_seed_fallback_failed", agency_id=agency.id)
    carried = [
        item for item in items
        if isinstance(item, dict) and item.get("carried", True) is not False
    ]
    equipment_ids: list[str] = []
    medication_ids: list[str] = []
    custom_labels: list[str] = []
    for item in carried:
        item_id = str(item.get("id") or "").strip()
        source = item.get("source") or "master"
        if source == "custom":
            label = str(item.get("label") or item_id).strip()
            if label:
                custom_labels.append(label)
            continue
        if not item_id:
            continue
        if is_medication_id(item_id):
            medication_ids.append(item_id)
        elif is_known_equipment_id(item_id):
            equipment_ids.append(item_id)

    return {
        "configured": bool(configured),
        "equipment_ids": sorted(set(equipment_ids)),
        "medication_ids": sorted(set(medication_ids)),
        "custom_labels": sorted(set(custom_labels)),
    }


@app.put("/api/me")
async def update_me(
    req: UpdateProfileRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    token: str = Depends(_extract_token),
    db: AsyncSession = Depends(get_db),
):
    if req.password is not None:
        if len(req.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        current_user.hashed_password = _hash_password(req.password)
    if req.first_name is not None:
        current_user.first_name = req.first_name.strip() or None
    if req.last_name is not None:
        current_user.last_name = req.last_name.strip() or None
    if req.email is not None:
        current_user.email = req.email.strip() or None
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    # Re-issue a token of the same type as the incoming token
    payload = _decode_token(token)
    active_agency_id = payload.get("agency_id")
    if payload.get("token_type") == "active" and active_agency_id:
        m_result = await db.execute(
            select(AgencyMember).where(
                AgencyMember.user_id   == current_user.id,
                AgencyMember.agency_id == active_agency_id,
            )
        )
        membership = m_result.scalar_one_or_none()
        a_result = await db.execute(select(Agency).where(Agency.id == active_agency_id))
        agency = a_result.scalar_one_or_none()
        if membership and agency:
            count = await _count_memberships(current_user.id, db)
            new_token = _create_active_token(current_user, membership, agency, membership_count=count)
        elif current_user.is_superuser:
            new_token = _create_superuser_token(current_user)
        else:
            new_token = _create_base_token(current_user)
    elif current_user.is_superuser:
        new_token = _create_superuser_token(current_user)
    else:
        new_token = _create_base_token(current_user)

    _set_auth_cookies(response, new_token)
    return _auth_response(new_token)


@app.get("/api/me/progress")
async def get_my_progress(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's gamification state (XP, treats, badges, session count)."""
    user = await db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    count_res = await db.execute(
        select(func.count(SimSession.id))
        .where(SimSession.user_id == ctx.user_id)
        .where(SimSession.ended_at.isnot(None))
    )
    sessions_count = count_res.scalar() or 0

    peds_progress_res = await db.execute(
        select(PedsMapProgress.map_id).where(PedsMapProgress.user_id == ctx.user_id)
    )
    peds_keys_res = await db.execute(
        select(PedsKey.key_id).where(PedsKey.user_id == ctx.user_id)
    )
    ce_seconds = await _get_user_ce_seconds(ctx.user_id, db)

    return {
        "xp":              user.xp or 0,
        "treats":          user.treats if user.treats is not None else 3,
        "badges":          user.badges or [],
        "sessions":        sessions_count,
        "pedsCount":       user.peds_count or 0,
        "pedsTraumaCount": user.peds_trauma_count or 0,
        "patRunsToday":    user.pat_runs_today or 0,
        "patXpToday":      user.pat_xp_today or 0,
        "pedsMapCompleted": [r for (r,) in peds_progress_res.all()],
        "pedsKeys":         [r for (r,) in peds_keys_res.all()],
        "ceSeconds":        ce_seconds,
    }


@app.get("/api/me/ce-summary")
async def get_my_ce_summary(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return accumulated CE time broken down by activity type.

    Designed for use by both the main web product and the SCORM deployment.
    The total_hours_ce field floors to the nearest completed 0.25 hour, which is
    the standard reporting unit across CE certifying agencies.
    """
    user = await db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    breakdown = await _get_user_ce_breakdown(ctx.user_id, db)
    total_seconds = breakdown["total_seconds"]

    return {
        "total_seconds":      total_seconds,
        "total_minutes":      round(total_seconds / 60, 1),
        "total_hours":        round(total_seconds / 3600, 2),
        "total_hours_ce":      _ce_round_hours(total_seconds),
        "by_activity": {
            activity_type: {
                "seconds": secs,
                "minutes": round(secs / 60, 1),
                "hours":   round(secs / 3600, 2),
            }
            for activity_type, secs in breakdown["by_activity"].items()
        },
        "orientation_completed":    user.orientation_completed_at is not None,
        "orientation_completed_at": (
            user.orientation_completed_at.isoformat()
            if user.orientation_completed_at else None
        ),
    }


# ── Pediatric progression: gateway and key-claim endpoints ───────────────────

# Toy Quest key definitions — toy_id checklist for each convergence key.
_PEDS_KEY_TOYS: dict[str, list[str]] = {
    "key_peds_med_golden_stethoscope": [
        "toy_peds_med_milestone_chew",
        "toy_peds_med_breathing_bear",
        "toy_peds_med_heartbeat_hound",
        "toy_peds_med_braingame_ball",
        "toy_peds_med_thermometer_rope",
        "toy_peds_med_guardian_retriever",
    ],
    "key_peds_trm_silver_shears": [
        "toy_peds_trm_patchwork_puppy",
        "toy_peds_trm_tourniquet_rope",
        "toy_peds_trm_ccollar_corgi",
        "toy_peds_trm_cooling_vest_dach",
        "toy_peds_trm_traction_stick",
        "toy_peds_trm_life_preserver",
        "toy_peds_trm_stbernard_rescue",
    ],
}
_PEDS_KEY_MAP: dict[str, str] = {
    "key_peds_med_golden_stethoscope": "pm7",
    "key_peds_trm_silver_shears":      "pt8",
}


class PedsKeyClaimRequest(BaseModel):
    key_id: str


@app.post("/api/me/peds/keys/claim")
async def peds_key_claim(
    req: PedsKeyClaimRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Award a Scout's Toy Quest convergence key if the user owns all required toys.

    Verifies the toy checklist server-side; returns the checklist state so the
    frontend can render which toys are missing if the claim is denied.
    Also writes PedsMapProgress for the corresponding convergence map (pm7/pt8)
    so PE1 unlocks automatically when both keys are claimed.
    """
    if req.key_id not in _PEDS_KEY_TOYS:
        raise HTTPException(status_code=400, detail=f"Unknown key: {req.key_id!r}")

    required_toy_names = _PEDS_KEY_TOYS[req.key_id]

    # Resolve toy DB IDs from name field — peds toys use name as their stable slug.
    toys_res = await db.execute(
        select(Toy.id, Toy.name, Toy.display_name).where(
            Toy.name.in_(required_toy_names),
            Toy.is_active == True,
        )
    )
    toys_by_name = {row.name: {"id": row.id, "display_name": row.display_name}
                   for row in toys_res.all()}

    missing_slugs = [n for n in required_toy_names if n not in toys_by_name]
    if missing_slugs:
        raise HTTPException(
            status_code=500,
            detail=f"Key {req.key_id!r} references toy slugs not found in DB: {missing_slugs}. "
                   "Seed the peds toy data before awarding this key.",
        )

    # Check ownership
    owned_res = await db.execute(
        select(UserToy.toy_id).where(
            UserToy.user_id == ctx.user_id,
            UserToy.toy_id.in_([t["id"] for t in toys_by_name.values()]),
        )
    )
    owned_ids = {r for (r,) in owned_res.all()}

    checklist = [
        {
            "toy_name":    name,
            "display_name": toys_by_name.get(name, {}).get("display_name", name),
            "owned":       toys_by_name.get(name, {}).get("id") in owned_ids,
        }
        for name in required_toy_names
    ]
    all_owned = all(item["owned"] for item in checklist)

    if not all_owned:
        return {"ok": False, "key_id": req.key_id, "checklist": checklist}

    # Award key (idempotent)
    key_existing = await db.execute(
        select(PedsKey).where(
            PedsKey.user_id == ctx.user_id,
            PedsKey.key_id  == req.key_id,
        )
    )
    already_held = key_existing.scalar_one_or_none() is not None
    if not already_held:
        db.add(PedsKey(user_id=ctx.user_id, key_id=req.key_id))

    # Write PedsMapProgress for the convergence node (pm7 or pt8).
    convergence_map = _PEDS_KEY_MAP[req.key_id]
    map_existing = await db.execute(
        select(PedsMapProgress).where(
            PedsMapProgress.user_id == ctx.user_id,
            PedsMapProgress.map_id  == convergence_map,
        )
    )
    if not map_existing.scalar_one_or_none():
        db.add(PedsMapProgress(user_id=ctx.user_id, map_id=convergence_map))

    await db.commit()
    return {"ok": True, "key_id": req.key_id, "already_held": already_held, "checklist": checklist}


# Per-run XP caps for generic mini-games. These are Station 1 drill rewards in
# the SCORM pilot, so keep them aligned with PAT/Development Sort per-run value.
_MINIGAME_PER_RUN_MAX_XP = 30
_MINIGAME_DAILY_CAP_XP = 90
_MINIGAME_LEARNING_PASSING_SCORE = 70

_ALLOWED_MINIGAME_IDS = get_allowed_minigame_ids()
validate_minigame_metadata(_ALLOWED_MINIGAME_IDS)


def _split_minigame_requirement(requirement: str) -> tuple[str, Optional[str]]:
    game_id, sep, mode = str(requirement).partition(":")
    return game_id, mode if sep and mode else None


async def _has_passing_minigame_requirement(
    user: User,
    requirement: str,
    db: AsyncSession,
) -> bool:
    game_id, mode = _split_minigame_requirement(requirement)
    metadata = get_minigame_metadata(game_id) or {}
    score_gte = int((metadata.get("pass_threshold") or {}).get("score_gte", _MINIGAME_LEARNING_PASSING_SCORE))

    if game_id == "pat":
        return int(user.pat_best_accuracy or 0) >= score_gte
    if game_id == "dev_sort":
        return int(user.dev_sort_best_accuracy or 0) >= score_gte

    filters = [
        MinigameResult.user_id == user.id,
        MinigameResult.game_id == game_id,
        MinigameResult.score >= score_gte,
    ]
    if mode:
        filters.append(MinigameResult.mode == mode)

    result = await db.execute(select(MinigameResult.id).where(*filters).limit(1))
    return result.scalar_one_or_none() is not None


def _reference_card_payload(card: MinigameReferenceCard) -> dict:
    definition = get_reference_card_definition(card.card_id) or {}
    return {
        "card_id": card.card_id,
        "title": definition.get("title", card.card_id),
        "framework_summary": definition.get("framework_summary", []),
        "common_traps": definition.get("common_traps", []),
        "field_examples": definition.get("field_examples", []),
        "related_game_ids": definition.get("related_game_ids", []),
        "unlock_condition": definition.get("unlock_condition", {}),
        "review_status": definition.get("review_status", "draft"),
        "unlocked_at": card.unlocked_at.isoformat() if card.unlocked_at else None,
    }


async def _evaluate_minigame_reference_card_unlocks(
    user: User,
    db: AsyncSession,
) -> list[dict]:
    """Unlock newly earned reference cards from static metadata and stored scores."""

    catalog = get_reference_card_catalog()
    existing_result = await db.execute(
        select(MinigameReferenceCard.card_id).where(MinigameReferenceCard.user_id == user.id)
    )
    existing_ids = set(existing_result.scalars().all())
    newly_unlocked: list[MinigameReferenceCard] = []

    for card_id, definition in catalog.items():
        if card_id in existing_ids:
            continue
        requirements = (definition.get("unlock_condition") or {}).get("all_passed") or []
        if not requirements:
            continue
        passed = True
        for requirement in requirements:
            if not await _has_passing_minigame_requirement(user, str(requirement), db):
                passed = False
                break
        if not passed:
            continue
        card = MinigameReferenceCard(user_id=user.id, card_id=card_id)
        db.add(card)
        newly_unlocked.append(card)

    if newly_unlocked:
        await db.flush()
        for card in newly_unlocked:
            await db.refresh(card)
    return [_reference_card_payload(card) for card in newly_unlocked]

_RESP_DX_SESSION_SIZE = 5  # cases selected per session (Math.min(5, pool))


def _process_resp_dx_submission(case_evidence: list[dict]) -> tuple[int, int, int, list[str]]:
    """Validate, score, and derive mistake tags for a resp_dx_1q submission.

    Validates the evidence shape against the authored cases.json — wrong item
    count, duplicate case IDs, or invalid investigation IDs all raise ValueError
    (→ HTTP 400). Returns (score_0_100, total_raw, correct_count, mistake_tags).
    """
    import json as _json
    from pathlib import Path as _Path
    cases_path = _Path("static/data/games/resp_dx/cases.json")
    try:
        cases = _json.loads(cases_path.read_text()) if cases_path.exists() else []
    except Exception:
        cases = []
    cases_by_id = {c["id"]: c for c in cases}
    valid_case_ids = set(cases_by_id)

    # Session size must match the number of cases the frontend actually sampled.
    # max(1, …) guards against an empty cases.json in dev.
    expected_n = min(_RESP_DX_SESSION_SIZE, max(1, len(cases)))
    n = len(case_evidence)
    if n != expected_n:
        raise ValueError(f"expected {expected_n} case evidence entries, got {n}")

    submitted_ids = [ev.get("case_id", "") for ev in case_evidence]
    if len(set(submitted_ids)) != n:
        raise ValueError("duplicate case IDs in evidence")
    unknown = sorted(set(submitted_ids) - valid_case_ids)
    if unknown:
        raise ValueError(f"unknown case IDs: {', '.join(unknown)}")

    for ev in case_evidence:
        case_id = ev.get("case_id", "")
        kase = cases_by_id[case_id]
        valid_inv = {i["id"] for i in kase.get("investigations", [])}
        inv_ids = ev.get("investigation_ids_used") or []
        if not inv_ids:
            raise ValueError(f"case {case_id}: no investigations used")
        bad = sorted(set(inv_ids) - valid_inv)
        if bad:
            raise ValueError(f"case {case_id}: invalid investigation IDs: {', '.join(bad)}")
        for attempt in ev.get("wrong_attempts") or []:
            aid = attempt.get("investigation_id", "")
            if aid and aid not in valid_inv:
                raise ValueError(f"case {case_id}: invalid investigation ID in wrong_attempts: {aid!r}")

    # Score — max 3 pts per case
    max_pts = n * 3
    earned = 0
    correct_count = 0
    for ev in case_evidence:
        case_id = ev.get("case_id", "")
        inv_ids = ev.get("investigation_ids_used") or []
        dx = ev.get("diagnosis_chosen") or ""
        kase = cases_by_id[case_id]
        if dx != kase.get("correct_diagnosis", ""):
            continue
        correct_count += 1
        n_inv = len(inv_ids)
        if n_inv == 1:
            first_inv = next((i for i in kase.get("investigations", []) if i["id"] == inv_ids[0]), None)
            pts = 3 if (first_inv and first_inv.get("is_high_yield")) else 2
        elif n_inv == 2:
            pts = 2
        else:
            pts = 1
        earned += pts

    score_100 = round((earned / max_pts) * 100)

    # Derive mistake tags from backend-audited wrong_attempts (order-preserving, deduplicated)
    seen_tags: dict[str, None] = {}
    for ev in case_evidence:
        case_id = ev.get("case_id", "")
        kase = cases_by_id[case_id]
        inv_lookup = {i["id"]: i for i in kase.get("investigations", [])}
        for attempt in ev.get("wrong_attempts") or []:
            inv = inv_lookup.get(attempt.get("investigation_id", ""))
            dx = attempt.get("diagnosis", "")
            if not inv:
                continue
            if inv.get("anchoring_trap") and inv.get("anchoring_trap_target") == dx:
                tag = "impression_anchoring"
            elif inv.get("is_high_yield"):
                tag = "etiology_misidentification"
            else:
                tag = "poor_investigation_choice"
            seen_tags.setdefault(tag, None)

    return score_100, max_pts, correct_count, list(seen_tags)


@app.post("/api/me/minigames/result")
@limiter.limit("60/minute")
async def submit_minigame_result(
    request: Request,
    body: MinigameResultRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Record a generic mini-game play result and award XP.

    Used by ten4_facesp, adult_child_ap_swipe, lung_sounds_matcher,
    history_maker, and peds_gcs_calculator. Each game caps XP at
    _MINIGAME_DAILY_CAP_XP per game per user per day.
    """
    if body.game_id not in _ALLOWED_MINIGAME_IDS:
        raise HTTPException(status_code=400, detail=f"Unknown game_id: {body.game_id!r}")

    # Idempotency: if run_id was provided and we've already recorded it, return the
    # original result without re-awarding XP. The unique index (uq_minigame_run) is
    # the DB-level guard; this application-level check makes the response meaningful.
    if body.run_id:
        dup_res = await db.execute(
            select(MinigameResult).where(
                MinigameResult.user_id == ctx.user_id,
                MinigameResult.game_id == body.game_id,
                MinigameResult.run_id  == body.run_id,
            )
        )
        if dup_res.scalar_one_or_none():
            return {
                "ok": True, "game_id": body.game_id,
                "score": 0, "xp_gross": 0, "xp_earned": 0,
                "xp_capped": False, "xp_today": 0, "remaining_xp": 0,
                "daily_cap_xp": _MINIGAME_DAILY_CAP_XP, "deduplicated": True,
                "newly_unlocked_reference_cards": [],
            }

    # resp_dx_1q: backend-authoritative scoring only. Missing or invalid evidence → 400.
    # All other games: accept frontend-computed score/total/correct as before.
    _derived_tags: list[str] | None = None
    if body.game_id == "resp_dx_1q":
        if not body.case_evidence:
            raise HTTPException(status_code=400, detail="resp_dx_1q requires case_evidence")
        try:
            score, total, correct, _derived_tags = _process_resp_dx_submission(body.case_evidence)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"resp_dx_1q evidence invalid: {exc}")
        total   = max(1, total)
        correct = max(0, min(total, correct))
    else:
        score     = max(0, min(100, int(body.score or 0)))
        total     = max(1, min(200, int(body.total or 1)))
        correct   = max(0, min(total, int(body.correct or 0)))
    hint_count = sanitize_minigame_hint_count(body.hint_count)
    xp_gross  = int(round((score / 100) * _MINIGAME_PER_RUN_MAX_XP))

    # Count XP earned today for this game (calendar day, UTC)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    daily_res = await db.execute(
        select(func.sum(MinigameResult.xp_earned)).where(
            MinigameResult.user_id  == ctx.user_id,
            MinigameResult.game_id  == body.game_id,
            MinigameResult.created_at >= today_start,
        )
    )
    xp_today = int(daily_res.scalar() or 0)
    remaining = max(0, _MINIGAME_DAILY_CAP_XP - xp_today)
    xp_earned = min(xp_gross, remaining)

    user = await db.get(User, ctx.user_id)
    xp_before = int(user.xp or 0) if user else 0
    if user and xp_earned > 0:
        user.xp = xp_before + xp_earned
        if ctx.agency_id:
            await _maybe_write_level_up(ctx.agency_id, user, xp_before, user.xp, db)

    result_row = MinigameResult(
        user_id      = ctx.user_id,
        game_id      = body.game_id,
        run_id       = body.run_id,
        score        = score,
        total        = total,
        correct      = correct,
        elapsed_sec  = max(0, int(body.elapsed_sec or 0)),
        xp_earned    = xp_earned,
        mistake_tags = _derived_tags if _derived_tags is not None else (body.mistake_tags or []),
        mode         = body.mode,
        hint_count   = hint_count,
        sequence_data = body.sequence_data if isinstance(body.sequence_data, dict) else None,
    )
    db.add(result_row)
    await db.flush()

    newly_unlocked_reference_cards: list[dict] = []
    if user:
        newly_unlocked_reference_cards = await _evaluate_minigame_reference_card_unlocks(user, db)

    if body.game_id == "rule_of_nines" and score >= _MINIGAME_LEARNING_PASSING_SCORE:
        existing_gateway = await db.execute(
            select(PedsMapProgress).where(
                PedsMapProgress.user_id == ctx.user_id,
                PedsMapProgress.map_id == "pt1",
            )
        )
        if not existing_gateway.scalar_one_or_none():
            db.add(PedsMapProgress(user_id=ctx.user_id, map_id="pt1"))

    _record_ce_time(db, user_id=ctx.user_id, activity_type="drill",
                    seconds=body.elapsed_sec, source_id=body.run_id,
                    scenario_id=body.game_id)
    if body.session_elapsed_sec > 0 and body.run_id:
        _record_ce_time(
            db, user_id=ctx.user_id, activity_type="drill",
            seconds=min(body.session_elapsed_sec, _CE_SESSION_MAX_SECONDS),
            source_id=f"{body.run_id}:session",
            scenario_id=body.game_id,
        )
    if user:
        await _complete_active_repeatable_challenges(
            user=user,
            agency_id=ctx.agency_id,
            db=db,
        )
    await db.commit()
    return {
        "ok":         True,
        "game_id":    body.game_id,
        "score":      score,
        "xp_gross":   xp_gross,
        "xp_earned":  xp_earned,
        "xp_capped":  xp_earned < xp_gross,
        "xp_today":   xp_today + xp_earned,
        "remaining_xp": max(0, remaining - xp_earned),
        "daily_cap_xp": _MINIGAME_DAILY_CAP_XP,
        "newly_unlocked_reference_cards": newly_unlocked_reference_cards,
    }


@app.get("/api/me/minigames/proficiency")
async def get_minigame_proficiency(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return per-game proficiency summary for the last 30 days.

    Response: { game_id: { runs_30d, avg_score_30d, last_score } }
    Used by the frontend to choose adaptive card tiers (Phase 5.2).
    """
    # MinigameResult.score is already a 0-100 integer (frontend stores Math.round(correct/total*100)).
    cutoff = datetime.utcnow() - timedelta(days=30)
    result = await db.execute(
        select(
            MinigameResult.game_id,
            func.count(MinigameResult.id).label("runs"),
            func.avg(MinigameResult.score).label("avg_score"),
        )
        .where(
            MinigameResult.user_id == ctx.user_id,
            MinigameResult.created_at >= cutoff,
        )
        .group_by(MinigameResult.game_id)
    )
    rows = result.all()

    # Last score per game (most recent run — score is already 0-100)
    last_result = await db.execute(
        select(MinigameResult.game_id, MinigameResult.score)
        .where(
            MinigameResult.user_id == ctx.user_id,
            MinigameResult.created_at >= cutoff,
        )
        .order_by(MinigameResult.created_at.desc())
    )
    last_rows = last_result.all()
    last_score_by_game: dict[str, int] = {}
    for game_id, score in last_rows:
        if game_id not in last_score_by_game:
            last_score_by_game[game_id] = score

    proficiency: dict[str, dict] = {}
    for game_id, runs, avg_score in rows:
        proficiency[game_id] = {
            "runs_30d": runs,
            "avg_score_30d": round(float(avg_score)) if avg_score is not None else None,
            "last_score": last_score_by_game.get(game_id),
        }
    return proficiency


@app.get("/api/me/minigames/recommended")
async def get_recommended_minigames(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return top 1–2 mini-game recommendations based on recent mistake tags.

    Each item: { game_id, reason_tags: [tag, ...], display_name }
    Ordered by frequency of distinct mistake tags seen (most gaps first).
    """
    gaps = await _get_recent_mistake_tags(ctx.user_id, db, days=30)
    if not gaps:
        return {"recommendations": []}

    # Sort games by number of distinct mistake tags — most gaps first
    ranked = sorted(gaps.items(), key=lambda kv: len(kv[1]), reverse=True)

    recommendations = [
        {
            "game_id": game_id,
            "reason_tags": tags,
            "display_name": get_minigame_display_name(game_id),
        }
        for game_id, tags in ranked[:2]
    ]
    return {"recommendations": recommendations}


@app.get("/api/me/minigames/phase13-readiness")
async def get_my_minigame_phase13_readiness(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return learner-scoped run evidence used to fill Phase 13 readiness notes.

    This endpoint does not unlock Phase 13 V2 implementation by itself. It keeps
    the readiness data user-scoped and deterministic so reviewers can decide
    whether the deferred V2 builds have enough evidence to proceed.
    """

    result = await db.execute(
        select(MinigameResult).where(
            MinigameResult.user_id == ctx.user_id,
            MinigameResult.game_id.in_([
                "vitals_trend_spotter",
                "peds_gcs_calculator",
                "dmist_builder",
            ]),
        )
    )
    rows = result.scalars().all()
    return summarize_phase13_readiness(rows)


@app.get("/api/me/minigames/reference-cards")
async def get_minigame_reference_cards(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return earned mini-game reference cards and locked-card summaries."""

    result = await db.execute(
        select(MinigameReferenceCard)
        .where(MinigameReferenceCard.user_id == ctx.user_id)
        .order_by(MinigameReferenceCard.unlocked_at.desc())
    )
    unlocked_cards = result.scalars().all()
    unlocked_ids = {card.card_id for card in unlocked_cards}

    locked_cards = []
    for card_id, definition in sorted(get_reference_card_catalog().items()):
        if card_id in unlocked_ids:
            continue
        locked_cards.append({
            "card_id": card_id,
            "title": definition.get("title", card_id),
            "unlock_condition": definition.get("unlock_condition", {}),
            "related_game_ids": definition.get("related_game_ids", []),
            "review_status": definition.get("review_status", "draft"),
        })

    return {
        "unlocked_card_ids": sorted(unlocked_ids),
        "cards": [_reference_card_payload(card) for card in unlocked_cards],
        "locked_cards": locked_cards,
    }


@app.get("/api/me/performance")
async def get_my_performance(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Student: return own performance summary across completed sessions."""
    return await _build_student_performance(ctx.user_id, ctx.agency_id, db)


@app.get("/api/students/{target_user_id}/performance")
async def get_student_performance(
    target_user_id: str,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: return a student's performance summary.

    Agency-scoped — instructor can only view students in their own agency unless
    they are a superuser.
    """
    # Verify the target user belongs to the instructor's agency (unless superuser)
    if not ctx.is_superuser:
        membership = await db.execute(
            select(AgencyMember).where(
                AgencyMember.user_id == target_user_id,
                AgencyMember.agency_id == ctx.agency_id,
            )
        )
        if not membership.scalar_one_or_none():
            raise HTTPException(
                status_code=403,
                detail="Target user is not a member of your agency",
            )
    return await _build_student_performance(target_user_id, ctx.agency_id, db)


async def _build_student_performance(
    user_id: str,
    agency_id: str | None,
    db: AsyncSession,
) -> dict:
    """Aggregate multi-session performance data for one student.

    Returns score trend, per-category averages, and most-missed checklist items
    across the last 50 completed scored sessions.
    """
    session_filters = [
        SimSession.user_id == user_id,
        SimSession.narrative_submitted.is_(True),
        SimSession.score.isnot(None),
    ]
    if agency_id:
        session_filters.append(SimSession.agency_id == agency_id)
    sessions_result = await db.execute(
        select(SimSession)
        .where(*session_filters)
        .order_by(SimSession.ended_at.desc())
        .limit(50)
    )
    sessions = list(sessions_result.scalars().all())

    score_trend = [
        {
            "session_id":       s.id,
            "scenario_id":      s.scenario_id,
            "score":            s.score,
            "assessment_score": s.assessment_score,
            "narrative_score":  s.narrative_score,
            "critical_failure": _session_critical_failure(s),
            "provider_level":   s.provider_level,
            "ended_at":         s.ended_at.isoformat() if s.ended_at else None,
        }
        for s in sessions
    ]

    cat_values: dict[str, list[float]] = defaultdict(list)
    cat_detail: dict[str, dict] = defaultdict(
        lambda: {"total_pct": 0.0, "count": 0, "deterministic_count": 0, "legacy_count": 0}
    )
    item_counts: dict[str, dict] = defaultdict(
        lambda: {
            "seen": 0,
            "not_satisfied": 0,
            "satisfied": 0,
            "label": None,
            "category": None,
            "missed_session_ids": [],
        }
    )
    deterministic_session_count = 0

    for s in sessions:
        # Category averages — from score_snapshot deterministic categories
        snap = s.score_snapshot or {}
        session_has_deterministic = False
        for cat, cat_data in snap.get("categories", {}).items():
            total = cat_data.get("total")
            max_score = cat_data.get("max")
            method = cat_data.get("method")
            if method == "deterministic":
                session_has_deterministic = True
            if total is not None and max_score:
                pct = float(total) / max(float(max_score), 1.0) * 100.0
                cat_values[cat].append(pct)
                cat_detail[cat]["total_pct"] += pct
                cat_detail[cat]["count"] += 1
                if method == "deterministic":
                    cat_detail[cat]["deterministic_count"] += 1
                elif method == "legacy_ai":
                    cat_detail[cat]["legacy_count"] += 1
        if session_has_deterministic:
            deterministic_session_count += 1

        # Most-missed checklist items
        states_blob = s.checklist_states or {}
        definitions = {
            d.get("id"): d
            for d in states_blob.get("checklist_definitions", [])
            if isinstance(d, dict) and d.get("id")
        }
        for item_state in states_blob.get("item_states", []):
            item_id = item_state.get("item_id")
            state = item_state.get("state")
            if not item_id or state == "not_applicable":
                continue
            definition = definitions.get(item_id) or {}
            item_counts[item_id]["seen"] += 1
            item_counts[item_id]["label"] = item_counts[item_id]["label"] or definition.get("label") or item_id
            item_counts[item_id]["category"] = item_counts[item_id]["category"] or definition.get("category")
            if state in ("not_satisfied", "contradicted"):
                item_counts[item_id]["not_satisfied"] += 1
                item_counts[item_id]["missed_session_ids"].append(s.id)
            if state == "satisfied":
                item_counts[item_id]["satisfied"] += 1

    category_averages = {
        cat: round(sum(vals) / len(vals), 1)
        for cat, vals in cat_values.items()
        if vals
    }

    category_details = {
        cat: {
            "avg_pct": round(data["total_pct"] / max(data["count"], 1), 1),
            "count": data["count"],
            "method": "deterministic" if data["deterministic_count"] >= data["legacy_count"] else "legacy_ai",
            "deterministic_count": data["deterministic_count"],
            "legacy_count": data["legacy_count"],
        }
        for cat, data in cat_detail.items()
        if data["count"]
    }

    most_missed = sorted(
        [
            {
                "item_id":       iid,
                "label":         c.get("label") or iid,
                "category":      c.get("category"),
                "miss_rate":     round(c["not_satisfied"] / max(c["seen"], 1), 2),
                "times_seen":    c["seen"],
                "times_missed":  c["not_satisfied"],
                "missed_session_ids": c.get("missed_session_ids", [])[-10:],
            }
            for iid, c in item_counts.items()
            if c["seen"] >= 2 and c["not_satisfied"] > 0
        ],
        key=lambda x: (-x["miss_rate"], -x["times_seen"]),
    )[:10]

    strengths = sorted(
        [
            {
                "item_id":         iid,
                "label":           c.get("label") or iid,
                "category":        c.get("category"),
                "satisfaction_rate": round(c["satisfied"] / max(c["seen"], 1), 2),
                "times_seen":      c["seen"],
                "times_satisfied": c["satisfied"],
            }
            for iid, c in item_counts.items()
            if c["seen"] >= 3 and c["satisfied"] >= 3 and (c["satisfied"] / max(c["seen"], 1)) >= 0.8
        ],
        key=lambda x: (-x["satisfaction_rate"], -x["times_seen"]),
    )[:5]

    return {
        "user_id":              user_id,
        "completed_sessions":   len(sessions),
        "score_trend":          score_trend,
        "category_averages":    category_averages,
        "category_details":     category_details,
        "most_missed_items":    most_missed,
        "consistent_strengths": strengths,
        "deterministic_session_count": deterministic_session_count,
    }


async def _build_drill_performance(user_id: str, db: AsyncSession) -> list[dict]:
    """Return per-game play history aggregated for one user's drill performance."""
    result = await db.execute(
        select(MinigameResult)
        .where(MinigameResult.user_id == user_id)
        .order_by(MinigameResult.created_at.asc())
        .limit(500)
    )

    grouped: dict[str, list[MinigameResult]] = defaultdict(list)
    for row in result.scalars().all():
        grouped[row.game_id].append(row)

    output = []
    for game_id, plays in grouped.items():
        scores = [int(p.score or 0) for p in plays]
        tag_counter: Counter[str] = Counter()
        for play in plays:
            tags = play.mistake_tags or []
            if isinstance(tags, list):
                tag_counter.update(str(t) for t in tags if t)
        last = plays[-1]
        output.append({
            "game_id": game_id,
            "play_count": len(plays),
            "best_score": max(scores) if scores else 0,
            "last_score": scores[-1] if scores else 0,
            "scores": scores[-10:],
            "top_mistake_tags": [tag for tag, _ in tag_counter.most_common(2)],
            "last_played_at": last.created_at.isoformat() if last.created_at else None,
        })

    return sorted(output, key=lambda r: (r.get("last_played_at") or ""), reverse=True)


@app.get("/api/me/drill-performance")
async def get_my_drill_performance(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return per-game play history aggregated for the current user's drill performance."""
    return await _build_drill_performance(ctx.user_id, db)


_PRACTICE_COACH_USAGE: dict[tuple[str, str], int] = {}
_PRACTICE_COACH_CONVERSATION_USAGE: dict[tuple[str, str, str], int] = {}


def _practice_coach_quota(user_id: str, *, consume: bool = False, conversation_id: str | None = None) -> dict:
    """In-process daily quota guard for Practice Coach MVP.

    This is intentionally backend-side so the frontend cannot bypass it. A
    durable table can replace this when Practice Coach graduates from MVP.
    """
    today = date.today().isoformat()
    cap = max(0, int(settings.practice_coach_daily_turn_cap or 0))
    session_cap = max(0, int(settings.practice_coach_session_turn_cap or 0))
    key = (user_id, today)
    used = int(_PRACTICE_COACH_USAGE.get(key, 0))
    conv_key = (user_id, today, conversation_id or "")
    session_used = int(_PRACTICE_COACH_CONVERSATION_USAGE.get(conv_key, 0)) if conversation_id else 0
    if consume and used >= cap:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Lexi's coaching limit is reached for today.",
                "daily_cap": cap,
                "used_today": used,
                "remaining_today": 0,
                "session_cap": session_cap,
                "used_this_session": session_used,
                "remaining_this_session": max(0, session_cap - session_used),
                "reset_date": today,
            },
        )
    if consume and conversation_id and session_used >= session_cap:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "This coaching conversation has reached its turn limit. Close and reopen Lexi if you want to start a fresh coaching thread.",
                "daily_cap": cap,
                "used_today": used,
                "remaining_today": max(0, cap - used),
                "session_cap": session_cap,
                "used_this_session": session_used,
                "remaining_this_session": 0,
                "reset_date": today,
            },
        )
    if consume:
        used += 1
        _PRACTICE_COACH_USAGE[key] = used
        if conversation_id:
            session_used += 1
            _PRACTICE_COACH_CONVERSATION_USAGE[conv_key] = session_used
    return {
        "daily_cap": cap,
        "used_today": used,
        "remaining_today": max(0, cap - used),
        "session_cap": session_cap,
        "used_this_session": session_used,
        "remaining_this_session": max(0, session_cap - session_used),
        "reset_date": today,
    }


def _practice_scenario_summary(session: SimSession) -> dict:
    nd = session.narrative_data or {}
    try:
        scenario = load_scenario(session.scenario_id)
        title = scenario.get("display_title") or scenario.get("title") or session.scenario_id
        protocol = scenario.get("protocol") or ""
    except Exception:
        title = session.scenario_id
        protocol = ""
    if isinstance(protocol, dict):
        protocol = protocol.get("ref") or ""
    return {
        "session_id": session.id,
        "scenario_id": session.scenario_id,
        "title": title,
        "score": session.score,
        "assessment_score": session.assessment_score,
        "ended_at": (session.ended_at or session.start_time).isoformat() if (session.ended_at or session.start_time) else None,
        "top_takeaways": list(nd.get("top_takeaways") or [])[:3],
        "next_action": nd.get("next_action") or "",
        "protocol": protocol,
    }


async def _build_practice_coach_context(
    ctx: ActiveContext,
    db: AsyncSession,
    *,
    focus_title: str | None = None,
    session_ids: list[str] | None = None,
) -> dict:
    perf = await _build_student_performance(ctx.user_id, ctx.agency_id, db)
    drill_perf = await _build_drill_performance(ctx.user_id, db)
    quota = _practice_coach_quota(ctx.user_id)
    agency_dict = await load_agency(ctx.agency_id, db) if ctx.agency_id else {}

    session_filters = [
        SimSession.user_id == ctx.user_id,
        SimSession.ended_at.isnot(None),
    ]
    if ctx.agency_id:
        session_filters.append(SimSession.agency_id == ctx.agency_id)
    recent_result = await db.execute(
        select(SimSession)
        .where(*session_filters)
        .order_by(SimSession.ended_at.desc())
        .limit(10)
    )
    recent_sessions = list(recent_result.scalars().all())

    selected_sessions: list[SimSession] = []
    clean_ids = [str(sid) for sid in (session_ids or []) if sid]
    if clean_ids:
        selected_result = await db.execute(
            select(SimSession)
            .where(
                SimSession.id.in_(clean_ids[:10]),
                SimSession.user_id == ctx.user_id,
                *( [SimSession.agency_id == ctx.agency_id] if ctx.agency_id else [] ),
            )
        )
        selected_sessions = list(selected_result.scalars().all())

    completed_ids = await _get_completed_scenario_ids(ctx.user_id, ctx.agency_id, db)
    drill_ids = await _get_unlocked_drill_ids(ctx.user_id, ctx.agency_id, db)

    def _scenario_option(sid: str) -> dict:
        try:
            sc = load_scenario(sid)
            return {
                "id": sid,
                "title": sc.get("display_title") or sc.get("title") or sid,
                "category": sc.get("category") or "",
            }
        except Exception:
            return {"id": sid, "title": sid, "category": ""}

    played_game_ids = {row.get("game_id") for row in drill_perf if row.get("game_id")}
    visible_drills = [
        {
            "game_id": game_id,
            "display_name": get_minigame_display_name(game_id),
        }
        for game_id in sorted(played_game_ids)
    ][:25]

    protocol_refs = []
    for item in [_practice_scenario_summary(s) for s in recent_sessions]:
        if item.get("protocol") and item["protocol"] not in protocol_refs:
            protocol_refs.append(item["protocol"])

    return {
        "student": {
            "provider_level": ctx.provider_level,
            "agency_id": ctx.agency_id,
            "agency_name": getattr(ctx, "agency_name", None) or agency_dict.get("name") or "",
            "mca": ctx.mca,
        },
        "focus_title": focus_title or "",
        "performance": {
            "completed_sessions": perf.get("completed_sessions"),
            "category_details": perf.get("category_details") or {},
            "focus_areas": (perf.get("most_missed_items") or [])[:5],
            "strengths": (perf.get("consistent_strengths") or [])[:5],
            "score_trend": (perf.get("score_trend") or [])[:10],
        },
        "drills": {
            "performance": drill_perf[:20],
            "played_or_visible_minigames": visible_drills,
            "unlocked_scenario_drills": [_scenario_option(sid) for sid in drill_ids[:20]],
        },
        "scenarios": {
            "completed": [_scenario_option(sid) for sid in completed_ids[:30]],
            "recent": [_practice_scenario_summary(s) for s in recent_sessions],
            "selected": [_practice_scenario_summary(s) for s in selected_sessions],
        },
        "protocols": {
            "agency_context": {
                "agency_name": agency_dict.get("name") or "",
                "service_type": agency_dict.get("service_type") or {},
            },
            "recent_protocol_refs": protocol_refs[:8],
        },
        "quota": quota,
    }


@app.get("/api/me/practice-coach/context")
async def get_practice_coach_context(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    return await _build_practice_coach_context(ctx, db)


@app.post("/api/me/practice-coach/chat")
@limiter.limit(f"{settings.rate_limit_practice_coach}/minute")
async def practice_coach_chat(
    request: Request,
    body: PracticeCoachRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")
    conversation_id = (body.conversation_id or "").strip()[:80] or None
    _practice_coach_quota(ctx.user_id, consume=True, conversation_id=conversation_id)
    context = await _build_practice_coach_context(
        ctx,
        db,
        focus_title=body.focus_title,
        session_ids=body.session_ids,
    )

    async def generate():
        try:
            async for chunk in get_practice_coach_response(message, body.history, context):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except AiProviderError as e:
            log.warning("practice_coach.provider_error", user_id=ctx.user_id, agency_id=ctx.agency_id, kind=e.kind)
            yield f"data: {json.dumps({'type': 'provider_error', 'kind': e.kind})}\n\n"
        except Exception:
            log.exception("practice_coach.chat_failed", user_id=ctx.user_id, agency_id=ctx.agency_id)
            yield f"data: {json.dumps({'text': 'I hit a snag pulling together that coaching response. Try again in a moment.'})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/me/drills/status")
async def get_drill_status(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return drill unlock/cap status for the current user."""
    user_row = (await db.execute(
        select(User.drill_xp_day, User.drill_xp_today, User.drill_runs_today)
        .where(User.id == ctx.user_id)
    )).one_or_none()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    unlocked_ids = await _get_unlocked_drill_ids(ctx.user_id, ctx.agency_id, db)
    today = _drill_day_utc()
    if user_row.drill_xp_day != today:
        xp_today, runs_today = 0, 0
    else:
        xp_today  = user_row.drill_xp_today  or 0
        runs_today = user_row.drill_runs_today or 0
    return {
        "unlocked_count": len(unlocked_ids),
        "min_required": DRILL_MIN_UNLOCKED_FOR_RANDOM,
        "random_available": len(unlocked_ids) >= DRILL_MIN_UNLOCKED_FOR_RANDOM,
        "daily_cap_xp": DRILL_DAILY_CAP_XP,
        "per_run_max_xp": DRILL_PER_RUN_MAX_XP,
        "xp_today": xp_today,
        "remaining_xp": max(0, DRILL_DAILY_CAP_XP - xp_today),
        "runs_today": runs_today,
    }


@app.post("/api/me/drills/random/start")
async def start_random_quick_drill(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Start a random quick drill from unlocked scenarios only."""
    unlocked_ids = await _get_unlocked_drill_ids(ctx.user_id, ctx.agency_id, db)
    if len(unlocked_ids) < DRILL_MIN_UNLOCKED_FOR_RANDOM:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least {DRILL_MIN_UNLOCKED_FOR_RANDOM} unlocked drills",
        )

    recent_result = await db.execute(
        select(SimSession.scenario_id, SimSession.narrative_data)
        .where(SimSession.user_id == ctx.user_id, SimSession.agency_id == ctx.agency_id, SimSession.ended_at.isnot(None))
        .order_by(SimSession.ended_at.desc())
        .limit(20)
    )
    recent_drill_ids = []
    for row in recent_result.all():
        nd = row.narrative_data or {}
        if nd.get("drill"):
            recent_drill_ids.append(row.scenario_id)
    avoid = set(recent_drill_ids[:DRILL_NO_REPEAT_WINDOW])
    pool = [sid for sid in unlocked_ids if sid not in avoid] or unlocked_ids
    scenario_id = random.choice(pool)

    session = SimSession(
        id=str(uuid.uuid4()),
        user_id=ctx.user_id,
        agency_id=ctx.agency_id,
        agency_file=ctx.agency_file,
        scenario_id=scenario_id,
        start_time=datetime.utcnow(),
        provider_level=ctx.provider_level,
        mca=ctx.mca,
        narrative_data={"drill": True, "drill_source": "random_quick"},
    )
    await _apply_protocol_snapshot(
        session,
        db,
        agency_id=ctx.agency_id,
        user_id=ctx.user_id,
        mca=ctx.mca,
        protocol_profile_id=ctx.protocol_profile_id,
    )
    db.add(session)
    await db.commit()

    user = await db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _, xp_today, runs_today, _ = _current_drill_ledger(user)
    return {
        "session_id": session.id,
        "scenario_id": scenario_id,
        "started_at": session.start_time,
        "daily_cap_xp": DRILL_DAILY_CAP_XP,
        "xp_today": xp_today,
        "remaining_xp": max(0, DRILL_DAILY_CAP_XP - xp_today),
        "runs_today": runs_today,
    }


@app.get("/api/me/random-call/status")
async def get_random_call_status(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's Random Call eligibility and daily XP status."""
    completed_ids = await _get_completed_scenario_ids(ctx.user_id, ctx.agency_id, db)
    user_row = (await db.execute(
        select(User.rc_xp_day, User.rc_xp_today).where(User.id == ctx.user_id)
    )).one_or_none()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")

    today = date.today()
    if (user_row.rc_xp_day or date.min) < today:
        rc_xp_today = 0
    else:
        rc_xp_today = user_row.rc_xp_today or 0

    return {
        "eligible":           len(completed_ids) >= RC_MIN_COMPLETED_FOR_RANDOM,
        "completed_count":    len(completed_ids),
        "min_required":       RC_MIN_COMPLETED_FOR_RANDOM,
        "daily_cap_xp":       RC_DAILY_CAP_XP,
        "xp_today":           rc_xp_today,
        "remaining_xp":       max(0, RC_DAILY_CAP_XP - rc_xp_today),
        "assessment_max_xp":  RC_ASSESSMENT_MAX_XP,
        "narrative_max_xp":   RC_NARRATIVE_MAX_XP,
    }


async def _get_rc_history(
    user_id: str,
    agency_id: str,
    scenario_ids: list[str],
    db: AsyncSession,
) -> dict[str, "StudentScenarioHistory"]:
    """Return StudentScenarioHistory rows keyed by scenario_id for the given scenarios."""
    result = await db.execute(
        select(StudentScenarioHistory).where(
            StudentScenarioHistory.user_id == user_id,
            StudentScenarioHistory.agency_id == agency_id,
            StudentScenarioHistory.scenario_id.in_(scenario_ids),
        )
    )
    return {row.scenario_id: row for row in result.scalars().all()}


async def _get_recent_mistake_tags(
    user_id: str,
    db: AsyncSession,
    days: int = 30,
) -> dict[str, list[str]]:
    """Return unique mistake tags per game_id from the last `days` days.

    Returns { game_id: [sorted unique tags] }. Empty tags lists are excluded.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        select(MinigameResult.game_id, MinigameResult.mistake_tags)
        .where(
            MinigameResult.user_id == user_id,
            MinigameResult.mistake_tags.isnot(None),
            MinigameResult.created_at >= cutoff,
        )
        .order_by(MinigameResult.created_at.desc())
    )
    rows = result.all()
    gaps: dict[str, set[str]] = {}
    for game_id, tags in rows:
        if tags and isinstance(tags, list):
            valid = {t for t in tags if isinstance(t, str)}
            if valid:
                gaps.setdefault(game_id, set()).update(valid)
    return {gid: sorted(tags) for gid, tags in gaps.items()}


async def _update_rc_history(
    user_id: str,
    agency_id: str,
    scenario_id: str,
    score_pct: int,
    db: AsyncSession,
) -> None:
    """Apply SM-2 update to StudentScenarioHistory after a Random Call completion.

    Score tiers: >=85 → easy, 70-84 → medium, <70 → hard.
    Ease factor clamped to [1.3, 3.0].
    """
    result = await db.execute(
        select(StudentScenarioHistory).where(
            StudentScenarioHistory.user_id == user_id,
            StudentScenarioHistory.agency_id == agency_id,
            StudentScenarioHistory.scenario_id == scenario_id,
        )
    )
    history = result.scalar_one_or_none()

    now = datetime.utcnow()
    if history is None:
        history = StudentScenarioHistory(
            id=str(uuid.uuid4()),
            user_id=user_id,
            agency_id=agency_id,
            scenario_id=scenario_id,
        )
        db.add(history)

    ef = history.ease_factor
    if score_pct >= 85:
        new_interval = round(history.interval_days * ef, 1)
        ef = min(3.0, ef + 0.1)
    elif score_pct >= 70:
        new_interval = round(history.interval_days * 1.8, 1)
    else:
        new_interval = 1.0
        ef = max(1.3, ef - 0.2)

    history.interval_days = new_interval
    history.ease_factor = ef
    history.last_random_call_date = now
    history.last_rc_score = score_pct
    history.updated_at = now


class RandomCallStartRequest(BaseModel):
    forced_scenario_id: Optional[str] = None


@app.post("/api/me/random-call/start")
async def start_random_call(
    req: RandomCallStartRequest = RandomCallStartRequest(),
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Start a Random Call from the user's already-completed map scenarios."""
    completed_ids = await _get_completed_scenario_ids(ctx.user_id, ctx.agency_id, db)
    if len(completed_ids) < RC_MIN_COMPLETED_FOR_RANDOM:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least {RC_MIN_COMPLETED_FOR_RANDOM} completed scenarios for Random Call",
        )

    # Anti-repeat: exclude the last RC_NO_REPEAT_WINDOW random calls
    recent_result = await db.execute(
        select(SimSession.scenario_id)
        .where(
            SimSession.user_id     == ctx.user_id,
            SimSession.agency_id   == ctx.agency_id,
            SimSession.session_type == "random_call",
            SimSession.ended_at.isnot(None),
        )
        .order_by(SimSession.ended_at.desc())
        .limit(RC_NO_REPEAT_WINDOW)
    )
    avoid = {row[0] for row in recent_result.all()}
    pool = [sid for sid in completed_ids if sid not in avoid] or completed_ids

    # Forced scenario: debrief CTA may request a specific scenario by ID.
    # Validate it is in the completed + eligible pool; fall through to weighted
    # selection if the supplied ID is not eligible (e.g. got filtered by anti-repeat).
    if req.forced_scenario_id and req.forced_scenario_id in pool:
        scenario_id = req.forced_scenario_id
    else:
        # SM-2 weighted selection: overdue → 4×, never seen → 2×, otherwise → 1×
        rc_history = await _get_rc_history(ctx.user_id, ctx.agency_id, pool, db)
        today_dt = datetime.utcnow()
        weights = []
        for sid in pool:
            h = rc_history.get(sid)
            if h is None:
                weights.append(2)
            elif h.last_random_call_date is None:
                weights.append(2)
            else:
                days_since = (today_dt - h.last_random_call_date).days
                weights.append(4 if days_since >= h.interval_days else 1)
        scenario_id = random.choices(pool, weights=weights, k=1)[0]

    user = await db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    today = date.today()
    if (user.rc_xp_day or date.min) < today:
        rc_xp_today = 0
    else:
        rc_xp_today = user.rc_xp_today or 0

    session = SimSession(
        id=str(uuid.uuid4()),
        user_id=ctx.user_id,
        agency_id=ctx.agency_id,
        agency_file=ctx.agency_file,
        scenario_id=scenario_id,
        start_time=datetime.utcnow(),
        provider_level=ctx.provider_level,
        mca=ctx.mca,
        session_type="random_call",
    )
    await _apply_protocol_snapshot(
        session,
        db,
        agency_id=ctx.agency_id,
        user_id=ctx.user_id,
        mca=ctx.mca,
        protocol_profile_id=ctx.protocol_profile_id,
    )
    db.add(session)
    await db.commit()

    return {
        "session_id":        session.id,
        "scenario_id":       scenario_id,
        "started_at":        session.start_time,
        "daily_cap_xp":      RC_DAILY_CAP_XP,
        "xp_today":          rc_xp_today,
        "remaining_xp":      max(0, RC_DAILY_CAP_XP - rc_xp_today),
        "assessment_max_xp": RC_ASSESSMENT_MAX_XP,
        "narrative_max_xp":  RC_NARRATIVE_MAX_XP,
    }


@app.get("/api/me/minigames/pat/status")
async def get_pat_status(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _, xp_today, runs_today = _current_pat_ledger(user)
    total_cards = int(user.pat_total_cards or 0)
    total_correct = int(user.pat_total_correct or 0)
    accuracy = int(round((total_correct / total_cards) * 100)) if total_cards > 0 else 0
    return {
        "daily_cap_xp": PAT_DAILY_CAP_XP,
        "per_run_max_xp": PAT_PER_RUN_MAX_XP,
        "xp_today": xp_today,
        "remaining_xp": max(0, PAT_DAILY_CAP_XP - xp_today),
        "runs_today": runs_today,
        "ever_completed": total_cards > 0,
        "total_cards": total_cards,
        "total_correct": total_correct,
        "accuracy": accuracy,
        "best_accuracy": int(user.pat_best_accuracy or 0),
    }


@app.post("/api/me/minigames/pat/submit")
@limiter.limit("60/minute")
async def submit_pat_result(
    request: Request,
    body: PatGameSubmitRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    total_cards = max(1, min(200, int(body.total_cards or 0)))
    correct = max(0, min(total_cards, int(body.correct or 0)))
    best_streak = max(0, min(total_cards, int(body.best_streak or 0)))

    accuracy = int(round((correct / total_cards) * 100))
    xp_gross = int(round((accuracy / 100) * PAT_PER_RUN_MAX_XP))
    xp_gross = max(0, min(PAT_PER_RUN_MAX_XP, xp_gross))

    xp_before = int(user.xp or 0)
    xp_today, runs_today = _ensure_pat_ledger_today(user)
    remaining = max(0, PAT_DAILY_CAP_XP - xp_today)
    xp_earned = min(xp_gross, remaining)

    user.pat_xp_today = xp_today + xp_earned
    user.pat_runs_today = runs_today + 1
    user.pat_total_cards = int(user.pat_total_cards or 0) + total_cards
    user.pat_total_correct = int(user.pat_total_correct or 0) + correct
    user.pat_best_accuracy = max(int(user.pat_best_accuracy or 0), accuracy)
    user.xp = xp_before + xp_earned
    if xp_earned > 0 and ctx.agency_id:
        await _maybe_write_level_up(ctx.agency_id, user, xp_before, user.xp, db)
    _record_ce_time(db, user_id=ctx.user_id, activity_type="drill",
                    seconds=body.elapsed_sec, scenario_id="drill_pat")
    if body.session_elapsed_sec > 0 and body.run_id:
        _record_ce_time(
            db, user_id=ctx.user_id, activity_type="drill",
            seconds=min(body.session_elapsed_sec, _CE_SESSION_MAX_SECONDS),
            source_id=f"{body.run_id}:session",
            scenario_id="pat_dash",
        )
    await _complete_active_repeatable_challenges(
        user=user,
        agency_id=ctx.agency_id,
        db=db,
    )
    await db.commit()

    return {
        "ok": True,
        "score": accuracy,
        "best_streak": best_streak,
        "xp_gross": xp_gross,
        "xp_earned": xp_earned,
        "xp_capped": xp_earned < xp_gross,
        "daily_cap_xp": PAT_DAILY_CAP_XP,
        "xp_today": int(user.pat_xp_today or 0),
        "remaining_xp": max(0, PAT_DAILY_CAP_XP - int(user.pat_xp_today or 0)),
        "runs_today": int(user.pat_runs_today or 0),
        "ever_completed": int(user.pat_total_cards or 0) > 0,
    }


@app.get("/api/me/minigames/dev-sort/status")
async def get_dev_sort_status(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _, xp_today, runs_today = _current_dev_sort_ledger(user)
    total_cards = int(user.dev_sort_total_cards or 0)
    total_correct = int(user.dev_sort_total_correct or 0)
    accuracy = int(round((total_correct / total_cards) * 100)) if total_cards > 0 else 0
    return {
        "daily_cap_xp": DEV_SORT_DAILY_CAP_XP,
        "per_run_max_xp": DEV_SORT_PER_RUN_MAX_XP,
        "xp_today": xp_today,
        "remaining_xp": max(0, DEV_SORT_DAILY_CAP_XP - xp_today),
        "runs_today": runs_today,
        "ever_completed": total_cards > 0,
        "total_cards": total_cards,
        "total_correct": total_correct,
        "accuracy": accuracy,
        "best_accuracy": int(user.dev_sort_best_accuracy or 0),
    }


@app.post("/api/me/minigames/dev-sort/submit")
@limiter.limit("60/minute")
async def submit_dev_sort_result(
    request: Request,
    body: DevSortGameSubmitRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    total_cards = max(1, min(200, int(body.total_cards or 0)))
    correct = max(0, min(total_cards, int(body.correct or 0)))

    accuracy = int(round((correct / total_cards) * 100))
    xp_gross = int(round((accuracy / 100) * DEV_SORT_PER_RUN_MAX_XP))
    xp_gross = max(0, min(DEV_SORT_PER_RUN_MAX_XP, xp_gross))

    xp_before = int(user.xp or 0)
    xp_today, runs_today = _ensure_dev_sort_ledger_today(user)
    remaining = max(0, DEV_SORT_DAILY_CAP_XP - xp_today)
    xp_earned = min(xp_gross, remaining)

    is_first_play = int(user.dev_sort_total_cards or 0) == 0
    user.dev_sort_xp_today = xp_today + xp_earned
    user.dev_sort_runs_today = runs_today + 1
    user.dev_sort_total_cards = int(user.dev_sort_total_cards or 0) + total_cards
    user.dev_sort_total_correct = int(user.dev_sort_total_correct or 0) + correct
    user.dev_sort_best_accuracy = max(int(user.dev_sort_best_accuracy or 0), accuracy)
    user.xp = xp_before + xp_earned
    if xp_earned > 0 and ctx.agency_id:
        await _maybe_write_level_up(ctx.agency_id, user, xp_before, user.xp, db)
    _record_ce_time(db, user_id=ctx.user_id, activity_type="drill",
                    seconds=body.elapsed_sec, scenario_id="drill_dev")
    if body.session_elapsed_sec > 0 and body.run_id:
        _record_ce_time(
            db, user_id=ctx.user_id, activity_type="drill",
            seconds=min(body.session_elapsed_sec, _CE_SESSION_MAX_SECONDS),
            source_id=f"{body.run_id}:session",
            scenario_id="dev_sort",
        )

    # First dev_sort play completes the PM1 gateway node.
    if is_first_play:
        existing = await db.execute(
            select(PedsMapProgress).where(
                PedsMapProgress.user_id == ctx.user_id,
                PedsMapProgress.map_id  == "pm1",
            )
        )
        if not existing.scalar_one_or_none():
            db.add(PedsMapProgress(user_id=ctx.user_id, map_id="pm1"))

    await _complete_active_repeatable_challenges(
        user=user,
        agency_id=ctx.agency_id,
        db=db,
    )
    await db.commit()

    return {
        "ok": True,
        "score": accuracy,
        "xp_gross": xp_gross,
        "xp_earned": xp_earned,
        "xp_capped": xp_earned < xp_gross,
        "daily_cap_xp": DEV_SORT_DAILY_CAP_XP,
        "xp_today": int(user.dev_sort_xp_today or 0),
        "remaining_xp": max(0, DEV_SORT_DAILY_CAP_XP - int(user.dev_sort_xp_today or 0)),
        "runs_today": int(user.dev_sort_runs_today or 0),
        "ever_completed": int(user.dev_sort_total_cards or 0) > 0,
    }


@app.get("/api/agency/leaderboard")
async def get_agency_leaderboard(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return agency leaderboard data with top 3, rising star, recent feed, and caller rank summary."""
    def _display_name(first, last, username):
        if first and last:
            return f"{first} {last[0]}."
        return first or username

    # ── Top 3 by total XP ────────────────────────────────────────────────────
    top_res = await db.execute(
        select(User.id, User.first_name, User.last_name, User.username, User.xp)
        .join(AgencyMember, AgencyMember.user_id == User.id)
        .where(AgencyMember.agency_id == ctx.agency_id)
        .where(User.is_active == True)
        .order_by(User.xp.desc())
        .limit(3)
    )
    top_rows = top_res.all()
    board = [
        {
            "rank":    rank,
            "user_id": row.id,
            "display": _display_name(row.first_name, row.last_name, row.username),
            "xp":      row.xp or 0,
            "is_me":   row.id == ctx.user_id,
        }
        for rank, row in enumerate(top_rows, start=1)
    ]

    # ── Current user's rank summary ──────────────────────────────────────────
    me_row = (await db.execute(select(User.xp).where(User.id == ctx.user_id))).one_or_none()
    my_xp = (me_row.xp or 0) if me_row else 0

    higher_xp_res = await db.execute(
        select(func.count())
        .select_from(User)
        .join(AgencyMember, AgencyMember.user_id == User.id)
        .where(AgencyMember.agency_id == ctx.agency_id)
        .where(User.is_active == True)
        .where(User.xp > my_xp)
    )
    my_rank = int((higher_xp_res.scalar() or 0) + 1)

    next_rank_res = await db.execute(
        select(User.xp)
        .join(AgencyMember, AgencyMember.user_id == User.id)
        .where(AgencyMember.agency_id == ctx.agency_id)
        .where(User.is_active == True)
        .where(User.xp > my_xp)
        .order_by(User.xp.asc(), User.id.asc())
        .limit(1)
    )
    next_rank_xp = next_rank_res.scalar_one_or_none()
    xp_to_next_rank = max(0, (next_rank_xp or my_xp) - my_xp)

    rank_summary = {
        "agency_name": ctx.agency_name or "",
        "my_xp": my_xp,
        "my_rank": my_rank,
        "next_rank_xp": next_rank_xp,
        "xp_to_next_rank": xp_to_next_rank,
    }

    # ── Rising star: most XP earned across sessions + Lexi in last 4 days ────
    cutoff = datetime.utcnow() - timedelta(days=4)

    # XP from scenario sessions
    session_xp_res = await db.execute(
        select(SimSession.user_id, func.sum(SimSession.xp_earned).label("xp_sum"))
        .join(AgencyMember, AgencyMember.user_id == SimSession.user_id)
        .where(AgencyMember.agency_id == ctx.agency_id)
        .where(SimSession.ended_at >= cutoff)
        .where(SimSession.xp_earned.isnot(None))
        .group_by(SimSession.user_id)
    )
    session_xp = {row.user_id: (row.xp_sum or 0) for row in session_xp_res}

    # XP from Lexi rounds
    lexi_xp_res = await db.execute(
        select(LexiRound.user_id, func.sum(LexiRound.xp_earned).label("xp_sum"))
        .join(AgencyMember, AgencyMember.user_id == LexiRound.user_id)
        .where(AgencyMember.agency_id == ctx.agency_id)
        .where(LexiRound.played_at >= cutoff)
        .group_by(LexiRound.user_id)
    )
    lexi_xp = {row.user_id: (row.xp_sum or 0) for row in lexi_xp_res}

    # Merge
    all_uids = set(session_xp) | set(lexi_xp)
    combined = {uid: session_xp.get(uid, 0) + lexi_xp.get(uid, 0) for uid in all_uids}

    rising_star = None
    if combined:
        best_uid = max(combined, key=lambda u: combined[u])
        best_xp  = combined[best_uid]
        if best_xp > 0:
            star_row = (await db.execute(
                select(User.first_name, User.last_name, User.username).where(User.id == best_uid)
            )).one_or_none()
            if star_row:
                rising_star = {
                    "user_id": best_uid,
                    "display": _display_name(star_row.first_name, star_row.last_name, star_row.username),
                    "xp_recent": best_xp,
                    "is_me": best_uid == ctx.user_id,
                }

    # ── Recent feed events ────────────────────────────────────────────────────
    feed_res = await db.execute(
        select(FeedEvent)
        .where(FeedEvent.agency_id == ctx.agency_id)
        .order_by(FeedEvent.created_at.desc())
        .limit(5)
    )
    feed_rows = feed_res.scalars().all()
    feed = [
        {
            "event_type":  row.event_type,
            "display":     row.display_name,
            "label":       row.event_label,
            "icon":        row.event_icon or ("🏅" if row.event_type == "badge" else "⬆️"),
            "is_me":       row.user_id == ctx.user_id,
        }
        for row in feed_rows
    ]

    return {
        "leaderboard": board,
        "rising_star": rising_star,
        "feed": feed,
        "rank_summary": rank_summary,
    }


class SpendTreatRequest(BaseModel):
    session_id: str  # active SimSession — treats_spent is incremented on this row


@app.post("/api/me/treats/spend")
async def spend_treat(
    req: SpendTreatRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Deduct one treat, increment treats_spent on the session (for Epic eligibility),
    and issue a single-use refund token.

    session_id is required — the backend uses it to authoratively track hint usage
    so Epic drop eligibility (treats_spent_in_session == 0) cannot be spoofed by
    the client.  If the session is invalid or already closed the spend is rejected,
    no treat is deducted, and no hint fires.
    """
    # Validate session ownership and open state atomically
    sess_result = await db.execute(
        select(SimSession).where(
            SimSession.id      == req.session_id,
            SimSession.user_id == ctx.user_id,
            SimSession.ended_at.is_(None),
        ).with_for_update()
    )
    session = sess_result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=400,
            detail="Session not found, already closed, or does not belong to you.",
        )

    user_result = await db.execute(
        select(User).where(User.id == ctx.user_id).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    current = user.treats if user.treats is not None else 0
    if current < 1:
        raise HTTPException(status_code=400, detail="No treats available")

    token = str(uuid.uuid4())
    tokens = list(user.treat_tokens or [])
    tokens.append(token)
    user.treats       = current - 1
    user.treat_tokens = tokens
    session.treats_spent = (session.treats_spent or 0) + 1

    await db.commit()
    return {"ok": True, "treats": user.treats, "token": token}


class TreatRefundRequest(BaseModel):
    token: str


@app.post("/api/me/treats/refund")
async def refund_treat(
    req: TreatRefundRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Refund one treat by consuming a spend token (exactly-once).

    If the token is invalid or already used, the request is silently ignored
    so clients don't need to handle errors on the refund path.
    """
    result = await db.execute(
        select(User).where(User.id == ctx.user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    tokens = list(user.treat_tokens or [])
    if req.token not in tokens:
        # Token already used or invalid — silently no-op
        return {"ok": True, "treats": user.treats if user.treats is not None else 0}
    tokens.remove(req.token)
    user.treat_tokens = tokens
    user.treats = (user.treats if user.treats is not None else 0) + 1
    await db.commit()
    return {"ok": True, "treats": user.treats}


# ── Orientation completion endpoint ──────────────────────────────────────────

_ORIENTATION_XP     = 50
_ORIENTATION_TREATS = 3
_ORIENTATION_BADGE  = "orientation_complete"
_CE_ORIENTATION_SECONDS = 600       # 10 minutes awarded for completing orientation
_CE_SESSION_MAX_SECONDS = 14400     # hard ceiling on any single CeTimeLog entry

# Per-phase CE caps — credit is bounded by expected average active completion
# time, not wall-clock (prevents farming by leaving debrief/feedback tabs open).
# Named for the learning activity, not a certifying agency.
CE_FEEDBACK_REVIEW_CAP_SECONDS     = 120   # 2 min: drill/minigame feedback review
CE_SCENARIO_DEBRIEF_CAP_SECONDS    = 480   # 8 min: scenario FTO debrief + case summary
CE_ORIENTATION_DEBRIEF_CAP_SECONDS = 300   # 5 min: orientation coaching debrief
_ORIENTATION_STATIC_FEEDBACK = (
    "You've completed your orientation at Station 1. You know the controls, "
    "you've run your first assessment, and you've submitted your first report. "
    "You're ready for the field."
)


async def _orientation_complete_internal(user: User) -> dict:
    """Apply the NULL→timestamp orientation completion transition on *user*.

    Mutates the user object in place; caller is responsible for committing the
    session.  Returns a dict describing what was awarded (or that it was already
    complete).  Does NOT commit — allows the caller to batch with other writes.
    """
    if user.orientation_completed_at is not None:
        return {"already_complete": True, "xp_earned": 0, "treats_earned": 0, "badge": None}

    user.orientation_completed_at = datetime.utcnow()
    user.xp      = (user.xp      or 0) + _ORIENTATION_XP
    user.treats  = (user.treats  or 0) + _ORIENTATION_TREATS
    badges = set(user.badges or [])
    badges.add(_ORIENTATION_BADGE)
    user.badges = list(badges)

    return {
        "already_complete": False,
        "xp_earned":    _ORIENTATION_XP,
        "treats_earned": _ORIENTATION_TREATS,
        "badge":         _ORIENTATION_BADGE,
    }


def _is_orientation_session(session: SimSession, scenario: dict) -> bool:
    """Treat the canonical orientation scenario id as authoritative."""
    return session.scenario_id == "orientation_01" or bool(scenario.get("is_orientation"))


async def _complete_orientation_session(
    session: SimSession,
    scenario: dict,
    db: AsyncSession,
    user_id: str,
    *,
    narrative_data: dict,
    narrative_attempted: bool,
) -> dict:
    """Persist and return the static orientation debrief without using AI."""
    if not session.narrative_submitted:
        session.narrative_submitted = True
        session.narrative_attempted = narrative_attempted
        session.narrative_data = {**narrative_data, "is_orientation": True}
        session.feedback = _ORIENTATION_STATIC_FEEDBACK
        session.score = None
        session.ended_at = datetime.utcnow()

        await db.commit()

    return {
        "feedback": _ORIENTATION_STATIC_FEEDBACK,
        "score": None,
        "subscores": None,
        "is_orientation": True,
        "cta_label": "Start your shift",
        "teaching_points": [],
        "timeline": None,
        "rubric_detail": None,
        "exemplar_dmist": None,
        "exemplar_narrative": scenario.get("exemplar_narrative"),
        "critical_failure": None,
        "top_takeaways": [],
        "reflection_prompts": [],
        "next_action": "",
        "next_action_target_type": "none",
        "next_action_target_id": None,
        "cpr_challenge_summary": None,
        "impression_challenge": None,
        "dmist_primary_impression": session.dmist_primary_impression,
    }


class OrientationCompleteRequest(BaseModel):
    session_id: str


@app.post("/api/me/orientation/complete")
async def complete_orientation(
    req: OrientationCompleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark orientation complete for the current user.

    Validates that the supplied session belongs to this user and that its
    scenario_id is 'orientation_01'. Awards XP/treats/badge on the
    NULL→timestamp transition only. Idempotent — calling again when already
    set returns 200 with no side effects.
    """
    sess_result = await db.execute(
        select(SimSession).where(
            SimSession.id == req.session_id,
            SimSession.user_id == current_user.id,
        )
    )
    session = sess_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.scenario_id != "orientation_01":
        raise HTTPException(status_code=400, detail="Session is not an orientation session")

    result = await _orientation_complete_internal(current_user)
    if not result.get("already_complete"):
        _record_ce_time(
            db,
            user_id=current_user.id,
            activity_type="orientation",
            seconds=_CE_ORIENTATION_SECONDS,
            source_id=req.session_id,
        )
    await db.commit()
    return {"ok": True, **result}


# ── Lexi's Challenge endpoints ────────────────────────────────────────────────

LEXI_DAILY_CAP = 3   # rounds per day that earn XP
LEXI_GROUP_QUESTION_SECONDS = 30
LEXI_GROUP_FEEDBACK_SECONDS = 30
LEXI_GROUP_RESULTS_READY_SECONDS = 30
LEXI_GROUP_ROUNDS = 3
LEXI_GROUP_QUESTIONS_PER_ROUND = 5
LEXI_GROUP_TREAT_DAILY_CAP = 1
LEXI_GROUP_LOBBY_TTL_MINUTES = 60
LEXI_GROUP_ACTIVE_STALE_HOURS = 12
LEXI_GROUP_BADGE_PARTICIPANT = "lexi_group_participant"
LEXI_GROUP_BADGE_WINNER = "lexi_group_winner"
LEXI_GROUP_BADGE_SWEEP = "lexi_group_sweep"
_LEXI_LEVEL_ORDER = ["MFR", "EMT", "AEMT", "Paramedic"]
_LEXI_GROUP_WS: dict[str, dict[WebSocket, str]] = {}
_lexi_group_phase_task: Optional[asyncio.Task] = None
_ttl_scrub_task: Optional[asyncio.Task] = None
_LEXI_RECENT_KEYS_MAX = 60
_LEXI_RECENT_QUESTION_KEYS: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=_LEXI_RECENT_KEYS_MAX))
_LEXI_MISSED_KEYS_MAX = 120
_LEXI_RECENT_MISSED_KEYS: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=_LEXI_MISSED_KEYS_MAX))
AGENCY_GROUP_TYPES = {"station", "shift", "crew", "custom"}
CHALLENGE_TEAM_TYPES = {"lexi_group"}
CHALLENGE_TEAM_MIN_MEMBERS = 2
CHALLENGE_TEAM_MAX_MEMBERS = 5
TEAM_INVITE_MIN_TIMEOUT_SEC = 20
TEAM_INVITE_MAX_TIMEOUT_SEC = 120
TEAM_HEARTBEAT_STALE_SEC = 60
TEAM_MATCH_FORMING_TTL_MINUTES = 10
TEAM_MATCH_READY_TTL_MINUTES = 20


def _lexi_question_key(q: dict) -> str:
    question = str((q or {}).get("question", "")).strip().lower()
    options = " | ".join(str(o).strip().lower() for o in ((q or {}).get("options") or []))
    return f"{question} || {options}"


def _recent_lexi_keys_for_users(user_ids: list[str]) -> set[str]:
    merged: set[str] = set()
    for uid in user_ids:
        if not uid:
            continue
        merged.update(_LEXI_RECENT_QUESTION_KEYS.get(uid, []))
    return merged


def _remember_lexi_questions_for_users(user_ids: list[str], questions: list[dict]) -> None:
    keys = [_lexi_question_key(q) for q in (questions or []) if q]
    for uid in user_ids:
        if not uid:
            continue
        dq = _LEXI_RECENT_QUESTION_KEYS[uid]
        for k in keys:
            dq.append(k)


def _remember_missed_lexi_keys_for_user(user_id: str, missed_keys: list[str]) -> None:
    if not user_id:
        return
    dq = _LEXI_RECENT_MISSED_KEYS[user_id]
    for k in missed_keys:
        if k:
            dq.append(str(k))


def _overlap_recent_missed_keys(user_ids: list[str], min_count: int = 2) -> set[str]:
    counts: dict[str, int] = {}
    for uid in user_ids:
        if not uid:
            continue
        for k in set(_LEXI_RECENT_MISSED_KEYS.get(uid, [])):
            counts[k] = counts.get(k, 0) + 1
    return {k for k, c in counts.items() if c >= max(1, min_count)}


def _display_name_from_user(user: User) -> str:
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name[0]}."
    return user.first_name or user.username


def _lowest_provider_level(levels: list[str]) -> str:
    if not levels:
        return "EMT"
    valid = [lvl for lvl in levels if lvl in _LEXI_LEVEL_ORDER]
    if not valid:
        return "EMT"
    return min(valid, key=lambda lvl: _LEXI_LEVEL_ORDER.index(lvl))


def _lexi_now() -> datetime:
    return datetime.utcnow()


def _group_treat_day_utc() -> date:
    return datetime.utcnow().date()


def _ensure_group_treat_ledger_today(user: User) -> int:
    """Normalize stale group-treat ledger fields in-place and return today's count."""
    today = _group_treat_day_utc()
    if user.lexi_group_treat_day != today:
        user.lexi_group_treat_day = today
        user.lexi_group_treats_today = 0
        return 0
    return int(user.lexi_group_treats_today or 0)


async def _award_group_badge(
    user: User,
    badge_id: str,
    badge_label: str,
    badge_icon: str,
    agency_id: Optional[str],
    db: AsyncSession,
) -> bool:
    existing = set(user.badges or [])
    if badge_id in existing:
        return False
    existing.add(badge_id)
    user.badges = list(existing)
    await _write_feed_event(agency_id, user, "badge", badge_label, badge_icon, db)
    return True


def _serialize_question_for_phase(q: dict, phase: str) -> dict:
    data = {
        "question": q.get("question", ""),
        "options": q.get("options", []),
    }
    if phase in ("feedback", "round_results", "final_results"):
        data["correct"] = q.get("correct")
        data["explanation"] = q.get("explanation", "")
    return data


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    return f"{dt.isoformat()}Z"


def _compute_round_stats(round_payload: dict, participant_ids: list[str]) -> dict[str, dict]:
    stats = {uid: {"score": 0, "time_ms": 0} for uid in participant_ids}
    answers = round_payload.get("answers", {}) or {}
    for q_answers in answers.values():
        for uid, ans in (q_answers or {}).items():
            if uid not in stats:
                continue
            if ans.get("correct"):
                stats[uid]["score"] += 1
            stats[uid]["time_ms"] += int(ans.get("response_ms") or 30000)
    return stats


def _count_user_answers_in_round(round_payload: dict, user_id: str) -> int:
    total = 0
    answers = round_payload.get("answers", {}) or {}
    for q_answers in answers.values():
        if user_id in (q_answers or {}):
            total += 1
    return total


def _rank_rows(rows: list[dict]) -> list[dict]:
    ranked = sorted(rows, key=lambda r: (-int(r.get("score", 0)), int(r.get("time_ms", 0)), r.get("display", "")))
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
    return ranked


def _build_group_public_state(session: LexiGroupSession, viewer_user_id: Optional[str] = None) -> dict:
    participants = list(session.participants or [])
    rounds = list(session.rounds or [])
    participant_ids = [p.get("user_id") for p in participants if p.get("user_id")]
    phase = session.phase or "lobby"
    round_idx = max(1, int(session.round_index or 1))
    q_idx = max(0, int(session.current_question_index or 0))

    round_payload = rounds[round_idx - 1] if 0 <= round_idx - 1 < len(rounds) else {}
    questions = round_payload.get("questions", []) or []
    question = questions[q_idx] if 0 <= q_idx < len(questions) else None
    q_answers = ((round_payload.get("answers") or {}).get(str(q_idx), {}) if question else {})
    q_ready = ((round_payload.get("feedback_ready") or {}).get(str(q_idx), {}) if question else {})

    # Cumulative standings across completed rounds (including current round if in results/final)
    cumulative = {uid: {"score": 0, "time_ms": 0} for uid in participant_ids}
    for i in range(min(round_idx, len(rounds))):
        include = i < (round_idx - 1) or phase in ("round_results", "final_results")
        if not include:
            continue
        stats = _compute_round_stats(rounds[i], participant_ids)
        for uid in participant_ids:
            cumulative[uid]["score"] += stats[uid]["score"]
            cumulative[uid]["time_ms"] += stats[uid]["time_ms"]

    standings_rows = []
    for p in participants:
        uid = p.get("user_id")
        if not uid:
            continue
        standings_rows.append({
            "user_id": uid,
            "display": p.get("display") or uid,
            "score": cumulative[uid]["score"],
            "time_ms": cumulative[uid]["time_ms"],
            "round_wins": int(p.get("round_wins") or 0),
            "is_me": uid == viewer_user_id,
        })
    standings = _rank_rows(standings_rows)

    payload = {
        "session_id": session.id,
        "host_user_id": session.host_user_id,
        "room_code": session.room_code,
        "agency_id": session.agency_id,
        "status": session.status,
        "phase": phase,
        "round_index": round_idx,
        "max_rounds": int(session.max_rounds or LEXI_GROUP_ROUNDS),
        "current_question_index": q_idx,
        "phase_started_at": _iso_utc(session.phase_started_at),
        "phase_ends_at": _iso_utc(session.phase_ends_at),
        "phase_started_epoch_ms": (int(session.phase_started_at.timestamp() * 1000) if session.phase_started_at else None),
        "phase_ends_epoch_ms": (int(session.phase_ends_at.timestamp() * 1000) if session.phase_ends_at else None),
        "effective_provider_level": session.effective_provider_level,
        "mca": session.mca,
        "participants": participants,
        "standings": standings,
        "top3": standings[:3],
        "answer_count": len(q_answers or {}),
        "feedback_ready_count": len(q_ready or {}),
        "answered_user_ids": sorted(list((q_answers or {}).keys())),
        "feedback_ready_user_ids": sorted(list((q_ready or {}).keys())),
        # Monotonic state marker for clients to discard out-of-order updates.
        "state_version_ms": int((session.updated_at or _lexi_now()).timestamp() * 1000),
    }

    if question:
        payload["question"] = _serialize_question_for_phase(question, phase)
        if viewer_user_id:
            my_ans = (q_answers or {}).get(viewer_user_id)
            payload["my_answer_submitted"] = bool(my_ans)
            payload["my_answer_correct"] = (my_ans.get("correct") if isinstance(my_ans, dict) else None)
            payload["my_feedback_ready"] = bool((q_ready or {}).get(viewer_user_id))
            # Current-round score so far (question phase or feedback phase)
            cur_score = 0
            answers_all = round_payload.get("answers", {}) or {}
            for qa in answers_all.values():
                ans = (qa or {}).get(viewer_user_id)
                if isinstance(ans, dict) and ans.get("correct"):
                    cur_score += 1
            payload["my_round_score"] = cur_score
    if phase in ("feedback", "round_results", "final_results") and question:
        payload["question_answer_summary"] = {
            "correct": int(question.get("correct", -1)),
            "answered_count": len(q_answers or {}),
        }
    if phase in ("round_results", "final_results"):
        round_stats = _compute_round_stats(round_payload, participant_ids)
        round_rows = _rank_rows([
            {
                "user_id": p.get("user_id"),
                "display": p.get("display") or p.get("user_id"),
                "score": round_stats[p.get("user_id")]["score"],
                "time_ms": round_stats[p.get("user_id")]["time_ms"],
                "is_me": p.get("user_id") == viewer_user_id,
            }
            for p in participants if p.get("user_id") in round_stats
        ])
        payload["round_results"] = round_rows
        payload["round_winner_user_id"] = round_payload.get("winner_user_id")
        next_ready = round_payload.get("next_round_ready", {}) or {}
        payload["next_round_ready_count"] = len(next_ready)
        payload["next_round_ready_user_ids"] = sorted(list(next_ready.keys()))
    if viewer_user_id:
        round_awards = (round_payload.get("awards") or {}) if isinstance(round_payload, dict) else {}
        my_award = (round_awards.get(viewer_user_id) or {}) if isinstance(round_awards, dict) else {}
        payload["my_round_xp_base"] = int(my_award.get("xp_earned") or 0)
        payload["my_round_xp_bonus"] = int(my_award.get("xp_bonus") or 0)
        payload["my_round_xp_capped"] = bool(my_award.get("xp_capped") or False)
    if viewer_user_id:
        my_xp_total = 0
        my_xp_round = 0
        for idx, r in enumerate(rounds):
            awards = (r or {}).get("awards", {}) or {}
            mine = awards.get(viewer_user_id) or {}
            gained = int(mine.get("xp_earned") or 0)
            my_xp_total += gained
            if idx == (round_idx - 1):
                my_xp_round = gained
        payload["my_xp_earned_total"] = my_xp_total
        payload["my_xp_earned_round"] = my_xp_round
    if phase == "final_results":
        bonus = (rounds[-1].get("final_bonus") if rounds else {}) or {}
        payload["bonus"] = bonus
        max_rounds = int(session.max_rounds or LEXI_GROUP_ROUNDS)
        completed_rounds = rounds[:max_rounds]
        participant_count = len(participant_ids)
        total_questions = len(completed_rounds) * LEXI_GROUP_QUESTIONS_PER_ROUND
        total_possible_answers = participant_count * total_questions
        total_answered = sum(int((r or {}).get("answer_count") or 0) for r in completed_rounds)
        total_correct = sum(int((row or {}).get("score") or 0) for row in standings)
        avg_points_per_responder_per_round = (
            round(total_correct / (participant_count * len(completed_rounds)), 2)
            if participant_count > 0 and len(completed_rounds) > 0 else 0.0
        )
        payload["facilitator_summary"] = {
            "rounds_completed": len(completed_rounds),
            "participants": participant_count,
            "questions_per_round": LEXI_GROUP_QUESTIONS_PER_ROUND,
            "total_answered": total_answered,
            "total_possible_answers": total_possible_answers,
            "completion_rate_pct": round((total_answered / total_possible_answers) * 100) if total_possible_answers else 0,
            "team_accuracy_pct": round((total_correct / total_possible_answers) * 100) if total_possible_answers else 0,
            "avg_points_per_responder_per_round": avg_points_per_responder_per_round,
            "rounds_with_no_answers": sum(1 for r in completed_rounds if int((r or {}).get("answer_count") or 0) == 0),
        }
        if viewer_user_id:
            capped_entries = bonus.get("treat_capped", []) if isinstance(bonus, dict) else []
            earned_entries = bonus.get("treat_earned", []) if isinstance(bonus, dict) else []
            payload["my_treat_capped_reasons"] = sorted([
                str((e or {}).get("reason"))
                for e in capped_entries
                if (e or {}).get("user_id") == viewer_user_id and (e or {}).get("reason")
            ])
            payload["my_treat_earned_reasons"] = sorted([
                str((e or {}).get("reason"))
                for e in earned_entries
                if (e or {}).get("user_id") == viewer_user_id and (e or {}).get("reason")
            ])

    return payload


async def _broadcast_lexi_group_state(session: LexiGroupSession) -> None:
    sockets = _LEXI_GROUP_WS.get(session.id)
    if not sockets:
        return
    participant_ids = {
        (p or {}).get("user_id")
        for p in (session.participants or [])
        if (p or {}).get("user_id")
    }
    stale = []
    for ws, uid in list(sockets.items()):
        if uid not in participant_ids:
            try:
                await ws.send_json({"type": "kicked", "message": "You were removed from this group challenge by the host."})
            except Exception:
                pass
            try:
                await ws.close(code=4003, reason="Removed from group")
            except Exception:
                pass
            stale.append(ws)
            continue
        try:
            await ws.send_json({"type": "state", "state": _build_group_public_state(session, uid)})
        except Exception:
            stale.append(ws)
    for ws in stale:
        sockets.pop(ws, None)
    if not sockets:
        _LEXI_GROUP_WS.pop(session.id, None)


@app.get("/api/me/lexi-status")
async def get_lexi_status(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return today's round count, all-time stats, and perfect-round count."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_res = await db.execute(
        select(func.count(LexiRound.id), func.coalesce(func.sum(LexiRound.xp_earned), 0))
        .where(LexiRound.user_id == ctx.user_id, LexiRound.played_at >= today_start)
    )
    rounds_today, xp_today = today_res.one()
    total_res = await db.execute(
        select(func.count(LexiRound.id), func.coalesce(func.max(LexiRound.score), 0))
        .where(LexiRound.user_id == ctx.user_id)
    )
    total_rounds, best_score = total_res.one()
    perfect_res = await db.execute(
        select(func.count(LexiRound.id))
        .where(LexiRound.user_id == ctx.user_id, LexiRound.score == 5)
    )
    perfect_rounds = perfect_res.scalar() or 0
    return {
        "rounds_today":   int(rounds_today),
        "xp_today":       int(xp_today),
        "total_rounds":   int(total_rounds),
        "perfect_rounds": int(perfect_rounds),
        "best_score":     int(best_score),
        "daily_cap":      LEXI_DAILY_CAP,
    }


async def _award_lexi_round(
    user_id: str,
    score: int,
    provider_level: str,
    mca: str,
    db: AsyncSession,
    agency_id: Optional[str] = None,
) -> dict:
    """Award one Lexi round using normal daily-cap rules and badge logic."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_result = await db.execute(
        select(func.count(LexiRound.id)).where(
            LexiRound.user_id == user_id,
            LexiRound.played_at >= today_start,
        )
    )
    rounds_today = today_result.scalar() or 0

    xp_earned = 0
    if rounds_today < LEXI_DAILY_CAP:
        base_xp = score * 2
        xp_earned = base_xp * 2 if score == 5 else base_xp

    round_rec = LexiRound(
        user_id=user_id,
        score=score,
        xp_earned=xp_earned,
        provider_level=provider_level,
        mca=mca,
    )
    db.add(round_rec)

    user_result = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    xp_before = user.xp or 0
    user.xp = xp_before + xp_earned

    await db.flush()
    all_result = await db.execute(select(LexiRound).where(LexiRound.user_id == user_id))
    all_rounds = all_result.scalars().all()
    total_rounds = len(all_rounds)
    perfect_rounds = sum(1 for r in all_rounds if r.score == 5)

    existing_badges = set(user.badges or [])
    new_badges: list[str] = []
    if "lexi_rookie" not in existing_badges and total_rounds >= 1:
        existing_badges.add("lexi_rookie")
        new_badges.append("lexi_rookie")
        await _write_feed_event(agency_id, user, "badge", "Lexi's Rookie", "🐾", db)
    if "lexi_ace" not in existing_badges and perfect_rounds >= 3:
        existing_badges.add("lexi_ace")
        new_badges.append("lexi_ace")
        await _write_feed_event(agency_id, user, "badge", "Lexi's Ace", "🏅", db)
    if new_badges:
        user.badges = list(existing_badges)
    if xp_earned > 0:
        await _maybe_write_level_up(agency_id, user, xp_before, user.xp, db)

    return {
        "xp_earned": xp_earned,
        "xp_capped": rounds_today >= LEXI_DAILY_CAP,
        "rounds_today": rounds_today + 1,
        "total_rounds": total_rounds,
        "perfect_rounds": perfect_rounds,
        "new_badges": new_badges,
    }


def _ensure_group_participant(session: LexiGroupSession, user_id: str, display: str, provider_level: str) -> bool:
    participants = list(session.participants or [])
    for p in participants:
        if p.get("user_id") == user_id:
            return False
    participants.append({
        "user_id": user_id,
        "display": display,
        "provider_level": provider_level,
        "round_wins": 0,
    })
    session.participants = participants
    flag_modified(session, "participants")
    return True


async def _advance_lexi_group_session_locked(session: LexiGroupSession, db: AsyncSession) -> bool:
    """Advance group phase if timers/all-answers require it. Returns True if state changed."""
    if session.status not in ("active", "finished"):
        return False
    if session.phase not in ("question", "feedback", "round_results"):
        return False

    now = _lexi_now()
    rounds = list(session.rounds or [])
    if not rounds:
        return False
    round_idx = max(1, int(session.round_index or 1))
    if round_idx > len(rounds):
        return False
    round_payload = rounds[round_idx - 1]
    participants = list(session.participants or [])
    participant_ids = [p.get("user_id") for p in participants if p.get("user_id")]
    q_idx = max(0, int(session.current_question_index or 0))
    answers = round_payload.get("answers", {}) or {}
    q_answers = answers.get(str(q_idx), {}) or {}

    if session.phase == "question":
        expired = bool(session.phase_ends_at and now >= session.phase_ends_at)
        all_answered = len(q_answers) >= len(participant_ids) and len(participant_ids) > 0
        if not (expired or all_answered):
            return False
        session.phase = "feedback"
        feedback_ready = round_payload.get("feedback_ready", {}) or {}
        feedback_ready[str(q_idx)] = {}
        round_payload["feedback_ready"] = feedback_ready
        rounds[round_idx - 1] = round_payload
        session.rounds = rounds
        flag_modified(session, "rounds")
        session.phase_started_at = now
        session.phase_ends_at = now + timedelta(seconds=LEXI_GROUP_FEEDBACK_SECONDS)
        session.updated_at = now
        return True

    # feedback phase
    if session.phase == "feedback":
        feedback_ready = round_payload.get("feedback_ready", {}) or {}
        q_ready = feedback_ready.get(str(q_idx), {}) or {}
        all_ready = len(q_ready) >= len(participant_ids) and len(participant_ids) > 0
        if (session.phase_ends_at and now < session.phase_ends_at) and not all_ready:
            return False

        # Move to next question or round results
        if q_idx + 1 < LEXI_GROUP_QUESTIONS_PER_ROUND:
            session.current_question_index = q_idx + 1
            session.phase = "question"
            session.phase_started_at = now
            session.phase_ends_at = now + timedelta(seconds=LEXI_GROUP_QUESTION_SECONDS)
            session.updated_at = now
            return True

        # End of round -> compute winner + normal Lexi XP awards (once)
        if not round_payload.get("awarded"):
            answers_obj = round_payload.get("answers", {}) or {}
            questions_obj = round_payload.get("questions", []) or []
            total_answers = sum(len(v or {}) for v in answers_obj.values())
            round_stats = _compute_round_stats(round_payload, participant_ids)
            # Team-mode context (if this group session came from a team match).
            rep_to_member_ids: dict[str, list[str]] = {}
            team_mode_active = False
            tm_res = await db.execute(
                select(TeamMatch).where(TeamMatch.started_session_id == session.id).limit(1)
            )
            tm = tm_res.scalar_one_or_none()
            if tm:
                part_res = await db.execute(
                    select(TeamMatchParticipant).where(
                        TeamMatchParticipant.match_id == tm.id,
                        TeamMatchParticipant.status == "accepted",
                    )
                )
                tm_parts = part_res.scalars().all()
                tm_team_ids = [p.team_id for p in tm_parts if p.team_id]
                if tm_team_ids:
                    teams_res = await db.execute(select(ChallengeTeam).where(ChallengeTeam.id.in_(tm_team_ids)))
                    teams = teams_res.scalars().all()
                    team_by_id = {t.id: t for t in teams}
                    team_member_res = await db.execute(
                        select(ChallengeTeamMember).where(
                            ChallengeTeamMember.team_id.in_(tm_team_ids),
                            ChallengeTeamMember.is_active == True,  # noqa: E712
                        )
                    )
                    team_members = team_member_res.scalars().all()
                    members_by_team: dict[str, list[str]] = defaultdict(list)
                    for m in team_members:
                        members_by_team[m.team_id].append(m.user_id)
                    for t in teams:
                        rep_uid = t.representative_user_id
                        if not rep_uid:
                            continue
                        rep_to_member_ids[rep_uid] = list(dict.fromkeys(members_by_team.get(t.id, [])))
                    team_mode_active = True
            round_rows = _rank_rows([
                {
                    "user_id": uid,
                    "display": next((p.get("display") for p in participants if p.get("user_id") == uid), uid),
                    "score": round_stats[uid]["score"],
                    "time_ms": round_stats[uid]["time_ms"],
                }
                for uid in participant_ids
            ])
            top_score = int(round_rows[0]["score"]) if round_rows else 0
            winner_uid = round_rows[0]["user_id"] if round_rows and top_score > 0 else None
            round_payload["winner_user_id"] = winner_uid
            round_payload["winner_score"] = top_score
            round_payload["answer_count"] = total_answers
            round_payload["next_round_ready"] = {}
            round_payload["winner_bonus_xp"] = 10 if winner_uid else 0
            for p in participants:
                if p.get("user_id") == winner_uid:
                    p["round_wins"] = int(p.get("round_wins") or 0) + 1
            # Round winner bonus: +10 XP per round winner (outside normal Lexi daily cap).
            if winner_uid:
                winner_user_result = await db.execute(select(User).where(User.id == winner_uid).with_for_update())
                winner_user = winner_user_result.scalar_one_or_none()
                if winner_user:
                    xp_before = winner_user.xp or 0
                    winner_user.xp = xp_before + 10
                    await _maybe_write_level_up(session.agency_id, winner_user, xp_before, winner_user.xp, db)
                    # Winner badge is tied to earning 1st-place winner XP in group mode.
                    await _award_group_badge(
                        user=winner_user,
                        badge_id=LEXI_GROUP_BADGE_WINNER,
                        badge_label="Group Challenge Winner",
                        badge_icon="🥇",
                        agency_id=session.agency_id,
                        db=db,
                    )
                    # Team mode: mirror winner bonus to active non-representative teammates.
                    if team_mode_active:
                        for teammate_uid in rep_to_member_ids.get(winner_uid, []):
                            if teammate_uid == winner_uid:
                                continue
                            teammate_res = await db.execute(select(User).where(User.id == teammate_uid).with_for_update())
                            teammate = teammate_res.scalar_one_or_none()
                            if not teammate:
                                continue
                            teammate_xp_before = teammate.xp or 0
                            teammate.xp = teammate_xp_before + 10
                            await _maybe_write_level_up(session.agency_id, teammate, teammate_xp_before, teammate.xp, db)
            # Capture misses from this completed round for future remediation.
            # Miss = incorrect answer OR unanswered question.
            for uid in participant_ids:
                missed_keys: list[str] = []
                for qi in range(min(len(questions_obj), LEXI_GROUP_QUESTIONS_PER_ROUND)):
                    q = questions_obj[qi]
                    q_key = _lexi_question_key(q)
                    q_answers_map = (answers_obj.get(str(qi), {}) or {})
                    ans = q_answers_map.get(uid)
                    if not isinstance(ans, dict):
                        missed_keys.append(q_key)
                        continue
                    if not bool(ans.get("correct")):
                        missed_keys.append(q_key)
                if missed_keys:
                    _remember_missed_lexi_keys_for_user(uid, missed_keys)
            round_awards = {}
            if total_answers > 0:
                for uid in participant_ids:
                    user_answer_count = _count_user_answers_in_round(round_payload, uid)
                    if user_answer_count <= 0:
                        round_awards[uid] = {"xp_earned": 0, "xp_bonus": 0, "xp_capped": False, "new_badges": []}
                        continue
                    score = round_stats[uid]["score"]
                    award = await _award_lexi_round(
                        user_id=uid,
                        score=score,
                        provider_level=session.effective_provider_level or "EMT",
                        mca=session.mca or settings.default_mca,
                        agency_id=session.agency_id,
                        db=db,
                    )
                    round_awards[uid] = {
                        "xp_earned": award["xp_earned"],
                        "xp_bonus": 10 if uid == winner_uid else 0,
                        "xp_capped": bool(award.get("xp_capped", False)),
                        "new_badges": award["new_badges"],
                    }
                    # Team mode: mirror base round XP to active non-representative teammates.
                    if team_mode_active:
                        teammate_ids = [muid for muid in rep_to_member_ids.get(uid, []) if muid and muid != uid]
                        for teammate_uid in teammate_ids:
                            teammate_award = await _award_lexi_round(
                                user_id=teammate_uid,
                                score=score,
                                provider_level=session.effective_provider_level or "EMT",
                                mca=session.mca or settings.default_mca,
                                agency_id=session.agency_id,
                                db=db,
                            )
                            # Not shown in standings (teammates are not direct participants),
                            # but persisted so teammates can receive the same XP progression.
                            round_awards[teammate_uid] = {
                                "xp_earned": teammate_award["xp_earned"],
                                "xp_bonus": 10 if uid == winner_uid else 0,
                                "xp_capped": bool(teammate_award.get("xp_capped", False)),
                                "new_badges": teammate_award["new_badges"],
                            }
            else:
                for uid in participant_ids:
                    round_awards[uid] = {"xp_earned": 0, "xp_bonus": 0, "xp_capped": False, "new_badges": []}
            round_payload["awarded"] = True
            round_payload["awards"] = round_awards
            rounds[round_idx - 1] = round_payload
            session.rounds = rounds
            flag_modified(session, "rounds")
            session.participants = participants
            flag_modified(session, "participants")

        if round_idx >= int(session.max_rounds or LEXI_GROUP_ROUNDS):
            # Finalize group bonus once.
            final_round = rounds[-1]
            if not final_round.get("final_bonus_applied"):
                cumulative = {uid: {"score": 0, "time_ms": 0} for uid in participant_ids}
                for r in rounds[:int(session.max_rounds or LEXI_GROUP_ROUNDS)]:
                    stats = _compute_round_stats(r, participant_ids)
                    for uid in participant_ids:
                        cumulative[uid]["score"] += stats[uid]["score"]
                        cumulative[uid]["time_ms"] += stats[uid]["time_ms"]
                standings = _rank_rows([
                    {
                        "user_id": uid,
                        "display": next((p.get("display") for p in participants if p.get("user_id") == uid), uid),
                        "score": cumulative[uid]["score"],
                        "time_ms": cumulative[uid]["time_ms"],
                    }
                    for uid in participant_ids
                ])
                total_answers_all_rounds = sum(int((r or {}).get("answer_count") or 0) for r in rounds[:int(session.max_rounds or LEXI_GROUP_ROUNDS)])
                winner_uid = standings[0]["user_id"] if standings and total_answers_all_rounds > 0 else None
                bonus = {
                    "xp_bonus_winner_user_id": None,  # Round winner bonuses are applied per round.
                    "xp_bonus": 0,
                    "treat_winner_user_id": None,  # legacy single-winner field (kept for compatibility)
                    "treat_earned_user_ids": [],
                    "treat_capped_user_ids": [],
                    "treat_earned": [],
                    "treat_capped": [],
                    "treat_award_capped": False,
                }
                if winner_uid:
                    winner_user_result = await db.execute(select(User).where(User.id == winner_uid).with_for_update())
                    winner_user = winner_user_result.scalar_one_or_none()
                    if winner_user:
                        await _award_group_badge(
                            user=winner_user,
                            badge_id=LEXI_GROUP_BADGE_WINNER,
                            badge_label="Group Challenge Winner",
                            badge_icon="🥇",
                            agency_id=session.agency_id,
                            db=db,
                        )
                # Challenge treats:
                # 1) Same winner for all 3 rounds with positive round scores.
                # 2) Any participant with 3 perfect rounds.
                max_rounds = int(session.max_rounds or LEXI_GROUP_ROUNDS)
                perfect_round_score = int(LEXI_GROUP_QUESTIONS_PER_ROUND)
                treat_earned_user_ids: list[str] = []
                treat_capped_user_ids: list[str] = []
                treat_reason_by_uid: dict[str, set[str]] = {}

                round_winners = [r.get("winner_user_id") for r in rounds[:max_rounds]]
                round_top_scores = [int((r or {}).get("winner_score") or 0) for r in rounds[:max_rounds]]
                if (
                    round_winners
                    and all(w == round_winners[0] and w is not None for w in round_winners)
                    and all(s > 0 for s in round_top_scores)
                ):
                    sweep_uid = round_winners[0]
                    treat_reason_by_uid.setdefault(sweep_uid, set()).add("won_all_3_rounds")
                    sweep_user_result = await db.execute(select(User).where(User.id == sweep_uid).with_for_update())
                    sweep_user = sweep_user_result.scalar_one_or_none()
                    if sweep_user:
                        await _award_group_badge(
                            user=sweep_user,
                            badge_id=LEXI_GROUP_BADGE_SWEEP,
                            badge_label="Group 3-Round Streak",
                            badge_icon="🔥",
                            agency_id=session.agency_id,
                            db=db,
                        )

                for uid in participant_ids:
                    is_perfect_all_rounds = True
                    for r in rounds[:max_rounds]:
                        stats = _compute_round_stats(r, participant_ids)
                        if int((stats.get(uid) or {}).get("score") or 0) < perfect_round_score:
                            is_perfect_all_rounds = False
                            break
                    if not is_perfect_all_rounds:
                        continue
                    treat_reason_by_uid.setdefault(uid, set()).add("three_perfect_rounds")

                for uid in sorted(treat_reason_by_uid.keys()):
                    user_result = await db.execute(select(User).where(User.id == uid).with_for_update())
                    treat_user = user_result.scalar_one_or_none()
                    if not treat_user:
                        continue
                    treats_today = _ensure_group_treat_ledger_today(treat_user)
                    if treats_today < LEXI_GROUP_TREAT_DAILY_CAP:
                        treat_user.treats = (treat_user.treats or 0) + 1
                        treat_user.lexi_group_treats_today = treats_today + 1
                        treat_earned_user_ids.append(uid)
                        for reason in sorted(treat_reason_by_uid.get(uid) or []):
                            bonus["treat_earned"].append({"user_id": uid, "reason": reason})
                    else:
                        treat_capped_user_ids.append(uid)
                        for reason in sorted(treat_reason_by_uid.get(uid) or []):
                            bonus["treat_capped"].append({"user_id": uid, "reason": reason})
                bonus["treat_earned_user_ids"] = treat_earned_user_ids
                bonus["treat_capped_user_ids"] = treat_capped_user_ids
                bonus["treat_winner_user_id"] = treat_earned_user_ids[0] if treat_earned_user_ids else None
                bonus["treat_award_capped"] = len(treat_capped_user_ids) > 0
                final_round["final_bonus"] = bonus
                final_round["final_bonus_applied"] = True
                rounds[-1] = final_round
                session.rounds = rounds
                flag_modified(session, "rounds")

            session.phase = "final_results"
            session.status = "finished"
            session.phase_started_at = now
            session.phase_ends_at = None
            session.ended_at = now
            session.updated_at = now
            return True

        session.phase = "round_results"
        session.phase_started_at = now
        session.phase_ends_at = None
        session.updated_at = now
        return True

    # round_results phase
    next_ready = round_payload.get("next_round_ready", {}) or {}
    ready_ids = set(next_ready.keys())
    all_ready = len(ready_ids) >= len(participant_ids) and len(participant_ids) > 0
    expired = bool(session.phase_ends_at and now >= session.phase_ends_at)
    if not (all_ready or expired):
        return False
    if expired and not all_ready:
        # Kick participants who didn't acknowledge in time.
        session.participants = [p for p in participants if p.get("user_id") in ready_ids]
        flag_modified(session, "participants")
    session.round_index = int(session.round_index or 1) + 1
    session.current_question_index = 0
    session.phase = "question"
    session.phase_started_at = now
    session.phase_ends_at = now + timedelta(seconds=LEXI_GROUP_QUESTION_SECONDS)
    session.updated_at = now
    return True


async def _remove_user_from_other_lexi_groups(
    db: AsyncSession,
    agency_id: str,
    user_id: str,
    exclude_session_id: Optional[str] = None,
) -> list[LexiGroupSession]:
    """Ensure a user participates in at most one active/lobby group per agency.

    Returns sessions that changed and should be rebroadcast after commit.
    """
    result = await db.execute(
        select(LexiGroupSession).where(
            LexiGroupSession.agency_id == agency_id,
            LexiGroupSession.status.in_(["lobby", "active"]),
        ).with_for_update()
    )
    sessions = result.scalars().all()
    changed: list[LexiGroupSession] = []
    now = _lexi_now()

    for session in sessions:
        if exclude_session_id and session.id == exclude_session_id:
            continue
        participants = list(session.participants or [])
        if not any((p or {}).get("user_id") == user_id for p in participants):
            continue

        participants = [p for p in participants if (p or {}).get("user_id") != user_id]
        session.participants = participants
        flag_modified(session, "participants")

        rounds = list(session.rounds or [])
        round_idx = max(1, int(session.round_index or 1))
        q_idx = max(0, int(session.current_question_index or 0))
        if 0 <= round_idx - 1 < len(rounds):
            round_payload = rounds[round_idx - 1]
            if session.phase == "feedback":
                feedback_ready = round_payload.get("feedback_ready", {}) or {}
                q_ready = feedback_ready.get(str(q_idx), {}) or {}
                q_ready.pop(user_id, None)
                feedback_ready[str(q_idx)] = q_ready
                round_payload["feedback_ready"] = feedback_ready
            if session.phase == "round_results":
                next_ready = round_payload.get("next_round_ready", {}) or {}
                next_ready.pop(user_id, None)
                round_payload["next_round_ready"] = next_ready
            rounds[round_idx - 1] = round_payload
            session.rounds = rounds
            flag_modified(session, "rounds")

        if session.host_user_id == user_id:
            session.host_user_id = participants[0].get("user_id") if participants else session.host_user_id

        if not participants:
            session.status = "finished"
            session.phase = "final_results"
            session.phase_started_at = now
            session.phase_ends_at = None
            session.ended_at = now
        elif session.status == "active":
            await _advance_lexi_group_session_locked(session, db)
        session.updated_at = now
        changed.append(session)

    return changed


async def _lexi_group_phase_worker():
    """Background task that advances timed group phases and cleans stale team state."""
    while True:
        try:
            async with async_session_factory() as db:
                now = _lexi_now()
                # Team challenge maintenance:
                # 1) expire pending invites
                await db.execute(
                    TeamInvite.__table__.update()
                    .where(
                        TeamInvite.status == "pending",
                        TeamInvite.expires_at <= now,
                    )
                    .values(status="expired", responded_at=now)
                )

                # 2) cancel stale forming matches and their pending invites
                stale_forming_cutoff = now - timedelta(minutes=TEAM_MATCH_FORMING_TTL_MINUTES)
                stale_match_res = await db.execute(
                    select(TeamMatch).where(
                        TeamMatch.status == "forming",
                        TeamMatch.created_at <= stale_forming_cutoff,
                    ).with_for_update(skip_locked=True)
                )
                stale_matches = stale_match_res.scalars().all()
                for tm in stale_matches:
                    meta = dict(tm.metadata_json or {})
                    meta["cancel_reason"] = "stale_forming_timeout"
                    meta["cancel_at"] = _now_iso()
                    tm.metadata_json = meta
                    tm.status = "canceled"
                    tm.ended_at = now
                    await db.execute(
                        TeamInvite.__table__.update()
                        .where(
                            TeamInvite.match_id == tm.id,
                            TeamInvite.status == "pending",
                        )
                        .values(status="expired", responded_at=now)
                    )

                # 3) cancel stale ready matches that were never started
                stale_ready_cutoff = now - timedelta(minutes=TEAM_MATCH_READY_TTL_MINUTES)
                stale_ready_res = await db.execute(
                    select(TeamMatch).where(
                        TeamMatch.status == "ready",
                        (
                            ((TeamMatch.ready_at.isnot(None)) & (TeamMatch.ready_at <= stale_ready_cutoff))
                            |
                            ((TeamMatch.ready_at.is_(None)) & (TeamMatch.created_at <= stale_ready_cutoff))
                        ),
                    ).with_for_update(skip_locked=True)
                )
                stale_ready_matches = stale_ready_res.scalars().all()
                for tm in stale_ready_matches:
                    meta = dict(tm.metadata_json or {})
                    meta["cancel_reason"] = "stale_ready_timeout"
                    meta["cancel_at"] = _now_iso()
                    tm.metadata_json = meta
                    tm.status = "canceled"
                    tm.ended_at = now
                    await db.execute(
                        TeamInvite.__table__.update()
                        .where(
                            TeamInvite.match_id == tm.id,
                            TeamInvite.status == "pending",
                        )
                        .values(status="expired", responded_at=now)
                    )

                # Cleanup stale lobby and abandoned active sessions to prevent unbounded growth.
                stale_lobby_cutoff = now - timedelta(minutes=LEXI_GROUP_LOBBY_TTL_MINUTES)
                stale_active_cutoff = now - timedelta(hours=LEXI_GROUP_ACTIVE_STALE_HOURS)

                stale_lobbies_result = await db.execute(
                    select(LexiGroupSession).where(
                        LexiGroupSession.status == "lobby",
                        LexiGroupSession.created_at <= stale_lobby_cutoff,
                    ).with_for_update(skip_locked=True)
                )
                for s in stale_lobbies_result.scalars().all():
                    s.status = "finished"
                    s.phase = "final_results"
                    s.phase_started_at = now
                    s.phase_ends_at = None
                    s.ended_at = now
                    s.updated_at = now

                stale_active_result = await db.execute(
                    select(LexiGroupSession).where(
                        LexiGroupSession.status == "active",
                        LexiGroupSession.updated_at <= stale_active_cutoff,
                    ).with_for_update(skip_locked=True)
                )
                for s in stale_active_result.scalars().all():
                    s.status = "finished"
                    s.phase = "final_results"
                    s.phase_started_at = now
                    s.phase_ends_at = None
                    s.ended_at = now
                    s.updated_at = now

                result = await db.execute(
                    select(LexiGroupSession).where(
                        LexiGroupSession.status == "active",
                        LexiGroupSession.phase.in_(["question", "feedback", "round_results"]),
                        LexiGroupSession.phase_ends_at.isnot(None),
                        LexiGroupSession.phase_ends_at <= now,
                    )
                )
                sessions = result.scalars().all()
                for s in sessions:
                    lock_res = await db.execute(
                        select(LexiGroupSession).where(LexiGroupSession.id == s.id).with_for_update()
                    )
                    locked = lock_res.scalar_one_or_none()
                    if not locked:
                        continue
                    changed = await _advance_lexi_group_session_locked(locked, db)
                    if changed:
                        await db.commit()
                        await _broadcast_lexi_group_state(locked)
                await db.commit()
            await asyncio.sleep(1)
        except Exception:
            await asyncio.sleep(1)


_TTL_CHAT_DAYS = 30   # delete ChatMessage rows older than this
_TTL_SCRUB_INTERVAL_SECONDS = 86_400  # run once per day

async def _ttl_scrub_worker():
    """Daily background task that purges raw transcript data from completed sessions
    older than _TTL_CHAT_DAYS.  Retains scored metadata and generated debriefs.
    Deletes ChatMessage rows; nulls dmist_report; strips narrative_data['narrative'].
    This implements the 30-day retention policy documented in the HLD (§6 Security)."""
    while True:
        try:
            cutoff = datetime.utcnow() - timedelta(days=_TTL_CHAT_DAYS)
            async with async_session_factory() as db:
                # Fetch IDs of sessions ended before the cutoff with any raw data remaining
                expired_res = await db.execute(
                    select(SimSession.id).where(
                        SimSession.ended_at != None,  # noqa: E711
                        SimSession.ended_at < cutoff,
                    )
                )
                expired_ids = [row[0] for row in expired_res.all()]
                if expired_ids:
                    # Bulk-delete chat messages for expired sessions
                    await db.execute(
                        ChatMessage.__table__.delete().where(
                            ChatMessage.session_id.in_(expired_ids)
                        )
                    )
                    # Bulk-delete session findings (transitional ingestion rows contain
                    # free-text clinical detail — subject to same TTL as chat transcripts)
                    await db.execute(
                        SessionFinding.__table__.delete().where(
                            SessionFinding.session_id.in_(expired_ids)
                        )
                    )
                    # Null dmist_report for expired sessions
                    await db.execute(
                        SimSession.__table__.update()
                        .where(SimSession.id.in_(expired_ids))
                        .values(dmist_report=None)
                    )
                    await db.commit()
                    # Strip narrative text in-place (keep other narrative_data keys for scoring)
                    narrative_res = await db.execute(
                        select(SimSession).where(
                            SimSession.id.in_(expired_ids),
                            SimSession.narrative_data != None,  # noqa: E711
                        )
                    )
                    for session in narrative_res.scalars().all():
                        if session.narrative_data and "narrative" in session.narrative_data:
                            updated = dict(session.narrative_data)
                            del updated["narrative"]
                            session.narrative_data = updated
                            flag_modified(session, "narrative_data")
                    await db.commit()
                    log.info("ttl_scrub.complete", scrubbed=len(expired_ids))
                # Purge expired WebSocket tickets
                await db.execute(
                    WsTicket.__table__.delete().where(
                        WsTicket.expires_at < datetime.utcnow()
                    )
                )
                # Purge expired refresh tokens
                await db.execute(
                    RefreshToken.__table__.delete().where(
                        RefreshToken.expires_at < datetime.utcnow()
                    )
                )
                await db.commit()
        except Exception:
            log.exception("ttl_scrub.error")
        await asyncio.sleep(_TTL_SCRUB_INTERVAL_SECONDS)


@app.post("/api/me/lexi-questions")
@limiter.limit(f"{settings.rate_limit_lexi}/minute")
async def get_lexi_questions(
    request: Request,
    req: LexiQuestionsRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate a fresh set of 5 quiz questions via AI."""
    exclude = _recent_lexi_keys_for_users([current_user.id])
    prefer = set(_LEXI_RECENT_MISSED_KEYS.get(current_user.id, []))
    questions = await generate_lexi_questions(
        req.provider_level,
        req.mca,
        exclude_keys=exclude,
        prefer_keys=prefer,
        prefer_n=2,
    )
    _remember_lexi_questions_for_users([current_user.id], questions)
    return {"questions": questions}


@app.post("/api/me/lexi-challenge")
async def submit_lexi_round(
    req: LexiRoundRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a completed Lexi round, award XP (up to daily cap), and check badges."""
    if not (0 <= req.score <= 5):
        raise HTTPException(status_code=400, detail="score must be 0–5")

    lexi_agency_id = current_user.memberships[0].agency_id if current_user.memberships else None
    award = await _award_lexi_round(
        user_id=current_user.id,
        score=req.score,
        provider_level=req.provider_level or "EMT",
        mca=req.mca or settings.default_mca,
        db=db,
        agency_id=lexi_agency_id,
    )
    # Update per-user missed-question memory for spaced remediation.
    raw_q = [str(k).strip() for k in (req.question_keys or []) if str(k).strip()]
    raw_missed = [str(k).strip() for k in (req.missed_question_keys or []) if str(k).strip()]
    q_keys = raw_q[:5]
    q_set = set(q_keys)
    missed = [k for k in raw_missed[:5] if (not q_set) or (k in q_set)]
    if missed:
        _remember_missed_lexi_keys_for_user(current_user.id, missed)
    await db.commit()
    return award


async def _make_unique_group_room_code(db: AsyncSession) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(20):
        code = "".join(random.choice(alphabet) for _ in range(6))
        existing = await db.execute(
            select(LexiGroupSession.id).where(
                LexiGroupSession.room_code == code,
                LexiGroupSession.status.in_(["lobby", "active"]),
            )
        )
        if not existing.first():
            return code
    raise HTTPException(status_code=500, detail="Could not allocate room code")


async def _make_unique_challenge_team_code(db: AsyncSession) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(25):
        code = "".join(random.choice(alphabet) for _ in range(6))
        existing = await db.execute(
            select(ChallengeTeam.id).where(
                ChallengeTeam.join_code == code,
                ChallengeTeam.status.in_(["forming", "locked"]),
            )
        )
        if not existing.first():
            return code
    raise HTTPException(status_code=500, detail="Could not allocate team code")


def _normalize_group_type(raw: str) -> str:
    normalized = (raw or "custom").strip().lower()
    if normalized not in AGENCY_GROUP_TYPES:
        raise HTTPException(status_code=400, detail="Invalid group_type")
    return normalized


def _normalize_challenge_team_type(raw: str) -> str:
    normalized = (raw or "lexi_group").strip().lower()
    if normalized not in CHALLENGE_TEAM_TYPES:
        raise HTTPException(status_code=400, detail="Invalid challenge_type")
    return normalized


def _safe_name(raw: str, field_name: str = "name", min_len: int = 2, max_len: int = 40) -> str:
    value = (raw or "").strip()
    if len(value) < min_len or len(value) > max_len:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be between {min_len} and {max_len} characters",
        )
    return value


def _ensure_team_challenge_enabled() -> None:
    if not bool(getattr(settings, "team_challenge_enabled", False)):
        raise HTTPException(status_code=404, detail="Team challenge mode is disabled")


def _now_iso() -> str:
    return _lexi_now().isoformat(timespec="seconds") + "Z"


async def _get_active_team_member(db: AsyncSession, team_id: str, user_id: str) -> Optional[ChallengeTeamMember]:
    res = await db.execute(
        select(ChallengeTeamMember).where(
            ChallengeTeamMember.team_id == team_id,
            ChallengeTeamMember.user_id == user_id,
            ChallengeTeamMember.is_active == True,  # noqa: E712
        )
    )
    return res.scalar_one_or_none()


async def _expire_pending_invites_for_match(db: AsyncSession, match_id: str, now: Optional[datetime] = None) -> int:
    ts = now or _lexi_now()
    upd = await db.execute(
        TeamInvite.__table__.update()
        .where(
            TeamInvite.match_id == match_id,
            TeamInvite.status == "pending",
            TeamInvite.expires_at < ts,
        )
        .values(status="expired", responded_at=ts)
    )
    return int(upd.rowcount or 0)


async def _team_is_in_open_match(
    db: AsyncSession,
    team_id: str,
    exclude_match_id: Optional[str] = None,
) -> bool:
    q = (
        select(TeamMatchParticipant.id)
        .join(TeamMatch, TeamMatch.id == TeamMatchParticipant.match_id)
        .where(
            TeamMatchParticipant.team_id == team_id,
            TeamMatchParticipant.status == "accepted",
            TeamMatch.status.in_(["forming", "ready", "active"]),
        )
    )
    if exclude_match_id:
        q = q.where(TeamMatch.id != exclude_match_id)
    res = await db.execute(q.limit(1))
    return bool(res.first())


@app.get("/api/me/groups")
async def list_agency_groups(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")
    result = await db.execute(
        select(AgencyGroup)
        .where(
            AgencyGroup.agency_id == ctx.agency_id,
            AgencyGroup.is_active == True,  # noqa: E712
        )
        .order_by(AgencyGroup.is_system.desc(), AgencyGroup.name.asc())
    )
    groups = result.scalars().all()
    if not groups:
        return {"groups": []}

    group_ids = [g.id for g in groups]
    mem_result = await db.execute(
        select(AgencyGroupMember).where(AgencyGroupMember.group_id.in_(group_ids))
    )
    members = mem_result.scalars().all()
    members_by_group: dict[str, list[AgencyGroupMember]] = defaultdict(list)
    for m in members:
        members_by_group[m.group_id].append(m)

    out = []
    for g in groups:
        rows = members_by_group.get(g.id, [])
        is_member = any(m.user_id == ctx.user_id for m in rows)
        out.append({
            "id": g.id,
            "name": g.name,
            "group_type": g.group_type,
            "is_system": bool(g.is_system),
            "created_by": g.created_by,
            "member_count": len(rows),
            "is_member": is_member,
            "can_manage": bool(ctx.is_superuser or ctx.role in ("admin", "instructor") or g.created_by == ctx.user_id),
            "created_at": g.created_at.isoformat() if g.created_at else None,
        })
    return {"groups": out}


@app.post("/api/me/groups", status_code=201)
@limiter.limit(f"{settings.rate_limit_lexi}/minute")
async def create_agency_group(
    request: Request,
    req: AgencyGroupCreateRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")
    name = _safe_name(req.name, field_name="Group name")
    group_type = _normalize_group_type(req.group_type)
    is_system = bool(req.is_system)
    if is_system and not (ctx.is_superuser or ctx.role in ("admin", "instructor")):
        raise HTTPException(status_code=403, detail="Instructor or admin access required for agency groups")

    existing = await db.execute(
        select(AgencyGroup).where(
            AgencyGroup.agency_id == ctx.agency_id,
            func.lower(AgencyGroup.name) == name.lower(),
            AgencyGroup.is_active == True,  # noqa: E712
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A group with this name already exists")

    group = AgencyGroup(
        id=str(uuid.uuid4()),
        agency_id=ctx.agency_id,
        name=name,
        group_type=group_type,
        created_by=ctx.user_id,
        is_system=is_system,
        is_active=True,
    )
    db.add(group)
    db.add(AgencyGroupMember(group_id=group.id, user_id=ctx.user_id, role="creator"))
    await db.commit()
    return {
        "group": {
            "id": group.id,
            "name": group.name,
            "group_type": group.group_type,
            "is_system": bool(group.is_system),
            "member_count": 1,
            "is_member": True,
            "can_manage": True,
        }
    }


@app.post("/api/me/groups/{group_id}/join")
@limiter.limit(f"{settings.rate_limit_lexi}/minute")
async def join_agency_group(
    request: Request,
    group_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")

    group_res = await db.execute(
        select(AgencyGroup).where(AgencyGroup.id == group_id).with_for_update()
    )
    group = group_res.scalar_one_or_none()
    if not group or group.agency_id != ctx.agency_id or not group.is_active:
        raise HTTPException(status_code=404, detail="Group not found")

    existing = await db.execute(
        select(AgencyGroupMember).where(
            AgencyGroupMember.group_id == group.id,
            AgencyGroupMember.user_id == ctx.user_id,
        )
    )
    member = existing.scalar_one_or_none()
    if not member:
        db.add(AgencyGroupMember(group_id=group.id, user_id=ctx.user_id, role="member"))
        await db.commit()

    count_res = await db.execute(
        select(func.count(AgencyGroupMember.id)).where(AgencyGroupMember.group_id == group.id)
    )
    return {"ok": True, "group_id": group.id, "member_count": int(count_res.scalar() or 0)}


@app.post("/api/me/groups/{group_id}/leave")
@limiter.limit(f"{settings.rate_limit_lexi}/minute")
async def leave_agency_group(
    request: Request,
    group_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")
    group_res = await db.execute(
        select(AgencyGroup).where(AgencyGroup.id == group_id).with_for_update()
    )
    group = group_res.scalar_one_or_none()
    if not group or group.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Group not found")

    member_res = await db.execute(
        select(AgencyGroupMember).where(
            AgencyGroupMember.group_id == group.id,
            AgencyGroupMember.user_id == ctx.user_id,
        ).with_for_update()
    )
    member = member_res.scalar_one_or_none()
    if member:
        await db.delete(member)
        await db.flush()

    count_res = await db.execute(
        select(func.count(AgencyGroupMember.id)).where(AgencyGroupMember.group_id == group.id)
    )
    remaining = int(count_res.scalar() or 0)
    if remaining == 0 and not group.is_system:
        group.is_active = False
    await db.commit()
    return {"ok": True, "group_id": group.id, "member_count": remaining}


@app.get("/api/me/challenge-teams")
async def list_challenge_teams(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")
    result = await db.execute(
        select(ChallengeTeam)
        .where(
            ChallengeTeam.agency_id == ctx.agency_id,
            ChallengeTeam.status.in_(["forming", "locked"]),
        )
        .order_by(ChallengeTeam.created_at.desc())
        .limit(50)
    )
    teams = result.scalars().all()
    if not teams:
        return {"teams": []}

    team_ids = [t.id for t in teams]
    mem_result = await db.execute(
        select(ChallengeTeamMember).where(
            ChallengeTeamMember.team_id.in_(team_ids),
            ChallengeTeamMember.is_active == True,  # noqa: E712
        )
    )
    members = mem_result.scalars().all()
    member_count_by_team: dict[str, int] = defaultdict(int)
    is_member_by_team: dict[str, bool] = defaultdict(bool)
    for m in members:
        member_count_by_team[m.team_id] += 1
        if m.user_id == ctx.user_id:
            is_member_by_team[m.team_id] = True

    out = []
    for t in teams:
        out.append({
            "id": t.id,
            "name": t.name,
            "join_code": t.join_code if (t.status == "forming" or is_member_by_team.get(t.id, False)) else None,
            "challenge_type": t.challenge_type,
            "status": t.status,
            "representative_user_id": t.representative_user_id,
            "member_count": int(member_count_by_team.get(t.id, 0)),
            "min_members": int(t.min_members or CHALLENGE_TEAM_MIN_MEMBERS),
            "max_members": int(t.max_members or CHALLENGE_TEAM_MAX_MEMBERS),
            "is_member": bool(is_member_by_team.get(t.id, False)),
            "is_creator": t.created_by_user_id == ctx.user_id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return {"teams": out}


@app.post("/api/me/challenge-teams", status_code=201)
@limiter.limit(f"{settings.rate_limit_lexi}/minute")
async def create_challenge_team(
    request: Request,
    req: ChallengeTeamCreateRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")
    name = _safe_name(req.name, field_name="Team name")
    challenge_type = _normalize_challenge_team_type(req.challenge_type)
    min_members = max(CHALLENGE_TEAM_MIN_MEMBERS, int(req.min_members or CHALLENGE_TEAM_MIN_MEMBERS))
    max_members = min(CHALLENGE_TEAM_MAX_MEMBERS, int(req.max_members or CHALLENGE_TEAM_MAX_MEMBERS))
    if min_members > max_members:
        raise HTTPException(status_code=400, detail="min_members must be <= max_members")

    existing_res = await db.execute(
        select(ChallengeTeam).where(
            ChallengeTeam.created_by_user_id == ctx.user_id,
            ChallengeTeam.agency_id == ctx.agency_id,
            ChallengeTeam.status.in_(["forming", "locked"]),
        )
    )
    if existing_res.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="You already have an active challenge team")

    team_code = await _make_unique_challenge_team_code(db)
    team = ChallengeTeam(
        id=str(uuid.uuid4()),
        agency_id=ctx.agency_id,
        name=name,
        join_code=team_code,
        challenge_type=challenge_type,
        created_by_user_id=ctx.user_id,
        representative_user_id=ctx.user_id,
        min_members=min_members,
        max_members=max_members,
        status="forming",
    )
    db.add(team)
    db.add(ChallengeTeamMember(
        team_id=team.id,
        user_id=ctx.user_id,
        role="creator",
        is_active=True,
    ))
    await db.commit()
    return {
        "team": {
            "id": team.id,
            "name": team.name,
            "join_code": team.join_code,
            "challenge_type": team.challenge_type,
            "status": team.status,
            "member_count": 1,
            "min_members": team.min_members,
            "max_members": team.max_members,
            "is_creator": True,
            "is_member": True,
        }
    }


@app.post("/api/me/challenge-teams/join")
@limiter.limit(f"{settings.rate_limit_lexi}/minute")
async def join_challenge_team(
    request: Request,
    req: ChallengeTeamJoinRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")
    join_code = (req.join_code or "").strip().upper()
    if len(join_code) < 4:
        raise HTTPException(status_code=400, detail="Invalid team code")

    team_res = await db.execute(
        select(ChallengeTeam).where(ChallengeTeam.join_code == join_code).with_for_update()
    )
    team = team_res.scalar_one_or_none()
    if not team or team.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.status != "forming":
        raise HTTPException(status_code=400, detail="Team is no longer open")

    # One active team per user in agency.
    user_active_res = await db.execute(
        select(ChallengeTeamMember)
        .join(ChallengeTeam, ChallengeTeam.id == ChallengeTeamMember.team_id)
        .where(
            ChallengeTeam.agency_id == ctx.agency_id,
            ChallengeTeam.status.in_(["forming", "locked"]),
            ChallengeTeamMember.user_id == ctx.user_id,
            ChallengeTeamMember.is_active == True,  # noqa: E712
        )
    )
    active_member_row = user_active_res.scalar_one_or_none()
    if active_member_row and active_member_row.team_id != team.id:
        raise HTTPException(status_code=409, detail="You are already in an active challenge team")

    member_res = await db.execute(
        select(ChallengeTeamMember).where(
            ChallengeTeamMember.team_id == team.id,
            ChallengeTeamMember.user_id == ctx.user_id,
        ).with_for_update()
    )
    member = member_res.scalar_one_or_none()
    if member and member.is_active:
        count_res = await db.execute(
            select(func.count(ChallengeTeamMember.id)).where(
                ChallengeTeamMember.team_id == team.id,
                ChallengeTeamMember.is_active == True,  # noqa: E712
            )
        )
        return {"ok": True, "team_id": team.id, "member_count": int(count_res.scalar() or 0)}

    count_res = await db.execute(
        select(func.count(ChallengeTeamMember.id)).where(
            ChallengeTeamMember.team_id == team.id,
            ChallengeTeamMember.is_active == True,  # noqa: E712
        )
    )
    active_count = int(count_res.scalar() or 0)
    if active_count >= int(team.max_members or CHALLENGE_TEAM_MAX_MEMBERS):
        raise HTTPException(status_code=400, detail="Team is full")

    if member and not member.is_active:
        member.is_active = True
        member.left_at = None
    elif not member:
        db.add(ChallengeTeamMember(
            team_id=team.id,
            user_id=ctx.user_id,
            role="member",
            is_active=True,
        ))
    await db.commit()
    return {"ok": True, "team_id": team.id, "member_count": active_count + 1}


@app.post("/api/me/challenge-teams/{team_id}/remove")
@limiter.limit(f"{settings.rate_limit_lexi}/minute")
async def remove_challenge_team_member(
    request: Request,
    team_id: str,
    req: ChallengeTeamRemoveMemberRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    team_res = await db.execute(
        select(ChallengeTeam).where(ChallengeTeam.id == team_id).with_for_update()
    )
    team = team_res.scalar_one_or_none()
    if not team or team.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.status != "forming":
        raise HTTPException(status_code=400, detail="Members can only be removed before team lock")
    if team.created_by_user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="Only team creator can remove members")
    if req.user_id == ctx.user_id:
        raise HTTPException(status_code=400, detail="Use disband to close your own team")

    member_res = await db.execute(
        select(ChallengeTeamMember).where(
            ChallengeTeamMember.team_id == team.id,
            ChallengeTeamMember.user_id == req.user_id,
            ChallengeTeamMember.is_active == True,  # noqa: E712
        ).with_for_update()
    )
    member = member_res.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    member.is_active = False
    member.left_at = _lexi_now()
    await db.commit()
    return {"ok": True}


@app.post("/api/me/challenge-teams/{team_id}/leave")
@limiter.limit(f"{settings.rate_limit_lexi}/minute")
async def leave_challenge_team(
    request: Request,
    team_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    team_res = await db.execute(
        select(ChallengeTeam).where(ChallengeTeam.id == team_id).with_for_update()
    )
    team = team_res.scalar_one_or_none()
    if not team or team.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.status != "forming":
        raise HTTPException(status_code=400, detail="Cannot leave after team is locked")
    if team.created_by_user_id == ctx.user_id:
        raise HTTPException(status_code=400, detail="Team creator cannot leave; disband instead")

    member_res = await db.execute(
        select(ChallengeTeamMember).where(
            ChallengeTeamMember.team_id == team.id,
            ChallengeTeamMember.user_id == ctx.user_id,
            ChallengeTeamMember.is_active == True,  # noqa: E712
        ).with_for_update()
    )
    member = member_res.scalar_one_or_none()
    if member:
        member.is_active = False
        member.left_at = _lexi_now()
        await db.commit()
    return {"ok": True}


@app.post("/api/me/challenge-teams/{team_id}/disband")
@limiter.limit(f"{settings.rate_limit_lexi}/minute")
async def disband_challenge_team(
    request: Request,
    team_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    now = _lexi_now()
    team_res = await db.execute(
        select(ChallengeTeam).where(ChallengeTeam.id == team_id).with_for_update()
    )
    team = team_res.scalar_one_or_none()
    if not team or team.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.created_by_user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="Only team creator can disband")
    if team.status not in ("forming", "locked"):
        raise HTTPException(status_code=400, detail="Team is already closed")

    team.status = "disbanded"
    team.ended_at = now
    members_res = await db.execute(
        select(ChallengeTeamMember).where(
            ChallengeTeamMember.team_id == team.id,
            ChallengeTeamMember.is_active == True,  # noqa: E712
        )
    )
    members = members_res.scalars().all()
    for m in members:
        m.is_active = False
        m.left_at = now

    # Cancel outstanding invites tied to this team.
    await db.execute(
        TeamInvite.__table__.update()
        .where(
            TeamInvite.agency_id == ctx.agency_id,
            TeamInvite.status == "pending",
            ((TeamInvite.source_team_id == team.id) | (TeamInvite.target_team_id == team.id)),
        )
        .values(status="canceled", responded_at=now, responded_by=ctx.user_id)
    )

    # If this team is in open matches, cancel host matches and drop participant rows.
    open_matches_res = await db.execute(
        select(TeamMatch).where(
            TeamMatch.agency_id == ctx.agency_id,
            TeamMatch.status.in_(["forming", "ready"]),
        ).with_for_update()
    )
    open_matches = open_matches_res.scalars().all()
    for match in open_matches:
        if match.host_team_id == team.id:
            match.status = "canceled"
            match.ended_at = now
            continue
        part_res = await db.execute(
            select(TeamMatchParticipant).where(
                TeamMatchParticipant.match_id == match.id,
                TeamMatchParticipant.team_id == team.id,
                TeamMatchParticipant.status == "accepted",
            ).with_for_update()
        )
        part = part_res.scalar_one_or_none()
        if part:
            part.status = "dropped"
            remaining_res = await db.execute(
                select(func.count(TeamMatchParticipant.id)).where(
                    TeamMatchParticipant.match_id == match.id,
                    TeamMatchParticipant.status == "accepted",
                )
            )
            remaining = int(remaining_res.scalar() or 0)
            if remaining < 2:
                match.status = "canceled"
                match.ended_at = now
    await db.commit()
    return {"ok": True}


@app.post("/api/me/challenge-teams/{team_id}/lock")
@limiter.limit(f"{settings.rate_limit_lexi}/minute")
async def lock_challenge_team(
    request: Request,
    team_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    team_res = await db.execute(
        select(ChallengeTeam).where(ChallengeTeam.id == team_id).with_for_update()
    )
    team = team_res.scalar_one_or_none()
    if not team or team.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.created_by_user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="Only team creator can lock")
    if team.status != "forming":
        raise HTTPException(status_code=400, detail="Team is already locked")

    count_res = await db.execute(
        select(func.count(ChallengeTeamMember.id)).where(
            ChallengeTeamMember.team_id == team.id,
            ChallengeTeamMember.is_active == True,  # noqa: E712
        )
    )
    active_count = int(count_res.scalar() or 0)
    min_required = int(team.min_members or CHALLENGE_TEAM_MIN_MEMBERS)
    max_allowed = int(team.max_members or CHALLENGE_TEAM_MAX_MEMBERS)
    if active_count < min_required:
        raise HTTPException(status_code=400, detail=f"Need at least {min_required} members")
    if active_count > max_allowed:
        raise HTTPException(status_code=400, detail=f"Team can have at most {max_allowed} members")

    team.status = "locked"
    team.locked_at = _lexi_now()
    meta = dict(team.metadata_json or {})
    meta["last_presence_at"] = _now_iso()
    meta["last_presence_user_id"] = ctx.user_id
    team.metadata_json = meta
    await db.commit()
    return {"ok": True, "team_id": team.id, "member_count": active_count}


@app.get("/api/me/challenge-teams/{team_id}")
async def get_challenge_team(
    team_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    team = await db.get(ChallengeTeam, team_id)
    if not team or team.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Team not found")
    mem_res = await db.execute(
        select(ChallengeTeamMember).where(
            ChallengeTeamMember.team_id == team.id,
            ChallengeTeamMember.is_active == True,  # noqa: E712
        )
    )
    members = mem_res.scalars().all()
    user_ids = [m.user_id for m in members]
    users: dict[str, User] = {}
    if user_ids:
        user_res = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in user_res.scalars().all():
            users[u.id] = u
    member_rows = []
    for m in members:
        u = users.get(m.user_id)
        member_rows.append({
            "user_id": m.user_id,
            "display": _display_name_from_user(u) if u else m.user_id,
            "role": m.role,
            "is_representative": m.user_id == team.representative_user_id,
            "joined_at": m.joined_at.isoformat() if m.joined_at else None,
        })
    return {
        "team": {
            "id": team.id,
            "name": team.name,
            "join_code": team.join_code,
            "challenge_type": team.challenge_type,
            "status": team.status,
            "created_by_user_id": team.created_by_user_id,
            "representative_user_id": team.representative_user_id,
            "min_members": team.min_members,
            "max_members": team.max_members,
            "member_count": len(member_rows),
            "members": member_rows,
        }
    }


@app.post("/api/me/challenge-teams/{team_id}/presence")
@limiter.limit(f"{getattr(settings, 'rate_limit_team_presence', settings.rate_limit_lexi)}/minute")
async def challenge_team_presence(
    request: Request,
    team_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    team_res = await db.execute(
        select(ChallengeTeam).where(ChallengeTeam.id == team_id).with_for_update()
    )
    team = team_res.scalar_one_or_none()
    if not team or team.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.status not in ("forming", "locked"):
        raise HTTPException(status_code=400, detail="Team is not active")
    member = await _get_active_team_member(db, team.id, ctx.user_id)
    if not member:
        raise HTTPException(status_code=403, detail="Not a team member")
    meta = dict(team.metadata_json or {})
    meta["last_presence_at"] = _now_iso()
    meta["last_presence_user_id"] = ctx.user_id
    team.metadata_json = meta
    await db.commit()
    return {"ok": True, "last_presence_at": meta["last_presence_at"]}


@app.get("/api/me/challenge-teams/live")
async def list_live_challenge_teams(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")
    result = await db.execute(
        select(ChallengeTeam)
        .where(
            ChallengeTeam.agency_id == ctx.agency_id,
            ChallengeTeam.status == "locked",
        )
        .order_by(ChallengeTeam.created_at.desc())
        .limit(100)
    )
    teams = result.scalars().all()
    if not teams:
        return {"teams": []}
    open_team_rows = await db.execute(
        select(TeamMatchParticipant.team_id)
        .join(TeamMatch, TeamMatch.id == TeamMatchParticipant.match_id)
        .where(
            TeamMatch.agency_id == ctx.agency_id,
            TeamMatch.status.in_(["forming", "ready", "active"]),
            TeamMatchParticipant.status == "accepted",
        )
    )
    busy_team_ids = {row.team_id for row in open_team_rows.all()}
    team_ids = [t.id for t in teams]
    members_res = await db.execute(
        select(ChallengeTeamMember).where(
            ChallengeTeamMember.team_id.in_(team_ids),
            ChallengeTeamMember.is_active == True,  # noqa: E712
        )
    )
    members = members_res.scalars().all()
    member_counts: dict[str, int] = defaultdict(int)
    for m in members:
        member_counts[m.team_id] += 1

    now = _lexi_now()
    out = []
    for t in teams:
        meta = dict(t.metadata_json or {})
        last_presence_raw = meta.get("last_presence_at")
        last_presence_dt = None
        if isinstance(last_presence_raw, str):
            try:
                last_presence_dt = datetime.fromisoformat(last_presence_raw.replace("Z", ""))
            except Exception:
                last_presence_dt = None
        is_online = bool(last_presence_dt and (now - last_presence_dt).total_seconds() <= TEAM_HEARTBEAT_STALE_SEC)
        is_busy = t.id in busy_team_ids
        out.append({
            "id": t.id,
            "name": t.name,
            "challenge_type": t.challenge_type,
            "representative_user_id": t.representative_user_id,
            "member_count": int(member_counts.get(t.id, 0)),
            "is_online": is_online,
            "is_busy": is_busy,
            "last_presence_at": last_presence_raw,
            "is_my_team": any(m.team_id == t.id and m.user_id == ctx.user_id for m in members),
        })
    return {"teams": out}


@app.post("/api/me/team-invites")
@limiter.limit(f"{getattr(settings, 'rate_limit_team_invite', settings.rate_limit_lexi)}/minute")
async def create_team_invites(
    request: Request,
    req: TeamInviteCreateRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")
    challenge_type = _normalize_challenge_team_type(req.challenge_type)
    if challenge_type != "lexi_group":
        raise HTTPException(status_code=400, detail="Unsupported challenge type")
    timeout_sec = max(TEAM_INVITE_MIN_TIMEOUT_SEC, min(TEAM_INVITE_MAX_TIMEOUT_SEC, int(req.timeout_sec or 60)))
    target_ids = [str(t).strip() for t in (req.target_team_ids or []) if str(t).strip()]
    target_ids = list(dict.fromkeys(target_ids))
    if not target_ids:
        raise HTTPException(status_code=400, detail="Select at least one target team")
    if req.source_team_id in target_ids:
        raise HTTPException(status_code=400, detail="Source team cannot challenge itself")

    source_res = await db.execute(
        select(ChallengeTeam).where(ChallengeTeam.id == req.source_team_id).with_for_update()
    )
    source = source_res.scalar_one_or_none()
    if not source or source.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Source team not found")
    if source.status != "locked":
        raise HTTPException(status_code=400, detail="Source team must be locked before challenging")
    if source.representative_user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="Only representative can send challenges")

    s_member = await _get_active_team_member(db, source.id, ctx.user_id)
    if not s_member:
        raise HTTPException(status_code=403, detail="Representative is not an active team member")

    existing_match_res = await db.execute(
        select(TeamMatch).where(
            TeamMatch.agency_id == ctx.agency_id,
            TeamMatch.host_team_id == source.id,
            TeamMatch.status.in_(["forming", "ready", "active"]),
        ).order_by(TeamMatch.created_at.desc()).limit(1)
    )
    existing_match = existing_match_res.scalar_one_or_none()
    if existing_match:
        raise HTTPException(status_code=409, detail="Source team already has an active team challenge")

    target_res = await db.execute(
        select(ChallengeTeam).where(
            ChallengeTeam.id.in_(target_ids),
            ChallengeTeam.agency_id == ctx.agency_id,
            ChallengeTeam.status == "locked",
        )
    )
    targets = target_res.scalars().all()
    found_ids = {t.id for t in targets}
    missing = [tid for tid in target_ids if tid not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail="One or more target teams are unavailable")
    for t in targets:
        if await _team_is_in_open_match(db, t.id):
            raise HTTPException(status_code=409, detail=f"Target team '{t.name}' is already in an active match")

    match = TeamMatch(
        id=str(uuid.uuid4()),
        agency_id=ctx.agency_id,
        challenge_type=challenge_type,
        host_team_id=source.id,
        host_user_id=ctx.user_id,
        status="forming",
        metadata_json={"created_from": "team_invite", "target_count": len(targets)},
    )
    db.add(match)
    db.add(TeamMatchParticipant(
        match_id=match.id,
        team_id=source.id,
        invite_id=None,
        is_host=True,
        accepted_at=_lexi_now(),
        status="accepted",
    ))

    expires_at = _lexi_now() + timedelta(seconds=timeout_sec)
    invites = []
    for t in targets:
        inv = TeamInvite(
            id=str(uuid.uuid4()),
            agency_id=ctx.agency_id,
            challenge_type=challenge_type,
            match_id=match.id,
            source_team_id=source.id,
            target_team_id=t.id,
            created_by=ctx.user_id,
            status="pending",
            expires_at=expires_at,
        )
        invites.append(inv)
        db.add(inv)

    await db.commit()
    return {
        "ok": True,
        "match_id": match.id,
        "invite_count": len(invites),
        "expires_at": expires_at.isoformat(),
    }


@app.get("/api/me/team-invites/incoming")
async def list_incoming_team_invites(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")
    my_teams_res = await db.execute(
        select(ChallengeTeam).where(
            ChallengeTeam.agency_id == ctx.agency_id,
            ChallengeTeam.representative_user_id == ctx.user_id,
            ChallengeTeam.status == "locked",
        )
    )
    my_teams = my_teams_res.scalars().all()
    if not my_teams:
        return {"invites": []}
    my_team_ids = [t.id for t in my_teams]

    invite_res = await db.execute(
        select(TeamInvite).where(
            TeamInvite.agency_id == ctx.agency_id,
            TeamInvite.target_team_id.in_(my_team_ids),
            TeamInvite.status == "pending",
        ).order_by(TeamInvite.created_at.desc())
    )
    invites = invite_res.scalars().all()
    now = _lexi_now()
    out = []
    expired_ids = []
    canceled_ids = []
    source_ids_for_validation = {i.source_team_id for i in invites}
    source_team_map: dict[str, ChallengeTeam] = {}
    if source_ids_for_validation:
        src_val_res = await db.execute(select(ChallengeTeam).where(ChallengeTeam.id.in_(list(source_ids_for_validation))))
        source_team_map = {t.id: t for t in src_val_res.scalars().all()}
    for inv in invites:
        if inv.expires_at and inv.expires_at < now:
            expired_ids.append(inv.id)
            continue
        src_team = source_team_map.get(inv.source_team_id)
        if not src_team or src_team.status != "locked":
            canceled_ids.append(inv.id)
            continue
        out.append(inv)
    if expired_ids:
        await db.execute(
            TeamInvite.__table__.update()
            .where(TeamInvite.id.in_(expired_ids))
            .values(status="expired", responded_at=now)
        )
    if canceled_ids:
        await db.execute(
            TeamInvite.__table__.update()
            .where(TeamInvite.id.in_(canceled_ids))
            .values(status="canceled", responded_at=now)
        )
    if expired_ids or canceled_ids:
        await db.commit()

    source_ids = list({i.source_team_id for i in out})
    team_map: dict[str, ChallengeTeam] = {}
    if source_ids:
        src_res = await db.execute(select(ChallengeTeam).where(ChallengeTeam.id.in_(source_ids)))
        team_map = {t.id: t for t in src_res.scalars().all()}

    payload = []
    for inv in out:
        src = team_map.get(inv.source_team_id)
        payload.append({
            "invite_id": inv.id,
            "match_id": inv.match_id,
            "challenge_type": inv.challenge_type,
            "source_team_id": inv.source_team_id,
            "source_team_name": src.name if src else inv.source_team_id,
            "target_team_id": inv.target_team_id,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
        })
    return {
        "invites": payload,
        "expired_count": len(expired_ids),
        "canceled_count": len(canceled_ids),
    }


@app.post("/api/me/team-invites/{invite_id}/respond")
@limiter.limit(f"{getattr(settings, 'rate_limit_team_accept', settings.rate_limit_lexi)}/minute")
async def respond_team_invite(
    request: Request,
    invite_id: str,
    req: TeamInviteRespondRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    lock_res = await db.execute(
        select(TeamInvite).where(TeamInvite.id == invite_id).with_for_update()
    )
    invite = lock_res.scalar_one_or_none()
    if not invite or invite.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != "pending":
        return {"ok": True, "status": invite.status}
    now = _lexi_now()
    if invite.expires_at and invite.expires_at < now:
        invite.status = "expired"
        invite.responded_at = now
        invite.responded_by = ctx.user_id
        await db.commit()
        return {"ok": True, "status": "expired"}

    target_team = await db.get(ChallengeTeam, invite.target_team_id)
    if not target_team or target_team.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Target team unavailable")
    if target_team.status != "locked":
        invite.status = "canceled"
        invite.responded_at = now
        invite.responded_by = ctx.user_id
        await db.commit()
        return {"ok": True, "status": "canceled"}
    if target_team.representative_user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="Only target team representative can respond")

    member = await _get_active_team_member(db, target_team.id, ctx.user_id)
    if not member:
        raise HTTPException(status_code=403, detail="Representative is not active on target team")

    source_team = await db.get(ChallengeTeam, invite.source_team_id)
    if not source_team or source_team.status != "locked":
        invite.status = "canceled"
        invite.responded_at = now
        invite.responded_by = ctx.user_id
        await db.commit()
        return {"ok": True, "status": "canceled"}

    invite.status = "accepted" if req.accept else "declined"
    invite.responded_at = now
    invite.responded_by = ctx.user_id

    if req.accept and invite.match_id:
        match = await db.get(TeamMatch, invite.match_id)
        if not match or match.status not in ("forming", "ready"):
            invite.status = "canceled"
            await db.commit()
            return {"ok": True, "status": "canceled", "match_id": invite.match_id}
        if await _team_is_in_open_match(db, target_team.id, exclude_match_id=match.id):
            raise HTTPException(status_code=409, detail="Target team is already in another active match")
        if match and match.status in ("forming", "ready"):
            existing_part = await db.execute(
                select(TeamMatchParticipant).where(
                    TeamMatchParticipant.match_id == match.id,
                    TeamMatchParticipant.team_id == target_team.id,
                ).with_for_update()
            )
            existing = existing_part.scalar_one_or_none()
            if not existing:
                db.add(TeamMatchParticipant(
                    match_id=match.id,
                    team_id=target_team.id,
                    invite_id=invite.id,
                    is_host=False,
                    accepted_at=now,
                    status="accepted",
                ))
            else:
                existing.invite_id = invite.id
                existing.accepted_at = now
                existing.status = "accepted"
            match.status = "ready"
            if not match.ready_at:
                match.ready_at = now

    await db.commit()
    return {"ok": True, "status": invite.status, "match_id": invite.match_id}


@app.get("/api/me/team-matches/{match_id}")
async def get_team_match(
    match_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    match = await db.get(TeamMatch, match_id)
    if not match or match.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Match not found")
    parts_res = await db.execute(
        select(TeamMatchParticipant).where(TeamMatchParticipant.match_id == match.id)
    )
    participants = parts_res.scalars().all()
    team_ids = [p.team_id for p in participants]
    team_map = {}
    if team_ids:
        teams_res = await db.execute(select(ChallengeTeam).where(ChallengeTeam.id.in_(team_ids)))
        team_map = {t.id: t for t in teams_res.scalars().all()}
    part_rows = []
    for p in participants:
        t = team_map.get(p.team_id)
        part_rows.append({
            "team_id": p.team_id,
            "team_name": t.name if t else p.team_id,
            "is_host": bool(p.is_host),
            "status": p.status,
            "accepted_at": p.accepted_at.isoformat() if p.accepted_at else None,
        })
    return {
        "match": {
            "id": match.id,
            "status": match.status,
            "challenge_type": match.challenge_type,
            "host_team_id": match.host_team_id,
            "host_user_id": match.host_user_id,
            "started_session_id": match.started_session_id,
            "ready_at": match.ready_at.isoformat() if match.ready_at else None,
            "participants": part_rows,
            "created_at": match.created_at.isoformat() if match.created_at else None,
        }
    }


@app.post("/api/me/team-matches/{match_id}/leave")
@limiter.limit(f"{getattr(settings, 'rate_limit_team_accept', settings.rate_limit_lexi)}/minute")
async def leave_team_match(
    request: Request,
    match_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    now = _lexi_now()
    lock_res = await db.execute(
        select(TeamMatch).where(TeamMatch.id == match_id).with_for_update()
    )
    match = lock_res.scalar_one_or_none()
    if not match or match.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.status in ("finished", "canceled"):
        raise HTTPException(status_code=400, detail="Match has already ended")
    existing_session: Optional[LexiGroupSession] = None
    if match.started_session_id:
        existing_session = await db.get(LexiGroupSession, match.started_session_id)
        # If gameplay has started already (not just lobby), do not allow team leave.
        if existing_session and existing_session.status != "lobby":
            raise HTTPException(status_code=400, detail="Match has already started")

    part_res = await db.execute(
        select(TeamMatchParticipant).where(
            TeamMatchParticipant.match_id == match.id,
            TeamMatchParticipant.status == "accepted",
        ).with_for_update()
    )
    parts = part_res.scalars().all()
    team_ids = [p.team_id for p in parts]
    teams_res = await db.execute(select(ChallengeTeam).where(ChallengeTeam.id.in_(team_ids)))
    team_map = {t.id: t for t in teams_res.scalars().all()}

    caller_part: Optional[TeamMatchParticipant] = None
    caller_team_id: Optional[str] = None
    for p in parts:
        t = team_map.get(p.team_id)
        if not t:
            continue
        if t.representative_user_id != ctx.user_id:
            continue
        member = await _get_active_team_member(db, t.id, ctx.user_id)
        if not member:
            continue
        caller_part = p
        caller_team_id = t.id
        break
    if not caller_part or not caller_team_id:
        raise HTTPException(status_code=403, detail="Only an accepted team representative can leave this match")

    caller_part.status = "dropped"
    if caller_part.invite_id:
        inv_res = await db.execute(
            select(TeamInvite).where(TeamInvite.id == caller_part.invite_id).with_for_update()
        )
        inv = inv_res.scalar_one_or_none()
        if inv and inv.status == "accepted":
            inv.status = "declined"
            inv.responded_at = now
            inv.responded_by = ctx.user_id

    meta = dict(match.metadata_json or {})
    joined_team_ids = {str(tid) for tid in (meta.get("joined_team_ids") or []) if tid}
    if caller_team_id in joined_team_ids:
        joined_team_ids.remove(caller_team_id)
    meta["joined_team_ids"] = sorted(list(joined_team_ids))
    match.metadata_json = meta

    remaining_accepted_res = await db.execute(
        select(func.count(TeamMatchParticipant.id)).where(
            TeamMatchParticipant.match_id == match.id,
            TeamMatchParticipant.status == "accepted",
        )
    )
    remaining = int(remaining_accepted_res.scalar() or 0)

    # If host team leaves before start, dissolve the whole challenge.
    if caller_team_id == match.host_team_id or remaining < 2:
        match.status = "canceled"
        match.ended_at = now
        await db.execute(
            TeamInvite.__table__.update()
            .where(
                TeamInvite.match_id == match.id,
                TeamInvite.status == "pending",
            )
            .values(status="canceled", responded_at=now)
        )
    elif match.status == "ready":
        # Keep it in forming until enough accepted teams remain and rejoin.
        match.status = "forming"

    # If a shared lobby already exists for this match, remove this team's representative
    # from the lobby roster so participants list stays accurate.
    if existing_session:
        rep_user_id = None
        caller_team = team_map.get(caller_team_id)
        if caller_team:
            rep_user_id = caller_team.representative_user_id
        if rep_user_id:
            participants = list(existing_session.participants or [])
            filtered = [p for p in participants if (p or {}).get("user_id") != rep_user_id]
            if len(filtered) != len(participants):
                existing_session.participants = filtered
                flag_modified(existing_session, "participants")
                existing_session.updated_at = now
                if existing_session.host_user_id == rep_user_id and filtered:
                    existing_session.host_user_id = filtered[0].get("user_id") or existing_session.host_user_id
                if len(filtered) < 2:
                    existing_session.status = "finished"
                    existing_session.phase = "final_results"
                    existing_session.phase_started_at = now
                    existing_session.phase_ends_at = None
                    existing_session.ended_at = now
                    match.status = "canceled"
                    match.ended_at = now

    await db.commit()
    if existing_session:
        await _broadcast_lexi_group_state(existing_session)
    return {
        "ok": True,
        "match_id": match.id,
        "match_status": match.status,
        "remaining_accepted_teams": remaining,
    }


@app.get("/api/me/team-matches-hosted")
async def get_my_team_match(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")
    res = await db.execute(
        select(TeamMatch)
        .where(
            TeamMatch.agency_id == ctx.agency_id,
            TeamMatch.host_user_id == ctx.user_id,
            TeamMatch.status.in_(["forming", "ready", "active"]),
        )
        .order_by(TeamMatch.created_at.desc())
        .limit(1)
    )
    match = res.scalar_one_or_none()
    if not match:
        recent_cancel_res = await db.execute(
            select(TeamMatch)
            .where(
                TeamMatch.agency_id == ctx.agency_id,
                TeamMatch.host_user_id == ctx.user_id,
                TeamMatch.status == "canceled",
                TeamMatch.ended_at.isnot(None),
                TeamMatch.ended_at >= (_lexi_now() - timedelta(minutes=30)),
            )
            .order_by(TeamMatch.ended_at.desc())
            .limit(1)
        )
        recent = recent_cancel_res.scalar_one_or_none()
        if recent:
            meta = dict(recent.metadata_json or {})
            reason = meta.get("cancel_reason")
            if reason == "stale_forming_timeout":
                return {
                    "match": None,
                    "recent_notice": {
                        "type": "info",
                        "message": "Your previous hosted team match timed out while waiting for accepts.",
                        "ended_at": recent.ended_at.isoformat() if recent.ended_at else None,
                    },
                }
            if reason == "stale_ready_timeout":
                return {
                    "match": None,
                    "recent_notice": {
                        "type": "info",
                        "message": "Your previous hosted team match timed out before it was started.",
                        "ended_at": recent.ended_at.isoformat() if recent.ended_at else None,
                    },
                }
        return {"match": None}

    parts_res = await db.execute(
        select(TeamMatchParticipant).where(TeamMatchParticipant.match_id == match.id)
    )
    participants = parts_res.scalars().all()
    accepted_count = sum(1 for p in participants if p.status == "accepted")
    return {
        "match": {
            "id": match.id,
            "status": match.status,
            "challenge_type": match.challenge_type,
            "host_team_id": match.host_team_id,
            "started_session_id": match.started_session_id,
            "accepted_team_count": accepted_count,
            "created_at": match.created_at.isoformat() if match.created_at else None,
            "ready_at": match.ready_at.isoformat() if match.ready_at else None,
        }
    }


@app.get("/api/me/team-lobby-state")
async def get_team_lobby_state(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")
    now = _lexi_now()

    # ── My active team summary ───────────────────────────────────────────────
    my_team_res = await db.execute(
        select(ChallengeTeam)
        .join(ChallengeTeamMember, ChallengeTeamMember.team_id == ChallengeTeam.id)
        .where(
            ChallengeTeam.agency_id == ctx.agency_id,
            ChallengeTeam.status.in_(["forming", "locked"]),
            ChallengeTeamMember.user_id == ctx.user_id,
            ChallengeTeamMember.is_active == True,  # noqa: E712
        )
        .order_by(ChallengeTeam.created_at.desc())
        .limit(1)
    )
    my_team = my_team_res.scalar_one_or_none()

    my_team_summary = None
    my_team_detail = None
    if my_team:
        my_mem_count_res = await db.execute(
            select(func.count(ChallengeTeamMember.id)).where(
                ChallengeTeamMember.team_id == my_team.id,
                ChallengeTeamMember.is_active == True,  # noqa: E712
            )
        )
        my_team_summary = {
            "id": my_team.id,
            "name": my_team.name,
            "join_code": my_team.join_code if my_team.status == "forming" else None,
            "challenge_type": my_team.challenge_type,
            "status": my_team.status,
            "representative_user_id": my_team.representative_user_id,
            "member_count": int(my_mem_count_res.scalar() or 0),
            "min_members": int(my_team.min_members or CHALLENGE_TEAM_MIN_MEMBERS),
            "max_members": int(my_team.max_members or CHALLENGE_TEAM_MAX_MEMBERS),
            "is_member": True,
            "is_creator": my_team.created_by_user_id == ctx.user_id,
            "created_at": my_team.created_at.isoformat() if my_team.created_at else None,
            "created_by_user_id": my_team.created_by_user_id,
        }

        my_members_res = await db.execute(
            select(ChallengeTeamMember).where(
                ChallengeTeamMember.team_id == my_team.id,
                ChallengeTeamMember.is_active == True,  # noqa: E712
            )
        )
        my_members = my_members_res.scalars().all()
        my_user_ids = [m.user_id for m in my_members]
        my_user_map: dict[str, User] = {}
        if my_user_ids:
            users_res = await db.execute(select(User).where(User.id.in_(my_user_ids)))
            my_user_map = {u.id: u for u in users_res.scalars().all()}

        my_team_detail = {
            "id": my_team.id,
            "name": my_team.name,
            "join_code": my_team.join_code,
            "challenge_type": my_team.challenge_type,
            "status": my_team.status,
            "created_by_user_id": my_team.created_by_user_id,
            "representative_user_id": my_team.representative_user_id,
            "min_members": my_team.min_members,
            "max_members": my_team.max_members,
            "member_count": len(my_members),
            "members": [
                {
                    "user_id": m.user_id,
                    "display": _display_name_from_user(my_user_map[m.user_id]) if m.user_id in my_user_map else m.user_id,
                    "role": m.role,
                    "is_representative": m.user_id == my_team.representative_user_id,
                    "joined_at": m.joined_at.isoformat() if m.joined_at else None,
                }
                for m in my_members
            ],
        }

    # ── Live teams list ──────────────────────────────────────────────────────
    locked_teams_res = await db.execute(
        select(ChallengeTeam)
        .where(
            ChallengeTeam.agency_id == ctx.agency_id,
            ChallengeTeam.status == "locked",
        )
        .order_by(ChallengeTeam.created_at.desc())
        .limit(100)
    )
    locked_teams = locked_teams_res.scalars().all()
    live_teams = []
    if locked_teams:
        team_ids = [t.id for t in locked_teams]
        members_res = await db.execute(
            select(ChallengeTeamMember).where(
                ChallengeTeamMember.team_id.in_(team_ids),
                ChallengeTeamMember.is_active == True,  # noqa: E712
            )
        )
        members = members_res.scalars().all()
        member_counts: dict[str, int] = defaultdict(int)
        member_user_ids: dict[str, set[str]] = defaultdict(set)
        for m in members:
            member_counts[m.team_id] += 1
            member_user_ids[m.team_id].add(m.user_id)

        open_team_rows = await db.execute(
            select(TeamMatchParticipant.team_id)
            .join(TeamMatch, TeamMatch.id == TeamMatchParticipant.match_id)
            .where(
                TeamMatch.agency_id == ctx.agency_id,
                TeamMatch.status.in_(["forming", "ready", "active"]),
                TeamMatchParticipant.status == "accepted",
            )
        )
        busy_team_ids = {row.team_id for row in open_team_rows.all()}

        for t in locked_teams:
            meta = dict(t.metadata_json or {})
            last_presence_raw = meta.get("last_presence_at")
            last_presence_dt = None
            if isinstance(last_presence_raw, str):
                try:
                    last_presence_dt = datetime.fromisoformat(last_presence_raw.replace("Z", ""))
                except Exception:
                    last_presence_dt = None
            is_online = bool(last_presence_dt and (now - last_presence_dt).total_seconds() <= TEAM_HEARTBEAT_STALE_SEC)
            live_teams.append({
                "id": t.id,
                "name": t.name,
                "challenge_type": t.challenge_type,
                "representative_user_id": t.representative_user_id,
                "member_count": int(member_counts.get(t.id, 0)),
                "is_online": is_online,
                "is_busy": t.id in busy_team_ids,
                "last_presence_at": last_presence_raw,
                "is_my_team": ctx.user_id in member_user_ids.get(t.id, set()),
            })

    # ── Incoming invites for my representative teams ─────────────────────────
    my_rep_teams_res = await db.execute(
        select(ChallengeTeam).where(
            ChallengeTeam.agency_id == ctx.agency_id,
            ChallengeTeam.representative_user_id == ctx.user_id,
            ChallengeTeam.status == "locked",
        )
    )
    my_rep_teams = my_rep_teams_res.scalars().all()
    my_rep_team_ids = [t.id for t in my_rep_teams]

    incoming_invites = []
    expired_ids: list[str] = []
    canceled_ids: list[str] = []
    if my_rep_team_ids:
        invite_res = await db.execute(
            select(TeamInvite).where(
                TeamInvite.agency_id == ctx.agency_id,
                TeamInvite.target_team_id.in_(my_rep_team_ids),
                TeamInvite.status.in_(["pending", "accepted"]),
            ).order_by(TeamInvite.created_at.desc())
        )
        invites = invite_res.scalars().all()
        source_team_ids = {i.source_team_id for i in invites}
        source_map: dict[str, ChallengeTeam] = {}
        if source_team_ids:
            src_res = await db.execute(select(ChallengeTeam).where(ChallengeTeam.id.in_(list(source_team_ids))))
            source_map = {t.id: t for t in src_res.scalars().all()}
        invite_match_ids = {i.match_id for i in invites if i.match_id}
        match_map: dict[str, TeamMatch] = {}
        if invite_match_ids:
            mres = await db.execute(select(TeamMatch).where(TeamMatch.id.in_(list(invite_match_ids))))
            match_map = {m.id: m for m in mres.scalars().all()}

        valid_invites = []
        for inv in invites:
            if inv.status == "pending" and inv.expires_at and inv.expires_at < now:
                expired_ids.append(inv.id)
                continue
            if inv.status == "accepted":
                m = match_map.get(inv.match_id or "")
                if not m or m.status not in ("forming", "ready", "active"):
                    continue
            src_team = source_map.get(inv.source_team_id)
            if inv.status == "pending" and (not src_team or src_team.status != "locked"):
                canceled_ids.append(inv.id)
                continue
            valid_invites.append(inv)

        if expired_ids:
            await db.execute(
                TeamInvite.__table__.update()
                .where(TeamInvite.id.in_(expired_ids))
                .values(status="expired", responded_at=now)
            )
        if canceled_ids:
            await db.execute(
                TeamInvite.__table__.update()
                .where(TeamInvite.id.in_(canceled_ids))
                .values(status="canceled", responded_at=now)
            )
        if expired_ids or canceled_ids:
            await db.commit()

        for inv in valid_invites:
            src = source_map.get(inv.source_team_id)
            incoming_invites.append({
                "invite_id": inv.id,
                "match_id": inv.match_id,
                "challenge_type": inv.challenge_type,
                "source_team_id": inv.source_team_id,
                "source_team_name": src.name if src else inv.source_team_id,
                "target_team_id": inv.target_team_id,
                "status": inv.status,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
                "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
            })

    # ── Active match for my representative team (host or target) ──────────────
    my_match = None
    if my_rep_team_ids:
        my_match_res = await db.execute(
            select(TeamMatch)
            .join(TeamMatchParticipant, TeamMatchParticipant.match_id == TeamMatch.id)
            .where(
                TeamMatch.agency_id == ctx.agency_id,
                TeamMatch.status.in_(["forming", "ready", "active"]),
                TeamMatchParticipant.team_id.in_(my_rep_team_ids),
                TeamMatchParticipant.status == "accepted",
            )
            .order_by(TeamMatch.created_at.desc())
            .limit(1)
        )
        mm = my_match_res.scalar_one_or_none()
        if mm:
            mm_parts_res = await db.execute(
                select(TeamMatchParticipant).where(
                    TeamMatchParticipant.match_id == mm.id,
                    TeamMatchParticipant.status == "accepted",
                )
            )
            mm_parts = mm_parts_res.scalars().all()
            mm_meta = dict(mm.metadata_json or {})
            joined_team_ids = list(mm_meta.get("joined_team_ids") or [])
            joined_team_set = {str(tid) for tid in joined_team_ids if tid}
            accepted_team_ids = [p.team_id for p in mm_parts]
            my_match = {
                "id": mm.id,
                "status": mm.status,
                "challenge_type": mm.challenge_type,
                "host_team_id": mm.host_team_id,
                "host_user_id": mm.host_user_id,
                "is_host": mm.host_user_id == ctx.user_id,
                "accepted_team_count": len(accepted_team_ids),
                "joined_team_count": len(joined_team_set.intersection(set(accepted_team_ids))),
                "joined_team_ids": sorted(list(joined_team_set)),
                "started_session_id": mm.started_session_id,
                "ready_at": mm.ready_at.isoformat() if mm.ready_at else None,
                "started_at": mm.started_at.isoformat() if mm.started_at else None,
                "created_at": mm.created_at.isoformat() if mm.created_at else None,
            }

    # ── Hosted match summary / recent notice ─────────────────────────────────
    hosted_match = None
    recent_notice = None
    hosted = None
    if my_rep_team_ids:
        hosted_res = await db.execute(
            select(TeamMatch)
            .where(
                TeamMatch.agency_id == ctx.agency_id,
                TeamMatch.host_user_id == ctx.user_id,
                TeamMatch.host_team_id.in_(my_rep_team_ids),
                TeamMatch.status.in_(["forming", "ready", "active"]),
            )
            .order_by(TeamMatch.created_at.desc())
            .limit(1)
        )
        hosted = hosted_res.scalar_one_or_none()
    if hosted:
        part_res = await db.execute(
            select(TeamMatchParticipant).where(TeamMatchParticipant.match_id == hosted.id)
        )
        accepted_count = sum(1 for p in part_res.scalars().all() if p.status == "accepted")
        hosted_match = {
            "id": hosted.id,
            "status": hosted.status,
            "challenge_type": hosted.challenge_type,
            "host_team_id": hosted.host_team_id,
            "started_session_id": hosted.started_session_id,
            "accepted_team_count": accepted_count,
            "created_at": hosted.created_at.isoformat() if hosted.created_at else None,
            "ready_at": hosted.ready_at.isoformat() if hosted.ready_at else None,
        }
    else:
        recent_cancel_res = await db.execute(
            select(TeamMatch)
            .where(
                TeamMatch.agency_id == ctx.agency_id,
                TeamMatch.host_user_id == ctx.user_id,
                TeamMatch.host_team_id.in_(my_rep_team_ids) if my_rep_team_ids else False,  # keep notice scoped to my current hosted teams
                TeamMatch.status == "canceled",
                TeamMatch.ended_at.isnot(None),
                TeamMatch.ended_at >= (_lexi_now() - timedelta(minutes=30)),
            )
            .order_by(TeamMatch.ended_at.desc())
            .limit(1)
        )
        recent = recent_cancel_res.scalar_one_or_none()
        if recent:
            reason = dict(recent.metadata_json or {}).get("cancel_reason")
            if reason == "stale_forming_timeout":
                recent_notice = {
                    "type": "info",
                    "message": "Your previous hosted team match timed out while waiting for accepts.",
                    "ended_at": recent.ended_at.isoformat() if recent.ended_at else None,
                }
            elif reason == "stale_ready_timeout":
                recent_notice = {
                    "type": "info",
                    "message": "Your previous hosted team match timed out before it was started.",
                    "ended_at": recent.ended_at.isoformat() if recent.ended_at else None,
                }

    return {
        "my_team": my_team_summary,
        "my_team_detail": my_team_detail,
        "live_teams": live_teams,
        "incoming_invites": incoming_invites,
        "incoming_sweep": {
            "expired_count": len(expired_ids),
            "canceled_count": len(canceled_ids),
        },
        "my_match": my_match,
        "hosted_match": hosted_match,
        "recent_notice": recent_notice,
    }


@app.post("/api/me/team-matches/{match_id}/start")
@limiter.limit(f"{getattr(settings, 'rate_limit_team_start', settings.rate_limit_lexi)}/minute")
async def start_team_match(
    request: Request,
    match_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    _ensure_team_challenge_enabled()
    now = _lexi_now()
    lock_res = await db.execute(
        select(TeamMatch).where(TeamMatch.id == match_id).with_for_update()
    )
    match = lock_res.scalar_one_or_none()
    if not match or match.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Match not found")

    part_res = await db.execute(
        select(TeamMatchParticipant).where(
            TeamMatchParticipant.match_id == match.id,
            TeamMatchParticipant.status == "accepted",
        ).with_for_update()
    )
    parts = part_res.scalars().all()
    team_ids = [p.team_id for p in parts]
    teams_res = await db.execute(select(ChallengeTeam).where(ChallengeTeam.id.in_(team_ids)))
    team_map = {t.id: t for t in teams_res.scalars().all()}

    # Keep accepted set clean if teams are no longer locked.
    valid_parts: list[TeamMatchParticipant] = []
    for p in parts:
        t = team_map.get(p.team_id)
        if t and t.status == "locked":
            valid_parts.append(p)
        else:
            p.status = "dropped"
    parts = valid_parts
    accepted_team_ids = [p.team_id for p in parts]
    if len(parts) < 2:
        match.status = "canceled"
        match.ended_at = now
        await db.commit()
        raise HTTPException(status_code=400, detail="Need at least two teams to continue")

    # Caller must be representative for one accepted team and still active on that team.
    caller_team_id: Optional[str] = None
    for p in parts:
        t = team_map.get(p.team_id)
        if not t:
            continue
        if t.representative_user_id != ctx.user_id:
            continue
        member = await _get_active_team_member(db, t.id, ctx.user_id)
        if not member:
            continue
        caller_team_id = t.id
        break
    if not caller_team_id:
        raise HTTPException(status_code=403, detail="Only an accepted team representative can join this match")

    await _expire_pending_invites_for_match(db, match.id, now=now)

    if match.status not in ("forming", "ready", "active"):
        raise HTTPException(status_code=400, detail="Match cannot be joined right now")

    # Record team-level join readiness before any early return.
    meta = dict(match.metadata_json or {})
    joined_team_ids = {str(tid) for tid in (meta.get("joined_team_ids") or []) if tid}
    joined_team_ids.add(caller_team_id)
    meta["joined_team_ids"] = sorted(list(joined_team_ids))
    match.metadata_json = meta
    if match.status == "forming":
        match.status = "ready"
        if not match.ready_at:
            match.ready_at = now

    # If shared lobby session already exists, add this team rep into that lobby and return.
    if match.started_session_id:
        session = await db.get(LexiGroupSession, match.started_session_id)
        if not session:
            await db.commit()
            return {
                "ok": True,
                "already_started": True,
                "session_id": match.started_session_id,
                "room_code": None,
            }
        caller_team = team_map.get(caller_team_id)
        if caller_team:
            rep_id = caller_team.representative_user_id
            rep_user = await db.get(User, rep_id)
            level_res = await db.execute(
                select(AgencyMember.provider_level).where(
                    AgencyMember.agency_id == ctx.agency_id,
                    AgencyMember.user_id == rep_id,
                )
            )
            rep_level = level_res.scalar_one_or_none() or "EMT"
            rep_display = f"{caller_team.name} ({_display_name_from_user(rep_user) if rep_user else rep_id})"
            _ensure_group_participant(session, rep_id, rep_display, rep_level)
            session.updated_at = now
        await db.commit()
        await _broadcast_lexi_group_state(session)
        return {
            "ok": True,
            "already_started": True,
            "session_id": session.id,
            "room_code": session.room_code,
            "state": _build_group_public_state(session, ctx.user_id),
        }

    host_team = await db.get(ChallengeTeam, match.host_team_id)
    if not host_team or host_team.status != "locked":
        match.status = "canceled"
        match.ended_at = now
        await db.commit()
        raise HTTPException(status_code=400, detail="Host team is no longer available")

    # Create shared lobby session immediately on first Join Live Match so reps are dropped
    # into the same lobby view without waiting on a second host-only action.
    rep_ids = [team_map[p.team_id].representative_user_id for p in parts if p.team_id in team_map]
    user_res = await db.execute(select(User).where(User.id.in_(rep_ids)))
    user_map = {u.id: u for u in user_res.scalars().all()}
    member_rows = await db.execute(
        select(AgencyMember.user_id, AgencyMember.provider_level).where(
            AgencyMember.agency_id == ctx.agency_id,
            AgencyMember.user_id.in_(rep_ids),
        )
    )
    level_map = {r.user_id: r.provider_level for r in member_rows}

    room_code = await _make_unique_group_room_code(db)
    group_session = LexiGroupSession(
        id=str(uuid.uuid4()),
        agency_id=ctx.agency_id,
        host_user_id=match.host_user_id,
        room_code=room_code,
        status="lobby",
        phase="lobby",
        round_index=1,
        max_rounds=LEXI_GROUP_ROUNDS,
        current_question_index=0,
        mca=ctx.mca,
        participants=[],
        rounds=[],
    )
    for p in parts:
        t = team_map.get(p.team_id)
        if not t:
            continue
        if p.team_id not in joined_team_ids:
            continue
        rep_id = t.representative_user_id
        rep_user = user_map.get(rep_id)
        display = f"{t.name} ({_display_name_from_user(rep_user) if rep_user else rep_id})"
        level = level_map.get(rep_id, "EMT")
        _ensure_group_participant(group_session, rep_id, display, level)

    db.add(group_session)
    match.status = "ready"
    if not match.ready_at:
        match.ready_at = now
    match.started_session_id = group_session.id
    await db.commit()
    await _broadcast_lexi_group_state(group_session)
    return {
        "ok": True,
        "session_id": group_session.id,
        "room_code": group_session.room_code,
        "state": _build_group_public_state(group_session, ctx.user_id),
    }


@app.post("/api/me/lexi-group/create")
@limiter.limit(f"{getattr(settings, 'rate_limit_lexi_group_create', settings.rate_limit_lexi)}/minute")
async def create_lexi_group(
    request: Request,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")
    user = await db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    moved_sessions = await _remove_user_from_other_lexi_groups(
        db=db,
        agency_id=ctx.agency_id,
        user_id=ctx.user_id,
        exclude_session_id=None,
    )

    room_code = await _make_unique_group_room_code(db)
    session = LexiGroupSession(
        id=str(uuid.uuid4()),
        agency_id=ctx.agency_id,
        host_user_id=ctx.user_id,
        room_code=room_code,
        status="lobby",
        phase="lobby",
        round_index=1,
        max_rounds=LEXI_GROUP_ROUNDS,
        current_question_index=0,
        mca=ctx.mca,
        participants=[],
        rounds=[],
    )
    _ensure_group_participant(session, ctx.user_id, _display_name_from_user(user), ctx.provider_level)
    db.add(session)
    await db.commit()
    for old in moved_sessions:
        await _broadcast_lexi_group_state(old)
    await _broadcast_lexi_group_state(session)
    return {
        "session_id": session.id,
        "room_code": session.room_code,
        "state": _build_group_public_state(session, ctx.user_id),
    }


@app.post("/api/me/lexi-group/join")
@limiter.limit(f"{getattr(settings, 'rate_limit_lexi_group_join', settings.rate_limit_lexi)}/minute")
async def join_lexi_group(
    request: Request,
    req: LexiGroupJoinRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.agency_id:
        raise HTTPException(status_code=400, detail="Agency context required")
    result = await db.execute(
        select(LexiGroupSession).where(
            LexiGroupSession.room_code == req.room_code.strip().upper()
        ).with_for_update()
    )
    session = result.scalar_one_or_none()
    if not session or session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Group session not found")
    is_participant = any((p or {}).get("user_id") == ctx.user_id for p in (session.participants or []))
    if session.status != "lobby" and not is_participant:
        raise HTTPException(status_code=400, detail="Group challenge already started")
    user = await db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    moved_sessions = await _remove_user_from_other_lexi_groups(
        db=db,
        agency_id=ctx.agency_id,
        user_id=ctx.user_id,
        exclude_session_id=session.id,
    )

    _ensure_group_participant(session, ctx.user_id, _display_name_from_user(user), ctx.provider_level)
    session.updated_at = _lexi_now()
    await db.commit()
    for old in moved_sessions:
        await _broadcast_lexi_group_state(old)
    await _broadcast_lexi_group_state(session)
    return {
        "session_id": session.id,
        "room_code": session.room_code,
        "state": _build_group_public_state(session, ctx.user_id),
    }


@app.get("/api/me/lexi-group/{session_id}")
async def get_lexi_group_state(
    session_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(LexiGroupSession, session_id)
    if not session or session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Group session not found")
    if not any((p or {}).get("user_id") == ctx.user_id for p in (session.participants or [])):
        raise HTTPException(status_code=403, detail="Not a participant")
    return {"state": _build_group_public_state(session, ctx.user_id)}


@app.post("/api/me/lexi-group/start")
@limiter.limit(f"{getattr(settings, 'rate_limit_lexi_group_start', settings.rate_limit_lexi)}/minute")
async def start_lexi_group(
    request: Request,
    req: LexiGroupSessionRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    lock_res = await db.execute(
        select(LexiGroupSession).where(LexiGroupSession.id == req.session_id).with_for_update()
    )
    session = lock_res.scalar_one_or_none()
    if not session or session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Group session not found")
    if session.host_user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="Only host can start this challenge")
    if session.status != "lobby":
        raise HTTPException(status_code=400, detail="Challenge already started")

    participants = list(session.participants or [])
    if len(participants) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 participants")

    # Team challenge gate: if this lobby was created from a TeamMatch, all accepted teams
    # must have clicked Join Live Match before host can start the round timer/questions.
    tm_res = await db.execute(
        select(TeamMatch).where(
            TeamMatch.started_session_id == session.id,
            TeamMatch.status.in_(["forming", "ready", "active"]),
        ).with_for_update()
    )
    team_match = tm_res.scalar_one_or_none()
    if team_match:
        part_res = await db.execute(
            select(TeamMatchParticipant).where(
                TeamMatchParticipant.match_id == team_match.id,
                TeamMatchParticipant.status == "accepted",
            )
        )
        accepted_parts = part_res.scalars().all()
        accepted_team_ids = [p.team_id for p in accepted_parts if p.team_id]
        tm_meta = dict(team_match.metadata_json or {})
        joined_team_ids = {str(tid) for tid in (tm_meta.get("joined_team_ids") or []) if tid}
        missing_team_ids = [tid for tid in accepted_team_ids if tid not in joined_team_ids]
        if missing_team_ids:
            teams_res = await db.execute(select(ChallengeTeam).where(ChallengeTeam.id.in_(missing_team_ids)))
            tmap = {t.id: t for t in teams_res.scalars().all()}
            missing_names = [tmap.get(tid).name if tmap.get(tid) else tid for tid in missing_team_ids]
            raise HTTPException(
                status_code=400,
                detail=f"Waiting for teams to join live lobby: {', '.join(missing_names)}",
            )
        team_match.status = "active"
        if not team_match.started_at:
            team_match.started_at = _lexi_now()

    member_rows = await db.execute(
        select(AgencyMember.user_id, AgencyMember.provider_level)
        .where(AgencyMember.agency_id == session.agency_id)
    )
    level_by_uid = {r.user_id: r.provider_level for r in member_rows}
    levels = [level_by_uid.get(p.get("user_id"), "EMT") for p in participants]
    effective_level = _lowest_provider_level(levels)
    session.effective_provider_level = effective_level
    session.mca = session.mca or ctx.mca

    mca_value = session.mca or settings.default_mca
    participant_ids = [p.get("user_id") for p in participants if p.get("user_id")]
    used_keys = _recent_lexi_keys_for_users(participant_ids)
    team_missed = _overlap_recent_missed_keys(participant_ids, min_count=2)
    generated: list[list[dict]] = []
    for _ in range(LEXI_GROUP_ROUNDS):
        qs = await generate_lexi_questions(
            effective_level,
            mca_value,
            exclude_keys=used_keys,
            prefer_keys=team_missed,
            prefer_n=1,
        )
        generated.append(qs)
        for q in qs:
            used_keys.add(_lexi_question_key(q))

    # Remember served questions for all participants to reduce near-term repeats.
    for qs in generated:
        _remember_lexi_questions_for_users(participant_ids, qs)
    rounds: list[dict] = [
        {"questions": qs[:LEXI_GROUP_QUESTIONS_PER_ROUND], "answers": {}, "winner_user_id": None}
        for qs in generated
    ]

    now = _lexi_now()
    session.rounds = rounds
    flag_modified(session, "rounds")
    session.status = "active"
    session.phase = "question"
    session.round_index = 1
    session.current_question_index = 0
    session.phase_started_at = now
    session.phase_ends_at = now + timedelta(seconds=LEXI_GROUP_QUESTION_SECONDS)
    session.started_at = now
    session.updated_at = now

    # Award participation badge once challenge starts.
    for p in participants:
        uid = p.get("user_id")
        if not uid:
            continue
        ures = await db.execute(select(User).where(User.id == uid).with_for_update())
        u = ures.scalar_one_or_none()
        if not u:
            continue
        await _award_group_badge(
            user=u,
            badge_id=LEXI_GROUP_BADGE_PARTICIPANT,
            badge_label="Group Challenge Participant",
            badge_icon="👥",
            agency_id=session.agency_id,
            db=db,
        )

    await db.commit()
    await _broadcast_lexi_group_state(session)
    return {"ok": True, "state": _build_group_public_state(session, ctx.user_id)}


@app.post("/api/me/lexi-group/answer")
@limiter.limit(f"{getattr(settings, 'rate_limit_lexi_group_answer', settings.rate_limit_lexi)}/minute")
async def answer_lexi_group_question(
    request: Request,
    req: LexiGroupAnswerRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    if req.choice < 0 or req.choice > 3:
        raise HTTPException(status_code=400, detail="choice must be 0-3")
    lock_res = await db.execute(
        select(LexiGroupSession).where(LexiGroupSession.id == req.session_id).with_for_update()
    )
    session = lock_res.scalar_one_or_none()
    if not session or session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Group session not found")
    if session.status not in ("active", "finished"):
        raise HTTPException(status_code=400, detail="Group session not active")
    if session.phase != "question":
        raise HTTPException(status_code=409, detail="Question is closed")

    participants = list(session.participants or [])
    if not any((p or {}).get("user_id") == ctx.user_id for p in participants):
        raise HTTPException(status_code=403, detail="Not a participant")

    rounds = list(session.rounds or [])
    if not rounds:
        raise HTTPException(status_code=400, detail="Round data missing")
    round_idx = max(1, int(session.round_index or 1))
    q_idx = max(0, int(session.current_question_index or 0))
    if round_idx > len(rounds):
        raise HTTPException(status_code=400, detail="Invalid round index")
    round_payload = rounds[round_idx - 1]
    questions = round_payload.get("questions", []) or []
    if q_idx >= len(questions):
        raise HTTPException(status_code=400, detail="Invalid question index")
    question = questions[q_idx]

    answers = round_payload.get("answers", {}) or {}
    q_answers = answers.get(str(q_idx), {}) or {}
    if ctx.user_id not in q_answers:
        start = session.phase_started_at or _lexi_now()
        response_ms = max(0, int((_lexi_now() - start).total_seconds() * 1000))
        q_answers[ctx.user_id] = {
            "choice": req.choice,
            "correct": req.choice == int(question.get("correct", -1)),
            "response_ms": response_ms,
        }
        answers[str(q_idx)] = q_answers
        round_payload["answers"] = answers
        rounds[round_idx - 1] = round_payload
        session.rounds = rounds
        flag_modified(session, "rounds")
        session.updated_at = _lexi_now()

    changed = await _advance_lexi_group_session_locked(session, db)
    await db.commit()
    await _broadcast_lexi_group_state(session)
    return {"ok": True, "advanced": changed, "state": _build_group_public_state(session, ctx.user_id)}


@app.post("/api/me/lexi-group/feedback-ready")
@limiter.limit(f"{getattr(settings, 'rate_limit_lexi_group_feedback_ready', settings.rate_limit_lexi)}/minute")
async def lexi_group_feedback_ready(
    request: Request,
    req: LexiGroupFeedbackReadyRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    lock_res = await db.execute(
        select(LexiGroupSession).where(LexiGroupSession.id == req.session_id).with_for_update()
    )
    session = lock_res.scalar_one_or_none()
    if not session or session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Group session not found")
    if not any((p or {}).get("user_id") == ctx.user_id for p in (session.participants or [])):
        raise HTTPException(status_code=403, detail="Not a participant")
    if session.phase != "feedback":
        raise HTTPException(status_code=409, detail="Feedback phase is closed")

    rounds = list(session.rounds or [])
    round_idx = max(1, int(session.round_index or 1))
    q_idx = max(0, int(session.current_question_index or 0))
    if 0 <= round_idx - 1 < len(rounds):
        round_payload = rounds[round_idx - 1]
        feedback_ready = round_payload.get("feedback_ready", {}) or {}
        q_ready = feedback_ready.get(str(q_idx), {}) or {}
        q_ready[ctx.user_id] = True
        feedback_ready[str(q_idx)] = q_ready
        round_payload["feedback_ready"] = feedback_ready
        rounds[round_idx - 1] = round_payload
        session.rounds = rounds
        flag_modified(session, "rounds")
        session.updated_at = _lexi_now()

    changed = await _advance_lexi_group_session_locked(session, db)
    await db.commit()
    await _broadcast_lexi_group_state(session)
    return {"ok": True, "advanced": changed, "state": _build_group_public_state(session, ctx.user_id)}


@app.post("/api/me/lexi-group/next-round")
@limiter.limit(f"{getattr(settings, 'rate_limit_lexi_group_next_round', settings.rate_limit_lexi)}/minute")
async def next_lexi_group_round(
    request: Request,
    req: LexiGroupSessionRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    lock_res = await db.execute(
        select(LexiGroupSession).where(LexiGroupSession.id == req.session_id).with_for_update()
    )
    session = lock_res.scalar_one_or_none()
    if not session or session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Group session not found")
    if not any((p or {}).get("user_id") == ctx.user_id for p in (session.participants or [])):
        raise HTTPException(status_code=403, detail="Not a participant")
    if session.phase != "round_results":
        raise HTTPException(status_code=409, detail="Round results phase is closed")

    rounds = list(session.rounds or [])
    round_idx = max(1, int(session.round_index or 1))
    if 0 <= round_idx - 1 < len(rounds):
        round_payload = rounds[round_idx - 1]
        next_ready = round_payload.get("next_round_ready", {}) or {}
        next_ready[ctx.user_id] = True
        round_payload["next_round_ready"] = next_ready
        rounds[round_idx - 1] = round_payload
        session.rounds = rounds
        flag_modified(session, "rounds")

    now = _lexi_now()
    if not session.phase_ends_at:
        session.phase_started_at = now
        session.phase_ends_at = now + timedelta(seconds=LEXI_GROUP_RESULTS_READY_SECONDS)
    session.updated_at = now
    changed = await _advance_lexi_group_session_locked(session, db)
    await db.commit()
    await _broadcast_lexi_group_state(session)
    return {"ok": True, "advanced": changed, "state": _build_group_public_state(session, ctx.user_id)}


@app.post("/api/me/lexi-group/leave")
@limiter.limit(f"{getattr(settings, 'rate_limit_lexi_group_join', settings.rate_limit_lexi)}/minute")
async def leave_lexi_group(
    request: Request,
    req: LexiGroupSessionRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    lock_res = await db.execute(
        select(LexiGroupSession).where(LexiGroupSession.id == req.session_id).with_for_update()
    )
    session = lock_res.scalar_one_or_none()
    if not session or session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Group session not found")

    participants = list(session.participants or [])
    was_participant = any((p or {}).get("user_id") == ctx.user_id for p in participants)
    if not was_participant:
        # Idempotent leave
        return {"ok": True, "advanced": False}

    participants = [p for p in participants if (p or {}).get("user_id") != ctx.user_id]
    session.participants = participants
    flag_modified(session, "participants")

    rounds = list(session.rounds or [])
    round_idx = max(1, int(session.round_index or 1))
    q_idx = max(0, int(session.current_question_index or 0))
    if 0 <= round_idx - 1 < len(rounds):
        round_payload = rounds[round_idx - 1]
        if session.phase == "feedback":
            feedback_ready = round_payload.get("feedback_ready", {}) or {}
            q_ready = feedback_ready.get(str(q_idx), {}) or {}
            q_ready.pop(ctx.user_id, None)
            feedback_ready[str(q_idx)] = q_ready
            round_payload["feedback_ready"] = feedback_ready
        if session.phase == "round_results":
            next_ready = round_payload.get("next_round_ready", {}) or {}
            next_ready.pop(ctx.user_id, None)
            round_payload["next_round_ready"] = next_ready
        rounds[round_idx - 1] = round_payload
        session.rounds = rounds
        flag_modified(session, "rounds")

    # Reassign host if needed.
    if session.host_user_id == ctx.user_id:
        session.host_user_id = participants[0].get("user_id") if participants else session.host_user_id

    now = _lexi_now()
    advanced = False
    if not participants:
        session.status = "finished"
        session.phase = "final_results"
        session.phase_started_at = now
        session.phase_ends_at = None
        session.ended_at = now
    else:
        advanced = await _advance_lexi_group_session_locked(session, db)
    session.updated_at = now

    await db.commit()
    await _broadcast_lexi_group_state(session)
    return {"ok": True, "advanced": advanced}


@app.post("/api/me/lexi-group/kick")
@limiter.limit(f"{getattr(settings, 'rate_limit_lexi_group_kick', settings.rate_limit_lexi)}/minute")
async def kick_lexi_group_participant(
    request: Request,
    req: LexiGroupKickRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    lock_res = await db.execute(
        select(LexiGroupSession).where(LexiGroupSession.id == req.session_id).with_for_update()
    )
    session = lock_res.scalar_one_or_none()
    if not session or session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Group session not found")
    if session.host_user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="Only host can remove participants")
    if req.user_id == ctx.user_id:
        raise HTTPException(status_code=400, detail="Host cannot remove self")

    participants = list(session.participants or [])
    if not any((p or {}).get("user_id") == req.user_id for p in participants):
        raise HTTPException(status_code=404, detail="Participant not found")

    participants = [p for p in participants if (p or {}).get("user_id") != req.user_id]
    session.participants = participants
    flag_modified(session, "participants")

    rounds = list(session.rounds or [])
    round_idx = max(1, int(session.round_index or 1))
    q_idx = max(0, int(session.current_question_index or 0))
    if 0 <= round_idx - 1 < len(rounds):
        round_payload = rounds[round_idx - 1]
        if session.phase == "feedback":
            feedback_ready = round_payload.get("feedback_ready", {}) or {}
            q_ready = feedback_ready.get(str(q_idx), {}) or {}
            q_ready.pop(req.user_id, None)
            feedback_ready[str(q_idx)] = q_ready
            round_payload["feedback_ready"] = feedback_ready
        if session.phase == "round_results":
            next_ready = round_payload.get("next_round_ready", {}) or {}
            next_ready.pop(req.user_id, None)
            round_payload["next_round_ready"] = next_ready
        rounds[round_idx - 1] = round_payload
        session.rounds = rounds
        flag_modified(session, "rounds")

    now = _lexi_now()
    advanced = False
    if not participants:
        session.status = "finished"
        session.phase = "final_results"
        session.phase_started_at = now
        session.phase_ends_at = None
        session.ended_at = now
    elif session.status == "active":
        advanced = await _advance_lexi_group_session_locked(session, db)
    session.updated_at = now

    await db.commit()
    await _broadcast_lexi_group_state(session)
    return {"ok": True, "advanced": advanced, "state": _build_group_public_state(session, ctx.user_id)}


@app.post("/api/me/lexi-group/end")
@limiter.limit(f"{getattr(settings, 'rate_limit_lexi_group_end', settings.rate_limit_lexi)}/minute")
async def end_lexi_group(
    request: Request,
    req: LexiGroupSessionRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    lock_res = await db.execute(
        select(LexiGroupSession).where(LexiGroupSession.id == req.session_id).with_for_update()
    )
    session = lock_res.scalar_one_or_none()
    if not session or session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=404, detail="Group session not found")
    if session.host_user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="Only host can end this challenge")

    now = _lexi_now()
    session.status = "finished"
    session.phase = "final_results"
    session.phase_started_at = now
    session.phase_ends_at = None
    session.ended_at = now
    session.updated_at = now

    await db.commit()
    await _broadcast_lexi_group_state(session)
    return {"ok": True, "state": _build_group_public_state(session, ctx.user_id)}


# ── Toy chest constants ───────────────────────────────────────────────────────

# Probability a standard eligible completion yields a Common toy (0.0–1.0)
_TOY_COMMON_DROP_RATE  = 0.40
# Probability a Mastery+no-hint run yields an Epic (on top of the guaranteed Rare)
_TOY_EPIC_DROP_RATE    = 0.25
# Pity thresholds — guarantee on the Nth attempt without a drop
_PITY_COMMON_THRESHOLD = 3
_PITY_RARE_THRESHOLD   = 6


async def _process_toy_grants(
    session: "SimSession",
    user: "User",
    is_first_time_clear: bool,
    is_personal_best: bool,
    anti_farm: bool,
    db: "AsyncSession",
    award_duplicate_treats: bool = True,
) -> list[dict]:
    """Evaluate toy drop eligibility for a completed full-scenario session and
    execute all grants atomically within the caller's open transaction.

    Returns a list of grant result dicts to be injected into the debrief response:
        [{"toy_id", "display_name", "rarity", "image_key",
          "is_duplicate", "treats_awarded", "grant_source"}, ...]
    """
    results: list[dict] = []

    # ── 1. Find the toy category for this scenario ────────────────────────────
    try:
        scenario_data = load_scenario(session.scenario_id)
        scenario_cat  = scenario_data.get("category", "")
    except Exception:
        scenario_cat = ""

    cat_result = await db.execute(
        select(ToyCategory).where(
            ToyCategory.scenario_categories.contains([scenario_cat])
        )
    )
    category: ToyCategory | None = cat_result.scalar_one_or_none()

    # If this scenario's category isn't mapped to a toy district, skip silently.
    if category is None:
        return []

    # ── 2. Mastery check (assessment_score normalized to its assessment max) ──
    a_score   = session.assessment_score or 0
    a_max     = _assessment_max_from_subscores((session.narrative_data or {}).get("subscores"))
    threshold = category.default_mastery_threshold  # e.g. 85 (%)
    # Allow scenario-level override stored in scenario JSON metadata
    scenario_override = scenario_data.get("mastery_threshold_override") if scenario_cat else None
    if scenario_override is not None:
        threshold = int(scenario_override)
    is_mastery = (a_score / float(a_max) * 100) >= threshold

    # ── 3. No-hint check ──────────────────────────────────────────────────────
    no_hint = (session.treats_spent or 0) == 0

    # ── 4. Determine which toy to attempt to grant ───────────────────────────
    #   Priority:  Epic > Rare > Common
    #   Rules:
    #     • first_time_clear          → guaranteed Common (no further rolls)
    #     • mastery + no_hint         → roll for Epic; guaranteed Rare on miss
    #     • mastery only              → guaranteed Rare
    #     • personal_best (non-first) → bonus Common roll
    #     • standard eligible (non-farm) → standard Common roll
    #   Only one toy is granted per session (highest rarity wins).

    grant_source: str | None = None
    target_rarity: str | None = None

    if is_first_time_clear:
        grant_source  = "first_clear"
        target_rarity = "common"
    elif is_mastery:
        if no_hint and random.random() < _TOY_EPIC_DROP_RATE:
            grant_source  = "epic_attempt"
            target_rarity = "epic"
        else:
            grant_source  = "mastery"
            target_rarity = "rare"
    elif not anti_farm:
        # Check pity timers before rolling RNG
        pity = await _get_or_create_pity(user.id, category.id, db)

        # Rare pity: guarantee on Nth attempt without Rare
        if pity.attempts_since_last_rare >= _PITY_RARE_THRESHOLD:
            grant_source  = "pity_rare"
            target_rarity = "rare"
        # Common pity: guarantee on Nth attempt without any drop
        elif pity.attempts_since_last_common >= _PITY_COMMON_THRESHOLD:
            grant_source  = "pity_common"
            target_rarity = "common"
        elif is_personal_best and random.random() < _TOY_COMMON_DROP_RATE:
            grant_source  = "personal_best"
            target_rarity = "common"
        elif random.random() < _TOY_COMMON_DROP_RATE:
            grant_source  = "standard"
            target_rarity = "common"

    # ── 5. Pick a toy of the target rarity from the category pool ────────────
    if target_rarity is None:
        # No drop this run — increment pity counters and return
        await _increment_pity(user.id, category.id, db)
        return []

    toy = await _pick_random_toy(category.id, target_rarity, db)
    if toy is None:
        # No toys of that rarity exist yet — treat as no-drop
        await _increment_pity(user.id, category.id, db)
        return []

    # ── 6. Check for duplicate ────────────────────────────────────────────────
    owned = await db.execute(
        select(UserToy).where(
            UserToy.user_id == user.id,
            UserToy.toy_id  == toy.id,
        )
    )
    is_duplicate = owned.scalar_one_or_none() is not None
    treats_awarded = 0

    if is_duplicate and award_duplicate_treats:
        treats_awarded = toy.duplicate_treat_value
        user.treats = (user.treats or 0) + treats_awarded
    else:
        if not is_duplicate:
            db.add(UserToy(
                user_id      = user.id,
                toy_id       = toy.id,
                grant_source = grant_source,
            ))

    # ── 7. Write immutable audit log ─────────────────────────────────────────
    db.add(ToyGrantLog(
        user_id        = user.id,
        toy_id         = toy.id,
        session_id     = session.id,
        grant_source   = grant_source,
        is_duplicate   = is_duplicate,
        treats_awarded = treats_awarded,
    ))

    # ── 8. Cascade pity reset ─────────────────────────────────────────────────
    await _cascade_pity_reset(user.id, category.id, target_rarity, db)

    results.append({
        "toy_id":       toy.id,
        "display_name": toy.display_name,
        "rarity":       toy.rarity,
        "image_key":    toy.image_key,
        "is_duplicate": is_duplicate,
        "treats_awarded": treats_awarded,
        "grant_source": grant_source,
    })
    return results


async def _get_or_create_pity(user_id: str, category_id: str, db: "AsyncSession") -> UserPityCounter:
    result = await db.execute(
        select(UserPityCounter).where(
            UserPityCounter.user_id     == user_id,
            UserPityCounter.category_id == category_id,
        ).with_for_update()
    )
    pity = result.scalar_one_or_none()
    if pity is None:
        pity = UserPityCounter(user_id=user_id, category_id=category_id)
        db.add(pity)
        await db.flush()
    return pity


async def _increment_pity(user_id: str, category_id: str, db: "AsyncSession") -> None:
    """Increment all pity counters — no toy was granted this run."""
    pity = await _get_or_create_pity(user_id, category_id, db)
    pity.attempts_since_last_common += 1
    pity.attempts_since_last_rare   += 1
    pity.attempts_since_last_epic   += 1


async def _cascade_pity_reset(
    user_id: str, category_id: str, granted_rarity: str, db: "AsyncSession"
) -> None:
    """Reset pity counters at the granted rarity tier and all lower tiers.
    Applies to both RNG grants AND pity-triggered guarantees per spec."""
    pity = await _get_or_create_pity(user_id, category_id, db)
    # Always reset Common when any toy drops
    pity.attempts_since_last_common = 0
    if granted_rarity in ("rare", "epic"):
        pity.attempts_since_last_rare = 0
    if granted_rarity == "epic":
        pity.attempts_since_last_epic = 0


async def _pick_random_toy(category_id: str, rarity: str, db: "AsyncSession") -> "Toy | None":
    """Return a random active toy of the given rarity from the category pool."""
    result = await db.execute(
        select(Toy).where(
            Toy.category_id == category_id,
            Toy.rarity      == rarity,
            Toy.is_active   == True,
        )
    )
    pool = result.scalars().all()
    return random.choice(pool) if pool else None


@app.post("/api/me/progress")
async def post_session_progress(
    req: SessionProgressRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Compute and record all session awards server-side from DB state.

    The client sends only session_id + elapsed_min + is_drill.
    All XP/badge/treat values are derived here and cannot be tampered with.
    Idempotent: repeated calls return the same result without re-awarding.
    """
    # Lock the session row to prevent concurrent double-award
    sess_result = await db.execute(
        select(SimSession).where(SimSession.id == req.session_id).with_for_update()
    )
    session = sess_result.scalar_one_or_none()
    if not session or session.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    # ── Debrief-only fast path ────────────────────────────────────────────────
    # Called after the debrief modal closes. Records:
    #   1. Capped CE time for the debrief review phase (source_id dedup).
    #   2. Total session active time (launch → close, 5-min idle pause) for
    #      challenge time tracking. Tagged with scenario_id so challenge
    #      progress queries can filter by scenario set.
    if req.debrief_only:
        _is_drill = req.is_drill or bool((session.narrative_data or {}).get("drill"))
        any_change = False

        debrief_sec = max(0, int(req.debrief_elapsed_sec or 0))
        if debrief_sec > 0:
            debrief_cap = (CE_FEEDBACK_REVIEW_CAP_SECONDS if _is_drill
                           else CE_SCENARIO_DEBRIEF_CAP_SECONDS)
            source_key = f"{session.id}:debrief"
            existing = await db.execute(
                select(CeTimeLog).where(
                    CeTimeLog.source_id == source_key,
                    CeTimeLog.user_id   == ctx.user_id,
                )
            )
            if not existing.scalar_one_or_none():
                _record_ce_time(
                    db, user_id=ctx.user_id, activity_type="debrief",
                    seconds=min(debrief_sec, debrief_cap),
                    source_id=source_key, scenario_id=session.scenario_id,
                )
                any_change = True

        session_active = max(0, int(req.session_active_sec or 0))
        if session_active > 0:
            source_key_session = f"{session.id}:session"
            existing_s = await db.execute(
                select(CeTimeLog).where(
                    CeTimeLog.source_id == source_key_session,
                    CeTimeLog.user_id   == ctx.user_id,
                )
            )
            if not existing_s.scalar_one_or_none():
                activity = "drill" if _is_drill else "scenario"
                _record_ce_time(
                    db, user_id=ctx.user_id, activity_type=activity,
                    seconds=min(session_active, _CE_SESSION_MAX_SECONDS),
                    source_id=source_key_session, scenario_id=session.scenario_id,
                )
                any_change = True

        if any_change:
            user = await db.get(User, ctx.user_id)
            if user:
                await _complete_active_repeatable_challenges(
                    user=user,
                    agency_id=session.agency_id,
                    db=db,
                )
            await db.commit()
        return {"ok": True}

    # ── Idempotency guard (checked inside the row lock) ───────────────────────
    if session.xp_earned is not None:
        return {
            "ok":               True,
            "xp_gross":         session.xp_gross or 0,
            "xp_earned":        session.xp_earned or 0,
            "treats_earned":    session.treats_earned or 0,
            "new_badges":       session.new_badges or [],
            "challenge_badges": [],
            "toy_grants":       [],  # already processed; client uses debrief for the reveal
        }

    score = session.score

    # Canonicalize drill from request OR from stored narrative_data
    is_drill = req.is_drill or bool((session.narrative_data or {}).get("drill"))

    user_result = await db.execute(
        select(User).where(User.id == ctx.user_id).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    xp_before = user.xp or 0
    new_badges: list[str] = []
    challenge_badges: list[str] = []

    is_random_call = session.session_type == "random_call"

    if is_drill:
        # Drill path: separate XP ledger/caps, perfect-run treats, no badges/challenges.
        # Mirrors full-scenario best-attempt behavior, but only against prior drills.
        xp_gross = _xp_for_score(score) // 2
        xp_gross = min(xp_gross, DRILL_PER_RUN_MAX_XP, DRILL_DAILY_CAP_XP)

        # Best prior DRILL attempt delta (agency + scenario scoped)
        prior_result = await db.execute(
            select(SimSession.xp_gross, SimSession.narrative_data).where(
                SimSession.user_id == ctx.user_id,
                SimSession.scenario_id == session.scenario_id,
                SimSession.agency_id == session.agency_id,
                SimSession.ended_at.isnot(None),
                SimSession.id != session.id,
                SimSession.xp_gross.isnot(None),
            )
        )
        best_prior_drill_xp = max(
            (
                (row[0] or 0)
                for row in prior_result.all()
                if bool((row[1] or {}).get("drill"))
            ),
            default=0,
        )
        xp_candidate = max(0, xp_gross - best_prior_drill_xp)

        xp_today, runs_today, _paid_ids = _ensure_drill_ledger_today(user)
        remaining = max(0, DRILL_DAILY_CAP_XP - xp_today)
        xp_earned = min(xp_candidate, remaining)

        user.drill_xp_today = xp_today + xp_earned
        user.drill_runs_today = runs_today + 1

        treats_earned = 1 if (score or 0) >= 100 and xp_earned > 0 else 0
        user.treats = (user.treats if user.treats is not None else 3) + treats_earned
        assessment_xp = None
        narrative_xp  = None
        toy_grants    = []
        user.xp = xp_before + xp_earned

    elif is_random_call:
        # ── Random Call path: scaled-down XP, daily cap, no badges/treats ─────
        _assessment_max = _assessment_max_from_subscores((session.narrative_data or {}).get("subscores"))
        a_xp = _xp_for_assessment(session.assessment_score, _assessment_max, RC_ASSESSMENT_MAX_XP)
        n_xp = _xp_for_narrative(session.narrative_score,   RC_NARRATIVE_MAX_XP)
        xp_gross = a_xp + n_xp

        # Best prior RC attempt delta (agency + scenario + session_type scoped)
        prior_rc_result = await db.execute(
            select(SimSession.xp_gross).where(
                SimSession.user_id     == ctx.user_id,
                SimSession.scenario_id == session.scenario_id,
                SimSession.agency_id   == session.agency_id,
                SimSession.session_type == "random_call",
                SimSession.ended_at.isnot(None),
                SimSession.id          != session.id,
                SimSession.xp_gross.isnot(None),
            )
        )
        best_prior_rc_xp = max((r[0] for r in prior_rc_result.all()), default=0)
        xp_candidate = max(0, xp_gross - best_prior_rc_xp)

        # Daily RC cap
        today = date.today()
        if (user.rc_xp_day or date.min) < today:
            user.rc_xp_today = 0
            user.rc_xp_day   = today
        rc_xp_today = user.rc_xp_today or 0
        remaining   = max(0, RC_DAILY_CAP_XP - rc_xp_today)
        xp_earned   = min(xp_candidate, remaining)

        user.rc_xp_today = rc_xp_today + xp_earned
        user.rc_xp_day   = today

        treats_earned = 0
        assessment_xp = a_xp
        narrative_xp  = n_xp
        toy_grants    = []
        session.assessment_xp = a_xp
        session.narrative_xp  = n_xp
        user.xp = xp_before + xp_earned

    else:
        # ── Full scenario path ────────────────────────────────────────────────
        _assessment_max = _assessment_max_from_subscores((session.narrative_data or {}).get("subscores"))
        a_xp = _xp_for_assessment(session.assessment_score, _assessment_max, 500)
        n_xp = _xp_for_narrative(session.narrative_score,   100)
        xp_gross = a_xp + n_xp

        # ── Best-attempt delta (server-side, agency-scoped) ───────────────────
        prior_result = await db.execute(
            select(SimSession.xp_gross).where(
                SimSession.user_id     == ctx.user_id,
                SimSession.scenario_id == session.scenario_id,
                SimSession.agency_id   == session.agency_id,
                SimSession.ended_at.isnot(None),
                SimSession.id          != session.id,
                SimSession.xp_gross.isnot(None),
            )
        )
        best_prior_xp = max((r[0] for r in prior_result.all()), default=0)
        xp_earned = max(0, xp_gross - best_prior_xp)

        assessment_xp = a_xp
        narrative_xp  = n_xp
        session.assessment_xp = a_xp
        session.narrative_xp  = n_xp

        try:
            scenario_data = load_scenario(session.scenario_id)
            category = scenario_data.get("category", "")
        except Exception:
            category = ""

        is_peds_medical = category == "pediatric_medical"
        is_peds_trauma  = category == "pediatric_trauma"

        # Update peds counters (passing assessment only)
        critical_failure = _session_critical_failure(session)
        passing = (
            ((session.assessment_score or 0) / float(_assessment_max)) >= PASSING_PCT
            and not critical_failure
        )
        if is_peds_medical and passing:
            user.peds_count = (user.peds_count or 0) + 1
        if is_peds_trauma and passing:
            user.peds_trauma_count = (user.peds_trauma_count or 0) + 1

        # ── Prior session count (for badge thresholds) ────────────────────────
        count_result = await db.execute(
            select(func.count()).select_from(SimSession).where(
                SimSession.user_id   == user.id,
                SimSession.ended_at.isnot(None),
                SimSession.id        != session.id,
            )
        )
        prior_session_count  = count_result.scalar() or 0
        total_sessions_after = prior_session_count + 1

        # ── System badges ──────────────────────────────────────────────────────
        existing_badges = set(user.badges or [])
        _SYSTEM_BADGE_META = {b["id"]: (b["name"], b["icon"]) for b in _SYSTEM_BADGE_DEFS}

        def maybe_badge(badge_id: str, condition: bool) -> None:
            if condition and badge_id not in existing_badges:
                existing_badges.add(badge_id)
                new_badges.append(badge_id)

        maybe_badge("first_alarm",    prior_session_count == 0)
        maybe_badge("honor_roll",     not critical_failure and (session.assessment_score or 0) >= round(_assessment_max * 0.90))
        maybe_badge("perfect_run",    not critical_failure and (session.assessment_score or 0) >= _assessment_max)
        maybe_badge("speed_demon",    req.elapsed_min > 0 and req.elapsed_min < 8)
        maybe_badge("frequent_flyer", total_sessions_after >= 5)
        maybe_badge("road_warrior",   total_sessions_after >= 10)
        maybe_badge(
            "peds_champion",
            await _pilot_pediatric_champion_complete(
                user.id,
                session.agency_id,
                db,
                current_session=session,
            ),
        )

        for badge_id in new_badges:
            meta = _SYSTEM_BADGE_META.get(badge_id)
            if meta:
                await _write_feed_event(session.agency_id, user, "badge", meta[0], meta[1], db)

        user.badges = list(existing_badges)

        # ── Level and treats ──────────────────────────────────────────────────
        user.xp = xp_before + xp_earned
        levels_gained = max(0, _level_index(user.xp) - _level_index(xp_before))
        is_perfect_scenario = not critical_failure and (session.assessment_score or 0) >= _assessment_max
        treats_earned = 1 if is_perfect_scenario else 0
        user.treats = (user.treats if user.treats is not None else 3) + treats_earned
        challenge_badges = await _check_and_award_challenges(user, session.agency_id, db)

        # ── Toy grants (full-scenario only) ───────────────────────────────────
        # is_first_time_clear: no prior completed scenario sessions for this scenario_id
        is_first_time_clear = (best_prior_xp == 0)
        is_personal_best    = (xp_gross > best_prior_xp) and not is_first_time_clear

        # Anti-farming: same scenario, same calendar day, score did not improve
        today = date.today()
        same_day_result = await db.execute(
            select(func.max(SimSession.assessment_score)).where(
                SimSession.user_id     == ctx.user_id,
                SimSession.scenario_id == session.scenario_id,
                SimSession.ended_at.isnot(None),
                SimSession.id          != session.id,
                func.date(SimSession.ended_at) == today,
            )
        )
        best_same_day_score = same_day_result.scalar() or 0
        anti_farm = (
            best_same_day_score > 0                          # has a prior run today
            and (session.assessment_score or 0) <= best_same_day_score  # score didn't improve
        )

        toy_grants = await _process_toy_grants(
            session           = session,
            user              = user,
            is_first_time_clear = is_first_time_clear,
            is_personal_best  = is_personal_best,
            anti_farm         = anti_farm,
            db                = db,
            award_duplicate_treats = is_perfect_scenario,
        )

        # Any duplicate treat payouts were already added to user.treats inside
        # _process_toy_grants — add them to treats_earned so the client knows.
        treats_from_toys = sum(g["treats_awarded"] for g in toy_grants)
        treats_earned   += treats_from_toys
        # user.treats already incremented inside _process_toy_grants for duplicates

    # ── Stamp session record ──────────────────────────────────────────────────
    session.xp_gross      = xp_gross
    session.xp_earned     = xp_earned
    session.treats_earned = treats_earned
    session.new_badges    = new_badges
    session.elapsed_min   = req.elapsed_min

    # ── CE time — active engagement + per-phase capped debrief ──────────────────
    # Orientation sessions are excluded: _complete_orientation_session awards a
    # fixed block. Debrief time is only credited when the frontend reports it
    # explicitly (debrief_elapsed_sec > 0) and is capped at the phase constant.
    # When debrief_elapsed_sec is not provided (older clients), full wall-clock
    # is recorded under the activity type — unchanged from prior behavior.
    _is_orient = bool((session.narrative_data or {}).get("is_orientation"))
    if session.ended_at and session.start_time and not _is_orient:
        elapsed     = (session.ended_at - session.start_time).total_seconds()
        ce_type     = "drill" if is_drill else "scenario"
        debrief_sec = max(0, int(req.debrief_elapsed_sec or 0))

        if debrief_sec > 0:
            # Frontend-instrumented path: record active and debrief separately.
            debrief_cap = (CE_FEEDBACK_REVIEW_CAP_SECONDS if is_drill
                           else CE_SCENARIO_DEBRIEF_CAP_SECONDS)
            debrief_ce  = min(debrief_sec, debrief_cap)
            active_ce   = max(0, int(elapsed) - debrief_sec)
            if active_ce > 0:
                _record_ce_time(
                    db, user_id=ctx.user_id, activity_type=ce_type,
                    seconds=active_ce, source_id=session.id,
                    scenario_id=session.scenario_id,
                )
            if debrief_ce > 0:
                _record_ce_time(
                    db, user_id=ctx.user_id, activity_type="debrief",
                    seconds=debrief_ce, source_id=f"{session.id}:debrief",
                    scenario_id=session.scenario_id,
                )
        else:
            # Non-instrumented path: record full wall-clock under activity type.
            _record_ce_time(
                db, user_id=ctx.user_id, activity_type=ce_type,
                seconds=elapsed, source_id=session.id,
                scenario_id=session.scenario_id,
            )

    # ── Level-up feed event ───────────────────────────────────────────────────
    await _complete_active_repeatable_challenges(
        user=user,
        agency_id=session.agency_id,
        db=db,
    )
    await _maybe_write_level_up(session.agency_id, user, xp_before, user.xp, db)

    await db.commit()
    return {
        "ok":               True,
        "xp_gross":         xp_gross,
        "xp_earned":        xp_earned,
        "assessment_xp":    assessment_xp,
        "narrative_xp":     narrative_xp,
        "treats_earned":    treats_earned,
        "new_badges":       new_badges,
        "challenge_badges": challenge_badges,
        "toy_grants":       toy_grants,
    }


@app.get("/api/me/toys")
async def get_my_toys(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return the user's toy collection grouped by category and series, plus
    'new_arrivals' flags for series the user hasn't dismissed yet.

    Response shape:
    {
      "categories": [
        {
          "id", "name", "display_name",
          "series": [
            {
              "series_tag", "display_name", "published_at", "is_new_arrival",
              "toys": [
                {"toy_id", "display_name", "rarity", "image_key", "owned",
                 "is_earn_only", "shop_price"}
              ]
            }
          ]
        }
      ]
    }
    """
    # Fetch all toy categories
    cats_result = await db.execute(select(ToyCategory).order_by(ToyCategory.display_name))
    categories  = cats_result.scalars().all()

    # Fetch all active toys in one query
    toys_result = await db.execute(
        select(Toy).where(Toy.is_active == True).order_by(Toy.series_tag, Toy.rarity, Toy.display_name)
    )
    all_toys = toys_result.scalars().all()

    # Fetch all toys this user owns
    owned_result = await db.execute(
        select(UserToy.toy_id).where(UserToy.user_id == ctx.user_id)
    )
    owned_ids = {row[0] for row in owned_result.all()}

    # Fetch all series
    series_result = await db.execute(select(ToySeries).order_by(ToySeries.published_at))
    all_series    = series_result.scalars().all()

    # Fetch series the user has already viewed (badge dismissed)
    viewed_result = await db.execute(
        select(UserSeriesView.series_tag).where(UserSeriesView.user_id == ctx.user_id)
    )
    viewed_tags = {row[0] for row in viewed_result.all()}

    # User's last_login for "new arrival" detection
    user_result = await db.execute(select(User.last_login).where(User.id == ctx.user_id))
    last_login  = user_result.scalar_one_or_none()

    # Build category → series → toys tree
    series_map = {s.series_tag: s for s in all_series}
    toys_by_cat_series: dict[str, dict[str, list]] = {}
    for toy in all_toys:
        toys_by_cat_series.setdefault(toy.category_id, {}).setdefault(toy.series_tag, []).append(toy)

    output = []
    for cat in categories:
        cat_series_toys = toys_by_cat_series.get(cat.id, {})
        series_out = []
        for series_tag, toys in sorted(cat_series_toys.items()):
            s = series_map.get(series_tag)
            if not s:
                continue
            is_new_arrival = (
                series_tag not in viewed_tags
                and s.published_at is not None
                and (last_login is None or s.published_at > last_login)
            )
            toys_out = [
                {
                    "toy_id":       t.id,
                    "display_name": t.display_name,
                    "rarity":       t.rarity,
                    "image_key":    t.image_key,
                    "owned":        t.id in owned_ids,
                    "is_earn_only": t.is_earn_only,
                    "shop_price":   t.shop_price,
                }
                for t in sorted(toys, key=lambda x: ("common", "rare", "epic").index(x.rarity))
            ]
            series_out.append({
                "series_tag":    series_tag,
                "display_name":  s.display_name,
                "published_at":  s.published_at.isoformat() if s.published_at else None,
                "is_new_arrival": is_new_arrival,
                "toys":          toys_out,
            })
        output.append({
            "id":           cat.id,
            "name":         cat.name,
            "display_name": cat.display_name,
            "series":       series_out,
        })

    return {"categories": output}


class SeriesViewRequest(BaseModel):
    pass  # body unused; series_tag comes from the path


@app.post("/api/me/toys/series/{series_tag}/view")
async def mark_series_viewed(
    series_tag: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Dismiss the 'New Arrivals' badge for a series by recording that the user
    has opened the shelf.  Idempotent — safe to call multiple times."""
    # Verify the series exists
    series_result = await db.execute(
        select(ToySeries).where(ToySeries.series_tag == series_tag)
    )
    if not series_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Series not found")

    # Upsert the view record (ON CONFLICT DO NOTHING via try/except on unique constraint)
    existing = await db.execute(
        select(UserSeriesView).where(
            UserSeriesView.user_id    == ctx.user_id,
            UserSeriesView.series_tag == series_tag,
        )
    )
    if not existing.scalar_one_or_none():
        db.add(UserSeriesView(user_id=ctx.user_id, series_tag=series_tag))
        await db.commit()

    return {"ok": True, "series_tag": series_tag}


@app.get("/api/toys/shop")
async def get_toy_shop(
    district: Optional[str] = None,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return purchasable toys with ownership status for the current user.
    Pass ?district=<category_name> (e.g. puppy_park) to scope to Scout's
    location on the map.  Omit for the full cross-district inventory."""
    completed_maps_result = await db.execute(
        select(PedsMapProgress.map_id).where(PedsMapProgress.user_id == ctx.user_id)
    )
    completed_map_ids = {row[0] for row in completed_maps_result.all()}

    query = (
        select(Toy, ToyCategory).join(ToyCategory, Toy.category_id == ToyCategory.id)
        .where(
            Toy.is_active    == True,
            Toy.is_earn_only == False,
            Toy.shop_price.isnot(None),
            or_(Toy.map_gate_id == None, Toy.map_gate_id.in_(completed_map_ids)),
        )
    )
    if district:
        query = query.where(ToyCategory.name == district)
    query = query.order_by(ToyCategory.display_name, Toy.rarity, Toy.display_name)

    shop_result = await db.execute(query)
    rows = shop_result.all()

    owned_result = await db.execute(
        select(UserToy.toy_id).where(UserToy.user_id == ctx.user_id)
    )
    owned_ids = {row[0] for row in owned_result.all()}

    user_result = await db.execute(
        select(User.treats).where(User.id == ctx.user_id)
    )
    treats = user_result.scalar_one_or_none() or 0

    items = [
        {
            "toy_id":       toy.id,
            "display_name": toy.display_name,
            "rarity":       toy.rarity,
            "image_key":    toy.image_key,
            "shop_price":   toy.shop_price,
            "category":     cat.display_name,
            "district":     cat.name,
            "owned":        toy.id in owned_ids,
        }
        for toy, cat in rows
    ]
    return {"items": items, "treats": treats}


class PurchaseToyRequest(BaseModel):
    toy_id: str


@app.post("/api/me/toys/purchase")
async def purchase_toy(
    req: PurchaseToyRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Atomically deduct Treats and grant a shop toy.  Earn-only (Epic) toys
    cannot be purchased.  Purchasing a duplicate converts to Treats per the
    toy's duplicate_treat_value (unusual but handled for consistency)."""
    # Lock user row first to prevent race conditions on treat balance
    user_result = await db.execute(
        select(User).where(User.id == ctx.user_id).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    toy_result = await db.execute(
        select(Toy).where(Toy.id == req.toy_id, Toy.is_active == True)
    )
    toy = toy_result.scalar_one_or_none()
    if not toy:
        raise HTTPException(status_code=404, detail="Toy not found")
    if toy.is_earn_only:
        raise HTTPException(status_code=400, detail="This toy can only be earned in-game.")
    if toy.shop_price is None:
        raise HTTPException(status_code=400, detail="This toy is not available in the shop.")

    current_treats = user.treats if user.treats is not None else 0
    if current_treats < toy.shop_price:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough treats — need {toy.shop_price}, you have {current_treats}."
        )

    # Check ownership (duplicate path)
    owned_result = await db.execute(
        select(UserToy).where(
            UserToy.user_id == ctx.user_id,
            UserToy.toy_id  == req.toy_id,
        )
    )
    is_duplicate   = owned_result.scalar_one_or_none() is not None
    treats_awarded = 0

    user.treats = current_treats - toy.shop_price

    if is_duplicate:
        treats_awarded = toy.duplicate_treat_value
        user.treats   += treats_awarded
    else:
        db.add(UserToy(
            user_id      = ctx.user_id,
            toy_id       = toy.id,
            grant_source = "shop",
        ))

    db.add(ToyGrantLog(
        user_id        = ctx.user_id,
        toy_id         = toy.id,
        session_id     = None,
        grant_source   = "shop",
        is_duplicate   = is_duplicate,
        treats_awarded = treats_awarded,
    ))

    await db.commit()
    return {
        "ok":           True,
        "toy_id":       toy.id,
        "display_name": toy.display_name,
        "rarity":       toy.rarity,
        "is_duplicate": is_duplicate,
        "treats_awarded": treats_awarded,
        "treats":       user.treats,
    }


@app.get("/api/me/sessions")
async def get_my_sessions(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
    limit: int | None = Query(None, ge=1, le=500),
):
    """Return the current user's completed sessions formatted as history entries."""
    q = (
        select(SimSession)
        .where(SimSession.user_id == ctx.user_id)
        .where(SimSession.ended_at.isnot(None))
        .order_by(SimSession.ended_at.desc())
    )
    result = await db.execute(q)
    sessions = [
        s for s in result.scalars().all()
        if not bool((s.narrative_data or {}).get("drill"))
    ]
    if limit is not None:
        sessions = sessions[:limit]

    # Column projection — avoids loading Agency ORM objects and triggering their selectin children
    agency_ids = list({s.agency_id for s in sessions if s.agency_id})
    agency_names: dict[str, str] = {}
    if agency_ids:
        a_result = await db.execute(
            select(Agency.id, Agency.name).where(Agency.id.in_(agency_ids))
        )
        agency_names = {row.id: row.name for row in a_result.all()}

    def _scenario_title(scenario_id: str) -> str:
        try:
            return load_scenario(scenario_id).get("title", scenario_id)
        except (FileNotFoundError, KeyError):
            return scenario_id

    def _scenario_patient_line(scenario: dict) -> str:
        patient = scenario.get("patient") or {}
        parts = [
            patient.get("name"),
            patient.get("age") or patient.get("age_display"),
            patient.get("sex"),
            patient.get("weight_display"),
        ]
        return " · ".join(str(p).strip() for p in parts if str(p or "").strip())

    def _intervention_label(scenario: dict, name: str) -> str:
        interventions = ((scenario.get("vitals") or {}).get("interventions") or {})
        meta = interventions.get(name) or {}
        return meta.get("label") or name

    def _session_pcr_notes(s: SimSession, scenario: dict) -> dict:
        findings = list(s.findings or [])
        by_type: dict[str, list[dict[str, str]]] = {"exam": [], "history": [], "vital": []}
        for finding in findings:
            f_type = str(finding.finding_type or "").lower()
            if f_type not in by_type:
                continue
            by_type[f_type].append({
                "key": finding.key or "",
                "value": finding.value or "",
                "time": finding.captured_at.isoformat() if finding.captured_at else "",
            })

        treatments = [
            {
                "label": _intervention_label(scenario, intervention.name),
                "time": intervention.applied_at.isoformat() if intervention.applied_at else "",
            }
            for intervention in (s.interventions or [])
        ]

        patient_line = _scenario_patient_line(scenario)
        patient = scenario.get("patient") or {}
        complaint = patient.get("chief_complaint") or scenario.get("chief_complaint") or ""
        return {
            "patientId": patient_line,
            "complaint": complaint,
            "dispatch": ((scenario.get("dispatch") or {}).get("text") or ""),
            "presentation": patient.get("general_impression") or scenario.get("presentation") or "",
            "exam": by_type["exam"],
            "history": by_type["history"],
            "vitals": by_type["vital"],
            "treatments": treatments,
        }

    def _session_dict(s: SimSession) -> dict:
        nd = s.narrative_data or {}
        _ep_hist = s.evidence_packet or {}
        _hist_ic = _ep_hist.get("impression_challenge")
        _hist_ic_result = (_hist_ic or {}).get("result") if _hist_ic else None
        # Use scenario config to determine whether IC was enabled — same predicate as
        # the four debrief response paths and the Lexi handler. load_scenario is
        # lru_cached so this is a memory lookup after the first call per scenario_id.
        try:
            _hist_sc = load_scenario(s.scenario_id)
        except (FileNotFoundError, KeyError):
            _hist_sc = {}
        _hist_sc_ic_enabled = bool((_hist_sc.get("impression_challenge") or {}).get("enabled"))
        _hist_qualifying = not _hist_sc_ic_enabled or _hist_ic_result in ("correct", "acceptable")
        _hist_debrief = (s.feedback or "") if _hist_qualifying else _redact_reference_sections(s.feedback or "")
        return {
            "key":             s.id,
            "scenarioId":      s.scenario_id,
            "title":           _scenario_title(s.scenario_id),
            "date":            (s.ended_at or s.start_time).isoformat(),
            "score":           s.score,
            "effectiveScore":  _effective_score(s),
            "adjudicated":     bool(s.adjudications),
            "assessmentScore": s.assessment_score,
            "narrativeScore":  s.narrative_score,
            "criticalFailure": _session_critical_failure(s),
            "assessmentMax":   _assessment_max_from_subscores(_effective_subscores(s)),
            "narrativeSkipped": bool(s.narrative_submitted) and not bool(s.narrative_attempted) and not bool(nd.get("drill")),
            "xpGross":         s.xp_gross or 0,
            "xpEarned":        s.xp_earned or 0,
            "treatsEarned":    s.treats_earned or 0,
            "newBadges":       s.new_badges or [],
            "debrief":         _hist_debrief,
            "impressionChallenge": _hist_ic,
            "timeline":        nd.get("timeline"),
            "rubricDetail":    nd.get("rubric_detail"),
            "pcrNotes":        _session_pcr_notes(s, _hist_sc),
            "subscores":       _effective_subscores(s),
            "topTakeaways":    nd.get("top_takeaways") or [],
            "reflectionPrompts": nd.get("reflection_prompts") or [],
            "nextAction":      nd.get("next_action") or "",
            "nextActionTargetType": nd.get("next_action_target_type") or "none",
            "nextActionTargetId": nd.get("next_action_target_id"),
            "cprChallengeSummary": nd.get("cpr_challenge_summary"),
            "debriefLexiHints": nd.get("debrief_lexi_hints") if _hist_qualifying else [],
            "drillMode":       bool(nd.get("drill")),
            "elapsedMin":      s.elapsed_min or 0,
            "providerLevel":   s.provider_level or "",
            "mca":             s.mca or "",
            "agencyId":        s.agency_id or "",
            "agencyName":      agency_names.get(s.agency_id, s.agency_file or ""),
        }

    return [_session_dict(s) for s in sessions]


@app.put("/api/me/membership")
async def update_membership(
    req: UpdateMembershipRequest,
    response: Response,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Update provider_level / mca for a membership.

    The target agency is taken from req.agency_id when provided (allows editing
    any membership from the modal), otherwise falls back to ctx.agency_id.
    """
    target_agency_id = req.agency_id or ctx.agency_id
    if not target_agency_id:
        raise HTTPException(status_code=400, detail="No agency context — provide agency_id in request body")

    m_result = await db.execute(
        select(AgencyMember).where(
            AgencyMember.user_id   == ctx.user_id,
            AgencyMember.agency_id == target_agency_id,
        )
    )
    membership = m_result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=404, detail="Membership not found")

    user_result   = await db.execute(select(User).where(User.id == ctx.user_id))
    agency_result = await db.execute(select(Agency).where(Agency.id == target_agency_id))
    user          = user_result.scalar_one_or_none()
    agency        = agency_result.scalar_one_or_none()
    agency_config = agency.config if agency else None

    # Capture intended values, applying agency ceiling enforcement
    new_level = _resolve_member_provider_level(req.provider_level or membership.provider_level, agency_config)
    new_mca   = _resolve_member_mca(req.mca or None, agency_config)

    if req.provider_level:
        membership.provider_level = new_level
        if req.mca:
            membership.mca = new_mca
            membership.protocol_profile_id = None
            membership.protocol_profile_assignment_source = "default"
    await _assign_agency_default_protocol_profile(db, agency=agency, membership=membership)
    db.add(membership)
    await db.commit()

    count = await _count_memberships(ctx.user_id, db)

    # Re-assert intended values — subsequent queries may reload identity-map entries
    # from the DB and overwrite what we set above; this guarantees the token is correct.
    membership.provider_level = new_level
    membership.mca            = new_mca
    await _assign_agency_default_protocol_profile(db, agency=agency, membership=membership)

    new_token = _create_active_token(user, membership, agency, membership_count=count)
    _set_auth_cookies(response, new_token)
    return _auth_response(
        new_token,
        protocol_profile_assignment_source=membership.protocol_profile_assignment_source,
    )


@app.delete("/api/me/membership/{agency_id}", status_code=200)
async def leave_agency(
    agency_id: str,
    request: Request,
    response: Response,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Self-service: remove own membership from an agency. Blocked if it's the only one."""
    all_memberships_result = await db.execute(
        select(AgencyMember).where(AgencyMember.user_id == ctx.user_id)
    )
    all_memberships = all_memberships_result.scalars().all()

    if len(all_memberships) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove your only agency membership."
        )

    target = next((m for m in all_memberships if m.agency_id == agency_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Membership not found")

    await db.delete(target)
    await db.commit()

    # Reload remaining memberships for token + response
    remaining_result = await db.execute(
        select(AgencyMember).where(AgencyMember.user_id == ctx.user_id)
    )
    remaining = remaining_result.scalars().all()

    # Pick a new active membership (first remaining one)
    new_membership = remaining[0]
    agency_result  = await db.execute(select(Agency).where(Agency.id == new_membership.agency_id))
    new_agency     = agency_result.scalar_one()
    user_result    = await db.execute(select(User).where(User.id == ctx.user_id))
    user           = user_result.scalar_one()

    new_token = _create_active_token(user, new_membership, new_agency, membership_count=len(remaining))

    # Rotate refresh token to the new active agency
    old_rt_id = request.cookies.get("pfd_ems_refresh")
    if old_rt_id:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_id == old_rt_id, RefreshToken.revoked == False)
            .values(revoked=True)
        )
    new_rt_id = await _issue_refresh_token(ctx.user_id, new_agency.id, db)
    await db.commit()

    _set_auth_cookies(response, new_token)
    _set_refresh_cookie(response, new_rt_id)

    # Build memberships list for UI re-render
    agency_ids = [m.agency_id for m in remaining]
    names_result = await db.execute(select(Agency).where(Agency.id.in_(agency_ids)))
    agency_names = {a.id: a.name for a in names_result.scalars().all()}

    memberships_out = [
        {
            "agency_id":      m.agency_id,
            "agency_name":    agency_names.get(m.agency_id, m.agency_id),
            "role":           m.role,
            "provider_level": m.provider_level,
            "mca":            m.mca,
            "protocol_profile_id": m.protocol_profile_id,
            "protocol_profile_assignment_source": m.protocol_profile_assignment_source,
        }
        for m in remaining
    ]

    return _auth_response(
        new_token,
        removed=agency_id,
        memberships=memberships_out,
    )


# ── Agency management (superuser only) ───────────────────────────────────────

@app.get("/api/agencies")
async def list_agencies(
    ctx: ActiveContext = Depends(get_superuser_context),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Agency).order_by(Agency.name))
    agencies = result.scalars().all()
    return [
        {
            "id":               a.id,
            "name":             a.name,
            "agency_file":      a.agency_file,
            "agency_join_code": a.agency_join_code,
            "is_active":        a.is_active,
            "member_count":     len(a.members),
            "created_at":       a.created_at,
        }
        for a in agencies
    ]


@app.post("/api/agencies", status_code=status.HTTP_201_CREATED)
async def create_agency(
    req: CreateAgencyRequest,
    ctx: ActiveContext = Depends(get_superuser_context),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(Agency).where(Agency.agency_join_code == req.agency_join_code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Join code already in use")
    default_config = {
        "id":              req.agency_file,
        "display_name":    req.name,
        "unit_designator": "",
        "mca":             "",
        "available_mcas":  [],
        "provider_levels": {"primary": "EMT"},
        "service_type":    {"transport": True, "notes": ""},
        "equipment":       {"items": []},
        "training_and_certifications": {"completed": []},
        "sops":            [],
        "ai_prompt_context": "",
    }
    agency = Agency(
        id=str(uuid.uuid4()),
        name=req.name,
        agency_join_code=req.agency_join_code,
        agency_file=req.agency_file,
        config=default_config,
    )
    db.add(agency)
    await db.commit()
    await db.refresh(agency)

    return {
        "id":               agency.id,
        "name":             agency.name,
        "agency_file":      agency.agency_file,
        "agency_join_code": agency.agency_join_code,
    }


@app.get("/api/agencies/public")
async def list_agencies_public(db: AsyncSession = Depends(get_db)):
    """Unauthenticated — returns id, name, and is_open_join. Powers registration/join dropdowns."""
    result = await db.execute(select(Agency).where(Agency.is_active == True).order_by(Agency.name))
    return [{"id": a.id, "name": a.name, "is_open_join": bool(a.is_open_join)} for a in result.scalars().all()]


@app.get("/api/agencies/open")
async def list_open_agencies(db: AsyncSession = Depends(get_db)):
    """
    Unauthenticated — returns all open-join (no code required) agencies.
    Powers the registration agency picker for students without an agency affiliation.
    """
    result = await db.execute(
        select(Agency)
        .where(Agency.is_open_join == True, Agency.is_active == True)
        .order_by(Agency.name)
    )
    agencies = result.scalars().all()
    return [
        {
            "id":           a.id,
            "name":         a.name,
            "display_name_short": (a.config or {}).get("display_name_short", a.name),
            "service_type": (a.config or {}).get("service_type", {}),
        }
        for a in agencies
    ]


class OpenJoinAgencyRequest(BaseModel):
    agency_id:      str
    provider_level: str = "EMT"
    mca:            Optional[str] = None   # None → inherit from agency config


@app.post("/api/agencies/join/open", status_code=status.HTTP_201_CREATED)
async def join_open_agency(
    req: OpenJoinAgencyRequest,
    token: str = Depends(_extract_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Join an open-join agency by agency ID — no join code required.
    Only agencies in the open-join list are accepted.
    """
    from sqlalchemy.exc import IntegrityError

    payload = _decode_token(token)
    user_id = payload["sub"]

    a_result = await db.execute(select(Agency).where(Agency.id == req.agency_id))
    agency = a_result.scalar_one_or_none()
    if not agency or not agency.is_open_join:
        raise HTTPException(status_code=400, detail="Agency is not open-join or does not exist")

    membership = AgencyMember(
        user_id=user_id,
        agency_id=req.agency_id,
        role="student",
        provider_level=_resolve_member_provider_level(req.provider_level, agency.config),
        mca=_resolve_member_mca(req.mca, agency.config),
    )
    await _assign_agency_default_protocol_profile(db, agency=agency, membership=membership)
    db.add(membership)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="You are already a member of this agency")

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    agency_ids = [m.agency_id for m in user.memberships]
    all_agencies_result = await db.execute(select(Agency).where(Agency.id.in_(agency_ids)))
    agency_map = {a.id: a.name for a in all_agencies_result.scalars().all()}

    return {
        "status":           "joined",
        "membership_count": len(user.memberships),
        "memberships": [
            {
                "agency_id":      m.agency_id,
                "agency_name":    agency_map.get(m.agency_id, m.agency_id),
                "role":           m.role,
                "provider_level": m.provider_level,
                "mca":            m.mca,
                "protocol_profile_id": m.protocol_profile_id,
                "protocol_profile_assignment_source": m.protocol_profile_assignment_source,
            }
            for m in user.memberships
        ],
    }


@app.get("/api/mcas")
async def list_mcas_endpoint():
    """Unauthenticated — returns available MCA options for registration and profile dropdowns."""
    return list_mcas()


@app.put("/api/agencies/{agency_id}/config")
async def update_agency_config(
    agency_id: str,
    config: dict,
    ctx: ActiveContext = Depends(get_superuser_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Superuser: replace an agency's clinical config JSONB in the database.
    Use this to apply changes from the JSON file without restarting — paste the
    updated JSON body directly. Invalidates the in-process agency cache and
    immediately propagates the new MCA to all AgencyMember rows for this agency.
    Note: active JWTs carry the previous MCA until they expire (up to 24 hours).
    """
    result = await db.execute(select(Agency).where(Agency.id == agency_id))
    agency = result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    config.pop("_schema", None)
    config.pop("_comment", None)
    agency.config = config
    db.add(agency)

    # Propagate new MCA to all member rows immediately so the next
    # login / context switch picks up the correct value without a restart.
    correct_mca = _resolve_member_mca(None, config)
    members_result = await db.execute(
        select(AgencyMember).where(AgencyMember.agency_id == agency_id)
    )
    members = members_result.scalars().all()
    updated = 0
    for member in members:
        if member.mca != correct_mca:
            member.mca = correct_mca
            db.add(member)
            updated += 1

    await db.commit()
    invalidate_agency_cache(agency_id)
    log.info("agency.config_updated", agency_id=agency_id, members_mca_updated=updated)
    return {
        "agency_id":       agency_id,
        "status":          "config_updated",
        "members_updated": updated,
        "note": (
            "Active tokens carry the previous MCA until they expire (up to 24 hours) "
            "— users may need to re-authenticate for immediate effect."
        ) if updated else None,
    }


@app.patch("/api/agencies/{agency_id}/active")
async def set_agency_active(
    agency_id: str,
    req: ToggleActiveRequest,
    ctx: ActiveContext = Depends(get_superuser_context),
    db: AsyncSession = Depends(get_db),
):
    """Superuser: activate or deactivate an agency. Inactive agencies block login."""
    result = await db.execute(select(Agency).where(Agency.id == agency_id))
    agency = result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    agency.is_active = req.is_active
    db.add(agency)
    await db.commit()
    return {"agency_id": agency_id, "is_active": req.is_active}


@app.put("/api/agency")
async def update_agency(
    req: UpdateAgencyRequest,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: update agency relational fields (name, join code)."""
    result = await db.execute(select(Agency).where(Agency.id == ctx.agency_id))
    agency = result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    if req.name is not None:
        agency.name = req.name.strip()
    if req.agency_join_code is not None:
        conflict = await db.execute(
            select(Agency).where(
                Agency.agency_join_code == req.agency_join_code,
                Agency.id              != agency.id,
            )
        )
        if conflict.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Join code already in use by another agency")
        agency.agency_join_code = req.agency_join_code.strip()
    db.add(agency)
    await db.commit()

    return {
        "id":               agency.id,
        "name":             agency.name,
        "agency_join_code": agency.agency_join_code,
        "agency_file":      agency.agency_file,
    }


@app.get("/api/agency/info")
async def get_agency_info(
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: return basic info (name, join code) for the active agency."""
    if not ctx.agency_id:
        raise HTTPException(status_code=403, detail="No active agency")
    result = await db.execute(select(Agency).where(Agency.id == ctx.agency_id))
    agency = result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    return {
        "id":               agency.id,
        "name":             agency.name,
        "agency_join_code": agency.agency_join_code,
    }


@app.get("/api/agency/config")
async def get_agency_config(
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: return the clinical config JSONB for the active agency."""
    effective = _superadmin_agency(ctx, agency_id) or ctx.agency_id
    if not effective:
        return {}
    result = await db.execute(select(Agency).where(Agency.id == effective))
    agency = result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    return agency.config or {}


@app.put("/api/agency/config")
async def update_agency_config(
    req: AgencyConfigUpdate,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: update the clinical config JSONB for the active agency."""
    effective = _superadmin_agency(ctx, agency_id) or ctx.agency_id
    if not effective:
        raise HTTPException(status_code=403, detail="No active agency")
    result = await db.execute(select(Agency).where(Agency.id == effective))
    agency = result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    # Merge into existing config to preserve any fields we don't expose in the form
    config = (agency.config or {}).copy()
    if req.display_name    is not None: config["display_name"]    = req.display_name
    if req.unit_designator is not None: config["unit_designator"] = req.unit_designator
    if req.mca             is not None: config["mca"]             = req.mca
    if req.provider_levels is not None: config["provider_levels"] = req.provider_levels
    if req.service_type    is not None: config["service_type"]    = req.service_type
    if req.ai_prompt_context is not None: config["ai_prompt_context"] = req.ai_prompt_context
    if req.equipment is not None:
        equip = req.equipment
        if isinstance(equip, dict) and "items" in equip:
            _validate_equipment_items_payload(equip["items"])
        config["equipment"] = equip
    if req.training_and_certifications is not None:
        config["training_and_certifications"] = req.training_and_certifications
    config["available_mcas"] = req.available_mcas
    config["sops"]           = req.sops

    agency.config = config
    db.add(agency)
    await db.commit()
    invalidate_agency_cache(effective)
    return config


@app.get("/api/agency/equipment-catalog")
async def get_equipment_catalog():
    """Return the curated master equipment and medications catalog. No auth required."""
    category_labels = {
        "airway": "Airway",
        "monitoring": "Monitoring",
        "trauma": "Trauma",
        "other": "Other",
    }
    categories = [
        {
            "key": cat_key,
            "label": category_labels.get(cat_key, cat_key.title()),
            "items": [{"id": iid, "label": lbl} for iid, lbl in cat_items.items()],
        }
        for cat_key, cat_items in EQUIPMENT_CATALOG.items()
    ]
    return {
        "categories": categories,
        "medications": all_medication_items(),
    }


class EquipmentReviewResolution(BaseModel):
    item_id:    str
    resolution: Literal["accept", "reject", "remap"]
    remap_to_id: Optional[str] = None


@app.get("/api/agency/equipment-review-queue")
async def get_equipment_review_queue(
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: return all equipment items flagged needs_review for the active agency."""
    effective = _superadmin_agency(ctx, agency_id) or ctx.agency_id
    if not effective:
        return {"items": []}
    result = await db.execute(select(Agency).where(Agency.id == effective))
    agency = result.scalar_one_or_none()
    if not agency or not agency.config:
        return {"items": []}
    items = (agency.config.get("equipment") or {}).get("items", [])
    review_items = []
    for item in items:
        if not item.get("needs_review"):
            continue
        entry = {
            "id": item["id"],
            "carried": item.get("carried", True),
            "original_text": item.get("original_text", item.get("label", item["id"])),
        }
        if item.get("source") == "master":
            entry["suggested_label"] = equipment_label_for_id(item["id"]) or item["id"]
        review_items.append(entry)
    return {"items": review_items}


@app.post("/api/agency/equipment-review")
async def resolve_equipment_review(
    req: EquipmentReviewResolution,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: accept, reject, or remap a needs_review equipment item."""
    effective = _superadmin_agency(ctx, agency_id) or ctx.agency_id
    if not effective:
        raise HTTPException(status_code=403, detail="No active agency")
    result = await db.execute(select(Agency).where(Agency.id == effective))
    agency = result.scalar_one_or_none()
    if not agency or not agency.config:
        raise HTTPException(status_code=404, detail="Agency not found")

    equip = agency.config.get("equipment") or {}
    items: list[dict] = list(equip.get("items", []))
    idx = next((i for i, it in enumerate(items) if it["id"] == req.item_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Equipment item not found")

    if req.resolution == "reject":
        items.pop(idx)
    elif req.resolution == "accept":
        items[idx] = {k: v for k, v in items[idx].items() if k != "needs_review"}
    elif req.resolution == "remap":
        if not req.remap_to_id:
            raise HTTPException(status_code=422, detail="remap_to_id required for remap resolution")
        if not equipment_label_for_id(req.remap_to_id):
            raise HTTPException(status_code=422, detail=f"remap_to_id {req.remap_to_id!r} is not a known catalog item")
        carried = items[idx].get("carried", True)
        items[idx] = {"id": req.remap_to_id, "carried": carried, "source": "master"}
    else:
        raise HTTPException(status_code=422, detail="resolution must be accept, reject, or remap")

    new_config = {**agency.config, "equipment": {**equip, "items": items}}
    agency.config = new_config
    flag_modified(agency, "config")
    db.add(agency)
    await db.commit()
    invalidate_agency_cache(effective)
    return {"ok": True, "items": items}


@app.get("/api/protocols")
async def list_protocols():
    """Return available MCA/protocol codes derived from the protocols directory structure."""
    protocols_dir = Path(__file__).parent / "protocols"
    mcas = []
    if protocols_dir.exists():
        for d in sorted(protocols_dir.iterdir()):
            if d.is_dir():
                # Use a human-readable label derived from the directory name
                label = d.name.replace("_", " ").replace("-", " ").title()
                mcas.append({"id": d.name, "label": label})
    return mcas


@app.get("/api/protocol-base-sets")
async def list_protocol_base_sets():
    """Return base protocol sets that can seed an agency protocol profile."""
    return available_base_protocol_sets()


@app.get("/api/admin/protocol-excerpt-preview")
async def admin_protocol_excerpt_preview(
    scenario_id: str,
    base_protocol_set: str = "MI",
    ctx: ActiveContext = Depends(get_admin_context),
):
    """Admin-only, non-authoritative preview of tag-based protocol matching.

    This is deliberately not used by simulation prompts, scoring, Medical
    Control, or debrief generation. It exists so admins/developers can inspect
    Phase 2 tag/index behavior before SME review makes it authoritative.
    """
    del ctx  # dependency enforces admin/superuser access
    try:
        scenario = load_scenario(scenario_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Scenario not found")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Scenario could not be loaded: {exc}")
    return build_protocol_excerpt_preview(base_protocol_set, scenario)


@app.get("/api/me/protocol-change-notifications")
async def list_my_protocol_change_notifications(
    include_seen: bool = False,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Return protocol-change notifications for the active user/agency."""
    stmt = select(ProtocolChangeNotification).where(
        ProtocolChangeNotification.user_id == ctx.user_id
    )
    if ctx.agency_id:
        stmt = stmt.where(ProtocolChangeNotification.agency_id == ctx.agency_id)
    if not include_seen:
        stmt = stmt.where(ProtocolChangeNotification.seen_at.is_(None))
    result = await db.execute(
        stmt.order_by(ProtocolChangeNotification.created_at.desc()).limit(20)
    )
    return [
        {
            "id": note.id,
            "agency_id": note.agency_id,
            "snapshot_id": note.snapshot_id,
            "summary_markdown": note.summary_markdown,
            "seen_at": note.seen_at.isoformat() if note.seen_at else None,
            "created_at": note.created_at.isoformat() if note.created_at else None,
        }
        for note in result.scalars().all()
    ]


@app.post("/api/me/protocol-change-notifications/seen")
async def mark_protocol_change_notification_seen(
    req: ProtocolNotificationSeenRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Mark a protocol-change notification as seen by its owning user."""
    result = await db.execute(
        select(ProtocolChangeNotification).where(
            ProtocolChangeNotification.id == req.notification_id,
            ProtocolChangeNotification.user_id == ctx.user_id,
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Protocol notification not found")
    note.seen_at = datetime.utcnow()
    db.add(note)
    await db.commit()
    return {"ok": True, "seen_at": note.seen_at.isoformat()}


@app.get("/api/agency/audit-logs")
async def list_agency_audit_logs(
    agency_id: Optional[str] = None,
    limit: int = 50,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: return recent append-only agency audit events."""
    agency = await _effective_admin_agency(ctx, db, agency_id)
    safe_limit = max(1, min(int(limit or 50), 200))
    result = await db.execute(
        select(AgencyAuditLog)
        .where(AgencyAuditLog.agency_id == agency.id)
        .order_by(AgencyAuditLog.timestamp.desc())
        .limit(safe_limit)
    )
    logs = result.scalars().all()
    user_ids = [log.user_id for log in logs if log.user_id]
    users_by_id: dict[str, User] = {}
    if user_ids:
        users = (await db.execute(select(User).where(User.id.in_(set(user_ids))))).scalars().all()
        users_by_id = {user.id: user for user in users}
    return [
        {
            "id": log.id,
            "agency_id": log.agency_id,
            "user_id": log.user_id,
            "username": users_by_id.get(log.user_id).username if log.user_id in users_by_id else None,
            "action": log.action,
            "previous_state": log.previous_state,
            "new_state": log.new_state,
            "ip_address": log.ip_address,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
        }
        for log in logs
    ]


def _protocol_profile_out(profile: AgencyProtocolProfile, selection_count: int = 0) -> dict:
    return {
        "id": profile.id,
        "agency_id": profile.agency_id,
        "display_name": profile.display_name,
        "profile_type": profile.profile_type,
        "base_protocol_set": profile.base_protocol_set,
        "official_mca_id": profile.official_mca_id,
        "active_protocol_snapshot_id": profile.active_protocol_snapshot_id,
        "last_compile_status": profile.last_compile_status,
        "last_compile_error": profile.last_compile_error,
        "last_compiled_at": profile.last_compiled_at.isoformat() if profile.last_compiled_at else None,
        "is_default": bool(profile.is_default),
        "is_active": bool(profile.is_active),
        "selection_count": selection_count,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


_SOP_RULE_TYPES = {
    "local_sop",
    "scope_restriction",
    "contraindication",
    "scope_expansion",
    "equipment_policy",
    "not_carried",
    "training_note",
    "protocol_clarification",
}
_SOP_EDITABLE_STATUSES = {"draft", "rejected"}


def _clean_identifier_list(values: list[str] | None, *, field_name: str) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        value = str(raw or "").strip()
        if not value:
            continue
        if not re.fullmatch(r"[a-z0-9_]+", value):
            raise HTTPException(
                status_code=422,
                detail=f"{field_name} must contain stable lowercase IDs using letters, numbers, and underscores",
            )
        if value not in seen:
            cleaned.append(value)
            seen.add(value)
    return cleaned


def _sop_out(sop: AgencySOP) -> dict:
    return {
        "id": sop.id,
        "agency_id": sop.agency_id,
        "protocol_profile_id": sop.protocol_profile_id,
        "version_id": sop.version_id,
        "rule_type": sop.rule_type,
        "status": sop.status,
        "extracted_rule": sop.extracted_rule,
        "source_quote": sop.source_quote,
        "source_label": sop.source_label,
        "page_number": sop.page_number,
        "clinical_concept_tags": sop.clinical_concept_tags or [],
        "intervention_action_ids": sop.intervention_action_ids or [],
        "patch_operations": sop.patch_operations,
        "sme_review_status": sop.sme_review_status,
        "submitted_by": sop.submitted_by,
        "submitted_at": sop.submitted_at.isoformat() if sop.submitted_at else None,
        "approved_by": sop.approved_by,
        "approved_at": sop.approved_at.isoformat() if sop.approved_at else None,
        "rejected_by": sop.rejected_by,
        "rejected_at": sop.rejected_at.isoformat() if sop.rejected_at else None,
        "superseded_at": sop.superseded_at.isoformat() if sop.superseded_at else None,
        "metadata_json": sop.metadata_json or {},
        "created_at": sop.created_at.isoformat() if sop.created_at else None,
        "updated_at": sop.updated_at.isoformat() if sop.updated_at else None,
        "authoritative": False,
    }


async def _load_agency_profile_or_404(
    db: AsyncSession,
    *,
    agency_id: str,
    profile_id: str,
) -> AgencyProtocolProfile:
    profile = (await db.execute(
        select(AgencyProtocolProfile).where(
            AgencyProtocolProfile.id == profile_id,
            AgencyProtocolProfile.agency_id == agency_id,
        )
    )).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Protocol profile not found")
    return profile


async def _load_agency_sop_or_404(
    db: AsyncSession,
    *,
    agency_id: str,
    sop_id: str,
) -> AgencySOP:
    sop = (await db.execute(
        select(AgencySOP).where(
            AgencySOP.id == sop_id,
            AgencySOP.agency_id == agency_id,
        )
    )).scalar_one_or_none()
    if not sop:
        raise HTTPException(status_code=404, detail="Agency SOP not found")
    return sop


def _apply_sop_fields(sop: AgencySOP, req: AgencySOPCreateRequest | AgencySOPUpdateRequest) -> None:
    if req.rule_type is not None:
        rule_type = req.rule_type.strip()
        if rule_type not in _SOP_RULE_TYPES:
            raise HTTPException(status_code=422, detail="Unknown SOP rule type")
        sop.rule_type = rule_type
    if req.extracted_rule is not None:
        extracted_rule = req.extracted_rule.strip()
        if not extracted_rule:
            raise HTTPException(status_code=422, detail="SOP rule text is required")
        sop.extracted_rule = extracted_rule
    if req.source_quote is not None:
        sop.source_quote = req.source_quote.strip() or None
    if req.source_label is not None:
        sop.source_label = req.source_label.strip() or None
    if req.page_number is not None:
        if req.page_number < 1:
            raise HTTPException(status_code=422, detail="Page number must be 1 or greater")
        sop.page_number = req.page_number
    if req.clinical_concept_tags is not None:
        sop.clinical_concept_tags = _clean_identifier_list(
            req.clinical_concept_tags,
            field_name="clinical_concept_tags",
        )
    if req.intervention_action_ids is not None:
        sop.intervention_action_ids = _clean_identifier_list(
            req.intervention_action_ids,
            field_name="intervention_action_ids",
        )
    if req.patch_operations is not None:
        if not isinstance(req.patch_operations, list):
            raise HTTPException(status_code=422, detail="patch_operations must be a list")
        sop.patch_operations = req.patch_operations
    if req.metadata_json is not None:
        sop.metadata_json = dict(req.metadata_json or {})


def _request_ip_address(request: Request | None) -> str | None:
    if not request or not request.client:
        return None
    return request.client.host


async def _write_agency_audit_log(
    db: AsyncSession,
    *,
    agency_id: str | None,
    user_id: str | None,
    action: str,
    previous_state: dict | list | None = None,
    new_state: dict | list | None = None,
    request: Request | None = None,
) -> None:
    db.add(AgencyAuditLog(
        id=str(uuid.uuid4()),
        agency_id=agency_id,
        user_id=user_id,
        action=action,
        previous_state=previous_state,
        new_state=new_state,
        ip_address=_request_ip_address(request),
        timestamp=datetime.utcnow(),
    ))


async def _queue_protocol_change_notifications(
    db: AsyncSession,
    *,
    agency_id: str,
    summary_markdown: str,
    snapshot_id: str | None = None,
) -> None:
    """Create unseen protocol-change notifications for active agency members."""
    members = (await db.execute(
        select(AgencyMember).where(AgencyMember.agency_id == agency_id)
    )).scalars().all()
    seen_user_ids: set[str] = set()
    for member in members:
        if member.user_id in seen_user_ids:
            continue
        seen_user_ids.add(member.user_id)
        db.add(ProtocolChangeNotification(
            id=str(uuid.uuid4()),
            user_id=member.user_id,
            agency_id=agency_id,
            snapshot_id=snapshot_id,
            summary_markdown=summary_markdown,
            created_at=datetime.utcnow(),
        ))


async def _effective_admin_agency(
    ctx: ActiveContext,
    db: AsyncSession,
    agency_id: Optional[str] = None,
) -> Agency:
    effective = _superadmin_agency(ctx, agency_id) or ctx.agency_id
    if not effective:
        raise HTTPException(status_code=403, detail="No active agency")
    result = await db.execute(select(Agency).where(Agency.id == effective))
    agency = result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    return agency


@app.get("/api/agency/protocol-profiles")
async def list_agency_protocol_profiles(
    agency_id: Optional[str] = None,
    ensure_default: bool = True,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list agency-approved protocol profiles for the active agency."""
    agency = await _effective_admin_agency(ctx, db, agency_id)
    if ensure_default:
        await get_effective_protocol_profile(
            db,
            agency_id=agency.id,
            mca_id=(agency.config or {}).get("mca") or settings.default_mca,
        )
        await db.commit()

    count_subq = (
        select(
            AgencyProtocolSelection.protocol_profile_id,
            func.count(AgencyProtocolSelection.id).label("selection_count"),
        )
        .group_by(AgencyProtocolSelection.protocol_profile_id)
        .subquery()
    )
    result = await db.execute(
        select(AgencyProtocolProfile, count_subq.c.selection_count)
        .outerjoin(count_subq, count_subq.c.protocol_profile_id == AgencyProtocolProfile.id)
        .where(AgencyProtocolProfile.agency_id == agency.id)
        .order_by(AgencyProtocolProfile.is_default.desc(), AgencyProtocolProfile.display_name)
    )
    return [
        _protocol_profile_out(profile, int(selection_count or 0))
        for profile, selection_count in result.all()
    ]


@app.post("/api/agency/protocol-profiles", status_code=status.HTTP_201_CREATED)
async def create_agency_protocol_profile(
    request: Request,
    req: ProtocolProfileCreateRequest,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: create a structured agency protocol profile."""
    agency = await _effective_admin_agency(ctx, db, agency_id)
    display_name = req.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="Profile name is required")
    allowed_sets = {item["id"] for item in available_base_protocol_sets()}
    if allowed_sets and req.base_protocol_set not in allowed_sets:
        raise HTTPException(status_code=422, detail="Unknown base protocol set")

    if req.is_default:
        existing_defaults = await db.execute(
            select(AgencyProtocolProfile).where(
                AgencyProtocolProfile.agency_id == agency.id,
                AgencyProtocolProfile.is_default == True,
            )
        )
        for existing in existing_defaults.scalars().all():
            existing.is_default = False
            db.add(existing)

    profile = AgencyProtocolProfile(
        id=str(uuid.uuid4()),
        agency_id=agency.id,
        display_name=display_name,
        profile_type=req.profile_type or "agency_local",
        base_protocol_set=req.base_protocol_set,
        official_mca_id=(req.official_mca_id or (agency.config or {}).get("mca") or settings.default_mca),
        is_default=bool(req.is_default),
        is_active=True,
        created_by=ctx.user_id,
    )
    db.add(profile)
    if profile.is_default:
        agency.default_protocol_profile_id = profile.id
        db.add(agency)
        await _propagate_agency_default_protocol_profile(db, agency_id=agency.id, profile_id=profile.id)
    snapshot = await materialize_protocol_profile_snapshot(
        db,
        profile=profile,
        mca_id=profile.official_mca_id or (agency.config or {}).get("mca") or settings.default_mca,
    )
    await _write_agency_audit_log(
        db,
        agency_id=agency.id,
        user_id=ctx.user_id,
        action="protocol_profile_created",
        previous_state=None,
        new_state={
            "profile_id": profile.id,
            "display_name": profile.display_name,
            "base_protocol_set": profile.base_protocol_set,
            "official_mca_id": profile.official_mca_id,
            "active_protocol_snapshot_id": profile.active_protocol_snapshot_id,
            "is_default": profile.is_default,
        },
        request=request,
    )
    await _queue_protocol_change_notifications(
        db,
        agency_id=agency.id,
        snapshot_id=snapshot.id,
        summary_markdown=f"Protocol profile created: **{profile.display_name}**.",
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A protocol profile with that name already exists")
    await db.refresh(profile)
    return _protocol_profile_out(profile)


@app.put("/api/agency/protocol-profiles/{profile_id}")
async def update_agency_protocol_profile(
    profile_id: str,
    request: Request,
    req: ProtocolProfileUpdateRequest,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: update profile metadata and default status."""
    agency = await _effective_admin_agency(ctx, db, agency_id)
    result = await db.execute(
        select(AgencyProtocolProfile).where(
            AgencyProtocolProfile.id == profile_id,
            AgencyProtocolProfile.agency_id == agency.id,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Protocol profile not found")
    previous_state = _protocol_profile_out(profile)
    cleared_selection_count = 0

    if req.display_name is not None:
        name = req.display_name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Profile name is required")
        profile.display_name = name
    if req.base_protocol_set is not None:
        allowed_sets = {item["id"] for item in available_base_protocol_sets()}
        if allowed_sets and req.base_protocol_set not in allowed_sets:
            raise HTTPException(status_code=422, detail="Unknown base protocol set")
        if req.base_protocol_set != profile.base_protocol_set:
            existing_selections = (await db.execute(
                select(AgencyProtocolSelection).where(
                    AgencyProtocolSelection.protocol_profile_id == profile.id
                )
            )).scalars().all()
            cleared_selection_count = len(existing_selections)
            for selection in existing_selections:
                await db.delete(selection)
        profile.base_protocol_set = req.base_protocol_set
    if req.official_mca_id is not None:
        profile.official_mca_id = req.official_mca_id or None
    if req.profile_type is not None:
        profile.profile_type = req.profile_type or "agency_local"
    if req.is_active is not None:
        if req.is_active is False and profile.is_default:
            raise HTTPException(status_code=422, detail="Set another default profile before deactivating this profile")
        if req.is_active is False:
            assigned_members = await db.execute(
                select(func.count(AgencyMember.id)).where(
                    AgencyMember.agency_id == agency.id,
                    AgencyMember.protocol_profile_id == profile.id,
                    AgencyMember.protocol_profile_assignment_source == "manual",
                )
            )
            if int(assigned_members.scalar() or 0) > 0:
                raise HTTPException(status_code=422, detail="Reassign members using this profile before deactivating it")
        profile.is_active = bool(req.is_active)
    should_materialize = (
        req.base_protocol_set is not None
        or req.official_mca_id is not None
        or req.is_active is not None
    )
    if req.is_default is True:
        existing_defaults = await db.execute(
            select(AgencyProtocolProfile).where(
                AgencyProtocolProfile.agency_id == agency.id,
                AgencyProtocolProfile.id != profile.id,
                AgencyProtocolProfile.is_default == True,
            )
        )
        for existing in existing_defaults.scalars().all():
            existing.is_default = False
            db.add(existing)
        profile.is_default = True
        agency.default_protocol_profile_id = profile.id
        db.add(agency)
        await _propagate_agency_default_protocol_profile(db, agency_id=agency.id, profile_id=profile.id)
    elif req.is_default is False and profile.is_default:
        raise HTTPException(status_code=422, detail="Set another profile as default before unsetting this one")

    profile.updated_at = datetime.utcnow()
    db.add(profile)
    snapshot = None
    if profile.is_active and should_materialize:
        snapshot = await materialize_protocol_profile_snapshot(
            db,
            profile=profile,
            mca_id=profile.official_mca_id or (agency.config or {}).get("mca") or settings.default_mca,
        )
    await _write_agency_audit_log(
        db,
        agency_id=agency.id,
        user_id=ctx.user_id,
        action="protocol_profile_updated",
        previous_state=previous_state,
        new_state={
            "profile_id": profile.id,
            "display_name": profile.display_name,
            "profile_type": profile.profile_type,
            "base_protocol_set": profile.base_protocol_set,
            "official_mca_id": profile.official_mca_id,
            "active_protocol_snapshot_id": profile.active_protocol_snapshot_id,
            "is_default": profile.is_default,
            "is_active": profile.is_active,
            "cleared_selection_count": cleared_selection_count,
        },
        request=request,
    )
    await _queue_protocol_change_notifications(
        db,
        agency_id=agency.id,
        snapshot_id=snapshot.id if snapshot else profile.active_protocol_snapshot_id,
        summary_markdown=f"Protocol profile updated: **{profile.display_name}**.",
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A protocol profile with that name already exists")
    await db.refresh(profile)
    return _protocol_profile_out(profile)


@app.get("/api/agency/protocol-profiles/{profile_id}/selections")
async def list_agency_protocol_profile_selections(
    profile_id: str,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list structured selection toggles stored for a protocol profile."""
    agency = await _effective_admin_agency(ctx, db, agency_id)
    profile = (await db.execute(
        select(AgencyProtocolProfile).where(
            AgencyProtocolProfile.id == profile_id,
            AgencyProtocolProfile.agency_id == agency.id,
        )
    )).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Protocol profile not found")
    result = await db.execute(
        select(AgencyProtocolSelection).where(
            AgencyProtocolSelection.protocol_profile_id == profile.id
        ).order_by(AgencyProtocolSelection.protocol_id, AgencyProtocolSelection.selection_id)
    )
    return [
        {
            "id": sel.id,
            "protocol_profile_id": sel.protocol_profile_id,
            "protocol_id": sel.protocol_id,
            "selection_id": sel.selection_id,
            "is_selected": bool(sel.is_selected),
            "selected_value": sel.selected_value,
            "base_protocol_version": sel.base_protocol_version,
            "updated_at": sel.updated_at.isoformat() if sel.updated_at else None,
        }
        for sel in result.scalars().all()
    ]


@app.get("/api/agency/protocol-profiles/{profile_id}/selection-options")
async def list_agency_protocol_profile_selection_options(
    profile_id: str,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: return base protocol choices merged with this profile's selections."""
    agency = await _effective_admin_agency(ctx, db, agency_id)
    profile = (await db.execute(
        select(AgencyProtocolProfile).where(
            AgencyProtocolProfile.id == profile_id,
            AgencyProtocolProfile.agency_id == agency.id,
        )
    )).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Protocol profile not found")

    existing_result = await db.execute(
        select(AgencyProtocolSelection).where(
            AgencyProtocolSelection.protocol_profile_id == profile.id
        )
    )
    existing = {
        (sel.protocol_id, sel.selection_id): sel
        for sel in existing_result.scalars().all()
    }
    options = []
    for option in protocol_selection_options_for_base_set(profile.base_protocol_set):
        key = (option["protocol_id"], option["selection_id"])
        row = existing.get(key)
        options.append({
            **option,
            "is_selected": bool(row.is_selected) if row else False,
            "selected_value": row.selected_value if row and row.selected_value is not None else option.get("default_selected"),
            "base_protocol_version": row.base_protocol_version if row else None,
        })
    return {
        "profile": _protocol_profile_out(profile, len(existing)),
        "options": options,
    }


@app.put("/api/agency/protocol-profiles/{profile_id}/selections")
async def update_agency_protocol_profile_selections(
    profile_id: str,
    request: Request,
    req: ProtocolSelectionsUpdateRequest,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: replace structured protocol selections for a profile."""
    agency = await _effective_admin_agency(ctx, db, agency_id)
    profile = (await db.execute(
        select(AgencyProtocolProfile).where(
            AgencyProtocolProfile.id == profile_id,
            AgencyProtocolProfile.agency_id == agency.id,
        )
    )).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Protocol profile not found")

    existing_result = await db.execute(
        select(AgencyProtocolSelection).where(
            AgencyProtocolSelection.protocol_profile_id == profile.id
        )
    )
    existing = {
        (sel.protocol_id, sel.selection_id): sel
        for sel in existing_result.scalars().all()
    }
    previous_state = [
        {
            "protocol_id": sel.protocol_id,
            "selection_id": sel.selection_id,
            "is_selected": bool(sel.is_selected),
            "selected_value": sel.selected_value,
            "base_protocol_version": sel.base_protocol_version,
        }
        for sel in existing.values()
    ]
    option_by_key = {
        (option["protocol_id"], option["selection_id"]): option
        for option in protocol_selection_options_for_base_set(profile.base_protocol_set)
    }
    seen: set[tuple[str, str]] = set()
    for item in req.selections:
        protocol_id = item.protocol_id.strip()
        selection_id = item.selection_id.strip()
        if not protocol_id or not selection_id:
            raise HTTPException(status_code=422, detail="Protocol ID and selection ID are required")
        key = (protocol_id, selection_id)
        option = option_by_key.get(key)
        if not option:
            raise HTTPException(status_code=422, detail=f"Unknown protocol selection: {protocol_id}:{selection_id}")
        choices = option.get("options") if isinstance(option.get("options"), list) else []
        if choices and item.selected_value is not None and item.selected_value not in choices:
            raise HTTPException(status_code=422, detail=f"Invalid selected value for {protocol_id}:{selection_id}")
        seen.add(key)
        row = existing.get(key)
        if not row:
            row = AgencyProtocolSelection(
                id=str(uuid.uuid4()),
                protocol_profile_id=profile.id,
                agency_id=agency.id,
                mca_id=profile.official_mca_id,
                protocol_id=protocol_id,
                selection_id=selection_id,
            )
        row.is_selected = bool(item.is_selected)
        row.selected_value = item.selected_value
        row.base_protocol_version = item.base_protocol_version
        row.updated_by = ctx.user_id
        row.updated_at = datetime.utcnow()
        db.add(row)

    for key, row in existing.items():
        if key not in seen:
            await db.delete(row)

    profile.updated_at = datetime.utcnow()
    db.add(profile)
    snapshot = await materialize_protocol_profile_snapshot(
        db,
        profile=profile,
        mca_id=profile.official_mca_id or (agency.config or {}).get("mca") or settings.default_mca,
    )
    new_state = [
        {
            "protocol_id": item.protocol_id.strip(),
            "selection_id": item.selection_id.strip(),
            "is_selected": bool(item.is_selected),
            "selected_value": item.selected_value,
            "base_protocol_version": item.base_protocol_version,
        }
        for item in req.selections
    ]
    await _write_agency_audit_log(
        db,
        agency_id=agency.id,
        user_id=ctx.user_id,
        action="protocol_selection_changed",
        previous_state=previous_state,
        new_state={
            "profile_id": profile.id,
            "profile_name": profile.display_name,
            "active_protocol_snapshot_id": profile.active_protocol_snapshot_id,
            "selections": new_state,
        },
        request=request,
    )
    await _queue_protocol_change_notifications(
        db,
        agency_id=agency.id,
        snapshot_id=snapshot.id,
        summary_markdown=f"Structured protocol selections updated for **{profile.display_name}**.",
    )
    await db.commit()
    return {"ok": True, "selection_count": len(req.selections)}


@app.get("/api/agency/protocol-profiles/{profile_id}/sops")
async def list_agency_protocol_profile_sops(
    profile_id: str,
    agency_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list Phase 2A SOP/custom protocol records for a profile.

    These records are workflow/audit artifacts only. They do not affect live
    prompts, Medical Control, deterministic scoring, or debriefs.
    """
    agency = await _effective_admin_agency(ctx, db, agency_id)
    await _load_agency_profile_or_404(db, agency_id=agency.id, profile_id=profile_id)
    stmt = select(AgencySOP).where(
        AgencySOP.agency_id == agency.id,
        AgencySOP.protocol_profile_id == profile_id,
    )
    if status_filter:
        stmt = stmt.where(AgencySOP.status == status_filter)
    result = await db.execute(stmt.order_by(AgencySOP.updated_at.desc(), AgencySOP.created_at.desc()))
    return [_sop_out(sop) for sop in result.scalars().all()]


@app.post("/api/agency/protocol-profiles/{profile_id}/sops", status_code=status.HTTP_201_CREATED)
async def create_agency_protocol_profile_sop(
    profile_id: str,
    request: Request,
    req: AgencySOPCreateRequest,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: create a non-authoritative local SOP/custom protocol draft."""
    agency = await _effective_admin_agency(ctx, db, agency_id)
    profile = await _load_agency_profile_or_404(db, agency_id=agency.id, profile_id=profile_id)
    sop = AgencySOP(
        id=str(uuid.uuid4()),
        agency_id=agency.id,
        protocol_profile_id=profile.id,
        version_id=str(uuid.uuid4()),
        rule_type=req.rule_type or "local_sop",
        status="draft",
        extracted_rule=req.extracted_rule,
        sme_review_status="pending",
        metadata_json={"created_by": ctx.user_id, **dict(req.metadata_json or {})},
    )
    _apply_sop_fields(sop, req)
    db.add(sop)
    await _write_agency_audit_log(
        db,
        agency_id=agency.id,
        user_id=ctx.user_id,
        action="sop_draft_created",
        previous_state=None,
        new_state={"profile_id": profile.id, "sop": _sop_out(sop)},
        request=request,
    )
    await db.commit()
    await db.refresh(sop)
    return _sop_out(sop)


@app.get("/api/agency/sops/{sop_id}")
async def get_agency_sop(
    sop_id: str,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: fetch a single Phase 2A SOP/custom protocol record."""
    agency = await _effective_admin_agency(ctx, db, agency_id)
    sop = await _load_agency_sop_or_404(db, agency_id=agency.id, sop_id=sop_id)
    return _sop_out(sop)


@app.put("/api/agency/sops/{sop_id}")
async def update_agency_sop(
    sop_id: str,
    request: Request,
    req: AgencySOPUpdateRequest,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: edit a draft/rejected SOP record before resubmission."""
    agency = await _effective_admin_agency(ctx, db, agency_id)
    sop = await _load_agency_sop_or_404(db, agency_id=agency.id, sop_id=sop_id)
    if sop.status not in _SOP_EDITABLE_STATUSES:
        raise HTTPException(status_code=409, detail="Only draft or rejected SOPs can be edited")
    previous_state = _sop_out(sop)
    _apply_sop_fields(sop, req)
    if sop.status == "rejected":
        sop.status = "draft"
        sop.rejected_by = None
        sop.rejected_at = None
    sop.updated_at = datetime.utcnow()
    db.add(sop)
    await _write_agency_audit_log(
        db,
        agency_id=agency.id,
        user_id=ctx.user_id,
        action="sop_draft_updated",
        previous_state=previous_state,
        new_state=_sop_out(sop),
        request=request,
    )
    await db.commit()
    await db.refresh(sop)
    return _sop_out(sop)


@app.post("/api/agency/sops/{sop_id}/submit")
async def submit_agency_sop_for_review(
    sop_id: str,
    request: Request,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: submit a draft SOP for second-person review.

    One-person agencies are routed to `pending_external_review` instead of
    allowing self-approval.
    """
    agency = await _effective_admin_agency(ctx, db, agency_id)
    sop = await _load_agency_sop_or_404(db, agency_id=agency.id, sop_id=sop_id)
    if sop.status not in _SOP_EDITABLE_STATUSES:
        raise HTTPException(status_code=409, detail="Only draft or rejected SOPs can be submitted")
    reviewer_count = int((await db.execute(
        select(func.count(AgencyMember.id)).where(
            AgencyMember.agency_id == agency.id,
            AgencyMember.user_id != ctx.user_id,
            AgencyMember.role.in_(("admin", "instructor")),
        )
    )).scalar() or 0)
    previous_state = _sop_out(sop)
    sop.status = "pending_review" if reviewer_count > 0 or ctx.is_superuser else "pending_external_review"
    sop.submitted_by = ctx.user_id
    sop.submitted_at = datetime.utcnow()
    sop.approved_by = None
    sop.approved_at = None
    sop.rejected_by = None
    sop.rejected_at = None
    sop.updated_at = datetime.utcnow()
    metadata = dict(sop.metadata_json or {})
    metadata["reviewer_count_at_submit"] = reviewer_count
    metadata["authoritative_runtime_use"] = False
    sop.metadata_json = metadata
    db.add(sop)
    await _write_agency_audit_log(
        db,
        agency_id=agency.id,
        user_id=ctx.user_id,
        action="sop_submitted",
        previous_state=previous_state,
        new_state=_sop_out(sop),
        request=request,
    )
    await db.commit()
    await db.refresh(sop)
    return _sop_out(sop)


@app.post("/api/agency/sops/{sop_id}/review")
async def review_agency_sop(
    sop_id: str,
    request: Request,
    req: AgencySOPReviewRequest,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    """Instructor/admin: review a submitted SOP and activate approved rules for Phase 2B."""
    agency = await _effective_admin_agency(ctx, db, agency_id)
    sop = await _load_agency_sop_or_404(db, agency_id=agency.id, sop_id=sop_id)
    if sop.status not in {"pending_review", "pending_external_review"}:
        raise HTTPException(status_code=409, detail="Only submitted SOPs can be reviewed")
    if sop.submitted_by and sop.submitted_by == ctx.user_id:
        raise HTTPException(status_code=403, detail="Submitters cannot approve or reject their own SOPs")
    previous_state = _sop_out(sop)
    metadata = dict(sop.metadata_json or {})
    if req.comment:
        metadata.setdefault("review_comments", []).append({
            "user_id": ctx.user_id,
            "decision": req.decision,
            "comment": req.comment.strip(),
            "timestamp": datetime.utcnow().isoformat(),
        })
    metadata["authoritative_runtime_use"] = req.decision == "approve"
    now = datetime.utcnow()
    if req.decision == "approve":
        sop.status = "active"
        sop.approved_by = ctx.user_id
        sop.approved_at = now
        sop.rejected_by = None
        sop.rejected_at = None
    else:
        sop.status = "rejected"
        sop.rejected_by = ctx.user_id
        sop.rejected_at = now
        sop.approved_by = None
        sop.approved_at = None
    sop.metadata_json = metadata
    sop.updated_at = now
    db.add(sop)
    await _write_agency_audit_log(
        db,
        agency_id=agency.id,
        user_id=ctx.user_id,
        action="sop_reviewed",
        previous_state=previous_state,
        new_state=_sop_out(sop),
        request=request,
    )
    await db.commit()
    await db.refresh(sop)
    return _sop_out(sop)


class JoinAgencyRequest(BaseModel):
    agency_id:        str
    agency_join_code: Optional[str] = None
    provider_level:   str = "EMT"
    mca:              Optional[str] = None   # None → inherit from agency config


@app.post("/api/agencies/join", status_code=status.HTTP_201_CREATED)
async def join_agency(
    req: JoinAgencyRequest,
    token: str = Depends(_extract_token),
    db: AsyncSession = Depends(get_db),
):
    """Add the current user to an agency using a join code or open-join. Stays in current context."""
    from sqlalchemy.exc import IntegrityError

    payload = _decode_token(token)
    user_id = payload["sub"]

    # Verify agency using agency_id as authoritative selector
    a_result = await db.execute(select(Agency).where(Agency.id == req.agency_id))
    agency = a_result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=400, detail="Agency not found")

    if agency.is_open_join:
        if req.agency_join_code:
            raise HTTPException(status_code=400, detail="This agency does not use a join code")
    else:
        if not req.agency_join_code:
            raise HTTPException(status_code=400, detail="This agency requires a join code")
        if agency.agency_join_code != req.agency_join_code:
            raise HTTPException(status_code=400, detail="Invalid join code for the selected agency")

    membership = AgencyMember(
        user_id=user_id,
        agency_id=req.agency_id,
        role="student",
        provider_level=_resolve_member_provider_level(req.provider_level, agency.config),
        mca=_resolve_member_mca(req.mca, agency.config),
    )
    await _assign_agency_default_protocol_profile(db, agency=agency, membership=membership)
    db.add(membership)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="You are already a member of this agency")

    # Return updated membership list so the frontend can update membership_count immediately
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()

    agency_ids = [m.agency_id for m in user.memberships]
    all_agencies_result = await db.execute(select(Agency).where(Agency.id.in_(agency_ids)))
    agency_map = {a.id: a.name for a in all_agencies_result.scalars().all()}

    return {
        "status":           "joined",
        "membership_count": len(user.memberships),
        "memberships": [
            {
                "agency_id":      m.agency_id,
                "agency_name":    agency_map.get(m.agency_id, m.agency_id),
                "role":           m.role,
                "provider_level": m.provider_level,
                "mca":            m.mca,
                "protocol_profile_id": m.protocol_profile_id,
                "protocol_profile_assignment_source": m.protocol_profile_assignment_source,
            }
            for m in user.memberships
        ],
    }


# ── Session helper ────────────────────────────────────────────────────────────

async def _get_owned_session(
    session_id: str,
    db: AsyncSession,
    ctx: ActiveContext,
    lock: bool = False,
) -> SimSession:
    q = select(SimSession).where(SimSession.id == session_id)
    if lock:
        q = q.with_for_update()
    result = await db.execute(q)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if not ctx.is_superuser and session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=403, detail="Session belongs to a different agency")
    return session


# ── Procedure endpoints ───────────────────────────────────────────────────────

@app.get("/api/procedures")
def list_available_procedures(mca: str = None, level: str = None):
    return list_procedures(mca=mca, level=level)


@app.get("/api/procedures/{ref:path}")
def get_procedure(ref: str):
    try:
        return load_procedure(ref)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Procedure not found: {ref}")


# ── Challenge endpoints ───────────────────────────────────────────────────────

def _challenge_out(ch: Challenge, earned_badge_ids: set[str], completion_counts: dict = None) -> dict:
    """Serialize a Challenge row for API output."""
    badge_id     = f"ch_{ch.id}"
    requirements = _resolve_requirements(ch)
    out = {
        "id":                ch.id,
        "badge_id":          badge_id,
        "name":              ch.name,
        "description":       ch.description or "",
        "icon":              ch.icon or "🏅",
        "requirements":      requirements,
        "is_active":         ch.is_active,
        "earned":            badge_id in earned_badge_ids,
        "created_at":        ch.created_at.isoformat() if ch.created_at else None,
        "time_goal_minutes": ch.time_goal_minutes,
        "repeatable":        bool(ch.repeatable),
    }
    if completion_counts is not None:
        out["completion_counts"] = completion_counts
    return out


@app.get("/api/challenges")
async def list_challenges(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Student-facing: return active challenges for the current agency with per-user progress."""
    if not ctx.agency_id:
        return []

    result = await db.execute(
        select(Challenge).where(
            Challenge.agency_id == ctx.agency_id,
            Challenge.is_active == True,  # noqa: E712
        ).order_by(Challenge.created_at)
    )
    challenges = result.scalars().all()
    if not challenges:
        return []

    # Fetch user's completed full sessions at this agency for progress tracking
    # Drill sessions are excluded — they don't satisfy prerequisites
    sessions_result = await db.execute(
        select(SimSession.scenario_id, SimSession.score, SimSession.narrative_data).where(
            SimSession.user_id   == ctx.user_id,
            SimSession.agency_id == ctx.agency_id,
            SimSession.ended_at.isnot(None),
        )
    )
    completed_rows = sessions_result.all()
    best_scores: dict[str, int] = {}
    completed_scenario_ids: set[str] = set()
    for row in completed_rows:
        sid, score, nd = row.scenario_id, (row.score or 0), (row.narrative_data or {})
        if nd.get("drill"):
            continue  # drill sessions don't satisfy challenge prerequisites
        completed_scenario_ids.add(sid)
        best_scores[sid] = max(best_scores.get(sid, 0), score)

    badges_row = (await db.execute(
        select(User.badges).where(User.id == ctx.user_id)
    )).one_or_none()
    earned_badge_ids = set(badges_row.badges or [] if badges_row else [])
    user = await db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    best_drill_scores = await _best_challenge_drill_scores(user=user, db=db)

    repeatable_ids = [ch.id for ch in challenges if ch.repeatable]
    latest_attempts = await _latest_challenge_attempts(ctx.user_id, repeatable_ids, db)
    completed_attempt_counts: dict[str, int] = {}
    if repeatable_ids:
        count_rows = await db.execute(
            select(ChallengeAttempt.challenge_id, func.count())
            .where(
                ChallengeAttempt.user_id == ctx.user_id,
                ChallengeAttempt.challenge_id.in_(repeatable_ids),
                ChallengeAttempt.status == "completed",
            )
            .group_by(ChallengeAttempt.challenge_id)
        )
        completed_attempt_counts = {row[0]: int(row[1] or 0) for row in count_rows.all()}

    # Fetch CE seconds per activity (scenario or drill) — only :session rows to avoid
    # double-counting the legacy wall-clock entries written by the non-debrief-only path.
    ce_result = await db.execute(
        select(CeTimeLog.scenario_id, func.sum(CeTimeLog.seconds))
        .where(
            CeTimeLog.user_id == ctx.user_id,
            CeTimeLog.scenario_id.isnot(None),
            CeTimeLog.source_id.like("%:session"),
        )
        .group_by(CeTimeLog.scenario_id)
    )
    ce_by_activity: dict[str, int] = {row[0]: int(row[1] or 0) for row in ce_result.all()}

    output = []
    completed_any_attempt = False
    for ch in challenges:
        requirements = _resolve_requirements(ch)
        if ch.repeatable:
            attempt = latest_attempts.get(ch.id)
            out = _challenge_out(ch, earned_badge_ids)
            if attempt:
                was_status = attempt.status
                progress = await _complete_repeatable_attempt_if_ready(
                    ch=ch,
                    attempt=attempt,
                    user=user,
                    db=db,
                    revealed_scenario_ids=completed_scenario_ids,
                )
                completed_now = was_status != attempt.status and attempt.status == "completed"
                if completed_now:
                    completed_any_attempt = True
                out["requirements_progress"] = progress["requirements_progress"]
                out["scenarios_completed"] = progress["scenarios_completed"]
                out["scenarios_total"] = progress["scenarios_total"]
                out["challenge_ce_seconds"] = progress["challenge_ce_seconds"]
                out["requirements_met"] = progress["requirements_met"]
                out["time_goal_met"] = progress["time_goal_met"]
                out["earned"] = attempt.status == "completed"
                out["attempt"] = _challenge_attempt_out(attempt)
            else:
                completed_now = False
                progress = _empty_challenge_progress(ch, completed_scenario_ids)
                out["requirements_progress"] = progress["requirements_progress"]
                out["scenarios_completed"] = progress["scenarios_completed"]
                out["scenarios_total"] = progress["scenarios_total"]
                out["challenge_ce_seconds"] = progress["challenge_ce_seconds"]
                out["requirements_met"] = progress["requirements_met"]
                out["time_goal_met"] = progress["time_goal_met"]
                out["earned"] = False
                out["attempt"] = None
            out["completion_count"] = completed_attempt_counts.get(ch.id, 0) + (1 if completed_now else 0)
            output.append(out)
            continue

        req_progress = []
        total_needed = total_done = 0
        all_scenario_ids: set[str] = set()
        all_activity_ids: set[str] = set()
        for req in requirements:
            ids    = _req_scenario_ids(req)
            drill_ids = _req_drill_ids(req)
            rtype  = req.get("type", "specific")
            done   = [sid for sid in ids if best_scores.get(sid, 0) >= PASSING_SCORE]
            drill_done = [
                did for did in drill_ids
                if best_drill_scores.get(_canonical_challenge_drill_id(did), 0) >= _challenge_drill_pass_threshold(did)
            ]
            item_count = len(ids) + len(drill_ids)
            needed = req.get("count", item_count) if rtype == "any_n" else item_count
            completed_count = len(done) + len(drill_done)
            req_progress.append({
                "type":          rtype,
                "label":         req.get("label", ""),
                "scenario_ids":  ids,
                "scenario_titles": _challenge_scenario_titles(ids, completed_scenario_ids),
                "drill_ids":     drill_ids,
                "completed_ids": done,
                "completed_drill_ids": drill_done,
                "completed":     min(completed_count, needed),
                "needed":        needed,
            })
            total_done   += min(completed_count, needed)
            total_needed += needed
            all_scenario_ids.update(ids)
            all_activity_ids.update(ids)
            for drill_id in drill_ids:
                all_activity_ids.update(_challenge_drill_activity_ids(drill_id))

        challenge_ce_seconds = sum(ce_by_activity.get(aid, 0) for aid in all_activity_ids)

        out = _challenge_out(ch, earned_badge_ids)
        out["requirements_progress"]  = req_progress
        out["scenarios_completed"]    = total_done
        out["scenarios_total"]        = total_needed
        out["challenge_ce_seconds"]   = challenge_ce_seconds
        output.append(out)

    if completed_any_attempt:
        await db.commit()

    return output


@app.post("/api/challenges/{challenge_id}/attempts", status_code=201)
@limiter.limit(f"{settings.rate_limit_session_write}/minute")
async def start_challenge_attempt(
    request: Request,
    challenge_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Start or resume a learner-scoped attempt for a repeatable challenge."""
    if not ctx.agency_id:
        raise HTTPException(status_code=403, detail="No active agency")

    ch = await db.get(Challenge, challenge_id)
    if not ch or ch.agency_id != ctx.agency_id or not ch.is_active:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if not ch.repeatable:
        raise HTTPException(status_code=400, detail="Challenge is not repeatable")

    active_result = await db.execute(
        select(ChallengeAttempt)
        .where(
            ChallengeAttempt.challenge_id == challenge_id,
            ChallengeAttempt.user_id == ctx.user_id,
            ChallengeAttempt.status == "active",
        )
        .order_by(ChallengeAttempt.started_at.desc())
    )
    active_attempt = active_result.scalars().first()
    if active_attempt:
        return {"ok": True, "attempt": _challenge_attempt_out(active_attempt)}

    max_result = await db.execute(
        select(func.max(ChallengeAttempt.attempt_number)).where(
            ChallengeAttempt.challenge_id == challenge_id,
            ChallengeAttempt.user_id == ctx.user_id,
        )
    )
    next_attempt_number = int(max_result.scalar() or 0) + 1
    attempt = ChallengeAttempt(
        id=str(uuid.uuid4()),
        challenge_id=challenge_id,
        agency_id=ctx.agency_id,
        user_id=ctx.user_id,
        attempt_number=next_attempt_number,
        status="active",
        started_at=datetime.utcnow(),
    )
    db.add(attempt)
    await db.commit()
    return {"ok": True, "attempt": _challenge_attempt_out(attempt)}


@app.get("/api/admin/challenges")
async def admin_list_challenges(
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: list challenges with per-member completion counts."""
    agency_id = ctx.agency_id
    if not agency_id:
        return []

    result = await db.execute(
        select(Challenge).where(Challenge.agency_id == agency_id).order_by(Challenge.created_at)
    )
    challenges = result.scalars().all()

    # Members of this agency
    m_result = await db.execute(
        select(AgencyMember).where(AgencyMember.agency_id == agency_id)
    )
    members = m_result.scalars().all()
    member_count = len(members)

    # All completed sessions for this agency
    s_result = await db.execute(
        select(SimSession.user_id, SimSession.scenario_id, SimSession.score).where(
            SimSession.agency_id == agency_id,
            SimSession.ended_at.isnot(None),
        )
    )
    session_rows = s_result.all()

    # Build best score per (user_id, scenario_id)
    best: dict[tuple, int] = {}
    for row in session_rows:
        key = (row.user_id, row.scenario_id)
        best[key] = max(best.get(key, 0), row.score or 0)

    # Fetch earned badges for all members
    user_ids = [m.user_id for m in members]
    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    users = {u.id: u for u in users_result.scalars().all()}
    repeatable_ids = [ch.id for ch in challenges if ch.repeatable]
    repeatable_completed_users: dict[str, set[str]] = {}
    if repeatable_ids and user_ids:
        attempts_result = await db.execute(
            select(ChallengeAttempt.challenge_id, ChallengeAttempt.user_id)
            .where(
                ChallengeAttempt.challenge_id.in_(repeatable_ids),
                ChallengeAttempt.user_id.in_(user_ids),
                ChallengeAttempt.status == "completed",
            )
        )
        for challenge_id, user_id in attempts_result.all():
            repeatable_completed_users.setdefault(challenge_id, set()).add(user_id)

    output = []
    for ch in challenges:
        badge_id = f"ch_{ch.id}"
        if ch.repeatable:
            earned_count = len(repeatable_completed_users.get(ch.id, set()))
        else:
            earned_count = sum(
                1 for uid in user_ids
                if badge_id in set(users.get(uid, User()).badges or [])
            )
        out = _challenge_out(ch, set(), {"earned": earned_count, "total": member_count})
        output.append(out)

    return output


@app.get("/api/admin/challenges/{challenge_id}/members")
async def admin_challenge_members(
    challenge_id: str,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    """Return per-member progress for a specific challenge."""
    ch = await db.get(Challenge, challenge_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if ch.agency_id != ctx.agency_id and not ctx.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    requirements = _resolve_requirements(ch)
    badge_id     = f"ch_{ch.id}"

    m_result = await db.execute(
        select(AgencyMember).where(AgencyMember.agency_id == ch.agency_id)
    )
    members = m_result.scalars().all()
    user_ids = [m.user_id for m in members]

    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    users_map = {u.id: u for u in users_result.scalars().all()}

    latest_attempt_by_user: dict[str, ChallengeAttempt] = {}
    completed_attempt_count_by_user: dict[str, int] = {}
    if ch.repeatable and user_ids:
        attempts_result = await db.execute(
            select(ChallengeAttempt)
            .where(
                ChallengeAttempt.challenge_id == ch.id,
                ChallengeAttempt.user_id.in_(user_ids),
            )
            .order_by(ChallengeAttempt.user_id, ChallengeAttempt.started_at.desc())
        )
        for attempt in attempts_result.scalars().all():
            latest_attempt_by_user.setdefault(attempt.user_id, attempt)
            if attempt.status == "completed":
                completed_attempt_count_by_user[attempt.user_id] = completed_attempt_count_by_user.get(attempt.user_id, 0) + 1

    s_result = await db.execute(
        select(SimSession.user_id, SimSession.scenario_id, SimSession.score, SimSession.narrative_data).where(
            SimSession.agency_id == ch.agency_id,
            SimSession.ended_at.isnot(None),
        )
    )
    all_best: dict[tuple, int] = {}
    for row in s_result.all():
        nd = row.narrative_data or {}
        if nd.get("drill"):
            continue  # drill sessions don't satisfy challenge prerequisites
        key = (row.user_id, row.scenario_id)
        all_best[key] = max(all_best.get(key, 0), row.score or 0)

    output = []
    for uid in user_ids:
        user = users_map.get(uid)
        if not user:
            continue
        attempt = latest_attempt_by_user.get(uid)
        if ch.repeatable and attempt:
            progress = await _challenge_progress_for_window(
                ch=ch,
                user_id=uid,
                agency_id=ch.agency_id,
                db=db,
                user=user,
                started_at=attempt.started_at,
                ended_at=attempt.completed_at if attempt.status == "completed" else None,
            )
            req_progress = progress["requirements_progress"]
            earned = completed_attempt_count_by_user.get(uid, 0) > 0
        elif ch.repeatable:
            req_progress = _empty_challenge_progress(ch)["requirements_progress"]
            earned = False
        else:
            best_scores = {sid: score for (u, sid), score in all_best.items() if u == uid}
            best_drill_scores = await _best_challenge_drill_scores(user=user, db=db)
            req_progress = []
            for req in requirements:
                ids   = _req_scenario_ids(req)
                drill_ids = _req_drill_ids(req)
                rtype = req.get("type", "specific")
                done  = [sid for sid in ids if best_scores.get(sid, 0) >= PASSING_SCORE]
                drill_done = [
                    did for did in drill_ids
                    if best_drill_scores.get(_canonical_challenge_drill_id(did), 0) >= _challenge_drill_pass_threshold(did)
                ]
                item_count = len(ids) + len(drill_ids)
                needed = req.get("count", item_count) if rtype == "any_n" else item_count
                completed_count = len(done) + len(drill_done)
                req_progress.append({
                    "type":          rtype,
                    "label":         req.get("label", ""),
                    "completed":     min(completed_count, needed),
                    "needed":        needed,
                    "completed_ids": done,
                    "completed_drill_ids": drill_done,
                })
            earned = badge_id in set(user.badges or [])
        display_name = " ".join(filter(None, [user.first_name, user.last_name])) or user.username
        output.append({
            "user_id":              uid,
            "username":             user.username,
            "display_name":         display_name,
            "earned":               earned,
            "completion_count":      completed_attempt_count_by_user.get(uid, 0) if ch.repeatable else (1 if earned else 0),
            "attempt":              _challenge_attempt_out(attempt) if ch.repeatable else None,
            "requirements_progress": req_progress,
        })

    output.sort(key=lambda x: (not x["earned"], x["display_name"].lower()))
    return output


@app.post("/api/admin/challenges", status_code=201)
async def create_challenge(
    req: ChallengeCreateRequest,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.agency_id:
        raise HTTPException(status_code=403, detail="No active agency")

    # Collect all scenario_ids from requirements for the legacy column
    all_scenario_ids = list({sid for r in req.requirements for sid in _req_scenario_ids(r)})

    ch = Challenge(
        id                = str(uuid.uuid4()),
        agency_id         = ctx.agency_id,
        name              = req.name.strip(),
        description       = (req.description or "").strip() or None,
        icon              = (req.icon or "").strip() or None,
        scenario_ids      = all_scenario_ids,
        requirements      = req.requirements or [],
        min_score         = PASSING_SCORE,
        is_active         = True,
        repeatable        = bool(req.repeatable),
        created_by        = ctx.user_id,
        time_goal_minutes = req.time_goal_minutes if req.time_goal_minutes and req.time_goal_minutes > 0 else None,
    )
    db.add(ch)
    await db.flush()  # get ch.id before retroactive check

    # Retroactive: award to any member who already qualifies
    m_result = await db.execute(
        select(AgencyMember).where(AgencyMember.agency_id == ctx.agency_id)
    )
    for m in m_result.scalars().all():
        user = await db.get(User, m.user_id)
        if user:
            await _check_and_award_challenges(user, ctx.agency_id, db)

    await db.commit()
    user_self = await db.get(User, ctx.user_id)
    return _challenge_out(ch, set(user_self.badges or []))


@app.put("/api/admin/challenges/{challenge_id}")
async def update_challenge(
    challenge_id: str,
    req: ChallengeUpdateRequest,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    ch = await db.get(Challenge, challenge_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if ch.agency_id != ctx.agency_id and not ctx.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    scenarios_changed = False
    if req.name              is not None: ch.name              = req.name.strip()
    if req.description       is not None: ch.description       = req.description.strip() or None
    if req.icon              is not None: ch.icon              = req.icon.strip() or None
    if req.is_active         is not None: ch.is_active         = req.is_active
    if req.repeatable        is not None: ch.repeatable        = bool(req.repeatable)
    if req.time_goal_minutes is not None:
        ch.time_goal_minutes = req.time_goal_minutes if req.time_goal_minutes > 0 else None
    if req.requirements is not None:
        ch.requirements  = req.requirements
        ch.scenario_ids  = list({sid for r in req.requirements for sid in _req_scenario_ids(r)})
        scenarios_changed = True

    if scenarios_changed and ch.is_active:
        m_result = await db.execute(
            select(AgencyMember).where(AgencyMember.agency_id == ch.agency_id)
        )
        for m in m_result.scalars().all():
            user = await db.get(User, m.user_id)
            if user:
                await _check_and_award_challenges(user, ch.agency_id, db)

    await db.commit()
    user_self = await db.get(User, ctx.user_id)
    return _challenge_out(ch, set(user_self.badges or []))


@app.delete("/api/admin/challenges/{challenge_id}", status_code=200)
async def delete_challenge(
    challenge_id: str,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate (soft-delete) a challenge. Earned badges are retained."""
    ch = await db.get(Challenge, challenge_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if ch.agency_id != ctx.agency_id and not ctx.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")
    ch.is_active = False
    await db.commit()
    return {"ok": True}


# ── Scenario endpoints ────────────────────────────────────────────────────────

@app.get("/api/scenarios")
def list_available_scenarios():
    return list_scenarios()


async def _apply_protocol_snapshot(
    session: SimSession,
    db: AsyncSession,
    *,
    agency_id: str | None,
    user_id: str | None = None,
    mca: str | None,
    protocol_profile_id: str | None = None,
) -> None:
    """Pin a session to the current resolved protocol snapshot."""
    effective_profile_id = protocol_profile_id
    if agency_id and user_id:
        membership = (await db.execute(
            select(AgencyMember).where(
                AgencyMember.agency_id == agency_id,
                AgencyMember.user_id == user_id,
            )
        )).scalar_one_or_none()
        if (
            membership
            and membership.protocol_profile_id
            and getattr(membership, "protocol_profile_assignment_source", "default") == "manual"
        ):
            effective_profile_id = membership.protocol_profile_id
        elif membership:
            effective_profile_id = None
    try:
        snapshot = await create_protocol_snapshot(db, agency_id, mca, effective_profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    session.protocol_snapshot_id = snapshot.id
    session.protocol_profile_id = (snapshot.compiled_json or {}).get("protocol_profile_id")
    session.protocol_hash = snapshot.content_hash
    session.legacy_protocol = False
    try:
        scenario = load_scenario(session.scenario_id)
        sop_result = await db.execute(
            select(AgencySOP).where(
                AgencySOP.agency_id == agency_id,
                AgencySOP.protocol_profile_id == session.protocol_profile_id,
                AgencySOP.status == "active",
            )
        )
        active_sops = list(sop_result.scalars().all())
        excerpt = build_protocol_excerpt_locked(
            snapshot.compiled_json or {},
            scenario,
            sops=active_sops,
            authoritative=True,
            allow_authoritative=True,
        )
        session.active_sop_ids = excerpt.get("sop_ids") or []
        session.effective_protocol_excerpt = excerpt
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Scenario not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/scenarios/{scenario_id}")
async def get_scenario(
    scenario_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        scenario = load_scenario(scenario_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Scenario not found")
    agency_dict = await load_agency(ctx.agency_id, db)
    return get_public_scenario_data(adapt_scenario_to_context(scenario, agency_dict, ctx.mca))


# ── Session endpoints ─────────────────────────────────────────────────────────

@app.post("/api/sessions")
@limiter.limit(f"{settings.rate_limit_session_start}/minute")
async def start_session(
    request: Request,
    req: StartSessionRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        scenario = load_scenario(req.scenario_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Scenario not found")

    start_drill = req.start_drill
    if req.drill_source == "station1_cpr_training":
        if req.scenario_id != "adult_cardiac_arrest_01_bls":
            raise HTTPException(status_code=400, detail="Invalid CPR training drill scenario")
        start_drill = True

    narrative_data = None
    if start_drill:
        narrative_data = {"drill": True}
        if req.drill_source:
            narrative_data["drill_source"] = req.drill_source

    session = SimSession(
        id=str(uuid.uuid4()),
        user_id=ctx.user_id,
        agency_id=ctx.agency_id,    # None for superuser — nullable column
        agency_file=ctx.agency_file, # None for superuser — nullable column
        scenario_id=req.scenario_id,
        start_time=datetime.utcnow(),
        provider_level=ctx.provider_level,
        mca=ctx.mca,
        narrative_data=narrative_data,
    )
    # Orientation uses a static debrief — no LLM call, no protocol matching needed.
    # Skip the 4-6 sequential DB queries in _apply_protocol_snapshot to keep launch fast.
    if not scenario.get("is_orientation"):
        await _apply_protocol_snapshot(
            session,
            db,
            agency_id=ctx.agency_id,
            user_id=ctx.user_id,
            mca=ctx.mca,
            protocol_profile_id=ctx.protocol_profile_id,
        )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return {
        "session_id":     session.id,
        "username":       ctx.username,
        "started_at":     session.start_time,
        "provider_level": session.provider_level,
        "mca":            session.mca,
    }


@app.post("/api/sessions/{session_id}/scene-entry")
async def submit_scene_entry(
    session_id: str,
    req: SceneEntryRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Record PPE selection, scene approach, and PAT assessment made before patient contact.

    Rate limit exempt: one-shot per session. Repeated calls are silently idempotent
    (session.scene_entry is overwritten) — no LLM call, minimal DB write.
    """
    session = await _get_owned_session(session_id, db, ctx)
    session.scene_entry = req.model_dump()
    flag_modified(session, "scene_entry")
    await db.commit()
    return {"status": "ok"}


@app.get("/api/sessions/{session_id}")
async def get_session_info(
    session_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_owned_session(session_id, db, ctx)
    elapsed = (datetime.utcnow() - session.start_time).total_seconds()
    return {
        "session_id":            session.id,
        "username":              ctx.username,
        "scenario_id":           session.scenario_id,
        "started_at":            session.start_time,
        "elapsed_seconds":       int(elapsed),
        "interventions_applied": [i.name for i in session.interventions],
        "treatment_submitted":   session.treatment_submitted,
        "message_count":         len(session.messages),
    }


@app.get("/api/sessions/{session_id}/vitals")
async def get_vitals(
    session_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_owned_session(session_id, db, ctx)
    scenario = load_scenario(session.scenario_id)
    vitals = calculate_vitals(session, scenario)
    elapsed = (datetime.utcnow() - session.start_time).total_seconds()
    return {
        "vitals":                vitals,
        "elapsed_seconds":       int(elapsed),
        "interventions_applied": [i.name for i in session.interventions],
    }


# ── Vitals WebSocket ──────────────────────────────────────────────────────────

@app.websocket("/ws/vitals/{session_id}")
async def vitals_ws(session_id: str, websocket: WebSocket):
    ticket_id = websocket.query_params.get("ticket")
    if not ticket_id:
        await websocket.close(code=4001, reason="Missing ticket")
        return
    async with async_session_factory() as db:
        result = await db.execute(
            update(WsTicket)
            .where(
                WsTicket.ticket_id == ticket_id,
                WsTicket.consumed == False,  # noqa: E712
                WsTicket.expires_at > datetime.utcnow(),
            )
            .values(consumed=True)
            .returning(WsTicket.user_id, WsTicket.agency_id)
        )
        row = result.fetchone()
        if not row:
            await websocket.close(code=4001, reason="Invalid or expired ticket")
            return
        user_id = row.user_id
        agency_id = row.agency_id
        is_su = False
        await db.commit()

    await websocket.accept()

    async with async_session_factory() as db:
        result = await db.execute(select(SimSession).where(SimSession.id == session_id))
        session = result.scalar_one_or_none()
        if not session or session.user_id != user_id:
            await websocket.close(code=4004, reason="Session not found")
            return
        if not is_su and session.agency_id != agency_id:
            await websocket.close(code=4004, reason="Agency mismatch")
            return
        async with async_session_factory() as _adb:
            _agency = await load_agency(session.agency_id, _adb)
        scenario = adapt_scenario_to_context(load_scenario(session.scenario_id), _agency, session.mca, session.effective_protocol_excerpt)

    try:
        while True:
            async with async_session_factory() as db:
                result = await db.execute(select(SimSession).where(SimSession.id == session_id))
                session = result.scalar_one_or_none()
                if not session:
                    break
                snapshot = {
                    "start_time": session.start_time,
                    "interventions": [
                        {"name": i.name, "applied_at": i.applied_at}
                        for i in session.interventions
                    ],
                    "events": [
                        {
                            "event_type": ev.event_type,
                            "event_key": ev.event_key,
                            "event_data": ev.event_data,
                            "source": ev.source,
                            "occurred_at": ev.occurred_at,
                        }
                        for ev in (session.events or [])
                    ],
                }

            vitals  = calculate_vitals(snapshot, scenario)
            elapsed = int((datetime.utcnow() - snapshot["start_time"]).total_seconds())

            await websocket.send_json({
                "vitals":                vitals,
                "elapsed_seconds":       elapsed,
                "interventions_applied": [i["name"] for i in snapshot["interventions"]],
            })
            await asyncio.sleep(3)

    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


# ── Lexi Group WebSocket ─────────────────────────────────────────────────────

@app.websocket("/ws/lexi-group/{group_session_id}")
async def lexi_group_ws(group_session_id: str, websocket: WebSocket):
    ticket_id = websocket.query_params.get("ticket")
    if not ticket_id:
        await websocket.close(code=4001, reason="Missing ticket")
        return
    async with async_session_factory() as db:
        result = await db.execute(
            update(WsTicket)
            .where(
                WsTicket.ticket_id == ticket_id,
                WsTicket.consumed == False,  # noqa: E712
                WsTicket.expires_at > datetime.utcnow(),
            )
            .values(consumed=True)
            .returning(WsTicket.user_id, WsTicket.agency_id)
        )
        row = result.fetchone()
        if not row:
            await websocket.close(code=4001, reason="Invalid or expired ticket")
            return
        user_id = row.user_id
        agency_id = row.agency_id
        await db.commit()

    await websocket.accept()
    async with async_session_factory() as db:
        session = await db.get(LexiGroupSession, group_session_id)
        if not session or session.agency_id != agency_id:
            await websocket.close(code=4004, reason="Group session not found")
            return
        if not any((p or {}).get("user_id") == user_id for p in (session.participants or [])):
            await websocket.close(code=4003, reason="Not a participant")
            return

        _LEXI_GROUP_WS.setdefault(group_session_id, {})[websocket] = user_id
        try:
            await websocket.send_json({"type": "state", "state": _build_group_public_state(session, user_id)})
        except Exception:
            ws_map = _LEXI_GROUP_WS.get(group_session_id, {})
            ws_map.pop(websocket, None)
            return

    try:
        while True:
            # Keep connection open; no client messages required for server-authoritative flow.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        sockets = _LEXI_GROUP_WS.get(group_session_id)
        if sockets:
            sockets.pop(websocket, None)
            if not sockets:
                _LEXI_GROUP_WS.pop(group_session_id, None)


# ── Primary impression challenge trigger (Phase 4) ───────────────────────────

def _intervention_triggers_impression_challenge(intervention_id: str, scenario: dict) -> bool:
    """Only medication administration should trigger the impression challenge.

    Oxygen is supportive care and may be appropriate before the learner has
    identified the root cause of hypoxia or distress. If no medication trigger
    occurs, the frontend opens the challenge before turnover/DMIST.
    """
    if not intervention_id:
        return False
    intervention = ((scenario.get("vitals") or {}).get("interventions") or {}).get(intervention_id) or {}
    return intervention.get("popup_type") == "medication"

async def _check_and_fire_primary_survey_milestone(
    session, scenario: dict, db
) -> dict | None:
    """Check whether the impression challenge should fire during the scenario.

    Idempotent — returns None immediately if the milestone has already fired.
    On first fire: emits a milestone_fired SessionEvent and returns challenge_data
    if scenario.impression_challenge.enabled is true; otherwise returns None.

    During the active scenario, only medication administration is allowed to
    trigger this challenge. Oxygen alone must not trigger it: oxygen is often
    appropriate supportive care before the learner has identified the etiology.
    If the challenge has not fired by turnover, the frontend opens it before the
    DMIST/handoff flow.
    """
    events = list(getattr(session, "events", None) or [])

    # Idempotent guard
    if any(
        getattr(ev, "event_type", "") == "milestone_fired"
        and getattr(ev, "event_key", "") == "primary_survey_complete"
        for ev in events
    ):
        return None

    # Medication intervention events are the deliberate "commit to treatment"
    # signal. Oxygen is intentionally excluded so students can correct hypoxia
    # while still working toward the root impression.
    medication_interventions = [
        ev for ev in events
        if getattr(ev, "event_type", "") == "intervention_applied"
        and getattr(ev, "source", "") == "backend_auto"
        and _intervention_triggers_impression_challenge(getattr(ev, "event_key", ""), scenario)
    ]
    user_message_count = len([
        m for m in (getattr(session, "messages", None) or [])
        if getattr(m, "role", "") == "user"
    ])

    # Require at least one medication intervention AND at least 3 student
    # messages. This keeps the modal from appearing before any assessment, while
    # allowing oxygen-only care to proceed uninterrupted.
    if not medication_interventions or user_message_count < 3:
        return None
    trigger = "medication_intervention"

    db.add(SessionEvent(
        session_id=session.id,
        event_type="milestone_fired",
        event_key="primary_survey_complete",
        event_data={"trigger": trigger},
        source="backend_auto",
        occurred_at=datetime.utcnow(),
    ))
    await db.commit()

    ic = scenario.get("impression_challenge") or {}
    if not ic.get("enabled"):
        return None

    return {
        "type": "impression",
        "challenge_id": "default",
        "data": {
            "title": "Clinical Impression",
            "subtitle": "Based on your primary survey — choose your working impression.",
            "prompt": ic.get("prompt", "Based on your initial assessment, what is your primary clinical impression?"),
            "options": ic.get("options", []),
        },
    }


# ── Chat endpoint (streaming SSE) ─────────────────────────────────────────────

@app.post("/api/chat")
@limiter.limit(f"{settings.rate_limit_chat}/minute")
async def chat(request: Request, req: ChatRequest, ctx: ActiveContext = Depends(get_active_context)):
    async with async_session_factory() as db:
        # SELECT FOR UPDATE: serializes concurrent chat writes on the same session.
        # The lock is held until db.commit() so auto-detect + message save are atomic
        # relative to concurrent intervention POSTs on this session. Released before
        # the LLM call, so no DB lock is held during network I/O.
        session = await _get_owned_session(req.session_id, db, ctx, lock=True)

        if session.treatment_submitted:
            raise HTTPException(
                status_code=400, detail="Session is complete — treatment already submitted"
            )

        agency_dict = await load_agency(session.agency_id, db)
        scenario = adapt_scenario_to_context(load_scenario(session.scenario_id), agency_dict, session.mca, session.effective_protocol_excerpt)
        _auto_detect_interventions(req.message, session, scenario, db)
        db.add(ChatMessage(
            session_id=session.id,
            role="user",
            content=req.message,
            timestamp=datetime.utcnow(),
        ))
        await db.commit()
        await db.refresh(session, attribute_names=["interventions", "messages", "events"])

        session_snapshot = {
            "id":             session.id,
            "start_time":     session.start_time,
            "scenario_id":    session.scenario_id,
            "provider_level": session.provider_level,
            "mca":            session.mca,
            "effective_protocol_excerpt": session.effective_protocol_excerpt,
            "interventions":  [{"name": i.name, "applied_at": i.applied_at} for i in session.interventions],
            "messages":       [{"role": m.role, "content": m.content} for m in session.messages],
            "events": [
                {
                    "event_type": ev.event_type,
                    "event_key": ev.event_key,
                    "event_data": ev.event_data,
                    "source": ev.source,
                    "occurred_at": ev.occurred_at,
                }
                for ev in (session.events or [])
            ],
        }

    async def generate():
        full_response = []
        for attempt in range(2):
            _attempt_chunks = []
            try:
                async for chunk in stream_chat_response(
                    session_snapshot,
                    scenario,
                    req.message,
                    agency_dict,
                    last_scene_speaker=req.last_scene_speaker,
                ):
                    _attempt_chunks.append(chunk)
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
            except AiProviderError as e:
                log.warning("chat.provider_error", session_id=session_snapshot.get("id"), attempt=attempt, kind=e.kind)
                yield f"data: {json.dumps({'type': 'provider_error', 'kind': e.kind})}\n\n"
                full_response.extend(_attempt_chunks)
                break
            except Exception as e:
                log.error("Chat stream failed for session %s attempt %d: %s: %s", session_snapshot.get("id"), attempt, type(e).__name__, e)
                yield f"data: {json.dumps({'text': '[An error occurred. Please try again.]'})}\n\n"
                full_response.extend(_attempt_chunks)
                break
            full_response.extend(_attempt_chunks)
            if _attempt_chunks:
                break
            log.warning("chat.empty_stream_retry", session_id=session_snapshot["id"], attempt=attempt + 1)
        if not full_response:
            log.warning("chat.empty_stream", session_id=session_snapshot["id"])
            yield f"data: {json.dumps({'text': '[No response — please try again]'})}\n\n"

        ai_text = "".join(full_response)
        _challenge_data = None
        async with async_session_factory() as save_db:
            save_db.add(ChatMessage(
                session_id=session_snapshot["id"],
                role="model",
                content=ai_text,
                timestamp=datetime.utcnow(),
            ))
            await save_db.commit()

            # Check primary survey milestone after every AI turn.
            # Reload session to pick up any SessionEvents added during this turn
            # (e.g., intervention_applied auto-detection from the user message).
            _fresh = await save_db.get(SimSession, session_snapshot["id"])
            if _fresh and not _fresh.treatment_submitted:
                _challenge_data = await _check_and_fire_primary_survey_milestone(
                    _fresh, scenario, save_db
                )

        if _challenge_data:
            yield f"data: {json.dumps({'challenge_available': _challenge_data})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


def _build_session_timeline(
    session,
    scenario: dict,
    agency_dict: dict | None = None,
    scene_entry: dict | None = None,
    session_events: list | None = None,
) -> list[dict]:
    """Build a debrief checklist/timeline for student feedback.

    The output mixes:
    - scene-entry credited items (PPE / PAT),
    - core assessment milestones (exam/history, vitals, lung sounds),
    - critical actions and recommended actions from the scenario,
    - actually applied interventions with timestamps.

    Status values:
    - `applied`: completed / correctly done (green)
    - `missed`: not done (red)
    - `out_of_order`: done, but after a protocol-required baseline assessment should
      have occurred first (yellow)
    - `informational`: grace / auto-dispatch / non-penalized note (blue)
    """
    if not session.start_time:
        return []

    # ── Resolve effective provider level after agency cap ─────────────────────
    _level_key_map = {
        "MFR": "MFR", "EMR": "MFR",
        "EMT": "EMT", "EMT-B": "EMT", "BLS": "EMT",
        "AEMT": "AEMT",
        "PARAMEDIC": "Paramedic", "ALS": "Paramedic",
    }
    raw_level = (getattr(session, "provider_level", None) or "EMT").upper()
    agency_cap = (agency_dict or {}).get("provider_level_cap") if agency_dict else None
    eff_level_raw = _effective_level(raw_level, agency_cap)
    level_key = _level_key_map.get(eff_level_raw.upper(), "EMT")

    t0 = session.start_time
    interventions_data = scenario.get("vitals", {}).get("interventions", {})
    findings = sorted(list(getattr(session, "findings", None) or []), key=lambda f: f.captured_at or t0)
    user_message_rows = [
        m for m in list(getattr(session, "messages", None) or [])
        if getattr(m, "role", "") == "user"
    ]
    user_messages = [(m.content or "").lower() for m in user_message_rows]
    user_text = "\n".join(user_messages)
    # Prefer the explicit scene_entry parameter (passed from the same load that built the
    # debrief prompt) to guard against SQLAlchemy attribute expiry on the session object
    # after a long async LLM call.
    se = (scene_entry if isinstance(scene_entry, dict) else None) \
         or (getattr(session, "scene_entry", None) if isinstance(getattr(session, "scene_entry", None), dict) else None) \
         or {}
    has_scene_safety_entry = bool((se.get("ppe_donned") or []) or se.get("scene_approach"))
    pat_recorded = bool(se.get("pat_assessment"))
    _states_blob = getattr(session, "checklist_states", None) or {}
    _state_rows = list(_states_blob.get("item_states", [])) if isinstance(_states_blob, dict) else []

    def _item_state_done(*item_ids: str) -> bool:
        wanted = set(item_ids)
        for row in _state_rows:
            item_id = str(row.get("item_id") or "")
            if item_id in wanted or any(item_id.endswith(f".{wanted_id}") for wanted_id in wanted):
                if row.get("state") in {"satisfied", "partial"}:
                    return True
        return False

    def _item_state_row(*item_ids: str) -> dict | None:
        wanted = set(item_ids)
        for row in _state_rows:
            item_id = str(row.get("item_id") or "")
            if item_id in wanted or any(item_id.endswith(f".{wanted_id}") for wanted_id in wanted):
                return row
        return None

    def _item_state_value(*item_ids: str) -> str | None:
        """Return the adjudicated state string for the first matching item, or None if absent."""
        return (_item_state_row(*item_ids) or {}).get("state")

    def _parse_evidence_timestamp(raw: str | None):
        if not raw:
            return None
        try:
            value = str(raw)
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except (TypeError, ValueError):
            return None

    def _item_state_evidence_time(*item_ids: str):
        row = _item_state_row(*item_ids)
        if not row:
            return None
        for ref in row.get("evidence_references") or []:
            if not isinstance(ref, dict):
                continue
            parsed = _parse_evidence_timestamp(ref.get("timestamp"))
            if parsed:
                return parsed
        return None

    has_scene_safety_entry = has_scene_safety_entry or _item_state_done(
        "scene_safety",
        "ppe",
        "ems.medical.scene_safety",
        "ems.medical.ppe",
        "ems.trauma.scene_safety",
        "ems.trauma.ppe",
        "nremt_trauma.scene_safety",
        "nremt_trauma.ppe_precautions",
    )
    pat_recorded = pat_recorded or _item_state_done("pat_assessment")

    applied_ids = {i.name for i in session.interventions}
    critical_actions = scenario.get("correct_treatment", {}).get("critical_actions", [])
    recommended_actions = scenario.get("correct_treatment", {}).get("recommended_actions", [])
    timeline: list[dict] = []

    # Derive CPR outcome for gating post-ROSC timeline rows
    _cpr_rosc_achieved = False
    for _ev in (session_events or []):
        _ev_type = getattr(_ev, "event_type", None) if not isinstance(_ev, dict) else _ev.get("event_type")
        _ev_data = getattr(_ev, "event_data", None) if not isinstance(_ev, dict) else _ev.get("event_data")
        if _ev_type == "challenge_completed" and isinstance(_ev_data, dict):
            if _ev_data.get("outcome") == "rosc":
                _cpr_rosc_achieved = True
            break

    def _elapsed(ts):
        return round((ts - t0).total_seconds() / 60, 1) if ts else None

    def _first_finding_time(finding_type: str, key_pattern: str | None = None):
        for f in findings:
            if f.finding_type != finding_type:
                continue
            if key_pattern and not re.search(key_pattern, f.key or "", re.IGNORECASE):
                continue
            return f.captured_at
        return None

    def _first_standard_vital_time():
        """Return first measured vital sign time, excluding AVPU/GCS and qualitative pulse checks."""
        standard_vital_re = re.compile(
            r"^(?:blood\s*pressure|bp|heart\s*rate|hr|resp(?:iratory)?\s*rate|"
            r"respirations?|rr|spo2|sp\s*o2|oxygen\s*saturation|temperature|temp|"
            r"blood\s*glucose|bgl|glucose)$",
            re.IGNORECASE,
        )
        for f in findings:
            if f.finding_type != "vital":
                continue
            key = (f.key or "").strip()
            value = str(getattr(f, "value", "") or "").strip()
            if standard_vital_re.search(key) and re.search(r"^\d", value):
                return f.captured_at
        return None

    def _first_lung_sound_time():
        """Return the first true lung/breath-sound exam time.

        Work-of-breathing findings include the word "Breathing" but are not
        auscultation. When a lung-sound challenge is enabled, only the
        challenge-stamped result should drive this timeline row.
        """
        lung_sound_cfg = scenario.get("lung_sound_challenge", {}) or {}
        challenge_enabled = bool(lung_sound_cfg.get("enabled"))
        lung_key_re = re.compile(r"\b(lung\s*sounds?|breath\s*sounds?|auscultat(?:e|ed|ion)?)\b", re.IGNORECASE)
        for f in findings:
            if f.finding_type != "exam":
                continue
            source = getattr(f, "source", None)
            haystack = f"{f.key or ''} {f.value or ''}"
            if challenge_enabled and source != "lung_sound_challenge":
                continue
            if lung_key_re.search(haystack):
                return f.captured_at
        return None

    def _any_finding_after(ts, finding_types: set[str] | None = None, key_pattern: str | None = None):
        if not ts:
            return False
        for f in findings:
            if f.captured_at is None or f.captured_at <= ts:
                continue
            if finding_types and f.finding_type not in finding_types:
                continue
            if key_pattern and not re.search(key_pattern, f.key or "", re.IGNORECASE):
                continue
            return True
        return False

    def _message_has_any(patterns: list[str]) -> bool:
        return any(re.search(p, user_text, re.IGNORECASE) for p in patterns)

    def _first_action_evidence_time(action: dict):
        evidence = action.get("evidence") or {}
        if not isinstance(evidence, dict):
            return None

        finding_types = set(evidence.get("finding_types") or [])
        finding_key_patterns = evidence.get("finding_key_patterns") or []
        transcript_patterns = evidence.get("transcript_patterns") or []
        min_matches = max(1, int(evidence.get("min_matches", 1) or 1))

        matches: set[str] = set()
        first_ts = None

        for m in user_message_rows:
            content = (m.content or "")
            for pattern in transcript_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    matches.add(f"tx:{pattern}")
                    if first_ts is None:
                        first_ts = getattr(m, "timestamp", None)

        for f in findings:
            if finding_types and f.finding_type not in finding_types:
                continue
            haystack = f"{f.key or ''} {f.value or ''}"
            for pattern in finding_key_patterns:
                if re.search(pattern, haystack, re.IGNORECASE):
                    matches.add(pattern)
                    if first_ts is None:
                        first_ts = f.captured_at

        return first_ts if len(matches) >= min_matches else None

    first_vital_at = _first_standard_vital_time()
    first_exam_at = _first_finding_time("exam")
    first_history_at = _first_finding_time("history")
    first_lung_sound_at = _first_lung_sound_time()
    first_intervention_at = min((i.applied_at for i in session.interventions if i.applied_at), default=None)

    def _add_timeline_item(action: str, status: str, elapsed_min=None, **metadata):
        row = {"elapsed_min": elapsed_min, "action": action, "status": status}
        row.update(metadata)
        timeline.append(row)

    def _add_code_log_items():
        events = list(session_events if session_events is not None else (getattr(session, "events", None) or []))
        if not events:
            return
        events_by_id = {getattr(ev, "id", None): ev for ev in events}
        completed_events = [
            ev for ev in events
            if getattr(ev, "event_type", None) == "challenge_completed"
            and str(getattr(ev, "event_key", "") or "").startswith("cpr:")
            and isinstance(getattr(ev, "event_data", None), dict)
        ]
        for ev in completed_events:
            data = getattr(ev, "event_data", None) or {}
            start_event = events_by_id.get(data.get("challenge_started_event_id"))
            started_at = getattr(start_event, "occurred_at", None) if start_event else None
            for row in _cpr_code_log_rows(data, started_at=started_at, session_start=t0):
                timeline.append(row)

    def _action_available(action: dict) -> bool:
        iv_ids = action.get("intervention_ids") or []
        if not iv_ids:
            return True
        available = [
            iid for iid in iv_ids
            if iid in interventions_data
            and interventions_data[iid].get("within_bls_scope", True)
            and not interventions_data[iid].get("expansion_not_selected", False)
            and not interventions_data[iid].get("unavailable_in_scenario", False)
        ]
        return bool(available)

    def _action_required_here(action: dict) -> bool:
        required_at = action.get("required_at")
        if required_at and level_key not in required_at:
            return False
        if not _action_available(action):
            return False
        return True

    def _is_out_of_order(action: dict, done_at) -> bool:
        if not done_at:
            return False
        iv_ids = action.get("intervention_ids") or []
        if not iv_ids:
            return False

        meta_text_parts = []
        for iid in iv_ids:
            data = interventions_data.get(iid) or {}
            meta_text_parts.extend(step for step in (data.get("procedure_steps") or []) if step)
            meta_text_parts.extend(cc.get("label", "") for cc in (data.get("cross_checks") or []) if cc)
            meta_text_parts.append(data.get("notes", ""))
        meta_text = " ".join(meta_text_parts).lower()

        need_vitals = (
            "vital" in meta_text
            or bool(re.search(r"\bbaseline\s+(?:vital|bp|blood pressure|heart rate|hr|resp|spo2|sp\s*o2)\b", meta_text))
        )
        need_lung = ("lung sounds" in meta_text) or ("auscultate" in meta_text)
        need_history = ("history" in meta_text) or ("sample" in meta_text) or ("opqrst" in meta_text)

        if not any([need_vitals, need_lung, need_history]):
            return False

        if need_vitals and not (first_vital_at and first_vital_at <= done_at):
            return True
        if need_lung and not (first_lung_sound_at and first_lung_sound_at <= done_at):
            return True
        if need_history and not ((first_history_at and first_history_at <= done_at) or (first_exam_at and first_exam_at <= done_at)):
            return True
        return False

    # Scene-entry credited items
    for ca in critical_actions:
        if not ca.get("scene_entry_credited"):
            continue
        if not _action_required_here(ca):
            continue
        ca_id = ca.get("id", "")
        display = ca.get("display") or ca.get("description", ca_id)
        if ca_id in {"pat", "pat_assessment"}:
            done = pat_recorded
        elif ca_id in {"scene_safety", "ppe", "scene_entry"}:
            done = has_scene_safety_entry
        else:
            done = _item_state_done(ca_id)
        done_at = _item_state_evidence_time(ca_id)
        _add_timeline_item(
            display,
            "applied" if done else "missed",
            _elapsed(done_at),
            pre_start=True,
        )

    # Assessment checklist
    has_exam_check = any(chk.get("type") == "exam_logged" for chk in (scenario.get("readiness_criteria", {}).get("checks") or []))
    has_vitals_check = any(chk.get("type") == "vitals_logged" for chk in (scenario.get("readiness_criteria", {}).get("checks") or []))
    if has_exam_check:
        assessment_at = min((ts for ts in [first_exam_at, first_history_at] if ts), default=None)
        _add_timeline_item("Exam / history obtained", "applied" if assessment_at else "missed", _elapsed(assessment_at))
    if has_vitals_check:
        _add_timeline_item("Vital signs obtained", "applied" if first_vital_at else "missed", _elapsed(first_vital_at))
    lung_sound_cfg = scenario.get("lung_sound_challenge", {}) or {}
    lung_sound_required = bool(lung_sound_cfg.get("required") or lung_sound_cfg.get("timeline_required"))
    if not lung_sound_required:
        lung_action_text = " ".join(
            str(action.get("description") or action.get("display") or action.get("id") or "")
            for action in [*critical_actions, *recommended_actions]
            if _action_required_here(action)
        )
        lung_sound_required = bool(re.search(r"\b(lung sounds?|breath sounds?|auscultat)", lung_action_text, re.IGNORECASE))
    if lung_sound_cfg.get("enabled") and (first_lung_sound_at or lung_sound_required):
        # STATUS from scoring engine: find lung-sound checklist items by ID pattern and
        # check their adjudicated state. This ensures the timeline cannot disagree with the
        # scoring engine about whether lung sounds were credited (prevents source-restriction
        # divergence — the lung-sounds bug). Timestamp still derives from findings.
        _defs = (_states_blob.get("checklist_definitions") or []) if isinstance(_states_blob, dict) else []
        _ls_ids = tuple(
            d.get("id") for d in _defs
            if isinstance(d, dict) and "lung_sound" in (d.get("id") or "").lower()
        )
        _ls_scored = _item_state_value(*_ls_ids) if _ls_ids else None
        if _ls_scored is not None:
            _ls_done = _item_state_done(*_ls_ids)
            _add_timeline_item(
                "Lung sounds auscultated",
                "applied" if _ls_done else "missed",
                _elapsed(first_lung_sound_at) if _ls_done else None,
            )
        else:
            _add_timeline_item(
                "Lung sounds auscultated",
                "applied" if first_lung_sound_at else "missed",
                _elapsed(first_lung_sound_at),
            )

    # Critical actions tied to interventions/grace items
    for ca in critical_actions:
        if ca.get("scene_entry_credited") or ca.get("cognitive"):
            continue
        if not _action_required_here(ca):
            continue
        ca_id = ca.get("id", "")
        display = ca.get("display") or ca.get("description", ca_id)
        iv_ids = ca.get("intervention_ids") or []
        done_ids = [i for i in session.interventions if i.name in set(iv_ids)] if iv_ids else []
        done_at = min((i.applied_at for i in done_ids if i.applied_at), default=None)
        ca_required_raw = ca.get("required", True)
        ca_required = not (
            ca_required_raw is False
            or str(ca_required_raw).lower() in {"false", "optional", "bonus"}
        )
        if _item_state_done(ca_id):
            done_at = done_at or _item_state_evidence_time(ca_id) or _first_action_evidence_time(ca)
            status = "out_of_order" if _is_out_of_order(ca, done_at) else "applied"
            _add_timeline_item(display, status, _elapsed(done_at) if done_at else None)
            continue
        # If the scoring engine adjudicated this item and it is not satisfied, trust its
        # verdict rather than falling back to intervention timestamps or evidence heuristics.
        _ca_state = _item_state_value(ca_id)
        if _ca_state is not None and _ca_state not in ("satisfied", "partial"):
            if _ca_state != "not_applicable":
                _add_timeline_item(display, "missed")
            continue
        if done_at:
            status = "out_of_order" if _is_out_of_order(ca, done_at) else "applied"
            _add_timeline_item(display, status, _elapsed(done_at))
        elif ca.get("evidence"):
            evidence_at = _first_action_evidence_time(ca)
            if evidence_at:
                _add_timeline_item(display, "applied", _elapsed(evidence_at))
            elif ca.get("protocol_indicated"):
                _add_timeline_item(display, "missed")
            elif ca_required:
                _add_timeline_item(display, "missed")
        elif ca.get("als_grace"):
            _add_timeline_item(display, "informational")
        elif ca_required:
            _add_timeline_item(display, "missed")

    # Recommended / follow-up actions
    for rec in recommended_actions:
        rec_required = bool(rec.get("required") is True or str(rec.get("required", "")).lower() == "required")
        rec_id = (rec.get("id") or "").lower()
        desc = rec.get("description") or rec_id
        desc_lower = desc.lower()
        done = False
        done_at = None

        # Post-ROSC items are only applicable when CPR actually achieved ROSC.
        # When outcome is criteria_not_met/terminated, omit rather than show as missed.
        if "post_rosc" in rec_id and not _cpr_rosc_achieved:
            continue

        # Trust the scoring engine over the legacy heuristics below — prevents
        # confusing display/score disagreement when the two diverge.
        if _item_state_done(rec_id):
            done_at = _item_state_evidence_time(rec_id) or _first_action_evidence_time(rec)
            if done_at is None and re.search(r"\bhistory\b|\bopqrst\b|\bsample\b|\bonset\b", f"{rec_id} {desc}", re.IGNORECASE):
                done_at = first_history_at
            if done_at is None and re.search(r"\bexam\b|\bassessment\b|\bsurvey\b", f"{rec_id} {desc}", re.IGNORECASE):
                done_at = first_exam_at
            _add_timeline_item(desc, "applied", _elapsed(done_at) if done_at else None)
            continue
        # If the scoring engine adjudicated this item as not satisfied, use its verdict
        # directly and skip the heuristics entirely. not_applicable items are omitted.
        _rec_state = _item_state_value(rec_id)
        if _rec_state is not None and _rec_state not in ("satisfied", "partial"):
            if _rec_state != "not_applicable":
                _add_timeline_item(desc, "missed")
            continue

        if "reassess" in rec_id or "reassess" in desc_lower:
            if first_intervention_at:
                # Always show reassessment in the timeline when there were interventions
                # to reassess — item appears as "missed" if criteria not met.
                rec_required = True
                min_reassess_at = first_intervention_at + timedelta(seconds=60)
                neuro_reassess = rec_id == "reassess_neuro" or ("gcs" in desc_lower and "pupil" in desc_lower)
                if neuro_reassess:
                    post_neuro_rows = [
                        f for f in findings
                        if f.captured_at and f.captured_at >= min_reassess_at
                        and re.search(r"\bgcs\b|\bpupils?\b", f.key or "", re.IGNORECASE)
                    ]
                    observed_neuro = set()
                    for f in post_neuro_rows:
                        key = f.key or ""
                        if re.search(r"\bgcs\b", key, re.IGNORECASE):
                            observed_neuro.add("gcs")
                        if re.search(r"\bpupils?\b", key, re.IGNORECASE):
                            observed_neuro.add("pupils")
                    done = {"gcs", "pupils"}.issubset(observed_neuro)
                    if done:
                        done_at = min((f.captured_at for f in post_neuro_rows if f.captured_at), default=None)
                else:
                    # pre_keys: vitals/key-exam findings recorded before the first intervention.
                    # If no pre-intervention vitals exist (student correctly prioritized treatment
                    # first), fall back to any vital recorded before first_intervention_at + 30s
                    # to capture in-flight responses that land just after the intervention.
                    pre_keys = {
                        (f.finding_type, (f.key or "").strip().lower())
                        for f in findings
                        if f.captured_at and f.captured_at <= first_intervention_at
                        and (
                            f.finding_type == "vital"
                            or (f.finding_type == "exam" and re.search(r"(lung|breath|work of breathing|wob|mental|gcs|loc)", f.key or "", re.IGNORECASE))
                        )
                    }
                    # Fallback: if no pre-intervention vitals, any post-treatment vital pair
                    # qualifies — student is reassessing from scratch post-treatment.
                    if not pre_keys:
                        post_all = [
                            f for f in findings
                            if f.captured_at and f.captured_at >= min_reassess_at
                            and f.finding_type == "vital"
                        ]
                        # Need at least two distinct vital types to distinguish a reassessment
                        # from a single-question follow-up
                        distinct_types = {(f.finding_type, (f.key or "").strip().lower()) for f in post_all}
                        done = len(distinct_types) >= 2
                        if done:
                            done_at = min((f.captured_at for f in post_all if f.captured_at), default=None)
                    else:
                        post_rows = [
                            f for f in findings
                            if f.captured_at and f.captured_at >= min_reassess_at
                            and (
                                f.finding_type == "vital"
                                or (f.finding_type == "exam" and re.search(r"(lung|breath|work of breathing|wob|mental|gcs|loc)", f.key or "", re.IGNORECASE))
                            )
                            and (f.finding_type, (f.key or "").strip().lower()) in pre_keys
                        ]
                        done = bool(post_rows)
                        if done:
                            done_at = min((f.captured_at for f in post_rows if f.captured_at), default=None)
        elif "epiglottitis" in rec_id or "epiglottitis" in desc_lower:
            done = _message_has_any([r"\bdrool", r"\bdrooling", r"\btripod", r"\btoxic", r"\bmuffled", r"\bswallow"])
        elif "calm_environment" in rec_id or ("calm" in desc_lower and "agitat" in desc_lower):
            done = ("calm_environment" in applied_ids) or _message_has_any([r"\bcalm", r"\bquiet", r"\bdim", r"\blow[- ]?by"])
            done_at = min((i.applied_at for i in session.interventions if i.name == "calm_environment" and i.applied_at), default=None)
        elif "bvm" in rec_id:
            done = _message_has_any([r"\bbvm", r"\bbag[- ]?valve", r"\bbag mask"])

        if done or rec_required:
            _add_timeline_item(desc, "applied" if done else "missed", _elapsed(done_at) if done_at else None)

    # Include any additional applied interventions that were not already represented
    represented = {item["action"] for item in timeline}
    # Skip bare intervention entries for IVs already narrated by a critical action entry —
    # prevents duplicate timeline rows when a critical action and its intervention have
    # different label strings (e.g. long protocol description vs short PCR treatment label).
    covered_iv_ids: set[str] = set()
    for ca in critical_actions:
        ca_display = (ca.get("display") or ca.get("description") or ca.get("id") or "").strip()
        if ca_display in represented:
            # Cover the CA's own id (handles drug CAs where iv.name == ca id and
            # intervention_ids is absent) plus any explicit intervention_ids.
            covered_iv_ids.add(ca.get("id", ""))
            for iv_id in (ca.get("intervention_ids") or []):
                covered_iv_ids.add(iv_id)
    for iv in session.interventions:
        if iv.name in covered_iv_ids:
            continue
        label = interventions_data.get(iv.name, {}).get("label", iv.name)
        if label in represented:
            continue
        _add_timeline_item(label, "applied", _elapsed(iv.applied_at))

    _add_code_log_items()

    _sort_session_timeline_rows(timeline)

    return timeline


def _sort_session_timeline_rows(timeline: list[dict]) -> None:
    status_order = {
        "applied": 0,
        "out_of_order": 1,
        "informational": 2,
        "missed": 3,
    }
    timeline.sort(key=lambda item: (
        0 if item.get("pre_start") else 1,
        0 if item.get("elapsed_min") is not None else 1,
        item.get("elapsed_min") if item.get("elapsed_min") is not None else 9999,
        item.get("_sort_ms") if item.get("_sort_ms") is not None else 999999999,
        status_order.get(item.get("status"), 9),
        item.get("action") or "",
    ))


_RUBRIC_CATEGORY_LABELS = {
    "clinical_performance": "Clinical Performance",
    "clinical_performance_general": "General Assessment (NREMT Rubric)",
    "clinical_performance_call_specific": "Call Specific",
    "protocols_treatment": "Protocols & Treatment",
    "scope_adherence": "Scope Adherence",
    "documentation": "Documentation",
    "professionalism": "Professionalism",
}

_GENERAL_ASSESSMENT_PROVENANCE = {
    "universal_base",
    "base_patient_care_rubric",
}


def _rubric_detail_group_key(item: dict) -> str:
    """Return the display group key for a checklist item."""
    category = item.get("category") or "other"
    if category != "clinical_performance":
        return category
    provenance = item.get("provenance") or "scenario_overlay"
    if provenance in _GENERAL_ASSESSMENT_PROVENANCE:
        return "clinical_performance_general"
    return "clinical_performance_call_specific"


def _build_session_rubric_detail(session: SimSession) -> list[dict]:
    """Return compact checklist scoring rows for client-side feedback display."""
    states_blob = getattr(session, "checklist_states", None) or {}
    if not isinstance(states_blob, dict):
        return []

    definitions = states_blob.get("checklist_definitions") or []
    item_states = states_blob.get("item_states") or []
    if not isinstance(definitions, list) or not isinstance(item_states, list):
        return []

    defs_by_id = {
        item.get("id"): item
        for item in definitions
        if isinstance(item, dict) and item.get("id")
    }
    score_snapshot = getattr(session, "score_snapshot", None) or {}
    category_scores = score_snapshot.get("categories", {}) if isinstance(score_snapshot, dict) else {}
    grouped: dict[str, dict] = {}

    for state in item_states:
        if not isinstance(state, dict):
            continue
        item = defs_by_id.get(state.get("item_id"))
        if not item or state.get("state") == "not_applicable":
            continue

        category = item.get("category") or "other"
        group_key = _rubric_detail_group_key(item)
        bucket = grouped.setdefault(group_key, {
            "category": group_key,
            "source_category": category,
            "label": _RUBRIC_CATEGORY_LABELS.get(group_key, group_key.replace("_", " ").title()),
            "score": None,
            "max": None,
            "items": [],
        })
        cat_score = category_scores.get(category) if isinstance(category_scores, dict) else None
        if isinstance(cat_score, dict) and group_key == category:
            bucket["score"] = cat_score.get("total")
            bucket["max"] = cat_score.get("max")

        earned = int(state.get("earned_points") or 0)
        points = int(item.get("point_value") or 0)
        if group_key != category:
            bucket["score"] = int(bucket.get("score") or 0) + earned
            bucket["max"] = int(bucket.get("max") or 0) + points

        bucket["items"].append({
            "id": item.get("id"),
            "label": item.get("display") or item.get("description") or item.get("id"),
            "category": category,
            "provenance": item.get("provenance") or "scenario_overlay",
            "required": item.get("required") or "required",
            "status": state.get("state") or "unknown",
            "points": points,
            "earned": earned,
            "timing_violation": bool(state.get("timing_violation")),
            "notes": state.get("notes") or "",
        })

    order = [
        "clinical_performance_general",
        "clinical_performance_call_specific",
        "clinical_performance",
        "protocols_treatment",
        "scope_adherence",
        "documentation",
        "professionalism",
    ]
    ordered = [grouped[key] for key in order if key in grouped and grouped[key].get("items")]
    ordered.extend(value for key, value in grouped.items() if key not in order and value.get("items"))
    return ordered


def _auto_detect_interventions(message: str, session: SimSession, scenario: dict, db: AsyncSession):
    already_applied = {i.name for i in session.interventions}
    msg_lower = message.lower()
    for intervention_id, int_data in scenario["vitals"]["interventions"].items():
        if intervention_id in already_applied:
            continue
        if int_data.get("unavailable_in_scenario"):
            continue
        if int_data.get("requires_popup"):
            continue
        for pattern in int_data.get("detection_patterns", []):
            m = re.search(pattern, msg_lower)
            if m and _detection_match_is_confident(m):
                _auto_at = datetime.utcnow()
                db.add(Intervention(
                    session_id=session.id,
                    name=intervention_id,
                    applied_at=_auto_at,
                ))
                db.add(SessionEvent(
                    session_id=session.id,
                    event_type="intervention_applied",
                    event_key=intervention_id,
                    source="backend_auto",
                    occurred_at=_auto_at,
                ))
                already_applied.add(intervention_id)
                break


# ── Lexi hint chat ────────────────────────────────────────────────────────────

@app.post("/api/lexi")
@limiter.limit(f"{settings.rate_limit_lexi}/minute")
async def lexi_chat(request: Request, req: LexiRequest, ctx: ActiveContext = Depends(get_active_context)):
    async with async_session_factory() as db:
        session = await _get_owned_session(req.session_id, db, ctx)
        agency_dict = await load_agency(session.agency_id, db)
        scenario = adapt_scenario_to_context(load_scenario(session.scenario_id), agency_dict, session.mca, session.effective_protocol_excerpt)
        effective_checklist = load_checklist(
            scenario,
            session.provider_level or "EMT",
            session.mca or "mi_base",
            session.agency_id,
        )
        snapshot = {
            "start_time":     session.start_time,
            "provider_level": session.provider_level,
            "mca":            session.mca,
            "interventions":  [{"name": i.name, "applied_at": i.applied_at} for i in session.interventions],
            "messages":       [{"role": m.role, "content": m.content} for m in session.messages],
            "checklist_items": [
                {"id": item.id, "description": item.description, "required": item.required}
                for item in effective_checklist
            ],
        }
        if req.mode == "debrief":
            nd = session.narrative_data or {}
            ep = session.evidence_packet or {}
            ep_corroboration = ep.get("corroboration") if isinstance(ep, dict) else {}
            snapshot["checklist_states"] = session.checklist_states or {}
            snapshot["subscores"] = nd.get("subscores") or {}
            snapshot["score_notes"] = nd.get("score_notes") or {}
            snapshot["submitted_dmist"] = session.dmist_report or ""
            snapshot["submitted_narrative"] = nd.get("narrative") or ""
            snapshot["document_corroboration"] = {
                "dmist_unsupported_claims": (ep_corroboration or {}).get("dmist_unsupported_claims") or [],
                "narrative_unsupported_claims": (ep_corroboration or {}).get("narrative_unsupported_claims") or [],
                "dmist_missing_components": (ep_corroboration or {}).get("dmist_missing_components") or [],
                "chart_missing_elements": (ep_corroboration or {}).get("chart_missing_elements") or [],
            }
            _ep_ic = (session.evidence_packet or {}).get("impression_challenge")
            snapshot["impression_challenge"] = _ep_ic  # always present; may be None
            # Compute lock flag server-side: scenario IC enabled + result not qualifying.
            # Missing/malformed IC data on a challenge-enabled scenario fails closed.
            _sc_ic_enabled = bool((scenario.get("impression_challenge") or {}).get("enabled"))
            _ep_ic_result = (_ep_ic or {}).get("result") if _ep_ic else None
            snapshot["condition_locked"] = _sc_ic_enabled and _ep_ic_result not in ("correct", "acceptable")

    async def generate():
        yielded = False
        for attempt in range(2):
            try:
                async for chunk in get_lexi_response(
                    req.message, req.history, snapshot, scenario, agency_dict,
                    treat_hint=req.treat_hint, mode=req.mode
                ):
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
                    yielded = True
            except Exception as e:
                yield f"data: {json.dumps({'text': f'[Lexi error: {str(e)[:120]}]'})}\n\n"
                yielded = True
            if yielded:
                break
            log.warning("lexi.empty_stream_retry", session_id=req.session_id, attempt=attempt + 1)
        if not yielded:
            log.warning("lexi.empty_stream", session_id=req.session_id)
            yield f"data: {json.dumps({'text': '[No response — please try again]'})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Intervention endpoint ─────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/interventions")
@limiter.limit(f"{settings.rate_limit_session_write}/minute")
async def apply_intervention(
    request: Request,
    session_id: str,
    req: InterventionRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_owned_session(session_id, db, ctx, lock=True)
    agency_dict = await load_agency(session.agency_id, db)
    scenario = adapt_scenario_to_context(
        load_scenario(session.scenario_id),
        agency_dict,
        session.mca,
        session.effective_protocol_excerpt,
    )

    if req.intervention_name not in scenario["vitals"]["interventions"]:
        raise HTTPException(status_code=400, detail="Unknown intervention")

    already_applied = {i.name for i in session.interventions}
    if req.intervention_name not in already_applied:
        _applied_at = datetime.utcnow()
        _vitals_at_apply = calculate_vitals(session, scenario)
        _clinical_snapshot = build_intervention_clinical_snapshot(
            req.intervention_name, scenario, _vitals_at_apply
        )
        db.add(Intervention(
            session_id=session.id,
            name=req.intervention_name,
            applied_at=_applied_at,
        ))
        db.add(SessionEvent(
            session_id=session.id,
            event_type="intervention_applied",
            event_key=req.intervention_name,
            event_data=_clinical_snapshot,
            source=req.source,
            occurred_at=_applied_at,
        ))
        await db.commit()
        await db.refresh(session, attribute_names=["interventions", "messages", "events"])
    else:
        await db.refresh(session, attribute_names=["interventions", "messages", "events"])

    challenge_data = None
    if not session.treatment_submitted:
        challenge_data = await _check_and_fire_primary_survey_milestone(session, scenario, db)

    vitals = calculate_vitals(session, scenario)
    return {
        "interventions_applied": [i.name for i in session.interventions],
        "vitals": vitals,
        "challenge_available": challenge_data,
    }


# ── Session findings (transitional ingestion) ────────────────────────────────
# Findings originate from frontend tag parsing and are NOT independently verified
# facts. This endpoint persists them so the debrief pipeline has access to what
# the student assessed. Marked transitional — see SessionFinding model docstring.

_VALID_FINDING_SOURCES = frozenset({
    "authored_vitals",
    "partner_reported_exam",
    "student_stated_exam",
    "lung_sound_challenge",
    "gcs_modal",
    "avpu_quick_action",
    "glucometer_check",
    "caregiver_reported_history",
    "patient_reported_history",
    "ai_roleplay_tag",
    "system_scene_entry",
})

class FindingRequest(BaseModel):
    finding_type: str           # "exam" | "history" | "vital"
    key:          str
    value:        str
    source:       Optional[str] = None  # FindingSource; None = legacy/untyped


def _normalize_finding_value(finding_type: str, key: str, value: str) -> str:
    """Clean narrow, known-bad generated finding phrasing before persistence."""
    clean = str(value or "")
    if finding_type == "exam" and re.search(r"(?i)^dcap[-\s]?btls\b", str(key or "")):
        clean = re.sub(r"(?i)\babrasion\s*\(\s*laceration\s*\)", "laceration", clean)
        clean = re.sub(r"(?i)\babrasions?\s*/\s*lacerations?\b", "laceration", clean)
        clean = re.sub(r"(?i)\blacerations?\s*/\s*abrasions?\b", "laceration", clean)
    return clean


@app.post("/api/sessions/{session_id}/findings", status_code=204)
@limiter.limit(f"{settings.rate_limit_session_write * 2}/minute")
async def record_finding(
    request: Request,
    session_id: str,
    req: FindingRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    if req.finding_type not in ("exam", "history", "vital"):
        raise HTTPException(status_code=400, detail="finding_type must be exam, history, or vital")
    session = await _get_owned_session(session_id, db, ctx)
    if session.treatment_submitted:
        return  # session closed — silently discard late findings
    _now = datetime.utcnow()
    _key = req.key[:200]
    _val = _normalize_finding_value(req.finding_type, _key, req.value)[:1000]
    _src = req.source if req.source in _VALID_FINDING_SOURCES else None

    if req.finding_type == "history":
        # History is a static clinical fact — upsert so re-asked questions update in place.
        # Backed by partial unique index uq_session_finding_history_key.
        stmt = pg_insert(SessionFinding).values(
            session_id=session.id,
            finding_type="history",
            key=_key,
            value=_val,
            source=_src,
            captured_at=_now,
        ).on_conflict_do_update(
            index_elements=["session_id", "finding_type", "key"],
            index_where=SessionFinding.finding_type == "history",
            set_={"value": _val, "source": _src, "captured_at": _now},
        )
        await db.execute(stmt)
    else:
        # Vital and exam findings accumulate over the session — repeated assessments reflect
        # disease progression and treatment response (e.g., SpO2 before/after albuterol).
        # DB-enforced dedup: a partial expression index (uq_session_finding_minute_bucket)
        # makes (session_id, finding_type, key, value, minute) unique for exam/vital.
        # Identical readings within the same clock minute are silently discarded;
        # the same value in a later minute is kept (deliberate reassessment).
        # This is race-free — no SELECT+INSERT window; the DB rejects concurrent duplicates.
        stmt = pg_insert(SessionFinding).values(
            session_id=session.id,
            finding_type=req.finding_type,
            key=_key,
            value=_val,
            source=_src,
            captured_at=_now,
        ).on_conflict_do_nothing()
        await db.execute(stmt)

    await db.commit()


# ── Session events (authoritative backend action log) ─────────────────────────
# SessionEvent is the migration target for SessionFinding. Events are emitted
# by the backend (backend_auto) or explicitly by students/instructors
# (frontend_explicit / instructor_note). See AI_ARCHITECTURE.md §3.1.

# ── Session and adjudication constants ───────────────────────────────────────
# Defined here so record_session_event and create_adjudication can reference
# them without forward-reference ambiguity.

_SESSION_EVENT_TYPES = {
    "explicit_assessment",
    "vital_check",
    "clinical_decision",
    "medical_control_contact",
    "intervention_applied",
}
# challenge_completed is backend-exclusive — emitted only by POST /challenge-response.
# Do NOT add it here; the generic events endpoint must reject it so clients cannot forge results.
_ADJUDICATION_REASON_TYPES = {
    "protocol_revocation",
    "human_appeal",
    "system_error",
    "instructor_override",    # Phase 6: checklist item state override
    "instructor_re_debrief",  # Phase 6: instructor-triggered debrief regeneration
}
_VALID_SUBSCORE_KEYS = {
    "clinical_performance",
    "protocols_treatment",
    "scope_adherence",
    "dmist",
    "professionalism",
    "narrative",
}


class SessionEventRequest(BaseModel):
    event_type: str  # must be in _SESSION_EVENT_TYPES
    event_key:  str
    event_data: dict | None = None
    source:     str = "frontend_explicit"

@app.post("/api/sessions/{session_id}/events", status_code=204)
@limiter.limit(f"{settings.rate_limit_session_write * 2}/minute")
async def record_session_event(
    request: Request,
    session_id: str,
    req: SessionEventRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    # Some event types are emitted exclusively by the backend; clients may not
    # forge them because they can influence deterministic scoring.
    _backend_only_event_types = {"intervention_applied", "medical_control_contact"}
    _client_submittable = _SESSION_EVENT_TYPES - _backend_only_event_types
    if req.event_type not in _client_submittable:
        raise HTTPException(
            status_code=400,
            detail=f"event_type must be one of: {sorted(_client_submittable)}",
        )
    if req.source not in ("frontend_explicit", "instructor_note"):
        raise HTTPException(
            status_code=400,
            detail="source must be frontend_explicit or instructor_note for client submissions",
        )
    if req.source == "instructor_note" and not (ctx.is_superuser or ctx.role in ("admin", "instructor")):
        raise HTTPException(
            status_code=403,
            detail="instructor_note source requires instructor role",
        )
    if req.source == "instructor_note":
        # Instructors can annotate any session within their agency — not just their own.
        result = await db.execute(select(SimSession).where(SimSession.id == session_id))
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if not ctx.is_superuser and session.agency_id != ctx.agency_id:
            raise HTTPException(status_code=403, detail="Session belongs to a different agency")
    else:
        session = await _get_owned_session(session_id, db, ctx)
    if session.treatment_submitted:
        return  # session closed — silently discard late events
    db.add(SessionEvent(
        session_id=session.id,
        event_type=req.event_type,
        event_key=req.event_key[:200],
        event_data=req.event_data,
        source=req.source,
        occurred_at=datetime.utcnow(),
    ))
    await db.commit()


# ── Challenge shell ───────────────────────────────────────────────────────────

_CHALLENGE_TYPES = {"impression", "ecg", "med_math", "capnography", "free_text"}


class ChallengeResponseRequest(BaseModel):
    challenge_type: str  # must be in _CHALLENGE_TYPES
    challenge_id:   str = "default"  # stable ID for multi-challenge scenarios; "default" for single
    student_answer: str  # always a string from the frontend (numeric answers are digit strings)


class CPRChallengeStartRequest(BaseModel):
    challenge_id: str


class CPRChallengeTimelineEvent(BaseModel):
    model_config = {"extra": "allow"}

    t_ms: int = Field(ge=0)
    type: str
    reason: str | None = None
    rhythm: str | None = None
    decision: str | None = None
    data: dict[str, Any] | None = None


class CPRChallengeResponseRequest(BaseModel):
    challenge_id: str
    challenge_attempt_id: str
    timeline: list[CPRChallengeTimelineEvent]
    code_log: list[dict[str, Any]] = Field(default_factory=list)
    outcome_hint: str | None = None
    assistive_interaction_mode: bool = False


def _evaluate_challenge_answer(
    challenge_type: str,
    challenge_id: str,
    student_answer: str,
    scenario: dict,
) -> tuple[str, dict]:
    """Evaluate a student challenge answer against the scenario declaration.

    Returns (result, resolved_block) where result is 'correct'|'acceptable'|'incorrect'
    and resolved_block is the sub-block that was actually graded (the root block when
    challenge_id is 'default'; the named sub-block otherwise).

    The block is found by convention: f'{challenge_type}_challenge' in the scenario dict.
    Numeric answers are compared within tolerance_pct (default 5%).
    """
    block_key = f"{challenge_type}_challenge"
    root_block: dict = scenario.get(block_key) or {}

    # Resolve named sub-challenge (future multi-challenge support); fall back to root.
    if challenge_id and challenge_id != "default" and isinstance(root_block, dict):
        resolved_block: dict = root_block.get(challenge_id) or root_block
    else:
        resolved_block = root_block

    correct = resolved_block.get("correct")
    acceptable = resolved_block.get("acceptable") or []

    if correct is None:
        log.warning(
            "challenge-response: no 'correct' declared in %s for scenario %s (challenge_id=%s)",
            block_key, scenario.get("id", "?"), challenge_id,
        )
        return "incorrect", resolved_block

    # Numeric evaluation: parse both sides; apply tolerance.
    try:
        student_num = float(student_answer.strip())
        correct_num = float(correct)
        tolerance_pct = float(resolved_block.get("tolerance_pct", 5.0))
        denom = abs(correct_num) if abs(correct_num) > 0 else 1.0
        if abs(student_num - correct_num) / denom * 100 <= tolerance_pct:
            return "correct", resolved_block
        return "incorrect", resolved_block
    except (ValueError, TypeError, AttributeError):
        pass  # not numeric — fall through to string comparison

    # String / single-choice evaluation (case-insensitive strip).
    answer_norm = str(student_answer).strip().lower()
    if answer_norm == str(correct).strip().lower():
        return "correct", resolved_block
    if isinstance(acceptable, list):
        if any(answer_norm == str(a).strip().lower() for a in acceptable):
            return "acceptable", resolved_block
    return "incorrect", resolved_block


@app.post("/api/sessions/{session_id}/challenge-response")
@limiter.limit(f"{settings.rate_limit_session_write}/minute")
async def submit_challenge_response(
    request: Request,
    session_id: str,
    req: ChallengeResponseRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Evaluate a student's challenge answer and record the result.

    Returns {result: 'correct'|'acceptable'|'incorrect'|'skipped'}.
    Emits a challenge_completed SessionEvent (source: backend_auto) that
    _build_evidence_packet() reads to populate the challenge_results block.
    The vitals engine is not affected by this endpoint.
    """
    if req.challenge_type not in _CHALLENGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"challenge_type must be one of: {sorted(_CHALLENGE_TYPES)}",
        )

    session = await _get_owned_session(session_id, db, ctx)
    if session.treatment_submitted:
        raise HTTPException(status_code=409, detail="Session already submitted")

    # Use the adapted scenario so challenge blocks honour agency/MCA overrides.
    agency_dict = await load_agency(session.agency_id, db)
    base_scenario = load_scenario(session.scenario_id)
    if not base_scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    scenario = adapt_scenario_to_context(base_scenario, agency_dict, session.mca, session.effective_protocol_excerpt)

    student_answer_stripped = (req.student_answer or "").strip()
    if student_answer_stripped == "__skipped__":
        result = "skipped"
        resolved_block: dict = scenario.get(f"{req.challenge_type}_challenge") or {}
    else:
        result, resolved_block = _evaluate_challenge_answer(
            req.challenge_type, req.challenge_id, student_answer_stripped, scenario
        )

    db.add(SessionEvent(
        session_id=session.id,
        event_type="challenge_completed",
        event_key=f"{req.challenge_type}:{req.challenge_id}",
        event_data={
            "challenge_type":  req.challenge_type,
            "challenge_id":    req.challenge_id,
            "student_answer":  student_answer_stripped,
            "correct_answer":  resolved_block.get("correct"),
            "acceptable":      resolved_block.get("acceptable") or [],
            "result":          result,
        },
        source="backend_auto",
        occurred_at=datetime.utcnow(),
    ))
    await db.commit()

    return {"result": result}


def _cpr_challenge_config_for_session(session: SimSession, scenario: dict, challenge_id: str) -> dict:
    config = scenario.get("cpr_challenge") or {}
    if not isinstance(config, dict) or not config.get("enabled"):
        raise HTTPException(status_code=400, detail="Scenario does not enable a CPR challenge")
    if str(config.get("challenge_id") or "") != str(challenge_id or ""):
        raise HTTPException(status_code=400, detail="challenge_id does not match active scenario")
    return config


def _cpr_challenge_type_from_config(config: dict | None) -> str:
    algorithm = str((config or {}).get("algorithm") or "").lower()
    arrest_type = str((config or {}).get("arrest_type") or "").lower()
    if "neonatal" in algorithm or arrest_type == "neonatal":
        return "neonatal_resuscitation"
    return "cpr"


def _cpr_challenge_summary_from_evidence(evidence_packet: dict | None) -> dict | None:
    """Compact CPR outcome summary for rewards, analytics, and cached debriefs.

    The full CPR evidence packet remains the audit source of truth. This summary
    intentionally contains only stable, deterministic fields that downstream
    reward/routing surfaces can consume without parsing the entire code log.
    """
    if not isinstance(evidence_packet, dict):
        return None
    cpr = evidence_packet.get("cpr_challenge")
    if not isinstance(cpr, dict):
        return None
    metrics = cpr.get("metrics") if isinstance(cpr.get("metrics"), dict) else {}
    analytics = metrics.get("analytics") if isinstance(metrics.get("analytics"), dict) else {}
    rosc = cpr.get("rosc") if isinstance(cpr.get("rosc"), dict) else {}
    timeline = cpr.get("timeline") if isinstance(cpr.get("timeline"), list) else []
    pause_events = metrics.get("pause_events") if isinstance(metrics.get("pause_events"), list) else []
    pulse_checks = metrics.get("pulse_checks") if isinstance(metrics.get("pulse_checks"), dict) else {}
    resume = metrics.get("post_decision_resume") if isinstance(metrics.get("post_decision_resume"), dict) else {}
    resume_events = resume.get("events") if isinstance(resume.get("events"), list) else []
    ventilation_raw = metrics.get("ventilation_modes")
    ventilation_events = []
    if isinstance(ventilation_raw, list):
        ventilation_events = ventilation_raw
    elif isinstance(ventilation_raw, dict) and isinstance(ventilation_raw.get("events"), list):
        ventilation_events = ventilation_raw["events"]
    ventilation_bucket = cpr.get("score_buckets", {}).get("ventilation_ratio") if isinstance(cpr.get("score_buckets"), dict) else {}
    ventilation_applicable = bool(
        (isinstance(ventilation_bucket, dict) and ventilation_bucket.get("possible"))
        or (isinstance(ventilation_raw, dict) and ventilation_raw.get("applicable"))
    )
    rhythm_decisions = metrics.get("rhythm_decisions") if isinstance(metrics.get("rhythm_decisions"), list) else []
    ccf_by_cycle = metrics.get("ccf_by_cycle") if isinstance(metrics.get("ccf_by_cycle"), list) else []
    timeline_ms = [
        ev.get("t_ms") for ev in timeline
        if isinstance(ev, dict) and isinstance(ev.get("t_ms"), (int, float))
    ]
    challenge_start_ms = next(
        (
            ev.get("t_ms") for ev in timeline
            if isinstance(ev, dict)
            and ev.get("type") == "challenge_started"
            and isinstance(ev.get("t_ms"), (int, float))
        ),
        0,
    )
    cpr_time_sec = None
    if timeline_ms:
        cpr_time_sec = round(max(0, max(timeline_ms) - challenge_start_ms) / 1000, 1)
    return {
        "challenge_type": cpr.get("challenge_type") or "cpr",
        "challenge_id": cpr.get("challenge_id"),
        "challenge_attempt_id": cpr.get("challenge_attempt_id"),
        "outcome": cpr.get("outcome"),
        "completed": bool(cpr.get("completed")),
        "score": cpr.get("score"),
        "timestamp_integrity": cpr.get("timestamp_integrity"),
        "rosc_achieved": bool(rosc.get("achieved")),
        "rosc_after_cycle": rosc.get("triggered_after_cycle"),
        "cpr_time_sec": cpr_time_sec,
        "rounds_completed": len(ccf_by_cycle) or len(rhythm_decisions),
        "shocks_delivered": sum(1 for row in rhythm_decisions if isinstance(row, dict) and row.get("decision") == "shock"),
        "ccf": metrics.get("ccf"),
        "ccf_trend": analytics.get("ccf_trend"),
        "average_pause_sec": metrics.get("average_pause_sec"),
        "longest_pause_sec": metrics.get("longest_pause_sec"),
        "pauses_over_10_count": sum(
            1 for row in pause_events
            if isinstance(row, dict) and isinstance(row.get("pause_sec"), (int, float)) and row["pause_sec"] > 10
        ),
        "pulse_checks": {
            "valid_checks": pulse_checks.get("valid_checks"),
            "too_short_count": len(pulse_checks.get("too_short") or []),
            "too_long_count": len(pulse_checks.get("too_long") or []),
            "rhythm_checks_without_pulse_check_count": len(pulse_checks.get("rhythm_checks_without_pulse_check") or []),
        },
        "post_decision_resume": {
            "average_resume_sec": resume.get("average_resume_sec"),
            "events_count": len(resume_events),
            "delayed_count": sum(
                1 for row in resume_events
                if isinstance(row, dict) and isinstance(row.get("weight"), (int, float)) and row["weight"] < 1.0
            ),
        },
        "ventilation_ratio": {
            "applicable": ventilation_applicable,
            "selected_initial": ventilation_events[0].get("selected") if ventilation_events and isinstance(ventilation_events[0], dict) else None,
            "expected": ventilation_events[0].get("expected") if ventilation_events and isinstance(ventilation_events[0], dict) else None,
            "events_count": len(ventilation_events),
            "incorrect_count": sum(1 for row in ventilation_events if isinstance(row, dict) and not row.get("correct")),
        },
        "rhythm_decisions": {
            "decisions_count": len(rhythm_decisions),
            "incorrect_count": sum(1 for row in rhythm_decisions if isinstance(row, dict) and row.get("correct") is False),
            "critical_count": sum(1 for row in rhythm_decisions if isinstance(row, dict) and row.get("severity") == "critical"),
        },
        "error_tags": list(analytics.get("error_tags") or []),
        "remediation_targets": list(analytics.get("remediation_targets") or []),
        "aggregation_rule": "latest_completed_attempt",
    }


def _cpr_training_subscores(score: int | None) -> dict:
    """Represent CPR training as a 100-point assessment-only drill bucket."""
    safe_score = max(0, min(100, int(score or 0)))
    return {
        "clinical_performance": safe_score,
        "protocols_treatment": 0,
        "scope_adherence": 0,
        "dmist": 0,
        "professionalism": 0,
        "narrative": 0,
        "_maxes": {
            "clinical_performance": 100,
            "protocols_treatment": 0,
            "scope_adherence": 0,
            "dmist": 0,
            "professionalism": 0,
            "narrative": 0,
        },
    }


def _fmt_cpr_percent(value) -> str:
    if isinstance(value, (int, float)):
        return f"{round(float(value) * 100)}%"
    return "not available"


def _fmt_cpr_sec(value) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.1f} sec"
    return "not available"


def _cpr_bucket(cpr_result: dict, name: str) -> dict:
    rows = cpr_result.get("score_buckets") if isinstance(cpr_result.get("score_buckets"), dict) else {}
    nested = rows.get("buckets") if isinstance(rows.get("buckets"), dict) else None
    if nested is not None:
        rows = nested
    bucket = rows.get(name) if isinstance(rows.get(name), dict) else {}
    return bucket


def _cpr_bucket_passed(cpr_result: dict, name: str) -> bool | None:
    bucket = _cpr_bucket(cpr_result, name)
    possible = bucket.get("possible")
    earned = bucket.get("earned")
    if not isinstance(possible, (int, float)) or possible <= 0:
        return None
    if not isinstance(earned, (int, float)):
        return False
    return earned >= possible


def _cpr_metric_status(ok: bool | None) -> str:
    if ok is None:
        return "informational"
    return "applied" if ok else "missed"


def _cpr_training_metric_facts(cpr_result: dict) -> dict:
    metrics = cpr_result.get("metrics") if isinstance(cpr_result.get("metrics"), dict) else {}
    pause_events = metrics.get("pause_events") if isinstance(metrics.get("pause_events"), list) else []
    pulse = metrics.get("pulse_checks") if isinstance(metrics.get("pulse_checks"), dict) else {}
    resume = metrics.get("post_decision_resume") if isinstance(metrics.get("post_decision_resume"), dict) else {}
    resume_events = resume.get("events") if isinstance(resume.get("events"), list) else []
    ventilation_raw = metrics.get("ventilation_modes")
    ventilation_events = []
    if isinstance(ventilation_raw, list):
        ventilation_events = ventilation_raw
    elif isinstance(ventilation_raw, dict) and isinstance(ventilation_raw.get("events"), list):
        ventilation_events = ventilation_raw["events"]
    rhythm_decisions = metrics.get("rhythm_decisions") if isinstance(metrics.get("rhythm_decisions"), list) else []

    longest_pause = metrics.get("longest_pause_sec")
    pauses_over_10 = sum(
        1 for row in pause_events
        if isinstance(row, dict) and isinstance(row.get("pause_sec"), (int, float)) and row["pause_sec"] > 10
    )
    missing_pulse = len(pulse.get("rhythm_checks_without_pulse_check") or [])
    rhythm_too_short = pulse.get("rhythm_too_short") if "rhythm_too_short" in pulse else pulse.get("too_short")
    rhythm_too_long = pulse.get("rhythm_too_long") if "rhythm_too_long" in pulse else pulse.get("too_long")
    too_short = len(rhythm_too_short or [])
    too_long = len(rhythm_too_long or [])
    valid_checks = pulse.get("valid_rhythm_checks")
    if not isinstance(valid_checks, int):
        valid_checks = pulse.get("valid_checks")
    pulse_check_ok = (
        isinstance(valid_checks, int)
        and valid_checks > 0
        and missing_pulse == 0
        and too_short == 0
        and too_long == 0
    )
    ventilation_bucket = _cpr_bucket(cpr_result, "ventilation_ratio")
    ventilation_applicable = bool(
        ventilation_bucket.get("possible")
        or (isinstance(ventilation_raw, dict) and ventilation_raw.get("applicable"))
    )
    ventilation_ok = _cpr_bucket_passed(cpr_result, "ventilation_ratio") if ventilation_applicable else None
    rhythm_ok = _cpr_bucket_passed(cpr_result, "rhythm_decisions")
    resume_ok = _cpr_bucket_passed(cpr_result, "post_decision_resume")
    pause_ok = _cpr_bucket_passed(cpr_result, "pause_discipline")
    ccf_ok = _cpr_bucket_passed(cpr_result, "ccf")

    return {
        "metrics": metrics,
        "ccf": metrics.get("ccf"),
        "ccf_ok": ccf_ok,
        "average_pause_sec": metrics.get("average_pause_sec"),
        "longest_pause_sec": longest_pause,
        "pauses_over_10": pauses_over_10,
        "pause_ok": pause_ok if pause_ok is not None else (longest_pause <= 10 if isinstance(longest_pause, (int, float)) else None),
        "valid_pulse_checks": valid_checks,
        "pulse_checks_missing": missing_pulse,
        "pulse_checks_too_short": too_short,
        "pulse_checks_too_long": too_long,
        "pulse_check_ok": pulse_check_ok,
        "average_resume_sec": resume.get("average_resume_sec"),
        "resume_events_count": len(resume_events),
        "resume_delayed_count": sum(
            1 for row in resume_events
            if isinstance(row, dict) and isinstance(row.get("weight"), (int, float)) and row["weight"] < 1.0
        ),
        "resume_ok": resume_ok,
        "ventilation_applicable": ventilation_applicable,
        "ventilation_selected": ventilation_events[0].get("selected") if ventilation_events and isinstance(ventilation_events[0], dict) else None,
        "ventilation_expected": ventilation_events[0].get("expected") if ventilation_events and isinstance(ventilation_events[0], dict) else None,
        "ventilation_incorrect_count": sum(1 for row in ventilation_events if isinstance(row, dict) and not row.get("correct")),
        "ventilation_ok": ventilation_ok,
        "rhythm_decisions_count": len(rhythm_decisions),
        "rhythm_decisions_incorrect": sum(1 for row in rhythm_decisions if isinstance(row, dict) and row.get("correct") is False),
        "rhythm_decisions_critical": sum(1 for row in rhythm_decisions if isinstance(row, dict) and row.get("severity") == "critical"),
        "rhythm_ok": rhythm_ok,
    }


def _cpr_training_timeline(cpr_result: dict) -> list[dict]:
    """CPR-specific timeline for authored CPR drills.

    Normal scenario timeline rows are transcript/checklist driven. The authored
    CPR shortcut bypasses those surfaces, so this view must come from the CPR
    HUD evidence packet instead.
    """
    facts = _cpr_training_metric_facts(cpr_result)
    rosc = cpr_result.get("rosc") if isinstance(cpr_result.get("rosc"), dict) else {}
    rows = [
        {
            "elapsed_min": None,
            "action": "Cardiac arrest recognized and CPR challenge started",
            "status": "applied",
        },
        {
            "elapsed_min": None,
            "action": "CPR/AED challenge completed with backend-verified CPR evidence",
            "status": "applied" if cpr_result.get("completed") else "missed",
        },
        {
            "elapsed_min": None,
            "action": f"Chest compression fraction {_fmt_cpr_percent(facts['ccf'])} (target >=80%)",
            "status": _cpr_metric_status(facts["ccf_ok"]),
        },
        {
            "elapsed_min": None,
            "action": (
                f"Pause discipline: longest pause {_fmt_cpr_sec(facts['longest_pause_sec'])}; "
                f"{facts['pauses_over_10']} pause(s) >10 sec"
            ),
            "status": _cpr_metric_status(facts["pause_ok"]),
        },
        {
            "elapsed_min": None,
            "action": (
                f"Pulse checks: {facts['valid_pulse_checks'] or 0} valid 5-10 sec check(s); "
                f"{facts['pulse_checks_missing']} rhythm-analysis pause(s) without pulse check; "
                f"{facts['pulse_checks_too_short']} short; {facts['pulse_checks_too_long']} long"
            ),
            "status": _cpr_metric_status(facts["pulse_check_ok"]),
        },
        {
            "elapsed_min": None,
            "action": (
                f"AED/rhythm decisions: {facts['rhythm_decisions_count']} decision(s); "
                f"{facts['rhythm_decisions_incorrect']} incorrect; {facts['rhythm_decisions_critical']} critical"
            ),
            "status": _cpr_metric_status(facts["rhythm_ok"]),
        },
        {
            "elapsed_min": None,
            "action": (
                f"Post-decision CPR resume: average {_fmt_cpr_sec(facts['average_resume_sec'])}; "
                f"{facts['resume_delayed_count']} delayed resume event(s)"
            ),
            "status": _cpr_metric_status(facts["resume_ok"]),
        },
    ]
    if facts["ventilation_applicable"]:
        selected = facts["ventilation_selected"] or "not recorded"
        expected = facts["ventilation_expected"] or "not specified"
        rows.append({
            "elapsed_min": None,
            "action": (
                f"Compression/ventilation ratio: selected {selected}; expected {expected}; "
                f"{facts['ventilation_incorrect_count']} incorrect ratio event(s)"
            ),
            "status": _cpr_metric_status(facts["ventilation_ok"]),
        })
    else:
        rows.append({
            "elapsed_min": None,
            "action": "Compression/ventilation ratio was not part of this scenario score gate",
            "status": "informational",
        })
    rows.append({
        "elapsed_min": None,
        "action": "ROSC achieved through authored CPR challenge flow",
        "status": "applied" if bool(rosc.get("achieved")) else "missed",
    })
    rows.extend(_cpr_code_log_rows(cpr_result))
    return rows


def _sanitize_cpr_code_log(raw_log: Any) -> list[dict[str, Any]]:
    """Normalize frontend HUD log rows for debrief display only."""
    if not isinstance(raw_log, list):
        return []
    rows: list[dict[str, Any]] = []
    for raw in raw_log[:200]:
        if isinstance(raw, str):
            text = raw.strip()
            t_ms = None
        elif isinstance(raw, dict):
            text = str(raw.get("text") or raw.get("message") or raw.get("line") or "").strip()
            try:
                t_ms = int(raw.get("t_ms")) if raw.get("t_ms") is not None else None
            except (TypeError, ValueError):
                t_ms = None
        else:
            continue
        if not text:
            continue
        rows.append({
            "t_ms": max(0, t_ms) if isinstance(t_ms, int) else None,
            "text": text[:240],
        })
    return rows


def _cpr_code_log_from_timeline(cpr_result: dict) -> list[dict[str, Any]]:
    timeline = cpr_result.get("timeline")
    if not isinstance(timeline, list):
        return []

    def _row(raw: dict, text: str) -> dict[str, Any] | None:
        try:
            t_ms = int(raw.get("t_ms")) if raw.get("t_ms") is not None else None
        except (TypeError, ValueError):
            t_ms = None
        return {
            "t_ms": max(0, t_ms) if isinstance(t_ms, int) else None,
            "text": text[:240],
        }

    rows: list[dict[str, Any]] = []
    for raw in timeline[:300]:
        if not isinstance(raw, dict):
            continue
        typ = str(raw.get("type") or "")
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        reason = str(raw.get("reason") or data.get("reason") or "")
        rhythm = str(raw.get("rhythm") or data.get("rhythm") or "").replace("_", " ").upper()
        text = None
        if typ == "challenge_started":
            text = "CPR challenge opened"
        elif typ == "pre_challenge_pulse_check_confirmed":
            text = "Pre-challenge pulse check documented"
        elif typ == "cpr_started":
            mode = data.get("mode")
            text = f"CPR initiated{f' - {mode}' if mode else ''}"
        elif typ == "aed_applied":
            text = "AED powered on / pads applied"
        elif typ == "compressions_paused":
            text = "Compressions paused for AED analysis" if reason == "rhythm_check" else "Compressions paused"
        elif typ == "rhythm_check_started":
            text = "AED analysis started"
        elif typ == "pulse_check_started":
            text = "Pulse check started"
        elif typ == "pulse_check_completed":
            result = str(data.get("result") or "").replace("_", " ")
            status = str(data.get("status") or "")
            text = f"Pulse check complete{f' - {result}' if result else ''}{f' ({status})' if status else ''}"
        elif typ == "rhythm_identified":
            text = f"Rhythm identified{f' - {rhythm}' if rhythm else ''}"
        elif typ == "shock_delivered":
            text = "Shock delivered"
        elif typ == "no_shock_selected":
            text = "No shock advised / selected"
        elif typ == "compressions_resumed":
            text = "Compressions resumed"
        elif typ == "rosc":
            text = "ROSC confirmed"
        elif typ == "additional_action_selected":
            label = data.get("label") or data.get("action_id")
            text = f"Additional action recorded{f' - {label}' if label else ''}"
        elif typ == "medical_control_consulted":
            text = "Medical control consultation documented"
        elif typ == "termination_of_resuscitation":
            text = "Termination of resuscitation requested"
        elif typ == "challenge_ended":
            outcome = raw.get("outcome") or data.get("outcome")
            text = f"CPR challenge ended{f' - {outcome}' if outcome else ''}"
        if text:
            row = _row(raw, text)
            if row:
                rows.append(row)
    return rows


def _cpr_code_log_rows(cpr_result: dict, *, started_at: datetime | None = None, session_start: datetime | None = None) -> list[dict]:
    code_log = _sanitize_cpr_code_log(cpr_result.get("code_log"))
    if not code_log:
        code_log = _cpr_code_log_from_timeline(cpr_result)
    if not code_log:
        return []

    def _elapsed_from_ms(t_ms: int | None):
        if isinstance(t_ms, int) and started_at and session_start:
            return round(((started_at + timedelta(milliseconds=t_ms)) - session_start).total_seconds() / 60, 1)
        if isinstance(t_ms, int):
            return round(t_ms / 60000, 1)
        return None

    return [
        {
            "elapsed_min": _elapsed_from_ms(row.get("t_ms")),
            "action": row["text"],
            "status": "informational",
            "source": "code_log",
            "_sort_ms": row.get("t_ms") if isinstance(row.get("t_ms"), int) else None,
        }
        for row in code_log
    ]


async def _load_session_events_for_timeline(session_id: str, db: AsyncSession) -> list[SessionEvent]:
    result = await db.execute(
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id)
        .order_by(SessionEvent.occurred_at)
    )
    return list(result.scalars().all())


def _cpr_training_rubric_detail(cpr_result: dict) -> list[dict]:
    facts = _cpr_training_metric_facts(cpr_result)
    score = max(0, min(100, int(cpr_result.get("score") or 0)))
    def _bucket_points(name: str) -> tuple[int, int]:
        bucket = _cpr_bucket(cpr_result, name)
        earned = bucket.get("earned")
        possible = bucket.get("possible")
        return (
            int(earned) if isinstance(earned, (int, float)) else 0,
            int(possible) if isinstance(possible, (int, float)) else 0,
        )

    def _scaled_bucket_points(name: str, display_possible: int) -> tuple[int, int]:
        earned, possible = _bucket_points(name)
        if possible <= 0 or display_possible <= 0:
            return 0, 0
        return round((earned / possible) * display_possible), display_possible

    timeline = cpr_result.get("timeline") if isinstance(cpr_result.get("timeline"), list) else []
    arrest_recognized = bool(cpr_result.get("completed")) or any(
        isinstance(ev, dict) and ev.get("type") == "cpr_started"
        for ev in timeline
    )
    recognition_earned, recognition_possible = (5 if arrest_recognized else 0), 5
    pulse_earned, pulse_possible = (10 if facts["pulse_check_ok"] else 0), 10
    ccf_earned, ccf_possible = _scaled_bucket_points("ccf", 25)
    pause_earned, pause_possible = _bucket_points("pause_discipline")
    rhythm_earned, rhythm_possible = _bucket_points("rhythm_decisions")
    cycle_earned, cycle_possible = _bucket_points("cycle_discipline")
    resume_earned, resume_possible = _scaled_bucket_points("post_decision_resume", 5)
    ventilation_earned, ventilation_possible = _bucket_points("ventilation_ratio")
    items = [
        (
            "cpr_training.arrest_recognition",
            "Cardiac arrest recognized and CPR initiated",
            "applied" if arrest_recognized else "missed",
            recognition_possible,
            recognition_earned,
        ),
        (
            "cpr_training.ccf",
            f"Chest compression fraction target met ({_fmt_cpr_percent(facts['ccf'])})",
            _cpr_metric_status(facts["ccf_ok"]),
            ccf_possible,
            ccf_earned,
        ),
        (
            "cpr_training.pause_discipline",
            "Pauses minimized with no excessive hands-off interval",
            _cpr_metric_status(facts["pause_ok"]),
            pause_possible,
            pause_earned,
        ),
        (
            "cpr_training.pulse_checks",
            "Pulse checks performed for 5-10 seconds during rhythm-analysis pauses",
            _cpr_metric_status(facts["pulse_check_ok"]),
            pulse_possible,
            pulse_earned,
        ),
        (
            "cpr_training.rhythm_decisions",
            "AED/rhythm decisions matched shockable vs non-shockable rhythms",
            _cpr_metric_status(facts["rhythm_ok"]),
            rhythm_possible,
            rhythm_earned,
        ),
        (
            "cpr_training.cycle_discipline",
            "Rhythm checks occurred near the authored two-minute cycle boundaries",
            _cpr_metric_status(_cpr_bucket_passed(cpr_result, "cycle_discipline")),
            cycle_possible,
            cycle_earned,
        ),
        (
            "cpr_training.post_decision_resume",
            "CPR resumed promptly after shock/no-shock decisions",
            _cpr_metric_status(facts["resume_ok"]),
            resume_possible,
            resume_earned,
        ),
    ]
    if facts["ventilation_applicable"]:
        items.append((
            "cpr_training.ventilation_ratio",
            "Correct compression/ventilation ratio selected for the authored algorithm",
            _cpr_metric_status(facts["ventilation_ok"]),
            ventilation_possible,
            ventilation_earned,
        ))
    return [{
        "category": "clinical_performance",
        "label": "CPR Training Performance",
        "score": score,
        "max": 100,
        "items": [
            {
                "id": item_id,
                "label": label,
                "category": "clinical_performance",
                "required": "required",
                "status": status,
                "points": points,
                "earned": earned,
                "timing_violation": False,
                "notes": "",
            }
            for item_id, label, status, points, earned in items
        ],
    }]


def _cpr_training_debrief_text(scenario: dict, cpr_result: dict, summary: dict | None) -> str:
    """Deterministic CPR-only feedback for authored training shortcuts."""
    score = cpr_result.get("score")
    outcome = "ROSC achieved" if cpr_result.get("outcome") == "rosc" else str(cpr_result.get("outcome") or "completed")
    metrics = cpr_result.get("metrics") if isinstance(cpr_result.get("metrics"), dict) else {}
    analytics = metrics.get("analytics") if isinstance(metrics.get("analytics"), dict) else {}
    facts = _cpr_training_metric_facts(cpr_result)
    targets = [str(t).replace("_", " ") for t in (analytics.get("remediation_targets") or [])]
    target_line = ", ".join(targets) if targets else "No major CPR remediation targets were flagged."
    title = scenario.get("display_title") or scenario.get("title") or "CPR Training"
    ratio_line = "not scored for this scenario"
    if facts["ventilation_applicable"]:
        ratio_line = (
            f"selected {facts['ventilation_selected'] or 'not recorded'}, "
            f"expected {facts['ventilation_expected'] or 'not specified'}, "
            f"{facts['ventilation_incorrect_count']} incorrect ratio event(s)"
        )
    return (
        f"CPR TRAINING RESULTS\n\n"
        f"Scenario: {title}\n\n"
        f"{outcome}. CPR challenge score: {score if score is not None else 'not scored'}/100.\n\n"
        f"HIGH-PERFORMANCE CPR METRICS\n\n"
        f"- Chest compression fraction: {_fmt_cpr_percent(facts['ccf'])} (target >=80%).\n"
        f"- Pause discipline: average pause {_fmt_cpr_sec(facts['average_pause_sec'])}; "
        f"longest pause {_fmt_cpr_sec(facts['longest_pause_sec'])}; {facts['pauses_over_10']} pause(s) >10 sec.\n"
        f"- Pulse checks: {facts['valid_pulse_checks'] or 0} valid 5-10 sec check(s); "
        f"{facts['pulse_checks_missing']} rhythm-analysis pause(s) without a pulse check; "
        f"{facts['pulse_checks_too_short']} short; {facts['pulse_checks_too_long']} long.\n"
        f"- AED/rhythm decisions: {facts['rhythm_decisions_count']} decision(s); "
        f"{facts['rhythm_decisions_incorrect']} incorrect; {facts['rhythm_decisions_critical']} critical.\n"
        f"- Post-decision CPR resume: average {_fmt_cpr_sec(facts['average_resume_sec'])}; "
        f"{facts['resume_delayed_count']} delayed resume event(s).\n"
        f"- Compression/ventilation ratio: {ratio_line}.\n\n"
        f"AHA BLS QUALITY REVIEW\n\n"
        f"- Chain of Survival: early recognition/activation, immediate high-quality CPR, rapid AED defibrillation when shockable, effective ventilation, and post-ROSC reassessment/continued care.\n"
        f"- High-quality CPR targets: rate 100-120/min, adult depth 2-2.4 in, full chest recoil, minimal interruptions, avoid excessive ventilation, rotate compressors about every 2 minutes when possible.\n"
        f"- This simulator directly scores CCF, hands-off pauses, AED/rhythm decisions, pulse-check timing, post-decision CPR resumption, and authored compression/ventilation ratio selection. Rate, depth, recoil, and hand placement should be reinforced by the instructor/manikin feedback when available.\n\n"
        f"The CPR HUD evidence packet is the source of truth for compression timing, AED decisions, pauses, pulse checks, ratio selection, and ROSC. "
        f"Because this scenario bypasses turnover and narrative writing, the normal transcript checklist is not used to decide whether arrest was recognized.\n\n"
        f"Focus for the next rep: {target_line}\n\n"
        f"Because this is an authored CPR training scenario, turnover and narrative writing were bypassed after ROSC and code termination.\n\n"
        f"SCORE: {score if score is not None else 0}/100"
    )


async def _load_session_scenario_for_challenge(session: SimSession, db: AsyncSession) -> dict:
    agency_dict = await load_agency(session.agency_id, db)
    base_scenario = load_scenario(session.scenario_id)
    if not base_scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return adapt_scenario_to_context(
        base_scenario,
        agency_dict,
        session.mca,
        session.effective_protocol_excerpt,
    )


@app.post("/api/sessions/{session_id}/cpr-challenge/start")
@limiter.limit(f"{settings.rate_limit_session_write}/minute")
async def start_cpr_challenge(
    request: Request,
    session_id: str,
    req: CPRChallengeStartRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Issue a backend-anchored CPR challenge attempt.

    The frontend HUD uses this attempt id when submitting its timeline. The
    paired response endpoint verifies that the attempt belongs to this active
    session and challenge before writing scored facts.
    """
    session = await _get_owned_session(session_id, db, ctx, lock=True)
    if session.treatment_submitted or session.ended_at is not None:
        raise HTTPException(status_code=409, detail="Session already closed")

    scenario = await _load_session_scenario_for_challenge(session, db)
    config = _cpr_challenge_config_for_session(session, scenario, req.challenge_id)
    challenge_type = _cpr_challenge_type_from_config(config)

    attempt_id = f"{session.id}:{req.challenge_id}:{uuid.uuid4().hex[:12]}"
    started_at = datetime.utcnow()
    db.add(SessionEvent(
        session_id=session.id,
        event_type="challenge_started",
        event_key=f"cpr:{req.challenge_id}",
        event_data={
            "challenge_type": challenge_type,
            "challenge_id": req.challenge_id,
            "challenge_attempt_id": attempt_id,
        },
        source="backend_auto",
        occurred_at=started_at,
    ))
    await db.commit()

    return {
        "challenge_type": challenge_type,
        "challenge_id": req.challenge_id,
        "challenge_attempt_id": attempt_id,
        "server_started_at": started_at.isoformat() + "Z",
        "cycle_seconds": config.get("cycle_seconds", 120),
        "algorithm": config.get("algorithm"),
        "arrest_type": config.get("arrest_type"),
        "initial_rhythm": config.get("initial_rhythm"),
        "rhythm_sequence": config.get("rhythm_sequence") or [],
        "allow_aed": bool(config.get("allow_aed", True)),
        "allow_manual_defib": bool(config.get("allow_manual_defib", False)),
        "allow_medications": bool(config.get("allow_medications", False)),
    }


@app.post("/api/sessions/{session_id}/cpr-challenge/response")
@limiter.limit(f"{settings.rate_limit_session_write}/minute")
async def submit_cpr_challenge_response(
    request: Request,
    session_id: str,
    req: CPRChallengeResponseRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Validate and score a CPR HUD timeline.

    Emits a backend-only `challenge_completed` SessionEvent with structured CPR
    facts. The generic `/events` endpoint cannot forge this event type.
    """
    session = await _get_owned_session(session_id, db, ctx, lock=True)
    if session.treatment_submitted or session.ended_at is not None:
        raise HTTPException(status_code=409, detail="Session already closed")

    scenario = await _load_session_scenario_for_challenge(session, db)
    config = _cpr_challenge_config_for_session(session, scenario, req.challenge_id)

    start_result = await db.execute(
        select(SessionEvent)
        .where(
            SessionEvent.session_id == session.id,
            SessionEvent.event_type == "challenge_started",
            SessionEvent.event_key == f"cpr:{req.challenge_id}",
        )
        .order_by(SessionEvent.occurred_at.desc())
    )
    start_event = next(
        (
            ev for ev in start_result.scalars().all()
            if ((ev.event_data or {}).get("challenge_attempt_id") == req.challenge_attempt_id)
        ),
        None,
    )
    if not start_event:
        raise HTTPException(status_code=409, detail="No active CPR challenge attempt found")

    duplicate_result = await db.execute(
        select(SessionEvent).where(
            SessionEvent.session_id == session.id,
            SessionEvent.event_type == "challenge_completed",
            SessionEvent.event_key == f"cpr:{req.challenge_id}",
        )
    )
    for ev in duplicate_result.scalars().all():
        if (ev.event_data or {}).get("challenge_attempt_id") == req.challenge_attempt_id:
            return ev.event_data

    timeline = [event.model_dump(exclude_none=True) for event in req.timeline]
    final_t_ms = max((int(event.get("t_ms", 0)) for event in timeline), default=0)
    elapsed_ms = int((datetime.utcnow() - start_event.occurred_at).total_seconds() * 1000)
    tolerance_ms = 30_000
    timestamp_integrity = "server_anchored"
    if req.outcome_hint == "abandoned":
        timestamp_integrity = "abandoned"
    elif final_t_ms > elapsed_ms + tolerance_ms:
        timestamp_integrity = "rejected_invalid"

    try:
        result = score_cpr_challenge(
            config,
            timeline,
            context=CPRScoreContext(
                assistive_interaction_mode=req.assistive_interaction_mode,
                timestamp_integrity=timestamp_integrity,
            ),
        )
    except CPRChallengeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result["challenge_attempt_id"] = req.challenge_attempt_id
    result["challenge_started_event_id"] = start_event.id
    result["server_elapsed_ms"] = elapsed_ms
    result["code_log"] = _sanitize_cpr_code_log(req.code_log)

    db.add(SessionEvent(
        session_id=session.id,
        event_type="challenge_completed",
        event_key=f"cpr:{req.challenge_id}",
        event_data=result,
        source="backend_auto",
        occurred_at=datetime.utcnow(),
    ))
    await db.commit()

    return result


@app.post("/api/sessions/{session_id}/cpr-training-debrief")
@limiter.limit(f"{settings.rate_limit_debrief}/minute")
async def submit_cpr_training_debrief(
    request: Request,
    session_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Close an authored CPR training scenario immediately after verified ROSC.

    This deliberately does not apply to normal scenarios. The scenario must opt
    in via cpr_challenge.training_auto_debrief_on_rosc, and the backend must
    find a completed CPR challenge event with outcome == "rosc".
    """
    session = await _get_owned_session(session_id, db, ctx, lock=True)
    if session.narrative_submitted and session.feedback:
        stored = session.narrative_data or {}
        stored_summary = stored.get("cpr_challenge_summary")
        stored_cpr = None
        if isinstance(session.evidence_packet, dict):
            candidate = session.evidence_packet.get("cpr_challenge")
            stored_cpr = candidate if isinstance(candidate, dict) else None
        stored_timeline = stored.get("timeline")
        stored_rubric = stored.get("rubric_detail")
        if stored.get("drill_source") == "cpr_training_auto_debrief" and stored_cpr:
            stored_summary = _cpr_challenge_summary_from_evidence({"cpr_challenge": stored_cpr}) or stored_summary
            stored_timeline = _cpr_training_timeline(stored_cpr)
            stored_rubric = _cpr_training_rubric_detail(stored_cpr)
            stored_feedback = _cpr_training_debrief_text(load_scenario(session.scenario_id) or {}, stored_cpr, stored_summary)
        else:
            stored_feedback = stored.get("client_feedback") or session.feedback
        return {
            "feedback": stored_feedback,
            "score": session.score,
            "assessment_score": session.assessment_score,
            "narrative_score": session.narrative_score,
            "subscores": stored.get("subscores"),
            "timeline": stored_timeline,
            "rubric_detail": stored_rubric,
            "exemplar_dmist": None,
            "exemplar_narrative": None,
            "critical_failure": None,
            "top_takeaways": stored.get("top_takeaways") or [],
            "reflection_prompts": stored.get("reflection_prompts") or [],
            "next_action": stored.get("next_action") or "",
            "next_action_target_type": stored.get("next_action_target_type") or "none",
            "next_action_target_id": stored.get("next_action_target_id"),
            "cpr_challenge_summary": stored_summary,
            "impression_challenge": None,
            "dmist_primary_impression": None,
        }

    agency_dict = await load_agency(session.agency_id, db)
    scenario = adapt_scenario_to_context(
        load_scenario(session.scenario_id),
        agency_dict,
        session.mca,
        session.effective_protocol_excerpt,
    )
    config = scenario.get("cpr_challenge") or {}
    if not (config.get("enabled") and config.get("training_auto_debrief_on_rosc")):
        raise HTTPException(status_code=400, detail="Scenario is not configured for CPR training auto-debrief")

    challenge_id = config.get("challenge_id")
    result = await db.execute(
        select(SessionEvent)
        .where(
            SessionEvent.session_id == session.id,
            SessionEvent.event_type == "challenge_completed",
            SessionEvent.event_key == f"cpr:{challenge_id}",
        )
        .order_by(SessionEvent.occurred_at.desc())
    )
    cpr_event = result.scalars().first()
    cpr_result = cpr_event.event_data if cpr_event else None
    if not isinstance(cpr_result, dict):
        raise HTTPException(status_code=409, detail="No completed CPR challenge found")
    if cpr_result.get("outcome") != "rosc" or not bool((cpr_result.get("rosc") or {}).get("achieved")):
        raise HTTPException(status_code=409, detail="CPR training auto-debrief requires ROSC")

    score = max(0, min(100, int(cpr_result.get("score") or 0)))
    subscores = _cpr_training_subscores(score)
    evidence_packet = {"cpr_challenge": cpr_result}
    summary = _cpr_challenge_summary_from_evidence(evidence_packet)
    timeline = _cpr_training_timeline(cpr_result)
    rubric_detail = _cpr_training_rubric_detail(cpr_result)
    feedback = _cpr_training_debrief_text(scenario, cpr_result, summary)

    narrative_data = dict(session.narrative_data or {})
    narrative_data.update({
        "drill": True,
        "drill_source": "cpr_training_auto_debrief",
        "skipped_turnover": True,
        "skipped_narrative": True,
        "subscores": subscores,
        "timeline": timeline,
        "rubric_detail": rubric_detail,
        "cpr_challenge_summary": summary,
        "top_takeaways": [
            "ROSC was achieved through the CPR challenge flow.",
            "High-performance CPR was evaluated from CCF, pauses under 10 seconds, AED/rhythm decisions, pulse-check timing, post-decision resume time, and ratio selection.",
            "AHA BLS priorities remain early recognition/activation, immediate high-quality CPR, rapid AED use for shockable rhythms, effective ventilation, and post-ROSC reassessment.",
        ],
        "reflection_prompts": [
            "Where did hands-off time occur during the code?",
            "What would you tighten on the next two-minute cycle?",
        ],
        "next_action": "Replay CPR Mastery if you want another focused arrest-management rep.",
        "next_action_target_type": "minigame",
        "next_action_target_id": "cpr_bls_sequence",
    })
    session.narrative_submitted = True
    session.narrative_attempted = False
    session.narrative_data = narrative_data
    _store_session_debrief(session, feedback)
    session.score = score
    session.assessment_score = score
    session.narrative_score = None
    session.ended_at = datetime.utcnow()
    session.evidence_packet = evidence_packet
    await db.commit()

    return {
        "feedback": feedback,
        "score": score,
        "assessment_score": score,
        "narrative_score": None,
        "subscores": subscores,
        "timeline": timeline or None,
        "rubric_detail": rubric_detail or None,
        "exemplar_dmist": None,
        "exemplar_narrative": None,
        "critical_failure": None,
        "top_takeaways": narrative_data["top_takeaways"],
        "reflection_prompts": narrative_data["reflection_prompts"],
        "next_action": narrative_data["next_action"],
        "next_action_target_type": narrative_data["next_action_target_type"],
        "next_action_target_id": narrative_data["next_action_target_id"],
        "cpr_challenge_summary": summary,
        "impression_challenge": None,
        "dmist_primary_impression": None,
    }


# ── Adjudicated outcomes (instructor/admin append-only re-scores) ─────────────

def _effective_subscores(session: SimSession) -> dict | None:
    """Effective subscores: latest adjudication corrections merged onto original subscores.

    When an adjudication only corrects a subset of dimensions, the uncorrected
    dimensions inherit from the original session subscores so the returned dict
    is always complete and consistent with _effective_score().
    """
    nd = session.narrative_data or {}
    original: dict = nd.get("subscores") or {}
    scored = [a for a in (session.adjudications or []) if a.corrected_subscores is not None]
    if not scored:
        return original if original else None
    correction = max(scored, key=lambda a: a.created_at).corrected_subscores
    # Merge: original provides base, correction overrides specific keys
    return {**original, **correction} if original else correction


def _effective_score(session: SimSession) -> int | None:
    """Effective total score: consistent with _effective_subscores().

    Resolution order:
    1. If the latest corrective adjudication (score OR subscores) has a direct
       corrected_score, use it.
    2. If the latest corrective adjudication only has corrected_subscores, derive
       the total by summing _effective_subscores() so score and subscores are
       always in sync.
    3. Fall back to the original session.score.
    """
    adjudications = list(session.adjudications or [])
    direct_scored = [a for a in adjudications if a.corrected_score is not None]
    subscore_scored = [a for a in adjudications if a.corrected_subscores is not None]

    if not direct_scored and not subscore_scored:
        return session.score

    latest_direct = max(direct_scored, key=lambda a: a.created_at) if direct_scored else None
    latest_sub = max(subscore_scored, key=lambda a: a.created_at) if subscore_scored else None

    # Direct score adjudication wins unless a subscore adjudication is strictly newer
    if latest_direct and (not latest_sub or latest_direct.created_at >= latest_sub.created_at):
        return latest_direct.corrected_score

    # Subscore-only (or newer) adjudication — derive assessment score from
    # effective subscores. Narrative is bonus-only XP and does not affect score.
    subs = _effective_subscores(session)
    return _compute_assessment_score_from_subscores(subs) if subs else session.score


def _compute_assessment_score_from_subscores(subscores: dict) -> int | None:
    """Sum the non-narrative assessment buckets for either legacy or migrated scenarios."""
    if not subscores:
        return None

    canonical_keys = [
        "clinical_performance",
        "protocols_treatment",
        "scope_adherence",
        "dmist",
        "professionalism",
    ]
    required_keys = ["clinical_performance", "dmist", "professionalism"]
    if all(k in subscores for k in required_keys) and any(
        k in subscores for k in ("protocols_treatment", "scope_adherence")
    ):
        return sum(subscores[k] for k in canonical_keys if subscores.get(k) is not None)

    return sum(
        v for k, v in subscores.items()
        if k not in {"narrative", "_maxes"} and isinstance(v, (int, float))
    )


def _session_assessment_pct(session: SimSession) -> int:
    """Normalize a stored assessment score using the session's own subscore shape."""
    subs = (session.narrative_data or {}).get("subscores") if getattr(session, "narrative_data", None) else None
    return _assessment_pct(getattr(session, "assessment_score", None), subs)


def _session_critical_failure(session: SimSession) -> dict | None:
    """Return the persisted critical-failure payload, if any."""
    snap = getattr(session, "score_snapshot", None) or {}
    if isinstance(snap, dict):
        cf = snap.get("critical_failure")
        if isinstance(cf, dict) and cf.get("triggered"):
            return cf
    return None


def _session_counts_as_passing_pilot_scenario(session: SimSession) -> bool:
    """Return true when this session passes one of the Station 1 pilot scenarios."""
    if getattr(session, "scenario_id", None) not in _PILOT_PEDIATRIC_CHAMPION_SCENARIOS:
        return False
    if _session_critical_failure(session):
        return False

    narrative_data = getattr(session, "narrative_data", None) or {}
    subscores = narrative_data.get("subscores") if isinstance(narrative_data, dict) else None
    assessment_score = getattr(session, "assessment_score", None)
    assessment_passed = False
    if assessment_score is not None:
        assessment_max = _assessment_max_from_subscores(subscores)
        assessment_passed = (assessment_score / float(assessment_max)) >= PASSING_PCT

    normalized_score = getattr(session, "score", None)
    normalized_passed = (normalized_score or 0) >= PASSING_SCORE
    return assessment_passed or normalized_passed


async def _pilot_pediatric_champion_complete(
    user_id: str,
    agency_id: str | None,
    db: AsyncSession,
    *,
    current_session: SimSession | None = None,
) -> bool:
    """Check distinct passed pilot scenarios instead of legacy category counters."""
    stmt = select(SimSession).where(
        SimSession.user_id == user_id,
        SimSession.scenario_id.in_(_PILOT_PEDIATRIC_CHAMPION_SCENARIOS),
        SimSession.ended_at.isnot(None),
    )
    if agency_id:
        stmt = stmt.where(SimSession.agency_id == agency_id)
    if current_session is not None and getattr(current_session, "id", None):
        stmt = stmt.where(SimSession.id != current_session.id)

    result = await db.execute(stmt)
    passed_scenarios = {
        session.scenario_id
        for session in result.scalars().all()
        if _session_counts_as_passing_pilot_scenario(session)
    }
    if current_session and _session_counts_as_passing_pilot_scenario(current_session):
        passed_scenarios.add(current_session.scenario_id)
    return _PILOT_PEDIATRIC_CHAMPION_SCENARIOS.issubset(passed_scenarios)


class AdjudicationRequest(BaseModel):
    reason_type:        str
    reason_notes:       str = ""
    corrected_score:    int | None = None          # normalized 0–100
    corrected_subscores: dict | None = None        # {clinical_performance, protocols_treatment|scope_adherence, dmist, professionalism, narrative}
    override_findings:  list | None = None         # cited evidence packet dimensions being corrected


def _validate_adjudication_request(req: AdjudicationRequest) -> None:
    if req.reason_type not in _ADJUDICATION_REASON_TYPES:
        raise HTTPException(400, f"reason_type must be one of: {sorted(_ADJUDICATION_REASON_TYPES)}")
    if req.corrected_score is None and req.corrected_subscores is None:
        raise HTTPException(400, "At least one of corrected_score or corrected_subscores is required")
    if req.corrected_score is not None and not (0 <= req.corrected_score <= 100):
        raise HTTPException(400, "corrected_score must be 0–100")
    if req.corrected_subscores is not None:
        bad_keys = set(req.corrected_subscores) - _VALID_SUBSCORE_KEYS
        if bad_keys:
            raise HTTPException(400, f"Unknown subscore keys: {sorted(bad_keys)}. Valid keys: {sorted(_VALID_SUBSCORE_KEYS)}")
        for key, val in req.corrected_subscores.items():
            if not isinstance(val, (int, float)):
                raise HTTPException(400, f"corrected_subscores[{key!r}] must be a number")
    if req.reason_type == "human_appeal" and not (req.reason_notes or "").strip():
        raise HTTPException(400, "reason_notes is required for human_appeal adjudications")


def _adjudication_out(a: AdjudicatedOutcome, adjudicator_username: str = "") -> dict:
    return {
        "id":                   a.id,
        "reason_type":          a.reason_type,
        "reason_notes":         a.reason_notes or "",
        "adjudicated_by":       adjudicator_username or a.adjudicated_by,
        "corrected_score":      a.corrected_score,
        "corrected_subscores":  a.corrected_subscores,
        "override_findings":    a.override_findings,
        "created_at":           a.created_at.isoformat() if a.created_at else None,
    }


@app.post("/api/sessions/{session_id}/adjudications", status_code=201)
@limiter.limit(f"{settings.rate_limit_debrief}/minute")
async def create_adjudication(
    request: Request,
    session_id: str,
    req: AdjudicationRequest,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    _validate_adjudication_request(req)
    result = await db.execute(select(SimSession).where(SimSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not ctx.is_superuser and session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=403, detail="Session belongs to a different agency")
    record = AdjudicatedOutcome(
        session_id=session_id,
        reason_type=req.reason_type,
        reason_notes=(req.reason_notes or "")[:2000] or None,
        adjudicated_by=ctx.user_id,
        corrected_score=req.corrected_score,
        corrected_subscores=req.corrected_subscores,
        override_findings=req.override_findings,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {
        "id":          record.id,
        "session_id":  session_id,
        "reason_type": record.reason_type,
        "created_at":  record.created_at.isoformat(),
    }


@app.get("/api/sessions/{session_id}/adjudications")
@limiter.limit(f"{settings.rate_limit_session_write}/minute")
async def list_session_adjudications(
    request: Request,
    session_id: str,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: list all adjudication records for a session, newest last."""
    result = await db.execute(select(SimSession).where(SimSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not ctx.is_superuser and session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=403, detail="Session belongs to a different agency")

    adj_result = await db.execute(
        select(AdjudicatedOutcome)
        .where(AdjudicatedOutcome.session_id == session_id)
        .order_by(AdjudicatedOutcome.created_at)
    )
    adjudications = adj_result.scalars().all()

    adj_user_ids = list({a.adjudicated_by for a in adjudications})
    if adj_user_ids:
        u_result = await db.execute(select(User).where(User.id.in_(adj_user_ids)))
        adj_user_map = {u.id: u.username for u in u_result.scalars().all()}
    else:
        adj_user_map = {}

    return {
        "session_id":      session_id,
        "original_score":  session.score,
        "effective_score": _effective_score(session),
        "adjudications":   [_adjudication_out(a, adj_user_map.get(a.adjudicated_by, "")) for a in adjudications],
    }


# ── Phase 6 instructor endpoints ──────────────────────────────────────────────


@app.get("/api/sessions/{session_id}/review-queue")
@limiter.limit(f"{settings.rate_limit_session_write}/minute")
async def get_review_queue(
    request: Request,
    session_id: str,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: list checklist items in 'ambiguous' state awaiting human review."""
    result = await db.execute(select(SimSession).where(SimSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not ctx.is_superuser and session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=403, detail="Session belongs to a different agency")

    states_blob = session.checklist_states or {}
    item_states = states_blob.get("item_states", [])
    ambiguous = [s for s in item_states if s.get("state") == "ambiguous"]

    if not ambiguous:
        return {"session_id": session_id, "items": []}

    # Enrich with item metadata from the scenario
    try:
        scenario = load_scenario(session.scenario_id)
    except Exception:
        scenario = {}
    items_by_id = {i["id"]: i for i in scenario.get("checklist", [])}

    enriched = []
    for s in ambiguous:
        meta = items_by_id.get(s.get("item_id"), {})
        enriched.append({
            "item_id":            s.get("item_id"),
            "state":              s.get("state"),
            "notes":              s.get("notes"),
            "description":        meta.get("description", ""),
            "subtype":            meta.get("subtype", ""),
            "category":           meta.get("category", ""),
            "point_value":        meta.get("point_value", 0),
            "evidence_references": s.get("evidence_references", []),
        })

    return {"session_id": session_id, "items": enriched}


class OverrideRequest(BaseModel):
    item_id:   str
    new_state: str   # "satisfied" | "not_satisfied"
    rationale: str


_VALID_OVERRIDE_STATES = {"satisfied", "not_satisfied"}


@app.post("/api/sessions/{session_id}/override", status_code=200)
@limiter.limit(f"{settings.rate_limit_debrief}/minute")
async def override_checklist_item(
    request: Request,
    session_id: str,
    req: OverrideRequest,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: resolve an ambiguous checklist item and recompute scores."""
    if req.new_state not in _VALID_OVERRIDE_STATES:
        raise HTTPException(400, f"new_state must be one of: {sorted(_VALID_OVERRIDE_STATES)}")
    if not (req.rationale or "").strip():
        raise HTTPException(400, "rationale is required for item overrides")

    result = await db.execute(select(SimSession).where(SimSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not ctx.is_superuser and session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=403, detail="Session belongs to a different agency")

    states_blob = session.checklist_states or {}
    item_states_raw: list[dict] = list(states_blob.get("item_states", []))

    # Load scenario and prefer the persisted checklist snapshot so instructor
    # overrides operate against the exact rule bundle this session originally used.
    try:
        scenario = load_scenario(session.scenario_id)
    except Exception:
        raise HTTPException(500, "Could not load scenario for this session")
    effective_defs = states_blob.get("checklist_definitions") or []
    if effective_defs:
        effective_checklist = [ChecklistItem.model_validate(i) for i in effective_defs]
    else:
        agency_dict = await load_agency(session.agency_id, db)
        adapted_scenario = adapt_scenario_to_context(scenario, agency_dict, session.mca, session.effective_protocol_excerpt)
        ctx_snap = session.effective_context or {}
        effective_checklist = load_checklist(
            adapted_scenario,
            level=ctx_snap.get("provider_level", getattr(session, "provider_level", "EMT")),
            mca=ctx_snap.get("mca", getattr(session, "mca", settings.default_mca)),
            agency_id=ctx_snap.get("agency_id", session.agency_id),
        )
    items_by_id = {i.id: i for i in effective_checklist}

    target_found = False
    for s in item_states_raw:
        if s.get("item_id") == req.item_id:
            current_state = s.get("state")
            if current_state not in ("ambiguous",):
                raise HTTPException(
                    400,
                    f"Item {req.item_id!r} is not in a reviewable state "
                    f"(current: {current_state!r}; only 'ambiguous' items may be overridden)",
                )
            item_meta = items_by_id.get(req.item_id)
            point_value = int(item_meta.point_value if item_meta else 0)
            s["state"] = req.new_state
            s["earned_points"] = point_value if req.new_state == "satisfied" else 0
            s["notes"] = f"instructor override by {ctx.user_id}: {req.rationale[:500]}"
            s["critical_failure_triggered"] = bool(
                item_meta and item_meta.critical_failure and req.new_state in ("not_satisfied", "contradicted", "unsupported_by_run")
            )
            target_found = True
            break

    if not target_found:
        raise HTTPException(404, f"Item {req.item_id!r} not found in checklist states for this session")

    # Recompute scores from updated item states
    agency_dict = await load_agency(session.agency_id, db)
    adapted_scenario = adapt_scenario_to_context(scenario, agency_dict, session.mca, session.effective_protocol_excerpt)

    updated_states = [ChecklistItemState.model_validate(s) for s in item_states_raw]
    updated_scores = compute_scores(
        updated_states,
        effective_checklist,
        scenario=adapted_scenario,
    )

    # Build corrected_subscores from deterministic categories only
    corrected_subscores = {}
    for cat, score in updated_scores.items():
        if score.total is not None:  # skip legacy_ai pending categories
            corrected_subscores[cat] = score.total

    # Persist the updated checklist states and score_snapshot.
    # score_snapshot must be updated here: re_debrief() calls adjudicate_and_persist()
    # which no-ops on unchanged inputs and reconstructs from score_snapshot, so a
    # stale snapshot would produce inconsistent category scores after an override.
    states_blob["item_states"] = item_states_raw
    session.checklist_states = states_blob
    flag_modified(session, "checklist_states")

    snap = dict(session.score_snapshot or {})
    snap["categories"] = {cat: score.model_dump() for cat, score in updated_scores.items()}
    snap["critical_failure"] = _compute_critical_failure_status(updated_states, effective_checklist)
    session.score_snapshot = snap
    flag_modified(session, "score_snapshot")

    override_record = AdjudicatedOutcome(
        session_id=session_id,
        reason_type="instructor_override",
        reason_notes=req.rationale[:2000],
        adjudicated_by=ctx.user_id,
        corrected_score=None,
        corrected_subscores=corrected_subscores if corrected_subscores else None,
        override_findings=[{"item_id": req.item_id, "new_state": req.new_state}],
        created_at=datetime.utcnow(),
    )
    db.add(override_record)
    await db.commit()

    return {
        "session_id":          session_id,
        "item_id":             req.item_id,
        "new_state":           req.new_state,
        "updated_subscores":   corrected_subscores,
        "adjudication_id":     override_record.id,
    }


@app.post("/api/sessions/{session_id}/re-debrief", status_code=200)
@limiter.limit(f"{settings.rate_limit_debrief}/minute")
async def re_debrief(
    request: Request,
    session_id: str,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: regenerate debrief coaching text from the current session state.

    Rate-limited to rate_limit_debrief/minute.  Audited via AdjudicatedOutcome.
    Requires the session to have completed narrative submission.
    Subscores are re-derived from current state; coaching prose is regenerated by AI.
    """
    result = await db.execute(select(SimSession).where(SimSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not ctx.is_superuser and session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=403, detail="Session belongs to a different agency")
    if not session.narrative_submitted or not session.feedback:
        raise HTTPException(
            400,
            "Re-debrief requires the session to have completed narrative submission",
        )

    agency_dict = await load_agency(session.agency_id, db)
    scenario = adapt_scenario_to_context(load_scenario(session.scenario_id), agency_dict, session.mca, session.effective_protocol_excerpt)

    existing_nd = session.narrative_data or {}
    narrative_dict = {
        "narrative": existing_nd.get("narrative", ""),
    }
    if existing_nd.get("drill"):
        narrative_dict["drill"] = True
        if existing_nd.get("drill_source"):
            narrative_dict["drill_source"] = existing_nd["drill_source"]

    # Re-run deterministic adjudication (picks up any instructor overrides)
    _det_packet = await adjudicate_and_persist(session, scenario, db)
    _all_completed_ids = await _get_completed_scenario_ids(session.user_id, session.agency_id, db)
    _student_history = await _get_rc_history(session.user_id, session.agency_id, _all_completed_ids, db)
    _minigame_gaps = await _get_recent_mistake_tags(session.user_id, db)

    try:
        from app.ai_client import _sanitize_input, _MAX_NARRATIVE_INPUT_CHARS  # noqa: PLC0415
        narrative_dict["narrative"] = _sanitize_input(
            narrative_dict["narrative"], _MAX_NARRATIVE_INPUT_CHARS
        )
        debrief_text, structured_subscores, _ep, _score_notes, _extras = await _generate_debrief_with_retry(
            session, scenario, session.treatment_data or {},
            narrative_dict, session.dmist_report or "",
            agency_dict=agency_dict,
            lexi_assist_labels=[],    # not stored; acceptable degradation
            include_narrative=bool(existing_nd.get("narrative")),
            scene_entry=session.scene_entry,
            student_history=_student_history,
            minigame_gaps=_minigame_gaps,
        )
    except Exception as e:
        log.error(
            "Re-debrief generation failed for session %s: %s: %s",
            session_id, type(e).__name__, e,
        )
        raise HTTPException(
            status_code=503,
            detail="Re-debrief generation is temporarily unavailable. Please try again.",
        )

    subscores = dict(structured_subscores)
    if _det_packet is not None:
        det = extract_deterministic_subscores(_det_packet)
        for cat, val in det.items():
            if val is not None:
                subscores[cat] = val

    # Recompute totals
    assessment_score = _compute_assessment_score_from_subscores(subscores)
    narrative_score = subscores.get("narrative", 0)
    score = assessment_score

    # Persist updated coaching text and scores
    existing_nd["subscores"] = subscores
    existing_nd["score_notes"] = _score_notes
    existing_nd["top_takeaways"] = _extras.get("top_takeaways") or []
    existing_nd["reflection_prompts"] = _extras.get("reflection_prompts") or []
    existing_nd["next_action"] = _extras.get("next_action") or ""
    existing_nd["next_action_target_type"] = _extras.get("next_action_target_type") or "none"
    existing_nd["next_action_target_id"] = _extras.get("next_action_target_id")
    session.narrative_data = existing_nd
    _store_session_debrief(session, debrief_text)
    session.score = score
    session.assessment_score = assessment_score
    session.narrative_score = narrative_score
    session.evidence_packet = _ep
    flag_modified(session, "narrative_data")

    # Audit record
    audit = AdjudicatedOutcome(
        session_id=session_id,
        reason_type="instructor_re_debrief",
        reason_notes=f"Re-debrief triggered by instructor {ctx.user_id}",
        adjudicated_by=ctx.user_id,
        corrected_score=score,
        corrected_subscores=subscores,
        override_findings=None,
        created_at=datetime.utcnow(),
    )
    db.add(audit)
    await db.commit()

    return {
        "feedback":                  debrief_text,
        "score":                     score,
        "assessment_score":          assessment_score,
        "narrative_score":           narrative_score,
        "subscores":                 subscores or None,
        "critical_failure":          (_det_packet.critical_failure if _det_packet is not None else _session_critical_failure(session)),
        "adjudication_id":           audit.id,
        "top_takeaways":             _extras.get("top_takeaways") or [],
        "reflection_prompts":        _extras.get("reflection_prompts") or [],
        "next_action":               _extras.get("next_action") or "",
        "next_action_target_type":   _extras.get("next_action_target_type") or "none",
        "next_action_target_id":     _extras.get("next_action_target_id"),
        "impression_challenge":      (_ep or {}).get("impression_challenge"),
        "dmist_primary_impression":  session.dmist_primary_impression,
    }


# ── Treatment submission ──────────────────────────────────────────────────────
# Rate limit exempt: once-per-session endpoint. already_submitted guard makes
# repeated calls idempotent (returns immediately without any state change). No LLM call.

@app.post("/api/sessions/{session_id}/treatment")
async def submit_treatment(
    session_id: str,
    req: TreatmentRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_owned_session(session_id, db, ctx)
    if session.treatment_submitted:
        return {"status": "already_submitted"}
    session.treatment_submitted = True
    # Override the client-built interventions_performed with the authoritative DB record
    # so that treatment_data never diverges from session.interventions regardless of caller.
    treatment_dict = req.model_dump()
    treatment_dict["interventions_performed"] = [i.name for i in session.interventions]
    session.treatment_data = treatment_dict
    await db.commit()
    return {"status": "ok", "next": "dmist"}


# ── DMIST ─────────────────────────────────────────────────────────────────────
# Rate limit exempt: once-per-session endpoint. already_submitted guard returns
# immediately on retry. Narrative rate limit (rate_limit_debrief) covers the LLM
# call that follows — DMIST submission itself is pure DB write.

@app.post("/api/sessions/{session_id}/dmist")
async def submit_dmist(
    session_id: str,
    req: DmistRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_owned_session(session_id, db, ctx)
    if not session.treatment_submitted:
        raise HTTPException(status_code=400, detail="Submit treatment plan before DMIST")
    if session.dmist_submitted:
        return {"status": "already_submitted", "next": "narrative"}
    report = req.report.strip()
    if not report:
        raise HTTPException(status_code=422, detail="report is required")
    session.dmist_submitted = True
    session.dmist_report = report
    session.dmist_primary_impression = (
        (req.primary_impression or "").strip()
        or extract_primary_impression_from_dmist(report)
    )
    await db.commit()
    return {"status": "ok", "next": "narrative"}


# ── Narrative — triggers debrief generation ───────────────────────────────────

@app.post("/api/sessions/{session_id}/narrative")
@limiter.limit(f"{settings.rate_limit_debrief}/minute")
async def submit_narrative(
    request: Request,
    session_id: str,
    req: NarrativeRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_owned_session(session_id, db, ctx)
    if not session.dmist_submitted:
        raise HTTPException(status_code=400, detail="Complete DMIST turnover before narrative")
    agency_dict = await load_agency(session.agency_id, db)
    scenario = adapt_scenario_to_context(load_scenario(session.scenario_id), agency_dict, session.mca, session.effective_protocol_excerpt)

    # ── Orientation static debrief path ──────────────────────────────────────
    if _is_orientation_session(session, scenario):
        return await _complete_orientation_session(
            session,
            scenario,
            db,
            ctx.user_id,
            narrative_data={"narrative": req.narrative},
            narrative_attempted=True,
        )

    if session.narrative_submitted and session.feedback:
        # Return cached result with effective (post-adjudication) values so the
        # cached response is always consistent with the adjudication list endpoint.
        stored = session.narrative_data or {}
        _eff_subscores = _effective_subscores(session) or stored.get("subscores") or {}
        _synced_feedback = _synchronize_debrief_scores(
            session.feedback,
            _eff_subscores,
            scenario,
            include_narrative=True,
        )
        _ep_cached = session.evidence_packet or {}
        _cached_ic = _ep_cached.get("impression_challenge")
        _cached_ic_result = (_cached_ic or {}).get("result") if _cached_ic else None
        _cached_sc_ic_enabled = bool((scenario.get("impression_challenge") or {}).get("enabled"))
        _cached_qualifying = not _cached_sc_ic_enabled or _cached_ic_result in ("correct", "acceptable")
        _cached_client_feedback = _synced_feedback if _cached_qualifying else _redact_reference_sections(_synced_feedback or "")
        return {
            "feedback":                  _cached_client_feedback,
            "score":                     _effective_score(session) if _effective_score(session) is not None else session.score,
            "subscores":                 _eff_subscores or None,
            "timeline":                  stored.get("timeline"),
            "rubric_detail":             stored.get("rubric_detail") or _build_session_rubric_detail(session),
            "exemplar_dmist":            stored.get("exemplar_dmist") if _cached_qualifying else None,
            "exemplar_narrative":        stored.get("exemplar_narrative") if _cached_qualifying else None,
            "reference_markdown":        stored.get("reference_markdown") if _cached_qualifying else "",
            "critical_failure":          _session_critical_failure(session),
            "top_takeaways":             stored.get("top_takeaways") or [],
            "reflection_prompts":        stored.get("reflection_prompts") or [],
            "next_action":               stored.get("next_action") or "",
            "next_action_target_type":   stored.get("next_action_target_type") or "none",
            "next_action_target_id":     stored.get("next_action_target_id"),
            "cpr_challenge_summary":     stored.get("cpr_challenge_summary"),
            "impression_challenge":      _cached_ic,
            "dmist_primary_impression":  session.dmist_primary_impression,
            "debrief_lexi_hints":        stored.get("debrief_lexi_hints") if _cached_qualifying else [],
        }

    # ── Phase 4: deterministic adjudication before AI debrief ────────────────
    _det_packet = await adjudicate_and_persist(session, scenario, db)

    # ── Next Action routing (computed pre-LLM from deterministic signals) ─────
    _all_completed_ids = await _get_completed_scenario_ids(session.user_id, session.agency_id, db)
    _student_history = await _get_rc_history(session.user_id, session.agency_id, _all_completed_ids, db)
    _minigame_gaps = await _get_recent_mistake_tags(session.user_id, db)

    existing_nd = session.narrative_data or {}
    # Cap narrative input to prevent token abuse
    from app.ai_client import _sanitize_input, _MAX_NARRATIVE_INPUT_CHARS
    narrative_dict = {"narrative": _sanitize_input(req.narrative, _MAX_NARRATIVE_INPUT_CHARS)}
    if existing_nd.get("drill"):
        narrative_dict["drill"] = True
        if existing_nd.get("drill_source"):
            narrative_dict["drill_source"] = existing_nd.get("drill_source")

    try:
        debrief_text, structured_subscores, _ep, _score_notes, _extras = await _generate_debrief_with_retry(
            session, scenario, session.treatment_data or {},
            narrative_dict, session.dmist_report or "",
            agency_dict=agency_dict,
            lexi_assist_labels=req.lexi_assist_labels,
            include_narrative=True,
            scene_entry=session.scene_entry,
            student_history=_student_history,
            minigame_gaps=_minigame_gaps,
        )
    except Exception as e:
        log.error("Debrief generation failed for session %s: %s: %s", session_id, type(e).__name__, e)
        raise HTTPException(
            status_code=503,
            detail="Debrief generation is temporarily unavailable. Please try again.",
        )

    # ── Extract per-category subscores ───────────────────────────────────────
    # evaluate_and_generate_debrief guarantees all required keys are present
    # (raises ValueError → 503 if not), so structured_subscores is authoritative.
    subscores = dict(structured_subscores)

    # ── Phase 4: overlay deterministic scores where available ─────────────────
    # _det_packet is non-None only for scenarios with a checklist array.
    # Deterministic categories (clinical_performance, protocols_treatment, scope_adherence) replace
    # the AI-generated values; documentation and professionalism remain from AI
    # until Phase 6 separated extraction calls are wired.
    if _det_packet is not None:
        det = extract_deterministic_subscores(_det_packet)
        for cat, val in det.items():
            if val is not None:  # None = legacy_ai pending — keep AI value
                subscores[cat] = val
        maxes = dict(subscores.get("_maxes") or {})
        for cat, score in _det_packet.score_snapshot.items():
            if score.total is not None:
                maxes[cat] = int(score.max)
        if maxes:
            subscores["_maxes"] = maxes

    debrief_text = _synchronize_debrief_scores(
        debrief_text,
        subscores,
        scenario,
        include_narrative=True,
    )

    # ── Compute final scores (backend is the arithmetic authority) ────────────
    assessment_score: Optional[int] = None
    narrative_score:  Optional[int] = None
    score: Optional[int] = None

    assessment_score = _compute_assessment_score_from_subscores(subscores)

    narrative_score = subscores.get("narrative", 0)

    if assessment_score is not None:
        score = assessment_score
        if narrative_score is None:
            narrative_score = 0

    # ── Build intervention timeline ───────────────────────────────────────────
    timeline = _build_session_timeline(
        session,
        scenario,
        agency_dict,
        scene_entry=session.scene_entry,
        session_events=await _load_session_events_for_timeline(session.id, db),
    )
    rubric_detail = _build_session_rubric_detail(session)

    # ── Exemplar content from scenario ───────────────────────────────────────
    exemplar_dmist = scenario.get("exemplar_dmist")
    exemplar_narrative = scenario.get("exemplar_narrative")
    reference_markdown = _scenario_reference_md(scenario)

    # Redact condition/treatment reference sections from the client payload when IC is
    # enabled for this scenario and the result is not qualifying.
    # session.feedback always stores the full text for server-side notebook unlock.
    _redact_sc_ic_enabled = bool((scenario.get("impression_challenge") or {}).get("enabled"))
    _ic_for_redact = ((_ep or {}).get("impression_challenge") or {})
    _ic_result_for_redact = _ic_for_redact.get("result")
    _ic_qualifying = not _redact_sc_ic_enabled or _ic_result_for_redact in ("correct", "acceptable")

    # ── Persist enriched data ─────────────────────────────────────────────────
    narrative_dict["subscores"] = subscores
    narrative_dict["score_notes"] = _score_notes
    narrative_dict["timeline"] = timeline
    narrative_dict["rubric_detail"] = rubric_detail
    narrative_dict["top_takeaways"] = _extras.get("top_takeaways") or []
    narrative_dict["reflection_prompts"] = _extras.get("reflection_prompts") or []
    narrative_dict["next_action"] = _extras.get("next_action") or ""
    narrative_dict["next_action_target_type"] = _extras.get("next_action_target_type") or "none"
    narrative_dict["next_action_target_id"] = _extras.get("next_action_target_id")
    narrative_dict["debrief_lexi_hints"] = _debrief_lexi_hints_for_client(
        scenario,
        condition_unlocked=_ic_qualifying,
    )
    _cpr_summary = _cpr_challenge_summary_from_evidence(_ep)
    if _cpr_summary:
        narrative_dict["cpr_challenge_summary"] = _cpr_summary
    if exemplar_dmist:
        narrative_dict["exemplar_dmist"] = exemplar_dmist
    if exemplar_narrative:
        narrative_dict["exemplar_narrative"] = exemplar_narrative
    if reference_markdown:
        narrative_dict["reference_markdown"] = reference_markdown

    session.narrative_submitted  = True
    session.narrative_data       = narrative_dict
    _store_session_debrief(session, debrief_text)
    session.score                = score
    session.assessment_score     = assessment_score
    session.narrative_score      = narrative_score
    session.narrative_attempted  = True
    session.ended_at             = datetime.utcnow()
    session.evidence_packet      = _ep   # Phase 3 adjudication record for audit/instructor review

    if session.session_type == "random_call":
        await _update_rc_history(
            session.user_id, session.agency_id, session.scenario_id, score or 0, db
        )

    await db.commit()

    _client_debrief = debrief_text if _ic_qualifying else _redact_reference_sections(debrief_text)

    return {
        "feedback":                  _client_debrief,
        "score":                     score,
        "assessment_score":          assessment_score,
        "narrative_score":           narrative_score,
        "subscores":                 subscores or None,
        "timeline":                  timeline or None,
        "rubric_detail":             rubric_detail or None,
        "exemplar_dmist":            exemplar_dmist if _ic_qualifying else None,
        "exemplar_narrative":        exemplar_narrative if _ic_qualifying else None,
        "reference_markdown":        reference_markdown if _ic_qualifying else "",
        "critical_failure":          (_det_packet.critical_failure if _det_packet is not None else _session_critical_failure(session)),
        "top_takeaways":             _extras.get("top_takeaways") or [],
        "reflection_prompts":        _extras.get("reflection_prompts") or [],
        "next_action":               _extras.get("next_action") or "",
        "next_action_target_type":   _extras.get("next_action_target_type") or "none",
        "next_action_target_id":     _extras.get("next_action_target_id"),
        "cpr_challenge_summary":     _cpr_summary,
        "impression_challenge":      (_ep or {}).get("impression_challenge"),
        "dmist_primary_impression":  session.dmist_primary_impression,
        "debrief_lexi_hints":        narrative_dict["debrief_lexi_hints"],
    }


@app.post("/api/sessions/{session_id}/narrative/skip")
@limiter.limit(f"{settings.rate_limit_debrief}/minute")
async def skip_narrative(
    request: Request,
    session_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Generate debrief without narrative (assessment + DMIST only, max 80 XP via assessment).
    Sets narrative_attempted=False so progress endpoint awards assessment-only XP."""
    session = await _get_owned_session(session_id, db, ctx)
    if not session.dmist_submitted:
        raise HTTPException(status_code=400, detail="Complete DMIST turnover before skipping narrative")
    agency_dict = await load_agency(session.agency_id, db)
    scenario    = adapt_scenario_to_context(load_scenario(session.scenario_id), agency_dict, session.mca, session.effective_protocol_excerpt)
    if _is_orientation_session(session, scenario):
        return await _complete_orientation_session(
            session,
            scenario,
            db,
            ctx.user_id,
            narrative_data={"narrative": "", "skipped_narrative": True},
            narrative_attempted=False,
        )

    if session.narrative_submitted and session.feedback:
        stored = session.narrative_data or {}
        _eff_score = _effective_score(session)
        _eff_subscores = _effective_subscores(session) or stored.get("subscores") or {}
        _synced_feedback = _synchronize_debrief_scores(
            session.feedback,
            _eff_subscores,
            scenario,
            include_narrative=False,
        )
        _ep_cached_skip = session.evidence_packet or {}
        _cached_skip_ic = _ep_cached_skip.get("impression_challenge")
        _cached_skip_ic_result = (_cached_skip_ic or {}).get("result") if _cached_skip_ic else None
        _cached_skip_sc_ic_enabled = bool((scenario.get("impression_challenge") or {}).get("enabled"))
        _cached_skip_qualifying = not _cached_skip_sc_ic_enabled or _cached_skip_ic_result in ("correct", "acceptable")
        _cached_skip_feedback = _synced_feedback if _cached_skip_qualifying else _redact_reference_sections(_synced_feedback or "")
        return {
            "feedback":                 _cached_skip_feedback,
            "score":                    _eff_score if _eff_score is not None else session.score,
            "assessment_score":         _eff_score if _eff_score is not None else session.assessment_score,
            "narrative_score":          None,
            "subscores":                _eff_subscores or None,
            "timeline":                 stored.get("timeline"),
            "rubric_detail":            stored.get("rubric_detail") or _build_session_rubric_detail(session),
            "exemplar_dmist":           stored.get("exemplar_dmist") if _cached_skip_qualifying else None,
            "reference_markdown":       stored.get("reference_markdown") if _cached_skip_qualifying else "",
            "critical_failure":         _session_critical_failure(session),
            "top_takeaways":            stored.get("top_takeaways") or [],
            "reflection_prompts":       stored.get("reflection_prompts") or [],
            "next_action":              stored.get("next_action") or "",
            "next_action_target_type":  stored.get("next_action_target_type") or "none",
            "next_action_target_id":    stored.get("next_action_target_id"),
            "cpr_challenge_summary":    stored.get("cpr_challenge_summary"),
            "impression_challenge":     _cached_skip_ic,
            "dmist_primary_impression": session.dmist_primary_impression,
            "debrief_lexi_hints":       stored.get("debrief_lexi_hints") if _cached_skip_qualifying else [],
        }

    # ── Phase 4: deterministic adjudication before AI debrief ────────────────
    _det_packet = await adjudicate_and_persist(session, scenario, db)

    # ── Next Action routing (computed pre-LLM from deterministic signals) ─────
    _all_completed_ids_skip = await _get_completed_scenario_ids(session.user_id, session.agency_id, db)
    _student_history_skip = await _get_rc_history(session.user_id, session.agency_id, _all_completed_ids_skip, db)
    _minigame_gaps_skip = await _get_recent_mistake_tags(session.user_id, db)

    try:
        debrief_text, structured_subscores, _ep, _score_notes, _extras = await _generate_debrief_with_retry(
            session, scenario, session.treatment_data or {},
            session.narrative_data or {}, session.dmist_report or "",
            agency_dict=agency_dict,
            include_narrative=False,
            scene_entry=session.scene_entry,
            student_history=_student_history_skip,
            minigame_gaps=_minigame_gaps_skip,
        )
    except Exception as e:
        log.error("Debrief generation failed for session %s: %s: %s", session_id, type(e).__name__, e)
        raise HTTPException(
            status_code=503,
            detail="Debrief generation is temporarily unavailable. Please try again.",
        )

    # ── Extract subscores ─────────────────────────────────────────────────────
    # evaluate_and_generate_debrief guarantees all required keys are present.
    subscores = dict(structured_subscores)

    # ── Phase 4: overlay deterministic scores where available ─────────────────
    if _det_packet is not None:
        det = extract_deterministic_subscores(_det_packet)
        for cat, val in det.items():
            if val is not None:
                subscores[cat] = val
        maxes = dict(subscores.get("_maxes") or {})
        for cat, score in _det_packet.score_snapshot.items():
            if score.total is not None:
                maxes[cat] = int(score.max)
        if maxes:
            subscores["_maxes"] = maxes

    debrief_text = _synchronize_debrief_scores(
        debrief_text,
        subscores,
        scenario,
        include_narrative=False,
    )

    # ── Compute final scores (backend is the arithmetic authority) ────────────
    assessment_score: Optional[int] = None
    assessment_score = _compute_assessment_score_from_subscores(subscores)

    score = assessment_score

    # ── Build timeline ────────────────────────────────────────────────────────
    timeline = _build_session_timeline(
        session,
        scenario,
        agency_dict,
        scene_entry=session.scene_entry,
        session_events=await _load_session_events_for_timeline(session.id, db),
    )
    rubric_detail = _build_session_rubric_detail(session)

    exemplar_dmist = scenario.get("exemplar_dmist")
    reference_markdown = _scenario_reference_md(scenario)

    nd = dict(session.narrative_data or {})
    nd["subscores"] = subscores
    nd["score_notes"] = _score_notes
    nd["timeline"]  = timeline
    nd["rubric_detail"] = rubric_detail
    nd["top_takeaways"] = _extras.get("top_takeaways") or []
    nd["reflection_prompts"] = _extras.get("reflection_prompts") or []
    nd["next_action"] = _extras.get("next_action") or ""
    nd["next_action_target_type"] = _extras.get("next_action_target_type") or "none"
    nd["next_action_target_id"] = _extras.get("next_action_target_id")
    _skip_cpr_summary = _cpr_challenge_summary_from_evidence(_ep)
    if _skip_cpr_summary:
        nd["cpr_challenge_summary"] = _skip_cpr_summary
    if exemplar_dmist:
        nd["exemplar_dmist"] = exemplar_dmist
    if reference_markdown:
        nd["reference_markdown"] = reference_markdown

    _skip_sc_ic_enabled = bool((scenario.get("impression_challenge") or {}).get("enabled"))
    _skip_ic_result = (((_ep or {}).get("impression_challenge")) or {}).get("result")
    _skip_qualifying = not _skip_sc_ic_enabled or _skip_ic_result in ("correct", "acceptable")
    nd["debrief_lexi_hints"] = _debrief_lexi_hints_for_client(
        scenario,
        condition_unlocked=_skip_qualifying,
    )

    session.narrative_submitted = True
    session.narrative_data      = nd
    _store_session_debrief(session, debrief_text)
    session.score               = score
    session.assessment_score    = assessment_score
    session.narrative_score     = None
    session.narrative_attempted = False
    session.ended_at            = datetime.utcnow()
    session.evidence_packet     = _ep   # Phase 3 adjudication record for audit/instructor review

    if session.session_type == "random_call":
        await _update_rc_history(
            session.user_id, session.agency_id, session.scenario_id, score or 0, db
        )

    await db.commit()

    _skip_client_debrief = debrief_text if _skip_qualifying else _redact_reference_sections(debrief_text or "")

    return {
        "feedback":                _skip_client_debrief,
        "score":                   score,
        "assessment_score":        assessment_score,
        "narrative_score":         None,
        "subscores":               subscores or None,
        "timeline":                timeline or None,
        "rubric_detail":           rubric_detail or None,
        "exemplar_dmist":          exemplar_dmist if _skip_qualifying else None,
        "reference_markdown":      reference_markdown if _skip_qualifying else "",
        "critical_failure":        (_det_packet.critical_failure if _det_packet is not None else _session_critical_failure(session)),
        "top_takeaways":           _extras.get("top_takeaways") or [],
        "reflection_prompts":      _extras.get("reflection_prompts") or [],
        "next_action":             _extras.get("next_action") or "",
        "next_action_target_type": _extras.get("next_action_target_type") or "none",
        "next_action_target_id":   _extras.get("next_action_target_id"),
        "cpr_challenge_summary":   _skip_cpr_summary,
        "impression_challenge":    (_ep or {}).get("impression_challenge"),
        "dmist_primary_impression": session.dmist_primary_impression,
        "debrief_lexi_hints":      nd["debrief_lexi_hints"],
    }


@app.post("/api/sessions/{session_id}/drill-debrief")
@limiter.limit(f"{settings.rate_limit_debrief}/minute")
async def submit_drill_debrief(
    request: Request,
    session_id: str,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Generate abbreviated AI debrief based on treatment only (no DMIST/narrative required).
    Session marked as drill mode; awards are applied later by /api/me/progress drill rules."""
    session = await _get_owned_session(session_id, db, ctx)
    if not session.treatment_submitted:
        raise HTTPException(status_code=400, detail="Submit treatment before requesting drill debrief")
    if session.narrative_submitted and session.feedback:
        stored = session.narrative_data or {}
        _ep_drill_cached = session.evidence_packet or {}
        return {
            "feedback":                 session.feedback,
            "score":                    session.score,
            "timeline":                 stored.get("timeline"),
            "rubric_detail":            stored.get("rubric_detail") or _build_session_rubric_detail(session),
            "impression_challenge":     _ep_drill_cached.get("impression_challenge"),
            "dmist_primary_impression": session.dmist_primary_impression,
        }

    agency_dict = await load_agency(session.agency_id, db)
    scenario = adapt_scenario_to_context(load_scenario(session.scenario_id), agency_dict, session.mca, session.effective_protocol_excerpt)

    # Build a focused treatment-only prompt (no DMIST/narrative)
    elapsed = (datetime.utcnow() - session.start_time).total_seconds() / 60.0
    protocol = scenario.get("protocol_config", {})
    level = getattr(session, "provider_level", None) or protocol.get("level", "BLS")
    interventions_data = scenario.get("vitals", {}).get("interventions", {})
    correct = scenario["correct_treatment"]

    applied_labels = [
        interventions_data[n]["label"]
        for n in [i.name for i in session.interventions]
        if n in interventions_data
    ]

    # Scene entry context for drill
    _se = session.scene_entry or {}
    _ppe_str = ", ".join(_se.get("ppe_donned", [])) or "none selected"
    _approach_str = "waited for PD" if _se.get("scene_approach") == "waited_for_pd" else "made direct contact"
    _pat_str = _se.get("pat_assessment", None)
    _pat_line = f"\nPAT Assessment: {_pat_str.upper() if _pat_str else 'N/A (non-peds or not recorded)'}"

    drill_prompt = f"""You are an EMS field training officer giving brief feedback on a student's treatment decisions in a quick practice drill (no DMIST or narrative required).

Scenario: {scenario['title']} — Scene time: {elapsed:.1f} min | Level: {level}

Scene Entry: PPE donned: {_ppe_str} | Scene approach: {_approach_str}{_pat_line}

Interventions applied: {applied_labels}
Critical actions expected: {[a['description'] for a in correct.get('critical_actions', [])]}
Recommended actions: {[a['description'] for a in correct.get('recommended_actions', [])]}

Write a short debrief (3–5 paragraphs):
1. What they did well (specific) — include brief note on PPE and scene entry if notable
2. What critical actions were missed and why they matter clinically
3. One key teaching point to carry forward

End with: SCORE: X/100 (treatment performance only; DMIST and narrative not evaluated in drill mode)"""

    try:
        drill_text = await simple_completion(drill_prompt, max_tokens=800)
    except Exception as e:
        log.error("Drill debrief generation failed: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=503, detail="Drill debrief is temporarily unavailable. Please try again.")

    score = None
    m = re.search(r"(?i)(?:ASSESSMENT |OVERALL |FINAL |TOTAL )?SCORE[^:\n]*:\s*(?:\*\*)?\s*(\d+)", drill_text)
    if m:
        score = int(m.group(1))

    # Build timeline (same as full debrief)
    timeline = _build_session_timeline(
        session,
        scenario,
        agency_dict,
        scene_entry=session.scene_entry,
        session_events=await _load_session_events_for_timeline(session.id, db),
    )
    rubric_detail = _build_session_rubric_detail(session)

    prev_nd = session.narrative_data or {}
    drill_data = {"drill": True, "timeline": timeline, "rubric_detail": rubric_detail}
    if prev_nd.get("drill_source"):
        drill_data["drill_source"] = prev_nd.get("drill_source")
    session.narrative_submitted = True
    session.narrative_data = drill_data
    _store_session_debrief(session, drill_text)
    session.score = score
    session.ended_at = datetime.utcnow()
    await db.commit()

    return {
        "feedback":                 drill_text,
        "score":                    score,
        "timeline":                 timeline or None,
        "rubric_detail":            rubric_detail or None,
        "impression_challenge":     None,
        "dmist_primary_impression": None,
    }


@app.post("/api/sessions/{session_id}/medical-control")
@limiter.limit(f"{settings.rate_limit_med_control}/minute")
async def medical_control_call(
    request: Request,
    session_id: str,
    req: MedControlRequest,
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Simulate a medical control physician responding to the student's call.
    The physician knows the MCA protocols but nothing about the caller, their
    level, or the scenario — only what the caller says in this conversation.
    """
    session = await _get_owned_session(session_id, db, ctx)
    mca = session.mca or ctx.mca or "mi_base"

    try:
        response = await get_medical_control_response(mca, req.history, req.message, ctx.agency_id)
    except Exception as e:
        log.error("Medical control failed for session %s: %s: %s", session_id, type(e).__name__, e)
        raise HTTPException(
            status_code=503,
            detail="Medical control is temporarily unavailable. Please try again.",
        )

    db.add(SessionEvent(
        session_id=session.id,
        event_type="medical_control_contact",
        event_key="medical_control_contacted",
        event_data={
            "mca": mca,
            "history_turn_count": len(req.history or []),
            "message_length": len((req.message or "").strip()),
            "response_received": True,
        },
        source="backend_auto",
        occurred_at=datetime.utcnow(),
    ))
    await db.commit()

    return {"response": response}


# ── Admin endpoints ───────────────────────────────────────────────────────────

def _superadmin_agency(ctx: ActiveContext, agency_id: Optional[str]) -> Optional[str]:
    """Return agency_id to use for an operation.
    Superusers may pass an explicit agency_id override; others always use their token's agency."""
    if ctx.is_superuser and agency_id:
        return agency_id
    return ctx.agency_id


@app.get("/api/admin/analytics")
async def admin_analytics(
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    """Return agency coaching insights: scenario trends, practice opportunities, and top missed interventions."""
    effective_agency = _superadmin_agency(ctx, agency_id)

    # Base query: completed sessions with score
    q = select(SimSession).where(SimSession.ended_at.isnot(None), SimSession.score.isnot(None))
    if effective_agency:
        q = q.where(SimSession.agency_id == effective_agency)
    result = await db.execute(q)
    sessions = result.scalars().all()

    PASS_SCORE = PASSING_SCORE

    # ── Per-scenario stats ────────────────────────────────────────────────────
    scenario_map: dict = {}
    for s in sessions:
        sid = s.scenario_id
        if sid not in scenario_map:
            # Try to get display title from cached scenario JSON
            try:
                scen = load_scenario(sid)
                title = scen.get("title", sid)
                category = scen.get("category", "uncategorized")
            except Exception:
                title = sid
                category = "uncategorized"
            scenario_map[sid] = {
                "scenario_id": sid,
                "title": title,
                "category": category,
                "scores": [],
                "assessment_pcts": [],
                "user_scores": {},
            }
        entry = scenario_map[sid]
        entry["scores"].append(s.score)
        entry["assessment_pcts"].append(0 if _session_critical_failure(s) else _session_assessment_pct(s))
        # Track per-user scores for practice-opportunity detection (multiple lower scores on same scenario)
        uid = str(s.user_id)
        if uid not in entry["user_scores"]:
            entry["user_scores"][uid] = []
        entry["user_scores"][uid].append(0 if _session_critical_failure(s) else _session_assessment_pct(s))

    scenario_stats = []
    for sid, entry in scenario_map.items():
        scores = entry["scores"]
        assessment_pcts = entry["assessment_pcts"]
        avg = round(sum(scores) / len(scores)) if scores else 0
        passes = sum(1 for sc in assessment_pcts if sc >= PASS_SCORE)
        scenario_stats.append({
            "scenario_id": sid,
            "title": entry["title"],
            "category": entry.get("category", "uncategorized"),
            "attempts": len(scores),
            "avg_score": avg,
            "pass_rate": round(passes / len(scores) * 100) if scores else 0,
            "on_track_rate": round(passes / len(scores) * 100) if scores else 0,
        })
    scenario_stats.sort(key=lambda x: x["avg_score"])

    # ── Category-level practice opportunities ────────────────────────────────
    category_map: dict = {}
    for entry in scenario_map.values():
        cat = str(entry.get("category") or "uncategorized")
        if cat not in category_map:
            category_map[cat] = {"scores": [], "scenario_ids": set()}
        category_map[cat]["scores"].extend(entry["scores"])
        category_map[cat]["scenario_ids"].add(entry["scenario_id"])

    category_stats = []
    for category, info in category_map.items():
        scores = info["scores"]
        assessment_pcts = [
            0 if _session_critical_failure(s) else _session_assessment_pct(s)
            for s in sessions
            if str(getattr(s, "scenario_id", "")) in info["scenario_ids"]
        ]
        passes = sum(1 for sc in assessment_pcts if sc >= PASS_SCORE)
        avg = round(sum(scores) / len(scores)) if scores else 0
        on_track_rate = round(passes / len(scores) * 100) if scores else 0
        category_stats.append({
            "category": category,
            "attempts": len(scores),
            "scenario_count": len(info["scenario_ids"]),
            "avg_score": avg,
            "on_track_rate": on_track_rate,
            "pass_rate": on_track_rate,  # legacy compatibility
        })
    category_stats.sort(key=lambda x: (x["avg_score"], -x["attempts"]))

    # ── Practice opportunities: 2+ lower-scoring attempts on the same scenario ─
    at_risk_set = set()
    for entry in scenario_map.values():
        for uid, scores in entry["user_scores"].items():
            fails = sum(1 for sc in scores if sc < PASS_SCORE)
            if fails >= 2:
                at_risk_set.add(uid)

    at_risk = []
    if at_risk_set:
        users_res = await db.execute(
            select(User).where(User.id.in_([int(uid) for uid in at_risk_set if uid.isdigit()]))
        )
        for u in users_res.scalars().all():
            # Find which scenarios likely need additional reps
            weak_scenarios = []
            for sid, entry in scenario_map.items():
                uid_str = str(u.id)
                u_scores = entry["user_scores"].get(uid_str, [])
                fails = sum(1 for sc in u_scores if sc < PASS_SCORE)
                if fails >= 2:
                    weak_scenarios.append(entry["title"])
            name = f"{u.first_name} {u.last_name}".strip() or u.username
            at_risk.append({"user_id": u.id, "name": name, "username": u.username, "weak_scenarios": weak_scenarios})

    # ── Top missed interventions: from failed sessions ────────────────────────
    # Interventions in correct_treatment.critical_actions that don't appear in session.interventions
    missed_counts: dict = {}
    failed_sessions = [s for s in sessions if _session_critical_failure(s) or _session_assessment_pct(s) < PASS_SCORE]
    for s in failed_sessions:
        try:
            scen = load_scenario(s.scenario_id)
        except Exception:
            continue
        critical = scen.get("correct_treatment", {}).get("critical_actions", [])
        applied_names = {iv.name for iv in s.interventions}
        for ca in critical:
            ca_id = ca.get("id", "")
            if ca_id and ca_id not in applied_names:
                desc = ca.get("description", ca_id)
                missed_counts[desc] = missed_counts.get(desc, 0) + 1

    top_missed = sorted(
        [{"action": k, "missed_count": v} for k, v in missed_counts.items()],
        key=lambda x: -x["missed_count"]
    )[:8]

    overall_pass_rate = round(
        sum(1 for s in sessions if not _session_critical_failure(s) and _session_assessment_pct(s) >= PASS_SCORE) / len(sessions) * 100
    ) if sessions else 0
    return {
        "scenario_stats": scenario_stats,
        "category_stats": category_stats,
        # New neutral keys (preferred)
        "practice_opportunities": at_risk,
        "on_track_rate_overall": overall_pass_rate,
        # Backward-compatible keys (legacy)
        "at_risk": at_risk,
        "top_missed_actions": top_missed,
        "total_sessions": len(sessions),
        "pass_rate_overall": overall_pass_rate,
    }


@app.get("/api/admin/team-challenges/diagnostics")
async def admin_team_challenge_diagnostics(
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    """Operational diagnostics for team challenge rollout and support."""
    effective_agency = _superadmin_agency(ctx, agency_id)
    now = _lexi_now()

    match_filters = []
    invite_filters = []
    if effective_agency:
        match_filters.append(TeamMatch.agency_id == effective_agency)
        invite_filters.append(TeamInvite.agency_id == effective_agency)

    active_match_count_res = await db.execute(
        select(func.count(TeamMatch.id)).where(
            TeamMatch.status.in_(["forming", "ready", "active"]),
            *match_filters,
        )
    )
    pending_invite_count_res = await db.execute(
        select(func.count(TeamInvite.id)).where(
            TeamInvite.status == "pending",
            *invite_filters,
        )
    )
    stale_forming_res = await db.execute(
        select(func.count(TeamMatch.id)).where(
            TeamMatch.status == "forming",
            TeamMatch.created_at <= now - timedelta(minutes=TEAM_MATCH_FORMING_TTL_MINUTES),
            *match_filters,
        )
    )
    stale_ready_res = await db.execute(
        select(func.count(TeamMatch.id)).where(
            TeamMatch.status == "ready",
            (
                ((TeamMatch.ready_at.isnot(None)) & (TeamMatch.ready_at <= now - timedelta(minutes=TEAM_MATCH_READY_TTL_MINUTES)))
                |
                ((TeamMatch.ready_at.is_(None)) & (TeamMatch.created_at <= now - timedelta(minutes=TEAM_MATCH_READY_TTL_MINUTES)))
            ),
            *match_filters,
        )
    )

    match_q = select(TeamMatch).order_by(TeamMatch.created_at.desc()).limit(20)
    invite_q = select(TeamInvite).order_by(TeamInvite.created_at.desc()).limit(40)
    if effective_agency:
        match_q = match_q.where(TeamMatch.agency_id == effective_agency)
        invite_q = invite_q.where(TeamInvite.agency_id == effective_agency)

    recent_matches_res = await db.execute(match_q)
    recent_matches = recent_matches_res.scalars().all()

    recent_invites_res = await db.execute(invite_q)
    recent_invites = recent_invites_res.scalars().all()

    match_ids = [m.id for m in recent_matches]
    participant_counts: dict[str, int] = {}
    if match_ids:
        part_count_res = await db.execute(
            select(TeamMatchParticipant.match_id, func.count(TeamMatchParticipant.id))
            .where(TeamMatchParticipant.match_id.in_(match_ids))
            .group_by(TeamMatchParticipant.match_id)
        )
        participant_counts = {row[0]: int(row[1] or 0) for row in part_count_res.all()}

    return {
        "agency_id": effective_agency,
        "summary": {
            "active_match_count": int(active_match_count_res.scalar() or 0),
            "pending_invite_count": int(pending_invite_count_res.scalar() or 0),
            "stale_forming_count": int(stale_forming_res.scalar() or 0),
            "stale_ready_count": int(stale_ready_res.scalar() or 0),
        },
        "recent_matches": [
            {
                "id": m.id,
                "status": m.status,
                "challenge_type": m.challenge_type,
                "host_team_id": m.host_team_id,
                "host_user_id": m.host_user_id,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "ready_at": m.ready_at.isoformat() if m.ready_at else None,
                "started_at": m.started_at.isoformat() if m.started_at else None,
                "ended_at": m.ended_at.isoformat() if m.ended_at else None,
                "participant_count": int(participant_counts.get(m.id, 0)),
                "metadata": m.metadata_json or {},
            }
            for m in recent_matches
        ],
        "recent_invites": [
            {
                "id": i.id,
                "status": i.status,
                "challenge_type": i.challenge_type,
                "match_id": i.match_id,
                "source_team_id": i.source_team_id,
                "target_team_id": i.target_team_id,
                "created_at": i.created_at.isoformat() if i.created_at else None,
                "expires_at": i.expires_at.isoformat() if i.expires_at else None,
                "responded_at": i.responded_at.isoformat() if i.responded_at else None,
            }
            for i in recent_invites
        ],
    }


@app.get("/api/admin/sessions")
async def admin_list_sessions(
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    effective_agency = _superadmin_agency(ctx, agency_id)
    if ctx.is_superuser and not effective_agency:
        result = await db.execute(select(SimSession).order_by(SimSession.start_time.desc()))
    else:
        result = await db.execute(
            select(SimSession)
            .where(SimSession.agency_id == effective_agency)
            .order_by(SimSession.start_time.desc())
        )
    sessions = result.scalars().all()

    user_ids = list({s.user_id for s in sessions})
    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    user_map = {
        u.id: {
            "username":     u.username,
            "student_name": " ".join(filter(None, [u.first_name, u.last_name])) or u.username,
        }
        for u in users_result.scalars().all()
    }

    agency_ids = list({s.agency_id for s in sessions if s.agency_id})
    agency_result = await db.execute(select(Agency).where(Agency.id.in_(agency_ids)))
    agency_name_map = {a.id: a.name for a in agency_result.scalars().all()}

    def _scenario_title(scenario_id: str) -> str:
        try:
            return load_scenario(scenario_id).get("title", scenario_id)
        except (FileNotFoundError, KeyError):
            return scenario_id

    def _protocol_label(scenario_id: str) -> str:
        try:
            return load_scenario(scenario_id).get("protocol", "")
        except (FileNotFoundError, KeyError):
            return ""

    return [
        {
            "session_id":          s.id,
            "username":            user_map.get(s.user_id, {}).get("username", s.user_id),
            "student_name":        user_map.get(s.user_id, {}).get("student_name", s.user_id),
            "scenario_id":         s.scenario_id,
            "scenario_title":      _scenario_title(s.scenario_id),
            "protocol":            _protocol_label(s.scenario_id),
            "agency_id":           s.agency_id,
            "agency_name":         agency_name_map.get(s.agency_id, s.agency_file or ""),
            "provider_level":      s.provider_level or "",
            "mca":                 s.mca or "",
            "started_at":          s.start_time,
            "ended_at":            s.ended_at,
            "score":               s.score,
            "effective_score":     _effective_score(s),
            "has_adjudication":    bool(s.adjudications),
            "assessmentScore":     s.assessment_score,
            "narrativeScore":      s.narrative_score,
            "criticalFailure":     _session_critical_failure(s),
            "assessmentMax":       _assessment_max_from_subscores(_effective_subscores(s)),
            "cpr_challenge_summary": (s.narrative_data or {}).get("cpr_challenge_summary"),
            "treatment_submitted": s.treatment_submitted,
            "dmist_submitted":     s.dmist_submitted,
            "narrative_submitted": s.narrative_submitted,
            "message_count":       len(s.messages),
            "interventions":       [i.name for i in s.interventions],
        }
        for s in sessions
    ]


@app.get("/api/admin/sessions/{session_id}")
async def admin_get_session(
    session_id: str,
    ctx: ActiveContext = Depends(get_instructor_context),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SimSession).where(SimSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not ctx.is_superuser and session.agency_id != ctx.agency_id:
        raise HTTPException(status_code=403, detail="Session belongs to a different agency")

    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalar_one_or_none()

    agency_name = ""
    if session.agency_id:
        a_result = await db.execute(select(Agency).where(Agency.id == session.agency_id))
        a = a_result.scalar_one_or_none()
        agency_name = a.name if a else session.agency_file or ""

    try:
        protocol_label = load_scenario(session.scenario_id).get("protocol", "")
    except (FileNotFoundError, KeyError):
        protocol_label = ""

    # Build adjudicator username map
    adj_user_ids = list({a.adjudicated_by for a in session.adjudications})
    if adj_user_ids:
        adj_u_result = await db.execute(select(User).where(User.id.in_(adj_user_ids)))
        adj_user_map = {u.id: u.username for u in adj_u_result.scalars().all()}
    else:
        adj_user_map = {}

    return {
        "session_id":          session.id,
        "username":            user.username if user else session.user_id,
        "student_name":        " ".join(filter(None, [user.first_name, user.last_name])) if user else session.user_id,
        "scenario_id":         session.scenario_id,
        "agency_id":           session.agency_id,
        "agency_name":         agency_name,
        "provider_level":      session.provider_level or "",
        "mca":                 session.mca or "",
        "protocol":            protocol_label,
        "started_at":          session.start_time,
        "ended_at":            session.ended_at,
        "score":               session.score,
        "effective_score":     _effective_score(session),
        "effective_subscores": _effective_subscores(session),
        "has_adjudication":    bool(session.adjudications),
        "cpr_challenge_summary": (session.narrative_data or {}).get("cpr_challenge_summary"),
        "treatment_submitted": session.treatment_submitted,
        "treatment_data":      session.treatment_data,
        "dmist_report":        session.dmist_report,
        "narrative_data":      session.narrative_data,
        "feedback":            session.feedback,
        "evidence_packet":     session.evidence_packet,
        "interventions":       [{"name": i.name, "applied_at": i.applied_at} for i in session.interventions],
        "transcript":          [{"role": m.role, "content": m.content, "timestamp": m.timestamp} for m in session.messages],
        "adjudications":       [_adjudication_out(a, adj_user_map.get(a.adjudicated_by, "")) for a in session.adjudications],
    }


@app.get("/api/admin/users")
async def admin_list_users(
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    effective_agency = _superadmin_agency(ctx, agency_id)
    if ctx.is_superuser and not effective_agency:
        result = await db.execute(select(User).order_by(User.created_at.desc()))
        users = result.scalars().all()
    else:
        m_result = await db.execute(
            select(AgencyMember).where(AgencyMember.agency_id == effective_agency)
        )
        user_ids = [m.user_id for m in m_result.scalars().all()]
        result = await db.execute(
            select(User).where(User.id.in_(user_ids)).order_by(User.created_at.desc())
        )
        users = result.scalars().all()

    # Build agency name map — column projection avoids loading Agency ORM objects
    # (which would trigger Agency.members selectin for every agency)
    agency_ids = list({m.agency_id for u in users for m in u.memberships})
    agency_result = await db.execute(
        select(Agency.id, Agency.name).where(Agency.id.in_(agency_ids))
    )
    agency_names = {row.id: row.name for row in agency_result.all()}

    # Session counts via a single COUNT query instead of loading session objects
    user_ids_list = [u.id for u in users]
    count_result = await db.execute(
        select(SimSession.user_id, func.count(SimSession.id).label("cnt"))
        .where(SimSession.user_id.in_(user_ids_list))
        .group_by(SimSession.user_id)
    )
    session_counts = {row.user_id: row.cnt for row in count_result.all()}

    return [
        {
            "user_id":       u.id,
            "username":      u.username,
            "first_name":    u.first_name or "",
            "last_name":     u.last_name  or "",
            "email":         u.email      or "",
            "is_superuser":  u.is_superuser,
            "is_active":     u.is_active,
            "created_at":    u.created_at,
            "last_login":    u.last_login,
            "session_count": session_counts.get(u.id, 0),
            "memberships": [
                {
                    "agency_id":      m.agency_id,
                    "agency_name":    agency_names.get(m.agency_id, m.agency_id),
                    "role":           m.role,
                    "provider_level": m.provider_level,
                    "mca":            m.mca,
                    "protocol_profile_id": m.protocol_profile_id,
                    "protocol_profile_assignment_source": m.protocol_profile_assignment_source,
                }
                for m in u.memberships
            ],
        }
        for u in users
    ]


@app.get("/api/admin/users/{user_id}")
async def admin_get_member(
    user_id: str,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: return full profile + gamification for a specific user."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Non-superusers can only view members of their own agency
    if not ctx.is_superuser:
        m_result = await db.execute(
            select(AgencyMember).where(
                AgencyMember.user_id   == user_id,
                AgencyMember.agency_id == ctx.agency_id,
            )
        )
        if not m_result.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="User is not a member of your agency")

    count_res = await db.execute(
        select(func.count(SimSession.id))
        .where(SimSession.user_id == user_id)
        .where(SimSession.ended_at.isnot(None))
    )
    session_count = count_res.scalar() or 0

    # Fetch agency names for all memberships
    mem_agency_ids = [m.agency_id for m in user.memberships]
    agency_result  = await db.execute(select(Agency).where(Agency.id.in_(mem_agency_ids)))
    agency_names   = {a.id: a.name for a in agency_result.scalars().all()}

    return {
        "user_id":         user.id,
        "username":        user.username,
        "first_name":      user.first_name  or "",
        "last_name":       user.last_name   or "",
        "email":           user.email       or "",
        "is_superuser":    user.is_superuser,
        "is_active":       user.is_active,
        "created_at":      user.created_at,
        "last_login":      user.last_login,
        "xp":              user.xp          or 0,
        "treats":          user.treats if user.treats is not None else 3,
        "badges":          user.badges      or [],
        "peds_count":      user.peds_count  or 0,
        "peds_trauma_count": user.peds_trauma_count or 0,
        "session_count":   session_count,
        "memberships": [
            {
                "agency_id":      m.agency_id,
                "agency_name":    agency_names.get(m.agency_id, m.agency_id),
                "role":           m.role,
                "provider_level": m.provider_level,
                "mca":            m.mca,
                "protocol_profile_id": m.protocol_profile_id,
                "protocol_profile_assignment_source": m.protocol_profile_assignment_source,
            }
            for m in user.memberships
        ],
    }


@app.put("/api/admin/users/{user_id}")
async def admin_update_member(
    user_id: str,
    request: Request,
    req: AdminUpdateMemberRequest,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: update profile and/or membership details for a member."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_superuser and not ctx.is_superuser:
        raise HTTPException(status_code=403, detail="Cannot modify a superuser account")

    effective_agency = _superadmin_agency(ctx, agency_id)

    # Scope check: non-superusers can only edit members of their agency
    membership = None
    if not ctx.is_superuser:
        m_result = await db.execute(
            select(AgencyMember).where(
                AgencyMember.user_id   == user_id,
                AgencyMember.agency_id == effective_agency,
            )
        )
        membership = m_result.scalar_one_or_none()
        if not membership:
            raise HTTPException(status_code=403, detail="User is not a member of your agency")
    elif effective_agency:
        m_result = await db.execute(
            select(AgencyMember).where(
                AgencyMember.user_id   == user_id,
                AgencyMember.agency_id == effective_agency,
            )
        )
        membership = m_result.scalar_one_or_none()

    if req.first_name is not None:
        user.first_name = req.first_name.strip() or None
    if req.last_name is not None:
        user.last_name = req.last_name.strip() or None
    if req.email is not None:
        user.email = req.email.strip() or None
    # Only superadmin can toggle is_active; superusers themselves can never be deactivated
    if req.is_active is not None and ctx.is_superuser and not user.is_superuser:
        user.is_active = req.is_active
    db.add(user)

    if membership:
        # Fetch agency config for ceiling enforcement
        agency_result = await db.execute(select(Agency).where(Agency.id == membership.agency_id))
        member_agency = agency_result.scalar_one_or_none()
        member_agency_config = member_agency.config if member_agency else None
        previous_protocol_profile_id = membership.protocol_profile_id
        previous_protocol_profile_source = membership.protocol_profile_assignment_source or "default"

        if req.provider_level is not None:
            membership.provider_level = _resolve_member_provider_level(req.provider_level, member_agency_config)
        if req.mca is not None:
            membership.mca = _resolve_member_mca(req.mca, member_agency_config)
        if req.protocol_profile_id == "__default__":
            if member_agency:
                await _assign_agency_default_protocol_profile(db, agency=member_agency, membership=membership)
        elif req.protocol_profile_id:
            profile_result = await db.execute(
                select(AgencyProtocolProfile).where(
                    AgencyProtocolProfile.id == req.protocol_profile_id,
                    AgencyProtocolProfile.agency_id == membership.agency_id,
                    AgencyProtocolProfile.is_active == True,
                )
            )
            profile = profile_result.scalar_one_or_none()
            if not profile:
                raise HTTPException(status_code=422, detail="Protocol profile is not active for this agency")
            membership.protocol_profile_id = profile.id
            membership.protocol_profile_assignment_source = "manual"
        if (
            previous_protocol_profile_id != membership.protocol_profile_id
            or previous_protocol_profile_source != (membership.protocol_profile_assignment_source or "default")
        ):
            await _write_agency_audit_log(
                db,
                agency_id=membership.agency_id,
                user_id=ctx.user_id,
                action="member_protocol_profile_assigned",
                previous_state={
                    "target_user_id": user.id,
                    "protocol_profile_id": previous_protocol_profile_id,
                    "assignment_source": previous_protocol_profile_source,
                },
                new_state={
                    "target_user_id": user.id,
                    "protocol_profile_id": membership.protocol_profile_id,
                    "assignment_source": membership.protocol_profile_assignment_source,
                },
                request=request,
            )
        db.add(membership)

    await db.commit()
    return {"ok": True}


@app.post("/api/admin/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: str,
    req: AdminResetPasswordRequest,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: reset a member's password."""
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_superuser and not ctx.is_superuser:
        raise HTTPException(status_code=403, detail="Cannot reset a superuser's password")
    if user_id == ctx.user_id:
        raise HTTPException(status_code=400, detail="Use your profile settings to change your own password")

    # Non-superuser scope check
    if not ctx.is_superuser:
        m_result = await db.execute(
            select(AgencyMember).where(
                AgencyMember.user_id   == user_id,
                AgencyMember.agency_id == ctx.agency_id,
            )
        )
        if not m_result.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="User is not a member of your agency")

    user.hashed_password = _hash_password(req.new_password)
    db.add(user)
    await db.commit()
    return {"ok": True}


@app.put("/api/agency/members/{user_id}")
async def update_member_role(
    user_id: str,
    req: UpdateMemberRoleRequest,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Change a member's role within the active agency. Admin-protected."""
    if user_id == ctx.user_id:
        raise HTTPException(status_code=400, detail="You cannot change your own role")
    if req.role not in ("student", "instructor", "admin"):
        raise HTTPException(status_code=422, detail="Role must be one of: student, instructor, admin")

    m_result = await db.execute(
        select(AgencyMember).where(
            AgencyMember.user_id   == user_id,
            AgencyMember.agency_id == ctx.agency_id,
        )
    )
    membership = m_result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this agency")

    # Last-admin guard: block if this demotion would leave the agency adminless
    if membership.role == "admin" and req.role != "admin":
        remaining = await db.execute(
            select(AgencyMember).where(
                AgencyMember.agency_id == ctx.agency_id,
                AgencyMember.role      == "admin",
                AgencyMember.user_id   != user_id,
            )
        )
        if not remaining.scalars().all():
            raise HTTPException(status_code=400, detail="Cannot demote the last admin of this agency")

    membership.role = req.role
    db.add(membership)
    await db.commit()
    return {"user_id": user_id, "role": req.role}


@app.post("/api/agency/members", status_code=201)
async def admin_add_member(
    req: AdminAddMemberRequest,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Admin: add an existing user to the active agency by username."""
    effective = _superadmin_agency(ctx, agency_id) or ctx.agency_id
    if not effective:
        raise HTTPException(status_code=403, detail="No active agency")

    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail=f"No user found with username '{req.username}'")

    # Check if already a member
    existing = await db.execute(
        select(AgencyMember).where(
            AgencyMember.user_id   == user.id,
            AgencyMember.agency_id == effective,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"'{req.username}' is already a member of this agency")

    if req.role not in ("student", "instructor", "admin"):
        raise HTTPException(status_code=400, detail="Role must be student, instructor, or admin")

    agency_result = await db.execute(select(Agency).where(Agency.id == effective))
    target_agency = agency_result.scalar_one_or_none()

    membership = AgencyMember(
        user_id        = user.id,
        agency_id      = effective,
        role           = req.role,
        provider_level = _resolve_member_provider_level(req.provider_level, target_agency.config if target_agency else None),
        mca            = _resolve_member_mca(req.mca, target_agency.config if target_agency else None),
    )
    await _assign_agency_default_protocol_profile(db, agency=target_agency, membership=membership)
    db.add(membership)
    await db.commit()

    return {
        "user_id":   user.id,
        "username":  user.username,
        "first_name": user.first_name or "",
        "last_name":  user.last_name  or "",
    }


@app.delete("/api/agency/members/{user_id}", status_code=200)
async def remove_agency_member(
    user_id: str,
    agency_id: Optional[str] = None,
    ctx: ActiveContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
):
    """Remove a user from the active agency. SimSession records are retained."""
    effective = _superadmin_agency(ctx, agency_id) or ctx.agency_id
    if not effective:
        raise HTTPException(status_code=400, detail="No active agency context")

    if user_id == ctx.user_id:
        raise HTTPException(status_code=400, detail="You cannot remove yourself from the agency")

    m_result = await db.execute(
        select(AgencyMember).where(
            AgencyMember.user_id   == user_id,
            AgencyMember.agency_id == effective,
        )
    )
    membership = m_result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this agency")

    # Last-admin guard
    if membership.role == "admin":
        remaining = await db.execute(
            select(AgencyMember).where(
                AgencyMember.agency_id == effective,
                AgencyMember.role      == "admin",
                AgencyMember.user_id   != user_id,
            )
        )
        if not remaining.scalars().all():
            raise HTTPException(status_code=400, detail="Cannot remove the last admin of this agency")

    await db.delete(membership)
    await db.commit()
    return {"removed": user_id}


# ── User notes ────────────────────────────────────────────────────────────────

class NoteCreateRequest(BaseModel):
    title:       str
    body:        str
    session_id:  Optional[str] = None
    scenario_id: Optional[str] = None
    tags:        list[str] = []


class NoteUpdateRequest(BaseModel):
    title: str
    body:  str
    tags:  list[str] = []


def _normalize_tags(raw: list[str]) -> list[str]:
    seen: list[str] = []
    for t in raw:
        normalized = t.strip().lower()[:50]
        if normalized and normalized not in seen:
            seen.append(normalized)
    return seen[:10]


def _note_to_dict(note: "UserNote", scenario_display_name: Optional[str]) -> dict:
    return {
        "id":                   note.id,
        "session_id":           note.session_id,
        "scenario_id":          note.scenario_id,
        "scenario_display_name": scenario_display_name,
        "title":                note.title,
        "body":                 note.body,
        "tags":                 note.tags or [],
        "created_at":           note.created_at.isoformat() if note.created_at else None,
        "updated_at":           note.updated_at.isoformat() if note.updated_at else None,
    }


def _scenario_display_name(scenario_id: Optional[str]) -> Optional[str]:
    if not scenario_id:
        return None
    try:
        return load_scenario(scenario_id).get("title") or scenario_id
    except Exception:
        return scenario_id


@app.post("/api/notes", status_code=201)
@limiter.limit(f"{settings.rate_limit_session_write}/minute")
async def create_note(
    request: Request,
    req: NoteCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    title = req.title.strip()
    body  = req.body.strip()
    if not title or len(title) > 200:
        raise HTTPException(status_code=400, detail="title must be 1–200 characters")
    if not body or len(body) > 2000:
        raise HTTPException(status_code=400, detail="body must be 1–2000 characters")

    scenario_id = req.scenario_id or None
    session_id  = req.session_id  or None

    if session_id:
        s_result = await db.execute(
            select(SimSession).where(SimSession.id == session_id, SimSession.user_id == current_user.id)
        )
        sess = s_result.scalar_one_or_none()
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        if scenario_id and sess.scenario_id != scenario_id:
            raise HTTPException(status_code=400, detail="scenario_id does not match session")
        scenario_id = sess.scenario_id

    note = UserNote(
        user_id     = current_user.id,
        session_id  = session_id,
        scenario_id = scenario_id,
        title       = title,
        body        = body,
        tags        = _normalize_tags(req.tags),
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return _note_to_dict(note, _scenario_display_name(note.scenario_id))


@app.get("/api/notes")
async def list_notes(
    session_id:  Optional[str] = None,
    scenario_id: Optional[str] = None,
    tags:        Optional[str] = None,
    q:           Optional[str] = None,
    limit:       int = 50,
    offset:      int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if session_id and scenario_id:
        raise HTTPException(status_code=400, detail="session_id and scenario_id are mutually exclusive")
    limit = min(max(limit, 1), 200)

    stmt = select(UserNote).where(UserNote.user_id == current_user.id)
    if session_id:
        stmt = stmt.where(UserNote.session_id == session_id)
    if scenario_id:
        stmt = stmt.where(UserNote.scenario_id == scenario_id)
    if tags:
        for tag in tags.split(","):
            t = tag.strip().lower()
            if t:
                stmt = stmt.where(UserNote.tags.contains([t]))
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            UserNote.title.ilike(pattern) | UserNote.body.ilike(pattern)
        )
    stmt = stmt.order_by(UserNote.updated_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    notes  = result.scalars().all()
    return [_note_to_dict(n, _scenario_display_name(n.scenario_id)) for n in notes]


@app.get("/api/notes/{note_id}")
async def get_note(
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserNote).where(UserNote.id == note_id, UserNote.user_id == current_user.id)
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return _note_to_dict(note, _scenario_display_name(note.scenario_id))


@app.put("/api/notes/{note_id}")
@limiter.limit(f"{settings.rate_limit_session_write}/minute")
async def update_note(
    request: Request,
    note_id: str,
    req: NoteUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserNote).where(UserNote.id == note_id, UserNote.user_id == current_user.id)
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    title = req.title.strip()
    body  = req.body.strip()
    if not title or len(title) > 200:
        raise HTTPException(status_code=400, detail="title must be 1–200 characters")
    if not body or len(body) > 2000:
        raise HTTPException(status_code=400, detail="body must be 1–2000 characters")

    note.title = title
    note.body  = body
    note.tags  = _normalize_tags(req.tags)
    note.updated_at = datetime.utcnow()
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return _note_to_dict(note, _scenario_display_name(note.scenario_id))


@app.delete("/api/notes/{note_id}", status_code=200)
@limiter.limit(f"{settings.rate_limit_session_write}/minute")
async def delete_note(
    request: Request,
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserNote).where(UserNote.id == note_id, UserNote.user_id == current_user.id)
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.delete(note)
    await db.commit()
    return {"deleted": note_id}


# ── Notebook helpers ──────────────────────────────────────────────────────────

def _extract_debrief_reference_md(feedback: str) -> str:
    """Extract sections 8–9 (Condition — and Treatment & Protocol Reference) from
    the AI debrief text.  Port of the JS _splitDebriefForModal() logic.

    Returns the joined reference markdown, or "" if the sections are absent.
    All content is server-owned text from session.feedback — never client-supplied.
    """
    if not feedback:
        return ""

    sections: list[tuple[int | None, list[str]]] = []
    current_number: int | None = None
    current_lines: list[str] = []

    def _push():
        if current_lines:
            sections.append((current_number, list(current_lines)))

    for line in feedback.splitlines():
        stripped = line.strip()
        numbered = re.match(r'^(?:\*\*|#{1,3}\s*)(\d+)\.\s+', stripped)
        is_condition = bool(re.match(
            r'^(?:\*\*|#{1,3}\s*)?(?:\d+\.\s*)?Condition\s+—',
            stripped, re.IGNORECASE,
        ))
        is_treatment = bool(re.match(
            r'^(?:\*\*|#{1,3}\s*)?(?:\d+\.\s*)?Treatment\s*&\s*Protocol\s*Reference',
            stripped, re.IGNORECASE,
        ))
        if numbered or is_condition or is_treatment:
            _push()
            current_lines = [line]
            if numbered:
                current_number = int(numbered.group(1))
            elif is_condition:
                current_number = 8
            else:
                current_number = 9
        else:
            current_lines.append(line)

    _push()

    ref_parts = [
        "\n".join(lines).rstrip()
        for num, lines in sections
        if num in (8, 9)
    ]
    return "\n\n".join(ref_parts).strip()


def _scenario_reference_md(scenario: dict) -> str:
    """Render authored condition reference markdown for notebook/debrief payloads."""
    return _compose_reference_section(scenario)


def _redact_reference_sections(feedback: str) -> str:
    """Return the debrief text with sections 8 and 9 removed.

    Used for server-side redaction of the condition/treatment reference from the
    API response payload when the learner's IC result is not correct/acceptable.
    session.feedback always stores the full text for server-side unlock verification.
    """
    if not feedback:
        return feedback

    sections: list[tuple[int | None, list[str]]] = []
    current_number: int | None = None
    current_lines: list[str] = []

    def _push():
        if current_lines:
            sections.append((current_number, list(current_lines)))

    for line in feedback.splitlines():
        stripped = line.strip()
        numbered = re.match(r'^(?:\*\*|#{1,3}\s*)(\d+)\.\s+', stripped)
        is_condition = bool(re.match(
            r'^(?:\*\*|#{1,3}\s*)?(?:\d+\.\s*)?Condition\s+—',
            stripped, re.IGNORECASE,
        ))
        is_treatment = bool(re.match(
            r'^(?:\*\*|#{1,3}\s*)?(?:\d+\.\s*)?Treatment\s*&\s*Protocol\s*Reference',
            stripped, re.IGNORECASE,
        ))
        if numbered or is_condition or is_treatment:
            _push()
            current_lines = [line]
            if numbered:
                current_number = int(numbered.group(1))
            elif is_condition:
                current_number = 8
            else:
                current_number = 9
        else:
            current_lines.append(line)

    _push()

    kept_parts = [
        "\n".join(lines).rstrip()
        for num, lines in sections
        if num not in (8, 9)
    ]
    return "\n\n".join(kept_parts).strip()


_QUALIFYING_IC_RESULTS = frozenset({"correct", "acceptable"})

# ── Notebook: condition entries ───────────────────────────────────────────────

class NotebookConditionUpsertRequest(BaseModel):
    scenario_id: str = Field(..., max_length=128)


@app.post("/api/me/notebook/conditions")
async def upsert_notebook_condition(
    body: NotebookConditionUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Server-authoritative upsert: derives all content from the session record.

    Verifies that the user has a completed session for this scenario where the
    impression challenge result (stored in evidence_packet, sourced exclusively
    from backend_auto SessionEvents) is "correct" or "acceptable".  Rejects the
    request with 403 if no qualifying session exists.  All notebook content
    (condition_name, reference_md, scenario_title) is derived server-side from
    authoritative session and scenario data — never from client-supplied values.
    """
    # Find the most recent qualifying session for this user + scenario
    sessions_result = await db.execute(
        select(SimSession)
        .where(
            SimSession.user_id     == current_user.id,
            SimSession.scenario_id == body.scenario_id,
            SimSession.evidence_packet.isnot(None),
        )
        .order_by(SimSession.ended_at.desc())
    )
    sessions = sessions_result.scalars().all()

    qualifying = None
    for sess in sessions:
        ep = sess.evidence_packet or {}
        ic = ep.get("impression_challenge") or {}
        if ic.get("result") in _QUALIFYING_IC_RESULTS:
            qualifying = sess
            break

    if qualifying is None:
        raise HTTPException(
            status_code=403,
            detail="No qualifying session found: impression challenge must be correct or acceptable.",
        )

    ep      = qualifying.evidence_packet or {}
    ic_data = ep.get("impression_challenge") or {}

    try:
        scenario_meta = load_scenario(body.scenario_id)
        scenario_title = scenario_meta.get("title") or body.scenario_id
    except Exception:
        scenario_meta = {}
        scenario_title = body.scenario_id

    # Derive content server-side only. The main feedback text may intentionally
    # omit static reference sections, so prefer authored scenario content and
    # fall back to legacy embedded feedback extraction for older sessions.
    condition_name = (ic_data.get("correct") or "").strip() or body.scenario_id
    reference_md = (
        _scenario_reference_md(scenario_meta)
        if scenario_meta
        else ""
    ) or _extract_debrief_reference_md(qualifying.feedback or "")

    result = await db.execute(
        select(NotebookConditionEntry).where(
            NotebookConditionEntry.user_id     == current_user.id,
            NotebookConditionEntry.scenario_id == body.scenario_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry:
        entry.scenario_title = scenario_title
        entry.condition_name = condition_name
        entry.reference_md   = reference_md
    else:
        entry = NotebookConditionEntry(
            user_id        = current_user.id,
            scenario_id    = body.scenario_id,
            scenario_title = scenario_title,
            condition_name = condition_name,
            reference_md   = reference_md,
        )
        db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {
        "id":             entry.id,
        "scenario_id":    entry.scenario_id,
        "scenario_title": entry.scenario_title,
        "condition_name": entry.condition_name,
        "reference_md":   entry.reference_md,
        "unlocked_at":    entry.unlocked_at.isoformat(),
    }


@app.get("/api/me/notebook/conditions")
async def list_notebook_conditions(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(NotebookConditionEntry)
        .where(NotebookConditionEntry.user_id == ctx.user_id)
        .order_by(NotebookConditionEntry.unlocked_at.desc())
    )
    entries = result.scalars().all()
    return [
        {
            "id":             e.id,
            "scenario_id":    e.scenario_id,
            "scenario_title": e.scenario_title,
            "condition_name": e.condition_name,
            "reference_md":   e.reference_md,
            "unlocked_at":    e.unlocked_at.isoformat(),
        }
        for e in entries
    ]


# ── Notebook: learning entries ────────────────────────────────────────────────

# Server-side registry: game_id → {title, category, learning_page path relative to repo root}
_NOTEBOOK_LEARNING_REGISTRY: dict[str, dict] = {
    "pat":                  {"title": "PAT & TICLS",                    "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/pat/learning_page.md"), "unlock_source": "pat_legacy"},
    "dev_sort":             {"title": "Pediatric Development Stages",    "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/sorting/learning_page.md"), "unlock_source": "dev_sort_legacy"},
    "ten4_facesp":          {"title": "TEN-4 FACESp Bruising Screen",    "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/ten4/learning_page.md")},
    "adult_child_ap_swipe": {"title": "Pediatric vs. Adult A&P",          "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/ap/learning_page.md")},
    "lung_sounds_matcher":  {"title": "Breath Sounds Reference",          "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/lsm/learning_page.md")},
    "sound_check":          {"title": "Sound Check: Breath Sounds",       "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/sound_check/learning_page.md")},
    "history_maker":        {"title": "History Taking: SAMPLE & OPQRST", "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/history/learning_page.md")},
    "peds_gcs_calculator":  {"title": "Pediatric GCS Reference",         "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/peds_gcs_calculator/learning_page.md")},
    "ams_aeioutips":        {"title": "AMS Differential: AEIOUTIPS",      "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/ams_aeioutips/learning_page.md")},
    "dev_flags":            {"title": "Developmental Red Flags",          "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/dev_red_flags/learning_page.md")},
    "dmist_builder":        {"title": "DMIST Handoff Builder",            "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/dmist_builder/learning_page.md")},
    "protocol_pivot":       {"title": "Protocol Pivot",                   "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/protocol_pivot/learning_page.md")},
    "vitals_trend_spotter": {"title": "Vitals Trend Spotter",             "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/vitals_trend/learning_page.md")},
    "shock_spotter_med":    {"title": "Shock Spotter: Medical",           "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/shock_spotter_med/learning_page.md")},
    "diff_dash_ams":        {"title": "Differential Dash: AMS",           "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/diff_dash_ams/learning_page.md")},
    "diff_dash_resp":       {"title": "Differential Dash: Respiratory",   "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/diff_dash_resp/learning_page.md")},
    "rule_of_nines":        {"title": "Rule of Nines",                    "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/rule_of_nines/learning_page.md")},
    "stop_the_bleed":       {"title": "Stop the Bleed",                   "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/stop_the_bleed/learning_page.md")},
    "cpr_bls_concepts":     {"title": "CPR Mastery: AHA BLS Quality Targets", "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/cpr_bls_concepts/learning_page.md")},
    "cpr_bls_sequence":     {"title": "BLS CPR: Chain of Survival",       "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/cpr_bls_sequence/learning_page.md")},
    "bls_sequence":         {"title": "BLS Sequence",                     "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/bls_sequence/learning_page.md")},
    "priority_stack":       {"title": "Priority Stack",                   "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/priority_stack/learning_page.md")},
    "moi_mapper":           {"title": "MOI Mapper",                       "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/moi_mapper/learning_page.md")},
    "shock_spotter_trauma": {"title": "Shock Spotter: Trauma",            "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/shock_spotter_trauma/learning_page.md")},
    "temp_check":           {"title": "Temp Check",                       "category_id": "dog_park", "category_title": "Training Center", "page": Path("static/data/games/temp_check/learning_page.md")},
}


class NotebookLearningUpsertRequest(BaseModel):
    game_id: str = Field(..., max_length=64)


async def _has_passing_minigame_learning_record(
    user: User,
    game_id: str,
    db: AsyncSession,
) -> bool:
    registry_entry = _NOTEBOOK_LEARNING_REGISTRY.get(game_id) or {}
    source = registry_entry.get("unlock_source", "minigame_results")
    if source == "pat_legacy":
        return int(user.pat_best_accuracy or 0) >= _MINIGAME_LEARNING_PASSING_SCORE
    if source == "dev_sort_legacy":
        return int(user.dev_sort_best_accuracy or 0) >= _MINIGAME_LEARNING_PASSING_SCORE

    mg_result = await db.execute(
        select(MinigameResult).where(
            MinigameResult.user_id == user.id,
            MinigameResult.game_id == game_id,
            MinigameResult.score >= _MINIGAME_LEARNING_PASSING_SCORE,
        ).limit(1)
    )
    return mg_result.scalar_one_or_none() is not None


async def _upsert_notebook_learning_entry(
    user_id: str,
    game_id: str,
    registry_entry: dict,
    db: AsyncSession,
) -> NotebookLearningEntry:
    page_path = registry_entry["page"]
    if not page_path.exists():
        raise HTTPException(status_code=404, detail="Learning page content not found on server.")

    content_md = page_path.read_text(encoding="utf-8")
    game_title = registry_entry["title"]

    result = await db.execute(
        select(NotebookLearningEntry).where(
            NotebookLearningEntry.user_id == user_id,
            NotebookLearningEntry.game_id == game_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry:
        entry.game_title = game_title
        entry.content_md = content_md
    else:
        entry = NotebookLearningEntry(
            user_id=user_id,
            game_id=game_id,
            game_title=game_title,
            content_md=content_md,
        )
        db.add(entry)
    return entry


def _notebook_learning_payload(entry: NotebookLearningEntry) -> dict:
    registry_entry = _NOTEBOOK_LEARNING_REGISTRY.get(entry.game_id, {})
    return {
        "id": entry.id,
        "game_id": entry.game_id,
        "game_title": entry.game_title,
        "category_id": registry_entry.get("category_id", "dog_park"),
        "category_title": registry_entry.get("category_title", "Training Center"),
        "content_md": entry.content_md,
        "unlocked_at": entry.unlocked_at.isoformat(),
    }


async def _materialize_eligible_notebook_learning(
    user: User,
    db: AsyncSession,
) -> None:
    for game_id, registry_entry in _NOTEBOOK_LEARNING_REGISTRY.items():
        if await _has_passing_minigame_learning_record(user, game_id, db):
            await _upsert_notebook_learning_entry(user.id, game_id, registry_entry, db)
    await db.commit()


@app.post("/api/me/notebook/learning")
async def upsert_notebook_learning(
    body: NotebookLearningUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Server-authoritative upsert: derives all content from server-side sources.

    Verifies that the user has at least one passing MinigameResult for this game_id.
    Rejects unknown game_ids and games without a registered learning page.
    All notebook content (game_title, content_md) is read from the server
    filesystem — never from client-supplied values.
    """
    registry_entry = _NOTEBOOK_LEARNING_REGISTRY.get(body.game_id)
    if not registry_entry:
        raise HTTPException(status_code=404, detail=f"No learning page registered for game '{body.game_id}'.")

    user = await db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not await _has_passing_minigame_learning_record(user, body.game_id, db):
        raise HTTPException(
            status_code=403,
            detail="No passing play record found for this mini-game.",
        )

    entry = await _upsert_notebook_learning_entry(current_user.id, body.game_id, registry_entry, db)
    await db.commit()
    await db.refresh(entry)
    return _notebook_learning_payload(entry)


@app.get("/api/me/notebook/learning")
async def list_notebook_learning(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await _materialize_eligible_notebook_learning(user, db)

    result = await db.execute(
        select(NotebookLearningEntry)
        .where(NotebookLearningEntry.user_id == current_user.id)
        .order_by(NotebookLearningEntry.unlocked_at.desc())
    )
    entries = result.scalars().all()
    return [_notebook_learning_payload(e) for e in entries]


# ── Static frontend ───────────────────────────────────────────────────────────

class VersionedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        query_string = scope.get("query_string", b"")
        if b"v=" in query_string:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.startswith(("img/", "audio/")):
            response.headers.setdefault("Cache-Control", "public, max-age=86400")
        return response


app.mount("/static", VersionedStaticFiles(directory="static"), name="static")


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    return FileResponse("static/index.html")
