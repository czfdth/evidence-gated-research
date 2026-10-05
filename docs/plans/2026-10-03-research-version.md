# research-version 实施计划（git 薄封装）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成 `research-version`：用 **git 标签**给论文版本编号，提供 `list` / `snapshot` / `diff` 三个子命令——保留"任意两版真 diff"的能力，但不另建版本库。

**Why a thin wrapper (Ruling E4/E26):** 论文库本身已是 git 仓库，独立快照库会制造**两个版本真相**——同一份稿子的"第几版"到底以哪个为准。参考实现的动机（替代手工 `mkdir/cp`、`git mv` 在空目录上炸）在 git 工作流里并不成立。所以本工具**不存任何自己的副本**，只把 git 标签变成好用的版本号，并用标注消息把"打这个标签时的树是否干净"记下来。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v6：§6.1 的分期说明、§6.1.1）
**账本：** `<repo-root>/.superpowers/sdd/2026-10-03-evidence-tracking/progress.md`（Ruling E4、E26）

## Global Constraints

- 仓库根：`<repo-root>`
- 退出码：`0` 正常；`1` **本工具不使用**（版本差异不是"问题"，见下）；`2` 工具自身出错（git 不可用 / 非 git 仓库 / 标签不存在 / 脏树未加 `--allow-dirty`）。
- **`diff` 的退出码例外（必须写进 `--help`）**：即使两个版本有差异，`diff` 也退 **0**——差异是这个子命令的**产物**，不是问题。这与 Unix `diff` 的约定不同（那里"有差异"= 1），因为我们把 `1` 保留给"检查发现了问题"。
- 标签命名：`paper-v<N>`，N 为现有同类标签的最大编号 + 1。
- **脏树默认拒绝**：工作树有未提交改动时 `snapshot` 退 2，除非显式 `--allow-dirty`；允许时在标签消息里记 `dirty=true`（脏树快照无法仅凭 commit 复现，这个事实必须留在标签里）。
- 本工具**不写任何自己的文件**，只调 git；不引入第二份真相。
- UTF-8 无 BOM；ASCII 标识符与注释；中文只在面向用户的消息里。
- 基线：**432 tests OK**，HEAD = `3c8039a`，工作树干净。
- 测试命令：`& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
- 既有接口：`ccfa.cli.Problem` / `emit` / `tool_error`。

---

### Task 1: git 薄封装与三个子命令

**Files:**
- Create: `tools/ccfa/research_version.py`
- Create: `tools/tests/test_research_version.py`

**Interfaces:**
- Produces:
  - `GitRunner = Callable[[list[str], Path], "tuple[int, str]"]`（注入点；默认走 `subprocess.run`，**`shell=False`**）
  - `git_output(args: list[str], repo: Path, runner: GitRunner | None = None) -> str`（非零退出 → `ValueError`）
  - `list_versions(repo: Path, runner=None) -> list[str]`（按 N 数值升序返回 `paper-v*`）
  - `next_version(repo: Path, runner=None) -> str`
  - `working_tree_dirty(repo: Path, runner=None) -> bool`（`git status --porcelain` 是否非空）
  - `snapshot(repo: Path, *, label: str | None = None, allow_dirty: bool = False, runner=None) -> tuple[str, str]`（返回 `(tag, commit)`）
  - `diff_versions(repo: Path, a: str, b: str, paths: list[str] | None = None, runner=None) -> str`
  - `main(argv: list[str]) -> int`

**要点**

- `git_output` 统一把 `OSError`（没装 git）与非零退出折成 `ValueError` → 退出 2（已固化的跨工具规则）。
- `snapshot` 先查脏树：脏且未 `allow_dirty` → `ValueError`（消息说明"脏树快照无法仅凭 commit 复现"）；允许时标签消息里带 `dirty=true`，干净时带 `dirty=false`。
- 标签用 **annotated tag**（`git tag -a <tag> -m <message>`），因为轻量标签没有消息，装不下 `dirty` 与 `label`。
- `label` 给了就写进标签消息，作为人读备注；它**不参与**标签命名（命名始终是 `paper-v<N>`，保证顺序可数）。
- `diff_versions` 调 `git diff <a> <b> [-- <paths>]`；`a`/`b` 不存在时 git 自己会非零退出 → `ValueError` → 2。

- [ ] **Step 1: 写失败测试**

`tools/tests/test_research_version.py`，约 11 条，全部用**注入的** `runner`（不碰真 git），另加一条真实 git 集成用例：

注入式用例的 `runner` 按 argv 分派并记录调用，例如 `["tag","-l","paper-v*"]` 返回已有标签、`["status","--porcelain"]` 返回干净或脏、`["rev-parse","HEAD"]` 返回一个假 commit、`["diff",...]` 返回一段假 diff。

必须覆盖：

1. `list_versions` 把 `paper-v2`、`paper-v10` 按**数值**排序（字符串排序会把 v10 排在 v2 前，这是本条用例的判别点）；
2. 空标签集时 `next_version` 得 `paper-v1`；
3. 已有 `paper-v3` 时 `next_version` 得 `paper-v4`；
4. `working_tree_dirty` 对空与非空 `--porcelain` 输出分别判假/真；
5. 干净树上 `snapshot` 打标签成功，标签消息含 `dirty=false`，且返回 `(tag, commit)`；
6. **脏树上 `snapshot` 未加 `--allow-dirty` 抛 `ValueError`**，且**没有执行任何 `git tag`**（用 runner 记录断言）；
7. 脏树 + `--allow-dirty` 时成功，标签消息含 `dirty=true`；
8. `label` 被写进标签消息且**不影响**标签名；
9. `diff_versions` 把路径参数放在 `--` 之后（用 runner 记录 argv 断言）；
10. `git_output` 在 runner 返回非零时抛 `ValueError`；
11. `runner` 抛 `OSError`（没装 git）时也折成 `ValueError`。

外加一条**真实 git 集成用例**（`git init` 一个临时仓库，配置 `user.email`/`user.name`，提交一个文件，然后走真实 runner 跑 `snapshot` → 再改文件 → 脏树上再 `snapshot` 必须被拒 → `--allow-dirty` 通过 → `diff` 两个标签能拿到非空 diff）。这条是本任务唯一证明"默认 runner 真的能用"的证据，价值等同于 latex-check 的真编译与 repro-package 的真 venv。

- [ ] **Step 2: 运行测试确认失败**（Expected: `ModuleNotFoundError: No module named 'ccfa.research_version'`）

- [ ] **Step 3: 实现**（按上文要点；`main` 的顶层参数是 `--repo`，三个子命令 `list` / `snapshot [--label L] [--allow-dirty]` / `diff A B [--path P]...`）

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 444 tests`，`OK`（432 + 12）。

