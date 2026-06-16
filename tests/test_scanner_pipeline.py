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

    def test_extractors_filter_config_only(self, tmp_path: Path):
        proj = self._init_project(tmp_path)
        toml = proj / "pyproject.toml"
        toml.write_text('[project]\nname = "x"\nrequires-python = ">=3.12"\n')
        readme = proj / "README.md"
        readme.write_text("# My Project\nUses PostgreSQL.\n")
        result = run_scan(proj, extractors=["config"])
        for c in result.candidates:
            assert c.extractor == "config-parser"

    def test_extractors_filter_markdown_only(self, tmp_path: Path):
        """When filtering to markdown only, no config candidates should appear."""
        proj = self._init_project(tmp_path)
        toml = proj / "pyproject.toml"
        toml.write_text('[project]\nname = "x"\nrequires-python = ">=3.12"\n')
        result = run_scan(proj, extractors=["markdown"])
        assert all(c.extractor != "config-parser" for c in result.candidates)

    def test_markdown_discovery(self, tmp_path: Path):
        """Markdown files in project root are discovered during auto-scan."""
        proj = self._init_project(tmp_path)
        readme = proj / "README.md"
        readme.write_text("# Hello\n")
        from fact_layer.core.scanner.pipeline import _discover_files

        files = _discover_files(proj, None, include_markdown=True)
        assert any(f.suffix == ".md" for f in files)

    def test_markdown_size_limit(self, tmp_path: Path):
        """Markdown files exceeding size limit are not discovered."""
        proj = self._init_project(tmp_path)
        big_md = proj / "huge.md"
        big_md.write_text("x" * 200_000)
        from fact_layer.core.scanner.pipeline import _discover_files

        files = _discover_files(proj, None, include_markdown=True)
        assert big_md not in files

    def test_no_markdown_when_disabled(self, tmp_path: Path):
        proj = self._init_project(tmp_path)
        readme = proj / "README.md"
        readme.write_text("# Hello\n")
        from fact_layer.core.scanner.pipeline import _discover_files

        files = _discover_files(proj, None, include_markdown=False)
        assert not any(f.suffix == ".md" for f in files)

    def test_unmapped_in_result(self, tmp_path: Path):
        """Unmapped facts from extractors appear in ScanResult."""
        proj = self._init_project(tmp_path)
        result = run_scan(proj)
        assert isinstance(result.unmapped, list)
        assert result.stats.unmapped == len(result.unmapped)

    def test_api_key_passthrough(self, tmp_path: Path):
        """api_key and model params are accepted without error."""
        proj = self._init_project(tmp_path)
        toml = proj / "pyproject.toml"
        toml.write_text('[project]\nname = "x"\nrequires-python = ">=3.12"\n')
        result = run_scan(proj, api_key="sk-test", model="claude-haiku-4-5-20251001")
        assert result.stats.candidates_found >= 1
