"""The validator: what model prose may and may not say about a run.

Fully offline. The fixture is the real cached urate/gout run from
data/demo_card_inputs.json, not a hand-built dictionary, so a rule that only passes against
a convenient toy run fails here.

Read the classes in order: traceability first (V1, V5 - rigorous set membership), then the
language rules (V2, V3, V4, V6 - phrase heuristics), then the ways the validator itself is
made not to fail open.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import validate_card
from validate_card import Finding, source_index, traceable_number, validate

DEMO = REPO_ROOT / "data" / "demo_card_inputs.json"


def demo_run() -> dict:
    return json.loads(DEMO.read_text(encoding="utf-8"))["pairs"]["urate|gout"]


def rules(findings) -> set:
    return {finding.rule for finding in findings}


class Traceability(unittest.TestCase):
    """V1 and V5. These are set membership against the run's own values, so they are the
    checks that actually hold - a model cannot invent a figure or an id and pass them."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = demo_run()

    def test_faithful_prose_is_accepted(self):
        prose = {
            "headline": "Published causal estimates were retrieved for this pair.",
            "reading": (
                "The strongest retrieved row runs from ieu-a-789 to ieu-a-1054 and reports "
                "b = 1.367 with a standard error of 0.1068. That row was retrieved from a "
                "pre-computed source, not calculated here."
            ),
            "limits": (
                "Colocalisation was not queried in this run, so nothing here says whether "
                "the two studies share a causal variant. No sensitivity diagnostics were "
                "reported alongside these rows."
            ),
        }
        self.assertEqual(validate(prose, self.fixture), [])

    def test_an_invented_effect_size_is_caught(self):
        findings = validate({"reading": "The effect size is 7.7771."}, self.fixture)
        self.assertIn("V1", rules(findings))

    def test_an_invented_dataset_id_is_caught(self):
        findings = validate({"reading": "Dataset ieu-a-99999 reports the effect."}, self.fixture)
        self.assertIn("V5", rules(findings))
        self.assertIn("ieu-a-99999", str(findings[0]))

    def test_an_invented_gene_is_caught(self):
        findings = validate({"reading": "The locus is driven by ZZZX9."}, self.fixture)
        self.assertIn("V5", rules(findings))

    def test_a_gene_the_run_did_nominate_is_allowed(self):
        # SLC2A9 and ABCG2 really are in this run's catalog envelope. A validator that
        # rejected them would make the rule useless on exactly the pairs it matters for.
        index = source_index(self.fixture)
        self.assertTrue(index.has_string("SLC2A9"))
        self.assertEqual(validate({"reading": "SLC2A9 is named at that locus."}, self.fixture), [])

    def test_an_invented_ontology_term_and_trial_are_caught(self):
        for text in ("The disease resolved to MONDO:9999999.", "Trial NCT99999999 is listed."):
            with self.subTest(text=text):
                self.assertIn("V5", rules(validate({"reading": text}, self.fixture)))

    def test_digits_inside_an_identifier_are_not_read_as_quantities(self):
        # 'ieu-a-789' holds 789 and is not a number the prose is claiming. Masking
        # identifiers before number extraction is what keeps V1 from reporting it.
        self.assertEqual(validate({"reading": "See ieu-a-789 and ebi-a-GCST001790."}, self.fixture), [])

    def test_a_count_of_retrieved_rows_is_traceable(self):
        # 'retrieved 22 estimates' is true of a run that stores no 22. List lengths are
        # the one derived arithmetic the validator accepts.
        self.assertEqual(validate({"reading": "22 estimate rows were retrieved."}, self.fixture), [])


class NumberMatching(unittest.TestCase):
    """The precision rule, in isolation: prose that quotes a printed figure must pass, and
    a number that merely looks plausible must not."""

    def setUp(self):
        self.numbers = {1.3672, 0.10681, 1.7891e-37, 22.0, 1.0}

    def test_an_exact_value_matches(self):
        self.assertTrue(traceable_number("1.3672", self.numbers))

    def test_a_faithful_rounding_matches(self):
        # The card prints four significant figures, so quoted prose has fewer digits than
        # the source value it came from.
        self.assertTrue(traceable_number("1.367", self.numbers))
        self.assertTrue(traceable_number("1.37", self.numbers))

    def test_scientific_notation_matches_at_its_own_precision(self):
        self.assertTrue(traceable_number("1.79e-37", self.numbers))

    def test_a_nearby_invention_does_not_match(self):
        for invented in ("1.4", "2.367", "0.5", "99"):
            with self.subTest(invented=invented):
                self.assertFalse(traceable_number(invented, self.numbers))

    def test_human_scientific_notation_is_read_as_one_number(self):
        # Found by running the real prompt through a real model: it wrote the p-value as
        # '1.8x10^-37' with Unicode superscripts, and the extractor pulled out '1.8' and
        # '10' while silently dropping the exponent that gives the value its meaning.
        for written, expected in (
            ("1.8×10⁻³⁷", ["1.8e-37"]),
            ("1.8 × 10^-37",              ["1.8e-37"]),
            ("2.5x10^-4",                      ["2.5e-4"]),
            ("1.8E-37",                        ["1.8E-37"]),
        ):
            with self.subTest(written=written):
                normalised = validate_card.normalise_notation(written)
                self.assertEqual(validate_card.NUMBER.findall(normalised), expected)

    def test_a_re_rounded_p_value_is_still_refused(self):
        # Normalising the notation is a parsing fix, not a loosening: once the whole value
        # is read, a two-significant-figure rewrite of it is still not what the run holds.
        source = {1.7855974619591198e-37}
        self.assertTrue(traceable_number("1.7855974619591198e-37", source))
        self.assertFalse(traceable_number("1.8e-37", source))

    def test_nonsense_does_not_crash_the_matcher(self):
        for literal in ("", "..", "1e999999", "-"):
            with self.subTest(literal=literal):
                self.assertIsInstance(traceable_number(literal, self.numbers), bool)


