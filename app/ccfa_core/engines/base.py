"""Shared engine value types and the Engine protocol (zero Qt)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class EngineError(RuntimeError):
    """Raised when an engine cannot complete a request.

    Messages are human readable and must never contain API keys or other
    secret material.
    """


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class EngineReply:
    text: str
    tool_calls: list[dict] = field(default_factory=list)


@runtime_checkable
class Engine(Protocol):
    name: str

    def send(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict] | None = None,
        timeout_s: float | None = None,
        cancel: Any = None,
    ) -> EngineReply:
        ...


def is_cancelled(cancel: Any) -> bool:
    """Return True when a cancellation token asks the engine to stop.

    Tokens may be plain booleans, callables returning a boolean, or objects
    with an ``is_set()`` method (for example ``threading.Event``).
    """
    if cancel is None:
        return False
    if callable(cancel):
        return bool(cancel())
    is_set = getattr(cancel, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    return bool(cancel)


def validate_timeout(value: Any, field_name: str) -> float:
    """Validate a positive timeout in seconds and return it as a float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} 必须是正数")
    if value <= 0:
        raise ValueError(f"{field_name} 必须是正数")
    return float(value)
