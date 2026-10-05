# friction-log 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成 `friction-log`：把"跑这套工作流时遇到的摩擦"（工具缺陷、技能指令缺口、环境限制、绕路）记成结构化条目，支持按条件筛选、导出人读文档，以及**跨论文聚合**——让重复出现的模式浮出来，而不是埋在各自没人重读的文件里。

**Architecture:** 单工具、四个子命令，store 为 JSON。每篇论文一个 store；`aggregate` 以 `PATH=LABEL` 读多个 store 合并成一份总账。写路径走共享的原子写与不覆盖契约；**读取时重新校验枚举**（E20 的教训：写入时校验不构成读取时的信任）。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v6：§6.1、§6.1.1、§10）
**账本：** `<repo-root>/.superpowers/sdd/2026-10-03-evidence-tracking/progress.md`（Ruling E25）

## 参考实现与取舍

`research-suite/tools/friction-log/friction_log.py`（MIT）。**吸收**：`add` / `list` / `export` / `aggregate` 的四段式，以及 `aggregate` 以 `PATH=LABEL` 合并多 store 的设计——它的文档把理由写得很准："跨若干不相关领域重复出现的模式，才能被聚合真正浮出来，而不是埋在各个没人会一起重读的文件里。"
**偏离**：它把 store 的读写放松在"写时校验"上；我们按 E25 要求**读取时也重新校验**枚举，并且聚合输出**不覆盖**已有文件（除非 `--force`）。

## Global Constraints

- 仓库根：`<repo-root>`
- 退出码：`0` 通过，`1` 发现问题（store 里存在非法条目 / 聚合输入不可读），`2` 工具自身出错。
- 写盘契约：原子写、不覆盖（`--force` 才覆盖）、`OSError` → `ValueError` → 2。
- store 的 `version` 必须是 1；`category` 限 `tool-bug` / `skill-gap` / `environment` / `other`；`severity` 限 `low` / `medium` / `high`（**读取时重校验**）。
- UTF-8 无 BOM；ASCII 标识符与注释；中文只在面向用户的消息里。
- 基线：**411 tests OK**，HEAD = `e2783b6`，工作树干净。
- 测试命令：`& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
- 既有接口：`ccfa.cli.Problem` / `emit` / `tool_error` / `save_text_atomically`。

---

### Task 1: store 与 `add` / `list` / `check`

**Files:**
- Create: `tools/ccfa/friction_log.py`
- Create: `tools/tests/test_friction_log.py`

**Interfaces:**
- Produces:
  - `VALID_CATEGORIES`、`VALID_SEVERITIES`（元组常量）
  - `load_store(path: Path) -> dict`（缺失文件 → 空 store；不可读 / 非对象 / 缺 `version` / `version != 1` / `entries` 非列表 → `ValueError`）
  - `save_store(path: Path, store: dict) -> None`（原子写）
  - `add_entry(store_path, *, stage, component, category, severity, description, workaround=None) -> dict`
  - `check_store(store_path: Path) -> list[Problem]`（只读；重校验每条目的枚举与必填字段）
  - `filter_entries(store: dict, *, category=None, component=None, severity=None) -> list[dict]`
  - `main(argv: list[str]) -> int`

**条目形状**（单行示意，实际写盘为缩进 JSON）：

`{"id": 3, "created_at": "2026-10-03T14:25:30Z", "stage": "writing", "component": "citation-manager", "category": "tool-bug", "severity": "high", "description": "…", "workaround": null}`

`id` 为自增整数（`max(已有 id) + 1`）；`workaround` 未给时为 `null`。

**判定表**

| 条件 | 结果 |
| --- | --- |
| 条目缺 `description` 或为空 | problem `friction-missing-description`（1） |
| 条目 `category` / `severity` 不在枚举内 | problem `friction-invalid-enum`（1） |
| 条目缺 `component` 或 `stage` | problem `friction-missing-field`（1） |
| store 的 `version` 非法 | `ValueError` → 2 |

- [ ] **Step 1: 写失败测试**（`tools/tests/test_friction_log.py`，约 12 条）

必须覆盖：空 store 的默认形状；`add` 后 `id` 自增且条目字段完整；非法 `category` / `severity` 在 `add` 时被拒（`ValueError`）；**手改 store 塞入非法枚举后 `check_store` 必须报出**（读取时重校验，E25 的核心）；缺 `description` 空串被报；`version != 1` 抛 `ValueError`；`save_store` 原子且不残留 `.tmp`；`filter_entries` 按 category / component / severity 各筛一次；`check_store` 只读（比对字节）。

- [ ] **Step 2: 运行测试确认失败**（Expected: `ModuleNotFoundError: No module named 'ccfa.friction_log'`）

- [ ] **Step 3: 实现**

要点与既有工具一致：`load_store` 缺失文件返回 `{"version": 1, "entries": []}`；`save_store` 走 `cli.save_text_atomically`（`ensure_ascii=False`、`indent=2`、`sort_keys=True`、结尾换行）；`add_entry` 先校验枚举与必填，再 `load` → 追加 → `save`；`check_store` 逐条重校验并把全部问题报全（不遇第一条就返回）。

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 423 tests`，`OK`（411 + 12）。

