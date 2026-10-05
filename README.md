# 一站式科研工作流

面向个人科研的本地论文工作流。每篇论文从 venue 模板派生为独立 git 仓库，
状态、检查、证据和归档都以确定性脚本与结构化账本为准。

## 从这里开始

| 你现在要做的事 | 阅读或执行 |
| --- | --- |
| 第一次安装 | 本页「从零搭建」，然后运行 `scripts/doctor.ps1` |
| 创建或继续一篇论文 | `docs/workflow-guide.md` |
| 查看所有论文的阶段、阻塞与下一动作 | `scripts/dashboard.ps1` |
| 接入 GitHub 私有仓库、CI 和 release | `docs/github-setup.md` |
| 了解产品能力和不能保证什么 | `docs/research-workflow-intro.md` |
| 查看哪些步骤可自动、哪些必须人类批准 | `docs/autonomy-policy.md` |
| 查一个具体 CLI | 本页「工具一览」或运行 `scripts/<tool>.ps1 --help` |
| 查看会议/期刊 gate | `checklists/conference.md` / `checklists/journal.md` |
| 理解架构与判定契约 | `docs/design/2026-10-03-research-workflow-design.md` |
| 追溯实施与评审历史 | `docs/sdd/2026-10-03-evidence-tracking-progress.md` |

日常使用只记住这一条循环：

```text
读状态 -> 处理当前 gate -> 定向检查 -> 人工复核 -> 提交论文仓库 -> 推进阶段
```

最常用的三个命令：

```powershell
$paper = "papers/my-paper"
scripts/milestones.ps1 stage --paper-root $paper
scripts/readiness.ps1 --paper-root $paper --out reviews/readiness.md
scripts/milestones.ps1 due --paper-root $paper
git -C $paper status --short
```

不要一开始运行全部工具，也不要为了让检查全绿而填写虚假的占位账本。

## 目录约定

| 路径 | 用途 |
| --- | --- |
| `ccfa.yaml.template` | 新项目状态文件模板 |
| `checklists/` | gate 清单，由 `tools/newpaper/checklists.py` 从 `tools/ccfa/stages.py` 生成 |
| `docs/` | 设计文档、实施计划、裁定账本与研究评估的正式留档 |
| `docs/workflow-guide.md` | 面向研究者的日常操作手册和逐阶段命令 |
| `library/` | 共享 BibTeX 与 PDF 原件 |
| `library/refs.bib` | 共享 BibTeX 条目；派生项目时复制为 `manuscript/references.bib` |
| `library/wiki/` | 跨项目研究记忆卡片；支持确定性索引与本地搜索 |
| `papers/<slug>/` | 派生论文项目的默认目标目录，已在 `.gitignore` 中忽略 |
| `scripts/` | 所有确定性 CLI 的 PowerShell 包装器 |
| `tools/` | 确定性工具与项目测试 |
| `automation/` | 四类本地自动化 prompt 与接线说明 |

## 工具一览

`tools/ccfa/` 下的每个 CLI 模块和 `newpaper.create` 都有对应的 `scripts/*.ps1` 入口，后者对应 `tools/newpaper/create.py`。包装器统一从仓库根设置 `PYTHONPATH`，调用 `tools/.venv/Scripts/python.exe`，并原样透传退出码、stdout 与 stderr。

