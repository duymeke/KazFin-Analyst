# Data

## What the files are

`data/raw/` holds the audited consolidated financial statements (IFRS, in English) of three
companies listed on KASE, for the years 2022–2024. Each PDF contains the independent auditor's
report, the primary statements and the notes.

**The PDFs and the vector index are not in git** (`data/raw/` and `data/index/` are in
`.gitignore`). Download the PDFs from the URLs below into `data/raw/`, then run:

```bash
python -m scripts.build_index
```

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
| `kegoc_2022.pdf` | KEGOC | 2022 | | **Wrong file**: contains the 2024 report. Skipped until replaced. |
| `kegoc_2023.pdf` | KEGOC | 2023 | | |
| `kegoc_2024.pdf` | KEGOC | 2024 | | |
| `kcell_2022.pdf` | Kcell | 2022 | | |
| `kcell_2023.pdf` | Kcell | 2023 | | **Scanned**: only page 1 has a text layer, pages 2–58 are images. Needs OCR or a text version. |
| `kcell_2024.pdf` | Kcell | 2024 | | |

## Pages without a text layer

In every file the signed primary statements are images, so their figures are **not in the
index** until we add OCR. The text layer still has the statement of changes in equity, the
statement of cash flows and the notes, which repeat many figures.

| File | Image-only pages | Lost |
|---|---|---|
| `halyk_2022.pdf` | 3, 9–12, 14, 16 | statement of financial position, profit or loss, OCI |
| `halyk_2023.pdf` | 3, 10–13, 15, 17 | statement of financial position, profit or loss, OCI |
| `halyk_2024.pdf` | 3, 8–11, 13, 15 | statement of financial position, profit or loss, OCI |
| `kegoc_2023.pdf` | 7, 9–10, 12–13 | equity and liabilities half of the balance sheet, comprehensive income |
| `kegoc_2024.pdf` | 3–7, 9–10, 12–13 | same as 2023, plus the auditor's report |
| `kcell_2022.pdf` | 9–13 | primary statements |
| `kcell_2023.pdf` | 2–58 | everything (whole file is a scan) |
| `kcell_2024.pdf` | 3–12 | auditor's report and primary statements |

`python -m scripts.build_index` prints this list on every run.

## Units

The statements give units once per page: Halyk Bank in millions of tenge, Kcell in millions of
tenge, KEGOC in **thousands** of tenge. KEGOC writes numbers with dots as thousands separators
(`1.097.066.105` = 1,097,066,105 thousand tenge).
