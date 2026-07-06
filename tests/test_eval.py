from pathlib import Path

import pytest

from fact_layer.core.eval_cmd import compute_eval_stats, load_traces, save_trace
from fact_layer.core.writer import dump_yaml
from fact_layer.models.eval import (
    BypassInfo,
    EvalStep,
    EvalSummary,
    EvalTrace,
)


def _make_trace(
    session_id: str = "test-session",
    turn: int = 1,
    timestamp: str = "2026-06-25T14:30:00",
    steps: list[dict] | None = None,
    summary: dict | None = None,
) -> EvalTrace:
    default_steps = [
        {
            "type": "tool_call",
            "tool": "facts_get",
            "args": {"slot": "tech-stack.database"},
            "source": "fl",
            "result_used_for": "确认数据库类型",
        },
    ]
    return EvalTrace(
        session_id=session_id,
        turn=turn,
        timestamp=timestamp,
        steps=[EvalStep.model_validate(s) for s in (steps or default_steps)],
        summary=EvalSummary.model_validate(summary or {"facts_consumed": 1, "sources": {"fl": 1}}),
    )


@pytest.fixture
def eval_dir(tmp_path: Path) -> Path:
    facts_dir = tmp_path / ".facts"
    facts_dir.mkdir()
    return facts_dir


class TestEvalModels:
    def test_eval_step_tool_call(self):
        step = EvalStep(
            type="tool_call",
            tool="facts_get",
            args={"slot": "tech-stack.database"},
            source="fl",
        )
        assert step.type == "tool_call"
        assert step.tool == "facts_get"
        assert step.source == "fl"

    def test_eval_step_reasoning(self):
        step = EvalStep(
            type="reasoning",
            rationale="FL 返回 status=6 已结清",
            conclusion="WHERE status=6",
            source="fl",
        )
        assert step.type == "reasoning"
        assert step.rationale is not None
        assert step.source == "fl"

    def test_eval_step_with_bypass(self):
        step = EvalStep(
            type="reasoning",
            source="doc",
            bypassed=BypassInfo(rule="A1", reason="FL 未覆盖该槽位"),
        )
        assert step.bypassed is not None
        assert step.bypassed.rule == "A1"

    def test_eval_step_optional_fields_default_none(self):
        step = EvalStep(type="tool_call")
        assert step.ts is None
        assert step.duration_ms is None
        assert step.tool is None
        assert step.source is None

    def test_eval_step_invalid_source_rejected(self):
        with pytest.raises(Exception):
            EvalStep(type="tool_call", source="invalid")

    def test_eval_trace_full(self):
        trace = _make_trace()
        assert trace.session_id == "test-session"
        assert trace.turn == 1
        assert len(trace.steps) == 1

    def test_eval_summary_defaults(self):
        summary = EvalSummary()
        assert summary.facts_consumed == 0
        assert summary.sources == {}
        assert summary.fl_vs_doc == {}
        assert summary.bypassed_count == 0


class TestSaveTrace:
    def test_save_creates_file(self, eval_dir: Path):
        trace = _make_trace()
        path = save_trace(eval_dir, trace)
        assert path.exists()
        assert path.suffix == ".yaml"
        assert "test-session" in path.name
        assert "turn-001" in path.name

    def test_save_filename_format(self, eval_dir: Path):
        trace = _make_trace(
            session_id="贷后催收-SQL",
            turn=3,
            timestamp="2026-06-25T14:30:00",
        )
        path = save_trace(eval_dir, trace)
        assert "turn-003" in path.name
        assert path.parent == eval_dir / "eval"

    def test_save_cleans_pending(self, eval_dir: Path):
        pending_dir = eval_dir / "eval" / "pending"
        pending_dir.mkdir(parents=True)
        pending_file = pending_dir / "test-session_turn-001.jsonl"
        pending_file.write_text('{"tool": "facts_get"}')

        trace = _make_trace(session_id="test-session", turn=1)
        save_trace(eval_dir, trace)

        assert not pending_file.exists()

    def test_save_multiple_turns(self, eval_dir: Path):
        for i in range(1, 4):
            trace = _make_trace(turn=i, timestamp=f"2026-06-25T14:{30+i}:00")
            save_trace(eval_dir, trace)

        files = list((eval_dir / "eval").glob("*.yaml"))
        assert len(files) == 3


