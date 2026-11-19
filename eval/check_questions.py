"""Validate eval/questions.json and print a summary.

    python -m eval.check_questions

Checks: required fields, unique ids, valid types, source_file listed in
data/reports.json for the same company, report year equal to the question year
or the next year (comparative column), units, ratio formulas and their input
names, number types. "TODO" is allowed everywhere a hand-filled value goes;
it is counted, not reported as an error.

Exit code 1 if the file is invalid.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from eval.metrics import TODO, is_ready
from src.agent.tools import CALCULATORS

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = ROOT / "eval" / "questions.json"
MANIFEST_PATH = ROOT / "data" / "reports.json"

TYPES = ("numeric", "text", "not_found")
REQUIRED = ("id", "question", "company", "year", "type", "unit", "gold_answer", "gold_value")
# Units of the figures in each company's statements (see DECISIONS.md, Berikzhan's prompt rules).
COMPANY_UNITS = {"Halyk Bank": "million KZT", "KEGOC": "thousand KZT", "Kcell": "million KZT"}
FORMULA_UNITS = {"percent_change": "%", "net_margin": "%", "roe": "%", "debt_to_equity": "x", "ratio": "x"}


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, dict[str, Any]]:
    """{file name: {"company", "year"}} for the reports that are indexed (no "skip")."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {r["file"]: r for r in data.get("reports", []) if not r.get("skip")}


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_page(v: Any) -> bool:
    return v == TODO or (isinstance(v, int) and not isinstance(v, bool) and v >= 1)


def _check_source(qid: str, where: str, company: str, file: Any, page: Any,
                  manifest: dict[str, dict[str, Any]], years: set[int] | None) -> list[str]:
    errors = []
    report = manifest.get(file) if isinstance(file, str) else None
    if report is None:
        errors.append(f"{qid}: {where}source_file {file!r} is not in data/reports.json")
    else:
        if report["company"] != company:
            errors.append(f"{qid}: {where}source_file {file} belongs to {report['company']}, not {company}")
        if years is not None and report["year"] not in years:
            errors.append(f"{qid}: {where}source_file {file} is the {report['year']} report; "
                          f"expected year {sorted(years)[0]} or the next one")
    if not _is_page(page):
        errors.append(f"{qid}: {where}source_page must be a page number >= 1 or \"TODO\", got {page!r}")
    return errors


