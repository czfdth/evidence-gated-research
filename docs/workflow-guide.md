# 科研工作流日常操作手册

日期：2026-10-04

这份手册回答一个问题：**打开仓库后，今天具体该做什么。**

产品能力与边界见 `docs/research-workflow-intro.md`；工具的底层契约见
`docs/design/2026-10-03-research-workflow-design.md`；本手册只保留日常操作路径。
自动推进与人工批准的边界见 `docs/autonomy-policy.md`。

## 1. 心智模型

每篇论文是一个独立 git 仓库。研究过程由三样东西组成：

1. `ccfa.yaml`：现在处于哪个阶段，当前 gate 是什么。
2. 论文目录中的证据文件：数据、运行日志、手稿、图表和人工复核账本。
3. 根仓库中的工具：只检查或更新证据，不替研究者判断科学真伪。

日常循环固定为：

```text
读状态 -> 处理当前 gate -> 运行定向检查 -> 人工复核 -> 提交论文仓库 -> 推进阶段
```

不要同时追求所有 gate 全绿。只处理当前阶段和下一阶段真正需要的材料。

## 2. 首次准备

在模板仓库根目录执行：

```powershell
python -m venv tools/.venv
& tools/.venv/Scripts/python.exe -m pip install -r tools/requirements.txt

py -3.12 -m venv app/.venv
& app/.venv/Scripts/python.exe -m pip install -r app/requirements.txt

scripts/doctor.ps1
scripts/dashboard.ps1 --papers-root papers
```

`doctor` 的 `found` 只表示命令可被发现；Docker daemon 会额外执行真实探测。
准备使用所有可选能力时运行 `scripts/doctor.ps1 --strict`。

Codex 桌面版把 CLI 装在版本化目录（`%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\`），
不会写进持久 PATH。工作流因此有两层兜底：`cross_review` 自己会解析最新版本，
另外在 `<home>\.local\bin\codex.cmd` 放一个稳定 shim，让普通终端里的
`codex`、`doctor` 也能直接用；后者在 Codex 升级后无需改动。

工作流支持三个 readiness profile：`minimal` 用于构思和短稿，`standard` 用于普通会议论文，`high-assurance` 用于安全、医学、正式证明或高风险研究。默认是 `standard`，也可在 `ccfa.yaml` 写 `workflow.profile`。

### 证明 guard 真的会失败：`data/gate-failure-drills.yaml`

一个 guard 只有**被看到拒绝过东西**之后才可信。gate 一多，很容易积累从未触发过的守卫，
而“不会失败的 guard”和“没接线的 guard”无法区分。所以 readiness 会对照
`data/gate-failure-drills.yaml`：有演练记录的 gate 算已演练，其余进 `unproven_guards`
并报 `unproven-guard`（advisory，不阻塞）。报告里的 `unproven_guards` 字段给出完整清单。

```yaml
version: 1
drills:
  - gate: formal-check
    method: 声明 expected_status=proved、但实际输出 status=unknown 的检查
    triggered: true
    evidence: reviews/drills/formal-check.json
    date: 2026-10-05
```

记录必须同时满足：`triggered: true`；`evidence` 指向真实存在的文件；若 evidence 是 JSON，
文件里的 `triggered` 也必须是 `true`。缺证据或证据显示没触发都是 **problem（会阻塞）**，
不是 advisory——声称演练过却拿不出失败证据，比不演练更糟。

**新增 gate 的纪律**：每加一个 gate，必须在同一个提交里附上它的失败演练记录，否则下一次
readiness 会把它列进 `unproven_guards`。演练要指出「破坏了什么、gate 用什么错误码拒绝」，
而且必须排除崩溃、模块缺失、CLI 用法错误这些假失败——那几种都不是 gate 在工作。

## 3. 创建论文

```powershell
scripts/new-paper.ps1 my-paper `
    --venue NeurIPS --year 2027 --mode conference --title "My Paper"
```

