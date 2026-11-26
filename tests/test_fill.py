"""Tests for eval/fill.py with scripted answers. Numbers are arbitrary test values, not report data."""

import copy
import json

import pytest

from eval import fill
from src.agent import tools

MANIFEST = {
    "halyk_2022.pdf": {"file": "halyk_2022.pdf", "company": "Halyk Bank", "year": 2022},
    "halyk_2023.pdf": {"file": "halyk_2023.pdf", "company": "Halyk Bank", "year": 2023},
    "kegoc_2023.pdf": {"file": "kegoc_2023.pdf", "company": "KEGOC", "year": 2023},
}
SINGLE = {
    "id": "q1", "question": "Net income?", "company": "Halyk Bank", "year": 2022, "type": "numeric",
    "unit": "million KZT", "label": "Net income 2022", "gold_answer": "TODO", "gold_value": "TODO",
    "source_file": "halyk_2022.pdf", "source_page": "TODO", "note": "hint",
}
RATIO = {
    "id": "q2", "question": "D/E?", "company": "Halyk Bank", "year": 2023, "type": "numeric", "unit": "x",
    "formula": "debt_to_equity",
    "inputs": [
        {"name": "total_liabilities", "label": "Total liabilities 2023", "value": "TODO",
         "source_file": "halyk_2023.pdf", "source_page": "TODO"},
        {"name": "total_equity", "label": "Total equity 2023", "value": "TODO",
         "source_file": "halyk_2023.pdf", "source_page": "TODO"},
    ],
    "gold_answer": "TODO", "gold_value": "TODO",
}
TEXT = {
    "id": "q3", "question": "Auditor?", "company": "KEGOC", "year": 2023, "type": "text", "unit": "",
    "gold_answer": "TODO", "gold_keywords": ["TODO"], "gold_value": None,
    "source_file": "kegoc_2023.pdf", "source_page": "TODO",
}
NOT_FOUND = {
    "id": "q4", "question": "2019?", "company": "Halyk Bank", "year": 2019, "type": "not_found", "unit": "",
    "gold_answer": "TODO", "gold_value": None, "source_file": None, "source_page": None,
}


# --- parsing ----------------------------------------------------------------

@pytest.mark.parametrize(
    "text,value",
    [
        ("693,436", 693436),
        ("1 097 066 105", 1097066105),
        ("1 097 066", 1097066),
        ("1.097.066.105", 1097066105),
        ("(1,234)", -1234),
        ("-1,234", -1234),
        ("−5", -5),
        ("17.31", 17.31),
        ("1,234.5", 1234.5),
        (" 42 ", 42),
    ],
)
def test_parse_number(text, value):
    assert fill.parse_number(text) == value
    assert type(fill.parse_number(text)) is type(value)


@pytest.mark.parametrize("text", ["abc", "12a", "1.2.3a", "", "--5", "()"])
def test_parse_number_rejects(text):
    with pytest.raises(ValueError):
        fill.parse_number(text)


@pytest.mark.parametrize("text", ["0", "-3", "2.5", "x"])
def test_parse_page_rejects(text):
    with pytest.raises(ValueError):
        fill.parse_page(text)


# --- the interactive flow ------------------------------------------------------

class Session:
    """Runs fill.main on a temp file with scripted answers."""

    def __init__(self, tmp_path, questions):
        self.qpath = tmp_path / "q.json"
        self.qpath.write_text(json.dumps(questions), encoding="utf-8")
        self.mpath = tmp_path / "reports.json"
        self.mpath.write_text(json.dumps({"reports": list(MANIFEST.values())}), encoding="utf-8")
        self.out = []

    def run(self, answers, *args):
        answers = list(answers)

        def ask(prompt):
            self.out.append(prompt)
            if not answers:
                raise EOFError
            return answers.pop(0)

        code = fill.main(["--questions", str(self.qpath), "--manifest", str(self.mpath), *args],
                         ask=ask, say=self.out.append)
        assert code == 0
        return json.loads(self.qpath.read_text(encoding="utf-8"))

    @property
    def text(self):
        return "\n".join(self.out)


