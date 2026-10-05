# 论文模板库骨架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `paper-template` 模板库，使一条命令能派生出一篇可编译的新论文项目，并带有可机读的阶段与 gate 定义。

**Architecture:** 模板库是纯文件系统加一组 Python CLI 工具。阶段状态机用 Python 常量定义，成为唯一事实来源；`ccfa.yaml` 与 checklist 都由它派生，避免文档与代码漂移。派生脚本把 venue 对应的 LaTeX 模板从共享模板树复制进新项目，编译驱动按显式四步执行。

**Tech Stack:** Python 3.12（Codex 内置运行时）、stdlib `unittest`、PyYAML（唯一外部依赖，装在项目本地 venv）、MiKTeX、git。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`

## Global Constraints

- 模板库根目录：`<home>/Documents/Codex/paper-template`
- 论文库根目录：`<home>/Documents/Codex/papers`
- Python 解释器：`<home>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`
- 所有工具脚本返回码语义：`0` 通过，`1` 发现问题，`2` 工具自身出错。三者不得合并。
- 所有文本文件写为 UTF-8 无 BOM。
- 不得写入或提交含用户名的绝对路径；共享模板树位置从 `CODEX_HOME` 解析，默认 `~/.codex`。
- 不得使用 `latexmk`（本机缺 Perl，实测不可用）。
- 派生脚本绝不覆盖已存在的论文目录。
- 检查类工具只读，不写文件。
- 默认 ASCII 注释；中文只出现在面向用户的文案与数据里。

---

## File Structure

| 路径 | 职责 |
| --- | --- |
| `paper-template/.gitignore` | 排除 venv、构建产物、PDF 原件 |
| `paper-template/README.md` | 用法与目录约定 |
| `paper-template/ccfa.yaml.template` | 新项目状态文件模板 |
| `paper-template/checklists/conference.md` | 会议模式 gate 清单（生成物） |
| `paper-template/checklists/journal.md` | 期刊模式 gate 清单（生成物） |
| `paper-template/library/refs.bib` | 共享 BibTeX |
| `paper-template/library/papers/.gitkeep` | PDF 原件占位（不入 git） |
| `paper-template/tools/pyproject.toml` | 工具依赖声明 |
| `paper-template/tools/ccfa/stages.py` | 阶段与 gate 的唯一事实来源 |
| `paper-template/tools/ccfa/validate.py` | `ccfa.yaml` 校验器 |
| `paper-template/tools/newpaper/venues.py` | venue 到 LaTeX 模板目录的解析 |
| `paper-template/tools/newpaper/create.py` | 派生新论文项目 |
| `paper-template/tools/newpaper/checklists.py` | 由 `stages.py` 生成 checklist |
| `paper-template/tools/build/compile.py` | 显式四步编译驱动 |
| `paper-template/tools/tests/` | 六个测试模块 |

每个文件只承担一件事。`stages.py` 是唯一事实来源；`checklists.py` 与 `create.py` 都从它读取，不各写一份。

---

### Task 1: 模板库骨架与 git

**Files:**
- Create: `paper-template/.gitignore`
- Create: `paper-template/library/papers/.gitkeep`
- Create: `paper-template/tools/tests/test_scaffold.py`
- Create: `paper-template/tools/tests/__init__.py`

**Interfaces:**
- Consumes: 无
- Produces: 模板库目录契约。后续任务的测试都假定该结构存在。

- [ ] **Step 1: 创建目录与 `.gitignore`**

```powershell
$root = "<home>/Documents/Codex/paper-template"
New-Item -ItemType Directory -Force -Path `
  "$root/checklists", "$root/library/papers", "$root/tools/ccfa", `
  "$root/tools/newpaper", "$root/tools/build", "$root/tools/tests" | Out-Null
