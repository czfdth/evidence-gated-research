# automation-review 实施计划（跨模型评审 + 定时任务的确定性底座）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把设计 §5.1 与 §9 落成可执行、可审计、默认安静的底座：
1. `cross_review`——用 `codex exec` 起独立模型评审 gate，落结构化记录，严格解析结论，输入变化即判过期；
2. `milestones`——按 `target_venue.deadline` 倒排 T-14/7/3，到期报 gate 缺失项；无 deadline 时按顺序推进提示，不伪造倒排；
3. `watch`——按关键词查 arXiv，状态文件记录已见 ID，只报新增；"实质重叠"判定留给 agent；
4. `queue`——顺序跑实验清单：超时、显式重试、总预算，每次尝试都进 run-log（失败留档）；
5. `automation/` 接线文档与 prompt 模板——把"无实质变化不通知"写成明确指令。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v6：§5.1、§4.5、§9、§9.2、§12）
**账本：** Ruling E41–E45（本计划写入 `.superpowers/sdd/2026-10-03-evidence-tracking/progress.md`）

## 环境实测（2026-10-03）

- `codex-cli 0.160.0` 在 PATH；`codex exec` 支持 `-m/--model`、`-s/--sandbox read-only`、`--ephemeral`、`-C/--cd`、`--skip-git-repo-check`、`-o/--output-last-message`、`--output-schema`、`--json`。
- 设计 §5.1 的诚实边界：v4-pro 与执行模型 v4-flash **同族不同规模**，不是跨族；`workbuddy`(glm-5.2) provider 未定义。help 与记录必须照实写。
- `ccfa.yaml` 目前**没有** deadline 字段（validate.py 只校验 name/year/mode）；T-14/7/3 倒排需要它。

## Global Constraints

- 仓库根：`<repo-root>`；基线以每个任务派发时 HEAD 为准（写计划时 536 tests OK）。
- 退出码：`0` 通过/完成，`1` 发现问题，`2` 工具自身出错；`OSError`/解析失败 → `ValueError` → 2。
- 外部进程（`codex exec`、`arxiv` 抓取、实验命令）一律走**可注入 runner/fetcher**；测试默认离线；每次真实外部调用的证据必须写进任务报告。
- 写盘：原子写、不覆盖（`--force` 才覆盖）、`OSError` → `ValueError` → 2。
- 一条坏记录不得打断整轮审计；工具不得在自己的输出里做不实声明；显式点名来源的操作，源必须存在（九条规则）。
- UTF-8 无 BOM；ASCII 标识符与注释；中文只在面向用户的消息与测试数据。
- 测试命令：`& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`

## Rulings（写入账本时编号 E41–E45）

- **E41 cross_review 的诚实边界**：记录实际 `model` 字符串与"是否跨族"判定（`same-family` / `cross-family`，默认 v4-pro 记 `same-family`）；verdict 只来自结构化输出（`--output-schema` + `-o`），缺失/不合 schema → `review-malformed`（1），绝不默认通过；记录输入文件 sha256，`check` 在输入变化后报 `review-stale`；`codex exec` 一律 `-s read-only --ephemeral --skip-git-repo-check`。
- **E42 deadline 是可选字段**：`target_venue.deadline: "YYYY-MM-DD" | null` 加入模板与 `validate.py`（存在时校验格式与真实日历日，非法 → problem）；`newpaper/create.py` 支持 `--deadline`；无 deadline 时 `milestones` 输出 `mode: sequential` 的顺序推进提示，不伪造倒排日期。
- **E43 watch 只报事实**：工具只输出结构化新增条目（id/title/published/summary 截断），不做"实质重叠"判断；`--baseline` 首次运行只建基线并如实打印数量；状态文件原子写；网络失败 → 2 且不推进状态（不能丢未读条目）。
- **E44 queue 的失败分流**：每次尝试先写 run-log `running`、结束写终态（失败留档）；重试只针对清单显式声明的 `retry_exit_codes`（默认空 = 不重试）；超时=失败一次并计入重试上限；总预算按墙钟，`--budget-seconds` 耗尽即停并记 `stopped-budget`；重试耗尽记 `stopped-retries`；禁止静默重试到成功。
- **E45 默认安静**：工具本身不产生"我检查过了"的叙述；automation prompt 模板必须写明"无新增/无到期/无变化就不通知"；prompt 模板按 `automation/` 交付，实际挂载由用户确认后执行。

