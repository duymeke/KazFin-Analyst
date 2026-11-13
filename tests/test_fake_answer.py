"""fake_answer() must follow the Answer contract from src/models.py."""

from src.app.fake_answer import fake_answer
from src.models import Answer, Citation


def test_fake_answer_has_text_citations_and_numbers():
    result = fake_answer("How did Halyk Bank's net income change?")
    assert isinstance(result, Answer)
    assert result.found is True
    assert result.text.startswith("[FAKE]")
    assert len(result.citations) == 2
    assert all(isinstance(c, Citation) for c in result.citations)
    assert result.numbers


def test_fake_answer_not_found_branch():
    result = fake_answer("Something that is not found")
    assert result.found is False
    assert result.citations == []


def test_fake_answer_returns_independent_copies():
    first = fake_answer("q")
    first.citations[0].page = 1
    first.numbers.append(1.0)
    second = fake_answer("q")
    assert second.citations[0].page == 87
    assert 1.0 not in second.numbers
