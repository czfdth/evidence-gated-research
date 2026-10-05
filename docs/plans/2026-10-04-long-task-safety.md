# 长任务安全 v1 实施计划（P1：可中断、可观察、有停止条件）

**Goal:** 关闭审计 P1-5：`queue` 目前只有墙钟预算与显式重试，没有并发上限、GPU 预算、卡死检测与受控运行策略。v1 面向本机单卡、人工启动的 ML 实验队列，先把可验证的停止条件做实；不把策略层伪装成 OS 级沙箱。

**裁定：**

- **E64 并发上限 = 1，按 log 目录加 OS 文件锁。** 同一 `--log-dir` 同时只允许一个队列实例；Windows 用 `msvcrt.locking`，POSIX 用 `fcntl.flock`。进程死亡由 OS 自动释放，不做易竞态的陈旧 PID 回收。第二条队列退 2，不排队、不静默并行。
- **E65 GPU 预算按 `nvidia-smi` 利用率采样。** `--gpu-budget-seconds` 或清单 `gpu_budget_s` 生效；默认每 1 秒采样一次，利用率 ≥ 5% 的墙钟时间计入 GPU 秒数。预算耗尽后当前 attempt 留档，后续项记 `skipped-gpu-budget`，整体退 1。`nvidia-smi` 不可用且确实要 GPU 预算时退 2，不静默忽略。
- **E66 看门狗按“无输出”判断卡死，不按总时长猜测。** `stall_timeout_s` 内子进程 stdout/stderr 都没有新行则 kill，记 `stalled`；是否重试由 `retry_on_stall` 显式声明。总时长仍由现有 `timeout_s` 管。
- **E67 沙箱 v1 = 进程策略沙箱，不是 OS 隔离。** `sandbox: policy` 只做三件事：`cwd` 必须解析到队列根内、默认环境只保留白名单变量、子进程由默认 runner 管理生命周期。它不限制文件系统写、网络或 GPU 可见性；需要这些隔离时必须另接 Docker/WSL/专用沙箱。help 与报告必须写明边界。
- **E71 Docker 沙箱后端（v1.1）。** `sandbox: docker` 使用受信任镜像运行队列项：根文件系统只读、队列根只读挂载到 `/workspace`、仅 `docker_output`（默认 `runs`）可写挂载到 `/outputs`、默认 `--network none`；`docker_gpus: all` 才加 `--gpus all`。Docker daemon 不可用直接退 2，不静默回退到宿主机。容器内只注入显式 CCFA 变量与镜像自带环境，不继承宿主环境。镜像本身是受信任输入；这不是对恶意镜像的强安全边界。

**Files:** Modify `tools/ccfa/queue.py`、`tools/tests/test_queue.py`、`docs/design/2026-10-03-research-workflow-design.md`、`docs/sdd/2026-10-03-evidence-tracking-progress.md`。

### Task 1: 独占锁与停止条件字段

- 清单新增可选 `stall_timeout_s`、`retry_on_stall`、`gpu_budget_s`、`sandbox`（`none|policy`）。
- `run_queue` 在开始时获取 `log_dir/.queue.lock` 的 OS 锁；正常/异常退出都释放。
- 判别力：锁被持有时第二次调用退 2；进程退出后锁自动可重获；残留元数据不阻塞下一次获取。

### Task 2: GPU 预算

- `GpuMeter` 默认调用 `nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits`，采样线程累计 busy 秒数。
- `run_queue` 每次 attempt 后把 `gpu_seconds`/`gpu_samples` 写进独立 `resource_usage` 字段，不写 `metrics`；累计超预算后停止并标记后续项。成功但未记实验指标的 run 仍会被 `run-log-metrics-pending` 报出。
- 测试注入 fake meter；真实冒烟只验证 `nvidia-smi` 读取路径不崩且记录非负秒数。

### Task 3: 卡死看门狗

