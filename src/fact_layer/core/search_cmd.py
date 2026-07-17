"""FL-021 L1: facts_search — content-based fact discovery.

The "search less by exporting less" half of anti-pollution: find a fact by its
content without dumping the full export or pre-knowing its ``category.slot-id``.

Pure retrieval, on purpose (philosophy 原则 2 & 7): it stores nothing and infers
nothing. A slot matches iff the query literally appears in its searchable text —
offline substring, case-insensitive, deterministic, auditable. No embeddings, no
similarity ranking (those would be a stored derived artifact + soft inference).

Searchable fields are exactly {slot-id, flattened value, reason}. Category is a
*filter* (``category=``), not a searchable field — searching a category name and
getting all its slots is noise, that's what ``facts_list`` is for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from fact_layer.core.loader import load_all_categories, load_framework
from fact_layer.core.registry import get_enabled_categories
from fact_layer.models.slot import ACTIVE_STATUSES, is_empty_value

DEFAULT_LIMIT = 20


class SearchHit(BaseModel):
    slot_ref: str
    category: str
    slot_id: str
    status: str
    matched_fields: list[str]
    value: str
    reason: str | None = None


class SearchResult(BaseModel):
    query: str
    hits: list[SearchHit]
    truncated: bool = False


def _flatten_value(value: Any) -> str:
    """Flatten a slot value to searchable text (keys included).

    Dict keys are kept so decision sub-fields like ``affected-slots`` are findable;
    lists/dicts are recursed. Mirrors the human display closely enough for search
    while never dropping content.
    """
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            parts.append(str(k))
            parts.append(_flatten_value(v))
        return " ".join(parts)
    if isinstance(value, list):
        return " ".join(_flatten_value(v) for v in value)
    return str(value)


def _format_value(value: Any) -> str:
    """Human-readable rendering of the value for the returned hit.

    Kept in sync with exporter._format_value so a search hit reads like export.
    """
    if isinstance(value, list):
        if not value:
            return ""
        return "\n".join(f"- {item}" for item in value)
    if isinstance(value, dict):
        return "\n".join(f"- **{k}:** {v}" for k, v in value.items())
    return str(value) if value else ""


def _matches(text: str, query: str, tokens: list[str]) -> bool:
    """Substring match: whole query as one run, OR every token present (AND)."""
    if query and query in text:
        return True
    return bool(tokens) and all(t in text for t in tokens)


def _rank(slot_id: str, value_text: str, reason_text: str, query: str, tokens: list[str]) -> int:
    """Lower is better. Tier by the strongest field the query hits."""
    if slot_id == query:
        return 0
    if _matches(slot_id, query, tokens):
        return 1
    if _matches(value_text, query, tokens):
        return 2
    if _matches(reason_text, query, tokens):
        return 3
    return 4  # matched only via joined text (tokens split across fields)


def _matched_fields(
    slot_id: str, value_text: str, reason_text: str, query: str, tokens: list[str]
) -> list[str]:
    fields = []
    for name, text in (("slot-id", slot_id), ("value", value_text), ("reason", reason_text)):
        if _matches(text, query, tokens):
            fields.append(name)
    if fields:
        return fields
    # cross-field-only hit: report fields where any token (or the query) appears,
    # so matched_fields is never empty when the slot matched.
    for name, text in (("slot-id", slot_id), ("value", value_text), ("reason", reason_text)):
        if (query and query in text) or any(t in text for t in tokens):
            fields.append(name)
    return fields


def compute_search(
    facts_dir: Path,
    query: str,
    *,
    category: str | None = None,
    include_stale: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> SearchResult:
    """Search slots by content. Pure function — no side effects, no logging.

    Args:
        query: search string. Empty/whitespace → no hits.
        category: restrict to a single category (filter, not a searched field).
        include_stale: also search stale/superseded slots (default active-only).
        limit: max hits returned; ``truncated`` flags when more matched.
    """
    q = query.strip().lower()
    tokens = q.split()
    if not q:
        return SearchResult(query=query, hits=[])

    config = load_framework(facts_dir)
    categories = load_all_categories(facts_dir)
    enabled = get_enabled_categories(config)

    scored: list[tuple[int, str, SearchHit]] = []
    for cat_name, cat in categories.items():
        if cat_name not in enabled:
            continue
        if category is not None and cat_name != category:
            continue
        for slot_id, sv in cat.slots.items():
            if not include_stale and sv.meta.status not in ACTIVE_STATUSES:
                continue
            if is_empty_value(sv.value):
                continue

            slot_id_text = slot_id.lower()
            value_text = _flatten_value(sv.value).lower()
            reason_text = (sv.meta.reason or "").lower()
            joined = f"{slot_id_text}\n{value_text}\n{reason_text}"

            if not _matches(joined, q, tokens):
                continue

            rank = _rank(slot_id_text, value_text, reason_text, q, tokens)
            slot_ref = f"{cat_name}.{slot_id}"
            hit = SearchHit(
                slot_ref=slot_ref,
                category=cat_name,
                slot_id=slot_id,
                status=sv.meta.status,
                matched_fields=_matched_fields(slot_id_text, value_text, reason_text, q, tokens),
                value=_format_value(sv.value),
                reason=sv.meta.reason,
            )
            scored.append((rank, slot_ref, hit))

    scored.sort(key=lambda t: (t[0], t[1]))
    truncated = len(scored) > limit
    hits = [h for _, _, h in scored[:limit]]
    return SearchResult(query=query, hits=hits, truncated=truncated)
