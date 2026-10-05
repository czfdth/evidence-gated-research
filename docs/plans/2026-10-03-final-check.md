# final-check 实施计划（Part A：确定性核心）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成终稿检查的三个确定性核心模块：图片字节嗅探、渲染后 PDF 的文本与未解析标记提取、`figures/manifest.yaml` 的逐条核验。

**Architecture:** 三个互不依赖的纯函数模块，全部只读、全部走 `ccfa.cli.Problem`。`figurebytes` 用魔数判定真实格式（重命名骗不过它）；`pdftext` 把"取文本"做成可注入的 Reader，缺 PyMuPDF 时返回 `None` 交给上层记 skipped；`figure_manifest` 把 manifest 的每条声明（file / bytes_format / generator_hash / referenced_in）拿去和真实字节对账。

**为什么拆两个计划：** Part A 结束后三个模块可独立测试、可独立评审；`final_check` 核心（组合、skipped 表示、声明缺失）与 CLI/e2e 依赖它们，放 Part B，避免一个计划里塞进八件事。

**Tech Stack:** Python 3.12（`tools/.venv`）；stdlib `hashlib` / `re` / `pathlib`；PyYAML 6.0.3；PyMuPDF 1.28.2（已装入 venv）；unittest。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v6：§6.2 / §6.3 / §6.6、§12）

## Global Constraints

- 仓库根：`<repo-root>`
- 退出码：`0` 通过，`1` 发现问题，`2` 工具自身出错（本计划不涉及，Part B 使用）。
- 只读：三个模块都不得写入任何文件。
- 机器可读 JSON 走 stdout，人读摘要走 stderr（本计划只产出 `Problem`，由 Part B 的 CLI 输出）。
- UTF-8 无 BOM；默认 ASCII 注释，中文只出现在面向用户的 `Problem.message` 里。
- 不得写入或提交含用户名的绝对路径。
- 基线：**253 个测试通过**，HEAD = `2045549`，工作树干净。
- 测试命令：`& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
- **新代码一律 `import pymupdf`，禁止使用已弃用的 `fitz` 别名**（会打印弃用警告）。
- 依赖缺失时的语义：**skipped，绝不是通过**。

---

### Task 1: 图片字节嗅探与扩展名核对

**Files:**
- Create: `tools/ccfa/figurebytes.py`
- Create: `tools/tests/test_figurebytes.py`

**Interfaces:**
- Produces:
  - `sniff(path: Path) -> str | None`（返回规范后缀 `.png`/`.jpg`/`.gif`/`.pdf`；读不到或无法识别返回 `None`）
  - `check_figure_formats(paths: Iterable[Path]) -> list[Problem]`（code `figure-format`）
- 判定：只看图片后缀（`.png`/`.jpg`/`.jpeg`/`.gif`）；`.jpg` 与 `.jpeg` 互认；无法识别字节的文件**不报**（不能凭猜定罪）。

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_figurebytes.py`：

```python
import tempfile
import unittest
from pathlib import Path

from ccfa.figurebytes import check_figure_formats, sniff

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 8
GIF = b"GIF89a" + b"\x00" * 8


class TestSniff(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _write(self, name, body):
        path = self.root / name
        path.write_bytes(body)
        return path

    def test_detects_png_jpeg_gif_pdf(self):
        self.assertEqual(sniff(self._write("a", PNG)), ".png")
        self.assertEqual(sniff(self._write("b", JPEG)), ".jpg")
        self.assertEqual(sniff(self._write("c", GIF)), ".gif")
        self.assertEqual(sniff(self._write("d", b"%PDF-1.4\n")), ".pdf")

    def test_unknown_bytes_return_none(self):
        self.assertIsNone(sniff(self._write("e", b"not an image at all")))

    def test_unreadable_path_returns_none(self):
        self.assertIsNone(sniff(self.root / "gone.png"))


class TestCheckFigureFormats(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _write(self, name, body):
        path = self.root / name
        path.write_bytes(body)
        return path

    def test_matching_png_is_clean(self):
        self.assertEqual(check_figure_formats([self._write("a.png", PNG)]), [])

    def test_jpeg_bytes_named_png_is_reported(self):
        problems = check_figure_formats([self._write("a.png", JPEG)])
        self.assertEqual([p.code for p in problems], ["figure-format"])
        self.assertIn("jpg", problems[0].message)

    def test_jpeg_bytes_named_jpeg_is_clean(self):
        self.assertEqual(check_figure_formats([self._write("a.jpeg", JPEG)]), [])

    def test_unknown_bytes_are_not_convicted(self):
        self.assertEqual(check_figure_formats([self._write("a.png", b"???")]), [])

    def test_pdf_suffix_is_out_of_scope(self):
        self.assertEqual(check_figure_formats([self._write("a.pdf", JPEG)]), [])

    def test_missing_file_is_skipped_not_crashed(self):
        self.assertEqual(check_figure_formats([self.root / "gone.png"]), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ModuleNotFoundError: No module named 'ccfa.figurebytes'`。

