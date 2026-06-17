#!/usr/bin/env python3
"""Generate a local HTML report for learner-facing FTO feedback.

The report reads completed scenario sessions directly from the configured
DATABASE_URL and renders the stored debrief with the same major learner-facing
sections used in the app: score/status, FTO summary, full debrief, timeline,
rubric detail, scenario transcript, and Lexi/debrief chat turns.

Database configuration:
    Prefer a dedicated read-only/reporting URL when possible. The script checks
    these in order:

    1. --database-url
    2. REPORT_DATABASE_URL
    3. RENDER_DATABASE_URL
    4. DATABASE_URL_EXTERNAL
    5. DATABASE_URL / app settings
    6. REPORT_DB_* or PG* component variables

    For a Render external Postgres URL, either use postgresql+asyncpg://... or
    paste the Render postgresql://... URL and this script will adapt it.

Examples:
    python scripts/fto_feedback_report.py --session-id SESSION_ID
    python scripts/fto_feedback_report.py --scenario-id peds_croup_01 --username jon --limit 5
    python scripts/fto_feedback_report.py --recent --limit 100 --output reports/fto.html
    REPORT_DATABASE_URL='postgresql://...' python scripts/fto_feedback_report.py --recent
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.scenario_engine import load_scenario  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.fto-report", override=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render stored FTO/debrief feedback for specific scenario runs.",
    )
    parser.add_argument(
        "--database-url",
        help="Override DB URL. Also supported via REPORT_DATABASE_URL, RENDER_DATABASE_URL, DATABASE_URL_EXTERNAL, or DATABASE_URL.",
    )
    parser.add_argument("--session-id", action="append", default=[], help="Session id to include. May be repeated.")
    parser.add_argument("--scenario-id", help="Filter by scenario id, e.g. peds_croup_01.")
    parser.add_argument("--scenario-contains", help="Case-insensitive match against scenario id or scenario title.")
    parser.add_argument("--username", help="Filter by exact backend username.")
    parser.add_argument("--user-contains", help="Case-insensitive match against username, first name, last name, or email.")
    parser.add_argument("--user-id", help="Filter by backend users.id.")
    parser.add_argument("--agency-id", help="Filter by agency id.")
    parser.add_argument("--agency-contains", help="Case-insensitive match against agency name or agency file.")
    parser.add_argument("--from-date", help="Only include sessions ending on/after this date/time, e.g. 2026-06-01 or 2026-06-01T08:00.")
    parser.add_argument("--to-date", help="Only include sessions ending before/on this date/time, e.g. 2026-06-13 or 2026-06-13T17:00.")
    parser.add_argument("--min-score", type=int, help="Minimum assessment score percentage.")
    parser.add_argument("--max-score", type=int, help="Maximum assessment score percentage.")
    parser.add_argument("--status", choices=["excellent", "strong", "on_track", "passed", "needs_work", "growth", "critical"], help="Filter by status tone. 'passed' means >=70%% and no critical miss.")
    parser.add_argument("--has-lexi", action="store_true", help="Only include sessions with Lexi/debrief chat messages.")
    parser.add_argument("--has-transcript", action="store_true", help="Only include sessions with scenario transcript messages.")
    parser.add_argument("--contains", help="Case-insensitive text search across debrief, transcript, and Lexi chats.")
    parser.add_argument("--recent", action="store_true", help="Include recent completed sessions matching filters.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum sessions to load into the report. Default: 100.")
    parser.add_argument(
        "--output",
        default="reports/fto_feedback_report.html",
        help="HTML output path. Default: reports/fto_feedback_report.html",
    )
    parser.add_argument("--json", action="store_true", help="Also write a sibling JSON file with raw report data.")
    return parser


def _loads(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _fmt_dt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def _iso_dt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _scenario_title(scenario_id: str) -> str:
    try:
        return str(load_scenario(scenario_id).get("title") or scenario_id)
    except Exception:
        return scenario_id


def _load_scenario_safe(scenario_id: str) -> dict[str, Any]:
    try:
        return dict(load_scenario(scenario_id) or {})
    except Exception:
        return {}


def _scenario_patient_line(scenario: dict[str, Any]) -> str:
    patient = scenario.get("patient") or {}
    parts = [
        patient.get("name"),
        patient.get("age") or patient.get("age_display"),
        patient.get("sex"),
        patient.get("weight_display"),
    ]
    return " · ".join(str(part).strip() for part in parts if str(part or "").strip())


def _intervention_label(scenario: dict[str, Any], name: str) -> str:
    interventions = ((scenario.get("vitals") or {}).get("interventions") or {})
    meta = interventions.get(name) or {}
    return str(meta.get("label") or name or "")


def _normalize_database_url(url: str) -> str:
    value = (url or "").strip()
    if value.startswith("postgres://"):
        value = "postgresql+asyncpg://" + value[len("postgres://"):]
    elif value.startswith("postgresql://"):
        value = "postgresql+asyncpg://" + value[len("postgresql://"):]
    if "sslmode=" in value:
        value = value.replace("sslmode=", "ssl=")
    return value


def _component_database_url() -> str:
    host = os.getenv("REPORT_DB_HOST") or os.getenv("PGHOST") or ""
    name = os.getenv("REPORT_DB_NAME") or os.getenv("PGDATABASE") or ""
    user = os.getenv("REPORT_DB_USER") or os.getenv("PGUSER") or ""
    password = os.getenv("REPORT_DB_PASSWORD") or os.getenv("PGPASSWORD") or ""
    port = os.getenv("REPORT_DB_PORT") or os.getenv("PGPORT") or "5432"
    sslmode = os.getenv("REPORT_DB_SSLMODE") or os.getenv("PGSSLMODE") or "require"
    if not (host and name and user):
        return ""
    auth = quote_plus(user)
    if password:
        auth += f":{quote_plus(password)}"
    query = f"?ssl={quote_plus(sslmode)}" if sslmode else ""
    return f"postgresql+asyncpg://{auth}@{host}:{port}/{quote_plus(name)}{query}"


def _resolve_database_url(args: argparse.Namespace) -> str:
    candidates = [
        args.database_url,
        os.getenv("REPORT_DATABASE_URL"),
        os.getenv("RENDER_DATABASE_URL"),
        os.getenv("DATABASE_URL_EXTERNAL"),
        os.getenv("DATABASE_URL"),
        _component_database_url(),
        getattr(settings, "database_url", ""),
    ]
    for candidate in candidates:
        if candidate:
            return _normalize_database_url(candidate)
    raise SystemExit(
        "No database URL found. Set REPORT_DATABASE_URL to the Render External Database URL "
        "or provide --database-url."
    )


def _redact_database_url(url: str) -> str:
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", url)


def _assessment_max(subscores: dict[str, Any] | None) -> int:
    subscores = subscores or {}
    maxes = subscores.get("_maxes") if isinstance(subscores.get("_maxes"), dict) else {}
    if maxes:
        total = sum(int(maxes.get(key) or 0) for key in (
            "clinical_performance",
            "protocols_treatment",
            "scope_adherence",
            "dmist",
            "professionalism",
        ))
        if total:
            return total
    return 100 if "protocols_treatment" in subscores else 80


def _status_meta(score: int | None, denom: int, critical_failure: dict[str, Any] | None = None) -> dict[str, str]:
    if critical_failure and critical_failure.get("triggered"):
        return {"label": str(critical_failure.get("display_label") or "Critical Misses"), "tone": "critical"}
    if score is None:
        return {"label": "No Score", "tone": "none"}
    pct = round((int(score) / max(denom, 1)) * 100)
    if pct >= 92:
        return {"label": "Excellent Rep", "tone": "excellent"}
    if pct >= 85:
        return {"label": "Strong Rep", "tone": "strong"}
    if pct >= 70:
        return {"label": "On Track", "tone": "on_track"}
    if pct >= 60:
        return {"label": "Needs Work", "tone": "needs_work"}
    return {"label": "Growth Opportunity", "tone": "growth"}


def _score_pct(row: dict[str, Any]) -> int | None:
    score = row.get("assessment_score") if row.get("assessment_score") is not None else row.get("score")
    if score is None:
        return None
    return round((int(score) / max(_assessment_max(row.get("subscores") or {}), 1)) * 100)


def _row_status_tone(row: dict[str, Any]) -> str:
    score = row.get("assessment_score") if row.get("assessment_score") is not None else row.get("score")
    return _status_meta(score, _assessment_max(row.get("subscores") or {}), row.get("critical_failure")).get("tone", "")


def _render_markdown(md: str) -> str:
    """Small renderer for stored debrief markdown; avoids adding a dependency."""
    text_in = _normalize_debrief_markdown_for_report(md)
    if not text_in:
        return "<p>No debrief feedback available.</p>"
    out: list[str] = []
    in_ul = False
    for raw in text_in.splitlines():
        line = raw.strip()
        if not line:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            continue
        header = re.match(r"^(#{1,4})\s+(.+)$", line)
        if header:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            level = min(len(header.group(1)) + 1, 4)
            out.append(f"<h{level}>{html.escape(header.group(2))}</h{level}>")
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", line)
        if bullet:
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{html.escape(bullet.group(1))}</li>")
            continue
        if in_ul:
            out.append("</ul>")
            in_ul = False
        out.append(f"<p>{html.escape(line)}</p>")
    if in_ul:
        out.append("</ul>")
    rendered = "\n".join(out)
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"`(.+?)`", r"<code>\1</code>", rendered)
    return rendered


def _normalize_debrief_markdown_for_report(markdown: str) -> str:
    """Normalize stored debrief markdown before local report rendering.

    Older generated debriefs occasionally packed section headers and dash
    bullets into one paragraph, which made missed items appear under the wrong
    visual section. Keep this report renderer defensive so stored historical
    rows remain readable.
    """
    text = str(markdown or "").replace("\r", "").strip()
    if not text:
        return ""

    headings = [
        r"FTO\s+Summary",
        r"What\s+Went\s+Well",
        r"What\s+Could\s+Be\s+Better",
        r"Protocols?\s*&\s*Treatments?",
        r"Handoff\s*&\s*Communication",
        r"Patient\s+Communication",
        r"Narrative",
        r"Case\s+Study",
        r"Rubric\s+Detail(?:\s+—[^\n]*)?",
    ]
    for title_pattern in headings:
        text = re.sub(
            rf"([^\n])\s+(?:#{{1,3}}\s*)({title_pattern})(?=\s|$)",
            r"\1\n\n## \2",
            text,
            flags=re.I,
        )
        text = re.sub(
            rf"(?im)^[ \t]*(?:#{{1,3}}\s*)?({title_pattern})[ \t]*$",
            r"## \1",
            text,
        )

    normalized_lines: list[str] = []
    active_list_section = ""
    gap_re = re.compile(
        r"\b(not|missed|missing|incomplete|not completed|not assessed|not documented|"
        r"no credit|priority fix|should have|needs?|requires?|must|omitted)\b",
        re.I,
    )
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        section_match = re.match(r"^#{1,3}\s+(What Went Well|What Could Be Better)\b", stripped, re.I)
        if section_match:
            active_list_section = section_match.group(1).lower()
            normalized_lines.append(line)
            continue
        if re.match(r"^#{1,3}\s+", stripped):
            active_list_section = ""
            normalized_lines.append(line)
            continue
        if (
            active_list_section
            and not re.match(r"^[-•*]\s+", stripped)
            and re.search(r"\s-\s", stripped)
        ):
            stripped = re.sub(r"\s+(Why it matters:)", r" - \1", stripped, flags=re.I)
            parts = [
                part.strip()
                for part in re.split(r"\s+-\s+(?=[A-Z0-9])", stripped)
                if part.strip()
            ]
            if len(parts) >= 2:
                moved_to_gaps = active_list_section == "what could be better"
                for part in parts:
                    is_gap = gap_re.search(part) or part.lower().startswith("why it matters:")
                    if active_list_section == "what went well" and not moved_to_gaps and is_gap:
                        normalized_lines.append("")
                        normalized_lines.append("## What Could Be Better")
                        moved_to_gaps = True
                    normalized_lines.append(f"- {part}")
                if moved_to_gaps:
                    active_list_section = "what could be better"
                continue
        normalized_lines.append(line)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(normalized_lines)).strip()


def _clock(entry: dict[str, Any]) -> str:
    if entry.get("pre_start"):
        return "done" if entry.get("status") == "applied" else "not done"
    elapsed = entry.get("elapsed_min")
    if elapsed is None:
        return "missed" if entry.get("status") == "missed" else ""
    try:
        total = max(0, round(float(elapsed) * 60))
    except (TypeError, ValueError):
        return ""
    return f"{total // 60:02d}:{total % 60:02d}"


def _render_timeline(timeline: list[dict[str, Any]]) -> str:
    if not timeline:
        return '<p class="muted">No timeline stored for this run.</p>'
    rows = []
    for item in timeline:
        status = str(item.get("status") or "")
        icon = "✓" if status == "applied" else "i" if status == "informational" else "!" if status == "out_of_order" else "x"
        rows.append(
            f'<div class="timeline-row {html.escape(status)}">'
            f'<span class="tl-icon">{icon}</span>'
            f'<span class="tl-time">{html.escape(_clock(item))}</span>'
            f'<span>{html.escape(str(item.get("action") or ""))}</span>'
            "</div>"
        )
    return "\n".join(rows)


def _render_rubric(rubric: list[dict[str, Any]]) -> str:
    if not rubric:
        return '<p class="muted">No rubric detail stored for this run.</p>'
    groups = []
    for group in rubric:
        items = []
        for item in group.get("items") or []:
            done = bool(item.get("satisfied") or item.get("status") == "satisfied")
            icon = "✓" if done else "x"
            cls = "done" if done else "missed"
            label = item.get("description") or item.get("label") or item.get("item_id") or "Rubric item"
            points = ""
            if item.get("earned_points") is not None or item.get("possible_points") is not None:
                points = f'{item.get("earned_points", 0)}/{item.get("possible_points", item.get("point_value", ""))}'
            items.append(
                f'<div class="rubric-item {cls}"><span>{icon}</span>'
                f'<strong>{html.escape(str(label))}</strong>'
                f'<em>{html.escape(str(points))}</em></div>'
            )
        title = group.get("title") or group.get("category") or "Rubric"
        groups.append(
            f'<section class="rubric-group"><h3>{html.escape(str(title))}</h3>'
            + "\n".join(items)
            + "</section>"
        )
    return "\n".join(groups)


def _subscore_defs(subscores: dict[str, Any]) -> list[tuple[str, str, int]]:
    maxes = subscores.get("_maxes") if isinstance(subscores.get("_maxes"), dict) else {}
    if "protocols_treatment" in subscores:
        return [
            ("clinical_performance", "Clinical Performance", int(maxes.get("clinical_performance") or 50)),
            ("protocols_treatment", "Protocols & Treatment", int(maxes.get("protocols_treatment") or 30)),
            ("scope_adherence", "Scope Adherence", int(maxes.get("scope_adherence") or 20)),
            ("dmist", "DMIST Quality", int(maxes.get("dmist") or 10)),
            ("professionalism", "Professionalism", int(maxes.get("professionalism") or 10)),
        ]
    return [
        ("clinical_performance", "Clinical Performance", int(maxes.get("clinical_performance") or 40)),
        ("scope_adherence", "Scope Adherence", int(maxes.get("scope_adherence") or 20)),
        ("dmist", "DMIST Quality", int(maxes.get("dmist") or 10)),
        ("professionalism", "Professionalism", int(maxes.get("professionalism") or 10)),
    ]


def _render_subscores(subscores: dict[str, Any]) -> str:
    if not subscores:
        return '<p class="muted">No subscore breakdown stored.</p>'
    rows = []
    for key, label, max_score in _subscore_defs(subscores):
        if key not in subscores:
            continue
        value = int(subscores.get(key) or 0)
        pct = round((value / max(max_score, 1)) * 100)
        rows.append(
            f'<div class="score-row"><span>{html.escape(label)}</span>'
            f'<div class="bar"><i style="width:{pct}%"></i></div>'
            f'<b>{value}/{max_score}</b></div>'
        )
    if "narrative" in subscores:
        value = int(subscores.get("narrative") or 0)
        rows.append(
            f'<div class="score-row bonus"><span>Narrative Bonus</span>'
            f'<div class="bar"><i style="width:{round((value / 20) * 100)}%"></i></div>'
            f'<b>{value}/20</b></div>'
        )
    return "\n".join(rows)


_REPORT_PROF_GREETING_RE = re.compile(r"\b(hi|hello|hey|good\s+(morning|afternoon|evening)|my\s+name\s+is|i('?m| am)\s+\w+)\b", re.I)
_REPORT_PROF_AGENCY_RE = re.compile(
    r"\b(with|from)\s+(the\s+)?(?:\w+\s+){0,4}(fire|ems|ambulance|rescue|department|medic)\b"
    r"|\b(i'?m|i am)\s+(?:an?\s+)?(firefighter|emt|emr|paramedic|medic|first.?responder)\b",
    re.I,
)
_REPORT_PROF_ACTION_RE = re.compile(
    r"\b("
    r"i('| a)?m\s+(?:just\s+)?going to|we('?re| are)\s+(?:just\s+)?going to|"
    r"let me|i need to|we need to|i('| a)?m\s+checking|we('?re| are)\s+checking|"
    r"i('| a)?m\s+getting|we('?re| are)\s+getting|"
    r"(?:roll|turn|place|put|position|keep)\s+(?:her|him|them|the\s+(?:baby|child|infant|patient))?.{0,30}\b(?:side|recovery\s+position)|"
    r"protect\s+(?:her|him|their|the\s+(?:baby|child|infant|patient))?.{0,30}\b(?:airway|injur(?:y|ies)|safe|safety)"
    r")\b",
    re.I,
)
_REPORT_PROF_CAREGIVER_RE = re.compile(
    r"\b(mom|mother|dad|father|parent|ma['’]?am|sir|what(?:'s| is)\s+going\s+on|what\s+happened|tell\s+me\s+what)\b",
    re.I,
)
_REPORT_PROF_EMPATHY_RE = re.compile(
    r"\b(we('?re| are) here to help|you('?re| are) doing great|i know this is scary|"
    r"we('?ll| will) help|i'?m sorry|i am sorry|it('?s| is) okay|you('?re| are) okay|help her|help him|help you)\b",
    re.I,
)


def _student_transcript_text(row: dict[str, Any]) -> str:
    return "\n".join(
        str(msg.get("content") or "")
        for msg in row.get("transcript") or []
        if str(msg.get("role") or "").lower() in {"user", "student"}
    )


def _professionalism_cues(row: dict[str, Any]) -> list[tuple[str, bool]]:
    text = _student_transcript_text(row)
    if not text.strip():
        return []
    return [
        ("Greeting or self-introduction", bool(_REPORT_PROF_GREETING_RE.search(text))),
        ("Agency or responder-role introduction", bool(_REPORT_PROF_AGENCY_RE.search(text))),
        ("Explained actions or care plan", bool(_REPORT_PROF_ACTION_RE.search(text))),
        ("Addressed caregiver/family", bool(_REPORT_PROF_CAREGIVER_RE.search(text))),
        ("Reassurance or empathy language", bool(_REPORT_PROF_EMPATHY_RE.search(text))),
    ]


def _score_note_rows(row: dict[str, Any]) -> list[str]:
    notes = row.get("score_notes") or {}
    subscores = row.get("subscores") or {}
    labels = {key: label for key, label, _max in _subscore_defs(subscores)}
    if "narrative" in subscores:
        labels["narrative"] = "Narrative Bonus"
    rows = []
    for key, label in labels.items():
        if key not in subscores:
            continue
        max_score = int((subscores.get("_maxes") or {}).get(key) or (20 if key == "narrative" else 10))
        if key in {"clinical_performance", "protocols_treatment", "scope_adherence"}:
            max_score = next((m for k, _label, m in _subscore_defs(subscores) if k == key), max_score)
        value = int(subscores.get(key) or 0)
        if value >= max_score and key not in notes:
            continue
        note = str(notes.get(key) or "").strip()
        if not note:
            note = "No stored score note for this category; use the timeline/rubric rows below for the concrete missed items."
        rows.append(
            '<div class="deduction-row">'
            f'<strong>{html.escape(label)}</strong>'
            f'<span>{html.escape(str(value))}/{html.escape(str(max_score))}</span>'
            f'<p>{html.escape(note)}</p>'
            "</div>"
        )
    return rows


def _missed_timeline_rows(row: dict[str, Any]) -> list[str]:
    rows = []
    for item in row.get("timeline") or []:
        status = str(item.get("status") or "")
        if status not in {"missed", "out_of_order"}:
            continue
        rows.append(
            '<li>'
            f'<strong>{html.escape(status.replace("_", " ").title())}:</strong> '
            f'{html.escape(str(item.get("action") or item.get("item_id") or "Timeline item"))}'
            "</li>"
        )
    return rows


def _missed_rubric_rows(row: dict[str, Any]) -> list[str]:
    rows = []
    for group in row.get("rubric_detail") or []:
        group_title = str(group.get("title") or group.get("category") or "Rubric")
        for item in group.get("items") or []:
            done = bool(item.get("satisfied") or item.get("status") == "satisfied")
            if done:
                continue
            label = item.get("description") or item.get("label") or item.get("item_id") or "Rubric item"
            points = ""
            if item.get("earned_points") is not None or item.get("possible_points") is not None:
                points = f' ({item.get("earned_points", 0)}/{item.get("possible_points", item.get("point_value", ""))})'
            rows.append(
                '<li>'
                f'<strong>{html.escape(group_title)}:</strong> {html.escape(str(label))}{html.escape(points)}'
                "</li>"
            )
    return rows


def _render_professionalism_cues(row: dict[str, Any]) -> str:
    cues = _professionalism_cues(row)
    if not cues:
        return ""
    rows = "\n".join(
        f'<li class="{"cue-yes" if present else "cue-no"}">'
        f'{"✓" if present else "x"} {html.escape(label)}'
        "</li>"
        for label, present in cues
    )
    return (
        '<div class="deduction-subblock">'
        "<h3>Professionalism Cues Detected From Student Chat</h3>"
        f"<ul>{rows}</ul>"
        '<p class="muted">These cues mirror the report-side check used to explain likely professionalism deductions; the stored backend subscore remains authoritative.</p>'
        "</div>"
    )


def _render_missed_points(row: dict[str, Any]) -> str:
    score_notes = _score_note_rows(row)
    timeline = _missed_timeline_rows(row)
    rubric = _missed_rubric_rows(row)
    prof_cues = _render_professionalism_cues(row)

    note_html = (
        "\n".join(score_notes)
        if score_notes
        else '<p class="muted">No category-level score notes were stored for this run.</p>'
    )
    timeline_html = (
        f'<ul class="deduction-list">{"".join(timeline)}</ul>'
        if timeline
        else '<p class="muted">No missed or out-of-order timeline rows were stored.</p>'
    )
    rubric_html = (
        f'<ul class="deduction-list">{"".join(rubric)}</ul>'
        if rubric
        else '<p class="muted">No not-done rubric rows were stored.</p>'
    )
    return (
        '<section class="deduction-section">'
        "<h2>Missed Points & Deduction Reasons</h2>"
        '<div class="deduction-subblock"><h3>Category Notes</h3>'
        f"{note_html}</div>"
        f"{prof_cues}"
        '<div class="deduction-subblock"><h3>Missed Timeline Items</h3>'
        f"{timeline_html}</div>"
        '<div class="deduction-subblock"><h3>Not-Done Rubric Items</h3>'
        f"{rubric_html}</div>"
        "</section>"
    )


def _fto_summary(row: dict[str, Any]) -> str:
    timeline = row["timeline"]
    score = row["assessment_score"] if row["assessment_score"] is not None else row["score"]
    denom = _assessment_max(row["subscores"])
    critical = row["critical_failure"]
    status = _status_meta(score, denom, critical)

    if critical and critical.get("triggered"):
        strength = "A critical miss was identified in this rep."
    elif status["tone"] == "excellent":
        strength = "Excellent clinical judgment and execution."
    elif status["tone"] == "strong":
        strength = "Strong overall scene management."
    elif status["tone"] == "on_track":
        strength = "Solid core performance under pressure."
    elif status["tone"] == "needs_work":
        strength = "You completed the call, but this rep needs more deliberate assessment and handoff work."
    else:
        strength = "You stayed engaged and completed the call workflow."

    missed = next((t for t in timeline if t.get("status") in ("missed", "out_of_order") and t.get("action")), None)
    critical_items = critical.get("items") if isinstance(critical, dict) else None
    if critical_items:
        first = critical_items[0]
        priority = f"Resolve the critical miss first: {first.get('label') or first.get('item_id')}."
    elif missed:
        priority = f"Prioritize: {missed.get('action')}."
    else:
        pct = round((int(score or 0) / max(denom, 1)) * 100) if score is not None else 0
        priority = "Prioritize earlier recognition and treatment sequencing." if pct < 85 else "Prioritize consistency and speed on critical actions."

    if critical and critical.get("triggered"):
        next_rep = "Repeat this scenario and clear the critical miss before focusing on optimization."
    elif status["tone"] in ("excellent", "strong"):
        next_rep = "Run one higher-complexity scenario and keep the same communication discipline."
    else:
        next_rep = "Replay a similar case and focus on faster, protocol-aligned critical interventions."

    return (
        '<section class="fto-summary">'
        "<h2>FTO Summary</h2>"
        f'<p><strong>What went well:</strong> {html.escape(strength)}</p>'
        f'<p><strong>Priority fix:</strong> {html.escape(priority)}</p>'
        f'<p><strong>Next rep:</strong> {html.escape(next_rep)}</p>'
        "</section>"
    )


def _render_messages(title: str, messages: list[dict[str, Any]]) -> str:
    if not messages:
        return f'<section><h2>{html.escape(title)}</h2><p class="muted">No messages stored.</p></section>'
    rows = []
    for msg in messages:
        role = str(msg.get("role") or "")
        mode = msg.get("mode")
        meta = f'{role}{f" / {mode}" if mode else ""} · {_fmt_dt(msg.get("timestamp"))}'
        rows.append(
            '<div class="chat-row">'
            f'<div class="chat-meta">{html.escape(meta)}</div>'
            f'<div>{html.escape(str(msg.get("content") or ""))}</div>'
            "</div>"
        )
    return f"<section><h2>{html.escape(title)}</h2>{''.join(rows)}</section>"


def _render_pcr_items(items: list[dict[str, Any]], *, treatment: bool = False) -> str:
    if not items:
        return '<p class="muted">No entries stored.</p>'
    rows = []
    for item in items:
        if treatment:
            label = str(item.get("label") or "")
            time = _fmt_dt(item.get("time"))
            rows.append(
                '<div class="pcr-note-item">'
                f'<span class="pcr-note-key">Treatment</span>'
                f'<span class="pcr-note-val">✓ {html.escape(label)}</span>'
                f'<span class="pcr-note-time">{html.escape(time)}</span>'
                "</div>"
            )
            continue
        key = str(item.get("key") or "Finding")
        value = str(item.get("value") or "")
        time = _fmt_dt(item.get("time"))
        rows.append(
            '<div class="pcr-note-item">'
            f'<span class="pcr-note-key">{html.escape(key)}</span>'
            f'<span class="pcr-note-val">{html.escape(value)}</span>'
            f'<span class="pcr-note-time">{html.escape(time)}</span>'
            "</div>"
        )
    return "\n".join(rows)


def _render_pcr_notes(notes: dict[str, Any] | None) -> str:
    notes = notes or {}
    blocks = [
        ("Patient", [
            ("Patient ID", notes.get("patientId")),
            ("Chief Complaint", notes.get("complaint")),
            ("Dispatch", notes.get("dispatch")),
            ("Presentation", notes.get("presentation")),
        ]),
    ]
    patient_rows = []
    for key, value in blocks[0][1]:
        if str(value or "").strip():
            patient_rows.append(
                '<div class="pcr-note-item">'
                f'<span class="pcr-note-key">{html.escape(key)}</span>'
                f'<span class="pcr-note-val">{html.escape(str(value))}</span>'
                '<span class="pcr-note-time"></span>'
                "</div>"
            )
    patient_html = "\n".join(patient_rows) if patient_rows else '<p class="muted">No patient header stored.</p>'
    sections = [
        ("Patient / Scene", patient_html),
        ("Exam / OPQRST", _render_pcr_items(notes.get("exam") or [])),
        ("History", _render_pcr_items(notes.get("history") or [])),
        ("Vital Signs", _render_pcr_items(notes.get("vitals") or [])),
        ("Treatments", _render_pcr_items(notes.get("treatments") or [], treatment=True)),
    ]
    return (
        "<section><h2>PCR Notes</h2>"
        + "\n".join(
            f'<div class="pcr-note-block"><h3>{html.escape(title)}</h3>{body}</div>'
            for title, body in sections
        )
        + "</section>"
    )


def _render_submitted_documents(row: dict[str, Any]) -> str:
    dmist = str(row.get("dmist_report") or "").strip()
    narrative = str(row.get("submitted_narrative") or "").strip()
    narrative_attempted = row.get("narrative_attempted")
    narrative_note = "No narrative stored for this run."
    if row.get("narrative_submitted") and narrative_attempted is False:
        narrative_note = "Narrative was skipped for this run."
    dmist_body = (
        f'<pre class="submitted-doc-text">{html.escape(dmist)}</pre>'
        if dmist
        else '<p class="muted">No DMIST handoff stored for this run.</p>'
    )
    narrative_body = (
        f'<pre class="submitted-doc-text">{html.escape(narrative)}</pre>'
        if narrative
        else f'<p class="muted">{html.escape(narrative_note)}</p>'
    )
    return (
        "<section><h2>Submitted DMIST & Narrative</h2>"
        '<div class="submitted-doc-block"><h3>DMIST Handoff</h3>'
        f"{dmist_body}</div>"
        '<div class="submitted-doc-block"><h3>CHART Narrative</h3>'
        f"{narrative_body}</div>"
        "</section>"
    )


def _safe_dom_id(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "record")).strip("-") or "record"


def _json_for_script(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False).replace("</", "<\\/")


def _export_payload(row: dict[str, Any], score_text: str, status_label: str) -> dict[str, Any]:
    return {
        "metadata": {
            "session_id": row.get("session_id"),
            "scenario_id": row.get("scenario_id"),
            "scenario_title": row.get("scenario_title"),
            "student_name": row.get("student_name") or row.get("username"),
            "username": row.get("username"),
            "email": row.get("email"),
            "agency_name": row.get("agency_name"),
            "agency_file": row.get("agency_file"),
            "started_at": _iso_dt(row.get("start_time")),
            "ended_at": _iso_dt(row.get("ended_at")),
            "score": score_text,
            "status": status_label,
        },
        "subscores": row.get("subscores") or {},
        "score_notes": row.get("score_notes") or {},
        "missed_points": {
            "timeline": [
                item for item in (row.get("timeline") or [])
                if str(item.get("status") or "") in {"missed", "out_of_order"}
            ],
            "rubric": [
                {
                    "group": group.get("title") or group.get("category") or "Rubric",
                    "item": item,
                }
                for group in (row.get("rubric_detail") or [])
                for item in (group.get("items") or [])
                if not bool(item.get("satisfied") or item.get("status") == "satisfied")
            ],
            "professionalism_cues": [
                {"label": label, "detected": detected}
                for label, detected in _professionalism_cues(row)
            ],
        },
        "fto_summary": {
            "feedback": row.get("debrief_markdown") or row.get("feedback") or "",
        },
        "pcr_notes": row.get("pcr_notes") or {},
        "submitted_documents": {
            "dmist": row.get("dmist_report") or "",
            "narrative": row.get("submitted_narrative") or "",
            "narrative_submitted": bool(row.get("narrative_submitted")),
            "narrative_attempted": row.get("narrative_attempted"),
        },
        "timeline": row.get("timeline") or [],
        "rubric_detail": row.get("rubric_detail") or [],
        "scenario_transcript": row.get("transcript") or [],
        "lexi_chats": row.get("lexi_messages") or [],
    }


def _render_session(row: dict[str, Any]) -> str:
    score = row["assessment_score"] if row["assessment_score"] is not None else row["score"]
    denom = _assessment_max(row["subscores"])
    status = _status_meta(score, denom, row["critical_failure"])
    score_text = f"{score}/{denom}" if score is not None else "No score"
    title = row.get("scenario_title") or row["scenario_id"]
    feedback = row.get("debrief_markdown") or row.get("feedback") or ""
    search_text = _row_search_text(row)
    record_id = _safe_dom_id(row["session_id"])
    export_json = _json_for_script(_export_payload(row, score_text, status["label"]))
    return f"""
    <article class="session-card"
      id="record-{html.escape(record_id)}"
      data-user="{html.escape(str(row.get("username") or row.get("student_name") or "").lower())}"
      data-scenario="{html.escape(str(row.get("scenario_id") or "").lower())}"
      data-title="{html.escape(str(title).lower())}"
      data-agency="{html.escape(str(row.get("agency_name") or row.get("agency_file") or "").lower())}"
      data-status="{html.escape(status["tone"])}"
      data-ended="{html.escape(_iso_dt(row.get("ended_at")))}"
      data-search="{html.escape(search_text)}">
      <header class="session-head">
        <div>
          <p class="eyebrow">{html.escape(row["scenario_id"])}</p>
          <h1>{html.escape(title)}</h1>
          <p class="muted">{html.escape(row.get("student_name") or row.get("username") or "")} · {_fmt_dt(row.get("ended_at"))} · session {html.escape(row["session_id"])}</p>
          <div class="record-actions">
            <button type="button" data-export-csv="{html.escape(record_id)}">Export CSV</button>
            <button type="button" data-print-record="{html.escape(record_id)}">Print / Save PDF</button>
          </div>
        </div>
        <div class="score-pill {html.escape(status["tone"])}">
          <strong>{html.escape(score_text)}</strong>
          <span>{html.escape(status["label"])}</span>
        </div>
      </header>
      {_fto_summary(row)}
      <section><h2>Score Breakdown</h2>{_render_subscores(row["subscores"])}</section>
      {_render_missed_points(row)}
      {_render_pcr_notes(row.get("pcr_notes"))}
      {_render_submitted_documents(row)}
      <section><h2>Full Debrief</h2><div class="debrief-prose">{_render_markdown(feedback)}</div></section>
      <section><h2>What Happened — Intervention Timeline</h2>{_render_timeline(row["timeline"])}</section>
      <section><h2>Rubric Detail — Done / Not Done</h2>{_render_rubric(row["rubric_detail"])}</section>
      {_render_messages("Scenario Transcript", row["transcript"])}
      {_render_messages("Lexi / Debrief Chats", row["lexi_messages"])}
      <script type="application/json" id="export-{html.escape(record_id)}">{export_json}</script>
    </article>
    """


def _row_search_text(row: dict[str, Any]) -> str:
    parts = [
        row.get("session_id"),
        row.get("scenario_id"),
        row.get("scenario_title"),
        row.get("username"),
        row.get("student_name"),
        row.get("email"),
        row.get("agency_name"),
        row.get("agency_file"),
        row.get("feedback"),
        row.get("debrief_markdown"),
        row.get("dmist_report"),
        row.get("submitted_narrative"),
        json.dumps(row.get("score_notes") or {}, default=str),
        json.dumps(row.get("timeline") or {}, default=str),
        json.dumps(row.get("rubric_detail") or {}, default=str),
        json.dumps(row.get("pcr_notes") or {}, default=str),
    ]
    parts.extend(str(msg.get("content") or "") for msg in row.get("transcript") or [])
    parts.extend(str(msg.get("content") or "") for msg in row.get("lexi_messages") or [])
    return "\n".join(str(part or "") for part in parts).lower()


def _apply_post_filters(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    filtered = rows
    if args.scenario_contains:
        needle = args.scenario_contains.lower()
        filtered = [
            row for row in filtered
            if needle in str(row.get("scenario_id") or "").lower()
            or needle in str(row.get("scenario_title") or "").lower()
        ]
    if args.min_score is not None:
        filtered = [row for row in filtered if (_score_pct(row) is not None and _score_pct(row) >= args.min_score)]
    if args.max_score is not None:
        filtered = [row for row in filtered if (_score_pct(row) is not None and _score_pct(row) <= args.max_score)]
    if args.status:
        if args.status == "passed":
            filtered = [row for row in filtered if (_score_pct(row) is not None and _score_pct(row) >= 70 and _row_status_tone(row) != "critical")]
        else:
            filtered = [row for row in filtered if _row_status_tone(row) == args.status]
    if args.has_lexi:
        filtered = [row for row in filtered if row.get("lexi_messages")]
    if args.has_transcript:
        filtered = [row for row in filtered if row.get("transcript")]
    if args.contains:
        needle = args.contains.lower()
        filtered = [row for row in filtered if needle in _row_search_text(row)]
    return filtered


def _html_doc(rows: list[dict[str, Any]]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = "\n".join(_render_session(row) for row in rows) if rows else '<p class="empty">No matching sessions found.</p>'
    scenario_options = "\n".join(
        f'<option value="{html.escape(str(value).lower())}">{html.escape(str(value))}</option>'
        for value in sorted({row.get("scenario_id") for row in rows if row.get("scenario_id")})
    )
    user_options = "\n".join(
        f'<option value="{html.escape(str(value).lower())}">{html.escape(str(value))}</option>'
        for value in sorted({row.get("username") for row in rows if row.get("username")})
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FTO Feedback Report</title>
<style>
  :root {{ color-scheme: light; --ink:#0f172a; --muted:#64748b; --line:#dbe3ee; --panel:#ffffff; --bg:#eef4fb; --blue:#2563eb; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--ink); }}
  .page-head {{ padding:28px 36px; border-bottom:1px solid var(--line); background:#fff; position:sticky; top:0; z-index:2; }}
  .page-head h1 {{ margin:0; font-size:28px; }}
  .filters {{ margin-top:16px; display:grid; grid-template-columns:2fr repeat(5, minmax(150px, 1fr)); gap:10px; }}
  .filters input, .filters select, .pager button {{ border:1px solid var(--line); border-radius:10px; padding:10px 12px; font:inherit; background:#fff; color:var(--ink); min-width:0; }}
  .filter-count {{ margin-top:10px; font-size:13px; color:var(--muted); }}
  .pager {{ margin-top:12px; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
  .pager button {{ cursor:pointer; font-weight:700; }}
  .pager button:disabled {{ opacity:.45; cursor:not-allowed; }}
  .session-card {{ max-width:1120px; margin:28px auto; background:var(--panel); border:1px solid var(--line); border-radius:18px; box-shadow:0 18px 50px rgba(15,23,42,.08); overflow:hidden; }}
  .session-card.hidden {{ display:none; }}
  .session-head {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-start; padding:28px 32px; border-bottom:1px solid var(--line); }}
  .session-head h1 {{ margin:3px 0 8px; font-size:30px; }}
  .eyebrow {{ margin:0; color:#475569; text-transform:uppercase; letter-spacing:.12em; font-size:12px; font-weight:800; }}
  .muted {{ color:var(--muted); }}
  .record-actions {{ margin-top:14px; display:flex; gap:10px; flex-wrap:wrap; }}
  .record-actions button {{ border:1px solid var(--line); border-radius:10px; background:#f8fafc; color:var(--ink); font:inherit; font-weight:800; padding:9px 12px; cursor:pointer; }}
  .record-actions button:hover {{ border-color:var(--blue); color:var(--blue); }}
  .score-pill {{ min-width:150px; text-align:right; border:1px solid var(--line); border-radius:14px; padding:14px 16px; background:#f8fafc; }}
  .score-pill strong {{ display:block; font-size:26px; }}
  .score-pill span {{ font-weight:800; }}
  .score-pill.excellent span, .score-pill.strong span {{ color:#047857; }}
  .score-pill.on_track span {{ color:#b45309; }}
  .score-pill.needs_work span, .score-pill.growth span, .score-pill.critical span {{ color:#b91c1c; }}
  section {{ padding:24px 32px; border-bottom:1px solid var(--line); }}
  section h2 {{ margin:0 0 14px; font-size:21px; }}
  .fto-summary {{ background:#f8fbff; border-left:5px solid var(--blue); }}
  .fto-summary p {{ margin:8px 0; font-size:15px; }}
  .score-row {{ display:grid; grid-template-columns:190px 1fr 70px; align-items:center; gap:14px; margin:9px 0; }}
  .score-row span {{ font-weight:700; color:#334155; }}
  .score-row.bonus span, .score-row.bonus b {{ color:#7c3aed; }}
  .bar {{ height:8px; background:#dbe3ee; border-radius:999px; overflow:hidden; }}
  .bar i {{ display:block; height:100%; background:var(--blue); }}
  .bonus .bar i {{ background:#8b5cf6; }}
  .deduction-section {{ background:#fffdf7; }}
  .deduction-subblock {{ border:1px solid #f1e2bd; border-radius:12px; padding:14px; margin:12px 0; background:#fffaf0; }}
  .deduction-subblock h3 {{ margin:0 0 10px; font-size:16px; color:#854d0e; }}
  .deduction-row {{ display:grid; grid-template-columns:190px 80px 1fr; gap:12px; align-items:start; border-top:1px solid #f4e8c9; padding:10px 0; }}
  .deduction-row:first-child {{ border-top:0; }}
  .deduction-row strong {{ color:#0f172a; }}
  .deduction-row span {{ font-weight:900; color:#b45309; }}
  .deduction-row p {{ margin:0; line-height:1.45; }}
  .deduction-list {{ margin:0; padding-left:22px; }}
  .deduction-list li {{ margin:7px 0; line-height:1.45; }}
  .cue-yes {{ color:#047857; }}
  .cue-no {{ color:#b91c1c; }}
  .pcr-note-block {{ border:1px solid #e2e8f0; border-radius:12px; padding:14px; margin:12px 0; background:#fbfdff; }}
  .pcr-note-block h3 {{ margin:0 0 10px; font-size:16px; }}
  .pcr-note-item {{ display:grid; grid-template-columns:180px 1fr 150px; gap:12px; padding:7px 0; border-top:1px solid #edf2f7; }}
  .pcr-note-item:first-of-type {{ border-top:0; }}
  .pcr-note-key {{ font-weight:800; color:#334155; }}
  .pcr-note-val {{ color:#0f172a; }}
  .pcr-note-time {{ color:#64748b; font-size:13px; text-align:right; }}
  .submitted-doc-block {{ border:1px solid #e2e8f0; border-radius:12px; padding:14px; margin:12px 0; background:#fbfdff; }}
  .submitted-doc-block h3 {{ margin:0 0 10px; font-size:16px; }}
  .submitted-doc-text {{ white-space:pre-wrap; margin:0; border:1px solid #edf2f7; border-radius:10px; padding:12px; background:#fff; color:#0f172a; font:inherit; line-height:1.5; }}
  .debrief-prose h2, .debrief-prose h3, .debrief-prose h4 {{ margin:20px 0 8px; }}
  .debrief-prose p {{ line-height:1.55; }}
  .timeline-row {{ display:grid; grid-template-columns:28px 62px 1fr; gap:8px; align-items:start; padding:7px 0; border-bottom:1px solid #edf2f7; }}
  .tl-icon {{ font-weight:900; text-align:center; }}
  .tl-time {{ color:#64748b; font-variant-numeric:tabular-nums; }}
  .timeline-row.applied .tl-icon, .rubric-item.done span {{ color:#15803d; }}
  .timeline-row.missed .tl-icon, .rubric-item.missed span {{ color:#dc2626; }}
  .timeline-row.out_of_order .tl-icon {{ color:#d97706; }}
  .rubric-group {{ padding:16px 0; border-bottom:1px solid #edf2f7; }}
  .rubric-group h3 {{ margin:0 0 10px; font-size:17px; }}
  .rubric-item {{ display:grid; grid-template-columns:28px 1fr 70px; gap:8px; padding:6px 0; }}
  .rubric-item em {{ color:#64748b; text-align:right; font-style:normal; }}
  .chat-row {{ border:1px solid #e2e8f0; border-radius:10px; padding:11px 13px; margin:9px 0; background:#f8fafc; white-space:pre-wrap; }}
  .chat-meta {{ color:#64748b; font-size:12px; font-weight:800; margin-bottom:5px; text-transform:uppercase; letter-spacing:.06em; }}
  .empty {{ max-width:900px; margin:40px auto; font-size:18px; }}
  @media (max-width: 900px) {{ .filters {{ grid-template-columns:1fr; }} }}
  @media print {{
    .page-head, .record-actions {{ display:none; }}
    .session-card {{ box-shadow:none; break-inside:avoid; margin:0; max-width:none; border:0; border-radius:0; }}
    body.printing-one .session-card {{ display:none; }}
    body.printing-one .session-card.print-target {{ display:block; }}
  }}
</style>
</head>
<body>
  <div class="page-head">
    <h1>FTO Feedback Report</h1>
    <div class="muted">Generated {html.escape(now)} · {len(rows)} run(s)</div>
    <div class="filters" role="search">
      <input id="filter-text" type="search" placeholder="Search feedback, transcript, Lexi chats..." aria-label="Search report text">
      <select id="filter-user" aria-label="Filter by user"><option value="">All users</option>{user_options}</select>
      <select id="filter-scenario" aria-label="Filter by scenario"><option value="">All scenarios</option>{scenario_options}</select>
      <select id="filter-status" aria-label="Filter by status">
        <option value="">All statuses</option>
        <option value="excellent">Excellent</option>
        <option value="strong">Strong</option>
        <option value="on_track">On Track</option>
        <option value="needs_work">Needs Work</option>
        <option value="growth">Growth Opportunity</option>
        <option value="critical">Critical Misses</option>
      </select>
      <input id="filter-from-dt" type="datetime-local" aria-label="Filter from date and time">
      <input id="filter-to-dt" type="datetime-local" aria-label="Filter to date and time">
    </div>
    <div id="filter-count" class="filter-count">{len(rows)} run(s) visible</div>
    <div class="pager" aria-label="Report pages">
      <button id="page-prev" type="button">Previous</button>
      <span id="page-status" class="muted">Page 1</span>
      <button id="page-next" type="button">Next</button>
    </div>
  </div>
  {body}
<script>
(() => {{
  const PAGE_SIZE = 10;
  const cards = Array.from(document.querySelectorAll(".session-card"));
  const text = document.getElementById("filter-text");
  const user = document.getElementById("filter-user");
  const scenario = document.getElementById("filter-scenario");
  const status = document.getElementById("filter-status");
  const fromDt = document.getElementById("filter-from-dt");
  const toDt = document.getElementById("filter-to-dt");
  const count = document.getElementById("filter-count");
  const prev = document.getElementById("page-prev");
  const next = document.getElementById("page-next");
  const pageStatus = document.getElementById("page-status");
  let page = 1;

  function csvEscape(value) {{
    const raw = value === null || value === undefined ? "" : String(value);
    return `"${{raw.replace(/"/g, '""')}}"`;
  }}

  function addCsvRow(rows, section, item, status, time, points, role, mode, timestamp, content) {{
    rows.push([section, item, status, time, points, role, mode, timestamp, content].map(csvEscape).join(","));
  }}

  function safeFilename(value) {{
    return String(value || "scenario-result").replace(/[^a-z0-9_-]+/gi, "-").replace(/^-+|-+$/g, "").toLowerCase() || "scenario-result";
  }}

  function exportCsv(recordId) {{
    const source = document.getElementById(`export-${{recordId}}`);
    if (!source) return;
    const data = JSON.parse(source.textContent || "{{}}");
    const rows = [["section", "item", "status", "time", "points", "role", "mode", "timestamp", "content"].map(csvEscape).join(",")];
    Object.entries(data.metadata || {{}}).forEach(([key, value]) => {{
      addCsvRow(rows, "metadata", key, "", "", "", "", "", "", value);
    }});
    Object.entries(data.subscores || {{}}).forEach(([key, value]) => {{
      if (key === "_maxes") return;
      const max = data.subscores?._maxes?.[key] ?? "";
      addCsvRow(rows, "score_breakdown", key, "", "", max ? `${{value}}/${{max}}` : value, "", "", "", "");
    }});
    Object.entries(data.score_notes || {{}}).forEach(([key, value]) => {{
      addCsvRow(rows, "score_notes", key, "", "", "", "", "", "", value || "");
    }});
    ((data.missed_points || {{}}).professionalism_cues || []).forEach(item => {{
      addCsvRow(rows, "professionalism_cues", item.label || "", item.detected ? "detected" : "not_detected", "", "", "", "", "", "");
    }});
    const pcr = data.pcr_notes || {{}};
    ["patientId", "complaint", "dispatch", "presentation"].forEach(key => {{
      if (pcr[key]) addCsvRow(rows, "pcr_notes", key, "", "", "", "", "", "", pcr[key]);
    }});
    (pcr.exam || []).forEach(item => {{
      addCsvRow(rows, "pcr_exam", item.key || "", "", item.time || "", "", "", "", "", item.value || "");
    }});
    (pcr.history || []).forEach(item => {{
      addCsvRow(rows, "pcr_history", item.key || "", "", item.time || "", "", "", "", "", item.value || "");
    }});
    (pcr.vitals || []).forEach(item => {{
      addCsvRow(rows, "pcr_vitals", item.key || "", "", item.time || "", "", "", "", "", item.value || "");
    }});
    (pcr.treatments || []).forEach(item => {{
      addCsvRow(rows, "pcr_treatments", item.label || "", "", item.time || "", "", "", "", "", "");
    }});
    const submitted = data.submitted_documents || {{}};
    addCsvRow(rows, "submitted_dmist", "dmist_handoff", "", "", "", "", "", "", submitted.dmist || "");
    addCsvRow(rows, "submitted_narrative", submitted.narrative_attempted === false ? "chart_narrative_skipped" : "chart_narrative", "", "", "", "", "", "", submitted.narrative || "");
    addCsvRow(rows, "fto_feedback", "full_debrief", "", "", "", "", "", "", data.fto_summary?.feedback || "");
    (data.timeline || []).forEach(item => {{
      addCsvRow(rows, "timeline", item.action || item.item_id || "", item.status || "", item.elapsed_min ?? "", "", "", "", "", item.notes || "");
    }});
    ((data.missed_points || {{}}).timeline || []).forEach(item => {{
      addCsvRow(rows, "missed_timeline", item.action || item.item_id || "", item.status || "", item.elapsed_min ?? "", "", "", "", "", item.notes || "");
    }});
    (data.rubric_detail || []).forEach(group => {{
      (group.items || []).forEach(item => {{
        const done = item.satisfied || item.status === "satisfied" ? "done" : "not_done";
        const label = item.description || item.label || item.item_id || "";
        const points = item.earned_points !== undefined || item.possible_points !== undefined
          ? `${{item.earned_points ?? 0}}/${{item.possible_points ?? item.point_value ?? ""}}`
          : "";
        addCsvRow(rows, `rubric:${{group.title || group.category || ""}}`, label, done, "", points, "", "", "", item.notes || "");
      }});
    }});
    ((data.missed_points || {{}}).rubric || []).forEach(entry => {{
      const item = entry.item || {{}};
      const label = item.description || item.label || item.item_id || "";
      const points = item.earned_points !== undefined || item.possible_points !== undefined
        ? `${{item.earned_points ?? 0}}/${{item.possible_points ?? item.point_value ?? ""}}`
        : "";
      addCsvRow(rows, `missed_rubric:${{entry.group || ""}}`, label, "not_done", "", points, "", "", "", item.notes || "");
    }});
    (data.scenario_transcript || []).forEach(msg => {{
      addCsvRow(rows, "scenario_transcript", "", "", "", "", msg.role || "", "", msg.timestamp || "", msg.content || "");
    }});
    (data.lexi_chats || []).forEach(msg => {{
      addCsvRow(rows, "lexi_chats", "", "", "", "", msg.role || "", msg.mode || "", msg.timestamp || "", msg.content || "");
    }});

    const csv = rows.join("\\n");
    const blob = new Blob([csv], {{ type: "text/csv;charset=utf-8" }});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${{safeFilename(data.metadata?.scenario_id)}}-${{safeFilename(data.metadata?.student_name || data.metadata?.username)}}-${{safeFilename(data.metadata?.session_id)}}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }}

  function printRecord(recordId) {{
    const card = document.getElementById(`record-${{recordId}}`);
    if (!card) return;
    document.body.classList.add("printing-one");
    card.classList.add("print-target");
    const cleanup = () => {{
      document.body.classList.remove("printing-one");
      card.classList.remove("print-target");
      window.removeEventListener("afterprint", cleanup);
    }};
    window.addEventListener("afterprint", cleanup);
    window.print();
    setTimeout(cleanup, 1000);
  }}

  function parseLocalDateTime(value) {{
    if (!value) return null;
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }}

  function cardEndedAt(card) {{
    if (!card.dataset.ended) return null;
    const parsed = new Date(card.dataset.ended);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }}

  function matchesFilters(card) {{
    const q = (text?.value || "").trim().toLowerCase();
    const u = user?.value || "";
    const s = scenario?.value || "";
    const st = status?.value || "";
    const from = parseLocalDateTime(fromDt?.value || "");
    const to = parseLocalDateTime(toDt?.value || "");
    const ended = cardEndedAt(card);
    return (
      (!q || (card.dataset.search || "").includes(q)) &&
      (!u || (card.dataset.user || "") === u) &&
      (!s || (card.dataset.scenario || "") === s) &&
      (!st || (card.dataset.status || "") === st) &&
      (!from || (ended && ended >= from)) &&
      (!to || (ended && ended <= to))
    );
  }}

  function applyFilters() {{
    const matches = cards.filter(matchesFilters);
    const pages = Math.max(1, Math.ceil(matches.length / PAGE_SIZE));
    page = Math.min(Math.max(page, 1), pages);
    const start = (page - 1) * PAGE_SIZE;
    const current = new Set(matches.slice(start, start + PAGE_SIZE));
    cards.forEach(card => {{
      card.classList.toggle("hidden", !current.has(card));
    }});
    if (count) count.textContent = `${{matches.length}} of ${{cards.length}} run(s) match filters · showing ${{current.size}} on this page`;
    if (pageStatus) pageStatus.textContent = `Page ${{page}} of ${{pages}}`;
    if (prev) prev.disabled = page <= 1;
    if (next) next.disabled = page >= pages;
  }}
  [text, user, scenario, status, fromDt, toDt].forEach(el => el?.addEventListener("input", () => {{
    page = 1;
    applyFilters();
  }}));
  prev?.addEventListener("click", () => {{
    page -= 1;
    applyFilters();
  }});
  next?.addEventListener("click", () => {{
    page += 1;
    applyFilters();
  }});
  document.addEventListener("click", event => {{
    const exportButton = event.target.closest("[data-export-csv]");
    if (exportButton) {{
      exportCsv(exportButton.dataset.exportCsv);
      return;
    }}
    const printButton = event.target.closest("[data-print-record]");
    if (printButton) {{
      printRecord(printButton.dataset.printRecord);
    }}
  }});
  applyFilters();
}})();
</script>
</body>
</html>
"""


