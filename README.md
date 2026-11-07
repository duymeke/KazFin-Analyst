# KazFin Analyst

AI assistant for analyzing annual reports of Kazakhstani listed companies (KASE).

> 🚧 Work in progress — CSS4007 Final Project (Narxoz University).

## What it does

Annual reports of Kazakhstani companies are hundreds of pages long, so finding and comparing key figures takes hours. KazFin Analyst lets economics students, beginner investors and analysts ask questions in plain language, for example:

- "How did Halyk Bank's net profit change from 2022 to 2024?"
- "What is KEGOC's debt-to-equity ratio in 2023?"

The assistant:
1. **Retrieves** the relevant passages and tables from the reports (RAG).
2. **Calculates** financial ratios through tool calls instead of letting the LLM do the arithmetic.
3. **Cites** the source document and page for every number.

## Team

| Member | Area |
|---|---|
| Suleimenov Dinmukhamed | PDF ingestion, retrieval (RAG) |
| Duisalip Berikzhan | Agent, ratio calculator tools, prompts |
| Boranbai Zangar | UI, evaluation set, README |

## Setup

_Coming soon. Setup instructions will work on a clean machine by the code freeze._

```bash
git clone <repo-url>
cd kazfin-analyst
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then put your API key in .env
```

## Data

Public annual reports downloaded manually from [kase.kz](https://kase.kz) and the companies' investor relations pages. The PDFs are not committed to this repository; see `data/README.md` (to be added) for the list of sources.

## Project files

- `PLAN.md`: project plan (written before the code)
- `AGENTS.md`: instructions for the coding agent
- `DECISIONS.md`: key decisions and agent mistakes
- `REFLECTION.md`: reflection on working with the agent (by code freeze)
- `agent-logs/`: key agent sessions
- `eval/`: evaluation of the AI feature

## Libraries and datasets used

_Will be listed here as they are added._