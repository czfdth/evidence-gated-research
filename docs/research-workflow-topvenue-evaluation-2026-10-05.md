# 科研工作流再评估：能否“一站式生成顶刊”

日期：2026-10-05
评估对象：本仓库科研工作流（ccfa 状态机 + 证据台账 + gate + 跨模型评审 + 复现包）
对标来源：GitHub 开源科研智能体 / 科研 skill / 方法学 harness + CS/AI 顶会官方要求

## 一、先回答那个直接的问题

**“一站式生成顶刊”作为工程目标不成立。** 但把它拆开会得到三个可实现的层级：

| 层级 | 目标 | 当前可达性 |
| --- | --- | --- |
| L1 | 一站式生成**可投稿初稿 + 完整证据包** | 接近达成 |
| L2 | 一站式生成**能过内部严格评审的稿** | 部分，卡在人工验证 |
| L3 | 一站式生成**被顶会/顶刊接受的稿** | 不成立，瓶颈是洞察而非流程 |

理由不是“工具还不够好”，而是顶刊的门槛结构：

1. 顶会要求的是**新 claim + 正确推理 + 强证据 + 清晰定位**，其中“新”和“正确”没有通用自动判定器。
2. 现有开源系统没有一个能证明可以稳定产出被接收的顶会论文。MLGym 的 13 个开放研究任务、PaperBench、Simreal-MLBench 等基准的存在本身就说明：研究智能体仍在“部分完成研究流程”的水平，而不是“稳定产出接收论文”。
3. 你自己的经历就是最直接的证据：内部 cross-review 曾给出 `pass`，而外部 CSF 评审发现 Proposition 4 的证明不成立。**自动评审的高分不能迁移为人类评审的接受。**

所以现实的定位应该写成：

> 一站式生成**可投稿初稿、证据包与纠错循环**；人的职责集中在洞察、判断与最终背书。

## 二、当前实际状态（2026-10-05 复检）

| 项 | 状态 |
| --- | --- |
| 主仓库 / 论文仓库 | 干净，与 `origin/master` 同步 |
| 工具模块 | 67 个 |
| PowerShell 入口 | 50 个 |
| 工具测试 | 1446 项通过 |
| app 测试 | 187 项通过 |
| `readiness` | `ready=false`，阻塞仅 2 类 |
| 论文新台账迁移 | 10/10 已完成 |
| `doctor` | 0 problems，1 advisory |

剩余阻塞：

```text
argument-audit: proof 8 条全部 pending-human-review
cross-review:   review-provider-config-drift + review-blocking
```

也就是说：**工程侧已经不再是瓶颈。** 这为下面的方法论分析提供了干净的基线。

## 三、最有价值的对标发现：breakthrough-harness

本轮检索到一个与你处境高度相关的项目：`GuoCheng24/breakthrough-harness`。它的定位不是编排框架，而是**让研究智能体“不自欺”的纪律层**。它的核心论断值得全文引用：

> **Breakthroughs are a throughput problem.**
> breakthrough ≈ many cheap attempts × a scoring function that is hard to fool.

并且给出了一个几乎是为你的情况写的推论：

> 当每一次尝试都很昂贵时，理性的做法是**审计已有的东西**，而不是去构建可能失败的新东西——审计有确定的交付物。持续滑向 negative-result / audit 的团队，是在理性地回应“尝试太贵”这件事。**把尝试变便宜，滑坡就会停止。**

这解释了你过去几轮的轨迹：台账从 5 个涨到 15 个、工具从 46 涨到 67 个、测试从 1065 涨到 1446 个，而论文本身推进缓慢。这不是纪律松懈，而是**昂贵尝试下的理性选择**。

### 它的五条习惯（你缺的方法论结构）

| # | 习惯 | 含义 | 你的现状 |
| --- | --- | --- | --- |
| 1 | **Null models first** | 相信任何分数之前，先问“什么都没学到的方法”会得多少分 | 缺失 |
| 2 | **Calibration 与 Evaluation 永不接触** | 在一组数据上调，在另一组上报告；未过 held-out 的提升等于不存在 | 缺失，且已被你自己的编码流程违反 |
| 3 | **打不过的 baseline 是你没读完的配方** | 复现到匹配之前不要宣称超越 | 部分具备 |
| 4 | **Claim 有极性** | 结果主句必须是构造性的；“审计输出支持 claim，但审计输出永远不是 claim” | 部分具备 |
| 5 | **每个 guard 都必须被演示会失败** | 没在故意破坏的输入上触发过的检查只是装饰 | 部分具备 |

