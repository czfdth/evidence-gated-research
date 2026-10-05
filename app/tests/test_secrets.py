import unittest

from keyring.errors import NoKeyringError, PasswordDeleteError

from ccfa_core.secrets import (
    KeyringSecretStore,
    SecretStore,
    SecretStoreUnavailable,
)


class InMemorySecretStore:
    def __init__(self):
        self.values = {}

    def get(self, key_name):
        return self.values.get(key_name)

    def set(self, key_name, value):
        self.values[key_name] = value

    def delete(self, key_name):
        self.values.pop(key_name, None)


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, key_name):
        return self.values.get((service, key_name))

    def set_password(self, service, key_name, value):
        self.values[(service, key_name)] = value

    def delete_password(self, service, key_name):
        if (service, key_name) not in self.values:
            raise PasswordDeleteError(key_name)
        del self.values[(service, key_name)]


class NoBackendKeyring:
    def get_password(self, service, key_name):
        raise NoKeyringError("no backend")

    def set_password(self, service, key_name, value):
        raise NoKeyringError("no backend")

    def delete_password(self, service, key_name):
        raise NoKeyringError("no backend")


class SecretTests(unittest.TestCase):
    def test_in_memory_store_round_trip(self):
        store = InMemorySecretStore()
        store.set("k", "v")
        self.assertEqual(store.get("k"), "v")
        store.delete("k")
        self.assertIsNone(store.get("k"))

    def test_keyring_store_round_trip(self):
        keyring = FakeKeyring()
        store = KeyringSecretStore(service="test-service", keyring_module=keyring)

        store.set("k", "secret")

        self.assertEqual(store.get("k"), "secret")
        self.assertEqual(keyring.values[("test-service", "k")], "secret")
        store.delete("k")
        self.assertIsNone(store.get("k"))

    def test_keyring_delete_missing_is_idempotent(self):
        store = KeyringSecretStore(
            service="test-service",
            keyring_module=FakeKeyring(),
        )

        store.delete("missing")

    def test_no_keyring_backend_raises_without_plaintext_fallback(self):
        keyring = NoBackendKeyring()
        store = KeyringSecretStore(service="test-service", keyring_module=keyring)

        for action in (
            lambda: store.get("k"),
            lambda: store.set("k", "secret"),
            lambda: store.delete("k"),
        ):
            with self.subTest(action=action):
                with self.assertRaises(SecretStoreUnavailable):
                    action()

        self.assertFalse(hasattr(store, "values"))

    def test_protocol_is_runtime_checkable(self):
        self.assertIsInstance(InMemorySecretStore(), SecretStore)


if __name__ == "__main__":
    unittest.main()
