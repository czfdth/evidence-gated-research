# 科研工作流缺口与完善清单

日期：2026-10-05（第八轮复检：论文迁移完成）

## 一句话结论

这一轮发生了两件关键的事：**示例论文真正迁移到新证据体系**（readiness 阻塞从 13 项降到 2 项），以及 **CI 重新设计为“工程检查必须通过、人工 gate 只做信息报告”**。工具层与论文层之间那条越拉越大的剪刀差开始收窄。

剩下的阻塞已经纯粹是人工科研验证与真实跨族评审，不再有任何代码或迁移工作。

## 一、本轮验证基线

| 检查 | 结果 |
| --- | --- |
| 主仓库 / 论文仓库 | 均干净，与 `origin/master` 同步 |
| 工具全量测试 | `Ran 1446 tests, OK`（上轮 1441） |
| app 全量测试 | `Ran 187 tests, OK` |
| `doctor` | 0 problems，1 advisory |
| `readiness` | `ready=false`，阻塞仅剩 2 类 |

## 二、示例论文迁移完成

`papers/example-paper/data/` 已经补入 10 个新台账：

```text
claim-registry.yaml            7698 B
assumptions-limitations.yaml   4522 B
venue-checklist.yaml           1802 B
artifact-provenance.yaml       2535 B
exploration-graph.yaml         2025 B
cost-ledger.yaml                888 B
risk-register.yaml             3731 B
experiment-loop.yaml            460 B
rigor-rubric.yaml              2301 B
proof-campaign.yaml            6984 B
```

仍未创建的两个：

```text
artifact-badge.yaml        （需要第三方 evaluated / reusable 证据）
scientific-acceptance.yaml （需要外部人类接受）
```

readiness 的阻塞从上一轮的 13 项降到 2 项：

```text
argument-audit gate failed: proof-review-not-verified ×5
cross-review gate failed: review-provider-config-drift, review-blocking
```

这正是应有的结果：剩下的都是“必须由人或外部完成”的事。

## 三、CI 重新设计

`paper-check.yml` 现在拆成两个 job：

| Job | 内容 | 是否阻塞 |
| --- | --- | --- |
| `deterministic-paper-checks` | validate、citation_guard、trace_claims、novelty、stats_plan、repro_env、latex_check、final_check、run_log | 阻塞 |
| `readiness-and-human-review` | readiness、governance、argument_audit、cross-review | `continue-on-error: true`，只上传 artifact |

这是一个合理的设计：CI 绿灯表示**工程侧健康**，不再因为人工复核未完成而长期红灯；人工与科学 gate 单独跟踪。

### 由此产生的一个残余风险

informational job 永远不会让 CI 失败。加上 `standard` profile 不要求 `governance`，目前 **COI、查重工具、披露联系人这三条 placeholder 不再被任何自动检查阻断**：

```text
ccfa.governance -> problem_count = 3, exit 1
但 CI 中该步骤 continue-on-error
且 readiness standard profile 不包含 governance
```

**已修复：** 论文仓库增加了 fail-closed 的
`.github/workflows/submission-gate.yml`，在 `v*` tag 或手动触发时强制运行
high-assurance readiness、governance、argument-audit、
`--strict-cross-family` cross-review 和复现包验证。该 workflow 不使用
`continue-on-error`，任一 gate 失败都会阻止发布流程。

## 四、环境状态（明显改善）

| 服务 | 本轮状态 | 变化 |
| --- | --- | --- |
| provider | `functional`，配置模型可用 | 稳定 |
| Docker daemon | **可达** | 上轮不可达，本轮恢复 |
| WorkBuddy converter | **依赖已移除** | doctor / README / workflow-guide 中已无引用 |
| Zotero `:23119` | 不可达 | 本轮回退（上轮为可连接未认证） |

`doctor` 现在只剩 1 条 advisory，环境侧基本健康。

