# 图表语义支持审计实施计划（2026-10-04）

**Goal:** 关闭审计总结里最后一条「可检查替代目标」的语义缺口：图表溯源只验来源、
字节与哈希，不验「这张图是否真的展示了正文用它所主张的结论」。文档、图表都能被
机械核对，唯独「图和结论是否一致」没有人负责——12 轮内部评审修的是表格不同步，
真正的图-结论不一致只有外部人看才发现。

**裁定（E79）：** 不新增工具、不新增 CLI。把图表语义支持做成 `argument-audit` 的
第三张台账，与「人工证明复核」「引用语义支持」并列，因为它们是同一类东西：
**脚本判不了语义真伪，但可以强制「有人做过这个判断、这个判断可追责、可复核」。**

## 契约

新增 `data/figure-support.yaml`：

```yaml
version: 1
figures:
  - id: main-results                 # 必须与 figures/manifest.yaml 的 name 一致
    claim_ids: [C1]                  # 必须来自 data/novelty-audit.yaml 的 claims
    attributed_text: "..."           # >=20 字符，必须出现在 referenced_in 指向的正文里
    verdict: supports                # supports | partial | contradicts | irrelevant | not-applicable
    reviewer: "张三"                 # 人类姓名，模型名不算
    reviewed_at: "2026-10-04"        # YYYY-MM-DD
    note: "..."                      # supports 可省；其余判定必须 >=20 字符
```

### 判定

| 条件 | 结果 |
| --- | --- |
| manifest 无交付图 | advisory `figure-support-not-needed` |
| manifest 有交付图但台账缺失 | problem `figure-support-ledger-missing` |
| manifest 条目缺 `name` 或图名重复 | problem `figure-support-manifest-invalid` |
| 台账条目 `id` 不在 manifest | problem `figure-support-figure-missing` |
| manifest 交付图没有台账条目 | problem `figure-support-missing` |
| 证据图 `claim_ids` 为空/非法 | problem `figure-support-invalid-claims` |
| `not-applicable` 却带 `claim_ids` | problem `figure-support-invalid-claims` |
| claim id 未在 novelty-audit 声明 | problem `figure-support-unknown-claim` |
| 有证据图但 novelty-audit 读不出 claims | problem `figure-support-claims-unavailable` |
| `attributed_text` < 20 字符 | problem `figure-support-text-too-short` |
| `attributed_text` 不在 `referenced_in` 指向的正文里 | problem `figure-support-text-not-found` |
| manifest 缺合法 `referenced_in` | problem `figure-support-reference-missing` |
| `referenced_in` 行号非法/越界/文件不存在 | problem `figure-support-reference-invalid` |
| reviewer 是模型名/空 | problem `figure-support-not-human` |
| `reviewed_at` 非 `YYYY-MM-DD` | problem `figure-support-invalid-date` |
| verdict 不在枚举 | problem `figure-support-invalid-verdict` |
| verdict = contradicts / irrelevant | problem `figure-support-not-supporting` |
| verdict = partial | advisory `figure-support-partial` |
| verdict != supports 却没写 >=20 字符 note | problem `figure-support-note-missing` |
| 重复 `id` | problem `argument-audit-invalid` |
| 全部命中 | 通过，并输出 coverage advisory |

### 边界（必须写清）

- **证据图**（verdict != not-applicable）必须绑定至少一个 claim id，且必须能在
  manifest 的 `referenced_in` 指向的正文文件中逐字找到 `attributed_text`。
  这只是「正文确实用过这张图、审计者指的是同一句话」的机械下限；v1 只做文件级
  匹配，不做段落级/同句级定位。
- **非证据图**（示意图、架构图、流程图）可以 `verdict: not-applicable`，
  但必须写明 >=20 字符理由，且不得绑定 claim。
- 脚本**不判断图与结论本身是否一致**，也不看图。它只保证：每张交付图都有人
  具名判断过、判断绑定到 claim 与正文原句、非同意的结论不会被静默放过。
- `final-check` 的 `unreferenced-figure` 仍是 advisory；本 gate 在**提出图表
  语义断言**时把 `referenced_in` 升级为硬要求，因为无法定位就没有可复核的结论。

## 文件

- 修改 `tools/ccfa/argument_audit.py`：新增 `figure-support.yaml` 读取、判定与
  `--figure-ledger` / `--manifest` 参数。
- 新增测试 `tools/tests/test_figure_audit.py`。
- 修改 `tools/ccfa/stages.py` 的 `internal-review` 判据；重新生成两份 checklist。
- 修改 `tools/newpaper/create.py` 播种 `data/figure-support.yaml`。
- 修改 `README.md` 工具表与阶段速查、设计文档 §4.2 / §6.1.2 / §6.3、进度账本。

## 完成定义

- `argument-audit` 同时审计证明、引用、图表三类语义支持；三者任一未复核都退 1。
- 新测试覆盖上表每一行，并带判别力（改坏实现会让对应用例失败）。
- tools / app 全量测试全绿。
- 文档明确：该 gate 只强制「有人做过判断」，不保证判断正确。