- [ ] **Step 3: 实现**

创建 `tools/ccfa/figurebytes.py`：

```python
"""Detect a file's real byte format and flag extension mismatches.

A figure re-encoded to another format, or simply renamed, breaks downstream
tooling while looking fine in a directory listing; only the byte signature is
honest. Files whose bytes cannot be identified are never convicted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ccfa.cli import Problem

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"%PDF", ".pdf"),
)
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif")


def sniff(path: Path) -> str | None:
    try:
        with Path(path).open("rb") as handle:
            head = handle.read(16)
    except OSError:
        return None
    for signature, suffix in _MAGIC:
        if head.startswith(signature):
            return suffix
    return None


def check_figure_formats(paths: Iterable[Path]) -> list[Problem]:
    problems: list[Problem] = []
    for path in paths:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix not in _IMAGE_SUFFIXES:
            continue
        actual = sniff(path)
        if actual is None:
            continue
        if actual == suffix or (actual == ".jpg" and suffix == ".jpeg"):
            continue
        problems.append(
            Problem(
                "figure-format",
                str(path),
                None,
                f"文件字节是 {actual.lstrip('.')}，扩展名却是 {suffix.lstrip('.')}"
                f"（应重新编码，不要改名）",
            )
        )
    return problems
```

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 262 tests`，`OK`（253 + 9）。

判别力检查：把 `sniff` 改成直接返回 `path.suffix.lower()`，`test_jpeg_bytes_named_png_is_reported` 必须失败；恢复。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/figurebytes.py tools/tests/test_figurebytes.py
git commit -m "feat: sniff figure bytes and flag extension mismatches"
```

---

### Task 2: PDF 文本提取与未解析标记

**Files:**
- Create: `tools/ccfa/pdftext.py`
- Create: `tools/tests/test_pdftext.py`

**Interfaces:**
- Produces:
  - `Reader = Callable[[Path], str]`
  - `extract_text(pdf: Path, reader: Reader | None = None) -> str | None`（缺 PyMuPDF 或读不出 → `None`）
  - `find_unresolved_markers(text: str, path: str) -> list[Problem]`（code `unresolved-marker`）
- 标记判定：`?` 两侧必须都是边界字符——`(?<=[\s(\[])\?(?=[\s,.;)\]]|$)`。这样 `[?]`、`(?)`、` ? ` 会被报出，而正常问句 `Why?` 不会（`?` 前是字母）。

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_pdftext.py`：

```python
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from ccfa.pdftext import extract_text, find_unresolved_markers


class TestFindUnresolvedMarkers(unittest.TestCase):
    def test_bracketed_marker_is_reported(self):
        problems = find_unresolved_markers("see [?] here", "paper.pdf")
        self.assertEqual([p.code for p in problems], ["unresolved-marker"])

    def test_spaced_marker_is_reported_with_line(self):
        problems = find_unresolved_markers("a\nb ? c\n", "paper.pdf")
        self.assertEqual(problems[0].line, 2)

    def test_prose_question_mark_is_not_reported(self):
        self.assertEqual(find_unresolved_markers("Why? Because.", "paper.pdf"), [])

    def test_two_markers_yield_two_problems(self):
        self.assertEqual(len(find_unresolved_markers("[?] and [?]", "p")), 2)

    def test_no_text_is_clean(self):
        self.assertEqual(find_unresolved_markers("", "p"), [])


