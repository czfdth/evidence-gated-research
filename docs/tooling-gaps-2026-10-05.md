# 工具与插件缺口盘点（第二轮复检）

日期：2026-10-05（更新版）
方法：读取 `~/.codex/config.toml`、skills 目录、PATH、`ccfa.verifiers`、`scripts/doctor.ps1`、GitHub Actions 与 secret 配置

## 一句话结论

上一版列出的缺口**几乎全部关闭**。`scripts/doctor.ps1` 现在报告 **0 problems, 0 advisories**，工具链已经完整。

同时要纠正上一版的三处误判：Ghostscript 在 Windows 上叫 `gswin64c` 而非 `gs`；Zotero 服务实际可用（curl 返回 HTTP 200，是 PowerShell 的探测方式有问题）；Ollama 的 OpenAI 兼容端点在 `data[].id` 而不是 `models[].slug`，所以第二个 provider 其实早已可用。

## 一、已关闭的缺口

| 上一版缺口 | 当前状态 | 证据 |
| --- | --- | --- |
| P0-1 缺第二个 model family provider | ✅ 已关闭 | `[model_providers.local-qwen]` → `127.0.0.1:11434`；Ollama 正在运行 |
| P0-2 主仓库缺 `PAPER_REPOSITORY_TOKEN` | ✅ 已关闭 | 主仓库与论文仓库两个 secret 均已配置 |
| P0-3 Zotero Desktop 未运行 | ✅ 已关闭 | zotero 进程在运行，23119 监听中，`curl` 返回 HTTP 200 |
| P1-4 分支保护 | ⚠️ 计划限制 | 免费私有仓库不支持，非配置遗漏 |
| P1-5 证明助手全缺 | ✅ 已关闭 | 9/9 引擎可用 |
| P1-6 外部归档与身份 | 🟡 部分 | `archive_client.py` 已写（未提交）；仍无 ORCID 集成 |
| P2-7 PDF 与文档处理 | ✅ 已关闭 | `gswin64c`、`qpdf`、`mutool`、`soffice` 全部就位 |
| P2-8 排版与可复现报告 | ✅ 已关闭 | `typst`、`quarto` 已安装 |
| P2-9 数据版本控制 | ✅ 已关闭 | `dvc` 已安装（原判断为缺） |
| P2-10 远程算力与 notebook | 🟡 部分 | `jupyter`、`micromamba` 已装；仍无远程 GPU/HPC 调度 |

## 二、当前工具链实际清单

### 核心命令

```text
git, gh, docker(daemon 可达), codex, nvidia-smi
pdflatex, xelatex, bibtex, latexmk, pandoc
Rscript, perl, tesseract, inkscape, 7z, magick, ffmpeg, pdfcrop, cmake
uv, uvx, node, npx, git-lfs
```

### 文档与排版

```text
gswin64c  C:\Program Files\gs\gs10.08.0\bin\gswin64c.EXE      Ghostscript
qpdf      F:\codex-tools\bin\qpdf.CMD
mutool    F:\codex-tools\bin\mutool.CMD
soffice   F:\codex-tools\bin\soffice.CMD                       LibreOffice
typst     F:\codex-tools\bin\typst.CMD
quarto    C:\Program Files\Quarto\bin\quarto.EXE
```

### 环境与数据

```text
dvc, micromamba, jupyter
tools/.venv, app/.venv
```

### 形式化引擎：9/9 可用

```text
z3        SMT                   module z3 5.1.0
cvc5      SMT                   module cvc5 1.3.1
lean      proof-assistant       Lean 4.34.1
coq       proof-assistant       Rocq 9.0 (coqc)
isabelle  proof-assistant       Isabelle2025-2
agda      proof-assistant       Agda 2.6.3 (WSL)
why3      verification-platform Why3 1.6.0 (WSL)
sage      CAS                   10.9 (WSL)
julia     language              Julia 1.13.1
```

### 服务

```text
provider  custom      http://127.0.0.1:15721/v1   deepseek-v4-flash  functional
provider  local-qwen  http://127.0.0.1:11434/v1   qwen3:30b          functional
zotero    http://127.0.0.1:23119                   HTTP 200           functional
docker    daemon                                   可达               functional
```

Ollama 可用模型：`qwen3:30b`、`qwen3.8:27b-q4_K_M`、`bge-m3:latest`（嵌入模型）。

### MCP 与插件

```text
MCP:     arxiv, semantic_scholar, zotero, academic_search,
         paper_search, overleaf_olcli, github, node_repl
Plugins: documents, pdf, spreadsheets, presentations, template-creator,
         browser, chrome, computer-use, unified-computer-use, visualize,
         latex, deep-research, github(@openai-api-curated), github(@zhongjingyun),
         consensus, code-review, superpowers, codex-security, zotero,
         sentry, notion, linear, figma, canva, remotion, boltz-api-cli,
         api-blackbox-tester
Skills:  ~/.codex/skills 66 个，~/.agents/skills 238 个
```

## 三、真正剩余的缺口（很少）

### 1. 远程 GPU / HPC 调度（唯一有实质影响的）

你有本机 GPU + Docker + GPU 秒预算，但没有远程调度接入。`tools/ccfa/compute.py` 与 `scripts/compute.ps1` 已在写（未提交），方向正确。这对 `experiment-loop` 的 pilot 与内层循环是最后一块能力短板。

### 2. CUDA 编译工具链

```text
MISS nvcc
```

只有需要自行编译 CUDA 扩展时才需要，日常跑 PyTorch 不必装。

### 3. `make`

```text
MISS make（Strawberry Perl 自带 gmake，多数场景够用）
```

### 4. Zenodo CLI 与 ORCID

```text
MISS zenodo CLI（Zenodo 有 REST API，archive_client.py 走 API 即可，未必需要 CLI）
无 ORCID 集成
```

### 5. 分支保护

```text
gh api .../branches/master/protection -> 403 Upgrade to GitHub Pro
```

免费私有仓库的能力限制，不是工具缺失。可选：升级 Pro、录用后公开、或继续用本地 gate。

## 四、由“工具太全”引出的一个副作用

全量测试当前 **1567 项，3 项失败**，全部在 `tools/tests/test_verifiers.py`：

```text
test_inventory_covers_every_registered_engine   all(not status.available)
test_status_lines_mark_wired_engines            all("MISSING" in line)
test_main_strict_exits_one                      problem_count == len(FORMAL_ENGINES)
```

原因不是工具缺失，而是**工具太完整**：这些测试假设宿主机“一个形式化引擎都没装”，但你现在 9/9 全装。这属于测试隔离缺陷（应注入受控探针），不是产品缺陷。

## 五、结论

**工具层面已经没有阻塞项。** `doctor` 0/0，两个 provider 可用，Zotero 可用，Docker 可用，9 个形式化引擎可用，排版与 PDF 工具齐全。

剩余只有三件小事：

1. 远程 GPU/HPC 调度（`compute.py` 正在写）；
2. `nvcc`（按需）；
3. `zenodo` CLI / ORCID（`archive_client.py` 走 REST 即可）。

以及一件非工具事项：修 `test_verifiers.py` 的环境依赖，让全量测试回到全绿。

**明确不需要再装的**：学术搜索类（arxiv / semantic_scholar / academic_search / paper_search / consensus 已足够）、CNKI 全套、LaTeX 全套、Obsidian/Zotero 桥接、文档/PDF/表格/演示插件、形式化引擎。你的瓶颈已经完全不在工具上。