class LanguageRules(unittest.TestCase):
    """V2, V3, V4 and V6. Phrase heuristics - they catch the obvious forms of the four
    claims this project most wants to avoid, and they are documented as heuristics."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = demo_run()

    def test_v2_the_state_presented_as_proof(self):
        for text in (
            "This proves that urate causes gout.",
            "State A confirms the causal relationship.",
            "The evidence is conclusive.",
            "This establishes that the exposure drives the outcome.",
        ):
            with self.subTest(text=text):
                self.assertIn("V2", rules(validate({"reading": text}, self.fixture)))

    def test_v2_allows_the_negated_house_wording(self):
        # The card itself says this. A rule that rejected it would reject the project's
        # own preferred sentence.
        text = "State A does not prove causation; it records that estimates were retrieved."
        self.assertNotIn("V2", rules(validate({"reading": text}, self.fixture)))

    def test_v3_an_explicit_mediation_claim(self):
        findings = validate({"reading": "The effect is mediated by the nominated gene."}, self.fixture)
        self.assertIn("V3", rules(findings))

    def test_v3_a_mediation_claim_that_never_says_mediate(self):
        # 'causes gout through SLC2A9' is the same claim in different words, and the gene
        # is genuinely in the run - so only the routing check can catch it.
        findings = validate({"reading": "Urate raises gout risk through SLC2A9."}, self.fixture)
        self.assertIn("V3", rules(findings))

    def test_v3_does_not_fire_on_a_method_abbreviation(self):
        # 'estimated via IVW' is not a causal chain. This is why the routing check consults
        # the vocabulary list instead of matching any capitalised token.
        text = "The estimate was produced via IVW on the source dataset."
        self.assertNotIn("V3", rules(validate({"reading": text}, self.fixture)))

    def test_v3_allows_saying_mediation_was_not_tested(self):
        text = "Nothing in this run tests mediation, so the mechanism is unresolved."
        self.assertNotIn("V3", rules(validate({"reading": text}, self.fixture)))

    def test_v4_absence_rendered_as_a_biological_negative(self):
        for text in (
            "There is no effect of urate on gout.",
            "This rules out a causal relationship.",
            "The analysis returned a null result.",
            "There is no association between the two.",
        ):
            with self.subTest(text=text):
                self.assertIn("V4", rules(validate({"reading": text}, self.fixture)))

    def test_v4_allows_the_correct_way_to_say_it(self):
        text = "Colocalisation was not queried, so no shared-variant evidence was retrieved."
        self.assertNotIn("V4", rules(validate({"limits": text}, self.fixture)))

    def test_v6_colocalisation_moving_the_state(self):
        for text in (
            "The high H4 upgrades this pair to State A.",
            "Colocalisation promoted the verdict.",
            "A CLPP that low would downgrade it to state C.",
        ):
            with self.subTest(text=text):
                self.assertIn("V6", rules(validate({"reading": text}, self.fixture)))

    def test_v6_allows_colocalisation_described_as_a_qualifier(self):
        text = (
            "Colocalisation runs after the verdict and cannot move a pair between "
            "state A, state B and state C."
        )
        self.assertNotIn("V6", rules(validate({"reading": text}, self.fixture)))


class TheValidatorDoesNotFailOpen(unittest.TestCase):
    """A validator that raises takes down the card it protects, and a validator that
    returns [] on junk input lets that junk ship. Neither is allowed."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = demo_run()

    def test_a_plain_string_is_accepted_as_input(self):
        self.assertIn("V1", rules(validate("The effect size is 7.7771.", self.fixture)))

    def test_non_text_input_is_a_finding_not_a_crash(self):
        self.assertTrue(validate(["not", "a", "dict"], self.fixture))
        self.assertTrue(validate({"reading": 12345}, self.fixture))

    def test_an_unreadable_run_is_a_finding_not_a_crash(self):
        class Exploding(dict):
            def items(self):
                raise RuntimeError("boom")

        findings = validate({"reading": "text"}, Exploding())
        self.assertEqual(rules(findings), {"V0"})

    def test_a_check_that_raises_becomes_a_finding(self):
        original = validate_card._check_language
        try:
            validate_card._check_language = lambda *a, **k: (_ for _ in ()).throw(ValueError("x"))
            findings = validate({"reading": "text"}, self.fixture)
        finally:
            validate_card._check_language = original
        self.assertIn("V0", rules(findings))

    def test_empty_prose_produces_no_findings(self):
        self.assertEqual(validate({}, self.fixture), [])
        self.assertEqual(validate({"reading": None}, self.fixture), [])

    def test_summarise_names_the_count_and_never_holds_a_key(self):
        findings = [Finding(rule="V1", name="n", detail="d")]
        text = validate_card.summarise(findings)
        self.assertIn("1 finding", text)
        self.assertIn("discarded", text)
        self.assertEqual(validate_card.summarise([]), "validator: no findings; prose may ship.")