### 它的 anti-cheat four（可直接借用的工程规则）

1. null model 放在地板上（先测下界）；
2. metric 约定固定并双重报告；
3. calibration 与 evaluation **物理隔离**；
4. 出现“荒谬 baseline”就冻结一切。

## 四、你缺失的方法论结构（按重要性）

### 1. Held-out 生命周期与预算（最严重）

`breakthrough-harness` 引用 Dwork et al. 的 reusable holdout：反复查看 held-out 集合，会让它悄悄退化成 calibration 集。

你的情况有一个具体实例：`human-coding-v2` 用同一批 9 篇工作既做 pilot、又做最终一致性报告。这违反了习惯 2。正确做法：

- 用一部分样本开发 codebook（calibration）；
- 用**从未参与开发**的另一批样本报告 kappa（evaluation）；
- 给 held-out 集合记录访问次数与预算。

这条现在没有任何机制强制，是方法论层最大的洞。

### 2. Null model / 负控

你的工作流没有要求任何“负控”。对 SoK 论文，对应的负控是：

- 随机编码器的一致率会是多少？
- 只按标题编码会得到什么矩阵？
- 两位编码者的 κ 是否显著高于“按先验比例随机猜”？

没有 null model，任何 κ、任何覆盖率、任何分数都无法判断是否真的好。

### 3. Claim 极性

你的 `claim-registry.yaml` 有 `type: theoretical | empirical | descriptive`，但没有极性约束。`breakthrough-harness` 的规则是：结果主句必须是构造性的，审计输出只是支持材料。

对 SoK 尤其危险：描述性结论很容易被写成发现性结论。建议在 claim registry 增加：

```yaml
polarity: constructive | descriptive   # 描述性 claim 不得使用发现性措辞
```

并在 final-check 里禁止把 `descriptive` claim 写成 “we discover / we reveal / first to” 这类发现性表述。

### 4. 每个 guard 必须被演示会失败

你有大量 gate，但缺少系统性证据证明**每个 gate 在故意破坏的输入上确实会失败**。部分计划文档里提到过“判别力测试”，但没有成为全局要求。

建议：

- 每个 gate 必须有一条“反例测试”；
- 新增 `data/gate-failure-drills.yaml` 记录每次演练：gate 名、破坏方式、是否触发、证据；
- 未演练过的 gate 在 readiness 中标为 `unproven-guard`。

这条直接回应你踩过的坑：governance gate 曾接受 pending 占位文本、readiness 曾只查文件存在。这些都是“没被演示会失败的 guard”。

### 5. 尝试成本（throughput）

这是最深的结构性缺口。你的工作流完全没有度量“一次尝试要多久”。而 breakthrough-harness 的整个论证是：**先让尝试变便宜**。

建议引入两个指标：

```text
time_to_first_attempt  从 idea 冻结到第一次可评分实验的时间
cost_per_attempt       单次尝试的 GPU 分钟 / 美元 / 人工分钟
```

如果 time_to_first_attempt 是几天甚至几周，工作流就必然持续滑向审计行为。

### 6. Metric 约定注册表

你有 `\dataval` 与舍入容差，做得比多数系统好。但仍缺：

- 每个指标的精确约定（分母、边界、是否去重）；
- 双重报告（原值 + 归一化值）；
- 约定变更时的历史重算。

建议 `data/metric-conventions.yaml`。

### 7. 荒谬 baseline ⇒ 冻结

若某次实验出现“荒谬基线反而最好”，说明管线有 bug，此时应冻结全部结论，先修管线。你的 run-log 与 queue 有失败留档，但没有这条显式规则。

## 五、与其他开源系统的结构对照（更新后）

