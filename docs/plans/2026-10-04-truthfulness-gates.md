# 真实性 gate 实施计划（2026-10-04）

**Goal:** 处理科研工作流审计总结里的三条最高优先级缺口：人工验证缺位、
跨族评审能力与 gate 不匹配、证明与引用语义没有 gate。确定性脚本不能判断
数学证明或语义支撑是否正确，但可以把「必须有人做过判断」变成可检查的文件要求。

**裁定：**

- **E72 人工编码一致性。** 新增 `human_coding`：两张人工编码表按 item id join，
  计算 observed agreement、Cohen's kappa、95% bootstrap CI 与逐标签计数；
  `--min-kappa` 以下退 1。模型辅助审计不能替代这一步。
- **E73 证明与引用语义支持。** 新增 `argument_audit`：扫描
  theorem/proposition/lemma/corollary 环境，要求 `data/proof-audit.yaml` 中
  有具名人类复核记录；扫描受保护章节中的 `\cite{}`，要求
  `data/citation-support.yaml` 中有具名人类语义支持记录。脚本不判断证明和
  语义本身，只拒绝缺记录、模型 reviewer、refuted/uncertain/contradicts 和无法核对的引文。
- **E74 同族 override 异常化。** `cross-review run --allow-same-family`
  必须同时提供 `--override-reason`（≥20 字符），原因写入评审记录；
  `cross-review check --strict-cross-family` 把任何同族 override 报成 problem。
  真正的 gate 仍然要求不同 family 的 provider。

**Files:** 新增 `tools/ccfa/human_coding.py`、`tools/ccfa/argument_audit.py`、
`scripts/human-coding.ps1`、`scripts/argument-audit.ps1`；修改
`tools/ccfa/cross_review.py`、`tools/ccfa/stages.py`、`README.md`、
`docs/research-workflow-intro.md`、`docs/design/2026-10-03-research-workflow-design.md`、
`checklists/`、测试与进度账本。

### Task 1: 人工编码一致性

- 输入两张 CSV，默认列 `item_id,code`；重复 item、缺 item、空 code 都是 problem。
- 输出 JSON 到 stdout，人读摘要到 stderr；退出码 0 通过、1 低 κ 或有结构问题、2 工具错误。
- 判别力：完美一致 κ=1；已知 2×2 表 κ=0.8；低 κ 触发 `human-coding-low-kappa`。

### Task 2: 证明与引用语义支持

- 证明台账字段：`id`、`reviewer`、`reviewed_at`、`method`、`status`；
  `status` 必须为 `verified` 才通过。
- 引用支持台账字段：`id`、`claim_text`、`citations`、`reviewer`、`reviewed_at`、
  `verdict`、`support_quote`、`source_path`。
- 受保护章节中的每个 citation key 必须至少被一条 `supports` 记录覆盖；
  `claim_text` 必须逐字出现在该引用所在的受保护章节中；`support_quote` 必须逐字
  出现在 `source_path` 中。
- 判别力：缺台账、模型 reviewer、uncertain、contradicts、未知 bib key、
  引文不在 source 中都触发对应 problem；有效人类记录通过。

### Task 3: 同族 override 异常化

- `run --allow-same-family` 缺 `--override-reason` 或不足 20 字符 → 工具错误，退 2。
- 记录写入 `family_override_reason`；`check` 缺 reason 报
  `review-override-reason-missing`。
- `check --strict-cross-family` 对任何 `family_override=true` 报
  `review-family-override`。
- 判别力：缺 reason 不执行；reason 写入记录；strict 模式报 override。

## 完成定义

- 新工具、wrapper、README、设计文档、checklists、测试与进度账本同步。
- `tools` 与 `app` 全量测试全绿。
- `internal-review` gate 明确要求人工证明复核与引用语义支持台账无未复核项。
- 不把新 gate 写成「保证正确」：文档明确它只强制人工判断留痕，最终正确性仍靠外部专家。
