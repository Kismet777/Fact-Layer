"""S1 — T2 observation layer: extraction, judgement, cache, report.

LLM is ALWAYS stubbed here (no live calls). The stub is a plain call-counting /
canned-JSON callable — it stands in for the model reading the evidence; it is NOT
a regex classifier in production (red-line 1 is enforced by having the real path
parse only the model's JSON verdict).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fact_layer.core.eval_t2 import (
    compute_t2_report,
    extract_evidence,
    judge_all,
    judge_evidence,
    run_effectiveness,
)
from fact_layer.core.eval_cmd import save_trace
from fact_layer.models.eval import EvalStep, EvalSummary, EvalTrace
from fact_layer.models.eval_results import ABCJudgement, EvidenceBundle, make_event_id


def _trace(session_id="s", turn=1, timestamp="2026-08-13T10:00:00", steps=None):
    return EvalTrace(
        session_id=session_id,
        turn=turn,
        timestamp=timestamp,
        steps=[EvalStep.model_validate(s) for s in (steps or [])],
        summary=EvalSummary(),
    )


@pytest.fixture
def facts_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".facts"
    d.mkdir()
    return d


# --------------------------------------------------------------------------- #
# S1a — extraction
# --------------------------------------------------------------------------- #


class TestExtractEvidence:
    def test_extracts_fl_get_read(self):
        traces = [
            _trace(
                steps=[
                    {
                        "type": "tool_call",
                        "tool": "facts_get",
                        "args": {"slot": "tech-stack.database"},
                        "source": "fl",
                        "result_used_for": "确认数据库类型",
                    }
                ]
            )
        ]
        bundles = extract_evidence(traces)
        assert len(bundles) == 1
        b = bundles[0]
        assert b.tool == "facts_get"
        assert b.slot_ref == "tech-stack.database"
        assert b.event_id == make_event_id("s", 1, 0)
        assert b.query == {"slot": "tech-stack.database"}
        assert b.fl_return is None

    def test_non_fl_steps_skipped(self):
        traces = [
            _trace(
                steps=[
                    {"type": "tool_call", "tool": "bash", "source": "code"},
                    {"type": "reasoning", "rationale": "x"},
                ]
            )
        ]
        assert extract_evidence(traces) == []

    def test_source_fl_toolcall_counts_even_if_tool_unlisted(self):
        # spec: FL read = tool in list OR source == "fl"
        traces = [
            _trace(steps=[{"type": "tool_call", "tool": "mcp_get", "source": "fl"}])
        ]
        assert len(extract_evidence(traces)) == 1

    def test_search_and_export_have_no_slot_ref(self):
        traces = [
            _trace(
                steps=[
                    {"type": "tool_call", "tool": "facts_search", "args": {"query": "status"}, "source": "fl"},
                    {"type": "tool_call", "tool": "facts_export", "args": {}, "source": "fl"},
                ]
            )
        ]
        bundles = extract_evidence(traces)
        assert [b.slot_ref for b in bundles] == [None, None]
        assert [b.tool for b in bundles] == ["facts_search", "facts_export"]

    def test_reasoning_span_includes_read_step_own_l2(self):
        traces = [
            _trace(
                steps=[
                    {
                        "type": "tool_call",
                        "tool": "facts_get",
                        "args": {"slot": "x.y"},
                        "source": "fl",
                        "rationale": "读它拿枚举",
                        "conclusion": "status=6",
                    }
                ]
            )
        ]
        span = extract_evidence(traces)[0].reasoning_span
        assert any("status=6" in s for s in span)

    def test_downstream_actions_capture_bash_refetch(self):
        traces = [
            _trace(
                steps=[
                    {"type": "tool_call", "tool": "facts_get", "args": {"slot": "x.y"}, "source": "fl"},
                    {"type": "tool_call", "tool": "bash", "args": {"cmd": "grep enum ddl.sql"}, "source": "code"},
                ]
            )
        ]
        b = extract_evidence(traces)[0]
        assert len(b.downstream_actions) == 1
        assert b.downstream_actions[0]["tool"] == "bash"

    def test_downstream_stops_at_next_fl_read(self):
        traces = [
            _trace(
                steps=[
                    {"type": "tool_call", "tool": "facts_get", "args": {"slot": "a.b"}, "source": "fl"},
                    {"type": "tool_call", "tool": "bash", "source": "code"},
                    {"type": "tool_call", "tool": "facts_get", "args": {"slot": "c.d"}, "source": "fl"},
                    {"type": "tool_call", "tool": "read", "source": "doc"},
                ]
            )
        ]
        bundles = extract_evidence(traces)
        assert len(bundles) == 2
        # first read's downstream = only the bash before the next FL read
        assert [a["tool"] for a in bundles[0].downstream_actions] == ["bash"]
        assert [a["tool"] for a in bundles[1].downstream_actions] == ["read"]

    def test_trace_ref_is_reconstructable_filename(self):
        traces = [_trace(steps=[{"type": "tool_call", "tool": "facts_get", "args": {"slot": "x.y"}, "source": "fl"}])]
        b = extract_evidence(traces)[0]
        assert b.trace_ref.endswith("turn-001.yaml")

    # ---- RED-LINE 2: decisive signal lives in the ADJACENT reasoning step ----

    def test_decisive_signal_only_in_adjacent_reasoning_and_degrades_if_dropped(self):
        """A judge that reads reasoning_span decides correctly; drop the adjacent
        reasoning step and the same judge degrades — proving the extractor MUST
        include neighbours, not just the read step's own fields (red-line 2)."""
        # The read step itself has NO decisive L2. The decisive sentence ('核源后写回
        # FL，健康验证' → C, not B) is ONLY in the reasoning step right after it.
        steps = [
            {"type": "tool_call", "tool": "facts_get", "args": {"slot": "data-model.enum"}, "source": "fl"},
            {"type": "reasoning", "rationale": "FL 值存疑，去核源，核对后把正确枚举写回 FL（健康验证，非回退）"},
            {"type": "tool_call", "tool": "bash", "args": {"cmd": "grep enum access.sql"}, "source": "code"},
        ]
        bundle = extract_evidence([_trace(steps=steps)])[0]
        assert any("写回 FL" in s for s in bundle.reasoning_span)

        # A stub judge that models the LLM: reads the span, sees the 'write back'
        # signal → C. Without the span it only sees read+bash → misreads as B.
        def judge_from_span(prompt: str) -> str:
            has_signal = "写回 FL" in prompt
            return '{"verdict": "C", "rationale": "verify-then-write"}' if has_signal else '{"verdict": "B", "rationale": "read then bash"}'

        with_span = judge_evidence(bundle, backend=judge_from_span)
        assert with_span.verdict == "C"

        # Simulate a cheap extractor that dropped the adjacent reasoning step.
        degraded = bundle.model_copy(update={"reasoning_span": []})
        without_span = judge_evidence(degraded, backend=judge_from_span)
        assert without_span.verdict == "B"  # proxy error reappears at the boundary
        assert with_span.verdict != without_span.verdict


