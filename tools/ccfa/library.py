"""Index and search the shared library.

The source of truth is ``refs.bib`` plus ``notes/<key>.md``. ``index.db`` is
derived data and is rebuilt atomically by ``library index``. The database
schema is:

CREATE TABLE meta (schema_version INTEGER, refs_sha256 TEXT, notes_sha256 TEXT,
                   built_at TEXT, entry_count INTEGER);
CREATE VIRTUAL TABLE papers USING fts5(
  key, title, authors, year, venue, abstract, notes, path, tokenize='trigram');

Queries of three or more characters use an FTS5 phrase. Shorter queries use a
literal LIKE fallback because the trigram tokenizer cannot match two-character
terms. The index contains metadata and notes, not PDF full text.

``library index --embed`` additionally fills two optional tables, which are what
``search --mode semantic|hybrid`` reads:

CREATE TABLE vector_index (model TEXT, dim INTEGER, metric TEXT, built_at TEXT,
                           row_count INTEGER);
CREATE TABLE vectors (key TEXT PRIMARY KEY, vector BLOB NOT NULL);

Vectors come from a local embedding model served by Ollama (``bge-m3`` by
default) and are stored as little-endian float32 blobs. They are a separate
table rather than extra ``meta`` columns so that an index built without
``--embed`` keeps the exact v1 ``meta`` contract and stays valid for keyword
search.

Semantic retrieval is an addition, never a replacement: the keyword path stays
exact and hash-checked, while embeddings only widen recall, because a
semantically similar paper is not the same paper. Scores are comparable within
one model only, so ``hybrid`` fuses the two rankings by reciprocal rank instead
of mixing raw scores.

Freshness is tracked only for ``refs.bib`` and ``notes/*.md``. The ``path``
column is a reserved placeholder written as an empty string; the ``path`` in
search results is a query-time fact, resolved from ``papers/<key>.pdf`` when a
search runs, so adding or deleting a PDF does not make the index stale. The
``path`` field is therefore an output field, never a searchable one.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from ccfa.bib import BibRecord, load_records
from ccfa.cli import Problem, emit, tool_error

SCHEMA_VERSION = 1

EMBED_DEFAULT_MODEL = "bge-m3"
EMBED_DEFAULT_URL = "http://127.0.0.1:11434/api/embed"
EMBED_TIMEOUT_S = 180.0
EMBED_METRIC = "cosine"

# Reciprocal-rank fusion constant. Rank-based fusion is used because raw
# cosine and FTS5 scores are not on a common scale.
RRF_K = 60

SEARCH_MODES = ("keyword", "semantic", "hybrid")

# One batch per request keeps the local embedding server responsive; bge-m3
# encodes well over a hundred short texts per minute on this host.
EMBED_BATCH_SIZE = 32

Embedder = Callable[[list[str]], list[list[float]]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_bytes(path: Path, description: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"无法读取{description} {path}: {exc}") from exc


def pack_vector(vector: Iterable[float]) -> bytes:
    """Pack a vector as little-endian float32 for SQLite storage."""
    values = array.array("f", vector)
    if array.array("f").itemsize != 4 or sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


def unpack_vector(blob: bytes) -> list[float]:
    """Inverse of :func:`pack_vector`; rejects a truncated or odd-length blob."""
    if len(blob) % 4:
        raise ValueError(f"向量 blob 长度不是 4 的倍数: {len(blob)}")
    values = array.array("f")
    values.frombytes(blob)
    if array.array("f").itemsize != 4 or sys.byteorder != "little":
        values.byteswap()
    return list(values)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Cosine similarity; returns 0.0 for a zero-length or mismatched pair."""
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def embedding_text(row: dict) -> str:
    """Compose the text a paper is embedded from.

    Authors, venue and year are deliberately excluded: the keyword index already
    answers exact metadata lookups, and mixing them into the vector makes a
    query like "graph neural networks" drift toward whoever publishes most in
    that area.
    """
    parts = [row.get("title", ""), row.get("abstract", ""), row.get("notes", "")]
    return ". ".join(part.strip() for part in parts if part and part.strip())


