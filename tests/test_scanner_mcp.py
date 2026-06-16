# tests/test_scanner_mcp.py
"""Tests for facts_scan MCP tool."""

from pathlib import Path

import pytest

from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.writer import dump_yaml
from fact_layer.mcp_server import facts_scan


def _make_slot(value, updated="2026-06-09", verified="2026-06-09"):
    return {
        "value": value,
        "meta": {
            "source": "human", "confidence": "high", "status": "active",
            "updated": updated, "verified": verified,
        },
    }


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    init_facts_dir(
        target=proj,
        project_name="test-proj",
        language="Python 3.12",
        enabled_extensions=["build-deploy"],
        enabled_optional=[],
    )
    facts = proj / ".facts"
    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {"language": _make_slot("Python 3.12")},
    })
    monkeypatch.chdir(proj)
    return proj


class TestFactsScan:
    def test_scan_pyproject(self, project_dir: Path):
        toml = project_dir / "pyproject.toml"
        toml.write_text("""\
[project]
name = "test-proj"
requires-python = ">=3.12"

[project.dependencies]
fastapi = ">=0.111"
""")
        result = facts_scan(paths=[str(toml)])
        assert isinstance(result, dict)
        assert "candidates" in result
        assert "conflicts" in result
        assert "unmapped" in result
        assert "stats" in result
        assert result["stats"]["files_scanned"] >= 1
        assert result["stats"]["candidates_found"] >= 1

    def test_scan_auto_discover(self, project_dir: Path):
        toml = project_dir / "pyproject.toml"
        toml.write_text("""\
[project]
name = "test-proj"
requires-python = ">=3.12"
""")
        result = facts_scan()
        assert result["stats"]["files_scanned"] >= 1

    def test_scan_with_category_filter(self, project_dir: Path):
        toml = project_dir / "pyproject.toml"
        toml.write_text("""\
[project]
name = "test-proj"
requires-python = ">=3.12"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
""")
        result = facts_scan(paths=[str(toml)], categories=["build-deploy"])
        for c in result["candidates"]:
            assert c["category"] == "build-deploy"

    def test_scan_no_facts_dir(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="No .facts/ directory found"):
            facts_scan()

    def test_scan_empty(self, project_dir: Path):
        result = facts_scan(paths=[])
        assert result["stats"]["candidates_found"] == 0

    def test_scan_with_model(self, project_dir: Path):
        toml = project_dir / "pyproject.toml"
        toml.write_text('[project]\nname = "x"\nrequires-python = ">=3.12"\n')
        result = facts_scan(paths=[str(toml)], model="claude-haiku-4-5-20251001")
        assert result["stats"]["candidates_found"] >= 1

    def test_scan_with_extractors_filter(self, project_dir: Path):
        toml = project_dir / "pyproject.toml"
        toml.write_text('[project]\nname = "x"\nrequires-python = ">=3.12"\n')
        result = facts_scan(paths=[str(toml)], extractors=["config"])
        for c in result["candidates"]:
            assert c["extractor"] == "config-parser"

    def test_result_includes_unmapped(self, project_dir: Path):
        toml = project_dir / "pyproject.toml"
        toml.write_text('[project]\nname = "x"\nrequires-python = ">=3.12"\n')
        result = facts_scan(paths=[str(toml)])
        assert "unmapped" in result
        assert isinstance(result["unmapped"], list)
