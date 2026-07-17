"""FL-019: tool-agnostic FL access logging (L1 backbone).

Every FL *read* path (get/list/check/export, via CLI and MCP) appends one line to
`.facts/eval/access.jsonl`. This is the universal floor of eval coverage:

- No hook, no prompt, no transcript, no LLM. Codex / Claude / a bare script all get
  L1 the moment they touch FL — because FL logs its own access, not the harness.
- Complements (does not replace) transcript ingest. Transcript adapters give L1+L2 for
  tools that persist sessions; access.jsonl guarantees at least L1 for everything else.

Design invariant: logging is best-effort and MUST NEVER break the caller. A read-only
FL command that failed because its telemetry write raised would be a strictly worse
tool. Every path here swallows its own exceptions and returns None.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fact_layer.models.eval import AccessStats, SlotHit


def _access_path(facts_dir: Path) -> Path:
    return facts_dir / "eval" / "access.jsonl"


def log_access(
    facts_dir: Path | None,
    op: str,
    *,
    slot: str | None = None,
    args: dict[str, Any] | None = None,
    caller: str | None = None,
    via: str | None = None,
) -> None:
    """Append one access record. Best-effort; never raises.

    Two orthogonal attribution axes are recorded:
    - ``caller`` = the *harness* (codex / claude-code / …). This is the FL-019 axis.
      Sourced from $FL_CALLER (set by the tool's MCP config or notify/hook wrapper),
      falling back to "unknown". The interface layer must NOT override it — when Codex
      runs `fl export`, the meaningful attribution is "codex", not "cli".
    - ``via`` = the *interface* it came through (cli / mcp). Secondary; lets us tell a
      live agent MCP query from a batch/hook/manual CLI run.

    Args:
        facts_dir: The resolved .facts/ directory (None → no-op).
        op: The read operation (get/list/check/export).
        slot: The slot/category referenced, if any.
        args: Extra call args; stored as a truncated JSON digest.
        caller: Explicit harness override (rare). Defaults to $FL_CALLER, else "unknown".
        via: The interface the call arrived through (cli/mcp).
    """
    try:
        if facts_dir is None:
            return
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "op": op,
            "caller": caller or os.environ.get("FL_CALLER") or "unknown",
        }
        if via:
            record["via"] = via
        if slot:
            record["slot"] = slot
        if args:
            try:
                record["args"] = json.dumps(args, ensure_ascii=False, sort_keys=True)[:200]
            except Exception:
                pass
        eval_dir = facts_dir / "eval"
        eval_dir.mkdir(parents=True, exist_ok=True)
        with _access_path(facts_dir).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        return


def log_search(
    facts_dir: Path | None,
    query: str,
    hit_refs: list[str],
    *,
    via: str | None = None,
    caller: str | None = None,
) -> None:
    """Log one search invocation + one touch record per surfaced slot.

    Two record kinds keep invocation-level and touch-level metrics separable:
    - ``op="search"`` (slot=None, args={query, hits}) — one per call. Drives
      empty-result rate and search→get conversion (a 5-hit search is still ONE call).
    - ``op="search-hit"`` (slot=slot_ref) — one per surfaced slot. Feeds the slot×op
      cross-tab, consistently with ``get`` being a per-slot touch.

    Best-effort; never raises (delegates to log_access, which swallows).
    """
    log_access(
        facts_dir,
        "search",
        args={"query": query, "hits": len(hit_refs)},
        via=via,
        caller=caller,
    )
    for ref in hit_refs:
        log_access(facts_dir, "search-hit", slot=ref, via=via, caller=caller)


def read_access(facts_dir: Path) -> list[dict]:
    """Read access.jsonl defensively (skip blank/corrupt lines). Never raises."""
    records: list[dict] = []
    try:
        path = _access_path(facts_dir)
        if not path.is_file():
            return records
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return records
    return records


def _search_hits(rec: dict) -> int:
    """Recover the hit count from a search invocation record's args JSON.

    args is stored as a (truncated) JSON string; a malformed/absent value is
    treated as 0 hits so we never crash on telemetry and stay on the safe side.
    """
    raw = rec.get("args")
    if not raw:
        return 0
    try:
        return int(json.loads(raw).get("hits", 0))
    except Exception:
        return 0


def compute_access_stats(facts_dir: Path) -> AccessStats:
    """Aggregate access.jsonl into AccessStats (by caller / op / slot + time range)."""
    records = read_access(facts_dir)
    if not records:
        return AccessStats(total=0)

    caller_counter: Counter[str] = Counter()
    op_counter: Counter[str] = Counter()
    via_counter: Counter[str] = Counter()
    slot_counter: Counter[str] = Counter()
    slot_op_counter: dict[str, Counter[str]] = {}
    timestamps: list[str] = []
    search_total = 0
    search_empty = 0

    for rec in records:
        op = str(rec.get("op") or "unknown")
        caller_counter[str(rec.get("caller") or "unknown")] += 1
        op_counter[op] += 1
        via = rec.get("via")
        if via:
            via_counter[str(via)] += 1
        slot = rec.get("slot")
        if slot:
            slot_counter[str(slot)] += 1
            slot_op_counter.setdefault(str(slot), Counter())[op] += 1
        ts = rec.get("ts")
        if ts:
            timestamps.append(str(ts))
        if op == "search":
            search_total += 1
            if _search_hits(rec) == 0:
                search_empty += 1

    # slot-level search→get conversion, straight off the cross-tab.
    searched = [ops for ops in slot_op_counter.values() if ops.get("search-hit")]
    converted = sum(1 for ops in searched if ops.get("get"))
    search_to_get_rate = (converted / len(searched)) if searched else None

    timestamps.sort()
    return AccessStats(
        total=len(records),
        by_caller=dict(caller_counter.most_common()),
        by_op=dict(op_counter.most_common()),
        by_via=dict(via_counter.most_common()),
        top_slots=[SlotHit(slot_ref=s, count=c) for s, c in slot_counter.most_common(10)],
        by_slot_op={s: dict(c.most_common()) for s, c in slot_op_counter.items()},
        search_total=search_total,
        search_empty=search_empty,
        search_empty_rate=(search_empty / search_total) if search_total else None,
        search_to_get_rate=search_to_get_rate,
        first_ts=timestamps[0] if timestamps else None,
        last_ts=timestamps[-1] if timestamps else None,
    )
