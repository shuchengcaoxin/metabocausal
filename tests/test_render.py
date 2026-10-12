"""render.render_card's contract. Fully offline, no network, no model.

    python -m unittest tests.test_render -v          # from the repo root

The three headline pairs are built from data/demo_card_inputs.json, the CACHED SNAPSHOT
of the real envelopes taken 2026-09-10, so this file runs in under a second and spends
no OpenGWAS credit. Anything the snapshot cannot carry - a gene dossier, a ledger line
whose URL is longer than the cap, a result a caller mangled - is built here by hand from
the shapes the 1E tools document in their own docstrings.

WHAT IS ASSERTED, AND WHY EACH ONE IS THE REAL RISK

  the 11 sections, in order      the card template is the contract 1G and the Slack
                                 upload both read; a section that silently stops
                                 rendering is a section nobody notices is gone

  the verdict names the state    section 2 is the one line a room hears, and it must be
                                 the classifier's sentence, not a paraphrase

  section 9, verbatim            1F is not wired in. A card that invents a reasoning
                                 paragraph is worse than a card with none, because the
                                 invented one gets quoted

  "not evidence of no effect"    a trait absent from a 2020 snapshot printed as a
                                 negative result is the single failure this project
                                 exists to prevent

  nothing was "computed"         this project retrieves. The word may appear only inside
                                 "not computed" or "pre-computed", and that is checked
                                 character by character, not by eyeballing

  p never renders 0.0            met-d-Gly reports p exactly 0 on its strongest hit,
                                 because the source underflowed double precision. "0.0"
                                 reads as certainty; "<1e-300 (reported 0)" reads as
                                 what happened

  nsnp never renders 0           MR-EVE returns no SNP count in this snapshot. A 0 there
                                 would say "an MR with no instruments", which is absurd,
                                 and a reader would believe the card over their instinct

  per-report drug phases         a drug at phase 4 for another indication must never
                                 read as phase 4 for the disease that was asked about

  every cap printed              a silent truncation tells a reader 6 datasets were
                                 looked at when 22 measure the metabolite

  render_card never raises       slack_app.py calls it inside a Bolt listener, where an
                                 exception takes the whole reply with it
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import render

DEMO_PATH = REPO_ROOT / "data" / "demo_card_inputs.json"
LEDGER_DIR = REPO_ROOT / "cards"

# Every ledger this file writes carries this prefix, so no frozen demo ledger and no
# slack_ ledger can be truncated by a test run. They are deleted in tearDown.
PREFIX = "rendertest"

URATE = "urate|gout"
GLYCINE = "glycine|coronary artery disease"
TMAO = "trimethylamine N-oxide|coronary artery disease"
PAIRS = (URATE, GLYCINE, TMAO)

EXPECTED_STATE = {URATE: "A", GLYCINE: "B", TMAO: "C"}

# The only forms in which the word may appear on a card. Checked at every occurrence,
# because "the estimate was computed" and "no estimate was computed" differ by two words
# and a reader skims.
COMPUTED_ALLOWED = (
    "not computed",
    "pre-computed",
    "no estimate was computed",
)

# U+2026 HORIZONTAL ELLIPSIS is the one non-ASCII character the card is allowed to emit:
# the spec names it as the truncation marker for a long query string.
ALLOWED_NON_ASCII = {"…"}

_DEMO = json.loads(DEMO_PATH.read_text(encoding="utf-8"))


def envelopes_for(pair: str) -> dict:
    """The four cached envelopes of one pair, keyed the way run_pair keys them."""
    cached = _DEMO["pairs"][pair]["envelopes"]
    return {
        "mr":          cached["get_mr_result"],
        "instruments": cached["get_mqtl_instruments"],
        "outcomes":    cached["find_outcome_datasets"],
        "catalog":     cached["get_gwas_catalog"],
    }


def entity_for(
    pair: str,
    side: str,
) -> dict:
    """One side of the pair in the shape pipeline.resolve_entity returns."""
    block = _DEMO["pairs"][pair]["inputs_from_1a"][side]
    return {
        "query":         block["input"],
        "input":         block["input"],
        "label":         block["label"],
        "id":            block["chebi"] if side == "metabolite" else block["id"],
        "synonyms":      list(block["synonyms"]),
        "resolved":      True,
        "resolved_from": pair,
    }


def result_for(
    pair:      str,
    stem:      str = "",
    envelopes: dict | None = None,
    notes:     list | None = None,
) -> dict:
    """One pipeline.run_pair result, built from the cached snapshot.

    `stem` names the ledger file this result claims; the caller writes it (or does not,
    to exercise the fallback). The eight keys are exactly run_pair's.
    """
    cached = _DEMO["pairs"][pair]
    carried = envelopes_for(pair) if envelopes is None else envelopes
    path = str(LEDGER_DIR / f"{stem}{render.LEDGER_SUFFIX}") if stem else ""
    return {
        "state":            cached["classify_state"]["state"],
        "reason":           cached["classify_state"]["reason"],
        "metabolite":       entity_for(pair, "metabolite"),
        "disease":          entity_for(pair, "disease"),
        "envelopes":        carried,
        "ledger_path":      path,
        "n_ledger_entries": len(carried),
        "notes":            list(notes or []),
    }


def envelope(
    tool:   str,
    status: str,
    data:   dict,
) -> dict:
    """The eight shared keys, for a 1E envelope the cached snapshot does not carry."""
    return {
        "tool":         tool,
        "args":         {"gene_symbol": "GLDC"},
        "source":       "synthetic",
        "url":          "https://example.invalid/synthetic",
        "retrieved_at": "2026-09-10T00:00:00+00:00",
        "status":       status,
        "data":         data,
        "caveats":      ["Retrieved, not computed here."],
    }


def dossier_envelopes() -> dict:
    """One gene's four 1E envelopes, in the shapes tools/opentargets.py, tools/chembl.py
    and tools/gnomad.py document.

    The drug is deliberately the hard case: a phase 4 report for ANOTHER indication and a
    phase 2 report for the disease that was asked about, under one drug-level maximum
    stage. A card that rolls those up says an approved drug exists for this disease.
    """
    return {
        "GLDC": {
            "get_target_disease_evidence": envelope(
                "get_target_disease_evidence",
                "empty",
                {
                    "gene":           "GLDC",
                    "ensembl":        "ENSG00000178445",
                    "disease_efo":    "MONDO_0005010",
                    "target_disease": None,
                    "top_diseases":   [
                        {
                            "disease":        {"id": "MONDO_0011612", "name": "glycine encephalopathy"},
                            "score":          0.8408763617039781,
                            "datatypeScores": [{"id": "genetic_association", "score": 0.96478}],
                        },
                    ],
                    "page":           {
                        "index":          0,
                        "size":           25,
                        "returned_count": 25,
                        "total_count":    2259,
                    },
                },
            ),
            "get_known_drugs": envelope(
                "get_known_drugs",
                "ok",
                {
                    "gene":    "GLDC",
                    "ensembl": "ENSG00000178445",
                    "count":   1,
                    "drugs":   [
                        {
                            "candidate_id":       "CHEMBL1201212",
                            "drug":               "SYNTHETIC-DRUG",
                            "drug_id":            "CHEMBL1201212",
                            "max_clinical_stage": 4,
                            "clinical_reports":   [
                                {
                                    "report_id":   "NCT00000001",
                                    "url":         "https://clinicaltrials.gov/study/NCT00000001",
                                    "report_type": "interventional trial",
                                    "trial_phase": 4,
                                    "status":      "Completed",
                                    "why_stopped": None,
                                    "year":        2015,
                                    "source":      "ClinicalTrials.gov",
                                    "diseases":    [
                                        {"disease": {"id": "MONDO_0011612", "name": "glycine encephalopathy"}},
                                    ],
                                },
                                {
                                    "report_id":   "NCT00000002",
                                    "url":         "https://clinicaltrials.gov/study/NCT00000002",
                                    "report_type": "interventional trial",
                                    "trial_phase": 2,
                                    "status":      "Terminated",
                                    "why_stopped": "Slow accrual",
                                    "year":        2019,
                                    "source":      "ClinicalTrials.gov",
                                    "diseases":    [
                                        {"disease": {"id": "MONDO_0005010", "name": "coronary artery disease"}},
                                    ],
                                },
                            ],
                        },
                    ],
                    "returned_count": 1,
                    "complete":       True,
                },
            ),
            "get_chembl_modulators": envelope(
                "get_chembl_modulators",
                "ok",
                {
                    "gene":           "GLDC",
                    "target":         {
                        "target_chembl_id": "CHEMBL1075189",
                        "target_type":      "SINGLE PROTEIN",
                        "pref_name":        "Glycine dehydrogenase",
                        "organism":         "Homo sapiens",
                        "tax_id":           9606,
                    },
                    "mechanisms":     [
                        {
                            "mechanism_of_action":  "Glycine dehydrogenase inhibitor",
                            "action_type":          "INHIBITOR",
                            "molecule_chembl_id":   "CHEMBL1201212",
                            "target_chembl_id":     "CHEMBL1075189",
                        },
                    ],
                    "activity_count": 37,
                },
            ),
            "get_gnomad_constraint": envelope(
                "get_gnomad_constraint",
                "ok",
                {
                    "gene":             "GLDC",
                    "ensembl":          "ENSG00000178445",
                    "reference_genome": "GRCh38",
                    "constraint_field": "gnomad_constraint",
                    "dataset_release":  None,
                    "pli":              2.62507216308594e-30,
                    "oe_lof":           0.8574752307398049,
                    "oe_lof_upper":     1.0092138740780154,
                    "loeuf":            1.0092138740780154,
                    "oe_mis":           1.0936891726711044,
                },
            ),
        },
    }


class LedgerWritingCase(unittest.TestCase):
    """Writes real ledger files under cards/, prefixed and removed afterwards."""

    def setUp(self):
        self.written = []

    def tearDown(self):
        for path in self.written:
            if path.exists():
                path.unlink()

    def write_ledger(
        self,
        stem:      str,
        envelopes: list,
    ) -> Path:
        path = LEDGER_DIR / f"{stem}{render.LEDGER_SUFFIX}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in envelopes),
            encoding = "utf-8",
        )
        self.written.append(path)
        return path


class TestMRSensitivity(unittest.TestCase):
    def test_coloc_is_additional_evidence_and_preserves_clpp_only_results(self):
        for envelope, phrase in (
            (None, "not queried"),
            ({"status": "error", "data": {}}, "request failed"),
            ({"status": "empty", "data": {}}, "none retrieved"),
        ):
            result = {"state": "A", "envelopes": {"coloc": envelope}}
            text = render._coloc_qualifier(result)
            self.assertIn(phrase, text)
            self.assertIn("Any retrieved MR is retained", text)
            self.assertIn("not an inclusion requirement", text)
        result["envelopes"]["coloc"] = {
            "status": "ok",
            "data": {"metabolite_hits": [{"h4": None, "clpp": .8, "method": "ECAVIAR"}]},
        }
        text = render._coloc_qualifier(result)
        self.assertIn("CLPP = 0.8000", text)
        self.assertIn("CLPP is not H4", text)
        self.assertNotIn("none retrieved", text)
        self.assertNotIn("request failed", text)

    def test_required_absence_list_and_feasibility_separation(self):
        text = "\n".join(render._mr_sensitivity_lines([]))
        self.assertIn(
            "Steiger directionality: not reported by this resource. Heterogeneity Q: not reported. "
            "Egger intercept: not reported. LD check: not reported. Colocalisation: see the colocalisation "
            "section (retrieved separately from Open Targets).",
            text,
        )
        self.assertIn("NOT necessarily the instruments behind", render.F_NOTE)
        self.assertNotIn("upper bound", render.F_NOTE)

    def test_low_h4_does_not_assert_corroboration_or_worldwide_absence_of_mr(self):
        result = {
            "state": "B",
            "envelopes": {"coloc": {
                "status": "ok",
                "data": {"metabolite_hits": [{"h4": .01, "method": "COLOC"}]},
            }},
        }
        line = render._coloc_qualifier(result)
        self.assertIn("H4 = 0.0100", line)
        self.assertNotIn("Corroborated", line)
        self.assertNotIn("already colocalise", line)
        self.assertNotIn("never been computed", line)
        self.assertIn("No MR estimate was retrieved in this run", line)
        self.assertIn("Higher source H4 gives greater support", line)
        self.assertIn("not an MR inclusion requirement", line)

    def test_methods_not_compared_across_exposure_scales(self):
        rows = [{"exposure_id": "raw", "outcome_id": "d", "method": "IVW", "b": .2},
                {"exposure_id": "irnt", "outcome_id": "d", "method": "Egger", "b": -.3}]
        text = "\n".join(render._mr_sensitivity_lines(rows))
        self.assertEqual(text.count("Only one reported method"), 2)
        self.assertNotIn("Mixed directions", text)

    def test_discordance_wald_and_missing_checks_are_explicit(self):
        rows = [{"exposure_id": "x", "outcome_id": "d", "method": "IVW", "b": .2},
                {"exposure_id": "x", "outcome_id": "d", "method": "Wald ratio", "b": -.3, "nsnp": 1}]
        text = "\n".join(render._mr_sensitivity_lines(rows))
        self.assertIn("Mixed directions", text)
        self.assertIn("Single-SNP / Wald-ratio warning", text)
        self.assertIn("Egger intercept: not reported", text)
        self.assertIn("non-significant p-value is not evidence of no effect", text)

    def test_source_ci_not_recalculated_from_se(self):
        text = render._source_ci({"b": 1.3665, "se": .1068, "ci_low": .5812, "ci_upp": 2.1518})
        self.assertIn("0.5812", text)
        self.assertNotIn("1.157", text)


class TestSectionsAndOrder(unittest.TestCase):

    def test_every_section_header_is_present_and_in_order(self):
        for pair in PAIRS:
            with self.subTest(pair=pair):
                card = render.render_card(result_for(pair))
                positions = []
                for number, heading in enumerate(render.SECTIONS, start=1):
                    header = f"## {number}. {heading}"
                    self.assertIn(
                        header,
                        card,
                        f"{pair} lost section {number}",
                    )
                    positions.append(card.index(header))
                self.assertEqual(
                    positions,
                    sorted(positions),
                    f"{pair} renders its sections out of order",
                )

    def test_the_card_is_titled_with_the_pair_as_it_was_asked(self):
        card = render.render_card(result_for(URATE))
        self.assertTrue(card.startswith("# MetaboCausal evidence card - urate x gout"))

    def test_section_seven_distinguishes_not_assessed_from_no_reactions(self):
        card = render.render_card(result_for(URATE))
        body = card.split("## 7. ")[1].split("## 8. ")[0]
        self.assertIn("was not assessed in this run", body)
        self.assertIn("not evidence", body)

    def test_a_name_carrying_a_pipe_is_escaped_once_not_twice(self):
        """The sample entry key is "urate|gout". Both the field formatter and the table
        used to escape it, and the card printed `urate\\\\|gout`."""
        card = render.render_card(result_for(URATE))
        self.assertIn("urate\\|gout", card)
        self.assertNotIn("urate\\\\|gout", card)


class TestVerdict(unittest.TestCase):

    def test_the_verdict_line_names_the_state(self):
        for pair in PAIRS:
            with self.subTest(pair=pair):
                card = render.render_card(result_for(pair))
                state = EXPECTED_STATE[pair]
                label = render.STATE_LABELS[state]
                self.assertIn(f"**Verdict: State {state} - {label}.**", card)

    def test_the_classifier_sentence_is_reproduced_and_not_paraphrased(self):
        for pair in PAIRS:
            with self.subTest(pair=pair):
                result = result_for(pair)
                card = render.render_card(result)
                self.assertIn(" ".join(result["reason"].split()), card)

    def test_the_verdict_says_who_wrote_it(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("classify.classify_state", card)
        self.assertIn("No model wrote them", card)


class TestReasoningIsPending(unittest.TestCase):

    def test_section_nine_is_exactly_the_pending_sentence(self):
        for pair in PAIRS:
            with self.subTest(pair=pair):
                card = render.render_card(result_for(pair))
                body = card.split("## 9. Reasoning")[1].split("## 10. ")[0].strip()
                self.assertEqual(body, "Model reasoning pending integration (section 1F).")

    def test_the_pending_sentence_is_the_documented_one(self):
        self.assertEqual(
            render.PENDING_REASONING,
            "Model reasoning pending integration (section 1F).",
        )


class TestNumberFormatting(unittest.TestCase):

    def test_beta_and_se_render_to_four_significant_figures(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("| 1.367 | 0.1068 |", card)
        self.assertNotIn("1.3665151455190399", card)
        self.assertNotIn("0.106814322383297", card)

    def test_a_trailing_zero_that_is_a_real_figure_is_kept(self):
        """%g strips trailing zeros, so a b of 1.38039018070005 printed as "1.38" - three
        figures where the source gave four, on a real row of the flagship card."""
        card = render.render_card(result_for(URATE))
        self.assertIn("| 1.380 |", card)
        self.assertNotIn("| 1.38 |", card)
        self.assertEqual(render._effect(1.38039018070005), "1.380")
        self.assertEqual(render._effect(0.0226969500563215), "0.02270")
        self.assertEqual(render._effect(1.2000004), "1.200")

    def test_a_number_too_big_or_too_small_goes_exponential_like_g_does(self):
        self.assertEqual(render._effect(440466.0), "4.405e+05")
        self.assertEqual(render._effect(0.0000123456), "1.235e-05")
        self.assertEqual(render._effect(0), "0")
        self.assertEqual(render._effect(None), render.NOT_RETRIEVED)

    def test_a_p_value_renders_in_scientific_notation(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("1.79e-37", card)
        self.assertNotIn("1.7855974619591198e-37", card)

    def test_no_p_value_anywhere_renders_as_zero(self):
        """met-d-Gly reports p exactly 0 on its strongest hit: the source underflowed
        double precision. Printed as 0.0 that reads as certainty."""
        for pair in PAIRS:
            with self.subTest(pair=pair):
                card = render.render_card(result_for(pair))
                self.assertNotIn("p 0.0", card)
                self.assertNotIn("p=0.0", card)
                self.assertNotIn("| 0.0 |", card)
                self.assertNotIn("| 0.0e+00 |", card)

    def test_an_underflowed_p_value_renders_as_a_bound_naming_what_the_source_said(self):
        card = render.render_card(result_for(GLYCINE))
        self.assertIn("<1e-300 (reported 0)", card)

    def test_nsnp_renders_as_not_returned_rather_than_a_number(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("n/a (not returned by this snapshot)", card)
        table = card.split("## 3. ")[1].split("**MR sensitivity and source completeness**")[0].split("## 4. ")[0]
        rows = [line for line in table.splitlines() if line.startswith("| ieu-")]
        self.assertTrue(rows, "the State A card lost its estimate table")
        for row in rows:
            self.assertIn("n/a (not returned by this snapshot)", row)

    def test_moescore_is_labelled_every_time_it_is_shown(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("| moescore |", card)
        self.assertIn("mixture-of-experts score (0-1)", card)
        self.assertIn("It is NOT a p-value", card)


class TestWordingDiscipline(unittest.TestCase):

    def all_cards(self):
        return [(pair, render.render_card(result_for(pair))) for pair in PAIRS]

    def test_no_card_ever_claims_something_was_computed_here(self):
        """Each occurrence must sit INSIDE one of the allowed phrases, not merely near
        one. A window check passed "... from a pre-computed source. Computed here from
        the retrieved rows." because the denial 40 characters earlier covered for it."""
        for pair, card in self.all_cards():
            lowered = card.lower()
            spans = []
            for phrase in COMPUTED_ALLOWED:
                start = lowered.find(phrase)
                while start != -1:
                    spans.append((start, start + len(phrase)))
                    start = lowered.find(phrase, start + 1)
            for match in re.finditer("comput", lowered):
                covered = any(
                    begin <= match.start() and match.end() <= end
                    for begin, end in spans
                )
                self.assertTrue(
                    covered,
                    f"{pair}: \"computed\" outside a denial: "
                    f"...{card[max(0, match.start() - 60): match.start() + 40]}...",
                )

    def test_the_card_says_retrieved(self):
        for _pair, card in self.all_cards():
            self.assertIn("etrieved", card)

    def test_an_empty_arm_is_never_rendered_as_a_negative_result(self):
        for pair in (GLYCINE, TMAO):
            with self.subTest(pair=pair):
                card = render.render_card(result_for(pair))
                self.assertIn(
                    "not available in this snapshot - not evidence of no effect",
                    card,
                )
                self.assertNotIn("no effect was found", card)
                self.assertNotIn("no causal effect", card)
                self.assertNotIn("is not causal", card)

    def test_an_error_is_never_rendered_as_a_source_holding_no_record(self):
        """Both CAD pairs carry a GWAS Catalog envelope that timed out. "the request
        failed" and "the source has no row" are different sentences, and the check is
        scoped to the Catalog's own block - section 8 naming the failed tool elsewhere
        must not cover for an arm that stopped saying it."""
        for pair in (GLYCINE, TMAO):
            with self.subTest(pair=pair):
                card = render.render_card(result_for(pair))
                block = card.split("### GWAS Catalog (context only)")[1].split("## 5. ")[0]
                self.assertIn("returned an error envelope", block)
                self.assertIn("the request failed", block)
                self.assertIn(
                    "not the same statement as the Catalog holding no association",
                    block,
                )
                self.assertNotIn(render.EMPTY_ARM, block)

    def test_an_empty_arm_and_a_failed_arm_do_not_share_a_sentence(self):
        """glycine carries both: MR came back empty and the Catalog came back an error.
        The card must not describe them the same way."""
        card = render.render_card(result_for(GLYCINE))
        mr_block = card.split("## 3. ")[1].split("## 4. ")[0]
        catalog_block = card.split("### GWAS Catalog (context only)")[1].split("## 5. ")[0]
        self.assertIn(render.EMPTY_ARM, mr_block)
        self.assertNotIn("the request failed", mr_block)
        self.assertIn("the request failed", catalog_block)

    def test_the_catalog_is_named_as_context_and_not_as_a_classifier_input(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("not a classifier input", card)
        self.assertIn("an association can never move the A/B/C state", card)

    def test_the_card_carries_no_emoji(self):
        for pair, card in self.all_cards():
            offenders = {
                character for character in card
                if ord(character) > 0x2100 and character not in ALLOWED_NON_ASCII
            }
            self.assertEqual(
                offenders,
                set(),
                f"{pair} carries non-text characters",
            )


class TestCapsArePrinted(unittest.TestCase):

    def test_the_estimate_table_prints_its_own_cap(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("Table capped: 15 of 22 retrieved row(s) are shown", card)
        self.assertIn("sorted by retrieved p-value (smallest first)", card)

    def test_the_row_count_says_how_many_distinct_estimates_it_actually_carries(self):
        """22 is the number a room carries away, from the verdict, from section 3 and
        from the Slack field. MR-EVE returns one row per method and one per deposited id,
        and ieu-a-1054 / ebi-a-GCST001790 are the same 2013 gout GWAS - so those 22 rows
        carry 13 distinct (b, se, p) and are not 22 pieces of evidence."""
        card = render.render_card(result_for(URATE))
        body = card.split("## 3. ")[1].split("## 4. ")[0]
        self.assertIn("22 estimate row(s) retrieved", body)
        self.assertIn("They carry 13 distinct (b, se, p)", body)
        self.assertIn("not a count of independent studies", body)

    def test_the_card_says_when_it_holds_rows_the_forest_plot_cannot_draw(self):
        """The figure can only draw a row with a finite b AND se, so the table and the
        picture in the same Slack thread can hold different rows. render.py used to claim
        in a comment that they never could."""
        cached = envelopes_for(URATE)
        mangled = json.loads(json.dumps(cached))
        for row in mangled["mr"]["data"]["estimates"][:3]:
            row["se"] = None
        card = render.render_card(result_for(
            URATE,
            envelopes = mangled,
        ))
        body = card.split("## 3. ")[1].split("## 4. ")[0]
        self.assertIn("3 of the 22 retrieved row(s) lack b or a usable interval", body)
        self.assertIn("NOT on the forest plot", body)
        self.assertNotIn(
            "lack b or a usable interval",
            render.render_card(result_for(URATE)).split("## 3. ")[1].split("## 4. ")[0],
        )

    def test_the_tool_side_dataset_cap_is_printed_with_both_numbers(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("6 of the 22 dataset(s) named by these synonyms were queried", card)
        self.assertIn("The other 16 were never opened", card)

    def test_the_outcome_dataset_cap_is_printed(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("3 of the 4 matched dataset(s) are returned", card)

    def test_the_synonym_list_prints_its_own_cap(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("(showing 8 of 15)", card)

    def test_an_uncapped_list_says_so_rather_than_staying_silent(self):
        card = render.render_card(result_for(GLYCINE))
        self.assertIn("All 2 dataset(s) named by these synonyms were queried.", card)


class TestInstrumentsAndFeasibility(unittest.TestCase):

    def test_each_exposure_dataset_carries_its_own_platform_unit_and_size(self):
        card = render.render_card(result_for(GLYCINE))
        self.assertIn("| met-d-Gly | Glycine | Nightingale NMR (UK Biobank) |", card)
        self.assertIn("| met-a-468 | Glycine | mass spectrometry (Metabolon-type panel) | log10 units |", card)

    def test_f_is_labelled_as_an_upper_bound_and_not_a_fitted_first_stage(self):
        card = render.render_card(result_for(GLYCINE))
        self.assertIn("F = (beta/se)^2", card)
        self.assertIn("not the first-stage F of a fitted MR", card)
        self.assertIn("may be upward-biased", card)

    def test_a_broken_source_side_name_is_flagged_and_not_repaired(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("D<U+00F6>nerta<U+015F> HM", card)
        self.assertIn("printed exactly as OpenGWAS wrote them", card)

    def test_an_absent_field_reads_as_a_sentence_and_never_as_none(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("not recorded by this source", card)
        self.assertNotIn("| None |", card)

    def test_sex_and_note_separate_the_three_otherwise_identical_urate_scans(self):
        """ieu-a-786/787/788 are a BMI-by-SNP interaction scan in all samples, in men and
        in women. Without Sex and Note they render as one urate GWAS printed three times,
        and an interaction beta is not a main-effect exposure at all - which is exactly
        what get_mqtl_instruments says in its own caveats."""
        card = render.render_card(result_for(URATE))
        table = card.split("### Exposure datasets")[1].split("### Outcome datasets")[0]
        rows = {
            line.split("|")[1].strip(): line
            for line in table.splitlines()
            if line.startswith("| ieu-a-78")
        }
        for identifier in ("ieu-a-786", "ieu-a-787", "ieu-a-788"):
            self.assertIn(identifier, rows, "the three interaction scans lost their rows")
        self.assertEqual(
            len({line.split("|", 2)[2] for line in rows.values()}),
            len(rows),
            "the interaction scans still render as identical rows",
        )
        self.assertIn("| Males |", table)
        self.assertIn("| Females |", table)
        self.assertIn("BMI by SNP interaction men", table)
        self.assertIn("an interaction beta measures how a SNP effect changes", card)


class TestEffectorGenes(unittest.TestCase):
    def test_no_atlas_gene_is_a_mechanism_gap_without_hiding_mr(self):
        result = result_for(URATE)
        result["envelopes"]["atlas"] = {"status": "empty", "data": {"genes": []}}
        result["effector_genes"] = []
        card = render.render_card(result)
        self.assertIn("mechanism remains unresolved", card)
        self.assertIn("does not remove or invalidate retrieved metabolite MR", card)
        self.assertIn("22 estimate row(s) retrieved", card)
        self.assertNotIn("no gene on this card is named by a", card)
        self.assertEqual(result["state"], "A")

    def test_atlas_nomination_is_not_mislabeled_as_caller_supplied(self):
        result = result_for(GLYCINE)
        result["effector_genes"] = [{
            "gene_symbol": "GLDC", "atlases": ["Chen 2023"],
            "gene_source": ["author_prioritized"],
        }]
        result["envelopes"]["dossier"] = {"GLDC": {}}
        section = "\n".join(render._section_genes(result))
        self.assertIn("GLDC: named by Chen 2023; rule: author_prioritized", section)
        self.assertNotIn("supplied to this run by its caller", section)


    def test_catalog_genes_are_labelled_as_positional_and_not_as_effectors(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("| ABCG2 |", card)
        self.assertIn("Catalog mapping is proximity-based", card)
        self.assertIn("not an effector gene of the metabolite and not a target", card)

    def test_the_gene_table_is_ordered_by_the_column_a_reader_can_see(self):
        """The Variants column counts DISTINCT rsIDs, but the sort used annotation rows.
        Ensembl and NCBI each contribute a row, so a gene named by 2 variants through both
        sources sorted above a gene named by 3 variants through one."""
        card = render.render_card(result_for(URATE))
        table = card.split("## 5. ")[1].split("## 6. ")[0]
        counts = [
            int(line.split("|")[2].strip().replace(",", ""))
            for line in table.splitlines()
            if line.startswith("| ") and line.count("|") == 5 and "Gene" not in line
            and line.split("|")[2].strip().replace(",", "").isdigit()
        ]
        self.assertTrue(counts, "section 5 lost its gene table")
        self.assertEqual(counts, sorted(counts, reverse=True), counts)

    def test_unqueried_atlas_and_human_gem_are_named(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("atlas nomination layer was not queried", card)
        self.assertIn("Human-GEM biochemical candidates were not assessed", card)


class TestGeneDossiers(unittest.TestCase):

    def card_with_dossier(self) -> str:
        envelopes = envelopes_for(GLYCINE)
        envelopes["dossier"] = dossier_envelopes()
        return render.render_card(result_for(
            GLYCINE,
            envelopes = envelopes,
        ))

    def test_a_run_without_a_dossier_does_not_infer_absent_drugs_or_mr(self):
        card = render.render_card(result_for(URATE))
        body = card.split("## 6. ")[1].split("## 7. ")[0]
        self.assertIn("No gene dossier is available", body)
        self.assertIn("does not invalidate any retrieved", body)
        self.assertIn("does not mean that these genes have no drugs", body)

    def test_each_clinical_report_keeps_its_own_phase_status_and_disease(self):
        card = self.card_with_dossier()
        lines = [line for line in card.splitlines() if "report NCT" in line]
        self.assertEqual(
            len(lines),
            2,
            lines,
        )

        other, asked = lines
        self.assertIn("NCT00000001", other)
        self.assertIn("phase 4", other)
        self.assertIn("glycine encephalopathy", other)
        self.assertNotIn("coronary artery disease", other)

        self.assertIn("NCT00000002", asked)
        self.assertIn("phase 2", asked)
        self.assertIn("status Terminated", asked)
        self.assertIn("why stopped Slow accrual", asked)
        self.assertIn("coronary artery disease", asked)
        self.assertNotIn("phase 4", asked)

    def test_the_drug_level_maximum_stage_is_never_offered_as_this_disease_s_stage(self):
        card = self.card_with_dossier()
        self.assertIn("drug-level maxClinicalStage 4 across all of its indications", card)
        self.assertIn(
            "never a stage for the disease that was asked about",
            card,
        )

    def test_a_disease_absent_from_the_returned_page_is_a_gap_not_a_negative(self):
        card = self.card_with_dossier()
        self.assertIn("not on the returned association page", card)
        self.assertIn("page 0, size 25 of 2,259 associated diseases", card)
        self.assertIn("not available in this snapshot - not evidence of no effect", card)

    def test_gnomad_constraint_is_population_intolerance_and_not_safety(self):
        card = self.card_with_dossier()
        self.assertIn("LOEUF 1.009", card)
        self.assertIn("population intolerance to loss", card)
        self.assertIn("not clinical safety", card)

    def test_chembl_counts_are_labelled_as_assay_records(self):
        card = self.card_with_dossier()
        self.assertIn("CHEMBL1075189", card)
        self.assertIn("37 activity record(s)", card)
        self.assertIn("count assay rows, not unique ligands", card)

    def test_the_dossier_gene_is_named_in_section_five_as_supplied_not_retrieved(self):
        card = self.card_with_dossier()
        body = card.split("## 5. ")[1].split("## 6. ")[0]
        self.assertIn("GLDC", body)
        self.assertIn("supplied to this run by its caller", body)


class TestNextAction(unittest.TestCase):

    def test_state_a_points_at_the_row_a_reader_should_check_first(self):
        card = render.render_card(result_for(URATE))
        body = card.split("## 10. ")[1].split("## 11. ")[0]
        self.assertIn("ieu-a-789 -> ieu-a-1054", body)
        self.assertIn("p 1.79e-37", body)
        self.assertIn("one direction only", body.lower())

    def test_state_b_names_the_datasets_an_analysis_would_use(self):
        card = render.render_card(result_for(GLYCINE))
        body = card.split("## 10. ")[1].split("## 11. ")[0]
        self.assertIn("met-d-Gly", body)
        self.assertIn("49 genome-wide significant hit(s)", body)
        self.assertIn("sample overlap", body.lower())
        self.assertIn("not a prior that an effect exists", body)

    def test_state_c_says_the_gap_is_about_retrieval_and_not_about_biology(self):
        card = render.render_card(result_for(TMAO))
        body = card.split("## 10. ")[1].split("## 11. ")[0]
        self.assertIn("never about the biology", body)
        self.assertIn("Widen the metabolite synonyms", body)


class TestCaveats(unittest.TestCase):

    def test_every_tool_declared_caveat_is_reproduced_verbatim(self):
        result = result_for(URATE)
        card = render.render_card(result)
        for envelope_ in result["envelopes"].values():
            for caveat in envelope_["caveats"]:
                self.assertIn(" ".join(caveat.split()), card)

    def test_a_run_level_note_reaches_the_card(self):
        note = "disease 'gout please': entity not in the pre-resolved sample"
        card = render.render_card(result_for(
            URATE,
            notes = [note],
        ))
        self.assertIn(note, card)

    def test_a_failed_tool_is_named_in_its_own_list(self):
        card = render.render_card(result_for(GLYCINE))
        body = card.split("**Tools that failed in this run**")[1]
        self.assertIn("`get_gwas_catalog`", body)
        self.assertIn("A failed request is not a source with no record", body)

    def test_a_run_with_no_failure_says_so_rather_than_printing_an_empty_list(self):
        card = render.render_card(result_for(URATE))
        self.assertIn("No tool returned an error envelope.", card)


class TestProvenance(LedgerWritingCase):

    def test_the_digest_holds_one_row_per_ledger_line(self):
        stem = f"{PREFIX}_urate_gout"
        entries = list(envelopes_for(URATE).values())
        self.write_ledger(
            stem,
            entries,
        )
        result = result_for(
            URATE,
            stem = stem,
        )
        card = render.render_card(result)
        body = card.split("## 11. ")[1]
        self.assertIn(f"{stem}{render.LEDGER_SUFFIX}", body)
        self.assertIn(f"{len(entries)} read back at render time", body)
        for index, entry in enumerate(entries, start=1):
            row = [line for line in body.splitlines() if line.startswith(f"| {index} | ")]
            self.assertEqual(
                len(row),
                1,
                f"entry {index} has no digest row",
            )
            self.assertIn(entry["tool"], row[0])
            self.assertIn(entry["status"], row[0])
            self.assertIn(entry["retrieved_at"], row[0])

    def test_a_long_query_string_is_cut_at_eighty_characters_with_an_ellipsis(self):
        query = "exposure_trait=" + "Urate+or+uric+acid+" * 12
        long_url = f"https://api.epigraphdb.org/mr?{query}"
        stem = f"{PREFIX}_longurl"
        only_mr = envelope(
            "get_mr_result",
            "ok",
            {"estimates": [], "url": long_url},
        ) | {"url": long_url}
        self.write_ledger(
            stem,
            [only_mr],
        )
        # The ledger and the result must describe the SAME run, or section 11 falls back
        # to the run's own envelopes and this URL is never reached (see
        # test_a_ledger_that_belongs_to_another_run_is_refused_out_loud).
        card = render.render_card(result_for(
            URATE,
            stem      = stem,
            envelopes = {"mr": only_mr},
        ))
        body = card.split("## 11. ")[1]
        self.assertIn("api.epigraphdb.org/mr?", body)
        self.assertIn("…", body)
        self.assertNotIn(query, body)
        cut = query[:render.MAX_QUERY_CHARS] + "…"
        self.assertIn(cut, body)

    def test_a_url_with_no_query_keeps_its_whole_path(self):
        self.assertEqual(
            render._url_digest("https://www.ebi.ac.uk/gwas/rest/api/efoTraits/MONDO_0005393/associations"),
            "www.ebi.ac.uk/gwas/rest/api/efoTraits/MONDO_0005393/associations",
        )

    def test_a_tool_that_recorded_no_url_says_so(self):
        self.assertEqual(
            render._url_digest(""),
            "no URL recorded by this tool",
        )

    def test_a_missing_ledger_falls_back_to_the_result_and_says_it_did(self):
        result = result_for(
            URATE,
            stem = f"{PREFIX}_never_written",
        )
        card = render.render_card(result)
        body = card.split("## 11. ")[1]
        self.assertIn("could not be read at render time", body)
        self.assertIn("envelopes carried in the run's own result", body)
        self.assertIn("| get_mr_result |", body)

    def test_a_run_that_wrote_no_ledger_still_digests_its_envelopes(self):
        card = render.render_card(result_for(URATE))
        body = card.split("## 11. ")[1]
        self.assertIn("This run wrote no ledger file", body)
        self.assertIn("| get_mqtl_instruments |", body)

    def test_a_ledger_that_belongs_to_another_run_is_refused_out_loud(self):
        """Two mentions of the same pair share one stem, so the second run truncates the
        file the first is about to render from. The digest must never silently describe a
        different run under a sentence promising it came from the envelopes above."""
        stem = f"{PREFIX}_someone_elses_run"
        self.write_ledger(
            stem,
            [envelope(
                "get_known_drugs",
                "ok",
                {"gene": "SLC2A9", "drugs": []},
            )],
        )
        card = render.render_card(result_for(
            URATE,
            stem = stem,
        ))
        body = card.split("## 11. ")[1]
        self.assertIn("do not match the envelopes this run carries", body)
        self.assertIn("describe a different run of this pair", body)
        self.assertIn("| get_mr_result |", body, "the fallback digest is the run's own")
        self.assertNotIn("| get_known_drugs |", body)

    def test_a_carried_ledger_snapshot_is_rendered_without_re_opening_the_file(self):
        """slack_app reads the ledger inside its run lock and carries the lines in the
        result. Section 11 then renders from those lines, so no file read at render time
        can hand this card the next run's ledger."""
        entries = list(envelopes_for(URATE).values())
        result = result_for(
            URATE,
            stem = f"{PREFIX}_never_written_either",
        )
        result[render.LEDGER_ENTRIES_KEY] = entries
        body = render.render_card(result).split("## 11. ")[1]
        self.assertIn("carried in this run's own result and rendered from there", body)
        self.assertIn("cannot belong to another run of the same pair", body)
        self.assertNotIn("could not be read at render time", body)
        for entry in entries:
            self.assertIn(entry["tool"], body)

    def test_snapshot_ledger_reads_the_file_once_and_never_raises(self):
        stem = f"{PREFIX}_snapshot"
        entries = list(envelopes_for(URATE).values())
        self.write_ledger(
            stem,
            entries,
        )
        result = result_for(
            URATE,
            stem = stem,
        )
        self.assertEqual(
            [entry["tool"] for entry in render.snapshot_ledger(result)],
            [entry["tool"] for entry in entries],
        )
        self.assertEqual(render.snapshot_ledger({}), [])
        self.assertEqual(render.snapshot_ledger(None), [])
        self.assertEqual(
            render.snapshot_ledger({"ledger_path": str(LEDGER_DIR / "nothing-here.jsonl")}),
            [],
        )

    def test_the_closing_sentence_never_claims_estimates_a_card_does_not_have(self):
        """On glycine and TMAO, section 3 says no MR estimate was retrieved. The last
        sentence of the card used to assert the opposite about the same section."""
        for pair in (GLYCINE, TMAO):
            with self.subTest(pair=pair):
                body = render.render_card(result_for(pair)).split("## 11. ")[1]
                self.assertIn("no MR estimate was retrieved for this pair", body)
                self.assertNotIn("the estimates in section 3 are retrieved", body)
        body = render.render_card(result_for(URATE)).split("## 11. ")[1]
        self.assertIn("the estimates in section 3 are retrieved", body)


class TestCardFilename(LedgerWritingCase):

    def test_the_filename_follows_the_ledger_stem(self):
        result = result_for(
            URATE,
            stem = f"{PREFIX}_urate_gout",
        )
        self.assertEqual(render.card_filename(result), f"card_{PREFIX}_urate_gout.md")

    def test_a_slack_run_keeps_its_namespace_in_the_filename(self):
        result = result_for(
            URATE,
            stem = "slack_urate_gout",
        )
        self.assertEqual(render.card_filename(result), "card_slack_urate_gout.md")

    def test_without_a_ledger_the_stem_is_rebuilt_from_the_two_names(self):
        self.assertEqual(
            render.card_filename(result_for(TMAO)),
            "card_trimethylamine-n-oxide_coronary-artery-disease.md",
        )

    def test_a_result_with_nothing_in_it_still_yields_a_usable_filename(self):
        self.assertEqual(render.card_filename({}), "card_unknown_unknown.md")


class TestNeverRaises(unittest.TestCase):

    def assert_full_card(self, card):
        self.assertIsInstance(card, str)
        for number, heading in enumerate(render.SECTIONS, start=1):
            self.assertIn(f"## {number}. {heading}", card)

    def test_an_empty_result_still_renders_all_eleven_sections(self):
        self.assert_full_card(render.render_card({}))

    def test_a_result_that_is_not_a_dict_is_survived(self):
        self.assert_full_card(render.render_card("not a result"))

    def test_envelopes_of_the_wrong_type_do_not_take_the_card_down(self):
        broken = result_for(URATE)
        broken["envelopes"] = {
            "mr":          "this should have been a dict",
            "instruments": None,
            "outcomes":    {"status": "ok", "data": "also wrong"},
            "catalog":     [],
        }
        self.assert_full_card(render.render_card(broken))

    def test_a_dossier_of_the_wrong_shape_does_not_take_the_card_down(self):
        broken = result_for(URATE)
        broken["envelopes"] = dict(broken["envelopes"])
        broken["envelopes"]["dossier"] = {"GLDC": "not a dict of envelopes"}
        self.assert_full_card(render.render_card(broken))

    def test_a_section_that_fails_names_itself_and_the_others_still_print(self):
        """The guard is only worth having if it is exercised: a builder that raises must
        leave ten sections standing and one honest sentence in the eleventh."""
        original = render._section_mr

        def explode(_result):
            raise RuntimeError("a builder must never do this, but the card must survive")

        render._BUILDERS_BACKUP = render._BUILDERS
        render._section_mr = explode
        try:
            render._BUILDERS = tuple(
                explode if builder is original else builder
                for builder in render._BUILDERS
            )
            card = render.render_card(result_for(URATE))
        finally:
            render._BUILDERS = render._BUILDERS_BACKUP
            render._section_mr = original
            del render._BUILDERS_BACKUP

        self.assert_full_card(card)
        self.assertIn("This section could not be rendered (RuntimeError)", card)
        self.assertIn("not a statement about the biology", card)


if __name__ == "__main__":
    unittest.main(verbosity=2)
