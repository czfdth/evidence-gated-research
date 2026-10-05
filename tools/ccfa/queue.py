"""Run experiment queues with explicit retry and budget stop conditions.

The injected runner contract is ``runner(argv, cwd, timeout_s) -> int``.
It may raise ``subprocess.TimeoutExpired`` or ``TimeoutError``. The default
runner uses ``subprocess.Popen(..., shell=False)``, streams 子进程 stdout/stderr
line by line and forwards both 转发到 stderr so queue stdout 只输出 JSON.
Timeouts still forward output that was already produced.

Timeouts retry only when the manifest explicitly sets
``retry_on_timeout: true``. A cwd 不存在 is a runtime error: that attempt still
gets a failed run-log record, then the queue raises ValueError and exits 2.

Long-task safety v1 adds an exclusive lock per log directory, an nvidia-smi
GPU-second budget, a no-output stall watchdog, and two optional sandbox
backends. ``sandbox=policy`` only constrains cwd containment and the child
environment; it is not filesystem, network, or GPU isolation.
``sandbox=docker`` runs the item in a container with a read-only rootfs,
read-only queue-root mount, a writable output mount, and network disabled by
default. The image is trusted input; this is process isolation, not a
security boundary against a malicious image.

For automation consumption, ``queue run`` stdout 只输出 JSON. Child output
remains visible without corrupting the machine-readable result. This differs
deliberately from ``run-log run``, which passes stdio through.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

from ccfa.cli import tool_error
from ccfa.run_log import log_metrics, log_resource_usage, run_command

QUEUE_VERSION = 1
SANDBOX_MODES = ("none", "policy", "docker")
GPU_UTILIZATION_THRESHOLD = 5
GPU_SAMPLE_INTERVAL_S = 1.0
SANDBOX_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONNOUSERSITE",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "CUDA_VISIBLE_DEVICES",
        "NVIDIA_VISIBLE_DEVICES",
    }
)


class QueueStalled(TimeoutError):
    """Raised when a child produced no output for the stall timeout."""


class QueueLocked(ValueError):
    """Raised when another queue instance owns the same log directory."""


def _load_payload(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取队列清单 {path}: {exc}") from exc
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"队列清单解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("队列清单顶层必须是对象")
    return payload


def _load_queue_document(path: Path) -> tuple[list[dict], dict]:
    """Load queue items and queue-level options."""
    path = Path(path)
    payload = _load_payload(path)
    if payload.get("schema_version") != QUEUE_VERSION:
        raise ValueError(
            f"队列 schema_version 必须是 {QUEUE_VERSION}: "
            f"{payload.get('schema_version')!r}"
        )
    sandbox = payload.get("sandbox", "none")
    if sandbox not in SANDBOX_MODES:
        raise ValueError(
            f"队列 sandbox 必须是 {' 或 '.join(SANDBOX_MODES)}: {sandbox!r}"
        )
    gpu_budget_s = payload.get("gpu_budget_s")
    if gpu_budget_s is not None and (
        isinstance(gpu_budget_s, bool)
        or not isinstance(gpu_budget_s, (int, float))
        or gpu_budget_s < 0
    ):
        raise ValueError("队列 gpu_budget_s 必须是非负数")
    docker_image = payload.get("docker_image")
    if docker_image is not None and (
        not isinstance(docker_image, str) or not docker_image.strip()
    ):
        raise ValueError("队列 docker_image 必须是非空字符串")
    docker_network = payload.get("docker_network", "none")
    if not isinstance(docker_network, str) or not docker_network.strip():
        raise ValueError("队列 docker_network 必须是非空字符串")
    docker_gpus = payload.get("docker_gpus")
    if docker_gpus not in (None, "all"):
        raise ValueError("队列 docker_gpus 目前只支持 null 或 'all'")
    docker_output = payload.get("docker_output", "runs")
    if not isinstance(docker_output, str) or not docker_output.strip():
        raise ValueError("队列 docker_output 必须是非空相对目录")
    output_parts = Path(docker_output).parts
    if (
        Path(docker_output).is_absolute()
        or Path(docker_output).root
        or Path(docker_output).drive
        or ".." in output_parts
        or not output_parts
    ):
        raise ValueError("队列 docker_output 必须是队列根内的相对目录")
    if sandbox == "docker" and docker_image is None:
        raise ValueError("sandbox=docker 需要队列 docker_image")

    items = None
    for key in ("queue", "items", "runs"):
        if key in payload:
            items = payload[key]
            break
    if not isinstance(items, list):
        raise ValueError("队列清单必须包含 queue/items/runs 列表")

    normalized: list[dict] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"队列第 {index} 项必须是对象")
        name = item.get("name")
        command = item.get("command")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"队列第 {index} 项缺少非空 name")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            raise ValueError(f"队列第 {index} 项 command 必须是非空字符串列表")
        cwd = item.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError(f"队列第 {index} 项 cwd 必须是字符串")
        timeout_s = item.get("timeout_s")
        if timeout_s is not None and (
            not isinstance(timeout_s, (int, float))
            or isinstance(timeout_s, bool)
            or timeout_s <= 0
        ):
            raise ValueError(f"队列第 {index} 项 timeout_s 必须是正数")
        stall_timeout_s = item.get("stall_timeout_s")
        if stall_timeout_s is not None and (
            not isinstance(stall_timeout_s, (int, float))
            or isinstance(stall_timeout_s, bool)
            or stall_timeout_s <= 0
        ):
            raise ValueError(f"队列第 {index} 项 stall_timeout_s 必须是正数")
        retry_exit_codes = item.get("retry_exit_codes", [])
        if not isinstance(retry_exit_codes, list) or not all(
            type(code) is int for code in retry_exit_codes
        ):
            raise ValueError(
                f"队列第 {index} 项 retry_exit_codes 必须是整数列表"
            )
        retry_on_timeout = item.get("retry_on_timeout", False)
        if not isinstance(retry_on_timeout, bool):
            raise ValueError(
                f"队列第 {index} 项 retry_on_timeout 必须是布尔值"
            )
        retry_on_stall = item.get("retry_on_stall", False)
        if not isinstance(retry_on_stall, bool):
            raise ValueError(
                f"队列第 {index} 项 retry_on_stall 必须是布尔值"
            )
        max_attempts = item.get("max_attempts", 1)
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError(f"队列第 {index} 项 max_attempts 必须是正整数")
        normalized.append(
            {
                "name": name,
                "command": list(command),
                "cwd": cwd,
                "timeout_s": timeout_s,
                "stall_timeout_s": stall_timeout_s,
                "retry_exit_codes": list(retry_exit_codes),
                "retry_on_timeout": retry_on_timeout,
                "retry_on_stall": retry_on_stall,
                "max_attempts": max_attempts,
            }
        )
    options = {
        "sandbox": sandbox,
        "gpu_budget_s": gpu_budget_s,
        "docker_image": docker_image,
        "docker_network": docker_network,
        "docker_gpus": docker_gpus,
        "docker_output": docker_output,
    }
    return normalized, options


def load_queue(path: Path) -> list[dict]:
    """Load and normalize a queue manifest."""
    items, _options = _load_queue_document(path)
    return items


class QueueLock:
    """A process lock for one queue log directory.

    The lock is an OS file lock (``fcntl.flock`` on POSIX, ``msvcrt.locking``
    on Windows), so process death releases it automatically. The file keeps
    diagnostic metadata but no stale-PID recovery protocol is needed.
    """

    def __init__(self, log_dir: Path):
        self.path = Path(log_dir) / ".queue.lock"
        self.pid = os.getpid()
        self._fd = None

    @staticmethod
    def _try_lock(descriptor: int) -> bool:
        if fcntl is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return False
            return True
        if msvcrt is not None:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError:
                return False
            return True
        raise ValueError("当前平台没有可用的文件锁实现")

    @staticmethod
    def _unlock(descriptor: int) -> None:
        if fcntl is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        elif msvcrt is not None:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass

    def _metadata(self) -> dict:
        try:
            data = self.path.read_bytes()
        except OSError:
            return {}
        if len(data) <= 1:
            return {}
        try:
            payload = json.loads(data[1:].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def __enter__(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"无法创建队列锁目录 {self.path.parent}: {exc}") from exc
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR)
        except OSError as exc:
            raise ValueError(f"无法打开队列锁 {self.path}: {exc}") from exc
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            if not self._try_lock(descriptor):
                metadata = self._metadata()
                owner = metadata.get("pid", "unknown")
                raise QueueLocked(
                    f"另一个队列正在运行 (pid={owner})，锁文件: {self.path}"
                )
            payload = json.dumps(
                {
                    "pid": self.pid,
                    "created_at": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            os.lseek(descriptor, 1, os.SEEK_SET)
            os.ftruncate(descriptor, 1)
            os.write(descriptor, payload)
        except QueueLocked:
            self._unlock(descriptor)
            os.close(descriptor)
            raise
        except OSError as exc:
            self._unlock(descriptor)
            os.close(descriptor)
            raise ValueError(f"无法初始化队列锁 {self.path}: {exc}") from exc
        self._fd = descriptor
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        if self._fd is not None:
            self._unlock(self._fd)
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        return False


def _nvidia_smi_utilization() -> int:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"无法运行 nvidia-smi: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise ValueError(f"nvidia-smi 退出码 {completed.returncode}: {detail}")
    values: list[int] = []
    for line in completed.stdout.splitlines():
        value = line.strip()
        if not value:
            continue
        try:
            values.append(int(float(value)))
        except ValueError as exc:
            raise ValueError(f"nvidia-smi 返回了非数字利用率: {value!r}") from exc
    if not values:
        raise ValueError("nvidia-smi 未返回 GPU 利用率")
    return max(values)


class GpuMeter:
    """Sample nvidia-smi and accumulate wall time while the GPU is busy."""

    def __init__(
        self,
        *,
        reader=None,
        clock=None,
        interval_s: float = GPU_SAMPLE_INTERVAL_S,
        threshold: int = GPU_UTILIZATION_THRESHOLD,
    ):
        self._reader = reader or _nvidia_smi_utilization
        self._clock = clock or time.monotonic
        self._interval_s = max(0.01, float(interval_s))
        self._threshold = int(threshold)
        self._stop = threading.Event()
        self._thread = None
        self._last = None
        self._busy_seconds = 0.0
        self._samples = 0
        self._errors = 0

    def _sample(self) -> None:
        if self._last is None:
            self._last = self._clock()
            return
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._last = now
        try:
            utilization = self._reader()
        except ValueError:
            self._errors += 1
            return
        self._samples += 1
        if utilization >= self._threshold:
            self._busy_seconds += elapsed

    def _loop(self) -> None:
        while not self._stop.wait(self._interval_s):
            self._sample()

    def start(self) -> None:
        # Validate the reader before the child starts. A missing nvidia-smi
        # must be a tool error, not a silently uncounted GPU budget.
        self._reader()
        self._last = self._clock()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread is not None:
            # The reader has its own subprocess timeout; waiting here removes
            # the old overlap where stop() and the sampler both recorded a
            # final interval.
            self._thread.join()
            self._thread = None
        self._sample()
        return {
            "seconds": round(self._busy_seconds, 6),
            "samples": self._samples,
            "errors": self._errors,
        }


def _sandbox_env(environ=None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    filtered = {
        key: value
        for key, value in source.items()
        if key.upper() in SANDBOX_ENV_ALLOWLIST
    }
    filtered.setdefault("PYTHONNOUSERSITE", "1")
    return filtered


def _docker_available() -> None:
    try:
        completed = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Docker daemon 不可用: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise ValueError(
            "Docker daemon 不可用: " + (detail or "docker info failed")
        )


def _docker_argv(
    item: dict,
    queue_root: Path,
    *,
    image: str,
    network: str,
    gpus: str | None,
    output_relative: str,
    env: dict[str, str],
    name: str,
) -> list[str]:
    root = queue_root.resolve()
    workdir = _docker_workdir(queue_root, item)
    output_dir = (root / output_relative).resolve()
    if output_dir == root:
        raise ValueError("docker_output 不能是队列根")
    try:
        output_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"docker_output 逃出队列根: {output_relative}") from exc
    if "," in str(root) or "," in str(output_dir):
        raise ValueError("Docker bind mount 源路径不能包含逗号")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"无法创建 Docker 输出目录 {output_dir}: {exc}") from exc
    argv = [
        "docker",
        "run",
        "--rm",
        "--read-only",
        "--security-opt",
        "no-new-privileges",
        "--network",
        network,
        "--tmpfs",
        "/tmp",
        "--name",
        name,
        "--mount",
        f"type=bind,source={root},target=/workspace,readonly",
        "--mount",
        f"type=bind,source={output_dir},target=/outputs",
        "--workdir",
        workdir,
    ]
    if gpus == "all":
        argv.extend(["--gpus", "all"])
    for key, value in sorted(env.items()):
        argv.extend(["-e", f"{key}={value}"])
    argv.extend(
        [
            "-e",
            "HOME=/tmp",
            "-e",
            "CCFA_WORKSPACE=/workspace",
            "-e",
            "CCFA_OUTPUT_DIR=/outputs",
            image,
            *item["command"],
        ]
    )
    return argv


def _docker_workdir(queue_root: Path, item: dict) -> str:
    root = queue_root.resolve()
    cwd = _item_cwd(queue_root, item, sandbox=True)
    relative = cwd.relative_to(root).as_posix()
    return "/workspace" if relative == "." else f"/workspace/{relative}"


def _docker_container_name(item_name: str, index: int, attempt: int) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "-", item_name).strip("-._") or "item"
    return f"ccfa-{index + 1}-{attempt}-{base[:40]}-{uuid.uuid4().hex[:12]}"


def _docker_remove(name: str) -> None:
    """Best-effort cleanup after a killed Docker CLI left a container."""
    try:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _forward_stream(stream, activity: list[float]) -> None:
    try:
        try:
            descriptor = stream.fileno()
        except (AttributeError, OSError):
            descriptor = None
        if descriptor is None:
            chunk = stream.read()
            if chunk:
                activity[0] = time.monotonic()
                sys.stderr.write(
                    chunk.decode("utf-8", errors="replace")
                    if isinstance(chunk, bytes)
                    else chunk
                )
                flush = getattr(sys.stderr, "flush", None)
                if flush is not None:
                    flush()
            return
        while True:
            chunk = os.read(descriptor, 4096)
            if not chunk:
                break
            activity[0] = time.monotonic()
            sys.stderr.write(chunk.decode("utf-8", errors="replace"))
            flush = getattr(sys.stderr, "flush", None)
            if flush is not None:
                flush()
    finally:
        stream.close()


def _default_runner(
    argv: list[str],
    cwd: Path,
    timeout_s: float | None,
    *,
    stall_timeout_s: float | None = None,
    env=None,
) -> int:
    process = subprocess.Popen(
        list(argv),
        cwd=str(cwd),
        shell=False,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    activity = [time.monotonic()]
    pumps = [
        threading.Thread(
            target=_forward_stream,
            args=(process.stdout, activity),
            daemon=True,
        ),
        threading.Thread(
            target=_forward_stream,
            args=(process.stderr, activity),
            daemon=True,
        ),
    ]
    for pump in pumps:
        pump.start()
    deadline = None if timeout_s is None else time.monotonic() + float(timeout_s)
    try:
        while True:
            try:
                returncode = process.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    raise
                if (
                    stall_timeout_s is not None
                    and now - activity[0] >= float(stall_timeout_s)
                ):
                    raise QueueStalled(
                        f"子进程 {float(stall_timeout_s):g} 秒无输出"
                    )
    except (subprocess.TimeoutExpired, QueueStalled):
        try:
            process.kill()
        except OSError:
            pass
        process.wait()
        for pump in pumps:
            pump.join()
        raise
    for pump in pumps:
        pump.join()
    return int(returncode)


def _item_cwd(
    queue_root: Path,
    item: dict,
    *,
    sandbox: bool = False,
) -> Path:
    cwd = item.get("cwd")
    if not cwd:
        resolved = queue_root
    else:
        path = Path(cwd)
        resolved = path if path.is_absolute() else queue_root / path
    resolved = resolved.resolve()
    if sandbox:
        try:
            resolved.relative_to(queue_root.resolve())
        except ValueError as exc:
            raise ValueError(
                f"沙箱策略拒绝队列项 {item.get('name')!r} 逃出队列根: {resolved}"
            ) from exc
    return resolved


def run_queue(
    queue_path: Path,
    *,
    log_dir: Path,
    runner=None,
    budget_s: float | None = None,
    clock=None,
    gpu_budget_s: float | None = None,
    gpu_meter_factory=None,
    sandbox: str | None = None,
    allow_sandbox_downgrade: bool = False,
    allow_injected_runner: bool = False,
) -> dict:
    """Run queue items in order and return per-run outcomes.

    ``sandbox="policy"`` is a policy layer: the item cwd must stay under the
    queue root and the default runner receives only the environment allowlist.
    It is not filesystem, network, or GPU isolation.

    ``sandbox="docker"`` runs each item through ``docker run`` with a
    read-only rootfs, a read-only queue-root mount, a writable output mount,
    and network disabled by default. Docker daemon availability is checked
    once before the first item; an unavailable daemon is a tool error and is
    never treated as permission to fall back to the host.

    A CLI ``sandbox`` override may strengthen a manifest, but downgrading a
    manifest that declares ``docker`` requires ``allow_sandbox_downgrade``.
    Injected runners are a test seam: policy and Docker modes reject them
    unless ``allow_injected_runner`` is set explicitly.
    """
    queue_path = Path(queue_path)
    queue_root = queue_path.parent
    log_dir = Path(log_dir)
    if budget_s is not None and budget_s < 0:
        raise ValueError("budget_s 必须是非负数")
    items, options = _load_queue_document(queue_path)
    sandbox_mode = options["sandbox"] if sandbox is None else sandbox
    if sandbox_mode not in SANDBOX_MODES:
        raise ValueError(
            f"sandbox 必须是 {' 或 '.join(SANDBOX_MODES)}: {sandbox_mode!r}"
        )
    if (
        options["sandbox"] == "docker"
        and sandbox_mode != "docker"
        and not allow_sandbox_downgrade
    ):
        raise ValueError(
            "队列声明 sandbox=docker；CLI 覆盖到 "
            f"{sandbox_mode} 会关闭容器隔离；"
            "确需降级请显式 --allow-sandbox-downgrade"
        )
    if gpu_budget_s is None:
        gpu_budget_s = options.get("gpu_budget_s")
    if gpu_budget_s is not None and gpu_budget_s < 0:
        raise ValueError("gpu_budget_s 必须是非负数")

    docker_image = options["docker_image"]
    docker_network = options["docker_network"]
    docker_gpus = options["docker_gpus"]
    docker_output = options["docker_output"]
    if sandbox_mode == "docker":
        if not docker_image:
            raise ValueError("sandbox=docker 需要队列 docker_image")
        _docker_available()

    default_runner = runner is None or runner is _default_runner
    if (
        sandbox_mode in ("policy", "docker")
        and not default_runner
        and not allow_injected_runner
    ):
        raise ValueError(
            f"sandbox={sandbox_mode} 仅支持默认 runner；"
            "注入 runner 必须显式 allow_injected_runner=True，"
            "否则无法保证沙箱语义"
        )
    run = runner or _default_runner
    now = clock or time.monotonic
    gpu_meter_factory = gpu_meter_factory or GpuMeter

    def invoke(argv, cwd, timeout_s, *, item, sandbox_env):
        if default_runner:
            return _default_runner(
                list(argv),
                Path(cwd),
                timeout_s,
                stall_timeout_s=item["stall_timeout_s"],
                env=sandbox_env,
            )
        return int(run(list(argv), Path(cwd), timeout_s))

    with QueueLock(log_dir):
        started = now()
        gpu_total = 0.0
        runs: list[dict] = []
        stopped: str | None = None
        for index, item in enumerate(items):
            if gpu_budget_s is not None and gpu_total >= gpu_budget_s:
                for skipped in items[index:]:
                    runs.append(
                        {
                            "name": skipped["name"],
                            "attempts": 0,
                            "status": "skipped-gpu-budget",
                        }
                    )
                stopped = "gpu-budget"
                break
            if budget_s is not None and now() - started >= budget_s:
                for skipped in items[index:]:
                    runs.append(
                        {
                            "name": skipped["name"],
                            "attempts": 0,
                            "status": "skipped-budget",
                        }
                    )
                stopped = "budget"
                break

            cwd = _item_cwd(
                queue_root,
                item,
                sandbox=sandbox_mode in ("policy", "docker"),
            )
            sandbox_env = _sandbox_env() if sandbox_mode == "policy" else None
            policy_record = None
            if sandbox_mode == "policy":
                policy_record = {"sandbox": "policy"}
            elif sandbox_mode == "docker":
                policy_record = {
                    "sandbox": "docker",
                    "image": docker_image,
                    "network": docker_network,
                    "gpus": docker_gpus,
                    "output": docker_output,
                    "workdir": _docker_workdir(queue_root, item),
                }
            attempts = 0
            status = "failed"
            gpu_exhausted = False
            while attempts < item["max_attempts"]:
                attempts += 1
                timed_out = False
                stalled = False
                meter = None
                meter_reading = None

                container_name = None
                docker_argv = None
                if sandbox_mode == "docker":
                    container_name = _docker_container_name(
                        item["name"], index, attempts
                    )
                    docker_argv = _docker_argv(
                        item,
                        queue_root,
                        image=docker_image,
                        network=docker_network,
                        gpus=docker_gpus,
                        output_relative=docker_output,
                        env={},
                        name=container_name,
                    )

                if gpu_budget_s is not None:
                    meter = gpu_meter_factory()
                    meter.start()

                def attempt_runner(argv, attempt_cwd):
                    nonlocal timed_out, stalled
                    effective_argv = (
                        docker_argv if docker_argv is not None else argv
                    )
                    try:
                        return (
                            invoke(
                                effective_argv,
                                attempt_cwd,
                                item["timeout_s"],
                                item=item,
                                sandbox_env=sandbox_env,
                            ),
                            "",
                        )
                    except QueueStalled:
                        stalled = True
                        return 124, ""
                    except (subprocess.TimeoutExpired, TimeoutError):
                        timed_out = True
                        return 124, ""
                    finally:
                        if container_name is not None:
                            _docker_remove(container_name)

                try:
                    run_id, record = run_command(
                        item["command"],
                        log_dir,
                        cwd,
                        cwd=str(cwd),
                        policy=policy_record,
                        runner=attempt_runner,
                    )
                finally:
                    if meter is not None:
                        meter_reading = meter.stop()

                attempt_metrics: dict = {}
                resource_usage: dict = {}
                if timed_out:
                    attempt_metrics.update(
                        timeout=True,
                        timeout_s=item["timeout_s"],
                    )
                if stalled:
                    attempt_metrics.update(
                        stalled=True,
                        stall_timeout_s=item["stall_timeout_s"],
                    )
                if meter_reading is not None:
                    gpu_total += float(meter_reading["seconds"])
                    resource_usage["gpu_seconds"] = meter_reading["seconds"]
                    resource_usage["gpu_samples"] = meter_reading["samples"]
                    if meter_reading["errors"]:
                        resource_usage["gpu_sampling_errors"] = meter_reading["errors"]
                if attempt_metrics:
                    log_metrics(log_dir, run_id, attempt_metrics)
                if resource_usage:
                    log_resource_usage(log_dir, run_id, resource_usage)
                if meter_reading is not None and meter_reading["errors"]:
                    raise ValueError(
                        "GPU 利用率采样失败，无法可靠执行 GPU 预算"
                    )

                exit_code = record["exit_code"]
                if gpu_budget_s is not None and gpu_total >= gpu_budget_s:
                    gpu_exhausted = True
                if exit_code == 0:
                    status = "complete"
                    break
                if stalled:
                    status = "stalled"
                elif timed_out:
                    status = "timeout"
                else:
                    status = "failed"
                retryable = (
                    exit_code in item["retry_exit_codes"]
                    or (timed_out and item["retry_on_timeout"])
                    or (stalled and item["retry_on_stall"])
                )
                if retryable and attempts < item["max_attempts"]:
                    if gpu_exhausted:
                        break
                    continue
                if retryable and item["max_attempts"] > 1:
                    stopped = "retries"
                break

            runs.append(
                {
                    "name": item["name"],
                    "attempts": attempts,
                    "status": status,
                }
            )
            if gpu_exhausted and index + 1 < len(items):
                for skipped in items[index + 1 :]:
                    runs.append(
                        {
                            "name": skipped["name"],
                            "attempts": 0,
                            "status": "skipped-gpu-budget",
                        }
                    )
                stopped = "gpu-budget"
                break
            if stopped == "retries":
                break

        return {"runs": runs, "stopped": stopped}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "顺序运行实验队列。超时仅在 retry_on_timeout=true 时重试；"
            "stall_timeout_s 无输出即判卡死；--gpu-budget-seconds 按 "
            "nvidia-smi 利用率累计 GPU 秒数；同一 log-dir 只允许一个队列；"
            "sandbox=policy 只做 cwd 与环境白名单，不是 OS 隔离。"
            "sandbox=docker 只读挂载队列根、仅 docker_output 可写、"
            "默认禁网；Docker daemon 不可用退 2，不静默回退。"
            "清单声明 docker 时，CLI 降级到 none/policy 需显式 --allow-sandbox-downgrade。"
            "cwd 不存在时该次尝试仍写 failed 记录，整体退出 2。"
            "stdout 只输出结果 JSON；子进程 stdout/stderr 流式转发到 stderr。"
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="运行队列")
    run.add_argument("--queue", required=True)
    run.add_argument("--log-dir", required=True)
    run.add_argument("--budget-seconds", type=float)
    run.add_argument("--gpu-budget-seconds", type=float)
    run.add_argument("--sandbox", choices=SANDBOX_MODES)
    run.add_argument(
        "--allow-sandbox-downgrade",
        action="store_true",
        help="显式允许 CLI 覆盖清单里的 docker 沙箱；默认拒绝",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        result = run_queue(
            Path(args.queue),
            log_dir=Path(args.log_dir),
            budget_s=args.budget_seconds,
            gpu_budget_s=args.gpu_budget_seconds,
            sandbox=args.sandbox,
            allow_sandbox_downgrade=args.allow_sandbox_downgrade,
        )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if any(item["status"] != "complete" for item in result["runs"]):
        return 1
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
