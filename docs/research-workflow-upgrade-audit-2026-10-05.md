# 科研工作流升级逐项审计

日期：2026-10-05

审计对象：`docs/research-workflow-benchmark-2026-10-05.md`

结论口径：

- **代码完成**：工具、schema、测试和入口已存在。
- **模板接入**：新论文会自动生成对应台账。
- **当前论文已落地**：`papers/example-paper` 已有真实、可解析的台账。
- **外部完成**：需要真人、第二个 provider、GitHub secret、Zenodo/OSF 或第二环境。

一句话结论：**对标报告的代码侧缺口已经补齐，但当前示例论文没有迁移到新台账，
因此整体仍未 ready。真正剩下的阻塞是项目接入、人工复核、真实跨族评审和外部归档。**

## 1. 十个共同结构

| # | 结构 | 状态 | 证据 | 仍未完成 |
| --- | --- | --- | --- | --- |
| 1 | claim 中心组织 | 代码完成，当前论文未落地 | `research_ledgers.py`、`data/claim-registry.yaml` 模板、readiness gate | 示例论文缺少 `data/claim-registry.yaml` |
| 2 | 探索图与死路记忆 | 代码完成，当前论文未落地 | `data/exploration-graph.yaml`、`memory.py`、`research_ledgers.py` | 示例论文缺少 exploration graph |
| 3 | 双循环编排 | 部分完成 | `experiment_loop.py` 记录 pilot、inner loop、outer loop 与 next action | 还没有自动调参/自动改代码执行器；当前是确定性记录与待办编排 |
| 4 | 实验直接接算力 | 本机机制完成，远程算力未接 | `queue.py` 支持 Docker、GPU 秒预算、stall watchdog | 远程 GPU/HPC 调度未实现，Docker daemon 本轮未验证 |
| 5 | provenance 标签 | 代码完成，当前论文未落地 | `data/artifact-provenance.yaml`、research-ledgers | 示例论文缺少 artifact provenance |
| 6 | rigor 评分 rubric | 代码完成，当前论文未落地 | `rigor.py` 六维 0..4 评分、证据绑定、真人/模型边界 | 示例论文缺少 `data/rigor-rubric.yaml` |
| 7 | 对抗评审且禁止自我开释 | 硬约束完成，真实跨族未完成 | `cross_review.py` 同族 pass 强制 blocking；high-assurance 要求真实跨族 | 当前机器没有第二个 family provider，示例论文记录仍是 same-family override |
| 8 | 累积研究记忆 | 工具完成，内容为空 | `research_wiki.py`、`library/wiki/` frontmatter、索引与搜索 | wiki 当前没有实际卡片 |
| 9 | 长时跨会话任务 | 机制完成，当前论文未落地 | `proof_orchestrator.py`、proof campaign attempts、next action | 示例论文缺少 `data/proof-campaign.yaml`，证明复核仍 pending |
| 10 | 投稿后链路 | 契约完成，当前论文未到尾部 | `post_submission.py` 校验 rebuttal/resubmit/talk | 当前论文缺少 post-submission 台账，尚未进入投稿后阶段 |

## 2. 八类建议新增结构

| # | 结构 | 状态 | 说明 |
| --- | --- | --- | --- |
| 1 | 统一 claim registry | 代码和模板完成 | `claim-registry.yaml` 已由 research-ledgers 校验；当前论文未迁移 |
| 2 | assumptions / limitations | 代码和模板完成 | 与 claim 双向链接、重复 ID、placeholder 均校验；当前论文未迁移 |
| 3 | exploration graph / dead end | 代码和模板完成 | pivot/dead-end/rejected/active 绑定 claim 与 run；当前论文未迁移 |
| 4 | artifact provenance | 代码和模板完成 | 记录 `human/model/mixed`、model family、run id 或 source hash；当前论文缺少该台账 |
| 5 | 算力与成本账本 | 代码和模板完成 | 记录 GPU 小时、型号、美元、token、重跑次数；当前论文未迁移 |
| 6 | venue checklist | 代码和模板完成 | 支持完整/pending/not-applicable/blocked 与证据；当前论文未迁移 |
| 7 | 风险登记册 | 代码和模板完成 | 风险、severity、mitigation、evidence、status；当前论文未迁移 |
| 8 | autonomy policy | 文档完成 | `docs/autonomy-policy.md` 已定义自动推进与人工批准边界 |

