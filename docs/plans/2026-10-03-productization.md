# productization 实施计划（商品化收口：可移植、可写回、契约补全）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 关闭 2026-10-03 遗漏审计确认的 P0/P1 缺口：新克隆可重建环境；`ccfa.yaml` 可写回且回退有记录；倒排时间表补全 8 节点并执行 T-30 硬规则；图表溯源补齐四个问题；审稿意见矩阵有 schema 检查器。

**Spec:** `docs/design/2026-10-03-research-workflow-design.md`（§4.3、§4.4、§4.5、§6.3、§12）
**账本：** `docs/sdd/2026-10-03-evidence-tracking-progress.md`（本计划新增裁定 E53–E56）
**基线：** HEAD `dc5b4b0`，**729 tests OK**

## 审计证据（为什么有这些任务）

| 遗漏 | 证据 |
| --- | --- |
| 新克隆不可复现 | `tools/.venv` 被 gitignore；仓库无 requirements/pyproject；README 假设 venv 已存在 |
| `ccfa.yaml` 只能读 | `tools/ccfa/*.py` 无写回代码；§4.3 回退记录无字段、无工具；§12 要求"可读和更新" |
| 倒排只有 3/8 节点 | `milestones.py:18-21` 只有 T-14/T-7/T-3；§4.5 还有 T-90/60/30/21/1；T-30 硬规则无执行点 |
| manifest 只验 2/4 问 | `figure_manifest.py` 只查 `generator_hash` 与 `referenced_in`；`source_run_ids`/`source_data` 完全不校验；缺 generator/hash 的条目静默通过 |
| 审稿矩阵是空壳 | `create.py` 只种 `# 审稿意见矩阵`；§4.4 的 7 列（含承诺风险）无 schema/检查器 |

## Global Constraints

- 仓库根：`<repo-root>`；退出码 0/1/2、stdout JSON / stderr 人读、原子写、UTF-8 无 BOM、ASCII 标识符——沿用九条跨工具规则。
- 一切判别力检查必须**实测**（错误实现下用例真的失败）。
- 新 CLI 模块必须同时更新：`scripts/<name>.ps1` 包装器、根 README 工具表（docs 一致性测试会强制）。
- 写操作必须显式授权语义（`--confirm`），且不得触碰 `ccfa.yaml` 的结论字段。
- 基线 729 tests OK；每个任务完成时全量必须绿。

**环境备注（2026-10-03 实测）**：本机 PATH 上的 `python` 是 **3.13.14**，而仓库 `tools/.venv`
与 README 的基线是 **3.12.14**；从零搭建时应显式使用 3.12（如 `py -3.12 -m venv tools/.venv`）。
17 个 `scripts/*.ps1` 固定调用 `tools/.venv/Scripts/python.exe`，不随 PATH 变化。

---

### Task 1: 依赖清单 + 从零搭建（P0-a/b）——已派

**Files:** Create `tools/requirements.txt`；Modify `README.md`

钉死实测版本（`bibtexparser==2.1.0`、`pylatexenc==2.11`、`pymupdf==1.28.2`、`PyYAML==6.0.3`）；README 增「从零搭建」；用临时全新 venv 只装该清单后跑全量作为证据。commit `chore: pin the toolchain dependencies for a fresh clone`。

### Task 2: `ccfa.yaml` 写回工具与回退记录（E53）

**Files:** Create `tools/ccfa/state.py`、`tools/tests/test_state.py`、`scripts/state.ps1`；Modify `ccfa.yaml.template`、`tools/ccfa/validate.py`、`tools/tests/test_validate.py`、`README.md`、`tools/tests/test_docs_consistency.py`（工具表口径自动跟随，如需）

