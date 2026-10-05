"""Validate, pack and install independently composable CCFA skills."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, save_text_atomically, tool_error
from ccfa.skillpack import build_pack, unpack_pack, verify_pack

REGISTRY = Path("skills") / "registry.yaml"
MARKER = ".ccfa-skill-install.json"
SOURCE_ROOTS_KEY = "source_roots"


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_registry(root: Path) -> tuple[dict | None, list[Problem]]:
    path = Path(root) / REGISTRY
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, [Problem("skill-registry-unreadable", str(path), None, str(exc))]
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return None, [
            Problem(
                "skill-registry-invalid",
                str(path),
                None,
                "registry 必须是 version: 1 的对象",
            )
        ]
    skills = payload.get("skills")
    if not isinstance(skills, list) or not skills:
        return None, [
            Problem("skill-registry-invalid", str(path), None, "skills 必须是非空数组")
        ]
    return payload, []


def _index(registry: dict) -> dict[str, dict]:
    return {item["id"]: item for item in registry.get("skills", []) if isinstance(item, dict)}


def _source_directory(root: Path, registry: dict, item: dict) -> Path:
    source = item.get("source")
    if source is None:
        return (root / str(item["path"])).resolve()
    if not isinstance(source, dict):
        raise ValueError(f"{item.get('id')}: source 必须是映射")
    source_root = source.get("root")
    source_path = source.get("path")
    if not isinstance(source_root, str) or not source_root:
        raise ValueError(f"{item.get('id')}: source.root 必须是非空字符串")
    if not isinstance(source_path, str) or not source_path:
        raise ValueError(f"{item.get('id')}: source.path 必须是非空字符串")
    roots = registry.get(SOURCE_ROOTS_KEY) or {}
    if not isinstance(roots, dict):
        raise ValueError("source_roots 必须是映射")
    base_value = roots.get(source_root)
    if source_root == "repo":
        base = root
    elif isinstance(base_value, str) and base_value:
        base = Path(base_value).expanduser()
    else:
        raise ValueError(f"{item.get('id')}: 未知 source root: {source_root!r}")
    if not base.is_absolute():
        base = root / base
    base = base.resolve()
    target = (base / source_path).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"{item.get('id')}: source 逃出 source root") from exc
    return target


def _content_version(source: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return "content-" + digest.hexdigest()[:12]


def _entry_version(root: Path, registry: dict, item: dict) -> str:
    declared = item.get("version")
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    return _content_version(_source_directory(root, registry, item))


def validate_registry(root: Path, *, strict_external: bool = False) -> list[Problem]:
    root = Path(root).resolve()
    registry, problems = load_registry(root)
    if registry is None:
        return problems
    path = root / REGISTRY
    skills = registry["skills"]
    source_roots = registry.get(SOURCE_ROOTS_KEY, {})
    if not isinstance(source_roots, dict):
        problems.append(
            Problem("skill-registry-invalid", str(path), None, "source_roots 必须是映射")
        )
    seen: set[str] = set()
    for index, item in enumerate(skills):
        if not isinstance(item, dict):
            problems.append(
                Problem("skill-registry-invalid", str(path), None, f"skills[{index}] 必须是映射")
            )
            continue
        missing = [
            key for key in ("id", "description", "dependencies") if key not in item
        ]
        if "path" not in item and "source" not in item:
            missing.append("path/source")
        if "source" not in item and "version" not in item:
            missing.append("version")
        if missing:
            problems.append(
                Problem(
                    "skill-registry-invalid",
                    str(path),
                    None,
                    f"skills[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        skill_id = item["id"]
        if not isinstance(skill_id, str) or not skill_id.strip():
            problems.append(
                Problem("skill-registry-invalid", str(path), None, f"skills[{index}].id 非法")
            )
            continue
        if skill_id in seen:
            problems.append(
                Problem("skill-registry-duplicate", str(path), None, f"skill id 重复: {skill_id}")
            )
        seen.add(skill_id)
        try:
            source = _source_directory(root, registry, item)
        except ValueError as exc:
            problems.append(
                Problem("skill-registry-source-invalid", str(path), None, str(exc))
            )
            continue
        external = item.get("source") is not None
        if external and not source.exists():
            if strict_external:
                problems.append(
                    Problem(
                        "skill-registry-source-missing",
                        str(path),
                        None,
                        f"{skill_id}: 外部 skill 源不存在: {source}",
                    )
                )
            continue
        if not (source / "SKILL.md").is_file():
            problems.append(
                Problem(
                    "skill-registry-source-missing",
                    str(path),
                    None,
                    f"{skill_id}: 缺少 SKILL.md",
                )
            )
        metadata = source / "skill.yaml"
        if not metadata.is_file() and not external:
            problems.append(
                Problem(
                    "skill-registry-source-missing",
                    str(path),
                    None,
                    f"{skill_id}: 缺少 skill.yaml",
                )
            )
        elif metadata.is_file():
            try:
                meta = yaml.safe_load(metadata.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                problems.append(
                    Problem("skill-registry-source-invalid", str(metadata), None, str(exc))
                )
            else:
                if not isinstance(meta, dict) or meta.get("id") != skill_id:
                    problems.append(
                        Problem(
                            "skill-registry-source-invalid",
                            str(metadata),
                            None,
                            "skill.yaml 的 id 与 registry 不一致",
                        )
                    )
                if item.get("version") is not None and meta.get("version") != item.get("version"):
                    problems.append(
                        Problem(
                            "skill-registry-source-invalid",
                            str(metadata),
                            None,
                            "skill.yaml 的 version 与 registry 不一致",
                        )
                    )
        dependencies = item.get("dependencies")
        if not isinstance(dependencies, list) or not all(
            isinstance(value, str) for value in dependencies
        ):
            problems.append(
                Problem(
                    "skill-registry-invalid",
                    str(path),
                    None,
                    f"{skill_id}: dependencies 必须是字符串数组",
                )
            )
    by_id = _index(registry)
    for item in skills:
        if not isinstance(item, dict):
            continue
        skill_id = item.get("id")
        for dependency in item.get("dependencies", []):
            if dependency not in by_id:
                problems.append(
                    Problem(
                        "skill-registry-unknown-dependency",
                        str(path),
                        None,
                        f"{skill_id}: 依赖不存在: {dependency}",
                    )
                )
    _install_order(by_id, set(by_id), problems)
    return problems


def _install_order(
    by_id: dict[str, dict],
    requested: set[str],
    problems: list[Problem] | None = None,
) -> list[str]:
    problems = problems if problems is not None else []
    order: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(skill_id: str) -> None:
        if skill_id in visited:
            return
        if skill_id in visiting:
            problems.append(
                Problem(
                    "skill-registry-cycle",
                    skill_id,
                    None,
                    f"skill 依赖环包含 {skill_id}",
                )
            )
            return
        visiting.add(skill_id)
        item = by_id.get(skill_id)
        if item is None:
            problems.append(
                Problem(
                    "skill-registry-unknown-skill",
                    skill_id,
                    None,
                    f"未知 skill: {skill_id}",
                )
            )
            visiting.remove(skill_id)
            return
        for dependency in item.get("dependencies", []):
            visit(dependency)
        visiting.remove(skill_id)
        visited.add(skill_id)
        order.append(skill_id)

    for skill_id in sorted(requested):
        visit(skill_id)
    return order


def resolve(root: Path, skill_ids: list[str]) -> list[str]:
    registry, problems = load_registry(root)
    if registry is None:
        raise ValueError(problems[0].message)
    by_id = _index(registry)
    issues: list[Problem] = []
    order = _install_order(by_id, set(skill_ids), issues)
    if issues:
        first = issues[0]
        raise ValueError(f"{first.code}: {first.message}")
    return order


def pack_skill(
    root: Path,
    skill_id: str,
    out_dir: Path,
    *,
    force: bool = False,
) -> dict:
    root = Path(root).resolve()
    registry, problems = load_registry(root)
    if registry is None:
        raise ValueError(problems[0].message)
    item = _index(registry).get(skill_id)
    if item is None:
        raise ValueError(f"未知 skill: {skill_id}")
    source = _source_directory(root, registry, item)
    version = _entry_version(root, registry, item)
    out = Path(out_dir)
    if not out.is_absolute():
        out = root / out
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{skill_id}-{version}.skillpack"
    manifest = build_pack(
        source,
        target,
        pack_id=skill_id,
        version=version,
        roles=["ccfa-skill"],
        overwrite=force,
    )
    return {
        "skill_id": skill_id,
        "version": version,
        "pack": str(target),
        "sha256": _sha256_file(target),
        "file_count": manifest["file_count"],
    }


def install_skills(
    root: Path,
    target: Path,
    skill_ids: list[str],
    *,
    force: bool = False,
) -> list[dict]:
    root = Path(root).resolve()
    target = Path(target)
    if not target.is_absolute():
        target = root / target
    order = resolve(root, skill_ids)
    installed = []
    with tempfile.TemporaryDirectory(prefix="ccfa-skillpack-") as tmp:
        pack_dir = Path(tmp)
        for skill_id in order:
            packed = pack_skill(root, skill_id, pack_dir, force=True)
            pack_path = Path(packed["pack"])
            problems = verify_pack(pack_path)
            if problems:
                raise ValueError(f"{skill_id}: skillpack 校验失败: {problems[0].message}")
            destination = target / skill_id
            if destination.exists() and not force:
                raise ValueError(f"目标 skill 已存在，拒绝覆盖: {destination}")
            unpack_pack(pack_path, destination, overwrite=force)
            marker = {
                "skill_id": skill_id,
                "version": packed["version"],
                "pack_sha256": packed["sha256"],
                "source": "ccfa-skill-registry",
            }
            save_text_atomically(
                destination / MARKER,
                json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                description="skill install marker",
            )
            installed.append(marker)
    return installed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CCFA skill registry")
    sub = parser.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("list")
    list_parser.add_argument("--root", default=".")
    check = sub.add_parser("check")
    check.add_argument("--root", default=".")
    check.add_argument("--strict-external", action="store_true")
    resolve_parser = sub.add_parser("resolve")
    resolve_parser.add_argument("--root", default=".")
    resolve_parser.add_argument("--skill", action="append", required=True)
    pack = sub.add_parser("pack")
    pack.add_argument("--root", default=".")
    pack.add_argument("--skill", required=True)
    pack.add_argument("--out", default="dist/skillpacks")
    pack.add_argument("--force", action="store_true")
    install = sub.add_parser("install")
    install.add_argument("--root", default=".")
    install.add_argument("--skill", action="append", required=True)
    install.add_argument("--target", required=True)
    install.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    root = Path(args.root)
    try:
        if args.command == "list":
            registry, problems = load_registry(root)
            if registry is None:
                return emit(problems, [])
            print(json.dumps(registry["skills"], ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.command == "check":
            return emit(
                validate_registry(root, strict_external=args.strict_external),
                [],
            )
        if args.command == "resolve":
            print(json.dumps(resolve(root, args.skill), ensure_ascii=False))
            return 0
        if args.command == "pack":
            print(json.dumps(pack_skill(root, args.skill, Path(args.out), force=args.force), ensure_ascii=False, indent=2))
            return 0
        print(json.dumps(install_skills(root, Path(args.target), args.skill, force=args.force), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
