from pathlib import Path


def test_history_finding_upsert_uses_literal_partial_index_predicate():
    """Postgres partial-index ON CONFLICT cannot use a bound predicate value."""
    src = Path("app/main.py").read_text(encoding="utf-8")
    record_finding = src[src.index("async def record_finding"):src.index("# ── Session events")]

    assert 'index_where=text("finding_type = \'history\'")' in record_finding
    assert 'index_where=SessionFinding.finding_type == "history"' not in record_finding
