"""eval-L3 T2 observation layer — S0 storage + S1 extract / judge / report.

T2 = replay real chains and have an LLM rate every FL read A/B/C, producing an
"adoption rate" (facts correctly adopted). This is the *observational* ceiling —
NOT causal ablation (that is S2/S3, deliberately out of scope here).

Invariants (spec §1):
- A/B/C comes from the LLM reading the evidence — never a regex/string match on
  reasoning (``_parse_verdict`` only *parses* the model's JSON, it never classifies).
- The evidence bundle carries the reasoning steps ADJACENT to the read, because the
  decisive signal usually lives there, not in the read step's own fields.
- Judgements are idempotent by ``event_id`` and append-only; a re-run hits the cache
  and does not re-call the LLM.
- This module is a leaf: it never touches the get/list/export read hot path, and an
  LLM backend failure degrades one event to ``unknown`` without crashing the run.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fact_layer.core.eval_cmd import compute_eval_stats, load_traces, trace_filename
from fact_layer.models.eval import EvalStep, EvalTrace
from fact_layer.models.eval_results import (
    ABCJudgement,
    EvidenceBundle,
    T2Report,
    make_event_id,
)

# The FL read tools whose calls become T2 read events.
FL_READ_TOOLS = ("facts_get", "facts_list", "facts_search", "facts_export")


# --------------------------------------------------------------------------- #
# S0 — verdict storage + idempotent cache
# --------------------------------------------------------------------------- #


def _results_path(facts_dir: Path) -> Path:
    return facts_dir / "eval" / "results" / "t2_verdicts.jsonl"


def save_verdict(facts_dir: Path, judgement: ABCJudgement) -> None:
    """Append one judgement to the verdict store. Best-effort; never raises.

    Mirrors ``save_trace`` / ``log_access``: telemetry writes must never break the
    caller. Append-only — re-judging appends a new row and read-back keeps the latest.
    """
    try:
        results_dir = facts_dir / "eval" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        with _results_path(facts_dir).open("a", encoding="utf-8") as f:
            f.write(json.dumps(judgement.model_dump(mode="json"), ensure_ascii=False) + "\n")
    except Exception:
        return


def load_verdict_cache(facts_dir: Path) -> dict[str, ABCJudgement]:
    """Load verdicts keyed by ``event_id`` (latest wins). Defensive; never raises."""
    cache: dict[str, ABCJudgement] = {}
    try:
        path = _results_path(facts_dir)
        if not path.is_file():
            return cache
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    j = ABCJudgement.model_validate_json(line)
                except Exception:
                    continue
                # append order == chronological; overwrite so the latest wins.
                cache.pop(j.event_id, None)
                cache[j.event_id] = j
    except Exception:
        return cache
    return cache


# --------------------------------------------------------------------------- #
# S1a — evidence extraction (pure)
# --------------------------------------------------------------------------- #


def _is_fl_read(step: EvalStep) -> bool:
    return step.type == "tool_call" and (
        (step.tool in FL_READ_TOOLS) or step.source == "fl"
    )


def _read_slot_ref(step: EvalStep) -> str | None:
    # facts_get/list carry slot|category; search/export have no single slot.
    if step.tool in ("facts_get", "facts_list") and step.args:
        return step.args.get("slot") or step.args.get("category")
    return None


def _reasoning_text(step: EvalStep) -> str:
    parts = [step.rationale, step.result_used_for, step.conclusion]
    return " ".join(p for p in parts if p)


def _summarize_args(args: dict | None) -> str:
    if not args:
        return ""
    try:
        return json.dumps(args, ensure_ascii=False, sort_keys=True)[:200]
    except Exception:
        return ""


def extract_evidence(traces: list[EvalTrace]) -> list[EvidenceBundle]:
    """Pure: turn each FL-read step into an EvidenceBundle. No IO, no LLM.

    ``reasoning_span`` = the read step's own L2 (rationale/result_used_for/
    conclusion) PLUS every contiguous ``reasoning`` step immediately before and
    after it (bounded by the next tool_call). This is spec red-line 2: the
    decisive "verify vs fall-back" signal lives in those neighbouring sentences.

    ``downstream_actions`` = the tool_call steps after the read, up to the next FL
    read or the turn end — this is how the judge spots B (read FL, then went to
    bash/source to re-fetch the same info).
    """
    bundles: list[EvidenceBundle] = []
    for trace in traces:
        steps = trace.steps
        n = len(steps)
        for i, step in enumerate(steps):
            if not _is_fl_read(step):
                continue

            span: list[str] = []
            # preceding contiguous reasoning steps (walk back to the nearest tool_call)
            preceding: list[str] = []
            j = i - 1
            while j >= 0 and steps[j].type == "reasoning":
                t = _reasoning_text(steps[j])
                if t:
                    preceding.append(t)
                j -= 1
            preceding.reverse()
            span.extend(preceding)
            # the read step's own L2
            self_text = _reasoning_text(step)
            if self_text:
                span.append(self_text)
            # following contiguous reasoning steps
            k = i + 1
            while k < n and steps[k].type == "reasoning":
                t = _reasoning_text(steps[k])
                if t:
                    span.append(t)
                k += 1

            # downstream tool_calls until the next FL read (or turn end)
            downstream: list[dict] = []
            m = i + 1
            while m < n:
                s2 = steps[m]
                if _is_fl_read(s2):
                    break
                if s2.type == "tool_call":
                    downstream.append(
                        {
                            "tool": s2.tool,
                            "args": _summarize_args(s2.args),
                            "source": s2.source,
                        }
                    )
                m += 1

            bundles.append(
                EvidenceBundle(
                    event_id=make_event_id(trace.session_id, trace.turn, i),
                    session_id=trace.session_id,
                    turn=trace.turn,
                    step_index=i,
                    slot_ref=_read_slot_ref(step),
                    tool=step.tool or "",
                    query=step.args or {},
                    reasoning_span=span,
                    downstream_actions=downstream,
                    trace_ref=trace_filename(trace),
                )
            )
    return bundles


# --------------------------------------------------------------------------- #
# S1b — LLM judgement (A/B/C)
# --------------------------------------------------------------------------- #

JUDGE_SYSTEM = (
    "You are auditing whether a fact-layer (FL) READ was correctly adopted by an "
    "AI coding agent. Classify the single read into exactly one of A/B/C/unknown "
    "by READING the evidence and the agent's reasoning. Do not pattern-match keywords."
)


def build_judge_prompt(bundle: EvidenceBundle) -> str:
    """Render the judge prompt. A/B/C definitions + the evidence bundle.

    Explicitly names the B and C signals so the model rates by meaning, not by the
    mere presence of a downstream bash/read step (which is ambiguous on its own —
    'verify then write back to FL' is healthy C/A, not B).
    """
    reasoning = "\n".join(f"  - {s}" for s in bundle.reasoning_span) or "  (none)"
    downstream = (
        "\n".join(
            f"  - {a.get('tool')} | {a.get('args')}" for a in bundle.downstream_actions
        )
        or "  (none)"
    )
    return f"""Classify one FL read into A / B / C / unknown.

