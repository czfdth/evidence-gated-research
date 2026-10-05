"""Run and audit an independent-model gate review."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ccfa.argument_audit import check as argument_audit_check
from ccfa.cli import Problem, emit, save_text_atomically, tool_error
from ccfa.stages import gate_for

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "blocking"]},
        "blocking": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["title", "evidence"],
                "additionalProperties": False,
            },
        },
        "checks": {
            "type": "array",
            "description": (
                "verdict=pass 时必需：每条论断给出 gate、path 与可核验证据"
                "（被引用文件里的原文片段，或该文件的 sha256）。"
            ),
            "items": {
                "type": "object",
                "properties": {
                    "gate": {"type": "string"},
                    "path": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["gate", "path", "evidence"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["verdict", "blocking", "summary"],
    "additionalProperties": False,
}

_REQUIRED_PROVENANCE_FIELDS = (
    "provider",
    "execution_model",
    "execution_provider",
    "provider_endpoint_sha256",
    "execution_endpoint_sha256",
    "provider_config_sha256",
    "codex_config_path",
)
_MODEL_FAMILIES = (
    ("deepseek", "deepseek"),
    ("qwen", "qwen"),
    ("llama", "meta"),
    ("mixtral", "mistral"),
    ("mistral", "mistral"),
    ("gemma", "google"),
    ("gemini", "google"),
    ("claude", "anthropic"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("chatglm", "zhipu"),
    ("glm", "zhipu"),
    ("phi", "microsoft"),
    ("command-r", "cohere"),
    ("internlm", "internlm"),
    ("grok", "xai"),
    ("moonshot", "moonshot"),
    ("kimi", "moonshot"),
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STDERR_LIMIT = 4000
_RAW_LAST_MESSAGE_LIMIT = 10000
_STDERR_TRUNCATION_MARKER = "...[truncated]"
_BLOCKING_QUOTE_MIN_LENGTH = 20
_TEXT_SUFFIXES = frozenset(
    {
        ".bib",
        ".cfg",
        ".csv",
        ".css",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".md",
        ".ps1",
        ".py",
        ".rst",
        ".schema",
        ".sh",
        ".tex",
        ".toml",
        ".ts",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)
_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _model_family(model: str) -> str:
    normalized = str(model).strip().casefold()
    for prefix, family in _MODEL_FAMILIES:
        if normalized.startswith(prefix):
            return family
    return "unknown"


def _family_judgement(
    model: str,
    execution_model: str,
) -> str:
    review_family = _model_family(model)
    execution_family = _model_family(execution_model)
    if review_family == "unknown" or execution_family == "unknown":
        return "unknown"
    if review_family == execution_family:
        return "same-family"
    return "cross-family"


# A reviewer below this parameter count, or one with no size information served
# from a local endpoint, may drive work but cannot on its own clear a gate.
# The rule exists because a local 30B model declared the human review ledgers
# complete while argument_audit reported 15 problems.
_ADVISORY_ONLY_PARAMETER_LIMIT = 32
_PARAMETER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*b(?![a-z0-9])", re.IGNORECASE)
_LOCAL_PROVIDER_MARKERS = ("local", "ollama", "vllm", "lmstudio", "llama.cpp")
# Blocking items that come from the deterministic gates rather than from the
# model; they are exempt from the "evidence must be a verbatim quote" rule.
_DETERMINISTIC_ITEM_PREFIXES = (
    "review-contradiction:",
    "review-advisory-only:",
    "review-unevidenced-pass:",
)


def _review_tier(model: str, provider: str | None) -> str:
    """Classify a review model as ``advisory-only`` or ``gate-capable``."""
    text = str(model).strip().casefold()
    sizes = [float(match.group(1)) for match in _PARAMETER_RE.finditer(text)]
    if sizes:
        largest = max(sizes)
        return (
            "advisory-only"
            if largest <= _ADVISORY_ONLY_PARAMETER_LIMIT
            else "gate-capable"
        )
    provider_text = (provider or "").strip().casefold()
    if any(marker in provider_text for marker in _LOCAL_PROVIDER_MARKERS):
        return "advisory-only"
    return "gate-capable"


def _bounded_text(value: object, limit: int) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + _STDERR_TRUNCATION_MARKER


def _bounded_stderr(stderr: object) -> str:
    return _bounded_text(stderr, _STDERR_LIMIT)


def _load_mode(paper_root: Path) -> str:
    path = paper_root / "ccfa.yaml"
    try:
        state = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc
    if not isinstance(state, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    venue = state.get("target_venue")
    if not isinstance(venue, dict):
        raise ValueError(f"{path} 的 target_venue 必须是映射")
    mode = venue.get("mode", "conference")
    if mode not in ("conference", "journal"):
        raise ValueError(f"未知 mode: {mode!r}")
    return mode


def _relative_input(paper_root: Path, path: Path) -> tuple[Path, str]:
    root = paper_root.resolve()
    resolved = path if path.is_absolute() else root / path
    resolved = resolved.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"评审输入逃出 paper_root: {path}") from exc
    if not resolved.is_file():
        raise ValueError(f"评审输入不存在: {relative}")
    return resolved, relative


def _sha256(path: Path) -> str:
    data = path.read_bytes()
    # Only known text suffixes are normalized, so an arbitrary binary file
    # without NUL bytes keeps its exact digest.
    if path.suffix.casefold() in _TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    digest = hashlib.sha256(data).hexdigest()
    return f"sha256:{digest}"


def _input_hashes(paper_root: Path, paths: list[Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in paths:
        resolved, relative = _relative_input(paper_root, Path(path))
        hashes[relative] = _sha256(resolved)
    return hashes


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _input_corpus(paper_root: Path, hashes: object) -> str:
    """Return the whitespace-normalized text of the recorded review inputs."""
    if not isinstance(hashes, dict):
        return ""
    texts: list[str] = []
    for relative in sorted(key for key in hashes if isinstance(key, str)):
        try:
            resolved, _relative = _relative_input(paper_root, Path(relative))
            raw = resolved.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        texts.append(_normalize_whitespace(raw))
    return "\n\n".join(texts)


def _longest_quote_length(evidence: str, corpus: str) -> int:
    """Length of the longest substring of *evidence* found in *corpus*."""
    if not evidence or not corpus:
        return 0
    matcher = difflib.SequenceMatcher(
        None,
        evidence,
        corpus,
        autojunk=False,
    )
    match = matcher.find_longest_match(0, len(evidence), 0, len(corpus))
    return match.size


def _quote_is_cited(evidence: str, corpus: str) -> bool:
    """Return True when *evidence* contains a verifiable quoted fragment.

    The common case is the normalized evidence itself appearing in the
    corpus; that is a cheap substring test. Only when the evidence carries
    extra text (for example a file prefix) do we pay for the longest common
    substring search.
    """
    if (
        len(evidence) >= _BLOCKING_QUOTE_MIN_LENGTH
        and evidence in corpus
    ):
        return True
    return (
        _longest_quote_length(evidence, corpus)
        >= _BLOCKING_QUOTE_MIN_LENGTH
    )


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None
    )


def _load_model_provenance(
    config_path: Path,
    review_provider: str | None,
) -> dict:
    """Resolve model/provider identity from Codex config, failing closed."""
    path = Path(config_path)
    try:
        raw = path.read_bytes()
        payload = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"无法读取 Codex 配置 {path}: {type(exc).__name__}") from None
    execution_model = payload.get("model")
    execution_provider = payload.get("model_provider")
    providers = payload.get("model_providers")
    if not isinstance(execution_model, str) or not execution_model.strip():
        raise ValueError("Codex 配置缺少有效 model")
    if not isinstance(execution_provider, str) or not execution_provider.strip():
        raise ValueError("Codex 配置缺少有效 model_provider")
    if not isinstance(providers, dict):
        raise ValueError("Codex 配置缺少 model_providers")
    selected_review_provider = review_provider or execution_provider

    def endpoint(name: str) -> str:
        entry = providers.get(name)
        value = entry.get("base_url") if isinstance(entry, dict) else None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Codex 配置未定义 provider {name!r} 的 base_url")
        return value.strip().rstrip("/")

    execution_endpoint = endpoint(execution_provider)
    review_endpoint = endpoint(selected_review_provider)
    return {
        "execution_model": execution_model.strip(),
        "execution_provider": execution_provider.strip(),
        "provider": selected_review_provider,
        "execution_endpoint_sha256": _sha256_text(execution_endpoint),
        "provider_endpoint_sha256": _sha256_text(review_endpoint),
        "provider_config_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "codex_config_path": str(path.resolve()),
    }


def _render_prompt(mode: str, stage: str, relative_paths: list[str]) -> str:
    """Render the review prompt from already-resolved relative paths.

    The file list is sorted and de-duplicated so the prompt -- and therefore its
    digest -- depends only on *which* files are reviewed, not on the order or
    repetition of ``--path``. ``check_review`` rebuilds the same text from the
    stored record, so any change to the gate criterion or the instruction block
    shows up as ``review-prompt-drift``.
    """
    try:
        gate = gate_for(mode, stage)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"未知 stage: {stage!r}") from exc
    lines = [
        "你是独立评审模型，只评审 gate 是否满足，不替作者改稿。",
        f"目标模式: {mode}",
        f"当前 stage: {stage}",
        f"Gate: {gate.id}",
        f"判据: {gate.criterion}",
        "",
        "待评审文件:",
    ]
    lines.extend(f"- {path}" for path in sorted(set(relative_paths)))
    if stage == "internal-review":
        lines.extend(
            [
                "",
                "本次运行就是在生成当前有效的跨模型评审报告。"
                "不要因为 reviews/cross-review.json 尚不存在，或因为历史轮次存在 "
                "blocking 记录，而把这一事实本身判为 blocking。"
                "请只依据给定的稿件和核验报告，独立判断引用、数字、图表三项核验"
                "是否通过，以及稿件是否存在实质性的科学或完整性问题。",
            ]
        )
    lines.extend(
        [
            "",
            "输出契约: 只返回 JSON 对象，字段为 verdict(pass|blocking)、"
            "blocking[{title,evidence}]、checks[{gate,path,evidence}]、summary。",
            "blocking 中每条必须给可核对的 evidence，不得凭印象断言。",
            "verdict=pass 时必须用 checks 给出正面证据：path 必须是本次待评审"
            "文件之一，evidence 必须是该文件里的原文片段或该文件的 sha256；"
            "没有可核验证据的 pass 一律按未验证处理。",
            "禁止修改任何文件；你只有只读权限，不得创建、删除或写入文件。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_prompt(paper_root: Path, stage: str, paths: list[Path]) -> str:
    """Build the independent-review prompt for the given input files."""
    paper_root = Path(paper_root).resolve()
    mode = _load_mode(paper_root)
    relative_paths = [
        _relative_input(paper_root, Path(path))[1]
        for path in paths
    ]
    return _render_prompt(mode, stage, relative_paths)


def _rebuild_prompt(
    paper_root: Path,
    stage: str,
    relative_paths: list[str],
) -> str:
    """Rebuild a stored review's prompt without requiring the inputs to exist."""
    return _render_prompt(_load_mode(Path(paper_root)), stage, relative_paths)


