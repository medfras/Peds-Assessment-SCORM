from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
    _hash_password,
    _issue_refresh_token,
    _resolve_member_mca,
    _resolve_member_provider_level,
    _set_auth_cookies,
    _set_refresh_cookie,
    _verify_password,
    get_active_context,
    get_superuser_context,
    limiter,
)
from app.config import settings
from app.database import get_db
from app.models import Agency, AgencyMember, RefreshToken, User, WsTicket

router = APIRouter()


class RegisterRequest(BaseModel):
    username:         str
    password:         str
    agency_join_code: Optional[str] = None
    agency_id:        Optional[str] = None
    email:            Optional[str] = None
    first_name:       Optional[str] = None
    last_name:        Optional[str] = None
    provider_level:   str = "EMT"
    mca:              Optional[str] = None


class TokenSwitchRequest(BaseModel):
    agency_id: str


class ImpersonateRequest(BaseModel):
    agency_id: Optional[str] = None


@router.post("/api/register", status_code=status.HTTP_201_CREATED)
@limiter.limit(f"{settings.rate_limit_auth}/minute")
async def register(request: Request, response: Response, req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if len(req.username.strip()) < 2:
        raise HTTPException(status_code=400, detail="Username must be at least 2 characters")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # Resolve agency: agency_id is always required and is the authoritative selector.
    # A join code is additionally required for private agencies and must match the
    # selected agency — preventing a join code for agency B from registering the
    # user into agency A when agency A is selected in the dropdown.
    if not req.agency_id and not req.agency_join_code:
        raise HTTPException(status_code=400, detail="Provide either an agency join code or select an open-join agency")

    if req.agency_id:
        # agency_id was provided — look up the selected agency first
        agency_result = await db.execute(select(Agency).where(Agency.id == req.agency_id))
        agency = agency_result.scalar_one_or_none()
        if not agency:
            raise HTTPException(status_code=400, detail="Agency not found")
        if agency.is_open_join:
            # Open-join: no code accepted or required
            if req.agency_join_code:
                raise HTTPException(status_code=400, detail="This agency does not use a join code — select it without a PIN")
        else:
            # Private agency: join code required and must match this specific agency
            if not req.agency_join_code:
                raise HTTPException(status_code=400, detail="This agency requires a join code")
            if agency.agency_join_code != req.agency_join_code:
                raise HTTPException(status_code=400, detail="Invalid join code for the selected agency")
    else:
        # Fallback: join code only (no agency_id) — look up by code, reject open-join agencies
        agency_result = await db.execute(
            select(Agency).where(Agency.agency_join_code == req.agency_join_code)
        )
        agency = agency_result.scalar_one_or_none()
        if not agency:
            raise HTTPException(status_code=400, detail="Invalid agency join code")
        if agency.is_open_join:
            raise HTTPException(status_code=400, detail="Invalid agency join code")

    # Username uniqueness
    existing = await db.execute(select(User).where(User.username == req.username.strip()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already taken")

    import uuid
    user = User(
        id=str(uuid.uuid4()),
        username=req.username.strip(),
        hashed_password=_hash_password(req.password),
        is_superuser=False,
        email=req.email.strip() if req.email else None,
        first_name=req.first_name.strip() if req.first_name else None,
        last_name=req.last_name.strip() if req.last_name else None,
    )
    db.add(user)
    await db.flush()  # get user.id before commit

    membership = AgencyMember(
        user_id=user.id,
        agency_id=agency.id,
        role="student",
        provider_level=_resolve_member_provider_level(req.provider_level, agency.config),
        mca=_resolve_member_mca(req.mca, agency.config),
    )
    await _assign_agency_default_protocol_profile(db, agency=agency, membership=membership)
    db.add(membership)
    await db.commit()
    await db.refresh(user)

    token = _create_active_token(user, membership, agency, membership_count=1)
    rt_id = await _issue_refresh_token(user.id, agency.id, db)
    await db.commit()
    _set_auth_cookies(response, token)
    _set_refresh_cookie(response, rt_id)
    return _auth_response(
        token,
        requires_selection=False,
        protocol_profile_assignment_source=membership.protocol_profile_assignment_source,
    )


@router.post("/api/token")
@limiter.limit(f"{settings.rate_limit_auth}/minute")
async def login(request: Request, response: Response, form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == form.username))
    user = result.scalar_one_or_none()
    if not user or not _verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_superuser and not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated. Contact your administrator.",
        )

    # Record login timestamp
    from datetime import datetime as _dt
    user.last_login = _dt.utcnow()
    db.add(user)
    await db.commit()

    memberships = user.memberships  # loaded via selectin (expire_on_commit=False keeps them)

    if not memberships:
        # No agency memberships — superusers get a global token, others are blocked
        if user.is_superuser:
            token = _create_superuser_token(user)
            rt_id = await _issue_refresh_token(user.id, None, db)
            await db.commit()
            _set_auth_cookies(response, token)
            _set_refresh_cookie(response, rt_id)
            return _auth_response(token, requires_selection=False)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No agency membership found. Contact your agency administrator.",
        )

    # Load all agencies and filter to active ones only
    agency_ids = [m.agency_id for m in memberships]
    agencies_result = await db.execute(select(Agency).where(Agency.id.in_(agency_ids)))
    agencies = {a.id: a for a in agencies_result.scalars().all()}

    active_pairs = [
        (m, agencies[m.agency_id])
        for m in memberships
        if m.agency_id in agencies and agencies[m.agency_id].is_active
    ]

    if not active_pairs:
        if user.is_superuser:
            token = _create_superuser_token(user)
            rt_id = await _issue_refresh_token(user.id, None, db)
            await db.commit()
            _set_auth_cookies(response, token)
            _set_refresh_cookie(response, rt_id)
            return _auth_response(token, requires_selection=False)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your agency is currently inactive. Contact your administrator.",
        )

    # Single active membership — fast path to active token
    if len(active_pairs) == 1:
        m, agency = active_pairs[0]
        if not m.protocol_profile_id or getattr(m, "protocol_profile_assignment_source", "default") != "manual":
            await _assign_agency_default_protocol_profile(db, agency=agency, membership=m)
            await db.commit()
        token = _create_active_token(user, m, agency, membership_count=1)
        rt_id = await _issue_refresh_token(user.id, agency.id, db)
        await db.commit()
        _set_auth_cookies(response, token)
        _set_refresh_cookie(response, rt_id)
        return _auth_response(
            token,
            requires_selection=False,
            protocol_profile_assignment_source=m.protocol_profile_assignment_source,
        )

    # Multiple active memberships — base token + selection list
    token = _create_base_token(user)
    for m, a in active_pairs:
        if not m.protocol_profile_id or getattr(m, "protocol_profile_assignment_source", "default") != "manual":
            await _assign_agency_default_protocol_profile(db, agency=a, membership=m)
    rt_id = await _issue_refresh_token(user.id, None, db)
    await db.commit()
    _set_auth_cookies(response, token)
    _set_refresh_cookie(response, rt_id)
    return _auth_response(
        token,
        requires_selection=True,
        memberships=[
            {
                "agency_id":      m.agency_id,
                "agency_name":    a.name,
                "provider_level": m.provider_level,
                "mca":            m.mca,
                "protocol_profile_id": m.protocol_profile_id,
                "protocol_profile_assignment_source": m.protocol_profile_assignment_source,
                "role":           m.role,
            }
            for m, a in active_pairs
        ],
    )