## 3. 七类流程

| # | 流程 | 状态 | 结论 |
| --- | --- | --- | --- |
| 1 | 双循环编排 | 部分完成 | 有多 attempt、result、decision、next action 的记录和续跑入口；没有自动搜索超参或自动改 bug 的执行器 |
| 2 | 想法 pilot | 记录和筛选契约完成 | 支持预算、metric、kill criterion、run id 与 promote/reject/park；不会自动跑 pilot |
| 3 | 对抗评审禁止开释 | 代码完成，实际能力待补 | 同族 override 不能 pass；真实跨族仍需第二个 provider |
| 4 | 周期性工作流自评 | 完成 | `meta_optimize.py` 聚合 friction 与 readiness gate 失败，输出 proposed，需人工批准 |
| 5 | 投稿后链路 | 完成 | rebuttal、resubmit、talk 都有机器可读契约 |
| 6 | 长任务续跑 | 完成 | proof orchestrator 记录 attempts、failure reason、next action；但不自动证明 |
| 7 | 复现分级与 artifact badge | 契约完成 | available/evaluated/reusable 有校验；DOI、第三方 evaluated、第三方 reuse 尚未取得 |

## 4. 顶会与顶刊方法学要求

| 要求 | 状态 | 审计结论 |
| --- | --- | --- |
| claims 与摘要/引言一致 | 部分 | claim registry 有双向链接与 claims policy；还没有专门的摘要/引言与结果表一致性语义检查 |
| limitations 台账与 gate | 代码完成，当前论文未落地 | assumptions/limitations schema 已有；示例论文缺少该文件 |
| 理论假设完整 | 部分 | assumptions 台账已有；示例论文未迁移，Proposition 4 仍无真人复核 |
| 证明完整 | 未完成 | proof orchestrator 和 proof-audit gate 已建；8 条 proof review 仍 pending |
| 实验可复现 | 部分 | run-log、provenance、repro 包已有；没有第二环境或容器实测证据 |
| 统计显著性/误差 | 代码完成 | statistics-plan gate 已有；当前 SoK 的适用性仍需作者判断 |
| 算力报告 | 代码完成，当前论文未落地 | cost ledger 已支持；示例论文未迁移 |
| 数据/代码开放 | 未完成 | GitHub private 和 repro 包已有；没有 Zenodo/OSF DOI |
| 伦理、broader impact、safeguards | 部分 | governance 工具可拒绝 placeholder；示例论文 COI、查重、披露联系人仍 pending |
| 数据许可与引用 | 部分 | governance 和 artifact badge 有许可字段；没有逐数据集许可检查 |
| artifact badge | 契约完成 | available/evaluated/reusable 工具已完成；当前论文没有 badge 台账，也没有第三方复核 |
| 匿名与双盲 | 部分 | 私有仓库和 workflow 已在；PAT secret、branch protection 和第二环境 CI 未核验 |

## 5. P0 / P1 / P2 实施顺序