## 五、仍然阻塞的事项（全部非代码）

### 1. 人工证明复核（8 条）

`data/proof-audit.yaml` 仍是 `pending-human-review`，8 条 review 的 reviewer 都是 `Human reviewer pending`，文件自己注明 “must not be treated as verified”。这是当前第一阻塞。

### 2. 引用与图表语义支持

`citation-support.yaml` 的 `supports: []`、`figure-support.yaml` 的 `figures: []` 仍为空。

### 3. 真人双编码

`human-coding-report.json` 仍是 `pending-human-dual-coding`，需要 blind second coding + kappa + 置信区间。

### 4. governance 占位值

COI、查重工具、披露联系人仍是 placeholder。gate 能正确识别，但目前不在阻塞路径上。

### 5. 真实跨族评审

`cross-review` 报 `review-provider-config-drift` 与 `review-blocking`。真实跨族仍需要一个不同 family 的 provider。

### 6. 外部证据

```text
artifact-badge.yaml       缺失（需第三方 evaluated / reusable）
scientific-acceptance.yaml 缺失（需外部人类接受）
PAT secrets / branch protection / 跨仓库 CI 实测
第二环境或容器复现证据
Zenodo / OSF DOI、ORCID
```

## 六、值得注意的两个观察

### 1. 全量测试耗时上升到约 203 秒

上轮 1441 项约 123 秒，本轮 1446 项约 203 秒。测试数量只增加 5 项，耗时却增加约 65%。可能是新增 lint / dependency audit 或某些测试变慢。建议关注是否有慢测试进入主套件，必要时拆分 `--fast` / `--full`。

### 2. 工程检查与人工 gate 分离后，需要新的“提交门”

**已修复。** `submission-gate.yml` 提供了“提交/发布时必须全绿”的强制路径，
informational 报告不再可能被当成最终放行依据。

## 七、优先行动清单

### P0：人工验证（唯一真正的科研阻塞）

1. 逐行复核 8 条 proof，特别是 `prop:noncomp`（Proposition 4）。
2. 补齐 citation-support 与 figure-support。
3. 完成真人盲法双编码，输出 kappa 与置信区间。
4. 把 governance 的 COI / 查重 / 披露联系人换成真实值。

### P1：提交门与外部能力

5. **已完成：** high-assurance 提交门由论文仓库的 `submission-gate.yml`
   提供，tag 或手动触发，任一人工 gate 未通过即阻止发布。
6. 接入第二个 family provider，重跑 cross-review 去掉 same-family。
7. 验证两个 PAT secret 与跨仓库 CI 实测。
8. 完成容器或第二环境复现，填 artifact-badge 的 evaluated / reusable 证据。

### P2：收尾与减负

9. 排查全量测试变慢的原因，必要时拆分快速/完整套件。
10. 用 survey / systems / theory 分档 profile 给台账瘦身。
11. 接入 Zenodo/OSF DOI 与 ORCID。
12. 开始往 Research Wiki 填真实卡片。

## 八、结论

这一轮是转折点：论文完成迁移，CI 完成分层，环境基本恢复，工具与论文之间的剪刀差显著收窄。

现在 `ready=false` 的原因只剩两类，且都不是工程问题：

1. 8 条证明还没有真人复核；
2. cross-review 需要真实跨族 provider。

换句话说，**工作流本身已经不再阻塞论文；阻塞论文的只剩人力和外部资源**。下一步的价值不在写代码，而在找到一位能独立复核 Proposition 4 的人，以及接入第二个模型 family。

## 九、跨族 provider 已接入（第九轮补记）

第二个 family provider 已落地为本机 Docker + Ollama 的 Qwen provider：

```text
provider: local-qwen
endpoint: http://127.0.0.1:11434/v1
model: qwen-local
remote model: qwen2.5:3b
reasoning: none
```