```

`paper-template/.gitignore`：

```gitignore
tools/.venv/
*.aux
*.log
*.out
*.bbl
*.blg
*.fls
*.fdb_latexmk
*.synctex.gz
library/papers/*.pdf
!library/papers/.gitkeep
__pycache__/
*.pyc
```

`paper-template/library/papers/.gitkeep`：空文件。

- [ ] **Step 2: 写失败测试**

`paper-template/tools/tests/test_scaffold.py`：

```python
import unittest
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parents[2]


class TestScaffoldContract(unittest.TestCase):
    def test_required_directories_exist(self):
        required = [
            "checklists",
            "library",
            "library/papers",
            "tools/ccfa",
            "tools/newpaper",
            "tools/build",
            "tools/tests",
        ]
        for rel in required:
            with self.subTest(rel=rel):
                self.assertTrue((TEMPLATE_ROOT / rel).is_dir(), f"缺少目录: {rel}")

    def test_gitignore_excludes_build_products(self):
        gitignore = (TEMPLATE_ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ["tools/.venv/", "*.aux", "*.log", "*.pdf"]:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, gitignore)

    def test_papers_dir_kept_but_pdfs_ignored(self):
        gitignore = (TEMPLATE_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!library/papers/.gitkeep", gitignore)
        self.assertTrue((TEMPLATE_ROOT / "library" / "papers" / ".gitkeep").is_file())
```

`paper-template/tools/tests/__init__.py`：空文件。

- [ ] **Step 3: 运行测试确认通过**

Run:
```powershell
$py = "<home>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
cd "<home>/Documents/Codex/paper-template"
& $py -m unittest discover -s tools/tests -t tools -v
```
Expected: PASS，3 个测试通过。

- [ ] **Step 4: 初始化 git 并提交**

```powershell
cd "<home>/Documents/Codex/paper-template"
git init
git add .
git commit -m "chore: scaffold paper-template repo structure"
```

---

### Task 2: 工具环境与 `ccfa.yaml` 校验器

> **执行顺序提示**：本任务的测试依赖 Task 3 的 `ccfa.stages`。建议先做 Task 3 再做本任务的 Step 2 之后部分；若先做本任务，Step 4 实现完后测试会因缺少 `ccfa.stages` 而报错，那是预期状态，完成 Task 3 后回本任务 Step 5 提交即可。

**Files:**
- Create: `paper-template/tools/pyproject.toml`
- Create: `paper-template/tools/ccfa/__init__.py`
- Create: `paper-template/tools/ccfa/validate.py`
- Create: `paper-template/tools/tests/test_validate.py`

**Interfaces:**
- Consumes: Task 1 的目录骨架
- Produces:
  - `validate_yaml(path: pathlib.Path) -> list[str]`，返回问题列表，空列表表示通过；文件无法解析时抛 `ValueError`
  - `main(argv: list[str]) -> int`，0 通过 / 1 有问题 / 2 工具出错
  - 依赖 `ccfa.stages.stages_for`（Task 3 提供）

- [ ] **Step 1: 建立项目本地 venv 并装 PyYAML**

```powershell
$py = "<home>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
$root = "<home>/Documents/Codex/paper-template"
& $py -m venv "$root/tools/.venv"
& "$root/tools/.venv/Scripts/python.exe" -m pip install --quiet pyyaml
& "$root/tools/.venv/Scripts/python.exe" -c "import yaml; print('pyyaml', yaml.__version__)"
```
Expected: 打印 pyyaml 版本号。

`paper-template/tools/pyproject.toml`：

```toml
[project]
name = "paper-template-tools"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["pyyaml>=6.0"]
```

- [ ] **Step 2: 写失败测试**

`paper-template/tools/tests/test_validate.py`：

```python
import tempfile
import unittest
from pathlib import Path

from ccfa.validate import validate_yaml

VALID = """\
version: "0.4.0"
project:
  title: "Demo"
  short_name: "demo"
  root: "."
target_venue:
  name: "NeurIPS"
  year: "2027"
  mode: "conference"
stage:
  current: "idea"
  gate: "scope_defined"
  updated_at: "2026-10-03"
artifacts:
  manuscript: "manuscript/main.tex"
  bibliography: "manuscript/references.bib"
claims: []
experiments: []
reviews: []
revision_ledger:
  path: "reviews/revision-ledger.md"
  status: "not_started"
submission_checks:
  path: "submission/checks.md"
  status: "not_started"
"""


def _write(text: str) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "ccfa.yaml"
    tmp.write_text(text, encoding="utf-8")
    return tmp


class TestValidateYaml(unittest.TestCase):
    def test_valid_file_has_no_problems(self):
        self.assertEqual(validate_yaml(_write(VALID)), [])

    def test_missing_required_top_level_field(self):
        broken = VALID.replace("claims: []\n", "")
        problems = validate_yaml(_write(broken))
        self.assertTrue(any("claims" in p for p in problems), problems)

    def test_invalid_mode_is_reported(self):
        broken = VALID.replace('mode: "conference"', 'mode: "workshop"')
        problems = validate_yaml(_write(broken))
        self.assertTrue(any("mode" in p for p in problems), problems)

    def test_invalid_stage_for_conference_mode(self):
        broken = VALID.replace('current: "idea"', 'current: "major-revision"')
        problems = validate_yaml(_write(broken))
        self.assertTrue(any("major-revision" in p for p in problems), problems)

    def test_unparsable_yaml_raises_not_returns(self):
        with self.assertRaises(ValueError):
            validate_yaml(_write("version: [unclosed\n"))
```

- [ ] **Step 3: 运行测试确认失败**

Run: `& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'ccfa.validate'`

- [ ] **Step 4: 实现校验器**

`paper-template/tools/ccfa/validate.py`：

```python
"""Validate ccfa.yaml against the project state contract."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REQUIRED_TOP_LEVEL = [
    "version",
    "project",
    "target_venue",
    "stage",
    "artifacts",
    "claims",
    "experiments",
    "reviews",
    "revision_ledger",
    "submission_checks",
]

VALID_MODES = ("conference", "journal")
REQUIRED_VENUE_FIELDS = ("name", "year", "mode")


def validate_yaml(path: Path) -> list[str]:
    """Return a list of problems; empty means valid.

    Raises ValueError when the file cannot be parsed, so a parse failure is
    never confused with a clean pass.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 解析失败: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("顶层必须是一个映射")

    problems: list[str] = []

    for field in REQUIRED_TOP_LEVEL:
        if field not in data:
            problems.append(f"缺少顶层字段: {field}")

    venue = data.get("target_venue")
    if isinstance(venue, dict):
        for field in REQUIRED_VENUE_FIELDS:
            if not venue.get(field):
                problems.append(f"target_venue.{field} 不能为空")
        mode = venue.get("mode")
        if mode and mode not in VALID_MODES:
            problems.append(
                f"target_venue.mode 非法: {mode!r}，应为 {' 或 '.join(VALID_MODES)}"
            )
    elif "target_venue" in data:
        problems.append("target_venue 必须是映射")

    stage = data.get("stage")
    if isinstance(stage, dict):
        current = stage.get("current")
        if current:
            from ccfa.stages import stages_for

            mode = (venue or {}).get("mode", "conference")
            if mode in VALID_MODES and current not in stages_for(mode):
                problems.append(f"stage.current 不适用于 {mode} 模式: {current!r}")
    elif "stage" in data:
        problems.append("stage 必须是映射")

    for list_field in ("claims", "experiments", "reviews"):
        value = data.get(list_field)
        if value is not None and not isinstance(value, list):
            problems.append(f"{list_field} 必须是列表")

    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法: validate.py <ccfa.yaml 路径>", file=sys.stderr)
        return 2

    path = Path(argv[1])
    if not path.is_file():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 2

    try:
        problems = validate_yaml(path)
    except ValueError as exc:
        print(f"工具错误: {exc}", file=sys.stderr)
        return 2

    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

`paper-template/tools/ccfa/__init__.py`：空文件。

- [ ] **Step 5: 提交**

```powershell
git add tools/pyproject.toml tools/ccfa tools/tests/test_validate.py
git commit -m "feat: add ccfa.yaml validator with 0/1/2 exit code contract"
```

---

### Task 3: 阶段与 gate 定义

**Files:**
- Create: `paper-template/tools/ccfa/stages.py`
- Create: `paper-template/tools/tests/test_stages.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `Gate = NamedTuple("Gate", [("id", str), ("criterion", str)])`
  - `SHARED_STAGES: list[str]`（10 个阶段，`idea` 到 `submitted`）
  - `CONFERENCE_TAIL: list[str]`、`JOURNAL_TAIL: list[str]`
  - `stages_for(mode: str) -> list[str]`，未知 mode 抛 `ValueError`
  - `gate_for(mode: str, stage: str) -> Gate`，未知 stage 抛 `KeyError`
  - `all_gates(mode: str) -> list[tuple[str, Gate]]`

本任务是 Task 2 测试通过的前置条件。

- [ ] **Step 1: 写失败测试**

`paper-template/tools/tests/test_stages.py`：

```python
import unittest

from ccfa.stages import (
    CONFERENCE_TAIL,
    JOURNAL_TAIL,
    SHARED_STAGES,
    all_gates,
    gate_for,
    stages_for,
)


class TestStages(unittest.TestCase):
    def test_shared_stages_are_identical_for_both_modes(self):
        shared = SHARED_STAGES
        self.assertEqual(stages_for("conference")[: len(shared)], shared)
        self.assertEqual(stages_for("journal")[: len(shared)], shared)

    def test_shared_stages_end_at_submitted(self):
        self.assertEqual(SHARED_STAGES[0], "idea")
        self.assertEqual(SHARED_STAGES[-1], "submitted")
        self.assertEqual(len(SHARED_STAGES), 10)

    def test_conference_tail_ends_archived(self):
        self.assertEqual(CONFERENCE_TAIL, ["rebuttal", "camera-ready", "archived"])

    def test_journal_tail_ends_archived(self):
        self.assertEqual(
            JOURNAL_TAIL,
            ["major-revision", "response-letter", "resubmitted", "accepted", "archived"],
        )

    def test_every_stage_has_a_gate(self):
        for mode in ("conference", "journal"):
            for stage in stages_for(mode):
                with self.subTest(mode=mode, stage=stage):
                    gate = gate_for(mode, stage)
                    self.assertTrue(gate.id)
                    self.assertTrue(gate.criterion)

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            stages_for("workshop")

    def test_unknown_stage_raises(self):
        with self.assertRaises(KeyError):
            gate_for("conference", "not-a-stage")

    def test_gate_ids_are_unique_within_a_mode(self):
        for mode in ("conference", "journal"):
            ids = [g.id for _, g in all_gates(mode)]
            self.assertEqual(len(ids), len(set(ids)), f"{mode} 模式存在重复 gate id")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'ccfa.stages'`

- [ ] **Step 3: 实现状态机**

`paper-template/tools/ccfa/stages.py`：

```python
"""Stage and gate definitions: the single source of truth.

Design doc section 4.1/4.2. Checklists and ccfa.yaml validation both read
from here so the documentation cannot drift from the state machine.
"""

from __future__ import annotations

from typing import NamedTuple


class Gate(NamedTuple):
    id: str
    criterion: str


SHARED_STAGES: list[str] = [
    "idea",
    "grounded",
    "data-ready",
    "experiment-design",
    "experiments-running",
    "results-ready",
    "writing",
    "internal-review",
    "submission-check",
    "submitted",
]

CONFERENCE_TAIL: list[str] = ["rebuttal", "camera-ready", "archived"]
JOURNAL_TAIL: list[str] = [
    "major-revision",
    "response-letter",
    "resubmitted",
    "accepted",
    "archived",
]

_SHARED_GATES: dict[str, Gate] = {
    "idea": Gate(
        "scope_defined",
        "问题陈述、至少一条可检验假设、目标 venue 均写明",
    ),
    "grounded": Gate(
        "novelty_grounded",
        "列出三篇最近邻工作及各自盲区，说明本工作填补的是哪一个无人测量的合取；"
        "禁止没人做过式表述",
    ),
    "data-ready": Gate(
        "provenance_recorded",
        "逐份数据有来源、分类与校验和；来源文档可被脚本核对；不合规来源已排除",
    ),
    "experiment-design": Gate(
        "design_frozen",
        "每个 claim 对应一个实验；baseline 来源明确；metric 定义明确；"
        "含种子计划、失败判据与平台画像",
    ),
    "experiments-running": Gate(
        "results_recorded",
        "experiments/log/ 逐次运行留有配置、种子、commit、退出码、指标",
    ),
    "results-ready": Gate(
        "claims_supported",
        "每个 claim 指到具体数值，且该数值通过行内标记脚本核对；"
        "无支撑项标记待验证或删除",
    ),
    "writing": Gate(
        "draft_complete",
        "正文、图表、引用齐备；页数符合 venue；所有引用条目来自检索期已核验的条目",
    ),
    "internal-review": Gate(
        "review_cleared",
        "跨模型评审报告无 blocking 项；引用、数字、图表三项核验通过",
    ),
    "submission-check": Gate(
        "package_ready",
        "模板、匿名、页数、元数据检查通过；复现包在干净环境实际重跑成功",
    ),
    "submitted": Gate("venue_decided", "收到 venue 决定，评审意见归档"),
}

_CONFERENCE_GATES: dict[str, Gate] = {
    "rebuttal": Gate("rebuttal_submitted", "逐条回应完成，修改范围与承诺一致"),
    "camera-ready": Gate(
        "final_package_ready", "终稿符合 camera-ready 规范；确定性终稿检查通过"
    ),
    "archived": Gate("archived", "终稿、复现包、数据来源文档归档"),
}

_JOURNAL_GATES: dict[str, Gate] = {
    "major-revision": Gate(
        "revision_planned", "每条意见有明确处置方案，含不采纳的正当理由"
    ),
    "response-letter": Gate("response_complete", "逐点回复完成，与实际改动一致"),
    "resubmitted": Gate("resubmission_ready", "改动稿与回复信齐备，修改痕迹保留"),
    "accepted": Gate("accepted", "数据来源文档、model card、data card 齐备"),
    "archived": Gate("archived", "确定性终稿检查通过；全部材料归档"),
}


def stages_for(mode: str) -> list[str]:
    if mode == "conference":
        return SHARED_STAGES + CONFERENCE_TAIL
    if mode == "journal":
        return SHARED_STAGES + JOURNAL_TAIL
    raise ValueError(f"未知 mode: {mode!r}，应为 conference 或 journal")


def gate_for(mode: str, stage: str) -> Gate:
    stages_for(mode)
    if stage in _SHARED_GATES:
        return _SHARED_GATES[stage]
    table = _CONFERENCE_GATES if mode == "conference" else _JOURNAL_GATES
    return table[stage]


def all_gates(mode: str) -> list[tuple[str, Gate]]:
    return [(stage, gate_for(mode, stage)) for stage in stages_for(mode)]
```

- [ ] **Step 4: 运行确认通过**

Run: `& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
Expected: PASS，8 个 stage 测试与 5 个 validate 测试全部通过。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/stages.py tools/tests/test_stages.py
git commit -m "feat: define stage and gate state machine as single source of truth"
```

---

### Task 4: venue 解析与新建脚本

**Files:**
- Create: `paper-template/tools/newpaper/__init__.py`
- Create: `paper-template/tools/newpaper/venues.py`
- Create: `paper-template/tools/newpaper/create.py`
- Create: `paper-template/ccfa.yaml.template`
- Create: `paper-template/tools/tests/test_venues.py`
- Create: `paper-template/tools/tests/test_create.py`

**Interfaces:**
- Consumes: `ccfa.stages.gate_for`、`ccfa.validate.validate_yaml`
- Produces:
  - `class VenueNotFound(Exception)`
  - `templates_root() -> Path`，读 `CODEX_HOME`
  - `available_venues() -> list[str]`
  - `resolve_venue(venue: str) -> Path`，大小写不敏感
  - `create_project(papers_root, slug, venue, year, mode, title) -> Path`
  - `main(argv: list[str]) -> int`

- [ ] **Step 1: 写 venue 解析的失败测试**

`paper-template/tools/tests/test_venues.py`：

```python
import os
import unittest
from pathlib import Path

from newpaper.venues import VenueNotFound, resolve_venue, templates_root


class TestVenueResolution(unittest.TestCase):
    def test_templates_root_honours_codex_home(self):
        original = os.environ.get("CODEX_HOME")
        try:
            os.environ["CODEX_HOME"] = "C:/fake/codex"
            self.assertEqual(
                templates_root(), Path("C:/fake/codex/skills/ccf-latex-templates")
            )
        finally:
            if original is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = original

    def test_known_venue_resolves_to_existing_directory(self):
        path = resolve_venue("NeurIPS")
        self.assertTrue(path.is_dir(), path)

    def test_venue_lookup_is_case_insensitive(self):
        self.assertEqual(resolve_venue("neurips"), resolve_venue("NeurIPS"))

    def test_unknown_venue_raises_with_available_list(self):
        with self.assertRaises(VenueNotFound) as ctx:
            resolve_venue("NotAVenue2099")
        self.assertIn("NotAVenue2099", str(ctx.exception))
        self.assertIn("NeurIPS", str(ctx.exception))
```

- [ ] **Step 2: 运行确认失败**

Run: `& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'newpaper.venues'`

- [ ] **Step 3: 实现 venue 解析**

`paper-template/tools/newpaper/venues.py`：

```python
"""Resolve a venue name to its LaTeX template directory."""

from __future__ import annotations

import os
from pathlib import Path


class VenueNotFound(Exception):
    """Raised when no template directory matches the requested venue."""


def templates_root() -> Path:
    codex_home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    return Path(codex_home) / "skills" / "ccf-latex-templates"


def available_venues() -> list[str]:
    root = templates_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def resolve_venue(venue: str) -> Path:
    root = templates_root()
    target = venue.strip().lower()
    for candidate in available_venues():
        if candidate.lower() == target:
            return root / candidate
    options = ", ".join(available_venues()[:12])
    raise VenueNotFound(
        f"找不到 venue {venue!r} 的模板。模板根: {root}。"
        f"可用示例: {options or '模板根不存在'}"
    )
```

`paper-template/tools/newpaper/__init__.py`：空文件。

- [ ] **Step 4: 运行确认通过**

Run: 同上
Expected: PASS，4 个 venue 测试通过。

- [ ] **Step 5: 写新建脚本的失败测试**

`paper-template/tools/tests/test_create.py`：

```python
import tempfile
import unittest
from pathlib import Path

from ccfa.validate import validate_yaml
from newpaper.create import create_project
from newpaper.venues import VenueNotFound


class TestCreateProject(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.papers = self.tmp / "papers"
        self.papers.mkdir()

    def _create(self, slug="demo-paper", venue="NeurIPS", mode="conference"):
        return create_project(
            papers_root=self.papers,
            slug=slug,
            venue=venue,
            year="2027",
            mode=mode,
            title="Demo Paper",
        )

    def test_creates_expected_tree(self):
        root = self._create()
        for rel in [
            "ccfa.yaml",
            "manuscript/sections",
            "manuscript/references.bib",
            "data/provenance.md",
            "experiments/log",
            "experiments/results",
            "figures",
            "tables",
            "reviews/revision-ledger.md",
            "submission/repro",
            "memory/ideas.md",
            "memory/dead-ends.md",
            "ccfa-workfiles/literature",
        ]:
            with self.subTest(rel=rel):
                self.assertTrue((root / rel).exists(), f"缺少 {rel}")

    def test_ccfa_yaml_is_valid_and_carries_mode(self):
        root = self._create(mode="journal")
        problems = validate_yaml(root / "ccfa.yaml")
        self.assertEqual(problems, [], problems)
        text = (root / "ccfa.yaml").read_text(encoding="utf-8")
        self.assertIn('mode: "journal"', text)

    def test_stage_starts_at_idea(self):
        root = self._create()
        text = (root / "ccfa.yaml").read_text(encoding="utf-8")
        self.assertIn('current: "idea"', text)

    def test_refuses_to_overwrite_existing_directory(self):
        root = self._create()
        marker = root / "manuscript" / "keep-me.txt"
        marker.write_text("user content", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self._create()
        self.assertTrue(marker.exists(), "已存在的用户文件被破坏")

    def test_seeds_bibliography_and_manuscript(self):
        root = self._create()
        self.assertTrue((root / "manuscript" / "references.bib").is_file())
        tex_files = list((root / "manuscript").glob("*.tex"))
        tex_files += list((root / "manuscript").glob("*.sty"))
        self.assertTrue(tex_files, "venue 模板文件未被复制到 manuscript/")

    def test_unknown_venue_propagates(self):
        with self.assertRaises(VenueNotFound):
            self._create(venue="NotAVenue2099")
```

- [ ] **Step 6: 运行确认失败**

Run: 同上
Expected: FAIL，`ModuleNotFoundError: No module named 'newpaper.create'`

- [ ] **Step 7: 实现新建脚本与模板**

`paper-template/ccfa.yaml.template`：

```yaml
version: "0.4.0"
project:
  title: "__TITLE__"
  short_name: "__SLUG__"
  root: "."
target_venue:
  name: "__VENUE__"
  year: "__YEAR__"
  mode: "__MODE__"
stage:
  current: "idea"
  gate: "scope_defined"
  updated_at: "__DATE__"
artifacts:
  manuscript: "manuscript/main.tex"
  bibliography: "manuscript/references.bib"
  figures: "figures/"
  tables: "tables/"
  experiments: "experiments/"
  reviews: "reviews/"
  submission: "submission/"
claims: []
experiments: []
reviews: []
revision_ledger:
  path: "reviews/revision-ledger.md"
  status: "not_started"
submission_checks:
  path: "submission/checks.md"
  status: "not_started"
```

`paper-template/tools/newpaper/create.py`：

```python
"""Create a new paper project from the template repository."""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

from ccfa.stages import gate_for
from newpaper.venues import resolve_venue

TEMPLATE_ROOT = Path(__file__).resolve().parents[2]

PAPER_DIRS = [
    "manuscript/sections",
    "data",
    "experiments/log",
    "experiments/results",
    "figures",
    "tables",
    "reviews",
    "submission/repro",
    "memory",
    "ccfa-workfiles/literature",
    "ccfa-workfiles/figures",
    "ccfa-workfiles/writing",
]

SEED_FILES = {
    "memory/ideas.md": "# 选题记忆\n",
    "memory/dead-ends.md": "# 反重复记忆\n",
    "reviews/revision-ledger.md": "# 审稿意见矩阵\n",
    "submission/checks.md": "# 投稿检查\n",
    "data/provenance.md": "# 数据来源\n",
}


def create_project(
    papers_root: Path,
    slug: str,
    venue: str,
    year: str,
    mode: str,
    title: str,
) -> Path:
    target = Path(papers_root) / slug
    if target.exists():
        raise FileExistsError(f"目标目录已存在，拒绝覆盖: {target}")

    venue_dir = resolve_venue(venue)
    target.mkdir(parents=True)

    for rel in PAPER_DIRS:
        (target / rel).mkdir(parents=True, exist_ok=True)

    manuscript = target / "manuscript"
    for entry in venue_dir.iterdir():
        if entry.is_file():
            shutil.copy2(entry, manuscript / entry.name)

    shared_bib = TEMPLATE_ROOT / "library" / "refs.bib"
    bib_target = manuscript / "references.bib"
    if shared_bib.is_file():
        shutil.copy2(shared_bib, bib_target)
    else:
        bib_target.write_text("", encoding="utf-8")

    date = dt.date.today().isoformat()
    template = (TEMPLATE_ROOT / "ccfa.yaml.template").read_text(encoding="utf-8")
    rendered = (
        template.replace("__TITLE__", title)
        .replace("__SLUG__", slug)
        .replace("__VENUE__", venue)
        .replace("__YEAR__", str(year))
        .replace("__MODE__", mode)
        .replace("__DATE__", date)
    )
    (target / "ccfa.yaml").write_text(rendered, encoding="utf-8")

    for rel, content in SEED_FILES.items():
        (target / rel).write_text(content, encoding="utf-8")

    return target


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="派生一个新的论文项目")
    parser.add_argument("slug")
    parser.add_argument("--venue", required=True)
    parser.add_argument("--year", required=True)
    parser.add_argument("--mode", required=True, choices=["conference", "journal"])
    parser.add_argument("--title", default="")
    parser.add_argument(
        "--papers-root",
        default=str(Path.home() / "Documents" / "Codex" / "papers"),
    )
    args = parser.parse_args(argv[1:])

    try:
        target = create_project(
            papers_root=Path(args.papers_root),
            slug=args.slug,
            venue=args.venue,
            year=args.year,
            mode=args.mode,
            title=args.title or args.slug,
        )
    except FileExistsError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"工具错误: {exc}", file=sys.stderr)
        return 2

    gate = gate_for(args.mode, "idea")
    print(str(target))
    print(f"起始 gate: {gate.id} — {gate.criterion}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 8: 运行确认通过**

Run: `& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
Expected: PASS，6 个 create 测试通过。

- [ ] **Step 9: 提交**

```powershell
git add ccfa.yaml.template tools/newpaper tools/tests/test_venues.py tools/tests/test_create.py
git commit -m "feat: add venue resolution and paper project scaffolding"
```

---

### Task 5: 主文件识别与编译驱动

**Files:**
- Create: `paper-template/tools/ccfa/texdoc.py`
- Create: `paper-template/tools/build/__init__.py`
- Create: `paper-template/tools/build/compile.py`
- Create: `paper-template/tools/tests/test_texdoc.py`
- Create: `paper-template/tools/tests/test_compile.py`
- Modify: `paper-template/tools/newpaper/create.py`
- Modify: `paper-template/tools/tests/test_create.py`

**Interfaces:**
- Consumes: Task 4 的 `create_project`
- Produces:
  - `find_main_tex(manuscript_dir: Path) -> Path`，找不到抛 `FileNotFoundError`
  - `class CompileResult`，字段 `ok: bool`、`steps: list[tuple[str, int]]`、`pdf: Path | None`、`log_tail: str`
  - `compile_project(main_tex: Path, build_dir: Path, engine: str = "pdflatex") -> CompileResult`

为什么需要 `find_main_tex`：各 venue 模板的主文件名不同（NeurIPS 是 `neurips_2026.tex`，CVPR 是 `main.tex`），不能写死。派生时探测真实主文件并回填 `ccfa.yaml` 的 `artifacts.manuscript`。

- [ ] **Step 1: 写主文件识别的失败测试**

`paper-template/tools/tests/test_texdoc.py`：

```python
import tempfile
import unittest
from pathlib import Path

from ccfa.texdoc import find_main_tex


def _write(dirpath: Path, name: str, body: str) -> Path:
    path = dirpath / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestFindMainTex(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_finds_single_documentclass_file(self):
        expected = _write(
            self.tmp, "neurips_2026.tex", r"\documentclass{article}\begin{document}\end{document}"
        )
        _write(self.tmp, "preamble.tex", r"\newcommand{\foo}{bar}")
        self.assertEqual(find_main_tex(self.tmp), expected)

    def test_prefers_conventional_main_name(self):
        _write(self.tmp, "aaa_template.tex", r"\documentclass{article}")
        expected = _write(self.tmp, "main.tex", r"\documentclass{article}")
        self.assertEqual(find_main_tex(self.tmp), expected)

    def test_searches_subdirectories(self):
        expected = _write(self.tmp / "src", "paper.tex", r"\documentclass{article}")
        self.assertEqual(find_main_tex(self.tmp), expected)

    def test_no_documentclass_raises(self):
        _write(self.tmp, "notes.tex", "just notes, no document class")
        with self.assertRaises(FileNotFoundError):
            find_main_tex(self.tmp)

    def test_empty_directory_raises(self):
        with self.assertRaises(FileNotFoundError):
            find_main_tex(self.tmp)
```

- [ ] **Step 2: 运行确认失败**

Run: `& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'ccfa.texdoc'`

- [ ] **Step 3: 实现主文件识别**

`paper-template/tools/ccfa/texdoc.py`：

```python
"""Locate the main LaTeX file inside a manuscript directory."""

from __future__ import annotations

from pathlib import Path

CONVENTIONAL_STEMS = {"main", "paper"}


def find_main_tex(manuscript_dir: Path) -> Path:
    """Return the .tex file that contains \\documentclass.

    Raises FileNotFoundError when no such file exists.
    """
    root = Path(manuscript_dir)
    candidates: list[Path] = []
    for tex in sorted(root.rglob("*.tex")):
        try:
            text = tex.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\\documentclass" in text:
            candidates.append(tex)

    if not candidates:
        raise FileNotFoundError(
            f"在 {root} 中找不到包含 \\documentclass 的 .tex 文件"
        )

    for candidate in candidates:
        if candidate.stem.lower() in CONVENTIONAL_STEMS:
            return candidate
    return candidates[0]
```

- [ ] **Step 4: 运行确认通过**

Run: 同上
Expected: PASS，5 个 texdoc 测试通过。

- [ ] **Step 5: 让派生脚本回填真实主文件路径**

在 `paper-template/tools/tests/test_create.py` 的 `TestCreateProject` 中追加：

```python
    def test_records_detected_main_tex_in_ccfa_yaml(self):
        from ccfa.texdoc import find_main_tex

        root = self._create()
        main = find_main_tex(root / "manuscript")
        rel = main.relative_to(root).as_posix()
        text = (root / "ccfa.yaml").read_text(encoding="utf-8")
        self.assertIn(f'manuscript: "{rel}"', text)
```

Run: `& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
Expected: FAIL，`manuscript: "manuscript/main.tex"` 仍为模板占位值。

在 `paper-template/tools/newpaper/create.py` 中修改三处：

```python
from ccfa.texdoc import find_main_tex
```

```python
    main_tex = find_main_tex(manuscript)
    main_rel = main_tex.relative_to(target).as_posix()
```

```python
    rendered = (
        template.replace("__TITLE__", title)
        .replace("__SLUG__", slug)
        .replace("__VENUE__", venue)
        .replace("__YEAR__", str(year))
        .replace("__MODE__", mode)
        .replace("__DATE__", date)
        .replace('manuscript: "manuscript/main.tex"', f'manuscript: "{main_rel}"')
    )
```

Run: 同上
Expected: PASS。

- [ ] **Step 6: 写编译驱动的失败测试**

`paper-template/tools/tests/test_compile.py`：

```python
import tempfile
import unittest
from pathlib import Path

from build.compile import CompileResult, compile_project

PLAIN = r"""\documentclass{article}
\begin{document}
\section{Smoke}
Plain English path only.
\end{document}
"""

WITH_BIB = r"""\documentclass{article}
\begin{document}
See \cite{vaswani2017attention}.
\bibliographystyle{plain}
\bibliography{sample}
\end{document}
"""

SAMPLE_BIB = """\
@inproceedings{vaswani2017attention,
  title     = {Attention Is All You Need},
  author    = {Vaswani, Ashish},
  booktitle = {NeurIPS},
  year      = {2017}
}
"""


class TestCompileProject(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tex = self.tmp / "main.tex"

    def test_plain_document_compiles(self):
        self.tex.write_text(PLAIN, encoding="utf-8")
        result = compile_project(self.tex, self.tmp / "build")
        self.assertIsInstance(result, CompileResult)
        self.assertTrue(result.ok, result.log_tail)
        self.assertIsNotNone(result.pdf)
        self.assertTrue(result.pdf.is_file())

    def test_bibliography_document_compiles_and_resolves_citation(self):
        self.tex.write_text(WITH_BIB, encoding="utf-8")
        (self.tmp / "sample.bib").write_text(SAMPLE_BIB, encoding="utf-8")
        result = compile_project(self.tex, self.tmp / "build2")
        self.assertTrue(result.ok, result.log_tail)
        names = [name for name, _ in result.steps]
        self.assertIn("bibtex", names, "含引用的文档必须触发 bibtex")
        aux = (self.tmp / "build2" / "main.aux").read_text(
            encoding="utf-8", errors="replace"
        )
        self.assertIn("bibcite", aux, "引用未被解析")

    def test_broken_document_fails_without_raising(self):
        self.tex.write_text(
            r"\documentclass{article}\begin{document}\undefinedcmd\end{document}",
            encoding="utf-8",
        )
        result = compile_project(self.tex, self.tmp / "build3")
        self.assertFalse(result.ok)
        self.assertIsNone(result.pdf)
        self.assertIn("undefinedcmd", result.log_tail)

    def test_missing_file_reports_tool_error(self):
        with self.assertRaises(FileNotFoundError):
            compile_project(self.tmp / "nope.tex", self.tmp / "build4")

    def test_never_invokes_latexmk(self):
        self.tex.write_text(PLAIN, encoding="utf-8")
        result = compile_project(self.tex, self.tmp / "build5")
        names = [name for name, _ in result.steps]
        self.assertNotIn("latexmk", names, "latexmk 本机缺 Perl，不得调用")

    def test_plain_document_skips_bibtex(self):
        self.tex.write_text(PLAIN, encoding="utf-8")
        result = compile_project(self.tex, self.tmp / "build6")
        names = [name for name, _ in result.steps]
        self.assertNotIn("bibtex", names, "无引用时不应调用 bibtex")
```

- [ ] **Step 7: 运行确认失败**

Run: 同上
Expected: FAIL，`ModuleNotFoundError: No module named 'build.compile'`

- [ ] **Step 8: 实现编译驱动**

`paper-template/tools/build/compile.py`：

```python
"""Compile a LaTeX project without latexmk.

latexmk is unavailable on this machine (it needs Perl). The build is an
explicit sequence so a failure can be attributed to a specific step.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CompileResult:
    ok: bool
    steps: list[tuple[str, int]] = field(default_factory=list)
    pdf: Path | None = None
    log_tail: str = ""


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout or ""


def _needs_bibtex(aux: Path) -> bool:
    if not aux.is_file():
        return False
    return "\\citation{" in aux.read_text(encoding="utf-8", errors="replace")


def compile_project(
    main_tex: Path,
    build_dir: Path,
    engine: str = "pdflatex",
) -> CompileResult:
    """Run latex, optionally bibtex, then latex twice more."""
    main_tex = Path(main_tex).resolve()
    if not main_tex.is_file():
        raise FileNotFoundError(f"找不到主文件: {main_tex}")
    if shutil.which(engine) is None:
        raise FileNotFoundError(f"找不到引擎: {engine}")

    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    stem = main_tex.stem
    base = [
        engine,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        f"-output-directory={build_dir}",
        str(main_tex),
    ]

    result = CompileResult(ok=False)
    transcript: list[str] = []

    code, out = _run(base, main_tex.parent)
    result.steps.append((engine, code))
    transcript.append(out)
    if code != 0:
        result.log_tail = out[-2000:]
        return result

    aux = build_dir / f"{stem}.aux"
    if _needs_bibtex(aux):
        bib_code, bib_out = _run(["bibtex", stem], build_dir)
        result.steps.append(("bibtex", bib_code))
        transcript.append(bib_out)

    for _ in range(2):
        code, out = _run(base, main_tex.parent)
        result.steps.append((engine, code))
        transcript.append(out)
        if code != 0:
            result.log_tail = out[-2000:]
            return result

    pdf = build_dir / f"{stem}.pdf"
    result.ok = pdf.is_file()
    result.pdf = pdf if result.ok else None
    result.log_tail = "\n".join(transcript)[-2000:]
    return result
```

`paper-template/tools/build/__init__.py`：空文件。

- [ ] **Step 9: 运行确认通过**

Run: `& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
Expected: PASS，6 个 compile 测试通过。这套测试同时验证了 BibTeX 链路。

- [ ] **Step 10: 提交**

```powershell
git add tools/ccfa/texdoc.py tools/build tools/tests/test_texdoc.py tools/tests/test_compile.py tools/newpaper/create.py tools/tests/test_create.py
git commit -m "feat: detect main tex and add explicit four-step compile driver"
```

---

### Task 6: 端到端回归测试

**Files:**
- Create: `paper-template/tools/tests/test_e2e.py`

**Interfaces:**
- Consumes: `newpaper.create.create_project`、`build.compile.compile_project`、`ccfa.validate.validate_yaml`
- Produces: 一条覆盖"派生 → 校验 → 编译"全链路的回归测试。

- [ ] **Step 1: 写端到端测试**

`paper-template/tools/tests/test_e2e.py`：

```python
import tempfile
import unittest
from pathlib import Path

from build.compile import compile_project
from ccfa.texdoc import find_main_tex
from ccfa.validate import validate_yaml
from newpaper.create import create_project


class TestEndToEnd(unittest.TestCase):
    def test_scaffold_validate_and_compile(self):
        papers = Path(tempfile.mkdtemp()) / "papers"
        root = create_project(
            papers_root=papers,
            slug="e2e-demo",
            venue="NeurIPS",
            year="2027",
            mode="conference",
            title="E2E Demo",
        )

        self.assertEqual(validate_yaml(root / "ccfa.yaml"), [])

        main_tex = find_main_tex(root / "manuscript")
        result = compile_project(main_tex, root / "ccfa-workfiles" / "build")
        self.assertTrue(result.ok, f"编译失败:\n{result.log_tail}")
        self.assertTrue(result.pdf.is_file())

    def test_journal_mode_scaffold_validates(self):
        papers = Path(tempfile.mkdtemp()) / "papers"
        root = create_project(
            papers_root=papers,
            slug="journal-demo",
            venue="NeurIPS",
            year="2027",
            mode="journal",
            title="Journal Demo",
        )
        self.assertEqual(validate_yaml(root / "ccfa.yaml"), [])
        text = (root / "ccfa.yaml").read_text(encoding="utf-8")
        self.assertIn('mode: "journal"', text)
```

- [ ] **Step 2: 运行确认失败**

Run: `& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
Expected: FAIL。若 venue 模板主文件缺少 `\documentclass`（例如某模板把正文放在 `\input` 的子文件中），`find_main_tex` 会抛 `FileNotFoundError`。此时换一个模板结构完整的 venue 重跑；若仍失败，说明该 venue 模板不完整，记下来并在 README 的已知约束里写明。

- [ ] **Step 3: 运行确认通过**

Run: 同上
Expected: PASS，2 个端到端测试通过。

- [ ] **Step 4: 提交**

```powershell
git add tools/tests/test_e2e.py
git commit -m "test: add end-to-end scaffold, validate and compile regression"
```

---

### Task 7: checklist 生成与 README

**Files:**
- Create: `paper-template/tools/newpaper/checklists.py`
- Create: `paper-template/tools/tests/test_checklists.py`
- Create: `paper-template/README.md`

**Interfaces:**
- Consumes: `ccfa.stages.stages_for`、`ccfa.stages.gate_for`
- Produces:
  - `render_checklist(mode: str) -> str`
  - `write_checklists(template_root: Path) -> list[Path]`

- [ ] **Step 1: 写失败测试**

`paper-template/tools/tests/test_checklists.py`：

```python
import unittest

from ccfa.stages import stages_for
from newpaper.checklists import render_checklist


class TestChecklistRendering(unittest.TestCase):
    def test_every_stage_appears_for_both_modes(self):
        for mode in ("conference", "journal"):
            text = render_checklist(mode)
            for stage in stages_for(mode):
                with self.subTest(mode=mode, stage=stage):
                    self.assertIn(f"[{stage}]", text)

    def test_conference_text_mentions_rebuttal(self):
        self.assertIn("rebuttal", render_checklist("conference"))

    def test_journal_text_mentions_response_letter(self):
        self.assertIn("response-letter", render_checklist("journal"))

    def test_checkbox_count_covers_every_stage(self):
        for mode in ("conference", "journal"):
            text = render_checklist(mode)
            with self.subTest(mode=mode):
                self.assertGreaterEqual(text.count("- [ ]"), len(stages_for(mode)))

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            render_checklist("workshop")
```

- [ ] **Step 2: 运行确认失败**

Run: `& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'newpaper.checklists'`

- [ ] **Step 3: 实现生成器**

`paper-template/tools/newpaper/checklists.py`：

```python
"""Render gate checklists from the stage machine.

Generated, not hand-written: the checklists cannot drift from stages.py.
"""

from __future__ import annotations

from pathlib import Path

from ccfa.stages import gate_for, stages_for

HEADER = """\
# {title}模式 gate 清单

本文件由 `tools/newpaper/checklists.py` 从 `tools/ccfa/stages.py` 生成。
不要手工编辑；改状态机后重新生成。

"""


def render_checklist(mode: str) -> str:
    stages = stages_for(mode)
    title = "会议" if mode == "conference" else "期刊"
    lines = [HEADER.format(title=title)]
    for index, stage in enumerate(stages, start=1):
        gate = gate_for(mode, stage)
        lines.append(f"## {index}. [{stage}]\n")
        lines.append(f"- [ ] gate `{gate.id}`")
        lines.append(f"  - 通过条件：{gate.criterion}\n")
    return "\n".join(lines)


def write_checklists(template_root: Path) -> list[Path]:
    written: list[Path] = []
    for mode, filename in (
        ("conference", "conference.md"),
        ("journal", "journal.md"),
    ):
        path = Path(template_root) / "checklists" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_checklist(mode), encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    for written_path in write_checklists(root):
        print(written_path)
```

- [ ] **Step 4: 运行确认通过**

Run: `& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
Expected: PASS，5 个 checklist 测试通过。

- [ ] **Step 5: 生成 checklist 文件**

```powershell
$env:PYTHONPATH = "<home>/Documents/Codex/paper-template/tools"
& "<home>/Documents/Codex/paper-template/tools/.venv/Scripts/python.exe" `
  "<home>/Documents/Codex/paper-template/tools/newpaper/checklists.py"
```
Expected: 打印 `checklists/conference.md` 与 `checklists/journal.md` 两个路径。

- [ ] **Step 6: 写 README**

`paper-template/README.md`：

```markdown
# paper-template

论文工作流模板库。每篇论文派生一份独立目录。

设计文档：`../2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`

## 目录约定

| 路径 | 用途 |
| --- | --- |
| `ccfa.yaml.template` | 新项目状态文件模板 |
| `checklists/` | gate 清单，由 `tools/ccfa/stages.py` 生成 |
| `library/` | 共享 BibTeX 与 PDF 原件 |
| `tools/` | 确定性工具（Python） |

## 派生一篇新论文

```powershell
$root = "<home>/Documents/Codex/paper-template"
$env:PYTHONPATH = "$root/tools"
$venv = "$root/tools/.venv/Scripts/python.exe"
& $venv "$root/tools/newpaper/create.py" my-paper `
    --venue NeurIPS --year 2027 --mode conference --title "My Paper"
```

## 重新生成 checklist

```powershell
& $venv "$root/tools/newpaper/checklists.py"
```

## 校验状态文件

```powershell
& $venv "$root/tools/ccfa/validate.py" path/to/ccfa.yaml
```

退出码：`0` 通过，`1` 发现问题，`2` 工具自身出错。

## 跑测试

```powershell
cd $root
& $venv -m unittest discover -s tools/tests -t tools -v
```

## 已知环境约束

- 编译不使用 `latexmk`（本机缺 Perl，实测报 `could not find the script engine 'perl'`）。编译驱动按 `pdflatex → bibtex → pdflatex → pdflatex` 显式执行。
- 中文文稿用 `xelatex` 加 `ctex`，已实测通过。
- 文献库索引用于中文时必须使用 FTS5 `trigram` 分词器；`unicode61` 对中文完全无效。
```

- [ ] **Step 7: 提交**

```powershell
git add tools/newpaper/checklists.py tools/tests/test_checklists.py checklists README.md
git commit -m "feat: generate gate checklists from the stage machine"
```

---

## 验收

全部任务完成后，以下命令应当全部通过：

```powershell
$root = "<home>/Documents/Codex/paper-template"
$venv = "$root/tools/.venv/Scripts/python.exe"
cd $root
& $venv -m unittest discover -s tools/tests -t tools -v
```

期望：7 个测试模块全部通过，其中包含一条"派生 → 校验 → 编译"的端到端回归。

## 后续计划（不在本计划范围）

本计划只交付模板库骨架。以下子系统的实现计划需另行编写：

| 计划 | 覆盖 |
| --- | --- |
| 引用与数字守卫 | `citation-guard`、`trace-claims` |
| 终稿与编译检查 | `latex-check`、`final-check`、图表 manifest |
| 证据追踪 | `provenance`、`run-log`、`research-version` |
| 复现与摩擦日志 | `repro-package`、`friction-log` |
| 知识层 | FTS5 索引器、记忆文件读写 |
| 自动化与评审 | 四类定时任务、`codex exec` 跨模型评审接线 |
