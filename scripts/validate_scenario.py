#!/usr/bin/env python3
"""
Validate scenario JSON files against the unified checklist schema.

Usage:
    python scripts/validate_scenario.py app/scenarios/pediatric/medical/peds_syncope_01.json
    python scripts/validate_scenario.py app/scenarios/          # validate all .json files

Exit codes:
    0 — all scenarios valid (or no checklist present — checklist is optional in Phase 1)
    1 — one or more validation errors found
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError

from app.checklist import ChecklistItem, CURRENT_SCHEMA_VERSION


# Descriptions containing these patterns are almost certainly abstract clinical
# judgments rather than observable behaviors — flag them.
_ABSTRACT_PATTERNS = [
    "recognized severity",
    "demonstrated situational",
    "showed sound clinical judgment",
    "understood airway",
    "appropriate clinical",
    "sound judgment",
    "good communication",
]


def _is_observable(description: str) -> bool:
    """Return False if the description looks like abstract clinical judgment (§6.3)."""
    lower = description.lower()
    for pattern in _ABSTRACT_PATTERNS:
        if pattern in lower:
            return False
    return True


def validate_scenario(path: Path) -> list[str]:
    """
    Validate one scenario file.  Returns a list of error strings (empty = clean).

    No checklist key → clean; checklist is optional during Phase 1–3 migration.
    """
    errors: list[str] = []

    try:
        with path.open() as f:
            scenario: dict[str, Any] = json.load(f)
    except json.JSONDecodeError as exc:
        return [f"JSON parse error: {exc}"]

    raw_items: list[dict] = scenario.get("checklist", [])
    if not raw_items:
        return []   # no checklist — valid during migration period

    seen_ids: set[str] = set()
    category_max: dict[str, int] = {}

    for idx, raw in enumerate(raw_items):
        label = raw.get("id", f"item[{idx}]")

        # Pydantic schema validation
        try:
            item = ChecklistItem.model_validate(raw)
        except ValidationError as exc:
            for err in exc.errors():
                field = ".".join(str(f) for f in err["loc"])
                errors.append(f"{label}: {field} — {err['msg']}")
            continue

        # Duplicate ID check
        if item.id in seen_ids:
            errors.append(f"{item.id}: duplicate id")
        seen_ids.add(item.id)

        # Observable behavior constraint (§6.3)
        if not _is_observable(item.description):
            errors.append(
                f"{item.id}: description looks like abstract clinical judgment — "
                "must describe an externally verifiable behavior"
            )

        # schema_version currency warning (not a hard error)
        if item.schema_version != CURRENT_SCHEMA_VERSION:
            errors.append(
                f"{item.id}: schema_version is '{item.schema_version}'; "
                f"current is '{CURRENT_SCHEMA_VERSION}' — review for field compatibility"
            )

        # Accumulate category max for sanity check
        category_max[item.category] = category_max.get(item.category, 0) + item.point_value

    # Warn when a category's raw sum looks unreasonable (>200 or zero)
    for category, total in category_max.items():
        if total == 0:
            errors.append(f"category '{category}' has zero total points")
        elif total > 200:
            errors.append(
                f"category '{category}' raw point sum is {total} — "
                "verify point_value values (bonus items can inflate this)"
            )

    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_scenario.py <path|directory> [...]")
        return 1

    targets: list[Path] = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            targets.extend(sorted(p.rglob("*.json")))
        elif p.is_file():
            targets.append(p)
        else:
            print(f"ERROR: path not found: {arg}")
            return 1

    if not targets:
        print("No JSON files found.")
        return 1

    total_files = 0
    files_with_checklist = 0
    total_errors = 0

    for path in targets:
        # Skip venv and __pycache__
        if any(part in path.parts for part in ("venv", "__pycache__", ".git")):
            continue

        total_files += 1
        errors = validate_scenario(path)

        # Only print output for files that have a checklist
        try:
            with path.open() as f:
                data = json.load(f)
            has_checklist = bool(data.get("checklist"))
        except Exception:
            has_checklist = False

        if has_checklist or errors:
            files_with_checklist += 1
            if errors:
                print(f"\nFAIL  {path}")
                for e in errors:
                    print(f"      {e}")
                total_errors += len(errors)
            else:
                item_count = len(data.get("checklist", []))
                print(f"OK    {path}  ({item_count} items)")

    print(f"\n{'='*60}")
    print(f"Scanned {total_files} files, {files_with_checklist} had checklists")
    if total_errors:
        print(f"ERRORS: {total_errors}")
        return 1

    print("All checklists valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
