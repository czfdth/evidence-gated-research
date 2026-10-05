# 治理、统计与新颖性 gate 实施计划（2026-10-04）

**Goal:** 关闭审计总结里剩余的高严重度缺口：治理与伦理检查空白、统计设计门槛薄、
新颖性判据只有三篇最近邻。三件事都无法由脚本判断真伪，但都可以要求使用者把
判断写进结构化台账，并在 stage gate 上强制检查。

**裁定：**

- **E75 `novelty`**：`data/novelty-audit.yaml` 记录检索数据库（≥2，去重）、查询、
  检索日期与 cutoff、≥3 篇最近邻（id 必须存在于 `manuscript/references.bib`，标题去重）、
  每篇的 overlap/difference、以及每篇覆盖的 claim id；claim id 必须属于声明的 claims，
  claims 去重。每个声明 claim 必须被至少一个近邻差异覆盖；禁止“没人做过 /
  no one has done / first to”式未支撑表述。脚本不证明新颖性，只强制检索与差异留痕。
- **E76 `statistics`**：`data/statistics-plan.yaml` 记录 alpha、multiple_comparison、
  每个 claim 的 endpoint/test/effect_size/target_power/sample_size/seeds/stopping_rule/
  missing_data。多个 claim 时 `multiple_comparison` 不能为 none；缺失功效、样本量、
  种子或停止规则都是 problem。脚本不判断检验是否合适，只强制设计先冻结。
- **E77 `governance`**：`data/governance.yaml` 记录作者与贡献角色、corresponding、
  逐作者利益冲突声明、伦理（human_subjects / IRB / informed consent / data license）、
  AI 使用披露、查重工具与日期、双用途复核与负责任披露联系人。缺失、未知作者、
  human_subjects=true 但缺 IRB/consent、AI/查重/双用途未完成都是 problem。
- **E78 `repro-env`**：`data/repro-environment.yaml` 记录 Python、包管理器、
  requirements、lockfile 与 sha256、系统工具的名称/版本/命令/证据文件。lockfile
  哈希漂移、requirements/证据缺失、证据中找不到版本、无效容器 digest 都是 problem。

**Files:** 新增 `tools/ccfa/ledger.py`、`tools/ccfa/novelty.py`、
`tools/ccfa/stats_plan.py`、`tools/ccfa/governance.py`、三个 `scripts/*.ps1`
与测试文件；另新增 `tools/ccfa/repro_env.py`、`scripts/repro-env.ps1` 与测试；
修改 `tools/ccfa/stages.py`、README、设计文档、checklists、进度账本。

### Task 1: novelty

- 输入 `data/novelty-audit.yaml`；输出 JSON problems 到 stdout，人读摘要到 stderr。
- 判别力：少于三个近邻、单数据库/重复数据库、bib 中不存在的 neighbor、未知或重复
  claim id、重复近邻标题、cutoff 晚于检索日、claim 未被任何近邻差异覆盖、
  “no one has done this”表述都触发对应 problem；完整台账通过。

### Task 2: statistics

- 输入 `data/statistics-plan.yaml`。
- 判别力：alpha 越界、effect_size 非正或非有限、sample_size 非正、seeds 为空、
  多 claim 但 correction=none 都触发 problem；完整计划通过。

### Task 3: governance

- 输入 `data/governance.yaml`。
- 判别力：缺作者 COI、human_subjects=true 但缺 IRB/consent、AI 未披露、查重未做、
  双用途未复核都触发 problem；完整台账通过。

### Task 4: repro-env

- 输入 `data/repro-environment.yaml`。
- 判别力：缺台账、requirements/lockfile 缺失、lockfile 哈希漂移、system tool
  证据缺失或版本不匹配、无效容器 digest、重复工具都触发 problem；完整台账通过。

## 完成定义

- `grounded` gate 要求 novelty audit；`experiment-design` gate 要求 statistics plan；
  `submission-check` gate 要求 repro-environment 与 governance 台账。
- 新工具、wrapper、README、设计文档、checklists、测试与进度账本同步。
- 全量 tools/app 测试全绿。
- 文档明确：这三道 gate 只强制结构化声明与覆盖，不保证新颖性、统计正确性或治理真实性。
