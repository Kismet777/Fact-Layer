from datetime import date
from pathlib import Path

import pytest

from fact_layer.core.impact_cmd import compute_impact
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.status_cmd import compute_status
from fact_layer.core.writer import dump_yaml


def _make_slot(value, updated="2026-06-09", verified="2026-06-09", status="active"):
    return {
        "value": value,
        "meta": {
            "source": "human",
            "confidence": "high",
            "status": status,
            "updated": updated,
            "verified": verified,
        },
    }


@pytest.fixture
def facts_dir(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    init_facts_dir(
        target=project,
        project_name="test-project",
        language="Python 3.12",
        enabled_extensions=["data-model", "testing", "build-deploy"],
        enabled_optional=["decisions"],
    )
    facts = project / ".facts"

    dump_yaml(facts / "canonical" / "project-overview.yaml", {
        "category": "project-overview", "tier": "stable",
        "slots": {
            "name": _make_slot("test-project"),
            "purpose": _make_slot("A test"),
            "stage": _make_slot("dev"),
        },
    })
    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {
            "language": _make_slot("Python 3.12"),
            "database": _make_slot("PostgreSQL 16"),
        },
    })
    dump_yaml(facts / "canonical" / "architecture.yaml", {
        "category": "architecture", "tier": "stable",
        "slots": {"style": _make_slot("monolith")},
    })
    dump_yaml(facts / "canonical" / "conventions.yaml", {
        "category": "conventions", "tier": "stable",
        "slots": {"naming": _make_slot("snake_case")},
    })
    dump_yaml(facts / "canonical" / "work-in-progress.yaml", {
        "category": "work-in-progress", "tier": "working",
        "slots": {"focus": _make_slot("MVP")},
    })
    dump_yaml(facts / "canonical" / "data-model.yaml", {
        "category": "data-model", "tier": "dynamic",
        "slots": {"database-type": _make_slot("PostgreSQL")},
    })
    dump_yaml(facts / "canonical" / "testing.yaml", {
        "category": "testing", "tier": "dynamic",
        "slots": {"framework": _make_slot("pytest")},
    })
    dump_yaml(facts / "canonical" / "build-deploy.yaml", {
        "category": "build-deploy", "tier": "dynamic",
        "slots": {"build-tool": _make_slot("hatch")},
    })
    dump_yaml(facts / "canonical" / "decisions.yaml", {
        "category": "decisions", "tier": "working",
        "slots": {
            "dec-001": {
                "value": {
                    "title": "Choose PostgreSQL",
                    "date": "2026-06-07",
                    "status": "active",
                    "affected-slots": ["tech-stack.database", "data-model.database-type"],
                },
                "meta": {
                    "source": "human", "confidence": "high", "status": "active",
                    "updated": "2026-06-07", "verified": "2026-06-07",
                },
            },
        },
    })

    return facts


class TestComputeStatus:
    def test_counts_filled_slots(self, facts_dir):
        st = compute_status(facts_dir, today=date(2026, 6, 9))
        assert st.total_filled > 0
        assert st.total_slots > 0

    def test_no_stale(self, facts_dir):
        st = compute_status(facts_dir, today=date(2026, 6, 9))
        assert st.total_stale == 0

    def test_stale_detected(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "data-model.yaml", {
            "category": "data-model", "tier": "dynamic",
            "slots": {"database-type": _make_slot("PG", verified="2026-04-01")},
        })
        st = compute_status(facts_dir, today=date(2026, 6, 9))
        assert st.total_stale >= 1
        dm = next(c for c in st.categories if c.name == "data-model")
        assert dm.stale_count >= 1

    def test_empty_category(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "testing.yaml", {
            "category": "testing", "tier": "dynamic", "slots": {},
        })
        st = compute_status(facts_dir, today=date(2026, 6, 9))
        testing = next(c for c in st.categories if c.name == "testing")
        assert testing.is_empty

    def test_categories_sorted_by_tier(self, facts_dir):
        st = compute_status(facts_dir, today=date(2026, 6, 9))
        tiers = [c.tier for c in st.categories]
        tier_order = {"stable": 0, "dynamic": 1, "working": 2}
        assert tiers == sorted(tiers, key=lambda t: tier_order.get(t, 99))

    def test_decisions_counted(self, facts_dir):
        st = compute_status(facts_dir, today=date(2026, 6, 9))
        dec = next(c for c in st.categories if c.name == "decisions")
        assert dec.active_decisions == 1


class TestComputeImpact:
    def test_finds_targets(self, facts_dir):
        result = compute_impact(facts_dir, "tech-stack.database")
        assert len(result.targets) > 0
        target_slots = [t.slot for t in result.targets]
        assert "data-model.database-type" in target_slots

    def test_derives_from_is_strong(self, facts_dir):
        result = compute_impact(facts_dir, "tech-stack.database")
        derives = [t for t in result.targets if t.relation_type == "derives-from"]
        assert all(t.is_strong for t in derives)

    def test_constrains_is_not_strong(self, facts_dir):
        result = compute_impact(facts_dir, "tech-stack.language")
        constrains = [t for t in result.targets if t.relation_type == "constrains"]
        assert all(not t.is_strong for t in constrains)

    def test_finds_decision_refs(self, facts_dir):
        result = compute_impact(facts_dir, "tech-stack.database")
        assert len(result.decisions) >= 1
        assert result.decisions[0].decision_id == "DEC-001"

    def test_nonexistent_slot(self, facts_dir):
        result = compute_impact(facts_dir, "tech-stack.nonexistent")
        assert not result.slot_exists

    def test_no_targets_for_leaf_slot(self, facts_dir):
        result = compute_impact(facts_dir, "data-model.database-type")
        assert len(result.targets) == 0

    def test_strong_targets_sorted_first(self, facts_dir):
        result = compute_impact(facts_dir, "tech-stack.database")
        if len(result.targets) > 1:
            strong_indices = [i for i, t in enumerate(result.targets) if t.is_strong]
            weak_indices = [i for i, t in enumerate(result.targets) if not t.is_strong]
            if strong_indices and weak_indices:
                assert max(strong_indices) < min(weak_indices)
