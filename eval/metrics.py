"""Evaluation metrics: pure functions over an Answer and one test item.

A test item is one object from eval/questions.json:
    id, question, company, year, type ("numeric" | "text" | "not_found"), unit,
    gold_answer, gold_value, source_file, source_page, note
  ratio questions (numeric) also have:
    formula   name of a calculator in src/agent/tools.py, e.g. "roe"
    inputs    [{name, label, value, source_file, source_page}, ...]
  text questions also have:
    gold_keywords   words that must appear in a correct answer

Which metric applies to which question type:
    numeric accuracy    -> "numeric"
    citation accuracy   -> "numeric" and "text"
    text accuracy       -> "text"
    not-found accuracy  -> "not_found"

A citation is correct when it points to the file and page where the gold
figure was read (source_file + page), not to the question's year: the report
for year X also holds the X-1 figures in its comparative column.
"""

from __future__ import annotations

from typing import Any

from src.models import Answer

TODO = "TODO"
GOLD_FIELDS = ("gold_answer", "gold_value", "source_page")
METRICS = ("numeric", "citation", "text", "not_found")


def is_ready(item: dict[str, Any]) -> bool:
    """True if every gold field, keyword and input is filled in by hand (no "TODO" left)."""
    if any(item.get(f) == TODO for f in GOLD_FIELDS):
        return False
    if TODO in (item.get("gold_keywords") or []):
        return False
    return all(inp.get("value") != TODO and inp.get("source_page") != TODO for inp in item.get("inputs") or [])


def numeric_correct(answer: Answer, gold_value: float | None, tolerance: float = 0.01) -> bool:
    """True if any number in answer.numbers is within `tolerance` (relative, 1%) of gold_value.

    For gold_value == 0 the tolerance is absolute, since 1% of zero is zero.
    """
    if gold_value is None or isinstance(gold_value, (str, bool)) or not answer.numbers:
        return False
    allowed = tolerance * abs(gold_value) if gold_value != 0 else tolerance
    return any(abs(n - gold_value) <= allowed for n in answer.numbers)


def _norm(name: Any) -> str:
    return " ".join(str(name or "").split()).casefold()


def _is_page(page: Any) -> bool:
    return isinstance(page, int) and not isinstance(page, bool)


def gold_locations(item: dict[str, Any]) -> set[tuple[str, int]]:
    """(source_file, page) pairs where the gold figures were read: the item itself and its inputs."""
    places = [item, *(item.get("inputs") or [])]
    return {
        (_norm(p.get("source_file")), p["source_page"])
        for p in places
        if p.get("source_file") and _is_page(p.get("source_page"))
    }


def citation_correct(answer: Answer, item: dict[str, Any]) -> bool:
    """True if any citation is for the item's company and points to a gold (source_file, page)."""
    locations = gold_locations(item)
    if not locations:
        return False
    return any(
        _norm(c.company) == _norm(item.get("company")) and (_norm(c.source_file), c.page) in locations
        for c in answer.citations
    )


def text_correct(answer: Answer, item: dict[str, Any]) -> bool:
    """For a "text" item: True if every gold keyword appears in the answer text (case-insensitive)."""
    keywords = [k for k in item.get("gold_keywords") or [] if k and k != TODO]
    if item.get("type") != "text" or not keywords or not answer.found:
        return False
    text = _norm(answer.text)
    return all(_norm(k) in text for k in keywords)


def not_found_correct(answer: Answer, item: dict[str, Any]) -> bool:
    """For a "not_found" item: True if the answer says the data is not in the reports."""
    return item.get("type") == "not_found" and answer.found is False


def score_item(answer: Answer, item: dict[str, Any]) -> dict[str, bool | None]:
    """All metrics for one item; None means the metric does not apply to this type."""
    kind = item.get("type")
    return {
        "numeric": numeric_correct(answer, item.get("gold_value")) if kind == "numeric" else None,
        "citation": citation_correct(answer, item) if kind in ("numeric", "text") else None,
        "text": text_correct(answer, item) if kind == "text" else None,
        "not_found": not_found_correct(answer, item) if kind == "not_found" else None,
    }


def summarize(scores: list[dict[str, bool | None]]) -> dict[str, dict[str, float | int | None]]:
    """Accuracy per metric over the items where it applies.

    Returns {metric: {"correct": int, "total": int, "accuracy": float | None}}.
    """
    summary: dict[str, dict[str, float | int | None]] = {}
    for metric in METRICS:
        values = [s[metric] for s in scores if s.get(metric) is not None]
        correct = sum(1 for v in values if v)
        summary[metric] = {
            "correct": correct,
            "total": len(values),
            "accuracy": round(correct / len(values), 4) if values else None,
        }
    return summary
