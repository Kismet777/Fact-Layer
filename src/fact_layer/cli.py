from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

app = typer.Typer(
    name="fl",
    help="fact-layer: Structured, consistency-checked project facts for AI coding agents.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def init(
    path: Annotated[
        Optional[str],
        typer.Argument(help="Project path to initialize (default: current directory)"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing .facts/ directory"),
    ] = False,
) -> None:
    """Initialize a .facts/ directory with framework, dependencies, and canonical templates."""
    from fact_layer.core.init_cmd import (
        EXTENSION_CATEGORIES,
        OPTIONAL_CATEGORIES,
        init_facts_dir,
    )

    target = Path(path) if path else Path.cwd()
    facts_dir = target / ".facts"

    if facts_dir.exists() and not force:
        console.print(f"[yellow].facts/ already exists at {facts_dir}[/yellow]")
        if not Confirm.ask("Overwrite?", default=False):
            console.print("Aborted.")
            raise typer.Exit(0)

    console.print("[bold]Initializing fact-layer...[/bold]\n")

    project_name = Prompt.ask("Project name", default=target.name)
    language = Prompt.ask("Primary language")

    console.print("\n[bold]Extension categories[/bold] (enable based on project needs):")
    enabled_extensions: list[str] = []
    for ext_name, ext_desc in EXTENSION_CATEGORIES.items():
        if Confirm.ask(f"  {ext_name} — {ext_desc}", default=True):
            enabled_extensions.append(ext_name)

    enabled_optional: list[str] = []
    console.print()
    for opt_name, opt_desc in OPTIONAL_CATEGORIES.items():
        if Confirm.ask(f"Enable {opt_desc}?", default=True):
            enabled_optional.append(opt_name)

    console.print()
    created = init_facts_dir(
        target=target,
        project_name=project_name,
        language=language,
        enabled_extensions=enabled_extensions,
        enabled_optional=enabled_optional,
    )

    console.print(f"[green]Created .facts/ with {len(created)} categories:[/green]")
    for cat in created:
        console.print(f"  - {cat}")
    console.print(
        "\nEdit [bold].facts/canonical/*.yaml[/bold] to fill in your project facts."
    )
    console.print("Run [bold]fl check[/bold] to validate consistency.")


@app.command()
def check(
    category: Annotated[
        Optional[str],
        typer.Option("--category", "-c", help="Only check a specific category"),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Treat warnings as errors (exit code 1)"),
    ] = False,
) -> None:
    """Validate all canonical facts for structural integrity, staleness, and dependency consistency."""
    from fact_layer.core.checker import CheckResult, Severity, run_check
    from fact_layer.core.registry import resolve_facts_dir

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    result = run_check(facts_dir, filter_category=category)

    if not result.issues:
        console.print("[green]All checks passed. 0 errors, 0 warnings.[/green]")
        raise typer.Exit(0)

    grouped: dict[str, list] = {}
    for issue in result.issues:
        grouped.setdefault(issue.check_type, []).append(issue)

    type_labels = {
        "structural": "Structural",
        "staleness": "Staleness",
        "dependency": "Dependencies",
        "decisions": "Decisions",
    }

    console.print("[bold]Checking facts consistency...[/bold]\n")
    for check_type in ["structural", "staleness", "dependency", "decisions"]:
        issues = grouped.get(check_type, [])
        if not issues:
            continue
        console.print(f"  [bold]{type_labels.get(check_type, check_type)}:[/bold]")
        for issue in issues:
            icon = "[red]x[/red]" if issue.severity == Severity.ERROR else "[yellow]![/yellow]"
            console.print(f"  {icon} {issue.message}")
            if issue.detail:
                console.print(f"      {issue.detail}")
        console.print()

    n_err = len(result.errors)
    n_warn = len(result.warnings)
    console.print(f"  [bold]Summary: {n_err} errors, {n_warn} warnings[/bold]")

    if result.has_errors or (strict and n_warn > 0):
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show an overview of facts health: fill rate, staleness, last verified times."""
    from fact_layer.core.registry import resolve_facts_dir
    from fact_layer.core.status_cmd import compute_status

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    st = compute_status(facts_dir)

    console.print("[bold]Facts Status[/bold]\n")

    current_tier = ""
    tier_labels = {"stable": "Stable Layer", "dynamic": "Dynamic Layer", "working": "Working Layer"}

    for cat in st.categories:
        if cat.tier != current_tier:
            current_tier = cat.tier
            console.print(f"  [bold]{tier_labels.get(current_tier, current_tier)}[/bold]")

        if cat.is_empty or cat.has_required_missing:
            icon = "[red]x[/red]"
        elif cat.stale_count > 0:
            icon = "[yellow]![/yellow]"
        else:
            icon = "[green]v[/green]"

        if cat.active_decisions is not None:
            detail = f"{cat.active_decisions} active decisions"
        else:
            detail = f"{cat.filled}/{cat.total} slots"

        if cat.is_empty:
            age = "never filled"
        elif cat.stale_count > 0:
            age = f"{cat.stale_count} stale"
        elif cat.last_verified_days is not None:
            if cat.last_verified_days == 0:
                age = "verified today"
            else:
                age = f"verified {cat.last_verified_days}d ago"
        else:
            age = ""

        line = f"  {icon} {cat.name:<22} {detail:<20} {age}"
        console.print(line)

    console.print()
    console.print(
        f"  Overall: {st.total_filled}/{st.total_slots} slots filled"
        f" · {st.total_stale} stale"
        f" · {st.empty_categories} category empty"
    )


@app.command()
def impact(
    slot: Annotated[str, typer.Argument(help="Slot to analyze, e.g. tech-stack.database")],
) -> None:
    """Show which other slots are affected when a given slot changes."""
    from fact_layer.core.impact_cmd import compute_impact
    from fact_layer.core.registry import resolve_facts_dir

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    result = compute_impact(facts_dir, slot)

    if not result.slot_exists:
        console.print(f"[yellow]Warning: slot '{slot}' not found in canonical facts[/yellow]")

    console.print(f"[bold]Impact analysis for {slot}[/bold]\n")

    if result.targets:
        console.print("  [bold]Direct dependencies:[/bold]")
        for i, t in enumerate(result.targets):
            prefix = "└──" if i == len(result.targets) - 1 else "├──"
            strength = "(MUST update)" if t.is_strong else "(should check)"
            console.print(f"  {prefix} {t.slot:<35} {t.relation_type:<16} {strength}")
    else:
        console.print("  No direct dependencies found.")

    if result.decisions:
        console.print("\n  [bold]From decisions:[/bold]")
        for i, d in enumerate(result.decisions):
            prefix = "└──" if i == len(result.decisions) - 1 else "├──"
            console.print(f'  {prefix} {d.decision_id} "{d.title}"    affects this slot')

    if not result.targets and not result.decisions:
        console.print("\n  This slot has no downstream dependencies or decision references.")


@app.command()
def export(
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output file path (default: .facts/snapshot.md)"),
    ] = None,
    stdout: Annotated[
        bool,
        typer.Option("--stdout", help="Print to stdout instead of file"),
    ] = False,
    budget: Annotated[
        Optional[int],
        typer.Option("--budget", "-b", help="Max token budget for smart truncation"),
    ] = None,
) -> None:
    """Export all canonical facts as a single markdown snapshot for agent consumption."""
    from fact_layer.core.exporter import render_export, render_export_budgeted
    from fact_layer.core.registry import resolve_facts_dir

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    if budget is not None:
        md = render_export_budgeted(facts_dir, budget_tokens=budget)
    else:
        md = render_export(facts_dir)

    if stdout:
        print(md)
    else:
        out_path = Path(output) if output else facts_dir / "snapshot.md"
        out_path.write_text(md, encoding="utf-8")
        console.print(f"[green]Exported to {out_path}[/green]")


@app.command(name="set")
def set_cmd(
    slot: Annotated[str, typer.Argument(help="Slot to modify, e.g. tech-stack.database")],
    value: Annotated[str, typer.Argument(help="New value (string, or JSON for lists/dicts)")],
    reason: Annotated[
        Optional[str],
        typer.Option("--reason", "-r", help="Reason for the change"),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Parse value as JSON"),
    ] = False,
) -> None:
    """Set a slot value with automatic metadata update and consistency check."""
    from fact_layer.core.editor import SetResult, parse_value, set_slot
    from fact_layer.core.registry import resolve_facts_dir

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    parsed = parse_value(value, force_json=json_mode)

    try:
        result = set_slot(facts_dir, slot, parsed, reason=reason)
    except (ValueError, KeyError, FileNotFoundError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Updated {result.slot_ref}[/green]")
    console.print(f"  {result.old_value} → {result.new_value}")

    if result.impact and result.impact.targets:
        console.print("\n  [bold]Downstream dependencies:[/bold]")
        for t in result.impact.targets:
            strength = "(MUST update)" if t.is_strong else "(should check)"
            console.print(f"    {t.slot:<35} {t.relation_type:<16} {strength}")

    errors = [i for i in result.check_issues if i.severity.value == "error"]
    warnings = [i for i in result.check_issues if i.severity.value == "warning"]
    if errors or warnings:
        console.print(f"\n  [bold]Check: {len(errors)} errors, {len(warnings)} warnings[/bold]")
        for issue in errors:
            console.print(f"  [red]x[/red] {issue.message}")


@app.command()
def add(
    category: Annotated[str, typer.Argument(help="Category name, e.g. tech-stack")],
    slot_id: Annotated[str, typer.Argument(help="New slot ID, e.g. orm")],
    value: Annotated[str, typer.Argument(help="Slot value")],
    reason: Annotated[
        Optional[str],
        typer.Option("--reason", "-r", help="Reason for adding"),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Parse value as JSON"),
    ] = False,
) -> None:
    """Add a new slot to an existing category."""
    from fact_layer.core.editor import parse_value, add_slot
    from fact_layer.core.registry import resolve_facts_dir

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    parsed = parse_value(value, force_json=json_mode)

    try:
        result = add_slot(facts_dir, category, slot_id, parsed, reason=reason)
    except (ValueError, KeyError, FileNotFoundError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Added {result.category}.{result.slot_id}[/green]")
    console.print(f"  Value: {result.value}")

    errors = [i for i in result.check_issues if i.severity.value == "error"]
    if errors:
        console.print(f"\n  [bold]Check: {len(errors)} errors[/bold]")
        for issue in errors:
            console.print(f"  [red]x[/red] {issue.message}")


@app.command()
def deprecate(
    slot: Annotated[str, typer.Argument(help="Slot to deprecate, e.g. tech-stack.legacy-db")],
    reason: Annotated[
        Optional[str],
        typer.Option("--reason", "-r", help="Reason for deprecation"),
    ] = None,
) -> None:
    """Mark a slot as superseded (soft-delete, preserves history)."""
    from fact_layer.core.editor import deprecate_slot
    from fact_layer.core.registry import resolve_facts_dir

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    try:
        result = deprecate_slot(facts_dir, slot, reason=reason)
    except (ValueError, KeyError, FileNotFoundError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Deprecated {result.slot_ref}[/yellow]")
    console.print(f"  Status: {result.old_status} → superseded")

    if result.impact and result.impact.targets:
        console.print("\n  [bold]Warning — downstream dependencies:[/bold]")
        for t in result.impact.targets:
            strength = "(MUST update)" if t.is_strong else "(should check)"
            console.print(f"    [yellow]{t.slot:<35} {t.relation_type:<16} {strength}[/yellow]")


@app.command()
def scan(
    paths: Annotated[
        Optional[list[str]],
        typer.Argument(help="Files or directories to scan (default: auto-discover)"),
    ] = None,
    category: Annotated[
        Optional[str],
        typer.Option("--category", "-c", help="Only extract for specific categories (comma-separated)"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show candidates without interactive review"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output raw JSON (for programmatic use)"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Auto-accept all candidates"),
    ] = False,
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="LLM model for markdown extraction"),
    ] = "claude-sonnet-4-6",
    api_key: Annotated[
        Optional[str],
        typer.Option("--api-key", help="Anthropic API key (or set ANTHROPIC_API_KEY env)"),
    ] = None,
    extractor: Annotated[
        Optional[str],
        typer.Option("--extractor", "-e", help="Only use specific extractors (comma-separated: config,markdown)"),
    ] = None,
    full: Annotated[
        bool,
        typer.Option("--full", help="Ignore indexes and rescan all files"),
    ] = False,
) -> None:
    """Scan project files to extract facts for .facts/ slots.

    Reads config files (pyproject.toml, Dockerfile, docker-compose, package.json, CI)
    and Markdown documents (README, CLAUDE.md, etc.) to propose candidate facts.
    Review and accept to populate your fact layer.
    """
    import json as json_mod
    import os

    from fact_layer.core.registry import resolve_facts_dir
    from fact_layer.core.scanner.pipeline import run_scan

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    project_root = facts_dir.parent
    categories = [c.strip() for c in category.split(",")] if category else None
    extractor_list = [e.strip() for e in extractor.split(",")] if extractor else None
    resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    result = run_scan(
        project_root=project_root,
        paths=paths or None,
        categories=categories,
        extractors=extractor_list,
        api_key=resolved_key,
        model=model,
        full=full,
    )

    if json_output:
        print(json_mod.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
        raise typer.Exit(0)

    # --- Summary header ---
    skip_info = f", {result.stats.skipped_files} skipped (unchanged)" if result.stats.skipped_files else ""
    console.print(f"[bold]Scan complete:[/bold] {result.stats.files_scanned} files scanned{skip_info}\n")

    if not result.candidates and not result.conflicts and not result.unmapped:
        console.print("  No candidates found.")
        raise typer.Exit(0)

    # --- Display candidates grouped by category ---
    if result.candidates:
        by_category: dict[str, list] = {}
        for c in result.candidates:
            by_category.setdefault(c.category, []).append(c)

        for cat_name, candidates in sorted(by_category.items()):
            console.print(f"  [bold]{cat_name}[/bold]")
            for c in candidates:
                console.print(f"    {c.slot:<25} = {c.value}")
                console.print(f"    [dim]source: {c.source}  evidence: {c.evidence}[/dim]")
            console.print()

    # --- Display conflicts ---
    if result.conflicts:
        console.print(f"  [bold yellow]Conflicts ({len(result.conflicts)}):[/bold yellow]")
        for cg in result.conflicts:
            console.print(f"    [yellow]{cg.slot_ref}[/yellow]")
            for c in cg.candidates:
                console.print(f"      {c.value:<30} [dim]({c.source})[/dim]")
        console.print()

    # --- Display unmapped facts ---
    if result.unmapped:
        console.print(f"  [bold cyan]Unmapped Facts ({len(result.unmapped)}):[/bold cyan]")
        for u in result.unmapped:
            console.print(f"    {u.fact}")
            if u.suggested_category and u.suggested_slot:
                console.print(f"      [dim]-> {u.suggested_category}.{u.suggested_slot}[/dim]")
            if u.evidence:
                console.print(f'      [dim]"{u.evidence}"[/dim]')
        console.print()

    console.print(
        f"  [bold]Summary: {result.stats.candidates_found} candidates"
        f" · {result.stats.conflicts} conflicts"
        f" · {result.stats.unmapped} unmapped[/bold]"
    )

    if dry_run:
        return

    # --- Batch review by category ---
    from fact_layer.core.editor import set_slot

    applied = 0
    skipped = 0

    by_category = {}
    for c in result.candidates:
        by_category.setdefault(c.category, []).append(c)

    for cat_name, candidates in sorted(by_category.items()):
        console.print(f"\n  [bold]Review: {cat_name}[/bold]")
        for idx, c in enumerate(candidates, 1):
            console.print(f"  [{idx}/{len(candidates)}] {c.slot_ref}")
            console.print(f"    Value:    [green]{c.value}[/green]")
            console.print(f"    Source:   {c.source}")
            console.print(f"    Evidence: {c.evidence}")

            if yes:
                action = "y"
            else:
                action = Prompt.ask(
                    "    [Y] accept  [n] skip",
                    choices=["y", "n"],
                    default="y",
                )

            if action == "y":
                try:
                    set_slot(facts_dir, c.slot_ref, c.value)
                    console.print(f"    [green]Applied.[/green]\n")
                    applied += 1
                except (ValueError, KeyError) as e:
                    console.print(f"    [red]Failed: {e}[/red]\n")
                    skipped += 1
            else:
                console.print(f"    [dim]Skipped.[/dim]\n")
                skipped += 1

    console.print(f"\n  [bold]Done: {applied} applied, {skipped} skipped.[/bold]")


@app.command()
def suggest(
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="Claude model to use"),
    ] = "claude-sonnet-4-6",
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Auto-accept all suggestions"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show suggestions without applying"),
    ] = False,
) -> None:
    """Generate LLM-powered fix suggestions for issues found by fl check."""
    from fact_layer.core.auditor import estimate_tokens
    from fact_layer.core.checker import run_check
    from fact_layer.core.editor import parse_value
    from fact_layer.core.registry import resolve_facts_dir
    from fact_layer.core.suggest_cmd import (
        apply_suggestion,
        build_suggest_prompt,
        run_suggest,
    )

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    check_result = run_check(facts_dir)
    if not check_result.issues:
        console.print("[green]No issues found by fl check. Nothing to suggest.[/green]")
        raise typer.Exit(0)

    n_err = len(check_result.errors)
    n_warn = len(check_result.warnings)
    console.print(f"[bold]fl check found {n_err} errors, {n_warn} warnings.[/bold]")

    prompt = build_suggest_prompt(facts_dir, check_result.issues)
    token_est = estimate_tokens(prompt)
    console.print(f"  Calling LLM (~{token_est} tokens, model: {model})...\n")

    result = run_suggest(facts_dir, model=model)

    if result.error:
        console.print(f"[red]{result.error}[/red]")
        raise typer.Exit(1)

    if not result.suggestions:
        console.print("[yellow]LLM returned no actionable suggestions.[/yellow]")
        raise typer.Exit(0)

    console.print(f"[bold]{len(result.suggestions)} suggestion(s):[/bold]\n")

    applied = 0
    skipped = 0

    for idx, s in enumerate(result.suggestions, 1):
        console.print(f"  [bold][{idx}/{len(result.suggestions)}] {s.slot}[/bold]")
        console.print(f"    Current:   {s.current_value}")
        console.print(f"    Suggested: [green]{s.suggested_value}[/green]")
        console.print(f"    Reason:    {s.reason}")

        if dry_run:
            console.print("    [dim](dry-run, not applied)[/dim]\n")
            continue

        if yes:
            action = "y"
        else:
            action = Prompt.ask(
                "    [Y] accept  [e] edit  [n] skip",
                choices=["y", "e", "n"],
                default="y",
            )

        if action == "y":
            apply_suggestion(facts_dir, s)
            console.print(f"    [green]Applied.[/green]\n")
            applied += 1
        elif action == "e":
            edited = Prompt.ask("    New value", default=str(s.suggested_value))
            parsed = parse_value(edited)
            s.suggested_value = parsed
            apply_suggestion(facts_dir, s, source="human")
            console.print(f"    [green]Applied (edited).[/green]\n")
            applied += 1
        else:
            console.print(f"    [dim]Skipped.[/dim]\n")
            skipped += 1

    if not dry_run:
        console.print(f"  [bold]Done: {applied} applied, {skipped} skipped.[/bold]")
        if applied > 0:
            post_check = run_check(facts_dir)
            n_err = len(post_check.errors)
            n_warn = len(post_check.warnings)
            console.print(f"  Post-check: {n_err} errors, {n_warn} warnings.")


eval_app = typer.Typer(
    name="eval",
    help="Eval trace logging and analysis for measuring FL effectiveness.",
    no_args_is_help=True,
)
app.add_typer(eval_app)


@eval_app.command()
def log(
    session: Annotated[
        Optional[str],
        typer.Option("--session", "-s", help="Session identifier"),
    ] = None,
    turn: Annotated[
        Optional[int],
        typer.Option("--turn", "-t", help="Turn number"),
    ] = None,
    steps: Annotated[
        Optional[str],
        typer.Option("--steps", help="Steps as JSON array"),
    ] = None,
    summary: Annotated[
        Optional[str],
        typer.Option("--summary", help="Summary as JSON object"),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Input is JSON (default auto-detects)"),
    ] = False,
) -> None:
    """Write a complete turn trace to .facts/eval/.

    Accepts input via --session/--turn/--steps flags, or reads JSON/YAML from stdin.
    """
    import json as json_mod
    import sys
    from datetime import datetime, timezone

    from fact_layer.core.eval_cmd import save_trace
    from fact_layer.core.registry import resolve_facts_dir
    from fact_layer.models.eval import EvalStep, EvalSummary, EvalTrace

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    if session and turn is not None and steps:
        parsed_steps = json_mod.loads(steps)
        parsed_summary = json_mod.loads(summary) if summary else {}
        trace = EvalTrace(
            session_id=session,
            turn=turn,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            steps=[EvalStep.model_validate(s) for s in parsed_steps],
            summary=EvalSummary.model_validate(parsed_summary),
        )
    elif not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        try:
            data = json_mod.loads(raw)
        except json_mod.JSONDecodeError:
            from ruamel.yaml import YAML

            yaml = YAML()
            from io import StringIO

            data = dict(yaml.load(StringIO(raw)))
        trace = EvalTrace.model_validate(data)
    else:
        console.print("[red]Provide --session/--turn/--steps, or pipe JSON/YAML to stdin.[/red]")
        raise typer.Exit(1)

    path = save_trace(facts_dir, trace)
    console.print(f"[green]Logged eval trace:[/green] {trace.session_id} turn {trace.turn}")
    console.print(f"  {len(trace.steps)} steps → {path.name}")


@eval_app.command(name="list")
def list_cmd(
    session: Annotated[
        Optional[str],
        typer.Option("--session", "-s", help="Filter by session (supports wildcards)"),
    ] = None,
    source: Annotated[
        Optional[str],
        typer.Option("--source", help="Only show traces with this source type"),
    ] = None,
    bypassed: Annotated[
        bool,
        typer.Option("--bypassed", help="Only show traces with rule bypasses"),
    ] = False,
    after: Annotated[
        Optional[str],
        typer.Option("--after", help="Only show traces after this date (YYYY-MM-DD)"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show step details for each turn"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Browse eval traces by session, with optional filtering."""
    import json as json_mod
    from collections import Counter

    from fact_layer.core.eval_cmd import load_traces
    from fact_layer.core.registry import resolve_facts_dir

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    traces = load_traces(
        facts_dir,
        session=session,
        source=source,
        bypassed=bypassed,
        after=after,
    )

    if json_output:
        print(json_mod.dumps([t.model_dump(mode="json") for t in traces], indent=2, ensure_ascii=False))
        raise typer.Exit(0)

    if not traces:
        console.print("No eval traces found.")
        raise typer.Exit(0)

    by_session: dict[str, list] = {}
    for t in traces:
        by_session.setdefault(t.session_id, []).append(t)

    for sess_id, sess_traces in by_session.items():
        sess_traces.sort(key=lambda t: t.timestamp)
        date_str = sess_traces[0].timestamp[:10]

        total_sources: Counter[str] = Counter()
        for t in sess_traces:
            for step in t.steps:
                if step.source:
                    total_sources[step.source] += 1

        source_parts = " / ".join(f"{s} {c}" for s, c in total_sources.most_common())
        console.print(
            f"[bold]Session: {sess_id}[/bold]（{date_str}）"
        )
        console.print(
            f"共 {len(sess_traces)} turns，事实来源: {source_parts}"
        )
        console.print()

        for t in sess_traces:
            step_sources = [s.source for s in t.steps if s.source]
            source_tags = " ".join(step_sources)
            bypass_warn = ""
            for s in t.steps:
                if s.bypassed:
                    bypass_warn = f"  [yellow]⚠️ bypassed:{s.bypassed.rule}[/yellow]"
                    break

            time_str = t.timestamp[11:16] if len(t.timestamp) >= 16 else ""
            tool_summary = ""
            tools = [s.tool for s in t.steps if s.type == "tool_call" and s.tool]
            if tools:
                tool_summary = " + ".join(tools[:3])
                if len(tools) > 3:
                    tool_summary += f" +{len(tools)-3}"

            console.print(
                f"  Turn {t.turn:<3} {time_str}  {source_tags:<20} {tool_summary}{bypass_warn}"
            )

            if verbose:
                for s in t.steps:
                    if s.type == "tool_call":
                        args_str = ""
                        if s.args:
                            args_str = " " + " ".join(f"{k}={v}" for k, v in s.args.items())
                        source_tag = f" ({s.source})" if s.source else ""
                        console.print(f"    [dim]\\[tool_call] {s.tool}{args_str}{source_tag}[/dim]")
                        if s.result_used_for:
                            console.print(f"      → {s.result_used_for}")
                    else:
                        source_tag = f" ({s.source})" if s.source else ""
                        console.print(f"    [dim]\\[reasoning]{source_tag}[/dim]")
                        if s.rationale:
                            console.print(f"      {s.rationale}")
                        if s.conclusion:
                            console.print(f"      → {s.conclusion}")
                    if s.bypassed:
                        console.print(
                            f"      [yellow]⚠️ bypassed:{s.bypassed.rule} {s.bypassed.reason}[/yellow]"
                        )
                console.print()

        fl_total = total_sources.get("fl", 0)
        doc_total = total_sources.get("doc", 0)
        fl_plus_doc = fl_total + doc_total
        if fl_plus_doc > 0:
            fl_pct = fl_total * 100 // fl_plus_doc
            doc_pct = 100 - fl_pct
            console.print(
                f"  FL vs 文档: FL {fl_total} ({fl_pct}%) / 文档 {doc_total} ({doc_pct}%)"
            )
        console.print()


@eval_app.command()
def stats(
    session: Annotated[
        Optional[str],
        typer.Option("--session", "-s", help="Filter by session (supports wildcards)"),
    ] = None,
    after: Annotated[
        Optional[str],
        typer.Option("--after", help="Only include traces after this date"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Compute aggregate statistics across eval traces."""
    import json as json_mod

    from fact_layer.core.eval_cmd import compute_eval_stats, load_traces
    from fact_layer.core.registry import resolve_facts_dir

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    traces = load_traces(facts_dir, session=session, after=after)

    if not traces:
        console.print("No eval traces found.")
        raise typer.Exit(0)

    result = compute_eval_stats(traces)

    if json_output:
        print(json_mod.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
        raise typer.Exit(0)

    date_range = ""
    if after:
        date_range = f"（{after} ~）"
    elif traces:
        first = traces[0].timestamp[:10]
        last = traces[-1].timestamp[:10]
        if first != last:
            date_range = f"（{first} ~ {last}）"
        else:
            date_range = f"（{first}）"

    console.print(f"[bold]FL 效果指标{date_range}[/bold]")
    console.print("───────────────────────────────────")
    console.print(f"总 turns:          {result.total_turns}")
    console.print(f"总 steps:         {result.total_steps}")

    console.print()
    console.print("[bold]核心指标 — 事实获取来源:[/bold]")
    fl_n = result.fl_vs_doc.get("fl", 0)
    doc_n = result.fl_vs_doc.get("doc", 0)
    total_fd = fl_n + doc_n
    if total_fd > 0:
        console.print(f"  FL:              {fl_n:>3} 次  ({fl_n*100//total_fd}%)  ← FL 提供")
        console.print(f"  文档:            {doc_n:>3} 次  ({doc_n*100//total_fd}%)  ← FL 应替代的")
    else:
        console.print("  （无 FL/文档来源数据）")

    other_sources = {k: v for k, v in result.sources.items() if k not in ("fl", "doc")}
    if other_sources:
        console.print()
        console.print("[bold]其他工具使用（参考）:[/bold]")
        labels = {"code": "代码", "db": "数据库", "web": "网络", "inference": "推理"}
        for src, count in other_sources.items():
            label = labels.get(src, src)
            console.print(f"  {label}:            {count:>3} 次")

    if result.bypassed:
        console.print()
        total_bypassed = sum(b.count for b in result.bypassed)
        bp_pct = total_bypassed * 100 // result.total_steps if result.total_steps else 0
        console.print(f"[bold]规则绕过:[/bold]           {total_bypassed} 次 ({bp_pct:>2}%)")
        for b in result.bypassed:
            reason_str = " — " + b.reasons[0] if b.reasons else ""
            console.print(f"  {b.rule}:   {b.count}{reason_str}")

    if result.slot_hits:
        console.print()
        console.print("[bold]FL 槽位命中 Top 5:[/bold]")
        for hit in result.slot_hits[:5]:
            console.print(f"  {hit.slot_ref:<35} {hit.count:>3} 次")

    console.print()
    console.print(
        f"L2 标注覆盖率:     {result.total_turns and int(result.l2_coverage * result.total_turns) or 0}"
        f"/{result.total_turns} turns ({int(result.l2_coverage * 100)}%)"
    )

    if result.timing:
        console.print()
        console.print("[bold]过程效率:[/bold]")
        if result.timing.avg_turn_ms:
            console.print(f"  平均 turn 耗时:        {result.timing.avg_turn_ms/1000:.1f}s")
        if result.timing.avg_fl_query_ms is not None:
            console.print(f"  FL 查询平均耗时:        {result.timing.avg_fl_query_ms/1000:.1f}s")
        if result.timing.avg_doc_read_ms is not None:
            console.print(f"  文档查找平均耗时:        {result.timing.avg_doc_read_ms/1000:.1f}s")
        if result.timing.avg_fl_query_ms and result.timing.avg_doc_read_ms:
            ratio = result.timing.avg_doc_read_ms / result.timing.avg_fl_query_ms
            console.print(f"  FL 快了 {ratio:.0f} 倍")

    if result.suggested_slots:
        console.print()
        console.print("[bold]待补充槽位建议（基于 bypassed 记录）:[/bold]")
        for slot in result.suggested_slots:
            console.print(f"  {slot}")


@app.command()
def audit(
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="Claude model to use"),
    ] = "claude-sonnet-4-6",
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt"),
    ] = False,
    fix: Annotated[
        bool,
        typer.Option("--fix", help="Interactively apply fixes from audit findings"),
    ] = False,
    scan_integrity: Annotated[
        bool,
        typer.Option("--scan-integrity", help="Check scan index integrity (no LLM needed)"),
    ] = False,
) -> None:
    """Run an LLM-powered semantic consistency audit across all canonical facts."""
    from fact_layer.core.registry import resolve_facts_dir

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    if scan_integrity:
        from fact_layer.core.scan_integrity import run_scan_integrity

        result = run_scan_integrity(facts_dir)
        if not result.findings:
            console.print("[green]All scan indexes are consistent.[/green]")
            raise typer.Exit(0)

        for finding in result.findings:
            icon = "[red]x[/red]" if finding.severity == "error" else "[yellow]![/yellow]"
            console.print(f"  {icon} [{finding.type}] {finding.description}")
        console.print(f"\n  [bold]{result.summary}[/bold]")

        if any(f.severity == "error" for f in result.findings):
            raise typer.Exit(1)
        return

    from fact_layer.core.auditor import build_audit_prompt, estimate_tokens, run_audit
    from fact_layer.core.editor import parse_value
    from fact_layer.core.suggest_cmd import Suggestion, apply_suggestion

    prompt = build_audit_prompt(facts_dir)
    token_est = estimate_tokens(prompt)
    console.print(f"[bold]Running LLM-powered consistency audit...[/bold]")
    console.print(f"  Input: ~{token_est} tokens, model: {model}\n")

    if not yes:
        if not Confirm.ask("Proceed?", default=True):
            raise typer.Exit(0)

    result = run_audit(facts_dir, model=model)

    if result.error:
        if result.raw_response:
            console.print(f"[yellow]{result.error}[/yellow]\n")
            console.print(result.raw_response)
        else:
            console.print(f"[red]{result.error}[/red]")
        raise typer.Exit(1)

    if not result.findings:
        console.print("[green]All facts are consistent. No issues found.[/green]")
        raise typer.Exit(0)

    type_icons = {
        "contradiction": "[red]![/red] Potential contradiction",
        "staleness": "[yellow]![/yellow] Possible staleness",
        "missing": "[yellow]![/yellow] Missing fact",
        "suggestion": "[blue]*[/blue] Suggestion",
    }

    for finding in result.findings:
        header = type_icons.get(finding.type, f"[yellow]![/yellow] {finding.type}")
        console.print(f"  {header}:")
        if finding.slots:
            console.print(f"     Slots: {', '.join(finding.slots)}")
        console.print(f"     {finding.description}")
        if finding.suggestion:
            console.print(f"     -> {finding.suggestion}")
        console.print()

    console.print(f"  [bold]{result.summary}[/bold]")

    if fix:
        fixable = [f for f in result.findings if f.fixes]
        if not fixable:
            console.print("\n[yellow]No findings have concrete fixes. Use fl suggest for rule-based issues.[/yellow]")
            return

        from fact_layer.core.loader import load_all_categories

        categories = load_all_categories(facts_dir)
        suggestions: list[Suggestion] = []
        for finding in fixable:
            for audit_fix in finding.fixes:
                from fact_layer.core.suggest_cmd import _resolve_current_value

                current = _resolve_current_value(audit_fix.slot, categories)
                suggestions.append(Suggestion(
                    slot=audit_fix.slot,
                    current_value=current,
                    suggested_value=audit_fix.value,
                    reason=finding.suggestion or finding.description,
                ))

        console.print(f"\n[bold]{len(suggestions)} fixable suggestion(s):[/bold]\n")
        applied = 0
        skipped = 0

        for idx, s in enumerate(suggestions, 1):
            console.print(f"  [bold][{idx}/{len(suggestions)}] {s.slot}[/bold]")
            console.print(f"    Current:   {s.current_value}")
            console.print(f"    Suggested: [green]{s.suggested_value}[/green]")
            console.print(f"    Reason:    {s.reason}")

            if yes:
                action = "y"
            else:
                action = Prompt.ask(
                    "    [Y] accept  [e] edit  [n] skip",
                    choices=["y", "e", "n"],
                    default="y",
                )

            if action == "y":
                apply_suggestion(facts_dir, s)
                console.print(f"    [green]Applied.[/green]\n")
                applied += 1
            elif action == "e":
                edited = Prompt.ask("    New value", default=str(s.suggested_value))
                parsed = parse_value(edited)
                s.suggested_value = parsed
                apply_suggestion(facts_dir, s, source="human")
                console.print(f"    [green]Applied (edited).[/green]\n")
                applied += 1
            else:
                console.print(f"    [dim]Skipped.[/dim]\n")
                skipped += 1

        console.print(f"  [bold]Done: {applied} applied, {skipped} skipped.[/bold]")
