from pathlib import Path

import pytest

from fact_layer.core.init_cmd import (
    CORE_CATEGORIES,
    EXTENSION_CATEGORIES,
    OPTIONAL_CATEGORIES,
    init_facts_dir,
)
from fact_layer.core.loader import load_category, load_dependencies, load_framework
from fact_layer.core.registry import get_enabled_categories


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    return tmp_path / "my-project"


def _run_init(
    project_dir: Path,
    extensions: list[str] | None = None,
    optional: list[str] | None = None,
) -> list[str]:
    project_dir.mkdir(parents=True, exist_ok=True)
    return init_facts_dir(
        target=project_dir,
        project_name="test-project",
        language="Python 3.12",
        enabled_extensions=extensions if extensions is not None else [],
        enabled_optional=optional if optional is not None else ["decisions"],
    )


class TestInitBasic:
    def test_creates_facts_dir(self, project_dir):
        _run_init(project_dir)
        assert (project_dir / ".facts").is_dir()
        assert (project_dir / ".facts" / "canonical").is_dir()

    def test_creates_framework_yaml(self, project_dir):
        _run_init(project_dir)
        config = load_framework(project_dir / ".facts")
        assert config.project_name == "test-project"
        assert config.version == 1
        assert "stable" in config.tiers
        assert "dynamic" in config.tiers
        assert "working" in config.tiers

    def test_creates_dependencies_yaml(self, project_dir):
        _run_init(project_dir)
        graph = load_dependencies(project_dir / ".facts")
        assert isinstance(graph.static, list)

    def test_core_categories_always_created(self, project_dir):
        created = _run_init(project_dir)
        for cat in CORE_CATEGORIES:
            assert cat in created
            assert (project_dir / ".facts" / "canonical" / f"{cat}.yaml").exists()

    def test_returns_created_categories(self, project_dir):
        created = _run_init(project_dir, extensions=["data-model", "testing"])
        assert "project-overview" in created
        assert "data-model" in created
        assert "testing" in created
        assert "security" not in created


class TestInitExtensions:
    def test_no_extensions(self, project_dir):
        created = _run_init(project_dir, extensions=[], optional=[])
        assert len(created) == len(CORE_CATEGORIES)
        for ext in EXTENSION_CATEGORIES:
            assert not (project_dir / ".facts" / "canonical" / f"{ext}.yaml").exists()

    def test_selected_extensions(self, project_dir):
        created = _run_init(project_dir, extensions=["data-model", "api-contracts"])
        assert "data-model" in created
        assert "api-contracts" in created
        assert "testing" not in created

    def test_all_extensions(self, project_dir):
        all_ext = list(EXTENSION_CATEGORIES.keys())
        created = _run_init(project_dir, extensions=all_ext)
        for ext in all_ext:
            assert ext in created

    def test_optional_decisions(self, project_dir):
        created = _run_init(project_dir, optional=["decisions"])
        assert "decisions" in created
        assert (project_dir / ".facts" / "canonical" / "decisions.yaml").exists()

    def test_no_optional(self, project_dir):
        created = _run_init(project_dir, optional=[])
        assert "decisions" not in created


class TestInitFrameworkReflectsChoices:
    def test_extensions_recorded(self, project_dir):
        _run_init(project_dir, extensions=["testing", "security"])
        config = load_framework(project_dir / ".facts")
        assert set(config.extensions.enabled) == {"testing", "security"}

    def test_optional_recorded(self, project_dir):
        _run_init(project_dir, optional=["decisions"])
        config = load_framework(project_dir / ".facts")
        assert "decisions" in config.optional.enabled

    def test_enabled_categories_correct(self, project_dir):
        _run_init(project_dir, extensions=["data-model"], optional=["decisions"])
        config = load_framework(project_dir / ".facts")
        enabled = get_enabled_categories(config)
        assert "project-overview" in enabled
        assert "data-model" in enabled
        assert "decisions" in enabled
        assert "security" not in enabled


class TestInitDependencyFiltering:
    def test_deps_only_for_enabled(self, project_dir):
        _run_init(project_dir, extensions=[], optional=[])
        graph = load_dependencies(project_dir / ".facts")
        enabled = set(CORE_CATEGORIES)
        for rule in graph.static:
            source_cat = rule.source.split(".")[0]
            assert source_cat in enabled
            for target in rule.targets:
                target_cat = target.slot.split(".")[0]
                assert target_cat in enabled

    def test_deps_include_extensions(self, project_dir):
        _run_init(project_dir, extensions=["data-model", "build-deploy"])
        graph = load_dependencies(project_dir / ".facts")
        target_cats = set()
        for rule in graph.static:
            for t in rule.targets:
                target_cats.add(t.slot.split(".")[0])
        assert "data-model" in target_cats or "build-deploy" in target_cats


class TestInitPreFill:
    def test_project_name_filled(self, project_dir):
        _run_init(project_dir)
        cat = load_category(project_dir / ".facts" / "canonical" / "project-overview.yaml")
        assert cat.slots["name"].value == "test-project"

    def test_language_filled(self, project_dir):
        _run_init(project_dir)
        cat = load_category(project_dir / ".facts" / "canonical" / "tech-stack.yaml")
        assert cat.slots["language"].value == "Python 3.12"


class TestInitCanonicalParseable:
    def test_all_canonical_files_parseable(self, project_dir):
        all_ext = list(EXTENSION_CATEGORIES.keys())
        all_opt = list(OPTIONAL_CATEGORIES.keys())
        _run_init(project_dir, extensions=all_ext, optional=all_opt)
        canonical_dir = project_dir / ".facts" / "canonical"
        for f in canonical_dir.glob("*.yaml"):
            cat = load_category(f)
            assert cat.category != ""
            assert cat.tier in ("stable", "dynamic", "working")
