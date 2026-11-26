"""Fill in the gold fields of eval/questions.json from the terminal.

    python -m eval.fill                          # every question with TODO left
    python -m eval.fill --company "Halyk Bank"   # one company
    python -m eval.fill --id q005 q006           # chosen questions

The helper only ASKS: it shows each question, its file, unit and hint, and
you type what you read in the PDF. It never looks up or suggests a figure.

- Numbers may be typed as in the PDF: 693,436 / 1 097 066 105 / (1,234) for a
  negative figure; the helper shows how it saved them.
- Enter skips a field (it stays "TODO"), q quits. Every answer is saved at once.
- Ratio questions ask only for their inputs; the gold ratio is computed by
  eval.compute_gold with the agent's calculator functions.
- At the end the file is validated and the consistency warnings are shown.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

from eval.check_questions import MANIFEST_PATH, check, load_manifest
from eval.compute_gold import GoldError, compute_item, format_gold
from eval.consistency import check_consistency
from eval.metrics import TODO, is_ready

QUESTIONS_PATH = Path(__file__).resolve().parent / "questions.json"
NOT_FOUND_ANSWER = "Not found in the reports"
_DIGITS_RE = re.compile(r"\d+(?:\.\d+)?")


class Quit(Exception):
    """The user typed q (or closed the input)."""


def parse_number(text: str) -> int | float:
    """A figure typed as in the PDF -> number. Raises ValueError if it is not a number.

    "693,436" -> 693436, "1 097 066 105" -> 1097066105, "1.097.066.105" -> 1097066105,
    "(1,234)" and "-1,234" -> -1234, "17.31" -> 17.31.
    """
    s = text.strip()
    for ch in (" ", " ", " ", "\t"):
        s = s.replace(ch, "")
    s = s.replace("−", "-")
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.startswith("-"):
        negative, s = True, s[1:]
    s = s.replace(",", "")
    if s.count(".") > 1:  # dot thousands separators
        s = s.replace(".", "")
    if not _DIGITS_RE.fullmatch(s):
        raise ValueError(f"not a number: {text!r}")
    value: int | float = float(s) if "." in s else int(s)
    return -value if negative else value


def parse_page(text: str) -> int:
    """A page number in the PDF viewer, >= 1."""
    page = int(text.strip())
    if page < 1:
        raise ValueError("page must be 1 or more")
    return page


def _show(value: int | float) -> str:
    return f"{value:,}" if isinstance(value, int) else f"{value:,.10g}"


class Filler:
    """Asks for the TODO fields of questions; `ask` and `say` are replaceable for tests."""

    def __init__(
        self,
        questions: list[dict[str, Any]],
        save: Callable[[], None],
        manifest: dict[str, dict[str, Any]],
        ask: Callable[[str], str] = input,
        say: Callable[[str], None] = print,
    ) -> None:
        self.questions = questions
        self.save = save
        self.manifest = manifest
        self.ask = ask
        self.say = say
        self.flagged: list[str] = []  # not_found questions whose data turned out to be in a report

    # --- prompts -------------------------------------------------------------

    def _input(self, prompt: str) -> str:
        try:
            text = self.ask(prompt)
        except (EOFError, KeyboardInterrupt):
            raise Quit from None
        if text.strip().lower() in ("q", "quit"):
            raise Quit
        return text.strip()

    def _ask_parsed(self, prompt: str, parse: Callable[[str], Any], error: str) -> Any:
        """Ask until the answer parses; Enter returns None (skip)."""
        while True:
            text = self._input(prompt)
            if not text:
                return None
            try:
                return parse(text)
            except ValueError:
                self.say(f"    {error}")

    def _ask_file(self, where: dict[str, Any], company: str) -> None:
        """Let the user change source_file, e.g. to the next year's report (comparative column)."""
        current = where.get("source_file")
        while True:
            text = self._input(f"  Read in which file? Enter = {current}: ")
            if not text:
                return
            report = self.manifest.get(text)
            if report is None:
                self.say(f"    {text} is not in data/reports.json")
            elif report["company"] != company:
                self.say(f"    {text} is a {report['company']} report, not {company}")
            else:
                where["source_file"] = text
                self.save()
                return

    def _fill_figure(self, where: dict[str, Any], value_key: str, company: str, what: str) -> None:
        """Value, file and page of one figure (a single question or one ratio input)."""
        if where.get(value_key) == TODO:
            value = self._ask_parsed(
                f"  {what} (number as in the PDF, Enter = skip): ",
                parse_number,
                "Type a number, e.g. 693,436 or (1,234) for a negative figure.",
            )
            if value is None:
                return
            where[value_key] = value
            self.save()
            self.say(f"    saved as {_show(value)}")
            self._ask_file(where, company)
        if where.get("source_page") == TODO:
            page = self._ask_parsed(
                f"  Page in {where.get('source_file')} (as the PDF viewer shows it): ",
                parse_page,
                "Type a whole page number, e.g. 12.",
            )
            if page is not None:
                where["source_page"] = page
                self.save()

    # --- question types ------------------------------------------------------

    def _numeric(self, q: dict[str, Any]) -> None:
        self._fill_figure(q, "gold_value", q["company"], f"{q.get('label', 'Value')}, {q['unit']}")
        value = q.get("gold_value")
        if q.get("gold_answer") == TODO and value != TODO:
            default = f"{_show(value)} {q['unit']}".strip()
            text = self._input(f"  gold_answer, Enter = \"{default}\": ")
            q["gold_answer"] = text or default
            self.save()

    def _ratio(self, q: dict[str, Any]) -> None:
        for inp in q.get("inputs") or []:
            self.say(f"  - input {inp.get('name')}: {inp.get('label')}")
            self._fill_figure(inp, "value", q["company"], f"{inp.get('label')}, {self._unit_of(q)}")
        try:
            value = compute_item(q)
        except GoldError as exc:
            self.say(f"    cannot compute yet: {exc}")
            return
        if value is not None:
            q["gold_value"] = value
            q["gold_answer"] = format_gold(value, q.get("unit", ""))
            self.save()
            self.say(f"    gold = {q['gold_answer']} (computed by {q['formula']})")

    def _unit_of(self, q: dict[str, Any]) -> str:
        """Unit of a ratio's inputs: the company's reporting unit."""
        from eval.check_questions import COMPANY_UNITS

        return COMPANY_UNITS.get(q.get("company"), "unit of the report")

    def _text(self, q: dict[str, Any]) -> None:
        if q.get("gold_answer") == TODO:
            text = self._input("  Answer as written in the report (Enter = skip): ")
            if text:
                q["gold_answer"] = text
                self.save()
        if q.get("gold_keywords") == [TODO]:
            text = self._input("  1-2 keywords a correct answer must contain, comma-separated: ")
            keywords = [k.strip() for k in text.split(",") if k.strip()]
            if keywords:
                q["gold_keywords"] = keywords
                self.save()
        if q.get("source_page") == TODO:
            self._ask_file(q, q["company"])
            page = self._ask_parsed(
                f"  Page in {q.get('source_file')}: ", parse_page, "Type a whole page number, e.g. 3."
            )
            if page is not None:
                q["source_page"] = page
                self.save()

    def _not_found(self, q: dict[str, Any]) -> None:
        while True:
            text = self._input(
                "  Did you check the reports and this data is NOT there? "
                "y = not there / n = it IS there / Enter = skip: "
            ).lower()
            if text in ("", "y", "n"):
                break
        if text == "y":
            q["gold_answer"] = NOT_FOUND_ANSWER
            self.save()
        elif text == "n":
            self.flagged.append(q["id"])
            self.say("    Left as TODO. This question must be replaced: tell the team or the agent.")

    # --- main loop -----------------------------------------------------------

    def run(self, selected: list[dict[str, Any]]) -> None:
        """Ask about every selected question; stop early on q."""
        for n, q in enumerate(selected, 1):
            self.say("")
            self.say(f"[{q['id']}] ({n}/{len(selected)}) {q['question']}")
            self.say(f"  {q['company']}, {q.get('year')}, type {q['type']}"
                     + (f", unit {q['unit']}" if q.get("unit") else ""))
            if q.get("note"):
                self.say(f"  Hint: {q['note']}")
            if q["type"] == "not_found":
                self._not_found(q)
            elif q["type"] == "text":
                self._text(q)
            elif "formula" in q:
                self._ratio(q)
            else:
                self._numeric(q)