Definitions:
- A (consumed & useful): the agent queried FL, got the fact, and USED it directly. The only positive outcome.
- B (consumed but wasted): the agent queried FL, then did NOT get / did NOT trust the answer, and went to bash / read source / grep to RE-FETCH the same information. Negative — the FL read was a wasted detour.
- C (self-maintenance): the read served WRITING FL — e.g. checking a slot's existence/type before an edit, a coverage audit, or pulling export as background to update FL. Orthogonal to knowledge supply.
- unknown: evidence is insufficient to decide.

Signals:
- B signal = after the read, the agent re-fetched the SAME information from bash/source because FL did not satisfy it.
- C signal = the read exists to support a subsequent FL write / verification, NOT to consume a fact for the task. A downstream "grep the source then write the correct value back to FL" is healthy verification (C/A), NOT B.
- Judge from the reasoning text, not from the mere existence of a downstream tool call.

Evidence:
- tool: {bundle.tool}
- slot_ref: {bundle.slot_ref}
- query (read args): {json.dumps(bundle.query, ensure_ascii=False)}
- reasoning span (read step + adjacent reasoning):
{reasoning}
- downstream actions (after the read, until next FL read / turn end):
{downstream}

Respond with a JSON object only:
{{"verdict": "A" | "B" | "C" | "unknown", "rationale": "<why>", "confidence": <0..1>}}"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _extract_json(raw: str) -> dict | None:
    """Locate + parse the JSON object in a model response.

    NOTE: this only *parses* structure (strip code fences, find the outermost
    braces). The verdict VALUE comes from the parsed ``verdict`` field — it is
    never inferred from the reasoning text. Red-line 1 (no regex classifier) holds.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```")).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    import re

    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            return None
    return None


def _parse_verdict(raw: str) -> tuple[str, str, float | None]:
    data = _extract_json(raw)
    if not data or not isinstance(data, dict):
        return "unknown", f"unparseable response: {raw[:200]}", None
    v = str(data.get("verdict", "")).strip().upper()
    verdict = v if v in ("A", "B", "C") else "unknown"
    rationale = str(data.get("rationale", ""))
    conf = data.get("confidence")
    try:
        confidence = float(conf) if conf is not None else None
    except Exception:
        confidence = None
    return verdict, rationale, confidence


def judge_evidence(
    bundle: EvidenceBundle,
    *,
    backend: Callable[[str], str],
    cache: dict[str, ABCJudgement] | None = None,
    judge_model: str | None = None,
) -> ABCJudgement:
    """Judge one bundle. Cache hit → return cached (no LLM). Backend error → unknown.

    ``backend`` is a ``prompt -> raw_response`` callable so tests stub it (and count
    calls) with no live LLM. The verdict is parsed from the backend's JSON only.
    """
    if cache is not None and bundle.event_id in cache:
        return cache[bundle.event_id]

    prompt = build_judge_prompt(bundle)
    try:
        raw = backend(prompt)
    except Exception as e:  # graceful degradation — one event, not the whole run
        return ABCJudgement(
            event_id=bundle.event_id,
            verdict="unknown",
            rationale=f"backend error: {e}",
            judged_at=_now(),
            judge_model=judge_model,
        )

    verdict, rationale, confidence = _parse_verdict(raw)
    return ABCJudgement(
        event_id=bundle.event_id,
        verdict=verdict,
        rationale=rationale,
        confidence=confidence,
        judged_at=_now(),
        judge_model=judge_model,
    )


def judge_all(
    bundles: list[EvidenceBundle],
    *,
    backend: Callable[[str], str],
    sample: int | None = None,
    facts_dir: Path | None = None,
    judge_model: str | None = None,
) -> list[ABCJudgement]:
    """Judge bundles (optionally a random sample of ``sample``), skipping cached ones.

    Loads the persisted cache once; cached events return without an LLM call and are
    not re-saved; new judgements are appended to the store. This is the idempotency
    guarantee: a second run over the same events makes zero new backend calls.
    """
    cache = load_verdict_cache(facts_dir) if facts_dir else {}

    targets = bundles
    if sample is not None and 0 <= sample < len(bundles):
        targets = random.sample(bundles, sample)

    results: list[ABCJudgement] = []
    for b in targets:
        was_cached = b.event_id in cache
        j = judge_evidence(b, backend=backend, cache=cache, judge_model=judge_model)
        results.append(j)
        if facts_dir and not was_cached:
            save_verdict(facts_dir, j)
            cache[b.event_id] = j
    return results


# --------------------------------------------------------------------------- #
# S1c — aggregation + orchestration
# --------------------------------------------------------------------------- #


def compute_t2_report(
    judgements: list[ABCJudgement],
    total_reads: int,
    *,
    sampled: bool = False,
    sample_size: int | None = None,
    bundles: list[EvidenceBundle] | None = None,
) -> T2Report:
    """Aggregate judgements into a T2Report.

    ``adoption_rate = A/(A+B)`` (C and unknown excluded); ``c_rate = C/judged``
    reported separately. ``bundles`` (optional) supplies event→slot so ``by_slot``
    can be filled — ABCJudgement itself does not carry slot_ref (kept per spec §2).
    """
    by_verdict: dict[str, int] = {"A": 0, "B": 0, "C": 0, "unknown": 0}
    for j in judgements:
        by_verdict[j.verdict] = by_verdict.get(j.verdict, 0) + 1

    judged = len(judgements)
    a, b, c = by_verdict["A"], by_verdict["B"], by_verdict["C"]
    adoption_rate = a / (a + b) if (a + b) > 0 else None
    c_rate = c / judged if judged > 0 else None
    coverage = judged / total_reads if total_reads > 0 else 0.0

    by_slot: dict[str, dict[str, int]] = {}
    if bundles:
        slot_by_event = {bd.event_id: (bd.slot_ref or "∅") for bd in bundles}
        for j in judgements:
            slot = slot_by_event.get(j.event_id, "∅")
            d = by_slot.setdefault(slot, {"A": 0, "B": 0, "C": 0, "unknown": 0})
            d[j.verdict] = d.get(j.verdict, 0) + 1

    return T2Report(
        total_reads=total_reads,
        judged=judged,
        coverage=coverage,
        by_verdict=by_verdict,
        adoption_rate=adoption_rate,
        c_rate=c_rate,
        by_slot=by_slot,
        sampled=sampled,
        sample_size=sample_size,
    )


def default_backend() -> Callable[[str], str]:
    """The real LLM backend: FL's unified call under the ``audit`` role."""
    from fact_layer.core.llm import llm_call

    def _backend(prompt: str) -> str:
        return llm_call(prompt, role="audit", system=JUDGE_SYSTEM, max_tokens=1024)

    return _backend


