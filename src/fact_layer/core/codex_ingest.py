"""FL-019 step 3: rebuild eval traces from a Codex rollout transcript.

Codex writes each session to ~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl.
This is the Codex-schema analogue of transcript_ingest.py (Claude Code): we reconstruct
L1 (tool calls + source classification) and layer on L2 (turn rationale/conclusion +
bypassed findings) via the shared, schema-agnostic extract_l2().

Design notes / why:
- Codex reasoning is ~93% encrypted (payload.reasoning.encrypted_content); plaintext
  `content` is never present and only ~7% of turns carry a plaintext `summary`. So we
  can't use the model's raw thinking for L2. Instead we feed the plaintext
  `agent_message` narrative (+ any reasoning summary) as the reasoning substitute. Bypass
  detection leans mostly on tool-sequence-vs-FL-export anyway, so L2 degrades gracefully.
- Every rollout line is an envelope: top-level `type` ∈ {session_meta, event_msg,
  response_item, turn_context}, wrapping a `payload` dict with its own `type`.
- Everything is best-effort/defensive, mirroring transcript_ingest: a malformed line, a
  failed LLM call, or a bad reply must never break the caller.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fact_layer.core.registry import resolve_facts_dir
from fact_layer.core.transcript_ingest import (
    _RETRIEVAL_SOURCES,
    _trace_exists,
    build_trace,
    classify_source,
    extract_l2,
    parse_transcript,
)
from fact_layer.core.eval_cmd import save_trace
from fact_layer.models.eval import EvalStep

# Tool names that carry file/data retrieval semantics via exec_command's first token.
_DOC_CMDS = {"rg", "grep", "ag", "cat", "sed", "nl", "head", "tail", "less", "more"}
_DB_CMD_RE = re.compile(r"^(mysql|psql|sqlite3?|mongo)", re.IGNORECASE)

# Codex tool names that are actions, not information retrieval → not a fact source.
_NON_RETRIEVAL_TOOLS = {
    "apply_patch", "write_stdin", "update_plan", "spawn_agent", "wait_agent",
    "close_agent", "send_input", "view_image", "load_workspace_dependencies", "js",
}

_DEFAULT_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


# --------------------------------------------------------------------------- #
# Envelope helpers
# --------------------------------------------------------------------------- #

def _payload(rec: dict) -> dict:
    p = rec.get("payload")
    return p if isinstance(p, dict) else {}


def _ptype(rec: dict) -> str | None:
    return _payload(rec).get("type")


def _exec_cmd(args: dict[str, Any] | None) -> str:
    """Best-effort extract the shell command string from an exec_command's args."""
    if not isinstance(args, dict):
        return ""
    cmd = args.get("cmd")
    if isinstance(cmd, str):
        return cmd
    # tolerate array form / alternate key
    command = args.get("command")
    if isinstance(command, str):
        return command
    if isinstance(command, list):
        return " ".join(str(x) for x in command)
    return ""


def _parse_args(payload: dict) -> dict[str, Any]:
    """function_call.arguments is a JSON string; custom_tool_call.input is raw text."""
    raw = payload.get("arguments")
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    inp = payload.get("input")
    if isinstance(inp, str):
        return {"input": inp[:500]}
    if isinstance(raw, dict):
        return raw
    return {}


# --------------------------------------------------------------------------- #
# L1: source classification
# --------------------------------------------------------------------------- #

