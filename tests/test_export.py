from datetime import date
from pathlib import Path

import pytest

from fact_layer.core.exporter import build_export_context, render_export
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.writer import dump_yaml


@pytest.fixture
def populated_facts(tmp_path: Path) -> Path:
    """Create a .facts/ directory with some filled-in data."""
    project = tmp_path / "proj"
    project.mkdir()
    init_facts_dir(
        target=project,
        project_name="demo-app",
        language="Python 3.12",
        enabled_extensions=["data-model", "testing"],
        enabled_optional=["decisions"],
    )
    facts_dir = project / ".facts"

    dump_yaml(
        facts_dir / "canonical" / "tech-stack.yaml",
        {
            "category": "tech-stack",
            "tier": "stable",
            "slots": {
                "language": {
                    "value": "Python 3.12",
                    "meta": {
                        "source": "human",
                        "confidence": "high",
                        "status": "active",
                        "updated": "2026-06-09",
                        "verified": "2026-06-09",
                    },
                },
                "framework": {
                    "value": "FastAPI 0.111",
                    "meta": {
                        "source": "human",
                        "confidence": "high",
                        "status": "active",
                        "updated": "2026-06-09",
                        "verified": "2026-06-09",
                    },
                },
                "database": {
                    "value": "PostgreSQL 16",
                    "meta": {
                        "source": "human",
                        "confidence": "high",
                        "status": "active",
                        "updated": "2026-06-09",
                        "verified": "2026-06-09",
                        "reason": "需要 JSONB 支持和 CTE 性能",
                    },
                },
                "old-orm": {
                    "value": "SQLAlchemy 1.4",
                    "meta": {
                        "source": "human",
                        "confidence": "low",
                        "status": "superseded",
                        "updated": "2026-01-01",
                        "verified": "2026-01-01",
                    },
                },
            },
        },
    )

    dump_yaml(
        facts_dir / "canonical" / "conventions.yaml",
        {
            "category": "conventions",
            "tier": "stable",
            "slots": {
                "do-not": {
                    "value": ["use ORM directly in endpoints", "catch bare exceptions"],
                    "meta": {
                        "source": "human",
                        "confidence": "high",
                        "status": "active",
                        "updated": "2026-06-09",
                        "verified": "2026-06-09",
                    },
                },
                "prefer": {
                    "value": ["async throughout", "composition over inheritance"],
                    "meta": {
                        "source": "human",
                        "confidence": "high",
                        "status": "active",
                        "updated": "2026-06-09",
                        "verified": "2026-06-09",
                    },
                },
            },
        },
    )

    dump_yaml(
        facts_dir / "canonical" / "decisions.yaml",
        {
            "category": "decisions",
            "tier": "working",
            "slots": {
                "dec-001": {
                    "value": {
                        "title": "选择 PostgreSQL 而非 MySQL",
                        "date": "2026-06-07",
                        "status": "active",
                        "rationale": "需要 JSONB 和 CTE",
                    },
                    "meta": {
                        "source": "human",
                        "confidence": "high",
                        "status": "active",
                        "updated": "2026-06-07",
                        "verified": "2026-06-07",
                    },
                },
            },
        },
    )

    return facts_dir


@pytest.fixture
def empty_facts(tmp_path: Path) -> Path:
    project = tmp_path / "empty"
    project.mkdir()
    init_facts_dir(
        target=project,
        project_name="empty-project",
        language="Go",
        enabled_extensions=[],
        enabled_optional=[],
    )
    return project / ".facts"


class TestBuildContext:
    def test_has_sections(self, populated_facts):
        ctx = build_export_context(populated_facts)
        assert len(ctx["sections"]) > 0
        assert ctx["project_name"] == "demo-app"
        assert "generated_at" in ctx

    def test_active_slots_only(self, populated_facts):
        ctx = build_export_context(populated_facts)
        tech_section = next(s for s in ctx["sections"] if s["category"] == "tech-stack")
        slot_names = [s["name"] for s in tech_section["slots"]]
        assert "Language" in slot_names
        assert "Database" in slot_names
        assert "Old Orm" not in slot_names

    def test_reason_included(self, populated_facts):
        ctx = build_export_context(populated_facts)
        tech_section = next(s for s in ctx["sections"] if s["category"] == "tech-stack")
        db_slot = next(s for s in tech_section["slots"] if s["name"] == "Database")
        assert db_slot["reason"] == "需要 JSONB 支持和 CTE 性能"

    def test_decisions_extracted(self, populated_facts):
        ctx = build_export_context(populated_facts)
        dec_section = next(s for s in ctx["sections"] if s["category"] == "decisions")
        assert dec_section["is_decisions"] is True
        assert len(dec_section["decisions"]) == 1
        assert dec_section["decisions"][0]["title"] == "选择 PostgreSQL 而非 MySQL"

    def test_empty_categories_skipped(self, empty_facts):
        ctx = build_export_context(empty_facts)
        categories = [s["category"] for s in ctx["sections"]]
        assert "data-model" not in categories
        assert "testing" not in categories

    def test_list_slots(self, populated_facts):
        ctx = build_export_context(populated_facts)
        conv_section = next(s for s in ctx["sections"] if s["category"] == "conventions")
        do_not = next(s for s in conv_section["slots"] if s["name"] == "Do Not")
        assert do_not["is_list"] is True
        assert "use ORM directly in endpoints" in do_not["value"]


