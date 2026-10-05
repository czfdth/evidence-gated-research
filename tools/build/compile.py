"""Compile a LaTeX project without latexmk.

latexmk is unavailable on this machine (it needs Perl). The build is an
explicit sequence so a failure can be attributed to a specific step.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CompileResult:
    ok: bool
    steps: list[tuple[str, int]] = field(default_factory=list)
    pdf: Path | None = None
    log_tail: str = ""


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout or ""


def _needs_bibtex(aux: Path) -> bool:
    if not aux.is_file():
        return False
    return "\\citation{" in aux.read_text(encoding="utf-8", errors="replace")


def compile_project(
    main_tex: Path,
    build_dir: Path,
    engine: str = "pdflatex",
) -> CompileResult:
    """Run latex, optionally bibtex, then latex twice more."""
    main_tex = Path(main_tex).resolve()
    if not main_tex.is_file():
        raise FileNotFoundError(f"找不到主文件: {main_tex}")
    if shutil.which(engine) is None:
        raise FileNotFoundError(f"找不到引擎: {engine}")

    build_dir = Path(build_dir).resolve()
    build_dir.mkdir(parents=True, exist_ok=True)

    stem = main_tex.stem
    base = [
        engine,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        f"-output-directory={build_dir}",
        str(main_tex),
    ]

    result = CompileResult(ok=False)
    transcript: list[str] = []

    code, out = _run(base, main_tex.parent)
    result.steps.append((engine, code))
    transcript.append(out)
    if code != 0:
        result.log_tail = out[-2000:]
        return result

    aux = build_dir / f"{stem}.aux"
    if _needs_bibtex(aux):
        # Run from the manuscript dir so relative \bibdata paths resolve the
        # same way they did for pdflatex; the .bbl is still written next to
        # the .aux in the build directory.
        bib_code, bib_out = _run(["bibtex", str(build_dir / stem)], main_tex.parent)
        result.steps.append(("bibtex", bib_code))
        transcript.append(bib_out)
        if bib_code != 0:
            result.log_tail = bib_out[-2000:]
            return result

    for _ in range(2):
        code, out = _run(base, main_tex.parent)
        result.steps.append((engine, code))
        transcript.append(out)
        if code != 0:
            result.log_tail = out[-2000:]
            return result

    pdf = build_dir / f"{stem}.pdf"
    result.ok = pdf.is_file()
    result.pdf = pdf if result.ok else None
    result.log_tail = "\n".join(transcript)[-2000:]
    return result