def classify_source_codex(tool: str | None, args: dict[str, Any] | None) -> str | None:
    """Map a Codex tool call to an eval source bucket.

    Codex has no dedicated Read/Grep tool — everything shell-like goes through
    exec_command — so we classify at the *command* level: rg/grep and file readers
    (cat/sed/nl/…) count as `doc` (file-content retrieval), mysql-family as `db`, `fl`
    as `fl`, else `code`. This is an intentional asymmetry with Claude's coarser
    Bash→code/db mapping (see transcript_ingest.classify_source); it's the more faithful
    reading of Codex's retrieval behavior and preserves the core "doc retrieval FL could
    have served" signal.
    """
    if not tool:
        return None
    if tool == "web_search_call":
        return "web"
    if tool in _NON_RETRIEVAL_TOOLS:
        return None
    if tool in ("exec_command", "shell"):
        cmd = _exec_cmd(args).strip()
        if not cmd:
            return "code"
        first = cmd.split()[0]
        base = first.rsplit("/", 1)[-1]  # strip path, e.g. /usr/bin/rg → rg
        if base == "fl" or cmd.startswith("fl "):
            return "fl"
        if base in _DOC_CMDS:
            return "doc"
        if _DB_CMD_RE.match(base):
            return "db"
        return "code"
    # MCP facts_* and anything else Claude already knows how to bucket.
    return classify_source(tool, args)


# --------------------------------------------------------------------------- #
# Turn segmentation
# --------------------------------------------------------------------------- #

def _is_real_user_turn(rec: dict) -> bool:
    """A genuine user prompt (event_msg / user_message) with non-empty text."""
    if _ptype(rec) != "user_message":
        return False
    msg = _payload(rec).get("message")
    return isinstance(msg, str) and bool(msg.strip())


def segment_turns_codex(rows: list[dict]) -> list[tuple[int, list[dict], str]]:
    """Split rows into turns bounded by real user_message events.

    Returns (turn_no, segment_rows, user_prompt). turn_no is the 1-based index among
    real turns — stable across re-runs, so it doubles as the idempotency key (mirrors
    transcript_ingest.segment_turns).
    """
    starts = [i for i, r in enumerate(rows) if _is_real_user_turn(r)]
    bounds = starts + [len(rows)]
    turns: list[tuple[int, list[dict], str]] = []
    for k, start in enumerate(starts):
        segment = rows[start:bounds[k + 1]]
        user_prompt = str(_payload(rows[start]).get("message") or "").strip()
        turns.append((k + 1, segment, user_prompt))
    return turns


# --------------------------------------------------------------------------- #
# L1 reconstruction
# --------------------------------------------------------------------------- #

_TOOL_PTYPES = ("function_call", "custom_tool_call", "web_search_call")


def rebuild_l1_steps_codex(segment_rows: list[dict]) -> list[EvalStep]:
    steps: list[EvalStep] = []
    for r in segment_rows:
        p = _payload(r)
        if p.get("type") not in _TOOL_PTYPES:
            continue
        tool = p.get("name") or p.get("type")  # web_search_call has no name
        args = _parse_args(p)
        steps.append(
            EvalStep(
                type="tool_call",
                tool=tool,
                args=args,
                source=classify_source_codex(tool, args),
            )
        )
    return steps


# --------------------------------------------------------------------------- #
# L2 reasoning substitute (plaintext narrative)
# --------------------------------------------------------------------------- #

