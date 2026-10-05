"""Check whether a DOI resolves, via Crossref then DataCite.

A 200 response is not evidence by itself. The body must be JSON, the DOI in
the body must match the requested DOI after normalization, and (when an
expected title is supplied) the returned title must be at least 0.9 similar
after normalization. The provider must also return a usable non-empty string
title; a missing title is a failure, never evidence with ``matched_title``
``None``. A successful lookup carries a :class:`LookupEvidence` record binding
the answer to the fetched body.

The ``body_sha256`` proves that some fetch happened. Without the response body
itself there is no way to recompute it offline, so this digest is not a
complete anti-forgery boundary; it cannot detect a hand-written ledger entry
with a plausible hash.

Network access is opt-in at the caller level: nothing here runs unless
lookup() is called explicitly.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, NamedTuple

from ccfa.bib import normalize_doi

Fetcher = Callable[[str, float], "tuple[int, str | bytes]"]

_ENDPOINTS = (
    ("crossref", "https://api.crossref.org/works/{doi}"),
    ("datacite", "https://api.datacite.org/dois/{doi}"),
)

_USER_AGENT = "paper-template-citation-guard/0.1"

TITLE_MATCH_THRESHOLD = 0.9

# Letters, digits and CJK ideographs survive; everything else becomes a
# separator before whitespace is collapsed.
_TITLE_SEPARATORS = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")


class LookupEvidence(NamedTuple):
    """Fetched-body evidence.

    ``body_sha256`` is computed over the raw response bytes. It proves that a
    fetch happened, but it cannot be recomputed offline when the body was not
    stored, so the anti-forgery boundary is incomplete.
    """

    body_sha256: str
    retrieved_at: str
    matched_title: str
    source: str


class LookupResult(NamedTuple):
    doi: str
    found: bool
    source: str | None
    detail: str
    evidence: LookupEvidence | None = None
    http_ok: bool = False


def normalize_title(value: str | None) -> str:
    """NFKC/casefold a title and keep only letters, digits and CJK."""
    if not isinstance(value, str) or not value.strip():
        return ""
    text = unicodedata.normalize("NFKC", value).casefold()
    text = _TITLE_SEPARATORS.sub(" ", text)
    return " ".join(text.split())


def title_similarity(left: str | None, right: str | None) -> float:
    """Return the difflib ratio of two normalized titles (0.0..1.0)."""
    normalized_left = normalize_title(left)
    normalized_right = normalize_title(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return difflib.SequenceMatcher(
        None,
        normalized_left,
        normalized_right,
    ).ratio()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _body_sha256(raw: bytes) -> str:
    digest = hashlib.sha256(raw).hexdigest()
    return f"sha256:{digest}"


def _first_title(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                candidate = item.get("title")
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
    return None


def _crossref_fields(payload: Any) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    message = payload.get("message")
    if not isinstance(message, dict):
        return None, None
    doi = message.get("DOI")
    return (
        doi if isinstance(doi, str) else None,
        _first_title(message.get("title")),
    )


def _datacite_fields(payload: Any) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, None
    attributes = data.get("attributes")
    if not isinstance(attributes, dict):
        return None, None
    doi = attributes.get("doi")
    return (
        doi if isinstance(doi, str) else None,
        _first_title(attributes.get("titles")),
    )


def _default_fetch(url: str, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def lookup(
    doi: str,
    fetch: Fetcher | None = None,
    timeout: float = 20.0,
    *,
    expected_title: str | None = None,
) -> LookupResult:
    """Resolve *doi* and return evidence for the answer.

    A 200 whose body has a different DOI is ``doi mismatch``; when an expected
    title is given, a missing or clearly different title is ``title mismatch``.
    Neither is treated as found.
    """
    normalized = normalize_doi(doi)
    if not normalized:
        return LookupResult(doi="", found=False, source=None, detail="DOI 为空")

    fetcher = fetch or _default_fetch
    attempts: list[str] = []
    saw_http_ok = False
    for source, template in _ENDPOINTS:
        url = template.format(doi=urllib.parse.quote(normalized, safe=""))
        try:
            status, body = fetcher(url, timeout)
        except OSError as exc:
            attempts.append(f"{source}: 网络错误 {exc}")
            continue
        if status != 200:
            attempts.append(f"{source}: HTTP {status}")
            continue
        saw_http_ok = True
        if isinstance(body, bytes):
            raw = body
            text = body.decode("utf-8", errors="replace")
        elif isinstance(body, str):
            text = body
            raw = body.encode("utf-8")
        else:
            attempts.append(f"{source}: 响应体类型非法")
            continue
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            attempts.append(f"{source}: 响应不是合法 JSON")
            continue
        if source == "crossref":
            returned_doi, matched_title = _crossref_fields(payload)
        else:
            returned_doi, matched_title = _datacite_fields(payload)
        if normalize_doi(returned_doi) != normalized:
            return LookupResult(
                normalized,
                False,
                source,
                "doi mismatch",
                None,
                True,
            )
        if not isinstance(matched_title, str) or not matched_title.strip():
            return LookupResult(
                normalized,
                False,
                source,
                "title missing",
                None,
                True,
            )
        if expected_title:
            similarity = title_similarity(expected_title, matched_title)
            if similarity < TITLE_MATCH_THRESHOLD:
                return LookupResult(
                    normalized,
                    False,
                    source,
                    "title mismatch",
                    None,
                    True,
                )
        evidence = LookupEvidence(
            body_sha256=_body_sha256(raw),
            retrieved_at=_utc_now(),
            matched_title=matched_title.strip(),
            source=source,
        )
        return LookupResult(
            normalized,
            True,
            source,
            f"{source} 返回 200 且 DOI 匹配",
            evidence,
            True,
        )

    return LookupResult(
        normalized,
        False,
        None,
        "; ".join(attempts),
        None,
        saw_http_ok,
    )
