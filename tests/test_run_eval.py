"""Tests for eval/run_eval.py: no network, no API key (chat() is mocked)."""

import json
from types import SimpleNamespace

import pytest

from eval import run_eval
from src.models import Answer, Citation


def write_questions(tmp_path, items):
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


READY = {
    "id": "r1",
    "question": "What was X's net income in 2023?",
    "company": "X",
    "year": 2023,
    "type": "numeric",
    "gold_answer": "test",
    "gold_value": 100.0,
    "unit": "",
    "source_file": "x.pdf",
    "source_page": 5,
}
TODO_ITEM = {**READY, "id": "t1", "gold_value": "TODO", "source_page": "TODO"}
NOT_FOUND_ITEM = {**READY, "id": "n1", "type": "not_found", "gold_value": None, "source_page": None}


def good_answer(_q):
    return Answer("ok", citations=[Citation("X", 2023, "x.pdf", 5)], numbers=[100.4])


def test_fake_mode_end_to_end(tmp_path, capsys):
    qpath = write_questions(tmp_path, [READY, TODO_ITEM, NOT_FOUND_ITEM])
    code = run_eval.main(["--fake", "--questions", str(qpath), "--out", str(tmp_path / "res")])
    assert code == 0
    out = capsys.readouterr().out
    assert "Numeric accuracy" in out and "Mode: fake" in out
    files = list((tmp_path / "res").glob("fake-*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert saved["n_questions"] == 3  # fake mode keeps TODO items


def test_agent_mode_skips_todo():
    result = run_eval.evaluate("agent", [READY, TODO_ITEM, NOT_FOUND_ITEM], good_answer)
    assert result["n_questions"] == 2 and result["skipped_todo"] == 1
    assert result["summary"]["numeric"] == {"correct": 1, "total": 1, "accuracy": 1.0}
    assert result["summary"]["citation"]["accuracy"] == 1.0
    assert result["summary"]["not_found"]["accuracy"] == 0.0


def test_error_in_one_question_does_not_stop_run():
    def flaky(q):
        raise TimeoutError("slow")

    result = run_eval.evaluate("agent", [READY], flaky)
    assert result["items"][0]["error"].startswith("TimeoutError")
    assert result["summary"]["numeric"]["correct"] == 0


def test_config_error_stops_run(tmp_path, monkeypatch, capsys):
    class LLMConfigError(RuntimeError):
        pass

    def no_key(_q):
        raise LLMConfigError("LLM_API_KEY is not set")

    monkeypatch.setattr(run_eval, "get_answer_fn", lambda mode: no_key)
    qpath = write_questions(tmp_path, [READY])
    code = run_eval.main(["--questions", str(qpath), "--out", str(tmp_path / "res")])
    assert code == 1
    assert "Configuration error" in capsys.readouterr().out
    assert not (tmp_path / "res").exists()


def test_all_todo_prints_message(tmp_path, capsys):
    qpath = write_questions(tmp_path, [TODO_ITEM])
    code = run_eval.main(["--questions", str(qpath), "--out", str(tmp_path / "res")])
    assert code == 0
    assert "No questions to run" in capsys.readouterr().out


def mock_chat(monkeypatch, content):
    from src.agent import llm

    sent = []

    def fake_chat(messages, tools=None):
        sent.append((messages, tools))
        return SimpleNamespace(content=content, tool_calls=None)

    monkeypatch.setattr(llm, "chat", fake_chat)
    return sent


def test_baseline_parses_numbers_without_tools(monkeypatch):
    sent = mock_chat(monkeypatch, "In 2023 net income was 1,234.5 million KZT.")
    ans = run_eval.baseline_answer("q")
    assert ans.found is True
    assert ans.numbers == [1234.5]  # the year is skipped
    assert ans.citations == []
    assert sent[0][1] is None  # no tools


@pytest.mark.parametrize("content", ["Not found in the reports.", "", None])
def test_baseline_not_found(monkeypatch, content):
    mock_chat(monkeypatch, content)
    assert run_eval.baseline_answer("q").found is False


def test_numbers_in_text():
    assert run_eval.numbers_in_text("Up 17.31% from 520,000 in 2022") == [17.31, 520000.0]
