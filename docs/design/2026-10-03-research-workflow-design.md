# 科研工作流设计文档

日期：2026-10-03
版本：v6（v1 初稿 → v2 依据 GitHub 参考核查修订 → v3 补齐确定性工具契约、跨模型评审机制、记忆与索引 schema、长任务安全 → v4 依据 research-suite 代码级深读补齐数字溯源契约 → v5 补齐编译检查契约 → v6 补齐终稿检查契约）
状态：v3 已评审；v4 已随 Plan 3 落地（trace-claims）；v5 已随 Plan 4 落地（latex-check，253 tests）；v6 增补第 6.6 节，待随 Plan 5 实施
主路径：LaTeX + BibTeX
形态：可复用模板，每篇论文派生一份

## 1. 目标

建立一套个人科研工作流，覆盖 CS 会议与 CS 期刊两类投稿，特征是：

- 可复用：模板库固定一份，每开一篇新论文派生一个独立项目目录。
- 两套尾部：会议走 rebuttal，期刊走 major revision，前段共用。
- 五层结构：业务流程层、Agent 执行层、Skills 工具层、工具适配层、知识资源层。
- 状态可恢复：任何阶段中断后，凭 `ccfa.yaml` 与目录内容即可回到原位继续。
- 确定性优先：凡能机械化判定的，写成脚本，让证据落在文件上而不是对话里。需要"模型自述已完成"才能通过的 gate 不算通过。

## 2. 非目标

- 不把 Word 作为主路径。保留导出能力，但不进入主链。
- 不做多人实时协作与云端同步。
- 第一版不做语义检索，只做全文检索。
- 不覆盖本机未安装的桌面软件（EndNote、MathType、Origin、Photoshop），只能文件交换或替换方案，见第 7 节。
- 不做传播与影响力追踪（综述的第 9 阶段）。它与投稿是两件不同的事，混进来会稀释主链。需要时单独加一条轨。
- 同一工作不同时投中文期刊与英文会议。跨语言并行投稿必须先核实两个 venue 的政策，否则按一稿多投处理。

## 3. 整体架构

### 3.1 位置

- 模板库：`<home>\Documents\Codex\paper-template\`
- 论文库：`<home>\Documents\Codex\papers\<slug>\`

模板库纳入 git 管理，改坏可回滚。

### 3.2 五层

| 层 | 职责 | 实现方式 |
| --- | --- | --- |
| 1 业务流程层 | 阶段推进与闭环回流 | `ccfa.yaml` 状态机 + gate 判据 |
| 2 Agent 执行层 | 五类角色路由，执行与评审分离 | 按 stage 路由到技能；gate 节点用独立模型评审 |
| 3 Skills 工具层 | 可复用能力 + 确定性工具 | 现有技能 + 自建校验、追踪、审计脚本 |
| 4 工具适配层 | 对接外部工具 | COM 原生操作 + 本地库 + 文件交换 + 浏览器自动化 |
| 5 知识资源层 | 检索、复用与记忆 | 文献库 + FTS5 全文索引 + 研究记忆（含反重复） |

## 4. 业务流程层

### 4.1 阶段流

会议模式：

```
idea -> grounded -> data-ready -> experiment-design -> experiments-running
     -> results-ready -> writing -> internal-review -> submission-check
     -> submitted -> rebuttal -> camera-ready -> archived
```

期刊模式与会议模式共用前十个阶段（`idea` 到 `submitted`），尾部替换为：

```
submitted -> major-revision -> response-letter -> resubmitted -> accepted -> archived
```

### 4.2 Gate 判据

每个阶段有可检验的通过条件，不满足则不算通过。

| Stage | Gate | 通过条件 |
| --- | --- | --- |
| idea | scope_defined | 问题陈述、至少一条可检验假设、目标 venue 均写明 |
| grounded | novelty_grounded | 列出三篇最近邻工作及各自盲区，说明本工作填补的是哪一个"无人测量的合取"；novelty-audit 记录检索范围/日期与逐 claim 差异；禁止"没人做过"式表述 |
| data-ready | provenance_recorded | 逐份数据有来源、分类与校验和；执行 `provenance check --scan data` 确认无未登记数据；来源文档可被脚本核对；不合规来源已排除 |
| experiment-design | design_frozen | 每个 claim 对应一个实验；baseline 来源明确；metric 定义明确；statistics-plan 含 alpha/多重比较、功效与样本量、种子、停止规则、缺失数据处理与平台画像（阶段零微基准） |
| experiments-running | results_recorded | `experiments/log/` 逐次运行留有配置、种子、commit、退出码、指标 |
| results-ready | claims_supported | 每个 claim 指到具体数值，且该数值通过行内标记脚本核对；无支撑项标记待验证或删除 |
| writing | draft_complete | 正文、图表、引用齐备；页数符合 venue；所有引用条目来自检索期已核验的条目 |
| internal-review | review_cleared | 跨模型评审报告无 blocking 项；引用、数字、图表三项核验通过；人工证明复核、引用语义支持与图表语义支持台账无未复核项 |
| submission-check | package_ready | 模板、匿名、页数、元数据检查通过；复现包在干净环境实际重跑成功；repro-environment 记录 lockfile 哈希与系统工具版本证据；governance 台账齐备（署名/贡献、COI、伦理与许可、AI 使用、查重、双用途与负责任披露） |

会议尾部：

| Stage | Gate | 通过条件 |
| --- | --- | --- |
| submitted | venue_decided | 收到 venue 决定，评审意见归档 |
| rebuttal | rebuttal_submitted | 逐条回应完成，修改范围与承诺一致 |
| camera-ready | final_package_ready | 终稿符合 camera-ready 规范；确定性终稿检查通过 |
| archived | archived | 终稿、复现包、数据来源文档归档 |

期刊尾部：

| Stage | Gate | 通过条件 |
| --- | --- | --- |
| submitted | venue_decided | 收到决定，评审意见归档 |
| major-revision | revision_planned | 每条意见有明确处置方案，含不采纳的正当理由 |
| response-letter | response_complete | 逐点回复完成，与实际改动一致 |
| resubmitted | resubmission_ready | 改动稿与回复信齐备，修改痕迹保留 |
| accepted | archived | 数据来源文档、model card、data card 齐备 |
| archived | archived | 确定性终稿检查通过；全部材料归档 |

### 4.2.1 状态文件

沿用 CCFA 的 `ccfa.yaml` v0.4.0 schema，不新增顶层字段。venue 模式通过已有字段表达：

```yaml
target_venue:
  name: "NeurIPS"
  year: "2027"
  mode: "conference"   # conference | journal
```

`mode` 决定第 4.1 节采用哪套尾部阶段与 gate 清单。其余字段保持原 schema。

`claims` 与 `experiments` 用数组承载结构化记录，这是"每个 claim 可追溯到证据"的落点。每条 claim 至少含：

```yaml
claims:
  - id: C1
    statement: "方法 A 在数据集 D 上优于基线 B"
    status: supported        # supported | provisional | dropped
    evidence:
      run_ids: [R12, R13, R14]
      commit: "abc1234"
      dataset_version: "D-v2.1"
      metric: "accuracy"
      statistic: "mean +/- 95% CI"
      figure: "figures/main-results.pdf"
    reviewer_concerns: []
