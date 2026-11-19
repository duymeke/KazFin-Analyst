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

Needs **Python 3.11+** and git. All commands are run from the repository root.

### 1. Code and dependencies

macOS / Linux:

```bash
git clone https://github.com/duymeke/KazFin-Analyst.git
cd KazFin-Analyst
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
git clone https://github.com/duymeke/KazFin-Analyst.git
cd KazFin-Analyst
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell refuses to run `Activate.ps1`, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use `cmd` and `.venv\Scripts\activate.bat`.

Check the install (no API key, no data and no network needed):

```bash
pytest
```

### 2. LLM settings

Copy the template and fill it in (`cp` on macOS/Linux, `Copy-Item` in PowerShell):

```bash
cp .env.example .env
```

| Variable | What to put |
|---|---|
| `LLM_API_KEY` | your API key (e.g. from OpenRouter) |
| `LLM_BASE_URL` | any OpenAI-compatible endpoint; default `https://openrouter.ai/api/v1` |
| `LLM_MODEL` | a model id that **supports tool calling**; the model we used is in `DECISIONS.md` |

`.env` is in `.gitignore`: never commit it and never paste the key into code, logs or chats.

### 3. Report data and the search index

The PDFs and the index are not in git. Put the 9 report PDFs into `data/raw/` with the exact
names from `data/reports.json` (`halyk_2023.pdf`, …); where to get them is in `data/README.md`.

The statement pages in the PDFs are images, so they need OCR before indexing. OCR needs
`ocrmypdf` with Tesseract and Ghostscript:

```bash
brew install ocrmypdf            # macOS (installs Tesseract and Ghostscript too)
sudo apt install ocrmypdf        # Debian/Ubuntu
```

On Windows, follow the ocrmypdf installation guide for Windows, or simply copy a teammate's
`data/ocr/` folder (the OCR copies) next to `data/raw/` and skip the OCR step.

```bash
python -m scripts.ocr_reports    # OCR image-only pages -> data/ocr/  (about 1-2 minutes)
python -m scripts.build_index    # parse the PDFs and build the index in data/index/
```

The first `build_index` downloads ChromaDB's embedding model (all-MiniLM-L6-v2, about 80 MB)
once. Rebuild the index whenever a PDF, `data/reports.json` or `data/ocr_fixes.json` changes.

## Usage

### Web interface

```bash
streamlit run src/app/streamlit_app.py
```

The browser opens at http://localhost:8501. Type a question, optionally pick a company, and the
answer shows its sources as "Company, year, page N" with the quoted text under each one. If the
data is not in the reports, the app says so instead of guessing. Stop the server with `Ctrl+C`.

**Demo mode** (no API key and no index needed, answers are clearly marked as FAKE):

```bash
USE_FAKE_AGENT=1 streamlit run src/app/streamlit_app.py                 # macOS / Linux
```

```powershell
$env:USE_FAKE_AGENT="1"; streamlit run src/app/streamlit_app.py          # Windows PowerShell
```

In PowerShell the variable stays set in that terminal; remove it with
`Remove-Item Env:USE_FAKE_AGENT` before running the real agent.

### Command line

```bash
python -m scripts.ask "How did Halyk Bank's net income change from 2022 to 2023?"
python -m scripts.ask -v "..."                                  # also print every tool call
python -m scripts.search "net income" --company Halyk --year 2023 -k 5   # retrieval only, no LLM
```

### Common errors

| Message | Fix |
|---|---|
| `LLM_API_KEY is not set` / "The LLM is not configured" | create `.env` (step 2 of Setup) |
| `Index not found` / "The search index is not built yet" | build the index (step 3 of Setup) |
| empty answers or HTTP 429 from the provider | the model is overloaded or not suited; change `LLM_MODEL` (see `DECISIONS.md`) |

## Data

Public annual reports downloaded manually from [kase.kz](https://kase.kz) and the companies' investor relations pages. The PDFs are not committed to this repository; see `data/README.md` for the list of files and the OCR step.

## Project files

- `PLAN.md`: project plan (written before the code)
- `AGENTS.md`: instructions for the coding agent
- `DECISIONS.md`: key decisions and agent mistakes
- `REFLECTION.md`: reflection on working with the agent (by code freeze)
- `agent-logs/`: key agent sessions
- `eval/`: evaluation of the AI feature

## Libraries and datasets used

_Will be listed here as they are added._