"""Audit human review of proofs, citations, and figures.

This tool cannot decide whether a proof is valid, whether a citation
semantically supports a sentence, or whether a figure shows what the text
claims with it. It enforces the next best thing: those human judgments must
exist as structured records before the paper can pass the gate, and missing,
non-human, contradictory, or unverifiable records are reported as problems
instead of disappearing into prose.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re
import sys
from pathlib import Path

import yaml

from ccfa.claims_policy import load_policy
from ccfa.cli import Problem, emit, tool_error
from ccfa.figure_manifest import load_manifest
from ccfa.texcomment import strip_comment
from ccfa.texscan import iter_tex_files

PROOF_LEDGER_RELATIVE_PATH = Path("data") / "proof-audit.yaml"
CITATION_LEDGER_RELATIVE_PATH = Path("data") / "citation-support.yaml"
FIGURE_LEDGER_RELATIVE_PATH = Path("data") / "figure-support.yaml"
FIGURE_MANIFEST_RELATIVE_PATH = Path("figures") / "manifest.yaml"
NOVELTY_LEDGER_RELATIVE_PATH = Path("data") / "novelty-audit.yaml"
PROOF_METHODS = frozenset(
    {
        "line-by-line",
        "independent-reproduction",
        "external-expert",
        "formal-proof",
    }
)
PROOF_STATUSES = frozenset({"pending", "verified", "refuted", "uncertain"})
SUPPORT_VERDICTS = frozenset({"supports", "partial", "contradicts", "irrelevant"})
FIGURE_VERDICTS = frozenset(
    {"supports", "partial", "contradicts", "irrelevant", "not-applicable"}
)
FIGURE_NOT_SUPPORTING_VERDICTS = frozenset({"contradicts", "irrelevant"})
FIGURE_NOTE_VERDICTS = frozenset(
    {"partial", "contradicts", "irrelevant", "not-applicable"}
)
THEOREM_ENVIRONMENTS = ("theorem", "proposition", "lemma", "corollary")
_ENV_BEGIN = re.compile(
    r"\\begin\{(" + "|".join(THEOREM_ENVIRONMENTS) + r")\}"
)
_ENV_END = re.compile(r"\\end\{(theorem|proposition|lemma|corollary)\}")
_LABEL = re.compile(r"\\label\{([^{}]+)\}")
_HEADING = re.compile(
    r"\\(section|subsection)\*?\s*(?:\[[^\]]*\]\s*)*\{([^{}]*)\}"
)
_CITE = re.compile(
    r"\\cite[a-zA-Z]*\s*(?:\[[^\]]*\]\s*)*\{([^{}]+)\}"
)
_BIB_KEY = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")
_ABSTRACT_BEGIN = re.compile(r"\\begin\{abstract\}")
_ABSTRACT_END = re.compile(r"\\end\{abstract\}")
_MODEL_REVIEWER = re.compile(
    r"(?i)\b(gpt|chatgpt|claude|gemini|deepseek|qwen|llama|mistral|"
    r"grok|sonnet|haiku|opus|nova|command|phi|o[134])\b"
)
_MIN_QUOTE = 20
_MIN_NOTE = 20


def _normalise_section(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _normalise_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _problem(code: str, path: Path | str, line: int | None, message: str) -> Problem:
    return Problem(code, str(path), line, message)


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _proof_input_key(
    paper_root: Path,
    manuscript: Path,
    environment_path: str,
) -> str | None:
    """Map a theorem's manuscript-relative path to a paper-relative key."""

    try:
        base = Path(manuscript).resolve().relative_to(Path(paper_root).resolve())
    except (OSError, ValueError):
        return None
    return (base / environment_path).as_posix()


def _check_audited_inputs(
    review: dict,
    review_id: str,
    paper_root: Path,
    required_key: str | None,
    ledger_path: Path,
    problems: list[Problem],
    *,
    codes: tuple[str, str] = ("proof-review-unbound", "proof-review-stale"),
) -> None:
    """Bind a human attestation to the bytes it claims to have reviewed.

    A signature that is not tied to a revision survives every later edit, which
    is exactly the failure mode this check exists for.
    """

    root = Path(paper_root).resolve()
    unbound_code, stale_code = codes
    inputs = review.get("audited_inputs")
    if not isinstance(inputs, dict) or not inputs:
        problems.append(
            _problem(
                unbound_code,
                ledger_path,
                None,
                f"{review_id}: status=verified 必须写 audited_inputs"
                "（复核时读过的文件 + sha256），否则改稿后复核仍然有效",
            )
        )
        return
    seen: set[str] = set()
    for raw_path, digest in inputs.items():
        relative = str(raw_path)
        try:
            target = (root / relative).resolve()
            resolved = target.relative_to(root).as_posix()
        except (OSError, ValueError):
            problems.append(
                _problem(
                    unbound_code,
                    ledger_path,
                    None,
                    f"{review_id}: audited_inputs 路径越界: {relative!r}",
                )
            )
            continue
        if not _DIGEST.match(str(digest)):
            problems.append(
                _problem(
                    unbound_code,
                    ledger_path,
                    None,
                    f"{review_id}: {relative} 的摘要必须是 sha256:<64 位十六进制>",
                )
            )
            continue
        seen.add(resolved)
        if not target.is_file():
            problems.append(
                _problem(
                    unbound_code,
                    ledger_path,
                    None,
                    f"{review_id}: audited_inputs 指向的文件不存在: {relative}",
                )
            )
        elif sha256_of(target) != digest:
            problems.append(
                _problem(
                    stale_code,
                    target,
                    None,
                    f"{review_id}: {relative} 在复核之后被修改，"
                    "复核结论作废（重跑 argument-audit stamp 并重新签字）",
                )
            )
    if required_key is not None and required_key not in seen:
        problems.append(
            _problem(
                unbound_code,
                ledger_path,
                None,
                f"{review_id}: audited_inputs 必须包含定理所在文件 {required_key}",
            )
        )