容器已设置 `--restart unless-stopped`，并使用 RTX 5060 GPU。Codex 配置中新增
了 Responses API provider 和 `cross-family` profile。`cross-review` 已支持
`--reasoning-effort`，用于非 thinking 的本地模型。

真实验证结果：

```text
family_judgement: cross-family
family_override: false
model_verdict: pass
status: complete
cross-review check: 0 problems
```

因此 `cross-review` 已从 blocking 变为 pass；readiness 现在只剩人工证明、
引用语义、图表语义与后续人工验证阻塞。需要保留的边界是：本地 Qwen 3B 是
真实不同 family，但推理能力弱于云端大模型，不能替代高质量人工复核。

## 十、形式化验证器已接入（第十轮补记）

上一轮的缺口是“有 proof-campaign、proof-orchestrator、notation gate、derivation gate，
却没有一个真正的形式化验证器”，`lean`、`coq`、`isabelle`、`agda`、`z3`、`sage`、
`julia` 在本机全部缺失。本轮把这层补齐，并让它可见、可追踪。

### 1. 新工具

```text
tools/ccfa/verifiers.py      scripts/verifiers.ps1
tools/ccfa/formal_check.py   scripts/formal-check.ps1
```

`formal_check` 运行论文在 `data/formal-checks.yaml` 声明的命令，解析 JSON 输出并核对
`id`/`engine`/`theorem_id`/`status`；只接受 `proved`/`unsat`/`valid`。
`verifiers` 清点本机引擎，并对照论文声明的引擎，缺失项如实报告而不是让 `doctor` 全绿。
`doctor` 已把 z3 缺失判为 problem，其余引擎缺失判为 advisory，`--strict` 全部升级。

### 2. 引擎状态（本机实测）

| 引擎 | 类型 | 状态 | 备注 |
| --- | --- | --- | --- |
| z3 | SMT | 可用，已接入 | pip `z3-solver==5.1.0.0`，核心引擎 |
| cvc5 | SMT | 可用，已接入 | pip `cvc5==1.3.1`，第二独立 SMT 引擎 |
| lean | proof-assistant | 可用 | winget `Lean.Lean` 4.34.1 |
| coq | proof-assistant | 可用 | winget `Coq.CoqPlatform` 2025.08.3（Rocq 9.0.1，装在 `C:\Rocq-Platform~9.0~2025.08`） |
| isabelle | proof-assistant | 可用 | 官方 7z SFX 解压到 `F:\Isabelle2025-2`（Isabelle2025-2，自带 Cygwin/JDK） |
| agda | proof-assistant | 可用 | WSL Ubuntu-24.04：`apt-get install agda agda-stdlib`（Agda 2.6.3） |
| why3 | verification-platform | 可用 | WSL Ubuntu-24.04：`apt-get install why3`（Why3 1.6.0） |
| sage | CAS | 可用 | WSL Ubuntu-24.04 + conda-forge `sage`（SageMath 10.9，装在 `/opt/sage`） |
| julia | language | 可用 | winget `Julialang.Julia` 1.13.1 |

Agda、Why3、Sage 装在 WSL 里，`verifiers` / `doctor` 会通过
`wsl -d Ubuntu-24.04 -u root -- bash -lc ...` 真正调用它们来确认可用，而不是只看文件是否
存在。Ubuntu 发行版的 vhdx 已从 C: 迁到 `F:\wsl\Ubuntu-24.04`。

安装过程记录了两处真实环境问题：Windows 上 Haskell 的 `stack` 因 TLS 证书校验失败
（`InvalidSignature`）无法拉取 GHC，因此 Agda 改走 WSL；Ubuntu 24.04 已移除 `sagemath`
apt 包，因此 Sage 改走 conda-forge（Miniforge + 清华镜像）。

### 3. Proposition 4 的双引擎交叉检查

`data/formal-checks.yaml` 现在声明两条针对 `prop:noncomp` 的检查：

