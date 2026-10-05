import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from ccfa.watch import main, parse_feed, scan

ATOM = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>urn:arxiv:2401.00001</id>
    <title>First Paper</title>
    <published>2026-10-01T00:00:00Z</published>
    <summary>First summary.</summary>
  </entry>
  <entry>
    <id>urn:arxiv:2401.00002</id>
    <title>Second Paper</title>
    <published>2026-10-02T00:00:00Z</published>
    <summary>Second summary.</summary>
  </entry>
</feed>
"""


class WatchTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.state_path = self.root / "state.json"

    def _fetcher(self, text=ATOM):
        calls = []

        def fetcher(url):
            calls.append(url)
            return text

        fetcher.calls = calls
        return fetcher

    def _state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))


class TestParseFeed(WatchTests):
    def test_parse_feed_reads_atom_fields(self):
        entries = parse_feed(ATOM)

        self.assertEqual(
            entries,
            [
                {
                    "id": "urn:arxiv:2401.00001",
                    "title": "First Paper",
                    "published": "2026-10-01T00:00:00Z",
                    "summary": "First summary.",
                },
                {
                    "id": "urn:arxiv:2401.00002",
                    "title": "Second Paper",
                    "published": "2026-10-02T00:00:00Z",
                    "summary": "Second summary.",
                },
            ],
        )

    def test_parse_feed_skips_entries_missing_id_or_title(self):
        xml = """\
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>good</id><title>Good</title></entry>
  <entry><title>Missing id</title></entry>
  <entry><id>missing-title</id></entry>
</feed>
"""
        self.assertEqual([entry["id"] for entry in parse_feed(xml)], ["good"])

    def test_parse_feed_empty_feed_is_empty(self):
        self.assertEqual(
            parse_feed('<feed xmlns="http://www.w3.org/2005/Atom"></feed>'),
            [],
        )

    def test_parse_feed_bad_xml_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse_feed("<feed><entry>")

    def test_parse_feed_reads_nested_title_and_summary_text(self):
        xml = """\
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>nested</id>
    <title type="xhtml"><div>Hello <b>World</b></div></title>
    <summary type="xhtml"><p>Nested summary</p></summary>
  </entry>
</feed>
"""

        entries = parse_feed(xml)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Hello World")
        self.assertEqual(entries[0]["summary"], "Nested summary")

    def test_parse_feed_separates_block_level_title_text(self):
        xml = """\
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>blocks-title</id>
    <title type="xhtml"><div>Hello</div><div>World</div></title>
  </entry>
</feed>
"""

        self.assertEqual(parse_feed(xml)[0]["title"], "Hello World")

    def test_parse_feed_separates_block_level_summary_text(self):
        xml = """\
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>blocks-summary</id>
    <title>Title</title>
    <summary type="xhtml"><div>First</div><div>Second</div></summary>
  </entry>
</feed>
"""

        self.assertEqual(parse_feed(xml)[0]["summary"], "First Second")


class TestScan(WatchTests):
    def test_first_run_creates_baseline_without_reporting_entries(self):
        fetcher = self._fetcher()

        result = scan(["https://feed"], self.state_path, fetcher=fetcher)

        self.assertTrue(result["baseline"])
        self.assertEqual(result["new"], [])
        self.assertEqual(result["seen_total"], 2)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(
            self._state(),
            {
                "version": 1,
                "seen_ids": ["urn:arxiv:2401.00001", "urn:arxiv:2401.00002"],
            },
        )

    def test_existing_state_reports_only_new_ids(self):
        self.state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "seen_ids": ["urn:arxiv:2401.00001"],
                }
            ),
            encoding="utf-8",
        )

        result = scan(["https://feed"], self.state_path, fetcher=self._fetcher())

        self.assertFalse(result["baseline"])
        self.assertEqual([entry["id"] for entry in result["new"]], ["urn:arxiv:2401.00002"])
        self.assertEqual(result["seen_total"], 2)

    def test_bad_entries_are_skipped_and_counted(self):
        xml = """\
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>good</id><title>Good</title></entry>
  <entry><title>Missing id</title></entry>
  <entry><id>missing-title</id></entry>
