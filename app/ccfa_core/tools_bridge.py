"""Deterministic tools exposed to the chat engine.

Read-only tools run immediately. Write tools require an explicit confirmation
callback and are declined when no callback is provided. Every call is audited
to ``<paper_root>/ccfa-workfiles/agent-tools.jsonl``; the audit stores only a
truncated sha256 digest of the arguments, never the arguments themselves.

``run-log run`` (arbitrary command execution) is deliberately not exposed.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NamedTuple

from ccfa_core.atomic import save_text_atomically
from ccfa_core.http_tools import HttpToolRegistry
from ccfa_core.workflow import WorkflowClient

READ = "read"
WRITE = "write"

AUDIT_RELATIVE = Path("ccfa-workfiles") / "agent-tools.jsonl"


class ToolArgumentError(ValueError):
    """Raised when tool arguments do not match the declared schema."""


@dataclass(frozen=True)
class ToolContext:
    """Paths shared by every tool call in one bridge."""

    project_root: Path
    library_dir: Path | None = None
    workflow: WorkflowClient | None = None

    def client(self) -> WorkflowClient:
        """Return the workflow client, creating the default one on demand."""

        return self.workflow or WorkflowClient()


class Tool(NamedTuple):
    name: str
    description: str
    risk: str
    parameters: dict
    handler: Callable[[ToolContext, dict], Any]


def _schema(properties: dict, required: tuple = ()) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _resolve_within(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("路径必须是非空字符串")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError(f"路径必须是相对路径: {raw!r}")
    root = Path(root).resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(f"路径越出论文根: {raw!r}") from None
    return resolved


def _tool_milestones_stage(context: ToolContext, args: dict) -> dict:
    return context.client().json(
        "milestones",
        ("stage", "--paper-root", str(context.project_root)),
    )


def _tool_milestones_due(context: ToolContext, args: dict) -> dict:
    raw_today = args.get("today")
    command = ["due", "--paper-root", str(context.project_root)]
    if raw_today is not None:
        if not isinstance(raw_today, str) or not raw_today.strip():
            raise ValueError("today 不能为空字符串")
        command += ["--today", raw_today.strip()]
    return context.client().json("milestones", tuple(command))


def _tool_library_search(context: ToolContext, args: dict) -> dict:
    library_dir = context.library_dir
    if library_dir is None:
        raise ValueError("未配置共享文献库：请先运行 library index")
    index_path = Path(library_dir) / "index.db"
    if not index_path.is_file():
        raise ValueError(
            f"找不到文献库索引 {index_path}：请先运行 library index"
        )
    return context.client().json(
        "library",
        (
            "--dir",
            str(library_dir),
            "search",
            args["query"],
            "--limit",
            str(args.get("limit", 20)),
        ),
    )


def _tool_memory_search(context: ToolContext, args: dict) -> dict:
    return context.client().json(
        "memory",
        ("--paper-root", str(context.project_root), "search", args["query"]),
    )


def _tool_memory_list(context: ToolContext, args: dict) -> dict:
    command = ["--paper-root", str(context.project_root), "list"]
    kind = args.get("kind")
    if kind:
        command += ["--kind", kind]
    status = args.get("status")
    if status:
        command += ["--status", status]
    return context.client().json("memory", tuple(command))


def _tool_memory_add_idea(context: ToolContext, args: dict) -> dict:
    command = [
        "--paper-root",
        str(context.project_root),
        "add-idea",
        "--idea",
        args["idea"],
        "--date",
        args["date"],
    ]
    status = args.get("status")
    if status:
        command += ["--status", status]
    notes = args.get("notes")
    if notes:
        command += ["--notes", notes]
    return context.client().json("memory", tuple(command))


def _tool_memory_add_dead_end(context: ToolContext, args: dict) -> dict:
    return context.client().json(
        "memory",
        (
            "--paper-root",
            str(context.project_root),
            "add-dead-end",
            "--idea",
            args["idea"],
            "--date",
            args["date"],
            "--reason",
            args["reason"],
            "--evidence",
            args["evidence"],
            "--reopen-if",
            args["reopen_if"],
        ),
    )


def _tool_state_set_stage(context: ToolContext, args: dict) -> dict:
    # The GUI confirmation already happened; ``confirm`` stays mandatory in
    # the underlying implementation, which is the ``--confirm`` semantics.
    return context.client().json(
        "state",
        (
            "--paper-root",
            str(context.project_root),
            "set-stage",
            args["to"],
            "--reason",
            args["reason"],
            "--confirm",
        ),
    )


def _tool_state_rollback(context: ToolContext, args: dict) -> dict:
    command = [
        "--paper-root",
        str(context.project_root),
        "rollback",
        args["to"],
        "--reason",
        args["reason"],
        "--confirm",
    ]
    for path in args.get("void_artifacts") or ():
        command += ["--void-artifacts", str(path)]
    return context.client().json("state", tuple(command))


def _tool_trace_claims_check(context: ToolContext, args: dict) -> dict:
    command: list[str] = []
    for raw in args["docs"]:
        command += ["--doc", str(_resolve_within(context.project_root, raw))]
    if args.get("base_dir") is not None:
        command += [
            "--base-dir",
            str(_resolve_within(context.project_root, args["base_dir"])),
        ]
    if args.get("untagged", True):
        command.append("--untagged")
    return context.client().json("trace_claims", tuple(command))


TOOL_DEFINITIONS: tuple[Tool, ...] = (
    Tool(
        name="milestones_stage",
        description="读取论文当前 stage、gate 与 updated_at（只读）。",
        risk=READ,
        parameters=_schema({}),
        handler=_tool_milestones_stage,
    ),
    Tool(
        name="milestones_due",
        description=(
            "读取投稿倒排里程碑报告；可选 today=YYYY-MM-DD 注入日期（只读）。"
        ),
        risk=READ,
        parameters=_schema(
            {"today": {"type": "string", "description": "YYYY-MM-DD"}}
        ),
        handler=_tool_milestones_due,
    ),
    Tool(
        name="library_search",
        description=(
            "在共享文献库 <repo>/library/index.db 中检索文献元数据（只读，"
            "不含 PDF 全文）。"
        ),
        risk=READ,
        parameters=_schema(
            {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            required=("query",),
        ),
        handler=_tool_library_search,
    ),
    Tool(
        name="memory_search",
        description="检索 research memory 的 idea 与 dead-end（只读）。",
        risk=READ,
        parameters=_schema(
            {"query": {"type": "string"}},
            required=("query",),
        ),
        handler=_tool_memory_search,
    ),
    Tool(
        name="memory_list",
        description="列出 research memory，可按 kind/status 过滤（只读）。",
        risk=READ,
        parameters=_schema(
            {
                "kind": {
                    "type": "string",
                    "enum": ["all", "ideas", "dead-ends"],
                },
                "status": {"type": "string"},
            }
        ),
        handler=_tool_memory_list,
    ),
    Tool(
        name="memory_add_idea",
        description="写入一条 idea；这是写操作，执行前需要用户确认。",
        risk=WRITE,
        parameters=_schema(
            {
                "idea": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "status": {"type": "string"},
                "notes": {"type": "string"},
            },
            required=("idea", "date"),
        ),
        handler=_tool_memory_add_idea,
    ),
    Tool(
        name="memory_add_dead_end",
        description=(
            "写入一条 dead-end 及 reopen_if；这是写操作，执行前需要用户确认。"
        ),
        risk=WRITE,
        parameters=_schema(
            {
                "idea": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "reason": {"type": "string"},
                "evidence": {"type": "string"},
                "reopen_if": {"type": "string"},
            },
            required=("idea", "date", "reason", "evidence", "reopen_if"),
        ),
        handler=_tool_memory_add_dead_end,
    ),
    Tool(
        name="state_set_stage",
        description=(
            "推进 ccfa.yaml 的 stage（只允许向后推进）；这是写操作，"
            "执行前需要用户确认。"
        ),
        risk=WRITE,
        parameters=_schema(
            {"to": {"type": "string"}, "reason": {"type": "string"}},
            required=("to", "reason"),
        ),
        handler=_tool_state_set_stage,
    ),
    Tool(
        name="state_rollback",
        description=(
            "回退 ccfa.yaml 的 stage 并记录作废产物；这是写操作，"
            "执行前需要用户确认。"
        ),
        risk=WRITE,
        parameters=_schema(
            {
                "to": {"type": "string"},
                "reason": {"type": "string"},
                "void_artifacts": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            required=("to", "reason"),
        ),
        handler=_tool_state_rollback,
    ),
    Tool(
        name="trace_claims_check",
        description=(
            "核验正文 \\dataval 标签与源数据一致，并默认给出未标记数字提示"
            "（只读）。"
        ),
        risk=READ,
        parameters=_schema(
            {
                "docs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "base_dir": {"type": "string"},
                "untagged": {"type": "boolean"},
            },
            required=("docs",),
        ),
        handler=_tool_trace_claims_check,
    ),
)

_TOOLS_BY_NAME = {tool.name: tool for tool in TOOL_DEFINITIONS}

_TYPE_CHECKS = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: type(value) is int,
    "boolean": lambda value: type(value) is bool,
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, dict),
}


def openai_tools() -> list[dict]:
    """Return fresh OpenAI function-calling specs for every tool."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": copy.deepcopy(tool.parameters),
            },
        }
        for tool in TOOL_DEFINITIONS
    ]


