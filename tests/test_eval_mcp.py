from pathlib import Path

import pytest

from fact_layer.core.eval_cmd import save_trace
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.writer import dump_yaml
from fact_layer.mcp_server import facts_eval_list, facts_eval_log, facts_eval_stats
from fact_layer.models.eval import EvalStep, EvalSummary, EvalTrace


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
        },
    ]
    return EvalTrace(
        session_id=session_id,
        turn=turn,
        timestamp=timestamp,
        steps=[EvalStep.model_validate(s) for s in (steps or default_steps)],
        summary=EvalSummary.model_validate(summary or {"facts_consumed": 1}),
    )


@pytest.fixture
def facts_dir(tmp_path: Path, monkeypatch) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    init_facts_dir(
        target=project,
        project_name="test-project",
        language="Python 3.12",
        enabled_extensions=[],
        enabled_optional=[],
    )
    monkeypatch.chdir(project)
    return project / ".facts"


class TestFactsEvalLog:
    def test_log_creates_trace(self, facts_dir: Path):
        result = facts_eval_log({
            "session_id": "mcp-test",
            "turn": 1,
            "timestamp": "2026-06-25T14:30:00",
            "steps": [{"type": "tool_call", "tool": "facts_get", "source": "fl"}],
            "summary": {"facts_consumed": 1},
        })
        assert result["status"] == "ok"
        assert result["session_id"] == "mcp-test"
        assert result["turn"] == 1
        assert result["steps_count"] == 1

        eval_files = list((facts_dir / "eval").glob("*.yaml"))
        assert len(eval_files) == 1

    def test_log_invalid_trace(self, facts_dir: Path):
        with pytest.raises(Exception):
            facts_eval_log({"invalid": "data"})


class TestFactsEvalList:
    def test_list_empty(self, facts_dir: Path):
        result = facts_eval_list()
        assert result == []

    def test_list_all(self, facts_dir: Path):
        save_trace(facts_dir, _make_trace(session_id="s1", timestamp="2026-06-25T14:30:00"))
        save_trace(facts_dir, _make_trace(session_id="s2", timestamp="2026-06-25T14:31:00"))
        result = facts_eval_list()
        assert len(result) == 2

    def test_list_filter_session(self, facts_dir: Path):
        save_trace(facts_dir, _make_trace(session_id="alpha", timestamp="2026-06-25T14:30:00"))
        save_trace(facts_dir, _make_trace(session_id="beta", timestamp="2026-06-25T14:31:00"))
        result = facts_eval_list(session="alpha")
        assert len(result) == 1
        assert result[0]["session_id"] == "alpha"

    def test_list_filter_bypassed(self, facts_dir: Path):
        save_trace(facts_dir, _make_trace(
            session_id="bp",
            timestamp="2026-06-25T14:30:00",
            steps=[{"type": "reasoning", "source": "doc", "bypassed": {"rule": "A1", "reason": "test"}}],
        ))
        save_trace(facts_dir, _make_trace(session_id="no-bp", timestamp="2026-06-25T14:31:00"))
        result = facts_eval_list(bypassed=True)
        assert len(result) == 1
        assert result[0]["session_id"] == "bp"


class TestFactsEvalStats:
    def test_stats_empty(self, facts_dir: Path):
        result = facts_eval_stats()
        assert result["total_turns"] == 0

    def test_stats_basic(self, facts_dir: Path):
        for i in range(1, 4):
            save_trace(facts_dir, _make_trace(
                turn=i,
                timestamp=f"2026-06-25T14:{30+i}:00",
                steps=[
                    {"type": "tool_call", "tool": "facts_get", "args": {"slot": "x.y"}, "source": "fl"},
                    {"type": "tool_call", "tool": "read", "source": "doc"},
                ],
            ))
        result = facts_eval_stats()
        assert result["total_turns"] == 3
        assert result["total_steps"] == 6
        assert result["fl_vs_doc"]["fl"] == 3
        assert result["fl_vs_doc"]["doc"] == 3
        assert result["fl_ratio"] == pytest.approx(0.5)

    def test_stats_filter_session(self, facts_dir: Path):
        save_trace(facts_dir, _make_trace(
            session_id="a",
            timestamp="2026-06-25T14:30:00",
            steps=[{"type": "tool_call", "source": "fl"}],
        ))
        save_trace(facts_dir, _make_trace(
            session_id="b",
            timestamp="2026-06-25T14:31:00",
            steps=[{"type": "tool_call", "source": "doc"}],
        ))
        result = facts_eval_stats(session="a")
        assert result["total_turns"] == 1
        assert result["fl_vs_doc"]["fl"] == 1
        assert result["fl_vs_doc"]["doc"] == 0
