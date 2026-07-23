from pathlib import Path

import pytest

from fact_layer.core.dep_editor import (
    add_dependency,
    list_dependencies,
    remove_dependency,
)
from fact_layer.core.init_cmd import init_facts_dir
from fact_layer.core.loader import load_dependencies
from fact_layer.core.writer import dump_yaml


def _slot(value):
    return {
        "value": value,
        "meta": {
            "source": "human",
            "confidence": "high",
            "status": "active",
            "updated": "2026-06-09",
            "verified": "2026-06-09",
        },
    }


@pytest.fixture
def facts_dir(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    init_facts_dir(
        target=project,
        project_name="t",
        language="Python 3.12",
        enabled_extensions=["data-model", "testing", "build-deploy"],
        enabled_optional=["decisions"],
    )
    facts = project / ".facts"
    dump_yaml(facts / "canonical" / "tech-stack.yaml", {
        "category": "tech-stack", "tier": "stable",
        "slots": {"language": _slot("Python 3.12"), "framework": _slot("FastAPI")},
    })
    dump_yaml(facts / "canonical" / "conventions.yaml", {
        "category": "conventions", "tier": "stable",
        "slots": {"naming": _slot("snake_case")},
    })
    dump_yaml(facts / "canonical" / "architecture.yaml", {
        "category": "architecture", "tier": "stable",
        "slots": {"style": _slot("monolith")},
    })
    # known small graph so tests are deterministic
    dump_yaml(facts / "dependencies.yaml", {
        "static": [
            {"source": "tech-stack.language",
             "targets": [{"slot": "conventions.naming", "type": "constrains"}]},
        ],
    })
    return facts


def _edges(facts_dir):
    graph = load_dependencies(facts_dir)
    return [(r.source, t.slot, t.type) for r in graph.static for t in r.targets]


class TestAdd:
    def test_add_appends_edge_to_existing_source(self, facts_dir):
        add_dependency(facts_dir, "tech-stack.language", "tech-stack.framework", "constrains")
        assert ("tech-stack.language", "tech-stack.framework", "constrains") in _edges(facts_dir)

    def test_add_creates_new_source_rule(self, facts_dir):
        add_dependency(facts_dir, "tech-stack.framework", "architecture.style", "constrains")
        assert ("tech-stack.framework", "architecture.style", "constrains") in _edges(facts_dir)

    def test_add_rejects_invalid_edge_type(self, facts_dir):
        with pytest.raises(ValueError, match="edge type"):
            add_dependency(facts_dir, "tech-stack.language", "conventions.naming", "bogus")

    def test_add_rejects_dangling_target(self, facts_dir):
        with pytest.raises(ValueError, match="does not exist"):
            add_dependency(facts_dir, "tech-stack.language", "conventions.nonexistent", "constrains")

    def test_add_rejects_dangling_source(self, facts_dir):
        with pytest.raises(ValueError, match="does not exist"):
            add_dependency(facts_dir, "tech-stack.nonexistent", "conventions.naming", "constrains")

    def test_add_rejects_duplicate_edge(self, facts_dir):
        add_dependency(facts_dir, "tech-stack.language", "tech-stack.framework", "constrains")
        with pytest.raises(ValueError, match="already exists"):
            add_dependency(facts_dir, "tech-stack.language", "tech-stack.framework", "references")

    def test_add_preserves_comment_header(self, facts_dir):
        # add must roundtrip (ruamel), not plain-dump, so the header survives
        path = facts_dir / "dependencies.yaml"
        path.write_text(
            "# fact-layer dependency graph — do not hand-edit\n"
            "static:\n"
            "  - source: tech-stack.language\n"
            "    targets:\n"
            "      - slot: conventions.naming\n"
            "        type: constrains\n",
            encoding="utf-8",
        )
        add_dependency(facts_dir, "tech-stack.framework", "architecture.style", "constrains")
        text = path.read_text(encoding="utf-8")
        assert "# fact-layer dependency graph — do not hand-edit" in text


class TestRemove:
    def test_remove_deletes_edge(self, facts_dir):
        assert remove_dependency(facts_dir, "tech-stack.language", "conventions.naming") is True
        assert ("tech-stack.language", "conventions.naming", "constrains") not in _edges(facts_dir)

    def test_remove_drops_empty_source_rule(self, facts_dir):
        remove_dependency(facts_dir, "tech-stack.language", "conventions.naming")
        graph = load_dependencies(facts_dir)
        assert all(r.source != "tech-stack.language" for r in graph.static)

    def test_remove_can_remove_dangling_edge(self, facts_dir):
        # a pre-existing dangling edge (endpoint slot missing) must be removable,
        # otherwise B-001's findings could never be fixed via FL.
        dump_yaml(facts_dir / "dependencies.yaml", {
            "static": [
                {"source": "tech-stack.database",
                 "targets": [{"slot": "build-deploy.docker", "type": "constrains"}]},
            ],
        })
        assert remove_dependency(facts_dir, "tech-stack.database", "build-deploy.docker") is True
        assert _edges(facts_dir) == []

    def test_remove_returns_false_when_edge_absent(self, facts_dir):
        assert remove_dependency(facts_dir, "tech-stack.language", "tech-stack.framework") is False

    def test_remove_returns_false_when_source_absent(self, facts_dir):
        assert remove_dependency(facts_dir, "no-such.source", "conventions.naming") is False


class TestList:
    def test_list_returns_edges(self, facts_dir):
        graph = list_dependencies(facts_dir)
        pairs = [(r.source, t.slot) for r in graph.static for t in r.targets]
        assert ("tech-stack.language", "conventions.naming") in pairs
