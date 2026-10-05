import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from ccfa_core.http_tools import (
    HttpToolRegistry,
    load_registry,
)
from ccfa_core.tools_bridge import ToolBridge


VALID = """
version: 1
tools:
  - name: arxiv_search
    description: "Search arXiv for a query."
    method: GET
    url: "https://export.arxiv.org/api/query"
    risk: read
    timeout_s: 20
    query:
      search_query: "{search_query}"
    parameters:
      type: object
      properties:
        search_query: {type: string}
      required: [search_query]
      additionalProperties: false
"""


class _FakeResponse:
    def __init__(self, *, status=200, headers=None, chunks=(b'{"ok": true}',)):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks
        self.chunk_size = None
        self.iterated = False

    def iter_bytes(self, chunk_size=None):
        self.iterated = True
        self.chunk_size = chunk_size
        for chunk in self._chunks:
            yield chunk


class _FakeStream:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self._response

    def __exit__(self, *exc):
        return False


class _FakeClient:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, method, url, **kwargs):
        self.request = (method, url, kwargs)
        return _FakeStream(self._response)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.path = self.root / "http-tools.yaml"

    def _write(self, text):
        self.path.write_text(text, encoding="utf-8")

    def _load(self, text, **kwargs):
        self._write(text)
        return load_registry(self.path, **kwargs)

    @staticmethod
    def _codes(issues):
        return sorted(issue.code for issue in issues)

    def test_missing_file_reports_registry_missing(self):
        specs, issues = load_registry(self.path)

        self.assertEqual(specs, [])
        self.assertEqual(self._codes(issues), ["registry-missing"])

    def test_empty_registry_is_valid(self):
        specs, issues = self._load("version: 1\ntools: []\n")

        self.assertEqual(specs, [])
        self.assertEqual(issues, [])

    def test_loads_a_valid_registry(self):
        specs, issues = self._load(VALID)

        self.assertEqual(issues, [])
        self.assertEqual([spec.name for spec in specs], ["arxiv_search"])
        self.assertEqual(specs[0].risk, "read")

    def test_duplicate_names_are_rejected(self):
        text = VALID + VALID.split("tools:", 1)[1]
        specs, issues = self._load(text)

        self.assertEqual(self._codes(issues), ["registry-duplicate-name"])
        self.assertEqual([spec.name for spec in specs], [])

    def test_name_collision_with_a_builtin_is_rejected(self):
        text = VALID.replace("arxiv_search", "library_search")

        specs, issues = self._load(text, reserved_names=("library_search",))

        self.assertEqual(self._codes(issues), ["registry-name-conflict"])
        self.assertEqual(specs, [])

    def test_invalid_name_is_rejected(self):
        text = VALID.replace("arxiv_search", "Bad-Name")

        _specs, issues = self._load(text)

        self.assertEqual(self._codes(issues), ["registry-invalid-name"])

    def test_plain_http_is_rejected_without_opt_in(self):
        text = VALID.replace("https://", "http://")

        _specs, issues = self._load(text)

        self.assertEqual(self._codes(issues), ["registry-insecure-url"])

    def test_plain_http_is_allowed_with_opt_in(self):
        text = VALID.replace("https://", "http://").replace(
            "risk: read", "risk: read\n    allow_http: true"
        )

        specs, issues = self._load(text)

        self.assertEqual(issues, [])
        self.assertEqual(len(specs), 1)

    def test_unknown_placeholder_is_rejected(self):
        text = VALID.replace('"{search_query}"', '"{missing}"')

        _specs, issues = self._load(text)

        self.assertEqual(self._codes(issues), ["registry-unknown-placeholder"])

    def test_placeholder_must_be_declared_in_parameters(self):
        text = VALID.replace(
            "        search_query: {type: string}\n",
            "        other_field: {type: string}\n",
        ).replace("      required: [search_query]\n", "      required: [other_field]\n")

        _specs, issues = self._load(text)

        self.assertEqual(self._codes(issues), ["registry-unknown-placeholder"])

    def test_sensitive_header_requires_a_secret_reference(self):
        text = VALID.replace(
            "    query:\n",
            '    headers:\n      Authorization: "Bearer literal"\n'
            "    query:\n",
        )

        _specs, issues = self._load(text)

        self.assertEqual(self._codes(issues), ["registry-literal-secret"])

    def test_sensitive_header_may_reference_a_secret(self):
        text = VALID.replace(
            "    query:\n",
            "    headers:\n      Authorization: \"secret:arxiv-key\"\n"
            "    query:\n",
        )

        specs, issues = self._load(text)

        self.assertEqual(issues, [])
        self.assertEqual(specs[0].headers["Authorization"], "secret:arxiv-key")

    def test_sensitive_header_with_surrounding_whitespace_is_rejected(self):
        text = VALID.replace(
            "    query:\n",
            '    headers:\n      " Authorization ": "Bearer literal"\n'
            "    query:\n",
        )

        _specs, issues = self._load(text)

        self.assertEqual(self._codes(issues), ["registry-literal-secret"])

    def test_secret_reference_may_not_contain_a_placeholder(self):
        text = VALID.replace(
            "    query:\n",
            '    headers:\n      Authorization: "secret:{key_name}"\n'
            "    query:\n",
        )

        _specs, issues = self._load(text)

        self.assertIn("registry-invalid-field", self._codes(issues))

    def test_secret_reference_requires_a_key_name(self):
        text = VALID.replace(
            "    query:\n",
            '    headers:\n      Authorization: "secret:   "\n'
            "    query:\n",
        )

        _specs, issues = self._load(text)

        self.assertEqual(self._codes(issues), ["registry-invalid-field"])

    def test_common_credential_header_names_require_a_secret(self):
        for header in (
            "X-Api-Token",
            "Token",
            "apikey",
            "X-Access-Token",
            "X-Session-Id",
            "X-Session-Cookie",
        ):
            with self.subTest(header=header):
                text = VALID.replace(
                    "    query:\n",
                    f'    headers:\n      "{header}": "literal-value"\n'
                    "    query:\n",
                )

                _specs, issues = self._load(text)

                self.assertEqual(
                    self._codes(issues), ["registry-literal-secret"]
                )

    def test_non_credential_header_may_hold_a_literal(self):
        text = VALID.replace(
            "    query:\n",
            '    headers:\n      Accept: "application/json"\n'
            "    query:\n",
        )

        specs, issues = self._load(text)

        self.assertEqual(issues, [])
        self.assertEqual(
            specs[0].headers["Accept"], "application/json"
        )

    def test_secret_reference_with_an_empty_key_name_is_rejected(self):
        text = VALID.replace(
            "    query:\n",
            '    headers:\n      Authorization: "secret:"\n'
            "    query:\n",
        )

        _specs, issues = self._load(text)

        self.assertEqual(self._codes(issues), ["registry-invalid-field"])

    def test_non_finite_timeout_is_rejected(self):
        text = VALID.replace("timeout_s: 20", "timeout_s: .nan")

        _specs, issues = self._load(text)

        self.assertEqual(self._codes(issues), ["registry-invalid-timeout"])

    def test_invalid_method_and_risk_are_rejected(self):
        text = VALID.replace("method: GET", "method: DELETE").replace(
            "risk: read", "risk: admin"
        )

        _specs, issues = self._load(text)

        self.assertIn("registry-invalid-method", self._codes(issues))
        self.assertIn("registry-invalid-risk", self._codes(issues))

    def test_invalid_parameters_schema_is_rejected(self):
        text = VALID.replace("      type: object\n", '      type: "not-an-object"\n')

        _specs, issues = self._load(text)

        self.assertEqual(self._codes(issues), ["registry-invalid-schema"])


class RegistryExecutionTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        path = self.root / "http-tools.yaml"
        path.write_text(VALID, encoding="utf-8")
        self.specs, issues = load_registry(path)
        assert issues == []
        self.requests = []

    def _transport(self, response):
        def handler(request):
            self.requests.append(request)
            return response

        return httpx.MockTransport(handler)

    def _registry(self, response, *, secret=None):
        return HttpToolRegistry(
            self.specs,
            resolve_secret=(lambda name: secret if name == "arxiv-key" else None),
            transport=self._transport(response),
        )

    def test_execute_renders_the_query_and_returns_json(self):
        registry = self._registry(
            httpx.Response(200, json={"hits": 3}),
        )

        result = registry.execute("arxiv_search", {"search_query": "rag"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], {"status": 200, "json": {"hits": 3}})
        self.assertEqual(
            str(self.requests[0].url),
            "https://export.arxiv.org/api/query?search_query=rag",
        )

    def test_execute_returns_text_when_the_body_is_not_json(self):
        registry = self._registry(
            httpx.Response(200, text="plain body"),
        )

        result = registry.execute("arxiv_search", {"search_query": "rag"})

        self.assertEqual(result["result"]["text"], "plain body")

    def test_non_2xx_is_an_error(self):
        registry = self._registry(httpx.Response(503, text="nope"))

        result = registry.execute("arxiv_search", {"search_query": "rag"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "http-status")
        self.assertIn("503", result["error"]["message"])

    def test_network_failure_is_reported_without_a_traceback(self):
        def handler(request):
            raise httpx.ConnectError("cannot connect")

        path = self.root / "with-secret.yaml"
        path.write_text(
            VALID.replace(
                "    query:\n",
                "    headers:\n      Authorization: \"secret:arxiv-key\"\n"
                "    query:\n",
            ),
            encoding="utf-8",
        )
        specs, issues = load_registry(path)
        assert issues == []
        registry = HttpToolRegistry(
            specs,
            resolve_secret=lambda name: "s3cret",
            transport=httpx.MockTransport(handler),
        )

        result = registry.execute("arxiv_search", {"search_query": "rag"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "http-error")
        self.assertNotIn("s3cret", json.dumps(result))

    def test_invalid_url_value_is_reported_without_echoing_it(self):
        path = self.root / "url-param.yaml"
        path.write_text(
            VALID.replace(
                'url: "https://export.arxiv.org/api/query"',
                'url: "https://example.com:{search_query}"',
            ).replace("    query:\n      search_query: \"{search_query}\"\n", ""),
            encoding="utf-8",
        )
        specs, issues = load_registry(path)
        assert issues == []

        def handler(request):  # pragma: no cover - must not be reached
            raise AssertionError("request should not be sent")

        registry = HttpToolRegistry(
            specs,
            transport=httpx.MockTransport(handler),
        )

        result = registry.execute(
            "arxiv_search", {"search_query": "sk-SECRET-VALUE"}
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "http-error")
        self.assertNotIn("sk-SECRET-VALUE", json.dumps(result))

    def test_large_response_body_is_bounded(self):
        registry = self._registry(
            httpx.Response(200, json={"data": "x" * 500_000}),
        )

        result = registry.execute("arxiv_search", {"search_query": "rag"})

        self.assertTrue(result["ok"])
        self.assertLess(len(json.dumps(result)), 100_000)

    def test_response_stream_uses_a_bounded_chunk_size(self):
        response = _FakeResponse(chunks=(b"x" * 300_000,))
        registry = HttpToolRegistry(self.specs, transport=None)

        with mock.patch.object(
            httpx, "Client", lambda **kwargs: _FakeClient(response)
        ):
            result = registry.execute("arxiv_search", {"search_query": "rag"})

        self.assertTrue(result["ok"])
        self.assertIsNotNone(response.chunk_size)
        self.assertLessEqual(response.chunk_size, 65536)
        self.assertLess(len(json.dumps(result)), 300_000)

    def test_compressed_response_is_refused_by_default(self):
        response = _FakeResponse(headers={"content-encoding": "gzip"})
        registry = HttpToolRegistry(self.specs, transport=None)

        with mock.patch.object(
            httpx, "Client", lambda **kwargs: _FakeClient(response)
        ):
            result = registry.execute("arxiv_search", {"search_query": "rag"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "http-encoding")
        self.assertFalse(response.iterated)

    def test_compressed_response_allowed_with_opt_in(self):
        path = self.root / "compressed.yaml"
        path.write_text(
            VALID.replace("risk: read", "risk: read\n    allow_compressed: true"),
            encoding="utf-8",
        )
        specs, issues = load_registry(path)
        assert issues == []
        response = _FakeResponse(headers={"content-encoding": "gzip"})
        registry = HttpToolRegistry(specs, transport=None)

        with mock.patch.object(
            httpx, "Client", lambda **kwargs: _FakeClient(response)
        ):
            result = registry.execute("arxiv_search", {"search_query": "rag"})

        self.assertTrue(result["ok"], result)
        self.assertTrue(response.iterated)

    def test_requests_ask_for_an_uncompressed_body(self):
        response = _FakeResponse()
        client = _FakeClient(response)
        registry = HttpToolRegistry(self.specs, transport=None)

        with mock.patch.object(httpx, "Client", lambda **kwargs: client):
            registry.execute("arxiv_search", {"search_query": "rag"})

        self.assertEqual(
            client.request[2]["headers"]["Accept-Encoding"], "identity"
        )

    def test_resolver_exception_is_sanitised(self):
        path = self.root / "with-secret.yaml"
        path.write_text(
            VALID.replace(
                "    query:\n",
                "    headers:\n      Authorization: \"secret:arxiv-key\"\n"
                "    query:\n",
            ),
            encoding="utf-8",
        )
        specs, issues = load_registry(path)
        assert issues == []

        def resolve_secret(name):
            raise RuntimeError("keyring exploded with sk-SECRET-VALUE")

        registry = HttpToolRegistry(
            specs,
            resolve_secret=resolve_secret,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={})
            ),
        )

        result = registry.execute("arxiv_search", {"search_query": "rag"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "http-error")
        self.assertNotIn("sk-SECRET-VALUE", json.dumps(result))
        self.assertNotIn("keyring exploded", json.dumps(result))

    def test_every_non_identity_content_encoding_is_refused(self):
        for encoding in (
            "gzip",
            "br",
            "zstd",
            "deflate",
            "GZip",
            "gzip, br",
            " gzip ",
        ):
            with self.subTest(encoding=encoding):
                response = _FakeResponse(
                    headers={"content-encoding": encoding}
                )
                registry = HttpToolRegistry(self.specs, transport=None)

                with mock.patch.object(
                    httpx, "Client", lambda **kwargs: _FakeClient(response)
                ):
                    result = registry.execute(
                        "arxiv_search", {"search_query": "rag"}
                    )

                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "http-encoding")
                self.assertFalse(response.iterated)

    def test_identity_content_encoding_is_read(self):
        response = _FakeResponse(headers={"content-encoding": "identity"})
        registry = HttpToolRegistry(self.specs, transport=None)

        with mock.patch.object(
            httpx, "Client", lambda **kwargs: _FakeClient(response)
        ):
            result = registry.execute("arxiv_search", {"search_query": "rag"})

        self.assertTrue(result["ok"], result)
        self.assertTrue(response.iterated)

    def test_missing_secret_is_an_error_and_is_not_echoed(self):
        path = self.root / "with-secret.yaml"
        path.write_text(
            VALID.replace(
                "    query:\n",
                "    headers:\n      Authorization: \"secret:arxiv-key\"\n"
                "    query:\n",
            ),
            encoding="utf-8",
        )
        specs, issues = load_registry(path)
        assert issues == []
        registry = HttpToolRegistry(
            specs,
            resolve_secret=lambda name: None,
            transport=self._transport(httpx.Response(200, json={})),
        )

        result = registry.execute("arxiv_search", {"search_query": "rag"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "missing-secret")
        self.assertEqual(self.requests, [])

    def test_secret_header_is_sent_but_never_returned(self):
        path = self.root / "with-secret.yaml"
        path.write_text(
            VALID.replace(
                "    query:\n",
                "    headers:\n      Authorization: \"secret:arxiv-key\"\n"
                "    query:\n",
            ),
            encoding="utf-8",
        )
        specs, issues = load_registry(path)
        assert issues == []
        registry = HttpToolRegistry(
            specs,
            resolve_secret=lambda name: "sk-test-123",
            transport=self._transport(httpx.Response(200, json={"ok": True})),
        )

        result = registry.execute("arxiv_search", {"search_query": "rag"})

        self.assertEqual(
            self.requests[0].headers["authorization"], "sk-test-123"
        )
        self.assertNotIn("sk-test-123", json.dumps(result))


class BridgeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "ccfa.yaml").write_text(
            "target_venue:\n  mode: conference\n"
            "stage:\n  current: idea\n",
            encoding="utf-8",
        )
        path = self.root / "http-tools.yaml"
        path.write_text(VALID, encoding="utf-8")
        self.specs, issues = load_registry(path)
        assert issues == []
        self.requests = []

    def _registry(self):
        def handler(request):
            self.requests.append(request)
            return httpx.Response(200, json={"ok": True})

        return HttpToolRegistry(
            self.specs,
            resolve_secret=lambda name: "s3cret",
            transport=httpx.MockTransport(handler),
        )

    def test_bridge_exposes_and_runs_a_registered_http_tool(self):
        bridge = ToolBridge(self.root, http_tools=self._registry())

        names = [tool["function"]["name"] for tool in bridge.openai_tools()]
        self.assertIn("arxiv_search", names)

        result = bridge.execute("arxiv_search", {"search_query": "rag"})

        self.assertTrue(result["ok"], result)
        self.assertEqual(
            str(self.requests[0].url),
            "https://export.arxiv.org/api/query?search_query=rag",
        )

    def test_bridge_validates_http_tool_arguments(self):
        bridge = ToolBridge(self.root, http_tools=self._registry())

        result = bridge.execute("arxiv_search", {"nope": 1})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid-arguments")
        self.assertEqual(self.requests, [])

    def test_write_http_tool_requires_confirmation(self):
        path = self.root / "write.yaml"
        path.write_text(
            VALID.replace("risk: read", "risk: write").replace(
                "method: GET", "method: POST"
            ).replace('    query:\n', "    json:\n      q: \"{search_query}\"\n"),
            encoding="utf-8",
        )
        specs, issues = load_registry(path)
        assert issues == []
        bridge = ToolBridge(
            self.root,
            http_tools=HttpToolRegistry(
                specs,
                resolve_secret=lambda name: "s3cret",
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json={"ok": True})
                ),
            ),
        )

        declined = bridge.execute("arxiv_search", {"search_query": "rag"})

        self.assertEqual(declined["error"]["code"], "user-declined")

    def test_write_http_tool_runs_after_confirmation(self):
        path = self.root / "write.yaml"
        path.write_text(
            VALID.replace("risk: read", "risk: write").replace(
                "method: GET", "method: POST"
            ).replace('    query:\n', "    json:\n      q: \"{search_query}\"\n"),
            encoding="utf-8",
        )
        specs, issues = load_registry(path)
        assert issues == []
        calls = []
        bridge = ToolBridge(
            self.root,
            http_tools=HttpToolRegistry(
                specs,
                resolve_secret=lambda name: "s3cret",
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json={"ok": True})
                ),
            ),
            confirm_write=lambda name, args: calls.append(name) or True,
        )

        result = bridge.execute("arxiv_search", {"search_query": "rag"})

        self.assertTrue(result["ok"], result)
        self.assertEqual(calls, ["arxiv_search"])


if __name__ == "__main__":
    unittest.main()