**Interfaces**
- `set_stage(paper_root, *, to, reason, confirm) -> dict`：非空 `reason`、`confirm is True`、`to ∈ stages_for(mode)` 且不等于当前 stage；写回 `stage.current`、`stage.gate = gate_for(mode, to).id`、`stage.updated_at`（本地日期），并向 `stage.history` 追加 `{"from","to","at","reason","kind":"advance"}`。
- `rollback(paper_root, *, to, reason, confirm, void_artifacts=None) -> dict`：`to` 必须在当前 stage 之前；`reason` 必填（一条具体事实）；追加 `{"from","to","at","reason","kind":"rollback","void_artifacts":[...]}`；不猜测产物有效性，`void_artifacts` 由调用者显式给。
- `main`：`set-stage` / `rollback` 两个子命令；`--confirm` 缺失 → 拒绝（`ValueError` → 2，消息说明需要明确授权）。
- 写盘走 `cli.save_text_atomically`；YAML 用 `allow_unicode=True`、`sort_keys=False`、保持顶层键顺序。

**判定表**

| 条件 | 结果 |
| --- | --- |
| 缺 `--confirm` | 拒绝，退 2，且文件字节不变 |
| `reason` 为空 | 拒绝，退 2 |
| `to` 不在 `stages_for(mode)` | 退 2 |
| `set-stage` 的 `to` 等于当前 | 退 2（无操作不是"成功"） |
| `rollback` 的 `to` 不在当前之前 | 退 2 |
| 正常 set-stage / rollback | 0；`stage.history` 追加一条；`gate` 与 stages.py 一致 |
| `ccfa.yaml` 缺 `stage.history`（旧文件） | 视为 `[]` 并补写；validate 对合法 history 不报 |
| history 条目缺字段/kind 非法 | validate 报 problem；`state.py` 读到坏 history 退 2（不静默重写） |

- [ ] 测试（约 14 条）：授权门、空 reason、stage 合法性、等值拒绝、回退方向、history 追加与顺序、gate 一致性、旧文件兼容、坏 history 拒写、原子写无 `.tmp`、只读性（被拒时字节不变）、CLI 0/1/2。
- [ ] 判别力实测：删掉 `--confirm` 检查（对应用例失败）；把回退方向检查改成任意值（方向用例失败）。
- [ ] commit `feat: write paper stage transitions with an audit trail`

### Task 3: 倒排补全 8 节点 + T-30 硬规则（E54）

**Files:** Modify `tools/ccfa/milestones.py`、`tools/tests/test_milestones.py`

**Interfaces**
- `checkpoints` 增加 `T-90 / T-60 / T-30 / T-21 / T-1`；映射：T-90→experiment-design、T-60→experiments-running、T-30→results-ready、T-21→writing、T-14/T-7→internal-review、T-3/T-1→submission-check。
- `due_report` 的 `problems` 增加 T-30 规则检查：`mode=countdown` 且 `today > T-30` 时，扫描 `<paper-root>/experiments/log/*.json`，任何记录的开始时间晚于 T-30 → problem `t30-new-experiment`（消息含 run id 与日期）。
- run-log 记录不可读/缺时间字段 → 跳过该条并计入 advisory（规则 5：一条坏记录不打断整轮）。

**判定表**

| 条件 | 结果 |
| --- | --- |
| 8 个节点各自当天命中 | `due` 列出该节点 + 目标 stage/gate 缺口（1） |
| T-30 之后有新的 run-log 记录 | problem `t30-new-experiment`（1） |
| T-30 之后只有更早的记录 / 无记录 | 无该 problem |
| run-log 单条损坏 | advisory，不打断，其余照查 |
| 无 deadline | 仍为 sequential、`due=[]`（不变） |

- [ ] 测试（约 12 条：8 节点命中、非命中日、T-30 命中/未命中、坏记录、CLI 0/1/2）。
- [ ] 判别力实测：把节点表改回 3 个（新节点用例失败）；去掉 T-30 扫描（规则用例失败）。
- [ ] commit `feat: cover the full submission countdown and the T-30 freeze`

### Task 4: manifest 溯源补全（E55）

**Files:** Modify `tools/ccfa/figure_manifest.py`、`tools/tests/test_figure_manifest.py`（文件名以实际为准）、必要时 `tools/tests/test_final_check.py`

**规则（problem，除非注明）**