## Non-goals

- 真正的跨族评审（需要第二个 provider；当前配置里没有可用的）。v1 交付"同族不同规模 + 诚实标注 + 可替换 model 参数"。
- 自动修改论文正文或 `ccfa.yaml` 的结论字段（§9 硬约束一）。
- 分布式/并行实验调度、GPU 配额管理（本机单卡场景；v1 只做顺序队列与停止条件）。
- 语义检索/向量库（§8.4 按需）。

---

### Task 1: `milestones` + `deadline` 字段（T-14/7/3 倒排与 gate 缺失项）

**Files:**
- Create: `tools/ccfa/milestones.py`、`tools/tests/test_milestones.py`
- Modify: `ccfa.yaml.template`、`tools/ccfa/validate.py`、`tools/newpaper/create.py`、`tools/tests/test_validate.py`、`tools/tests/test_newpaper.py`（文件名以实际为准）

**Interfaces:**
- `parse_deadline(value) -> date | None`（None/空 → None；非法 → `ValueError`）
- `checkpoints(deadline: date) -> dict[str, date]`（`T-14`/`T-7`/`T-3`）
- `due_report(paper_root: Path, today: date) -> dict`：
  `{"mode": "countdown"|"sequential", "deadline": str|None, "due": [...], "missing_gates": [...]}`
  - countdown：`today == T-N` 当天输出该 checkpoint；`today > deadline` 输出 `overdue`；
  - sequential：无 deadline 时按 §4.5 的相对顺序给出"下一个建议动作"，不含具体日期。
- `main(argv) -> int`：子命令 `due`；`--today YYYY-MM-DD`（默认系统日期，测试必须注入）。

**判定表**

| 条件 | 结果 |
| --- | --- |
| deadline 缺失/null | `mode: sequential`，退 0，advisory 说明"无投稿目标日，按顺序推进" |
| deadline 格式非法/不存在日期 | problem `deadline-invalid`（1）；`create --deadline` 非法 → `ValueError` → 2 |
| 今天 = T-14/7/3 且有未过 gate | 列出该 checkpoint + 缺失项（1） |
| 今天不在 checkpoint 且未 overdue | 退 0，`due: []` |
| 今天 > deadline | problem `deadline-passed`（1） |
| stage 不在 stages.py 里（手改坏） | problem `stage-unknown`（1） |
| 无 deadline 的 sequential 模式 | 不得出现任何具体日期字符串（防伪造倒排） |

- [ ] **Step 1: 写失败测试**（约 14 条：三种 checkpoint 命中、非命中日、overdue、sequential 无日期、非法 deadline/日历、stage 未知、CLI 退出码 0/1/2、`--deadline` 写进新项目）
- [ ] **Step 2–4: 失败 → 实现 → 通过**；判别力实测：把 checkpoint 判定从"等于当天"改成"≤ 当天"（非命中日用例必须失败）；删掉 sequential 的日期清洗（"无日期"断言必须失败）
- [ ] **Step 5: 提交** `feat: check milestone countdowns against gate gaps`

### Task 2: `cross_review`（codex exec 编排 + 严格 verdict + 输入哈希）

**Files:**
- Create: `tools/ccfa/cross_review.py`、`tools/tests/test_cross_review.py`

