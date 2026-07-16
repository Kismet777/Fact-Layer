"""Guard: vendor LLM model ids may appear ONLY in core/config.py.

Model names are policy and must live in exactly one place (core.config._ROLE_MODELS).
This test fails the build if a model id leaks into a string literal anywhere else —
the mechanical backstop that stopped the "claude id sent to a DeepSeek endpoint" bug
from ever recurring via copy-paste defaults.

It inspects STRING LITERALS via AST, so comments/docstrings that merely mention a
model for documentation are fine — only real string constants used as values count.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# Shapes of real vendor model ids. Deliberately specific so harness labels like
# "claude-code" or "codex" don't trip it.
_MODEL_ID = re.compile(
    r"(claude-(haiku|sonnet|opus)"
    r"|deepseek-(chat|reasoner|coder|v\d)"
    r"|gpt-\d"
    r"|o[13]-)",
    re.IGNORECASE,
)

_SRC = Path(__file__).resolve().parent.parent / "src" / "fact_layer"
_ALLOWED = {_SRC / "core" / "config.py"}


def _string_constants(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def test_no_model_literals_outside_config():
    offenders: list[str] = []
    for py in _SRC.rglob("*.py"):
        if py in _ALLOWED:
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for s in _string_constants(tree):
            if _MODEL_ID.search(s):
                offenders.append(f"{py.relative_to(_SRC)}: {s!r}")

    assert not offenders, (
        "Vendor model ids must only live in core/config.py. Move these into "
        "_ROLE_MODELS and resolve by role:\n  " + "\n  ".join(offenders)
    )


def test_config_still_owns_the_models():
    # Sanity: the one allowed home actually contains the model policy.
    from fact_layer.core import config

    for role in ("audit", "ingest", "scan", "suggest"):
        assert _MODEL_ID.search(config.model_for(role)), role