class TestRenderExport:
    def test_renders_markdown(self, populated_facts):
        md = render_export(populated_facts)
        assert "# Project Facts Snapshot" in md
        assert "Generated:" in md

    def test_contains_tech_stack(self, populated_facts):
        md = render_export(populated_facts)
        assert "## Tech Stack" in md
        assert "Python 3.12" in md
        assert "PostgreSQL 16" in md
        assert "JSONB" in md

    def test_superseded_not_in_output(self, populated_facts):
        md = render_export(populated_facts)
        assert "SQLAlchemy 1.4" not in md
        assert "Old Orm" not in md

    def test_decisions_in_output(self, populated_facts):
        md = render_export(populated_facts)
        assert "## Recent Decisions" in md
        assert "DEC-001" in md
        assert "PostgreSQL" in md

    def test_conventions_lists(self, populated_facts):
        md = render_export(populated_facts)
        assert "## Conventions" in md
        assert "- use ORM directly in endpoints" in md

    def test_empty_project_still_renders(self, empty_facts):
        md = render_export(empty_facts)
        assert "# Project Facts Snapshot" in md


class TestEnabledCategoryCoverage:
    """FL-020: export must cover every enabled category, not just a hardcoded list."""

    def _populate(self, tmp_path: Path, extension: str, canonical: dict) -> Path:
        project = tmp_path / f"proj-{extension}"
        project.mkdir()
        init_facts_dir(
            target=project,
            project_name="demo",
            language="Python",
            enabled_extensions=[extension],
            enabled_optional=[],
        )
        facts_dir = project / ".facts"
        dump_yaml(facts_dir / "canonical" / f"{extension}.yaml", canonical)
        return facts_dir

    def test_custom_extension_exported(self, tmp_path):
        """The reported bug: a project-defined custom extension (e.g. user-profile,
        which ships no package template and is absent from CATEGORY_ORDER) was
        enabled + populated but silently dropped from export.

        Reproduce faithfully: register the custom extension in framework.yaml, then
        assert it appears with a fallback title derived from the category name.
        """
        from fact_layer.core.loader import _load_yaml

        project = tmp_path / "proj-custom"
        project.mkdir()
        init_facts_dir(
            target=project,
            project_name="demo",
            language="Python",
            enabled_extensions=[],
            enabled_optional=[],
        )
        facts_dir = project / ".facts"

        framework = _load_yaml(facts_dir / "framework.yaml")
        framework["extensions"]["available"]["user-profile"] = {
            "file": "user-profile.yaml",
            "tier": "dynamic",
            "required_slots": [],
        }
        framework["extensions"]["enabled"] = ["user-profile"]
        dump_yaml(facts_dir / "framework.yaml", framework)

        dump_yaml(
            facts_dir / "canonical" / "user-profile.yaml",
            {
                "category": "user-profile",
                "tier": "dynamic",
                "slots": {
                    "derived-scores": {
                        "value": ["willingness_score", "contactability_score"],
                        "meta": {
                            "source": "human",
                            "confidence": "high",
                            "status": "active",
                            "updated": "2026-06-09",
                            "verified": "2026-06-09",
                        },
                    },
                },
            },
        )

        ctx = build_export_context(facts_dir)
        assert "user-profile" in {s["category"] for s in ctx["sections"]}
        md = render_export(facts_dir)
        assert "## User Profile" in md  # fallback title from _slot_display_name
        assert "willingness_score" in md

    def test_category_absent_from_order_still_exported(self, tmp_path, monkeypatch):
        """Root cause: iteration is over enabled categories, not CATEGORY_ORDER.

        Removing a category from CATEGORY_ORDER must not drop it from the export.
        """
        from fact_layer.core import exporter

        facts_dir = self._populate(
            tmp_path,
            "data-model",
            {
                "category": "data-model",
                "tier": "dynamic",
                "slots": {
                    "database-type": {
                        "value": "MySQL 8",
                        "meta": {
                            "source": "human",
                            "confidence": "high",
                            "status": "active",
                            "updated": "2026-06-09",
                            "verified": "2026-06-09",
                        },
                    },
                },
            },
        )
        monkeypatch.setattr(
            exporter,
            "CATEGORY_ORDER",
            [c for c in exporter.CATEGORY_ORDER if c != "data-model"],
        )
        ctx = build_export_context(facts_dir)
        assert "data-model" in {s["category"] for s in ctx["sections"]}
