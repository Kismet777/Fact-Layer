from __future__ import annotations

import importlib.resources
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from fact_layer.core.loader import load_all_categories, load_framework
from fact_layer.core.registry import get_enabled_categories
from fact_layer.models.category import CategoryFile


CATEGORY_TITLES = {
    "project-overview": "Project Overview",
    "tech-stack": "Tech Stack",
    "architecture": "Architecture",
    "conventions": "Conventions",
    "work-in-progress": "Current Work",
    "decisions": "Recent Decisions",
    "data-model": "Data Model",
    "api-contracts": "API Contracts",
    "testing": "Testing",
    "build-deploy": "Build & Deploy",
    "security": "Security",
}

TIER_ORDER = {"stable": 0, "dynamic": 1, "working": 2}

CATEGORY_ORDER = [
    "project-overview",
    "tech-stack",
    "architecture",
    "conventions",
    "work-in-progress",
    "decisions",
    "data-model",
    "api-contracts",
    "testing",
    "build-deploy",
    "security",
]


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return ""
        return "\n".join(f"- {item}" for item in value)
    if isinstance(value, dict):
        return "\n".join(f"- **{k}:** {v}" for k, v in value.items())
    return str(value) if value else ""


def _slot_display_name(slot_id: str) -> str:
    return slot_id.replace("-", " ").replace("_", " ").title()


def _extract_active_slots(cat: CategoryFile) -> list[dict]:
    """Extract only active slots with non-empty values."""
    result = []
    for slot_id, slot_val in cat.slots.items():
        if slot_val.meta.status not in ("active", "uncertain"):
            continue
        raw = slot_val.value
        if raw is None or raw == "" or raw == []:
            continue
        formatted = _format_value(raw)
        if not formatted:
            continue
        entry: dict[str, Any] = {
            "name": _slot_display_name(slot_id),
            "value": formatted,
            "is_list": isinstance(raw, (list, dict)),
        }
        if slot_val.meta.reason:
            entry["reason"] = slot_val.meta.reason
        result.append(entry)
    return result


def _extract_decisions(cat: CategoryFile, max_count: int = 10) -> list[dict]:
    """Extract active decisions in a compact format."""
    decisions = []
    for slot_id, slot_val in cat.slots.items():
        if slot_val.meta.status not in ("active", "uncertain"):
            continue
        raw = slot_val.value
        if not raw or not isinstance(raw, dict):
            continue
        title = raw.get("title", slot_id)
        date_str = raw.get("date", str(slot_val.meta.updated))
        status = raw.get("status", "active")
        rationale = raw.get("rationale", "")
        decisions.append({
            "id": slot_id.upper(),
            "date": date_str,
            "status": status,
            "title": title,
            "rationale": rationale,
        })
    decisions.sort(key=lambda d: d["date"], reverse=True)
    return decisions[:max_count]


def build_export_context(facts_dir: Path, max_decisions: int = 10) -> dict:
    """Build the template context dict from .facts/ directory."""
    config = load_framework(facts_dir)
    categories = load_all_categories(facts_dir)
    enabled = get_enabled_categories(config)

    sections = []
    for cat_name in CATEGORY_ORDER:
        if cat_name not in categories or cat_name not in enabled:
            continue
        cat = categories[cat_name]
        title = CATEGORY_TITLES.get(cat_name, _slot_display_name(cat_name))

        if cat_name == "decisions":
            decisions = _extract_decisions(cat, max_decisions)
            if not decisions:
                continue
            sections.append({
                "title": title,
                "category": cat_name,
                "tier": cat.tier,
                "is_decisions": True,
                "decisions": decisions,
            })
        else:
            slots = _extract_active_slots(cat)
            if not slots:
                continue
            sections.append({
                "title": title,
                "category": cat_name,
                "tier": cat.tier,
                "is_decisions": False,
                "slots": slots,
            })

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project_name": config.project_name,
        "sections": sections,
    }


def render_export(facts_dir: Path, max_decisions: int = 10) -> str:
    """Render the full markdown export."""
    ctx = build_export_context(facts_dir, max_decisions)
    templates_dir = Path(str(importlib.resources.files("fact_layer") / "templates"))
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("export.md.j2")
    return template.render(**ctx)