默认目录是 `papers/my-paper/`。它会成为独立 git 仓库并包含初始提交。

创建后立即确认：

```powershell
scripts/validate.ps1 papers/my-paper/ccfa.yaml
scripts/milestones.ps1 stage --paper-root papers/my-paper
git -C papers/my-paper status --short
```

期望结果：状态文件合法、stage 为 `idea`、论文仓库没有未预期改动。

## 4. 每日开工

把论文路径放进一个短变量，减少误操作：

```powershell
$paper = "papers/my-paper"
scripts/milestones.ps1 stage --paper-root $paper
scripts/readiness.ps1 --paper-root $paper --out reviews/readiness.md
scripts/milestones.ps1 due --paper-root $paper
git -C $paper status --short
```

然后只回答五个问题：

1. 当前 stage 和 gate 是什么？
2. readiness report 的 `schema-valid`、`evidence-present`、`gate-verified`、`independently-reviewed`、`scientifically-accepted`、`collaboration-ready` 各是什么状态？
3. `due` 是否提示临近节点或缺口？
4. 工作树里哪些改动是今天要继续的？
5. 当前 gate 缺的是研究工作、人工判断，还是可机械修复的材料？

`readiness` 会执行当前 profile 对应的 gate。`evidence-present` 只表示文件齐全；`gate-verified` 才表示下游检查器真实通过。人工审计仍是 pending、cross-review provenance 不完整或 lockfile 漂移时，报告必须为 `ready=false`。

`human_review.checkpoints` 把每条待人工项展开成**可回答的问题**：

- `question`：要人判断的到底是什么；
- `answer_with`：答案要写成什么；
- `ledger`：答案落在哪个台账。

`reviews/readiness.md` 的 `## Human Checkpoints` 段就是当天“必须由人决定”的清单。
脚本只能证明它还没被回答，不能替你回答。

会话恢复只装载聚焦上下文：新会话先读 `ccfa.yaml`、`reviews/readiness.md` 和当前 claim 的条目，
不要把全部候选想法、全部台账历史一起塞进上下文。

新论文模板已经包含 claim registry 与研究循环台账。填完一个 claim 后运行：

```powershell
scripts/research-ledgers.ps1 --paper-root $paper
```

它检查 claim→proof/experiment/figure/citation/assumption/limitation 的链接，
以及 venue checklist、artifact provenance、探索图、成本账本和风险登记册。

## 5. 阶段操作表

### `idea`：定义问题

必须产出：问题陈述、可检验假设、目标 venue。

```powershell
scripts/memory.ps1 --paper-root $paper check
scripts/library.ps1 --dir library search "your topic"
```

先检索个人记忆和共享文献库，避免重复做已经放弃或已经完成的方向。

### `grounded`：建立新颖性依据

必须产出：检索范围、检索日期、至少三篇最近邻、重叠与逐 claim 差异。

主要文件：`data/novelty-audit.yaml`、`manuscript/references.bib`。

```powershell
scripts/novelty.ps1 --paper-root $paper
```

这一步不能证明“世界上没人做过”，只能证明检索过程和差异判断已被记录。

### `data-ready`：登记来源

必须产出：每份数据的来源、分类和校验和。

```powershell
scripts/provenance.ps1 --store "$paper/data/provenance.json" `
    --paper-root $paper check
