# Weekly Watch Prompt

运行共享文献增量监控，只报告事实新增。

## 源配置

从 `automation/watch-sources.json` 读取：`feeds`（Atom feed URL 列表）与 `state`（状态文件相对路径）。
`feeds` 为空时保持安静，不通知。每个 URL 各跑一次下面的命令。

## 命令

```powershell
$ROOT = "<repo-root>"
$env:PYTHONPATH = "$ROOT/tools"
& "$ROOT/tools/.venv/Scripts/python.exe" "$ROOT/tools/ccfa/watch.py" scan `
    --state "$ROOT/<state>" `
    --url "<feeds 中的每个 URL>"
```

## 读取字段

- `baseline`：首次运行是否只建立基线。
- `new`：本轮新增条目；每条包含 `id`, `title`, `published`, `summary`。
- `seen_total`：状态中累计已见 ID 数。
- `skipped`：源中缺字段而跳过的条目数。

## 通知规则

- `baseline=true` 时只说明“已建立基线 N 条”，不逐条通知。
- `new=[]` 且 `skipped=0` 时，没有实质变化就不通知。
- `new` 非空时，只列出新增 ID、标题与 published，不做“实质重叠”判断。
- `skipped>0` 时，报告丢弃数量，不伪造缺失字段。

## 安全边界

不得修改论文正文与 `ccfa.yaml` 的结论字段；不得修改 watch state 以外的文件。
