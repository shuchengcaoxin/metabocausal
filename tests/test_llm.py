"""The switchable LLM layer: registry, credential handling, and failure translation.

Fully offline. No provider SDK is installed or called - every adapter is exercised through
a fake client, and the two credential tests that matter most are pure.

The test that gates the phase is CredentialIsolation. Everything else here is ordinary
coverage; that class is the one asserting the property which is cheap to hold now and
expensive to retrofit once a second surface exists.
"""

from __future__ import annotations

import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import llm
from llm import registry
from llm.base import (
    Credential,
    CredentialMissing,
    CredentialRejected,
    LLMError,
    ModelNotSupported,
    ProviderNotSupported,
    ProviderUnavailable,
    Reply,
    ResponseUnusable,
)


class CredentialsKeepQuiet(unittest.TestCase):
    """A key must not be printable. Every leak this project could have starts with a
    traceback, a log line or a repr that happened to hold one."""

    def setUp(self):
        self.cred = Credential(provider="anthropic", key="sk-ant-SECRETVALUE", source="user_session")

    def test_repr_and_str_redact_the_key(self):
        for rendered in (repr(self.cred), str(self.cred), f"{self.cred}"):
            self.assertNotIn("SECRETVALUE", rendered)
            self.assertIn("<redacted>", rendered)

    def test_the_key_does_not_survive_into_a_traceback_frame_summary(self):
        # A dataclass with a default repr prints every field. This asserts the override
        # actually took, by rendering the object the way an error report would.
        self.assertNotIn("SECRETVALUE", "{!r}".format(self.cred))
        self.assertNotIn("SECRETVALUE", repr([self.cred]))
        self.assertNotIn("SECRETVALUE", repr({"cred": self.cred}))

    def test_redacted_is_what_run_metadata_may_hold(self):
        record = self.cred.redacted()
        self.assertEqual(record, {"provider": "anthropic", "source": "user_session"})
        self.assertNotIn("key", record)

    def test_run_metadata_carries_no_key(self):
        spec = registry.resolve("claude", "claude-opus-5")
        record = registry.run_metadata(spec, self.cred, mode="interpretation")

        self.assertNotIn("SECRETVALUE", repr(record))
        self.assertEqual(record["provider"], "anthropic")
        self.assertEqual(record["model"], "claude-opus-5")
        self.assertEqual(record["model_status"], registry.EXPERIMENTAL)
        self.assertEqual(record["execution_mode"], "interpretation")

    def test_a_blank_key_is_not_usable(self):
        for blank in ("", "   ", None):
            self.assertFalse(Credential(provider="openai", key=blank).is_usable())


class RegistryIsHonest(unittest.TestCase):
    def test_all_three_providers_are_present(self):
        self.assertEqual(registry.providers(), ["anthropic", "google", "openai"])

    def test_user_facing_names_resolve(self):
        for typed, expected in (
            ("Claude", "anthropic"), ("claude", "anthropic"), ("anthropic", "anthropic"),
            ("ChatGPT", "openai"),   ("gpt", "openai"),       ("openai", "openai"),
            ("Gemini", "google"),    ("google", "google"),
        ):
            with self.subTest(typed=typed):
                self.assertEqual(registry.provider_key(typed), expected)

    def test_an_unknown_provider_raises_rather_than_defaulting(self):
        with self.assertRaises(ProviderNotSupported):
            registry.provider_key("llama")

    def test_every_supported_row_carries_its_measurement(self):
        # The status field is a claim about testing, not about the model. This test began
        # as "nothing may say supported", so that the first promotion could not happen by
        # accident; gemini-flash-lite-latest was promoted on 2026-09-12 against 30/30 on
        # the evidence fixtures. The guard now checks the thing that actually matters -
        # that a promoted row says when it was measured, so the claim can be re-run and
        # disproved. A bare 'supported' with no note is indistinguishable from a guess.
        unevidenced = [
            row["model"] for row in registry.menu()
            if row["status"] == registry.SUPPORTED and "Validated" not in (row["note"] or "")
        ]
        self.assertEqual(
            unevidenced,
            [],
            "A 'supported' row must record the date and result of the fixture run that "
            "earned it: " + registry.PROMOTION_RULE,
        )

    def test_a_supported_row_names_a_date_and_a_count(self):
        for row in registry.menu():
            if row["status"] != registry.SUPPORTED:
                continue
            with self.subTest(model=row["model"]):
                self.assertRegex(row["note"], r"\d{4}-\d{2}-\d{2}")
                self.assertRegex(row["note"], r"\d+\s*/\s*\d+")

    def test_an_unmeasured_model_stays_experimental(self):
        # gemini-flash-latest is the same family as the promoted one and would very likely
        # pass. 'Very likely' is what this field exists to refuse.
        spec = registry.resolve("gemini", "gemini-flash-latest")
        self.assertEqual(spec.status, registry.EXPERIMENTAL)

    def test_an_unknown_model_raises_and_names_the_alternatives(self):
        with self.assertRaises(ModelNotSupported) as caught:
            registry.resolve("claude", "claude-opus-9")
        self.assertIn("claude-opus-5", str(caught.exception))

    def test_an_unavailable_model_is_refused_not_hidden(self):
        spec = registry.ModelSpec(
            "anthropic", "claude-future", "Future", True, registry.UNAVAILABLE,
            note="not built in this version.",
        )
        with patch.dict(registry.REGISTRY["anthropic"], {"claude-future": spec}):
            self.assertFalse(spec.offerable)
            with self.assertRaises(ModelNotSupported):
                registry.resolve("anthropic", "claude-future")

    def test_menu_carries_status_so_a_picker_cannot_imply_endorsement(self):
        rows = registry.menu()
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(model=row["model"]):
                self.assertIn(row["status"], (registry.SUPPORTED, registry.EXPERIMENTAL))
                self.assertTrue(row["provider_name"])
                self.assertTrue(row["label"])

    def test_default_model_is_the_first_offerable_one(self):
        self.assertEqual(registry.default_model("claude"), "claude-opus-5")


