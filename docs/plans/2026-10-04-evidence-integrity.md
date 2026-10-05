# evidence-integrity 实施计划（P0：让"可追溯"绑定真实证据）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 关闭 2026-10-04 审计的 P0 三条：论文不在版本控制（版本/快照/run-log commit 空转）；数字溯源只有抽查级却被声明为全覆盖；citation / run-log / cross-review 的 gate 由"文件自称"构成。P1/P2 条目（长任务安全、跨族评审、外部真实性、治理检查、覆盖）另立计划。

**前提裁定：**
- **E61**：每篇论文 = 独立 git 仓库（`papers/<slug>` 内 `git init`）；模板仓库继续忽略 `/papers/`；所有论文 git 操作必须验证 toplevel == 论文根，**不得回退父仓库**。
- **E62**：`\dataval` 目标 = **受保护区**（摘要/贡献列表/结果主叙事）的关键数字；受保护区未绑定且未豁免 → problem；豁免进 `data/claims.yaml` 逐条留痕；`checks.md` 的覆盖声明由工具产出。
- **E63**：确定性 gate 的"已核验"必须绑定外部证据：DOI 核验读响应体并记录证据哈希与匹配字段；run-log 的 git 身份记自身仓库或 `foreign/null`；cross-review 的每条 blocking 必须携带**在输入文件中可逐字命中**的引文。

---

### Task 1: 论文独立仓库 + 防父仓库逃逸（E61）

**并发避让（2026-10-04）**：`tools/ccfa/run_log.py`、`tools/ccfa/milestones.py`、`tools/ccfa/cross_review.py` 当前有另一并行任务（Ampere）的未提交改动。本任务拆为 **1a（本文件集：create + research_version）** 与 **1b（run-log 身份，待上述文件落地后再派）**。

**Task 1a Files:** Modify `tools/newpaper/create.py`、`tools/tests/test_create.py`、`tools/ccfa/research_version.py`、`tools/tests/test_research_version.py`；Create `docs/migrations/migrate-paper-to-git.md`（迁移步骤）。**不得触碰 run_log.py / milestones.py / cross_review.py 及其测试。**

- `create.py`：scaffold 完成后 `git init`（若目标已在仓库内则用 `git init` 独立 .git）、写论文级 `.gitignore`（TeX 中间产物、`*.pdf` 除外交付物、`__pycache__`）、`git add -A` + 首次提交；身份缺失时用 `git -c user.name=... -c user.email=...` 的本地默认（不写全局配置），提交失败则整体失败并清理（保持既有"不留下半成品"契约）。
- `research_version.py`：所有子命令先解析 `git -C <repo> rev-parse --show-toplevel`；不等于 `<repo>`（realpath 比较）→ `ValueError("论文目录不是独立 git 仓库……拒绝在父仓库上打 tag")` → 2。新增 `--allow-parent-repo`？**不加**（E61：不留后门）。
- **Task 1b（待 run_log.py 的并行改动落地后派）**：记录 git 身份时验证 toplevel；命中父仓库 → `git_repo: "foreign"`、`git_commit: null`、`git_dirty: null`；自身仓库 → `git_repo: "self"` + 既有字段；`check` 对 `foreign` 记 advisory（如实，不误报为"干净"）。

### Task 1b（文件已解锁）：run-log 记录真实的仓库身份

**Files:** Modify `tools/ccfa/run_log.py`、`tools/tests/test_run_log.py`（及 e2e 如需）

| 条件 | 结果 |
| --- | --- |
| `rev-parse --show-toplevel` == paper_root（realpath） | `git_repo: "self"` + 既有 `git_commit`/`git_dirty` |
| toplevel 是父仓库或其它仓库 | `git_repo: "foreign"`、`git_commit: null`、`git_dirty: null`（绝不记录父仓库提交） |
| git 不可用 / rev-parse 失败 | `git_repo: "none"` + 两个 null |
| 旧记录缺 `git_repo` | `check` → advisory `run-log-git-repo-unknown` |
| `git_repo == "foreign"` | `check` → problem `run-log-foreign-repo` |
| `git_repo == "none"` | `check` → problem `run-log-no-git-repo` |

- 测试约 8 条；判别力实测：去掉 toplevel 校验 → foreign 用例失败。
- commit：`feat: record whether a run happened in the paper repository`
- 迁移：对既有 `papers/example-paper` 执行 `git init` + 首次提交（内容不变，仅加 .git 与论文级 .gitignore）；迁移后重跑一条 run-log 记录，断言 `git_commit` 指向论文仓库。
- 测试（约 14 条）：新建项目自动成仓库且首提交含论文文件；仓库内嵌套目录运行 research-version → 拒绝；自身仓库 → 正常；run-log 在嵌套非仓库目录 → `foreign/null`；迁移文档步骤可照做。
- 判别力实测：去掉 toplevel 校验 → 逃逸用例失败；去掉 init → 首提交用例失败。
- commit：`feat: make each paper its own git repository`

### Task 2: 受保护区数字覆盖率（E62）

**Files:** Modify `tools/ccfa/dataval.py`（受保护区扫描）、`tools/ccfa/final_check.py`、`tools/tests/test_final_check.py`、`tools/tests/test_trace_claims*.py`、`tools/newpaper/create.py`（seed `data/claims.yaml` 模板 + `checks.md` 生成说明）；Create `tools/ccfa/claims_policy.py` + tests

