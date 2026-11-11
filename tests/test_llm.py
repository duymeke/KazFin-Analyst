import pytest

from src.agent import llm


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    # do not read a real .env from the developer's machine during tests
    monkeypatch.setattr(llm, "load_dotenv", lambda: None)


def test_missing_key_gives_clear_error(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MODEL", "some-model")
    with pytest.raises(llm.LLMConfigError, match="LLM_API_KEY"):
        llm.chat([{"role": "user", "content": "hi"}])


def test_missing_model_gives_clear_error(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test-secret")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(llm.LLMConfigError) as exc:
        llm.chat([{"role": "user", "content": "hi"}])
    assert "sk-test-secret" not in str(exc.value)


def test_default_base_url(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert llm._settings()[1] == llm.DEFAULT_BASE_URL