| 模块 | 一句话作用 | PowerShell 入口 |
| --- | --- | --- |
| `tools/newpaper/create.py` | 按 venue、年份、会议或期刊模式派生完整论文目录 | `scripts/new-paper.ps1` |
| `tools/ccfa/citation_guard.py` | 检查引用台账、DOI 存在性与正文悬空引用 | `scripts/citation-guard.ps1` |
| `tools/ccfa/trace_claims.py` | 将正文数字标记与 JSON、CSV、YAML 源值机械比对；`--manuscript` 可一次扫描目录下全部 `.tex` | `scripts/trace-claims.ps1` |
| `tools/ccfa/latex_check.py` | 检查 LaTeX 结构、引用、图片，并可按 `--main` 指定主文件编译 | `scripts/latex-check.ps1` |
| `tools/ccfa/final_check.py` | 对终稿执行未解析标记、图表与声明完整性检查 | `scripts/final-check.ps1` |
| `tools/ccfa/revision_ledger.py` | 检查审稿意见矩阵的七列契约与承诺风险一致性 | `scripts/revision-ledger.ps1` |
| `tools/ccfa/provenance.py` | 登记数据来源、分类与校验和，并可导出人读来源文档 | `scripts/provenance.ps1` |
| `tools/ccfa/run_log.py` | 记录每次运行的配置、种子、commit、退出码与指标 | `scripts/run-log.ps1` |
| `tools/ccfa/run_ledger.py` | 在 run-log 旁维护 append-only、hash-chained peer ledger，检测缺失、篡改、链断与记录更新 | `scripts/run-ledger.ps1` |
| `tools/ccfa/passport_ledger.py` | 保存 initial instructions、checkpoint、tool receipt、file reference 等 handoff-critical 事件的 hash chain | `scripts/passport-ledger.ps1` |
| `tools/ccfa/citation_calibration.py` | 从 gold set 与预测计算 citation support 的 FNR/FPR 并按阈值 fail closed | `scripts/citation-calibration.ps1` |
| `tools/ccfa/venue_fixtures.py` | 校验并 seed NeurIPS/ARR 官方方法学 checklist fixture 到 `venue-checklist.yaml` | `scripts/venue-fixtures.ps1` |
| `tools/ccfa/repro_package.py` | 打包复现材料并在干净环境验证重跑 | `scripts/repro-package.ps1` |
| `tools/ccfa/friction_log.py` | 记录工具缺陷与指令缺口，支持跨论文聚合 | `scripts/friction-log.ps1` |
| `tools/ccfa/research_version.py` | 用 git tag 建立自动编号快照并输出任意两版 diff | `scripts/research-version.ps1` |
| `tools/ccfa/library.py` | 索引和全文检索共享文献库 | `scripts/library.ps1` |
| `tools/ccfa/memory.py` | 管理选题记忆与反重复 dead-end 记录 | `scripts/memory.ps1` |
| `tools/ccfa/milestones.py` | 读取 stage 并检查投稿倒排 checkpoint 与 gate 缺口 | `scripts/milestones.ps1` |
| `tools/ccfa/cross_review.py` | 运行和检查跨模型评审矩阵；`run --model` 必填，同族评审即使 override 也不能开释为 pass；记录绑定输入哈希、指令摘要与真实 provider provenance | `scripts/cross-review.ps1` |
| `tools/ccfa/review_loop.py` | 维护多轮 review loop、reviewer memory、append-only acquittal log，并可注入 fix/review 命令自动驱动轮次 | `scripts/review-loop.ps1` |
| `tools/ccfa/argument_audit.py` | 审计人工证明复核、引用语义支持与图表语义支持台账，阻断未复核的论证 | `scripts/argument-audit.ps1` |
| `tools/ccfa/human_coding.py` | 计算两名人类编码者的一致率、Cohen's kappa 与置信区间 | `scripts/human-coding.ps1` |
| `tools/ccfa/novelty.py` | 检查检索范围、最近邻工作与逐 claim 差异，阻断未支撑的新颖性表述 | `scripts/novelty.ps1` |
| `tools/ccfa/stats_plan.py` | 检查预注册统计设计：alpha、功效、样本量、多重比较、停止规则与缺失数据处理 | `scripts/statistics.ps1` |
| `tools/ccfa/governance.py` | 检查署名/贡献、利益冲突、伦理与许可、AI 使用、查重、双用途与负责任披露 | `scripts/governance.ps1` |
| `tools/ccfa/governance_map.py` | 校验 risk→control→evidence status→residual gap，以及 machine-readable data flows 和明文凭据 | `scripts/governance-map.ps1` |
| `tools/ccfa/repro_env.py` | 检查 requirements、lockfile 哈希、系统工具版本与证据 | `scripts/repro-env.ps1` |
| `tools/ccfa/watch.py` | 增量扫描外部文献源，只报告未见过的 ID | `scripts/watch.ps1` |
| `tools/ccfa/queue.py` | 顺序运行实验队列并执行预算、重试与失败停止规则 | `scripts/queue.ps1` |
| `tools/ccfa/validate.py` | 校验 `ccfa.yaml` 的结构、stage 与 gate 状态 | `scripts/validate.ps1` |
| `tools/ccfa/state.py` | 写回 stage/gate/updated_at，并追加 advance/rollback 审计记录 | `scripts/state.ps1` |
| `tools/ccfa/stages.py` | stage/gate 状态机的唯一来源；CLI 把整表以 JSON 输出，供工作台等外部消费者读取而不必 import `ccfa` | `scripts/stages.ps1` |
| `tools/ccfa/doctor.py` | 预检本地平台依赖（git/LaTeX/codex/Docker/GPU/venv/交付格式/排版/数据版本/算力），报告缺什么与禁用了哪个能力；`found` 只表示在 PATH 上，不表示命令一定跑得通 | `scripts/doctor.ps1` |
| `tools/ccfa/readiness.py` | 生成一页式 readiness report，执行 profile 对应的 gate，并区分结构、证据存在、gate 通过、独立复核与科学接受 | `scripts/readiness.ps1` |
| `tools/ccfa/dashboard.py` | 扫描 `papers/`，汇总每篇论文的 readiness、阻塞项、人工待办、Git/CI 状态与下一动作 | `scripts/dashboard.ps1` |
| `tools/ccfa/formal_check.py` | 运行论文声明的 Z3/形式化检查，验证机器输出并写入 `reviews/formal-check.json` | `scripts/formal-check.ps1` |
| `tools/ccfa/verifiers.py` | 清点本机可用的形式化验证器（z3/cvc5/lean/coq/isabelle/agda/why3/sage/julia），对照 `data/formal-checks.yaml` 说明缺哪个、禁用了哪个能力、如何安装 | `scripts/verifiers.ps1` |
| `tools/ccfa/research_state.py` | 对齐 AI-Research-SKILLs 的项目级 research-state：literature、hypotheses、experiments trajectory、outer loop 与 workspace | `scripts/research-state.ps1` |
| `tools/ccfa/ara_compile.py` | 从 claim、exploration、figure、run 台账编译 ARA 五层 draft，并如实报告未满足的 Seal Level 1 项 | `scripts/ara-compile.ps1` |
| `tools/ccfa/research_ledgers.py` | 校验 claim registry、assumptions/limitations、venue checklist、artifact provenance、探索图、成本账本与风险登记册 | `scripts/research-ledgers.ps1` |
| `tools/ccfa/experiment_loop.py` | 校验 pilot 筛选与内层/外层实验循环，绑定真实 claim 与 run id，并输出下一批待办动作 | `scripts/experiment-loop.ps1` |
| `tools/ccfa/post_submission.py` | 校验 rebuttal 回复矩阵、resubmit venue 差异与 talk 大纲的产出物契约 | `scripts/post-submission.ps1` |
| `tools/ccfa/resubmit_pipeline.py` | 校验 resubmit 物理隔离、bib 冻结、无新增 run、匿名泄漏与 forbidden path | `scripts/resubmit-pipeline.ps1` |
| `tools/ccfa/talk_pipeline.py` | 校验 conference talk 的 slide、claim/figure 复用、speaker notes 与 Q&A | `scripts/talk-pipeline.ps1` |
| `tools/ccfa/rigor.py` | 校验六维 rigor rubric 的评分、证据引用与“模型只能 advisory、不能开释”边界 | `scripts/rigor-rubric.ps1` |
| `tools/ccfa/proof_orchestrator.py` | 记录跨会话 proof campaign、失败尝试、阻塞点与下一步，并把 proved 绑定到真人 verified 证明复核 | `scripts/proof-orchestrator.ps1` |
| `tools/ccfa/proof_run.py` | 按 ARIS 结构创建 proof run directory，校验 status、notation scorecard 与 top-down derivation gate | `scripts/proof-run.ps1` |
| `tools/ccfa/meta_optimize.py` | 聚合 friction store 与 readiness gate 失败，输出人类审批用的候选工作流改进 | `scripts/meta-optimize.ps1` |
| `tools/ccfa/artifact_badge.py` | 校验 ACM available/evaluated/reusable badge、第三方复核、reuse 记录与 DOI/归档证据 | `scripts/artifact-badge.ps1` |
| `tools/ccfa/artifact_store.py` | 内容寻址的 immutable artifact store、完整性验证、provenance replay 与 `.science` 打包 | `scripts/artifact-store.ps1` |
| `tools/ccfa/session_replay.py` | 串联 passport、run ledger、artifact store 与 review state，生成只读 session replay HTML | `scripts/session-replay.ps1` |
| `tools/ccfa/research_wiki.py` | 校验跨项目 Markdown wiki、typed graph edges；支持 BibTeX sync、catalog/gap map 重建、搜索和 query pack | `scripts/research-wiki.ps1` |
| `tools/ccfa/test_impact.py` | 按 git diff 选择最小相关测试集；未知路径或共享核心模块自动回退全量测试 | `scripts/test-impact.ps1` |
| `tools/ccfa/archive_client.py` | Zenodo/OSF/ORCID 归档薄客户端；内置 DNS-over-HTTPS 绕行，只有拿到 DOI 才报告 published | `scripts/archive.ps1` |
| `tools/ccfa/compute.py` | 探测本机 CPU/内存/GPU/Docker 与远程 Slurm/PBS 后端，在墙钟预算内执行 pilot 并记录 `wall_seconds`/`gpu_minutes` | `scripts/compute.ps1` |

