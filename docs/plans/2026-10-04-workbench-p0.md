# workbench P0 实施计划（论文工作台：桌面骨架 + 状态看板 + BYO API）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付"论文工作台"的第一个可运行版本：Windows 桌面壳（PySide6）能看到 `papers/*` 项目与阶段门清单、能一键跑确定性检查、能在设置页配置任意 OpenAI 兼容 API（密钥只进 Windows 凭据管理器）。核心逻辑与 GUI 分层，核心零 Qt 依赖、可独立测试。

**定位（建议已定）**：做"论文工作台"，不做通用智能体平台；智能体引擎（P1）与自定义 API 工具注册表（P2）后续接入。P0 只证明最窄链路。

**Spec/账本：** `docs/design/2026-10-03-research-workflow-design.md`、`docs/sdd/2026-10-03-evidence-tracking-progress.md`（本计划新增 E57–E59）

## 架构与目录（本阶段固定）

```
app/
  ccfa_core/          # 零 Qt 依赖：项目模型 / 设置 / 密钥 / 检查编排
    projects.py
    settings.py
    secrets.py
    checks.py
  ccfa_gui/           # PySide6 桌面壳（薄层）
    main.py
    window.py
  tests/              # app 自己的 unittest（core + gui）
  requirements.txt    # PySide6 / keyring（钉死版本）
  README.md           # 开发与运行说明
```

- `tools/` 的确定性核心保持**零新增依赖**（819 tests 基线不动）；app 用独立 venv `app/.venv`（gitignore）。
- 运行 app 测试：`PYTHONPATH=tools` + `app/.venv/Scripts/python.exe -m unittest discover -s app/tests -t app`。
- 打包（PyInstaller/Inno Setup）属 P3，本阶段只做 PyInstaller 可行性记录，不强制交付安装包。

## Global Constraints

- 退出码/JSON 契约沿用九条跨工具规则；app 不复制工具实现，只 import `ccfa.*` 或调用既有入口。
- 密钥红线：**任何项目文件与 settings.json 不得出现 key 明文**；keyring 不可用时明确报错，**不得降级明文**。
- 一切写盘原子；读配置时重校验；一条坏项目不打断项目列表（只标红该条）。
- UTF-8 无 BOM；ASCII 标识符；中文只在面向用户消息与文档。
- GUI 验收必须**真实渲染**（offscreen + 非空像素检查），不能只断言"能 import"。

### Rulings（写入账本 E57–E59）

- **E57 密钥只进凭据管理器**：`settings.json` 只存 `key_name` 引用；`KeyringSecretStore` 是唯一实现；`NoKeyringError` 上抛为 `SecretStoreUnavailable`，UI 如实展示。
- **E58 核心零 Qt、壳可替换**：`ccfa_core` 不 import PySide6；GUI 只做编排与展示；将来换 Electron 壳时核心不动。
- **E59 GUI 验收用真实渲染**：offscreen 实例化 + `grab()` 出 PNG + 非空像素阈值 + 关键控件可见性/尺寸断言；截图字节写进任务报告。

---

### Task 1: `ccfa_core`（项目模型 / 设置 / 密钥 / 检查编排）

**Files:** Create `app/ccfa_core/{__init__,projects,settings,secrets,checks}.py`、`app/tests/{__init__,test_projects,test_settings,test_secrets,test_checks}.py`、`app/requirements.txt`、`app/README.md`；Modify `.gitignore`（`app/.venv/`）

**Interfaces**
- `projects.find_projects(repo_root) -> list[ProjectRef]`（扫 `papers/*/ccfa.yaml`；`papers/` 不存在 → `[]`；单条 yaml 坏 → 该项带 `error` 字段，不抛断整列）
- `projects.load_project(path) -> ProjectState`（字段：slug/dir/mode/current_stage/gate/deadline/updated_at；用 `ccfa.stages` 校验 mode/stage；非法 → `ProjectError`）
- `settings.ProviderSettings`（dataclass：name/base_url/model/key_name/timeout_s）、`load_settings`/`save_settings`（schema version 1、原子写、读时重校验、UTF-8 无 BOM、**不存 key**）
- `secrets.SecretStore`（协议：get/set/delete）、`KeyringSecretStore`（keyring 实现；`NoKeyringError → SecretStoreUnavailable`）、测试用 `InMemorySecretStore`（放 tests 内，不进生产包）
- `checks.run_validate(project) -> CheckResult`、`checks.run_milestones_due(project, today=None) -> CheckResult`（直接 import `ccfa.validate.validate_yaml` / `ccfa.milestones.due_report`，不复制逻辑）

