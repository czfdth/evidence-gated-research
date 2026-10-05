# Deadline Check Prompt

按投稿目标日检查 T-90/T-60/T-30/T-21/T-14/T-7/T-3/T-1 到期与 gate 缺口。

## 命令

```powershell
$ROOT = "<repo-root>"
$PAPER_ROOT = "<paper-root>"
$TODAY = "<YYYY-MM-DD>"
$env:PYTHONPATH = "$ROOT/tools"
& "$ROOT/tools/.venv/Scripts/python.exe" "$ROOT/tools/ccfa/milestones.py" due `
    --paper-root "$PAPER_ROOT" --today $TODAY
```

## 读取字段

- `mode`：`countdown` 或 `sequential`。
- `deadline`：投稿目标日或 null。
- `due`：命中的 checkpoint 或 overdue。
- `missing_gates`：目标前的 gate 缺口。
- `problems`：`deadline-invalid`, `stage-unknown`, `deadline-passed` 等。
- `advisory`：`sequential` 模式下的下一建议动作。
- `advisories`：跳过项列表，例如 `t30-scan-skipped`；有内容时应报告，不能当成通过。

## 通知规则

- `due=[]` 且 `problems=[]` 时，没有实质变化就不通知。
- `sequential` 模式下 `due=[]`，下一建议动作只在 advisory；没有具体日期。
- 命中 checkpoint 时只报告 checkpoint、日期与缺失 gate。
- `problems` 非空时原样报告 code，不自行解释成“已通过”。

## 安全边界

不得修改论文正文与 `ccfa.yaml` 的结论字段；不得代改 deadline 或 stage。
