from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from ruamel.yaml import YAML

from fact_layer.core.checker import CheckIssue, run_check
from fact_layer.core.impact_cmd import ImpactResult, compute_impact
from fact_layer.core.loader import load_framework
from fact_layer.core.registry import get_enabled_categories, resolve_facts_dir

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.default_flow_style = False


def load_yaml_roundtrip(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return _yaml.load(f)


def save_yaml_roundtrip(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        _yaml.dump(data, f)


def parse_value(raw: str, *, force_json: bool = False) -> Any:
    if force_json:
        return json.loads(raw)
    if raw.startswith("[") or raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return raw


def _parse_slot_ref(slot_ref: str) -> tuple[str, str]:
    parts = slot_ref.split(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid slot reference '{slot_ref}'. Expected format: category.slot-id")
    return parts[0], parts[1]


def _resolve_category_path(facts_dir: Path, category: str) -> Path:
    return facts_dir / "canonical" / f"{category}.yaml"


def _validate_category_enabled(facts_dir: Path, category: str) -> None:
    config = load_framework(facts_dir)
    enabled = get_enabled_categories(config)
    if category not in enabled:
        raise ValueError(f"Category '{category}' is not enabled")


def _today_str() -> str:
    return date.today().isoformat()


class SetResult(BaseModel):
    slot_ref: str
    old_value: Any = None
    new_value: Any = None
    check_issues: list[CheckIssue] = []
    impact: ImpactResult | None = None


class AddResult(BaseModel):
    category: str
    slot_id: str
    value: Any = None
    check_issues: list[CheckIssue] = []


class DeprecateResult(BaseModel):
    slot_ref: str
    old_status: str
    impact: ImpactResult | None = None


def set_slot(
    facts_dir: Path,
    slot_ref: str,
    value: Any,
    reason: str | None = None,
) -> SetResult:
    cat_name, slot_id = _parse_slot_ref(slot_ref)
    _validate_category_enabled(facts_dir, cat_name)

    cat_path = _resolve_category_path(facts_dir, cat_name)
    if not cat_path.exists():
        raise FileNotFoundError(f"Category file not found: {cat_path}")

    data = load_yaml_roundtrip(cat_path)
    slots = data.get("slots", {})

    if slot_id not in slots:
        raise KeyError(f"Slot '{slot_id}' not found in category '{cat_name}'")

    old_value = slots[slot_id].get("value")

    slots[slot_id]["value"] = value

    meta = slots[slot_id].get("meta", {})
    today = _today_str()
    meta["source"] = "human"
    meta["confidence"] = "high"
    meta["updated"] = today
    meta["verified"] = today
    if reason is not None:
        meta["reason"] = reason
    slots[slot_id]["meta"] = meta

    save_yaml_roundtrip(cat_path, data)

    check_result = run_check(facts_dir, filter_category=cat_name)
    impact_result = compute_impact(facts_dir, slot_ref)

    return SetResult(
        slot_ref=slot_ref,
        old_value=old_value,
        new_value=value,
        check_issues=check_result.issues,
        impact=impact_result,
    )


def add_slot(
    facts_dir: Path,
    category: str,
    slot_id: str,
    value: Any,
    reason: str | None = None,
) -> AddResult:
    _validate_category_enabled(facts_dir, category)

    cat_path = _resolve_category_path(facts_dir, category)
    if not cat_path.exists():
        raise FileNotFoundError(f"Category file not found: {cat_path}")

    data = load_yaml_roundtrip(cat_path)
    slots = data.get("slots", {})

    if slot_id in slots:
        raise KeyError(f"Slot '{slot_id}' already exists in category '{category}'. Use 'fl set' to modify.")

    today = _today_str()
    meta: dict[str, Any] = {
        "source": "human",
        "confidence": "high",
        "status": "active",
        "updated": today,
        "verified": today,
    }
    if reason is not None:
        meta["reason"] = reason

    slots[slot_id] = {"value": value, "meta": meta}
    data["slots"] = slots

    save_yaml_roundtrip(cat_path, data)

    check_result = run_check(facts_dir, filter_category=category)

    return AddResult(
        category=category,
        slot_id=slot_id,
        value=value,
        check_issues=check_result.issues,
    )


def deprecate_slot(
    facts_dir: Path,
    slot_ref: str,
    reason: str | None = None,
) -> DeprecateResult:
    cat_name, slot_id = _parse_slot_ref(slot_ref)
    _validate_category_enabled(facts_dir, cat_name)

    cat_path = _resolve_category_path(facts_dir, cat_name)
    if not cat_path.exists():
        raise FileNotFoundError(f"Category file not found: {cat_path}")

    data = load_yaml_roundtrip(cat_path)
    slots = data.get("slots", {})

    if slot_id not in slots:
        raise KeyError(f"Slot '{slot_id}' not found in category '{cat_name}'")

    meta = slots[slot_id].get("meta", {})
    old_status = meta.get("status", "active")

    meta["status"] = "superseded"
    meta["updated"] = _today_str()
    if reason is not None:
        meta["reason"] = reason
    slots[slot_id]["meta"] = meta

    save_yaml_roundtrip(cat_path, data)

    impact_result = compute_impact(facts_dir, slot_ref)

    return DeprecateResult(
        slot_ref=slot_ref,
        old_status=old_status,
        impact=impact_result,
    )