## 阶段到命令速查

`ccfa.yaml` 的 `stage.current` 以 `tools/ccfa/stages.py` 为唯一状态机。会议模式在 `submitted` 后进入 `rebuttal`、`camera-ready`、`archived`；期刊模式进入 `major-revision`、`response-letter`、`resubmitted`、`accepted`、`archived`。

| `ccfa.yaml` stage 或用途 | 命令 | 说明 |
| --- | --- | --- |
| 任意阶段的状态校验 | `scripts/validate.ps1` | 校验状态文件结构与 stage/gate 合法性 |
| 任意阶段（开始前） | `scripts/doctor.ps1` | 预检平台依赖；默认只把必需的 `git` 缺失判为 problem，`--strict` 把可选缺失也判为 problem；只有 Docker 会真正执行探测，daemon 不可达报 `doctor-daemon-down` |
| 任意阶段（开始前） | `scripts/readiness.ps1` | 生成一页式 readiness report；支持 `--profile minimal|standard|high-assurance`，输出结构、证据存在、`gate-verified`、人工复核、科学接受与协作就绪六个维度；任一下游 gate 失败都会使 `ready=false` |
| 任意阶段（claim 中心台账） | `scripts/research-ledgers.ps1` | 校验 claim→proof/experiment/figure/citation/assumption/limitation 的交叉引用，以及 venue checklist、artifact provenance、探索图、成本与风险台账 |
| 读取当前阶段 | `scripts/milestones.ps1` | 调用 `stage` 子命令输出 `current`、`gate`、`updated_at` |
| 投稿日期倒排 | `scripts/milestones.ps1` | 调用 `due` 子命令检查 T-90、T-60、T-30、T-21、T-14、T-7、T-3、T-1 与 gate 缺口；T-30 之后出现新实验运行会报 `t30-new-experiment`，只声明 `build` 但没写 `purpose_reason` 会报 `t30-unjustified-build-run` |
| `idea`、`grounded` | `scripts/library.ps1` | 索引和检索共享文献库，支撑近邻工作与新颖性核对 |
| `idea`、`grounded` | `scripts/memory.ps1` | 追加 idea 或 dead-end，检查是否重复 |
| `grounded` | `scripts/novelty.ps1` | 检查检索范围/日期、至少三个近邻与逐 claim 差异 |
| `data-ready` | `scripts/provenance.ps1` | 登记数据来源、分类、校验和并检查完整性 |
| `experiment-design` | `scripts/statistics.ps1` | 检查功效、样本量、多重比较校正、种子、停止规则与缺失数据处理 |
| `experiment-design`、`experiments-running` | `scripts/experiment-loop.ps1` | 校验 pilot 候选、kill criterion 与内外层实验循环，并输出下一批待办动作 |
| `experiment-design`、`experiments-running` | `scripts/run-log.ps1` | 记录运行事实、指标、退出码与失败结果；`check` 对脏树运行报 problem，只有 `--dirty-waiver` 写明 ≥20 字符的理由才降为 advisory |
| `experiment-design`、`experiments-running` | `scripts/queue.ps1` | 按队列顺序运行实验，预算或重试耗尽即停止 |
| `results-ready` | `scripts/trace-claims.ps1` | 核对 claim 数字与源数据值 |
| `writing`、`internal-review` | `scripts/citation-guard.ps1` | 检查引用可信性、DOI 与悬空引用 |
| `internal-review` | `scripts/cross-review.ps1` | 运行评审矩阵并检查 blocking 项；执行模型、provider 与 endpoint 哈希从 Codex 配置解析并写入 provenance；`check` 因输入变化报 `review-stale`，因评审指令变化报 `review-prompt-drift`，因 provider 配置变化报 `review-provider-config-drift` |
| `internal-review`、`submission-check` | `scripts/rigor-rubric.ps1` | 检查六维 rigor rubric 的真人/模型边界、0..4 评分、理由与 claim/run/file 证据引用 |
| `grounded`、`internal-review` | `scripts/proof-orchestrator.ps1` | 记录跨天证明尝试与下一步，检查 proved 是否绑定 proof-audit 的真人 verified 记录 |
| `results-ready`、`internal-review` | `scripts/argument-audit.ps1` | 检查人工证明复核、引用语义支持与图表语义支持台账；未复核即 problem |
| `experiment-design`、`results-ready` | `scripts/human-coding.ps1` | 对人工双编码表计算一致率与 Cohen's kappa 置信区间 |
| `writing`、`submission-check` | `scripts/latex-check.ps1` | 结构检查或编译；非默认主文件用 `--main` 指定 |
| `submission-check`、`camera-ready` | `scripts/final-check.ps1` | 对终稿或渲染 PDF 执行确定性检查 |
| `submission-check` | `scripts/governance.ps1` | 检查署名/贡献、COI、伦理与许可、AI 使用、查重、双用途与披露 |
| `submission-check` | `scripts/repro-env.ps1` | 检查 lockfile 哈希与系统工具版本证据 |
| `submission-check`、`archived` | `scripts/repro-package.ps1` | 生成复现包并实际重跑 |
| `rebuttal`、`major-revision`、`response-letter`、`resubmitted` | `scripts/post-submission.ps1` | 校验 rebuttal/resubmit/talk 合同，绑定真实 run id、claim 与 figure 台账 |
| `accepted`、`camera-ready`、`archived` | `scripts/artifact-badge.ps1` | 校验 artifact badge、独立复核、reuse 记录与 Zenodo/OSF DOI 归档 |
| 任意需要快照的阶段 | `scripts/research-version.ps1` | 建立版本 tag 或比较两版差异 |

