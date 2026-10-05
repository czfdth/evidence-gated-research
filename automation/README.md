# 自动化接线

本目录提供四类自动化 prompt 模板。它们面向 Codex automations 的**本地项目**模式：
自动化运行在仓库根目录，读取脚本输出并向用户报告事实；仓库本身不创建或注册任何云端任务。

**实际创建 automations 需用户确认**。在用户明确确认前，只保留模板和手动命令，
不把任何任务挂入 scheduler。

## 四类模板

| 模板 | 用途 | 主要输出字段 |
| --- | --- | --- |
| `weekly-watch.md` | 每周文献增量监控 | `baseline`, `new`, `seen_total`, `skipped` |
| `deadline-check.md` | 完整 8 节点倒排检查 | `mode`, `deadline`, `due`, `missing_gates`, `problems`, `advisory`, `advisories` |
| `stage-advance.md` | 手动读取状态并给出下一阶段建议 | `current`, `gate`, `updated_at` |
| `experiment-queue.md` | 顺序运行实验队列 | `runs[].name`, `runs[].attempts`, `runs[].status`, `stopped` |

## 静默策略

所有模板统一遵循：

> 没有实质变化就不通知。没有新增文献、没有到期 checkpoint、没有状态变化、
> 队列没有失败或停止项时，不发送任何“我检查过了”的消息。

只有出现新增条目、到期/过期、gate 缺口、队列失败、超时、预算停止或重试耗尽时，
才向用户发送含具体字段值的简短报告。

## 安全边界

- 自动化只做信息收集与提醒。
- 不得修改论文正文与 `ccfa.yaml` 的结论字段。
- 不得自动推进 `stage.current` 或修改 gate 状态；只报告建议动作，修改需用户明确授权。
- 不访问网络的任务必须在测试中使用注入 fetcher/runner；真实运行遵循各脚本约束。

## 挂载方式

1. 用户提供论文项目根目录 `<paper-root>`。
2. 用户确认要创建的自动化、频率和相关 URL/队列文件；文献监控的源写在
   `automation/watch-sources.json`（`feeds` 为空时该任务保持安静）。
3. 在 Codex automations 中选择本地项目，把对应模板作为 prompt。
4. 在 prompt 中替换 `<repo-root>` 与 `<paper-root>`。
5. 先用手动命令验证输出，再启用定时触发。

`stage-advance.md` 是手动模板，不挂定时任务。

模板中的命令统一设置 `PYTHONPATH` 并调用 `tools/.venv/Scripts/python.exe`，
避免依赖系统 Python 环境。