class TestLoadTraces:
    def test_load_empty(self, eval_dir: Path):
        traces = load_traces(eval_dir)
        assert traces == []

    def test_load_all(self, eval_dir: Path):
        for i in range(1, 4):
            save_trace(eval_dir, _make_trace(turn=i, timestamp=f"2026-06-25T14:{30+i}:00"))

        traces = load_traces(eval_dir)
        assert len(traces) == 3

    def test_load_sorted_by_timestamp(self, eval_dir: Path):
        save_trace(eval_dir, _make_trace(turn=2, timestamp="2026-06-25T14:32:00"))
        save_trace(eval_dir, _make_trace(turn=1, timestamp="2026-06-25T14:31:00"))

        traces = load_traces(eval_dir)
        assert traces[0].turn == 1
        assert traces[1].turn == 2

    def test_filter_by_session_exact(self, eval_dir: Path):
        save_trace(eval_dir, _make_trace(session_id="alpha", timestamp="2026-06-25T14:30:00"))
        save_trace(eval_dir, _make_trace(session_id="beta", timestamp="2026-06-25T14:31:00"))

        traces = load_traces(eval_dir, session="alpha")
        assert len(traces) == 1
        assert traces[0].session_id == "alpha"

    def test_filter_by_session_wildcard(self, eval_dir: Path):
        save_trace(eval_dir, _make_trace(session_id="贷后催收-SQL", timestamp="2026-06-25T14:30:00"))
        save_trace(eval_dir, _make_trace(session_id="贷后催收-画像", timestamp="2026-06-25T14:31:00"))
        save_trace(eval_dir, _make_trace(session_id="other", timestamp="2026-06-25T14:32:00"))

        traces = load_traces(eval_dir, session="贷后催收*")
        assert len(traces) == 2

    def test_filter_by_source(self, eval_dir: Path):
        save_trace(
            eval_dir,
            _make_trace(
                session_id="s1",
                timestamp="2026-06-25T14:30:00",
                steps=[{"type": "tool_call", "tool": "facts_get", "source": "fl"}],
            ),
        )
        save_trace(
            eval_dir,
            _make_trace(
                session_id="s2",
                timestamp="2026-06-25T14:31:00",
                steps=[{"type": "tool_call", "tool": "read", "source": "doc"}],
            ),
        )

        traces = load_traces(eval_dir, source="doc")
        assert len(traces) == 1
        assert traces[0].session_id == "s2"

    def test_filter_by_bypassed(self, eval_dir: Path):
        save_trace(
            eval_dir,
            _make_trace(
                session_id="s1",
                timestamp="2026-06-25T14:30:00",
                steps=[{"type": "reasoning", "source": "doc", "bypassed": {"rule": "A1", "reason": "test"}}],
            ),
        )
        save_trace(
            eval_dir,
            _make_trace(
                session_id="s2",
                timestamp="2026-06-25T14:31:00",
                steps=[{"type": "tool_call", "tool": "facts_get", "source": "fl"}],
            ),
        )

        traces = load_traces(eval_dir, bypassed=True)
        assert len(traces) == 1
        assert traces[0].session_id == "s1"

    def test_filter_by_after(self, eval_dir: Path):
        save_trace(eval_dir, _make_trace(timestamp="2026-06-20T10:00:00"))
        save_trace(eval_dir, _make_trace(session_id="new", timestamp="2026-06-25T10:00:00"))

        traces = load_traces(eval_dir, after="2026-06-24")
        assert len(traces) == 1
        assert traces[0].session_id == "new"


