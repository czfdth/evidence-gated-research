"""OpenAI-compatible chat-completions engine.

The API key is read from a SecretStore at request time. It is never logged
and never embedded into engine errors; response snippets are redacted before
they reach an exception message.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

import httpx

from .base import (
    ChatMessage,
    EngineError,
    EngineReply,
    is_cancelled,
    validate_timeout,
)

LOGGER = logging.getLogger(__name__)

SNIPPET_LIMIT = 500
REDACTED = "[redacted]"


def _snippet(text: Any, secret: str, limit: int = SNIPPET_LIMIT) -> str:
    redacted = str(text)
    if secret and secret in redacted:
        redacted = redacted.replace(secret, REDACTED)
    if len(redacted) <= limit:
        return redacted
    marker = "...[truncated]"
    keep = max(0, limit - len(marker))
    return redacted[:keep] + marker


class OpenAICompatibleEngine:
    """Chat-completions engine for OpenAI-compatible HTTP APIs.

    Cancellation is cooperative: a cancel token is checked before the request
    and again after it returns, so an in-flight HTTP request is never aborted
    mid-flight; the worst case waits for the current request to finish or for
    ``timeout_s`` to fire. The codex engine, by contrast, kills its child
    process as soon as the token is set.
    """

    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        secret_store: Any,
        key_name: str,
        timeout_s: float = 120,
        transport: httpx.BaseTransport | None = None,
        client_factory: Callable[[], Any] | None = None,
        tool_handler: Callable[[str, dict], dict] | None = None,
        max_tool_rounds: int = 6,
    ):
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url 必须是非空字符串")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model 必须是非空字符串")
        if not isinstance(key_name, str) or not key_name.strip():
            raise ValueError("key_name 必须是非空字符串")
        if secret_store is None:
            raise ValueError("secret_store 不能为 None")
        self._base_url = base_url.strip().rstrip("/")
        self._model = model.strip()
        self._secret_store = secret_store
        self._key_name = key_name
        self._timeout_s = validate_timeout(timeout_s, "timeout_s")
        self._transport = transport
        self._client_factory = client_factory
        self._tool_handler = None
        self._max_tool_rounds = 6
        self.configure_tools(tool_handler, max_tool_rounds)

    def configure_tools(
        self,
        handler: Callable[[str, dict], dict] | None,
        max_rounds: int = 6,
    ) -> None:
        """Attach (or clear) the tool handler used by the tool-call loop."""
        if handler is not None and not callable(handler):
            raise ValueError("tool_handler 必须可调用或 None")
        if type(max_rounds) is not int or max_rounds < 1:
            raise ValueError("max_tool_rounds 必须是正整数")
        self._tool_handler = handler
        self._max_tool_rounds = max_rounds

    def send(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict] | None = None,
        timeout_s: float | None = None,
        cancel: Any = None,
    ) -> EngineReply:
        if is_cancelled(cancel):
            raise EngineError("请求已取消")
        key = self._api_key()
        effective_timeout = (
            self._timeout_s
            if timeout_s is None
            else validate_timeout(timeout_s, "timeout_s")
        )
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"
        conversation: list[dict[str, Any]] = [
            {"role": message.role, "content": message.content}
            for message in messages
        ]
        rounds = 0
        while True:
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": conversation,
            }
            if tools is not None:
                payload["tools"] = tools
            body = self._request(
                url,
                payload,
                headers,
                effective_timeout,
                key,
                cancel,
            )
            reply = self._parse_reply(body)
            if not reply.tool_calls or self._tool_handler is None:
                return reply
            if rounds >= self._max_tool_rounds:
                raise EngineError(
                    f"工具调用轮数超过上限 {self._max_tool_rounds}，已停止"
                )
            conversation.append(
                {
                    "role": "assistant",
                    "content": reply.text or None,
                    "tool_calls": reply.tool_calls,
                }
            )
            for index, call in enumerate(reply.tool_calls):
                conversation.append(
                    self._tool_message(call, index, rounds)
                )
            rounds += 1

    def _request(
        self,
        url: str,
        payload: dict,
        headers: dict,
        timeout: float,
        key: str,
        cancel: Any,
    ) -> Any:
        LOGGER.debug("POST %s model=%s", url, self._model)
        try:
            with self._make_client() as client:
                response = client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
        except httpx.TimeoutException as exc:
            raise EngineError(
                f"请求超时（{timeout:g}s）: {_snippet(exc, key)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise EngineError(f"请求失败: {_snippet(exc, key)}") from exc
        if is_cancelled(cancel):
            raise EngineError("请求已取消")
        if not 200 <= response.status_code < 300:
            raise EngineError(
                f"HTTP {response.status_code}: "
                f"{_snippet(self._response_text(response), key)}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise EngineError(
                "响应不是合法 JSON: "
                f"{_snippet(self._response_text(response), key)}"
            ) from exc
        return body

    def _tool_message(
        self,
        call: Any,
        index: int,
        round_index: int,
    ) -> dict:
        fallback_id = f"call_{round_index}_{index}"
        call_id = fallback_id
        name = None
        arguments: Any = {}
        problem = None
        if not isinstance(call, dict):
            problem = "tool_call 必须是对象"
        else:
            raw_id = call.get("id")
            if isinstance(raw_id, str) and raw_id.strip():
                call_id = raw_id
            function = call.get("function")
            if not isinstance(function, dict):
                problem = "tool_call.function 必须是对象"
            else:
                raw_name = function.get("name")
                if not isinstance(raw_name, str) or not raw_name.strip():
                    problem = "tool_call.function.name 必须是非空字符串"
                else:
                    name = raw_name
                    raw_arguments = function.get("arguments", "{}")
                    if isinstance(raw_arguments, dict):
                        arguments = raw_arguments
                    elif isinstance(raw_arguments, str):
                        try:
                            arguments = (
                                json.loads(raw_arguments)
                                if raw_arguments.strip()
                                else {}
                            )
                        except ValueError:
                            problem = (
                                "tool_call.function.arguments 不是合法 JSON"
                            )
                    else:
                        problem = (
                            "tool_call.function.arguments 必须是 JSON 字符串"
                        )
        if problem is not None:
            result = {
                "ok": False,
                "error": {"code": "invalid-tool-call", "message": problem},
            }
        else:
            try:
                result = self._tool_handler(name, arguments)
            except Exception as exc:  # tool failures must not stop the chat
                result = {
                    "ok": False,
                    "error": {
                        "code": "tool-handler-error",
                        "message": f"{type(exc).__name__}: {exc}",
                    },
                }
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps(result, ensure_ascii=False),
        }

    def _api_key(self) -> str:
        try:
            value = self._secret_store.get(self._key_name)
        except Exception as exc:  # never echo the store message: it may embed
            raise EngineError(  # the key under a hostile implementation
                f"无法读取 API key（{type(exc).__name__}）"
            ) from exc
        if not isinstance(value, str) or not value.strip():
            raise EngineError(
                "未配置 API key：请先在设置中保存该 provider 的密钥"
            )
        return value.strip()

    def _make_client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        return httpx.Client(transport=self._transport, timeout=self._timeout_s)

    @staticmethod
    def _response_text(response: Any) -> str:
        try:
            return response.text
        except Exception:
            return ""

    @staticmethod
    def _parse_reply(body: Any) -> EngineReply:
        if not isinstance(body, dict):
            raise EngineError("响应 JSON 顶层必须是对象")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise EngineError("响应缺少 choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise EngineError("choices[0] 必须是对象")
        message = first.get("message")
        if not isinstance(message, dict):
            raise EngineError("choices[0].message 必须是对象")
        content = message.get("content")
        if content is None:
            text = ""
        elif isinstance(content, str):
            text = content
        else:
            raise EngineError("choices[0].message.content 必须是字符串或 null")
        tool_calls = message.get("tool_calls")
        if tool_calls is None:
            tool_calls = []
        elif not isinstance(tool_calls, list):
            raise EngineError("choices[0].message.tool_calls 必须是列表")
        return EngineReply(text=text, tool_calls=list(tool_calls))