**Interfaces:**
- `REVIEW_SCHEMA`（JSON schema：`verdict` ∈ {pass, blocking}；`blocking[]` 每项 {title, evidence}；`summary`）
- `build_prompt(paper_root: Path, stage: str, paths: list[Path]) -> str`（含角色、gate 判据、文件清单、输出契约、禁止改稿）
- `run_review(paper_root, *, model, stage, paths, runner=None, timeout=600, out_dir=None) -> dict`：调 `codex exec -m <model> -s read-only --ephemeral --skip-git-repo-check -C <root> --output-schema <schema> -o <last_msg> -`，prompt 走 stdin；记录 `{"model","family_judgement","verdict","blocking","summary","input_hashes","record_path","started_at","duration_s"}`
- `check_review(paper_root) -> list[Problem]`：无记录 → `review-missing`；输入哈希不符 → `review-stale`；verdict=blocking → `review-blocking`；JSON 不合 schema → `review-malformed`
- `main(argv)`：`run` / `check`

**判定表**

| 条件 | 结果 |
| --- | --- |
| runner 返回 0 且 `-o` 文件是合 schema JSON | 写记录（md + json），verdict=pass 退 0，blocking 退 1 |
| `-o` 缺失/JSON 不合 schema | `review-malformed`（记录 raw 输出），退 1，不写"通过" |
| `codex` 不在 PATH（`OSError`） | `ValueError` → 2，消息点名 `codex exec` |
| 子进程非零退出 | 2，stderr 摘要入记录 |
| 记录里的 model 是 v4-pro | `family_judgement == "same-family"`，help/记录照实写"非跨族" |
| 输入文件哈希与记录不符 | `check` → `review-stale`（1） |
| 记录不存在 | `check` → `review-missing`（1） |

- [ ] **Step 1: 写失败测试**（约 16 条：prompt 含 gate 判据与禁止改稿、argv 精确断言含 `-s read-only`/`--ephemeral`/`--output-schema`、pass/blocking/malformed/非零退出/缺 codex、记录原子写不覆盖（`--force`）、哈希入记录与 stale 判定、help 含同族声明、blocking 项的 evidence 原样保留）
- [ ] **Step 2–4: 失败 → 实现 → 通过**；判别力实测：把 malformed 处理改成默认通过（对应用例必须失败）；把 `-s read-only` 从 argv 去掉（argv 断言必须失败）
- [ ] **Step 5: 真实冒烟 + 提交**：在临时论文目录用**真实 `codex exec`** 跑一次（小输入、timeout 600s），把实际记录与耗时写进任务报告；commit `feat: run gate reviews with an independent model`

### Task 3: `watch`（arXiv 增量监控，只报新增）

**Files:**
- Create: `tools/ccfa/watch.py`、`tools/tests/test_watch.py`

**Interfaces:**
- `parse_feed(xml_text: str) -> list[dict]`（Atom；条目 {id,title,published,summary}；缺字段跳过并计数）
- `scan(feed_urls: list[str], state_path: Path, *, fetcher=None, baseline=False, limit=50) -> dict`：
  `{"baseline": bool, "new": [...], "seen_total": N, "skipped": M}`
- `main(argv)`：`scan --state <path> --url ... [--baseline] [--force]`

**判定表**

| 条件 | 结果 |
| --- | --- |
| 首次运行（无 state） | 自动按 baseline 处理：只写 state、`new: []`、stderr 如实打印"已建立基线 N 条" |
| 有 state 且出现新 ID | `new` 只含新 ID（旧 ID 不重复报） |
| 条目缺 id/title | 跳过并计入 `skipped`，不得让整轮失败 |
| 网络失败（fetcher 抛 OSError） | `ValueError` → 2，**state 不推进** |
| state 损坏（非 JSON/版本不符） | `ValueError` → 2，不覆盖 |
| 重复 URL | 去重后只抓一次 |

