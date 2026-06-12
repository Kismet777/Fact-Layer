# tests/test_scanner_pipeline.py
"""Tests for the scan pipeline: discover → dispatch → extract → dedup → result."""

from pathlib import Path

from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.scanner.pipeline import run_scan


class TestRunScan:
    def _init_project(self, tmp_path: Path) -> Path:
        proj = tmp_path / "proj"
        proj.mkdir()
        init_facts_dir(
            target=proj,
            project_name="test-proj",
            language="Python 3.12",
            enabled_extensions=["build-deploy"],
            enabled_optional=[],
        )
        return proj

    def test_scan_pyproject(self, tmp_path: Path):
        proj = self._init_project(tmp_path)
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
        result = run_scan(proj, paths=[str(toml)])
        assert result.stats.files_scanned >= 1
        assert result.stats.candidates_found >= 1
        slots = {c.slot_ref for c in result.candidates}
        assert "tech-stack.language" in slots

    def test_scan_docker_compose(self, tmp_path: Path):
        proj = self._init_project(tmp_path)
        dc = proj / "docker-compose.yaml"
        dc.write_text("""\
services:
  db:
    image: postgres:16-alpine
""")
        result = run_scan(proj, paths=[str(dc)])
        slots = {c.slot_ref for c in result.candidates}
        assert "tech-stack.database" in slots

    def test_scan_directory(self, tmp_path: Path):
        proj = self._init_project(tmp_path)
        toml = proj / "pyproject.toml"
        toml.write_text("""\
[project]
name = "test-proj"
requires-python = ">=3.12"
""")
        result = run_scan(proj, paths=[str(proj)])
        assert result.stats.files_scanned >= 1

    def test_scan_auto_discover(self, tmp_path: Path):
        proj = self._init_project(tmp_path)
        toml = proj / "pyproject.toml"
        toml.write_text("""\
[project]
name = "test-proj"
requires-python = ">=3.12"
""")
        result = run_scan(proj)
        assert result.stats.files_scanned >= 1

    def test_scan_category_filter(self, tmp_path: Path):
        proj = self._init_project(tmp_path)
        toml = proj / "pyproject.toml"
        toml.write_text("""\
[project]
name = "test-proj"
requires-python = ">=3.12"

[project.dependencies]
fastapi = ">=0.111"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
""")
        result = run_scan(proj, paths=[str(toml)], categories=["build-deploy"])
        for c in result.candidates:
            assert c.category == "build-deploy"

    def test_scan_conflict_detection(self, tmp_path: Path):
        proj = self._init_project(tmp_path)
        dc = proj / "docker-compose.yaml"
        dc.write_text("""\
services:
  db:
    image: postgres:16-alpine
  legacy:
    image: mysql:8.0
""")
        result = run_scan(proj, paths=[str(dc)])
        assert result.stats.conflicts >= 1 or len(result.conflicts) >= 1

    def test_scan_empty_project(self, tmp_path: Path):
        proj = self._init_project(tmp_path)
        result = run_scan(proj, paths=[])
        assert result.stats.candidates_found == 0

    def test_scan_dedup_across_files(self, tmp_path: Path):
        proj = self._init_project(tmp_path)
        toml = proj / "pyproject.toml"
        toml.write_text("""\
[project]
name = "test-proj"
requires-python = ">=3.12"
""")
        df = proj / "Dockerfile"
        df.write_text("FROM python:3.12-slim\n")
        result = run_scan(proj, paths=[str(toml), str(df)])
        lang_candidates = [c for c in result.candidates if c.slot == "language"]
        assert len(lang_candidates) <= 1