@router.post("/api/token/switch")
async def switch_context(
    req: TokenSwitchRequest,
    request: Request,
    response: Response,
    token: str = Depends(_extract_token),
    db: AsyncSession = Depends(get_db),
):
    """Exchange any valid JWT for an Active JWT scoped to a specific agency."""
    payload = _decode_token(token)
    user_id = payload["sub"]

    m_result = await db.execute(
        select(AgencyMember).where(
            AgencyMember.user_id  == user_id,
            AgencyMember.agency_id == req.agency_id,
        )
    )
    membership = m_result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="No membership in requested agency")

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    agency_result = await db.execute(select(Agency).where(Agency.id == req.agency_id))
    agency = agency_result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if not agency.is_active:
        raise HTTPException(status_code=403, detail="Agency is currently inactive")

    if not membership.protocol_profile_id or getattr(membership, "protocol_profile_assignment_source", "default") != "manual":
        await _assign_agency_default_protocol_profile(db, agency=agency, membership=membership)
        await db.commit()

    count = await _count_memberships(user_id, db)
    new_token = _create_active_token(user, membership, agency, membership_count=count)

    # Rotate refresh token to the new agency context
    old_rt_id = request.cookies.get("pfd_ems_refresh")
    if old_rt_id:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_id == old_rt_id, RefreshToken.revoked == False)
            .values(revoked=True)
        )
    new_rt_id = await _issue_refresh_token(user_id, agency.id, db)
    await db.commit()

    _set_auth_cookies(response, new_token)
    _set_refresh_cookie(response, new_rt_id)
    return _auth_response(
        new_token,
        requires_selection=False,
        protocol_profile_assignment_source=membership.protocol_profile_assignment_source,
    )


