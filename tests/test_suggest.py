"""Tests for fl suggest: prompt building, response parsing, and suggestion application."""

import json
from datetime import date
from pathlib import Path

import pytest

from fact_layer.core.checker import CheckIssue, Severity, run_check
from fact_layer.core.editor import load_yaml_roundtrip
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.loader import load_all_categories
from fact_layer.core.suggest_cmd import (
    Suggestion,
    SuggestResult,
    apply_suggestion,
    build_suggest_prompt,
    format_check_issues,
    parse_suggestions,
)
from fact_layer.core.writer import dump_yaml


def _slot(value, updated=None, verified=None, status="active", reason=None):
    if updated is None:
        updated = date.today().isoformat()
    if verified is None:
        verified = date.today().isoformat()
    meta = {
        "source": "human", "confidence": "high", "status": status,
        "updated": updated, "verified": verified,
    }
    if reason:
        meta["reason"] = reason
    return {"value": value, "meta": meta}


@pytest.fixture
def facts_dir(tmp_path: Path) -> Path:
    proj = tmp_path / "suggest-proj"
    proj.mkdir()
    init_facts_dir(
        target=proj,
        project_name="suggest-proj",
        language="Python 3.12",
        enabled_extensions=["data-model", "build-deploy"],
        enabled_optional=["decisions"],
    )
    facts = proj / ".facts"

    dump_yaml(facts / "canonical" / "project-overview.yaml", {
        "category": "project-overview", "tier": "stable",
        "slots": {
            "name": _slot("suggest-proj"),
            "purpose": _slot("Testing suggest feature"),
            "stage": _slot("active-development"),
        },
    })
    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {
            "language": _slot("Python 3.12"),
            "database": _slot("MongoDB 7", updated="2026-06-09"),
        },
    })
    dump_yaml(facts / "canonical" / "architecture.yaml", {
        "category": "architecture", "tier": "stable",
        "slots": {"style": _slot("layered monolith")},
    })
    dump_yaml(facts / "canonical" / "conventions.yaml", {
        "category": "conventions", "tier": "stable",
        "slots": {"naming": _slot("snake_case")},
    })
    dump_yaml(facts / "canonical" / "data-model.yaml", {
        "category": "data-model", "tier": "dynamic",
        "slots": {
            "database-type": _slot("PostgreSQL 16", updated="2026-05-01"),
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
        "slots": {"focus": _slot("Testing suggest")},
    })

    return facts


@pytest.fixture
def facts_with_issues(facts_dir):
    """facts_dir already has a dep violation: tech-stack.database (MongoDB 7, 06-09) vs data-model.database-type (PostgreSQL 16, 05-01)."""
    return facts_dir


class TestFormatCheckIssues:
    def test_empty(self):
        assert format_check_issues([]) == "No issues found."

    def test_formats_issues(self):
        issues = [
            CheckIssue(
                category_name="tech-stack",
                check_type="dependency",
                severity=Severity.ERROR,
                message="tech-stack.database updated but data-model.database-type stale",
                slot="tech-stack.database",
                detail="derives-from: downstream must be updated",
            ),
        ]
        result = format_check_issues(issues)
        assert "[ERROR]" in result
        assert "tech-stack.database" in result
        assert "derives-from" in result


class TestBuildSuggestPrompt:
    def test_contains_all_sections(self, facts_with_issues):
        issues = run_check(facts_with_issues).issues
        prompt = build_suggest_prompt(facts_with_issues, issues)
        assert "Project Facts" in prompt
        assert "Dependency Graph" in prompt
        assert "Issues Found" in prompt
        assert "MongoDB 7" in prompt or "tech-stack.database" in prompt


class TestParseSuggestions:
    def test_valid_json(self, facts_dir):
        categories = load_all_categories(facts_dir)
        raw = json.dumps({
            "suggestions": [
                {
                    "slot": "data-model.database-type",
                    "suggested_value": "MongoDB 7",
                    "reason": "Should match tech-stack.database",
                },
            ],
        })
        result = parse_suggestions(raw, categories)
        assert len(result) == 1
        assert result[0].slot == "data-model.database-type"
        assert result[0].suggested_value == "MongoDB 7"
        assert result[0].current_value == "PostgreSQL 16"

    def test_empty_suggestions(self, facts_dir):
        categories = load_all_categories(facts_dir)
        raw = json.dumps({"suggestions": []})
        result = parse_suggestions(raw, categories)
        assert result == []

    def test_invalid_json(self, facts_dir):
        categories = load_all_categories(facts_dir)
        result = parse_suggestions("not json at all", categories)
        assert result == []

    def test_strips_markdown_fences(self, facts_dir):
        categories = load_all_categories(facts_dir)
        raw = "```json\n" + json.dumps({
            "suggestions": [
                {"slot": "tech-stack.database", "suggested_value": "PostgreSQL 17", "reason": "test"},
            ],
        }) + "\n```"
        result = parse_suggestions(raw, categories)
        assert len(result) == 1

    def test_skips_invalid_slot_ref(self, facts_dir):
        categories = load_all_categories(facts_dir)
        raw = json.dumps({
            "suggestions": [
                {"slot": "nodotshere", "suggested_value": "x", "reason": "bad"},
                {"slot": "tech-stack.database", "suggested_value": "PG17", "reason": "ok"},
            ],
        })
        result = parse_suggestions(raw, categories)
        assert len(result) == 1
        assert result[0].slot == "tech-stack.database"


class TestApplySuggestion:
    def test_applies_and_sets_source(self, facts_dir):
        suggestion = Suggestion(
            slot="tech-stack.database",
            current_value="MongoDB 7",
            suggested_value="PostgreSQL 17",
            reason="consistency fix",
        )
        apply_suggestion(facts_dir, suggestion)

        data = load_yaml_roundtrip(facts_dir / "canonical" / "tech-stack.yaml")
        slot = data["slots"]["database"]
        assert slot["value"] == "PostgreSQL 17"
        assert slot["meta"]["source"] == "agent-analysis"
        assert slot["meta"]["reason"] == "fl suggest: consistency fix"

    def test_applies_with_custom_source(self, facts_dir):
        suggestion = Suggestion(
            slot="tech-stack.database",
            suggested_value="MySQL 8",
            reason="audit fix",
        )
        apply_suggestion(facts_dir, suggestion, source="human")

        data = load_yaml_roundtrip(facts_dir / "canonical" / "tech-stack.yaml")
        assert data["slots"]["database"]["meta"]["source"] == "human"


class TestSuggestResult:
    def test_no_issues_returns_error(self, tmp_path):
        proj = tmp_path / "clean-proj"
        proj.mkdir()
        init_facts_dir(
            target=proj,
            project_name="clean-proj",
            language="Python",
            enabled_extensions=[],
            enabled_optional=[],
        )
        facts = proj / ".facts"
        dump_yaml(facts / "canonical" / "project-overview.yaml", {
            "category": "project-overview", "tier": "stable",
            "slots": {
                "name": _slot("clean-proj"),
                "purpose": _slot("Clean project"),
                "stage": _slot("active"),
            },
        })
        dump_yaml(facts / "canonical" / "tech-stack.yaml", {
            "category": "tech-stack", "tier": "stable",
            "slots": {"language": _slot("Python")},
        })
        dump_yaml(facts / "canonical" / "architecture.yaml", {
            "category": "architecture", "tier": "stable",
            "slots": {"style": _slot("monolith")},
        })
        dump_yaml(facts / "canonical" / "conventions.yaml", {
            "category": "conventions", "tier": "stable",
            "slots": {"naming": _slot("snake_case")},
        })
        dump_yaml(facts / "canonical" / "work-in-progress.yaml", {
            "category": "work-in-progress", "tier": "working",
            "slots": {"focus": _slot("nothing")},
        })

        from fact_layer.core.suggest_cmd import run_suggest

        result = run_suggest(facts, api_key="fake-key")
        assert result.error is not None
        assert "No issues" in result.error
