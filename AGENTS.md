# AGENTS.md

Instructions for the coding agent (Claude Code) working in this repository.
Read `PLAN.md` and `src/models.py` before starting any task.

## Project

KazFin Analyst: an assistant that answers questions about annual reports of
companies listed on KASE. It retrieves passages from the PDFs (RAG), computes
financial ratios through tool calls, and cites the company, year and page for
every figure. If the data is not in the reports, it says so.

## Layout and owners

| Path | What | Owner |
|---|---|---|
| `src/models.py` | Shared data contract: `Chunk`, `Citation`, `Answer` | Dinmukhamed |
| `src/ingest/` | PDF parsing, chunking, vector index, `Retriever.search()` | Dinmukhamed |
| `src/agent/` | LLM client, calculator tools, agent loop, prompts | Berikzhan |
| `src/app/` | Streamlit UI | Zangar |
| `eval/` | Test questions, metrics, evaluation script, baseline | Zangar |
| `scripts/` | Command-line entry points | owner of the module it calls |
| `tests/` | pytest tests, one file per module | owner of the module |

Work only inside the folders of the person running the session, unless they ask otherwise.

## Contract (do not break)

- **Do not change `src/models.py`.** Changes need agreement of all three members.
- `Retriever().search(query, k=5, company=None, year=None) -> list[Chunk]` (`src/ingest/retriever.py`)
- `answer(question, retriever=None) -> Answer` (`src/agent/agent.py`)
- `chat(messages, tools=None) -> response` (`src/agent/llm.py`)
- Until a teammate's module exists, use a stub with the same interface
  (`src/agent/stub_retriever.py`, `src/app/fake_answer.py`).

## Rules

- Python 3.11+. Type hints and short docstrings on public functions.
- **The LLM never does arithmetic.** Every computed number comes from a function in `src/agent/tools.py`.
- **Never invent figures or page numbers**, in code, prompts, tests or eval data. Citations are built only from chunks the retriever actually returned.
- **Secrets only in `.env`** (see `.env.example`). Never print, log or commit API keys. Never commit `.env`.
- All LLM calls go through `src/agent/llm.py` (openai SDK with `LLM_BASE_URL`), so the provider can change without code changes.
- Add every new dependency to `requirements.txt`.
- Tests use pytest and **must not need network or an API key** (mock `chat()`).
- Run `pytest` before saying a task is done, and show the output.
- Small commits with clear messages ("Add ratio calculator tools", not "update").
- Each member works on their own branch (`ingest/...`, `agent/...`, `app/...`) and merges to `main` through a Pull Request.
- Before writing code, show a short plan and wait for OK. If the plan or contract is unclear, ask instead of guessing.

## Commands

```bash
pip install -r requirements.txt
pytest
python -m scripts.ask "How did Halyk Bank's net income change from 2022 to 2023?"
```
