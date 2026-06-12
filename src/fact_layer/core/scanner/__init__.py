# src/fact_layer/core/scanner/__init__.py
from fact_layer.core.scanner.candidates import (
    ConflictGroup,
    ScanResult,
    ScanStats,
    SlotCandidate,
    UnmappedFact,
)

__all__ = [
    "ConflictGroup",
    "ScanResult",
    "ScanStats",
    "SlotCandidate",
    "UnmappedFact",
]
