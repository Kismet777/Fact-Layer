# src/fact_layer/core/scanner/candidates.py
"""Data models for the scan pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


class SlotCandidate(BaseModel):
    """A candidate fact extracted from a source file."""

    category: str
    slot: str
    value: Any
    confidence: Literal["high", "medium", "low"]
    source: str
    extractor: str
    evidence: str

    @property
    def slot_ref(self) -> str:
        return f"{self.category}.{self.slot}"


class ConflictGroup(BaseModel):
    """Multiple candidates for the same slot with conflicting values."""

    slot_ref: str
    candidates: list[SlotCandidate]


class UnmappedFact(BaseModel):
    """A fact found in source that doesn't map to any existing slot."""

    fact: str
    source: str
    suggested_category: str | None = None
    suggested_slot: str | None = None
    evidence: str = ""


class ScanContext(BaseModel):
    """Runtime context passed to all extractors."""

    facts_dir: Path | None = None
    framework: Any = None
    categories: dict[str, Any] | None = None
    api_key: str | None = None
    model: str = "claude-sonnet-4-6"


class ExtractResult(BaseModel):
    """Output of an extractor: mapped candidates + unmapped facts."""

    candidates: list[SlotCandidate] = []
    unmapped: list[UnmappedFact] = []


class ScanStats(BaseModel):
    files_scanned: int
    candidates_found: int
    conflicts: int
    unmapped: int


class ScanResult(BaseModel):
    """Complete output of a scan pipeline run."""

    candidates: list[SlotCandidate]
    conflicts: list[ConflictGroup]
    unmapped: list[UnmappedFact]
    stats: ScanStats
