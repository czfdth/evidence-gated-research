"""Compute-backend discovery, budgeted execution, and attempt-cost ledger.

The workflow previously assumed "local machine plus a Docker sandbox", which
makes a pilot's cost invisible: nothing recorded how long an attempt took or
how much GPU time it burned. That is the throughput problem named in the
top-venue evaluation: when an attempt is expensive, teams rationally drift
into auditing instead of experimenting.

This module does three things:

* :func:`probe_local` reports the actual ceiling — CPU, RAM, every GPU and
  whether Docker exposes an NVIDIA runtime.
* :func:`plan` answers whether a backend can serve a pilot budget, and refuses
  to pretend a remote cluster exists when none is configured.
* :func:`run_local` executes a command under a wall-clock budget and appends a
  record to ``experiments/log/compute-ledger.jsonl`` with ``wall_seconds`` and
  ``gpu_minutes`` so ``cost_per_attempt`` becomes measurable rather than
  anecdotal.

Remote schedulers (Slurm, PBS/Torque) are adapters over SSH. They are absent
until a host is configured in ``data/compute.yaml``; :func:`probe_remote`
reports exactly that instead of reporting a false capability.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from ccfa.cli import Problem, emit, tool_error
from ccfa.toolchain import which as toolchain_which

COMPUTE_CONFIG = Path("data/compute.yaml")
COMPUTE_LEDGER = Path("experiments/log/compute-ledger.jsonl")

_PROBE_TIMEOUT_S = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Gpu:
    index: int
    name: str
    memory_mib: int
    compute_cap: str = ""


@dataclass
class LocalResources:
    cpu_count: int
    ram_gib: float
    gpus: list[Gpu] = field(default_factory=list)
    docker: bool = False
    docker_gpu: bool = False

    @property
    def gpu_count(self) -> int:
        return len(self.gpus)

    def as_dict(self) -> dict:
        return {
            "cpu_count": self.cpu_count,
            "ram_gib": round(self.ram_gib, 1),
            "gpus": [
                {
                    "index": gpu.index,
                    "name": gpu.name,
                    "memory_mib": gpu.memory_mib,
                    "compute_cap": gpu.compute_cap,
                }
                for gpu in self.gpus
            ],
            "docker": self.docker,
            "docker_gpu": self.docker_gpu,
        }


def _default_run(argv: Sequence[str], timeout: float = _PROBE_TIMEOUT_S) -> tuple[int, str]:
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
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return completed.returncode, completed.stdout or ""


def parse_nvidia_smi(output: str) -> list[Gpu]:
    """Parse ``--query-gpu=index,name,memory.total,compute_cap`` CSV output."""
    gpus: list[Gpu] = []
    for line in output.splitlines():
        cells = [cell.strip() for cell in line.split(",")]
        if len(cells) < 3 or not cells[0].isdigit():
            continue
        try:
            memory = int(float(cells[2].split()[0]))
        except (ValueError, IndexError):
            continue
        gpus.append(
            Gpu(
                index=int(cells[0]),
                name=cells[1],
                memory_mib=memory,
                compute_cap=cells[3] if len(cells) > 3 else "",
            )
        )
    return gpus


def _ram_gib() -> float:
    try:
        import ctypes

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys / (1024**3)
    except (AttributeError, OSError):
        pass
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        return pages * size / (1024**3)
    except (ValueError, OSError, AttributeError):
        return 0.0


def probe_local(
    *,
    which: Callable[[str], str | None] | None = None,
    run: Callable[[Sequence[str]], tuple[int, str]] | None = None,
    cpu_count: int | None = None,
    ram_gib: float | None = None,
) -> LocalResources:
    which = which or toolchain_which
    run = run or _default_run
    gpus: list[Gpu] = []
    if which("nvidia-smi"):
        code, output = run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,compute_cap",
                "--format=csv,noheader",
            ]
        )
        if code == 0:
            gpus = parse_nvidia_smi(output)
    docker = bool(which("docker"))
    docker_gpu = False
    if docker:
        code, output = run(["docker", "info", "--format", "{{json .Runtimes}}"])
        docker_gpu = code == 0 and "nvidia" in output
    return LocalResources(
        cpu_count=cpu_count if cpu_count is not None else (os.cpu_count() or 1),
        ram_gib=ram_gib if ram_gib is not None else _ram_gib(),
        gpus=gpus,
        docker=docker,
        docker_gpu=docker_gpu,
    )


@dataclass(frozen=True)
class RemoteBackend:
    kind: str
    host: str
    user: str = ""
    partition: str = ""
    gpus: int = 0

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "host": self.host,
            "user": self.user,
            "partition": self.partition,
            "gpus": self.gpus,
        }


def load_backends(paper_root: Path) -> list[RemoteBackend]:
    """Read ``data/compute.yaml``; an absent file means no remote compute."""
    path = Path(paper_root) / COMPUTE_CONFIG
    if not path.is_file():
        return []
    try:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    entries = payload.get("backends")
    backends: list[RemoteBackend] = []
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            host = item.get("host")
            if kind not in {"slurm", "pbs"} or not isinstance(host, str):
                continue
            backends.append(
                RemoteBackend(
                    kind=kind,
                    host=host,
                    user=str(item.get("user") or ""),
                    partition=str(item.get("partition") or ""),
                    gpus=int(item.get("gpus") or 0),
                )
            )
    return backends


def probe_remote(
    backend: RemoteBackend,
    *,
    run: Callable[[Sequence[str]], tuple[int, str]] | None = None,
) -> dict:
    """Check that SSH reaches *host* and the scheduler command exists."""
    run = run or _default_run
    command = "sbatch --version" if backend.kind == "slurm" else "qstat --version"
    code, output = run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", backend.target, command]
    )
    return {
        **backend.as_dict(),
        "reachable": code == 0,
        "detail": output.strip()[:200] if code == 0 else "SSH 或调度器不可用",
    }


@dataclass
class Attempt:
    command: str
    backend: str
    budget_minutes: float
    wall_seconds: float
    returncode: int
    gpus_used: int
    timed_out: bool

    @property
    def gpu_minutes(self) -> float:
        return round(self.wall_seconds / 60.0 * self.gpus_used, 3)

    def as_dict(self) -> dict:
        return {
            "command": self.command,
            "backend": self.backend,
            "budget_minutes": self.budget_minutes,
            "wall_seconds": round(self.wall_seconds, 2),
            "gpu_minutes": self.gpu_minutes,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "recorded_at": _now_iso(),
        }


def run_local(
    command: Sequence[str],
    *,
    budget_minutes: float,
    gpus_used: int = 0,
    cwd: Path | None = None,
    popen: Callable[..., subprocess.Popen] | None = None,
) -> Attempt:
    """Run *command* under a wall-clock budget and return measured cost."""
    if budget_minutes <= 0:
        raise ValueError("budget_minutes 必须为正数")
    runner = popen or subprocess.Popen
    started = time.monotonic()
    timed_out = False
    process = runner(
        list(command),
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        process.communicate(timeout=budget_minutes * 60)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.communicate()
    wall = time.monotonic() - started
    return Attempt(
        command=" ".join(command),
        backend="local",
        budget_minutes=budget_minutes,
        wall_seconds=wall,
        returncode=process.returncode if process.returncode is not None else -1,
        gpus_used=gpus_used,
        timed_out=timed_out,
    )


def append_attempt(paper_root: Path, attempt: Attempt) -> Path:
    path = Path(paper_root) / COMPUTE_LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(attempt.as_dict(), ensure_ascii=False) + "\n")
    return path


def plan(
    paper_root: Path,
    *,
    budget_minutes: float,
    needs_gpu: bool = False,
    resources: LocalResources | None = None,
    backends: list[RemoteBackend] | None = None,
) -> dict:
    """Decide which backends can serve a pilot, without overstating reach."""
    resources = resources or probe_local()
    backends = backends if backends is not None else load_backends(paper_root)
    local_ok = not needs_gpu or resources.gpu_count > 0
    return {
        "budget_minutes": budget_minutes,
        "needs_gpu": needs_gpu,
        "local": {
            "usable": local_ok,
            "gpus": resources.gpu_count,
            "docker_gpu": resources.docker_gpu,
            "note": (
                "本地 GPU 秒预算可用" if local_ok else "本机无 GPU，pilot 只能 CPU 级或需要远程算力"
            ),
        },
        "remote": [backend.as_dict() for backend in backends],
        "remote_configured": bool(backends),
        "recommendation": (
            "local" if local_ok and not backends else ("remote" if backends else "blocked")
        ),
    }


def check_environment(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    """Report compute capability as problems (blocking) and advisories."""
    resources = probe_local()
    backends = load_backends(paper_root)
    problems: list[Problem] = []
    advisories: list[Problem] = []
    path = Path(paper_root) / COMPUTE_CONFIG
    if not resources.gpu_count and not backends:
        advisories.append(
            Problem(
                "compute-no-gpu-no-remote",
                str(path),
                None,
                "本机无 GPU 且未配置远程算力：experiment-loop 的 pilot 受限",
            )
        )
    if not backends:
        advisories.append(
            Problem(
                "compute-remote-unconfigured",
                str(path),
                None,
                "未配置 Slurm/PBS 远程后端（data/compute.yaml 缺失或为空）",
            )
        )
    return problems, advisories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="算力探测、pilot 预算执行与单次尝试成本台账")
    sub = parser.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("probe", help="探测本机 CPU/内存/GPU/Docker 与远程后端")
    probe.add_argument("--paper-root", default=".")
    sub.add_parser("check", help="以 problem/advisory 形式报告算力缺口")

    plan_parser = sub.add_parser("plan", help="判断某预算能否被某个后端承接")
    plan_parser.add_argument("--paper-root", default=".")
    plan_parser.add_argument("--minutes", type=float, required=True)
    plan_parser.add_argument("--needs-gpu", action="store_true")

    run_parser = sub.add_parser("run", help="在墙钟预算内执行命令并记账")
    run_parser.add_argument("--paper-root", default=".")
    run_parser.add_argument("--minutes", type=float, required=True)
    run_parser.add_argument("--gpus", type=int, default=0)
    run_parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "probe":
            resources = probe_local()
            backends = load_backends(Path(args.paper_root))
            payload = {
                "local": resources.as_dict(),
                "remote": [probe_remote(backend) for backend in backends],
                "remote_configured": bool(backends),
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command == "check":
            problems, advisories = check_environment(Path("."))
            return emit(problems, advisories)
        if args.command == "plan":
            payload = plan(
                Path(args.paper_root),
                budget_minutes=args.minutes,
                needs_gpu=args.needs_gpu,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            if payload["recommendation"] == "blocked":
                print(
                    "PILOT 受阻：无可用算力承接该预算",
                    file=sys.stderr,
                )
                return 1
            return 0
        command = [item for item in args.command if item != "--"]
        if not command:
            return tool_error("run 需要一条命令")
        attempt = run_local(
            command,
            budget_minutes=args.minutes,
            gpus_used=args.gpus,
        )
        path = append_attempt(Path(args.paper_root), attempt)
        print(json.dumps(attempt.as_dict(), ensure_ascii=False))
        print(f"已记录到 {path}", file=sys.stderr)
        return 1 if attempt.timed_out else attempt.returncode
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
