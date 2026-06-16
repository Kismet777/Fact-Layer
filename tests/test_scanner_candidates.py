# tests/test_scanner_candidates.py
"""Tests for scanner data models."""

from pathlib import Path

from fact_layer.core.scanner.candidates import (
    ConflictGroup,
    ExtractResult,
    ScanContext,
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
        assert u.evidence == ""

    def test_with_evidence(self):
        u = UnmappedFact(
            fact="Uses monorepo",
            source="README.md:10",
            evidence="This project is organized as a monorepo",
        )
        assert u.evidence == "This project is organized as a monorepo"
        assert u.suggested_category is None


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


class TestScanContext:
    def test_defaults(self):
        ctx = ScanContext()
        assert ctx.facts_dir is None
        assert ctx.framework is None
        assert ctx.categories is None
        assert ctx.api_key is None
        assert ctx.model == "claude-sonnet-4-6"

    def test_with_values(self):
        ctx = ScanContext(
            facts_dir=Path("/tmp/.facts"),
            api_key="sk-test",
            model="claude-haiku-4-5-20251001",
        )
        assert ctx.facts_dir == Path("/tmp/.facts")
        assert ctx.api_key == "sk-test"
        assert ctx.model == "claude-haiku-4-5-20251001"


class TestExtractResult:
    def test_empty(self):
        r = ExtractResult()
        assert r.candidates == []
        assert r.unmapped == []

    def test_with_candidates(self):
        c = SlotCandidate(
            category="tech-stack", slot="language", value="Python 3.12",
            confidence="high", source="pyproject.toml:3",
            extractor="config-parser", evidence='requires-python = ">=3.12"',
        )
        r = ExtractResult(candidates=[c])
        assert len(r.candidates) == 1
        assert r.unmapped == []

    def test_with_unmapped(self):
        u = UnmappedFact(fact="Uses monorepo", source="README.md:10", evidence="monorepo")
        r = ExtractResult(unmapped=[u])
        assert r.candidates == []
        assert len(r.unmapped) == 1

    def test_json_round_trip(self):
        c = SlotCandidate(
            category="tech-stack", slot="language", value="Python 3.12",
            confidence="high", source="pyproject.toml:3",
            extractor="config-parser", evidence="test",
        )
        u = UnmappedFact(fact="fact", source="src", evidence="ev")
        r = ExtractResult(candidates=[c], unmapped=[u])
        d = r.model_dump(mode="json")
        r2 = ExtractResult.model_validate(d)
        assert len(r2.candidates) == 1
        assert len(r2.unmapped) == 1
