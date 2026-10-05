"""Fetch portable toolchain binaries through mirrors reachable from this host.

The machine this workflow runs on reaches GitHub's web/API endpoints but its
release-asset CDN is throttled to a few tens of kilobytes per second, its DNS
resolver answers ``zenodo.org`` with ``0.0.0.0``, and ``pypi.org`` TLS
handshakes time out. Every artifact here therefore lists mirror URLs in
priority order, and the downloader falls through them until one responds.

The tool is deliberately dependency-free so it can bootstrap before any
virtualenv exists. It never edits system locations that need elevation: the
``msi-admin`` mode uses an administrative extract (``msiexec /a``) instead of
installing, so LibreOffice lands under the user profile without a UAC prompt.
"""

from __future__ import annotations

import argparse
import glob as glob_module
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path


def default_dest() -> Path:
    """Resolve the install root: env override, then relocation pointer, then default."""
    override = os.environ.get("CODEX_TOOLS_DIR")
    if override:
        return Path(override)
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    pointer = base / "codex-tools-location"
    try:
        if pointer.is_file():
            recorded = pointer.read_text(encoding="utf-8").strip()
            if recorded:
                return Path(recorded)
    except OSError:
        pass
    return base / "codex-tools"


# GitHub release assets are proxied; direct downloads run at ~0.03 MB/s here
# while the gh-proxy front end reaches ~0.2 MB/s.
_GH = "https://gh-proxy.com/https://github.com"


@dataclass(frozen=True)
class Artifact:
    key: str
    version: str
    urls: tuple[str, ...]
    archive: str
    # Path inside the extracted tree that contains executables. ``None`` means
    # the extracted root itself is scanned.
    bin_dir: str | None = None
    # Executables to expose on PATH through the shared shim directory.
    executables: tuple[str, ...] = ()
    # For ``archive="existing"``: absolute paths already present on the host.
    source_paths: tuple[str, ...] = ()
    sha256: str | None = None
    note: str = ""
    # Some mirrors (TUNA's LibreOffice tree) answer 403 to a browser-like UA and
    # throttle this tool's default UA, but stream at full speed when the header
    # is absent. ``None`` omits User-Agent entirely.
    user_agent: str | None = "codex-toolchain-fetch/1.0"
    extra: dict[str, str] = field(default_factory=dict)


