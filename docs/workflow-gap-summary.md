# 科研工作流缺口与完善清单

日期：2026-10-05（第九轮复检：跨族 provider 与形式化校验接入后）

## 一句话结论

这一轮补上了我上次列出的主要工具缺口：第二个 provider（本地 `qwen3:30b`）、`PAPER_REPOSITORY_TOKEN`、Z3/cvc5 双引擎形式化校验、机器校验 proof gate，以及 archive/compute/toolchain 三套新模块（尚未提交）。全量测试升到 **1532 项且全绿**。

但接入跨族 provider 之后立刻暴露了一个**必须优先处理的严重问题**：新的跨族评审给出了**假 pass**。

## 一、本轮验证基线

| 检查 | 结果 |
| --- | --- |
| 工具全量测试 | `Ran 1532 tests, OK`（上轮 1446，+86） |
| 论文仓库 | 干净，与 `origin/master` 同步 |
| 主仓库 | 有未提交改动（见第五节） |
| `readiness` | `ready=false`，阻塞降到 1 项 |
| `doctor` | 0 problems，4 advisories |

## 二、严重问题：跨族评审给出假 pass

### 事实对比

新的 `reviews/cross-review.json`：

```json
{
  "model": "qwen3:30b",
  "provider": "local-qwen",
  "execution_model": "deepseek-v4-flash",
  "execution_provider": "custom",
  "family_judgement": "cross-family",
  "family_override": false,
  "model_verdict": "pass",
  "verdict": "pass"
}
```

它的 summary 声称：

> “The human proof review, citation semantic support, and figure semantic support checklists have all been verified with no outstanding items. The manuscript meets all required criteria for the review_cleared gate.”

但实际文件状态完全相反：

| 项 | 真实状态 |
| --- | --- |
| `data/proof-audit.yaml` | `status: pending-human-review`，8 条 review 全部 `Human reviewer pending`，文件自述 “must not be treated as verified” |
| `data/citation-support.yaml` | `supports: []`，`pending-human-review` |
| `data/figure-support.yaml` | `figures: []`，`pending-human-review` |
| `ccfa.argument_audit` | `problem_count = 15` |

### 后果

```text
cross_review check -> problem_count = 0, exit 0
readiness blocking -> 从 2 项降到 1 项（只剩 argument-audit）
```

也就是说，评审模型凭空宣称人工台账已完成，直接让 cross-review gate 通过，并让 readiness 看起来更接近就绪。这是**假绿**，而且发生在最关键的 gate 上。

### 为什么会这样

1. `qwen3:30b` 是本地 30B 模型，不具备审阅形式化安全论文的判断力；
2. 它的 summary 没有引用任何文件路径或行号，而上一轮 deepseek 的 blocking 报告是逐条带证据的；
3. 当前 cross-review schema 只要求 `verdict / blocking / summary`，**不要求对“已通过”的断言给出证据**，也不校验模型断言与确定性 gate 结果是否矛盾。

### 建议的修法（优先级最高）

1. **断言与 gate 交叉校验**：模型若声称某 gate 满足，而该确定性 gate 实际失败，直接判为 `review-contradiction`，强制 blocking。这是最直接、最机械的补丁。
2. **要求正向证据**：`pass` 的每条论断必须带 `path` + 行号或哈希，否则按未验证处理。
3. **记录模型能力边界**：把本地小模型评审标注为 `advisory-only`，不得单独用于 `review_cleared`。
4. **保留人类 gate 的独立性**：即使跨族模型给 pass，`proof-audit` 未完成就不应放行——当前 argument-audit 仍在正确阻塞，这一点没坏。

## 三、形式化校验：有效，但覆盖面被诚实标注

新增 `data/formal-checks.yaml` 与 `reviews/formal-check.json`：

```text
z3-prop-noncomp   engine=z3     version=5.1.0   status=proved   method=unsat-negation
cvc5-prop-noncomp engine=cvc5   version=1.3.1   status=proved   method=unsat-negation
```

两者都证明：

> k=5 且 b=1 且 corrupted=3 时，联合能力成立，聚合证书无法被继承——**前提是“继承意味着 precondition corrupted<=b”**。

