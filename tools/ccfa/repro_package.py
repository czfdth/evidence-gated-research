"""Bundle the files and command that reproduce one reported result.

The bundle is a claim about real bytes and a real argv. The manifest records
the hash and size of every bundled file, the command as an argv array (with a
``{python}`` placeholder for later substitution), the declared dependency
file's hash, and the interpreter and platform that built it. Paths are always
relative to ``paper_root`` so usernames and out-of-tree files never leak into a
shared bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ccfa.cli import (
    Problem,
    ToolEnvironmentError,
    emit,
    save_text_atomically,
    tool_error,
)

MANIFEST_NAME = "MANIFEST.json"
FILES_DIR_NAME = "files"

SCOPE_ADVISORY_CODE = "repro-scope"
OUTPUT_TAIL_ADVISORY_CODE = "repro-output-tail"
SCOPE_ADVISORY_MESSAGE = (
    "本次验证只在包含 bundle 声明依赖的新建 venv 中重跑命令，"
    "不提供容器级隔离：系统库、网络以及 PATH 上已有的非 Python 工具都没有被隔离。"
)

_OUTPUT_TAIL_LIMIT = 800


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _resolve_member(paper_root: Path, relpath: str) -> tuple[str, Path]:
    """Validate *relpath* against *paper_root* and return its posix form and path."""
    if Path(relpath).is_absolute():
        raise ValueError(f"清单路径必须是相对 paper_root 的相对路径: {relpath}")
    root = Path(paper_root).resolve()
    target = (Path(paper_root) / relpath).resolve()
    try:
        relative = target.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"清单路径不得逃逸 paper_root: {relpath}") from exc
    if not target.is_file():
        raise ValueError(f"清单文件不存在: {relpath}")
    return relative, target


def _file_entry(paper_root: Path, relpath: str) -> dict:
    relative, target = _resolve_member(paper_root, relpath)
    try:
        digest = sha256_of(target)
        size = target.stat().st_size
    except OSError as exc:
        raise ValueError(f"无法读取清单文件 {relative}: {exc}") from exc
    return {"path": relative, "sha256": digest, "size": size}


def build_manifest(
    paper_root: Path,
    files: list[str],
    command: list[str],
    requirements: str | None,
    notes: str | None,
) -> dict:
    command = list(command)
    if not command or command[0] != "{python}":
        raise ValueError(
            "bundle 命令必须以 {python} 开头；否则无法在新建 venv 中重跑并作诚实验证"
        )

    entries = [_file_entry(paper_root, relpath) for relpath in files]
    entries.sort(key=lambda item: item["path"])

    requirement_entry = None
    if requirements is not None:
        relative, target = _resolve_member(paper_root, requirements)
        try:
            digest = sha256_of(target)
        except OSError as exc:
            raise ValueError(f"无法读取依赖文件 {relative}: {exc}") from exc
        requirement_entry = {"path": relative, "sha256": digest}

    return {
        "version": 1,
        "created_at": _now_iso(),
        "command": command,
        "files": entries,
        "requirements": requirement_entry,
        "notes": notes,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def create_bundle(
    paper_root: Path,
    out_dir: Path,
    manifest: dict,
    *,
    force: bool = False,
) -> dict:
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ValueError("清单 version 必须是 1")
    items = manifest.get("files")
    if not isinstance(items, list):
        raise ValueError("清单 files 必须是数组")
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("清单 files 的每个条目都必须包含字符串 path")
    requirement = manifest.get("requirements")
    if requirement is not None:
        if not isinstance(requirement, dict) or not isinstance(requirement.get("path"), str):
            raise ValueError("清单 requirements 必须包含字符串 path")

    paper_root = Path(paper_root)
    out_dir = Path(out_dir)

    members: list[tuple[str, Path]] = []
    try:
        for item in items:
            members.append(_resolve_member(paper_root, item["path"]))
        if requirement is not None:
            members.append(_resolve_member(paper_root, requirement["path"]))
    except OSError as exc:
        raise ValueError(f"无法构建 bundle {out_dir}: {exc}") from exc

    if out_dir.exists():
        if not force:
            try:
                is_empty_dir = (
                    out_dir.is_dir()
                    and not out_dir.is_symlink()
                    and next(out_dir.iterdir(), None) is None
                )
            except OSError as exc:
                raise ValueError(
                    f"无法检查已有 bundle 目录 {out_dir}: {exc}"
                ) from exc
            if not is_empty_dir:
                raise ValueError(
                    f"bundle 目录已存在且非空: {out_dir}"
                    "（如需覆盖请显式使用 --force）"
                )
        else:
            try:
                shutil.rmtree(out_dir)
            except OSError as exc:
                raise ValueError(
                    f"无法删除已有 bundle 目录 {out_dir}: {exc}"
                ) from exc

    try:
        files_dir = out_dir / FILES_DIR_NAME
        files_dir.mkdir(parents=True, exist_ok=True)
        for relative, source in members:
            destination = files_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        save_text_atomically(out_dir / MANIFEST_NAME, payload, description="清单")
    except OSError as exc:
        raise ValueError(f"无法构建 bundle {out_dir}: {exc}") from exc
    return manifest


def load_manifest(bundle_dir: Path) -> dict:
    path = Path(bundle_dir) / MANIFEST_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"无法读取清单 {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"清单不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("清单顶层必须是对象")
    if "version" not in data:
        raise ValueError("清单缺少 version 字段")
    if data["version"] != 1:
        raise ValueError(f"清单 version 不支持: {data['version']}")
    return data


def _bundle_member(bundle_dir: Path, relpath: str) -> Path:
    """Resolve *relpath* under ``bundle_dir/files`` and reject any escape."""
    if Path(relpath).is_absolute():
        raise ValueError(f"清单路径必须是相对路径: {relpath}")
    files_dir = (Path(bundle_dir) / FILES_DIR_NAME).resolve()
    target = (files_dir / relpath).resolve()
    try:
        target.relative_to(files_dir)
    except ValueError as exc:
        raise ValueError(f"清单路径不得逃逸 bundle: {relpath}") from exc
    return target


def _validate_manifest(manifest: dict) -> None:
    items = manifest.get("files")
    if not isinstance(items, list):
        raise ValueError("清单 files 必须是数组")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("清单 files 的每个条目必须是对象")
        if not isinstance(item.get("path"), str) or not item["path"]:
            raise ValueError("清单 files 的每个条目都必须包含字符串 path")
        if not isinstance(item.get("sha256"), str) or not item["sha256"]:
            raise ValueError("清单 files 的每个条目都必须包含字符串 sha256")

    command = manifest.get("command")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(argument, str) for argument in command)
    ):
        raise ValueError("清单 command 必须是非空字符串数组")
    if command[0] != "{python}":
        raise ValueError(
            "清单 command 必须以 {python} 开头；否则无法在新建 venv 中作诚实验证"
        )

    requirement = manifest.get("requirements")
    if requirement is not None:
        if not isinstance(requirement, dict):
            raise ValueError("清单 requirements 必须是对象或 null")
        if not isinstance(requirement.get("path"), str) or not requirement["path"]:
            raise ValueError("清单 requirements 必须包含字符串 path")
        if not isinstance(requirement.get("sha256"), str) or not requirement["sha256"]:
            raise ValueError("清单 requirements 必须包含字符串 sha256")


def _hash_problem(relpath: str, message: str) -> Problem:
    return Problem(
        "repro-bundle-incomplete",
        f"{FILES_DIR_NAME}/{relpath}",
        None,
        message,
    )


def _check_bundle_bytes(bundle_dir: Path, manifest: dict) -> list[Problem]:
    """Check every recorded hash, reporting all problems instead of the first."""
    problems: list[Problem] = []
    entries: list[tuple[str, str]] = [
        (item["path"], item["sha256"]) for item in manifest["files"]
    ]
    requirement = manifest.get("requirements")
    if requirement is not None:
        entries.append((requirement["path"], requirement["sha256"]))

    for relpath, recorded in entries:
        target = _bundle_member(bundle_dir, relpath)
        if not target.is_file():
            problems.append(_hash_problem(relpath, f"bundle 缺少文件: {relpath}"))
            continue
        try:
            actual = sha256_of(target)
        except OSError as exc:
            problems.append(
                _hash_problem(relpath, f"bundle 文件不可读: {relpath}: {exc}")
            )
            continue
        if actual != recorded:
            problems.append(
                _hash_problem(
                    relpath,
                    f"bundle 文件哈希不匹配: {relpath}（清单 {recorded}，实际 {actual}）",
                )
            )
    return problems


def _tail(text: str, limit: int = _OUTPUT_TAIL_LIMIT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


def _default_venv_factory(path: Path) -> Path:
    # Imported here on purpose: the embeddable CPython distribution that
    # scripts/bundle-workflow.ps1 ships has no ``venv`` module, and this tool is
    # only one of many that share the workflow package.
    import venv

    path = Path(path)
    try:
        venv.EnvBuilder(with_pip=True).create(str(path))
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolEnvironmentError(f"无法创建虚拟环境 {path}: {exc}") from exc
    if sys.platform == "win32":
        return path / "Scripts" / "python.exe"
    return path / "bin" / "python"


def _default_runner(argv: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
    completed = subprocess.run(
        list(argv),
        cwd=str(cwd),
        check=False,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    output = f"{completed.stdout or ''}{completed.stderr or ''}"
    return int(completed.returncode), output


def verify_bundle(
    bundle_dir: Path,
    *,
    timeout: float = 600.0,
    keep: bool = False,
    venv_factory=None,
    runner=None,
    install_runner=None,
) -> tuple[list[Problem], list[Problem]]:
    """Re-run a bundle in a fresh venv built from its declared requirements."""
    bundle_dir = Path(bundle_dir)
    advisories = [
        Problem(SCOPE_ADVISORY_CODE, str(bundle_dir), None, SCOPE_ADVISORY_MESSAGE)
    ]

    manifest = load_manifest(bundle_dir)
    _validate_manifest(manifest)

    problems = _check_bundle_bytes(bundle_dir, manifest)
    if problems:
        return problems, advisories

    venv_factory = venv_factory or _default_venv_factory
    runner = runner or _default_runner
    install_runner = install_runner or runner
    files_dir = bundle_dir / FILES_DIR_NAME

    temp_dir: Path | None = None
    try:
        try:
            temp_dir = Path(tempfile.mkdtemp(prefix="ccfa-verify-"))
        except OSError as exc:
            raise ValueError(f"无法创建临时目录: {exc}") from exc
        if keep:
            print(f"已保留临时环境: {temp_dir}", file=sys.stderr)

        try:
            run_files_dir = temp_dir / FILES_DIR_NAME
            shutil.copytree(files_dir, run_files_dir)
        except OSError as exc:
            raise ValueError(f"无法复制 bundle 文件到临时目录: {exc}") from exc

        try:
            venv_python = Path(venv_factory(temp_dir / "venv"))
        except ToolEnvironmentError:
            raise
        except OSError as exc:
            raise ToolEnvironmentError(f"无法创建虚拟环境: {exc}") from exc

        install_problem: Problem | None = None
        requirement = manifest.get("requirements")
        if requirement is not None:
            requirement_path = run_files_dir / requirement["path"]
            install_argv = [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "-r",
                str(requirement_path),
            ]
            problem_path = f"{FILES_DIR_NAME}/{requirement['path']}"
            try:
                code, output = install_runner(install_argv, run_files_dir, timeout)
            except subprocess.TimeoutExpired as exc:
                install_problem = Problem(
                    "repro-install-failed",
                    problem_path,
                    None,
                    f"安装依赖超时: {exc}；未尝试重跑命令",
                )
            except OSError as exc:
                raise ValueError(f"无法安装依赖: {exc}") from exc
            else:
                if int(code) != 0:
                    install_problem = Problem(
                        "repro-install-failed",
                        problem_path,
                        None,
                        f"安装依赖失败（退出码 {int(code)}）: {_tail(output)}；未尝试重跑命令",
                    )

        if install_problem is not None:
            problems.append(install_problem)
            return problems, advisories

        argv = list(manifest["command"])
        argv[0] = str(venv_python)

        try:
            code, output = runner(argv, run_files_dir, timeout)
        except subprocess.TimeoutExpired as exc:
            problem = Problem(
                "repro-rerun-failed",
                str(bundle_dir),
                None,
                f"重跑超时: {exc}",
            )
        except OSError as exc:
            raise ValueError(f"无法重跑命令: {exc}") from exc
        else:
            if int(code) != 0:
                problem = Problem(
                    "repro-rerun-failed",
                    str(bundle_dir),
                    None,
                    f"重跑失败（退出码 {int(code)}）: {_tail(output)}",
                )
            else:
                problem = None
                advisories.append(
                    Problem(
                        OUTPUT_TAIL_ADVISORY_CODE,
                        str(bundle_dir),
                        None,
                        _tail(output),
                    )
                )

        if problem is not None:
            problems.append(problem)
    finally:
        if temp_dir is not None and not keep:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return problems, advisories


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="打包可复现的结果文件与命令")
    parser.add_argument("--paper-root")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    bundle = sub.add_parser("bundle", help="构建 bundle 目录与 MANIFEST.json")
    bundle.add_argument("--files", nargs="+", required=True)
    bundle.add_argument("--command", required=True)
    bundle.add_argument("--requirements")
    bundle.add_argument("--notes")
    bundle.add_argument("--out", required=True)
    bundle.add_argument("--force", action="store_true")

    verify = sub.add_parser("verify", help="在全新虚拟环境中重跑 bundle")
    verify.add_argument("--bundle", required=True)
    verify.add_argument("--timeout", type=float, default=600.0)
    verify.add_argument("--keep", action="store_true")

    args = parser.parse_args(argv[1:])

    if args.subcommand == "verify":
        try:
            problems, advisories = verify_bundle(
                Path(args.bundle),
                timeout=args.timeout,
                keep=args.keep,
            )
        except (ValueError, ToolEnvironmentError) as exc:
            return tool_error(str(exc))
        return emit(problems, advisories)

    if args.paper_root is None:
        return tool_error("bundle 需要 --paper-root")

    try:
        try:
            command = shlex.split(args.command, posix=True)
        except ValueError as exc:
            raise ValueError(f"--command 无法解析为 argv: {exc}") from exc
        if not command:
            raise ValueError("--command 不能为空")

        manifest = build_manifest(
            Path(args.paper_root),
            list(args.files),
            command,
            args.requirements,
            args.notes,
        )
        create_bundle(Path(args.paper_root), Path(args.out), manifest, force=args.force)
    except (ValueError, ToolEnvironmentError) as exc:
        return tool_error(str(exc))
    return emit([], [])


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
