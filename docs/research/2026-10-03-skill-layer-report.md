# Skill 层体检报告与路由表

日期：2026-10-03
输入：用户提供的《科研 skill 分类清单》（322 个 SKILL.md）
方法：YAML 真解析 + `skill-creator` 自带的官方校验器 `quick_validate.py` + 触发词碰撞统计

## 一、核对结果：分类清单的账是准的

独立重扫，与清单完全一致：**322 个 SKILL.md**，`~/.codex/skills` 63 个、`~/.agents/skills` 259 个；16 组重名，其中 2 组跨根（`literature-review`、`statistical-analysis`）；全部有 name 与 description。

## 二、一个必须纠正的方法学问题

我第一遍用正则扫描述长度，报出"32 个 skill 描述过短，最短的只有 1 个字符"。**这是假阳性**——那些文件用的是 YAML 块标量（`description: >` 或 `|-`），我的正则只抓到了指示符本身。

改用 YAML 真解析后：描述长度的中位数是 **302 字符**，最短 59 字符，没有任何一个缺失。原来那 32 条告警全部消失。

记下来是因为这正是本工作流反复要防的那类错误：朴素扫描给出的告警看起来像发现，实际是工具自身的局限。**告警不等于缺陷，先怀疑工具。**

## 三、官方校验器的结果与解读

`skill-creator` 自带 `quick_validate.py`，其允许的顶层字段写死为 `{name, description, license, allowed-tools, metadata}`。全量跑一遍：

| 结果 | 数量 |
| --- | --- |
| 通过 | 167 |
| 未允许的字段 | 153 |
| 描述超长 | 1 |
| 描述含尖括号 | 1 |

**153 条"未允许的字段"基本全是假阳性。** 涉及的字段是 `compatibility`(70)、`argument-hint`(44)、`version`(35)、`when_to_use`(8)、`tags`(7)、`author`(3)、`status`(1)、`inputs`(1) 等，全部来自 Claude Code 插件体系——那是另一套合法的 frontmatter 约定，Codex 只是忽略它们，不影响加载。

拿单一 harness 的校验器去检跨 harness 的集合，153 条噪声盖过 2 条真信号。这个校验器**不适合直接用作全量门禁**；它的价值在于逐个 skill 的针对性检查。

## 四、找到的真实缺陷（2 个）

### 4.1 `academic-paper-strategist` — frontmatter YAML 损坏（已修）

`~/.agents/skills/academic-paper-strategist/SKILL.md` 的 `description` 是未加引号的普通标量，值里含 `: `（"The skill guides through three phases: Platform Analysis…"）。YAML 规范中裸标量不得包含冒号加空格，解析器在此处报 `mapping values are not allowed here`，**整个 frontmatter 读不出来**——该 skill 处于不可用状态。

修复：改为折叠块标量 `>-`，内容逐字未动。

修复后该 skill 可正常解析，name 与 description 均能读出。

### 4.2 同一 skill — 描述超长（未修，待你决定）

修好 YAML 后校验器报出下一个约束：描述 **1049 字符**，上限 1024，超出 25。

若加载器真的按此限制截断，受损的是描述尾部的 "Output: optimized detailed outline ready for systematic writing (use with academic-paper-composer skill)." 一句，会削弱该 skill 与 `academic-paper-composer` 的衔接提示。

**未修的原因**：削掉 25 个字符必然改动原作者的文字与语义边界，这属于内容决定，不是机械修复。需要你确认是否允许我压缩其描述。

### 4.3 `academic-pipeline` — 描述含 `>`（判定为非缺陷）

校验器禁止描述中出现尖括号。该 skill 的描述里用的是箭头记法 `research -> write -> integrity check -> ...`，只有 `>` 没有 `<`，不构成模板语法风险。判定为校验器规则过宽，不改。

### 4.4 `nature-proposal-writer` 目录名与 name 不一致（非缺陷，但易混淆）

目录叫 `nature-proposal-writer`，而 `name: researchwrite`。功能正常，但按目录名找会找不到、按 name 找又对不上路径。建议择一统一，属整洁问题。

## 五、frontmatter 字段的实际情况

322 个 skill 一共用到 15 种顶层字段，说明这确实是一个跨来源混装的集合：

| 字段 | 出现次数 | 来源体系 |
| --- | --- | --- |
| `metadata` | 158 | 双方都用 |
| `license` | 96 | 双方都用 |
| `allowed-tools` | 70 | Claude Code |
| `compatibility` | 70 | Claude Code |
| `argument-hint` | 44 | Claude Code |
| `version` | 35 | Claude Code |
| `when_to_use` | 8 | 自定义 |
| `tags` / `author` / `status` / `inputs` / `dependencies` / `disable-model-invocation` | 各 1–7 | 自定义 |

注意 `disable-model-invocation`(3) 与 `user-invocable`/`user-invokable` 这类字段：**Codex 官方校验器不认它们**，因此它们的实际行为取决于各 harness，行为未经验证。若某个 skill 依赖这些字段来控制是否需要用户显式调用，在 Codex 下可能完全不生效。

## 六、Skill 路由表

分类清单指出 6 组功能重叠，但只给了选项、没给选择。以下是按任务定下主线，**目的不是删减，而是让每次选择变成查表而不是犹豫**。

选型依据来自本工作流既定的三条决定：主路径是 LaTeX + BibTeX；目标 venue 覆盖 CCF 会议与 CS 期刊；`nature-*` 体系用于非 CS 期刊。

### 6.1 两套流水线的分界（最重要的一条）