def _validate_arguments(schema: dict, arguments: Any) -> None:
    if not isinstance(arguments, dict):
        raise ToolArgumentError("参数必须是 JSON 对象")
    properties = schema.get("properties", {})
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise ToolArgumentError(f"未知参数: {', '.join(unknown)}")
    missing = [name for name in schema.get("required", []) if name not in arguments]
    if missing:
        raise ToolArgumentError(f"缺少参数: {', '.join(missing)}")
    for name, value in arguments.items():
        declared = properties[name]
        check = _TYPE_CHECKS.get(declared.get("type"))
        if check is not None and not check(value):
            raise ToolArgumentError(f"参数 {name} 必须是 {declared['type']}")
        if declared.get("enum") is not None and value not in declared["enum"]:
            raise ToolArgumentError(
                f"参数 {name} 必须是 {' / '.join(declared['enum'])}"
            )
        if declared.get("type") == "array":
            min_items = declared.get("minItems")
            if min_items is not None and len(value) < min_items:
                raise ToolArgumentError(f"参数 {name} 至少需要 {min_items} 项")
            item_schema = declared.get("items")
            if item_schema is not None:
                item_check = _TYPE_CHECKS.get(item_schema.get("type"))
                if item_check is not None:
                    for item in value:
                        if not item_check(item):
                            raise ToolArgumentError(
                                f"参数 {name} 的每一项必须是 "
                                f"{item_schema['type']}"
                            )


