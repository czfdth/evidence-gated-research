# final-check 实施计划（Part B：组合、CLI 与 e2e）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Part A 的三个模块组合成 `final-check` 工具：以渲染后的 PDF 为基线检查未解析标记与声明缺失，扫 `figures/` 查字节格式，核验 `figures/manifest.yaml`，复用 `trace-claims` 的未标记数字扫描，并把一切走 `ccfa.cli` 的 JSON / stderr / 退出码契约输出。

**Architecture:** 一个 `final_check.check()` 把五个来源的结论汇总成 `(problems, advisories)`，一个 `main()` 负责参数与退出码。所有"读不出"的情形一律走 advisory（`check-skipped`），所有"传参坏了"一律抛 `ValueError` 由 `main` 映射为退出码 2。检查全程只读。

**Tech Stack:** Python 3.12（`tools/.venv`）；PyYAML 6.0.3；PyMuPDF 1.28.2；unittest。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v6：§6.2 / §6.3 / §6.6、§12）

**Part A（已完成，HEAD `d46d78a`，287 tests）**：`figurebytes`、`pdftext`、`figure_manifest` 三个模块，最终全分支评审 Ready。

## 评审者留下、本计划必须定死的六条决策

1. **`None` 先判后用**：`extract_text` 返回 `None` 时**不得**调用 `find_unresolved_markers`（它只接受 `str`），改为发 `check-skipped` advisory。
2. **`load_manifest` 的 `ValueError` 一律映射退出码 2**（工具错误），不是 problem。
3. **适配层**：`find_untagged` 返回 `Untagged` NamedTuple（字段 `path/line/text`），不是 `Problem`，必须显式转换成 advisory。
4. **重复报告显式接受**：一张 JPEG 字节却命名为 `.png`、且 manifest 也声明 `png` 的图，会同时得到 `figure-format`（文件对自己名字不诚实）与 `figure-manifest-format`（manifest 描述错）。两个码回答不同问题，**同时报**，并用一条 e2e 用例钉住。
5. **图集选择**：`check_figure_formats` 扫 `<paper-root>/figures/` 下的全部文件（`rglob("*")`）。矢量 `.pdf` 由 `figurebytes` 的后缀门天然排除在图片格式检查外，改由 manifest 的 `bytes_format` 比对覆盖——两条路径各有其职，不重叠。
6. **别名抽共享常量**：`figurebytes` 增加 `JPEG_SUFFIXES = (".jpg", ".jpeg")`，`figure_manifest` 改为引用它，消除两处内联的漂移风险。

## Global Constraints

- 仓库根：`<repo-root>`
- 退出码：`0` 通过，`1` 有 problem，`2` 工具错误。
- 机器可读 JSON 走 stdout，人读摘要走 stderr。**只读**：不写任何被检查文件。
- UTF-8 无 BOM；默认 ASCII 注释，中文只出现在面向用户的 `Problem.message` 里。
- 不得写入或提交含用户名的绝对路径。
- 基线：**287 tests OK**，HEAD = `d46d78a`，工作树干净。
- 测试命令：`& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
- 新代码一律 `import pymupdf`；禁止 `fitz`。
- **skipped 不是通过**：任何被跳过的检查必须出现在 advisory 列表里（`check-skipped`），而"通过"不出现在报告中。

---

### Task 1: `check()` 组合五个来源

**Files:**
- Modify: `tools/ccfa/figurebytes.py`（加 `JPEG_SUFFIXES` 常量）
- Modify: `tools/ccfa/figure_manifest.py`（改用该常量）
- Create: `tools/ccfa/final_check.py`
- Create: `tools/tests/test_final_check.py`

**Interfaces:**
- Consumes: `figurebytes.JPEG_SUFFIXES` / `check_figure_formats`、`pdftext.Reader` / `extract_text` / `find_unresolved_markers`、`figure_manifest.load_manifest` / `check_manifest`、`dataval.find_untagged`、`texscan.iter_tex_files`、`cli.Problem`
- Produces:
  - `check(manuscript: Path, pdf: Path | None = None, manifest: Path | None = None, paper_root: Path | None = None, reader: Reader | None = None) -> tuple[list[Problem], list[Problem]]`
  - `_find_pdf(manuscript: Path) -> Path | None`（取手稿目录下最大的 `.pdf`）
  - `_check_declarations(text: str, path: str) -> list[Problem]`

**行为规格（逐条可测）**

| 输入 | 结果 |
| --- | --- |
| `manuscript` 不是目录 | `ValueError`（→ 2） |
| 找不到 PDF | `ValueError`（→ 2） |
| `reader` 返回 `None` | advisory `check-skipped`，**不调用**标记扫描 |
| PDF 文本含未解析标记 | problem `unresolved-marker` |
| PDF 文本无"局限/数据可用性"关键词 | advisory `missing-declaration` |
| `<paper-root>/figures/` 不存在 | advisory `check-skipped`（图格式检查跳过） |
| `figures/` 下有字节与扩展名不符的图片 | problem `figure-format` |
| `manifest` 给出且不可解析 | `ValueError`（→ 2） |
| manifest 条目与真实字节/脚本不符 | problem `figure-missing` / `figure-hash` / `figure-manifest-format` |
| 手稿 `.tex` 里有未标记数字 | advisory `untagged-number` |

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_final_check.py`：

