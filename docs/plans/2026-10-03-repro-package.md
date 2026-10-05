# repro-package 实施计划 — Part A（打包与清单）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成 `repro-package` 的打包侧：把"复现一个已报告结果"所需的最小文件集与命令固化成一份带哈希的清单，并把它复制成可直接验证的 bundle。

**Architecture:** 一个工具、两个子命令。`bundle` 是唯一的写路径（复制文件 + 原子写 `MANIFEST.json`，不覆盖已存在的输出目录）；`verify` 在 Part B（建新 venv、按 argv 重跑、三类失败分流）。命令一律以 **argv 数组**表达，`{python}` 占位符留给 Part B 替换。

**Tech Stack:** Python 3.12（`tools/.venv`）；stdlib `hashlib` / `json` / `shutil` / `platform` / `argparse`；unittest。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v6：§6.1、§6.1.1 写盘契约、§10）
**预研账本：** `<repo-root>/.superpowers/sdd/2026-10-03-evidence-tracking/progress.md`（Ruling E22–E24）

## 参考实现与两处偏离

`research-suite/tools/repro-package/repro_package.py`（MIT）。**吸收**：它把"干净环境"的范围写在文档首段（只装 bundle 声明依赖的新 venv，**不是**容器级隔离），并自陈"这是诚实、可实现的保证，不是对完全隔离的宣称"。
**偏离（Ruling E23）**：它用 shell 执行 bundle 的命令，并因此需要"只信任你自己的命令"这类免责声明；我们用 argv，不引入这条风险面。

## Global Constraints

- 仓库根：`<repo-root>`
- 退出码：`0` 通过，`1` 发现问题，`2` 工具自身出错。`bundle` 失败一律 2（它没有"发现问题"这一档）。
- 写盘契约（§6.1.1）：**原子写**、**不覆盖**（目标已存在时拒绝，除非 `--force`）、`OSError` → `ValueError` → 2。
- bundle 内的路径一律相对 `paper_root`；绝对路径与 `..` 逃逸一律拒绝（与 `provenance` 同规则）。
- `MANIFEST.json` 的 `version` 必须是 1（E6 规则：store 的版本字段必须校验）。
- UTF-8 无 BOM；ASCII 标识符与注释；中文只在面向用户的消息里。
- 基线：**379 tests OK**，HEAD = `2440356`，工作树干净。
- 测试命令：`& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
- 既有接口：`ccfa.cli.Problem` / `ToolEnvironmentError` / `emit` / `tool_error` / `save_text_atomically`。

---

### Task 1: bundle 构建与清单

**Files:**
- Create: `tools/ccfa/repro_package.py`
- Create: `tools/tests/test_repro_package.py`

**Interfaces:**
- Produces:
  - `MANIFEST_NAME = "MANIFEST.json"`
  - `sha256_of(path: Path) -> str`（`"sha256:<hex>"`）
  - `build_manifest(paper_root: Path, files: list[str], command: list[str], requirements: str | None, notes: str | None) -> dict`
  - `create_bundle(paper_root: Path, out_dir: Path, manifest: dict, *, force: bool = False) -> dict`
  - `load_manifest(bundle_dir: Path) -> dict`
  - `main(argv: list[str]) -> int`

**清单形状**（Part B 的 `verify` 依赖它，字段名不得改）

```json
{
  "version": 1,
  "created_at": "2026-10-03T14:25:30Z",
  "command": ["{python}", "train.py", "--config", "config.yaml"],
  "files": [{"path": "train.py", "sha256": "sha256:...", "size": 1234}],
  "requirements": {"path": "requirements.txt", "sha256": "sha256:..."},
  "notes": "Table 3 的主结果",
  "python": "3.12.14",
  "platform": "Windows-10-10.0.22631-SP0"
}
```

`requirements` 未给时为 `null`。`files` 按 `path` 排序，保证清单可复现。

**bundle 目录形状**：`<out_dir>/MANIFEST.json` + `<out_dir>/files/<原相对路径>`（保持目录结构），`requirements` 若给出也复制到 `<out_dir>/files/<其相对路径>`。

- [ ] **Step 1: 写失败测试**

创建 `tools/tests/test_repro_package.py`：

```python
import json
import tempfile
import unittest
from pathlib import Path

