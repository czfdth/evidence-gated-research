"""Compute FNR/FPR calibration for citation-support judgements."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ccfa.cli import tool_error


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
        rows[payload["id"]] = payload
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
        "max_fnr": max_fnr,
        "max_fpr": max_fpr,
        "threshold_pass": (
            not missing
            and not invalid
            and fnr <= max_fnr
            and fpr <= max_fpr
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="citation support calibration")
    parser.add_argument("--gold", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--max-fnr", type=float, default=0.15)
    parser.add_argument("--max-fpr", type=float, default=0.10)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        report = calibrate(
            Path(args.gold),
            Path(args.predictions),
            max_fnr=args.max_fnr,
            max_fpr=args.max_fpr,
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
