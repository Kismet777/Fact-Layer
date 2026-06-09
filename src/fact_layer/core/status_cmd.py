from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel

from fact_layer.core.loader import load_all_categories, load_framework
from fact_layer.core.registry import get_enabled_categories, get_stale_threshold
from fact_layer.models.category import CategoryFile
from fact_layer.models.framework import CategoryDef, FrameworkConfig


class CategoryStatus(BaseModel):
    name: str
    tier: str
    filled: int
    total: int
    stale_count: int
    last_verified_days: int | None
    has_required_missing: bool
    is_empty: bool
    active_decisions: int | None = None


class FactsStatus(BaseModel):
    categories: list[CategoryStatus]
    total_filled: int
    total_slots: int
    total_stale: int
    empty_categories: int


def compute_status(facts_dir: Path, today: date | None = None) -> FactsStatus:
    if today is None:
        today = date.today()

    config = load_framework(facts_dir)
    categories = load_all_categories(facts_dir)
    enabled = get_enabled_categories(config)

    result: list[CategoryStatus] = []

    for cat_name, cat_def in enabled.items():
        cat = categories.get(cat_name)

        if cat is None or not cat.slots:
            result.append(CategoryStatus(
                name=cat_name,
                tier=cat_def.tier,
                filled=0,
                total=0,
                stale_count=0,
                last_verified_days=None,
                has_required_missing=bool(cat_def.required_slots),
                is_empty=True,
            ))
            continue

        if cat_name == "decisions":
            active_decisions = sum(
                1 for sv in cat.slots.values()
                if sv.meta.status in ("active", "uncertain")
                and isinstance(sv.value, dict)
                and sv.value.get("status") == "active"
            )
            result.append(CategoryStatus(
                name=cat_name,
                tier=cat_def.tier,
                filled=active_decisions,
                total=active_decisions,
                stale_count=0,
                last_verified_days=None,
                has_required_missing=False,
                is_empty=active_decisions == 0,
                active_decisions=active_decisions,
            ))
            continue

        total = len(cat.slots)
        filled = 0
        stale_count = 0
        latest_verified: date | None = None
        threshold = get_stale_threshold(config, cat_def.tier)

        for slot_id, sv in cat.slots.items():
            if sv.meta.status not in ("active", "uncertain"):
                continue
            if sv.value is not None and sv.value != "" and sv.value != []:
                filled += 1
            if threshold and (today - sv.meta.verified).days > threshold:
                stale_count += 1
            if latest_verified is None or sv.meta.verified > latest_verified:
                latest_verified = sv.meta.verified

        last_verified_days = (today - latest_verified).days if latest_verified else None

        has_required_missing = False
        for req in cat_def.required_slots:
            if req not in cat.slots:
                has_required_missing = True
                break
            sv = cat.slots[req]
            if sv.value is None or sv.value == "" or sv.value == []:
                has_required_missing = True
                break

        result.append(CategoryStatus(
            name=cat_name,
            tier=cat_def.tier,
            filled=filled,
            total=total,
            stale_count=stale_count,
            last_verified_days=last_verified_days,
            has_required_missing=has_required_missing,
            is_empty=filled == 0,
        ))

    tier_order = {"stable": 0, "dynamic": 1, "working": 2}
    result.sort(key=lambda c: (tier_order.get(c.tier, 99), c.name))

    return FactsStatus(
        categories=result,
        total_filled=sum(c.filled for c in result),
        total_slots=sum(c.total for c in result),
        total_stale=sum(c.stale_count for c in result),
        empty_categories=sum(1 for c in result if c.is_empty),
    )
