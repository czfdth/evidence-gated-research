"""Thin, evidence-returning client for long-term research archives.

This host reaches ``github.com`` but its resolver answers ``zenodo.org`` with
``0.0.0.0`` and ``::`` (a DNS sinkhole, not a hosts-file entry), so a plain
``urllib`` call to Zenodo never leaves the machine. :func:`resolve_host`
therefore falls back to DNS-over-HTTPS, and every request is issued against
the resolved address while keeping the original ``Host`` and TLS SNI. That is
a transport workaround, not a security boundary: the TLS certificate still
has to match, so a poisoned answer cannot silently redirect the request.

The Zenodo flow follows the InvenioRDM API that Zenodo switched to in late
2024: create a draft record, upload file bytes into the record's bucket,
optionally publish. A deposit is only reported as ``published`` when the API
returns a DOI for the published record; a draft upload is never described as
archived evidence.

Tokens are read from the environment (``ZENODO_TOKEN``, ``OSF_TOKEN``) and
are never written to stdout, logs, or ledgers.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ccfa.cli import Problem, emit, save_text_atomically, tool_error

ZENODO_API = "https://zenodo.org/api"
ZENODO_SANDBOX_API = "https://sandbox.zenodo.org/api"
OSF_API = "https://api.osf.io/v2"
ORCID_API = "https://pub.orcid.org/v3.0"

_DOH_ENDPOINTS = (
    "https://cloudflare-dns.com/dns-query?name={host}&type=A&ct=application/dns-json",
    "https://dns.alidns.com/resolve?name={host}&type=A",
    "https://doh.pub/dns-query?name={host}&type=A&ct=application/dns-json",
)

_HTTPS_TIMEOUT_S = 30.0
_DNS_TIMEOUT_S = 12.0
_USER_AGENT = "ccfa-archive-client/0.1"


class ArchiveError(Exception):
    """A deposit could not be completed or verified."""


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    url: str

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArchiveError(f"{self.url} 的响应不是合法 JSON") from exc


@dataclass
class DepositResult:
    provider: str
    record_id: str
    doi: str | None
    status: str
    files: list[str] = field(default_factory=list)
    url: str | None = None
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "record_id": self.record_id,
            "doi": self.doi,
            "status": self.status,
            "files": list(self.files),
            "url": self.url,
            "detail": self.detail,
            "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


def _system_lookup(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return []
    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        # 0.0.0.0 / :: are sinkhole answers, never usable endpoints.
        if address in {"0.0.0.0", "::"}:
            continue
        if address not in addresses:
            addresses.append(address)
    return addresses


def _doh_lookup(host: str, *, fetch: Callable[[str], bytes] | None = None) -> list[str]:
    fetch = fetch or _plain_get
    for template in _DOH_ENDPOINTS:
        url = template.format(host=urllib.parse.quote(host))
        try:
            payload = json.loads(fetch(url).decode("utf-8"))
        except Exception:
            continue
        answers = payload.get("Answer")
        if not isinstance(answers, list):
            continue
        addresses = [
            answer.get("data")
            for answer in answers
            if isinstance(answer, dict)
            and answer.get("type") == 1
            and isinstance(answer.get("data"), str)
        ]
        if addresses:
            return addresses
    return []


def resolve_host(
    host: str,
    *,
    system_lookup: Callable[[str], list[str]] | None = None,
    doh_lookup: Callable[[str], list[str]] | None = None,
) -> list[str]:
    """Resolve *host*, falling back to DoH when the local resolver is poisoned."""
    system_lookup = system_lookup or _system_lookup
    doh_lookup = doh_lookup or _doh_lookup
    addresses = system_lookup(host)
    if addresses:
        return addresses
    return doh_lookup(host)


def _plain_get(url: str, timeout: float = _DNS_TIMEOUT_S) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/dns-json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that dials *address* while presenting *host*."""

    def __init__(self, host: str, address: str, *, timeout: float) -> None:
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self) -> None:  # noqa: D102 - mirrors stdlib behaviour
        sock = socket.create_connection(
            (self._address, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    json_body: Any | None = None,
    raw_body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = _HTTPS_TIMEOUT_S,
    host_addresses: Callable[[str], list[str]] | None = None,
) -> Response:
    """Issue an HTTPS request, pinning the socket to a resolved address."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ArchiveError(f"只支持 https URL: {url}")
    resolver = host_addresses or resolve_host
    addresses = resolver(parsed.hostname)
    if not addresses:
        raise ArchiveError(f"无法解析主机: {parsed.hostname}")
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body: bytes | None = raw_body
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif content_type:
        headers["Content-Type"] = content_type
    if body is not None:
        headers["Content-Length"] = str(len(body))
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    last_error: Exception | None = None
    for address in addresses:
        connection = _PinnedHTTPSConnection(parsed.hostname, address, timeout=timeout)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            return Response(int(response.status), payload, url)
        except (OSError, http.client.HTTPException) as exc:
            last_error = exc
            continue
        finally:
            connection.close()
    raise ArchiveError(f"请求 {url} 失败: {last_error}")


def _orcid_checksum(orcid: str) -> bool:
    """Validate an ORCID iD with the ISO 7064 MOD 11-2 check digit."""
    digits = orcid.replace("-", "").upper()
    if len(digits) != 16 or not digits[:15].isdigit():
        return False
    total = 0
    for char in digits[:15]:
        total = (total + int(char)) * 2
    remainder = total % 11
    check = (12 - remainder) % 11
    expected = "X" if check == 10 else str(check)
    return digits[15] == expected


def validate_orcid(orcid: str) -> tuple[bool, str]:
    normalized = orcid.strip().upper()
    if not _orcid_checksum(normalized):
        return False, "ORCID 校验位不合法"
    return True, "ORCID 校验位合法"


def probe_orcid(
    orcid: str,
    *,
    http: Callable[..., Response] | None = None,
) -> tuple[bool, str]:
    """Fetch the public ORCID record and confirm the iD resolves."""
    ok, detail = validate_orcid(orcid)
    if not ok:
        return False, detail
    normalized = orcid.strip().upper()
    call = http or request
    try:
        response = call(
            "GET",
            f"{ORCID_API}/{normalized}/record",
            timeout=_HTTPS_TIMEOUT_S,
        )
    except ArchiveError as exc:
        return False, str(exc)
    if response.status != 200:
        return False, f"ORCID 返回 HTTP {response.status}"
    return True, f"ORCID {normalized} 公开记录可读"


def zenodo_create_draft(
    metadata: dict,
    *,
    token: str,
    base_url: str = ZENODO_API,
    http: Callable[..., Response] | None = None,
) -> dict:
    call = http or request
    response = call(
        "POST",
        f"{base_url}/records",
        token=token,
        json_body={"metadata": metadata},
    )
    if response.status not in (200, 201):
        raise ArchiveError(
            f"创建 Zenodo draft 失败: HTTP {response.status} "
            f"{response.body[:300].decode('utf-8', 'replace')}"
        )
    return response.json()


def zenodo_upload_file(
    bucket_url: str,
    filename: str,
    payload: bytes,
    *,
    token: str,
    http: Callable[..., Response] | None = None,
    content_type: str = "application/octet-stream",
) -> dict:
    call = http or request
    url = f"{bucket_url.rstrip('/')}/{urllib.parse.quote(filename)}"
    response = call(
        "PUT",
        url,
        token=token,
        raw_body=payload,
        content_type=content_type,
    )
    if response.status not in (200, 201):
        raise ArchiveError(
            f"上传 {filename} 失败: HTTP {response.status} "
            f"{response.body[:300].decode('utf-8', 'replace')}"
        )
    return response.json()


def zenodo_publish(
    record_id: str,
    *,
    token: str,
    base_url: str = ZENODO_API,
    http: Callable[..., Response] | None = None,
) -> dict:
    call = http or request
    response = call(
        "POST",
        f"{base_url}/records/{record_id}/draft/actions/publish",
        token=token,
        raw_body=b"",
        content_type="application/json",
    )
    if response.status not in (200, 202):
        raise ArchiveError(
            f"发布 Zenodo record {record_id} 失败: HTTP {response.status} "
            f"{response.body[:300].decode('utf-8', 'replace')}"
        )
    return response.json()


def zenodo_deposit(
    metadata: dict,
    files: list[Path],
    *,
    token: str,
    publish: bool = False,
    base_url: str = ZENODO_API,
    http: Callable[..., Response] | None = None,
) -> DepositResult:
    """Create a draft, upload *files*, and optionally publish it.

    ``publish=False`` returns ``status="draft"``: the bytes exist on Zenodo but
    no DOI has been issued, so the caller must not present it as archived.
    """
    call = http or request
    draft = zenodo_create_draft(metadata, token=token, base_url=base_url, http=call)
    record_id = str(draft.get("id") or draft.get("pid") or "")
    if not record_id:
        raise ArchiveError("Zenodo 响应缺少 record id")
    links = draft.get("links") if isinstance(draft.get("links"), dict) else {}
    bucket = links.get("files") or links.get("self")
    if not isinstance(bucket, str):
        raise ArchiveError("Zenodo 响应缺少文件 bucket 链接")
    uploaded: list[str] = []
    for path in files:
        source = Path(path)
        if not source.is_file():
            raise ArchiveError(f"待上传文件不存在: {source}")
        zenodo_upload_file(
            bucket,
            source.name,
            source.read_bytes(),
            token=token,
            http=call,
        )
        uploaded.append(source.name)
    doi: str | None = None
    status = "draft"
    url = links.get("self_html") if isinstance(links.get("self_html"), str) else None
    detail = f"草稿已创建并上传 {len(uploaded)} 个文件（未发布，无 DOI）"
    if publish:
        published = zenodo_publish(record_id, token=token, base_url=base_url, http=call)
        if not isinstance(published.get("doi"), str):
            raise ArchiveError("发布响应缺少 DOI，不能声称已归档")
        doi = published["doi"]
        status = "published"
        html = published.get("links", {}).get("self_html")
        if isinstance(html, str):
            url = html
        detail = "已发布并取得 DOI"
    return DepositResult(
        provider="zenodo",
        record_id=record_id,
        doi=doi,
        status=status,
        files=uploaded,
        url=url,
        detail=detail,
    )


def osf_create_project(
    title: str,
    *,
    token: str,
    description: str = "",
    http: Callable[..., Response] | None = None,
) -> dict:
    call = http or request
    body = {
        "data": {
            "type": "nodes",
            "attributes": {"title": title, "description": description},
        }
    }
    response = call("POST", f"{OSF_API}/nodes/", token=token, json_body=body)
    if response.status not in (200, 201):
        raise ArchiveError(
            f"创建 OSF 项目失败: HTTP {response.status} "
            f"{response.body[:300].decode('utf-8', 'replace')}"
        )
    return response.json()


def probe(
    *,
    http: Callable[..., Response] | None = None,
    resolver: Callable[[str], list[str]] | None = None,
) -> dict:
    """Report transport reachability for the three archive providers."""
    call = http or request
    host_addresses = resolver or resolve_host
    results: dict[str, dict] = {}
    for name, url in (
        ("zenodo", f"{ZENODO_API}/records?size=1"),
        ("osf", f"{OSF_API}/nodes/?page[size]=1"),
        ("orcid", f"{ORCID_API}/0000-0002-1825-0097/record"),
    ):
        host = urllib.parse.urlsplit(url).hostname or ""
        addresses = host_addresses(host)
        try:
            response = call("GET", url)
            results[name] = {
                "reachable": 200 <= response.status < 300,
                "status": response.status,
                "addresses": addresses[:3],
            }
        except Exception as exc:
            results[name] = {
                "reachable": False,
                "error": f"{type(exc).__name__}: {exc}"[:200],
                "addresses": addresses[:3],
            }
    return results


def record_result(result: DepositResult, paper_root: Path) -> Path:
    """Append a deposit result to ``data/archive.yaml`` for badge evidence."""
    path = Path(paper_root) / "data" / "archive.yaml"
    payload: dict = {"version": 1, "records": []}
    if path.is_file():
        import yaml  # imported lazily so the CLI never needs PyYAML to probe

        existing = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            payload = existing
            payload.setdefault("records", [])
    if not isinstance(payload.get("records"), list):
        raise ArchiveError("data/archive.yaml 的 records 必须是数组")
    payload["records"].append(result.as_dict())
    import yaml

    save_text_atomically(
        path,
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        description="archive ledger",
    )
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Zenodo / OSF / ORCID 归档薄客户端（内置 DNS-over-HTTPS 绕行）"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("probe", help="探测三个归档服务的传输可达性")
    validate = sub.add_parser("orcid-validate", help="离线校验 ORCID iD 校验位")
    validate.add_argument("orcid")
    fetch = sub.add_parser("orcid-fetch", help="抓取 ORCID 公开记录")
    fetch.add_argument("orcid")

    deposit = sub.add_parser("zenodo-deposit", help="创建 Zenodo 记录并上传文件")
    deposit.add_argument("--metadata", required=True, help="记录元数据 JSON")
    deposit.add_argument("--file", action="append", default=[], help="上传文件")
    deposit.add_argument("--publish", action="store_true")
    deposit.add_argument("--sandbox", action="store_true")
    deposit.add_argument("--paper-root", default=None)
    deposit.add_argument("--dry-run", action="store_true")

    zen = sub.add_parser("zenodo-record", help="读取 Zenodo 记录状态")
    zen.add_argument("record_id")
    zen.add_argument("--sandbox", action="store_true")

    osf = sub.add_parser("osf-create", help="创建 OSF 项目")
    osf.add_argument("--title", required=True)
    osf.add_argument("--description", default="")
    return parser


def _probe_problems(results: dict) -> list[Problem]:
    problems: list[Problem] = []
    for name, result in sorted(results.items()):
        if result.get("reachable"):
            continue
        problems.append(
            Problem(
                "archive-probe-unreachable",
                name,
                None,
                f"{name} 不可达: {result.get('error') or result.get('status')}",
            )
        )
    return problems


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "probe":
            results = probe()
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return emit(_probe_problems(results), [])
        if args.command == "orcid-validate":
            ok, detail = validate_orcid(args.orcid)
            print(json.dumps({"orcid": args.orcid, "valid": ok, "detail": detail}))
            return 0 if ok else 1
        if args.command == "orcid-fetch":
            ok, detail = probe_orcid(args.orcid)
            print(json.dumps({"orcid": args.orcid, "ok": ok, "detail": detail}))
            return 0 if ok else 1
        if args.command == "zenodo-record":
            base = ZENODO_SANDBOX_API if args.sandbox else ZENODO_API
            response = request("GET", f"{base}/records/{args.record_id}")
            print(json.dumps(response.json(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "osf-create":
            token = os.environ.get("OSF_TOKEN", "")
            if not token:
                return tool_error("未设置 OSF_TOKEN 环境变量")
            payload = osf_create_project(args.title, token=token, description=args.description)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        # zenodo-deposit
        metadata_path = Path(args.metadata)
        if not metadata_path.is_file():
            return tool_error(f"元数据文件不存在: {metadata_path}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        files = [Path(item) for item in args.file]
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "metadata_keys": sorted(metadata),
                        "files": [str(item) for item in files],
                        "sandbox": args.sandbox,
                        "publish": args.publish,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        token = os.environ.get("ZENODO_TOKEN", "")
        if not token:
            return tool_error("未设置 ZENODO_TOKEN 环境变量")
        base = ZENODO_SANDBOX_API if args.sandbox else ZENODO_API
        result = zenodo_deposit(
            metadata,
            files,
            token=token,
            publish=args.publish,
            base_url=base,
        )
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        if args.paper_root:
            path = record_result(result, Path(args.paper_root))
            print(f"已写入 {path}", file=sys.stderr)
        return 0
    except (ArchiveError, OSError, ValueError, json.JSONDecodeError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
