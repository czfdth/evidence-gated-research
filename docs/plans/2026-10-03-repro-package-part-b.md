# repro-package 实施计划 — Part B（verify：真的重跑一遍）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成 `repro-package verify`：读清单、核对 bundle 内每个文件的哈希、建一个**新 venv**、按 argv 重跑命令，并把三类失败分开报。

**Architecture:** 沿用 Part A 的单工具。`verify` 只读 bundle（不修改它），副作用全部发生在系统临时目录里的新 venv 中；venv 创建与命令执行都做成可注入的（`venv_factory` / `runner`），使绝大部分测试不建真实 venv、不联网。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v6：§6.1、§12）
**Part A：** `<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-repro-package.md`（已完成，HEAD `9b6b0e2`，394 tests）
**账本：** `<repo-root>/.superpowers/sdd/2026-10-03-evidence-tracking/progress.md`（Ruling E22–E24、E27）

## 判定表（本任务的规格）

| 情形 | code / 退出码 |
| --- | --- |
| bundle 内某文件缺失或哈希与清单不符 | problem `repro-bundle-incomplete`（**1**） |
| 声明的依赖安装失败 | problem `repro-install-failed`（**1**），detail 里附 pip 输出尾部 |
| 重跑非零退出 | problem `repro-rerun-failed`（**1**），detail 里附退出码与输出尾部 |
| 重跑超时 | problem `repro-rerun-failed`（**1**），detail 标明超时 |
| 清单不可读 / `version` 非法 | **工具错误（2）** |
| 建 venv 失败（找不到解释器 / 创建失败） | **工具错误（2）** |
| 全部通过 | 0 |

**"环境建不起来"（2）与"这个包复现不了"（1）必须分开**（E24）：前者是机器的问题，后者是包的问题，混在一起会让"验证没跑成"看起来像"验证发现了问题"。

## Ruling E22 的落实（必须出现在输出里）

每次 `verify` 的报告（JSON 里的 advisory 与人读摘要）都要显式写明本次"干净环境"覆盖了什么、没覆盖什么：

> 本次验证使用一个只安装了 bundle 声明依赖的新 venv；**不**提供容器级隔离——系统库、网络、PATH 上已存在的非 Python 工具均未隔离。

Ruling: 这句话以固定文案出现在 `verify` 的 advisory（code `repro-scope`）里，**无论通过与否**。
理由: 把"我看了一遍包"说成"我验证了可复现"是本层最容易犯的谎；边界必须每次可见，而不只躺在文档里。

## Global Constraints

- 仓库根：`<repo-root>`
- `verify` **只读 bundle**；临时 venv 建在系统临时目录并在结束时清理（`--keep` 时保留并打印路径）。
- 退出码 0/1/2 按上表；`OSError` 一律折成 `ValueError`（已固化的跨工具规则）。
- **命令以 argv 执行，绝不经过 shell**（E23）；`{python}` 只替换 `argv[0]`。
- UTF-8 无 BOM；ASCII 标识符与注释；中文只在面向用户的消息里。
- 基线：**394 tests OK**，HEAD = `9b6b0e2`，工作树干净。
- 测试命令：`& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`

---

### Task 2: verify

**Files:**
- Modify: `tools/ccfa/repro_package.py`
- Modify: `tools/tests/test_repro_package.py`

**Interfaces:**
- Produces:
  - `verify_bundle(bundle_dir: Path, *, timeout: float = 600.0, keep: bool = False, venv_factory=None, runner=None) -> tuple[list[Problem], list[Problem]]`
  - `main` 增加子命令 `verify --bundle DIR [--timeout N] [--keep]`
- `venv_factory(path: Path) -> Path`：默认用 stdlib `venv` 建环境并返回其 python 可执行文件路径；失败抛 `ToolEnvironmentError`。
- `runner(argv: list[str], cwd: Path, timeout: float) -> tuple[int, str]`：默认真实 `subprocess.run`；**`shell=False`**。

