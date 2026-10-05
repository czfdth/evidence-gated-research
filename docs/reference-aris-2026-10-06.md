# 参考审计：ARIS（Modex-MH-Agent 的上游）

日期：2026-10-06
对象：`wanshuiyin/Auto-claude-code-research-in-sleep`（ARIS，MIT）
方法：`gh api` 读仓库元数据 + `git clone --depth 1` 后直接读源码

## 一、为什么换成这个参考对象

上一份审计（`docs/reference-modex-mh-agent-2026-10-06.md`）读的是本机安装的
Modex-MH-Agent，它的技能是密文，只能推断。WorkBuddy 的分析指出了上游，
我自己在二进制里核对了它的关键论断：

| 论断 | 我自己的验证 | 结果 |
| --- | --- | --- |
| 派生自 `Auto-claude-code-research-in-sleep` | `rg -a` 二进制 | 命中 14 个文件 |
| 打包路径残留 `_tmp_backend` | `rg -a` 二进制 | 命中 13 个文件 |
| `_check_step_companions` / `_min_size_for` / `_required_companions_for` | `rg -a` 二进制 | 各命中 1 个文件 |
| `_should_skip_step_by_assets` / `_generate_claude_md` | `rg -a` 二进制 | 各命中 1 个文件 |
| `mhcoding.xyz` / `aris.db` | `rg -a` 二进制 | 各命中 1 个文件 |

注意：符号存在只证明这些名字在，不证明 WorkBuddy 对语义的推断都对。
所以真正值得读的是上游本身，它是 MIT、Markdown 明文，可以直接读。

仓库元数据（`gh api`）：17.0k stars、MIT、`pushed_at 2026-10-05`，
自述为 "Lightweight Markdown-only skills for autonomous ML research:
cross-model review loops, idea discovery, and experiment automation.
No framework, no lock-in"。

## 二、ARIS 的结构（实读）

```text
AGENT_GUIDE.md          18 KB，两个控制轴 + 工作流索引 + 跨模型协议
README_CN.md           195 KB
skills/                110+ 个明文 SKILL.md
mcp-servers/           claude-review, gemini-review, codex-exec, antigravity-exec,
                       grok-exec, manual-review, minimax-chat, llm-chat, feishu-bridge
skills/shared-references/  29 份契约文档（assurance-contract, reviewer-independence,
                       review-tracing, resumable-runs, experiment-integrity ...）
tools/, commands/, templates/, tests/
```

和 Modex 的关系：Modex 把 ARIS 的技能加密、套 Electron 壳、锁自家 API 网关；
ARIS 本体是明文 Markdown + 可选的 MCP 评审服务。

## 三、它比我们强的地方（按价值排序）

### 1. 两个独立控制轴：`effort` × `assurance`（本次采纳）

`effort: lite | balanced | max | beast` 管深度与预算；
`assurance: draft | submission` 管审计是否承载结论。

它给出的采纳理由很具体：早期把两者混在一起，结果 `effort: beast` 的论文
因为内容探测器没命中而静默跳过了三项投稿审计。这和我们踩过的
「present 等于 pass」是同一类事故。

`assurance: submission` 的语义是硬约束：

- 所有强制审计必须给出结论，禁止静默跳过；
- 缺前置条件的审计判 `BLOCKED`（阻塞），而不是当作「不适用」；
- 校验器不通过就拒绝生成 Final Report。

### 2. 六值结论状态机

`PASS / WARN / FAIL / NOT_APPLICABLE / BLOCKED / ERROR`，关键在于区分：

- `NOT_APPLICABLE`：探测器为负，但审计阶段跑过并留下产物（「查过，确实没有」）；
- `BLOCKED`：本该审计却缺前置条件（例如论文写了 89.2% 却没有 `results/`），阻塞；
- `ERROR`：审计本身失败，投稿档视为阻塞。

### 3. 审计产物 schema：把「审计过什么」变成可复算的事实

每项强制审计写 JSON，至少含 `audited_input_hashes`（被审文件的 SHA256）、
`trace_path`、`thread_id`、`executor_model` / `reviewer_model` 与各自 family、
`review_independence`、`acceptance_status`。校验器重新哈希这些输入，
不一致就标 `STALE` 并退出 1；`same-family` 的结论只能是 `provisional`，
永远不能对外说 `submission-ready: yes`。