if __name__ == "__main__":
    unittest.main()


class V4DoesNotRejectCorrectWording(unittest.TestCase):
    """V4 must catch a model ASSERTING a biological negative and allow one DENYING it.

    Found by running the fixtures against a live model: two of three State C runs were
    rejected for sentences that said exactly the right thing. The generic negation test
    cannot serve here, because the phrase V4 matches contains a negation word itself -
    "there is no effect" holds "no". What separates the two is a disclaiming construction.
    """

    @classmethod
    def setUpClass(cls):
        cls.fixture = demo_run()

    def v4_fires(self, text) -> bool:
        return "V4" in rules(validate({"limits": text}, self.fixture))

    def test_the_deterministic_cards_own_wording_is_allowed(self):
        # An earlier version of this rule rejected render.EMPTY_ARM. A validator that
        # refuses the card it protects is wrong about the rule, not about the card.
        import render

        self.assertFalse(self.v4_fires(render.EMPTY_ARM))

    def test_live_model_sentences_that_disclaim_correctly_are_allowed(self):
        for text in (
            "These empty outcomes reflect database limitations and coverage gaps rather "
            "than biological proof of no effect.",
            "Readers should view this as an absence of retrieved information rather than "
            "evidence of a true biological null effect.",
            "An empty arm does not mean there is no effect.",
            "This should not be read as a null result.",
        ):
            with self.subTest(text=text[:50]):
                self.assertFalse(self.v4_fires(text))

    def test_a_plain_assertion_is_still_caught(self):
        for text in (
            "There is no effect of urate on gout.",
            "The analysis returned a null result.",
            "This rules out a causal relationship.",
            "There is no association between the two.",
        ):
            with self.subTest(text=text):
                self.assertTrue(self.v4_fires(text))

    def test_retrieval_talk_is_not_a_biological_negative(self):
        # "no effect" is a claim about biology; "no effect ESTIMATE" is a claim about
        # retrieval, and State C prose is full of the second. All four of these came from
        # live model runs and were wrongly rejected before the lookahead was added.
        for text in (
            "no association rows were retrieved from that source",
            "no causal effect estimate was generated in either direction",
            "no association data could be loaded for coronary artery disorder",
            "no effect estimates are reported in this run",
            "no effect values were returned by the source",
        ):
            with self.subTest(text=text[:50]):
                self.assertFalse(self.v4_fires(text))

    def test_the_biological_claim_is_still_caught_without_those_nouns(self):
        for text in (
            "There is no effect of urate on gout.",
            "We found no association between the two.",
            "There is no causal relationship here.",
        ):
            with self.subTest(text=text):
                self.assertTrue(self.v4_fires(text))

    def test_process_framing_is_not_a_biological_negative(self):
        # "no causal relationship could be EVALUATED" says the analysis did not happen.
        # On a State C run that is most of what there is to say, and every one of these
        # came from a live model and was wrongly rejected before the exemption widened.
        for text in (
            "Consequently, no causal relationship or association could be evaluated for this pair.",
            "No causal effect estimate was generated in either direction.",
            "No association rows were retrieved from that source.",
            "No association data could be loaded for coronary artery disorder.",
        ):
            with self.subTest(text=text[:50]):
                self.assertFalse(self.v4_fires(text))

    def test_a_claim_about_the_result_is_still_caught(self):
        # "was found" is deliberately absent from the process verbs: a result that was
        # looked for and not found is a claim about the world, not about the query.
        self.assertTrue(self.v4_fires("No effect was found for this exposure."))


class SourceHasNoControlCharacters(unittest.TestCase):
    """A literal 0x08 byte once reached this file in place of a `\b` escape, turning a
    word boundary into a backspace that silently matched nothing. Editors and `sed` both
    render it invisibly, so the pattern looked correct while failing."""

    def test_the_validator_source_is_clean(self):
        raw = (REPO_ROOT / "validate_card.py").read_bytes()
        for byte in range(1, 9):
            with self.subTest(byte=hex(byte)):
                self.assertEqual(raw.count(bytes([byte])), 0)