class TestExtractText(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_injected_reader_is_used(self):
        seen = []

        def reader(path):
            seen.append(path)
            return "hello"

        pdf = self.root / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        self.assertEqual(extract_text(pdf, reader=reader), "hello")
        self.assertEqual(seen, [pdf])

    def test_missing_pymupdf_returns_none(self):
        pdf = self.root / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        with patch.dict(sys.modules, {"pymupdf": None}):
            self.assertIsNone(extract_text(pdf))

    def test_unreadable_pdf_returns_none(self):
        self.assertIsNone(extract_text(self.root / "gone.pdf"))

    def test_real_pdf_text_is_extracted(self):
        pdf = self.root / "real.pdf"
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), "HELLO WORLD")
        document.save(str(pdf))
        document.close()
        text = extract_text(pdf)
        self.assertIsNotNone(text)
        self.assertIn("HELLO", text.replace("\n", " "))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ModuleNotFoundError: No module named 'ccfa.pdftext'`。

- [ ] **Step 3: 实现**

创建 `tools/ccfa/pdftext.py`：

```python
"""Extract text from a rendered PDF and find unresolved reference markers.

The rendered PDF is the baseline, not the compile log: a citation that failed
to resolve leaves a literal '?' in the output even when the build succeeded.
PyMuPDF is optional at runtime -- when it is unavailable this module returns
None, and the caller must report the check as skipped, never as passing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from ccfa.cli import Problem

Reader = Callable[[Path], str]

# A '?' counts as a marker only when both sides are boundary characters, so an
# ordinary question in prose ("Why?") is not convicted.
_MARKER = re.compile(r"(?<=[\s(\[])\?(?=[\s,.;)\]]|$)")


def extract_text(pdf: Path, reader: Reader | None = None) -> str | None:
    pdf = Path(pdf)
    if reader is not None:
        return reader(pdf)
    try:
        import pymupdf
    except ImportError:
        return None
    try:
        with pymupdf.open(str(pdf)) as document:
            return "".join(page.get_text() for page in document)
    except Exception:
        # Any failure to read means "text unavailable" -- the caller reports a
        # skipped check. A corrupt PDF must never crash the tool, and must
        # never be mistaken for a passing check.
        return None


def find_unresolved_markers(text: str, path: str) -> list[Problem]:
    problems: list[Problem] = []
    for match in _MARKER.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        problems.append(
            Problem("unresolved-marker", path, line, "PDF 文本中存在未解析的引用标记 '?'")
        )
    return problems
```

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 271 tests`，`OK`（262 + 9）。

注意 `test_real_pdf_text_is_extracted` 会用 PyMuPDF 现场生成一个真 PDF——这是唯一一条走真实依赖的用例，它的存在意味着"PDF 路径真的能读出文本"这件事有证据，而不是只靠注入的假 reader。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/pdftext.py tools/tests/test_pdftext.py
git commit -m "feat: extract PDF text and find unresolved markers"
```

---

### Task 3: manifest 逐条核验

**Files:**
- Create: `tools/ccfa/figure_manifest.py`
- Create: `tools/tests/test_figure_manifest.py`

**Interfaces:**
- Consumes: `ccfa.figurebytes.sniff`、`ccfa.cli.Problem`、PyYAML
- Produces:
  - `load_manifest(path: Path) -> list[dict]`（不可读 / 非列表 / 条目非对象 → `ValueError`）
  - `check_manifest(items: list[dict], paper_root: Path) -> tuple[list[Problem], list[Problem]]`
- codes：`figure-missing`、`figure-hash`、`figure-manifest-format`（problem）；`manifest-missing-file`、`unreferenced-figure`（advisory）
- `file` 字段相对 `paper_root`；缺字段时回退 `<paper_root>/figures/<name>.<bytes_format>` 并记一条 `manifest-missing-file` advisory（spec v6 §6.3 / Ruling P2）。

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_figure_manifest.py`：

```python
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

    def _item(self, **overrides):
        item = {
            "name": "plot",
            "file": "figures/plot.png",
            "bytes_format": "png",
            "generator": "src/plot.py",
            "generator_hash": "",
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

    def test_generator_hash_mismatch_is_reported(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(generator_hash="sha256:deadbeef")
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-hash", [p.code for p in problems])

    def test_missing_generator_script_is_reported(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(generator="src/gone.py", generator_hash="sha256:x")
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-hash", [p.code for p in problems])

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
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ModuleNotFoundError: No module named 'ccfa.figure_manifest'`。

- [ ] **Step 3: 实现**

创建 `tools/ccfa/figure_manifest.py`：

```python
"""Validate figures/manifest.yaml against the files it claims to describe.

The manifest is what makes a figure traceable: which run produced it, which
script generated it, and where the text references it. A manifest that has
drifted from reality is worse than no manifest, so every claim is checked
against bytes rather than trusted.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from ccfa.cli import Problem
from ccfa.figurebytes import sniff


def load_manifest(path: Path) -> list[dict]:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 manifest {path}: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"manifest 解析失败: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError("manifest 顶层必须是列表")
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"manifest 第 {index} 项必须是对象")
    return data


