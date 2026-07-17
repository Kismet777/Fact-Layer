"""export --outline: lightweight catalog (all slots + one-line snippet, no full value).

The closed-loop base — agent uses outline to know *what exists* cheaply, then
search/get for detail. (Requirements tree §1.4 gap.)
"""

from pathlib import Path

import pytest

from fact_layer.core.exporter import render_export_outline
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.writer import dump_yaml


def _make_slot(value, status="active"):
    return {"value": value, "meta": {
        "source": "human", "confidence": "high", "status": status,
        "updated": "2026-06-09", "verified": "2026-06-09"}}


@pytest.fixture
def facts_dir(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    init_facts_dir(target=project, project_name="p", language="Python 3.12",
                   enabled_extensions=["data-model"], enabled_optional=["decisions"])
    facts = project / ".facts"
    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {
            "language": _make_slot("Python 3.12"),
            "database": _make_slot("PostgreSQL 16"),
            "dropped": _make_slot("old", status="superseded"),
        },
    })
    dump_yaml(facts / "canonical" / "data-model.yaml", {
        "category": "data-model", "tier": "dynamic",
        "slots": {"long-note": _make_slot("HEAD line\n" + "x" * 200 + " TAILTOKEN")},
    })
    dump_yaml(facts / "canonical" / "decisions.yaml", {
        "category": "decisions", "tier": "working",
        "slots": {"dec-001": {"value": {
            "title": "Choose PostgreSQL", "rationale": "mature", "status": "active"},
            "meta": {"source": "human", "confidence": "high", "status": "active",
                     "updated": "2026-06-07", "verified": "2026-06-07"}}},
    })
    return facts


def test_lists_active_slot_refs(facts_dir):
    out = render_export_outline(facts_dir)
    assert "tech-stack.language" in out
    assert "tech-stack.database" in out


def test_excludes_non_active(facts_dir):
    out = render_export_outline(facts_dir)
    assert "tech-stack.dropped" not in out


def test_snippet_is_single_line_and_truncated(facts_dir):
    out = render_export_outline(facts_dir)
    matching = [ln for ln in out.splitlines() if "data-model.long-note" in ln]
    # exactly one physical line carries the slot (multiline value collapsed)
    assert len(matching) == 1
    assert matching[0].rstrip().endswith("…")
    assert len(matching[0]) < 160


def test_no_full_value_dumped(facts_dir):
    # the tail of the long value is truncated away — outline is an index, not a dump
    out = render_export_outline(facts_dir)
    assert "TAILTOKEN" not in out


def test_decision_shown_by_title(facts_dir):
    out = render_export_outline(facts_dir)
    assert "Choose PostgreSQL" in out
    assert "decisions.dec-001" in out


def test_ends_with_watermark(facts_dir):
    out = render_export_outline(facts_dir)
    assert "fl-watermark:" in out.splitlines()[-1]
