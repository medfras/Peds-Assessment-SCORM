"""Deterministic pediatric length-based tape reference data.

The simulator should not ask an LLM to infer Broselow/length-based color bands
or tape measurements. This module provides a small authoritative default table
and an agency/state override hook for local tape systems.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_TAPE_SYSTEM = {
    "id": "mi_length_based_v1",
    "label": "Michigan length-based tape",
    "source": "application_default",
    "bands": [
        {
            "color": "Grey",
            "age_range": "0-2 months",
            "min_weight_kg": 3,
            "max_weight_kg": 5,
            "weight_kg_range": "3-5 kg",
            "weight_lb_range": "6-12 lb",
        },
        {
            "color": "Pink",
            "age_range": "3-6 months",
            "min_weight_kg": 6,
            "max_weight_kg": 7,
            "weight_kg_range": "6-7 kg",
            "weight_lb_range": "13-16 lb",
        },
        {
            "color": "Red",
            "age_range": "7-10 months",
            "min_weight_kg": 8,
            "max_weight_kg": 9,
            "weight_kg_range": "8-9 kg",
            "weight_lb_range": "17-20 lb",
        },
        {
            "color": "Purple",
            "age_range": "11-18 months",
            "min_weight_kg": 10,
            "max_weight_kg": 11,
            "weight_kg_range": "10-11 kg",
            "weight_lb_range": "21-25 lb",
        },
        {
            "color": "Yellow",
            "age_range": "19-35 months",
            "min_weight_kg": 12,
            "max_weight_kg": 14,
            "weight_kg_range": "12-14 kg",
            "weight_lb_range": "26-31 lb",
        },
        {
            "color": "White",
            "age_range": "3-4 years",
            "min_weight_kg": 15,
            "max_weight_kg": 18,
            "weight_kg_range": "15-18 kg",
            "weight_lb_range": "32-40 lb",
        },
        {
            "color": "Blue",
            "age_range": "5-6 years",
            "min_weight_kg": 19,
            "max_weight_kg": 23,
            "weight_kg_range": "19-23 kg",
            "weight_lb_range": "41-51 lb",
        },
        {
            "color": "Orange",
            "age_range": "7-9 years",
            "min_weight_kg": 24,
            "max_weight_kg": 29,
            "weight_kg_range": "24-29 kg",
            "weight_lb_range": "52-64 lb",
        },
        {
            "color": "Green",
            "age_range": "10-14 years",
            "min_weight_kg": 30,
            "max_weight_kg": 36,
            "weight_kg_range": "30-36 kg",
            "weight_lb_range": "65-79 lb",
        },
        {
            "color": "Black",
            "age_range": ">14 years",
            "min_weight_kg": 36,
            "min_weight_exclusive": True,
            "max_weight_kg": None,
            "weight_kg_range": ">36 kg",
            "weight_lb_range": ">80 lb",
        },
    ],
}


def _clean_bands(raw_bands: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_bands, list):
        return []
    bands: list[dict[str, Any]] = []
    for raw in raw_bands:
        if not isinstance(raw, dict):
            continue
        try:
            min_weight = float(raw["min_weight_kg"])
            max_weight = (
                None
                if raw.get("max_weight_kg") is None
                else float(raw["max_weight_kg"])
            )
        except (KeyError, TypeError, ValueError):
            continue
        if min_weight <= 0 or (max_weight is not None and max_weight < min_weight):
            continue
        band = dict(raw)
        band["min_weight_kg"] = min_weight
        band["max_weight_kg"] = max_weight
        band["color"] = str(band.get("color") or "").strip() or "Unknown"
        if not band.get("weight_kg_range"):
            band["weight_kg_range"] = (
                f">{min_weight:g} kg"
                if max_weight is None
                else f"{min_weight:g}-{max_weight:g} kg"
            )
        bands.append(band)
    return bands


def resolve_tape_system(agency: dict | None = None) -> dict[str, Any]:
    """Return the active pediatric length-based tape system.

    Agency config may provide either:

    - ``pediatric_length_based_tape.bands``: full replacement band table.
    - ``pediatric_length_based_tape.band_overrides``: per-color additive patch.

    This keeps state/local variation data-driven without requiring a schema
    migration or LLM prompt edits.
    """
    system = deepcopy(DEFAULT_TAPE_SYSTEM)
    cfg = (agency or {}).get("pediatric_length_based_tape")
    if not isinstance(cfg, dict):
        return system

    if cfg.get("id"):
        system["id"] = str(cfg["id"])
    if cfg.get("label"):
        system["label"] = str(cfg["label"])
    system["source"] = str(cfg.get("source") or "agency_override")

    replacement_bands = _clean_bands(cfg.get("bands"))
    if replacement_bands:
        system["bands"] = replacement_bands

    overrides = cfg.get("band_overrides")
    if isinstance(overrides, dict):
        for band in system["bands"]:
            patch = overrides.get(str(band.get("color") or "").lower()) or overrides.get(band.get("color"))
            if isinstance(patch, dict):
                band.update(patch)
    return system


def _band_midpoint(band: dict[str, Any]) -> float:
    min_weight = float(band["min_weight_kg"])
    max_weight = band.get("max_weight_kg")
    if max_weight is None:
        return min_weight
    return (min_weight + float(max_weight)) / 2


def band_for_weight(weight_kg: Any, agency: dict | None = None) -> dict[str, Any] | None:
    try:
        weight = float(weight_kg)
    except (TypeError, ValueError):
        return None
    if weight <= 0:
        return None

    system = resolve_tape_system(agency)
    bands = system.get("bands") or []
    for band in bands:
        min_weight = float(band["min_weight_kg"])
        max_weight = band.get("max_weight_kg")
        lower_match = (
            weight > min_weight
            if band.get("min_weight_exclusive")
            else weight >= min_weight
        )
        upper_match = max_weight is None or weight <= float(max_weight)
        if lower_match and upper_match:
            return {
                **band,
                "system_id": system["id"],
                "system_label": system["label"],
                "system_source": system["source"],
            }

    if not bands:
        return None
    nearest = min(
        bands,
        key=lambda band: abs(weight - _band_midpoint(band)),
    )
    return {
        **nearest,
        "system_id": system["id"],
        "system_label": system["label"],
        "system_source": system["source"],
        "estimated_from_nearest_band": True,
    }


def patient_tape_reference(patient: dict, agency: dict | None = None) -> dict[str, Any] | None:
    """Build the deterministic reference block for a scenario patient."""
    if not isinstance(patient, dict):
        return None
    existing = patient.get("length_based_tape")
    if isinstance(existing, dict) and existing.get("color"):
        return existing
    band = band_for_weight(patient.get("weight_kg"), agency)
    if not band:
        return None
    return {
        "system_id": band.get("system_id"),
        "system_label": band.get("system_label"),
        "system_source": band.get("system_source"),
        "color": band.get("color"),
        "age_hint": band.get("age_hint"),
        "age_range": band.get("age_range"),
        "weight_kg_range": band.get("weight_kg_range"),
        "weight_lb_range": band.get("weight_lb_range"),
        "length_cm_range": band.get("length_cm_range"),
        "patient_weight_kg": patient.get("weight_kg"),
        "patient_weight_display": patient.get("weight_display"),
        "estimated_from_nearest_band": bool(band.get("estimated_from_nearest_band")),
    }


def tape_reference_sentence(patient: dict, agency: dict | None = None) -> str:
    ref = patient_tape_reference(patient, agency)
    if not ref:
        return ""
    weight_range = str(ref["weight_kg_range"])
    if ref.get("weight_lb_range"):
        weight_range = f"{weight_range} ({ref['weight_lb_range']})"
    parts = [
        f"{ref['system_label']}: {ref['color']} zone",
        f"estimated weight range {weight_range}",
    ]
    if ref.get("length_cm_range"):
        parts.append(f"length range {ref['length_cm_range']}")
    if ref.get("age_range"):
        parts.append(f"age range {ref['age_range']}")
    return "; ".join(parts) + "."
