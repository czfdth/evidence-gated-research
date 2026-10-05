# 引用守卫 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一个只读的引用守卫，使论文里的每一条引用都能追溯到检索期核验过的条目，并让"写作阶段新造参考文献"这件事在退出码上暴露出来。

**Architecture:** 核心不是内部一致性检查，而是核验台账。幻觉引用的典型形态是同时编造 `\cite` 键与其对应的 bib 条目——只比对两者是否匹配，恰好会放过它。因此本计划引入 `citation-ledger.json`：记录每个 bib 键在检索期的核验结果。守卫只信台账，不信 bib 本身。工具全部只读，不改稿。

**Tech Stack:** Python 3.12、stdlib `unittest`、`bibtexparser`（唯一新增依赖，装在既定 venv 内）、Crossref 与 DataCite REST API。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（§6.1 工具表、§6.1.1 通用接口契约、§6.2 终稿检查）

## Global Constraints

- 仓库根：`<repo-root>`
- 测试命令：`& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
- 退出码语义：`0` 通过，`1` 发现问题，`2` 工具自身出错。三者不得合并。
- 输出契约：机器可读 JSON 到 stdout，人读摘要到 stderr，两者分离。
- 检查类工具**只读**，不得写入任何被检查的文件。
- 所有文本文件 UTF-8 无 BOM；默认 ASCII 注释，中文只出现在面向用户的文案里。
- 不得写入或提交含用户名的绝对路径。
- 离线是默认模式：联网核验必须显式开启，且测试套件不得依赖网络。
- 现有 60 个测试必须继续通过。

---

## File Structure

| 路径 | 职责 |
| --- | --- |
| `tools/ccfa/cli.py` | 退出码与输出契约的单一实现，供本计划及后续工具复用 |
| `tools/ccfa/texscan.py` | 扫描 `.tex`，提取被引用的键及其位置 |
| `tools/ccfa/bib.py` | 载入 `.bib`，给出键、DOI、标题 |
| `tools/ccfa/citation_ledger.py` | 载入并校验核验台账 |
| `tools/ccfa/doi_lookup.py` | 对单个 DOI 查询 Crossref / DataCite |
| `tools/ccfa/citation_guard.py` | 装配上述模块的 CLI |
| `tools/tests/test_cli.py` | 契约测试 |
| `tools/tests/test_texscan.py` | 扫描器测试 |
| `tools/tests/test_bib.py` | bib 载入测试 |
| `tools/tests/test_citation_ledger.py` | 台账测试 |
| `tools/tests/test_doi_lookup.py` | DOI 查询测试（HTTP 层被替换） |
| `tools/tests/test_citation_guard.py` | 守卫的行为测试 |
| `tools/tests/test_citation_guard_e2e.py` | 端到端回归 |

依赖方向单向：`citation_guard.py` 依赖其余五个模块；其余模块之间不互相依赖。

---

### Task 1: 共享 CLI 契约

**Files:**
- Create: `tools/ccfa/cli.py`
- Create: `tools/tests/test_cli.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `Problem = NamedTuple("Problem", [("code", str), ("path", str), ("line", int | None), ("message", str)])`
  - `render_report(problems: list[Problem], advisories: list[Problem]) -> dict`
  - `emit(problems: list[Problem], advisories: list[Problem] = []) -> int` — 写 stdout/stderr，返回 0 或 1
  - `tool_error(message: str) -> int` — 写 stderr，返回 2

- [ ] **Step 1: 写失败测试**

`tools/tests/test_cli.py`：

```python
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

from ccfa.cli import Problem, emit, render_report, tool_error


class TestRenderReport(unittest.TestCase):
    def test_report_shape_with_no_problems(self):
        report = render_report([], [])
        self.assertEqual(report, {"problems": [], "advisories": [], "problem_count": 0})

    def test_problem_is_serialized_with_all_fields(self):
        problem = Problem("dangling-cite", "manuscript/main.tex", 42, "引用键不存在: foo")
        report = render_report([problem], [])
        self.assertEqual(
            report["problems"],
            [
                {
                    "code": "dangling-cite",
                    "path": "manuscript/main.tex",
                    "line": 42,
                    "message": "引用键不存在: foo",
                }
            ],
        )

    def test_advisories_do_not_count_as_problems(self):
        advisory = Problem("orphan-entry", "manuscript/references.bib", None, "条目从未被引用: bar")
        report = render_report([], [advisory])
        self.assertEqual(report["problem_count"], 0)
        self.assertEqual(len(report["advisories"]), 1)


class TestEmit(unittest.TestCase):
    def _emit(self, problems, advisories=()):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = emit(list(problems), list(advisories))
        return code, out.getvalue(), err.getvalue()

    def test_clean_run_exits_zero_and_emits_empty_json(self):
        code, out, _ = self._emit([])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["problem_count"], 0)

    def test_problem_run_exits_one(self):
        code, out, _ = self._emit([Problem("dangling-cite", "a.tex", 1, "x")])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["problem_count"], 1)

    def test_human_summary_goes_to_stderr_with_location(self):
        _, _, err = self._emit([Problem("dangling-cite", "a.tex", 7, "引用键不存在: foo")])
        self.assertIn("a.tex:7", err)

    def test_missing_line_does_not_emit_a_bare_colon(self):
        _, _, err = self._emit([Problem("orphan-entry", "a.bib", None, "从未被引用: bar")])
        self.assertIn("a.bib:", err)
        self.assertNotIn("a.bib:None", err)

    def test_stdout_stays_machine_readable(self):
        _, out, err = self._emit([Problem("dangling-cite", "a.tex", 1, "x")])
        json.loads(out)  # 抛异常即失败
        self.assertNotIn("a.tex", out)
        self.assertIn("a.tex", err)


class TestToolError(unittest.TestCase):
    def test_tool_error_exits_two_and_writes_stderr(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = tool_error("找不到 bib 文件")
        self.assertEqual(code, 2)
        self.assertIn("找不到 bib 文件", err.getvalue())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest tests.test_cli -v`
