# 科研工作流：插件工具清单与开源对标缺点分析

日期：2026-10-06
范围：本仓库工作流自身的工具、配置的 MCP/插件/skills、已安装 CLI，以及相对于 GitHub 开源科研系统与智能体的差距

## 一句话结论

工具层已经完整：`doctor` 报 0 problems / 0 advisories，87 个工具模块、72 个入口、9 个 MCP、28 个插件、305 个 skills、25 类 CLI、9 个形式化引擎。剩下的缺点集中在**度量缺口、外部资源未接通、以及必须由人完成的验证**，不再是插件或工具不足。

## 一、工作流自身的工具（仓库内，87 模块 / 72 入口）

### 状态与编排

`state`、`stages`、`dispatch`、`long_task`、`watch`、`autoresearch`、`experiment_loop`、`experiment_optimizer`、`research_state`、`queue`

### 证据与核验

`dataval`/`datavalue`、`trace_claims`、`citation_guard`、`citation_ledger`、`citation_calibration`、`doi_lookup`、`bib`、`provenance`、`datasource`、`figure_manifest`、`figurebytes`、`pdftext`、`run_log`、`run_ledger`、`passport_ledger`

### 论证与评审

`argument_audit`、`cross_review`、`review_loop`、`proof_run`、`proof_orchestrator`、`formal_check`、`verifiers`、`rigor`、`human_coding`、`claims_policy`、`claim_extract`、`research_ledgers`、`novelty`、`stats_plan`、`governance`、`governance_map`

### 写作与交付

`latex_check`、`latex_compile`、`latex_structure`、`texdoc`/`texscan`/`texcomment`、`final_check`、`revision_ledger`、`post_submission`、`resubmit_pipeline`、`talk_pipeline`、`venue_fixtures`、`reference_audit`

### 知识管理

`library`、`memory`、`research_wiki`、`dashboard`、`skill_registry`、`skillpack`

### 平台与运维

`doctor`、`readiness`、`e2e_check`、`change_log`、`compute`、`archive_client`、`artifact_store`、`artifact_badge`、`repro_package`、`repro_container`、`repro_env`、`worktree_audit`、`test_impact`、`meta_optimize`、`friction_log`、`toolchain`、`session_replay`、`ara_compile`、`ara_extract`、`external_adapters`、`cli`、`validate`

对应 72 个 `scripts/*.ps1` 入口，全部经 `dispatch` 映射，可无 PowerShell 运行。

## 二、MCP 服务器（9）

| 名称 | 用途 |
| --- | --- |
| `arxiv` | arXiv 检索与全文 |
| `semantic_scholar` | 引文图与语义检索 |
| `zotero` | 本地文献库读写（已实测 HTTP 200） |
| `academic_search` | 综合学术检索 |
| `paper_search` | 论文检索 |
| `overleaf_olcli` | Overleaf 工程操作 |
| `github` | 仓库、PR、Actions |
| `node_repl` | 浏览器与原生控制 |
| `consensus_bridge` | Consensus 学术证据检索 |

## 三、启用的插件（28）

- **文档与写作**：documents、pdf、spreadsheets、presentations、template-creator、latex、deep-research
- **研究检索**：consensus、github（两个来源重复启用）、zotero
- **工程与安全**：code-review、codex-security、api-blackbox-tester、sentry、superpowers
- **设计与演示**：figma、canva、remotion、visualize
- **协作**：notion、linear
- **桌面与浏览**：browser、chrome、computer-use、unified-computer-use、computer-use
- **领域专用**：boltz-api-cli（结构生物学）

## 四、已安装 CLI（`doctor` 0/0）

- **版本控制与 CI**：git、gh、git-lfs
- **容器**：docker（daemon 可达）
- **LaTeX**：pdflatex、xelatex、bibtex、latexmk
- **PDF 与文档**：gswin64c、qpdf、mutool、soffice、pandoc
- **排版**：typst、quarto
- **数据与环境**：dvc、micromamba、jupyter、Rscript
- **图形与图像**：inkscape、magick、ffmpeg、tesseract、pdfcrop
- **工程**：codex、node、npx、uv、uvx、cmake、7z、perl
- **形式化（9/9）**：z3、cvc5、lean、coqc、isabelle、agda、why3、sage、julia

