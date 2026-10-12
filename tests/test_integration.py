"""1A(sample) -> 1B -> 1C -> classify as one chain. Network-live, stdlib unittest.

    python -m unittest tests.test_integration -v          # from the repo root

test_1b and test_1c_* each check one tool against its own database. This file checks
the thing none of them can see: that the four envelopes fit together, that every one
of them reaches the ledger, and that the state the classifier returns for the three
pairs the demo rests on is the state we say it is on stage.

THE THREE STATES ASSERTED HERE, AND THE EVIDENCE BEHIND EACH (measured 2026-09-10)

  urate|gout                            A   get_mr_result returns 22 MR-EVE rows;
                                            ieu-a-789 -> ieu-a-1054 FE IVW b=1.3665,
                                            se=0.1068, p=1.79e-37.
  glycine|coronary artery disease        B   MR-EVE holds no Glycine -> CAD row at all,
                                            but met-d-Gly (n=114,972, Nightingale NMR)
                                            returns 49 clumped hits at p<5e-8 and CAD
                                            has 9 outcome datasets. met-d does not
                                            exist in EpiGraphDB's 2020 snapshot, so
                                            this state is reachable only because 1C
                                            re-pulled gwasinfo. The flagship demo.
  trimethylamine N-oxide|CAD             C   no synonym of TMAO names any of the 50,056
                                            gwasinfo traits or any EpiGraphDB trait, so
                                            there is no exposure to instrument. The
                                            outcome side still matches 9 CAD datasets -
                                            C here means "no exposure data", which is
                                            what the caveats must say.

The other three pairs come out A (creatinine|CKD, 3 rows; citrate|ischemic stroke, 6
rows) and B (isoleucine|type 2 diabetes, met-d-Ile 10 hits). They are not asserted
here: their MR-EVE row counts are a property of a snapshot, not of this wiring.

WHY THESE RUN WITH THE CATALOG SKIPPED. get_gwas_catalog takes ~100 s per disease and
its own suite already covers it. Skipping it also makes `ledger_keys` and the ledger
agree exactly, which is the assertion in TestLedgerIsComplete; TestCatalogIsRecorded
covers the other case with a stub, because the wiring claim there ("recorded, never
classified") is about end_to_end.py, not about EBI.

Each pair is run ONCE for the whole file - every run sends real queries and spends
OpenGWAS credits. The ledgers these tests overwrite are saved and put back afterwards.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import classify
import ledger
from scripts import end_to_end
from tools import _common

ENVELOPE_KEYS = {"tool", "args", "source", "url", "retrieved_at", "status", "data", "caveats"}

GLYCINE = "glycine|coronary artery disease"
URATE = "urate|gout"
TMAO = "trimethylamine N-oxide|coronary artery disease"

SAMPLE = end_to_end.load_sample()

_RESULTS = {}
_SAVED_LEDGERS = {}


def result_for(pair: str) -> dict:
    """One pipeline run per pair per test session, cached. Every call to this would
    otherwise re-send the MR-EVE queries and re-spend OpenGWAS tophits credits."""
    if pair not in _RESULTS:
        _RESULTS[pair] = end_to_end.run_pair(
            pair,
            SAMPLE[pair],
            skip_catalog = True,
        )
    return _RESULTS[pair]


def setUpModule():
    for pair in (GLYCINE, URATE, TMAO):
        target = ledger.path_for(end_to_end.stem_for(pair))
        _SAVED_LEDGERS[pair] = target.read_bytes() if target.exists() else None


def tearDownModule():
    for pair, saved in _SAVED_LEDGERS.items():
        target = ledger.path_for(end_to_end.stem_for(pair))
        if saved is None:
            if target.exists():
                target.unlink()
        else:
            target.write_bytes(saved)


class EnvelopeMixin:
    def assert_envelope(
        self,
        env,
        tool,
    ):
        self.assertIsInstance(env, dict)
        self.assertEqual(
            set(env),
            ENVELOPE_KEYS,
            f"{tool} must return exactly the eight shared keys",
        )
        self.assertEqual(env["tool"], tool)
        self.assertIn(env["status"], _common.STATUSES)
        self.assertIsInstance(env["data"], dict)
        self.assertIsInstance(env["caveats"], list)
        self.assertTrue(env["caveats"], f"{tool} must carry at least one caveat")


class TestStateA(EnvelopeMixin, unittest.TestCase):
    """urate|gout. A because an estimate was RETRIEVED, not because an effect is real."""

    @classmethod
    def setUpClass(cls):
        cls.result = result_for(URATE)

    def test_state_is_a(self):
        self.assertEqual(self.result["state"], "A")

    def test_a_rests_on_the_published_estimate(self):
        env = self.result["mr_env"]
        self.assert_envelope(env, "get_mr_result")
        self.assertEqual(env["status"], "ok")
        self.assertGreaterEqual(env["data"]["n_estimates"], 1)

        published = [
            estimate for estimate in env["data"]["estimates"]
            if estimate["exposure_id"] == "ieu-a-789"
            and estimate["method"] == "FE IVW"
            and abs(estimate["b"] - 1.3665) < 0.01
        ]
        self.assertTrue(published, "the ieu-a-789 -> gout FE IVW row, b=1.3665, must survive the chain")

    def test_reason_says_retrieved_not_computed(self):
        reason = self.result["verdict"]["reason"].lower()
        self.assertIn("retrieved", reason)
        self.assertIn("not computed here", reason)

    def test_instruments_and_outcomes_are_there_too(self):
        """A does not mean the 1C half was skipped: an A pair still reports its
        instruments, and the card shows them beside the retrieved estimate."""
        instr = self.result["instr_env"]
        self.assert_envelope(instr, "get_mqtl_instruments")
        self.assertEqual(instr["status"], "ok")
        # ieu-b-5137 (n=440,466) measured 323 clumped hits. A met- prefix filter would
        # never have reached it: only 1 of urate's 22 matched datasets is met-*.
        self.assertTrue([
            row for row in instr["data"]["exposures"]
            if row["id"] == "ieu-b-5137" and row["gws_hits"] >= classify.GWS_HITS_MIN
        ])

        outcome = self.result["outcome_env"]
        self.assert_envelope(outcome, "find_outcome_datasets")
        self.assertEqual(outcome["status"], "ok")
        self.assertTrue(outcome["data"]["datasets"])


class TestStateB(EnvelopeMixin, unittest.TestCase):
    """glycine|coronary artery disease - the flagship. B exists only because 1C looks
    at a live gwasinfo that has met-d in it; EpiGraphDB's 2020 snapshot does not."""

    @classmethod
    def setUpClass(cls):
        cls.result = result_for(GLYCINE)

    def test_state_is_b(self):
        self.assertEqual(self.result["state"], "B")

    def test_b_needs_the_mr_half_to_be_honestly_empty(self):
        env = self.result["mr_env"]
        self.assert_envelope(env, "get_mr_result")
        self.assertEqual(env["status"], "empty")
        self.assertEqual(env["data"]["n_estimates"], 0)
        self.assertTrue(
            env["data"]["exposure_matches"],
            "the exposure DID match a dataset - empty here means MR-EVE holds no row, "
            "not that glycine is unknown, and the caveat must be able to say which",
        )
        self.assertIn("not evidence of no effect", " ".join(env["caveats"]).lower())

    def test_b_rests_on_met_d_gly(self):
        instr = self.result["instr_env"]
        self.assert_envelope(instr, "get_mqtl_instruments")
        self.assertEqual(instr["status"], "ok")

        gly = [row for row in instr["data"]["exposures"] if row["id"] == "met-d-Gly"]
        self.assertTrue(gly, "met-d-Gly is the dataset the whole B state depends on")
        # Measured 49 clumped hits at p<5e-8, min F 26.4, zero weak. The threshold is
        # what the classifier reads; the count is what makes the demo worth showing.
        self.assertGreaterEqual(gly[0]["gws_hits"], classify.GWS_HITS_MIN)
        self.assertEqual(gly[0]["weak_instruments"], 0)
        self.assertIsNotNone(gly[0]["min_f"])

    def test_b_needs_an_outcome_dataset(self):
        outcome = self.result["outcome_env"]
        self.assert_envelope(outcome, "find_outcome_datasets")
        self.assertEqual(outcome["status"], "ok")
        self.assertTrue(outcome["data"]["datasets"])
        self.assertGreater(
            outcome["data"]["n_matched_before_cap"],
            outcome["data"]["n_datasets"],
            "CAD matches 9 datasets and top_n is 3, so the cap must be visible in the data",
        )
        self.assertTrue(
            [caveat for caveat in outcome["caveats"] if caveat.startswith("Capped:")],
            "a cap that bit and was not stated is a silent truncation",
        )

    def test_reason_names_the_hit_count_and_the_outcome_count(self):
        reason = self.result["verdict"]["reason"]
        self.assertIn("analysis-ready", reason)
        self.assertIn("could be analysed", reason)
        self.assertNotIn("causal", reason.lower())


