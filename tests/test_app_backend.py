"""UI logic tests: no Streamlit server, no network, no API key."""

from src.app import backend
from src.app.fake_answer import fake_answer
from src.models import Citation


class LLMConfigError(RuntimeError):
    """Same name as the error raised by src/agent/llm.py."""


def test_use_fake_agent_env(monkeypatch):
    monkeypatch.setenv("USE_FAKE_AGENT", "1")
    result = backend.choose_answer_fn()
    assert result.is_fake and result.answer_fn is fake_answer


def test_real_agent_by_default(monkeypatch):
    monkeypatch.delenv("USE_FAKE_AGENT", raising=False)
    result = backend.choose_answer_fn()
    assert result.is_fake is False
    assert result.answer_fn.__name__ == "answer"


def test_import_failure_falls_back_to_fake(monkeypatch):
    import builtins

    monkeypatch.delenv("USE_FAKE_AGENT", raising=False)
    real_import = builtins.__import__

    def broken_import(name, *args, **kwargs):
        if name == "src.agent.agent":
            raise ImportError("no agent")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_import)
    result = backend.choose_answer_fn()
    assert result.is_fake and "ImportError" in result.reason


def test_ask_returns_answer():
    result = backend.ask(fake_answer, "q")
    assert result.error == "" and result.answer.found


def test_ask_missing_key_is_friendly():
    def fail(_q):
        raise LLMConfigError("LLM_API_KEY is not set")

    result = backend.ask(fail, "q")
    assert result.answer is None
    assert ".env" in result.error


def test_ask_other_error_has_no_details():
    def fail(_q):
        raise ConnectionError("secret-ish details sk-123")

    result = backend.ask(fail, "q")
    assert "ConnectionError" in result.error
    assert "sk-123" not in result.error


def test_with_company_all_keeps_question():
    assert backend.with_company("  Net income? ", "All") == "Net income?"


def test_with_company_adds_hint():
    assert backend.with_company("Net income?", "Kcell") == "Net income? (Company: Kcell)"


def test_format_citation():
    c = Citation(company="KEGOC", year=2024, source_file="kegoc_2024.pdf", page=12)
    assert backend.format_citation(c) == "KEGOC, 2024, page 12"