| 条件 | code |
| --- | --- |
| 缺 `generator` 或 `generator_hash` | `figure-provenance-missing`（硬规则 1：交付图必须脚本生成） |
| `source_run_ids` 缺/空/非列表 | `figure-provenance-missing` |
| `source_run_ids` 中某个 id 在 `experiments/log/<id>.json` 不存在 | `figure-source-run` |
| `source_data` 缺/为空/文件不存在（相对 paper root） | `figure-source-data` |
| `manual_edit: true` 但缺 `manual_edit_note` | `figure-manual-edit` |
| `referenced_in` 为空 | 仍是 advisory `unreferenced-figure`（§6.6 口径不变） |

**兼容**：历史 manifest 缺新必填字段 → 报 problem（这正是"补齐"的目的），但每条 problem 的消息要指出该补什么；`figure_manifest` 的 `check_manifest` 需接收 `paper_root` 下 `experiments/log` 的路径约定（已有 `paper_root` 参数）。

- [ ] 测试（约 10 条）：缺 generator/hash、缺 run_ids、未知 run id、缺 source_data、文件不存在、manual_edit 无 note、全部齐全时干净、advisory 不变、既有 6 个 code 不回归。
- [ ] 判别力实测：把 generator 必填改回可选（对应用例失败）。
- [ ] commit `feat: require figure provenance for every delivered figure`

### Task 5: 审稿意见矩阵检查器（E56）

**Files:** Create `tools/ccfa/revision_ledger.py`、`tools/tests/test_revision_ledger.py`、`scripts/revision-ledger.ps1`；Modify `README.md`

**Interfaces**：`check_ledger(path) -> list[Problem]`；`main` 只读；退出码 0/1/2。

**规则（§4.4 七列）**

| 条件 | code |
| --- | --- |
| 表头缺列 / 列序不符 | `ledger-header`（1） |
| 行缺单元格 | `ledger-row-shape`（1） |
| Concern ID 重复 | `ledger-duplicate-id`（1） |
| 类型不在 {证据不足, 表述不清, 需要新实验, 误解} | `ledger-invalid-type`（1） |
| 状态不在 {待处理, 已处理, 不采纳} | `ledger-invalid-status`（1） |
| 状态=不采纳但理由为空 | `ledger-missing-reason`（1） |
| 承诺风险不在 {是, 否} | `ledger-invalid-risk`（1） |
| 承诺风险=是 且"需要的新证据"为空或"无" | `ledger-risk-without-evidence`（1） |

problem 必须带真实行号（markdown 有行号，不再用 `None`）。

- [ ] 测试（约 10 条）：表头、行形状、重复 id、两个枚举、不采纳理由、承诺风险一致性、全合法文件退 0、CLI 0/1/2、只读。
- [ ] 判别力实测：删掉风险一致性检查（对应用例失败）。
- [ ] commit `feat: check the revision ledger against its column contract`

### Task 6: 收口（e2e + 文档 + 终审）

**Files:** Create `tools/tests/test_productization_e2e.py`；Modify `README.md`（工具表新增 state/revision-ledger）

- e2e：派生项目 → `state set-stage`（0，history 一条）→ `validate`（0）→ `rollback`（0，history 两条）→ milestones 8 节点抽查 → manifest 全字段校验 → revision-ledger 合法文件退 0、坏文件退 1。
- [ ] 判别力：伪造一条坏 history 让 validate 报 problem。
- [ ] commit `test: add productization integration regression`
- [ ] 终审（base `dc5b4b0`，新评审者）；README/docs 同步；账本更新 E53–E56 与结项。

## 完成定义（DoD）

- 全量测试 ≥ 780 且全绿；上述 6 条判别力均有实测失败记录。
- 全新 venv（只装 `tools/requirements.txt`）跑通全量的证据入库。
- README 工具表覆盖新增 CLI；每个新模块都有 `.ps1` 包装器并被 `test_scripts.py` 的清单断言覆盖。
- 账本（`docs/sdd/...`）记录 E53–E56 的理由与代价。