（在 `<repo-root>/tools` 目录下运行，或沿用 discover 命令加 `-k cli`）
Expected: FAIL，`ModuleNotFoundError: No module named 'ccfa.cli'`

- [ ] **Step 3: 实现**

`tools/ccfa/cli.py`：

```python
"""Shared exit-code and output contract for paper-template tools.

Machine-readable JSON goes to stdout; the human summary goes to stderr.
Exit codes: 0 clean, 1 problems found, 2 tool error. They are never merged.
"""

from __future__ import annotations

import json
import sys
from typing import NamedTuple


class Problem(NamedTuple):
    code: str
    path: str
    line: int | None
    message: str


def _location(problem: Problem) -> str:
    if problem.line is None:
        return f"{problem.path}:"
    return f"{problem.path}:{problem.line}"


def render_report(problems: list[Problem], advisories: list[Problem]) -> dict:
    return {
        "problems": [dict(problem._asdict()) for problem in problems],
        "advisories": [dict(advisory._asdict()) for advisory in advisories],
        "problem_count": len(problems),
    }


def emit(problems: list[Problem], advisories: list[Problem] | None = None) -> int:
    advisories = advisories or []
    print(json.dumps(render_report(problems, advisories), ensure_ascii=False))
    for problem in problems:
        print(f"{_location(problem)} {problem.code}: {problem.message}", file=sys.stderr)
    for advisory in advisories:
        print(f"{_location(advisory)} {advisory.code}: {advisory.message}", file=sys.stderr)
    return 1 if problems else 0


def tool_error(message: str) -> int:
    print(f"工具错误: {message}", file=sys.stderr)
    return 2
```

- [ ] **Step 4: 运行测试确认通过**

Run: discover 命令
Expected: PASS，本任务新增 9 个测试，总数 69。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/cli.py tools/tests/test_cli.py
git commit -m "feat: add shared CLI exit-code and output contract"
```

---

### Task 2: LaTeX 引用扫描

**Files:**
- Create: `tools/ccfa/texscan.py`
- Create: `tools/tests/test_texscan.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `Location = NamedTuple("Location", [("path", str), ("line", int)])`
  - `find_cited_keys(paths: Iterable[Path]) -> dict[str, list[Location]]` — 键 → 出现位置，按位置排序
  - `iter_tex_files(root: Path) -> list[Path]` — 递归收集 `.tex`，排序返回

- [ ] **Step 1: 写失败测试**

`tools/tests/test_texscan.py`：

```python
import tempfile
import unittest
from pathlib import Path

from ccfa.texscan import find_cited_keys, iter_tex_files


def _write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestIterTexFiles(unittest.TestCase):
    def test_collects_recursively_and_sorts(self):
        root = Path(tempfile.mkdtemp())
        _write(root, "b.tex", "")
        _write(root, "sub/a.tex", "")
        _write(root, "notes.txt", "not latex")
        names = [p.name for p in iter_tex_files(root)]
        self.assertEqual(names, ["b.tex", "a.tex"])

    def test_missing_directory_returns_empty(self):
        self.assertEqual(iter_tex_files(Path(tempfile.mkdtemp()) / "nope"), [])


class TestFindCitedKeys(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _scan(self, body: str):
        path = _write(self.root, "main.tex", body)
        return find_cited_keys([path]), path

    def test_plain_cite(self):
        keys, path = self._scan(r"See \cite{vaswani2017attention}.")
        self.assertEqual(list(keys), ["vaswani2017attention"])
        self.assertEqual(keys["vaswani2017attention"][0].line, 1)

    def test_multiple_keys_in_one_command(self):
        keys, _ = self._scan(r"\cite{alpha, beta ,gamma}")
        self.assertEqual(sorted(keys), ["alpha", "beta", "gamma"])

    def test_cite_variants(self):
        keys, _ = self._scan(r"\citep{a} \citet{b} \citeauthor{c} \cite[p.~3]{d}")
        self.assertEqual(sorted(keys), ["a", "b", "c", "d"])

    def test_optional_argument_with_braces_inside_is_handled(self):
        keys, _ = self._scan(r"\cite[see {Sec.} 3]{e}")
        self.assertEqual(list(keys), ["e"])

    def test_commented_line_is_ignored(self):
        keys, _ = self._scan("% \\cite{ghost}\n\\cite{real}")
        self.assertEqual(list(keys), ["real"])

    def test_escaped_percent_does_not_start_a_comment(self):
        keys, _ = self._scan("100\\% of \\cite{kept}")
        self.assertEqual(list(keys), ["kept"])

    def test_repeated_key_records_every_location(self):
        keys, path = self._scan("\\cite{a}\ntext\n\\cite{a}")
        locations = keys["a"]
        self.assertEqual([loc.line for loc in locations], [1, 3])
        self.assertEqual([loc.path for loc in locations], [str(path)] * 2)

    def test_no_citations_yields_empty_mapping(self):
        keys, _ = self._scan("Plain text only.")
        self.assertEqual(keys, {})

    def test_multiple_files_are_merged(self):
        first = _write(self.root, "one.tex", r"\cite{a}")
        second = _write(self.root, "two.tex", r"\cite{b}")
        keys = find_cited_keys([first, second])
        self.assertEqual(sorted(keys), ["a", "b"])

    def test_unreadable_file_is_skipped_not_crashed(self):
        missing = self.root / "gone.tex"
        keys = find_cited_keys([missing])
        self.assertEqual(keys, {})
```

