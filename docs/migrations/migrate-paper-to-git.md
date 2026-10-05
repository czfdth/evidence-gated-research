# 把既有论文迁移为独立 git 仓库

E61 要求每篇论文是**独立 git 仓库**（`papers/<slug>/.git`），并且所有论文级
git 操作都要校验 `rev-parse --show-toplevel` 等于论文目录本身，禁止回退到模板
父仓库。本文件记录迁移步骤；本计划的 Task 1a **只写文档**，对
`papers/example-paper` 的实际执行在 Task 4。

## 前置检查

1. 论文目录存在且内容已备份（迁移不改内容，只新增 `.git/`、`.gitignore`
   与 `.gitattributes`）。
2. `git --version` 可用；`git config user.name` 与 `git config user.email`
   至少在有全局配置时可用。缺失时下方提交命令用 `-c` 传一次性身份，
   **不写全局配置**。

```powershell
cd <仓库根>
git -C papers/<slug> rev-parse --show-toplevel
```

如果这条命令输出的是模板仓库根，说明论文还不是自己的仓库，可以按下面迁移；
如果它已经等于 `papers/<slug>`，说明迁移已完成，不要重复 `git init`。

## 迁移步骤

1. 写入论文级 `.gitignore`（内容是 `tools/newpaper/create.py` 中
   `PAPER_GITIGNORE` 的同一份规则）：

```gitignore
# TeX build products (regenerable)
*.aux
*.bbl
*.blg
*.fdb_latexmk
*.fls
*.log
*.out
*.synctex.gz
*.toc
*.xdv

# Python caches
__pycache__/
*.pyc

# Generated PDFs are build output; keep delivery and figure PDFs tracked.
*.pdf
!submission/**/*.pdf
!manuscript/figs/**/*.pdf
!figures/**/*.pdf
```

   同时写入论文级 `.gitattributes`，固定 fresh clone 的文本换行：

```gitattributes
* text=auto eol=lf
```

2. 初始化独立仓库并做首次提交：

```powershell
cd <仓库根>/papers/<slug>
git init -q
git add -A
git commit -q -m "chore: initialize paper repository"
```

   如果论文此前已经以 CRLF 工作树存在，先让 Git 按属性重规范化索引：

```powershell
git add --renormalize .
git status --porcelain
git commit -q -m "chore: normalize line endings"
```

   这里的重点是提交属性与索引一致；`cross_review._sha256` 已对文本
   CRLF/LF 做等价归一，二进制文件仍按原始字节哈希。

若 git 提示 `Please tell me who you are`，改用一次性身份（不会写入任何配置）：

```powershell
git -c user.name="Paper Workbench" -c user.email="paper@localhost" `
    commit -q -m "chore: initialize paper repository"
```

3. 校验论文目录就是自己的仓库根：

```powershell
$paper = (Resolve-Path .).Path
$toplevel = (git rev-parse --show-toplevel).Trim()
if ((Resolve-Path $toplevel).Path -ne $paper) { throw "toplevel 不是论文目录" }
git log --oneline -1
git status --porcelain
```

`git status --porcelain` 只应显示被有意保留的文件；构建产物与生成 PDF 不应出现。

4. 迁移后按 Task 1b/4 的步骤重跑一条 run-log 记录，确认记录的 `git_commit`
   指向论文仓库的提交，而不是父仓库或 `null`。

## 回退

迁移不修改论文内容，只新增 `.git/`、`.gitignore` 与 `.gitattributes`。在尚未打 tag、尚未推送的
前提下，删除这两个新增物即可回到迁移前状态：

```powershell
Remove-Item -LiteralPath <仓库根>/papers/<slug>/.git -Recurse -Force
Remove-Item -LiteralPath <仓库根>/papers/<slug>/.gitignore -Force
Remove-Item -LiteralPath <仓库根>/papers/<slug>/.gitattributes -Force
```

如果已经打过 `paper-v<N>` 标签或推送到远端，先确认没有需要保留的版本证据，
再删除标签/远端引用；不要用 `git reset --hard` 之类的命令处理论文内容。

## 注意

- 模板仓库继续忽略 `/papers/`，论文仓库不会把模板仓库的 `.git` 卷进来。
- `research_version.py` 对非独立仓库会拒绝执行（退 2），没有 `--allow-parent-repo`
  之类后门；如果迁移后命令仍报"论文目录不是独立 git 仓库"，先检查 3 的校验。
- 论文级 `.gitignore` 默认忽略构建生成的 PDF，但保留 `submission/**/*.pdf`
  交付件与 `manuscript/figs/**/*.pdf` 图资源。
