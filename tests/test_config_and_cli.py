import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from fisochat.config import AppConfig, load_admin_token
from fisochat.send import main as send_main


def valid_config(**overrides):
    values = {
        "QQ_BOT_APPID": "app-id",
        "QQ_BOT_SECRET": "bot-secret",
        "FISOCHAT_ADMIN_TOKEN": "admin-token",
        "FISOCHAT_STICKER_PUBLIC_BASE_URL": "https://example.com/fisochat",
        "FISOCHAT_STICKER_SIGNING_SECRET": "s" * 32,
    }
    values.update(overrides)
    return values


class ConfigTests(unittest.TestCase):
    def test_terminal_service_requires_qq_admin_and_sticker_configuration(self):
        config = AppConfig.from_env(valid_config())
        self.assertEqual(config.web_port, 8789)
        self.assertEqual(config.database_path, Path("data/group_messages.db"))
        self.assertEqual(config.sticker_directory, Path("data/stickers"))
        for name in (
            "QQ_BOT_APPID", "QQ_BOT_SECRET", "FISOCHAT_ADMIN_TOKEN",
            "FISOCHAT_STICKER_PUBLIC_BASE_URL", "FISOCHAT_STICKER_SIGNING_SECRET",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                AppConfig.from_env(valid_config(**{name: ""}))

    def test_legacy_non_viewer_aliases_and_explicit_new_values(self):
        values = valid_config(AIQQ_HEALTH_PORT="8799")
        self.assertEqual(AppConfig.from_env(values).web_port, 8799)
        values["FISOCHAT_WEB_PORT"] = "8789"
        self.assertEqual(AppConfig.from_env(values).web_port, 8789)

    def test_secrets_are_not_in_config_repr(self):
        config = AppConfig.from_env(valid_config(
            QQ_BOT_SECRET="secret-bot",
            FISOCHAT_ADMIN_TOKEN="secret-token",
            FISOCHAT_STICKER_SIGNING_SECRET="secret-signing-value-012345678901",
        ))
        for secret in (
            "secret-token", "secret-bot", "secret-signing-value-012345678901"
        ):
            self.assertNotIn(secret, repr(config))

    def test_invalid_ports_public_urls_and_short_secrets_fail_before_start(self):
        cases = (
            ("FISOCHAT_WEB_PORT", "0"),
            ("FISOCHAT_WEB_PORT", "65536"),
            ("FISOCHAT_WEB_PORT", "abc"),
            ("FISOCHAT_STICKER_PUBLIC_BASE_URL", "http://example.com/fisochat"),
            ("FISOCHAT_STICKER_PUBLIC_BASE_URL", "https://user@example.com/fisochat"),
            ("FISOCHAT_STICKER_PUBLIC_BASE_URL", "https://example.com/fisochat?token=x"),
            ("FISOCHAT_STICKER_PUBLIC_BASE_URL", "https://127.0.0.1/fisochat"),
            ("FISOCHAT_STICKER_PUBLIC_BASE_URL", "https://localhost/fisochat"),
            ("FISOCHAT_STICKER_SIGNING_SECRET", "too-short"),
        )
        for name, value in cases:
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                AppConfig.from_env(valid_config(**{name: value}))

    def test_token_file_permissions_and_explicit_token_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            path.write_text("file-token\n")
            path.chmod(0o600)
            self.assertEqual(
                load_admin_token({"FISOCHAT_ADMIN_TOKEN_FILE": str(path)}), "file-token"
            )
            config = AppConfig.from_env(valid_config(
                FISOCHAT_ADMIN_TOKEN="", FISOCHAT_ADMIN_TOKEN_FILE=str(path)
            ))
            self.assertEqual(config.admin_token, "file-token")
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "0600"):
                load_admin_token({"FISOCHAT_ADMIN_TOKEN_FILE": str(path)})
            self.assertEqual(load_admin_token({
                "FISOCHAT_ADMIN_TOKEN": "direct",
                "FISOCHAT_ADMIN_TOKEN_FILE": str(path),
            }), "direct")

    def test_cli_rejects_nonlocal_and_malformed_endpoints_before_network(self):
        for endpoint in (
            "https://example.com/internal/group-messages", "http://[broken",
            "http://127.0.0.1:99999", "http://user:password@127.0.0.1/",
        ):
            with self.subTest(endpoint=endpoint), patch.dict(os.environ, {}, clear=True), \
                    patch("fisochat.send.urlopen") as network, redirect_stderr(io.StringIO()):
                code = send_main([
                    "--endpoint", endpoint, "--group", "group-1", "--text", "hello"
                ])
                self.assertEqual(code, 2)
                network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
