# src/fact_layer/core/scanner/__init__.py
from fact_layer.core.scanner.candidates import (
    ConflictGroup,
    ScanResult,
    ScanStats,
    SlotCandidate,
    UnmappedFact,
)
from fact_layer.core.scanner.dedup import deduplicate

__all__ = [
    "ConflictGroup",
    "ScanResult",
    "ScanStats",
    "SlotCandidate",
    "UnmappedFact",
    "deduplicate",
]
