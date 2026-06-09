from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from fact_layer.core.loader import load_all_categories, load_dependencies, load_framework
from fact_layer.core.registry import get_enabled_categories
from fact_layer.models.dependency import DependencyGraph


class ImpactTarget(BaseModel):
    slot: str
    relation_type: str
    is_strong: bool


class DecisionRef(BaseModel):
    decision_id: str
    title: str


class ImpactResult(BaseModel):
    slot: str
    targets: list[ImpactTarget]
    decisions: list[DecisionRef]
    slot_exists: bool


def compute_impact(facts_dir: Path, slot_ref: str) -> ImpactResult:
    config = load_framework(facts_dir)
    categories = load_all_categories(facts_dir)
    graph = load_dependencies(facts_dir)
    enabled = get_enabled_categories(config)
    enabled_cats = set(enabled.keys())

    parts = slot_ref.split(".", 1)
    slot_exists = False
    if len(parts) == 2:
        cat_name, slot_id = parts
        cat = categories.get(cat_name)
        if cat and slot_id in cat.slots:
            slot_exists = True

    targets: list[ImpactTarget] = []
    for rule in graph.static:
        if rule.source == slot_ref:
            for t in rule.targets:
                target_cat = t.slot.split(".")[0]
                if target_cat not in enabled_cats:
                    continue
                is_strong = t.type in ("derives-from", "references")
                targets.append(ImpactTarget(
                    slot=t.slot,
                    relation_type=t.type,
                    is_strong=is_strong,
                ))

    targets.sort(key=lambda t: (not t.is_strong, t.slot))

    decisions: list[DecisionRef] = []
    dec_cat = categories.get("decisions")
    if dec_cat and "decisions" in enabled_cats:
        for slot_id, sv in dec_cat.slots.items():
            if sv.meta.status not in ("active", "uncertain"):
                continue
            raw = sv.value
            if not isinstance(raw, dict) or raw.get("status") != "active":
                continue
            affected = raw.get("affected-slots", [])
            if slot_ref in affected:
                decisions.append(DecisionRef(
                    decision_id=slot_id.upper(),
                    title=raw.get("title", slot_id),
                ))

    return ImpactResult(
        slot=slot_ref,
        targets=targets,
        decisions=decisions,
        slot_exists=slot_exists,
    )
