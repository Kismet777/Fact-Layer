"""FL-018 step 1: rebuild eval traces from a Claude Code session transcript.

Single-source rebuild: the session transcript (~/.claude/projects/<enc>/<sid>.jsonl)
is a complete superset of tool activity plus the agent's reasoning (thinking/text).
We reconstruct L1 (tool calls + source classification) and extract L2 (turn-level
rationale/conclusion + bypassed findings) via one LLM call per evaluable turn.

Design notes / why:
- L2 can't be captured by a PostToolUse hook (reasoning lives inside the model, not
  around the tool call), and asking the agent to self-report was already proven
  unreliable. The transcript is the objective already-existing record.
- Everything is best-effort and defensive: a malformed transcript line, a failed LLM
  call, or a bad JSON reply must never break the caller (the Stop hook). L1 is always
  written; L2 is layered on when possible.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fact_layer.core.eval_cmd import _sanitize_filename, save_trace
from fact_layer.core.exporter import render_export_budgeted
from fact_layer.core.llm import llm_call
from fact_layer.core.registry import resolve_facts_dir
from fact_layer.models.eval import BypassInfo, EvalStep, EvalSummary, EvalTrace

# Tool-call sources that count as information retrieval (evaluable behavior).
_RETRIEVAL_SOURCES = ("fl", "doc", "code", "db", "web")

_DB_RE = re.compile(r"(mysql|psql|sqlite|mongo)", re.IGNORECASE)


def classify_source(tool: str | None, args: dict[str, Any] | None) -> str | None:
    """Map a transcript tool name to an eval source bucket.

    Mirrors fl-eval-capture.sh, and fixes the Grep漏采 (Grep is file-content retrieval).
    Returns None for non-retrieval tools (Edit/Write/Glob/Task/…) — still recorded as a
    tool_call step, but not counted as a fact source.
    """
    if not tool:
        return None
    if tool.startswith("mcp__"):
        low = tool.lower()
        if "fact-layer" in low or "facts" in low or "fl" in low:
            return "fl"
    if tool in (
        "facts_get", "facts_list", "facts_export", "facts_set",
        "facts_check", "facts_audit", "facts_set_batch",
    ):
        return "fl"
    if tool in ("Read", "read"):
        return "doc"
    if tool in ("Grep", "grep"):  # FIX FL-018: Grep was previously dropped
        return "doc"
    if tool in ("Bash", "bash"):
        cmd = ""
        if isinstance(args, dict):
            cmd = str(args.get("command", ""))
        return "db" if _DB_RE.search(cmd) else "code"
    if tool in ("WebSearch", "WebFetch", "web_search", "web_fetch"):
        return "web"
    return None


# --------------------------------------------------------------------------- #
# Transcript parsing + turn segmentation
# --------------------------------------------------------------------------- #

def parse_transcript(path: str | Path) -> list[dict]:
    """Read a JSONL transcript defensively (skip blank/corrupt lines)."""
    rows: list[dict] = []
    p = Path(path)
    if not p.is_file():
        return rows
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _cwd_from_rows(rows: list[dict]) -> str | None:
    """First non-empty per-record `cwd` — the directory the session ran in."""
    for r in rows:
        cwd = r.get("cwd")
        if isinstance(cwd, str) and cwd:
            return cwd
    return None


def facts_dir_from_transcript(rows: list[dict]) -> Path | None:
    """Route to the .facts/ of the project the session actually ran in (its cwd).

    Returns None when the session's own cwd resolves to no .facts/. Callers must
    NOT fall back to the ingest command's cwd: that misroutes a cross-project
    transcript into whatever project the operator happens to be standing in
    (root cause of the 2026-08-10 jobcity-recsys→贷后 eval pollution)."""
    cwd = _cwd_from_rows(rows)
    if cwd:
        return resolve_facts_dir(Path(cwd))
    return None


def _message_text(rec: dict) -> str:
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _is_real_user_turn_start(rec: dict) -> bool:
    """A genuine user prompt that starts a main-thread turn.

    Excludes: subagent sidechains, meta records, tool_result carriers, and
    slash-command / local-command wrapper messages (which masquerade as user turns).
    """
    if rec.get("type") != "user":
        return False
    if rec.get("isSidechain") is True or rec.get("isMeta") is True:
        return False
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    ):
        return False
    text = _message_text(rec).strip()
    if not text:
        return False
    if text.startswith("<command-") or text.startswith("<local-command-"):
        return False
    return True


def segment_turns(rows: list[dict]) -> list[tuple[int, list[dict], dict]]:
    """Split rows into main-thread turns.

    Returns list of (turn_no, segment_rows, user_record). turn_no is the 1-based
    index among real turns — stable across re-runs (deterministic), so it doubles
    as the idempotency key.
    """
    starts = [i for i, r in enumerate(rows) if _is_real_user_turn_start(r)]
    bounds = starts + [len(rows)]
    turns: list[tuple[int, list[dict], dict]] = []
    for k, start in enumerate(starts):
        turns.append((k + 1, rows[start:bounds[k + 1]], rows[start]))
    return turns


# --------------------------------------------------------------------------- #
# L1 reconstruction
# --------------------------------------------------------------------------- #

def _iter_main_assistant_blocks(segment_rows: list[dict]):
    for r in segment_rows:
        if r.get("isSidechain") is True:  # subagent work is a separate concern
            continue
        if r.get("type") != "assistant":
            continue
        for b in (r.get("message") or {}).get("content", []) or []:
            if isinstance(b, dict):
                yield r, b


def rebuild_l1_steps(segment_rows: list[dict]) -> list[EvalStep]:
    steps: list[EvalStep] = []
    for r, b in _iter_main_assistant_blocks(segment_rows):
        if b.get("type") != "tool_use":
            continue
        tool = b.get("name")
        args = b.get("input")
        if not isinstance(args, dict):
            args = {}
        steps.append(
            EvalStep(
                type="tool_call",
                ts=r.get("timestamp"),
                tool=tool,
                args=args,
                source=classify_source(tool, args),
            )
        )
    return steps


# --------------------------------------------------------------------------- #
# L2 extraction (best-effort)
# --------------------------------------------------------------------------- #

def _gather_reasoning(segment_rows: list[dict], max_chars: int = 6000) -> str:
    parts: list[str] = []
    for _r, b in _iter_main_assistant_blocks(segment_rows):
        t = b.get("type")
        if t == "thinking" and b.get("thinking"):
            parts.append("[思考] " + str(b["thinking"]))
        elif t == "text" and b.get("text"):
            parts.append("[叙述] " + str(b["text"]))
    joined = "\n".join(parts)
    if len(joined) > max_chars:  # keep head + tail, drop the middle
        head = joined[: max_chars * 2 // 3]
        tail = joined[-max_chars // 3:]
        joined = head + "\n...[中间推理省略]...\n" + tail
    return joined


def _tool_sequence(steps: list[EvalStep], max_items: int = 80) -> str:
    lines: list[str] = []
    for s in steps[:max_items]:
        arg_preview = ""
        if s.args:
            arg_preview = json.dumps(s.args, ensure_ascii=False)[:120]
        lines.append(f"- {s.tool}({s.source or '-'}) {arg_preview}")
    if len(steps) > max_items:
        lines.append(f"- …(+{len(steps) - max_items} more)")
    return "\n".join(lines)


def _extract_json(raw: str) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    # tolerate prose around the JSON object
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except Exception:
            return None
    return None


_L2_PROMPT = """你在分析一次 AI agent 的单个 turn，判断它的信息获取行为是否高效、是否绕过了已有的事实层(FL)。

