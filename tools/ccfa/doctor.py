"""Report which platform pieces this workflow needs and which are absent.

The workflow is deliberately coupled to a few local tools (git, a LaTeX
toolchain, codex, Docker, nvidia-smi) and to two virtualenvs. When one is
missing, the failure shows up later as a confusing crash inside an unrelated
step, so this preflight names what is absent and which capability it disables.

The report uses explicit capability levels. ``installed`` only means a command
is on ``PATH`` or a venv interpreter exists. ``reachable`` means a daemon or
HTTP service answered. ``authenticated`` means it did not reject credentials.
``functional`` means the service returned the minimum expected payload. The
paper-specific ``ready`` level belongs to the readiness report, not this host
preflight. This tool never installs anything and never writes files.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import json
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NamedTuple

from ccfa.cli import Problem, emit
from ccfa.toolchain import which as toolchain_which
from ccfa.verifiers import (
    FORMAL_ENGINES,
    TIER_CORE,
    Engine,
    EngineStatus,
    default_wsl_probe,
    probe_engine,
)


class Dependency(NamedTuple):
    key: str
    executables: tuple[str, ...]
    required: bool
    capability: str
    daemon_args: tuple[str, ...] | None = None


class Venv(NamedTuple):
    key: str
    relative: str
    capability: str


@dataclass(frozen=True)
class Service:
    key: str
    url: str
    capability: str
    expected_model: str | None = None


@dataclass(frozen=True)
class ServiceResult:
    reachable: bool
    authenticated: bool
    functional: bool
    detail: str


DEPENDENCIES: tuple[Dependency, ...] = (
    Dependency(
        "git",
        ("git",),
        True,
        "论文独立仓库、版本快照与 run-log commit",
    ),
    Dependency(
        "pdflatex",
        ("pdflatex",),
        False,
        "LaTeX 编译（latex-check --compile）",
    ),
    Dependency("bibtex", ("bibtex",), False, "参考文献编译"),
    Dependency("xelatex", ("xelatex",), False, "中文文稿编译"),
    Dependency(
        "codex",
        ("codex",),
        False,
        "cross-review run 与工作台 codex 引擎",
    ),
    Dependency(
        "docker",
        ("docker",),
        False,
        "queue 的 sandbox=docker 沙箱后端",
        daemon_args=("info", "--format", "{{.ServerVersion}}"),
    ),
    Dependency("nvidia-smi", ("nvidia-smi",), False, "queue 的 GPU 秒预算"),
    Dependency(
        "ghostscript",
        ("gswin64c", "gs"),
        False,
        "PDF/EPS 压缩与转换（投稿系统常见要求）",
    ),
    Dependency("qpdf", ("qpdf",), False, "PDF 结构检查、修复与线性化"),
    Dependency("mutool", ("mutool",), False, "PDF 解析、转换与渲染"),
    Dependency(
        "soffice",
        ("soffice",),
        False,
        "DOCX/PPTX/XLSX 文档格式转换",
    ),
    Dependency(
        "typst",
        ("typst",),
        False,
        "Typst 排版运行时（typst-paper skill 依赖）",
    ),
    Dependency("quarto", ("quarto",), False, "Quarto 可复现报告"),
    Dependency(
        "dvc",
        ("dvc",),
        False,
        "数据集版本控制（大数据集超出 git-lfs 时）",
    ),
    Dependency(
        "conda",
        ("micromamba", "conda", "mamba"),
        False,
        "conda 兼容的研究环境管理",
    ),
    Dependency(
        "jupyter",
        ("jupyter",),
        False,
        "notebook 交互式实验",
    ),
)

VENVS: tuple[Venv, ...] = (
    Venv("tools", "tools/.venv", "所有 scripts/*.ps1 包装器与工具侧测试"),
    Venv("app", "app/.venv", "论文工作台 GUI 与 app 测试"),
)

_VENV_SUFFIXES = (
    Path("Scripts") / "python.exe",
    Path("bin") / "python",
)

_DAEMON_TIMEOUT_S = 15
_HTTP_TIMEOUT_S = 5

_LOCAL_SERVICES = (
    Service(
        "zotero",
        "http://127.0.0.1:23119/api/users/0/items?limit=1",
        "Zotero Desktop API",
    ),
)


class ImportCheck(NamedTuple):
    module: str
    capability: str
    why: str


# Mirror tools/requirements.txt. These are the imports the machine-checkable
# gates need *in the interpreter that runs them*: the same workflow behaves
# differently under a venv that has them and a bare interpreter that does not,
# and a missing module shows up as a failed gate rather than as a broken
# environment. Keeping the list here is what lets the workbench tell the two
# apart before it trusts a report.
IMPORT_CHECKS: tuple[ImportCheck, ...] = (
    ImportCheck("yaml", "所有工具", "PyYAML：所有 YAML 台账的读写"),
    ImportCheck("pymupdf", "pdftext", "PDF 正文抽取（claim-candidates 等）"),
    ImportCheck("z3", "formal-check", "Z3 SMT 引擎（formal-check 默认引擎）"),
    ImportCheck("cvc5", "formal-check", "cvc5 第二独立 SMT 引擎"),
    ImportCheck("bibtexparser", "bib", "BibTeX 解析（reference-audit 等）"),
    ImportCheck("pylatexenc", "bib", "LaTeX 解码（bibtexparser 依赖）"),
    ImportCheck("cryptography", "skillpack", "AES-256-GCM 加密技能包"),
)


def check_imports(
    checks: tuple[ImportCheck, ...] = IMPORT_CHECKS,
    *,
    importer: Callable[[str], object] | None = None,
) -> tuple[list[dict], list[str]]:
    """Return (missing, present) for the modules this interpreter must import.

    ``missing`` is a JSON-ready record per module, because the caller is a
    program (the workbench probe) far more often than it is a human.
    """

    probe = importer
    if probe is None:
        import importlib

        probe = importlib.import_module
    missing: list[dict] = []
    present: list[str] = []
    for check in checks:
        try:
            probe(check.module)
        except Exception as exc:  # a probe must never take down the preflight
            missing.append(
                {
                    "module": check.module,
                    "capability": check.capability,
                    "message": check.why,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        else:
            present.append(check.module)
    return missing, present


def discover_services(config_path: Path) -> tuple[Service, ...]:
    """Return read-only probes derived from Codex config plus local services."""
    services = list(_LOCAL_SERVICES)
    try:
        payload = tomllib.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return tuple(services)
    provider_name = payload.get("model_provider")
    model = payload.get("model")
    providers = payload.get("model_providers")
    provider = (
        providers.get(provider_name)
        if isinstance(providers, dict) and isinstance(provider_name, str)
        else None
    )
    base_url = provider.get("base_url") if isinstance(provider, dict) else None
    if isinstance(base_url, str) and base_url.strip() and isinstance(model, str):
        services.insert(
            0,
            Service(
                "provider",
                base_url.strip().rstrip("/") + "/models",
                "配置模型的推理服务",
                expected_model=model.strip(),
            ),
        )
    return tuple(services)


def _default_which(name: str) -> str | None:
    # PATH first, then the portable toolchain shim directory, so a preflight
    # started before a PATH edit still sees what is installed.
    return toolchain_which(name)


def _default_path_exists(path: Path) -> bool:
    """A venv interpreter must be a real, non-empty file."""
    try:
        return Path(path).is_file() and Path(path).stat().st_size > 0
    except OSError:
        return False


def _default_run(argv: list[str]) -> int:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_DAEMON_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return 1
    return completed.returncode


def _default_fetch(url: str, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Accept-Encoding": "identity"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read(200_000)
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(20_000)


def _model_ids(payload: object) -> set[str]:
    """Accept OpenAI-style data[].id and proxy-style models[].slug."""
    if not isinstance(payload, dict):
        return set()
    model_ids: set[str] = set()
    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                model_ids.add(item["id"])
    models = payload.get("models")
    if isinstance(models, list):
        for item in models:
            if not isinstance(item, dict):
                continue
            for field in ("id", "slug"):
                value = item.get(field)
                if isinstance(value, str):
                    model_ids.add(value)
    return model_ids


def _probe_http_service(
    service: Service,
    *,
    fetch: Callable[[str, float], tuple[int, bytes]] | None = None,
) -> ServiceResult:
    fetch = fetch or _default_fetch
    try:
        status, body = fetch(service.url, _HTTP_TIMEOUT_S)
    except Exception as exc:
        return ServiceResult(False, False, False, type(exc).__name__)
    if status in (401, 403):
        return ServiceResult(True, False, False, f"HTTP {status}")
    if status < 200 or status >= 300:
        return ServiceResult(True, True, False, f"HTTP {status}")
    if service.expected_model is None:
        return ServiceResult(True, True, True, f"HTTP {status}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ServiceResult(True, True, False, "响应不是合法 JSON")
    model_ids = _model_ids(payload)
    if service.expected_model not in model_ids:
        return ServiceResult(
            True,
            True,
            False,
            "配置模型不在模型列表中",
        )
    return ServiceResult(True, True, True, "配置模型可用")


def _venv_python(
    repo_root: Path,
    relative: str,
    path_exists: Callable[[Path], bool],
) -> Path | None:
    for suffix in _VENV_SUFFIXES:
        candidate = Path(repo_root) / relative / suffix
        if path_exists(candidate):
            return candidate
    return None


def check_environment(
    repo_root: Path,
    *,
    which: Callable[[str], str | None] | None = None,
    path_exists: Callable[[Path], bool] | None = None,
    dependencies: tuple[Dependency, ...] = DEPENDENCIES,
    venvs: tuple[Venv, ...] = VENVS,
    strict: bool = False,
    run: Callable[[list[str]], int] | None = None,
    services: tuple[Service, ...] = (),
    service_probe: Callable[[Service], ServiceResult] | None = None,
    formal_engines: tuple[Engine, ...] = (),
    engine_probe: Callable[[Engine], EngineStatus] | None = None,
) -> tuple[list[Problem], list[Problem], list[str]]:
    """Return (problems, advisories, human status lines)."""
    repo_root = Path(repo_root)
    which = which or _default_which
    path_exists = path_exists or _default_path_exists
    run = run or _default_run
    problems: list[Problem] = []
    advisories: list[Problem] = []
    statuses: list[str] = []

    def report(
        code: str,
        label: str,
        message: str,
        required: bool,
    ) -> None:
        problem = Problem(code, label, None, message)
        if required or strict:
            problems.append(problem)
        else:
            advisories.append(problem)

    for dependency in dependencies:
        found = None
        for executable in dependency.executables:
            found = which(executable)
            if found:
                break
        label = dependency.executables[0]
        if found:
            statuses.append(f"installed    {label:<12} {found}")
            if dependency.daemon_args is not None:
                try:
                    reachable = run([found, *dependency.daemon_args]) == 0
                except Exception:  # a probe must never take down the preflight
                    reachable = False
                if not reachable:
                    statuses.append(f"MISSING {label} daemon 不可达")
                    report(
                        "doctor-daemon-down",
                        label,
                        f"{label} 已安装但 daemon 不可达："
                        f"{dependency.capability} 不可用",
                        False,
                    )
                else:
                    statuses.append(
                        f"reachable    {label:<12} daemon 可达"
                    )
        else:
            statuses.append(f"MISSING      {label:<12} -")
            report(
                "doctor-missing-command",
                label,
                f"缺少 {label}：{dependency.capability} 不可用"
                f"（{'必需' if dependency.required else '可选'}）",
                dependency.required,
            )

    for venv in venvs:
        python = _venv_python(repo_root, venv.relative, path_exists)
        if python is not None:
            statuses.append(f"installed    {venv.relative:<12} {python}")
        else:
            statuses.append(f"MISSING      {venv.relative:<12} -")
            report(
                "doctor-missing-venv",
                venv.relative,
                f"缺少虚拟环境 {venv.relative}：{venv.capability} 不可用",
                False,
            )

    probe = service_probe or _probe_http_service
    for service in services:
        try:
            result = probe(service)
        except Exception as exc:
            result = ServiceResult(
                False,
                False,
                False,
                type(exc).__name__,
            )
        if result.functional:
            statuses.append(
                f"functional   {service.key:<12} {result.detail}"
            )
            continue
        if result.authenticated:
            statuses.append(
                f"authenticated {service.key:<12} {result.detail}"
            )
            report(
                "doctor-service-not-functional",
                service.key,
                f"{service.key} 可连接但最小功能检查失败："
                f"{service.capability} 尚不可用",
                False,
            )
            continue
        if result.reachable:
            statuses.append(
                f"reachable    {service.key:<12} 未通过身份验证"
            )
            report(
                "doctor-service-unauthenticated",
                service.key,
                f"{service.key} 可连接但身份无效："
                f"{service.capability} 尚不可用",
                False,
            )
            continue
        statuses.append(
            f"UNREACHABLE  {service.key:<12} {result.detail}"
        )
        report(
            "doctor-service-unreachable",
            service.key,
            f"{service.key} 不可达：{service.capability} 尚不可用",
            False,
        )

    engines_probe = engine_probe or (
        lambda engine: probe_engine(engine, wsl_probe=default_wsl_probe)
    )
    for engine in formal_engines:
        try:
            status = engines_probe(engine)
        except Exception as exc:  # a probe must never take down the preflight
            status = EngineStatus(engine, False, None, type(exc).__name__)
        if status.available:
            statuses.append(f"installed    {engine.key:<12} {status.detail}")
            continue
        statuses.append(f"MISSING      {engine.key:<12} -")
        report(
            "doctor-missing-verifier",
            engine.key,
            f"缺少形式化引擎 {engine.key}：{engine.capability} 不可用"
            f"（安装：{engine.install_hint}）",
            engine.tier == TIER_CORE,
        )
    return problems, advisories, statuses


def main(
    argv: list[str],
    *,
    which: Callable[[str], str | None] | None = None,
    path_exists: Callable[[Path], bool] | None = None,
    dependencies: tuple[Dependency, ...] = DEPENDENCIES,
    venvs: tuple[Venv, ...] = VENVS,
    run: Callable[[list[str]], int] | None = None,
    services: tuple[Service, ...] | None = None,
    service_probe: Callable[[Service], ServiceResult] | None = None,
    formal_engines: tuple[Engine, ...] = (),
    engine_probe: Callable[[Engine], EngineStatus] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="检查本地平台依赖：报告缺什么，以及缺它会禁用哪个能力"
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="仓库根（默认从本文件位置推导）",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="把可选依赖的缺失也算 problem（退 1），用于一次性装齐",
    )
    parser.add_argument(
        "--skip-services",
        action="store_true",
        help="只检查本地安装，不探测 provider/Zotero",
    )
    parser.add_argument(
        "--skip-verifiers",
        action="store_true",
        help="不检查形式化验证器（lean/coq/z3/...）是否可用",
    )
    parser.add_argument(
        "--codex-config",
        default=str(Path.home() / ".codex" / "config.toml"),
        help="Codex config.toml 路径，用于发现 provider 和配置模型",
    )
    parser.add_argument(
        "--imports-only",
        action="store_true",
        help=(
            "只检查当前解释器能否导入各 gate 需要的 Python 依赖，"
            "输出 JSON（给桌面工作台用）"
        ),
    )
    args = parser.parse_args(argv[1:])
    if args.imports_only:
        missing, present = check_imports()
        payload = {
            "python": sys.executable,
            "version": ".".join(str(part) for part in sys.version_info[:3]),
            "ok": not missing,
            "missing": missing,
            "present": present,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        if missing:
            names = ", ".join(item["module"] for item in missing)
            print(
                f"依赖自检失败：{names} 无法导入（{sys.executable}）；"
                "相关 gate 会失败而不是通过",
                file=sys.stderr,
            )
            return 1
        print(f"依赖自检通过：{len(present)} 个模块（{sys.executable}）", file=sys.stderr)
        return 0
    repo_root = (
        Path(args.repo_root)
        if args.repo_root
        else Path(__file__).resolve().parents[2]
    )
    selected_services = (
        ()
        if args.skip_services
        else (
            discover_services(Path(args.codex_config))
            if services is None
            else services
        )
    )
    problems, advisories, statuses = check_environment(
        repo_root,
        which=which,
        path_exists=path_exists,
        dependencies=dependencies,
        venvs=venvs,
        strict=args.strict,
        run=run,
        services=selected_services,
        service_probe=service_probe,
        formal_engines=() if args.skip_verifiers else formal_engines,
        engine_probe=engine_probe,
    )
    for line in statuses:
        print(line, file=sys.stderr)
    code = emit(problems, advisories)
    advisory_label = "advisory" if len(advisories) == 1 else "advisories"
    print(
        f"doctor summary: {len(problems)} problems, "
        f"{len(advisories)} {advisory_label}; "
        "run `scripts/doctor.ps1 --strict` before the submission gate",
        file=sys.stderr,
    )
    return code


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv, formal_engines=FORMAL_ENGINES))