| 场景 | 走哪套 |
| --- | --- |
| 投 CCF 会议 / CS 期刊 | `ccf-*` 家族（17 个 skill，有 `ccfa.yaml` 状态机与 routing 表） |
| 投 Nature 系 / CNS 系 | `nature-*` 家族 |
| 两者都不是，或只是内部草稿 | 用 `nature-*` 的写作类，但不要串 CCFA 的状态机 |

**不要混用**：两套的标准与产出风格不同，混起来会让同一篇稿子前后不一致。清单里"按任务挑一个固定用"的建议，落到实处就是上面这张表。

### 6.2 逐任务主线

| 任务 | 用这个 | 不用/少用 | 理由 |
| --- | --- | --- | --- |
| 选题构思 | `ccf-idea-optimizer`（CCF）／`hypothesis-generation`（通用） | `idea-generation`、`research-ideation`、`kdense-scientific-brainstorming` | 前者有明确的 problem-gap-insight 结构与下游交接 |
| 想法审核 | `ccf-idea-reviewer` | `novelty-assessment` | 前者默认不含实验评估，符合"先判概念"的需要 |
| 文献检索 | `ccf-literature-searcher`（CCF）／`nature-academic-search`（Nature） | 其余 18 个 | 这两条已在各自体系内接好下游 |
| 持续追踪 | `ccf-literature-monitor` | `daily-paper-generator` | 前者有日期证据与重叠标记，后者是通用摘要 |
| 文献管理 | `nature-ref-verifier` + `bib-search-citation` | `pyzotero`、`citation-management` | 前者做多源交叉验证，后者做本地 BibTeX 检索；`pyzotero` 留给程序化批量操作 |
| 精读 | `nature-paper-card`（结构化方法/证据链） | `claude-paper-summary` | 前者产出可复用的 Paper Card，后者是一次性摘要 |
| 全文对照翻译 | `nature-reader` | — | 唯一一个做图文对齐的 |
| 综述写作 | `research-literature-review` | `literature-review`、`davila7-*`、`evidence-synthesis` | 前者是最完整的一条（检索→评分→写作→引用校验） |
| 实验设计 | `ccf-experiment-designer` | `experiment-design`、`research-planning` | 前者有 claim↔实验↔结果表的证据结构 |
| 统计 | `nature-statistics`（稿件统计审查）／`statsmodels`（具体建模） | `statistical-analysis`、`kdense-*`、`data-analysis` | 前者审报告口径，后者是库用法 |
| 绘图 | `ccf-visual-composer`（投稿图） | `nature-figure`、`cell-cns-figure`、`scipilot-figure-skill`、`figure-generation`、`publication-chart-skill` | 投稿图与探索图分开：前者管布局与可编辑交付 |
| 写作 | `ccf-paper-writer`（CCF）／`nature-writing`（Nature） | `ml-paper-writing`、`academic-paper-composer`、`econ-write`、`paper-writing-studio` | 各自的 venue 感知最强 |
| 引用核验 | `ccf-integrity-auditor`（CCF）／`nature-ref-verifier`（Nature） | `citation-verification`、`research-citation-check` | 前两者的输出可直接进各自状态机 |
| 审稿 | `ccf-paper-reviewer`（CCF）／`nature-reviewer`（Nature） | `academic-paper-reviewer`、`peer-review`、`self-review`、`paper-audit` | review 与 rewrite 的边界清晰：这两条只审不改 |
| 投稿检查 | `ccf-submission-checker` | — | 唯一会去核实 venue 当年规则的 |
| 返修答复 | `ccf-rebuttal-writer`（CCF）／`nature-response`（Nature） | `review-response`、`rebuttal-writing` | 前者维护 revision ledger |
| 汇报展示 | `nature-paper2ppt` | `scientific-slides`、`paper-deck` | 保留源图与讲者备注 |
| 基金申报 | `nsfc-*` 系列 | `research-grants`、`researchwrite` | 前者按国自然本子结构写 |
| 全流程统筹 | `ccf-pipeline-orchestrator` | `academic-pipeline`、`paper-skill` | 只有它有 `ccfa.yaml` 状态与 gate |

### 6.3 与本工作流工具的关系

上面这张表解决"选哪个 skill"，但**不解决"证据落在哪里"**。这正是 paper-template 那 9 个确定性工具的位置：

| 关注点 | 工具 | 与 skill 的分工 |
| --- | --- | --- |
| 这条引用是否真实存在 | `citation-guard`（Plan 2，进行中） | skill 负责找与写，工具负责判真假 |
| 正文数字是否来自数据 | `trace-claims` | skill 负责叙述，工具负责核对 |
| 是否还有未解析引用 | `final-check` | skill 负责改，工具负责判是否改完 |

**skill 给判断，工具给判决。** 两者都不能省。

## 七、结论与待决

1. 分类清单的数据准确，可直接作为后续管理依据。
2. 修好了 1 个彻底损坏的 skill（`academic-paper-strategist`）。
3. 遗留 1 个待你决定：同一 skill 的描述超出 25 字符，修它需要改内容。
4. 153 条"未允许字段"告警确认为跨 harness 假阳性，不建议据此批量改动。
5. 未被验证的一点：`disable-model-invocation`、`user-invocable` 这类字段在 Codex 下的实际行为。若你依赖它们控制调用方式，需要实测。

## 方法学限制

- 只做了静态检查：解析 frontmatter、跑官方校验器、统计字段与触发词。没有实际加载任何 skill，也没有验证它们的脚本能跑。
- 触发词碰撞统计用的是关键词正则，命中数（18–41）包含了描述中顺带提及该词的 skill，不是真正的触发冲突。要精确判定需要模拟加载器，本轮未做。
- 路由表的选型依据是各 skill 的 description 与本项目既定的三条决定，未逐个通读 322 个 skill 的正文。