def ollama_embed(
    texts: list[str],
    *,
    model: str = EMBED_DEFAULT_MODEL,
    url: str = EMBED_DEFAULT_URL,
    timeout: float = EMBED_TIMEOUT_S,
    opener: Callable[..., object] | None = None,
) -> list[list[float]]:
    """Embed *texts* with the local Ollama embedding endpoint.

    Network access happens only when a caller asks for it: ``library index``
    without ``--embed`` and keyword search never reach this function.
    """
    if not texts:
        return []
    open_url = opener or urllib.request.urlopen
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with open_url(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.URLError as exc:
        raise ValueError(
            f"无法连接本地 embedding 服务 {url}: {exc}. "
            "确认 Ollama 正在运行，或省略 --embed 只用关键词检索"
        ) from exc
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"embedding 服务返回的不是合法 JSON: {exc}") from exc
    embeddings = parsed.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise ValueError(
            f"embedding 服务返回 {len(embeddings) if isinstance(embeddings, list) else '?'} "
            f"条向量，期望 {len(texts)} 条"
        )
    vectors: list[list[float]] = []
    for item in embeddings:
        if not isinstance(item, list) or not item:
            raise ValueError("embedding 服务返回了空向量")
        vectors.append([float(value) for value in item])
    return vectors


def _batched(items: list, size: int = EMBED_BATCH_SIZE) -> list[list]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def reciprocal_rank_fusion(
    rankings: list[list[str]],
    *,
    k: int = RRF_K,
) -> list[tuple[str, float]]:
    """Fuse ranked key lists by reciprocal rank; ties break on key for determinism."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + position)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _notes_snapshot(library_dir: Path) -> tuple[list[tuple[str, str, str]], str]:
    notes_dir = library_dir / "notes"
    paths = sorted(notes_dir.glob("*.md")) if notes_dir.is_dir() else []
    entries: list[tuple[str, str, str]] = []
    digest = hashlib.sha256()
    for path in paths:
        data = _read_bytes(path, "note")
        relative = path.relative_to(library_dir).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"无法读取 note {path}: {exc}") from exc
        entries.append((path.stem, text, relative))
    return entries, digest.hexdigest()


def _pdf_relative(library_dir: Path, key: str) -> str:
    candidate = library_dir / "papers" / f"{key}.pdf"
    if candidate.is_file():
        return candidate.relative_to(library_dir).as_posix()
    return ""


def _insert_index(
    temporary: Path,
    refs_sha256: str,
    notes_sha256: str,
    records: dict[str, BibRecord],
    notes: dict[str, str],
    vectors: dict[str, list[float]] | None = None,
    embed_model: str = EMBED_DEFAULT_MODEL,
) -> None:
    connection = sqlite3.connect(temporary)
    try:
        connection.execute(
            "CREATE TABLE meta (schema_version INTEGER, refs_sha256 TEXT, "
            "notes_sha256 TEXT, built_at TEXT, entry_count INTEGER)"
        )
        connection.execute(
            "CREATE VIRTUAL TABLE papers USING fts5("
            "key, title, authors, year, venue, abstract, notes, path, "
            "tokenize='trigram')"
        )
        connection.execute(
            "CREATE TABLE vector_index (model TEXT, dim INTEGER, metric TEXT, "
            "built_at TEXT, row_count INTEGER)"
        )
        connection.execute("CREATE TABLE vectors (key TEXT PRIMARY KEY, vector BLOB NOT NULL)")
        connection.execute(
            "INSERT INTO meta VALUES (?, ?, ?, ?, ?)",
            (
                SCHEMA_VERSION,
                refs_sha256,
                notes_sha256,
                _now_iso(),
                len(records),
            ),
        )
        for key, record in records.items():
            connection.execute(
                "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    record.title,
                    record.authors,
                    record.year,
                    record.venue,
                    record.abstract,
                    notes.get(key, ""),
                    "",
                ),
            )
        if vectors:
            dimensions = sorted({len(vector) for vector in vectors.values()})
            if len(dimensions) != 1:
                raise ValueError(f"向量维度不一致: {dimensions}")
            connection.execute(
                "INSERT INTO vector_index VALUES (?, ?, ?, ?, ?)",
                (
                    embed_model,
                    dimensions[0],
                    EMBED_METRIC,
                    _now_iso(),
                    len(vectors),
                ),
            )
            connection.executemany(
                "INSERT INTO vectors VALUES (?, ?)",
                [(key, pack_vector(vector)) for key, vector in vectors.items()],
            )
        connection.commit()
    finally:
        connection.close()


def build_index(
    library_dir: Path,
    *,
    embed: bool = False,
    embed_model: str = EMBED_DEFAULT_MODEL,
    embed_url: str = EMBED_DEFAULT_URL,
    embedder: Embedder | None = None,
) -> dict:
    """Atomically rebuild index.db from refs.bib and notes/*.md.

    With ``embed=True`` the rows are also sent to a local embedding model. The
    call happens before the temporary database is opened, so a dead embedding
    service leaves the existing index untouched.
    """
    library_dir = Path(library_dir)
    refs_path = library_dir / "refs.bib"
    refs_bytes = _read_bytes(refs_path, "BibTeX")
    refs_sha256 = hashlib.sha256(refs_bytes).hexdigest()
    parsed = load_records(refs_path)
    note_entries, notes_sha256 = _notes_snapshot(library_dir)
    note_text = {stem: text for stem, text, _relative in note_entries}
    stray_notes = sorted(
        relative for stem, _text, relative in note_entries if stem not in parsed.records
    )

    vectors: dict[str, list[float]] = {}
    skipped: list[str] = []
    if embed:
        rows = [
            {
                "key": key,
                "title": record.title,
                "abstract": record.abstract,
                "notes": note_text.get(key, ""),
            }
            for key, record in parsed.records.items()
        ]
        texts = [embedding_text(row) for row in rows]
        embeddable = [(row["key"], text) for row, text in zip(rows, texts) if text]
        skipped = [row["key"] for row, text in zip(rows, texts) if not text]
        runner = embedder or (
            lambda batch: ollama_embed(  # noqa: E731 - one-line adapter
                batch, model=embed_model, url=embed_url
            )
        )
        for batch in _batched(embeddable):
            returned = runner([text for _key, text in batch])
            if len(returned) != len(batch):
                raise ValueError(f"embedding 返回 {len(returned)} 条向量，本批期望 {len(batch)} 条")
            for (key, _text), vector in zip(batch, returned):
                vectors[key] = vector

    try:
        library_dir.mkdir(parents=True, exist_ok=True)
        temporary = library_dir / "index.db.tmp"
        temporary.unlink(missing_ok=True)
        _insert_index(
            temporary,
            refs_sha256,
            notes_sha256,
            parsed.records,
            note_text,
            vectors or None,
            embed_model,
        )
        os.replace(temporary, library_dir / "index.db")
    except (OSError, sqlite3.Error) as exc:
        temporary = library_dir / "index.db.tmp"
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ValueError(f"无法重建索引 {library_dir / 'index.db'}: {exc}") from exc

    if stray_notes:
        print(
            f"游离 note {len(stray_notes)}: {', '.join(stray_notes)}",
            file=sys.stderr,
        )
    return {
        "entries": len(parsed.records),
        "duplicate_keys": parsed.duplicate_keys,
        "stray_notes": stray_notes,
        "embedded": len(vectors),
        "embedding_model": embed_model if embed else None,
        "embedding_skipped": skipped,
    }


def _load_meta(index_path: Path) -> tuple:
    if not index_path.is_file():
        raise ValueError("索引不存在：请先运行 library index")
    try:
        connection = sqlite3.connect(index_path)
        try:
            row = connection.execute(
                "SELECT schema_version, refs_sha256, notes_sha256, built_at, entry_count FROM meta"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ValueError(f"无法读取索引 {index_path}: {exc}") from exc
    if row is None:
        raise ValueError(f"索引缺少 meta 行: {index_path}")
    return row


def _assert_fresh(library_dir: Path, meta: tuple) -> None:
    refs_path = library_dir / "refs.bib"
    refs_bytes = _read_bytes(refs_path, "BibTeX")
    refs_sha256 = hashlib.sha256(refs_bytes).hexdigest()
    _notes, notes_sha256 = _notes_snapshot(library_dir)
    if meta[0] != SCHEMA_VERSION:
        raise ValueError(f"索引 schema_version 不受支持: {meta[0]!r}")
    if meta[1] != refs_sha256 or meta[2] != notes_sha256:
        raise ValueError("索引已过期：请先运行 library index 重建")


def _index_keys(index_path: Path) -> list[str]:
    try:
        connection = sqlite3.connect(index_path)
        try:
            return [row[0] for row in connection.execute("SELECT key FROM papers").fetchall()]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ValueError(f"无法读取索引 {index_path}: {exc}") from exc


def _vector_problems(index_path: Path, index_keys: set[str]) -> list[Problem]:
    """Read-only integrity audit of the optional vector tables."""
    try:
        connection = sqlite3.connect(index_path)
        try:
            stored = _load_vector_index(connection)
            if stored is None:
                return []
            _model, dim, row_count = stored
            rows = connection.execute("SELECT key, vector FROM vectors").fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return [
            Problem(
                "vector-index-unreadable",
                str(index_path),
                None,
                f"无法读取向量表: {exc}",
            )
        ]

    problems: list[Problem] = []
    if row_count != len(rows):
        problems.append(
            Problem(
                "vector-index-count-mismatch",
                str(index_path),
                None,
                f"vector_index 记录 {row_count} 条向量，实际存有 {len(rows)} 条",
            )
        )
    vector_keys = {row[0] for row in rows}
    for key in sorted(index_keys - vector_keys):
        problems.append(
            Problem(
                "vector-index-missing",
                str(index_path),
                None,
                f"索引条目缺少向量: {key}",
            )
        )
    for key, blob in rows:
        width = len(blob) // 4 if isinstance(blob, (bytes, bytearray)) else 0
        if width != dim:
            problems.append(
                Problem(
                    "vector-index-dim-mismatch",
                    str(index_path),
                    None,
                    f"{key} 的向量维度 {width} 与索引声明的 {dim} 不一致",
                )
            )
    return problems


def check_library(library_dir: Path) -> list[Problem]:
    """Read-only audit of index.db against refs.bib and notes/*.md."""
    library_dir = Path(library_dir)
    refs_path = library_dir / "refs.bib"
    parsed = load_records(refs_path)
    refs_sha256 = hashlib.sha256(_read_bytes(refs_path, "BibTeX")).hexdigest()
    note_entries, notes_sha256 = _notes_snapshot(library_dir)

    problems: list[Problem] = []
    index_path = library_dir / "index.db"
    if not index_path.is_file():
        problems.append(
            Problem(
                "index-missing",
                str(index_path),
                None,
                "索引不存在；请先运行 library index",
            )
        )
    else:
        meta = _load_meta(index_path)
        if meta[0] != SCHEMA_VERSION:
            problems.append(
                Problem(
                    "index-schema-version",
                    str(index_path),
                    None,
                    f"索引 schema_version 不受支持: {meta[0]!r}",
                )
            )
        if meta[1] != refs_sha256 or meta[2] != notes_sha256:
            problems.append(
                Problem(
                    "index-stale",
                    str(index_path),
                    None,
                    "索引已过期：来源 refs.bib 或 notes 已变更",
                )
            )

        index_keys = set(_index_keys(index_path))
        problems.extend(_vector_problems(index_path, index_keys))
        records = parsed.records
        for key in sorted(set(records) - index_keys):
            problems.append(
                Problem(
                    "index-entry-missing",
                    str(refs_path),
                    None,
                    f"refs.bib 的 key 不在索引中: {key}",
                )
            )
        for key in sorted(index_keys - set(records)):
            problems.append(
                Problem(
                    "index-entry-extra",
                    str(index_path),
                    None,
                    f"索引中的 key 不在 refs.bib 中: {key}",
                )
            )

    for key in dict.fromkeys(parsed.duplicate_keys):
        problems.append(
            Problem(
                "duplicate-bib-key",
                str(refs_path),
                None,
                f"refs.bib 包含重复 key: {key}",
            )
        )

    for stem, _text, relative in note_entries:
        if stem not in parsed.records:
            problems.append(
                Problem(
                    "note-without-entry",
                    str(library_dir / relative),
                    None,
                    f"note 没有对应的 refs.bib key: {stem}",
                )
            )
    return problems


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fts_phrase(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


_RESULT_COLUMNS = "key, title, year, venue"
_RESULT_COLUMNS_SELECT = f"SELECT {_RESULT_COLUMNS} FROM papers"


def _search_rows(
    connection: sqlite3.Connection,
    query: str,
    limit: int,
) -> tuple[str, list[tuple]]:
    if len(query) <= 2:
        pattern = f"%{_escape_like(query)}%"
        columns = ("key", "title", "authors", "year", "venue", "abstract", "notes")
        where = " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for column in columns)
        rows = connection.execute(
            f"SELECT {_RESULT_COLUMNS} FROM papers WHERE {where} LIMIT ?",
            (*([pattern] * len(columns)), limit),
        ).fetchall()
        return "like", rows

    rows = connection.execute(
        f"SELECT {_RESULT_COLUMNS} FROM papers WHERE papers MATCH ? LIMIT ?",
        (_fts_phrase(query), limit),
    ).fetchall()
    return "fts", rows


def _load_vector_index(connection: sqlite3.Connection) -> tuple[str, int, int] | None:
    """Return ``(model, dim, row_count)`` for the stored vectors, if any."""
    try:
        row = connection.execute("SELECT model, dim, row_count FROM vector_index").fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    model, dim, row_count = row
    if not isinstance(model, str) or not model.strip():
        return None
    if not isinstance(dim, int) or dim < 1:
        return None
    return model.strip(), dim, int(row_count or 0)


def _semantic_ranking(
    connection: sqlite3.Connection,
    query_vector: list[float],
    dim: int,
) -> list[tuple[str, float]]:
    """Rank every stored vector against *query_vector*, deterministically."""
    rows = connection.execute("SELECT key, vector FROM vectors").fetchall()
    scored: list[tuple[str, float]] = []
    for key, blob in rows:
        vector = unpack_vector(blob)
        if len(vector) != dim:
            raise ValueError(
                f"向量维度与 vector_index 不一致: {key} 为 {len(vector)}，索引声明 {dim}"
            )
        scored.append((key, cosine_similarity(query_vector, vector)))
    return sorted(scored, key=lambda item: (-item[1], item[0]))


def search_index(
    library_dir: Path,
    query: str,
    limit: int = 20,
    *,
    mode: str = "keyword",
    embed_url: str = EMBED_DEFAULT_URL,
    embedder: Embedder | None = None,
) -> dict:
    """Search a fresh index. Raises ValueError if it is missing or stale.

    ``mode`` is one of ``keyword`` (exact FTS5/LIKE, the default and the only
    mode that works without embeddings), ``semantic`` (local vectors only) or
    ``hybrid`` (both rankings fused by reciprocal rank).

    The returned ``mode`` field keeps its historical meaning — the keyword
    mechanism used (``fts`` or ``like``) — while ``search_mode`` repeats the
    requested mode. Every result carries ``matched_by`` and, for hybrid, the
    per-mode ranks and fused score, so a caller can always tell *why* a key
    surfaced instead of trusting a single opaque number.
    """
    library_dir = Path(library_dir)
    if not isinstance(query, str):
        raise ValueError("查询必须是字符串")
    query = query.strip()
    if not query:
        raise ValueError("查询不能为空")
    if type(limit) is not int or limit < 1:
        raise ValueError("limit 必须是正整数")
    if mode not in SEARCH_MODES:
        raise ValueError(f"mode 必须是 {' / '.join(SEARCH_MODES)}: {mode!r}")

    index_path = library_dir / "index.db"
    meta = _load_meta(index_path)
    _assert_fresh(library_dir, meta)

    try:
        connection = sqlite3.connect(index_path)
        try:
            metadata = {
                row[0]: {"title": row[1], "year": row[2], "venue": row[3]}
                for row in connection.execute(_RESULT_COLUMNS_SELECT)
            }
            total = len(metadata)
            keyword_keys: list[str] = []
            keyword_mode = "semantic"
            if mode in {"keyword", "hybrid"}:
                # Hybrid fuses the *complete* keyword ranking; truncating it to
                # `limit` first would silently drop keys that only rank low.
                keyword_limit = limit if mode == "keyword" else max(total, 1)
                keyword_mode, keyword_rows = _search_rows(connection, query, keyword_limit)
                keyword_keys = [row[0] for row in keyword_rows]

            semantic_scores: dict[str, float] = {}
            semantic_keys: list[str] = []
            if mode in {"semantic", "hybrid"}:
                stored = _load_vector_index(connection)
                if stored is None:
                    raise ValueError("索引没有向量：请先运行 library index --embed 建立语义索引")
                model, dim, _row_count = stored
                runner = embedder or (lambda batch: ollama_embed(batch, model=model, url=embed_url))
                query_vectors = runner([query])
                if len(query_vectors) != 1:
                    raise ValueError("embedding 服务未返回查询向量")
                query_vector = query_vectors[0]
                if len(query_vector) != dim:
                    raise ValueError(f"查询向量维度 {len(query_vector)} 与索引 {dim} 不一致")
                ranked = _semantic_ranking(connection, query_vector, dim)
                semantic_scores = dict(ranked)
                semantic_keys = [key for key, _score in ranked]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ValueError(f"搜索索引失败 {index_path}: {exc}") from exc

    keyword_rank = {key: index for index, key in enumerate(keyword_keys, start=1)}
    semantic_rank = {key: index for index, key in enumerate(semantic_keys, start=1)}
    if mode == "keyword":
        ordered = keyword_keys
        fused: dict[str, float] = {}
    elif mode == "semantic":
        ordered = semantic_keys
        fused = {}
    else:
        pairs = reciprocal_rank_fusion([keyword_keys, semantic_keys])
        fused = dict(pairs)
        ordered = [key for key, _score in pairs]

    results = []
    for key in ordered[:limit]:
        if key not in metadata:
            continue
        matched_by = [
            name
            for name, present in (
                ("keyword", key in keyword_rank),
                ("semantic", key in semantic_rank),
            )
            if present
        ]
        results.append(
            {
                "key": key,
                **metadata[key],
                "path": _pdf_relative(library_dir, key),
                "matched_by": matched_by,
                "keyword_rank": keyword_rank.get(key),
                "semantic_rank": semantic_rank.get(key),
                "semantic_score": semantic_scores.get(key),
                "rrf_score": fused.get(key),
            }
        )
    return {
        "query": query,
        "mode": keyword_mode,
        "search_mode": mode,
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="索引和检索共享文献库")
    parser.add_argument(
        "--dir",
        default="library",
        help="文献库目录（默认: library）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    index = subparsers.add_parser(
        "index",
        help="重建 index.db；这是派生数据、可重建，也是唯一允许覆盖的写路径",
        description=("重建 index.db。它是派生数据、可重建，也是本工具唯一允许覆盖的写路径。"),
    )
    index.add_argument(
        "--embed",
        action="store_true",
        help=(
            "同时用本地 embedding 模型为每条记录建立向量，供 search --mode "
            "semantic/hybrid 使用；不加此参数时索引只支持关键词检索"
        ),
    )
    index.add_argument("--embed-model", default=EMBED_DEFAULT_MODEL)
    index.add_argument("--embed-url", default=EMBED_DEFAULT_URL)
    search = subparsers.add_parser(
        "search",
        help="检索索引字段，不包含 PDF 全文",
        description=(
            "检索 key/title/authors/year/venue/abstract/notes；"
            "索引不含 PDF 全文。新鲜度只对 refs.bib 与 notes 负责；"
            "path 是结果字段、不参与检索，其取值在查询期按 "
            "papers/<key>.pdf 当前是否存在解析。"
            "--mode 可选 keyword（默认，精确关键词）、semantic（本地向量）"
            "或 hybrid（两种排序按倒数排名融合）；后两者要求索引用 "
            "library index --embed 建立过向量。"
        ),
    )
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument(
        "--mode",
        choices=SEARCH_MODES,
        default="keyword",
        help="keyword 精确匹配 / semantic 语义 / hybrid 融合",
    )
    search.add_argument("--embed-url", default=EMBED_DEFAULT_URL)
    subparsers.add_parser(
        "check",
        help="只读审计 index.db 与 refs.bib/notes 的一致性",
        description=("只读审计 index.db 与 refs.bib/notes 的一致性；本命令不写盘。"),
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "index":
            summary = build_index(
                Path(args.dir),
                embed=args.embed,
                embed_model=args.embed_model,
                embed_url=args.embed_url,
            )
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "check":
            return emit(check_library(Path(args.dir)))
        result = search_index(
            Path(args.dir),
            args.query,
            limit=args.limit,
            mode=args.mode,
            embed_url=args.embed_url,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
