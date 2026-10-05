# run-log 实施计划 — Part B（指标登记与只读检查）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 `run-log` 的后半：`log-metrics` 把指标登记到已有记录上，`check` 只读地执行判定表——把**"跑了但没记指标"**从一个静默陷阱变成一个可检测的 problem。

**Architecture:** 沿用一运行一文件。`log-metrics` 就地更新一条记录（原子写、不新增文件）；`check` 只读遍历日志目录，按判定表把每条记录分类成 problem / advisory / 无。

**Spec:** `<home>/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`（v6：§6.1、§6.1.1、§9.2、§10）
**Part A：** `<home>/Documents/Codex/2026-10-03/wo/outputs/plans/2026-10-03-run-log.md`（已完成，HEAD `3a37f37`，354 tests）
**账本：** `<repo-root>/.superpowers/sdd/2026-10-03-evidence-tracking/progress.md`（Ruling E1–E15）

## 先解决一条控制器自己造成的矛盾（Ruling E16，已裁定）

预研的 E2 说"记 `status: "metrics-pending"`，`log-metrics` 成功后改为 `complete`"；但 Part A 的 E12 冻结了记录形状，`status` 只取 `running` / `completed` / `failed`，而 `metrics: null` 表示"尚未记录"。两者不可能同时成立。

Ruling: **以 Part A 已实现并过评审的形状为准**（E12/Part A 胜出），E2 的**意图**（把静默空指标变成显式可检测）由 `check` 的判定实现，而不是靠多一个状态值。
理由: `status` 回答"命令跑成没有"，`metrics` 回答"指标记了没有"——这是两个正交事实，塞进一个字段会让两者互相覆盖。分开放，判定表同时读它们即可。
代价: E2 里"状态值 `metrics-pending`"这一具体形式作废；若将来要单独表达"指标未记"，应加 `metrics_status` 字段而不是复用 `status`。

## 判定表（`check`，全部只读）

| 条件 | code | 归类 |
| --- | --- | --- |
| 记录缺 `status` 字段（`O_EXCL` 占位后进程即死，留下 `{}`） | `run-log-malformed` | problem |
| `status == "completed"` 且 `metrics is None` | `run-log-metrics-pending` | problem |
| `status == "completed"` 且 `metrics == {}` | `run-log-empty-metrics` | problem |
| `status == "running"` 且 `started_at` 早于阈值（默认 24h） | `run-log-stale-running` | problem |
| `git_commit` 为空 | `run-log-missing-commit` | problem |
| `git_dirty is True` | `run-log-dirty-tree` | advisory |
| `status == "failed"` | 不报 | —— |

**`failed` 不报**是有意的：失败的实验是被记录下来的合法结果，不是缺陷。闸门要防的是"跑了但没有记录"和"记了但没有指标"。

## Global Constraints

- 仓库根：`<repo-root>`
- 退出码：`0` 通过，`1` 有问题，`2` 工具自身出错（本工具 `run` 子命令的 E11 例外不适用于 `check`）。
- `check` **只读**；`log-metrics` 是写路径，走共享的原子写与不覆盖契约（`OSError` → `ValueError` → 2）。
- UTF-8 无 BOM；ASCII 标识符与注释；中文只在面向用户的消息里。
- 基线：**354 tests OK**，HEAD = `3a37f37`，工作树干净。
- 测试命令：`& "<repo-root>/tools/.venv/Scripts/python.exe" -m unittest discover -s tools/tests -t tools -v`
- 既有接口（Part A，已评审）：`run_log.new_run_id`、`git_state`、`read_config`、`run_command`、`main`；记录字段名已冻结；`cli.save_text_atomically`、`cli.Problem` / `emit` / `tool_error`。

---

### Task 2: `log-metrics` 与 `check`

**Files:**
- Modify: `tools/ccfa/run_log.py`
- Modify: `tools/tests/test_run_log.py`

**Interfaces:**
- `log_metrics(log_dir: Path, run_id: str, metrics: dict) -> dict`（未知 run_id 或指标不是对象 → `ValueError`）
- `check_runs(log_dir: Path, stale_hours: float = 24.0, now: datetime | None = None) -> tuple[list[Problem], list[Problem]]`
- `main` 增加子命令 `log-metrics <run_id> --metrics '<json>'` 与 `check [--stale-hours N]`

**要点**

- `log_metrics` **只改一条记录**：读 → 写 `metrics` → 原子写回；`status` 与 `exit_code` 不动（`status` 反映命令结果，`metrics` 反映指标，两者正交）。不接受数组/标量，只接受 JSON 对象。
- `check_runs` 遍历 `log_dir/*.json`；**单条记录损坏（JSON 解析失败或不是对象）不得让整轮检查崩掉**，应记为该条的 `run-log-malformed` 并继续。
- `now` 参数可注入，测试不依赖真实时钟。
- `started_at` 解析失败也归 `run-log-malformed`（宁可报"记录畸形"，不要静默跳过）。

- [ ] **Step 1: 写失败测试**

在 `tools/tests/test_run_log.py` 的 import 中加入 `check_runs, log_metrics`，并追加：

