# 跨族评审实施计划（E68–E70）

**Goal:** 关闭审计 P1-6：原 `cross-review` 默认执行模型与评审模型同属 DeepSeek V4，同族评审只能记 `same-family`，不能冒充跨族 gate。v1 不伪造第二个 provider；它把“必须跨族”变成可执行约束，并允许显式、可审计的例外。

**裁定：**

- **E68 记录真实组成。** 评审记录新增 `provider`、`execution_model`、`family_judgement`、`family_override`；`family_judgement` 由评审模型家族与执行模型家族计算，未知族记为 `unknown`。v1 的执行模型固定为工作流常量 `deepseek-v4-flash`，不作为 `run` 的 CLI 覆盖；跨族只能通过选择不同 family 的评审模型实现，不能用自报的 `--execution-model` 改变 gate。
- **E69 默认拒绝同族/未知族。** `cross-review run` 只有在 `family_judgement=="cross-family"` 时才允许写 pass；同族/未知族默认退 2，除非显式传 `--allow-same-family`。override 只是诚实例外，不等于跨族。
- **E70 `check` 强制同一口径。** 旧记录或缺字段记录默认报 problem `review-same-family`；只有记录内 `family_override: true` 或调用方显式 `check --allow-same-family` 才豁免。`--provider` 作为 `codex exec -c model_provider=<provider>` 传入并进记录。信任边界写清：`check` 检测本地记录内部不一致，不是密码学签名；能改写整份 JSON 的人仍可同时伪造 `model` 与 `family_judgement`，本机防的是默认同族与无意错写，不是防本机恶意篡改。

**Files:** Modify `tools/ccfa/cross_review.py`、`tools/tests/test_cross_review.py`、`docs/design/2026-10-03-research-workflow-design.md`、`docs/sdd/2026-10-03-evidence-tracking-progress.md`。

**DoD：**

- 同族模型默认不能写 pass；跨族模型可写；provider 进入 argv 与记录。
- `check` 对同族/旧记录报 `review-same-family`；显式 override/migration flag 可豁免。
- 判别力：同族拒绝、跨族接受、provider argv、override 豁免四条均有测试。
- 全量 tools/app 全绿；文档明确“本机尚未配置第二 provider，跨族仍需用户接入”。