async def _fetch_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    filter_values = [
        args.scenario_id,
        args.scenario_contains,
        args.username,
        args.user_contains,
        args.user_id,
        args.agency_id,
        args.agency_contains,
        args.from_date,
        args.to_date,
        args.min_score,
        args.max_score,
        args.status,
        args.has_lexi,
        args.has_transcript,
        args.contains,
    ]
    if not args.session_id and not args.recent and not any(value is not None and value is not False for value in filter_values):
        raise SystemExit("Pass --session-id, --recent, or at least one filter such as --scenario-id/--username.")

    database_url = _resolve_database_url(args)
    print(f"Using database: {_redact_database_url(database_url)}", file=sys.stderr)
    engine = create_async_engine(database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with async_session() as db:
            clauses = ["s.ended_at IS NOT NULL", "(s.feedback IS NOT NULL OR s.debrief_markdown IS NOT NULL)"]
            fetch_limit = max(1, int(args.limit or 10))
            if not args.session_id and any([
                args.scenario_contains,
                args.min_score is not None,
                args.max_score is not None,
                args.status,
                args.has_lexi,
                args.has_transcript,
                args.contains,
            ]):
                fetch_limit = max(fetch_limit * 10, 100)
            params: dict[str, Any] = {"limit": fetch_limit}
            if args.session_id:
                clauses.append("s.id IN :session_ids")
                params["session_ids"] = args.session_id
            if args.scenario_id:
                clauses.append("s.scenario_id = :scenario_id")
                params["scenario_id"] = args.scenario_id
            if args.scenario_contains:
                clauses.append("s.scenario_id ILIKE :scenario_contains")
                params["scenario_contains"] = f"%{args.scenario_contains}%"
            if args.username:
                clauses.append("u.username = :username")
                params["username"] = args.username
            if args.user_contains:
                clauses.append("(u.username ILIKE :user_contains OR u.first_name ILIKE :user_contains OR u.last_name ILIKE :user_contains OR u.email ILIKE :user_contains)")
                params["user_contains"] = f"%{args.user_contains}%"
            if args.user_id:
                clauses.append("s.user_id = :user_id")
                params["user_id"] = args.user_id
            if args.agency_id:
                clauses.append("s.agency_id = :agency_id")
                params["agency_id"] = args.agency_id
            if args.agency_contains:
                clauses.append("(a.name ILIKE :agency_contains OR s.agency_file ILIKE :agency_contains)")
                params["agency_contains"] = f"%{args.agency_contains}%"
            if args.from_date:
                clauses.append("s.ended_at >= CAST(:from_date AS timestamp)")
                params["from_date"] = args.from_date
            if args.to_date:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.to_date.strip()):
                    clauses.append("s.ended_at < (CAST(:to_date AS date) + INTERVAL '1 day')")
                else:
                    clauses.append("s.ended_at <= CAST(:to_date AS timestamp)")
                params["to_date"] = args.to_date

            stmt = text(f"""
                SELECT
                    s.id AS session_id,
                    s.scenario_id,
                    s.start_time,
                    s.ended_at,
                    s.score,
                    s.assessment_score,
                    s.narrative_score,
                    s.feedback,
                    s.debrief_markdown,
                    s.narrative_data,
                    s.narrative_submitted,
                    s.narrative_attempted,
                    s.dmist_report,
                    s.dmist_submitted,
                    s.score_snapshot,
                    s.checklist_states,
                    s.agency_id,
                    s.agency_file,
                    u.username,
                    u.email,
                    u.first_name,
                    u.last_name,
                    concat_ws(' ', nullif(u.first_name, ''), nullif(u.last_name, '')) AS student_name,
                    a.name AS agency_name
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                LEFT JOIN agencies a ON a.id = s.agency_id
                WHERE {" AND ".join(clauses)}
                ORDER BY s.ended_at DESC
                LIMIT :limit
            """)
            if args.session_id:
                stmt = stmt.bindparams(bindparam("session_ids", expanding=True))
            session_rows = [dict(row) for row in (await db.execute(stmt, params)).mappings().all()]
            session_ids = [row["session_id"] for row in session_rows]
            if not session_ids:
                return []

            msg_stmt = text("""
                SELECT session_id, role, content, timestamp
                FROM chat_messages
                WHERE session_id IN :session_ids
                ORDER BY timestamp, id
            """).bindparams(bindparam("session_ids", expanding=True))
            msg_rows = [dict(row) for row in (await db.execute(msg_stmt, {"session_ids": session_ids})).mappings().all()]

            lexi_stmt = text("""
                SELECT session_id, mode, role, content, timestamp
                FROM lexi_chat_messages
                WHERE session_id IN :session_ids
                ORDER BY timestamp, id
            """).bindparams(bindparam("session_ids", expanding=True))
            lexi_rows = [dict(row) for row in (await db.execute(lexi_stmt, {"session_ids": session_ids})).mappings().all()]

            finding_stmt = text("""
                SELECT session_id, finding_type, key, value, source, captured_at
                FROM session_findings
                WHERE session_id IN :session_ids
                ORDER BY captured_at, id
            """).bindparams(bindparam("session_ids", expanding=True))
            finding_rows = [dict(row) for row in (await db.execute(finding_stmt, {"session_ids": session_ids})).mappings().all()]

            intervention_stmt = text("""
                SELECT session_id, name, applied_at
                FROM interventions
                WHERE session_id IN :session_ids
                ORDER BY applied_at, id
            """).bindparams(bindparam("session_ids", expanding=True))
            intervention_rows = [dict(row) for row in (await db.execute(intervention_stmt, {"session_ids": session_ids})).mappings().all()]
    finally:
        await engine.dispose()

    by_session_messages: dict[str, list[dict[str, Any]]] = {sid: [] for sid in session_ids}
    for row in msg_rows:
        by_session_messages.setdefault(row["session_id"], []).append(row)
    by_session_lexi: dict[str, list[dict[str, Any]]] = {sid: [] for sid in session_ids}
    for row in lexi_rows:
        by_session_lexi.setdefault(row["session_id"], []).append(row)
    by_session_findings: dict[str, list[dict[str, Any]]] = {sid: [] for sid in session_ids}
    for row in finding_rows:
        by_session_findings.setdefault(row["session_id"], []).append(row)
    by_session_interventions: dict[str, list[dict[str, Any]]] = {sid: [] for sid in session_ids}
    for row in intervention_rows:
        by_session_interventions.setdefault(row["session_id"], []).append(row)

    for row in session_rows:
        nd = _loads(row.get("narrative_data"), {})
        score_snapshot = _loads(row.get("score_snapshot"), {})
        scenario = _load_scenario_safe(row["scenario_id"])
        patient = scenario.get("patient") or {}
        by_type: dict[str, list[dict[str, Any]]] = {"exam": [], "history": [], "vital": []}
        for finding in by_session_findings.get(row["session_id"], []):
            finding_type = str(finding.get("finding_type") or "").lower()
            if finding_type not in by_type:
                continue
            by_type[finding_type].append({
                "key": finding.get("key") or "",
                "value": finding.get("value") or "",
                "source": finding.get("source") or "",
                "time": finding.get("captured_at"),
            })
        treatments = [
            {
                "label": _intervention_label(scenario, intervention.get("name") or ""),
                "intervention_id": intervention.get("name") or "",
                "time": intervention.get("applied_at"),
            }
            for intervention in by_session_interventions.get(row["session_id"], [])
        ]
        row["pcr_notes"] = {
            "patientId": _scenario_patient_line(scenario),
            "complaint": patient.get("chief_complaint") or scenario.get("chief_complaint") or "",
            "dispatch": ((scenario.get("dispatch") or {}).get("text") or ""),
            "presentation": patient.get("general_impression") or scenario.get("presentation") or "",
            "exam": by_type["exam"],
            "history": by_type["history"],
            "vitals": by_type["vital"],
            "treatments": treatments,
        }
        row["subscores"] = nd.get("subscores") or score_snapshot.get("subscores") or {}
        row["score_notes"] = nd.get("score_notes") or {}
        row["submitted_narrative"] = str(nd.get("narrative") or "").strip()
        row["timeline"] = nd.get("timeline") or []
        row["rubric_detail"] = nd.get("rubric_detail") or []
        row["critical_failure"] = nd.get("critical_failure") or score_snapshot.get("critical_failure") or None
        row["transcript"] = by_session_messages.get(row["session_id"], [])
        row["lexi_messages"] = by_session_lexi.get(row["session_id"], [])
        row["scenario_title"] = str(scenario.get("title") or _scenario_title(row["scenario_id"]))
    return _apply_post_filters(session_rows, args)[: max(1, int(args.limit or 10))]


async def _main() -> None:
    args = _parser().parse_args()
    rows = await _fetch_rows(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_html_doc(rows), encoding="utf-8")
    print(f"Wrote {output} ({len(rows)} run(s))")
    if args.json:
        json_path = output.with_suffix(".json")
        json_path.write_text(json.dumps(rows, default=str, indent=2), encoding="utf-8")
        print(f"Wrote {json_path}")


if __name__ == "__main__":
    asyncio.run(_main())
