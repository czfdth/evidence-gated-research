"""Create a new paper project from the template repository."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import yaml

from ccfa.stages import gate_for
from ccfa.texdoc import find_main_tex
from ccfa.milestones import parse_deadline
from newpaper.venues import resolve_venue

TEMPLATE_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PAPERS_ROOT = TEMPLATE_ROOT / "papers"

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# Windows reserves these device names before the first dot.
WINDOWS_RESERVED_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        "com1",
        "com2",
        "com3",
        "com4",
        "com5",
        "com6",
        "com7",
        "com8",
        "com9",
        "lpt1",
        "lpt2",
        "lpt3",
        "lpt4",
        "lpt5",
        "lpt6",
        "lpt7",
        "lpt8",
        "lpt9",
    }
)

PAPER_DIRS = [
    "manuscript/sections",
    "data",
    "experiments/log",
    "experiments/results",
    "figures",
    "tables",
    "reviews",
    "submission/repro",
    "memory",
    "ccfa-workfiles/literature",
    "ccfa-workfiles/figures",
    "ccfa-workfiles/writing",
    "ara-input/src/execution",
]

SEED_FILES = {
    "memory/ideas.md": "# 选题记忆\n",
    "memory/dead-ends.md": "# 反重复记忆\n",
    "reviews/revision-ledger.md": "# 审稿意见矩阵\n",
    "submission/checks.md": (
        "# 投稿检查\n"
        "\n"
        "数字覆盖率报告由工具生成，见 `submission/claims-coverage.md`"
        "（机器记录：`submission/claims-coverage.json`）。\n"
    ),
    "data/provenance.json": '{\n  "version": 1,\n  "files": {}\n}\n',
    "data/claims.yaml": (
        "version: 1\n"
        "# 节名按标题文本匹配（大小写/空白归一化）；名字必须能在 manuscript\n"
        "# 中找到标题，否则 final_check 报 claims-policy-unknown-section。\n"
        "protected_sections:\n"
        "  - abstract\n"
        "  - contributions\n"
        "  - results\n"
        "# waiver 必填 file/line_text/reason/date/author；line_text 大小写不敏感、\n"
        "# 空白归一化，命中同文件多处时全部豁免并在 advisory 中标注命中 N 处。\n"
        "# 如需精确到单行，加可选 line: <1 起的行号>。\n"
        "waivers: []\n"
    ),
    "data/novelty-audit.yaml": (
        "version: 1\n"
        "# 完成文献检索后填写；结构见 "
        "docs/plans/2026-10-04-governance-statistics-novelty.md。\n"
        "search:\n"
        "  databases: []\n"
        "  queries: []\n"
        "  searched_at: null\n"
        "  cutoff: null\n"
        "neighbors: []\n"
        "claims: []\n"
    ),
    "data/statistics-plan.yaml": (
        "version: 1\n"
        "alpha: null\n"
        "multiple_comparison: ''\n"
        "claims: []\n"
    ),
    "data/governance.yaml": (
        "version: 1\n"
        "authors: []\n"
        "conflicts: []\n"
        "ethics:\n"
        "  human_subjects: false\n"
        "  data_license: ''\n"
        "ai_usage:\n"
        "  disclosed: false\n"
        "  policy: ''\n"
        "plagiarism:\n"
        "  checked: false\n"
        "  tool: ''\n"
        "  date: null\n"
        "responsible_disclosure:\n"
        "  dual_use_reviewed: false\n"
        "  disclosure_contact: ''\n"
        "  notes: ''\n"
    ),
    "data/repro-environment.yaml": (
        "version: 1\n"
        "python: ''\n"
        "package_manager: ''\n"
        "requirements: ''\n"
        "lockfile: ''\n"
        "lockfile_sha256: ''\n"
        "system_tools: []\n"
    ),
    "data/figure-support.yaml": (
        "version: 1\n"
        "# 完成后填写；结构见 "
        "docs/plans/2026-10-04-figure-support-audit.md。\n"
        "figures: []\n"
    ),
    "data/claim-registry.yaml": (
        "version: 1\n"
        "# claim 是中心对象：把 proof、experiment、figure、citation、\n"
        "# assumption 与 limitation 链接到同一个 id。\n"
        "claims: []\n"
    ),
    "data/assumptions-limitations.yaml": (
        "version: 1\n"
        "assumptions: []\n"
        "limitations: []\n"
    ),
    "data/venue-checklist.yaml": (
        "version: 1\n"
        "venue: ''\n"
        "source: ''\n"
        "items: []\n"
    ),
    "data/artifact-provenance.yaml": (
        "version: 1\n"
        "artifacts: []\n"
    ),
    "data/exploration-graph.yaml": (
        "version: 1\n"
        "entries: []\n"
    ),
    "data/cost-ledger.yaml": (
        "version: 1\n"
        "currency: ''\n"
        "paper: ''\n"
        "entries: []\n"
    ),
    "data/risk-register.yaml": (
        "version: 1\n"
        "risks: []\n"
    ),
    "data/capability-matrix.yaml": (
        "version: 1\n"
        "capabilities: []\n"
    ),
    "data/data-flows.yaml": (
        "version: 1\n"
        "network: []\n"
        "stores: []\n"
    ),
    "data/experiment-loop.yaml": (
        "version: 1\n"
        "not_applicable: false\n"
        "not_applicable_reason: ''\n"
        "ideas: []\n"
        "inner_loop: []\n"
        "outer_loop: []\n"
    ),
    "data/post-submission.yaml": (
        "version: 1\n"
        "rebuttal:\n"
        "  status: not-started\n"
        "  response_ledger: ''\n"
        "  new_evidence_run_ids: []\n"
        "  commitments: []\n"
        "resubmit:\n"
        "  status: not-started\n"
        "  from_venue: ''\n"
        "  to_venue: ''\n"
        "  venue_diff: []\n"
        "  sections_to_rewrite: []\n"
        "talk:\n"
        "  status: not-started\n"
        "  slide_outline: []\n"
    ),
    "data/rigor-rubric.yaml": (
        "version: 1\n"
        "status: not-started\n"
        "reviewed_by:\n"
        "  kind: ''\n"
        "  identity: ''\n"
        "  reviewed_at: ''\n"
        "dimensions:\n"
        "  evidence_relevance:\n"
        "    score: null\n"
        "    rationale: ''\n"
        "    evidence: []\n"
        "  falsifiability:\n"
        "    score: null\n"
        "    rationale: ''\n"
        "    evidence: []\n"
        "  scope:\n"
        "    score: null\n"
        "    rationale: ''\n"
        "    evidence: []\n"
        "  coherence:\n"
        "    score: null\n"
        "    rationale: ''\n"
        "    evidence: []\n"
        "  exploration_integrity:\n"
        "    score: null\n"
        "    rationale: ''\n"
        "    evidence: []\n"
        "  methodology:\n"
        "    score: null\n"
        "    rationale: ''\n"
        "    evidence: []\n"
    ),
    "data/proof-campaign.yaml": (
        "version: 1\n"
        "not_applicable: false\n"
        "not_applicable_reason: ''\n"
        "campaigns: []\n"
    ),
    "data/artifact-badge.yaml": (
        "version: 1\n"
        "status: not-started\n"
        "doi: ''\n"
        "archive_url: ''\n"
        "license:\n"
        "  code: ''\n"
        "  data: ''\n"
        "badges:\n"
        "  available:\n"
        "    status: not-started\n"
        "    evidence: []\n"
        "    rationale: ''\n"
        "  evaluated:\n"
        "    status: not-started\n"
        "    evidence: []\n"
        "    rationale: ''\n"
        "    independent_reviewer: ''\n"
        "    reviewed_at: ''\n"
        "  reusable:\n"
        "    status: not-started\n"
        "    evidence: []\n"
        "    rationale: ''\n"
        "    reuse_context: ''\n"
    ),
    "ara-input/README.md": (
        "# ARA semantic input\n"
        "\n"
        "Provide source-grounded semantic layers for `ara-compile`:\n"
        "\n"
        "- problem.yaml\n"
        "- concepts.yaml\n"
        "- solution.yaml\n"
        "- related_work.yaml\n"
        "- experiments.yaml\n"
        "- configs.yaml\n"
        "- trace.yaml\n"
        "- evidence.yaml\n"
        "- src/execution/*.py\n"
    ),
}

GitRunner = Callable[[list[str], Path], "tuple[int, str]"]

INITIAL_COMMIT_MESSAGE = "chore: initialize paper repository"
DEFAULT_GIT_NAME = "Paper Workbench"
DEFAULT_GIT_EMAIL = "paper@localhost"

# Paper-level ignore rules. Build PDFs next to the manuscript stay out of the
# repository; delivery PDFs under submission/ and figure assets under
# manuscript/figs/ are source material and must be tracked.
PAPER_GITIGNORE = """\
# TeX build products (regenerable)
*.aux
*.bbl
*.blg
*.fdb_latexmk
*.fls
*.log
*.out
*.synctex.gz
*.toc
*.xdv

