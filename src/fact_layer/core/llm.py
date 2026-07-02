"""Unified LLM call — supports Anthropic and OpenAI-compatible providers (DeepSeek, etc.)."""

from __future__ import annotations

import os


def llm_call(prompt: str, model: str, max_tokens: int = 2048, api_key: str | None = None) -> str:
    openai_key = os.environ.get("OPENAI_API_KEY")
    openai_base = os.environ.get("OPENAI_BASE_URL")
    anthropic_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    if openai_key or openai_base:
        return _openai_call(prompt, model, max_tokens, openai_key, openai_base)

    if anthropic_key:
        return _anthropic_call(prompt, model, max_tokens, anthropic_key)

    raise RuntimeError(
        "No LLM API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY (for DeepSeek etc.)."
    )


def _anthropic_call(
    prompt: str, model: str, max_tokens: int, api_key: str
) -> str:
    import anthropic

    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    client = anthropic.Anthropic(
        api_key=api_key, **({"base_url": base_url} if base_url else {})
    )
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "text" and block.text:
            return block.text
    for block in response.content:
        if block.type == "thinking":
            return block.thinking
    return ""


def _openai_call(
    prompt: str, model: str, max_tokens: int, api_key: str | None, base_url: str | None
) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=api_key or "dummy",
        **({"base_url": base_url} if base_url else {}),
    )
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content
