"""Offline regression tests. Test hosts and keys are synthetic, never customer values."""

import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import runtime
import setup
import smoke_test


def sample_values():
    # Construct synthetic URLs in tests only; no application inference defaults.
    return {
        "FOUNDRY_API_BASE": "https://" + "resource.invalid/openai/v1",
        "FOUNDRY_API_KEY": "synthetic-test-value-not-a-credential",
        "FOUNDRY_SONNET_DEPLOYMENT": "test-default",
        "FOUNDRY_OPUS_DEPLOYMENT": "test-advanced",
        "FOUNDRY_HAIKU_DEPLOYMENT": "test-background",
        "LITELLM_PROXY_BASE_URL": "http://" + "127.0.0.1:45678",
        "LITELLM_MASTER_KEY": "sk-" + "synthetic-unit-test-value-00000000",
    }


class ConfigurationTests(unittest.TestCase):
    def test_values_and_project_scoped_base(self):
        values = sample_values()
        runtime.validate(values)
        values["FOUNDRY_API_BASE"] = "https://" + "resource.invalid/api/projects/test/openai/v1/"
        runtime.validate(values)

    def test_reject_invalid_urls(self):
        for invalid in ("http://resource.invalid/openai/v1", "https://resource.invalid",
                        "https://resource.invalid/openai/v1/chat/completions",
                        "https://resource.invalid/openai/v1?key=private", "https://user:pass@resource.invalid/openai/v1"):
            with self.subTest(base=invalid):
                values = sample_values()
                values["FOUNDRY_API_BASE"] = invalid
                with self.assertRaises(ValueError):
                    runtime.validate(values)
        for invalid in ("http://0.0.0.0:45678", "https://localhost:45678", "http://localhost",
                        "http://localhost:45678/v1", "http://localhost:80", "http://localhost:99999"):
            with self.subTest(proxy=invalid):
                values = sample_values()
                values["LITELLM_PROXY_BASE_URL"] = invalid
                with self.assertRaises(ValueError):
                    runtime.validate(values)

    def test_reject_missing_and_catalog_paths(self):
        for field in set(runtime.FIELDS) - {"FOUNDRY_MODEL"}:
            values = sample_values()
            values[field] = ""
            with self.assertRaises(ValueError):
                runtime.validate(values)
        values = sample_values()
        values["FOUNDRY_SONNET_DEPLOYMENT"] = "accounts/vendor/models/test"
        with self.assertRaises(ValueError):
            runtime.validate(values)

    def test_single_model_override(self):
        values = sample_values()
        values["FOUNDRY_MODEL"] = "test-unified"
        for role in runtime.ROUTES:
            values.pop(f"FOUNDRY_{role}_DEPLOYMENT")
        runtime.validate(values)
        env = runtime.proxy_environment(values)
        for role in runtime.ROUTES:
            self.assertEqual(env[f"LITELLM_{role}_MODEL"], "openai/test-unified")
        values["FOUNDRY_SONNET_DEPLOYMENT"] = "test-ignored"
        self.assertEqual(runtime.deployment_for(values, "SONNET"), "test-unified")
        values["FOUNDRY_MODEL"] = "invalid/path"
        with self.assertRaises(ValueError):
            runtime.validate(values)

    def test_env_round_trip_is_inert_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            values = sample_values()
            values["FOUNDRY_API_KEY"] = 'literal-$(not-a-command)-"quoted"-#value'
            runtime.write_private(path, "".join(f"{key}={json.dumps(value)}\n" for key, value in values.items()))
            self.assertEqual(runtime.read_env(path), values)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            runtime.write_private(path, "FOUNDRY_API_KEY=replaced\n")
            self.assertEqual(runtime.read_env(path)["FOUNDRY_API_KEY"], "replaced")

    def test_write_does_not_follow_target_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.write_text("untouched")
            path = Path(directory) / ".env"
            path.symlink_to(target)
            runtime.write_private(path, "replacement")
            self.assertEqual(target.read_text(), "untouched")
            self.assertFalse(path.is_symlink())

    def test_parser_rejects_unknown_duplicate_or_multiline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            for text in ("UNEXPECTED=value\n", "FOUNDRY_API_KEY=a\nFOUNDRY_API_KEY=b\n",
                         'FOUNDRY_API_KEY="bad\\nvalue"\n', 'FOUNDRY_API_KEY="unterminated\n'):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    runtime.read_env(path)

    def test_environment_precedence(self):
        with patch.object(runtime, "read_env", return_value=sample_values()), patch.dict(
                os.environ, {"FOUNDRY_SONNET_DEPLOYMENT": "override"}, clear=True):
            self.assertEqual(runtime.load_config()["FOUNDRY_SONNET_DEPLOYMENT"], "override")

    def test_model_prefix_and_client_secret_separation(self):
        values = sample_values()
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime, "ROOT", Path(directory)), patch.dict(
                os.environ, {"ANTHROPIC_API_KEY": "competing", "ANTHROPIC_CUSTOM_HEADERS": "private",
                             "CLAUDE_CODE_USE_FOUNDRY": "1", "FOUNDRY_API_KEY": "private",
                             "LITELLM_MASTER_KEY": "private"}, clear=True):
            proxy = runtime.proxy_environment(values)
            self.assertEqual(proxy["LITELLM_SONNET_MODEL"], "openai/test-default")
            client = runtime.claude_environment(values)
            self.assertNotIn("ANTHROPIC_API_KEY", client)
            self.assertNotIn("FOUNDRY_API_KEY", client)
            self.assertNotIn("CLAUDE_CODE_USE_FOUNDRY", client)
            self.assertNotIn("ANTHROPIC_CUSTOM_HEADERS", client)
            self.assertNotIn("LITELLM_MASTER_KEY", client)
            self.assertEqual(client["ANTHROPIC_AUTH_TOKEN"], values["LITELLM_MASTER_KEY"])
            self.assertEqual(client["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "claude-haiku-foundry")
            self.assertEqual(client["CLAUDE_CONFIG_DIR"], str(Path(directory) / ".local/claude-config"))
            self.assertEqual((Path(directory) / ".local/claude-config/settings.json").read_text(), "{}\n")
            self.assertEqual(os.environ["ANTHROPIC_API_KEY"], "competing")

    def test_claude_launcher_preserves_local_settings(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime, "ROOT", Path(directory)):
            settings = Path(directory) / ".local/claude-config/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text('{"permissions": {"defaultMode": "default"}}\n')
            original = settings.read_text()
            runtime.claude_environment(sample_values())
            self.assertEqual(settings.read_text(), original)

    def test_setup_generates_and_retains_key(self):
        values = sample_values()
        values["LITELLM_MASTER_KEY"] = ""
        with patch.object(setup, "read_env", return_value=values), patch.dict(os.environ, {}, clear=True):
            result = setup.collect_values(True)
        self.assertTrue(result["LITELLM_MASTER_KEY"].startswith("sk-"))
        self.assertGreaterEqual(len(result["LITELLM_MASTER_KEY"]), 35)
        with patch.object(setup, "read_env", return_value=result), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(setup.collect_values(True)["LITELLM_MASTER_KEY"], result["LITELLM_MASTER_KEY"])

    def test_configure_only_does_not_install_or_print_secrets(self):
        values = sample_values()
        with tempfile.TemporaryDirectory() as directory, patch.object(setup, "ENV_FILE", Path(directory) / ".env"), \
                patch.object(setup, "collect_values", return_value=values), \
                patch.object(setup, "install_nexus") as nexus, patch.object(setup, "install_litellm") as litellm, \
                patch("sys.argv", ["setup.py", "--non-interactive", "--configure-only"]):
            output = io.StringIO()
            old_mask = os.umask(0o077)
            try:
                with contextlib.redirect_stdout(output):
                    self.assertEqual(setup.main(), 0)
            finally:
                os.umask(old_mask)
            nexus.assert_not_called()
            litellm.assert_not_called()
            self.assertNotIn(values["FOUNDRY_API_KEY"], output.getvalue())
            self.assertNotIn(values["LITELLM_MASTER_KEY"], output.getvalue())

    def test_stream_validation(self):
        smoke_test.check_stream([b'data: {"type":"message_start"}\n',
                                 b'data: {"type":"content_block_delta"}\n',
                                 b'data: {"type":"message_stop"}\n'])
        with self.assertRaises(ValueError):
            smoke_test.check_stream([b'data: {"type":"message_start"}\n'])
        with self.assertRaises(ValueError):
            smoke_test.check_stream([b'data: {"type":"error"}\n'])


if __name__ == "__main__":
    unittest.main()
