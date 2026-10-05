# Workflow Change Log

Generated from `docs/workflow-change-log.jsonl`. Append-only; do not
rewrite historical entries.

## WC-20261006T000000Z-mandatory-log - Add an append-only, fail-closed workflow change log contract.

- timestamp: `2026-10-06T00:00:00Z`
- status: `complete`
- author: `codex`
- reason: 用户要求规定每次工作流修改都必须记录日志，不能用聊天记录代替可审计变更日志。
- files:
  - `.github/pull_request_template.md`
  - `.github/workflows/tests.yml`
  - `AGENTS.md`
  - `README.md`
  - `docs/workflow-change-log.jsonl`
  - `docs/workflow-change-log.md`
  - `docs/workflow-guide.md`
  - `scripts/change-log.ps1`
  - `tools/ccfa/change_log.py`
  - `tools/tests/test_change_log.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_github_workflows.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_change_log`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
- notes: The log itself and its generated Markdown are excluded from coverage checks, but listed here for traceability.

## WC-20261005T163310Z-a005adfa58 - Design the workbench UI as a three-pane operations surface on a Modex-MH-Agent style theme.

- timestamp: `2026-10-05T16:33:10Z`
- status: `complete`
- author: `codex`
- reason: 用户要求参考 Modex-MH-Agent 设计工作台 UI：原界面把项目列表、阶段标签和结果表放在同一视觉层级，坏项目与好项目难以区分，YAML 报错还会溢出到标题区。
- files:
  - `app/ccfa_gui/settings_dialog.py`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
- tests:
  - `ruff check app`
  - `unittest discover -s app/tests -t app (205 tests)`
- notes: papers/ 未改动；未触碰工作区中其他未提交文件。

## WC-20261005T163719Z-cc4d566f97 - Fix app tests that broke on GitHub runners and make the workflow probe verify its directory

- timestamp: `2026-10-05T16:37:19Z`
- status: `complete`
- author: `codex`
- reason: App E2E tests scaffolded projects from the host ccf-latex-templates library, which does not exist on a clean runner, and WorkflowClient.probe() reported a bogus directory as reachable because it never checked tools/ccfa.
- files:
  - `app/ccfa_core/workflow.py`
  - `app/tests/__init__.py`
- tests:
  - `app.tests.test_chat_e2e`
  - `app.tests.test_tools_bridge`
  - `app.tests.test_workbench_e2e`
  - `app.tests.test_workflow`

## WC-20261005T164056Z-234290264d - Normalize temp paths before comparing in the chat E2E test

- timestamp: `2026-10-05T16:40:56Z`
- status: `complete`
- author: `codex`
- reason: The GitHub Windows runner exposes 8.3 short names (RUNNER~1), so the assertion compared a short path against the canonical long path and failed only on CI.
- files:
  - `app/tests/test_chat_e2e.py`
- tests:
  - `app.tests.test_chat_e2e`

## WC-20261005T164251Z-c08422da28 - Adopt Modex-MH-Agent's checkpoint shape: expand each pending human ledger into a question with an explicit answer location.

- timestamp: `2026-10-05T16:42:51Z`
- status: `complete`
- author: `codex`
- reason: 参考 Modex-MH-Agent 工作流设计：他们把人工决定建模成 checkpoint（类型/展示数据/回复）。我们的 readiness 只输出 pending key 列表，人看不出到底要被问什么、答案写哪里。
- files:
  - `docs/reference-modex-mh-agent-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `ruff check tools/ccfa/readiness.py tools/tests/test_readiness.py`
  - `tools.tests.test_dashboard + test_docs_consistency (53 tests)`
  - `tools.tests.test_readiness (33 tests)`
- notes: worktree 缺 tools/.venv，test_scripts 在本目录跑不动；已在主仓库验证 tests.test_scripts 116 项通过。

## WC-20261005T164518Z-207ae33734 - Add portable CLI entry, deterministic ARA extraction, and worktree drift audit.

- timestamp: `2026-10-05T16:45:18Z`
- status: `complete`
- author: `codex`
- reason: Address the portability, automatic semantic-extraction, and uncommitted-worktree drift gaps identified in the live comparison.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-guide.md`
  - `pyproject.toml`
  - `scripts/ara-extract.ps1`
  - `scripts/worktree-audit.ps1`
  - `tools/ccfa/ara_extract.py`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/worktree_audit.py`
  - `tools/tests/test_ara_extract.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_packaging.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_worktree_audit.py`
- tests:
  - `tools.tests.test_ara_extract`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_packaging`
  - `tools.tests.test_scripts`
  - `tools.tests.test_worktree_audit`

## WC-20261005T164728Z-0a75308587 - Publish fake-pass detection notes and the P0/P1/P2 deficiency checklist.