- [ ] **Step 1: 写失败测试**

在 `tools/tests/test_repro_package.py` 中追加（import 加 `verify_bundle`、`ToolEnvironmentError`）：

```python
class TestVerifyBundle(BaseCase):
    def _bundle(self):
        create_bundle(self.root, self.out, self.manifest())
        return self.out

    def _venv(self, path):
        path.mkdir(parents=True, exist_ok=True)
        return path / "python"

    def _codes(self, items):
        return sorted(i.code for i in items)

    def test_a_consistent_bundle_passes_and_reports_scope(self):
        bundle = self._bundle()
        problems, advisories = verify_bundle(
            bundle,
            venv_factory=self._venv,
            runner=lambda argv, cwd, timeout: (0, "ok\n"),
        )
        self.assertEqual(problems, [])
        self.assertEqual(self._codes(advisories), ["repro-scope"])

    def test_tampered_file_is_reported_as_incomplete(self):
        bundle = self._bundle()
        (bundle / "files" / "src" / "train.py").write_text("tampered\n", encoding="utf-8")
        problems, _ = verify_bundle(
            bundle, venv_factory=self._venv, runner=lambda a, c, t: (0, "")
        )
        self.assertEqual(self._codes(problems), ["repro-bundle-incomplete"])

    def test_nonzero_rerun_is_reported(self):
        bundle = self._bundle()
        problems, _ = verify_bundle(
            bundle, venv_factory=self._venv, runner=lambda a, c, t: (3, "boom\n")
        )
        self.assertEqual(self._codes(problems), ["repro-rerun-failed"])

    def test_timeout_is_reported_as_rerun_failed(self):
        bundle = self._bundle()

        def runner(argv, cwd, timeout):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)

        problems, _ = verify_bundle(bundle, venv_factory=self._venv, runner=runner)
        self.assertEqual(self._codes(problems), ["repro-rerun-failed"])
        self.assertIn("超时", problems[0].message)

    def test_venv_creation_failure_is_a_tool_error(self):
        bundle = self._bundle()

        def broken_venv(path):
            raise ToolEnvironmentError("找不到解释器")

        with self.assertRaises(ToolEnvironmentError):
            verify_bundle(bundle, venv_factory=broken_venv, runner=lambda a, c, t: (0, ""))

    def test_command_is_passed_as_argv_without_a_shell(self):
        bundle = self._bundle()
        seen = {}

        def runner(argv, cwd, timeout):
            seen["argv"] = list(argv)
            return 0, ""

        verify_bundle(bundle, venv_factory=self._venv, runner=runner)
        self.assertIsInstance(seen["argv"], list)
        self.assertTrue(seen["argv"][0].endswith("python"))
        self.assertNotIn("{python}", seen["argv"])

    def test_verify_does_not_modify_the_bundle(self):
        bundle = self._bundle()
        before = (bundle / "MANIFEST.json").read_bytes()
        verify_bundle(bundle, venv_factory=self._venv, runner=lambda a, c, t: (0, ""))
        self.assertEqual((bundle / "MANIFEST.json").read_bytes(), before)
```

（测试文件顶部补 `import subprocess` 与 `from ccfa.cli import ToolEnvironmentError`。）

- [ ] **Step 2: 运行测试确认失败**

Expected: `ImportError: cannot import name 'verify_bundle'`。

- [ ] **Step 3: 实现**

在 `repro_package.py` 中追加，要点：

1. `load_manifest(bundle_dir)`（Part A 已有，含 `version` 校验；失败抛 `ValueError` → 2）。
2. **哈希核对**：对清单里每个 `files` 条目，比对 `bundle_dir / "files" / path` 的实际 `sha256_of` 与记录值；缺失或不符都进 `repro-bundle-incomplete` 的问题列表（**逐条比完再决定**——一次报全，不要遇到第一条就返回）。
   **若存在任何哈希问题，就不进入第 3–5 步**：跑一个已损坏的包，正是本工具要拦下的事。此时返回的问题列表只含哈希问题，advisory 仍含 `repro-scope`（说明本次验证到哪一步为止）。