常用命令：

```powershell
scripts/milestones.ps1 due --paper-root <paper-root>
scripts/milestones.ps1 stage --paper-root <paper-root>
scripts/readiness.ps1 --paper-root <paper-root> --out reviews/readiness.md
scripts/library.ps1 --dir <library-dir> search "keyword"
scripts/memory.ps1 --paper-root <paper-root> check
scripts/run-log.ps1 --log-dir <log-dir> --paper-root <paper-root> run -- <command...>
scripts/latex-check.ps1 --manuscript <paper-root>/manuscript --bib <paper-root>/manuscript/references.bib --main sections/main.tex --compile
scripts/final-check.ps1 --manuscript <paper-root>/manuscript --pdf <paper-root>/submission/final.pdf
```

`latex-check.ps1` 的 `--main` 接收相对手稿目录的主文件路径。默认值是 `main.tex`；venue 模板把主文件放在子目录时，应显式传入，例如 `--main paper/main.tex`。

## Automation

四类自动化模板与接线规则见 `automation/README.md`：

- `automation/weekly-watch.md`：每周文献增量监控。
- `automation/deadline-check.md`：投稿日倒排与 gate 缺口检查。
- `automation/stage-advance.md`：读取当前 stage 并给出手动推进建议。
- `automation/experiment-queue.md`：顺序运行实验队列并报告停止原因。

