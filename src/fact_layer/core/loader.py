from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel
from ruamel.yaml import YAML

from fact_layer.models.category import CategoryFile
from fact_layer.models.dependency import DependencyGraph
from fact_layer.models.framework import FrameworkConfig

T = TypeVar("T", bound=BaseModel)

_yaml = YAML()
_yaml.preserve_quotes = True


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = _yaml.load(f)
    return dict(data) if data else {}


def load_model(path: Path, model_class: type[T]) -> T:
    return model_class.model_validate(_load_yaml(path))


def load_framework(facts_dir: Path) -> FrameworkConfig:
    return load_model(facts_dir / "framework.yaml", FrameworkConfig)


def load_dependencies(facts_dir: Path) -> DependencyGraph:
    return load_model(facts_dir / "dependencies.yaml", DependencyGraph)


def load_category(path: Path) -> CategoryFile:
    return load_model(path, CategoryFile)


def load_all_categories(facts_dir: Path) -> dict[str, CategoryFile]:
    canonical_dir = facts_dir / "canonical"
    if not canonical_dir.is_dir():
        return {}
    result: dict[str, CategoryFile] = {}
    for f in sorted(canonical_dir.glob("*.yaml")):
        cat = load_category(f)
        result[cat.category] = cat
    return result
