"""Record where each data file came from, and keep that record honest.

The store is a claim about real bytes; a checksum is what lets `check` notice
when the claim drifts. Writing is deliberately strict: atomic, and refusing to
overwrite an existing entry, because the record of a failed or superseded
source is itself evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ccfa.cli import (
    Problem,
    ToolEnvironmentError,
    emit,
    save_text_atomically,
    tool_error,
)

VALID_CLASSIFICATIONS = ("real", "rescaled-real", "documented-substitute")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest}"


def load_store(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"version": 1, "files": {}}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 store {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"store 不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("store 顶层必须是对象")
    if "version" not in data:
        raise ValueError("store 缺少 version 字段")
    if data["version"] != 1:
        raise ValueError(f"store version 不支持: {data['version']}")
    files = data.get("files")
    if not isinstance(files, dict):
        raise ValueError("store 的 files 必须是对象")
    for key, entry in files.items():
        if not isinstance(key, str):
            raise ValueError(f"store 条目的键必须是字符串: {key!r}")
        if not isinstance(entry, dict):
            raise ValueError(f"store 条目必须是对象: {key}")
    return data


def save_store(path: Path, store: dict) -> None:
    payload = json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    save_text_atomically(Path(path), payload, description="store")


def render_markdown(store: dict) -> str:
    lines = [
        "# 数据来源",
        "",
        "| 路径 | 分类 | 来源 | 字节 | sha256 | 登记时间 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for relpath, entry in sorted(store["files"].items()):
        digest = str(entry.get("sha256", ""))
        short = digest.split(":", 1)[-1][:12]
        lines.append(
            f"| {relpath} | {entry.get('classification', '')} | {entry.get('source', '')} "
            f"| {entry.get('size', '')} | {short} | {entry.get('recorded_at', '')} |"
        )
    return "\n".join(lines) + "\n"


def write_markdown(path: Path, text: str, force: bool = False) -> None:
    path = Path(path)
    if path.exists() and not force:
        raise ValueError(f"导出目标已存在: {path}（如需覆盖请显式使用 --force）")
    save_text_atomically(path, text, description="")


def add_entry(
    store_path: Path,
    paper_root: Path,
    relpath: str,
    *,
    source: str,
    classification: str,
    units: str | None = None,
    coverage: str | None = None,
    notes: str | None = None,
    force: bool = False,
) -> dict:
    if classification not in VALID_CLASSIFICATIONS:
        raise ValueError(
            f"classification 非法: {classification!r}，应为 {' / '.join(VALID_CLASSIFICATIONS)}"
        )
    if Path(relpath).is_absolute():
        raise ValueError(f"条目路径必须是相对 paper_root 的相对路径: {relpath}")
    target = Path(paper_root) / relpath
    if not target.is_file():
        raise ValueError(f"来源文件不存在: {target}")

    store = load_store(store_path)
    files = store.setdefault("files", {})
    if relpath in files and not force:
        raise ValueError(f"条目已存在: {relpath}（如需覆盖请显式使用 --force）")

    try:
        checksum = sha256_of(target)
        size = target.stat().st_size
    except OSError as exc:
        raise ValueError(f"无法读取来源文件 {target}: {exc}") from exc

    entry = {
        "source": source,
        "classification": classification,
        "sha256": checksum,
        "size": size,
        "recorded_at": _now_iso(),
    }
    for key, value in (("units", units), ("coverage", coverage), ("notes", notes)):
        if value is not None:
            entry[key] = value
    files[relpath] = entry
    save_store(store_path, store)
    return entry


def check_store(
    store_path: Path,
    paper_root: Path,
    *,
    scan_dir: Path | None = None,
) -> list[Problem]:
    store = load_store(store_path)
    problems: list[Problem] = []
    for relpath, entry in sorted(store["files"].items()):
        target = Path(paper_root) / relpath
        if not str(entry.get("source", "")).strip():
            problems.append(
                Problem("provenance-missing-source", str(target), None, f"条目缺少来源: {relpath}")
            )
        classification = entry.get("classification")
        if classification not in VALID_CLASSIFICATIONS:
            problems.append(
                Problem(
                    "provenance-invalid-classification",
                    str(target),
                    None,
                    f"条目分类非法: {classification!r}（{relpath}）",
                )
            )
        if not target.is_file():
            problems.append(
                Problem("provenance-missing-file", str(target), None, f"来源文件不存在: {relpath}")
            )
            continue
        try:
            actual = sha256_of(target)
        except OSError as exc:
            raise ValueError(f"无法读取来源文件 {target}: {exc}") from exc
        if actual != entry.get("sha256"):
            problems.append(
                Problem(
                    "provenance-drift",
                    str(target),
                    None,
                    f"文件内容与记录不符: {relpath}（记录 {entry.get('sha256')}，实际 {actual}）",
                )
            )
    if scan_dir is not None:
        scan_root = Path(scan_dir)
        if not scan_root.is_absolute():
            scan_root = Path(paper_root) / scan_root
        try:
            if not scan_root.is_dir():
                raise ValueError(f"扫描目录不存在或不是目录: {scan_root}")
            scanned = sorted(path for path in scan_root.rglob("*") if path.is_file())
        except OSError as exc:
            raise ValueError(f"无法扫描目录 {scan_root}: {exc}") from exc

        resolved_root = Path(paper_root).resolve()
        resolved_store = Path(store_path).resolve()
        ignored = {
            resolved_store,
            resolved_store.with_suffix(".md"),
        }
        recorded = set(store["files"])
        for path in scanned:
            try:
                resolved_path = path.resolve()
                relpath = resolved_path.relative_to(resolved_root).as_posix()
            except (OSError, ValueError) as exc:
                raise ValueError(f"扫描文件不在 paper-root 内: {path}") from exc
            if resolved_path in ignored:
                continue
            if relpath not in recorded:
                problems.append(
                    Problem(
                        "provenance-unrecorded",
                        str(path),
                        None,
                        f"数据文件未登记: {relpath}",
                    )
                )
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="数据来源记录与核对")
    parser.add_argument("--store", required=True)
    parser.add_argument("--paper-root", required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="登记一个数据文件的来源")
    add.add_argument("relpath")
    add.add_argument("--source", required=True)
    add.add_argument("--classification", required=True, choices=VALID_CLASSIFICATIONS)
    add.add_argument("--units")
    add.add_argument("--coverage")
    add.add_argument("--notes")
    add.add_argument("--force", action="store_true")

    check = sub.add_parser("check", help="核对已登记文件的内容")
    check.add_argument("--scan", help="递归扫描目录，报告未登记的数据文件")

    export = sub.add_parser("export", help="导出人读的来源文档")
    export.add_argument("--out")
    export.add_argument("--force", action="store_true")

    args = parser.parse_args(argv[1:])
    try:
        if args.command == "add":
            add_entry(
                Path(args.store),
                Path(args.paper_root),
                args.relpath,
                source=args.source,
                classification=args.classification,
                units=args.units,
                coverage=args.coverage,
                notes=args.notes,
                force=args.force,
            )
            return emit([], [])
        if args.command == "check":
            return emit(
                check_store(
                    Path(args.store),
                    Path(args.paper_root),
                    scan_dir=Path(args.scan) if args.scan else None,
                ),
                [],
            )
        if args.command == "export":
            store = load_store(Path(args.store))
            if args.out:
                write_markdown(Path(args.out), render_markdown(store), force=args.force)
                return emit([], [])
            print(render_markdown(store))
            return 0
    except (ValueError, ToolEnvironmentError) as exc:
        return tool_error(str(exc))
    return tool_error(f"未知子命令: {args.command}")


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
