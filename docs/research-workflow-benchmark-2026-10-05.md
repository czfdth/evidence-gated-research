# 科研工作流对标报告：GitHub 生态与 CS/AI 顶会方法学

日期：2026-10-05
对标对象：GitHub 开源科研智能体 / 科研 skill 库 / 科研工作流 + CS/AI 顶会与安全会议方法学要求
对标基准：本仓库 `科研工作流`（ccfa 状态机 + 确定性 gate + 证据台账 + cross-review + 复现包）

## 一、对标对象一览

| 系统 | 定位 | 核心结构 |
| --- | --- | --- |
| SakanaAI/AI-Scientist | 全自动科学发现 | 想法生成 → 实验迭代 → 论文撰写 → 自动评审；模板绑定（NanoGPT / Diffusion / Grokking）；容器化 |
| SamuelSchmidgall/AgentLaboratory | LLM 作为研究助理 | 三阶段：文献综述 → 实验 → 报告撰写；专职 agent 分工；Co-Pilot 模式；任务 notes 必须写清算力；AgentRxiv 累积平台 |
| Orchestra-Research/AI-Research-SKILLs | AI 科研 skill 库 | 98 个 skill / 23 类；`autoresearch` 双循环编排（内层优化 + 外层综合）；含工程类 skill（训练/推理/评测/RAG/多模态） |
| wanshuiyin/ARIS | Markdown-only 自主 ML 科研 | 83 个可组合 skill；全链路 pipeline；跨模型对抗评审；Research Wiki 长期记忆；proof orchestrator；rebuttal/resubmit/talk/patent |
| Imbad0202/academic-research-skills | 人在环学术写作流水线 | 5 个 skill：Deep Research / Academic Paper / Reviewer / Pipeline / SR-Screener；run ledger；risk register；governance；data flows |
| gxCaesar/open-research-skills | 从选题到可复现发布 | 10 个可独立安装 skill；五个过程入口；对照评测并公开自身缺陷 |
| aipoch/open-science | 本地优先科研工作台 | 桌面 app + skills + MCP + Python/R 执行；`.science` 研究包；可追溯 artifact（能看到结果从哪来） |
| reproducibility-sec/reproducibility | 复现实证研究 | 对安全顶会 ML 论文做复现性测量 |
| AmberLJC/ara-paperbench | Agent 原生科研 artifact | 32 个机器可读、以可复现为先的 artifact，含 claims、可运行代码、grounded evidence、探索轨迹 |
| 方法学基准 | 顶会/顶刊要求 | NeurIPS Paper Checklist、ARR Responsible NLP Checklist、ACM Artifact Badging、复现性研究 |

## 二、这些系统的共同结构

把上面 9 个系统拆开看，反复出现的结构只有 10 个：

1. **claim 是中心对象**：claim → 实验 → 证据 → 图 → 引用，全部围绕 claim 组织。
2. **探索图（exploration graph）**：记录走过的路、死路（dead end）和转向（pivot），而不是只记录成功路径。
3. **双循环编排**：内层 loop 做单次实验优化，外层 loop 做整体综合与决策。
4. **可运行的实验体 + 远程算力**：把实验直接接到 GPU/HPC，而不是只写实验计划。
5. **provenance 标签**：区分“人决定的”与“AI 决定的”，每个 artifact 能回溯到来源。
6. **rigor 评分 rubric**：对证据相关性、可证伪性、范围、一致性、方法学等打分，而不是只做 pass/fail。
7. **对抗式评审且禁止自我开释**：评审方不能由执行方自己担任，且“能驱动流程 ≠ 能批准结论”。
8. **累积式研究记忆**：跨会话/跨项目持续累积文献、想法、失败实验，失败想法变成反重复记忆。
9. **长时跨会话任务**：多天推进一个证明、一个实验循环，可中断可续跑。
10. **投稿后链路**：rebuttal → resubmit → talk → artifact release，全部有对应 skill。

## 三、你的工作流与它们的对照

图例：✅ 已有且可用；🟡 有机制但未落地/不完整；❌ 缺失

