"""Provider settings with schema version 1; key material is never stored."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ccfa_core.atomic import save_text_atomically

SCHEMA_VERSION = 1
PROVIDER_FIELDS = ("name", "base_url", "model", "key_name", "timeout_s")


@dataclass(frozen=True)
class ProviderSettings:
    name: str
    base_url: str
    model: str
    key_name: str
    timeout_s: float = 60.0


@dataclass(frozen=True)
class Settings:
    schema_version: int = SCHEMA_VERSION
    provider: ProviderSettings | None = None
    http_tools_path: str | None = None


def _text(field: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"provider.{field} 必须是非空字符串")
    return value


def _provider_from_payload(payload: Any) -> ProviderSettings | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("provider 必须是对象或 null")
    unknown = sorted(set(payload) - set(PROVIDER_FIELDS))
    if unknown:
        raise ValueError(f"provider 含未知字段: {', '.join(unknown)}")
    missing = [field for field in PROVIDER_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"provider 缺字段: {', '.join(missing)}")
    timeout = payload["timeout_s"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
    ):
        raise ValueError("provider.timeout_s 必须是正数")
    return ProviderSettings(
        name=_text("name", payload["name"]),
        base_url=_text("base_url", payload["base_url"]),
        model=_text("model", payload["model"]),
        key_name=_text("key_name", payload["key_name"]),
        timeout_s=float(timeout),
    )


def _settings_from_payload(payload: Any) -> Settings:
    if payload is None:
        return Settings()
    if not isinstance(payload, dict):
        raise ValueError("settings.json 顶层必须是对象")
    unknown = sorted(
        set(payload) - {"schema_version", "provider", "http_tools_path"}
    )
    if unknown:
        raise ValueError(f"settings.json 含未知字段: {', '.join(unknown)}")
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"settings.json schema_version 必须是 {SCHEMA_VERSION}: {version!r}"
        )
    http_tools_path = payload.get("http_tools_path")
    if http_tools_path is not None and (
        not isinstance(http_tools_path, str) or not http_tools_path.strip()
    ):
        raise ValueError("http_tools_path 必须是非空字符串或 null")
    return Settings(
        schema_version=SCHEMA_VERSION,
        provider=_provider_from_payload(payload.get("provider")),
        http_tools_path=(
            http_tools_path.strip() if http_tools_path is not None else None
        ),
    )


def load_settings(path: Path) -> Settings:
    """Load settings; missing or empty files return a default Settings."""
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Settings()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"无法读取设置 {path}: {exc}") from exc
    if not raw.strip():
        return Settings()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"设置 JSON 解析失败 {path}: {exc}") from exc
    return _settings_from_payload(payload)


def save_settings(
    path: Path,
    settings: Settings | ProviderSettings | None = None,
) -> None:
    """Atomically save settings; secrets belong in SecretStore."""
    path = Path(path)
    if isinstance(settings, ProviderSettings):
        settings = Settings(provider=settings)
    if settings is None:
        settings = Settings()
    if not isinstance(settings, Settings):
        raise ValueError("settings 必须是 Settings、ProviderSettings 或 null")
    if settings.schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"schema_version 必须是 {SCHEMA_VERSION}: {settings.schema_version!r}"
        )
    provider = _provider_from_payload(
        None
        if settings.provider is None
        else {
            "name": settings.provider.name,
            "base_url": settings.provider.base_url,
            "model": settings.provider.model,
            "key_name": settings.provider.key_name,
            "timeout_s": settings.provider.timeout_s,
        }
    )
    http_tools_path = settings.http_tools_path
    if http_tools_path is not None and (
        not isinstance(http_tools_path, str) or not http_tools_path.strip()
    ):
        raise ValueError("http_tools_path 必须是非空字符串或 null")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "provider": None
        if provider is None
        else {
            "name": provider.name,
            "base_url": provider.base_url,
            "model": provider.model,
            "key_name": provider.key_name,
            "timeout_s": provider.timeout_s,
        },
        "http_tools_path": (
            http_tools_path.strip() if http_tools_path is not None else None
        ),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    save_text_atomically(path, text, description="设置")