def _sha256(path: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _resolve_figure(item: dict, paper_root: Path) -> tuple[Path, Problem | None]:
    explicit = item.get("file")
    if explicit:
        return paper_root / str(explicit), None
    name = str(item.get("name", ""))
    suffix = str(item.get("bytes_format", "")).lstrip(".")
    fallback = paper_root / "figures" / f"{name}.{suffix}"
    advisory = Problem(
        "manifest-missing-file",
        str(fallback),
        None,
        f"manifest 条目 {name} 缺 file 字段，已回退到约定路径；建议显式补写",
    )
    return fallback, advisory


def check_manifest(
    items: list[dict], paper_root: Path
) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root)
    problems: list[Problem] = []
    advisories: list[Problem] = []
    for item in items:
        name = str(item.get("name", "<unnamed>"))
        figure, fallback_advisory = _resolve_figure(item, paper_root)
        if fallback_advisory is not None:
            advisories.append(fallback_advisory)

        if not figure.is_file():
            problems.append(
                Problem("figure-missing", str(figure), None, f"条目 {name} 的交付图不存在")
            )
        else:
            declared_raw = str(item.get("bytes_format", "")).lower().lstrip(".")
            actual = sniff(figure)
            if declared_raw and actual is not None and actual != "." + declared_raw:
                problems.append(
                    Problem(
                        "figure-manifest-format",
                        str(figure),
                        None,
                        f"条目 {name} 声明 bytes_format={declared_raw}，实际字节是 {actual.lstrip('.')}",
                    )
                )

        generator = item.get("generator")
        expected_hash = item.get("generator_hash")
        if generator and expected_hash:
            generator_path = paper_root / str(generator)
            actual_hash = _sha256(generator_path)
            if actual_hash is None:
                problems.append(
                    Problem(
                        "figure-hash",
                        str(generator_path),
                        None,
                        f"条目 {name} 的生成脚本不存在: {generator}",
                    )
                )
            elif actual_hash != str(expected_hash):
                problems.append(
                    Problem(
                        "figure-hash",
                        str(generator_path),
                        None,
                        f"条目 {name} 的生成脚本哈希不符（记录 {expected_hash}，实际 {actual_hash}）",
                    )
                )

        if not item.get("referenced_in"):
            advisories.append(
                Problem(
                    "unreferenced-figure",
                    str(figure),
                    None,
                    f"条目 {name} 未记录正文引用位置",
                )
            )
    return problems, advisories
```

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 284 tests`，`OK`（271 + 13：6 条 load + 7 条 check）。

判别力检查：把 `_sha256` 改成返回 `str(expected_hash)`（即永远"相符"），`test_generator_hash_mismatch_is_reported` 必须失败；恢复。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/figure_manifest.py tools/tests/test_figure_manifest.py
git commit -m "feat: verify figure manifest entries against real bytes"
```

---

## 验收

```powershell
$root = "<repo-root>"
cd $root
& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v
```

期望：基线 **253** + 本计划新增 **31**（9 + 9 + 13），共 **284** 个测试通过。

按 spec v6 逐条核对（Part A 覆盖的部分）：

- 图片字节与扩展名不符能被报出（`figure-format`），且无法识别的字节不会被误定罪。
- PDF 文本中的未解析 `?` 能被报出（`unresolved-marker`），正常问句不会误报；PyMuPDF 缺失时返回 `None`（交由 Part B 记 skipped，**不是通过**）。
- manifest 的四类声明（交付图存在、声明格式、生成脚本哈希、正文引用）逐条与真实字节/文件对账；缺 `file` 字段回退并记 advisory。

已知边界（留给最终全分支评审）：

- `sniff` 只认 PNG/JPEG/GIF/PDF 四种魔数，WebP/TIFF/EPS 不识别（不报，即不误定罪）。
- `pdftext` 用 `except Exception` 兜住 PyMuPDF 的读取失败——这是"降级为 skipped，绝不假通过"的有意选择；代价是它也会吞掉库自身的编程错误（例如 API 改名）。Part B 的 skipped 报告是这件事的可见性补偿。
- `find_unresolved_markers` 用启发式边界判定，`?` 紧贴字母时不报（如 `Fig.?`）。

## Part B（另立计划，不在本计划范围）

`final_check` 核心与 CLI：组合本计划三个模块 + 复用 `ccfa.dataval.find_untagged`（数字缺标记 advisory）+ 声明缺失 advisory + **skipped 以 `check-skipped` advisory 表示**；CLI 参数 `--manuscript/--pdf/--manifest/--paper-root`，退出码 0/1/2；e2e 用 PyMuPDF 现场生成 PDF 夹具。
