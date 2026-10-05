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

**安装版必须配置工作流目录**：冻结包里没有 `ccfa`，所以第一次启动后要在设置页
填写「工作流目录」（包含 `tools/.venv` 的仓库根），或者设置环境变量
`CCFA_WORKFLOW_ROOT`。设置本身写在 `%APPDATA%\ccfa-workbench\settings.json`。

**PySide6 版本**：`requirements.txt` 故意钉在 6.9.1 而不是最新版。用 6.11.2 冻结
出来的程序启动即报 `DLL load failed while importing QtWidgets`（用一个 10 行的
最小应用复现过，与本项目代码无关）。升级这个 pin 之前，一定要重跑
`scripts/build-workbench.ps1` 并实测启动。

## 启动 GUI

```powershell
cd app
& .venv/Scripts/python.exe -m ccfa_gui.main
```

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
