"""Tests for fl set / fl add / fl deprecate / fl set --batch write commands."""

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from fact_layer.core.editor import (
    AddResult,
    BatchSetItem,
    BatchSetResult,
    DeprecateResult,
    SetResult,
    add_slot,
    deprecate_slot,
    load_yaml_roundtrip,
    parse_value,
    set_batch,
    set_slot,
)
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.writer import dump_yaml


def _slot(value, updated="2026-06-09", verified="2026-06-09", status="active", reason=None):
    meta = {
        "source": "human",
        "confidence": "high",
        "status": status,
        "updated": updated,
        "verified": verified,
    }
    if reason:
        meta["reason"] = reason
    return {"value": value, "meta": meta}


@pytest.fixture
def facts_dir(tmp_path: Path) -> Path:
    proj = tmp_path / "test-proj"
    proj.mkdir()
    init_facts_dir(
        target=proj,
        project_name="test-proj",
        language="Python 3.12",
        enabled_extensions=["data-model", "build-deploy"],
        enabled_optional=["decisions"],
    )
    facts = proj / ".facts"

    dump_yaml(facts / "canonical" / "project-overview.yaml", {
        "category": "project-overview", "tier": "stable",
        "slots": {
            "name": _slot("test-proj"),
            "purpose": _slot("Testing fact-layer editor"),
            "stage": _slot("active-development"),
        },
    })
    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {
            "language": _slot("Python 3.12"),
            "framework": _slot("FastAPI"),
            "database": _slot("PostgreSQL 16", reason="JSONB support"),
            "key-libraries": _slot(["pydantic>=2.0", "sqlalchemy>=2.0"]),
        },
    })
    dump_yaml(facts / "canonical" / "architecture.yaml", {
        "category": "architecture", "tier": "stable",
        "slots": {
            "style": _slot("layered monolith"),
        },
    })
    dump_yaml(facts / "canonical" / "conventions.yaml", {
        "category": "conventions", "tier": "stable",
        "slots": {
            "naming": _slot("snake_case"),
        },
    })
    dump_yaml(facts / "canonical" / "data-model.yaml", {
        "category": "data-model", "tier": "dynamic",
        "slots": {
            "database-type": _slot("PostgreSQL 16", updated="2026-06-08"),
        },
    })
    dump_yaml(facts / "canonical" / "build-deploy.yaml", {
        "category": "build-deploy", "tier": "dynamic",
        "slots": {
            "build-tool": _slot("hatch"),
            "docker": _slot("python:3.12-slim"),
        },
    })
    dump_yaml(facts / "canonical" / "work-in-progress.yaml", {
        "category": "work-in-progress", "tier": "working",
        "slots": {
            "focus": _slot("Testing editor commands"),
        },
    })

    return facts


class TestParseValue:
    def test_plain_string(self):
        assert parse_value("hello") == "hello"

    def test_json_list(self):
        assert parse_value('["a", "b"]') == ["a", "b"]

    def test_json_dict(self):
        assert parse_value('{"k": "v"}') == {"k": "v"}

    def test_force_json(self):
        assert parse_value('"quoted"', force_json=True) == "quoted"

    def test_invalid_json_bracket_fallback(self):
        assert parse_value("[not json") == "[not json"


