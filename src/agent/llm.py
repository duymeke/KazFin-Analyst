"""Thin LLM client: one function, `chat()`, used by the agent and the eval baseline.

Settings come from environment variables (loaded from `.env`):
    LLM_API_KEY   API key (never printed)
    LLM_BASE_URL  OpenAI-compatible endpoint, e.g. https://openrouter.ai/api/v1
    LLM_MODEL     model id; must support tool calling

Any OpenAI-compatible provider works by changing these variables only.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class LLMConfigError(RuntimeError):
    """Raised when the LLM settings are missing from the environment."""


_client: OpenAI | None = None


def _settings() -> tuple[str, str, str]:
    load_dotenv()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", "").strip() or DEFAULT_BASE_URL
    model = os.getenv("LLM_MODEL", "").strip()
    if not api_key:
        raise LLMConfigError(
            "LLM_API_KEY is not set. Copy .env.example to .env and put your API key there."
        )
    if not model:
        raise LLMConfigError(
            "LLM_MODEL is not set. Put a model id that supports tool calling in .env."
        )
    return api_key, base_url, model


def _get_client(api_key: str, base_url: str) -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=api_key, base_url=base_url)
    return _client


def chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> Any:
    """Send `messages` to the model and return its reply message.

    The returned object has `.content` (str | None) and `.tool_calls`
    (list | None), as in the openai SDK's ChatCompletionMessage.
    """
    api_key, base_url, model = _settings()
    kwargs: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0}
    if tools:
        kwargs["tools"] = tools
    response = _get_client(api_key, base_url).chat.completions.create(**kwargs)
    return response.choices[0].message
