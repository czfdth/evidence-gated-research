"""Maintain an append-only, hash-chained peer ledger for experiment runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from ccfa.cli import Problem, emit, tool_error


LEDGER_NAME = "run-ledger.jsonl"
LOG_DIR = Path("experiments") / "log"


def _canonical(payload: dict) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record_sha256(record: dict) -> str:
    return _sha256_text(_canonical(record))


def _entry_hash(entry: dict) -> str:
    without_hash = {key: value for key, value in entry.items() if key != "hash"}
    return _sha256_text(_canonical(without_hash))


def _ledger_path(paper_root: Path) -> Path:
    return Path(paper_root) / LOG_DIR / LEDGER_NAME


def _read_ledger(
    path: Path,
    *,
    missing_ok: bool = False,
) -> tuple[list[dict], list[Problem]]:
    if not path.is_file():
        if missing_ok:
            return [], []
        return [], [
            Problem("run-ledger-missing", str(path), None, "run ledger 不存在")
        ]
    entries: list[dict] = []
    problems: list[Problem] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(
                Problem(
                    "run-ledger-malformed",
                    str(path),
                    line_number,
                    f"JSON 非法: {exc}",
                )
            )
            continue
        if not isinstance(entry, dict):
            problems.append(
                Problem(
                    "run-ledger-malformed",
                    str(path),
                    line_number,
                    "ledger entry 必须是对象",
                )
            )
            continue
        entries.append(entry)
    return entries, problems


def _validate_chain(path: Path, entries: list[dict]) -> list[Problem]:
    problems: list[Problem] = []
    previous_hash: str | None = None
    required = (
        "seq",
        "kind",
        "at",
        "run_id",
        "record_path",
        "record_sha256",
        "prev_hash",
        "hash",
    )
    for index, entry in enumerate(entries, start=1):
        missing = [field for field in required if field not in entry]
        if missing:
            problems.append(
                Problem(
                    "run-ledger-malformed",
                    str(path),
                    index,
                    f"entry 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        if entry.get("seq") != index:
            problems.append(
                Problem(
                    "run-ledger-sequence-mismatch",
                    str(path),
                    index,
                    f"seq 应为 {index}，实际 {entry.get('seq')!r}",
                )
            )
        if entry.get("prev_hash") != previous_hash:
            problems.append(
                Problem(
                    "run-ledger-chain-mismatch",
                    str(path),
                    index,
                    "prev_hash 与上一条 hash 不一致",
                )
            )
        if entry.get("hash") != _entry_hash(entry):
            problems.append(
                Problem(
                    "run-ledger-chain-mismatch",
                    str(path),
                    index,
                    "entry hash 与内容不一致",
                )
            )
        if entry.get("kind") != "tool_receipt":
            problems.append(
                Problem(
                    "run-ledger-malformed",
                    str(path),
                    index,
                    f"kind 非法: {entry.get('kind')!r}",
                )
            )
        previous_hash = entry.get("hash")
    return problems


def _load_records(paper_root: Path) -> tuple[dict[str, dict], list[Problem]]:
    log_dir = Path(paper_root) / LOG_DIR
    records: dict[str, dict] = {}
    problems: list[Problem] = []
    if not log_dir.is_dir():
        return records, [
            Problem(
                "run-ledger-log-dir-missing",
                str(log_dir),
                None,
                "experiments/log 目录不存在",
            )
        ]
    for path in sorted(log_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(
                Problem(
                    "run-ledger-record-malformed",
                    str(path),
                    None,
                    f"run record 不可读: {exc}",
                )
            )
            continue
        if not isinstance(payload, dict):
            problems.append(
                Problem(
                    "run-ledger-record-malformed",
                    str(path),
                    None,
                    "run record 顶层必须是对象",
                )
            )
            continue
        run_id = payload.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            problems.append(
                Problem(
                    "run-ledger-record-malformed",
                    str(path),
                    None,
                    "run record 缺少 run_id",
                )
            )
            continue
        records[run_id] = payload
    return records, problems


def _make_entry(
    sequence: int,
    previous_hash: str | None,
    record_path: Path,
    record: dict,
) -> dict:
    entry = {
        "seq": sequence,
        "kind": "tool_receipt",
        "at": record.get("started_at")
        or record.get("finished_at")
        or "1970-01-01T00:00:00Z",
        "run_id": record["run_id"],
        "record_path": record_path.name,
        "record_sha256": _record_sha256(record),
        "command": record.get("command", []),
        "status": record.get("status", "unknown"),
        "exit_status": record.get("exit_code"),
        "prev_hash": previous_hash,
    }
    entry["hash"] = _entry_hash(entry)
    return entry


def sync_ledger(paper_root: Path) -> dict:
    """Append missing or changed run records to the hash chain."""
    paper_root = Path(paper_root).resolve()
    records, record_problems = _load_records(paper_root)
    if record_problems:
        raise ValueError(record_problems[0].message)
    ledger_path = _ledger_path(paper_root)
    entries, problems = _read_ledger(ledger_path, missing_ok=True)
    problems.extend(_validate_chain(ledger_path, entries))
    if problems:
        raise ValueError(problems[0].message)
    latest: dict[str, dict] = {}
    for entry in entries:
        latest[entry["run_id"]] = entry
    appended = 0
    previous_hash = entries[-1]["hash"] if entries else None
    sequence = len(entries) + 1
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
        for run_id in sorted(records):
            record = records[run_id]
            digest = _record_sha256(record)
            if latest.get(run_id, {}).get("record_sha256") == digest:
                continue
            entry = _make_entry(
                sequence,
                previous_hash,
                (paper_root / LOG_DIR / f"{run_id}.json"),
                record,
            )
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            entries.append(entry)
            latest[run_id] = entry
            previous_hash = entry["hash"]
            sequence += 1
            appended += 1
    return {
        "appended": appended,
        "ledger": str(ledger_path),
        "entries": len(entries),
    }


def check_ledger(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    ledger_path = _ledger_path(paper_root)
    entries, problems = _read_ledger(ledger_path)
    problems.extend(_validate_chain(ledger_path, entries))
    records, record_problems = _load_records(paper_root)
    problems.extend(record_problems)
    latest: dict[str, dict] = {}
    for entry in entries:
        run_id = entry.get("run_id")
        if isinstance(run_id, str):
            latest[run_id] = entry
    for run_id, record in records.items():
        entry = latest.get(run_id)
        if entry is None:
            problems.append(
                Problem(
                    "run-ledger-missing-record",
                    str(ledger_path),
                    None,
                    f"run record 未进入 ledger: {run_id}",
                )
            )
        elif entry.get("record_sha256") != _record_sha256(record):
            problems.append(
                Problem(
                    "run-ledger-stale-record",
                    str(ledger_path),
                    None,
                    f"run record 已变化但 ledger 未更新: {run_id}",
                )
            )
    for run_id in sorted(set(latest) - set(records)):
        problems.append(
            Problem(
                "run-ledger-orphan-record",
                str(ledger_path),
                None,
                f"ledger 指向不存在的 run record: {run_id}",
            )
        )
    return problems, []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="hash-chained run ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("sync", "check"):
        item = sub.add_parser(name)
        item.add_argument("--paper-root", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "sync":
            result = sync_ledger(Path(args.paper_root))
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        problems, advisories = check_ledger(Path(args.paper_root))
        return emit(problems, advisories)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