class TestSetSlot:
    def test_updates_value_and_meta(self, facts_dir):
        result = set_slot(facts_dir, "tech-stack.database", "PostgreSQL 17")
        assert isinstance(result, SetResult)
        assert result.old_value == "PostgreSQL 16"
        assert result.new_value == "PostgreSQL 17"

        data = load_yaml_roundtrip(facts_dir / "canonical" / "tech-stack.yaml")
        slot = data["slots"]["database"]
        assert slot["value"] == "PostgreSQL 17"
        assert slot["meta"]["source"] == "human"
        assert slot["meta"]["confidence"] == "high"
        assert str(slot["meta"]["updated"]) == date.today().isoformat()

    def test_preserves_other_slots(self, facts_dir):
        set_slot(facts_dir, "tech-stack.database", "MongoDB 7")

        data = load_yaml_roundtrip(facts_dir / "canonical" / "tech-stack.yaml")
        assert data["slots"]["language"]["value"] == "Python 3.12"
        assert data["slots"]["framework"]["value"] == "FastAPI"

    def test_nonexistent_category_errors(self, facts_dir):
        with pytest.raises(ValueError, match="not enabled"):
            set_slot(facts_dir, "nonexistent.slot", "value")

    def test_nonexistent_slot_errors(self, facts_dir):
        with pytest.raises(KeyError, match="not found"):
            set_slot(facts_dir, "tech-stack.nonexistent", "value")

    def test_with_reason(self, facts_dir):
        set_slot(facts_dir, "tech-stack.database", "PostgreSQL 17", reason="LTS upgrade")

        data = load_yaml_roundtrip(facts_dir / "canonical" / "tech-stack.yaml")
        assert data["slots"]["database"]["meta"]["reason"] == "LTS upgrade"

    def test_preserves_existing_reason_when_none(self, facts_dir):
        set_slot(facts_dir, "tech-stack.database", "PostgreSQL 17")

        data = load_yaml_roundtrip(facts_dir / "canonical" / "tech-stack.yaml")
        assert data["slots"]["database"]["meta"]["reason"] == "JSONB support"

    def test_returns_impact(self, facts_dir):
        result = set_slot(facts_dir, "tech-stack.database", "PostgreSQL 17")
        assert result.impact is not None
        target_slots = [t.slot for t in result.impact.targets]
        assert "data-model.database-type" in target_slots

    def test_list_value(self, facts_dir):
        new_libs = ["pydantic>=2.0", "sqlalchemy>=2.0", "anthropic>=0.30"]
        result = set_slot(facts_dir, "tech-stack.key-libraries", new_libs)
        assert result.new_value == new_libs

        data = load_yaml_roundtrip(facts_dir / "canonical" / "tech-stack.yaml")
        assert data["slots"]["key-libraries"]["value"] == new_libs

    def test_returns_check_issues(self, facts_dir):
        result = set_slot(facts_dir, "tech-stack.database", "MongoDB 7")
        assert result.check_issues is not None


class TestAddSlot:
    def test_creates_new_slot(self, facts_dir):
        result = add_slot(facts_dir, "tech-stack", "orm", "SQLAlchemy 2.0")
        assert isinstance(result, AddResult)
        assert result.category == "tech-stack"
        assert result.slot_id == "orm"
        assert result.value == "SQLAlchemy 2.0"

        data = load_yaml_roundtrip(facts_dir / "canonical" / "tech-stack.yaml")
        assert "orm" in data["slots"]
        slot = data["slots"]["orm"]
        assert slot["value"] == "SQLAlchemy 2.0"
        assert slot["meta"]["status"] == "active"
        assert slot["meta"]["source"] == "human"

    def test_with_reason(self, facts_dir):
        add_slot(facts_dir, "tech-stack", "orm", "SQLAlchemy 2.0", reason="async support")

        data = load_yaml_roundtrip(facts_dir / "canonical" / "tech-stack.yaml")
        assert data["slots"]["orm"]["meta"]["reason"] == "async support"

    def test_existing_slot_errors(self, facts_dir):
        with pytest.raises(KeyError, match="already exists"):
            add_slot(facts_dir, "tech-stack", "database", "PostgreSQL 17")

    def test_disabled_category_errors(self, facts_dir):
        with pytest.raises(ValueError, match="not enabled"):
            add_slot(facts_dir, "security", "auth", "JWT")

    def test_returns_check_issues(self, facts_dir):
        result = add_slot(facts_dir, "tech-stack", "orm", "SQLAlchemy 2.0")
        assert result.check_issues is not None