class NoSilentSubstitution(unittest.TestCase):
    def test_a_wrong_side_key_is_named_as_such(self):
        # An Anthropic key sent to Google should be reported as the wrong key, not as an
        # invalid one: the user needs to know which of the two things they got wrong.
        cred = Credential(provider="anthropic", key="sk-ant-x")
        with self.assertRaises(CredentialRejected) as caught:
            llm.complete([{"role": "user", "content": "hi"}],
                         provider="gemini", model="gemini-flash-latest", credential=cred)
        message = str(caught.exception)
        self.assertIn("Claude", message)
        self.assertIn("Gemini", message)

    def test_a_missing_key_is_its_own_failure(self):
        with self.assertRaises(CredentialMissing):
            llm.complete([{"role": "user", "content": "hi"}],
                         provider="claude", model="claude-opus-5",
                         credential=Credential(provider="anthropic", key=""))

    def test_an_unknown_model_never_falls_back_to_a_working_one(self):
        cred = Credential(provider="anthropic", key="sk-ant-x")
        with self.assertRaises(ModelNotSupported):
            llm.complete([{"role": "user", "content": "hi"}],
                         provider="claude", model="claude-opus-9", credential=cred)


class MissingSdkIsNotAnAppFailure(unittest.TestCase):
    """An uninstalled optional dependency must degrade to one unavailable provider, never
    to an import error that stops the deterministic product from starting."""

    def test_importing_the_package_needs_no_provider_sdk(self):
        for module in ("anthropic", "openai", "google.genai"):
            with self.subTest(module=module):
                self.assertNotIn(module, sys.modules)

    def test_a_missing_sdk_surfaces_as_provider_unavailable(self):
        from llm.adapters import anthropic_api

        with patch.object(anthropic_api, "_sdk", side_effect=ProviderUnavailable(
                "The 'anthropic' package is not installed.", provider="anthropic")):
            with self.assertRaises(ProviderUnavailable):
                anthropic_api.AnthropicProvider().check(
                    "claude-opus-5", Credential(provider="anthropic", key="k"),
                )

    def test_every_provider_unavailable_is_an_llm_error(self):
        # The caller's one guarantee: catching LLMError is enough to keep the card.
        self.assertTrue(issubclass(ProviderUnavailable, LLMError))
        self.assertTrue(issubclass(CredentialRejected, LLMError))
        self.assertTrue(issubclass(ModelNotSupported, LLMError))
        self.assertTrue(issubclass(ResponseUnusable, LLMError))


class FakeAdapter:
    """Records the credential it was handed, so a test can assert which key arrived."""

    name = "anthropic"

    def __init__(self):
        self.seen = []
        self.lock = threading.Lock()

    def complete(self, messages, *, model, credential, **kwargs):
        with self.lock:
            self.seen.append((threading.current_thread().name, credential.key))
        # Echo the key back through the reply so the test reads what this call actually
        # used, not what a shared client might have been configured with earlier.
        return Reply(text=f"used:{credential.key}", provider="anthropic", model=model)

    def check(self, model, credential):
        raise AssertionError("not used in these tests")