还有一条硬规则：`deterministic` 只允许用在机器真能判定的审计上
（编译、schema、哈希、测试），四项语义审计（proof / claims / citations / attack）
只认 `cross-family`。

### 4. 分工纪律：「子审计只报告，父流程决定阻塞」

子审计永远出结论、从不自己阻塞；是否阻塞只在 `assurance` + 校验器这一处决定。
这避免了每个子工具各自发明阻塞语义。

### 5. 禁止自审自己的修复

`integrity-forensics` 里明写 "The One Forbidden Loop"：审计发现的问题，
不能由执行者改完就自评通过，必须有人类 sign-off。这与我们「人工复核」的立场一致，
但他们把它写成了禁止条款。

### 6. 其他值得记的

- `resumable-runs`：`— resume <run_id>`，长流程可断点续跑；
- `manual-review` MCP：给人用的评审界面，是把「人工复核」做成工具的样例；
- `reviewer-routing.md`（50 KB）：按难度路由评审者，`xhigh` / `ultra` 分层。

## 四、与我们工作流的对照

| 维度 | ARIS | 我们 | 判定 |
| --- | --- | --- | --- |
| 深度 vs 严格 | 两个独立轴 | 单一 `profile` | 本次采纳 |
| 结论词表 | 六值，含 BLOCKED / NOT_APPLICABLE | readiness 维度 + problems 退出码 | 我们表达力够，但没有统一词表 |
| 审计输入绑定 | `audited_input_hashes` + STALE 重算 | 证据变更作废 stale 评审 | 等价 |
| 跨族要求 | `cross-family` 才算 accepted | cross_review 同族需 override 留痕 | 等价 |
| 子工具阻塞权 | 只报告，父流程决定 | 同样的原则（advisory vs problem） | 等价 |
| 人工复核 | `manual-review` MCP + 禁止自审条款 | 台账 + checkpoint + 失败演练 | 我们台账更厚，他们交互更好 |
| 规模 | 110+ skills，明文 | 60+ CLI，可测 | 各有侧重 |

## 五、本次落地

`ccfa.yaml` 新增可选键 `workflow.assurance`：

```yaml
workflow:
  profile: minimal      # 深度/预算（不变）
  assurance: submission # 审计严格度（新增，可选）
```

- 不写：行为与之前完全一致（`high-assurance` 默认 `submission`，其余默认 `draft`）；
- `assurance: submission`：不管 profile 多轻，审计链升到 `high-assurance`，
  强制证据台账与人工复核 checkpoint；
- `assurance: draft`：给高保障项目一个显式降级出口（探索期用），
  profile 仍然标 `high-assurance`，避免假装审计已通过；
- 取值非法直接报错（fail closed），不静默按默认值跑。

`readiness` 报告新增 `assurance` 与 `audit_profile` 两个字段，
Markdown 头部同步显示，便于一眼看出「这次到底有没有跑审计」。

## 六、没有采纳的

1. 六值结论词表与审计 JSON schema：要迁移所有 gate 的输出格式，
   收益（外部可复算）我们已用 `readiness` + 哈希清单覆盖大半，先不动。
2. `mcp-servers/` 那套评审服务：我们已有 `cross_review` + 本地第二 family provider，
   再铺一层 MCP 只会增加维护面。
3. 110 个技能的目录规模：他们的定位是「任何 agent 都能用的 Markdown 技能包」，
   我们的定位是可被测试钉住的工具链，规模和形态本来就不该一样。

## 七、下一步候选

1. 把 `BLOCKED` 语义写进 readiness 维度：区分「没有这项审计」与「该审却缺前置」。
2. `resume <run_id>` 式的断点续跑，落到 `experiment-loop` 与 `queue`。
3. 把 `audited_input_hashes` 的复算扩到人工台账（proof-audit / citation-support），
   让「人在什么输入上签的字」可复算。
4. 给「证据存在」加最小体积门槛（对应 Modex 的 `_min_size_for`）：
   现在 `evidence.items[].present` 只看文件在不在，空壳文件要靠各自的 gate 兜。
