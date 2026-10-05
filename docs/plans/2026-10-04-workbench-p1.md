# workbench P1 实施计划（聊天面板 + 引擎适配器 + 工具桥）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让论文工作台"能聊天"：引擎适配器（OpenAI 兼容 HTTP + `codex exec`）+ 聊天面板；然后把六个核心工具接成 HTTP 引擎可调用的工具（带风险分级与写操作确认）。

**前提（E60）**：工作台定位**个人自用、不外分发**——`codex exec` 可作一等引擎；许可/签名不阻塞；密钥红线与写操作确认保留。

**Spec/账本：** `docs/plans/2026-10-04-workbench-p0.md`、`docs/sdd/2026-10-03-evidence-tracking-progress.md`（E57–E60）

## 架构（P1 固定）

```
app/ccfa_core/
  engines/
    base.py            # ChatMessage / EngineReply / Engine 协议（零 Qt）
    openai_compat.py   # httpx；chat completions；tool-calling；超时/取消；key 来自 SecretStore
    codex_exec.py      # subprocess；codex exec；超时/输出捕获；不落 key
  tools_bridge.py      # 六个工具的 specs + handlers + 风险分级（Task 3）
app/ccfa_gui/
  chat_panel.py        # 消息列表 / 输入 / 发送 / 停止 / 引擎选择（Task 2）
app/tests/
  test_engine_openai.py / test_engine_codex.py / test_chat_panel.py / test_tools_bridge.py
```

## Global Constraints

- `ccfa_core` 继续零 Qt（E58）；GUI 只编排。
- 密钥不落日志/文件；`provider.key_name` 是唯一引用；引擎从 `SecretStore` 取 key。
- 网络与子进程都要有**超时 + 可取消**；错误在 UI 以人读消息呈现，不吞、不伪造。
- HTTP 引擎要能被离线测试：用 `httpx.MockTransport`（或注入 transport）覆盖成功/非 2xx/超时/坏 JSON。
- `codex exec` 引擎用可注入 runner 测试；真实冒烟可选（个人自用环境已有 codex）。
- 写操作（state set-stage/rollback、memory add-*）必须是 `risk=write`，执行前在 GUI 弹确认；P1 **不暴露** `run-log run`（任意命令执行）给引擎。
- tools 侧 819 tests 保持不动；app 侧测试运行方式同 P0（`PYTHONPATH=tools` + `app/.venv` + offscreen）。

---

### Task 1: 引擎适配器（core，零 Qt）

**Files:** Create `app/ccfa_core/engines/{__init__,base,openai_compat,codex_exec}.py`、`app/tests/{test_engine_openai,test_engine_codex}.py`；Modify `app/requirements.txt`（加 `httpx` 并钉死）

**Interfaces**
- `base.ChatMessage(role, content)`、`base.EngineReply(text, tool_calls=[])`、`base.Engine` 协议（`name`、`send(messages, *, tools=None, timeout_s=None, cancel=None) -> EngineReply`）。
- `OpenAICompatibleEngine(base_url, model, secret_store, key_name, timeout_s=120, transport=None, client_factory=None)`：POST `{base_url}/chat/completions`；Authorization: Bearer <key>；解析 `choices[0].message`（text/tool_calls）；支持 tools 参数透传；非 2xx → `EngineError`（含状态码与响应片段 ≤500 字符）；坏 JSON → `EngineError`；**异常消息与日志不得含 key**。
- `CodexExecEngine(model="", timeout_s=600, runner=None)`：`codex exec [-m model] -C <cwd> -`，prompt 走 stdin；捕获 stdout 作为回复；非零退出 → `EngineError`（stderr 摘要 ≤500 字符）；runner 注入契约 `runner(argv, cwd, timeout_s, prompt) -> (code, stdout, stderr)`。

**判定表**

| 条件 | 结果 |
| --- | --- |
| HTTP 200 正常 JSON（文本） | `EngineReply` 文本正确 |
| HTTP 200 带 tool_calls | `EngineReply.tool_calls` 原样结构化 |
| 非 2xx | `EngineError` 含状态码，不含 key |
| 坏 JSON / 缺 choices | `EngineError` |
| 超时 | `EngineError("超时")` |
| codex 退 0 | 回复 = stdout（strip） |
| codex 非 0 | `EngineError` 含 stderr 摘要 |
| 未配置 key（keyring 无值） | `EngineError` 点名"未配置 API key"，不发请求 |

- [ ] 测试约 18 条（含"错误消息不含 key"的字节断言、超时、坏 JSON、tool_calls 透传、codex argv 精确断言、stdin prompt）。
- [ ] 判别力实测：把 `raise EngineError` 改成返回空回复（对应用例失败）；把 key 校验去掉（未配置用例失败）。
- [ ] commit `feat: add the workbench engine adapters`

