# fact-layer

Structured, consistency-checked project facts for AI coding agents.

## The Problem

CLAUDE.md, AGENTS.md, and `.cursorrules` are plain text — no structure, no versioning, no dependency tracking. When project facts contradict each other or go stale, your AI agent makes decisions on unreliable context.

**fact-layer** takes a different approach: instead of free-form text, it uses **structured YAML slots** with metadata, an **explicit dependency graph** between facts, and **automated consistency checks** — from structural validation to LLM-powered semantic audits.

The core design philosophy: **prevent inconsistency at the source through structure, rather than detect it downstream.**

## What You Get

```
.facts/
├── framework.yaml          # Category definitions, tier config, stale thresholds
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

Each fact slot carries metadata:

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

## Install

```bash
pipx install fact-layer
```

Or for development:

```bash
git clone https://github.com/nokismet/fact-layer.git
cd fact-layer
pip install -e ".[dev]"
```

## Quick Start

### 1. Initialize

```bash
cd my-project
fl init
```

Interactive prompts guide you through project name, language, and which extension categories to enable (data-model, api-contracts, testing, build-deploy, security).

### 2. Fill in facts

Edit `.facts/canonical/*.yaml` files. Each slot has comments explaining its purpose and example values.

### 3. Validate consistency

```bash
fl check
```

Runs four types of checks:
- **Structural** — required slots filled, categories not empty
- **Staleness** — slots not verified beyond tier threshold (stable: 90d, dynamic: 30d, working: 7d)
- **Dependencies** — upstream slot updated but downstream not (e.g., changed database but didn't update docker config)
- **Decisions** — active decisions whose affected slots haven't been updated

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
fl export --stdout     # pipe to other commands
fl export -o ctx.md    # custom output path
```

Generates a clean markdown snapshot that you can paste into CLAUDE.md or feed to any coding agent. Only active slots are included; superseded/stale facts are filtered out.

### 7. LLM-powered semantic audit

```bash
fl audit
```

Calls Claude to analyze all facts for semantic contradictions, staleness signals, and missing implications that structural checks can't catch.

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

The dependency graph (`dependencies.yaml`) defines five relationship types between slots:

| Relation | Meaning | On change |
|----------|---------|-----------|
| `derives-from` | B's value is determined by A | A changes → B **must** update |
| `references` | B references an entity defined in A | A's entity renamed/deleted → B breaks |
| `constrains` | A constrains what B can be | A changes → B **should** be checked |
| `implies` | A being true implies B should exist | A added → check if B exists |
| `conflicts-with` | A and B can't hold certain values together | A changes → check B compatibility |

`fl check` uses this graph to catch "changed one thing but forgot to update the related thing" — the most common source of stale context.

## Three-Layer Consistency

```
Layer 0 — Structural prevention (schema + unique index)
  → Eliminates 80% of uniqueness issues at the source
  → Zero AI cost

Layer 1 — Dependency-driven checks (fl check)
  → Catches cross-slot inconsistencies using the dependency graph
  → LLM scope bounded by graph — O(D) not O(N)

Layer 2 — LLM semantic audit (fl audit)
  → Safety net for accumulated drift
  → Finds issues structural checks can't see
```

## Fact Framework

Facts are organized into three tiers by change frequency:

| Tier | Categories | Stale threshold |
|------|-----------|----------------|
| **Stable** | project-overview, tech-stack, architecture, conventions | 90 days |
| **Dynamic** | data-model, api-contracts, testing, build-deploy, security | 30 days |
| **Working** | work-in-progress, decisions | 7 days |

Core categories are always enabled. Extension categories (data-model, api-contracts, etc.) are opt-in during `fl init`.

## Tech Stack

- Python 3.12+
- [Typer](https://typer.tiangolo.com/) + [Rich](https://rich.readthedocs.io/) — CLI framework
- [Pydantic v2](https://docs.pydantic.dev/) — schema validation
- [ruamel.yaml](https://yaml.readthedocs.io/) — YAML read/write preserving comments
- [Anthropic SDK](https://docs.anthropic.com/) — LLM audit
- [Jinja2](https://jinja.palletsprojects.com/) — export template rendering

## License

MIT
