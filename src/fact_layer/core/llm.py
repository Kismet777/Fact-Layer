"""Unified LLM call — provider + model resolved together via core.config.resolve_llm.

Supports OpenAI-compatible providers (DeepSeek etc.) and Anthropic. The model is
never chosen here: callers pass a `role` (audit/ingest/scan/suggest) and config
resolves the model + provider as one coherent bundle.
"""

from __future__ import annotations

from fact_layer.core.config import LLMTarget, resolve_llm


def llm_call(
    prompt: str,
    *,
    role: str | None = None,
    model: str | None = None,
    system: str | None = None,
    max_tokens: int = 2048,
    api_key: str | None = None,
    json_mode: bool = True,
    max_retries: int = 1,
) -> str:
    """Single entry point for every FL LLM call.

    role: policy role -> resolves the default model via core.config.
    model: explicit override (e.g. CLI --model); wins over the role default.
    system: optional system prompt.
    json_mode: request a structured JSON object (all FL prompts are JSON). On
        OpenAI-compatible providers this sets response_format; if the endpoint
        rejects it, we transparently retry without it.
    max_retries: extra attempts when the model returns blank output (reasoning
        models occasionally emit only reasoning_content on the first pass).
    """
    target = resolve_llm(role, model=model, api_key=api_key)

    last = ""
    for _ in range(max_retries + 1):
        if target.provider == "openai":
            last = _openai_call(prompt, target, system, max_tokens, json_mode)
        else:
            last = _anthropic_call(prompt, target, system, max_tokens)
        if last and last.strip():
            return last
    return last


def _anthropic_call(
    prompt: str, target: LLMTarget, system: str | None, max_tokens: int
) -> str:
    import anthropic

    client = anthropic.Anthropic(
        api_key=target.api_key,
        **({"base_url": target.base_url} if target.base_url else {}),
    )
    kwargs: dict = {
        "model": target.model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    for block in response.content:
        if block.type == "text" and block.text:
            return block.text
    for block in response.content:
        if block.type == "thinking":
            return block.thinking
    return ""


def _openai_call(
    prompt: str,
    target: LLMTarget,
    system: str | None,
    max_tokens: int,
    json_mode: bool,
) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=target.api_key or "dummy",
        **({"base_url": target.base_url} if target.base_url else {}),
    )
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {
        "model": target.model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = client.chat.completions.create(**kwargs)
    except Exception:
        # Endpoint may not support response_format — degrade gracefully.
        if json_mode:
            kwargs.pop("response_format", None)
            response = client.chat.completions.create(**kwargs)
        else:
            raise

    msg = response.choices[0].message
    text = (msg.content or "").strip()
    if not text:
        # Reasoning-style models (e.g. deepseek-v4-flash) can leave `content`
        # empty and put their output in `reasoning_content`. Fall back to it;
        # downstream JSON extraction tolerates surrounding prose.
        text = (getattr(msg, "reasoning_content", None) or "").strip()
    return text