### Task 2: 聊天面板（GUI）

**Files:** Create `app/ccfa_gui/chat_panel.py`；Modify `app/ccfa_gui/window.py`（挂载面板与引擎选择）；Create `app/tests/test_chat_panel.py`

**行为**
- 引擎下拉：`OpenAI 兼容`（用当前 provider 设置）与 `codex exec`（模型名可选）。
- 消息列表（用户/助手/错误三种样式）；输入框 + 发送（Ctrl+Enter）；运行中禁用发送并显示"停止"；停止触发取消（HTTP 引擎用 cancel 任务/超时；codex 引擎 kill 进程）。
- 引擎在**后台线程**执行；完成后经 Qt 信号回主线程更新 UI（禁止在主线程阻塞）。
- 未配置 provider 或 keyring 不可用时，发送前给出人读提示，不崩溃。

**测试（约 12 条，offscreen + FakeEngine）**
- 发送后消息列表出现用户消息与助手回复；FakeEngine 慢速返回时"停止"可取消且不崩。
- 错误路径：FakeEngine 抛 `EngineError` → 列表出现错误样式消息，输入不被吞。
- 引擎切换后使用对应引擎；未配置 provider 时提示且不调用引擎。
- 渲染：`grab()` 非空像素断言（同 E59 阈值），截图字节入报告。

- [ ] 判别力实测：把后台线程改回主线程直调（慢引擎会阻塞 UI，用"发送后 100ms 内界面仍可响应"断言失败）；贴原文。
- [ ] commit `feat: add the chat panel with engine switching`

### Task 3: 工具桥（HTTP 引擎可调用）

**Files:** Create `app/ccfa_core/tools_bridge.py`、`app/tests/test_tools_bridge.py`；Modify `app/ccfa_core/engines/openai_compat.py`（tool_calls 循环）、`app/ccfa_gui/chat_panel.py`（工具调用展示 + 写确认弹窗）

**六个工具（spec + handler，直接复用既有实现）**

| 工具 | 风险 | 备注 |
| --- | --- | --- |
| `milestones_stage` / `milestones_due` | read | 复用 `ccfa.milestones` |
| `library_search` | read | 复用 `ccfa.library.search_index` |
| `memory_search` / `memory_list` | read | 复用 `ccfa.memory` |
| `memory_add_idea` / `memory_add_dead_end` | write | 需 GUI 确认 |
| `state_set_stage` / `state_rollback` | write | 需 GUI 确认；沿用 `--confirm` 语义 |
| `trace_claims_check` | read | 复用 `ccfa.trace_claims` 路径（`--untagged` 模式） |

- 工具循环：模型返回 tool_calls → bridge 执行（write 先弹确认，拒绝则回 "user declined"）→ 结果作为 tool 消息回传 → 最多 N 轮（默认 6，可配）。
- 审计：每次调用记录 `{time, tool, args_digest, risk, outcome}` 到项目 `ccfa-workfiles/agent-tools.jsonl`（原子追加；**不记录 key**）。
- 参数校验：未知工具/坏参数 → 结构化错误回给模型；单次失败不中断会话。

- [ ] 测试约 16 条（每工具 happy path + 坏参数；write 确认拒绝；轮数上限；审计文件内容与不含 key；坏 JSONL 追加行为）。
- [ ] 判别力实测：把 write 工具改为自动执行（确认用例失败）；去掉轮数上限（上限用例失败）。
- [ ] commit `feat: expose the deterministic tools to the chat engine`

### Task 4: 收口（e2e + 文档 + 终审）

**Files:** Create `app/tests/test_chat_e2e.py`；Modify `README.md`（工作台 P1 小节）

- e2e（offscreen + FakeEngine）：派生项目 → 打开聊天 → 发送 → 回复显示 → 触发一次 `milestones_due` 工具调用 → 审计文件出现记录 → 改为 write 工具 → 确认弹窗（自动点"拒绝"）→ 模型收到 declined。
- [ ] 判别力：把审计写入去掉 → e2e 失败。
- [ ] README 如实标注 P1 边界（流式可选、`run-log run` 未暴露、安装包未做）。
- [ ] commit `test: add the chat end-to-end smoke`；终审（base `8747928` 之后的最初 P1 commit，新评审者）；账本更新 E60 与结项。

## 完成定义（DoD）

- app 侧测试 ≥ 100 且全绿；tools 819 不动。
- 引擎错误消息不含 key（字节断言）；未配置 key 不发请求。
- 聊天面板有真实 offscreen 截图证据；慢引擎不阻塞 UI 的判别力实测。
- 工具桥只暴露列出的六个工具（无 `run-log run`）；write 操作必须确认；审计日志不含 key。
- 账本记录 E60、各任务评审与挂账。