# --------------------------------------------------------------------------- #
# S1b — judgement: A/B/C semantics, cache, degradation
# --------------------------------------------------------------------------- #


def _bundle(event_id="s:001:0", slot_ref="x.y", tool="facts_get"):
    return EvidenceBundle(
        event_id=event_id,
        session_id="s",
        turn=1,
        step_index=0,
        slot_ref=slot_ref,
        tool=tool,
    )


class TestJudgeSemantics:
    def test_verdict_A_used_directly(self):
        backend = lambda p: '{"verdict": "A", "rationale": "used the fact directly", "confidence": 0.9}'
        j = judge_evidence(_bundle(), backend=backend)
        assert j.verdict == "A"
        assert j.confidence == 0.9

    def test_verdict_B_read_then_refetch(self):
        backend = lambda p: '{"verdict": "B", "rationale": "re-fetched from bash"}'
        assert judge_evidence(_bundle(), backend=backend).verdict == "B"

    def test_verdict_C_read_for_write(self):
        backend = lambda p: '{"verdict": "C", "rationale": "read to verify before writing FL"}'
        assert judge_evidence(_bundle(), backend=backend).verdict == "C"

    def test_verdict_from_llm_json_not_regex(self):
        # reasoning text screams "B" but the model's JSON says A — we honor the JSON.
        b = _bundle()
        b = b.model_copy(update={"reasoning_span": ["went to bash to re-fetch", "wasted the FL read"]})
        backend = lambda p: '{"verdict": "A", "rationale": "model decided A"}'
        assert judge_evidence(b, backend=backend).verdict == "A"

    def test_unparseable_response_degrades_to_unknown(self):
        backend = lambda p: "not json at all"
        assert judge_evidence(_bundle(), backend=backend).verdict == "unknown"

    def test_invalid_verdict_value_degrades_to_unknown(self):
        backend = lambda p: '{"verdict": "D", "rationale": "?"}'
        assert judge_evidence(_bundle(), backend=backend).verdict == "unknown"

    def test_backend_exception_degrades_not_crash(self):
        def backend(p):
            raise RuntimeError("api down")

        j = judge_evidence(_bundle(), backend=backend)
        assert j.verdict == "unknown"
        assert "api down" in j.rationale


