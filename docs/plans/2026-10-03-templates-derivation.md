# templates-derivation 实施计划（模板库与派生流程收口）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把设计 §10 与 §12 的验收落地：一条命令派生完整论文目录；会议/期刊模式门清单正确；状态文件可读可校验；共享文献库全文检索可用；工具在派生项目里真正接线。这是"一站式"的收口阶段。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v6：§4、§6、§8、§10、§12）
**前置证据（模板复用评估，已完成）**：`<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-bensz-reuse-evaluation.md` —— **Verdict 低—中、reference-only、零代码 vendor**；只借鉴 profile 键值+覆盖、薄入口、单一正文源、缓存隔离；不复用 bensz-nsfc / bensz-fonts（字体再分发未验证）。

## 现状盘点（本计划依据）

- venue 模板库：`$CODEX_HOME/skills/ccf-latex-templates`，**139 个 venue**（NeurIPS/ICML/ACL/AAAI/CVPR…），已实测存在；README 自述为"官方/社区模板下载"。
- **已知缺口**：`tools/newpaper/create.py` 只复制 venue 目录的**顶层文件**（`if entry.is_file()`），而 ACM / CVPR / ICCV / VLDB 四个 venue 含子目录——派生结果对这些 venue 不完整。
- 已有：`ccfa.yaml.template`（含 `deadline: null`）、`tools/newpaper/{create,checklists,venues}.py`、`checklists/{conference,journal}.md`（由 stages.py 生成）、`library/`、`automation/`、11 个确定性工具的 CLI。
- 记忆种子文件是纯注释 YAML（`# 选题记忆`），`load_memory` 已实测返回 `[]`，`check_memory` 退 0。

## Global Constraints

- 仓库根：`<repo-root>`；基线以任务派发时 HEAD 为准（写计划时 **650 tests OK**，automation 终审收尾中）。
- 退出码 0/1/2、stdout JSON / stderr 人读、原子写/不覆盖、UTF-8 无 BOM、ASCII 标识符——沿用九条跨工具规则。
- 一切写盘：失败必须清理（scaffold 半成品不得留在 `papers/`）。
- 真实外部依赖的验证要真跑：LaTeX 用本机 MiKTeX（`tools/ccfa/latex_check.py --compile` 已有实测先例）；包装器用真实 `powershell -NoProfile -File` 调用。
- 中文只在面向用户消息与文档里；测试禁止依赖网络。

---

### Task 1: `create.py` 递归复制 venue 模板（修补 ACM/CVPR/ICCV/VLDB 不完整）

**Files:** Modify `tools/newpaper/create.py`、`tools/tests/test_create.py`

**要求**
- 复制 venue 目录时**保留相对目录结构**：把文件与子目录下的文件都复制到 `manuscript/` 对应相对路径（`shutil.copytree(..., dirs_exist_ok=True)` 或逐文件 `copy2` + `mkdir`）。
- `find_main_tex` 仍能找到主文件（嵌套也支持）；`state["artifacts"]["manuscript"]` 记录相对路径。
- 失败清理逻辑保持：任何异常都不得留下半成品于 `papers/<slug>`（现有 `created_target` 逻辑不变）。
- 补用例（约 6 条）：嵌套 `styles/x.sty`、`figs/f.pdf` 被复制且结构一致；扁平 venue 行为不变；主文件在子目录时可被发现；复制失败（把目标目录设为只读或用 mock 让 `copy2` 抛 `OSError`）→ 目标目录被清理、异常类型符合既有契约；重复创建仍拒绝覆盖。
- 判别力**实测**：把复制改回"只顶层文件"→ 嵌套用例必须失败。贴失败原文。
- commit：`fix: copy venue template trees recursively`

### Task 2: 派生 + 真编译冒烟（NeurIPS 与 ACL）

**Files:** Create `tools/tests/test_derivation_e2e.py`（其余不改）

**要求（真实文件树 + 真实 MiKTeX，不 mock）**
- NeurIPS：`create_project(papers_root=tmp, slug="neurips-smoke", venue="NeurIPS", year=2027, mode="conference", deadline=None, title=...)` → 断言目录骨架齐全（`ccfa.yaml`、`manuscript/*.sty+*.tex`、`data/provenance.json`、`experiments/log/`、`memory/{ideas,dead-ends}.md`、`reviews/`、`submission/repro/`）。
- 在该项目上真跑：`validate.py` 退 0；`milestones stage` 退 0 且 `current=idea`；`milestones due` 退 0（`deadline=null` → sequential、`due=[]`）；`memory check` 退 0；`latex_check --compile` 在 `manuscript/` 上退 0 且产出 PDF（真实引擎；若本机引擎缺失，测试 skip 并如实标注——但本仓库既有 MiKTeX 实测先例，预期可跑）。
- ACL：同法派生 `acl-smoke` 并真编译通过（证明两个不同 venue 的模板都能编译）。
- **这一条的证据必须写进任务报告**：引擎与版本、命令、PDF 路径与字节数。
- commit：`test: prove derived venue projects compile end to end`

