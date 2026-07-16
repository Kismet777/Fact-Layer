"""Tests for fl export --budget token-budgeted export."""

from pathlib import Path

import pytest

from fact_layer.core.exporter import (
    _compute_indegree,
    _estimate_tokens,
    _score_slot,
    build_budgeted_context,
    render_export,
    render_export_budgeted,
)
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.loader import load_dependencies
from fact_layer.core.writer import dump_yaml

from datetime import date, timedelta


def _slot(value, updated="2026-06-09", verified="2026-06-09", reason=None):
    meta = {
        "source": "human", "confidence": "high", "status": "active",
        "updated": updated, "verified": verified,
    }
    if reason:
        meta["reason"] = reason
    return {"value": value, "meta": meta}


@pytest.fixture
def facts_dir(tmp_path: Path) -> Path:
    proj = tmp_path / "budget-proj"
    proj.mkdir()
    init_facts_dir(
        target=proj,
        project_name="budget-proj",
        language="Python 3.12",
        enabled_extensions=["data-model", "testing", "build-deploy"],
        enabled_optional=["decisions"],
    )
    facts = proj / ".facts"

    dump_yaml(facts / "canonical" / "project-overview.yaml", {
        "category": "project-overview", "tier": "stable",
        "slots": {
            "name": _slot("budget-proj"),
            "purpose": _slot("Testing budget export feature"),
            "stage": _slot("active-development"),
        },
    })
    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {
            "language": _slot("Python 3.12"),
            "framework": _slot("FastAPI 0.111"),
            "database": _slot("PostgreSQL 16"),
            "package-manager": _slot("uv"),
            "key-libraries": _slot(["pydantic>=2.0", "sqlalchemy>=2.0", "anthropic"]),
        },
    })
    dump_yaml(facts / "canonical" / "architecture.yaml", {
        "category": "architecture", "tier": "stable",
        "slots": {
            "style": _slot("layered monolith"),
            "layers": _slot(["endpoint", "service", "module", "repository"]),
        },
    })
    dump_yaml(facts / "canonical" / "conventions.yaml", {
        "category": "conventions", "tier": "stable",
        "slots": {
            "naming": _slot("snake_case for functions, PascalCase for classes"),
        },
    })
    dump_yaml(facts / "canonical" / "data-model.yaml", {
        "category": "data-model", "tier": "dynamic",
        "slots": {
            "database-type": _slot("PostgreSQL 16"),
            "orm": _slot("SQLAlchemy 2.0"),
        },
    })
    dump_yaml(facts / "canonical" / "testing.yaml", {
        "category": "testing", "tier": "dynamic",
        "slots": {
            "framework": _slot("pytest"),
            "strategy": _slot("unit + integration"),
        },
    })
    dump_yaml(facts / "canonical" / "build-deploy.yaml", {
        "category": "build-deploy", "tier": "dynamic",
        "slots": {
            "build-tool": _slot("hatch"),
            "docker": _slot("python:3.12-slim"),
            "ci": _slot("GitHub Actions"),
        },
    })
    dump_yaml(facts / "canonical" / "work-in-progress.yaml", {
        "category": "work-in-progress", "tier": "working",
        "slots": {
            "focus": _slot("Testing budget export"),
        },
    })
    dump_yaml(facts / "canonical" / "decisions.yaml", {
        "category": "decisions", "tier": "working",
        "slots": {
            "dec-001": {
                "value": {
                    "title": "Choose PostgreSQL over MySQL",
                    "date": "2026-06-07",
                    "status": "active",
                    "rationale": "Need JSONB support",
                    "affected-slots": ["tech-stack.database", "data-model.database-type"],
                },
                "meta": {
                    "source": "human", "confidence": "high", "status": "active",
                    "updated": "2026-06-07", "verified": "2026-06-07",
                },
            },
        },
    })

    return facts


class TestEstimateTokens:
    def test_basic(self):
        assert _estimate_tokens("hello world") >= 1

    def test_empty(self):
        assert _estimate_tokens("") == 1

    def test_longer(self):
        text = "a" * 400
        assert _estimate_tokens(text) == 100


class TestComputeIndegree:
    def test_from_real_graph(self, facts_dir):
        graph = load_dependencies(facts_dir)
        indegree = _compute_indegree(graph)
        assert isinstance(indegree, dict)
        assert indegree.get("data-model.database-type", 0) >= 1


