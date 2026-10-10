# Workflow Change Log

Generated from `docs/workflow-change-log.jsonl`. Append-only; do not
rewrite historical entries.

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

## WC-20261005T165038Z-048c83d06d - Let the public mirror drop the private workflow change-log gate

- timestamp: `2026-10-05T16:50:38Z`
- status: `complete`
- author: `codex`
- reason: The mirror diff is not the private commit diff, so the change-log gate cannot be satisfied there; publish-public.ps1 now removes named workflow steps on the mirror via config.
- files:
  - `scripts/publish-public.ps1`
- tests:
  - `tools.tests.test_scripts`

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

## WC-20261005T173802Z-5d4940b771 - Record the Figma design file in the workbench UI spec.

- timestamp: `2026-10-05T17:38:02Z`
- status: `complete`
- author: `codex`
- reason: 五屏已通过 Figma MCP 导入为可编辑矢量图层并按列排布；原文说'没有配置 Figma MCP'已经过期，会把读者带偏。
- files:
  - `docs/design/2026-10-06-workbench-ui-spec.md`
- tests:
  - `docs consistency (tools.tests.test_docs_consistency)`
- notes: Figma 文件 XpIadzobOUEEPimh31y0TC，导入后 get_screenshot 复核过。

## WC-20261005T174350Z-d5442bc931 - Add system-following dark mode and a width-based chat column collapse to the workbench.

- timestamp: `2026-10-05T17:43:50Z`
- status: `complete`
- author: `codex`
- reason: 深色模式与窄窗口折叠是 UI 设计清单里剩下的两项：界面只有浅色一套，窗口变窄时对话栏死占 420px，把项目详情挤没。
- files:
  - `app/README.md`
  - `app/ccfa_gui/appearance.py`
  - `app/ccfa_gui/icon_paths.py`
  - `app/ccfa_gui/icons.py`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_gui_smoke.py`
  - `app/tests/test_theme.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
- tests:
  - `app unittest discover (218 tests)`
  - `ruff check app`
- notes: 深色截图确认色板生效；900px 截图确认对话栏收起；三栏显式最小宽度是折叠能生效的前提。

## WC-20261005T174851Z-9430eff04f - Render chat messages as role bubbles (user/assistant/tool/error/stopped) and add the matching design screen.

- timestamp: `2026-10-05T17:48:51Z`
- status: `complete`
- author: `codex`
- reason: 对话面板之前是纯文本列表项，工具调用和错误只能靠前缀区分，也没出过设计稿。
- files:
  - `app/README.md`
  - `app/ccfa_gui/chat_panel.py`
  - `app/ccfa_gui/theme.py`
  - `app/tests/test_chat_panel.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `docs/design/exports/06-chat-bubbles.svg`
  - `docs/design/generate_mockups.py`
- tests:
  - `app unittest discover (220 tests)`
  - `ruff check app`
- notes: 列表项仍保留纯文本，item.text() 消费方不受影响；第一次 sizeHint 在样式生效前算出会截断一行气泡，已改为 adjustSize + 事件循环后再量一次。

## WC-20261005T175017Z-12d710bf90 - Extract candidate claims from PDFs and repository text

- timestamp: `2026-10-05T17:50:17Z`
- status: `complete`
- author: `codex`
- reason: Close the PDF/repo-to-claim gap without allowing model auto-acceptance: candidates carry source hashes, page/line locations and verbatim quotes, are written to claim-candidates.yaml, and are checked before human promotion.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/claim-extract.ps1`
  - `tools/ccfa/claim_extract.py`
  - `tools/ccfa/pdftext.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_claim_extract.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_pdftext.py`
  - `tools/tests/test_readiness.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_claim_extract`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_pdftext`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T175113Z-ef2e542c53 - Extract candidate claims from PDFs and repository text

- timestamp: `2026-10-05T17:51:13Z`
- status: `complete`
- author: `codex`
- reason: Close the PDF/repo-to-claim gap without allowing model auto-acceptance: candidates carry source hashes, page/line locations and verbatim quotes, are written to claim-candidates.yaml, and are checked before human promotion.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/claim-extract.ps1`
  - `tools/ccfa/claim_extract.py`
  - `tools/ccfa/pdftext.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_claim_extract.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_pdftext.py`
  - `tools/tests/test_readiness.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_claim_extract`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_pdftext`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T175202Z-3335c7e38c - Generate the design exports in both themes: the mockup generator now takes the palette from CCFA_MOCKUP_MODE and writes exports/dark.

- timestamp: `2026-10-05T17:52:02Z`
- status: `complete`
- author: `codex`
- reason: 设计说明里'只有浅色一套'是最后一块没对齐的地方；深色模式已经在 app 里跑起来了，设计稿不跟上就没法用来核对。
- files:
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `docs/design/exports/02-workbench-project.svg`
  - `docs/design/exports/03-workbench-blocked.svg`
  - `docs/design/exports/04-human-checkpoints.svg`
  - `docs/design/exports/06-chat-bubbles.svg`
  - `docs/design/exports/dark/01-workbench-empty.svg`
  - `docs/design/exports/dark/02-workbench-project.svg`
  - `docs/design/exports/dark/03-workbench-blocked.svg`
  - `docs/design/exports/dark/04-human-checkpoints.svg`
  - `docs/design/exports/dark/05-settings-dialog.svg`
  - `docs/design/exports/dark/06-chat-bubbles.svg`
  - `docs/design/generate_mockups.py`
- tests:
  - `generator byte-stability (both modes)`
- notes: 浅色四屏也变了：选中行改用主题里的 row_selected(#eef1ff)，与 app 对齐；同一份生成器对同一棵树是确定性的。

## WC-20261005T175759Z-ad850411eb - Add a budgeted inner-loop parameter optimizer

- timestamp: `2026-10-05T17:57:59Z`
- status: `complete`
- author: `codex`
- reason: Replace the single-pilot executor gap with grid/random trial search, objective extraction, best tracking, patience/budget stops, append-only trial logs and a keep/revert proposal; claims and code remain human-reviewed.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/experiment-optimize.ps1`
  - `tools/ccfa/experiment_optimizer.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_experiment_optimizer.py`
  - `tools/tests/test_readiness.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_experiment_optimizer`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T175824Z-6bb05263a8 - Add a budgeted inner-loop parameter optimizer

- timestamp: `2026-10-05T17:58:24Z`
- status: `complete`
- author: `codex`
- reason: Replace the single-pilot executor gap with grid/random trial search, objective extraction, best tracking, patience/budget stops, append-only trial logs and a keep/revert proposal; claims and code remain human-reviewed.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/experiment-optimize.ps1`
  - `tools/ccfa/experiment_optimizer.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_experiment_optimizer.py`
  - `tools/tests/test_readiness.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_experiment_optimizer`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T175903Z-6e9b621bb2 - Render chat bubble bodies as Markdown (lists, code fences in monospace, wrapping code lines).

- timestamp: `2026-10-05T17:59:03Z`
- status: `complete`
- author: `codex`
- reason: 气泡正文之前是纯文本，模型回复里的列表和代码块都成了带标记的散文；代码行还会被 420px 的栏宽裁掉。
- files:
  - `app/README.md`
  - `app/ccfa_gui/chat_panel.py`
  - `app/ccfa_gui/theme.py`
  - `app/tests/test_chat_panel.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `docs/design/exports/06-chat-bubbles.svg`
  - `docs/design/exports/dark/06-chat-bubbles.svg`
  - `docs/design/generate_mockups.py`
