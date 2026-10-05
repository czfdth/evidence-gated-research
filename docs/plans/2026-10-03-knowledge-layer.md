# knowledge-layer 实施计划（共享文献库索引 + 研究记忆）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成知识层 v1：（1）共享文献库 `library`——以 `refs.bib` 与逐篇 notes 为真相，用 SQLite FTS5 (trigram) 建立可检索索引，派生索引与真相可互相核对；（2）研究记忆 `memory`——把选题想法与**走不通的死路**（含 `reopen_if`）记成可脚本读写的固定字段条目，选题前可检索、可反重复、可在条件变化时重新打开。

**Architecture:** 两个工具、各自独立。
`library` 的真相是 `library/refs.bib` + `library/notes/<key>.md`；`library/index.db` 是**派生数据**（可覆盖重建，是"不覆盖"契约的具名例外），meta 表记录来源 sha256；索引缺失或过期时 `search` 拒绝服务（退 2），而不是拿过期结果冒充当前结果。
`memory` 的真相是论文目录下的 `memory/ideas.md` 与 `memory/dead-ends.md`（YAML 列表，`#` 开头的中文标题行是合法 YAML 注释）；写入前校验、**读取时逐条重校验**，一条坏条目不得打断整轮审计。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v6：§8.1–8.4、§10、§6.1.1、§12）
**账本：** `<repo-root>/.superpowers/sdd/2026-10-03-evidence-tracking/progress.md`（Ruling E33–E37）

## 本层与已完成工具的定位差异

| 维度 | 检查类工具（前六个） | 写盘工具（provenance / run-log / friction-log） | 本层 |
| --- | --- | --- | --- |
| 真相 | 输入文件 | 自建 store | **外部真相 + 派生索引**（library）/ 自建 store（memory） |
| 主要风险 | 漏报误报 | 半截 JSON、覆盖 | **派生数据与真相漂移后仍被当作当前结果** |
| 对策 | 注入点判别力 | 原子写 + 不覆盖 | 来源哈希 + 过期拒绝服务（E33） |

## Global Constraints

