"""Single source of truth for LLM model policy.

Model names are POLICY, not per-call defaults. Every LLM-using command in FL
resolves its model from here BY ROLE — it must never hardcode a model literal
anywhere else. A guard test (tests/test_model_config_single_source.py) fails the
build if a vendor model id appears outside this module.

Why this module exists: model ids used to be duplicated across ~15 call sites
(CLI signatures, MCP tools, ingest/audit/scan/suggest leaves). They drifted into
three different defaults and one of them (a Claude id) was being sent to a
DeepSeek endpoint, which the endpoint rejected. Collapsing the policy to one
table makes "change the model" a one-line edit and makes provider/model mismatch
structurally impossible (see resolve_llm).

To change a role's model globally: edit _ROLE_MODELS (one line).
To override at runtime without code change: set env FL_MODEL_<ROLE> or FL_MODEL.
To override for a single call: pass model=... explicitly (CLI --model).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Role -> default model. The ONLY place vendor model ids may appear.
_ROLE_MODELS: dict[str, str] = {
    "audit": "deepseek-v4-pro",     # consistency / contradiction reasoning — quality first
    "ingest": "deepseek-v4-flash",  # high-volume eval L2 enrichment — fast / cheap
    "scan": "deepseek-v4-pro",      # markdown fact extraction
    "suggest": "deepseek-v4-pro",   # fix suggestions from check issues
}

_FALLBACK_ROLE = "audit"


def model_for(role: str | None) -> str:
    """Resolve the model for a role.

    Precedence: env FL_MODEL_<ROLE>  >  env FL_MODEL  >  _ROLE_MODELS table.
    Unknown roles fall back to the audit model.
    """
    role = role or _FALLBACK_ROLE
    specific = os.environ.get(f"FL_MODEL_{role.upper()}")
    if specific:
        return specific
    glob = os.environ.get("FL_MODEL")
    if glob:
        return glob
    return _ROLE_MODELS.get(role, _ROLE_MODELS[_FALLBACK_ROLE])


@dataclass(frozen=True)
class LLMTarget:
    """A coherent (provider, model, credentials) bundle — resolved together."""

    provider: str  # "openai" | "anthropic"
    model: str
    api_key: str | None
    base_url: str | None


def resolve_llm(
    role: str | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> LLMTarget:
    """Resolve provider + model + credentials as ONE bundle.

    Provider and model are decided together, so a provider-mismatched model
    (e.g. a Claude id sent to a DeepSeek endpoint — the original bug) cannot be
    constructed. Provider precedence matches the historical llm_call: an
    OpenAI-compatible endpoint (DeepSeek etc.) wins when configured.
    """
    if model is None:
        model = model_for(role)

    openai_key = os.environ.get("OPENAI_API_KEY")
    openai_base = os.environ.get("OPENAI_BASE_URL")
    if openai_key or openai_base:
        return LLMTarget("openai", model, openai_key, openai_base)

    anthropic_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        return LLMTarget(
            "anthropic", model, anthropic_key, os.environ.get("ANTHROPIC_BASE_URL")
        )

    raise RuntimeError(
        "No LLM API key configured. Set OPENAI_API_KEY / OPENAI_BASE_URL (for "
        "DeepSeek etc.) or ANTHROPIC_API_KEY."
    )
