import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from fisochat.config import AppConfig, load_admin_token
from fisochat.send import main as send_main


class ConfigTests(unittest.TestCase):
    def test_web_only_needs_no_qq_credentials_but_requires_password(self):
        config = AppConfig.from_env({"FISOCHAT_VIEW_PASSWORD": "password"}, web_only=True)
        self.assertEqual(config.web_port, 8789)
        self.assertEqual(config.database_path, Path("data/group_messages.db"))
        self.assertEqual(config.app_id, "")
        with self.assertRaisesRegex(ValueError, "FISOCHAT_VIEW_PASSWORD"):
            AppConfig.from_env({}, web_only=True)
        with self.assertRaisesRegex(ValueError, "QQ_BOT_APPID"):
            AppConfig.from_env({"FISOCHAT_VIEW_PASSWORD": "password"})

    def test_legacy_aliases_and_explicit_new_values(self):
        values = {"AIQQ_GROUP_MESSAGE_VIEW_PASSWORD": "password", "AIQQ_HEALTH_PORT": "8799"}
        self.assertEqual(AppConfig.from_env(values, web_only=True).web_port, 8799)
        values["FISOCHAT_WEB_PORT"] = "8789"
        self.assertEqual(AppConfig.from_env(values, web_only=True).web_port, 8789)
        values["FISOCHAT_VIEW_PASSWORD"] = ""
        with self.assertRaisesRegex(ValueError, "FISOCHAT_VIEW_PASSWORD"):
            AppConfig.from_env(values, web_only=True)

    def test_secrets_are_not_in_config_repr(self):
        config = AppConfig.from_env({
            "FISOCHAT_VIEW_PASSWORD": "secret-password",
            "FISOCHAT_ADMIN_TOKEN": "secret-token",
            "QQ_BOT_SECRET": "secret-bot",
        }, web_only=True)
        for secret in ("secret-password", "secret-token", "secret-bot"):
            self.assertNotIn(secret, repr(config))

    def test_invalid_ports_and_username_fail_before_start(self):
        for name, value in (("FISOCHAT_WEB_PORT", "0"), ("FISOCHAT_WEB_PORT", "65536"), ("FISOCHAT_WEB_PORT", "abc"), ("FISOCHAT_VIEW_USERNAME", "a:b")):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                AppConfig.from_env({"FISOCHAT_VIEW_PASSWORD": "pass", name: value}, web_only=True)

    def test_token_file_permissions_and_explicit_token_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            path.write_text("file-token\n")
            path.chmod(0o600)
            self.assertEqual(load_admin_token({"FISOCHAT_ADMIN_TOKEN_FILE": str(path)}), "file-token")
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "0600"):
                load_admin_token({"FISOCHAT_ADMIN_TOKEN_FILE": str(path)})
            self.assertEqual(load_admin_token({"FISOCHAT_ADMIN_TOKEN": "direct", "FISOCHAT_ADMIN_TOKEN_FILE": str(path)}), "direct")

    def test_cli_rejects_nonlocal_and_malformed_endpoints_before_network(self):
        for endpoint in ("https://example.com/internal/group-messages", "http://[broken", "http://127.0.0.1:99999", "http://user:password@127.0.0.1/"):
            with self.subTest(endpoint=endpoint), patch.dict(os.environ, {}, clear=True), patch("fisochat.send.urlopen") as network, redirect_stderr(io.StringIO()):
                code = send_main(["--endpoint", endpoint, "--group", "group-1", "--text", "hello"])
                self.assertEqual(code, 2)
                network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