判别力检查：把 `check_store` 里的枚举重校验删掉，"手改 store 塞入非法枚举"那条用例必须失败；恢复。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/friction_log.py tools/tests/test_friction_log.py
git commit -m "feat: log workflow friction with read-time enum validation"
```

---

### Task 2: `export` 与 `aggregate`

**Files:**
- Modify: `tools/ccfa/friction_log.py`
- Modify: `tools/tests/test_friction_log.py`

**Interfaces:**
- `render_markdown(store: dict) -> str`（表格：id / 日期 / stage / component / category / severity / 描述 / 绕路）
- `aggregate_stores(inputs: list[tuple[Path, str]]) -> dict`（把多个 store 的条目合并，给每条加 `source` 标签；`id` 重新编号）
- `write_text_output(path: Path, text: str, force: bool = False) -> None`（原子写；已存在且未 `force` → `ValueError`）
- `main` 增加 `export --format markdown|json [--out PATH] [--force]` 与 `aggregate PATH=LABEL ... --out PATH [--force]`

- [ ] **Step 1: 写失败测试**（约 8 条）

`render_markdown` 含表头与每条一行；`export` 不带 `--out` 时只打 stdout（`--format markdown` 打 markdown、`--format json` 打 JSON）；`aggregate` 合并两个 store 后条目数为两者之和、每条带正确的 `source`、`id` 重新连续编号；`aggregate --out` 指向已存在文件且未 `--force` → `ValueError`；`aggregate` 读入含非法条目的 store 时**报 problem 并继续**（不打断整轮，规则 5）。

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现**（`aggregate` 的输出 store 也带 `version: 1`；`source` 标签来自 `PATH=LABEL` 的 LABEL）

**一处必须写明的语义**：`aggregate` 遇到输入里的非法条目时，**仍然写出合并文件**（把两条合法条目合起来这件事本身是成功的），但把非法条目录成 problem，因此退出码是 **1**。理由：聚合的产物是"记录"，而记录里的坏条目是**事实**，不该因为要"干净"就把它丢掉——丢掉正好违背这一层"让重复模式浮出来"的目的。坏条目的原始内容原样保留在输出里，问题列表指出它们。

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 431 tests`，`OK`（423 + 8）。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/friction_log.py tools/tests/test_friction_log.py
git commit -m "feat: export and aggregate friction logs across papers"
```

---

## 验收

期望：基线 **411** + 本计划新增 **20**（12 + 8），共 **431** 个测试通过。

逐条核对：store 的 `version` 校验与枚举**读取时重校验**（E25）；`aggregate` 跨论文合并且带来源标签；聚合输出不覆盖；`export` 不带 `--out` 时打文档而非 JSON（沿用 `provenance export` 的具名偏离，`check` 走 JSON）；单条非法不得打断聚合（规则 5）。

已知边界：`aggregate` 不做去重（同一根因在两个项目里各记一条就是两条——这是有意的，重复次数本身是信号）；`id` 在聚合后重新编号，因此聚合结果里的 `id` 与原 store 的 `id` 不再对应（用 `source` 标签区分来源）。

## 后续

`research-version`（E26 的 git 薄封装）→ 知识层（FTS5 + 记忆）→ 自动化与跨模型评审 → 模板库与派生流程。