```python
import hashlib
import tempfile
import unittest
from pathlib import Path

from ccfa.final_check import check

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 8
CLEAN_TEXT = "Limitations and Data Availability are stated here."
MANIFEST = (
    "- name: plot\n"
    "  file: figures/plot.png\n"
    "  bytes_format: png\n"
    "  generator: src/plot.py\n"
    "  generator_hash: \"{hash}\"\n"
    "  referenced_in: [\"manuscript/main.tex:1\"]\n"
)


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.manuscript = self.root / "manuscript"
        self.manuscript.mkdir()
        (self.manuscript / "main.tex").write_text("\\section{Intro}\n", encoding="utf-8")
        self.pdf = self.manuscript / "main.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\n")
        self.figures = self.root / "figures"
        self.figures.mkdir()
        self.reader = lambda path: CLEAN_TEXT

    def run_check(self, **kwargs):
        kwargs.setdefault("reader", self.reader)
        return check(self.manuscript, pdf=self.pdf, **kwargs)

    def write_generator(self, body="print('x')\n"):
        path = self.root / "src" / "plot.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def write_manifest(self, body):
        path = self.root / "manifest.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    @staticmethod
    def codes(items):
        return sorted(item.code for item in items)


class TestCheck(BaseCase):
    def test_clean_paper_has_no_problems(self):
        problems, advisories = self.run_check()
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_marker_in_pdf_text_is_a_problem(self):
        self.reader = lambda path: CLEAN_TEXT + " Figure ?? here"
        problems, _ = self.run_check()
        self.assertIn("unresolved-marker", self.codes(problems))

    def test_unreadable_pdf_is_skipped_not_passed(self):
        self.reader = lambda path: None
        problems, advisories = self.run_check()
        self.assertEqual(problems, [])
        self.assertIn("check-skipped", self.codes(advisories))

    def test_jpeg_bytes_named_png_is_a_problem(self):
        (self.figures / "a.png").write_bytes(JPEG)
        problems, _ = self.run_check()
        self.assertIn("figure-format", self.codes(problems))

    def test_manifest_hash_mismatch_is_a_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        self.write_generator()
        manifest = self.write_manifest(MANIFEST.format(hash="sha256:deadbeef"))
        problems, _ = self.run_check(manifest=manifest)
        self.assertIn("figure-hash", self.codes(problems))

    def test_malformed_manifest_raises_value_error(self):
        manifest = self.write_manifest("name: not-a-list\n")
        with self.assertRaises(ValueError):
            self.run_check(manifest=manifest)

    def test_untagged_number_is_an_advisory(self):
        (self.manuscript / "main.tex").write_text(
            "Accuracy was 92.5 percent.\n", encoding="utf-8"
        )
        _, advisories = self.run_check()
        self.assertIn("untagged-number", self.codes(advisories))

    def test_missing_declaration_is_an_advisory(self):
        self.reader = lambda path: "nothing relevant here"
        problems, advisories = self.run_check()
        self.assertEqual(problems, [])
        self.assertIn("missing-declaration", self.codes(advisories))

    def test_missing_pdf_raises_value_error(self):
        with self.assertRaises(ValueError):
            check(self.manuscript, pdf=self.root / "gone.pdf", reader=self.reader)

    def test_one_bad_figure_can_report_both_codes(self):
        # Decision 4: the two codes answer different questions, so both fire.
        (self.figures / "plot.png").write_bytes(JPEG)
        manifest = self.write_manifest(
            MANIFEST.format(hash=self.write_generator())
        )
        problems, _ = self.run_check(manifest=manifest)
        codes = self.codes(problems)
        self.assertIn("figure-format", codes)
        self.assertIn("figure-manifest-format", codes)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ModuleNotFoundError: No module named 'ccfa.final_check'`。

- [ ] **Step 3: 实现**

先在 `tools/ccfa/figurebytes.py` 中**按这个顺序**改（常量必须先定义后使用，写反了会 `NameError`）：

```python
# 放在 _MAGIC 之后、_IMAGE_SUFFIXES 之前
JPEG_SUFFIXES = (".jpg", ".jpeg")
_IMAGE_SUFFIXES = (".png",) + JPEG_SUFFIXES + (".gif",)
```

