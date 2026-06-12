from __future__ import annotations

import importlib.resources
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from fact_layer.core.loader import load_all_categories, load_dependencies, load_framework
from fact_layer.core.registry import get_enabled_categories
from fact_layer.models.category import CategoryFile
from fact_layer.models.dependency import DependencyGraph
from fact_layer.models.framework import CategoryDef, FrameworkConfig
from fact_layer.models.slot import ACTIVE_STATUSES, is_empty_value


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
        if slot_val.meta.status not in ACTIVE_STATUSES:
            continue
        raw = slot_val.value
        if is_empty_value(raw):
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
        if slot_val.meta.status not in ACTIVE_STATUSES:
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
    return _render_context(ctx)


def _render_context(ctx: dict) -> str:
    templates_dir = Path(str(importlib.resources.files("fact_layer") / "templates"))
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("export.md.j2")
    return template.render(**ctx)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _compute_indegree(graph: DependencyGraph) -> dict[str, int]:
    indegree: dict[str, int] = {}
    for rule in graph.static:
        for target in rule.targets:
            indegree[target.slot] = indegree.get(target.slot, 0) + 1
    return indegree


def _score_slot(
    slot_ref: str,
    tier: str,
    is_required: bool,
    updated: date | None,
    indegree: dict[str, int],
    today: date,
) -> float:
    score = 0.0
    score += indegree.get(slot_ref, 0) * 10
    tier_scores = {"stable": 30, "dynamic": 20, "working": 10}
    score += tier_scores.get(tier, 0)
    if is_required:
        score += 15
    if updated:
        days_since = (today - updated).days
        score += max(0, 10 - days_since)
    return score


def build_budgeted_context(
    facts_dir: Path,
    budget_tokens: int,
    max_decisions: int = 10,
) -> tuple[dict, int]:
    """Build export context trimmed to fit within a token budget.

    Returns (context_dict, omitted_count).
    """
    config = load_framework(facts_dir)
    categories = load_all_categories(facts_dir)
    graph = load_dependencies(facts_dir)
    enabled = get_enabled_categories(config)
    indegree = _compute_indegree(graph)
    today = date.today()

    required_slots: set[str] = set()
    for cat_name, cat_def in enabled.items():
        for req in cat_def.required_slots:
            required_slots.add(f"{cat_name}.{req}")

    full_ctx = build_export_context(facts_dir, max_decisions)

    scored_sections: list[tuple[float, int, dict]] = []
    for idx, section in enumerate(full_ctx["sections"]):
        cat_name = section["category"]
        cat = categories.get(cat_name)
        tier = section["tier"]

        if section["is_decisions"]:
            best_score = {"stable": 30, "dynamic": 20, "working": 10}.get(tier, 0)
            scored_sections.append((best_score, idx, section))
            continue

        slot_scores: list[tuple[float, dict]] = []
        for slot_dict in section.get("slots", []):
            display_name = slot_dict["name"]
            slot_id = display_name.lower().replace(" ", "-")
            slot_ref = f"{cat_name}.{slot_id}"
            updated = None
            if cat and slot_id in cat.slots:
                updated = cat.slots[slot_id].meta.updated
            s = _score_slot(slot_ref, tier, slot_ref in required_slots, updated, indegree, today)
            slot_scores.append((s, slot_dict))

        slot_scores.sort(key=lambda x: x[0], reverse=True)
        section["_scored_slots"] = slot_scores
        best = slot_scores[0][0] if slot_scores else 0
        scored_sections.append((best, idx, section))

    scored_sections.sort(key=lambda x: x[0], reverse=True)

    header_text = f"# Project Facts Snapshot\nGenerated: ...\n\n"
    used_tokens = _estimate_tokens(header_text)
    kept_sections: list[dict] = []
    total_omitted = 0

    for _, _, section in scored_sections:
        section_header = f"## {section['title']}\n"
        header_cost = _estimate_tokens(section_header)

        if section["is_decisions"]:
            section_text = ""
            for dec in section.get("decisions", []):
                line = f"- {dec['id']} ({dec['date']}, {dec['status']}): {dec['title']}"
                if dec.get("rationale"):
                    line += f" — {dec['rationale']}"
                section_text += line + "\n"
            cost = header_cost + _estimate_tokens(section_text)
            if used_tokens + cost <= budget_tokens:
                used_tokens += cost
                kept_sections.append(section)
            else:
                total_omitted += len(section.get("decisions", []))
            continue

        scored_slots = section.get("_scored_slots", [])
        kept_slots = []
        section_started = False

        for _, slot_dict in scored_slots:
            slot_text = f"**{slot_dict['name']}:** {slot_dict['value']}\n"
            slot_cost = _estimate_tokens(slot_text)
            needed = (header_cost if not section_started else 0) + slot_cost
            if used_tokens + needed <= budget_tokens:
                if not section_started:
                    used_tokens += header_cost
                    section_started = True
                used_tokens += slot_cost
                kept_slots.append(slot_dict)
            else:
                total_omitted += 1

        if kept_slots:
            new_section = dict(section)
            new_section["slots"] = kept_slots
            new_section.pop("_scored_slots", None)
            kept_sections.append(new_section)

    kept_sections.sort(key=lambda s: (
        TIER_ORDER.get(s["tier"], 99),
        CATEGORY_ORDER.index(s["category"]) if s["category"] in CATEGORY_ORDER else 99,
    ))

    ctx = {
        "generated_at": full_ctx["generated_at"],
        "project_name": full_ctx["project_name"],
        "sections": kept_sections,
    }
    return ctx, total_omitted


def render_export_budgeted(
    facts_dir: Path,
    budget_tokens: int,
    max_decisions: int = 10,
) -> str:
    ctx, omitted = build_budgeted_context(facts_dir, budget_tokens, max_decisions)
    md = _render_context(ctx)
    if omitted > 0:
        md += f"\n[truncated: {omitted} items omitted due to token budget]\n"
    return md