```python
class TestLogMetrics(BaseCase):
    def _make_run(self, exit_code=0):
        run, _ = self.runner(exit_code=exit_code)
        return run_command(["python", "train.py"], self.log_dir, self.root, runner=run)[0]

    def test_metrics_are_recorded_on_an_existing_run(self):
        run_id = self._make_run()
        record = log_metrics(self.log_dir, run_id, {"accuracy": 0.91})
        self.assertEqual(record["metrics"], {"accuracy": 0.91})
        self.assertEqual(record["status"], "completed")

    def test_status_is_not_touched_by_log_metrics(self):
        run_id = self._make_run(exit_code=3)
        record = log_metrics(self.log_dir, run_id, {"loss": 1.5})
        self.assertEqual(record["status"], "failed")

    def test_unknown_run_id_is_a_tool_error(self):
        with self.assertRaises(ValueError):
            log_metrics(self.log_dir, "20260101T000000-99", {"accuracy": 1.0})

    def test_metrics_must_be_an_object(self):
        run_id = self._make_run()
        with self.assertRaises(ValueError):
            log_metrics(self.log_dir, run_id, [1, 2, 3])


class TestCheckRuns(BaseCase):
    def _codes(self, problems):
        return sorted(p.code for p in problems)

    def _write_record(self, name, payload):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _base(self, **overrides):
        record = {
            "run_id": "20261003T142530-01",
            "status": "completed",
            "metrics": {"accuracy": 0.9},
            "git_commit": "abc1234",
            "git_dirty": False,
            "started_at": "2026-10-03T14:25:30Z",
        }
        record.update(overrides)
        return record

    def test_a_complete_record_is_clean(self):
        self._write_record("a", self._base())
        problems, advisories = check_runs(self.log_dir)
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_completed_without_metrics_is_a_problem(self):
        self._write_record("a", self._base(metrics=None))
        problems, _ = check_runs(self.log_dir)
        self.assertEqual(self._codes(problems), ["run-log-metrics-pending"])

    def test_completed_with_empty_metrics_is_a_problem(self):
        self._write_record("a", self._base(metrics={}))
        problems, _ = check_runs(self.log_dir)
        self.assertEqual(self._codes(problems), ["run-log-empty-metrics"])

    def test_a_failed_run_is_not_reported(self):
        self._write_record("a", self._base(status="failed", metrics=None, exit_code=3))
        problems, advisories = check_runs(self.log_dir)
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_missing_status_is_malformed(self):
        self._write_record("a", {})
        problems, _ = check_runs(self.log_dir)
        self.assertEqual(self._codes(problems), ["run-log-malformed"])

    def test_missing_commit_is_a_problem(self):
        self._write_record("a", self._base(git_commit=None))
        problems, _ = check_runs(self.log_dir)
        self.assertEqual(self._codes(problems), ["run-log-missing-commit"])

    def test_dirty_tree_is_only_an_advisory(self):
        self._write_record("a", self._base(git_dirty=True))
        problems, advisories = check_runs(self.log_dir)
        self.assertEqual(problems, [])
        self.assertEqual(self._codes(advisories), ["run-log-dirty-tree"])

    def test_stale_running_record_is_a_problem(self):
        self._write_record("a", self._base(status="running", metrics=None))
        problems, _ = check_runs(
            self.log_dir, now=datetime(2026, 10, 5, 14, 25, 30, tzinfo=timezone.utc)
        )
        self.assertEqual(self._codes(problems), ["run-log-stale-running"])

    def test_a_recent_running_record_is_not_reported(self):
        self._write_record("a", self._base(status="running", metrics=None))
        problems, _ = check_runs(
            self.log_dir, now=datetime(2026, 10, 3, 15, 0, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(problems, [])

    def test_unreadable_json_does_not_crash_the_whole_check(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / "broken.json").write_text("{not json", encoding="utf-8")
        self._write_record("a", self._base())
        problems, _ = check_runs(self.log_dir)
        self.assertEqual(self._codes(problems), ["run-log-malformed"])

    def test_check_does_not_write(self):
        path = self._write_record("a", self._base())
        before = path.read_bytes()
        check_runs(self.log_dir)
        self.assertEqual(path.read_bytes(), before)
```

（测试文件顶部需要补 `from datetime import datetime, timezone`。）

- [ ] **Step 2: 运行测试确认失败**

Expected: `ImportError: cannot import name 'check_runs'`。

- [ ] **Step 3: 实现**

在 `run_log.py` 中追加（`main` 之前）：