def _schema_text() -> str:
    return json.dumps(REVIEW_SCHEMA, ensure_ascii=False, indent=2) + "\n"


def _validate_payload(payload: object) -> dict | None:
    if not isinstance(payload, dict):
        return None
    verdict = payload.get("verdict")
    blocking = payload.get("blocking")
    summary = payload.get("summary")
    if verdict not in ("pass", "blocking"):
        return None
    if not isinstance(blocking, list) or not isinstance(summary, str):
        return None
    if verdict == "pass" and blocking:
        return None
    normalized: list[dict] = []
    for item in blocking:
        if not isinstance(item, dict):
            return None
        title = item.get("title")
        evidence = item.get("evidence")
        if not isinstance(title, str) or not isinstance(evidence, str):
            return None
        normalized.append({"title": title, "evidence": evidence})
    raw_checks = payload.get("checks", [])
    if not isinstance(raw_checks, list):
        return None
    normalized_checks: list[dict] = []
    for item in raw_checks:
        if not isinstance(item, dict):
            continue
        gate = item.get("gate")
        path = item.get("path")
        evidence = item.get("evidence")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (gate, path, evidence)
        ):
            continue
        normalized_checks.append(
            {
                "gate": gate.strip(),
                "path": path.strip(),
                "evidence": evidence.strip(),
            }
        )
    return {
        "verdict": verdict,
        "blocking": normalized,
        "checks": normalized_checks,
        "summary": summary,
    }


