"""S0 — result-layer data model + verdict storage / idempotent cache.

Covers the S0 acceptance bar of the eval-L3 spec:
- model can express A/B/C+unknown and the adoption-rate cadence;
- event_id is stable + readable;
- writing the same event_id twice reads back idempotently (one row, latest wins);
- storage touches nothing on the read hot path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fact_layer.models.eval_results import (
    ABCJudgement,
    EvidenceBundle,
    T2Report,
    make_event_id,
)
from fact_layer.core.eval_t2 import load_verdict_cache, save_verdict


@pytest.fixture
def facts_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".facts"
    d.mkdir()
    return d


class TestEventId:
    def test_stable_and_readable(self):
        assert make_event_id("sess-a", 7, 3) == "sess-a:007:3"

    def test_zero_padded_turn(self):
        # 3-digit turn keeps lexical sort aligned with the trace filenames.
        assert make_event_id("s", 12, 0) == "s:012:0"


class TestModels:
    def test_evidence_bundle_defaults(self):
        b = EvidenceBundle(
            event_id="s:001:0",
            session_id="s",
            turn=1,
            step_index=0,
            tool="facts_get",
        )
        assert b.slot_ref is None
        assert b.fl_return is None
        assert b.reasoning_span == []
        assert b.downstream_actions == []
        assert b.query == {}

    def test_fl_return_is_locked_none(self):
        # Red-line 6: fl_return stays empty this pass (choice 1). Only None is valid.
        with pytest.raises(Exception):
            EvidenceBundle(
                event_id="s:001:0",
                session_id="s",
                turn=1,
                step_index=0,
                tool="facts_get",
                fl_return={"value": "x"},
            )

    def test_judgement_verdict_enum(self):
        for v in ("A", "B", "C", "unknown"):
            j = ABCJudgement(event_id="e", verdict=v)
            assert j.verdict == v

    def test_judgement_rejects_bad_verdict(self):
        with pytest.raises(Exception):
            ABCJudgement(event_id="e", verdict="D")


class TestVerdictStorage:
    def test_save_then_load_roundtrip(self, facts_dir: Path):
        j = ABCJudgement(event_id="s:001:0", verdict="A", rationale="used it")
        save_verdict(facts_dir, j)
        cache = load_verdict_cache(facts_dir)
        assert cache["s:001:0"].verdict == "A"
        assert cache["s:001:0"].rationale == "used it"

    def test_load_empty_when_no_file(self, facts_dir: Path):
        assert load_verdict_cache(facts_dir) == {}

    def test_idempotent_latest_wins(self, facts_dir: Path):
        # append-only store; re-judging an event appends a new row, read-back
        # keeps exactly one entry per event_id (the latest).
        save_verdict(facts_dir, ABCJudgement(event_id="e", verdict="A"))
        save_verdict(facts_dir, ABCJudgement(event_id="e", verdict="B"))
        cache = load_verdict_cache(facts_dir)
        assert list(cache.keys()) == ["e"]
        assert cache["e"].verdict == "B"

    def test_load_skips_corrupt_lines(self, facts_dir: Path):
        save_verdict(facts_dir, ABCJudgement(event_id="ok", verdict="A"))
        path = facts_dir / "eval" / "results" / "t2_verdicts.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write("{not json}\n\n")
        cache = load_verdict_cache(facts_dir)
        assert set(cache.keys()) == {"ok"}

    def test_save_creates_results_dir(self, facts_dir: Path):
        save_verdict(facts_dir, ABCJudgement(event_id="e", verdict="C"))
        assert (facts_dir / "eval" / "results" / "t2_verdicts.jsonl").is_file()


class TestT2ReportModel:
    def test_report_fields(self):
        r = T2Report(
            total_reads=10,
            judged=8,
            coverage=0.8,
            by_verdict={"A": 4, "B": 2, "C": 2, "unknown": 0},
            adoption_rate=4 / 6,
            c_rate=2 / 8,
        )
        assert r.adoption_rate == pytest.approx(2 / 3)
        assert r.c_rate == pytest.approx(0.25)
        assert r.sampled is False
        assert r.sample_size is None