- [ ] **Step 1: 写失败测试**（约 12 条，含真实 Atom 样本字符串、空 feed、坏条目、baseline、增量、state 不推进、原子写、CLI 退码）
- [ ] **Step 2–4: 失败 → 实现 → 通过**；判别力实测：把"新 ID"判定改成"全部条目"（增量用例必须失败）；把失败时仍写 state（不推进用例必须失败）
- [ ] **Step 5: 提交** `feat: watch literature feeds for unseen entries`

### Task 4: `queue`（顺序实验队列 + 停止条件 + run-log 留档）

**Files:**
- Create: `tools/ccfa/queue.py`、`tools/tests/test_queue.py`

**Interfaces:**
- `load_queue(path) -> list[dict]`（清单：`[{name, command:[...], cwd?, timeout_s?, retry_exit_codes?[], max_attempts?}]`；schema_version=1）
- `run_queue(queue_path, *, log_dir, runner=None, budget_s=None, clock=None) -> dict`：
  `{"runs": [{"name","attempts","status"}...], "stopped": None|"budget"|"retries"}`
- 与 `run_log` 对接：每次尝试先 `running` 再终态（复用其 store 写契约；不重写 run_log 的私有实现——先读现有接口再决定是调用函数还是子进程）
- `main(argv)`：`run --queue <path> --log-dir <dir> [--budget-seconds N]`

**判定表**

| 条件 | 结果 |
| --- | --- |
| 命令退 0 | 该 run `status: complete`，退 0 |
| 命令退非 0 且不在 retry_exit_codes | `status: failed`，**不重试**，退 1 |
| 命令退在 retry_exit_codes 且未到 max_attempts | 重试；每次尝试都留档 |
| 重试耗尽 | `status: failed`，`stopped-retries`；退 1 |
| 超时 | 按一次失败处理并计入重试上限；状态注明 timeout |
| 墙钟预算耗尽 | 未跑的 run 记 `status: skipped-budget`；`stopped: budget`；退 1 |
| 清单非法/schema_version 不符 | `ValueError` → 2 |

- [ ] **Step 1: 写失败测试**（约 16 条，注入 runner 与 clock：成功、不重试的失败、重试后成功、重试耗尽、超时、预算停止、跳过项如实记录、每次尝试都进 log、argv `shell=False`、非法清单）
- [ ] **Step 2–4: 失败 → 实现 → 通过**；判别力实测：把"默认不重试"改成"失败即重试"（不重试用例必须失败）；把预算停止改成继续跑（预算用例必须失败）
- [ ] **Step 5: 提交** `feat: run experiment queues with explicit stop conditions`

### Task 5: 接线文档 + prompt 模板 + e2e

**Files:**
- Create: `paper-template/automation/README.md`、`weekly-watch.md`、`deadline-check.md`、`stage-advance.md`、`experiment-queue.md`
- Create: `tools/tests/test_automation_e2e.py`

**要求**
- 四个 prompt 模板必须包含：调用哪个脚本、看哪个输出字段、**"没有实质变化就不通知"**、以及"不得修改论文正文/结论字段"。
- `README.md` 写清挂载方式（Codex automations；本仓库为本地项目）与静默策略；实际创建 automations 需用户确认（E45）。
- e2e：临时论文目录跑 milestones（命中过期→1）→ watch（baseline 后增量）→ queue（一条成功一条失败）→ cross_review（注入 runner 的 blocking 记录 → check 报 `review-blocking`）。
- [ ] 提交 `docs: wire the automation layer with quiet-by-default prompts`

---

## 完成定义（DoD）

- 全量测试通过（536 基线 + ≥ 60）；四条判别力要求均有实测失败记录。
- Task 2 有**一次真实 codex exec 冒烟**的证据（记录文件、耗时、结论），不是只有注入测试。
- 四个 prompt 模板都写明"无实质变化不通知"；README 写明实际挂载需用户确认。
- 台账更新：E41–E45 的理由与代价、各任务 review 结论、结项 commit 区间。
