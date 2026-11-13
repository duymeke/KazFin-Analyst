"""UI logic without Streamlit, so it can be tested with pytest.

- choose_answer_fn(): the real agent, or fake_answer() in demo mode
- ask(): calls it and turns errors into short messages for the user
- format_citation(): "Company, year, page N"
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from src.app.fake_answer import fake_answer
from src.models import Answer, Citation

AnswerFn = Callable[[str], Answer]


@dataclass
class Backend:
    """Which answer function the UI uses and why."""

    answer_fn: AnswerFn
    is_fake: bool
    reason: str = ""  # why the fake is used; empty for the real agent


@dataclass
class AskResult:
    """Result of one question: an Answer or a user-friendly error message."""

    answer: Answer | None = None
    error: str = ""


def choose_answer_fn() -> Backend:
    """Real answer() from src.agent.agent, or fake_answer() if USE_FAKE_AGENT=1 or the import fails."""
    if os.getenv("USE_FAKE_AGENT", "").strip() == "1":
        return Backend(fake_answer, True, "USE_FAKE_AGENT=1")
    try:
        from src.agent.agent import answer
    except Exception as exc:  # missing module or dependency: fall back to the demo
        return Backend(fake_answer, True, f"agent import failed ({type(exc).__name__})")
    return Backend(answer, False)


def ask(answer_fn: AnswerFn, question: str) -> AskResult:
    """Call the answer function; never raise, never show a stack trace or a key."""
    try:
        return AskResult(answer=answer_fn(question))
    except Exception as exc:
        if type(exc).__name__ == "LLMConfigError":
            return AskResult(
                error="The LLM is not configured: copy .env.example to .env and set "
                "LLM_API_KEY and LLM_MODEL. Or run the demo with USE_FAKE_AGENT=1."
            )
        return AskResult(error=f"The request to the LLM failed ({type(exc).__name__}). Try again later.")


def format_citation(c: Citation) -> str:
    """Short label for a citation, e.g. "Halyk Bank, 2023, page 87"."""
    return f"{c.company}, {c.year}, page {c.page}"