@router.post("/api/admin/impersonate")
async def impersonate_agency(
    req: ImpersonateRequest,
    request: Request,
    response: Response,
    ctx: ActiveContext = Depends(get_superuser_context),
    db: AsyncSession = Depends(get_db),
):
    """Superadmin: issue a token scoped to a specific agency (or back to global).

    Rotates the refresh token so that silent refresh after the 60-minute access
    token expires restores the impersonated context, not the previous one.
    """
    user_result = await db.execute(select(User).where(User.id == ctx.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Revoke the current refresh token before issuing a new one for the new context
    old_rt_id = request.cookies.get("pfd_ems_refresh")
    if old_rt_id:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_id == old_rt_id, RefreshToken.revoked == False)
            .values(revoked=True)
        )

    if not req.agency_id:
        # Return to global superadmin context
        token = _create_superuser_token(user)
        new_rt_id = await _issue_refresh_token(ctx.user_id, None, db)
        await db.commit()
        _set_auth_cookies(response, token)
        _set_refresh_cookie(response, new_rt_id)
        return _auth_response(token)

    agency_result = await db.execute(select(Agency).where(Agency.id == req.agency_id))
    agency = agency_result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if not agency.is_active:
        raise HTTPException(status_code=403, detail="Agency is currently inactive")

    # Synthetic membership — superadmin gets admin role, no DB row needed
    fake_membership = SimpleNamespace(
        role="admin",
        provider_level="Paramedic",
        mca=settings.default_mca,
        protocol_profile_id=agency.default_protocol_profile_id,
    )
    token = _create_active_token(user, fake_membership, agency, membership_count=1)
    new_rt_id = await _issue_refresh_token(ctx.user_id, agency.id, db)
    await db.commit()
    _set_auth_cookies(response, token)
    _set_refresh_cookie(response, new_rt_id)
    return _auth_response(token)


@router.get("/api/auth/context")
async def auth_context(request: Request):
    """Return decoded JWT claims from the session cookie for page-load session restore."""
    token = request.cookies.get("pfd_ems_session")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No session")
    payload = _decode_token(token)
    return payload


@router.post("/api/auth/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Revoke refresh token, clear all auth cookies."""
    token_id = request.cookies.get("pfd_ems_refresh")
    if token_id:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_id == token_id, RefreshToken.revoked == False)
            .values(revoked=True)
        )
        await db.commit()
    response.set_cookie("pfd_ems_session", "", max_age=0, path="/", httponly=True)
    response.set_cookie("pfd_ems_csrf", "", max_age=0, path="/")
    response.set_cookie("pfd_ems_refresh", "", max_age=0, path="/", httponly=True)
    return {"ok": True}


@router.post("/api/token/refresh")
async def token_refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token cookie for a new access + refresh token pair.

    Implements rotation: the presented refresh token is revoked and a new one issued.
    The new access token preserves the same agency context stored in the refresh token row.
    """
    token_id = request.cookies.get("pfd_ems_refresh")
    if not token_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    from datetime import datetime as _dt
    # Atomic consume: revoke and read context in one statement to prevent replay
    result = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_id == token_id,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > _dt.utcnow(),
        )
        .values(revoked=True)
        .returning(RefreshToken.user_id, RefreshToken.agency_id)
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user_id, agency_id = row.user_id, row.agency_id

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    # Reconstruct same-scope access token
    if agency_id:
        m_result = await db.execute(
            select(AgencyMember).where(AgencyMember.user_id == user_id, AgencyMember.agency_id == agency_id)
        )
        membership = m_result.scalar_one_or_none()
        a_result = await db.execute(select(Agency).where(Agency.id == agency_id))
        agency = a_result.scalar_one_or_none()
        if membership and agency and agency.is_active:
            count = await _count_memberships(user_id, db)
            new_access = _create_active_token(user, membership, agency, membership_count=count)
        elif user.is_superuser:
            new_access = _create_superuser_token(user)
            agency_id = None
        else:
            new_access = _create_base_token(user)
            agency_id = None
    elif user.is_superuser:
        new_access = _create_superuser_token(user)
    else:
        new_access = _create_base_token(user)

    new_rt_id = await _issue_refresh_token(user_id, agency_id, db)
    await db.commit()

    _set_auth_cookies(response, new_access)
    _set_refresh_cookie(response, new_rt_id)
    return {"ok": True}


@router.post("/api/ws-ticket")
async def create_ws_ticket(
    ctx: ActiveContext = Depends(get_active_context),
    db: AsyncSession = Depends(get_db),
):
    """Issue a 30-second single-use WebSocket auth ticket."""
    import uuid
    from app.models import WsTicket as _WsTicket
    ticket = _WsTicket(
        user_id=ctx.user_id,
        agency_id=ctx.agency_id,
        expires_at=datetime.utcnow() + timedelta(seconds=30),
    )
    db.add(ticket)
    await db.commit()
    return {"ticket": ticket.ticket_id}