class TestStateC(EnvelopeMixin, unittest.TestCase):
    """TMAO|coronary artery disease. C is a statement about the databases, and the
    envelopes have to say so in words a reader can check."""

    @classmethod
    def setUpClass(cls):
        cls.result = result_for(TMAO)

    def test_state_is_c(self):
        self.assertEqual(self.result["state"], "C")

    def test_both_metabolite_lookups_are_empty_and_neither_sent_a_request(self):
        mr = self.result["mr_env"]
        instr = self.result["instr_env"]
        self.assert_envelope(mr, "get_mr_result")
        self.assert_envelope(instr, "get_mqtl_instruments")

        self.assertEqual(mr["status"], "empty")
        self.assertEqual(mr["data"]["exposure_matches"], [])
        self.assertEqual(mr["data"]["queries"], [])

        self.assertEqual(instr["status"], "empty")
        self.assertEqual(instr["data"]["matched_datasets"], 0)
        self.assertEqual(
            instr["data"]["queries"],
            [],
            "no synonym matched, so no tophits credit should have been spent",
        )
        self.assertEqual(
            instr["url"],
            "",
            "url is the URL actually sent, and none was",
        )

    def test_the_outcome_side_still_matched(self):
        """The disease is in the release; only the metabolite is missing. A C reason
        that blamed the disease would be wrong about which half of the pair failed."""
        outcome = self.result["outcome_env"]
        self.assertEqual(outcome["status"], "ok")
        self.assertTrue(outcome["data"]["datasets"])

    def test_c_never_claims_no_effect(self):
        reason = self.result["verdict"]["reason"].lower()
        self.assertIn("not evidence of no effect", reason)
        for forbidden in ("no effect on", "no causal", "no genetic basis"):
            self.assertNotIn(forbidden, reason)

        caveats = " ".join(self.result["instr_env"]["caveats"]).lower()
        self.assertIn("not evidence of no effect", caveats)
        self.assertIn("not evidence of no genetic basis", caveats)


