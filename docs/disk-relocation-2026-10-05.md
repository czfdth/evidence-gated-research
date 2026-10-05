# C 盘清理与 F 盘迁移记录

日期：2026-10-05
触发原因：安装 LibreOffice 时 Windows Installer 报 `OutOfDiskSpace = 1` / 1603，
实测 C 盘只剩 **0.70 GB / 400 GB**。

## 一、结论

**C 盘可用空间：0.70 GB → 39.81 GB。**
迁移方式统一为「搬到 F 盘 + 在原路径建 junction」，应用程序感知不到路径变化。

## 二、C 盘为什么满了

`%APPDATA%`（`<home>\AppData\Roaming`）单目录约 40 GB，前几名：

| 目录 | 大小 |
| --- | --- |
| `TRAE SOLO CN` | 17.2 GB |
| `kingsoft` | 3.9 GB |
| `Tencent` | 3.6 GB |
| `baidu` | 2.0 GB |
| `Code` / `JetBrains` | 各约 1.2 GB |
| `kimi-desktop` / `uv` / `greencore` | 各约 1.0 GB |

另有 `%TEMP%` 约 5.2 GB（本轮已顺手清掉自建的解包与日志残留）。

## 三、已迁移（junction 生效中）

目标根目录：`F:\UsersData\Roaming`

| 目录 | 大小 |
| --- | --- |
| `TRAE SOLO CN` | 17.2 GB |
| `Code` | 1.2 GB |
| `JetBrains` | 1.2 GB |
| `kimi-desktop` | 1.1 GB |
| `greencore` | 1.0 GB |
| `Xiaomi MiMo` | 0.89 GB |
| `UnityHub` | 0.84 GB |
| `Trae CN` | 0.55 GB |
| `baidunetdisk` | 0.52 GB |
| `360se6` | 0.51 GB |
| `npm` | 0.51 GB |
| `GreenCore7z` / `TuanjieWebGLHost` / `UnityHubWebGLHost` | 各约 0.34 GB |

查看方式：

```powershell
Get-ChildItem "$env:APPDATA" -Force |
  Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } |
  ForEach-Object { "$($_.Name) -> $((Get-Item -LiteralPath $_.FullName -Force).Target)" }
```

## 四、迁移中回滚的两个目录（重要）

这两个目录**已完整复制到 F 后又原样还原回 C**，现在是干净的原始状态：

| 目录 | 原因 | 处置 |
| --- | --- | --- |
| `uv` | 有 7 个正在运行的 MCP `python.exe` 就位于 `uv\python\cpython-3.10-windows-x86_64-none\`（`cpython-3.10-*` 是指向 `cpython-3.10.21-*` 的链接）。搬移会让运行中的文献 MCP 服务失去解释器。 | 已还原，7 个进程全部存活 |
| `baidu` | `BaiduNetdisk\YunShellExtV164.dll` 被 `explorer.exe` 加载为 shell 扩展，无法删除，junction 建不起来。 | 已还原 |

要迁移这两个，需要先让占用方退出：

```powershell
# uv：结束依赖 uv 托管 Python 的 MCP 进程后再迁
# baidu：结束资源管理器中的百度网盘 shell 扩展（或注销/重启）后再迁
```

## 五、本轮明确跳过的目录

进程正在运行，搬移会破坏其状态：

| 目录 | 占用进程 |
| --- | --- |
| `kingsoft` | `wps.exe` |
| `Tencent` | `wetype_server` / `wetype_renderer` |
| `PICO Connect` | 4 个 `PICO Connect` 进程 |

另：`C:\Program Files`（57.9 GB）、`C:\Program Files (x86)`（27.8 GB）、
`C:\ProgramData`（8.0 GB）体量更大，但属于已安装程序，不在本轮「应用数据搬迁」范围内。

## 六、回滚方式

单个目录回滚（以 `Code` 为例）：

```powershell
$name = 'Code'
$link = Join-Path $env:APPDATA $name
$real = "F:\UsersData\Roaming\$name"
# 1. 删掉 junction（只删链接，不动 F 盘数据）
[System.IO.Directory]::Delete($link, $false)
# 2. 把数据搬回来
robocopy $real $link /E /MOVE
```

注意：`[System.IO.Directory]::Delete($link, $false)` 只删除链接本身；
加 `$true` 会删除链接**指向的内容**。回滚时务必用 `$false`。

## 七、复现要点

1. 先确认目标应用没有进程在运行。
2. 用 `robocopy <src> <dst> /E /MOVE /SL /XJ /R:0 /W:0` 搬移（`/SL` 保留符号链接，
   `/XJ` 避免跟进 junction 形成递归）。
3. 搬完后如果源目录还有残留，**先判断残留是不是损坏的符号链接**；
   只要存在普通文件残留就说明有文件被占用，此时不要建 junction，应回滚或等占用方退出。
4. 用 `New-Item -ItemType Junction -Path <src> -Target <dst>` 建链接（无需管理员）。
