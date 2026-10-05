import json
import tempfile
import unittest
from pathlib import Path

from ccfa.citation_ledger import (
    VALID_STATUSES,
    LedgerEvidence,
    LedgerRecord,
    load_ledger,
    save_ledger,
)


def _evidence(sha=None):
    return {
        "body_sha256": "sha256:" + (sha or "a" * 64),
        "retrieved_at": "2026-10-04T00:00:00Z",
        "matched_title": "Attention Is All You Need",
        "source": "crossref",
    }

GOOD = {
    "version": 1,
    "entries": {
        "vaswani2017attention": {
            "doi": "10.48550/arxiv.1706.03762",
            "status": "verified",
            "verified_at": "2026-10-03T12:00:00Z",
            "source": "crossref",
            "evidence": _evidence(),
        }
    },
}


def _ledger(payload) -> Path:
    path = Path(tempfile.mkdtemp()) / "citation-ledger.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class TestLoadLedger(unittest.TestCase):
    def test_loads_a_valid_ledger(self):
        records = load_ledger(_ledger(GOOD))
        record = records["vaswani2017attention"]
        self.assertEqual(record.status, "verified")
        self.assertEqual(record.source, "crossref")
        self.assertEqual(record.doi, "10.48550/arxiv.1706.03762")

    def test_doi_is_normalized(self):
        payload = json.loads(json.dumps(GOOD))
        payload["entries"]["vaswani2017attention"]["doi"] = "https://doi.org/10.1/MiXeD"
        records = load_ledger(_ledger(payload))
        self.assertEqual(records["vaswani2017attention"].doi, "10.1/mixed")

    def test_empty_entries_is_valid(self):
        self.assertEqual(load_ledger(_ledger({"version": 1, "entries": {}})), {})

    def test_missing_file_raises(self):
        with self.assertRaises(ValueError):
            load_ledger(Path(tempfile.mkdtemp()) / "nope.json")

    def test_invalid_json_raises(self):
        path = Path(tempfile.mkdtemp()) / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_ledger(path)

    def test_missing_version_raises(self):
        with self.assertRaises(ValueError):
            load_ledger(_ledger({"entries": {}}))

    def test_entries_must_be_a_mapping(self):
        with self.assertRaises(ValueError):
            load_ledger(_ledger({"version": 1, "entries": []}))

    def test_record_must_be_a_mapping(self):
        with self.assertRaises(ValueError):
            load_ledger(_ledger({"version": 1, "entries": {"k": "verified"}}))

    def test_unknown_status_raises(self):
        payload = {"version": 1, "entries": {"k": {"status": "maybe"}}}
        with self.assertRaises(ValueError):
            load_ledger(_ledger(payload))

    def test_non_string_doi_raises_and_names_key(self):
        payload = {"version": 1, "entries": {"k": {"status": "verified", "doi": 10.1}}}
        with self.assertRaises(ValueError) as ctx:
            load_ledger(_ledger(payload))
        self.assertIn("k", str(ctx.exception))

    def test_all_declared_statuses_are_accepted(self):
        for status in VALID_STATUSES:
            with self.subTest(status=status):
                payload = {
                    "version": 1,
                    "entries": {"k": {"status": status, "verified_at": "", "source": ""}},
                }
                self.assertEqual(load_ledger(_ledger(payload))["k"].status, status)

    def test_verified_with_valid_evidence_parses_it(self):
        record = load_ledger(_ledger(GOOD))["vaswani2017attention"]

        self.assertEqual(
            record.evidence.body_sha256,
            "sha256:" + "a" * 64,
        )
        self.assertEqual(record.evidence.source, "crossref")
        self.assertEqual(
            record.evidence.matched_title,
            "Attention Is All You Need",
        )
        self.assertEqual(record.evidence_error, "")

    def test_verified_without_evidence_loads_with_a_reason(self):
        payload = {"version": 1, "entries": {"k": {"status": "verified"}}}

        record = load_ledger(_ledger(payload))["k"]

        self.assertIsNone(record.evidence)
        self.assertIn("evidence", record.evidence_error)

    def test_invalid_body_sha_is_recorded_not_raised(self):
        payload = {
            "version": 1,
            "entries": {
                "k": {
                    "status": "verified",
                    "evidence": _evidence(sha="zz"),
                }
            },
        }

        record = load_ledger(_ledger(payload))["k"]

        self.assertIsNone(record.evidence)
        self.assertIn("body_sha256", record.evidence_error)

    def test_evidence_missing_field_is_recorded_not_raised(self):
        evidence = _evidence()
        del evidence["matched_title"]
        payload = {
            "version": 1,
            "entries": {
                "k": {"status": "verified", "evidence": evidence}
            },
        }

        record = load_ledger(_ledger(payload))["k"]

        self.assertIsNone(record.evidence)
        self.assertIn("matched_title", record.evidence_error)

    def test_non_verified_status_does_not_require_evidence(self):
        payload = {"version": 1, "entries": {"k": {"status": "failed"}}}

        record = load_ledger(_ledger(payload))["k"]

        self.assertIsNone(record.evidence)
        self.assertEqual(record.evidence_error, "")

    def test_save_ledger_round_trips_evidence(self):
        path = _ledger({"version": 1, "entries": {}})
        records = {
            "k": LedgerRecord(
                key="k",
                doi="10.1/x",
                status="verified",
                verified_at="2026-10-04T00:00:00Z",
                source="crossref",
                evidence=LedgerEvidence(
                    body_sha256="sha256:" + "b" * 64,
                    retrieved_at="2026-10-04T00:00:00Z",
                    matched_title="Title",
                    source="crossref",
                ),
            )
        }

        save_ledger(path, records)

        reloaded = load_ledger(path)
        self.assertEqual(reloaded["k"].status, "verified")
        self.assertEqual(
            reloaded["k"].evidence.body_sha256,
            "sha256:" + "b" * 64,
        )

    def test_failed_record_round_trips_detail(self):
        path = _ledger({"version": 1, "entries": {}})
        records = {
            "k": LedgerRecord(
                key="k",
                doi="10.1/x",
                status="failed",
                verified_at="",
                source="crossref",
                detail="doi mismatch",
            )
        }

        save_ledger(path, records)

        self.assertEqual(load_ledger(path)["k"].detail, "doi mismatch")

    def test_legacy_failed_record_without_detail_is_compatible(self):
        payload = {"version": 1, "entries": {"k": {"status": "failed"}}}

        self.assertEqual(load_ledger(_ledger(payload))["k"].detail, "")

    def test_non_string_detail_is_ignored(self):
        payload = {
            "version": 1,
            "entries": {"k": {"status": "failed", "detail": 7}},
        }

        self.assertEqual(load_ledger(_ledger(payload))["k"].detail, "")