class TestLedgerIsComplete(unittest.TestCase):
    """One line per tool call, each an eight-key envelope, and the classifier's
    ledger_keys naming every one of them - that is what makes the card auditable."""

    @classmethod
    def setUpClass(cls):
        cls.result = result_for(URATE)

    def test_one_line_per_tool_call_in_call_order(self):
        lines = self.result["ledger_lines"]
        self.assertEqual(
            [line["tool"] for line in lines],
            ["get_mr_result", "get_mqtl_instruments", "find_outcome_datasets"],
        )

    def test_every_ledger_line_is_a_full_envelope(self):
        for line in self.result["ledger_lines"]:
            self.assertEqual(set(line), ENVELOPE_KEYS)
            self.assertIn(line["status"], _common.STATUSES)
            self.assertIsInstance(line["data"], dict)
            self.assertIsInstance(line["caveats"], list)
            self.assertTrue(line["retrieved_at"])

    def test_ledger_keys_names_every_tool_that_ran(self):
        self.assertEqual(
            self.result["verdict"]["ledger_keys"],
            [line["tool"] for line in self.result["ledger_lines"]],
        )
        self.assertEqual(self.result["verdict"]["failed_tools"], [])

    def test_the_lines_on_disk_are_the_envelopes_that_were_returned(self):
        reloaded = ledger.load(self.result["stem"])
        self.assertEqual(len(reloaded), len(self.result["ledger_lines"]))
        self.assertEqual(reloaded[0]["url"], self.result["mr_env"]["url"])
        self.assertEqual(
            reloaded[1]["data"]["n_exposures"],
            self.result["instr_env"]["data"]["n_exposures"],
        )

    def test_the_ledger_is_closed_after_a_run(self):
        """A run that leaves the ledger open would append the next pair's tool calls to
        this pair's file, and every card after the first would be wrong."""
        self.assertIsNone(ledger.active_stem())