| 能力 | 你的状态 | 对标系统 | 差距说明 |
| --- | --- | --- | --- |
| claim 中心组织 | 🟡 | 全部 | 你有 `data/claims.yaml`、`\dataval`、citation ledger、figure manifest，但它们是四条独立链，没有统一的 claim→evidence→figure→citation 图 |
| 探索图与死路记忆 | 🟡 | ARA、ARIS | 你有 `memory/dead-ends` 与 `friction_log`，但没有把每一次 pivot/dead end 绑定到 claim 与 run |
| 双循环编排 | ❌ | AI-Research-SKILLs、ARIS | 你是线性 stage 状态机 + gate，没有“内层实验优化循环 + 外层综合循环” |
| 实验直接接算力 | 🟡 | ARIS、AI-Scientist、AgentLab | 你有 `queue` + Docker 沙箱 + GPU 秒预算，但 Docker daemon 当前不可达，也没接远程 GPU/HPC |
| provenance 标签（人 vs AI） | 🟡 | ARA、open-science | 你有数据来源、评审 provenance、run-log，但没有“这个决定是人还是模型做的”逐 artifact 标签 |
| rigor 评分 rubric | ❌ | ARA Rigor Reviewer、ARR checklist | 你的 gate 是存在性/格式检查 + 二元 pass/fail，没有六维 rigor 评分 |
| 对抗评审且禁止开释 | 🟡 | ARIS | 你有 `cross-review`，但当前记录是 `same-family`、`provider=null`、且 stale；“能驱动不能批准”没有写成硬约束 |
| 累积研究记忆 | 🟡 | ARIS Research Wiki、AgentRxiv | 你有 `memory` 与 `library`，但更像局部工具，没有跨项目复利增长的 wiki |
| 跨会话长任务 | 🟡 | ARIS proof-orchestrator、auto-research-in-sleep | 你有 `watch` 与 automation prompt，但没有 run-directory 的证明战役续跑机制 |
| 投稿后链路 | 🟡 | ARIS W4-W6、ARS pipeline | 状态机里有 `rebuttal` / `major-revision`，但缺少 rebuttal、resubmit、talk 的实操 skill 与产出物契约 |
| 算力/成本账本 | ❌ | ARS（明确给出 $3-7/篇）、AI-Scientist | 你有 GPU 秒预算，但没有每篇论文的累计算力与费用账本 |
| venue 方法学 fixture | ❌ | 顶会 checklist | 你检查格式与引用，但没有把 NeurIPS/ARR/ACM 的 checklist 条目做成可检查清单 |
| artifact release / badging | 🟡 | ACM badging、ARA paperbench | 你有 repro 包与 release workflow，但只有 stdlib 级复现，没有 badge 对应关系 |
| 风险登记与治理文档 | 🟡 | ARS（RISK_REGISTER / GOVERNANCE / DATA_FLOWS） | 你有 `governance.yaml`，但 COI/查重/披露仍是 pending，也没有常设风险登记册 |
| 自主程度策略 | ❌ | ARS（明确人在环）、ARIS（可配置 checkpoint） | 你没有“哪些阶段自动推进、哪些必须人批准”的成文策略 |
| 工作流自评与自优化 | 🟡 | ARIS `/meta-optimize`、open-research-skills 公开缺陷 | 你有 `friction_log`，但没有周期性把摩擦聚合成工作流改进的流程 |

## 四、你缺少的结构（建议新增）

### 1. 统一 claim registry（最高优先）

现在 claim、数字、引用、图分散在四处。建议合并为一个机器可读注册表：

```yaml
# data/claim-registry.yaml
claims:
  - id: C1
    statement: "单个文本级分离防御在 epsilon-close 观测下存在误差下界"
    type: theoretical          # theoretical | empirical | descriptive
    assumptions: [A1, A2]
    proof: prop:textonly       # 指向 proof-audit
    experiments: []            # SoK 可为空
    figures: [threat-model-lattice]
    citations: [gao2024ragsurvey]
    limitations: [L1]
    status: pending-human-review
```

这样每个 claim 一条链到底，gate 可以真正检查“claim 是否有证据、证明、图、引用、局限”。

### 2. 假设与局限注册表

NeurIPS checklist 明确要求：理论结果必须列全假设，并说明假设被违反时的后果。你现在有 `proof-audit`，但没有独立的 assumptions/limitations 台账。建议：

```yaml
# data/assumptions-limitations.yaml
assumptions:
  - id: A1
    claim_ids: [C1]
    statement: "..."
    violation_impact: "..."
limitations:
  - id: L1
    claim_ids: [C1]
    statement: "..."
    discussed_in: manuscript/sections/08-open-problems.tex
```

### 3. 探索图与死路记录

借 ARA 的 exploration graph：每次 pivot、失败实验、被否掉的想法都进图，并绑定 claim 与 run id。失败想法应成为下次 ideation 的反重复输入。

### 4. artifact provenance 标签

为每个主要产出（图、表、评审、台账）记录：`decided_by: human | model | mixed`、`model_family`、`run_id`、`source_sha256`。这是 ARA 与 open-science 都在做的“结果从哪来”。

