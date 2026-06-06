from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.vitals_engine import calculate_vitals


def _load_scenario(scenario_id: str) -> dict:
    root = Path(__file__).resolve().parents[1]
    matches = list((root / "app/scenarios").rglob(f"{scenario_id}.json"))
    assert matches, f"Scenario not found: {scenario_id}"
    return json.loads(matches[0].read_text())


def test_pediatric_diabetic_oral_glucose_improves_gcs_and_blood_glucose():
    scenario = _load_scenario("peds_diabetic_emergency_01")
    now = datetime.utcnow()
    session = {
        "start_time": now,
        "interventions": [
            {"name": "blood_glucose_check", "applied_at": now},
            {"name": "oral_glucose", "applied_at": now},
        ],
    }

    vitals = calculate_vitals(session, scenario)

    assert vitals["gcs"] == 15
    assert vitals["blood_glucose"] >= 70
    assert "38" not in str(vitals["blood_glucose"])