class TestDeprecateSlot:
    def test_sets_superseded(self, facts_dir):
        result = deprecate_slot(facts_dir, "tech-stack.framework")
        assert isinstance(result, DeprecateResult)
        assert result.old_status == "active"

        data = load_yaml_roundtrip(facts_dir / "canonical" / "tech-stack.yaml")
        assert data["slots"]["framework"]["meta"]["status"] == "superseded"

    def test_with_reason(self, facts_dir):
        deprecate_slot(facts_dir, "tech-stack.framework", reason="switching to Django")

        data = load_yaml_roundtrip(facts_dir / "canonical" / "tech-stack.yaml")
        assert data["slots"]["framework"]["meta"]["reason"] == "switching to Django"

    def test_nonexistent_slot_errors(self, facts_dir):
        with pytest.raises(KeyError, match="not found"):
            deprecate_slot(facts_dir, "tech-stack.nonexistent")

    def test_returns_impact(self, facts_dir):
        result = deprecate_slot(facts_dir, "tech-stack.database")
        assert result.impact is not None
        target_slots = [t.slot for t in result.impact.targets]
        assert "data-model.database-type" in target_slots


class TestSetBatch:
    def _mock_audit(self, *args, **kwargs):
        from fact_layer.core.auditor import AuditResult
        return AuditResult(findings=[], summary="All facts are consistent.")

    def test_batch_multiple_success(self, facts_dir):
        items = [
            BatchSetItem(slot="tech-stack.database", value="PostgreSQL 17"),
            BatchSetItem(slot="tech-stack.framework", value="Django 5.0", reason="migration"),
        ]
        with patch("fact_layer.core.auditor.run_audit", self._mock_audit):
            result = set_batch(facts_dir, items)

        assert isinstance(result, BatchSetResult)
        assert len(result.results) == 2
        assert result.results[0].new_value == "PostgreSQL 17"
        assert result.results[1].new_value == "Django 5.0"
        assert all(r.error is None for r in result.results)

        data = load_yaml_roundtrip(facts_dir / "canonical" / "tech-stack.yaml")
        assert data["slots"]["database"]["value"] == "PostgreSQL 17"
        assert data["slots"]["framework"]["value"] == "Django 5.0"

    def test_partial_failure(self, facts_dir):
        items = [
            BatchSetItem(slot="tech-stack.database", value="PostgreSQL 17"),
            BatchSetItem(slot="tech-stack.nonexistent", value="oops"),
            BatchSetItem(slot="tech-stack.framework", value="Django 5.0"),
        ]
        with patch("fact_layer.core.auditor.run_audit", self._mock_audit):
            result = set_batch(facts_dir, items)

        assert len(result.results) == 3
        assert result.results[0].error is None
        assert result.results[1].error is not None
        assert result.results[2].error is None

    def test_empty_items(self, facts_dir):
        result = set_batch(facts_dir, [], audit=False)
        assert isinstance(result, BatchSetResult)
        assert len(result.results) == 0
        assert result.audit is None

    def test_audit_triggered(self, facts_dir):
        items = [BatchSetItem(slot="tech-stack.database", value="PostgreSQL 17")]
        with patch("fact_layer.core.auditor.run_audit", wraps=self._mock_audit) as mock:
            result = set_batch(facts_dir, items, audit=True)
            mock.assert_called_once()
        assert result.audit is not None

    def test_audit_skipped(self, facts_dir):
        items = [BatchSetItem(slot="tech-stack.database", value="PostgreSQL 17")]
        result = set_batch(facts_dir, items, audit=False)
        assert result.audit is None

    def test_with_reason(self, facts_dir):
        items = [BatchSetItem(slot="tech-stack.database", value="PostgreSQL 17", reason="LTS")]
        with patch("fact_layer.core.auditor.run_audit", self._mock_audit):
            set_batch(facts_dir, items)

        data = load_yaml_roundtrip(facts_dir / "canonical" / "tech-stack.yaml")
        assert data["slots"]["database"]["meta"]["reason"] == "LTS"
