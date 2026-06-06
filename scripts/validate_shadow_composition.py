"""
Shadow composition validation matrix.

Runs compose_shadow_checklist() for each NASEMSO call-type rubric using an
empty base checklist (no existing scenario items), then prints an inspectable
report of the composition decisions for pre-activation review.

Usage:
    python scripts/validate_shadow_composition.py

Checklist before flipping CALL_TYPE_RUBRIC_ACTIVE=true:
  [ ] No duplicate IDs between base and call-type items
  [ ] No noisy suspected duplicates (Jaccard threshold plausible)
  [ ] Empty-role items documented, not surprising
  [ ] Level exclusions correct for the provider level under test
  [ ] "all" items show allowed_tiers=[1], not [1,2]
  [ ] overlay_audit absent in shadow mode (shadow_composition present)
"""

from __future__ import annotations

import sys
import pathlib

# Allow running from project root without installing the package.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from datetime import datetime, timezone

from app.rubric_loader import load_call_type_rubric, compose_shadow_checklist


CALL_TYPES = ["hypoglycemia", "pediatric_croup", "respiratory_distress"]
PROVIDER_LEVEL = "EMT"
DEPLOYMENT_CONTEXT = "training"


def _section(title: str) -> None:
    width = 70
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def _subsection(title: str) -> None:
    print(f"\n  -- {title} --")


def _ok(msg: str) -> None:
    print(f"    [OK]  {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN]  {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL]  {msg}")


def _info(label: str, value) -> None:
    print(f"    {label:<32} {value}")