- [ ] **Step 2: 运行测试确认失败**

Run: discover 命令
Expected: FAIL，`ModuleNotFoundError: No module named 'ccfa.texscan'`

- [ ] **Step 3: 实现**

`tools/ccfa/texscan.py`：

```python
"""Scan .tex files for citation keys.

Comment handling matters: a commented-out \\cite must not count as a real
reference, and an escaped percent (\\%) must not start a comment.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, NamedTuple


class Location(NamedTuple):
    path: str
    line: int


_CITE = re.compile(r"\\cite[a-zA-Z]*\s*(?:\[[^\]]*\]\s*)?\{([^}]*)\}")
# A percent starts a comment only when it is not backslash-escaped.
_COMMENT = re.compile(r"(?<!\\)%")


def iter_tex_files(root: Path) -> list[Path]:
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(root.rglob("*.tex"))


def _strip_comment(line: str) -> str:
    match = _COMMENT.search(line)
    return line[: match.start()] if match else line


def find_cited_keys(paths: Iterable[Path]) -> dict[str, list[Location]]:
    found: dict[str, list[Location]] = {}
    for path in paths:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, raw_line in enumerate(text.splitlines(), start=1):
            line = _strip_comment(raw_line)
            for match in _CITE.finditer(line):
                for key in match.group(1).split(","):
                    key = key.strip()
                    if key:
                        found.setdefault(key, []).append(Location(str(path), number))
    return found
```

- [ ] **Step 4: 运行测试确认通过**

Run: discover 命令
Expected: PASS，本任务新增 11 个测试，总数 80。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/texscan.py tools/tests/test_texscan.py
git commit -m "feat: scan LaTeX sources for citation keys"
```

---

### Task 3: BibTeX 载入

**Files:**
- Create: `tools/ccfa/bib.py`
- Create: `tools/tests/test_bib.py`
- Modify: `tools/pyproject.toml`（加 `bibtexparser` 依赖）

**Interfaces:**
- Consumes: 无
- Produces:
  - `BibEntry = NamedTuple("BibEntry", [("key", str), ("doi", str | None), ("title", str | None)])`
  - `load_entries(path: Path) -> dict[str, BibEntry]`，文件缺失或不可解析抛 `ValueError`

- [ ] **Step 1: 安装依赖**

```powershell
$root = "<repo-root>"
& "$root/tools/.venv/Scripts/python.exe" -m pip install --quiet --disable-pip-version-check bibtexparser
& "$root/tools/.venv/Scripts/python.exe" -c "import bibtexparser, inspect; print(bibtexparser.__version__); print([n for n in dir(bibtexparser) if not n.startswith('_')])"
```

Expected: 安装成功，打印 `2.1.0` 与顶层名字列表。

**控制器已在 2026-10-03 于本机实测该版本的 API**，实现代码据此写成，不要凭其他版本的记忆改写：

| 需求 | 确认过的用法 |
| --- | --- |
| 解析字符串 | `bibtexparser.parse_string(text)` 返回 `Library` |
| 遍历条目 | `library.entries` 是 `Entry` 列表；`library.entries_dict` 是键到条目的映射 |
| 取键 | `entry.key` |
| 取字段 | `entry.fields_dict["doi"]`，是普通 dict，支持 `.get`；字段对象有 `.value` |
| 检测坏块 | `library.failed_blocks`：重复键为 `DuplicateBlockKeyBlock`，语法错误为 `ParsingFailedBlock` |

另外实测两点：嵌套花括号会原样留在字段值里（`{The {GPU} Story}` 得到 `The {GPU} Story`），因此标题需要清理花括号；空文件不产生 `failed_blocks`，只有真正的问题才会。

`tools/pyproject.toml` 的 `dependencies` 追加 `"bibtexparser>=2.0"`。

- [ ] **Step 2: 写失败测试**

`tools/tests/test_bib.py`：

```python
import tempfile
import unittest
from pathlib import Path

from ccfa.bib import load_entries

SAMPLE = r"""
@inproceedings{vaswani2017attention,
  title     = {Attention Is All You Need},
  author    = {Vaswani, Ashish},
  doi       = {10.48550/arXiv.1706.03762},
  year      = {2017}
}

@article{noDOIentry,
  title = {An Entry Without a DOI},
  year  = {2020}
}

@misc{braces{in}key,
  title = {Weird}
}
"""


def _bib(text: str) -> Path:
    path = Path(tempfile.mkdtemp()) / "references.bib"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadEntries(unittest.TestCase):
    def test_reads_key_doi_and_title(self):
        entries = load_entries(_bib(SAMPLE))
        self.assertIn("vaswani2017attention", entries)
        entry = entries["vaswani2017attention"]
        self.assertEqual(entry.doi, "10.48550/arXiv.1706.03762")
        self.assertEqual(entry.title, "Attention Is All You Need")

    def test_entry_without_doi_has_none(self):
        entries = load_entries(_bib(SAMPLE))
        self.assertIsNone(entries["noDOIentry"].doi)

    def test_title_braces_are_preserved_as_text(self):
        entries = load_entries(_bib('@misc{k, title = {The {GPU} Story}}'))
        self.assertIn("GPU", entries["k"].title)

    def test_empty_file_yields_no_entries(self):
        self.assertEqual(load_entries(_bib("")), {})

    def test_missing_file_raises_value_error(self):
        with self.assertRaises(ValueError):
            load_entries(Path(tempfile.mkdtemp()) / "nope.bib")

    def test_doi_is_normalized_to_lowercase_without_prefix(self):
        entries = load_entries(_bib('@misc{k, doi = {https://doi.org/10.1/AbC}}'))
        self.assertEqual(entries["k"].doi, "10.1/abc")

    def test_duplicate_key_raises_value_error(self):
        text = "@misc{dup, title={A}}\n@misc{dup, title={B}}\n"
        with self.assertRaises(ValueError):
            load_entries(_bib(text))