def test_single_figure_with_comparative_file(tmp_path):
    s = Session(tmp_path, [copy.deepcopy(SINGLE)])
    # value, file (2022 figure read in the 2023 report), page, gold_answer default
    q = s.run(["693,436", "halyk_2023.pdf", "12", ""])[0]
    assert q["gold_value"] == 693436
    assert q["source_file"] == "halyk_2023.pdf" and q["source_page"] == 12
    assert q["gold_answer"] == "693,436 million KZT"
    assert "saved as 693,436" in s.text


def test_bad_inputs_are_asked_again(tmp_path):
    s = Session(tmp_path, [copy.deepcopy(SINGLE)])
    q = s.run(["six", "600", "kegoc_2023.pdf", "halyk_2019.pdf", "", "0", "7", "my answer"])[0]
    assert q["gold_value"] == 600 and q["source_file"] == "halyk_2022.pdf"
    assert q["source_page"] == 7 and q["gold_answer"] == "my answer"
    assert "Type a number" in s.text
    assert "is a KEGOC report" in s.text and "not in data/reports.json" in s.text


def test_ratio_inputs_and_computed_gold(tmp_path):
    s = Session(tmp_path, [copy.deepcopy(RATIO)])
    q = s.run(["580", "", "20", "100", "", "21"])[0]
    assert [i["value"] for i in q["inputs"]] == [580, 100]
    assert [i["source_page"] for i in q["inputs"]] == [20, 21]
    assert q["gold_value"] == tools.debt_to_equity(580, 100)
    assert q["gold_answer"] == "5.8 x"


def test_ratio_partial_stays_todo(tmp_path):
    s = Session(tmp_path, [copy.deepcopy(RATIO)])
    q = s.run(["580", "", "20", "", ""])[0]
    assert q["inputs"][0]["value"] == 580 and q["inputs"][1]["value"] == "TODO"
    assert q["gold_value"] == "TODO"


def test_text_question(tmp_path):
    s = Session(tmp_path, [copy.deepcopy(TEXT)])
    q = s.run(["Audit Firm LLP", "Audit Firm, LLP", "", "3"])[0]
    assert q["gold_answer"] == "Audit Firm LLP"
    assert q["gold_keywords"] == ["Audit Firm", "LLP"]
    assert q["source_page"] == 3


@pytest.mark.parametrize("answer,expected", [("y", "Not found in the reports"), ("n", "TODO"), ("", "TODO")])
def test_not_found_question(tmp_path, answer, expected):
    s = Session(tmp_path, [copy.deepcopy(NOT_FOUND)])
    q = s.run([answer])[0]
    assert q["gold_answer"] == expected
    if answer == "n":
        assert "Questions to replace" in s.text and "q4" in s.text


def test_quit_keeps_saved_answers(tmp_path):
    s = Session(tmp_path, [copy.deepcopy(SINGLE), copy.deepcopy(NOT_FOUND)])
    qs = s.run(["500", "q"])
    assert qs[0]["gold_value"] == 500 and qs[0]["source_page"] == "TODO"
    assert qs[1]["gold_answer"] == "TODO"
    assert "Stopped" in s.text


def test_eof_is_like_quit(tmp_path):
    s = Session(tmp_path, [copy.deepcopy(SINGLE)])
    qs = s.run([])
    assert qs[0]["gold_value"] == "TODO" and "Stopped" in s.text


def test_filters_by_company_and_id(tmp_path):
    s = Session(tmp_path, [copy.deepcopy(SINGLE), copy.deepcopy(TEXT), copy.deepcopy(NOT_FOUND)])
    s.run([], "--company", "kegoc")
    assert "[q3]" in s.text and "[q1]" not in s.text
    s2 = Session(tmp_path, [copy.deepcopy(SINGLE), copy.deepcopy(NOT_FOUND)])
    s2.run([], "--id", "q4")
    assert "[q4]" in s2.text and "[q1]" not in s2.text


def test_nothing_to_fill(tmp_path):
    done = {**copy.deepcopy(NOT_FOUND), "gold_answer": "Not found in the reports"}
    s = Session(tmp_path, [done])
    s.run([])
    assert "Nothing to fill" in s.text


def test_report_shows_consistency_warning(tmp_path):
    other = {**copy.deepcopy(SINGLE), "id": "q9", "gold_value": 1, "gold_answer": "1",
             "source_page": 5}
    s = Session(tmp_path, [copy.deepcopy(SINGLE), other])
    s.run(["2", "", "6", ""])
    assert "warning" in s.text and "different values" in s.text