```text
z3-prop-noncomp    ccfa-workfiles/formal/proposition4_z3.py
cvc5-prop-noncomp  ccfa-workfiles/formal/proposition4_cvc5.py
```

两个引擎独立编码同一个算术核心（k=5、b=1、corrupted=3，以及
“继承 ⇒ 聚合证书前提”这一显式公理），都用否定不可满足的方式证明命题成立：

```text
z3    5.1.0  proved  prop:noncomp
cvc5  1.3.1  proved  prop:noncomp
```

两个不同实现给出同一结论，比单一引擎更能排除“某个求解器的实现巧合”。但必须保留边界：
**机器检查只覆盖算术/条件核心，不覆盖从防御到继承公理的语义映射**。这一步仍需人工复核，
因此 `data/proof-audit.yaml` 的 `prop:noncomp` 仍是 pending，`proof-campaign` 的
`pc-noncomp` 状态仍是 open。

### 4. 还剩什么

九个引擎现在都可用，但**只有 z3 与 cvc5 接入了 `formal-checks.yaml`**。交互式证明助手
（Lean/Coq/Isabelle/Agda）要真正产生价值，需要先把某个命题写成该助手的形式化，再把它
接进 `formal-checks.yaml` 和 CI（CI 还要提供对应 toolchain）。只装二进制不等于有了证明。
当前 Proposition 4 的独立检查需求由 z3 + cvc5 满足；其余引擎就位，供后续“需要对无界结构
归纳”的定理使用。

## 十一、跨族评审模型升级（第十一轮补记）

F 盘的本地模型库（`F:\models\ollama`，原生 Ollama 0.35.1）里有比 qwen2.5:3b 强得多的
模型：

```text
qwen3:30b              18 GB  Qwen3-30B-A3B（MoE，激活 3B）
qwen3.8:27b-q4_K_M     17 GB  含视觉投影
bge-m3:latest         1.2 GB  embedding
```

原本 11434 端口由 Docker 容器 `ccfa-ollama`（qwen2.5:3b）占用。现已停掉该容器（保留，
可随时切回），改由原生 Ollama 接管端口并直接使用 F 盘模型库。

### 真实性能（RTX 5060 Laptop 8GB 显存，超出部分走 CPU）

| 模型 | prompt 预填 | 生成 | 完整 cross-review（67 文件 / 33.8 万字符 ≈ 28k tokens） |
| --- | --- | --- | --- |
| qwen3:30b (MoE) | 841 tok/s | 39 tok/s | 冷启动 47s，热启动 17s |
| qwen3.8:27b-q4_K_M | 324 tok/s | 4.7 tok/s | 明显更慢，不推荐 |

结论：**qwen3:30b 可以替代 qwen2.5:3b**，速度可接受，能力明显更强。

### 顺带修掉的 family 判定 bug

`cross_review._MODEL_FAMILIES` 原来只匹配带横线的 `qwen-`，而 Ollama 的真实标签是
`qwen3:30b`、`qwen3.8:27b-q4_K_M`，会被判成 `unknown`，导致「跨族」判定失效。之前
`qwen-local` 能过，只是因为它名字里正好带了横线。现已改为按家族前缀匹配
（qwen / deepseek / llama / mistral / gemma / glm / phi 等），并补了回归测试。

### 必须保留的边界

换用 30B 模型后，`cross-review` 仍然会**错误地宣称人工复核已全部完成**——它的 summary
写着 “All human review tickets … are fully verified”，而 `data/proof-audit.yaml` 的
条目实际仍是 pending，`ccfa-workfiles/human-review/README.md` 也明确说这些不是已完成的
人工复核。更强的模型只是把这句话写得更像真的。

这正好印证了核心边界：**模型评审可以驱动修改，但永远不能开释**。真正阻止 `ready=true`
的仍是确定性的 `argument-audit` gate；模型说得再满，也不能让 `ready` 变绿。
