# DECISIONS.md

Important decisions, including where the agent was wrong and how we noticed.

## 2026-11-11 · Agent layer (Berikzhan)

### Citations only from chunks the retriever returned
The LLM marks each figure with a chunk id like `[halyk-2023-p87-0]`. `agent.py` keeps only ids
that `search_reports` actually returned and drops any other id, so the model cannot invent a page.

### The agent recommended a broken model (agent was wrong)
Claude Code picked `nvidia/nemotron-3-ultra-550b-a55b:free` from the OpenRouter model list
by its description only, without testing it. `scripts/ask.py` then printed an empty answer.
**How we noticed:** `ask.py -v` showed "empty reply from the model"; a raw API call showed that
even "Say hello" returned `content: null` and garbage text in the `reasoning` field.
**Fix:** switched models. `google/gemma-4-31b-it:free` gave HTTP 429 (free tier overloaded).
We now use `baidu/ernie-5.5-flash-preview:free`. It is a preview model and may be removed,
so the model is configured only in `.env` (`LLM_MODEL`) and can be changed without code changes.

### Empty model replies were shown as an empty answer (bug in our code)
The first version of `agent.py` treated a reply with no text and no tool calls as a final
answer, so the user saw a blank line. **Fix:** the agent asks the model once more; if the
reply is still empty it returns `found=False` with a clear message. Added `-v` to
`scripts/ask.py` to print every tool call, and two tests for this case.

### API key pasted into the agent chat (our mistake)
An OpenRouter key was pasted into the Claude Code chat by accident. The agent warned about it.
**Fix:** the key was deleted on OpenRouter and a new one created; the key was removed from the
exported agent log before committing. Keys go only into `.env`.

### Commit author stays the student, not the agent
A hook in the agent environment asked to rewrite commits with the author "Claude". We refused:
the course grades each member by their own commits, so commits are authored by AdamNarxoz.

### Manual check with stub data (model: baidu/ernie-5.5-flash-preview:free)
| Question | Result |
|---|---|
| Halyk net income change 2022→2023 | 17.31% via `percent_change`, cites p. 79 and p. 87 ✅ |
| Halyk debt-to-equity 2023 | 5.8 via `debt_to_equity`, cites p. 85 ✅ |
| Kcell net income 2023 (not in stub) | "Not found in the reports", no figures ✅ |

## 2026-11-13 · UI and evaluation (Zangar)

### Company filter is passed inside the question
`answer(question, retriever=None)` has no `company` parameter, and the contract is fixed.
When a company is selected in the UI, `src/app/backend.py` appends `(Company: <name>)` to the
question; the agent then passes it to `search_reports(company=...)`. If the contract later gets
a `company` argument, only `with_company()` in the UI changes.

### UI logic is separate from Streamlit
`src/app/backend.py` holds the choice of real/fake agent, error handling and formatting, so it is
tested with pytest without starting Streamlit. `streamlit_app.py` adds the repo root to
`sys.path`, because `streamlit run` only puts the script's own folder there.

### Errors in the UI never show a stack trace or the key
`LLMConfigError` (matched by name, so the UI does not import the agent package) becomes a short
hint about `.env`; any other error shows only its type, not the message, because provider
error messages can contain request details.

### Evaluation rules
- Gold values in `eval/questions.json` are filled in **by hand** from the PDFs. The template has
  `"TODO"` in `gold_answer`, `gold_value`, `source_page`; such questions are skipped by
  `run_eval` (agent and baseline). `--fake` keeps them, only to test the pipeline.
- Metrics apply per type: numeric accuracy to `numeric`, citation accuracy to `numeric` and
  `text`, not-found accuracy to `not_found`. Numeric tolerance is 1% relative; for a gold value
  of 0 it is absolute (1% of 0 would be 0).
- Baseline = the same `chat()` with no retrieval and no tools. It has no sources, so its
  citation accuracy is 0 by design; the comparison that matters is numeric and not-found.
- A missing LLM key stops the whole run with one message instead of failing every question.
- Results of real runs (`eval/results/agent-*.json`, `baseline-*.json`) are committed for the
  defence; `fake-*.json` are ignored in git.
- Source file names in the template (`halyk_2023.pdf`, ...) follow the example in
  `src/models.py`; they must be checked against the real names used by ingest.

## 2026-11-17 · PDF ingestion and retrieval (Dinmukhamed)

