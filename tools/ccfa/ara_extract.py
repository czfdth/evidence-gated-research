"""Deterministic front-end that turns local paper artifacts into ARA semantic input.

This is not an LLM paper reader. It extracts only what is mechanically present in
the repository and records every unresolved semantic field in
``ara-input/EXTRACTION_REPORT.json`` instead of inventing content.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

from ccfa.bib import load_records
from ccfa.cli import save_text_atomically, tool_error


CLAIM_REGISTRY = Path("data") / "claim-registry.yaml"
EXPLORATION_GRAPH = Path("data") / "exploration-graph.yaml"
FIGURE_MANIFEST = Path("figures") / "manifest.yaml"
RUN_LOG_DIR = Path("experiments") / "log"
REFERENCES = Path("manuscript") / "references.bib"
OUTPUT_DIR = Path("ara-input")
SECTION_RE = re.compile(
    r"\\(?:section|subsection)\*?\s*(?:\[[^\]]*\]\s*)*\{([^{}]*)\}"
)


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _run_records(paper_root: Path) -> list[dict]:
    log_dir = paper_root / RUN_LOG_DIR
    if not log_dir.is_dir():
        return []
    records = []
    for path in sorted(log_dir.glob("*.json")):
        payload = _load_json(path)
        if payload and isinstance(payload.get("run_id"), str):
            records.append(payload)
    return records


def _tex_sections(paper_root: Path) -> list[str]:
    manuscript = paper_root / "manuscript"
    if not manuscript.is_dir():
        return []
    sections = []
    for path in sorted(manuscript.rglob("*.tex")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in SECTION_RE.finditer(text):
            title = match.group(1).strip()
            if title:
                sections.append(title)
    return sections


def _bib_entries(paper_root: Path) -> list[dict]:
    path = paper_root / REFERENCES
    if not path.is_file():
        return []
    try:
        records = load_records(path).records
    except ValueError:
        return []
    return [
        {
            "key": key,
            "title": record.title,
            "authors": record.authors,
            "year": record.year,
            "venue": record.venue,
            "doi": record.doi,
        }
        for key, record in sorted(records.items())
    ]


def _claims(paper_root: Path) -> list[dict]:
    payload = _load_yaml(paper_root / CLAIM_REGISTRY)
    claims = payload.get("claims")
    return [item for item in claims if isinstance(item, dict)] if isinstance(claims, list) else []


def _exploration_entries(paper_root: Path) -> list[dict]:
    payload = _load_yaml(paper_root / EXPLORATION_GRAPH)
    entries = payload.get("entries")
    return [item for item in entries if isinstance(item, dict)] if isinstance(entries, list) else []


def _figures(paper_root: Path) -> list[dict]:
    payload = _load_yaml(paper_root / FIGURE_MANIFEST)
    figures = payload.get("figures")
    return [item for item in figures if isinstance(item, dict)] if isinstance(figures, list) else []


def _table_files(paper_root: Path) -> list[Path]:
    tables = paper_root / "tables"
    if not tables.is_dir():
        return []
    return [
        path
        for path in sorted(tables.iterdir())
        if path.is_file() and path.suffix.casefold() in {".csv", ".json", ".md"}
    ]


def _split_csv_line(line: str) -> list[str]:
    return [cell.strip() for cell in line.split(",")]


def _table_rows(path: Path) -> list[list[str]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if path.suffix.casefold() == ".csv":
        return [_split_csv_line(line) for line in lines if line.strip()]
    if path.suffix.casefold() == ".json":
        payload = _load_json(path)
        if payload:
            return [["key", "value"], *[[str(k), str(v)] for k, v in payload.items()]]
        return []
    rows = []
    for line in lines:
        if line.strip().startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            rows.append(cells)
    return rows


def _write(path: Path, payload: dict) -> None:
    save_text_atomically(
        path,
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        description="ARA semantic input",
    )


def extract(
    paper_root: Path,
    *,
    out_dir: Path | None = None,
    force: bool = False,
) -> dict:
    paper_root = Path(paper_root).resolve()
    out = out_dir or (paper_root / OUTPUT_DIR)
    out = out if out.is_absolute() else paper_root / out
    if out.exists():
        if not force:
            raise ValueError(f"ARA input 已存在，拒绝覆盖: {out}")
        shutil.rmtree(out)
    out.mkdir(parents=True)

    state = _load_yaml(paper_root / "ccfa.yaml")
    project = state.get("project") if isinstance(state.get("project"), dict) else {}
    claims = _claims(paper_root)
    runs = _run_records(paper_root)
    sections = _tex_sections(paper_root)
    bib = _bib_entries(paper_root)
    figures = _figures(paper_root)
    tables = _table_files(paper_root)
    exploration = _exploration_entries(paper_root)

    observations = []
    for index, claim in enumerate(claims, start=1):
        observations.append(
            {
                "id": f"O{index}",
                "title": str(claim.get("id", f"claim-{index}")),
                "statement": str(claim.get("statement") or "Not specified in provided input."),
                "evidence": str(claim.get("experiments") or claim.get("proof") or "Not specified in provided input."),
                "implication": "Derived from claim registry; human review required.",
            }
        )
    if not observations:
        observations.append(
            {
                "id": "O1",
                "title": "Missing problem statement",
                "statement": "No claim registry entry was available.",
                "evidence": "None",
                "implication": "Fill data/claim-registry.yaml before compiling a full ARA.",
            }
        )
    problem = {
        "observations": observations,
        "gaps": [
            {
                "id": "G1",
                "title": "Gap not extracted",
                "statement": "No explicit research gap was found in structured inputs.",
                "caused_by": ["O1"],
                "existing_attempts": "Not specified in provided input.",
                "why_they_fail": "Not specified in provided input.",
            }
        ],
        "key_insight": {
            "insight": project.get("title") or "Not specified in provided input.",
            "derived_from": ["O1"],
            "enables": "Review and complete ara-input/problem.yaml.",
        },
        "assumptions": [
            "Derived from local structured inputs; semantic fields marked as not specified require human completion."
        ],
    }
    _write(out / "problem.yaml", problem)

    concept_names = sections[:5]
    while len(concept_names) < 5:
        concept_names.append(f"Concept {len(concept_names) + 1}")
    concepts = {
        "concepts": [
            {
                "term": name,
                "notation": "",
                "definition": "Derived from manuscript section heading; requires human review.",
                "boundary_conditions": "Not specified in provided input.",
                "related": [],
            }
            for name in concept_names
        ]
    }
    _write(out / "concepts.yaml", concepts)

    experiment_entries = []
    for index, run in enumerate(runs, start=1):
        experiment_entries.append(
            {
                "id": f"E{index:02d}",
                "title": str(run.get("run_id")),
                "verifies": [c.get("id") for c in claims if run.get("run_id") in (c.get("experiments") or [])],
                "setup": {"Source": "experiments/log/" + str(run.get("run_id")) + ".json"},
                "procedure": ["See recorded run."],
                "metrics": str(run.get("metrics") or "Not specified in provided input."),
                "expected_outcome": "Not specified in provided input.",
                "baselines": [],
                "dependencies": "none",
            }
        )
    while len(experiment_entries) < 3:
        index = len(experiment_entries) + 1
        experiment_entries.append(
            {
                "id": f"E{index:02d}",
                "title": f"Missing experiment {index}",
                "verifies": [],
                "setup": {"Source": "Not specified in provided input."},
                "procedure": ["Not specified in provided input."],
                "metrics": "Not specified in provided input.",
                "expected_outcome": "Not specified in provided input.",
                "baselines": [],
                "dependencies": "none",
            }
        )
    _write(out / "experiments.yaml", {"experiments": experiment_entries})

    related = []
    for index, entry in enumerate(bib, start=1):
        related.append(
            {
                "id": f"RW{index}",
                "citation": f"{entry.get('authors') or 'Unknown'} {entry.get('year') or ''}".strip(),
                "doi": entry.get("doi") or "",
                "type": "baseline",
                "delta": {"what_changed": "Not specified in provided input.", "why": "Not specified in provided input."},
                "claims_affected": [],
                "adopted_elements": [],
            }
        )
    if not related:
        related.append(
            {
                "id": "RW1",
                "citation": "Missing related work",
                "doi": "",
                "type": "baseline",
                "delta": {"what_changed": "Not specified in provided input.", "why": "Not specified in provided input."},
                "claims_affected": [],
                "adopted_elements": [],
            }
        )
    _write(out / "related_work.yaml", {"entries": related})

    architecture = []
    for name in sections[:3]:
        architecture.append(
            {
                "name": name,
                "purpose": "Derived from manuscript section heading; requires human review.",
                "inputs": [],
                "outputs": [],
                "interactions": "Not specified in provided input.",
                "design_choices": "Not specified in provided input.",
            }
        )
    if not architecture:
        architecture.append(
            {
                "name": "Missing architecture",
                "purpose": "Not specified in provided input.",
                "inputs": [],
                "outputs": [],
                "interactions": "Not specified in provided input.",
                "design_choices": "Not specified in provided input.",
            }
        )
    _write(
        out / "solution.yaml",
        {
            "architecture": architecture,
            "algorithm": {
                "math": "Not specified in provided input.",
                "pseudocode": "Not specified in provided input.",
                "complexity": "Not specified in provided input.",
            },
            "constraints": ["Not specified in provided input."],
            "heuristics": [
                {
                    "id": "H1",
                    "description": "Missing heuristic",
                    "rationale": "Not specified in provided input.",
                    "sensitivity": "low",
                    "bounds": "Not specified in provided input.",
                    "code_ref": "src/execution/core.py",
                    "source": "Not specified in provided input.",
                }
            ],
        },
    )

    _write(
        out / "configs.yaml",
        {
            "training": [
                {
                    "name": "Not specified",
                    "value": "Not specified",
                    "rationale": "Not specified in provided input.",
                    "search_range": "",
                    "sensitivity": "low",
                    "source": "Not specified in provided input.",
                }
            ],
            "model": [
                {
                    "name": "Not specified",
                    "value": "Not specified",
                    "rationale": "Not specified in provided input.",
                    "search_range": "",
                    "sensitivity": "low",
                    "source": "Not specified in provided input.",
                }
            ],
        },
    )

    trace_children = []
    for index, entry in enumerate(exploration, start=2):
        kind = entry.get("kind")
        node_id = f"N{index:02d}"
        title = str(entry.get("summary") or "Not specified in provided input.")
        if kind in {"dead-end", "rejected"}:
            trace_children.append(
                {
                    "id": node_id,
                    "type": "dead_end",
                    "support_level": "inferred",
                    "title": title,
                    "hypothesis": title,
                    "failure_mode": str(entry.get("rationale") or "Not specified in provided input."),
                    "lesson": "Review exploration-graph entry.",
                }
            )
        elif kind == "pivot":
            trace_children.append(
                {
                    "id": node_id,
                    "type": "pivot",
                    "support_level": "inferred",
                    "title": title,
                    "from": "previous trajectory",
                    "to": title,
                    "trigger": str(entry.get("rationale") or "Not specified in provided input."),
                }
            )
        else:
            trace_children.append(
                {
                    "id": node_id,
                    "type": "experiment",
                    "support_level": "inferred",
                    "title": title,
                    "result": title,
                    "evidence": [],
                }
            )
    if len(trace_children) < 6:
        for index in range(len(trace_children) + 2, 8):
            trace_children.append(
                {
                    "id": f"N{index:02d}",
                    "type": "experiment",
                    "support_level": "inferred",
                    "title": "Missing trace node",
                    "result": "Not specified in provided input.",
                    "evidence": [],
                }
            )
    trace_children.append(
        {
            "id": "N07",
            "type": "decision",
            "support_level": "inferred",
            "title": "Decision not extracted",
            "choice": "Not specified in provided input.",
            "alternatives": ["Not specified in provided input."],
            "evidence": "Review ara-input/trace.yaml.",
        }
    )
    _write(
        out / "trace.yaml",
        {
            "tree": [
                {
                    "id": "N01",
                    "type": "question",
                    "support_level": "inferred",
                    "title": str(project.get("title") or "Research question"),
                    "description": "Derived from ccfa.yaml; requires review.",
                    "children": trace_children,
                }
            ]
        },
    )

    tables_payload = []
    for path in tables:
        tables_payload.append(
            {
                "filename": f"derived_{path.stem}.md",
                "source": f"{path.relative_to(paper_root).as_posix()} (derived)",
                "caption": "Derived from repository table; review before use.",
                "extraction_type": "derived_subset",
                "rows": _table_rows(path),
            }
        )
    figures_payload = []
    for figure in figures:
        figure_id = figure.get("id") or figure.get("name")
        if not figure_id:
            continue
        figures_payload.append(
            {
                "filename": f"{figure_id}.md",
                "source": f"figures/manifest.yaml {figure_id}",
                "caption": "Derived from figure manifest; review before use.",
                "extraction_type": "derived_subset",
                "rows": [
                    ["field", "value"],
                    ["path", str(figure.get("path", ""))],
                    ["sha256", str(figure.get("sha256", ""))],
                ],
            }
        )
    _write(
        out / "evidence.yaml",
        {"tables": tables_payload, "figures": figures_payload},
    )

    report = {
        "status": "draft",
        "paper_root": str(paper_root),
        "claims": len(claims),
        "runs": len(runs),
        "sections": len(sections),
        "bib_entries": len(bib),
        "figures": len(figures),
        "tables": len(tables),
        "exploration_entries": len(exploration),
        "seal_level1_ready": bool(
            len(claims) > 0
            and len(runs) >= 3
            and len(bib) > 0
            and (figures or tables)
        ),
        "unresolved": [
            "concepts definitions",
            "solution algorithm/architecture",
            "related-work deltas",
            "heuristics",
            "configs",
            "experiment setup/procedure/expected outcome",
            "trace source references",
        ],
    }
    save_text_atomically(
        out / "EXTRACTION_REPORT.json",
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="ARA extraction report",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从本地论文材料抽取 ARA semantic input（deterministic）"
    )
    parser.add_argument("--paper-root", required=True)
    parser.add_argument("--out")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        report = extract(
            Path(args.paper_root),
            out_dir=Path(args.out) if args.out else None,
            force=args.force,
        )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