### 5. 算力与成本账本

记录每篇论文：GPU 小时、GPU 型号、美元成本、token 成本、重跑次数。ARS 直接给出“15k 词论文约 $3-7”，你的工作流目前完全没有这个维度。

### 6. venue 方法学 fixture

把三份官方要求落成可检查文件：

| 来源 | 关键条目 |
| --- | --- |
| NeurIPS Paper Checklist | claims 与摘要/引言一致；limitations；theory assumptions & proofs 完整；实验可复现（数据/代码/设置/种子）；统计显著性；算力报告；伦理与 broader impact；safeguards |
| ARR Responsible NLP Checklist | 局限、风险、数据许可与引用、标注协议、IRB、社会影响、复现信息；每个 Yes 需指向具体章节 |
| ACM Artifact Badging | Artifacts Available / Evaluated / Reusable 三档，需对应可复现包与复用说明 |

建议新增 `data/venue-checklist.yaml`，并与 `submission-check` gate 绑定。

### 7. 常设风险登记册

借 ARS 的 `RISK_REGISTER.md`：列出已知风险（如模型评审可能漏掉证明漏洞）、对应控制、证据状态、未解决项。你们的示例论文已经出现过“自动评审给 pass 但 Proposition 4 有 soundness 问题”，这正是风险登记册该记录的类型。

### 8. 自主程度策略

写成一份 `docs/autonomy-policy.md`：哪些阶段可自动推进、哪些必须人批准、哪些必须外部人复核。ARS 明确选择“人在环而非全自动”，ARIS 用可配置 checkpoint，你目前是隐式的。

## 五、你缺少的流程（建议新增）

### 1. 双循环编排

参考 AI-Research-SKILLs 的 `autoresearch`：

- **内层循环**：单次实验优化（改超参、修 bug、加 baseline），自动迭代到指标收敛。
- **外层循环**：跨实验综合（claim 是否成立、是否要换方向、是否要写进论文）。

你现在的 stage 是单向推进，缺少内层自动迭代与外层综合回路。

### 2. 想法筛选要先做 pilot

ARIS 的做法：8-12 个想法 → 过滤 → 对前 2-3 个做 30 分钟到 2 小时的并行 pilot → 按实测信号排序。你的流程在 `grounded` 之后直接进 experiment-design，缺少“小试决定要不要投入”的环节。

### 3. 对抗评审不得自我开释

ARIS 的表述值得直接采用：**can drive, never acquit**。具体到你的 gate：

- 执行模型与评审模型必须跨族，且 provenance 可验证；
- 同族评审只能产出 advisory，不能写 `pass`；
- 涉及理论正确性的结论必须有人工证明复核，模型评审不得替代。

### 4. 周期性工作流自评

借 ARIS `/meta-optimize`：定期分析 `friction_log`、gate 失败原因、返工次数，产出工作流改进提案，并由人类批准。open-research-skills 甚至公开自己 skill 的对照评测与缺陷，这种自评文化值得引入。

### 5. 投稿后链路

补齐三个缺失产出物契约：

| 阶段 | 需要新增的产出 |
| --- | --- |
| rebuttal | 逐条回复矩阵 + 证据引用 + 实验补充清单（你已有 `revision_ledger` 雏形） |
| resubmit | venue 差异表 + 需要改写的章节清单 |
| talk | 幻灯片大纲 + 图表复用清单 + 讲稿要点 |

### 6. 长任务续跑

借 ARIS proof-orchestrator：为“跨天攻一个定理”建立 run directory，记录每次尝试、失败原因、下一步计划，可中断续跑。你的 `proof-audit` 目前只有 pending，没有推进机制。

### 7. 复现分级与 artifact badge

把复现分为三级并对齐 ACM badge：

1. `available`：代码与数据可获取；
2. `evaluated`：第三方能重现主要结论；
3. `reusable`：他人能在新场景复用。

你现在是 stdlib 级重算，大概只到 available 的一半。

## 六、顶会/顶刊方法学要求 → 你的差距

