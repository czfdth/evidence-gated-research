"""Run a repro bundle inside a pinned container image and write a receipt.

The venv-based ``repro_package verify`` proves that the bundle command works
with a declared Python environment. This module adds a second, explicit
environment boundary: a content-addressed container image with networking
disabled and the bundle copied into an isolated writable workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ccfa.cli import save_text_atomically, tool_error
from ccfa.repro_package import (
    FILES_DIR_NAME,
    MANIFEST_NAME,
    _check_bundle_bytes,
    _validate_manifest,
    load_manifest,
    sha256_of,
)


DEFAULT_IMAGE = (
    "python@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d"
)
_OUTPUT_LIMIT = 12000


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_pinned_image(image: str) -> bool:
    """Require ``name@sha256:<64 hex>`` rather than a mutable tag."""
    if "@sha256:" not in image:
        return False
    digest = image.rsplit("@sha256:", 1)[1]
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


def _bounded(text: str) -> str:
    if len(text) <= _OUTPUT_LIMIT:
        return text
    return text[-_OUTPUT_LIMIT:]


def _container_argv(
    workspace: Path,
    image: str,
    command: list[str],
) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--pids-limit",
        "256",
        "--memory",
        "4g",
        "--cpus",
        "2",
        "--mount",
        f"type=bind,source={workspace},target=/workspace",
        "--workdir",
        "/workspace",
        image,
        *command,
    ]


def _default_runner(
    argv: list[str],
    *,
    timeout: float,
) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"容器复现超时: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"无法启动容器复现: {exc}") from exc
    return (
        int(completed.returncode),
        completed.stdout or "",
        completed.stderr or "",
    )


def verify_container(
    bundle_dir: Path,
    *,
    image: str = DEFAULT_IMAGE,
    out_path: Path | None = None,
    timeout: float = 600.0,
    runner=None,
) -> dict:
    """Verify the bundle in a pinned container and return the receipt."""
    bundle_dir = Path(bundle_dir)
    if not _is_pinned_image(image):
        raise ValueError(
            "容器镜像必须是 name@sha256:<64 hex>，不能使用可变的 tag"
        )
    manifest = load_manifest(bundle_dir)
    _validate_manifest(manifest)
    problems = _check_bundle_bytes(bundle_dir, manifest)
    if problems:
        raise ValueError(
            f"bundle 内容不完整: {problems[0].code}: {problems[0].message}"
        )
    command = list(manifest["command"])
    if not command or command[0] != "{python}":
        raise ValueError("bundle command 必须以 {python} 开头")
    command[0] = "python"

    temp_dir: Path | None = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="ccfa-repro-container-"))
        shutil.copytree(bundle_dir / FILES_DIR_NAME, temp_dir / FILES_DIR_NAME)
        argv = _container_argv(temp_dir / FILES_DIR_NAME, image, command)
        runner = runner or _default_runner
        exit_code, stdout, stderr = runner(argv, timeout=timeout)
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)

    combined = stdout + stderr
    receipt = {
        "version": 1,
        "status": "pass" if int(exit_code) == 0 else "fail",
        "bundle": str(bundle_dir),
        "manifest_sha256": sha256_of(bundle_dir / MANIFEST_NAME),
        "image": image,
        "command": argv,
        "network": "none",
        "exit_code": int(exit_code),
        "output_sha256": "sha256:"
        + hashlib.sha256(combined.encode("utf-8")).hexdigest(),
        "stdout_tail": _bounded(stdout),
        "stderr_tail": _bounded(stderr),
        "checked_at": _now_iso(),
        "boundary": (
            "content-addressed image; bundle copied to a disposable writable "
            "workspace; network disabled; no host package manager used"
        ),
    }
    if out_path is not None:
        save_text_atomically(
            Path(out_path),
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            description="container repro receipt",
        )
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="固定镜像中的复现验证")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--bundle", required=True)
    verify.add_argument("--out")
    verify.add_argument("--image", default=DEFAULT_IMAGE)
    verify.add_argument("--timeout-seconds", type=float, default=600.0)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        receipt = verify_container(
            Path(args.bundle),
            image=args.image,
            out_path=Path(args.out) if args.out else None,
            timeout=args.timeout_seconds,
        )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    if args.out is None:
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
