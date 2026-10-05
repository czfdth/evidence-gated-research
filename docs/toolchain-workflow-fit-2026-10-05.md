# 工具链与科研工作流适配核查

日期：2026-10-05
核查对象：`docs/tooling-install-2026-10-05.md` 里安装的 9 类工具 + 安装器本身
核查方法：对 `tools/ccfa`、`tools/newpaper`、`tools/build`、`app`、`scripts` 做带词边界的引用扫描，
并对每个候选消费点逐个读取实现确认

## 一、结论（先给判定）

**工具都装好了，也都真的能跑；但工作流的判定逻辑一次都没有调用它们。**

除 `doctor.py` 之外，`qpdf`、`mutool`、`gswin64c`、`soffice`、`typst`、`quarto`、`dvc`、
`jupyter`、`micromamba` 在仓库代码里**零引用**。所以当前状态准确说法是：

> 这些是「随时可用的能力」，不是「已接入流水线的能力」。

这不等于白装。下面按「有没有真实消费点」分三类，逐个给出接入位置。

## 二、适配矩阵

| 工具 | 版本 | 来源 | 工作流引用 | 真实消费点 | 判定 |
| --- | --- | --- | --- | --- | --- |
| lessmsi | 2.12.9 | winget | 安装器内部 | 解 MSI（LibreOffice 能落地就靠它） | ✅ 已接入 |
| qpdf | 12.4.2 | winget 系统安装 | 仅 `doctor` | `final_check` 的 PDF 结构校验 | 🟡 未接线 |
| mutool | 1.28.0 | conda-forge 精简 | 仅 `doctor` | PDF 解析 / 修复 / 渲染 | 🟡 未接线 |
| Ghostscript | 10.08.0 | 系统原有 | 仅 `doctor` | PDF 压缩、EPS 转换（投稿系统要求） | 🟡 未接线 |
| LibreOffice | 25.8.7.3 | lessmsi 解包 | 仅 `doctor` | `post_submission` / `talk_pipeline` 的 docx/pptx 交付转换 | 🟡 未接线 |
| DVC | 3.67.1 | uv tool | 仅 `doctor` | 大数据集版本化 | 🟡 条件未到 |
| micromamba | 2.4.0 | 便携 | 仅 `doctor` | `queue` 的运行环境后端 | 🟡 未接线 |
| JupyterLab | 4.6.4 | uv tool | 仅 `doctor` | notebook 式 pilot 执行 | 🟡 未接线 |
| Typst | 0.13.1 | 便携 | 仅 `doctor` | 由 `typst-paper` skill 消费，仓库侧无入口 | ⚪ skill 级已消费 |
| Quarto | 1.10.18 | winget 系统安装 | 仅 `doctor` | 无：`readiness`/`dashboard` 直接产出 Markdown | ⚪ 无消费点 |

### 为什么 `queue.py` 不算 micromamba 的消费点

早期扫描曾把 `queue.py` 列为引用 `conda`，那是 "GPU-**second**" 里的子串造成的假阳性。
逐行确认后，`queue.py` 的 `SANDBOX_MODES` 只有 `("none", "policy", "docker")`，
没有任何环境创建/依赖安装步骤，所以 micromamba 目前对队列没有作用。

## 三、本轮实际闭合的一条链路

核查中唯一「台账字段已经在、执行能力刚装好、但两者没连」且改动零风险的地方是 pilot 预算：

- `data/experiment-loop.yaml` 里已经声明 `pilot_budget_minutes`；
- `tools/ccfa/compute.py` 能按墙钟预算执行并记录 `gpu_minutes`；
- 但 `experiment_loop next` 原先只输出一句自然语言待办，预算没有任何东西去约束它。

现在 `next_actions()` 会为 `pilot-planned` 的 idea 生成可直接执行的下一条命令：

```text
scripts/compute.ps1 run --paper-root <paper-root> --minutes 45 --gpus 1 -- <命令>
```

这条改动落在 `next_actions()` 的**建议输出**里，不碰任何 gate 判定，因此不会改变
`ready`/`pass` 语义。`pilot-running` 的条目不生成命令（那时该做的是记录结果，不是再跑）。

其余链路本轮**故意没有接**：它们都会改变 gate 行为或引入新的失败模式，应该在单独一轮里
带着测试一起改，而不是混在"清理 + 核查"里。

### 追加：文献库的语义召回（`library.py`）

上表把 `bge-m3` 归为「未接线」，这一条已经补上。`library` 现在同时具备两种排序：

- `library index --embed`：为每条记录的「标题 + 摘要 + 笔记」调用本地 Ollama
  (`bge-m3`, 1024 维) 生成向量，存进 `index.db` 的 `vectors` / `vector_index` 表；
- `library search --mode keyword|semantic|hybrid`：keyword 保持原来的 FTS5 短语精确匹配，
  semantic 走本地向量，hybrid 用倒数排名融合（RRF，`k=60`）合并两种排序。

设计上刻意做的三件事：

1. **不替换精确检索。** 关键词路径仍然带 `refs_sha256`/`notes_sha256` 新鲜度校验；
   语义只是扩大召回，因为语义相近的论文**不是同一篇论文**，引用链路不能让相似度冒充匹配。
2. **不混用分数尺度。** 余弦分数和 FTS5 分数不可比，所以融合只按排名，并且每条结果都回填
   `matched_by` / `keyword_rank` / `semantic_rank` / `rrf_score`，让人能看出它为什么被召回。
