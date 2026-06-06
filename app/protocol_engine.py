"""Protocol loading and snapshot utilities.

Phase 1A keeps protocol content file-backed, but all callers go through this
module so the future database-backed resolver can replace the implementation
without changing scenario, AI, or scoring code.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models import Agency, AgencyProtocolProfile, AgencyProtocolSelection, AgencySOP, ProtocolSnapshot
from app.protocol_concept_index import protocol_concepts, protocol_ids_for_concepts
from app.scenarios.vocabulary import INTERVENTION_ACTIONS, canonical_intervention_id

logger = get_logger()

PROTOCOLS_DIR = Path(__file__).parent / "protocols"
MCA_CONFIG_PATH = Path(__file__).parent / "mca_config.json"

_PROTOCOL_EXCERPT_GENERIC_CONCEPTS = frozenset({
    "airway_management",
    "documentation_handoff",
    "medical_control",
    "oxygen_therapy",
    "patient_assessment",
    "pediatric_patient",
    "primary_survey",
    "respiratory_distress",
    "scene_safety",
    "transport_decision",
    "ventilation_support",
    "vital_signs",
})


@lru_cache(maxsize=1)
def _load_mca_config() -> dict[str, Any]:
    if not MCA_CONFIG_PATH.exists():
        return {"mcas": []}
    with MCA_CONFIG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _mca_base_protocols() -> dict[str, str]:
    cfg = _load_mca_config()
    return {
        m["id"]: m["base_protocols"]
        for m in cfg.get("mcas", [])
        if isinstance(m, dict) and m.get("id") and m.get("base_protocols")
    }


def _protocol_dir_for_mca(mca_id: str) -> Path:
    """Resolve MCA-specific protocol dir, falling back to configured state base."""
    mca_dir = PROTOCOLS_DIR / mca_id
    if mca_dir.exists():
        return mca_dir
    base_key = _mca_base_protocols().get(mca_id)
    if base_key:
        base_dir = PROTOCOLS_DIR / base_key
        if base_dir.exists():
            return base_dir
    return mca_dir


def _protocol_dir_for_base_set(base_protocol_set: str | None) -> Path:
    base = (base_protocol_set or "NASEMSO").strip() or "NASEMSO"
    direct = PROTOCOLS_DIR / base
    if direct.exists():
        return direct
    upper = PROTOCOLS_DIR / base.upper()
    if upper.exists():
        return upper
    return direct


def _base_protocol_set_for_mca(mca_id: str | None) -> str:
    resolved_mca = (mca_id or "mi_base").split("/")[0]
    return _mca_base_protocols().get(resolved_mca) or (
        resolved_mca if (PROTOCOLS_DIR / resolved_mca).exists() else "NASEMSO"
    )


def available_base_protocol_sets() -> list[dict[str, str]]:
    """Return file-backed base protocol sets that may seed a profile."""
    if not PROTOCOLS_DIR.exists():
        return []
    sets = []
    for directory in sorted(p for p in PROTOCOLS_DIR.iterdir() if p.is_dir()):
        sets.append({
            "id": directory.name,
            "label": directory.name.replace("_", " ").replace("-", " ").title(),
        })
    return sets


def _selection_id_for_option(option: dict[str, Any]) -> str:
    explicit = option.get("id") or option.get("selection_id")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    item = str(option.get("item") or "selection").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", item).strip("_")
    return slug or "selection"


@lru_cache(maxsize=1)
def _protocol_id_index() -> dict[str, Path]:
    """Build {protocol_id: path} for all protocol files."""
    index: dict[str, Path] = {}
    for path in sorted(PROTOCOLS_DIR.rglob("*.json")):
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            logger.warning("protocol.index_skip", path=str(path), error=str(exc))
            continue
        protocol_id = data.get("id")
        if isinstance(protocol_id, str) and protocol_id:
            index[protocol_id] = path
    return index


def _resolve_protocol_path(protocol_id: str) -> Path:
    """Resolve canonical protocol IDs and tolerated legacy path-style refs."""
    ref = (protocol_id or "").strip()
    if not ref:
        raise FileNotFoundError("Protocol reference is empty")

    # Legacy compatibility: existing scenarios use path refs such as
    # "MI/04_OB_Pediatrics/04-5_respiratory_distress". Keep this tolerated form
    # internal to the resolver while the public contract moves to protocol IDs.
    if "/" in ref or ref.endswith(".json"):
        normalized = ref[:-5] if ref.endswith(".json") else ref
        path = PROTOCOLS_DIR / f"{normalized}.json"
        if path.exists():
            return path
        raise FileNotFoundError(f"Protocol file not found: {path}")

    path = _protocol_id_index().get(ref)
    if path and path.exists():
        return path

    # Last-chance fallback for callers still passing a file stem.
    matches = sorted(PROTOCOLS_DIR.rglob(f"{ref}.json"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"Protocol ID not found: {protocol_id}")


@lru_cache(maxsize=256)
def get_resolved_protocol(agency_id: str | None, protocol_id: str) -> dict[str, Any]:
    """Return a protocol dict by canonical ID or tolerated legacy path ref.

    ``agency_id`` is accepted now to freeze the resolver interface; Phase 1A
    does not use it because protocol content remains file-backed.
    """
    del agency_id  # reserved for future snapshot/agency-aware resolution
    path = _resolve_protocol_path(protocol_id)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=64)
def _get_all_protocols_for_mca_cached(mca_id: str) -> list[dict[str, Any]]:
    protocols_dir = _protocol_dir_for_mca((mca_id or "mi_base").split("/")[0])
    if not protocols_dir.exists():
        return []
    protocols: list[dict[str, Any]] = []
    for path in sorted(protocols_dir.rglob("*.json")):
        try:
            with path.open(encoding="utf-8") as f:
                protocols.append(json.load(f))
        except Exception as exc:
            logger.warning("protocol.load_skip", path=str(path), error=str(exc))
    return protocols


def get_all_protocols_for_mca(agency_id: str | None, mca_id: str) -> list[dict[str, Any]]:
    """Return all protocol dicts for an MCA/state base without scenario filtering."""
    del agency_id  # reserved for future agency-specific snapshots
    return _get_all_protocols_for_mca_cached((mca_id or "mi_base").split("/")[0])


def warmup_protocol_caches() -> None:
    """Pre-load all protocol file sets into lru_cache.

    Called once at server startup so the first session creation is fast.
    Runs synchronously — intended to be dispatched via asyncio.to_thread.
    """
    if PROTOCOLS_DIR.exists():
        for directory in sorted(p for p in PROTOCOLS_DIR.iterdir() if p.is_dir()):
            _get_all_protocols_for_mca_cached(directory.name)
            get_all_protocols_for_base_set(directory.name)


@lru_cache(maxsize=64)
def get_all_protocols_for_base_set(base_protocol_set: str) -> list[dict[str, Any]]:
    """Return all protocol dicts for a state/national base protocol set."""
    protocols_dir = _protocol_dir_for_base_set(base_protocol_set)
    if not protocols_dir.exists():
        return []

    protocols: list[dict[str, Any]] = []
    for path in sorted(protocols_dir.rglob("*.json")):
        try:
            with path.open(encoding="utf-8") as f:
                protocols.append(json.load(f))
        except Exception as exc:
            logger.warning("protocol.load_skip", path=str(path), error=str(exc))
    return protocols


def get_protocol_concepts(protocol_id: str) -> list[str]:
    """Return clinical concept IDs mapped to a protocol ID in the static Phase 2 index."""
    return sorted(protocol_concepts(protocol_id))


def get_protocols_for_concepts(
    base_protocol_set: str,
    concepts: list[str] | tuple[str, ...] | set[str] | frozenset[str],
) -> list[dict[str, Any]]:
    """Return protocols from a base set mapped to any supplied clinical concept ID.

    This is a Phase 2 pilot helper for protocol tree-shaking. It uses the static
    concept index rather than requiring tags inside protocol JSON files.
    """
    wanted_ids = protocol_ids_for_concepts(concepts)
    if not wanted_ids:
        return []
    return [
        proto
        for proto in get_all_protocols_for_base_set(base_protocol_set)
        if proto.get("id") in wanted_ids
    ]


@lru_cache(maxsize=1)
def intervention_action_index() -> dict[str, list[str]]:
    """Return {UI intervention ID: canonical action IDs} from the vocabulary registry."""
    index: dict[str, list[str]] = {}
    for action_id, action in INTERVENTION_ACTIONS.items():
        intervention_ids = action.get("intervention_ids") if isinstance(action, dict) else None
        if not isinstance(intervention_ids, list):
            continue
        for intervention_id in intervention_ids:
            if not isinstance(intervention_id, str) or not intervention_id:
                continue
            index.setdefault(intervention_id, []).append(action_id)
    return {key: sorted(value) for key, value in index.items()}


def action_ids_for_intervention(intervention_id: str) -> list[str]:
    """Map a scenario/UI intervention ID to canonical action IDs.

    Phase 2B evidence-packet scope analysis uses this mapping as the bridge
    from UI/scenario intervention IDs to stable clinical action IDs.
    """
    canonical_id = canonical_intervention_id(str(intervention_id or ""))
    return intervention_action_index().get(canonical_id, [])


def _scenario_concepts(scenario: dict[str, Any]) -> tuple[list[str], list[str]]:
    context = scenario.get("clinical_context") if isinstance(scenario, dict) else None
    warnings: list[str] = []
    if not isinstance(context, dict):
        return [], ["scenario clinical_context is missing"]

    concepts = context.get("concepts")
    focus = context.get("protocol_focus")
    concept_list = [str(c) for c in concepts] if isinstance(concepts, list) else []
    focus_list = [str(c) for c in focus] if isinstance(focus, list) else []
    merged_concepts = sorted({c for c in [*concept_list, *focus_list] if c})
    if not concept_list:
        warnings.append("scenario clinical_context.concepts is empty")
    return merged_concepts, warnings


def _protocol_match_concepts(scenario: dict[str, Any], concepts: list[str]) -> list[str]:
    """Return the concept set used to select base protocol excerpts.

    ``clinical_context.concepts`` intentionally includes broad support and
    population tags that are useful for SOP overlays and diagnostics. Base
    protocol excerpt selection needs the narrower ``protocol_focus`` tags when
    available, or generic concepts such as ``airway_management`` can pull in
    unrelated standing orders for every pediatric respiratory scenario.
    """
    context = scenario.get("clinical_context") if isinstance(scenario, dict) else None
    focus = context.get("protocol_focus") if isinstance(context, dict) else None
    focus_list = [str(c) for c in focus] if isinstance(focus, list) else []
    raw = sorted({c for c in focus_list if c}) or list(concepts)
    specific = [c for c in raw if c not in _PROTOCOL_EXCERPT_GENERIC_CONCEPTS]
    return sorted(specific or raw)


def _sop_value(sop: AgencySOP | dict[str, Any], field: str) -> Any:
    if isinstance(sop, dict):
        return sop.get(field)
    return getattr(sop, field, None)


def _filtered_sop_rows(
    sops: list[AgencySOP | dict[str, Any]] | tuple[AgencySOP | dict[str, Any], ...] | None,
    concepts: list[str],
    *,
    allowed_statuses: set[str],
) -> list[dict[str, Any]]:
    if not sops:
        return []

    concept_set = set(concepts)
    rows: list[dict[str, Any]] = []
    for sop in sops:
        status = _sop_value(sop, "status")
        if status not in allowed_statuses:
            continue
        raw_tags = _sop_value(sop, "clinical_concept_tags")
        tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []
        matched = sorted(concept_set & set(tags))
        if not matched:
            continue
        rows.append({
            "id": _sop_value(sop, "id"),
            "title": _sop_value(sop, "title"),
            "rule_type": _sop_value(sop, "rule_type"),
            "status": status,
            "sme_review_status": _sop_value(sop, "sme_review_status"),
            "matched_concepts": matched,
            "clinical_concept_tags": sorted(tags),
            "intervention_action_ids": _sop_value(sop, "intervention_action_ids") or [],
            "rule_text": _sop_value(sop, "rule_text") or _sop_value(sop, "extracted_rule"),
            "source_quote": _sop_value(sop, "source_quote"),
            "source_label": _sop_value(sop, "source_label"),
            "source_page": _sop_value(sop, "source_page") or _sop_value(sop, "page_number"),
            "metadata_json": _sop_value(sop, "metadata_json") or {},
        })
    return rows


def build_protocol_excerpt_locked(
    compiled_context: dict[str, Any],
    scenario: dict[str, Any],
    *,
    sops: list[AgencySOP | dict[str, Any]] | tuple[AgencySOP | dict[str, Any], ...] | None = None,
    allow_authoritative: bool = False,
    authoritative: bool = False,
) -> dict[str, Any]:
    """Build the Phase 2B protocol excerpt shape.

    The helper filters a compiled snapshot by scenario concept tags, then
    filters SOP rows by status. By default it returns a non-authoritative
    preview. Authoritative mode is available only when the explicit runtime
    caller passes ``allow_authoritative=True``.
    """
    if authoritative and not allow_authoritative:
        raise ValueError("Authoritative protocol excerpts are blocked until Phase 2B runtime use is explicitly enabled")

    scenario_id = str(scenario.get("id") or "")
    concepts, warnings = _scenario_concepts(scenario)
    protocol_match_concepts = _protocol_match_concepts(scenario, concepts)
    protocols = compiled_context.get("protocols") if isinstance(compiled_context, dict) else None
    protocols = protocols if isinstance(protocols, dict) else {}
    matched_protocols: dict[str, dict[str, Any]] = {}

    def _match_protocol_rows(match_concepts: list[str]) -> dict[str, dict[str, Any]]:
        protocol_match_set = set(match_concepts)
        rows: dict[str, dict[str, Any]] = {}
        indexed_protocol_ids = protocol_ids_for_concepts(match_concepts)
        for protocol_id in sorted(set(protocols) & indexed_protocol_ids):
            proto = protocols.get(protocol_id)
            if not isinstance(proto, dict):
                continue
            indexed_concepts = set(protocol_concepts(protocol_id))
            enriched = dict(proto)
            enriched["static_index_concepts"] = sorted(indexed_concepts)
            enriched["matched_concepts"] = sorted(indexed_concepts & protocol_match_set)
            rows[protocol_id] = enriched
        return rows

    matched_protocols = _match_protocol_rows(protocol_match_concepts)
    if not matched_protocols and protocol_match_concepts != concepts:
        protocol_match_concepts = concepts
        matched_protocols = _match_protocol_rows(protocol_match_concepts)

    if protocol_match_concepts and not matched_protocols:
        warnings.append("no protocols matched scenario protocol focus tags")

    allowed_sop_statuses = {"active"} if authoritative else {"reviewed_non_authoritative", "active"}
    matched_sops = _filtered_sop_rows(sops, concepts, allowed_statuses=allowed_sop_statuses)

    return {
        "schema": "protocol_excerpt_locked_v1",
        "authoritative": bool(authoritative and allow_authoritative),
        "authority_blocked": not bool(authoritative and allow_authoritative),
        "scenario_id": scenario_id,
        "base_protocol_set": (compiled_context.get("protocol_profile") or {}).get("base_protocol_set"),
        "mca_id": compiled_context.get("mca_id"),
        "protocol_profile_id": compiled_context.get("protocol_profile_id"),
        "concepts": concepts,
        "protocol_match_concepts": protocol_match_concepts,
        "protocol_ids": sorted(matched_protocols),
        "protocols": matched_protocols,
        "sop_ids": [str(row["id"]) for row in matched_sops if row.get("id")],
        "sops": matched_sops,
        "warnings": warnings,
    }


def build_protocol_excerpt_preview(
    base_protocol_set: str,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    """Build a non-authoritative protocol excerpt preview from scenario tags.

    This is intentionally not wired into prompts, scoring, Medical Control, or
    persistence. It exists to validate the Phase 2 tagging/index contract before
    clinical SME review makes the tags authoritative.
    """
    scenario_id = str(scenario.get("id") or "")
    context = scenario.get("clinical_context") if isinstance(scenario, dict) else None
    warnings: list[str] = []
    if not isinstance(context, dict):
        return {
            "schema": "protocol_excerpt_preview_v1",
            "authoritative": False,
            "scenario_id": scenario_id,
            "base_protocol_set": base_protocol_set,
            "concepts": [],
            "protocol_match_concepts": [],
            "protocol_ids": [],
            "protocols": {},
            "warnings": ["scenario clinical_context is missing"],
        }

    merged_concepts, concept_warnings = _scenario_concepts(scenario)
    warnings.extend(concept_warnings)
    if not merged_concepts:
        return {
            "schema": "protocol_excerpt_preview_v1",
            "authoritative": False,
            "scenario_id": scenario_id,
            "base_protocol_set": base_protocol_set,
            "concepts": [],
            "protocol_match_concepts": [],
            "protocol_ids": [],
            "protocols": {},
            "warnings": warnings,
        }

    protocol_match_concepts = _protocol_match_concepts(scenario, merged_concepts)

    def _preview_protocol_rows(match_concepts: list[str]) -> dict[str, dict[str, Any]]:
        protocols = get_protocols_for_concepts(base_protocol_set, match_concepts)
        rows: dict[str, dict[str, Any]] = {}
        protocol_match_set = set(match_concepts)
        for proto in protocols:
            if not isinstance(proto, dict) or not isinstance(proto.get("id"), str):
                continue
            pid = str(proto["id"])
            indexed_concepts = set(protocol_concepts(pid))
            enriched = dict(proto)
            enriched["static_index_concepts"] = sorted(indexed_concepts)
            enriched["matched_concepts"] = sorted(indexed_concepts & protocol_match_set)
            rows[pid] = enriched
        return rows

    protocols_by_id = _preview_protocol_rows(protocol_match_concepts)
    if not protocols_by_id and protocol_match_concepts != merged_concepts:
        protocol_match_concepts = merged_concepts
        protocols_by_id = _preview_protocol_rows(protocol_match_concepts)
    if not protocols_by_id:
        warnings.append("no protocols matched scenario protocol focus tags")

    return {
        "schema": "protocol_excerpt_preview_v1",
        "authoritative": False,
        "scenario_id": scenario_id,
        "base_protocol_set": base_protocol_set,
        "jurisdiction": context.get("jurisdiction"),
        "concepts": merged_concepts,
        "protocol_match_concepts": protocol_match_concepts,
        "protocol_ids": sorted(protocols_by_id),
        "protocols": {pid: protocols_by_id[pid] for pid in sorted(protocols_by_id)},
        "warnings": warnings,
    }


def protocol_selection_options_for_base_set(base_protocol_set: str) -> list[dict[str, Any]]:
    """Return structured MCA/profile choices exposed by a base protocol set."""
    options: list[dict[str, Any]] = []
    for proto in get_all_protocols_for_base_set(base_protocol_set):
        proto_id = proto.get("id")
        if not isinstance(proto_id, str) or not proto_id:
            continue
        required = proto.get("mca_selections_required")
        if not isinstance(required, list) or not required:
            continue
        ref = proto.get("protocol_reference") or {}
        section = proto.get("section") or proto.get("category") or ""
        for raw in required:
            if not isinstance(raw, dict):
                continue
            selection_id = _selection_id_for_option(raw)
            choices = raw.get("options") if isinstance(raw.get("options"), list) else []
            options.append({
                "protocol_id": proto_id,
                "protocol_title": proto.get("title") or proto.get("name") or proto_id,
                "protocol_reference": ref,
                "section": section,
                "selection_id": selection_id,
                "item": raw.get("item") or selection_id,
                "description": raw.get("description") or "",
                "options": choices,
                "default_selected": raw.get("selected"),
            })
    return options


def _compiled_context_for_mca(agency_id: str | None, mca_id: str) -> dict[str, Any]:
    protocols = get_all_protocols_for_mca(agency_id, mca_id)
    return {
        "schema": "protocol_snapshot_v1",
        "agency_id": agency_id,
        "mca_id": mca_id,
        "protocols": {
            proto["id"]: proto
            for proto in protocols
            if isinstance(proto, dict) and isinstance(proto.get("id"), str)
        },
    }


def _compiled_context_for_profile(
    agency_id: str | None,
    mca_id: str,
    profile: AgencyProtocolProfile,
    selections: list[AgencyProtocolSelection],
) -> dict[str, Any]:
    protocols = get_all_protocols_for_base_set(profile.base_protocol_set)
    compiled = {
        "schema": "protocol_snapshot_v1",
        "agency_id": agency_id,
        "mca_id": mca_id,
        "protocol_profile_id": profile.id,
        "protocol_profile": {
            "display_name": profile.display_name,
            "profile_type": profile.profile_type,
            "base_protocol_set": profile.base_protocol_set,
            "official_mca_id": profile.official_mca_id,
        },
        "selections": {
            f"{sel.protocol_id}:{sel.selection_id}": {
                "protocol_id": sel.protocol_id,
                "selection_id": sel.selection_id,
                "is_selected": bool(sel.is_selected),
                "selected_value": sel.selected_value,
                "base_protocol_version": sel.base_protocol_version,
            }
            for sel in selections
        },
        "protocols": {
            proto["id"]: proto
            for proto in protocols
            if isinstance(proto, dict) and isinstance(proto.get("id"), str)
        },
    }
    _apply_profile_selections(compiled, selections)
    return compiled


def _apply_profile_selections(
    compiled_json: dict[str, Any],
    selections: list[AgencyProtocolSelection],
) -> None:
    """Overlay structured selections into matching protocol option blocks.

    This deliberately only touches known `mca_selections_required` option
    records. Local free-text protocol changes are a later reviewed pipeline.
    """
    selected_by_key = {
        (sel.protocol_id, sel.selection_id): (
            sel.selected_value if sel.selected_value is not None else bool(sel.is_selected)
        )
        for sel in selections
    }
    if not selected_by_key:
        return
    for protocol_id, proto in (compiled_json.get("protocols") or {}).items():
        stack: list[Any] = [proto]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                options = node.get("mca_selections_required")
                if isinstance(options, list):
                    for option in options:
                        if not isinstance(option, dict):
                            continue
                        selection_id = _selection_id_for_option(option)
                        key = (protocol_id, selection_id)
                        if key in selected_by_key:
                            option["selected"] = selected_by_key[key]
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)


def _canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def protocol_content_hash(compiled_json: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(compiled_json).encode("utf-8")).hexdigest()


async def create_protocol_snapshot(
    db: AsyncSession,
    agency_id: str | None,
    mca_id: str | None,
    protocol_profile_id: str | None = None,
    use_active_profile_snapshot: bool = True,
) -> ProtocolSnapshot:
    """Create or reuse an immutable protocol snapshot for this agency/MCA."""
    resolved_mca = (mca_id or "mi_base").split("/")[0]
    profile = await get_effective_protocol_profile(
        db,
        agency_id=agency_id,
        mca_id=resolved_mca,
        protocol_profile_id=protocol_profile_id,
    )
    if profile:
        if profile.active_protocol_snapshot_id:
            existing_active = await db.get(ProtocolSnapshot, profile.active_protocol_snapshot_id)
            if use_active_profile_snapshot and existing_active:
                return existing_active
        selections_result = await db.execute(
            select(AgencyProtocolSelection).where(
                AgencyProtocolSelection.protocol_profile_id == profile.id
            )
        )
        selections = list(selections_result.scalars().all())
        compiled_json = await asyncio.to_thread(
            _compiled_context_for_profile,
            agency_id,
            resolved_mca,
            profile,
            selections,
        )
    else:
        compiled_json = await asyncio.to_thread(_compiled_context_for_mca, agency_id, resolved_mca)
    content_hash = protocol_content_hash(compiled_json)

    stmt = select(ProtocolSnapshot).where(
        ProtocolSnapshot.agency_id.is_(None)
        if agency_id is None
        else ProtocolSnapshot.agency_id == agency_id,
        ProtocolSnapshot.mca_id == resolved_mca,
        ProtocolSnapshot.content_hash == content_hash,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        if profile:
            profile.active_protocol_snapshot_id = existing.id
            profile.last_compile_status = "compiled"
            profile.last_compile_error = None
            profile.last_compiled_at = profile.last_compiled_at or datetime.utcnow()
            profile.updated_at = datetime.utcnow()
            db.add(profile)
            await db.flush()
        return existing

    snapshot = ProtocolSnapshot(
        id=str(uuid.uuid4()),
        agency_id=agency_id,
        mca_id=resolved_mca,
        compiled_json=compiled_json,
        content_hash=content_hash,
    )
    db.add(snapshot)
    try:
        await db.flush()
    except Exception:
        # Concurrent session starts can race between lookup and insert. Roll back
        # the failed insert and re-read the row that won the unique constraint.
        await db.rollback()
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            if profile:
                profile.active_protocol_snapshot_id = existing.id
                profile.last_compile_status = "compiled"
                profile.last_compile_error = None
                profile.last_compiled_at = profile.last_compiled_at or datetime.utcnow()
                profile.updated_at = datetime.utcnow()
                db.add(profile)
                await db.flush()
            return existing
        raise
    if profile:
        profile.active_protocol_snapshot_id = snapshot.id
        profile.last_compile_status = "compiled"
        profile.last_compile_error = None
        profile.last_compiled_at = datetime.utcnow()
        profile.updated_at = datetime.utcnow()
        db.add(profile)
        await db.flush()
    return snapshot


async def materialize_protocol_profile_snapshot(
    db: AsyncSession,
    *,
    profile: AgencyProtocolProfile,
    mca_id: str | None = None,
) -> ProtocolSnapshot:
    """Compile a profile now and store its active immutable snapshot pointer."""
    profile.last_compile_status = "compiling"
    profile.last_compile_error = None
    db.add(profile)
    await db.flush()
    try:
        snapshot = await create_protocol_snapshot(
            db,
            profile.agency_id,
            mca_id or profile.official_mca_id,
            profile.id,
            False,
        )
    except Exception as exc:
        profile.last_compile_status = "failed"
        profile.last_compile_error = str(exc)[:1000]
        profile.updated_at = datetime.utcnow()
        db.add(profile)
        await db.flush()
        raise
    profile.active_protocol_snapshot_id = snapshot.id
    profile.last_compile_status = "compiled"
    profile.last_compile_error = None
    profile.last_compiled_at = datetime.utcnow()
    profile.updated_at = datetime.utcnow()
    db.add(profile)
    await db.flush()
    return snapshot


async def get_effective_protocol_profile(
    db: AsyncSession,
    *,
    agency_id: str | None,
    mca_id: str | None,
    protocol_profile_id: str | None = None,
) -> AgencyProtocolProfile | None:
    """Return the profile a session should use, creating an agency default if needed."""
    if protocol_profile_id:
        stmt = select(AgencyProtocolProfile).where(
            AgencyProtocolProfile.id == protocol_profile_id,
            AgencyProtocolProfile.is_active == True,
        )
        if agency_id is not None:
            stmt = stmt.where(AgencyProtocolProfile.agency_id == agency_id)
        profile = (await db.execute(stmt)).scalar_one_or_none()
        if not profile:
            raise ValueError("Protocol profile not found or inactive")
        return profile

    if agency_id is None:
        return None

    agency = (await db.execute(select(Agency).where(Agency.id == agency_id))).scalar_one_or_none()
    if not agency:
        return None

    if agency.default_protocol_profile_id:
        stmt = select(AgencyProtocolProfile).where(
            AgencyProtocolProfile.id == agency.default_protocol_profile_id,
            AgencyProtocolProfile.agency_id == agency_id,
            AgencyProtocolProfile.is_active == True,
        )
        profile = (await db.execute(stmt)).scalar_one_or_none()
        if profile:
            return profile

    stmt = select(AgencyProtocolProfile).where(
        AgencyProtocolProfile.agency_id == agency_id,
        AgencyProtocolProfile.is_default == True,
        AgencyProtocolProfile.is_active == True,
    )
    profile = (await db.execute(stmt)).scalar_one_or_none()
    if profile:
        agency.default_protocol_profile_id = profile.id
        db.add(agency)
        await db.flush()
        return profile

    return await create_default_protocol_profile(
        db,
        agency=agency,
        mca_id=mca_id,
        created_by=None,
    )


async def create_default_protocol_profile(
    db: AsyncSession,
    *,
    agency: Agency,
    mca_id: str | None,
    created_by: str | None,
) -> AgencyProtocolProfile:
    """Create the agency's default profile from its configured MCA/base set."""
    resolved_mca = (mca_id or (agency.config or {}).get("mca") or "mi_base").split("/")[0]
    base_protocol_set = _base_protocol_set_for_mca(resolved_mca)
    display_name = f"{base_protocol_set} Default"
    profile = AgencyProtocolProfile(
        id=str(uuid.uuid4()),
        agency_id=agency.id,
        display_name=display_name,
        profile_type="agency_default",
        base_protocol_set=base_protocol_set,
        official_mca_id=resolved_mca,
        is_default=True,
        is_active=True,
        created_by=created_by,
    )
    db.add(profile)
    await db.flush()
    agency.default_protocol_profile_id = profile.id
    db.add(agency)
    await db.flush()
    return profile