def _read_yaml(path: Path) -> tuple[object | None, list[Problem]]:
    path = Path(path)
    if not path.is_file():
        return None, []
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, [
            _problem("argument-audit-invalid", path, None, f"无法读取台账: {exc}")
        ]
    if not isinstance(payload, dict):
        return None, [
            _problem(
                "argument-audit-invalid",
                path,
                None,
                "台账顶层必须是映射",
            )
        ]
    version = payload.get("version")
    if type(version) is not int or version != 1:
        return None, [
            _problem(
                "argument-audit-invalid",
                path,
                None,
                "台账 version 必须是整数 1",
            )
        ]
    return payload, []


def _human_reviewer(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and _MODEL_REVIEWER.search(value) is None
    )


def _valid_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _scan_theorem_environments(manuscript: Path) -> list[dict]:
    entries: list[dict] = []
    try:
        tex_files = iter_tex_files(Path(manuscript))
    except OSError as exc:
        raise ValueError(f"无法遍历手稿目录 {manuscript}: {exc}") from exc
    for tex in tex_files:
        relative = tex.relative_to(Path(manuscript)).as_posix()
        try:
            lines = tex.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise ValueError(f"无法读取 {tex}: {exc}") from exc
        pending: dict | None = None
        for line_number, raw in enumerate(lines, start=1):
            line = strip_comment(raw)
            if pending is None:
                match = _ENV_BEGIN.search(line)
                if match:
                    pending = {
                        "environment": match.group(1),
                        "path": relative,
                        "line": line_number,
                        "label": None,
                    }
            if pending is None:
                continue
            label = _LABEL.search(line)
            if label and pending["label"] is None:
                pending["label"] = label.group(1)
            end = _ENV_END.search(line)
            if end and end.group(1) == pending["environment"]:
                key = pending["label"] or f"{pending['path']}#L{pending['line']}"
                entries.append({**pending, "id": key})
                pending = None
    return entries


def _seal_region(region: dict, end_line: int) -> None:
    region["end"] = end_line
    region["text"] = _normalise_whitespace(" ".join(region.pop("lines")))


def _scan_protected_citations(
    manuscript: Path,
    protected_sections: set[str],
) -> dict[str, list[dict]]:
    citations: dict[str, list[dict]] = {}
    try:
        tex_files = iter_tex_files(Path(manuscript))
    except OSError as exc:
        raise ValueError(f"无法遍历手稿目录 {manuscript}: {exc}") from exc
    for tex in tex_files:
        relative = tex.relative_to(Path(manuscript)).as_posix()
        try:
            lines = tex.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise ValueError(f"无法读取 {tex}: {exc}") from exc
        active_stack: list[tuple[int, bool]] = []
        in_abstract = False
        current_region: dict | None = None
        for line_number, raw in enumerate(lines, start=1):
            line = strip_comment(raw)
            if _ABSTRACT_BEGIN.search(line):
                if (
                    "abstract" in protected_sections
                    and current_region is not None
                ):
                    _seal_region(current_region, line_number - 1)
                    current_region = None
                in_abstract = True
            if in_abstract and _ABSTRACT_END.search(line):
                in_abstract = False
            heading = _HEADING.search(line)
            if heading:
                level = 1 if heading.group(1) == "section" else 2
                normalised = _normalise_section(heading.group(2))
                while active_stack and active_stack[-1][0] >= level:
                    active_stack.pop()
                parent_protected = (
                    active_stack[-1][1] if active_stack else False
                )
                active_stack.append(
                    (
                        level,
                        parent_protected
                        or normalised in protected_sections,
                    )
                )
                if (
                    level == 1
                    and normalised in protected_sections
                    and current_region is not None
                ):
                    _seal_region(current_region, line_number - 1)
                    current_region = None
            protected = (
                (in_abstract and "abstract" in protected_sections)
                or (active_stack and active_stack[-1][1])
            )
            if protected and current_region is None:
                current_region = {
                    "path": relative,
                    "start": line_number,
                    "lines": [],
                }
            elif not protected and current_region is not None:
                _seal_region(current_region, line_number - 1)
                current_region = None
            if not protected:
                continue
            current_region["lines"].append(line)
            for match in _CITE.finditer(line):
                for key in match.group(1).split(","):
                    key = key.strip()
                    if key:
                        citations.setdefault(key, []).append(
                            {
                                "path": relative,
                                "line": line_number,
                                "region": current_region,
                            }
                        )
        if current_region is not None:
            _seal_region(current_region, len(lines))
    return citations


