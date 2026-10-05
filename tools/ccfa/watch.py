"""Watch Atom feeds and report only unseen entry IDs."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from ccfa.cli import save_text_atomically, tool_error

STATE_VERSION = 1
SUMMARY_LIMIT = 500


def _local_name(tag: object) -> str:
    text = str(tag)
    return text.rsplit("}", 1)[-1]


def _parse_feed_with_skipped(xml_text: str) -> tuple[list[dict], int]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Atom 解析失败: {exc}") from exc

    entries: list[dict] = []
    skipped = 0
    for element in root.iter():
        if _local_name(element.tag) != "entry":
            continue
        fields: dict[str, str] = {}
        for child in element:
            name = _local_name(child.tag)
            if name in ("id", "title", "published", "summary") and name not in fields:
                fields[name] = " ".join(" ".join(child.itertext()).split())
        entry_id = fields.get("id", "")
        title = fields.get("title", "")
        if not entry_id or not title:
            skipped += 1
            continue
        entries.append(
            {
                "id": entry_id,
                "title": title,
                "published": fields.get("published", ""),
                "summary": fields.get("summary", ""),
            }
        )
    return entries, skipped


def parse_feed(xml_text: str) -> list[dict]:
    """Parse Atom entries, skipping entries missing id or title."""
    entries, _skipped = _parse_feed_with_skipped(xml_text)
    return entries


def _default_fetcher(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ccfa-watch/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
    except OSError as exc:
        raise ValueError(f"抓取失败 {url}: {exc}") from exc
    return data.decode("utf-8", errors="replace")


def _load_state(path: Path) -> tuple[dict, bool]:
    path = Path(path)
    if not path.exists():
        return {"version": STATE_VERSION, "seen_ids": []}, False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 watch state {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("watch state 顶层必须是对象")
    if payload.get("version") != STATE_VERSION:
        raise ValueError(f"watch state version 不支持: {payload.get('version')!r}")
    seen_ids = payload.get("seen_ids")
    if not isinstance(seen_ids, list) or not all(
        isinstance(item, str) for item in seen_ids
    ):
        raise ValueError("watch state.seen_ids 必须是字符串列表")
    return {"version": STATE_VERSION, "seen_ids": list(seen_ids)}, True


def _save_state(path: Path, seen_ids: list[str]) -> None:
    save_text_atomically(
        Path(path),
        json.dumps(
            {"version": STATE_VERSION, "seen_ids": seen_ids},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        description="watch state",
    )


def _fetch(url: str, fetcher) -> str:
    try:
        text = fetcher(url)
    except OSError as exc:
        raise ValueError(f"抓取失败 {url}: {exc}") from exc
    if not isinstance(text, str):
        raise ValueError(f"fetcher 必须返回字符串: {url}")
    return text


def scan(
    feed_urls: list[str],
    state_path: Path,
    *,
    fetcher=None,
    baseline: bool = False,
    limit: int = 50,
    force: bool = False,
) -> dict:
    """Fetch feeds and atomically update the seen-ID state."""
    if type(limit) is not int or limit < 0:
        raise ValueError("limit 必须是非负整数")
    state_path = Path(state_path)
    if force:
        state = {"version": STATE_VERSION, "seen_ids": []}
        state_exists = False
    else:
        state, state_exists = _load_state(state_path)
    fetch = fetcher or _default_fetcher
    is_baseline = baseline or force or not state_exists

    urls: list[str] = []
    seen_urls: set[str] = set()
    for url in feed_urls:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        urls.append(url)

    parsed_entries: list[dict] = []
    skipped = 0
    for url in urls:
        text = _fetch(url, fetch)
        entries, bad_count = _parse_feed_with_skipped(text)
        parsed_entries.extend(entries)
        skipped += bad_count

    seen_ids = list(state["seen_ids"])
    seen = set(seen_ids)
    if is_baseline:
        for entry in parsed_entries:
            if entry["id"] not in seen:
                seen.add(entry["id"])
                seen_ids.append(entry["id"])
        _save_state(state_path, seen_ids)
        return {
            "baseline": True,
            "new": [],
            "seen_total": len(seen_ids),
            "skipped": skipped,
        }

    new_entries: list[dict] = []
    queued: set[str] = set()
    for entry in parsed_entries:
        entry_id = entry["id"]
        if entry_id in seen or entry_id in queued:
            continue
        queued.add(entry_id)
        new_entries.append(
            {
                **entry,
                "summary": entry["summary"][:SUMMARY_LIMIT],
            }
        )

    reported = new_entries[:limit]
    for entry in reported:
        seen.add(entry["id"])
        seen_ids.append(entry["id"])
    _save_state(state_path, seen_ids)
    return {
        "baseline": False,
        "new": reported,
        "seen_total": len(seen_ids),
        "skipped": skipped,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="监控 Atom 文献源；只报告未见过的 ID，不判断实质重叠。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan", help="扫描 feed 并更新 state")
    scan_parser.add_argument("--state", required=True)
    scan_parser.add_argument("--url", action="append", required=True)
    scan_parser.add_argument("--baseline", action="store_true")
    scan_parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        result = scan(
            args.url,
            Path(args.state),
            baseline=args.baseline,
            force=args.force,
        )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["baseline"]:
        action = "已重建基线" if args.force else "已建立基线"
        print(
            f"{action} {result['seen_total']} 条",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
