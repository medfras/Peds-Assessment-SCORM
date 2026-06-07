from dataclasses import dataclass
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from passlib.context import CryptContext
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, _IS_PROD
from app.database import get_db
from app.models import User, AgencyMember, Agency, RefreshToken


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.app_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _generate_csrf_token(session_token: str) -> str:
    return hmac.new(
        settings.app_secret_key.encode(),
        session_token.encode(),
        hashlib.sha256,
    ).hexdigest()


def _verify_csrf_token(csrf_header: str, session_token: str) -> bool:
    expected = _generate_csrf_token(session_token)
    return hmac.compare_digest(expected, csrf_header)


async def _extract_token(request: Request) -> str:
    """Read JWT from the httpOnly session cookie or Authorization bearer header.

    Browser SaaS sessions use the httpOnly cookie. Moodle-hosted SCORM launches
    cannot rely on third-party cookies, so the packaged SCO sends its scoped JWT
    explicitly in the Authorization header.
    """
    token = request.cookies.get("pfd_ems_session")
    if token:
        return token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _rate_limit_key(request: Request) -> str:
    """Use JWT sub as the rate-limit key so limits are per user, not per IP."""
    token = request.cookies.get("pfd_ems_session")
    if token:
        try:
            payload = _decode_token(token)
            return payload.get("sub", get_remote_address(request))
        except Exception:
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)


@dataclass
class ActiveContext:
    user_id: str
    username: str
    first_name: str
    is_superuser: bool
    agency_id: Optional[str]
    agency_name: str
    agency_file: Optional[str]
    provider_level: str
    mca: str
    protocol_profile_id: Optional[str]
    role: str
    membership_count: int = 1


