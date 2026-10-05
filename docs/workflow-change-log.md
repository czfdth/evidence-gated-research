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