- tests:
  - `app unittest discover (221 tests)`
  - `ruff check app`
- notes: 气泡改用 QTextBrowser.setMarkdown；代码围栏默认不折行，已逐块关掉 nonBreakableLines，并按文档实际高度反算气泡高度。

## WC-20261005T180305Z-1535278c9d - Add motion to the workbench: 180ms conversation-column slide and 140ms detail-page fade, with an off switch.

- timestamp: `2026-10-05T18:03:05Z`
- status: `complete`
- author: `codex`
- reason: 设计清单里的最后一项：折叠是瞬间跳变，切页也是硬切，空间关系读不出来；同时需要有 reduced-motion 的关闭路径。
- files:
  - `app/README.md`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_gui_smoke.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
- tests:
  - `app unittest discover (222 tests)`
  - `ruff check app`
- notes: 动画只动最大宽度与不透明度，结束回调恢复常态；animations=False / CCFA_NO_ANIM=1 / 窗口未显示时全部即时生效。

## WC-20261005T180645Z-b2db15c4bc - Add sandboxed automatic code mutation and research plan generation

- timestamp: `2026-10-05T18:06:45Z`
- status: `complete`
- author: `codex`
- reason: Implement the remaining autoresearch gap safely: model-generated plans and file replacements are written as candidates, code mutations run only in a disposable sandbox with tests and diffs, and neither claims nor the source repo are auto-accepted or modified.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/autoresearch.ps1`
  - `tools/ccfa/autoresearch.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_autoresearch.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_readiness.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_autoresearch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T180709Z-90a6359694 - Add sandboxed automatic code mutation and research plan generation

- timestamp: `2026-10-05T18:07:09Z`
- status: `complete`
- author: `codex`
- reason: Implement the remaining autoresearch gap safely: model-generated plans and file replacements are written as candidates, code mutations run only in a disposable sandbox with tests and diffs, and neither claims nor the source repo are auto-accepted or modified.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/autoresearch.ps1`
  - `tools/ccfa/autoresearch.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_autoresearch.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_readiness.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_autoresearch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T180937Z-40463a8128 - Give code blocks a mode-aware background and add the narrow/collapsed design screen (07) in both themes.

- timestamp: `2026-10-05T18:09:37Z`
- status: `complete`
- author: `codex`
- reason: 两处尾巴：代码块只有等宽字体没有底色；设计稿没有折叠态，无法核对窄窗口那一屏。
- files:
  - `app/README.md`
  - `app/ccfa_gui/chat_panel.py`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_chat_panel.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `docs/design/exports/07-narrow-collapsed.svg`
  - `docs/design/exports/dark/07-narrow-collapsed.svg`
  - `docs/design/generate_mockups.py`
- tests:
  - `app unittest discover (223 tests)`
  - `ruff check app`
- notes: Qt 的 markdown 导入器忽略样式表里的块背景，改用 nonBreakableLines 标记识别代码块并直接设置 block 背景；深浅色采样确认 #eef0f3 / #2b2b34 生效。

## WC-20261005T181502Z-728c97291b - Add cross-session task replay and independently installable skills

- timestamp: `2026-10-05T18:15:02Z`
- status: `complete`
- author: `codex`
- reason: Close the remaining orchestration and packaging gaps: long tasks now replay a hash-chained event log from disk, and core capabilities are split into dependency-resolved skill packages that can be verified and installed independently.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/long-task.ps1`
  - `scripts/skill-registry.ps1`
  - `skills/ccfa-autoresearch/SKILL.md`
  - `skills/ccfa-autoresearch/skill.yaml`
  - `skills/ccfa-claims/SKILL.md`
  - `skills/ccfa-claims/skill.yaml`
  - `skills/ccfa-core/SKILL.md`
  - `skills/ccfa-core/skill.yaml`
  - `skills/ccfa-evidence/SKILL.md`
  - `skills/ccfa-evidence/skill.yaml`
  - `skills/ccfa-experiments/SKILL.md`
  - `skills/ccfa-experiments/skill.yaml`
  - `skills/registry.yaml`
  - `tools/ccfa/long_task.py`
  - `tools/ccfa/skill_registry.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_long_task.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_skill_registry.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_long_task`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T181536Z-0606c5a773 - Add cross-session task replay and independently installable skills

- timestamp: `2026-10-05T18:15:36Z`
- status: `complete`
- author: `codex`
- reason: Close the remaining orchestration and packaging gaps: long tasks now replay a hash-chained event log from disk, and core capabilities are split into dependency-resolved skill packages that can be verified and installed independently.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/long-task.ps1`
  - `scripts/skill-registry.ps1`
  - `skills/ccfa-autoresearch/SKILL.md`
  - `skills/ccfa-autoresearch/skill.yaml`
  - `skills/ccfa-claims/SKILL.md`
  - `skills/ccfa-claims/skill.yaml`
  - `skills/ccfa-core/SKILL.md`
  - `skills/ccfa-core/skill.yaml`
  - `skills/ccfa-evidence/SKILL.md`
  - `skills/ccfa-evidence/skill.yaml`
  - `skills/ccfa-experiments/SKILL.md`
  - `skills/ccfa-experiments/skill.yaml`
  - `skills/registry.yaml`
  - `tools/ccfa/long_task.py`
  - `tools/ccfa/skill_registry.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_long_task.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_skill_registry.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_long_task`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T181834Z-f6e3da5ec9 - Bind human proof attestations to the reviewed bytes: proof-audit verified reviews need audited_inputs, and argument-audit gains --stamp.

- timestamp: `2026-10-05T18:18:34Z`
- status: `complete`
- author: `codex`
- reason: 人工复核只记录'谁评过'，不记录'评的是哪一版字节'；改稿之后旧签字仍然有效，这是人工验证链条上最后一个静默失效点。
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/argument_audit.py`
  - `tools/tests/test_argument_audit.py`
- tests:
  - `ruff check tools`
  - `tools.tests.test_argument_audit (25 tests)`
  - `tools.tests.test_readiness + test_proof_orchestrator + test_research_ledgers + test_dashboard + test_artifact_badge (95 tests)`
- notes: 新增错误码 proof-review-unbound / proof-review-stale；--stamp 只打印片段，不写文件。

## WC-20261005T182231Z-68d52db630 - Extend the audited_inputs binding to citation-support and figure-support attestations.

- timestamp: `2026-10-05T18:22:31Z`
- status: `complete`
- author: `codex`
- reason: 上一轮只把人工签字绑到了证明文件；引用语义与图表语义两本台账仍然只记'谁评过'，改稿后同样会静默保持有效。
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/argument_audit.py`
  - `tools/tests/test_argument_audit.py`
  - `tools/tests/test_figure_audit.py`
