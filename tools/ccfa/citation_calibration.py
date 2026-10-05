"""Compute FNR/FPR calibration for citation-support judgements.

``score`` measures a judge against a labelled set. ``build`` produces that set
from a real project so the numbers are not fabricated: clean cases are the
project's own verified entries, and negative cases are defects *constructed*
on purpose, so each label is objectively true rather than an opinion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ccfa import citation_guard
from ccfa.bib import load_records
from ccfa.cli import save_text_atomically, tool_error

# Each constructed defect has a code the guard is supposed to raise. A miss is
# a false negative; raising it on a clean entry would be a false positive.
CONSTRUCTED_DEFECTS = {
    "ledger-missing": "unverified-entry",
    "evidence-null": "citation-self-asserted",
    "duplicate-doi": "duplicate-doi",
    "dangling-cite": "dangling-cite",
}
GENERATOR = "ccfa.citation_calibration/build"


def _load_jsonl(path: Path) -> dict[str, dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc
    rows: dict[str, dict] = {}
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: JSON 非法: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
            raise ValueError(f"{path}:{line_number}: 缺少字符串 id")
        item_id = payload["id"]
        if item_id in rows:
            raise ValueError(f"{path}:{line_number}: 重复 id: {item_id}")
        rows[item_id] = payload
    return rows


def calibrate(
    gold_path: Path,
    prediction_path: Path,
    *,
    max_fnr: float = 0.15,
    max_fpr: float = 0.10,
) -> dict:
    gold = _load_jsonl(Path(gold_path))
    predictions = _load_jsonl(Path(prediction_path))
    tp = fp = tn = fn = 0
    missing = []
    invalid = []
    if not gold:
        return {
            "tp": 0,
            "fp": 0,
            "tn": 0,
            "fn": 0,
            "fnr": 0.0,
            "fpr": 0.0,
            "missing": [],
            "invalid": [],
            "gold_count": 0,
            "prediction_count": len(predictions),
            "max_fnr": max_fnr,
            "max_fpr": max_fpr,
            "threshold_pass": False,
            "error": "gold-set-empty",
        }
    for item_id, row in gold.items():
        label = row.get("label")
        if label not in {"supported", "unsupported"}:
            invalid.append(item_id)
            continue
        predicted_row = predictions.get(item_id)
        if predicted_row is None:
            missing.append(item_id)
            continue
        prediction = predicted_row.get("prediction")
        if prediction not in {"supported", "unsupported"}:
            invalid.append(item_id)
            continue
        if label == "supported" and prediction == "supported":
            tp += 1
        elif label == "unsupported" and prediction == "supported":
            fp += 1
        elif label == "unsupported" and prediction == "unsupported":
            tn += 1
        else:
            fn += 1
    fnr = fn / (fn + tp) if (fn + tp) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "fnr": fnr,
        "fpr": fpr,
        "missing": sorted(missing),
        "invalid": sorted(invalid),
        "gold_count": len(gold),
        "prediction_count": len(predictions),
        "max_fnr": max_fnr,
        "max_fpr": max_fpr,
        "threshold_pass": (
            not missing
            and not invalid
            and fnr <= max_fnr
            and fpr <= max_fpr
        ),
    }


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_ledger_entries(path: Path) -> dict[str, dict]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取引用台账 {path}: {exc}") from exc
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, dict) or not entries:
        raise ValueError(f"引用台账缺少非空 entries: {path}")
    return entries


def _guard(
    manuscript: Path,
    bib: Path,
    ledger: Path,
) -> tuple[list, list]:
    return citation_guard.check(Path(manuscript), Path(bib), Path(ledger))


def _write_temp_ledger(directory: Path, entries: dict[str, dict]) -> Path:
    path = Path(directory) / "citation-ledger.json"
    path.write_text(
        json.dumps(
            {"version": 1, "entries": entries},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _codes_for(problems: list, token: str) -> list[str]:
    return sorted(
        {problem.code for problem in problems if token in problem.message}
    )


def build_dataset(
    paper_root: Path,
    *,
    sample: int | None = None,
) -> dict:
    """Construct an objectively-labelled gold set and its guard predictions."""
    paper_root = Path(paper_root).resolve()
    manuscript = paper_root / "manuscript"
    bib = manuscript / "references.bib"
    ledger_path = paper_root / "data" / "citation-ledger.json"
    for path in (manuscript, bib, ledger_path):
        if not path.exists():
            raise ValueError(f"缺少校准输入: {path}")

    entries = _load_ledger_entries(ledger_path)
    bib_records = load_records(bib).records
    bib_text = bib.read_text(encoding="utf-8")
    clean_problems, _ = _guard(manuscript, bib, ledger_path)

    gold: list[dict] = []
    predictions: list[dict] = []
    cases: list[dict] = []

    def record(
        case_id: str,
        label: str,
        basis: str,
        target: str,
        codes: list[str],
    ) -> None:
        gold.append({"id": case_id, "label": label, "basis": basis})
        predictions.append(
            {
                "id": case_id,
                "prediction": "unsupported" if codes else "supported",
                "codes": codes,
            }
        )
        cases.append(
            {
                "id": case_id,
                "target": target,
                "expected": "supported" if label == "supported" else "defect",
                "codes": codes,
            }
        )

    for key in sorted(entries):
        codes = _codes_for(clean_problems, key)
        record(
            f"clean:{key}",
            "supported",
            "real corpus entry; the citation is genuine and verifiable",
            key,
            codes,
        )

    targets = sorted(entries)
    if sample is not None:
        targets = targets[: max(0, int(sample))]
    skipped: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for index, key in enumerate(targets):
            # Defect 1: the ledger entry disappears.
            mutated = {k: dict(v) for k, v in entries.items()}
            mutated.pop(key, None)
            codes = _codes_for(
                _guard(manuscript, bib, _write_temp_ledger(tmp_path, mutated))[0],
                key,
            )
            record(
                f"ledger-missing:{key}",
                "unsupported",
                f"the ledger entry was removed, so {key} is not verifiable",
                key,
                codes,
            )

            # Defect 2: the entry claims verified but carries no evidence body.
            mutated = {k: dict(v) for k, v in entries.items()}
            mutated[key] = {**mutated[key], "status": "verified", "evidence": None}
            codes = _codes_for(
                _guard(manuscript, bib, _write_temp_ledger(tmp_path, mutated))[0],
                key,
            )
            record(
                f"evidence-null:{key}",
                "unsupported",
                f"{key} asserts verified with no fetchable evidence body",
                key,
                codes,
            )

            # Defect 3: the bibliography hands one DOI to two distinct works.
            # duplicate-doi is a bibliography property, so the bib is mutated.
            record_doi = bib_records[key].doi if key in bib_records else None
            if record_doi:
                temp_bib = tmp_path / "duplicate.bib"
                temp_bib.write_text(
                    bib_text
                    + "\n"
                    + "@article{calibration-duplicate-"
                    + key
                    + ",\n  title = {Calibration duplicate},\n  doi = {"
                    + record_doi
                    + "},\n}\n",
                    encoding="utf-8",
                )
                codes = _codes_for(
                    _guard(manuscript, temp_bib, ledger_path)[0],
                    key,
                )
                record(
                    f"duplicate-doi:{key}",
                    "unsupported",
                    f"a second work was given the same DOI as {key}",
                    key,
                    codes,
                )
            else:
                skipped.append(
                    {
                        "id": f"duplicate-doi:{key}",
                        "reason": f"{key} has no DOI in the bibliography",
                    }
                )

            # Defect 4: the manuscript cites a key the bibliography lacks.
            ghost = f"ghost-{key}"
            ghost_dir = tmp_path / f"manuscript-{index}"
            ghost_dir.mkdir(exist_ok=True)
            (ghost_dir / "ghost.tex").write_text(
                f"\\cite{{{ghost}}}\n",
                encoding="utf-8",
            )
            codes = _codes_for(
                _guard(ghost_dir, bib, ledger_path)[0],
                ghost,
            )
            record(
                f"dangling-cite:{key}",
                "unsupported",
                f"the manuscript cites {ghost}, which is absent from the bib",
                ghost,
                codes,
            )

    return {
        "gold": gold,
        "predictions": predictions,
        "cases": cases,
        "skipped": skipped,
        "sources": {
            "bib": _sha256_file(bib),
            "ledger": _sha256_file(ledger_path),
        },
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in rows
    )
    save_text_atomically(path, text, description="校准数据集")


def run_build(
    paper_root: Path,
    out_dir: Path,
    *,
    sample: int | None = None,
    max_fnr: float = 0.15,
    max_fpr: float = 0.10,
) -> dict:
    dataset = build_dataset(paper_root, sample=sample)
    out_dir = Path(out_dir)
    gold_path = out_dir / "gold.jsonl"
    prediction_path = out_dir / "predictions.jsonl"
    _write_jsonl(gold_path, dataset["gold"])
    _write_jsonl(prediction_path, dataset["predictions"])
    report = calibrate(
        gold_path,
        prediction_path,
        max_fnr=max_fnr,
        max_fpr=max_fpr,
    )
    report["generator"] = GENERATOR
    report["generated_at"] = _now_iso()
    report["paper_root"] = str(Path(paper_root).resolve())
    report["sources"] = dataset["sources"]
    report["skipped"] = dataset["skipped"]
    save_text_atomically(
        out_dir / "report.json",
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="校准报告",
    )
    save_text_atomically(
        out_dir / "cases.json",
        json.dumps(dataset["cases"], ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        description="校准用例",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="citation support calibration")
    parser.add_argument("--gold")
    parser.add_argument("--predictions")
    parser.add_argument("--out", help="把指标报告写入该 JSON 文件")
    parser.add_argument("--max-fnr", type=float, default=0.15)
    parser.add_argument("--max-fpr", type=float, default=0.10)
    sub = parser.add_subparsers(dest="command")
    build = sub.add_parser(
        "build",
        help="从真实论文语料构造客观金标集并运行校准",
    )
    build.add_argument("--paper-root", required=True)
    build.add_argument("--out", required=True)
    build.add_argument("--sample", type=int, default=None)
    build.add_argument("--max-fnr", type=float, default=0.15)
    build.add_argument("--max-fpr", type=float, default=0.10)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "build":
            report = run_build(
                Path(args.paper_root),
                Path(args.out),
                sample=args.sample,
                max_fnr=args.max_fnr,
                max_fpr=args.max_fpr,
            )
        else:
            if not args.gold or not args.predictions:
                return tool_error("score 需要 --gold 与 --predictions")
            report = calibrate(
                Path(args.gold),
                Path(args.predictions),
                max_fnr=args.max_fnr,
                max_fpr=args.max_fpr,
            )
            if args.out:
                save_text_atomically(
                    Path(args.out),
                    json.dumps(
                        report,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    description="校准报告",
                )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["threshold_pass"] else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
