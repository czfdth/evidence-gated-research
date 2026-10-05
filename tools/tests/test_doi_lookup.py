import hashlib
import json
import urllib.error
import unittest
from unittest import mock

from ccfa.doi_lookup import _default_fetch, lookup, title_similarity


def _crossref_body(doi="10.1/x", title="Sample Paper"):
    return json.dumps({"message": {"DOI": doi, "title": [title]}})


def _datacite_body(doi="10.1/x", title="Sample Paper"):
    return json.dumps(
        {"data": {"attributes": {"doi": doi, "titles": [{"title": title}]}}}
    )


def _fetcher(responses):
    calls = []

    def fetch(url, timeout):
        calls.append(url)
        for needle, response in responses.items():
            if needle in url:
                return response
        return (404, "")

    return fetch, calls


class TestLookup(unittest.TestCase):
    def test_crossref_hit_does_not_consult_datacite(self):
        body = _crossref_body()
        fetch, calls = _fetcher({"crossref.org": (200, body)})

        result = lookup("10.1/x", fetch=fetch)

        self.assertTrue(result.found)
        self.assertEqual(result.source, "crossref")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.evidence.source, "crossref")
        self.assertEqual(result.evidence.matched_title, "Sample Paper")
        self.assertEqual(
            result.evidence.body_sha256,
            "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
        )
        self.assertRegex(
            result.evidence.retrieved_at,
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
            r"[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
        )

    def test_datacite_is_tried_when_crossref_misses(self):
        fetch, calls = _fetcher(
            {
                "crossref.org": (404, ""),
                "api.datacite.org": (200, _datacite_body()),
            }
        )

        result = lookup("10.1/x", fetch=fetch)

        self.assertTrue(result.found)
        self.assertEqual(result.source, "datacite")
        self.assertEqual(result.evidence.source, "datacite")
        self.assertEqual(len(calls), 2)

    def test_doi_mismatch_is_not_found(self):
        fetch, _ = _fetcher(
            {"crossref.org": (200, _crossref_body(doi="10.1/other"))}
        )

        result = lookup("10.1/x", fetch=fetch)

        self.assertFalse(result.found)
        self.assertIsNone(result.evidence)
        self.assertEqual(result.detail, "doi mismatch")

    def test_missing_doi_in_body_is_a_mismatch(self):
        body = json.dumps({"message": {"title": ["Sample Paper"]}})
        fetch, _ = _fetcher({"crossref.org": (200, body)})

        result = lookup("10.1/x", fetch=fetch)

        self.assertFalse(result.found)
        self.assertEqual(result.detail, "doi mismatch")

    def test_bad_json_is_not_found_with_detail(self):
        fetch, _ = _fetcher(
            {
                "crossref.org": (200, "not json"),
                "api.datacite.org": (200, "not json"),
            }
        )

        result = lookup("10.1/x", fetch=fetch)

        self.assertFalse(result.found)
        self.assertIn("JSON", result.detail)

    def test_title_mismatch_is_not_found(self):
        fetch, _ = _fetcher(
            {"crossref.org": (200, _crossref_body(title="Cooking With Gas"))}
        )

        result = lookup(
            "10.1/x",
            fetch=fetch,
            expected_title="Attention Is All You Need",
        )

        self.assertFalse(result.found)
        self.assertEqual(result.detail, "title mismatch")
        self.assertIsNone(result.evidence)

    def test_missing_title_is_not_found(self):
        body = json.dumps({"message": {"DOI": "10.1/x", "title": []}})
        fetch, _ = _fetcher({"crossref.org": (200, body)})

        result = lookup("10.1/x", fetch=fetch)

        self.assertFalse(result.found)
        self.assertEqual(result.detail, "title missing")
        self.assertIsNone(result.evidence)

    def test_non_string_title_is_not_found(self):
        body = json.dumps({"message": {"DOI": "10.1/x", "title": [123]}})
        fetch, _ = _fetcher({"crossref.org": (200, body)})

        result = lookup("10.1/x", fetch=fetch)

        self.assertFalse(result.found)
        self.assertEqual(result.detail, "title missing")
        self.assertIsNone(result.evidence)

    def test_title_similarity_boundary_is_around_point_nine(self):
        base = "the quick brown fox jumps over the lazy dog"
        high = base + "z" * 8
        low = base + "z" * 10

        self.assertGreaterEqual(title_similarity(base, high), 0.9)
        self.assertLess(title_similarity(base, low), 0.9)

    def test_title_just_above_threshold_is_found(self):
        base = "the quick brown fox jumps over the lazy dog"
        high = base + "z" * 8
        fetch, _ = _fetcher(
            {"crossref.org": (200, _crossref_body(title=high))}
        )

        result = lookup("10.1/x", fetch=fetch, expected_title=base)

        self.assertTrue(result.found)

    def test_title_just_below_threshold_is_mismatch(self):
        base = "the quick brown fox jumps over the lazy dog"
        low = base + "z" * 10
        fetch, _ = _fetcher(
            {"crossref.org": (200, _crossref_body(title=low))}
        )

        result = lookup("10.1/x", fetch=fetch, expected_title=base)

        self.assertFalse(result.found)
        self.assertEqual(result.detail, "title mismatch")

    def test_evidence_hashes_raw_response_bytes(self):
        raw = _crossref_body().encode("utf-8")
        fetch, _ = _fetcher({"crossref.org": (200, raw)})

        result = lookup("10.1/x", fetch=fetch)

        self.assertTrue(result.found)
        self.assertEqual(
            result.evidence.body_sha256,
            "sha256:" + hashlib.sha256(raw).hexdigest(),
        )

    def test_title_match_tolerates_case_and_punctuation(self):
        fetch, _ = _fetcher(
            {
                "crossref.org": (
                    200,
                    _crossref_body(title="Attention, Is All You Need!"),
                )
            }
        )

        result = lookup(
            "10.1/x",
            fetch=fetch,
            expected_title="attention is all you need",
        )

        self.assertTrue(result.found)
        self.assertEqual(
            result.evidence.matched_title,
            "Attention, Is All You Need!",
        )

    def test_title_similarity_uses_normalized_sequence_ratio(self):
        self.assertEqual(
            title_similarity(
                "Attention Is All You Need",
                "attention is all you need",
            ),
            1.0,
        )
        self.assertLess(
            title_similarity(
                "Attention Is All You Need",
                "Cooking With Gas",
            ),
            0.9,
        )
        self.assertGreaterEqual(
            title_similarity("A Study of X", "A Study of X."),
            0.9,
        )

    def test_both_miss_reports_not_found(self):
        fetch, _ = _fetcher({})
        result = lookup("10.1/x", fetch=fetch)
        self.assertFalse(result.found)
        self.assertIsNone(result.source)
        self.assertIn("404", result.detail)

    def test_network_error_is_reported_not_raised(self):
        def fetch(url, timeout):
            raise OSError("connection reset")

        result = lookup("10.1/x", fetch=fetch)
        self.assertFalse(result.found)
        self.assertIn("connection reset", result.detail)

    def test_doi_is_normalized_before_the_request(self):
        fetch, calls = _fetcher(
            {"crossref.org": (200, _crossref_body(doi="10.1/mixed"))}
        )
        lookup("https://doi.org/10.1/MiXeD", fetch=fetch)
        self.assertIn("10.1%2Fmixed", calls[0])

    def test_empty_doi_is_not_found_without_a_request(self):
        fetch, calls = _fetcher({"crossref.org": (200, _crossref_body())})
        result = lookup("", fetch=fetch)
        self.assertFalse(result.found)
        self.assertEqual(calls, [])

    def test_url_uses_the_crossref_endpoint(self):
        fetch, calls = _fetcher({"crossref.org": (200, _crossref_body())})
        lookup("10.1/x", fetch=fetch)
        self.assertTrue(calls[0].startswith("https://api.crossref.org/works/"))


class TestDefaultFetch(unittest.TestCase):
    def test_http_error_returns_bytes_body(self):
        error = urllib.error.HTTPError(
            "https://api.crossref.org/works/10.1%2Fx",
            404,
            "Not Found",
            None,
            None,
        )

        with mock.patch("urllib.request.urlopen", side_effect=error):
            status, body = _default_fetch("https://example.test", 1.0)

        self.assertEqual(status, 404)
        self.assertIsInstance(body, bytes)
        self.assertEqual(body, b"")

    def test_success_returns_raw_bytes(self):
        class FakeResponse:
            status = 200

            def read(self):
                return b'{"message": {"DOI": "10.1/x"}}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with mock.patch(
            "urllib.request.urlopen",
            return_value=FakeResponse(),
        ):
            status, body = _default_fetch("https://example.test", 1.0)

        self.assertEqual(status, 200)
        self.assertIsInstance(body, bytes)
        self.assertEqual(body, b'{"message": {"DOI": "10.1/x"}}')


if __name__ == "__main__":
    unittest.main()