- tests:
  - `ruff check tools`
  - `tools.tests.test_argument_audit + test_figure_audit + test_readiness + test_proof_orchestrator (134 tests)`
- notes: 必录文件：引用=记录里的 source_path，图表=manifest 里的 file；新增 citation-support-unbound/-stale 与 figure-support-unbound/-stale。

## WC-20261005T182608Z-cb45d21fd1 - Give every readiness gate a verdict (pass / fail / blocked / error) so missing inputs no longer look like rejected content.

- timestamp: `2026-10-05T18:26:08Z`
- status: `complete`
- author: `codex`
- reason: ARIS 审计里我们还没抄的最后一条：过去 gate 只有 pass/problem，缺前置台账和内容不过显示成一样，人看不出下一步该补输入还是改内容。顺带核实 resume 已经由 tools/ccfa/long_task.py 实现。
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `ruff check tools`
  - `tools.tests.test_readiness (61 tests)`
- notes: verdicts 由缺失台账映射（LEDGER_GATE_NAMES）+ gate 自身 status 推导；markdown 里每个 gate 行带 verdict，未执行的 blocked gate 单独列一行。

## WC-20261005T182805Z-4eee662850 - Let the installed workbench discover a workflow checkout instead of requiring manual configuration.

- timestamp: `2026-10-05T18:28:05Z`
- status: `complete`
- author: `codex`
- reason: 给合作者用时最大的摩擦是装完必须自己找仓库并填路径；安装包已经支持把 workflow/ 放在 exe 旁边，客户端却只认显式配置。
- files:
  - `app/README.md`
  - `app/ccfa_core/workflow.py`
  - `app/tests/test_workflow.py`
- tests:
  - `app unittest (tests.test_workflow + test_settings, 33 tests)`
  - `ruff check app`
- notes: 搜索顺序：显式配置/环境变量 → 安装目录 workflow\\ → LOCALAPPDATA Programs → 用户目录两个位置；开发时仓库本身仍优先。捆绑 embeddable Python 的代价写进 README。

## WC-20261005T183936Z-ff72f75d7b - Ship a self-contained workflow runtime for the installer: bundle-workflow.ps1 stages an embeddable CPython + tools sources + pip --target dependencies, and build-workbench.ps1 gains -BundleWorkflow.

- timestamp: `2026-10-05T18:39:36Z`
- status: `complete`
- author: `codex`
- reason: 给合作者用时安装包里只有 app，装完还得自己找并配置工作流目录；venv 不能随包分发（pyvenv.cfg 指向构建机解释器），所以用 embeddable CPython。
- files:
  - `app/README.md`
  - `app/ccfa_core/workflow.py`
  - `app/tests/test_workflow.py`
  - `scripts/build-workbench.ps1`
  - `scripts/bundle-workflow.ps1`
  - `tools/ccfa/repro_package.py`
- tests:
  - `app unittest discover (226 tests)`
  - `real bundle + embedded CLI run: 169.8 MB, 84 modules import, readiness/validate exit 0 from cwd=C:\`
  - `tools.tests.test_repro_package (27 tests)`
  - `tools.tests.test_scripts in the main checkout (136 tests)`
- notes: 实测发现嵌入版 CPython 不含 venv，repro_package 顶层 import 会让 readiness 崩；已改为惰性 import，并在打包脚本里逐模块 import 自检。

## WC-20261005T184206Z-db62f9953f - Add ccfa-workbench.exe --self-check so an installed copy can be smoke-tested without launching the GUI.

- timestamp: `2026-10-05T18:42:06Z`
- status: `complete`
- author: `codex`
- reason: 安装包没法用脚本验证：GUI 一跑就占用界面，看不出冻结后的 app 到底有没有发现自带的工作流运行时。
- files:
  - `app/README.md`
  - `app/ccfa_gui/main.py`
  - `app/tests/test_gui_smoke.py`
- tests:
  - `app unittest discover (227 tests)`
  - `ruff check app`
- notes: self-check 复用窗口同一条发现路径并调用工作流的 probe；输出 JSON 含 probe_ok/probe_detail。

## WC-20261005T184733Z-9a456ec0c5 - Register external P0 skills and support multiple source roots

- timestamp: `2026-10-05T18:47:33Z`
- status: `complete`
- author: `codex`
- reason: Promote already-referenced global CCF skills into the workflow registry without copying their source, and derive content-hash versions for unversioned external skills while keeping missing external sources non-fatal unless strict validation is requested.
- files:
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `skills/registry.yaml`
  - `tools/ccfa/skill_registry.py`
  - `tools/tests/test_skill_registry.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T184756Z-5e249ff15e - Register external P0 skills and support multiple source roots

- timestamp: `2026-10-05T18:47:56Z`
- status: `complete`
- author: `codex`
- reason: Promote already-referenced global CCF skills into the workflow registry without copying their source, and derive content-hash versions for unversioned external skills while keeping missing external sources non-fatal unless strict validation is requested.
- files:
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `skills/registry.yaml`
  - `tools/ccfa/skill_registry.py`
  - `tools/tests/test_skill_registry.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T185201Z-74478856dd - Register P1 Nature and Cell methodology skills

- timestamp: `2026-10-05T18:52:01Z`
- status: `complete`
- author: `codex`
- reason: Expand the external-source registry with the selected Nature/Cell skill set now that source roots, content hashes, dependency resolution, packing and installation are in place.
- files:
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `skills/registry.yaml`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T185232Z-27436dd029 - Register P1 Nature and Cell methodology skills

- timestamp: `2026-10-05T18:52:32Z`
- status: `complete`
- author: `codex`
- reason: Expand the external-source registry with the selected Nature/Cell skill set now that source roots, content hashes, dependency resolution, packing and installation are in place.
- files:
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `skills/registry.yaml`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T185818Z-1b96b722e0 - Add external-service adapter capability checks

- timestamp: `2026-10-05T18:58:18Z`
- status: `complete`
- author: `codex`
- reason: Separate installed skills from configured and functional external services, record only env-var names, and expose adapter probes without reading or printing secrets.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/external-adapters.ps1`
  - `skills/adapters.yaml`
  - `skills/registry.yaml`
  - `tools/ccfa/external_adapters.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_external_adapters.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_external_adapters`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T185842Z-29a8ef8bc1 - Add external-service adapter capability checks