【用户这一 turn 的请求】
{user_prompt}

【agent 的推理链路（思考+叙述，可能截断）】
{reasoning}

【agent 的工具调用序列（source: fl=事实层 doc=读文档/检索 code=命令 db=数据库 web=搜网 -=其他）】
{tool_seq}

【事实层(FL)当前已有的槽位（agent 本可直接查询这些，而非外部检索）】
{fl_export}

只输出 JSON（不要任何解释文字）：
{{
  "turn_rationale": "这一 turn agent 的信息获取路径概述：为什么这样查、走了什么弯路",
  "conclusion": "结论：信息获取是否高效？关键结论",
  "bypassed": [
    {{"rule": "已有未用 或 缺槽位", "reason": "具体说明"}}
  ]
}}

判定规则：
- agent 外部检索(doc/code/web)的事实其实 FL 已有 → rule="已有未用"（可发现性问题）。
- agent 反复外部检索某事实但 FL 没有 → rule="缺槽位"，且 reason 中必须包含"槽位"或"未覆盖"字样。
- 没有明显问题时 bypassed 返回 []。"""


def extract_l2(
    user_prompt: str,
    reasoning: str,
    steps: list[EvalStep],
    facts_dir: Path,
    model: str | None,
) -> tuple[str | None, str | None, list[BypassInfo]]:
    """One LLM call → (turn_rationale, conclusion, bypassed). Best-effort; ('',[]) on failure.

    Schema-agnostic: callers extract the plaintext user prompt + reasoning narrative from
    their own transcript format (Claude thinking/text blocks, Codex agent_message/summary),
    so this L2 stage is shared across harnesses.
    """
    try:
        fl_export = render_export_budgeted(facts_dir, budget_tokens=3000)
    except Exception:
        fl_export = "(无法加载 FL 导出)"
    prompt = _L2_PROMPT.format(
        user_prompt=(user_prompt or "").strip()[:1500] or "(空)",
        reasoning=reasoning or "(无推理记录)",
        tool_seq=_tool_sequence(steps) or "(无工具调用)",
        fl_export=fl_export[:6000],
    )
    try:
        # Reasoning models spend early tokens on chain-of-thought; leave room for
        # the final JSON. (L2 output itself is small — rationale/conclusion/bypassed.)
        raw = llm_call(prompt, role="ingest", model=model, max_tokens=4000)
    except Exception:
        return None, None, []
    data = _extract_json(raw)
    if not isinstance(data, dict):
        return None, None, []
    rationale = data.get("turn_rationale") or None
    conclusion = data.get("conclusion") or None
    bypassed: list[BypassInfo] = []
    for item in data.get("bypassed", []) or []:
        if isinstance(item, dict) and item.get("reason"):
            bypassed.append(
                BypassInfo(
                    rule=str(item.get("rule") or "bypassed"),
                    reason=str(item["reason"]),
                )
            )
    return rationale, conclusion, bypassed


# --------------------------------------------------------------------------- #
# Trace assembly + idempotency
# --------------------------------------------------------------------------- #

def _trace_exists(facts_dir: Path, session: str, turn_no: int) -> bool:
    eval_dir = facts_dir / "eval"
    if not eval_dir.is_dir():
        return False
    session_safe = _sanitize_filename(session)
    return any(eval_dir.glob(f"*_{session_safe}_turn-{turn_no:03d}.yaml"))


def _build_summary(steps: list[EvalStep]) -> EvalSummary:
    sources: Counter[str] = Counter(s.source for s in steps if s.source)
    return EvalSummary(
        facts_consumed=sources.get("fl", 0),
        sources=dict(sources),
        fl_vs_doc={"fl": sources.get("fl", 0), "doc": sources.get("doc", 0)},
        bypassed_count=sum(1 for s in steps if s.bypassed),
    )


def build_trace(
    session: str, turn_no: int, steps: list[EvalStep], harness: str = "unknown"
) -> EvalTrace:
    return EvalTrace(
        session_id=session,
        turn=turn_no,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        harness=harness,
        steps=steps,
        summary=_build_summary(steps),
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def ingest_transcript(
    transcript_path: str | Path,
    session: str,
    *,
    only_last_turn: bool = True,
    model: str | None = None,
    facts_dir: Path | None = None,
    harness: str = "claude-code",
) -> dict:
    """Rebuild eval trace(s) from a transcript. Returns a report dict.

    Writes a trace only for evaluable turns (>=1 retrieval tool call). L2 is layered on
    best-effort. Idempotent: turns already having a trace file are skipped.
    """
    report: dict = {"written": [], "skipped": [], "no_retrieval": [], "errors": []}

    rows = parse_transcript(transcript_path)
    if not rows:
        report["errors"].append("empty or unreadable transcript")
        return report

    if facts_dir is None:
        facts_dir = facts_dir_from_transcript(rows)
    if not facts_dir:
        report["errors"].append(
            "no .facts/ for the session's project (transcript cwd unresolved); "
            "refusing to fall back to the ingest command's cwd"
        )
        return report

    turns = segment_turns(rows)
    if only_last_turn:
        turns = turns[-1:]

    for turn_no, segment_rows, user_record in turns:
        try:
            if _trace_exists(facts_dir, session, turn_no):
                report["skipped"].append(turn_no)
                continue

            steps = rebuild_l1_steps(segment_rows)
            has_retrieval = any(s.source in _RETRIEVAL_SOURCES for s in steps)
            if not has_retrieval:
                report["no_retrieval"].append(turn_no)
                continue

            user_prompt = _message_text(user_record).strip()
            reasoning = _gather_reasoning(segment_rows)
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
