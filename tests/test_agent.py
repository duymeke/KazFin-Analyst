"""Agent loop tests with a scripted fake chat(): no network, no API key."""

import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from src.agent import agent
from src.agent.stub_retriever import StubRetriever
from src.models import Chunk

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


def test_invented_citation_is_sent_back_once_then_dropped(monkeypatch):
    bad = "Net income was 610,000 million KZT [halyk-2023-p87-0] [halyk-2023-p999-0]."
    fake = use_chat(
        monkeypatch,
        [
            reply(tool_calls=[tool_call("c1", "search_reports", {"query": "net income", "year": 2023})]),
            reply(bad),
            reply(bad),  # the model repeats it: the invented id is dropped
        ],
    )

    result = agent.answer("Halyk net income 2023?")

    nudge = fake.calls[2][-1]
    assert nudge["role"] == "user" and "halyk-2023-p999-0" in nudge["content"]
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
        ("For the year ended 31 December 2023: 693,436", [693436.0]),
        ("Balance at December 31, 2024 was 769,921,817", [769921817.0]),
        ("Growth of 31% in 2024", [31.0]),
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



# --- guards found in the first run on the real index (DECISIONS, 2026-11-18) ---


def test_answer_without_search_is_sent_back(monkeypatch):
    # Kcell case: the model answered from memory in step 1, citing an id it never got
    fake = use_chat(
        monkeypatch,
        [
            reply("Revenue rose from 627,617 to 704,544 million KZT [kcell-2024-p5-0]."),
            reply(tool_calls=[tool_call("c1", "search_reports", {"query": "net income", "company": "Halyk Bank"})]),
            reply("Net income was 610,000 million KZT [halyk-2023-p87-0]."),
        ],
    )

    result = agent.answer("Halyk net income 2023?")

    assert fake.calls[1][-1] == {"role": "user", "content": agent.NO_SEARCH_NUDGE}
    assert result.found is True
    assert [c.page for c in result.citations] == [87]


def test_two_answers_without_search_give_not_found(monkeypatch):
    memory = reply("Revenue rose from 627,617 to 704,544 million KZT, +12.3%.")
    use_chat(monkeypatch, [memory, memory])

    result = agent.answer("How did Kcell's revenue change from 2022 to 2024?")

    assert result.found is False
    assert result.text == agent.NO_SEARCH_ANSWER
    assert result.numbers == [] and result.citations == []


def test_not_found_without_search_is_accepted(monkeypatch):
    # Kaspi case: a company we do not have, no search needed
    fake = use_chat(monkeypatch, [reply("Not found in the reports.")])

    result = agent.answer("What was Kaspi's net income in 2023?")

    assert len(fake.calls) == 1
    assert result.found is False


def test_figures_without_valid_citation_give_not_found(monkeypatch):
    # KEGOC case: the only source of the figure was an invented id
    bad = "Total equity was 769,921,817 thousand tenge [kegoc-2024-p13-3]."
    use_chat(
        monkeypatch,
        [
            reply(tool_calls=[tool_call("c1", "search_reports", {"query": "total equity", "company": "KEGOC"})]),
            reply(bad),
            reply(bad),
        ],
    )

    result = agent.answer("What was KEGOC's total equity at the end of 2024?")

    assert result.found is False
    assert result.text == agent.NO_SOURCE_ANSWER
    assert result.citations == [] and result.numbers == []


def test_search_limit_is_enforced_in_code(monkeypatch):
    class CountingRetriever(StubRetriever):
        calls = 0

        def search(self, query, k=5, company=None, year=None):
            CountingRetriever.calls += 1
            return super().search(query, k, company, year)

    searches = [
        reply(tool_calls=[tool_call(f"c{i}", "search_reports", {"query": "net income"})])
        for i in range(agent.MAX_SEARCHES + 1)
    ]
    fake = use_chat(monkeypatch, searches + [reply("Not found in the reports.")])

    agent.answer("Halyk net income 2023?", retriever=CountingRetriever())

    assert CountingRetriever.calls == agent.MAX_SEARCHES
    last_tool = [m for m in fake.calls[-1] if m["role"] == "tool"][-1]
    assert json.loads(last_tool["content"]) == {"error": agent.SEARCH_LIMIT_ERROR}