- timestamp: `2026-10-05T16:47:28Z`
- status: `complete`
- author: `codex`
- reason: Keep the evidence-first moat visible and separate code-resolved items from human or external blockers.
- files:
  - `docs/fake-pass-detection.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
- tests:
  - `tools.tests.test_change_log`

## WC-20261005T165038Z-c0f50383ce - Make host-only tool end-to-end tests skip on a clean CI runner

- timestamp: `2026-10-05T16:50:38Z`
- status: `complete`
- author: `codex`
- reason: The venue derivation and compile suites run against the host ccf-latex-templates library and MiKTeX, neither of which exists on a GitHub runner or the public mirror. Skipping with an explicit reason keeps the full-suite CI job honest instead of red. Also resolve paths before comparing in the cross-review argv test so 8.3 short names do not fail it.
- files:
  - `tools/tests/__init__.py`
  - `tools/tests/test_compile.py`
  - `tools/tests/test_cross_review.py`
  - `tools/tests/test_derivation_e2e.py`
  - `tools/tests/test_e2e.py`
  - `tools/tests/test_evidence_integrity_e2e.py`
  - `tools/tests/test_productization_e2e.py`
  - `tools/tests/test_venues.py`
  - `tools/tests/test_workflow_e2e.py`
- tests:
  - `tools.tests.test_compile`
  - `tools.tests.test_cross_review`
  - `tools.tests.test_derivation_e2e`
  - `tools.tests.test_e2e`
  - `tools.tests.test_evidence_integrity_e2e`
  - `tools.tests.test_productization_e2e`
  - `tools.tests.test_venues`
  - `tools.tests.test_workflow_e2e`

## WC-20261005T165038Z-048c83d06d - Let the public mirror drop the private workflow change-log gate

- timestamp: `2026-10-05T16:50:38Z`
- status: `complete`
- author: `codex`
- reason: The mirror diff is not the private commit diff, so the change-log gate cannot be satisfied there; publish-public.ps1 now removes named workflow steps on the mirror via config.
- files:
  - `scripts/publish-public.ps1`
- tests:
  - `tools.tests.test_scripts`

## WC-20261005T165530Z-89b92885fa - Add budgeted pilot execution and periodic upstream reference audit

- timestamp: `2026-10-05T16:55:30Z`
- status: `complete`
- author: `codex`
- reason: Close the remaining mechanically addressable comparison gaps: the experiment loop now hands a declared pilot to the budgeted executor, and pinned source-audit references are checked monthly instead of relying on a prose promise.
- files:
  - `.github/workflows/reference-audit.yml`
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/reference-drift-2026-10-06.md`
  - `docs/reference-registry.yaml`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/reference-audit.ps1`
  - `tools/ccfa/experiment_loop.py`
  - `tools/ccfa/reference_audit.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_experiment_loop.py`
  - `tools/tests/test_github_workflows.py`
  - `tools/tests/test_reference_audit.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_experiment_loop`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_reference_audit`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261005T165648Z-8cf3d9d75a - Skip the private change-log gate assertion on the public mirror

- timestamp: `2026-10-05T16:56:48Z`
- status: `complete`
- author: `codex`
- reason: The mirror drops the workflow change-log step because its diff is not the private commit diff, so the fail-closed assertion is private-only. A .public-mirror marker makes the test skip there while it still runs in the private repository.
- files:
  - `automation/public-docs/PUBLIC-MIRROR.md`
  - `tools/tests/test_github_workflows.py`
- tests:
  - `tools.tests.test_github_workflows`

## WC-20261005T165734Z-12b19b01d3 - Split audit strictness from depth: add an optional workflow.assurance axis (draft | submission) to ccfa.yaml.

- timestamp: `2026-10-05T16:57:34Z`
- status: `complete`
- author: `codex`
- reason: 参考上游 ARIS 的 effort x assurance 设计：把深度和审计严格度混在一个 profile 里，会让高预算的论文在探测器未命中时静默跳过投稿审计。这也是我们踩过的 present=pass 同类事故。
- files:
  - `docs/reference-aris-2026-10-06.md`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `ruff check tools`
  - `tools.tests.test_dashboard + test_docs_consistency (61 tests)`
  - `tools.tests.test_readiness (41 tests)`
- notes: 默认行为不变：不写 assurance 时与之前完全一致；high-assurance 默认 submission。workflow-guide 段落待并发编辑落地后再补。

## WC-20261005T170010Z-cea660be07 - Normalize README workflow-row line endings

- timestamp: `2026-10-05T17:00:10Z`
- status: `complete`
- author: `codex`
- reason: Remove CRLF trailing whitespace flagged by git diff --check on the newly added workflow rows.
- files:
  - `README.md`
- tests:
  - `git diff --check`

## WC-20261005T170326Z-ae6a6b566f - Add a verifiable .skillpack format (sha256 manifest, deterministic zip, optional AES-256-GCM) after reviewing Modex-MH-Agent's encrypted skill pack.

