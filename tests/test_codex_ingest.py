"""FL-019 step 3: tests for the Codex rollout adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fact_layer.core import codex_ingest
from fact_layer.core.codex_ingest import (
    classify_source_codex,
    gather_reasoning_codex,
    ingest_rollout,
    locate_latest_rollout,
    rebuild_l1_steps_codex,
    segment_turns_codex,
    session_id_from_rollout,
)
from fact_layer.core.eval_cmd import load_traces


# --------------------------------------------------------------------------- #
# Fixtures: build rollout envelope rows
# --------------------------------------------------------------------------- #

def _fn_call(name: str, arguments: dict) -> dict:
    return {
        "type": "response_item",
        "payload": {"type": "function_call", "name": name,
                    "arguments": json.dumps(arguments), "call_id": "c1"},
    }


def _custom_call(name: str, inp: str) -> dict:
    return {
        "type": "response_item",
        "payload": {"type": "custom_tool_call", "name": name, "input": inp,
                    "status": "completed", "call_id": "c2"},
    }


def _web_call() -> dict:
    return {"type": "response_item",
            "payload": {"type": "web_search_call", "status": "completed"}}


def _mcp_call(name: str) -> dict:
    return {"type": "response_item",
            "payload": {"type": "function_call", "name": name, "arguments": "{}", "call_id": "c3"}}


def _user(msg: str) -> dict:
    return {"type": "event_msg", "payload": {"type": "user_message", "message": msg}}


def _agent(msg: str) -> dict:
    return {"type": "event_msg",
            "payload": {"type": "agent_message", "message": msg, "phase": "commentary"}}


def _reasoning(summary_text: str | None = None) -> dict:
    p = {"type": "reasoning", "summary": [], "content": None, "encrypted_content": "xxx"}
    if summary_text:
        p["summary"] = [{"type": "summary_text", "text": summary_text}]
    return {"type": "response_item", "payload": p}


def _session_meta(sid: str, cwd: str) -> dict:
    return {"type": "session_meta",
            "payload": {"type": "session_meta", "id": sid, "cwd": cwd}}


# --------------------------------------------------------------------------- #
# classify_source_codex
# --------------------------------------------------------------------------- #

class TestClassify:
    @pytest.mark.parametrize("cmd,expected", [
        ("rg foo src/", "doc"),
        ("grep -n bar file", "doc"),
        ("cat README.md", "doc"),
        ("sed -n 1,5p f", "doc"),
        ("nl file", "doc"),
        ("/usr/bin/rg pattern", "doc"),   # path-stripped
        ("git status", "code"),
        ("python3 x.py", "code"),
        ("pytest", "code"),
        ("fl get slot", "fl"),
        ("sqlite3 db.sqlite", "db"),
        ("mysql -u root", "db"),
        ("", "code"),
    ])
    def test_exec_command(self, cmd, expected):
        assert classify_source_codex("exec_command", {"cmd": cmd}) == expected

    def test_apply_patch_is_none(self):
        assert classify_source_codex("apply_patch", {"input": "*** Begin Patch"}) is None

    def test_non_retrieval_tools_none(self):
        for t in ("write_stdin", "update_plan", "spawn_agent", "view_image"):
            assert classify_source_codex(t, {}) is None

    def test_web_search(self):
        assert classify_source_codex("web_search_call", {}) == "web"

    def test_mcp_facts_delegates_to_fl(self):
        assert classify_source_codex("facts_get", {}) == "fl"
        assert classify_source_codex("facts_export", {}) == "fl"

    def test_none_tool(self):
        assert classify_source_codex(None, {}) is None


# --------------------------------------------------------------------------- #
# segmentation
# --------------------------------------------------------------------------- #

class TestSegment:
    def test_splits_on_user_messages(self):
        rows = [
            _session_meta("s1", "/tmp"),
            _user("first"), _fn_call("exec_command", {"cmd": "rg x"}),
            _user("second"), _fn_call("exec_command", {"cmd": "git s"}),
        ]
        turns = segment_turns_codex(rows)
        assert [t[0] for t in turns] == [1, 2]
        assert turns[0][2] == "first"
        assert turns[1][2] == "second"

    def test_filters_empty_user_messages(self):
        rows = [_user("  "), _user("real"), _fn_call("exec_command", {"cmd": "ls"})]
        turns = segment_turns_codex(rows)
        assert len(turns) == 1
        assert turns[0][2] == "real"

    def test_no_user_messages(self):
        assert segment_turns_codex([_fn_call("exec_command", {"cmd": "ls"})]) == []


# --------------------------------------------------------------------------- #
# L1 rebuild + reasoning
# --------------------------------------------------------------------------- #

class TestRebuildL1:
    def test_parses_function_call_args(self):
        rows = [_fn_call("exec_command", {"cmd": "rg foo"})]
        steps = rebuild_l1_steps_codex(rows)
        assert len(steps) == 1
        assert steps[0].tool == "exec_command"
        assert steps[0].args == {"cmd": "rg foo"}
        assert steps[0].source == "doc"

    def test_custom_tool_call_captured_non_retrieval(self):
        steps = rebuild_l1_steps_codex([_custom_call("apply_patch", "*** Begin Patch")])
        assert len(steps) == 1
        assert steps[0].tool == "apply_patch"
        assert steps[0].source is None

    def test_web_search_call_has_tool_name(self):
        steps = rebuild_l1_steps_codex([_web_call()])
        assert steps[0].tool == "web_search_call"
        assert steps[0].source == "web"

    def test_ignores_non_tool_payloads(self):
        assert rebuild_l1_steps_codex([_user("x"), _agent("y"), _reasoning()]) == []


class TestReasoning:
    def test_gathers_agent_message_and_summary(self):
        rows = [_agent("I will search"), _reasoning("thinking hard"), _agent("done")]
        r = gather_reasoning_codex(rows)
        assert "[叙述] I will search" in r
        assert "[思考] thinking hard" in r
        assert "[叙述] done" in r

    def test_encrypted_only_reasoning_yields_no_thought(self):
        r = gather_reasoning_codex([_reasoning(None)])
        assert "[思考]" not in r


# --------------------------------------------------------------------------- #
# session id / locate
# --------------------------------------------------------------------------- #

class TestSessionAndLocate:
    def test_session_id_from_meta(self):
        rows = [_session_meta("abc-123", "/tmp")]
        assert session_id_from_rollout(rows, "rollout-x.jsonl") == "abc-123"

    def test_session_id_fallback_to_filename_uuid(self):
        name = "rollout-2026-04-20T15-56-14-019da9e3-d56a-74d3-8f4b-ed9aa900f157.jsonl"
        assert session_id_from_rollout([], name) == "019da9e3-d56a-74d3-8f4b-ed9aa900f157"

    def test_locate_recursive_newest(self, tmp_path: Path):
        d = tmp_path / "2026" / "04" / "20"
        d.mkdir(parents=True)
        old = d / "rollout-2026-04-20T10-00-00-aaaa.jsonl"
        new = d / "rollout-2026-04-20T11-00-00-bbbb.jsonl"
        old.write_text("{}\n"); new.write_text("{}\n")
        import os
        os.utime(old, (1, 1)); os.utime(new, (2, 2))
        assert locate_latest_rollout(sessions_dir=tmp_path) == new

    def test_locate_matches_uuid(self, tmp_path: Path):
        d = tmp_path / "2026" / "04" / "20"; d.mkdir(parents=True)
        a = d / "rollout-2026-04-20T10-00-00-target.jsonl"
        b = d / "rollout-2026-04-20T11-00-00-other.jsonl"
        a.write_text("{}\n"); b.write_text("{}\n")
        assert locate_latest_rollout("target", sessions_dir=tmp_path) == a

    def test_locate_missing_dir(self, tmp_path: Path):
        assert locate_latest_rollout(sessions_dir=tmp_path / "nope") is None


# --------------------------------------------------------------------------- #
# end-to-end ingest_rollout (LLM stubbed)
# --------------------------------------------------------------------------- #

@pytest.fixture
def facts_dir(tmp_path: Path) -> Path:
    fd = tmp_path / ".facts"
    (fd / "eval").mkdir(parents=True)
    return fd


def _write_rollout(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "rollout-2026-04-20T15-56-14-019da9e3-test.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


class TestIngestRollout:
    def test_writes_trace_with_codex_harness(self, tmp_path, facts_dir, monkeypatch):
        monkeypatch.setattr(codex_ingest, "extract_l2",
                            lambda *a, **k: ("rationale", "concl", []))
        rows = [
            _session_meta("sess-1", str(tmp_path)),
            _user("please look up the schema"),
            _agent("checking FL"),
            _mcp_call("facts_get"),
            _fn_call("exec_command", {"cmd": "rg pattern src/"}),
        ]
        path = _write_rollout(tmp_path, rows)
        report = ingest_rollout(path, only_last_turn=True, facts_dir=facts_dir)
        assert report["written"] == [1]
        traces = load_traces(facts_dir)
        assert len(traces) == 1
        assert traces[0].harness == "codex"
        assert traces[0].session_id == "sess-1"
        sources = {s.source for s in traces[0].steps if s.source}
        assert "fl" in sources and "doc" in sources

    def test_idempotent_rerun_skips(self, tmp_path, facts_dir, monkeypatch):
        monkeypatch.setattr(codex_ingest, "extract_l2", lambda *a, **k: (None, None, []))
        rows = [
            _session_meta("sess-2", str(tmp_path)),
            _user("q"), _mcp_call("facts_get"),
        ]
        path = _write_rollout(tmp_path, rows)
        assert ingest_rollout(path, facts_dir=facts_dir)["written"] == [1]
        assert ingest_rollout(path, facts_dir=facts_dir)["skipped"] == [1]

    def test_no_retrieval_turn_skipped(self, tmp_path, facts_dir, monkeypatch):
        monkeypatch.setattr(codex_ingest, "extract_l2", lambda *a, **k: (None, None, []))
        rows = [
            _session_meta("sess-3", str(tmp_path)),
            _user("just edit"), _custom_call("apply_patch", "*** patch"),
        ]
        path = _write_rollout(tmp_path, rows)
        report = ingest_rollout(path, facts_dir=facts_dir)
        assert report["no_retrieval"] == [1]
        assert report["written"] == []

    def test_facts_dir_autoderived_from_cwd(self, tmp_path, monkeypatch):
        # session_meta.cwd points into a project whose .facts/ we should resolve to.
        proj = tmp_path / "proj"
        (proj / ".facts" / "eval").mkdir(parents=True)
        # resolve_facts_dir requires framework.yaml as the .facts marker
        (proj / ".facts" / "framework.yaml").write_text("version: 1\n")
        monkeypatch.setattr(codex_ingest, "extract_l2", lambda *a, **k: (None, None, []))
        rows = [
            _session_meta("sess-4", str(proj)),
            _user("q"), _mcp_call("facts_get"),
        ]
        path = _write_rollout(tmp_path, rows)
        report = ingest_rollout(path)  # no explicit facts_dir
        assert report["written"] == [1]
        assert len(load_traces(proj / ".facts")) == 1

    def test_empty_rollout_reports_error(self, tmp_path, facts_dir):
        p = tmp_path / "rollout-empty.jsonl"
        p.write_text("")
        report = ingest_rollout(p, facts_dir=facts_dir)
        assert report["errors"]


class TestCodexRoutingNoFallback:
    def test_no_fallback_to_command_cwd(self, tmp_path, monkeypatch):
        """When the session's own cwd resolves to no .facts/, routing must return
        None — never silently fall back to whatever project the ingest command was
        run from (guards cross-project eval pollution)."""
        standing = tmp_path / "standing"
        (standing / ".facts").mkdir(parents=True)
        (standing / ".facts" / "framework.yaml").write_text("version: 1\n")
        monkeypatch.chdir(standing)
        foreign = tmp_path / "jobcity"
        foreign.mkdir()  # no .facts/ up its tree
        rows = [_session_meta("sess-x", str(foreign))]

        assert codex_ingest.facts_dir_from_rollout(rows) is None

    def test_routes_to_session_cwd_when_resolvable(self, tmp_path):
        proj = tmp_path / "proj"
        (proj / ".facts").mkdir(parents=True)
        (proj / ".facts" / "framework.yaml").write_text("version: 1\n")
        rows = [_session_meta("sess-y", str(proj))]

        assert codex_ingest.facts_dir_from_rollout(rows) == proj / ".facts"
