"""Validate figures/manifest.yaml against the files it claims to describe.

The manifest is what makes a figure traceable: which run produced it, which
script generated it, and where the text references it. A manifest that has
drifted from reality is worse than no manifest, so every claim is checked
against bytes rather than trusted.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from ccfa.cli import Problem
from ccfa.figurebytes import JPEG_SUFFIXES, sniff
from ccfa.run_log import record_path


def load_manifest(path: Path) -> list[dict]:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 manifest {path}: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"manifest 解析失败: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError("manifest 顶层必须是列表")
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"manifest 第 {index} 项必须是对象")
    return data


def _sha256(path: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _blank(value: object) -> bool:
    """Return true when *value* is not a usable non-empty string."""
    return not isinstance(value, str) or not value.strip()


def _resolve_inside(base: Path, path: Path) -> tuple[Path, bool]:
    """Resolve *path* and report whether it stays under *base*."""
    try:
        resolved_base = base.resolve()
        resolved = path.resolve()
    except OSError:
        resolved_base = base.absolute()
        resolved = path.absolute()
    try:
        resolved.relative_to(resolved_base)
    except ValueError:
        return resolved, False
    return resolved, True


def _resolve_figure(item: dict, paper_root: Path) -> tuple[Path, Problem | None]:
    explicit = item.get("file")
    if explicit:
        return paper_root / str(explicit), None
    name = str(item.get("name", ""))
    suffix = str(item.get("bytes_format", "")).lstrip(".")
    fallback = paper_root / "figures" / f"{name}.{suffix}"
    advisory = Problem(
        "manifest-missing-file",
        str(fallback),
        None,
        f"manifest 条目 {name} 缺 file 字段，已回退到约定路径；建议显式补写",
    )
    return fallback, advisory


def check_manifest(
    items: list[dict], paper_root: Path
) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root)
    problems: list[Problem] = []
    advisories: list[Problem] = []
    for item in items:
        name = str(item.get("name", "<unnamed>"))
        figure, fallback_advisory = _resolve_figure(item, paper_root)
        if fallback_advisory is not None:
            advisories.append(fallback_advisory)
        explicit_file = item.get("file")
        file_outside = isinstance(explicit_file, str) and Path(explicit_file).is_absolute()
        resolved_figure, figure_inside = _resolve_inside(paper_root, figure)
        if file_outside:
            figure_inside = False

        provenance_issues: list[str] = []
        for field in ("generator", "generator_hash"):
            if field not in item:
                provenance_issues.append(f"{field} 缺失")
                continue
            value = item[field]
            if not _blank(value):
                continue
            if isinstance(value, str):
                provenance_issues.append(f"{field} 为空，必须是非空字符串")
            else:
                provenance_issues.append(
                    f"{field} 类型非法（{type(value).__name__}），必须是非空字符串"
                )
        if provenance_issues:
            fields = "；".join(provenance_issues)
            problems.append(
                Problem(
                    "figure-provenance-missing",
                    str(figure),
                    None,
                    f"条目 {name} 的生成脚本溯源非法: {fields}",
                )
            )

        source_run_ids = item.get("source_run_ids")
        if not isinstance(source_run_ids, list) or not source_run_ids:
            problems.append(
                Problem(
                    "figure-provenance-missing",
                    str(figure),
                    None,
                    f"条目 {name} 缺可追溯的 source_run_ids（必须是非空列表）",
                )
            )
        else:
            log_dir = paper_root / "experiments" / "log"
            valid_run_ids: list[str] = []
            bad_members: list[str] = []
            for index, run_id in enumerate(source_run_ids):
                if not isinstance(run_id, str):
                    bad_members.append(
                        f"第 {index} 项为 {type(run_id).__name__}"
                    )
                elif not run_id.strip():
                    bad_members.append(f"第 {index} 项为空字符串")
                else:
                    valid_run_ids.append(run_id)
            if bad_members:
                problems.append(
                    Problem(
                        "figure-provenance-missing",
                        str(figure),
                        None,
                        f"条目 {name} 的 source_run_ids 成员类型非法: "
                        f"{'、'.join(bad_members)}；每个成员必须是非空字符串",
                    )
                )
            for run_label in valid_run_ids:
                run_path = record_path(log_dir, run_label)
                resolved_run, inside_log = _resolve_inside(log_dir, run_path)
                if not inside_log:
                    problems.append(
                        Problem(
                            "figure-source-run",
                            str(resolved_run),
                            None,
                            f"条目 {name} 的 source_run_ids 越界: {run_label}",
                        )
                    )
                elif not resolved_run.is_file():
                    problems.append(
                        Problem(
                            "figure-source-run",
                            str(resolved_run),
                            None,
                            f"条目 {name} 的 source_run_ids 指向不存在的运行记录: {run_label}",
                        )
                    )

        source_data = item.get("source_data")
        if not isinstance(source_data, str):
            problems.append(
                Problem(
                    "figure-source-data",
                    str(figure),
                    None,
                    f"条目 {name} 的 source_data 类型非法"
                    f"（{type(source_data).__name__}），必须是非空字符串",
                )
            )
        elif not source_data.strip():
            problems.append(
                Problem(
                    "figure-source-data",
                    str(figure),
                    None,
                    f"条目 {name} 的 source_data 为空，必须是非空字符串",
                )
            )
        else:
            source_path = Path(source_data)
            if source_path.is_absolute():
                problems.append(
                    Problem(
                        "figure-source-data",
                        str(source_path),
                        None,
                        f"条目 {name} 的 source_data 不允许绝对路径: {source_data}",
                    )
                )
            else:
                resolved_source, inside_root = _resolve_inside(
                    paper_root,
                    paper_root / source_data,
                )
                if not inside_root:
                    problems.append(
                        Problem(
                            "figure-source-data",
                            str(resolved_source),
                            None,
                            f"条目 {name} 的 source_data 越界: {source_data}",
                        )
                    )
                elif not resolved_source.is_file():
                    problems.append(
                        Problem(
                            "figure-source-data",
                            str(resolved_source),
                            None,
                            f"条目 {name} 的 source_data 文件不存在: {source_data}",
                        )
                    )

        if "manual_edit" in item:
            manual_edit = item["manual_edit"]
            if not isinstance(manual_edit, bool):
                problems.append(
                    Problem(
                        "figure-manual-edit",
                        str(figure),
                        None,
                        f"条目 {name} 的 manual_edit 必须是布尔值，"
                        f"当前是 {type(manual_edit).__name__}",
                    )
                )
            elif manual_edit and _blank(item.get("manual_edit_note")):
                problems.append(
                    Problem(
                        "figure-manual-edit",
                        str(figure),
                        None,
                        f"条目 {name} 标记 manual_edit: true，"
                        "但 manual_edit_note 必须是非空字符串",
                    )
                )

        if not figure_inside:
            problems.append(
                Problem(
                    "figure-missing",
                    str(resolved_figure),
                    None,
                    f"条目 {name} 的交付图路径越出论文根",
                )
            )
        elif not resolved_figure.is_file():
            problems.append(
                Problem(
                    "figure-missing",
                    str(resolved_figure),
                    None,
                    f"条目 {name} 的交付图不存在",
                )
            )
        else:
            declared_raw = str(item.get("bytes_format", "")).lower().lstrip(".")
            actual = sniff(resolved_figure)
            if (
                declared_raw
                and actual is not None
                and actual != "." + declared_raw
                and not (actual == ".jpg" and "." + declared_raw in JPEG_SUFFIXES)
            ):
                problems.append(
                    Problem(
                        "figure-manifest-format",
                        str(figure),
                        None,
                        f"条目 {name} 声明 bytes_format={declared_raw}，实际字节是 {actual.lstrip('.')}",
                    )
                )

        generator = item.get("generator")
        expected_hash = item.get("generator_hash")
        generator_valid = isinstance(generator, str) and bool(generator.strip())
        hash_valid = isinstance(expected_hash, str) and bool(expected_hash.strip())
        if generator_valid and hash_valid:
            generator_path = Path(generator)
            resolved_generator, generator_inside = _resolve_inside(
                paper_root,
                paper_root / generator_path,
            )
            if generator_path.is_absolute() or not generator_inside:
                problems.append(
                    Problem(
                        "figure-hash",
                        str(resolved_generator),
                        None,
                        f"条目 {name} 的生成脚本必须在论文根内: {generator}",
                    )
                )
            else:
                actual_hash = _sha256(resolved_generator)
                if actual_hash is None:
                    problems.append(
                        Problem(
                            "figure-hash",
                            str(resolved_generator),
                            None,
                            f"条目 {name} 的生成脚本不存在: {generator}",
                        )
                    )
                elif actual_hash != expected_hash:
                    problems.append(
                        Problem(
                            "figure-hash",
                            str(resolved_generator),
                            None,
                            f"条目 {name} 的生成脚本哈希不符"
                            f"（记录 {expected_hash}，实际 {actual_hash}）",
                        )
                    )

        if not item.get("referenced_in"):
            advisories.append(
                Problem(
                    "unreferenced-figure",
                    str(figure),
                    None,
                    f"条目 {name} 未记录正文引用位置",
                )
            )
    return problems, advisories
