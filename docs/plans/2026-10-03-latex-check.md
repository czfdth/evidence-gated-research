# latex-check（编译检查）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成 `latex-check`：对 LaTeX 手稿做注释感知的结构校验（花括号、环境、悬空引用、缺图），并在显式开启时按 `pdflatex → bibtex → pdflatex → pdflatex` 四步把文档真正编译出来。

**Architecture:** 三层。`latex_structure` 做纯文本结构扫描与引用/图片检查，复用 `ccfa.texcomment.strip_comment`（已是偶数反斜杠的正确版本，参考实现的同名函数仍有旧缺陷）；`latex_compile` 是四步编译驱动，runner 可注入以便离线测试；`latex_check` 把两者串成 `check()` 与 CLI，输出走 `ccfa.cli` 的既定契约。

**Tech Stack:** Python 3.12（`tools/.venv`）；stdlib `re` / `subprocess` / `shutil`；unittest。编译走本机 MiKTeX 的 `pdflatex`（实测可用），不使用 `latexmk`（缺 Perl）。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v5 第 6.5 节、第 12 节；参考 §7.1 的 MiKTeX 实测）

## Global Constraints

- 仓库根：`<repo-root>`
- 退出码：`0` 通过，`1` 发现问题（含编译失败），`2` 工具自身出错。三者不得合并。
- 机器可读 JSON 走 stdout，人读摘要走 stderr。
- 结构检查模式**只读**；`--compile` 是唯一写盘路径，产物只写在手稿目录内。
- UTF-8 无 BOM；默认 ASCII 注释，中文只出现在面向用户的文案里。
- 不得写入或提交含用户名的绝对路径。
- 基线：**198 个测试通过**，HEAD = `b7054d4`，工作树干净。
- 测试命令：`& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
- 既有接口：`ccfa.cli` 的 `Problem` / `emit` / `tool_error`；`ccfa.texcomment.strip_comment`；`ccfa.texscan.iter_tex_files` / `find_cited_keys`；`ccfa.bib.load_entries`。
- 参考实现：`research-suite/tools/latex-tools/latex_tools.py`（MIT）。其 `strip_comments` 只回溯一个字符，**不得照抄**。

---

### Task 1: 结构扫描（花括号与环境）

**Files:**
- Create: `tools/ccfa/latex_structure.py`
- Create: `tools/tests/test_latex_structure.py`

**Interfaces:**
- Consumes: `ccfa.cli.Problem`、`ccfa.texcomment.strip_comment`
- Produces:
  - `check_braces(path: Path) -> list[Problem]`（code `unbalanced-brace`）
  - `check_environments(path: Path) -> list[Problem]`（code `unmatched-environment`）
  - `scan_structure(path: Path) -> list[Problem]`

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_latex_structure.py`：

```python
import tempfile
import unittest
from pathlib import Path

from ccfa.latex_structure import check_braces, check_environments, scan_structure


def _write(root: Path, body: str) -> Path:
    path = root / "main.tex"
    path.write_text(body, encoding="utf-8")
    return path


class TestBraces(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_balanced_braces_are_clean(self):
        self.assertEqual(check_braces(_write(self.root, r"\section{A} \textbf{b}")), [])

    def test_unclosed_brace_is_reported(self):
        problems = check_braces(_write(self.root, r"\section{A"))
        self.assertEqual([p.code for p in problems], ["unbalanced-brace"])

    def test_extra_closing_brace_is_reported_with_line(self):
        problems = check_braces(_write(self.root, "ok\n}\n"))
        self.assertEqual(problems[0].line, 2)

    def test_escaped_braces_do_not_count(self):
        self.assertEqual(check_braces(_write(self.root, r"a \{ b \}")), [])

    def test_brace_inside_a_comment_is_ignored(self):
        self.assertEqual(check_braces(_write(self.root, "% { unmatched")), [])

    def test_literal_backslash_then_comment_is_ignored(self):
        self.assertEqual(check_braces(_write(self.root, "line\\\\% { unmatched")), [])


class TestEnvironments(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_balanced_environments_are_clean(self):
        body = "\\begin{figure}\n\\end{figure}\n"
        self.assertEqual(check_environments(_write(self.root, body)), [])

    def test_mismatched_environment_names_are_reported(self):
        body = "\\begin{figure}\n\\end{table}\n"
        problems = check_environments(_write(self.root, body))
        self.assertEqual([p.code for p in problems], ["unmatched-environment"])
        self.assertIn("line 1", problems[0].message)

    def test_unclosed_environment_reports_its_open_line(self):
        problems = check_environments(_write(self.root, "text\n\\begin{table}\n"))
        self.assertEqual(problems[0].line, 2)

    def test_end_without_begin_is_reported(self):
        problems = check_environments(_write(self.root, "\\end{itemize}\n"))
        self.assertEqual(problems[0].line, 1)

    def test_environment_inside_a_comment_is_ignored(self):
        self.assertEqual(check_environments(_write(self.root, "% \\begin{figure}")), [])


class TestScanStructure(unittest.TestCase):
    def test_combines_both_checks(self):
        body = "\\begin{figure}\n{ unclosed\n"
        problems = scan_structure(_write(Path(tempfile.mkdtemp()), body))
        self.assertEqual(
            sorted(p.code for p in problems),
            ["unbalanced-brace", "unmatched-environment"],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ModuleNotFoundError: No module named 'ccfa.latex_structure'`。

