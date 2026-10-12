"""Unit tests for classify.classify_state. Stdlib unittest, no network, no key.

Every envelope here is hand-built to the shapes documented at the top of
classify.py, so these tests also serve as the written examples the 1C author
writes get_mqtl_instruments / find_outcome_datasets against.

    python -m unittest tests.test_classify -v
"""

import copy
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import classify


def _env(
    tool:    str,
    status:  str,
    data:    dict,
    source:  str  = "test fixture",
    url:     str  = "https://example.invalid/test",
    caveats: list = None,
) -> dict:
    """One shared 8-key envelope, built by hand so no tool code is needed here."""
    return {
        "tool":         tool,
        "args":         {},
        "source":       source,
        "url":          url,
        "retrieved_at": "2026-09-10T12:00:00",
        "status":       status,
        "data":         data,
        "caveats":      list(caveats or []),
    }


def _mr_ok(estimates: list) -> dict:
    return _env(
        tool   = "get_mr_result",
        status = "ok",
        data   = {
            "exposure_matches": [{"id": "ieu-a-789", "trait": "Urate"}],
            "outcome_matches":  [{"id": "ieu-a-1054", "trait": "Gout"}],
            "estimates":        estimates,
            "n_estimates":      len(estimates),
            "queries":          ["https://api.epigraphdb.org/mr?exposure_trait=Urate"],
        },
    )


def _instr_ok(exposures: list) -> dict:
    return _env(
        tool   = "get_mqtl_instruments",
        status = "ok",
        data   = {
            "exposures": exposures,
            "queries":   ["https://api.opengwas.io/api/tophits"],
        },
    )


def _outcomes_ok(datasets: list) -> dict:
    return _env(
        tool   = "find_outcome_datasets",
        status = "ok" if datasets else "empty",
        data   = {
            "datasets": datasets,
            "queries":  ["https://api.opengwas.io/api/gwasinfo"],
        },
    )


URATE_GOUT = {
    "exposure_id":    "ieu-a-789",
    "exposure_trait": "Urate",
    "outcome_id":     "ieu-a-1054",
    "outcome_trait":  "Gout",
    "b":              1.3665,
    "se":             0.1068,
    "pval":           1.79e-37,
    "method":         "FE IVW",
    "nsnp":           26,
}

GLYCINE_PAPER = {
    "pmid":     "31391524",
    "year":     2019,
    "design":   "two-sample MR",
    "exposure": "glycine",
    "outcome":  "coronary heart disease",
    "estimate": {"type": "OR", "value": 0.85, "ci": [0.80, 0.91], "p": 1e-6},
    "method":   "IVW",
    "n_snps":   12,
}