## 五、Skills（`.codex/skills` 67 + `.agents/skills` 238）

| 类别 | 数量 | 代表 |
| --- | --- | --- |
| 文献与检索 | 47 | literature-review、arxiv-search、paper-lookup、deep-research、exa-search、paperclip |
| 写作与评审 | 71 | academic-paper、paper-write-sci、latex-paper-en、nature-polishing、rebuttal-writing |
| 数据与统计 | 19 | statsmodels、pymc、scikit-learn、matplotlib、seaborn、shap、figure-generation |
| 知识库 | 9 | obsidian-project-kb-core、zotero-obsidian-bridge、pyzotero、open-notebook |
| 中文文献 | 10 | cnki-search、cnki-download、cnki-journal-index 等全套 |
| 投稿与基金 | 20 | ccf-rank、paper-select-journal、cover-letter、nsfc-* |
| 复现与工程 | 5 | reproduce、uv-package-manager、modal |

## 六、对标的开源系统

| 系统 | 结构贡献 |
| --- | --- |
| SakanaAI/AI-Scientist | 想法→实验→论文→自动评审全自动闭环，模板绑定，容器化 |
| SamuelSchmidgall/AgentLaboratory | 文献→实验→报告三阶段；算力 notes；AgentRxiv 累积 |
| Orchestra-Research/AI-Research-SKILLs | 98 skills / 23 类；`autoresearch` 双循环；ARA（claims + exploration graph + evidence + code stubs）；六维 rigor-reviewer |
| wanshuiyin/ARIS | 83 个可组合 skill；跨模型对抗评审；Research Wiki；proof orchestrator；resubmit/talk pipeline |
| Imbad0202/academic-research-skills | 人在环；hash-chained run ledger；passport ledger；risk register；data flows |
| gxCaesar/open-research-skills | 10 个可独立安装 skill；公开对照评测与自身缺陷 |
| aipoch/open-science | 本地工作台；不可变 artifact；`.science` 包；session replay |
| facebookresearch/MLGym | 13 个开放研究任务的智能体基准 |
| dualverse-ai/station | 多智能体开放研究环境与共享文献 |
| GuoCheng24/breakthrough-harness | 纪律层：null model、held-out、claim polarity、guard 必须被演示失败、尝试吞吐 |
| AmberLJC/ara-paperbench | 机器可读、可复现优先的 artifact 规范 |
| reproducibility-sec/reproducibility | 顶会论文复现性实证研究 |

## 七、已经吸收的对标能力

经代码核对，上一轮提出的方法学建议**大部分已落地**：

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| claim 中心化 | ✅ | `claim-registry.yaml` 串联 proof / experiment / figure / citation / assumption / limitation |
| 探索图与死路 | ✅ | `exploration-graph.yaml` |
| claim 极性 | ✅ | `polarity` 出现 13 处，`descriptive` 不得写成发现性 |
| held-out 纪律 | ✅ | `held_out` 出现 56 处，效果类 claim 必须带 held-out 计划 |
| 对照运行 | ✅ | 效果类 claim 必须引用 negative-control / ablation / baseline |
| 负控 | ✅ | `run_log.VALID_ROLES` 含 `negative-control`；`research_ledgers` 强制 |
| guard 失败演练 | ✅ | `data/gate-failure-drills.yaml` + `gate-drill-not-triggered` 等校验 |
| 双循环编排 | ✅ | `experiment_loop.py` + `experiment_optimizer.py` |
| 不可变 artifact | ✅ | `artifact_store.py` 内容寻址 + `session_replay.py` |
| 跨仓库 CI 与提交门 | ✅ | 两个仓库 Actions + fail-closed `submission-gate` |

## 八、仍然存在的缺点

### 1. 缺少"零技能基线"的度量要求（承自 breakthrough-harness 第 1 条）

有 `negative-control` 运行角色，但没有要求报告"一个什么都没学到的方法会得多少分"。对 SoK 而言，缺的是：随机编码器的一致率是多少、只按标题编码会得到什么矩阵、kappa 是否显著高于按先验比例随机猜。代码里 `null model` 命中数为 0。

### 2. 缺少尝试吞吐度量