```

敏感、无许可或来源不明的数据不要带入后续实验。

### `experiment-design`：冻结设计

必须产出：claim 到实验的映射、baseline、metric 和统计设计。

主要文件：`data/claims.yaml`、`data/statistics-plan.yaml`。

```powershell
scripts/statistics.ps1 --paper-root $paper
scripts/experiment-loop.ps1 check --paper-root $paper
scripts/experiment-loop.ps1 run-next --paper-root $paper
scripts/experiment-loop.ps1 run-next --paper-root $paper --execute
scripts/research-state.ps1 check --paper-root $paper
```

`data/experiment-loop.yaml` 记录 8-12 个候选、pilot 预算与 kill criterion，
以及内层 keep/revert/continue 和外层 continue/pivot/write 决策。先用
`experiment-loop next` 读取下一批待办动作；`run-next` 先预演，加 `--execute`
后才会在 `pilot_budget_minutes` 内通过 `compute.py` 执行命令，并同时写入
run-log 与 compute ledger。执行结果仍需人工写回 `run_ids`、`result` 和
`decision`，工具不会替人开释。纯 SoK 或不含实验的论文应写明
`not_applicable_reason`，不要把空台账伪装成完成。

涉及人工编码时，在这一阶段准备双人编码协议，不要等结果出来后再定义标签。

### `experiments-running`：运行并留档

每次运行都通过 run log 或实验队列执行，失败也必须保留。

```powershell
scripts/run-log.ps1 --log-dir "$paper/experiments/log" `
    --paper-root $paper run -- <command...>

scripts/run-log.ps1 --log-dir "$paper/experiments/log" `
    --paper-root $paper check
scripts/run-ledger.ps1 sync --paper-root $paper
scripts/run-ledger.ps1 check --paper-root $paper
scripts/passport-ledger.ps1 check --paper-root $paper
scripts/citation-calibration.ps1 `
    --gold data/citation-gold.jsonl `
    --predictions data/citation-predictions.jsonl
scripts/venue-fixtures.ps1 list
scripts/venue-fixtures.ps1 check `
    --fixture checklists/neurips-paper-checklist.yaml
scripts/venue-fixtures.ps1 seed --paper-root $paper `
    --fixture checklists/neurips-paper-checklist.yaml
scripts/experiment-loop.ps1 next --paper-root $paper
```

长任务优先使用 `scripts/queue.ps1`。需要隔离时使用 Docker 沙箱，不要在 daemon
不可用时静默改成宿主机执行。T-30 后的 build 豁免和脏树运行都必须写具体理由。

### `results-ready`：把 claim 绑定到证据

必须产出：每个 supported claim 对应具体源值；人工编码达到预设一致性门槛。

```powershell
scripts/trace-claims.ps1 --manuscript "$paper/manuscript" `
    --base-dir $paper --untagged
```

如果 venue 主文件不叫 `main.tex`，把路径替换为实际文件。无法支撑的 claim 应标为
provisional 或 dropped，不要为了过 gate 修改源数据。

### `writing`：完成可编译草稿

必须产出：正文、图表、引用和符合 venue 的页数。

```powershell
scripts/citation-guard.ps1 `
    --manuscript "$paper/manuscript" `
    --bib "$paper/manuscript/references.bib" `
    --ledger "$paper/data/citation-ledger.json"

scripts/latex-check.ps1 `
    --manuscript "$paper/manuscript" `
    --bib "$paper/manuscript/references.bib" `
    --compile
```

主文件位于子目录时，给 `latex-check` 增加 `--main <relative/path.tex>`。

### `internal-review`：独立复核论证

必须产出：证明、引用语义、图表语义的具名人工复核，以及无 blocking 项的评审记录。

主要文件：

- `data/proof-audit.yaml`
- `data/proof-campaign.yaml`
- `data/citation-support.yaml`
- `data/figure-support.yaml`
- `data/rigor-rubric.yaml`
- `reviews/*.json`

```powershell
scripts/argument-audit.ps1 --paper-root $paper
scripts/proof-orchestrator.ps1 check --paper-root $paper
scripts/proof-run.ps1 check --run-dir "$paper/prompts/260101-01" `
    --notation-required --require-closed
scripts/cross-review.ps1 check --paper-root $paper --out-dir reviews `
    --strict-cross-family
scripts/verifiers.ps1 --paper-root $paper
scripts/formal-check.ps1 --paper-root $paper `
    --out reviews/formal-check.json
