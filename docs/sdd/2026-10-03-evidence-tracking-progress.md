> **仓库正式留档（2026-10-03 从 `.superpowers/sdd/` 工作副本复制）**：
> 这是 E1–E52 全部裁定、各任务评审结论与挂账清单的唯一正式留档。
> 之后如再更新，以本文件为准；设计与计划分别见 `docs/design/` 与 `docs/plans/`。
> 文件里出现的 `<home>/Documents/Codex/...` 路径是历史来源，保留不改。

# SDD ledger — plan: （待写）evidence-tracking（provenance / run-log / research-version）

状态：**预研完成，实施计划尚未撰写**。本文件是该计划的恢复入口。

Spec: <home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md（v6，§6.1、§6.1.1、§9.2、§10）
Repo root: <repo-root>
基线: HEAD = `2c87264`，工作树干净，**305 tests OK**
前置: 四个确定性检查工具已齐备（citation-guard / trace-claims / latex-check / final-check）

## 参考实现（research-suite，MIT，已代码级深读头部与结构）

路径：`<home>/Documents/Codex/2026-10-03/wo/work/gh-clones/research-suite/tools/`

| 参考 | 结构 | 对我们的价值 |
| --- | --- | --- |
| `provenance-manifest/provenance_manifest.py` | 子命令 `add` / `log-calibration` / `check` / `verify-checksums` / `refresh` / `export`；一个 JSON store；`VALID_CLASSIFICATIONS = ("real", "rescaled-real", "documented-substitute")` | 逐文件来源 + 分类 + 校验和；**校验和可反查真实文件**（防"说明与数据漂移"）；分类里专门有"有据可查的替代品"一档 |
| `experiment-tracker/experiment_tracker.py` | 子命令 `run` / `log-metrics` / `list` / `show` / `find`；`run ... -- <cmd>` 包裹真实命令 | 自动记录 exit code、时长、git commit；`log-metrics` 事后挂指标 |
| `research-version/research_version.py` | 子命令 `snapshot` / `list` / `diff` / `show`；`.research-versions/` + `manifest.json`；`TEXT_SUFFIXES` 决定哪些文件做真 diff | 自动编号快照 + 任意两版真 diff；动机是替代手工 `mkdir/cp/git mv`（`git mv` 在空目录上会炸） |

### 参考实现的两个教训（我们自己必须避免）

1. **`experiment_tracker` 的静默空指标**：它的文档明写"调了 `run` 却没调 `log-metrics` 的驱动脚本，会把每次运行都记成空指标、且不报错"。这正是本工作流要防的失效方向——**记录看起来完整，其实关键字段空着**。
2. **`provenance_manifest` 是写盘工具**：它有 store、会改文件。我们的四个现有工具全是只读检查器，契约（§6.1.1 的"检查类工具只读"）不覆盖它们，所以这一层需要**新的写入契约**，不能照搬既有 CLI 约定。

## 本层与现有工具的根本区别

| 维度 | 现有四个检查工具 | 本层三个工具 |
| --- | --- | --- |
| 副作用 | 只读 | **写**（store / 日志 / 快照） |
| 退出码 | 0/1/2（发现/工具错误） | 需要重新定义：写入失败应可区分于"记录里有问题" |
| 幂等性 | 天然幂等 | 必须显式设计（重复 `run` 同一个命令、重复 `snapshot` 同一状态） |

这一点必须先定，否则会把只读工具的契约硬套到写盘工具上，产出"看起来像检查、实际在写文件"的怪物。

## 待定设计问题（写计划前必须先定）

### Q1 — run-log 的存储形态：单 JSON store 还是每次运行一个文件？

spec §10 写 `experiments/log/`，§9.2 又要求"失败必须留在 log 里"。参考实现用单 JSON store（并发写有覆盖风险）。候选：

- (a) **每次运行一个文件** `experiments/log/<run_id>.json`：天然防并发覆盖、单条损坏不影响其余、失败记录与成功记录同级；
- (b) 单 store `runs.json`（照搬参考）：查询方便，但并发与损坏风险集中。

倾向 (a)：§9.2 的"失败必须留档"要求单条记录的耐久性，而不是一个会被整体重写的聚合文件。

### Q2 — 指标空缺怎么办？

参考实现的致命弱点是"空指标静默通过"。我们的 `run-log` 若照抄，就会重演。候选：

- (a) `run` 结束时记为 `metrics: null`，并**另设一个检查**（`run-log check`）把"有 run 无指标"报出来；
- (b) `run` 拒绝在无指标时结束（不现实，指标通常事后才算）；
- (c) 记 `status: "metrics-pending"`，由后续 `log-metrics` 改为 `"complete"`，`check` 把 pending 当 problem 报。

倾向 (c)：状态显式，且"未完成"与"完成但指标为空"可区分——后者本身也是异常。

### Q3 — `--paper-root` / store 位置

spec §10 的布局已经把位置写死：`data/provenance.md`、`experiments/log/`。机器可读的 store 建议与人类文档并存（`data/provenance.json` + 生成的 `provenance.md`），而不是另找地方。research-version 的 store 建议 `.research-versions/`（gitignored 或入库需定）。

### Q4 — research-version 与 git 的关系（最需要想清楚的一条）

论文库已是 git 仓库，`snapshot` 与 `git commit` 功能重叠。参考实现的动机（替代手工 `mkdir/cp`、`git mv` 在空目录上炸）在 git 工作流里并不成立。

候选：

- (a) 照搬参考实现（独立版本库），与 git 并存；
- (b) 降级为 git 的薄封装（`tag` + `git diff`），保持"任意两版真 diff"的能力但不另建存储；
- (c) 本轮**不做** research-version，把它并入后面"复现与归档"计划，理由是它与 git 的边界没想清楚之前，独立实现大概率是重复建设。

倾向 (c) 或 (b)：**先不写一个与 git 打架的版本库**。这条要在写计划前定，因为它直接决定本计划是三个工具还是两个。

## 计划轮廓（待 Q4 定夺后确定任务数）

若 Q4 取 (b)/(c)：

1. `tools/ccfa/provenance.py` — store 的读写与校验（add / 校验和核对 / 导出 markdown）
2. `tools/ccfa/provenance_check.py` — 检查模式：文件与 store 漂移、缺来源、分类非法 → problem；**只读**
3. `tools/ccfa/run_log.py` — 包裹命令执行并落单文件记录（exit code / 时长 / git commit / 配置 / 种子 / 状态）
4. `tools/ccfa/run_log_check.py` — 检查模式：pending 指标、失败运行未留档 → problem；**只读**
5. 端到端回归（含"失败运行确实留在 log 里"与"空指标不会被当成完成"两条）

## 下一步

1. 先定 Q1–Q4（尤其 Q4），必要时改 spec（§6.1 的工具表 + 新的写入契约小节）。
2. 按 `superpowers:writing-plans` 写出含完整代码的实施计划（每任务带判别力检查）。
3. 再按 `superpowers:subagent-driven-development` 逐任务执行：task-brief → 派实施者 → review-package → 派评审者 → 记本 ledger。

## 控制器裁定（写计划前已定，Q1–Q4）

### Ruling E1（Q1）— run-log 每次运行落一个文件

Ruling: `experiments/log/<run_id>.json`，一运行一文件。
理由: spec §9.2 要求"失败必须留在 log 里"——这要求单条记录的耐久性，而不是一个会被整体重写的聚合文件；并发训练多个种子时单 store 还有覆盖风险。
代价: 跨运行查询需要自己聚合（后续若需要，再加一个只读的 `run-log list` 读全部文件，而不是改存储形态）。

### Ruling E2（Q2）— 指标空缺必须显式，且可被检查报出

Ruling: 记 `status: "metrics-pending"`；`log-metrics` 成功后改为 `"complete"`；`run-log check` 把 `metrics-pending` 与"complete 但 metrics 为空"都报为 problem。
理由: 参考实现的致命弱点正是"调了 run 忘了 log-metrics → 每次运行都记成空指标且不报错"。把"未完成"做成显式状态，是把那个静默陷阱变成可检测项。
代价: 每次实验多一次 `log-metrics` 调用；但少这一次调用会被检查抓住，而不是静默通过。

### Ruling E3（Q3）— store 位置沿用 spec §10 的布局

Ruling: `data/provenance.json`（机器可读）+ 由它生成的 `data/provenance.md`（人读）；运行记录在 `experiments/log/`。不另找位置。
理由: spec §10 已经把目录结构定死，新增约定会让"可恢复"这件事变差。
代价: provenance 与 run-log 分处两个目录，跨层查询要靠路径约定。

### Ruling E4（Q4）— research-version 本轮不做，并入后面的归档计划

Ruling: 本计划只做 `provenance` 与 `run-log` 两个工具；`research-version` 推迟到"复现与归档"计划，且默认按 **(b) git 的薄封装**（tag + diff）实现，除非届时有明确理由另建独立版本库。
理由: 论文库本身已是 git 仓库，`snapshot` 与 `git commit` 的功能重叠；参考实现的动机（替代手工 `mkdir/cp`、`git mv` 在空目录上炸）在 git 工作流里并不成立。在"它和 git 的边界"想清楚之前实现独立版本库，大概率是**重复建设**，而且会制造"两个版本真相"的风险——同一份稿子的"第几版"到底看哪个。
代价: 本计划少交付一个 spec 里列过的工具；但 spec §6.1 的工具表本来就标注了分阶段实施，且"先不建与 git 打架的东西"比"建了再拆"便宜。

### 由此确定的计划范围（两个工具、四个任务）

1. `tools/ccfa/provenance.py` — store 读写 + 校验和 + 导出 markdown（**写盘工具**，需新的写入契约）
2. `tools/ccfa/provenance_check.py` — 检查模式：与真实文件漂移、缺来源、分类非法（**只读**）
3. `tools/ccfa/run_log.py` — 包裹命令执行并落单文件记录（exit code / 时长 / git commit / 配置 / 种子 / status）
4. `tools/ccfa/run_log_check.py` — 检查模式：`metrics-pending`、`complete` 但指标为空、失败运行未留档（**只读**）

外加一次端到端回归，其中必须包含两条判别性用例："失败运行确实留在 log 里"与"空指标不会被当成完成"。

### 新的写入契约（写进 spec §6.1.1 的补充分支）

检查类工具只读不变；写盘工具（本层）另立三条：

- **原子写**：先写临时文件再改名，避免半截 JSON；
- **不覆盖**：同名 `run_id` 已存在时拒绝写入（除非显式 `--force`），避免把已经失败的记录悄悄盖掉；
- **幂等可查**：重复执行同一检查不产生新记录；重复 `snapshot`/`add` 同一目标必须报"已存在"而非静默重写。

## 设计修正（写计划时发现预研的一处不自洽）

预研轮廓把 provenance 拆成"写模块 + 独立检查模块"，但 spec §6.1 把它列为**一个**工具，而 §6.1.1 的写法是"检查类工具（…）只读"——同一工具存在只读的 check 模式是被允许的（先例：`citation-guard`）。拆两块会让 store 解析出现两份。

修正：`provenance` 按**单工具 + 三子命令**（`add` / `check` / `export`）实现，其中 `add` 是唯一写路径。已在计划里写明理由。

## Plan 已写（Part A）

- 计划文件：`<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-provenance.md`
- Task 1（store 写入路径 `add`）：含完整实现与完整测试代码；终态 **319**（305 + 14）。
- 自审修掉两处：一是我自己写进计划的中文命名测试（违反 ASCII 约束、且是容易被照抄的陷阱）；二是测试条数数错（14 不是 16）。
- **一处诚实的局限**：`save_store` 的原子性（临时文件 + `os.replace`）**无法被单测证伪**——把 `os.replace` 换回直接写，测试仍全绿。计划里已声明这一点，改用实现审查 + 评审者核对，而不是假装有测试覆盖。
- Task 2（`check` 只读漂移核对 + `export`）与 `run-log` 的两个任务留待后续。

## 下一步

1. 按既有模式执行 Task 1：`scripts/task-brief <plan> 1` → 派实施者（deepseek-v4-flash）→ `scripts/review-package` → 派评审者（deepseek-v4-pro）→ 记本 ledger。
2. Task 1 通过后写 Part B（`check` + `export` + e2e），再写 `run-log` 的两个任务。

## Plan A（provenance）执行进度

- Task 1: dispatched. Implementer agent `Bernoulli` = `01a1011f-e46d-78a2-9f69-81079ec27c47`, model `deepseek-v4-flash`.
  BASE = `2c87264`。Brief: `.superpowers/sdd/2026-10-03-provenance/task-1-brief.md`；Report: 同目录 `task-1-report.md`。
- Task 1: implementer reported DONE, commit `5e5c892`，**319/319**。判别力检查给出**负结果**（把 `os.replace` 换成直接写，套件仍全绿），实施者如实报告并改用代码审查核对原子性——与计划预先声明的局限完全一致，没有编造假测试。
- Task 1: review dispatched → 评审者 `Euclid` = `01a10121-8a80-73c3-98a4-960d8a0e9ddb`, `deepseek-v4-pro`。
  评审结果：Spec ✅，Approved，无 Critical。评审者确认实施者处理"不可测不变量"的方式诚实（跑负结果实验 → 回退 → 单独按代码核对），并核实工作树干净、无实验残留、两文件无 BOM。

### Ruling E5 — 写盘路径的 `OSError` 必须归为工具错误（控制器裁定：阻塞级）

评审列的第一条是 Minor：`save_store` 的 `mkdir`/`write_text`/`os.replace` 与 `add_entry` 的 `sha256_of`/`stat` 都可能抛 `OSError`，而 `main` 只捕 `(ValueError, ToolEnvironmentError)`——磁盘满或权限失败会变成 traceback + shell 退出 1，违反 §6.1.1 的 2-vs-1 分离。

控制器不接受"Minor"：这与 **R26a（latex-check）**、**P9/P11（final-check）**是同一条规则的第三次出现——**工具坏了不能看起来像检查发现了问题**。前两次都判了阻塞级，这里同样处理，否则规则就只是口号。

Ruling: 把写盘路径的 `OSError` 统一折成 `ValueError`（`load_store` 已经是这么做的，保持全工具一致），并补一条用例。
代价: 需要一条能可移植触发写失败的用例；若不可移植，沿用既有做法——受控 mock 或明确记录为按检查兜底。

### Ruling E6 — store 的 `version` 必须校验（控制器裁定：随 E5 一并修）

评审指出 `{"files": {}}`（缺 `version`）与 `{"version": 2, ...}` 都会被原样接受并保留。而同仓库的 `citation_ledger.py` **拒绝**缺失 `version`。同一套代码里两个 store 对同一字段采取相反态度，是不可接受的漂移。

Ruling: `load_store` 要求 `version` 存在且为整数（暂只接受 1），与 `citation_ledger` 的先例对齐。
代价: 未来升版需要显式处理迁移，而不是静默带着旧/新版本号继续读写——这正是我们想要的摩擦。

### 待执行的一轮修复波（E5 + E6）

两条都在 `tools/ccfa/provenance.py` 内，属小改动；按 skill 要求**一个**修复者处理，随后**一次**定向复审，预计终态 **321**（319 + 2）。完成后再进 Part B（`check` + `export`）。

### 其余 deferred minor（不阻塞）

- 校验和用例自指（比对的是同一个 `sha256_of`），一个"稳定但错误"的摘要在两处都会通过；实现本身用的是 `hashlib.sha256`，属覆盖盲区而非缺陷。
- 固定临时文件名 `<name>.tmp` 在并发写下会互踩（已声明不在本层目标内）。
- `read_bytes()` 整文件入内存（大文件场景未考量）。
- `Problem` 与测试文件里的 `json` 是未使用导入（逐字来自计划）。

## Plan A Task 1 结项

- 修复波：修复者 `Mill` = `01a10124-2c3c-7cb3-b7b9-661ae1b1f05b`，commit `748c78e`，**322/322**（319 + 3 条新用例）。
  E5：`save_store` 的 `mkdir`/`write_text`/`os.replace` 与 `add_entry` 的 `sha256_of`/`stat` 各自包住并折成 `ValueError`（与 `load_store` 的读路径风格一致）；新用例只 patch `os.replace`，`mkdir`/`write_text` 仍走真实临时文件，因此确实触达了真实写入。
  E6：缺 `version` 与 `version != 1` 都 `ValueError`，缺文件仍是空 store；与 `citation_ledger.py` 的先例对齐。
- 定向复审（`Epicurus` = `01a10125-7e82-7f92-961b-8ada394d19be`）：**两条均 ADDRESSED，无新 issue，fix accepted**。评审者另确认：被拒的 `add` 仍然在任何写入/校验和之前抛错（重复检查在读取块之前），store 保持字节不变；成功路径的 round-trip 未被改动。
  Task 1: complete (commits 2c87264..748c78e, review clean)

### Ruling E5/E6 的执行结果（一致性说明）

这两条与 **R26a（latex-check）**、**P9/P11（final-check）** 同源，都是"工具自身坏了不能看起来像检查发现了问题"。到这一层，"写盘路径的 OSError 必须归为退出码 2"已经从单个发现升级为**跨工具的固定规则**——后续任何会写文件的工具都应照此处理，不必再逐次论证。

## 当前状态

- Plan 6（证据追踪）进度：**provenance 的写入路径完成**（Task 1）。
- HEAD = `748c78e`，工作树干净，**322 tests OK**。
- 待办：provenance Part B（只读 `check` 漂移核对 + `export` 生成 `data/provenance.md` + e2e）；随后 run-log 的两个任务（包裹命令执行 + 只读检查 `metrics-pending`）。
- 全部裁定 E1–E6 已记录；Part A 的 deferred minor 见上。

## Plan 已写（provenance Part B）

- 计划文件：`<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-provenance-part-b.md`
- 三个任务：Task 2（只读 `check` 漂移核对，4 个新 code）、Task 3（`export` markdown + 原子写不覆盖）、Task 4（e2e）。终态依次 **328 / 334 / 339**。
- 计划里写明两处需要评审者知道的判断：
  1. **"写入时校验不构成读取时的信任"**——store 是人可编辑的 JSON，`check` 必须重新校验分类，不能因为 `add` 拒绝过非法值就信任读取结果。
  2. **`export` 不给 `--out` 时 stdout 是 markdown 本身、不是 JSON**——这是对 §6.1.1 的有意偏离，理由是 export 的产物就是人读文档；`check` 与 `add` 仍走 JSON。
- 自审又抓到并修掉两处：`text.count("\n| ")` 我写成 2（实际 3：表头、分隔行、数据行），会让用例直接失败；以及上面第 2 条的契约说明原先缺失。
- 一处允许的重构：把 `save_store` 里的"临时文件 + `os.replace` + `OSError → ValueError`"抽成共用的 `save_text_atomically`，供 `write_markdown` 复用；要求行为逐位不变（含临时文件名与 JSON 缩进），评审者需核对这一点。

## 恢复指引（下一次会话）

1. 确认 `git log` 有 `748c78e`、工作树干净、`Ran 322 tests ... OK`。
2. 按既有模式执行 Part B Task 2：`scripts/task-brief <part-b 计划> 2` → 派实施者（deepseek-v4-flash）→ `scripts/review-package` → 派评审者（deepseek-v4-pro）→ 记本 ledger。
3. 三个任务全绿后跑 provenance 的最终全分支评审（base `2c87264`），再进 `run-log`。
4. **跨工具规则提醒**：写盘路径的 `OSError` 一律折成 `ValueError` → 退出码 2（E5）；store 的 `version` 必须校验（E6）。这两条已定为跨工具规则，新工具照办，不必重新论证。

## Part B 执行进度

- Part B workspace：`.superpowers/sdd/2026-10-03-provenance-part-b/`。
- Task 2（只读 `check`）: implementer `Herschel` = `01a10128-a005-75c3-bc8a-6091e323ad27`，commit `b20b75b`，**328/328**。判别力检查（把漂移比较改成恒 False）实测让 `test_modified_file_is_reported_as_drift` 失败，随后恢复。
- Task 2 review: 评审者 `Schrodinger` = `01a1012a-6689-7c13-83f0-f30b7c37afae`。
  **Spec ✅，Approved，无 Critical/Important。** 评审者逐条核实：
  - **"写入时校验不构成读取时的信任"这一核心设计点确实实现**——`source` 与 `classification` 是从加载后的 store 重新校验的，与 `add_entry` 的写入时拒绝相互独立；
  - 四个 code 与判定表一致；`continue` 的位置正确（先报来源/分类，文件不存在时才跳过漂移检查，绝不会对不存在的路径算校验和）；
  - `check` 全程只读（`check_store` 不调用 `save_store`，`check` 分支只调 `emit`）；
  - E5（`sha256_of` 的 `OSError` 折成 `ValueError`）与 E6（复用 `load_store` 的版本校验、未重复实现）均满足；
  - `--store`/`--paper-root` 仍作为顶层参数位于子命令之前。
  Task 2: complete (commits 748c78e..b20b75b, review clean)

- Task 2: minor (deferred): 一条条目可能同时产出多个 code（缺来源 + 文件不存在等），行为正确但无用例钉住；手改 store 删掉 `sha256` 键会走 `provenance-drift` 且消息渲染成"记录 None"（结果可辩护，措辞待改）；`main` 的 `check` 分支缺 0/1 退出码的直接用例（Task 4 的 e2e 会覆盖）。

## 当前状态

- Plan 6（证据追踪）进度：provenance 的**写入路径 + 只读核对**完成；剩 Task 3（`export`）与 Task 4（e2e）。
- HEAD = `b20b75b`，工作树干净，**328 tests OK**。
- 终态：Task 3 → **334**，Task 4 → **339**。
- 账本裁定 E1–E6；跨工具规则（E5/E6）已固化。

## Part B Task 3（`export`）

- 实施者 `Lagrange` = `01a1012c-a28a-7531-81a6-21741b6f2d66`，commit `4feff44`，**334/334**。
  自报的重构验证是**实测**而非口头保证：新 `save_store` 的输出字节与改动前逐位相同，临时文件名、`mkdir`、错误消息字符串都不变，且不残留临时文件。
- 评审者 `Anscombe` = `01a1012e-8aa7-73d2-88cb-e6481bd36738`：**Spec ✅，Approved，无 Critical/Important**。评审者独立对照 `b20b75b` 确认抽取是逐位等价的（唯一的额外物是 `description="store"` 关键字，存在的目的正是**保住原来那句错误消息**）；`write_markdown` 在任何写入之前检查"存在且未 force"，失败写入因 `os.replace` 是提交点而不会破坏旧文件；`render_markdown` 对缺字段渲染空白而非崩溃、行序确定；`export` 不给 `--out` 时只调 `load_store`/`render_markdown`/`print`，一个字节都不写——那条有意的 stdout 偏离被正确尊重。
  Task 3: complete (commits b20b75b..4feff44, review clean)

### Ruling E7 — 一个"几乎不测任何东西"的测试必须重写（控制器裁定：必改）

评审指出 `test_render_does_not_write` 只断言 `self.store.exists()`——而那在 `setUp` 里 `add()` 之后就成立了。**就算 `render_markdown` 把 store 覆写了，这条测试照样通过**。它与 Plan 3 的 `Table 3`、Plan 5 的哈希分支用例同属一族：**看起来有测试，其实没有判别力**。

Ruling: 必改。改成捕获 render 前后的 store 字节并断言相等（`before = self.store.read_bytes(); render_markdown(...); assertEqual(before, self.store.read_bytes())`）。
理由: 这条测试的**唯一**目的就是证明"渲染不写盘"；它现在连这个目的都没做到，等于这条设计约束没有任何证据。
代价: 一处 3 行改动 + 一次定向复审；无行为变更。

### 其余 deferred minor（不阻塞）

- `print(render_markdown(store))` 会多一个尾随空行（文档本身已以 `\n` 结尾）——逐字来自计划，无害。
- 报告里把"改动前"写成 `git show HEAD:...`，而提交后 HEAD 已变；应写基准 `b20b75b` 才可复现。证据本身成立。

## 当前状态

- Plan 6 进度：provenance 的写入路径、只读核对、导出三块完成；剩 **Task 4（e2e）** 与 **E7 的修复**。
- HEAD = `4feff44`，工作树干净，**334 tests OK**。
- 下一步：先做 E7 修复（含定向复审），再执行 Task 4（终态 **339**），随后跑 provenance 的最终全分支评审（base `2c87264`）。
- **跨工具规则（已固化，新工具照办）**：写盘 `OSError` → `ValueError` → 退出码 2；store 的 `version` 必须校验；**"有测试"不等于"有判别力"——每条判别力检查必须实测其能在错误实现下失败**。

## Part B Task 4（e2e）与 E7 修复

- 实施者 `Carver` = `01a10130-19a5-72f3-b52e-aa16e5b6dccf`，两个 commit：`d536f32`（E7 修复）+ `9eae7b7`（5 条 e2e），**339/339**。
  **取证方式值得记**：yòng 变异副本验证 e2e 有判别力——把 `check_store` 强制返回空列表后，漂移用例确实失败；E7 修复也用模拟"会写盘的 render"证明旧断言仍会通过、新断言会失败。这正是这条规则要的"实测而非声称"。
- 评审者 `Darwin` = `01a10132-6053-77f3-976f-9a26f0597393`：**Spec ✅，Approved，无 Critical/Important**。评审者独立核实：diff 只碰两个测试文件、`provenance.py` 未被改动；E7 断言读的是"`add` 写盘之后、render 之后"两个正确时刻的真实字节，不可能在文件不存在时静默通过；漂移用例同时钉住退出码 1、`provenance-drift` 与 stderr 里的绝对路径；子进程设置（`sys.executable`、`PYTHONPATH=tools`、`encoding="utf-8"`）符合既有惯例；还独立复现了顶层参数位置陷阱（flags 放在子命令之后 → 退出 2、stderr 有 usage、stdout 为空）。
  Task 4: complete (commits 4feff44..9eae7b7, review clean)

- Task 4: minor (deferred): 两条退出码 2 的用例只断言"退出码 2 + stdout 空"，无法区分工具自身的 `tool_error` 与 argparse 的 `SystemExit(2)`（加 `assertIn("工具错误", stderr)` 即可钉住，非阻塞）；e2e 无 `tearDown` 清理临时目录；位置陷阱只是手工验证、未固化为用例（brief 未要求）；`test_add_then_check_is_clean` 是最弱的一条——`add` 静默什么都不做也能过，但被漂移用例兜住。

## provenance（Plan 6 前半）结项状态

- **四个任务全部完成并通过任务级评审**：Task 1 写入路径、Task 2 只读核对、Task 3 导出、Task 4 e2e。
- HEAD = `9eae7b7`，工作树干净，**339 tests OK**。
- 分支范围：`2c87264..9eae7b7`（provenance 全部 7 个 commit）。
- 工具现状：`provenance.py` 三个子命令 `add` / `check` / `export`，写盘契约（原子写、不覆盖、`OSError`→2、`version` 校验）与只读契约并存。

## 下一步

1. **provenance 的最终全分支评审**（base `2c87264`，head `9eae7b7`），并把全部 deferred minors 交给它分流。
2. 随后 **`run-log`**：两个任务（包裹命令执行并落单文件记录 + 只读检查 `metrics-pending`），按 E1/E2 的设计——一运行一文件、`metrics-pending` 显式状态、把参考实现那个"忘了 log-metrics 就记成空指标且不报错"的陷阱变成可检测项。
3. 之后按 spec §6.1：「复现与归档」计划（含被 E4 推迟的 `research-version`，走 git 薄封装）→ 知识层（FTS5 + 记忆）→ 自动化与跨模型评审 → 模板库与派生流程。

### 已固化的跨工具规则（新工具照办，不必逐次论证）

1. 写盘路径的 `OSError` → `ValueError` → 退出码 2（来源：latex-check R26a、final-check P9/P11、provenance E5）。
2. store 的 `version` 必须校验（E6）。
3. "有测试"不等于"有判别力"——每条判别力检查必须实测其在错误实现下失败（来源：Table 3、哈希分支、E7）。
4. 闸门没跑全不能报成功（final-check P8：含 `check-skipped` 的一轮退出码为 2）。

## provenance 最终全分支评审

- 评审者 `Poincare` = `01a10135-9050-7e91-9ac5-ee1486826108`, `deepseek-v4-pro`（最高档）。Diff: `.superpowers/sdd/2026-10-03-provenance-part-b/review-2c87264..9eae7b7.diff`（6 commits）。
- **Verdict: Needs fixes**（1 Critical + 3 Important）。
- §6.1.1 写盘契约逐条核实**满足**：原子写（同目录 `.tmp` + `os.replace`）、`add` 与 `export --out` 都不静默覆盖、`check` 幂等不写、`OSError` 折成 `ValueError` 覆盖写/读/哈希三条路径。核心设计点（`check` 重新校验来源与分类，不信任写入时校验）被确认真实存在。

### Ruling E8 — 逐条 store 未校验 → 工具崩溃（Critical，必改）

评审者**实测复现**：`load_store` 只校验顶层与 `files` 是对象，**没校验每个值也是对象**。手改 store 成 `{"version":1,"files":{"data/a.csv":"oops"}}` 后，`check_store` 的 `entry.get(...)` 抛 `AttributeError` → traceback + shell 退出 1，而契约要求工具错误 2。这是本分支存在的意义所要防的那类混淆（工具坏了看起来像检查发现问题），也是同一条跨工具规则的第四次出现。

Ruling: 在 `load_store` 里要求 `files` 的每个值都是对象（键须为字符串），使该路径收敛为 `ValueError` → 退出 2。补一条用例（手改 store 塞入非对象条目 → `main` 返回 2 且 stdout 为空）。
代价: 无；这是把已有的严格性补全。

### Ruling E9 — 脚手架预置的 `provenance.md` 与 `export` 的不覆盖规则冲突（Important，必改）

评审者发现：Plan 1 的脚手架会预建 `data/provenance.md`，而本工具 `export --out data/provenance.md` 在不带 `--force` 时**拒绝覆盖**——于是一篇新论文的第一次规范导出直接退 2。同时机器可读的 `data/provenance.json` 既不在 spec §10 里、也没被脚手架预置。

Ruling: **在源头消除冲突**——脚手架改为预置空的 `data/provenance.json`（`{"version":1,"files":{}}`），不再预建 `provenance.md`；`provenance.md` 由用户首次 `export` 生成，路径本来就不存在，不覆盖规则自然成立。同时把 `data/provenance.json` 补进 spec §10 的目录树。
理由: 不覆盖规则的目的是保护**用户写下的记录**；脚手架预置的是一个空占位符，用"允许覆盖"去兼容它会让不覆盖规则变得有条件、容易失守。改脚手架是一处小改动，且让"机器可读 store 是被跟踪的产物"这件事变得明确。
代价: 需要改 Plan 1 已评审过的 `tools/newpaper/create.py` 与其测试；§10 目录树要补一行。

### Ruling E10 — "从未登记的数据文件"看不见（Important，定为可选扫描）

`check_store` 只遍历 store 里已有的条目，`data/` 下从未登记的 CSV 完全不可见——而 §4.2 的 `data-ready` gate 要求"逐份数据有来源、分类与校验和"。这半条目前没有任何机制见证。

Ruling: `check` 增加 `--scan DIR`（可选）；给了就列出该目录下**没有条目**的文件，code `provenance-unrecorded`，归 problem。默认关闭，避免对只想核对已有条目的用法产生意外噪声；spec §4.2 的 `data-ready` gate 应显式用 `--scan data` 调用。
理由: 机械可判定的完整性检查必须有入口，但默认开会对"尚未登记任何数据"的早期项目造成满屏噪声；可选开关把选择权留给 gate。
代价: gate 的调用方必须记得带 `--scan`，否则这半条仍然没人查——这一点要写进 spec 的 gate 描述里。

### 待执行的一轮修复波（E8 + E9 + E10）

三个发现中：E8 是 `provenance.py` 内的窄修；E9 跨到 `newpaper/create.py` 与 spec §10；E10 是 `check` 的新可选参数。按 skill 要求**一个**修复者处理全部，随后**一次**定向复审。预计新增 3–4 条用例。

### 其余 deferred minor（评审判定可 defer）

临时文件名固定、并发写会互踩；`read_bytes()` 整文件入内存；`export` stdout 多一个尾随空行；`--classification` 由 argparse `choices` 拦截因而 CLI 走不到 `add_entry` 自己的校验（两处校验的报错呈现不同）；`--source ""` 会被写入然后立刻被 `check` 报缺失；两条退出码 2 的 e2e 用例无法区分 `tool_error` 与 argparse 自身的退出 2（加一句 stderr 断言即可钉住）。

## 修复波（E8 + E9 + E10）与定向复审

- 修复者 `Arendt` = `01a10138-7217-7290-b6dd-92f8ff094d1a`，commit `defe288`，**342/342**。
- 定向复审（`Poincare`）：**E8 / E9 / E10 全部 ADDRESSED，fix accepted，无新 Critical/Important**。评审者逐条核实：
  - **E8**：`load_store` 在任何 `.get(...)` 之前就拒绝非字符串键与非对象值；新用例走的是 `main("check")`，断言退出 2 + stdout 空 + 错误文案——测的是 CLI 映射，不只是 `load_store`。
  - **E9**：脚手架改为预置 `data/provenance.json`（`{"version":1,"files":{}}`）并去掉了 `.md` 预置；既有脚手架**测试被更新而非删除**，且新增断言"JSON 可解析"与"`.md` 不存在"；`write_markdown` 的不覆盖规则**未被放松**；§10 已列两个文件。
  - **E10**：`--scan` 默认关闭（并有用例钉住默认关闭时不报），未登记文件每个恰好产出一条 `provenance-unrecorded`；`--scan` 指向不存在或非目录时 `ValueError` → 退出 2。
  - 退出码与写盘契约未被改动，diff 无新破坏。

- 修复波新增 minor (deferred)：`scan` 把路径规范化为 `data/a.csv` 却与 store 的**原始键**比较，因此若有人用 `data/../data/a.csv` 或 Windows 反斜杠登记，扫描会把它误报为未登记（与此前那条"非规范键"同源，现在在 scan 里显形）；`version: true` / `1.0` 仍被当作 1（E6 的"整数"只说了一半，且不触达 `.get`）；非字符串键分支无回归用例。

## provenance 结项

- **六个 commit 全部落地并通过任务级评审 + 最终全分支评审 + 一轮修复波复审。**
- HEAD = `defe288`，工作树干净，**342 tests OK**。
- 工具形态：`provenance` 三子命令 `add` / `check` / `export`；写盘契约（原子写、不覆盖、`OSError`→2、`version` 校验、逐条对象校验）、只读契约（`check` 重校验来源与分类）、可选完整性扫描（`--scan` → `provenance-unrecorded`）。
- Plan 1 的脚手架随之改为预置 `data/provenance.json`，`provenance.md` 改由首次 `export` 生成。

## 下一步

1. **`run-log`**：两个任务（包裹命令执行并落单文件记录 + 只读检查 `metrics-pending`），按 E1/E2 —— 一运行一文件、`metrics-pending` 显式状态、把参考实现"忘了 log-metrics 就记成空指标且不报错"的陷阱变成可检测项。需先按惯例深读参考实现主体（本轮只读了头部）。
2. 之后：「复现与归档」计划（含 E4 推迟的 `research-version`，走 git 薄封装）→ 知识层（FTS5 + 记忆）→ 自动化与跨模型评审 → 模板库与派生流程。

## run-log 预研（参考实现主体已深读）

`research-suite/tools/experiment-tracker/experiment_tracker.py` 的关键实现：

| 它的做法 | 对我们的意义 |
| --- | --- |
| `get_git_state()` 同时取 `git rev-parse HEAD` **与** `git status --porcelain`，记录 `git_commit` + `git_dirty` | **直接吸收**：脏树上的运行无法仅凭 commit 复现，"脏"这个事实必须进记录 |
| 用 `<store>.lock` 锁住"读 store → 分配 run_id → 保存" | 由于我们已裁定一运行一文件（E1），**不需要 store 锁**；run_id 的竞争改用 `open(path, "x")` 原子占位解决 |
| 在命令启动**之前**分配 run_id 并落盘（注释明说"在长命令开始前分配，而不是之后"） | **直接吸收**：进程被杀也留下 `running` 记录——这正是 §9.2"失败必须留在 log 里"要的耐久性 |
| `run` 结束后把指标留空，等 `log-metrics` 补齐；忘了调用**不报错** | **必须偏离**（E2）：把静默空指标改成显式 `metrics-pending` 状态 + 可检测 |
| `run` 的 summary 行同时打到 stdout 与 stderr（因为"只捕获其中一路的驱动脚本也该看到 run_id"） | 吸收其意图，但我们的契约是 stdout 走 JSON、stderr 走人读摘要，run_id 进 JSON 即可 |
| `run` 返回被包裹命令的退出码 | **需裁定**（见 E11） |

### Ruling E11 — `run` 的退出码：默认不传播被包裹命令的码

冲突：`run` 作为包装器，直觉上应把被包裹命令的退出码传出去（脚本/CI 依赖它）；但本项目已把 `0/1/2` 定为"工具自身状态"的机器契约，若被包裹命令恰好退 2，就与"工具自身出错"不可区分。

Ruling: **默认 `run` 退出 0（只要记录成功落盘），被包裹命令的退出码写进记录与 JSON；工具自身失败（无法占位 run_id、无法写记录）退 2。另给 `--propagate-exit` 开关**，需要脚本直接消费被包裹命令状态时显式启用。
理由: 一次失败的实验是**被记录下来的结果**，不是工具故障；把两者混在同一个码上，会让"闸门没跑全"与"实验失败"再次不可区分——这正是本项目反复付出代价的那类混淆。默认干净 + 显式逃逸口，比默认含糊好。
代价: 现有习惯"包装器返回内部命令的码"需要改；用 `--propagate-exit` 可恢复。

### Ruling E12 — 运行记录的结构与写入时机

Ruling: 一运行一文件 `experiments/log/<run_id>.json`，字段：`run_id`、`command`（argv 数组）、`cwd`、`config`（路径 + `sha256` + 解析后的内容）、`seed`、`git_commit`、`git_dirty`、`started_at`、`finished_at`、`duration_s`、`exit_code`、`status`（`running` → `completed` / `failed`）、`metrics`（未记录时为 `null`）、`notes`。
**关键时机**：命令启动**之前**先落一条 `status: "running"` 的记录；结束后再原子更新为 `completed`/`failed`。
理由: 长任务被杀、断电、卡死都应留下证据（§9.2）。只在结束时写记录，等于"跑挂了的实验没有痕迹"。
代价: 每次运行多一次写盘；`running` 状态的收尾依赖下一次调用（`check` 会把长期停留在 `running` 的记录报出来）。

### Ruling E13 — run_id 的原子占位

Ruling: run_id 由时间戳加序号构成（如 `20261003T142530-01`）；用 `open(path, "x")` 创建文件作为**原子占位**，`FileExistsError` 就顺延序号。不引入锁文件。
理由: 一运行一文件之后，并发安全只需保证"同一 id 不被两个进程同时认领"，`O_EXCL` 语义正好够用；锁文件是为单 store 设计的，我们不需要。
代价: 同一秒内并发启动多个运行会顺延序号，这是期望行为。

### Ruling E14 — `run-log check` 的判定表

| 条件 | code | 归类 |
| --- | --- | --- |
| `status == "metrics-pending"`（运行完成但未记录指标） | `run-log-metrics-pending` | problem |
| `status == "completed"` 但 `metrics` 为空对象 | `run-log-empty-metrics` | problem |
| `status == "running"` 且 `started_at` 早于阈值（默认 24 小时） | `run-log-stale-running` | problem |
| `git_commit` 为空 | `run-log-missing-commit` | problem |
| `git_dirty == true` | `run-log-dirty-tree` | advisory |
| `status == "failed"` | 不报 | —— |

Ruling: 上表为准。**失败的运行不报**——它是被记录下来的合法结果，不是缺陷；闸门要防的是"跑了但没有记录"与"记了但没有指标"。
代价: `git_dirty` 只是 advisory，脏树运行不会被闸门拦下；如将来要收紧，把它升为 problem 即可。

## run-log 计划轮廓（待写）

1. `tools/ccfa/run_log.py` — 记录结构、原子占位、`run` 包裹执行（含 config/seed/git 采集）、`log-metrics`
2. `tools/ccfa/run_log_check.py`（或同一工具的 `check` 子命令）— 只读判定表实现
3. 端到端回归：必须包含"被 kill 的运行留下 `running` 记录"与"空指标不会被当成完成"两条判别性用例

## 参考清单核查（用户 2026-10-03 提供的截图，已 clone 三个新仓库）

来源：用户截图列出的"核心方法论参考 + 社区 Skill/模板 + 底层执行器"。按惯例做代码级浅读，不看名字下结论。

### 最重要的结论：清单里大部分**本机已经装了**

| 清单项 | 核查结果 |
| --- | --- |
| `K-Dense-AI/scientific-agent-skills` | 已 clone（2809 文件）；其 `skills/` 是**领域工具箱**（生物/化学/物理/统计等 100+ 个，如 `aeon`、`astropy`、`dask`、`citation-management`、`experimental-design`）。**本机已装其中多个**（`kdense-scientific-brainstorming`、`kdense-statistical-analysis` 等）。 |
| `huangwb8/ChineseResearchLaTeX` | 已 clone（1433 文件）；其 `skills/` 下 **27 个技能本机全部已装**（`nsfc-abstract` / `nsfc-budget` / `nsfc-qc` / `make-latex-model` / `paper-write-sci` / `research-literature-*` 等）。 |
| `wanshuiyin/Auto-claude-code-research-in-sleep` | 早前已核查（83 skills，见 `2026-10-03-github-workflow-review.md`），是设计文档 §5.1 跨模型评审与 §8.2 研究记忆的来源。 |
| `WUBING2023/PaperSpine` | 已 clone（1479 文件）；见下。 |
| `ganzhi-black/humanities-thesis-skill`、`Doryoku1223/lunwen-skill` | 未 clone（本轮预算所限）；从命名看面向人文社科与中文论文写作，与本工作流的英文 CS 会议主路径重叠度低。 |
| `Anthropic Claude Code`（底层执行器） | 与我们的执行器（Codex）不同。这是**适配层问题**，不是方法论问题；PaperSpine 的 `src/adapters` 正是为这种多运行时做的。 |

**由此得出的行动结论**：这份清单的价值**不是"去重建这些能力"，而是"去接线"**——领域技能与中文 LaTeX 技能已在环境里，缺的是工作流把它们按 stage 路由起来（设计文档 §5 的 `ccf-pipeline-orchestrator` 路由规则）。

### 两处对我们后续计划有直接价值的新发现

1. **`ChineseResearchLaTeX` 带真实模板包**：`packages/` 下有 `bensz-nsfc`、`bensz-paper`、`bensz-thesis`、`bensz-cv`、`bensz-fonts`。这直接影响**"模板库与派生流程"计划**——原计划是要自建 `paper-template/`，现在应当先评估复用 `bensz-paper`（论文）与 `bensz-nsfc`（基金），而不是闭门造模板。
   代价/风险: 该仓库的模板面向中文科研与 NSFC，与我们主路径（英文 CS 会议 LaTeX）的版式要求不同；复用前要确认它的模板是否可参数化到英文会议。

2. **`PaperSpine5` 是端到端全流程 Skill，且是多运行时适配设计**：它覆盖查文献→梳理论点→大纲→全文→科研配图→引用核验→审阅→排版，交付可编辑 Word / LaTeX / PDF；`src/` 下有 `adapters` / `scripts` / `skill`，说明它同时适配多种底层执行器。它的自述原则与我们的确定性层**同向**："研究材料优先保存在本地；论点、引用和图表均以真实资料与证据为依据"。
   对我们的意义: (a) 它的 `adapters` 结构回答了"如何不绑死单一执行器"；(b) 它的全流程覆盖说明我们手搓的五个工具在**功能上不是空白**，我们的差异化在于**机械可核验**（它是靠流程与提示词约束，我们靠退出码与 JSON）；(c) 后续"模板库与派生流程"计划应参考它的 section 骨架与交付形态（Word + LaTeX + PDF 三份）。

### 与现有设计的对照结论

- 设计文档 §6 "直接复用，不新建"的判断**被证实是对的且比原先写的更充分**：可复用的面比 CCFA 17 个技能宽得多（加 K-Dense 领域技能与 ChineseResearchLaTeX 的 27 个）。
- 我们的差异化仍然成立且更清晰：**已建成的五个工具做的是机械可核验**（引用/数字/结构/终稿/来源），这一层在上述参考项目里都没有等价的退出码级契约。
- 待办不变：`run-log` → 复现与归档 → 知识层 → 自动化与跨模型评审 → **模板库与派生流程（新增强制前置：先评估 `bensz-paper` / `bensz-nsfc` 的复用可行性）**。

## run-log Part A 计划已写

- 计划文件：`<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-run-log.md`
- Task 1（记录结构 + 原子占位 + `run` 包裹）：含完整实现与完整测试代码，终态 **353**（342 + 11）。
- 计划里写死的关键点：
  - **命令启动前落 `running` 记录**，判别力检查会实测这点（把落盘挪到命令之后，相关用例必须失败）；
  - `config` 以"路径 + sha256 + 解析后内容"三件套记录，使记录**自包含**；
  - `git_dirty` 进记录（脏树运行无法仅凭 commit 复现）；
  - run_id 用 `open(path, "x")` 原子占位，**不引入锁文件**（一运行一文件后锁是多余的）；
  - E11 的退出码例外：`run` 默认退 0（记录成功即成功），`--propagate-exit` 才透传被包裹命令的码，工具自身失败退 2。
- **跨工具重构**：把原子写抽成 `cli.save_text_atomically`，`provenance.py` 改为调用它——写盘契约只应有一份实现。计划特别标注：`provenance` 原来的描述词是 `"store"`，调用时必须显式传 `description="store"` 才能保住原错误消息，评审者会专门核对。
- 自审修掉两处：不可写目录的用例原用根路径（Windows 上权限因机器而异），改为"用文件当目录父级"（每个 OS 都确定性失败）；`cli.py` 的代码片段原把 import 写在函数内，已改为顶部 import。
- **必须传给 Part B 的边界**：`O_EXCL` 占位文件先是 `{}`；若进程在"占位"与"写入 running"之间被杀，会留下**没有 `status` 字段**的记录。Part B 的 `check` 必须把它报成 problem（建议 `run-log-malformed`），否则这类损坏会静默通过。

## 当前状态

- HEAD = `defe288`，工作树干净，**342 tests OK**。
- 已建成五个工具（citation-guard / trace-claims / latex-check / final-check / provenance）；
  `run-log` 设计与 Part A 计划就绪，待执行。
- 剩余：run-log Part A/B → 复现与归档 → 知识层 → 自动化与跨模型评审 → 模板库与派生流程。

## run-log Task 1 执行记录

- 实施者 `Locke` = `01a10145-9acb-7c53-8a43-d2fb925d4037`，commit `f5f2126`，**353/353**。
  **它对我计划里的计数错误处理得比我写的好**：计划写"11 条测试"却只给了 10 条。它没有把数字改小，而是**补上了缺的那条覆盖**（`main` 的 E11 退出码规则回归）——我的算术错误恰好暴露了一个真实覆盖空洞。这条值得作为"计划散文数字让位于测试代码"（C6/R4 先例）的正面案例记下来。
  另一处好判断：`save_text_atomically` 的抽取里，它保留了 `provenance` 原来 `无法写入 store` 的**空格格式**，而没有照抄计划片段里的无空格写法——以"保住原消息"的裁定为准，而不是以计划字面为准。
- 评审者 `Nietzsche` = `01a1014b-bbcb-7f33-84b2-cdec591e3b94`：首轮 **Needs fixes**（1 Important），其余全部核实通过——耐久性次序正确（`write_text` 关文件 + `os.replace` 之后才调 runner；把写盘挪到命令后会让该用例以 `KeyError` 失败，是"因正确原因失败"）、抽取逐位等价、`new_run_id` 是真 `O_EXCL`、`git_state` 三种失败都不抛、E11/E12/E13 全部符合、测试不依赖工作区自身 git 状态。

### Ruling E15 — 相对配置路径必须按 `paper_root` 解析（评审发现，必改）

评审者**复现**了：`read_config` 用 `path.resolve()`，相对路径会按**进程 CWD**解析，而不是 `paper_root`。于是从论文根目录之外调用 `run-log --paper-root X run --config configs/a.yaml` 直接退 2。计划里那条测试只传了绝对路径，正好漏掉这条主路径。

Ruling: 相对路径先与 `paper_root` 拼接再 `resolve()`；绝对路径行为不变（根内可用、根外仍拒）。补一条不改 CWD 的回归用例。
理由: "路径相对 paper_root" 是记录在案的文件契约；按 CWD 解析会让同一条命令在不同目录下行为不同——对可复现性工具来说这是最不该有的不确定性。
代价: 无。

- 修复 commit `3a37f37`，**354/354**（353 + 1）。定向复审（`Nietzsche`）：**ADDRESSED，无新 issue，fix accepted**。评审者确认绝对路径在根内仍可用且仍返回根相对路径、根外仍被拒；新用例在旧实现下确实会失败（测试进程 CWD 是仓库根，不在临时 paper_root 之下）。
  Task 1: complete (commits defe288..3a37f37, review clean)

- Task 1: minor (deferred): `provenance` 的那条写失败用例只断言退出码与 stdout 为空、不校验错误消息，所以"`store` 一词被逐位保留"这件事**没有自动化测试钉住**（实现正确，属覆盖缺口）；`main` 的退出码 2 路径（空命令、不可写日志目录）无用例直接走 `main`；`main` 把 run id 打到 stdout、`git_state` 用 10 秒超时，都是计划未规定的设计选择。

## 当前状态

- HEAD = `3a37f37`，工作树干净，**354 tests OK**。
- 五个确定性工具 + **run-log 的耐久记录与包裹执行**已完成并过评审。
- 剩余：run-log Part B（`log-metrics` + 只读 `check` 实现 E14 判定表 + e2e，含 `run-log-malformed` 那条边界）→ 复现与归档 → 知识层 → 自动化与跨模型评审 → 模板库与派生流程。
- run-log Part B 计划已写：`<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-run-log-part-b.md`（Task 2 = `log-metrics` + `check`，终态 369；Task 3 = e2e，终态 373）。

### Ruling E16 — E2 的 `metrics-pending` 状态值作废，以 Part A 冻结的形状为准

写 Part B 计划时发现控制器自己造成的矛盾：预研 E2 说"记 `status: "metrics-pending"`，`log-metrics` 后改为 `complete`"；但 Part A 的 E12 冻结了记录形状——`status` 只取 `running` / `completed` / `failed`，`metrics: null` 表示尚未记录。两者不可能同时成立。

Ruling: **以 Part A 已实现并过评审的形状为准**；E2 的意图（把静默空指标变成显式可检测）改由 `check` 的判定实现，不再多一个状态值。
理由: `status` 回答"命令跑成没有"，`metrics` 回答"指标记了没有"——两个正交事实塞进一个字段会互相覆盖。分开放，判定表同时读二者即可。
代价: E2 里那个具体状态名作废；将来若要单独表达"指标未记"，应加 `metrics_status` 字段，而不是复用 `status`。

### Part B 判定表（已定，含两条边界）

`run-log-malformed`（缺 `status`，即 `O_EXCL` 占位后进程即死的 `{}` 残留 / JSON 不可读 / `running` 却无有效 `started_at`）、`run-log-metrics-pending`（completed 且 `metrics is None`）、`run-log-empty-metrics`（completed 且 `metrics == {}`）、`run-log-stale-running`（running 超过 `--stale-hours`，默认 24）、`run-log-missing-commit` 均为 problem；`run-log-dirty-tree` 为 advisory；**`status == "failed"` 不报**（失败的实验是被记录下来的合法结果）。

两条边界写进了计划：**单条记录损坏不得让整轮检查崩掉**（报该条 malformed 后继续）；**没有 `started_at` 的 running 记录归 malformed**（宁可报畸形，不要静默跳过）。

## run-log Part B Task 2 执行记录

- 实施者 `Carson` = `01a10152-63a1-7933-a104-ad5912031076`，commit `c45ecea`，**369/369**。判别力检查（删掉 completed+metrics None 那条判定）实测让 `test_completed_without_metrics_is_a_problem` 失败，随后恢复。
- 评审者 `Faraday` = `01a10155-1a93-7a00-9ed2-acd2fb76e952`：首轮 **Needs fixes**（1 Important），其余全部核实通过——判定表逐行落实、`status`/`metrics` 正交未被破坏（E16 遵守）、`failed` 记录只跳过指标分支而 git 检查仍在跑（与表中"`run-log-missing-commit` 无状态限定"一致）、`>` 与"older than"语义相符、只读字节比对有效。

### Ruling E17 — 一条坏记录不得打断整轮（评审发现，必改，含同族一条）

**Important**：`check_runs` 的 `except` 只捕获 `(OSError, json.JSONDecodeError)`，而 `UnicodeDecodeError` 是 `ValueError`、不是 `OSError`——**一条非 UTF-8 的记录会冲出循环，让整轮检查崩掉**，直接违反计划里写明的"单条损坏不得打断整轮"。

控制器同时判定一条同族问题：`log_metrics` 在记录解析成非对象（如 `[]`）时抛未捕获 `TypeError` → traceback + shell 退出 1，而非工具错误 2。这与 latex-check R26a、final-check P9/P11、provenance E5/E8 是同一条规则的第五、六次出现。

Ruling: 两处一并修——`check_runs` 的 `except` 扩到含 `UnicodeDecodeError`；`log_metrics` 在解析后要求是对象，否则 `ValueError`（且在**任何变更之前**判定，保证坏文件字节不变）。
理由: "一条坏记录不得让整份审计失效"是这一层存在的意义之一；而工具自身崩成 1 是本项目已立过五次的规则。
代价: 无。

- 修复 commit `1f37de1`，**371/371**（369 + 2）。定向复审（`Faraday`）：**两条均 ADDRESSED，无新 issue，fix accepted**。评审者核实：新用例用的是**真正的非法 UTF-8 字节**（`b"\xff\xfe\x00garbage"`）而非仅畸形 JSON，且好记录仍被扫描到；`isinstance(record, dict)` 判定发生在赋值与落盘**之前**，坏文件字节不变；退出码契约与冻结的判定表均未改动。
  Task 2: complete (commits 3a37f37..1f37de1, review clean)

- Task 2: minor (deferred)：注入 naive 的 `now` 会因时区相减抛 `TypeError`（测试都用 aware，属 API 硬化）；`completed` 且 `metrics` 为**非对象非空**（如列表）时两个判定都不命中，静默通过——这是判定表的空缺而非崩溃，需要一次裁定；无 `exit_code`/其他字段在 `log_metrics` 后保持不变的直接断言。

## 当前状态

- HEAD = `1f37de1`，工作树干净，**371 tests OK**。
- run-log 已完成：耐久记录与包裹执行（Task 1）、指标登记与只读检查（Task 2）。
- 剩余：run-log Task 3（e2e，终态 375）→ 复现与归档 → 知识层 → 自动化与跨模型评审 → 模板库与派生流程。

## run-log Task 3 与最终全分支评审

- Task 3（e2e）: implementer `Rawls` = `01a10159-4a45-78e2-bd33-076ee070f240`，commit `61ad9d3`，**375/375**。
- 评审者 `Ampere` = `01a1015b-120f-73f0-b5f4-5205f76d057d`：Spec ✅，Approved。四条 e2e 断言均有判别力；"跑完没记指标"的陷阱**在 CLI 路径上被真正触发并证明可清除**（case 1 报 pending，case 2 记完指标后 check 归零）；被包裹命令用 `sys.executable` 不依赖 PATH；顶层参数位置正确；子进程按 UTF-8 解码。
- 评审者的规划注记：计划里 Step 2 写"369 + 4"、验收写"354 + 19 = 373"，而 E16/E17 两轮修复把基线推到了 371——**又是我的算术滞后于修复轮**（同 C6/R4/R24 一族）。代码本身按 371 + 4 = 375 是对的。

### 最终全分支评审（`Feynman` = `01a1015c-948b-7512-8737-652a9a8a03d9`）：Verdict = Needs fixes

§9.2 与 §6.1.1 逐条核实**基本满足**：命令启动前落 running 记录、失败路径（非零退出与 `OSError`→exit_code 127）都保留记录、无重试路径因而"不得静默重试到成功"成立；原子写与不覆盖成立；`check` 只读成立。

### Ruling E18 — 配置里的日期让 `run` 崩成退出 1 并留下 `{}` 占位（Critical，评审者真机复现，必改）

`yaml.safe_load` 把 `date: 2026-10-03` 解析成 `datetime.date`，而 `_dump_record` 用裸 `json.dumps` → **TypeError: Object of type date is not JSON serializable**。`main` 只捕 `(ValueError, ToolEnvironmentError)`，于是 traceback 逃逸、进程退 **1**（契约要求 2）、stdout 为空，且 `new_run_id` 的 `{}` 占位文件留在盘上——§9.2 的"失败必须留档"在一半程度上被破坏。

Ruling: 在 `read_config` 里把 `content` 规范化为 JSON 安全的基本类型（日期/时间转 ISO 字符串，其余不可序列化的转其字符串形式）；补一条带日期配置的回归用例，断言 `run` 正常落记录而非崩溃。
理由: 配置里写日期是最普通不过的事，这条路径任何真实用户都会撞上；而且它同时踩中两条已固化的跨工具规则（工具不能崩成 1、失败必须留档）。
代价: 非标量类型会被字符串化，记录里的 `content` 不再是 YAML 原样对象——但保住"可读、可复现"，比保住类型保真重要。

### Ruling E19 — `run` 的 stdout 必须是 JSON（Important，必改）

`print(run_id)` 与 §6.1.1 的"机器可读 JSON 走 stdout"冲突，也与同工具的 `log-metrics` / `check` 不一致。评审者把它从"未规定的设计选择"提为契约偏离。

Ruling: 改为输出 `{"run_id": ..., "status": ..., "exit_code": ...}` 形状的 JSON；人读摘要仍走 stderr（这正是参考实现"summary 同时打两路"的意图，只是按我们的契约拆分）。
代价: 既有"把 run id 打到 stdout"的直觉用法要改为解析 JSON；e2e 用例需相应调整。

### Ruling E20 — `check` 必须校验 `status` 枚举（Important，必改）

`check_runs` 只对 `running` 与 `completed` 分支，**任何其它 `status` 值都静默落到 git 检查上**——包括手写的 `"complete"` 与 E16 里作废的 `"metrics-pending"`。冻结形状写着 `status ∈ {running, completed, failed}`，未知值就是畸形，应当报出而不是静默接受。

Ruling: 未知 `status` 报 `run-log-malformed`；补一条用例（手写 `"metrics-pending"` 的记录必须被报出而非静默通过）。
理由: 这正是"静默通过"——这一层存在的理由所要防的事；而且它恰好会放过 E16 作废的那个值，等于把已被否决的设计从后门放回来。
代价: 无。

### 其余 deferred minor（评审判定可 defer）

`completed` 且 `metrics` 为**非对象非空**（如列表）时两个判定都不命中、静默通过——评审者同意不阻塞，但建议顺手加一句 `isinstance(metrics, dict)` 守卫（**控制器意见：这条与 E20 同族，应在同一轮修掉**）；注入 naive `now` 抛 `TypeError`（仅测试注入缝，无 CLI 开关）；`main` 的退出码 2 路径缺 `main` 级用例；记录里没有区分 §9.2 的"环境问题（可重试）"与"结果问题（必须记录）"（冻结形状从未包含该字段）；§10 未规定 `--config` 的规范位置；固定临时文件名的并发问题（继承自 provenance，属误用场景）。

## 当前状态与下一步

- HEAD = `61ad9d3`，工作树干净，**375 tests OK**。
- **待执行一轮修复波（E18 + E19 + E20，另建议带上 metrics 非对象守卫）**：全部在 `tools/ccfa/run_log.py` 与其测试内；按 skill 要求一个修复者处理全部发现，随后一次定向复审。
- 之后：run-log 结项 → 复现与归档 → 知识层 → 自动化与跨模型评审 → 模板库与派生流程（强制前置：先评估 `bensz-paper` / `bensz-nsfc`）。

## 修复波（E18–E20）与定向复审

- 修复者 `Socrates` = `01a10160-8b80-7252-bd51-94336e1a4c60`，commit `033e1c9`，**379/379**（修复前实测 2 failures + 4 errors）。
- 定向复审（`Feynman`）：**E18 / E20 / metrics 守卫均 ADDRESSED，E19 按指令范围也算 ADDRESSED，但新增一条 Important**。逐条证据：`_json_safe` 递归处理 dict/list/tuple、把 `datetime`/`date`/`time` 经 `isoformat()` 转换，其余原生类型原样返回；未知 `status` 在 running/completed 分支之前短路为 `run-log-malformed`；completed + 非对象非空 `metrics` 也归 malformed；E11 的 `--propagate-exit` 行为未变。

### Ruling E21 — `run` 不得夺走被包裹命令的 stdout（Important，必改）

为实现 E19（`run` 输出 JSON），实施者把**被包裹命令的 stdout 重定向到 stderr**。评审者当场实测：子进程打印 `7` 到 stdout、`8` 到 stderr，结果 stdout 只有 `{"exit_code":0,...}`，而 stderr 里是 `8\n7\n…`——两路被合并。

后果是包装器的**核心用途被破坏**：`run-log run -- python train.py > out.txt` 再也捕获不到训练输出；而 stdout/stderr 合并毁掉了研究者依赖的"结果 vs 日志"分离。评审者指出"把 JSON 打在子进程输出之后"也不可行——同一个 fd 上既 passthrough 又可解析是做不到的。

Ruling: **让子进程原样继承两路流**（不重定向），把本工具的控制信息（run_id / status / exit_code 的摘要）打到 **stderr**；并把这记为 `run` 这一个 passthrough 子命令对 §6.1.1 "JSON 走 stdout" 的**具名例外**，在 spec §6.1.1 里写明。
理由: `run` 的本质是包装器，它的第一职责是让被包裹的命令像没被包装一样工作；把子命令的输出挪走，等于为了工具的契约便利牺牲用户的主要用途。`check` 与 `log-metrics` 仍走 JSON stdout，机器可读契约在检查侧完好。
代价: `run` 的机器可读输出移到 stderr（与"人读摘要走 stderr"有混用），需要 spec 里具名说明；若将来有人想脚本化 `run`，应使用 `--propagate-exit` + 解析 stderr 或另加 `--json-file`。

## 当前状态与下一步

- HEAD = `033e1c9`，工作树干净，**379 tests OK**。E18/E20/metrics 守卫已清；**E21 待修**。
- 下一步：一轮修复波处理 E21（改造 `run` 的流处理 + 调整 e2e 用例 + 在 spec §6.1.1 写明具名例外），随后一次定向复审；两者通过后 run-log 即可结项。
- 之后：复现与归档 → 知识层 → 自动化与跨模型评审 → 模板库与派生流程。

## E21 修复与 run-log 结项

- 修复者 `Einstein` = `01a10165-6990-7191-b246-4540f0b3214b`，commit `2440356`，**379/379**。E21 回归（子进程标记必须到达调用方 stdout）改前失败、改后通过。
- 定向复审（`Feynman`）：**E21 ADDRESSED，无回归，fix accepted**。评审者核实：`_subprocess_runner` 现在 `subprocess.run(list(argv), cwd=..., check=False)`，**两路流都不重定向**，子进程原样继承；`run` 自身只往 stderr 打摘要；E18（日期配置）、E20（status 枚举）、metrics 守卫、E11（`--propagate-exit`）全部未回归；spec §6.1.1 第 251 行已写入**只覆盖 `run`** 的具名例外，`check`/`log-metrics` 仍走 JSON stdout；run_id 的恢复用正则在整个 stderr 上搜（`\b\d{8}T\d{6}-\d{2}\b`），因此不受子进程自身 stderr 输出干扰。
- 新增 minor (deferred)：`run` 的 run_id 只能从中文人读摘要里正则提取，没有结构化通道（确定性且有用例钉住，不阻塞）。

## run-log 结项

- **五个 commit 全部落地**：`f5f2126`（耐久记录与包裹）、`3a37f37`（相对配置路径按 paper_root 解析）、`c45ecea`（log-metrics + check）、`1f37de1`（非 UTF-8 记录不打断整轮 / 非对象记录归工具错误）、`61ad9d3`（e2e）、`033e1c9`（E18–E20）、`2440356`（E21）。
- HEAD = `2440356`，工作树干净，**379 tests OK**。
- 工具形态：`run`（包装器，命令启动前落 running 记录、O_EXCL 占位、E11 退出码例外、两路流原样透传）、`log-metrics`（只改 metrics，status 与 exit_code 不动）、`check`（只读判定表 + `run-log-malformed` 兜住一切畸形记录）。
- **"忘了 log-metrics"的陷阱已在 CLI 路径上被关闭并有用例证明可清除**——这正是参考实现文档里自己承认的那个"每次运行都记成空指标且不报错"。

## 全局进度

六个工具全部成形并各自过审：`citation_guard` / `trace_claims` / `latex_check` / `final_check` / `provenance` / `run_log`。测试从最初的 125 增至 **379**。

## 下一步

按 spec §6.1：「复现与归档」计划（含 E4 推迟的 `research-version`，走 git 薄封装）→ 知识层（FTS5 + 记忆，含反重复）→ 自动化与跨模型评审 → 模板库与派生流程（强制前置：先评估 `bensz-paper` / `bensz-nsfc` 的复用可行性）。

### 已固化的跨工具规则（新工具照办，不必逐次论证）

1. 写盘路径的 `OSError` → `ValueError` → 退出码 2；
2. store / 记录的 `version` 与枚举字段必须校验；
3. **"有测试"不等于"有判别力"**——每条判别力检查必须实测其能在错误实现下失败；
4. **闸门没跑全不能报成功**（含跳过项的一轮退出码为 2）；
5. **一条坏记录不得打断整轮审计**；
6. **包装器不得夺走被包裹命令的流**——工具的契约便利不能牺牲用户的主要用途。

## 「复现与归档」层预研（参考实现主体已深读）

参考：`research-suite/tools/repro-package/repro_package.py` 与 `friction-log/friction_log.py`（MIT）。

### 参考实现里值得吸收的两点

1. **`repro_package` 把"干净环境"的范围写在文档第一段**：它明说自己指的是"一个只装了 bundle 声明依赖的新 venv"，**不是**容器级隔离（不隔离系统库、网络、PATH 上已有的非 Python 工具），并且写明"这是一份诚实、可实现的保证，不是对完全隔离的宣称"。这种"先说清保证的边界"正是本工作流的风格。
2. **`friction_log` 的 `aggregate`**：以 `PATH=LABEL` 接收多个 store 并合并，其文档给的理由是"跨若干不相关领域重复出现的模式，才能被聚合真正浮出来，而不是埋在各个没人会一起重读的文件里"。这正是 spec §6.1 要的"跨论文聚合"。

### 参考实现里必须偏离的一点

`repro_package` 在 `verify` 时**通过 shell 执行 bundle 的命令**，并在文档里加了"只对你信任的命令构建与验证 bundle"的警告。我们已经有 `run-log` 的 argv 包装先例，没有必要引入 shell 注入面。

## 裁定（E22–E26）

### Ruling E22 — repro-package 的"干净环境"必须诚实定义范围

Ruling: 采纳参考实现的诚实口径并写进 spec 与工具输出——"干净环境"= 一个只装 bundle 声明依赖的**新 venv**，不含容器级隔离。报告里必须显式说明这次验证覆盖了什么、没覆盖什么。
理由: 把"我看了一遍包"说成"我验证了可复现"是本层最容易犯的谎；先把保证边界写死，才谈得上后面的判定。
代价: 用户可能误以为它比实际更强——所以这条必须出现在 `--help` 与每次 verify 的输出里，而不只是文档里。

### Ruling E23 — 命令用 argv 数组，不用 shell 字符串

Ruling: `repro-package` 的命令以 **argv 数组**表达（与 `run-log` 一致），`{python}` 占位符在 verify 时替换为新 venv 的解释器（作为 `argv[0]`）。需要管道/重定向的场景必须写成一个脚本文件，不引入 shell。
理由: 参考实现的 shell 路径既需要"只信自己的命令"这类免责声明，又把注入面带进一个本该只读的执行环境。argv 让这一类风险不存在，且与既有包装器一致。
代价: 依赖 shell 特性的复现命令需要多写一个脚本文件；这是有意的摩擦。

### Ruling E24 — verify 必须真的重跑，并区分三类失败

| 情形 | code / 退出码 |
| --- | --- |
| bundle 清单与实际文件不符（缺文件、哈希对不上） | problem `repro-bundle-incomplete`（退 1） |
| 重跑本身非零退出 | problem `repro-rerun-failed`（退 1） |
| 环境无法建立（找不到解释器、建 venv 失败、超时） | **工具错误（退 2）** |

Ruling: 第三类必须与第一二类分开。**"环境没建起来"不是"这个包复现不了"**——把两者混为一谈，等于让"验证没跑成"看起来像"验证发现问题"（本项目已固化规则的又一次应用）。
代价: 用户需要分别处理"包的问题"与"机器的问题"；这正是要的区分。

### Ruling E25 — friction-log 沿用既有 store 契约

Ruling: store 为 JSON（带 `version`）；`category` 限 `tool-bug` / `skill-gap` / `environment` / `other`，`severity` 限 `low` / `medium` / `high`；**读取时重新校验枚举**（E20 的教训：写入时校验不构成读取时的信任）；`aggregate` 以 `PATH=LABEL` 合并多个 store，输出**不覆盖**已存在文件，除非 `--force`；原子写。
理由: 这些都是已固化的跨工具规则，新工具照办。
代价: 每篇论文一个 store + 一个聚合命令，需要用户记得在阶段收尾时聚合；写到 spec 的 gate 描述里。

### Ruling E26 — research-version 落实为 git 薄封装（E4 的细则）

Ruling:
- `list` = `git tag -l "paper-v*"`；
- `snapshot [--label L] [--allow-dirty]` = 打一个带注释的标签 `paper-v<N>`（N 自增），标签消息写入当时的 commit 与 `dirty` 标志；
- **脏树默认拒绝**（退 2），`--allow-dirty` 时才允许并在标签消息里记 `dirty=true`——因为脏树快照无法被 commit 复现；
- `diff <a> <b>` = `git diff <a> <b> -- <paths>`（真实 diff，不另存副本）。
理由（E4 的延续）: 论文库已是 git 仓库，独立版本库会制造"两个版本真相"。薄封装保留"任意两版真 diff"的能力，同时让"第几版"只有一个答案。
代价: 依赖 git 可用；非 git 环境下 `research-version` 不可用（这是有意的——离开版本控制谈快照本就没有意义）。

## 计划轮廓（待写）

1. `tools/ccfa/repro_package.py` — bundle（清单 + 哈希 + 声明依赖）与 verify（建新 venv、按 argv 重跑、三类失败分流）
2. `tools/ccfa/friction_log.py` — add / list / export / aggregate（store 契约 + 枚举重校验 + 不覆盖聚合输出）
3. `tools/ccfa/research_version.py` — list / snapshot / diff（git 薄封装，脏树默认拒绝）
4. 端到端回归：必须含"bundle 缺文件 → 1""重跑失败 → 1""环境建不起来 → 2""脏树 snapshot 被拒 → 2"四条判别性用例

## repro-package Part A 计划已写

- 计划文件：`<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-repro-package.md`
- Task 1（bundle 构建与清单）：含完整实现与测试代码，终态 **393**（379 + 14）。
- 计划里落实的裁定：**E22**（"干净环境"的范围要在 `--help` 与每次 verify 输出里说清——Part B）、**E23**（命令用 argv 数组，`{python}` 占位；`--command` 用 `shlex.split` 切分而**不是 shell 执行**）、**E6 规则**（清单 `version` 必须校验）、**路径规则**（绝对路径与 `..` 逃逸一律拒绝）、**写盘契约**（原子写、不覆盖、`--force` 才重建）。
- 自审修掉两处：测试条数又数错（14 不是 15，终态 393 不是 394）；Step 4 的判别力检查我写成自我矛盾的一段（先说必须通过、又说必须失败）——已改成一条清晰的检查（把 `shutil.copy2` 换成写空文件后，存在性用例仍过、哈希用例必须失败），并把"若它没失败该怎么办"的判断交给实施者。
- **这条判别力检查本身值得留意**：它测的是"复制有没有真的把字节带过去"，而存在性断言抓不到这件事——这正是本项目反复强调的"有测试不等于有判别力"的一个新实例。

## repro-package Task 1 执行记录

- 实施者 `Huygens` = `01a1016c-2233-7130-b519-c0a6cddfac83`，commit `a34e741`，**393/393**。
  两点值得记：(a) 判别力检查**恰好按设计分化**——把 `shutil.copy2` 换成写空文件后，存在性用例仍过、哈希用例失败，无需加强，说明计划里重写的那条检查是站得住的；(b) 它在自查时发现了一个数据丢失隐患并"修复"了：`--force` 原本先 `rmtree` 再校验清单。
- 评审者 `Euler` = `01a1016f-0cce-79c3-8554-10e1a1185d2a`：**Spec ❌，Needs fixes（1 Critical）**。

### Ruling E27 — `--force` 的删除必须晚于**全部**校验（评审发现，Critical，必改）

评审者指出并**复现**：实施者的自查修复是**不完整**的——它只把**形状**校验（`version`、`files` 是列表、`path` 是字符串）移到了 `rmtree` 之前，而**路径包含性与文件存在性**校验（`_resolve_member`）仍在删除**之后**执行。实测：建好一个有效 bundle → 加一个 `KEEP` 文件 → 篡改清单条目为 `"src/gone.py"` → `create_bundle(..., force=True)` → 抛 `ValueError`，但 `KEEP` **已被删除**。

这条直接推翻了实施者报告里"清单在任何意义上无效时都不会删除已存在目录"的声称。CLI 正常流程之所以没暴露，只是因为 `main` 里恰好先跑了 `build_manifest`；库函数 `create_bundle`、以及"构建与复制之间文件被删"的时序窗口，都没有被保护。

Ruling: 在**任何**破坏性操作之前，把全部成员的 `(相对路径, 源路径)` 解析完（含 `requirements`），把路径包含性与存在性一次验完；之后再删除、再复制。并补一条用例把"`--force` + 路径无效不得破坏已有 bundle"钉死。
理由: 这是数据丢失路径，而本工具的本职正是保存可复现产物——一个在报错前先毁掉旧产物的实现，方向与它的存在意义相反。另外，实施者"我已修好"的声称被证明只覆盖了一半，这本身说明**自查结论必须由独立评审核实**，不能当作证据。
代价: 无；校验顺序调整而已。

## 当前状态与下一步

- HEAD = `a34e741`，工作树干净，**393 tests OK**。
- **待执行一轮修复波（E27）**：`create_bundle` 把全部解析与校验提到删除之前；补一条 `--force` + 路径无效的回归用例。
- 之后：repro-package Part B（verify：建新 venv、按 argv 重跑、三类失败分流 E24）→ friction-log → research-version（E26 的 git 薄封装）→ 知识层 → 自动化与跨模型评审 → 模板库与派生流程。

## E27 修复与 repro-package Task 1 结项

- 修复者 `Godel` = `01a10171-2b73-7d71-92da-aae77b8e48f0`，commit `9b6b0e2`，**394/394**。新回归用例 RED→GREEN 实测（旧顺序下 `KEEP` 标记会消失）。实施者在报告里如实写明："先前的自查安全声称被夸大了，实际只覆盖了形状校验"——这句比修好的代码更值钱。
- 定向复审（`Euler`）：**ADDRESSED，无新 issue，fix accepted**。评审者核实：`_resolve_member` 现在把**全部** `files` 条目与 `requirements` 解析成 `members` 列表（`repro_package.py:118-126`）之后才 `rmtree`（`:128-133`），复制循环消费的是已解析对（`:137-140`），删除之后不再有任何路径校验；有效路径的布局与清单字节未变；既有 `ValueError` 路径不变；唯一的行为位移是"非 force + 目录已存在 + 路径无效"现在先报路径错误——仍是 `ValueError` / 退出 2。
  Task 1: complete (commits 2440356..9b6b0e2, review clean)

### 这一轮暴露的流程教训（值得单独记）

实施者自查时"发现并修复了一个数据丢失隐患"，报告里写成"清单在任何意义上无效时都不会删除已存在目录"——但评审者复现证明它只覆盖了形状校验，路径与存在性校验仍在删除之后。**一个被夸大的安全声称，比没有声称更危险**：它会让人停止检查。

由此补一条操作惯例（不新增工具规则，只记流程）：**凡自查里声称"已堵住某类危险"的，必须给出能证明它的失败用例；没有失败用例的安全声称，视为未验证。**

## 当前状态

- HEAD = `9b6b0e2`，工作树干净，**394 tests OK**。
- repro-package 的打包侧完成；剩 verify（Part B）→ friction-log → research-version → 知识层 → 自动化 → 模板库。
- 账本裁定 E1–E27。

## repro-package Part B 计划已写

- 计划文件：`<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-repro-package-part-b.md`
- Task 2（`verify`）：判定表 + 三个可注入点（`venv_factory` / `runner` / `timeout`），7 条测试；Task 3（e2e + 一次真实 venv 冒烟），4 条测试。终态依次 **401 / 405**。
- 计划落实的裁定：
  - **E24**：三类失败分流——bundle 哈希不符 → 1；依赖装不上 / 重跑非零 / 超时 → 1；**清单非法或建 venv 失败 → 2**（"环境建不起来"是机器的问题，不是包的问题）；
  - **E22**：`repro-scope` advisory 固定文案，**无论通过与否**都出现在报告里，写明本次"干净环境"覆盖了什么、没覆盖什么；
  - **E23**：`{python}` 只替换 `argv[0]`，绝不经过 shell。
- 自审收紧一处：**哈希核对失败时不执行命令**。跑一个已损坏的包正是本工具要拦下的事；但仍要把全部哈希问题一次报全（逐条比完再决定，不是遇到第一条就返回），且 `repro-scope` 仍出现，说明本次验证停在哪一步。
- 另一处刻意的取舍写进了边界：`pip install` 失败不区分"依赖无法解析"与"无网络"，都归 `repro-install-failed` 并在 detail 里附原始输出供人判断——因为工具**分不出来**，假装分得出来才是错的。

## 当前状态

- HEAD = `9b6b0e2`，工作树干净，**394 tests OK**。
- repro-package 打包侧完成；verify 计划就绪待执行。之后：friction-log → research-version → 知识层 → 自动化 → 模板库。
- 账本裁定 E1–E27 + 一条流程惯例（无失败用例的安全声称视为未验证）。

## repro-package Part B Task 2 执行记录

- 实施者 `Erdos` = `01a10175-7e0f-78d0-a40b-e520f41c62b2`，commit `5c3c33a`，**401/401**。判别力检查（删掉哈希核对步）实测让 `test_tampered_file_is_reported_as_incomplete` 以 `[] != ['repro-bundle-incomplete']` 失败，随后恢复。额外做了两件对的事：把 `requirements` 的哈希也纳入核对（安装消费的正是那份字节），以及按规则把 `repro-scope` 写成中文（面向用户）。
- 评审者 `Laplace` = `01a10179-8bd9-7ea1-97ea-dc0e91dcbd49`：**Approved，无 Critical，1 Important + 若干 Minor**。核实：E24 三类分流正确；E23 只替换 `argv[0]`、`shell=False`、命令里后出现的 `{python}` 原样保留（正确）；哈希失败时**确实**在建立 venv 与执行之前返回，且逐条报全；`verify` 不写 bundle；临时 venv 在 `finally` 里清理，`--keep` 才保留。

### Ruling E28 — 安装失败时不得把"重跑失败"当主因（Important，必改；根因在我的测试设计）

评审者指出：安装失败而重跑也失败时，代码只返回 `repro-rerun-failed`，把安装失败塞进消息末尾（"；依赖安装也未成功"）。**依赖缺失导致的重跑失败是症状**；机器消费者只看到"重跑失败"，人得读自由文本才能找到病因。

更要紧的是评审者点出的**根因**：我的 brief 只注入了**一个 `runner`**，同时用于 pip install 与重跑——于是测试**分不清**这两次调用，实现也就无法区分，只能把症状当主因。**这是计划层面的测试设计缺陷，不是实施者的判断问题。**

Ruling:
1. **行为**：安装失败时**不进行重跑**，直接以 `repro-install-failed` 为主因返回（detail 附 pip 输出尾部，并注明"未继续重跑"）。安装成功才重跑。
2. **测试**：把注入点改成能区分两次调用——保留一个 `runner`，但测试按其 argv 是否含 `pip` 分派；或新增 `install_runner` 与 `run_runner` 两个注入点。必须新增一条"仅安装失败"的用例（安装失败、命令本可成功 → 只报 `repro-install-failed`）。
理由: 一次验证的价值在于指向病因；把症状当主因报出，等于让用户去修错的东西。而"测试分不清两次调用"这件事本身再次印证那条惯例——**测试的判别力决定了实现对错误的可见度**。
代价: 注入点从 1 个变 2 个（或测试内加分派）；既有两条用例需相应改造。

### 其余 deferred minor（评审判定可 defer）

`repro-scope` 在**工具错误**路径（清单非法 / 建 venv 失败）不出现——与 E22 的"无条件"措辞有一处小缺口（实际影响有限，因为那时没有产生验证结果）；无"仅安装失败""`requirements` 被篡改""哈希失败不建 venv""`--keep` 清理"的用例；只读测试只钉了 `MANIFEST.json`，抓不到 `files/` 成员被改或新增文件；`_bundle_member` 的 `Path.resolve()` 在 `OSError → ValueError` 包装之外，极端情况下会逃成 traceback；"固定文案"是中文改写而非英文原文（符合"中文只在面向用户消息"的规则，但与计划措辞不一致）。

## 当前状态与下一步

- HEAD = `5c3c33a`，工作树干净，**401 tests OK**。
- **待执行一轮修复波（E28）**：安装失败即止、以安装失败为主因；把注入点做成可区分；补"仅安装失败"用例。随后一次定向复审。
- 之后：Task 3（e2e + 真实 venv 冒烟，终态 405）→ friction-log → research-version → 知识层 → 自动化 → 模板库。
- 账本裁定 E1–E28。

## repro-package 最终全分支评审

- 评审者 `Turing` = `01a10185-8f18-74b0-aabc-85e42ddea734`, `deepseek-v4-pro`（最高档）。Diff: `.superpowers/sdd/2026-10-03-repro-package-part-b/review-2440356..7258d0d.diff`（5 commits）。
- **Verdict: Merge readiness = Ready**，无 Critical。§6.1 与 §12 的相关条款均核实满足；1-vs-2 分流全程成立；E27（删除晚于全部校验）与 E28（安装失败即止）经代码核验确已落地；真实 venv 冒烟被认可为端到端证据。
- 评审者还做了一次"真实论文布局走查"，指出四个会绊住用户的地方：`requirements.txt` 里的 `-e .` 或相对引用（只复制了点名文件、安装 cwd 在 bundle 内，因此装不上）；命令参数里的 Windows 绝对路径被 `shlex(posix=True)` 弄坏；**命令省略 `{python}`（跑错解释器）**；命令写相对输出（弄脏 bundle）。

### Ruling E29 — `{python}` 必须校验，不得让工具做不实声明（Important，控制器提为阻塞级）

评审者把它列为 Important 但判"可作后续修"。控制器**不接受"后续"**：`build_manifest` 不校验命令首元素，`verify` 只在 `argv[0] == "{python}"` 时替换——于是用 `--command "python train.py"` 构建的 bundle 会**用系统 PATH 上的 python 重跑**，而 `repro-scope` 那条 advisory 仍然宣称"命令在包含 bundle 声明依赖的新建 venv 中运行"。

这是**工具在自己的输出里做不实声明**。本层存在的全部价值就是"诚实证据"（E22 特意把隔离边界写死，就是为了不夸大）。一条与事实不符的证据声明，比没有声明更危险——它会让人停止怀疑。

Ruling:
1. **`bundle` 拒绝**首元素不是 `{python}` 的命令（`ValueError` → 2），并在错误消息里说明原因（否则该 bundle 无法被诚实验证）；
2. **`verify` 同样拒绝**命令首元素不是 `{python}` 的清单（防手工构造的清单绕过第 1 条）；
3. 补两条用例，分别钉住这两处拒绝。
理由: 与"闸门没跑全不能报成功"同源——**报告不得声称自己没做到的事**。
代价: 命令首元素被强制为 `{python}`；非 Python 命令（编译好的二进制等）不能进 bundle，这与"本工具只验证 Python 侧复现"的边界一致（计划已声明）。

### Ruling E30 — 重跑必须在 `files/` 的临时副本里进行（Important，一并修）

`verify` 把重跑的 cwd 设为 `<bundle>/files`，因此**一条会写相对输出的命令会弄脏 bundle**——"只读 bundle"这条不变量只是有条件的。评审者指出只读测试只钉了 `MANIFEST.json`，抓不到这件事。

Ruling: 建 venv 之前把 `<bundle>/files` 整棵复制到临时目录，在副本里重跑；bundle 全程零写入，不变量变成无条件的。只读测试改成对**整个 bundle 目录**做前后比对（文件清单 + 每个文件的哈希）。
代价: 每次 verify 多一次文件复制（对 bundle 规模而言可接受）。

### Ruling E31 — 成功的重跑输出必须留下痕迹（Important，一并修）

非零退出时输出尾部被保留在 Problem 消息里，成功时却被直接丢弃。**证据是本层的产物**：一条跑了 20 分钟的命令，用户只拿到退出码 0 与空 problems，等于没有任何关于"它到底跑了什么"的记录。

Ruling: 成功时把输出尾部（末 800 字符）打到 **stderr**（人读通道），JSON 契约不动；同时把它作为一条 advisory（code `repro-output-tail`）放进 JSON，便于机器侧留存。
代价: 长输出会在 stderr 上多一段；用尾部截断控制体量。

## 当前状态与下一步

- HEAD = `7258d0d`，工作树干净，**406 tests OK**。
- **待执行一轮修复波（E29 + E30 + E31，三条都是控制器提为阻塞级）**：全部在 `tools/ccfa/repro_package.py` 与其测试内；按 skill 要求一个修复者处理全部发现，随后一次定向复审。预计新增 3–5 条用例。
- 之后：`friction-log` → `research-version`（E26 的 git 薄封装）→ 知识层 → 自动化与跨模型评审 → 模板库与派生流程。
- 账本裁定 E1–E31。

## E29–E31 修复与 repro-package 结项

- 修复者 `Kuhn` = `01a1018a-19fd-76d1-8239-96d25738912c`，commit `e2783b6`，**411/411**。
- 定向复审（新派 `Nash` = `01a1018c-88cf-7103-b7d5-f084417b7948`，因原评审者已关闭）：**E29 / E30 / E31 全部 ADDRESSED，无回归，fix accepted**。三处证据：
  1. **E29**：`build_manifest` 在 `command[0] != "{python}"` 时拒绝并解释理由（"无法诚实地在新 venv 中重跑"）；`_validate_manifest` 镜像同一检查，且 `verify_bundle` **在最开头**就调用它——因此手工构造的 `["python", "x.py"]` 在替换之前就抛 `ValueError` → 2。两个方向都堵住了。
  2. **E30**：`shutil.copytree(files_dir, run_files_dir)` 把 `files/` 复制进临时目录，安装与重跑都以副本为 cwd；只读测试改为对**整个 bundle** 做"相对路径 + 每文件哈希"的前后快照，且用例里的 `writer.py` 会真的往 cwd 写文件——**旧实现下必然失败**。
  3. **E31**：成功时追加 `repro-output-tail` advisory；`emit` 本就往 stderr 打 advisory，因此标记到达 stderr 而非新增 stdout 行；原先"只有 `repro-scope`"的断言被**更新为期望两条**，不是删除。
  无回归：三类退出码分流、安装失败即止、哈希失败即止、`repro-scope` 在所有非工具错误路径、`shell=False`、原子写、`--keep` 清理均保持。
  repro-package: complete (commits 2440356..e2783b6, review clean)

## repro-package 结项

- **7 个 commit 全部落地**：`a34e741`（bundle + 清单）、`9b6b0e2`（E27：删除晚于全部校验）、`5c3c33a`（verify）、`c9646e2`（E28：安装失败即止）、`7258d0d`（e2e + 真实 venv 冒烟）、`e2783b6`（E29–E31）。
- HEAD = `e2783b6`，工作树干净，**411 tests OK**。
- 工具形态：`bundle`（文件 + 哈希清单 + argv 命令 + `{python}` 强制 + 清单版本校验 + 原子写 + 不覆盖 + 删除晚于全部校验）、`verify`（哈希全检 → 在新 venv 副本里重跑 → 三类失败分流 → `repro-scope` 恒在 → 成功也留输出尾部）。
- **真实 venv 冒烟通过**：真建出 stdlib venv 并离线跑通 `{python} hello.py`——这是注入式单测给不了的硬证据（与 latex-check 用真 MiKTeX、final-check 用真 PDF 同类）。

## 全局进度

七个工具成形：`citation_guard` / `trace_claims` / `latex_check` / `final_check` / `provenance` / `run_log` / `repro_package`。测试从 125 增至 **411**；账本裁定 E1–E31。

## 下一步

- `friction-log`（store 契约 + 枚举读取时重校验 + `aggregate` 跨论文合并，Ruling E25）
- `research-version`（E26 的 git 薄封装：`paper-v<N>` 标签、脏树默认拒绝）
- 之后：知识层（FTS5 + 记忆）→ 自动化与跨模型评审 → 模板库与派生流程（强制前置：先评估 `bensz-paper` / `bensz-nsfc`）

### 已固化的跨工具规则（新工具照办）

1. 写盘路径的 `OSError` → `ValueError` → 退出码 2；
2. store / 记录的 `version` 与枚举字段必须校验；
3. **"有测试"不等于"有判别力"**——每条判别力检查必须实测其能在错误实现下失败；
4. **闸门没跑全不能报成功**；
5. **一条坏记录不得打断整轮审计**；
6. **包装器不得夺走被包裹命令的流**；
7. **工具不得在自己的输出里做不实声明**（E29）；
8. **无失败用例的安全声称，视为未验证**；注入点必须能让测试区分被测的两条路径（E27/E28 的教训）。

## friction-log 计划已写

- 计划文件：`<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-friction-log.md`
- Task 1（store + `add`/`list`/`check`，12 条测试）→ 终态 423；Task 2（`export`/`aggregate`，8 条测试）→ 终态 431。
- 落实 **E25**：store 的 `version` 校验 + **读取时重校验枚举**（"写入时校验不构成读取时的信任"这条已固化的教训，在 friction-log 是主判定）；`aggregate` 以 `PATH=LABEL` 跨论文合并并给每条打 `source` 标签；聚合输出不覆盖（`--force` 才覆盖）；单条非法**不得打断整轮**（规则 5）。
- 吸收参考实现的核心论点：跨若干不相关领域重复出现的模式才能被聚合浮出来，而不是埋在各自没人重读的文件里。
- 自审补写一处语义（否则评审者必问）：`aggregate` 遇到非法输入条目时**仍然写出合并文件**（合并这件事本身成功），但把坏条目录成 problem，退出码为 **1**。理由是——**记录里的坏条目是事实，不该为了"干净"丢掉它**，丢掉正好违背这一层"让重复模式浮出来"的目的；坏条目原样保留，问题列表指出它们。
- 写计划时踩了一次补丁工具的坑：JSON 示例的续行漏了 `+` 前缀导致整块补丁被拒，改成单行示意后通过。记下来免得重复。

## 当前状态

- HEAD = `e2783b6`，工作树干净，**411 tests OK**。
- 七个工具成形（引用 / 数字 / 结构编译 / 终稿 / 来源 / 运行记录 / 复现包）；`friction-log` 计划就绪待执行。
- 之后：`research-version`（E26 的 git 薄封装）→ 知识层 → 自动化与跨模型评审 → 模板库与派生流程。

## E32 修复（friction-log）

- 修复者 `Curie` = `01a1019c-44d2-77e1-8a65-d927b9531275`，commit `3c8039a`，**432/432**。
  改前定向用例以 `0 != 2` 失败（旧行为：拼错的输入路径被当成空 store，退出 0 并写出一个"少了一篇"的合并文件）；改后退出 2、stdout 为空、**且不留下 `--out` 文件**——参数给错不该产生一份半成品的总账。`load_store` 的既有契约（缺文件=空 store）与 `add`/`check`/`list` 行为均未改动，严格规则只加在 `aggregate` 这条显式点名来源的路径上。
- **待办**：一次定向复审（E32），随后 friction-log 的最终全分支评审（base `e2783b6`）。

## 当前状态

- HEAD = `3c8039a`，工作树干净，**432 tests OK**。
- `tools/ccfa/` 27 个模块；八个工具成形或接近成形：引用 / 数字 / 结构编译 / 终稿 / 来源 / 运行记录 / 复现包 / 摩擦日志。
- 剩余路线：`research-version`（E26 的 git 薄封装）→ 知识层（FTS5 + 记忆）→ 自动化与跨模型评审 → 模板库与派生流程（强制前置：先评估 `bensz-paper` / `bensz-nsfc`）。

### 已固化的跨工具规则与流程惯例（共 9 条，新工具照办）

1. 写盘路径的 `OSError` → `ValueError` → 退出码 2；
2. store / 记录的 `version` 与枚举字段必须校验；
3. **"有测试"不等于"有判别力"**——每条判别力检查必须实测其能在错误实现下失败；
4. **闸门没跑全不能报成功**；
5. **一条坏记录不得打断整轮审计**；
6. **包装器不得夺走被包裹命令的流**；
7. **工具不得在自己的输出里做不实声明**；
8. **记录里的坏条目是事实，不得为了"干净"丢弃**；
9. （流程）**无失败用例的安全声称，视为未验证**；注入点必须能让测试区分被测的两条路径；**显式点名来源的操作，源必须存在**（E32）。

## E32 定向复审与 friction-log 结项

- 定向复审（`Galileo` = `01a1019f-0dcd-7f11-88e3-bbdd685a52ec`）：**ADDRESSED，无回归，fix accepted**。核实：`aggregate_stores` 在 `load_store` 之前对每个输入做存在性检查（循环覆盖全部输入）；`aggregate_stores` 在 `write_text_output` **之前**执行，因此缺输入时不留 `--out` 文件；`load_store` 与 `add`/`check`/`list` 分支逐行未动；非法条目仍原样进合并结果、仍以退出码 1 + 已写出文件收场。
- 最终全分支评审（`Goodall` = `01a1019f-b889-7f42-8c1d-6071780fcb14`）：**Merge readiness = Ready**，无 Critical/Important。§6.1 的"记录工具缺陷与指令缺口，跨论文聚合"逐条核实满足。
  **评审者做了一次往返探针（很有价值）**：把两个 store 先聚合一次，再把聚合结果当作输入**二次聚合**，结果通过自己的 `check`，id 为 `[1, 2]`、来源标签在重新标记的层级上保留。它另外确认：`add` 只会产出 `aggregate` 能接受的 v1 形状；有效 store 合并后能通过自身 `check`。
  friction-log: complete (commits e2783b6..3c8039a, review clean)

## friction-log 结项

- **3 个 commit**：`7efd38e`（store + `add`/`list`/`check`，读取时重校验枚举）、`43f1f10`（`export` + 跨论文 `aggregate`）、`3c8039a`（E32：聚合输入必须存在）。
- HEAD = `3c8039a`，工作树干净，**432 tests OK**。
- 工具形态：`add`（先校验后改）、`check`（只读、重校验、报全）、`list`（JSON 筛选）、`export`（不带 `--out` 只打文档）、`aggregate`（`PATH=LABEL` 跨论文合并、坏条目作为事实保留、缺来源即退 2）。

## 全局进度

八个工具成形：`citation_guard` / `trace_claims` / `latex_check` / `final_check` / `provenance` / `run_log` / `repro_package` / `friction_log`。测试从 125 增至 **432**；账本裁定 E1–E32。

## 剩余路线

1. `research-version`（E26 的 git 薄封装：`paper-v<N>` 带注释标签、脏树默认拒绝、`diff` 用 `git diff`）
2. 知识层（FTS5 trigram 索引 + 记忆文件，含反重复的 `reopen_if`）
3. 自动化与跨模型评审（定时任务 + `codex exec` 独立评审接线）
4. **模板库与派生流程**（把整条链串成"一条命令开一篇新论文"；强制前置：先评估 `huangwb8/ChineseResearchLaTeX` 的 `bensz-paper` / `bensz-nsfc` 复用可行性，而不是闭门造模板）

### 已固化的规则与惯例（9 条，新工具照办，不必逐次论证）

写盘 `OSError`→2；store/记录的 `version` 与枚举必须校验；"有测试"不等于"有判别力"（每条判别力检查必须实测其能失败）；闸门没跑全不能报成功；一条坏记录不得打断整轮；包装器不得夺走被包裹命令的流；工具不得在自己的输出里做不实声明；记录里的坏条目是事实不得为"干净"丢弃；显式点名来源的操作源必须存在。另有两条流程惯例：无失败用例的安全声称视为未验证；注入点必须能让测试区分被测的两条路径。

## research-version 计划已写

- 计划文件：`<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-research-version.md`
- Task 1（git 薄封装的 `list`/`snapshot`/`diff`）：11 条注入式用例 + **1 条真实 git 集成用例**，终态 **444**（432 + 12）。
- 落实 **E4/E26**：
  - 标签命名 `paper-v<N>`，**按数值排序**（字符串排序会把 v10 排在 v2 前——这是判别力检查的靶点）；
  - **脏树默认拒绝**（退 2），`--allow-dirty` 时才允许并在 annotated tag 的消息里记 `dirty=true`——脏树快照无法仅凭 commit 复现，这个事实必须留在标签里；
  - `diff` 用真实 `git diff`，路径参数放在 `--` 之后；
  - **本工具不写任何自己的存储**，因此不引入"两个版本真相"。
- 三处需要评审者知道的设计判断：
  1. **`diff` 有差异也退 0**——差异是这个子命令的**产物**，不是问题；`1` 在本项目里保留给"检查发现了问题"。这是与 Unix `diff` 约定不同的具名例外，必须写进 `--help`。
  2. **用 annotated tag 而不是轻量标签**，因为轻量标签没有消息，装不下 `dirty` 与 `label`。
  3. `label` 只进标签消息、**不参与命名**——命名始终是 `paper-v<N>`，保证顺序可数。
- 自审补一条真实使用会撞上的边界：**annotated tag 需要 git 身份**（`user.name`/`user.email`），未配置时 git 报错 → 折成 `ValueError` → 2；并特别写明真实 git 集成用例**必须在临时仓库里自己配好这两项**，否则会因机器全局配置不同而时灵时不灵（"测试依赖全局状态"的典型陷阱）。

## 当前状态

- HEAD = `3c8039a`，工作树干净，**432 tests OK**。
- 八个工具成形；`research-version` 计划就绪待执行。
- 之后：知识层（FTS5 + 记忆）→ 自动化与跨模型评审 → 模板库与派生流程。

## friction-log Task 2 执行记录

- 实施者 `Copernicus` = `01a10197-10e9-7900-885d-93d283b874f7`，commit `43f1f10`，**431/431**。判别力检查（去掉聚合的问题上报）实测只让非法条目那条用例失败、其余全过，随后恢复。brief 同样只有 46 行（枚举清单式规格）。
- 评审者 `Aristotle` = `01a10199-e977-71a1-adc0-4e2f511478f5`：**Spec ✅，Approved，无 Critical/Important**。关键核实：**"坏条目是事实"这条落实正确**——合并文件在 `emit(problems)` **之前**写出，因此退出码 1 时输出文件仍然完整；`source` 标签、`id` 连续重编号、`version: 1` 均正确；三类退出码无混淆；`export` 不带 `--out` 确实一个文件都不写。

### Ruling E32 — `aggregate` 不得让"路径写错"静默吞掉一整篇论文（控制器提为阻塞级）

评审把它列为 Minor：`load_store` 对**不存在的文件**返回空 store，因此 `aggregate PATH=LABEL` 里路径拼错时，那一篇的摩擦条目**一条都不会进总账**，而工具退出 0。评审者的理由是"继承自既有 `load_store` 契约、与 `add` 一致"。

控制器不接受。`aggregate` 存在的全部理由是"让重复模式浮出来"——**静默丢掉一整篇的来源，正好与它的目的相反**；而且它丢的是"摩擦记录"，这类记录本来就最容易没人注意。这与本项目已多次修正的"静默省略"同族（一条坏记录不得让整轮失效 / 记录里的坏条目不得为整洁而丢弃）。

Ruling: `aggregate` 的每个输入路径**必须存在**；不存在则 `ValueError` → 退出 2（工具错误：参数给错了），而不是当成空 store 参与合并。
理由: `add`/`check` 面向"某一篇还没建 store"是合理场景（缺文件=空 store）；但 `aggregate` 是显式点名若干来源的合并操作，**点名的文件必须存在**——否则用户拼错一个字母就静默少一篇。
代价: 需要把"缺文件视为空"这条契约限定在 `add`/`check` 路径上；`aggregate` 走一条更严的读取分支。补一条用例：不存在的 `PATH=LABEL` → 退出 2。

### 其余 deferred minor（评审判定可 defer）

`aggregate` 对每个输入读两遍（`check_store` 一遍、`aggregate_stores` 一遍），两次读之间文件可能变，因此问题报告可能与实际合并的内容不一致（TOCTOU；本地手改日志，风险低，但确实不是单遍）；非 dict 条目原样保留但**不带 `source` 标签、且仍占用一个 id 序号**，混合 store 里 dict 条目的 id 会不连续（如 `[1, 3]`）；`created_at` 为 `None` 时日期列渲染成字面 `"None"`；若干覆盖缺口（`export --out` 无 `--force` 被拒、聚合输入不可读 → 2、markdown 里竖线转义、`workaround` 为 null 的单元格、非 dict 条目）。

## 当前状态与下一步

- HEAD = `43f1f10`，工作树干净，**431 tests OK**。
- **待执行一轮修复波（E32）**：`aggregate` 的输入路径必须存在，否则退出 2；补一条用例。随后跑 friction-log 的最终全分支评审（base `e2783b6`）。
- 之后：`research-version`（E26 的 git 薄封装）→ 知识层 → 自动化与跨模型评审 → 模板库与派生流程。

## friction-log Task 1 执行记录

- 实施者 `Lorentz` = `01a10190-6d56-7142-a72a-b940417f670c`，commit `7efd38e`，**423/423**。判别力检查（删掉 `check_store` 的枚举重校验）实测失败、恢复后通过。
  这轮的 brief 只有 56 行——因为我在计划里把测试写成**枚举清单**而非粘贴代码，派发时明确告知"清单即规格，逐条写成真实用例"。实施者照办，12 条全部落到用例。
- 评审者 `Heisenberg` = `01a10193-fc42-7ff1-9581-21009bf2a91b`：**Spec ✅，Approved，无 Critical/Important**。逐条核实：
  - **E25 落实到位**——`check_store` 重新加载 store，独立重校验 `category`/`severity`；手改 `category: "whatever"` 的用例会先加合法条目、再篡改、再写回，断言恰好两条 `friction-invalid-enum`（有判别力）；
  - `load_store` 覆盖全部 `ValueError` 路径（缺 `version`、非整数或非 1、`entries` 非列表、顶层非对象、不可读、非法 JSON），缺文件的默认形状正确；
  - `add_entry` **先校验后读改写**，被拒的 `add` 不可能碰到 store；`id = max(整数 id, default=0) + 1`，空 store 得 1；
  - `check_store` 逐条累积、无早退、无写入（只读性有用例字节比对）；
  - 退出码正确（0 / 1 / 2），`save_store` 走共享原子写。
  两个文件均 UTF-8 无 BOM。

- Task 1: minor (deferred)：`main` 无单测（退出码与 JSON 行为只做了冒烟，12 条配额全给函数级）；若干廉价覆盖缺口（组合筛选、未知筛选值返回空、被拒 `add` 后字节不变、非整数 `id`、顶层非对象/不可读）；`add_entry` 计算下一个 id 时会**静默忽略非整数或非 dict 条目的 id**（可辩护：避免被手改数据弄崩，且不会与整数 id 冲突），但这个选择没有写在文档里。

## 当前状态

- HEAD = `7efd38e`，工作树干净，**423 tests OK**。
- friction-log 的 store 与 `add`/`list`/`check` 完成；剩 Task 2（`export` + `aggregate`，终态 431）。
- 之后：`research-version`（E26 的 git 薄封装）→ 知识层 → 自动化与跨模型评审 → 模板库与派生流程。

## repro-package Task 3 执行记录

- 实施者 `Maxwell` = `01a10180-5849-7da0-855d-c1dd817b99dd`，commit `7258d0d`，**406/406**。
- **真实 venv 冒烟通过**（本任务最重要的一块证据）：CLI `bundle` 退 0；CLI `verify` 退 0 且带 `repro-scope`；`--keep` 下的环境里确实有 `pyvenv.cfg`、`Scripts/python.exe`，Python 3.12.14，并离线跑通了 `{python} hello.py`；冒烟用的临时目录已清理。
  这条证明了**默认的 `venv_factory` 与默认 runner 真的能建环境并执行**——注入式单测只能证明逻辑，证明不了这件事（与 latex-check 用真 MiKTeX、final-check 用真 PDF 是同一类硬证据）。
- 评审者 `Sagan` = `01a10183-c939-7570-a61d-087e4450de4a`：**Spec ✅，Approved，无 Critical/Important**。四条 e2e 断言均有判别力（第一条同时钉退出码 + `problem_count` + JSON advisory + stderr；第二条用列表相等，缺一条就过不了；三四条要求退出码 2 **且** stdout 为空）；参数顺序正确；UTF-8 显式；argv 执行不依赖 PATH。

- Task 3: minor (deferred)：**成功时重跑的输出被丢弃**——评审者明确判定这不是正确性缺陷（验证信号是退出码；把子进程输出打上 stdout 会破坏 JSON 契约），但长任务场景下"跑了 20 分钟、退 0、看不到任何输出"是可用的缺口；建议 `--verbose` 或把人读输出走 stderr 的 advisory。另有：e2e 的 `setUp` 用 `mkdtemp` 但无 `tearDown`（bundle 目录与 `report.py` 残留在 `%TEMP%`，venv 本身由 `verify_bundle` 清理）；e2e 首例依赖真实 venv（约 8 秒，且要求 Python 带 `ensurepip`）——评审者认为这对端到端检查是恰当取舍，建议加一句注释说明前提。

## 当前状态与下一步

- HEAD = `7258d0d`，工作树干净，**406 tests OK**。
- repro-package 三任务全部落地并通过任务级评审；**待跑最终全分支评审**（base `2440356`）。
- 之后：`friction-log` → `research-version`（E26 的 git 薄封装）→ 知识层 → 自动化与跨模型评审 → 模板库与派生流程。
- 账本裁定 E1–E28。

## E28 修复与 Task 2 结项

- 修复者 `Ptolemy` = `01a1017c-4c5d-7352-b81a-eb7cd83255ac`，commit `c9646e2`，**402/402**。注入点改为 `install_runner`（keyword-only，默认回退到 `runner`，因此真实 CLI 仍是同一套 `subprocess.run`，向后兼容）。
- 定向复审（`Laplace`）：**ADDRESSED，无新 issue，fix accepted**。三处关键核实：
  1. 安装失败时**确实没有走到重跑**（早退在 `try` 内，`finally` 仍清理临时 venv），且 `repro-install-failed` 是唯一 problem；
  2. 两条重跑用例现在各自注入"成功的 `install_runner` + 独立的失败 `runner`"，只走自己的路径——评审者确认它们**不会再因安装路径坏掉而误过**（各有专属覆盖）；
  3. 新用例记录重跑调用并断言 `run_calls == []` 与消息含"未尝试重跑"——**在旧的"总是重跑"行为下必然失败**，因此不是装饰性修改。
  无回归：哈希失败即止、`repro-scope` 在安装失败路径仍出现、E24 三类分流、`argv[0]` 专属替换 + `shell=False`、只读、临时 venv 清理均未变。
  Task 2: complete (commits 9b6b0e2..c9646e2, review clean)

### 这一轮再次印证的流程惯例

评审者点出：实现之所以把症状当主因，根因是**我的测试设计**——只注入一个 runner，使两次调用在测试里不可区分。这与 E27 那条是同一类：**测试的判别力决定了实现对错误的可见度**。已固化的惯例（无失败用例的安全声称视为未验证）在此再加半条：**注入点必须能让测试区分被测的两条路径，否则覆盖是假的。**

## 当前状态

- HEAD = `c9646e2`，工作树干净，**402 tests OK**。
- repro-package：打包侧完成、verify 完成；剩 Task 3（e2e + 真实 venv 冒烟，终态 406）。
- 之后：friction-log → research-version → 知识层 → 自动化 → 模板库。
- 账本裁定 E1–E28。

## research-version 实施与修复（E26 落地）

- 实施者 `Fermat`，Task 1 唯一任务，commit `99edf1c`，**444/444**（+12 用例）。判别力检查（字符串排序）实测失败，恢复后通过。
- 评审者 `Lovelace` = `01a101aa-1b6c-7b10-be1c-737ecf7f75b1`：**Spec ✅，1 Important**。

### Ruling E33（评审转裁定）— `--allow-dirty` 的标签消息必须写明"未提交内容没有被捕获"

背景: annotated tag 只能指向 commit；`--allow-dirty` 打的 `paper-v<N>` 指向 HEAD，未提交内容不在任何地方。原实现的标签消息只有 `dirty=true`、help 只写"记录 dirty=true"，用户会把版本号误读成"我当时的状态"。
Ruling: 保留该 flag（E26 已定要有），但脏树时标签消息追加第二行 `note=uncommitted changes are not captured; tag points at HEAD commit <sha>`（commit 用已解析的 rev-parse 结果），`--allow-dirty` 的 help 追加同一句声明。
理由: 版本号的可信度来自"它能指向一个可复现状态"；不能指向时必须自己说清楚。这条与第 7 条规则（工具不得在自己的输出里做不实声明）同源。
代价: 一个已知的不可复现版本号依然可以被制造出来；这是显式 opt-in + 显式声明的平衡，而不是用一个隐蔽的拒绝破坏 E26 的裁定。

### E33 修复 (commit `2ff989a`)

- `_tag_message(dirty, label, commit)`；`snapshot` 只调用一次 `working_tree_dirty`，把已解析 commit 传入消息；help 同步。
- 测试：`test_allow_dirty_records_dirty_true` 断言 note（含 sha）；真实 git 集成用例同样断言；新增 `test_clean_tree_message_carries_no_uncaptured_content_note` 防误加。
- 顺带 Minor：`_version_number` 对畸形标签抛具名 `ValueError`（新增用例）；新增 `diff` 未知 revision 经 `main` 退 2 用例（补上原先未用的 `redirect_stderr`）；脏树拒绝用例从"无 `-a`"强化为"无任何 `git tag` 调用"。
- 判别力实测：把 `_tag_message` 换回旧实现，两条 note 断言确实失败（不是纸面声明）。定向 15 用例 OK；全套 **447 OK**。
- **待办**：Lovelace 定向复审（review-99edf1c..2ff989a.diff）→ research-version 最终全分支评审（base `3c8039a`）。

## 知识层（knowledge-layer）计划与裁定

计划: `<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-knowledge-layer.md`（5 任务，两个工具 `library` + `memory`）
实测前提: venv 内 SQLite 3.53.1 `tokenize='trigram'` 可用（2 字中文不命中，须 LIKE 回退）；PyYAML、bibtexparser 2.1.0 可用。

### Ruling E34 — `library` 的真相/派生边界：来源哈希 + 过期拒绝服务

Ruling: 真相是 `library/refs.bib` + `library/notes/<key>.md`；`index.db` 是派生数据，允许 `index` 覆盖重建（"不覆盖"契约的具名例外，理由写进 help）；meta 表记录两枚 sha256；索引缺失或与源不符时 `search` 退 2 并点名"先运行 library index"，**不返回过期结果**。
理由: 本层最危险的失效是"索引没跟上、搜索给一个有缺口的空/旧结果且看起来正常"——这正是我们反复防的静默失效。重建代价极低，拒绝服务没有真实用户代价。
代价: 编辑 refs.bib 后必须重跑 index 才能搜；换来的是搜索结果永远可追溯到当时的源。

### Ruling E35 — 查询文本永不解释为 FTS5 语法

Ruling: 去空白后长度 ≥ 3 走 FTS5 `MATCH`，查询整体包成双引号短语、内部 `"` 翻倍；≤ 2 字符走 `LIKE ... ESCAPE '\'`（`%`/`_` 转义）；全部走 `?` 占位符；无命中退 0、空结果（搜索无命中是完整答案，不是问题）。
理由: 用户输入 `-`、`NOT`、引号不应产生 SQL 错误或语义漂移；trigram 的 2 字限制是分词器的硬事实（已实测），回退是唯一不引额外依赖的诚实做法。
代价: 2 字查询走 LIKE，个人库规模下可接受；跨库大时会慢，届时按 §8.4 触发条件再评估。

### Ruling E36 — `memory` 的字段契约与"死路必须可重开"

Ruling: `memory/ideas.md` / `memory/dead-ends.md` 是 YAML 列表（`#` 标题行是合法 YAML 注释）；dead-end 的 `reopen_if` 是**必填**字段（缺则 `add` 拒绝、`check` 报 `deadend-missing-reopen-if`）；id 同文件内唯一（`I<N>` / `DE<N>`）；写入前校验 + 读取时逐条重校验，坏条目不打断整轮（规则 5）。
理由: §8.2 第 4 条是 v1 完全缺失的行为；`reopen_if` 让死路可被重新打开，缺了它反重复记忆会退化成永久排除。与 friction-log E25 的"读取时校验"同一教训。
代价: 手工编辑记忆文件时字段格式受约束（换来脚本可核对）；YAML 语法错误仍然使整个文件不可审计（退 2），这是解析层的硬边界，不假装能局部恢复。

### Ruling E37 — §8.2 第 3 条（实验结果回写 claim 状态）明确推迟

Ruling: 本层不做 claim 状态回写。当前没有 claim registry——claim 与数字的对应由 `trace-claims` 的 `\dataval` 承担，没有可回写的存储。推迟到"实验-结论"层立项时一并建。
理由: 没有 claim 存储而先造"状态回写"会是无处安放的字段；按第 7 条与 DoD，未实现的东西必须写进 `--help` 与计划，不许沉默。
代价: 设计文档 §8.2 的四个行为本轮只交付 1/2/4；第 3 条带理由挂账。

### 本层 Non-goals（写进计划）

语义检索（§8.4 按需）、PDF 全文入索引（schema 无该列）、跨论文记忆聚合、claim 状态回写（E37）。

## 当前状态与下一步

- HEAD = `2ff989a`，工作树干净，**447 tests OK**。
- research-version：E33 已修，待 Lovelace 定向复审 → 最终全分支评审（base `3c8039a`）。
- 知识层：计划与 E34–E37 已定；待 research-version 结项后按 SDD 逐任务实施。
- 之后：知识层 → 自动化与跨模型评审 → 模板库与派生流程（强制前置：先评估 `bensz-paper` / `bensz-nsfc` 复用可行性）。

## research-version 结项

- 定向复审（`Lovelace`，`review-99edf1c..2ff989a.diff`）：**clean / Approved**。Important 关闭；clean 路径、label 顺序、`FakeGit` 调用序列断言无回归；`tag_calls()==[]` 的强化在实现顺序下是正确而非迎合测试；判别力为实（不是纸面）。两条非阻塞观察：note 是英文而 surface 是中文（一致性小缺口）；`_tag_message` 的 `commit or "HEAD"` 兜底实际不可达（无害）。
- 最终全分支评审（新派 `Peirce` = `01a101b0-020e-7c22-8db2-014d1646aa44`，`review-3c8039a..2ff989a.diff`）：**Merge readiness = Ready**，无新的 Critical/Important。
  - 独立复测两条判别力（字典序失败、旧无-note 实现失败）+ 真实 git 冒烟（clean → dirty 拒绝 2 → `--allow-dirty` 含 note+sha → commit 后 snapshot → `diff` 退 0 且含差异；annotated tag 对象类型实测为 `tag`）。
  - 已知 Minor 全部处理（畸形标签具名报错 / diff 未知 revision 退 2 / `tag_calls()==[]` / 无未用 import）。
  - 残余风险（诚实挂账）：`_default_runner` 把 stdout+stderr 拼接返回（若未来成功路径 stderr 有 warning 会被当标签解析）；`tag -l` 与 `tag -a` 两次调用之间并发可能抢号（退 2 不静默覆盖）；`--path` 真实 diff 行为与 `--repo` 非仓库负例无真实用例；`git status --porcelain` 的目录级折叠无专项用例。
  research-version: complete (commits 3c8039a..2ff989a, review clean)

## 累计状态（research-version 结项时）

- 九个工具成形：`citation_guard` / `trace_claims` / `latex_check` / `final_check` / `provenance` / `run_log` / `repro_package` / `friction_log` / `research_version`。测试从 125 增至 **447**；账本裁定 E1–E37。
- HEAD = `2ff989a`，工作树干净。
- 知识层 Task 1 已派实施者 `Confucius` = `01a101af-c917-7ab1-981c-94e884bc1f89`（计划 `2026-10-03-knowledge-layer.md`，base 届时 HEAD）；待其报告后走 review-package → 独立评审。

## knowledge-layer Task 1 执行记录

- 实施者 `Confucius`，commit `3aced21`，**472/472**（+25 用例；brief 预计 ~16，实施者按检查点拆细）。
- 三条判别力实测（原始断言已报告）：去短查询回退 → `'fts' != 'like'`；去新鲜度校验 → `ValueError not raised`；去短语转义 → 三条 `sqlite3.OperationalError`（unterminated string / no such column / syntax error near NOT）。
- 评审者 `Halley` = `01a101b5-b294-7d73-a154-64a2ecaf5d10`：**Approved**，无 Critical/Important。独立复现了三条判别力；另跑了危险面探针（损坏 index.db → ValueError；改一字节 note → 过期退 2；`NEAR`/`Alpha-Beta` 当字面量；`%`/`_`/`\` 转义正确；真实 CLI 子进程 index/search/过期/`--limit abc`）。

### Task 1 Minor 处置（7 条）

折进 Task 2 处理（2 条）：
- `library search --help` 缺 description，未在自然位置写明"不含 PDF 全文"边界，且字段清单漏 key 与 path（不完整声明）。
- `path` 字段不参与新鲜度，新增/删除 PDF 后结果滞后 → 改为查询时按文件系统现状解析，规则写进 docstring 与 help，并补 3 条用例。

挂账（5 条，均为已固化的既有边界或极边缘）：
- `bib.py` 重复 key 的报错文本从 `DuplicateBlockKeyBlock` 改为 `duplicate keys: …`（语义与签名不变，无调用方解析该文本）；DOI 现在先过 `_clean` 再 normalize（仅病态花括号 DOI 有差）。
- 长度分类用 `strip()` 而非去除全部空白：含内部空格的 3 字符查询走 FTS5（"去空白后"措辞歧义，无用例）。
- `.tmp` 固定文件名在并发 `library index` 下会撞（与仓库其他工具同一既有非目标）。
- `parse_args` 在 try 之外（`--limit abc` 走 argparse 退 2，无"工具错误:"前缀，与既有工具一致）。
- 未覆盖面：`.tmp` 原子性无法单测证明；整文件读入内存是已挂账限制。

## knowledge-layer Task 2 执行记录

- 实施者 `Confucius`，commit `6cdeaa3`，**488/488**（+16 用例，test_library 共 41 条）。三条判别力实测：去 `index-stale` 实质校验 → `'index-stale' not found in []`；check 早退 → `['index-stale']`（缺 `duplicate-bib-key`）；path 改回索引快照 → `'' != 'papers/sample.pdf'`。
- 评审者 `Halley`：**Approved**，无 Critical/Important。独立复现三条判别力；CLI 实测 check clean→0 / 有问题→1 / 缺 refs→2；目录前后文件集一致（无 `-journal`/`-wal`/临时文件）；7 个 code 全有落点且两种问题并存都报出。
- Task 2 Minor（4 条）处置：
  - **当场修（1 条，控制器直改 commit `9a760b2`）**：help 把 `path` 列入可检索字段，而 `papers.path` 列恒为空——这是"声明与实际不符"，按第 7 条规则不挂账。修复：help 字段清单改为 7 个真实可检索字段 + "path 是结果字段、不参与检索"；LIKE 回退删掉恒空的 `path` 死列；docstring 写明 path 列是保留占位列；新增 `test_path_is_an_output_field_never_a_search_term`（结果 path 正确解析，但 path 文本检索零命中）。判别力实测：旧文案下目标断言失败。全套 **489 tests OK**。待 Halley 定向验证。
  - 挂账（3 条）：`index.db` 存在但无 meta 行时走"工具错误"（可辩护：无法审计即 2，但无对应用例）；`main` 的 `check` 干净→0 / 缺 refs→2 两条退出码路径缺直接断言（CLI 子进程已实测正确）；`check_library` 对 refs.bib 读两次的本地 TOCTOU（既有挂账模式）。

## 当前状态与下一步

- HEAD = `9a760b2`，工作树干净，**489 tests OK**（`9a760b2` 验证与 Task 3 并行在飞）。
- knowledge-layer：Task 1 / Task 2 Approved；Task 2 修复待定向验证；Task 3（memory store）已派 `Confucius`，base `9a760b2`。
- 之后：Task 4（memory check + search）→ Task 5（e2e）→ 知识层结项 → 自动化与跨模型评审 → 模板库与派生流程。

## Task 2 修复验证与收尾

- Halley 定向验证 `9a760b2`：**ADDRESSED**，无新 Critical/Important。独立复现"旧文案下断言失败"；确认 help 字段清单只有 7 个真实可检索字段、无新的不实声明；Task 2 的 7 个 code / 只读 / 退出码无回归（全套 489 OK）。
- Halley 两条纯文案/测试强度 Minor 已当场收尾（commit `0d06e44`）："存在在"连读改顺；help 用例新增负向断言 `notes/path` 不得出现，防止 path 被加回检索清单。`test_library` 42 例 OK。
  - 说明：`0d06e44` 为控制器直改的文案+断言，未单独送审；将纳入知识层最终全分支评审范围。

## knowledge-layer Task 3 执行记录

- 实施者 `Confucius`，commit `3715520`，**504/504**（+15 用例）。两条判别力实测：删 `reopen_if` 必填 → `ValueError not raised`；id 用 `len+1` → `'I3' != 'I4'`。
- 规格补充（实施者自述，控制器认可）：`list_memory` 返回形状定为 `{"ideas": [...], "dead_ends": [...]}`，与 Task 4 的 `search` 输出键保持一致；`add_dead_end` 的 `reason`/`evidence`/`reopen_if` 以 `None` 默认值统一校验，保证"省略"与"空串"都得到 `ValueError` 而不是 `TypeError`。
- 评审者 `Kepler` = `01a101c6-d9da-7691-b524-e44de974717c`，review-0d06e44..3715520.diff，进行中。

## 当前状态与下一步

- HEAD = `3715520`，工作树干净，**504 tests OK**。
- knowledge-layer：Task 1/2/3 已提交（Task 3 评审在飞）；待 Task 3 评审后派 Task 4（memory check + search）。
- 之后：Task 4 → Task 5（e2e）→ 知识层结项 → 自动化与跨模型评审 → 模板库与派生流程。

## knowledge-layer Task 3 评审结项

- 评审者 `Kepler`：**Approved**，无 Critical/Important。独立复现两条判别力（删 `reopen_if` 校验 → `ValueError not raised`；id 用 `len+1` → `I3 != I4`）；另实测省略/空串两条路径、BOM=False、追加保留、无 `.tmp`、parent 为文件时 `ValueError`、`date`/`idea` 歧义串（`yes/no/true/123/null`）round-trip 仍为 `str`。
- Task 3 Minor（5 条，全部是测试覆盖缺口、非行为缺陷）已**全部折进 Task 4 任务书**（Task 4 要改同一个测试文件）：BOM 断言；`load_memory` 的 `OSError`/`UnicodeDecodeError` 折叠；`list_memory` 非法 kind/status 负例；`add-dead-end` CLI happy path；日历非法日期（`2026-13-01`/`2026-02-30`）。
- 评审者另指出共享基建缺口（挂账）：`save_text_atomically` 的 `OSError→ValueError` 折叠无任何一处测试（跨工具既有缺口，不属本任务）。

## 当前状态与下一步

- HEAD = `3715520`，工作树干净，**504 tests OK**。
- knowledge-layer：Task 1/2/3 Approved；Task 4（memory check + search + 5 条结转）已派 `Confucius`，base `3715520`。
- 之后：Task 5（e2e）→ 知识层最终全分支评审 → 自动化与跨模型评审 → 模板库与派生流程。

## knowledge-layer Task 4 评审与修复轮（E38/E39）

- 实施者 `Confucius`，commit `6d549ce`，**524/524**（test_memory 15→35 条）。两条判别力实测：删 status 重校验 → `'memory-invalid-status' not found in []`；search 遇坏条目抛异常 → `ValueError: bad entry`。
- 评审者 `Kepler`：**Approved**，无 Critical/Important。独立复现两条判别力；CLI 实测 check clean→0 / 有问题→1 / 坏 YAML→2 / search 无命中→0；专项确认"重复 id 时两条都被跳过"不是缺陷（E36 下同 id 两条本身即无效，对称跳过，无偏袒）。

### Ruling E38 — dead-end 的 `reason`/`evidence` 读取时也要重校验

背景: 写入时 reason/evidence/reopen_if 三字段必填，但 Task 4 判定表只要求读取时重校验 reopen_if，形成"写入严、读取松"的不对称；手改清空 reason/evidence 会静默通过 check。
Ruling: `check_memory` 对 reason/evidence 做与写入时同强度的读取时校验（缺失/空串/非字符串 → `memory-missing-field` 并指明字段），`reopen_if` 保留专门 code。
理由: 记忆文件的价值在于"脚本可核对"；一个没有 reason 的死路条目正是需要浮出来的坏记忆，读取时漏报等于把写入时校验降级成一次性装饰。
代价: 手改文件的容错面变窄（这正是意图）。

### Ruling E39 — `search` 的跳过必须可解释

背景: search 只给 `skipped_invalid` 计数，用户在"命中但被跳过"时无法仅凭搜索结果知道发生了什么（评审 Minor）。
Ruling: 保留计数的同时新增 `skipped` 列表（`{"file","id","codes"}`）；非映射、重复 id、校验失败都带 code 进列表；计数键保持兼容（Task 5 e2e 已按计数写，不变）。
理由: 与九条规则第 5 条同源——坏条目不打断整轮，但也不能无声；"给数字不给名字"让用户无法行动。
代价: 返回 JSON 变大（可忽略）；坏条目的 id 可能缺失 → 用 null，诚实表达"连 id 都没有"。

- 修复轮已派 `Confucius`（base `6d549ce`），commit message `fix: revalidate dead-end fields and report skipped memory entries`；随后 `Kepler` 定向验证。

## 当前状态与下一步

- HEAD = `6d549ce`，工作树干净，**524 tests OK**；修复轮在飞。
- knowledge-layer：Task 1–4 已提交（Task 4 修复待验证）；之后 Task 5（e2e）→ 知识层最终全分支评审。

## E38/E39 修复验证（Task 4 结项）

- 修复者 `Confucius`，commit `c3f851a`，**530/530**（test_memory 41 条）。判别力实测：删 reason/evidence 重校验 → `AssertionError: 0 != 1` ×2；删 `skipped` → `KeyError: 'skipped'`。
- 定向验证（`Kepler`）：**ADDRESSED**，无新 Critical/Important。E38/E39 落点核实；`skipped_invalid == len(skipped)` 全路径恒等（含空结果 0==0、含坏条目 3==3）；8 个 check code 无回归；上一轮 4 条 Minor 全部关闭（1→E39、2→E38、3/4→补测）。
- Kepler 新 Minor（2 条）处置：
  - **待收尾（已排期）**：`skipped[].file` 存的是 kind（`"ideas"`/`"dead-ends"`）而键名叫 `file`——命名与实际不符。决定改为**真实相对路径**（`memory/ideas.md` / `memory/dead-ends.md`），与 Task 5 的 e2e 断言在同一轮改（Task 5 在飞，先不改，避免与其冲突）。
  - 挂账：非字符串 id 的条目在 `skipped[].id` 里为 `null`（codes 已带 `memory-invalid-id`，值不可见但问题可见）。

## 当前状态与下一步

- HEAD = `c3f851a`，工作树干净，**530 tests OK**。
- knowledge-layer：Task 1–4 全部 Approved（含修复验证）；Task 5（e2e）在飞。
- Task 5 落地后：`skipped[].file` 改真实路径 + e2e 断言同轮调整 → 知识层最终全分支评审 → 自动化与跨模型评审 → 模板库与派生流程。

## knowledge-layer Task 5 与 E40

- 实施者 `Confucius`，commit `8000ac3`，**536/536**（+6 条 e2e，真实文件树 + 真实 SQLite，无 mock/注入）。退出码证据：0（index/search/check 正路径、中文 3 字 FTS、2 字 LIKE、无命中空）、1（note 删除+游离 note → `index-stale`+`note-without-entry`；删 `reopen_if` → `deadend-missing-reopen-if`）、2（改 refs 后 search → stdout 空、stderr 含"过期"）。
- 实施者诚实报告一条未满足项：`memory check` 的人类消息不点名条目 id（计划场景 5 要求），因该任务只许新建测试文件而未越界修改。**控制器判定为真缺口**，立 E40。

### Ruling E40 — check 消息必须点名条目 locator；`skipped[].file` 必须是真实路径

Ruling: (1) `_entry_problems` 的每条 Problem 消息加 locator 前缀——有合法 id → `条目 <id>`，否则 `第 <n> 条`；(2) `skipped[].file` 的值从 kind（`"ideas"`/`"dead-ends"`）改为真实相对路径（`memory/ideas.md` / `memory/dead-ends.md`），Task 5 e2e 断言同步改。
理由: §6.1.1 要求问题带定位；YAML 列表条目没有行号，id/序号是诚实的等价物。`file` 键存 kind 是命名与实际不符（与 E33/E34 同类）。
代价: 消息文本变化（无调用方解析文本）；e2e 断言需同步修改。

修复轮已派 `Confucius`（base `8000ac3`）：`fix: name memory entries in check messages and skipped records`；随后 `Kepler` 定向验证。

## 自动化阶段计划（automation-review）与裁定 E41–E45

计划: `<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-automation-review.md`（5 任务：milestones / cross_review / watch / queue / 接线文档+e2e）
环境实测: `codex-cli 0.160.0`；`codex exec` 支持 `-m`、`-s read-only`、`--ephemeral`、`-C`、`--skip-git-repo-check`、`-o`、`--output-schema`、`--json`。

- **E41 cross_review 的诚实边界**：记录实际 model 与 `family_judgement`（默认 v4-pro 记 `same-family`，help 写明"非跨族"）；verdict 只来自结构化输出（`--output-schema` + `-o`），缺失/不合 schema → `review-malformed`（1）绝不默认通过；输入 sha256 入记录，变化后 `check` 报 `review-stale`；`codex exec` 一律 `-s read-only --ephemeral --skip-git-repo-check`。
- **E42 deadline 是可选字段**：`target_venue.deadline: "YYYY-MM-DD" | null` 入模板与 validate（存在时校验真实日历日）；`create.py` 支持 `--deadline`；无 deadline → `mode: sequential` 顺序提示，不伪造倒排日期。
- **E43 watch 只报事实**：只输出结构化新增（id/title/published/summary 截断）；首次运行自动建基线并如实打印数量；state 原子写；网络失败退 2 且**不推进 state**。
- **E44 queue 失败分流**：每次尝试先 `running` 后终态（失败留档）；重试只针对清单显式 `retry_exit_codes`（默认空=不重试）；超时=一次失败；预算按墙钟，耗尽记 `stopped-budget`、重试耗尽记 `stopped-retries`；禁止静默重试到成功。
- **E45 默认安静**：工具不产生"我检查过了"叙述；automation prompt 模板必须写明"无新增/无到期/无变化就不通知"；实际挂载 automations 需用户确认后执行。

Non-goals: 真跨族评审（无第二 provider）、自动改正文/结论字段、分布式+GPU 配额调度、语义检索。

## 当前状态与下一步

- HEAD = `8000ac3`，工作树干净，**536 tests OK**；E40 修复在飞。
- knowledge-layer：Task 1–5 已提交；待 E40 验证 → 知识层最终全分支评审。
- 之后：按 automation-review 计划逐任务实施 → 模板库与派生流程（强制前置：评估 `bensz-paper` / `bensz-nsfc`）。

## E40 验证与 knowledge-layer 终审

- 修复者 `Confucius`，commit `d3940f9`，**538/538**。判别力实测：去掉 locator 前缀 → `AssertionError: False is not true`（id 与 `第 1 条` 两处）；`file` 改回 kind → `'dead-ends' != 'memory/dead-ends.md'`。
- 定向验证（`Kepler`）：**ADDRESSED**，无新 Critical/Important。E40 两条落实；8 个 check code 无回归；`skipped_invalid == len(skipped)` 不变；e2e 的 0/1/2 退出码无回归；独立复现两条判别力（含 `relative_to(".")` 不崩）。
- Kepler 新 Minor（2 条，**挂账不修**，理由：均为观感级、消息正文已带出坏值、改它属金饰）：
  1. locator 判定用"任意非空字符串 id"而非"合法 id"格式 → 坏的 `I0` 得到 `条目 I0` 而非 `第 n 条`（消息正文仍带 `I0` 与 `id 必须匹配` 的 code）。
  2. `skipped[].id` 对空串 id 返回 `""`，locator 走 `第 n 条`，同一坏条目两处表述不一致（无功能影响）。
- 知识层最终全分支评审：新派 `Bohr` = `01a101dc-4c6f-7f03-be26-3caec0007ca6`，review-2ff989a..d3940f9.diff（9 commits），进行中。

## automation-review Task 1 已派

- 计划 `2026-10-03-automation-review.md`；Task 1 = `milestones` + `deadline` 字段（模板/validate/create 同步）。
- 实施者 `Confucius`（base `d3940f9`）；与知识层终审（只读）并行，文件不相交。

## automation-review Task 1 执行记录

- 实施者 `Confucius`，commit `4714004`，**558/558**（+20：milestones 16、validator 2、create 2）。改动 7 文件（模板/validate/create/新工具/3 测试）。
- 判别力实测：checkpoint 判定改 `≤` → `due` 意外非空（`Lists differ: [{'checkpoint': 'T-7', ...}] != []`）；sequential 注入日期 → `assertIsNone(report["due"][0]["date"])` 失败。
- 实现者自述偏离（评审重点）：`due_report` 在四键外增 `problems`/`advisory`；checkpoint→stage 映射为 T-14→internal-review、T-7/T-3→submission-check；gate 缺口按当前 stage 到目标 stage 逐 gate 枚举。
- 评审者 `Archimedes` = `01a101e0-59d7-7c03-b0b5-a60753e07cf5`，review-d3940f9..4714004.diff，进行中（重点：映射与 stages.py 一致性、越界/漏报、deadline 链路、只读与定位）。

## automation-review Task 2 已派

- `cross_review`（codex exec 编排、严格 verdict、输入哈希、真实冒烟）；实施者 `Confucius`，base `4714004`。
- 与 Task 1 评审并行，文件不相交。

## knowledge-layer 结项

- 最终全分支评审（新派 `Bohr` = `01a101dc-4c6f-7f03-be26-3caec0007ca6`，review-2ff989a..d3940f9.diff，9 commits）：**Merge readiness = Ready**，无 Critical/Important。
  - 核实：退出码 0/1/2 不混；stdout JSON / stderr 人读一致；两个 check 只读有字节级用例；`library` 覆盖仅限派生 `index.db`（help 写明）；`memory` 追加不覆盖；E34 全链路（真值/双 sha256/过期拒绝/2 字回退/查询不当语法/path 查询期且不参与检索）；E36/E38/E40 全链路；DoD 447→538（+91 ≥ +50）；诚实边界（PDF 全文边界、子串非语义检索、claim 回写未实现 E37）help/docstring 齐备。
  - 独立抽查：同索引 2 字 `MATCH` 0 行 vs `search` LIKE 命中；改 refs 后 `ValueError` 含"过期"；`git diff --check` 干净；6 文件 BOM=False；两工具 help 边界文本齐备。
  - 新 Minor（1 条，挂账不修）：idea 缺 `status` 被报成 `memory-invalid-status`（消息 `status 非法: None`）而非 `memory-missing-field`——标签错位但**不静默漏报**，低价值。
  knowledge-layer: complete (commits 2ff989a..d3940f9, review clean)

## 累计状态（knowledge-layer 结项时）

- 十一个工具成形：前九个 + `library` + `memory`。测试从 125 增至 **538**；账本裁定 E1–E45。
- 知识层挂账（诚实清单）：idea 缺 status 标签错位；locator 对非空非法 id 用 `条目 I0` 而非序号；`skipped[].id` 对空串返回 `""`；`index.db` 缺 meta 行退 2 而非 problem code；固定 `.tmp` 并发竞态；`save_text_atomically` 折叠无共享用例；`library` 整文件读入内存。语义检索/PDF 全文/跨论文记忆聚合/claim 回写（E37）均明确为 Non-goals。

## 模板阶段强制前置：bensz-paper / bensz-nsfc 复用评估（完成）

- 评估者 `Averroes` = `01a101dd-078f-77e3-a932-730b8e4e5768`；备忘：`<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-bensz-reuse-evaluation.md`（只读评估，未改本仓库）。
- **Verdict：低—中，reference-only（零代码 vendor）。**
- 关键证据（控制器抽查复核）：
  1. MIT（`license.txt:1-6`，© 2024 Weibin Huang）；vendor 需随附 MIT 全文+版权行；`packages/bensz-fonts/fonts/` 有 20 个字体文件（14 otf + 6 ttf，控制器复核一致），字体再分发许可未验证，**不随 MIT 授权，不复制**。
  2. `bensz-paper` 是 `article` + `\usepackage{bensz-paper}` + `\BenszPaperSetup{...}` 的 SCI 样式层，`bml-bibliography.sty` **无条件加载 biblatex/biber**（默认 gb7714-2015）；直接叠加会与 NeurIPS/ICML/ACL/AAAI 官方类抢格式。可借鉴：profile 键值 + 二次覆盖、薄入口、`extraTex` 单一正文源、`.latex-cache/` 产物隔离。
  3. `bensz-nsfc` 是 ctexart + `[type=general|local|young]` + BibTeX bst + 四遍 xelatex 链，与顶会/期刊目标无交集 → 不复用。
  4. **本机 MiKTeX 实测两例均编译失败**（exit 1，无 PDF）：NSFC 缺 `wasysym.sty`/`tabu.sty`，paper 缺 `setspace.sty`，且缺 `biblatex-gb7714-2015.bbx`；MiKTeX on-the-fly installer 非交互报 `FATAL ... GUI framework cannot be initialized`。上游只推荐 TeX Live/MacTeX 且 CI 无 LaTeX 编译作业。属环境未满足，不等于模板不可编译。
- **对模板阶段的约束（写进模板计划）**：顶会链路自建 profile 元数据层（官方类 + ccfa.yaml 记录模板标识与校验项）；零代码 vendor；若未来做中文期刊派生，先出参数转换表，复制 `bml-core` 子集时必须附 MIT 声明；在干净 TeX Live 环境跑上游 `validate_package.py` 留档（当前未做，标注"环境未满足"）。

## automation-review Task 2 执行记录

- 实施者 `Confucius`，commit `42e59bb`，**575/575**（+17 用例）。判别力实测：malformed 默认通过 → `'pass' != 'malformed'`；argv 去 `-s read-only` → `'-s' not found`。
- **真实冒烟（本计划最重要证据）**：临时论文目录真跑 `codex exec -m deepseek-v4-pro -s read-only --ephemeral --skip-git-repo-check -C <tmp> --output-schema <tmp>/reviews/cross-review.schema.json -o <tmp>/reviews/cross-review-last-message.json -`；**exit 0、38.6s、verdict=blocking、blocking_count=4、schema 解析通过、family_judgement=same-family**。4 条 blocking：缺少跨模型评审报告 / 引用核验未通过 / 数字核验未通过 / 图表核验未通过（对最小临时稿是合理结论）。
- 评审者 `Aquinas` = `01a101e5-45a7-7281-a442-5e1d624c9484`，review-4714004..42e59bb.diff，进行中（重点：argv 契约、E41 诚实性、schema 文件落点、stderr 无界写入、离线可测）。

## automation-review Task 3 已派

- `watch`（arXiv 增量、state 原子写、失败不推进 state）；实施者 `Confucius`，base `42e59bb`；与 Task 2 评审并行，文件不相交。

## automation-review Task 3 执行记录

- 实施者 `Confucius`，commit `1887695`，**591/591**（+16，全部离线注入 fetcher）。判别力实测：新 ID 判定改全部 → `['...0001','...0002'] != ['...0002']`；失败仍写 state → 字节比对断言失败。
- 实现要点：state `{"version":1,"seen_ids":[...]}`；`limit` 只限制本轮 `new`，未报告的新 ID 不写 seen（防丢未读）；首次无 state 自动 baseline，损坏 state 不被覆盖；summary 截断 500 字符。
- 评审者 `Ohm` = `01a101e8-da8f-7d50-96a7-3f06d8aedc54`，review-42e59bb..1887695.diff，进行中。

## automation-review Task 4 已派

- `queue`（顺序执行、超时/显式重试/墙钟预算、每次尝试进 run-log、失败不静默）；实施者 `Confucius`，base `1887695`；要求先读 `run_log.py` 现有接口并如实报告接线方式。

## automation-review Task 1 评审：Request Changes（E46）

- 评审者 `Archimedes`：**Request Changes**，2 Important + 3 Minor；判别力两条均已独立复现（`<=` 判定失败；sequential 注入日期失败）；deadline 链路（模板/null/ISO/非法→2/不留残渣）与只读性（SHA-256 前后一致）通过。

### Ruling E46 — 检查点自身的 gate 在越过该阶段前必须算未过；T-7 归 internal-review

背景 1: `_gate_problems` 用 `stages[current_index:target_index]` **排除 target**，`main` 只看 `problems` 定退出码。实测 deadline 2027-05-01、`stage.current=submission-check`、today 2027-04-28（T-3）→ `due=[T-3 package_ready]`、`missing_gates=[]`、退 **0**。"论文正停在检查点阶段"是最典型状态，却判干净——这是会漏掉截止动作的静默误判，与判定表"命中且未过 gate → 1"直接冲突。
背景 2: `T-7` 映射到 `submission-check`（`package_ready`）与设计 §4.5 不符：T-7 = 引用/数字/图表三项核验 = `internal-review.review_cleared`（stages.py:71），`package_ready` 是 T-3 的语义。
Ruling: (1) 区间改 `stages[current_index : target_index + 1]`（"还停在该阶段"=该阶段 gate 未过；越过才算过）；(2) `_CHECKPOINT_STAGES["T-7"]="internal-review"`；(3) 当天命中但 `current_index > target_index` 的检查点不得进 `due`（automation 读到 `due` 不应以为有动作）。
理由: 退出码必须反映"检查点当天该 gate 未过"这一事实；把 target 排除导致工具在最常见场景下做不实声明（第 7 条）。T-7 映射错位会把"三项核验"提前标成"投稿包"。
代价: 修复后 `stage.current == target_stage` 的当天会退 1（这正是意图）；此前依赖"退 0"的自动化行为需要按新语义理解。

- 修复者 `Chandrasekhar` = `01a101e9-676a-7792-927c-2af1fe30b946`（新派，不打断在飞的 queue 实施），base `1887695`；commit message `fix: treat a checkpoint gate as pending until the stage is passed`；随后 `Archimedes` 定向复评。
- Minor 处置：非法 mode → 2（"无法计算阶段顺序=工具错误"，挂账，与 validate 的分工不同）；定位只有路径无行号（挂账，字段级等价定位可接受）；已过检查点进 due（并入 E46 修复）。

## automation-review Task 2 评审：APPROVE + 1 Important 修复

- 评审者 `Aquinas`：**APPROVE**，无 Critical；E41 诚实性契约成立；两条判别力独立复现；离线 575 OK；逐 flag 对照 `codex exec --help` 核实 argv 契约。
- **Important（要修，违反任务书"摘要"措辞）**：失败/malformed/成功三条记录路径把完整 stderr 原样写入，无上限（`capture_output=True` 全量），可把记录与内存顶到无界；异常消息用了 `stderr[:500]`，两者不一致。
- Minor：`check` 忽略自定义 `--out-dir`（run 到 foo 后 check 报 review-missing）；schema 与 last-message 在 `reviews/` 持久残留（评审判定可接受：专用目录、幂等重写，可留作审计痕迹）。
- 修复排给 `Chandrasekhar`（在 milestones 修复之后、独立 commit）：stderr 统一截断（≥ 标记）+ `check --out-dir`；commit `fix: bound review stderr in records and let check honor out-dir`；随后定向复评。

## E46 修复落地（待定向复评）

- 修复者 `Chandrasekhar`，commit `68c7580`（`fix: treat a checkpoint gate as pending until the stage is passed`），在 queue 之前落地；全量测试当时 591+（其报告将随 cross_review 修复一并复核）。**待 `Archimedes` 定向复评**（其已关闭，届时 resume）。

## automation-review Task 4 执行记录（queue）

- 实施者 `Confucius`，commit `071bf41`，**607/607**（+16）。判别力实测：默认不重试改失败即重试 → `3 != 1`（runner.calls）；关闭预算停止 → 期望 `['complete','skipped-budget']` 实得 `['complete','complete']`。
- run-log 接线：**import 复用公开 `run_command`/`log_metrics`**，不复制私有实现；每次 attempt 由 `run_command` 原子写 `running`→终态；超时 → `exit_code=124` + `log_metrics({"timeout": true, ...})`；默认 runner `shell=False`、不捕获子进程 stdio（直通）。
- 语义说明（评审确认点）：`max_attempts=1` 时不标 `stopped-retries`（未实际重试）；重试耗尽停整个队列（后续项不进 `runs`）；预算耗尽把当前及后续项记 `skipped-budget`。
- 评审者 `Aquinas`（复用 Task 2 评审者），review-68c7580..071bf41.diff，进行中。
- 注意：Task 4 提交时工作树有并发的 `cross_review` 修复改动（Chandrasekhar 在飞），其已核对未把无关文件纳入 commit。

## automation-review Task 5 已派

- 接线文档 + 四 prompt 模板 + e2e；实施者 `Confucius`，base 以提交时 HEAD 为准；e2e 用默认 out-dir，避免依赖在飞修复细节。

## automation-review Task 3 评审：Approve + watch 修复轮

- 评审者 `Ohm`：**Approve**，无 Critical/Important；两条判别力独立复现（新 ID 判定改全部；失败仍写 state）。
- 深度核实通过：两轮 `limit=1` 实测 `['id1']→['id2']→[]`（未报告 ID 不写 seen，防丢未读）；中文摘要 600→500 截断无半个字符、无 `\ufffd`；`&amp;nbsp;` 仅 XML 层解码、不做 HTML 反转义；测试全部注入 fetcher 无联网。
- Minor 处置：
  - **要修**：`--force` 与 `--baseline` 等价（实际是合并），违反仓库"`--force` 才覆盖/重置"约定；`parse_feed` 对 Atom xhtml 嵌套 `title` 只取 `child.text` → 整条被当缺 title 跳过。
  - 挂账：state 不记录来源 URL 集合（arXiv ID 全局唯一，无误报；换非全局唯一 feed 才可能假阴性；force 重置路径落地后已有恢复手段）。
- 修复派 `Chandrasekhar`（resume）：commit `fix: let watch force reset the baseline and read nested titles`；要求 force=重置（含从损坏 state 恢复）、baseline=合并、itertext 取标题；随后定向复评（`Ohm`）。

## 修复轮汇总（在飞）

- `68c7580` milestones（E46）→ `Archimedes` 定向复评中。
- `a0e1048` cross_review（stderr 截断 + check --out-dir）→ 待 `Aquinas` 完成 queue 评审后定向复评。
- watch（force 重置 + xhtml 标题）→ `Chandrasekhar` 实施中。

## watch 修复落地（待定向复评）

- 修复者 `Chandrasekhar`，commit `4710ca2`，watch 模块 21 例、当时全量 **629 tests OK**（含并行 Task 5 未提交的 e2e，7 例）。
- `--force` = 重置（不读/不校验旧 state，含损坏 state 恢复路径；stderr 如实"已重建基线 N 条"）；`--baseline` 保持合并；`title/summary` 用 `itertext()` 取后代文本。
- 判别力实测：force 改回 merge → `seen_total 3 != 2`；itertext 改回 child.text → `len(entries) 0 != 1`。
- 定向复评：`Ohm`（resume）进行中。

## automation-review Task 5 执行记录

- 实施者 `Confucius`，commit `b40b828`，**629/629**（+7 文档/e2e 用例）。
- 交付：`automation/README.md` + 四个 prompt 模板（`weekly-watch.md` / `deadline-check.md` / `stage-advance.md` / `experiment-queue.md`）+ `tools/tests/test_automation_e2e.py`。
  - 四模板静默语句均落到可判定字段：watch `new=[] 且 skipped=0`；milestones `due=[] 且 problems=[]`；stage-advance "阶段和 gate 无变化"；queue "全部 complete 且 stopped=null"。
  - README：实际创建 automations 需用户确认；只做信息收集与提醒；不得改正文与 `ccfa.yaml` 结论字段。
- 合理偏离（记录）：计划路径 `paper-template/automation/` 在当前仓库布局下会嵌套错误，实施者落在仓库根 `automation/`（仓库根本身即 paper-template 库）——评审核实中。
- 评审者 `Plato` = `01a101f2-15ac-75f3-991f-9c050170ef1f`，review-4710ca2..b40b828.diff，进行中（重点：点名路径/字段真实存在、静默语句可判定、安全边界、e2e 真实性、路径偏离）。

## automation-review Task 4 评审（APPROVE + E47）

- 评审者 `Aquinas`：**APPROVE**，无 Critical；两条判别力独立复现；`max_attempts=1` 不标 stopped-retries 被判**可接受**（没有发生重试，标 retries 才是谎报）；真实子进程冒烟确认 stdio 直通（OUT/ERR 两路原样）；run-log 接线确认只 import 公开 `run_command`/`log_metrics`。
- **Important（要修）**：`retryable = timed_out or exit_code in retry_exit_codes` —— 超时**无条件**可重试，与 E44"重试只针对清单显式声明的 `retry_exit_codes`（默认空=不重试）"口径冲突；现有用例还把该行为固化成契约。
- Minor：超时在 run-log 顶层仍是 `failed(124)`，timeout 只在 metrics（可追溯，挂账）；清单 cwd 不存在 → 记录 failed 后整体退 2（未在判定表约定，需明确并补测）。

### Ruling E47 — 超时重试也必须显式声明；坏 cwd 是清单错误

Ruling: (1) 清单项新增 `retry_on_timeout: false`（默认 false，必须为布尔）；超时仅当该项显式 `retry_on_timeout: true` 且 `max_attempts` 未耗尽才重试；(2) 把"cwd 不存在 = 清单错误 → 记 failed 后整体退 2"写进 help/docstring 并补一条用例（当前行为保留）。
理由: E44 的核心是"重试只发生在清单显式声明处"——超时没有退出码，因此需要一个显式的布尔键，而不是"超时天然可重试"的隐含规则。默认不再因 max_attempts>1 悄悄多跑一次。
代价: 想重试超时的清单要显式写 `retry_on_timeout: true`（这正是意图）；既有用例需改为显式声明后再断言重试。

- 修复排期：等 `Confucius`（queue 作者）槽位释放后派发；`Chandrasekhar` 已关闭。修复后由 `Aquinas` 定向复评。

## watch 修复定向复评：ADDRESSED

- `Ohm` 复评 `4710ca2`：**ADDRESSED**，无新 Critical/Important。force 重置（旧 ID 消失、损坏 state 恢复退 0、stderr"已重建基线 N 条"）、baseline 合并、xhtml 嵌套标题均核实；额外验证 force 遇 OSError/坏 XML 时旧 state 字节不变（不会重置到半截）。判别力两条独立复现。
- 新 Minor（挂账→并入收尾修复 B）：`itertext()` 无块级分隔符，多块 xhtml 会拼成 `HelloWorld`（仅非 arXiv 多块文本受影响）。

## 收尾修复批量派发（Confucius）

- A：queue E47（`retry_on_timeout` 显式门控 + 默认不重试用例 + cwd 错误语义文档/用例）→ `fix: gate timeout retries behind an explicit manifest flag`。
- B：watch 块级文本空白规范化（多块 title/summary 断言）→ `fix: separate block-level text in watched feed titles`。
- 两个独立 commit；完成后 A 由 `Aquinas` 定向复评，B 由 `Ohm` 定向复评。

## milestones 修复定向复评：ADDRESSED

- `Archimedes` 复评 `68c7580`：**ADDRESSED**，无新 Critical/Important。三处关闭：区间含 target（T-3+submission-check→退 1 缺 `package_ready`；T-14+internal-review→退 1 缺 `review_cleared`）；T-7→internal-review/review_cleared；已越过的检查点不进 `due`。
- 强证据：独立枚举 conference/journal × 所有 current stage × 三个 checkpoint 共 **84 个场景**，`missing_gates` 与 `stages[current:target+1]` 完全一致，无重复无遗漏；两次 mutation 独立复现失败。
- 挂账确认：非法 mode→2 可接受（validate 另有 structured problem）；无行号定位可接受；T-14/T-7 映射同一 gate 是 stages.py 单 gate 粒度的已知限制。
- **新边界（已立修复 C）**：`deadline: 2027-05-01T00:00:00Z` → PyYAML datetime 绕过 `isinstance(value, date)`，比较时抛未捕获 `TypeError`；validate 返回 `[]` 漏报。
- 修复 C 已排入 `Confucius` 批次：只接受 `YYYY-MM-DD` 字符串或 null，datetime 一律非法（parse 抛具名 ValueError、validate 报 problem、CLI 退 2 非 traceback）；commit `fix: reject timestamp deadlines instead of crashing`；随后由 `Archimedes` 复评。

## cross_review 修复定向复评：ADDRESSED

- `Aquinas` 复评 `a0e1048`：**ADDRESSED**，无新 Critical/Important。stderr 三条记录路径统一 `_STDERR_LIMIT=4000` + `...[truncated]`；短 stderr 无标记；异常消息仍用 500 摘要；`check --out-dir` 贯通且默认路径不回归（`rg` 确认无其它硬编码 `reviews`）；E41 契约与 23 例全绿；两条判别力独立复现。
- 新 Minor（同类残留，已排修复 D）：malformed 的 `raw_last_message[:10000]` 仍是静默切片无标记 → 统一为带标记截断（上限参数化：stderr 4000 / raw 10000），补用例；commit `fix: mark truncated raw review output instead of slicing silently`；随后并入 `Aquinas` 的收尾核实。

## automation-review Task 5 评审：Request Changes（E48）

- 评审者 `Plato`：**Request Changes**，2 Important + 2 Minor。路径偏离（`automation/`）判定正确；e2e 真实性通过（真实文件树 + 多模块协作，断言具体到字段/退出码）；629 OK 复核一致；脚本路径与 venv 均真实存在；两处字段无产出源的实测证据齐（`MILESTONES_KEYS=['advisory','deadline','due','missing_gates','mode','problems']`）。
- **Important 1**：`stage-advance.md` 点名 `stage.current/gate/updated_at`，但模板只跑 `validate.py`（成功无 JSON）与 `milestones due`（无这三键）——字段没有产出源，九条规则第 9 条冲突。
- **Important 2**：`milestones` 的 sequential 模式每次把"下一建议动作"塞进 `due`，导致 `due` 永不为空；`deadline-check.md` 的静默条件 `due=[] 且 problems=[]` 在无 deadline 时永不成立 → **每次运行都通知**，违反 E45。

### Ruling E48 — 给阶段自动化真实数据源；sequential 不得占用 due

Ruling: (1) `milestones` 新增只读 `stage` 子命令，输出 `{"current","gate","updated_at"}` JSON（缺失/非法 → 2），作为 stage-advance 模板的点名数据源；(2) sequential 模式下 `due` 必须为空，下一建议动作移入 `advisory`（due 的语义 = 检查点到期）；(3) `stage-advance.md` 改为手动触发模板（不挂定时），README 同步；`deadline-check.md` 静默条件不变（现在 sequential 也成立）；(4) 根 README 目录表补 `automation/`；(5) 文档测试改为字段对齐断言（模板字段 ⊆ 真实工具输出键），不再用"任一字段出现"的正则。
理由: 第 9 条（点名的源必须存在）与 E45（静默必须可判定）都是本层的硬约束；"字段名写对一半"和"无 deadline 每次通知"都会让默认安静策略变成空话。
代价: sequential 的下一建议不再出现在 `due`（自动化需读 `advisory` 才提示）；stage-advance 明确为手动模板。

- 修复 E 已排入 `Confucius` 批次（在 A–D 之后），commit `fix: give stage automations a real data source and quiet sequential mode`；随后由 `Plato` 定向复评；milestones 的 sequential 语义变化由 `Archimedes` 做增量复评。

## 收尾修复批次 A–E 全部落地（`ec262e5`→`d2f8b50`）

- A `ec262e5` queue：`retry_on_timeout` 显式门控（默认 false；非布尔 → 2）+ 默认不重试用例 + bad-cwd 语义文档/用例。判别力：默认超时重试改回无条件 → `3 != 1`。
- B `ff7ecf2` watch：块级文本分隔（实施者修正题面公式为 `" ".join(" ".join(itertext()).split())`——朴素 `"".join` 仍会粘连）；判别力：`'HelloWorld' != 'Hello World'`。
- C `096f850` milestones：datetime deadline 一律非法（parse 具名 ValueError / validate problem / CLI 退 2 非 traceback）；判别力：恢复接受 → TypeError + ValueError not raised。
- D `b356fab` cross_review：raw_last_message 截断上限参数化 + `...[truncated]` 标记；判别力：改回静默切片 → `endswith` 断言失败。
- E `d2f8b50` milestones+docs：新增只读 `stage` 子命令（`current/gate/updated_at`）；sequential `due` 固定空、建议移 advisory；stage-advance 改手动模板；字段对齐测试；根 README 补 `automation/`。判别力：sequential 放回 due → 非空失败；stage 改名 → argparse invalid choice。
- 测试链：A 632 → B 634 → C 637 → D 639 → **E 644 tests OK**；工作树干净。
- 四路定向复评已派：`Aquinas`（A+D）、`Archimedes`（C + E 的 milestones 部分）、`Plato`（E 的文档与字段对齐部分）、`Ohm`（B）。全部通过后：automation-review 最终全分支评审（base `d3940f9`）。

## A–E 四路复评结果（全部 ADDRESSED）

- `Aquinas`（A+D）：ADDRESSED，无新问题。E47 分流清晰（`retry_on_timeout` 缺省=超时不重试，即便 max_attempts>1；非布尔 → ValueError → 2）；bad-cwd 记 failed 后整体退 2 有用例；raw 截断标记核实；独立复现两条判别力（`2 != 1`、`endswith` False）；全量 644 OK。
- `Archimedes`（C + E-milestones 增量）：ADDRESSED，无新 Critical/Important。datetime 三路径（parse ValueError / validate problem / CLI 退 2 无 traceback）核实；sequential `due=[]` + advisory；`stage` 键与 ccfa.yaml 完全一致；84 场景不变量无回归；只读 SHA-256 不变。两条可选 Minor：`stage` 不校验 gate 与 stages.py 一致（走 read-only 信任边界，挂账）；`updated_at` 接受 ISO 变体（如 `20261003`）（挂账）。
- `Plato`（E 文档）：ADDRESSED 4/4。字段对齐测试真实调用工具取键；判别力独立复现（sequential 放回 due 失败、`stage` 改名 argparse invalid choice、漂移键检测 False）。两条 Minor：字段对齐只做单向（→ 控制器当场修，见下）；`stage` gate 信任边界（挂账）。
- `Ohm`（B）：ADDRESSED，无新 Critical/Important；新 Minor：空白归一化粒度过粗（`Hello<b>World</b>` → `Hello World`、`AI<b>2</b>` → `AI 2`、内部空白折叠）——watch 面向 arXiv 纯文本，挂账，未来接非 arXiv feed 再收紧。

## 控制器直改（`ac6edfb`，终审覆盖）

- `automation/deadline-check.md` 读取字段补 `advisory`（Archimedes 发现的文档不一致）。
- `test_automation_e2e.py` 字段对齐改为**双向集合相等**：解析"读取字段"小节的 `^- \`字段\`` 得声明集，与实际工具输出键集合断言相等（模板塞假字段也会失败）；判别力实测（注入 `bogus` → 检出）。
- 全套 **644 tests OK**。

## automation-review 最终全分支评审已派

- 终审者 `Popper` = `01a10205-27a9-74f1-bfa3-8b84256d316b`，review-d3940f9..ac6edfb.diff（14 commits）；重点：跨工具契约一致性、E41–E48 全链路、E45 静默可判定、DoD（538→644，+106 ≥ +60）、真实 codex exec 冒烟如实标注"终审未复跑"、离线可测、新 Critical/Important/Minor。

## automation-review 终审：Needs fixes（E49）

- 终审者 `Popper`：**Needs fixes**，无 Critical，1 Important + 3 Minor。跨任务契约、E41–E48、E45 静默、DoD（644，+106）均核实通过；真实 codex exec 冒烟**未被终审复跑**（如实标注，代码路径支持该调用形态）。
- **Important（真集成缺陷）**：`queue run` 的默认 runner 让子进程继承 stdio，queue 自己的结果 JSON 又打到 stdout——被排队命令一旦打印 stdout，输出即 `子进程输出\n{json}`，`json.loads` 失败。实测复现 `stdout: 'CHILD_STDOUT_MARKER\n{"runs":...}'`。违反 §6.1.1"JSON 到 stdout"（直通例外只给了 `run-log run`），并直接破坏 `experiment-queue.md` 对 `runs/stopped` 的读取与 E45 静默判定。既有 `main` 测试全 mock `run_queue`，真实路径无覆盖——这是终审才暴露的测试盲区。
- Minor：队列项 `cwd` 未进 run-log（仍记 `"."`）；`weekly-watch`/`experiment-queue` 字段对齐仍单向；`cross_review check` 信任 `input_hashes` 键为相对路径，手改 `../` 会对外部文件做只读哈希（低危本地探针）。

### Ruling E49 — queue 的 stdout 必须可解析；子进程输出转 stderr

Ruling: `queue run` 捕获子进程 stdout/stderr（含超时时的部分输出）并**转发到本工具 stderr**；stdout 只保留结果 JSON；help/docstring 写明这一具名取舍（与 `run-log run` 的直通例外不同，因为 queue 是自动化消费方，`runs/stopped` 必须可 json.loads）。(2) 每次 attempt 的 `cwd` 经 `log_metrics` 写入 metrics；(3) watch/queue 模板字段对齐改双向集合相等；(4) `cross_review check` 对记录内 `input_hashes` 键做 `paper_root` 包含性校验，越界 → 结构化 problem（退 1）。
理由: 规则 6"包装器不得夺走被包裹命令的流"的意图是不要把子进程输出丢掉——转发到 stderr 仍可见；但自动化契约要求 stdout 可解析，二者在此处由 stderr 承载人读输出解决。真实子进程用例必须补，否则同类盲区还会复发。
代价: 子进程 stdout 不再出现在父进程 stdout（脚本若依赖管道需要改读 stderr）；换来自动化可解析性。

- 修复者 `Confucius`（resume），base `ac6edfb`；commit `fix: keep queue stdout parseable and harden review records`；随后由 `Popper` 定向复评并重下 merge verdict。

## Fix F（`a99a219`）与复评：原 Important 关闭，但引入 E50 两条新 Important

- F 落地：queue stdout 纯 JSON（子进程输出转 stderr，含超时部分输出）、`cross_review check` 路径包含性校验（`../`/绝对路径/符号链接逃逸 → `review-record-invalid` 退 1）、watch/queue 模板双向字段对齐；650 tests OK。
- `Popper` 复评：原 Important **确认关闭**（真实子进程用例：父 stdout 可 json.loads、marker 只在 stderr；超时部分输出有独立用例）；三条 Minor 中路径校验与字段对齐关闭；**但 cwd 修法引入两个新 Important**：

### Ruling E50 — cwd 必须进 run-log 规范字段；长任务输出必须流式

背景 1: F 把 `{"cwd": ...}` 写进 `metrics` 而规范 `cwd` 字段仍是 `"."`——既没有修好字段，又用非空 metrics 把 `check_runs` 的 `metrics-pending` 告警压掉（实测只剩 `run-log-missing-commit`）。这直接违反 E2"完成但指标为空必须报"，属于**用一个假修复掩盖了另一个真告警**。
背景 2: `capture_output=True` 把子进程全部输出缓冲到进程结束才转 stderr——长实验运行期零输出、内存无上限，违反 §9.2"长任务可观察"。
Ruling: (1) `run_log.run_command` 增加显式 `cwd` 参数（默认保留 `"."` 行为）并写入记录 `cwd` 字段；queue 传解析后的真实 cwd；queue 不再用 metrics 携带 cwd（非超时 attempt 的 metrics 保持原状，超时仍写 timeout 元数据）。(2) queue 默认 runner 改 `subprocess.Popen` + 逐行 pump 到父 stderr（stdout 仍纯 JSON；无缓冲驻留；超时 kill 并转发已产生输出）。
理由: "记录真实 cwd"必须落在规范字段上，否则就是装饰；指标告警是 E2 的核心，不得被任何写盘工具顺带压掉。长任务可观察是 §9.2 的硬要求，缓冲到结束等于把可观察性取消。
代价: 多一个 `Popen` + pump 线程的复杂度；测试需要"子进程结束前就能看到首批输出"的流式断言。

- 修复者 `Confucius`，base `a99a219`；commit `fix: record queue cwd in the run log and stream child output`；随后 `Popper` 定向复评并重下 merge verdict。

## E50 复评与 automation-review 结项

- 修复者 `Confucius`，commit `22f0921`，**653 tests OK**。判别力实测：旧行为下 `record["cwd"] == '.'`、`'run-log-metrics-pending' not found in ['run-log-missing-commit']`、`'FIRST' not found in ''`、`run_command() got an unexpected keyword argument 'cwd'`；超时部分输出用真实子进程（print 后 sleep 5s / timeout 1s）覆盖。
- 定向复评（`Popper`）：**ADDRESSED，Merge readiness = Ready**。实测 `record_cwd_field=<resolved>`、`record_metrics=None`、`problem_codes=['run-log-metrics-pending','run-log-missing-commit']`（与旧行为正好翻转）；流式 `FIRST` 在子进程退出前到达 stderr；`run_log run` 默认 cwd 行为不变；父 stdout 纯 JSON。
  - 残余 Minor（控制器当场处理）：流式测试原以 1.35s 墙钟对 1.5s sleep 竞争（0.15s 余量），改为 ready/go-ahead 文件同步的确定性写法（控制器 commit `f4e9608`，判别力实测：缓冲实现下 `FIRST not found in ''`；全套 653 OK）。该 commit 与「pump 线程在孙进程继承句柄时可能阻塞」的边角风险一并挂账，由模板阶段终审覆盖。
  automation-review: complete (commits d3940f9..f4e9608, review clean)

## 累计状态（automation-review 结项时）

- 十五个工具成形：前十一（含 library/memory）+ `milestones` / `cross_review` / `watch` / `queue`。测试从 125 增至 **653**；账本裁定 E1–E50。
- 四类自动化的确定性底座 + 接线文档（`automation/`）齐备；实际挂载 automations 需用户确认（E45），尚未挂载。
- 自动化阶段挂账（诚实清单）：真实 `codex exec` 冒烟未被终审复跑（账本+代码路径核实）；`check` 的 pump 孙进程句柄边角；watch 空白归一化粒度过粗；`milestones stage` 不校验 gate 与 stages.py 一致；`stage.updated_at` 接受 ISO 变体；`today == deadline` 无提示；T-14/T-7 共用同一 gate；非法 mode 退 2；problem 无行号。

## 模板阶段（templates-derivation）启动

- 计划：`<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-templates-derivation.md`（5 任务：递归复制 venue / 双 venue 真编译冒烟 / PS 包装器 / README+checklist 一致性 / 一站式集成回归）。
- 前置评估已完成（bensz：reference-only、零 vendor）；侦察发现真实缺口：139 个 venue 中 ACM/CVPR/ICCV/VLDB 含子目录，而 `create.py` 只复制顶层文件。
- Task 1（递归复制 + 失败清理 + 判别力）已派 `Confucius`，base `f4e9608`。

## templates-derivation Task 1 执行记录

- 实施者 `Confucius`，commit `b1f234b`，**659/659**（+6 用例）。改为 `shutil.copytree(..., dirs_exist_ok=True, copy_function=shutil.copy2)`；失败清理与既有契约不变；测试 patch `newpaper.venues.templates_root` 用注入的临时 venue。
- 判别力实测：旧实现下嵌套 `styles/x.sty` → `FileNotFoundError`；嵌套主文件 → "找不到包含 \documentclass 的 .tex 文件"；失败后重试仍缺文件。真实 venue 冒烟：CVPR 派生复制出 `sec/0_abstract.tex` 等嵌套文件。
- 评审者 `Popper`，review-f4e9608..b1f234b.diff，进行中。
- Task 2（双 venue 真编译冒烟）已派 `Confucius`，base `b1f234b`；要求如实报告编译失败（不许伪造/静默 skip）。

## templates Task 1 评审与 Task 2 执行记录

- Task 1 评审（`Popper`）：**Approved**，无 Critical/Important。真实 venue 独立复跑（CVPR 嵌套 `sec/*.tex` 复制成功）；判别力独立复现；两条 Minor：`papers/` 根为新建时的失败清理分支无自动化用例（评审手工验证 `papers_root_removed: True`，挂账并入 Task 5）、真实 venue 派生待 Task 2（已承接）。
- Task 2 实施者 `Confucius`，commit `19f085d`，**662 tests 含 1 failure**（诚实保留失败，未伪造/未 skip）。真实编译证据：
  - 引擎 MiKTeX-pdfTeX 4.23 / BibTeX 0.99e（MiKTeX 25.12）。
  - **NeurIPS 编译成功**：3×pdflatex 退 0（无 \bibdata 跳过 bibtex），PDF 177736 bytes。
  - **ACL 编译失败（上游模板缺件）**：首轮 pdflatex 退 0 且产出 PDF 167899 bytes，但 `bibtex acl_latex` 退 1——模板库只有 `acl.sty` + `acl_latex.tex`，缺 `acl_natbib.bst` 与 `custom.bib`（`kpsewhich` 无结果）。日志：`I couldn't open style file acl_natbib.bst` / `I couldn't open database file custom.bib`。
  - 派生工具链两项目均通过：validate 0、`milestones stage` current=idea、`due` sequential/due=[]/problems=[]、`memory check` 0、骨架齐全。
  - 判别力：把 copytree 改回顶层复制 → CVPR 用例 `递归复制缺失: manuscript/sec/1_intro.tex` 失败。

### Ruling E51 — latex_check 必须能检查 venue 真主文件；上游模板缺件如实钉住

背景 1: `latex_check` 硬编码 `manuscript/main.tex`，而真实 venue 主文件名是 `neurips_2026.tex` / `acl_latex.tex`（`ccfa.yaml.artifacts.manuscript` 也记录真名）——派生项目无法被检查，属产品缺陷。
背景 2: ACL 模板库缺 `acl_natbib.bst`/`custom.bib`，真实编译序列在 bibtex 中断。这是**上游模板库不完整**的事实，不是本工具的缺陷；必须如实钉住而不是伪造成功或静默 skip。
Ruling: (1) `latex_check` 新增 `--main <相对路径>`（默认 `main.tex`），缺文件/越界 → 2；(2) Task 2 e2e 改为：NeurIPS 断言真编译成功 + `latex_check --main neurips_2026.tex` 如实报出上游占位缺图（退 1 正确）；ACL 断言失败且指名缺 `acl_natbib.bst`，测试名与注释写明"上游补齐后该测试应失败并升级为完整编译断言"。
理由: 主文件名是派生项目的既有事实，检查器必须接受它；模板库缺件是环境事实，测试应把它钉成回归信号，而不是让它长期把套件留在红色或悄悄跳过。
代价: ACL 的"编译成功"证据暂时拿不到，挂账到模板库补齐（可能的修复路线：从 acl-org/acl-style-files 取 `acl_natbib.bst` 与 `custom.bib`）。

- 修复轮 G 已派 `Confucius`（base `19f085d`），commit `fix: let latex-check target the venue main file`；要求全量恢复 ≥665 OK。

## G 修复落地（`b4cd4eb`）

- 实施者 `Confucius`，commit `b4cd4eb`，**666 tests OK**（套件恢复绿色）。
- `latex_check --main <相对路径>`（默认 `main.tex`；绝对路径/`../`/缺失 → 2）；判别力实测：丢弃 main 参数 → `工具错误: 找不到主文件 ...\manuscript\main.tex`（`2 != 0`）。
- NeurIPS：真编译成功（177,736 bytes）**且** `latex_check --main neurips_2026.tex` 如实报 `missing-figure: myfile.pdf`（退 1 为正确行为，上游模板带占位缺件）。
- ACL：测试改名 `test_acl_upstream_template_is_missing_bibliography_assets`，断言模板目录缺 `acl_natbib.bst`/`custom.bib` 且 bibtex 输出含对应错误；注释写明"上游补齐后本测试应失败并升级为完整编译断言"。判别力实测：旧"必须编译成功"断言会因 `bibtex returncode=1` 失败。
- 评审者 `Popper`，review-b1f234b..b4cd4eb.diff（2 commits，含 Task 2+G），进行中。
- Task 3（PS 包装器）由新实施者 `Kierkegaard` = `01a10222-f601-7240-80b6-ba6656e1a0f4` 并行实施中（`scripts/` + `test_scripts.py`，未提交）。

## templates Task 2+G 评审已派；Task 3 执行记录

- Task 2+G 评审：`Popper`，review-b1f234b..b4cd4eb.diff（2 commits），进行中。
- Task 3 实施者 `Kierkegaard`，commit `e743fd8`，**704/704**（+38 用例）。17 个包装器：扫描发现 `validate.py` 也有 `main()`，额外加了 `validate.ps1`（否则清单一致性用例覆盖不全）。
  - 口径：`validate.py` 是非 argparse CLI，`validate.ps1 --help` 原样透传其既有行为（退 2、stderr 含 `--help`）；实施者未为它特判或改 Python CLI——评审判定是否可接受。
  - 判别力实测：删除 `research-version.ps1` 的 `exit $LASTEXITCODE` → 非零退出被吞（`0 == 0`，stderr 有 usage），用例失败。
  - 评审者 `Sagan the 2nd` = `01a10228-2057-7430-adf7-f5985d740a49`，review-b4cd4eb..e743fd8.diff，进行中（重点：一一对应、透传契约、真实执行、validate --help 的现状断言是否可接受）。
- Task 4（README 同步 + docs/checklist 一致性测试）已派 `Kierkegaard`，base `e743fd8`。

## Task 2+G 评审：Approved

- `Popper`：**Approved**，无 Critical/Important。独立复跑 NeurIPS 真派生+真编译（PDF 177736 bytes；`latex_check --compile --main` 退 1 是结构扫描报上游占位缺图，不是编译失败）；独立验证 `--main` 判别（默认 name 缺失 → 工具错误；显式 `venue-paper.tex` → 0 problems）；ACL 缺件钉住诚实（先断言缺文件，再断言 bibtex 输出含两资产名，docstring 写明上游补齐后应升级）。
- 两条 Minor（折入 Task 5）：e2e docstring 过期（仍称 latex_check 硬编码 main.tex）；`--compile --main` 真实引擎组合未进自动化。Task 1 的 `papers/` 根清理分支用例一并折入 Task 5（结转 C）。
- Task 5 已派 `Confucius`（一站式集成回归 + A/B/C 结转），base 以实际 HEAD 为准。

## templates Task 3/4/5 评审与收尾修复

- **Task 3（`e743fd8`，包装器）**：评审 `Sagan the 2nd`：**Approved**，1 Minor——`validate.ps1 --help` 被测试特判为退 2、弱断言。已修（`7600829`）：`validate.main` 增 `-h/--help`（stdout usage、退 0；其它行为不变），test_scripts 删除特判、统一断言 help 退 0 且含 usage；判别力实测去掉分支 → `2 != 0`；全量 **727 tests OK**。评审另独立验证：全部 wrapper 的 `--definitely-invalid` 都退 2（非零不吞）；`research-version.ps1 list --repo <tmp>` 与直接 CLI 输出一致。
- **Task 4（`c4c1a35`，README+docs 一致性）**：评审 `Popper`：**Approved**，2 Minor（checklist 字节比对按 checkout 换行自适应、不再钉死 LF；stage→command 速查只做子串存在性）。均挂账。README 工具表 16 模块 + newpaper 与 wrapper 一一对应；反引号路径存在性校验有判别力（独立注入不存在路径 → 失败）；venue 数 139 实测准确；"实际挂载需用户确认"未虚报。
- **Task 5（`da55cb6`，一站式 e2e + 结转 A/B/C）**：评审 `Sagan the 2nd`：**Approved**，2 Minor（checklist 尾部只有正向+不等；run_log 的 cwd 字段断言价值有限）。控制器收尾（`0adab5a`）：补两条反向排他断言（conference 不得含 `[major-revision]`、journal 不得含 `[camera-ready]`）；第二条挂账（stdout marker + exit_code 已证真实执行）。
  - 强证据：两个派生项目（真实 NeurIPS 模板、同 venue 不同 mode）；四条工具链从**仓库外 neutral cwd** 以子进程跑；library 2 字中文 `mode=like` 命中 `attention`（判别力独立复现 `'fts' != 'like'`）；路径级快照证明 `ccfa.yaml`/`references.bib` 字节不变、neutral cwd 无新文件；B 用真实 MiKTeX 跑 `latex_check --compile --main`（退 1 + PDF + `missing-figure: myfile.pdf`，2.6s）。

## 当前状态与下一步

- HEAD = `0adab5a`，工作树干净，**727 tests OK**（Sagan2 正在定向验证 `7600829`）。
- templates-derivation：Task 1–5 全部提交并 Approved；待 validate-help 验证 → 模板阶段最终全分支评审（base `f4e9608`）→ 全仓收口。
- 已知挂账（模板阶段）：ACL 上游模板缺 `acl_natbib.bst`/`custom.bib`（测试诚实钉住，模板库补齐后升级为编译成功断言）；bensz 零 vendor 的决定与字体许可提示；checklist 换行规范未钉死、stage→command 速查语义未结构化断言、run_log cwd 断言价值有限；`papers/` 根清理用例已补（Task 5 结转 C 关闭）。

## validate --help 定向验证

- `Sagan the 2nd` 复评 `7600829`：**ADDRESSED**，无新 Critical/Important/Minor。`validate.ps1 --help` 与 `python -m ccfa.validate --help` 均退 0 含 `usage`；退出码对照（valid=0 / bad-path=2 / no-arg=2 / problems=1）改动前后一致；`HELP_EXIT_CODES` 特判已不存在；独立复现判别力（删 help 分支 → `2 != 0`）。
- 残留说明（非本次问题）：`main` 的"发现问题→1"仍无直接单测（`validate_yaml` 语义已覆盖）。

## templates-derivation 最终全分支评审已派

- 终审者 `Schrodinger the 2nd` = `01a10239-7316-77a0-a3d8-0afea2695c00`，review-f4e9608..0adab5a.diff（8 commits）。
- 范围：§12 验收逐条映射、NeurIPS 真编译独立复跑、3 个 PS 包装器独立跑、ACL 诚实钉住判定、README 诚实性（automation 未挂载/bensz 零 vendor/139 venue）、DoD 653→727（+74）、挂账汇总、Merge readiness。

## templates-derivation 终审：Needs fixes（E52）

- 终审者 `Schrodinger the 2nd`：**Needs fixes**，无 Critical；工具代码、两条硬证据（NeurIPS 真编译 177736 bytes 独立复跑；4 个包装器抽验 + 6 个 `--definitely-invalid` 退 2）、诚实性（139 venue、零 vendor、automation 未挂载、ACL 诚实钉住）与 §12 22 条验收映射均通过；全量 727 OK 复核一致。
- **Important（README 可用性）**：README「常用命令」三条是无效命令，用户照抄退 2：
  1. `library.ps1 search --query ...` —— search 是位置参数，无 `--query`；
  2. `memory.ps1 check --paper-root ...` —— `--paper-root` 是顶层参数，必须在子命令前；
  3. `run-log.ps1 run --paper-root ... --log-dir ...` —— 两个都是顶层必需参数，须先于 `run`。
- Minor：`test_docs_consistency.py` 只做子串断言，完全抓不到命令无效（本次 Important 漏网）；`latex_check --main` 不带 `--compile` 时被静默忽略。

### Ruling E52 — 文档里的命令必须可执行；标志不得静默失效

Ruling: (1) 三条 README 命令改为真实 argv（顶层参数前置、位置参数不带 `--query`），并**实际跑通**留证；(2) `test_docs_consistency.py` 从 README「常用命令」块提取 `scripts/*.ps1` 行，替换占位后真实执行，断言 stderr 不得出现 `unrecognized arguments` / `the following arguments are required`（argparse 形状错误必须被测试抓住）；(3) `latex_check --main`（非默认）不配 `--compile` → 工具错误退 2，消息说明其仅在编译路径生效。
理由: README 是"一站式"入口，示例命令失效等于把用户直接挡在门外；文档测试只做子串存在性无法发现命令行形状错误。显式标志被静默忽略属"声明了却没发生"，与第 7 条同源。
代价: 文档里每条命令从此受测试约束（改 CLI 参数名会同时要求改 README，是意图）。

- 修复者 `Kierkegaard`（resume），base `0adab5a`；commit `fix: make the documented commands real`；随后 `Schrodinger the 2nd` 定向复评并重下 merge verdict。

## E52 修复与最终裁定（整个建设完成）

- `a3cc919` `fix: make the documented commands real`：README 三条命令改真实 argv 并实际跑通（library index/search、memory check、run-log run 均退 0）；`test_docs_consistency.py` 增「常用命令」fenced block 可执行性测试（解析 7 行、真实子进程执行、断言无 `unrecognized arguments`/`the following arguments are required`）；`latex_check` 非默认 `--main` 无 `--compile` → 退 2 而非静默忽略。判别力实测：`--query` → `unrecognized arguments: --query`；去掉 H3 检查 → `0 != 2`。
- `7a94af4` `test: scan the derived manuscript without a compile-only flag`：结构扫描调用移除 `--main`（结构扫描是全目录行为），保留退 1 + `missing-figure: myfile.pdf`；`--compile --main` 真实编译证据保留。全量 **729 tests OK**。
- 终审者 `Schrodinger the 2nd` 定向复评：**Merge readiness = Ready**，1 Important + 2 Minor 全部关闭，无新 Critical/Important/Minor。独立验证三种旧错误形状都会被 H2 拦截；H3 不误伤默认 `main.tex`；全量 729 OK；工作树干净。
  templates-derivation: complete (commits f4e9608..7a94af4, review clean)

## 项目总收口（2026-10-03）

- **三个新阶段全部完成**：knowledge-layer（`library` + `memory`，E33–E40）→ automation-review（`milestones`/`cross_review`/`watch`/`queue` + `automation/` 文档，E41–E50）→ templates-derivation（venue 递归派生 + 真编译冒烟 + 17 个 PS 包装器 + README/docs 一致性 + 一站式集成回归，E51–E52）。
- **交付物**：17 个确定性工具/入口（citation_guard / trace_claims / latex_check / final_check / provenance / run_log / repro_package / friction_log / research_version / library / memory / milestones / cross_review / watch / queue / validate / newpaper-create）+ 17 个 `scripts/*.ps1` 包装器 + `automation/` 四模板 + 根 README 一站式入口 + `checklists/` + `library/`。
- **测试**：从本日段起点的 125 → **729 tests OK**；全库 `tools/ccfa/` + `tools/newpaper/` + 测试。
- **真实外部证据（非 mock）**：MiKTeX 真编译（NeurIPS PDF 177,736 bytes；派生项目结构扫描如实报占位缺图）；真实 `codex exec` 冒烟（v4-pro，38.6s，verdict=blocking，schema 解析通过）；真实 venv 复现包重跑；真实 git 标签/diff 冒烟；真实 SQLite FTS5 三字/两字命中；17 个 PS 包装器真实 `--help`/`--definitely-invalid` 执行。
- **诚实挂账（未完成即写明）**：
  1. 四类自动化**底座与接线文档已交付，实际挂载 automations 需用户确认**（E45），尚未挂载；
  2. ACL 上游模板缺 `acl_natbib.bst`/`custom.bib`（测试诚实钉住，上游补齐后升级为编译成功断言）；
  3. bensz-paper/bensz-nsfc 评估结论为 reference-only、零代码 vendor；字体再分发许可未验证故未引入；
  4. 知识层：语义检索/PDF 全文/跨论文记忆聚合/claim 回写（E37）为明确 Non-goals；
  5. 小项：checklist 换行未钉死 LF、stage→command 速查未结构化断言、`run_log` cwd 断言价值有限、`milestones stage` 不校验 gate 与 stages.py 一致、`stage.updated_at` 接受 ISO 变体、`today == deadline` 无提示、T-14/T-7 共用 gate、problem 无行号、pump 孙进程句柄边角、watch 空白归一化粒度；
  6. 期刊 venue 未做真编译冒烟（状态/清单已验，LaTeX 真编译只覆盖 NeurIPS；ACL 因上游缺件无法完成）。
- **恢复入口**：本账本（E1–E52 全部裁定与代价）+ 设计文档 v6 + `outputs/plans/` 下 17 份计划 + `outputs/2026-10-03-bensz-reuse-evaluation.md`。

## 自动化挂载（用户确认后执行，2026-10-03）

用户以"继续"确认挂载后，按 `automation/README.md` 的流程执行：

- **新增源配置 `automation/watch-sources.json`**（commit `cfce45f`）：`{"version":1,"feeds":[],"state":"library/watch-state.json"}`；`feeds` 为空时周监控保持安静（不通知、不抓取）。`library/watch-state.json` 为派生游标，已加入 `.gitignore`。`automation/README.md` 与 `weekly-watch.md` 同步（模板改为读配置，不再写死 `<arxiv-feed-url>`）。改动后定向 61 例（automation_e2e + docs_consistency + scripts）OK。
- **已挂载（Codex automations，本地项目「科研」= `08e21f53-f6d8-4c54-98bb-a636f63e8a19`）**：
  1. `automation`「科研·投稿里程碑检查」：每日 09:00（cron），flash/low，cwd=仓库根；prompt 自定位 `papers/*/ccfa.yaml`，无项目即静默（NO_CHANGE），`due`/`problems` 非空才通知；只读。
  2. `automation-2`「科研·每周文献增量」：每周一 09:10（cron），flash/low，cwd=仓库根；prompt 读 `automation/watch-sources.json`，`feeds` 空即静默；新增才列 id/title/published，baseline 只报条数；如实报告网络/工具错误。
  - 两条均 `status = ACTIVE`、`target = project(科研)`；已通过 `$CODEX_HOME/automations/*/automation.toml` 逐字段核实（名称/rrule/model/effort/cwd/prompt）。
- **未挂载（按设计保持手动）**：`stage-advance`（手动触发模板，README 明示不挂定时任务）；`experiment-queue`（长任务运行期按需执行，无队列文件可挂）。
- **激活周监控的唯一动作**：把要跟踪的 arXiv Atom feed URL 填进 `automation/watch-sources.json` 的 `feeds`；在此之前该任务每周静默空跑。

## 遗漏审计（用户要求，2026-10-03）

对照设计 v6 与商品化标准做全量审计，确认四类遗漏（均有实证）：

**A. 设计写了未实现**：倒排只有 3/8 节点（缺 T-90/60/30/21/1，T-30 硬规则无执行点）；`ccfa.yaml` 只能读不能写回，§4.3 回退记录无字段无工具；§4.4 审稿矩阵只有种子行、7 列契约无检查器；§6.3 manifest 只验 2/4 问（`source_run_ids`/`source_data` 完全不校验，缺 generator/hash 静默通过）；§5 stage→技能路由依赖仓库外技能且"更新状态"缺写回工具；§7 COM/Overleaf/浏览器适配层大部分未建；§10 缺 `docs/`、派生项目缺 `experiments/design.md` 与 `figures/manifest.yaml` 种子。

**B. 有代码但真实环境未跑**：`library/refs.bib` 0 字节、无 `index.db`（只在 fixture 验证）；无真实论文项目；watch feeds 为空；自动化未经历真实定时运行；跨模型评审只有一次临时冒烟；期刊 venue 无真编译证据。

**C. 可移植性**：无依赖清单（venv 被 gitignore）；`.superpowers/` 全被忽略导致 E1–E52 账本不入库（本轮已复制进 `docs/`）；仓库无 remote、无 CI；无 LICENSE；README 无建 venv 说明。

**D. 已挂账小项**（见上文各阶段结项）。

### 商品化裁定 E53–E56（计划 `docs/plans/2026-10-03-productization.md`）

- **E53 state 写回必须显式授权且留痕**：`set-stage`/`rollback` 需 `--confirm`；`reason` 必填；`rollback` 只能往回且由调用者显式给出作废产物；写 `stage.history`（advance/rollback）。理由：§12 要求"可读和更新"，§4.3 要求回退留痕；§9 硬约束一要求修改需明确授权。代价：自动化推进 stage 时同样要带 `--confirm`（意图是让人/代理显式表态）。
- **E54 倒排补全 8 节点 + T-30 硬规则可检测**：节点映射 T-90→experiment-design、T-60→experiments-running、T-30→results-ready、T-21→writing、T-14/T-7→internal-review、T-3/T-1→submission-check；T-30 之后 `experiments/log` 出现新记录 → problem `t30-new-experiment`。理由：§4.5"T-30 之后不接受新实验是硬规则"，没有检测点等于没有规则。代价：误报面（补跑旧记录需人工判断），用 advisory/明细消息降低。
- **E55 交付图必须有完整溯源**：缺 generator/hash、缺 `source_run_ids`、run id 在 log 中不存在、`source_data` 缺失、`manual_edit: true` 无说明 → problem；`referenced_in` 仍按 §6.6 保持 advisory。理由：§6.3 硬规则 1"必须由脚本生成"当前无检查，硬规则 2"手工修图必须注明"无检查点。代价：历史 manifest 需要补齐字段（这正是目的）。
- **E56 审稿矩阵按 §4.4 七列校验**：表头/行形状/ID 唯一/两个枚举/不采纳须理由/承诺风险一致性；problem 带真实行号。理由：承诺风险列是 §4.4 的关键，没有检查器时它只是一句口号。

## 商品化执行记录

- **P0-c 已落地**（`dc5b4b0`）：设计 v6、17 份计划、E1–E52 账本、研究评估全部复制进 `docs/`（23 文件、632KB），根 README 指向仓库内副本；此文件自此为正式留档。
- **P0-a/b 已派** `Confucius`：`tools/requirements.txt`（4 个实测钉死版本）+ README「从零搭建」+ **全新临时 venv 只装该清单跑全量**的证据；commit `chore: pin the toolchain dependencies for a fresh clone`。
- **P1 Task 2 已派** `Kierkegaard`：`state.py` + `stage.history` + validate 兼容 + `scripts/state.ps1` + README 工具表；commit `feat: write paper stage transitions with an audit trail`。

## 商品化 P0/P1 实施记录（提交链 `8d0db77 → f2eb1e7 → c4bf4f3 → bd12001`）

- **P0 `8d0db77`**（`Confucius`）：`tools/requirements.txt` 钉死 `PyYAML==6.0.3 / bibtexparser==2.1.0 / pylatexenc==2.11 / pymupdf==1.28.2`（`pylatexenc` 是 bibtexparser 的硬依赖）；README 增「从零搭建」。**真实验证**：临时全新 venv 只装该清单 → 全量 `Ran 729 tests OK`（74.7s）；系统外部依赖（MiKTeX/git/PowerShell）照旧。包装器固定指向 `tools/.venv`，新克隆需先按 README 建 venv。
- **Task 4 `f2eb1e7`**（`Pasteur the 2nd`）：manifest 溯源补全（缺 generator/hash、缺/坏 `source_run_ids`、未知 run id、缺/坏 `source_data`、`manual_edit` 无说明 → problem；`referenced_in` 仍 advisory）。run id 约定核实为 `run_id` 字段 + `experiments/log/<run_id>.json`，复用 `run_log.record_path()`。判别力：generator 改回可选 → `0 != 1` 失败。
- **Task 3 `c4bf4f3`**（`Cicero the 2nd`）：倒排补全 8 节点（映射见 E54）+ T-30 硬规则（读 `run_id`/`started_at`，晚于 T-30 → `t30-new-experiment`；坏记录 → `t30-scan-skipped` advisory）。判别力：节点表回退 3 个 → `KeyError: 'T-30'`；去 T-30 扫描 → `StopIteration`。**连带待办**：countdown 报告新增 `advisories` 键，`automation/deadline-check.md` 未声明 → 记入 Task 6 文档同步（评审判定中）。
- **Task 2 `bd12001`**（`Kierkegaard`）：`state.py` 的 `set-stage`/`rollback`（`--confirm` 授权门、`--reason` 必填、方向校验、`stage.history` 追加、`gate` 与 stages.py 一致、原子写）；模板加 `stage.history: []`；validate 兼容旧文件并校验 history；`scripts/state.ps1` + README 工具表 + CLI 清单测试同步。判别力：删 confirm → `ValueError not raised`；放宽回退方向 → 两个 subtest 失败。
- 各任务完成后全量均 773 OK（含并行新增用例）；评审安排：P0 → `Kierkegaard`；Task 3 → `Pasteur the 2nd`；Task 4 → `Cicero the 2nd`；Task 2 → `Cicero the 2nd`（排在 Task 4 之后）。
- **Task 5 已派** `Confucius`：`revision_ledger.py`（§4.4 七列 + 承诺风险一致性 + 真实行号）+ 包装器 + README；commit `feat: check the revision ledger against its column contract`。

## 商品化评审与修复轮（2026-10-03 下半场）

**P0 复评（`Kierkegaard`，对 `8d0db77`）：Needs fixes（1 Important）**
- Important：README 把 `tools/.venv` / `tools/.venv/Scripts/python.exe` 放入反引号，`test_docs_consistency` 的路径存在性断言收集它们；`.gitignore` 忽略该目录 → **fresh clone 上该用例失败**（评审用 `git archive` 复现：`README 路径不存在: tools/.venv/Scripts/python.exe`）。当前绿只是因为本机有 venv。
- 其余通过：requirements 四项与 pip freeze 一致；`pylatexenc` 作为 bibtexparser 硬依赖的理由成立；`pip install --dry-run` 解析通过；README 命令与 3.12.14 实测一致；包装器固定 venv 的声明明确。
- 修复已排入 `Confucius`（Task 5 之后）：`test_docs_consistency.py` 对"生成型/gitignored 路径"显式豁免（至少 `tools/.venv`；用 `git archive` 找出其它同类缺失路径），并加"豁免不得变成什么都放过"的对抗用例 + 判别力实测（fresh archive 下无豁免必须失败）。commit `test: exempt generated paths from the README path check`。

**Task 4 复评（`Cicero the 2nd`，对 `f2eb1e7`）：Request Changes（4 Important + 1 Minor）**
1. `generator`/`generator_hash` 只做 falsy 检查：`[]`/`0` 等绕过整段哈希校验（实测 `problems=[]`）。
2. `manual_edit` 用 `is True`：YAML 常见 `"true"`/`1` 绕过"手工修图必须注明"硬规则。
3. `source_data` 不约束为 paper root 内相对路径：绝对路径与 `../` 越界指向真实文件时 `problems=[]`。
4. `source_run_ids` 成员无类型/包含性约束：`../outside-run` 搭配外部文件可绕过；对象成员报错分类不准。
5. Minor：新测试未覆盖上述类型/路径边界。
- 修复已派回 `Pasteur the 2nd`：类型与路径硬化（见上），commit `fix: reject type and path bypasses in figure provenance`。

**Task 2 复评（`Cicero the 2nd`，对 `bd12001`）：Request Changes（1 Important + 1 Minor）**
- Important：`set-stage` 只拒绝"等于当前"，**允许向后移动且写成 `kind: advance`**（实测 `writing → results-ready` 退 0），绕开 `rollback` 的 `void_artifacts` 审计并谎报方向——属"审计轨迹不实"（规则 7 同类）。
- Minor：history 校验不查方向/阶段合法性/日期（`writing → results-ready, kind=advance` 返回 `[]`）。
- 修复已派回 `Kierkegaard`：`set-stage` 严格要求 `target_index > current_index`；`history_problems` 加方向与合法性校验；commit `fix: keep stage advances strictly forward`。

## 商品化修复轮与验证结论（全部关闭）

| 任务 | 评审发现（Request Changes / Needs fixes） | 修复 commit | 复验 |
| --- | --- | --- | --- |
| P0 依赖清单 | `tools/.venv` 是 gitignored 生成路径，README 反引号引用导致 fresh clone 的 docs 测试失败 | `c3f2a52`（显式豁免前缀 + 3 条对抗用例） | `Kierkegaard`：ADDRESSED（fresh archive 14 例 OK；豁免未放宽——注入不存在路径仍失败） |
| Task 4 manifest | 4 条类型/路径绕过（非字符串 hash、非布尔 manual_edit、越界 source_data/run id） | `e73f00d` | `Confucius`：ADDRESSED；但复评另发现 3 条同类残留 → `f4a61f5`（generator/file 包含性、无 secondary code） |
| Task 4 硬化 | `generator`/`file` 可越出 paper_root（traceability 漏洞）+ 误导性 secondary problem | `f4a61f5` | `Cicero the 2nd`：ADDRESSED（越界且 hash/格式匹配也不放行；判别力两处 `0 != 1`） |
| Task 2 state | `set-stage` 允许向后移动并写成 `kind: advance`（绕开 rollback 审计） | `b864e2d` | `Cicero the 2nd`：ADDRESSED（向后 set-stage 退 2 且字节不变；伪造方向 history 报 `state-history-direction`） |
| Task 5 revision-ledger | 转义竖线 `\|` 被误拆列（合法输入 false positive）；ID 大小写口径未定 | `ea93cca`（未转义拆分 + `casefold` 判重 + `ledger-empty-id` + 缺分隔行） | `Cicero the 2nd`：ADDRESSED（四种探针全过；判别力 `ledger-row-shape ... 实际 8 列`） |
| Task 3 milestones | countdown `advisories` 未入模板、文档仍写 3 节点 | `b9b790d`（Task 6 内） | `Kierkegaard`（Task 6 评审）：Approved；独立删字段判别力、fresh checkout 12+10 例 OK |
| Task 6 收口 | —（e2e + 模板同步） | `0d07466` + `b9b790d` | `Kierkegaard`：**Approved，无 issue**（e2e 无 mock、断言具体到退码/字段/行号） |

## 商品化最终全分支评审（进行中）

- 终审者 `Bernoulli the 2nd`；范围 base `dc5b4b0` → head `f4a61f5`（14 commits，153,626 bytes）。
- 重点：fresh checkout 可复现（无 venv 跑 docs 测试）、state 授权与审计方向、8 节点 + T-30、manifest 类型/路径、revision-ledger 七列、DoD（729→818，+89）、新 CLI 包装器与集合断言、诚实挂账。

## 商品化结项（2026-10-03）

- 终审者 `Bernoulli the 2nd`：**Merge readiness = Ready**，无 Critical/Important。独立证据：全量 818 OK；`git archive f4a61f5`（无 venv、无 .git）下 docs 测试 14 例 OK；`pip install --dry-run` 解析四项钉死依赖；向后 set-stage 退 2 且字节不变；伪造方向 history 报 `state-history-direction`；manifest 越界 generator/source_data/run id 均被拦；revision-ledger 转义竖线不误拆、`C1`/`c1` 判重。
- 终审两条 Minor 处置：
  1. **根 README 速查仍是 3 节点**（`b9b790d` 漏了根 README）→ 控制器当场修：`87edf7a` 改成 8 节点，并新增 `test_every_countdown_node_is_named_in_readme`（节点列表**从 `milestones.checkpoints` 派生**、用数字边界避免 `T-1` 匹配 `T-14`）。判别力实测：修前 4 条失败（T-90/T-60/T-30/T-21 缺失），修后 docs 15 例 OK、全量 **819 OK**。
  2. `stage.history[].at` 只校验非空字符串、不校验日期 → **挂账**（信息字段、无授权/方向含义；与既有 `stage.updated_at` 不校验日期的口径一致）。
- 商品化阶段：commits `dc5b4b0..87edf7a`；测试 **729 → 819（+90）**；DoD（≥780、6 条判别力、全新 venv 证据、新 CLI 包装器与集合断言、E53–E56 入账）全部满足。
  productization: complete (review clean)

## 全项目挂账清单（商品化后，供后续决定）

1. 自动化：2 条 cron 已挂载（投稿里程碑每日、文献监控每周），但尚未经历真实定时触发；周监控 `feeds` 仍为空待用户填；`stage-advance`/`experiment-queue` 按设计保持手动。
2. 模板库：ACL 上游缺 `acl_natbib.bst`/`custom.bib`（测试诚实钉住）；期刊 venue 无真编译证据（NeurIPS 会议模板已真编译）。
3. 契约小项：`history[].at` 与 `stage.updated_at` 不校验日期；`milestones stage` 不校验 gate 与 stages.py 一致；T-14/T-7 共用同一 gate；`today == deadline` 无提示；problem 无行号（milestones）；checklist 换行未钉死文件规范；`run_log` cwd 断言价值有限；真实 `codex exec` 冒烟未被终审复跑。
4. 工程化：无远端仓库、无 CI、无 LICENSE（需用户决定私有/开源与托管位置）；venv 依赖清单已补齐并验证，但 `tools/.venv` 本身仍不入库（符合预期）。

## 论文工作台（workbench P0）启动（2026-10-04）

- 用户确认方向后，按建议开工"论文工作台"：**不做通用智能体平台**，做这套确定性工作流的桌面门面；智能体引擎（P1）与自定义 API 工具注册表（P2）后续接入。
- 计划：`docs/plans/2026-10-04-workbench-p0.md`（提交 `a5bedf0`）。技术选型实测依据：Node 24/npm 11 在（可选 Electron），Rust/cargo 与 .NET 不在（排除 Tauri/WPF 首版），Codex CLI 0.160 可用；选 **PySide6 + 独立 app venv**（单语言、直接 import 工具核心）。

### 裁定 E57–E59

- **E57 密钥只进凭据管理器**：`settings.json` 只存 `key_name` 引用；`KeyringSecretStore` 是唯一实现；`NoKeyringError` 上抛 `SecretStoreUnavailable`，**不降级明文**。理由：桌面软件一旦把 key 写进项目文件，就会随备份/同步外泄；这与本仓库"显式点名来源、不得静默"的底线同源。代价：无凭据后端的环境必须显式配置 keyring 后端。
- **E58 核心零 Qt、壳可替换**：`ccfa_core` 不 import PySide6；GUI 只做编排与展示；核心测试不依赖 Qt。理由：未来若换 Electron/Tauri 壳或做无头 CLI，核心不动；也让核心可以用现有 unittest 纪律测。代价：GUI 需要通过 core 的接口拿数据，短期多一层接口。
- **E59 GUI 验收用真实渲染**：offscreen 实例化 + `grab()` 出 PNG + 非空像素阈值 + 关键控件可见性/尺寸断言；截图字节写进报告。理由："能 import、能构造"证明不了界面存在；与前端/Three.js 场景同一原则。

## workbench P0 Task 1 已派

- 实施者 `Confucius`：`app/ccfa_core`（projects/settings/secrets/checks，零 Qt）+ `app/tests`（约 20 条）+ `app/requirements.txt`（PySide6/keyring 实测钉死）+ `app/README.md` + `.gitignore`；密钥红线（settings 不含 key、keyring 不可用不降级）与两条判别力实测；tools 侧 819 必须不动。commit `feat: add the workbench core for projects, settings and checks`。

## workbench P0 执行记录（`7b3fa93 → ba01d2c → b5d156b → ed02bf4`）

- **Task 1 `7b3fa93`**（`Confucius`）：`ccfa_core` 五个模块（projects/settings/secrets/checks）+ app 33 tests OK + tools 819 不动；钉死 `PySide6==6.11.2`、`keyring==25.7.0`、`PyYAML==6.0.3`（PyYAML 是 app 侧独立 venv 必需项）；判别力两条实测（save_settings 落 key、坏项不隔离）。
  - 复评（`Kierkegaard`）：**Needs fixes**。Important——`save_settings` 的 `key` 参数被 `del` 静默丢弃（调用方以为存了密钥），属"接口在撒谎"；Minor——E58 只是文本断言、README 硬编码机器绝对路径。
- **Task 1 修复 `b5d156b`**：删除 `key` 参数（传 key → `TypeError`）；落盘字段白名单逐字段断言；E58 换成真实 import 图测试（meta_path 阻断 PySide6，导核心模块 + 最小路径，断言 sys.modules 无 PySide6）；README 改 `py -3.12`、绝对路径降为示例。复评 **ADDRESSED**（判别力：恢复 key 参数 → `TypeError not raised`；故意 import → `blocked PySide6 import`）。
- **Task 2 `ba01d2c`**（`Confucius`）：PySide6 壳（项目列表含坏项标红、阶段面板、运行 validate/milestones、设置对话框、凭据状态栏）；offscreen 真实渲染，`SCREENSHOT_RATIO=0.7457`、PNG 7505 bytes；清空布局 → 非空像素断言失败（判别力）。评审 `Kierkegaard`：**Approved**，独立复跑同比例/字节，对抗验证（坏项与好项并存、keyring 不可用时对话框报错不写盘）全过。
- **Task 3 `ed02bf4`**（`Confucius`）：`test_workbench_e2e.py`（7 条，真实 NeurIPS 派生 + 真实 offscreen + 真实 validate/milestones + 密钥路径字节断言）；README 加「论文工作台（P0）」小节并如实标注边界（聊天/自定义 API 工具/安装包未接入）。app 53 tests OK；tools 819 不动；判别力：坏项跳过 → e2e 失败。
- 待办：Task 3 评审（`Kierkegaard`）→ workbench P0 最终全分支评审（base `8747928`）。

## workbench P0 结项准备（Task 3 评审 + 控制器收尾）

- Task 3 评审（`Kierkegaard`）：**Approved**（1 条 Minor：README P0 小节不自包含——缺建 venv/装依赖/offscreen 说明）。独立证据：e2e 7 例 OK、GUI 12 例 OK、`SCREENSHOT_RATIO=0.7457/BYTES=7505`、清空布局判别力 `CLEARED_RATIO=0.0001`、坏项跳过判别力 `project bad not found`、app 53 OK、tools 819 OK。同轮第二节复验 Task 1 修复 **ADDRESSED**。
- 控制器收尾（`7e95e98`）：README「论文工作台（P0）」补建 venv（`py -3.12`）+ `app/requirements.txt` + 启动 + headless `QT_QPA_PLATFORM=offscreen` 说明；`GENERATED_README_PATH_PREFIXES` 增加 `app/.venv`（前缀严格、`app/.venv-other` 不豁免）并同步对抗断言。**fresh checkout 验证**：`git archive 7e95e98` 解到临时目录（无任何 venv）跑 `test_docs_consistency` → 15 tests OK。
- 终态：app **53 tests OK**、tools **819 tests OK**；工作树干净。
- 最终全分支评审：新派 `Poincare the 2nd`，review-8747928..7e95e98.diff（6 commits）；重点 E57 字节级密钥红线、E58 import 图、E59 独立复跑截图、集成与 DoD、fresh checkout。

## workbench P0 终审：Merge readiness = Ready

- 终审者 `Poincare the 2nd`：**Ready**，无 Critical/Important。独立证据：
  - E57：自造 `sk-INDEP-FAKE-KEY-...` 走 GUI 保存 → `settings.json` 无 key、无 key 字段；`save_settings(key=...)` → `TypeError`；注入 `NoKeyringError` → `SecretStoreUnavailable` 且消息含"未降级为明文存储"。
  - E58：`ccfa_core` 零 PySide6；独立 meta_path 阻断下导入核心 + 最小路径通过，`PY_SIDE6_LOADED=[]`。
  - E59：独立复跑截图 `INDEP_SCREENSHOT_RATIO=0.8464 / BYTES=5575`（与套件 0.7457/7505 差异因 fixture 不同，属预期）；清空中央控件 → `CLEARED_RATIO=0.0001` 断言失败。
  - 集成：坏项标红 `#ff0000` + tooltip、好项正常；validate/milestones 真跑；凭据状态两态。
  - DoD：app 53 OK、tools 819 OK；fresh checkout（`git archive 7e95e98`，无 venv）docs 测试 15 OK。
- 终审 Minor 处置：
  1. **要修**：`settings_dialog.save()` 改名 + 留空 key 时凭据失联（旧 key_name 被换掉）→ 修复轮 `fix: keep provider credentials linked across renames`（改名且留空 key 时沿用旧 key_name；补两条用例 + 判别力），交 `Confucius` 实施、`Kierkegaard` 验证。
  2. `app/README.md` 本机绝对路径示例 → 同一修复轮内改成通用占位。
- 终审残余风险（挂账）：真实 Windows 凭据管理器后端未做端到端（用注入 fake）；keyring 非 `NoKeyringError` 异常会外抛（未覆盖异常面）；像素阈值 0.02 对"部分清空"不敏感；app venv 依赖随接入模块增加需补充；打包与聊天/工具注册表按 P0 边界未实现。

## workbench P0 结项（2026-10-04）

- 终审 Minor 修复 `e79164e`（`fix: keep provider credentials linked across renames`）：改名 + 留空 key 时沿用旧 `key_name`（凭据不失联、状态保持"已配置"）；改名 + 新 key 走新名称（旧条目保留不删，最小无损）；`app/README.md` 去掉具体用户路径。
- 定向验证（`Poincare the 2nd`，即终审发现者）：**ADDRESSED**，无新 Critical/Important/Minor。独立走 GUI：`RENAME_BLANK_KEY_NAME=old`、`STATUS_IS_CONFIGURED=True`、旧凭据可取、新名下无值、白名单字段成立、settings 字节无 key 明文；判别力（改回旧实现）如预期失败。
- 终态：app **55 tests OK**、tools **819 tests OK**；HEAD `e79164e`；工作树干净。
  workbench P0: complete (commits 8747928..e79164e, review clean)

## 工作台路线与挂账（P0 后）

- **P1（下一步）**：智能体聊天面板 + 引擎适配器（OpenAI 兼容 HTTP 为主、`codex exec` 为可选）+ 六个核心工具的工具桥（milestones/state/library/memory/run-log/trace-claims）。
- **P2**：自定义 API 工具注册表（HTTP 工具声明式接入 → 校验 → 注册 → 调用审计；Python handler 默认关闭、需显式授权与沙箱）。
- **P3**：PyInstaller + Inno Setup 安装包、代码签名、更新与许可合规（含 codex CLI 再分发条款核实；对外售卖建议以 BYO API 为主）。
- 工作台挂账：真实 Windows 凭据管理器未做 E2E（注入 fake 已覆盖契约）；keyring 非 `NoKeyringError` 异常面未覆盖；像素阈值对"部分清空"不敏感；改名换 key 时旧 keyring 条目保留（设计选择，后续可显式清理）。

## Ruling E60 — 工作台定位为个人自用，不做对外分发

用户决定：**不售卖、自己用**。影响：
1. **引擎选型放宽**：`codex exec` 可作为一等引擎（无需商业再分发适配），OpenAI 兼容 HTTP 作为 BYO API 引擎并行存在；P3 的"许可合规/代码签名"降级为可选（自用可只做本地安装或直接运行）。
2. **保留的工程约束**（对自己也是保护）：密钥只进凭据管理器、settings 不落 key、写操作显式确认、工具调用留审计——这些不改。
3. **优先级调整**：P1 先做"能聊天"的最短路径（引擎 + 聊天面板），再做工具桥（HTTP 引擎的自定义 API 工具接入）；因为自用场景下 `codex exec` 本身已能调用仓库脚本。

## workbench P1 执行记录（`6fb7d2a → 9da1fdc → fb8a310 → 55b10a6 → 191cd54 → b9bb540 → fb20f77`）

- **Task 1 引擎适配器 `6fb7d2a`**（`Confucius`）：`ccfa_core/engines/`（base/openai_compat/codex_exec）+ 26 用例；httpx==0.28.1 钉死；app 81、tools 819。判别力：非 2xx 改返回空、去 key 校验。
  - 复评（`Kierkegaard`）**Needs fixes**：Important——`SecretStore.get()` 异常文本被拼进错误消息（对抗注入 `RuntimeError(KEY)` 实测 key 泄露）；Minor——片段 514>500；Minor——HTTP 取消只在请求边界。
- **引擎修复 `55b10a6`**：store 异常只带类型名（补字节级红线用例）；片段含 marker 总长 ≤500；HTTP 取消语义写进 docstring+README 并补边界用例。复评 **ADDRESSED**（判别力：恢复 `{exc}` → 红线用例失败；`514 not less than or equal to 500`）。
- **Task 2 聊天面板 `9da1fdc`**（`Confucius`）：后台线程 + 四个 Qt 信号回主线程；停止/错误回填/引擎切换/未配置 provider 不调引擎；截图 `0.8341/3819`；判别力：主线程直调 → 0.609s > 0.1s 阻塞断言失败。评审 **Approved**（无 issue，独立复跑截图与阻塞判别力）。
- **Task 3 工具桥 `fb8a310`**（`Confucius`）：10 个工具（read/write 分级；write 需确认；拒绝 → `user-declined`）；tool_calls 循环上限 6；`agent-tools.jsonl` 审计只存 digest；`run-log run` 未暴露。判别力：write 自动执行、去轮数上限。
  - 自曝+复评发现 **Important**：`library_search` 指向项目级 `library/`（共享库在仓库根）→ 真实项目恒 `tool-error`；Minor：bridge 复用私有 `_stage_report`。
- **Task 3 修复 `fb20f77`**：`ToolBridge` 显式 `library_dir`（window → panel → bridge 透传 `<repo>/library`）；`milestones.stage_report` 公开化并被 CLI/bridge 共用；新增真实共享库命中、未配置结构化错误、e2e 传递链断言、tools 公开入口一致性用例。判别力：改回项目级路径 → `ok False`；去公开包装 → `ImportError: cannot find stage_report`。app 139、tools 820。定向验证（`Kierkegaard`）待回报。
- **Task 4 e2e `191cd54`**（`Confucius`）：`test_chat_e2e.py`（真实派生 + 工具调用 + 审计 + 写确认拒绝/同意 + 截图 0.7577/7510）；判别力：去审计写入 → e2e 失败。**实施者自曝真线程缺陷**：生产路径写确认会从 worker 线程弹 `QMessageBox`（Qt 控件只能在 GUI 线程）。
- **线程修复 `b9bb540`**：写确认经 `write_confirmation_requested` 信号回 GUI 线程（worker 阻塞等待、300s 上限、停止可中止）；e2e 改为 worker 线程执行工具以覆盖生产路径；线程 id 证据 `CONFIRM_THREAD_ID=7520 GUI_THREAD_ID=7520`；判别力：worker 直弹 → `confirmation ran off the GUI thread`。app 135、tools 819。

## workbench P1 待办

- `Kierkegaard` 定向验证 `fb20f77`（进行中）→ P1 最终全分支评审（base `d4c4bee`，新评审者）→ 账本结项、README/边界复核。

## P1 定向验证与终审修复（结局）

- `fb20f77` 定向验证（`Kierkegaard`）：**ADDRESSED**。传递链 window→panel→bridge→`ToolContext.library_dir` 核实无隐式猜路径；判别力独立复现（改回项目级 → `test_library_search_uses_the_explicit_shared_library` `ok False`）；app 139 / tools 820。
- P1 终审（新派 `Ramanujan the 2nd`，review-d4c4bee..4dbda14.diff）：**Needs fixes**，1 Important + 2 Minor：
  1. **Important（红线跨任务不一致）**：`chat_panel.refresh_status/_prepare_engine` 的 `except Exception as exc: hint=f"无法读取凭据: {exc}"` 会把 store 异常文本（可含 key）显示到界面；引擎侧已去 secret 化，面板漏了。对抗复现 `LEAKED=True`。
  2. Minor：`library_search` 描述仍写 `project/library/index.db`（实现已用共享库）。
  3. Minor（可接受偏离）：tools 测试 819→820（公开 `stage_report` 新增一致性用例），无行为变更。
- 其余全部核实通过：E60 一等 codex 引擎（argv/stdin/超时/取消）；密钥红线四条路径字节断言；工具桥风险模型（10 工具、write 确认、`user-declined`、`run-log run` 未暴露、轮数 6、审计只存 digest）；后台线程 + GUI 线程确认（线程 id 相等）；offscreen 独立复跑 `0.7427/6935`；`git clone` fresh checkout app 139 / tools 820 全绿；README 边界与实现一致。
- 修复 `59c2210`：面板两处只回显异常类型名（补对抗用例，两条路径字节断言）；`library_search` 描述改为共享库并加断言。判别力：恢复 `{exc}` → `'sk-CHAT-LEAK-9999' unexpectedly found in '无法读取凭据: sk-CHAT-LEAK-9999'`。app 140 / tools 820。
- `Ramanujan the 2nd` 定向复评（进行中）→ 通过后 P1 结项。

## workbench P1 结项（2026-10-04）

- 终审修复 `59c2210` 复评：**ADDRESSED / Merge readiness = Ready**。独立换新假 key 复现两条面板路径均不泄露；判别力 `sk-CHAT-LEAK-9999` 重现；app 140 / tools 820。
- 终审遗留两条 Minor 也已关闭（`cdaba2e`）：
  1. `SecretStoreUnavailable` 两条分支不再拼接 `str(exc)`（与引擎口径统一；对抗 SSU 含假 key 的两路径字节断言；判别力两 subtest 失败原文留档）。
  2. `test_codex_engine_does_not_require_provider` 等待条件补齐为 `len(engine.calls)==1 and panel._thread is None`，竞态消除。
  - 复评（`Ramanujan the 2nd`）：**ADDRESSED / Ready**，app 全量连续 3 次 `Ran 141 tests OK`（无 flake），新假 key 对抗复现无泄露，无新问题。
- 终态：app **141 tests OK**、tools **820 tests OK**；代码 HEAD `cdaba2e`（其后仅账本文档提交）。P1 交付：两个引擎（OpenAI 兼容 HTTP + `codex exec`）、聊天面板（后台线程/停止/错误回填/引擎切换）、10 个工具的桥（read/write 分级、GUI 线程写确认、`user-declined`、`run-log run` 未暴露、digest 审计、轮数上限）、聊天 e2e（截图 `0.7577/7510`）。
  workbench P1: complete (commits d4c4bee..cdaba2e, review clean)

## 工作台后续（P2/P3，供参考）

- **P2**：自定义 API 工具注册表（HTTP 工具声明式接入 → 校验 → 注册 → 审计；Python handler 默认关闭、显式授权 + 沙箱）。
- **P3（自用可选）**：PyInstaller + 安装包/快捷方式；自用不需要代码签名与许可合规（E60）。
- 挂账：真实 Windows 凭据管理器 E2E、真实 provider 联调与真实 `codex exec` 冒烟未做；HTTP 取消为边界式；流式输出未做；`window._update_credential_status` 对非 `SecretStoreUnavailable` 异常仍会外抛。
- 注：工作树中 `tools/ccfa/cross_review.py`、`tools/tests/test_cross_review.py` 与未跟踪 `submission/` 属**另一并行任务（Ampere）**的改动，本阶段未触碰、未纳入任何提交。

## 用户审计与 P0 修复立项（2026-10-04，evidence-integrity）

用户对整套工作流做了深度审计（"工程设计强于它保证的真相"）。控制器逐条核对，关键指控**属实**：
- `papers/example-paper` 不是独立仓库：`git -C papers/example-paper rev-parse --show-toplevel` → 模板仓库根；示例 run-log 记录 `git_commit=4dbda14918c9…`（模板仓库 commit，**不含论文文件**）；`git_dirty=false` 却照常通过 check。
- `doi_lookup.lookup` 丢弃响应体（`status, _body = fetcher(...)`），200 即 `found=True`；`cross_review.DEFAULT_MODEL = deepseek-v4-pro` 且 `_SAME_FAMILY_MODELS` 含两侧模型（默认同族）；`datavalue.implied_rounding_tolerance` 按 claimed 小数位放宽（写粗更容易过）。
- 示例论文 59 处 `\dataval`，同时 final-check 报出数十条 `untagged-number` advisory（advisory 不改退出码）；`submission/checks.md` 却写"All headline counts … are bound"——声明超出证据。根目录另有一份未跟踪的 `submission/` 误拷贝。

### 裁定 E61–E63（计划 `docs/plans/2026-10-04-evidence-integrity.md`）

- **E61**：每篇论文 = 独立 git 仓库（`papers/<slug>` 内 `git init` + 首提交 + 论文级 .gitignore）；模板仓库继续忽略 `/papers/`；**任何论文 git 操作必须验证 toplevel == 论文根，绝不允许回退父仓库**（research-version 拒绝；run-log 记 `git_repo:"foreign"`、`git_commit:null`）。理由：现有中间态让"版本/快照/可复现"全部空转，是最严重的结构性问题。代价：`create.py` 多一步 git init/提交；迁移既有论文需一次性操作。
- **E62**：`\dataval` 目标 = **受保护区**（摘要/贡献列表/结果主叙事）的关键数字；受保护区未绑定且未豁免 → **problem**；豁免进 `data/claims.yaml` 逐条留痕；`checks.md` 的覆盖率声明由工具生成，禁止手写。理由：advisory 永不改退出码 + 段落式声明 = 不可审计；覆盖标准不定义就永远靠拍板。代价：模板需要 `claims.yaml` 与策略扫描逻辑，历史论文会立刻暴露未绑定数字（这正是意图）。
- **E63**：gate 的"已核验"必须绑定外部证据——DOI 核验读响应体、记录 body sha256/retrieved_at/matched_title 并校验 DOI 与标题；无 evidence 的 `verified` 台账条目 → problem；cross-review 的每条 blocking 必须携带**在输入文件中可逐字命中**的引文（否则 `review-uncited-blocking`）；run-log 的 `purpose` 降为 `declared_purpose` 并明示不构成证据，gate 改用可查事实（metrics-pending、repro verify 记录）。理由：把"文件自称已核验即可通过"换成"可交叉验证"。

## evidence-integrity 执行状态

- Task 1（论文独立仓库 + 防父仓库逃逸 + 示例论文迁移）已派 `Confucius`，base `b4bfec6`；Task 2（受保护区覆盖率）/Task 3（去自证）/Task 4（迁移与收口）随后。
- 未跟踪根目录 `submission/`：与论文内 `submission/` 比对后按用户确认处理，本阶段不擅自删除。

### 根目录 `submission/` 误拷贝处理（已解决）

- 比对证据：根目录副本 11 个文件，其中 10 个与论文内 `submission/repro/` 对应文件**字节一致**，仅 `MANIFEST.json` 不同（根 `created_at=2026-10-03T18:34:37Z`，论文内 `19:23:20Z`，后者是超集）。
- 处置：**不删除**，非破坏性归档到 `papers/example-paper/ccfa-workfiles/archive/repro-bundle-20261003T1834/`；模板仓库根目录不再有游离 `submission/`。由论文仓库（迁移后）自行决定保留或丢弃。

### 用户对 P1 方向的口头确认

- 用户以"嗯嗯"回应"P0 之后紧接着做长任务安全（沙箱/GPU 预算/看门狗）与跨族评审"的提议：按**同意**处理，两项列入 evidence-integrity 之后的下一计划（长任务安全为最高优先）。

## evidence-integrity 执行记录（Task 1a/2）

- **Task 1a `a0531ee`**（`Confucius`）：`create.py` 自动 `git init` + 论文级 `.gitignore`（`*.pdf` 默认忽略，`submission/**` 与 `manuscript/figs/**` 保留）+ `git add -A` + 首提交（身份缺失仅命令级 `-c` fallback，不写全局）；`research_version` 三个子命令开头 `assert_own_repository`（toplevel realpath 必须等于论文根，无后门）；迁移文档落 `docs/migrations/migrate-paper-to-git.md`。评审（`Kierkegaard`，干净 worktree 833 tests OK）**Approved**，1 Minor：`assert_own_repository` 有一段不可达重复实现。
- **Task 1a 清理 `6241b6f`**：纯删除 14 行不可达块，行为不变；`test_research_version` 21 条 OK。
- **Task 2 `11239ad`**（`Meitner the 2nd`）：`claims_policy.py`（受保护区识别、`protected-untagged-number` problem、`waived-number` advisory 含理由、坏 waiver 报行号不中断、无 policy → `claims-policy-missing` advisory）+ `final_check` 接入 + `claims_coverage_report` 原子写 `submission/claims-coverage.json/.md` + `create.py` seed `data/claims.yaml` 并把 `checks.md` 声明改成指向机器报告。判别力实测：受保护区改回 advisory → `protected-untagged-number` 用例失败。
  - **对示例论文的真实数字**（机制立刻命中了审计预言）：`tags=62, protected_total=8, bound=7, unbound=1`；唯一未绑定项 = `manuscript/main.tex:58` 的 `Coding 43`（摘要 "systematizes 43 works"）。口径说明：用户审计计 56/59 处标记，当前 HEAD 实测 62，属计数口径差异（`find_untagged` 逐行候选 vs 其它口径），已记录。
  - 待办：Task 2 评审（`Kierkegaard`，干净 worktree）。
- **Task 3 拆分**：3a（DOI/引用证据；不等 Ampere）本次派发；3b（cross-review 引文 + run-log `declared_purpose`/gate 证据化）待 Ampere 的 `cross_review.py`/`run_log.py`/`milestones.py` 落地后派。

## evidence-integrity 执行记录（Task 2 评审 + Task 3a）

- **Task 2 评审（`Kierkegaard`）**：**Approved**（3 Minor，无 Critical/Important）。干净 worktree（detached `11239ad` + 挂现有 venv）工具全量 **853 OK**；判别力独立复现（受保护区改回 advisory → `protected-untagged-number` 用例失败）。
  - 示例论文独立复跑（复制到临时目录 + 默认 policy）：`tags=62, protected_total=8, bound=7, waived=0, unbound=1`；未绑定 = `main.tex:58` 的 `Coding 43`——与实施者一致。旧示例论文尚未迁移 policy/checks（Task 4 范围）。
  - 3 条 Minor：① 未知 `protected_sections` 名被静默接受（拼错节名 → 该节静默退化为 advisory）；② waiver 的 `line_text` 只归一化空白、不归一化大小写；③ 同一 waiver 命中同文件多处时全部豁免（契约允许但不可见）。
  - 修复已改派 `Confucius`（原实施者线程失效）：未知节名 → problem `claims-policy-unknown-section`；waiver 匹配 `casefold`；`waived-number` 消息标注"命中 N 处"并在模板/报告写明可选 `line` 字段。commit `fix: make claims policy failures and waivers visible`。
- **Task 3a `4118590`**（`Confucius`）：`doi_lookup` 读响应体——Crossref `message.DOI`/`title`、DataCite `data.attributes.doi`/`titles`；归一化 DOI 必须等于请求（否则 `doi mismatch`）；`expected_title` 相似度 <0.9 → `title mismatch`（NFKC+casefold、去标点、折叠空白、SequenceMatcher）；成功携带 `LookupEvidence(body_sha256="sha256:<64hex>", retrieved_at, matched_title, source)`；`LookupResult.evidence` 默认 `None` 保持向后兼容。`citation_ledger` 新增 `LedgerEvidence` + 证据校验（缺失/非法不崩、记 `evidence`/`evidence_error`）+ `save_ledger` 原子写；`citation_guard` 对无有效证据的 `verified` 报 `citation-self-asserted`（离线同样，退 1），`--verify-online` 写 evidence 或 failed。判别力：只看 200 → `test_doi_mismatch_is_not_found` 失败；去 evidence 校验 → `citation-self-asserted` 用例失败。工具全量 874（含 Ampere 并行用例）。
  - 评审已派 `Kierkegaard`（review-e709fe8..4118590.diff，干净 worktree）。
- **插曲（"没有反应"）**：Task 2 评审与 Task 3a 实际都已完成，但完成通知未送达/被截断；控制器通过 `read_thread` 取回了完整结论。流程改进口径：**长时间等待改用 read_thread 主动取证，而不是只等通知**。

## evidence-integrity 执行记录（Task 2 修复 + Task 3a 评审）

- **Task 2 Minor 修复 `331eb88`**（`Confucius` 接手，原实施者线程失效）：未知受保护区名 → problem `claims-policy-unknown-section`（退 1）；waiver 匹配加 `casefold`；真正实现可选 `line` 字段（`(file, line_text, line)` 三者参与匹配），`waived-number` 消息含"命中 N 处"，模板与报告写明用法。判别力：禁用未知节检查 → 两条用例失败（`claims-policy-unknown-section` not found / CLI 0 != 1）。tools 全量 883（含并行未提交改动的用例）。
- **Task 3a 评审（`Kierkegaard`，干净 worktree `4118590`）**：**Needs fixes**，1 Important + 2 Minor。
  - **I1（Important）**：bib 无 title + 提供方 200 但无可用标题时，`lookup` 产出 `matched_title=None` 并写进台账，而读侧要求非空 → 工具自己写的台账下次只读必报 `citation-self-asserted`，且重跑不收敛（实测 `verify 0 → read 1 → reverify 0 → read 1`）。
  - I2（Minor）：`body_sha256` 哈希的是**解码后字符串**而非原始字节，且只存摘要不存响应体 → 摘要离线不可复算（翻转 1 位 hex 检测不到）；建议至少改为原始字节哈希并如实声明边界。
  - I3（Minor）：缺"真实 lookup → 写账 → 只读检查归零"的往返用例与 0.9 相似度边界用例（评审实测边界行为本身正确：0.8929→mismatch，0.9091→found）。
  - 其余全部通过：DOI 归一/变体、expected_title=None 语义、坏 JSON 双源、evidence 校验、原子写、只读失败退 2、help 如实、key 哨兵不入台账、二次核验幂等；判别力两条独立复现。
  - 修复已派 `Confucius`：无可用标题 → `found=False, detail="title missing"`（保证写读收敛）；补真实往返 + 边界用例；证据哈希改原始字节并写清防伪造边界。commit `fix: never write evidence the ledger reader rejects`。
- **更正：并行未提交改动的归属**。控制器核对 `read_thread`：`Ampere`（01a1015b）是 2026-10-03 run-log Part B 的**旧评审者**（已 completed、只读），并非工作树中 `run_log.py`/`milestones.py`/`cross_review.py` 未提交改动的作者。该批改动来自**另一个未知会话**；Task 1b（run-log git 身份）与 Task 3b（cross-review 引文 / declared_purpose / gate 证据化）在其归属澄清前保持不触碰。

## 在途改动纳入（用户授权，2026-10-04）

- 用户选择"授权接管并纳入"。控制器先跑全量确认自洽（**891 tests OK**），再按语义分三笔纳入：
  1. `b06913a feat: mark run purpose and exempt build runs from the T-30 freeze`：run-log 新增 `purpose=experiment|build`（校验 + CLI `--purpose`），T-30 扫描跳过声明为 build 的运行。
  2. `975fb61 fix: stop the review prompt from treating its own absence as blocking`：internal-review 的 prompt 明确"本次运行就是在生成评审报告"，不再把"记录不存在/历史 blocking"本身判为 blocking（对应用户审计里的循环自指）。
  3. `c9b9694 docs: add the research workflow introduction`：面向使用者的工作流介绍（`docs/research-workflow-intro.md`）。
  - 三笔提交信息均注明"adopted from an in-flight session with the user's authorization"；原作者未知。
- **Task 3a 修复 `e834edc`**（`Confucius`）：无可用标题 → `found=False, detail="title missing"`，不再写 `matched_title: null`；补真实往返与相似度边界用例；证据哈希改原始字节并写明防伪造边界（commit `fix: never write evidence the ledger reader rejects`）。待 `Kierkegaard` 定向复验。
- 计划已补 **Task 1b**（run-log 记 `git_repo: self|foreign|none`；foreign → problem、旧记录 → advisory）与 **Task 3b**（`declared_purpose` + T-30 build 豁免 advisory + cross-review 引文逐字命中）两个可派发小节。Task 1b 与 3b 都改 `run_log.py`，按序执行。

## evidence-integrity 执行记录（Task 3a 复验 + Task 1b + DOI code）

- **Task 3a 修复 `e834edc` 复验（`Kierkegaard`）**：**ADDRESSED**（I1/I2/I3 全关）。独立复现：无标题 → `(False, "title missing", None)`，写账为 `failed`（全文件无 `null`），只读复查只报 `unverified-entry`、无 `citation-self-asserted`，重复核验字节稳定；正常往返写账后只读 problems 为空；边界 0.8929→mismatch / 0.9091→found；非 UTF-8 响应按原始字节哈希。判别力两条独立复现。干净 worktree 888 tests OK。新 Minor：`doi-not-found` 混用（DOI 不存在 vs 标题不可用）→ 已修（见下）。
- **Task 1b `66d4657`**（`Confucius`）：`git_state` 三态（`self`/`foreign`/`none`）+ realpath 比较；`foreign` 时 commit/dirty 双 null（不再记录父仓库提交）；`check_runs` 新 code：旧记录 advisory `run-log-git-repo-unknown`、foreign problem `run-log-foreign-repo`、none problem `run-log-no-git-repo`、非法值 malformed；顺带修了一处真缺陷——`_run_git` 用系统 locale 解码，中文路径会被误判 foreign，改为 UTF-8。判别力：去掉 toplevel 校验 → 嵌套目录用例 `'self' != 'foreign'` 失败。tools 898 OK。
- **DOI code 拆分 `c0da3ae`**：`LookupResult.http_ok` 标记"提供方返回过 200"；两源都非 200 → `doi-not-found`，200 但 DOI/标题失败 → 新 code `doi-lookup-failed`；`_default_fetch` HTTPError 分支统一返回 bytes。判别力：title-missing 改回 doi-not-found → `doi-lookup-failed not found in ['doi-not-found', ...]`。tools 902 OK。
- 评审派 `Kierkegaard`（两节：Task 1b + DOI code 拆分，干净 worktree）；**Task 3b 已派** `Confucius`（`declared_purpose` + T-30 build 豁免 advisory + cross-review 引文逐字命中；commit `feat: mark declarations as declared and require quotable review findings`）。

## Task 1b / DOI code 评审结果（均 Approved）

- **Task 1b `66d4657`（`Kierkegaard`）**：**Approved**。独立矩阵覆盖 none/self/foreign、git 缺失/超时/非零/空输出、CRLF/正斜杠、符号链接/junction/大小写翻转；`check_runs` 的 advisory/problem/malformed 行为核对；UTF-8 修复被证实（本机 locale=cp936，旧实现要么 AttributeError 要么把中文路径误判 foreign）。判别力独立复现（`'self' != 'foreign'`，2 条失败）。干净 worktree 898 OK。
  - Minor 1：UTF-8 修复**无判别力用例**（测试路径全 ASCII）→ 已排收尾 A1（非 ASCII 子目录用例 + locale 回退判别力）。
  - Minor 2：显式 `git_repo: null` 同时报 malformed + missing-commit（缺失与 null 被 `record.get()` 混同）→ 收尾 A2。
- **DOI code 拆分 `c0da3ae`（`Kierkegaard`）**：**Approved**，无新 Critical/Important/Minor。分支矩阵（both 404 → `doi-not-found`；mismatch/title missing/title mismatch/bad JSON → `doi-lookup-failed`、`http_ok=True`；`_default_fetch` 两分支 bytes）全部核实；反向变异用例失败原文留档；干净 worktree 902 OK。
  - 残留观察（已排收尾 B）：台账 `status=failed` 不保存失败原因，读账无法区分 not-found 与 mismatch → 存 `detail`。
- 收尾轮（A+B）已排 `Confucius`（在 Task 3b 之后）：commit `fix: sharpen run-log provenance and citation failure evidence`。

## Task 3b + 收尾轮落地（`723735a`、`c09601d`）

- **Task 3b `723735a`**（`Confucius`）：run-log 只写 `declared_purpose`（旧 `purpose` 读取兼容；help/docstring 明说"声明不构成证据"）；milestones 的 T-30 对 `declared_purpose=="build"` 豁免 problem 但输出 advisory `t30-declared-build-run`（含 run id、日期、声明不构成证据），experiment/无声明仍是 problem；cross-review `check` 要求每条 blocking 的 evidence 含 ≥20 字符且逐字命中输入文件的引文，否则 `review-uncited-blocking` 退 1。判别力：build 豁免改静默 → `StopIteration`；去引文校验 → `['review-blocking'] != ['review-blocking','review-uncited-blocking']`。tools 908 OK。
  - 偏离：`test_automation_e2e.py` 的 blocking fixture 换成真实引文（否则全量必红），属必要适配；计划里"gate 证据化"未做（本次规格只要求 T-30 可见化），留待后续。
- **小收尾 `c09601d`**：非 ASCII 路径守护用例（`<tmp>/论文`，locale 回退时 `'foreign' != 'self'` 失败）；显式 `git_repo: null` 只报 malformed、不再叠加 missing-commit；台账 `status=failed` 保存 `detail`（legacy 兼容）。判别力三条实测。tools 915 OK。
- 评审（`Kierkegaard`，两节）与 **Task 4** 已派：迁移 `papers/example-paper` 为独立仓库 + 真实 run-log（`git_repo=self`）+ 覆盖率报告 + `checks.md` 换机器产物 + `test_evidence_integrity_e2e.py`；commit `feat: migrate the example paper and publish its coverage report`。

## Task 3b / 收尾评审（均 Approved）与 Task 4 落地

- **Task 3b `723735a`（`Kierkegaard`）**：**Approved**。独立矩阵：写侧只有 `declared_purpose`；T-30 的 declared build → advisory（含 run id/日期/"不构成证据"）、experiment/无声明 → problem、legacy `purpose: build` 同路径（declared 优先、不能反向伪造）；引文闸门双向空白归一、19/20 字符中英文同口径、多 blocking 独立、非字符串 evidence → malformed；清单外改 `test_automation_e2e.py` 判定为**合理**（原 fixture 用文件名当引文，本就该被拒）。判别力三条独立复现；干净 worktree 908 OK。
  - 新 Minor（性能）：引文闸门每项跑 SequenceMatcher（195KB×10 项≈2.5s）→ 已修（见下）。
- **收尾 `c09601d`（`Kierkegaard`）**：**Approved**。非 ASCII 路径判别力成立（locale 回退 → `'foreign' != 'self'`）；显式 null 只报 malformed（反向变异可复现）；台账 failed 保存 `detail` 且 legacy 兼容。干净 worktree 915 OK。
- **性能收尾 `4b37c68`**（`Confucius`）：`_quote_is_cited` 先做 `evidence in corpus` 短路径，未命中才走最长公共子串；用**注入调用计数**判别（整串命中 0 次调用、跨换行 1 次），不依赖墙钟。tools 923 OK。
- **Task 4 `23d9020`**（`Confucius`）：`papers/example-paper` 已成独立仓库（首提交 `d98340b`）；论文内 run-log 记录 `git_repo=self` + 论文 HEAD；`data/claims.yaml` + `submission/claims-coverage.{json,md}` 生成（protected=8/bound=7/unbound=1，未绑定 `main.tex:58 Coding 43`）；`checks.md` 手写声明改为指向机器报告；新增 `test_evidence_integrity_e2e.py`（6 条）。
  - **控制器发现**：迁移后论文仓库仍是脏的（44 项：报告/checks/被重跑的验证输出；`exports/` 13.9MB 生成物）——已派收尾：论文 `.gitignore` 加 `/exports/`，并把当前真实状态提交为论文仓库第二个 commit（不动模板仓库）。
- 评审（`Kierkegaard`：Task 4 + 性能两节）与论文仓库收尾（`Confucius`）在飞；随后 evidence-integrity 最终全分支评审（base `fb46fa7` → 最终 HEAD）。

## evidence-integrity 终审与收口（2026-10-04）

- **独立终审**（`codex exec`，`deepseek-v4-pro`，只读，base `fb46fa7`）：`final-review.json` 判 **blocking**，四条 finding：
  - F1：`cross_review` 的输入哈希按工作树字节计算，CRLF/LF 会改变哈希；`.gitattributes` 未 renormalize，也未进入新论文模板。
  - F2：旧的 stale cross-review 仍是 `verdict=pass`，`ccfa.yaml` 仍写 `submission_checks.status=passed`，机器状态与 `checks.md` 的 stale/2-problem 声明不一致。
  - F3：HEAD 上没有真实的全量 927/141 证据；终审只能看到 923 的旧记录。
  - F4：论文工作树不干净（当时有并行任务产生的未跟踪文件）。
- **第一轮定向复验**（`focused-review.json`）：F1/F2 主路径已闭合，但发现两条修复细节：`cross-review-check.json` 从脏工作树生成、多报 5 个未变化的 manuscript 输入；NUL 启发式的二进制保真不完整。均已修复。
- **第二轮定向复验**（`focused-review-2.json`，`deepseek-v4-flash`）：**verdict=pass，findings 为空**；独立复算确认文本后缀哈希、二进制保真、15 条 stale 报告与 clean HEAD 一致。

### 修复与证据

- F1（模板仓库）：`0b79676` 让 `cross_review._sha256` 对文本做 CRLF→LF 归一；`01923a8` 改为**已知文本后缀白名单**，`.bin` 等未知后缀按原始字节哈希；`tests/test_cross_review.py` 增加可区分旧实现的 `.bin` 用例；`tools/newpaper/create.py` 现在写入 `.gitattributes`（`30b8ac1` 已提交论文级规则）；`3ed4dd0` 把 `.gitattributes` 与 `git add --renormalize` 步骤写进迁移文档。判别力：旧 NUL 启发式对 `.bin` CRLF 会算错，新白名单用例失败；新实现复算 `TEXT_CRLF_EQ_LF=True`、`BINARY_BYTES_EXACT=True`。
- F2（论文仓库）：`226db0f` 用 `state.py rollback` 把示例论文从 `submission-check/package_ready` 回退到 `internal-review/review_cleared`，`void_artifacts=[reviews/cross-review.json]`，并把 `submission_checks.status` 改成 `needs-rerun`；`7e34b52` 增加机器可读的 `reviews/cross-review-check.json`；`6c68cfa` 从 clean HEAD 重生成该报告为 **15 条 `review-stale`**，不再包含未变化的 manuscript 输入。`checks.md` 与 `review-history.md` 均指向该报告并明确 stale；clean clone 复跑 `cross-review check` 得到 `problem_count=15`。
- 额外发现（clean clone 才暴露）：交付图 `figures/threat-model-lattice.pdf` 被 `*.pdf` 规则误伤、未进论文仓库，clean clone 的 `final-check` 因此报 3 个 problem（多出 `figure-missing`）。修复：模板 `!figures/**/*.pdf` 规则 + `test_create` 判别用例；迁移文档同步；论文仓库 `9d372d2` 纳入该图。clean clone `9d372d2` 复验：`STATUS_LINES=0`、`FIGURE_PRESENT=True`、`final-check=2`（与提交的 `reviews/final-check.json` 一致）、`cross-review check=15`、`run-log check` 退 0。

### 最终验证（当前模板 HEAD）

- 验证时模板代码 HEAD = `b2c6676`（图规则修复后）；论文 HEAD = `9d372d2`（交付图纳入后）。其后只追加本账本说明。
- `tools`：`Ran 929 tests OK`；`app`（offscreen）：`Ran 141 tests OK`。
- fresh clone（新建 `tools/.venv` + `pip install -r tools/requirements.txt`）后：`Ran 929 tests OK`。
- 论文提交树 clean clone（`9d372d2`）：`git status --porcelain` 为空；`run-log check` 退 0（problems=0）；`cross-review check` 退 1（15 条 stale，符合预期）；`final-check` 退 1（2 个 protected-section problem，符合提交报告）。
- 现状说明：主工作树中的论文仓库仍被另一个并行任务写入未提交的稿件/表格/手工编码文件（`manuscript/`、`tables/`、`ccfa-workfiles/literature/human-coding-v2/` 等）；按"不得为干净丢弃记录"的规则未触碰、未提交这些改动。可复现性以提交树和 clean clone 为准。

## 长任务安全 v1（2026-10-04，E64–E67）

- 计划：`docs/plans/2026-10-04-long-task-safety.md`。目标是把审计 P1-5 从"只有墙钟预算与显式重试"补到"可中断、可观察、有停止条件"。
- **E64 并发上限 = 1**：`queue` 用 OS 文件锁而不是易竞态的 PID 陈旧锁协议。Windows 用 `msvcrt.locking`，POSIX 用 `fcntl.flock`；进程退出/异常自动释放，锁文件保留诊断元数据。
- **E65 GPU 预算**：`GpuMeter` 采样 `nvidia-smi --query-gpu=utilization.gpu`，按利用率 ≥5% 的墙钟时间累计 GPU 秒数；`gpu_seconds/gpu_samples` 进独立 `resource_usage` 字段，**不写 metrics**，因此成功但未调用 `log-metrics` 的运行仍会被 `run-log-metrics-pending` 报出。预算耗尽后后续项记 `skipped-gpu-budget`。
- **E66 看门狗**：默认 runner 按 4 KiB 字节块读 stdout/stderr 并刷新活动时间；`stall_timeout_s` 内无任何输出才 kill，记 `stalled`，只有 `retry_on_stall` 为真才重试。
- **E67 策略沙箱**：`sandbox: policy` 做 cwd containment 与环境白名单，只支持默认 runner；注入 runner 直接退 2。help/计划/设计明确写清它不是文件系统、网络或 GPU 隔离。

### 实现与评审

- `17ab214 feat: add long-task safety controls to the experiment queue`：首版实现与判别测试。
- `1808857 fix: harden queue locks, gpu accounting, and watchdog`：独立评审发现 7 条边界问题；修复了 GPU 计数混入 metrics、无换行输出误杀、policy 被注入 runner 伪记录、relative queue root 的 cwd containment、GpuMeter 采样线程重叠计数、锁写失败残留、陈旧锁回收等问题。
- `486ae01 fix: use OS file locks for queue exclusion`：第二轮定向复验指出 `_stale()+os.replace()` 仍有 TOCTOU；最终改为 Windows `msvcrt` / POSIX `fcntl` OS 文件锁，彻底移除 `_stale/_pid_alive/_recover_stale/unlink/O_EXCL` 路径。
- 评审记录：`long-task-review.json`（needs-fixes，7 条）→ `long-task-review-2.json`（needs-fixes，TOCTOU）→ `long-task-review-3.json`（**pass，findings 为空**）。

### 真实验证

- 真实 `nvidia-smi` 冒烟：`GpuMeter` 返回 `{'seconds': 0.25, 'samples': 3, 'errors': 0}`。
- 真实 queue 冒烟（policy + GPU budget）：CLI 退 0；run-log 记录同时有 `policy={"sandbox":"policy"}`、独立 `resource_usage={"gpu_seconds":..., "gpu_samples":...}`，而 `metrics` 保持 `null`。
- 全量：tools **955 tests OK**；app（offscreen）**141 tests OK**，于 486ae01 代码状态验证（其后仅文档/账本变更）。

## 跨族评审 v1（2026-10-04，E68–E70）

- 计划：`docs/plans/2026-10-04-cross-family-review.md`。目标：同族/未知族评审默认不能冒充跨族 gate；本机没有第二 provider 时只实现强制与诚实边界，不伪造跨族。
- **E68 记录真实组成**：记录 `provider`、`execution_model`、`family_judgement`、`family_override`；v1 执行模型固定为 `deepseek-v4-flash`。
- **E69 默认拒绝同族/未知族**：`cross-review run` 只有 `family_judgement=="cross-family"` 才能写 pass；同族/未知族退 2，除非显式 `--allow-same-family`。
- **E70 `check` 同一口径**：从记录 `model` 与固定执行模型重算 family；检测 `family_judgement` 被单字段篡改；旧/缺字段记录默认报 `review-same-family`，`--allow-same-family` 只豁免迁移问题，不掩盖 `review-family-mismatch`。`--provider` 映射为 `codex exec -c model_provider=<provider>`。信任边界：本地一致性审计，不是密码学签名。

### 实现与评审

- `3ed3d0b feat: enforce cross-family review provenance`：首版跨族判定、默认拒绝、provider 传递、记录字段。
- `543794b fix: recompute cross-family provenance during review checks`：`check` 从 `model`+执行模型重算，检测 `family_judgement` 单字段篡改。
- `3e2c955 fix: close cross-family migration and self-report bypasses`：移除 `--execution-model` 自报覆盖，固定工作流执行模型；修复真实旧记录只报 `review-same-family`、allow 迁移可豁免。
- `52d7d16 docs: state the cross-family trust boundary`：设计、计划、用户介绍同步“默认拒绝同族/未知族”“本机尚无第二 provider”和“改写整份 JSON 仍可伪造，不是密码学签名”。
- `e6d204c fix: require complete cross-family provenance`：缺 `provider/execution_model/family_override` 的记录即使 model 看起来跨族也报 `review-same-family`。
- `0bfbd07 fix: require the fixed execution model in provenance`：记录 `execution_model` 必须等于工作流常量，不能用自报执行模型翻 family。
- `abaa790 fix: preserve family mismatch through migration allow flag`：`allow-same-family` 不再吞掉 `review-family-mismatch`。
- `3c40c53 fix: keep unknown family mismatches visible`：`computed_family=="unknown"` 与具体 `family_judgement` 的冲突也保留 mismatch。

### 评审与最终证据

- `cross-family-review.json`：needs-fixes（旧记录缺字段、`--provider` 提示、文档未同步）；`cross-family-review-2.json`：needs-fixes（旧记录 mismatch 迁移口、model/execution_model 自报）；`cross-family-review-3.json`：对 `3e2c955`+`52d7d16` 判 **pass**；`cross-family-review-4.json`：对 `e6d204c` 判 critical（mismatch 被 allow 掩盖）；`cross-family-review-5.json`：对 `abaa790` 指出 unknown family 窄分支。
- 最终只读内存对照：对 `model=mystery-v1`、`execution_model=deepseek-v4-flash`、`family_judgement=same-family`、缺 provider 的记录，`abaa790^` 返回 `['review-same-family'] / []`，`3c40c53` 返回 `['review-family-mismatch','review-same-family'] / ['review-family-mismatch']`。
- 真实旧记录 CLI：`cross-review check --paper-root papers/example-paper --out-dir reviews` 只报 `review-same-family`；加 `--allow-same-family` 后 problems 为空。
- 全量：tools **966 tests OK**，app（offscreen）**141 tests OK**；最终代码 HEAD 为 `3c40c53`（其后仅本账本说明）。
- 未实现边界：本机仍未配置第二个可用 provider，跨族评审还没有真实双 provider 运行证据；`check` 是本地一致性审计，不防整份 JSON 被重写。论文仓库未按用户要求触碰。

## Docker 沙箱后端 v1.1（2026-10-04，E71）

- 计划：`docs/plans/2026-10-04-long-task-safety.md` 的 Task 5。目标：把 `queue` 从“只有策略沙箱”补到可选的 Docker 后端，让实验根只读、只有输出目录可写、默认禁网；daemon 不可用时必须退 2，不静默回退宿主机。
- **E71 清单与判定**：新增 `docker_image`（`sandbox: docker` 时必填）、`docker_network`（默认 `none`）、`docker_gpus`（`null|all`）、`docker_output`（默认 `runs`，必须是队列根内相对目录，拒绝 `.`、`..`、绝对路径、盘符路径与前导分隔符）。
- **运行语义**：`docker run --rm --read-only --security-opt no-new-privileges --network <none|...> --tmpfs /tmp --name <ccfa-...>`；队列根只读挂载到 `/workspace`，`docker_output` 可写挂载到 `/outputs`，`--workdir /workspace/<item cwd>`。`docker_gpus: all` 才加 `--gpus all`。
- **环境边界**：容器只收到 `HOME=/tmp`、`CCFA_WORKSPACE=/workspace`、`CCFA_OUTPUT_DIR=/outputs` 与显式 `env`；宿主 `QUEUE_TEST_SECRET` 不出现在容器 argv。run-log 的 `policy` 记录镜像、网络、GPU、输出目录与容器内 `workdir`，`command` 仍是原始队列命令。Docker CLI 自身继承宿主环境，这是 CLI 连接 daemon 所需；它不把宿主环境注入容器。
- **清理**：每个 attempt 生成独立 `ccfa-` 容器名；超时/卡死 kill Docker CLI 后，`finally` 执行 best-effort `docker rm -f`，避免容器继续占 GPU。宿主进程被强杀或断电后仍可能残留容器，需要 `docker ps` 人工清理。
- **测试**：`tools/tests/test_queue.py` 新增精确 argv（只读根、只读 `/workspace`、可写 `/outputs`、`--network none`、`--workdir`、镜像与命令顺序）、docker_output 逃逸/根目录/逗号路径拒绝、daemon 失败前置、CLI 退 2 且不写 run-log、policy 记录、宿主环境不泄漏、超时清理、Docker cwd containment 等用例。
- **真实验证（fail-closed）**：Docker daemon 关闭时，真实 CLI 冒烟输出 `工具错误: Docker daemon 不可用...`，退 2，`LOG_JSON=0`，没有回退执行，也没有伪造 run-log。
- **真实验证（daemon 可用）**：启动 Docker Desktop（`ServerVersion 29.8.1`），用真实 `python:3.12-slim` 容器跑 `sandbox: docker` 队列：退出 0，容器内 `SMOKE_OK`；`/outputs/probe.txt` 可写并落到宿主 `runs/probe.txt`；`/workspace/probe.txt` 与 `/workspace/runs/probe2.txt` 均写入失败；`socket.create_connection(("1.1.1.1", 80))` 被 `--network none` 阻断。run-log `status=completed`、`policy.sandbox=docker`、`command[0]=python`；`docker ps -a --filter name=ccfa-` 为空，无残留容器。

### 评审与修复

- 独立只读评审（`deepseek-v4-pro`，`os-sandbox-review.json`）判 **fail**，4 条 finding：清单 `sandbox: docker` 可被 CLI `--sandbox none|policy` 静默降级为主机执行（high）；Docker argv 校验错误发生在 `run_command` 写入 `running` 之后，会留下永久 `running` 记录（medium）；docker 模式允许注入 runner 冒充 Docker（medium）；symlink 与 Windows drive-relative `docker_output` 缺判别测试（low）。
- 修复：新增 `allow_sandbox_downgrade`（CLI `--allow-sandbox-downgrade`），清单声明 docker 时降级到 none/policy 默认拒绝；新增 `allow_injected_runner`，policy/docker 默认拒绝注入 runner，测试或高级调用必须显式开启；`_docker_argv` 移到 `run_command` 之前构造，校验失败不再留下 `running`；补 symlink 逃逸不留记录、Windows drive-relative 拒绝、降级与注入 runner 判别用例。
- 第二轮独立只读评审（`os-sandbox-review-2.json`）判 **pass**：四条 finding 均关闭；发现一条低非阻塞回归——`_docker_argv` 构造失败时 GPU meter 线程已启动但不会 stop。随后把 `meter.start()` 移到 Docker argv 构造成功之后，并新增“构造失败不启动 meter”判别用例。
- 第三轮定向复核（`os-sandbox-review-3.json`，HEAD `48189ed`）判 **pass，findings 为空**；确认 meter leak 已关闭，前四条 finding 未回归。
- 最终全量：tools **988 tests OK**，app（offscreen）**141 tests OK**；Docker 后端最终代码 HEAD 为 `48189ed`（其后仅本账本说明与真实验证记录）。

## 真实性 gate 补丁（2026-10-04，E72–E74）

- 计划：`docs/plans/2026-10-04-truthfulness-gates.md`。目标：处理审计总结的三条最高优先级缺口——人工验证缺位、跨族评审能力与 gate 不匹配、证明与引用语义没有 gate。确定性脚本不判断证明/语义本身，只强制这些判断有人做过、可追责、可复核。
- **E72 `human-coding`**：两张人工编码表按 item id join，输出 observed agreement、Cohen's kappa、95% bootstrap CI、逐标签计数与混淆矩阵；重复 item、缺 item、空 code 都是 problem；`--min-kappa`（默认 0.6）以下退 1。判别力：完美一致 κ=1；已知 2×2 表 κ=0.8；低 κ 触发 `human-coding-low-kappa`。
- **E73 `argument-audit`**：扫描 theorem/proposition/lemma/corollary 环境，要求 `data/proof-audit.yaml` 有具名人类复核记录；扫描受保护章节 `\cite{}`，要求 `data/citation-support.yaml` 有具名人类语义支持记录。`claim_text` 必须出现在引用所在的受保护章节，`support_quote` 必须出现在必填的 `source_path` 中；模型 reviewer、`refuted`/`uncertain`/`contradicts`、未知 bib key、缺 source、claim/source 不匹配都是 problem；`partial` 是 advisory。
- **E74 同族 override 异常化**：`cross-review run --allow-same-family` 现在必须同时给 `--override-reason`（≥20 字符），原因写入 `family_override_reason`；`check` 缺 reason 报 `review-override-reason-missing`；新增 `check --strict-cross-family`，任何同族 override 都报 `review-family-override`。
- 文档同步：README 工具表与阶段速查、`docs/research-workflow-intro.md`、`docs/design/2026-10-03-research-workflow-design.md` §6.1.2、`tools/ccfa/stages.py` 的 `internal-review` gate 判据与两份 checklist。
- 第一轮独立评审（`truthfulness-gates-review.json`）判 **fail**：畸形 `method/status/verdict` 会抛未捕获 TypeError；`\cite[opt]{key}` 与 `\section[short]{Title}` 漏扫；reviewer deny-list 漏 grok/sonnet/nova；引用覆盖只按 key、未绑定 `claim_text`；受保护子节后的非保护兄弟子节会清掉父章节保护。
- 修复：membership 改为类型安全；引用/标题 regex 支持 optional args；reviewer deny-list 扩充；`claim_text` 必须逐字出现在引用所在受保护章节，`source_path` 必填且 quote 必须命中；受保护章节改为栈式父子继承；移除非标准 normal κ CI；恢复设计文档 COM 表。补对应判别测试。
- 第二轮复核（`truthfulness-gates-review-2.json`）仍判 **fail**：`claim_text` 仍按整份 manuscript 文件匹配，没有限定到引用所在的受保护章节，同文件非保护章节中的句子可以误过。修复：扫描器记录受保护章节区间的归一化文本，`claim_text` 必须在对应引用区间内命中；补“同文件非保护章节不能覆盖”反例。
- 修复后全量：tools **1022 tests OK**，app（offscreen）**141 tests OK**。
- 第三轮定向复核（`truthfulness-gates-review-3.json`，HEAD `d25a6e9`）判 **pass，findings 为空**；确认 claim_text 已在受保护章节区间内匹配，前序修复未回归。
- 边界：新 gate 只证明「有人做过判断」，不证明判断正确。数学证明的最终正确性仍靠外部数学专家；引用语义的最终判断仍靠领域专家；跨族 gate 仍要求真实第二 provider，override 只是异常路径。

## 治理、统计、新颖性与复现环境 gate（2026-10-04，E75–E78）

- 计划：`docs/plans/2026-10-04-governance-statistics-novelty.md`。目标：关闭审计剩余的三条高严重度缺口——治理与伦理空白、统计设计门槛薄、新颖性只有三篇最近邻。
- **E75 `novelty`**：`data/novelty-audit.yaml` 要求 ≥2 个去重数据库、非空查询、一致的 YYYY-MM-DD 检索日期与 cutoff、≥3 篇去重近邻（id 必须在 `manuscript/references.bib` 中）、每篇 overlap/difference/claim_ids；claim id 必须属于声明的去重 claims，且每个 claim 必须被至少一个近邻差异覆盖；禁止“没人做过 / no one has done / first to”式表述。
- **E76 `stats_plan`**（CLI `scripts/statistics.ps1`）：`data/statistics-plan.yaml` 要求 alpha、multiple_comparison、每个 claim 的 endpoint/test/effect_size/target_power/sample_size/seeds/stopping_rule/missing_data；多 claim 时 correction 不能为 none；effect_size 必须有限且为正。
- **E77 `governance`**：`data/governance.yaml` 要求作者/贡献角色/corresponding、逐作者 COI、伦理与数据许可（human_subjects=true 时 IRB 与 informed consent 必填）、AI 使用披露、查重工具与日期、双用途复核与负责任披露联系人。
- **E78 `repro-env`**：`data/repro-environment.yaml` 要求 Python、包管理器、requirements、lockfile 与 sha256、系统工具名称/版本/命令/证据文件；lockfile 漂移、requirements/证据缺失、证据版本不匹配、无效容器 digest、重复工具都是 problem。
- gate 同步：`grounded` 要求 novelty audit；`experiment-design` 要求 statistics plan；`submission-check` 要求 repro-environment 与 governance 台账；两份 checklist 已重新生成。模块名为 `stats_plan.py`，避免与 Python 标准库 `statistics` 冲突；CLI 入口仍是 `scripts/statistics.ps1`；新论文模板会 seed 四份空台账，等待逐项填写。
- 判别力：三个新测试文件共 19 条，覆盖缺台账、少近邻、单数据库、未覆盖 claim、未支撑表述、alpha/sample_size/seeds/correction 错误、缺 COI、缺 IRB/consent、AI 未披露、查重未做、双用途未复核等。
- 独立评审（`governance-stats-novelty-review.json`）判 **fail**：novelty 可用重复数据库/重复 claim/未声明 claim_id 蒙过；stats_plan 接受 `.nan/.inf` 作为 `effect_size`；另有混合 ISO 日期、宽松 version、未 seed 台账、文档计数等低风险问题。
- 修复：novelty 增加数据库/claim/近邻标题去重、近邻 id 必须存在于 `manuscript/references.bib`、claim_id 必须属于声明 claims；stats_plan 用有限数检查拒绝 `.nan/.inf` 和超大整数 effect_size；`is_iso_date` 只接受 `YYYY-MM-DD`；ledger version 要求严格 int；new-paper seed 四份空台账；更新设计文档与账本。
- 复现环境 gate 独立复核（`repro-env-review.json`）判 **pass**，仅三条低风险：版本字符串按子串命中、路径逃逸/畸形形状缺测试、missing 与 malformed 台账共用错误码。修复：版本改为 token 边界匹配，补路径逃逸/非 dict tool/非 list system_tools/缺 hash 测试，`repro-env-ledger-missing` 与 `repro-env-invalid` 分离。
- 修复后全量：tools **1074 tests OK**，app（offscreen）**141 tests OK**。
- 第二轮复核（`governance-stats-novelty-review-2.json`）判 **pass**，无 blocking/important finding；保留两条低风险观察：缺 `references.bib` 时 novelty 退 2 而非结构化 problem，未跟踪的 weaknesses 文档仍保留旧治理缺口表述。
- 边界：三道 gate 只强制结构化声明与覆盖，不保证新颖性、统计正确性或治理真实性。

## 图表语义支持 gate（2026-10-04，E79）

- 计划：`docs/plans/2026-10-04-figure-support-audit.md`。目标：关闭审计剩余的中等严重度缺口——「不检查图表是否支撑正文结论」：manifest 只验来源/字节/哈希，没有人对「这张图是否真的展示了正文用它所主张的结论」负责。不新增工具与 CLI：把图表语义支持做成 `argument-audit` 的第三张台账，与人工证明复核、引用语义支持并列，因为它们同属「脚本判不了语义真伪，但可以强制判断有人做过、可追责、可复核」。
- **E79 契约**：新增 `data/figure-support.yaml`（`version: 1`，`figures:`）。`figures/manifest.yaml` 里每张具名交付图必须有一条具名人工判断：`id`、`claim_ids`、`attributed_text`、`verdict`（supports/partial/contradicts/irrelevant/not-applicable）、`reviewer`、`reviewed_at`、`note`。
- **fail-closed 判定（problem）**：manifest 缺 name/图名重复；台账缺失；条目 id 不在 manifest；交付图无记录；证据图 claim_ids 非法；claim 未在 novelty-audit 声明；novelty claim 注册表不可信或为空；attributed_text 过短或不在 `referenced_in` 指向的正文文件里；`referenced_in` 缺失/行号非法/越界/逃逸/文件不存在；reviewer 是模型名；日期非法；verdict 非法；contradicts/irrelevant；非 supports 判定缺理由。**advisory（永不改退出码）**：`partial`、`figure-support-not-needed`、`figure-support-coverage`。
- **边界**：脚本不看图、不判断语义本身；v1 只做文件级原文匹配，不做段落级定位。非证据图（示意图/架构图）用 `not-applicable`，必须写明 >=20 字符理由且不得绑定 claim。
- 文档同步：README 工具表与阶段速查、设计文档 §4.2/§6.1.2/§6.3、用户介绍、审计缺点总结；`stages.py` internal-review 判据与两份 checklist 重新生成；`new-paper` 播种空台账并加断言。

### 实现与评审

- `8d131fd feat: audit figure-to-claim support`：首版实现 + 28 用例。
- 第一轮独立只读评审（`deepseek-v4-pro`，`figure-support-review.json`）判 **needs-fixes**，5 条：`referenced_in` 行号不查上界（important）；manifest 重复/无名图名被静默丢弃、交付图可漏审（important）；novelty claim 注册表不可信被降级为 advisory、claim 绑定可零退出遁过（important）；`version: true`/`1.0` 与整数 1 相等（minor）；多条合同行无测试、happy-path 断言偏弱（minor）。
- 修复 `f905414 fix: fail closed on figure-audit gaps`：行号按文件实际行数校验；缺 name/重名直接报 `figure-support-manifest-invalid`；有证据图但 claim 注册表不可用时报 problem；`_read_yaml` 要求严格 int 版本（同时收紧 proof/citation 台账，属合同收紧）；happy-path 改为 `problems == []`；补 9 条用例。
- 判别力实测：把 `argument_audit.py` 回退到 `8d131fd` 后，越界行号、重名 manifest、缺失注册表、bool 版本四条新用例全部失败（AssertionError 原文留档于会话）。
- 第二轮定向复核（`figure-support-review-2.json`）指出修复不完整：`_declared_claims` 仍忽略注册表版本并过滤非字符串成员，`claims: [C1, 123]` 会返回 `{C1}`，绑定仍可零退出通过。
- 修复 `b47192f fix: reject partial novelty claim registries`：`_declared_claims` 改为「可信才返回集合，不可信返回 `None`」——缺文件/解析失败/顶层非映射/版本非整数 1/claims 非列表/任一成员非非空字符串都判不可信；调用方对 `None` 与空集合都按不可绑定处理。补 3 条用例（两条对 `f905414` 判别力失败）。
- 第三轮定向复核（`figure-support-review-3.json`）指出同类最后一条：重复 claim id 被折叠为集合，`claims: [C1, C1]` 仍可信，而 `novelty.py` 对同一注册表报 `novelty-duplicate-claim`。
- 修复 `6be4bb1 fix: reject duplicate novelty claim ids`：strip 后检测重复并返回 `None`；补 1 条用例（对 `b47192f` 判别力失败）。
- 第四轮定向复核（`figure-support-review-4.json`，HEAD `6be4bb1`）判 **pass，findings 为空**：确认重复 claim 已封闭、`None`/空集合都被正确当作不可绑定、`not-applicable` 图仍豁免、proof/citation 路径未变；并记下两条不构成 false pass 的观察——空 claims 列表在 novelty 侧报 `novelty-invalid` 而本工具按不可绑定处理；novelty 台账的 search/neighbors 不合法时本工具仍信任其 claims（但 novelty 是独立 gate，论文仍过不了）。

### 验证

- 全量：tools **1115 tests OK**，app（offscreen）**141 tests OK**；Docker 后端与跨族评审相关模块未触碰。
- 最终代码 HEAD 为 `6be4bb1`（其后仅本账本与文档提交）。
- 未实现边界：本 gate 只证明「有人做过图表语义判断」，不证明判断正确，也不看图；图-结论一致性的最终判断仍靠外部专家。

## 自证豁免必须写理由（2026-10-04，E80）

- 目标：处理审计缺点表里的 #10「冻结规则靠自报」与 #16「工作流自身纪律不总保持」。两处共同的缺陷是：一次自我声明就能换到豁免，而且只留一条 advisory，等于零成本绕过。
- **T-30 build 豁免**：`milestones due` 扫描 T-30 之后开始的运行。`declared_purpose: build`（或 legacy `purpose: build`）只在记录同时写了 `purpose_reason`（空白归一化后 >=20 字符）时才算正当豁免，仍是 advisory `t30-declared-build-run`（消息里带理由）；缺理由或理由过短改为 problem `t30-unjustified-build-run`。`experiment` 或无声明仍是 problem `t30-new-experiment`，给了理由也不豁免。
- **脏树运行**：`run-log check` 把论文仓库自身的脏树运行从 advisory 升为 problem `run-log-dirty-tree`；记录里写了 `dirty_waiver`（>=20 字符）才降为 advisory `run-log-dirty-waiver`（消息里带理由）。该规则对**所有 status** 生效（含 `running`）——运行还没结束，也不代表它可复现；`git_dirty` 不是布尔也不是 null 时报 `run-log-malformed`（判定不出是否可复现时不放行）。
- **写入口**：`run-log run` 新增 `--purpose-reason` 与 `--dirty-waiver`，随记录落盘；旧记录缺字段按「无理由」处理。
- 边界：声明仍然可能不实。脚本无法证明这次运行真的是 build，也无法判断脏树为什么可接受；改变的是绕过的成本——从一个词变成一条具体、可复核、会写进报告的理由。
- **测试策略（用户裁定，2026-10-04）**：此后每轮只跑受改动影响的测试模块，不再每轮全量。

### 实现与评审

- `7ba80ac fix: require a reason to waive the T-30 and dirty-tree rules`：首版实现 + 判别测试；改动前 5 条新用例全部失败（`t30-unjustified-build-run` 不存在、`run-log-dirty-tree` 仍只是 advisory）。
- 第一轮独立只读评审（`freeze-exemptions-review.json`）判 **fail**，3 条：`status == "running"` 的脏树记录在脏树判定之前就 `continue`，可零退出遁过（important）；README 说 `--dirty-waiver` 即降级、没写 >=20 字符条件（minor）；边界用例缺失（minor）。
- 修复 `c890ec8 fix: check dirty trees on running records too`：把脏树判定抽成 `_dirty_tree_findings`，在 status 分支之前对所有记录生效；README 补上 >=20 字符；补 7 条边界用例（空白理由、非字符串、恰好 20 字符、experiment+理由、干净树+waiver、running 脏树）。判别力：`running` 脏树用例对 `7ba80ac` 失败。
- 第二轮定向复核（`freeze-exemptions-review-2.json`）判 **needs-fixes**，2 条 minor：truthy 非布尔 `git_dirty`（`1`、`"true"`）仍绕过规则；缺 `git_repo`/外来仓库的脏树组合无测试。
- 修复 `e17f18e fix: reject non-boolean git_dirty and cover dirty repo combinations`：`git_dirty` 非 bool 且非 null 报 `run-log-malformed`，在 repo 判定之前拦截；补 3 条用例（畸形布尔值、legacy 无 repo 字段、外来仓库脏树不冒充论文树）。
- 第三轮定向复核（`freeze-exemptions-review-3.json`，HEAD `e17f18e`）判 **pass，findings 为空**：逐值枚举 `git_dirty` 的 `true/false/null/缺失/0/1/"true"/"false"/[]/{}`，确认没有值能在「暗示脏树」的同时零退出；畸形分支对所有 status 与缺/外来 repo 都生效；T-30 侧未回归（19 字符不豁免、20 字符豁免、experiment+理由仍报 `t30-new-experiment`）。

### 验证

- 按用户裁定只跑受影响模块：`test_milestones`、`test_run_log`、`test_queue`、`test_docs_consistency`、`test_evidence_integrity_e2e`，共 **201 tests OK**（约 35 秒；全量 1115 条约 150 秒）。未跑全量，也未跑 app 侧（本轮未触碰 app 代码）。
- 最终代码 HEAD 为 `e17f18e`（其后仅本账本提交）。
- 未实现边界：声明仍可能不实；脚本不判断运行真的是 build，也不判断脏树为什么可接受。

## 跨族评审绑定指令摘要（2026-10-04，E81）

- 目标：处理审计缺点表里的 #7「LLM 评审不可复现」。`cross-review` 原先存了输入文件哈希（`input_hashes`）与评审模型的原始输出，`check` 能报 `review-stale`，但没有任何东西把评审记录绑定到**产生它的指令**：`build_prompt` 里嵌着 `stages.py` 的 gate 判据与 stage 提示，改了这些文本，旧评审就是在另一套指令下产生的，却仍然通过。
- **E81 `prompt_sha256`**：`cross-review run` 把发送给评审模型的 prompt 的 sha256 写进记录的三种形态（complete/malformed/failed）。`check` 用记录里的 `stage` 与 `input_hashes` 键重建同一段 prompt 并比对：缺字段、缺/空 stage、或重建失败（`ccfa.yaml` 不可读、mode/stage 未知）报 `review-prompt-unknown`；摘要不一致报 `review-prompt-drift`。两者都是 problem，处置都是重跑评审。
- **规范化**：prompt 的文件清单排序并去重，`--path` 的顺序与重复都不影响摘要；重建不 stat 输入文件，输入被删仍由 `review-stale` 负责；`input_hashes` 条目本身非法（`review-record-invalid`）时跳过指令比对，避免噪音。
- **空评审输入**：`run` 传空 `--path` 直接 `ValueError`（CLI 退 2）；`check` 遇到空 `input_hashes` 报 `review-malformed`。没有输入的跨模型评审不成立。
- 边界：这证明「评审是在当前指令下产生的」，不证明评审结论正确；LLM 采样本身仍不可复现；整份 JSON 被重写仍可伪造（既有信任边界，未变）。

### 实现与评审

- `b2b3731 feat: bind cross-review records to the instructions they used`：`build_prompt` 抽出 `_render_prompt`；记录 `prompt_sha256`；`check` 重建比对；+5 条用例（对 `56c6b96` 全部判别失败）。
- 自审发现、RED 证实并修复 `975018f fix: canonicalise the review file list before hashing`：`--path` 传重复路径时 `build_prompt` 列两次而 `check` 从哈希字典键重建只列一次，会产生永久 `review-prompt-drift`；`_render_prompt` 改为排序 + 去重，补 1 条判别用例（对 `b2b3731` 失败）。
- 第一轮独立只读评审（`prompt-drift-review.json`）判 **needs-fixes**，2 条：`check_review` 接受空 `input_hashes` 可零退出、`run_review` 在 API 层接受空 `paths`（important）；缺 stage/空 stage/空输入分支无测试（minor）。
- 修复 `0df6f05 fix: reject a cross-review with no inputs`：空 `input_hashes` 报 `review-malformed` 并跳过指令比对；`run_review` 在写盘前拒绝空输入清单；补 4 条用例（空输入与空 paths 两条对 `975018f` 判别失败）。
- 第二轮定向复核（`prompt-drift-review-2.json`，HEAD `0df6f05`）判 **pass，findings 为空**：确认空输入不再零退出、非字符串键/单文件缺失/异文件集摘要都按预期报错、`hashes_usable` 只在已报 `review-record-invalid` 后为假不会掩盖有效记录的 drift、排序去重对 `./` 前缀/反斜杠/绝对路径/重复/乱序都归一一致、既有 `review-stale`/`review-blocking`/`review-uncited-blocking`/`review-same-family`/`review-override-reason-missing` 未回归。

### 验证

- 按用户裁定只跑受影响模块：`test_cross_review`、`test_docs_consistency`、`test_scripts`、`test_automation_e2e`、`test_evidence_integrity_e2e`，共 **147 tests OK**（约 42 秒）。未跑全量，也未跑 app 侧（本轮未触碰 app 代码）。
- 最终代码 HEAD 为 `0df6f05`（其后仅本账本与文档提交）。
- 未实现边界：证明「评审在什么指令下产生」，不证明评审结论正确；LLM 采样仍不可复现；整份 JSON 被重写仍可伪造。

## 平台依赖预检 doctor（2026-10-04，E82）

- 目标：处理审计缺点表里的 #17「平台耦合」。工作流绑死在 git、LaTeX 工具链、codex、Docker、nvidia-smi 与两个 venv 上，缺哪个都只会在某个不相关的步骤里炸成一个看不懂的错。新增只读预检 `doctor`：点名缺什么，以及缺它禁用了哪个能力。
- **判定**：`git` 缺失是 problem；`pdflatex`/`bibtex`/`xelatex`/`codex`/`docker`/`nvidia-smi` 与 `tools/.venv`、`app/.venv` 缺失默认是 advisory，`--strict` 一律升为 problem。`docker` 除了二进制还会执行 `docker info` 探测 daemon，daemon 不可达报 `doctor-daemon-down`（默认 advisory / strict 下 problem）——因为「有 docker 二进制但 daemon 没起」是本工作流实际踩到的失效，只报二进制等于假装通过。
- **诚实边界**：`found` 只表示命令在 PATH 上、venv 解释器是非空文件；除 Docker daemon 外不执行任何命令，所以 `found` 不等于该命令跑得通。venv 默认检查要求非空普通文件（空文件/目录/断链都算缺失）。
- **契约**：只读、不安装、不写文件；stdout JSON，stderr 逐行状态；退出码 0/1/2 与其它工具一致。新增 `scripts/doctor.ps1`，两份 CLI 清单（`test_scripts.py`、`test_docs_consistency.py`）与 README 工具表/阶段速查同步。

### 实现与评审

- `bfa3d03 feat: add a platform dependency preflight`：首版实现（含 daemon 探测与 15s 超时）+ 16 条用例；真机冒烟 `scripts/doctor.ps1` 输出 9 项 `found`、退 0。
- 第一轮独立只读评审（`doctor-review.json`）判 **needs-fixes**，3 条：注入的 daemon runner 抛非 `OSError` 异常会带 traceback 逃出预检（important）；非 daemon 命令只查 PATH 就报 `ok`，与「报告能实际用什么」的 docstring 矛盾（important）；venv 检查信任空文件（minor）。
- 修复 `357fbed fix: keep doctor honest about what it verified`：探测加宽为 `except Exception`；状态标签 `ok` 改为 `found`，并在 docstring/README/设计里写清「found=在 PATH 上、只有 Docker 会执行、venv 只确认非空解释器文件」；默认 venv 检查改为非空普通文件。补 4 条用例（注入异常、空解释器、非空解释器、标签措辞），三条行为用例对 `bfa3d03` 判别失败。
- 第二轮定向复核（`doctor-review-2.json`，HEAD `357fbed`）判 **pass，findings 为空**。

### 验证

- 按用户裁定只跑受影响模块：`test_doctor`、`test_scripts`、`test_docs_consistency`，共 **91 tests OK**（约 40 秒）。`test_scripts` 会对新包装器实跑 `--help` 与非法参数两条真 PowerShell 用例。未跑全量，也未跑 app 侧。
- 真机冒烟（`357fbed`）：`scripts/doctor.ps1` 退 0，9 项 `found`（git/pdflatex/bibtex/xelatex/codex/docker/nvidia-smi/tools venv/app venv），daemon 探测通过。
- 最终代码 HEAD 为 `357fbed`（其后仅本账本提交）。
- 未实现边界：`found` 不证明命令可执行成功（PATH 上的坏 shim 仍会显示 found）；不安装或修复任何依赖；不检查 daemon 之外的运行时状态。

## 自定义 HTTP 工具注册表（2026-10-04，E83）

- 目标：P2——让使用者不写代码就能把自己的 API 接进工作台。做法是声明式 YAML 注册表，`ToolBridge` 把注册的工具与内置工具合并，走同一套参数校验、写操作确认与摘要审计。
- **加载规则（fail-closed）**：v1 只支持 HTTP，不支持任意 Python handler（那样会拿到应用自身权限且无法校验）；`http://` 需显式 `allow_http: true`；凭据头只能写 `secret:<key_name>`（判定按名字：`Authorization`/`Proxy-Authorization`/`Cookie`/`Set-Cookie`，以及任何含 token/key/auth/secret/credential/password/session/cookie 的名字），明文凭据是加载错误；占位符必须在 `parameters` 中声明；GET 不许带 json body；**任一工具非法则整份注册表不加载**。
- **运行规则**：请求带 `Accept-Encoding: identity`；响应若仍带非 identity 的 `Content-Encoding`，在读取请求体之前就报 `http-encoding`（解压会在限流前吃内存），确需压缩响应的工具要写 `allow_compressed: true`。响应体按字节上限流式读取，再解析 JSON 或截断文本。所有请求异常只报异常类型名，不报消息，避免把插值后的 URL/占位符/凭据带出去。
- **接入**：`ToolBridge(project_root, http_tools=HttpToolRegistry(specs, resolve_secret=...))`；`ToolBridge.openai_tools()` 同时给出内置与注册工具。
- 边界（如实）：注册表到 `ToolBridge` 的核心链路已通；把它接到设置界面与聊天面板（`http_tools` 设置项 + 启动加载）与 P3 打包仍未做。名字启发式刻意保守，`Public-Key-Pins`/`X-Monkey` 这类非凭据名也会被要求走 keyring——代价是麻烦而不是泄露。

### 实现与评审

- `3efc6ce feat: add a declarative HTTP tool registry`：首版实现 + 24 条用例（改动前 `ModuleNotFoundError` 全失败）。
- 第一轮独立只读评审（`http-tools-review.json`）判 **fail**，6 条：带空白的敏感头名绕过明文检查（important）；`httpx.InvalidURL` 不是 `HTTPError`，坏 URL 占位符值会带 traceback 逃出并回显（important）；响应体在截断前被完整缓冲（important）；`secret:{key}` 里的占位符不被校验（minor）；`timeout_s: .nan` 通过范围检查（minor）；网络失败泄漏用例因为 spec 没有 secret 头而形同虚设（minor）。
- 修复 `ae397ea fix: close HTTP tool registry leak and bounds gaps`：头名 strip 后再判定；请求路径改捕所有异常且只报类型名；响应改为流式 + 字节上限；`secret:` 引用不得含占位符；用 `math.isfinite` 拒绝 NaN/inf；泄漏用例改用带 secret 头的 spec。补 5 条判别用例（对 `3efc6ce` 全部失败）。
- 第二轮复核（`http-tools-review-2.json`）判 **needs-fixes**，2 条：`iter_bytes()` 未给 chunk_size，压缩响应可在截断前放大出超大解码块（important）；空 `secret:` 引用被放行（minor）。
- 修复 `2275e73 fix: bound decoded response chunks and reject empty secret refs`：按 8 KiB 分块读取并按剩余预算切片；`secret:` 必须给出非空 key 名。补 3 条用例（对 `ae397ea` 失败）。
- 第三轮复核（`http-tools-review-3.json`）判 **needs-fixes**，4 条：chunk_size 只是重新切片，httpx 内部仍会整块解压（important）；敏感头白名单漏掉 `X-Api-Token`/`apikey`/`Token`（important）；两条限流用例绕过 content decoding（minor）；`resolve_secret` 抛异常时逃出净化路径（minor）。
- 修复 `650d20e fix: refuse compressed responses and broaden credential headers`：请求带 `Accept-Encoding: identity`，并**在读取前拒绝**任何非 identity 压缩响应（`allow_compressed: true` 才放行）——这是真正把内存钉住的唯一办法；凭据名改为「显式集合 + 名字含 token/key/auth/secret/credential/password」；`_build_request` 移进净化 try。补 4 条判别用例（对 `2275e73` 全部失败）。
- 第四轮复核（`http-tools-review-4.json`）输出**不符合 schema**（键名错、缺 summary、被代码围栏包住），3 条 finding。逐条核验后：两条**驳回**（都用实测探针证伪），一条部分成立。驳回证据：① 声称压缩守卫可被 `br`/`zstd`/`gzip, br`/大小写绕过——实测这些取值全部报 `http-encoding` 且 `body_read=False`，守卫是「只允许 identity」的白名单而非黑名单，代码里也没有 `response.json()/read()`；② 声称 resolver 消息会泄漏——实测 envelope 只有 `请求失败: RuntimeError`，resolver 文本整体不出现。成立部分：`X-Session-Id` 确实没被匹配。
- 修复 `acddaf5 fix: cover session headers; lock the encoding and resolver invariants`：加入 session/cookie 名字提示；补 3 条回归用例，把两条被驳回的结论钉成不变量（非 identity 编码全拒且不读体、resolver 消息不回显）。
- 第五轮定向复核（`http-tools-review-5.json`，HEAD `acddaf5`）判 **pass，findings 为空**：独立重推后无法推翻两条驳回（httpx 只按 `Content-Encoding` 解码、守卫在读体前拒绝；错误格式化只输出类型名），并确认 session/cookie 修复与用例判别力。该轮评审自述本地探针被策略拦截，非 2xx 响应体/`agent-tools.jsonl` 两条向量依赖控制器的探针证据与静态推理。

### 验证

- 按用户裁定只跑受影响模块：`app/tests/test_http_tools.py` **40 tests OK**、`app/tests/test_tools_bridge.py` **32 tests OK**、`tools/tests/test_docs_consistency.py` **15 tests OK**，合计 **87 tests OK**。未跑全量，也未跑其它 app 模块（本轮只触碰注册表与工具桥）。
- 真机/内存探针：压缩编码 7 种取值全部在读体前拒绝；resolver 抛含 secret 的消息只回显类型名。
- 最终代码 HEAD 为 `acddaf5`（其后仅本账本与文档提交）。
- 未实现边界：GUI/设置接线与打包未做；名字启发式保守（可能要求无关头走 keyring）；`allow_compressed: true` 明确接受解压内存风险。

## 自定义 HTTP 工具注册表工作台接线（2026-10-04，E84）

- 目标：关闭 E83 留下的产品缺口，让声明式 HTTP 工具不再只停留在 `ToolBridge`
  核心 API，而能从工作台设置加载并真正提供给聊天模型。
- `Settings` schema v1 新增可选 `http_tools_path`；旧的 schema v1 文件没有该字段时
  继续正常加载。空字符串和非字符串拒绝，相对路径按 `settings.json` 所在目录解析。
- 设置页新增注册表路径与文件选择。保存前使用与运行时相同的验证器，并保留内置工具名；
  任一条目无效时不保存设置，界面只显示去重后的错误代码，不回显 YAML 内容。
- `ChatPanel` 在项目绑定时加载注册表，以现有 `SecretStore.get` 解析
  `secret:<key_name>`，并把 `HttpToolRegistry` 注入 `ToolBridge`。模型收到
  `bridge.openai_tools()`，因此内置与注册工具共用参数校验、风险分级、写确认和摘要审计。
- 设置保存后调用 `reload_configuration()`，当前项目的工具桥立即重建，无需重启工作台。
  无效注册表只禁用全部自定义 HTTP 工具，内置只读/写入工具仍可用，并在状态栏显示
  非敏感错误代码。
- TDD 判别：新增旧 schema 兼容、路径 round-trip、非法路径类型、注册工具到达模型、
  非法注册表不泄密且 fail-closed、设置页拒绝非法注册表、保存后热重载等用例。
- 定向验证：`test_settings`、`test_http_tools`、`test_tools_bridge`、`test_chat_panel`、
  `test_gui_smoke`、`test_chat_e2e`、`test_workbench_e2e`、`test_docs_consistency`，共
  **151 tests OK**。按用户要求未运行全量测试。
- 剩余边界：HTTP 工具只提供给支持 function calling 的 OpenAI-compatible 聊天路径；
  `codex exec` 路径保持现状。Windows launcher、快捷方式与 PyInstaller 自用包尚未完成。

## 日常工作流整理与复现包路径对齐（2026-10-04，E85）

- 目标：把功能密集但入口分散的仓库整理为研究者每天能直接执行的路径，减少在
  README、设计文档、实施计划和 26 个 CLI 之间来回寻找下一步的成本。
- 新增 `docs/workflow-guide.md`，固定日常循环为「读状态 -> 处理当前 gate -> 定向检查
  -> 人工复核 -> 提交论文仓库 -> 推进阶段」，并按会议/期刊共用阶段说明产出、规范文件、
  真实命令、退出码、推进/回退、版本、工作台与收工流程。
- 根 README 改为产品入口，首屏按任务路由到安装、日常手册、能力边界、gate、设计和实施
  账本；完整工具表保留为参考，不再承担唯一的新手引导职责。`app/README.md` 同步 P2
  设置页加载与热重载现状。
- 文档核验发现并修正两处命令错误：`state` 的目标 stage 是位置参数；
  `repro-package verify` 必须显式给 `--bundle`。
- 整理过程发现脚手架与打包器的真实冲突：新论文会预建空的 `submission/repro/`，但
  `create_bundle` 原先拒绝所有已存在输出目录，导致规范路径首次打包必然失败。现在只允许
  已存在的真实空目录；非空目录、文件和符号链接仍拒绝，`--force` 的显式覆盖语义不变。
- 防漂移：文档一致性测试新增 README 必须指向日常手册、手册引用的每个 PowerShell
  包装器必须真实存在；复现包新增预建空目录判别测试。
- 定向验证：`test_repro_package`、`test_repro_package_e2e`、`test_create`、
  `test_docs_consistency`，共 **87 tests OK**。按用户要求未运行全量测试。
- 边界：手册提供默认操作顺序，不替代具体 CLI 的 `--help`；venue 主文件、引用台账、
  复现文件清单和实验命令仍需按论文实际内容填写。

## Provider provenance 与 readiness report（2026-10-04，E86）

- 目标：关闭用户复审指出的两类缺口：跨模型评审不应继续依赖硬编码执行模型或自报模型身份；日常工作需要一页式入口，把结构通过、证据存在、独立复核和科学接受分开呈现。
- `cross_review.py` 的运行路径继续从 Codex `config.toml` 解析执行模型、执行 provider、评审 provider、endpoint 哈希和 provider 配置哈希；本轮补齐 `check` 路径：家族判定改用记录中的 `model` 与 `execution_model` 重算，完整 provenance 必须包含 provider、execution_model、execution_provider、两个 endpoint sha256、provider_config_sha256 和 family_override。缺字段的旧记录保守报 `review-same-family`。
- `cross-review check` 新增 `--codex-config`。当记录 provenance 完整时，`check` 会用当前 Codex 配置重算 provider、执行模型和哈希；任何差异报 `review-provider-config-drift`，要求重跑评审。endpoint 明文仍不写入记录。
- 新增 `tools/ccfa/readiness.py` 与 `scripts/readiness.ps1`：读取 `ccfa.yaml`、当前 stage/gate、倒排 checkpoint、八类证据台账、Git dirty/commit/remote、`.github/workflows`，输出 JSON；可选 `--out` 写 Markdown 一页报告。
- Readiness profile：`minimal`、`standard`、`high-assurance`。默认 `standard`，也可在 `ccfa.yaml` 的 `workflow.profile` 指定。`minimal` 只要求新颖性台账；`standard` 要求 citation/figure/novelty/statistics/repro-environment；`high-assurance` 要求 proof/citation/figure/governance/novelty/statistics/repro-environment/human-coding 全部存在。
- 科学边界：readiness 只输出 `schema-valid`、`evidence-present`、`independently-reviewed`、`scientifically-accepted` 四维状态；`scientifically-accepted` 默认 `not-claimed`，除非存在外部人类接受台账。工具不会把“材料齐全”升格为“结论正确”。
- 定向验证：`tools.tests.test_cross_review` **65 tests OK**，`tools.tests.test_readiness` **7 tests OK**。随后还需随 README/脚本清单更新跑 `test_docs_consistency` 与 `test_scripts`。
- 边界：GitHub 私有仓库、branch protection、Actions、Zenodo/OSF 和第二机器复现没有被自动创建；这些是外部副作用，需用户明确确认后再接线。Readiness 只能检测本地是否已有 remote/workflows，不能证明远端策略已经配置正确。

## Readiness gate 聚合与 provenance fail-closed（2026-10-05，E87）

- 目标：关闭第二轮复检发现的假绿：readiness 只检查台账存在与 pending 状态，没有执行
  `repro_env`、`argument_audit`、`cross_review` 等下游 gate，导致
  `repro-env-lockfile-drift` 存在时仍可能 `ready=true`。
- `readiness` 新增 `gate-verified` 维度，并实际调用 profile 对应的检查器：
  novelty、statistics、repro-environment、argument-audit、governance、human-coding，
  以及输入存在的 LaTeX structure、trace-claims、citation-guard、final-check、
  cross-review。`gate_results` 记录每个 gate 的 status、problem/advisory count 和
  problem codes；任一 gate problem 会进入 blocking 并使 `ready=false`。
- `evidence-present` 保持 presence-only 语义；缺少必需台账时 `gate-verified` 是
  `not-run`，不再与“gate 已执行且通过”混为一谈。standard profile 下
  argument-audit 失败会把 `independently-reviewed` 显示为 `pending-human-review`。
- `cross_review.check` 收紧 fail-closed：缺 provider、execution_model、
  execution_provider、endpoint/config 哈希时统一报 `review-provenance-incomplete`；
  `family_override` 只能解释同族评审，不能替代 provenance。删除硬编码
  `DEFAULT_EXECUTION_MODEL`，家族判定必须由记录中的真实模型字段重算。
- `stats_plan` 支持 `analysis_type: descriptive`：描述性研究可对 alpha、effect_size、
  target_power、sample_size、seeds 写 `not-applicable`；推断性设计仍拒绝该值，避免
  通过填写虚假的 `effect_size=1.0`、`target_power=0.8` 机械过关。
- 论文仓库 `data/repro-environment.yaml` 的 lockfile 哈希已从
  `cf503d5b...` 修正为实际的 `7481a005...`；`data/statistics-plan.yaml` 改为
  descriptive，不再伪造功效字段。
- 定向验证：`tools.tests.test_readiness` 11 tests OK、`tools.tests.test_cross_review`
  65 tests OK、`tools.tests.test_statistics` 9 tests OK。真实论文 readiness 现在
  `gate-verified=problem`，明确列出 proof/citation/figure 人工审计未完成与旧
  cross-review provenance/stale/prompt-hash 问题。

## CI 参数契约、governance 占位值与 bundle 重建（2026-10-05，E88）

- 复现并修复 `paper-check` 的 P0 错误：两个 workflow 原先用 `--paper-root` 调用
  `citation_guard` / `trace_claims`，两者都退 2。现在分别使用真实参数；
  `trace_claims` 新增 `--manuscript`，一次扫描目录下全部 `.tex`。
- `tools/tests/test_github_workflows.py` 新增 workflow↔CLI 守护：实际执行 workflow
  中的每条 `python -m ccfa.*`，发现 argparse 的 unrecognized/required/invalid-choice
  即失败。
- `governance` 新增 `governance-placeholder`，拒绝 pending/TBD/todo/placeholder/
  to-be-determined 占位文本。论文现有 COI、查重工具与披露联系人因此正确报 3 problems。
- `cross_review run` 删除 `DEFAULT_MODEL` 与 `DEFAULT_EXECUTION_MODEL`；评审模型
  `--model` 必填，执行模型/provider 仍从 Codex config 解析。缺少 provenance 的旧记录
  fail closed。
- `readiness` 现在执行 `repro_package.verify_bundle`。论文 `submission/repro` 已重建：
  60 个文件哈希刷新，`requirements` 从 `null` 改为指向 `requirements.txt` 并记录 SHA-256。
  `repro_package verify` 当前 0 problems，只保留“无容器隔离”的 advisory。
- `doctor` 现在始终输出 problem/advisory 汇总，并提示投稿前使用 `--strict`。
- 定向验证：workflow 8 tests、governance 10 tests、trace-claims 16 tests、
  cross-review 66 tests、readiness 12 tests 均通过；真实 `repro_package verify`
  0 problems。

## 全量测试红灯与 provider 假警报修复（2026-10-05，E89）

- BUG-NEW-1：`cross_review.run_review` 改为强制显式模型后，两个 E2E 仍在旧调用形态，
  导致全量 1209 tests 中有 2 个 error，而 CI targeted 列表没有覆盖这两个模块。
  修复：两个 E2E 显式传 `model=deepseek-v4-pro` 和隔离 `codex_config`；CI targeted
  列表加入 `test_automation_e2e`、`test_evidence_integrity_e2e`，workflow 守护测试
  固定这两个模块必须存在。
- BUG-NEW-2：doctor provider probe 只解析 `data[].id`，而本地代理返回
  `models[].slug`，造成配置模型已存在却报 false negative。修复：新增
  `_model_ids`，同时解析 `data[].id`、`models[].id`、`models[].slug`。
- 验证：全量工具测试 `Ran 1211 tests, OK`；真实 doctor 返回
  `functional provider 配置模型可用`，剩余 advisories 为 Docker daemon、
  WorkBuddy、Zotero。

## Cross-review 相对路径与安全 diff 扫描（2026-10-05，E90）

- 重跑 cross-review 时复现 P0：`cross_review.run_review` 接收相对
  `--paper-root` 后，`codex -C` 的目录与 `--output-schema/-o` 路径一起变为相对，
  codex 切换目录后把路径拼成两遍。修复：`run_review` 与 `check_review` 入口统一
  `Path(paper_root).resolve()`；新增相对 paper-root 回归测试，断言 `-C`、
  `--output-schema`、`-o` 均为绝对路径。
- 重跑 cross-review：记录现在包含当前输入哈希、prompt hash、execution/review
  provider、endpoint/config hashes 与显式 same-family override。记录不再 stale，
  也不缺 provenance。评审 verdict 为 `blocking`，因为 proof/citation/figure 台账
  仍为 pending；check 另有 2 条 `review-uncited-blocking`。旧 `pass` 不再冒充有效
  评审，真实跨族仍需第二个 family provider。
- Codex Security diff scan（`dff6cd4..cb8645a`，scanId
  `3e2db666-9c2b-4e48-83dc-df8e46b1f24d`）完成：0 reportable findings。威胁模型
  指出 provider `functional` 仍只是模型列表成员判断，不等价于真实推理能力验证；
  该限制保留为开放问题。
- 本地服务：Zotero `127.0.0.1:23119` 已进入 LISTEN，但 API 请求仍报错；Docker
  Desktop 进程已启动但 Linux engine 不可达；WorkBuddy `8787` 仍无监听。

## Claim 中心研究循环升级（2026-10-05，E91）

- 新增 `tools/ccfa/research_ledgers.py` 与 `scripts/research-ledgers.ps1`，把
  benchmark 中的 P0/P1 结构落成机器可读 gate：
  `claim-registry`、`assumptions-limitations`、`venue-checklist`、
  `artifact-provenance`、`exploration-graph`、`cost-ledger`、`risk-register`。
- claim registry 现在串起 proof、experiment、figure、citation、assumption 与
  limitation；支持 theoretical/empirical/descriptive 类型，并对 supported
  theoretical claim 要求 proof、supported empirical claim 要求 experiment。
- assumptions/limitations 要求双向链接，拒绝重复 id；experiment 只接受日志中的真实
  `run_id`，不再接受任意 JSON 文件名 stem。
- artifact provenance 对 model/mixed 产物要求 model_family 与 run_id/source_sha256；
  探索图要求非空 claim/run 绑定；成本、风险台账检查有限数值和 pending 占位。
- 新论文模板创建七个新台账；空台账是可解析的“未填写”状态并产生
  `research-ledger-empty` advisory，不伪造已填写证据。
- readiness 新增 `research-ledgers` gate，`evidence-present` inventory 也列出全部
  七个新台账；standard/high-assurance 缺少任一核心台账即报
  `research-ledger-missing`。
- 独立 code review 发现并修复：malformed YAML 类型崩溃、只强制两个台账、模板无效、
  empirical/theoretical 证据错配、单向/重复链接、伪 run id、artifact 自报、
  探索条目空绑定、claim policy 分叉等 10 项问题。
- cross-review 实行 `can drive, never acquit`：同族模型返回 pass 时，记录保留
  `model_verdict=pass`，但 effective `verdict=blocking`，因此 override 不能开释。
- 独立复审发现并修复两个 fail-open：`codex_config_path` 从 provenance 中删除会跳过
  配置漂移核验；`model_verdict` 与 effective `verdict` 不一致时不报错。现在前者报
  `review-provenance-incomplete`，后者报 `review-record-invalid`。
- 验证：`tools.tests.test_research_ledgers` 18 tests OK；全量工具测试
  `Ran 1236 tests, OK`。

## 测试影响选择与 CI 降频（2026-10-05）

- 新增 `tools/ccfa/test_impact.py` / `scripts/test-impact.ps1`：从
  `base...HEAD` 和本地工作树收集改动，按显式映射选择最小测试集。
- fail closed 规则：未知路径、删除的测试文件、`tools/ccfa/cli.py`、
  `tools/ccfa/stages.py`、依赖清单等共享边界回退对应 suite 全量测试。
- tools/app 分 suite；app 选择使用 `app/.venv`、`PYTHONPATH=app;tools` 与
  `QT_QPA_PLATFORM=offscreen`。
- CI 改为 PR/push 跑影响集，每晚 schedule 和 `workflow_dispatch` 跑全量；
  checkout 使用 `fetch-depth: 0`，PR 以 base SHA 计算 diff。
- README、workflow guide、PR 模板与设计文档同步；新增
  `tools/tests/test_test_impact.py`，覆盖精确映射、未知回退、删除回退、
  dotfile 路径、工作树未跟踪文件和运行命令选择。

## Pilot 筛选与双循环实验账本（2026-10-05）

- 新增 `data/experiment-loop.yaml`、`tools/ccfa/experiment_loop.py` 与
  `scripts/experiment-loop.ps1`，补齐对标报告 P1-5 的 pilot 与内外层循环。
- `check` 验证 ideas / inner_loop / outer_loop 的枚举、placeholder、终态理由、
  pilot 预算、metric、kill criterion，以及 claim/run id 的真实引用。
- `next` 输出 pilot、内层和外层当前待办动作，只读，不自动运行实验或修改结论。
- 纯 SoK 支持 `not_applicable: true`，但必须有非空具体 reason；空台账只产生
  advisory，不伪装完成。
- readiness standard/high-assurance 接入第八类台账，新论文模板自动生成。
- 新增 `tools/tests/test_experiment_loop.py` 9 条覆盖；create/readiness/scripts/
  docs 测试同步。

## 投稿后产出物契约（2026-10-05）

- 新增 `data/post-submission.yaml`、`tools/ccfa/post_submission.py` 与
  `scripts/post-submission.ps1`，补齐对标报告 P1-9 的 rebuttal/resubmit/talk。
- `rebuttal` 校验回复矩阵路径、承诺列表与新增证据 run id；`resubmit` 校验
  venue 差异表、改写章节与 evidence；`talk` 校验 slide 大纲、claim id、
  figure id 与 talking points。
- 三个 section 支持 not-started/in-progress/complete/not-applicable；
  不适用必须写具体 reason，占位文本与悬空引用均为 problem。
- readiness 在台账存在时执行 `post-submission` gate；新论文模板预置空台账，
  空台账只产生 advisory，不伪装完成。
- 新增 `tools/tests/test_post_submission.py` 7 条覆盖；create/readiness/scripts/
  docs 测试同步。

## 六维 rigor rubric（2026-10-05）

- 新增 `data/rigor-rubric.yaml`、`tools/ccfa/rigor.py` 与
  `scripts/rigor-rubric.ps1`，落地对标报告 P2-13。
- 六个固定维度：evidence_relevance、falsifiability、scope、coherence、
  exploration_integrity、methodology；每维必须有 0..4 分、非占位理由和证据。
- 证据必须是 claim id、真实 run id 或仓库内已有文件；悬空引用为 problem。
- `complete` 只允许 human/mixed reviewer；model 只能 `model-advisory`，
  不能开释；high-assurance 使用 `--require-complete`。
- readiness 在台账存在时运行 `rigor-rubric` gate；新论文模板预置台账。
- 新增 `tools/tests/test_rigor.py` 11 条覆盖；create/readiness/scripts/docs
  测试同步。

## Proof orchestration 与跨天续跑（2026-10-05）

- 新增 `data/proof-campaign.yaml`、`tools/ccfa/proof_orchestrator.py` 与
  `scripts/proof-orchestrator.ps1`，落地对标报告 P2-11。
- campaign 绑定 claim、theorem 与多次 attempt；attempt 记录策略、状态、结果、
  失败原因、证据和 next_action，支持 open/blocked/proved/refuted/abandoned。
- `proved` 必须指向 proof-audit 中真人 verified 的 review；模型 reviewer 不能
  开释；refuted 需要 counterexample，abandoned 需要理由。
- `next` 只读输出当前待办，不自动推进证明；high-assurance 使用
  `--require-complete` 拒绝仍为 open/blocked 的 campaign。
- 新增 `tools/tests/test_proof_orchestrator.py` 7 条覆盖；create/readiness/
  scripts/docs 测试同步。

## 周期性工作流自评（2026-10-05）

- 新增 `tools/ccfa/meta_optimize.py` 与 `scripts/meta-optimize.ps1`，落地
  对标报告 P2-14。
- 聚合多个 friction store 的 category+component 重复模式，以及 readiness
  `gate_results` 中的 gate+problem-code 重复失败。
- 达到 `--min-count` 的模式输出候选提案，status 固定为 `proposed`；工具只读，
  不自动改 skill、gate、代码或论文。
- 支持 Markdown/JSON 输出、原子写和不覆盖已有报告。
- 新增 `tools/tests/test_meta_optimize.py` 5 条覆盖；scripts/docs/test-impact
  测试同步。

## Artifact badge 与长期归档（2026-10-05）

- 新增 `data/artifact-badge.yaml`、`tools/ccfa/artifact_badge.py` 与
  `scripts/artifact-badge.ps1`，落地对标报告 P2-12。
- 校验 available/evaluated/reusable badge、证据、理由、code/data license、
  DOI 与 archive_url；evaluated 需要独立真人 reviewer，reusable 需要
  reuse_context。
- standard profile 在台账存在时运行结构 gate；high-assurance 使用
  `--require-verified` 要求三类 badge 与归档证据完整。
- 新论文模板预置台账；新增 `tools/tests/test_artifact_badge.py` 6 条覆盖；
  create/readiness/scripts/docs 测试同步。

## Research Wiki 与跨项目记忆（2026-10-05）

- 新增 `library/wiki/README.md`、`tools/ccfa/research_wiki.py` 与
  `scripts/research-wiki.ps1`，落地对标报告 P2-10。
- 条目是带固定 YAML frontmatter 的 Markdown；校验 id、kind、status、
  tags、projects、evidence、related 与 updated_at。
- `related` 必须解析到真实 id；evidence 使用 run/file/doi/url/claim/project
  前缀；重复 id、悬空链接、非法枚举与缺失字段都报 problem。
- `index` 生成带 body sha256 的确定性 JSON，`search` 做本地大小写不敏感
  子串搜索；Markdown 是 source of truth，索引可重建。
- 新增 `tools/tests/test_research_wiki.py` 8 条覆盖；scripts/docs/test-impact
  测试同步。

## 跨论文 dashboard（2026-10-05）

- 新增 `tools/ccfa/dashboard.py` 与 `scripts/dashboard.ps1`，扫描 `papers/`
  下所有含 `ccfa.yaml` 的独立论文仓库，复用 readiness 报告生成一页总览。
- 汇总 ready/blocked、人工 pending、dirty worktree、remote/CI 状态，并把第一条
  blocking 作为 next_action；支持 Markdown/JSON 与不覆盖落盘。
- 新增 `tools/tests/test_dashboard.py` 3 条覆盖；scripts/docs/test-impact/
  readiness 相关测试同步。

## 源码对齐第一切片：research-state（2026-10-05）

- 按 `Orchestra-Research/AI-Research-SKILLs` 的 `research-state.yaml`
  对齐项目级 literature / hypotheses / experiments trajectory / outer_loop /
  workspace 状态。
- 新增 `tools/ccfa/research_state.py` 与 `scripts/research-state.ps1`。
- 校验 hypothesis parent、trajectory 的真实 run_id 与 total_runs 一致性、
  outer-loop 方向枚举、workspace 路径存在性；`next` 选择未闭环 hypothesis。
- 新增 `tools/tests/test_research_state.py` 7 条覆盖；scripts/docs/test-impact
  测试同步。

## 源码对齐第二切片：ARA draft compiler（2026-10-05）

- 按 `AI-Research-SKILLs` 的 ARA compiler / ara-schema / Seal Level 1
  validation checklist，新增 `tools/ccfa/ara_compile.py` 与
  `scripts/ara-compile.ps1`。
- `compile` 生成 PAPER.md、logic/、src/、trace/、evidence/ mandatory 文件；
  claim registry 映射为 C01+，run 映射为 E01+，exploration graph 映射为
  nested YAML DAG。
- 无法从结构化输入获得的 concepts、solution、heuristics、code stub 保持
  draft gap，并写入 `compile-report.json`；`seal_level1_ready` 不会伪造为 true。
- `validate` 检查目录、mandatory file、计数、trace 节点与 cross-layer 条件。
- 新增 `tools/tests/test_ara_compile.py` 4 条覆盖；README、workflow guide、
  设计文档、CI 与 test-impact 映射同步。
- 后续补 `ara-input/` 语义输入通道（problem、concepts、solution、
  related_work、experiments、configs、trace、evidence、code stubs），使
  compiler 可在不编造内容的前提下真正达到 Seal Level 1。

## 源码对齐第三切片：ARIS proof run directory（2026-10-05）

- 按 ARIS `skills/proof-orchestrator/SKILL.md`，新增 `tools/ccfa/proof_run.py`
  与 `scripts/proof-run.ps1`。
- `materialize` 从 proof campaign 创建 run directory 和 ARIS 文件契约；
  目录必须位于 paper root 内，默认拒绝覆盖。
- `check --notation-required` 校验 notation scorecard；核心语义对象保留
  必须 100%，undefined symbols 与 symbol collisions 必须为 0。
- `check --require-closed` 要求 `READY_FOR_USER`、非 draft final 和
  `Top-down derivation structure: PASS`。
- 新增 `tools/tests/test_proof_run.py` 5 条覆盖；scripts/docs/CI/test-impact
  同步。

## 源码对齐第四切片：ARIS typed graph wiki（2026-10-05）

- 按 ARIS `skills/research-wiki/SKILL.md`，扩展 `research_wiki.py` 的 kind
  到 paper/idea/experiment/claim/gap/source/decision/dead-end/method/result。
- 新增 `graph/edges.jsonl` 和八类 typed edge：extends、contradicts、
  addresses_gap、inspired_by、tested_by、supports、invalidates、supersedes。
- `add-edge` 校验真实端点与非空 evidence 后追加；`check`/`index` 校验边；
  `query-pack` 生成实体、边和 kind counts 的紧凑摘要。
- Markdown 实体与 edges.jsonl 是 source of truth；index/query pack 是生成物，
  query pack 已加入 gitignore。
- `tools/tests/test_research_wiki.py` 扩展到 11 条覆盖；README、workflow guide、
  设计文档、CI/test-impact 同步。
- 后续补 BibTeX sync、index/gap_map 重建和 append-log，扩展到 13 条测试，
  覆盖自动 ingest 与 catalog 生成。

## 源码对齐第五切片：hash-chained run ledger（2026-10-05）

- 按 academic-research-skills `run_ledger.schema.json`，新增
  `tools/ccfa/run_ledger.py` 与 `scripts/run-ledger.ps1`。
- `sync` 在 `experiments/log/run-ledger.jsonl` 追加 peer ledger；`check`
  检测 JSON 损坏、seq、prev_hash/hash、缺失、orphan 和 stale record。
- entry 记录 run record 的 canonical SHA-256；同一 run_id 更新时追加新 entry，
  旧记录永不覆盖。
- readiness 在 ledger 存在时执行可选 run-ledger gate。
- 新增 `tools/tests/test_run_ledger.py` 5 条覆盖；scripts/docs/CI/test-impact
  同步。

## 源码对齐第六切片：ARIS review loop state（2026-10-05）

- 按 ARIS `skills/auto-review-loop/SKILL.md`，新增
  `tools/ccfa/review_loop.py` 与 `scripts/review-loop.ps1`。
- 维护 review-loop-state.json、reviewer-memory.md 和 append-only
  ACQUITTAL_LOG.jsonl；同族/未知族 pass 强制 blocked，不能 completed。
- `check` 检测 self-acquittal、review stale、缺 memory 与 malformed
  acquittal log；`next` 输出下一动作。
- readiness 在 state 存在时执行可选 review-loop gate。
- 新增 `tools/tests/test_review_loop.py` 4 条覆盖；scripts/docs/CI/test-impact
  同步。
- 后续补 `drive` 注入式 fix/review runner 与 3 条测试，支持按轮执行并维持
  fail-closed。

## 源码对齐第七切片：risk matrix 与 data flows（2026-10-05）

- 按 academic-research-skills `RISK_REGISTER.md` / `DATA_FLOWS.md`，新增
  `tools/ccfa/governance_map.py` 与 `scripts/governance-map.ps1`。
- capability status 固定为 DESIGNED/NOT_RUN/MEASURED/MIXED；risk 必须引用真实
  control 并填写 residual_gap。
- data flows 覆盖 network endpoint、发送内容、凭据、off switch，以及本地
  store 的 path/content/lifetime/delete。
- `check` 拒绝未知 control、非法状态和明文凭据；`render` 生成
  `docs/data-flows.md`。
- 新增 `tools/tests/test_governance_map.py` 5 条覆盖；create/readiness/
  scripts/docs/CI/test-impact 同步。

## 源码对齐第八切片：open-science immutable artifact（2026-10-05）

- 按 open-science 的 immutable artifact、provenance、`.science` package 概念，
  新增 `tools/ccfa/artifact_store.py` 与 `scripts/artifact-store.ps1`。
- 使用 SHA-256 内容寻址 blob 和递增 manifest version，拒绝原地覆盖旧版本。
- `verify` 检查 blob 缺失、hash 不匹配和 version 跳号；`replay` 输出版本与
  run provenance；`package` 生成包含 manifest、blobs、run ledger、provenance
  和 verify receipt 的 `.science` zip。
- readiness 在 manifest 存在时执行可选 artifact-store gate。
- 新增 `tools/tests/test_artifact_store.py` 6 条覆盖；scripts/docs/CI/
  test-impact 同步。

## 源码对齐第九切片：resubmit 与 talk pipeline（2026-10-05）

- 按 ARIS `RESUBMIT_AND_TALK.md`，新增 `resubmit_pipeline.py` 与
  `talk_pipeline.py` 及对应 PowerShell 入口。
- resubmit 校验 source/target 隔离、frozen bib hash、无新增 run、
  forbidden path 未变化和 anonymity leak。
- talk 校验 slide→claim/figure 解析、talking points、speaker notes、Q&A，
  并可 render 汇报 outline。
- readiness 在对应 plan 存在时执行可选 resubmit/talk gate。
- 新增 resubmit 5 条、talk 4 条测试；scripts/docs/CI/test-impact 同步。

## 源码对齐第十切片：passport ledger 与 citation calibration（2026-10-05）

- 按 academic-research-skills 的 passport run ledger，新增
  `passport_ledger.py` / `passport-ledger.ps1`，保存 initial instructions、
  checkpoints、partial answers、tool receipts、progress 与 file references。
- entry 使用 seq、data、prev_hash、hash 的 append-only hash chain；check 检测
  链断、字段缺失与非法 kind。
- 按 citation calibration，新增 `citation_calibration.py` /
  `citation-calibration.ps1`，从 gold/prediction JSONL 计算 TP/FP/TN/FN、
  FNR/FPR，并按阈值 fail closed。
- readiness 在 passport ledger 存在时执行可选 gate。
- 新增 passport 4 条、calibration 2 条测试；scripts/docs/CI/test-impact 同步。

## 源码对齐第十一切片：官方 venue checklist fixture（2026-10-05）

- 新增 `checklists/neurips-paper-checklist.yaml` 与
  `checklists/arr-responsible-nlp.yaml`。
- 新增 `venue_fixtures.py` / `venue-fixtures.ps1`，支持 list/check/seed。
- `seed` 生成 pending `venue-checklist.yaml`，evidence、owner、status 不伪造，
  必须由作者逐条完成。
- 新增 `tools/tests/test_venue_fixtures.py` 4 条覆盖；scripts/docs/CI/
  test-impact 同步。

## 源码对齐第十二切片：open-science session replay（2026-10-05）

- 新增 `session_replay.py` / `session-replay.ps1`，串联 passport ledger、
  run-ledger.jsonl、artifact store manifest 与 review-loop state。
- `check` 检测 artifact run_id 是否悬空；`render` 生成静态 HTML timeline。
- replay 是只读证据视图，不执行代码、不恢复凭据，也不宣称科学正确性。
- 新增 `tools/tests/test_session_replay.py` 3 条覆盖；scripts/docs/CI/
  test-impact 同步。
