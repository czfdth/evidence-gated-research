"""Read and write ``ccfa.yaml`` stage transitions with an audit trail."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

from ccfa.cli import save_text_atomically, tool_error
from ccfa.stages import gate_for, stages_for


HISTORY_FIELDS = ("from", "to", "at", "reason", "kind")
HISTORY_KINDS = ("advance", "rollback")


def history_entry_problems(
    entry: object,
    index: int,
    stages: list[str] | None = None,
) -> list[str]:
    """Return validation problems for one ``stage.history`` entry."""
    where = f"stage.history[{index}]"
    if not isinstance(entry, dict):
        return [f"{where} 必须是映射"]

    problems: list[str] = []
    for field in HISTORY_FIELDS:
        if field not in entry:
            problems.append(f"{where} 缺少字段: {field}")
        elif not isinstance(entry[field], str) or not entry[field].strip():
            problems.append(f"{where}.{field} 必须是非空字符串")

    kind = entry.get("kind")
    if "kind" in entry and kind not in HISTORY_KINDS:
        problems.append(
            f"{where}.kind 非法: {kind!r}，应为 {' 或 '.join(HISTORY_KINDS)}"
        )

    if kind == "rollback":
        if "void_artifacts" not in entry:
            problems.append(f"{where} 缺少字段: void_artifacts")
        else:
            artifacts = entry["void_artifacts"]
            if not isinstance(artifacts, list) or any(
                not isinstance(item, str) or not item.strip()
                for item in artifacts
            ):
                problems.append(
                    f"{where}.void_artifacts 必须是非空字符串列表"
                )

    if stages is not None:
        from_stage = entry.get("from")
        to_stage = entry.get("to")
        for field, value in (("from", from_stage), ("to", to_stage)):
            if (
                isinstance(value, str)
                and value.strip()
                and value not in stages
            ):
                problems.append(
                    f"state-history-stage: {where}.{field} 不是合法 stage: "
                    f"{value!r}"
                )
        if (
            kind in HISTORY_KINDS
            and isinstance(from_stage, str)
            and isinstance(to_stage, str)
            and from_stage in stages
            and to_stage in stages
        ):
            from_index = stages.index(from_stage)
            to_index = stages.index(to_stage)
            if kind == "advance" and to_index <= from_index:
                problems.append(
                    f"state-history-direction: {where} kind=advance "
                    "必须严格向后推进"
                )
            if kind == "rollback" and to_index >= from_index:
                problems.append(
                    f"state-history-direction: {where} kind=rollback "
                    "必须严格向前回退"
                )
    return problems


def history_problems(
    history: object,
    mode: str | None = None,
) -> list[str]:
    """Return validation problems for a whole ``stage.history`` value."""
    if not isinstance(history, list):
        return ["stage.history 必须是列表"]
    stages = stages_for(mode) if mode is not None else None
    problems: list[str] = []
    for index, entry in enumerate(history):
        problems.extend(history_entry_problems(entry, index, stages=stages))
    return problems


def _read_state(paper_root: Path) -> tuple[Path, dict]:
    path = Path(paper_root) / "ccfa.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 解析失败于 {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    stage = data.get("stage")
    if not isinstance(stage, dict):
        raise ValueError(f"{path} 的 stage 必须是映射")

    mode, _stages = _mode_and_stages(data)
    problems = history_problems(stage.get("history", []), mode)
    if problems:
        raise ValueError("stage.history 非法: " + "; ".join(problems))
    return path, data


def _mode_and_stages(data: dict) -> tuple[str, list[str]]:
    venue = data.get("target_venue")
    if not isinstance(venue, dict):
        raise ValueError("target_venue 必须是映射")
    mode = venue.get("mode", "conference")
    if not isinstance(mode, str):
        raise ValueError(f"target_venue.mode 非法: {mode!r}")
    return mode, stages_for(mode)


def _current_stage(data: dict, stages: list[str]) -> str:
    stage = data["stage"]
    current = stage.get("current")
    if not isinstance(current, str) or current not in stages:
        raise ValueError(f"stage.current 非法: {current!r}")
    return current


def _require_confirm(confirm: object) -> None:
    if confirm is not True:
        raise ValueError("需要明确授权：请传入 --confirm")


def _require_reason(reason: object) -> str:
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason 必填且不能为空")
    return reason.strip()


def _void_artifacts(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError("void_artifacts 必须是非空字符串列表")
    return list(value)


def _write_state(path: Path, data: dict) -> None:
    text = yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    if not text.endswith("\n"):
        text += "\n"
    save_text_atomically(path, text, description="状态文件")


def _transition(
    paper_root: Path,
    *,
    to: str,
    reason: str,
    confirm: bool,
    kind: str,
    void_artifacts: list[str] | None = None,
) -> dict:
    _require_confirm(confirm)
    reason = _require_reason(reason)
    path, data = _read_state(paper_root)
    mode, stages = _mode_and_stages(data)
    current = _current_stage(data, stages)

    if not isinstance(to, str) or to not in stages:
        raise ValueError(f"目标 stage 非法: {to!r}")
    current_index = stages.index(current)
    target_index = stages.index(to)

    if kind == "advance":
        if target_index == current_index:
            raise ValueError("目标 stage 与当前 stage 相同")
        if target_index < current_index:
            raise ValueError("set-stage 只能推进到当前 stage 之后")
    elif target_index >= current_index:
        raise ValueError("rollback 只能回退到当前 stage 之前")

    at = date.today().isoformat()
    entry = {
        "from": current,
        "to": to,
        "at": at,
        "reason": reason,
        "kind": kind,
    }
    if kind == "rollback":
        entry["void_artifacts"] = void_artifacts or []

    history = list(data["stage"].get("history", []))
    history.append(entry)
    data["stage"]["current"] = to
    data["stage"]["gate"] = gate_for(mode, to).id
    data["stage"]["updated_at"] = at
    data["stage"]["history"] = history
    _write_state(path, data)

    result = dict(entry)
    result["gate"] = gate_for(mode, to).id
    return result


def set_stage(
    paper_root: Path,
    *,
    to: str,
    reason: str,
    confirm: bool,
) -> dict:
    """Advance the stage and append an ``advance`` history entry."""
    return _transition(
        Path(paper_root),
        to=to,
        reason=reason,
        confirm=confirm,
        kind="advance",
    )


def rollback(
    paper_root: Path,
    *,
    to: str,
    reason: str,
    confirm: bool,
    void_artifacts: list[str] | None = None,
) -> dict:
    """Roll back to an earlier stage and record explicitly voided artifacts."""
    return _transition(
        Path(paper_root),
        to=to,
        reason=reason,
        confirm=confirm,
        kind="rollback",
        void_artifacts=_void_artifacts(void_artifacts),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="写回论文 stage，并记录可审计的 advance/rollback history"
    )
    parser.add_argument("--paper-root", default=".")
    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set-stage", help="推进到后续 stage")
    set_parser.add_argument("to")
    set_parser.add_argument("--reason", required=True)
    set_parser.add_argument("--confirm", action="store_true")

    rollback_parser = subparsers.add_parser(
        "rollback",
        help="回退到更早的 stage",
    )
    rollback_parser.add_argument("to")
    rollback_parser.add_argument("--reason", required=True)
    rollback_parser.add_argument("--confirm", action="store_true")
    rollback_parser.add_argument(
        "--void-artifacts",
        action="append",
        default=[],
        help="作废产物路径，可重复",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "set-stage":
            result = set_stage(
                Path(args.paper_root),
                to=args.to,
                reason=args.reason,
                confirm=args.confirm,
            )
        else:
            result = rollback(
                Path(args.paper_root),
                to=args.to,
                reason=args.reason,
                confirm=args.confirm,
                void_artifacts=args.void_artifacts,
            )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