scripts/review-loop.ps1 check --paper-root $paper
scripts/review-loop.ps1 drive --paper-root $paper `
    --fix-command '["powershell","-File","fix-review.ps1"]' `
    --review-command '["powershell","-File","review-round.ps1"]'
scripts/rigor-rubric.ps1 check --paper-root $paper
```

人工复核应由真实的人完成。模型名字不能冒充 reviewer。跨族 provider 不可用时，
同族 override 只能作为异常记录，不能当作独立评审；即使模型返回 pass，
effective verdict 也会被检查器重算为 blocking。Rigor rubric 的六个维度必须
逐项绑定 claim、run id 或仓库内文件；模型可以写 `model-advisory`，但不能把
rubric 标成 `complete`。

`cross-review` 对模型的 pass 有三道机械否决，都不依赖人工判断：

| 否决项 | 触发条件 | 结果 |
| --- | --- | --- |
| `review-advisory-only` | 评审模型参数量 ≤ 32B，或来自本地 provider | pass 降级为 blocking：模型可以驱动流程，不能单独开释 `review_cleared` |
| `review-contradiction` | 模型返回 pass，但 `argument-audit` 仍报问题 | 降级为 blocking，并逐条列出确定性 gate 的问题 |
| `review-unevidenced-pass` | pass 缺少 `checks[{gate,path,evidence}]`，或 evidence 既不是被引用文件的原文也不是它的 sha256 | 降级为 blocking，按未验证处理 |

所以 `verdict=pass` 现在要求三件事同时成立：模型足够强（>32B 且非本地）、
给出了可核验的正面证据、确定性 gate 没有反对。缺任何一条，记录只能是 blocking。
更早版本写下的 pass 记录会在 `check` 时被重算，并报 `review-contradiction`。

本机没有外部第二 family API 时，可以用 Ollama 提供真实的本地跨族 provider
（默认 `127.0.0.1:11434`；`OLLAMA_HOST` 如被改动，provider 的 `base_url` 必须同步）：

Codex 配置需要注册一个 Responses API provider；非 thinking 本地模型必须显式
传 `--reasoning-effort none`，否则 Codex 会发送 Ollama 不支持的 reasoning
参数：

```toml
[model_providers.local-qwen]
name = "Ollama Qwen"
base_url = "http://127.0.0.1:11434/v1"
wire_api = "responses"
requires_openai_auth = false
```

```powershell
scripts/cross-review.ps1 run --paper-root $paper `
    --model qwen3:30b `
    --provider local-qwen `
    --reasoning-effort none
```

本地模型属于真实不同 family，但按上面的规则只能是 advisory-only：
它解决的是 provider/family 独立性，不能替代高质量人类评审，也不能单独开释 gate。

### `submission-check`：冻结投稿包

必须产出：终稿检查、治理台账、复现环境和可实际验证的复现包。

```powershell
scripts/governance.ps1 --paper-root $paper
scripts/governance-map.ps1 check --paper-root $paper
scripts/governance-map.ps1 render --paper-root $paper `
    --out "$paper/docs/data-flows.md"
scripts/repro-env.ps1 --paper-root $paper
scripts/final-check.ps1 --paper-root $paper `
    --manuscript "$paper/manuscript" `
    --pdf "$paper/submission/final.pdf"
scripts/repro-package.ps1 --paper-root $paper bundle `
    --files <复现所需的论文内相对路径...> `
    --command "{python} <入口脚本>" `
    --requirements <依赖文件相对路径> `
    --out "$paper/submission/repro"
scripts/repro-package.ps1 --paper-root $paper verify `
    --bundle "$paper/submission/repro"
scripts/repro-container.ps1 verify `
    --bundle "$paper/submission/repro" `
    --out "$paper/reviews/repro-container.json"
scripts/artifact-store.ps1 put --paper-root $paper `
    --path "figures/threat-model-lattice.pdf" --role figure --run-id RUN1
