# trace-claims（数字溯源守卫）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成数字溯源守卫 `trace-claims`：把正文里每个 `\dataval` 标记机械地比对到活的 JSON / CSV / YAML 源值，对不上就报 problem；未标记的数字线索以 advisory 形式列出，不影响退出码。

**Architecture:** 四层，每层一个模块。`texcomment` 提供正确的 LaTeX 注释剥离（`%` 前反斜杠为偶数个才算注释），`texscan` 与数字扫描共用它；`dataval` 扫描标签与未标记数字；`datasource` 负责路径边界、载入与键路径导航；`datavalue` 只负责"两个值算不算相等"；`trace_claims` 把前三者串成 `check()` 与 CLI，输出走 `ccfa.cli` 的既定契约。

**Tech Stack:** Python 3.12（`tools/.venv` 已有）；stdlib `json` / `csv` / `re` / `argparse`；PyYAML 6.0.3；unittest。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v4，第 6.4 节与第 12 节）

## Global Constraints

- 仓库根：`<repo-root>`
- 退出码语义：`0` 通过，`1` 发现问题，`2` 工具自身出错。三者不得合并。
- 机器可读 JSON 走 stdout；人读摘要走 stderr。检查类工具只读，不得写入被检查文件。
- 所有文本文件 UTF-8 无 BOM；默认 ASCII 注释，中文只出现在面向用户的文案里。
- 不得写入或提交含用户名的绝对路径。
- 基线：**125 个测试全部通过**，工作树干净，HEAD = `ba92e25`。每个任务结束后套件必须全绿。
- 测试命令（仓库根执行）：
  `& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
- 既有接口（已完成，直接消费，不修改语义）：`ccfa.cli` 的 `Problem(code, path, line, message)`、`emit(problems, advisories)`（JSON 到 stdout、摘要到 stderr、有问题返回 1）、`tool_error(message)`（返回 2）。
- 运行期依赖已就绪：`bibtexparser==2.1.0`、`pylatexenc==2.11`、`PyYAML==6.0.3`。不得重建 venv、不得安装新依赖。
- 参考实现：`15b4t/research-suite`（MIT）的 `tools/traceable-claims/traceable_claims.py`；本计划在其之上按 spec v4 收紧退出码语义。

---

### Task 1: 共享注释剥离 + 修掉 texscan 已知缺陷

**Files:**
- Create: `tools/ccfa/texcomment.py`
- Modify: `tools/ccfa/texscan.py`
- Create: `tools/tests/test_texcomment.py`
- Modify: `tools/tests/test_texscan.py`

**Interfaces:**
- Produces: `strip_comment(line: str) -> str`（返回注释开始前的部分；无反斜杠转义的 `%` 起注释作用）
- Consumes: 无
- 动机：Plan 2 deferred minor 第 1 条——`texscan._COMMENT = re.compile(r"(?<!\\)%")` 只回溯一个字符，`line\\% \cite{ghost}` 会被误判为"百分号被转义"，幽灵引用被计入。数字扫描要复用同一逻辑，不能把缺陷复制一份。

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_texcomment.py`：

```python
import unittest

from ccfa.texcomment import strip_comment


class TestStripComment(unittest.TestCase):
    def test_plain_percent_starts_a_comment(self):
        self.assertEqual(strip_comment("\\cite{a} % \\cite{ghost}"), "\\cite{a} ")

    def test_escaped_percent_is_not_a_comment(self):
        self.assertEqual(strip_comment("100\\% of \\cite{a}"), "100\\% of \\cite{a}")

    def test_two_backslashes_then_percent_starts_a_comment(self):
        # A literal backslash followed by a percent: the percent is not escaped.
        self.assertEqual(strip_comment("line\\\\% \\cite{ghost}"), "line\\\\")

    def test_three_backslashes_then_percent_is_escaped(self):
        self.assertEqual(strip_comment("line\\\\\\% x"), "line\\\\\\% x")

    def test_no_percent_returns_line_unchanged(self):
        self.assertEqual(strip_comment("\\cite{a}"), "\\cite{a}")

    def test_percent_at_position_zero_yields_empty(self):
        self.assertEqual(strip_comment("% hidden"), "")


if __name__ == "__main__":
    unittest.main()
```

在 `tools/tests/test_texscan.py` 的 `TestFindCitedKeys` 内追加一条（放在 `test_escaped_percent_does_not_start_a_comment` 之后）：

```python
    def test_literal_backslash_then_comment_hides_the_citation(self):
        keys, _ = self._scan("line\\\\% \\cite{ghost}\n\\cite{real}")
        self.assertEqual(list(keys), ["real"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools 2>&1 | Select-String "ModuleNotFoundError|FAILED|Ran "`

Expected: FAIL，`ModuleNotFoundError: No module named 'ccfa.texcomment'`。

