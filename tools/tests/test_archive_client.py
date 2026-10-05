import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ccfa.archive_client as archive
from ccfa.archive_client import (
    ArchiveError,
    Response,
    resolve_host,
    validate_orcid,
    zenodo_deposit,
)


class ResolveHostTests(unittest.TestCase):
    def test_valid_system_answer_is_used_without_doh(self):
        def doh(host):  # pragma: no cover - must not be called
            raise AssertionError("DoH consulted despite a usable answer")

        addresses = resolve_host(
            "zenodo.org",
            system_lookup=lambda host: ["188.184.103.118"],
            doh_lookup=doh,
        )

        self.assertEqual(addresses, ["188.184.103.118"])

    def test_sinkhole_answer_falls_back_to_doh(self):
        # The real resolver answers 0.0.0.0/:: for zenodo.org on this host.
        def system(host):
            return []

        addresses = resolve_host(
            "zenodo.org",
            system_lookup=system,
            doh_lookup=lambda host: ["137.138.52.235"],
        )

        self.assertEqual(addresses, ["137.138.52.235"])

    def test_system_lookup_drops_sinkhole_addresses(self):
        infos = [
            (2, 1, 6, "", ("0.0.0.0", 443)),
            (2, 1, 6, "", ("::", 443)),
            (2, 1, 6, "", ("137.138.52.235", 443)),
        ]
        with mock.patch.object(archive.socket, "getaddrinfo", return_value=infos):
            self.assertEqual(archive._system_lookup("zenodo.org"), ["137.138.52.235"])

    def test_doh_uses_only_a_records(self):
        payload = json.dumps(
            {
                "Answer": [
                    {"type": 5, "data": "alias.example"},
                    {"type": 1, "data": "137.138.52.235"},
                ]
            }
        ).encode()

        addresses = archive._doh_lookup("zenodo.org", fetch=lambda url: payload)

        self.assertEqual(addresses, ["137.138.52.235"])


class OrcidTests(unittest.TestCase):
    def test_known_valid_orcid_passes(self):
        ok, _detail = validate_orcid("0000-0002-1825-0097")
        self.assertTrue(ok)

    def test_bad_check_digit_fails(self):
        ok, detail = validate_orcid("0000-0002-1825-0098")
        self.assertFalse(ok)
        self.assertIn("校验位", detail)

    def test_malformed_orcid_fails(self):
        for value in ("", "1234", "0000-0002-1825-00X7", "abcd-0002-1825-0097"):
            with self.subTest(value=value):
                ok, _detail = validate_orcid(value)
                self.assertFalse(ok)

    def test_lowercase_and_spacing_is_normalised(self):
        ok, _detail = validate_orcid(" 0000-0002-1825-0097 ")
        self.assertTrue(ok)