- timestamp: `2026-10-05T18:58:42Z`
- status: `complete`
- author: `codex`
- reason: Separate installed skills from configured and functional external services, record only env-var names, and expose adapter probes without reading or printing secrets.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/external-adapters.ps1`
  - `skills/adapters.yaml`
  - `skills/registry.yaml`
  - `tools/ccfa/external_adapters.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_external_adapters.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_external_adapters`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T190205Z-8e86b0dd3f - Add a readiness view to the workbench: a 运行 readiness action that renders the six dimensions, the non-pass gate verdicts and the blocking list in one table.

- timestamp: `2026-10-05T19:02:05Z`
- status: `complete`
- author: `codex`
- reason: 工作台只驱动 validate/milestones/checkpoints 三条命令，而日常循环的核心是 readiness；报告里的维度、gate 结论和阻塞清单此前只能在终端看。
- files:
  - `app/README.md`
  - `app/ccfa_core/checks.py`
  - `app/ccfa_gui/icon_paths.py`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_checks.py`
  - `app/tests/test_gui_smoke.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
- tests:
  - `app unittest discover (229 tests)`
  - `ruff check app`
- notes: 表格三段：维度 / 非 pass 的 gate 结论 / 阻塞项；横幅给第一条阻塞与结论计数。

## WC-20261005T190513Z-4b9c885c93 - Register drawio-skill as a local visual-composition capability

- timestamp: `2026-10-05T19:05:13Z`
- status: `complete`
- author: `codex`
- reason: The registry had CCF and Nature figure skills but no editable diagram authoring; drawio-skill produces editable .drawio architecture/UML/BPMN diagrams on Windows with no API key, so it is registered as a codex-root capability skill with a ccf-common dependency.
- files:
  - `docs/workflow-guide.md`
  - `skills/registry.yaml`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T190625Z-dcd0351ab5 - Register drawio-skill as a local visual-composition capability

- timestamp: `2026-10-05T19:06:25Z`
- status: `complete`
- author: `codex`
- reason: The registry had CCF and Nature figure skills but no editable diagram authoring; drawio-skill produces editable .drawio architecture/UML/BPMN diagrams on Windows with no API key, so it is registered as a codex-root capability skill with a ccf-common dependency.
- files:
  - `docs/workflow-guide.md`
  - `skills/registry.yaml`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T190724Z-2f02f72ec5 - Show the stage gate criterion in the workbench project panel, sourced from the workflow gate definition.

- timestamp: `2026-10-05T19:07:24Z`
- status: `complete`
- author: `codex`
- reason: The panel showed the gate state badge but never what the gate requires; the criterion was only reachable by running ccfa.stages in a terminal.
- files:
  - `app/ccfa_core/projects.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_gui_smoke.py`
  - `app/tests/test_projects.py`
- tests:
  - `app unittest discover (231 tests)`
  - `ruff check app`
- notes: Decorative lookup: an unreadable gate yields an empty hint instead of blocking the project from loading.

## WC-20261005T191403Z-8e81189b54 - Drive stage advance and rollback from the workbench, and wrap the action row instead of eliding its labels.

- timestamp: `2026-10-05T19:14:03Z`
- status: `complete`
- author: `codex`
- reason: Stage transitions were CLI-only (scripts/state.ps1), so the panel could show the stage but not move it; and adding a fifth action squeezed the row until Qt elided button text even at 1280px.
- files:
  - `app/README.md`
  - `app/ccfa_core/state.py`
  - `app/ccfa_gui/flow_layout.py`
  - `app/ccfa_gui/icon_paths.py`
  - `app/ccfa_gui/stage_dialog.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_gui_smoke.py`
  - `app/tests/test_state.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
- tests:
  - `app unittest discover (246 tests)`
  - `ruff check app`
- notes: The transition dialog only offers targets from the workflow stage table, requires a reason, and calls ccfa.state --confirm; the window then re-scans papers/ so the badges show what the workflow wrote. The action row uses a small FlowLayout so narrow panes wrap to a second line.

## WC-20261005T192704Z-8bb03b2cbc - Show each paper git/GitHub collaboration state in the project list, via a new ccfa.readiness --collaboration-only report.

- timestamp: `2026-10-05T19:27:04Z`
- status: `complete`
- author: `codex`
- reason: A dirty tree or a missing remote is a readiness blocker that only showed up deep inside the readiness report, so the list could not tell a wired-up paper from one whose version history and CI do not exist.
- files:
  - `app/README.md`
  - `app/ccfa_core/collaboration.py`
  - `app/ccfa_gui/collaboration_probe.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_chat_e2e.py`
  - `app/tests/test_chat_panel.py`
  - `app/tests/test_collaboration.py`
  - `app/tests/test_gui_smoke.py`
  - `app/tests/test_workbench_e2e.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `app unittest discover (256 tests)`
  - `ruff check app tools`
  - `tools.tests.test_readiness + test_docs_consistency (80 tests)`
- notes: The slim report reuses the full report own git probe and dirty rule (generated readiness records do not count), pinned by a test that compares both blockers lists. Rows show a marker instead of an inline reason because the 180px sidebar elides any suffix; the probe runs on a shared QThreadPool with a generation guard, and tests disable it except one real subprocess case.

## WC-20261005T193531Z-60ed2618fc - Turn the readiness report into a countdown-first one-page report, and let the workbench export and show it.

- timestamp: `2026-10-05T19:35:31Z`
- status: `complete`
- author: `codex`
- reason: The report listed dimensions first and never named the deadline, so the one number that changes behaviour (days to submission) was only visible by running milestones separately; the app could also not produce the file at all.
- files:
  - `app/README.md`
  - `app/ccfa_core/checks.py`
  - `app/ccfa_core/projects.py`
  - `app/ccfa_gui/icon_paths.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_checks.py`
  - `app/tests/test_gui_smoke.py`
  - `app/tests/test_projects.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `app unittest discover (264 tests)`
  - `ruff check app tools`
  - `tools.tests.test_readiness + test_docs_consistency (88 tests)`
- notes: readiness JSON gains deadline/mode/days_left/overdue and the Markdown leads with ## Summary (countdown, blocker count and first blocker, human checkpoint count) plus a ## Deadline section. The workbench badge shows the countdown and keeps the date in its tooltip, and a header icon button exports reviews/readiness-<date>.md through the workflow render and opens it; the report is never re-summarised by the app.

## WC-20261005T194216Z-581900cade - Make the workbench probe verify that the resolved interpreter can actually import the gates dependencies, via a new ccfa.doctor --imports-only.

- timestamp: `2026-10-05T19:42:16Z`
- status: `complete`
- author: `codex`
- reason: Running readiness under an interpreter without pymupdf/z3/cvc5 turned formal-check and claim-candidates into failures, and a failed gate reads exactly like a blocked paper: a misconfigured interpreter silently inflated the blocking list from 2 to 4 with no hint that the machine was at fault.
- files:
  - `app/README.md`
  - `app/ccfa_core/workflow.py`
  - `app/tests/test_gui_smoke.py`
  - `app/tests/test_workflow.py`
  - `tools/ccfa/doctor.py`
  - `tools/tests/test_doctor.py`
- tests:
  - `app unittest discover (268 tests)`
  - `ruff check app tools`
  - `tools.tests.test_doctor + test_readiness + test_docs_consistency (123 tests)`
- notes: doctor --imports-only imports each dependency in the running interpreter and prints JSON (module, capability, error), green in tools/.venv and naming pymupdf/z3/cvc5/cryptography under app/.venv. probe() runs it and fails closed with the module list; an older workflow without the flag degrades to "self-check unavailable" instead of failing. Two tests that asserted a fixed verdict against "the real workflow" now assert the contract, since whether that interpreter has the deps is a property of the machine.

