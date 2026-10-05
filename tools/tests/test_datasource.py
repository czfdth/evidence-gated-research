import csv
import tempfile
import unittest
from pathlib import Path

from ccfa.datasource import (
    SourceError,
    load_source,
    navigate,
    resolve_within_base_dir,
    split_key_path,
)


class TestResolveWithinBaseDir(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())

    def test_resolves_relative_path_under_base_dir(self):
        resolved = resolve_within_base_dir("results/a.json", self.base)
        self.assertEqual(resolved, (self.base / "results" / "a.json").resolve())

    def test_refuses_parent_escape(self):
        with self.assertRaises(SourceError):
            resolve_within_base_dir("../outside.json", self.base)

    def test_refuses_absolute_path(self):
        with self.assertRaises(SourceError):
            resolve_within_base_dir(str(self.base / "a.json"), self.base)


class TestLoadSource(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_loads_json(self):
        path = self.root / "a.json"
        path.write_text('{"x": 1}', encoding="utf-8")
        kind, data = load_source(path)
        self.assertEqual(kind, "json")
        self.assertEqual(data, {"x": 1})

    def test_malformed_json_raises_source_error(self):
        path = self.root / "bad.json"
        path.write_text('{"x": [1, 2', encoding="utf-8")
        with self.assertRaises(SourceError):
            load_source(path)

    def test_loads_yaml(self):
        path = self.root / "a.yaml"
        path.write_text("x: 1\n", encoding="utf-8")
        kind, data = load_source(path)
        self.assertEqual(kind, "yaml")
        self.assertEqual(data, {"x": 1})

    def test_loads_csv_as_dict_rows(self):
        path = self.root / "a.csv"
        path.write_text("name,value\nfirst,1\nsecond,2\n", encoding="utf-8")
        kind, data = load_source(path)
        self.assertEqual(kind, "csv")
        self.assertEqual(data[1]["name"], "second")

    def test_csv_parse_error_raises_source_error(self):
        path = self.root / "wide.csv"
        path.write_text("name,value\n" + "x" * 64 + ",1\n", encoding="utf-8")
        original_limit = csv.field_size_limit()
        csv.field_size_limit(1)
        try:
            # A tiny field limit makes the csv module raise its own error type.
            with self.assertRaises(csv.Error):
                with path.open(encoding="utf-8", newline="") as handle:
                    list(csv.DictReader(handle))
            with self.assertRaises(SourceError):
                load_source(path)
        finally:
            csv.field_size_limit(original_limit)

    def test_unsupported_suffix_raises(self):
        path = self.root / "a.txt"
        path.write_text("x", encoding="utf-8")
        with self.assertRaises(SourceError):
            load_source(path)

    def test_malformed_yaml_raises_source_error(self):
        path = self.root / "bad.yaml"
        path.write_text("x: [1, 2\n", encoding="utf-8")
        with self.assertRaises(SourceError):
            load_source(path)

    def test_missing_file_raises_oserror(self):
        with self.assertRaises(OSError):
            load_source(self.root / "gone.json")


class TestSplitKeyPath(unittest.TestCase):
    def test_splits_on_dots(self):
        self.assertEqual(split_key_path("summary.lcoe"), ["summary", "lcoe"])

    def test_escaped_dot_is_literal(self):
        self.assertEqual(
            split_key_path(r"sweep.0\.5x.rate"), ["sweep", "0.5x", "rate"]
        )


class TestNavigate(unittest.TestCase):
    def test_walks_json_dicts_and_lists(self):
        data = {"sweep": [{"rate": 0.5}, {"rate": 0.7}]}
        self.assertEqual(navigate("json", data, "sweep.1.rate"), 0.7)

    def test_literal_dot_key_is_reachable(self):
        data = {"0.5x_4ms": {"stat": 16.98}}
        self.assertEqual(navigate("json", data, r"0\.5x_4ms.stat"), 16.98)

    def test_missing_key_raises(self):
        with self.assertRaises(SourceError):
            navigate("json", {"a": 1}, "b")

    def test_csv_row_and_column(self):
        rows = [{"lcoe": "0.143"}, {"lcoe": "0.2"}]
        self.assertEqual(navigate("csv", rows, "0.lcoe"), "0.143")


if __name__ == "__main__":
    unittest.main()
