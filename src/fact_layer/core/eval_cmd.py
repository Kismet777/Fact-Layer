from __future__ import annotations

import re
from collections import Counter
from fnmatch import fnmatch
from pathlib import Path

from fact_layer.core.loader import _load_yaml
from fact_layer.core.writer import dump_yaml
from fact_layer.models.eval import (
    BypassDetail,
    EvalStats,
    EvalStep,
    EvalSummary,
    EvalTrace,
    SlotHit,
    TimingStats,
)


def _sanitize_filename(s: str) -> str:
    return re.sub(r"[^\w\-]", "_", s)


def trace_filename(trace: EvalTrace) -> str:
    """The canonical on-disk filename for a trace (single source of the naming).

    Deterministic from the trace's own fields, so evidence extraction can
    reconstruct a ``trace_ref`` without carrying the path around.
    """
    ts_safe = trace.timestamp.replace(":", "-")
    session_safe = _sanitize_filename(trace.session_id)
    return f"{ts_safe}_{session_safe}_turn-{trace.turn:03d}.yaml"


def save_trace(facts_dir: Path, trace: EvalTrace) -> Path:
    eval_dir = facts_dir / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)

    filename = trace_filename(trace)
    out_path = eval_dir / filename

    dump_yaml(out_path, trace.model_dump(mode="json"))

    pending_dir = eval_dir / "pending"
    if pending_dir.is_dir():
        session_safe = _sanitize_filename(trace.session_id)
        pattern = f"{session_safe}_turn-{trace.turn:03d}.*"
        for p in pending_dir.glob(pattern):
            p.unlink()

    return out_path


def load_traces(
    facts_dir: Path,
    *,
    session: str | None = None,
    source: str | None = None,
    bypassed: bool = False,
    after: str | None = None,
) -> list[EvalTrace]:
    eval_dir = facts_dir / "eval"
    if not eval_dir.is_dir():
        return []

    traces: list[EvalTrace] = []
    for f in sorted(eval_dir.glob("*.yaml")):
        data = _load_yaml(f)
        if not data:
            continue
        try:
            trace = EvalTrace.model_validate(data)
        except Exception:
            continue

        if session and not fnmatch(trace.session_id, session):
            continue

        if after and trace.timestamp < after:
            continue

        if source:
            has_source = any(s.source == source for s in trace.steps)
            if not has_source:
                continue

        if bypassed:
            has_bypassed = any(s.bypassed is not None for s in trace.steps)
            if not has_bypassed:
                continue

        traces.append(trace)

    return traces


def prune_traces(
    facts_dir: Path,
    sessions: list[str],
    *,
    dry_run: bool = False,
) -> dict:
    """Remove eval trace files whose session_id matches any of `sessions`.

    `sessions` entries are matched with fnmatch (exact ids or globs). Used to
    excise misrouted / cross-project traces from an eval store. Safety: an empty
    `sessions` list is a no-op — this never mass-deletes without explicit targets.

    Returns {"matched": [{file, session, turn}], "removed": [file, ...]}. With
    dry_run=True nothing is deleted; `matched` still lists what would be removed.
    """
    report: dict = {"matched": [], "removed": []}
    if not sessions:
        return report

    eval_dir = facts_dir / "eval"
    if not eval_dir.is_dir():
        return report

    for f in sorted(eval_dir.glob("*.yaml")):
        data = _load_yaml(f)
        if not data:
            continue
        try:
            trace = EvalTrace.model_validate(data)
        except Exception:
            continue

        if not any(fnmatch(trace.session_id, pat) for pat in sessions):
            continue

        report["matched"].append(
            {"file": f.name, "session": trace.session_id, "turn": trace.turn}
        )
        if not dry_run:
            f.unlink()
            report["removed"].append(f.name)

    return report


def _extract_slot_ref(step: EvalStep) -> str | None:
    if step.type != "tool_call" or step.tool not in ("facts_get", "facts_list"):
        return None
    if not step.args:
        return None
    slot = step.args.get("slot")
    if slot:
        return slot
    category = step.args.get("category")
    if category:
        return category
    return None


