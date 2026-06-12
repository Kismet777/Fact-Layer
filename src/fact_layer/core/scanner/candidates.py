# src/fact_layer/core/scanner/candidates.py
"""Data models for the scan pipeline."""

from __future__ import annotations

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
