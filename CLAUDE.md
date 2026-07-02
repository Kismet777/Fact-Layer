# fact-layer

Structured, consistency-checked project facts for AI coding agents.

**Structured knowledge:** `.facts/` directory — run `fl export --stdout` for the full snapshot, `fl check` for consistency validation.

## Core architecture

```
project files → scan (extract) → candidate facts → review → canonical YAML (.facts/canonical/)
                                                              ↓
agent queries ← export/exporter.py ← loader ← checker (structural + staleness + dependency + decisions)
                                                              ↓
                                          editor (set/add/deprecate) → audit (LLM semantic check)
```

- **Preventive pipeline:** schema guard → index dedup → dependency graph → LLM audit (not reactive cleanup)
- **Writer unified to `fl set`:** single entry point for all fact writes; agent + batch + scan all go through it
- **Scanner frozen:** Phase 1 (config extractors) + Phase 2 (markdown LLM extractor) retained; no new extractors planned
- **FL-009 cancelled:** code structure analyzer won't be built (code extraction unreliable)

## Key design decisions (not in code)

- **Unique index `(category, slot, scope)`** reduces uniqueness from semantic to index-level matching
- **Human declaration + machine verification:** ETH Zurich research showed LLM-auto-generated context reduces success rate on 5/8 tasks
- **FL manages validation and consistency; agent manages discovery and writing**

## Project structure

```
src/fact_layer/
  cli.py              # typer CLI (fl init/check/set/add/scan/suggest/audit/export/status/impact/eval)
  mcp_server.py       # MCP server for Claude Code integration
  core/
    loader.py         # YAML → CategoryFile models
    checker.py        # Structural + staleness + dependency + decision checks
    editor.py         # set_slot, add_slot, deprecate_slot, set_batch
    writer.py          # Low-level YAML write
    auditor.py         # LLM semantic audit (now uses unified llm_call)
    suggest_cmd.py     # LLM fix suggestions from check issues
    eval_cmd.py        # Eval trace logging and analysis
    exporter.py        # Markdown export for agent consumption
    impact_cmd.py      # Downstream dependency impact analysis
    status_cmd.py      # Health overview
    init_cmd.py        # .facts/ directory initialization
    registry.py        # Category resolution, tier config
    llm.py             # Unified LLM call: Anthropic + OpenAI backends
    scanner/
      pipeline.py      # Scan orchestration
      candidates.py    # File discovery
      dedup.py         # Candidate dedup
      indexes.py        # Source + extraction indexes for incremental scan
      extractors/
        config.py      # Config file extractors (pyproject, Dockerfile, CI, etc.)
        markdown.py    # LLM-powered Markdown extractor
  models/
    category.py, slot.py, dependency.py, framework.py, eval.py
  templates/
    framework.yaml, dependencies.yaml, canonical/*.yaml, audit_prompt.txt, suggest_prompt.txt
```

## Dev commands

```bash
fl check                    # Validate facts consistency
fl status                   # Health overview
fl export --stdout          # Full markdown snapshot
pytest tests/ -x            # Run tests (376 passed)
```

## LLM backend

- **Anthropic endpoint:** used when `ANTHROPIC_API_KEY` is set (Claude Code uses this)
- **OpenAI-compatible endpoint:** used when `OPENAI_API_KEY` is set (for DeepSeek via `api.deepseek.com/v1`)
  - **Why OpenAI endpoint for DeepSeek:** DeepSeek's Anthropic-compatible endpoint puts all content in `thinking` blocks (not `text` blocks) for thinking models, causing FL to parse empty responses
- Priority: `OPENAI_API_KEY`/`OPENAI_BASE_URL` checked first, then `ANTHROPIC_API_KEY`

## Current state

- FL-017 (batch set + auto-audit + MCP tools) deployed
- LLM unified call refactoring (`llm.py`) in progress — uncommitted
- Test time-bomb fixed (`_slot()` defaults changed to `date.today()`)
- `.facts/` dogfood initialized with 9 categories, all checks passing