</feed>
"""
        result = scan(["https://feed"], self.state_path, fetcher=self._fetcher(xml))

        self.assertEqual(result["seen_total"], 1)
        self.assertEqual(result["skipped"], 2)

    def test_duplicate_urls_are_fetched_once(self):
        fetcher = self._fetcher()

        result = scan(
            ["https://feed", "https://feed"],
            self.state_path,
            fetcher=fetcher,
        )

        self.assertEqual(fetcher.calls, ["https://feed"])
        self.assertEqual(result["seen_total"], 2)

    def test_explicit_baseline_does_not_report_existing_new_ids(self):
        self.state_path.write_text(
            json.dumps({"version": 1, "seen_ids": []}),
            encoding="utf-8",
        )

        result = scan(
            ["https://feed"],
            self.state_path,
            fetcher=self._fetcher(),
            baseline=True,
        )

        self.assertTrue(result["baseline"])
        self.assertEqual(result["new"], [])
        self.assertEqual(result["seen_total"], 2)

    def test_explicit_baseline_merges_with_existing_state(self):
        self.state_path.write_text(
            json.dumps({"version": 1, "seen_ids": ["old"]}),
            encoding="utf-8",
        )

        result = scan(
            ["https://feed"],
            self.state_path,
            fetcher=self._fetcher(),
            baseline=True,
        )

        self.assertTrue(result["baseline"])
        self.assertEqual(result["new"], [])
        self.assertEqual(result["seen_total"], 3)
        self.assertEqual(
            self._state()["seen_ids"],
            ["old", "urn:arxiv:2401.00001", "urn:arxiv:2401.00002"],
        )

    def test_force_resets_state_to_current_feed_ids(self):
        self.state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "seen_ids": ["old", "urn:arxiv:2401.00001"],
                }
            ),
            encoding="utf-8",
        )

        result = scan(
            ["https://feed"],
            self.state_path,
            fetcher=self._fetcher(),
            force=True,
        )

        self.assertTrue(result["baseline"])
        self.assertEqual(result["new"], [])
        self.assertEqual(result["seen_total"], 2)
        self.assertEqual(
            self._state()["seen_ids"],
            ["urn:arxiv:2401.00001", "urn:arxiv:2401.00002"],
        )

    def test_limit_defers_unreported_new_entries(self):
        state = {"version": 1, "seen_ids": []}
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

        first = scan(["https://feed"], self.state_path, fetcher=self._fetcher(), limit=1)
        second = scan(["https://feed"], self.state_path, fetcher=self._fetcher(), limit=50)

        self.assertEqual([entry["id"] for entry in first["new"]], ["urn:arxiv:2401.00001"])
        self.assertEqual([entry["id"] for entry in second["new"]], ["urn:arxiv:2401.00002"])

    def test_network_failure_does_not_advance_state(self):
        self.state_path.write_text(
            json.dumps({"version": 1, "seen_ids": ["old"]}),
            encoding="utf-8",
        )
        before = self.state_path.read_bytes()

        def fetcher(url):
            raise OSError("offline")

        with self.assertRaisesRegex(ValueError, "抓取失败"):
            scan(["https://feed"], self.state_path, fetcher=fetcher)

        self.assertEqual(self.state_path.read_bytes(), before)

    def test_corrupt_state_is_not_overwritten(self):
        for payload in ("{bad json", json.dumps({"version": 2, "seen_ids": []})):
            with self.subTest(payload=payload):
                self.state_path.write_text(payload, encoding="utf-8")
                before = self.state_path.read_bytes()
                with self.assertRaises(ValueError):
                    scan(["https://feed"], self.state_path, fetcher=self._fetcher())
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_state_write_is_atomic_and_leaves_no_tmp(self):
        scan(["https://feed"], self.state_path, fetcher=self._fetcher())

        self.assertTrue(self.state_path.is_file())
        self.assertEqual(list(self.root.glob("state.json.tmp")), [])

    def test_summary_is_truncated_in_reported_entries(self):
        self.state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "seen_ids": ["urn:arxiv:2401.00001"],
                }
            ),
            encoding="utf-8",
        )
        long_summary = "x" * 1200
        xml = ATOM.replace("Second summary.", long_summary)
        fetcher = self._fetcher(xml)

        result = scan(["https://feed"], self.state_path, fetcher=fetcher)

        reported = next(entry for entry in result["new"] if entry["id"].endswith("00002"))
        self.assertEqual(len(reported["summary"]), 500)


class TestMain(WatchTests):
    def test_cli_baseline_prints_json_and_honest_stderr(self):
        stdout = StringIO()
        stderr = StringIO()
        with mock.patch("ccfa.watch._default_fetcher", return_value=ATOM):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    [
                        "watch",
                        "scan",
                        "--state",
                        str(self.state_path),
                        "--url",
                        "https://feed",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout.getvalue())["baseline"])
        self.assertIn("已建立基线 2 条", stderr.getvalue())

    def test_cli_force_reports_rebuilt_count_and_drops_old_ids(self):
        self.state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "seen_ids": ["old", "urn:arxiv:2401.00001"],
                }
            ),
            encoding="utf-8",
        )
        stdout = StringIO()
        stderr = StringIO()
        with mock.patch("ccfa.watch._default_fetcher", return_value=ATOM):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    [
                        "watch",
                        "scan",
                        "--state",
                        str(self.state_path),
                        "--url",
                        "https://feed",
                        "--force",
                    ]
                )

        report = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report["new"], [])
        self.assertEqual(report["seen_total"], 2)
        self.assertNotIn("old", self._state()["seen_ids"])
        self.assertIn("已重建基线 2 条", stderr.getvalue())

    def test_cli_force_recovers_from_corrupt_state(self):
        self.state_path.write_text("{bad json", encoding="utf-8")
        stdout = StringIO()
        stderr = StringIO()
        with mock.patch("ccfa.watch._default_fetcher", return_value=ATOM):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    [
                        "watch",
                        "scan",
                        "--state",
                        str(self.state_path),
                        "--url",
                        "https://feed",
                        "--force",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(
            self._state()["seen_ids"],
            ["urn:arxiv:2401.00001", "urn:arxiv:2401.00002"],
        )
        self.assertIn("已重建基线 2 条", stderr.getvalue())

    def test_cli_network_error_exits_two(self):
        stdout = StringIO()
        stderr = StringIO()
        with mock.patch("ccfa.watch._default_fetcher", side_effect=OSError("offline")):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    [
                        "watch",
                        "scan",
                        "--state",
                        str(self.state_path),
                        "--url",
                        "https://feed",
                    ]
                )
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("工具错误", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