- [ ] **Step 3: 实现**

创建 `tools/ccfa/latex_structure.py`：

```python
"""Structural checks for LaTeX sources.

Read-only. Comments are stripped before braces or environments are counted,
because a brace inside a comment is not document structure. The shared
strip_comment implements the even-backslash rule, so a line ending in a
literal backslash before '%' is still treated as a real comment.
"""

from __future__ import annotations

import re
from pathlib import Path

from ccfa.cli import Problem
from ccfa.texcomment import strip_comment

_ENV = re.compile(r"\\(begin|end)\{([^}]+)\}")


def _stripped_lines(path: Path) -> list[str]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [strip_comment(line) for line in text.splitlines()]


def check_braces(path: Path) -> list[Problem]:
    path = Path(path)
    problems: list[Problem] = []
    depth = 0
    for number, line in enumerate(_stripped_lines(path), start=1):
        index = 0
        while index < len(line):
            char = line[index]
            if char == "\\" and index + 1 < len(line) and line[index + 1] in "{}":
                index += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth < 0:
                    problems.append(
                        Problem("unbalanced-brace", str(path), number, "多余的 '}'")
                    )
                    depth = 0
            index += 1
    if depth > 0:
        problems.append(
            Problem("unbalanced-brace", str(path), None, f"有 {depth} 个 '{{' 未闭合")
        )
    return problems


def check_environments(path: Path) -> list[Problem]:
    path = Path(path)
    problems: list[Problem] = []
    stack: list[tuple[str, int]] = []
    for number, line in enumerate(_stripped_lines(path), start=1):
        for match in _ENV.finditer(line):
            kind, name = match.group(1), match.group(2)
            if kind == "begin":
                stack.append((name, number))
                continue
            if not stack:
                problems.append(
                    Problem(
                        "unmatched-environment",
                        str(path),
                        number,
                        f"\\end{{{name}}} 没有对应的 \\begin",
                    )
                )
                continue
            open_name, open_line = stack.pop()
            if open_name != name:
                problems.append(
                    Problem(
                        "unmatched-environment",
                        str(path),
                        number,
                        f"\\end{{{name}}} 与第 {open_line} 行的 \\begin{{{open_name}}} 不匹配",
                    )
                )
    for name, open_line in stack:
        problems.append(
            Problem(
                "unmatched-environment",
                str(path),
                open_line,
                f"\\begin{{{name}}} 从未闭合",
            )
        )
    return problems


def scan_structure(path: Path) -> list[Problem]:
    path = Path(path)
    return check_braces(path) + check_environments(path)
```

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 210 tests`，`OK`（198 + 12）。

判别力检查：把 `_stripped_lines` 改成直接返回 `text.splitlines()`（不剥离注释），`test_brace_inside_a_comment_is_ignored`、`test_literal_backslash_then_comment_is_ignored`、`test_environment_inside_a_comment_is_ignored` 必须失败；恢复。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/latex_structure.py tools/tests/test_latex_structure.py
git commit -m "feat: scan LaTeX braces and environments ignoring comments"
```

---

### Task 2: 引用键与图片文件检查

**Files:**
- Modify: `tools/ccfa/latex_structure.py`
- Modify: `tools/tests/test_latex_structure.py`

