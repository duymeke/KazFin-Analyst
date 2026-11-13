"""Evaluation metrics: pure functions over an Answer and one test item.

A test item is one object from eval/questions.json:
    id, question, company, year, type ("numeric" | "text" | "not_found"),
    gold_answer, gold_value, unit, source_file, source_page

Which metric applies to which question type:
    numeric accuracy    -> "numeric"
    citation accuracy   -> "numeric" and "text"
    not-found accuracy  -> "not_found"
"""

from __future__ import annotations

from typing import Any

from src.models import Answer

TODO = "TODO"
GOLD_FIELDS = ("gold_answer", "gold_value", "source_page")


def is_ready(item: dict[str, Any]) -> bool:
    """True if the gold fields are filled in by hand (no "TODO" left)."""
    return all(item.get(f) != TODO for f in GOLD_FIELDS)


def numeric_correct(answer: Answer, gold_value: float | None, tolerance: float = 0.01) -> bool:
    """True if any number in answer.numbers is within `tolerance` (relative, 1%) of gold_value.

    For gold_value == 0 the tolerance is absolute, since 1% of zero is zero.
    """
    if gold_value is None or isinstance(gold_value, str) or not answer.numbers:
        return False
    allowed = tolerance * abs(gold_value) if gold_value != 0 else tolerance
    return any(abs(n - gold_value) <= allowed for n in answer.numbers)


def _norm(name: Any) -> str:
    return " ".join(str(name or "").split()).casefold()


def citation_correct(answer: Answer, item: dict[str, Any]) -> bool:
    """True if any citation matches the item's company, year and source_page."""
    page = item.get("source_page")
    if not isinstance(page, int) or isinstance(page, bool):
        return False
    return any(
        _norm(c.company) == _norm(item.get("company")) and c.year == item.get("year") and c.page == page
        for c in answer.citations
    )


def not_found_correct(answer: Answer, item: dict[str, Any]) -> bool:
    """For a "not_found" item: True if the answer says the data is not in the reports."""
    return item.get("type") == "not_found" and answer.found is False


def score_item(answer: Answer, item: dict[str, Any]) -> dict[str, bool | None]:
    """All metrics for one item; None means the metric does not apply to this type."""
    kind = item.get("type")
    return {
        "numeric": numeric_correct(answer, item.get("gold_value")) if kind == "numeric" else None,
        "citation": citation_correct(answer, item) if kind in ("numeric", "text") else None,
        "not_found": not_found_correct(answer, item) if kind == "not_found" else None,
    }


def summarize(scores: list[dict[str, bool | None]]) -> dict[str, dict[str, float | int | None]]:
    """Accuracy per metric over the items where it applies.

    Returns {metric: {"correct": int, "total": int, "accuracy": float | None}}.
    """
    summary: dict[str, dict[str, float | int | None]] = {}
    for metric in ("numeric", "citation", "not_found"):
        values = [s[metric] for s in scores if s.get(metric) is not None]
        correct = sum(1 for v in values if v)
        summary[metric] = {
            "correct": correct,
            "total": len(values),
            "accuracy": round(correct / len(values), 4) if values else None,
        }
    return summary
