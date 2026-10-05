# provenance 实施计划 — Part B（只读核对与导出）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `provenance` 加上只读的漂移核对 `check` 与导出 `export`，并补端到端回归——让"来源说明"能被机械核对，而不是靠人相信。

**Architecture:** 继续 Task 1 建的单工具三子命令。`check` 只读，把 store 里每条声明与真实字节对账；`export` 只读 store、产出人读 markdown，写文件时走同一套写盘契约（原子写、不覆盖）。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v6：§6.1、§6.1.1 写盘补充契约、§10）
**Part A：** `<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-provenance.md`（已完成，HEAD `748c78e`，322 tests）
**账本：** `<repo-root>/.superpowers/sdd/2026-10-03-evidence-tracking/progress.md`

## Global Constraints

- 仓库根：`<repo-root>`
- 退出码：`0` 通过，`1` 发现问题（`check` 的漂移/缺文件/缺来源/分类非法），`2` 工具自身出错。
- `check` **只读**；`export` 仅在给了 `--out` 时写文件，且必须原子写、已存在时拒绝（除非 `--force`）。
- **写盘路径的 `OSError` 一律折成 `ValueError`**（Ruling E5 已把这条定为跨工具规则，见账本）。
- store 的 `version` 必须是 1（Ruling E6）。
- UTF-8 无 BOM；ASCII 标识符与注释；中文只在面向用户的消息里。
- 基线：**322 tests OK**，HEAD = `748c78e`，工作树干净。
- 测试命令：`& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`

---

### Task 2: 只读漂移核对（`check`）

**Files:**
- Modify: `tools/ccfa/provenance.py`
- Modify: `tools/tests/test_provenance.py`

**Interfaces:**
- Produces: `check_store(store_path: Path, paper_root: Path) -> list[Problem]`
- codes（全部 problem）：`provenance-missing-file`、`provenance-drift`、`provenance-missing-source`、`provenance-invalid-classification`

**判定表（逐条可测）**

| 条件 | code |
| --- | --- |
| 条目指向的文件不存在 | `provenance-missing-file` |
| 文件存在但 `sha256` 与记录不符 | `provenance-drift` |
| 条目缺 `source` 或为空 | `provenance-missing-source` |
| 条目 `classification` 不在三种之内 | `provenance-invalid-classification` |
| 以上都不满足 | 无输出 |

注意：分类非法在这里也要报，尽管 `add` 已拒绝过非法值——store 是人可编辑的 JSON，**写入时校验不构成读取时的信任**。

- [ ] **Step 1: 写失败测试**

在 `tools/tests/test_provenance.py` 的 import 中加入 `check_store`，并追加：

```python
class TestCheckStore(BaseCase):
    def _codes(self, problems):
        return sorted(p.code for p in problems)

    def test_consistent_entry_is_clean(self):
        self.add()
        self.assertEqual(check_store(self.store, self.root), [])

    def test_modified_file_is_reported_as_drift(self):
        self.add()
        (self.data / "raw.csv").write_text("a,b\n9,9\n", encoding="utf-8")
        self.assertEqual(self._codes(check_store(self.store, self.root)), ["provenance-drift"])

    def test_removed_file_is_reported_as_missing(self):
        self.add()
        (self.data / "raw.csv").unlink()
        self.assertEqual(
            self._codes(check_store(self.store, self.root)), ["provenance-missing-file"]
        )

    def test_empty_source_is_reported(self):
        self.add()
        store = load_store(self.store)
        store["files"]["data/raw.csv"]["source"] = ""
        save_store(self.store, store)
        self.assertEqual(
            self._codes(check_store(self.store, self.root)), ["provenance-missing-source"]
        )

    def test_hand_edited_invalid_classification_is_reported(self):
        self.add()
        store = load_store(self.store)
        store["files"]["data/raw.csv"]["classification"] = "made-up"
        save_store(self.store, store)
        self.assertEqual(
            self._codes(check_store(self.store, self.root)),
            ["provenance-invalid-classification"],
        )

    def test_check_does_not_write(self):
        self.add()
        before = self.store.read_bytes()
        check_store(self.store, self.root)
        self.assertEqual(self.store.read_bytes(), before)
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ImportError: cannot import name 'check_store'`。