async def get_current_user(
    token: str = Depends(_extract_token),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Accepts any valid token (base or active). Loads User from DB."""
    payload = _decode_token(token)
    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def get_active_context(token: str = Depends(_extract_token)) -> ActiveContext:
    """Requires an Active JWT with locked agency context. No DB hit.

    Accepts token_type 'active' (regular login) and 'scorm' (LMS-provisioned).
    SCORM tokens carry the same agency context fields as active tokens.
    In-branch: add explicit restriction checks on sensitive endpoints for 'scorm' tokens.
    """
    payload = _decode_token(token)
    if payload.get("token_type") not in ("active", "scorm"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Active agency context required. "
                "POST to /api/token/switch with your target agency_id."
            ),
        )
    return ActiveContext(
        user_id=payload["sub"],
        username=payload["username"],
        first_name=payload.get("first_name", ""),
        is_superuser=payload.get("is_superuser", False),
        agency_id=payload.get("agency_id"),
        agency_name=payload.get("agency_name", ""),
        agency_file=payload.get("agency_file"),
        provider_level=payload.get("provider_level", settings.default_provider_level),
        mca=payload.get("mca", settings.default_mca),
        protocol_profile_id=payload.get("protocol_profile_id"),
        role=payload.get("role", "student"),
        membership_count=payload.get("membership_count", 1),
    )


def get_instructor_context(ctx: ActiveContext = Depends(get_active_context)) -> ActiveContext:
    if ctx.is_superuser or ctx.role in ("admin", "instructor"):
        return ctx
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Instructor access required")


def get_admin_context(ctx: ActiveContext = Depends(get_active_context)) -> ActiveContext:
    if ctx.is_superuser or ctx.role == "admin":
        return ctx
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


def get_superuser_context(ctx: ActiveContext = Depends(get_active_context)) -> ActiveContext:
    if ctx.is_superuser:
        return ctx
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superuser access required")


# ── Password hashing ──────────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── Provider-level enforcement ────────────────────────────────────────────────

_PROVIDER_LEVEL_ORDER = ["MFR", "EMT", "AEMT", "Paramedic"]


def _resolve_member_mca(requested_mca: Optional[str], agency_config: Optional[dict]) -> str:
    """
    Resolve and validate the MCA for a new AgencyMember.
    The agency's configured MCA is the only allowed value — members cannot
    exceed their agency's MCA. An explicit request that doesn't match the
    agency MCA is silently corrected to the agency's MCA.
    Priority: agency config (authoritative) → system default.
    """
    agency_mca = (agency_config or {}).get("mca") if agency_config else None
    allowed = agency_mca or settings.default_mca
    if requested_mca and requested_mca != allowed:
        return allowed
    return allowed


def _resolve_member_provider_level(requested_level: str, agency_config: Optional[dict]) -> str:
    """
    Resolve and cap the provider level for a new AgencyMember.
    The agency's provider_levels.primary defines the ceiling — a member cannot
    be assigned a level higher than what the agency operates at.
    e.g. an EMT-level agency: a Paramedic joining is capped at EMT.
    """
    agency_ceiling = (agency_config or {}).get("provider_levels", {}).get("primary", "Paramedic")
    ceiling_idx = _PROVIDER_LEVEL_ORDER.index(agency_ceiling) if agency_ceiling in _PROVIDER_LEVEL_ORDER else len(_PROVIDER_LEVEL_ORDER) - 1
    requested_idx = _PROVIDER_LEVEL_ORDER.index(requested_level) if requested_level in _PROVIDER_LEVEL_ORDER else 1
    capped_idx = min(requested_idx, ceiling_idx)
    return _PROVIDER_LEVEL_ORDER[capped_idx]


async def _assign_agency_default_protocol_profile(
    db: AsyncSession,
    *,
    agency: "Agency | None",
    membership: AgencyMember,
) -> None:
    """Pin a membership to the agency-approved default protocol profile."""
    from app.protocol_engine import get_effective_protocol_profile
    if not agency:
        membership.protocol_profile_id = None
        membership.protocol_profile_assignment_source = "default"
        return
    profile = await get_effective_protocol_profile(
        db,
        agency_id=agency.id,
        mca_id=membership.mca,
        protocol_profile_id=None,
    )
    membership.protocol_profile_id = profile.id if profile else None
    membership.protocol_profile_assignment_source = "default"
    db.add(membership)


# ── Token creation ────────────────────────────────────────────────────────────

def _create_base_token(user: User) -> str:
    """Issued when a user has multiple agency memberships and must choose one."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub":          user.id,
        "username":     user.username,
        "first_name":   user.first_name or "",
        "is_superuser": user.is_superuser,
        "token_type":   "base",
        "exp":          expire,
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


async def _count_memberships(user_id: str, db: AsyncSession) -> int:
    result = await db.execute(
        select(AgencyMember).where(AgencyMember.user_id == user_id)
    )
    return len(result.scalars().all())


def _create_active_token(
    user: User, membership: AgencyMember, agency: Agency, membership_count: int = 1
) -> str:
    """Issued when active agency context is locked in."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub":              user.id,
        "username":         user.username,
        "first_name":       user.first_name or "",
        "is_superuser":     user.is_superuser,
        "token_type":       "active",
        "agency_id":        agency.id,
        "agency_name":      agency.name,
        "agency_file":      agency.agency_file,
        "provider_level":   membership.provider_level,
        "mca":              membership.mca,
        "protocol_profile_id": membership.protocol_profile_id or agency.default_protocol_profile_id,
        "role":             membership.role,
        "membership_count": membership_count,
        "exp":              expire,
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


def _create_superuser_token(user: User) -> str:
    """Active token for superusers — no agency membership required."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub":            user.id,
        "username":       user.username,
        "first_name":     user.first_name or "",
        "is_superuser":   True,
        "token_type":     "active",
        "agency_id":      None,
        "agency_name":    "Global",
        "agency_file":    None,
        "provider_level": "Paramedic",
        "mca":            settings.default_mca,
        "protocol_profile_id": None,
        "role":           "admin",
        "exp":            expire,
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


def _create_scorm_token(
    user: User,
    membership: "AgencyMember",
    agency: "Agency",
    attempt_id: str,
    module_id: str,
) -> str:
    """Scoped JWT for LMS-provisioned SCORM learners.

    token_type='scorm' is accepted by get_active_context() so existing
    endpoints (PAT submit, scenario start, etc.) work without modification.
    In-branch: add restriction checks on sensitive endpoints for this token type.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub":               user.id,
        "username":          user.username,
        "first_name":        user.first_name or "",
        "is_superuser":      False,
        "token_type":        "scorm",
        "agency_id":         agency.id,
        "agency_name":       agency.name,
        "agency_file":       agency.agency_file,
        "provider_level":    membership.provider_level,
        "mca":               membership.mca,
        "protocol_profile_id": membership.protocol_profile_id,
        "role":              "student",
        "membership_count":  1,
        "scorm_attempt_id":  attempt_id,
        "scorm_module_id":   module_id,
        "exp":               expire,
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


@dataclass
class ScormContext:
    user_id: str
    scorm_attempt_id: str
    scorm_module_id: str
    agency_id: Optional[str]
    provider_level: str
    mca: str


async def _extract_scorm_token(request: Request) -> str:
    """Read JWT from the session cookie or Authorization Bearer header.

    SCORM clients running in an LMS iframe may not have access to the httpOnly
    cookie across origins, so Bearer header is also accepted for SCORM endpoints.
    """
    token = request.cookies.get("pfd_ems_session")
    if token:
        return token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_scorm_context(token: str = Depends(_extract_scorm_token)) -> ScormContext:
    """Requires a SCORM-scoped JWT. Extracts attempt ID and module ID."""
    payload = _decode_token(token)
    if payload.get("token_type") != "scorm":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SCORM token required.",
        )
    attempt_id = payload.get("scorm_attempt_id")
    if not attempt_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SCORM token missing attempt binding.",
        )
    return ScormContext(
        user_id=payload["sub"],
        scorm_attempt_id=attempt_id,
        scorm_module_id=payload.get("scorm_module_id", ""),
        agency_id=payload.get("agency_id"),
        provider_level=payload.get("provider_level", settings.default_provider_level),
        mca=payload.get("mca", settings.default_mca),
    )


# ── Cookie and refresh-token helpers ─────────────────────────────────────────

def _set_auth_cookies(response: Response, session_token: str) -> None:
    """Set httpOnly session cookie and readable CSRF cookie."""
    response.set_cookie(
        key="pfd_ems_session",
        value=session_token,
        httponly=True,
        secure=_IS_PROD,
        samesite="strict",
        path="/",
        max_age=settings.jwt_expire_minutes * 60,
    )
    response.set_cookie(
        key="pfd_ems_csrf",
        value=_generate_csrf_token(session_token),
        httponly=False,
        secure=_IS_PROD,
        samesite="strict",
        path="/",
        max_age=settings.jwt_expire_minutes * 60,
    )


def _set_refresh_cookie(response: Response, token_id: str) -> None:
    """Set the httpOnly refresh token cookie.

    Path is "/" so the browser sends it to logout, context-switch, and leave-agency
    endpoints that must revoke the token before issuing a replacement.  The cookie
    is httpOnly (JS-inaccessible) and SameSite=Strict, so cross-site CSRF cannot
    trigger a silent refresh.
    """
    response.set_cookie(
        key="pfd_ems_refresh",
        value=token_id,
        httponly=True,
        secure=_IS_PROD,
        samesite="strict",
        path="/",
        max_age=settings.refresh_token_expire_days * 86400,
    )


async def _issue_refresh_token(
    user_id: str, agency_id: Optional[str], db: AsyncSession
) -> str:
    """Persist a new refresh token row and return its token_id. Caller must commit."""
    rt = RefreshToken(
        user_id=user_id,
        agency_id=agency_id,
        expires_at=datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(rt)
    await db.flush()
    return rt.token_id


def _auth_response(token: str, **extra) -> dict:
    """Decode a freshly issued JWT and return its claims as a response dict.

    The frontend uses these fields to populate auth state without reading the
    JWT string from the response body.  Extra keyword args are merged in and
    take precedence over decoded claims.
    """
    return {**_decode_token(token), **extra}
