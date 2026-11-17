"""Agent loop tests with a scripted fake chat(): no network, no API key."""

import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from src.agent import agent
from src.agent.stub_retriever import StubRetriever

REAL_DEFAULT_RETRIEVER = agent._default_retriever


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    """Keep every test offline: answer() without a retriever gets the stub data."""
    monkeypatch.setattr(agent, "_default_retriever", StubRetriever)


def tool_call(call_id, name, args):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def reply(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


class ScriptedChat:
    """Returns the prepared replies in order and records what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])
        return self.replies.pop(0)


def use_chat(monkeypatch, replies):
    fake = ScriptedChat(replies)
    monkeypatch.setattr(agent, "chat", fake)
    return fake


def test_tool_call_then_final_answer(monkeypatch):
    fake = use_chat(
        monkeypatch,
        [
            reply(tool_calls=[tool_call("c1", "search_reports", {"query": "net income", "company": "Halyk Bank"})]),
            reply(tool_calls=[tool_call("c2", "percent_change", {"old": 520000, "new": 610000})]),
            reply(
                "Net income grew by 17.31% [halyk-2023-p87-0], from 520,000 million KZT "
                "[halyk-2022-p79-0] in 2022 to 610,000 million KZT in 2023."
            ),
        ],
    )

    result = agent.answer("How did Halyk Bank's net income change from 2022 to 2023?")

    assert result.found is True
    assert result.numbers[0] == 17.31  # calculator result comes first
    assert 520000 in result.numbers and 610000 in result.numbers
    assert 2022 not in result.numbers  # years are not figures
    assert [(c.year, c.page) for c in result.citations] == [(2023, 87), (2022, 79)]
    assert "(Halyk Bank 2023, p. 87)" in result.text
    assert "[" not in result.text

    # the tool results were sent back to the model
    last_messages = fake.calls[-1]
    tool_messages = [m for m in last_messages if m["role"] == "tool"]
    assert len(tool_messages) == 2
    assert json.loads(tool_messages[1]["content"]) == {"result": 17.31}


def test_not_found_sets_found_false(monkeypatch):
    use_chat(
        monkeypatch,
        [
            reply(tool_calls=[tool_call("c1", "search_reports", {"query": "net income", "company": "Kcell"})]),
            reply("Not found in the reports. There is no Kcell data."),
        ],
    )

    result = agent.answer("What was Kcell's net income in 2023?")

    assert result.found is False
    assert result.citations == []
    assert result.numbers == []


def test_invented_citation_is_dropped(monkeypatch):
    use_chat(
        monkeypatch,
        [
            reply(tool_calls=[tool_call("c1", "search_reports", {"query": "net income", "year": 2023})]),
            reply("Net income was 610,000 million KZT [halyk-2023-p87-0] [halyk-2023-p999-0]."),
        ],
    )

    result = agent.answer("Halyk net income 2023?")

    assert [c.page for c in result.citations] == [87]
    assert "p999" not in result.text


def test_calculator_error_goes_back_to_model(monkeypatch):
    fake = use_chat(
        monkeypatch,
        [
            reply(tool_calls=[tool_call("c1", "ratio", {"numerator": 1, "denominator": 0})]),
            reply("Not found in the reports."),
        ],
    )

    agent.answer("ratio?")

    tool_message = [m for m in fake.calls[-1] if m["role"] == "tool"][0]
    assert "error" in json.loads(tool_message["content"])


def test_stops_after_max_steps(monkeypatch):
    loop_reply = reply(tool_calls=[tool_call("c", "search_reports", {"query": "net income"})])
    fake = use_chat(monkeypatch, [loop_reply] * (agent.MAX_STEPS + 1))

    result = agent.answer("Endless question")

    assert len(fake.calls) == agent.MAX_STEPS
    assert result.found is False


def test_uses_given_retriever(monkeypatch):
    class SpyRetriever(StubRetriever):
        def __init__(self):
            super().__init__()
            self.queries = []

        def search(self, query, k=5, company=None, year=None):
            self.queries.append((query, company, year))
            return super().search(query, k, company, year)

    spy = SpyRetriever()
    use_chat(
        monkeypatch,
        [
            reply(tool_calls=[tool_call("c1", "search_reports", {"query": "equity", "company": "Halyk Bank", "year": 2022})]),
            reply("Equity was 2,050,000 million KZT [halyk-2022-p77-0]."),
        ],
    )

    result = agent.answer("Halyk equity 2022?", retriever=spy)

    assert spy.queries == [("equity", "Halyk Bank", 2022)]
    assert result.citations[0].page == 77


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Grew 17.31% in 2023", [17.31]),
        ("See page 87 for 1,450,000 million KZT", [1450000.0]),
        ("Loss of -12.5 in 2024", [-12.5]),
        ("Net income was 693 435 million KZT", [693435.0]),
        ("Total assets 1 097 066 105 thousand KZT", [1097066105.0]),
        ("Total assets 1.097.066.105 thousand KZT", [1097066105.0]),
        ("No-break spaces: 693\u00a0435 and 1\u202f234", [693435.0, 1234.0]),
        ("Decimals stay: 17.31% and 5.8", [17.31, 5.8]),
        ("One dot is a decimal: 569.653", [569.653]),
        ("Space thousands with decimals: 12 345.67", [12345.67]),
        ("In 2023 net income was 693 435", [693435.0]),
        ("Loss of -1.234.567", [-1234567.0]),
        ("Two figures: 1,450,000 and 610 000", [1450000.0, 610000.0]),
    ],
)
def test_numbers_in_text(text, expected):
    assert agent._numbers_in_text(text) == expected


def test_empty_reply_is_retried_once(monkeypatch):
    fake = use_chat(
        monkeypatch,
        [
            reply(tool_calls=[tool_call("c1", "search_reports", {"query": "net income", "year": 2023})]),
            reply(content=""),
            reply("Net income was 610,000 million KZT [halyk-2023-p87-0]."),
        ],
    )

    result = agent.answer("Halyk net income 2023?")

    assert result.found is True
    assert result.text.startswith("Net income was 610,000")
    assert fake.calls[-1][-1] == {"role": "user", "content": agent.EMPTY_REPLY_NUDGE}


def test_two_empty_replies_give_not_found(monkeypatch):
    fake = use_chat(monkeypatch, [reply(content=None), reply(content="  ")])

    result = agent.answer("Halyk net income 2023?")

    assert len(fake.calls) == 2
    assert result.found is False
    assert result.text  # never an empty answer


def test_missing_index_gives_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "_default_retriever", REAL_DEFAULT_RETRIEVER)
    monkeypatch.setattr(agent, "INDEX_DIR", tmp_path / "no-index")
    REAL_DEFAULT_RETRIEVER.cache_clear()
    use_chat(monkeypatch, [])  # chat() must not be called at all

    with pytest.raises(FileNotFoundError, match=r"python -m scripts\.build_index"):
        agent.answer("Halyk net income 2023?")
    REAL_DEFAULT_RETRIEVER.cache_clear()


def test_default_retriever_is_opened_once(monkeypatch, tmp_path):
    opened = []

    class FakeRetriever:
        def __init__(self, index_dir):
            opened.append(index_dir)

    fake_module = ModuleType("src.ingest.retriever")
    fake_module.Retriever = FakeRetriever
    monkeypatch.setitem(sys.modules, "src.ingest.retriever", fake_module)
    monkeypatch.setattr(agent, "INDEX_DIR", tmp_path)
    REAL_DEFAULT_RETRIEVER.cache_clear()

    first = REAL_DEFAULT_RETRIEVER()
    second = REAL_DEFAULT_RETRIEVER()

    assert first is second
    assert opened == [tmp_path]
    REAL_DEFAULT_RETRIEVER.cache_clear()


def test_system_prompt_rules_for_real_reports(monkeypatch):
    fake = use_chat(monkeypatch, [reply("Not found in the reports.")])
    agent.answer("q")
    prompt = fake.calls[0][0]["content"]

    assert fake.calls[0][0]["role"] == "system"
    assert "thousands of tenge" in prompt and "millions of tenge" in prompt  # units
    assert "state the unit" in prompt
    assert "year=Y+1" in prompt and "comparative" in prompt  # X-1 column fallback
    assert "statement of profit or loss" in prompt  # main statements over notes
    assert "always pass company=" in prompt
    assert f'"{agent.NOT_FOUND}."' in prompt