- [ ] **Step 3: 实现**

在 `provenance.py` 中追加（`add_entry` 之后、`main` 之前）：

```python
def check_store(store_path: Path, paper_root: Path) -> list[Problem]:
    store = load_store(store_path)
    problems: list[Problem] = []
    for relpath, entry in sorted(store["files"].items()):
        target = Path(paper_root) / relpath
        if not str(entry.get("source", "")).strip():
            problems.append(
                Problem("provenance-missing-source", str(target), None, f"条目缺少来源: {relpath}")
            )
        classification = entry.get("classification")
        if classification not in VALID_CLASSIFICATIONS:
            problems.append(
                Problem(
                    "provenance-invalid-classification",
                    str(target),
                    None,
                    f"条目分类非法: {classification!r}（{relpath}）",
                )
            )
        if not target.is_file():
            problems.append(
                Problem("provenance-missing-file", str(target), None, f"来源文件不存在: {relpath}")
            )
            continue
        try:
            actual = sha256_of(target)
        except OSError as exc:
            raise ValueError(f"无法读取来源文件 {target}: {exc}") from exc
        if actual != entry.get("sha256"):
            problems.append(
                Problem(
                    "provenance-drift",
                    str(target),
                    None,
                    f"文件内容与记录不符: {relpath}（记录 {entry.get('sha256')}，实际 {actual}）",
                )
            )
    return problems
```

并在 `main` 的 subparser 区加 `check` 子命令（无额外参数），在 `args.command == "check"` 分支里
`return emit(check_store(Path(args.store), Path(args.paper_root)), [])`。

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 328 tests`，`OK`（322 + 6）。

判别力检查：把 `actual != entry.get("sha256")` 改成恒 `False`，`test_modified_file_is_reported_as_drift` 必须失败；恢复。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/provenance.py tools/tests/test_provenance.py
git commit -m "feat: check recorded provenance against real bytes"
```

---

### Task 3: 导出人读文档（`export`）

**Files:**
- Modify: `tools/ccfa/provenance.py`
- Modify: `tools/tests/test_provenance.py`

**Interfaces:**
- Produces:
  - `render_markdown(store: dict) -> str`
  - `write_markdown(path: Path, text: str, force: bool = False) -> None`（原子写；已存在且未 `force` → `ValueError`）
  - CLI：`export [--out PATH] [--force]`；不给 `--out` 时打 stdout（不写文件）

**markdown 形状**：一个 H1、一个表格，列固定为 `路径 | 分类 | 来源 | 字节 | sha256 | 登记时间`，`sha256` 只显示前 12 位十六进制（全值仍在 store 里）；条目按路径排序。

- [ ] **Step 1: 写失败测试**

追加：

```python
class TestExport(BaseCase):
    def test_markdown_has_a_row_per_entry(self):
        self.add(notes="first")
        text = render_markdown(load_store(self.store))
        self.assertIn("data/raw.csv", text)
        self.assertIn("| 路径 |", text)
        # header row + separator row + the single data row
        self.assertEqual(text.count("\n| "), 3)

    def test_short_hash_is_shown(self):
        entry = self.add()
        text = render_markdown(load_store(self.store))
        self.assertIn(entry["sha256"][7:19], text)
        self.assertNotIn(entry["sha256"], text)

    def test_render_does_not_write(self):
        self.add()
        render_markdown(load_store(self.store))
        self.assertTrue(self.store.exists())

    def test_write_markdown_creates_the_file(self):
        out = self.root / "data" / "provenance.md"
        write_markdown(out, "# doc\n")
        self.assertEqual(out.read_text(encoding="utf-8"), "# doc\n")

    def test_write_markdown_refuses_to_overwrite_without_force(self):
        out = self.root / "data" / "provenance.md"
        write_markdown(out, "first")
        with self.assertRaises(ValueError):
            write_markdown(out, "second")
        self.assertEqual(out.read_text(encoding="utf-8"), "first")

    def test_write_markdown_force_replaces(self):
        out = self.root / "data" / "provenance.md"
        write_markdown(out, "first")
        write_markdown(out, "second", force=True)
        self.assertEqual(out.read_text(encoding="utf-8"), "second")
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ImportError: cannot import name 'render_markdown'`。

