# 对标仓库参考审计

日期：2026-10-05

问题：这些 GitHub 项目在实现前参考了吗？

诚实回答：**之前没有逐仓库读取源码。** 之前的升级是基于
`docs/research-workflow-benchmark-2026-10-05.md` 对这些项目的摘要，采取的是
概念对齐和本地契约设计，不是源码级复刻。本文补做代码级参考核对。

参考快照：

| 项目 | 实际仓库 | commit |
| --- | --- | --- |
| AI-Research-SKILLs | `Orchestra-Research/AI-Research-SKILLs` | `773a52944ba4747a18bd4ae9ade53fff041adcbc` |
| academic-research-skills | `Imbad0202/academic-research-skills` | `6ab4b03bf70a118a1b3ee7f3263ed9f19031061b` |
| ARA paperbench | `AmberLJC/ara-paperbench` | `62e9b54b2d4efe45b97f25676a16784530dd552a` |
| open-science | `aipoch/open-science` | `e4ba390f9f797800b06aa70c5ccae51a956f4baf` |
| ARIS | `wanshuiyin/Auto-claude-code-research-in-sleep` | `2132036060e03e8d0df69a4b21e5971819c0c2d6` |

路径差异：报告里的 `wanshuiyin/ARIS` 当前不存在。实际对应项目名是
`wanshuiyin/Auto-claude-code-research-in-sleep`。

本轮状态：AI-Research-SKILLs 的 `research-state.yaml` 已完成第一切片；
ARA 五层目录已通过 `tools/ccfa/ara_compile.py` 完成 draft compiler 第二切片；
ARIS proof run-directory + notation/derivation gate 已完成第三切片；
ARIS typed graph wiki 已完成第四切片；academic-research-skills 的
hash-chained run ledger 已完成第五切片；ARIS auto-review-loop state 已完成
第六切片；academic-research-skills risk capability matrix 与 data flows 已完成
第七切片；open-science immutable artifact store 与 `.science` package 已完成
第八切片；ARIS resubmit/talk pipeline guardrails 已完成第九切片。其余来源仍
按下表分级；academic-research-skills passport ledger 与 citation calibration
已完成第十切片；NeurIPS/ARR 官方 checklist fixture 已完成第十一切片；
open-science session replay 已完成第十二切片。

## 1. AI-Research-SKILLs

实际参考到的结构：

- `0-autoresearch-skill/SKILL.md` 明确使用 two-loop architecture。
- `0-autoresearch-skill/templates/research-state.yaml` 单独保存 literature、
  hypotheses、experiments、outer_loop、workspace。
- inner loop 有协议先行、运行、sanity check、metric、记录、保留或回退步骤。
- outer loop 有 deepen、broaden、pivot、conclude 四类方向决策。
- `findings.md` 是跨会话项目记忆，不只是日志。
- `22-agent-native-research-artifact/` 有 compiler、research-manager、
  rigor-reviewer 三件套。

我们的实现：

- `experiment-loop.yaml` 已覆盖 pilot、inner loop、outer loop 和 next action。
- `research-state.yaml` 已对齐 project/literature/hypotheses/experiments/
  outer_loop/workspace，并把 trajectory 的 run_id 与真实 run-log 绑定。
- 已有 `ara_compile.py` 生成 `logic/`、`src/`、`evidence/`、`trace/` draft；
  `ara-input/` 可提供 problem、concepts、solution、related_work、
  experiments、configs、trace、evidence 与 code stubs，从而生成完整 ARA 并
  通过 Seal Level 1；没有输入时仍为 draft gap。
- 仍没有自动从 PDF/仓库抽取这些语义层的 compiler 前端。
- 没有强制 `/loop` 或 heartbeat 式 wall-clock continuation。

结论：**two-loop 概念已吸收，项目级 research-state 已完成第一切片；
ARA 目录 contract 已完成 draft compiler，code stub 和完整语义提取尚未复刻。**

## 2. ARIS

实际参考到的结构：

- `skills/proof-orchestrator/SKILL.md` 使用 run directory：
  `task.md`、`materials.md`、`local-proof.md`、`sources/`、
  `source-manifest.md`、`browser-prompt.md`、`handoff.md`、
  `gpt-pro-output.md`、`audit.md`、`final.md`、`codex-ledger.md`。
- 有 `LOCAL_ATTEMPT`、`LOCAL_PROVED`、`LOCAL_BLOCKED`、
  `READY_FOR_MANUAL_GPT_PRO`、`AUDIT_FAILED` 等状态标签。
- 有 notation gate、derivation structure gate、manual GPT Pro handoff contract。
- `skills/auto-review-loop/SKILL.md` 是 review → fix → re-review 循环，
  reviewer memory、threadId、round state、human checkpoint、difficulty 都可配置。
