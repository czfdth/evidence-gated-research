# 工具链补齐记录

日期：2026-10-05
对应缺口盘点：`docs/tooling-gaps-2026-10-05.md`
目标：把"交付格式 / 排版 / 数据版本 / 远程算力 / 归档"五类缺口从"缺"变成"可用或有明确接线"

装完之后的适配核查（哪些真的进了工作流、哪些只是可用）见
`docs/toolchain-workflow-fit-2026-10-05.md`。

## 一、结论

本轮把缺口清单里可本地落地的部分全部装齐，并把无法本地变出来的部分（远程 GPU/HPC）做成
**可配置、可探测、拒绝假装存在**的适配层。归档不再是"没有通道"，而是"有薄客户端 + 真实可达性证据"。

## 二、实际安装结果

安装根目录：`F:\codex-tools`
PATH 接线目录：`F:\codex-tools\bin`（已写入用户 PATH）
清单文件：`F:\codex-tools\toolchain-manifest.json`

根目录之所以在 F 盘：安装过程中发现 C 盘只剩 0.70 GB，`%LOCALAPPDATA%` 放不下
LibreOffice 的 1.5 GB 解包。迁移细节见 `docs/disk-relocation-2026-10-05.md`。
根目录由两个机制记录，迁移后老进程也能找到工具：

```text
CODEX_TOOLS_DIR=F:\codex-tools                      # 用户环境变量
%LOCALAPPDATA%\codex-tools-location  -> F:\codex-tools   # 指针文件
```

`tools/ccfa/toolchain.py` 的 `tools_dir()` 按「环境变量 → 指针文件 → 默认路径」解析。

| 缺口 | 工具 | 版本 | 位置 | 安装方式 |
| --- | --- | --- | --- | --- |
| 排版 | Typst | 0.13.1 | `...\bin\typst.cmd` | 便携 zip（gh-proxy 镜像） |
| 排版/报告 | Quarto | 1.10.18 | `C:\Program Files\Quarto\bin`（已在 PATH，无需 shim） | winget 系统安装优先，便携 zip 为回退 |
| PDF | qpdf | 12.4.2 | `C:\Program Files\qpdf 12.4.2\bin`（`...\bin\qpdf.cmd` 转发） | winget 系统安装优先，便携 zip 为回退 |
| PDF | mutool | 1.28.0 | `F:\codex-tools\mutool`（222 MB 运行时，非整个 conda 环境） | conda-forge `mupdf` via micromamba（TUNA 镜像） |
| PDF | Ghostscript | 10.08.0 | 系统已装 | 本来就在 `C:\Program Files\gs`，只是探针写的是 `gs` 而 Windows 是 `gswin64c` |
| 文档转换 | LibreOffice (`soffice`) | 25.8.7.3 | `...\bin\soffice.cmd` | lessmsi 解包 MSI（无需管理员与 Windows Installer 服务） |
| 数据版本 | DVC | 3.67.1 | `~\.local\bin\dvc.exe` | `uv tool install`（TUNA PyPI） |
| 环境管理 | micromamba（conda 兼容） | 2.4.0 | `...\bin\micromamba.cmd` | conda-forge 包解包（TUNA 镜像） |
| Notebook | JupyterLab | 4.6.4 | `~\.local\bin\jupyter.exe` | `uv tool install jupyter-core --with jupyterlab` |

一条命令重放全部安装：

```powershell
scripts/install-toolchain.ps1
```

只修复 PATH 接线（不重新下载）：

```powershell
scripts/install-toolchain.ps1 --shims-only
```

## 三、本机网络的分层事实（这是本轮最耗时的地方）

实测结论，全部会影响未来任何安装动作：

| 目标 | 状态 | 处置 |
| --- | --- | --- |
| `github.com` / `api.github.com` | 可达 | 正常用 |
| GitHub release 资产 CDN | 限速约 0.03 MB/s | 走 `https://gh-proxy.com/`（约 0.2 MB/s） |
| `pypi.org` | TLS 握手超时 | 走 `https://pypi.tuna.tsinghua.edu.cn/simple` |
| `zenodo.org` | DNS 被解析到 `0.0.0.0`/`::`（污染，不是 hosts 条目） | `archive_client.py` 用 DNS-over-HTTPS 解析后按 IP 直连，保留 SNI |
| `mirrors.tuna.tsinghua.edu.cn` LibreOffice | 浏览器 UA 被 403，本工具 UA 被限速 | 该构件显式不带 `User-Agent`（实测 2.4 MB/s） |
| `mirrors.tuna.tsinghua.edu.cn` anaconda | conda-forge 可用 | micromamba 通道写成完整 URL |
| `mupdf.com` | 连接超时 | 改用 conda-forge 的 `mupdf` 包拿 `mutool` |

`tools/install/fetch_toolchain.py` 把这些事实编码成"每个构件一组候选镜像 + 逐个回退"，
而不是散落在一次性命令里。

## 四、新接线

### 归档：`tools/ccfa/archive_client.py` + `scripts/archive.ps1`

- `probe`：报告 Zenodo / OSF / ORCID 的传输可达性（当前三者均 HTTP 200）。
- `zenodo-deposit`：草稿 → 上传 → 可选发布；**只有 API 返回 DOI 才记 `published`**，
  只上传成功记 `draft`，绝不把草稿当归档证据。
