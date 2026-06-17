# tests/test_scan_integrity.py
"""Tests for scan index integrity checks."""

from pathlib import Path

from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.scan_integrity import run_scan_integrity
from fact_layer.core.scanner.indexes import (
    ExtractionEntry,
    ExtractionIndex,
    SourceEntry,
    SourceIndex,
    save_extraction_index,
    save_source_index,
)
from fact_layer.core.writer import dump_yaml


def _make_slot(value, updated="2026-06-15", verified="2026-06-15"):
    return {
        "value": value,
        "meta": {
            "source": "human", "confidence": "high", "status": "active",
            "updated": updated, "verified": verified,
        },
    }


def _init_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    init_facts_dir(
        target=proj,
        project_name="test-proj",
        language="Python 3.12",
        enabled_extensions=[],
        enabled_optional=[],
    )
    return proj


class TestScanIntegrity:
    def test_all_consistent(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        facts_dir = proj / ".facts"

        save_source_index(facts_dir, SourceIndex(sources={
            "SRC-001": SourceEntry(
                path="pyproject.toml", type="config", status="active",
                content_hash="abc123", last_scanned="2026-06-15", extracted_count=1,
            ),
        }))
        save_extraction_index(facts_dir, ExtractionIndex(extractions={
            "EXT-001": ExtractionEntry(
                slot_ref="tech-stack.language",
                source_id="SRC-001",
                source_location="pyproject.toml:3",
                extractor="config-parser",
                confidence="high",
                status="active",
                extracted_at="2026-06-15",
            ),
        }))

        result = run_scan_integrity(facts_dir)
        assert len(result.findings) == 0
        assert "consistent" in result.summary.lower()

    def test_orphaned_extraction(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        facts_dir = proj / ".facts"

        save_source_index(facts_dir, SourceIndex())
        save_extraction_index(facts_dir, ExtractionIndex(extractions={
            "EXT-001": ExtractionEntry(
                slot_ref="tech-stack.language",
                source_id="SRC-999",
                source_location="missing.toml:3",
                extractor="config-parser",
                confidence="high",
                status="active",
                extracted_at="2026-06-15",
            ),
        }))

        result = run_scan_integrity(facts_dir)
        types = [f.type for f in result.findings]
        assert "orphaned_extraction" in types
        orphaned = [f for f in result.findings if f.type == "orphaned_extraction"]
        assert orphaned[0].severity == "error"

    def test_stale_source(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        facts_dir = proj / ".facts"

        save_source_index(facts_dir, SourceIndex(sources={
            "SRC-001": SourceEntry(
                path="pyproject.toml", type="config", status="stale",
                content_hash="old_hash", last_scanned="2026-06-10", extracted_count=1,
            ),
        }))
        save_extraction_index(facts_dir, ExtractionIndex())

        result = run_scan_integrity(facts_dir)
        types = [f.type for f in result.findings]
        assert "stale_source" in types
        stale = [f for f in result.findings if f.type == "stale_source"]
        assert stale[0].severity == "warning"

    def test_cross_source_conflict(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        facts_dir = proj / ".facts"

        save_source_index(facts_dir, SourceIndex(sources={
            "SRC-001": SourceEntry(
                path="pyproject.toml", type="config", status="active",
                content_hash="abc", last_scanned="2026-06-15", extracted_count=1,
            ),
            "SRC-002": SourceEntry(
                path="README.md", type="markdown", status="active",
                content_hash="def", last_scanned="2026-06-15", extracted_count=1,
            ),
        }))
        save_extraction_index(facts_dir, ExtractionIndex(extractions={
            "EXT-001": ExtractionEntry(
                slot_ref="tech-stack.language",
                source_id="SRC-001",
                source_location="pyproject.toml:3",
                extractor="config-parser",
                confidence="high",
                status="active",
                extracted_at="2026-06-15",
            ),
            "EXT-002": ExtractionEntry(
                slot_ref="tech-stack.language",
                source_id="SRC-002",
                source_location="README.md:5",
                extractor="llm-markdown",
                confidence="medium",
                status="active",
                extracted_at="2026-06-15",
            ),
        }))

        result = run_scan_integrity(facts_dir)
        types = [f.type for f in result.findings]
        assert "cross_source_conflict" in types

    def test_empty_indexes(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        facts_dir = proj / ".facts"

        save_source_index(facts_dir, SourceIndex())
        save_extraction_index(facts_dir, ExtractionIndex())

        result = run_scan_integrity(facts_dir)
        assert len(result.findings) == 0

    def test_summary_counts(self, tmp_path: Path):
        proj = _init_project(tmp_path)
        facts_dir = proj / ".facts"

        save_source_index(facts_dir, SourceIndex(sources={
            "SRC-001": SourceEntry(
                path="x.toml", type="config", status="stale",
                content_hash="old", last_scanned="2026-06-10", extracted_count=0,
            ),
        }))
        save_extraction_index(facts_dir, ExtractionIndex(extractions={
            "EXT-001": ExtractionEntry(
                slot_ref="tech-stack.language",
                source_id="SRC-999",
                source_location="missing:1",
                extractor="config-parser",
                confidence="high",
                status="active",
                extracted_at="2026-06-15",
            ),
        }))

        result = run_scan_integrity(facts_dir)
        assert "1 error" in result.summary
        assert "1 warning" in result.summary
