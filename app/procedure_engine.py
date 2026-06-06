"""
Loads procedure/medication JSON files from disk.

Procedure files are medication monographs (dosing, 6 rights, administration steps).
They are separate from protocol files (clinical guidelines) and are referenced by
drug_ref / procedure_ref in scenario popup_config fields.

Reference format: "{base}/{level}/{name}"  e.g. "mi_base/bls/albuterol"

Procedure files live at:  app/procedures/{base}/{level}/{name}.json

Unlike protocols (which live under state directories like MI/), procedure files
are organized by base MCA identifier. MCA-specific scope (e.g. whether epi draw-up
is BLS scope) is determined at runtime by mca_config.json expansions — not by the
procedure file itself. The file describes the drug; the expansion controls access.
"""
import json
from functools import lru_cache
from pathlib import Path

PROCEDURES_DIR = Path(__file__).parent / "protocols"


@lru_cache(maxsize=64)
def load_procedure(ref: str) -> dict:
    """Load a procedure file by slash-separated path."""
    path = PROCEDURES_DIR / f"{ref}.json"
    if not path.exists():
        raise FileNotFoundError(f"Procedure file not found: {path}")
    with open(path, "r") as f:
        return json.load(f)


def list_procedures(mca: str = None, level: str = None) -> list[dict]:
    """List available procedure files, optionally filtered by mca and level."""
    results = []
    for path in sorted(PROCEDURES_DIR.rglob("*.json")):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if mca and data.get("mca") != mca:
                continue
            if level and data.get("level") != level:
                continue
            results.append({
                "id": data.get("id"),
                "name": data.get("name"),
                "type": data.get("type", "procedure"),
                "mca": data.get("mca"),
                "level": data.get("level"),
                "reference": data.get("reference", ""),
            })
        except Exception:
            continue
    return results