class ClassifyStateTests(unittest.TestCase):

    def test_a_from_mr_env(self):
        result = classify.classify_state(mr_env=_mr_ok([URATE_GOUT]))
        self.assertEqual(result["state"], "A")
        self.assertEqual(result["ledger_keys"], ["get_mr_result"])
        self.assertEqual(result["failed_tools"], [])
        self.assertIn("get_mr_result", result["reason"])

    def test_a_from_lit_env_only(self):
        lit = _env(
            tool   = "get_literature_mr",
            status = "ok",
            data   = {
                "rounds":         1,
                "papers_checked": 18,
                "supporting":     [GLYCINE_PAPER],
                "opposing":       [],
                "unresolved":     [],
            },
        )
        result = classify.classify_state(
            mr_env  = None,
            lit_env = lit,
        )
        self.assertEqual(result["state"], "A")
        self.assertEqual(result["ledger_keys"], ["get_literature_mr"])
        self.assertIn("get_literature_mr", result["reason"])

    def test_a_wins_when_b_conditions_also_hold(self):
        result = classify.classify_state(
            mr_env      = _mr_ok([URATE_GOUT]),
            instr_env   = _instr_ok([{"id": "met-a-468", "gws_hits": 7}]),
            outcome_env = _outcomes_ok([{"id": "ieu-a-7"}]),
        )
        self.assertEqual(result["state"], "A")
        self.assertEqual(
            result["ledger_keys"],
            ["get_mr_result", "get_mqtl_instruments", "find_outcome_datasets"],
        )

    def test_b_from_three_hits_and_one_outcome(self):
        result = classify.classify_state(
            mr_env      = _env(
                tool   = "get_mr_result",
                status = "empty",
                data   = {"estimates": [], "n_estimates": 0},
            ),
            lit_env     = None,
            instr_env   = _instr_ok([{
                "id":       "met-a-468",
                "trait":    "Glycine",
                "platform": "Metabolon",
                "n":        7802,
                "gws_hits": 3,
            }]),
            outcome_env = _outcomes_ok([{"id": "ieu-a-7", "trait": "Coronary heart disease"}]),
        )
        self.assertEqual(result["state"], "B")
        self.assertEqual(result["failed_tools"], [])
        self.assertIn("analysis-ready", result["reason"])

    def test_c_when_hits_below_threshold(self):
        result = classify.classify_state(
            mr_env      = None,
            lit_env     = None,
            instr_env   = _instr_ok([{"id": "met-a-468", "gws_hits": 2}]),
            outcome_env = _outcomes_ok([{"id": "ieu-a-7"}]),
        )
        self.assertEqual(result["state"], "C")
        self.assertIn("best 2", result["reason"])
        self.assertIn("not evidence of no effect", result["reason"])

    def test_c_when_outcomes_empty(self):
        result = classify.classify_state(
            mr_env      = None,
            lit_env     = None,
            instr_env   = _instr_ok([{"id": "met-a-468", "gws_hits": 42}]),
            outcome_env = _outcomes_ok([]),
        )
        self.assertEqual(result["state"], "C")
        self.assertIn("no outcome dataset", result["reason"])
        self.assertEqual(result["failed_tools"], [])

    def test_c_when_everything_is_none(self):
        result = classify.classify_state(
            mr_env      = None,
            lit_env     = None,
            instr_env   = None,
            outcome_env = None,
        )
        self.assertEqual(result["state"], "C")
        self.assertEqual(result["ledger_keys"], [])
        self.assertEqual(result["failed_tools"], [])
        self.assertIn("No tool result reached the classifier", result["reason"])
        self.assertIn("no retrieved MR estimate", result["reason"])

    def test_c_when_mr_and_instruments_error(self):
        mr_error = _env(
            tool   = "get_mr_result",
            status = "error",
            data   = {"error": "HTTP 500 from https://api.epigraphdb.org/mr"},
        )
        instr_error = _env(
            tool   = "get_mqtl_instruments",
            status = "error",
            data   = {"error": "HTTP 401: JWT expired"},
        )
        result = classify.classify_state(
            mr_env      = mr_error,
            lit_env     = None,
            instr_env   = instr_error,
            outcome_env = _outcomes_ok([{"id": "ieu-a-7"}]),
        )
        self.assertEqual(result["state"], "C")
        self.assertEqual(result["failed_tools"], ["get_mr_result", "get_mqtl_instruments"])
        self.assertIn("get_mr_result", result["reason"])
        self.assertIn("get_mqtl_instruments", result["reason"])
        self.assertIn("returned an error envelope", result["reason"])

    def test_error_envelope_data_is_never_read_as_evidence(self):
        poisoned = _env(
            tool   = "get_mr_result",
            status = "error",
            data   = {"error": "timed out", "estimates": [URATE_GOUT]},
        )
        result = classify.classify_state(mr_env=poisoned)
        self.assertEqual(result["state"], "C")
        self.assertEqual(result["failed_tools"], ["get_mr_result"])

    def test_estimate_without_numeric_pval_is_not_a(self):
        result = classify.classify_state(mr_env=_mr_ok([
            {**URATE_GOUT, "pval": None},
            {**URATE_GOUT, "pval": "not reported"},
        ]))
        self.assertEqual(result["state"], "C")
        self.assertIn("2 row(s), none with", result["reason"])

    def test_estimate_without_numeric_se_is_not_a(self):
        result = classify.classify_state(mr_env=_mr_ok([{**URATE_GOUT, "se": None}]))
        self.assertEqual(result["state"], "C")

    def test_paper_without_an_estimate_is_not_a(self):
        lit = _env(
            tool   = "get_literature_mr",
            status = "ok",
            data   = {"supporting": [{**GLYCINE_PAPER, "estimate": None}], "opposing": []},
        )
        result = classify.classify_state(lit_env=lit)
        self.assertEqual(result["state"], "C")
        self.assertIn("1 row(s), none with", result["reason"])

    def test_opposing_paper_with_a_full_estimate_counts_as_a(self):
        lit = _env(
            tool   = "get_literature_mr",
            status = "ok",
            data   = {
                "supporting": [],
                "opposing":   [{**GLYCINE_PAPER, "estimate": {"type": "OR", "value": 1.01,
                                                              "ci": [0.94, 1.09], "p": 0.78}}],
            },
        )
        self.assertEqual(classify.classify_state(lit_env=lit)["state"], "A")

    def test_numeric_strings_survive_a_ledger_round_trip(self):
        stringy = {**URATE_GOUT, "b": "1.3665", "se": "0.1068", "pval": "1.79e-37"}
        self.assertEqual(classify.classify_state(mr_env=_mr_ok([stringy]))["state"], "A")

        result = classify.classify_state(
            instr_env   = _instr_ok([{"id": "met-a-468", "gws_hits": "3"}]),
            outcome_env = _outcomes_ok([{"id": "ieu-a-7"}]),
        )
        self.assertEqual(result["state"], "B")

    def test_empty_mr_is_not_read_as_no_effect(self):
        empty = _env(
            tool   = "get_mr_result",
            status = "empty",
            data   = {"estimates": [], "n_estimates": 0},
        )
        result = classify.classify_state(mr_env=empty)
        self.assertEqual(result["state"], "C")
        self.assertEqual(result["failed_tools"], [])
        self.assertIn("returned no estimate", result["reason"])
        self.assertIn("not evidence of no effect", result["reason"])

    def test_malformed_envelope_is_named_as_a_failure(self):
        result = classify.classify_state(
            mr_env  = _env(
                tool   = "get_mr_result",
                status = "ok",
                data   = None,
            ),
            lit_env = "this is not an envelope",
        )
        self.assertEqual(result["state"], "C")
        self.assertEqual(result["failed_tools"], ["get_mr_result"])
        self.assertIn("malformed envelope", result["reason"])

    def test_return_shape_and_purity(self):
        mr = _mr_ok([{**URATE_GOUT, "pval": None}])
        instr = _instr_ok([{"id": "met-a-468", "gws_hits": 2}])
        outcome = _outcomes_ok([{"id": "ieu-a-7"}])
        before = copy.deepcopy([mr, instr, outcome])

        first = classify.classify_state(
            mr_env      = mr,
            instr_env   = instr,
            outcome_env = outcome,
        )
        second = classify.classify_state(
            mr_env      = mr,
            instr_env   = instr,
            outcome_env = outcome,
        )

        self.assertEqual(set(first), {"state", "reason", "ledger_keys", "failed_tools"})
        self.assertIn(first["state"], ("A", "B", "C"))
        self.assertIsInstance(first["reason"], str)
        self.assertEqual(first, second)
        self.assertEqual([mr, instr, outcome], before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