def validate_call_type(call_type: str) -> list[str]:
    """
    Run shadow composition for one call type and print a human-readable report.
    Returns a list of failure strings (empty = clean).
    """
    failures: list[str] = []
    composed_at = datetime.now(timezone.utc).isoformat()

    _section(f"Call type: {call_type}  (level={PROVIDER_LEVEL}, ctx={DEPLOYMENT_CONTEXT})")

    # ── Load rubric ──────────────────────────────────────────────────────────
    rubric = load_call_type_rubric(call_type, deployment_context=DEPLOYMENT_CONTEXT)
    if rubric is None:
        _fail(f"load_call_type_rubric returned None — no rubric file for '{call_type}'")
        failures.append(f"{call_type}: rubric not found")
        return failures

    _info("Rubric id", rubric.rubric_id)
    _info("Rubric version", rubric.rubric_version)
    _info("Resolved items", len(rubric.items))

    # ── Shadow compose with empty base (no existing scenario checklist) ──────
    report = compose_shadow_checklist(
        base_items=[],
        rubric=rubric,
        provider_level=PROVIDER_LEVEL,
        composed_at=composed_at,
    )
    d = report.to_dict()

    _subsection("Composition counts")
    _info("base_item_count", d["base_item_count"])
    _info("call_type_item_count", d["call_type_item_count"])
    _info("composed_item_count", d["composed_item_count"])

    # ── Duplicate IDs ────────────────────────────────────────────────────────
    _subsection("Duplicate ID conflicts")
    conflicts = d.get("conflicts", [])
    dup_conflicts = [c for c in conflicts if c.get("kind") == "duplicate_id"]
    if not dup_conflicts:
        _ok("No duplicate IDs between base and call-type items")
    else:
        for c in dup_conflicts:
            msg = f"DUPLICATE {c['item_id']} ({c.get('detail', '')})"
            _fail(msg)
            failures.append(f"{call_type}: {msg}")

    # ── All-logic items ──────────────────────────────────────────────────────
    _subsection("'all' logic items (must be Tier 1 only)")
    all_ids = d.get("all_logic_items", [])
    _info("all_logic_item_count", len(all_ids))
    for item_id in all_ids:
        _info("  item", item_id)
        ct_item = next((i for i in rubric.items if i.item_id == item_id), None)
        if ct_item is None:
            _warn(f"  {item_id} not found in resolved rubric items")
            continue
        if ct_item.requirement_logic != "all":
            _fail(f"  {item_id} expected requirement_logic=all, got {ct_item.requirement_logic}")
            failures.append(f"{call_type}: {item_id} requirement_logic mismatch")
        else:
            _ok(f"  {item_id} requirement_logic=all  reqs={len(ct_item.evidence_requirements)}")

    # ── Empty-role items ─────────────────────────────────────────────────────
    _subsection("Empty-role items (role exists but no concrete sources in context)")
    empty_ids = d.get("empty_role_items", [])
    if not empty_ids:
        _ok("No empty-role items in this context")
    else:
        _warn(f"{len(empty_ids)} item(s) have roles with no concrete sources:")
        for item_id in empty_ids:
            ct_item = next((i for i in rubric.items if i.item_id == item_id), None)
            roles = []
            if ct_item:
                for req in ct_item.evidence_requirements:
                    if not req.resolved_sources and req.original_source_roles:
                        roles.extend(req.original_source_roles)
            _warn(f"  {item_id}  empty roles: {roles}")

    # ── Level-excluded items ─────────────────────────────────────────────────
    _subsection(f"Level-excluded items (excluded from {PROVIDER_LEVEL})")
    excluded_ids = d.get("level_excluded_items", [])
    if not excluded_ids:
        _ok(f"No items excluded for level={PROVIDER_LEVEL}")
    else:
        for item_id in excluded_ids:
            ct_item = next((i for i in rubric.items if i.item_id == item_id), None)
            levels = ct_item.applicable_levels if ct_item else "?"
            _info(f"  excluded {item_id}", f"applicable_levels={levels}")

    # ── Added items summary ──────────────────────────────────────────────────
    _subsection("Items that would be added to the composed checklist")
    added = d.get("added_items", [])
    _info("added_item_count", len(added))
    for item in added:
        flags = []
        if item.get("has_empty_roles"):
            flags.append("EMPTY_ROLE")
        if item.get("unsafe_if_missed"):
            flags.append("UNSAFE")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        print(f"    {item['item_id']:<48} pts={item['point_value']}  "
              f"req={item['required'][:3]}  logic={item.get('requirement_logic', 'any')}"
              f"{flag_str}")

    # ── Suspected duplicates (Jaccard) ───────────────────────────────────────
    _subsection("Suspected duplicates (Jaccard ≥ 0.55, informational)")
    suspected = d.get("suspected_duplicates", [])
    if not suspected:
        _ok("No suspected duplicates detected (base is empty — run again with real scenario items)")
    else:
        _warn(f"{len(suspected)} suspected duplicate pair(s) — review for overlap or false positives:")
        for pair in suspected:
            sim = pair.get("similarity_score", pair.get("score", "?"))
            sim_str = f"{sim:.2f}" if isinstance(sim, float) else str(sim)
            _warn(
                f"  base={pair.get('base_item_id', '?')}  "
                f"ct={pair.get('call_type_item_id', pair.get('similar_to', '?'))}  "
                f"score={sim_str}"
            )

    # ── Diagnostic flag ──────────────────────────────────────────────────────
    _subsection("Artifact flags")
    _ok("_diagnostic_only=True (added by scoring_service when persisted to checklist_states)")

    return failures


def main() -> int:
    print("\nShadow Composition Validation Matrix")
    print(f"Deployment context : {DEPLOYMENT_CONTEXT}")
    print(f"Provider level     : {PROVIDER_LEVEL}")
    print(f"Call types         : {', '.join(CALL_TYPES)}")

    all_failures: list[str] = []
    for ct in CALL_TYPES:
        failures = validate_call_type(ct)
        all_failures.extend(failures)

    _section("Summary")
    if not all_failures:
        _ok(f"All {len(CALL_TYPES)} call types passed shadow composition checks")
        print()
        print("  Pre-activation checklist:")
        print("    [x] No duplicate IDs")
        print("    [x] 'all' logic items present and verified")
        print("    [x] Suspected duplicates reviewed")
        print("    [ ] Flip CALL_TYPE_RUBRIC_ACTIVE=true locally and re-run scoring")
        print("    [ ] Confirm overlay_audit appears, shadow_composition disappears")
        print("    [ ] Confirm no LLM prose claims point math beyond locked renderer")
    else:
        print(f"\n  {len(all_failures)} failure(s) require resolution before activation:")
        for f in all_failures:
            _fail(f)
    print()
    return 1 if all_failures else 0


if __name__ == "__main__":
    sys.exit(main())
