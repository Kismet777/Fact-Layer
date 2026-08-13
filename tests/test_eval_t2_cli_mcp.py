"""S1 — CLI `fl eval effectiveness` + MCP `facts_eval_effectiveness` parity.

LLM is stubbed by monkeypatching ``eval_t2.default_backend`` — no live call. Both
surfaces funnel through ``run_effectiveness`` so parity is structural; these tests
lock it (same filters → same report) and check the T1/T2 分栏 wording + degradation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import fact_layer.core.eval_t2 as eval_t2
from fact_layer.cli import app
from fact_layer.core.eval_cmd import save_trace
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.mcp_server import facts_eval_effectiveness
from fact_layer.models.eval import EvalStep, EvalSummary, EvalTrace

runner = CliRunner()


def _trace(session_id="proj", turn=1, timestamp="2026-08-13T10:00:00", steps=None):
    return EvalTrace(
        session_id=session_id,
        turn=turn,
        timestamp=timestamp,
        steps=[EvalStep.model_validate(s) for s in (steps or [])],
        summary=EvalSummary(),
    )


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    init_facts_dir(
        target=proj,
        project_name="test-project",
        language="Python 3.12",
        enabled_extensions=[],
        enabled_optional=[],
    )
    monkeypatch.chdir(proj)
    facts_dir = proj / ".facts"
    save_trace(
        facts_dir,
        _trace(
            steps=[
                {"type": "tool_call", "tool": "facts_get", "args": {"slot": "x.y"}, "source": "fl"},
                {"type": "tool_call", "tool": "read", "source": "doc"},
            ],
        ),
    )
    return proj


@pytest.fixture
def stub_backend(monkeypatch):
    """Replace the real LLM backend with a canned A-verdict stub (no live call)."""
    monkeypatch.setattr(
        eval_t2, "default_backend", lambda: (lambda p: '{"verdict": "A", "rationale": "ok"}')
    )


class TestEffectivenessCLI:
    def test_dry_run_no_llm(self, project: Path):
        result = runner.invoke(app, ["eval", "effectiveness", "--dry-run"])
        assert result.exit_code == 0
        assert "dry-run" in result.output
        # T1/T2 分栏: both sections labelled, counts marked as "非有效性"
        assert "T1 相关计数" in result.output
        assert "非有效性" in result.output

    def test_full_run_reports_adoption(self, project: Path, stub_backend):
        result = runner.invoke(app, ["eval", "effectiveness"])
        assert result.exit_code == 0
        assert "采纳率" in result.output
        assert "100%" in result.output  # single A read → A/(A+B)=100%

    def test_json_output(self, project: Path, stub_backend):
        result = runner.invoke(app, ["eval", "effectiveness", "--json"])
        assert result.exit_code == 0
        import json

        out = json.loads(result.output)
        assert out["t2"]["by_verdict"]["A"] == 1
        assert out["t1"] is not None


class TestEffectivenessMCP:
    def test_dry_run(self, project: Path):
        out = facts_eval_effectiveness(dry_run=True)
        assert out["dry_run"] is True
        assert out["total_reads"] == 1
        assert out["t2"] is None

    def test_full_run(self, project: Path, stub_backend):
        out = facts_eval_effectiveness()
        assert out["t2"]["adoption_rate"] == pytest.approx(1.0)


class TestParity:
    def test_cli_and_mcp_agree_dry_run(self, project: Path):
        import json

        cli = json.loads(
            runner.invoke(app, ["eval", "effectiveness", "--dry-run", "--json"]).output
        )
        mcp = facts_eval_effectiveness(dry_run=True)
        assert cli["total_reads"] == mcp["total_reads"]
        assert cli["t1"]["fl_vs_doc"] == mcp["t1"]["fl_vs_doc"]

    def test_cli_and_mcp_agree_full_run(self, project: Path, stub_backend):
        import json

        cli = json.loads(runner.invoke(app, ["eval", "effectiveness", "--json"]).output)
        # re-seed fresh: cli run already persisted verdicts, so mcp hits cache →
        # same report (idempotent). That's exactly the parity we want.
        mcp = facts_eval_effectiveness()
        assert cli["t2"]["by_verdict"] == mcp["t2"]["by_verdict"]
        assert cli["t2"]["adoption_rate"] == mcp["t2"]["adoption_rate"]