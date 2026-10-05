# provenance（数据来源）实施计划 — Part A

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成 `provenance` 工具：逐文件记录来源与分类，用校验和把"说明"钉在真实字节上，并提供只读的漂移检查与 markdown 导出。

**Architecture:** 一个工具、三个子命令。`add` 是唯一的写路径（原子写、不覆盖）；`check` 只读，把 store 与真实文件对账；`export` 只读，生成人读文档。store 用 spec §10 的规范位置 `data/provenance.json`，导出到 `data/provenance.md`。

**为什么单工具而不是"写模块 + 独立检查模块"：** spec §6.1 把它列为**一个**工具 `provenance`，而 §6.1.1 的只读约束写法是"检查类工具（…）只读"——即允许同一工具存在只读的 check 模式（先例：`citation-guard` 的检查模式）。拆成两个模块会让 store 的解析逻辑出现两份。

**Tech Stack:** Python 3.12（`tools/.venv`）；stdlib `hashlib` / `json` / `argparse`；unittest。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v6：§6.1、§6.1.1 的写盘补充契约、§10）

**预研账本：** `<repo-root>/.superpowers/sdd/2026-10-03-evidence-tracking/progress.md`（裁定 E1–E4）

## 参考实现

`research-suite/tools/provenance-manifest/provenance_manifest.py`（MIT）提供了正确的骨架——子命令 `add` / `check` / `verify-checksums` / `export`、单 store、`VALID_CLASSIFICATIONS = ("real", "rescaled-real", "documented-substitute")`。**不照搬**的是它的写入方式：它直接改写 store，没有原子写与不覆盖保证；我们的写盘契约（§6.1.1 v6 补记）要求更严。

## Global Constraints

- 仓库根：`<repo-root>`
- 退出码：`0` 通过，`1` 发现问题（`check` 的漂移/缺来源/分类非法），`2` 工具自身出错。
- `check` 与 `export` **只读**；`add` 是唯一写路径，且必须满足：**原子写**（先写临时文件再改名）、**不覆盖**（同名条目已存在时拒绝，除非 `--force`）、**幂等可查**（重复 `check` 不产生任何写入）。
- store 顶层形状：`{"version": 1, "files": {"<相对 paper_root 的路径>": {...}}}`。
- 条目字段：`source`、`classification`、`sha256`、`size`、`recorded_at` 必填；`units`、`coverage`、`notes`、`calibration`（列表）可选。
- `classification` 限 `real` / `rescaled-real` / `documented-substitute`。
- UTF-8 无 BOM；默认 ASCII 注释，中文只出现在面向用户的 `Problem.message` 里。
- 不得写入或提交含用户名的绝对路径（store 里的键必须是相对路径）。
- 基线：**305 tests OK**，HEAD = `2c87264`，工作树干净。
- 测试命令：`& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
- 既有接口：`ccfa.cli.Problem` / `ToolEnvironmentError` / `emit` / `tool_error`。

---

### Task 1: store 的写入路径（`add`）

**Files:**
- Create: `tools/ccfa/provenance.py`
- Create: `tools/tests/test_provenance.py`

**Interfaces:**
- Produces:
  - `VALID_CLASSIFICATIONS: tuple[str, ...]`
  - `load_store(path: Path) -> dict`（不可读 / 非法 JSON / 顶层不是对象 / `files` 不是对象 → `ValueError`）
  - `save_store(path: Path, store: dict) -> None`（**原子写**：同目录临时文件 + `os.replace`）
  - `sha256_of(path: Path) -> str`（返回 `"sha256:<hex>"`）
  - `add_entry(store_path, paper_root, relpath, *, source, classification, units=None, coverage=None, notes=None, force=False) -> dict`
  - `main(argv: list[str]) -> int`

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_provenance.py`：

