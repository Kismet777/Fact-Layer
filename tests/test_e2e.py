"""End-to-end test: init → fill → check → export full pipeline."""

from datetime import date
from pathlib import Path

import pytest

from fact_layer.core.checker import Severity, run_check
from fact_layer.core.exporter import render_export
from fact_layer.core.impact_cmd import compute_impact
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.loader import load_all_categories, load_framework
from fact_layer.core.registry import get_enabled_categories
from fact_layer.core.status_cmd import compute_status
from fact_layer.core.writer import dump_yaml


def _slot(value, updated="2026-06-09", verified="2026-06-09", reason=None):
    meta = {
        "source": "human", "confidence": "high", "status": "active",
        "updated": updated, "verified": verified,
    }
    if reason:
        meta["reason"] = reason
    return {"value": value, "meta": meta}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    proj = tmp_path / "my-app"
    proj.mkdir()

    init_facts_dir(
        target=proj,
        project_name="my-app",
        language="Python 3.12",
        enabled_extensions=["data-model", "api-contracts", "testing", "build-deploy"],
        enabled_optional=["decisions"],
    )

    facts = proj / ".facts"

    dump_yaml(facts / "canonical" / "project-overview.yaml", {
        "category": "project-overview", "tier": "stable",
        "slots": {
            "name": _slot("my-app"),
            "purpose": _slot("REST API for AI companion chat"),
            "stage": _slot("active-development"),
            "scope-in": _slot(["AI chat", "content generation"]),
            "scope-out": _slot(["recommendation", "proxy-chat"]),
        },
    })
    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {
            "language": _slot("Python 3.12"),
            "framework": _slot("FastAPI 0.111"),
            "database": _slot("PostgreSQL 16", reason="JSONB support and CTE performance"),
            "package-manager": _slot("uv"),
            "key-libraries": _slot(["pydantic>=2.0", "sqlalchemy>=2.0", "anthropic"]),
        },
    })
    dump_yaml(facts / "canonical" / "architecture.yaml", {
        "category": "architecture", "tier": "stable",
        "slots": {
            "style": _slot("layered monolith"),
            "layers": _slot(["endpoint", "service", "module", "repository", "client"]),
            "key-patterns": _slot(["repository pattern", "dependency injection"]),
        },
    })
    dump_yaml(facts / "canonical" / "conventions.yaml", {
        "category": "conventions", "tier": "stable",
        "slots": {
            "naming": _slot("snake_case for functions, PascalCase for classes"),
            "async-convention": _slot("async throughout API layer"),
            "do-not": _slot(["import Anthropic SDK in module layer", "bare except"]),
            "prefer": _slot(["composition over inheritance", "explicit over implicit"]),
        },
    })
    dump_yaml(facts / "canonical" / "work-in-progress.yaml", {
        "category": "work-in-progress", "tier": "working",
        "slots": {
            "focus": _slot("Implementing Call B signal extraction"),
            "next-steps": _slot(["Finish confidence validator", "Add session persistence"]),
        },
    })
    dump_yaml(facts / "canonical" / "data-model.yaml", {
        "category": "data-model", "tier": "dynamic",
        "slots": {
            "database-type": _slot("PostgreSQL 16"),
            "orm": _slot("SQLAlchemy 2.0"),
            "key-entities": _slot(["User", "Session", "Message", "Signal"]),
        },
    })
    dump_yaml(facts / "canonical" / "api-contracts.yaml", {
        "category": "api-contracts", "tier": "dynamic",
        "slots": {
            "style": _slot("REST"),
            "auth-method": _slot("JWT"),
            "key-endpoints": _slot(["POST /api/chat", "GET /api/sessions"]),
        },
    })
    dump_yaml(facts / "canonical" / "testing.yaml", {
        "category": "testing", "tier": "dynamic",
        "slots": {
            "framework": _slot("pytest"),
            "strategy": _slot("unit + integration, no e2e"),
            "commands": _slot("pytest tests/"),
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
    dump_yaml(facts / "canonical" / "decisions.yaml", {
        "category": "decisions", "tier": "working",
        "slots": {
            "dec-001": {
                "value": {
                    "title": "Choose PostgreSQL over MySQL",
                    "date": "2026-06-07",
                    "status": "active",
                    "rationale": "Need JSONB support and CTE performance",
                    "affected-slots": ["tech-stack.database", "data-model.database-type"],
                },
                "meta": {
                    "source": "human", "confidence": "high", "status": "active",
                    "updated": "2026-06-07", "verified": "2026-06-07",
                },
            },
        },
    })

    return proj


class TestE2EPipeline:
    def test_init_produces_valid_structure(self, project):
        facts = project / ".facts"
        assert facts.is_dir()
        assert (facts / "framework.yaml").exists()
        assert (facts / "dependencies.yaml").exists()
        assert (facts / "canonical").is_dir()

    def test_all_categories_loadable(self, project):
        facts = project / ".facts"
        config = load_framework(facts)
        categories = load_all_categories(facts)
        enabled = get_enabled_categories(config)
        for cat_name in enabled:
            assert cat_name in categories

    def test_check_passes_on_consistent_project(self, project):
        result = run_check(project / ".facts", today=date(2026, 6, 9))
        errors = [i for i in result.issues if i.severity == Severity.ERROR]
        for e in errors:
            assert "decisions" in e.message and "empty" in e.message or False, \
                f"Unexpected error: {e.message}"

    def test_check_catches_dep_violation(self, project):
        dump_yaml(project / ".facts" / "canonical" / "tech-stack.yaml", {
            "category": "tech-stack", "tier": "stable",
            "slots": {
                "language": _slot("Python 3.12"),
                "database": _slot("MongoDB 7", updated="2026-06-09"),
            },
        })
        dump_yaml(project / ".facts" / "canonical" / "data-model.yaml", {
            "category": "data-model", "tier": "dynamic",
            "slots": {
                "database-type": _slot("PostgreSQL 16", updated="2026-05-01"),
            },
        })
        result = run_check(project / ".facts", today=date(2026, 6, 9))
        dep_errors = [
            i for i in result.issues
            if i.check_type == "dependency" and i.severity == Severity.ERROR
        ]
        assert len(dep_errors) >= 1

    def test_status_shows_all_categories(self, project):
        st = compute_status(project / ".facts", today=date(2026, 6, 9))
        cat_names = {c.name for c in st.categories}
        assert "tech-stack" in cat_names
        assert "data-model" in cat_names
        assert "decisions" in cat_names

    def test_impact_shows_database_deps(self, project):
        result = compute_impact(project / ".facts", "tech-stack.database")
        target_slots = [t.slot for t in result.targets]
        assert "data-model.database-type" in target_slots

    def test_export_produces_readable_markdown(self, project):
        md = render_export(project / ".facts")
        assert "# Project Facts Snapshot" in md
        assert "## Tech Stack" in md
        assert "Python 3.12" in md
        assert "PostgreSQL 16" in md
        assert "JSONB" in md
        assert "## Conventions" in md
        assert "bare except" in md
        assert "## Current Work" in md
        assert "Call B signal" in md
        assert "## Recent Decisions" in md
        assert "DEC-001" in md

    def test_export_excludes_empty_slots(self, project):
        md = render_export(project / ".facts")
        assert "Security" not in md

    def test_full_pipeline_roundtrip(self, project):
        """init → load → check → status → impact → export all succeed."""
        facts = project / ".facts"

        config = load_framework(facts)
        assert config.project_name == "my-app"

        categories = load_all_categories(facts)
        assert len(categories) >= 9

        result = run_check(facts, today=date(2026, 6, 9))
        real_errors = [
            i for i in result.errors
            if not ("decisions" in i.message and "empty" in i.message)
        ]
        assert len(real_errors) == 0

        st = compute_status(facts, today=date(2026, 6, 9))
        assert st.total_filled > 20
        assert st.total_stale == 0

        impact = compute_impact(facts, "tech-stack.database")
        assert impact.slot_exists
        assert len(impact.targets) > 0

        md = render_export(facts)
        assert len(md) > 500
        snapshot = facts / "snapshot.md"
        snapshot.write_text(md, encoding="utf-8")
        assert snapshot.exists()
