from __future__ import annotations

import importlib.resources
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from fact_layer.core.auditor import format_decisions, format_dependency_graph
from fact_layer.core.checker import CheckIssue, Severity, run_check
from fact_layer.core.editor import set_slot
from fact_layer.core.exporter import render_export
from fact_layer.core.loader import load_all_categories, load_dependencies


class Suggestion(BaseModel):
    slot: str
    current_value: Any = None
    suggested_value: Any = None
    reason: str = ""


class SuggestResult(BaseModel):
    suggestions: list[Suggestion] = []
    applied: int = 0
    skipped: int = 0
    error: str | None = None


def _load_suggest_template() -> str:
    tmpl_path = Path(
        str(importlib.resources.files("fact_layer") / "templates" / "suggest_prompt.txt")
    )
    return tmpl_path.read_text(encoding="utf-8")


def format_check_issues(issues: list[CheckIssue]) -> str:
    if not issues:
        return "No issues found."
    lines = []
    for issue in issues:
        severity = "ERROR" if issue.severity == Severity.ERROR else "WARNING"
        line = f"- [{severity}] {issue.message}"
        if issue.detail:
            line += f"\n  Detail: {issue.detail}"
        lines.append(line)
    return "\n".join(lines)


def _resolve_current_value(
    slot_ref: str,
    categories: dict,
) -> Any:
    parts = slot_ref.split(".", 1)
    if len(parts) != 2:
        return None
    cat_name, slot_id = parts
    cat = categories.get(cat_name)
    if not cat or slot_id not in cat.slots:
        return None
    return cat.slots[slot_id].value


def build_suggest_prompt(facts_dir: Path, issues: list[CheckIssue]) -> str:
    facts_md = render_export(facts_dir)
    graph = load_dependencies(facts_dir)
    categories = load_all_categories(facts_dir)

    template = _load_suggest_template()
    return template.format(
        facts_markdown=facts_md,
        dependency_graph=format_dependency_graph(graph),
        decisions=format_decisions(categories),
        check_issues=format_check_issues(issues),
    )


def parse_suggestions(
    raw: str,
    categories: dict,
) -> list[Suggestion]:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [line for line in lines if not line.startswith("```")]
        raw = "\n".join(lines).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    suggestions: list[Suggestion] = []
    for s in data.get("suggestions", []):
        slot = s.get("slot", "")
        if not slot or "." not in slot:
            continue
        current = _resolve_current_value(slot, categories)
        suggestions.append(Suggestion(
            slot=slot,
            current_value=current,
            suggested_value=s.get("suggested_value"),
            reason=s.get("reason", ""),
        ))
    return suggestions


def run_suggest(
    facts_dir: Path,
    model: str = "claude-sonnet-4-6",
    api_key: str | None = None,
    today: date | None = None,
) -> SuggestResult:
    check_result = run_check(facts_dir, today=today)
    if not check_result.issues:
        return SuggestResult(error="No issues found by fl check. Nothing to suggest.")

    prompt = build_suggest_prompt(facts_dir, check_result.issues)

    try:
        from fact_layer.core.llm import llm_call

        raw = llm_call(prompt, model=model, api_key=api_key)
    except Exception as e:
        return SuggestResult(error=f"API call failed: {e}")

    categories = load_all_categories(facts_dir)
    suggestions = parse_suggestions(raw, categories)

    return SuggestResult(suggestions=suggestions)


def apply_suggestion(
    facts_dir: Path,
    suggestion: Suggestion,
    source: str = "agent-analysis",
) -> None:
    result = set_slot(
        facts_dir,
        suggestion.slot,
        suggestion.suggested_value,
        reason=f"fl suggest: {suggestion.reason}",
    )
    cat_path = facts_dir / "canonical" / f"{suggestion.slot.split('.')[0]}.yaml"
    if cat_path.exists():
        from fact_layer.core.editor import load_yaml_roundtrip, save_yaml_roundtrip

        data = load_yaml_roundtrip(cat_path)
        slot_id = suggestion.slot.split(".", 1)[1]
        slots = data.get("slots", {})
        if slot_id in slots:
            slots[slot_id]["meta"]["source"] = source
            save_yaml_roundtrip(cat_path, data)