def select(questions: list[dict[str, Any]], company: str | None = None,
           ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Questions that still have TODO, filtered by company (case-insensitive) and ids."""
    chosen = [q for q in questions if not is_ready(q)]
    if company:
        chosen = [q for q in chosen if str(q.get("company", "")).casefold() == company.casefold()]
    if ids:
        wanted = set(ids)
        chosen = [q for q in chosen if q.get("id") in wanted]
    return chosen


def report(questions: list[dict[str, Any]], manifest: dict[str, dict[str, Any]],
           say: Callable[[str], None] = print) -> None:
    """Validation, consistency warnings and progress after a session."""
    errors = check(questions, manifest)
    ready = sum(1 for q in questions if is_ready(q))
    say("")
    say(f"Ready (no TODO): {ready} of {len(questions)}.")
    for e in errors:
        say(f"  problem: {e}")
    for w in check_consistency(questions):
        say(f"  warning: {w}")


def main(argv: list[str] | None = None, ask: Callable[[str], str] = input,
         say: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(description="Fill in gold values of eval/questions.json")
    parser.add_argument("--company", help='e.g. "Halyk Bank"')
    parser.add_argument("--id", nargs="+", dest="ids", help="question ids, e.g. q001 q005")
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args(argv)

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    manifest = load_manifest(args.manifest)

    def save() -> None:
        args.questions.write_text(json.dumps(questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    selected = select(questions, args.company, args.ids)
    if not selected:
        say("Nothing to fill: no question with TODO matches.")
        return 0
    say(f"{len(selected)} question(s) to fill. Enter = skip a field, q = quit. Answers are saved at once.")
    filler = Filler(questions, save, manifest, ask, say)
    try:
        filler.run(selected)
    except Quit:
        say("\nStopped. Everything typed so far is saved.")
    if filler.flagged:
        say(f"Questions to replace (data is in the reports): {', '.join(filler.flagged)}")
    report(questions, manifest, say)
    return 0


if __name__ == "__main__":
    sys.exit(main())
