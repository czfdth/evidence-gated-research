"""Structural checks and optional compilation for a LaTeX manuscript.

Read-only unless --compile is given; compilation writes only inside the
manuscript directory, which is normal LaTeX behaviour.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ccfa.cli import Problem, ToolEnvironmentError, emit, tool_error
from ccfa.latex_compile import compile_document, find_engine
from ccfa.latex_structure import (
    check_citations,
    check_figures,
    find_stray_percent,
    scan_structure,
)
from ccfa.texscan import iter_tex_files


def _resolve_main(manuscript: Path, main: str) -> Path:
    """Resolve a manuscript-relative main file without escaping its root."""
    raw = Path(main)
    if raw.is_absolute():
        raise ValueError(f"--main 必须是手稿目录下的相对路径: {main!r}")
    root = manuscript.resolve()
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"--main 逃出手稿目录: {main!r}") from exc
    if not candidate.is_file():
        raise ValueError(f"找不到主文件: {candidate}")
    return candidate


def check(
    manuscript: Path,
    bib: Path | None = None,
    figures_root: Path | None = None,
    compile: bool = False,
    engine: str | None = None,
    main: str = "main.tex",
) -> tuple[list[Problem], list[Problem]]:
    manuscript = Path(manuscript)
    if not manuscript.is_dir():
        raise ValueError(f"手稿目录不存在或不是目录: {manuscript}")
    paths = iter_tex_files(manuscript)
    problems: list[Problem] = []
    for path in paths:
        problems.extend(scan_structure(path))
    if bib is not None:
        problems.extend(check_citations(paths, Path(bib)))
    root = Path(figures_root) if figures_root else manuscript
    problems.extend(check_figures(paths, root))
    advisories: list[Problem] = []
    for path in paths:
        advisories.extend(find_stray_percent(path))
    if compile:
        chosen = find_engine(engine)
        if chosen is None:
            raise ToolEnvironmentError("找不到 LaTeX 引擎（尝试过 pdflatex / xelatex）")
        main_tex = _resolve_main(manuscript, main)
        try:
            report = compile_document(main_tex, chosen)
        except OSError as exc:
            raise ToolEnvironmentError(f"编译工具不可用: {exc}") from exc
        for step in report.steps:
            if step.status == "failed":
                problems.append(
                    Problem(
                        "compile-failed",
                        str(main_tex),
                        None,
                        f"{step.name} 退出码 {step.returncode}",
                    )
                )
    return problems, advisories


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="检查 LaTeX 手稿结构与编译")
    parser.add_argument("--manuscript", required=True)
    parser.add_argument("--bib")
    parser.add_argument("--figures-root")
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("--engine")
    parser.add_argument(
        "--main",
        default="main.tex",
        help="手稿目录下的相对主文件路径（默认: main.tex）",
    )
    args = parser.parse_args(argv[1:])
    if args.main != "main.tex" and not args.compile:
        return tool_error("--main 仅在 --compile 时生效")
    try:
        problems, advisories = check(
            Path(args.manuscript),
            Path(args.bib) if args.bib else None,
            Path(args.figures_root) if args.figures_root else None,
            compile=args.compile,
            engine=args.engine,
            main=args.main,
        )
    except (ValueError, ToolEnvironmentError) as exc:
        return tool_error(str(exc))
    return emit(problems, advisories)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
