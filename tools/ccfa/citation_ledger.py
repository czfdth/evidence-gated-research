"""Load and write the citation verification ledger.

This ledger is the record of what was checked at retrieval time. It is what
separates "a key that exists because someone verified it" from "a key that
exists because a model typed it". A ``verified`` record must carry fetched
evidence; the loader never crashes on a missing or malformed evidence block,
it records the reason on the entry so ``citation_guard`` can report it.

``evidence.body_sha256`` is the sha256 of the raw response bytes: it proves a
fetch happened, but without the stored body it cannot be recomputed offline,
so the anti-forgery boundary is incomplete.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NamedTuple

from ccfa.bib import normalize_doi
from ccfa.cli import save_text_atomically

VALID_STATUSES = ("verified", "unverified", "failed")

EVIDENCE_FIELDS = ("body_sha256", "retrieved_at", "matched_title", "source")
BODY_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class LedgerEvidence(NamedTuple):
    body_sha256: str
    retrieved_at: str
    matched_title: str
    source: str


class LedgerRecord(NamedTuple):
    key: str
    doi: str | None
    status: str
    verified_at: str
    source: str
    evidence: LedgerEvidence | None = None
    evidence_error: str = ""
    detail: str = ""


def _parse_evidence(value: object) -> LedgerEvidence:
    if not isinstance(value, dict):
        raise ValueError("evidence 必须是对象")
    for field in EVIDENCE_FIELDS:
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"evidence.{field} 必须是非空字符串")
    body_sha256 = value["body_sha256"].strip()
    if BODY_SHA256_PATTERN.fullmatch(body_sha256) is None:
        raise ValueError(
            "evidence.body_sha256 必须是 sha256:<64 位小写十六进制>"
        )
    return LedgerEvidence(
        body_sha256=body_sha256,
        retrieved_at=value["retrieved_at"].strip(),
        matched_title=value["matched_title"].strip(),
        source=value["source"].strip(),
    )


def load_ledger(path: Path) -> dict[str, LedgerRecord]:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取台账 {path}: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"台账不是合法 JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("台账顶层必须是对象")
    if "version" not in data:
        raise ValueError("台账缺少 version 字段")
    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("台账 entries 必须是对象")

    records: dict[str, LedgerRecord] = {}
    for key, value in entries.items():
        if not isinstance(value, dict):
            raise ValueError(f"台账条目 {key} 必须是对象")
        status = value.get("status")
        if status not in VALID_STATUSES:
            raise ValueError(
                f"台账条目 {key} 的 status 非法: {status!r}，应为 {' / '.join(VALID_STATUSES)}"
            )
        doi = value.get("doi")
        if doi is not None and not isinstance(doi, str):
            raise ValueError(f"台账条目 {key} 的 doi 必须是字符串或 null，实际是 {type(doi).__name__}")

        evidence = None
        evidence_error = ""
        if status == "verified":
            raw_evidence = value.get("evidence")
            if raw_evidence is None:
                evidence_error = "缺少 evidence"
            else:
                try:
                    evidence = _parse_evidence(raw_evidence)
                except ValueError as exc:
                    evidence_error = str(exc)

        records[key] = LedgerRecord(
            key=key,
            doi=normalize_doi(doi),
            status=status,
            verified_at=str(value.get("verified_at", "")),
            source=str(value.get("source", "")),
            evidence=evidence,
            evidence_error=evidence_error,
            detail=(
                value.get("detail")
                if isinstance(value.get("detail"), str)
                else ""
            ),
        )
    return records


def save_ledger(path: Path, records: dict[str, LedgerRecord]) -> None:
    """Atomically write schema v1; evidence is serialized when present."""
    entries: dict[str, dict] = {}
    for key in sorted(records):
        record = records[key]
        entry: dict = {
            "doi": record.doi,
            "status": record.status,
            "verified_at": record.verified_at,
            "source": record.source,
        }
        if record.evidence is not None:
            entry["evidence"] = dict(record.evidence._asdict())
        if record.detail:
            entry["detail"] = record.detail
        entries[key] = entry
    text = json.dumps(
        {"version": 1, "entries": entries},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    save_text_atomically(path, text, description="引用台账")