# Python caches
__pycache__/
*.pyc

# Generated PDFs are build output; keep delivery and figure PDFs tracked.
*.pdf
!submission/**/*.pdf
!manuscript/figs/**/*.pdf
!figures/**/*.pdf
"""

PAPER_GITATTRIBUTES = "* text=auto eol=lf\n"


class InvalidSlugError(ValueError):
    """Raised when a slug is not safe to use as a directory name."""


def _default_git_runner(args: list[str], cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def _git_or_error(
    args: list[str],
    cwd: Path,
    runner: GitRunner,
) -> str:
    code, output = runner(list(args), Path(cwd))
    if code != 0:
        detail = output.strip() or f"git 退出码 {code}"
        raise ValueError(f"git {' '.join(args)} 失败: {detail}")
    return output


def _identity_overrides(runner: GitRunner, target: Path) -> list[str]:
    """Return command-scoped ``-c`` identity flags when git has none.

    Global configuration is never written; the fallback lives only in the
    single ``git commit`` invocation.
    """
    overrides: list[str] = []
    name_code, name = runner(["config", "user.name"], target)
    if name_code != 0 or not name.strip():
        overrides.extend(["-c", f"user.name={DEFAULT_GIT_NAME}"])
    email_code, email = runner(["config", "user.email"], target)
    if email_code != 0 or not email.strip():
        overrides.extend(["-c", f"user.email={DEFAULT_GIT_EMAIL}"])
    return overrides


def init_paper_repository(
    target: Path,
    *,
    runner: GitRunner | None = None,
) -> str:
    """Make *target* its own git repository with one initial commit.

    Returns the first commit hash. Any failure propagates so ``create_project``
    can remove the half-scaffolded directory.
    """
    run = runner or _default_git_runner
    target = Path(target)
    _git_or_error(["init", "-q"], target, run)
    (target / ".gitignore").write_text(PAPER_GITIGNORE, encoding="utf-8")
    (target / ".gitattributes").write_text(
        PAPER_GITATTRIBUTES,
        encoding="utf-8",
    )
    _git_or_error(["add", "-A"], target, run)
    overrides = _identity_overrides(run, target)
    _git_or_error(
        [*overrides, "commit", "-q", "-m", INITIAL_COMMIT_MESSAGE],
        target,
        run,
    )
    return _git_or_error(["rev-parse", "HEAD"], target, run).strip()


def validate_slug(slug: str) -> str:
    """Return the slug unchanged; raise when it could escape the papers root."""
    if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
        raise InvalidSlugError(
            f"非法 slug: {slug!r}；只允许 [a-z0-9._-]，且必须由小写字母或数字开头"
        )
    stem = slug.split(".", 1)[0]
    if stem.lower() in WINDOWS_RESERVED_NAMES:
        raise InvalidSlugError(
            f"非法 slug: {slug!r}；{stem!r} 是 Windows 保留设备名，不能作为目录名"
        )
    return slug


class _QuotedString(str):
    """Marker type emitted in double quotes so scalars cannot change type."""


class _StateDumper(yaml.SafeDumper):
    """SafeDumper that writes _QuotedString values in double quotes."""


_StateDumper.add_representer(
    _QuotedString,
    lambda dumper, value: dumper.represent_scalar(
        "tag:yaml.org,2002:str", str(value), style='"'
    ),
)


def _quote_strings(value: object) -> object:
    """Return the structure with every string leaf wrapped as _QuotedString."""
    if isinstance(value, str):
        return _QuotedString(value)
    if isinstance(value, dict):
        return {key: _quote_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_quote_strings(item) for item in value]
    return value


def create_project(
    papers_root: Path,
    slug: str,
    venue: str,
    year: str,
    mode: str,
    title: str,
    deadline: str | None = None,
    git_runner: GitRunner | None = None,
) -> Path:
    slug = validate_slug(slug)
    deadline_date = parse_deadline(deadline)
    root = Path(papers_root).resolve()
    target = (root / slug).resolve()
    if not target.is_relative_to(root):
        raise InvalidSlugError(f"非法 slug: {slug!r}；目标目录逃出 papers root {root}")
    if target.exists():
        raise FileExistsError(f"目标目录已存在，拒绝覆盖: {target}")

    venue_dir = resolve_venue(venue)
    root_existed = root.is_dir()
    created_target = False
    try:
        target.mkdir(parents=True)
        created_target = True

        for rel in PAPER_DIRS:
            (target / rel).mkdir(parents=True, exist_ok=True)

        manuscript = target / "manuscript"
        shutil.copytree(
            venue_dir,
            manuscript,
            dirs_exist_ok=True,
            copy_function=shutil.copy2,
        )

        shared_bib = TEMPLATE_ROOT / "library" / "refs.bib"
        bib_target = manuscript / "references.bib"
        if shared_bib.is_file():
            shutil.copy2(shared_bib, bib_target)
        else:
            bib_target.write_text("", encoding="utf-8")

        main_tex = find_main_tex(manuscript)
        main_rel = main_tex.relative_to(target).as_posix()

        date = dt.date.today().isoformat()
        state = yaml.safe_load(
            (TEMPLATE_ROOT / "ccfa.yaml.template").read_text(encoding="utf-8")
        )
        if not isinstance(state, dict):
            raise ValueError("ccfa.yaml.template 顶层必须是映射")
        state["project"]["title"] = title
        state["project"]["short_name"] = slug
        state["target_venue"]["name"] = venue
        state["target_venue"]["year"] = str(year)
        state["target_venue"]["mode"] = mode
        state["target_venue"]["deadline"] = (
            deadline_date.isoformat() if deadline_date else None
        )
        state["stage"]["updated_at"] = date
        state["artifacts"]["manuscript"] = main_rel
        rendered = yaml.dump(
            _quote_strings(state),
            Dumper=_StateDumper,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            line_break="\n",
        )
        (target / "ccfa.yaml").write_text(rendered, encoding="utf-8")

        for rel, content in SEED_FILES.items():
            (target / rel).write_text(content, encoding="utf-8")

        init_paper_repository(target, runner=git_runner)
    except BaseException:
        # A failed scaffold must not block a retry with leftover files.
        if created_target:
            shutil.rmtree(target, ignore_errors=True)
        if not root_existed:
            try:
                root.rmdir()
            except OSError:
                pass
        raise

    return target


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="派生一个新的论文项目")
    parser.add_argument("slug")
    parser.add_argument("--venue", required=True)
    parser.add_argument("--year", required=True)
    parser.add_argument("--mode", required=True, choices=["conference", "journal"])
    parser.add_argument("--title", default="")
    parser.add_argument("--deadline")
    parser.add_argument(
        "--papers-root",
        default=str(DEFAULT_PAPERS_ROOT),
    )
    args = parser.parse_args(argv[1:])

    try:
        target = create_project(
            papers_root=Path(args.papers_root),
            slug=args.slug,
            venue=args.venue,
            year=args.year,
            mode=args.mode,
            title=args.title or args.slug,
            deadline=args.deadline,
        )
    except (FileExistsError, InvalidSlugError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"工具错误: {exc}", file=sys.stderr)
        return 2

    gate = gate_for(args.mode, "idea")
    print(str(target))
    print(f"起始 gate: {gate.id} — {gate.criterion}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
