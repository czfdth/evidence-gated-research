# Stage Advance Prompt

读取论文状态、定位当前阶段，并给出下一步建议动作；不自动推进状态。

## 命令

```powershell
$ROOT = "<repo-root>"
$PAPER_ROOT = "<paper-root>"
$env:PYTHONPATH = "$ROOT/tools"
& "$ROOT/tools/.venv/Scripts/python.exe" "$ROOT/tools/ccfa/milestones.py" stage `
    --paper-root "$PAPER_ROOT"
```

## 读取字段

- `current`：当前阶段。
- `gate`：当前 gate。
- `updated_at`：最近更新时间。

## 通知规则

- 本模板仅手动触发运行，不挂定时任务。
- 阶段和 gate 没有变化时，没有实质变化就不通知。
- 只报告当前 `current`、`gate` 和建议动作，不自动改写状态。
- 状态字段只引用 `milestones stage` 输出，不凭印象推断完成情况。

## 安全边界

不得修改论文正文与 `ccfa.yaml` 的结论字段；推进 stage 需要用户明确授权。