scripts/artifact-store.ps1 verify --paper-root $paper
scripts/artifact-store.ps1 package --paper-root $paper `
    --out "$paper/submission/research-artifact.science"
scripts/session-replay.ps1 check --paper-root $paper
scripts/session-replay.ps1 render --paper-root $paper `
    --out "$paper/reviews/session-replay.html"
```

如果 `data/repro-environment.yaml` 声明了 `container`，则必须同时写
`container.receipt` 指向这份 JSON 收据；`repro_env` 会校验镜像 digest、
`status=pass`、`exit_code=0` 和 `network=none`。只有说明文字、没有收据仍算
未完成第二环境复现。

在提交前检查匿名、页数、补充材料、AI 使用政策、预印本政策和一稿多投政策。

### 投稿后

会议：`submitted -> rebuttal -> camera-ready -> archived`。

期刊：`submitted -> major-revision -> response-letter -> resubmitted -> accepted -> archived`。

审稿意见逐条进入 revision ledger。最终归档终稿、复现包、来源文档和评审材料。

尾部产出统一写入 `data/post-submission.yaml`。rebuttal 的回复矩阵、
resubmit 的 venue 差异表与改写章节、talk 的 slide 大纲都必须能追溯到真实
run id、claim id 和 figure id：

```powershell
scripts/revision-ledger.ps1 --ledger "$paper/reviews/revision-ledger.md"
scripts/post-submission.ps1 check --paper-root $paper
scripts/artifact-badge.ps1 check --paper-root $paper
scripts/resubmit-pipeline.ps1 check --paper-root $paper
scripts/talk-pipeline.ps1 check --paper-root $paper
```

## 6. 推进与回退

所有检查通过并完成必要人工判断后，先提交论文仓库：

```powershell
git -C $paper status --short
git -C $paper add <本阶段文件>
git -C $paper commit -m "complete <stage> gate"
```

再推进状态：

```powershell
scripts/state.ps1 --paper-root $paper set-stage `
    <next-stage> --reason "<具体完成事实>" --confirm
```

证据失效时应回退，而不是保留一个虚假的绿灯：

```powershell
scripts/state.ps1 --paper-root $paper rollback `
    <earlier-stage> --reason "<触发回退的事实>" --confirm
```

准确参数以 `scripts/state.ps1 <subcommand> --help` 为准。

## 7. 退出码处理

| 退出码 | 含义 | 处理方式 |
| --- | --- | --- |
| `0` | 检查通过 | 继续人工复核或进入下一步 |
| `1` | 发现材料或研究问题 | 阅读 JSON `problems`，修复证据，不要重装工具 |
| `2` | 工具自身错误 | 检查参数、环境、文件格式或依赖；不能视为 gate 通过 |

`advisory` 是待审阅事项，不自动改变退出码。对关键结论的 advisory 必须逐条处理，
不能用一段笼统声明批量关闭。

## 8. 版本与快照

阶段完成后优先用普通 git commit。需要命名快照或比较版本时使用：

```powershell
scripts/research-version.ps1 --help
```

快照前必须确认命令指向论文自己的 git 仓库，且没有未解释的脏树改动。

## 9. 桌面工作台

启动：

```powershell
cd app
$env:PYTHONPATH = (Resolve-Path ../tools).Path
& .venv/Scripts/python.exe -m ccfa_gui.main
```

工作台适合查看项目、运行常用检查和与模型协作。模型只能调用白名单工具；写操作必须
人工确认，`run-log run` 不对模型开放。

设置页可配置 OpenAI-compatible provider 和 HTTP 工具注册表。注册表中的凭据写成
`secret:<key_name>`，实际值只存系统 keyring。注册表保存后热重载，无需重启。

## 10. 开发与测试

每次修改 `tools/`、`scripts/`、`app/`、`.github/`、`automation/`、
`checklists/`、workflow 文档或根工作流文件，都必须在同一次提交里追加变更日志。
未记录日志的改动会被 `change-log check` 阻断：

```powershell
scripts/change-log.ps1 add `
    --summary "<改了什么>" `
    --reason "<为什么改>" `
    --file tools/ccfa/example.py `
    --test "tools.tests.test_example"
