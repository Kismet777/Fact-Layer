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
) -> None:
    """Export all canonical facts as a single markdown snapshot for agent consumption."""
    from fact_layer.core.exporter import render_export
    from fact_layer.core.registry import resolve_facts_dir

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    md = render_export(facts_dir)

    if stdout:
        print(md)
    else:
        out_path = Path(output) if output else facts_dir / "snapshot.md"
        out_path.write_text(md, encoding="utf-8")
        console.print(f"[green]Exported to {out_path}[/green]")


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
) -> None:
    """Run an LLM-powered semantic consistency audit across all canonical facts."""
    from fact_layer.core.auditor import AuditFinding, build_audit_prompt, estimate_tokens, run_audit
    from fact_layer.core.registry import resolve_facts_dir

    facts_dir = resolve_facts_dir()
    if not facts_dir:
        console.print("[red]No .facts/ directory found. Run 'fl init' first.[/red]")
        raise typer.Exit(1)

    prompt = build_audit_prompt(facts_dir)
    token_est = estimate_tokens(prompt)
    console.print(f"[bold]Running LLM-powered consistency audit...[/bold]")
    console.print(f"  Input: ~{token_est} tokens, model: {model}\n")

    if not yes:
        from rich.prompt import Confirm
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
