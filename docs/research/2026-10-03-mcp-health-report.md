# MCP 层体检报告

日期：2026-10-03
范围：`<home>\.codex\config.toml` 中配置的全部 7 个 MCP server
方法：逐个以真实 MCP 握手探测（`initialize` → `notifications/initialized` → `tools/list`），不依赖 Codex 客户端的加载结果

## 结论摘要

配置的 7 个 server 里，**4 个存在缺陷或阻塞**，其中 3 个从未连上过。三个已修复，一个受网络问题阻塞。

| Server | 探测前 | 探测后 | 工具数 |
| --- | --- | --- | --- |
| `paper_search` | 正常 | 正常 | 8 |
| `arxiv` | 正常 | 正常 | 3（部分：`search_papers`/`download_paper` 未暴露） |
| `overleaf_olcli` | 正常 | 正常 | 6 |
| `node_repl` | 正常（基础设施） | 正常 | — |
| `zotero` | **未连接** | **已修复** | 41 |
| `semantic_scholar` | **未连接** | 配置本就正确，已验证可用 | 16 |
| `academic_search` | **未连接** | 已修路径，仍被网络阻塞 | — |

## 逐个诊断

### zotero — 配置缺子命令（已修）

`zotero-mcp.exe` 是多命令 CLI（`serve` / `setup` / `update-db` / `install-skill` 等）。原配置只给了可执行文件、没有 `args`，进程启动后打印用法然后退出，因此从未连上。

修复：`args = ["serve"]`。`serve` 默认 `--transport stdio`。

验证：MCP 握手成功，`serverInfo = {'name': 'Zotero', 'version': '0.13.1'}`，`tools/list` 返回 **41 个工具**，覆盖条目搜索、集合浏览、批注读写、PDF 全文与大纲、导出参考文献等。

### semantic_scholar — 配置正确，先前未连上是启动慢

原配置无误（`uvx semantic-scholar-fastmcp`）。单独启动可正常完成握手，`serverInfo = {'name': 'Semantic Scholar Server', 'version': '2.14.7'}`，`tools/list` 返回 **16 个工具**。

但它启动时需要加载依赖并打印横幅，首次连接可能超过客户端启动窗口。探测时若把三帧请求一次性写入并立即关闭 stdin，会因异步竞争而收不到 `tools/list` 响应——这是**探测方法**的假阴性，不是 server 缺陷。放慢握手节奏后正常。

结论：无需改配置；若 Codex 侧仍看不到工具，重启客户端让其重新连接。

### academic_search — 路径错误（已修）＋ TLS 证书阻塞（未解）

**缺陷一，路径错误，已修。** 原配置指向 `server/server.py`，实测该路径不存在；仓库实际结构是根目录下的 `server.py`。改为 `args = [..., "server.py"]` 后进程不再立即退出。

**缺陷二，TLS 证书校验失败，未解。**

该项目的 `.python-version` 钉死 `3.10`，而本机 uv 尚未安装该解释器，于是每次启动都要下载 20.9 MiB。下载失败：

```
WARN Failed to fetch cpython-3.10.21-windows-x86_64-none from https://releases.astral.sh/...
error: Failed to install cpython-3.10.21-windows-x86_64-none
  cause: invalid peer certificate: UnknownIssuer
```

本机存在 TLS 拦截，而 uv 使用的 rustls 只信任自带根证书，不认拦截方注入的 CA。PowerShell 的 `Invoke-RestMethod` 走系统证书库，所以同一台机器上 GitHub API 调用一直正常——这解释了为什么问题只出现在 uv 一侧。

已验证的修复方向：设置 `UV_SYSTEM_CERTS=1` 让 uv 改用系统证书库后，下载立即开始（进度到 20.9 MiB 的拉取阶段）。`UV_NATIVE_TLS=1` 是同一开关的旧名，已弃用。

**当前阻塞**：改用系统证书库后连接建立，但 20.9 MiB 的下载在 10 分钟内未完成，疑为中间代理限速。已终止停滞进程以免其长期占用 uv 的 Python 安装锁。

### 顺带发现的资源泄漏

uv 的 Python 安装锁 `<home>\AppData\Roaming\uv\python\.lock` 会被卡住的下载进程长期占用。探测过程中一个被中断的 `uv run` 留下了孤儿进程 `48192`，导致后续所有 `uv python install` 报 `Timeout (300s) when waiting for lock`。已清除。

教训：对 uv 发起的进程做强制终止时，要连同其子进程一起处理，否则锁不会被释放。

## 已实施的配置变更

文件：`<home>\.codex\config.toml`
备份：`<home>\.codex\config.toml.bak-20261003-140226`

| 位置 | 变更 |
| --- | --- |
| `[mcp_servers.zotero]` | 新增 `args = ["serve"]` |
| `[mcp_servers.academic_search]` | 参数末项由 `server/server.py` 改为 `server.py` |
| `[mcp_servers.arxiv.env]` | 新增，`UV_SYSTEM_CERTS = "1"` |
| `[mcp_servers.semantic_scholar.env]` | 新增，`UV_SYSTEM_CERTS = "1"` |
| `[mcp_servers.academic_search.env]` | 新增，`UV_SYSTEM_CERTS = "1"` |

已验证该 TOML 可被 `tomllib` 正常解析，7 个 server 的参数与 env 均符合预期。

**注意：配置变更需要重启 Codex 才会生效。**

## 尚未解决

1. `academic_search` 仍无法启动，卡在 Python 3.10 的下载。可选出路有二：
   - 在网络条件较好的时段重跑 `uv python install 3.10`（已确认证书修复后能开始下载，只是慢）；
   - 把该项目 `.python-version` 改为本机已有的 `3.13.14`。其 `pyproject.toml` 只要求 `>=3.10`，3.13 满足；但这会偏离上游钉死的版本，属对第三方仓库的本地改动。
2. `arxiv` server 只暴露 3 个工具（`semantic_search` / `citation_graph` / `reindex`）。其工具描述里提到的 `search_papers`、`download_paper` 均未出现在 `tools/list` 中，说明该 server 的功能被裁剪或其依赖（标注为 pro 的 extras）未安装。本地语义检索因此无可用索引来源。
3. `paper_search` 的 `search_papers` 支持 `scihub` 平台。这与项目既定的引用核验原则相冲突，实际使用时应避开该选项。
4. `overleaf_olcli` 暴露了 `delete_entity` 与 `rename_entity` 两个**会改动远端 Overleaf 工程**的工具，且没有二次确认机制。自动化流程里应显式排除它们。

## 方法学限制

- 探测只覆盖 MCP 握手与 `tools/list`，未逐个调用工具验证其实际行为。
- `academic_search` 的修复未能端到端验证，因为它始终没启动起来。
- 未检查 `npx -y paper-search-mcp-nodejs` 与 `olcli-mcp` 的版本锁定情况；`npx -y` 每次可能拉到不同版本。
