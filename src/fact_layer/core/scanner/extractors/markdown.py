# src/fact_layer/core/scanner/extractors/markdown.py
"""Markdown LLM extractor — extracts facts from .md files using an LLM."""

from __future__ import annotations

import importlib.resources
import json
from pathlib import Path
from typing import Any

from fact_layer.core.llm import llm_call
from fact_layer.core.scanner.candidates import (
    ExtractResult,
    ScanContext,
    SlotCandidate,
    UnmappedFact,
)


def _load_template() -> str:
    tmpl_path = Path(
        str(
            importlib.resources.files("fact_layer")
            / "templates"
            / "markdown_extract_prompt.txt"
        )
    )
    return tmpl_path.read_text(encoding="utf-8")


def _build_slot_definitions(context: ScanContext) -> str:
    """Format all available slots from the framework for the prompt."""
    if not context.framework:
        return "No framework loaded."

    lines: list[str] = []
    all_cats: dict[str, Any] = {}

    for name, cat_def in (context.framework.core or {}).items():
        all_cats[name] = cat_def
    if hasattr(context.framework, "extensions") and context.framework.extensions:
        for name, cat_def in (context.framework.extensions.available or {}).items():
            all_cats[name] = cat_def
    if hasattr(context.framework, "optional") and context.framework.optional:
        for name, cat_def in (context.framework.optional.available or {}).items():
            all_cats[name] = cat_def

    for cat_name, cat_def in sorted(all_cats.items()):
        lines.append(f"{cat_name} (tier: {cat_def.tier}):")
        if cat_def.required_slots:
            for slot in cat_def.required_slots:
                lines.append(f"  - {slot} (required)")
        if context.categories and cat_name in context.categories:
            cat_file = context.categories[cat_name]
            for slot_name in cat_file.slots:
                if slot_name not in (cat_def.required_slots or []):
                    lines.append(f"  - {slot_name}")
        lines.append("")

    return "\n".join(lines) if lines else "No slots defined."


def _build_filled_slots(context: ScanContext) -> str:
    """Format already-filled slots so LLM can skip them."""
    if not context.categories:
        return "None."

    lines: list[str] = []
    for cat_name, cat_file in sorted(context.categories.items()):
        for slot_name, slot_val in cat_file.slots.items():
            lines.append(f"- {cat_name}.{slot_name} = {slot_val.value}")

    return "\n".join(lines) if lines else "None."


def _build_system_prompt(context: ScanContext) -> str:
    """Build the system prompt with slot definitions. Cached across files."""
    template = _load_template()
    return template.format(
        slot_definitions=_build_slot_definitions(context),
        filled_slots=_build_filled_slots(context),
    )


def _build_user_prompt(path: Path, content: str) -> str:
    """Build the user prompt with the markdown content."""
    return f"Extract facts from the following document.\n\nFile: {path.name}\n---\n{content}"


def _parse_extraction_response(raw: str, source: str) -> ExtractResult:
    """Parse the LLM JSON response into ExtractResult."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [line for line in lines if not line.startswith("```")]
        raw = "\n".join(lines).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ExtractResult()

    if not isinstance(data, dict):
        return ExtractResult()

    candidates: list[SlotCandidate] = []
    for item in data.get("candidates", []):
        if not isinstance(item, dict):
            continue
        cat = item.get("category", "")
        slot = item.get("slot", "")
        value = item.get("value")
        if not cat or not slot or value is None:
            continue
        confidence = item.get("confidence", "medium")
        if confidence not in ("medium", "low"):
            confidence = "medium"
        candidates.append(
            SlotCandidate(
                category=cat,
                slot=slot,
                value=value,
                confidence=confidence,
                source=source,
                extractor="llm-markdown",
                evidence=item.get("evidence", ""),
            )
        )

    unmapped: list[UnmappedFact] = []
    for item in data.get("unmapped", []):
        if not isinstance(item, dict):
            continue
        fact = item.get("fact", "")
        if not fact:
            continue
        unmapped.append(
            UnmappedFact(
                fact=fact,
                source=source,
                suggested_category=item.get("suggested_category"),
                suggested_slot=item.get("suggested_slot"),
                evidence=item.get("evidence", ""),
            )
        )

    return ExtractResult(candidates=candidates, unmapped=unmapped)


def extract_markdown(
    path: Path, context: ScanContext | None = None
) -> ExtractResult:
    """Extract facts from a Markdown file using LLM."""
    if not path.is_file():
        return ExtractResult()

    try:
        content = path.read_text(encoding="utf-8").strip()
    except Exception:
        return ExtractResult()

    if not content:
        return ExtractResult()

    if not context:
        return ExtractResult()

    system_prompt = _build_system_prompt(context)
    user_prompt = _build_user_prompt(path, content)

    try:
        raw = llm_call(
            user_prompt,
            role="scan",
            model=context.model,
            system=system_prompt,
            max_tokens=4096,
            api_key=context.api_key,
        )
    except Exception:
        return ExtractResult()

    return _parse_extraction_response(raw, str(path))
