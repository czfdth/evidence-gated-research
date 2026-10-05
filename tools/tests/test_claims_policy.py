import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.claims_policy import (
    claims_coverage_report,
    load_policy,
    scan_claims,
)


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.manuscript = self.root / "manuscript"
        self.manuscript.mkdir()
        self.main = self.manuscript / "main.tex"
        self.policy_path = self.root / "data" / "claims.yaml"
        self.write_policy()

    def write_policy(self, **overrides):
        payload = {
            "version": 1,
            "protected_sections": ["abstract"],
            "waivers": [],
        }
        payload.update(overrides)
        self.policy_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def write_main(self, body: str):
        self.main.write_text(body, encoding="utf-8")

    def load_and_scan(self):
        policy, policy_problems = load_policy(self.root)
        self.assertIsNotNone(policy)
        problems, advisories, counts = scan_claims(
            self.manuscript,
            policy,
            paper_root=self.root,
        )
        problems = list(policy_problems) + problems
        return problems, advisories, counts

    @staticmethod
    def codes(items):
        return sorted(item.code for item in items)


class TestScanClaims(BaseCase):
    def test_untagged_number_in_abstract_is_problem(self):
        self.write_main(
            "\\begin{abstract}\n"
            "Coding 43 works.\n"
            "\\end{abstract}\n"
        )

        problems, advisories, counts = self.load_and_scan()

        self.assertEqual(self.codes(problems), ["protected-untagged-number"])
        self.assertEqual(advisories, [])
        self.assertIn("43", problems[0].message)
        self.assertEqual(problems[0].line, 2)
        self.assertEqual(
            counts,
            {"protected_total": 1, "bound": 0, "waived": 0, "unbound": 1},
        )

    def test_bound_number_in_abstract_is_clean(self):
        self.write_main(
            "\\begin{abstract}\n"
            "\\dataval{stats.json:rows}{43} works.\n"
            "\\end{abstract}\n"
        )

        problems, advisories, counts = self.load_and_scan()

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])
        self.assertEqual(
            counts,
            {"protected_total": 1, "bound": 1, "waived": 0, "unbound": 0},
        )

    def test_waiver_is_advisory_and_keeps_audit_fields(self):
        self.write_main(
            "\\begin{abstract}\n"
            "Coding 43 works.\n"
            "\\end{abstract}\n"
        )
        self.write_policy(
            waivers=[
                {
                    "file": "manuscript/main.tex",
                    "line_text": "Coding 43 works.",
                    "reason": "protocol count",
                    "date": "2026-10-04",
                    "author": "Alice",
                }
            ]
        )

        problems, advisories, counts = self.load_and_scan()

        self.assertEqual(problems, [])
        self.assertEqual(self.codes(advisories), ["waived-number"])
        self.assertIn("protocol count", advisories[0].message)
        self.assertIn("2026-10-04", advisories[0].message)
        self.assertIn("Alice", advisories[0].message)
        self.assertIn("43", advisories[0].message)
        self.assertEqual(
            counts,
            {"protected_total": 1, "bound": 0, "waived": 1, "unbound": 0},
        )

    def test_nonprotected_number_remains_advisory(self):
        self.write_policy(protected_sections=["results"])
        self.write_main(
            "\\section{Introduction}\n"
            "Coding 43 works.\n"
            "\\section{Results}\n"
            "\\dataval{stats.json:rows}{43} works.\n"
        )

        problems, advisories, counts = self.load_and_scan()

        self.assertEqual(problems, [])
        self.assertEqual(self.codes(advisories), ["untagged-number"])
        self.assertEqual(advisories[0].line, 2)
        self.assertEqual(counts["unbound"], 0)

    def test_bad_waiver_is_a_problem_and_scan_continues(self):
        self.write_main(
            "\\begin{abstract}\n"
            "Coding 43 works.\n"
            "\\end{abstract}\n"
        )
        self.write_policy(
            waivers=[
                {
                    "file": "manuscript/main.tex",
                    "line_text": "Coding 43 works.",
                    "reason": "protocol count",
                    "date": "2026-10-04",
                    "author": 7,
                }
            ]
        )

        problems, _, _ = self.load_and_scan()

        self.assertEqual(
            self.codes(problems),
            ["claims-policy-invalid", "protected-untagged-number"],
        )
        invalid = next(
            item for item in problems if item.code == "claims-policy-invalid"
        )
        self.assertTrue(invalid.path.endswith("claims.yaml"))
        self.assertEqual(invalid.line, 9)

    def test_policy_version_must_be_one(self):
        self.write_policy(version=2)
        self.write_main("\\begin{abstract}\n43\n\\end{abstract}\n")

        policy, problems = load_policy(self.root)

        self.assertIsNone(policy)
        self.assertEqual(self.codes(problems), ["claims-policy-invalid"])

    def test_section_names_are_case_and_whitespace_normalized(self):
        self.write_policy(protected_sections=["  ReSults  "])
        self.write_main("\\section{ Results }\nCoding 43 works.\n")

        problems, _, _ = self.load_and_scan()

        self.assertEqual(self.codes(problems), ["protected-untagged-number"])

    def test_unknown_protected_section_is_a_problem(self):
        self.write_policy(protected_sections=["resultz"])
        self.write_main("\\section{Results}\nCoding 43 works.\n")

        problems, _, _ = self.load_and_scan()

        self.assertIn("claims-policy-unknown-section", self.codes(problems))
        unknown = next(
            item
            for item in problems
            if item.code == "claims-policy-unknown-section"
        )
        self.assertIn("resultz", unknown.message)
        self.assertIn("未在 manuscript 中找到", unknown.message)

    def test_all_matching_protected_sections_have_no_unknown_problem(self):
        self.write_policy(
            protected_sections=["abstract", "contributions", "results"]
        )
        self.write_main(
            "\\begin{abstract}\n"
            "\\end{abstract}\n"
            "\\section{Contributions}\n"
            "\\section{Results}\n"
            "\\dataval{stats.json:rows}{43}\n"
        )

        problems, _, _ = self.load_and_scan()

        self.assertNotIn("claims-policy-unknown-section", self.codes(problems))

    def test_waiver_line_text_matches_case_insensitively(self):
        self.write_main(
            "\\begin{abstract}\n"
            "Coding 43 works.\n"
            "\\end{abstract}\n"
        )
        self.write_policy(
            waivers=[
                {
                    "file": "manuscript/main.tex",
                    "line_text": "CODING 43 WORKS.",
                    "reason": "protocol count",
                    "date": "2026-10-04",
                    "author": "Alice",
                }
            ]
        )

        problems, advisories, counts = self.load_and_scan()

        self.assertEqual(problems, [])
        self.assertEqual(self.codes(advisories), ["waived-number"])
        self.assertEqual(counts["waived"], 1)

    def test_waiver_reports_how_many_lines_it_hit(self):
        self.write_main(
            "\\begin{abstract}\n"
            "Coding 43 works.\n"
            "Coding 43 works.\n"
            "\\end{abstract}\n"
        )
        self.write_policy(
            waivers=[
                {
                    "file": "manuscript/main.tex",
                    "line_text": "Coding 43 works.",
                    "reason": "protocol count",
                    "date": "2026-10-04",
                    "author": "Alice",
                }
            ]
        )

        problems, advisories, counts = self.load_and_scan()

        self.assertEqual(problems, [])
        self.assertEqual(
            self.codes(advisories),
            ["waived-number", "waived-number"],
        )
        for advisory in advisories:
            self.assertIn("命中 2 处", advisory.message)
        self.assertEqual(counts["waived"], 2)

    def test_waiver_line_field_limits_the_exemption_to_one_line(self):
        self.write_main(
            "\\begin{abstract}\n"
            "Coding 43 works.\n"
            "Coding 43 works.\n"
            "\\end{abstract}\n"
        )
        self.write_policy(
            waivers=[
                {
                    "file": "manuscript/main.tex",
                    "line_text": "Coding 43 works.",
                    "line": 3,
                    "reason": "protocol count",
                    "date": "2026-10-04",
                    "author": "Alice",
                }
            ]
        )

        problems, advisories, counts = self.load_and_scan()

        self.assertEqual(self.codes(problems), ["protected-untagged-number"])
        self.assertEqual(problems[0].line, 2)
        self.assertEqual(self.codes(advisories), ["waived-number"])
        self.assertIn("命中 1 处", advisories[0].message)
        self.assertEqual(advisories[0].line, 3)
        self.assertEqual(counts["waived"], 1)
        self.assertEqual(counts["unbound"], 1)

    def test_starred_subsection_boundary_protects_contributions(self):
        self.write_policy(protected_sections=["contributions"])
        self.write_main(
            "\\section{Introduction}\n"
            "\\subsection*{Contributions}\n"
            "Coding 43 works.\n"
            "\\subsection{Next}\n"
            "More 99 works.\n"
        )

        problems, advisories, _ = self.load_and_scan()

        self.assertEqual(self.codes(problems), ["protected-untagged-number"])
        self.assertEqual(problems[0].line, 3)
        self.assertEqual(self.codes(advisories), ["untagged-number"])
        self.assertEqual(advisories[0].line, 5)

    def test_subsection_does_not_end_a_protected_section(self):
        self.write_policy(protected_sections=["results"])
        self.write_main(
            "\\section{Results}\n"
            "Before 43 works.\n"
            "\\subsection{Details}\n"
            "After 44 works.\n"
            "\\section{Conclusion}\n"
            "Outside 45 works.\n"
        )

        problems, advisories, _ = self.load_and_scan()

        self.assertEqual(
            self.codes(problems),
            ["protected-untagged-number", "protected-untagged-number"],
        )
        self.assertEqual(self.codes(advisories), ["untagged-number"])
        self.assertEqual(advisories[0].line, 6)


