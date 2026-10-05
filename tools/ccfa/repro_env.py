"""Validate the reproducibility environment ledger.

This is a completeness gate. It cannot prove that a lockfile resolves on a
clean machine, but it forces the author to name the requirements file, the
lockfile, its hash, and the system tools with version evidence before the
submission package can pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from ccfa.cli import emit, tool_error
from ccfa.ledger import (
    is_nonempty_str,
    load_ledger,
    missing_fields,
    problem,
)

LEDGER_RELATIVE_PATH = Path("data") / "repro-environment.yaml"
TOP_FIELDS = ("python", "package_manager", "requirements", "lockfile", "system_tools")
TOOL_FIELDS = ("name", "version", "command", "evidence")
_SHA256 = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


def _sha256(path: Path) -> str:
    data = path.read_bytes()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _version_present(text: str, version: str) -> bool:
    escaped = re.escape(version.strip())
    return (
        re.search(
            rf"(?<![0-9A-Za-z._-]){escaped}(?![0-9A-Za-z._-])",
            text,
        )
        is not None
    )


def _check_tools(path: Path, paper_root: Path, tools: object) -> list:
    if not isinstance(tools, list) or not tools:
        return [
            problem(
                "repro-env-invalid",
                path,
                None,
                "system_tools 必须是非空数组",
            )
        ]
    problems = []
    seen: set[str] = set()
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            problems.append(
                problem(
                    "repro-env-invalid",
                    path,
                    None,
                    f"system_tools[{index}] 必须是映射",
                )
            )
            continue
        missing = missing_fields(tool, TOOL_FIELDS)
        if missing:
            problems.append(
                problem(
                    "repro-env-invalid",
                    path,
                    None,
                    f"system_tools[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        name = tool.get("name")
        version = tool.get("version")
        command = tool.get("command")
        evidence = tool.get("evidence")
        if not is_nonempty_str(name):
            problems.append(
                problem(
                    "repro-env-invalid",
                    path,
                    None,
                    f"system_tools[{index}].name 必须是非空字符串",
                )
            )
            continue
        name = name.strip()
        if name in seen:
            problems.append(
                problem(
                    "repro-env-duplicate-tool",
                    path,
                    None,
                    f"system tool 重复: {name}",
                )
            )
        seen.add(name)
        for field, value in (
            ("version", version),
            ("command", command),
            ("evidence", evidence),
        ):
            if not is_nonempty_str(value):
                problems.append(
                    problem(
                        "repro-env-invalid",
                        path,
                        None,
                        f"{name}: {field} 必须是非空字符串",
                    )
                )
        if not is_nonempty_str(evidence):
            continue
        evidence_path = (paper_root / evidence).resolve()
        try:
            evidence_path.relative_to(paper_root.resolve())
        except ValueError:
            problems.append(
                problem(
                    "repro-env-evidence-escape",
                    path,
                    None,
                    f"{name}: evidence 逃出 paper_root: {evidence}",
                )
            )
            continue
        if not evidence_path.is_file():
            problems.append(
                problem(
                    "repro-env-evidence-missing",
                    path,
                    None,
                    f"{name}: evidence 不存在: {evidence}",
                )
            )
            continue
        try:
            text = evidence_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ValueError(f"无法读取 {evidence_path}: {exc}") from exc
        if is_nonempty_str(version) and not _version_present(text, version):
            problems.append(
                problem(
                    "repro-env-evidence-mismatch",
                    path,
                    None,
                    f"{name}: evidence 中未找到版本 {version!r}",
                )
            )
    return problems


def _check_container(
    path: Path,
    paper_root: Path,
    container: object,
) -> list:
    if not isinstance(container, dict):
        return [
            problem(
                "repro-env-invalid",
                path,
                None,
                "container 必须是映射",
            )
        ]
    problems = []
    image = container.get("image")
    digest = container.get("digest")
    receipt = container.get("receipt")
    if not is_nonempty_str(image):
        problems.append(
            problem(
                "repro-env-invalid",
                path,
                None,
                "container.image 必须是非空字符串",
            )
        )
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        problems.append(
            problem(
                "repro-env-invalid-hash",
                path,
                None,
                "container.digest 必须是 sha256:<64 hex>",
            )
        )
    if not is_nonempty_str(receipt):
        problems.append(
            problem(
                "repro-env-invalid",
                path,
                None,
                "container.receipt 必须是非空相对路径",
            )
        )
        return problems
    if not is_nonempty_str(image) or not isinstance(digest, str):
        return problems

    receipt_path = (paper_root / receipt).resolve()
    try:
        receipt_path.relative_to(paper_root.resolve())
    except ValueError:
        problems.append(
            problem(
                "repro-env-container-receipt-escape",
                path,
                None,
                f"container.receipt 逃出 paper_root: {receipt}",
            )
        )
        return problems
    if not receipt_path.is_file():
        problems.append(
            problem(
                "repro-env-container-receipt-missing",
                path,
                None,
                f"container receipt 不存在: {receipt}",
            )
        )
        return problems
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        problems.append(
            problem(
                "repro-env-container-receipt-invalid",
                path,
                None,
                f"container receipt 不可读: {exc}",
            )
        )
        return problems
    if not isinstance(payload, dict) or payload.get("version") != 1:
        problems.append(
            problem(
                "repro-env-container-receipt-invalid",
                path,
                None,
                "container receipt 必须是 version: 1 的对象",
            )
        )
        return problems
    expected_image = f"{image}@{digest}"
    if payload.get("image") != expected_image:
        problems.append(
            problem(
                "repro-env-container-image-mismatch",
                path,
                None,
                f"receipt image 与台账不一致: {payload.get('image')!r} != {expected_image!r}",
            )
        )
    if payload.get("status") != "pass" or payload.get("exit_code") != 0:
        problems.append(
            problem(
                "repro-env-container-not-pass",
                path,
                None,
                "container receipt 不是成功的第二环境复现",
            )
        )
    if payload.get("network") != "none":
        problems.append(
            problem(
                "repro-env-container-network",
                path,
                None,
                "container receipt 没有记录 network=none",
            )
        )
    manifest_sha = payload.get("manifest_sha256")
    if not isinstance(manifest_sha, str) or _SHA256.fullmatch(manifest_sha) is None:
        problems.append(
            problem(
                "repro-env-invalid-hash",
                path,
                None,
                "container receipt 的 manifest_sha256 必须是 sha256:<64 hex>",
            )
        )
    return problems


def check(paper_root: Path, ledger: Path | None = None) -> tuple[list, list]:
    paper_root = Path(paper_root)
    path = Path(ledger) if ledger else paper_root / LEDGER_RELATIVE_PATH
    if not path.is_file():
        return [
            problem(
                "repro-env-ledger-missing",
                path,
                None,
                "台账不存在",
            )
        ], []
    payload, problems = load_ledger(path, code="repro-env-invalid")
    if payload is None:
        return problems, []
    missing = missing_fields(payload, TOP_FIELDS)
    if missing:
        return [
            problem(
                "repro-env-invalid",
                path,
                None,
                f"复现环境台账缺少字段: {', '.join(missing)}",
            )
        ], []
    for field in ("python", "package_manager"):
        if not is_nonempty_str(payload.get(field)):
            problems.append(
                problem(
                    "repro-env-invalid",
                    path,
                    None,
                    f"{field} 必须是非空字符串",
                )
            )
    requirements = payload.get("requirements")
    if not is_nonempty_str(requirements):
        problems.append(
            problem(
                "repro-env-invalid",
                path,
                None,
                "requirements 必须是非空相对路径",
            )
        )
    else:
        requirements_path = (paper_root / requirements).resolve()
        try:
            requirements_path.relative_to(paper_root.resolve())
        except ValueError:
            problems.append(
                problem(
                    "repro-env-path-escape",
                    path,
                    None,
                    f"requirements 逃出 paper_root: {requirements}",
                )
            )
        else:
            if not requirements_path.is_file():
                problems.append(
                    problem(
                        "repro-env-requirements-missing",
                        path,
                        None,
                        f"requirements 文件不存在: {requirements}",
                    )
                )
    lockfile = payload.get("lockfile")
    expected_sha = payload.get("lockfile_sha256")
    if not is_nonempty_str(lockfile):
        problems.append(
            problem(
                "repro-env-invalid",
                path,
                None,
                "lockfile 必须是非空相对路径",
            )
        )
    else:
        lock_path = (paper_root / lockfile).resolve()
        try:
            lock_path.relative_to(paper_root.resolve())
        except ValueError:
            problems.append(
                problem(
                    "repro-env-path-escape",
                    path,
                    None,
                    f"lockfile 逃出 paper_root: {lockfile}",
                )
            )
        else:
            if not lock_path.is_file():
                problems.append(
                    problem(
                        "repro-env-lockfile-missing",
                        path,
                        None,
                        f"lockfile 不存在: {lockfile}",
                    )
                )
            elif not isinstance(expected_sha, str) or _SHA256.fullmatch(
                expected_sha
            ) is None:
                problems.append(
                    problem(
                        "repro-env-invalid-hash",
                        path,
                        None,
                        "lockfile_sha256 必须是 sha256:<64 hex>",
                    )
                )
            else:
                actual = _sha256(lock_path)
                if actual != expected_sha.lower():
                    problems.append(
                        problem(
                            "repro-env-lockfile-drift",
                            path,
                            None,
                            f"lockfile 已变化: 记录 {expected_sha}，实际 {actual}",
                        )
                    )
    container = payload.get("container")
    if container is not None:
        problems.extend(_check_container(path, paper_root, container))
    problems.extend(_check_tools(path, paper_root, payload.get("system_tools")))
    return problems, []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="检查复现环境：requirements、lockfile 哈希与系统工具版本证据"
    )
    parser.add_argument("--paper-root", default=".")
    parser.add_argument("--ledger")
    args = parser.parse_args(argv[1:])
    try:
        problems, advisories = check(
            Path(args.paper_root),
            Path(args.ledger) if args.ledger else None,
        )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    return emit(problems, advisories)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
