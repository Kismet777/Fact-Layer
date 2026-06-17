# tests/test_scanner_cli.py
"""Tests for fl scan CLI command."""

from pathlib import Path

from typer.testing import CliRunner

from fact_layer.cli import app
from fact_layer.core.init_cmd import init_facts_dir

runner = CliRunner()


def _setup_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    init_facts_dir(
        target=proj,
        project_name="test-proj",
        language="Python 3.12",
        enabled_extensions=["build-deploy"],
        enabled_optional=[],
    )
    toml = proj / "pyproject.toml"
    toml.write_text("""\
[project]
name = "test-proj"
requires-python = ">=3.12"

[project.dependencies]
fastapi = ">=0.111"
pydantic = ">=2.0"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
""")
    return proj


class TestScanCLI:
    def test_scan_dry_run(self, tmp_path: Path, monkeypatch):
        proj = _setup_project(tmp_path)
        monkeypatch.chdir(proj)
        result = runner.invoke(app, ["scan", "--dry-run"])
        assert result.exit_code == 0
        assert "tech-stack" in result.output or "candidates" in result.output.lower()

    def test_scan_explicit_path(self, tmp_path: Path, monkeypatch):
        proj = _setup_project(tmp_path)
        monkeypatch.chdir(proj)
        result = runner.invoke(app, ["scan", str(proj / "pyproject.toml"), "--dry-run"])
        assert result.exit_code == 0

    def test_scan_category_filter(self, tmp_path: Path, monkeypatch):
        proj = _setup_project(tmp_path)
        monkeypatch.chdir(proj)
        result = runner.invoke(app, ["scan", "--category", "build-deploy", "--dry-run"])
        assert result.exit_code == 0

    def test_scan_no_facts_dir(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["scan", "--dry-run"])
        assert result.exit_code == 1
        assert "No .facts/" in result.output

    def test_scan_json_output(self, tmp_path: Path, monkeypatch):
        proj = _setup_project(tmp_path)
        monkeypatch.chdir(proj)
        result = runner.invoke(app, ["scan", "--dry-run", "--json"])
        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert "candidates" in data
        assert "stats" in data

    def test_scan_empty_project(self, tmp_path: Path, monkeypatch):
        proj = tmp_path / "empty"
        proj.mkdir()
        init_facts_dir(
            target=proj, project_name="empty",
            language="Python", enabled_extensions=[], enabled_optional=[],
        )
        monkeypatch.chdir(proj)
        result = runner.invoke(app, ["scan", "--dry-run"])
        assert result.exit_code == 0
        assert "0" in result.output or "No candidates" in result.output

    def test_scan_with_model_option(self, tmp_path: Path, monkeypatch):
        proj = _setup_project(tmp_path)
        monkeypatch.chdir(proj)
        result = runner.invoke(app, ["scan", "--dry-run", "--model", "claude-haiku-4-5-20251001"])
        assert result.exit_code == 0

    def test_scan_with_extractor_filter(self, tmp_path: Path, monkeypatch):
        proj = _setup_project(tmp_path)
        monkeypatch.chdir(proj)
        result = runner.invoke(app, ["scan", "--dry-run", "--extractor", "config"])
        assert result.exit_code == 0
        assert "tech-stack" in result.output or "candidates" in result.output.lower()

    def test_scan_summary_includes_unmapped(self, tmp_path: Path, monkeypatch):
        proj = _setup_project(tmp_path)
        monkeypatch.chdir(proj)
        result = runner.invoke(app, ["scan", "--dry-run"])
        assert result.exit_code == 0
        assert "unmapped" in result.output.lower()

    def test_scan_json_includes_unmapped(self, tmp_path: Path, monkeypatch):
        proj = _setup_project(tmp_path)
        monkeypatch.chdir(proj)
        result = runner.invoke(app, ["scan", "--dry-run", "--json"])
        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert "unmapped" in data

    def test_scan_full_flag(self, tmp_path: Path, monkeypatch):
        proj = _setup_project(tmp_path)
        monkeypatch.chdir(proj)
        result = runner.invoke(app, ["scan", "--dry-run", "--full"])
        assert result.exit_code == 0

    def test_scan_incremental_shows_skipped(self, tmp_path: Path, monkeypatch):
        proj = _setup_project(tmp_path)
        monkeypatch.chdir(proj)
        runner.invoke(app, ["scan", "--dry-run"])
        result = runner.invoke(app, ["scan", "--dry-run"])
        assert result.exit_code == 0
        assert "skipped" in result.output.lower()

    def test_audit_scan_integrity(self, tmp_path: Path, monkeypatch):
        proj = _setup_project(tmp_path)
        monkeypatch.chdir(proj)
        result = runner.invoke(app, ["audit", "--scan-integrity"])
        assert result.exit_code == 0
        assert "consistent" in result.output.lower()

    def test_scan_json_includes_skipped(self, tmp_path: Path, monkeypatch):
        proj = _setup_project(tmp_path)
        monkeypatch.chdir(proj)
        runner.invoke(app, ["scan", "--dry-run"])
        result = runner.invoke(app, ["scan", "--dry-run", "--json"])
        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert "skipped_files" in data["stats"]
