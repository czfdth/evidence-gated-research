"""Build a read-only replay timeline from run, passport, artifact, and review state."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error


RUN_LEDGER = Path("experiments") / "log" / "run-ledger.jsonl"
ARTIFACT_MANIFEST = Path("ccfa-workfiles") / "artifact-store" / "manifest.json"
PASSPORT_LEDGER = Path("ccfa-workfiles") / "passport" / "run-ledger.yaml"
REVIEW_STATE = Path("reviews") / "review-loop-state.json"


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _run_ledger_entries(paper_root: Path) -> list[dict]:
    path = paper_root / RUN_LEDGER
    if not path.is_file():
        return []
    entries = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def build_replay(paper_root: Path) -> dict:
    paper_root = Path(paper_root).resolve()
    run_entries = _run_ledger_entries(paper_root)
    run_ids = {
        entry["run_id"]
        for entry in run_entries
        if isinstance(entry.get("run_id"), str)
    }
    passport = _load_yaml(paper_root / PASSPORT_LEDGER)
    passport_entries = passport.get("entries")
    passport_entries = (
        passport_entries if isinstance(passport_entries, list) else []
    )
    for entry in passport_entries:
        if isinstance(entry, dict):
            data = entry.get("data")
            if isinstance(data, dict) and isinstance(data.get("run_id"), str):
                run_ids.add(data["run_id"])
    manifest = _load_json(paper_root / ARTIFACT_MANIFEST)
    artifacts = manifest.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    steps = []
    for entry in passport_entries:
        if not isinstance(entry, dict):
            continue
        steps.append(
            {
                "kind": "passport",
                "id": entry.get("seq"),
                "title": entry.get("kind", "event"),
                "details": entry.get("data", {}),
            }
        )
    for entry in run_entries:
        steps.append(
            {
                "kind": "run",
                "id": entry.get("run_id"),
                "title": entry.get("status", "run"),
                "details": entry,
            }
        )
    artifact_count = 0
    for artifact_id, versions in artifacts.items():
        if not isinstance(versions, list):
            continue
        for entry in versions:
            if not isinstance(entry, dict):
                continue
            artifact_count += 1
            steps.append(
                {
                    "kind": "artifact",
                    "id": f"{artifact_id}@v{entry.get('version')}",
                    "title": artifact_id,
                    "details": entry,
                }
            )
    review_state = _load_json(paper_root / REVIEW_STATE)
    if review_state:
        steps.append(
            {
                "kind": "review-loop",
                "id": review_state.get("run_id"),
                "title": review_state.get("last_verdict", "review"),
                "details": review_state,
            }
        )
    return {
        "run_ids": sorted(run_ids),
        "run_count": len(run_ids),
        "artifact_count": artifact_count,
        "review_state": review_state,
        "steps": steps,
    }


def check_replay(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    replay = build_replay(paper_root)
    problems: list[Problem] = []
    run_ids = set(replay["run_ids"])
    manifest = _load_json(paper_root / ARTIFACT_MANIFEST)
    if not manifest:
        return [], [
            Problem(
                "session-replay-not-configured",
                str(paper_root / ARTIFACT_MANIFEST),
                None,
                "artifact manifest 不存在，无法构建 artifact replay",
            )
        ]
    for artifact_id, versions in manifest.get("artifacts", {}).items():
        if not isinstance(versions, list):
            continue
        for entry in versions:
            if not isinstance(entry, dict):
                continue
            run_id = entry.get("run_id")
            if run_id is not None and run_id not in run_ids:
                problems.append(
                    Problem(
                        "session-replay-dangling-run",
                        str(paper_root / ARTIFACT_MANIFEST),
                        None,
                        f"{artifact_id} v{entry.get('version')} 引用了不存在的 run: {run_id!r}",
                    )
                )
    return problems, []


def render_html(replay: dict) -> str:
    lines = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><title>Research Session Replay</title>",
        "<style>body{font-family:sans-serif;max-width:1000px;margin:2rem auto}"
        ".step{border-left:4px solid #888;padding:.5rem 1rem;margin:.5rem 0}"
        "pre{white-space:pre-wrap}</style></head><body>",
        "<h1>Research Session Replay</h1>",
        f"<p>runs: {len(replay.get('run_ids', []))}; "
        f"artifacts: {replay.get('artifact_count', 0)}</p>",
        "<h2>Timeline</h2>",
    ]
    for step in replay.get("steps", []):
        lines.append(
            "<div class='step'>"
            f"<strong>{html.escape(str(step.get('kind')))}</strong> "
            f"{html.escape(str(step.get('id')))}: "
            f"{html.escape(str(step.get('title'))) }"
            f"<pre>{html.escape(json.dumps(step.get('details', {}), ensure_ascii=False, indent=2))}</pre>"
            "</div>"
        )
    lines.extend(["</body></html>"])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="research session replay")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("--paper-root", required=True)
    render = sub.add_parser("render")
    render.add_argument("--paper-root", required=True)
    render.add_argument("--out", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        paper_root = Path(args.paper_root)
        if args.command == "check":
            problems, advisories = check_replay(paper_root)
            return emit(problems, advisories)
        Path(args.out).write_text(
            render_html(build_replay(paper_root)),
            encoding="utf-8",
        )
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
