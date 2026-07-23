from datetime import date, timedelta
from pathlib import Path

import pytest

from fact_layer.core.checker import Severity, run_check
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.writer import dump_yaml


def _make_slot(value, updated="2026-06-09", verified="2026-06-09", status="active", reason=None, confidence="high"):
    meta = {
        "source": "human",
        "confidence": confidence,
        "status": status,
        "updated": updated,
        "verified": verified,
    }
    if reason:
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
        enabled_extensions=["data-model", "testing", "build-deploy"],
        enabled_optional=["decisions"],
    )
    facts = project / ".facts"

    dump_yaml(facts / "canonical" / "project-overview.yaml", {
        "category": "project-overview", "tier": "stable",
        "slots": {
            "name": _make_slot("test-project"),
            "purpose": _make_slot("A test project"),
            "stage": _make_slot("active-development"),
        },
    })
    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {
            "language": _make_slot("Python 3.12"),
            "framework": _make_slot("FastAPI 0.111"),
            "database": _make_slot("PostgreSQL 16", updated="2026-06-09"),
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
        "slots": {"focus": _make_slot("Building MVP")},
    })
    dump_yaml(facts / "canonical" / "data-model.yaml", {
        "category": "data-model", "tier": "dynamic",
        "slots": {"database-type": _make_slot("PostgreSQL 16")},
    })
    dump_yaml(facts / "canonical" / "testing.yaml", {
        "category": "testing", "tier": "dynamic",
        "slots": {"framework": _make_slot("pytest")},
    })
    dump_yaml(facts / "canonical" / "build-deploy.yaml", {
        "category": "build-deploy", "tier": "dynamic",
        "slots": {"build-tool": _make_slot("hatch"), "docker": _make_slot("python:3.12-slim")},
    })
    dump_yaml(facts / "canonical" / "decisions.yaml", {
        "category": "decisions", "tier": "working",
        "slots": {},
    })

    return facts


class TestCleanProject:
    def test_no_issues(self, facts_dir):
        result = run_check(facts_dir, today=date(2026, 6, 9))
        issues = [i for i in result.issues if i.check_type != "structural" or "empty" not in i.message]
        structural_empty = [i for i in result.issues if "empty" in i.message]
        assert not result.has_errors or all(
            "decisions" in i.message for i in result.errors
        )