| 要求 | 你有 | 差距 |
| --- | --- | --- |
| claims 与摘要/引言一致 | `claims.yaml` | 没有“摘要/引言 claim 与结果表一致性”检查 |
| limitations 章节 | 有 open problems | 没有独立 limitations 台账与 gate |
| 理论假设完整 | `proof-audit`（pending） | 没有 assumptions 注册表；Proposition 4 仍未被人工复核 |
| 证明完整 | 附录有证明 | 无人工验证，模型评审给过错误 pass |
| 实验可复现（数据/代码/设置/种子） | run-log + provenance + repro 包 | 复现仅 stdlib 级，无第二环境证据 |
| 统计显著性/误差 | `statistics-plan.yaml` | 描述性 SoK 里填了不适用的 effect size / power |
| 算力报告 | GPU 秒预算 | 无每篇论文算力汇总 |
| 数据/代码开放 | GitHub private + repro 包 | 无 DOI/Zenodo，投稿期需保持私有 |
| 伦理、broader impact、safeguards | `governance.yaml`（pending） | COI/查重/披露未填；无双用途单独章节检查 |
| 数据许可与引用 | governance 里有 license | 无逐数据集 license 检查 |
| artifact badge | 无 | 无 badge 目标与对应证据 |
| 匿名与双盲 | 私有仓库 | 已具备，但 CI 跨仓库 token 未验证 |

## 七、和各家相比，你的独特优势

不要只补短板，也要认清你已经做得比多数开源系统更好的地方：

1. **状态机 + 回退留痕**：ARIS/AI-Scientist 都没有你这种带 `void_artifacts` 的回滚历史。
2. **证据台账与 fail-closed gate**：readiness 会聚合 gate，governance 会拒绝 pending 占位文本，这比多数 skill 库严格。
3. **数字溯源 `\dataval`**：把正文数字机械回源，这一点对标系统里基本没有。
4. **引用证据台账 + DOI 核验**：比 ARIS 的 DBLP/CrossRef 校验更偏“逐条证据”。
5. **run-log 与 commit 绑定、脏树检测**：比绝大多数科研 agent 都更严谨。
6. **独立复现包 + gate**：多数开源系统只给脚本，不给复现包契约。

你的问题不是“不够先进”，而是**缺少闭环的另一半**：想法筛选、探索记忆、算力接入、对抗评审、投稿后链路。

## 八、建议实施顺序

### P0（本次投稿前）

1. 建立 `data/claim-registry.yaml`，把 claim / 证明 / 图 / 引用 / 局限串成一条链。
2. 建立 `data/assumptions-limitations.yaml`，并让 `argument-audit` 检查覆盖率。
3. 把 NeurIPS + ARR checklist 落成 `data/venue-checklist.yaml` 并接进 `submission-check`。
4. 完成人工证明复核与真人双编码（这是当前唯一真正的科学阻塞）。

### P1（一个月内）

5. 实现内层实验循环（自动调参 / 修 bug / 补 baseline）与 pilot 筛选环节。
6. 引入探索图与死路记忆，绑定 claim 与 run。
7. 把“对抗评审禁止自我开释”写成硬约束，并用真实跨族模型重跑 cross-review。
8. 建立算力与成本账本。
9. 补 rebuttal / resubmit / talk 三个产出物契约。

### P2（长期）

10. 建设 Research Wiki 式跨项目累积记忆。
11. 实现 proof orchestrator 式跨天长任务。
12. 对齐 ACM artifact badge，接入 Zenodo/OSF 获取 DOI。
13. 引入 rigor 六维评分（evidence relevance / falsifiability / scope / coherence / exploration integrity / methodology）。
14. 建立工作流自评与自优化流程（类似 `/meta-optimize`）。

## 九、可直接借鉴的具体仓库

| 想要的能力 | 建议直接参考 |
| --- | --- |
| claim / exploration / evidence / code stub 结构 + 六维 rigor 评分 | Orchestra-Research/AI-Research-SKILLs 的 ARA 三件套 |
| 全链路 skill 命名与跨模型“只驱动不开释”约束 | wanshuiyin/ARIS |
| 人在环 pipeline、run ledger、风险登记、治理与数据流文档 | Imbad0202/academic-research-skills |
| 想法 pilot 筛选与自动实验循环 | ARIS Workflow 1 / 1.5 / 2 |
| 跨会话证明战役 | ARIS proof-orchestrator |
| 机器可读、可复现优先的 artifact | AmberLJC/ara-paperbench |
| 本地可追溯工作台与 `.science` 包 | aipoch/open-science |
| 顶会方法学条目 | NeurIPS Paper Checklist、ARR Responsible NLP Checklist、ACM Artifact Badging |

## 十、一句话总结

你的工作流在“证据与 gate 的严谨性”上已经超过多数开源科研 agent，但在“想法筛选、探索记忆、算力接入、对抗评审、投稿后链路、方法学 checklist 落地”这六块上落后于 ARIS、AI-Research-SKILLs 和 academic-research-skills 这类成熟系统。

下一步不是继续加固 gate，而是把闭环补上：让 claim 成为中心对象、让探索与失败被记录、让评审真正对抗、让投稿后的链路也有产出物契约。
