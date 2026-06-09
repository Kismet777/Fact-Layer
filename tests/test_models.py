from datetime import date

from fact_layer.models import (
    CategoryFile,
    DependencyGraph,
    DependencyRule,
    DependencyTarget,
    FrameworkConfig,
    SlotMeta,
    SlotValue,
)


class TestSlotMeta:
    def test_defaults(self):
        meta = SlotMeta()
        assert meta.source == "human"
        assert meta.confidence == "high"
        assert meta.status == "active"
        assert meta.reason is None

    def test_full(self):
        meta = SlotMeta(
            source="agent-analysis",
            confidence="medium",
            status="uncertain",
            updated=date(2026, 6, 7),
            verified=date(2026, 6, 7),
            reason="Inferred from pyproject.toml",
        )
        assert meta.source == "agent-analysis"
        assert meta.reason == "Inferred from pyproject.toml"


class TestSlotValue:
    def test_string_value(self):
        sv = SlotValue(value="PostgreSQL 16")
        assert sv.value == "PostgreSQL 16"
        assert sv.meta.source == "human"

    def test_list_value(self):
        sv = SlotValue(value=["pydantic", "typer", "rich"])
        assert len(sv.value) == 3

    def test_with_explicit_meta(self):
        sv = SlotValue(
            value="FastAPI",
            meta=SlotMeta(
                source="code-extracted",
                confidence="low",
                status="stale",
                updated=date(2026, 1, 1),
                verified=date(2026, 1, 1),
            ),
        )
        assert sv.meta.confidence == "low"
        assert sv.meta.status == "stale"


class TestCategoryFile:
    def test_minimal(self):
        cat = CategoryFile(category="tech-stack", tier="stable")
        assert cat.category == "tech-stack"
        assert cat.tier == "stable"
        assert cat.slots == {}

    def test_with_slots(self):
        cat = CategoryFile(
            category="tech-stack",
            tier="stable",
            slots={
                "language": SlotValue(value="Python 3.12"),
                "database": SlotValue(
                    value="PostgreSQL 16",
                    meta=SlotMeta(reason="JSONB support"),
                ),
            },
        )
        assert cat.slots["language"].value == "Python 3.12"
        assert cat.slots["database"].meta.reason == "JSONB support"

    def test_from_dict(self):
        data = {
            "category": "project-overview",
            "tier": "stable",
            "slots": {
                "name": {
                    "value": "my-app",
                    "meta": {
                        "source": "human",
                        "confidence": "high",
                        "status": "active",
                        "updated": "2026-06-07",
                        "verified": "2026-06-07",
                    },
                },
            },
        }
        cat = CategoryFile.model_validate(data)
        assert cat.slots["name"].value == "my-app"
        assert cat.slots["name"].meta.updated == date(2026, 6, 7)


class TestFrameworkConfig:
    def test_minimal(self):
        config = FrameworkConfig()
        assert config.version == 1
        assert config.tiers == {}

    def test_from_dict(self):
        data = {
            "version": 1,
            "project_name": "test",
            "tiers": {
                "stable": {
                    "description": "Low-frequency changes",
                    "stale_threshold_days": 90,
                },
            },
            "core": {
                "tech-stack": {
                    "file": "tech-stack.yaml",
                    "tier": "stable",
                    "required_slots": ["language"],
                },
            },
            "extensions": {"enabled": [], "available": {}},
            "optional": {"enabled": [], "available": {}},
        }
        config = FrameworkConfig.model_validate(data)
        assert config.tiers["stable"].stale_threshold_days == 90
        assert "tech-stack" in config.core
        assert config.core["tech-stack"].required_slots == ["language"]


class TestDependencyGraph:
    def test_empty(self):
        graph = DependencyGraph()
        assert graph.static == []

    def test_with_rules(self):
        graph = DependencyGraph(
            static=[
                DependencyRule(
                    source="tech-stack.database",
                    targets=[
                        DependencyTarget(
                            slot="data-model.database-type",
                            type="derives-from",
                        ),
                        DependencyTarget(
                            slot="build-deploy.docker",
                            type="constrains",
                        ),
                    ],
                ),
            ]
        )
        assert len(graph.static) == 1
        assert len(graph.static[0].targets) == 2
        assert graph.static[0].targets[0].type == "derives-from"
