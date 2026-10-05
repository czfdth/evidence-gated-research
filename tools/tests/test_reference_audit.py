import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa import reference_audit


PINNED = "a" * 40
LATEST = "b" * 40


class _Response:
    status = 200

    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


class ReferenceAuditTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "source.md").write_text("# source\n", encoding="utf-8")
        (self.root / "docs" / "reference-registry.yaml").write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "projects": [
                        {
                            "id": "demo",
                            "repository": "owner/demo",
                            "pinned_commit": PINNED,
                            "source_doc": "docs/source.md",
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def test_offline_audit_validates_registry_without_fetching(self):
        report = reference_audit.audit(self.root, offline=True)

        self.assertEqual(report["problems"], [])
        self.assertFalse(report["projects"][0]["checked"])

    def test_stale_pin_is_a_problem(self):
        report = reference_audit.audit(
            self.root,
            fetch=lambda repository, token=None: LATEST,
        )

        self.assertIn(
            "reference-audit-stale",
            [problem.code for problem in report["problems"]],
        )

    def test_matching_pin_is_clean(self):
        report = reference_audit.audit(
            self.root,
            fetch=lambda repository, token=None: PINNED,
        )

        self.assertEqual(report["problems"], [])
        self.assertTrue(report["projects"][0]["checked"])

    def test_fetch_latest_commit_parses_github_response(self):
        def opener(request, timeout):
            self.assertIn("owner/demo/commits", request.full_url)
            return _Response([{"sha": LATEST}])

        sha = reference_audit.fetch_latest_commit("owner/demo", opener=opener)

        self.assertEqual(sha, LATEST)

    def test_invalid_sha_is_registry_problem(self):
        path = self.root / "docs" / "reference-registry.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        payload["projects"][0]["pinned_commit"] = "short"
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

        _projects, problems = reference_audit.load_registry(self.root)

        self.assertIn(
            "reference-registry-invalid",
            [problem.code for problem in problems],
        )


if __name__ == "__main__":
    unittest.main()