**Interfaces:**
- Consumes: `ccfa.texscan.find_cited_keys`（已含注释感知）、`ccfa.bib.load_entries`、`ccfa.texcomment.strip_comment`
- Produces:
  - `check_citations(paths: Iterable[Path], bib_path: Path) -> list[Problem]`（code `missing-cite-key`）
  - `check_figures(paths: Iterable[Path], figures_root: Path) -> list[Problem]`（code `missing-figure`）

- [ ] **Step 1: 写失败测试**

在 `tools/tests/test_latex_structure.py` 顶部改 import 为
`from ccfa.latex_structure import check_braces, check_citations, check_environments, check_figures, scan_structure`，
并追加：

```python
class TestCitations(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.bib = self.root / "references.bib"
        self.bib.write_text("@misc{known, title={T}}\n", encoding="utf-8")

    def test_known_key_is_clean(self):
        tex = _write(self.root, r"\cite{known}")
        self.assertEqual(check_citations([tex], self.bib), [])

    def test_unknown_key_is_reported_with_location(self):
        tex = _write(self.root, "text\n" + r"\citep{ghost}")
        problems = check_citations([tex], self.bib)
        self.assertEqual([p.code for p in problems], ["missing-cite-key"])
        self.assertEqual(problems[0].line, 2)
        self.assertIn("ghost", problems[0].message)

    def test_commented_citation_is_ignored(self):
        tex = _write(self.root, "% " + r"\cite{ghost}")
        self.assertEqual(check_citations([tex], self.bib), [])


class TestFigures(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.figures = self.root / "figures"
        self.figures.mkdir()

    def test_existing_figure_is_clean(self):
        (self.figures / "plot.pdf").write_bytes(b"%PDF-1.4\n")
        tex = _write(self.root, r"\includegraphics{plot.pdf}")
        self.assertEqual(check_figures([tex], self.figures), [])

    def test_extensionless_reference_resolves(self):
        (self.figures / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        tex = _write(self.root, r"\includegraphics[width=0.5\textwidth]{plot}")
        self.assertEqual(check_figures([tex], self.figures), [])

    def test_missing_figure_is_reported_with_line(self):
        tex = _write(self.root, "text\n" + r"\includegraphics{gone.png}")
        problems = check_figures([tex], self.figures)
        self.assertEqual([p.code for p in problems], ["missing-figure"])
        self.assertEqual(problems[0].line, 2)

    def test_commented_include_is_ignored(self):
        tex = _write(self.root, "% " + r"\includegraphics{gone.png}")
        self.assertEqual(check_figures([tex], self.figures), [])


if __name__ == "__main__":
    unittest.main()
```

（文件末尾原本已有一个 `if __name__` 块时不要重复添加。）

- [ ] **Step 2: 运行测试确认失败**

Expected: `ImportError: cannot import name 'check_citations'`。

- [ ] **Step 3: 实现**

在 `tools/ccfa/latex_structure.py` 的 import 区补
`from typing import Iterable`、`from ccfa.bib import load_entries`、`from ccfa.texscan import find_cited_keys`，
并在文件末尾追加：

```python
_INCLUDE = re.compile(r"\\includegraphics(?:\[[^\]]*\]\s*)?\{([^}]+)\}")
_FIGURE_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".eps")


def check_citations(paths: Iterable[Path], bib_path: Path) -> list[Problem]:
    cited = find_cited_keys(paths)
    entries = load_entries(Path(bib_path))
    problems: list[Problem] = []
    for key, locations in sorted(cited.items()):
        if key in entries:
            continue
        for location in locations:
            problems.append(
                Problem(
                    "missing-cite-key",
                    location.path,
                    location.line,
                    f"引用键不在文献表中: {key}",
                )
            )
    return problems


def check_figures(paths: Iterable[Path], figures_root: Path) -> list[Problem]:
    root = Path(figures_root)
    problems: list[Problem] = []
    for path in paths:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, raw_line in enumerate(text.splitlines(), start=1):
            line = strip_comment(raw_line)
            for match in _INCLUDE.finditer(line):
                name = match.group(1).strip()
                candidates = [root / name]
                if not Path(name).suffix:
                    candidates += [root / (name + suffix) for suffix in _FIGURE_SUFFIXES]
                if not any(candidate.exists() for candidate in candidates):
                    problems.append(
                        Problem(
                            "missing-figure",
                            str(path),
                            number,
                            f"图片文件不存在: {name}",
                        )
                    )
    return problems
```

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 217 tests`，`OK`（210 + 7）。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/latex_structure.py tools/tests/test_latex_structure.py
git commit -m "feat: check citation keys and figure files in LaTeX sources"
```

