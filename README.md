# fact-layer

**Structured, consistency-checked project facts for AI coding agents.**

> Prevent inconsistency at the source through structure, rather than detect it downstream.

fact-layer gives AI coding agents (Claude Code, Codex, Cursor, Aider, etc.) a **single source of truth** about your project — with schema enforcement, dependency tracking, and automated consistency checks.

## The Problem

CLAUDE.md, AGENTS.md, and `.cursorrules` are plain text — no structure, no versioning, no dependency tracking. When project facts contradict each other or go stale, your AI agent silently makes decisions on unreliable context.

The industry's answer is **reactive**: free-form input → embedding dedup → LLM cleanup. fact-layer takes the opposite approach — **preventive**: schema enforcement → unique indexing → dependency graph checks → LLM audit. Control quality at the source, not downstream.

## How It Works

```
.facts/
├── framework.yaml          # Category config, tier thresholds
├── dependencies.yaml       # Explicit dependency graph between slots
├── canonical/              # Your project facts (structured YAML)
│   ├── project-overview.yaml
│   ├── tech-stack.yaml
│   ├── architecture.yaml
│   ├── conventions.yaml
│   ├── work-in-progress.yaml
│   ├── decisions.yaml
│   └── ...                 # data-model, api-contracts, testing, etc.
└── snapshot.md             # Exported markdown for agent consumption
```

Each fact is a **slot** with structured metadata:

```yaml
database:
  value: "PostgreSQL 16"
  meta:
    source: human              # human | agent-analysis | code-extracted
    confidence: high           # high | medium | low
    status: active             # active | uncertain | stale | superseded
    updated: "2026-06-09"
    verified: "2026-06-09"
    reason: "Need JSONB support and CTE performance"
```

## Three-Layer Consistency Model

```
Layer 0 — Structural Prevention
  Schema + unique index (category, slot, scope)
  Eliminates 80% of uniqueness issues at the source. Zero AI cost.

Layer 1 — Dependency-Driven Checks (fl check)
  Catches cross-slot inconsistencies via the dependency graph.
  LLM scope bounded by graph edges — O(edges), not O(slots²).

Layer 2 — LLM Semantic Audit (fl audit)
  Safety net for accumulated drift.
  Finds contradictions and gaps that structural checks can't see.
```

## Install

```bash
pipx install fact-layer
```

Or for development:

```bash
git clone https://github.com/Kismet777/Fact-Layer.git
cd fact-layer
pip install -e ".[dev]"
```

## Quick Start

### 1. Initialize

```bash
cd my-project
fl init
```

Interactive prompts guide you through project name, language, and which extension categories to enable.

### 2. Fill in facts

Edit `.facts/canonical/*.yaml` — each slot has comments explaining its purpose and example values.

### 3. Validate consistency

```bash
fl check
```

Runs four checks: structural integrity, staleness, dependency consistency, and decision tracking.

```
Checking facts consistency...

  Structural:
  x testing — category enabled but empty

  Dependencies:
  x tech-stack.database updated 2026-06-09
     but build-deploy.docker last updated 2026-05-01
     derives-from: downstream must be updated

  Summary: 2 errors, 0 warnings
```

### 4. Check impact before changing a fact

```bash
fl impact tech-stack.database
```

```
Impact analysis for tech-stack.database

  Direct dependencies:
  ├── data-model.database-type     derives-from       (MUST update)
  ├── build-deploy.docker          constrains         (should check)
  └── testing.commands             constrains         (should check)

  From decisions:
  └── DEC-001 "Choose PostgreSQL"    affects this slot
```

### 5. View facts health

```bash
fl status
```

```
Facts Status

  Stable Layer
  v project-overview    5/5 slots    verified today
  v tech-stack          5/6 slots    verified today
  v architecture        3/3 slots    verified today

  Dynamic Layer
  v data-model          3/4 slots    verified today
  ! api-contracts       2/4 slots    1 stale

  Working Layer
  v work-in-progress    2/5 slots    verified today
  v decisions           1 active decisions

  Overall: 24/35 slots filled · 1 stale · 0 category empty
```

### 6. Export for agent consumption

```bash
fl export              # writes to .facts/snapshot.md
fl export --stdout     # pipe to other tools
fl export -o ctx.md    # custom output path
```

Generates a clean markdown snapshot — only active slots, no noise. Paste into CLAUDE.md or feed to any coding agent.

### 7. LLM-powered semantic audit

```bash
fl audit
```

Calls Claude to find semantic contradictions, staleness signals, and missing implications that structural checks can't catch.

```
Running LLM-powered consistency audit...
  Input: ~1200 tokens, model: claude-sonnet-4-6

  ! Potential contradiction:
     Slots: project-overview.purpose, api-contracts.style
     purpose says "REST API service" but api style is "gRPC"
     -> Confirm if migration happened, then update purpose

  * Suggestion:
     Slots: tech-stack.external-services
     architecture mentions "LLM Gateway" but external-services is empty
     -> Consider filling external-services for completeness

  2 warnings, 1 suggestion
```

## Dependency Graph

The dependency graph (`dependencies.yaml`) defines five relationship types:

| Relation | Meaning | On source change |
|----------|---------|-----------|
| `derives-from` | B's value is determined by A | B **must** update |
| `references` | B references an entity in A | B may **break** |
| `constrains` | A constrains what B can be | B **should** be checked |
| `implies` | A being true implies B should exist | Check if B exists |
| `conflicts-with` | A and B can't hold certain values together | Check B compatibility |

`fl check` uses this graph to catch "changed one thing but forgot to update the related thing" — the most common source of stale context for AI agents.

## Fact Framework

Facts are organized into three tiers by change frequency:

| Tier | Categories | Stale threshold |
|------|-----------|----------------|
| **Stable** | project-overview, tech-stack, architecture, conventions | 90 days |
| **Dynamic** | data-model, api-contracts, testing, build-deploy, security | 30 days |
| **Working** | work-in-progress, decisions | 7 days |

Core categories (stable tier) are always enabled. Extension and optional categories are opt-in during `fl init`.

## Configuration

`framework.yaml` controls the project setup:

```yaml
project_name: my-project
tiers:
  stable:
    description: Foundational facts that rarely change
    stale_threshold_days: 90
  dynamic:
    description: Facts that change with development
    stale_threshold_days: 30
  working:
    description: Frequently changing operational facts
    stale_threshold_days: 7

extensions:
  enabled: [data-model, testing, build-deploy]
optional:
  enabled: [decisions]
```

## Development

```bash
git clone https://github.com/Kismet777/Fact-Layer.git
cd fact-layer
pip install -e ".[dev]"
pytest                  # 95 tests
```

## Tech Stack

- **Python 3.12+**
- [Typer](https://typer.tiangolo.com/) + [Rich](https://rich.readthedocs.io/) — CLI framework
- [Pydantic v2](https://docs.pydantic.dev/) — schema validation
- [ruamel.yaml](https://yaml.readthedocs.io/) — YAML read/write preserving comments
- [Anthropic SDK](https://docs.anthropic.com/) — LLM-powered audit
- [Jinja2](https://jinja.palletsprojects.com/) — export template rendering

## License

MIT