## WC-20261005T194731Z-3ebdb46b6e - Cap a decimal dataval claim rounding tolerance at a fraction of the source magnitude, so dropping precision stops making a mismatch easier to pass.

- timestamp: `2026-10-05T19:47:31Z`
- status: `complete`
- author: `codex`
- reason: The tolerance came only from the claim own decimals, so writing 0.1 (half unit 0.05) was accepted against a source of 0.143 while writing 0.143 (half unit 0.0005) was not: the rule rewarded losing precision, and a coarse claim stops constraining the value it claims to trace.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/datavalue.py`
  - `tools/ccfa/trace_claims.py`
  - `tools/tests/test_datavalue.py`
  - `tools/tests/test_trace_claims.py`
- tests:
  - `ruff check tools`
  - `tools.tests.test_datavalue + test_trace_claims + test_trace_claims_e2e + test_dataval + test_claims_policy + test_readiness + test_docs_consistency (161 tests)`
- notes: values_match gains max_rounding_error (default 0.05 = about two significant figures); the implied half-unit may not exceed it, integer claims are untouched (they were already exact). trace_claims.check and the CLI forward it, and a failure caused only by the cap says 小数位不足 plus the --max-rounding-error 0 escape. Verified against the live paper: all 58 dataval tags there are integers, readiness still reports 2 blockers and trace-claims still passes.

## WC-20261005T195052Z-7535723af0 - Add a claim polarity field to the claim registry, require it for supported empirical/theoretical claims, and require an experiment behind a supported null claim.

- timestamp: `2026-10-05T19:50:52Z`
- status: `complete`
- author: `codex`
- reason: A claim registry entry recorded what a claim was about (type) and how strong it was (status) but never what it asserted, so a "no difference" result could be marked supported on the strength of a citation or a figure, and nothing distinguished an effect claim from a null one when judging whether the evidence matched the sentence.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/research_ledgers.py`
  - `tools/tests/test_research_ledgers.py`
- tests:
  - `ccfa.research_ledgers --paper-root papers/example-paper --require-core (0 problems)`
  - `ruff check tools`
  - `tools.tests.test_research_ledgers + test_docs_consistency (43 tests)`
- notes: polarity is optional (effect/null/descriptive) and validated when present; descriptive claims are exempt because a count asserts no direction, which is why the live paper 5 supported descriptive claims are untouched. A supported empirical/theoretical claim without polarity is claim-registry-polarity-missing, and polarity=null without an experiment is claim-registry-null-experiment-missing. Verified the live registry still reports 0 problems and the readiness research-ledgers gate still passes.

## WC-20261005T195348Z-3793a7ad41 - Make the post-submission tail fail closed and give citation calibration a live gold set

- timestamp: `2026-10-05T19:53:48Z`
- status: `complete`
- author: `codex`
- reason: Two gaps from the GitHub comparison: the writing/rebuttal/resubmit/talk tail had contracts but no live run, and calibration had a harness but no data. readiness registered the tail gates only when their input files already existed, so a missing file silently deleted its own gate; and citation calibration had no producer of labels or predictions.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/citation_calibration.py`
  - `tools/ccfa/post_submission.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/resubmit_pipeline.py`
  - `tools/ccfa/talk_pipeline.py`
  - `tools/tests/test_citation_calibration.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_citation_calibration`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_post_submission`
  - `tools.tests.test_readiness`
  - `tools.tests.test_resubmit_pipeline`
  - `tools.tests.test_scripts`
  - `tools.tests.test_talk_pipeline`

## WC-20261005T195416Z-824712e3ea - Make the post-submission tail fail closed and give citation calibration a live gold set

- timestamp: `2026-10-05T19:54:16Z`
- status: `complete`
- author: `codex`
- reason: Two gaps from the GitHub comparison: the writing/rebuttal/resubmit/talk tail had contracts but no live run, and calibration had a harness but no data. readiness registered the tail gates only when their input files already existed, so a missing file silently deleted its own gate; and citation calibration had no producer of labels or predictions.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/citation_calibration.py`
  - `tools/ccfa/post_submission.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/resubmit_pipeline.py`
  - `tools/ccfa/talk_pipeline.py`
  - `tools/tests/test_citation_calibration.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_citation_calibration`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_post_submission`
  - `tools.tests.test_readiness`
  - `tools.tests.test_resubmit_pipeline`
  - `tools.tests.test_scripts`
  - `tools.tests.test_talk_pipeline`

## WC-20261005T195621Z-9b382d19ae - Give a run a scientific role (treatment/negative-control/ablation/baseline) and require a supported effect claim to cite a control run.

- timestamp: `2026-10-05T19:56:21Z`
- status: `complete`
- author: `codex`
- reason: A run log said whether a run was an experiment and how it ended, but never which side of the experiment it was, so an effect claim could be marked supported on a log that only ever contained the treatment: nothing in the record ruled out the obvious confound.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/research_ledgers.py`
  - `tools/ccfa/run_log.py`
  - `tools/tests/test_research_ledgers.py`
  - `tools/tests/test_run_log.py`
- tests:
  - `ccfa.research_ledgers + ccfa.run_log check on papers/example-paper (0 problems)`
  - `ruff check tools`
  - `tools.tests.test_run_log + test_research_ledgers + test_docs_consistency + test_experiment_loop + test_readiness (201 tests)`
- notes: record_run validates role against VALID_ROLES and refuses a role on a purpose=build run; run-log check reports run-log-role-invalid and run-log-role-on-build for hand-edited records. research_ledgers now reads run roles and reports claim-registry-control-run-missing for a supported empirical polarity=effect claim whose referenced runs contain no negative-control/ablation. Backfill note: the live paper has no experiment-purpose runs at all (all 7 run-log records are builds), and its 5 supported claims are descriptive, so there was nothing to label and the new rule does not fire on it.

## WC-20261005T200124Z-8ebfd7ce94 - Add post-submission init and make a tail stage require its own section

- timestamp: `2026-10-05T20:01:24Z`
- status: `complete`
- author: `codex`
- reason: The tail still passed while empty: a skeleton file satisfied the missing-file check and every section stayed not-started. init now derives a schema-correct ledger from the paper's real run/claim/figure ids without overwriting, and readiness requires the section a stage is named after to be complete.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/post_submission.py`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_post_submission.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_post_submission`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T200139Z-c6134746ad - Add post-submission init and make a tail stage require its own section

- timestamp: `2026-10-05T20:01:39Z`
- status: `complete`
- author: `codex`
- reason: The tail still passed while empty: a skeleton file satisfied the missing-file check and every section stayed not-started. init now derives a schema-correct ledger from the paper's real run/claim/figure ids without overwriting, and readiness requires the section a stage is named after to be complete.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/post_submission.py`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_post_submission.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_post_submission`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T200146Z-8387e0bd7e - Add an optional held-out evaluation plan ledger whose freeze date, access budget and every access are validated, and require a supported effect claim to cite one.

- timestamp: `2026-10-05T20:01:46Z`
- status: `complete`
- author: `codex`
- reason: Nothing recorded which data was never used for tuning, so an effect could be reported after unbounded looks at the same evaluation set; the run log said what ran but not whether the number came from a split that was frozen before it was read.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/research_ledgers.py`
  - `tools/tests/test_research_ledgers.py`
