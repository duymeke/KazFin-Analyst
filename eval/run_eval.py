"""Run the evaluation on eval/questions.json and save the results.

    python -m eval.run_eval              # real agent: answer() from src/agent/agent.py
    python -m eval.run_eval --baseline   # same LLM, plain chat(): no retrieval, no tools
    python -m eval.run_eval --fake       # fake_answer(), tests the pipeline offline

Questions whose gold fields still contain "TODO" are skipped, except in
--fake mode, where they are kept so the pipeline can be tested before the
gold answers are filled in.

Prints a summary table and saves eval/results/<mode>-<YYYYMMDD-HHMMSS>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from eval.metrics import is_ready, score_item, summarize
from src.models import Answer

EVAL_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = EVAL_DIR / "questions.json"
RESULTS_DIR = EVAL_DIR / "results"

NOT_FOUND = "Not found in the reports"
BASELINE_PROMPT = f"""You are a financial analyst. Answer the question about the annual report of a company listed on the Kazakhstan Stock Exchange (KASE) from your own knowledge.
Give the figure with its unit. If you do not know the answer, reply exactly: "{NOT_FOUND}."
"""

_NUMBER_RE = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")

AnswerFn = Callable[[str], Answer]


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict[str, Any]]:
    """Read the test set (a JSON list of question objects)."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def numbers_in_text(text: str) -> list[float]:
    """Figures written in a plain-text answer; bare years (2000-2100) are skipped."""
    numbers = []
    for token in _NUMBER_RE.findall(text):
        value = float(token.replace(",", ""))
        if "." not in token and "," not in token and 2000 <= value <= 2100:
            continue
        numbers.append(value)
    return numbers


def baseline_answer(question: str) -> Answer:
    """The same LLM without retrieval and tools. It has no sources, so no citations."""
    from src.agent.llm import chat

    reply = chat(
        [
            {"role": "system", "content": BASELINE_PROMPT},
            {"role": "user", "content": question},
        ]
    )
    text = (reply.content or "").strip()
    if not text or NOT_FOUND.lower() in text.lower():
        return Answer(text=text or NOT_FOUND, found=False)
    return Answer(text=text, numbers=numbers_in_text(text))


def get_answer_fn(mode: str) -> AnswerFn:
    """Answer function for a mode: "agent", "baseline" or "fake"."""
    if mode == "fake":
        from src.app.fake_answer import fake_answer

        return fake_answer
    if mode == "baseline":
        return baseline_answer
    from src.agent.agent import answer

    return answer


def evaluate(
    mode: str,
    questions: list[dict[str, Any]],
    answer_fn: AnswerFn,
) -> dict[str, Any]:
    """Answer every question, score it and return the full result (not saved)."""
    keep_todo = mode == "fake"
    selected = [q for q in questions if keep_todo or is_ready(q)]
    rows = []
    for q in selected:
        started = time.perf_counter()
        error = ""
        try:
            ans = answer_fn(q["question"])
        except Exception as exc:
            if type(exc).__name__ == "LLMConfigError":
                raise  # same for every question: stop the run
            error = f"{type(exc).__name__}: {exc}"[:300]
            ans = Answer(text="", found=True)  # counts as wrong for every metric
        scores = score_item(ans, q)
        rows.append(
            {
                "id": q.get("id"),
                "question": q["question"],
                "type": q.get("type"),
                "answer": asdict(ans),
                "scores": scores,
                "error": error,
                "seconds": round(time.perf_counter() - started, 2),
            }
        )
    return {
        "mode": mode,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": os.getenv("LLM_MODEL", "") if mode != "fake" else "",
        "n_questions": len(selected),
        "skipped_todo": len(questions) - len(selected),
        "summary": summarize([r["scores"] for r in rows]),
        "items": rows,
    }


def save_result(result: dict[str, Any], out_dir: Path = RESULTS_DIR) -> Path:
    """Write the result to <out_dir>/<mode>-<YYYYMMDD-HHMMSS>.json and return the path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{result['mode']}-{stamp}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def format_summary(result: dict[str, Any]) -> str:
    """Plain-text summary table."""
    labels = {
        "numeric": "Numeric accuracy",
        "citation": "Citation accuracy",
        "not_found": "Not-found accuracy",
    }
    lines = [
        f"Mode: {result['mode']}   Questions: {result['n_questions']}   "
        f"Skipped (TODO): {result['skipped_todo']}",
        "",
        f"{'Metric':<20}{'Correct':>8}{'Total':>7}{'Accuracy':>10}",
        "-" * 45,
    ]
    for key, label in labels.items():
        m = result["summary"][key]
        acc = "-" if m["accuracy"] is None else f"{m['accuracy'] * 100:.1f}%"
        lines.append(f"{label:<20}{m['correct']:>8}{m['total']:>7}{acc:>10}")
    errors = sum(1 for r in result["items"] if r["error"])
    if errors:
        lines.append(f"\nErrors: {errors} question(s) failed, see the JSON file.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate KazFin Analyst on eval/questions.json")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--baseline", action="store_true", help="plain LLM, no retrieval and no tools")
    group.add_argument("--fake", action="store_true", help="fake answers, no LLM (offline)")
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH, help="test set JSON")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR, help="folder for result files")
    args = parser.parse_args(argv)

    mode = "fake" if args.fake else "baseline" if args.baseline else "agent"
    questions = load_questions(args.questions)
    try:
        result = evaluate(mode, questions, get_answer_fn(mode))
    except Exception as exc:
        if type(exc).__name__ != "LLMConfigError":
            raise
        print(f"Configuration error: {exc}")
        return 1

    if result["n_questions"] == 0:
        print(f"No questions to run: all {result['skipped_todo']} still have TODO gold fields.")
        return 0
    print(format_summary(result))
    path = save_result(result, args.out)
    print(f"\nSaved: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