# --- figures must come from chunks or calculators (second real run, DECISIONS 2026-11-18) ---

KEGOC_P9 = Chunk(
    id="kegoc-2024-p9-1",
    text=(
        "Units: In thousands of tenge\n"
        "Total liabilities   327,144,288   316,065,873\n"
        "Total equity and liabilities   1,097,066,105   1,001,785,007"
    ),
    company="KEGOC",
    year=2024,
    source_file="kegoc_2024.pdf",
    page=9,
)


class OneChunkRetriever:
    def __init__(self, chunk):
        self.chunk = chunk

    def search(self, query, k=5, company=None, year=None):
        return [self.chunk]


def kegoc_search():
    return reply(tool_calls=[tool_call("s1", "search_reports", {"query": "total equity", "company": "KEGOC", "year": 2024})])


def test_own_subtraction_is_sent_back_then_calculator_is_accepted(monkeypatch):
    fake = use_chat(
        monkeypatch,
        [
            kegoc_search(),
            reply(
                "Equity = 1,097,066,105 - 327,144,288 = 769,921,817 thousand KZT "
                "(about 769.9 billion) [kegoc-2024-p9-1]."
            ),
            reply(tool_calls=[tool_call("d1", "difference", {"minuend": 1097066105, "subtrahend": 327144288})]),
            reply("Total equity was 769,921,817 thousand KZT [kegoc-2024-p9-1]."),
        ],
    )

    result = agent.answer("What was KEGOC's total equity at the end of 2024?", retriever=OneChunkRetriever(KEGOC_P9))

    nudge = fake.calls[2][-1]["content"]
    assert "769,921,817" in nudge and "769.9" in nudge  # own result and unit conversion
    assert "1,097,066,105" not in nudge  # figures copied from the chunk are fine
    assert result.found is True
    assert result.numbers[0] == 769921817
    assert [c.page for c in result.citations] == [9]


def test_own_arithmetic_twice_gives_not_found(monkeypatch):
    own = reply("Equity = 1,097,066,105 - 327,144,288 = 769,921,817 thousand KZT [kegoc-2024-p9-1].")
    use_chat(monkeypatch, [kegoc_search(), own, own])

    result = agent.answer("KEGOC equity 2024?", retriever=OneChunkRetriever(KEGOC_P9))

    assert result.found is False
    assert result.text == agent.UNCHECKED_ANSWER
    assert result.numbers == []


def test_rounded_calculator_result_is_accepted(monkeypatch):
    fake = use_chat(
        monkeypatch,
        [
            reply(tool_calls=[tool_call("c1", "search_reports", {"query": "net income", "company": "Halyk Bank"})]),
            reply(tool_calls=[tool_call("c2", "percent_change", {"old": 520000, "new": 610000})]),
            reply("Net income grew by about 17.3% [halyk-2023-p87-0]."),
        ],
    )

    result = agent.answer("Halyk net income growth?")

    assert len(fake.calls) == 3  # no nudge
    assert result.found is True


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("Retained earnings 64,089,351 [x]", []),  # in the chunk
        ("A loss of -930 [x]", []),  # the chunk writes losses as (930)
        ("Equity 769,921,817 [x]", [769921817.0]),  # own subtraction
        ("About 64.1 billion [x]", [64.1]),  # own unit conversion
        ("See note 14 and item 3 [x]", []),  # small whole numbers are not checked
        ("Rose by 12.26% [x]", []),  # calculator result
        ("Rose by 12.3% [x]", []),  # calculator result, rounded
        ("Rose by 12.4% [x]", [12.4]),
        ("Total 1,001,785,007 [x]", []),  # OCR wrote it as 1,001.785.007
    ],
)
def test_unchecked_figures(answer, expected):
    chunk = Chunk(
        id="x",
        text="Retained earnings   64,089,351   48,259,455\nTreasury shares   (930)\nTotal   _1,001.785.007",
        company="KEGOC",
        year=2024,
        source_file="kegoc_2024.pdf",
        page=9,
    )
    assert agent._unchecked_figures(answer, {"x": chunk}, [12.26]) == expected
