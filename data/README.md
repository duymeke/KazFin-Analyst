# Data

## What the files are

`data/raw/` holds the audited consolidated financial statements (IFRS, in English) of three
companies listed on KASE, for the years 2022–2024. Each PDF contains the independent auditor's
report, the primary statements and the notes.

**The PDFs, their OCR copies and the vector index are not in git** (`data/raw/`, `data/ocr/`
and `data/index/` are in `.gitignore`). Download the PDFs from the URLs below into `data/raw/`,
then run:

```bash
python -m scripts.ocr_reports   # add a text layer to image-only pages -> data/ocr/
python -m scripts.build_index   # parse and index (reads data/ocr/ when it exists)
```

## OCR step

The signed primary statements are image-only pages in every PDF, and `kcell_2023.pdf` is a full
scan. `scripts/ocr_reports.py` runs, for every file in `reports.json`:

```bash
ocrmypdf --skip-text -l eng --output-type pdf data/raw/<file> data/ocr/<file>
```

- `--skip-text` OCRs only pages without a text layer; all other pages are kept as they are.
- The copy has the same pages in the same order, so chunk ids and citations (file name, page)
  still refer to the original PDF in `data/raw/`.
- Files already in `data/ocr/` are skipped, unless the raw PDF is newer than its copy (it was
  replaced); `--force` redoes all. The script prints how many pages were OCRed per file and
  how many are still without text.
- `build_index` reads `data/ocr/<file>` when it exists, otherwise `data/raw/<file>`
  (`--no-ocr` forces raw). So after replacing a raw PDF, run `ocr_reports` again before
  `build_index`, otherwise the old OCR copy is indexed.
- Needs `ocrmypdf` with Tesseract (English) and Ghostscript: `brew install ocrmypdf` (macOS),
  `sudo apt install ocrmypdf` (Debian/Ubuntu). The whole set takes about 1–2 minutes.

**OCR misreads digits.** On `kegoc_2024.pdf` page 9 four figures were read wrong (e.g. total
equity and liabilities `1,087,066,105` instead of `1,097,066,105`), see DECISIONS.md. Every
figure used in `eval/questions.json` from an OCR page must be checked by hand against the image.

## Naming rule

`data/raw/<company>_<year>.pdf`, all lowercase, e.g. `halyk_2023.pdf`. `<year>` is the
reporting year (the year ended 31 December), not the year the report was published.

The company name and year used in the index and in citations come **only** from
`data/reports.json`, never from the file name or the PDF text. To add a report: put the PDF in
`data/raw/`, add an entry to `reports.json`, and rebuild the index.

`reports.json` fields:

- `file`, `company`, `year`: required.
- `skip` (optional): a reason; the file is not indexed and the reason is printed by `build_index`.
- `aliases` (top level): other names the LLM may use for a company, e.g. its full legal name.

## Files

| File | Company | Year | Source URL | Notes |
|---|---|---|---|---|
| `halyk_2022.pdf` | Halyk Bank | 2022 | | |
| `halyk_2023.pdf` | Halyk Bank | 2023 | | |
| `halyk_2024.pdf` | Halyk Bank | 2024 | | |
| `kegoc_2022.pdf` | KEGOC | 2022 | | Replaced on 17 Nov 2026 (the first download was the 2024 report). |
| `kegoc_2023.pdf` | KEGOC | 2023 | | |
| `kegoc_2024.pdf` | KEGOC | 2024 | | |
| `kcell_2022.pdf` | Kcell | 2022 | | |
| `kcell_2023.pdf` | Kcell | 2023 | | **Scanned**: only page 1 has a text layer; pages 2–58 come from OCR only. |
| `kcell_2024.pdf` | Kcell | 2024 | | |

## Pages without a text layer (text from OCR only)

These pages are images in `data/raw/`. After the OCR step all of them have text and no page is
left without text, but their figures come **only from OCR** and can contain misread digits.
The text layer of the other pages (changes in equity, cash flows, notes) is exact.

| File | Image-only pages (OCRed) | What they are |
|---|---|---|
| `halyk_2022.pdf` | 3, 9–12, 14, 16 | statement of financial position, profit or loss, OCI |
| `halyk_2023.pdf` | 3, 10–13, 15, 17 | statement of financial position, profit or loss, OCI |
| `halyk_2024.pdf` | 3, 8–11, 13, 15 | statement of financial position, profit or loss, OCI |
| `kegoc_2022.pdf` | 7–13 | primary statements |
| `kegoc_2023.pdf` | 7, 9–10, 12–13 | equity and liabilities half of the balance sheet, comprehensive income |
| `kegoc_2024.pdf` | 3–7, 9–10, 12–13 | same as 2023, plus the auditor's report |
| `kcell_2022.pdf` | 9–13 | primary statements |
| `kcell_2023.pdf` | 2–58 | everything (whole file is a scan) |
| `kcell_2024.pdf` | 3–12 | auditor's report and primary statements |

`python -m scripts.ocr_reports` prints the count per file; `python -m scripts.build_index`
reports any page that is still without text.

## OCR fixes (`data/ocr_fixes.json`)

OCR misreads digits and words, and some of those errors change the answer (KEGOC 2024 p. 9:
"Total equity and abilities 1,087,066,105" instead of "Total equity and liabilities
1,097,066,105"). `data/ocr_fixes.json` holds hand-checked corrections; it is in git.

```json
{"file": "kegoc_2024.pdf", "page": 9,
 "old": "Retained earnings   64,089,351   8,259,455",
 "new": "Retained earnings   64,089,351   48,259,455",
 "checked": "page image, 2026-11-17"}
```

- A fix replaces **one whole row** of the page text as the parser builds it (after `1.097.066.105`
  → `1,097,066,105`). Copy `old` exactly from the parsed text, including the three-space column
  gaps and any OCR noise such as `‘`.
- It is applied only when the `old` row occurs on that page exactly once. Otherwise `build_index`
  prints `! OCR fix not applied (...)` and leaves the text as it is, so a fix that no longer fits
  (e.g. after OCR was redone) is visible, not silent.
- Fixes apply only to OCR copies in `data/ocr/`, not with `build_index --no-ocr`.
- **Add a fix only after checking the row against the page image**, and check that the
  statement's totals add up after the fix. Never add labels or figures that are not on the page.
- Current fixes: 17 rows of `kegoc_2024.pdf` p. 9 (balance sheet, equity and liabilities).

## Rotated pages

Some statement pages are landscape scans stored with a page rotation (`/Rotate 90` or `270`).
The parser maps word positions to the page as it is displayed before it builds rows, so these
pages read normally (fixed on 18 Nov 2026; before that their text in the index was garbled).

| File | Rotated pages |
|---|---|
| `halyk_2022.pdf` | 14 |
| `halyk_2024.pdf` | 13 |
| `kegoc_2023.pdf` | 9–10, 12–13 |
| `kcell_2024.pdf` | 8–12 (all primary statements) |

## Units

The statements give units once per page: Halyk Bank in millions of tenge, Kcell in millions of
tenge, KEGOC in **thousands** of tenge. KEGOC writes numbers with dots as thousands separators
(`1.097.066.105` = 1,097,066,105 thousand tenge).

The parser rewrites numbers with two or more dot-separated groups of exactly 3 digits to commas
(`1.097.066.105` → `1,097,066,105`) in page text and tables. Numbers with one dot are left as
they are, because they may be decimals: in KEGOC files `569.653` (thousands) or `2.780` (book
value per share, tenge) stay with a dot. On OCR pages Tesseract also mixes the separators
(`148,922.757`, `5.588895`); these are not normalized either.
