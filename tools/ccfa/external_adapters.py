"""Inspect external-service adapters without reading or printing secrets."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from ccfa import skill_registry
from ccfa.cli import Problem, emit, tool_error

ADAPTERS = Path("skills") / "adapters.yaml"
AUTH_MODES = {"none", "env", "local", "browser", "cli-login", "oauth", "remote-mcp"}


def load_adapters(root: Path) -> tuple[dict | None, list[Problem]]:
    path = Path(root) / ADAPTERS
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, [Problem("adapters-unreadable", str(path), None, str(exc))]
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return None, [
            Problem(
                "adapters-invalid",
                str(path),
                None,
                "adapters registry 必须是 version: 1 的对象",
            )
        ]
    adapters = payload.get("adapters")
    if not isinstance(adapters, list) or not adapters:
        return None, [
            Problem("adapters-invalid", str(path), None, "adapters 必须是非空数组")
        ]
    return payload, []


def _index(registry: dict) -> dict[str, dict]:
    return {
        item["id"]: item
        for item in registry.get("skills", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def validate_adapters(root: Path, *, strict_external: bool = False) -> list[Problem]:
    root = Path(root).resolve()
    payload, problems = load_adapters(root)
    if payload is None:
        return problems
    path = root / ADAPTERS
    skill_payload, skill_problems = skill_registry.load_registry(root)
    if skill_payload is None:
        return skill_problems
    skills = _index(skill_payload)
    seen: set[str] = set()
    for index, item in enumerate(payload["adapters"]):
        if not isinstance(item, dict):
            problems.append(
                Problem("adapters-invalid", str(path), None, f"adapters[{index}] 必须是映射")
            )
            continue
        missing = [
            key
            for key in ("id", "skill", "service", "auth_mode", "required_env", "optional_env", "capabilities")
            if key not in item
        ]
        if missing:
            problems.append(
                Problem(
                    "adapters-invalid",
                    str(path),
                    None,
                    f"adapters[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        adapter_id = item.get("id")
        skill_id = item.get("skill")
        if not isinstance(adapter_id, str) or not adapter_id.strip():
            problems.append(
                Problem("adapters-invalid", str(path), None, f"adapters[{index}].id 非法")
            )
            continue
        if adapter_id in seen:
            problems.append(
                Problem("adapters-duplicate", str(path), None, f"adapter id 重复: {adapter_id}")
            )
        seen.add(adapter_id)
        if skill_id not in skills:
            problems.append(
                Problem(
                    "adapters-unknown-skill",
                    str(path),
                    None,
                    f"{adapter_id}: skill 不在 registry 中: {skill_id!r}",
                )
            )
        if item.get("auth_mode") not in AUTH_MODES:
            problems.append(
                Problem(
                    "adapters-invalid",
                    str(path),
                    None,
                    f"{adapter_id}: auth_mode 非法",
                )
            )
        for field in ("required_env", "optional_env", "capabilities"):
            values = item.get(field)
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values
            ):
                problems.append(
                    Problem(
                        "adapters-invalid",
                        str(path),
                        None,
                        f"{adapter_id}: {field} 必须是字符串数组",
                    )
                )
        healthcheck = item.get("healthcheck")
        if healthcheck is not None and not isinstance(healthcheck, dict):
            problems.append(
                Problem(
                    "adapters-invalid",
                    str(path),
                    None,
                    f"{adapter_id}: healthcheck 必须是映射或 null",
                )
            )
        if strict_external and skill_id in skills:
            try:
                source = skill_registry._source_directory(root, skill_payload, skills[skill_id])
            except ValueError as exc:
                problems.append(
                    Problem(
                        "adapters-source-invalid",
                        str(path),
                        None,
                        f"{adapter_id}: {exc}",
                    )
                )
            else:
                if not source.exists():
                    problems.append(
                        Problem(
                            "adapters-source-missing",
                            str(path),
                            None,
                            f"{adapter_id}: skill 源不存在: {source}",
                        )
                    )
    return problems


def _configured(item: dict, environ: dict[str, str]) -> str:
    mode = item.get("auth_mode")
    required = item.get("required_env", [])
    if mode in {"none", "local"}:
        return "yes"
    if mode in {"browser", "oauth", "remote-mcp"}:
        return "manual"
    if mode == "env":
        return "yes" if all(name in environ and environ[name] for name in required) else "no"
    if mode == "cli-login":
        return "yes" if all(name in environ and environ[name] for name in required) else "manual"
    return "manual"


def _http_probe(url: str, accept_status: list[int], timeout: float) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "ccfa-adapter-probe"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", response.getcode())
            return status in accept_status, f"HTTP {status}"
    except urllib.error.HTTPError as exc:
        return exc.code in accept_status, f"HTTP {exc.code}"
    except (OSError, urllib.error.URLError) as exc:
        return False, str(exc)


def probe_adapter(
    root: Path,
    adapter_id: str,
    *,
    environ: dict[str, str] | None = None,
    functional: bool = False,
    timeout: float = 10.0,
    runner=None,
) -> dict:
    root = Path(root).resolve()
    payload, problems = load_adapters(root)
    if payload is None:
        raise ValueError(problems[0].message)
    item = next(
        (entry for entry in payload["adapters"] if isinstance(entry, dict) and entry.get("id") == adapter_id),
        None,
    )
    if item is None:
        raise ValueError(f"未知 adapter: {adapter_id}")
    skill_payload, skill_problems = skill_registry.load_registry(root)
    if skill_payload is None:
        raise ValueError(skill_problems[0].message)
    skill = _index(skill_payload).get(item["skill"])
    source_exists = False
    if skill is not None:
        source = skill_registry._source_directory(root, skill_payload, skill)
        source_exists = source.exists() and (source / "SKILL.md").is_file()
    configured = _configured(item, os.environ if environ is None else environ)
    functional_status = "not-checked"
    functional_detail = ""
    healthcheck = item.get("healthcheck")
    if functional and isinstance(healthcheck, dict):
        kind = healthcheck.get("kind")
        if kind == "http":
            functional_status, functional_detail = _http_probe(
                str(healthcheck.get("url")),
                [int(value) for value in healthcheck.get("accept_status", [200])],
                timeout,
            )
            functional_status = "pass" if functional_status else "fail"
        elif kind == "command":
            command = healthcheck.get("command")
            if not isinstance(command, list) or not command:
                functional_status = "invalid"
                functional_detail = "健康检查 command 非法"
            else:
                try:
                    completed = (runner or subprocess.run)(
                        command,
                        check=False,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=timeout,
                    )
                    functional_status = "pass" if completed.returncode == 0 else "fail"
                    functional_detail = (completed.stdout or completed.stderr or "").strip()[:500]
                except (OSError, subprocess.TimeoutExpired) as exc:
                    functional_status = "fail"
                    functional_detail = str(exc)
        else:
            functional_status = "unsupported"
            functional_detail = f"未知 healthcheck kind: {kind!r}"
    requires_probe = (
        isinstance(healthcheck, dict)
        or item.get("auth_mode") in {"local", "browser", "oauth", "remote-mcp", "cli-login"}
    )
    ready = (
        source_exists
        and configured == "yes"
        and (not requires_probe or functional_status == "pass")
    )
    return {
        "id": adapter_id,
        "skill": item.get("skill"),
        "service": item.get("service"),
        "auth_mode": item.get("auth_mode"),
        "required_env": item.get("required_env", []),
        "optional_env": item.get("optional_env", []),
        "configured": configured,
        "installed": source_exists,
        "functional": functional_status,
        "functional_detail": functional_detail,
        "ready": ready,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="外部科研服务 adapter 检查")
    sub = parser.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("list")
    list_parser.add_argument("--root", default=".")
    check = sub.add_parser("check")
    check.add_argument("--root", default=".")
    check.add_argument("--strict-external", action="store_true")
    probe = sub.add_parser("probe")
    probe.add_argument("--root", default=".")
    probe.add_argument("--adapter", required=True)
    probe.add_argument("--functional", action="store_true")
    probe.add_argument("--timeout", type=float, default=10.0)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "list":
            payload, problems = load_adapters(Path(args.root))
            if payload is None:
                return emit(problems, [])
            print(json.dumps(payload["adapters"], ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.command == "check":
            return emit(
                validate_adapters(
                    Path(args.root),
                    strict_external=args.strict_external,
                ),
                [],
            )
        print(
            json.dumps(
                probe_adapter(
                    Path(args.root),
                    args.adapter,
                    functional=args.functional,
                    timeout=args.timeout,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
