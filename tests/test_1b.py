"""1B acceptance tests. Network-live against EpiGraphDB (no key), stdlib unittest.

    python -m unittest tests.test_1b -v          # from the repo root

They check the two things that are easy to get quietly wrong: that a known-true pair
comes back with the published number (urate -> gout, b = 1.3665), and that every way
of coming back with nothing is labelled "empty" with a caveat saying so, never "ok"
with an empty list and never an exception.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ledger
from tools import _common
from tools.epigraphdb import get_mr_outcomes, get_mr_result

SAMPLE_PATH = REPO_ROOT / "data" / "1a_sample.json"
ENVELOPE_KEYS = {"tool", "args", "source", "url", "retrieved_at", "status", "data", "caveats"}
LEDGER_STEM = "_test_1b"

with SAMPLE_PATH.open(encoding="utf-8") as handle:
    SAMPLE = json.load(handle)


def synonyms(pair: str) -> tuple:
    entry = SAMPLE[pair]
    return entry["metabolite"]["synonyms"], entry["disease"]["synonyms"]


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class EnvelopeMixin:
    def assert_envelope(
        self,
        env,
        tool = "get_mr_result",
    ):
        self.assertIsInstance(env, dict)
        self.assertEqual(set(env), ENVELOPE_KEYS)
        self.assertEqual(env["tool"], tool)
        self.assertIn(env["status"], _common.STATUSES)
        self.assertIsInstance(env["data"], dict)
        self.assertIsInstance(env["caveats"], list)
        self.assertTrue(env["caveats"], "every 1B envelope carries the retrieved-not-computed caveat")


class TestSourceDetailsOffline(unittest.TestCase):
    def test_source_properties_and_ci_preserved(self):
        from tools.epigraphdb import _estimate
        raw = {"b": 1.3665, "se": .1068, "nsnp": 4, "ci_low": .5812,
               "ci_upp": 2.1518, "_source": ["MR-EvE-2021-03-10"]}
        result = _estimate({"mr": raw})
        self.assertEqual(result["source_properties"], raw)
        self.assertEqual(result["ci_low"], .5812)
        self.assertEqual(result["nsnp"], 4)
        self.assertEqual(result["source_release"], raw["_source"])

    def test_cypher_failure_falls_back_to_rest(self):
        from unittest.mock import patch
        from tools.epigraphdb import _query_mr
        row = {"exposure": {"id": "x"}, "outcome": {"id": "y"},
               "mr": {"b": .2, "method": "FE IVW"}}
        with patch("tools.epigraphdb._common.get_json",
                   side_effect=[ValueError("offline"), ({"results": [row]}, "https://example/mr")]):
            rows, url = _query_mr("Urate", "Gout")
        self.assertEqual(rows[0]["mr"]["b"], .2)
        self.assertEqual(rows[0]["detail_retrieval"]["status"], "error")

    def test_full_source_rows_keep_method_and_dataset_identity(self):
        from unittest.mock import patch
        from tools.epigraphdb import _query_mr
        row = {"exposure": {"id": "x"}, "outcome": {"id": "y"},
               "mr": {"b": .2, "method": "FE IVW"}}
        extra = {**row, "mr": {"b": .2, "method": "MR Egger", "nsnp": 20}}
        with patch("tools.epigraphdb._common.get_json", return_value=(
                {"results": [row, extra]}, "https://example/cypher")) as transport:
            rows, _ = _query_mr("Urate", "Gout")
        self.assertNotIn("nsnp", rows[0]["mr"])
        self.assertEqual(rows[1]["mr"]["nsnp"], 20)
        self.assertEqual(rows[1]["mr"]["method"], "MR Egger")
        self.assertEqual(transport.call_count, 1)

    def test_wildcard_uses_source_properties_without_outcome_filter(self):
        from unittest.mock import patch
        from tools.epigraphdb import _query_mr
        row = {"exposure": {"id": "x"}, "outcome": {"id": "y"},
               "mr": {"b": .2, "se": .01, "ci_low": -.1, "ci_upp": .4, "nsnp": 4}}
        with patch("tools.epigraphdb._common.get_json", return_value=(
                {"results": [row]}, "cypher")) as transport:
            rows, _ = _query_mr("Urate")
        query = transport.call_args.kwargs["json_body"]["query"]
        self.assertIn("properties(mr)", query)
        self.assertNotIn("outcome.trait =", query)
        self.assertEqual(rows[0]["mr"]["ci_low"], -.1)

    def test_successful_empty_cypher_is_not_requeried(self):
        from unittest.mock import patch
        from tools.epigraphdb import _query_mr
        with patch("tools.epigraphdb._common.get_json", return_value=(
                {"results": []}, "cypher")) as transport:
            rows, _ = _query_mr("Urate", "Gout")
        self.assertEqual(rows, [])
        self.assertEqual(transport.call_count, 1)

    def test_empty_rest_fallback_preserves_failed_source_request(self):
        from unittest.mock import patch
        from tools.epigraphdb import _query_mr, _retrieval_note
        with patch("tools.epigraphdb._common.get_json", side_effect=[
                ValueError("source unavailable"), ({"results": []}, "rest")]):
            rows, _ = _query_mr("Urate", "Gout")
        data, caveats = {}, []
        _retrieval_note(rows, data, caveats)
        self.assertEqual(data["source_requests"][0]["status"], "error")
        self.assertIn("REST fallback", " ".join(caveats))


class TestKnownPair(EnvelopeMixin, unittest.TestCase):
    """urate -> gout is the pair whose published estimate we know by heart."""

    @classmethod
    def setUpClass(cls):
        metabolite, disease = synonyms("urate|gout")
        cls.env = get_mr_result(metabolite, disease)

    def test_status_ok_with_estimates(self):
        self.assert_envelope(self.env)
        self.assertEqual(self.env["status"], "ok")
        self.assertGreaterEqual(self.env["data"]["n_estimates"], 1)
        self.assertEqual(len(self.env["data"]["estimates"]), self.env["data"]["n_estimates"])

    def test_published_ivw_estimate_is_retrieved_verbatim(self):
        hits = [
            estimate for estimate in self.env["data"]["estimates"]
            if estimate["method"] == "FE IVW"
            and abs(estimate["b"] - 1.3665) < 0.01
            and estimate["pval"] < 1e-30
        ]
        self.assertTrue(hits, "expected the ieu-a-789 -> gout FE IVW row, b=1.3665")

    def test_queries_are_recorded(self):
        queries = self.env["data"]["queries"]
        self.assertTrue(queries)
        self.assertEqual(self.env["url"], queries[0])
        for url in queries:
            self.assertTrue("/cypher" in url or "exposure_trait=" in url, url)
        source_requests = self.env["data"]["source_requests"]
        self.assertTrue(source_requests)
        self.assertTrue(all("exposure.trait" in item["query"] for item in source_requests))


class TestSweep(EnvelopeMixin, unittest.TestCase):
    """get_mr_outcomes: the wildcard sweep, sorted and joined to the vocabulary."""

    @classmethod
    def setUpClass(cls):
        cls.env = get_mr_outcomes("Urate", 1e-5)

    def test_sweep_returns_many_sorted_estimates(self):
        self.assert_envelope(self.env, tool="get_mr_outcomes")
        self.assertEqual(self.env["status"], "ok")
        estimates = self.env["data"]["estimates"]
        self.assertGreaterEqual(len(estimates), 20)

        pvals = [estimate["pval"] for estimate in estimates]
        self.assertEqual(
            pvals,
            sorted(pvals),
            "estimates must be sorted by pval ascending",
        )

    def test_every_row_carries_the_outcome_join(self):
        for estimate in self.env["data"]["estimates"]:
            self.assertIn("outcome_cat", estimate)
            self.assertIn("outcome_n", estimate)
            self.assertIn("outcome_ncase", estimate)

    def test_disease_outcomes_are_found_by_case_count_not_by_cat(self):
        """cat is the source's category label, not a disease flag: Gout ieu-a-1054 is
        cat='Disease' and its duplicate ebi-a-GCST001790 is cat=None, so a cat=="Binary"
        filter drops the outcome the demo rests on. outcome_ncase is the real marker."""
        estimates = self.env["data"]["estimates"]
        gout = [row for row in estimates if row["outcome_id"] == "ieu-a-1054"]
        self.assertTrue(gout, "the Urate sweep must reach Gout ieu-a-1054")
        for row in gout:
            self.assertIsNotNone(
                row["outcome_ncase"],
                "a case/control outcome must carry outcome_ncase",
            )
            self.assertNotEqual(
                row["outcome_cat"],
                "Binary",
                "if this ever becomes Binary, re-check the docstring's filter advice",
            )

        with_cases = [row for row in estimates if row["outcome_ncase"] is not None]
        self.assertTrue(with_cases, "the sweep must expose disease-like outcomes")


class TestMatchedButNoRow(EnvelopeMixin, unittest.TestCase):
    """glycine x coronary artery disease: both sides match datasets, MR-EVE has no
    metabolite -> disease row. met-a-468 sits at position 29,674 of the vocabulary, past
    the offset where the REST list endpoint was seen to 500 - only the cypher pull is
    guaranteed to reach it."""

    @classmethod
    def setUpClass(cls):
        metabolite, disease = synonyms("glycine|coronary artery disease")
        cls.env = get_mr_result(metabolite, disease)

    def test_envelope_shape(self):
        self.assert_envelope(self.env)
        self.assertIn(self.env["status"], {"ok", "empty"})

    def test_exposure_match_includes_the_cypher_only_dataset(self):
        ids = [row["id"] for row in self.env["data"]["exposure_matches"]]
        self.assertIn("met-a-468", ids)
        self.assertTrue(self.env["data"]["outcome_matches"])

    def test_estimates_are_numeric_when_present(self):
        for estimate in self.env["data"]["estimates"]:
            for field in ("b", "se", "pval"):
                self.assertTrue(
                    is_number(estimate[field]),
                    f"{field} is {estimate[field]!r}, not a number",
                )


class TestHonestEmpty(EnvelopeMixin, unittest.TestCase):
    """The two ways of finding nothing. Neither is "no effect", neither raises."""

    def test_trait_absent_from_the_snapshot(self):
        metabolite, disease = synonyms("trimethylamine N-oxide|coronary artery disease")
        env = get_mr_result(metabolite, disease)

        self.assert_envelope(env)
        self.assertEqual(env["status"], "empty")
        self.assertEqual(env["data"]["n_estimates"], 0)
        self.assertEqual(env["data"]["exposure_matches"], [])

        caveats = " ".join(env["caveats"]).lower()
        self.assertIn("not evidence of no effect", caveats)
        self.assertIn("no dataset in this snapshot is named", caveats)

    def test_garbage_string_matches_nothing(self):
        env = get_mr_result(["zzqx-not-a-trait"], ["gout"])

        self.assert_envelope(env)
        self.assertEqual(env["status"], "empty")
        self.assertEqual(env["data"]["n_estimates"], 0)
        self.assertEqual(
            env["data"]["queries"],
            [],
            "no request should be sent at all",
        )
        self.assertEqual(
            env["url"],
            "",
            "url is the URL actually sent, and none was",
        )
        self.assertTrue(env["data"]["outcome_matches"], "the disease side still matched")

    def test_a_bare_string_is_not_shredded_into_characters(self):
        """A model calling this tool sends "urate" instead of ["urate"] sooner or later.
        list("urate") would match nothing and the tool would then claim, in the ledger,
        that no dataset is named that - about a pair that has 22 estimates."""
        env = get_mr_result("urate", "gout")

        self.assert_envelope(env)
        self.assertEqual(env["args"]["metabolite_synonyms"], ["urate"])
        self.assertEqual(env["args"]["disease_synonyms"], ["gout"])
        self.assertEqual(env["status"], "ok")
        self.assertGreaterEqual(env["data"]["n_estimates"], 1)


class TestNetworkFailure(EnvelopeMixin, unittest.TestCase):
    """A dead network must produce an error envelope, not a traceback."""

    def test_request_failure_becomes_an_error_envelope(self):
        def boom(*args, **kwargs):
            raise _common.RequestFailed(
                "simulated outage",
                status_code = 503,
                url         = "https://api.epigraphdb.org/mr?exposure_trait=Urate",
            )

        original = _common.get_json
        _common.get_json = boom
        try:
            metabolite, disease = synonyms("urate|gout")
            env = get_mr_result(metabolite, disease)
        finally:
            _common.get_json = original

        self.assert_envelope(env)
        self.assertEqual(env["status"], "error")
        self.assertEqual(env["data"]["error"], "simulated outage")
        self.assertIn("simulated outage", " ".join(env["caveats"]))
        self.assertTrue(env["data"]["exposure_matches"], "partial data survives the failure")
        self.assertIn(
            "no retrieved evidence either way",
            " ".join(env["caveats"]),
            "nothing was retrieved here, so that claim is the true one",
        )

    def test_estimates_retrieved_before_a_failure_are_kept(self):
        """urate|gout genuinely sends two queries ('Urate', then 'Uric acid'). Query 1
        carries all 22 rows including b=1.3665. If query 2 flakes and the tool throws
        those away, the flagship pair drops from State A to State C on a hiccup - missing
        data presented to the audience as an evidence gap."""
        original = _common.get_json
        calls = {"n": 0}

        def fail_after_the_first(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return original(*args, **kwargs)
            raise _common.RequestFailed(
                "simulated outage on the second query",
                status_code = 504,
                url         = "https://api.epigraphdb.org/mr?exposure_trait=Uric+acid",
            )

        _common.get_json = fail_after_the_first
        try:
            metabolite, disease = synonyms("urate|gout")
            env = get_mr_result(metabolite, disease)
        finally:
            _common.get_json = original

        self.assert_envelope(env)
        self.assertGreater(
            calls["n"],
            1,
            "this pair must send more than one query",
        )
        self.assertEqual(env["status"], "error")
        self.assertGreaterEqual(env["data"]["n_estimates"], 1)
        self.assertEqual(len(env["data"]["estimates"]), env["data"]["n_estimates"])

        caveats = " ".join(env["caveats"])
        self.assertIn("already retrieved are kept", caveats)
        self.assertNotIn(
            "no retrieved evidence either way",
            caveats,
            "evidence WAS retrieved; the envelope must not deny it",
        )


class TestLedger(unittest.TestCase):
    """Tools record themselves; the card is auditable because of this line."""

    def tearDown(self):
        ledger.stop()
        target = ledger.path_for(LEDGER_STEM)
        if target.exists():
            target.unlink()

    def test_get_mr_result_records_its_envelope(self):
        ledger.start(LEDGER_STEM)
        metabolite, disease = synonyms("urate|gout")
        env = get_mr_result(metabolite, disease)

        records = ledger.load(LEDGER_STEM)
        self.assertGreaterEqual(len(records), 1)
        self.assertEqual(records[-1]["tool"], "get_mr_result")
        self.assertEqual(records[-1]["status"], env["status"])
        self.assertEqual(records[-1]["data"]["n_estimates"], env["data"]["n_estimates"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
