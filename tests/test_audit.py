import json
from pathlib import Path

import pytest

from fact_layer.core.auditor import (
    AuditResult,
    _parse_response,
    build_audit_prompt,
    estimate_tokens,
)
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.writer import dump_yaml


def _make_slot(value, updated="2026-06-09", verified="2026-06-09", status="active"):
    return {
        "value": value,
        "meta": {
            "source": "human", "confidence": "high", "status": status,
            "updated": updated, "verified": verified,
        },
    }


@pytest.fixture
def facts_dir(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    init_facts_dir(
        target=project,
        project_name="audit-test",
        language="Python 3.12",
        enabled_extensions=["data-model"],
        enabled_optional=["decisions"],
    )
    facts = project / ".facts"

    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {
            "language": _make_slot("Python 3.12"),
            "database": _make_slot("PostgreSQL 16"),
        },
    })
    dump_yaml(facts / "canonical" / "project-overview.yaml", {
        "category": "project-overview", "tier": "stable",
        "slots": {
            "name": _make_slot("audit-test"),
            "purpose": _make_slot("REST API service"),
            "stage": _make_slot("development"),
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
        "slots": {"database-type": _make_slot("PostgreSQL 16")},
    })
    dump_yaml(facts / "canonical" / "decisions.yaml", {
        "category": "decisions", "tier": "working",
        "slots": {
            "dec-001": {
                "value": {
                    "title": "Use PostgreSQL",
                    "date": "2026-06-07",
                    "status": "active",
                    "rationale": "JSONB support",
                    "affected-slots": ["tech-stack.database"],
                },
                "meta": {
                    "source": "human", "confidence": "high", "status": "active",
                    "updated": "2026-06-07", "verified": "2026-06-07",
                },
            },
        },
    })

    return facts


class TestBuildPrompt:
    def test_contains_facts(self, facts_dir):
        prompt = build_audit_prompt(facts_dir)
        assert "Python 3.12" in prompt
        assert "PostgreSQL 16" in prompt

    def test_contains_dependency_graph(self, facts_dir):
        prompt = build_audit_prompt(facts_dir)
        assert "derives-from" in prompt or "constrains" in prompt or "No dependency" in prompt

    def test_contains_decisions(self, facts_dir):
        prompt = build_audit_prompt(facts_dir)
        assert "DEC-001" in prompt
        assert "PostgreSQL" in prompt

    def test_contains_audit_instructions(self, facts_dir):
        prompt = build_audit_prompt(facts_dir)
        assert "contradiction" in prompt
        assert "staleness" in prompt
        assert "JSON" in prompt


class TestEstimateTokens:
    def test_reasonable_estimate(self, facts_dir):
        prompt = build_audit_prompt(facts_dir)
        tokens = estimate_tokens(prompt)
        assert 100 < tokens < 10000


class TestParseResponse:
    def test_valid_json(self):
        raw = json.dumps({
            "findings": [
                {
                    "severity": "warning",
                    "type": "contradiction",
                    "slots": ["a.b", "c.d"],
                    "description": "test issue",
                    "suggestion": "fix it",
                }
            ],
            "summary": "1 warning",
        })
        result = _parse_response(raw)
        assert len(result.findings) == 1
        assert result.findings[0].type == "contradiction"
        assert result.summary == "1 warning"
        assert result.error is None

    def test_empty_findings(self):
        raw = json.dumps({"findings": [], "summary": "All consistent"})
        result = _parse_response(raw)
        assert len(result.findings) == 0
        assert result.error is None

    def test_json_with_markdown_fences(self):
        raw = '```json\n{"findings": [], "summary": "ok"}\n```'
        result = _parse_response(raw)
        assert result.error is None
        assert result.summary == "ok"

    def test_invalid_json_fallback(self):
        raw = "This is not JSON at all, just plain text analysis."
        result = _parse_response(raw)
        assert result.error is not None
        assert result.raw_response == raw

    def test_multiple_findings(self):
        raw = json.dumps({
            "findings": [
                {
                    "severity": "warning",
                    "type": "contradiction",
                    "slots": ["a.b"],
                    "description": "issue 1",
                },
                {
                    "severity": "info",
                    "type": "suggestion",
                    "slots": [],
                    "description": "idea 1",
                    "suggestion": "try this",
                },
            ],
            "summary": "1 warning, 1 suggestion",
        })
        result = _parse_response(raw)
        assert len(result.findings) == 2