- tests:
  - `ccfa.research_ledgers (worktree code) on papers/example-paper: 0 problems`
  - `ruff check tools`
  - `tools.tests.test_research_ledgers + test_docs_consistency + test_readiness (125 tests)`
- notes: data/held-out-plan.yaml splits declare role (held-out/development), artifact and, for held-out, frozen_at plus a positive access_budget; each access records run_id/at/reason and must resolve to a real run. Fail-closed codes: held-out-budget-exceeded, held-out-access-before-freeze, held-out-unknown-run, held-out-artifact-missing, held-out-invalid. An effect empirical supported claim must cite a held-out access or the plan must carry a >=40 character non-placeholder no_held_out_reason (claim-registry-held-out-missing). Live paper unaffected: no effect claims and no plan file.

## WC-20261005T201207Z-2ee565ab0b - Make the tool layer runnable without PowerShell

- timestamp: `2026-10-05T20:12:07Z`
- status: `complete`
- author: `codex`
- reason: Portability was the weakest axis: python -m ccfa did not exist, the ccfa.dispatch entry point was untested and its aliases were wrong for statistics/rigor-rubric/archive/experiment-optimize, and every tool was reachable only through 71 .ps1 wrappers. A portable dispatcher, a POSIX launcher and a fail-closed parity test make the same tools run on Linux and macOS, with a Linux CI job as evidence.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-guide.md`
  - `pyproject.toml`
  - `scripts/ccfa`
  - `scripts/install-toolchain.ps1`
  - `tools/ccfa/__main__.py`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_dispatch.py`
  - `tools/tests/test_github_workflows.py`
  - `tools/tests/test_packaging.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_packaging`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261005T201305Z-1f8150ba42 - Make the tool layer runnable without PowerShell

- timestamp: `2026-10-05T20:13:05Z`
- status: `complete`
- author: `codex`
- reason: Portability was the weakest axis: python -m ccfa did not exist, the ccfa.dispatch entry point was untested and its aliases were wrong for statistics/rigor-rubric/archive/experiment-optimize, and every tool was reachable only through 71 .ps1 wrappers. A portable dispatcher, a POSIX launcher and a fail-closed parity test make the same tools run on Linux and macOS, with a Linux CI job as evidence.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-guide.md`
  - `pyproject.toml`
  - `scripts/ccfa`
  - `scripts/install-toolchain.ps1`
  - `tools/ccfa/__main__.py`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_dispatch.py`
  - `tools/tests/test_github_workflows.py`
  - `tools/tests/test_packaging.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_packaging`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261005T201620Z-a6490aa603 - Keep the paper CI deterministic gates identical on Windows and Linux

- timestamp: `2026-10-05T20:16:20Z`
- status: `complete`
- author: `codex`
- reason: The paper repository now runs the deterministic gates on ubuntu-latest through .github/scripts/deterministic-gates.sh as well as inline with pwsh on windows-latest. A fail-closed test asserts both runners exercise exactly the same ccfa tool set, so the Linux job cannot silently become a weaker check.
- files:
  - `tools/tests/test_github_workflows.py`
- tests:
  - `tools.tests.test_github_workflows`

## WC-20261005T201635Z-0025570e27 - Keep the paper CI deterministic gates identical on Windows and Linux

- timestamp: `2026-10-05T20:16:35Z`
- status: `complete`
- author: `codex`
- reason: The paper repository now runs the deterministic gates on ubuntu-latest through .github/scripts/deterministic-gates.sh as well as inline with pwsh on windows-latest. A fail-closed test asserts both runners exercise exactly the same ccfa tool set, so the Linux job cannot silently become a weaker check.
- files:
  - `tools/tests/test_github_workflows.py`
- tests:
  - `tools.tests.test_github_workflows`

## WC-20261005T202518Z-4523c9af47 - Fix the three machine-dependent tools-test failures that kept CI red

- timestamp: `2026-10-05T20:25:18Z`
- status: `complete`
- author: `codex`
- reason: The GitHub Windows runner failed tools-impact on every recent push. experiment_optimizer compared a spec path spelling (8.3 short name RUNNER~1) against a resolved paper_root and raised ValueError on a file inside the paper; two external-adapter tests asserted installed against whatever skills the developer machine had, so they failed on a clean runner. Confirmed against real Actions logs for runs 37360029400 and 37361015600, which failed identically before this branch existed.
- files:
  - `tools/ccfa/experiment_optimizer.py`
  - `tools/tests/test_experiment_optimizer.py`
  - `tools/tests/test_external_adapters.py`
- tests:
  - `scripts/test-impact.ps1 run --suite tools --full (1812 tests)`
  - `tools.tests.test_experiment_optimizer`
  - `tools.tests.test_external_adapters`

## WC-20261005T202534Z-67bb3895f9 - Fix the three machine-dependent tools-test failures that kept CI red

- timestamp: `2026-10-05T20:25:34Z`
- status: `complete`
- author: `codex`
- reason: The GitHub Windows runner failed tools-impact on every recent push. experiment_optimizer compared a spec path spelling (8.3 short name RUNNER~1) against a resolved paper_root and raised ValueError on a file inside the paper; two external-adapter tests asserted installed against whatever skills the developer machine had, so they failed on a clean runner. Confirmed against real Actions logs for runs 37360029400 and 37361015600, which failed identically before this branch existed.
- files:
  - `tools/ccfa/experiment_optimizer.py`
  - `tools/tests/test_experiment_optimizer.py`
  - `tools/tests/test_external_adapters.py`
- tests:
  - `tools.tests.test_experiment_optimizer`
  - `tools.tests.test_external_adapters`

## WC-20261005T213608Z-637574217a - Record an end-to-end snapshot of the flagship paper: gate verdicts, the six human checkpoints, environment health and the workbench-side links actually rerun.

- timestamp: `2026-10-05T21:36:08Z`
- status: `complete`
- author: `codex`
- reason: The layered checks each answered one question, but nothing stated the current whole-paper state in one place, so it was impossible to see at a glance that every remaining blocker is human or external rather than mechanical.
- files:
  - `docs/e2e-check-2026-10-06.md`
- tests:
  - `app export_readiness -> 6200 bytes with ## Summary`
  - `ccfa.doctor --repo-root repo (0 problems, 1 advisory: zotero 23119)`
  - `ccfa.readiness --collaboration-only (collaboration_ready=true, commit 5253728)`
  - `ccfa.readiness on papers/example-paper (exit 1, 2 blockers, 18/20 gates pass)`
  - `ccfa_gui.main --self-check (probe_ok=true, exit 0)`
