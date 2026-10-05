import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from ccfa.human_coding import check, main


class HumanCodingTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.a_path = self.root / "a.csv"
        self.b_path = self.root / "b.csv"

    def _write(self, path, rows):
        path.write_text(
            "item_id,code\n"
            + "".join(f"{item_id},{code}\n" for item_id, code in rows),
            encoding="utf-8",
        )

    def test_perfect_agreement(self):
        rows = [(f"i{index}", "yes" if index < 3 else "no") for index in range(6)]
        self._write(self.a_path, rows)
        self._write(self.b_path, rows)

        report, problems = check(self.a_path, self.b_path)

        self.assertEqual(problems, [])
        self.assertEqual(report["n"], 6)
        self.assertEqual(report["kappa"], 1.0)
        self.assertTrue(report["passed"])
        self.assertEqual(report["labels"]["yes"]["both"], 3)

    def test_known_kappa(self):
        a = [(f"i{index}", "x" if index < 5 else "y") for index in range(10)]
        b = [
            (f"i{index}", "x" if index < 4 else "y")
            for index in range(10)
        ]
        self._write(self.a_path, a)
        self._write(self.b_path, b)

        report, problems = check(self.a_path, self.b_path, bootstrap_iterations=200)

        self.assertEqual(problems, [])
        self.assertEqual(report["observed_agreement"], 0.9)
        self.assertEqual(report["expected_agreement"], 0.5)
        self.assertAlmostEqual(report["kappa"], 0.8, places=6)
        self.assertIn("ci95_bootstrap", report)
        self.assertLessEqual(
            report["ci95_bootstrap"]["low"],
            report["ci95_bootstrap"]["high"],
        )

    def test_duplicate_and_missing_items_are_problems(self):
        self._write(self.a_path, [("i1", "x"), ("i1", "y"), ("i2", "x")])
        self._write(self.b_path, [("i2", "x"), ("i3", "y")])

        report, problems = check(self.a_path, self.b_path)

        codes = {problem["code"] for problem in problems}
        self.assertIn("human-coding-duplicate-id", codes)
        self.assertIn("human-coding-missing-item", codes)
        self.assertFalse(report["passed"])

    def test_low_kappa_is_a_problem(self):
        a = [(f"i{index}", "x" if index < 5 else "y") for index in range(10)]
        b = [(f"i{index}", "x" if index % 2 == 0 else "y") for index in range(10)]
        self._write(self.a_path, a)
        self._write(self.b_path, b)

        report, problems = check(
            self.a_path,
            self.b_path,
            min_kappa=0.6,
            bootstrap_iterations=200,
        )

        self.assertFalse(report["passed"])
        self.assertIn(
            "human-coding-low-kappa",
            {problem["code"] for problem in problems},
        )

    def test_main_emits_json_and_exit_code(self):
        rows = [("i1", "x"), ("i2", "x")]
        self._write(self.a_path, rows)
        self._write(self.b_path, rows)
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "human-coding",
                    "--a",
                    str(self.a_path),
                    "--b",
                    str(self.b_path),
                    "--bootstrap-iterations",
                    "200",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["kappa"], 1.0)
        self.assertIn("human-coding:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
