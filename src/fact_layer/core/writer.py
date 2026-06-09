from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.default_flow_style = False


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        _yaml.dump(data, f)


def copy_template(template_path: Path, target_path: Path) -> None:
    """Copy a YAML template file preserving comments and formatting."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with template_path.open("r", encoding="utf-8") as src:
        data = _yaml.load(src)
    with target_path.open("w", encoding="utf-8") as dst:
        _yaml.dump(data, dst)