3. **建 venv**：在 `tempfile.mkdtemp()` 下建；默认 `venv_factory` 用 `venv.EnvBuilder(with_pip=True)` 并把 `bin/python`（Windows 上 `Scripts/python.exe`）返回。失败抛 `ToolEnvironmentError`。结束（或 `--keep` 时跳过）清理临时目录。
4. **装依赖**：清单 `requirements` 非空时，用 venv 的 python 跑 `-m pip install -r <bundle>/files/<requirements 路径>`。非零 → problem `repro-install-failed`（1），detail 附 pip 输出尾部（末 800 字符）。
5. **重跑**：`argv = [venv_python if a == "{python}" else a for a in manifest["command"]]`；`runner(argv, cwd=bundle_dir / "files", timeout=timeout)`。`TimeoutExpired` → `repro-rerun-failed`（detail 含"超时"）；非零 → `repro-rerun-failed`（detail 含退出码与输出尾部）。
6. **无论结果**，advisory 里加一条 `repro-scope`，文案按上文固定。
7. 全过程 `OSError` → `ValueError`。

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 401 tests`，`OK`（394 + 7）。

判别力检查：把"哈希核对"那一步删掉，`test_tampered_file_is_reported_as_incomplete` 必须失败；恢复。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/repro_package.py tools/tests/test_repro_package.py
git commit -m "feat: verify a bundle by re-running it in a fresh environment"
```

---

### Task 3: 端到端 + 一次真实 venv 冒烟

**Files:**
- Create: `tools/tests/test_repro_package_e2e.py`

**行为规格**

| 场景 | 期望 |
| --- | --- |
| `bundle` 一个打印 `ok` 的脚本后 `verify` | `0`，advisory 含 `repro-scope` |
| 篡改 bundle 内文件后 `verify` | `1`，`repro-bundle-incomplete` |
| `verify` 指向不存在的 bundle | `2`，stdout 为空 |
| 手工把清单 `version` 改成 2 后 `verify` | `2`，stdout 为空 |

- [ ] **Step 1: 写 e2e 测试**（四条，用 `subprocess.run(..., encoding="utf-8")`）

**另外做一次真实冒烟（不进自动化套件，写进报告）**：用一个**不带依赖**的 bundle（脚本只 `print`，`requirements` 为 `null`）跑真实的 `verify`，确认它真的建出 venv 并执行——本地建 venv 不需要网络，因此这一步可离线完成。把命令与实际输出写进报告。

- [ ] **Step 2: 运行测试确认通过**

Expected: `Ran 405 tests`，`OK`（401 + 4）。

- [ ] **Step 3: 提交**

```powershell
git add tools/tests/test_repro_package_e2e.py
git commit -m "test: add repro-package end-to-end regression"
```

---

## 验收

期望：基线 **394** + 本计划新增 **11**（7 + 4），共 **405** 个测试通过。

逐条核对：三类失败分流（1 / 1 / 2）与 E24 一致；`repro-scope` 在通过与失败时都出现（E22）；命令以 argv 执行、`{python}` 只替换 `argv[0]`、无 shell（E23）；`verify` 不修改 bundle；真实 venv 冒烟证明"新环境里真的能跑起来"这件事有证据，而不只是注入了假 factory。

已知边界：`--keep` 保留的临时 venv 需用户自行清理；`pip install` 的失败不区分"依赖无法解析"与"无网络"（都归 `repro-install-failed`，detail 里附原始输出供人判断）；只验证 Python 侧的复现（非 Python 工具的依赖本工具看不到，报告里应说明）。

## 后续

repro-package 完成后：`friction-log`（store 契约 + 枚举重校验 + `aggregate` 跨论文合并）→ `research-version`（E26 的 git 薄封装）→ 知识层 → 自动化与跨模型评审 → 模板库与派生流程。