---

### Task 3: 行内百分号 advisory

**Files:**
- Modify: `tools/ccfa/latex_structure.py`
- Modify: `tools/tests/test_latex_structure.py`

**Interfaces:**
- Produces: `find_stray_percent(path: Path) -> list[Problem]`（code `stray-percent`，advisory）

判定用 `strip_comment` 的结果反推注释起点，而不是自己写 `(?<!\\)%` —— 后者正是参考实现里有缺陷的那条规则。advisory 的定义：注释前有正文内容，且注释符后还有非空白字符（意味着这行被截断了）。

- [ ] **Step 1: 写失败测试**

在 `tools/tests/test_latex_structure.py` 的 import 中加入 `find_stray_percent`，并追加：

```python
class TestStrayPercent(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_inline_percent_with_trailing_text_is_reported(self):
        problems = find_stray_percent(_write(self.root, "50% faster than baseline\n"))
        self.assertEqual([p.code for p in problems], ["stray-percent"])
        self.assertEqual(problems[0].line, 1)

    def test_trailing_percent_with_nothing_after_is_not_reported(self):
        self.assertEqual(find_stray_percent(_write(self.root, "text %\n")), [])

    def test_whole_line_comment_is_not_reported(self):
        self.assertEqual(find_stray_percent(_write(self.root, "% a note\n")), [])

    def test_escaped_percent_is_not_reported(self):
        self.assertEqual(find_stray_percent(_write(self.root, r"50\% faster")), [])

    def test_literal_backslash_then_comment_with_text_is_reported(self):
        self.assertEqual(
            [p.code for p in find_stray_percent(_write(self.root, "line\\\\% lost text\n"))],
            ["stray-percent"],
        )


if __name__ == "__main__":
    unittest.main()
```

（同样避免重复末尾的 `if __name__` 块。）

- [ ] **Step 2: 运行测试确认失败**

Expected: `ImportError: cannot import name 'find_stray_percent'`。

- [ ] **Step 3: 实现**

在 `latex_structure.py` 末尾追加：

```python
def find_stray_percent(path: Path) -> list[Problem]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[Problem] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = strip_comment(line)
        if stripped == line:
            continue
        if not stripped.strip():
            continue
        if line[len(stripped) + 1:].strip():
            found.append(
                Problem(
                    "stray-percent",
                    str(path),
                    number,
                    f"行内未转义 '%' 会截断该行: {line.strip()[:60]}",
                )
            )
    return found
```

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 222 tests`，`OK`（217 + 5）。

判别力检查：把判定换成朴素的 `"(?<!\\\\)%" in line`，`test_escaped_percent_is_not_reported` 与 `test_literal_backslash_then_comment_with_text_is_reported` 中至少一条必须失败；恢复。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/latex_structure.py tools/tests/test_latex_structure.py
git commit -m "feat: flag inline percent truncation as an advisory"
```

---

### Task 4: 四步编译驱动

**Files:**
- Create: `tools/ccfa/latex_compile.py`
- Create: `tools/tests/test_latex_compile.py`

**Interfaces:**
- Produces:
  - `Runner = Callable[[list[str], Path], "tuple[int, str]"]`
  - `find_engine(preferred: str | None = None) -> str | None`
  - `CompileStep = NamedTuple("CompileStep", [("name", str), ("status", str), ("returncode", int)])`
  - `CompileReport = NamedTuple("CompileReport", [("engine", str), ("steps", list[CompileStep])])`
  - `compile_document(tex: Path, engine: str, runner: Runner | None = None) -> CompileReport`
- 顺序固定：`pdflatex → bibtex → pdflatex → pdflatex`；`.aux` 无 `\bibdata` 时 bibtex 记 `skipped`；任一步非零即停止并记 `failed`。runner 可注入，测试全程不碰真实 LaTeX。

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_latex_compile.py`：

```python
import tempfile
import unittest
from pathlib import Path

from ccfa.latex_compile import compile_document, find_engine


