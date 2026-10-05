"""Number paper versions with annotated git tags.

This tool stores nothing of its own: git tags are the only version truth.
Tags are annotated so the message can record whether the working tree was
clean when the snapshot was taken, plus an optional human label.

Every operation first resolves ``git rev-parse --show-toplevel`` and refuses
to run when it is not the paper directory itself: a paper nested inside a
template repository must never tag the parent repository (E61).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Callable

from ccfa.cli import tool_error

GitRunner = Callable[[list[str], Path], "tuple[int, str]"]

TAG_PREFIX = "paper-v"
TAG_GLOB = TAG_PREFIX + "*"


def _default_runner(args: list[str], repo: Path) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def git_output(args: list[str], repo: Path, runner: GitRunner | None = None) -> str:
    """Run git and return its output, folding any failure into ValueError.

    The output is returned verbatim; callers that need a single value (a
    commit hash, for example) strip it themselves.
    """
    run = runner or _default_runner
    try:
        code, output = run(list(args), Path(repo))
    except OSError as exc:
        raise ValueError(f"无法运行 git {list(args)}: {exc}") from exc
    if code != 0:
        detail = output.strip() or f"git 退出码 {code}"
        raise ValueError(f"git {' '.join(args)} 失败: {detail}")
    return output


def assert_own_repository(
    repo: Path,
    runner: GitRunner | None = None,
) -> Path:
    """Return *repo* only when git resolves its toplevel to that same path."""
    repo = Path(repo)
    output = git_output(["rev-parse", "--show-toplevel"], repo, runner=runner)
    toplevel = output.strip()
    if not toplevel:
        raise ValueError("git rev-parse --show-toplevel 未返回仓库路径")
    try:
        same_repository = Path(toplevel).resolve() == repo.resolve()
    except OSError as exc:
        raise ValueError(f"无法解析论文目录与 git toplevel: {exc}") from exc
    if not same_repository:
        raise ValueError(
            "论文目录不是独立 git 仓库，拒绝在父仓库上打 tag: "
            f"{repo}（git toplevel: {toplevel}）"
        )
    return repo


def _version_number(tag: str) -> int:
    suffix = tag[len(TAG_PREFIX) :]
    try:
        return int(suffix)
    except ValueError as exc:
        raise ValueError(
            f"标签 {tag!r} 不符合 {TAG_PREFIX}<N> 命名，无法解析版本号"
        ) from exc


def list_versions(repo: Path, runner: GitRunner | None = None) -> list[str]:
    """Return existing ``paper-v<N>`` tags in numeric order."""
    repo = assert_own_repository(repo, runner=runner)
    output = git_output(["tag", "-l", TAG_GLOB], repo, runner=runner)
    tags = [line.strip() for line in output.splitlines() if line.strip()]
    return sorted(tags, key=_version_number)


def next_version(repo: Path, runner: GitRunner | None = None) -> str:
    versions = list_versions(repo, runner=runner)
    highest = max((_version_number(tag) for tag in versions), default=0)
    return f"{TAG_PREFIX}{highest + 1}"


def working_tree_dirty(repo: Path, runner: GitRunner | None = None) -> bool:
    output = git_output(["status", "--porcelain"], repo, runner=runner)
    return bool(output.strip())


def _tag_message(
    dirty: bool, label: str | None = None, commit: str | None = None
) -> str:
    lines = [f"dirty={'true' if dirty else 'false'}"]
    if dirty:
        target = commit or "HEAD"
        lines.append(
            f"note=uncommitted changes are not captured; tag points at HEAD commit {target}"
        )
    if label:
        lines.append(f"label={label}")
    return "\n".join(lines)


def snapshot(
    repo: Path,
    *,
    label: str | None = None,
    allow_dirty: bool = False,
    runner: GitRunner | None = None,
) -> tuple[str, str]:
    """Tag the current commit as ``paper-v<N>`` and return ``(tag, commit)``."""
    repo = assert_own_repository(repo, runner=runner)
    dirty = working_tree_dirty(repo, runner=runner)
    if dirty and not allow_dirty:
        raise ValueError(
            "工作树有未提交改动，脏树快照无法仅凭 commit 复现；"
            "如确认要记录该状态，请加 --allow-dirty"
        )
    tag = next_version(repo, runner=runner)
    commit = git_output(["rev-parse", "HEAD"], repo, runner=runner).strip()
    git_output(
        ["tag", "-a", tag, "-m", _tag_message(dirty, label, commit)],
        repo,
        runner=runner,
    )
    return tag, commit


def diff_versions(
    repo: Path,
    a: str,
    b: str,
    paths: list[str] | None = None,
    runner: GitRunner | None = None,
) -> str:
    """Run ``git diff`` between two versions; differences are the product."""
    repo = assert_own_repository(repo, runner=runner)
    args = ["diff", a, b]
    if paths:
        args.append("--")
        args.extend(paths)
    return git_output(args, repo, runner=runner)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="用带注释的 git 标签给论文编号（paper-v<N>）"
    )
    parser.add_argument("--repo", default=".", help="论文仓库路径（默认当前目录）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="按数值升序列出已有版本")
    list_parser.set_defaults(handler="list")

    snapshot_parser = subparsers.add_parser(
        "snapshot", help="把当前提交打成 paper-v<N> 注释标签"
    )
    snapshot_parser.add_argument("--label", help="写进标签消息的人读备注")
    snapshot_parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "允许工作树有未提交改动：标签仍指向 HEAD 提交，"
            "未提交内容不会被捕获，标签消息记录 dirty=true 及该声明"
        ),
    )
    snapshot_parser.set_defaults(handler="snapshot")

    diff_parser = subparsers.add_parser(
        "diff",
        help=(
            "显示两个版本之间的差异；差异是输出而非错误，"
            "因此本子命令发现差异也退出 0（对 Unix diff 惯例的具名例外）"
        ),
    )
    diff_parser.add_argument("a")
    diff_parser.add_argument("b")
    diff_parser.add_argument(
        "--path", action="append", default=[], help="限定路径，可重复"
    )
    diff_parser.set_defaults(handler="diff")
    return parser


def main(argv: list[str], runner: GitRunner | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv[1:])
    repo = Path(args.repo)
    try:
        if args.handler == "list":
            for version in list_versions(repo, runner=runner):
                print(version)
            return 0
        if args.handler == "snapshot":
            tag, commit = snapshot(
                repo,
                label=args.label,
                allow_dirty=args.allow_dirty,
                runner=runner,
            )
            print(f"{tag} {commit}")
            return 0
        difference = diff_versions(
            repo, args.a, args.b, args.path or None, runner=runner
        )
        sys.stdout.write(difference)
        return 0
    except ValueError as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
