# 参考审计：Modex-MH-Agent 的工作流设计

日期：2026-10-06
对象：本机安装的 Modex-MH-Agent 1.6.5（明珩科技，MIT，Electron + FastAPI）
方法：直接读安装目录里的明文资产，不依赖官网或二手介绍

## 阅读边界（先说清楚）

读到的：

- `resources/app/backend/db/schema.sql`（工作流数据模型）
- `resources/app/templates/*.md`（9 份流程模板全文）
- `resources/app/backend/main.py`、`routers/`、`services/` 的文件清单与依赖
- `resources/app/skills/**` 的目录名与明文附件（LaTeX 模板、字体、样式档、示例 drawio、check 脚本清单）
- `runtime/`（捆绑的 python / git / node / pandoc / miktex / draw.io）

没读到的：`skills/**/SKILL.md.enc` 是密文，运行时由
`backend/services/skill_crypto.cp311-win_amd64.pyd` 解密，密钥来自其授权服务。
我没有绕过它，所以**技能正文未读**。下面关于流水线顺序的结论来自技能目录名、
模板里的交叉引用和 README，属于高置信推断，不是逐字引用。

## 一、它的工作流骨架

### 1. 状态模型（`schema.sql`）

```text
workflows       id, template, params, status, current_step,
                workspace_dir, enable_checkpoints
workflow_steps  skill_name, display_name, step_order, status,
                has_checkpoint, checkpoint_type, output_files
workflow_logs   step_name, level, message
checkpoints     step_name, checkpoint_type, data, response, status
```

- `workflows.template`：`idea_discovery | experiment_bridge | auto_review |
  paper_writing | full_pipeline | thesis_proposal | literature_review | ...`
- `workflows.params`：`AUTO_PROCEED`、`HUMAN_CHECKPOINT` 这类自主度开关
- `workflow_steps.status`：`pending | running | waiting_checkpoint | completed |
  failed | skipped`，并记录该步骤产出的 `output_files`
- `checkpoints.checkpoint_type`：`idea_select | approve | feedback`；
  存“展示给用户的数据”和“用户的回复”，状态只有 `pending | resolved`

值得注意的设计判断：他们把“人需要回答什么”建模成一等对象，而不是
“某个台账文件里写着 pending”。工作流可以停在 `waiting_checkpoint`，
恢复时能拿到当时展示给用户的那份数据。

### 2. 模板即接口（`templates/`）

每个阶段都有一份“写好了就能跑”的输入文档，且每份模板开头都写明
为什么需要这个文件，以及它和其它文件的边界：

| 模板 | 作用 | 关键规则 |
| --- | --- | --- |
| RESEARCH_BRIEF | 输入：研究方向 | 含 Compute / Timeline / Non-Goals |
| RESEARCH_CONTRACT | 当前 idea 的聚焦上下文 | 明确写“避免把 8-12 个候选全塞进上下文”，会话恢复只读这一份 |
| IDEA_CANDIDATES | 幸存想法 + Killed Ideas + Idea Switch Log | 当前想法失败时从候选池取下一个，而不是重跑全流程 |
| EXPERIMENT_PLAN | claim map + 实验块 | 每块必须有 success criterion 与 failure interpretation |
| EXPERIMENT_LOG | 永久实验记录 | 更新规则：实验结束立刻写，禁止攒批 |
| FINDINGS | 研究发现 + 工程发现 | 会话恢复必读 |
| PAPER_PLAN / NARRATIVE_REPORT | 写作输入 | claims-evidence 矩阵、图表计划 |

### 3. 流水线（由目录名与模板交叉推断）

```text
idea-discovery → novelty-check → research-refine(research contract)
→ experiment-plan / experiment-bridge → run-experiment / training-check
→ ablation-planner / monitor-experiment → analyze-results → result-to-claim
→ paper-plan → paper-write(zh/en/docx/nature) → paper-figure/illustration
→ paper-compile → auto-review-loop(+llm/minimax) → quality-check
→ rebuttal → paper-slides / paper-poster
```

外加 `research-pipeline` 作为编排入口，`dse-loop`、`auto-paper-improvement-loop`
做自我改进，`proof-writer`、`grant-proposal`、`thesis-proposal` 覆盖旁支。

### 4. 两套运行时与自举环境

- `skills-codex` 与 `skills-codex-claude-review` 是同一套流程的两份运行时副本，
  第二份专门给另一个模型跑评审。
- `runtime/` 捆绑 python 3.11、git、node + claude CLI、pandoc、miktex/texlive、
  draw.io；`tools/` 里是确定性检查脚本（paper_data_check、facts_audit、
  figure_check、drawio_check、tikz_check、leakage_audit、delivery_audit、watchdog）。
