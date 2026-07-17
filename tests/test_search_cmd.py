from pathlib import Path

import pytest

from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.search_cmd import compute_search
from fact_layer.core.writer import dump_yaml


def _make_slot(value, updated="2026-06-09", verified="2026-06-09", status="active", reason=None):
    meta = {
        "source": "human",
        "confidence": "high",
        "status": status,
        "updated": updated,
        "verified": verified,
    }
    if reason is not None:
        meta["reason"] = reason
    return {"value": value, "meta": meta}


@pytest.fixture
def facts_dir(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    init_facts_dir(
        target=project,
        project_name="test-project",
        language="Python 3.12",
        enabled_extensions=["data-model"],
        enabled_optional=["decisions"],
    )
    facts = project / ".facts"

    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {
            "language": _make_slot("Python 3.12", reason="team standard"),
            "database": _make_slot("PostgreSQL 16"),
        },
    })
    dump_yaml(facts / "canonical" / "data-model.yaml", {
        "category": "data-model", "tier": "dynamic",
        "slots": {
            # value carries the searched term, slot-id does not
            "enum-situation": _make_slot(["1=normal", "2=overdue", "3=settled"]),
            # a superseded (non-active) slot, only surfaced with include_stale
            "legacy-status": _make_slot("old mapping", status="superseded"),
        },
    })
    dump_yaml(facts / "canonical" / "decisions.yaml", {
        "category": "decisions", "tier": "working",
        "slots": {
            "dec-001": {
                "value": {
                    "title": "Choose PostgreSQL",
                    "rationale": "mature ecosystem",
                    "status": "active",
                    "affected-slots": ["tech-stack.database"],
                },
                "meta": {
                    "source": "human", "confidence": "high", "status": "active",
                    "updated": "2026-06-07", "verified": "2026-06-07",
                },
            },
        },
    })
    return facts


class TestCompuseSearchMatching:
    def test_finds_by_slot_id_substring(self, facts_dir):
        r = compute_search(facts_dir, "database")
        refs = [h.slot_ref for h in r.hits]
        assert "tech-stack.database" in refs

    def test_case_insensitive(self, facts_dir):
        r = compute_search(facts_dir, "DATABASE")
        assert "tech-stack.database" in [h.slot_ref for h in r.hits]

    def test_finds_by_value_content(self, facts_dir):
        # "overdue" lives only in the value of data-model.enum-situation
        r = compute_search(facts_dir, "overdue")
        assert "data-model.enum-situation" in [h.slot_ref for h in r.hits]

    def test_finds_by_reason(self, facts_dir):
        r = compute_search(facts_dir, "team standard")
        assert "tech-stack.language" in [h.slot_ref for h in r.hits]

    def test_multi_token_and(self, facts_dir):
        # both tokens present across joined text of tech-stack.language
        r = compute_search(facts_dir, "python team")
        assert "tech-stack.language" in [h.slot_ref for h in r.hits]

    def test_multi_token_and_excludes_partial(self, facts_dir):
        # "python" matches language, "banana" matches nothing → AND fails
        r = compute_search(facts_dir, "python banana")
        assert "tech-stack.language" not in [h.slot_ref for h in r.hits]

    def test_empty_query_returns_no_hits(self, facts_dir):
        assert compute_search(facts_dir, "").hits == []
        assert compute_search(facts_dir, "   ").hits == []

    def test_no_match_returns_empty(self, facts_dir):
        assert compute_search(facts_dir, "zzz-nonexistent-zzz").hits == []


class TestSearchDecisionFlattening:
    def test_decision_searchable_by_title(self, facts_dir):
        # title/rationale/affected-slots fall out of value flattening, no special-casing
        r = compute_search(facts_dir, "mature ecosystem")
        assert "decisions.dec-001" in [h.slot_ref for h in r.hits]

    def test_decision_searchable_by_affected_slot(self, facts_dir):
        r = compute_search(facts_dir, "affected-slots")
        assert "decisions.dec-001" in [h.slot_ref for h in r.hits]


class TestSearchStatusScope:
    def test_default_excludes_stale(self, facts_dir):
        r = compute_search(facts_dir, "old mapping")
        assert "data-model.legacy-status" not in [h.slot_ref for h in r.hits]

    def test_include_stale_surfaces_superseded(self, facts_dir):
        r = compute_search(facts_dir, "old mapping", include_stale=True)
        hit = next((h for h in r.hits if h.slot_ref == "data-model.legacy-status"), None)
        assert hit is not None
        assert hit.status == "superseded"

    def test_status_shown_on_every_hit(self, facts_dir):
        r = compute_search(facts_dir, "database")
        assert all(h.status for h in r.hits)


class TestSearchFilterAndShape:
    def test_category_filter(self, facts_dir):
        r = compute_search(facts_dir, "e", category="tech-stack")
        assert all(h.category == "tech-stack" for h in r.hits)

    def test_limit_caps_and_flags_truncated(self, facts_dir):
        r = compute_search(facts_dir, "e", limit=1)
        assert len(r.hits) <= 1
        assert r.truncated is True

    def test_hit_carries_full_value(self, facts_dir):
        r = compute_search(facts_dir, "database")
        hit = next(h for h in r.hits if h.slot_ref == "tech-stack.database")
        assert "PostgreSQL 16" in hit.value

    def test_matched_fields_reports_slot_id(self, facts_dir):
        r = compute_search(facts_dir, "database")
        hit = next(h for h in r.hits if h.slot_ref == "tech-stack.database")
        assert "slot-id" in hit.matched_fields

    def test_matched_fields_reports_value(self, facts_dir):
        r = compute_search(facts_dir, "overdue")
        hit = next(h for h in r.hits if h.slot_ref == "data-model.enum-situation")
        assert "value" in hit.matched_fields


class TestSearchRanking:
    def test_slot_id_match_ranked_before_value_match(self, facts_dir):
        # "status" appears in slot-id data-model.legacy-status (with include_stale)
        # and in decision value ("status": "active"). slot-id hit should rank first.
        r = compute_search(facts_dir, "status", include_stale=True)
        refs = [h.slot_ref for h in r.hits]
        assert "data-model.legacy-status" in refs
        assert refs.index("data-model.legacy-status") < refs.index("decisions.dec-001")