from ccfa.repro_package import (
    MANIFEST_NAME,
    build_manifest,
    create_bundle,
    load_manifest,
    sha256_of,
)


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "src").mkdir()
        (self.root / "src" / "train.py").write_text("print('train')\n", encoding="utf-8")
        (self.root / "configs").mkdir()
        (self.root / "configs" / "a.yaml").write_text("epochs: 5\n", encoding="utf-8")
        (self.root / "requirements.txt").write_text("numpy\n", encoding="utf-8")
        self.out = self.root / "bundles" / "result3"

    def manifest(self, **overrides):
        kwargs = dict(
            paper_root=self.root,
            files=["src/train.py", "configs/a.yaml"],
            command=["{python}", "src/train.py", "--config", "configs/a.yaml"],
            requirements="requirements.txt",
            notes="Table 3",
        )
        kwargs.update(overrides)
        return build_manifest(**kwargs)


class TestBuildManifest(BaseCase):
    def test_records_files_sorted_with_hashes_and_sizes(self):
        manifest = self.manifest()
        self.assertEqual([item["path"] for item in manifest["files"]], ["configs/a.yaml", "src/train.py"])
        first = manifest["files"][0]
        self.assertEqual(first["sha256"], sha256_of(self.root / "configs" / "a.yaml"))
        self.assertEqual(first["size"], (self.root / "configs" / "a.yaml").stat().st_size)

    def test_records_command_verbatim_as_argv(self):
        manifest = self.manifest()
        self.assertEqual(manifest["command"][0], "{python}")
        self.assertEqual(manifest["command"][2], "--config")

    def test_records_requirements_hash(self):
        manifest = self.manifest()
        self.assertEqual(manifest["requirements"]["path"], "requirements.txt")
        self.assertTrue(manifest["requirements"]["sha256"].startswith("sha256:"))

    def test_requirements_is_null_when_absent(self):
        self.assertIsNone(self.manifest(requirements=None)["requirements"])

    def test_absolute_path_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manifest(files=[str(self.root / "src" / "train.py")])

    def test_parent_escape_is_rejected(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("x\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.manifest(files=["../outside.txt"])

    def test_missing_file_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manifest(files=["src/gone.py"])

    def test_version_is_one_and_platform_is_recorded(self):
        manifest = self.manifest()
        self.assertEqual(manifest["version"], 1)
        self.assertIn("python", manifest)
        self.assertIn("platform", manifest)
        self.assertIn("created_at", manifest)


class TestCreateBundle(BaseCase):
    def test_copies_files_preserving_structure(self):
        create_bundle(self.root, self.out, self.manifest())
        self.assertTrue((self.out / "files" / "src" / "train.py").is_file())
        self.assertTrue((self.out / "files" / "configs" / "a.yaml").is_file())

    def test_writes_a_readable_manifest(self):
        create_bundle(self.root, self.out, self.manifest())
        loaded = load_manifest(self.out)
        self.assertEqual(loaded["version"], 1)
        self.assertEqual(len(loaded["files"]), 2)

    def test_manifest_hashes_match_the_copied_bytes(self):
        create_bundle(self.root, self.out, self.manifest())
        loaded = load_manifest(self.out)
        for item in loaded["files"]:
            self.assertEqual(sha256_of(self.out / "files" / item["path"]), item["sha256"])

    def test_existing_bundle_is_not_overwritten_without_force(self):
        create_bundle(self.root, self.out, self.manifest())
        (self.out / "KEEP").write_text("keep\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            create_bundle(self.root, self.out, self.manifest())
        self.assertTrue((self.out / "KEEP").is_file())

    def test_force_rebuilds_the_bundle(self):
        create_bundle(self.root, self.out, self.manifest())
        (self.out / "KEEP").write_text("keep\n", encoding="utf-8")
        create_bundle(self.root, self.out, self.manifest(), force=True)
        self.assertFalse((self.out / "KEEP").is_file())
        self.assertTrue((self.out / MANIFEST_NAME).is_file())

    def test_missing_manifest_version_is_rejected(self):
        bad = self.manifest()
        del bad["version"]
        with self.assertRaises(ValueError):
            create_bundle(self.root, self.out, bad)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Expected: `ModuleNotFoundError: No module named 'ccfa.repro_package'`。

- [ ] **Step 3: 实现**

创建 `tools/ccfa/repro_package.py`，要点：

- `sha256_of`：与 `provenance` / `run_log` 同语义（`sha256:` 前缀）。
- `build_manifest`：逐个校验入口路径——**先拒绝绝对路径**，再用 `(paper_root / rel).resolve()` 与 `paper_root.resolve()` 做 `relative_to` 包含检查（拒绝 `..` 逃逸）；文件不存在抛 `ValueError`。`files` 按路径排序。`requirements` 同样规则。
- `create_bundle`：校验 `manifest["version"] == 1`（缺失或不等都 `ValueError`）；`out_dir` 已存在且未 `force` → `ValueError`；有 `force` 时先删除输出目录（`shutil.rmtree`）再重建；用 `shutil.copy2` 复制文件；`MANIFEST.json` 用 `cli.save_text_atomically` 原子写入（`ensure_ascii=False`、`indent=2`、`sort_keys=True`、结尾换行）。所有 `OSError` 折成 `ValueError`。
- `load_manifest`：不可读 / 非法 JSON / 非对象 / 缺 `version` 或 `version != 1` → `ValueError`。
- `main`：顶层 `--paper-root`；子命令 `bundle --files A B --command '{python} train.py' --requirements R --notes N --out DIR [--force]`。`--command` 是一个字符串，按 `shlex.split`（POSIX 规则）切成 argv——**这不是 shell 执行**，只是把一行命令安全地切成数组；切分失败 → 2。

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 393 tests`，`OK`（379 + 14）。

判别力检查：临时把 `shutil.copy2` 改成写空文件。预期结果是——`test_copies_files_preserving_structure` **仍然通过**（它只查文件存在性），而 `test_manifest_hashes_match_the_copied_bytes` **必须失败**（复制后的字节与清单哈希对不上）。若后者没有失败，说明该用例判别力不足：实施者应把它改成比对复制后的字节长度或内容，并在报告里说明改了什么、为什么。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/repro_package.py tools/tests/test_repro_package.py
git commit -m "feat: bundle files and command with a hashed manifest"
```

---

## 验收（Part A）

期望：基线 **379** + 本任务新增 **14**（8 条清单 + 6 条 bundle），共 **393** 个测试通过。

- 清单记录文件（路径 + 哈希 + 字节数，按路径排序）、命令（argv 数组，`{python}` 占位）、依赖文件哈希、python 与平台、创建时间、`version: 1`。
- 绝对路径与 `..` 逃逸一律拒绝（bundle 内的路径必须相对 `paper_root`）。
- 不覆盖已有 bundle，`--force` 才重建。
- 读取时校验 `version`（E6 规则）。

已知边界（留给最终全分支评审）：`--command` 用 `shlex.split` 切分，因此命令里带空格或引号的参数需自行转义（比 shell 安全，但比直接传 argv 数组少一点表达力）；`--force` 用 `shutil.rmtree` 整个删除输出目录，若用户把 bundle 建在含有其他内容的目录上会连带删除（Part B 的 verify 不做此操作，风险仅限 bundle 构建）。

## Part B（另立计划）

`verify`：读清单 → 校验 bundle 内文件哈希（不符 → problem `repro-bundle-incomplete`，退 1）→ 建新 venv 并安装声明依赖 → 以 argv 替换 `{python}` 后重跑（非零 → problem `repro-rerun-failed`，退 1）→ 环境建不起来（找不到解释器 / 建 venv 失败 / 超时）→ **工具错误退 2**（Ruling E24）。输出必须显式说明"干净环境"覆盖了什么、没覆盖什么（Ruling E22）。
