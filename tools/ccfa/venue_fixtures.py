"""Validate and seed official venue methodology checklist fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, save_text_atomically, tool_error


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "checklists"
ITEM_FIELDS = ("id", "category", "requirement", "required")


def _load(path: Path) -> dict:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取 fixture {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    return payload


def list_fixtures() -> list[dict]:
    fixtures = []
    for path in sorted(FIXTURES_DIR.glob("*.yaml")):
        try:
            payload = _load(path)
        except ValueError:
            continue
        fixtures.append(
            {
                "name": path.stem,
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "venue": payload.get("venue"),
                "item_count": len(payload.get("items", []))
                if isinstance(payload.get("items"), list)
                else 0,
            }
        )
    return fixtures


def check_fixture(path: Path) -> tuple[list[Problem], list[Problem]]:
    path = Path(path)
    try:
        payload = _load(path)
    except ValueError as exc:
        return [Problem("venue-fixture-invalid", str(path), None, str(exc))], []
    problems: list[Problem] = []
    if payload.get("version") != 1:
        problems.append(
            Problem("venue-fixture-invalid", str(path), None, "version 必须是 1")
        )
    for field in ("venue", "source"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            problems.append(
                Problem(
                    "venue-fixture-invalid",
                    str(path),
                    None,
                    f"{field} 必须是非空字符串",
                )
            )
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        problems.append(
            Problem("venue-fixture-invalid", str(path), None, "items 必须是非空数组")
        )
        return problems, []
    seen = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(
                Problem(
                    "venue-fixture-invalid",
                    str(path),
                    None,
                    f"items[{index}] 必须是映射",
                )
            )
            continue
        missing = [field for field in ITEM_FIELDS if field not in item]
        if missing:
            problems.append(
                Problem(
                    "venue-fixture-invalid",
                    str(path),
                    None,
                    f"items[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        item_id = item.get("id")
        if item_id in seen:
            problems.append(
                Problem(
                    "venue-fixture-invalid",
                    str(path),
                    None,
                    f"items[{index}].id 重复: {item_id!r}",
                )
            )
        seen.add(item_id)
        if type(item.get("required")) is not bool:
            problems.append(
                Problem(
                    "venue-fixture-invalid",
                    str(path),
                    None,
                    f"items[{index}].required 必须是布尔值",
                )
            )
    return problems, []


def seed_checklist(
    paper_root: Path,
    fixture_path: Path,
    *,
    force: bool = False,
) -> dict:
    paper_root = Path(paper_root).resolve()
    payload = _load(Path(fixture_path))
    problems, _advisories = check_fixture(Path(fixture_path))
    if problems:
        raise ValueError(problems[0].message)
    out = paper_root / "data" / "venue-checklist.yaml"
    if out.exists() and not force:
        raise ValueError(f"venue checklist 已存在: {out}")
    items = []
    for item in payload["items"]:
        items.append(
            {
                "id": item["id"],
                "requirement": item["requirement"],
                "status": "pending",
                "evidence": [],
                "owner": "",
                "category": item["category"],
                "required": item["required"],
            }
        )
    seeded = {
        "version": 1,
        "venue": payload["venue"],
        "source": payload["source"],
        "items": items,
    }
    save_text_atomically(
        out,
        yaml.safe_dump(seeded, sort_keys=False, allow_unicode=True),
        description="venue checklist",
    )
    return {
        "path": str(out),
        "venue": payload["venue"],
        "item_count": len(items),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="venue checklist fixtures")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    check = sub.add_parser("check")
    check.add_argument("--fixture", required=True)
    seed = sub.add_parser("seed")
    seed.add_argument("--paper-root", required=True)
    seed.add_argument("--fixture", required=True)
    seed.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "list":
            print(json.dumps(list_fixtures(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "check":
            problems, advisories = check_fixture(Path(args.fixture))
            return emit(problems, advisories)
        result = seed_checklist(
            Path(args.paper_root),
            Path(args.fixture),
            force=args.force,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