```

- [ ] **Step 3: 运行测试确认失败**

Run: discover 命令
Expected: FAIL，`ModuleNotFoundError: No module named 'ccfa.bib'`

- [ ] **Step 4: 实现**

`tools/ccfa/bib.py`：

```python
"""Load a BibTeX file into a key -> entry mapping.

DOI values are normalized: a URL prefix is stripped and the result is
lowercased, so the same DOI written two ways compares equal.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import bibtexparser


class BibEntry(NamedTuple):
    key: str
    doi: str | None
    title: str | None


_DOI_URL_PREFIX = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
_BRACES = re.compile(r"[{}]")


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip()
    doi = _DOI_URL_PREFIX.sub("", doi)
    return doi.lower() or None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return _BRACES.sub("", value).strip() or None


def load_entries(path: Path) -> dict[str, BibEntry]:
    """Return entries by key. Raises ValueError on a missing or invalid file."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc

    library = bibtexparser.parse_string(text)
    if library.failed_blocks:
        kinds = ", ".join(type(block).__name__ for block in library.failed_blocks)
        raise ValueError(f"BibTeX 解析失败于 {path}: {kinds}")

    entries: dict[str, BibEntry] = {}
    for entry in library.entries:
        fields = entry.fields_dict
        doi = fields.get("doi")
        title = fields.get("title")
        entries[entry.key] = BibEntry(
            key=entry.key,
            doi=normalize_doi(doi.value if doi else None),
            title=_clean(title.value if title else None),
        )
    return entries
```

重复键与语法错误一律让整个文件失败，而不是丢弃坏块后继续——静默丢条目正是这个工具存在的理由所要防的事。

- [ ] **Step 5: 运行测试确认通过**

Run: discover 命令
Expected: PASS，本任务新增 7 个测试，总数 87。

- [ ] **Step 6: 提交**

```powershell
git add tools/pyproject.toml tools/ccfa/bib.py tools/tests/test_bib.py
git commit -m "feat: load BibTeX entries with normalized DOIs"
```

---

### Task 4: 核验台账

**Files:**
- Create: `tools/ccfa/citation_ledger.py`
- Create: `tools/tests/test_citation_ledger.py`

**Interfaces:**
- Consumes: `ccfa.bib.normalize_doi`
- Produces:
  - `LedgerRecord = NamedTuple("LedgerRecord", [("key", str), ("doi", str | None), ("status", str), ("verified_at", str), ("source", str)])`
  - `VALID_STATUSES = ("verified", "unverified", "failed")`
  - `load_ledger(path: Path) -> dict[str, LedgerRecord]`，缺失或非法抛 `ValueError`

台账是本计划的机制核心：bib 文件可以被任何一次编辑改动，台账是"这个键在检索期被核验过"的独立记录。守卫只承认台账里状态为 `verified` 的键。

- [ ] **Step 1: 写失败测试**

`tools/tests/test_citation_ledger.py`：

```python
import json
import tempfile
import unittest
from pathlib import Path

from ccfa.citation_ledger import VALID_STATUSES, load_ledger