ARTIFACTS: tuple[Artifact, ...] = (
    Artifact(
        key="qpdf",
        version="12.4.2",
        urls=(
            f"{_GH}/qpdf/qpdf/releases/download/v12.4.2/qpdf-12.4.2-msvc64.zip",
            "https://github.com/qpdf/qpdf/releases/download/v12.4.2/qpdf-12.4.2-msvc64.zip",
        ),
        # A winget / Program Files install is preferred: it receives updates and
        # lives outside the portable root. The zip is the fallback when absent.
        archive="auto",
        bin_dir="qpdf-12.4.2-msvc64/bin",
        source_paths=(
            r"C:\Program Files\qpdf*\bin\qpdf.exe",
            r"C:\Program Files (x86)\qpdf*\bin\qpdf.exe",
            "{tools}\\qpdf\\qpdf-12.4.2-msvc64\\bin\\qpdf.exe",
        ),
        executables=("qpdf.exe",),
        note="PDF 结构检查、修复与线性化（系统安装优先，缺失时回退便携版）",
    ),
    Artifact(
        key="typst",
        version="0.13.1",
        urls=(
            f"{_GH}/typst/typst/releases/download/v0.13.1/typst-x86_64-pc-windows-msvc.zip",
            "https://github.com/typst/typst/releases/download/v0.13.1/"
            "typst-x86_64-pc-windows-msvc.zip",
        ),
        archive="zip",
        bin_dir="typst-x86_64-pc-windows-msvc",
        executables=("typst.exe",),
        note="Typst 排版运行时（typst-paper skill 依赖）",
    ),
    Artifact(
        key="quarto",
        version="1.8.25",
        urls=(
            f"{_GH}/quarto-dev/quarto-cli/releases/download/v1.8.25/quarto-1.8.25-win.zip",
            "https://github.com/quarto-dev/quarto-cli/releases/download/v1.8.25/"
            "quarto-1.8.25-win.zip",
        ),
        archive="auto",
        bin_dir="quarto-1.8.25/bin",
        source_paths=(
            r"C:\Program Files\Quarto\bin\quarto.exe",
            "{tools}\\quarto\\quarto-1.8.25\\bin\\quarto.exe",
        ),
        executables=("quarto.exe",),
        note="Quarto 可复现报告运行时（系统安装优先，缺失时回退便携版）",
    ),
    Artifact(
        key="micromamba",
        version="2.4.0",
        urls=(
            "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/"
            "win-64/micromamba-2.4.0-0.tar.bz2",
        ),
        archive="tar.bz2",
        bin_dir="Library/bin",
        executables=("micromamba.exe",),
        note="conda/mamba 兼容的环境管理器（conda-forge 通道）",
    ),
    Artifact(
        key="libreoffice",
        version="25.8.7",
        urls=(
            "https://mirrors.tuna.tsinghua.edu.cn/libreoffice/libreoffice/stable/"
            "25.8.7/win/x86_64/LibreOffice_25.8.7_Win_x86-64.msi",
        ),
        archive="msi-admin",
        bin_dir="LibreOffice/program",
        # soffice.exe is the GUI subsystem binary and does not return for
        # ``--version``/``--convert-to`` when spawned from a console; soffice.com
        # is the console companion and is the correct headless entry point.
        executables=("soffice.com",),
        user_agent=None,
        note="DOCX/PPTX/XLSX 文档转换（lessmsi 解包，无需管理员与 Windows Installer 服务）",
    ),
    Artifact(
        key="mutool",
        version="1.28.0",
        urls=(),
        archive="existing",
        source_paths=(
            # mupdf.com is unreachable from this host, so mutool comes from the
            # conda-forge ``mupdf`` package instead. Build it once with:
            #   micromamba create -y -p <tools>\mupdf-env \
            #     https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge::mupdf
            # then keep only ``Library\bin`` (222 MB) as ``<tools>\mutool`` and
            # drop the env: the remaining 1.6 GB is Python/tk/cairo the CLI never
            # loads. Verified with ``mutool -v``, ``info`` and ``clean -gggg``.
            "{tools}\\mutool\\mutool.exe",
        ),
        executables=("mutool.exe",),
        note="PDF 解析/转换（conda-forge mupdf 包，经 TUNA 镜像）",
    ),
    Artifact(
        key="ghostscript",
        version="10.08.0",
        urls=(),
        archive="existing",
        executables=("gswin64c.exe", "gs.exe"),
        source_paths=(r"C:\Program Files\gs\gs10.08.0\bin\gswin64c.exe",),
        note="已随系统安装，仅缺 PATH 接线（PDF/EPS 压缩与转换）",
    ),
)

BY_KEY = {artifact.key: artifact for artifact in ARTIFACTS}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_paths(artifact: Artifact, tools_root: Path) -> tuple[Path, ...]:
    """Expand ``{tools}`` and glob wildcards in ``source_paths``.

    Machine-wide installs embed their version in the directory name
    (``C:\\Program Files\\qpdf 12.4.2\\bin``), so a literal path would break on
    the next upgrade; a ``*`` keeps the pointer valid across versions.
    """
    expanded: list[Path] = []
    for item in artifact.source_paths:
        pattern = item.replace("{tools}", str(tools_root))
        if any(char in pattern for char in "*?["):
            expanded.extend(Path(match) for match in sorted(glob_module.glob(pattern)))
        else:
            expanded.append(Path(pattern))
    return tuple(expanded)


def _external_executable(
    executables: tuple[str, ...],
    shim_dir: Path,
) -> str | None:
    """Return an executable found on PATH *outside* our own shim directory.

    A machine-wide install (winget, Program Files) is strictly better than a
    portable copy: it gets updates and is on PATH before the shim directory.
    Counting our own shim as "already installed" would make the installer
    non-idempotent, so shim paths are filtered out here.
    """
    shim_root = os.path.normcase(str(shim_dir.resolve()))
    for name in executables:
        found = shutil.which(name)
        if not found:
            continue
        if os.path.normcase(str(Path(found).resolve())).startswith(shim_root):
            continue
        return found
    return None


def _drop_shims(artifact: Artifact, shim_dir: Path) -> list[str]:
    """Remove this artifact's shims, e.g. after a machine-wide install lands."""
    removed: list[str] = []
    for name in artifact.executables:
        shim = shim_dir / f"{Path(name).stem}.cmd"
        if shim.is_file():
            shim.unlink()
            removed.append(str(shim))
    return removed


