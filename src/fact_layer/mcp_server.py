"""MCP Server for fact-layer — exposes project facts to AI agents via MCP protocol."""

from __future__ import annotations

from fastmcp import FastMCP

from fact_layer.core.access_log import log_access, log_search
from fact_layer.core.checker import run_check
from fact_layer.core.exporter import (
    render_export,
    render_export_budgeted,
    render_export_delta,
    render_export_outline,
)
from fact_layer.core.impact_cmd import compute_impact
from fact_layer.core.search_cmd import compute_search
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
    log_access(facts_dir, "get", slot=slot, via="mcp")

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
    log_access(facts_dir, "list", slot=category, via="mcp")

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
    log_access(facts_dir, "check", slot=category, via="mcp")

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
def facts_search(
    query: str,
    category: str | None = None,
    include_stale: bool = False,
    limit: int = 20,
) -> dict:
    """Search facts by content — find a slot without knowing its category.slot-id.

    Offline case-insensitive substring match over each slot's id, value, and
    reason. Multi-word queries are AND (every whitespace-split token must appear);
    a query with no spaces matches as one contiguous run. Each hit carries the
    full value + which fields matched, so you usually need no follow-up facts_get.

    Args:
        query: search string. Empty → no hits.
        category: restrict to one category (a filter, not a searched field).
        include_stale: also search stale/superseded slots (default active-only).
            Every hit shows its status, so a non-active match is labeled, not hidden.
        limit: max hits (default 20); ``truncated`` flags when more matched.
    """
    facts_dir = _require_facts_dir()
    result = compute_search(
        facts_dir, query, category=category, include_stale=include_stale, limit=limit
    )
    log_search(facts_dir, query, [h.slot_ref for h in result.hits], via="mcp")
    return result.model_dump(mode="json")


@mcp.tool()
def facts_status() -> dict:
    """Get health overview of all fact categories."""
    facts_dir = _require_facts_dir()

    result = compute_status(facts_dir)
    return result.model_dump(mode="json")


@mcp.tool()
def facts_export(
    budget: int | None = None, since: str | None = None, outline: bool = False
) -> str:
    """Export facts as a markdown snapshot for agent consumption.

    Every export ends with an `fl-watermark:` token. To avoid re-reading the
    same content across turns, pass that token back as `since`: you then get
    only the facts changed since, or a tiny "no changes" note if nothing moved.

    For a cheap first look, use `outline=True`: it lists every slot with a
    one-line snippet (no full values), so you learn what facts exist without
    pulling them all — then use facts_search / facts_get for the ones you need.

    Args:
        budget: Optional max token budget. Omit for full export.
        since: Optional watermark token from a previous export (delta mode).
            Takes precedence over budget.
        outline: Lightweight catalog mode (takes precedence over since/budget).
    """
    facts_dir = _require_facts_dir()
    log_access(
        facts_dir,
        "export",
        args={k: v for k, v in {"budget": budget, "since": since, "outline": outline}.items() if v} or None,
        via="mcp",
    )

    if outline:
        return render_export_outline(facts_dir)
    if since is not None:
        return render_export_delta(facts_dir, since)
    if budget is not None:
        return render_export_budgeted(facts_dir, budget_tokens=budget)
    return render_export(facts_dir)


