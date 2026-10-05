# Experiment Queue Prompt

顺序运行实验队列，报告成功、失败、停止条件与 run-log 留档。

## 命令

```powershell
$ROOT = "<repo-root>"
$PAPER_ROOT = "<paper-root>"
$env:PYTHONPATH = "$ROOT/tools"
& "$ROOT/tools/.venv/Scripts/python.exe" "$ROOT/tools/ccfa/queue.py" run `
    --queue "$PAPER_ROOT/experiments/queue.json" `
    --log-dir "$PAPER_ROOT/experiments/log"
```

## 读取字段

- `runs`：每个队列项的运行结果数组。
- `runs[].name`、`runs[].attempts`、`runs[].status`。
- `stopped`：null、`budget` 或 `retries`。
- run-log 中每次 attempt 的 `status`、`exit_code`。

## 通知规则

- 所有 run 都是 `complete` 且 `stopped=null` 时，没有实质变化就不通知。
- 失败、`skipped-budget`、`stopped=budget`、`stopped=retries` 或 timeout 必须通知。
- 超时按失败报告，不静默重试到成功；重试次数与停止原因照实引用。

## 安全边界

不得修改论文正文与 `ccfa.yaml` 的结论字段；不得修改队列文件或实验结论字段。
