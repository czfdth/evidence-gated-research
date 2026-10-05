# 大检查与清理报告

日期：2026-10-05

## 一、大检查结果

### 仓库状态

| 仓库 | 状态 |
| --- | --- |
| 主仓库 | 有未提交改动（见下） |
| 论文仓库 `example-paper` | 干净，与 `origin/master` 同步 |

主仓库未提交内容：

```text
M  README.md
M  tools/ccfa/doctor.py
M  tools/ccfa/experiment_loop.py
M  tools/tests/test_docs_consistency.py
M  tools/tests/test_experiment_loop.py
M  tools/tests/test_scripts.py
?? docs/disk-relocation-2026-10-05.md
?? docs/toolchain-workflow-fit-2026-10-05.md
?? docs/tooling-install-2026-10-05.md
?? scripts/archive.ps1, compute.ps1, install-toolchain.ps1
?? tools/ccfa/archive_client.py, compute.py, toolchain.py
?? tools/install/
?? tools/tests/test_archive_client.py, test_compute.py, test_fetch_toolchain.py
```

### 测试：3 项失败（需要修）

```text
Ran 1567 tests, FAILED (failures=3)
```

全部集中在 `tools/tests/test_verifiers.py`：

| 测试 | 断言 | 失败原因 |
| --- | --- | --- |
| `test_inventory_covers_every_registered_engine` | `all(not status.available)` | 机器上实际有引擎可用 |
| `test_status_lines_mark_wired_engines` | 每一行都含 `MISSING` | 有引擎显示 `installed` |
| `test_main_strict_exits_one` | `problem_count == len(FORMAL_ENGINES)`（9） | 实际为 8，因为 1 个引擎真的装了 |

**根因**：测试假设“宿主机没装任何形式化引擎”，但当前机器 **9/9 全部可用**：

```text
z3, cvc5, lean, coq, isabelle, agda, why3, sage, julia
```

这与之前 `run-log-dirty-tree` 的问题同类：测试依赖宿主机环境，而不是注入受控探针。修法是让这些测试传入显式的空 inventory / 假 probe，而不是断言真实环境。

### 形式化引擎：9/9 可用

```text
installed  z3        SMT                   module z3 5.1.0
installed  cvc5      SMT                   module cvc5 1.3.1
installed  lean      proof-assistant       lean 4.34.1
installed  coq       proof-assistant       Rocq 9.0 (coqc)
installed  isabelle  proof-assistant       Isabelle2025-2
installed  agda      proof-assistant       Agda 2.6.3 (WSL)
installed  why3      verification-platform Why3 1.6.0 (WSL)
installed  sage      CAS                   10.9 (WSL)
installed  julia     language              Julia 1.13.1
```

### doctor

```text
0 problems, 2 advisories
- docker daemon 不可达
- zotero 不可达
```

### readiness

```text
ready = false
blocking:
  argument-audit gate failed: proof-review-not-verified ×5
  cross-review  gate failed: review-provider-config-drift, review-blocking
```

### 上一轮的假 pass 已完全修复

cross-review 现在把模型的 `pass` 覆盖为 `blocking`，并列出：

```text
review-advisory-only: qwen3:30b
review-contradiction: proof-review-not-verified ×8
review-contradiction: citation-support-missing ×6
review-contradiction: figure-support-missing ×1
review-unevidenced-pass: no checks
```

正是上一轮建议的方向：模型断言必须与确定性证据交叉校验。

## 二、清理结果

### 已确认：跟踪文件是干净的

- 无 `.DS_Store` / `Thumbs.db` / `desktop.ini`
- 无 `.tmp` / `.bak` / `.orig` / `.rej` / `.old`
- 无散落在根目录的 `*-check.json` / `*.err.txt` / `readiness-*.json`
- `docs/` 共 49 个文件，全部与科研工作流相关

### 可清理的缓存与临时目录（37 个，约 9 MB）

```text
.ruff_cache/                       ruff 缓存
.superpowers/                      superpowers 插件的 SDD 会话草稿（4.4 MB，含 2026-10-03 review diff）
__pycache__/ × 33（排除 .venv）     Python 字节码缓存
  - app/ccfa_core, app/ccfa_gui, app/tests
  - tools/ccfa, tools/build, tools/install, tools/newpaper, tools/tests
  - papers/example-paper/ccfa-workfiles/literature
  - ccfa-workfiles/.../gma-main（多处）与 .pytest_cache
```

以上全部可再生（缓存、字节码、插件草稿），删除无资料损失。

### 需要你决定的大项：根目录 `ccfa-workfiles/`

```text
总量      685.78 MB（960 个文件）
├─ deep-research/          157.90 MB
├─ source/neo4j/           518.75 MB   ← Neo4j 运行时数据库
├─ source/gma-main/          6.37 MB   ← 第三方仓库克隆
├─ cache/                    2.60 MB
└─ build/ + idea 文档        少量
```

内容是一个**另外的论文项目**：`gma-acl-20261005`（ACL 2027，agent memory / GMA 方向），包含完整的 idea 文档、文献扫描、deep-research 输出与一个已建好的 Neo4j 图数据库。

性质判断：

- 它不是科研工作流本身的代码或文档（整目录已 gitignore）；
- 但它是**真实研究内容**，且**目前只有这一份，没有副本**；
- Neo4j 数据库 518 MB 是实验运行时状态，重跑需重新 ingest，代价高。

因此**没有删除**。建议二选一：

1. 迁移：移动到 `papers/gma-acl-2027/`（成为独立论文仓库）或仓库外单独目录；
2. 清理：若该方向已放弃，先归档 `idea/` 下的 Markdown，再删除 `source/neo4j/` 与第三方克隆。

### 占用概览

```text
整个工作区            1566.70 MB
其中 ccfa-workfiles    685.78 MB
去除后                880.92 MB
```

## 三、需要你执行的清理命令

由于环境策略拦截了递归删除，以下命令需要你在本地终端执行：

```powershell
cd <repo-root>

# 1. 项目自身缓存（排除虚拟环境）
Get-ChildItem -Recurse -Directory -Filter __pycache__ |
  Where-Object { $_.FullName -notmatch '\\\.venv\\' } |
  Remove-Item -Recurse -Force

# 2. ruff 缓存
Remove-Item .ruff_cache -Recurse -Force -ErrorAction SilentlyContinue

# 3. superpowers 会话草稿
Remove-Item .superpowers -Recurse -Force -ErrorAction SilentlyContinue
```

若确认放弃 GMA 方向（**不可恢复**，请先备份 idea 文档）：

```powershell
Remove-Item .\ccfa-workfiles -Recurse -Force
```

## 四、下一步优先级

1. 修 `test_verifiers.py` 的环境依赖，让全量测试回到 1567 全绿。
2. 提交 archive / compute / toolchain 三套进行中的模块。
3. 决定 GMA 项目去留（迁移或归档后删除）。
4. 继续人工验证：8 条证明、引用与图表语义支持、真人双编码。