class TestStructuralChecks:
    def test_missing_required_slot(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "tech-stack.yaml", {
            "category": "tech-stack", "tier": "stable",
            "slots": {"database": _make_slot("PostgreSQL 16")},
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        req_issues = [i for i in result.issues if "required" in i.message and "language" in i.message]
        assert len(req_issues) == 1
        assert req_issues[0].severity == Severity.ERROR

    def test_empty_required_slot(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "tech-stack.yaml", {
            "category": "tech-stack", "tier": "stable",
            "slots": {
                "language": _make_slot(""),
                "database": _make_slot("PostgreSQL 16"),
            },
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        req_issues = [i for i in result.issues if "required" in i.message and "language" in i.message]
        assert len(req_issues) == 1

    def test_empty_category(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "testing.yaml", {
            "category": "testing", "tier": "dynamic",
            "slots": {},
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        empty_issues = [i for i in result.issues if "testing" in i.message and "empty" in i.message]
        assert len(empty_issues) == 1
        assert empty_issues[0].severity == Severity.ERROR


class TestStalenessChecks:
    def test_stale_dynamic_slot(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "data-model.yaml", {
            "category": "data-model", "tier": "dynamic",
            "slots": {
                "database-type": _make_slot("PostgreSQL 16", verified="2026-05-01"),
            },
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        stale = [i for i in result.issues if i.check_type == "staleness" and "database-type" in i.message]
        assert len(stale) == 1
        assert stale[0].severity == Severity.WARNING

    def test_not_stale_within_threshold(self, facts_dir):
        result = run_check(facts_dir, today=date(2026, 6, 9))
        stale = [i for i in result.issues if i.check_type == "staleness"]
        assert len(stale) == 0

    def test_stale_working_slot(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "work-in-progress.yaml", {
            "category": "work-in-progress", "tier": "working",
            "slots": {"focus": _make_slot("old task", verified="2026-05-25")},
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        stale = [i for i in result.issues if i.check_type == "staleness" and "focus" in i.message]
        assert len(stale) == 1


class TestDependencyChecks:
    def test_derives_from_outdated(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "tech-stack.yaml", {
            "category": "tech-stack", "tier": "stable",
            "slots": {
                "language": _make_slot("Python 3.12"),
                "database": _make_slot("PostgreSQL 16", updated="2026-06-09"),
            },
        })
        dump_yaml(facts_dir / "canonical" / "data-model.yaml", {
            "category": "data-model", "tier": "dynamic",
            "slots": {
                "database-type": _make_slot("MySQL 8", updated="2026-05-01"),
            },
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        dep_issues = [i for i in result.issues if i.check_type == "dependency"]
        assert len(dep_issues) >= 1
        derives = [i for i in dep_issues if i.detail and "derives-from" in i.detail]
        assert len(derives) >= 1
        assert derives[0].severity == Severity.ERROR

    def test_constrains_outdated_is_warning(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "tech-stack.yaml", {
            "category": "tech-stack", "tier": "stable",
            "slots": {
                "language": _make_slot("Python 3.12", updated="2026-06-09"),
            },
        })
        dump_yaml(facts_dir / "canonical" / "build-deploy.yaml", {
            "category": "build-deploy", "tier": "dynamic",
            "slots": {
                "build-tool": _make_slot("hatch", updated="2026-05-01"),
            },
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        constrains = [
            i for i in result.issues
            if i.check_type == "dependency" and i.detail and "constrains" in i.detail
        ]
        assert len(constrains) >= 1
        assert constrains[0].severity == Severity.WARNING

    def test_no_dep_issues_when_up_to_date(self, facts_dir):
        result = run_check(facts_dir, today=date(2026, 6, 9))
        dep_issues = [i for i in result.issues if i.check_type == "dependency"]
        assert len(dep_issues) == 0


class TestDependencyIntegrity:
    """B-001: dangling dependency edges (endpoint slot does not exist) must be
    caught deterministically by fl check, not silently skipped."""

    def test_clean_fixture_has_no_integrity_issues(self, facts_dir):
        result = run_check(facts_dir, today=date(2026, 6, 9))
        integrity = [i for i in result.issues if i.check_type == "dependency-integrity"]
        assert integrity == []

    def test_dangling_target_slot_is_error(self, facts_dir):
        # drop build-deploy.docker -> edge tech-stack.database -> build-deploy.docker dangles at target
        dump_yaml(facts_dir / "canonical" / "build-deploy.yaml", {
            "category": "build-deploy", "tier": "dynamic",
            "slots": {"build-tool": _make_slot("hatch")},
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        dangling = [
            i for i in result.issues
            if i.check_type == "dependency-integrity" and "build-deploy.docker" in i.message
        ]
        assert len(dangling) == 1
        assert dangling[0].severity == Severity.ERROR

    def test_dangling_source_slot_is_error(self, facts_dir):
        # drop tech-stack.framework -> edge tech-stack.framework -> ... dangles at source
        dump_yaml(facts_dir / "canonical" / "tech-stack.yaml", {
            "category": "tech-stack", "tier": "stable",
            "slots": {
                "language": _make_slot("Python 3.12"),
                "database": _make_slot("PostgreSQL 16"),
            },
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        dangling = [
            i for i in result.issues
            if i.check_type == "dependency-integrity" and "tech-stack.framework" in i.message
        ]
        assert len(dangling) == 1
        assert dangling[0].severity == Severity.ERROR

    def test_edge_to_disabled_category_not_flagged(self, facts_dir):
        # template deps reference api-contracts.style, but api-contracts is not enabled
        # here -> dormant edge, must NOT be reported as dangling.
        result = run_check(facts_dir, today=date(2026, 6, 9))
        api = [
            i for i in result.issues
            if i.check_type == "dependency-integrity" and "api-contracts" in i.message
        ]
        assert api == []


class TestSlotDuplicates:
    """B-003: two active slot ids in one category that differ only by case or
    '-'/'_' are near-certainly the same fact duplicated (the Bug B residue) —
    flag them so one can be consolidated."""

    def test_hyphen_underscore_variant_flagged(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "build-deploy.yaml", {
            "category": "build-deploy", "tier": "dynamic",
            "slots": {
                "package-manager": _make_slot(""),
                "package_manager": _make_slot("hatch"),
            },
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        dups = [i for i in result.issues if i.check_type == "slot-duplicate"]
        assert len(dups) == 1
        assert dups[0].severity == Severity.WARNING
        assert "package-manager" in dups[0].message
        assert "package_manager" in dups[0].message

    def test_distinct_slots_not_flagged(self, facts_dir):
        # framework vs cli_framework are genuinely different ids (not separator
        # variants) — a deterministic check must NOT flag them (that's audit's job).
        dump_yaml(facts_dir / "canonical" / "tech-stack.yaml", {
            "category": "tech-stack", "tier": "stable",
            "slots": {
                "language": _make_slot("Python"),
                "framework": _make_slot(""),
                "cli_framework": _make_slot("typer"),
                "database": _make_slot("PG"),
            },
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        dups = [i for i in result.issues if i.check_type == "slot-duplicate"]
        assert dups == []

    def test_deprecated_variant_not_flagged(self, facts_dir):
        # once the empty variant is deprecated, the duplicate is resolved -> no warning
        dump_yaml(facts_dir / "canonical" / "build-deploy.yaml", {
            "category": "build-deploy", "tier": "dynamic",
            "slots": {
                "package-manager": _make_slot("", status="superseded"),
                "package_manager": _make_slot("hatch"),
            },
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        dups = [i for i in result.issues if i.check_type == "slot-duplicate"]
        assert dups == []

    def test_clean_fixture_no_slot_duplicates(self, facts_dir):
        result = run_check(facts_dir, today=date(2026, 6, 9))
        dups = [i for i in result.issues if i.check_type == "slot-duplicate"]
        assert dups == []


class TestDecisionChecks:
    def test_decision_affects_outdated_slot(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "decisions.yaml", {
            "category": "decisions", "tier": "working",
            "slots": {
                "dec-001": {
                    "value": {
                        "title": "Switch to PostgreSQL",
                        "date": "2026-06-08",
                        "status": "active",
                        "affected-slots": ["data-model.database-type"],
                    },
                    "meta": {
                        "source": "human",
                        "confidence": "high",
                        "status": "active",
                        "updated": "2026-06-08",
                        "verified": "2026-06-08",
                    },
                },
            },
        })
        dump_yaml(facts_dir / "canonical" / "data-model.yaml", {
            "category": "data-model", "tier": "dynamic",
            "slots": {
                "database-type": _make_slot("MySQL 8", updated="2026-06-01"),
            },
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        dec_issues = [i for i in result.issues if i.check_type == "decisions"]
        assert len(dec_issues) >= 1
        assert dec_issues[0].severity == Severity.WARNING

    def test_no_decision_issue_when_slot_updated(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "decisions.yaml", {
            "category": "decisions", "tier": "working",
            "slots": {
                "dec-001": {
                    "value": {
                        "title": "Switch to PostgreSQL",
                        "date": "2026-06-07",
                        "status": "active",
                        "affected-slots": ["tech-stack.database"],
                    },
                    "meta": {
                        "source": "human",
                        "confidence": "high",
                        "status": "active",
                        "updated": "2026-06-07",
                        "verified": "2026-06-07",
                    },
                },
            },
        })
        result = run_check(facts_dir, today=date(2026, 6, 9))
        dec_issues = [i for i in result.issues if i.check_type == "decisions"]
        assert len(dec_issues) == 0


class TestFilterCategory:
    def test_filter_only_tech_stack(self, facts_dir):
        dump_yaml(facts_dir / "canonical" / "testing.yaml", {
            "category": "testing", "tier": "dynamic",
            "slots": {},
        })
        result = run_check(facts_dir, filter_category="tech-stack", today=date(2026, 6, 9))
        for issue in result.issues:
            assert issue.category_name == "tech-stack"
