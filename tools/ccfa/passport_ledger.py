"""Append-only hash-chained passport ledger for handoff-critical events."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, save_text_atomically, tool_error


LEDGER = Path("ccfa-workfiles") / "passport" / "run-ledger.yaml"
KINDS = {
    "initial_instructions",
    "checkpoint_opened",
    "checkpoint_closed",
    "partial_answer",
    "tool_receipt",
    "progress",
    "file_reference",
}
REQUIRED_DATA = {
    "initial_instructions": ("user_words",),
    "checkpoint_opened": ("checkpoint_id", "stage", "checkpoint_type", "question"),
    "checkpoint_closed": ("checkpoint_id", "answer", "user_words"),
    "partial_answer": ("checkpoint_id", "item_id", "answer", "user_words"),
    "tool_receipt": ("step", "command", "status"),
    "progress": ("counters",),
    "file_reference": ("path", "sha256", "role"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(payload: dict) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash(entry: dict) -> str:
    return hashlib.sha256(
        _canonical({key: value for key, value in entry.items() if key != "hash"})
        .encode("utf-8")
    ).hexdigest()


def _load(path: Path) -> dict:
    if not path.is_file():
        return {"version": 1, "entries": []}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取 passport ledger: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("passport ledger 顶层或 version 非法")
    if not isinstance(payload.get("entries"), list):
        raise ValueError("passport ledger entries 必须是数组")
    return payload


def _validate_entry(
    entry: dict,
    previous_hash: str | None,
    sequence: int,
) -> list[Problem]:
    problems: list[Problem] = []
    kind = entry.get("kind")
    if kind not in KINDS:
        return [
            Problem("passport-invalid", "ledger", sequence, f"kind 非法: {kind!r}")
        ]
    if entry.get("seq") != sequence:
        problems.append(
            Problem("passport-sequence-mismatch", "ledger", sequence, "seq 不连续")
        )
    if entry.get("prev_hash") != previous_hash:
        problems.append(
            Problem("passport-chain-mismatch", "ledger", sequence, "prev_hash 不一致")
        )
    if entry.get("hash") != _hash(entry):
        problems.append(
            Problem("passport-chain-mismatch", "ledger", sequence, "entry hash 不一致")
        )
    data = entry.get("data")
    if not isinstance(data, dict):
        problems.append(
            Problem("passport-invalid", "ledger", sequence, "data 必须是对象")
        )
        return problems
    for field in REQUIRED_DATA[kind]:
        if field not in data:
            problems.append(
                Problem("passport-invalid", "ledger", sequence, f"data 缺少 {field}")
            )
    if kind == "tool_receipt" and data.get("status") not in {"passed", "failed", "not_run"}:
        problems.append(
            Problem("passport-invalid", "ledger", sequence, "tool_receipt.status 非法")
        )
    return problems


def append_event(paper_root: Path, *, kind: str, data: dict) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind 非法: {kind!r}")
    if not isinstance(data, dict):
        raise ValueError("data 必须是对象")
    for field in REQUIRED_DATA[kind]:
        if field not in data:
            raise ValueError(f"{kind} 缺少字段: {field}")
    paper_root = Path(paper_root).resolve()
    path = paper_root / LEDGER
    ledger = _load(path)
    entries = ledger["entries"]
    previous_hash = entries[-1]["hash"] if entries else None
    entry = {
        "seq": len(entries) + 1,
        "kind": kind,
        "at": _now_iso(),
        "data": data,
        "prev_hash": previous_hash,
    }
    entry["hash"] = _hash(entry)
    entries.append(entry)
    save_text_atomically(
        path,
        yaml.safe_dump(ledger, sort_keys=False, allow_unicode=True),
        description="passport ledger",
    )
    return entry


def check_ledger(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    path = paper_root / LEDGER
    if not path.is_file():
        return [], [
            Problem("passport-not-configured", str(path), None, "passport ledger 不存在")
        ]
    try:
        ledger = _load(path)
    except ValueError as exc:
        return [Problem("passport-invalid", str(path), None, str(exc))], []
    problems: list[Problem] = []
    previous_hash: str | None = None
    for index, entry in enumerate(ledger["entries"], start=1):
        if not isinstance(entry, dict):
            problems.append(
                Problem("passport-invalid", str(path), index, "entry 必须是对象")
            )
            continue
        problems.extend(_validate_entry(entry, previous_hash, index))
        previous_hash = entry.get("hash")
    return problems, []


def render_ledger(paper_root: Path) -> str:
    ledger = _load(Path(paper_root) / LEDGER)
    lines = ["# Passport Ledger", ""]
    for entry in ledger["entries"]:
        if not isinstance(entry, dict):
            continue
        lines.append(
            f"- {entry.get('seq')}. `{entry.get('kind')}` at {entry.get('at')}: "
            + json.dumps(entry.get("data", {}), ensure_ascii=False, sort_keys=True)
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="passport run ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    append = sub.add_parser("append")
    append.add_argument("--paper-root", required=True)
    append.add_argument("--kind", required=True, choices=sorted(KINDS))
    append.add_argument("--data-json", required=True)
    check = sub.add_parser("check")
    check.add_argument("--paper-root", required=True)
    render = sub.add_parser("render")
    render.add_argument("--paper-root", required=True)
    render.add_argument("--out", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "append":
            data = json.loads(args.data_json)
            result = append_event(Path(args.paper_root), kind=args.kind, data=data)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "check":
            problems, advisories = check_ledger(Path(args.paper_root))
            return emit(problems, advisories)
        Path(args.out).write_text(
            render_ledger(Path(args.paper_root)),
            encoding="utf-8",
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
