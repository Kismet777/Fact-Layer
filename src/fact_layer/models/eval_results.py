"""Result-layer (eval-L3) data model — S0.

Separate from ``models/eval.py`` (the L1/L2 trace model) on purpose: this file
holds only the *result* layer's shapes — the T2 observation of whether a FL read
was correctly adopted (A/B/C), plus the aggregate report.

A/B/C semantics (authoritative, from the design doc §2):
- **A** consumed & useful: queried FL, got the fact, used it directly. (the only positive)
- **B** consumed but wasted: queried FL → didn't get / didn't trust → re-fetched the
  same info from bash/source. (negative: count +1 but the detour was wasted)
- **C** self-maintenance: read FL in order to *write* FL (pre-edit slot existence/type
  check, coverage audit, export-as-background). (orthogonal to knowledge-supply
  effectiveness; broken out and excluded from the adoption rate)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# The four verdicts a single FL read can receive. "unknown" is the graceful
# degradation value when the LLM backend fails — never a positive/negative signal.
ABCVerdict = Literal["A", "B", "C", "unknown"]


def make_event_id(session_id: str, turn: int, step_index: int) -> str:
    """Stable, readable, idempotent key for one FL-read event.

    ``{session}:{turn:03d}:{step_index}`` — 3-digit turn keeps lexical order
    aligned with the trace filenames (``…turn-003.yaml``).
    """
    return f"{session_id}:{turn:03d}:{step_index}"


class EvidenceBundle(BaseModel):
    """One FL-read event + the surrounding evidence a judge needs to rate it.

    Built by a pure extractor (no IO, no LLM) so the extraction boundary is
    testable in isolation — the decisive signal for A/B/C is often a single
    reasoning sentence *adjacent* to the read step, so ``reasoning_span`` must
    carry the neighbours, not just the read step's own fields (spec red-line 2).
    """

    event_id: str
    session_id: str
    turn: int
    step_index: int
    slot_ref: str | None = None  # facts_get/list: slot|category; search/export: None
    tool: str  # facts_get / facts_list / facts_search / facts_export
    query: dict[str, Any] = Field(default_factory=dict)  # the read step's args
    # Locked None this pass (choice 1): judgement rides on reasoning_span +
    # downstream_actions, not the FL return value. Field kept for a later upgrade.
    fl_return: None = None
    reasoning_span: list[str] = Field(default_factory=list)
    downstream_actions: list[dict] = Field(default_factory=list)
    trace_ref: str = ""  # source trace filename, for provenance


class ABCJudgement(BaseModel):
    """A single LLM verdict on one EvidenceBundle. Append-only, keyed by event_id."""

    event_id: str
    verdict: ABCVerdict
    rationale: str = ""  # why this verdict (the judge's own words)
    confidence: float | None = None
    judged_at: str = ""
    judge_model: str | None = None


class T2Report(BaseModel):
    """Aggregate of T2 judgements.

    ``adoption_rate = A / (A + B)`` — C and unknown are both excluded from the
    ratio (C is self-maintenance, unknown is a degraded judgement). ``c_rate`` is
    reported separately as a reference, never folded into the adoption rate.
    """

    total_reads: int  # FL-read events extracted
    judged: int  # judgements produced
    coverage: float  # judged / total_reads
    by_verdict: dict[str, int] = Field(default_factory=dict)  # {A,B,C,unknown}
    adoption_rate: float | None = None  # A / (A+B); None when denominator is 0
    c_rate: float | None = None  # C / judged; None when judged is 0
    by_slot: dict[str, dict[str, int]] = Field(default_factory=dict)
    sampled: bool = False
    sample_size: int | None = None