- 仓库根：`<repo-root>`
- 退出码：`0` 通过/完成，`1` 发现问题（仅 `check` 类子命令），`2` 工具自身出错。
- 写盘契约：原子写（临时文件 + `os.replace`）、`OSError` → `ValueError` → 2；`memory` 的 `add-*` 不覆盖已有文件内容（追加），`library index` 是唯一允许覆盖的写路径且必须在 `--help` 与工具文档里写明理由。
- strip / 校验：store 内 `schema_version` 必须等于 1；`memory` 枚举（`status`）与 `dead-ends` 的必填字段在**读取时重新校验**（E20/E25 教训）。
- 一条坏记录不得打断整轮审计（九条规则第 5 条）：`memory check` 报全所有条目的问题；`library check` 报全所有不一致。
- 查询文本永不当作 FTS5 语法解释（E34）；查询无命中是完整答案而非问题（退 0，空结果）。
- UTF-8 无 BOM；ASCII 标识符与注释；中文只在面向用户的消息与测试数据里。
- 基线：写计划时 HEAD = `2ff989a`，工作树干净，**447 tests OK**；每个任务的 BASE 以派发时 HEAD 为准。
- 测试命令：`& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
- 既有接口：`ccfa.cli.Problem` / `emit` / `tool_error` / `save_text_atomically`；`ccfa.bib.load_entries`。
- 环境已实测：venv 内 SQLite **3.53.1**（`trigram` 可用；2 字中文查询不命中，须 LIKE 回退）；`PyYAML`、`bibtexparser 2.1.0` 可用。

## Non-goals（明确不做，不做静默丢弃）

1. **语义检索**（向量库）：§8.4 的触发条件是"全文检索出现明显召回不足"，当前不提前引入依赖。
2. **PDF 全文入库**：§8.3 的 schema 没有全文列；v1 索引字段是 key/title/authors/year/venue/abstract/notes/path。PDF 文本抽取留到有实测召回缺口时再评估。
3. **§8.2 第 3 条"实验结果回写 claim 状态"**：当前没有 claim registry（claim 与数字的对应由 `trace-claims` 的 `\dataval` 承担）。没有 claim 存储而先造"状态回写"会是无处安放的字段，推迟到"实验-结论"层立项，见 Ruling E36/E37。
4. **跨论文记忆聚合**：v1 记忆按 §10 放在各自论文目录；跨论文聚合参考 `friction-log aggregate` 的既有模式，等有第二篇真实论文时再做。

---

### Task 1: `library` 的索引与检索（FTS5 trigram + 短查询回退 + 过期拒绝服务）

**Files:**
- Create: `tools/ccfa/library.py`
- Modify: `tools/ccfa/bib.py`（新增 `load_records`，`load_entries` 改为其薄封装，行为不变）
- Create: `tools/tests/test_library.py`
- Modify: `tools/tests/test_bib.py`（若不存在则并入 `test_library.py` 中的一层：先确认现有测试文件名）

**Interfaces:**
- Produces（`ccfa.bib`）:
  - `BibRecord = NamedTuple(key, title, authors, year, venue, abstract, doi)`
  - `BibFile = NamedTuple(records: dict[str, BibRecord], duplicate_keys: list[str])`
  - `load_records(path: Path) -> BibFile`（缺失/解析失败 → `ValueError`；重复 key 保留第一条并如实记录在 `duplicate_keys`）
  - `load_entries(path) -> dict[str, BibEntry]` 保持现签名与语义（由 `load_records` 派生）
- Produces（`ccfa.library`）:
  - `SCHEMA_VERSION = 1`
  - `build_index(library_dir: Path) -> dict`（读 `refs.bib` + `notes/*.md`，原子重建 `index.db`，返回 `{"entries": N, "duplicate_keys": [...], "stray_notes": [...]}`）
  - `search_index(library_dir: Path, query: str, limit: int = 20) -> dict`（缺索引/过期 → `ValueError`；≥3 字符 FTS5 短语，≤2 字符 LIKE 回退）
  - `main(argv: list[str]) -> int`

**index.db schema（唯一事实源，写在模块 docstring 里）**

```sql
CREATE TABLE meta (schema_version INTEGER, refs_sha256 TEXT, notes_sha256 TEXT,
                   built_at TEXT, entry_count INTEGER);
CREATE VIRTUAL TABLE papers USING fts5(
  key, title, authors, year, venue, abstract, notes, path, tokenize='trigram');
```

**notes 约定:** `library/notes/<bibkey>.md`；文件 stem 必须能对上 `refs.bib` 的 key。对不上的 note 是事实，索引照建（退 0），但 `build_index` 返回 `stray_notes` 且 stderr 打 summary；由 Task 2 的 `check` 报 problem。

**判定表**

| 条件 | 结果 |
| --- | --- |
| `refs.bib` 缺失/解析失败 | `ValueError` → 2 |
| 查询长度 ≥ 3（去空白后） | FTS5 `MATCH`，查询被包成双引号短语，内部 `"` 翻倍 |
| 查询长度 ≤ 2 | `LIKE %q%` 且 `%`/`_` 以 `ESCAPE '\'` 转义 |
| `index.db` 不存在 | `ValueError` → 2，消息点名"先运行 library index" |
| `refs.bib` 或 notes 的 sha256 与 meta 不符 | `ValueError` → 2，消息点名过期 |
| 查询无命中 | 退 0，`results: []` |
| `index` 重建 | 原子替换 `index.db`（`.tmp` 不留残骸） |

- [ ] **Step 1: 写失败测试**（约 16 条）

必须覆盖：`load_records` 取到 authors/year/venue/abstract；重复 key 进 `duplicate_keys` 且不抛异常；`load_entries` 行为不变（现测试继续过）；`build_index` 后 meta 的两枚 sha256 等于实测源文件哈希；trigram 中文 3 字命中、2 字走 LIKE 命中（**判别力核心**：2 字若错走 FTS5 必 0 命中）；含 `"` 与 `-`/`NOT` 的查询被当作字面量（旧式裸 MATCH 会抛 `sqlite3.OperationalError` 或把 NOT 当操作符）；`%`/`_` 在短查询里不被当通配符；索引缺失 → `ValueError`；篡改 `refs.bib` 一字节后 `search_index` → `ValueError`；无命中退 0 空列表；`index` 重建覆盖已有 db 且无 `.tmp` 残留；notes 文件参与命中；`path` 列在有 PDF 时写相对路径、无 PDF 时为空串。

- [ ] **Step 2: 运行测试确认失败**（Expected: `ModuleNotFoundError: No module named 'ccfa.library'`）

- [ ] **Step 3: 实现**

`build_index` 先读全部输入、算出哈希、在 `<dir>/index.db.tmp` 建库写数据、关闭连接后 `os.replace`。`search_index` 先做新鲜度校验再执行查询。查询参数一律走 `?` 占位符。输出 JSON：`{"query":..., "mode":"fts"|"like", "results":[{"key","title","year","venue","path"}...]}`，`--limit` 默认 20。

- [ ] **Step 4: 运行测试确认通过**

Expected: 447 + 约 16 条全绿。

判别力检查（必须实测失败，不允许纸面声明）：
1. 把短查询回退去掉（一律 FTS5）→ "2 字中文命中"用例必须失败；
2. 把新鲜度校验去掉 → "篡改 refs.bib 后 search 报错"用例必须失败；
3. 把短语转义去掉（裸 MATCH）→ 含 `"` / `NOT` 的用例必须失败。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/library.py tools/ccfa/bib.py tools/tests/test_library.py
git commit -m "feat: index the shared library with sqlite fts5 trigram search"
```

---

### Task 2: `library check` 只读审计（缺失 / 过期 / 两向不一致 / 重复 key / 游离 note）

**Files:**
- Modify: `tools/ccfa/library.py`
- Modify: `tools/tests/test_library.py`

**Interfaces:**
- Produces: `check_library(library_dir: Path) -> list[Problem]`；`main` 新增 `check` 子命令。

**Task 1 评审结转（必须在本任务内处理）**

1. `library search --help` 需要自己的 description，写明两条边界：索引**不含 PDF 全文**；查询字段是 key/title/authors/year/venue/abstract/notes/path（当前清单漏了 key 与 path，属不完整声明）。
2. `path` 字段改为**查询时按文件系统现状解析**（`papers/<key>.pdf` 存在则给相对路径，否则空串），不再把建索引时的快照当作现状——否则新增/删除 PDF 后 path 会滞后。规则写进 docstring 与 help：E34 的新鲜度只对 refs.bib 与 notes 负责，path 是查询期事实。补两条用例：建索引时无 PDF → search 的 path 为空；随后放入 PDF（不重建索引）→ search 的 path 立刻出现；删除后 → 恢复为空。

**判定表（每条一个 code，全部报全，不早退）**

| 条件 | 结果 |
| --- | --- |
| `index.db` 不存在 | problem `index-missing` |
| meta 任一 sha256 与当前源不符 | problem `index-stale` |
| `refs.bib` 有 key 而索引没有 | problem `index-entry-missing` |
| 索引有 key 而 `refs.bib` 没有 | problem `index-entry-extra` |
| `refs.bib` 内重复 key | problem `duplicate-bib-key` |
| `notes/<stem>` 对不上任何 key | problem `note-without-entry` |
| 索引可读但 `schema_version != 1` | problem `index-schema-version` |
| `refs.bib` 本身缺失/解析失败 | `ValueError` → 2（无法审计） |

- [ ] **Step 1: 写失败测试**（约 9 条，逐一构造上述条件；"两条同时存在"的用例断言**两条都出现**）

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现**（只读：实现后须有字节级"check 不写盘"用例）

- [ ] **Step 4: 运行测试确认通过**

判别力检查：把 `index-stale` 判定改成只看 meta 是否存在 → 篡改来源的用例必须失败；把 check 改成遇第一条即 return → "两条都出现"用例必须失败。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/library.py tools/tests/test_library.py
git commit -m "feat: audit library index against its bib and notes sources"
```

---

### Task 3: `memory` 的 store 与 `add-idea` / `add-dead-end` / `list`

**Files:**
- Create: `tools/ccfa/memory.py`
- Create: `tools/tests/test_memory.py`

**Interfaces:**
- Produces:
  - `VALID_IDEA_STATUSES = ("active", "abandoned", "merged")`
  - `IDEAS_FILE = "memory/ideas.md"`、`DEAD_ENDS_FILE = "memory/dead-ends.md"`
  - `load_memory(path: Path) -> list[dict]`（缺失 → `[]`；YAML 语法错误 / 顶层非列表 → `ValueError`）
  - `save_memory(path: Path, entries: list[dict]) -> None`（原子写；`allow_unicode=True`、字段顺序固定、末尾换行）
  - `add_idea(paper_root, *, idea, date, status="active", notes=None) -> dict`
  - `add_dead_end(paper_root, *, idea, reason, evidence, reopen_if, date) -> dict`
  - `list_memory(paper_root, *, kind="all", status=None) -> dict`
  - `main(argv: list[str]) -> int`

**条目形状（字段顺序即写盘顺序）**

```yaml
# 研究记忆（脚本读写，勿改字段名）
- id: I1
  date: "2026-10-03"
  idea: "用对比学习替代现有多任务损失"
  status: active
  notes: null
```

```yaml
# 反重复记忆（脚本读写，勿改字段名）
- id: DE1
  date: "2026-10-03"
  idea: "用对比学习替代现有多任务损失"
  reason: "消融显示增益来自 batch size 变化，不是损失函数"
  evidence: experiments/results/ablation-contrastive.csv
  reopen_if: "出现新的负样本采样策略"
```

**判定表**

| 条件 | 结果 |
| --- | --- |
| `idea` 为空 / 非字符串 | `add_*` 拒绝：`ValueError` → 2 |
| `date` 不匹配 `YYYY-MM-DD` | `add_*` 拒绝（不做"猜日期"） |
| `status` 不在枚举 | `add_idea` 拒绝 |
| `dead-end` 缺 `reason`/`evidence`/`reopen_if` | `add_dead_end` 拒绝；`reopen_if` 是必填而非可选 |
| 追加时 id | 同文件内 `max(数字后缀)+1`，不跨文件复用 |
| 已存在文件 | 追加而非覆盖；首个条目写入时补 `#` 标题注释行 |
| YAML 语法错误 | `ValueError` → 2（无法解析就审计不了，如实报） |

- [ ] **Step 1: 写失败测试**（约 13 条）

必须覆盖：空目录首次 `add_idea` 自动建文件且带注释标题行；id 从 1 递增、跳过已用号后取 max+1；`add_dead_end` 六个字段齐全且顺序固定；缺 `reopen_if` 被拒（**判别力核心**：把 `reopen_if` 当作可选即失败）；非法日期被拒；非法 `status` 被拒；`load_memory` 缺失文件得 `[]`、YAML 损坏抛 `ValueError`、顶层是 mapping 而非 list 抛 `ValueError`；追加不破坏已有条目（两次 add 后两条都在）；`save_memory` 后无 `.tmp` 残留；`list_memory` 的 `status` 过滤与 `kind` 选择。

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现**

- [ ] **Step 4: 运行测试确认通过**

判别力检查：删除 `add_dead_end` 的 `reopen_if` 必填校验 → 对应用例必须失败；把 id 生成改成 `len(entries)+1` → "跳过已用号"用例必须失败。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/memory.py tools/tests/test_memory.py
git commit -m "feat: record ideas and dead ends with required reopen conditions"
```

---

### Task 4: `memory check` 与 `memory search`（读取时重校验 + 反重复提示）

**Files:**
- Modify: `tools/ccfa/memory.py`
- Modify: `tools/tests/test_memory.py`

**Interfaces:**
- Produces:
  - `check_memory(paper_root: Path) -> list[Problem]`（只读；逐条报全）
  - `search_memory(paper_root, query: str) -> dict`（确定性子串匹配，`casefold`；返回 `{"query","ideas","dead_ends","skipped_invalid","skipped"}`；dead-end 的每条命中都带 `reopen_if`）
  - `main` 新增 `check` / `search` 子命令

**Task 3 评审结转（5 条测试覆盖缺口，均只加用例、不改生产行为）**

1. 原子写用例加一条断言：写出的字节不以 UTF-8 BOM（`\xef\xbb\xbf`）开头。
2. `load_memory` 的读盘失败折叠：用一个**目录**冒充 `ideas.md`（或 `chmod` 不可读）触发 `OSError` → `ValueError`；不可解码字节（`b"\xff\xfe"`）触发 `UnicodeDecodeError` → `ValueError`。
3. `list_memory` 非法 `kind` 与非法 `status` 各自 `ValueError`。
4. `add-dead-end` 的 CLI happy path：退 0、stdout JSON 条目字段齐全、`reopen_if` 原样出现。
5. 日历非法日期（如 `2026-13-01`、`2026-02-30`）被拒（`date.fromisoformat` 分支）。

**判定表**

| 条件 | 结果 |
| --- | --- |
| 条目缺 `id`/`date`/`idea` | problem `memory-missing-field` |
| `date` 不匹配 `YYYY-MM-DD` | problem `memory-invalid-date` |
| id 不匹配 `^(I|DE)[1-9][0-9]*$` | problem `memory-invalid-id` |
| 同文件 id 重复 | problem `memory-duplicate-id` |
| `ideas` 的 `status` 非法 | problem `memory-invalid-status` |
| `dead-ends` 缺 `reopen_if` 或为空 | problem `deadend-missing-reopen-if` |
| `dead-ends` 缺 `reason`/`evidence` 或为空 | problem `memory-missing-field`（读取时与写入时同严，E38） |
| 条目不是映射（YAML 列表里夹了字符串） | problem `memory-entry-not-mapping`，**继续审计其余条目** |
| 两种问题同时存在 | 两条都报（不早退） |

**修复轮规格（E38/E39，Task 4 评审后追加）**

- E38：`check_memory` 对 dead-end 的 `reason` 与 `evidence` 做与写入时同强度的读取时校验（缺失/空串/非字符串 → `memory-missing-field` 并指明字段名）。
- E39：`search_memory` 在保留 `skipped_invalid` 计数的同时，新增 `skipped` 列表（每项 `{"file", "id", "codes"}`），让"命中但被跳过"不再只能靠另跑 check 才看得见。计数键保持兼容。
- 测试补齐：`check` 有问题→1、坏 YAML→2、`search` 无命中→0、空/非字符串 query → `ValueError`（CLI 退 2）、重复 id 条目在 search 里进 `skipped`（带 `memory-duplicate-id`）。
- **E40（Task 5 落地后追加）**：`skipped[].file` 的值改为真实相对路径（`memory/ideas.md` / `memory/dead-ends.md`），键名与实际一致；`check_memory` 的每条 Problem 消息点名条目 locator——有合法 id 时前缀 `条目 <id>`，否则 `第 <n> 条`（YAML 无行号，位置索引是诚实等价物）。Task 5 的 e2e 断言同步改为路径 + id。

- [ ] **Step 1: 写失败测试**（约 11 条）

必须覆盖：手改文件塞入 `status: whatever` 后 `check_memory` 报出（**读取时重校验**）；手改删掉 `reopen_if` 后报 `deadend-missing-reopen-if`；id 重复两条都报；坏条目 + 好条目共存时好条目的问题仍被报出（不早退）；`check` 只读（前后字节比对）；`search` 命中 idea 文本；`search` 命中 dead-end 的 `reason` 且结果里 `reopen_if` 原样出现；`search` 大小写不敏感；`search` 对坏条目计数 `skipped_invalid` 而不是崩溃或静默；无命中退 0 空结果。

判别力检查：删掉 `check_memory` 的枚举重校验 → 手改用例必须失败；把 `search` 改为遇非映射条目即抛异常 → `skipped_invalid` 用例必须失败。

- [ ] **Step 2–4: 跑失败 → 实现 → 跑通过**

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/memory.py tools/tests/test_memory.py
git commit -m "feat: audit and search research memory including reopen conditions"
```

---

### Task 5: 端到端回归（真实 SQLite + 真实文件树）

**Files:**
- Create: `tools/tests/test_knowledge_layer_e2e.py`

**场景（一个临时论文库，真实 `refs.bib` 文本、真实 notes、真实 memory 文件）**

1. 写 `library/refs.bib`（≥3 条，其中 1 条标题含中文）+ `notes/<key>.md`；`library index` 退 0；`library search` 中文 3 字命中、2 字 LIKE 命中、无命中退 0；`library check` 退 0。
2. 改 `refs.bib` 加一条 → `library search` 退 2 且消息含"过期"；重跑 `index` 后新条目可被检索；`check` 恢复 0。
3. 删掉一个 note 文件、再制造一个游离 note → `check` 退 1 并同时报出两向问题。
4. 写 `memory/ideas.md` 与 `dead-ends.md`（含一条真实死路）→ `memory check` 退 0；`memory search` 命中死路且 `reopen_if` 出现在输出里。
5. 把死路的 `reopen_if` 删掉 → `memory check` 退 1 且消息点名该 id；`search` 仍可用且如实报 `skipped_invalid`，`skipped[0]["file"]` 是真实相对路径 `memory/dead-ends.md`。

预计 +6 条。跑全量后提交：

```powershell
git add tools/tests/test_knowledge_layer_e2e.py
git commit -m "test: add knowledge layer end-to-end regression"
```

---

## 完成定义（DoD）

- 全量测试通过（447 基线 + 本层新增 ≥ 50）。
- 三条判别力检查在实现 PR 里都有**实测失败记录**（不是纸面声明）。
- `library check` 与 `memory check` 只读；`library index` 的覆盖重建在 `--help` 中写明"派生数据、可重建"。
- 台账更新：E33–E37 的裁定理由与代价、每个任务的 review 结论、结项 commit 区间。
- 诚实边界写进两个工具的 `--help`：索引不含 PDF 全文；记忆检索是子串匹配而非语义检索；claim 状态回写未实现（E37）。
