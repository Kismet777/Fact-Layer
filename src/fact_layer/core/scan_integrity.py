# src/fact_layer/core/scan_integrity.py
"""Rule-based integrity checks for scan indexes vs canonical facts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from fact_layer.core.loader import load_all_categories
from fact_layer.core.scanner.indexes import (
    load_extraction_index,
    load_source_index,
)


class IntegrityFinding(BaseModel):
    severity: Literal["error", "warning"]
    type: str
    description: str
    details: dict[str, Any] = {}


class IntegrityResult(BaseModel):
    findings: list[IntegrityFinding] = []
    summary: str = ""


def run_scan_integrity(facts_dir: Path) -> IntegrityResult:
    src_index = load_source_index(facts_dir)
    ext_index = load_extraction_index(facts_dir)
    categories = load_all_categories(facts_dir)

    findings: list[IntegrityFinding] = []

    _check_orphaned_extractions(src_index.sources, ext_index.extractions, findings)
    _check_stale_sources(src_index.sources, findings)
    _check_value_mismatch(ext_index.extractions, categories, findings)
    _check_cross_source_conflicts(ext_index.extractions, findings)

    n_err = sum(1 for f in findings if f.severity == "error")
    n_warn = sum(1 for f in findings if f.severity == "warning")
    summary = f"{n_err} errors, {n_warn} warnings" if findings else "All indexes consistent."

    return IntegrityResult(findings=findings, summary=summary)


def _check_orphaned_extractions(sources, extractions, findings):
    source_ids = set(sources.keys())
    for eid, ext in extractions.items():
        if ext.source_id not in source_ids:
            findings.append(IntegrityFinding(
                severity="error",
                type="orphaned_extraction",
                description=f"Extraction {eid} references missing source {ext.source_id}",
                details={"extraction_id": eid, "source_id": ext.source_id},
            ))


def _check_stale_sources(sources, findings):
    for sid, entry in sources.items():
        if entry.status == "stale":
            findings.append(IntegrityFinding(
                severity="warning",
                type="stale_source",
                description=f"Source {sid} ({entry.path}) is stale — content changed since last scan",
                details={"source_id": sid, "path": entry.path},
            ))


def _check_value_mismatch(extractions, categories, findings):
    for eid, ext in extractions.items():
        if ext.status != "active":
            continue
        parts = ext.slot_ref.split(".", 1)
        if len(parts) != 2:
            continue
        cat_name, slot_id = parts
        cat = categories.get(cat_name)
        if not cat:
            continue
        slot_value = cat.slots.get(slot_id)
        if not slot_value or slot_value.value is None:
            continue


def _check_cross_source_conflicts(extractions, findings):
    active_by_slot: dict[str, list[tuple[str, Any]]] = {}
    for eid, ext in extractions.items():
        if ext.status != "active":
            continue
        active_by_slot.setdefault(ext.slot_ref, []).append((eid, ext))

    for slot_ref, entries in active_by_slot.items():
        if len(entries) <= 1:
            continue
        source_ids = {ext.source_id for _, ext in entries}
        if len(source_ids) > 1:
            findings.append(IntegrityFinding(
                severity="warning",
                type="cross_source_conflict",
                description=f"Slot {slot_ref} has active extractions from {len(source_ids)} different sources",
                details={
                    "slot_ref": slot_ref,
                    "extraction_ids": [eid for eid, _ in entries],
                    "source_ids": list(source_ids),
                },
            ))
