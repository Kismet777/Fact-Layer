# src/fact_layer/core/scanner/__init__.py
from fact_layer.core.scanner.candidates import (
    ConflictGroup,
    ExtractResult,
    ScanContext,
    ScanResult,
    ScanStats,
    SlotCandidate,
    UnmappedFact,
)
from fact_layer.core.scanner.dedup import deduplicate
from fact_layer.core.scanner.indexes import (
    ExtractionEntry,
    ExtractionIndex,
    SourceEntry,
    SourceIndex,
    load_extraction_index,
    load_source_index,
    save_extraction_index,
    save_source_index,
)
from fact_layer.core.scanner.pipeline import run_scan

__all__ = [
    "ConflictGroup",
    "ExtractResult",
    "ExtractionEntry",
    "ExtractionIndex",
    "ScanContext",
    "ScanResult",
    "ScanStats",
    "SlotCandidate",
    "SourceEntry",
    "SourceIndex",
    "UnmappedFact",
    "deduplicate",
    "load_extraction_index",
    "load_source_index",
    "run_scan",
    "save_extraction_index",
    "save_source_index",
]