- [ ] **Step 3: 实现 texcomment**

创建 `tools/ccfa/texcomment.py`：

```python
"""Strip LaTeX line comments, respecting escaped percent signs.

A percent begins a comment only when the backslashes immediately before it
are even in number: an odd count means the last backslash escapes it.
Checking only the previous character is wrong for a line containing a
literal backslash, where the percent that follows is a real comment.
"""

from __future__ import annotations


def strip_comment(line: str) -> str:
    for index, char in enumerate(line):
        if char != "%":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return line[:index]
    return line
```

- [ ] **Step 4: 运行 texcomment 测试确认通过**

Run: `& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools 2>&1 | Select-String "FAILED|Ran "`

Expected: `Ran 131 tests`（125 + 6 条 texcomment 用例），**恰好 1 个 failure**——`test_texscan` 的新用例仍失败，因为 texscan 还没换实现。6 条 texcomment 用例必须全绿；若那条 texscan 用例不失败，说明它没有判别力，回到 Step 1 检查字符串转义。

- [ ] **Step 5: 让 texscan 复用共享实现**

修改 `tools/ccfa/texscan.py`：删除 `_COMMENT` 正则与 `_strip_comment` 函数，改为导入；文档字符串里那句"escaped percent (\\%) must not start a comment"保留。改动如下：

```python
# 顶部 import 区，替换原来的 import re 行之后新增
from ccfa.texcomment import strip_comment

# 删除这两处：
# _COMMENT = re.compile(r"(?<!\\)%")
# def _strip_comment(line: str) -> str: ...

# find_cited_keys 内，替换：
#     line = _strip_comment(raw_line)
            line = strip_comment(raw_line)
```

`import re` 必须保留（`_CITE` 仍在用）。除上述三处外不得改动 `texscan.py`。

- [ ] **Step 6: 运行完整套件确认通过**

Run: 全局测试命令（见 Global Constraints）

Expected: `Ran 132 tests`，`OK`（125 + 7）。

判别力检查：临时把 `strip_comment` 改成 `return line.split("%", 1)[0]`，则 `test_two_backslashes_then_percent_starts_a_comment`（返回值多出注释）与 `test_escaped_percent_is_not_a_comment` / texscan 的 `test_escaped_percent_does_not_start_a_comment` 应各自失败；恢复实现后全绿。

- [ ] **Step 7: 提交**

```powershell
git add tools/ccfa/texcomment.py tools/ccfa/texscan.py tools/tests/test_texcomment.py tools/tests/test_texscan.py
git commit -m "fix: strip LaTeX comments with even-backslash rule"
```

---

### Task 2: dataval 标签扫描

**Files:**
- Create: `tools/ccfa/dataval.py`
- Create: `tools/tests/test_dataval.py`

**Interfaces:**
- Consumes: `ccfa.texcomment.strip_comment`
- Produces:
  - `Tag = NamedTuple("Tag", [("path", str), ("line", int), ("source_path", str), ("key_path", str), ("claimed", str)])`
  - `find_tags(paths: Iterable[Path]) -> list[Tag]`（按传入顺序、同文件按行序；不可读文件跳过）

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_dataval.py`：

```python
import tempfile
import unittest
from pathlib import Path

from ccfa.dataval import find_tags


