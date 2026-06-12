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
) -> None:
    """Scan project files to extract facts for .facts/ slots.

    Reads config files (pyproject.toml, Dockerfile, docker-compose, package.json, CI)
    and proposes candidate facts. Review and accept to populate your fact layer.
    """
    import json as json_mod

    from fact_layer.core.registry import resolve_facts_dir
    from fact_layer.core.scanner.pipeline import run_scan

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    project_root = facts_dir.parent
    categories = [c.strip() for c in category.split(",")] if category else None

    result = run_scan(
        project_root=project_root,
        paths=paths or None,
        categories=categories,
    )

    if json_output:
        print(json_mod.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
        raise typer.Exit(0)

    # --- Summary header ---
    console.print(f"[bold]Scan complete:[/bold] {result.stats.files_scanned} files scanned\n")

    if not result.candidates and not result.conflicts:
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

    console.print(
        f"  [bold]Summary: {result.stats.candidates_found} candidates"
        f" · {result.stats.conflicts} conflicts[/bold]"
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
) -> None:
    """Run an LLM-powered semantic consistency audit across all canonical facts."""
    from fact_layer.core.auditor import build_audit_prompt, estimate_tokens, run_audit
    from fact_layer.core.editor import parse_value
    from fact_layer.core.registry import resolve_facts_dir
    from fact_layer.core.suggest_cmd import Suggestion, apply_suggestion

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

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
