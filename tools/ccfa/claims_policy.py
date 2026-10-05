"""Validate claims policy and classify numeric claims by protected section."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ccfa.cli import Problem, save_text_atomically
from ccfa.dataval import find_tags, find_untagged
from ccfa.texcomment import strip_comment
from ccfa.texscan import iter_tex_files

POLICY_RELATIVE_PATH = Path("data") / "claims.yaml"
REPORT_JSON_RELATIVE_PATH = Path("submission") / "claims-coverage.json"
REPORT_MD_RELATIVE_PATH = Path("submission") / "claims-coverage.md"

_WAIVER_REQUIRED_FIELDS = frozenset(
    {"file", "line_text", "reason", "date", "author"}
)
_WAIVER_OPTIONAL_FIELDS = frozenset({"line"})
_WAIVER_FIELDS = _WAIVER_REQUIRED_FIELDS | _WAIVER_OPTIONAL_FIELDS
_POLICY_FIELDS = frozenset({"version", "protected_sections", "waivers"})
_HEADING = re.compile(r"\\(section|subsection)\*?\s*\{([^{}]*)\}")
_ABSTRACT_BEGIN = re.compile(r"\\begin\{abstract\}")
_ABSTRACT_END = re.compile(r"\\end\{abstract\}")


@dataclass(frozen=True)
class Waiver:
    file: str
    line_text: str
    reason: str
    date: str
    author: str
    line: int | None = None


@dataclass(frozen=True)
class ClaimsPolicy:
    protected_sections: tuple[str, ...]
    waivers: tuple[Waiver, ...]


def _normalise_section(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _normalise_file(value: str) -> str:
    normalised = value.replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised[2:]
    return normalised


def _normalise_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _invalid(path: Path, line: int | None, message: str) -> Problem:
    return Problem("claims-policy-invalid", str(path), line, message)


def _mapping_node_line(node: Any, key: str | None = None) -> int | None:
    if node is None:
        return None
    target = node
    if key is not None and getattr(node, "value", None) is not None:
        for key_node, value_node in node.value:
            if getattr(key_node, "value", None) == key:
                target = value_node
                break
    mark = getattr(target, "start_mark", None)
    return None if mark is None else mark.line + 1


def _waiver_node_line(
    sequence_node: Any,
    index: int,
    field: str | None = None,
) -> int | None:
    if sequence_node is None or not getattr(sequence_node, "value", None):
        return None
    if index >= len(sequence_node.value):
        return None
    return _mapping_node_line(sequence_node.value[index], field)


def _read_yaml(path: Path) -> tuple[Any, Any, list[Problem]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, None, [_invalid(path, None, f"无法读取 claims policy: {exc}")]
    try:
        payload = yaml.safe_load(text)
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        return None, None, [_invalid(path, None, f"claims policy 不是有效 YAML: {exc}")]
    return payload, node, []


def load_policy(paper_root: Path) -> tuple[ClaimsPolicy | None, list[Problem]]:
    """Load and validate ``data/claims.yaml``.

    A missing file is not an error: callers must report that coverage was not
    verified. Malformed policy entries are returned as problems while valid
    entries in the same file remain usable.
    """
    policy_path = Path(paper_root) / POLICY_RELATIVE_PATH
    if not policy_path.is_file():
        return None, []

    payload, node, read_problems = _read_yaml(policy_path)
    if read_problems:
        return None, read_problems
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) for key in payload
    ):
        return None, [
            _invalid(
                policy_path,
                _mapping_node_line(node),
                "claims policy 顶层必须是映射",
            )
        ]

    fields = set(payload)
    if fields != _POLICY_FIELDS:
        missing = sorted(_POLICY_FIELDS - fields)
        extra = sorted(fields - _POLICY_FIELDS)
        details = []
        if missing:
            details.append("缺少字段 " + ", ".join(missing))
        if extra:
            details.append("未知字段 " + ", ".join(extra))
        return None, [
            _invalid(
                policy_path,
                _mapping_node_line(node),
                "claims policy 字段无效: " + "; ".join(details),
            )
        ]

    version = payload["version"]
    if type(version) is not int or version != 1:
        return None, [
            _invalid(
                policy_path,
                _mapping_node_line(node, "version"),
                "claims policy version 必须是整数 1",
            )
        ]

    raw_sections = payload["protected_sections"]
    if not isinstance(raw_sections, list) or not raw_sections:
        return None, [
            _invalid(
                policy_path,
                _mapping_node_line(node, "protected_sections"),
                "protected_sections 必须是非空字符串数组",
            )
        ]

    protected_sections: list[str] = []
    for index, raw_section in enumerate(raw_sections):
        if type(raw_section) is not str or not raw_section.strip():
            return None, [
                _invalid(
                    policy_path,
                    _mapping_node_line(node, "protected_sections"),
                    f"protected_sections[{index}] 必须是非空字符串",
                )
            ]
        normalised = _normalise_section(raw_section)
        if normalised not in protected_sections:
            protected_sections.append(normalised)

    raw_waivers = payload["waivers"]
    if not isinstance(raw_waivers, list):
        return None, [
            _invalid(
                policy_path,
                _mapping_node_line(node, "waivers"),
                "waivers 必须是数组",
            )
        ]

    sequence_node = None
    if getattr(node, "value", None) is not None:
        for key_node, value_node in node.value:
            if getattr(key_node, "value", None) == "waivers":
                sequence_node = value_node
                break

    waivers: list[Waiver] = []
    problems: list[Problem] = []
    for index, raw_waiver in enumerate(raw_waivers):
        line = _waiver_node_line(sequence_node, index)
        if not isinstance(raw_waiver, dict):
            problems.append(
                _invalid(policy_path, line, f"waivers[{index}] 必须是映射")
            )
            continue
        if not all(isinstance(key, str) for key in raw_waiver):
            problems.append(
                _invalid(policy_path, line, f"waivers[{index}] 字段名必须是字符串")
            )
            continue
        fields = set(raw_waiver)
        missing = sorted(_WAIVER_REQUIRED_FIELDS - fields)
        extra = sorted(fields - _WAIVER_FIELDS)
        if missing or extra:
            details = []
            if missing:
                details.append("缺少 " + ", ".join(missing))
            if extra:
                details.append("未知 " + ", ".join(extra))
            problems.append(
                _invalid(
                    policy_path,
                    line,
                    f"waivers[{index}] 字段无效: " + "; ".join(details),
                )
            )
            continue

        invalid_field = None
        for field in sorted(_WAIVER_REQUIRED_FIELDS):
            if type(raw_waiver[field]) is not str:
                invalid_field = field
                break
        if invalid_field is not None:
            problems.append(
                _invalid(
                    policy_path,
                    _waiver_node_line(sequence_node, index, invalid_field),
                    f"waivers[{index}].{invalid_field} 必须是字符串",
                )
            )
            continue

        if "line" in raw_waiver:
            line_value = raw_waiver["line"]
            if type(line_value) is not int or line_value < 1:
                problems.append(
                    _invalid(
                        policy_path,
                        _waiver_node_line(sequence_node, index, "line"),
                        f"waivers[{index}].line 必须是 1 起的整数行号",
                    )
                )
                continue

        if not all(
            raw_waiver[field].strip()
            for field in ("file", "line_text", "reason", "date", "author")
        ):
            problems.append(
                _invalid(
                    policy_path,
                    line,
                    f"waivers[{index}] 字段不能为空",
                )
            )
            continue

        try:
            dt.date.fromisoformat(raw_waiver["date"])
        except ValueError:
            problems.append(
                _invalid(
                    policy_path,
                    _waiver_node_line(sequence_node, index, "date"),
                    f"waivers[{index}].date 必须是 YYYY-MM-DD",
                )
            )
            continue

        waivers.append(
            Waiver(
                _normalise_file(raw_waiver["file"].strip()),
                _normalise_line(raw_waiver["line_text"]),
                raw_waiver["reason"].strip(),
                raw_waiver["date"].strip(),
                raw_waiver["author"].strip(),
                raw_waiver.get("line"),
            )
        )

    return ClaimsPolicy(tuple(protected_sections), tuple(waivers)), problems


def _protected_lines(
    path: Path,
    policy: ClaimsPolicy,
) -> tuple[set[int], set[str]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return set(), set()

    protected_sections = set(policy.protected_sections)
    protected: set[int] = set()
    matched_sections: set[str] = set()
    in_abstract = False
    protected_section_level = 0
    for number, raw_line in enumerate(lines, start=1):
        line = strip_comment(raw_line)
        if _ABSTRACT_BEGIN.search(line):
            in_abstract = True
            matched_sections.add("abstract")
        if _ABSTRACT_END.search(line):
            in_abstract = False
            continue

        heading = _HEADING.search(line)
        if heading is not None:
            kind = heading.group(1)
            title = _normalise_section(heading.group(2))
            matches_policy = title in protected_sections
            if matches_policy:
                matched_sections.add(title)
            if kind == "section":
                protected_section_level = 1 if matches_policy else 0
            elif protected_section_level == 0:
                protected_section_level = 2 if matches_policy else 0
            elif protected_section_level == 2:
                protected_section_level = 2 if matches_policy else 0

        if in_abstract or protected_section_level:
            protected.add(number)
    return protected, matched_sections


def _path_relative_to(path: str | Path, paper_root: Path) -> str:
    root = Path(paper_root).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        rooted = root / candidate
        candidate = rooted if rooted.exists() else candidate.resolve()
    else:
        candidate = candidate.resolve()
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _report_path(path: str | Path, paper_root: Path) -> str:
    """Return a stable repository-relative path for machine-readable output."""
    return _path_relative_to(path, paper_root)


def _matching_waiver(
    item_path: str,
    item_line: int,
    item_text: str,
    policy: ClaimsPolicy,
    paper_root: Path,
) -> tuple[Waiver, int] | None:
    relative = _path_relative_to(item_path, paper_root)
    line_text = _normalise_line(item_text)
    for index, waiver in enumerate(policy.waivers):
        if _normalise_file(waiver.file) != relative:
            continue
        if _normalise_line(waiver.line_text) != line_text:
            continue
        if waiver.line is not None and waiver.line != item_line:
            continue
        return waiver, index
    return None


def scan_claims(
    manuscript: Path,
    policy: ClaimsPolicy,
    paper_root: Path | None = None,
) -> tuple[list[Problem], list[Problem], dict[str, int]]:
    """Classify untagged numbers against protected sections and waivers."""
    manuscript = Path(manuscript)
    root = Path(paper_root) if paper_root is not None else manuscript.parent
    tex_files = iter_tex_files(manuscript)
    protected_by_file: dict[str, set[int]] = {}
    matched_sections: set[str] = set()
    for path in tex_files:
        protected, matched = _protected_lines(path, policy)
        protected_by_file[str(path)] = protected
        matched_sections |= matched

    problems: list[Problem] = []
    advisories: list[Problem] = []
    for section in policy.protected_sections:
        if section not in matched_sections:
            problems.append(
                Problem(
                    "claims-policy-unknown-section",
                    POLICY_RELATIVE_PATH.as_posix(),
                    None,
                    f"protected_sections 条目 {section!r} "
                    "未在 manuscript 中找到任何标题匹配",
                )
            )

    hit_counts: dict[int, int] = {}
    for path in tex_files:
        protected = protected_by_file[str(path)]
        for item in find_untagged(path):
            if item.line not in protected:
                continue
            match = _matching_waiver(
                item.path,
                item.line,
                item.text,
                policy,
                root,
            )
            if match is not None:
                index = match[1]
                hit_counts[index] = hit_counts.get(index, 0) + 1

    waived = 0
    unbound = 0

    for path in tex_files:
        protected = protected_by_file[str(path)]
        for item in find_untagged(path):
            if item.line not in protected:
                advisories.append(
                    Problem(
                        "untagged-number",
                        _report_path(item.path, root),
                        item.line,
                        f"未标记的数字线索（需人工复核）: {item.text}",
                    )
                )
                continue

            match = _matching_waiver(
                item.path,
                item.line,
                item.text,
                policy,
                root,
            )
            if match is None:
                unbound += 1
                problems.append(
                    Problem(
                        "protected-untagged-number",
                        _report_path(item.path, root),
                        item.line,
                        f"受保护区未绑定数字（需绑定或逐条豁免）: {item.text}",
                    )
                )
                continue

            waiver, index = match
            waived += 1
            advisories.append(
                Problem(
                    "waived-number",
                    _report_path(item.path, root),
                    item.line,
                    "受保护区数字已豁免"
                    f"（命中 {hit_counts[index]} 处；"
                    f"reason={waiver.reason}; date={waiver.date}; "
                    f"author={waiver.author}）: {item.text}",
                )
            )

    bound = 0
    for tag in find_tags(tex_files):
        if tag.line in protected_by_file.get(tag.path, set()):
            bound += 1

    counts = {
        "protected_total": bound + waived + unbound,
        "bound": bound,
        "waived": waived,
        "unbound": unbound,
    }
    return problems, advisories, counts


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Claims Coverage Report",
        "",
        f"- Protected sections: {', '.join(report['protected_sections'])}",
        f"- Protected total: {report['protected_total']}",
        f"- Bound: {report['bound']}",
        f"- Waived: {report['waived']}",
        f"- Unbound: {report['unbound']}",
        "",
    ]
    for heading, key in (
        ("Unbound protected numbers", "problems"),
        ("Waived protected numbers", "advisories"),
    ):
        lines.extend([f"## {heading}", ""])
        items = [
            item
            for item in report[key]
            if item["code"]
            in {"protected-untagged-number", "waived-number"}
        ]
        if not items:
            lines.extend(["None.", ""])
            continue
        for item in items:
            location = item["path"]
            if item["line"] is not None:
                location += f":{item['line']}"
            lines.append(f"- `{location}` {item['message']}")
        lines.append("")
    lines.extend(
        [
            "## Notes",
            "",
            "- `waived-number` 消息会标注命中处数；如需精确到单行，"
            "请在 `data/claims.yaml` 的 waiver 中加可选 "
            "`line: <1 起行号>`。",
            "",
        ]
    )
    return "\n".join(lines)


def claims_coverage_report(
    paper_root: Path,
    manuscript: Path | None = None,
) -> dict[str, Any]:
    """Scan coverage and atomically write JSON and Markdown reports."""
    root = Path(paper_root)
    policy, policy_problems = load_policy(root)
    if policy is None:
        detail = "未配置或无效"
        if policy_problems:
            detail += f": {policy_problems[0].message}"
        raise ValueError(f"无法生成 claims coverage report，claims policy {detail}")

    manuscript_dir = Path(manuscript) if manuscript is not None else root / "manuscript"
    if not manuscript_dir.is_dir():
        raise ValueError(f"手稿目录不存在或不是目录: {manuscript_dir}")

    problems, advisories, counts = scan_claims(
        manuscript_dir,
        policy,
        paper_root=root,
    )
    problems = list(policy_problems) + problems
    report: dict[str, Any] = {
        "version": 1,
        "protected_sections": list(policy.protected_sections),
        **counts,
        "problems": [dict(item._asdict()) for item in problems],
        "advisories": [dict(item._asdict()) for item in advisories],
    }

    json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    markdown_text = _render_markdown(report)
    save_text_atomically(
        root / REPORT_JSON_RELATIVE_PATH,
        json_text,
        "claims coverage JSON",
    )
    save_text_atomically(
        root / REPORT_MD_RELATIVE_PATH,
        markdown_text,
        "claims coverage Markdown",
    )
    return report
