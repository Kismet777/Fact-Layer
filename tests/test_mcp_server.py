from pathlib import Path

import pytest

from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.writer import dump_yaml
from fact_layer.mcp_server import (
    facts_add,
    facts_check,
    facts_export,
    facts_get,
    facts_impact,
    facts_list,
    facts_status,
)


def _make_slot(value, updated="2026-06-09", verified="2026-06-09", status="active"):
    return {
        "value": value,
        "meta": {
            "source": "human",
            "confidence": "high",
            "status": status,
            "updated": updated,
            "verified": verified,
        },
    }


@pytest.fixture
def facts_dir(tmp_path: Path, monkeypatch) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    init_facts_dir(
        target=project,
        project_name="test-project",
        language="Python 3.12",
        enabled_extensions=["data-model", "testing"],
        enabled_optional=["decisions"],
    )
    facts = project / ".facts"

    dump_yaml(facts / "canonical" / "project-overview.yaml", {
        "category": "project-overview", "tier": "stable",
        "slots": {
            "name": _make_slot("test-project"),
            "purpose": _make_slot("A test project"),
            "stage": _make_slot("dev"),
        },
    })
    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {
            "language": _make_slot("Python 3.12"),
            "database": _make_slot("PostgreSQL 16"),
        },
    })
    dump_yaml(facts / "canonical" / "architecture.yaml", {
        "category": "architecture", "tier": "stable",
        "slots": {"style": _make_slot("monolith")},
    })
    dump_yaml(facts / "canonical" / "conventions.yaml", {
        "category": "conventions", "tier": "stable",
        "slots": {"naming": _make_slot("snake_case")},
    })
    dump_yaml(facts / "canonical" / "work-in-progress.yaml", {
        "category": "work-in-progress", "tier": "working",
        "slots": {"focus": _make_slot("MVP")},
    })
    dump_yaml(facts / "canonical" / "data-model.yaml", {
        "category": "data-model", "tier": "dynamic",
        "slots": {"database-type": _make_slot("PostgreSQL")},
    })
    dump_yaml(facts / "canonical" / "testing.yaml", {
        "category": "testing", "tier": "dynamic",
        "slots": {"framework": _make_slot("pytest")},
    })
    dump_yaml(facts / "canonical" / "decisions.yaml", {
        "category": "decisions", "tier": "working",
        "slots": {
            "dec-001": {
                "value": {
                    "title": "Choose PostgreSQL",
                    "date": "2026-06-07",
                    "status": "active",
                    "affected-slots": ["tech-stack.database", "data-model.database-type"],
                },
                "meta": {
                    "source": "human", "confidence": "high", "status": "active",
                    "updated": "2026-06-07", "verified": "2026-06-07",
                },
            },
        },
    })

    monkeypatch.chdir(project)
    return facts


class TestFactsGet:
    def test_returns_value_and_meta(self, facts_dir):
        result = facts_get(slot="tech-stack.database")
        assert result["slot"] == "tech-stack.database"
        assert result["value"] == "PostgreSQL 16"
        assert result["meta"]["source"] == "human"
        assert result["meta"]["status"] == "active"

    def test_invalid_format_raises(self, facts_dir):
        with pytest.raises(ValueError, match="Invalid slot reference"):
            facts_get(slot="no-dot-here")

    def test_missing_category_raises(self, facts_dir):
        with pytest.raises(ValueError, match="not found"):
            facts_get(slot="nonexistent.slot")

    def test_missing_slot_raises(self, facts_dir):
        with pytest.raises(ValueError, match="not found"):
            facts_get(slot="tech-stack.nonexistent")


