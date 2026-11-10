from src.models import Answer, Chunk, Citation


def test_chunk_defaults():
    chunk = Chunk(
        id="kegoc-2023-p12-0",
        text="Net profit for 2023 was 50.1 bn KZT.",
        company="KEGOC",
        year=2023,
        source_file="kegoc_2023.pdf",
        page=12,
    )
    assert chunk.kind == "text"
    assert chunk.score is None


def test_citation_defaults():
    citation = Citation(company="KEGOC", year=2023, source_file="kegoc_2023.pdf", page=12)
    assert citation.snippet == ""


def test_answer_with_citation():
    citation = Citation(
        company="KEGOC", year=2023, source_file="kegoc_2023.pdf", page=12, snippet="Net profit"
    )
    answer = Answer(text="Net profit was 50.1 bn KZT.", citations=[citation], numbers=[50.1])
    assert answer.found is True
    assert answer.citations[0].page == 12
    assert answer.numbers == [50.1]


def test_answer_lists_are_not_shared():
    a = Answer(text="a")
    b = Answer(text="b")
    a.citations.append(Citation(company="X", year=2023, source_file="x.pdf", page=1))
    assert b.citations == []