判定行的 `(actual == ".jpg" and suffix == ".jpeg")` 改为 `(actual == ".jpg" and suffix in JPEG_SUFFIXES)`。

再把 `tools/ccfa/figure_manifest.py` 的
`and not (actual == ".jpg" and declared_raw in ("jpg", "jpeg"))`
改为引用共享常量（导入 `JPEG_SUFFIXES`，写成 `and not (actual == ".jpg" and "." + declared_raw in JPEG_SUFFIXES)`）。

创建 `tools/ccfa/final_check.py`：

```python
"""Final checks against the rendered paper: PDF baseline, figures, manifest.

Read-only. Every check that cannot run is reported as a `check-skipped`
advisory -- never silently treated as passing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ccfa.cli import Problem, ToolEnvironmentError, emit, tool_error
from ccfa.dataval import find_untagged
from ccfa.figure_manifest import check_manifest, load_manifest
from ccfa.figurebytes import check_figure_formats
from ccfa.pdftext import Reader, extract_text, find_unresolved_markers
from ccfa.texscan import iter_tex_files

_DECLARATION_KEYWORDS = ("limitation", "data availability", "局限性", "数据可用性")


def _find_pdf(manuscript: Path) -> Path | None:
    pdfs = sorted(
        Path(manuscript).rglob("*.pdf"),
        key=lambda path: path.stat().st_size,
        reverse=True,
    )
    return pdfs[0] if pdfs else None


def _check_declarations(text: str, path: str) -> list[Problem]:
    lowered = text.lower()
    if any(keyword in lowered for keyword in _DECLARATION_KEYWORDS):
        return []
    return [
        Problem(
            "missing-declaration",
            path,
            None,
            "渲染后的 PDF 中未找到局限或数据可用性声明",
        )
    ]


def check(
    manuscript: Path,
    pdf: Path | None = None,
    manifest: Path | None = None,
    paper_root: Path | None = None,
    reader: Reader | None = None,
) -> tuple[list[Problem], list[Problem]]:
    manuscript = Path(manuscript)
    if not manuscript.is_dir():
        raise ValueError(f"手稿目录不存在或不是目录: {manuscript}")
    root = Path(paper_root) if paper_root else manuscript.parent

    problems: list[Problem] = []
    advisories: list[Problem] = []

    target_pdf = Path(pdf) if pdf else _find_pdf(manuscript)
    if target_pdf is None or not target_pdf.is_file():
        raise ValueError(f"找不到渲染后的 PDF: {target_pdf}")
    text = extract_text(target_pdf, reader=reader)
    if text is None:
        advisories.append(
            Problem(
                "check-skipped",
                str(target_pdf),
                None,
                "PyMuPDF 不可用或 PDF 无法读取，未解析标记与声明检查已跳过",
            )
        )
    else:
        problems.extend(find_unresolved_markers(text, str(target_pdf)))
        advisories.extend(_check_declarations(text, str(target_pdf)))

    figures_dir = root / "figures"
    if figures_dir.is_dir():
        problems.extend(check_figure_formats(sorted(figures_dir.rglob("*"))))
    else:
        advisories.append(
            Problem(
                "check-skipped",
                str(figures_dir),
                None,
                "未找到 figures/ 目录，图片格式检查已跳过",
            )
        )

    if manifest is not None:
        items = load_manifest(Path(manifest))
        manifest_problems, manifest_advisories = check_manifest(items, root)
        problems.extend(manifest_problems)
        advisories.extend(manifest_advisories)

    for tex in iter_tex_files(manuscript):
        for item in find_untagged(tex):
            advisories.append(
                Problem(
                    "untagged-number",
                    item.path,
                    item.line,
                    f"未标记的数字线索（需人工复核）: {item.text}",
                )
            )

    return problems, advisories


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="终稿确定性检查")
    parser.add_argument("--manuscript", required=True)
    parser.add_argument("--pdf")
    parser.add_argument("--manifest")
    parser.add_argument("--paper-root")
    args = parser.parse_args(argv[1:])
    try:
        problems, advisories = check(
            Path(args.manuscript),
            Path(args.pdf) if args.pdf else None,
            Path(args.manifest) if args.manifest else None,
            Path(args.paper_root) if args.paper_root else None,
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

Expected: `Ran 297 tests`，`OK`（287 + 10）。

判别力检查：把 `extract_text` 返回 `None` 时的分支改成"什么都不做"，`test_unreadable_pdf_is_skipped_not_passed` 必须失败（advisory 消失）；恢复。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/figurebytes.py tools/ccfa/figure_manifest.py tools/ccfa/final_check.py tools/tests/test_final_check.py
git commit -m "feat: compose final checks over PDF, figures and manifest"
```

---

### Task 2: CLI 退出码与端到端回归

**Files:**
- Create: `tools/tests/test_final_check_e2e.py`

