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

