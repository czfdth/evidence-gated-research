# 科研工作流 GitHub 参考核查报告

日期：2026-10-03
核查对象：设计文档 v1（2026-10-03-research-workflow-design.md）
方法：GitHub Search API 检索 + raw 抓取 README + 本机能力实测
额度说明：`gh` CLI 未安装，使用未认证 REST API。核心接口仅剩 13 次配额，因此发现阶段用 Search 接口，内容阶段用 `raw.githubusercontent.com`（不受 API 限流），未做 clone 与代码级深读。

## 1. 核查的参考项目

| 项目 | 规模 | 定位 | 对本设计的关键价值 |
| --- | --- | --- | --- |
| `wanshuiyin/Auto-claude-code-research-in-sleep` (ARIS) | 83 skills | 端到端自主科研框架 | 跨模型评审、研究记忆、claim 状态追踪、实验队列 |
| `SamuelSchmidgall/AgentLaboratory` | 5.9k star | 端到端自主研究工作流 | 阶段划分与 human-in-the-loop 定位 |
| `aipoch/open-science` | 5.4k star | 本地优先科研工作台 | `.science` 研究包、产物可追溯、headless CLI |
| `JihaoXin/paper-machine` | 新项目 | 论文防伪护栏 | 事故驱动的硬规则，全部有真实事故背书 |
| `15b4t/research-suite` | 新项目 | 通用科研技能集 + 工具 | 8 个确定性 CLI 工具，可直接借鉴设计 |
| `yunyancuo/keresearch` | 新项目 | 中文科研全周期技能 | 10 条实战硬规则，含数字审计与统计纪律 |
| `modelscope/Awesome-Vibe-Research` | 446 star | 科研生命周期综述 | 10 阶段流程地图，暴露我的阶段缺失 |
| `chrisliu298/awesome-research-agents` | 新项目 | 科研 Agent 综述 | 未解决问题清单，直接指向设计空白 |
| `huashu996/PPT-Framework-Skill` | 42 star | 学术框图转可编辑 PPT | 你引用的仓库，见第 2 节 |

## 2. 你引用的仓库核实结果

`huashu996/PPT-Framework-Skill` 确实存在：42 star，PowerShell 实现，2026-07-17 创建，7-27 最后更新，无 license、无仓库描述。

它的设计原则里有三条与本工作流完全一致，值得直接吸收：

1. **用户确认优先于生成器默认值**。且设了两道确认闸门：先确认参数，再确认 SVG 骨架，之后才产出正式文件。
2. **最终保存状态优先于生成器预览**。不接受"生成器说完成了"，只认最终文件本身通过检查。
3. **未通过最终检查不声称可交付**。这与文档 v1 第 9 节的硬约束一致，但 v1 只约束了自动化，没有约束"我声称完成"的口径。

需要澄清的一点：它依赖 Windows 桌面版 PowerPoint 与已注册的 MathType。本机 MathType 未安装，因此该仓库的 MathType 路径在本机不可用，Office 原生公式路径可用。

## 3. 本机能力重新核实（修正 v1 的一处错误）

v1 第 7 节写"GUI 软件的直接操作不做"。这个判断是错的。实测 COM 注册情况：

| 组件 | 状态 | 含义 |
| --- | --- | --- |
| `Word.Application` | 已注册 | 可脚本化驱动，能生成含原生公式、交叉引用、字段的真实 docx |
| `PowerPoint.Application` | 已注册 | 可脚本化驱动，能生成原生可编辑 pptx（即 PPT-Framework-Skill 的路径） |
| `Excel.Application` | 已注册 | 可脚本化驱动，含原生图表 |
| `KWPS.Application` | 已注册 | WPS 可用 |
| `EndNote.Application` | 未安装 | 只能走 RIS / BibTeX 文件交换 |
| `MathType.Application` | 未安装 | 公式走 Office 原生 OMML |
| `Origin.ApplicationSI` | 未安装 | 图表走 matplotlib / seaborn |

结论：第 4 层的真实上限比 v1 判断的高。Word / PowerPoint / Excel 可以做真正的原生文件操作，不是"只能生成后交付"。

## 4. 逐层差距

### 第 1 层 业务流程层

对照综述的 10 阶段地图，v1 缺三个阶段：

- **数据获取与制备**。综述单列此阶段，要求合规、可复现地抓取、解析、清洗并保留来源。v1 完全没有。
- **复现发布与归档**。v1 只有 `submission/checks.md`，没有 artifact 打包、model card、data card、复现清单。
- **传播与影响力追踪**。v1 在 `accepted` 结束。

另外 `keresearch` 的硬规则里有两条直接关系到 gate 判据：

- **证据链选题**：不许说"没人做过"，要列相邻论文各自的盲区，你的工作等于一个无人测量的合取。最接近的三篇 + 盲区说不清 = 没有空档。
- **阶段零微基准**：端到端实验前先给平台画像，后续所有主张锚定实测常数。

### 第 2 层 Agent 执行层

v1 把它当作纯粹的路由问题，这是不够的。ARIS 的核心机制是**执行者与评审者是不同模型**：执行用一个模型，评审用独立模型（默认 Codex MCP）。跨模型评审能抓到同模型自查抓不到的问题——ARIS 的更新日志里多次记录"评审发现并阻止了回归"。

