# tests/test_scanner_markdown.py
"""Tests for the Markdown LLM extractor."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from fact_layer.core.scanner.candidates import ExtractResult, ScanContext
from fact_layer.core.scanner.extractors.markdown import (
    _build_filled_slots,
    _build_slot_definitions,
    _parse_extraction_response,
    extract_markdown,
)

_MOCK_TARGET = "fact_layer.core.scanner.extractors.markdown._anthropic_mod"


def _mock_context(**overrides) -> ScanContext:
    defaults = {"api_key": "sk-test", "model": "claude-sonnet-4-6"}
    defaults.update(overrides)
    return ScanContext(**defaults)


def _mock_llm_response(candidates=None, unmapped=None) -> str:
    return json.dumps({
        "candidates": candidates or [],
        "unmapped": unmapped or [],
    })


def _patch_llm(response_text: str):
    """Return a context manager that mocks the anthropic module."""
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=response_text)]
    mock_mod = MagicMock()
    mock_mod.Anthropic.return_value.messages.create.return_value = mock_msg
    return patch(_MOCK_TARGET, mock_mod)


class TestExtractMarkdownGuards:
    def test_missing_file(self, tmp_path: Path):
        result = extract_markdown(tmp_path / "nonexistent.md", _mock_context())
        assert result == ExtractResult()

    def test_empty_file(self, tmp_path: Path):
        md = tmp_path / "empty.md"
        md.write_text("")
        result = extract_markdown(md, _mock_context())
        assert result == ExtractResult()

    def test_no_context(self, tmp_path: Path):
        md = tmp_path / "test.md"
        md.write_text("# Hello\n")
        result = extract_markdown(md, None)
        assert result == ExtractResult()

    def test_no_api_key(self, tmp_path: Path):
        md = tmp_path / "test.md"
        md.write_text("# Hello\n")
        result = extract_markdown(md, ScanContext())
        assert result == ExtractResult()


class TestExtractMarkdownLLM:
    def test_successful_extraction(self, tmp_path: Path):
        md = tmp_path / "README.md"
        md.write_text("# My Project\nBuilt with Python 3.12 and FastAPI.\n")

        resp = _mock_llm_response(candidates=[{
            "category": "tech-stack",
            "slot": "framework",
            "value": "FastAPI",
            "confidence": "medium",
            "evidence": "Built with Python 3.12 and FastAPI.",
        }])

        with _patch_llm(resp):
            result = extract_markdown(md, _mock_context())

        assert len(result.candidates) == 1
        assert result.candidates[0].category == "tech-stack"
        assert result.candidates[0].slot == "framework"
        assert result.candidates[0].value == "FastAPI"
        assert result.candidates[0].extractor == "llm-markdown"
        assert result.candidates[0].confidence == "medium"

    def test_extracts_unmapped_facts(self, tmp_path: Path):
        md = tmp_path / "README.md"
        md.write_text("# My Project\nWe follow trunk-based development.\n")

        resp = _mock_llm_response(unmapped=[{
            "fact": "Uses trunk-based development",
            "evidence": "We follow trunk-based development.",
            "suggested_category": "conventions",
            "suggested_slot": "branching-strategy",
        }])

        with _patch_llm(resp):
            result = extract_markdown(md, _mock_context())

        assert len(result.unmapped) == 1
        assert result.unmapped[0].fact == "Uses trunk-based development"
        assert result.unmapped[0].evidence == "We follow trunk-based development."
        assert result.unmapped[0].suggested_category == "conventions"

    def test_api_failure_returns_empty(self, tmp_path: Path):
        md = tmp_path / "README.md"
        md.write_text("# My Project\n")

        mock_mod = MagicMock()
        mock_mod.Anthropic.side_effect = Exception("API down")

        with patch(_MOCK_TARGET, mock_mod):
            result = extract_markdown(md, _mock_context())

        assert result == ExtractResult()

    def test_malformed_response_returns_empty(self, tmp_path: Path):
        md = tmp_path / "README.md"
        md.write_text("# My Project\n")

        with _patch_llm("not valid json at all"):
            result = extract_markdown(md, _mock_context())

        assert result == ExtractResult()

    def test_evidence_populated(self, tmp_path: Path):
        md = tmp_path / "README.md"
        md.write_text("# My Project\nUses PostgreSQL 16.\n")

        resp = _mock_llm_response(candidates=[{
            "category": "tech-stack",
            "slot": "database",
            "value": "PostgreSQL 16",
            "confidence": "medium",
            "evidence": "Uses PostgreSQL 16.",
        }])

        with _patch_llm(resp):
            result = extract_markdown(md, _mock_context())

        assert result.candidates[0].evidence == "Uses PostgreSQL 16."

    def test_high_confidence_clamped_to_medium(self, tmp_path: Path):
        md = tmp_path / "README.md"
        md.write_text("# My Project\n")

        resp = _mock_llm_response(candidates=[{
            "category": "tech-stack",
            "slot": "language",
            "value": "Python",
            "confidence": "high",
            "evidence": "test",
        }])

        with _patch_llm(resp):
            result = extract_markdown(md, _mock_context())

        assert result.candidates[0].confidence == "medium"


class TestParseExtractionResponse:
    def test_strips_markdown_fences(self):
        raw = '```json\n{"candidates": [], "unmapped": []}\n```'
        result = _parse_extraction_response(raw, "test.md")
        assert result.candidates == []
        assert result.unmapped == []

    def test_skips_invalid_candidates(self):
        raw = json.dumps({"candidates": [
            {"category": "tech-stack"},
            {"category": "tech-stack", "slot": "lang", "value": "Python", "evidence": "test"},
        ], "unmapped": []})
        result = _parse_extraction_response(raw, "test.md")
        assert len(result.candidates) == 1

    def test_skips_empty_unmapped_fact(self):
        raw = json.dumps({"candidates": [], "unmapped": [
            {"fact": "", "evidence": "test"},
            {"fact": "real fact", "evidence": "test"},
        ]})
        result = _parse_extraction_response(raw, "test.md")
        assert len(result.unmapped) == 1


class TestBuildPromptHelpers:
    def test_slot_definitions_no_framework(self):
        ctx = ScanContext()
        result = _build_slot_definitions(ctx)
        assert "No framework loaded" in result

    def test_filled_slots_none(self):
        ctx = ScanContext()
        result = _build_filled_slots(ctx)
        assert result == "None."
