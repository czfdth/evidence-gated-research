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

Freshness is tracked only for ``refs.bib`` and ``notes/*.md``. The ``path``
column is a reserved placeholder written as an empty string; the ``path`` in
search results is a query-time fact, resolved from ``papers/<key>.pdf`` when a
search runs, so adding or deleting a PDF does not make the index stale. The
``path`` field is therefore an output field, never a searchable one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from ccfa.bib import BibRecord, load_records
from ccfa.cli import Problem, emit, tool_error

SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_bytes(path: Path, description: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"无法读取{description} {path}: {exc}") from exc


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
        connection.commit()
    finally:
        connection.close()


def build_index(library_dir: Path) -> dict:
    """Atomically rebuild index.db from refs.bib and notes/*.md."""
    library_dir = Path(library_dir)
    refs_path = library_dir / "refs.bib"
    refs_bytes = _read_bytes(refs_path, "BibTeX")
    refs_sha256 = hashlib.sha256(refs_bytes).hexdigest()
    parsed = load_records(refs_path)
    note_entries, notes_sha256 = _notes_snapshot(library_dir)
    note_text = {stem: text for stem, text, _relative in note_entries}
    stray_notes = sorted(
        relative
        for stem, _text, relative in note_entries
        if stem not in parsed.records
    )

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
    }


def _load_meta(index_path: Path) -> tuple:
    if not index_path.is_file():
        raise ValueError("索引不存在：请先运行 library index")
    try:
        connection = sqlite3.connect(index_path)
        try:
            row = connection.execute(
                "SELECT schema_version, refs_sha256, notes_sha256, built_at, "
                "entry_count FROM meta"
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
            return [
                row[0]
                for row in connection.execute("SELECT key FROM papers").fetchall()
            ]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ValueError(f"无法读取索引 {index_path}: {exc}") from exc


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


def search_index(library_dir: Path, query: str, limit: int = 20) -> dict:
    """Search a fresh index. Raises ValueError if it is missing or stale."""
    library_dir = Path(library_dir)
    if not isinstance(query, str):
        raise ValueError("查询必须是字符串")
    query = query.strip()
    if not query:
        raise ValueError("查询不能为空")
    if type(limit) is not int or limit < 1:
        raise ValueError("limit 必须是正整数")

    index_path = library_dir / "index.db"
    meta = _load_meta(index_path)
    _assert_fresh(library_dir, meta)

    try:
        connection = sqlite3.connect(index_path)
        try:
            mode, rows = _search_rows(connection, query, limit)
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ValueError(f"搜索索引失败 {index_path}: {exc}") from exc

    results = [
        {
            "key": row[0],
            "title": row[1],
            "year": row[2],
            "venue": row[3],
            "path": _pdf_relative(library_dir, row[0]),
        }
        for row in rows
    ]
    return {"query": query, "mode": mode, "results": results}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="索引和检索共享文献库")
    parser.add_argument(
        "--dir",
        default="library",
        help="文献库目录（默认: library）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "index",
        help="重建 index.db；这是派生数据、可重建，也是唯一允许覆盖的写路径",
        description=(
            "重建 index.db。它是派生数据、可重建，也是本工具唯一允许覆盖的写路径。"
        ),
    )
    search = subparsers.add_parser(
        "search",
        help="检索索引字段，不包含 PDF 全文",
        description=(
            "检索 key/title/authors/year/venue/abstract/notes；"
            "索引不含 PDF 全文。新鲜度只对 refs.bib 与 notes 负责；"
            "path 是结果字段、不参与检索，其取值在查询期按 "
            "papers/<key>.pdf 当前是否存在解析。"
        ),
    )
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    subparsers.add_parser(
        "check",
        help="只读审计 index.db 与 refs.bib/notes 的一致性",
        description=(
            "只读审计 index.db 与 refs.bib/notes 的一致性；本命令不写盘。"
        ),
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "index":
            summary = build_index(Path(args.dir))
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "check":
            return emit(check_library(Path(args.dir)))
        result = search_index(Path(args.dir), args.query, limit=args.limit)
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
