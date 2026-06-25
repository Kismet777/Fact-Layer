import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fact_layer.cli import app
from fact_layer.core.eval_cmd import save_trace
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.models.eval import EvalStep, EvalSummary, EvalTrace

runner = CliRunner()


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
def project_dir(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    init_facts_dir(
        target=project,
        project_name="test-project",
        language="Python 3.12",
        enabled_extensions=[],
        enabled_optional=[],
    )
    return project


@pytest.fixture
def facts_dir(project_dir: Path) -> Path:
    return project_dir / ".facts"


class TestEvalLog:
    def test_log_with_flags(self, project_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        steps_json = json.dumps([
            {"type": "tool_call", "tool": "facts_get", "args": {"slot": "tech-stack.db"}, "source": "fl"},
        ])
        result = runner.invoke(app, [
            "eval", "log",
            "--session", "test-session",
            "--turn", "1",
            "--steps", steps_json,
        ])
        assert result.exit_code == 0
        assert "Logged eval trace" in result.output
        assert "test-session" in result.output

    def test_log_with_summary(self, project_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        steps_json = json.dumps([{"type": "tool_call", "tool": "facts_get", "source": "fl"}])
        summary_json = json.dumps({"facts_consumed": 1, "sources": {"fl": 1}})
        result = runner.invoke(app, [
            "eval", "log",
            "--session", "s1",
            "--turn", "1",
            "--steps", steps_json,
            "--summary", summary_json,
        ])
        assert result.exit_code == 0

    def test_log_from_stdin(self, project_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        trace_data = {
            "session_id": "stdin-session",
            "turn": 1,
            "timestamp": "2026-06-25T14:30:00",
            "steps": [{"type": "tool_call", "tool": "facts_get", "source": "fl"}],
            "summary": {"facts_consumed": 1},
        }
        result = runner.invoke(app, ["eval", "log"], input=json.dumps(trace_data))
        assert result.exit_code == 0
        assert "stdin-session" in result.output

    def test_log_creates_file(self, project_dir: Path, facts_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        steps_json = json.dumps([{"type": "tool_call", "tool": "facts_get", "source": "fl"}])
        runner.invoke(app, [
            "eval", "log",
            "--session", "file-test",
            "--turn", "1",
            "--steps", steps_json,
        ])
        eval_files = list((facts_dir / "eval").glob("*.yaml"))
        assert len(eval_files) == 1

    def test_log_no_facts_dir(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "eval", "log",
            "--session", "s1",
            "--turn", "1",
            "--steps", "[]",
        ])
        assert result.exit_code == 1

    def test_log_no_input(self, project_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        result = runner.invoke(app, ["eval", "log"])
        assert result.exit_code == 1


class TestEvalList:
    def _seed_traces(self, facts_dir: Path):
        save_trace(facts_dir, _make_trace(
            session_id="alpha",
            turn=1,
            timestamp="2026-06-25T14:30:00",
            steps=[
                {"type": "tool_call", "tool": "facts_get", "args": {"slot": "x.y"}, "source": "fl"},
                {"type": "reasoning", "rationale": "test", "source": "fl"},
            ],
        ))
        save_trace(facts_dir, _make_trace(
            session_id="alpha",
            turn=2,
            timestamp="2026-06-25T14:35:00",
            steps=[
                {"type": "tool_call", "tool": "read", "source": "doc"},
                {"type": "reasoning", "source": "doc", "bypassed": {"rule": "A1", "reason": "FL未覆盖"}},
            ],
        ))
        save_trace(facts_dir, _make_trace(
            session_id="beta",
            turn=1,
            timestamp="2026-06-25T15:00:00",
            steps=[{"type": "tool_call", "tool": "facts_get", "source": "fl"}],
        ))

    def test_list_all(self, project_dir: Path, facts_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        self._seed_traces(facts_dir)
        result = runner.invoke(app, ["eval", "list"])
        assert result.exit_code == 0
        assert "alpha" in result.output
        assert "beta" in result.output

    def test_list_filter_session(self, project_dir: Path, facts_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        self._seed_traces(facts_dir)
        result = runner.invoke(app, ["eval", "list", "--session", "alpha"])
        assert result.exit_code == 0
        assert "alpha" in result.output
        assert "beta" not in result.output

    def test_list_filter_session_wildcard(self, project_dir: Path, facts_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        self._seed_traces(facts_dir)
        result = runner.invoke(app, ["eval", "list", "--session", "al*"])
        assert result.exit_code == 0
        assert "alpha" in result.output

    def test_list_filter_bypassed(self, project_dir: Path, facts_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        self._seed_traces(facts_dir)
        result = runner.invoke(app, ["eval", "list", "--bypassed"])
        assert result.exit_code == 0
        assert "alpha" in result.output
        assert "beta" not in result.output

    def test_list_json(self, project_dir: Path, facts_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        self._seed_traces(facts_dir)
        result = runner.invoke(app, ["eval", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 3

    def test_list_verbose(self, project_dir: Path, facts_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        self._seed_traces(facts_dir)
        result = runner.invoke(app, ["eval", "list", "-v"])
        assert result.exit_code == 0
        assert "tool_call" in result.output
        assert "reasoning" in result.output

    def test_list_empty(self, project_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        result = runner.invoke(app, ["eval", "list"])
        assert result.exit_code == 0
        assert "No eval traces found" in result.output

    def test_list_no_facts_dir(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["eval", "list"])
        assert result.exit_code == 1


class TestEvalStats:
    def _seed_traces(self, facts_dir: Path):
        for i in range(1, 6):
            save_trace(facts_dir, _make_trace(
                turn=i,
                timestamp=f"2026-06-25T14:{30+i}:00",
                steps=[
                    {"type": "tool_call", "tool": "facts_get", "args": {"slot": "x.y"}, "source": "fl", "duration_ms": 200},
                    {"type": "tool_call", "tool": "read", "source": "doc", "duration_ms": 3000},
                    {"type": "reasoning", "rationale": "test", "source": "code"},
                ],
                summary={"facts_consumed": 1, "turn_duration_ms": 10000},
            ))

    def test_stats_output(self, project_dir: Path, facts_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        self._seed_traces(facts_dir)
        result = runner.invoke(app, ["eval", "stats"])
        assert result.exit_code == 0
        assert "FL 效果指标" in result.output
        assert "总 turns:" in result.output
        assert "FL:" in result.output

    def test_stats_json(self, project_dir: Path, facts_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        self._seed_traces(facts_dir)
        result = runner.invoke(app, ["eval", "stats", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_turns"] == 5
        assert data["fl_vs_doc"]["fl"] == 5
        assert data["fl_vs_doc"]["doc"] == 5

    def test_stats_empty(self, project_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        result = runner.invoke(app, ["eval", "stats"])
        assert result.exit_code == 0
        assert "No eval traces found" in result.output

    def test_stats_no_facts_dir(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["eval", "stats"])
        assert result.exit_code == 1

    def test_stats_filter_session(self, project_dir: Path, facts_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        save_trace(facts_dir, _make_trace(
            session_id="a",
            turn=1,
            timestamp="2026-06-25T14:30:00",
            steps=[{"type": "tool_call", "source": "fl"}],
        ))
        save_trace(facts_dir, _make_trace(
            session_id="b",
            turn=1,
            timestamp="2026-06-25T14:31:00",
            steps=[{"type": "tool_call", "source": "doc"}],
        ))
        result = runner.invoke(app, ["eval", "stats", "--session", "a", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_turns"] == 1
