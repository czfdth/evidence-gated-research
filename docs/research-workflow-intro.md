# 科研工作流：产品介绍、能力边界与使用方法

日期：2026-10-04

## 一句话定位

这是一套面向个人科研的本地工作流：把「做一篇论文」从一连串临时决定，变成一条
**有状态、有 gate、有证据、可回退、可复核**的流水线。

它的主路径是 LaTeX + BibTeX。模板库只维护一份，每篇论文派生为独立 git 仓库；
`ccfa.yaml` 记录论文所处阶段，确定性脚本检查可机械判定的问题，无法机械判定的
证明、语义、统计与治理判断则必须留下具名、结构化的复核记录。

它真正交付的不只是论文文件，而是**论文、证据、决策、失败记录和版本历史组成的
可审计研究档案**。

## 一、解决的问题

| 常见问题 | 工作流机制 |
| --- | --- |
| 结论与证据脱节，过一段时间说不清数字来源 | 数字行内标记、源值回查与 claim 绑定 |
| 引用存在，但并不支撑正文论断 | DOI/条目核验 + 引用语义人工复核账本 |
| 图表来源不明，正文对图的解释无人负责 | 图表 manifest + 图表到 claim 的人工支持判断 |
| 证明看起来成立，却遗漏条件或循环论证 | 定理类环境扫描 + 具名证明复核记录 |
| 复现时才发现缺依赖、版本或系统工具 | 运行日志、环境账本、lockfile 哈希与真实重跑 |
| 版本混乱，无法确认某次提交包含哪些论文文件 | 每篇论文独立 git 仓库、tag 快照与真实 diff |
| 最后一刻增加实验，导致主线失控 | 倒排时间表、T-30 冻结规则与豁免理由留痕 |
| 长任务失控、静默重试或持续占用 GPU | 预算、重试上限、停滞看门狗、Docker 沙箱与失败留档 |
| 自查存在系统性盲区 | 执行与评审分离，关键 gate 要求跨模型家族评审 |
| 中断后不知道从哪里继续 | 状态机、推进/回退历史与 stale 证据自动作废 |
| 自动提醒逐渐变成噪声 | 默认安静，只在实质变化、失败或需要人工处理时通知 |

## 二、核心资产

### 1. 状态

`ccfa.yaml` 是论文阶段状态的唯一事实源，记录当前 stage、gate、更新时间，以及完整的
推进与回退历史。证据改变后，旧评审不会继续冒充有效结果；工作流会报告 stale，必要时
回滚到需要重新审查的阶段。

### 2. 判据

`tools/ccfa/stages.py` 是会议与期刊状态机的统一定义。每个阶段有明确 gate，生成的
checklist 只是它的可读视图，不能另行发明一套口径。

### 3. 证据

引用台账、数据来源、运行日志、图表 manifest、人工复核、评审记录、复现包与版本标签
都落在文件中。检查器读取这些文件，不把聊天记录或模型自述当作通过依据。

## 三、论文生命周期

### 创建论文

```powershell
scripts/new-paper.ps1 my-paper `
    --venue NeurIPS --year 2027 --mode conference --title "My Paper"
```

命令从模板派生完整目录，写入初始状态与账本，并建立独立 git 仓库和初始提交。
创建失败时不保留半成品目录。

### 会议流程

```text
idea -> grounded -> data-ready -> experiment-design -> experiments-running
     -> results-ready -> writing -> internal-review -> submission-check
     -> submitted -> rebuttal -> camera-ready -> archived