GOOD = {
    "version": 1,
    "entries": {
        "vaswani2017attention": {
            "doi": "10.48550/arxiv.1706.03762",
            "status": "verified",
            "verified_at": "2026-10-03T12:00:00Z",
            "source": "crossref",
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

    def test_all_declared_statuses_are_accepted(self):
        for status in VALID_STATUSES:
            with self.subTest(status=status):
                payload = {
                    "version": 1,
                    "entries": {"k": {"status": status, "verified_at": "", "source": ""}},
                }
                self.assertEqual(load_ledger(_ledger(payload))["k"].status, status)
```

- [ ] **Step 2: 运行测试确认失败**

Run: discover 命令
Expected: FAIL，`ModuleNotFoundError: No module named 'ccfa.citation_ledger'`

- [ ] **Step 3: 实现**

`tools/ccfa/citation_ledger.py`：

```python
"""Load the citation verification ledger.

This ledger is the record of what was checked at retrieval time. It is what
separates "a key that exists because someone verified it" from "a key that
exists because a model typed it".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

from ccfa.bib import normalize_doi

VALID_STATUSES = ("verified", "unverified", "failed")


class LedgerRecord(NamedTuple):
    key: str
    doi: str | None
    status: str
    verified_at: str
    source: str


def load_ledger(path: Path) -> dict[str, LedgerRecord]:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取台账 {path}: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"台账不是合法 JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("台账顶层必须是对象")
    if "version" not in data:
        raise ValueError("台账缺少 version 字段")
    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("台账 entries 必须是对象")

    records: dict[str, LedgerRecord] = {}
    for key, value in entries.items():
        if not isinstance(value, dict):
            raise ValueError(f"台账条目 {key} 必须是对象")
        status = value.get("status")
        if status not in VALID_STATUSES:
            raise ValueError(
                f"台账条目 {key} 的 status 非法: {status!r}，应为 {' / '.join(VALID_STATUSES)}"
            )
        records[key] = LedgerRecord(
            key=key,
            doi=normalize_doi(value.get("doi")),
            status=status,
            verified_at=str(value.get("verified_at", "")),
            source=str(value.get("source", "")),
        )
    return records
```

- [ ] **Step 4: 运行测试确认通过**

Run: discover 命令
Expected: PASS，本任务新增 10 个测试，总数 97。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/citation_ledger.py tools/tests/test_citation_ledger.py
git commit -m "feat: load the citation verification ledger"
```

---

### Task 5: 守卫本体（离线）

**Files:**
- Create: `tools/ccfa/citation_guard.py`
- Create: `tools/tests/test_citation_guard.py`

**Interfaces:**
- Consumes: `ccfa.cli`、`ccfa.texscan`、`ccfa.bib`、`ccfa.citation_ledger`
- Produces:
  - `check(manuscript: Path, bib_path: Path, ledger_path: Path) -> tuple[list[Problem], list[Problem]]`
  - `main(argv: list[str]) -> int`，参数 `--manuscript`、`--bib`、`--ledger`

检查项与归类的对应关系是本任务的规格，不得改动：

| 条件 | code | 归类 |
| --- | --- | --- |
| 正文引用了 bib 里没有的键 | `dangling-cite` | problem |
| bib 里有键，但台账无记录，或状态不是 `verified` | `unverified-entry` | problem |
| 两个 bib 条目的 DOI 相同 | `duplicate-doi` | problem |
| bib 条目从未被正文引用 | `orphan-entry` | advisory |

`orphan-entry` 归为 advisory 而非 problem：留着未被引用的条目是整洁问题，不是可信性问题，不应该让守卫失败。advisory 仍会出现在 JSON 与 stderr 中。

- [ ] **Step 1: 写失败测试**

`tools/tests/test_citation_guard.py`：

```python
import json
import tempfile
import unittest
from pathlib import Path

from ccfa.citation_guard import check, main

BIB = r"""
@misc{good, doi = {10.1/ok}}
@misc{unverified, doi = {10.1/unverified}}
@misc{orphan, doi = {10.1/orphan}}
@misc{dupa, doi = {10.1/same}}
@misc{dupb, doi = {10.1/same}}
"""

LEDGER = {
    "version": 1,
    "entries": {
        "good": {"status": "verified", "doi": "10.1/ok"},
        "unverified": {"status": "unverified", "doi": "10.1/unverified"},
        "orphan": {"status": "verified", "doi": "10.1/orphan"},
        "dupa": {"status": "verified", "doi": "10.1/same"},
        "dupb": {"status": "verified", "doi": "10.1/same"},
    },
}


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "manuscript").mkdir()
        self.bib = self.root / "references.bib"
        self.bib.write_text(BIB, encoding="utf-8")
        self.ledger = self.root / "citation-ledger.json"
        self.ledger.write_text(json.dumps(LEDGER), encoding="utf-8")

    def cite(self, body: str):
        (self.root / "manuscript" / "main.tex").write_text(body, encoding="utf-8")

    def run_check(self):
        return check(self.root / "manuscript", self.bib, self.ledger)

    @staticmethod
    def codes(problems):
        return sorted(p.code for p in problems)


class TestCheck(BaseCase):
    def test_clean_manuscript_has_no_problems(self):
        # 用一份全部已核验的最小语料。共享 fixture 里含有故意置为 unverified
        # 的条目，而守卫要求 bib 中每个条目都已核验——不论是否被引用。
        self.bib.write_text("@misc{good, doi = {10.1/ok}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps({"version": 1, "entries": {"good": {"status": "verified"}}}),
            encoding="utf-8",
        )
        self.cite(r"\cite{good}")
        problems, advisories = self.run_check()
        self.assertEqual(problems, [], problems)
        self.assertEqual(advisories, [])

    def test_dangling_cite_is_a_problem_with_location(self):
        self.cite(r"\cite{ghost}")
        problems, _ = self.run_check()
        self.assertIn("dangling-cite", self.codes(problems))
        dangling = [p for p in problems if p.code == "dangling-cite"][0]
        self.assertIn("ghost", dangling.message)
        self.assertEqual(dangling.line, 1)
        self.assertTrue(dangling.path.endswith("main.tex"))

    def test_unverified_entry_is_a_problem(self):
        self.cite(r"\cite{good} \cite{unverified}")
        problems, _ = self.run_check()
        self.assertIn("unverified-entry", self.codes(problems))

    def test_entry_missing_from_ledger_is_a_problem(self):
        self.cite(r"\cite{good}")
        self.ledger.write_text(json.dumps({"version": 1, "entries": {}}), encoding="utf-8")
        problems, _ = self.run_check()
        self.assertIn("unverified-entry", self.codes(problems))

    def test_duplicate_doi_is_a_problem(self):
        self.cite(r"\cite{good} \cite{dupa} \cite{dupb}")
        problems, _ = self.run_check()
        self.assertIn("duplicate-doi", self.codes(problems))

    def test_orphan_entry_is_only_an_advisory(self):
        self.cite(r"\cite{good}")
        problems, advisories = self.run_check()
        self.assertNotIn("orphan-entry", self.codes(problems))
        self.assertIn("orphan-entry", self.codes(advisories))

    def test_entry_without_doi_is_not_a_duplicate(self):
        self.bib.write_text("@misc{a, title={A}}\n@misc{b, title={B}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": {
                        "a": {"status": "verified"},
                        "b": {"status": "verified"},
                    },
                }
            ),
            encoding="utf-8",
        )
        self.cite(r"\cite{a} \cite{b}")
        problems, _ = self.run_check()
        self.assertNotIn("duplicate-doi", self.codes(problems))


class TestMain(BaseCase):
    def test_clean_run_exits_zero(self):
        self.cite(r"\cite{good}")
        code = main(
            [
                "citation_guard.py",
                "--manuscript",
                str(self.root / "manuscript"),
                "--bib",
                str(self.bib),
                "--ledger",
                str(self.ledger),
            ]
        )
        self.assertEqual(code, 0)

    def test_problem_run_exits_one(self):
        self.cite(r"\cite{ghost}")
        code = main(
            [
                "citation_guard.py",
                "--manuscript",
                str(self.root / "manuscript"),
                "--bib",
                str(self.bib),
                "--ledger",
                str(self.ledger),
            ]
        )
        self.assertEqual(code, 1)

    def test_missing_bib_exits_two(self):
        self.cite(r"\cite{good}")
        code = main(
            [
                "citation_guard.py",
                "--manuscript",
                str(self.root / "manuscript"),
                "--bib",
                str(self.root / "nope.bib"),
                "--ledger",
                str(self.ledger),
            ]
        )
        self.assertEqual(code, 2)
```

- [ ] **Step 2: 运行测试确认失败**

Run: discover 命令
Expected: FAIL，`ModuleNotFoundError: No module named 'ccfa.citation_guard'`

- [ ] **Step 3: 实现**

`tools/ccfa/citation_guard.py`：

```python
"""Report citations that cannot be trusted.

Read-only. Never edits the manuscript or the bibliography.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ccfa.bib import load_entries
from ccfa.citation_ledger import load_ledger
from ccfa.cli import Problem, emit, tool_error
from ccfa.texscan import find_cited_keys, iter_tex_files


def check(
    manuscript: Path,
    bib_path: Path,
    ledger_path: Path,
) -> tuple[list[Problem], list[Problem]]:
    cited = find_cited_keys(iter_tex_files(Path(manuscript)))
    entries = load_entries(Path(bib_path))
    ledger = load_ledger(Path(ledger_path))

    problems: list[Problem] = []
    advisories: list[Problem] = []

    for key, locations in sorted(cited.items()):
        if key not in entries:
            for location in locations:
                problems.append(
                    Problem(
                        "dangling-cite",
                        location.path,
                        location.line,
                        f"正文引用了文献表中不存在的键: {key}",
                    )
                )

    for key in sorted(entries):
        record = ledger.get(key)
        if record is None or record.status != "verified":
            reason = "台账中无记录" if record is None else f"台账状态为 {record.status}"
            problems.append(
                Problem(
                    "unverified-entry",
                    str(bib_path),
                    None,
                    f"条目未通过检索期核验（{reason}）: {key}",
                )
            )

    by_doi: dict[str, list[str]] = {}
    for key, entry in entries.items():
        if entry.doi:
            by_doi.setdefault(entry.doi, []).append(key)
    for doi, keys in sorted(by_doi.items()):
        if len(keys) > 1:
            problems.append(
                Problem(
                    "duplicate-doi",
                    str(bib_path),
                    None,
                    f"DOI {doi} 被多个条目共用: {', '.join(sorted(keys))}",
                )
            )

    for key in sorted(entries):
        if key not in cited:
            advisories.append(
                Problem(
                    "orphan-entry",
                    str(bib_path),
                    None,
                    f"条目从未被正文引用: {key}",
                )
            )

    return problems, advisories


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="检查引用的可信性")
    parser.add_argument("--manuscript", required=True)
    parser.add_argument("--bib", required=True)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args(argv[1:])

    try:
        problems, advisories = check(
            Path(args.manuscript), Path(args.bib), Path(args.ledger)
        )
    except ValueError as exc:
        return tool_error(str(exc))

    return emit(problems, advisories)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: 运行测试确认通过**

Run: discover 命令
Expected: PASS，本任务新增 10 个测试，总数 107。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/citation_guard.py tools/tests/test_citation_guard.py
git commit -m "feat: detect dangling, unverified and duplicate citations"
```

---

### Task 6: 联网 DOI 核验

**Files:**
- Create: `tools/ccfa/doi_lookup.py`
- Create: `tools/tests/test_doi_lookup.py`
- Modify: `tools/ccfa/citation_guard.py`
- Modify: `tools/tests/test_citation_guard.py`

**Interfaces:**
- Consumes: `ccfa.cli`、`ccfa.bib.normalize_doi`
- Produces:
  - `LookupResult = NamedTuple("LookupResult", [("doi", str), ("found", bool), ("source", str | None), ("detail", str)])`
  - `lookup(doi: str, fetch: Fetcher | None = None, timeout: float = 20.0) -> LookupResult`
  - `Fetcher = Callable[[str, float], tuple[int, str]]`，返回 `(status_code, body)`
  - `check(..., verify_online: bool = False) -> tuple[list[Problem], list[Problem]]`
  - `main` 新增 `--verify-online` 开关，默认关闭

HTTP 用 stdlib `urllib.request`：本机 venv 里没有 `requests`，也不为这一件事引入。`fetch` 参数存在的唯一目的是让测试不碰网络——除默认实现之外的调用路径都不得自行发起网络请求。

控制器实测（2026-10-03）：`https://api.crossref.org/works/<doi>` 与 `https://api.datacite.org/dois/<doi>` 均返回 200；伪造 DOI 在 Crossref 返回 404。请求必须带 `User-Agent`，否则 Crossref 拒绝。

**已知的测试设计取舍**：本计划不写需要真实网络的测试。默认 `fetch` 实现只通过手工验收确认（见验收一节），不进自动化套件——让套件依赖外网会让它在离线时变成噪声源。

- [ ] **Step 1: 写失败测试**

`tools/tests/test_doi_lookup.py`：

```python
import unittest

from ccfa.doi_lookup import lookup


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
        fetch, calls = _fetcher({"crossref.org": (200, "{}")})
        result = lookup("10.1/x", fetch=fetch)
        self.assertTrue(result.found)
        self.assertEqual(result.source, "crossref")
        self.assertEqual(len(calls), 1)

    def test_datacite_is_tried_when_crossref_misses(self):
        fetch, calls = _fetcher({"api.datacite.org": (200, "{}")})
        result = lookup("10.1/x", fetch=fetch)
        self.assertTrue(result.found)
        self.assertEqual(result.source, "datacite")
        self.assertEqual(len(calls), 2)

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
        fetch, calls = _fetcher({"crossref.org": (200, "{}")})
        lookup("https://doi.org/10.1/MiXeD", fetch=fetch)
        self.assertIn("10.1%2Fmixed", calls[0])

    def test_empty_doi_is_not_found_without_a_request(self):
        fetch, calls = _fetcher({"crossref.org": (200, "{}")})
        result = lookup("", fetch=fetch)
        self.assertFalse(result.found)
        self.assertEqual(calls, [])

    def test_url_uses_the_crossref_endpoint(self):
        fetch, calls = _fetcher({"crossref.org": (200, "{}")})
        lookup("10.1/x", fetch=fetch)
        self.assertTrue(calls[0].startswith("https://api.crossref.org/works/"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: discover 命令
Expected: FAIL，`ModuleNotFoundError: No module named 'ccfa.doi_lookup'`

- [ ] **Step 3: 实现**

`tools/ccfa/doi_lookup.py`：

```python
"""Check whether a DOI resolves, via Crossref then DataCite.

Network access is opt-in at the caller level: nothing here runs unless
lookup() is called explicitly.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, NamedTuple

from ccfa.bib import normalize_doi

Fetcher = Callable[[str, float], "tuple[int, str]"]

_ENDPOINTS = (
    ("crossref", "https://api.crossref.org/works/{doi}"),
    ("datacite", "https://api.datacite.org/dois/{doi}"),
)

_USER_AGENT = "paper-template-citation-guard/0.1"


class LookupResult(NamedTuple):
    doi: str
    found: bool
    source: str | None
    detail: str


def _default_fetch(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def lookup(doi: str, fetch: Fetcher | None = None, timeout: float = 20.0) -> LookupResult:
    normalized = normalize_doi(doi)
    if not normalized:
        return LookupResult(doi="", found=False, source=None, detail="DOI 为空")

    fetcher = fetch or _default_fetch
    attempts: list[str] = []
    for source, template in _ENDPOINTS:
        url = template.format(doi=urllib.parse.quote(normalized, safe=""))
        try:
            status, _body = fetcher(url, timeout)
        except OSError as exc:
            attempts.append(f"{source}: 网络错误 {exc}")
            continue
        if status == 200:
            return LookupResult(normalized, True, source, f"{source} 返回 200")
        attempts.append(f"{source}: HTTP {status}")

    return LookupResult(normalized, False, None, "; ".join(attempts))
```

- [ ] **Step 4: 运行测试确认通过**

Run: discover 命令
Expected: PASS，本任务新增 7 个测试，总数 114。

- [ ] **Step 5: 把联网核验接进守卫**

在 `tools/tests/test_citation_guard.py` 追加：

```python
class TestVerifyOnline(BaseCase):
    def test_online_flag_is_off_by_default(self):
        self.cite(r"\cite{good}")
        problems, _ = check(self.root / "manuscript", self.bib, self.ledger)
        self.assertNotIn("doi-not-found", self.codes(problems))

    def test_online_flag_reports_a_dead_doi(self):
        self.cite(r"\cite{good}")
        import ccfa.citation_guard as guard
        from ccfa.doi_lookup import LookupResult

        def fake_lookup(doi, fetch=None, timeout=20.0):
            return LookupResult(doi, False, None, "crossref: HTTP 404")

        original = guard.lookup
        guard.lookup = fake_lookup
        try:
            problems, _ = check(
                self.root / "manuscript", self.bib, self.ledger, verify_online=True
            )
        finally:
            guard.lookup = original
        self.assertIn("doi-not-found", self.codes(problems))
```

在 `citation_guard.py` 中做三处改动：

第一，import 段加 `from ccfa.doi_lookup import lookup`。

第二，`check` 的签名改为 `def check(manuscript, bib_path, ledger_path, verify_online: bool = False)`，并在 problem 收集完成后追加：

```python
    if verify_online:
        for key in sorted(entries):
            doi = entries[key].doi
            if not doi:
                continue
            result = lookup(doi)
            if not result.found:
                problems.append(
                    Problem(
                        "doi-not-found",
                        str(bib_path),
                        None,
                        f"条目 {key} 的 DOI {doi} 无法解析（{result.detail}）",
                    )
                )
```

第三，`main` 的参数解析处加 `parser.add_argument("--verify-online", action="store_true")`，调用 `check` 时传 `verify_online=args.verify_online`。

Run: discover 命令
Expected: PASS，本步骤追加 2 个测试，总数 116。默认路径不发起任何网络请求，整个套件保持离线。

- [ ] **Step 6: 提交**

```powershell
git add tools/ccfa/doi_lookup.py tools/tests/test_doi_lookup.py tools/ccfa/citation_guard.py tools/tests/test_citation_guard.py
git commit -m "feat: verify DOIs against Crossref and DataCite on demand"
```

---

### Task 7: 端到端回归

**Files:**
- Create: `tools/tests/test_citation_guard_e2e.py`

**Interfaces:**
- Consumes: 前六个任务的全部产出，通过子进程调用 CLI
- Produces: 一条把干净引用与脏引用都跑到真实退出码上的回归

这一条存在的理由：前六个任务的测试都在进程内调用函数，无法证明命令行入口、参数解析、`PYTHONPATH`、退出码这三者串起来是通的。而退出码正是这个工具对外唯一的契约。

- [ ] **Step 1: 写失败测试**

`tools/tests/test_citation_guard_e2e.py`：

```python
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
GUARD = TOOLS_ROOT / "ccfa" / "citation_guard.py"


class TestCitationGuardEndToEnd(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "manuscript").mkdir()
        self.bib = self.root / "references.bib"
        self.ledger = self.root / "citation-ledger.json"

    def _run(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(TOOLS_ROOT)
        return subprocess.run(
            [
                sys.executable,
                str(GUARD),
                "--manuscript",
                str(self.root / "manuscript"),
                "--bib",
                str(self.bib),
                "--ledger",
                str(self.ledger),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def _write_clean_inputs(self):
        self.bib.write_text("@misc{good, doi = {10.1/ok}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps({"version": 1, "entries": {"good": {"status": "verified"}}}),
            encoding="utf-8",
        )

    def test_clean_project_exits_zero_with_parseable_json(self):
        self._write_clean_inputs()
        (self.root / "manuscript" / "main.tex").write_text(r"\cite{good}", encoding="utf-8")

        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problem_count"], 0)

    def test_unsupported_citation_exits_one_and_names_the_key(self):
        self._write_clean_inputs()
        (self.root / "manuscript" / "main.tex").write_text(
            r"\cite{good} \cite{invented2026}", encoding="utf-8"
        )

        result = self._run()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problem_count"], 1)
        self.assertEqual(payload["problems"][0]["code"], "dangling-cite")
        self.assertIn("invented2026", result.stderr)
        self.assertIn("main.tex:1", result.stderr)

    def test_bib_entry_without_a_ledger_record_exits_one(self):
        self.bib.write_text("@misc{good, doi = {10.1/ok}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps({"version": 1, "entries": {}}), encoding="utf-8"
        )
        (self.root / "manuscript" / "main.tex").write_text(r"\cite{good}", encoding="utf-8")

        result = self._run()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problems"][0]["code"], "unverified-entry")

    def test_missing_ledger_exits_two_not_one(self):
        self._write_clean_inputs()
        self.ledger.unlink()
        (self.root / "manuscript" / "main.tex").write_text(r"\cite{good}", encoding="utf-8")

        result = self._run()
        self.assertEqual(result.returncode, 2, result.stderr)
```

最后一条是本文件的重点：**缺少台账是工具环境问题（2），不是引用有问题（1）**。这两者混淆会让"检查没跑成"看起来像"检查通过了"或"检查失败了"，是这个项目从一开始就要防的错误。

- [ ] **Step 2: 运行测试确认通过**

Run: discover 命令
Expected: PASS，本任务新增 4 个测试，总数 120。

若 `test_missing_ledger_exits_two_not_one` 失败并返回 1，说明 `load_ledger` 抛出的 `ValueError` 没有被 `main` 的 `except ValueError` 捕获到，或捕获后返回了错误的码——修 `citation_guard.main`，不要改这条测试的期望值。

- [ ] **Step 3: 提交**

```powershell
git add tools/tests/test_citation_guard_e2e.py
git commit -m "test: add citation-guard end-to-end regression"
```

---

## 验收

```powershell
$root = "<repo-root>"
cd $root
& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v
```

期望：既有 **61** 个测试全部仍然通过（基线在本计划编写后因一次残留修复增加了 1 个），加上本计划新增的 60 个（9+11+7+10+10+9+4），共 **121 个测试通过**。

手工验收（唯一需要联网的一步，不进自动化套件）：

```powershell
$root = "<repo-root>"
$env:PYTHONPATH = "$root/tools"
& "$root/tools/.venv/Scripts/python.exe" -c "
from ccfa.doi_lookup import lookup
print('real  :', lookup('10.1109/5.771073'))
print('fake  :', lookup('10.9999/definitely-not-a-real-doi'))
"
```

期望：真实 DOI 报 `found=True source='crossref'`；伪造 DOI 报 `found=False` 且 detail 中同时出现 crossref 与 datacite 的 404。

## 后续计划（不在本计划范围）

`citation-guard` 只覆盖引用。设计文档 §6.1 的其余工具各自独立成计划：

| 计划 | 覆盖 |
| --- | --- |
| 数字守卫 | `trace-claims`、`dataval` 指针解析 |
| 终稿与编译检查 | `latex-check`、`final-check`、图表 manifest |
| 证据追踪 | `provenance`、`run-log`、`research-version` |
| 复现与摩擦日志 | `repro-package`、`friction-log` |
| 知识层 | FTS5 索引器、记忆文件读写 |
| 自动化与评审 | 四类定时任务、`codex exec` 跨模型评审接线 |

其中**数字守卫与本计划是同一类问题**（让机器可判定的东西不要靠模型自述），依赖方向也独立，可以并行推进。