def _digest(arguments: Any) -> str:
    payload = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        default=repr,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error(name: Any, code: str, message: str) -> dict:
    return {
        "ok": False,
        "tool": name,
        "error": {"code": code, "message": message},
    }


def _http_handler(
    registry: HttpToolRegistry,
    name: str,
) -> Callable[[ToolContext, dict], Any]:
    def handler(context: ToolContext, arguments: dict) -> Any:
        return registry.call(name, arguments)

    return handler


class ToolBridge:
    """Dispatch model tool calls against one paper project."""

    def __init__(
        self,
        project_root: Path,
        *,
        library_dir: Path | None = None,
        confirm_write: Callable[[str, dict], bool] | None = None,
        on_call: Callable[[dict], None] | None = None,
        http_tools: HttpToolRegistry | None = None,
    ):
        self.project_root = Path(project_root)
        self.library_dir = (
            Path(library_dir) if library_dir is not None else None
        )
        self._context = ToolContext(self.project_root, self.library_dir)
        self._confirm_write = confirm_write
        self._on_call = on_call
        self._tools = dict(_TOOLS_BY_NAME)
        if http_tools is not None:
            self._register_http_tools(http_tools)

    def _register_http_tools(self, registry: HttpToolRegistry) -> None:
        for spec in registry.specs():
            if spec.name in self._tools:
                raise ValueError(
                    f"HTTP 工具名与内置工具冲突: {spec.name!r}"
                )
            self._tools[spec.name] = Tool(
                name=spec.name,
                description=spec.description,
                risk=spec.risk,
                parameters=copy.deepcopy(spec.parameters),
                handler=_http_handler(registry, spec.name),
            )

    def openai_tools(self) -> list[dict]:
        """Return fresh OpenAI specs for built-in plus registered tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": copy.deepcopy(tool.parameters),
                },
            }
            for tool in self._tools.values()
        ]

    def risk(self, name: str) -> str:
        return self._tools[name].risk

    def execute(self, name: Any, arguments: Any = None) -> dict:
        if arguments is None:
            arguments = {}
        tool = self._tools.get(name) if isinstance(name, str) else None
        if tool is None:
            result = _error(name, "unknown-tool", f"未知工具: {name!r}")
            self._finish(name, arguments, "unknown", "unknown-tool", result)
            return result
        try:
            _validate_arguments(tool.parameters, arguments)
        except ToolArgumentError as exc:
            result = _error(name, "invalid-arguments", str(exc))
            self._finish(name, arguments, tool.risk, "invalid", result)
            return result
        if tool.risk == WRITE:
            allowed = False
            if self._confirm_write is not None:
                try:
                    allowed = bool(
                        self._confirm_write(name, dict(arguments))
                    )
                except Exception:
                    allowed = False
            if not allowed:
                result = _error(name, "user-declined", "user declined")
                self._finish(name, arguments, tool.risk, "declined", result)
                return result
        try:
            value = tool.handler(self._context, arguments)
        except Exception as exc:
            result = _error(
                name,
                getattr(exc, "code", "tool-error"),
                f"{type(exc).__name__}: {exc}",
            )
            self._finish(name, arguments, tool.risk, "error", result)
            return result
        result = {
            "ok": True,
            "tool": name,
            "risk": tool.risk,
            "result": value,
        }
        self._finish(name, arguments, tool.risk, "ok", result)
        return result

    def _finish(
        self,
        name: Any,
        arguments: Any,
        risk: str,
        outcome: str,
        result: dict,
    ) -> None:
        error = self._audit(name, arguments, risk, outcome)
        if error is not None:
            result["audit_error"] = error
        if self._on_call is not None:
            try:
                self._on_call(
                    {
                        "tool": name,
                        "risk": risk,
                        "outcome": outcome,
                    }
                )
            except Exception:
                pass

    def _audit(
        self,
        name: Any,
        arguments: Any,
        risk: str,
        outcome: str,
    ) -> str | None:
        entry = {
            "time": _utc_now(),
            "tool": name if isinstance(name, str) else str(name),
            "args_digest": _digest(arguments),
            "risk": risk,
            "outcome": outcome,
        }
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
        path = self.project_root / AUDIT_RELATIVE
        try:
            existing = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            existing = ""
        except OSError as exc:
            return f"{type(exc).__name__}: {exc}"
        if existing and not existing.endswith("\n"):
            existing += "\n"
        try:
            save_text_atomically(
                path,
                existing + line,
                description="工具审计日志",
            )
        except (OSError, ValueError) as exc:
            return f"{type(exc).__name__}: {exc}"
        return None
