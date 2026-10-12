"""The CLI surface: reading a local key, and reporting what it finds without leaking it.

Fully offline. No provider SDK is installed and no request is made.

This is the only module in the project that reads a provider key from the environment, so
these tests exist to pin two things: that it reads the right places in the right order,
and that nothing it prints ever contains a key. Everything below `llm/` takes a credential
as an argument, and the tests in test_llm.py assert that; this file covers the boundary
where an environment becomes one.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm import cli
from llm.base import CheckResult, CredentialRejected, ProviderUnavailable

SECRET = "sk-ant-SECRETVALUE123"


def env_file(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return Path(handle.name)


class ReadingTheEnvFile(unittest.TestCase):
    def test_it_parses_the_shape_env_example_actually_has(self):
        path = env_file(
            "# a comment\n"
            "OPENGWAS_JWT=\n"
            "ANTHROPIC_API_KEY=sk-ant-abc\n"
            'OPENAI_API_KEY="sk-oai-def"\n'
            "\n"
            "GEMINI_API_KEY = sk-gem-ghi \n"
        )
        try:
            values = cli.load_env_file(path)
        finally:
            path.unlink()

        self.assertEqual(values.get("ANTHROPIC_API_KEY"), "sk-ant-abc")
        self.assertEqual(values.get("OPENAI_API_KEY"), "sk-oai-def")
        self.assertEqual(values.get("GEMINI_API_KEY"), "sk-gem-ghi")
        # A blank assignment is not a configured key.
        self.assertNotIn("OPENGWAS_JWT", values)

    def test_a_missing_file_is_empty_not_an_error(self):
        self.assertEqual(cli.load_env_file(REPO_ROOT / "does-not-exist.env"), {})

    def test_reading_never_mutates_the_process_environment(self):
        path = env_file("ANTHROPIC_API_KEY=sk-ant-fromfile\n")
        before = dict(os.environ)
        try:
            cli.load_env_file(path)
        finally:
            path.unlink()
        self.assertEqual(dict(os.environ), before)


class BuildingACredential(unittest.TestCase):
    def test_the_process_environment_wins_over_the_file(self):
        # `ANTHROPIC_API_KEY=... python render.py ...` has to do what it looks like it does.
        path = env_file("ANTHROPIC_API_KEY=sk-ant-fromfile\n")
        try:
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-fromenv"}):
                credential = cli.credential_from_env("claude", path)
        finally:
            path.unlink()
        self.assertEqual(credential.key, "sk-ant-fromenv")

    def test_the_file_is_used_when_the_environment_has_nothing(self):
        path = env_file("GEMINI_API_KEY=sk-gem-fromfile\n")
        try:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GEMINI_API_KEY", None)
                credential = cli.credential_from_env("gemini", path)
        finally:
            path.unlink()
        self.assertEqual(credential.key, "sk-gem-fromfile")
        self.assertEqual(credential.provider, "google")

    def test_nothing_configured_is_an_unusable_credential_not_a_crash(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            credential = cli.credential_from_env("chatgpt", REPO_ROOT / "missing.env")
        self.assertFalse(credential.is_usable())
        self.assertEqual(credential.provider, "openai")

    def test_the_source_is_recorded_as_the_operator_environment(self):
        # Distinguishing this from a per-session user key is what makes run metadata
        # meaningful once a second surface exists.
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": SECRET}):
            self.assertEqual(cli.credential_from_env("claude").source, "operator_env")

    def test_every_configured_provider_has_an_environment_variable(self):
        from llm import provider_key, providers as provider_keys

        for key in ("anthropic", "openai", "google"):
            with self.subTest(provider=key):
                self.assertIn(key, cli.ENV_VARS)
        self.assertEqual(set(cli.ENV_VARS), set(provider_keys()))


class NothingPrintsAKey(unittest.TestCase):
    """The whole point of a --keys command is to answer 'is it set' without showing it."""

    def test_describe_keys_reports_presence_and_length_only(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": SECRET}):
            text = cli.describe_keys(REPO_ROOT / "missing.env")

        self.assertNotIn(SECRET, text)
        self.assertNotIn("SECRETVALUE", text)
        self.assertIn(f"set ({len(SECRET)} chars)", text)

    def test_a_failing_check_does_not_print_the_key(self):
        buffer = io.StringIO()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": SECRET}), \
             patch.object(cli, "check", side_effect=CredentialRejected(
                 "Anthropic rejected this API key.", provider="anthropic")), \
             redirect_stdout(buffer):
            code = cli.run_check("claude", None, REPO_ROOT / "missing.env")

        self.assertEqual(code, 2)
        self.assertNotIn("SECRETVALUE", buffer.getvalue())

    def test_the_model_menu_names_the_variable_not_the_value(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": SECRET}):
            text = cli.describe_models()
        self.assertIn("ANTHROPIC_API_KEY", text)
        self.assertNotIn("SECRETVALUE", text)


class CheckReportsUsefully(unittest.TestCase):
    def check(self, provider="claude", model=None, env=None, **patches):
        buffer = io.StringIO()
        with patch.dict(os.environ, env or {}, clear=False), redirect_stdout(buffer):
            for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
                if not (env or {}).get(name):
                    os.environ.pop(name, None)
            with patch.object(cli, "check", **patches) if patches else _nothing():
                code = cli.run_check(provider, model, REPO_ROOT / "missing.env")
        return code, buffer.getvalue()

    def test_a_working_key_reports_ok_and_says_it_is_unvalidated(self):
        code, text = self.check(
            env          = {"ANTHROPIC_API_KEY": SECRET},
            return_value = CheckResult(True, "anthropic", "claude-opus-5", "Reached it.", 42),
        )
        self.assertEqual(code, 0)
        self.assertIn("OK", text)
        self.assertIn("42 ms", text)
        # A green check must not read as an endorsement of the results.
        self.assertIn("experimental", text)
        self.assertIn("not yet validated", text)

    def test_a_missing_key_names_the_variable_to_set(self):
        code, text = self.check()
        self.assertEqual(code, 2)
        self.assertIn("ANTHROPIC_API_KEY", text)

    def test_a_missing_sdk_prints_the_install_command(self):
        code, text = self.check(
            env         = {"ANTHROPIC_API_KEY": SECRET},
            side_effect = ProviderUnavailable(
                "The 'anthropic' package is not installed.", provider="anthropic"),
        )
        self.assertEqual(code, 2)
        self.assertIn("pip install anthropic", text)

    def test_an_unknown_provider_or_model_fails_before_any_request(self):
        for provider, model in (("llama", None), ("claude", "claude-opus-9")):
            with self.subTest(provider=provider, model=model):
                code, text = self.check(provider=provider, model=model)
                self.assertEqual(code, 2)
                self.assertIn("FAILED", text)


class _nothing:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


class TheEntryPoint(unittest.TestCase):
    def run_main(self, argv):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(argv)
        return code, buffer.getvalue()

    def test_list_prints_every_configured_row(self):
        code, text = self.run_main(["--list"])
        self.assertEqual(code, 0)
        for model in ("claude-opus-5", "gpt-4.1", "gemini-flash-latest"):
            with self.subTest(model=model):
                self.assertIn(model, text)

    def test_keys_prints_the_three_variables(self):
        code, text = self.run_main(["--keys"])
        self.assertEqual(code, 0)
        for variable in cli.ENV_VARS.values():
            with self.subTest(variable=variable):
                self.assertIn(variable, text)

    def test_no_arguments_prints_help_rather_than_doing_anything(self):
        code, text = self.run_main([])
        self.assertEqual(code, 0)
        self.assertIn("--check", text)


class RenderDefaultsModelSafely(unittest.TestCase):
    def test_a_known_provider_resolves_to_its_first_model(self):
        import render

        self.assertEqual(render._default_model_for("claude"), "claude-opus-5")

    def test_an_unknown_provider_is_passed_through_for_the_layer_to_report(self):
        # Raising inside argument handling would lose the card; letting the bad value
        # through means llm.interpret reports it like every other failure.
        import render

        self.assertEqual(render._default_model_for("llama"), "llama")


if __name__ == "__main__":
    unittest.main()