class TestCoverageReport(BaseCase):
    def test_report_paths_do_not_depend_on_absolute_paper_root(self):
        self.write_main(
            "\\begin{abstract}\n"
            "Coding 43 works.\n"
            "\\end{abstract}\n"
        )

        relative_report = claims_coverage_report(self.root)
        relative_paths = [
            item["path"] for item in relative_report["problems"]
        ]
        self.assertEqual(
            relative_paths,
            ["manuscript/main.tex"],
        )

        absolute_report = claims_coverage_report(self.root.resolve())
        absolute_paths = [
            item["path"] for item in absolute_report["problems"]
        ]
        self.assertEqual(absolute_paths, relative_paths)
        self.assertNotIn(str(self.root.resolve()), absolute_paths[0])

    def test_report_counts_match_scan(self):
        self.write_main(
            "\\begin{abstract}\n"
            "Bound \\dataval{stats.json:bound}{11}.\n"
            "Waived 22 works.\n"
            "Unbound 33 works.\n"
            "\\end{abstract}\n"
        )
        self.write_policy(
            waivers=[
                {
                    "file": "manuscript/main.tex",
                    "line_text": "Waived 22 works.",
                    "reason": "external baseline",
                    "date": "2026-10-04",
                    "author": "Bob",
                }
            ]
        )

        report = claims_coverage_report(self.root)

        self.assertEqual(
            {
                key: report[key]
                for key in ("protected_total", "bound", "waived", "unbound")
            },
            {"protected_total": 3, "bound": 1, "waived": 1, "unbound": 1},
        )
        json_report = json.loads(
            (self.root / "submission" / "claims-coverage.json").read_text(
                encoding="utf-8"
            )
        )
        markdown = (self.root / "submission" / "claims-coverage.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(json_report["protected_total"], 3)
        self.assertEqual(json_report["unbound"], 1)
        self.assertIn("Protected total: 3", markdown)
        self.assertIn("Unbound: 1", markdown)
        self.assertIn("命中", markdown)
        self.assertIn("line", markdown)

    def test_report_marks_unknown_protected_sections(self):
        self.write_policy(protected_sections=["resultz"])
        self.write_main("\\section{Results}\nCoding 43 works.\n")

        report = claims_coverage_report(self.root)

        self.assertIn(
            "claims-policy-unknown-section",
            [item["code"] for item in report["problems"]],
        )
        json_report = json.loads(
            (self.root / "submission" / "claims-coverage.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn(
            "claims-policy-unknown-section",
            [item["code"] for item in json_report["problems"]],
        )

    def test_report_requires_a_policy(self):
        self.policy_path.unlink()

        with self.assertRaises(ValueError):
            claims_coverage_report(self.root)


if __name__ == "__main__":
    unittest.main()