def _parse_payload(raw: str) -> object | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.findall(
        r"```(?:json)?\s*(.*?)\s*```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if len(fenced) != 1:
        return None
    try:
        return json.loads(fenced[0])
    except json.JSONDecodeError:
        return None


def _record_paths(out_dir: Path) -> tuple[Path, Path, Path, Path]:
    return (
        out_dir / "cross-review.json",
        out_dir / "cross-review.md",
        out_dir / "cross-review.schema.json",
        out_dir / "cross-review-last-message.json",
    )


def _resolve_out_dir(paper_root: Path, out_dir: Path | None) -> Path:
    output_dir = Path(out_dir) if out_dir else paper_root / "reviews"
    if not output_dir.is_absolute():
        output_dir = paper_root / output_dir
    return output_dir


def _render_markdown(record: dict) -> str:
    lines = [
        "# 跨模型评审记录",
        "",
        f"- model: {record['model']}",
        f"- model_verdict: {record.get('model_verdict', record['verdict'])}",
        f"- family_judgement: {record['family_judgement']}",
        f"- verdict: {record['verdict']}",
        f"- started_at: {record['started_at']}",
        f"- duration_s: {record['duration_s']}",
        "",
        "## Summary",
        "",
        str(record.get("summary", "")),
        "",
        "## Blocking",
        "",
    ]
    blocking = record.get("blocking", [])
    if not blocking:
        lines.append("- none")
    else:
        for item in blocking:
            lines.append(f"- {item['title']}: {item['evidence']}")
    lines.extend(["", "## Inputs", ""])
    for path, digest in sorted(record.get("input_hashes", {}).items()):
        lines.append(f"- {path}: {digest}")
    return "\n".join(lines) + "\n"


def _write_records(
    record: dict,
    json_path: Path,
    markdown_path: Path,
) -> None:
    record["record_path"] = str(json_path)
    save_text_atomically(
        json_path,
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="评审记录",
    )
    save_text_atomically(
        markdown_path,
        _render_markdown(record),
        description="评审记录",
    )


def _resolve_codex_executable() -> str:
    """Locate the Codex CLI, including installs missing from the PATH.

    The desktop app ships versioned binaries under ``%LOCALAPPDATA%`` and does
    not always export that directory, so a plain terminal would otherwise fail
    with "无法运行 codex exec". ``CCFA_CODEX_EXECUTABLE`` overrides the lookup.
    """
    override = os.environ.get("CCFA_CODEX_EXECUTABLE", "").strip()
    if override:
        return override
    found = shutil.which("codex")
    if found:
        return found
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    try:
        candidates = [
            path for path in root.glob("*/codex.exe") if path.is_file()
        ]
    except OSError:
        candidates = []
    if candidates:
        newest = max(candidates, key=lambda path: path.stat().st_mtime)
        return str(newest)
    return "codex"


def _default_runner(argv, cwd, timeout, prompt):
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(cwd),
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"codex exec 超时: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"无法运行 codex exec: {exc}") from exc
    return int(completed.returncode), completed.stderr or ""


def _unevidenced_pass_items(
    paper_root: Path,
    checks: list[dict],
    hashes: dict[str, str],
) -> list[dict]:
    """Blocking items for ``pass`` claims that carry no verifiable evidence.

    A ``pass`` is only accepted when every claim names one of the review inputs
    and quotes that file (or gives its sha256). An unevidenced pass is treated
    as unverified rather than trusted.
    """
    if not checks:
        return [
            {
                "title": "review-unevidenced-pass: no checks",
                "evidence": (
                    "verdict=pass 但没有提供任何 checks[gate,path,evidence]；"
                    "无证据的 pass 按未验证处理"
                ),
            }
        ]
    items: list[dict] = []
    for index, check in enumerate(checks):
        relative = str(check.get("path", "")).strip().replace("\\", "/")
        if relative not in hashes:
            items.append(
                {
                    "title": f"review-unevidenced-pass: checks[{index}]",
                    "evidence": f"path={relative!r} 不是本次评审的输入文件",
                }
            )
            continue
        try:
            resolved, _relative = _relative_input(paper_root, Path(relative))
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as exc:
            items.append(
                {
                    "title": f"review-unevidenced-pass: checks[{index}]",
                    "evidence": f"{relative}: 无法读取该文件: {exc}",
                }
            )
            continue
        evidence = _normalize_whitespace(str(check.get("evidence", "")))
        corpus = _normalize_whitespace(text)
        if _quote_is_cited(evidence, corpus) or evidence in hashes[relative]:
            continue
        items.append(
            {
                "title": f"review-unevidenced-pass: checks[{index}]",
                "evidence": (
                    f"{relative}: evidence 既不是该文件中 ≥"
                    f"{_BLOCKING_QUOTE_MIN_LENGTH} 字符的原文，"
                    "也不是该文件哈希"
                ),
            }
        )
    return items


def _deterministic_contradictions(paper_root: Path) -> list[dict]:
    """Blocking items where a claimed ``pass`` contradicts machine evidence.

    A review model may drive work but never acquit the paper. If it returns
    ``pass`` while a deterministic gate still reports problems, the record is
    downgraded to blocking instead of quietly turning the gate green. This is
    the mechanical guard against the local reviewer that declared the human
    review ledgers complete while ``argument_audit`` reported 15 problems.
    """
    try:
        problems, _advisories = argument_audit_check(Path(paper_root))
    except Exception as exc:  # a probe must never crash the review
        return [
            {
                "title": "review-contradiction: deterministic gate failed to run",
                "evidence": (
                    f"argument_audit raised {type(exc).__name__}: {exc}"
                ),
            }
        ]
    blockers: list[dict] = []
    for problem in problems:
        location = (
            f"{problem.path}:{problem.line}"
            if problem.line is not None
            else str(problem.path)
        )
        blockers.append(
            {
                "title": f"review-contradiction: {problem.code}",
                "evidence": f"{location}: {problem.message}",
            }
        )
    return blockers


def run_review(
    paper_root: Path,
    *,
    model: str | None = None,
    provider: str | None = None,
    reasoning_effort: str | None = None,
    allow_same_family: bool = False,
    override_reason: str | None = None,
    stage: str,
    paths: list[Path],
    runner=None,
    timeout: float = 600,
    out_dir: Path | None = None,
    force: bool = False,
    codex_config: Path | None = None,
    contradiction_probe=None,
) -> dict:
    """Run codex exec and write a structured review record."""
    paper_root = Path(paper_root).resolve()
    if not paths:
        raise ValueError(
            "评审输入不能为空：跨模型评审至少要有一个 --path"
        )
    if not isinstance(model, str) or not model.strip():
        raise ValueError(
            "跨模型评审必须显式提供 --model；"
            "工作流不再替调用方选择评审模型"
        )
    model = model.strip()
    if reasoning_effort is not None:
        reasoning_effort = str(reasoning_effort).strip().casefold()
        if reasoning_effort not in _REASONING_EFFORTS:
            raise ValueError(
                f"reasoning_effort 非法: {reasoning_effort!r}，"
                f"应为 {' / '.join(_REASONING_EFFORTS)}"
            )
    provenance = _load_model_provenance(
        codex_config or (Path.home() / ".codex" / "config.toml"),
        provider,
    )
    execution_model = provenance["execution_model"]
    provider = provenance["provider"]
    family = _family_judgement(model, execution_model)
    if family != "cross-family" and not allow_same_family:
        raise ValueError(
            "评审模型与执行模型不是跨族；请用 --model 选择不同家族的"
            "评审模型（必要时用 --provider 指向其 provider），"
            "或显式传 --allow-same-family"
        )
    if allow_same_family:
        if (
            not isinstance(override_reason, str)
            or len(override_reason.strip()) < 20
        ):
            raise ValueError(
                "同族 override 必须提供 --override-reason，且至少 20 字符，"
                "说明为什么当前没有真实跨族评审"
            )
        override_reason = override_reason.strip()
    else:
        override_reason = None
    output_dir = _resolve_out_dir(paper_root, out_dir)
    json_path, markdown_path, schema_path, last_message_path = _record_paths(
        output_dir
    )
    if not force and (json_path.exists() or markdown_path.exists()):
        raise ValueError(f"评审记录已存在，拒绝覆盖: {json_path}")

    input_hashes = _input_hashes(paper_root, paths)
    prompt = build_prompt(paper_root, stage, paths)
    prompt_sha256 = _sha256_text(prompt)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    save_text_atomically(
        schema_path,
        _schema_text(),
        description="评审 schema",
    )
    last_message_path.unlink(missing_ok=True)

    argv = [
        _resolve_codex_executable(),
        "exec",
        *(["-c", f"model_provider={provider}"] if provider else []),
        *(
            ["-c", f"model_reasoning_effort={reasoning_effort}"]
            if reasoning_effort
            else []
        ),
        "-m",
        model,
        "-s",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
        "-C",
        str(paper_root),
        "--output-schema",
        str(schema_path),
        "-o",
        str(last_message_path),
        "-",
    ]
    run = runner or _default_runner
    started_at = _now_iso()
    started = time.monotonic()
    try:
        exit_code, stderr = run(argv, paper_root, timeout, prompt)
    except OSError as exc:
        raise ValueError(f"无法运行 codex exec: {exc}") from exc
    duration_s = round(time.monotonic() - started, 6)
    if exit_code != 0:
        failure = {
            "status": "failed",
            "model": model,
            "provider": provider,
            **provenance,
            "execution_model": execution_model,
            "reasoning_effort": reasoning_effort,
            "family_judgement": family,
            "family_override": allow_same_family,
            "family_override_reason": override_reason,
            "verdict": None,
            "blocking": [],
            "summary": "codex exec failed",
            "input_hashes": input_hashes,
            "prompt_sha256": prompt_sha256,
            "started_at": started_at,
            "duration_s": duration_s,
            "stage": stage,
            "exit_code": int(exit_code),
            "stderr": _bounded_stderr(stderr),
        }
        _write_records(failure, json_path, markdown_path)
        raise ValueError(
            f"codex exec 失败 (exit {exit_code}): {str(stderr)[:500]}"
        )

    raw_last_message = ""
    if last_message_path.is_file():
        raw_last_message = last_message_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    payload = _parse_payload(raw_last_message)
    normalized = _validate_payload(payload)
    if normalized is None:
        malformed = {
            "status": "malformed",
            "model": model,
            "provider": provider,
            **provenance,
            "execution_model": execution_model,
            "reasoning_effort": reasoning_effort,
            "family_judgement": family,
            "family_override": allow_same_family,
            "family_override_reason": override_reason,
            "verdict": "malformed",
            "blocking": [],
            "summary": "review output missing or malformed",
            "input_hashes": input_hashes,
            "prompt_sha256": prompt_sha256,
            "started_at": started_at,
            "duration_s": duration_s,
            "stage": stage,
            "exit_code": 0,
            "stderr": _bounded_stderr(stderr),
            "raw_last_message": _bounded_text(
                raw_last_message,
                _RAW_LAST_MESSAGE_LIMIT,
            ),
        }
        _write_records(malformed, json_path, markdown_path)
        return malformed

    model_verdict = normalized["verdict"]
    effective_verdict = model_verdict
    effective_summary = normalized["summary"]
    if family != "cross-family":
        if model_verdict == "pass":
            effective_verdict = "blocking"
            effective_summary = (
                "同族评审不能开释（can drive, never acquit）。"
                "模型返回 pass，但当前评审记录不能作为 gate pass。 "
                + normalized["summary"]
            )
        else:
            effective_summary = (
                "同族评审不能开释（can drive, never acquit）。 "
                + normalized["summary"]
            )

    review_tier = _review_tier(model, provider)
    contradictions: list[dict] = []
    if effective_verdict == "pass":
        if review_tier == "advisory-only":
            contradictions.append(
                {
                    "title": f"review-advisory-only: {model}",
                    "evidence": (
                        f"review_tier=advisory-only, provider={provider!r}: "
                        "本地/小模型评审不得单独开释 review_cleared"
                    ),
                }
            )
        probe = contradiction_probe or _deterministic_contradictions
        contradictions.extend(probe(paper_root))
        contradictions.extend(
            _unevidenced_pass_items(
                paper_root,
                normalized["checks"],
                input_hashes,
            )
        )
        if contradictions:
            effective_verdict = "blocking"
            effective_summary = (
                f"模型返回 pass，但被 {len(contradictions)} 项确定性证据否决"
                "（review-contradiction / review-advisory-only）："
                "模型不得开释确定性 gate。 "
                + effective_summary
            )

    record = {
        "status": "complete",
        "model": model,
        "model_verdict": model_verdict,
        "provider": provider,
        **provenance,
        "execution_model": execution_model,
        "reasoning_effort": reasoning_effort,
        "family_judgement": family,
        "family_override": allow_same_family,
        "family_override_reason": override_reason,
        "review_tier": review_tier,
        "verdict": effective_verdict,
        "blocking": [*normalized["blocking"], *contradictions],
        "deterministic_contradiction": bool(contradictions),
        "summary": effective_summary,
        "input_hashes": input_hashes,
        "prompt_sha256": prompt_sha256,
        "started_at": started_at,
        "duration_s": duration_s,
        "stage": stage,
        "exit_code": 0,
        "stderr": _bounded_stderr(stderr),
    }
    _write_records(record, json_path, markdown_path)
    return record


def _review_record_path(paper_root: Path, out_dir: Path | None = None) -> Path:
    return _resolve_out_dir(Path(paper_root), out_dir) / "cross-review.json"


def check_review(
    paper_root: Path,
    out_dir: Path | None = None,
    *,
    allow_same_family: bool = False,
    strict_cross_family: bool = False,
    codex_config: Path | None = None,
) -> list[Problem]:
    """Audit the stored review record against current inputs."""
    paper_root = Path(paper_root).resolve()
    path = _review_record_path(paper_root, out_dir)
    if not path.is_file():
        return [
            Problem(
                "review-missing",
                str(path),
                None,
                "缺少跨模型评审记录",
            )
        ]
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [
            Problem(
                "review-malformed",
                str(path),
                None,
                f"评审记录不可读: {exc}",
            )
        ]
    if not isinstance(record, dict):
        return [
            Problem(
                "review-malformed",
                str(path),
                None,
                "评审记录顶层必须是对象",
            )
        ]
    try:
        payload = _validate_payload(record)
    except (KeyError, TypeError):
        payload = None
    if payload is None or record.get("status") != "complete":
        return [
            Problem(
                "review-malformed",
                str(path),
                None,
                "评审记录 verdict/blocking/summary 不合 schema",
            )
        ]

    problems: list[Problem] = []
    model = record.get("model")
    execution_model = record.get("execution_model")
    family_recomputable = isinstance(model, str) and isinstance(execution_model, str)
    computed_family = (
        _family_judgement(model, execution_model)
        if family_recomputable
        else "unknown"
    )
    stored_family = record.get("family_judgement")
    model_verdict = record.get("model_verdict")
    contradiction_downgrade = record.get("deterministic_contradiction") is True
    if model_verdict is not None:
        verdict_is_consistent = model_verdict == payload["verdict"] or (
            model_verdict == "pass"
            and payload["verdict"] == "blocking"
            and (computed_family != "cross-family" or contradiction_downgrade)
        )
        if model_verdict not in ("pass", "blocking") or not verdict_is_consistent:
            problems.append(
                Problem(
                    "review-record-invalid",
                    str(path),
                    None,
                    "评审记录 model_verdict="
                    f"{model_verdict!r} 与 effective verdict="
                    f"{payload['verdict']!r} 不一致；"
                    "只有同族/未知族或确定性矛盾的 pass→blocking "
                    "降级是允许的",
                )
            )
    provenance_complete = (
        isinstance(stored_family, str)
        and stored_family in {"same-family", "cross-family", "unknown"}
        and isinstance(record.get("family_override"), bool)
        and all(
            isinstance(record.get(field), str) and record.get(field).strip()
            for field in _REQUIRED_PROVENANCE_FIELDS
        )
        and _is_sha256(record.get("provider_endpoint_sha256"))
        and _is_sha256(record.get("execution_endpoint_sha256"))
        and _is_sha256(record.get("provider_config_sha256"))
    )
    if not provenance_complete:
        problems.append(
            Problem(
                "review-provenance-incomplete",
                str(path),
                None,
                "评审记录缺少完整 provider provenance"
                "（provider/execution_model/execution_provider/endpoint hashes/"
                "provider_config_sha256/codex_config_path/family_override）",
            )
        )
    current_provenance: dict | None = None
    config_path = codex_config or record.get("codex_config_path")
    if (
        provenance_complete
        and isinstance(config_path, (str, Path))
        and str(config_path).strip()
    ):
        try:
            current_provenance = _load_model_provenance(
                Path(config_path),
                record.get("provider") if isinstance(record.get("provider"), str) else None,
            )
        except ValueError as exc:
            problems.append(
                Problem(
                    "review-provider-config-unavailable",
                    str(path),
                    None,
                    f"无法验证当前 provider 配置: {exc}",
                )
            )
        else:
            for field in (
                "execution_model",
                "execution_provider",
                "provider",
                "execution_endpoint_sha256",
                "provider_endpoint_sha256",
                "provider_config_sha256",
            ):
                if record.get(field) != current_provenance.get(field):
                    problems.append(
                        Problem(
                            "review-provider-config-drift",
                            str(path),
                            None,
                            f"评审 provenance 字段 {field} 与当前 Codex 配置不一致；必须重跑评审",
                        )
                    )
                    break
    if (
        family_recomputable
        and
        isinstance(stored_family, str)
        and stored_family != computed_family
    ):
        problems.append(
            Problem(
                "review-family-mismatch",
                str(path),
                None,
                "评审记录的 family_judgement="
                f"{stored_family!r} 与 model/execution_model 重算值 "
                f"{computed_family!r} 不一致",
            )
        )
    family_override = record.get("family_override") is True
    if family_override:
        override_reason = record.get("family_override_reason")
        if (
            not isinstance(override_reason, str)
            or len(override_reason.strip()) < 20
        ):
            problems.append(
                Problem(
                    "review-override-reason-missing",
                    str(path),
                    None,
                    "family_override=true 但缺少 ≥20 字符的 "
                    "family_override_reason",
                )
            )
        elif strict_cross_family:
            problems.append(
                Problem(
                    "review-family-override",
                    str(path),
                    None,
                    "记录使用的是同族 override，不是真正跨族评审",
                )
            )
    same_family_gate = computed_family != "cross-family"
    if same_family_gate and not (family_override or allow_same_family):
        detail = (
            "评审模型不是跨族；"
            f"family_judgement={computed_family!r}，"
            "且没有显式 allow-same-family override"
        )
        problems.append(
            Problem(
                "review-same-family",
                str(path),
                None,
                detail,
            )
        )
    hashes = record.get("input_hashes")
    hashes_usable = isinstance(hashes, dict) and bool(hashes)
    if not isinstance(hashes, dict):
        problems.append(
            Problem(
                "review-malformed",
                str(path),
                None,
                "评审记录缺少 input_hashes",
            )
        )
    elif not hashes:
        problems.append(
            Problem(
                "review-malformed",
                str(path),
                None,
                "评审记录的 input_hashes 为空：不存在没有评审输入的跨模型评审",
            )
        )
    else:
        for relative, expected in hashes.items():
            if not isinstance(relative, str) or not relative:
                hashes_usable = False
                problems.append(
                    Problem(
                        "review-record-invalid",
                        str(path),
                        None,
                        f"评审输入路径非法: {relative!r}",
                    )
                )
                continue
            root = paper_root.resolve()
            input_path = (paper_root / relative).resolve()
            try:
                input_path.relative_to(root)
            except ValueError:
                hashes_usable = False
                problems.append(
                    Problem(
                        "review-record-invalid",
                        str(path),
                        None,
                        f"评审输入路径逃出 paper_root: {relative!r}",
                    )
                )
                continue
            try:
                actual = _sha256(input_path)
            except OSError:
                problems.append(
                    Problem(
                        "review-stale",
                        str(path),
                        None,
                        f"评审输入不存在: {relative}",
                    )
                )
                continue
            if actual != expected:
                problems.append(
                    Problem(
                        "review-stale",
                        str(path),
                        None,
                        f"评审输入已变化: {relative}",
                    )
                )
    stage = record.get("stage")
    expected_prompt_hash = record.get("prompt_sha256")
    if hashes_usable:
        if not isinstance(stage, str) or not stage.strip():
            problems.append(
                Problem(
                    "review-prompt-unknown",
                    str(path),
                    None,
                    "评审记录缺少 stage，无法重建评审指令来核对 prompt_sha256",
                )
            )
        else:
            try:
                rebuilt = _rebuild_prompt(
                    paper_root,
                    stage,
                    [key for key in hashes if isinstance(key, str)],
                )
            except (OSError, ValueError) as exc:
                problems.append(
                    Problem(
                        "review-prompt-unknown",
                        str(path),
                        None,
                        f"无法重建该评审的指令以核对 prompt_sha256: {exc}",
                    )
                )
            else:
                actual_prompt_hash = _sha256_text(rebuilt)
                if (
                    not isinstance(expected_prompt_hash, str)
                    or not expected_prompt_hash.strip()
                ):
                    problems.append(
                        Problem(
                            "review-prompt-unknown",
                            str(path),
                            None,
                            "评审记录缺少 prompt_sha256：无法证明它是在"
                            "当前评审指令（gate 判据与 stage 提示）下产生的",
                        )
                    )
                elif expected_prompt_hash != actual_prompt_hash:
                    problems.append(
                        Problem(
                            "review-prompt-drift",
                            str(path),
                            None,
                            "评审指令已变化"
                            f"（记录 {expected_prompt_hash}，"
                            f"当前 {actual_prompt_hash}）；必须重跑评审",
                        )
                    )
    same_family_cannot_acquit = (
        computed_family != "cross-family" and payload["verdict"] == "pass"
    )
    if payload["verdict"] == "blocking" or same_family_cannot_acquit:
        summary = payload["summary"] or "评审报告包含 blocking 项"
        if same_family_cannot_acquit:
            summary = (
                "同族评审不能开释（can drive, never acquit）："
                f"重算 family_judgement={computed_family!r}，"
                "记录不能作为 gate pass。"
            )
        problems.append(
            Problem(
                "review-blocking",
                str(path),
                None,
                summary,
            )
        )
        corpus = _input_corpus(paper_root, hashes)
        for index, item in enumerate(payload["blocking"]):
            if item["title"].startswith(_DETERMINISTIC_ITEM_PREFIXES):
                # These items are copied from the deterministic gates, not
                # produced by the model, so the "evidence must be a verbatim
                # quote from the review inputs" rule does not apply.
                continue
            evidence = _normalize_whitespace(item["evidence"])
            if not _quote_is_cited(evidence, corpus):
                problems.append(
                    Problem(
                        "review-uncited-blocking",
                        str(path),
                        None,
                        f"blocking[{index}] {item['title']!r} 的 evidence "
                        f"没有 ≥{_BLOCKING_QUOTE_MIN_LENGTH} 字符的引文"
                        "逐字出现在评审输入文件中",
                    )
                )
    if (
        record.get("review_tier") == "advisory-only"
        and payload["verdict"] == "pass"
    ):
        problems.append(
            Problem(
                "review-advisory-only",
                str(path),
                None,
                "评审模型被判定为 advisory-only，不能单独支撑 "
                "review_cleared；需要 gate-capable 的评审模型",
            )
        )
    if payload["verdict"] == "pass":
        contradictions = _deterministic_contradictions(paper_root)
        if contradictions:
            problems.append(
                Problem(
                    "review-contradiction",
                    str(path),
                    None,
                    "评审记录返回 pass，但确定性 gate 仍报告 "
                    f"{len(contradictions)} 项问题；"
                    "模型不得开释确定性 gate（假 pass）",
                )
            )
    return problems


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "用独立模型执行 gate 评审。执行模型和 provider 从 Codex 配置"
            "解析并写入 provenance；默认拒绝写入同族 pass，除非显式 "
            "--allow-same-family。"
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="运行一次独立模型评审")
    run.add_argument("--paper-root", default=".")
    run.add_argument("--stage", required=True)
    run.add_argument("--path", action="append", required=True)
    run.add_argument(
        "--model",
        required=True,
        help="显式指定独立评审模型；不提供默认值",
    )
    run.add_argument("--provider")
    run.add_argument(
        "--reasoning-effort",
        choices=_REASONING_EFFORTS,
        help="传给 codex exec 的 model_reasoning_effort；非 thinking 本地模型用 none",
    )
    run.add_argument("--allow-same-family", action="store_true")
    run.add_argument(
        "--override-reason",
        help="同族 override 的原因，至少 20 字符；会写入评审记录",
    )
    run.add_argument("--timeout", type=float, default=600)
    run.add_argument("--out-dir")
    run.add_argument("--force", action="store_true")
    run.add_argument(
        "--codex-config",
        help="Codex config.toml 路径；默认读取用户目录，用于解析真实执行模型和 provider",
    )

    check = subparsers.add_parser("check", help="审计已有评审记录")
    check.add_argument("--paper-root", default=".")
    check.add_argument("--out-dir", default="reviews")
    check.add_argument("--allow-same-family", action="store_true")
    check.add_argument(
        "--codex-config",
        help="Codex config.toml 路径；提供后会检查评审 provenance 是否已随配置变化而 stale",
    )
    check.add_argument(
        "--strict-cross-family",
        action="store_true",
        help="严格模式：任何同族 override 都报 review-family-override",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "check":
            return emit(
                check_review(
                    Path(args.paper_root),
                    out_dir=Path(args.out_dir),
                    allow_same_family=args.allow_same_family,
                    strict_cross_family=args.strict_cross_family,
                    codex_config=Path(args.codex_config) if args.codex_config else None,
                )
            )
        record = run_review(
            Path(args.paper_root),
            model=args.model,
            provider=args.provider,
            reasoning_effort=args.reasoning_effort,
            allow_same_family=args.allow_same_family,
            override_reason=args.override_reason,
            stage=args.stage,
            paths=[Path(item) for item in args.path],
            timeout=args.timeout,
            out_dir=Path(args.out_dir) if args.out_dir else None,
            force=args.force,
            codex_config=Path(args.codex_config) if args.codex_config else None,
        )
        print(json.dumps(record, ensure_ascii=False, sort_keys=True))
        if record.get("verdict") == "pass":
            return 0
        return 1
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