def _write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestFindTags(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _scan(self, body: str):
        path = _write(self.root, "main.tex", body)
        return find_tags([path]), path

    def test_plain_tag(self):
        tags, path = self._scan("\\dataval{results.json:summary.lcoe}{0.143}")
        self.assertEqual(len(tags), 1)
        tag = tags[0]
        self.assertEqual(tag.source_path, "results.json")
        self.assertEqual(tag.key_path, "summary.lcoe")
        self.assertEqual(tag.claimed, "0.143")
        self.assertEqual(tag.line, 1)
        self.assertEqual(tag.path, str(path))

    def test_multiple_tags_on_one_line(self):
        tags, _ = self._scan("\\dataval{a.json:x}{1} and \\dataval{b.csv:0.y}{2}")
        self.assertEqual([t.source_path for t in tags], ["a.json", "b.csv"])

    def test_commented_tag_is_ignored(self):
        tags, _ = self._scan("% \\dataval{a.json:x}{1}\n\\dataval{b.json:y}{2}")
        self.assertEqual([t.source_path for t in tags], ["b.json"])

    def test_tag_after_literal_backslash_comment_is_ignored(self):
        tags, _ = self._scan("line\\\\% \\dataval{ghost.json:x}{1}\n\\dataval{real.json:y}{2}")
        self.assertEqual([t.source_path for t in tags], ["real.json"])

    def test_escaped_percent_does_not_truncate_the_line(self):
        tags, _ = self._scan("100\\% \\dataval{kept.json:x}{1}")
        self.assertEqual([t.source_path for t in tags], ["kept.json"])

    def test_unreadable_file_is_skipped_not_crashed(self):
        self.assertEqual(find_tags([self.root / "gone.tex"]), [])

    def test_line_number_counts_from_one(self):
        tags, _ = self._scan("text\n\n\\dataval{a.json:x}{1}")
        self.assertEqual(tags[0].line, 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ModuleNotFoundError: No module named 'ccfa.dataval'`。

- [ ] **Step 3: 实现**

创建 `tools/ccfa/dataval.py`：

```python
"""Scan LaTeX sources for \\dataval tags.

A tag is ``\\dataval{source_path:key_path}{claimed_value}``. Tags inside
comments do not count, and an escaped percent does not truncate a line.
Scanning is read-only and never touches the files it reads.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, NamedTuple

from ccfa.texcomment import strip_comment


class Tag(NamedTuple):
    path: str
    line: int
    source_path: str
    key_path: str
    claimed: str


_TAG = re.compile(r"\\dataval\{([^:}]+):([^}]+)\}\{([^}]*)\}")


def find_tags(paths: Iterable[Path]) -> list[Tag]:
    tags: list[Tag] = []
    for path in paths:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, raw_line in enumerate(text.splitlines(), start=1):
            line = strip_comment(raw_line)
            for match in _TAG.finditer(line):
                tags.append(
                    Tag(
                        str(path),
                        number,
                        match.group(1).strip(),
                        match.group(2).strip(),
                        match.group(3).strip(),
                    )
                )
    return tags
```

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 139 tests`，`OK`（132 + 7）。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/dataval.py tools/tests/test_dataval.py
git commit -m "feat: scan dataval tags in LaTeX sources"
```

---

### Task 3: 源文件边界、载入与键路径导航

**Files:**
- Create: `tools/ccfa/datasource.py`
- Create: `tools/tests/test_datasource.py`

**Interfaces:**
- Produces:
  - `class SourceError(Exception)`
  - `resolve_within_base_dir(source_path: str, base_dir: Path | None) -> Path`（绝对路径与 `..` 逃逸一律 `SourceError`）
  - `load_source(path: Path) -> tuple[str, object]`（`json` / `yaml` / `csv`）
  - `split_key_path(key_path: str) -> list[str]`（`\.` 转义字面点）
  - `navigate(kind: str, data: object, key_path: str) -> object`
- 关键约束：标签里的 source_path 来自正文文本，可能写错甚至恶意。`--base-dir` 是真边界，不是默认前缀。

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_datasource.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ModuleNotFoundError: No module named 'ccfa.datasource'`。

- [ ] **Step 3: 实现**

创建 `tools/ccfa/datasource.py`：

```python
"""Resolve a tagged source path and key path against a live data file.

Source paths come from the manuscript text, so the base directory is a real
containment boundary: absolute paths and '..' escapes are refused rather
than silently re-rooted. JSON/YAML key paths are dot-separated, with '\\.'
escaping a literal dot; CSV key paths are '<row>.<column>' over 0-indexed
data rows (the header row is not counted).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - only reachable without PyYAML
    yaml = None


class SourceError(Exception):
    """A tag's source could not be read, parsed, or navigated."""


def resolve_within_base_dir(source_path: str, base_dir: Path | None) -> Path:
    if Path(source_path).is_absolute():
        raise SourceError(f"source path must be relative: {source_path}")
    base = Path(base_dir or Path.cwd()).resolve()
    resolved = (base / source_path).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        raise SourceError(
            f"source path '{source_path}' escapes base dir '{base}'"
        ) from None
    return resolved


def load_source(path: Path) -> tuple[str, object]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json", json.loads(path.read_text(encoding="utf-8"))
    if suffix in (".yaml", ".yml"):
        if yaml is None:
            raise SourceError("PyYAML 未安装，无法读取 YAML 源")
        try:
            return "yaml", yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise SourceError(f"YAML 解析失败: {exc}") from exc
    if suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return "csv", list(csv.DictReader(handle))
    raise SourceError(f"不支持的源文件类型: {path.suffix}")


def split_key_path(key_path: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(key_path):
        char = key_path[index]
        if char == "\\" and index + 1 < len(key_path) and key_path[index + 1] == ".":
            current.append(".")
            index += 2
            continue
        if char == ".":
            parts.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def navigate(kind: str, data: object, key_path: str) -> object:
    if kind in ("json", "yaml"):
        node = data
        for part in split_key_path(key_path):
            if isinstance(node, list):
                node = node[int(part)]
            elif isinstance(node, dict):
                if part not in node:
                    raise SourceError(f"key '{part}' not found (path: {key_path})")
                node = node[part]
            else:
                raise SourceError(
                    f"cannot navigate into {type(node).__name__} with '{part}'"
                )
        return node
    if kind == "csv":
        parts = key_path.split(".", 1)
        if len(parts) != 2:
            raise SourceError(
                f"CSV key path must be '<row>.<column>', got '{key_path}'"
            )
        row_text, column = parts
        try:
            row_index = int(row_text)
        except ValueError:
            raise SourceError(f"CSV row index is not an integer: {row_text!r}") from None
        if not isinstance(data, list):
            raise SourceError("CSV data is not a list of rows")
        if row_index < 0 or row_index >= len(data):
            raise SourceError(f"row {row_index} out of range (0..{len(data) - 1})")
        row = data[row_index]
        if column not in row:
            raise SourceError(f"column '{column}' not found")
        return row[column]
    raise SourceError(f"unknown source kind: {kind}")
```

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 154 tests`，`OK`（139 + 15）。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/datasource.py tools/tests/test_datasource.py
git commit -m "feat: resolve dataval sources with a real base-dir boundary"
```

---

### Task 4: 值比较语义

**Files:**
- Create: `tools/ccfa/datavalue.py`
- Create: `tools/tests/test_datavalue.py`

**Interfaces:**
- Produces:
  - `implied_rounding_tolerance(claimed: str) -> float`
  - `values_match(claimed: str, actual: object, tolerance: float = 1e-9, rel_tolerance: float = 0.0) -> bool`
- 动机：正文里的数字是给人读的，必然经过舍入。精确相等会把每个正常四舍五入的图都判错，工具立刻变成噪声源。spec v4 第 6.4 节把这条列为第 1 条比较语义。

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_datavalue.py`：

```python
import unittest

from ccfa.datavalue import implied_rounding_tolerance, values_match


class TestImpliedRoundingTolerance(unittest.TestCase):
    def test_three_decimals_implies_half_unit(self):
        self.assertAlmostEqual(implied_rounding_tolerance("0.143"), 0.0005)

    def test_integer_has_no_implied_tolerance(self):
        self.assertEqual(implied_rounding_tolerance("42"), 0.0)


class TestValuesMatch(unittest.TestCase):
    def test_exact_number_matches(self):
        self.assertTrue(values_match("0.143", 0.143))

    def test_exact_string_matches(self):
        self.assertTrue(values_match("baseline", "baseline"))

    def test_rounded_claim_matches_full_precision_source(self):
        self.assertTrue(values_match("0.143", 0.14285714285714285))

    def test_rounded_claim_outside_half_unit_fails(self):
        self.assertFalse(values_match("0.5", 0.56))

    def test_integer_claim_has_no_implied_tolerance(self):
        self.assertFalse(values_match("42", 42.4))

    def test_thousands_separator_is_stripped(self):
        self.assertTrue(values_match("12,345.67", 12345.67))

    def test_json_style_boolean_matches_python_bool(self):
        self.assertTrue(values_match("false", False))
        self.assertTrue(values_match("True", True))

    def test_boolean_mismatch_fails(self):
        self.assertFalse(values_match("false", True))

    def test_relative_tolerance_accepts_small_relative_difference(self):
        self.assertTrue(
            values_match("1200000000", 1200000000.5, rel_tolerance=1e-6)
        )

    def test_relative_tolerance_is_off_by_default(self):
        self.assertFalse(values_match("1200000000", 1200000000.5))

    def test_non_numeric_mismatch_fails(self):
        self.assertFalse(values_match("baseline", "proposed"))

    def test_explicit_absolute_tolerance(self):
        # An integer claim implies no rounding tolerance; only an explicit one accepts the gap.
        self.assertTrue(values_match("10", 10.05, tolerance=0.1))
        self.assertFalse(values_match("10", 10.05))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ModuleNotFoundError: No module named 'ccfa.datavalue'`。

- [ ] **Step 3: 实现**

创建 `tools/ccfa/datavalue.py`：

```python
"""Decide whether a claimed value matches its live source value.

A manuscript rounds numbers for readability, so exact equality is the wrong
test. A claim written to three decimals implies a half-unit tolerance in the
last place -- that rule is what keeps a correct draft from failing on every
rounded figure, without one hand-picked global tolerance.
"""

from __future__ import annotations

import re

_THOUSANDS = re.compile(r"^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")


def _parse_number(value: object) -> float | None:
    text = str(value).strip()
    if _THOUSANDS.match(text):
        text = text.replace(",", "")
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def implied_rounding_tolerance(claimed: str) -> float:
    text = claimed.strip().lstrip("-")
    if "." not in text:
        return 0.0
    decimals = len(text.split(".", 1)[1])
    return 0.5 * (10 ** -decimals)


def values_match(
    claimed: str,
    actual: object,
    tolerance: float = 1e-9,
    rel_tolerance: float = 0.0,
) -> bool:
    claimed_text = claimed.strip()
    actual_text = str(actual).strip()
    if claimed_text == actual_text:
        return True
    claimed_lower = claimed_text.lower()
    actual_lower = actual_text.lower()
    if claimed_lower in ("true", "false") and actual_lower in ("true", "false"):
        return claimed_lower == actual_lower
    claimed_number = _parse_number(claimed_text)
    actual_number = _parse_number(actual_text)
    if claimed_number is None or actual_number is None:
        return False
    difference = abs(claimed_number - actual_number)
    if difference <= tolerance:
        return True
    if rel_tolerance > 0 and difference <= rel_tolerance * max(
        abs(claimed_number), abs(actual_number)
    ):
        return True
    return difference <= implied_rounding_tolerance(claimed_text)
```

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 168 tests`，`OK`（154 + 14）。

注意 `test_rounded_claim_outside_half_unit_fails` 的判别力：把 `implied_rounding_tolerance` 恒返回 `0.0`，该用例仍会通过（0.56 与 0.5 差 0.06 本就超过任何小容差），真正被它抓到的是 `test_rounded_claim_matches_full_precision_source`。两个方向各自独立成立，正是本节要保证的。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/datavalue.py tools/tests/test_datavalue.py
git commit -m "feat: compare claimed values with implied rounding tolerance"
```

---

### Task 5: check 流水线与 CLI

**Files:**
- Create: `tools/ccfa/trace_claims.py`
- Create: `tools/tests/test_trace_claims.py`

**Interfaces:**
- Consumes: `ccfa.dataval.find_tags`、`ccfa.datasource`（四个函数）、`ccfa.datavalue.values_match`、`ccfa.cli`
- Produces:
  - `check(docs: Iterable[Path], base_dir: Path | None = None, tolerance: float = 1e-9, rel_tolerance: float = 0.0) -> tuple[list[Problem], list[Problem]]`
  - `main(argv: list[str]) -> int`，参数 `--doc`（可重复）、`--base-dir`、`--tolerance`、`--rel-tolerance`
  - problem codes：`dataval-mismatch`（值不符）、`dataval-error`（源不可解析）
- 退出码判定：文档传参不存在 → `ValueError` → `tool_error` → 2；标签指向的源文件/键不存在 → problem → 1。**这两者混同就是本工具最该防的错误。**

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_trace_claims.py`：

```python
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ccfa.trace_claims import check, main


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.doc = self.root / "main.tex"
        (self.root / "results.json").write_text(
            json.dumps({"summary": {"lcoe": 0.14285714285714285}}), encoding="utf-8"
        )

    def write_doc(self, body: str):
        self.doc.write_text(body, encoding="utf-8")

    def run_check(self):
        return check([self.doc], self.root)

    def run_main(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                [
                    "trace_claims.py",
                    "--doc",
                    str(self.doc),
                    "--base-dir",
                    str(self.root),
                ]
            )
        return code, out.getvalue(), err.getvalue()

    @staticmethod
    def codes(problems):
        return sorted(p.code for p in problems)


class TestCheck(BaseCase):
    def test_matching_rounding_passes(self):
        self.write_doc("\\dataval{results.json:summary.lcoe}{0.143}")
        problems, _ = self.run_check()
        self.assertEqual(problems, [])

    def test_mismatch_is_a_problem_with_location(self):
        self.write_doc("\\dataval{results.json:summary.lcoe}{0.5}")
        problems, _ = self.run_check()
        self.assertEqual(self.codes(problems), ["dataval-mismatch"])
        self.assertEqual(problems[0].line, 1)
        self.assertTrue(problems[0].path.endswith("main.tex"))

    def test_missing_key_is_a_problem_not_a_crash(self):
        self.write_doc("\\dataval{results.json:nope}{1}")
        problems, _ = self.run_check()
        self.assertEqual(self.codes(problems), ["dataval-error"])

    def test_missing_source_file_is_a_problem(self):
        self.write_doc("\\dataval{gone.json:x}{1}")
        problems, _ = self.run_check()
        self.assertEqual(self.codes(problems), ["dataval-error"])

    def test_path_escape_is_a_problem(self):
        self.write_doc("\\dataval{../outside.json:x}{1}")
        problems, _ = self.run_check()
        self.assertEqual(self.codes(problems), ["dataval-error"])

    def test_commented_tag_is_not_checked(self):
        self.write_doc("% \\dataval{results.json:nope}{1}")
        problems, _ = self.run_check()
        self.assertEqual(problems, [])

    def test_no_tags_is_clean(self):
        self.write_doc("No numbers here.")
        problems, _ = self.run_check()
        self.assertEqual(problems, [])


class TestMain(BaseCase):
    def test_clean_run_exits_zero(self):
        self.write_doc("\\dataval{results.json:summary.lcoe}{0.143}")
        code, _, _ = self.run_main()
        self.assertEqual(code, 0)

    def test_mismatch_exits_one(self):
        self.write_doc("\\dataval{results.json:summary.lcoe}{0.5}")
        code, _, _ = self.run_main()
        self.assertEqual(code, 1)

    def test_missing_document_exits_two(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                [
                    "trace_claims.py",
                    "--doc",
                    str(self.root / "nope.tex"),
                    "--base-dir",
                    str(self.root),
                ]
            )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ModuleNotFoundError: No module named 'ccfa.trace_claims'`。

- [ ] **Step 3: 实现**

创建 `tools/ccfa/trace_claims.py`：

```python
"""Verify every \\dataval tag against its live source.

Read-only: never edits the manuscript or the data files it reads.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from ccfa.cli import Problem, emit, tool_error
from ccfa.datasource import SourceError, load_source, navigate, resolve_within_base_dir
from ccfa.dataval import Tag, find_tags
from ccfa.datavalue import values_match

_TAG_ERRORS = (SourceError, OSError, ValueError, KeyError, IndexError, TypeError)


def _resolve(tag: Tag, base_dir: Path | None) -> object:
    try:
        source = resolve_within_base_dir(tag.source_path, base_dir)
        kind, data = load_source(source)
        return navigate(kind, data, tag.key_path)
    except _TAG_ERRORS as exc:
        raise SourceError(str(exc)) from exc


def _documents(paths: Iterable[str]) -> list[Path]:
    docs: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            raise ValueError(f"文档不存在或不是文件: {path}")
        docs.append(path)
    return docs


def check(
    docs: Iterable[Path],
    base_dir: Path | None = None,
    tolerance: float = 1e-9,
    rel_tolerance: float = 0.0,
) -> tuple[list[Problem], list[Problem]]:
    problems: list[Problem] = []
    for tag in find_tags(docs):
        try:
            actual = _resolve(tag, base_dir)
        except SourceError as exc:
            problems.append(
                Problem(
                    "dataval-error",
                    tag.path,
                    tag.line,
                    f"标签源不可解析（{tag.source_path}:{tag.key_path}）: {exc}",
                )
            )
            continue
        if not values_match(tag.claimed, actual, tolerance, rel_tolerance):
            problems.append(
                Problem(
                    "dataval-mismatch",
                    tag.path,
                    tag.line,
                    f"标记值 {tag.claimed!r} 与源值 {str(actual)!r} 不符"
                    f"（{tag.source_path}:{tag.key_path}）",
                )
            )
    return problems, []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="核验正文数字与源数据一致")
    parser.add_argument("--doc", action="append", required=True, dest="docs")
    parser.add_argument("--base-dir")
    parser.add_argument("--tolerance", type=float, default=1e-9)
    parser.add_argument("--rel-tolerance", type=float, default=0.0)
    args = parser.parse_args(argv[1:])

    try:
        docs = _documents(args.docs)
        base_dir = Path(args.base_dir) if args.base_dir else None
        problems, advisories = check(docs, base_dir, args.tolerance, args.rel_tolerance)
    except ValueError as exc:
        return tool_error(str(exc))

    return emit(problems, advisories)


if __name__ == "__main__":
    # Windows consoles default to a locale code page; pin the contract streams.
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 178 tests`，`OK`（168 + 10）。

判别力检查：把 `_documents` 里的 `is_file()` 判定删掉（只做 `Path(raw)`），`test_missing_document_exits_two` 必须失败；恢复。这一步证明"文档传参错误 → 2"确实由代码强制，而不是碰巧。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/trace_claims.py tools/tests/test_trace_claims.py
git commit -m "feat: check dataval claims and split tool errors from findings"
```

---

### Task 6: 未标记数字 advisory

**Files:**
- Modify: `tools/ccfa/dataval.py`
- Modify: `tools/ccfa/trace_claims.py`
- Modify: `tools/tests/test_dataval.py`
- Modify: `tools/tests/test_trace_claims.py`

**Interfaces:**
- Produces（dataval）：
  - `Untagged = NamedTuple("Untagged", [("path", str), ("line", int), ("text", str)])`
  - `find_untagged(path: Path) -> list[Untagged]`
- Produces（trace_claims）：
  - `check(..., untagged: bool = False)`；`untagged=True` 时把线索放进返回的 advisories，code = `untagged-number`
  - `main` 新增 `--untagged`
- 硬约束：advisory **永不影响退出码**。它是待人工复核的线索，不是判决。

- [ ] **Step 1: 写失败测试**

在 `tools/tests/test_dataval.py` 追加（`find_tags` 的 import 改为 `from ccfa.dataval import find_tags, find_untagged`）：

```python
class TestFindUntagged(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _scan(self, body: str):
        path = _write(self.root, "main.tex", body)
        return find_untagged(path)

    def test_plain_number_is_reported(self):
        found = self._scan("Accuracy was 92.5 percent.")
        self.assertEqual([item.text for item in found], ["Accuracy was 92.5 percent."])
        self.assertEqual(found[0].line, 1)

    def test_tagged_number_is_not_reported(self):
        self.assertEqual(
            self._scan("\\dataval{a.json:x}{92.5} percent"), []
        )

    def test_year_is_skipped(self):
        # The trailing space matters: a digit touching a period never matches _NUMBER's
        # third branch, so only "2024 and later" actually exercises the _YEAR filter.
        self.assertEqual(self._scan("Published in 2024 and later."), [])

    def test_table_reference_is_skipped(self):
        self.assertEqual(self._scan("See Table 3 for details."), [])

    def test_bracket_citation_is_skipped(self):
        self.assertEqual(self._scan("Prior work [12] showed this."), [])

    def test_unreadable_file_returns_empty(self):
        self.assertEqual(find_untagged(self.root / "gone.tex"), [])
```

在 `tools/tests/test_trace_claims.py` 追加：

```python
class TestUntaggedAdvisory(BaseCase):
    def test_untagged_flag_puts_candidates_in_advisories(self):
        self.write_doc("Accuracy was 92.5 percent.")
        problems, advisories = check([self.doc], self.root, untagged=True)
        self.assertEqual(problems, [])
        self.assertEqual(self.codes(advisories), ["untagged-number"])

    def test_untagged_candidates_do_not_change_the_exit_code(self):
        self.write_doc("Accuracy was 92.5 percent.")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                [
                    "trace_claims.py",
                    "--doc",
                    str(self.doc),
                    "--base-dir",
                    str(self.root),
                    "--untagged",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["problem_count"], 0)
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ImportError: cannot import name 'find_untagged'`（以及 `check()` 不认识 `untagged` 参数）。

- [ ] **Step 3: 实现**

在 `tools/ccfa/dataval.py` 的 `Tag` 之后追加：

```python
class Untagged(NamedTuple):
    path: str
    line: int
    text: str
```

在文件末尾追加：

```python
_YEAR = re.compile(r"^(19|20)\d{2}$")
_REF_CONTEXT = re.compile(
    r"(Table|Figure|Fig\.|Section|Sec\.|Eq\.|Equation|Chapter|Appendix|Step|Page|pp?\.|No\.|ref)\s*$",
    re.IGNORECASE,
)
_NUMBER = re.compile(
    r"(?<![\w.])-?\d+\.\d+(?![\w])"
    r"|(?<![\w.])-?\d{1,3}(?:,\d{3})+(?![\w])"
    r"|(?<![\w.,])-?\d{2,}(?![\w.,])"
)
_BRACKET_CITATION = re.compile(r"\[\d+(,\s*\d+)*\]")


def find_untagged(path: Path) -> list[Untagged]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[Untagged] = []
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = strip_comment(raw_line)
        tagged = [(match.start(), match.end()) for match in _TAG.finditer(line)]
        for match in _NUMBER.finditer(line):
            if any(start <= match.start() < end for start, end in tagged):
                continue
            if _YEAR.match(match.group(0)):
                continue
            before = line[max(0, match.start() - 15):match.start()]
            if _REF_CONTEXT.search(before):
                continue
            if match.start() > 0 and _BRACKET_CITATION.match(
                line[match.start() - 1:match.end() + 1]
            ):
                continue
            found.append(Untagged(str(path), number, line.strip()))
    return found
```

在 `tools/ccfa/trace_claims.py` 中：import 行改为 `from ccfa.dataval import Tag, find_tags, find_untagged`；`check` 签名追加 `untagged: bool = False`；**函数体第一行加 `docs = list(docs)`**（`find_tags` 会消费迭代器，后面的 advisory 循环还要再遍历一遍）；在 `return problems, []` 之前插入：

```python
    advisories: list[Problem] = []
    if untagged:
        for doc in docs:
            for item in find_untagged(Path(doc)):
                advisories.append(
                    Problem(
                        "untagged-number",
                        item.path,
                        item.line,
                        f"未标记的数字线索（需人工复核）: {item.text}",
                    )
                )
```

并把返回改为 `return problems, advisories`。`main` 中加 `parser.add_argument("--untagged", action="store_true")`，调用改为 `check(docs, base_dir, args.tolerance, args.rel_tolerance, untagged=args.untagged)`。

注意：`docs` 是可迭代对象，`find_tags(docs)` 已消费一次；若传入生成器会被耗尽。`check` 的调用方传的是 list，测试也传 list——为稳妥，在 `check` 开头写 `docs = list(docs)`。

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 186 tests`，`OK`（178 + 6 + 2）。

判别力检查：把 `find_untagged` 里 `_YEAR` 判定那行删掉，`test_year_is_skipped` 必须失败；恢复。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/dataval.py tools/ccfa/trace_claims.py tools/tests/test_dataval.py tools/tests/test_trace_claims.py
git commit -m "feat: list untagged numeric candidates as advisories"
```

---

### Task 7: 端到端回归

**Files:**
- Create: `tools/tests/test_trace_claims_e2e.py`

**Interfaces:**
- Consumes: 前六个任务的全部产出，通过子进程调用 CLI
- Produces: 一条把干净、失配、工具错误、越界、advisory 五类输入都跑到真实退出码上的回归

理由同 citation-guard：前六个任务的测试都在进程内调用函数，证明不了命令行入口、参数解析、`PYTHONPATH`、UTF-8 输出与退出码这五者串起来是通的。

- [ ] **Step 1: 写测试**

创建 `tools/tests/test_trace_claims_e2e.py`：

```python
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
CLI = TOOLS_ROOT / "ccfa" / "trace_claims.py"


class TestTraceClaimsEndToEnd(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.doc = self.root / "main.tex"
        (self.root / "results.json").write_text(
            json.dumps({"summary": {"lcoe": 0.14285714285714285}}), encoding="utf-8"
        )

    def _run(self, *extra):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(TOOLS_ROOT)
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--doc",
                str(self.doc),
                "--base-dir",
                str(self.root),
                *extra,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def test_clean_run_exits_zero_with_parseable_json(self):
        self.doc.write_text(
            "\\dataval{results.json:summary.lcoe}{0.143}", encoding="utf-8"
        )
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problem_count"], 0)

    def test_mismatch_exits_one_and_names_the_location(self):
        self.doc.write_text(
            "\\dataval{results.json:summary.lcoe}{0.5}", encoding="utf-8"
        )
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problems"][0]["code"], "dataval-mismatch")
        self.assertIn("main.tex:1", result.stderr)

    def test_missing_document_exits_two_with_empty_stdout(self):
        self.doc.unlink()
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_path_escape_is_a_problem_not_a_tool_error(self):
        self.doc.write_text("\\dataval{../outside.json:x}{1}", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problems"][0]["code"], "dataval-error")

    def test_untagged_flag_exits_zero_with_advisory_json(self):
        self.doc.write_text("Accuracy was 92.5 percent.", encoding="utf-8")
        result = self._run("--untagged")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problem_count"], 0)
        self.assertEqual(payload["advisories"][0]["code"], "untagged-number")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认通过**

Expected: `Ran 191 tests`，`OK`（186 + 5）。

若 `test_missing_document_exits_two_with_empty_stdout` 失败，修 `trace_claims.main`，不要改这条测试的期望值。

- [ ] **Step 3: 全套件回归**

Run: 全局测试命令（见 Global Constraints）

Expected: `Ran 191 tests`，`OK`，输出无噪声（无 JSON 泄漏到控制台）。

- [ ] **Step 4: 提交**

```powershell
git add tools/tests/test_trace_claims_e2e.py
git commit -m "test: add trace-claims end-to-end regression"
```

---

## 验收

```powershell
$root = "<repo-root>"
cd $root
& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v
```

期望：基线 **125** + 本计划新增 **66**（7 + 7 + 15 + 14 + 10 + 8 + 5），共 **191** 个测试通过。

按 spec v4 第 12 节逐条核对：

- 凭空改掉一个 `\dataval` 数字 → 退出码 1 且报 `dataval-mismatch`。
- 正文写 `0.143`、源值 `0.142857…` → 不报错。
- 含字面点的键（`sweep.0\.5x_4ms.stat`）与 CSV 行寻址（`4.lcoe`）→ 能解析（Task 3 单测直接覆盖）。
- `../` 逃逸 → problem（1）；被检查文档不存在 → 工具错误（2）。
- `--untagged` → advisory 出现在 JSON 且退出码保持 0。
- 检查类工具只读：全程未写入被检查文件。

已知边界（不在本计划范围，留给最终全分支评审）：

- 标签的 claimed 值含 `}` 时正则截断（嵌套花括号不支持）。
- 源文件路径含 `:`（如 Windows 盘符）不被接受——这是有意的，spec 要求相对路径。
- 标签与被检查文档同为 UTF-8；非 UTF-8 文件按替换字符读取，不做编码嗅探。
- `find_tags` 对不可读文件静默跳过；`_documents` 已先行校验 `is_file()`，但 TOCTOU 窗口存在。

## 后续计划（不在本计划范围）

按 spec v4 第 6.1 节，其余七项各成计划：终稿与编译检查（`latex-check`、`final-check`、图表 manifest）、证据追踪（`provenance`、`run-log`、`research-version`）、复现与摩擦日志（`repro-package`、`friction-log`）、知识层（FTS5 索引、记忆文件）、自动化与评审（定时任务、`codex exec` 跨模型评审）。参考实现在 `<home>/Documents/Codex/2026-10-03/wo/work/gh-clones/research-suite/`（MIT），每个计划开工前做同样的代码级深读。
