from __future__ import annotations

import importlib.resources
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from fact_layer.core.exporter import render_export
from fact_layer.core.loader import load_all_categories, load_dependencies
from fact_layer.models.dependency import DependencyGraph
from fact_layer.models.slot import ACTIVE_STATUSES


class AuditFix(BaseModel):
    slot: str
    value: Any = None


class AuditFinding(BaseModel):
    severity: str
    type: str
    slots: list[str] = []
    description: str
    suggestion: str = ""
    fixes: list[AuditFix] = []


class AuditResult(BaseModel):
    findings: list[AuditFinding] = []
    summary: str = ""
    raw_response: str = ""
    error: str | None = None


def _load_prompt_template() -> str:
    tmpl_path = Path(str(importlib.resources.files("fact_layer") / "templates" / "audit_prompt.txt"))
    return tmpl_path.read_text(encoding="utf-8")


def format_dependency_graph(graph: DependencyGraph) -> str:
    if not graph.static:
        return "No dependency rules defined."
    lines = []
    for rule in graph.static:
        for t in rule.targets:
            lines.append(f"- {rule.source} --[{t.type}]--> {t.slot}")
    return "\n".join(lines)


def format_decisions(categories: dict) -> str:
    dec_cat = categories.get("decisions")
    if not dec_cat or not dec_cat.slots:
        return "No active decisions."
    lines = []
    for slot_id, sv in dec_cat.slots.items():
        if sv.meta.status not in ACTIVE_STATUSES:
            continue
        raw = sv.value
        if not isinstance(raw, dict) or raw.get("status") != "active":
            continue
        title = raw.get("title", slot_id)
        affected = raw.get("affected-slots", [])
        rationale = raw.get("rationale", "")
        lines.append(f"- {slot_id.upper()}: {title}")
        if rationale:
            lines.append(f"  Rationale: {rationale}")
        if affected:
            lines.append(f"  Affects: {', '.join(affected)}")
    return "\n".join(lines) if lines else "No active decisions."


def build_audit_prompt(facts_dir: Path) -> str:
    facts_md = render_export(facts_dir)
    graph = load_dependencies(facts_dir)
    categories = load_all_categories(facts_dir)

    template = _load_prompt_template()
    return template.format(
        facts_markdown=facts_md,
        dependency_graph=format_dependency_graph(graph),
        decisions=format_decisions(categories),
    )


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def run_audit(
    facts_dir: Path,
    model: str | None = None,
    api_key: str | None = None,
) -> AuditResult:
    prompt = build_audit_prompt(facts_dir)

    from fact_layer.core.llm import llm_call

    # One retry when the model returns something we can't parse as JSON — a
    # transient malformed response shouldn't fail the whole audit.
    result: AuditResult | None = None
    for _ in range(2):
        try:
            # Reasoning models (deepseek-v4-*) spend the early token budget on
            # chain-of-thought; give enough room for the final JSON to land in
            # `content` rather than truncating mid-reasoning.
            raw = llm_call(
                prompt, role="audit", model=model, api_key=api_key, max_tokens=8000
            )
        except Exception as e:
            return AuditResult(error=f"API call failed: {e}", raw_response="")
        result = _parse_response(raw)
        if result.error is None:
            return result
    return result if result is not None else AuditResult(error="Audit failed")


def _parse_response(raw: str) -> AuditResult:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(lines).strip()

    data = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        import re

        match = re.search(r'\{[\s\S]*"findings"[\s\S]*\}', raw)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                pass

    if data is None:
        return AuditResult(
            findings=[],
            summary="",
            raw_response=raw,
            error="Could not parse LLM response as JSON. Raw response shown below.",
        )

    findings: list[AuditFinding] = []
    for f in data.get("findings", []):
        try:
            findings.append(AuditFinding(**f))
        except Exception:
            continue

    return AuditResult(
        findings=findings,
        summary=data.get("summary", ""),
        raw_response=raw,
    )