class TestScoreSlot:
    def test_stable_required_high_indegree(self):
        indegree = {"tech-stack.language": 3}
        score = _score_slot(
            "tech-stack.language", "stable", True,
            date(2026, 6, 9), indegree, date(2026, 6, 10),
        )
        assert score >= 30 + 15 + 30

    def test_working_unrequired_no_deps(self):
        score = _score_slot(
            "work-in-progress.focus", "working", False,
            date(2026, 6, 1), {}, date(2026, 6, 10),
        )
        assert score == 10 + max(0, 10 - 9)


class TestBudgetExport:
    def test_respects_limit(self, facts_dir):
        md = render_export_budgeted(facts_dir, budget_tokens=200)
        actual_tokens = _estimate_tokens(md)
        assert actual_tokens < 300

    def test_large_budget_equals_full(self, facts_dir):
        full_md = render_export(facts_dir)
        budget_md = render_export_budgeted(facts_dir, budget_tokens=100000)
        assert "truncated" not in budget_md
        assert "Project Overview" in budget_md
        assert "Tech Stack" in budget_md

    def test_prioritizes_stable(self, facts_dir):
        md = render_export_budgeted(facts_dir, budget_tokens=300)
        has_stable = "Project Overview" in md or "Tech Stack" in md
        assert has_stable

    def test_adds_truncation_marker(self, facts_dir):
        md = render_export_budgeted(facts_dir, budget_tokens=100)
        assert "truncated" in md

    def test_budgeted_context_returns_omitted_count(self, facts_dir):
        _, omitted = build_budgeted_context(facts_dir, budget_tokens=100)
        assert omitted > 0

    def test_zero_omitted_for_large_budget(self, facts_dir):
        _, omitted = build_budgeted_context(facts_dir, budget_tokens=100000)
        assert omitted == 0


class TestUnderscoreSlotRecency:
    """Regression: budgeted export must score underscore slot_ids by their real
    recency. It used to reverse-engineer slot_id from the display name, turning
    underscores into hyphens, so the lookup failed and updated became None."""

    def _minimal_dir(self, tmp_path: Path) -> Path:
        proj = tmp_path / "us-proj"
        proj.mkdir()
        init_facts_dir(
            target=proj,
            project_name="us",
            language="Python 3.12",
            enabled_extensions=["data-model"],
            enabled_optional=[],
        )
        facts = proj / ".facts"
        dump_yaml(facts / "canonical" / "project-overview.yaml", {
            "category": "project-overview", "tier": "stable",
            "slots": {"name": _slot("p"), "purpose": _slot("q"), "stage": _slot("r")},
        })
        dump_yaml(facts / "canonical" / "tech-stack.yaml", {
            "category": "tech-stack", "tier": "stable",
            "slots": {"language": _slot("Py")},
        })
        dump_yaml(facts / "canonical" / "architecture.yaml", {
            "category": "architecture", "tier": "stable", "slots": {"style": _slot("m")},
        })
        dump_yaml(facts / "canonical" / "conventions.yaml", {
            "category": "conventions", "tier": "stable", "slots": {},
        })
        dump_yaml(facts / "canonical" / "work-in-progress.yaml", {
            "category": "work-in-progress", "tier": "working", "slots": {},
        })
        return facts

    def test_fresh_underscore_beats_stale_hyphen(self, tmp_path: Path):
        facts = self._minimal_dir(tmp_path)
        today = date.today()
        fresh = today.isoformat()
        stale = (today - timedelta(days=5)).isoformat()
        # Two big, equal-size slots in the same category+tier. Only one fits the
        # budget. The fresh one must win on recency (+10 vs +5). With the old bug
        # the underscore slot's updated resolved to None (recency 0) and lost.
        dump_yaml(facts / "canonical" / "data-model.yaml", {
            "category": "data-model", "tier": "dynamic",
            "slots": {
                "database-type": _slot("PG"),
                "alpha_under": _slot("ALPHAMARKER" + "x" * 2000, updated=fresh, verified=fresh),
                "bravo-hyphen": _slot("BRAVOMARKER" + "y" * 2000, updated=stale, verified=stale),
            },
        })
        md = render_export_budgeted(facts, budget_tokens=600)
        assert "ALPHAMARKER" in md
        assert "BRAVOMARKER" not in md
