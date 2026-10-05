"""Drive the explicit pdflatex -> bibtex -> pdflatex -> pdflatex sequence.

latexmk is unavailable on this host (it needs Perl), and an explicit sequence
also makes it obvious which step failed. The runner is injectable so tests
never need a real LaTeX installation.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable, NamedTuple

Runner = Callable[[list[str], Path], "tuple[int, str]"]

_ENGINES = ("pdflatex", "xelatex")


class CompileStep(NamedTuple):
    name: str
    status: str
    returncode: int


class CompileReport(NamedTuple):
    engine: str
    steps: list[CompileStep]


def find_engine(preferred: str | None = None) -> str | None:
    for name in (preferred,) if preferred else _ENGINES:
        if name and shutil.which(name):
            return name
    return None


def _default_runner(argv: list[str], cwd: Path) -> tuple[int, str]:
    result = subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, errors="replace"
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _has_bibdata(aux: Path) -> bool:
    try:
        return "\\bibdata" in aux.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def compile_document(tex: Path, engine: str, runner: Runner | None = None) -> CompileReport:
    tex = Path(tex)
    run = runner or _default_runner
    cwd = tex.parent
    steps: list[CompileStep] = []

    code, _ = run([engine, "-interaction=nonstopmode", tex.name], cwd)
    steps.append(CompileStep(engine, "ran" if code == 0 else "failed", code))
    if code != 0:
        return CompileReport(engine, steps)

    aux = cwd / f"{tex.stem}.aux"
    if _has_bibdata(aux):
        code, _ = run(["bibtex", tex.stem], cwd)
        steps.append(CompileStep("bibtex", "ran" if code == 0 else "failed", code))
        if code != 0:
            return CompileReport(engine, steps)
    else:
        steps.append(CompileStep("bibtex", "skipped", 0))

    for _ in range(2):
        code, _ = run([engine, "-interaction=nonstopmode", tex.name], cwd)
        steps.append(CompileStep(engine, "ran" if code == 0 else "failed", code))
        if code != 0:
            return CompileReport(engine, steps)

    return CompileReport(engine, steps)
