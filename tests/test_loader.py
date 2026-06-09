import textwrap
from pathlib import Path

import pytest

from fact_layer.core.loader import (
    load_all_categories,
    load_category,
    load_dependencies,
    load_framework,
)
from fact_layer.core.writer import copy_template, dump_yaml


@pytest.fixture
def facts_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".facts"
    d.mkdir()
    (d / "canonical").mkdir()
    return d


@pytest.fixture
def sample_framework(facts_dir: Path) -> Path:
    path = facts_dir / "framework.yaml"
    dump_yaml(
        path,
        {
            "version": 1,
            "project_name": "test-project",
            "tiers": {
                "stable": {
                    "description": "Low-frequency",
                    "stale_threshold_days": 90,
                },
                "dynamic": {
                    "description": "Mid-frequency",
                    "stale_threshold_days": 30,
                },
                "working": {
                    "description": "High-frequency",
                    "stale_threshold_days": 7,
                },
            },
            "core": {
                "tech-stack": {
                    "file": "tech-stack.yaml",
                    "tier": "stable",
                    "required_slots": ["language"],
                },
            },
            "extensions": {
                "enabled": ["data-model"],
                "available": {
                    "data-model": {
                        "file": "data-model.yaml",
                        "tier": "dynamic",
                        "required_slots": ["database-type"],
                    },
                },
            },
            "optional": {
                "enabled": ["decisions"],
                "available": {
                    "decisions": {
                        "file": "decisions.yaml",
                        "tier": "working",
                        "required_slots": [],
                    },
                },
            },
        },
    )
    return path


@pytest.fixture
def sample_deps(facts_dir: Path) -> Path:
    path = facts_dir / "dependencies.yaml"
    dump_yaml(
        path,
        {
            "static": [
                {
                    "source": "tech-stack.database",
                    "targets": [
                        {"slot": "data-model.database-type", "type": "derives-from"},
                    ],
                },
            ],
        },
    )
    return path


@pytest.fixture
def sample_category(facts_dir: Path) -> Path:
    path = facts_dir / "canonical" / "tech-stack.yaml"
    dump_yaml(
        path,
        {
            "category": "tech-stack",
            "tier": "stable",
            "slots": {
                "language": {
                    "value": "Python 3.12",
                    "meta": {
                        "source": "human",
                        "confidence": "high",
                        "status": "active",
                        "updated": "2026-06-07",
                        "verified": "2026-06-07",
                    },
                },
                "database": {
                    "value": "PostgreSQL 16",
                    "meta": {
                        "source": "human",
                        "confidence": "high",
                        "status": "active",
                        "updated": "2026-06-07",
                        "verified": "2026-06-07",
                        "reason": "Need JSONB and CTE",
                    },
                },
            },
        },
    )
    return path


class TestLoadFramework:
    def test_loads_correctly(self, facts_dir, sample_framework):
        config = load_framework(facts_dir)
        assert config.version == 1
        assert config.project_name == "test-project"
        assert config.tiers["stable"].stale_threshold_days == 90
        assert "tech-stack" in config.core

    def test_missing_file(self, facts_dir):
        with pytest.raises(FileNotFoundError):
            load_framework(facts_dir)


class TestLoadDependencies:
    def test_loads_correctly(self, facts_dir, sample_deps):
        graph = load_dependencies(facts_dir)
        assert len(graph.static) == 1
        assert graph.static[0].source == "tech-stack.database"


class TestLoadCategory:
    def test_loads_correctly(self, sample_category):
        cat = load_category(sample_category)
        assert cat.category == "tech-stack"
        assert cat.tier == "stable"
        assert cat.slots["language"].value == "Python 3.12"
        assert cat.slots["database"].meta.reason == "Need JSONB and CTE"


class TestLoadAllCategories:
    def test_loads_all(self, facts_dir, sample_category):
        cats = load_all_categories(facts_dir)
        assert "tech-stack" in cats
        assert cats["tech-stack"].slots["language"].value == "Python 3.12"

    def test_empty_canonical(self, facts_dir):
        cats = load_all_categories(facts_dir)
        assert cats == {}


class TestWriter:
    def test_dump_and_reload(self, tmp_path):
        path = tmp_path / "test.yaml"
        dump_yaml(path, {"key": "value", "nested": {"a": 1}})
        cat_data = {
            "category": "test",
            "tier": "stable",
            "slots": {},
        }
        dump_yaml(path, cat_data)
        from fact_layer.core.loader import load_category

        cat = load_category(path)
        assert cat.category == "test"

    def test_copy_template(self, tmp_path):
        src = tmp_path / "src.yaml"
        dump_yaml(src, {"category": "test", "tier": "stable", "slots": {}})
        dst = tmp_path / "sub" / "dst.yaml"
        copy_template(src, dst)
        assert dst.exists()
        cat = load_category(dst)
        assert cat.category == "test"