```

指不到 `run_ids` 的 claim 不允许标为 `supported`。种子、统计口径与图号都在同一条记录里，这是把"结论"与"证据"绑在一起的最小结构。

### 4.3 闭环回流

任一阶段发现前置结论不成立时，允许回退。回退必须记录在 `ccfa.yaml`：

- 从哪个阶段回退到哪个阶段。
- 触发原因（一条具体事实，不写"感觉不对"）。
- 哪些已完成产物仍然有效，哪些作废。

### 4.4 审稿意见矩阵

`reviews/revision-ledger.md` 沿用 CCFA 的字段，补两列：

| 列 | 内容 |
| --- | --- |
| Concern ID | 稳定编号，跨版本复用 |
| 来源 | 哪位审稿人，第几轮 |
| 类型 | 证据不足 / 表述不清 / 需要新实验 / 误解 |
| 需要的新证据 | 指向 `run_id`、引用键或明确写"无" |
| 处置 | 改稿位置或回复要点 |
| **承诺风险** | 这条回复是否承诺了尚未完成的工作 |
| 状态 | 待处理 / 已处理 / 不采纳（须写理由） |

承诺风险这一列是关键。绝大多数 rebuttal 翻车不是回应写得不好，而是回复里承诺了做不出来的实验。"需要的新证据"与"承诺风险"必须同时填，两者对不上就说明这条回复在冒险。

### 4.5 倒排时间表

会议模式以 deadline 为锚点倒排（T 为截止日）：

| 节点 | 要求 |
| --- | --- |
| T-90 | 端到端流程跑通，能力冻结，不再引入新方法 |
| T-60 | 主实验结果冻结，只补消融 |
| T-30 | 全部 claim 锁定，进入写作。此后不接受新实验 |
| T-21 | 初稿完成 |
| T-14 | 跨模型评审完成 |
| T-7 | 引用、数字、图表三项核验完成 |
| T-3 | 终稿确定性检查通过，打包完成 |
| T-1 | 只做格式与提交，不动内容 |

T-30 之后不接受新实验是硬规则。最后一刻加实验是论文流产最常见的单一原因。

**执行细节（v6 补记）：** `milestones due` 扫描 `experiments/log/`，T-30 之后开始的
运行按记录里的 `declared_purpose` 分流：`experiment` 或无声明是 problem
（`t30-new-experiment`）；声明 `build` 的运行只有同时写了 `purpose_reason`
（≥20 字符）才算正当豁免，豁免仍只是 advisory（`t30-declared-build-run`，声明不构成
证据），缺理由的 build 声明是 problem（`t30-unjustified-build-run`）。这条把「一个词
换一次豁免」改成「一次豁免必须写清是什么构建、为什么不是新实验」——脚本仍然无法证明
声明为真，但绕过它不再是零成本。同理，`run-log check` 把发生在脏树上的运行报成
problem（`run-log-dirty-tree`），因为仅凭 commit 无法复现；记录里写了 `dirty_waiver`
（≥20 字符）才降为 advisory（`run-log-dirty-waiver`）。

期刊模式没有硬 deadline，用同样的相对节点由投稿目标日倒推；若暂无投稿目标日，则按"结果冻结 → 3 周写作 → 2 周评审 → 1 周核验"的顺序推进。

## 5. Agent 执行层

五个角色不新建实体，按 stage 路由到已有技能。

| 角色 | 承担技能 |
| --- | --- |
| 文献与证据 | `ccf-literature-searcher`、`ccf-literature-monitor`、`ccf-integrity-auditor` |
| 创新与方案 | `ccf-idea-optimizer`、`ccf-idea-reviewer` |
| 代码与实验 | `ccf-experiment-designer` + 通用代码执行 |
| 分析与写作 | `ccf-visual-composer`、`ccf-paper-writer` |
| 审稿与质量控制 | `ccf-paper-reviewer`、`ccf-integrity-auditor`、`ccf-submission-checker` |

路由规则由 `ccf-pipeline-orchestrator` 统一执行：读 `ccfa.yaml` 定位当前 stage，确定 gate 缺失项，调起对应技能，最后更新状态。

### 5.1 执行与评审分离

参考 ARIS 的做法：执行者与评审者使用不同模型。同模型自查有系统性盲区。

本机实测（2026-10-03）：

- `codex` CLI 在 PATH 上，版本 0.160.0，支持 `codex exec` 非交互执行，可用 `-c model="..."` 覆盖模型。
- 本地代理 `cc-switch` 监听 `127.0.0.1:15721`，提供 OpenAI 兼容接口；可用模型必须以 `/v1/models` 实际返回为准。
- 当前执行模型由 Codex `config.toml` 决定，评审模型由 `--model` 显式指定；2026-10-05 本机配置为 `deepseek-flash`，但 provider 只实际返回 `deepseek-v4-pro`，因此 doctor 的 provider 仍不是 functional。

| 环节 | 执行 | 评审 |
| --- | --- | --- |
| 选题与实验设计 | config 中的执行模型 | 显式指定的独立评审模型 |
| 正文写作 | config 中的执行模型 | 显式指定的独立评审模型 |
| 终稿检查 | 脚本（确定性） | 不需要模型 |

**必须说清的限制**：`v4-flash` 与 `v4-pro` 同属 DeepSeek V4 系列。E68–E70 之后，`cross-review run` 默认拒绝把同族/未知族模型写成 pass：只有 `family_judgement=="cross-family"` 才允许写入，或显式传 `--allow-same-family` 留 override；`check` 对旧同族记录报 `review-same-family`。E86 之后，执行模型、执行 provider、评审 provider、endpoint 哈希和 provider 配置哈希从 Codex `config.toml` 解析，记录不再接受调用方自称 execution model；`check --codex-config` 或记录中的 `codex_config_path` 会把配置变化报为 `review-provider-config-drift`，而 `codex_config_path` 本身是必需 provenance，删除它会报 `review-provenance-incomplete`。本机尚未接入不同 family 的 provider，所以真正跨族仍需用户显式配置。工具不会伪造跨族。当前 provenance 也不能证明 provider 实际按 `-m` 服务的模型身份；provider alias 或忽略 `-m` 只能由 provider 自身的 `/models` 响应与运行日志继续核查。信任边界：`check` 检测记录内部不一致与配置漂移，不是密码学签名；能改写整份 JSON 与配置文件的人仍可伪造整条链路，局部改写 `model`、`execution_model`、`family_judgement`、`verdict`、`blocking` 等字段并保持组合自洽也无法被本地审计识别。本机防的是默认同族、无意错写和配置变化后旧评审继续冒充有效，不是防本机恶意伪造。

**评审指令漂移（v6 补记，E81）：** 只绑定输入文件哈希不足以说明评审仍然有效——`build_prompt` 里嵌着 gate 判据与 stage 提示，这些文本来自 `stages.py`，改了它们，旧评审就是在另一套指令下产生的。因此 `cross-review run` 把发送给评审模型的 prompt 的 sha256 写进记录（`prompt_sha256`），`check` 用记录里的 `stage` 与输入清单重建同一段 prompt 并比对：缺字段报 `review-prompt-unknown`，不一致报 `review-prompt-drift`，两者都是 problem，处置方式是重跑评审。prompt 里的文件清单排序并去重，所以 `--path` 的传入顺序与重复都不影响摘要；重建不需要输入文件仍然存在（输入没了由 `review-stale` 负责）。评审输入为空不是合法评审：`run` 传空 `--path` 直接退 2，`check` 遇到空 `input_hashes` 报 `review-malformed`。边界：这证明「评审是在当前指令下产生的」，不证明评审结论正确，也不防整份 JSON 被重写。

触发约束：跨模型评审只在 gate 关键节点触发（T-14、内部审稿），不逐轮触发。

## 6. Skills 工具层

直接复用，不新建：

- CCFA 家族 17 个技能。
- Nature 家族用于文献检索、引用核验、统计审查。
- 绘图技能用于出版级图表。
- 代码执行与数据处理属于通用能力，不单独封装。

明确不覆盖：Photoshop、Origin 的桌面端自动化（本机未安装）。

### 6.1 确定性工具（必须自建）

机械可判定的工作不靠提示词反复推导，写成脚本。参考 `research-suite` 的 8 个工具：

**实现语言：Python 3.12**（不是 v2 写的 PowerShell）。理由：这些工具的核心工作是文本解析、字节嗅探、PDF 抽取、SQLite 和子进程编排，Python 的对应库本机全部就绪；PowerShell 在这几件事上没有优势。本机内置 Python 3.12.14，`hashlib`、`sqlite3`、`urllib`、`csv`、`subprocess`、`pathlib` 与 PyMuPDF、Pillow、pandas 均可用。

唯一缺的依赖是 `PyYAML`。处理方式：在 `paper-template/tools/` 下建独立虚拟环境装它，不改动 Codex 的托管运行时。

| 工具 | 作用 |
| --- | --- |
| `citation-guard` | 引用只在检索期入库；Crossref / DataCite 核验存在性；DOI 去重；悬空 `\cite{}` 检测 |
| `trace-claims` | 行内标记 `\dataval{path:key}{value}`，机械化比对活的 JSON / CSV / YAML，契约见 6.4 |
| `provenance` | 逐文件来源、分类、校验和；生成来源文档并可反查 |
| `run-log` | 每次实验运行的配置、种子、commit、退出码、指标 |
| `repro-package` | 打包并在干净环境实际重跑，不只看包是否完整 |
| `latex-check` | 结构校验（括号、环境、未解析引用、缺失图片、未转义 `%`）+ 多引擎编译 |
| `research-version` | 自动编号的版本快照与任意两版之间的真实 diff，替代手工 `v2` / `final-final` |
| `final-check` | 终稿确定性检查，见 6.2 |
| `friction-log` | 记录工具缺陷与指令缺口，跨论文聚合 |
| `argument-audit`（v6 补记） | 审计人工证明复核、引用语义支持与图表语义支持台账；缺记录、非人类 reviewer、refuted/uncertain/contradicts/irrelevant 均报 problem |
| `human-coding`（v6 补记） | 对两张人工编码表计算一致率、Cohen's kappa 与 bootstrap 置信区间；低 κ 先修编码手册 |
| `novelty`（v6 补记） | 检查检索范围/日期、≥3 篇近邻、逐 claim 差异；禁止未支撑的没人做过式表述 |
| `statistics`（v6 补记） | 检查预注册统计设计：alpha、功效、样本量、多重比较、种子、停止规则、缺失数据处理 |
| `governance`（v6 补记） | 检查署名/贡献、COI、伦理与许可、AI 使用、查重、双用途与负责任披露 |
| `repro-env`（v6 补记） | 检查 requirements、lockfile 哈希、系统工具版本与证据文件 |
| `doctor`（v6 补记） | 预检本地平台耦合：git、LaTeX 工具链、codex、Docker、nvidia-smi 与两个 venv；缺什么就点名它禁用了哪个能力。`found` 只证明命令在 PATH 上、venv 解释器是非空文件；唯一的执行探测是 Docker daemon（`doctor-daemon-down`），因为「有 docker 二进制但 daemon 不可达」是本工作流实际踩到的失效。只读，不安装任何东西 |

**分期说明（v6 补记）**：`research-version` 推迟到"复现与归档"计划实施，且默认按 **git 的薄封装**（tag + 真实 diff）而非独立版本库来做。理由：论文库本身已是 git 仓库，独立快照库会制造"两个版本真相"——同一份稿子的"第几版"到底以哪个为准。先不建与 git 打架的东西，比建了再拆便宜。

**写盘工具的补充契约（v6 补记）**：第 6.1.1 节的三条约束针对检查类工具。本层的 `provenance` 与 `run-log` 会写文件，除退出码与输出契约外，另须满足：**原子写**（先写临时文件再改名，避免半截 JSON）、**不覆盖**（同名记录已存在时拒绝写入，除非显式 `--force`）、**幂等可查**（重复执行同一检查不产生新记录）。"失败必须留档"（§9.2）要求单条记录的耐久性，因此运行记录一运行一文件，而不是一个会被整体重写的聚合文件。

### 6.1.1 通用接口契约

所有工具遵循同一份契约，否则它们会各自变成需要模型解释的黑盒。

- **输入**：文件路径或 stage 名。不读对话历史，不依赖上下文。
- **输出**：机器可读的 JSON 到 stdout，人读摘要到 stderr。两者分离，便于脚本串联。
- **点名例外**：`run-log` 的 `run` 子命令是直通包装器，子进程 stdout 与 stderr 原样透传，`run` 自身的控制摘要写 stderr，§6.1.1 的“JSON 到 stdout”只适用于 `check` 与 `log-metrics`。
- **退出码**：`0` 通过，`1` 发现问题，`2` 工具自身出错（输入缺失、依赖缺失、解析失败）。
- **幂等**：同一输入重复运行结果一致。
- **无副作用**：检查类工具（`latex-check`、`final-check`、`citation-guard` 检查模式）只读，不写文件。
- **定位**：返回 `1` 时，每条问题带 `文件:行` 定位。

退出码 `2` 与 `1` 必须分开。把"工具坏了"混进"检查通过"，比检查本身失效更危险。

### 6.1.2 真实性 gate（v6 补记）

机械 gate 只能证明"案卷整齐"，不能证明"结论正确"。为补上这个天花板，新增两道必须由人完成的门：

- **人工证明复核**（`data/proof-audit.yaml`）：扫出 theorem/proposition/lemma/corollary 环境；每个环境必须有 `reviewer`（人类姓名）、`reviewed_at`、`method`、`status`。`status` 不是 `verified` 即 problem；模型名不能冒充 reviewer。
- **引用语义支持**（`data/citation-support.yaml`）：受保护章节中的每个 `\cite{}` 必须有 `reviewer`、`reviewed_at`、`verdict`、`claim_text`、`support_quote`、`citations`、`source_path`。`contradicts`/`irrelevant` 是 problem，`partial` 是 advisory；脚本核对 `claim_text` 是否出现在该引用所在的受保护章节中，并核对 `support_quote` 是否真的出现在 `source_path` 中。脚本不判断证明和语义本身，只强制这些判断有人做过、可追责、可复核。
- **人工编码一致性**（`human-coding`）：两张人工编码表按 item id join，计算 observed agreement、Cohen's kappa 与 95% bootstrap CI；`--min-kappa` 以下退 1。模型辅助审计不能替代这一步。
- **同族评审 override**：`cross-review run --allow-same-family` 现在必须同时提供 `--override-reason`（≥20 字符），原因写入记录；`check --strict-cross-family` 会把任何同族 override 报成 problem。真正的 gate 仍然要求不同 family 的 provider。
- **图表语义支持**（`data/figure-support.yaml`，v6 补记）：`figures/manifest.yaml` 里的每张交付图必须有一条具名人工判断，记录 `claim_ids`（必须来自 `novelty-audit` 的 claim 注册表）、`attributed_text`（≥20 字符，必须逐字出现在该图 `referenced_in` 指向的正文文件里）、`verdict`（`supports` / `partial` / `contradicts` / `irrelevant` / `not-applicable`）、人员、日期与理由。非证据图（示意图/架构图）用 `not-applicable` 并写明理由，且不得绑定 claim。`contradicts`/`irrelevant` 是 problem，`partial` 是 advisory，非 `supports` 判定必须写理由。脚本不看图、不判断图与结论本身是否一致，只强制这个判断有人做过、绑定到 claim 与正文原句、且非同意的结论不会被静默放过；v1 只做文件级原文匹配，不做段落级定位。读不出 claim 注册表、manifest 图名缺失或重复、`referenced_in` 行号越界都按 problem 处理（fail-closed），不会降级为 advisory。

### 6.1.3 治理、统计与新颖性 gate（v6 补记）

审计指出三条剩余高严重度缺口：治理与伦理检查空白、统计设计门槛薄、新颖性判据只有
三篇最近邻。三件事都无法由脚本判断真伪，但都可以要求使用者把判断写进结构化台账：

- **novelty**（`data/novelty-audit.yaml`）：记录检索数据库（≥2）、查询、检索日期与
  cutoff、≥3 篇最近邻、每篇的 overlap/difference、以及每篇覆盖的 claim id。每个
  声明 claim 必须被至少一个近邻差异覆盖；禁止“没人做过 / no one has done / first to”
  式未支撑表述。
- **statistics**（`data/statistics-plan.yaml`）：记录 alpha、multiple_comparison、
  每个 claim 的 endpoint/test/effect_size/target_power/sample_size/seeds/
  stopping_rule/missing_data。多个 claim 时 correction 不能为 none；缺失功效、样本量、
  种子或停止规则都是 problem。描述性研究可写 `analysis_type: descriptive`，并把
  alpha、effect_size、target_power、sample_size、seeds 中不适用者显式写
  `not-applicable`；推断性设计仍拒绝该值。
- **governance**（`data/governance.yaml`）：记录作者与贡献角色、corresponding、
  逐作者 COI、伦理（human_subjects / IRB / informed consent / data license）、
  AI 使用披露、查重工具与日期、双用途复核与负责任披露联系人。
- **repro-env**（`data/repro-environment.yaml`）：记录 Python 版本、包管理器、
  requirements、lockfile 与 sha256、系统工具的名称/版本/命令/证据文件；lockfile
  变化即报 `repro-env-lockfile-drift`，证据中找不到版本即报 mismatch。

这三道 gate 只保证“结构化声明存在且覆盖完整”，不保证新颖性、统计正确性或治理真实性。

`scripts/readiness.ps1` 现在会真实执行 profile 对应的 gate，而不是只检查台账存在。
报告新增 `gate-verified` 维度；`evidence-present` 与 `gate-verified` 分离，任一
下游检查器返回 problem 时 `ready=false`。

第四轮补记：readiness 同时执行 `repro_package.verify_bundle`，因此 bundle 内文件哈希
或 requirements 陈旧时不再假绿。`trace-claims` 增加 `--manuscript`，CI 不再需要自行
枚举全部 `.tex`。`cross-review run --model` 改为必填，不再隐式选择评审模型。
`governance` 对 pending/TBD/placeholder 文本报 `governance-placeholder`。

同族评审新增 `can drive, never acquit` 约束：记录保留模型的原始
`model_verdict`，但 effective `verdict` 只能是 `blocking`。同族 override 只解释
为什么允许记录这次评审，不能把模型返回的 `pass` 变成 gate pass。真正跨族评审仍需
不同 family provider。`check` 也会重新计算该约束，因此只改 effective `verdict`
不能把同族记录变成通过；但记录本身仍不是密码学签名，完整改写自洽字段不属于本机
审计能防的范围。`codex_config_path` 现在是必需的 provenance 字段，缺失时报
`review-provenance-incomplete`，防止删掉该字段来跳过配置漂移核验。

**影响面测试选择（2026-10-05）：** 新增 `tools/ccfa/test_impact.py` 与
`scripts/test-impact.ps1`。它从 `base...HEAD` 与当前工作树收集改动，把路径映射到
最小相关测试模块。未知路径、删除的测试文件、`cli.py` / `stages.py`、依赖清单等
共享边界 fail closed 到对应 suite 的全量测试；tools 与 app 分开选择，app 使用
`app/.venv` 与 offscreen Qt。GitHub Actions 只在 PR/push 上跑影响集，每晚 schedule
和手动 `workflow_dispatch` 保留完整回归。该选择器减少的是重复验证成本，不放松
跨模块改动与未知改动的全量回退。

### 6.2 终稿确定性检查项

基线是渲染后的 PDF，不是编译日志。

- 渲染结果中是否存在未解析的 `?` 引用标记
- 图片字节格式与扩展名是否一致（JPEG 存成 `.png` 会让视觉模型直接报错）
- 是否存在没有任何正文引用的图或表
- 是否有数字缺少 `\dataval` 标记
- 声明类内容（局限、数据可用性）是否齐备

### 6.3 图表溯源契约

综述把"图表溯源"列为尚未解决的问题。每个图必须能回答四个问题，答案写在 `figures/manifest.yaml`：

```yaml
- name: main-results
  file: figures/main-results.pdf
  source_run_ids: [R12, R13, R14]
  source_data: experiments/results/main.csv
  generator: ccfa-workfiles/figures/main-results/source/plot.py
  generator_hash: "sha256:..."
  bytes_format: pdf
  referenced_in: ["manuscript/sections/experiments.tex:142"]
