"""Pack a directory of agent skills into a verifiable archive.

Reference: Modex-MH-Agent ships 283 AES-256-GCM ``SKILL.md.enc`` files whose
data key is issued by a license server and bound to a machine fingerprint. That
hides the prompts, but it makes the archive opaque in the other direction too:
nothing in the bytes lets a recipient check that what arrived is what the
author packed, and nothing works offline.

This keeps the half worth copying and drops the half that only creates lock-in:

- every member carries a SHA-256 digest in ``skillpack.json`` and ``verify``
  rehashes it, so tampering is detectable without the author being online;
- encryption is optional and explicit: standard AES-256-GCM with a
  PBKDF2-HMAC-SHA256 key from a passphrase, parameters recorded in the
  manifest. No disguised framing and no server handshake, because both make a
  pack unauditable and unusable offline;
- ``unpack`` refuses to overwrite an existing file unless asked.

Encryption here is copy protection against casual sharing, not a security
boundary: anyone who can run the pack can read the key from memory. Packs meant
to be inspected should stay plaintext, which is why that is the default.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from ccfa.cli import Problem, emit, tool_error

FORMAT = "ccfa-skillpack"
FORMAT_VERSION = 1
MANIFEST_NAME = "skillpack.json"
PAYLOAD_PREFIX = "payload/"
PBKDF2_ITERATIONS = 600_000
KEY_CHECK_PLAINTEXT = b"ccfa-skillpack-key-check"
_FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)


class SkillpackError(ValueError):
    """Raised when a pack cannot be built or read."""


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _require_crypto():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - depends on the host
        raise SkillpackError(
            "加密打包需要 cryptography："
            "& tools/.venv/Scripts/python.exe -m pip install cryptography"
        ) from exc
    return AESGCM


def _read_passphrase(args) -> bytes | None:
    if args.passphrase_env:
        value = os.environ.get(args.passphrase_env)
        if not value:
            raise SkillpackError(f"环境变量 {args.passphrase_env} 为空")
        return value.encode("utf-8")
    if args.passphrase_file:
        path = Path(args.passphrase_file)
        try:
            return path.read_bytes().strip()
        except OSError as exc:
            raise SkillpackError(f"无法读取口令文件 {path}: {exc}") from exc
    return None


def _derive_key(passphrase: bytes, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passphrase, salt, iterations, dklen=32)


def _collect(source: Path) -> list[Path]:
    if not source.is_dir():
        raise SkillpackError(f"源目录不存在或不是目录: {source}")
    members: list[Path] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise SkillpackError(f"不接受符号链接: {path}")
        if path.is_file():
            members.append(path)
        elif not path.is_dir():
            raise SkillpackError(f"不支持的文件类型: {path}")
    if not members:
        raise SkillpackError(f"源目录里没有文件: {source}")
    return members


def build_pack(
    source: Path,
    out: Path,
    *,
    pack_id: str,
    version: str,
    roles: list[str],
    created_at: str | None = None,
    passphrase: bytes | None = None,
    overwrite: bool = False,
) -> dict:
    source = Path(source)
    out = Path(out)
    if out.exists() and not overwrite:
        raise SkillpackError(f"目标已存在（加 --force 覆盖）: {out}")
    members = _collect(source)

    encryption = None
    key = None
    if passphrase is not None:
        AESGCM = _require_crypto()
        salt = secrets.token_bytes(16)
        key = _derive_key(passphrase, salt, PBKDF2_ITERATIONS)
        check_nonce = secrets.token_bytes(12)
        encryption = {
            "algorithm": "AES-256-GCM",
            "kdf": "PBKDF2-HMAC-SHA256",
            "iterations": PBKDF2_ITERATIONS,
            "salt": base64.b64encode(salt).decode("ascii"),
            "key_check_nonce": base64.b64encode(check_nonce).decode("ascii"),
            "key_check": base64.b64encode(
                AESGCM(key).encrypt(check_nonce, KEY_CHECK_PLAINTEXT, None)
            ).decode("ascii"),
        }

    manifest = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "pack_id": pack_id,
        "version": version,
        "created_at": created_at
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "roles": sorted(set(roles)),
        "encryption": encryption,
        "files": [],
    }

    entries: list[tuple[str, bytes]] = []
    for path in members:
        relative = path.relative_to(source).as_posix()
        data = path.read_bytes()
        stored = f"{PAYLOAD_PREFIX}{relative}"
        entry = {
            "path": relative,
            "size": len(data),
            "sha256": _sha256(data),
            "stored": stored,
            "stored_sha256": "",
            "nonce": None,
        }
        if key is not None:
            AESGCM = _require_crypto()
            nonce = secrets.token_bytes(12)
            blob = AESGCM(key).encrypt(nonce, data, None)
            entry["nonce"] = base64.b64encode(nonce).decode("ascii")
            stored = f"{stored}.enc"
            entry["stored"] = stored
            payload = blob
        else:
            payload = data
        entry["stored_sha256"] = _sha256(payload)
        manifest["files"].append(entry)
        entries.append((stored, payload))

    manifest["file_count"] = len(manifest["files"])
    manifest["total_size"] = sum(item["size"] for item in manifest["files"])
    manifest["manifest_sha256"] = ""
    manifest["manifest_sha256"] = _sha256(
        json.dumps(
            {**manifest, "manifest_sha256": ""},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
    )
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(out.name + ".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        _write_member(archive, MANIFEST_NAME, manifest_bytes)
        for name, payload in entries:
            _write_member(archive, name, payload)
    os.replace(temporary, out)
    return manifest


def _write_member(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, payload)


def load_pack(path: Path) -> tuple[zipfile.ZipFile, dict]:
    path = Path(path)
    if not path.is_file():
        raise SkillpackError(f"skillpack 不存在: {path}")
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SkillpackError(f"无法读取 skillpack {path}: {exc}") from exc
    try:
        raw = archive.read(MANIFEST_NAME)
    except KeyError as exc:
        archive.close()
        raise SkillpackError(f"skillpack 缺少 {MANIFEST_NAME}") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        archive.close()
        raise SkillpackError(f"{MANIFEST_NAME} 不是合法 JSON: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        archive.close()
        raise SkillpackError(f"{MANIFEST_NAME} 不是 {FORMAT} 清单")
    if manifest.get("format_version") != FORMAT_VERSION:
        archive.close()
        raise SkillpackError(
            f"不支持的 format_version: {manifest.get('format_version')!r}"
        )
    return archive, manifest


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SkillpackError(f"非法的成员路径: {value!r}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"..", ""} for part in pure.parts):
        raise SkillpackError(f"成员路径越界: {value!r}")
    return pure.as_posix()


def _unlock(manifest: dict, passphrase: bytes | None):
    encryption = manifest.get("encryption")
    if not encryption:
        return None, []
    if passphrase is None:
        return None, [
            Problem(
                "skillpack-locked",
                MANIFEST_NAME,
                None,
                "该 pack 已加密，需要 --passphrase-env 或 --passphrase-file",
            )
        ]
    AESGCM = _require_crypto()
    try:
        salt = base64.b64decode(encryption["salt"])
        nonce = base64.b64decode(encryption["key_check_nonce"])
        check = base64.b64decode(encryption["key_check"])
        iterations = int(encryption["iterations"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SkillpackError(f"加密参数非法: {exc}") from exc
    key = _derive_key(passphrase, salt, iterations)
    try:
        AESGCM(key).decrypt(nonce, check, None)
    except Exception:  # noqa: BLE001 - any failure means the passphrase is wrong
        return None, [
            Problem("skillpack-bad-passphrase", MANIFEST_NAME, None, "口令不正确")
        ]
    return key, []


def verify_pack(path: Path, passphrase: bytes | None = None) -> list[Problem]:
    archive, manifest = load_pack(path)
    problems: list[Problem] = []
    with archive:
        key, lock_problems = _unlock(manifest, passphrase)
        problems.extend(lock_problems)
        stored_manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        expected = stored_manifest.get("manifest_sha256")
        probe = {**stored_manifest, "manifest_sha256": ""}
        actual = _sha256(
            json.dumps(probe, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        )
        if expected and expected != actual:
            problems.append(
                Problem(
                    "skillpack-manifest-tampered",
                    MANIFEST_NAME,
                    None,
                    "清单自身的哈希与内容不符",
                )
            )
        listed = set()
        for item in manifest.get("files", []):
            if not isinstance(item, dict):
                problems.append(
                    Problem("skillpack-bad-entry", MANIFEST_NAME, None, "files 条目必须是映射")
                )
                continue
            try:
                _safe_relative(item.get("path"))
                stored = _safe_relative(item.get("stored"))
            except SkillpackError as exc:
                problems.append(Problem("skillpack-bad-entry", str(path), None, str(exc)))
                continue
            listed.add(stored)
            try:
                payload = archive.read(stored)
            except KeyError:
                problems.append(
                    Problem("skillpack-missing-member", stored, None, "清单声明了成员但包里没有")
                )
                continue
            if item.get("stored_sha256") != _sha256(payload):
                problems.append(
                    Problem("skillpack-member-tampered", stored, None, "成员字节与清单不符")
                )
                continue
            if key is None:
                continue
            if not item.get("nonce"):
                problems.append(
                    Problem("skillpack-bad-entry", stored, None, "加密包缺少 nonce")
                )
                continue
            AESGCM = _require_crypto()
            try:
                plain = AESGCM(key).decrypt(
                    base64.b64decode(item["nonce"]), payload, None
                )
            except Exception:  # noqa: BLE001 - GCM failure means broken or forged bytes
                problems.append(
                    Problem("skillpack-decrypt-failed", stored, None, "解密失败或认证标签不符")
                )
                continue
            if _sha256(plain) != item.get("sha256"):
                problems.append(
                    Problem("skillpack-plaintext-mismatch", stored, None, "解密后的内容与清单不符")
                )
            elif len(plain) != item.get("size"):
                problems.append(
                    Problem("skillpack-size-mismatch", stored, None, "解密后的长度与清单不符")
                )
        for name in archive.namelist():
            if name == MANIFEST_NAME or name in listed:
                continue
            problems.append(
                Problem("skillpack-unlisted-member", name, None, "包里有清单未声明的成员")
            )
    return problems


def unpack_pack(
    path: Path,
    dest: Path,
    passphrase: bytes | None = None,
    *,
    overwrite: bool = False,
) -> None:
    archive, manifest = load_pack(path)
    dest = Path(dest)
    with archive:
        key, lock_problems = _unlock(manifest, passphrase)
        if lock_problems:
            raise SkillpackError(lock_problems[0].message)
        planned: list[tuple[Path, bytes]] = []
        for item in manifest.get("files", []):
            relative = _safe_relative(item.get("path"))
            stored = _safe_relative(item.get("stored"))
            target = dest / relative
            if target.exists() and not overwrite:
                raise SkillpackError(f"目标已存在（加 --force 覆盖）: {target}")
            payload = archive.read(stored)
            if item.get("stored_sha256") != _sha256(payload):
                raise SkillpackError(f"成员字节与清单不符: {stored}")
            if key is None:
                plain = payload
            else:
                AESGCM = _require_crypto()
                plain = AESGCM(key).decrypt(
                    base64.b64decode(item["nonce"]), payload, None
                )
            if _sha256(plain) != item.get("sha256"):
                raise SkillpackError(f"解密后的内容与清单不符: {relative}")
            planned.append((target, plain))
        for target, plain in planned:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(plain)


def describe(path: Path) -> dict:
    archive, manifest = load_pack(path)
    with archive:
        encryption = manifest.get("encryption")
        return {
            "pack": str(path),
            "pack_id": manifest.get("pack_id"),
            "version": manifest.get("version"),
            "created_at": manifest.get("created_at"),
            "roles": manifest.get("roles", []),
            "file_count": manifest.get("file_count"),
            "total_size": manifest.get("total_size"),
            "encrypted": bool(encryption),
            "encryption": encryption or None,
            "files": [item.get("path") for item in manifest.get("files", [])],
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="打包/校验可验证的科研技能包")
    sub = parser.add_subparsers(dest="command", required=True)

    pack = sub.add_parser("pack", help="把技能目录打成 .skillpack")
    pack.add_argument("--source", required=True)
    pack.add_argument("--out", required=True)
    pack.add_argument("--pack-id", required=True)
    pack.add_argument("--version", required=True)
    pack.add_argument("--role", action="append", default=[], dest="roles")
    pack.add_argument("--created-at")
    pack.add_argument("--encrypt", action="store_true")
    pack.add_argument("--passphrase-env")
    pack.add_argument("--passphrase-file")
    pack.add_argument("--force", action="store_true")

    for name, help_text in (
        ("verify", "校验 pack 的清单与成员字节"),
        ("list", "列出 pack 的清单摘要"),
        ("unpack", "解开 pack 到目录"),
    ):
        item = sub.add_parser(name, help=help_text)
        item.add_argument("pack")
        item.add_argument("--passphrase-env")
        item.add_argument("--passphrase-file")
        if name == "unpack":
            item.add_argument("--dest", required=True)
            item.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv[1:])
    try:
        passphrase = _read_passphrase(args)
        if getattr(args, "encrypt", False) and passphrase is None:
            return tool_error("--encrypt 需要 --passphrase-env 或 --passphrase-file")
        if args.command == "pack":
            manifest = build_pack(
                Path(args.source),
                Path(args.out),
                pack_id=args.pack_id,
                version=args.version,
                roles=args.roles,
                created_at=args.created_at,
                passphrase=passphrase if args.encrypt else None,
                overwrite=args.force,
            )
            print(
                json.dumps(
                    {
                        "pack": str(args.out),
                        "pack_id": manifest["pack_id"],
                        "file_count": manifest["file_count"],
                        "encrypted": bool(manifest["encryption"]),
                        "manifest_sha256": manifest["manifest_sha256"],
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "verify":
            return emit(verify_pack(Path(args.pack), passphrase))
        if args.command == "list":
            print(json.dumps(describe(Path(args.pack)), ensure_ascii=False, indent=2))
            return 0
        unpack_pack(
            Path(args.pack),
            Path(args.dest),
            passphrase,
            overwrite=args.force,
        )
        print(json.dumps({"unpacked": str(args.dest)}, ensure_ascii=False))
        return 0
    except SkillpackError as exc:
        return tool_error(str(exc))
    except OSError as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
