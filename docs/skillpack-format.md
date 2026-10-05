# Skillpack 格式（参考 Modex-MH-Agent 的加密技能包）

日期：2026-10-06
工具：`tools/ccfa/skillpack.py`（`scripts/skillpack.ps1`）

## 一、先看它保护了什么

本机 Modex-MH-Agent 1.6.5 的实测：

| 事实 | 证据 |
| --- | --- |
| 283 个 `*.enc`，合计 7,724,954 字节，单文件 1 KB 到 50 KB+ | 递归统计 |
| 加密算法是 AES-256-GCM，外面套了 zlib 字典框 | `skill_crypto.pyd` 里的 `AES-256-GCM` / `nonce` / `zlib` / `dictionary` 字符串 |
| 密钥与机器绑定 | 同一模块里的 `_get_machine_fingerprint` / `MachineGuid` / `getnode` |
| 密钥运行时构造、用完擦除 | `_xor_bind` / `_validate_secret_chain` / `_wipe_bytearray` / `decrypt_dk_from_transport` |
| 执行前强制再联网校验 | `_force_online_verify` |
| 没有标准 KDF 名字 | backend 里搜不到 `sha256` / `scrypt` / `hkdf` |

它确实挡住了「直接读提示词」，但**结构层什么都没挡住**：技能名、`references/`
文件名、`templates/`、`tools/` 目录、`prompts/` 模块名全是明文，方法论骨架一眼可见
（这本身就是上一轮审计能做出来的原因）。而它的技能内容源自 MIT 许可的 ARIS，
上游本来就是明文。

结论：**加密保护的是"随手复制"，不是"内容本身"。** 代价是全部离线不可用、
换硬件即失效、外人在拿到包之前无法校验任何东西。

## 二、我们抄哪一半

保留：**一个自描述、可校验、可离线验证的包**。
不要：**伪装层、服务端下发密钥、机器指纹绑定**。

`.skillpack` 就是一个 zip：

```text
skillpack.json                 清单（明文，永远放在第一个成员）
payload/<相对路径>              明文包：原始字节
payload/<相对路径>.enc          加密包：AES-256-GCM 密文
```

清单字段：

```json
{
  "format": "ccfa-skillpack",
  "format_version": 1,
  "pack_id": "ccf-skills",
  "version": "2026.10.06",
  "created_at": "2026-10-06T00:00:00Z",
  "roles": ["executor", "reviewer"],
  "file_count": 42,
  "total_size": 123456,
  "encryption": null,
  "manifest_sha256": "sha256:...",
  "files": [
    {
      "path": "ccf-common/SKILL.md",
      "size": 1234,
      "sha256": "sha256:<明文哈希>",
      "stored": "payload/ccf-common/SKILL.md",
      "stored_sha256": "sha256:<存储字节哈希>",
      "nonce": null
    }
  ]
}
```

加密模式下 `encryption` 记录算法、KDF、迭代次数、salt、`key_check`；
每个文件有独立 nonce（12 字节），密钥由口令经 PBKDF2-HMAC-SHA256（600k 次）派生。

## 三、校验语义（这是他们没有的一半）

```powershell
scripts/skillpack.ps1 pack --source <技能目录> --out ccf-skills.skillpack `
    --pack-id ccf-skills --version 2026.10.06 --role executor

scripts/skillpack.ps1 verify ccf-skills.skillpack          # 0 = 干净，1 = 有问题，2 = 工具错误
scripts/skillpack.ps1 list   ccf-skills.skillpack
scripts/skillpack.ps1 unpack ccf-skills.skillpack --dest <目录> [--force]
```

`verify` 做五件事，缺一不可：

1. 清单自身的 `manifest_sha256` 是否与内容一致（清单被改写会被发现）；
2. 每个成员的实际字节是否匹配 `stored_sha256`；
3. 包里有没有清单未声明的成员（夹带文件）；
4. 清单路径是否越界（绝对路径或 `..`）；
5. 给了口令时，解密后是否同时匹配 `sha256` 与 `size`。

没有口令时加密包返回 `skillpack-locked`（问题，退出码 1），而不是假装通过。
口令错误返回 `skillpack-bad-passphrase`——用 `key_check` 判定，不需要先解一个大文件。

打包是**确定性**的：固定 zip 时间戳、成员排序，同一棵树打两次字节完全相同，
所以包本身的哈希可以作为对外发布的标识。

## 四、威胁模型（写清楚，不装作更强）

能挡住：

- 拿到包但不知道口令的人；
- 传输过程中被改动（bit 级篡改会被 `verify` 抓到）；
- 夹带/替换成员；
- "作者改了内容但说没改"（清单哈希 + 确定性打包）。

挡不住：

- 能运行打包内容的机器上读内存拿密钥；
- 拿到明文包的人（明文是默认模式）；
- 通过目录名/文件名推断方法论骨架——这一点加密的 Modex 也挡不住。

因此：**需要被审计的包保持明文**；`--encrypt` 只用于"发给合作者但不想被随便转发"
的场景。不建议做机器指纹绑定：换硬件、重装系统、离线 CI 都会当场失效，
而这些失败模式和"科研产物要能长期复现"直接冲突。

## 五、不做的事

- 不做 license 服务器，不做在线激活，不做硬件绑定；
- 不做伪装容器（zlib 字典框那种），它让包既不像密文也不像压缩包，反而不利于排查；
- 不用它保护需要被评审的科研证据——证据要能被独立复核，加密与那个目标冲突。