class TestCatalogIsRecordedButNotClassified(unittest.TestCase):
    """get_gwas_catalog reaches the ledger and never reaches the classifier. EBI is
    stubbed here: the claim under test is end_to_end's wiring, not the Catalog, which
    tests/test_1c_gwascat.py covers and which costs ~100 s per call."""

    # Its own key, so its ledger is its own file: this runs the pair a second time and
    # must not leave a four-line urate_gout ledger behind for another test to read.
    KEY = "_integration-stub|urate gout"

    def setUp(self):
        self.original = end_to_end.get_gwas_catalog

    def tearDown(self):
        end_to_end.get_gwas_catalog = self.original
        target = ledger.path_for(end_to_end.stem_for(self.KEY))
        if target.exists():
            target.unlink()

    def test_four_lines_on_disk_three_in_ledger_keys(self):
        def stub(**kwargs):
            env = _common.envelope(
                tool    = "get_gwas_catalog",
                args    = kwargs,
                source  = "GWAS Catalog (EBI) REST API",
                url     = "https://www.ebi.ac.uk/gwas/rest/api/efoTraits/MONDO_0005393/associations",
                status  = "ok",
                data    = {"efo_short_form": "MONDO_0005393", "associations": [], "mapped_genes": []},
                caveats = ["stubbed in tests/test_integration.py"],
            )
            ledger.record(env)
            return env

        end_to_end.get_gwas_catalog = stub
        # The state asserted below comes from the MR half, so the 1C caps are turned
        # down to 1: this is a second live run of the same pair and tophits costs credits.
        result = end_to_end.run_pair(
            self.KEY,
            SAMPLE[URATE],
            skip_catalog = False,
            max_datasets = 1,
            top_n        = 1,
        )

        self.assertEqual(
            [line["tool"] for line in result["ledger_lines"]],
            ["get_mr_result", "get_mqtl_instruments", "find_outcome_datasets", "get_gwas_catalog"],
        )
        self.assertNotIn(
            "get_gwas_catalog",
            result["verdict"]["ledger_keys"],
            "an association is not an MR estimate and not an instrument count; letting it "
            "into the classifier would let it move the state",
        )
        self.assertEqual(result["state"], "A")


class TestPairSelection(unittest.TestCase):
    """The two flags, and the stem the ledger file is named after. No network."""

    def test_stem_is_one_readable_name_per_pair(self):
        self.assertEqual(end_to_end.stem_for(GLYCINE), "glycine_coronary-artery-disease")
        self.assertEqual(
            end_to_end.stem_for(TMAO),
            "trimethylamine-n-oxide_coronary-artery-disease",
        )

    def test_no_pair_flag_runs_every_pair(self):
        self.assertEqual(len(end_to_end.select_pairs(SAMPLE, [])), len(SAMPLE))

    def test_pair_flag_matches_a_substring_and_never_duplicates(self):
        chosen = end_to_end.select_pairs(
            SAMPLE,
            ["urate", "urate|gout", "GLYCINE"],
        )
        self.assertEqual([key for key, _ in chosen], [URATE, GLYCINE])

    def test_an_unmatched_pair_flag_is_not_a_crash(self):
        self.assertEqual(
            end_to_end.select_pairs(
                SAMPLE,
                ["zzqx-not-a-pair"],
            ),
            [],
        )


class TestSampleContract(unittest.TestCase):
    """1A's frozen contract, read straight off the file the chain starts from."""

    def test_every_pair_carries_both_sides_with_synonyms(self):
        for key, entry in SAMPLE.items():
            self.assertIn("|", key)
            for side in ("metabolite", "disease"):
                self.assertIn(
                    side,
                    entry,
                    key,
                )
                self.assertTrue(entry[side].get("synonyms"), f"{key} {side} has no synonyms")
            self.assertTrue(entry["disease"].get("id", "").startswith("MONDO:"), key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