scripts/change-log.ps1 check --base origin/master
scripts/change-log.ps1 render
```

`docs/workflow-change-log.jsonl` 是 append-only source of truth；
`docs/workflow-change-log.md` 是生成物。不要删改旧日志来绕过检查。

工作树漂移审计：

```powershell
scripts/worktree-audit.ps1 --base origin/master --format markdown
scripts/worktree-audit.ps1 --base origin/master --strict
```

参照仓库漂移审计：

```powershell
scripts/reference-audit.ps1 list
scripts/reference-audit.ps1 check --strict
```

`docs/reference-registry.yaml` 固定已做源码审计的 commit。月度 workflow 发现
上游有新 commit 时会 fail closed；此时需要人读 diff、更新本地对齐结论和 pin，
不能把“上游有更新”自动当作“已经完成对齐”。

修改工具后只运行新增、修改模块及直接消费者：

```powershell
scripts/test-impact.ps1 plan --base origin/master
scripts/test-impact.ps1 run --base origin/master
```

选择器把改动映射到最小测试集；未知路径、删除的测试文件、`cli.py` / `stages.py`
等共享边界会自动回退全量。工作台改动用 `--suite app`。只有发布、每晚 CI、
状态机/公共契约大改或明确要求时，才主动运行全量套件。

周期性自优化用 friction 与 readiness 报告聚合候选，不直接改工作流：

```powershell
scripts/meta-optimize.ps1 `
    --friction "<paper>/friction_log.json=paper-slug" `
    --readiness "<paper>/reviews/readiness.json=paper-slug" `
    --min-count 2 --out "<repo>/reviews/meta-optimize.md"
```

跨项目的 decision、dead-end、claim、method 与 result 卡片写入
`library/wiki/`，先校验再重建索引：

```powershell
scripts/research-wiki.ps1 check --dir library/wiki
scripts/research-wiki.ps1 index --dir library/wiki --out library/wiki/index.json
scripts/research-wiki.ps1 search --index library/wiki/index.json --query "artifact"
scripts/research-wiki.ps1 add-edge --dir library/wiki `
    --from rw:002 --to rw:001 --type inspired_by --evidence "file:notes.md"
scripts/research-wiki.ps1 query-pack --dir library/wiki `
    --out library/wiki/query_pack.md
scripts/research-wiki.ps1 sync --dir library/wiki --bib library/refs.bib
scripts/research-wiki.ps1 rebuild --dir library/wiki
scripts/research-wiki.ps1 append-log --dir library/wiki `
    --message "rebuilt after new literature ingest"
```

从已有 claim、exploration、figure 和 run 台账生成 ARA draft：

```powershell
scripts/ara-compile.ps1 compile --paper-root $paper --out "$paper/ara"
scripts/ara-compile.ps1 validate --dir "$paper/ara"
```

这里的 `compile` 是诚实 draft 编译器：语义内容不足时写出 mandatory 文件骨架，
并在 `compile-report.json` 里列出未满足的 Seal Level 1 条件，不宣称 ARA 完整。

不要把测试生成物、临时复现输出或某篇论文的工作文件提交到模板仓库。

## 11. 每日收工

1. 运行今天改动对应的定向检查。
2. 确认失败运行和人工判断都已经落盘。
3. 查看 `git -C $paper status --short`，区分应提交材料与临时文件。
4. 提交一个边界清楚的论文仓库 commit。
5. 再运行 `milestones stage`，记录下一次从哪个 gate 继续。

工作流的目标不是制造更多表格，而是让重要结论在两周后仍然能够回答：它来自哪里、
谁复核过、哪次运行产生、在哪个版本被采用，以及什么事实会让它失效。
