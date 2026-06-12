# tests/test_scanner_candidates.py
"""Tests for scanner data models."""

from fact_layer.core.scanner.candidates import (
    ConflictGroup,
    ScanResult,
    ScanStats,
    SlotCandidate,
    UnmappedFact,
)


class TestSlotCandidate:
    def test_create_minimal(self):
        c = SlotCandidate(
            category="tech-stack",
            slot="database",
            value="PostgreSQL 16",
            confidence="high",
            source="docker-compose.yaml:8",
            extractor="config-parser",
            evidence="image: postgres:16-alpine",
        )
        assert c.category == "tech-stack"
        assert c.slot == "database"
        assert c.slot_ref == "tech-stack.database"

    def test_slot_ref_property(self):
        c = SlotCandidate(
            category="build-deploy",
            slot="ci",
            value="GitHub Actions",
            confidence="high",
            source=".github/workflows/ci.yaml:1",
            extractor="config-parser",
            evidence="name: CI",
        )
        assert c.slot_ref == "build-deploy.ci"

    def test_json_serialization(self):
        c = SlotCandidate(
            category="tech-stack",
            slot="key-libraries",
            value=["fastapi", "pydantic"],
            confidence="high",
            source="pyproject.toml:10",
            extractor="config-parser",
            evidence='dependencies = ["fastapi", "pydantic"]',
        )
        d = c.model_dump(mode="json")
        assert d["category"] == "tech-stack"
        assert d["value"] == ["fastapi", "pydantic"]


class TestConflictGroup:
    def test_create(self):
        c1 = SlotCandidate(
            category="tech-stack", slot="database", value="PostgreSQL 16",
            confidence="high", source="docker-compose.yaml:8",
            extractor="config-parser", evidence="image: postgres:16",
        )
        c2 = SlotCandidate(
            category="tech-stack", slot="database", value="PostgreSQL 14",
            confidence="medium", source="README.md:35",
            extractor="llm-markdown", evidence="We use PostgreSQL 14",
        )
        g = ConflictGroup(slot_ref="tech-stack.database", candidates=[c1, c2])
        assert g.slot_ref == "tech-stack.database"
        assert len(g.candidates) == 2


class TestUnmappedFact:
    def test_create(self):
        u = UnmappedFact(
            fact="Project uses monorepo structure",
            source="README.md:10",
            suggested_category="architecture",
            suggested_slot="repo-structure",
        )
        assert u.fact == "Project uses monorepo structure"


class TestScanResult:
    def test_empty(self):
        r = ScanResult(
            candidates=[],
            conflicts=[],
            unmapped=[],
            stats=ScanStats(files_scanned=0, candidates_found=0, conflicts=0, unmapped=0),
        )
        assert r.stats.files_scanned == 0

    def test_json_serialization(self):
        c = SlotCandidate(
            category="tech-stack", slot="language", value="Python 3.12",
            confidence="high", source="pyproject.toml:3",
            extractor="config-parser", evidence='requires-python = ">=3.12"',
        )
        r = ScanResult(
            candidates=[c],
            conflicts=[],
            unmapped=[],
            stats=ScanStats(files_scanned=1, candidates_found=1, conflicts=0, unmapped=0),
        )
        d = r.model_dump(mode="json")
        assert len(d["candidates"]) == 1
        assert d["stats"]["files_scanned"] == 1
