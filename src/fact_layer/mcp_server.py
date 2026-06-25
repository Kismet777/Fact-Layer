"""MCP Server for fact-layer — exposes project facts to AI agents via MCP protocol."""

from __future__ import annotations

from fastmcp import FastMCP

from fact_layer.core.checker import run_check
from fact_layer.core.exporter import render_export, render_export_budgeted
from fact_layer.core.impact_cmd import compute_impact
from fact_layer.core.loader import load_all_categories
from fact_layer.core.registry import resolve_facts_dir
from fact_layer.core.status_cmd import compute_status
from fact_layer.models.slot import ACTIVE_STATUSES

mcp = FastMCP("fact-layer")


def _require_facts_dir():
    facts_dir = resolve_facts_dir()
    if not facts_dir:
        raise ValueError("No .facts/ directory found. Run 'fl init' first.")
    return facts_dir


@mcp.tool()
def facts_get(slot: str) -> dict:
    """Get a single slot's value and metadata.

    Args:
        slot: Slot reference in 'category.slot-id' format, e.g. 'tech-stack.database'.
    """
    facts_dir = _require_facts_dir()

    parts = slot.split(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid slot reference '{slot}'. Expected 'category.slot-id' format.")

    cat_name, slot_id = parts
    categories = load_all_categories(facts_dir)
    cat = categories.get(cat_name)
    if not cat:
        raise ValueError(f"Category '{cat_name}' not found.")

    slot_value = cat.slots.get(slot_id)
    if not slot_value:
        raise ValueError(f"Slot '{slot_id}' not found in category '{cat_name}'.")

    return {
        "slot": slot,
        "value": slot_value.value,
        "meta": slot_value.meta.model_dump(mode="json"),
    }


@mcp.tool()
def facts_list(category: str) -> list[dict]:
    """List all active slots in a category.

    Args:
        category: Category name, e.g. 'tech-stack'.
    """
    facts_dir = _require_facts_dir()

    categories = load_all_categories(facts_dir)
    cat = categories.get(category)
    if not cat:
        raise ValueError(f"Category '{category}' not found.")

    slots = []
    for slot_id, slot_value in cat.slots.items():
        if slot_value.meta.status in ACTIVE_STATUSES:
            slots.append({
                "slot": f"{category}.{slot_id}",
                "value": slot_value.value,
                "meta": slot_value.meta.model_dump(mode="json"),
            })
    return slots


@mcp.tool()
def facts_check(category: str | None = None) -> dict:
    """Run consistency checks on facts.

    Args:
        category: Optional category name to filter checks. Checks all if omitted.
    """
    facts_dir = _require_facts_dir()

    result = run_check(facts_dir, filter_category=category)
    return {
        "errors": [issue.model_dump(mode="json") for issue in result.errors],
        "warnings": [issue.model_dump(mode="json") for issue in result.warnings],
        "has_errors": result.has_errors,
    }


@mcp.tool()
def facts_impact(slot: str) -> dict:
    """Analyze downstream impact of changing a slot.

    Args:
        slot: Slot reference in 'category.slot-id' format.
    """
    facts_dir = _require_facts_dir()

    result = compute_impact(facts_dir, slot)
    return result.model_dump(mode="json")


@mcp.tool()
def facts_status() -> dict:
    """Get health overview of all fact categories."""
    facts_dir = _require_facts_dir()

    result = compute_status(facts_dir)
    return result.model_dump(mode="json")


@mcp.tool()
def facts_export(budget: int | None = None) -> str:
    """Export facts as a markdown snapshot for agent consumption.

    Args:
        budget: Optional max token budget. Omit for full export.
    """
    facts_dir = _require_facts_dir()

    if budget is not None:
        return render_export_budgeted(facts_dir, budget_tokens=budget)
    return render_export(facts_dir)


@mcp.tool()
def facts_scan(
    paths: list[str] | None = None,
    categories: list[str] | None = None,
    extractors: list[str] | None = None,
    model: str = "claude-sonnet-4-6",
    api_key: str | None = None,
    full: bool = False,
) -> dict:
    """Scan project files to extract candidate facts for .facts/ slots.

    Extracts from config files (pyproject.toml, Dockerfile, docker-compose,
    package.json, CI) and Markdown documents (README, CLAUDE.md, etc.).
    Uses incremental scanning by default — only rescans files whose content changed.

    Args:
        paths: File or directory paths to scan. Omit to auto-discover from project root.
        categories: Only return candidates for these categories. Omit for all.
        extractors: Only use these extractors (e.g. ["config", "markdown"]). Omit for all.
        model: LLM model for markdown extraction (default: claude-sonnet-4-6).
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
        full: Ignore indexes and rescan all files (default: False).
    """
    import os

    facts_dir = _require_facts_dir()
    project_root = facts_dir.parent

    from fact_layer.core.scanner.pipeline import run_scan

    result = run_scan(
        project_root=project_root,
        paths=paths,
        categories=categories,
        extractors=extractors,
        api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
        model=model,
        full=full,
    )
    return result.model_dump(mode="json")


@mcp.tool()
def facts_scan_integrity() -> dict:
    """Check scan index integrity — orphaned extractions, stale sources, cross-source conflicts.

    Pure rule-based check, no LLM needed.
    """
    facts_dir = _require_facts_dir()

    from fact_layer.core.scan_integrity import run_scan_integrity

    result = run_scan_integrity(facts_dir)
    return result.model_dump(mode="json")


@mcp.tool()
def facts_eval_log(trace: dict) -> dict:
    """Write a complete turn trace to .facts/eval/.

    Args:
        trace: Full trace object with session_id, turn, timestamp, steps, and summary.
    """
    facts_dir = _require_facts_dir()

    from fact_layer.core.eval_cmd import save_trace
    from fact_layer.models.eval import EvalTrace

    parsed = EvalTrace.model_validate(trace)
    path = save_trace(facts_dir, parsed)
    return {
        "status": "ok",
        "session_id": parsed.session_id,
        "turn": parsed.turn,
        "steps_count": len(parsed.steps),
        "path": path.name,
    }


@mcp.tool()
def facts_eval_list(
    session: str | None = None,
    source: str | None = None,
    bypassed: bool = False,
    after: str | None = None,
) -> list[dict]:
    """Browse eval traces with optional filtering.

    Args:
        session: Filter by session ID (supports wildcards like "贷后催收*").
        source: Only return traces containing this source type (fl/doc/code/db/web/inference).
        bypassed: Only return traces that contain rule bypasses.
        after: Only return traces after this date (YYYY-MM-DD format).
    """
    facts_dir = _require_facts_dir()

    from fact_layer.core.eval_cmd import load_traces

    traces = load_traces(
        facts_dir,
        session=session,
        source=source,
        bypassed=bypassed,
        after=after,
    )
    return [t.model_dump(mode="json") for t in traces]


@mcp.tool()
def facts_eval_stats(
    session: str | None = None,
    after: str | None = None,
) -> dict:
    """Compute aggregate statistics across eval traces.

    Returns FL vs doc ratio, source distribution, bypass details, slot hit ranking,
    L2 coverage, and timing stats.

    Args:
        session: Filter by session ID (supports wildcards).
        after: Only include traces after this date (YYYY-MM-DD format).
    """
    facts_dir = _require_facts_dir()

    from fact_layer.core.eval_cmd import compute_eval_stats, load_traces

    traces = load_traces(facts_dir, session=session, after=after)
    stats = compute_eval_stats(traces)
    return stats.model_dump(mode="json")


def main():
    mcp.run()


if __name__ == "__main__":
    main()
