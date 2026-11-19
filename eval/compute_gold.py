"""Compute gold_value of ratio questions from their hand-filled inputs.

    python -m eval.compute_gold             # compute and write eval/questions.json
    python -m eval.compute_gold --dry-run   # only print what would change

A ratio question has "formula" (a calculator name from src/agent/tools.py) and
"inputs" ([{name, value, ...}]). When every input value is filled in, the gold
value is computed with the SAME function the agent calls, so the gold answer
and the agent use one formula. Questions with a "TODO" input are skipped.

gold_value and gold_answer of ratio questions are always overwritten: edit the
inputs, not the computed fields.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from eval.metrics import TODO
from src.agent.tools import CALCULATORS

QUESTIONS_PATH = Path(__file__).resolve().parent / "questions.json"


class GoldError(ValueError):
    """An input is malformed or the formula cannot be computed."""


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compute_item(item: dict[str, Any]) -> float | None:
    """Gold value of one ratio question, or None if an input is still TODO."""
    formula = item.get("formula")
    func = CALCULATORS.get(formula or "")
    if func is None:
        raise GoldError(f"{item.get('id')}: unknown formula {formula!r}")
    args: dict[str, float] = {}
    for inp in item.get("inputs") or []:
        value = inp.get("value")
        if value == TODO:
            return None
        if not _is_number(value):
            raise GoldError(
                f"{item.get('id')}: input {inp.get('name')!r} must be a number without quotes "
                f"or commas, got {value!r}"
            )
        args[inp["name"]] = value
    try:
        return func(**args)
    except TypeError as exc:  # wrong or missing input names
        raise GoldError(f"{item.get('id')}: inputs do not match {formula}(): {exc}") from exc
    except ValueError as exc:  # zero denominator
        raise GoldError(f"{item.get('id')}: {exc}") from exc


def format_gold(value: float, unit: str) -> str:
    """Gold answer text for a computed ratio, e.g. "17.31 %" or "5.8 x"."""
    return f"{value:g} {unit}".strip()


def apply(questions: list[dict[str, Any]]) -> tuple[list[tuple[str, Any, float]], int]:
    """Fill gold_value/gold_answer of ratio questions in place.

    Returns (changes as (id, old_value, new_value), number of ratio questions still pending).
    """
    changes: list[tuple[str, Any, float]] = []
    pending = 0
    for item in questions:
        if "formula" not in item:
            continue
        value = compute_item(item)
        if value is None:
            pending += 1
            continue
        old = item.get("gold_value")
        item["gold_value"] = value
        item["gold_answer"] = format_gold(value, item.get("unit", ""))
        if old != value:
            changes.append((item.get("id", "?"), old, value))
    return changes, pending


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute gold values of ratio questions")
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    parser.add_argument("--dry-run", action="store_true", help="print changes, do not write")
    args = parser.parse_args(argv)

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    try:
        changes, pending = apply(questions)
    except GoldError as exc:
        print(f"Error: {exc}")
        return 1

    for qid, old, new in changes:
        print(f"{qid}: gold_value {old!r} -> {new:g}")
    print(f"Computed: {len(changes)} changed. Still waiting for inputs: {pending}.")
    if changes and not args.dry_run:
        args.questions.write_text(json.dumps(questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Saved: {args.questions}")
    elif changes:
        print("Dry run: nothing written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
