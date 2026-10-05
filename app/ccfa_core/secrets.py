"""Secret storage; the only production backend is the OS keyring."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import keyring
from keyring.errors import NoKeyringError, PasswordDeleteError


class SecretStoreUnavailable(RuntimeError):
    """Raised when the OS credential backend is unavailable."""


@runtime_checkable
class SecretStore(Protocol):
    def get(self, key_name: str) -> str | None:
        ...

    def set(self, key_name: str, value: str) -> None:
        ...

    def delete(self, key_name: str) -> None:
        ...


class KeyringSecretStore:
    """Keyring-backed store; never falls back to plaintext."""

    def __init__(self, service: str = "ccfa-workbench", *, keyring_module=None):
        self._service = service
        self._keyring = keyring_module or keyring

    @staticmethod
    def _unavailable(exc: NoKeyringError) -> SecretStoreUnavailable:
        return SecretStoreUnavailable(
            f"系统凭据管理器不可用，未降级为明文存储: {exc}"
        )

    def get(self, key_name: str) -> str | None:
        try:
            return self._keyring.get_password(self._service, key_name)
        except NoKeyringError as exc:
            raise self._unavailable(exc) from exc

    def set(self, key_name: str, value: str) -> None:
        try:
            self._keyring.set_password(self._service, key_name, value)
        except NoKeyringError as exc:
            raise self._unavailable(exc) from exc

    def delete(self, key_name: str) -> None:
        try:
            self._keyring.delete_password(self._service, key_name)
        except PasswordDeleteError:
            return
        except NoKeyringError as exc:
            raise self._unavailable(exc) from exc
