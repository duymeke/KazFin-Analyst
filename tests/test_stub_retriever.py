from src.agent.stub_retriever import STUB_CHUNKS, StubRetriever


def test_finds_net_income_with_scores():
    results = StubRetriever().search("net income")
    assert results
    assert all(r.score is not None for r in results)
    assert all("Net income" in r.text for r in results[:2])


def test_filters_by_company_and_year():
    results = StubRetriever().search("net income", company="halyk", year=2022)
    assert results
    assert all(r.year == 2022 and r.company == "Halyk Bank" for r in results)


def test_unknown_company_returns_nothing():
    assert StubRetriever().search("net income", company="Kcell") == []


def test_respects_k():
    assert len(StubRetriever().search("total", k=2)) <= 2


def test_does_not_mutate_stub_chunks():
    StubRetriever().search("net income")
    assert all(c.score is None for c in STUB_CHUNKS)
