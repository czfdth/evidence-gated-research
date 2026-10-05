import hashlib
import tempfile
import unittest
from pathlib import Path

from ccfa.figure_manifest import check_manifest, load_manifest

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 8


class TestLoadManifest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _write(self, body: str) -> Path:
        path = self.root / "manifest.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_loads_a_list_of_dicts(self):
        items = load_manifest(self._write("- name: a\n  bytes_format: png\n"))
        self.assertEqual(items[0]["name"], "a")

    def test_empty_file_is_an_empty_list(self):
        self.assertEqual(load_manifest(self._write("")), [])

    def test_top_level_must_be_a_list(self):
        with self.assertRaises(ValueError):
            load_manifest(self._write("name: a\n"))

    def test_each_item_must_be_an_object(self):
        with self.assertRaises(ValueError):
            load_manifest(self._write("- just-a-string\n"))

    def test_malformed_yaml_raises_value_error(self):
        with self.assertRaises(ValueError):
            load_manifest(self._write("- name: [unclosed\n"))

    def test_missing_file_raises_value_error(self):
        with self.assertRaises(ValueError):
            load_manifest(self.root / "gone.yaml")


class TestCheckManifest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.figures = self.root / "figures"
        self.figures.mkdir()
        self.run_id = "20261003T142530-01"
        self.log_dir = self.root / "experiments" / "log"
        self.log_dir.mkdir(parents=True)
        (self.log_dir / f"{self.run_id}.json").write_text(
            '{"run_id": "20261003T142530-01"}\n',
            encoding="utf-8",
        )
        self.source_data = self.root / "experiments" / "results" / "plot.csv"
        self.source_data.parent.mkdir(parents=True)
        self.source_data.write_text("x,y\n1,2\n", encoding="utf-8")

    def _item(self, **overrides):
        item = {
            "name": "plot",
            "file": "figures/plot.png",
            "bytes_format": "png",
            "generator": "src/plot.py",
            "generator_hash": "",
            "source_run_ids": [self.run_id],
            "source_data": "experiments/results/plot.csv",
            "referenced_in": ["manuscript/main.tex:1"],
        }
        item.update(overrides)
        return item

    def _write_generator(self, body: str = "print('x')\n") -> str:
        path = self.root / "src" / "plot.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def test_consistent_entry_is_clean(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(generator_hash=self._write_generator())
        problems, advisories = check_manifest([item], self.root)
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_declared_format_mismatch_is_reported(self):
        (self.figures / "plot.png").write_bytes(JPEG)
        item = self._item(generator_hash=self._write_generator())
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-manifest-format", [p.code for p in problems])

    def test_jpeg_alias_is_not_a_format_mismatch(self):
        (self.figures / "plot.jpeg").write_bytes(JPEG)
        item = self._item(
            file="figures/plot.jpeg",
            bytes_format="jpeg",
            generator_hash=self._write_generator(),
        )
        problems, _ = check_manifest([item], self.root)
        self.assertEqual(problems, [])

    def test_generator_hash_mismatch_is_reported(self):
        (self.figures / "plot.png").write_bytes(PNG)
        self._write_generator()
        item = self._item(generator_hash="sha256:deadbeef")
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-hash", [p.code for p in problems])
        self.assertIn("哈希不符", problems[0].message)
        self.assertNotIn("不存在", problems[0].message)

    def test_missing_generator_script_is_reported(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(generator="src/gone.py", generator_hash="sha256:x")
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-hash", [p.code for p in problems])

    def test_missing_generator_and_hash_report_one_provenance_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        for field in ("generator", "generator_hash"):
            with self.subTest(field=field):
                item = self._item(generator_hash=self._write_generator())
                del item[field]
                problems, _ = check_manifest([item], self.root)
                matching = [
                    problem
                    for problem in problems
                    if problem.code == "figure-provenance-missing"
                ]
                self.assertEqual(len(matching), 1)
                self.assertIn(field, matching[0].message)

    def test_missing_or_empty_run_ids_report_provenance_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        for value in (None, []):
            with self.subTest(value=value):
                item = self._item(generator_hash=self._write_generator())
                if value is None:
                    del item["source_run_ids"]
                else:
                    item["source_run_ids"] = value
                problems, _ = check_manifest([item], self.root)
                self.assertIn("figure-provenance-missing", [p.code for p in problems])

    def test_non_list_run_ids_report_provenance_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(
            generator_hash=self._write_generator(),
            source_run_ids="20261003T142530-01",
        )
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-provenance-missing", [p.code for p in problems])

    def test_non_string_generator_or_hash_reports_provenance_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        for field in ("generator", "generator_hash"):
            for value in ([], 0, {"id": "x"}):
                with self.subTest(field=field, value=value):
                    item = self._item(generator_hash=self._write_generator())
                    item[field] = value
                    problems, _ = check_manifest([item], self.root)
                    matching = [
                        problem
                        for problem in problems
                        if problem.code == "figure-provenance-missing"
                    ]
                    self.assertEqual(len(matching), 1)
                    self.assertIn(field, matching[0].message)
                    self.assertIn("类型非法", matching[0].message)
                    self.assertIn(type(value).__name__, matching[0].message)

    def test_non_string_generator_or_hash_has_no_secondary_hash_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        for field in ("generator", "generator_hash"):
            with self.subTest(field=field):
                item = self._item(generator_hash=self._write_generator())
                item[field] = {"id": "x"}
                problems, _ = check_manifest([item], self.root)
                self.assertEqual(
                    [p.code for p in problems],
                    ["figure-provenance-missing"],
                )
                self.assertIn("dict", problems[0].message)

    def test_generator_outside_paper_root_is_reported_even_with_matching_hash(self):
        (self.figures / "plot.png").write_bytes(PNG)
        outside = self.root.parent / "outside.py"
        outside.write_text("print('outside')\n", encoding="utf-8")
        outside_hash = "sha256:" + hashlib.sha256(outside.read_bytes()).hexdigest()

        for generator in ("../outside.py", str(outside)):
            with self.subTest(generator=generator):
                item = self._item(generator=generator, generator_hash=outside_hash)
                problems, _ = check_manifest([item], self.root)
                matching = [p for p in problems if p.code == "figure-hash"]
                self.assertEqual(len(matching), 1)
                self.assertIn("生成脚本必须在论文根内", matching[0].message)

    def test_file_outside_paper_root_is_reported_as_figure_missing(self):
        outside = self.root.parent / "outside.png"
        outside.write_bytes(PNG)

        for file_value in ("../outside.png", str(outside)):
            with self.subTest(file=file_value):
                item = self._item(
                    file=file_value,
                    generator_hash=self._write_generator(),
                )
                problems, _ = check_manifest([item], self.root)
                matching = [p for p in problems if p.code == "figure-missing"]
                self.assertEqual(len(matching), 1)
                self.assertIn("交付图路径越出论文根", matching[0].message)

    def test_non_string_run_id_member_reports_provenance_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(
            generator_hash=self._write_generator(),
            source_run_ids=[{"id": "x"}, 1, ""],
        )
        problems, _ = check_manifest([item], self.root)
        matching = [
            problem
            for problem in problems
            if problem.code == "figure-provenance-missing"
        ]
        self.assertEqual(len(matching), 1)
        self.assertIn("成员类型非法", matching[0].message)

    def test_traversal_run_id_reports_source_run_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        outside = self.root / "experiments" / "outside-run.json"
        outside.write_text('{"run_id": "outside-run"}\n', encoding="utf-8")
        item = self._item(
            generator_hash=self._write_generator(),
            source_run_ids=["../outside-run"],
        )
        problems, _ = check_manifest([item], self.root)
        matching = [p for p in problems if p.code == "figure-source-run"]
        self.assertEqual(len(matching), 1)
        self.assertIn("越界", matching[0].message)

    def test_unknown_run_id_reports_the_missing_log_path(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(
            generator_hash=self._write_generator(),
            source_run_ids=["20261003T142530-99"],
        )
        problems, _ = check_manifest([item], self.root)
        matching = [p for p in problems if p.code == "figure-source-run"]
        self.assertEqual(len(matching), 1)
        self.assertIn("20261003T142530-99.json", matching[0].path)

    def test_missing_or_empty_source_data_reports_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        for value in (None, "", "   "):
            with self.subTest(value=value):
                item = self._item(generator_hash=self._write_generator())
                if value is None:
                    del item["source_data"]
                else:
                    item["source_data"] = value
                problems, _ = check_manifest([item], self.root)
                self.assertIn("figure-source-data", [p.code for p in problems])

    def test_non_string_source_data_reports_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        for value in (0, [], {"path": "experiments/results/plot.csv"}):
            with self.subTest(value=value):
                item = self._item(
                    generator_hash=self._write_generator(),
                    source_data=value,
                )
                problems, _ = check_manifest([item], self.root)
                matching = [p for p in problems if p.code == "figure-source-data"]
                self.assertEqual(len(matching), 1)
                self.assertIn("类型非法", matching[0].message)

    def test_absolute_source_data_reports_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(
            generator_hash=self._write_generator(),
            source_data=str(self.source_data),
        )
        problems, _ = check_manifest([item], self.root)
        matching = [p for p in problems if p.code == "figure-source-data"]
        self.assertEqual(len(matching), 1)
        self.assertIn("绝对路径", matching[0].message)

    def test_traversal_source_data_reports_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        outside = self.root.parent / f"{self.root.name}-outside.csv"
        outside.write_text("x,y\n1,2\n", encoding="utf-8")
        item = self._item(
            generator_hash=self._write_generator(),
            source_data=f"../{outside.name}",
        )
        problems, _ = check_manifest([item], self.root)
        matching = [p for p in problems if p.code == "figure-source-data"]
        self.assertEqual(len(matching), 1)
        self.assertIn("越界", matching[0].message)

    def test_missing_source_data_file_reports_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(
            generator_hash=self._write_generator(),
            source_data="experiments/results/gone.csv",
        )
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-source-data", [p.code for p in problems])

    def test_manual_edit_without_note_reports_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(generator_hash=self._write_generator(), manual_edit=True)
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-manual-edit", [p.code for p in problems])

    def test_non_boolean_manual_edit_reports_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        for value in ("true", 1, []):
            with self.subTest(value=value):
                item = self._item(
                    generator_hash=self._write_generator(),
                    manual_edit=value,
                )
                problems, _ = check_manifest([item], self.root)
                matching = [p for p in problems if p.code == "figure-manual-edit"]
                self.assertEqual(len(matching), 1)
                self.assertIn("布尔", matching[0].message)

    def test_manual_edit_with_note_is_clean(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(
            generator_hash=self._write_generator(),
            manual_edit=True,
            manual_edit_note="Moved the legend; data unchanged.",
        )
        problems, advisories = check_manifest([item], self.root)
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_complete_provenance_still_reports_a_bad_delivery_path(self):
        item = self._item(
            generator_hash=self._write_generator(),
            file="figures/elsewhere.png",
        )
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-missing", [p.code for p in problems])

    def test_missing_delivered_figure_is_reported(self):
        item = self._item(generator_hash=self._write_generator())
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-missing", [p.code for p in problems])

    def test_absent_file_field_falls_back_and_warns(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(generator_hash=self._write_generator())
        del item["file"]
        problems, advisories = check_manifest([item], self.root)
        self.assertEqual([p.code for p in advisories], ["manifest-missing-file"])
        self.assertNotIn("figure-missing", [p.code for p in problems])

    def test_empty_referenced_in_is_an_advisory(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(generator_hash=self._write_generator(), referenced_in=[])
        problems, advisories = check_manifest([item], self.root)
        self.assertEqual(problems, [])
        self.assertIn("unreferenced-figure", [p.code for p in advisories])


if __name__ == "__main__":
    unittest.main()