def _download_one(
    url: str,
    target: Path,
    *,
    timeout: float = 30.0,
    retries: int = 3,
    user_agent: str | None = "codex-toolchain-fetch/1.0",
) -> None:
    """Stream *url* to *target*, resuming if the mirror supports ranges."""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        start = target.stat().st_size if target.exists() else 0
        headers = {"User-Agent": user_agent} if user_agent else {}
        if start:
            headers["Range"] = f"bytes={start}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if start and response.status == 200:
                    start = 0
                mode = "ab" if start else "wb"
                with target.open(mode) as handle:
                    while True:
                        chunk = response.read(1 << 18)
                        if not chunk:
                            break
                        handle.write(chunk)
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"下载失败 {url}: {last_error}")


def _download(
    artifact: Artifact,
    cache: Path,
    *,
    dry_run: bool = False,
    reuse_cache: bool = False,
) -> tuple[str, Path, str]:
    suffix = Path(artifact.urls[0]).name
    target = cache / f"{artifact.key}-{artifact.version}-{suffix}"
    errors: list[str] = []
    if reuse_cache and not dry_run and target.is_file() and target.stat().st_size:
        return "cache", target, _sha256(target)
    for url in artifact.urls:
        if dry_run:
            return url, target, "dry-run"
        try:
            _download_one(url, target, user_agent=artifact.user_agent)
        except RuntimeError as exc:
            target.unlink(missing_ok=True)
            errors.append(str(exc))
            continue
        if artifact.sha256 and _sha256(target) != artifact.sha256:
            target.unlink(missing_ok=True)
            errors.append(f"sha256 不匹配: {url}")
            continue
        return url, target, _sha256(target)
    raise RuntimeError("；".join(errors) or f"{artifact.key} 无可用镜像")


def _extract(
    artifact: Artifact,
    archive_path: Path,
    destination: Path,
) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if artifact.archive in {"zip", "auto"}:
        with zipfile.ZipFile(archive_path) as bundle:
            bundle.extractall(destination)
        return
    if artifact.archive == "tar.bz2":
        with tarfile.open(archive_path, "r:bz2") as bundle:
            bundle.extractall(destination)
        return
    if artifact.archive == "msi-admin":
        # Preference order matters. msiexec /a fails on hosts whose Windows
        # Installer service cannot cost the volume (seen as 1603 with
        # ``OutOfDiskSpace = 1``), 7z flattens the MSI directory table so the
        # result cannot bootstrap, and only lessmsi reproduces the layout.
        if _extract_msi_admin(archive_path, destination):
            return
        if _extract_with_lessmsi(archive_path, destination):
            return
        if _extract_with_7z(archive_path, destination):
            return
        raise RuntimeError("MSI 解包失败：msiexec /a、lessmsi 与 7z 均不可用或均失败")
    raise ValueError(f"未知归档类型: {artifact.archive}")