- `orcid-validate` / `orcid-fetch`：ISO 7064 MOD 11-2 校验位 + 公开记录可读性。
- `osf-create`：OSF 项目创建。
- 结果可写进 `data/archive.yaml`，作为 `artifact_badge.py` 的 DOI/归档证据来源。
- Token 只从 `ZENODO_TOKEN` / `OSF_TOKEN` 读，不写 stdout、日志或台账。

### 算力：`tools/ccfa/compute.py` + `scripts/compute.ps1`

- `probe`：本机 CPU/内存/GPU/Docker（含 NVIDIA runtime）与已配置远程后端。
- `plan`：给定 pilot 预算，判断本地/远程能否承接；都不行时退 1 并明说 `PILOT 受阻`。
- `run`：在墙钟预算内执行命令，超预算即 kill，并把 `wall_seconds` / `gpu_minutes`
  追加到 `experiments/log/compute-ledger.jsonl`。
- 远程 Slurm/PBS 通过 `data/compute.yaml` 配置；**没配置就报没配置**，不假装接上了。

本机实测：RTX 5060 Laptop 8 GB（compute capability 12.0）、24 逻辑核、31.4 GB 内存、
Docker 29.8.1 且 `nvidia` runtime 存在。本地 GPU 秒预算是可用的，
真正缺的是"大显存/多卡"这一类远程容量。

### 预检：`tools/ccfa/doctor.py`

新增 9 类可选依赖探针：Ghostscript、qpdf、mutool、soffice、Typst、Quarto、DVC、
conda（micromamba/conda/mamba 任一）、Jupyter。默认是 advisory，`--strict` 提升为 problem，
与"一次装齐"的验收口径一致。

`tools/ccfa/toolchain.py` 提供 `which()`：先查 PATH，再回退到 `%LOCALAPPDATA%\codex-tools\bin`。
这样即使进程在改 PATH 之前启动（Codex 应用本身、CI runner、长驻 shell），预检也不会误报缺失。

## 五、仍然成立的限制（不粉饰）

1. **远程 GPU/HPC 没有接**。只有适配层和配置契约；要真正用起来需要在 `data/compute.yaml`
   写入可达的 SSH 主机与调度器，并且该主机必须真的存在。本机没有可用的远程集群凭据。
2. **Zenodo 上传未做端到端真实发布**。缺 `ZENODO_TOKEN`，因此只验证了传输可达性与
   草稿/发布的状态机逻辑（有单测覆盖），没有产生真实 DOI。
3. **LibreOffice 是 lessmsi 解包，不是注册安装**。不会写 HKLM、不会注册文件关联，
   `soffice --headless --convert-to` 可用（已用 HTML→PDF 实测，产出 21 KB 真实 PDF），
   但不会出现在"程序和功能"里。`msiexec /a` 在本机因 Windows Installer 服务无法计价卷而报 1603。
4. **Typst 是 0.13.1**，比 winget 最新版（0.15.1）旧；升版本需先确认 `typst-paper` skill 的语法假设。
5. **DVC 未初始化到任何论文仓库**。工具可用，但"某个数据集纳入 DVC 管理"是论文仓库侧的动作。

## 六、回滚

```powershell
# 1. 删除便携工具目录（不涉及系统目录）
[System.IO.Directory]::Delete("F:\codex-tools", $true)
[System.IO.File]::Delete("$env:LOCALAPPDATA\codex-tools-location")

# 2. 从用户 PATH 移除接线目录
$bin = "F:\codex-tools\bin"
$p = [Environment]::GetEnvironmentVariable('Path','User')
[Environment]::SetEnvironmentVariable(
  'Path', (($p -split ';' | Where-Object { $_ -and $_ -ne $bin }) -join ';'), 'User')
[Environment]::SetEnvironmentVariable('CODEX_TOOLS_DIR', $null, 'User')

# 3. 卸载 uv 工具
uv tool uninstall dvc jupyter-core
```

mutool 用安装器一键重建（会自动只保留运行时、删掉 conda 环境、清包缓存，
结果约 222 MB 而不是 1.9 GB）：

```powershell
scripts/install-toolchain.ps1 --build-mutool
```

等价的手工步骤：

```powershell
$env:MAMBA_ROOT_PREFIX = "F:\codex-tools\mamba-root"
& "F:\codex-tools\micromamba\Library\bin\micromamba.exe" create -y `
    -p "F:\codex-tools\mupdf-env" `
    "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge::mupdf"
# 建完可清理包缓存（本机清掉约 3 GB）
& "F:\codex-tools\micromamba\Library\bin\micromamba.exe" clean --all -y
```

Ghostscript 是系统原有安装，本轮的改动只是让探针认 `gswin64c`；不要卸载它。

## 七、验收命令

```powershell
scripts/doctor.ps1 --strict        # 期望：上述 9 类依赖不再出现在问题里
scripts/compute.ps1 probe          # 期望：local.gpus 非空、docker_gpu=true
scripts/archive.ps1 probe          # 期望：zenodo/osf/orcid 三者 reachable=true
scripts/install-toolchain.ps1 --list
```

测试覆盖：`tools/tests/test_archive_client.py`、`tools/tests/test_compute.py`。
