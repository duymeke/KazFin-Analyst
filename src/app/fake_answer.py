"""Stand-in for src/agent/agent.answer() so the UI and eval run offline.

Same interface as the real one: `fake_answer(question) -> Answer`.

Everything here is FAKE, made up to test the UI and the eval pipeline.
The figures are not taken from any real report and must never be shown
as real data or used as gold answers.
"""

from __future__ import annotations

from typing import Any

from src.models import Answer, Citation

FAKE_TEXT = (
    "[FAKE] Net income grew by 17.31%, from 520,000 million KZT (Halyk Bank 2022, p. 79) "
    "to 610,000 million KZT (Halyk Bank 2023, p. 87)."
)

FAKE_CITATIONS = [
    Citation(
        company="Halyk Bank",
        year=2023,
        source_file="halyk_2023.pdf",
        page=87,
        snippet="[FAKE] Consolidated statement of profit or loss for 2023. Net income: 610,000 million KZT.",
    ),
    Citation(
        company="Halyk Bank",
        year=2022,
        source_file="halyk_2022.pdf",
        page=79,
        snippet="[FAKE] Consolidated statement of profit or loss for 2022. Net income: 520,000 million KZT.",
    ),
]

FAKE_NUMBERS = [17.31, 520000.0, 610000.0]

# Questions containing one of these words get a "not found" answer, so the
# UI and eval can exercise the refusal branch without a real agent.
NOT_FOUND_TRIGGERS = ("not found", "unknown", "нет данных")


def fake_answer(question: str, retriever: Any = None) -> Answer:
    """Return a fixed fake Answer. `retriever` is accepted and ignored, like answer()."""
    if any(t in question.lower() for t in NOT_FOUND_TRIGGERS):
        return Answer(text="[FAKE] Not found in the reports.", found=False)
    return Answer(
        text=FAKE_TEXT,
        citations=[Citation(**vars(c)) for c in FAKE_CITATIONS],
        numbers=list(FAKE_NUMBERS),
    )