**Interfaces:**
- Consumes: Task 1 的 CLI，通过子进程调用；PyMuPDF 用于现场生成 PDF 夹具。

**行为规格**

| 场景 | 期望 |
| --- | --- |
| 干净稿（真 PDF、无标记、有声明） | `0`，stdout 是可解析 JSON |
| 真 PDF 里写入 `??` | `1`，problem code `unresolved-marker`，stderr 含 PDF 路径 |
| PDF 不存在 | `2`，stdout 为空 |
| 只有 advisory（正文有未标记数字） | `0`，JSON 的 `problem_count` 为 0 且 `advisories` 非空 |

- [ ] **Step 1: 写测试**

创建 `tools/tests/test_final_check_e2e.py`：

```python
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pymupdf

TOOLS_ROOT = Path(__file__).resolve().parents[1]
CLI = TOOLS_ROOT / "ccfa" / "final_check.py"


class TestFinalCheckEndToEnd(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.manuscript = self.root / "manuscript"
        self.manuscript.mkdir()
        (self.root / "figures").mkdir()
        self.tex = self.manuscript / "main.tex"
        self.tex.write_text("\\section{Intro}\n", encoding="utf-8")
        self.pdf = self.manuscript / "main.pdf"

    def make_pdf(self, *lines):
        # One short line per insert_text call: a single long string can run past
        # the page and be clipped, which would make the fixture flaky.
        document = pymupdf.open()
        page = document.new_page()
        for index, line in enumerate(lines):
            page.insert_text((72, 72 + 14 * index), line)
        document.save(str(self.pdf))
        document.close()

    def _run(self, *extra):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(TOOLS_ROOT)
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--manuscript",
                str(self.manuscript),
                "--pdf",
                str(self.pdf),
                *extra,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def test_clean_paper_exits_zero_with_parseable_json(self):
        self.make_pdf("Limitations.", "Data Availability.")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problem_count"], 0)

    def test_unresolved_marker_exits_one(self):
        self.make_pdf("Limitations.", "Data Availability.", "Figure ?? here")
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problems"][0]["code"], "unresolved-marker")
        self.assertIn("main.pdf", result.stderr)

    def test_missing_pdf_exits_two_with_empty_stdout(self):
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_advisory_only_run_exits_zero(self):
        self.make_pdf("Limitations.", "Data Availability.")
        self.tex.write_text("Accuracy was 92.5 percent.\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problem_count"], 0)
        self.assertTrue(payload["advisories"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认通过**

Expected: `Ran 301 tests`，`OK`（297 + 4）。

若 `test_missing_pdf_exits_two_with_empty_stdout` 失败，修 `final_check.main`，不要改这条测试的期望值。

- [ ] **Step 3: 提交**

```powershell
git add tools/tests/test_final_check_e2e.py
git commit -m "test: add final-check end-to-end regression"
```

---

## 验收

```powershell
$root = "<repo-root>"
cd $root
& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v
```

期望：基线 **287** + 本计划新增 **14**（10 + 4），共 **301** 个测试通过。

按 spec v6 与评审者交办清单逐条核对：

- `unresolved-marker` 在渲染后的 PDF 文本上检出；`extract_text` 返回 `None` 时走 `check-skipped`，**不是通过**（决策 1）。
- `load_manifest` 的 `ValueError` 映射退出码 2（决策 2）。
- `find_untagged` 的 `Untagged` 被适配成 advisory（决策 3）。
- 一张坏图同时报 `figure-format` 与 `figure-manifest-format`，且有用例钉住（决策 4）。
- 图片格式检查扫 `figures/` 目录；`.pdf` 由后缀门排除，改由 manifest 覆盖（决策 5）。
- `jpg`/`jpeg` 别名收敛为 `figurebytes.JPEG_SUFFIXES` 单一常量（决策 6）。
- skipped 在 JSON 里以 advisory 出现，与"通过"（不出现）可区分（§12）。

已知边界（留给最终全分支评审）：

- 声明检查是中英关键词匹配（`limitation` / `data availability` / `局限性` / `数据可用性`），不是语义判断；声明换个说法就会漏。
- `_find_pdf` 取手稿目录下**最大**的 PDF——多份 PDF 并存时可能选错，需要 `--pdf` 显式指定。
- `check_figure_formats` 扫 `figures/` 全部文件，包含未被 manifest 收录的图；这是有意的（漏网的坏图也要报），代价是同一问题可能从 manifest 那条路径再报一次（决策 4 已接受）。

## 后续计划（不在本计划范围）

`final-check` 完成后，四个确定性工具（citation-guard、trace-claims、latex-check、final-check）齐备。其后按 spec §6.1：`provenance` / `run-log` / `research-version`、`repro-package` / `friction-log`、知识层（FTS5 + 记忆）、自动化与跨模型评审，最后是模板库与派生流程把整条链串起来。