def gather_reasoning_codex(segment_rows: list[dict], max_chars: int = 6000) -> str:
    """Plaintext reasoning substitute: agent_message narrative + any reasoning summary.

    Codex reasoning is mostly encrypted; agent_message is the assistant's visible output
    and reasoning.summary[].text is present on the ~7% of turns with reasoning summaries.
    """
    parts: list[str] = []
    for r in segment_rows:
        p = _payload(r)
        pt = p.get("type")
        if pt == "agent_message":
            msg = p.get("message")
            if isinstance(msg, str) and msg.strip():
                parts.append("[叙述] " + msg.strip())
        elif pt == "reasoning":
            for item in p.get("summary") or []:
                if isinstance(item, dict) and item.get("text"):
                    parts.append("[思考] " + str(item["text"]))
    joined = "\n".join(parts)
    if len(joined) > max_chars:  # keep head + tail, drop the middle (mirrors Claude)
        head = joined[: max_chars * 2 // 3]
        tail = joined[-max_chars // 3:]
        joined = head + "\n...[中间推理省略]...\n" + tail
    return joined


# --------------------------------------------------------------------------- #
# Session / facts-dir / file location
# --------------------------------------------------------------------------- #

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def _session_meta(rows: list[dict]) -> dict:
    for r in rows:
        if r.get("type") == "session_meta":
            return _payload(r)
    return {}


def session_id_from_rollout(rows: list[dict], path: str | Path) -> str:
    """session_meta.id, falling back to the uuid embedded in the filename."""
    sid = _session_meta(rows).get("id")
    if isinstance(sid, str) and sid:
        return sid
    m = _UUID_RE.search(Path(path).name)
    return m.group(0) if m else Path(path).stem


def facts_dir_from_rollout(rows: list[dict]) -> Path | None:
    """Route to the .facts/ of the project the Codex session ran in (session_meta.cwd)."""
    cwd = _session_meta(rows).get("cwd")
    if isinstance(cwd, str) and cwd:
        fd = resolve_facts_dir(Path(cwd))
        if fd:
            return fd
    return resolve_facts_dir()


def locate_latest_rollout(
    session_uuid: str | None = None, sessions_dir: Path | None = None
) -> Path | None:
    """Find a rollout under ~/.codex/sessions/**/. Match by uuid, else newest by mtime.

    Note the nested YYYY/MM/DD layout — a recursive glob is required (the flat-dir
    assumption in earlier notes was wrong).
    """
    base = sessions_dir or _DEFAULT_SESSIONS_DIR
    if not base.is_dir():
        return None
    files = list(base.glob("**/rollout-*.jsonl"))
    if not files:
        return None
    if session_uuid:
        matches = [f for f in files if session_uuid.lower() in f.name.lower()]
        if matches:
            return max(matches, key=lambda f: f.stat().st_mtime)
    return max(files, key=lambda f: f.stat().st_mtime)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def ingest_rollout(
    rollout_path: str | Path | None = None,
    session: str | None = None,
    *,
    only_last_turn: bool = True,
    model: str | None = None,
    facts_dir: Path | None = None,
    harness: str = "codex",
) -> dict:
    """Rebuild eval trace(s) from a Codex rollout. Returns a report dict.

    Mirrors transcript_ingest.ingest_transcript: writes a trace only for evaluable turns
    (>=1 retrieval tool call), layers L2 best-effort, idempotent by (session, turn_no).
    session and facts_dir are auto-derived from the rollout's session_meta when omitted.
    """
    report: dict = {"written": [], "skipped": [], "no_retrieval": [], "errors": []}

    if rollout_path is None:
        rollout_path = locate_latest_rollout(session)
        if rollout_path is None:
            report["errors"].append("no rollout file found under ~/.codex/sessions")
            return report

    rows = parse_transcript(rollout_path)
    if not rows:
        report["errors"].append("empty or unreadable rollout")
        return report

    session = session or session_id_from_rollout(rows, rollout_path)
    facts_dir = facts_dir or facts_dir_from_rollout(rows)
    if not facts_dir:
        report["errors"].append("no .facts/ directory")
        return report

    turns = segment_turns_codex(rows)
    if only_last_turn:
        turns = turns[-1:]

    for turn_no, segment_rows, user_prompt in turns:
        try:
            if _trace_exists(facts_dir, session, turn_no):
                report["skipped"].append(turn_no)
                continue

            steps = rebuild_l1_steps_codex(segment_rows)
            has_retrieval = any(s.source in _RETRIEVAL_SOURCES for s in steps)
            if not has_retrieval:
                report["no_retrieval"].append(turn_no)
                continue

            reasoning = gather_reasoning_codex(segment_rows)
            rationale, conclusion, bypassed = extract_l2(
                user_prompt, reasoning, steps, facts_dir, model
            )
            if rationale or conclusion:
                steps.append(
                    EvalStep(type="reasoning", rationale=rationale, conclusion=conclusion)
                )
            for b in bypassed:
                steps.append(EvalStep(type="reasoning", bypassed=b))

            trace = build_trace(session, turn_no, steps, harness=harness)
            save_trace(facts_dir, trace)
            report["written"].append(turn_no)
        except Exception as e:  # never let one turn break the rest / the caller
            report["errors"].append({"turn": turn_no, "error": str(e)[:200]})

    return report
