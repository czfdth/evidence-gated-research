import json
import tempfile
import unittest
from pathlib import Path

from ccfa_core.settings import (
    ProviderSettings,
    Settings,
    load_settings,
    save_settings,
)

FAKE_KEY = "sk-test-FAKE-KEY-1234567890"


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.path = Path(self._temporary.name) / "settings.json"

    def _provider(self, **overrides):
        values = {
            "name": "local",
            "base_url": "https://api.example.test/v1",
            "model": "gpt-test",
            "key_name": "provider-key",
            "timeout_s": 30.0,
        }
        values.update(overrides)
        return ProviderSettings(**values)

    def test_missing_file_returns_default_without_provider(self):
        settings = load_settings(self.path)
        self.assertEqual(settings.schema_version, 1)
        self.assertIsNone(settings.provider)
        self.assertIsNone(settings.http_tools_path)

    def test_empty_file_returns_default_without_provider(self):
        self.path.write_text("", encoding="utf-8")
        self.assertIsNone(load_settings(self.path).provider)

    def test_round_trip_provider(self):
        provider = self._provider()

        save_settings(
            self.path,
            Settings(provider=provider, http_tools_path="tools.yaml"),
        )

        loaded = load_settings(self.path)
        self.assertEqual(loaded.provider, provider)
        self.assertEqual(loaded.http_tools_path, "tools.yaml")

    def test_loads_legacy_schema_v1_without_http_tools_path(self):
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "provider": None,
                }
            ),
            encoding="utf-8",
        )

        settings = load_settings(self.path)

        self.assertIsNone(settings.http_tools_path)

    def test_rejects_empty_or_non_string_http_tools_path(self):
        for value in ("", "   ", 12, [], {}):
            with self.subTest(value=value):
                self.path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "provider": None,
                            "http_tools_path": value,
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError):
                    load_settings(self.path)

    def test_saved_file_is_schema_v1_utf8_without_bom_and_atomic(self):
        save_settings(self.path, Settings(provider=self._provider()))

        raw = self.path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["provider"]["key_name"], "provider-key")
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_saved_provider_fields_are_exactly_the_whitelist(self):
        provider = self._provider()

        save_settings(self.path, Settings(provider=provider))

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(payload["provider"]),
            {"name", "base_url", "model", "key_name", "timeout_s"},
        )
        self.assertEqual(payload["provider"]["name"], provider.name)
        self.assertEqual(payload["provider"]["base_url"], provider.base_url)
        self.assertEqual(payload["provider"]["model"], provider.model)
        self.assertEqual(payload["provider"]["key_name"], provider.key_name)
        self.assertEqual(payload["provider"]["timeout_s"], provider.timeout_s)
        self.assertNotIn(FAKE_KEY, self.path.read_text(encoding="utf-8"))

    def test_save_settings_rejects_an_unknown_key_argument(self):
        with self.assertRaises(TypeError):
            save_settings(
                self.path,
                Settings(provider=self._provider()),
                key=FAKE_KEY,
            )

    def test_load_rejects_wrong_schema_version(self):
        self.path.write_text(
            json.dumps({"schema_version": 2, "provider": None}),
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            load_settings(self.path)

    def test_load_rejects_invalid_provider_fields(self):
        self.path.write_text(
            json.dumps({"schema_version": 1, "provider": {"name": "x"}}),
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            load_settings(self.path)

    def test_load_rejects_a_smuggled_key_field(self):
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "provider": {
                        "name": "local",
                        "base_url": "https://api.example.test/v1",
                        "model": "gpt-test",
                        "key_name": "provider-key",
                        "timeout_s": 30.0,
                        "key": FAKE_KEY,
                    },
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            load_settings(self.path)

    def test_load_revalidates_timeout(self):
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "provider": {
                        "name": "local",
                        "base_url": "https://api.example.test/v1",
                        "model": "gpt-test",
                        "key_name": "provider-key",
                        "timeout_s": 0,
                    },
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            load_settings(self.path)

    def test_save_rejects_invalid_provider(self):
        with self.assertRaises(ValueError):
            save_settings(
                self.path,
                Settings(provider=self._provider(timeout_s=0)),
            )


if __name__ == "__main__":
    unittest.main()
