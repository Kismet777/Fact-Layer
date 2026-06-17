# tests/test_scanner_indexes.py
"""Tests for scan index data models and I/O."""

from pathlib import Path

from fact_layer.core.scanner.indexes import (
    ExtractionEntry,
    ExtractionIndex,
    SourceEntry,
    SourceIndex,
    compute_content_hash,
    load_extraction_index,
    load_source_index,
    next_id,
    save_extraction_index,
    save_source_index,
)


class TestSourceEntry:
    def test_create(self):
        e = SourceEntry(
            path="pyproject.toml",
            type="config",
            status="active",
            content_hash="a3f2c1d4e5f6",
            last_scanned="2026-06-15",
            extracted_count=4,
        )
        assert e.path == "pyproject.toml"
        assert e.type == "config"
        assert e.status == "active"

    def test_json_roundtrip(self):
        e = SourceEntry(
            path="README.md", type="markdown", status="stale",
            content_hash="abc123", last_scanned="2026-06-15", extracted_count=2,
        )
        d = e.model_dump(mode="json")
        e2 = SourceEntry.model_validate(d)
        assert e2.path == e.path
        assert e2.status == "stale"


class TestSourceIndex:
    def test_empty(self):
        idx = SourceIndex()
        assert idx.version == 1
        assert idx.sources == {}

    def test_with_entries(self):
        idx = SourceIndex(sources={
            "SRC-001": SourceEntry(
                path="pyproject.toml", type="config", status="active",
                content_hash="abc", last_scanned="2026-06-15", extracted_count=3,
            ),
        })
        assert "SRC-001" in idx.sources
        assert idx.sources["SRC-001"].path == "pyproject.toml"


class TestExtractionEntry:
    def test_create(self):
        e = ExtractionEntry(
            slot_ref="tech-stack.language",
            source_id="SRC-001",
            source_location="pyproject.toml:3",
            extractor="config-parser",
            confidence="high",
            status="active",
            extracted_at="2026-06-15",
        )
        assert e.slot_ref == "tech-stack.language"
        assert e.superseded_by is None

    def test_superseded(self):
        e = ExtractionEntry(
            slot_ref="tech-stack.database",
            source_id="SRC-002",
            source_location="docker-compose.yaml:5",
            extractor="config-parser",
            confidence="high",
            status="superseded",
            extracted_at="2026-06-14",
            superseded_by="EXT-005",
        )
        assert e.status == "superseded"
        assert e.superseded_by == "EXT-005"


class TestExtractionIndex:
    def test_empty(self):
        idx = ExtractionIndex()
        assert idx.version == 1
        assert idx.extractions == {}


class TestComputeContentHash:
    def test_deterministic(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h1 = compute_content_hash(f)
        h2 = compute_content_hash(f)
        assert h1 == h2
        assert len(h1) == 12

    def test_different_content(self, tmp_path: Path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello")
        f2.write_text("world")
        assert compute_content_hash(f1) != compute_content_hash(f2)


class TestNextId:
    def test_first_id(self):
        assert next_id("SRC", {}) == "SRC-001"

    def test_sequential(self):
        existing = {"SRC-001": None, "SRC-002": None}
        assert next_id("SRC", existing) == "SRC-003"

    def test_with_gaps(self):
        existing = {"EXT-001": None, "EXT-005": None}
        assert next_id("EXT", existing) == "EXT-006"

    def test_ignores_malformed(self):
        existing = {"SRC-001": None, "SRC-abc": None}
        assert next_id("SRC", existing) == "SRC-002"

    def test_with_set(self):
        existing = {"SRC-001", "SRC-003"}
        assert next_id("SRC", existing) == "SRC-004"


class TestSourceIndexIO:
    def test_save_and_load(self, tmp_path: Path):
        facts_dir = tmp_path / ".facts"
        facts_dir.mkdir()

        idx = SourceIndex(sources={
            "SRC-001": SourceEntry(
                path="pyproject.toml", type="config", status="active",
                content_hash="abc123", last_scanned="2026-06-15", extracted_count=3,
            ),
        })
        save_source_index(facts_dir, idx)
        loaded = load_source_index(facts_dir)
        assert loaded.version == 1
        assert "SRC-001" in loaded.sources
        assert loaded.sources["SRC-001"].path == "pyproject.toml"

    def test_load_missing(self, tmp_path: Path):
        facts_dir = tmp_path / ".facts"
        facts_dir.mkdir()
        loaded = load_source_index(facts_dir)
        assert loaded.sources == {}

    def test_creates_indexes_dir(self, tmp_path: Path):
        facts_dir = tmp_path / ".facts"
        save_source_index(facts_dir, SourceIndex())
        assert (facts_dir / "indexes").is_dir()


class TestExtractionIndexIO:
    def test_save_and_load(self, tmp_path: Path):
        facts_dir = tmp_path / ".facts"
        facts_dir.mkdir()

        idx = ExtractionIndex(extractions={
            "EXT-001": ExtractionEntry(
                slot_ref="tech-stack.language",
                source_id="SRC-001",
                source_location="pyproject.toml:3",
                extractor="config-parser",
                confidence="high",
                status="active",
                extracted_at="2026-06-15",
            ),
        })
        save_extraction_index(facts_dir, idx)
        loaded = load_extraction_index(facts_dir)
        assert "EXT-001" in loaded.extractions
        assert loaded.extractions["EXT-001"].slot_ref == "tech-stack.language"

    def test_load_missing(self, tmp_path: Path):
        facts_dir = tmp_path / ".facts"
        facts_dir.mkdir()
        loaded = load_extraction_index(facts_dir)
        assert loaded.extractions == {}