| 结构 | 你的状态 | 对标来源 |
| --- | --- | --- |
| claim registry | ✅ 已迁移 | ARA |
| exploration graph / dead end | ✅ 已迁移 | ARA、ARIS |
| assumptions / limitations | ✅ 已迁移 | NeurIPS checklist |
| rigor rubric | ✅ 已迁移 | ARA rigor-reviewer |
| artifact provenance | ✅ 已迁移 | ARA、open-science |
| venue checklist | ✅ 已迁移（NeurIPS/ARR） | 官方 |
| cost ledger | ✅ 已迁移 | ARS |
| proof campaign | ✅ 已迁移 | ARIS proof-orchestrator |
| run ledger / passport | ✅ 已建 | academic-research-skills |
| immutable artifact store | ✅ 已建 | open-science |
| **null model / 负控** | ❌ 缺 | breakthrough-harness |
| **held-out 生命周期与预算** | ❌ 缺 | Dwork et al. / breakthrough-harness |
| **claim 极性** | ❌ 缺 | breakthrough-harness |
| **guard 必须被演示失败** | 🟡 部分 | breakthrough-harness |
| **尝试成本度量** | ❌ 缺 | breakthrough-harness |
| **metric 约定注册表** | ❌ 缺 | breakthrough-harness |
| **荒谬 baseline 冻结规则** | ❌ 缺 | breakthrough-harness |
| 长时研究环境 / 共享文献 | ❌ 缺 | dualverse-ai/station |
| 研究智能体基准化评估 | ❌ 缺 | MLGym、Simreal-MLBench |

## 六、关于“顶刊方法”还需要补什么

顶会/顶刊的方法学要求，你的 venue-checklist 已覆盖条目层。但条目背后的**方法论纪律**仍缺：

1. **NeurIPS：** claims 与摘要/引言一致、limitations、theory assumptions & proofs、实验可复现、统计显著性、算力报告。你缺的是“摘要—引言—结果表”三方一致性检查。
2. **ARR：** 每个 Yes 必须指向具体章节。你缺的是“checklist 答案 ↔ 正文位置”的机器可查映射。
3. **ACM Artifact Badging：** available / evaluated / reusable。你有契约，但没有第三方 evaluated/reusable 证据。
4. **方法论纪律：** 上面第四节的 7 条，尤其 held-out 与 null model，是审稿人真正会用的问题，而不是条目本身。

## 七、建议：把“一站式”重新定义为“一站到可投稿初稿”

### P0（立刻）

1. **修正 human coding 的 held-out 违反**：pilot 样本与报告样本分离。
2. 增加 null model 要求：κ、覆盖率、矩阵统计都要报告负控基线。
3. claim registry 增加 `polarity` 字段，final-check 禁止描述性 claim 使用发现性措辞。
4. 建立 `gate-failure-drills`：每个 gate 必须有一条故意破坏的触发证据。

### P1（两周内）

5. 引入 `time_to_first_attempt` 与 `cost_per_attempt` 两个吞吐指标，并实际测量。
6. 建立廉价尝试循环：小规模、可评分、可并行，替代“昂贵一次 + 大量审计”。
7. 建立 metric convention 注册表与双重报告。
8. 加“荒谬 baseline ⇒ 冻结”规则。

### P2（长期）

9. 把 held-out 预算机制产品化（访问计数 + 生命周期）。
10. 用 MLGym / Simreal-MLBench 式外部基准评估**你的工作流本身**，而不只是论文。
11. 补第三方 artifact badge 证据、Zenodo DOI、ORCID。

## 八、结论

你已经有全生态里最完整的一层：**证据、gate、provenance、复现、评审分离**。用 breakthrough-harness 的话说，你把“不要自欺”做到了很高的水准。

但它同时点出了你的结构性偏差：**你把力气花在了让评分函数难以被欺骗上，却没有让尝试变便宜。** 当尝试很贵时，继续审计是理性的；而顶刊需要的是大量廉价尝试加上难以作弊的评分函数。

所以答案分两半：

- “一站式生成顶刊”**不成立**，任何开源系统都做不到，瓶颈是洞察而非流程；
- “一站式生成可投稿初稿 + 可信证据包 + 不自欺的纠错循环”**已经接近达成**，而你的工作流在这条路上领先大多数开源项目。

下一步最该修的不是再加 gate，而是补上 held-out 纪律、null model、claim 极性、guard 失败演练，以及最重要的——**降低一次尝试的成本**。
