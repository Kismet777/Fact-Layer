# src/fact_layer/core/scanner/dedup.py
"""Deduplication and conflict detection for scan candidates."""

from __future__ import annotations

from collections import defaultdict

from fact_layer.core.scanner.candidates import ConflictGroup, SlotCandidate

_CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}

_EXTRACTOR_RANK = {"config-parser": 2, "ast-analyzer": 1, "llm-markdown": 0}


def _normalize_value(value) -> str:
    if isinstance(value, list):
        return str(sorted(str(v) for v in value))
    return str(value).strip().lower()


def _merge_group(candidates: list[SlotCandidate]) -> SlotCandidate:
    best = max(candidates, key=lambda c: (
        _EXTRACTOR_RANK.get(c.extractor, -1),
        _CONFIDENCE_RANK.get(c.confidence, -1),
    ))
    merged_sources = " | ".join(c.source for c in candidates)
    best_confidence = max(
        (c.confidence for c in candidates),
        key=lambda c: _CONFIDENCE_RANK.get(c, -1),
    )
    return SlotCandidate(
        category=best.category,
        slot=best.slot,
        value=best.value,
        confidence=best_confidence,
        source=merged_sources,
        extractor=best.extractor,
        evidence=best.evidence,
    )


def deduplicate(
    candidates: list[SlotCandidate],
) -> tuple[list[SlotCandidate], list[ConflictGroup]]:
    if not candidates:
        return [], []

    by_slot: dict[str, list[SlotCandidate]] = defaultdict(list)
    for c in candidates:
        by_slot[c.slot_ref].append(c)

    merged: list[SlotCandidate] = []
    conflicts: list[ConflictGroup] = []

    for slot_ref, group in by_slot.items():
        by_value: dict[str, list[SlotCandidate]] = defaultdict(list)
        for c in group:
            by_value[_normalize_value(c.value)].append(c)

        if len(by_value) == 1:
            merged.append(_merge_group(group))
        else:
            conflicts.append(ConflictGroup(slot_ref=slot_ref, candidates=group))

    return merged, conflicts
