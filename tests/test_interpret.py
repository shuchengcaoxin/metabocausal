"""Section 9's agent: the digest it sends, the JSON it parses, and every way it gives up.

Fully offline - no provider SDK is installed and no request is made. The model is a stub
throughout; what is under test is the wiring around it.

The contract this file exists to pin is one sentence: `interpret` never raises, and
`accepted` is true only when a real model returned real JSON that the validator passed.
Every other path has to come back as a result the caller can render the deterministic card
from. The class at the bottom walks the failure table row by row.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm import Credential
from llm.base import (
    CredentialMissing,
    CredentialRejected,
    ModelNotSupported,
    ProviderUnavailable,
    RateLimited,
    Reply,
    ResponseUnusable,
)
from llm import interpret as interpret_module
from llm.interpret import Interpretation, build_digest, interpret, load_prompt, parse_fields

DEMO = REPO_ROOT / "data" / "demo_card_inputs.json"
CRED = Credential(provider="anthropic", key="sk-ant-TESTKEY")

FAITHFUL = {
    "headline": "Published causal estimates were retrieved for this pair.",
    "reading": (
        "The strongest retrieved row runs from ieu-a-789 to ieu-a-1054 and reports "
        "b = 1.367. It was retrieved from a pre-computed source, not calculated here."
    ),
    "limits": (
        "Colocalisation was not queried in this run, so nothing here says whether the two "
        "studies share a causal variant."
    ),
}


def demo_run() -> dict:
    entry = json.loads(DEMO.read_text(encoding="utf-8"))["pairs"]["urate|gout"]
    envelopes = entry["envelopes"]
    sample = entry["inputs_from_1a"]
    # The pipeline's run shape, built from the cached snapshot the same way render.py's
    # demo path builds it. Using the real snapshot keeps the validator's index real.
    return {
        "state":      entry["classify_state"]["state"],
        "reason":     entry["classify_state"]["reason"],
        "metabolite": {
            "query":    sample["metabolite"]["input"],
            "label":    sample["metabolite"]["label"],
            "id":       sample["metabolite"]["chebi"],
            "synonyms": sample["metabolite"]["synonyms"],
        },
        "disease": {
            "query":    sample["disease"]["input"],
            "label":    sample["disease"]["label"],
            "id":       sample["disease"]["id"],
            "synonyms": sample["disease"]["synonyms"],
        },
        "envelopes": {
            "mr":          envelopes["get_mr_result"],
            "instruments": envelopes["get_mqtl_instruments"],
            "outcomes":    envelopes["find_outcome_datasets"],
            "catalog":     envelopes["get_gwas_catalog"],
        },
        "coloc_summary":  {},
        "effector_genes": [],
        "notes":          ["cached snapshot, not a live run."],
    }


def replying(payload):
    """A stub `complete` that returns `payload` as the model's text."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return lambda *args, **kwargs: Reply(text=text, provider="anthropic", model="claude-opus-5")