四类任务的统一静默策略是：没有实质变化就不通知。没有新增文献、没有到期 checkpoint、没有状态变化、队列没有失败或停止项时，不发送“已检查”消息。模板只做信息收集与提醒，不得自动修改正文、`ccfa.yaml` 结论字段或推进 stage。实际挂载需用户确认；用户明确确认前只保留模板与手动命令，不注册 scheduler。

## Venue 模板

venue 模板库位于 `$CODEX_HOME/skills/ccf-latex-templates`，当前 139 个 venue 覆盖 NeurIPS、ICML、ACL、AAAI、CVPR 等会议与期刊入口。

模板为官方/社区下载，不是本仓库生成或再分发的内容。使用前自查许可与完整性；例如 ACL 模板必须确认 `acl_natbib.bst` 与 `custom.bib` 均已随模板提供，否则真实编译会因缺文件失败。

## 派生一篇新论文

```powershell
cd <仓库根>
scripts/new-paper.ps1 my-paper `
    --venue NeurIPS --year 2027 --mode conference --title "My Paper"
```

默认写入 `papers/<slug>/`。派生失败时不得留下半成品目录。

## 重新生成 checklist

checklist 是生成物，不要手工编辑。修改 `tools/ccfa/stages.py` 后运行：

```powershell
cd <仓库根>
& tools/.venv/Scripts/python.exe tools/newpaper/checklists.py
```

生成结果必须与 `checklists/conference.md` 和 `checklists/journal.md` 保持一致。

## 论文工作台（P0）

一个本地 PySide6 桌面壳：查看 `papers/*` 项目的阶段门、运行确定性检查，并配置 OpenAI 兼容 API；核心 `app/ccfa_core/` 零 Qt，GUI 在 `app/ccfa_gui/`。

工作台是工作流的**消费者**：`app/` 下不 import 任何 `ccfa.*` 模块，只通过
`python -m ccfa.<tool>` 子进程调用，依赖 JSON stdout / stderr 摘要 / 退出码 0-1-2 这个契约。
因此两边可独立升级，且删掉 `app/` 不影响任何 gate 与证据。工作流位置默认取仓库根，
可用 `CCFA_WORKFLOW_ROOT` 覆盖。

首次准备（在仓库根执行；`app/.venv` 已被 gitignore，不随克隆提供）：

```powershell
cd <仓库根>
py -3.12 -m venv app/.venv
& app/.venv/Scripts/python.exe -m pip install -r app/requirements.txt
```

启动：

```powershell
cd app
& .venv/Scripts/python.exe -m ccfa_gui.main
```

headless/CI 环境再设 `$env:QT_QPA_PLATFORM = "offscreen"`；若本机没有 `py -3.12`，把解释器换成你机器上 Python 3.12 的绝对路径。

P0 边界：本轮只证明"项目 → 阶段 → 检查 → 设置"的最窄链路；聊天与工具桥见下面的 P1 小节。

## 论文工作台（P1：聊天与工具桥）

P1 在 P0 之上加了聊天面板与引擎适配器：

- 引擎下拉：`OpenAI 兼容`（读取 provider 设置，密钥只从 keyring 取）与 `codex exec`（本机 CLI，模型名可选）。
- 引擎在后台线程执行，回复经 Qt 信号回主线程；运行中显示"停止"。
- 选中项目后，模型可调用确定性工具：milestones、library、memory、state、trace_claims。写操作（memory 追加、stage 推进/回退）必须先在确认弹窗批准，拒绝时返回 `user declined`；每次调用追加到 `<paper>/ccfa-workfiles/agent-tools.jsonl`，只记录参数 sha256 摘要与结果，不记录参数明文或密钥。
- `run-log run`（任意命令执行）不暴露给模型。

P1 边界（如实）：

- 流式输出未做，当前整段返回后一次显示。
- `run-log run` 未暴露。
- HTTP 取消是请求边界式：最坏等当前请求完成或超时（`timeout_s` 兜底）；codex 取消会立即 kill 子进程。
- 安装包未做；仍需按上面的"首次准备"手动建 venv。

## 论文工作台（P2：自定义 HTTP 工具注册表）

P2 让使用者用声明式配置接入自己的 API，不写代码。注册表是一份 YAML；每项描述一个模型可发起的 HTTP 请求：

```yaml
version: 1
tools:
  - name: arxiv_search
    description: "Search arXiv for a query."
    method: GET
    url: "https://export.arxiv.org/api/query"
    risk: read
    timeout_s: 20
    query:
      search_query: "{search_query}"
    parameters:
      type: object
      properties:
        search_query: {type: string}
      required: [search_query]
      additionalProperties: false
```

加载规则（`app/ccfa_core/http_tools.py`）：

- v1 只支持 HTTP，不支持任意 Python handler——那样会拿到应用自身权限，且无法校验。
- `http://` 明文默认拒绝，必须显式写 `allow_http: true`。
- 凭据头只能写 `secret:<key_name>`，由 keyring 取值。判定按名字：`Authorization`/`Proxy-Authorization`/`Cookie`/`Set-Cookie`，以及任何名字含 `token`/`key`/`auth`/`secret`/`credential`/`password`/`session`/`cookie` 的头（如 `X-Api-Token`、`apikey`、`X-Session-Id`）。写明文凭据是加载错误，`secret:` 必须给出非空 key 名且不能含占位符。名字匹配是刻意保守的启发式：像 `Public-Key-Pins`、`X-Monkey` 这类非凭据名也会被要求走 keyring，代价是麻烦而不是泄露。
- url / query / json / headers 里的 `{占位符}` 必须在 `parameters` 中声明；GET 不许带 json body。
- 响应默认按未压缩读取（请求带 `Accept-Encoding: identity`）；服务端仍返回压缩体时拒绝（`http-encoding`），因为解压会在限流前吃掉内存——确需压缩响应的工具要显式写 `allow_compressed: true`。
- **任一工具非法，整个注册表不加载**（fail-closed），不会留下「一半工具悄悄生效」的状态。

接入方式：`ToolBridge(project_root, http_tools=HttpToolRegistry(specs, resolve_secret=...))`；注册的工具与内置工具走同一套参数校验、风险分级、写操作确认与审计日志（只记参数摘要）。

工作台接线：设置页可选择注册表文件并在保存前完整验证；相对路径按
`settings.json` 所在目录解析。保存后当前项目的 `ToolBridge` 会立即重建，聊天面板
广播内置工具与注册工具的合并清单，无需重启。任一注册项非法时整份注册表拒载，
界面只显示错误代码，不回显可能含凭据的 YAML 内容。

P2 边界（如实）：HTTP 工具注册表已接入设置与聊天路径；P3 的 Windows 打包安装仍未做。

## 从零搭建

依赖清单固定在 `tools/requirements.txt`。需要 Python 3.12（本仓库实测 3.12.14）。`tools/.venv` 已被 gitignore，不会随克隆提供。在仓库根执行：

```powershell
cd <仓库根>
python -m venv tools/.venv
& tools/.venv/Scripts/python.exe -m pip install -r tools/requirements.txt
```

如果 `python` 不是 3.12，可用 `py -3.12 -m venv tools/.venv`。`scripts/*.ps1` 包装器固定调用 `tools/.venv/Scripts/python.exe`，因此必须安装在默认路径。装完后从仓库根运行：

```powershell
$env:PYTHONPATH = (Resolve-Path tools).Path
& tools/.venv/Scripts/python.exe -m unittest discover -s tools/tests -t tools -v
```

交付格式、排版、数据版本与 notebook 依赖不是 Python 包，用便携版安装器一次补齐（下载走可达镜像，解包到 `%LOCALAPPDATA%\codex-tools`，不改系统目录）：

```powershell
cd <仓库根>
scripts/install-toolchain.ps1
scripts/doctor.ps1 --strict
scripts/compute.ps1 probe
scripts/archive.ps1 probe
```

给 `scripts/doctor.ps1` 加 `--strict` 会把缺失的可选依赖也判为 problem，是"一次装齐"的验收口径；`compute.ps1 probe` 报告本机与远程算力，`archive.ps1 probe` 报告 Zenodo/OSF/ORCID 的传输可达性。

## 跑测试

日常不要手写测试模块清单。先看影响计划，再运行最小测试集：

```powershell
cd <仓库根>
scripts/test-impact.ps1 plan --base origin/master
scripts/test-impact.ps1 run --base origin/master
```

工作台改动使用 `--suite app`。未知路径、`cli.py` / `stages.py`、
依赖文件等共享边界会 fail closed，自动回退到对应 suite 的全量测试。
只有全量回退、每晚 schedule、手动发布检查，或明确要验证跨模块契约时才运行全量：

```powershell
cd <仓库根>
scripts/test-impact.ps1 run --suite tools --full
```

## 已知环境约束

- `perl` 与 `latexmk` 本机已可用（Strawberry Perl + MiKTeX）。`latex_check` 仍按 `pdflatex`、`bibtex`、`pdflatex`、`pdflatex` 显式执行，以避免 MiKTeX 自动装包在 CI 中挂起；这不是缺 Perl 导致的限制。
- 中文文稿用 `xelatex` 加 `ctex`，已实测通过。
- 文献库索引用于中文时必须使用 FTS5 `trigram` 分词器；`unicode61` 对中文完全无效。
- 本机网络分层：`github.com` 与 `api.github.com` 可达，但 GitHub release 资产 CDN 被限速到约 0.03 MB/s，需经 `gh-proxy.com`（约 0.2 MB/s）；`pypi.org` TLS 握手超时，需用 `pypi.tuna.tsinghua.edu.cn`；`zenodo.org` 被本地 DNS 解析到 `0.0.0.0`，`archive_client.py` 用 DNS-over-HTTPS 绕过。
- 便携版工具链（qpdf/typst/quarto/micromamba/LibreOffice/mutool）用 `scripts/install-toolchain.ps1` 安装，不写系统目录、不需要管理员；清单见 `tools/install/fetch_toolchain.py`。本机安装在 `F:\codex-tools`（C 盘曾只剩 0.7 GB），根目录由 `CODEX_TOOLS_DIR` 与 `%LOCALAPPDATA%\codex-tools-location` 指针双重记录，`tools/ccfa/toolchain.py` 负责解析。