class CredentialIsolation(unittest.TestCase):
    """THE BLOCKING TEST FOR THIS PHASE.

    Two concurrent requests with two different keys must not be able to reach each other's.
    The property is structural - credentials are arguments, and clients are built per call
    - but it is asserted here because it is invisible in single-user development and it is
    the failure that would be discovered in production, on someone else's bill."""

    def test_concurrent_requests_keep_their_own_keys(self):
        adapter = FakeAdapter()
        results: dict = {}
        barrier = threading.Barrier(2)

        def run(name, key):
            cred = Credential(provider="anthropic", key=key, source="user_session")
            barrier.wait(timeout=5)          # force genuine overlap, not sequential calls
            results[name] = llm.complete(
                [{"role": "user", "content": "hi"}],
                provider="claude", model="claude-opus-5", credential=cred,
            ).text

        with patch.object(llm, "adapter_for", return_value=adapter):
            threads = [
                threading.Thread(target=run, args=("alice", "sk-ant-ALICE"), name="alice"),
                threading.Thread(target=run, args=("bob", "sk-ant-BOB"), name="bob"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertEqual(results["alice"], "used:sk-ant-ALICE")
        self.assertEqual(results["bob"], "used:sk-ant-BOB")
        self.assertEqual(
            sorted(adapter.seen),
            [("alice", "sk-ant-ALICE"), ("bob", "sk-ant-BOB")],
        )

    def test_no_provider_key_is_ever_read_from_the_environment(self):
        # The zero-argument constructors of all three SDKs resolve a key from the process
        # environment. This asserts no adapter reaches for one, by planting keys that must
        # never be used and a selected credential that must be.
        adapter = FakeAdapter()
        planted = {
            "ANTHROPIC_API_KEY": "sk-ant-ENVIRONMENT",
            "OPENAI_API_KEY":    "sk-oai-ENVIRONMENT",
            "GEMINI_API_KEY":    "sk-gem-ENVIRONMENT",
        }
        with patch.dict(os.environ, planted, clear=False), \
             patch.object(llm, "adapter_for", return_value=adapter):
            reply = llm.complete(
                [{"role": "user", "content": "hi"}],
                provider="claude", model="claude-opus-5",
                credential=Credential(provider="anthropic", key="sk-ant-REQUEST"),
            )

        self.assertEqual(reply.text, "used:sk-ant-REQUEST")
        self.assertNotIn("ENVIRONMENT", reply.text)

    def test_the_layer_never_writes_the_environment(self):
        adapter = FakeAdapter()
        before = dict(os.environ)

        with patch.object(llm, "adapter_for", return_value=adapter):
            llm.complete([{"role": "user", "content": "hi"}],
                         provider="claude", model="claude-opus-5",
                         credential=Credential(provider="anthropic", key="sk-ant-x"))

        self.assertEqual(dict(os.environ), before)


class EmptyRepliesAreRefused(unittest.TestCase):
    def test_an_empty_response_is_unusable_not_a_silent_blank_card(self):
        class Blank(FakeAdapter):
            def complete(self, messages, *, model, credential, **kwargs):
                return Reply(text="   ", provider="anthropic", model=model)

        with patch.object(llm, "adapter_for", return_value=Blank()):
            with self.assertRaises(ResponseUnusable):
                llm.complete([{"role": "user", "content": "hi"}],
                             provider="claude", model="claude-opus-5",
                             credential=Credential(provider="anthropic", key="k"))


if __name__ == "__main__":
    unittest.main()


class ClientLifetime(unittest.TestCase):
    """Regression: the check() client must be held by a name, not built inline.

    `_client(...).models.get(...)` leaves the client unreferenced, so the collector can
    run its __del__ - which closes the underlying HTTP transport - before the request
    completes. google-genai fails that with "Cannot send a request, as the client has
    been closed". It only appears against a real endpoint, so it survived every mocked
    test and was found by the first live check.

    Asserting on source is unusual and deliberate: the bug is a lifetime property of the
    call expression, and no mock reproduces a garbage collection race."""

    def test_no_adapter_builds_a_throwaway_client_inline(self):
        import inspect

        from llm.adapters import anthropic_api, google_api, openai_api

        for module in (anthropic_api, google_api, openai_api):
            with self.subTest(adapter=module.NAME):
                source = inspect.getsource(module)
                self.assertNotIn(
                    "_client(credential, timeout=20.0).",
                    source,
                    f"{module.NAME}: bind the client to a name before calling it - an "
                    "unreferenced client can be closed mid-request",
                )

    def test_every_adapter_binds_the_client_before_using_it(self):
        import inspect

        from llm.adapters import anthropic_api, google_api, openai_api

        for module in (anthropic_api, google_api, openai_api):
            with self.subTest(adapter=module.NAME):
                source = inspect.getsource(module)
                self.assertIn("client = _client(credential, timeout=20.0)", source)