class ZenodoDepositTests(unittest.TestCase):
    def _draft_payload(self, record_id="1234"):
        return {
            "id": record_id,
            "links": {
                "files": "https://zenodo.org/api/records/1234/files",
                "self_html": "https://zenodo.org/records/1234",
            },
        }

    def test_draft_upload_without_publish_has_no_doi(self):
        calls = []

        def http(method, url, **kwargs):
            calls.append((method, url))
            if method == "POST" and url.endswith("/api/records"):
                return Response(201, json.dumps(self._draft_payload()).encode(), url)
            if method == "PUT":
                return Response(201, b"{}", url)
            raise AssertionError(f"unexpected call {method} {url}")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "artifact.zip"
            source.write_bytes(b"payload")
            result = zenodo_deposit(
                {"title": "t"},
                [source],
                token="secret",
                http=http,
            )

        self.assertEqual(result.status, "draft")
        self.assertIsNone(result.doi)
        self.assertEqual(result.files, ["artifact.zip"])
        self.assertIn("未发布", result.detail)

    def test_publish_requires_a_doi_in_the_response(self):
        def http(method, url, **kwargs):
            if method == "POST" and url.endswith("/api/records"):
                return Response(201, json.dumps(self._draft_payload()).encode(), url)
            if method == "PUT":
                return Response(201, b"{}", url)
            return Response(202, b"{}", url)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "artifact.zip"
            source.write_bytes(b"payload")
            with self.assertRaises(ArchiveError):
                zenodo_deposit(
                    {"title": "t"},
                    [source],
                    token="secret",
                    publish=True,
                    http=http,
                )

    def test_published_record_reports_the_doi(self):
        def http(method, url, **kwargs):
            if method == "POST" and url.endswith("/api/records"):
                return Response(201, json.dumps(self._draft_payload()).encode(), url)
            if method == "PUT":
                return Response(201, b"{}", url)
            return Response(
                202,
                json.dumps(
                    {
                        "doi": "10.5281/zenodo.1234",
                        "links": {"self_html": "https://zenodo.org/records/1234"},
                    }
                ).encode(),
                url,
            )

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "artifact.zip"
            source.write_bytes(b"payload")
            result = zenodo_deposit(
                {"title": "t"},
                [source],
                token="secret",
                publish=True,
                http=http,
            )

        self.assertEqual(result.status, "published")
        self.assertEqual(result.doi, "10.5281/zenodo.1234")

    def test_missing_record_id_is_an_error(self):
        def http(method, url, **kwargs):
            return Response(201, b'{"links": {}}', url)

        with self.assertRaises(ArchiveError):
            zenodo_deposit({"title": "t"}, [], token="secret", http=http)

    def test_missing_bucket_link_is_an_error(self):
        def http(method, url, **kwargs):
            return Response(201, b'{"id": "1234"}', url)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "f.zip"
            source.write_bytes(b"x")
            with self.assertRaises(ArchiveError):
                zenodo_deposit({"title": "t"}, [source], token="secret", http=http)

    def test_absent_local_file_is_an_error(self):
        def http(method, url, **kwargs):
            return Response(201, json.dumps(self._draft_payload()).encode(), url)

        with self.assertRaises(ArchiveError):
            zenodo_deposit(
                {"title": "t"},
                [Path("does-not-exist.bin")],
                token="secret",
                http=http,
            )

    def test_token_is_passed_but_never_returned(self):
        seen = {}

        def http(method, url, **kwargs):
            seen["token"] = kwargs.get("token")
            if method == "POST" and url.endswith("/api/records"):
                return Response(201, json.dumps(self._draft_payload()).encode(), url)
            return Response(201, b"{}", url)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "f.zip"
            source.write_bytes(b"x")
            result = zenodo_deposit({"title": "t"}, [source], token="secret", http=http)

        self.assertEqual(seen["token"], "secret")
        self.assertNotIn("secret", json.dumps(result.as_dict()))


class RequestTests(unittest.TestCase):
    def test_request_pins_the_resolved_address_and_sets_bearer(self):
        captured = {}

        class FakeConnection:
            def __init__(self, host, address, *, timeout):
                captured["host"] = host
                captured["address"] = address

            def request(self, method, path, body=None, headers=None):
                captured["headers"] = headers
                captured["path"] = path

            def getresponse(self):
                return mock.Mock(status=200, read=lambda: b"{}")

            def close(self):
                pass

        with mock.patch.object(archive, "_PinnedHTTPSConnection", FakeConnection):
            response = archive.request(
                "GET",
                "https://zenodo.org/api/records?size=1",
                token="tok",
                host_addresses=lambda host: ["137.138.52.235"],
            )

        self.assertEqual(response.status, 200)
        self.assertEqual(captured["host"], "zenodo.org")
        self.assertEqual(captured["address"], "137.138.52.235")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(captured["path"], "/api/records?size=1")

    def test_request_without_addresses_is_an_error(self):
        with self.assertRaises(ArchiveError):
            archive.request(
                "GET",
                "https://zenodo.org/api/records",
                host_addresses=lambda host: [],
            )


class ProbeTests(unittest.TestCase):
    def test_probe_marks_a_failing_provider_unreachable(self):
        def http(method, url, **kwargs):
            if "zenodo" in url:
                return Response(200, b"{}", url)
            raise ArchiveError("boom")

        results = archive.probe(
            http=http,
            resolver=lambda host: ["127.0.0.1"],
        )

        self.assertTrue(results["zenodo"]["reachable"])
        self.assertFalse(results["osf"]["reachable"])
        self.assertIn("error", results["osf"])


class RecordResultTests(unittest.TestCase):
    def test_result_is_appended_to_the_archive_ledger(self):
        from ccfa.archive_client import DepositResult, record_result

        result = DepositResult(
            provider="zenodo",
            record_id="1234",
            doi="10.5281/zenodo.1234",
            status="published",
            files=["artifact.zip"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = record_result(result, Path(tmp))
            self.assertTrue(path.is_file())
            import yaml

            payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertEqual(len(payload["records"]), 1)
        self.assertEqual(payload["records"][0]["doi"], "10.5281/zenodo.1234")


if __name__ == "__main__":
    unittest.main()