class TestComputeStats:
    def test_empty_traces(self):
        stats = compute_eval_stats([])
        assert stats.total_turns == 0
        assert stats.total_steps == 0
        assert stats.fl_ratio is None
        assert stats.l2_coverage == 0.0

    def test_basic_stats(self):
        traces = [
            _make_trace(
                steps=[
                    {"type": "tool_call", "tool": "facts_get", "args": {"slot": "tech-stack.db"}, "source": "fl"},
                    {"type": "reasoning", "rationale": "test", "source": "fl"},
                    {"type": "tool_call", "tool": "read", "source": "doc"},
                ],
                summary={"facts_consumed": 1, "sources": {"fl": 2, "doc": 1}},
            ),
        ]
        stats = compute_eval_stats(traces)
        assert stats.total_turns == 1
        assert stats.total_steps == 3
        assert stats.sources["fl"] == 2
        assert stats.sources["doc"] == 1
        assert stats.fl_vs_doc == {"fl": 2, "doc": 1}
        assert stats.fl_ratio == pytest.approx(2 / 3)

    def test_fl_ratio_no_doc(self):
        traces = [
            _make_trace(
                steps=[
                    {"type": "tool_call", "tool": "facts_get", "args": {"slot": "x.y"}, "source": "fl"},
                ],
            ),
        ]
        stats = compute_eval_stats(traces)
        assert stats.fl_ratio == pytest.approx(1.0)
        assert stats.fl_vs_doc == {"fl": 1, "doc": 0}

    def test_bypassed_aggregation(self):
        traces = [
            _make_trace(
                turn=1,
                timestamp="2026-06-25T14:30:00",
                steps=[
                    {"type": "reasoning", "source": "doc", "bypassed": {"rule": "A1", "reason": "FL 未覆盖该槽位"}},
                ],
            ),
            _make_trace(
                turn=2,
                timestamp="2026-06-25T14:31:00",
                steps=[
                    {"type": "reasoning", "source": "doc", "bypassed": {"rule": "A1", "reason": "FL 未覆盖该槽位"}},
                    {"type": "reasoning", "source": "doc", "bypassed": {"rule": "A2", "reason": "直接引用"}},
                ],
            ),
        ]
        stats = compute_eval_stats(traces)
        assert len(stats.bypassed) == 2
        assert stats.bypassed[0].rule == "A1"
        assert stats.bypassed[0].count == 2
        assert stats.bypassed[1].rule == "A2"
        assert stats.bypassed[1].count == 1

    def test_slot_hits(self):
        traces = [
            _make_trace(
                steps=[
                    {"type": "tool_call", "tool": "facts_get", "args": {"slot": "tech-stack.db"}, "source": "fl"},
                    {"type": "tool_call", "tool": "facts_get", "args": {"slot": "tech-stack.db"}, "source": "fl"},
                    {"type": "tool_call", "tool": "facts_get", "args": {"slot": "arch.style"}, "source": "fl"},
                ],
            ),
        ]
        stats = compute_eval_stats(traces)
        assert stats.slot_hits[0].slot_ref == "tech-stack.db"
        assert stats.slot_hits[0].count == 2
        assert stats.slot_hits[1].slot_ref == "arch.style"
        assert stats.slot_hits[1].count == 1

    def test_l2_coverage(self):
        traces = [
            _make_trace(
                turn=1,
                timestamp="2026-06-25T14:30:00",
                # L2 coverage requires a real semantic field (rationale/result_used_for/
                # conclusion); source alone is an L1 signal and does NOT count (FL-018).
                steps=[{"type": "tool_call", "tool": "facts_get", "source": "fl", "result_used_for": "确认数据库类型"}],
            ),
            _make_trace(
                turn=2,
                timestamp="2026-06-25T14:31:00",
                steps=[{"type": "tool_call", "tool": "bash"}],
            ),
        ]
        stats = compute_eval_stats(traces)
        assert stats.l2_coverage == pytest.approx(0.5)

    def test_timing_stats(self):
        traces = [
            _make_trace(
                steps=[
                    {"type": "tool_call", "tool": "facts_get", "source": "fl", "duration_ms": 200},
                    {"type": "tool_call", "tool": "read", "source": "doc", "duration_ms": 3000},
                ],
                summary={"facts_consumed": 1, "turn_duration_ms": 10000},
            ),
        ]
        stats = compute_eval_stats(traces)
        assert stats.timing is not None
        assert stats.timing.avg_turn_ms == 10000
        assert stats.timing.avg_fl_query_ms == 200
        assert stats.timing.avg_doc_read_ms == 3000

    def test_suggested_slots_from_bypassed(self):
        traces = [
            _make_trace(
                turn=1,
                timestamp="2026-06-25T14:30:00",
                steps=[
                    {"type": "reasoning", "source": "doc", "bypassed": {"rule": "缺槽位", "reason": "FL 未覆盖该槽位 attitude"}},
                ],
            ),
            _make_trace(
                turn=2,
                timestamp="2026-06-25T14:31:00",
                steps=[
                    {"type": "reasoning", "source": "doc", "bypassed": {"rule": "缺槽位", "reason": "FL 未覆盖该槽位 attitude"}},
                ],
            ),
        ]
        stats = compute_eval_stats(traces)
        assert len(stats.suggested_slots) > 0