```python
import json
import tempfile
import unittest
from pathlib import Path

from ccfa.provenance import (
    VALID_CLASSIFICATIONS,
    add_entry,
    load_store,
    save_store,
    sha256_of,
)


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.data = self.root / "data"
        self.data.mkdir()
        (self.data / "raw.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        self.store = self.root / "data" / "provenance.json"

    def add(self, **overrides):
        kwargs = dict(source="internal export", classification="real")
        kwargs.update(overrides)
        return add_entry(self.store, self.root, "data/raw.csv", **kwargs)


class TestSha256(BaseCase):
    def test_hash_is_prefixed_and_stable(self):
        first = sha256_of(self.data / "raw.csv")
        self.assertTrue(first.startswith("sha256:"))
        self.assertEqual(first, sha256_of(self.data / "raw.csv"))


class TestStoreRoundTrip(BaseCase):
    def test_missing_store_is_empty(self):
        self.assertEqual(load_store(self.store), {"version": 1, "files": {}})

    def test_save_then_load_round_trips(self):
        save_store(self.store, {"version": 1, "files": {"a": {"source": "x"}}})
        self.assertEqual(load_store(self.store)["files"]["a"]["source"], "x")

    def test_non_object_store_raises(self):
        self.store.write_text("[1, 2]\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_store(self.store)

    def test_malformed_json_raises(self):
        self.store.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_store(self.store)

    def test_save_leaves_no_temporary_file_behind(self):
        save_store(self.store, {"version": 1, "files": {}})
        leftovers = [p.name for p in self.data.iterdir() if p.name != "provenance.json"]
        self.assertEqual([n for n in leftovers if n.startswith("provenance.")], [])


class TestAddEntry(BaseCase):
    def test_records_source_classification_and_checksum(self):
        entry = self.add(units="count", coverage="2020-2024", notes="exported 2026-10")
        self.assertEqual(entry["classification"], "real")
        self.assertEqual(entry["units"], "count")
        self.assertEqual(entry["sha256"], sha256_of(self.data / "raw.csv"))
        self.assertIn("recorded_at", entry)
        self.assertEqual(entry["size"], (self.data / "raw.csv").stat().st_size)

    def test_store_is_written_with_the_entry(self):
        self.add()
        self.assertIn("data/raw.csv", load_store(self.store)["files"])

    def test_invalid_classification_is_rejected(self):
        with self.assertRaises(ValueError):
            self.add(classification="made-up")

    def test_absolute_path_is_rejected(self):
        with self.assertRaises(ValueError):
            add_entry(
                self.store,
                self.root,
                str(self.data / "raw.csv"),
                source="x",
                classification="real",
            )

    def test_missing_source_file_is_rejected(self):
        with self.assertRaises(ValueError):
            add_entry(
                self.store, self.root, "data/gone.csv", source="x", classification="real"
            )

    def test_existing_entry_is_not_overwritten_without_force(self):
        self.add(notes="first")
        with self.assertRaises(ValueError):
            self.add(notes="second")
        self.assertEqual(load_store(self.store)["files"]["data/raw.csv"]["notes"], "first")

    def test_force_allows_rewriting(self):
        self.add(notes="first")
        self.add(notes="second", force=True)
        self.assertEqual(load_store(self.store)["files"]["data/raw.csv"]["notes"], "second")

    def test_classification_list_is_exposed(self):
        self.assertEqual(
            VALID_CLASSIFICATIONS, ("real", "rescaled-real", "documented-substitute")
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ModuleNotFoundError: No module named 'ccfa.provenance'`。

- [ ] **Step 3: 实现**

创建 `tools/ccfa/provenance.py`：