`time_to_first_attempt` 命中 0，`cost_per_attempt` 仅 1 处，`cost_usd`/`token_cost` 为 0。没有度量"从想定冻结到第一次可评分实验要多久"，就无法发现"审计替代尝试"的滑坡。这是 breakthrough-harness 的核心论据。

### 3. 远程算力未接通

`compute.py` 已实现 Slurm / PBS over SSH 适配器，但**必须存在 `data/compute.yaml` 才生效**，当前论文没有该文件，因此远程后端为空，只有本机 + Docker。

### 4. 外部归档未验证

`archive_client.py` 已实现 Zenodo（InvenioRDM）与 OSF，token 取自 `ZENODO_TOKEN` / `OSF_TOKEN`。但代码内注释记录：本机解析 `zenodo.org` 异常，HTTP 到 Zenodo 出不去。也就是说**契约在、链路未通**，DOI 尚未取得。

### 5. 安装版缺干净机器验收

`dist/ccfa-workbench-setup-0.1.0.exe` 已构建，本机 `--self-check` 通过（`probe_ok=true`），但尚未在未装开发环境的机器上完成安装、启动与工具调用验收。

### 6. 六项人工复核未完成

`e2e-check` 列出的待人工项：proof（8 条）、citation-support（6 条）、figure-support（1 条）、cross-review、claim-candidates 晋升、research-plans 审批。这是 `ready=false` 的直接原因。

### 7. 评审模型能力不足

`cross-review` 当前由 `qwen3:30b` 出具，被判定 `review-advisory-only`，加上 15 条 `review-contradiction` 与 4 条 `review-unevidenced-pass`，合计 20 条否决。要转绿需要：补完人工台账 + 换成 gate-capable 评审（≥32B 且模型名带参数量，或非本地不同 family provider）。

### 8. governance 台账仍是占位

COI、查重工具、披露联系人仍是 pending 文本，`ccfa.governance` 报 3 个 problem；因不在 standard profile 的必需集合里，所以不阻塞，但也没被解决。

### 9. 工具自身缺少外部基准评价

MLGym（13 个开放研究任务）、Simreal-MLBench 这类基准用来评价**智能体本身**。你的工作流从未用外部基准评估过自己，因此"工作流提升了多少科研产出"只有内部台账，没有对照。

### 10. 轻微冗余

同时启用了两个来源的 GitHub 插件（`github@openai-api-curated` 与 `github@zhongjingyun-codex-plugins`），功能重叠；`computer-use@openai-bundled` 与 `unified-computer-use@openai-bundled` 亦重叠。

## 九、优先建议

1. **补零技能基线**：给 kappa、覆盖率、矩阵统计各加一条负控报告要求，写进 `rigor-rubric` 或 `statistics-plan`。
2. **加尝试吞吐指标**：在 `cost-ledger` 或 `experiment-loop` 增加 `time_to_first_attempt` 与 `cost_per_attempt`，并在 `e2e-check` 里显示趋势。
3. **接通远程算力**：写 `data/compute.yaml`（哪怕只配一台），验证 `probe_remote` 返回真实后端。
4. **打通归档链路**：解决 `zenodo.org` 解析问题后跑一次 draft，取得 DOI。
5. **干净机器验收安装包**：在一台无开发环境的机器上跑安装 + 自检 + 一次工具调用。
6. **完成六项人工复核**：这是唯一能把 `ready` 从 false 变 true 的路径。
7. **清理重复插件**：二选一保留 GitHub 与 computer-use。
8. **引外部基准**：选 1-2 个 MLGym 式任务，用外部评分度量工作流本身。

## 十、总结

工具与插件这一层已经没有缺口：MCP 9 个、插件 28 个、skills 305 个、CLI 25 类、形式化引擎 9 个、仓库内 87 个模块，`doctor` 全绿，两个仓库 CI 与提交门齐备。上一轮的方法学建议（claim 极性、held-out、对照运行、guard 失败演练、双循环、不可变 artifact）也基本吸收。

当前缺点可以归成三类：**度量缺口**（零技能基线、尝试吞吐）、**外部资源未接通**（远程算力、Zenodo DOI、干净机器验收）、**人工验证未完成**（六项复核、governance 占位）。前两类是工程可解的，第三类只能由人来做。