"""
Tiny LLM gateway — OpenAI for v0.1, room to add Anthropic / Gemini later.

The judge needs strict JSON back. We use OpenAI's response_format json_object
which works on gpt-4o-mini and up. If the chosen model doesn't support JSON
mode, we fall back to plain chat + best-effort JSON extraction.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore

DEFAULT_MODEL = os.getenv("JUDGE_MCP_MODEL", "gpt-4o-mini")

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if OpenAI is None:
        raise RuntimeError("openai package not installed. Run: pip install openai")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY not set — needed for judge LLM calls")
    _client = OpenAI()
    return _client


def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    max_tokens: int = 700,
    temperature: float = 0.3,
    json_mode: bool = False,
) -> str:
    """Single chat completion. Returns the assistant message content as a string."""
    client = _get_client()
    kwargs: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def parse_json_lenient(text: str, default: Any = None) -> Any:
    """Parse JSON; if the LLM wrapped it in prose, extract the first {…} block."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try to grab the first balanced JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return default if default is not None else {}
