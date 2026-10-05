"""Validate an accepted paper's conference-talk plan."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error


PLAN = Path("data/talk-plan.yaml")
CLAIM_REGISTRY = Path("data/claim-registry.yaml")
FIGURE_MANIFEST = Path("figures/manifest.yaml")
STATUSES = {"draft", "polished", "conference-ready"}
SLIDE_FIELDS = (
    "id",
    "title",
    "claim_ids",
    "figure_ids",
    "talking_points",
    "speaker_notes",
)


def _load_yaml(path: Path) -> dict:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    return payload


def _ids(paper_root: Path, path: Path, key: str, field: str) -> set[str]:
    if not (paper_root / path).is_file():
        return set()
    payload = _load_yaml(paper_root / path)
    values = payload.get(key)
    if not isinstance(values, list):
        return set()
    result = set()
    for item in values:
        if isinstance(item, dict) and isinstance(item.get(field), str):
            result.add(item[field])
    return result


def _string_list(value: object, *, allow_empty: bool = False) -> bool:
    if not isinstance(value, list):
        return False
    if not value and not allow_empty:
        return False
    return all(isinstance(item, str) and item.strip() for item in value)


def check(
    paper_root: Path,
    *,
    require_configured: bool = False,
) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    path = paper_root / PLAN
    if not path.is_file():
        if require_configured:
            return [
                Problem(
                    "talk-plan-missing",
                    str(path),
                    None,
                    "已进入需要口头报告的 tail stage，但没有 talk plan",
                )
            ], []
        return [], [
            Problem(
                "talk-plan-not-configured",
                str(path),
                None,
                "尚未配置 talk plan",
            )
        ]
    try:
        payload = _load_yaml(path)
    except ValueError as exc:
        return [Problem("talk-invalid", str(path), None, str(exc))], []
    problems: list[Problem] = []
    if payload.get("version") != 1:
        problems.append(
            Problem("talk-invalid", str(path), None, "version 必须是 1")
        )
    status = payload.get("status")
    if status not in STATUSES:
        problems.append(
            Problem("talk-invalid", str(path), None, "status 非法")
        )
    claim_ids = _ids(paper_root, CLAIM_REGISTRY, "claims", "id")
    figure_ids = _ids(paper_root, FIGURE_MANIFEST, "figures", "id") | _ids(
        paper_root,
        FIGURE_MANIFEST,
        "figures",
        "name",
    )
    slides = payload.get("slides")
    if not isinstance(slides, list) or not slides:
        problems.append(
            Problem("talk-invalid", str(path), None, "slides 必须是非空数组")
        )
    else:
        for index, slide in enumerate(slides):
            if not isinstance(slide, dict):
                problems.append(
                    Problem(
                        "talk-invalid",
                        str(path),
                        None,
                        f"slides[{index}] 必须是映射",
                    )
                )
                continue
            missing = [field for field in SLIDE_FIELDS if field not in slide]
            if missing:
                problems.append(
                    Problem(
                        "talk-invalid",
                        str(path),
                        None,
                        f"slides[{index}] 缺少字段: {', '.join(missing)}",
                    )
                )
                continue
            if not _string_list(slide.get("claim_ids")):
                problems.append(
                    Problem(
                        "talk-invalid",
                        str(path),
                        None,
                        f"slides[{index}].claim_ids 必须非空",
                    )
                )
            for claim_id in slide.get("claim_ids", []):
                if claim_id not in claim_ids:
                    problems.append(
                        Problem(
                            "talk-unknown-claim",
                            str(path),
                            None,
                            f"slide {slide.get('id')}: claim {claim_id!r} 不存在",
                        )
                    )
            if not _string_list(slide.get("figure_ids"), allow_empty=True):
                problems.append(
                    Problem(
                        "talk-invalid",
                        str(path),
                        None,
                        f"slides[{index}].figure_ids 必须是字符串数组",
                    )
                )
            for figure_id in slide.get("figure_ids", []):
                if figure_id not in figure_ids:
                    problems.append(
                        Problem(
                            "talk-unknown-figure",
                            str(path),
                            None,
                            f"slide {slide.get('id')}: figure {figure_id!r} 不存在",
                        )
                    )
            if not _string_list(slide.get("talking_points")):
                problems.append(
                    Problem(
                        "talk-invalid",
                        str(path),
                        None,
                        f"slides[{index}].talking_points 必须非空",
                    )
                )
            if status == "conference-ready" and not isinstance(
                slide.get("speaker_notes"),
                str,
            ):
                problems.append(
                    Problem(
                        "talk-conference-ready-incomplete",
                        str(path),
                        None,
                        "conference-ready 需要 speaker_notes",
                    )
                )
    qa = payload.get("qa")
    if status == "conference-ready" and (not isinstance(qa, list) or not qa):
        problems.append(
            Problem(
                "talk-conference-ready-incomplete",
                str(path),
                None,
                "conference-ready 需要非空 Q&A",
            )
        )
    return problems, []


def render_outline(payload: dict) -> str:
    lines = [
        "# Conference Talk Outline",
        "",
        f"- status: {payload.get('status', 'unknown')}",
        "",
    ]
    for slide in payload.get("slides", []):
        if not isinstance(slide, dict):
            continue
        lines.extend(
            [
                f"## {slide.get('id', '?')}: {slide.get('title', '')}",
                f"- Claims: {', '.join(slide.get('claim_ids', []))}",
                f"- Figures: {', '.join(slide.get('figure_ids', []))}",
                "- Talking points:",
            ]
        )
        lines.extend(
            f"  - {point}" for point in slide.get("talking_points", [])
        )
        lines.extend(
            [
                f"- Speaker notes: {slide.get('speaker_notes', '')}",
                "",
            ]
        )
    lines.extend(["# Q&A", ""])
    for item in payload.get("qa", []):
        if isinstance(item, dict):
            lines.extend(
                [
                    f"## {item.get('question', '')}",
                    item.get("answer", ""),
                    "",
                ]
            )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="talk pipeline validator")
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--paper-root", required=True)
    render = sub.add_parser("render")
    render.add_argument("--paper-root", required=True)
    render.add_argument("--out", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        paper_root = Path(args.paper_root)
        if args.command == "check":
            problems, advisories = check(paper_root)
            return emit(problems, advisories)
        payload = _load_yaml(paper_root / PLAN)
        Path(args.out).write_text(render_outline(payload), encoding="utf-8")
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