- `data/claims.yaml`（schema v1）：`protected_sections: ["abstract", "contributions", "results"]`；`waivers: [{file, line_text, reason, date, author}]`；读时重校验，坏条目报 problem 不中断。
- `claims_policy`：给定 manuscript 与 policy → 输出受保护区未绑定数字（problem `protected-untagged-number`，带文件:行）与非受保护区 advisory（沿用 `untagged-number`）；豁免按 `(file, 行文本归一化)` 匹配，命中即豁免但**仍列出**（advisory `waived-number`，含理由）。
- `final_check`：无 policy 文件时如实 advisory（"未配置 claims policy，覆盖率未验证"），有 policy 时未绑定 → problem（退 1）。
- `checks.md`：覆盖声明段改为工具生成（`claims_coverage_report` 写入 `submission/checks.json` + md 片段），手写声明被模板注释禁止。
- 测试（约 16 条）：摘要未绑定 → problem；绑定后干净；豁免命中 → advisory 含理由；坏 waiver → problem；非受保护区仍 advisory 且不改退出码；无 policy → advisory；生成报告与真实计数一致。
- 判别力实测：把受保护区判定改回"全部 advisory" → 覆盖率用例失败。
- commit：`feat: require dataval coverage in protected sections`

### Task 3: 去自证（E63）

**并发避让（2026-10-04）**：`cross_review.py`、`run_log.py`、`milestones.py` 及其测试仍有 Ampere 的未提交改动。本任务拆为 **3a（DOI/引用证据，本次派发）** 与 **3b（cross-review 引文 + run-log purpose/gate，待 Ampere 落地后派）**。

**Task 3a Files:** Modify `tools/ccfa/doi_lookup.py`、`tools/ccfa/citation_guard.py`、`tools/ccfa/citation_ledger.py`、`tools/tests/test_citation_guard*.py`、`tools/tests/test_doi_lookup*.py`。**不得触碰 cross_review.py / run_log.py / milestones.py 及其测试。**

**Task 3b（待派）Files:** `tools/ccfa/cross_review.py`、`tools/tests/test_cross_review.py`、`tools/ccfa/run_log.py`（purpose → declared_purpose）、`tools/ccfa/milestones.py`（gate 证据化）

### Task 3b（文件已解锁）：自声明降级 + 引文可核验

1. **自声明降级**：run-log 新写入 `declared_purpose`（继续接受旧 `purpose` 读取）；help/docstring 明说这是调用者声明、不构成证据。
2. **T-30 豁免可见**：T-30 之后 `declared_purpose=="build"` 仍豁免 `t30-new-experiment`，但必须输出 advisory `t30-declared-build-run`（含 run id 与日期）；experiment 仍是 problem。
3. **cross-review 引文**：每条 blocking 的 `evidence` 至少含一条 ≥20 字符、且在 `--path` 输入文件拼接文本中逐字命中（空白归一化）的引文；否则 problem `review-uncited-blocking`（退 1）。
4. 测试约 12 条；判别力：build 豁免改静默跳过 → advisory 用例失败；去掉引文校验 → 编造引文用例失败。
5. commit：`feat: mark declarations as declared and require quotable review findings`

- **DOI**：`lookup` 读响应体 JSON，校验返回 DOI == 请求 DOI（大小写归一），提取 title；`LookupResult` 增 `evidence`（body sha256、retrieved_at、matched_title）；title 与 bib 条目 title 做归一化相似度（≥0.9 视为匹配，低则 `found=False, detail="title mismatch"`）。`citation_guard --verify-online` 写台账时 `status=verified` 必须携带 evidence；无 evidence 的 verified 条目 → problem `citation-self-asserted`。
- **run-log**：`purpose` 字段改 `declared_purpose`（并保留兼容读）；`check` 输出明确"declared 字段不构成证据"；milestones 的 `experiments-running` gate 证据改为"存在 run-log 记录且无 metrics-pending"（已可查），`submission-check` 要求 repro verify 记录存在。
- **cross-review**：每条 blocking 的 `evidence` 必须含至少一条 ≥20 字符的引文，且在 `--path` 输入文件的拼接文本中逐字出现；否则 `review-uncited-blocking`（problem，退 1）。记录增加 `provider_model` 与 `family_judgement`（已有）。
- 测试（约 18 条）：200+DOI 匹配 → verified 含 evidence；200+DOI 不符 → failed；200+title 明显不符 → failed；离线自写 verified 无 evidence → problem；cross-review 引文命中 → 通过；编造引文 → problem；run-log declared 标注。
- 判别力实测：DOI 改回"只看 200" → mismatch 用例失败；cross-review 去掉引文校验 → 编造引文用例失败。
- commit：`feat: bind gate evidence to external facts`

### Task 4: 收口（e2e + 迁移执行 + 结项）

- 对 `papers/example-paper` 执行迁移（Task 1 步骤）：`git init`、论文级 `.gitignore`、首提交；重跑 run-log 记录并断言 `git_commit` 指向论文仓库。
- 对示例论文跑 `claims_policy` 覆盖率报告，把 `checks.md` 声明改为工具生成；对受保护区未绑定数字如实报 problem（不粉饰；该论文的修复由使用者决定）。
- e2e 回归（约 6 条）＋终审（新评审者）；账本记录 E61–E63 与结项。
- 根目录未跟踪 `submission/`：与论文内 `submission/` 比对；若为误拷贝，记录并在用户确认后删除（本计划不擅自删除）。

## 完成定义（DoD）

- 新论文默认是独立 git 仓库；论文目录内任何 git 工具不再能命中父仓库（有负例测试）。
- 受保护区未绑定数字是 problem；豁免逐条可审计；`checks.md` 覆盖声明由工具生成。
- DOI `verified` 必须带响应体证据；cross-review blocking 必须带可逐字命中的引文；run-log 的 git 身份不再借父仓库。
- 全量测试全绿（tools 与 app），示例论文完成迁移并留证。