- [ ] **Step 3: 实现**

```python
def render_markdown(store: dict) -> str:
    lines = [
        "# 数据来源",
        "",
        "| 路径 | 分类 | 来源 | 字节 | sha256 | 登记时间 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for relpath, entry in sorted(store["files"].items()):
        digest = str(entry.get("sha256", ""))
        short = digest.split(":", 1)[-1][:12]
        lines.append(
            f"| {relpath} | {entry.get('classification', '')} | {entry.get('source', '')} "
            f"| {entry.get('size', '')} | {short} | {entry.get('recorded_at', '')} |"
        )
    return "\n".join(lines) + "\n"


def write_markdown(path: Path, text: str, force: bool = False) -> None:
    path = Path(path)
    if path.exists() and not force:
        raise ValueError(f"导出目标已存在: {path}（如需覆盖请显式使用 --force）")
    save_text_atomically(path, text)
```

其中 `save_text_atomically` 是把 Task 1 `save_store` 里的"临时文件 + `os.replace` + `OSError → ValueError`"抽出来的共用函数，`save_store` 改为调用它（**唯一允许的改动**：行为必须逐位不变，包括临时文件名与 JSON 缩进）。

`main` 加 `export` 子命令：`--out`、`--force`；给了 `--out` 就 `write_markdown` 并 `emit([], [])`；没给就 `print(render_markdown(store))` 并返回 0。

> **契约说明（有意偏离）**：`export` 不给 `--out` 时 stdout 是**markdown 文档本身**，不是 JSON。§6.1.1 的"机器可读 JSON 走 stdout"针对的是检查类输出；`export` 的产物就是一份人读文档，把它包进 JSON 只会让下游多剥一层。`check` 与 `add` 仍然走 JSON。

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 334 tests`，`OK`（328 + 6）。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/provenance.py tools/tests/test_provenance.py
git commit -m "feat: export provenance as markdown without silent overwrite"
```

---

### Task 4: 端到端回归

**Files:**
- Create: `tools/tests/test_provenance_e2e.py`

**行为规格**

| 场景 | 期望 |
| --- | --- |
| `add` 一个文件后 `check` | `0`，JSON `problem_count` 为 0 |
| 改动文件后 `check` | `1`，code `provenance-drift`，stderr 含路径 |
| store 缺 `version` | `2`，stdout 为空 |
| `export`（不带 `--out`） | `0`，stdout 含 markdown 表头与该路径 |
| `export --out` 指向已存在文件且未 `--force` | `2`，stdout 为空 |

- [ ] **Step 1: 写测试**

创建 `tools/tests/test_provenance_e2e.py`：用 `subprocess.run([...], encoding="utf-8")` 调 `tools/ccfa/provenance.py`，`PYTHONPATH` 指向 `tools/`；`--store` 与 `--paper-root` 放在子命令**之前**（argparse 的顶层参数位置，参考实现的文档也特别标注过这个坑）。五个用例对应上表五行。

- [ ] **Step 2: 运行测试确认通过**

Expected: `Ran 339 tests`，`OK`（334 + 5）。

- [ ] **Step 3: 提交**

```powershell
git add tools/tests/test_provenance_e2e.py
git commit -m "test: add provenance end-to-end regression"
```

---

## 验收

期望：基线 **322** + 本计划新增 **17**（6 + 6 + 5），共 **339** 个测试通过。

逐条核对：

- `check` 只读且能报出漂移、缺文件、缺来源、分类非法四类问题；**写入时校验不构成读取时的信任**（手改 store 也会被抓）。
- `export` 不打 `--out` 时只打 stdout、不写任何文件；打 `--out` 时原子写且不覆盖。
- 写盘路径的 `OSError` 仍归为退出码 2（E5 的规则在本计划的两个新写点同样成立）。

已知边界：markdown 表格不转义 `|`（来源里含竖线会破表）；`check` 不扫描"存在于磁盘但未登记"的数据文件（要不要报、报哪些目录，是本层之外的策略问题）。

## 后续

provenance 完成后进入 `run-log` 的两个任务（包裹命令执行 + 只读检查 `metrics-pending`），随后是"复现与归档"计划（含被推迟的 `research-version`，按 E4 走 git 薄封装）。