| 项 | 状态 | 证据与剩余工作 |
| --- | --- | --- |
| P0-1 claim registry | 代码完成，论文未迁移 | 工具与模板已落地；示例论文 readiness 报 missing |
| P0-2 assumptions / limitations | 代码完成，论文未迁移 | 同上 |
| P0-3 venue checklist | 代码完成，论文未迁移 | 同上 |
| P0-4 人工证明复核与真人双编码 | 未完成 | proof-audit 8 条 pending；human-coding-report 仍 pending |
| P1-5 pilot 与内层实验循环 | 记录完成，自动化未完成 | `experiment_loop.py` 有记录和 next；没有自动调参执行器 |
| P1-6 探索图与死路 | 代码完成，论文未迁移 | 工具已建，示例论文缺少台账 |
| P1-7 对抗评审禁止自我开释 | 硬约束完成，真实跨族未完成 | 同族不能 pass；真实跨族 provider 未配置 |
| P1-8 算力与成本账本 | 代码完成，论文未迁移 | 工具已建，示例论文缺少台账 |
| P1-9 rebuttal / resubmit / talk | 完成 | post-submission 契约与测试已完成 |
| P2-10 Research Wiki | 工具完成，内容为空 | wiki 校验、索引、搜索已建；尚未积累卡片 |
| P2-11 proof orchestrator | 工具完成，论文未接入 | campaign schema 与 next 已建；示例论文缺少台账 |
| P2-12 ACM badge / DOI | 工具完成，外部动作未完成 | badge 校验已建；DOI、第三方 evaluated/reusable 未取得 |
| P2-13 rigor 六维评分 | 工具完成，论文未接入 | 六维评分和真人边界已建；示例论文缺少台账 |
| P2-14 工作流自评 | 完成 | meta-optimize 已建；提案仍需人类批准 |

## 6. 当前示例论文的实际阻塞

`scripts/readiness.ps1 --paper-root papers/example-paper` 当前结果：

- `ready=false`
- `stage=internal-review`
- `profile=standard`
- `scientifically-accepted=not-claimed`
- `independently-reviewed=pending-human-review`

缺失的 standard ledgers：

- `artifact-provenance`
- `assumptions-limitations`
- `claim-registry`
- `cost-ledger`
- `experiment-loop`
- `exploration-graph`
- `proof-orchestrator`
- `rigor-rubric`
- `risk-register`
- `venue-checklist`

已有 gate 问题：

- `argument-audit`: proof review not verified
- `research-ledgers`: missing core ledgers
- `cross-review`: provider config drift、blocking、uncited blocking

人工与治理 pending：

- `proof-audit.yaml`: 8 条 proof review 全部 pending
- `citation-support.yaml`: supports 为空
- `figure-support.yaml`: figures 为空
- `human-coding-report.json`: pending human dual coding
- `governance.yaml`: COI、查重、披露联系人 pending

## 7. 最短剩余路径

1. **迁移示例论文台账**：按真实内容补 claim、assumptions、exploration、provenance、
   cost、risk、venue、experiment-loop、proof campaign、rigor 和 artifact badge。
   无实验或不适用时使用 `not_applicable` 与具体理由，禁止填假数据。
2. **完成人工复核**：逐行复核 Proposition 4 等 8 条 proof；完成 citation semantic
   support、figure support 和真人盲法双编码。
3. **接入真实跨族评审**：配置第二个 family provider，重跑 cross-review，移除
   same-family override。
4. **验证 GitHub 运维**：PAT secrets、branch protection、跨仓库 workflow 的真实运行证据。
5. **完成第二环境复现与归档**：容器或第二机器重跑，取得 Zenodo/OSF DOI，填写
   artifact badge 的第三方 evaluated/reusable 证据。
6. **开始填充 Research Wiki**：把已确认的 decision、dead-end、method、result 卡片
   纳入 `library/wiki/`，而不是继续增加新 gate。

## 8. 最终判定

代码层的对标升级已经完成。当前距离“产品级科研工作流”的真正差距不再是工具数量，
而是：

1. 示例论文没有迁移到新证据体系；
2. 人工科研验证没有完成；
3. 真实跨族 provider 和外部归档没有接入；
4. 第二环境复现和 GitHub 运维没有实测证据。

因此现在不应继续宣称 `review_cleared` 或 `ready`。正确的下一步是把现有论文接入
新台账并完成人工与外部验证，而不是继续加新的检查脚本。