def run_effectiveness(
    facts_dir: Path,
    *,
    session: str | None = None,
    after: str | None = None,
    sample: int | None = None,
    dry_run: bool = False,
    backend: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Single orchestrator shared by CLI and MCP (guarantees parity).

    Returns a dict with ``t1`` (relevance counts — NOT effectiveness), and either
    ``t2`` (the adoption report) or, in dry-run, just the evidence scale so cost can
    be estimated before spending any LLM call.
    """
    traces = load_traces(facts_dir, session=session, after=after)
    bundles = extract_evidence(traces)
    t1 = compute_eval_stats(traces)

    result: dict[str, Any] = {
        "dry_run": dry_run,
        "total_reads": len(bundles),
        "t1": t1.model_dump(mode="json"),
        "t2": None,
    }

    if dry_run:
        result["evidence_chars"] = sum(
            len("".join(b.reasoning_span)) for b in bundles
        )
        return result

    if backend is None:
        backend = default_backend()

    judge_model: str | None = None
    try:
        from fact_layer.core.config import model_for

        judge_model = model_for("audit")
    except Exception:
        judge_model = None

    judgements = judge_all(
        bundles,
        backend=backend,
        sample=sample,
        facts_dir=facts_dir,
        judge_model=judge_model,
    )
    report = compute_t2_report(
        judgements,
        total_reads=len(bundles),
        sampled=sample is not None,
        sample_size=sample,
        bundles=bundles,
    )
    result["t2"] = report.model_dump(mode="json")
    return result