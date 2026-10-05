# 论文工作台 app

`ccfa_core` 是零 Qt 依赖的核心层：项目发现、设置、密钥与检查编排。
GUI 在 `app/ccfa_gui/`。

## 与工作流的关系

工作台是工作流的**消费者**，不是它的一部分：**`app/` 下的代码不 import 任何
`ccfa.*` 模块**。所有确定性操作都通过子进程调用工作流自己的
`python -m ccfa.<tool>` 入口，只依赖它已经承诺的契约——JSON 到 stdout、人读摘要到
stderr、退出码 0（干净）/ 1（发现问题）/ 2（工具错误）。

因此两边可以独立改动：工作流改函数签名不会打断工作台，只有改 CLI 契约才会。反过来
工作流也不依赖 app，删掉整个 `app/` 不会影响任何 gate 或证据。

工作流位置按以下顺序解析：

1. 调用方显式传入的 `root`；
2. 环境变量 `CCFA_WORKFLOW_ROOT`；
3. 本文件所在仓库根（两边同仓库时的默认值）。

解释器优先用工作流自己的 `tools/.venv`；不存在时回退到当前解释器并把 `PYTHONPATH`
指向工作流的 `tools/`。也可用 `CCFA_WORKFLOW_PYTHON` 指定解释器。

## 环境

需要 Python 3.12（本仓库用 3.12.14 实测）。在仓库根执行：

```powershell
py -3.12 -m venv app/.venv
& app/.venv/Scripts/python.exe -m pip install -r app/requirements.txt
```

若本机没有 `py`，改用你机器上的 Python 3.12 解释器完整路径，例如：
`<你机器上的 Python 3.12> -m venv app/.venv`。

`app/.venv` 已被 gitignore。工作台自己不 import `ccfa`，所以**不需要**
`PYTHONPATH=tools`；它只在调用工作流时给子进程设置该变量。

## 跑测试

```powershell
cd <仓库根>
& app/.venv/Scripts/python.exe -m unittest discover -s app/tests -t app
```

## 打包成 Windows 安装包

```powershell
cd <仓库根>
& app/.venv/Scripts/python.exe -m pip install -r app/requirements-dev.txt
scripts/build-workbench.ps1
```

产物：`dist/ccfa-workbench/`（PyInstaller 冻结版）与
`dist/ccfa-workbench-setup-<version>.exe`（Inno Setup 安装程序）。
安装是按用户进行的（不需要管理员），默认装到
`%LOCALAPPDATA%\Programs\ccfa-workbench`，卸载时保留 `%APPDATA%` 下的设置。

装完可以不做任何人工操作先跑一次自检（不启动界面）：

```powershell
& "$env:LOCALAPPDATA\Programs\ccfa-workbench\ccfa-workbench.exe" --self-check
# {"probe_ok": true, "workflow_root": "...", "workflow_python": "...", ...}
```

`probe_ok=false` 时 `probe_detail` 会说明是找不到工作流目录、没有解释器、
工作流目录里缺 `tools/ccfa`，还是**解释器跑不动 gate**。最后一种是真实会咬人的：
`ccfa.readiness` 用一个缺依赖的解释器跑时，`formal-check`、`claim-candidates`
这类 gate 会失败——而失败的 gate 长得就像「论文被阻塞」。所以 probe 会再问一次
工作流自己的 `ccfa.doctor --imports-only`（在该解释器里真的 `import` 一遍各 gate
的依赖，约 0.4s），缺哪个模块就照实报，而不是让报告凭空多出几条阻塞。
「设置 → 测试连接」走的是同一条 probe。

**安装版怎么找到工作流**：冻结包里没有 `ccfa`，所以启动时按下面的顺序找
"包含 `tools/ccfa` 的目录"，第一个命中就用：

