"""Smoke tests for the dependency-edge editing interface (B-002) via CLI + MCP."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from fact_layer.cli import app
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.writer import dump_yaml
from fact_layer.mcp_server import facts_dep_add, facts_dep_list, facts_dep_remove

runner = CliRunner()


def _slot(value):
    return {
        "value": value,
        "meta": {
            "source": "human", "confidence": "high", "status": "active",
            "updated": "2026-06-09", "verified": "2026-06-09",
        },
    }


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    init_facts_dir(
        target=proj,
        project_name="t",
        language="Python 3.12",
        enabled_extensions=["data-model", "testing", "build-deploy"],
        enabled_optional=["decisions"],
    )
    facts = proj / ".facts"
    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {"language": _slot("Python 3.12"), "framework": _slot("FastAPI")},
    })
    dump_yaml(facts / "canonical" / "conventions.yaml", {
        "category": "conventions", "tier": "stable",
        "slots": {"naming": _slot("snake_case")},
    })
    dump_yaml(facts / "dependencies.yaml", {
        "static": [
            {"source": "tech-stack.language",
             "targets": [{"slot": "conventions.naming", "type": "constrains"}]},
        ],
    })
    monkeypatch.chdir(proj)
    return proj


class TestDepCli:
    def test_list_shows_seed_edge(self, project_dir):
        result = runner.invoke(app, ["dep", "list"])
        assert result.exit_code == 0
        assert "tech-stack.language" in result.stdout
        assert "conventions.naming" in result.stdout

    def test_add_then_list(self, project_dir):
        result = runner.invoke(app, ["dep", "add", "tech-stack.language", "tech-stack.framework", "constrains"])
        assert result.exit_code == 0
        listed = runner.invoke(app, ["dep", "list"])
        assert "tech-stack.framework" in listed.stdout

    def test_rm(self, project_dir):
        result = runner.invoke(app, ["dep", "rm", "tech-stack.language", "conventions.naming"])
        assert result.exit_code == 0
        listed = runner.invoke(app, ["dep", "list"])
        assert "conventions.naming" not in listed.stdout

    def test_add_invalid_type_exits_nonzero(self, project_dir):
        result = runner.invoke(app, ["dep", "add", "tech-stack.language", "conventions.naming", "bogus"])
        assert result.exit_code == 1

    def test_rm_absent_exits_nonzero(self, project_dir):
        result = runner.invoke(app, ["dep", "rm", "tech-stack.language", "tech-stack.framework"])
        assert result.exit_code == 1


class TestDepMcp:
    def test_add_and_list(self, project_dir):
        res = facts_dep_add("tech-stack.framework", "conventions.naming", "constrains")
        assert res["added"] is True
        edges = facts_dep_list()["edges"]
        assert {"source": "tech-stack.framework", "target": "conventions.naming", "type": "constrains"} in edges

    def test_remove(self, project_dir):
        res = facts_dep_remove("tech-stack.language", "conventions.naming")
        assert res["removed"] is True
        assert facts_dep_list()["edges"] == []

    def test_remove_absent_returns_false(self, project_dir):
        res = facts_dep_remove("tech-stack.language", "tech-stack.framework")
        assert res["removed"] is False

    def test_add_dangling_raises(self, project_dir):
        with pytest.raises(ValueError, match="does not exist"):
            facts_dep_add("tech-stack.language", "conventions.nonexistent", "constrains")