### Audited financial statements instead of full annual reports
PLAN.md speaks of annual reports (200–300 pages). In `data/raw/` we use the audited consolidated
IFRS financial statements instead (57–163 pages each). They contain the figures our questions
need (net income, equity, liabilities), the figures are audited, and all three companies use the
same IFRS statements, so the same questions work for every company. The management part of the
annual report (strategy, ESG, photos) adds pages but no figures we evaluate.

### `kegoc_2022.pdf` was the 2024 report (wrong file downloaded)
`kegoc_2022.pdf` and `kegoc_2024.pdf` have different hashes but the same size (1,776,276 bytes).
**How we noticed:** the first survey of the PDFs showed the same page count (63), the same empty
pages and the same sentences in both files. Comparing the text page by page: all 63 pages are
identical, and the statements are "as at 31 December 2024". Indexing it as 2022 would have made
the agent cite 2024 figures as 2022 figures. **Fix:** the file has a `skip` reason in
`data/reports.json` and is not indexed; `build_index` prints the reason on every run. It also
now warns when two files have the same text. The real 2022 report still has to be downloaded.

### `kcell_2023.pdf` is a scan
Only page 1 has a text layer; pages 2–58 are images (the PDF was made by "eCopy ShareScan", a
scanner). **How we noticed:** the parse quality report of `build_index`
("no text layer, image only (scanned?): page(s) 2-58"). **Fix for now:** only page 1 is indexed
(1 chunk), so the agent answers "Not found in the reports" for Kcell 2023 instead of guessing.

### The primary statements are image-only in every file
The signed pages (statement of financial position, profit or loss, comprehensive income) are
images without text in all Halyk, KEGOC and Kcell files: e.g. Halyk 2023 pages 10–13, 15, 17,
KEGOC 2024 page 9 (the equity and liabilities half of the balance sheet). Only the statement of
changes in equity, the cash flow statement and the notes have text.
**How we noticed:** the parse quality report listed image-only pages right after the auditor's
report in every file, and the test searches looked wrong: "net income" for Halyk 2023 returned
notes pages 145, 153, 36, 27; the real "Net income 693,435" row (page 14, changes in equity)
ranked only 15th. "total equity" for KEGOC 2024 could not find the row at all, because page 9
is an image. **Fix:** not hidden: the pages are listed in `data/README.md` and printed by
`build_index`. The real fix is OCR (below).

### Page text rebuilt as rows instead of trusting pdfplumber tables
The plan was to get tables from `pdfplumber.extract_tables()`. On the statement pages it found
0 tables, because these tables have no ruling lines; over all files only 28 of 2,271 chunks are
tables. PyMuPDF's plain text put every cell on its own line, so a label ("Total assets") and its
numbers ended up far apart. **How we noticed:** printing the text and tables of one statement
page per company before writing the parser. **Fix:** the parser groups words by their vertical
position into visual rows and joins columns with wide gaps, e.g.
`Total assets   1.097.066.105   1.001.785.007`. Page text is always indexed, even when pdfplumber
finds a table on the page; good pdfplumber tables are added as extra `kind="table"` chunks, and
broken ones (too small or more than 60% empty cells) are reported and skipped.

### Units prefixed to every chunk of a page
Statement pages give the unit once at the top: "(Millions of Kazakhstani Tenge)" for Halyk,
"In millions of tenge" for Kcell, "In thousands of tenge" for KEGOC. After splitting a page
into ~1000-character chunks, only the first chunk had the unit, so a KEGOC figure could be read
as millions (a 1000x error). **Fix:** the parser finds the unit line on the page and starts every
other chunk of that page with `Units: <unit line>`. The unit must start a row and be followed by
the end of the row or a column gap, so sentences like "thousands of tenge were paid" do not
match. Covered by tests. Note for the agent: KEGOC writes `1.097.066.105` with dots as thousands
separators.

### Next: OCR for the image-only pages
Without OCR the index has no balance sheet and no income statement, so questions like
"KEGOC debt-to-equity" cannot be answered from the primary statements. **Decision:** run
`ocrmypdf --skip-text` on the PDFs before parsing, instead of `pytesseract`:
- `--skip-text` OCRs only pages without a text layer; pages that already have text stay as they are.
- The output PDF has the same pages in the same order, so page numbers, chunk ids and citations
  still match the original PDF.
