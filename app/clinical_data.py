"""
Agency clinical config — loaded from the agencies.config JSONB column.
An in-process dict cache avoids repeated DB round-trips; invalidated on PUT.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Agency

_agency_cache: dict[str, dict] = {}


async def load_agency(agency_id: str | None, db: AsyncSession) -> dict:
    """Return the agency's clinical config dict, or {} if absent/unconfigured."""
    if not agency_id:
        return {}
    if agency_id in _agency_cache:
        return _agency_cache[agency_id]
    result = await db.execute(select(Agency).where(Agency.id == agency_id))
    agency = result.scalar_one_or_none()
    if not agency or agency.config is None:
        return {}
    _agency_cache[agency_id] = agency.config
    return agency.config


def invalidate_agency_cache(agency_id: str) -> None:
    _agency_cache.pop(agency_id, None)
