PLAN: KazFin Analyst

Written before the code, on 7 November 2026. Changes to this plan are recorded in DECISIONS.md.

1. Problem and user

Annual reports of companies listed on KASE are 200–300 page PDFs. Finding a single figure, or comparing it across years or companies, takes a long time.

Users: economics students, beginner investors, junior analysts.

2. AI feature
RAG over annual reports: split PDFs into chunks (text + tables), embed them, retrieve the most relevant ones for a question.
Tool use: the LLM calls Python functions to compute financial ratios (ROE, ROA, net margin, debt-to-equity, YoY growth). It does not do the arithmetic itself.
Citations: every answer includes the source document and page number.
Refusal: if the data is not in the reports, the assistant says so instead of guessing.
3. Evaluation
A test set of 30–40 questions with correct answers calculated by hand from the reports.
Metrics:
Numeric accuracy: answer within ±1% of the correct value
Citation accuracy: the cited page actually contains the figure
Correct refusal rate: for questions with no answer in the data
Baseline: the same LLM without RAG and tools. We report how much RAG + tools improve the results.
4. Scope
MVP (by checkpoint, Mon 16 Nov)
3 companies, 2–3 years of annual reports each
PDF → chunks → vector index
Question → retrieval → LLM answer with citation
Simple web UI (Streamlit)
Full version (by code freeze, Sun 13 Dec)
5 companies
Ratio calculator tools
Evaluation script and results
Tests
Stretch goals
Compare two companies side by side with a chart
Reports in Kazakh
5. Tech stack (draft)
Part	Choice
Language	Python 3.11+
PDF parsing	PyMuPDF / pdfplumber (tables)
Embeddings + vector store	sentence-transformers or API embeddings + ChromaDB
LLM	via API (provider TBD), key in .env
UI	Streamlit
Tests	pytest
Coding agent	Claude Code (paid)
6. Who does what
Member	Responsibility
Suleimenov Dinmukhamed	PDF ingestion, chunking, retrieval
Duisalip Berikzhan	Agent loop, ratio tools, prompts
Boranbai Zangar	Streamlit UI, evaluation set and script, README

Everyone commits from their own account and saves their own agent logs.

7. Timeline
Week	Dates	Goal
1	9–15 Nov	Download reports, parse PDFs, first end-to-end version
2	16–22 Nov	Checkpoint 16 Nov. Improve retrieval, add ratio tools
3	23–29 Nov	Evaluation set (30–40 questions), baseline comparison
4	30 Nov–6 Dec	More companies, tests, UI polish
5	7–13 Dec	README from scratch, REFLECTION.md, tag v1.0 on 13 Dec
8. Risks
Risk	Mitigation
Tables in PDFs parse badly	Test parsing on week 1; limit to companies with clean PDFs
LLM invents numbers	Tools for arithmetic, mandatory citations, refusal when no data
Free API limits run out	Plan sessions, use a cheaper model for routine edits