3. **不动 v1 schema 契约。** 向量放独立表，`meta` 仍是精确的 5 列，因此没建向量的索引
   依旧完全合法，关键词检索行为不变；embedding 服务不可用时，`index` 在打开临时库之前
   就失败，原索引原封不动。

## 四、建议的接线顺序（按性价比）

1. **`final_check` 加 PDF 结构检查**（约 20 行 + 测试）
   现状：`final_check` 只用 PyMuPDF 抽文本，PDF 的 xref/流编码坏了也能过。
   位置：`tools/ccfa/final_check.py` 的 `check()`，在 `extract_text` 之后。
   语义：qpdf 报 syntax/stream 错误 → problem；qpdf 缺失 → 按本仓库既有惯例给
   `check-skipped` advisory（`PyMuPDF 不可用时已这么处理`）。
2. **`artifact_store.put_artifact` 对大文件报警**（约 10 行）
   现状：`_sha256_file` / `put_artifact` 用 `read_bytes()` 整文件读入内存，
   写入 `ccfa-workfiles/artifact-store/blobs`。超过几百 MB 的数据集既爆内存又污染仓库。
   建议：超过阈值时给 advisory，指向 DVC，而不是静默照存。
3. **`post_submission` / `talk_pipeline` 接 LibreOffice**（中等）
   现状：两个模块只校验 slide/交付物**存在与契约**，不做格式转换。
   接入后才谈得上"交付格式"这条需求闭环。
4. **`queue` 增加 `sandbox=conda` 后端**（较大）
   用 micromamba + lockfile 建运行环境，才能真正复现 `repro_env` 声明的环境。

不建议接线：**Quarto**。现有报告链路是确定性 Markdown（`readiness`、`dashboard`），
引入 Quarto 会多一层渲染依赖却不增加判定能力。Typst 同理留在 skill 层，不要往
`newpaper` 里加平行模板体系。

## 五、本轮删掉的无关文件

### 仓库根目录（已备份后删除）

31 个 `.gitignore` 明确标注为「手工验证的临时捕获」的残留（`*-check.json`、
`*.err.txt`、`readiness-*.json`、`export-*.log` 等），共 32 KB。
备份：`F:\UsersData\repo-cleanup\2026-10-05\repo-root-captures.zip`。
`.gitignore` 的注释本身就写明「持久证据应放在 `reviews/` 或论文仓库的 `ccfa-workfiles/`」。

### 工具链冗余（F 盘）

| 删除项 | 释放 | 原因 |
| --- | --- | --- |
| `mupdf-env` | 1863 MB | `mutool.exe` 只需要 `Library\bin`（222 MB），其余是 Python/tk/cairo |
| `.cache`（安装包） | 517 MB | 工具已解包，归档可重新下载 |
| `quarto`（便携副本） | 444 MB | 系统已有 winget 安装的 1.10.18，且比便携版 1.8.25 新 |
| `qpdf`（便携副本） | 52 MB | 系统已有 winget 安装的 12.4.2，且比便携版 12.2.0 新 |
| `mamba-root` | 0 MB | 包缓存，已 `clean --all` |

工具链从 **4.4 GB 降到 1.79 GB**（libreoffice 1519 + mutool 222 + typst 37 + micromamba 11）。

### 安装器随之修正

- 新增 `archive="auto"`：优先使用系统安装（`C:\Program Files\qpdf*\bin`，用 glob 容忍版本号变化），
  缺失时才回退下载便携版；
- 新增「PATH 上已有等价工具则跳过并回收自己的 shim」逻辑，避免便携版遮蔽新版；
- 新增 `--force` 覆盖上述行为；
- 新增 `--build-mutool`：一键「建 conda 环境 → 只留 `Library\bin` → 删环境 → 清包缓存」，
  不会再装出 1.9 GB。

## 六、仍需注意

1. **Docker daemon 当前不可达**（`doctor --strict` 报 `doctor-daemon-down`），
   因此 `queue sandbox=docker` 此刻不可用。启动 Docker Desktop 即可恢复。
2. `doctor` 把 `lean`/`coq`/`isabelle`/`julia` 报成 MISSING，**是当前进程 PATH 过期**：
   这四个已装在持久化用户 PATH 上，新开终端或重启应用后即可识别。
3. LibreOffice 是 MSI 解包而非注册安装，`soffice` 启动时会打印
   `Could not find platform independent libraries <prefix>`（内嵌 Python 的提示）。
   实测不影响文档转换：HTML→PDF 产出 21 KB 合法 PDF。

## 七、验收命令

```powershell
scripts/doctor.ps1 --strict           # 9 类工具 installed；仅剩 Docker/形式化验证器相关项
scripts/install-toolchain.ps1 --list  # 构件与镜像清单
scripts/experiment-loop.ps1 next --paper-root <paper-root>   # pilot 带可执行命令
scripts/compute.ps1 probe             # 本机 GPU / Docker runtime
scripts/library.ps1 --dir library index --embed              # 建向量（需 Ollama 在跑）
scripts/library.ps1 --dir library search "查询" --mode hybrid # 关键词 + 语义融合检索
scripts/library.ps1 --dir library check                      # 含向量完整性审计，只读
```

测试：`tools/tests/test_fetch_toolchain.py`（17 项）、
`tools/tests/test_experiment_loop.py` 中的预算命令用例、
`tools/tests/test_library.py` 中的向量原语 / 语义模式 / 融合用例（共 65 项）。