v1 没有区分这两种角色，五类角色里的"审稿与质量控制"仍然由同一个模型扮演。

### 第 3 层 Skills 工具层

缺两类确定性工具。参考项目的共识是：机械的、可判定的工作不该靠提示词反复推导，应该写成脚本。

`research-suite` 的 8 个工具给出了现成清单：

| 工具 | 作用 | v1 是否有 |
| --- | --- | --- |
| citation-manager | Crossref/DataCite 元数据解析、DOI 去重、悬空引用检测 | 无 |
| traceable-claims | 行内标记数据来源，机械化核对数字 | 无 |
| research-version | 自动编号版本存储 + 真实 diff | 无 |
| provenance-manifest | 逐文件来源、校验和、校准历史 | 无 |
| experiment-tracker | 记录每次运行的配置、种子、commit、退出码、指标 | 无 |
| repro-package | 打包并在全新环境实际重跑验证 | 无 |
| latex-tools | LaTeX 结构校验 + 多引擎编译 | 部分（有编译，无结构校验） |
| friction-log | 持续记录工具缺陷与指令缺口，跨项目聚合 | 无 |

### 第 4 层 工具适配层

除第 3 节的 COM 修正外，还缺：Overleaf 双向 git 同步（ARIS 有 `/overleaf-sync`）。

### 第 5 层 知识资源层

v1 只有"共享文献库 + FTS5 全文检索"，缺**记忆**这个语义。ARIS 的研究记忆有四个特征：

1. 文献自动入库，形成 wiki。
2. 选题前先读记忆，选题后写回记忆。
3. 实验结果能回写 claim 状态。
4. **失败的想法变成反重复记忆**，防止反复走进同一个死胡同。

v1 的 `ccfa-workfiles/ideas/` 只是目录，没有承担这些语义。

## 5. 必须补的八项

按"不做会出事"的严重程度排序，前四项有真实事故背书。

1. **引用必须在检索时验证，写作阶段禁止新建 BibTeX 条目**。`paper-machine` 记录：让 Agent 补引用，它一次写了 9 条 BibTeX，其中 4 条不存在。草稿编译通过，参考文献看起来完整，没有任何机制报警。对 Agent 撰写论文的审计发现引用幻觉率超过 20%。
2. **一行内标记 + 机械化数字核对**。v1 的 gate 只有"能指到具体数值"这一句，没有机制。参考实现是行内标签 `\dataval{path:key}{value}`，脚本拿它去比对活的 JSON/CSV/YAML，而不是让模型模糊匹配。`keresearch` 用同类脚本抓到过 3,296 与 3,349 的笔误。
3. **终稿的确定性检查器**。`paper-machine` 的检查项：渲染后 PDF 里的 `?` 引用标记、图片字节与扩展名不符、没有任何图被引用、数字缺少证据标签、缺少声明。注意基线是"渲染后的 PDF"，不是编译日志。
4. **实验运行记录**。配置、种子、git commit、退出码、指标，逐次运行留档。缺了它，"这个数字哪来的"无法回答。
5. **数据来源文档**。逐文件记录来源、分类、校验和，并且这份文档本身可被机械核对，防止手写说明与真实数据漂移。
6. **复现包实际重跑**。不是检查包看起来完整，而是在干净环境真跑一遍。
7. **跨模型评审**。执行与评审分离，评审用另一个模型。
8. **成本与上下文预算**。`paper-machine` 实测：把上下文压到 24k 省钱的方案反而贵了 2.5 倍（11.4M tokens / $11.99 完成 对比 27.6M tokens / $29.75 耗光额度失败，后者单会话 463 次动作）。需要明确的工作上下文预算，不能盲目压缩。

## 6. v1 已经做对、不要改的

- 五层结构与主流实现（ARIS、open-science、PPT-Framework-Skill）一致。
- `ccfa.yaml` 承载 claim / experiment / review 状态，与 ARIS 的 claim 状态追踪同构。
- 会议与期刊两套尾部，前段共用。
- "不自动改正文与结论"的硬约束，与 PPT-Framework-Skill 的"用户确认优先"、`paper-machine` 的"prefer stopping to inventing"完全一致。这是正确的保守选择，不要放松。
- 先用 FTS5 再上向量库的分步策略。

## 7. 未处理与已知限制

- 未 clone 任何仓库做代码级深读，全部结论基于 README 与仓库元数据。
- GitHub 未认证配额只剩 13 次核心请求，未做多轮交叉检索，可能漏掉未用英文关键词命中的项目。
- EndNote / MathType / Origin 的替代方案未做实测，只做了安装状态探测。
- ARIS 的 83 个技能未逐个评估，只读了主 README 的架构部分。

## 8. 结论

v1 的骨架是对的，但缺一层"确定性"。

现在的问题不是流程画得不够全，而是流程里的关键判断全靠模型自述：引用是靠模型说"已核对"，数字是靠模型说"来自实验"，图是靠模型说"已检查"。参考项目的一致经验是——凡是能机械化判定的，都要写成脚本，让证据落在文件上而不是对话里。

修订方向：给每一层补确定性抓手，而不是给流程再加阶段。