- 默认 runner 维护 last-output 时间；超过 `stall_timeout_s` 无输出则 kill 并抛 `QueueStalled`。
- `run_queue` 把 `stalled` attempt 留档；`retry_on_stall` 为真才重试。
- 判别力：真实子进程先输出后 sleep → 看门狗在 stall 阈值附近 kill；无 `stall_timeout_s` 时不触发。

### Task 4: 策略沙箱

- `sandbox: policy`：`cwd` 越出 queue root → `ValueError`；默认 runner 用 `_sandbox_env()` 白名单环境；注入 runner 不能宣称 policy，直接退 2。
- 边界写进 docstring/help：不承诺只读数据、不承诺禁网、不承诺 GPU 隔离。
- 判别力：`..` 逃逸与绝对外部路径均被拒；白名单外变量不传给子进程。

### Task 5: Docker 沙箱后端（v1.1）

- 清单新增 `docker_image`（`sandbox: docker` 时必填）、`docker_network`（默认 `none`）、`docker_gpus`（`null` 或 `all`）、`docker_output`（默认 `runs`，必须是队列根内的相对目录）。
- `run_queue` 在进入队列循环前调用一次 `docker info`。daemon 不可用 → `ValueError`，CLI 退 2，且不调用任何队列项；绝不回退到宿主机执行。
- 清单声明 `sandbox: docker` 时，CLI `--sandbox none|policy` 属于降级，默认拒绝；确需降级必须显式 `--allow-sandbox-downgrade`。policy/docker 模式默认拒绝注入 runner；测试或高级调用要注入 runner 必须显式 `allow_injected_runner=True`，否则 run-log 可能声称 Docker 而实际在宿主机执行。
- 每个 attempt 生成独立容器名，`docker run` 参数固定包含 `--rm --read-only --security-opt no-new-privileges`，队列根以 `readonly` 方式挂到 `/workspace`，`docker_output` 可写挂到 `/outputs`，工作目录映射为 `/workspace/<item cwd>`。
- Docker argv 在 `run_command` 写入 `running` 之前构造；symlink 逃逸、逗号路径、输出目录创建失败等校验错误不会留下无终态的 `running` 记录。GPU meter 在 argv 构造成功后才启动，构造失败不会留下采样线程。
- 宿主机环境不进入容器；容器只收到 `HOME=/tmp`（让只读根上的缓存写入落到 tmpfs）、`CCFA_WORKSPACE=/workspace`、`CCFA_OUTPUT_DIR=/outputs` 与显式 `env` 参数。run-log 的 `policy` 记录镜像、网络、GPU、输出目录与容器内 `workdir`，但 `command` 仍是原始队列命令。
- 超时或卡死会 kill Docker CLI；`finally` 再执行一次 best-effort `docker rm -f <name>`，避免 CLI 被杀后容器继续占 GPU。宿主进程被强杀或机器断电仍可能留下 `ccfa-` 前缀容器，需要用 `docker ps` 人工清理；这是 v1 的已知边界。
- 判别力：精确断言 mount/network/workdir/命令顺序；daemon 不可用时不执行、不留 run-log；CLI 降级需显式 flag；注入 runner 默认拒绝；构造 argv 失败不留 `running`；symlink/drive-relative `docker_output` 被拒；超时 attempt 必定调用清理；宿主 `QUEUE_TEST_SECRET` 不出现在容器 argv。

## 完成定义

- `queue` 有并发锁、GPU 预算、卡死看门狗、策略沙箱与 Docker 沙箱五类停止/约束，并全部有判别性测试。
- 所有 attempt 仍先写 `running` 再写终态；失败、超时、卡死都不被静默重试掉。
- 全量 tools/app 全绿；真实 `nvidia-smi` 与真实子进程冒烟留档。Docker 后端在 daemon 不可用时必须有真实退 2 冒烟；daemon 可用时优先补真实容器只读/可写/禁网冒烟。
- 文档明确 policy 与 Docker 两种后端的边界：policy 不是 OS 隔离；Docker 只承诺只读根/只读队列根/单输出目录可写/默认禁网，不承诺防恶意镜像。
