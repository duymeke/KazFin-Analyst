"""Read data/reports.json and map company names to their canonical form.

The manifest is the only source of company names and years. The parser never
guesses them from the PDF text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "data" / "reports.json"
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw"


@dataclass(frozen=True)
class ReportEntry:
    """One PDF listed in the manifest."""

    file: str
    company: str
    year: int
    skip: str | None = None  # reason the file must not be indexed


@dataclass(frozen=True)
class Manifest:
    reports: list[ReportEntry]
    aliases: dict[str, list[str]]  # canonical company -> other names

    @property
    def companies(self) -> list[str]:
        """Canonical company names, in manifest order, without duplicates."""
        return list(dict.fromkeys(r.company for r in self.reports))


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> Manifest:
    """Load and validate the manifest."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    reports = [
        ReportEntry(
            file=str(r["file"]),
            company=str(r["company"]),
            year=int(r["year"]),
            skip=r.get("skip") or None,
        )
        for r in data["reports"]
    ]
    aliases = {str(k): [str(a) for a in v] for k, v in data.get("aliases", {}).items()}
    return Manifest(reports=reports, aliases=aliases)


def company_slug(company: str) -> str:
    """Short id-safe name: first word, lowercase, letters and digits only.

    "Halyk Bank" -> "halyk", "KEGOC" -> "kegoc".
    """
    first = company.strip().split()[0] if company.strip() else ""
    slug = re.sub(r"[^a-z0-9]+", "", first.lower())
    if not slug:
        raise ValueError(f"cannot make a slug from company name {company!r}")
    return slug


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def resolve_company(
    name: str, companies: list[str], aliases: dict[str, list[str]] | None = None
) -> str | None:
    """Map a free-form company name from the LLM to a canonical name, or None.

    Case-insensitive and tolerant: "halyk", "Halyk Bank", "Halyk Bank JSC" and
    the slug all map to "Halyk Bank". Returns None when nothing matches.
    """
    query = _norm(name)
    if not query:
        return None
    aliases = aliases or {}
    padded_query = f" {query} "
    for company in companies:
        names = [company, company_slug(company), *aliases.get(company, [])]
        for candidate in map(_norm, names):
            if not candidate:
                continue
            padded = f" {candidate} "
            # whole-word match in either direction, so "k" does not match "kcell"
            if padded_query in padded or padded in padded_query:
                return company
    return None
