"""Immutable content-addressed artifact store and portable .science package."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ccfa.cli import Problem, emit, save_text_atomically, tool_error


STORE = Path("ccfa-workfiles") / "artifact-store"
MANIFEST = STORE / "manifest.json"
BLOBS = STORE / "blobs"
RECEIPT = "verify-receipt.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest(paper_root: Path) -> dict:
    path = paper_root / MANIFEST
    if not path.is_file():
        return {"version": 1, "artifacts": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 artifact manifest: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("artifact manifest 顶层必须是对象")
    if payload.get("version") != 1:
        raise ValueError("artifact manifest version 必须是 1")
    if not isinstance(payload.get("artifacts"), dict):
        raise ValueError("artifact manifest artifacts 必须是映射")
    return payload


def _save_manifest(paper_root: Path, payload: dict) -> None:
    save_text_atomically(
        paper_root / MANIFEST,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="artifact manifest",
    )


def _resolve_source(paper_root: Path, relative: str) -> Path:
    source = (paper_root / relative).resolve()
    try:
        source.relative_to(paper_root.resolve())
    except ValueError as exc:
        raise ValueError(f"artifact 必须位于 paper root 内: {relative}") from exc
    if not source.is_file():
        raise ValueError(f"artifact 不存在: {relative}")
    return source


def put_artifact(
    paper_root: Path,
    relative: str,
    *,
    role: str | None = None,
    run_id: str | None = None,
) -> dict:
    paper_root = Path(paper_root).resolve()
    source = _resolve_source(paper_root, relative)
    digest = _sha256_file(source)
    manifest = _load_manifest(paper_root)
    artifact_id = Path(relative).as_posix()
    versions = manifest["artifacts"].setdefault(artifact_id, [])
    if not isinstance(versions, list):
        raise ValueError(f"artifact manifest 条目非法: {artifact_id}")
    if versions and versions[-1].get("sha256") == digest:
        return {
            "artifact_id": artifact_id,
            "version": versions[-1].get("version"),
            "sha256": digest,
            "created": False,
        }
    blob = paper_root / BLOBS / digest
    blob.parent.mkdir(parents=True, exist_ok=True)
    if blob.exists():
        if _sha256_file(blob) != digest:
            raise ValueError(f"已有 blob 内容损坏: {blob}")
    else:
        blob.write_bytes(source.read_bytes())
    version = len(versions) + 1
    entry = {
        "artifact_id": artifact_id,
        "version": version,
        "sha256": digest,
        "role": role or "artifact",
        "run_id": run_id,
        "source_path": artifact_id,
        "created_at": _now_iso(),
    }
    versions.append(entry)
    _save_manifest(paper_root, manifest)
    return {**entry, "created": True}


def _manifest_entry(paper_root: Path, artifact_id: str) -> list[dict]:
    manifest = _load_manifest(paper_root)
    versions = manifest["artifacts"].get(artifact_id)
    if not isinstance(versions, list) or not versions:
        raise ValueError(f"artifact 不在 store 中: {artifact_id}")
    return versions


def replay_artifact(paper_root: Path, artifact_id: str) -> dict:
    paper_root = Path(paper_root).resolve()
    return {
        "artifact_id": artifact_id,
        "versions": _manifest_entry(paper_root, artifact_id),
    }


def verify_store(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    manifest_path = paper_root / MANIFEST
    if not manifest_path.is_file():
        return [], [
            Problem(
                "artifact-store-not-configured",
                str(manifest_path),
                None,
                "artifact store 尚未建立",
            )
        ]
    try:
        manifest = _load_manifest(paper_root)
    except ValueError as exc:
        return [
            Problem(
                "artifact-store-invalid",
                str(manifest_path),
                None,
                str(exc),
            )
        ], []
    problems: list[Problem] = []
    for artifact_id, versions in manifest["artifacts"].items():
        if not isinstance(versions, list):
            problems.append(
                Problem(
                    "artifact-store-invalid",
                    str(manifest_path),
                    None,
                    f"{artifact_id}: versions 必须是数组",
                )
            )
            continue
        expected_version = 1
        for entry in versions:
            if not isinstance(entry, dict):
                problems.append(
                    Problem(
                        "artifact-store-invalid",
                        str(manifest_path),
                        None,
                        f"{artifact_id}: version entry 必须是对象",
                    )
                )
                continue
            if entry.get("version") != expected_version:
                problems.append(
                    Problem(
                        "artifact-store-sequence",
                        str(manifest_path),
                        None,
                        f"{artifact_id}: version 应为 {expected_version}，"
                        f"实际 {entry.get('version')!r}",
                    )
                )
            expected_version += 1
            digest = entry.get("sha256")
            blob = paper_root / BLOBS / str(digest)
            if not blob.is_file():
                problems.append(
                    Problem(
                        "artifact-store-integrity",
                        str(blob),
                        None,
                        f"{artifact_id} v{entry.get('version')}: blob 缺失",
                    )
                )
            elif _sha256_file(blob) != digest:
                problems.append(
                    Problem(
                        "artifact-store-integrity",
                        str(blob),
                        None,
                        f"{artifact_id} v{entry.get('version')}: blob hash 不匹配",
                    )
                )
    return problems, []


def package_science(paper_root: Path, out_path: Path) -> dict:
    paper_root = Path(paper_root).resolve()
    problems, _advisories = verify_store(paper_root)
    if problems:
        raise ValueError(f"artifact store 不完整: {problems[0].message}")
    manifest_path = paper_root / MANIFEST
    manifest = _load_manifest(paper_root)
    out = Path(out_path)
    if not out.is_absolute():
        out = paper_root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "version": 1,
        "manifest_sha256": _sha256_file(manifest_path),
        "artifact_count": len(manifest["artifacts"]),
        "packaged_at": _now_iso(),
    }
    file_count = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        )
        file_count += 1
        archive.writestr(
            "README.md",
            "# Portable Research Artifact\n\n"
            "This package contains immutable artifact versions, their manifest, "
            "and a verification receipt. It is read-only evidence for handoff "
            "and review, not a replay guarantee.\n",
        )
        file_count += 1
        archive.writestr(
            RECEIPT,
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True),
        )
        file_count += 1
        for artifact_id, versions in manifest["artifacts"].items():
            if not isinstance(versions, list):
                continue
            for entry in versions:
                if not isinstance(entry, dict):
                    continue
                digest = entry.get("sha256")
                blob = paper_root / BLOBS / str(digest)
                if blob.is_file():
                    archive.write(blob, f"blobs/{digest}")
                    file_count += 1
        for extra, arcname in (
            (paper_root / "experiments" / "log" / "run-ledger.jsonl", "run-ledger.jsonl"),
            (paper_root / "data" / "provenance.json", "data/provenance.json"),
            (
                paper_root / "data" / "artifact-provenance.yaml",
                "data/artifact-provenance.yaml",
            ),
        ):
            if extra.is_file():
                archive.write(extra, arcname)
                file_count += 1
    return {"out": str(out), "file_count": file_count, **receipt}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="immutable artifact store")
    sub = parser.add_subparsers(dest="command", required=True)
    put = sub.add_parser("put")
    put.add_argument("--paper-root", required=True)
    put.add_argument("--path", required=True)
    put.add_argument("--role")
    put.add_argument("--run-id")
    for name in ("list", "verify"):
        item = sub.add_parser(name)
        item.add_argument("--paper-root", required=True)
    package = sub.add_parser("package")
    package.add_argument("--paper-root", required=True)
    package.add_argument("--out", required=True)
    replay = sub.add_parser("replay")
    replay.add_argument("--paper-root", required=True)
    replay.add_argument("--artifact", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "put":
            result = put_artifact(
                Path(args.paper_root),
                args.path,
                role=args.role,
                run_id=args.run_id,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "list":
            manifest = _load_manifest(Path(args.paper_root))
            print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.command == "verify":
            problems, advisories = verify_store(Path(args.paper_root))
            return emit(problems, advisories)
        if args.command == "package":
            result = package_science(Path(args.paper_root), Path(args.out))
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        result = replay_artifact(Path(args.paper_root), args.artifact)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