- notes: Paper repo untouched: every report was written to %TEMP%, and the snapshot records that. 20 gates: 18 pass; argument-audit fails with 8 proof-review-not-verified + 6 citation-support-missing + 1 figure-support-missing, cross-review fails with review-blocking.

## WC-20261005T215008Z-7760a8b83d - Add ccfa.e2e_check / scripts/e2e-check.ps1: one command that composes the full gate set and the platform preflight into a single Markdown snapshot.

- timestamp: `2026-10-05T21:50:08Z`
- status: `complete`
- author: `codex`
- reason: The state of a paper was spread over five commands and five outputs, so seeing that every remaining blocker is human rather than mechanical required running readiness, doctor, self-check, collaboration and milestones by hand and reading all of them.
- files:
  - `README.md`
  - `scripts/e2e-check.ps1`
  - `tools/ccfa/e2e_check.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `ccfa.e2e_check on the flagship paper: ready=false, 2 blocking, 20 gates (18 pass), 6 human checkpoints, 0 environment problems / 1 advisory`
  - `ruff check tools scripts`
  - `tools.tests.test_scripts inventory/contract + test_docs_consistency (19 tests)`
- notes: Read-only: without --out it prints and writes nothing, and it never touches the paper tracked files. Output leads with an auto-generated headline (ready/blocking/gate pass count) then the gate table with de-duplicated problem codes, the human checkpoint table with its destination ledger, the doctor problems/advisories plus the installed/reachable inventory, git/CI and the countdown. discover_paper refuses to guess when papers/ holds more than one project. Exit code reports whether the snapshot was produced, not whether the paper is ready.

## WC-20261005T215837Z-36be525a3c - Update the e2e snapshot with the Zotero verification results and the fact that the environment is now fully green.

- timestamp: `2026-10-05T21:58:37Z`
- status: `complete`
- author: `codex`
- reason: The committed snapshot listed Zotero 23119 as the one remaining environment gap; leaving it that way after the link was verified and doctor went to 0 advisories would make a dated record quietly wrong.
- files:
  - `docs/e2e-check-2026-10-06.md`
- tests:
  - `ccfa.doctor --repo-root repo (0 problems, 0 advisories, functional zotero HTTP 200)`
  - `zotero-mcp.exe serve initialize + 41 tools + import/search/bibtex/delete round trip`
- notes: Records the dedupe result precisely: if_exists=skip de-duplicates when the record carries an identifier (DOI), and does not fall back to fuzzy title matching. Three probe items were trashed and live items are back to zero; no Zotero account sync is configured, so nothing left the machine.

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

## WC-20261005T221321Z-a43688691e - Reconcile the local workflow branch with origin/master and register e2e-check in the dispatch map and compile list.

- timestamp: `2026-10-05T22:13:21Z`
- status: `complete`
- author: `codex`
- reason: Local master and origin/master had diverged (42 ahead / 13 behind) with intersecting work, and the newly added e2e-check wrapper was missing from dispatch.COMMANDS and the CI py_compile list, which broke the dispatch parity tests.
- files:
  - `.github/workflows/tests.yml`
  - `docs/workflow-change-log.jsonl`
  - `docs/workflow-change-log.md`
  - `docs/workflow-guide.md`
  - `tools/ccfa/dispatch.py`
- tests:
  - `tools.tests.test_dispatch (7 tests)`
- notes: Merge commit 8ecb3bf. Conflicts in the change log were resolved by union of entry ids; workflow-guide.md kept the local side after verifying it is a strict superset of origin/master (0 remote-only lines).

## WC-20261005T221325Z-baf9040305 - Backfill the change-log entry for semantic and hybrid retrieval in the shared literature library.

- timestamp: `2026-10-05T22:13:25Z`
- status: `complete`
- author: `codex`
- reason: Commit 76566b0 added semantic and hybrid retrieval to tools/ccfa/library.py plus 349 lines of tests, but landed without a change-log entry, so change-log check flagged both files as uncovered.
- files:
  - `tools/ccfa/library.py`
  - `tools/tests/test_library.py`
- tests:
  - `tools.tests.test_library (65 tests)`
- notes: Entry written after the fact to satisfy the append-only change-log contract; the tests were re-run before recording this entry.

## WC-20261005T221338Z-03721b5e75 - Add the workflow assessment reports and refresh the gap summary.

- timestamp: `2026-10-05T22:13:38Z`
- status: `complete`
- author: `codex`
- reason: These analysis documents record the tooling inventory, the top-venue evaluation, the big-check and cleanup findings, the disk relocation, the toolchain install and the workflow fit audit; they were written to docs/ without accompanying change-log entries.
- files:
  - `docs/big-check-and-cleanup-2026-10-05.md`
  - `docs/disk-relocation-2026-10-05.md`
  - `docs/research-workflow-topvenue-evaluation-2026-10-05.md`
  - `docs/toolchain-workflow-fit-2026-10-05.md`
  - `docs/tooling-gaps-2026-10-05.md`
  - `docs/tooling-install-2026-10-05.md`
  - `docs/workflow-gap-summary.md`
- tests:
  - `tools.tests.test_docs_consistency (17 tests)`
- notes: Documentation only; no workflow code changed.

## WC-20261005T222126Z-9983a0e142 - Correct the workflow introduction: the Windows workbench installer is delivered, not pending.

- timestamp: `2026-10-05T22:21:26Z`
- status: `complete`
- author: `codex`
- reason: docs/research-workflow-intro.md still claimed the Windows launcher, shortcut and PyInstaller installer were not delivered, but dist/ccfa-workbench-setup-0.1.0.exe exists and the installed ccfa-workbench.exe --self-check passes; the remaining gap is a clean-machine acceptance run, not the build.
- files:
  - `docs/research-workflow-intro.md`
- tests:
  - `ccfa-workbench.exe --self-check (probe_ok=true, exit 0)`
  - `tools.tests.test_docs_consistency (17 tests)`
- notes: Documentation corrected against the built artifact; the product-readiness table and the next-step list now say the installer is built and only the clean-machine acceptance remains.

## WC-20261005T223117Z-b272b3d157 - Inventory the workflow's plugins, tools and skills, and analyse the remaining gaps against open-source research agents.

- timestamp: `2026-10-05T22:31:17Z`
- status: `complete`
- author: `codex`
- reason: The tool and plugin layer changed substantially (second provider, nine formal engines, installer, archive and compute adapters), so the earlier tooling-gaps document was stale and no single document listed the current inventory plus the remaining methodological gaps.
- files:
  - `docs/research-workflow-tooling-and-gaps-2026-10-06.md`
- tests:
  - `tools.tests.test_docs_consistency (17 tests)`
- notes: Documentation only. Records 87 modules, 72 entries, 9 MCP servers, 28 plugins, 305 skills and the verified adoption of polarity / held-out / negative-control / gate drills; the remaining gaps are metrics (null-model baseline, attempt throughput), external links (remote compute, Zenodo DOI, clean-machine installer acceptance) and the six human checkpoints.

## WC-20261005T223656Z-834aa52586 - Add the missing cryptography pin to the tools lock and guard against lock drift

- timestamp: `2026-10-05T22:36:56Z`
- status: `complete`
- author: `codex`
- reason: CI installs tools/requirements.lock, not requirements.txt, and cryptography existed only in the latter. A clean runner therefore had no cryptography, so test_doctor's fully-provisioned assertion failed there while passing on a developer machine. Observed in Actions run 37381530489 (7890a6e): missing [cryptography], ok=false. The failure is masked on docs-only pushes because impact selection runs about 17 tests, so only the nightly full run would have caught it.
- files:
  - `tools/requirements.lock`
  - `tools/tests/test_packaging.py`
- tests:
  - `clean venv + uv pip install -r tools/requirements.lock + doctor --imports-only`
  - `tools.tests.test_doctor`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_packaging`