class TestFactsAdd:
    def test_creates_new_slot(self, facts_dir):
        result = facts_add(
            category="data-model",
            slot_id="enum-status",
            value={"values": ["open", "closed"]},
            reason="new enum",
        )
        assert result["category"] == "data-model"
        assert result["slot_id"] == "enum-status"
        # New slot is now queryable via facts_get.
        got = facts_get(slot="data-model.enum-status")
        assert got["value"] == {"values": ["open", "closed"]}
        assert got["meta"]["reason"] == "new enum"

    def test_duplicate_slot_raises(self, facts_dir):
        with pytest.raises(KeyError, match="already exists"):
            facts_add(category="tech-stack", slot_id="database", value="MySQL")

    def test_unenabled_category_raises(self, facts_dir):
        with pytest.raises((ValueError, KeyError, FileNotFoundError)):
            facts_add(category="security", slot_id="policy", value="x")


class TestFactsList:
    def test_returns_active_slots(self, facts_dir):
        result = facts_list(category="tech-stack")
        assert len(result) == 2
        slots = {s["slot"] for s in result}
        assert "tech-stack.language" in slots
        assert "tech-stack.database" in slots

    def test_excludes_superseded(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "tech-stack.yaml", {
            "category": "tech-stack", "tier": "stable",
            "slots": {
                "language": _make_slot("Python 3.12"),
                "old-db": _make_slot("MySQL", status="superseded"),
            },
        })
        result = facts_list(category="tech-stack")
        slots = {s["slot"] for s in result}
        assert "tech-stack.old-db" not in slots

    def test_missing_category_raises(self, facts_dir):
        with pytest.raises(ValueError, match="not found"):
            facts_list(category="nonexistent")

    def test_each_slot_has_meta(self, facts_dir):
        result = facts_list(category="tech-stack")
        for s in result:
            assert "meta" in s
            assert "value" in s


class TestFactsCheck:
    def test_clean_project_no_errors(self, facts_dir):
        result = facts_check()
        assert result["has_errors"] is False

    def test_returns_errors_and_warnings(self, facts_dir):
        result = facts_check()
        assert "errors" in result
        assert "warnings" in result
        assert isinstance(result["errors"], list)
        assert isinstance(result["warnings"], list)

    def test_filter_by_category(self, facts_dir):
        result = facts_check(category="tech-stack")
        for issue in result["errors"] + result["warnings"]:
            assert issue["category_name"] == "tech-stack"

    def test_detects_missing_required(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "project-overview.yaml", {
            "category": "project-overview", "tier": "stable",
            "slots": {},
        })
        result = facts_check(category="project-overview")
        assert result["has_errors"] is True


class TestFactsImpact:
    def test_finds_downstream(self, facts_dir):
        result = facts_impact(slot="tech-stack.database")
        assert len(result["targets"]) > 0

    def test_finds_decision_refs(self, facts_dir):
        result = facts_impact(slot="tech-stack.database")
        assert len(result["decisions"]) >= 1

    def test_leaf_slot_no_targets(self, facts_dir):
        result = facts_impact(slot="data-model.database-type")
        assert len(result["targets"]) == 0


class TestFactsStatus:
    def test_returns_categories(self, facts_dir):
        result = facts_status()
        assert len(result["categories"]) > 0
        assert result["total_filled"] > 0
        assert result["total_slots"] > 0

    def test_category_fields(self, facts_dir):
        result = facts_status()
        cat = result["categories"][0]
        assert "name" in cat
        assert "tier" in cat
        assert "filled" in cat
        assert "total" in cat


class TestFactsExport:
    def test_returns_markdown(self, facts_dir):
        result = facts_export()
        assert isinstance(result, str)
        assert "# Project Facts Snapshot" in result

    def test_budget_export(self, facts_dir):
        full = facts_export()
        budgeted = facts_export(budget=100)
        assert len(budgeted) <= len(full)

    def test_budget_export_has_truncation_notice(self, facts_dir):
        result = facts_export(budget=50)
        assert "truncated" in result


class TestNoFactsDir:
    def test_get_raises_without_facts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="No .facts/"):
            facts_get(slot="tech-stack.database")

    def test_list_raises_without_facts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="No .facts/"):
            facts_list(category="tech-stack")

    def test_check_raises_without_facts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="No .facts/"):
            facts_check()

    def test_status_raises_without_facts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="No .facts/"):
            facts_status()
