"""Load a BibTeX file into a key -> entry mapping.

DOI values are normalized: a URL prefix is stripped and the result is
lowercased, so the same DOI written two ways compares equal.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import bibtexparser
from bibtexparser.model import DuplicateBlockKeyBlock


class BibEntry(NamedTuple):
    key: str
    doi: str | None
    title: str | None


class BibRecord(NamedTuple):
    key: str
    title: str | None
    authors: str | None
    year: str | None
    venue: str | None
    abstract: str | None
    doi: str | None


class BibFile(NamedTuple):
    records: dict[str, BibRecord]
    duplicate_keys: list[str]


_DOI_URL_PREFIX = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
_BRACES = re.compile(r"[{}]")


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip()
    doi = _DOI_URL_PREFIX.sub("", doi)
    return doi.lower() or None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return _BRACES.sub("", value).strip() or None


def _field_value(fields: dict, name: str) -> str | None:
    field = fields.get(name)
    return _clean(field.value if field else None)


def load_records(path: Path) -> BibFile:
    """Return indexable records. Duplicate keys keep the first entry."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc

    library = bibtexparser.parse_string(text)
    duplicate_keys: list[str] = []
    other_failures = []
    for block in library.failed_blocks:
        if isinstance(block, DuplicateBlockKeyBlock):
            duplicate_keys.append(block.key)
        else:
            other_failures.append(block)
    if other_failures:
        kinds = ", ".join(type(block).__name__ for block in other_failures)
        raise ValueError(f"BibTeX 解析失败于 {path}: {kinds}")

    records: dict[str, BibRecord] = {}
    for entry in library.entries:
        fields = entry.fields_dict
        doi = _field_value(fields, "doi")
        venue = _field_value(fields, "journal") or _field_value(fields, "booktitle")
        records[entry.key] = BibRecord(
            key=entry.key,
            title=_field_value(fields, "title"),
            authors=_field_value(fields, "author"),
            year=_field_value(fields, "year"),
            venue=venue,
            abstract=_field_value(fields, "abstract"),
            doi=normalize_doi(doi),
        )
    return BibFile(records=records, duplicate_keys=duplicate_keys)


def load_entries(path: Path) -> dict[str, BibEntry]:
    """Return entries by key. Raises ValueError on a missing or invalid file."""
    parsed = load_records(path)
    if parsed.duplicate_keys:
        keys = ", ".join(parsed.duplicate_keys)
        raise ValueError(f"BibTeX 解析失败于 {path}: duplicate keys: {keys}")

    entries: dict[str, BibEntry] = {}
    for key, record in parsed.records.items():
        entries[key] = BibEntry(key=key, doi=record.doi, title=record.title)
    return entries
