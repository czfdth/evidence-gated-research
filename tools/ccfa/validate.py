"""Validate ccfa.yaml against the project state contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from ccfa.milestones import parse_deadline
from ccfa.state import history_problems

REQUIRED_TOP_LEVEL = [
    "version",
    "project",
    "target_venue",
    "stage",
    "artifacts",
    "claims",
    "experiments",
    "reviews",
    "revision_ledger",
    "submission_checks",
]

VALID_MODES = ("conference", "journal")
REQUIRED_VENUE_FIELDS = ("name", "year", "mode")


def validate_yaml(path: Path) -> list[str]:
    """Return a list of problems; empty means valid.

    Raises ValueError when the file cannot be parsed, so a parse failure is
    never confused with a clean pass.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 解析失败: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("顶层必须是一个映射")

    problems: list[str] = []

    for field in REQUIRED_TOP_LEVEL:
        if field not in data:
            problems.append(f"缺少顶层字段: {field}")

    venue = data.get("target_venue")
    if isinstance(venue, dict):
        for field in REQUIRED_VENUE_FIELDS:
            if not venue.get(field):
                problems.append(f"target_venue.{field} 不能为空")
        mode = venue.get("mode")
        if mode and mode not in VALID_MODES:
            problems.append(
                f"target_venue.mode 非法: {mode!r}，应为 {' 或 '.join(VALID_MODES)}"
            )
        if "deadline" in venue and venue.get("deadline") is not None:
            try:
                parse_deadline(venue.get("deadline"))
            except ValueError:
                problems.append(
                    f"target_venue.deadline 非法: {venue.get('deadline')!r}，"
                    "必须是 YYYY-MM-DD 日期字符串"
                )
    elif "target_venue" in data:
        problems.append("target_venue 必须是映射")

    stage = data.get("stage")
    if isinstance(stage, dict):
        current = stage.get("current")
        if current:
            from ccfa.stages import stages_for

            mode = venue.get("mode", "conference") if isinstance(venue, dict) else "conference"
            if mode in VALID_MODES and current not in stages_for(mode):
                problems.append(f"stage.current 不适用于 {mode} 模式: {current!r}")
        history_mode = mode if mode in VALID_MODES else None
        problems.extend(history_problems(stage.get("history", []), history_mode))
    elif "stage" in data:
        problems.append("stage 必须是映射")

    for list_field in ("claims", "experiments", "reviews"):
        value = data.get(list_field)
        if value is not None and not isinstance(value, list):
            problems.append(f"{list_field} 必须是列表")

    return problems


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] in ("-h", "--help"):
        print("usage: validate.py <ccfa.yaml 路径>")
        print("校验 ccfa.yaml 的结构、stage 与 gate 状态")
        print("位置参数:")
        print("  <ccfa.yaml 路径>  要校验的状态文件")
        return 0

    if len(argv) != 2:
        print("用法: validate.py <ccfa.yaml 路径>", file=sys.stderr)
        return 2

    path = Path(argv[1])
    if not path.is_file():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 2

    try:
        problems = validate_yaml(path)
    except ValueError as exc:
        print(f"工具错误: {exc}", file=sys.stderr)
        return 2

    # Machine-readable stdout; the human summary stays on stderr, as every
    # other tool in this repo promises.
    report = {
        "path": str(path),
        "problems": [
            {
                "code": "schema-invalid",
                "path": str(path),
                "line": None,
                "message": message,
            }
            for message in problems
        ],
        "advisories": [],
        "problem_count": len(problems),
    }
    print(json.dumps(report, ensure_ascii=False))
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