```python
"""Record where each data file came from, and keep that record honest.

The store is a claim about real bytes; a checksum is what lets `check` notice
when the claim drifts. Writing is deliberately strict: atomic, and refusing to
overwrite an existing entry, because the record of a failed or superseded
source is itself evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ccfa.cli import Problem, ToolEnvironmentError, emit, tool_error

VALID_CLASSIFICATIONS = ("real", "rescaled-real", "documented-substitute")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest}"


def load_store(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"version": 1, "files": {}}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 store {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"store 不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("store 顶层必须是对象")
    files = data.get("files")
    if not isinstance(files, dict):
        raise ValueError("store 的 files 必须是对象")
    return data


def save_store(path: Path, store: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def add_entry(
    store_path: Path,
    paper_root: Path,
    relpath: str,
    *,
    source: str,
    classification: str,
    units: str | None = None,
    coverage: str | None = None,
    notes: str | None = None,
    force: bool = False,
) -> dict:
    if classification not in VALID_CLASSIFICATIONS:
        raise ValueError(
            f"classification 非法: {classification!r}，应为 {' / '.join(VALID_CLASSIFICATIONS)}"
        )
    if Path(relpath).is_absolute():
        raise ValueError(f"条目路径必须是相对 paper_root 的相对路径: {relpath}")
    target = Path(paper_root) / relpath
    if not target.is_file():
        raise ValueError(f"来源文件不存在: {target}")

    store = load_store(store_path)
    files = store.setdefault("files", {})
    if relpath in files and not force:
        raise ValueError(f"条目已存在: {relpath}（如需覆盖请显式使用 --force）")

    entry = {
        "source": source,
        "classification": classification,
        "sha256": sha256_of(target),
        "size": target.stat().st_size,
        "recorded_at": _now_iso(),
    }
    for key, value in (("units", units), ("coverage", coverage), ("notes", notes)):
        if value is not None:
            entry[key] = value
    files[relpath] = entry
    save_store(store_path, store)
    return entry


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="数据来源记录与核对")
    parser.add_argument("--store", required=True)
    parser.add_argument("--paper-root", required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="登记一个数据文件的来源")
    add.add_argument("relpath")
    add.add_argument("--source", required=True)
    add.add_argument("--classification", required=True, choices=VALID_CLASSIFICATIONS)
    add.add_argument("--units")
    add.add_argument("--coverage")
    add.add_argument("--notes")
    add.add_argument("--force", action="store_true")

    args = parser.parse_args(argv[1:])
    try:
        if args.command == "add":
            add_entry(
                Path(args.store),
                Path(args.paper_root),
                args.relpath,
                source=args.source,
                classification=args.classification,
                units=args.units,
                coverage=args.coverage,
                notes=args.notes,
                force=args.force,
            )
            return emit([], [])
    except (ValueError, ToolEnvironmentError) as exc:
        return tool_error(str(exc))
    return tool_error(f"未知子命令: {args.command}")


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
```

> `check` 与 `export` 子命令在 Task 2 加入；本任务只做写入路径，`main` 先只支持 `add`。

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 319 tests`，`OK`（305 + 14）。

判别力检查：把 `save_store` 里的 `os.replace` 换成直接 `path.write_text(...)`，其余不变——测试仍全绿（因为原子性不可观测）。因此**这条不能用测试判别**，改用代码审查：在报告中写明"原子写不可由单测证伪，只能靠实现审查"，并由评审者核对该点。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/provenance.py tools/tests/test_provenance.py
git commit -m "feat: record data provenance with checksums and no silent overwrite"
```

---

## 验收（Part A Task 1）

```powershell
$root = "<repo-root>"
cd $root
& "$root/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v
```

期望：基线 **305** + 本任务新增 **14**，共 **319** 个测试通过。

逐条核对：

- 每条记录含来源、分类、校验和（`sha256:` 前缀）、字节数、登记时间；分类限三种。
- 绝对路径被拒（store 的键必须是相对路径，避免把用户名写进仓库）。
- 已有条目在未给 `--force` 时拒绝覆盖——**失败/被取代的来源记录本身就是证据，不能被悄悄盖掉**。
- `save_store` 先写同目录临时文件再 `os.replace`；正常路径不留下临时文件。

已知边界（留给最终全分支评审）：

- 原子写的**不可观测性**：单测无法证伪"直接写"，只能靠实现审查（上面已写明）。若要更强的保证，需要故障注入（写一半时中断），本计划不做。
- `save_store` 的临时文件名固定为 `<name>.tmp`，两个进程并发写同一 store 会互相踩；并发写不在本层目标内（一次实验一个 run 文件，见 E1）。

## Part B（另立计划，不在本计划范围）

`check`（只读：文件漂移、缺来源、分类非法 → problem；`--force` 覆盖过的条目可选报出）与 `export`（生成 `data/provenance.md`），外加端到端回归。之后是 `run-log` 的两个任务（包裹命令执行 + 只读检查 `metrics-pending`）。
