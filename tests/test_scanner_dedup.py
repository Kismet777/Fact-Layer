# tests/test_scanner_dedup.py
"""Tests for candidate dedup and conflict detection."""

from fact_layer.core.scanner.candidates import ConflictGroup, SlotCandidate
from fact_layer.core.scanner.dedup import deduplicate


def _candidate(category, slot, value, confidence="high", source="file:1", extractor="config-parser"):
    return SlotCandidate(
        category=category, slot=slot, value=value,
        confidence=confidence, source=source,
        extractor=extractor, evidence=f"value={value}",
    )


class TestDeduplicate:
    def test_no_duplicates(self):
        candidates = [
            _candidate("tech-stack", "language", "Python 3.12"),
            _candidate("tech-stack", "database", "PostgreSQL 16"),
        ]
        merged, conflicts = deduplicate(candidates)
        assert len(merged) == 2
        assert len(conflicts) == 0

    def test_same_value_merges(self):
        candidates = [
            _candidate("tech-stack", "database", "PostgreSQL 16",
                        confidence="high", source="docker-compose.yaml:8"),
            _candidate("tech-stack", "database", "PostgreSQL 16",
                        confidence="medium", source="README.md:35"),
        ]
        merged, conflicts = deduplicate(candidates)
        assert len(merged) == 1
        assert merged[0].confidence == "high"
        assert "docker-compose.yaml:8" in merged[0].source
        assert "README.md:35" in merged[0].source

    def test_conflicting_values(self):
        candidates = [
            _candidate("tech-stack", "database", "PostgreSQL 16",
                        source="docker-compose.yaml:8"),
            _candidate("tech-stack", "database", "PostgreSQL 14",
                        source="README.md:35"),
        ]
        merged, conflicts = deduplicate(candidates)
        assert len(merged) == 0
        assert len(conflicts) == 1
        assert conflicts[0].slot_ref == "tech-stack.database"
        assert len(conflicts[0].candidates) == 2

    def test_mixed_merge_and_conflict(self):
        candidates = [
            _candidate("tech-stack", "language", "Python 3.12", source="a:1"),
            _candidate("tech-stack", "language", "Python 3.12", source="b:2"),
            _candidate("tech-stack", "database", "PostgreSQL 16", source="c:3"),
            _candidate("tech-stack", "database", "MySQL 8", source="d:4"),
        ]
        merged, conflicts = deduplicate(candidates)
        assert len(merged) == 1
        assert merged[0].slot == "language"
        assert len(conflicts) == 1
        assert conflicts[0].slot_ref == "tech-stack.database"

    def test_confidence_ordering(self):
        candidates = [
            _candidate("tech-stack", "language", "Python 3.12",
                        confidence="low", source="a:1"),
            _candidate("tech-stack", "language", "Python 3.12",
                        confidence="medium", source="b:2"),
        ]
        merged, _ = deduplicate(candidates)
        assert merged[0].confidence == "medium"

    def test_extractor_priority_in_merge(self):
        candidates = [
            _candidate("tech-stack", "language", "Python 3.12",
                        source="pyproject.toml:3", extractor="config-parser"),
            _candidate("tech-stack", "language", "Python 3.12",
                        source="README.md:1", extractor="llm-markdown"),
        ]
        merged, _ = deduplicate(candidates)
        assert merged[0].extractor == "config-parser"
        assert "pyproject.toml:3" in merged[0].source

    def test_empty_input(self):
        merged, conflicts = deduplicate([])
        assert merged == []
        assert conflicts == []

    def test_three_way_conflict(self):
        candidates = [
            _candidate("tech-stack", "database", "PostgreSQL 16", source="a:1"),
            _candidate("tech-stack", "database", "MySQL 8", source="b:2"),
            _candidate("tech-stack", "database", "SQLite", source="c:3"),
        ]
        merged, conflicts = deduplicate(candidates)
        assert len(merged) == 0
        assert len(conflicts) == 1
        assert len(conflicts[0].candidates) == 3