- timestamp: `2026-10-05T17:03:26Z`
- status: `complete`
- author: `codex`
- reason: 用户要求参考他的加密技能包。实测其 283 个 .enc 用 AES-256-GCM + zlib 字典伪装、密钥服务端下发并绑定机器指纹：能挡住读提示词，但目录名/模板/脚本名全明文，骨架照样可见，且离线不可用、换硬件即失效、收到包的一方无法校验。抄可校验那一半，丢掉伪装与绑定。
- files:
  - `README.md`
  - `docs/reference-modex-mh-agent-2026-10-06.md`
  - `docs/skillpack-format.md`
  - `scripts/skillpack.ps1`
  - `tools/ccfa/skillpack.py`
  - `tools/requirements.txt`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_skillpack.py`
- tests:
  - `ruff check tools`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_skillpack (12 tests, including the encrypted round-trip)`
- notes: 实测打包 ccf-common（16 文件）并在明文与加密两种模式下 verify 通过；加密包无口令返回 skillpack-locked。

## WC-20261005T170408Z-0990e86d3a - Install the public venue template library and MiKTeX in CI

- timestamp: `2026-10-05T17:04:08Z`
- status: `complete`
- author: `codex`
- reason: The derivation and compile end-to-end suites were skipping on runners because the host ccf-latex-templates library and pdflatex were absent. Both are publicly installable (mikubaka88/CCFA-Skills, MiKTeX), so the tools job now installs them with continue-on-error; a failed install degrades to the existing explicit skips instead of a red job.
- files:
  - `.github/workflows/tests.yml`
- tests:
  - `tools.tests.test_github_workflows`

## WC-20261005T170719Z-db032c0d3b - Add pinned container reproduction receipts

- timestamp: `2026-10-05T17:07:19Z`
- status: `complete`
- author: `codex`
- reason: Close the second-environment reproduction gap with a deterministic, network-disabled Docker runner and make repro-env validate the receipt instead of accepting prose.
- files:
  - `.github/workflows/repro-smoke.yml`
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/repro-container.ps1`
  - `tools/ccfa/repro_container.py`
  - `tools/ccfa/repro_env.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_repro_container.py`
  - `tools/tests/test_repro_env.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_repro_container`
  - `tools.tests.test_repro_env`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261005T170947Z-5be2220993 - Expose gate-driven human checkpoints in standard readiness

- timestamp: `2026-10-05T17:09:47Z`
- status: `complete`
- author: `codex`
- reason: Standard-profile readiness reported human review as not-required even while proof/citation/figure gates were blocking; it now derives answerable human checkpoints from the actual gate failures without converting them to pass.
- files:
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_readiness`

## WC-20261005T171205Z-d13b046223 - Ignore generated readiness reports when checking git dirtiness

- timestamp: `2026-10-05T17:12:05Z`
- status: `complete`
- author: `codex`
- reason: A readiness run writes its own JSON/Markdown/error files under reviews/, which made the same report claim the paper tree was dirty. The generated report files are now excluded from the dirtiness calculation.
- files:
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_readiness`

## WC-20261005T171238Z-c91e5f2823 - Design the workbench app: five Figma-importable SVG screens generated from the shipped theme tokens, plus a UI spec.

- timestamp: `2026-10-05T17:12:38Z`
- status: `complete`
- author: `codex`
- reason: 用户要求用 Figma 设计 app。本机 Figma 插件已启用但没有配置 Figma MCP server，无法直接读写 Figma 文件；改为产出可导入 Figma 的 SVG 屏幕与设计说明，并把生成器接在同一份 theme.py 令牌上，保证设计稿不会与实现漂移。
- files:
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `docs/design/exports/01-workbench-empty.svg`
  - `docs/design/exports/02-workbench-project.svg`
  - `docs/design/exports/03-workbench-blocked.svg`
  - `docs/design/exports/04-human-checkpoints.svg`
  - `docs/design/exports/05-settings-dialog.svg`
  - `docs/design/generate_mockups.py`
- tests:
  - `tools.tests.test_docs_consistency`
- notes: 04-human-checkpoints 是新提的界面：数据来自 readiness.human_review.checkpoints，尚未在 Qt 里实现。

## WC-20261005T171603Z-0bb348e1bc - Fail closed on an empty citation calibration gold set

- timestamp: `2026-10-05T17:16:03Z`
- status: `complete`
- author: `codex`
- reason: The calibration report treated zero gold rows as a threshold pass, which let missing live evidence masquerade as calibrated citation support.
- files:
  - `tools/ccfa/citation_calibration.py`
  - `tools/tests/test_citation_calibration.py`
- tests:
  - `tools.tests.test_citation_calibration`

## WC-20261005T171719Z-462141832f - Turn cross-review failures into an actionable checkpoint

- timestamp: `2026-10-05T17:17:19Z`
- status: `complete`
- author: `codex`
- reason: Readiness reported cross-review as a bare gate failure; it now names the required action: configure a verifiable gate-capable cross-family provider or complete an external human review with evidence.
- files:
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_readiness`