def _extract_msi_admin(archive_path: Path, destination: Path) -> bool:
    """Unpack an MSI without registering it, using ``msiexec /a``."""
    completed = subprocess.run(
        [
            "msiexec",
            "/a",
            str(archive_path),
            "/qn",
            f"TARGETDIR={destination}",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode == 0


def _find_7z() -> str | None:
    found = shutil.which("7z") or shutil.which("7za")
    if found:
        return found
    for candidate in (
        Path(os.environ.get("ProgramFiles", "")) / "7-Zip" / "7z.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "7-Zip" / "7z.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def build_mutool_from_conda(dest: Path, *, channel: str | None = None) -> dict:
    """Materialise ``mutool`` from conda-forge without keeping the full env.

    The conda-forge ``mupdf`` package pulls Python, tk, cairo and font stacks to
    the tune of ~1.6 GB, none of which ``mutool.exe`` loads. Only
    ``Library\\bin`` (the executable plus its DLLs, ~222 MB) is kept.
    """
    micromamba = _find_executable("micromamba", dest)
    if not micromamba:
        raise RuntimeError("未找到 micromamba；先运行 scripts/install-toolchain.ps1")
    channel = channel or ("https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge::mupdf")
    env_dir = dest / "mupdf-env"
    final = dest / "mutool"
    environment = dict(os.environ)
    environment["MAMBA_ROOT_PREFIX"] = str(dest / "mamba-root")
    create = subprocess.run(
        [micromamba, "create", "-y", "-p", str(env_dir), channel],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    if create.returncode != 0:
        raise RuntimeError(
            f"micromamba create 失败 (rc={create.returncode}): "
            f"{(create.stderr or create.stdout or '')[-400:]}"
        )
    source = env_dir / "Library" / "bin"
    if not source.is_dir():
        raise RuntimeError(f"conda 环境缺少 {source}")
    if final.exists():
        shutil.rmtree(final)
    final.mkdir(parents=True)
    for item in source.iterdir():
        shutil.move(str(item), final / item.name)
    shutil.rmtree(env_dir, ignore_errors=True)
    # Reclaim the package cache the env was materialised from.
    subprocess.run(
        [micromamba, "clean", "--all", "-y"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    keep = final / "mutool.exe"
    return {
        "key": "mutool",
        "path": str(keep),
        "exists": keep.is_file(),
        "bytes": keep.stat().st_size if keep.is_file() else 0,
    }


def _find_executable(name: str, dest: Path) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for candidate in (
        dest / "bin" / f"{name}.cmd",
        dest / "bin" / f"{name}.exe",
        dest / "micromamba" / "Library" / "bin" / f"{name}.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _extract_with_7z(archive_path: Path, destination: Path) -> bool:
    """Fallback for MSI packages the Windows Installer service refuses.

    ``msiexec /a`` returns 1619 for some Microsoft-hosted MSIs even when the
    file is byte-complete (verified with ``7z t``). 7-Zip reads the embedded
    cabinet directly and needs no service, so it is the reliable path.
    """
    seven = _find_7z()
    if not seven:
        return False
    completed = subprocess.run(
        [seven, "x", str(archive_path), f"-o{destination}", "-y"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode == 0


def _extract_with_lessmsi(archive_path: Path, destination: Path) -> bool:
    """Extract an MSI preserving the installer's directory table.

    lessmsi writes into ``<destination>/SourceDir`` (or a folder named after the
    MSI, depending on the package), so the caller-visible tree is normalised to
    *destination* afterwards.
    """
    lessmsi = shutil.which("lessmsi")
    if not lessmsi:
        for candidate in Path(os.environ.get("LOCALAPPDATA", "")).glob(
            "Microsoft/WinGet/Packages/activescott.lessmsi*/lessmsi.exe"
        ):
            lessmsi = str(candidate)
            break
    if not lessmsi:
        return False
    staging = destination.parent / f"{destination.name}-lessmsi-staging"
    if staging.exists():
        shutil.rmtree(staging)
    completed = subprocess.run(
        [lessmsi, "x", str(archive_path), str(staging)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return False
    nested = staging / "SourceDir"
    inner = nested if nested.is_dir() else staging
    for child in inner.iterdir():
        shutil.move(str(child), destination / child.name)
    shutil.rmtree(staging, ignore_errors=True)
    return True


def _shim(
    artifact: Artifact,
    destination: Path,
    shim_dir: Path,
    *,
    explicit: tuple[Path, ...] = (),
) -> list[str]:
    root = destination / artifact.bin_dir if artifact.bin_dir else destination
    written: list[str] = []
    shim_dir.mkdir(parents=True, exist_ok=True)
    for name in artifact.executables:
        candidates = [path for path in explicit if path.name == name and path.is_file()]
        # Archives sometimes nest one extra directory level.
        if not candidates:
            candidates = list(root.rglob(name)) if root.is_dir() else []
        if not candidates and destination.is_dir():
            candidates = list(destination.rglob(name))
        if not candidates:
            continue
        real = candidates[0]
        stem = Path(name).stem
        # A batch shim must carry .cmd/.bat: Windows refuses to CreateProcess a
        # non-PE file that claims a .exe extension.
        shim = shim_dir / f"{stem}.cmd"
        shim.write_text(
            f'@echo off\r\n"{real}" %*\r\n',
            encoding="utf-8",
        )
        # Clean up the pre-fix .exe-named batch shim if one is present.
        stale = shim_dir / f"{stem}.exe"
        if stale.is_file():
            stale.unlink()
        written.append(str(real))
    return written


def install(
    artifacts: tuple[Artifact, ...],
    *,
    dest: Path,
    cache: Path,
    dry_run: bool = False,
    jobs: int = 4,
    shims_only: bool = False,
    reuse_cache: bool = False,
    force: bool = False,
) -> list[dict]:
    dest.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    shim_dir = dest / "bin"
    records: list[dict] = []
    pending_artifacts = []
    for artifact in artifacts:
        if not force:
            external = _external_executable(artifact.executables, shim_dir)
            if external:
                dropped = [] if dry_run else _drop_shims(artifact, shim_dir)
                records.append(
                    {
                        "key": artifact.key,
                        "version": artifact.version,
                        "note": artifact.note,
                        "archive": artifact.archive,
                        "source": external,
                        "status": "already-present",
                        "shims": [],
                        "dropped_shims": dropped,
                        "error": "",
                    }
                )
                print(
                    f"[already-present] {artifact.key} <- {external}".rstrip(),
                    file=sys.stderr,
                )
                continue
        if not force and artifact.archive == "auto":
            preferred = tuple(path for path in _source_paths(artifact, dest) if path.is_file())
            if preferred:
                shims = (
                    []
                    if dry_run
                    else _shim(
                        artifact,
                        dest / artifact.key,
                        shim_dir,
                        explicit=preferred,
                    )
                )
                records.append(
                    {
                        "key": artifact.key,
                        "version": artifact.version,
                        "note": artifact.note,
                        "archive": artifact.archive,
                        "source": str(preferred[0]),
                        "status": "installed" if shims else "failed",
                        "shims": shims,
                        "error": "" if shims else "找到系统安装但无法建立 shim",
                    }
                )
                print(
                    f"[prefers-system] {artifact.key} <- {preferred[0]}".rstrip(),
                    file=sys.stderr,
                )
                continue
            pending_artifacts.append(artifact)
            continue
        if shims_only:
            target_dir = dest / artifact.key
            found = _source_paths(artifact, dest)
            if artifact.archive == "existing":
                real = tuple(path for path in found if path.is_file())
                shims = (
                    []
                    if dry_run or not real
                    else _shim(artifact, target_dir, shim_dir, explicit=real)
                )
                records.append(
                    {
                        "key": artifact.key,
                        "version": artifact.version,
                        "note": artifact.note,
                        "archive": artifact.archive,
                        "source": "already-installed",
                        "status": "installed" if shims else "failed",
                        "shims": shims,
                        "error": "" if shims else "未找到已安装的可执行文件",
                    }
                )
                print(
                    f"[{records[-1]['status']:>10}] {artifact.key} "
                    f"{artifact.version} (shims-only)".rstrip(),
                    file=sys.stderr,
                )
                continue
            shims = (
                []
                if dry_run or not target_dir.is_dir()
                else _shim(artifact, target_dir, shim_dir, explicit=found)
            )
            records.append(
                {
                    "key": artifact.key,
                    "version": artifact.version,
                    "note": artifact.note,
                    "archive": artifact.archive,
                    "source": "shims-only",
                    "status": "installed" if shims else "failed",
                    "shims": shims,
                    "error": "" if shims else "未找到已解包目录",
                }
            )
            print(
                f"[{records[-1]['status']:>10}] {artifact.key} "
                f"{artifact.version} (shims-only)".rstrip(),
                file=sys.stderr,
            )
            continue
        if artifact.archive != "existing":
            pending_artifacts.append(artifact)
            continue
        record = {
            "key": artifact.key,
            "version": artifact.version,
            "note": artifact.note,
            "archive": artifact.archive,
            "source": "already-installed",
            "status": "extracted",
        }
        found = _source_paths(artifact, dest)
        if not any(path.is_file() for path in found):
            record.update({"status": "failed", "error": "未找到已安装的可执行文件"})
        elif not dry_run:
            shims = _shim(artifact, dest / artifact.key, shim_dir, explicit=found)
            record["shims"] = shims
            record["status"] = "installed" if shims else "failed"
        records.append(record)
        print(
            f"[{record['status']:>10}] {artifact.key} {artifact.version} "
            f"{record.get('error', '')}".rstrip(),
            file=sys.stderr,
        )
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        pending = {
            pool.submit(
                _download,
                artifact,
                cache,
                dry_run=dry_run,
                reuse_cache=reuse_cache,
            ): artifact
            for artifact in pending_artifacts
        }
        for future in as_completed(pending):
            artifact = pending[future]
            record = {
                "key": artifact.key,
                "version": artifact.version,
                "note": artifact.note,
                "archive": artifact.archive,
                "status": "pending",
            }
            try:
                url, archive_path, digest = future.result()
                record.update({"source": url, "sha256": digest, "status": "downloaded"})
                if not dry_run:
                    target_dir = dest / artifact.key
                    _extract(artifact, archive_path, target_dir)
                    shims = _shim(artifact, target_dir, shim_dir)
                    record["shims"] = shims
                    record["status"] = "installed" if shims else "extracted"
            except Exception as exc:  # a single mirror failure must not abort
                record.update({"status": "failed", "error": str(exc)[:400]})
            records.append(record)
            print(
                f"[{record['status']:>10}] {artifact.key} "
                f"{artifact.version} {record.get('error', '')}".rstrip(),
                file=sys.stderr,
            )
    records.sort(key=lambda item: item["key"])
    manifest = dest / "toolchain-manifest.json"
    if not dry_run:
        # Also drop a relocation pointer so pre-existing processes (the desktop
        # app, long-lived shells) can still find the tools when the root moved.
        # Written directly rather than via ccfa.toolchain so the installer keeps
        # working when PYTHONPATH is not set.
        base = os.environ.get("LOCALAPPDATA")
        if base:
            try:
                (Path(base) / "codex-tools-location").write_text(str(dest) + "\n", encoding="utf-8")
            except OSError:
                pass
        merged: dict[str, dict] = {}
        if manifest.is_file():
            try:
                previous = json.loads(manifest.read_text(encoding="utf-8"))
                for item in previous.get("artifacts", []):
                    if isinstance(item, dict) and item.get("key"):
                        merged[item["key"]] = item
            except (OSError, json.JSONDecodeError):
                merged = {}
        for item in records:
            merged[item["key"]] = item
        manifest.write_text(
            json.dumps(
                {
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "dest": str(dest),
                    "artifacts": sorted(merged.values(), key=lambda i: i["key"]),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="通过可达镜像下载并解包便携版科研工具链")
    parser.add_argument(
        "--dest",
        default=str(default_dest()),
        help="安装根目录（默认 %%LOCALAPPDATA%%\\codex-tools）",
    )
    parser.add_argument("--cache", default=None, help="下载缓存目录")
    parser.add_argument(
        "--only",
        default=None,
        help="逗号分隔的 key 子集，默认全部",
    )
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--shims-only",
        action="store_true",
        help="跳过下载与解包，只按已解包目录重建 PATH shim（修复用）",
    )
    parser.add_argument(
        "--reuse-cache",
        action="store_true",
        help="缓存里已有非空归档时直接复用，不重新下载（解包失败后重试用）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略 PATH 上已有的等价工具，强制安装便携版",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="只列出可用构件与镜像，不下载",
    )
    parser.add_argument(
        "--build-mutool",
        action="store_true",
        help="经 conda-forge 构建 mutool，只保留运行时（约 222 MB 而非 1.9 GB）",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    if args.build_mutool:
        try:
            result = build_mutool_from_conda(Path(args.dest).expanduser())
        except (OSError, RuntimeError) as exc:
            print(f"FAILED mutool: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["exists"] else 1
    if args.list:
        for artifact in ARTIFACTS:
            print(f"{artifact.key:<12} {artifact.version:<10} {artifact.note}")
            for url in artifact.urls:
                print(f"    {url}")
        return 0
    selected = ARTIFACTS
    if args.only:
        keys = {item.strip() for item in args.only.split(",") if item.strip()}
        unknown = keys - BY_KEY.keys()
        if unknown:
            print(f"未知构件: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        selected = tuple(item for item in ARTIFACTS if item.key in keys)
    dest = Path(args.dest).expanduser()
    cache = Path(args.cache).expanduser() if args.cache else dest / ".cache"
    records = install(
        selected,
        dest=dest,
        cache=cache,
        dry_run=args.dry_run,
        jobs=args.jobs,
        shims_only=args.shims_only,
        reuse_cache=args.reuse_cache,
        force=args.force,
    )
    failed = [item for item in records if item["status"] == "failed"]
    if failed:
        for item in failed:
            print(
                f"FAILED {item['key']}: {item.get('error')}",
                file=sys.stderr,
            )
        return 1
    print(f"toolchain: {len(records)} 个构件在 {dest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