def _bib_keys(bib: Path) -> set[str]:
    if not bib.is_file():
        raise ValueError(f"BibTeX 不存在: {bib}")
    try:
        text = bib.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"无法读取 BibTeX {bib}: {exc}") from exc
    return {match.group(1) for match in _BIB_KEY.finditer(text)}


def _check_proofs(
    paper_root: Path,
    manuscript: Path,
    environments: list[dict],
    ledger_path: Path,
) -> tuple[list[Problem], list[Problem], dict]:
    problems: list[Problem] = []
    advisories: list[Problem] = []
    payload, read_problems = _read_yaml(ledger_path)
    problems.extend(read_problems)
    if not environments:
        advisories.append(
            _problem(
                "proof-audit-not-needed",
                ledger_path,
                None,
                "手稿中没有 theorem/proposition/lemma/corollary，证明复核不适用",
            )
        )
        return problems, advisories, {"required": 0, "reviewed": 0}
    if payload is None:
        if not ledger_path.is_file():
            problems.append(
                _problem(
                    "proof-audit-missing",
                    ledger_path,
                    None,
                    "存在定理类环境，但缺少人工证明复核台账",
                )
            )
        return problems, advisories, {
            "required": len(environments),
            "reviewed": 0,
        }
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        problems.append(
            _problem(
                "proof-audit-invalid",
                ledger_path,
                None,
                "reviews 必须是数组",
            )
        )
        return problems, advisories, {
            "required": len(environments),
            "reviewed": 0,
        }
    by_id: dict[str, dict] = {}
    for index, review in enumerate(reviews):
        if not isinstance(review, dict):
            problems.append(
                _problem(
                    "proof-audit-invalid",
                    ledger_path,
                    None,
                    f"reviews[{index}] 必须是映射",
                )
            )
            continue
        missing = [
            field
            for field in ("id", "reviewer", "reviewed_at", "method", "status")
            if field not in review
        ]
        if missing:
            problems.append(
                _problem(
                    "proof-audit-invalid",
                    ledger_path,
                    None,
                    f"reviews[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        review_id = review.get("id")
        if not isinstance(review_id, str) or not review_id.strip():
            problems.append(
                _problem(
                    "proof-audit-invalid",
                    ledger_path,
                    None,
                    f"reviews[{index}].id 必须是非空字符串",
                )
            )
            continue
        by_id[review_id] = review
        if not _human_reviewer(review.get("reviewer")):
            problems.append(
                _problem(
                    "proof-review-not-human",
                    ledger_path,
                    None,
                    f"{review_id}: reviewer 必须记录人类姓名，不能是模型名",
                )
            )
        if not _valid_date(review.get("reviewed_at")):
            problems.append(
                _problem(
                    "proof-review-invalid-date",
                    ledger_path,
                    None,
                    f"{review_id}: reviewed_at 必须是 YYYY-MM-DD",
                )
            )
        method = review.get("method")
        if not isinstance(method, str) or method not in PROOF_METHODS:
            problems.append(
                _problem(
                    "proof-review-invalid-method",
                    ledger_path,
                    None,
                    f"{review_id}: method 必须是 {sorted(PROOF_METHODS)}",
                )
            )
        status = review.get("status")
        if not isinstance(status, str) or status not in PROOF_STATUSES:
            problems.append(
                _problem(
                    "proof-review-invalid-status",
                    ledger_path,
                    None,
                    f"{review_id}: status 必须是 {sorted(PROOF_STATUSES)}",
                )
            )
        elif status != "verified":
            problems.append(
                _problem(
                    "proof-review-not-verified",
                    ledger_path,
                    None,
                    f"{review_id}: status={status!r}，"
                    "未通过人工复核",
                )
            )
        elif _human_reviewer(review.get("reviewer")):
            # Only a human attestation needs binding; a model reviewer is
            # already rejected above, and repeating the complaint adds noise.
            environment = next(
                (item for item in environments if item["id"] == review_id),
                None,
            )
            required = (
                _proof_input_key(paper_root, manuscript, environment["path"])
                if environment is not None
                else None
            )
            _check_audited_inputs(
                review,
                review_id,
                paper_root,
                required,
                ledger_path,
                problems,
            )
    env_ids = {item["id"] for item in environments}
    for item in environments:
        if item["id"] not in by_id:
            problems.append(
                _problem(
                    "proof-review-missing",
                    item["path"],
                    item["line"],
                    f"{item['environment']} 环境 {item['id']!r} 没有人工复核记录",
                )
            )
    for review_id in sorted(set(by_id) - env_ids):
        advisories.append(
            _problem(
                "proof-review-orphan",
                ledger_path,
                None,
                f"{review_id!r} 不对应任何当前定理类环境",
            )
        )
    reviewed = sum(
        1
        for item in environments
        if by_id.get(item["id"], {}).get("status") == "verified"
        and _human_reviewer(by_id[item["id"]].get("reviewer"))
        and _valid_date(by_id[item["id"]].get("reviewed_at"))
        and by_id[item["id"]].get("method") in PROOF_METHODS
    )
    return problems, advisories, {
        "required": len(environments),
        "reviewed": reviewed,
    }


def _check_citation_support(
    paper_root: Path,
    manuscript: Path,
    protected_citations: dict[str, list[dict]],
    ledger_path: Path,
    bib_keys: set[str],
) -> tuple[list[Problem], list[Problem], dict]:
    problems: list[Problem] = []
    advisories: list[Problem] = []
    payload, read_problems = _read_yaml(ledger_path)
    problems.extend(read_problems)
    if not protected_citations:
        advisories.append(
            _problem(
                "citation-support-not-needed",
                ledger_path,
                None,
                "受保护章节中没有引用，引用语义支持不适用",
            )
        )
        return problems, advisories, {"required": 0, "reviewed": 0}
    if payload is None:
        if not ledger_path.is_file():
            problems.append(
                _problem(
                    "citation-support-ledger-missing",
                    ledger_path,
                    None,
                    "受保护章节存在引用，但缺少人工语义支持台账",
                )
            )
        return problems, advisories, {
            "required": len(protected_citations),
            "reviewed": 0,
        }
    supports = payload.get("supports")
    if not isinstance(supports, list):
        problems.append(
            _problem(
                "argument-audit-invalid",
                ledger_path,
                None,
                "supports 必须是数组",
            )
        )
        return problems, advisories, {
            "required": len(protected_citations),
            "reviewed": 0,
        }
    citation_regions: dict[str, list[str]] = {
        key: [entry["region"]["text"] for entry in entries]
        for key, entries in protected_citations.items()
    }
    covered: set[str] = set()
    for index, support in enumerate(supports):
        if not isinstance(support, dict):
            problems.append(
                _problem(
                    "argument-audit-invalid",
                    ledger_path,
                    None,
                    f"supports[{index}] 必须是映射",
                )
            )
            continue
        missing = [
            field
            for field in (
                "id",
                "claim_text",
                "citations",
                "reviewer",
                "reviewed_at",
                "verdict",
                "support_quote",
            )
            if field not in support
        ]
        if missing:
            problems.append(
                _problem(
                    "argument-audit-invalid",
                    ledger_path,
                    None,
                    f"supports[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        support_id = support.get("id")
        if not isinstance(support_id, str) or not support_id.strip():
            problems.append(
                _problem(
                    "argument-audit-invalid",
                    ledger_path,
                    None,
                    f"supports[{index}].id 必须是非空字符串",
                )
            )
            continue
        claim_text = support.get("claim_text")
        claim_text_valid = (
            isinstance(claim_text, str)
            and len(_normalise_whitespace(claim_text)) >= _MIN_QUOTE
        )
        if not claim_text_valid:
            problems.append(
                _problem(
                    "citation-support-claim-too-short",
                    ledger_path,
                    None,
                    f"{support_id}: claim_text 至少需要 {_MIN_QUOTE} 字符",
                )
            )
        if not _human_reviewer(support.get("reviewer")):
            problems.append(
                _problem(
                    "citation-support-not-human",
                    ledger_path,
                    None,
                    f"{support_id}: reviewer 必须记录人类姓名，不能是模型名",
                )
            )
        if not _valid_date(support.get("reviewed_at")):
            problems.append(
                _problem(
                    "citation-support-invalid-date",
                    ledger_path,
                    None,
                    f"{support_id}: reviewed_at 必须是 YYYY-MM-DD",
                )
            )
        if _human_reviewer(support.get("reviewer")):
            # The human read an evidence source; bind the verdict to those bytes.
            source_path = support.get("source_path")
            required = (
                source_path.strip()
                if isinstance(source_path, str) and source_path.strip()
                else None
            )
            _check_audited_inputs(
                support,
                support_id,
                paper_root,
                required,
                ledger_path,
                problems,
                codes=(
                    "citation-support-unbound",
                    "citation-support-stale",
                ),
            )
        verdict = support.get("verdict")
        if not isinstance(verdict, str) or verdict not in SUPPORT_VERDICTS:
            problems.append(
                _problem(
                    "citation-support-invalid-verdict",
                    ledger_path,
                    None,
                    f"{support_id}: verdict 必须是 {sorted(SUPPORT_VERDICTS)}",
                )
            )
        elif verdict in {"contradicts", "irrelevant"}:
            problems.append(
                _problem(
                    "citation-support-not-supporting",
                    ledger_path,
                    None,
                    f"{support_id}: verdict={verdict!r}，引用不支撑当前论断",
                )
            )
        elif verdict == "partial":
            advisories.append(
                _problem(
                    "citation-support-partial",
                    ledger_path,
                    None,
                    f"{support_id}: 引用只提供部分支持，需要人工确认是否足够",
                )
            )
        quote = support.get("support_quote")
        quote_valid = (
            isinstance(quote, str)
            and len(_normalise_whitespace(quote)) >= _MIN_QUOTE
        )
        if not quote_valid:
            problems.append(
                _problem(
                    "citation-support-quote-too-short",
                    ledger_path,
                    None,
                    f"{support_id}: support_quote 至少需要 {_MIN_QUOTE} 字符",
                )
            )
        citations = support.get("citations")
        if (
            not isinstance(citations, list)
            or not citations
            or not all(isinstance(item, str) and item.strip() for item in citations)
        ):
            problems.append(
                _problem(
                    "citation-support-invalid-citations",
                    ledger_path,
                    None,
                    f"{support_id}: citations 必须是非空字符串数组",
                )
            )
            continue
        for key in citations:
            key = key.strip()
            if key not in bib_keys:
                problems.append(
                    _problem(
                        "citation-support-unknown-bib",
                        ledger_path,
                        None,
                        f"{support_id}: bib 中不存在 {key!r}",
                    )
                )
            if key in protected_citations:
                covered.add(key)
                if claim_text_valid:
                    needle = _normalise_whitespace(claim_text)
                    if not any(
                        needle in region_text
                        for region_text in citation_regions.get(key, [])
                    ):
                        problems.append(
                            _problem(
                                "citation-support-claim-not-found",
                                ledger_path,
                                None,
                                f"{support_id}: claim_text 没有出现在引用 "
                                f"{key!r} 的受保护章节中",
                            )
                        )
        source_path = support.get("source_path")
        if not isinstance(source_path, str) or not source_path.strip():
            problems.append(
                _problem(
                    "citation-support-source-missing",
                    ledger_path,
                    None,
                    f"{support_id}: source_path 必填，否则引文无法本地复核",
                )
            )
        elif quote_valid:
            source = (Path(paper_root) / source_path).resolve()
            try:
                source.relative_to(Path(paper_root).resolve())
            except ValueError:
                problems.append(
                    _problem(
                        "citation-support-source-escape",
                        ledger_path,
                        None,
                        f"{support_id}: source_path 逃出 paper_root: {source_path}",
                    )
                )
                continue
            if not source.is_file():
                problems.append(
                    _problem(
                        "citation-support-source-missing",
                        ledger_path,
                        None,
                        f"{support_id}: source_path 不存在: {source_path}",
                    )
                )
                continue
            try:
                corpus = _normalise_whitespace(
                    source.read_text(encoding="utf-8", errors="replace")
                )
            except OSError as exc:
                raise ValueError(f"无法读取 {source}: {exc}") from exc
            if _normalise_whitespace(quote) not in corpus:
                problems.append(
                    _problem(
                        "citation-support-quote-not-found",
                        source,
                        None,
                        f"{support_id}: support_quote 未在 source_path 中找到",
                    )
                )
    for key, locations in sorted(protected_citations.items()):
        if key not in covered:
            first_path = locations[0]["path"]
            first_line = locations[0]["line"]
            problems.append(
                _problem(
                    "citation-support-missing",
                    manuscript / first_path,
                    first_line,
                    f"受保护章节引用了 {key!r}，但没有人工作为「支撑该论断」的记录",
                )
            )
    return problems, advisories, {
        "required": len(protected_citations),
        "reviewed": len(covered),
    }


def _declared_claims(paper_root: Path) -> set[str] | None:
    """Return the claim ids declared by the novelty audit.

    The novelty ledger owns the canonical claim registry; a figure that
    asserts evidence must bind to one of those ids, otherwise the binding is
    just a free-form string that no other gate understands. ``None`` means the
    registry cannot be trusted (missing, unparseable, wrong version, or not a
    list of non-empty strings); an empty set means a valid registry that
    declares no claims. Callers must not treat a partial registry as usable.
    """
    path = Path(paper_root) / NOVELTY_LEDGER_RELATIVE_PATH
    if not path.is_file():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(payload, dict):
        return None
    version = payload.get("version")
    if type(version) is not int or version != 1:
        return None
    raw = payload.get("claims")
    if not isinstance(raw, list):
        return None
    claims: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            return None
        claim_id = item.strip()
        if claim_id in claims:
            return None
        claims.add(claim_id)
    return claims


def _load_figure_manifest(
    manifest_path: Path,
) -> tuple[list[dict] | None, list[Problem]]:
    if not manifest_path.is_file():
        return None, []
    try:
        return load_manifest(manifest_path), []
    except ValueError as exc:
        return None, [
            _problem(
                "argument-audit-invalid",
                manifest_path,
                None,
                f"无法读取图表清单: {exc}",
            )
        ]


def _reference_corpus(
    paper_root: Path,
    reference: str,
) -> tuple[Path | None, str | None, str | None]:
    """Parse one ``path:line`` reference and return its normalised text.

    Returns ``(resolved_path, corpus, error)``. Exactly one of ``corpus`` and
    ``error`` is set when the reference parses; both are ``None`` only when the
    reference resolves to a readable file with no text.
    """
    raw = reference.strip()
    relative, separator, line_part = raw.rpartition(":")
    if not separator or not relative:
        return None, None, f"referenced_in 条目必须是 <相对路径>:<行号>: {raw!r}"
    if not line_part.isdigit() or int(line_part) < 1:
        return None, None, f"referenced_in 行号必须是 >=1 的整数: {raw!r}"
    resolved = (paper_root / relative).resolve()
    try:
        resolved.relative_to(paper_root.resolve())
    except ValueError:
        return None, None, f"referenced_in 逃出 paper_root: {raw!r}"
    if not resolved.is_file():
        return None, None, f"referenced_in 指向不存在的文件: {raw!r}"
    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"无法读取 {resolved}: {exc}") from exc
    line_count = len(text.splitlines())
    if int(line_part) > line_count:
        return (
            None,
            None,
            f"referenced_in 行号越界（文件只有 {line_count} 行）: {raw!r}",
        )
    corpus = _normalise_whitespace(text)
    return resolved, corpus, None


def _check_figure_support(
    paper_root: Path,
    manifest_path: Path,
    ledger_path: Path,
) -> tuple[list[Problem], list[Problem], dict]:
    problems: list[Problem] = []
    advisories: list[Problem] = []
    manifest, manifest_problems = _load_figure_manifest(manifest_path)
    problems.extend(manifest_problems)
    if manifest is None:
        advisories.append(
            _problem(
                "figure-support-not-needed",
                manifest_path,
                None,
                "没有 figures/manifest.yaml，图表语义支持不适用",
            )
        )
        return problems, advisories, {"required": 0, "reviewed": 0}

    manifest_entries: dict[str, dict] = {}
    manifest_scan_problems = False
    for index, item in enumerate(manifest, start=1):
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            manifest_scan_problems = True
            problems.append(
                _problem(
                    "figure-support-manifest-invalid",
                    manifest_path,
                    None,
                    f"manifest 第 {index} 项缺非空 name，无法逐图审计",
                )
            )
            continue
        name = name.strip()
        if name in manifest_entries:
            manifest_scan_problems = True
            problems.append(
                _problem(
                    "figure-support-manifest-invalid",
                    manifest_path,
                    None,
                    f"manifest 图名重复 {name!r}，无法把审计结论逐图对上",
                )
            )
            continue
        manifest_entries[name] = item
    if not manifest_entries:
        if not manifest_scan_problems:
            advisories.append(
                _problem(
                    "figure-support-not-needed",
                    manifest_path,
                    None,
                    "图表清单没有具名交付图，图表语义支持不适用",
                )
            )
        return problems, advisories, {"required": 0, "reviewed": 0}

    payload, read_problems = _read_yaml(ledger_path)
    problems.extend(read_problems)
    if payload is None:
        if not ledger_path.is_file():
            problems.append(
                _problem(
                    "figure-support-ledger-missing",
                    ledger_path,
                    None,
                    "manifest 声明了交付图，但缺少人工图表语义支持台账",
                )
            )
        return problems, advisories, {
            "required": len(manifest_entries),
            "reviewed": 0,
        }

    entries = payload.get("figures")
    if not isinstance(entries, list):
        problems.append(
            _problem(
                "argument-audit-invalid",
                ledger_path,
                None,
                "figures 必须是数组",
            )
        )
        return problems, advisories, {
            "required": len(manifest_entries),
            "reviewed": 0,
        }

    claims = _declared_claims(paper_root)
    claims_reported = False

    covered: set[str] = set()
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(
                _problem(
                    "argument-audit-invalid",
                    ledger_path,
                    None,
                    f"figures[{index}] 必须是映射",
                )
            )
            continue
        figure_id = entry.get("id")
        if not isinstance(figure_id, str) or not figure_id.strip():
            problems.append(
                _problem(
                    "argument-audit-invalid",
                    ledger_path,
                    None,
                    f"figures[{index}].id 必须是非空字符串",
                )
            )
            continue
        figure_id = figure_id.strip()
        if figure_id in seen:
            problems.append(
                _problem(
                    "argument-audit-invalid",
                    ledger_path,
                    None,
                    f"{figure_id}: 重复的图表语义支持条目",
                )
            )
            continue
        seen.add(figure_id)

        missing = [
            field
            for field in ("verdict", "reviewer", "reviewed_at")
            if field not in entry
        ]
        if missing:
            problems.append(
                _problem(
                    "argument-audit-invalid",
                    ledger_path,
                    None,
                    f"{figure_id}: 缺少字段 {', '.join(missing)}",
                )
            )
            continue
        if not _human_reviewer(entry.get("reviewer")):
            problems.append(
                _problem(
                    "figure-support-not-human",
                    ledger_path,
                    None,
                    f"{figure_id}: reviewer 必须记录人类姓名，不能是模型名",
                )
            )
        if not _valid_date(entry.get("reviewed_at")):
            problems.append(
                _problem(
                    "figure-support-invalid-date",
                    ledger_path,
                    None,
                    f"{figure_id}: reviewed_at 必须是 YYYY-MM-DD",
                )
            )
        verdict = entry.get("verdict")
        if not isinstance(verdict, str) or verdict not in FIGURE_VERDICTS:
            problems.append(
                _problem(
                    "figure-support-invalid-verdict",
                    ledger_path,
                    None,
                    f"{figure_id}: verdict 必须是 {sorted(FIGURE_VERDICTS)}",
                )
            )
            continue

        manifest_entry = manifest_entries.get(figure_id)
        if manifest_entry is None:
            problems.append(
                _problem(
                    "figure-support-figure-missing",
                    manifest_path,
                    None,
                    f"{figure_id}: manifest 中没有同名交付图",
                )
            )
            continue
        covered.add(figure_id)

        if _human_reviewer(entry.get("reviewer")):
            # The human looked at a delivered figure; bind the verdict to it.
            figure_file = manifest_entry.get("file")
            _check_audited_inputs(
                entry,
                figure_id,
                paper_root,
                figure_file if isinstance(figure_file, str) else None,
                ledger_path,
                problems,
                codes=(
                    "figure-support-unbound",
                    "figure-support-stale",
                ),
            )

        note = entry.get("note")
        note_valid = (
            isinstance(note, str) and len(_normalise_whitespace(note)) >= _MIN_NOTE
        )
        if verdict in FIGURE_NOTE_VERDICTS and not note_valid:
            problems.append(
                _problem(
                    "figure-support-note-missing",
                    ledger_path,
                    None,
                    f"{figure_id}: verdict={verdict} 必须写明 >= {_MIN_NOTE} 字符的理由",
                )
            )

        if verdict == "not-applicable":
            claim_ids = entry.get("claim_ids")
            if claim_ids not in (None, []):
                problems.append(
                    _problem(
                        "figure-support-invalid-claims",
                        ledger_path,
                        None,
                        f"{figure_id}: not-applicable 的图不得绑定 claim",
                    )
                )
            continue

        if not claims and not claims_reported:
            claims_reported = True
            problems.append(
                _problem(
                    "figure-support-claims-unavailable",
                    NOVELTY_LEDGER_RELATIVE_PATH,
                    None,
                    "novelty-audit 未声明可用 claims，无法核对图表与 claim 的绑定",
                )
            )

        claim_ids = entry.get("claim_ids")
        if (
            not isinstance(claim_ids, list)
            or not claim_ids
            or not all(
                isinstance(item, str) and item.strip() for item in claim_ids
            )
        ):
            problems.append(
                _problem(
                    "figure-support-invalid-claims",
                    ledger_path,
                    None,
                    f"{figure_id}: claim_ids 必须是非空字符串数组",
                )
            )
        else:
            for claim_id in sorted({item.strip() for item in claim_ids}):
                if claims and claim_id not in claims:
                    problems.append(
                        _problem(
                            "figure-support-unknown-claim",
                            ledger_path,
                            None,
                            f"{figure_id}: claim {claim_id!r} 未在 novelty-audit 中声明",
                        )
                    )

        text = entry.get("attributed_text")
        text_valid = (
            isinstance(text, str)
            and len(_normalise_whitespace(text)) >= _MIN_QUOTE
        )
        if not text_valid:
            problems.append(
                _problem(
                    "figure-support-text-too-short",
                    ledger_path,
                    None,
                    f"{figure_id}: attributed_text 至少需要 {_MIN_QUOTE} 字符",
                )
            )

        if verdict in FIGURE_NOT_SUPPORTING_VERDICTS:
            problems.append(
                _problem(
                    "figure-support-not-supporting",
                    ledger_path,
                    None,
                    f"{figure_id}: verdict={verdict!r}，图表不支撑正文归属的结论",
                )
            )
        elif verdict == "partial":
            advisories.append(
                _problem(
                    "figure-support-partial",
                    ledger_path,
                    None,
                    f"{figure_id}: 图表只提供部分支持，需要人工确认是否足够",
                )
            )

        references = manifest_entry.get("referenced_in")
        if (
            not isinstance(references, list)
            or not references
            or not all(
                isinstance(item, str) and item.strip() for item in references
            )
        ):
            problems.append(
                _problem(
                    "figure-support-reference-missing",
                    manifest_path,
                    None,
                    f"{figure_id}: manifest 缺 referenced_in，无法把审计结论绑定到正文",
                )
            )
            continue

        if not text_valid:
            continue
        found = False
        for reference in references:
            resolved, corpus, error = _reference_corpus(paper_root, reference)
            if error is not None:
                problems.append(
                    _problem(
                        "figure-support-reference-invalid",
                        manifest_path,
                        None,
                        f"{figure_id}: {error}",
                    )
                )
                continue
            if corpus is not None and _normalise_whitespace(text) in corpus:
                found = True
        if not found:
            problems.append(
                _problem(
                    "figure-support-text-not-found",
                    manifest_path,
                    None,
                    f"{figure_id}: attributed_text 未出现在 referenced_in 指向的正文文件中",
                )
            )

    for name in sorted(manifest_entries):
        if name not in covered:
            problems.append(
                _problem(
                    "figure-support-missing",
                    manifest_path,
                    None,
                    f"交付图 {name!r} 没有人工图表语义支持记录",
                )
            )
    return problems, advisories, {
        "required": len(manifest_entries),
        "reviewed": len(covered),
    }


def check(
    paper_root: Path,
    *,
    manuscript: Path | None = None,
    bib: Path | None = None,
    proof_ledger: Path | None = None,
    citation_ledger: Path | None = None,
    figure_ledger: Path | None = None,
    manifest: Path | None = None,
) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root)
    manuscript = Path(manuscript) if manuscript else paper_root / "manuscript"
    bib = Path(bib) if bib else manuscript / "references.bib"
    proof_ledger = (
        Path(proof_ledger)
        if proof_ledger
        else paper_root / PROOF_LEDGER_RELATIVE_PATH
    )
    citation_ledger = (
        Path(citation_ledger)
        if citation_ledger
        else paper_root / CITATION_LEDGER_RELATIVE_PATH
    )
    figure_ledger = (
        Path(figure_ledger)
        if figure_ledger
        else paper_root / FIGURE_LEDGER_RELATIVE_PATH
    )
    manifest = (
        Path(manifest)
        if manifest
        else paper_root / FIGURE_MANIFEST_RELATIVE_PATH
    )
    if not manuscript.is_dir():
        raise ValueError(f"手稿目录不存在或不是目录: {manuscript}")
    environments = _scan_theorem_environments(manuscript)
    protected_sections: set[str] = set()
    policy, policy_problems = load_policy(paper_root)
    if policy is not None:
        protected_sections = {
            _normalise_section(section)
            for section in policy.protected_sections
        }
    protected_citations = _scan_protected_citations(
        manuscript,
        protected_sections,
    )
    keys = _bib_keys(bib)
    proof_problems, proof_advisories, proof_summary = _check_proofs(
        paper_root,
        manuscript,
        environments,
        proof_ledger,
    )
    support_problems, support_advisories, support_summary = (
        _check_citation_support(
            paper_root,
            manuscript,
            protected_citations,
            citation_ledger,
            keys,
        )
    )
    figure_problems, figure_advisories, figure_summary = _check_figure_support(
        paper_root,
        manifest,
        figure_ledger,
    )
    problems = [
        *policy_problems,
        *proof_problems,
        *support_problems,
        *figure_problems,
    ]
    advisories = [
        *proof_advisories,
        *support_advisories,
        *figure_advisories,
    ]
    if proof_summary["required"]:
        advisories.append(
            _problem(
                "proof-audit-coverage",
                proof_ledger,
                None,
                f"人工证明复核 {proof_summary['reviewed']}/"
                f"{proof_summary['required']}",
            )
        )
    if support_summary["required"]:
        advisories.append(
            _problem(
                "citation-support-coverage",
                citation_ledger,
                None,
                f"引用语义支持 {support_summary['reviewed']}/"
                f"{support_summary['required']}",
            )
        )
    if figure_summary["required"]:
        advisories.append(
            _problem(
                "figure-support-coverage",
                figure_ledger,
                None,
                f"图表语义支持 {figure_summary['reviewed']}/"
                f"{figure_summary['required']}",
            )
        )
    return problems, advisories


def _print_audited_inputs(paper_root: Path, files: list[str]) -> int:
    """Print the ``audited_inputs`` block for the current bytes of *files*."""

    root = Path(paper_root).resolve()
    lines = ["audited_inputs:"]
    for raw in files:
        target = (root / str(raw)).resolve()
        try:
            relative = target.relative_to(root).as_posix()
        except ValueError:
            return tool_error(f"文件不在论文目录内: {raw}")
        if not target.is_file():
            return tool_error(f"找不到文件: {raw}")
        lines.append(f"  {relative}: {sha256_of(target)}")
    print("\n".join(lines))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="审计人工证明复核、引用语义支持与图表语义支持台账"
    )
    parser.add_argument("--paper-root", default=".")
    parser.add_argument("--manuscript")
    parser.add_argument("--bib")
    parser.add_argument("--proof-ledger")
    parser.add_argument("--citation-ledger")
    parser.add_argument("--figure-ledger")
    parser.add_argument("--manifest")
    parser.add_argument(
        "--stamp",
        action="append",
        default=[],
        metavar="FILE",
        help=(
            "只打印这些文件（论文目录相对路径）的 audited_inputs 片段，"
            "供人工复核后粘进台账；不执行检查"
        ),
    )
    args = parser.parse_args(argv[1:])
    if args.stamp:
        return _print_audited_inputs(Path(args.paper_root), args.stamp)
    try:
        problems, advisories = check(
            Path(args.paper_root),
            manuscript=Path(args.manuscript) if args.manuscript else None,
            bib=Path(args.bib) if args.bib else None,
            proof_ledger=Path(args.proof_ledger) if args.proof_ledger else None,
            citation_ledger=(
                Path(args.citation_ledger) if args.citation_ledger else None
            ),
            figure_ledger=(
                Path(args.figure_ledger) if args.figure_ledger else None
            ),
            manifest=Path(args.manifest) if args.manifest else None,
        )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    return emit(problems, advisories)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
