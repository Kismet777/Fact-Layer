from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


SOURCE_TYPES = ("fl", "doc", "code", "db", "web", "inference")


class BypassInfo(BaseModel):
    rule: str
    reason: str


class EvalStep(BaseModel):
    type: Literal["tool_call", "reasoning"]
    ts: str | None = None
    duration_ms: int | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    result_used_for: str | None = None
    rationale: str | None = None
    conclusion: str | None = None
    source: Literal["fl", "doc", "code", "db", "web", "inference"] | None = None
    bypassed: BypassInfo | None = None


class EvalSummary(BaseModel):
    facts_consumed: int = 0
    sources: dict[str, int] = Field(default_factory=dict)
    fl_vs_doc: dict[str, int] = Field(default_factory=dict)
    bypassed_count: int = 0
    turn_duration_ms: int | None = None
    tool_duration_ms: int | None = None
    reasoning_duration_ms: int | None = None


class EvalTrace(BaseModel):
    session_id: str
    turn: int
    timestamp: str
    # Which tool/harness produced this turn (claude-code / codex / unknown).
    # This is the FL-019 "变化的轴" — orthogonal to EvalStep.source (fl/doc/…),
    # which classifies the *retrieval origin* within a turn.
    harness: str = "unknown"
    steps: list[EvalStep]
    summary: EvalSummary = Field(default_factory=EvalSummary)


class BypassDetail(BaseModel):
    rule: str
    count: int
    reasons: list[str]


class SlotHit(BaseModel):
    slot_ref: str
    count: int


class TimingStats(BaseModel):
    avg_turn_ms: float
    avg_fl_query_ms: float | None = None
    avg_doc_read_ms: float | None = None
    avg_db_query_ms: float | None = None


class EvalStats(BaseModel):
    total_turns: int
    total_steps: int
    sources: dict[str, int]
    fl_vs_doc: dict[str, int]
    fl_ratio: float | None = None
    bypassed: list[BypassDetail]
    slot_hits: list[SlotHit]
    l2_coverage: float
    timing: TimingStats | None = None
    suggested_slots: list[str]
    # FL-019: per-harness turn counts (claude-code / codex / unknown), most-common first.
    harness_breakdown: dict[str, int] = Field(default_factory=dict)


class AccessStats(BaseModel):
    """FL-019 L1 backbone: aggregate of the tool-agnostic access log.

    Derived purely from .facts/eval/access.jsonl (FL self-logging on read paths).
    Independent of transcript-based EvalStats — no LLM, no hook, no transcript needed.
    """

    total: int
    by_caller: dict[str, int] = Field(default_factory=dict)  # harness: codex/claude-code/…
    by_op: dict[str, int] = Field(default_factory=dict)  # get/list/check/export
    by_via: dict[str, int] = Field(default_factory=dict)  # interface: cli/mcp
    top_slots: list[SlotHit] = Field(default_factory=list)
    first_ts: str | None = None
    last_ts: str | None = None