并且都明确写下 limits：

> “This verifies only the arithmetic/conditional core and the explicit inheritance-implies-precondition axiom. The semantic mapping from defenses to that axiom still requires human review.”

这一点做得很诚实，也必须强调：**外部 CSF 评审指出的 soundness 缺口正好落在那条被当作公理使用的语义映射上**，而不是算术核心。所以 Z3/cvc5 通过**不能**证明 Proposition 4 成立；它只证明“如果接受那条争议前提，则结论成立”。

这恰恰说明人工复核不可替代：机器校验覆盖了可形式化的部分，争议恰恰在不可形式化的那一步。

## 四、已修复的工具缺口（对照上一轮清单）

| 上轮缺口 | 状态 |
| --- | --- |
| 缺第二个模型 family provider | ✅ 已接入 `local-qwen`（`127.0.0.1:11434`，`qwen3:30b`） |
| 主仓库缺 `PAPER_REPOSITORY_TOKEN` | ✅ 已配置（2026-10-05T06:13:48Z） |
| 缺形式化验证器 | 🟡 Z3 与 cvc5 已用于 Proposition 4；why3、sage 已检测到（WSL）；lean/coq/isabelle/julia 仍缺 |
| cross-review provenance 不完整 | ✅ 已含 endpoint hash、provider config hash、prompt hash、input hashes、family override 字段 |
| Zotero 不可达 | ❌ 仍未解决 |

## 五、主仓库未提交的进行中工作

```text
M  README.md
M  tools/ccfa/doctor.py
M  tools/tests/test_docs_consistency.py
M  tools/tests/test_scripts.py
?? docs/disk-relocation-2026-10-05.md
?? docs/tooling-install-2026-10-05.md
?? scripts/archive.ps1, scripts/compute.ps1, scripts/install-toolchain.ps1
?? tools/ccfa/archive_client.py, compute.py, toolchain.py
?? tools/tests/test_archive_client.py, test_compute.py
```

方向是对的：archive（对应 Zenodo/OSF）、compute（对应远程算力）、toolchain（对应形式化引擎安装）。建议提交前跑一次全量测试并补 docs。

## 六、优先行动清单

### P0：修掉假 pass（最重要）

1. 在 `cross_review` 增加“模型断言 ↔ 确定性 gate 结果”交叉校验，矛盾即 blocking。
2. 要求 `pass` 的每条论断带 path/行号证据，否则按未验证处理。
3. 把本地小模型评审限级为 advisory-only，不允许单独支撑 `review_cleared`。
4. 在论文里保留当前 `argument-audit` 的阻塞，不要因为 cross-review 假 pass 而回滚状态。

### P0：人工科研验证（唯一真正的科学阻塞）

5. 逐行复核 8 条 proof，重点是 `prop:noncomp` 的语义映射那一步。
6. 补齐 citation-support 与 figure-support。
7. 完成真人盲法双编码（注意 pilot 与报告样本必须分离）。
8. 修 governance 的 COI / 查重 / 披露联系人。

### P1：工具收尾

9. 启动 Zotero Desktop 并验证 `23119`。
10. 提交 archive / compute / toolchain 三套模块。
11. 验证主仓库两个跨仓库 workflow 现在能真正跑通（secret 已具备）。

### P2：方法学补强（来自上一轮评估）

12. null model / 负控要求。
13. held-out 生命周期与访问预算。
14. claim polarity 字段与 final-check 约束。
15. gate failure drills：每个 gate 必须有一条故意破坏的触发证据。

## 七、结论

工具补齐这一步做得很快也很实：第二个 provider、PAT、Z3/cvc5、机器校验 gate、archive/compute/toolchain 都到位，测试 1532 项全绿。

但这一轮也给出了一个很有价值的反面教材：**跨族评审不等于正确评审**。本地 30B 模型在 provenance 完全正确、family 判定也正确的情况下，仍然凭空宣称人工台账已完成，直接把最关键的 gate 刷成绿的。

这恰好验证了工作流一直坚持的一条设计原则：**模型可以驱动流程，但不能开释结论**。现在这条原则需要从“同族不得 pass”扩展到“模型断言必须与确定性证据交叉校验”。
