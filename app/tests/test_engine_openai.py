"""Offline tests for the OpenAI-compatible HTTP engine (MockTransport only)."""

from __future__ import annotations

import json
import unittest

import httpx

from ccfa_core.engines.base import ChatMessage, Engine, EngineError
from ccfa_core.engines.openai_compat import OpenAICompatibleEngine

FAKE_KEY = "sk-test-FAKE-KEY-1234567890"
BASE_URL = "https://api.example.test/v1"


class InMemorySecretStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key_name):
        return self.values.get(key_name)

    def set(self, key_name, value):
        self.values[key_name] = value

    def delete(self, key_name):
        self.values.pop(key_name, None)


def make_engine(handler, *, key=FAKE_KEY, **overrides):
    calls = {"count": 0}

    def counting_handler(request):
        calls["count"] += 1
        return handler(request)

    transport = httpx.MockTransport(counting_handler)
    store = InMemorySecretStore(
        {"provider-key": key} if key is not None else {}
    )
    values = {
        "base_url": BASE_URL,
        "model": "test-model",
        "secret_store": store,
        "key_name": "provider-key",
        "timeout_s": 5.0,
        "transport": transport,
    }
    values.update(overrides)
    return OpenAICompatibleEngine(**values), calls


def chat_json(content="hello", **message_extra):
    message = {"role": "assistant", "content": content}
    message.update(message_extra)
    return {"choices": [{"message": message}]}


