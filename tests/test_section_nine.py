"""Section 9 at the point of rendering: the last gate before model prose reaches a card.

Fully offline. No model is called - `Interpretation` objects are built by hand, including
dishonest ones, because the property under test is that render.py does not trust them.

llm/interpret.py already validates before setting `accepted`. render.py validates AGAIN.
That duplication is the point: it turns "no unchecked prose reaches a card" from a promise
about every caller into a property of the function that prints the card. These tests are
what stop someone removing the second check as redundant.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import render
from llm.interpret import Interpretation
from tests.test_interpret import FAITHFUL, demo_run

PENDING = render.PENDING_REASONING


def section_nine(card: str) -> str:
    return card[card.index("## 9."):card.index("## 10.")]


class WithoutAnInterpretation(unittest.TestCase):
    """Every existing caller passes one argument and must get exactly today's card."""

    def test_the_default_card_is_unchanged(self):
        card = render.render_card(demo_run())
        self.assertIn(PENDING, section_nine(card))

    def test_none_is_the_same_as_omitting_it(self):
        self.assertEqual(render.render_card(demo_run()),
                         render.render_card(demo_run(), None))


class AcceptedProseIsPrinted(unittest.TestCase):
    def setUp(self):
        self.good = Interpretation(
            accepted = True,
            status   = "accepted",
            fields   = FAITHFUL,
            metadata = {"model": "claude-opus-5"},
        )

    def test_each_block_reaches_the_card(self):
        body = section_nine(render.render_card(demo_run(), self.good))
        for text in FAITHFUL.values():
            with self.subTest(text=text[:40]):
                self.assertIn(text, body)
        self.assertNotIn(PENDING, body)

    def test_the_card_says_which_model_wrote_it_and_that_it_was_checked(self):
        body = section_nine(render.render_card(demo_run(), self.good))
        self.assertIn("claude-opus-5", body)
        self.assertIn("checked against it", body)

    def test_the_other_ten_sections_are_untouched(self):
        # Section 9 is the model's and section 9 only.
        plain = render.render_card(demo_run())
        withprose = render.render_card(demo_run(), self.good)
        self.assertEqual(plain[:plain.index("## 9.")], withprose[:withprose.index("## 9.")])
        self.assertEqual(plain[plain.index("## 10."):], withprose[withprose.index("## 10."):])


class RenderDoesNotTrustTheFlag(unittest.TestCase):
    """The gate that matters. Each of these objects claims to have been accepted."""

    def render_forged(self, fields):
        forged = Interpretation(
            accepted = True,
            status   = "accepted",
            fields   = fields,
            metadata = {"model": "claude-opus-5"},
        )
        return section_nine(render.render_card(demo_run(), forged))

    def test_an_invented_number_is_refused_at_render_time(self):
        body = self.render_forged({"reading": "The effect size is 7.7771."})
        self.assertIn(PENDING, body)
        self.assertNotIn("7.7771", body)

    def test_an_invented_identifier_is_refused_at_render_time(self):
        body = self.render_forged({"reading": "Dataset ieu-a-99999 reports it."})
        self.assertIn(PENDING, body)
        self.assertNotIn("ieu-a-99999", body)

    def test_a_proof_claim_is_refused_at_render_time(self):
        body = self.render_forged({"headline": "This proves urate causes gout."})
        self.assertIn(PENDING, body)
        self.assertNotIn("proves", body)

    def test_the_card_says_prose_was_offered_and_rejected(self):
        # Silence would leave a reader unable to tell an unwired model from a caught one.
        body = self.render_forged({"reading": "The effect size is 7.7771."})
        self.assertIn("rejected", body)
        self.assertIn("evidence above is unaffected", body)

    def test_prose_validated_against_a_different_run_does_not_carry_over(self):
        # An interpretation cached from another pair would pass its own validation and
        # must still fail here, because here it is checked against THIS run.
        other = demo_run()
        other["envelopes"] = {}
        other["reason"] = "State C: no retrieved MR."
        forged = Interpretation(accepted=True, status="accepted", fields=FAITHFUL,
                                metadata={"model": "claude-opus-5"})
        body = section_nine(render.render_card(other, forged))
        self.assertIn(PENDING, body)


class UnusableInterpretationsFallBackQuietly(unittest.TestCase):
    def test_a_rejected_result_prints_the_pending_sentence(self):
        rejected = Interpretation(accepted=False, status="rejected", fields={},
                                  reason="validator: 1 finding(s); prose discarded.")
        self.assertIn(PENDING, section_nine(render.render_card(demo_run(), rejected)))

    def test_an_unavailable_result_prints_the_pending_sentence(self):
        unavailable = Interpretation(accepted=False, status="unavailable",
                                     reason="No Anthropic API key was supplied.")
        body = section_nine(render.render_card(demo_run(), unavailable))
        self.assertIn(PENDING, body)
        # The reason belongs in the log, not on a scientific card.
        self.assertNotIn("API key", body)

    def test_junk_in_place_of_an_interpretation_does_not_break_the_card(self):
        for junk in ("a string", 42, [], {"fields": FAITHFUL}, object()):
            with self.subTest(junk=type(junk).__name__):
                card = render.render_card(demo_run(), junk)
                self.assertIn(PENDING, section_nine(card))
                self.assertIn("## 11.", card)

    def test_empty_fields_print_the_pending_sentence(self):
        for fields in ({}, {"headline": ""}, {"headline": None}, None):
            with self.subTest(fields=fields):
                empty = Interpretation(accepted=True, status="accepted", fields=fields or {})
                self.assertIn(PENDING, section_nine(render.render_card(demo_run(), empty)))


if __name__ == "__main__":
    unittest.main()