- It adds an invisible text layer that the current parser reads as it is, so we need no own code
  to render pages to images and put the OCR text back on the right page, as `pytesseract` would need.

`ocrmypdf` needs Tesseract and Ghostscript installed, which goes into the README setup. OCR can
misread digits, so for every eval question the figure on a cited OCR page is checked by hand
against the PDF.

## 2026-11-17 · OCR of image-only pages (Dinmukhamed)

### OCR copies in `data/ocr/`, citations still point to the original PDF
`scripts/ocr_reports.py` runs `ocrmypdf --skip-text -l eng --output-type pdf` on every file in
`reports.json` and writes `data/ocr/<file>` (not in git). `--output-type pdf` skips the default
PDF/A conversion, which is slower and rewrites pages that already have text. `build_index`
parses the OCR copy when it exists, but passes the original file name to the parser
(`source_name`), and the page order does not change, so chunk ids and citations are the same as
before. Covered by tests with a fake raw PDF and a fake OCR copy.

### Results
OCR of all 9 files took about 1 min 20 s. OCRed pages per file: Halyk 7 / 7 / 7, KEGOC 7 / 5 / 9,
Kcell 5 / 57 / 10 (2022 / 2023 / 2024). **No page is left without text.** The index grew from
2,271 to 2,866 chunks (2,838 text, 28 table); 229 of the new ones are `kegoc_2022.pdf`, which is
indexed again. `build_index` took 162 s.

Test searches, before → after:
- "net income", Halyk 2023: the profit or loss statement (page 12, "NET INCOME 693,436") was
  not in the index → now rank 4. Rank 1 is still a notes page (145).
- "total equity", KEGOC 2024: page 9 (equity and liabilities) could not be found → now rank 4.
  The page has no "Total equity" label (the equity total is an unlabelled row), which explains
  part of the weak ranking. Improving the ranking is a separate retrieval task.

### `halyk_2024.pdf`: ocrmypdf exit code 4 (our check, not a crash)
ocrmypdf wrote the output but its qpdf check found bad `0 0 R` references and it exited with 4
("output is invalid"). Rewriting the input with qpdf or PyMuPDF first did not help. All 158
pages were there, and the pages that already had text were unchanged. **Decision:** exit code 4
is accepted only after our own check (`check_pages`): same page count and identical text on
every page that had text before; otherwise the file fails. The script prints a warning.

### OCR misread 4 figures on the KEGOC 2024 balance sheet (how we noticed)
We added up the subtotals in the OCR text of `kegoc_2024.pdf` page 9 and compared them with the
totals, then compared the rendered page image. Three sums did not match. Wrong digits
(OCR → image): total equity and liabilities 2024 `1,087,066,105` → `1.097.066.105`, retained
earnings 2023 `8,259,455` → `48.259.455`, trade and other payables 2024 `17,873,658` →
`17.573.658`, contract liabilities 2024 `2,008,832` → `2.006.832`. Halyk 2023 page 12 (profit or
loss) has no wrong digits; all its sums match. **Consequence:** an OCR page is never trusted
without a check. For every eval question the figure on a cited OCR page is checked against the
image, and the sums of the statement are checked where possible. Where a figure also appears in
the text layer (e.g. "Total assets 1.097.066.105" on page 8), the text layer is the reference.

### Dot thousands separators normalized to commas
The parser rewrites numbers with two or more dot-separated groups of exactly 3 digits
(`1.097.066.105` → `1,097,066,105`) in page text and table cells, so all companies use the same
format. Numbers with one dot are not changed, because they may be decimals (`63.65`, `13.5`).
This leaves some KEGOC thousands with a dot (`569.653`, book value per share `2.780` tenge).
On OCR pages Tesseract also reads some dots as commas and mixes them (`148,922.757`,
`1,001.785.007`, `5.588895`); the rule does not touch these mixed numbers. If they turn out to
hurt answers, a rule for mixed separators is the next step.

### `kegoc_2022.pdf` replaced, `skip` removed
The new file has 56 pages (the 2024 report has 63), the statements are "for the year ended
31 December 2022" with 2021 comparatives, no "31 December 2024" appears, and no page is identical
to `kegoc_2023.pdf` or `kegoc_2024.pdf`. `ocr_reports` now also redoes a file when the raw PDF is
newer than its OCR copy, so a replaced report does not keep an old OCR copy.
