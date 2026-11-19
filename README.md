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

## Evaluation

We measure how well the AI feature works on a test set of questions whose correct answers were
read **by hand** from the PDFs (`eval/questions.json`):

| Type | What is checked |
|---|---|
| `numeric` | a single figure or a ratio; correct if a number in the answer is within ±1% of the gold value |
| `text` | e.g. the auditor; correct if the gold keywords appear in the answer |
| `not_found` | data that is not in the reports; correct if the assistant refuses instead of guessing |

For `numeric` and `text` questions we also check **citation accuracy**: the answer must cite the
file and page where the gold figure was read. Gold values of ratios are computed from the
hand-read base figures by the same calculator functions the agent uses. The design of the set
(types, units, the comparative-year rule) is explained in `DECISIONS.md`.

**Baseline:** the same LLM with no retrieval and no tools, asked the same questions. The
difference between the two runs is what RAG + tools add.

```bash
python -m eval.check_questions        # validate the question file, show what is still TODO
python -m eval.compute_gold           # compute gold values of ratio questions from their inputs
python -m eval.run_eval               # the full assistant (needs .env and the index)
python -m eval.run_eval --baseline    # the same LLM without RAG and tools (needs .env)
python -m eval.run_eval --fake        # fake answers: tests the pipeline offline
python -m scripts.eval_retrieval      # retrieval only: does search rank the right page high?
```

`run_eval` skips questions that still contain `TODO`, prints accuracy overall, per company and
per question type, and saves every answer to `eval/results/<mode>-<timestamp>.json`. The results
and their analysis are in `eval/results.md`.

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

| Library | Used for |
|---|---|
| [openai](https://github.com/openai/openai-python) | LLM client for any OpenAI-compatible API (`src/agent/llm.py`) |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | reading LLM settings from `.env` |
| [PyMuPDF](https://pymupdf.readthedocs.io/) | reading PDF text and words with positions |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | PDF page and table structure |
| [ChromaDB](https://www.trychroma.com/) | vector index; its default embedding model all-MiniLM-L6-v2 |
| [Streamlit](https://streamlit.io/) | web interface |
| [pytest](https://pytest.org/) | tests |
| [OCRmyPDF](https://ocrmypdf.readthedocs.io/) + Tesseract | OCR of image-only statement pages (system tool, not in `requirements.txt`) |

**Data:** audited IFRS consolidated financial statements of Halyk Bank, KEGOC and Kcell for
2022–2024, public documents from the companies' investor-relations pages and [kase.kz](https://kase.kz).
The list of files and their sources is in `data/README.md`.

The LLM is used through an API and configured in `.env`; it is not part of the repository.