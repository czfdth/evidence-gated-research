"""Verify every \\dataval tag against its live source.

Read-only: never edits the manuscript or the data files it reads.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from ccfa.cli import Problem, emit, tool_error
from ccfa.datasource import (
    SourceError,
    ToolEnvironmentError,
    load_source,
    navigate,
    resolve_within_base_dir,
)
from ccfa.dataval import Tag, find_tags, find_untagged
from ccfa.datavalue import DEFAULT_MAX_ROUNDING_ERROR, values_match
from ccfa.texscan import iter_tex_files

_TAG_ERRORS = (SourceError, OSError, ValueError, KeyError, IndexError, TypeError)


def _resolve(tag: Tag, base_dir: Path | None) -> object:
    try:
        source = resolve_within_base_dir(tag.source_path, base_dir)
        kind, data = load_source(source)
        return navigate(kind, data, tag.key_path)
    except _TAG_ERRORS as exc:
        raise SourceError(str(exc)) from exc


def _documents(paths: Iterable[str]) -> list[Path]:
    docs: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            raise ValueError(f"文档不存在或不是文件: {path}")
        try:
            with path.open("rb"):
                pass
        except OSError as exc:
            raise ValueError(f"文档不可读: {path}: {exc}") from exc
        docs.append(path)
    return docs


def check(
    docs: Iterable[Path],
    base_dir: Path | None = None,
    tolerance: float = 1e-9,
    rel_tolerance: float = 0.0,
    untagged: bool = False,
    max_rounding_error: float = DEFAULT_MAX_ROUNDING_ERROR,
) -> tuple[list[Problem], list[Problem]]:
    docs = list(docs)
    problems: list[Problem] = []
    for tag in find_tags(docs):
        try:
            actual = _resolve(tag, base_dir)
        except SourceError as exc:
            problems.append(
                Problem(
                    "dataval-error",
                    tag.path,
                    tag.line,
                    f"标签源不可解析（{tag.source_path}:{tag.key_path}）: {exc}",
                )
            )
            continue
        matches = values_match(
            tag.claimed,
            actual,
            tolerance,
            rel_tolerance,
            max_rounding_error,
        )
        if not matches:
            message = (
                f"标记值 {tag.claimed!r} 与源值 {str(actual)!r} 不符"
                f"（{tag.source_path}:{tag.key_path}）"
            )
            if max_rounding_error > 0 and values_match(
                tag.claimed,
                actual,
                tolerance,
                rel_tolerance,
                0.0,
            ):
                # It would have passed before the precision cap: say so, or the
                # author sees a mismatch that looks like the number is wrong.
                message += (
                    f"；小数位不足：该标记的舍入容差超过源值量级的"
                    f" {max_rounding_error:.0%}，把标记写到至少两位有效数字"
                    "（或用 --max-rounding-error 0 关掉这条上限）"
                )
            problems.append(
                Problem(
                    "dataval-mismatch",
                    tag.path,
                    tag.line,
                    message,
                )
            )
    advisories: list[Problem] = []
    if untagged:
        for doc in docs:
            for item in find_untagged(Path(doc)):
                advisories.append(
                    Problem(
                        "untagged-number",
                        item.path,
                        item.line,
                        f"未标记的数字线索（需人工复核）: {item.text}",
                    )
                )
    return problems, advisories


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="核验正文数字与源数据一致")
    parser.add_argument("--doc", action="append", dest="docs")
    parser.add_argument(
        "--manuscript",
        help="手稿目录；等价于对该目录下所有 .tex 逐个传 --doc",
    )
    parser.add_argument("--base-dir")
    parser.add_argument("--tolerance", type=float, default=1e-9)
    parser.add_argument("--rel-tolerance", type=float, default=0.0)
    parser.add_argument(
        "--max-rounding-error",
        type=float,
        default=DEFAULT_MAX_ROUNDING_ERROR,
        help=(
            "小数标记的舍入容差上限（占源值量级的比例，默认 0.05）；"
            "0 表示关闭该上限"
        ),
    )
    parser.add_argument("--untagged", action="store_true")
    args = parser.parse_args(argv[1:])

    try:
        if bool(args.docs) == bool(args.manuscript):
            raise ValueError("--doc 与 --manuscript 必须二选一")
        if args.manuscript:
            manuscript = Path(args.manuscript)
            if not manuscript.is_dir():
                raise ValueError(f"手稿目录不存在或不是目录: {manuscript}")
            docs = list(iter_tex_files(manuscript))
        else:
            docs = _documents(args.docs)
        base_dir = Path(args.base_dir) if args.base_dir else None
        if base_dir is not None and not base_dir.is_dir():
            raise ValueError(f"--base-dir 不存在或不是目录: {base_dir}")
        problems, advisories = check(
            docs,
            base_dir,
            args.tolerance,
            args.rel_tolerance,
            untagged=args.untagged,
            max_rounding_error=args.max_rounding_error,
        )
    except (ValueError, ToolEnvironmentError) as exc:
        return tool_error(str(exc))

    return emit(problems, advisories)


if __name__ == "__main__":
    # Windows consoles default to a locale code page; pin the contract streams.
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