```

`file` 是交付图相对论文根目录的路径，**必填**：校验"bytes_format 与实际字节是否一致"必须先定位到文件，靠"名字约定"去猜会在图被放到别处时静默失配。若历史 manifest 缺该字段，回退到 `<paper-root>/figures/<name>.<bytes_format>`，并在报告中记一条 advisory 提示补写。

`bytes_format` 必须与文件的**真实字节**一致，取值限 `png` / `jpg` / `jpeg` / `gif` / `pdf`。矢量图（论文里最常见）用 `pdf`，与 `file` 的扩展名必须自洽——示例里 `file` 与 `bytes_format` 不一致的写法会被 `final-check` 判为 `figure-manifest-format`。

两条硬规则：

1. 交付的图必须由脚本生成，字节格式与扩展名一致。手工编辑过的导出图不得直接交付。
2. 若确实需要手工修图（排版遮挡、标注修正），必须在 `manifest.yaml` 里注明并写明改了什么。静默修图属于学术诚信问题，不是格式问题。

**语义支持（v6 补记）：** manifest 只能证明图的来源与字节，不能证明图支撑了正文用它所主张的结论。因此每张交付图必须在 `data/figure-support.yaml` 里有一条具名人工判断（§6.1.2），把结论绑定到 claim id 与正文原句。证据图必须声明 `referenced_in`，否则图-结论的绑定没有可复核的落点；`final-check` 的 `unreferenced-figure` 仍是 advisory，这条硬要求只在提出图表语义断言时生效。

### 6.4 数字溯源契约（trace-claims）

第 6.2 节要求"数字缺少 `\dataval` 标记"可被检出，前提是标记本身有确定语义。本节依据 `15b4t/research-suite`（MIT）的 `traceable-claims` 实现深读后定稿，六条为 v4 新增。

**标记语法**：`\dataval{<source_path>:<key_path>}{<claimed_value>}`。编译期由导言区 `\newcommand{\dataval}[2]{#2}` 渲染为 `claimed_value`，脚本独立核验。source_path 相对 `--base-dir` 解析，不得是绝对路径，不得经 `..` 逃逸出 base_dir。

**key_path 解析规则**：

- JSON / YAML：点分隔路径；键名中含字面点时写 `\.` 转义（如 `sweep.0\.5x_4ms.stat`）；列表用整数下标。
- CSV：`<row>.<column>`，row 从 0 起算且不计表头（`0.x` 是第一条数据行）。
- 标签指向的源文件不存在、键不存在、行越界或源文件解析失败，都是**稿件证据缺陷**，属 problem，退出码 1。

**比较语义**（六条中的第 1、4 条在 v3 完全缺失，会导致每个正常四舍五入的数字都误报）：

1. **隐含舍入容差**：按 claimed_value 自身的小数位数推容差——`0.143` 表示源值被舍入到 3 位，容忍 `0.5e-3`。整数写法不推容差。这条让同一篇稿件里不同显示精度共存，无需手工挑一个全局容差。
2. **绝对容差**：`--tolerance`，默认 `1e-9`。
3. **相对容差**：`--rel-tolerance`，默认关闭；开启后差值不超过较大者绝对值的该比例即算通过，用于同一文档跨数量级（`0.143` 与 `1.2e9`）的取值。
4. **数字与布尔归一**：先剥 US 式千分位逗号（仅当形如 `1,234` 时才剥）；`true` / `false` 大小写不敏感（JSON 小写，Python `str(bool)` 首字母大写）。
5. **字符串兜底**：非数字且非布尔的取值要求精确字符串相等。

**未标记数字扫描**：`--untagged` 开启后输出 advisory，启发式识别未包裹的数值字面量，过滤年份、图表/章节编号、方括号引用。**advisory 永不影响退出码**：它是待人工复核的线索，不是判决。

**退出码判定**（与第 6.1.1 节一致，且比参考实现严格）：

- `0`：全部标签通过（零标签也算通过；"有数字没标记"由 `--untagged` 的 advisory 承担，不是 problem）。
- `1`：任一 claimed_value 与源值不符，或任一标签指向的源不可解析。
- `2`：工具自身出错——被检查的文档路径不存在或不可读、`--base-dir` 非法、依赖缺失、参数错误。

参考实现把所有异常都归为 1；本设计把"文档传参错误"（2）与"稿件证据缺陷"（1）分开。两者混淆会让"检查没跑成"看起来像"检查发现了问题"，与第 6.1.1 节的立节理由直接冲突。

**只读**：trace-claims 不写入任何被检查文件。

**配套改进**：v3 遗留的 `texscan._COMMENT` 只回溯一个字符，`text\\%` 后接注释会被误判（见 Plan 2 deferred minors 第 1 条）。数字扫描同样依赖注释剥离，两者共用一个正确的剥离函数（`%` 前的反斜杠为偶数个时才是注释），在 Plan 3 一并修掉，不再各写一份。

### 6.5 编译检查契约（latex-check）

本节依据 `research-suite/tools/latex-tools`（MIT）与 `paper-machine/scripts/verify_paper.py`（MIT）的代码级深读定稿。参考实现的注释剥离仍是"只回溯一个字符"的旧缺陷；本仓库的 `ccfa.texcomment.strip_comment` 已是偶数反斜杠版本，直接复用即可，不要再实现一遍。

**检查项（默认只读，不写任何文件）**：

| 条件 | code | 归类 |
| --- | --- | --- |
| 花括号不配平（`\{` / `\}` 不计数） | `unbalanced-brace` | problem |
| 环境 `\begin` / `\end` 不匹配或未闭合 | `unmatched-environment` | problem |
| 正文引用的键不在 bib 中 | `missing-cite-key` | problem |
| `\includegraphics` 指向的文件不存在 | `missing-figure` | problem |
| 行内未转义 `%`（会静默截断该行） | `stray-percent` | advisory |

`stray-percent` 归 advisory 的理由与 trace-claims 的未标记数字相同：`%` 的合法性依赖上下文（数学模式、`verbatim`、URL），机械扫描只能产出线索。整行注释（`%` 为该行第一个非空白字符）永不报。

结构扫描必须先剥离注释——落在注释里的花括号与环境不该参与配平——并逐文件独立配平，不能把多个 `.tex` 拼接后再数。

**编译（`--compile` 显式开启，是唯一写盘路径）**：本机实测 `latexmk` 不可用（缺 Perl），因此编译器自己按 `pdflatex → bibtex → pdflatex → pdflatex` 四步驱动，逐步判退出码；`.aux` 中无 `\bibdata` 时跳过 bibtex 并记为 skipped。产物写在手稿目录（LaTeX 常规行为）；不开 `--compile` 时一个字节也不写。

**退出码**：`0` 通过；`1` 结构问题，或 `--compile` 时编译失败；`2` 工具错误（手稿目录缺失、开了 `--compile` 但找不到引擎、参数错误）。

### 6.6 终稿检查契约（final-check）

第 6.2 节列了检查项，本节给出可执行的判定与归类。参考实现 `paper-machine/scripts/verify_paper.py`（MIT），采纳其两条设计原则：**基线是渲染后的 PDF 文本，不是编译日志**；**可选依赖缺失时该项记为 skipped，绝不降级为通过**。

| 条件 | code | 归类 |
| --- | --- | --- |
| PDF 文本中存在未解析的引用标记（孤立 `?`） | `unresolved-marker` | problem |
| 图片字节的魔数与扩展名不符（如 JPEG 存成 `.png`） | `figure-format` | problem |
| `figures/manifest.yaml` 里记录的 `generator_hash` 与实际脚本不符 | `figure-hash` | problem |
| manifest 记录的 `bytes_format` 与该图实际字节不符 | `figure-manifest-format` | problem |
| manifest 的 `file`（或回退路径）指向的交付图不存在 | `figure-missing` | problem |
| manifest 条目缺 `file` 字段（用了回退路径） | `manifest-missing-file` | advisory |
| manifest 中的 `referenced_in` 为空，或正文从未引用该图 | `unreferenced-figure` | advisory |
| 正文数字缺少 `\dataval` 标记 | 委托 `trace-claims --untagged` 的结果 | advisory |
| 声明类内容缺失（局限 / 数据可用性） | `missing-declaration` | advisory |

**依赖与降级**：PDF 文本提取用 PyMuPDF（已装入 `tools/.venv`，版本 1.28.2）。若某台机器上不可用，`unresolved-marker` 与依赖 PDF 文本的检查记为 **skipped**，其余检查照常执行、照常报告。**skipped 不是通过，且不得以退出码 0 结束**：本轮存在任何跳过项时，退出码为 **2**（§6.1.1："依赖缺失"属工具错误）——一份闸门报告若因缺依赖而没跑全，就不能对外声称成功。

**退出码**：`0` 通过；`1` 有 problem；`2` 工具错误——手稿目录或渲染后的 PDF 缺失、`manifest.yaml` 存在但不可解析、参数错误。

**自动发现**：未显式传入 `--manifest` 时，如果 `<paper-root>/figures/manifest.yaml` 存在，final-check 必须自动校验该文件；该文件不存在时不进行 manifest 校验，也不记 skipped。

**只读**：final-check 不写入任何被检查文件，也不修改 manifest。

**skipped 的表示**：跳过项以 advisory 形式进入 JSON，code 为 `check-skipped`。理由：`ccfa.cli` 的契约只有 problems 与 advisories 两个数组，扩展它会影响三个既有工具的报告形状；而"跳过"在语义上确实是"需要人注意、但不是判决"，与 advisory 的定义一致。这样 skipped 在机器可读输出里与"通过"（不出现在报告中）天然可区分。

## 7. 工具适配层

本机没有 Word / PPT / EndNote / MathType 的 MCP server，但 COM 自动化可用，因此该层按实测能力设计。

实测 COM 注册情况（2026-10-03）：

| 组件 | 状态 | 含义 |
| --- | --- | --- |
| `Word.Application` | 已注册 | 可生成含原生公式、交叉引用、字段的真实 docx |
| `PowerPoint.Application` | 已注册 | 可生成原生可编辑 pptx |
| `Excel.Application` | 已注册 | 可生成含原生图表的 xlsx |
| `KWPS.Application` | 已注册 | WPS 可用 |
| `EndNote.Application` | 未安装 | 走 RIS / BibTeX 文件交换 |
| `MathType.Application` | 未安装 | 公式走 Office 原生 OMML |
| `Origin.ApplicationSI` | 未安装 | 图表走 matplotlib / seaborn |

| 需求 | 实现手段 | 可用性 |
| --- | --- | --- |
| LaTeX 编译 | 本机 MiKTeX 工具链（见下方实测） | 可用 |
| BibTeX 管理 | `references.bib` 直接读写 | 可用 |
| 数据整理 | pandas、openpyxl、CSV | 可用 |
| 统计图 | matplotlib、seaborn | 可用 |
| 论文配图 | 绘图技能 + Python | 可用 |
| PDF 解析与生成 | PyMuPDF、pdfplumber、pdf-lib | 可用 |
| 幻灯片 | COM 驱动 PowerPoint（原生可编辑）或 python-pptx | 可用 |
| 原生 Office 文稿 | COM 驱动 Word / Excel | 可用 |
| 公式 | LaTeX 原生；Word 内为 Office OMML | 可用 |
| 文献库交换 | BibTeX / RIS 文件导入导出 | 可用 |
| 学术网站检索 | 浏览器自动化 | 可用 |
| Overleaf 协作 | 双向 git 同步 | 待建 |
| EndNote / MathType / Origin | 未安装，走 RIS / OMML / CSV 替代 | 不可用 |

COM 只用于生成和读取原生文件，不用于无人值守地点击界面。需要人工判断的操作一律停下来问。

### 7.1 LaTeX 工具链实测（2026-10-03）

v1 写的"内置 LaTeX 编译器，无需本地 TeX 安装"不准确。本机装了 MiKTeX，位置在 `<home>\AppData\Local\Programs\MiKTeX\miktex\bin\x64\`。逐项实测：

| 工具 | 状态 | 实测结果 |
| --- | --- | --- |
| `pdflatex` | 可用 | 英文文档 exit 0，产出 PDF |
| `xelatex` + `ctex` | 可用 | 中文文档 exit 0，产出 PDF，字体与断行正常 |
| `bibtex` | 可用 | `pdflatex → bibtex → pdflatex → pdflatex` 四步全 exit 0，PDF 产出 44 KB，`.aux` 中 `\bibcite` 正确生成 |
| `biber` | 已安装，未实测 | 存在，未做端到端验证 |
| `latexmk` | **不可用** | 依赖 Perl，本机未安装，直接报 `MiKTeX could not find the script engine 'perl'` |

这条决定了编译驱动怎么写：**不能调 `latexmk`**，必须由 `latex-check` 自己按 `pdflatex → bibtex → pdflatex → pdflatex` 的顺序执行。反过来这也是好事——显式四步比 `latexmk` 更容易判断"哪一步失败、失败在哪"。

Codex 内置的 LaTeX 编辑器编译器仍然保留，用于交互式预览；脚本化的批量编译走 MiKTeX。

## 8. 知识资源层

### 8.1 第一版

- 共享文献库：`paper-template/library/`，存放读过的 PDF 与 BibTeX。
- 每篇论文的引用从共享库选取，避免重复下载和重复录入。
- 全文检索：SQLite FTS5（零外部依赖，本机已确认可用，SQLite 3.53.1）。

### 8.2 研究记忆

文献库只是存储，记忆是另一层语义。参考 ARIS 的研究记忆，需要四个行为：

1. 读过的文献自动入库，形成可检索条目。
2. 每次选题前先读记忆，避免重复自己。
3. 实验结果能回写 claim 状态。
4. 失败的想法与走不通的路线作为反重复记忆保留，下次选题时主动提示。

第 4 条在 v1 完全缺失。没有它，同一批想法会被反复捡起来撞同一面墙。

记忆文件用固定字段，便于脚本读写：

```yaml
# memory/dead-ends.md 中的一条
- id: DE3
  date: "2026-09-14"
  idea: "用对比学习替代现有多任务损失"
  reason: "消融显示增益来自 batch size 变化，不是损失函数"
  evidence: experiments/results/ablation-contrastive.csv
  reopen_if: "出现新的负样本采样策略"
```

`reopen_if` 这一条让死路可被重新打开。没有它，反重复记忆会变成永久排除，误伤本来可行的方向。

### 8.3 索引 schema

实测结论（SQLite 3.53.1，本机验证）：

| 分词器 | 中文检索 | 结论 |
| --- | --- | --- |
| `unicode61` | 完全失效（连续汉字被当作单个 token，`注意力`、`推理` 均返回 0） | 不可用于中文 |
| `trigram` | 可用，但查询至少需 3 个字符（`注意力` 命中，2 字的 `推理` 不命中） | 主索引用它 |

因此索引分两路：

```sql
CREATE VIRTUAL TABLE papers USING fts5(
  key, title, authors, year, venue, abstract, notes, path,
  tokenize='trigram'
);
```

三字符以上的查询走 FTS5；两字以内的中文查询回退到 `LIKE '%q%'`。个人文献库规模下 `LIKE` 的开销可以接受，不必为此引入分词库。

### 8.4 第二阶段（按需）

语义检索：安装向量库，对 PDF 全文与实验记录建立向量索引。

触发条件：全文检索出现明显召回不足时再上，不提前引入依赖。

## 9. 自动化层

三类定时任务，默认安静，无实质变化不通知。

| 任务 | 频率 | 行为 |
| --- | --- | --- |
| 文献监控 | 每周 | 扫指定关键词与对标工作，仅在有实质重叠或新竞品时通知 |
| 里程碑提醒 | 按 deadline 倒排 | 投稿前 14 / 7 / 3 天检查 gate 缺失项 |
| 阶段推进 | 手动触发 | 读状态、定位阶段、调用技能、更新状态 |
| 实验队列 | 长任务运行期 | 多组种子排队执行，失败重试有上限，看门狗检测卡死 |

硬约束一：自动化只做信息收集与提醒。修改论文正文、修改 `ccfa.yaml` 中的结论字段，必须经明确授权。

硬约束二：长任务必须可中断、可观察、有停止条件。失控的运行脚本会污染结果，比跑得慢更糟。

### 9.1 成本与上下文预算

`paper-machine` 的实测：为省钱把历史上下文压到 24k，成本反而从 $11.99 涨到 $29.75 并最终失败（输入 token 从 11.4M 涨到 27.6M，单会话动作数达到 463）。被饿死的上下文让 Agent 反复重读文件、重跑命令、重新规划。

因此：设定工作上下文的下限，不做盲目压缩；对长会话设动作数上限，触发即停下来汇报，而不是继续消耗。

### 9.2 长任务安全执行

综述把"安全自主执行"列为未解决问题。长任务（多组种子、多小时训练、批量消融）需要四件事：

| 项 | 要求 |
| --- | --- |
| 沙箱 | 实验代码在受控目录运行，只读挂载原始数据，防止脚本改写数据集 |
| 预算 | 每个实验队列声明 GPU 时长上限与并发上限，超限即停 |
| 停止条件 | 声明最大步数、最大时长、失败重试上限，三者任一触发即停 |
| 失败分流 | 运行失败分为"环境问题（可重试）"与"结果问题（必须记录）"，不得静默重试到成功 |

最后一条是要害。把失败的运行重试掉、只留下成功的那次，会直接制造不可复现的结果。失败必须留在 `experiments/log/` 里。

**v1 落地边界（2026-10-04）：** `queue` 已实现同一 `log-dir` 独占锁、
`nvidia-smi` 利用率采样的 GPU 秒预算、`stall_timeout_s` 无输出看门狗，以及
`sandbox: policy`（cwd 必须留在队列根内 + 子进程环境白名单）。这里的
`policy` **不是 OS 级沙箱**：不保证只读数据、不保证禁网、不隔离 GPU；
需要更强的隔离时还可启用下面的 Docker 后端，或另接 WSL / 专用沙箱。
help、计划与账本都按此边界陈述，不把策略层写成容器隔离。GPU 预算按设备
利用率采样，不按 PID 归属；它适合本机单卡的单用户队列，不能在共享 GPU
上替代调度器的配额。

**Docker 沙箱后端（v1.1，2026-10-04）：** `sandbox: docker` 使用受信任
镜像运行队列项：容器根文件系统只读，队列根以只读方式挂载到 `/workspace`，
仅 `docker_output`（默认 `runs`）以可写方式挂载到 `/outputs`，网络默认
`none`，只有 `docker_gpus: all` 时才加 `--gpus all`。Docker daemon 不可用
时直接退 2，不静默回退到宿主机；清单声明 `docker` 时，CLI 降级到
`none`/`policy` 默认拒绝，必须显式 `--allow-sandbox-downgrade`。policy 与
docker 模式默认拒绝注入 runner；测试或高级调用要注入 runner 必须显式
`allow_injected_runner=True`，否则 run-log 可能声称 Docker 而实际在宿主机执行。
容器内只注入显式 `CCFA_WORKSPACE` /
`CCFA_OUTPUT_DIR` 变量，并把 `HOME` 指到 tmpfs（`/tmp`），不继承宿主机环境。
超时或卡死会 kill Docker CLI
并在 `finally` 执行 best-effort `docker rm -f`，避免容器继续占 GPU；宿主
进程被强杀或机器断电后仍可能留下 `ccfa-` 前缀容器，需要用 `docker ps`
人工清理。镜像本身是受信任输入：只读根、mount 与 network 控制是本机单用户
流程的隔离边界，不是对恶意镜像或内核漏洞的安全承诺。

### 9.3 Pilot 筛选与双循环实验账本

对标报告指出的缺口是：`grounded` 之后直接进入实验设计，缺少“小试后再投入”的
筛选环节；单次实验优化与跨实验综合也没有统一台账。v6.1 新增
`data/experiment-loop.yaml` 和 `tools/ccfa/experiment_loop.py`。

账本包含三层：

- `ideas`：候选想法、pilot 预算、metric、kill criterion、run id 与
  promote/reject/park 决策。终态必须有理由；没有 run id 不能声称 pilot 完成。
- `inner_loop`：每次 baseline、调参、修 bug 或消融的 change、hypothesis、
  metric、result 与 keep/revert/continue/stop 决策。result=pending 时不能写
  终结决策；已有 result 时必须写决策。
- `outer_loop`：跨实验综合，绑定 claim 与 evidence run ids，记录
  continue/pivot/write/stop 和下一步动作。

`check` 做确定性的枚举、placeholder、claim/run 交叉引用验证；
`next` 只输出当前待办动作，不自动运行实验、不自动改论文结论。纯 SoK 或
不含实验的论文可以 `not_applicable: true`，但必须写明具体 reason。

### 9.4 投稿后产出物契约

对标报告指出 rebuttal、resubmit、talk 只有 stage 名称，没有产物契约。v6.1
新增 `data/post-submission.yaml` 与 `tools/ccfa/post_submission.py`：

- `rebuttal`：回复矩阵路径、新增证据 run id、承诺清单；complete 时回复矩阵
  必须存在，新增证据 run id 必须能在 `experiments/log/` 中找到。
- `resubmit`：from/to venue、venue 差异表、需要改写的章节；complete 时差异表
  和章节清单不能为空，evidence 必须是真实 run id 或仓库内文件。
- `talk`：slide 大纲；每页必须绑定至少一个真实 claim id，figure id 若出现则
  必须存在于 `figures/manifest.yaml`，并写出 talking points。

三个阶段支持 `not-started`、`in-progress`、`complete`、`not-applicable`；
`not-applicable` 必须有具体 reason。该工具只验证产出物契约与交叉引用，
不判断 rebuttal 是否有说服力、talk 是否讲得清楚。

### 9.5 六维 rigor rubric

对标报告的 P2-13 缺一项可执行的严谨性评分。v6.1 新增
`data/rigor-rubric.yaml`、`tools/ccfa/rigor.py` 与 `scripts/rigor-rubric.ps1`，
固定六个维度：evidence relevance、falsifiability、scope、coherence、
exploration integrity、methodology。

每个维度必须填写 0..4 整数分数、非占位理由和至少一个证据引用。证据可以是
claim id、真实 run id，或仓库内已有文件。`complete` 只能由 `human` 或
`mixed` reviewer 填写；`model` reviewer 只能写 `model-advisory`，不能开释。
standard profile 在台账存在时运行 advisory gate；high-assurance 使用
`--require-complete`，要求真人完成的六维 rubric。该工具验证的是记录完整性
和边界，不替代人的评分判断。

### 9.6 Proof orchestration 与跨天续跑

对标报告的 P2-11 要求把跨天证明战役做成可中断、可续跑的记录，而不是只保留
最后一次成功尝试。v6.1 新增 `data/proof-campaign.yaml`、
`tools/ccfa/proof_orchestrator.py` 与 `scripts/proof-orchestrator.ps1`：

- 每个 campaign 绑定 claim、theorem id 和多次 attempt；attempt 记录策略、
  状态、结果、失败原因、证据和下一步动作。
- `open`/`blocked` campaign 必须有最后的 `next_action`；failed/blocked attempt
  必须写明失败原因。`next` 子命令只输出当前待办，不替人推进证明。
- `proved` 必须同时指向 `proof-audit.yaml` 中 `status=verified` 且由真人复核的
  theorem 记录；模型 reviewer 不能开释。`refuted` 需要 counterexample 证据，
  `abandoned` 需要 abandon_reason。
- standard profile 使用 advisory gate；high-assurance 使用
  `--require-complete`，要求所有 campaign 离开 open/blocked。

### 9.7 周期性工作流自评

对标报告的 P2-14 要求把 `friction_log` 与 gate 失败原因转成改进提案，而不是
靠模型逐次凭印象修改工作流。v6.1 新增 `tools/ccfa/meta_optimize.py` 与
`scripts/meta-optimize.ps1`：

- 合并多个 `friction_log.json`，按 `category + component` 聚合重复次数、
  最高 severity、来源论文、stage 与样例描述。
- 读取 readiness JSON 的 `gate_results[*].problems[*].code`，按
  `gate + code` 聚合重复失败。
- 达到 `--min-count` 的重复模式输出候选提案；工具只读，结果 status 固定为
  `proposed`，必须由人批准后才能改 skill、gate 或代码。
- Markdown/JSON 输出支持落盘不覆盖；不自动修改论文或工作流。

### 9.8 Artifact badge 与长期归档

对标报告的 P2-12 要求把 ACM Artifact Badging 与 DOI 归档变成可核验契约。
v6.1 新增 `data/artifact-badge.yaml`、`tools/ccfa/artifact_badge.py` 与
`scripts/artifact-badge.ps1`：

- `available`：代码/数据/材料可获取，必须有 URL 或 release 证据。
- `evaluated`：第三方重跑主结果，必须有独立真人 reviewer、日期和评估证据；
  模型名不能充当 reviewer。
- `reusable`：第三方在新场景复用，必须有 reuse_context 与复用记录。
- `verified` 需要 DOI 或 archive_url，并记录 code/data license。
- standard profile 在台账存在时做结构检查；high-assurance 使用
  `--require-verified`，要求三类 badge、独立复核与归档证据完整。

### 9.9 Research Wiki 与跨项目记忆

对标报告的 P2-10 需要把文献、决策、死路、方法和结果累积成跨项目记忆，
而不是每篇论文各自重读。v6.1 新增 `library/wiki/`、
`tools/ccfa/research_wiki.py` 与 `scripts/research-wiki.ps1`：

- 每个条目是带 YAML frontmatter 的 Markdown 文件，字段固定为
  `id`、`kind`、`title`、`status`、`tags`、`projects`、`evidence`、
  `related`、`updated_at`。
- `kind` 支持 source/claim/decision/dead-end/method/result；`related` 必须指向
  真实存在的 wiki id，evidence 使用 `run:`、`file:`、`doi:`、`url:`、
  `claim:` 或 `project:` 前缀。
- `index` 生成确定性 JSON 索引（含 body sha256），`search` 只在本地索引上做
  大小写不敏感的确定性子串搜索；Markdown 是 source of truth，索引可重建。
- 该层不自动创造结论，也不替代每篇论文的 claim/proof/experiment 台账。

### 9.10 跨论文 dashboard

为避免使用者在 20 多条命令之间来回切换，v6.1 新增
`tools/ccfa/dashboard.py` 与 `scripts/dashboard.ps1`。它扫描 `papers/` 下每个
含 `ccfa.yaml` 的独立仓库，复用 `readiness.build_report`，输出一页跨论文
Markdown/JSON：

- 阶段、profile、ready/blocked 状态；
- 第一条阻塞项作为 `next_action`；
- 人工复核 pending、git dirty、remote 和 workflows 状态；
- 总计 ready/blocked/human-pending/dirty 数量。

它不是新的科学 gate，只是把已有 gate 结果汇总成可操作的控制台。

### 9.11 源码对齐第一切片：research-state

参考 `Orchestra-Research/AI-Research-SKILLs` 的
`0-autoresearch-skill/templates/research-state.yaml`，v6.1 新增
`tools/ccfa/research_state.py` 与 `scripts/research-state.ps1`。它把项目级
`literature`、`hypotheses`、`experiments.trajectory`、`outer_loop` 与
`workspace` 变为可校验状态：

- hypothesis id 必须唯一，parent 必须存在；
- trajectory run_id 必须指向真实 run-log；total_runs 必须等于 trajectory 长度；
- outer_loop 只允许 deepen / broaden / pivot / conclude；
- workspace 中的 findings、log、literature、experiments、to_human、paper
  路径必须真实存在；
- `next` 选择最高优先级未闭环 hypothesis，输出下一步实验动作。

该文件当前是可选的项目级状态层，不替代 claim-registry、experiment-loop 或
run-log；它是对齐 two-loop 编排的第一切片，不是 ARA 五层 artifact 的完整复刻。

### 9.12 源码对齐第二切片：ARA draft compiler

按 `AI-Research-SKILLs/22-agent-native-research-artifact/compiler` 的目录结构和
Seal Level 1 checklist，v6.1 新增 `tools/ccfa/ara_compile.py` 与
`scripts/ara-compile.ps1`：

- `compile` 生成 `PAPER.md`、`logic/`、`src/`、`trace/`、`evidence/`
  的 mandatory 文件骨架。
- claim registry 会映射为 C01+；run/experiment 会映射为 E01+，并建立
  claim↔experiment 的交叉引用。
- exploration graph 会转换为嵌套 YAML research DAG；dead-end、rejected 和
  pivot 分别映射到 ARA 的 dead_end / pivot 节点。
- 无法从结构化台账恢复的语义层会明确写成 draft gap，`compile-report.json`
  列出 `concepts>=5`、`experiments>=3`、`src/execution/*.py`、
  `trace_decision` 等未满足项。
- 如果 `ara-input/` 提供 problem、concepts、solution、related_work、
  experiments、configs、trace、evidence 和 code stubs，compiler 会生成完整
  ARA 并可真正通过 Seal Level 1；没有语义输入时仍保持 draft gap。
- `validate` 按 Seal Level 1 的目录、mandatory file、计数、trace 字段和
  cross-layer 条件报告 problem。

该 compiler 不会把 draft 误报为 Seal Level 1 通过，也不会为通过结构校验而
编造 concepts、heuristics 或 code stubs。

### 9.13 源码对齐第三切片：ARIS proof run directory

按 `wanshuiyin/Auto-claude-code-research-in-sleep` 的
`skills/proof-orchestrator/SKILL.md`，v6.1 新增 `tools/ccfa/proof_run.py`
与 `scripts/proof-run.ps1`：

- `materialize` 从一个 proof campaign 创建 run directory，包含 `task.md`、
  `materials.md`、`local-proof.md`、`source-manifest.md`、`codex-ledger.md`、
  `audit.md`、`final.md`、`next.md` 和 `sources/`。
- run directory 必须位于 paper root 内；已存在时必须显式 `--force`。
- `check --require-closed` 要求 status 为 `READY_FOR_USER`，final 不能仍是
  draft，并要求 `Top-down derivation structure: PASS`。
- `check --notation-required` 解析 ARIS notation scorecard，核心语义对象保留
  必须 100%，undefined symbols 与 symbol collisions 必须为 0。
- 这个工具负责续跑、审计和 handoff 骨架，不自动证明、不替人批准定理。

### 9.14 源码对齐第四切片：ARIS typed graph wiki

按 ARIS `skills/research-wiki/SKILL.md`，扩展 `tools/ccfa/research_wiki.py`：

- `kind` 增加 paper、idea、experiment、claim、gap，保留原有 source、decision、
  dead-end、method、result。
- 新增 `graph/edges.jsonl`，支持 extends、contradicts、addresses_gap、
  inspired_by、tested_by、supports、invalidates、supersedes 八类边。
- 每条 edge 必须绑定真实 from/to wiki id 和非空 evidence。
- `add-edge` 追加边而不是重写文件；`check` 与 `index` 会同时校验实体和边。
- `query-pack` 生成紧凑 Markdown，包含实体、边和 kind counts，供下游 ideation
  或检索消费。
- `sync` 从 `library/refs.bib` 批量创建缺失的 paper card；`rebuild` 重新生成
  `index.md` 与 `gap_map.md`；`append-log` 维护 append-only `log.md`。

Markdown 实体和图边是 source of truth；index 与 query pack 是生成物。

### 9.15 源码对齐第五切片：hash-chained run ledger

按 `Imbad0202/academic-research-skills` 的
`shared/contracts/passport/run_ledger.schema.json`，v6.1 新增
`tools/ccfa/run_ledger.py` 与 `scripts/run-ledger.ps1`：

- 在 `experiments/log/run-ledger.jsonl` 维护 append-only peer ledger。
- 每条 entry 包含 seq、kind、at、run_id、record_path、record_sha256、
  command、status、exit_status、prev_hash 和 hash。
- hash 是 entry 去掉 hash 字段后的 canonical JSON SHA-256。
- `sync` 对缺失或变化的 run record 追加新 entry；同一 run_id 的新 entry 覆盖
  latest 比较，但旧记录永不删除或重写。
- `check` 检测 JSON 损坏、seq 跳号、prev_hash/hash 不匹配、run record 缺失、
  ledger orphan，以及 record 已变化但 ledger stale。

该 ledger 不替代 `run_log.py` 的实验记录，只提供防意外损坏的追加式证据链；
它不是密码学签名，不能抵抗拥有完整写权限的人重写整个文件。

### 9.16 源码对齐第六切片：ARIS review loop state

按 ARIS `skills/auto-review-loop/SKILL.md`，v6.1 新增
`tools/ccfa/review_loop.py` 与 `scripts/review-loop.ps1`：

- `reviews/review-loop-state.json` 记录 run_id、round、max_rounds、status、
  executor/reviewer model、backend、family relation、last verdict 与
  cross-review sha256。
- `reviews/reviewer-memory.md` 追加每轮 verdict、family 和 blocking 标题。
- `reviews/ACQUITTAL_LOG.jsonl` 只在真正 cross-family pass 时追加，且为
  append-only。
- 同族或未知族即使 cross-review 返回 pass，也只能进入 blocked 并标记
  `requires_external_acquittal`，不能 completed。
- `check` 检测 state 非法、review stale、self-acquittal、缺 memory 或
  malformed acquittal log；`next` 输出 run-review、fix-blockers、
  configure-cross-family-review、blocked-max-rounds 或 stop。

该 state machine 负责门禁和续跑，不自动修稿、不自动开释。
`drive` 可注入 fix/review JSON argv，按 fix → review → record-round 循环，
直到 cross-family pass、需要外部开释或达到 max rounds；CLI 本身不生成修复
内容，修复动作由调用者提供的命令负责。

### 9.17 源码对齐第七切片：risk capability matrix 与 data flows

按 academic-research-skills 的 `docs/RISK_REGISTER.md` 与
`docs/DATA_FLOWS.md`，v6.1 新增 `tools/ccfa/governance_map.py` 与
`scripts/governance-map.ps1`：

- `data/capability-matrix.yaml` 逐项记录 stage、control、behavioral evidence
  status 和 evidence。
- `data/risk-register.yaml` 在 capability matrix 存在时必须为每条风险记录
  controls、evidence_status、residual_gap；controls 必须解析到真实 capability
  id。
- `data/data-flows.yaml` 逐项记录 network touchpoint 的 endpoint、purpose、
  sends、credentials、off switch，以及 local store 的 path、content、
  lifetime、delete。
- `check` 拒绝未知 control、非法 capability status 和明显明文凭据；
  `render` 从 YAML 生成 `docs/data-flows.md`。
- status 词表固定为 DESIGNED / NOT_RUN / MEASURED / MIXED，避免风险登记册
  用自造状态掩盖未运行证据。

### 9.18 源码对齐第八切片：open-science immutable artifact

按 `aipoch/open-science` 的 immutable artifact、provenance 和 `.science`
portable package 概念，v6.1 新增 `tools/ccfa/artifact_store.py` 与
`scripts/artifact-store.ps1`：

- artifact 以 SHA-256 内容寻址，存放于
  `ccfa-workfiles/artifact-store/blobs/`。
- `manifest.json` 为每个逻辑 artifact 保留递增 version，不覆盖旧版本。
- `put` 在内容不变时幂等；内容变化时追加新版本。
- `verify` 检测 blob 缺失、hash 不匹配和 version 跳号。
- `replay` 返回某 artifact 的版本、run_id 与来源路径。
- `package` 生成 `.science` zip，包含 manifest、blobs、run ledger、
  provenance 和 verify receipt。

该层是内容不可变与可追踪契约，不宣称能科学上复现结果，也不替代 repro
package 的执行验证。

### 9.19 源码对齐第九切片：resubmit 与 talk pipeline

按 ARIS `docs/RESUBMIT_AND_TALK.md`，v6.1 新增：

- `tools/ccfa/resubmit_pipeline.py` / `scripts/resubmit-pipeline.ps1`
- `tools/ccfa/talk_pipeline.py` / `scripts/talk-pipeline.ps1`

resubmit guardrails：

- source 与 target 必须物理隔离；
- target bib hash 必须等于 frozen hash；
- target 不得出现 frozen run_ids 之外的 experiment run；
- forbidden path 的内容必须与 source 一致；
- target 文本不得出现 plan 中的 anonymity patterns。

talk contract：

- slide 必须有 title、claim_ids、figure_ids、talking_points、speaker_notes；
- claim/figure id 必须解析到 claim registry 与 figure manifest；
- conference-ready 必须有 speaker notes 和 Q&A；
- `render` 输出可直接供 `/paper-slides` 或汇报准备的 outline。

这些 pipeline 做确定性 guardrail，不替代真正的文本润色、视觉 polish 或
adversarial review。

### 9.20 源码对齐第十切片：passport ledger 与 citation calibration

按 academic-research-skills 的 passport run ledger 与 citation calibration，
v6.1 新增：

- `tools/ccfa/passport_ledger.py` / `scripts/passport-ledger.ps1`
- `tools/ccfa/citation_calibration.py` / `scripts/citation-calibration.ps1`

passport ledger：

- 以 `ccfa-workfiles/passport/run-ledger.yaml` 单独保存 initial
  instructions、checkpoint opened/closed、partial answer、tool receipt、
  progress 和 file reference；
- 每条 entry 有 seq、kind、at、data、prev_hash、hash；
- `check` 检测 seq、prev_hash、entry hash、kind 和 kind-specific 必填字段；
- `render` 生成 human-readable passport timeline。

citation calibration：

- gold 与 prediction 使用 JSONL；
- 计算 TP/FP/TN/FN、FNR、FPR；
- 默认阈值 FNR≤0.15、FPR≤0.10，缺失或非法 prediction 一律 fail closed；
- 该工具测量 citation judge，不替代真实 claim-support 审核。

### 9.21 源码对齐第十一切片：官方 venue checklist fixture

为消除“通用 checklist schema 已存在、官方条目仍未固化”的缺口，v6.1 新增：

- `checklists/neurips-paper-checklist.yaml`
- `checklists/arr-responsible-nlp.yaml`
- `tools/ccfa/venue_fixtures.py` / `scripts/venue-fixtures.ps1`

每个 fixture 固定记录 venue、source 和 item id/category/requirement/required。
`check` 校验 fixture 结构；`seed` 把 fixture 转成论文的
`data/venue-checklist.yaml`，初始状态全部为 pending，不伪造完成。标准发布
前仍需作者逐条填写 evidence、owner 和 status。

### 9.22 源码对齐第十二切片：open-science session replay

按 open-science 的 session replay 与 artifact provenance view，v6.1 新增
`tools/ccfa/session_replay.py` 与 `scripts/session-replay.ps1`：

- 串联 passport ledger、run-ledger.jsonl、artifact store manifest 和
  review-loop state；
- 输出 read-only replay timeline；
- `check` 检测 artifact 的 run_id 是否能在 run/passport ledger 中解析；
- `render` 生成静态 HTML，显示每个 passport event、run、artifact version 和
  review state；
- replay 不执行代码、不恢复凭据，也不是科学正确性证明。

## 10. 目录结构

模板库：

```
paper-template/
  ccfa.yaml.template
  README.md
  docs/
  scripts/
    new-paper.ps1
    citation-guard.ps1
    trace-claims.ps1
    provenance.ps1
    run-log.ps1
    repro-package.ps1
    latex-check.ps1
    final-check.ps1
  checklists/conference.md
  checklists/journal.md
  library/
    refs.bib        # 共享 BibTeX，纳入 git
    papers/         # PDF 原件，不纳入 git
    index.db        # FTS5 索引
```

单篇论文：

```
papers/<slug>/
  ccfa.yaml
  manuscript/
    main.tex
    sections/
    references.bib
  data/
    provenance.json  # 机器可读来源登记，纳入 git
    provenance.md    # provenance export 生成的人读来源文档
  experiments/
    design.md
    log/            # 每次运行的配置、种子、commit、退出码、指标
    results/
  figures/
    manifest.yaml   # 图表溯源：来源 run、生成脚本、哈希、正文引用位置
  tables/
  reviews/
    revision-ledger.md
  submission/
    checks.md
    repro/
  memory/
    ideas.md        # 选题记忆
    dead-ends.md    # 反重复记忆
  ccfa-workfiles/
    literature/
    figures/
    writing/
```

## 11. 待确认

- 模板库位置是否确定为 `<home>\Documents\Codex\paper-template\`。
- 是否现在建立示例论文目录跑通派生流程。
- 文献监控的初始关键词与对标工作。
- 共享文献库是否纳入 git（PDF 默认不纳入，只纳入 BibTeX）。
- 跨模型评审：默认 `deepseek-v4-pro` 仍与执行模型同族；要过默认 gate 必须配不同 family 的 provider。显式 override 现在必须 `--allow-same-family --override-reason <≥20 字符>`，原因写入记录；`check --strict-cross-family` 会把任何同族 override 报成 problem。
**已定**：第 6.1 节的 9 个工具全建（用户 2026-10-03 决定），分六个实施计划推进。

## 12. 验收标准

- 能通过一条命令派生出一篇新论文的完整目录，且 LaTeX 模板可编译。
- 会议与期刊两种模式切换后，阶段流与 gate 清单正确变化。
- `ccfa.yaml` 能被正确读取和更新，中断后可恢复。
- 全文检索能对共享文献库返回有效结果。
- 四类自动化任务建立后，默认不产生噪声通知。
- `citation-guard` 能对含虚构条目的草稿报出全部虚构引用（用已知的 4 条虚构样本做回归）。
- `trace-claims` 能在凭空改掉一个 `\dataval` 数字后成功报错；正文写 `0.143`、源值为 `0.142857…` 时**不**误报（第 6.4 节隐含舍入容差生效）。
- `trace-claims` 能正确解析含字面点的键（`sweep.0\.5x_4ms.stat`）与 CSV 行寻址（`4.lcoe`）。
- `trace-claims` 对试图经 `..` 逃出 `--base-dir` 的标签报 problem（退出码 1），对被检查文档路径不存在报工具错误（退出码 2）。
- `trace-claims --untagged` 能列出未标记的数字线索，且 advisory 不改变退出码。
- `latex-check` 能在五类输入上分别报出对应 code：`unbalanced-brace`、`unmatched-environment`、`missing-cite-key`、`missing-figure`，以及 advisory `stray-percent`。
- `latex-check` 的结构扫描忽略注释内的花括号与环境（注释里写 `{` 不得造成误报）。
- `latex-check` 不开 `--compile` 时一个字节也不写；开了 `--compile` 且引擎缺失时退出码 2，编译失败时退出码 1。
- `final-check` 能在渲染后的 PDF 文本含未解析 `?` 标记时报 `unresolved-marker`；PyMuPDF 不可用时该项记为 skipped（以 advisory 形式可见），**不是通过**。
- `final-check` 的 skipped 结果在 JSON 里与"通过"可区分（通过不出现在报告中，skipped 出现在 advisory 列表里）。
- `final-check` 能在故意把 JPEG 改名成 `.png` 的文件上报警。
- 复现包在干净环境实际重跑成功。
- 审稿意见矩阵的"承诺风险"列能挡住一条"承诺了未完成实验"的回复样例。
- 图表 manifest 能检出无正文引用、生成脚本哈希不符、字节格式与扩展名不符三种情况。
- 索引对三字以上中文查询走 FTS5、两字查询回退 `LIKE`，两者均能命中。
- 实验队列在超过预算或重试上限时停止，且失败运行保留在 `experiments/log/`。
- 工具自身出错时返回退出码 `2`，不会被误判成检查通过。