@mcp.tool()
def facts_scan(
    paths: list[str] | None = None,
    categories: list[str] | None = None,
    extractors: list[str] | None = None,
    model: str | None = None,
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
        model: Override the LLM model. Omit to use the role default from core.config.
        api_key: LLM API key. Falls back to OPENAI_API_KEY / ANTHROPIC_API_KEY env.
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


@mcp.tool()
def facts_eval_access_stats() -> dict:
    """Aggregate the tool-agnostic FL access log (.facts/eval/access.jsonl).

    This is the L1 backbone (FL-019): every FL read (get/list/check/export) is logged
    regardless of tool/hook/transcript. Returns totals by caller, by op, top slots, and
    the time range — the universal-floor view of who is actually consuming facts.
    """
    facts_dir = _require_facts_dir()

    from fact_layer.core.access_log import compute_access_stats

    return compute_access_stats(facts_dir).model_dump(mode="json")


@mcp.tool()
def facts_eval_effectiveness(
    session: str | None = None,
    after: str | None = None,
    sample: int | None = None,
    dry_run: bool = False,
) -> dict:
    """T2 observation: LLM replays real chains and rates each FL read A/B/C.

    Produces the *adoption rate* (A/(A+B)) — the observational effectiveness of FL,
    distinct from `facts_eval_stats` T1 counts (which only say how often FL was
    touched, NOT whether it helped). Returns both, in separate keys, so counts are
    never mistaken for the adoption rate.

    Args:
        session: Filter traces by session ID (supports wildcards).
        after: Only include traces after this date (YYYY-MM-DD).
        sample: Judge a random sample of N reads (default: all).
        dry_run: Extract evidence only, no LLM call (cost preview).

    Returns:
        {dry_run, total_reads, t1: {...relevance counts...}, t2: T2Report|None}.
    """
    facts_dir = _require_facts_dir()

    from fact_layer.core.eval_t2 import run_effectiveness

    return run_effectiveness(
        facts_dir, session=session, after=after, sample=sample, dry_run=dry_run
    )


@mcp.tool()
def facts_set(slot: str, value: str | int | float | bool | list | dict, reason: str | None = None) -> dict:
    """Set a single slot's value with automatic consistency check.

    Args:
        slot: Slot reference in 'category.slot-id' format, e.g. 'tech-stack.database'.
        value: New value for the slot.
        reason: Optional reason for the change.
    """
    facts_dir = _require_facts_dir()

    from fact_layer.core.editor import set_slot

    result = set_slot(facts_dir, slot, value, reason=reason)
    return result.model_dump(mode="json")


@mcp.tool()
def facts_add(
    category: str,
    slot_id: str,
    value: str | int | float | bool | list | dict,
    reason: str | None = None,
) -> dict:
    """Add a NEW slot to an existing category.

    Use this to CREATE a slot that does not yet exist. To UPDATE an existing
    slot, use facts_set instead. Fails if the slot already exists (use facts_set)
    or the category is not enabled.

    Args:
        category: Category name the slot belongs to, e.g. 'data-model'.
        slot_id: New slot ID; must not already exist in the category, e.g. 'enum-status'.
        value: Slot value.
        reason: Optional reason for adding.
    """
    facts_dir = _require_facts_dir()

    from fact_layer.core.editor import add_slot

    result = add_slot(facts_dir, category, slot_id, value, reason=reason)
    return result.model_dump(mode="json")


@mcp.tool()
def facts_set_batch(
    items: list[dict],
    audit: bool = True,
    model: str | None = None,
) -> dict:
    """Batch-set multiple slot values, then optionally run an audit.

    Each item: {"slot": "category.slot-id", "value": ..., "reason": "..."}.
    After all writes, an LLM audit checks for contradictions, redundant slots,
    and missing relationships.

    Args:
        items: List of slot updates. Each must have 'slot' and 'value'; 'reason' is optional.
        audit: Run semantic audit after batch write (default: true).
        model: Override the audit LLM model. Omit to use the role default from core.config.
    """
    facts_dir = _require_facts_dir()

    from fact_layer.core.editor import BatchSetItem, set_batch

    parsed_items = [BatchSetItem.model_validate(item) for item in items]
    result = set_batch(facts_dir, parsed_items, audit=audit, audit_model=model)
    return result.model_dump(mode="json")


@mcp.tool()
def facts_audit(model: str | None = None) -> dict:
    """Run an LLM-powered semantic consistency audit across all canonical facts.

    Checks for contradictions, staleness, missing facts, redundant slots,
    and missing dependency relationships.

    Args:
        model: Override the audit LLM model. Omit to use the role default from core.config.
    """
    facts_dir = _require_facts_dir()

    from fact_layer.core.auditor import run_audit

    result = run_audit(facts_dir, model=model)
    return result.model_dump(mode="json")


@mcp.tool()
def facts_dep_add(source: str, target: str, edge_type: str) -> dict:
    """Add a dependency edge source -> target in the dependency graph.

    Both endpoint slots must already exist (a dangling edge is refused).
    edge_type is one of: derives-from | constrains | references | implies |
    conflicts-with.

    Args:
        source: Source slot, e.g. 'tech-stack.database'.
        target: Target slot, e.g. 'data-model.database-type'.
        edge_type: Relationship type (see above).
    """
    facts_dir = _require_facts_dir()

    from fact_layer.core.dep_editor import add_dependency

    add_dependency(facts_dir, source, target, edge_type)
    return {"added": True, "source": source, "target": target, "type": edge_type}


@mcp.tool()
def facts_dep_remove(source: str, target: str) -> dict:
    """Remove the dependency edge source -> target.

    Works on dangling edges (endpoint slot missing) too — that is how a dangling
    edge flagged by facts_check gets repaired. Returns removed=false if absent.

    Args:
        source: Source slot of the edge.
        target: Target slot of the edge.
    """
    facts_dir = _require_facts_dir()

    from fact_layer.core.dep_editor import remove_dependency

    removed = remove_dependency(facts_dir, source, target)
    return {"removed": removed, "source": source, "target": target}


@mcp.tool()
def facts_dep_list() -> dict:
    """List all dependency edges as {source, target, type} records."""
    facts_dir = _require_facts_dir()

    from fact_layer.core.dep_editor import list_dependencies

    graph = list_dependencies(facts_dir)
    edges = [
        {"source": rule.source, "target": t.slot, "type": t.type}
        for rule in graph.static
        for t in rule.targets
    ]
    return {"edges": edges}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