```

### 期刊流程

前十个阶段与会议共用，投稿后的尾部为：

```text
submitted -> major-revision -> response-letter -> resubmitted -> accepted -> archived
```

允许回退，但必须记录触发事实、回退目标和失效产物。归档时将终稿、来源、复现包、
评审和审计记录一起保存。

## 四、能力全景

### 1. 确定性检查

目前仓库包含 52 个 PowerShell CLI 入口和 69 个工具模块，覆盖状态推进、引用核验、
数字溯源、来源登记、运行日志、实验队列、复现打包、LaTeX 检查、终稿检查、版本快照、
文献库、研究记忆、跨模型评审、人工论证审计、readiness 汇总和平台预检。

工具遵循统一契约：JSON 写 stdout，人读摘要写 stderr；退出码 `0` 表示通过，`1` 表示
发现研究或材料问题，`2` 表示工具自身失败。检查类操作只读且幂等，写入类操作原子写入
并默认不覆盖现有证据。

### 2. 数字、图表与引用证据链

正文关键数字可写为：

```tex
\dataval{<源文件>:<键路径>}{<显示值>}
```

检查器按路径回查源值，并按显示精度处理正常舍入。`data/claims.yaml` 定义必须覆盖的
章节；这些章节内未绑定的数字是 problem，范围外的候选数字保留为 advisory。

`figures/manifest.yaml` 记录每张交付图的来源 run、源数据、生成脚本与哈希。
`data/citation-support.yaml` 和 `data/figure-support.yaml` 再分别记录「引用是否支撑句子」
以及「图表是否支撑 claim」的具名人工判断。

### 3. 人工判断账本

| 账本 | 强制记录的内容 |
| --- | --- |
| `data/proof-audit.yaml` | 证明复核方法、复核者、日期与结论 |
| `data/citation-support.yaml` | 引用对正文原句的支持判定和来源摘录 |
| `data/figure-support.yaml` | 交付图、claim、正文归因与支持判定 |
| `data/novelty-audit.yaml` | 检索库、查询、日期、近邻、重叠与逐 claim 差异 |
| `data/statistics-plan.yaml` | 端点、检验、alpha、效应量、功效、样本量、种子与停止规则；描述性研究可显式写 `analysis_type: descriptive` 并对不适用字段写 `not-applicable` |
| `data/governance.yaml` | 署名、贡献、COI、伦理、许可、AI 使用、查重和负责任披露 |
| `data/repro-environment.yaml` | Python、依赖文件、lockfile 哈希、系统工具版本与证据 |
| `data/human-coding.yaml` | 双人编码的一致率、Cohen's kappa 与 bootstrap 置信区间 |
| `data/claim-registry.yaml` | claim 到 proof / experiment / figure / citation / assumption / limitation 的统一链接 |
| `data/assumptions-limitations.yaml` | 假设、假设违反后的影响、局限及正文位置 |
| `data/venue-checklist.yaml` | venue 方法学条目、完成状态、证据与负责人 |
| `data/artifact-provenance.yaml` | 主要产物的 human/model/mixed 归属、模型族与 run/hash 绑定 |
| `data/exploration-graph.yaml` | pivot、dead-end、rejected 与 active 方向及其 claim/run 绑定 |
| `data/cost-ledger.yaml` | GPU、模型、token 成本与重跑次数 |
| `data/risk-register.yaml` | 已知风险、严重度、缓解措施、证据与状态 |

这些是**完整性 gate**，不是自动真值判断器。它们能阻止「没人复核却宣称已复核」，
但不能证明复核者的判断正确。

### 4. 执行与评审分离

关键 gate 要求评审模型与执行模型来自不同 family。同族或无法识别 family 的结果默认
不能写入 pass。异常情况下可以显式 override，但必须留下足够长的理由；严格检查会把
任何同族 override 重新判为 problem。

执行模型、执行 provider、评审 provider、endpoint 哈希与 provider 配置哈希都从 Codex
配置解析并写入评审记录，不接受调用方自报。评审记录同时绑定输入文件哈希和评审指令
哈希。正文、证据、gate 指令或 provider 配置改变后，旧评审会被报告为 stale、prompt
drift 或 provider config drift，必须重新执行。

### 4.5 Readiness report

`scripts/readiness.ps1` 是每天开工的一页式入口。它支持 `minimal`、`standard`、
`high-assurance` 三个 profile，汇总当前 stage、gate、必需证据台账、倒排 checkpoint、
Git dirty 状态、remote 和 GitHub Actions 是否存在。

报告明确分成六个维度：`schema-valid`、`evidence-present`、`gate-verified`、
`independently-reviewed`、`scientifically-accepted`、`collaboration-ready`。
`evidence-present` 只判断文件是否存在；`gate-verified` 真正执行 profile 对应的
novelty、statistics、repro-env、repro-package、argument-audit、governance、
cross-review 等检查器。
任一 gate 有 problem 时 `ready=false`。`standard` 与 `high-assurance` 还要求论文仓库
已有 remote 和 GitHub Actions；`high-assurance` 会把明确标记为 pending 的证明、引用、
图表与真人双编码台账继续视为阻塞。科学接受默认是 `not-claimed`，不会把“材料齐全”
误写成“结论正确”。

### 4.6 形式化验证

`scripts/formal-check.ps1` 运行论文在 `data/formal-checks.yaml` 中声明的机器检查：
每条检查给出 `engine`、`theorem_id` 和命令，工具执行命令、解析 JSON 输出，并核对
`id`/`engine`/`theorem_id`/`status` 与台账一致，结果写入 `reviews/formal-check.json`。
它只认 `proved`/`unsat`/`valid`；任何不一致或未证明都记为 problem。

示例论文的 Proposition 4（非组合性）用两个独立 SMT 引擎交叉检查同一个算术核心：
z3 与 cvc5 都证明其否定不可满足。两个不同实现给出同一结论，比单一引擎更有说服力，
但仍只覆盖算术/条件核心，语义映射到继承公理这一步仍需人工复核。

`scripts/verifiers.ps1` 清点本机可用的形式化引擎并对照论文声明的引擎。截至本机实测，
九个引擎全部可用：z3、cvc5（SMT，已接入）、Lean、Coq、Isabelle、Agda、Why3、Sage、
Julia。其中 Agda、Why3、Sage 走 WSL（`apt` / conda-forge），检测器会运行
`wsl -d <distro> -u root -- bash -lc ...` 确认它们真的可调用，而不只是文件存在。
缺失时如实报告，而不是让 `doctor` 保持“全绿”。

### 5. 长任务安全

实验队列支持 wall-clock 预算、GPU 秒预算、重试上限、无输出停滞看门狗，以及
`policy` 和 `docker` 两级沙箱。Docker 模式默认只读挂载研究目录、仅开放指定输出目录、
禁止网络并启用 `no-new-privileges`。Docker 不可用时任务失败关闭，不会静默降级到宿主机。

### 6. 平台预检

`scripts/doctor.ps1` 检查 git、LaTeX 工具链、codex、Docker、GPU 工具、两个虚拟环境，
以及形式化验证器（z3/cvc5/lean/coq/isabelle/agda/why3/sage/julia）。`found` 只表示命令
在 PATH 上；除 Docker daemon 外，预检不会把「能找到」夸大成「已完整运行验证」。核心
形式化引擎（z3）缺失会判为 problem，其余引擎缺失为 advisory，`--strict` 全部升级。

### 7. 桌面工作台与自定义 API

本地 PySide6 工作台已经支持项目、阶段、检查、设置、OpenAI 兼容 API、`codex exec`、
后台聊天、取消操作和白名单工具调用。写操作必须经确认，工具审计只记录参数摘要与结果，
不会记录 API key 或完整敏感参数。

工作台是工作流的**消费者**，不 import 任何 `ccfa.*` 模块：所有确定性操作都通过
`python -m ccfa.<tool>` 子进程进行，只依赖 JSON stdout / stderr 摘要 / 退出码 0-1-2
这个契约。因此两边可以独立升级，删掉 `app/` 也不影响任何 gate 与证据。工作流位置默认
取仓库根，可用 `CCFA_WORKFLOW_ROOT` 覆盖。

声明式 HTTP 工具注册表核心已经实现：可用 YAML 定义 GET/POST API，将凭据以
`secret:<key_name>` 方式从系统 keyring 解析，并复用同一套参数校验、风险分级、写确认和
摘要审计。注册表默认拒绝明文凭据、不安全 HTTP、未声明占位符和超限响应。

注册表已经接入工作台设置与聊天面板。设置页保存前会完整验证 YAML，保存后立即重建
当前项目的 `ToolBridge`，无需重启；任一条目非法时整份注册表拒载，界面只显示错误代码，
不回显可能含凭据的内容。当前剩余边界是 **Windows 安装包尚未完成**。

## 五、能保证与不能保证

| 能保证 | 不能保证 |
| --- | --- |
| 阶段状态可恢复，推进与回退有记录 | 研究结论一定正确 |
| 关键数字、图表和引用可以指回文件 | 从数据到结论的推理一定成立 |
| 失败不会因自动重试而消失 | 数学证明一定没有遗漏条件 |
| 悬空引用、缺图、未解析标记等结构错误可机械发现 | 引用和图表在语义上一定支持论断 |
| 指定人工判断必须存在、具名并可机检 | 复核者一定独立、称职或诚实 |
| 评审输入和指令变化会使旧结果失效 | LLM 评审可完全复现或没有偏差 |
| 环境声明、lockfile 和工具版本证据齐备 | 任意机器都能重建完全相同的结果 |
| 本地密钥不写入配置与工具审计 | 能抵御拥有本机文件写权限的人篡改账本 |

最重要的边界是：**gate 通过说明证据链和复核程序齐备，不等于论文结论已被证明为真。**

## 六、当前缺点

### P0：真实性仍依赖合格的人

证明正确性、贡献是否成立、引用是否真正支持论断、统计设计是否适用，都不存在可靠的
通用自动判定器。当前方案把人工复核变成强制且可追踪的步骤，但无法替代领域专家。

### P0：本地账本仍属于自证材料

人工账本没有外部签名、机构身份或不可篡改时间戳。作者可以同时修改正文、证据和复核记录。
对个人自用场景，这是一条明确接受的信任边界；需要对外证明时，还应引入独立复核者、
签名归档或受控的远端记录。

### P1：跨族评审取决于本机 provider

代码已经实施跨族 gate，但真正通过仍要求配置第二个不同 family 的 provider。没有该能力时，
同族 override 只能作为有记录的异常路径，不能冒充独立评审。

### P1：复现验证仍受研究项目声明质量限制

工作流会检查 requirements、lockfile、工具版本和真实重跑，但无法替项目猜出未声明的系统依赖，
也不能保证外部数据源、驱动、GPU 或远端服务长期不变。

### P1：桌面产品尚未完成 Windows 交付

自定义 HTTP 工具注册表已经可以从设置页面加载并提供给聊天模型，但 Windows launcher、
快捷方式和 PyInstaller 安装包尚未交付。目前仍需从开发环境启动工作台。

### P2：复杂度和维护成本较高

状态机、多个账本、Docker、GPU 计量、跨族 provenance 和桌面应用共同扩大了维护面。
新增机制必须证明能消除真实风险；不能仅因为某项指标可检查，就继续增加低价值 gate。

### P2：指标可能替代目标

覆盖率、哈希、账本数量和评审轮次容易产生漂亮数字，但论文质量最终取决于论证、实验设计、
新颖性与表达。工作流应服务于研究判断，而不是让研究者为了让检查全绿而写材料。

## 七、产品成熟度

| 组件 | 当前状态 |
| --- | --- |
| 论文状态机与会议/期刊 gate | 已实现 |
| 独立论文仓库、版本快照与 stale 回滚 | 已实现 |
| 数字、引用、图表与来源证据链 | 已实现 |
| 人工论证、治理、统计、新颖性与复现环境 gate | 已实现 |
| Docker 队列、GPU 预算与看门狗 | 已实现 |
| 跨族评审约束与 prompt/input/provider 配置漂移检测 | 已实现，实际使用需第二 provider |
| 一页式 readiness report 与三档 profile | 已实现 |
| 平台依赖预检 | 已实现 |
| PySide6 工作台与模型聊天 | 已实现 |
| 自定义 HTTP 工具注册表核心 | 已实现并通过定向测试 |
| HTTP 注册表的 GUI/聊天接线 | 已实现，保存后热重载 |
| Windows 自用安装包与快捷启动 | 待完成 |
| 外部签名或不可篡改审计 | 未实现，个人自用暂不作为默认范围 |

当前代码规模约为 28 个 PowerShell CLI、46 个工具模块、1167 个工具侧测试函数和
187 个工作台测试函数。数字只是维护规模，不代表科学结论的可信度。

## 八、推荐使用方法

### 1. 首次检查环境

```powershell
cd <仓库根>
scripts/doctor.ps1
```

需要所有可选能力都可用时运行：

```powershell
scripts/doctor.ps1 --strict
```

### 2. 创建一篇新论文

```powershell
scripts/new-paper.ps1 my-paper `
    --venue NeurIPS --year 2027 --mode conference --title "My Paper"
```