class OpenAICompatibleEngineTests(unittest.TestCase):
    def test_success_posts_expected_request_and_returns_text(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["method"] = request.method
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json=chat_json("你好"))

        engine, calls = make_engine(handler)

        reply = engine.send([ChatMessage("user", "hello")])

        self.assertEqual(reply.text, "你好")
        self.assertEqual(reply.tool_calls, [])
        self.assertEqual(seen["url"], BASE_URL + "/chat/completions")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["auth"], "Bearer " + FAKE_KEY)
        self.assertEqual(seen["body"]["model"], "test-model")
        self.assertEqual(
            seen["body"]["messages"],
            [{"role": "user", "content": "hello"}],
        )
        self.assertNotIn("tools", seen["body"])
        self.assertEqual(calls["count"], 1)

    def test_tool_calls_are_preserved_and_tools_are_passed_through(self):
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "milestones_due", "arguments": "{}"},
            }
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "milestones_due",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        def handler(request):
            body = json.loads(request.content.decode("utf-8"))
            self.assertEqual(body["tools"], tools)
            return httpx.Response(
                200,
                json=chat_json(None, tool_calls=tool_calls),
            )

        engine, _ = make_engine(handler)

        reply = engine.send([ChatMessage("user", "check")], tools=tools)

        self.assertEqual(reply.text, "")
        self.assertEqual(reply.tool_calls, tool_calls)

    def test_non_2xx_raises_with_status_and_bounded_snippet(self):
        body = "echo " + FAKE_KEY + " " + "x" * 800

        def handler(request):
            return httpx.Response(401, text=body)

        engine, _ = make_engine(handler)

        with self.assertRaises(EngineError) as context:
            engine.send([ChatMessage("user", "hello")])

        message = str(context.exception)
        self.assertIn("401", message)
        self.assertLessEqual(message.count("x"), 500)
        self.assertNotIn(FAKE_KEY, message)
        snippet = message.split(": ", 1)[1]
        self.assertLessEqual(len(snippet), 500)

    def test_bad_json_raises_engine_error(self):
        def handler(request):
            return httpx.Response(200, text="not-json{")

        engine, _ = make_engine(handler)

        with self.assertRaises(EngineError) as context:
            engine.send([ChatMessage("user", "hello")])

        self.assertIn("JSON", str(context.exception))

    def test_missing_or_malformed_choices_raise_engine_error(self):
        payloads = [
            {},
            {"choices": []},
            {"choices": "nope"},
            {"choices": [{"message": "nope"}]},
            {"choices": [{"message": {"content": 42}}]},
        ]
        for payload in payloads:

            def handler(request, payload=payload):
                return httpx.Response(200, json=payload)

            engine, _ = make_engine(handler)
            with self.subTest(payload=payload):
                with self.assertRaises(EngineError):
                    engine.send([ChatMessage("user", "hello")])

    def test_timeout_raises_engine_error_naming_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout("slow", request=request)

        engine, _ = make_engine(handler)

        with self.assertRaises(EngineError) as context:
            engine.send([ChatMessage("user", "hello")])

        self.assertIn("超时", str(context.exception))

    def test_connection_error_raises_engine_error(self):
        def handler(request):
            raise httpx.ConnectError("refused", request=request)

        engine, _ = make_engine(handler)

        with self.assertRaises(EngineError):
            engine.send([ChatMessage("user", "hello")])

    def test_missing_key_raises_before_any_request(self):
        def handler(request):
            raise AssertionError("request must not be sent without a key")

        engine, calls = make_engine(handler, key=None)

        with self.assertRaises(EngineError) as context:
            engine.send([ChatMessage("user", "hello")])

        self.assertIn("未配置 API key", str(context.exception))
        self.assertEqual(calls["count"], 0)

    def test_blank_key_is_treated_as_unconfigured(self):
        def handler(request):
            raise AssertionError("request must not be sent with a blank key")

        engine, calls = make_engine(handler, key="   ")

        with self.assertRaises(EngineError):
            engine.send([ChatMessage("user", "hello")])

        self.assertEqual(calls["count"], 0)

    def test_error_messages_never_contain_key_bytes(self):
        bodies = [
            ("401", httpx.Response(401, text="denied " + FAKE_KEY)),
            ("500", httpx.Response(500, text=FAKE_KEY * 100)),
        ]
        for label, response in bodies:

            def handler(request, response=response):
                return response

            engine, _ = make_engine(handler)
            with self.subTest(status=label):
                with self.assertRaises(EngineError) as context:
                    engine.send([ChatMessage("user", "hello")])
                encoded = str(context.exception).encode("utf-8")
                self.assertNotIn(FAKE_KEY.encode("utf-8"), encoded)

    def test_cancel_token_set_before_send_skips_the_request(self):
        def handler(request):
            raise AssertionError("request must not be sent after cancellation")

        engine, calls = make_engine(handler)

        with self.assertRaises(EngineError) as context:
            engine.send([ChatMessage("user", "hello")], cancel=lambda: True)

        self.assertIn("取消", str(context.exception))
        self.assertEqual(calls["count"], 0)

    def test_cancel_during_request_takes_effect_at_the_boundary(self):
        state = {"cancelled": False}

        def handler(request):
            # The request is already in flight; the token flips mid-request.
            state["cancelled"] = True
            return httpx.Response(200, json=chat_json("late reply"))

        engine, calls = make_engine(handler)

        with self.assertRaises(EngineError) as context:
            engine.send(
                [ChatMessage("user", "hello")],
                cancel=lambda: state["cancelled"],
            )

        message = str(context.exception)
        self.assertIn("请求已取消", message)
        self.assertEqual(calls["count"], 1)
        self.assertNotIn("late reply", message)

    def test_secret_store_error_never_leaks_key_bytes(self):
        class ExplodingStore:
            def get(self, key_name):
                raise RuntimeError(FAKE_KEY)

        engine = OpenAICompatibleEngine(
            base_url=BASE_URL,
            model="test-model",
            secret_store=ExplodingStore(),
            key_name="provider-key",
            timeout_s=5.0,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=chat_json("unreachable"),
                )
            ),
        )

        with self.assertRaises(EngineError) as context:
            engine.send([ChatMessage("user", "hello")])

        message = str(context.exception)
        self.assertIn("RuntimeError", message)
        self.assertNotIn(FAKE_KEY, message)
        self.assertNotIn(FAKE_KEY.encode("utf-8"), message.encode("utf-8"))

    def test_client_factory_is_used_for_requests(self):
        def handler(request):
            return httpx.Response(200, json=chat_json("via factory"))

        created = {"count": 0}

        def factory():
            created["count"] += 1
            return httpx.Client(transport=httpx.MockTransport(handler))

        engine = OpenAICompatibleEngine(
            base_url=BASE_URL,
            model="test-model",
            secret_store=InMemorySecretStore({"provider-key": FAKE_KEY}),
            key_name="provider-key",
            timeout_s=5.0,
            client_factory=factory,
        )

        reply = engine.send([ChatMessage("user", "hello")])

        self.assertEqual(reply.text, "via factory")
        self.assertEqual(created["count"], 1)

    def test_engine_satisfies_the_runtime_protocol(self):
        engine, _ = make_engine(
            lambda request: httpx.Response(200, json=chat_json("ok"))
        )
        self.assertIsInstance(engine, Engine)


if __name__ == "__main__":
    unittest.main()