```python
def record_path(log_dir: Path, run_id: str) -> Path:
    return Path(log_dir) / f"{run_id}.json"


def log_metrics(log_dir: Path, run_id: str, metrics: dict) -> dict:
    if not isinstance(metrics, dict):
        raise ValueError("metrics 必须是 JSON 对象")
    path = record_path(log_dir, run_id)
    if not path.is_file():
        raise ValueError(f"没有这条运行记录: {run_id}")
    record = json.loads(path.read_text(encoding="utf-8"))
    record["metrics"] = metrics
    save_text_atomically(path, json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", description="运行记录")
    return record


def _parse_started(value: object) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def check_runs(log_dir: Path, stale_hours: float = 24.0, now: datetime | None = None) -> tuple[list[Problem], list[Problem]]:
    log_dir = Path(log_dir)
    reference = now or datetime.now(timezone.utc)
    problems: list[Problem] = []
    advisories: list[Problem] = []
    if not log_dir.is_dir():
        return problems, advisories
    for path in sorted(log_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(Problem("run-log-malformed", str(path), None, f"运行记录不可读: {exc}"))
            continue
        if not isinstance(record, dict) or "status" not in record:
            problems.append(Problem("run-log-malformed", str(path), None, "运行记录缺少 status 字段"))
            continue
        status = record.get("status")
        started = _parse_started(record.get("started_at"))
        if status == "running":
            if started is None:
                problems.append(Problem("run-log-malformed", str(path), None, "running 记录缺少可解析的 started_at"))
            elif (reference - started).total_seconds() > stale_hours * 3600:
                problems.append(Problem("run-log-stale-running", str(path), None, f"记录停留在 running 超过 {stale_hours:g} 小时: {record.get('run_id')}"))
            continue
        if status == "completed":
            if record.get("metrics") is None:
                problems.append(Problem("run-log-metrics-pending", str(path), None, f"运行已完成但未登记指标: {record.get('run_id')}"))
            elif record.get("metrics") == {}:
                problems.append(Problem("run-log-empty-metrics", str(path), None, f"运行指标为空对象: {record.get('run_id')}"))
        if not record.get("git_commit"):
            problems.append(Problem("run-log-missing-commit", str(path), None, f"记录缺少 git commit: {record.get('run_id')}"))
        if record.get("git_dirty") is True:
            advisories.append(Problem("run-log-dirty-tree", str(path), None, f"该运行发生在脏树上，无法仅凭 commit 复现: {record.get('run_id')}"))
    return problems, advisories
```

`main` 加两个子命令：`log-metrics <run_id> --metrics <json>`（解析 JSON，失败 → 2）、`check [--stale-hours N]`（`return emit(*check_runs(...))`）。`run_log.py` 需补 `from datetime import datetime, timezone`。

- [ ] **Step 4: 运行测试确认通过**

Expected: `Ran 369 tests`，`OK`（354 + 15：4 条 `log-metrics` + 11 条 `check`）。

判别力检查：把"completed 且 metrics 为 None"那条判定删掉，`test_completed_without_metrics_is_a_problem` 必须失败；恢复。

- [ ] **Step 5: 提交**

```powershell
git add tools/ccfa/run_log.py tools/tests/test_run_log.py
git commit -m "feat: register run metrics and detect incomplete run records"
```

---

### Task 3: 端到端回归

**Files:**
- Create: `tools/tests/test_run_log_e2e.py`

**行为规格**

| 场景 | 期望 |
| --- | --- |
| `run` 一个成功命令后立刻 `check` | `1`，code `run-log-metrics-pending`（这正是要抓的陷阱：跑完了但没记指标） |
| 再 `log-metrics` 后 `check` | `0`，`problem_count` 为 0 |
| `check` 遇到手写的 `{}` 记录 | `1`，code `run-log-malformed` |
| `log-metrics` 指向不存在的 run | `2`，stdout 为空 |

- [ ] **Step 1: 写测试**

创建 `tools/tests/test_run_log_e2e.py`：用 `subprocess.run([...], encoding="utf-8")` 调 `tools/ccfa/run_log.py`，顶层参数 `--log-dir` / `--paper-root` 放在子命令**之前**。用 `python -c "print(1)"` 当被包裹命令（不依赖外部工具）。

- [ ] **Step 2: 运行测试确认通过**

Expected: `Ran 373 tests`，`OK`（369 + 4）。

- [ ] **Step 3: 提交**

```powershell
git add tools/tests/test_run_log_e2e.py
git commit -m "test: add run-log end-to-end regression"
```

---

## 验收

期望：基线 **354** + 本计划新增 **19**（15 + 4），共 **373** 个测试通过。

逐条核对：

- **`run-log check` 能抓住"跑了但没记指标"**——这正是参考实现文档里承认的静默陷阱，现在是退出码 1 的 problem。
- **`failed` 不报**：失败的实验是合法结果，不是缺陷。
- 占位残留的空记录（`{}`）报 `run-log-malformed`，不是静默通过。
- 单条记录损坏不会让整轮检查崩掉（`test_unreadable_json_does_not_crash_the_whole_check`）。
- `check` 只读（有用例比对记录字节）。
- E16 的裁定落实：`status` 与 `metrics` 两个正交事实分开表达，判定表同时读二者。

已知边界：`check` 不做"记录数与实际运行次数"的交叉核对（那需要外部基准）；`--stale-hours` 的默认 24 小时是启发式，长任务可按需调大。

## 后续

run-log 完成后，按 spec §6.1 进入「复现与归档」计划（含 E4 推迟的 `research-version`，走 git 薄封装）→ 知识层（FTS5 + 记忆）→ 自动化与跨模型评审 → 模板库与派生流程（强制前置：先评估 `bensz-paper` / `bensz-nsfc`）。
