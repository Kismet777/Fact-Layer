"""Routing tests for the Claude-transcript eval ingester.

Guards against cross-project eval pollution: a transcript from project A must
never land in project B's .facts/eval/ just because the operator ran the ingest
command while standing in B. Root cause captured 2026-08-10 (5 jobcity-recsys
turns had leaked into the 贷后催收 eval store via the command-cwd fallback).
"""

from __future__ import annotations

import json
from pathlib import Path

from fact_layer.core import transcript_ingest
from fact_layer.core.eval_cmd import load_traces
from fact_layer.core.transcript_ingest import ingest_transcript


def _user(text: str, cwd: str) -> dict:
    return {"type": "user", "cwd": cwd, "message": {"content": text}}


def _assistant_tool(tool: str, inp: dict, cwd: str) -> dict:
    return {
        "type": "assistant",
        "cwd": cwd,
        "message": {"content": [{"type": "tool_use", "name": tool, "input": inp}]},
    }


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "session-transcript.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


def _make_facts(root: Path) -> Path:
    fd = root / ".facts"
    (fd / "eval").mkdir(parents=True)
    (fd / "framework.yaml").write_text("version: 1\n")  # resolve_facts_dir marker
    return fd


class TestTranscriptRouting:
    def test_routes_to_session_cwd_facts(self, tmp_path, monkeypatch):
        """No explicit facts_dir → derive from the transcript's own cwd."""
        proj = tmp_path / "proj"
        proj.mkdir()
        fd = _make_facts(proj)
        monkeypatch.setattr(transcript_ingest, "extract_l2", lambda *a, **k: (None, None, []))
        rows = [
            _user("look up the schema", str(proj)),
            _assistant_tool("Read", {"file_path": "x"}, str(proj)),
        ]
        path = _write(tmp_path, rows)

        report = ingest_transcript(path, "sess-a", only_last_turn=True)  # no facts_dir

        assert report["written"] == [1]
        assert len(load_traces(fd)) == 1

    def test_does_not_misroute_cross_project(self, tmp_path, monkeypatch):
        """Session ran in a project with NO .facts/; operator stands in a different
        project that DOES have one. The foreign turn must NOT be dumped into the
        standing project — it must be skipped with an error."""
        foreign = tmp_path / "jobcity"
        foreign.mkdir()  # deliberately no .facts/ anywhere up its tree
        standing = tmp_path / "standing"
        standing.mkdir()
        standing_fd = _make_facts(standing)
        monkeypatch.chdir(standing)
        monkeypatch.setattr(transcript_ingest, "extract_l2", lambda *a, **k: (None, None, []))
        rows = [
            _user("audit diversity.py", str(foreign)),
            _assistant_tool("Read", {"file_path": "x"}, str(foreign)),
        ]
        path = _write(tmp_path, rows)

        report = ingest_transcript(path, "sess-foreign", only_last_turn=True)  # no facts_dir

        assert load_traces(standing_fd) == []  # nothing leaked into the standing project
        assert report["written"] == []
        assert report["errors"]

    def test_explicit_facts_dir_is_honored(self, tmp_path, monkeypatch):
        """An explicitly passed facts_dir always wins (caller override)."""
        target = tmp_path / "target"
        target.mkdir()
        target_fd = _make_facts(target)
        monkeypatch.setattr(transcript_ingest, "extract_l2", lambda *a, **k: (None, None, []))
        rows = [
            _user("q", "/nonexistent/project"),
            _assistant_tool("Read", {"file_path": "x"}, "/nonexistent/project"),
        ]
        path = _write(tmp_path, rows)

        report = ingest_transcript(
            path, "sess-x", only_last_turn=True, facts_dir=target_fd
        )

        assert report["written"] == [1]
        assert len(load_traces(target_fd)) == 1