判别力检查：把 `list_versions` 的排序从"按 N 数值"改成"按字符串"，第 1 条用例（v2 vs v10）必须失败；恢复。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/research_version.py tools/tests/test_research_version.py
git commit -m "feat: number paper versions with annotated git tags"
```

---

## 验收

期望：基线 **432** + 本计划新增 **12**（11 注入 + 1 真实 git），共 **444** 个测试通过。

逐条核对：标签命名 `paper-v<N>` 且按数值排序；**脏树默认拒绝**，允许时 `dirty=true` 进标签消息（E26 的核心）；`diff` 用真实 `git diff`、路径参数在 `--` 之后；**本工具不写自己的存储**（不引入第二份版本真相）；`diff` 有差异也退 0（具名例外，须写进 `--help`）；git 不可用或非仓库退 2。

已知边界：标签落在**当前仓库**上——若论文库不是 git 仓库（或用户从非仓库目录调用），本工具不可用；这是有意的，离开版本控制谈快照本就没有意义。`snapshot` 不推送标签（推送是共享操作，按项目惯例必须人工决定）。**annotated tag 需要 git 身份**（`user.name` / `user.email`）：未配置时 git 会报错，本工具折成 `ValueError` → 退 2，消息里带上 git 的原文（真实 git 集成用例必须在临时仓库里自己配好这两项，否则会因环境而失败——这是"测试依赖全局状态"的典型陷阱，需在用例里显式设置）。

## 后续

知识层（FTS5 trigram 索引 + 记忆文件，含反重复的 `reopen_if`）→ 自动化与跨模型评审 → 模板库与派生流程（强制前置：先评估 `bensz-paper` / `bensz-nsfc`）。
