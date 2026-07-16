"""Delta / watermark export (kills repeated full-export context pollution).

Plan A: stateless watermark token = "<max_updated_date>:<content_hash8>".
- hash detects "did anything change at all" (robust, no date granularity issue);
- date drives the delta (coarse but never misses; may re-include same-date items).
"""

from pathlib import Path

import pytest

from fact_layer.core.editor import set_slot
from fact_layer.core.exporter import (
    compute_watermark,
    render_export,
    render_export_delta,
)
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.writer import dump_yaml


def _slot(value, updated="2026-01-01", status="active"):
    return {
        "value": value,
        "meta": {
            "source": "human",
            "confidence": "high",
            "status": status,
            "updated": updated,
            "verified": updated,
        },
    }


@pytest.fixture
def facts(tmp_path: Path) -> Path:
    """.facts/ with MIXED updated dates so delta reduction is observable.

    tech-stack: language / database  → 2026-01-01 (old)
    data-model: entity-x             → 2026-06-01 (newer)  → max date = 2026-06-01
    """
    project = tmp_path / "proj"
    project.mkdir()
    init_facts_dir(
        target=project,
        project_name="demo",
        language="Python 3.12",
        enabled_extensions=["data-model"],
        enabled_optional=[],
    )
    facts_dir = project / ".facts"
    dump_yaml(facts_dir / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {
            "language": _slot("Python 3.12", updated="2026-01-01"),
            "database": _slot("PostgreSQL 16", updated="2026-01-01"),
        },
    })
    dump_yaml(facts_dir / "canonical" / "data-model.yaml", {
        "category": "data-model", "tier": "dynamic",
        "slots": {
            "entity-x": _slot("OLDVAL-DM", updated="2026-06-01"),
        },
    })
    return facts_dir


def _watermark_in(md: str) -> str:
    for line in md.splitlines():
        if line.startswith("fl-watermark:"):
            return line.split("fl-watermark:", 1)[1].strip()
    raise AssertionError(f"no fl-watermark line in output:\n{md}")


class TestWatermark:
    def test_full_export_emits_watermark(self, facts):
        md = render_export(facts)
        assert "fl-watermark:" in md
        token = _watermark_in(md)
        assert ":" in token  # date:hash

    def test_watermark_deterministic_when_unchanged(self, facts):
        assert compute_watermark(facts) == compute_watermark(facts)

    def test_watermark_changes_when_value_changes(self, facts):
        before = compute_watermark(facts)
        set_slot(facts, "tech-stack.language", "Rust 1.80")
        assert compute_watermark(facts) != before


class TestDelta:
    def test_reexport_unchanged_reports_no_change(self, facts):
        token = compute_watermark(facts)
        out = render_export_delta(facts, token)
        assert "No fact changes" in out
        # must NOT re-dump the full body
        assert "Python 3.12" not in out
        assert "PostgreSQL 16" not in out
        # still hands back a watermark to reuse
        assert "fl-watermark:" in out

    def test_delta_after_change_includes_changed_slot(self, facts):
        token0 = compute_watermark(facts)
        set_slot(facts, "tech-stack.language", "NEWVAL-PY")
        out = render_export_delta(facts, token0)
        assert "No fact changes" not in out
        assert "NEWVAL-PY" in out

    def test_delta_excludes_older_unchanged_slots(self, facts):
        # token0 date = 2026-06-01 (max). Edit language (→ today).
        token0 = compute_watermark(facts)
        set_slot(facts, "tech-stack.language", "NEWVAL-PY")
        out = render_export_delta(facts, token0)
        # database (2026-01-01, unchanged, older than since-date) must be omitted
        assert "PostgreSQL 16" not in out
        # the changed slot is present
        assert "NEWVAL-PY" in out

    def test_delta_emits_updated_watermark(self, facts):
        token0 = compute_watermark(facts)
        set_slot(facts, "tech-stack.language", "NEWVAL-PY")
        out = render_export_delta(facts, token0)
        assert _watermark_in(out) != token0

    def test_invalid_token_falls_back_to_full(self, facts):
        out = render_export_delta(facts, "not-a-valid-token")
        assert "Python 3.12" in out
        assert "PostgreSQL 16" in out


class TestMcpSinceParam:
    def test_facts_export_since_roundtrip(self, facts, monkeypatch):
        from fact_layer.mcp_server import facts_export

        monkeypatch.chdir(facts.parent)
        full = facts_export()
        assert "fl-watermark:" in full
        token = _watermark_in(full)
        delta = facts_export(since=token)
        assert "No fact changes" in delta