## WC-20261005T223811Z-7da4601920 - Pin the rule that dependency files force the full test suite

- timestamp: `2026-10-05T22:38:11Z`
- status: `complete`
- author: `codex`
- reason: No behaviour change. While fixing the lock drift I claimed the impact selector also missed tools/requirements.lock; testing the original code showed both lock files already returned full=True through the generic 'unmapped path under tools/ or app/' fall-through. The two explicit entries plus a new test make an implicit, load-bearing rule explicit, so a future early return cannot silently downgrade a dependency change to a partial run.
- files:
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_test_impact.py`
- tests:
  - `tools.tests.test_test_impact`

## WC-20261010-coling-real-smoke - Add isolated real LangChain and public tiny LLM smoke evidence jobs

- timestamp: `2026-10-10T05:06:00Z`
- status: `pending`
- author: `ChatGPT`
- reason: User requested public independently auditable installed-framework and open-weight model execution; isolated branch only.
- files:
  - `papers/coling27-real-smoke/real_core_smoke.py`
  - `papers/coling27-real-smoke/open_model_probe.py`
  - `.github/workflows/coling-real-core-smoke.yml`
- tests:
  - `Local Python syntax check passed (earlier kit)`
  - `GitHub Actions pending; not yet executed`
- notes: Standalone smoke tests, not full COLING main experiment.

## WC-20261010-coling-fix-workflow-parse - Simplify isolated smoke workflow after GitHub rejected initial workflow before scheduling jobs

- timestamp: `2026-10-10T05:24:00Z`
- status: `pending`
- author: `ChatGPT`
- reason: Observed Actions run 38027179017 completed failure with zero jobs; remove optional release job to isolate validation, retain artifact uploads.
- files:
  - `.github/workflows/coling-real-core-smoke.yml`
- tests:
  - `GitHub Actions run 38027179017 failed before any jobs`
  - `Revised workflow rerun pending`
- notes: Raw artifacts will be retained as Actions artifacts; no release automatically created in this diagnostic revision.

## WC-20261010-fix-visible-smoke - Restore valid inline genuine installed LangChain smoke workflow after connector returned hidden-file placeholders

- timestamp: `2026-10-10T05:29:00Z`
- status: `pending`
- author: `ChatGPT`
- reason: Original pushed blob was 155-byte placeholder; prior GitHub run failed validation before job creation. Inline workflow avoids unavailable file transport.
- files:
  - `.github/workflows/coling-real-core-smoke.yml`
- tests:
  - `Existing run 38027179017 failed without jobs`
  - `Corrected smoke run pending`
- notes: This is a minimal real-framework smoke, not v18 experiment.

## WC-20261010-coling-numpy - Install numpy for genuine InMemoryVectorStore cosine scoring

- timestamp: `2026-10-10T05:27:00Z`
- status: `pending`
- author: `ChatGPT`
- reason: Observed actual runner 38027315800 failure: ImportError numpy required after real BaseRetriever.invoke entered vector-store code.
- files:
  - `.github/workflows/coling-real-core-smoke.yml`
- tests:
  - `Official wheel and installed core completed successfully in run 38027315800`
  - `Corrected installed-core smoke pending`
- notes: No claim of successful full workflow until GitHub job returns green.

## WC-20261010-coling-v18-real-agent - Run original v18 time-weighted audited two-read retrieval and 24 real LangChain Agent cases in CI

- timestamp: `2026-10-10T05:43:00Z`
- status: `pending`
- author: `ChatGPT`
- reason: Strict pinned installed-core source and full synthetic agent scenario from v18, evidence saved even if execution fails. Source payload pinned in Git.
- files:
  - `papers/coling27-v18-runtime/v18-runtime.zip`
  - `.github/workflows/coling-v18-real-agent.yml`
- tests:
  - `Source ZIP SHA-256 retained in workflow log; check pending`
  - `CI real framework and 24-case agent pending`
- notes: Synthetic agent policy and embeddings; not a genuine autonomous LLM agent. Public GitHub branch only; master unchanged.

## WC-20261010-v18-relevance-adapter - Adapt official InMemoryVectorStore cosine similarities to upstream relevance-score API

- timestamp: `2026-10-10T05:47:00Z`
- status: `pending`
- author: `ChatGPT`
- reason: Real installed-core run 38027597282 failed in BaseVectorStore._select_relevance_score_fn NotImplementedError; no source hash change to upstream retriever.
- files:
  - `papers/coling27-v18-runtime/v18-runtime.zip`
- tests:
  - `Python compile/zip hashes local; corrected v18 full run pending`
  - `Previously run 38027597282: official install PASS, runtime relevance API mismatch FAIL`
- notes: The wrapper uses identity on cosine similarities with authentic official InMemoryVectorStore base class; source hash remains pinned.

## WC-20261010-v18-store-class-report - Report installed InMemoryVectorStore base type and concrete relevance adapter separately

- timestamp: `2026-10-10T05:51:00Z`
- status: `pending`
- author: `ChatGPT`
- reason: Real v18 run 38027694447 completed signed two-read execution; independent verifier failed on concrete adapter class name rather than official base class.
- files:
  - `papers/coling27-v18-runtime/v18-runtime.zip`
- tests:
  - `real LangChain two-read runner succeeded in Actions 38027694447`
  - `Independent verifier previously rejected misleading class report; fix pending`
- notes: Avoids weakening independent verifier; adds concrete subclass reporting field.

## WC-20261010-v18-live-openweight-llm - Extend full genuine LangChain v18 audit with 24-pair actual open-weight model generation

- timestamp: `2026-10-10T05:56:00Z`
- status: `pending`
- author: `ChatGPT`
- reason: The real pinned two-read ledger and 24 real LangChain Agent paths succeeded in Actions 38027777798. Run a public open-weight instruction model on verified trajectories, preserving raw generated tokens, signed trace references, model revision, hash, and paired independent analysis without API keys.
- files:
  - `.github/workflows/coling-v18-real-agent.yml`
  - `papers/coling27-v18-runtime/v18-runtime.zip`
- tests:
  - `Actions run 38027777798: full official LangChain audit + 24 Agents PASS`
  - `True open-weight LLM run pending; never count mocked transport`
- notes: Uses SmolLM2-135M-Instruct on CPU; not OpenAI GPT nor autonomous model tool routing; clearly separate result type.
