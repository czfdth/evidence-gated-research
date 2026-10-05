"""Write one durable record for each computational run.

``declared_purpose`` is the caller's own statement. It is recorded so that
consumers can see *why* an exemption was claimed; it is not evidence that the
run really was a build. Legacy records with a ``purpose`` field remain
readable by consumers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import date, datetime, time as datetime_time, timezone
from pathlib import Path
from typing import NamedTuple

import yaml

from ccfa import cli
from ccfa.cli import Problem, ToolEnvironmentError, emit, save_text_atomically, tool_error

VALID_PURPOSES = ("experiment", "build")
# What a run *is* inside an experiment, which is a different question from
# whether it is an experiment at all. A treatment-only log cannot support an
# effect claim: nothing in it rules out the obvious confound.
VALID_ROLES = ("treatment", "negative-control", "ablation", "baseline")
_MIN_EXEMPTION_REASON = 20


def _exemption_reason(value: object) -> str:
    """Return the whitespace-normalised reason, or '' when unusable."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _dirty_tree_findings(
    record: dict,
    path: Path,
) -> tuple[Problem | None, Problem | None]:
    """Return the (problem, advisory) pair for a record taken on a dirty tree.

    Applies to every record status, including ``running``: a run that started on
    a dirty tree cannot be reproduced from its commit whether or not it has
    finished yet.
    """
    dirty = record.get("git_dirty")
    if dirty is not None and not isinstance(dirty, bool):
        return (
            Problem(
                "run-log-malformed",
                str(path),
                None,
                f"git_dirty 必须是布尔值或 null，无法判断该运行是否可复现: {dirty!r}",
            ),
            None,
        )
    if dirty is not True:
        return None, None
    has_repo_field = "git_repo" in record
    repo = record.get("git_repo")
    if not (not has_repo_field or repo == "self"):
        return None, None
    waiver = _exemption_reason(record.get("dirty_waiver"))
    if len(waiver) < _MIN_EXEMPTION_REASON:
        return (
            Problem(
                "run-log-dirty-tree",
                str(path),
                None,
                f"该运行发生在脏树上，无法仅凭 commit 复现: "
                f"{record.get('run_id')}；如确需保留，请在记录里写明 "
                f"dirty_waiver（至少 {_MIN_EXEMPTION_REASON} 字符）",
            ),
            None,
        )
    return (
        None,
        Problem(
            "run-log-dirty-waiver",
            str(path),
            None,
            f"该运行发生在脏树上，已按记录的理由豁免: "
            f"{record.get('run_id')}；理由：{waiver}",
        ),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dump_record(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _json_safe(value):
    if isinstance(value, dict):
        return {
            key if isinstance(key, str) else str(key): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date, datetime_time)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _save_record(path: Path, record: dict) -> None:
    cli.save_text_atomically(path, _dump_record(record), description="运行记录")


def new_run_id(log_dir: Path, stamp: str | None = None) -> tuple[str, Path]:
    log_dir = Path(log_dir)
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"无法创建运行记录目录 {log_dir}: {exc}") from exc

    counter = 1
    while True:
        run_id = f"{stamp}-{counter:02d}"
        path = log_dir / f"{run_id}.json"
        try:
            with open(path, "x", encoding="utf-8") as handle:
                handle.write("{}")
        except FileExistsError:
            counter += 1
            continue
        except OSError as exc:
            raise ValueError(f"无法占位运行记录 {path}: {exc}") from exc
        return run_id, path


class GitState(NamedTuple):
    git_repo: str
    git_commit: str | None
    git_dirty: bool | None


def _run_git(
    paper_root: Path,
    args: list[str],
) -> subprocess.CompletedProcess | None:
    """Run one git command, folding missing git/timeout into None."""
    try:
        return subprocess.run(
            ["git", "-C", str(paper_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _is_untracked_under(record: str, paper_root: Path, exclude: Path) -> bool:
    """Return whether a porcelain record is an untracked file under *exclude*."""
    if not record.startswith("?? "):
        return False
    raw_path = record[3:]
    try:
        candidate = (paper_root / raw_path).resolve()
        candidate.relative_to(exclude.resolve())
    except (OSError, ValueError):
        return False
    return True


def git_state(
    paper_root: Path,
    *,
    exclude: Path | None = None,
) -> GitState:
    """Record whether the run happened in the paper's own repository.

    ``self`` keeps the commit/dirty fields. A directory inside a parent or
    other repository is ``foreign`` and a missing git environment is ``none``;
    both carry null commit/dirty so a parent repository's commit is never
    recorded as this run's provenance.
    """
    paper_root = Path(paper_root)
    top = _run_git(paper_root, ["rev-parse", "--show-toplevel"])
    if top is None or top.returncode != 0:
        return GitState("none", None, None)
    toplevel = top.stdout.strip()
    if not toplevel:
        return GitState("none", None, None)
    try:
        same_repository = Path(toplevel).resolve() == paper_root.resolve()
    except OSError:
        same_repository = False
    if not same_repository:
        return GitState("foreign", None, None)
    head = _run_git(paper_root, ["rev-parse", "HEAD"])
    status = _run_git(
        paper_root,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
    )
    if (
        head is None
        or status is None
        or head.returncode != 0
        or status.returncode != 0
    ):
        return GitState("self", None, None)
    records = [record for record in status.stdout.split("\0") if record]
    if exclude is not None:
        records = [
            record
            for record in records
            if not _is_untracked_under(record, paper_root, exclude)
        ]
    return GitState("self", head.stdout.strip() or None, bool(records))


def read_config(path: Path, *, paper_root: Path) -> dict:
    path = Path(path)
    root = Path(paper_root)
    try:
        resolved = path if path.is_absolute() else root / path
        resolved = resolved.resolve()
        relative = resolved.relative_to(root.resolve()).as_posix()
        raw = resolved.read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError(f"无法读取配置 {path}: {exc}") from exc
    try:
        content = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"无法解析配置 {path}: {exc}") from exc
    content = _json_safe(content)
    digest = hashlib.sha256(raw).hexdigest()
    return {"path": relative, "sha256": f"sha256:{digest}", "content": content}


def _subprocess_runner(argv: list[str], cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(
        list(argv),
        cwd=str(cwd),
        check=False,
    )
    return completed.returncode, ""


def run_command(
    argv: list[str],
    log_dir: Path,
    paper_root: Path,
    *,
    cwd: str = ".",
    config: Path | None = None,
    seed: str | None = None,
    notes: str | None = None,
    purpose: str = "experiment",
    purpose_reason: str | None = None,
    role: str | None = None,
    dirty_waiver: str | None = None,
    policy: dict | None = None,
    runner=None,
) -> tuple[str, dict]:
    argv = list(argv)
    if not argv:
        raise ValueError("运行命令不能为空")
    if purpose not in VALID_PURPOSES:
        raise ValueError(
            f"purpose 非法: {purpose!r}，应为 {' / '.join(VALID_PURPOSES)}"
        )
    if role is not None:
        if role not in VALID_ROLES:
            raise ValueError(
                f"role 非法: {role!r}，应为 {' / '.join(VALID_ROLES)}"
            )
        if purpose != "experiment":
            raise ValueError(
                f"只有 experiment 运行能声明 role: 这次运行声明为 {purpose}，"
                "构建运行没有科学角色"
            )
    log_dir = Path(log_dir)
    paper_root = Path(paper_root)
    runner = runner or _subprocess_runner

    run_id, record_path = new_run_id(log_dir)
    config_entry = read_config(config, paper_root=paper_root) if config else None
    state = git_state(paper_root, exclude=log_dir)
    started_at = _now_iso()
    started = time.monotonic()
    record = {
        "run_id": run_id,
        "command": argv,
        "cwd": cwd,
        "config": config_entry,
        "seed": seed,
        "git_repo": state.git_repo,
        "git_commit": state.git_commit,
        "git_dirty": state.git_dirty,
        "started_at": started_at,
        "finished_at": None,
        "duration_s": None,
        "exit_code": None,
        "status": "running",
        "metrics": None,
        "notes": notes,
        "declared_purpose": purpose,
        "purpose_reason": purpose_reason,
        "role": role,
        "dirty_waiver": dirty_waiver,
        "policy": _json_safe(policy) if policy is not None else None,
        "resource_usage": None,
    }
    _save_record(record_path, record)

    try:
        exit_code, _output = runner(argv, paper_root)
    except OSError as exc:
        finished_at = _now_iso()
        record.update(
            finished_at=finished_at,
            duration_s=round(time.monotonic() - started, 6),
            exit_code=127,
            status="failed",
        )
        _save_record(record_path, record)
        raise ValueError(f"无法运行命令 {argv[0]!r}: {exc}") from exc

    finished_at = _now_iso()
    record.update(
        finished_at=finished_at,
        duration_s=round(time.monotonic() - started, 6),
        exit_code=int(exit_code),
        status="completed" if exit_code == 0 else "failed",
    )
    _save_record(record_path, record)
    return run_id, record


def record_path(log_dir: Path, run_id: str) -> Path:
    return Path(log_dir) / f"{run_id}.json"


def log_metrics(log_dir: Path, run_id: str, metrics: dict) -> dict:
    if not isinstance(metrics, dict):
        raise ValueError("metrics 必须是 JSON 对象")
    path = record_path(log_dir, run_id)
    if not path.is_file():
        raise ValueError(f"没有这条运行记录: {run_id}")
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError(f"运行记录不是对象: {run_id}")
    record["metrics"] = metrics
    save_text_atomically(
        path,
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="运行记录",
    )
    return record


def log_resource_usage(
    log_dir: Path,
    run_id: str,
    resource_usage: dict,
) -> dict:
    """Record operational resource accounting without touching metrics."""
    if not isinstance(resource_usage, dict):
        raise ValueError("resource_usage 必须是 JSON 对象")
    path = record_path(log_dir, run_id)
    if not path.is_file():
        raise ValueError(f"没有这条运行记录: {run_id}")
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError(f"运行记录不是对象: {run_id}")
    record["resource_usage"] = _json_safe(resource_usage)
    save_text_atomically(
        path,
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="运行记录",
    )
    return record


def _parse_started(value: object) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return None


def check_runs(
    log_dir: Path,
    stale_hours: float = 24.0,
    now: datetime | None = None,
) -> tuple[list[Problem], list[Problem]]:
    log_dir = Path(log_dir)
    reference = now or datetime.now(timezone.utc)
    problems: list[Problem] = []
    advisories: list[Problem] = []
    if not log_dir.is_dir():
        return problems, advisories
    for path in sorted(log_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(
                Problem("run-log-malformed", str(path), None, f"运行记录不可读: {exc}")
            )
            continue
        if not isinstance(record, dict) or "status" not in record:
            problems.append(
                Problem(
                    "run-log-malformed",
                    str(path),
                    None,
                    "运行记录缺少 status 字段",
                )
            )
            continue
        status = record.get("status")
        started = _parse_started(record.get("started_at"))
        role = record.get("role")
        if role is not None:
            declared = record.get("declared_purpose", record.get("purpose"))
            if role not in VALID_ROLES:
                problems.append(
                    Problem(
                        "run-log-role-invalid",
                        str(path),
                        None,
                        f"role 非法: {role!r}，应为 {' / '.join(VALID_ROLES)}",
                    )
                )
            elif declared == "build":
                problems.append(
                    Problem(
                        "run-log-role-on-build",
                        str(path),
                        None,
                        "声明为 build 的运行不能带科学 role"
                        "（build 不是实验条件）",
                    )
                )
        if status not in {"running", "completed", "failed"}:
            problems.append(
                Problem(
                    "run-log-malformed",
                    str(path),
                    None,
                    f"运行记录 status 非法: {status!r}",
                )
            )
            continue
        dirty_problem, dirty_advisory = _dirty_tree_findings(record, path)
        if dirty_problem is not None:
            problems.append(dirty_problem)
        if dirty_advisory is not None:
            advisories.append(dirty_advisory)
        if status == "running":
            if started is None:
                problems.append(
                    Problem(
                        "run-log-malformed",
                        str(path),
                        None,
                        "running 记录缺少可解析的 started_at",
                    )
                )
            elif (reference - started).total_seconds() > stale_hours * 3600:
                problems.append(
                    Problem(
                        "run-log-stale-running",
                        str(path),
                        None,
                        f"记录停留在 running 超过 {stale_hours:g} 小时: {record.get('run_id')}",
                    )
                )
            continue
        if status == "completed":
            metrics = record.get("metrics")
            if metrics is None:
                problems.append(
                    Problem(
                        "run-log-metrics-pending",
                        str(path),
                        None,
                        f"运行已完成但未登记指标: {record.get('run_id')}",
                    )
                )
            elif not isinstance(metrics, dict):
                problems.append(
                    Problem(
                        "run-log-malformed",
                        str(path),
                        None,
                        f"运行记录的 metrics 不是对象: {record.get('run_id')}",
                    )
                )
            elif metrics == {}:
                problems.append(
                    Problem(
                        "run-log-empty-metrics",
                        str(path),
                        None,
                        f"运行指标为空对象: {record.get('run_id')}",
                    )
                )
        has_repo_field = "git_repo" in record
        repo = record.get("git_repo")
        if not has_repo_field:
            advisories.append(
                Problem(
                    "run-log-git-repo-unknown",
                    str(path),
                    None,
                    f"旧记录未标注 git_repo，无法判断是否发生在论文仓库: {record.get('run_id')}",
                )
            )
        elif repo == "foreign":
            problems.append(
                Problem(
                    "run-log-foreign-repo",
                    str(path),
                    None,
                    f"该运行发生在论文目录之外的 git 仓库，未记录父仓库提交: {record.get('run_id')}",
                )
            )
        elif repo == "none":
            problems.append(
                Problem(
                    "run-log-no-git-repo",
                    str(path),
                    None,
                    f"该运行不在任何 git 仓库中，无法绑定 commit: {record.get('run_id')}",
                )
            )
        elif repo != "self":
            problems.append(
                Problem(
                    "run-log-malformed",
                    str(path),
                    None,
                    f"运行记录 git_repo 非法: {repo!r}",
                )
            )

        if (
            (not has_repo_field or repo == "self")
            and not record.get("git_commit")
        ):
            problems.append(
                Problem(
                    "run-log-missing-commit",
                    str(path),
                    None,
                    f"记录缺少 git commit: {record.get('run_id')}",
                )
            )
    return problems, advisories


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="记录并运行一次计算")
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--paper-root", required=True)
    sub = parser.add_subparsers(dest="subcommand", required=True)

    run = sub.add_parser("run", help="运行命令并写入运行记录")
    run.add_argument("--config")
    run.add_argument("--seed")
    run.add_argument("--notes")
    run.add_argument(
        "--purpose",
        choices=VALID_PURPOSES,
        default="experiment",
        help=(
            "experiment 受 T-30 冻结规则约束；build 仅用于图表/编译等构建运行。"
            "这是调用者的声明，不构成证据；T-30 后声明 build 必须同时给 "
            "--purpose-reason"
        ),
    )
    run.add_argument(
        "--purpose-reason",
        help=(
            "为什么这次运行算 build 而不是新实验；T-30 后声明的 build 运行"
            "缺该理由（至少 20 字符）会被 milestones due 判为 problem"
        ),
    )
    run.add_argument(
        "--dirty-waiver",
        help=(
            "明知工作树有未提交改动仍要记录这次运行的理由；"
            "缺该理由（至少 20 字符）时 run-log check 会把脏树运行判为 problem"
        ),
    )
    run.add_argument(
        "--role",
        choices=VALID_ROLES,
        default=None,
        help=(
            "这次 experiment 运行在实验里扮演什么角色（treatment / "
            "negative-control / ablation / baseline）。supported 的 effect "
            "实证 claim 必须引用至少一个 negative-control 或 ablation"
        ),
    )
    run.add_argument("--propagate-exit", action="store_true")
    run.add_argument("command", nargs=argparse.REMAINDER)

    metrics = sub.add_parser("log-metrics", help="为已有运行记录登记指标")
    metrics.add_argument("run_id")
    metrics.add_argument("--metrics", required=True)

    check = sub.add_parser("check", help="检查运行记录完整性")
    check.add_argument("--stale-hours", type=float, default=24.0)

    args = parser.parse_args(argv[1:])
    if args.subcommand == "log-metrics":
        try:
            parsed_metrics = json.loads(args.metrics)
            record = log_metrics(Path(args.log_dir), args.run_id, parsed_metrics)
        except (ValueError, OSError) as exc:
            return tool_error(str(exc))
        print(json.dumps(record, ensure_ascii=False, sort_keys=True))
        return 0

    if args.subcommand == "check":
        return emit(
            *check_runs(
                Path(args.log_dir),
                stale_hours=args.stale_hours,
            )
        )

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        return tool_error("run 需要 `--` 后的命令")

    try:
        run_id, record = run_command(
            command,
            Path(args.log_dir),
            Path(args.paper_root),
            config=Path(args.config) if args.config else None,
            seed=args.seed,
            notes=args.notes,
            purpose=args.purpose,
            purpose_reason=args.purpose_reason,
            role=args.role,
            dirty_waiver=args.dirty_waiver,
        )
    except (ValueError, ToolEnvironmentError) as exc:
        return tool_error(str(exc))

    print(
        f"运行 {run_id}: {record['status']} (exit_code={record['exit_code']})",
        file=sys.stderr,
    )
    if args.propagate_exit:
        return int(record["exit_code"])
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