- 状态存在 SQLite，不进 git。

## 二、与我们工作流的对照

| 维度 | Modex-MH-Agent | 我们 | 判定 |
| --- | --- | --- | --- |
| 状态存储 | SQLite，工作流/步骤表 | `ccfa.yaml` + stage history，在 git 里 | 我们更可审计、可回滚、可 diff |
| 步骤产物 | `output_files` 列表 | run-log + manifest + artifact-provenance + 图 manifest（带哈希） | 我们更强 |
| 人类决定 | `checkpoints`：类型 + 展示数据 + 回复 | 各审计台账 `status: pending-human-*`，readiness 只给 key 列表 | 他们更完整，本次采纳 |
| 上下文纪律 | RESEARCH_CONTRACT：只装载当前想法 | ccfa.yaml + readiness.md + data/* | 他们更聚焦，值得写进纪律 |
| 实验计划 | claim map + success criterion + failure interpretation + run order 决策门 + GPU 预算 | `data/experiment-loop.yaml` 已要求 pilot 预算/metric/kill criterion + 内外层决策 | 已覆盖，且更严 |
| 想法池与死路 | IDEA_CANDIDATES + Killed Ideas + Switch Log | `data/exploration-graph.yaml` + experiment-loop ideas[] + memory | 已覆盖 |
| 发现记录 | FINDINGS（研究+工程） | run-log + friction-log + research-state.workspace.findings | 已覆盖但分散 |
| 自主度 | `AUTO_PROCEED` / `HUMAN_CHECKPOINT` | `workflow.profile` + `docs/autonomy-policy.md` | 等价 |
| 跨模型评审 | 两份技能包，同流程不同模型 | `cross_review` 要求跨 family，否则 override 留痕 | 我们更严格 |
| 交付环境 | 捆绑全部运行时 | 依赖系统 PATH，doctor 探测 | 他们更开箱即用 |
| 可审计性 | 技能正文加密，规则不可读 | 全部规则在仓库里，可被测试钉住 | 我们更可审计 |

## 三、采纳 / 已有 / 拒绝

### 采纳

1. 人工作为 checkpoint 记录形状（本次落地）：每条待人工项给出
   `type`、`stage`、`question`、`answer_with`、`ledger`、`status`，
   让“待人工”从 key 列表变成可回答的问题。
   实现：`tools/ccfa/readiness.py` 的 `human_review.checkpoints`，
   写入 `reviews/readiness.md` 的 Human Checkpoints 段。
2. 会话恢复只装载聚焦上下文：写进操作手册，不新增文件。

### 已有，不重复建设

- claim registry、假设/局限、探索图、成本账本、风险登记册、实验循环、复现环境、
  artifact badge 等 21 类台账。
- 失败演练（`data/gate-failure-drills.yaml`）比他们的 `check` 脚本更严。

### 拒绝

1. 把工作流状态搬进 SQLite：会让回滚、代码评审和 `git bisect` 全部失效；
   我们的“论文目录是独立 git 仓库”是更重要的性质。
2. 加密技能包：规则不可读就无法被测试和审计，与 fail-closed 原则冲突。
3. 再加一套 skill 目录结构：他们是给消费者装的一体化应用，我们是可测工具链 + 桌面壳，
   复制目录结构只会增加维护面。

## 四、本次落地的具体改动

`readiness` 的 `human_review` 字段从：

```json
{"status": "pending-human-review", "pending": ["proof", "human-coding"]}
```

变成（`pending` 保留，向后兼容）：

```json
{
  "status": "pending-human-review",
  "pending": ["proof", "human-coding"],
  "checkpoints": [
    {
      "id": "proof",
      "type": "approve",
      "stage": "internal-review",
      "status": "pending",
      "question": "主证明逐行成立吗？每一步推理与所依赖的假设是否都站得住？",
      "answer_with": "写 reviewer、结论与复核证据路径",
      "ledger": "data/proof-audit.yaml"
    }
  ]
}
```

`reviews/readiness.md` 相应多一段 `## Human Checkpoints`。

## 五、还没做、但值得排期的

1. 桌面工作台显示 checkpoint：详情区加“待人工”面板，读
   `readiness.human_review.checkpoints`，让 app 不只是跑 validate/milestones。
2. 捆绑运行时的取舍：他们用 `runtime/` 自带 python/texlive 换开箱即用；
   我们的安装包目前依赖系统环境 + doctor。若要做“给不会配环境的合作者用”的版本，
   这是必选项；自用版本不急。
3. 步骤级 output_files：把“这个 stage 产出了哪些文件”写进 stage history，
   让 `readiness` 能直接回答“这步的产物在哪”，而不只是“文件在不在”。