## WC-20261005T171750Z-7feb7aa905 - Wire the human-checkpoint queue into the workbench: readiness gains --checkpoints-only and the app gets a 待人工复核 button with a status banner.

- timestamp: `2026-10-05T17:17:50Z`
- status: `complete`
- author: `codex`
- reason: 设计稿 04-human-checkpoints 只停留在模拟图。工作台要能回答'现在有哪些事只有人能决定、答案写哪里'，但完整 readiness 会跑 20+ 个 gate，不适合点一下就等。
- files:
  - `app/README.md`
  - `app/ccfa_core/checks.py`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_checks.py`
  - `app/tests/test_gui_smoke.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `app unittest discover (207 tests)`
  - `ruff check app tools`
  - `tools.tests.test_readiness (47 tests)`
- notes: 实测：真实 app 点按钮走 ccfa.readiness --checkpoints-only，表格列出 4 条 checkpoint，横幅显示待人工复核。

## WC-20261005T171917Z-ce5fc363e9 - Reject duplicate citation calibration ids

- timestamp: `2026-10-05T17:19:17Z`
- status: `complete`
- author: `codex`
- reason: Duplicate JSONL ids silently overwrote earlier rows, allowing a calibration set to lose samples without any visible failure.
- files:
  - `tools/ccfa/citation_calibration.py`
  - `tools/tests/test_citation_calibration.py`
- tests:
  - `tools.tests.test_citation_calibration`

## WC-20261005T172224Z-b23ba49ddd - Render the human-checkpoint queue as cards with an 打开台账 action instead of table rows.

- timestamp: `2026-10-05T17:22:24Z`
- status: `complete`
- author: `codex`
- reason: 表格形态放不下问题原文与台账说明，也没有直接跳到要写的文件的入口；设计稿 04 本来就是卡片。
- files:
  - `app/README.md`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_gui_smoke.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
- tests:
  - `app unittest discover (208 tests)`
  - `ruff check app`
- notes: 打开台账做了路径约束：解析后的目标必须留在项目目录内，文件不存在时打开最近的已存在祖先目录。

## WC-20261005T173212Z-932a491227 - Align artifact dependency edges with advisory and verified semantics

- timestamp: `2026-10-05T17:32:12Z`
- status: `complete`
- author: `codex`
- reason: Adopt the useful part of open-science's provenance graph without overclaiming: static dependencies stay advisory, verified edges require existing evidence, dangling links fail, and cycles are rejected.
- files:
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `tools/ccfa/research_ledgers.py`
  - `tools/tests/test_research_ledgers.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_research_ledgers`

## WC-20261005T173552Z-2c2b7f6189 - Polish the workbench chrome: shared vector icon set, product mark, empty state, selected-row accent, transparent icon pixmaps.

- timestamp: `2026-10-05T17:35:52Z`
- status: `complete`
- author: `codex`
- reason: 用户要求设计好看的 UI。原来的 chrome 用 Qt 自带图标（蓝色文件夹/刷新箭头），和整套配色不搭；空列表时中栏是一张空表；图标 pixmap 用 QPixmap.fill() 默认填了白色，在主按钮上显示成白方块。
- files:
  - `app/README.md`
  - `app/ccfa_gui/chat_panel.py`
  - `app/ccfa_gui/icon_paths.py`
  - `app/ccfa_gui/icons.py`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_gui_smoke.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `docs/design/exports/01-workbench-empty.svg`
  - `docs/design/exports/02-workbench-project.svg`
  - `docs/design/exports/03-workbench-blocked.svg`
  - `docs/design/exports/04-human-checkpoints.svg`
  - `docs/design/exports/05-settings-dialog.svg`
  - `docs/design/generate_mockups.py`
- tests:
  - `app unittest discover (209 tests)`
  - `ruff check app`
- notes: 实测截图确认：工具栏标记+图标、侧栏选中主色条、状态栏圆点、空白状态占位。

## WC-20261005T173725Z-5f27688374 - Require the CI compile list and its modules to move in one commit

- timestamp: `2026-10-05T17:37:25Z`
- status: `complete`
- author: `codex`
- reason: A parallel commit listed tools/ccfa/repro_container.py in tests.yml py_compile before the file existed, which failed CI at Compile core modules. The engineering contract now states the rule and a guard test asserts every listed path exists.
- files:
  - `AGENTS.md`
  - `tools/tests/test_github_workflows.py`
- tests:
  - `tools.tests.test_github_workflows`