1. 设置页里填的「工作流目录」（或环境变量 `CCFA_WORKFLOW_ROOT`）
2. 安装目录下的 `workflow\`（如果发行版把工作流捆进去了）
3. `%LOCALAPPDATA%\Programs\research-workflow`
4. `%USERPROFILE%\research-workflow`
5. `%USERPROFILE%\Documents\research-workflow`

开发时本仓库就是第 0 个候选（`app/` 的上一级），所以本地跑无需任何配置。
一个都找不到时，报告里会给出具体路径并提示去设置页填写。设置写在
`%APPDATA%\ccfa-workbench\settings.json`。

**捆绑运行时的现状与代价**（给"不发仓库只发 exe"的合作者用）：

- 默认只捆 app（工作流要自己配目录，或放在上面几个搜索位置之一）；
- 加上 `-BundleWorkflow` 后会多打一个自包含运行时
  （`scripts/bundle-workflow.ps1`：embeddable CPython + `tools/` 源码 +
  `pip --target` 依赖 → `dist/ccfa-workbench/workflow/`，实测 **169.8 MB**），
  安装版开箱即用；
- 为什么不用 `tools/.venv`：venv 的 `pyvenv.cfg` 指向构建机的解释器，换机器直接废；
  嵌入版的 `._pth` 把 `..\tools` 与 `..\tools\site-packages` 写进 `sys.path`，
  且 Python 在有 `._pth` 时会忽略 `PYTHONPATH`；
- 嵌入版 stdlib 是**裁剪过**的（没有 `venv`、`tkinter`），所以打包脚本会
  **逐个 import 全部 `ccfa.*` 模块**做自检（当前 84 个），缺模块在构建时就失败，
  而不是等用户点开某个功能才崩；
- 再往上就是 TeX/Docker/GPU 这类外部依赖：Modex 那类产品把 texlive 整体捆进
  安装包（1GB 级），我们没有跟。
**PySide6 版本**：`requirements.txt` 故意钉在 6.9.1 而不是最新版。用 6.11.2 冻结
出来的程序启动即报 `DLL load failed while importing QtWidgets`（用一个 10 行的
最小应用复现过，与本项目代码无关）。升级这个 pin 之前，一定要重跑
`scripts/build-workbench.ps1` 并实测启动。

## 启动 GUI

```powershell
cd app
& .venv/Scripts/python.exe -m ccfa_gui.main
```

## 主界面

三栏同时可见：左栏 `papers/` 下的项目（坏项目显示 `▲` 与一行原因），中栏当前项目的
阶段/门禁/截止徽章与检查结果，右栏对话。中栏每个动作都走工作流自己的 CLI
（`ccfa_core` 只解析 JSON，不重复实现工具语义）：

项目行还会带上协作状态：`●` 正常，`◆` 表示 `ccfa.readiness --collaboration-only`
报了问题（非 git 仓库、有未提交改动、无 remote、无 CI workflows），颜色为琥珀，鼠标
悬停的 tooltip 逐条列出原因与提交号，工具栏汇总 `N 个项目 · … · M 个有协作风险`。
行里不写第二段文字：侧栏只有 180px，「有未提交改动」这类后缀会被省略成「· 有未提」，
所以状态由字形+颜色表达，细节放 tooltip。探针走 `QThreadPool` 后台线程（`ccfa_gui/
collaboration_probe.py`），因为一次 `--collaboration-only` 约 0.6s，不能卡住刷新；
每次刷新会递增 generation，过期结果直接丢弃。测试用
`MainWindow(..., collaboration_probes=False)` 关掉它，只留一个真跑子进程的集成用例。

界面图标来自 `ccfa_gui/icon_paths.py` 的线性路径（无 Qt 依赖，同一条路径数据
也供 `docs/design/generate_mockups.py` 生成设计稿），工具栏最左侧是产品标记；
没有项目可显示时中栏是空白状态（图标 + 一行提示），不是一张空表。

配色跟随系统深浅色（`ccfa_gui/appearance.py` 读 `QStyleHints.colorScheme`，
`CCFA_THEME=light|dark` 可强制覆盖），两套色板在 `theme.py` 的 `LIGHT`/`DARK`，
键名一致并有测试钉住。窗口窄于 1000px 时右栏对话自动收起，工具栏的对话按钮
可以手动叫回来。

对话消息按角色渲染成气泡：`user` 主色淡底、`assistant` 面板、`tool` 灰底，
`error` 红底、`stopped` 琥珀底；工具消息的 `名字 [risk] -> outcome` 会拆成
名字 / risk chip / outcome 三段，chip 颜色跟 outcome 走。列表项仍保留纯文本
（`item.text()` 不变），所以既有脚本消费者不受影响。

气泡正文按 **Markdown** 渲染（`QTextBrowser.setMarkdown`）：列表、强调、
链接、代码围栏都生效；代码块用等宽字体加当前模式的底色，代码行会换行
而不是被裁掉，切换深浅色时气泡文档会按新色板重渲染。

动效只解释布局变化：对话栏收起/展开是 180ms 的宽度动画，详情页切换是 140ms 淡入。
`MainWindow(..., animations=False)` 或 `CCFA_NO_ANIM=1` 可全部关掉（测试与
减少动效偏好都用这条路径）。

| 按钮 | 调用的工作流命令 | 结果 |
| --- | --- | --- |
| 运行 validate | `ccfa.validate` | `ccfa.yaml` 的 schema 与状态问题 |
| 运行 milestones | `ccfa.milestones due` | 倒排截止与 gate 缺口 |
| 运行 readiness | `ccfa.readiness` | 一屏给出六个维度、每个 gate 的结论与阻塞清单 |
| 阶段流转 | `ccfa.state` | 推进/回退 stage，写回 `ccfa.yaml` 并记入 `stage.history` |
| 待人工复核 | `ccfa.readiness --checkpoints-only` | 人工复核队列：要判断什么、写进哪个台账 |
| 导出报告（头部图标） | `ccfa.readiness --out` | 写出 `reviews/readiness-<日期>.md` 一页式报告并打开 |

头部徽章的「截止」显示的是倒计时（`剩 9 天` / `已逾期 6 天` / `今天截止`），绝对日期
在 tooltip 里：徽章行在窄窗口本来就紧，塞进完整日期会挤掉其它徽章，而 readiness 的
Markdown 报告第一段就是 `## Summary`（投稿倒计时、阻塞条数与第一条阻塞、待人工复核
项数），所以日期并没有丢。导出报告走工作流自己的 `render_markdown`，不是工作台另写
一份摘要——同一篇论文不能有两套会漂移的描述。

