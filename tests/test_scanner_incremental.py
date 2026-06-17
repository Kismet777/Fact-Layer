# tests/test_scanner_incremental.py
"""Tests for incremental scan logic: hash-based skip, stale rescan, removed cleanup."""

from pathlib import Path

from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.scanner.indexes import (
    load_extraction_index,
    load_source_index,
)
from fact_layer.core.scanner.pipeline import run_scan


def _init_project(tmp_path: Path) -> Path:
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


def _write_pyproject(proj: Path, content: str | None = None) -> Path:
    toml = proj / "pyproject.toml"
    toml.write_text(content or """\
[project]
name = "test-proj"
requires-python = ">=3.12"

[project.dependencies]
fastapi = ">=0.111"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
""")
    return toml


class TestIncrementalScan:
    def test_first_scan_populates_indexes(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        _write_pyproject(proj)
        result = run_scan(proj)
        assert result.stats.files_scanned >= 1
        assert result.stats.skipped_files == 0

        src_idx = load_source_index(proj / ".facts")
        assert len(src_idx.sources) >= 1
        for entry in src_idx.sources.values():
            assert entry.status == "active"
            assert len(entry.content_hash) == 12

    def test_second_scan_skips_unchanged(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        _write_pyproject(proj)

        run_scan(proj)
        result2 = run_scan(proj)
        assert result2.stats.skipped_files >= 1
        assert result2.stats.candidates_found == 0

    def test_full_flag_ignores_indexes(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        _write_pyproject(proj)

        run_scan(proj)
        result2 = run_scan(proj, full=True)
        assert result2.stats.skipped_files == 0
        assert result2.stats.candidates_found >= 1

    def test_changed_file_rescanned(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        _write_pyproject(proj)

        run_scan(proj)

        _write_pyproject(proj, """\
[project]
name = "test-proj"
requires-python = ">=3.13"

[project.dependencies]
fastapi = ">=0.111"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
""")
        result2 = run_scan(proj)
        assert result2.stats.skipped_files == 0
        assert result2.stats.files_scanned >= 1

    def test_removed_file_marks_source_removed(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        toml = _write_pyproject(proj)

        run_scan(proj)
        src_idx = load_source_index(proj / ".facts")
        assert any(e.status == "active" for e in src_idx.sources.values())

        toml.unlink()
        run_scan(proj)
        src_idx = load_source_index(proj / ".facts")
        for entry in src_idx.sources.values():
            if entry.path == "pyproject.toml":
                assert entry.status == "removed"

    def test_removed_file_cleans_extractions(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        toml = _write_pyproject(proj)

        run_scan(proj)
        ext_idx = load_extraction_index(proj / ".facts")
        assert len(ext_idx.extractions) >= 1

        toml.unlink()
        run_scan(proj)
        ext_idx = load_extraction_index(proj / ".facts")
        assert len(ext_idx.extractions) == 0

    def test_extraction_index_tracks_slots(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        _write_pyproject(proj)

        run_scan(proj)
        ext_idx = load_extraction_index(proj / ".facts")
        slot_refs = {e.slot_ref for e in ext_idx.extractions.values()}
        assert "tech-stack.language" in slot_refs

    def test_new_file_added_to_index(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        _write_pyproject(proj)

        run_scan(proj)

        dc = proj / "docker-compose.yaml"
        dc.write_text("services:\n  db:\n    image: postgres:16-alpine\n")

        result2 = run_scan(proj)
        assert result2.stats.files_scanned >= 1

        src_idx = load_source_index(proj / ".facts")
        paths = {e.path for e in src_idx.sources.values() if e.status == "active"}
        assert "docker-compose.yaml" in paths

    def test_skipped_files_in_stats(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        _write_pyproject(proj)

        run_scan(proj)
        result = run_scan(proj)
        assert "skipped_files" in result.stats.model_dump()
        assert result.stats.skipped_files >= 1

    def test_multiple_files_mixed_skip(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        _write_pyproject(proj)
        dc = proj / "docker-compose.yaml"
        dc.write_text("services:\n  db:\n    image: postgres:16-alpine\n")

        run_scan(proj)

        dc.write_text("services:\n  db:\n    image: postgres:17-alpine\n")
        result = run_scan(proj)
        assert result.stats.skipped_files >= 1
        assert result.stats.files_scanned >= 1