class TestJudgeCache:
    def test_cache_hit_skips_backend(self):
        calls = {"n": 0}

        def backend(p):
            calls["n"] += 1
            return '{"verdict": "A"}'

        cache = {"s:001:0": ABCJudgement(event_id="s:001:0", verdict="B")}
        j = judge_evidence(_bundle(), backend=backend, cache=cache)
        assert j.verdict == "B"  # returned from cache
        assert calls["n"] == 0

    def test_judge_all_idempotent_second_run_zero_calls(self, facts_dir: Path):
        calls = {"n": 0}

        def backend(p):
            calls["n"] += 1
            return '{"verdict": "A", "rationale": "ok"}'

        bundles = [_bundle(event_id="s:001:0"), _bundle(event_id="s:001:1")]
        first = judge_all(bundles, backend=backend, facts_dir=facts_dir)
        assert len(first) == 2
        assert calls["n"] == 2

        # second run: everything cached from the persisted store → no new calls
        second = judge_all(bundles, backend=backend, facts_dir=facts_dir)
        assert len(second) == 2
        assert calls["n"] == 2  # unchanged

    def test_judge_all_degrade_isolated_per_event(self, facts_dir: Path):
        def backend(p):
            # one bundle triggers an error; the other succeeds
            if "boom" in p:
                raise RuntimeError("boom")
            return '{"verdict": "A"}'

        good = _bundle(event_id="s:001:0")
        bad = _bundle(event_id="s:001:1")
        bad = bad.model_copy(update={"reasoning_span": ["boom"]})
        results = judge_all([good, bad], backend=backend, facts_dir=facts_dir)
        verdicts = {r.event_id: r.verdict for r in results}
        assert verdicts["s:001:0"] == "A"
        assert verdicts["s:001:1"] == "unknown"


# --------------------------------------------------------------------------- #
# S1c — report aggregation
# --------------------------------------------------------------------------- #


class TestComputeReport:
    def _judgements(self, spec):
        return [ABCJudgement(event_id=f"e{i}", verdict=v) for i, v in enumerate(spec)]

    def test_adoption_rate_excludes_c_and_unknown(self):
        js = self._judgements(["A", "A", "A", "B", "C", "unknown"])
        r = compute_t2_report(js, total_reads=6)
        assert r.by_verdict == {"A": 3, "B": 1, "C": 1, "unknown": 1}
        assert r.adoption_rate == pytest.approx(3 / 4)  # A/(A+B), C & unknown out
        assert r.c_rate == pytest.approx(1 / 6)
        assert r.coverage == pytest.approx(6 / 6)

    def test_adoption_rate_none_when_denominator_zero(self):
        js = self._judgements(["C", "C", "unknown"])
        r = compute_t2_report(js, total_reads=3)
        assert r.adoption_rate is None
        assert r.c_rate == pytest.approx(2 / 3)

    def test_c_rate_none_when_no_judgements(self):
        r = compute_t2_report([], total_reads=5)
        assert r.c_rate is None
        assert r.adoption_rate is None
        assert r.coverage == 0.0

    def test_coverage_reflects_partial_judging(self):
        js = self._judgements(["A", "B"])
        r = compute_t2_report(js, total_reads=10)
        assert r.judged == 2
        assert r.coverage == pytest.approx(0.2)

    def test_by_slot_from_bundles(self):
        bundles = [
            _bundle(event_id="e0", slot_ref="data-model.enum"),
            _bundle(event_id="e1", slot_ref="data-model.enum"),
            _bundle(event_id="e2", slot_ref="tech-stack.db"),
        ]
        js = [
            ABCJudgement(event_id="e0", verdict="A"),
            ABCJudgement(event_id="e1", verdict="B"),
            ABCJudgement(event_id="e2", verdict="A"),
        ]
        r = compute_t2_report(js, total_reads=3, bundles=bundles)
        assert r.by_slot["data-model.enum"]["A"] == 1
        assert r.by_slot["data-model.enum"]["B"] == 1
        assert r.by_slot["tech-stack.db"]["A"] == 1

    def test_sampled_flag_recorded(self):
        r = compute_t2_report(self._judgements(["A"]), total_reads=10, sampled=True, sample_size=1)
        assert r.sampled is True
        assert r.sample_size == 1


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #


class TestRunEffectiveness:
    def _seed(self, facts_dir: Path):
        save_trace(
            facts_dir,
            _trace(
                session_id="proj",
                steps=[
                    {"type": "tool_call", "tool": "facts_get", "args": {"slot": "x.y"}, "source": "fl"},
                    {"type": "tool_call", "tool": "read", "source": "doc"},
                ],
            ),
        )

    def test_dry_run_makes_no_llm_call(self, facts_dir: Path):
        self._seed(facts_dir)

        def backend(p):
            raise AssertionError("dry-run must not call the backend")

        out = run_effectiveness(facts_dir, dry_run=True, backend=backend)
        assert out["dry_run"] is True
        assert out["total_reads"] == 1
        assert out["t2"] is None
        assert "t1" in out  # T1 relevance counts present alongside

    def test_full_run_returns_t1_and_t2(self, facts_dir: Path):
        self._seed(facts_dir)
        out = run_effectiveness(
            facts_dir, backend=lambda p: '{"verdict": "A", "rationale": "ok"}'
        )
        assert out["t2"]["by_verdict"]["A"] == 1
        assert out["t2"]["adoption_rate"] == pytest.approx(1.0)
        assert out["t1"]["fl_ratio"] is not None  # T1 kept separate from T2