动作按钮排在一行可换行的流式布局里（`ccfa_gui/flow_layout.py`）：中栏被对话栏挤窄时
按钮换到第二行，而不是把「运行 milestones」这类标签省略成「运行 mileston」。窄窗口
的回归测试直接断言每个按钮的宽度不小于 `sizeHint()`。

阶段流转是唯一会写盘的动作：弹窗先选定推进/回退（按钮组，只列出工作流 stage 表里
合法的目标）、填原因，回退时再逐行列出要作废的产物；原因是必填的，工作流自己也会
拒绝空原因。确认后由 `ccfa_core.state` 调 `ccfa.state … --confirm`，成功后工作台重新
扫描 `papers/` 并重新选中同一个项目，所以徽章显示的是工作流写回后的状态，而不是
界面自己的推测。

readiness 视图把三样东西排进同一张表：**维度**（`schema-valid` / `evidence-present` /
`gate-verified` / `independently-reviewed` / `scientifically-accepted` /
`collaboration-ready`）、**gate 结论**（只列非 `pass` 的：`blocked` 琥珀、`fail` 红）、
**阻塞项**；右侧汇总 `ready=... · N 条阻塞`，横幅给出第一条阻塞与 gate 结论计数。

`--checkpoints-only` 只解析人工台账、不跑 gate，所以点它是秒级返回。结果区会切换成
卡片列表：每条 checkpoint 一张卡（类型 chip、问题、`台账 — 答案要求`），卡片上的
`打开台账` 直接打开要写的 YAML/JSON（文件还不存在时打开最近的已存在目录，
并且绝不允许台账路径把用户带出项目目录）；上方是状态横幅（待人工/已完成/不要求）。
设计稿见仓库 `docs/design/exports/04-human-checkpoints.svg`。

## 红线

- `ccfa_core` 不 import PySide6（E58）。
- `ccfa_core` / `ccfa_gui` / `app/tests` 不 import `ccfa.*`：只能走 CLI 子进程。
- `settings.json` 只写 `key_name` 引用，不写 key 明文；密钥只进
  `KeyringSecretStore`（E57）。
- keyring 不可用时抛 `SecretStoreUnavailable`，不降级明文。

## 引擎与取消

- `OpenAICompatibleEngine` 的取消是协作式的：只在请求边界生效，最坏等待当前
  HTTP 请求完成或超时（`timeout_s` 兜底）；正在飞行中的请求不会被中途打断。
- `CodexExecEngine` 的取消会立即 kill 子进程。
- 引擎错误消息不包含 `SecretStore.get()` 的原始异常文本（可能嵌入 key），
  只带异常类型名。

## 自定义 HTTP 工具

`ccfa_core/http_tools.py` 提供声明式 HTTP 工具注册表。它只读 YAML，不执行任意
代码：v1 只支持 GET/POST；`http://` 需显式 `allow_http: true`；敏感头必须写成
`secret:<key_name>` 并由 keyring 取值——判定按名字，任何含
token/key/auth/secret/credential/password/session/cookie 的头都算敏感，明文凭据是加载错误；
占位符必须在 `parameters` 中声明；压缩响应默认拒绝（解压会在限流前吃内存），
确需时写 `allow_compressed: true`；任一工具非法则整份注册表不加载。格式与示例见
仓库根 `README.md` 的「论文工作台（P2）」一节。

`ToolBridge(project_root, http_tools=HttpToolRegistry(...))` 会把注册的工具与内置
工具合并：同一套参数校验、写操作确认与审计（只记参数摘要）。

工作台设置页已经接入注册表：填写或选择 YAML 路径，保存时整份验证；相对路径按
`settings.json` 所在目录解析。保存成功后当前项目的工具桥立即重建，无需重启。
无效注册表只显示错误代码并整份拒载，不回显 YAML 内容。