def check_item(item: Any, manifest: dict[str, dict[str, Any]]) -> list[str]:
    """All problems of one question, as readable messages."""
    if not isinstance(item, dict):
        return [f"not an object: {item!r}"]
    qid = str(item.get("id", "?"))
    errors = [f"{qid}: missing field {f!r}" for f in REQUIRED if f not in item]
    if errors:
        return errors

    kind, company, year, unit = item["type"], item["company"], item["year"], item["unit"]
    if kind not in TYPES:
        return [f"{qid}: type must be one of {TYPES}, got {kind!r}"]
    if not isinstance(year, int) or isinstance(year, bool):
        errors.append(f"{qid}: year must be an integer, got {year!r}")
        year = None
    known_companies = {r["company"] for r in manifest.values()}
    if kind != "not_found" and company not in known_companies:
        errors.append(f"{qid}: company {company!r} is not in data/reports.json")

    if kind == "not_found":
        if item["gold_value"] is not None:
            errors.append(f"{qid}: not_found question must have gold_value null")
        if item.get("source_file") is not None:
            errors.append(f"{qid}: not_found question must have source_file null")
        return errors

    if kind == "text":
        keywords = item.get("gold_keywords")
        if not isinstance(keywords, list) or not keywords or not all(isinstance(k, str) and k for k in keywords):
            errors.append(f"{qid}: text question needs gold_keywords, a non-empty list of strings")
        if item["gold_value"] is not None:
            errors.append(f"{qid}: text question must have gold_value null")
        years = {year, year + 1} if year else None
        errors += _check_source(qid, "", company, item.get("source_file"), item.get("source_page"), manifest, years)
        return errors

    # numeric
    if not (_is_number(item["gold_value"]) or item["gold_value"] == TODO):
        errors.append(f"{qid}: gold_value must be a number or \"TODO\", got {item['gold_value']!r}")

    if "formula" not in item:
        expected = COMPANY_UNITS.get(company)
        if expected and unit != expected:
            errors.append(f"{qid}: unit for {company} must be {expected!r}, got {unit!r}")
        years = {year, year + 1} if year else None
        errors += _check_source(qid, "", company, item.get("source_file"), item.get("source_page"), manifest, years)
        return errors

    formula = item["formula"]
    func = CALCULATORS.get(formula)
    if func is None:
        return errors + [f"{qid}: unknown formula {formula!r}; use one of {sorted(CALCULATORS)}"]
    if unit != FORMULA_UNITS.get(formula, unit):
        errors.append(f"{qid}: unit for {formula} must be {FORMULA_UNITS[formula]!r}, got {unit!r}")
    inputs = item.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        return errors + [f"{qid}: ratio question needs a non-empty inputs list"]
    params = list(inspect.signature(func).parameters)
    names = [i.get("name") for i in inputs if isinstance(i, dict)]
    if sorted(names) != sorted(params):
        errors.append(f"{qid}: inputs for {formula} must be {params}, got {names}")
    for inp in inputs:
        if not isinstance(inp, dict):
            errors.append(f"{qid}: input is not an object: {inp!r}")
            continue
        where = f"input {inp.get('name')!r}: "
        value = inp.get("value")
        if not (_is_number(value) or value == TODO):
            errors.append(f"{qid}: {where}value must be a number (no quotes, no commas) or \"TODO\", got {value!r}")
        errors += _check_source(qid, where, company, inp.get("source_file"), inp.get("source_page"), manifest, None)
    return errors


def check(questions: Any, manifest: dict[str, dict[str, Any]]) -> list[str]:
    """All problems in the question file; empty list means valid."""
    if not isinstance(questions, list):
        return ["the file must contain a JSON list of questions"]
    errors: list[str] = []
    ids = Counter(q.get("id") for q in questions if isinstance(q, dict))
    errors += [f"duplicate id {i!r} ({n} times)" for i, n in ids.items() if n > 1]
    for item in questions:
        errors += check_item(item, manifest)
    return errors


def summary(questions: list[dict[str, Any]]) -> str:
    """Counts per company and type, and how many questions are ready (no TODO)."""
    rows = Counter((q.get("company"), "ratio" if "formula" in q else q.get("type")) for q in questions)
    cols = ["numeric", "ratio", "text", "not_found"]
    companies = sorted({c for c, _ in rows}, key=str)
    lines = [f"{'Company':<14}" + "".join(f"{c:>11}" for c in cols) + f"{'total':>8}", "-" * 66]
    for company in companies:
        counts = [rows[(company, c)] for c in cols]
        lines.append(f"{company:<14}" + "".join(f"{n:>11}" for n in counts) + f"{sum(counts):>8}")
    totals = [sum(rows[(co, c)] for co in companies) for c in cols]
    lines.append(f"{'total':<14}" + "".join(f"{n:>11}" for n in totals) + f"{sum(totals):>8}")
    ready = sum(1 for q in questions if is_ready(q))
    lines.append("")
    lines.append(f"Ready (no TODO): {ready} of {len(questions)}. Still TODO: {len(questions) - ready}.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate eval/questions.json")
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args(argv)

    try:
        questions = json.loads(args.questions.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in {args.questions}: {exc}")
        return 1
    errors = check(questions, load_manifest(args.manifest))
    if isinstance(questions, list):
        print(summary([q for q in questions if isinstance(q, dict)]))
    if errors:
        print(f"\n{len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("\nOK: the file is valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