class TestFindEngine(unittest.TestCase):
    def test_unknown_preferred_engine_returns_none(self):
        self.assertIsNone(find_engine("definitely-not-a-real-engine"))


class TestCompileDocument(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.tex = self.root / "main.tex"
        self.tex.write_text("\\documentclass{article}", encoding="utf-8")

    def _runner(self, behaviour, with_bibdata=True):
        calls: list[list[str]] = []

        def run(argv, cwd):
            calls.append(list(argv))
            if argv[0] == "pdflatex" and with_bibdata:
                (Path(cwd) / "main.aux").write_text("\\bibdata{refs}\n", encoding="utf-8")
            return behaviour(argv[0], len(calls))

        return run, calls

    @staticmethod
    def _ok(name, count):
        return 0, ""

    def test_runs_the_full_sequence_when_bibdata_is_present(self):
        run, calls = self._runner(self._ok)
        report = compile_document(self.tex, "pdflatex", runner=run)
        self.assertEqual([step.name for step in report.steps], ["pdflatex", "bibtex", "pdflatex", "pdflatex"])
        self.assertEqual([step.status for step in report.steps], ["ran", "ran", "ran", "ran"])
        self.assertEqual([call[0] for call in calls], ["pdflatex", "bibtex", "pdflatex", "pdflatex"])

    def test_skips_bibtex_when_aux_has_no_bibdata(self):
        run, calls = self._runner(self._ok, with_bibdata=False)
        report = compile_document(self.tex, "pdflatex", runner=run)
        self.assertEqual([step.status for step in report.steps], ["ran", "skipped", "ran", "ran"])
        self.assertNotIn("bibtex", [call[0] for call in calls])

    def test_stops_after_a_failed_first_pass(self):
        run, calls = self._runner(lambda name, count: (1, "boom"))
        report = compile_document(self.tex, "pdflatex", runner=run)
        self.assertEqual(len(report.steps), 1)
        self.assertEqual(report.steps[0].status, "failed")
        self.assertEqual(report.steps[0].returncode, 1)

    def test_stops_after_a_failed_bibtex(self):
        def behaviour(name, count):
            return (1, "bibtex failed") if name == "bibtex" else (0, "")

        run, _ = self._runner(behaviour)
        report = compile_document(self.tex, "pdflatex", runner=run)
        self.assertEqual([step.status for step in report.steps], ["ran", "failed"])

    def test_stops_after_a_failed_second_pass(self):
        states = {"pdflatex": 0}

        def behaviour(name, count):
            if name == "pdflatex":
                states["pdflatex"] += 1
                if states["pdflatex"] == 2:
                    return (1, "second pass failed")
            return (0, "")

        run, _ = self._runner(behaviour)
        report = compile_document(self.tex, "pdflatex", runner=run)
        self.assertEqual([step.status for step in report.steps], ["ran", "ran", "failed"])

    def test_report_names_the_engine(self):
        run, _ = self._runner(self._ok)
        self.assertEqual(compile_document(self.tex, "xelatex", runner=run).engine, "xelatex")

    def test_runner_receives_the_document_directory_as_cwd(self):
        seen = []

        def run(argv, cwd):
            seen.append(Path(cwd))
            (Path(cwd) / "main.aux").write_text("\\bibdata{refs}\n", encoding="utf-8")
            return 0, ""

        compile_document(self.tex, "pdflatex", runner=run)
        self.assertEqual(set(seen), {self.root})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ModuleNotFoundError: No module named 'ccfa.latex_compile'`。

- [ ] **Step 3: 实现**

创建 `tools/ccfa/latex_compile.py`：

```python
"""Drive the explicit pdflatex -> bibtex -> pdflatex -> pdflatex sequence.

latexmk is unavailable on this host (it needs Perl), and an explicit sequence
also makes it obvious which step failed. The runner is injectable so tests
never need a real LaTeX installation.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable, NamedTuple

Runner = Callable[[list[str], Path], "tuple[int, str]"]

_ENGINES = ("pdflatex", "xelatex")


class CompileStep(NamedTuple):
    name: str
    status: str
    returncode: int


class CompileReport(NamedTuple):
    engine: str
    steps: list[CompileStep]


def find_engine(preferred: str | None = None) -> str | None:
    for name in (preferred,) if preferred else _ENGINES:
        if name and shutil.which(name):
            return name
    return None


def _default_runner(argv: list[str], cwd: Path) -> tuple[int, str]:
    result = subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, errors="replace"
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _has_bibdata(aux: Path) -> bool:
    try:
        return "\\bibdata" in aux.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def compile_document(tex: Path, engine: str, runner: Runner | None = None) -> CompileReport:
    tex = Path(tex)
    run = runner or _default_runner
    cwd = tex.parent
    steps: list[CompileStep] = []

    code, _ = run([engine, "-interaction=nonstopmode", tex.name], cwd)
    steps.append(CompileStep(engine, "ran" if code == 0 else "failed", code))
    if code != 0:
        return CompileReport(engine, steps)

    aux = cwd / f"{tex.stem}.aux"
    if _has_bibdata(aux):
        code, _ = run(["bibtex", tex.stem], cwd)
        steps.append(CompileStep("bibtex", "ran" if code == 0 else "failed", code))
        if code != 0:
            return CompileReport(engine, steps)
    else:
        steps.append(CompileStep("bibtex", "skipped", 0))

    for _ in range(2):
        code, _ = run([engine, "-interaction=nonstopmode", tex.name], cwd)
        steps.append(CompileStep(engine, "ran" if code == 0 else "failed", code))
        if code != 0:
            return CompileReport(engine, steps)

    return CompileReport(engine, steps)
```

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 230 tests`，`OK`（222 + 8）。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/latex_compile.py tools/tests/test_latex_compile.py
git commit -m "feat: drive the explicit four-step LaTeX build"
```

---

### Task 5: CLI 与退出码

**Files:**
- Modify: `tools/ccfa/cli.py`（新增共享异常）
- Modify: `tools/ccfa/datasource.py`（改为复用共享异常）
- Create: `tools/ccfa/latex_check.py`
- Create: `tools/tests/test_latex_check.py`

**Interfaces:**
- Consumes: `ccfa.latex_structure.scan_structure / check_citations / check_figures / find_stray_percent`、`ccfa.latex_compile.find_engine / compile_document`、`ccfa.texscan.iter_tex_files`
- Produces:
  - `check(manuscript, bib=None, figures_root=None, compile=False, engine=None) -> tuple[list[Problem], list[Problem]]`
  - `main(argv) -> int`，参数 `--manuscript`（必需）、`--bib`、`--figures-root`、`--compile`、`--engine`
  - problem codes：结构/引用/图片四类 + `compile-failed`
- `ToolEnvironmentError` 目前定义在 `datasource.py`。它是通用契约（"工具自身环境坏了"），本轮上移到 `cli.py`，`datasource.py` 改为导入并继续对外暴露同名符号——`trace_claims.py` 的 `from ccfa.datasource import ToolEnvironmentError` 因此不受影响。

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_latex_check.py`：

```python
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import ccfa.latex_check as latex_check
from ccfa.latex_check import check, main
from ccfa.latex_compile import CompileReport, CompileStep


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.manuscript = self.root / "manuscript"
        self.manuscript.mkdir()
        self.tex = self.manuscript / "main.tex"
        self.tex.write_text("\\section{Intro}\n", encoding="utf-8")

    def write(self, body: str):
        self.tex.write_text(body, encoding="utf-8")

    def run_main(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                ["latex_check.py", "--manuscript", str(self.manuscript), *extra]
            )
        return code, out.getvalue(), err.getvalue()


class TestCheck(BaseCase):
    def test_clean_manuscript_has_no_problems(self):
        problems, advisories = check(self.manuscript)
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_unclosed_brace_is_a_problem(self):
        self.write("\\section{Intro\n")
        problems, _ = check(self.manuscript)
        self.assertIn("unbalanced-brace", [p.code for p in problems])

    def test_missing_figure_is_a_problem(self):
        self.write("\\includegraphics{gone.png}\n")
        problems, _ = check(self.manuscript)
        self.assertIn("missing-figure", [p.code for p in problems])

    def test_missing_cite_key_is_a_problem(self):
        bib = self.root / "references.bib"
        bib.write_text("@misc{known, title={T}}\n", encoding="utf-8")
        self.write("\\cite{ghost}\n")
        problems, _ = check(self.manuscript, bib=bib)
        self.assertIn("missing-cite-key", [p.code for p in problems])

    def test_stray_percent_is_only_an_advisory(self):
        self.write("50% faster\n")
        problems, advisories = check(self.manuscript)
        self.assertNotIn("stray-percent", [p.code for p in problems])
        self.assertIn("stray-percent", [p.code for p in advisories])

    def test_failed_compile_step_becomes_a_problem(self):
        report = CompileReport("pdflatex", [CompileStep("pdflatex", "failed", 1)])
        original_compile = latex_check.compile_document
        original_engine = latex_check.find_engine
        latex_check.compile_document = lambda tex, engine: report
        latex_check.find_engine = lambda preferred=None: "pdflatex"
        try:
            problems, _ = check(self.manuscript, compile=True)
        finally:
            latex_check.compile_document = original_compile
            latex_check.find_engine = original_engine
        self.assertIn("compile-failed", [p.code for p in problems])


class TestMain(BaseCase):
    def test_missing_manuscript_exits_two(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                ["latex_check.py", "--manuscript", str(self.root / "nope")]
            )
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")

    def test_compile_without_engine_exits_two(self):
        original = latex_check.find_engine
        latex_check.find_engine = lambda preferred=None: None
        try:
            code, _, _ = self.run_main("--compile")
        finally:
            latex_check.find_engine = original
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ModuleNotFoundError: No module named 'ccfa.latex_check'`。

- [ ] **Step 3: 实现**

先在 `tools/ccfa/cli.py` 末尾追加：

```python
class ToolEnvironmentError(Exception):
    """A missing or broken dependency in the tool's own environment."""
```

把 `tools/ccfa/datasource.py` 里的 `class ToolEnvironmentError(Exception): ...` 定义删掉，改为在 import 区加
`from ccfa.cli import ToolEnvironmentError`（保留该名字在 `datasource` 命名空间，`trace_claims` 无需改动）。

再创建 `tools/ccfa/latex_check.py`：

```python
"""Structural checks and optional compilation for a LaTeX manuscript.

Read-only unless --compile is given; compilation writes only inside the
manuscript directory, which is normal LaTeX behaviour.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ccfa.cli import Problem, ToolEnvironmentError, emit, tool_error
from ccfa.latex_compile import compile_document, find_engine
from ccfa.latex_structure import (
    check_citations,
    check_figures,
    find_stray_percent,
    scan_structure,
)
from ccfa.texscan import iter_tex_files


def check(
    manuscript: Path,
    bib: Path | None = None,
    figures_root: Path | None = None,
    compile: bool = False,
    engine: str | None = None,
) -> tuple[list[Problem], list[Problem]]:
    manuscript = Path(manuscript)
    if not manuscript.is_dir():
        raise ValueError(f"手稿目录不存在或不是目录: {manuscript}")
    paths = iter_tex_files(manuscript)
    problems: list[Problem] = []
    for path in paths:
        problems.extend(scan_structure(path))
    if bib is not None:
        problems.extend(check_citations(paths, Path(bib)))
    root = Path(figures_root) if figures_root else manuscript
    problems.extend(check_figures(paths, root))
    advisories: list[Problem] = []
    for path in paths:
        advisories.extend(find_stray_percent(path))
    if compile:
        chosen = find_engine(engine)
        if chosen is None:
            raise ToolEnvironmentError("找不到 LaTeX 引擎（尝试过 pdflatex / xelatex）")
        main_tex = manuscript / "main.tex"
        if not main_tex.is_file():
            raise ValueError(f"找不到主文件: {main_tex}")
        for step in compile_document(main_tex, chosen).steps:
            if step.status == "failed":
                problems.append(
                    Problem(
                        "compile-failed",
                        str(main_tex),
                        None,
                        f"{step.name} 退出码 {step.returncode}",
                    )
                )
    return problems, advisories


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="检查 LaTeX 手稿结构与编译")
    parser.add_argument("--manuscript", required=True)
    parser.add_argument("--bib")
    parser.add_argument("--figures-root")
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("--engine")
    args = parser.parse_args(argv[1:])
    try:
        problems, advisories = check(
            Path(args.manuscript),
            Path(args.bib) if args.bib else None,
            Path(args.figures_root) if args.figures_root else None,
            compile=args.compile,
            engine=args.engine,
        )
    except (ValueError, ToolEnvironmentError) as exc:
        return tool_error(str(exc))
    return emit(problems, advisories)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 238 tests`，`OK`（加入本任务的 8 条之前应为 230；198 + 12 + 7 + 5 + 8 = 230）。同时必须确认 `trace_claims` 的 `ToolEnvironmentError` 导入路径未因异常上移而失效——它在 `datasource` 命名空间里仍然可见。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/cli.py tools/ccfa/datasource.py tools/ccfa/latex_check.py tools/tests/test_latex_check.py
git commit -m "feat: check LaTeX structure and compile through one CLI"
```

---

### Task 6: 端到端回归

**Files:**
- Create: `tools/tests/test_latex_check_e2e.py`

**Interfaces:**
- Consumes: Task 5 的 CLI，通过子进程调用
- Produces: 结构问题、工具错误、advisory 三类路径的真实退出码回归

- [ ] **Step 1: 写测试**

创建 `tools/tests/test_latex_check_e2e.py`：

```python
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
CLI = TOOLS_ROOT / "ccfa" / "latex_check.py"


class TestLatexCheckEndToEnd(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.manuscript = self.root / "manuscript"
        self.manuscript.mkdir()
        self.tex = self.manuscript / "main.tex"
        self.tex.write_text("\\section{Intro}\n", encoding="utf-8")

    def _run(self, *extra):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(TOOLS_ROOT)
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--manuscript",
                str(self.manuscript),
                *extra,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def test_clean_run_exits_zero_with_parseable_json(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problem_count"], 0)

    def test_structure_error_exits_one_with_location(self):
        self.tex.write_text("text\n\\section{Broken\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problems"][0]["code"], "unbalanced-brace")
        self.assertIn("main.tex", result.stderr)

    def test_missing_manuscript_exits_two_with_empty_stdout(self):
        result = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--manuscript",
                str(self.root / "nope"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONPATH": str(TOOLS_ROOT)},
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_unknown_engine_with_compile_exits_two(self):
        result = self._run("--compile", "--engine", "definitely-not-a-real-engine")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_stray_percent_exits_zero_with_advisory_json(self):
        self.tex.write_text("50% faster than baseline\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problem_count"], 0)
        self.assertEqual(payload["advisories"][0]["code"], "stray-percent")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认通过**

Expected: `Ran 243 tests`，`OK`（238 + 5）。

- [ ] **Step 3: 真实编译手工验收（唯一需要 MiKTeX 的一步）**

在临时目录写一份最小中文文档（含 `\cite` 与 `\bibliography`），运行：

```powershell
& "$root/tools/.venv/Scripts/python.exe" "$root/tools/ccfa/latex_check.py" --manuscript <tmp> --compile
```

期望：退出码 0，且步骤序列包含 `pdflatex → bibtex → pdflatex → pdflatex`。若本机引擎确实不可用，则退出码 2 且 stdout 为空——这也是契约内行为，但需在报告中如实写明"编译路径未成功验证"。**不得把未编译成功的文档报告为可编译。**

- [ ] **Step 4: 提交**

```powershell
git add tools/tests/test_latex_check_e2e.py
git commit -m "test: add latex-check end-to-end regression"
```

---

## 验收

```powershell
$root = "<repo-root>"
cd $root
& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v
```

期望：基线 **198** + 本计划新增 **45**（12 + 7 + 5 + 8 + 8 + 5），共 **243** 个测试通过。

按 spec v5 第 12 节逐条核对：

- 五类输入分别报出 `unbalanced-brace`、`unmatched-environment`、`missing-cite-key`、`missing-figure`，以及 advisory `stray-percent`。
- 注释里的花括号/环境不造成误报（含 `line\\% {` 这一偶数反斜杠用例）。
- 不开 `--compile` 不写任何文件；`--compile` 缺引擎 → 2，编译失败 → 1。

已知边界（留给最终全分支评审）：`verbatim`/`lstlisting` 体内的花括号与环境仍参与扫描；`\input` 的多文件是逐文件配平而非整体配平；`\includegraphics` 的路径只按 `--figures-root` 解析，不跟踪 `\graphicspath`。

## 后续计划（不在本计划范围）

按 spec v5 第 6.1 节，其余工具各成计划：`final-check`（渲染后 PDF 基线 + 图表 manifest，参考 `paper-machine/scripts/verify_paper.py`）、`provenance` + `run-log` + `research-version`、`repro-package` + `friction-log`、知识层（FTS5 索引与记忆）、自动化与跨模型评审。