### Task 3: `scripts/*.ps1` 包装器（11 工具 + newpaper）

**Files:** Create `scripts/*.ps1`（design §10 的清单：`new-paper.ps1`、`citation-guard.ps1`、`trace-claims.ps1`、`provenance.ps1`、`run-log.ps1`、`repro-package.ps1`、`latex-check.ps1`、`final-check.ps1`、`friction-log.ps1`、`research-version.ps1`、`library.ps1`、`memory.ps1`，另加 `queue.ps1`/`watch.ps1`/`milestones.ps1`/`cross-review.ps1` 视 §10 补全）；Create `tools/tests/test_scripts.py`

**要求**
- 每个包装器：`$ErrorActionPreference='Stop'`；解析 `$PSScriptRoot/..` 为仓库根；`$env:PYTHONPATH="$root/tools"`；调用 `"$root/tools/.venv/Scripts/python.exe" -m ccfa.<module> @args`；`exit $LASTEXITCODE`。不得吞掉或改写被包装命令的 stdout/stderr。
- **模块清单一处定义**：`tools/ccfa/` 下的 CLI 模块清单（可放 `tools/ccfa/__init__` 或测试内常量），测试断言每个有 `main()` 的模块都有对应 `.ps1`，防止漂移。
- 真实执行验证：对每个包装器跑 `powershell -NoProfile -File <wrapper> --help`，断言退出码 0 且输出含 `usage`（或该工具 help 的实际关键字）；至少一个包装器跑一次真实子命令（如 `research-version.ps1 list --repo <tmp repo>`）。
- commit：`feat: wrap every tool with a powershell entry script`

### Task 4: README/文档同步 + checklist 再生核对

**Files:** Modify `README.md`（仓库根）；Modify `tools/tests/test_create.py` 或 Create `tools/tests/test_docs_consistency.py`

**要求**
- 根 README 增加：11+ 工具一览（名称/一句话/入口）、阶段→命令速查（`ccfa.yaml` stage 与 `milestones`、`library`、`memory`、`run-log`、`latex-check`、`final-check` 的对应关系）、`automation/` 指针、venue 模板位置（`$CODEX_HOME/skills/ccf-latex-templates`）与"模板为官方/社区下载，使用前自查许可"的提示。
- 文档一致性测试：README 必须提及每个 CLI 模块名；README 点名的仓库内路径必须存在（九条规则第 9 条）。
- **checklist 再生核对**：`checklists.py` 渲染结果与仓库内 `checklists/{conference,journal}.md` 逐字节一致；两种模式的 stage 数量与 gate id 与 `stages.py` 一致（模式切换验收）。
- commit：`docs: document the one-stop workflow surface`

### Task 5: 一站式集成回归（派生项目 × 全工具链）

**Files:** Create `tools/tests/test_workflow_e2e.py`

**要求（真实文件树；网络与 codex 调用注入）**
- 派生一个 conference 项目与一个 journal 项目：断言 `ccfa.yaml` 的 mode/stage/gate/deadline 正确；`checklists` 两种模式覆盖不同尾部阶段（会议有 `rebuttal/camera-ready`，期刊有 `major-revision/response-letter`）。
- 在派生项目里串起：`memory add-idea` → `memory check` → `run-log run`（真实短命令 `{python} -c ...`）→ `provenance add`（用项目内生成的小 CSV）→ `library index/search`（用项目 `manuscript/references.bib` + 一个 note）。
- 断言各工具在**派生项目路径**下都能工作（不依赖仓库根 cwd），且互不覆盖对方的文件。
- 约 8–10 条；判别力：把 `create.py` 的 venue 递归复制临时改回顶层复制 → 派生项目缺嵌套文件（若 Task 2 已覆盖可省略此条，改为对 `library` 的 2 字回退做一次真实命中断言）。
- commit：`test: add one-stop workflow integration regression`

---

## 完成定义（DoD）

- 全量测试通过（650 基线 + ≥ 35）；四条判别力实测记录。
- **真实证据**：至少两个 venue 的派生项目由真实 MiKTeX 编译出 PDF；每个包装器真实执行 `--help` 退 0。
- 设计 §12 验收逐条挂到测试或证据上（派生命令、模式切换、状态文件、全文检索、自动化默认安静、各工具专项验收）。
- 台账更新：本阶段裁定与结项 commit 区间；挂账清单（bensz 零 vendor 的决定、模板许可自查提示、SUB/BIB 等未覆盖 venue）。