**判定表**

| 条件 | 结果 |
| --- | --- |
| `papers/` 不存在 / 空 | `[]`，不报错 |
| 单个项目 yaml 坏 | 该项 `error` 非空，其余项目照常 |
| mode/stage 非法 | `ProjectError`（消息含路径与原因） |
| settings.json 缺 / 空 | 返回默认（无 provider），不抛 |
| settings.json 版本/字段非法 | `ValueError` → UI 显示错误 |
| 保存 settings | 文件字节中**不含**任何 key 内容（用假 key 断言） |
| keyring 无后端 | `SecretStoreUnavailable`（不做明文回退） |
| `run_validate` | 返回问题列表；工具异常 → `CheckError` 带原因 |

- [ ] Step 1: 测试先行（约 20 条：项目发现/坏项隔离/mode 校验/设置往返与不落 key/版本非法/keyring 注入/validate 与 due 结构化结果）
- [ ] Step 2: 建 `app/.venv`（Python 3.12），安装并**钉死** `PySide6`、`keyring` 到 `app/requirements.txt`；`app/README.md` 写开发/运行/测试命令
- [ ] Step 3: 实现 → 全绿；判别力实测：把 `save_settings` 改成允许写 key 字段（不落 key 用例必须失败）；把坏项目隔离去掉（隔离用例必须失败）
- [ ] Step 4: 跑 `tools/` 全量确认 819 不动；commit `feat: add the workbench core for projects, settings and checks`

### Task 2: `ccfa_gui`（PySide6 壳：项目列表 + 阶段看板 + 设置 + 检查）

**Files:** Create `app/ccfa_gui/{__init__,main,window,settings_dialog}.py`、`app/tests/test_gui_smoke.py`

**Interfaces / 界面（P0 最小）**
- 主窗口：左侧项目列表（`find_projects`；坏项标红并显示 error）；中间阶段面板（`current/gate/deadline` + `milestones due` 结果表格）；按钮：刷新、运行 validate、运行 milestones、设置；状态栏显示"凭据后端可用/不可用"。
- 设置对话框：provider name/base_url/model/timeout + API key 输入（保存时 set 进 keyring，settings.json 只落 name）；显示当前 key 是否已存在（不显示值）。
- 启动方式：`app/.venv/Scripts/python.exe -m ccfa_gui.main`（PYTHONPATH=tools）。

**验收与测试（约 12 条）**
- offscreen（`QT_QPA_PLATFORM=offscreen`）实例化主窗口；注入假项目目录与 `InMemorySecretStore`。
- `window.grab()` → QImage：断言宽高 > 阈值、非背景像素占比 > 阈值、关键控件（项目列表/阶段标签/按钮）可见且尺寸 > 0；PNG 落到临时目录并把字节数写进报告。
- 交互：点"运行 validate"对合法项目不退崩溃、表格出现行；坏项目在列表中显示错误文本；设置对话框保存后 keyring 收到 set、settings.json 不含 key 明文。
- 判别力实测：把渲染前布局清空（不 addWidget）→ 非空像素断言必须失败（贴原文）。
- commit `feat: add the PySide6 workbench shell`

### Task 3: 收口（e2e + 文档 + 终审）

**Files:** Create `app/tests/test_workbench_e2e.py`；Modify `README.md`（"论文工作台（P0）"小节：定位、启动命令、P0 边界）

- e2e（真实文件树 + 真实 offscreen 渲染）：派生 NeurIPS 项目 → 主窗口看到该项目与 stage → 运行 validate/milestones → 设置页保存 provider → 断言 settings 无 key、keyring 有值 → 截图非空。
- [ ] 判别力：把项目加载改成"跳过无 ccfa.yaml"→ e2e 必须失败。
- [ ] commit `test: add the workbench P0 end-to-end smoke`
- [ ] 终审（base 以实际 HEAD 为准，新评审者）；账本记录 E57–E59 与结项。

## 完成定义（DoD）

- `app` 侧新测试 ≥ 40 且全绿；`tools` 侧 819 基线不动。
- 密钥红线有**字节级**测试（settings.json 不含 key）；keyring 不可用路径有测试。
- GUI 有一张真实 offscreen 截图（非空像素断言通过，PNG 字节数入报告）。
- 代码目录满足 E58（`ccfa_core` 不 import PySide6，可用一条测试断言 import 图）。
- 账本（`docs/sdd/...`）写 E57–E59 与各任务评审结论。