- `skills/meta-optimize/SKILL.md` 分析 usage logs、失败、收敛、人工干预、
  trigger rate、bottleneck succession，并且是 read-only producer，单独由
  human-invoked apply skill 落地修改。
- `skills/research-wiki/SKILL.md` 有 paper/idea/experiment/claim 四类节点和
  `graph/edges.jsonl` 类型化关系。
- `docs/RESUBMIT_AND_TALK.md` 有 resubmit 的物理隔离、匿名检查、soft-only
  audit、whitelist microedit、adversarial gate，以及 talk 的生成和 polish 流程。

我们的实现：

- `proof_orchestrator.py` 已记录 campaign、attempt、failure、next action，并把
  `proved` 绑定到真人 verified proof-audit。
- `proof_run.py` 已提供 run directory 文件契约、status、notation scorecard
  与 top-down derivation gate；manual GPT Pro handoff 仍是骨架，不会自动执行。
- `review_loop.py` 已提供 round state、reviewer memory 和 append-only
  acquittal log；自动修稿和模型驱动的 fix/re-review 尚未实现。
- `meta_optimize.py` 已做聚合候选，但没有 bottleneck succession、trigger-rate
  evaluation、proposal IDs 或独立 apply gate。
- `research_wiki.py` 已有 paper/idea/experiment/claim/gap kinds、
  `graph/edges.jsonl` 八类 typed edges、`add-edge`、`query-pack`，
  以及 BibTeX `sync`、`index.md`/`gap_map.md` rebuild 和 append-only `log.md`。
- `post_submission.py` 只校验产出物契约，没有真正执行 resubmit 的物理隔离、
  匿名清点、edit whitelist 和 adversarial gate。

结论：**proof/next action、meta-optimize、post-submission 已吸收；
proof run-directory、typed graph wiki、review loop state、resubmit/talk
guardrails 和注入式自动 fix/re-review 已对齐。**

## 3. academic-research-skills

实际参考到的结构：

- README 明确 human-in-the-loop，AI 是 copilot，不是 pilot。
- `shared/contracts/passport/run_ledger.schema.json` 是 append-only、
  hash-chained run ledger，保存初始指令、checkpoint、用户原话、工具回执、
  progress counters 和 transient file fingerprints。
- `docs/RISK_REGISTER.md` 把风险、控制、证据状态和残余缺口放在一张表里，
  并由 `check_risk_register.py` 校验。
- `docs/DATA_FLOWS.md` 逐项列出网络触点、发送内容、凭据、关掉方式和本地存储。
- README 还明确 claim-source alignment、citation calibration、实验 provenance
  intake 和“检查不能证明程序真的执行过”的边界。

我们的实现：

- `docs/autonomy-policy.md` 已明确人在环边界。
- `run_log.py` 有每次实验的配置、种子、commit、退出码和指标。
- `risk-register.yaml` 有风险、severity、mitigation、evidence、status。
- `governance.py` 有 COI、伦理、许可、AI 使用、查重和披露。

缺口：

- 已有 `run_ledger.py` 的 hash-chained append-only peer ledger；但仍没有保存
  checkpoint 问题、用户原话和 initial instructions 的完整 ARS passport ledger。
- `governance_map.py` 已实现 risk → control → evidence status → residual gap
  和 `DATA_FLOWS.md` 生成；完整 ARS passport 与 calibration 仍未完成。
- Citation semantic support 仍是人工台账，没有 FNR/FPR calibration gold set。

结论：**人在环、hash-chain run ledger、完整 passport ledger、citation
calibration、risk capability matrix、data-flow map、governance 已吸收；
仍未在本机用真实 gold set 跑出 live calibration 数据。**

## 4. ARA paperbench

实际参考到的结构：

- 每个 artifact 固定五层：`PAPER.md`、`logic/`、`src/`、`evidence/`、
  `trace/`。
- `logic/claims.md` 每条 claim 有 statement、status、falsification criteria、
  proof/evidence pointers。
- `trace/exploration_tree.yaml` 是 question、experiment、dead_end、decision、
  pivot 的 DAG，dead end 必须记录 hypothesis、failure_mode、lesson。
- `evidence/` 的 figures/tables 通过 README 和 claim pointers 绑定。
- `src/` 是可运行代码、environment、configs；`rubric/requirements.md`
  是专家复现 rubric。

我们的实现：

- `claim-registry.yaml` 已有 statement、type、status、proof、experiments、
  figures、citations、assumptions、limitations。
- `exploration-graph.yaml` 已有 pivot、dead-end、rejected、active，并绑定
  claim 与 run。
- `figures/manifest.yaml` 有字节和来源绑定，但语义支持仍靠人工台账。

缺口：

- 没有 `logic/` 的 concepts、problem、related_work、solution
  algorithm/architecture/constraints/heuristics 分文件结构。