class TheDigest(unittest.TestCase):
    """What the model is shown. Every value copied, nothing recomputed - so anything the
    model quotes back is a value the validator will find."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = demo_run()

    def test_it_carries_the_verdict_and_the_classifier_sentence(self):
        digest = build_digest(self.fixture)
        self.assertEqual(digest["state"], "A")
        self.assertEqual(digest["classifier_sentence"], self.fixture["reason"])

    def test_it_names_both_sides_with_their_resolved_ids(self):
        digest = build_digest(self.fixture)
        self.assertEqual(digest["metabolite_exposure"]["id"], "CHEBI:17775")
        self.assertEqual(digest["disease_outcome"]["id"], "MONDO:0005393")

    def test_estimates_are_capped_but_real(self):
        digest = build_digest(self.fixture)
        rows = digest["retrieved_estimates"]
        self.assertTrue(rows)
        self.assertLessEqual(len(rows), interpret_module.MAX_ESTIMATES)
        self.assertIn("method", rows[0])

    def test_arms_that_never_ran_are_named_not_omitted(self):
        # "not queried" and "queried and returned nothing" are different statements, and
        # section 9 has to be able to tell them apart.
        digest = build_digest(self.fixture)
        for arm in ("coloc", "atlas", "dossier"):
            with self.subTest(arm=arm):
                self.assertIn(arm, digest["arms"])
                self.assertIn("not run", str(digest["arms"][arm]["status"]))

    def test_arm_statuses_are_carried_verbatim(self):
        digest = build_digest(self.fixture)
        self.assertEqual(digest["arms"]["mr"]["status"], "ok")

    def test_a_sparse_run_does_not_break_the_digest(self):
        for sparse in ({}, {"state": "C"}, {"envelopes": None}, {"envelopes": {"mr": None}}):
            with self.subTest(sparse=sparse):
                self.assertIsInstance(build_digest(sparse), dict)


class ParsingTheReply(unittest.TestCase):
    def test_a_plain_object_parses(self):
        self.assertEqual(parse_fields(json.dumps(FAITHFUL)), FAITHFUL)

    def test_a_code_fence_is_stripped(self):
        fenced = "```json\n" + json.dumps(FAITHFUL) + "\n```"
        self.assertEqual(parse_fields(fenced), FAITHFUL)

    def test_an_object_wrapped_in_chatter_is_recovered(self):
        wrapped = "Here you go:\n" + json.dumps(FAITHFUL) + "\nHope that helps."
        self.assertEqual(parse_fields(wrapped), FAITHFUL)

    def test_unknown_keys_are_dropped_rather_than_passed_through(self):
        payload = dict(FAITHFUL, verdict="State A", score=0.9)
        parsed = parse_fields(json.dumps(payload))
        self.assertEqual(set(parsed), set(interpret_module.FIELDS))

    def test_malformed_output_yields_nothing(self):
        for text in ("", "   ", "not json at all", "[1, 2, 3]", "{", '{"headline": 12}',
                     '{"headline": "   "}', None):
            with self.subTest(text=text):
                self.assertEqual(parse_fields(text), {})


class ThePromptIsRequired(unittest.TestCase):
    def test_the_shipped_prompt_exists_and_states_the_core_rules(self):
        text = load_prompt()
        self.assertTrue(text.strip())
        for rule in ("must already appear", "Do not compute", "section 9"):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)

    def test_a_missing_prompt_leaves_section_nine_empty(self):
        # Improvising a prompt here would produce prose written to rules nobody reviewed.
        result = interpret(demo_run(), provider="claude", model="claude-opus-5",
                           credential=CRED, prompt_path=REPO_ROOT / "prompts" / "nope.md")
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, "unavailable")
        self.assertIn("prompt is missing", result.reason)


class TheHappyPath(unittest.TestCase):
    def test_faithful_prose_is_accepted_and_returned(self):
        with patch.object(interpret_module, "complete", replying(FAITHFUL)):
            result = interpret(demo_run(), provider="claude", model="claude-opus-5",
                               credential=CRED)

        self.assertTrue(result.accepted)
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.fields, FAITHFUL)
        self.assertEqual(result.findings, [])

    def test_metadata_records_what_ran_and_no_key(self):
        with patch.object(interpret_module, "complete", replying(FAITHFUL)):
            result = interpret(demo_run(), provider="claude", model="claude-opus-5",
                               credential=CRED)

        self.assertEqual(result.metadata["provider"], "anthropic")
        self.assertEqual(result.metadata["model"], "claude-opus-5")
        self.assertEqual(result.metadata["execution_mode"], "interpretation")
        self.assertNotIn("TESTKEY", repr(result.metadata))
        self.assertNotIn("TESTKEY", result.note())

    def test_the_note_is_one_loggable_line(self):
        with patch.object(interpret_module, "complete", replying(FAITHFUL)):
            note = interpret(demo_run(), provider="claude", model="claude-opus-5",
                             credential=CRED).note()
        self.assertIn("claude-opus-5", note)
        self.assertIn("accepted", note)


class RejectedProseIsDiscarded(unittest.TestCase):
    def test_an_invented_number_discards_the_whole_output(self):
        bad = dict(FAITHFUL, reading="The effect size is 7.7771 on the original scale.")
        with patch.object(interpret_module, "complete", replying(bad)):
            result = interpret(demo_run(), provider="claude", model="claude-opus-5",
                               credential=CRED)

        self.assertFalse(result.accepted)
        self.assertEqual(result.status, "rejected")
        # Not returned even for inspection: a caller cannot render what it does not have.
        self.assertEqual(result.fields, {})
        self.assertTrue(result.findings)
        self.assertIn("V1", {finding.rule for finding in result.findings})

    def test_one_bad_field_discards_the_good_ones_too(self):
        # Partial prose would leave a reader unable to tell which half was checked.
        bad = dict(FAITHFUL, limits="This proves urate causes gout.")
        with patch.object(interpret_module, "complete", replying(bad)):
            result = interpret(demo_run(), provider="claude", model="claude-opus-5",
                               credential=CRED)
        self.assertEqual(result.fields, {})
        self.assertIn("V2", {finding.rule for finding in result.findings})

    def test_the_rejection_note_says_it_was_discarded(self):
        bad = dict(FAITHFUL, reading="Driven by ZZZX9 at that locus.")
        with patch.object(interpret_module, "complete", replying(bad)):
            note = interpret(demo_run(), provider="claude", model="claude-opus-5",
                             credential=CRED).note()
        self.assertIn("discarded", note)


class EveryFailureLeavesTheCardShippable(unittest.TestCase):
    """The failure table from the design, row by row. None of these may raise, and none
    may come back accepted."""

    def assert_gives_up(self, result: Interpretation, expect_status="unavailable"):
        self.assertIsInstance(result, Interpretation)
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, expect_status)
        self.assertEqual(result.fields, {})
        self.assertTrue(result.reason.strip())
        self.assertNotIn("TESTKEY", result.reason)

    def run_with(self, side_effect):
        with patch.object(interpret_module, "complete", side_effect=side_effect):
            return interpret(demo_run(), provider="claude", model="claude-opus-5",
                             credential=CRED)

    def test_no_key_supplied(self):
        result = interpret(demo_run(), provider="claude", model="claude-opus-5",
                           credential=Credential(provider="anthropic", key=""))
        self.assert_gives_up(result)

    def test_invalid_or_revoked_key(self):
        self.assert_gives_up(self.run_with(
            CredentialRejected("Anthropic rejected this API key.", provider="anthropic")))

    def test_model_timeout(self):
        self.assert_gives_up(self.run_with(
            ProviderUnavailable("Could not reach Anthropic (APITimeoutError).",
                                provider="anthropic")))

    def test_rate_limited(self):
        self.assert_gives_up(self.run_with(
            RateLimited("Anthropic is rate limiting this key.", provider="anthropic")))

    def test_unknown_model_is_refused_before_any_request(self):
        with patch.object(interpret_module, "complete") as never:
            result = interpret(demo_run(), provider="claude", model="claude-opus-9",
                               credential=CRED)
        never.assert_not_called()
        self.assert_gives_up(result)

    def test_unbuilt_provider_is_refused_before_any_request(self):
        with patch.object(interpret_module, "complete") as never:
            result = interpret(demo_run(), provider="llama", model="llama-3",
                               credential=CRED)
        never.assert_not_called()
        self.assert_gives_up(result)

    def test_missing_sdk(self):
        self.assert_gives_up(self.run_with(
            ProviderUnavailable("The 'anthropic' package is not installed.",
                                provider="anthropic")))

    def test_refusal_or_empty_response(self):
        self.assert_gives_up(self.run_with(
            ResponseUnusable("The model returned an empty response.", provider="anthropic")))

    def test_malformed_json_has_nothing_to_validate(self):
        with patch.object(interpret_module, "complete", replying("I'm afraid I can't do that.")):
            result = interpret(demo_run(), provider="claude", model="claude-opus-5",
                               credential=CRED)
        self.assert_gives_up(result)
        self.assertIn("JSON", result.reason)

    def test_a_partial_object_is_not_half_accepted(self):
        with patch.object(interpret_module, "complete", replying({"headline": "Only this."})):
            result = interpret(demo_run(), provider="claude", model="claude-opus-5",
                               credential=CRED)
        # One valid field is enough to validate and ship; the renderer decides what to do
        # with a missing block. What must not happen is an unvalidated field getting through.
        self.assertTrue(result.accepted)
        self.assertEqual(set(result.fields), {"headline"})

    def test_a_bug_below_this_layer_does_not_become_a_traceback(self):
        # Anything that is NOT an LLMError is a defect in the layer below. It must not
        # reach a Slack handler as a traceback, and it must not be smoothed over either -
        # the exception type is named in the reason so the bug stays findable.
        result = self.run_with(RuntimeError("bug"))
        self.assert_gives_up(result)
        self.assertIn("RuntimeError", result.reason)
        self.assertIn("defect", result.reason)

    def test_a_bug_in_the_validator_does_not_become_a_traceback(self):
        with patch.object(interpret_module, "complete", replying(FAITHFUL)), \
             patch.object(interpret_module.validate_card, "validate",
                          side_effect=RuntimeError("validator bug")):
            result = interpret(demo_run(), provider="claude", model="claude-opus-5",
                               credential=CRED)
        self.assert_gives_up(result)


if __name__ == "__main__":
    unittest.main()