def compute_eval_stats(traces: list[EvalTrace]) -> EvalStats:
    if not traces:
        return EvalStats(
            total_turns=0,
            total_steps=0,
            sources={},
            fl_vs_doc={},
            bypassed=[],
            slot_hits=[],
            l2_coverage=0.0,
            suggested_slots=[],
            harness_breakdown={},
        )

    total_steps = 0
    source_counter: Counter[str] = Counter()
    fl_count = 0
    doc_count = 0
    bypass_counter: Counter[str] = Counter()
    bypass_reasons: dict[str, list[str]] = {}
    slot_counter: Counter[str] = Counter()
    harness_counter: Counter[str] = Counter()
    turns_with_l2 = 0
    turn_durations: list[int] = []
    fl_durations: list[int] = []
    doc_durations: list[int] = []
    db_durations: list[int] = []
    bypass_doc_refs: set[str] = set()

    for trace in traces:
        total_steps += len(trace.steps)
        harness_counter[trace.harness] += 1

        has_l2 = False
        for step in trace.steps:
            if step.source:
                source_counter[step.source] += 1
                # NOTE: source is an L1 signal — it must NOT count as L2 coverage.
                # Real L2 (rationale/result_used_for/conclusion) is checked below.
                if step.source == "fl":
                    fl_count += 1
                    if step.duration_ms is not None:
                        fl_durations.append(step.duration_ms)
                elif step.source == "doc":
                    doc_count += 1
                    if step.duration_ms is not None:
                        doc_durations.append(step.duration_ms)
                elif step.source == "db":
                    if step.duration_ms is not None:
                        db_durations.append(step.duration_ms)

            if step.rationale or step.result_used_for or step.conclusion:
                has_l2 = True

            if step.bypassed:
                bypass_counter[step.bypassed.rule] += 1
                bypass_reasons.setdefault(step.bypassed.rule, []).append(
                    step.bypassed.reason
                )
                if step.result_used_for:
                    bypass_doc_refs.add(step.result_used_for)

            slot_ref = _extract_slot_ref(step)
            if slot_ref:
                slot_counter[slot_ref] += 1

        if has_l2:
            turns_with_l2 += 1

        if trace.summary.turn_duration_ms is not None:
            turn_durations.append(trace.summary.turn_duration_ms)

    bypassed_details = [
        BypassDetail(
            rule=rule,
            count=count,
            reasons=list(dict.fromkeys(bypass_reasons.get(rule, []))),
        )
        for rule, count in bypass_counter.most_common()
    ]

    slot_hits = [
        SlotHit(slot_ref=slot, count=count)
        for slot, count in slot_counter.most_common()
    ]

    fl_plus_doc = fl_count + doc_count
    fl_ratio = fl_count / fl_plus_doc if fl_plus_doc > 0 else None

    l2_coverage = turns_with_l2 / len(traces) if traces else 0.0

    timing = None
    if turn_durations or fl_durations or doc_durations:
        timing = TimingStats(
            avg_turn_ms=sum(turn_durations) / len(turn_durations) if turn_durations else 0,
            avg_fl_query_ms=sum(fl_durations) / len(fl_durations) if fl_durations else None,
            avg_doc_read_ms=sum(doc_durations) / len(doc_durations) if doc_durations else None,
            avg_db_query_ms=sum(db_durations) / len(db_durations) if db_durations else None,
        )

    # suggested_slots must derive ONLY from "missing slot" bypasses (rule 缺槽位) —
    # NOT from "已有未用" (discoverability) findings, whose reasons also mention "槽位"
    # ("未引用 FL 的槽位"). Key off the bypass RULE, not fragile reason-text matching.
    # Dedup reasons (the old logic could append the same reason repeatedly).
    suggested_slots: list[str] = []
    _seen_reasons: set[str] = set()
    for detail in bypassed_details:
        rule_l = detail.rule.lower()
        is_missing = "缺" in detail.rule or "未覆盖" in detail.rule or "missing" in rule_l
        if not is_missing:
            continue
        for reason in detail.reasons:
            if reason not in _seen_reasons:
                _seen_reasons.add(reason)
                suggested_slots.append(reason)

    return EvalStats(
        total_turns=len(traces),
        total_steps=total_steps,
        sources=dict(source_counter.most_common()),
        fl_vs_doc={"fl": fl_count, "doc": doc_count},
        fl_ratio=fl_ratio,
        bypassed=bypassed_details,
        slot_hits=slot_hits,
        l2_coverage=l2_coverage,
        timing=timing,
        suggested_slots=suggested_slots,
        harness_breakdown=dict(harness_counter.most_common()),
    )