### 3. 按阶段推进

阅读 `checklists/conference.md` 或 `checklists/journal.md`，使用：

```powershell
scripts/milestones.ps1 stage --paper-root papers/my-paper
scripts/milestones.ps1 due --paper-root papers/my-paper
```

每次只处理当前 gate 暴露的问题，不要为了全绿提前伪造空账本或占位复核。

### 4. 测试修改

日常开发只运行本次新增、修改模块及其直接消费者的测试，不默认运行全量套件。例如修改
HTTP 工具注册表后，运行：

```powershell
& app/.venv/Scripts/python.exe -m unittest `
    app.tests.test_http_tools `
    app.tests.test_tools_bridge -v
```

只有发布、合并大范围基础设施修改或明确要求时，才运行完整测试集。

## 九、下一步产品化顺序

1. **交付 Windows 自用包。** 增加 launcher、快捷方式与 PyInstaller 构建，不打包 API key，
   保留 keyring、写确认和摘要审计。
2. **做一次真实端到端验收。** 用全新测试论文验证创建、配置 API、聊天调用只读/写入工具、
   人工确认、阶段推进、失败恢复与归档；不要改动已有论文来充当产品验收夹具。

命令速查见仓库根 `README.md`；架构、gate 与接口契约见
`docs/design/2026-10-03-research-workflow-design.md`。
