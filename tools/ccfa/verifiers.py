"""Inventory the formal verification engines available to this workflow.

The workflow can machine-check proofs (``ccfa.formal_check``), but that only
works if a real engine is installed. Historically the host preflight stayed
green while every proof assistant was absent, which made the gap invisible
until a proof campaign reached the point of needing a checker. This module
turns that gap into an explicit, machine-readable inventory: which engines are
installed, which kind of reasoning each one enables, whether the current paper
actually declares it, and how to install the missing ones.

Detection is deliberately cheap and side-effect free. An engine counts as
available if one of its executables is on ``PATH`` or its Python module can be
imported by the interpreter running this tool. It is not a functional proof:
``available`` means the entry point exists, not that the engine reasons
correctly on a given problem.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from ccfa.cli import Problem, save_text_atomically, tool_error


LEDGER_RELATIVE_PATH = Path("data") / "formal-checks.yaml"
TIER_CORE = "core"
TIER_OPTIONAL = "optional"


@dataclass(frozen=True)
class Engine:
    """A formal reasoning engine the workflow knows how to invoke."""

    key: str
    kind: str
    capability: str
    executables: tuple[str, ...] = ()
    python_module: str | None = None
    wsl_probe: str | None = None
    tier: str = TIER_OPTIONAL
    install_hint: str = ""


@dataclass(frozen=True)
class EngineStatus:
    engine: Engine
    available: bool
    location: str | None
    detail: str


# z3 is deliberately the only ``core`` entry: it is small, pip-installable with
# no toolchain bootstrap, and expressive enough for bounded SMT propositions
# such as the arithmetic core of the flagship paper's Proposition 4. The heavy
# interactive provers are listed so that their absence is reported, not hidden.
FORMAL_ENGINES: tuple[Engine, ...] = (
    Engine(
        key="z3",
        kind="SMT",
        capability="有界命题与反例搜索（formal-check 的默认引擎）",
        python_module="z3",
        tier=TIER_CORE,
        install_hint="写入 tools/requirements.txt；安装：python -m pip install z3-solver",
    ),
    Engine(
        key="cvc5",
        kind="SMT",
        capability="SMT/量词与非线性算术的第二独立检查器",
        executables=("cvc5",),
        python_module="cvc5",
        install_hint="python -m pip install cvc5 或从 cvc5 官方下载二进制",
    ),
    Engine(
        key="lean",
        kind="proof-assistant",
        capability="交互式定理证明与可导出机器校验证明项（Lean 4）",
        executables=("lean", "lake"),
        install_hint="winget install Lean.Lean（安装 elan，首次运行再拉取 toolchain）",
    ),
    Engine(
        key="coq",
        kind="proof-assistant",
        capability="依赖类型定理证明（Coq/Rocq）",
        executables=("coqc", "coqtop"),
        install_hint="winget 未收录；用 opam 或从 https://coq.inria.fr/download 安装",
    ),
    Engine(
        key="isabelle",
        kind="proof-assistant",
        capability="高阶逻辑定理证明（Isabelle/HOL）",
        executables=("isabelle", "isabelle.exe", "Isabelle2025-2.exe"),
        install_hint="从 https://isabelle.in.tum.de 下载 7z SFX 并用 7z 解压，再把 bin 加进 PATH",
    ),
    Engine(
        key="agda",
        kind="proof-assistant",
        capability="依赖类型定理证明（Agda）",
        executables=("agda",),
        wsl_probe="command -v agda >/dev/null 2>&1 && agda --version",
        install_hint="WSL: apt-get install agda agda-stdlib；Windows 需 GHC+cabal",
    ),
    Engine(
        key="why3",
        kind="verification-platform",
        capability="把 WhyML 义务分派给多个 SMT/证明助手",
        executables=("why3",),
        wsl_probe="command -v why3 >/dev/null 2>&1 && why3 --version",
        install_hint="opam install why3 或 WSL: apt-get install why3",
    ),
    Engine(
        key="sage",
        kind="CAS",
        capability="符号代数、数论与大规模精确计算（SageMath）",
        executables=("sage",),
        wsl_probe="test -x /opt/sage/bin/sage && /opt/sage/bin/sage --version",
        install_hint="WSL: conda create -p /opt/sage -c conda-forge sage（Ubuntu 24.04 已移除 apt 包）",
    ),
    Engine(
        key="julia",
        kind="language",
        capability="数值与符号计算环境（Symbolics.jl 等）",
        executables=("julia",),
        install_hint="winget install Julialang.Julia",
    ),
)


def _default_module_probe(module: str) -> str | None:
    """Return a version string if *module* is importable, else ``None``."""
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        return None
    if spec is None:
        return None
    try:
        loaded = importlib.import_module(module)
    except Exception:
        # The module exists but self-reported a broken import; treat it as
        # present and let the real check surface the failure.
        return "present"
    version = getattr(loaded, "__version__", None)
    if isinstance(version, str) and version.strip():
        return version.strip()
    getter = getattr(loaded, "get_version_string", None)
    if callable(getter):
        try:
            rendered = str(getter()).strip()
        except Exception:
            rendered = ""
        if rendered:
            return rendered
    return "present"


def probe_engine(
    engine: Engine,
    *,
    which: Callable[[str], str | None] | None = None,
    module_probe: Callable[[str], str | None] | None = None,
    wsl_probe: Callable[[str], str | None] | None = None,
) -> EngineStatus:
    """Report whether *engine* is present on this host."""
    which = which or _default_which
    module_probe = module_probe or _default_module_probe
    for executable in engine.executables:
        found = which(executable)
        if found:
            return EngineStatus(
                engine,
                True,
                found,
                f"{executable} -> {found}",
            )
    if engine.python_module:
        version = module_probe(engine.python_module)
        if version is not None:
            location = f"python:{engine.python_module}"
            return EngineStatus(
                engine,
                True,
                location,
                f"module {engine.python_module} {version}",
            )
    if engine.wsl_probe and wsl_probe is not None:
        detail = wsl_probe(engine.wsl_probe)
        if detail:
            return EngineStatus(engine, True, "wsl", detail)
    return EngineStatus(engine, False, None, "未找到可执行文件或 Python 模块")


_WSL_DISTRO: str | None = None


def _wsl_distro() -> str | None:
    """Return the first registered WSL distro that is not Docker's internal one."""
    global _WSL_DISTRO
    if _WSL_DISTRO is not None:
        return _WSL_DISTRO or None
    try:
        completed = subprocess.run(
            ["wsl", "-l", "-q"],
            capture_output=True,
            text=True,
            encoding="utf-16-le",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        _WSL_DISTRO = ""
        return None
    for line in completed.stdout.splitlines():
        name = line.strip().strip("\x00")
        if not name or name.lower().startswith("docker-desktop"):
            continue
        _WSL_DISTRO = name
        return name
    _WSL_DISTRO = ""
    return None


def default_wsl_probe(command: str) -> str | None:
    """Run *command* inside WSL; return its first output line on success."""
    if os.name != "nt":
        return None
    distro = _wsl_distro()
    if not distro:
        return None
    try:
        completed = subprocess.run(
            [
                "wsl",
                "-d",
                distro,
                "-u",
                "root",
                "--",
                "bash",
                "-lc",
                command,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    text = completed.stdout.strip()
    if not text:
        return None
    first_line = text.splitlines()[0].strip()
    return f"{first_line} (WSL {distro})" if first_line else None


def _path_scan(name: str) -> str | None:
    """Find an extensionless launcher on PATH, which ``shutil.which`` misses.

    Windows resolves executables through ``PATHEXT``, so a plain shell script
    such as Isabelle's ``bin/isabelle`` is invisible to ``shutil.which``. Only
    the *default* locator does this scan; an injected ``which`` stays in full
    control so tests never depend on the host environment.
    """
    if os.name != "nt":
        return None
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        candidate = Path(entry) / name
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def _default_which(name: str) -> str | None:
    return shutil.which(name) or _path_scan(name)


def inventory(
    engines: tuple[Engine, ...] = FORMAL_ENGINES,
    *,
    which: Callable[[str], str | None] | None = None,
    module_probe: Callable[[str], str | None] | None = None,
    wsl_probe: Callable[[str], str | None] | None = None,
) -> list[EngineStatus]:
    return [
        probe_engine(
            engine,
            which=which,
            module_probe=module_probe,
            wsl_probe=wsl_probe,
        )
        for engine in engines
    ]


def _normalise_engine(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


def wired_engines(paper_root: Path) -> set[str]:
    """Return the engine names a paper declares in ``data/formal-checks.yaml``."""
    ledger = Path(paper_root) / LEDGER_RELATIVE_PATH
    if not ledger.is_file():
        return set()
    try:
        payload = yaml.safe_load(ledger.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return set()
    if not isinstance(payload, dict):
        return set()
    names: set[str] = set()
    checks = payload.get("checks")
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict):
                name = _normalise_engine(check.get("engine"))
                if name:
                    names.add(name)
    return names


def status_lines(
    statuses: list[EngineStatus],
    *,
    wired: set[str] | None = None,
) -> list[str]:
    wired = wired or set()
    lines: list[str] = []
    for status in statuses:
        key = status.engine.key
        marker = "*" if key in wired else " "
        level = "installed" if status.available else "MISSING  "
        lines.append(
            f"{level} {marker} {key:<8} {status.engine.kind:<20} {status.detail}"
        )
    return lines


def collect_problems(
    statuses: list[EngineStatus],
    *,
    wired: set[str] | None = None,
    strict: bool = False,
    required: tuple[str, ...] = (),
) -> tuple[list[Problem], list[Problem]]:
    """Split engine statuses into (problems, advisories).

    A missing engine is an advisory unless it is ``core``, explicitly required
    by the caller, or referenced by the paper's own formal-check ledger. The
    last case matters most: declaring a check that cannot run is not optional.
    """
    wired = wired or set()
    required_set = {name.strip().lower() for name in required if name.strip()}
    problems: list[Problem] = []
    advisories: list[Problem] = []
    for status in statuses:
        if status.available:
            continue
        key = status.engine.key
        mandatory = (
            strict
            or status.engine.tier == TIER_CORE
            or key in required_set
            or key in wired
        )
        if key in wired:
            reason = "论文在 formal-checks.yaml 中声明了该引擎，但本机不可用"
        elif status.engine.tier == TIER_CORE:
            reason = "核心形式化引擎不可用，formal-check 无法运行"
        else:
            reason = f"缺少 {key}：{status.engine.capability} 不可用"
        message = f"{reason}。安装：{status.engine.install_hint}"
        problem = Problem("verifier-missing", key, None, message)
        (problems if mandatory else advisories).append(problem)
    return problems, advisories


def build_report(
    statuses: list[EngineStatus],
    problems: list[Problem],
    advisories: list[Problem],
    *,
    wired: set[str] | None = None,
) -> dict:
    wired = wired or set()
    return {
        "problems": [dict(problem._asdict()) for problem in problems],
        "advisories": [dict(advisory._asdict()) for advisory in advisories],
        "problem_count": len(problems),
        "engines": [
            {
                "key": status.engine.key,
                "kind": status.engine.kind,
                "tier": status.engine.tier,
                "available": status.available,
                "location": status.location,
                "detail": status.detail,
                "install_hint": status.engine.install_hint,
                "wired": status.engine.key in wired,
            }
            for status in statuses
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="清点本机可用的形式化验证器，并对照论文声明的引擎"
    )
    parser.add_argument(
        "--paper-root",
        help="论文根目录；给出时会读取 data/formal-checks.yaml 判断哪些引擎被声明",
    )
    parser.add_argument("--out", help="把 JSON 报告写到该路径")
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        help="把指定引擎的缺失提升为 problem（可重复）",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="任何引擎缺失都算 problem（退 1），用于一次性装齐",
    )
    parser.add_argument(
        "--no-wsl",
        action="store_true",
        help="不探测 WSL 中安装的 Agda/Sage/Why3",
    )
    return parser


def main(
    argv: list[str],
    *,
    which: Callable[[str], str | None] | None = None,
    module_probe: Callable[[str], str | None] | None = None,
    wsl_probe: Callable[[str], str | None] | None = None,
) -> int:
    args = build_parser().parse_args(argv[1:])
    wired = wired_engines(Path(args.paper_root)) if args.paper_root else set()
    selected_wsl = None if args.no_wsl else wsl_probe
    statuses = inventory(
        which=which,
        module_probe=module_probe,
        wsl_probe=selected_wsl,
    )
    problems, advisories = collect_problems(
        statuses,
        wired=wired,
        strict=args.strict,
        required=tuple(args.require),
    )
    report = build_report(statuses, problems, advisories, wired=wired)
    for line in status_lines(statuses, wired=wired):
        print(line, file=sys.stderr)
    if args.out:
        try:
            save_text_atomically(
                Path(args.out),
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                description="形式化验证器清单",
            )
        except ValueError as exc:
            return tool_error(str(exc))
    print(json.dumps(report, ensure_ascii=False))
    for problem in problems:
        print(f"{problem.path}: {problem.code}: {problem.message}", file=sys.stderr)
    for advisory in advisories:
        print(
            f"{advisory.path}: advisory {advisory.code}: {advisory.message}",
            file=sys.stderr,
        )
    available = sum(1 for status in statuses if status.available)
    print(
        f"verifiers summary: {available}/{len(statuses)} engines available; "
        f"{len(problems)} problems, {len(advisories)} advisories",
        file=sys.stderr,
    )
    return 1 if problems else 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv, wsl_probe=default_wsl_probe))