- 没有 claim-to-code-stub 字段，也没有 `src/environment.md` 这种代码层契约。
- exploration graph 是平铺 entries，不是带 `also_depends_on` 的完整 DAG。
- 没有专家 rubric 级别的逐 leaf requirements。

结论：**claim、exploration、evidence 三层已部分对齐；code stub、完整 DAG
和 expert rubric 仍未对齐。**

## 5. open-science

实际参考到的结构：

- `.science` portable research package，包含对话分支、文件版本、Notebook
  records 和 verification evidence。
- 每个 artifact 是不可变、带校验和的版本；Provenance 暴露 producer code、
  inputs、execution history、环境 inventory、conversation branch 和 reviewer findings。
- Reviewer 在独立 context 检查 turn response、execution logs 和 file evidence。
- 本地-first，模型和 agent backend 可替换；权限、网络触点和敏感数据边界有说明。

我们的实现：

- `provenance.json`、`artifact-provenance.yaml`、run-log、repro bundle 已有。
- `artifact_store.py` 已有内容寻址 immutable version、完整性验证、replay 和
  `.science` zip；`session_replay.py` 已串联 passport、run ledger、artifact
  store 和 review state 生成静态 replay。
- app workbench 有聊天、工具桥和自定义 HTTP tools。
- GitHub private repo、CI 和 release workflow 已有。

缺口：

- 没有完整 artifact-level producer code、execution history、environment
  inventory 的全链 provenance graph。
- 没有独立 context 的 turn-level reviewer。

结论：**provenance、本地工作台、immutable artifacts、`.science` package 和
只读 session replay 已吸收；桌面工作台级 execution graph 交互仍可扩展。**

## 6. 官方方法学来源

我们的现状：

- `venue-checklist.yaml` 是通用 schema，支持状态和 evidence。
- `artifact_badge.py` 已对齐 ACM Available/Evaluated/Reusable 三档。
- `rigor.py` 已实现六维 0..4 评分和真人/模型边界。
- `checklists/neurips-paper-checklist.yaml` 与
  `checklists/arr-responsible-nlp.yaml` 已提供可校验、可 seed 的 fixture。

缺口：

- 已固化的是 adapted structure，不是逐字官方文本；使用前仍需核对 venue 当年
  版本。
- 其他 venue 的 checklist fixture 尚未补齐。
- ACM badge 有校验契约，但没有真实 DOI、第三方 evaluated、第三方 reusable。

结论：**方法学 gate 的机械契约已有；官方 checklist 内容和外部归档证据未完成。**

## 7. 总体判定

真实参考状态应写成：

| 来源 | 是否参考过源码 | 我们对齐的程度 |
| --- | --- | --- |
| AI-Research-SKILLs | 本轮补查 | two-loop、research-state、ARA draft/full compiler contract 已对齐；自动语义提取前端仍缺 |
| ARIS | 本轮补查 | proof run-dir + proof gates、typed graph wiki、review loop、注入式 fix/re-review、resubmit/talk guardrails 已对齐 |
| academic-research-skills | 本轮补查 | human-in-loop、hash-chained run ledger、完整 passport ledger、risk capability matrix、data-flow map、citation calibration 工具已对齐；live calibration 数据未产生 |
| ARA paperbench | 本轮补查 | claim/exploration/evidence/code stub/DAG contract 已对齐；expert rubric 与自动抽取前端未完成 |
| open-science | 本轮补查 | provenance/workbench、immutable artifacts、`.science` package、只读 session replay 已对齐；GUI 级 execution graph 未实现 |
| NeurIPS/ARR/ACM | 本轮核对公开结构 | ACM badge、NeurIPS/ARR adapted fixtures 已实现；逐字官方版本与其他 venue fixture 未完成 |

此前说“参考了这些项目”只能成立为：

> 参考了报告对这些项目的结构化摘要，并按相同方向设计了本地实现。

本轮已经实际读取源码并完成可确定性契约对齐，但仍不能成立为：

> 逐字等价复刻了这些系统的全部语义抽取、GUI 交互和外部验证能力。

下一步若继续升级，优先级最高的仍是：

1. 继续补齐 AI-Research-SKILLs 的自动 ARA 语义提取前端；本地
   `ara-input/` 到完整 Seal-valid ARA 的 compiler contract 已完成。
2. ARIS 的 review loop、fix/re-review runner、proof run directory、
   notation/derivation gate、typed graph wiki、resubmit/talk guardrails 已完成。
3. 用真实 citation gold set 产生 live FNR/FPR 证据；passport ledger、
   risk matrix、data flows、hash-chain 已完成。
4. 把 open-science 的 execution graph 与 session replay 接入 GUI workbench；
   命令行 replay 已完成。

这些才是“真正参考源码后”的下一轮工作，不是继续增加抽象 gate。
