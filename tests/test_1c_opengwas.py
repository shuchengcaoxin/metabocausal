"""1C acceptance tests for tools/opengwas.py. Network-live against OpenGWAS, stdlib
unittest, needs OPENGWAS_JWT.

    python -m unittest tests.test_1c_opengwas -v          # from the repo root

They check the four things that are easy to get quietly wrong:

  1. the two glycine platforms are BOTH kept (met-d-Gly is the dataset EpiGraphDB's
     2020 snapshot does not have, so losing it would erase 1C's whole reason to exist);
  2. urate's non-met- datasets survive (a met- prefix filter drops 21 of 22, including
     the largest and including ieu-a-789, which is the exposure behind 1B's flagship
     b = 1.3665);
  3. every way of coming back with nothing is "empty" with a caveat naming the honest
     reason, never "ok" with an empty list and never an exception;
  4. the JWT never reaches an envelope, a URL or the ledger.

Deliberately cheap on credits: the whole suite makes 7 tophits calls.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import classify
import ledger
from tools import _common
from tools.opengwas import JWT_ENV_VAR, find_outcome_datasets, get_mqtl_instruments

SAMPLE_PATH = REPO_ROOT / "data" / "1a_sample.json"
ENVELOPE_KEYS = {"tool", "args", "source", "url", "retrieved_at", "status", "data", "caveats"}
LEDGER_STEM = "_test_1c"

with SAMPLE_PATH.open(encoding="utf-8") as handle:
    SAMPLE = json.load(handle)


def synonyms(pair: str) -> tuple:
    entry = SAMPLE[pair]
    return entry["metabolite"]["synonyms"], entry["disease"]["synonyms"]


def token() -> str:
    """Only ever used to prove the value is ABSENT from something. Never printed."""
    _common.load_env()
    return (os.environ.get(JWT_ENV_VAR) or "").strip()


class EnvelopeMixin:
    def assert_envelope(
        self,
        env,
        tool,
    ):
        self.assertIsInstance(env, dict)
        self.assertEqual(set(env), ENVELOPE_KEYS)
        self.assertEqual(env["tool"], tool)
        self.assertIn(env["status"], _common.STATUSES)
        self.assertIsInstance(env["data"], dict)
        self.assertIsInstance(env["caveats"], list)
        self.assertTrue(env["caveats"], "every 1C envelope carries the retrieved-not-computed caveat")
        self.assert_no_secret(env)

    def assert_no_secret(self, env):
        """assertFalse, not assertIn: a failing assertIn would print the haystack, and
        the haystack is the thing that must never be printed."""
        blob = json.dumps(
            env,
            ensure_ascii = False,
            default      = str,
        )
        secret = token()
        self.assertFalse(
            "Bearer" in blob,
            "no envelope may carry an Authorization header value",
        )
        self.assertFalse(
            secret and secret in blob,
            "the JWT must never appear anywhere in an envelope",
        )
        for url in [env.get("url"), *env.get("data", {}).get("queries", [])]:
            text = str(url or "")
            self.assertFalse(
                "Bearer" in text or "jwt" in text.lower(),
                "no URL may carry a token",
            )
            self.assertFalse(
                secret and secret in text,
                "no URL may carry a token",
            )


@unittest.skipUnless(token(), f"{JWT_ENV_VAR} absent; the live 1C tests cannot run")
class TestGlycineInstruments(EnvelopeMixin, unittest.TestCase):
    """glycine is the pair that justifies 1C: two datasets on two platforms, and the
    bigger one (met-d-Gly, n=114,972) does not exist in the EpiGraphDB snapshot 1B
    reads. 2 tophits calls."""

    @classmethod
    def setUpClass(cls):
        metabolite, _ = synonyms("glycine|coronary artery disease")
        cls.env = get_mqtl_instruments(
            metabolite,
            max_datasets = 6,
        )
        cls.by_id = {row["id"]: row for row in cls.env["data"]["exposures"]}

    def test_status_ok_with_both_platforms(self):
        self.assert_envelope(self.env, "get_mqtl_instruments")
        self.assertEqual(self.env["status"], "ok")
        self.assertIn("met-d-Gly", self.by_id)
        self.assertIn("met-a-468", self.by_id)
        self.assertEqual(self.env["data"]["n_exposures"], len(self.env["data"]["exposures"]))

    def test_met_d_gly_carries_the_instruments(self):
        gly = self.by_id["met-d-Gly"]
        self.assertGreaterEqual(gly["gws_hits"], 40)
        self.assertEqual(gly["weak_instruments"], 0)
        self.assertGreater(gly["min_f"], 10)
        self.assertGreater(gly["max_f"], gly["min_f"])

    def test_met_a_468_finds_the_cps1_locus(self):
        """The one clumped hit of the 2014 Metabolon glycine GWAS is rs715 at
        chr2:211543055 - the CPS1 locus, the known glycine effector gene. If this ever
        moves, the instrument set changed and 1D's gene story changes with it."""
        shin = self.by_id["met-a-468"]
        self.assertGreaterEqual(shin["gws_hits"], 1)
        self.assertIn("rs715", [hit["rsid"] for hit in shin["example_hits"]])

    def test_every_exposure_reports_platform_unit_and_size(self):
        for exposure in self.env["data"]["exposures"]:
            for field in ("platform", "unit", "sample_size", "population", "year", "build"):
                self.assertIn(field, exposure)
            self.assertIsInstance(exposure["sample_size"], int)
            self.assertIsInstance(exposure["gws_hits"], int)
        self.assertIn("NMR", self.by_id["met-d-Gly"]["platform"])
        self.assertIn("mass spectrometry", self.by_id["met-a-468"]["platform"])
        self.assertEqual(self.by_id["met-a-468"]["unit"], "log10 units")
        self.assertIsNone(
            self.by_id["met-d-Gly"]["unit"],
            'gwasinfo writes the literal "NA" here, which means absent, not a unit',
        )

    def test_the_two_platforms_are_never_merged(self):
        sizes = {row["sample_size"] for row in self.env["data"]["exposures"]}
        self.assertEqual(len(sizes), len(self.env["data"]["exposures"]))
        caveats = " ".join(self.env["caveats"])
        self.assertIn("not comparable", caveats)
        self.assertIn("inferred", caveats.lower())
        self.assertIn("clump", caveats.lower())

    def test_the_envelope_satisfies_the_classify_contract(self):
        """classify.py reads exactly data['exposures'][i]['gws_hits'] and
        data['datasets']. Glycine has no MR-EVE row, so this pair is State B."""
        outcome_env = find_outcome_datasets(
            synonyms("glycine|coronary artery disease")[1],
            top_n = 3,
        )
        result = classify.classify_state(
            mr_env      = None,
            lit_env     = None,
            instr_env   = self.env,
            outcome_env = outcome_env,
        )
        self.assertEqual(result["state"], "B")
        self.assertEqual(result["failed_tools"], [])
        self.assertEqual(
            result["ledger_keys"],
            ["get_mqtl_instruments", "find_outcome_datasets"],
        )


@unittest.skipUnless(token(), f"{JWT_ENV_VAR} absent; the live 1C tests cannot run")
class TestUrateIsNotFilteredByIdPrefix(EnvelopeMixin, unittest.TestCase):
    """The trap 1B learned the hard way. Urate matches 22 gwasinfo datasets and exactly
    ONE is met-* (met-a-345, n=7,819). Filtering on the id prefix would drop the other
    21 - including ieu-b-5137 at n=440,466 and ieu-a-789, the exposure behind the
    published urate -> gout estimate. 3 tophits calls."""

    @classmethod
    def setUpClass(cls):
        metabolite, _ = synonyms("urate|gout")
        cls.env = get_mqtl_instruments(
            metabolite,
            max_datasets = 3,
        )
        cls.ids = [row["id"] for row in cls.env["data"]["exposures"]]

    def test_non_met_datasets_are_kept(self):
        self.assert_envelope(self.env, "get_mqtl_instruments")
        self.assertEqual(self.env["status"], "ok")
        self.assertGreaterEqual(self.env["data"]["matched_datasets"], 20)
        self.assertTrue(
            [row for row in self.ids if not row.startswith("met-")],
            "a met- prefix filter would have emptied this result",
        )
        self.assertIn("ieu-b-5137", self.ids)

    def test_kept_datasets_are_the_largest_by_sample_size(self):
        sizes = [row["sample_size"] for row in self.env["data"]["exposures"]]
        self.assertEqual(
            sizes,
            sorted(sizes, reverse=True),
            "exposures must be ordered by sample size descending",
        )
        self.assertGreaterEqual(sizes[0], 400000)

    def test_a_non_met_dataset_gets_no_invented_platform(self):
        """Platform is inferred from the batch prefix and there is no batch to infer
        from outside met-a/b/c/d, so it must be null rather than guessed."""
        for exposure in self.env["data"]["exposures"]:
            if not exposure["id"].startswith("met-"):
                self.assertIsNone(exposure["platform"])

    def test_the_cap_is_stated_not_silent(self):
        caveats = " ".join(self.env["caveats"])
        self.assertIn("Capped", caveats)
        self.assertIn(
            "ieu-a-789",
            caveats,
            "the dataset not queried must be named",
        )
        self.assertIn("max_datasets", caveats)

    def test_f_statistics_are_computed_from_beta_and_se(self):
        for exposure in self.env["data"]["exposures"]:
            for hit in exposure["example_hits"]:
                if hit["se"] and hit["beta"] is not None:
                    self.assertAlmostEqual(
                        hit["f"],
                        (hit["beta"] / hit["se"]) ** 2,
                        places = 6,
                    )
            self.assertLessEqual(exposure["weak_instruments"], exposure["gws_hits"])


@unittest.skipUnless(token(), f"{JWT_ENV_VAR} absent; the live 1C tests cannot run")
class TestHonestEmpty(EnvelopeMixin, unittest.TestCase):
    """The ways of finding nothing. None is "no effect", none raises, none costs a
    tophits call - no request is sent when nothing matched."""

    def test_tmao_is_absent_from_opengwas_entirely(self):
        """Discovered, not assumed: none of TMAO's 18 synonyms names any of the 50,056
        gwasinfo traits, in either vocabulary. The panels cover a few hundred
        metabolites; TMAO is not one of them. So the honest answer is "not measured in
        this release", and it must not read as "no genetic basis"."""
        metabolite, _ = synonyms("trimethylamine N-oxide|coronary artery disease")
        env = get_mqtl_instruments(metabolite)

        self.assert_envelope(env, "get_mqtl_instruments")
        self.assertEqual(env["status"], "empty")
        self.assertEqual(env["data"]["matched_datasets"], 0)
        self.assertEqual(env["data"]["n_exposures"], 0)
        self.assertEqual(
            env["data"]["queries"],
            [],
            "no dataset matched, so no tophits call may be made",
        )
        self.assertEqual(
            env["url"],
            "",
            "url is the URL actually sent, and none was",
        )

        caveats = " ".join(env["caveats"]).lower()
        self.assertIn("no dataset in this opengwas release is named", caveats)
        self.assertIn("not evidence of no effect", caveats)
        self.assertIn("not evidence of no genetic basis", caveats)

    def test_the_disease_side_of_the_same_pair_still_matches(self):
        """The contrast that makes the TMAO caveat honest: the pair is not unknown, the
        metabolite is. The outcome half is fully populated."""
        _, disease = synonyms("trimethylamine N-oxide|coronary artery disease")
        env = find_outcome_datasets(disease)

        self.assert_envelope(env, "find_outcome_datasets")
        self.assertEqual(env["status"], "ok")
        self.assertGreaterEqual(env["data"]["n_datasets"], 1)

    def test_garbage_metabolite_synonyms_match_nothing(self):
        env = get_mqtl_instruments(["zzqx-not-a-metabolite", "definitely not a trait"])

        self.assert_envelope(env, "get_mqtl_instruments")
        self.assertEqual(env["status"], "empty")
        self.assertEqual(env["data"]["queries"], [])
        self.assertIn(
            "no dataset in this opengwas release is named",
            " ".join(env["caveats"]).lower(),
        )

    def test_garbage_disease_synonyms_match_nothing(self):
        env = find_outcome_datasets(["zzqx-not-a-disease"])

        self.assert_envelope(env, "find_outcome_datasets")
        self.assertEqual(env["status"], "empty")
        self.assertEqual(env["data"]["datasets"], [])
        self.assertEqual(env["data"]["n_datasets"], 0)
        self.assertIn(
            "no outcome dataset in this opengwas release is named",
            " ".join(env["caveats"]).lower(),
        )

    def test_a_bare_string_is_not_shredded_into_characters(self):
        """A model sends "glycine" instead of ["glycine"] sooner or later. list("glycine")
        would match nothing and the tool would then claim, in the ledger, that OpenGWAS
        has no glycine dataset - about a metabolite with two."""
        env = find_outcome_datasets("gout")

        self.assert_envelope(env, "find_outcome_datasets")
        self.assertEqual(env["args"]["disease_synonyms"], ["gout"])
        self.assertEqual(env["status"], "ok")
        self.assertGreaterEqual(env["data"]["n_datasets"], 1)


class TestOutcomeDatasets(EnvelopeMixin, unittest.TestCase):
    """find_outcome_datasets reads the cached index, so it sends nothing, costs no
    credits and needs no token - hence no skipUnless on this class."""

    @classmethod
    def setUpClass(cls):
        _, disease = synonyms("glycine|coronary artery disease")
        cls.env = find_outcome_datasets(
            disease,
            top_n = 3,
        )

    def test_status_ok_and_sorted_by_sample_size(self):
        self.assert_envelope(self.env, "find_outcome_datasets")
        self.assertEqual(self.env["status"], "ok")
        datasets = self.env["data"]["datasets"]
        self.assertGreaterEqual(len(datasets), 1)
        self.assertEqual(self.env["data"]["n_datasets"], len(datasets))

        sizes = [row["sample_size"] for row in datasets if row["sample_size"] is not None]
        self.assertEqual(
            sizes,
            sorted(sizes, reverse=True),
            "outcome datasets must be ordered by sample size descending",
        )
        self.assertGreaterEqual(sizes[0], 500000)

    def test_no_request_is_sent(self):
        self.assertEqual(self.env["data"]["queries"], [])
        self.assertEqual(self.env["url"], "")

    def test_case_counts_are_coerced_without_crashing(self):
        """gwasinfo writes ints here, other IEU surfaces write "2115.0", and finn-b
        writes case and control counts with no sample_size at all. None of it may raise
        and none of it may become a string in the envelope."""
        for dataset in self.env["data"]["datasets"]:
            for field in ("sample_size", "ncase", "ncontrol", "year"):
                value = dataset[field]
                self.assertTrue(
                    value is None or isinstance(value, int),
                    f"{dataset['id']}.{field} is {type(value).__name__}, not int or None",
                )

    def test_every_dataset_reports_its_population(self):
        for dataset in self.env["data"]["datasets"]:
            self.assertIn("population", dataset)
            self.assertIn("build", dataset)
        if any(row["population"] is None for row in self.env["data"]["datasets"]):
            self.assertIn(
                "records no population",
                " ".join(self.env["caveats"]),
                "a null population must be explained, not left silent",
            )

    def test_the_cap_names_what_it_dropped(self):
        self.assertGreaterEqual(self.env["data"]["n_matched_before_cap"], 4)
        caveats = " ".join(self.env["caveats"])
        self.assertIn("Capped", caveats)
        self.assertIn("top_n", caveats)
        self.assertIn(
            "bbj-a-159",
            caveats,
            "the dropped East Asian GWAS must be named",
        )

    def test_met_datasets_are_never_offered_as_outcomes(self):
        for dataset in self.env["data"]["datasets"]:
            self.assertFalse(dataset["id"].startswith("met-"))

    def test_the_ranking_rule_is_stated_and_is_not_pure_sample_size(self):
        self.assertIn("Ranking:", " ".join(self.env["caveats"]))

    def test_a_dataset_with_no_recorded_size_never_outranks_one_that_has_one(self):
        """finn-b-M13_GOUT carries 3,576 cases and no sample_size at all. Ranking it by a
        missing number would put it above the 484,598-participant GWAS, or below a dataset
        a hundredth its size, depending on which way the null sorted."""
        env = find_outcome_datasets(
            synonyms("urate|gout")[1],
            top_n = 4,
        )

        self.assert_envelope(env, "find_outcome_datasets")
        ids = [row["id"] for row in env["data"]["datasets"]]
        sizes = [row["sample_size"] for row in env["data"]["datasets"]]
        self.assertEqual(ids[-1], "finn-b-M13_GOUT")
        self.assertIsNone(sizes[-1])
        self.assertTrue(all(size is not None for size in sizes[:-1]))
        self.assertEqual(
            sizes[:-1],
            sorted(sizes[:-1], reverse=True),
        )
        self.assertEqual(env["data"]["datasets"][-1]["ncase"], 3576)

    def test_the_same_study_deposited_twice_is_named_as_such(self):
        """ieu-a-1054 and ebi-a-GCST001790 are the same 2013 gout GWAS (n=69,374,
        2,115 cases) under two ids. A card that counts them as two studies is wrong."""
        env = find_outcome_datasets(
            synonyms("urate|gout")[1],
            top_n = 4,
        )
        caveats = " ".join(env["caveats"])
        self.assertIn("SAME study deposited under more than one id", caveats)
        self.assertIn("ieu-a-1054", caveats)
        self.assertIn("ebi-a-GCST001790", caveats)

    def test_type_2_diabetes_is_where_the_cap_bites_hardest(self):
        """24 matched datasets under three trait spellings, 3 returned. If that cap were
        silent, a card could claim the largest T2D GWAS is ieu-a-24."""
        _, disease = synonyms("isoleucine|type 2 diabetes")
        env = find_outcome_datasets(
            disease,
            top_n = 3,
        )

        self.assert_envelope(env, "find_outcome_datasets")
        self.assertEqual(env["status"], "ok")
        self.assertGreaterEqual(env["data"]["n_matched_before_cap"], 20)
        self.assertEqual(env["data"]["n_datasets"], 3)
        caveats = " ".join(env["caveats"])
        self.assertIn("Capped", caveats)
        self.assertIn("different trait spellings", caveats)


class TestMissingToken(EnvelopeMixin, unittest.TestCase):
    """No token must be a clean error envelope naming the missing variable - and the
    caveat must not leak anything that looks like a token."""

    def test_absent_jwt_is_an_error_envelope(self):
        original_load_env = _common.load_env
        saved = os.environ.pop(JWT_ENV_VAR, None)
        _common.load_env = lambda: None                # else .env would put it straight back
        try:
            env = get_mqtl_instruments(["glycine"])
        finally:
            _common.load_env = original_load_env
            if saved is not None:
                os.environ[JWT_ENV_VAR] = saved

        self.assertIsInstance(env, dict)
        self.assertEqual(set(env), ENVELOPE_KEYS)
        self.assertEqual(env["tool"], "get_mqtl_instruments")
        self.assertEqual(env["status"], "error")
        self.assertEqual(env["url"], "")
        self.assertEqual(env["data"]["queries"], [])
        self.assertIn(JWT_ENV_VAR, env["data"]["error"])

        caveats = " ".join(env["caveats"])
        self.assertIn(JWT_ENV_VAR, caveats)
        self.assertIn("missing credential", caveats)
        for needle in ("Bearer", "eyJ", "Authorization"):
            self.assertFalse(
                needle in caveats,
                f"a caveat must never contain {needle!r}",
            )
        self.assert_no_secret(env)

    def test_outcome_search_needs_no_token_at_all(self):
        """find_outcome_datasets reads the cached index. A dead token must not take the
        outcome half of the card down with it."""
        original_load_env = _common.load_env
        saved = os.environ.pop(JWT_ENV_VAR, None)
        _common.load_env = lambda: None
        try:
            env = find_outcome_datasets(["gout"])
        finally:
            _common.load_env = original_load_env
            if saved is not None:
                os.environ[JWT_ENV_VAR] = saved

        self.assertEqual(set(env), ENVELOPE_KEYS)
        self.assertEqual(env["status"], "ok")
        self.assertGreaterEqual(env["data"]["n_datasets"], 1)


@unittest.skipUnless(token(), f"{JWT_ENV_VAR} absent; the live 1C tests cannot run")
class TestNetworkFailure(EnvelopeMixin, unittest.TestCase):
    """A dead network must produce an error envelope, not a traceback."""

    def test_request_failure_becomes_an_error_envelope(self):
        def boom(*args, **kwargs):
            raise _common.RequestFailed(
                "simulated outage",
                status_code = 503,
                url         = "https://api.opengwas.io/api/tophits",
            )

        original = _common.get_json
        _common.get_json = boom
        try:
            metabolite, _ = synonyms("glycine|coronary artery disease")
            env = get_mqtl_instruments(metabolite)
        finally:
            _common.get_json = original

        self.assert_envelope(env, "get_mqtl_instruments")
        self.assertEqual(env["status"], "error")
        self.assertEqual(env["data"]["error"], "simulated outage")
        self.assertIn("simulated outage", " ".join(env["caveats"]))
        self.assertEqual(env["data"]["exposures"], [])
        self.assertIn(
            "no retrieved evidence either way",
            " ".join(env["caveats"]),
            "nothing was retrieved here, so that claim is the true one",
        )

    def test_exposures_retrieved_before_a_failure_are_kept(self):
        """glycine sends two tophits calls. If call 2 flakes and the tool throws call 1
        away, a State B pair drops to State C on a hiccup - a network wobble presented to
        the audience as an evidence gap. 1 real tophits call."""
        original = _common.get_json
        calls = {"n": 0}

        def fail_after_the_first(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return original(*args, **kwargs)
            raise _common.RequestFailed(
                "simulated outage on the second dataset",
                status_code = 504,
                url         = "https://api.opengwas.io/api/tophits",
            )

        _common.get_json = fail_after_the_first
        try:
            metabolite, _ = synonyms("glycine|coronary artery disease")
            env = get_mqtl_instruments(metabolite)
        finally:
            _common.get_json = original

        self.assert_envelope(env, "get_mqtl_instruments")
        self.assertGreater(
            calls["n"],
            1,
            "glycine must query more than one dataset",
        )
        self.assertEqual(env["status"], "error")
        self.assertEqual(env["data"]["n_exposures"], 1)
        self.assertEqual(len(env["data"]["exposures"]), 1)

        caveats = " ".join(env["caveats"])
        self.assertIn("already retrieved are kept", caveats)
        self.assertNotIn(
            "no retrieved evidence either way",
            caveats,
            "evidence WAS retrieved; the envelope must not deny it",
        )


@unittest.skipUnless(token(), f"{JWT_ENV_VAR} absent; the live 1C tests cannot run")
class TestLedger(unittest.TestCase):
    """Tools record themselves; the card is auditable because of this line. 1 tophits
    call (max_datasets=1)."""

    def tearDown(self):
        ledger.stop()
        target = ledger.path_for(LEDGER_STEM)
        if target.exists():
            target.unlink()

    def test_both_tools_record_their_envelopes(self):
        ledger.start(LEDGER_STEM)
        instruments = get_mqtl_instruments(
            ["glycine"],
            max_datasets = 1,
        )
        outcomes = find_outcome_datasets(
            ["gout"],
            top_n = 1,
        )

        records = ledger.load(LEDGER_STEM)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["tool"], "get_mqtl_instruments")
        self.assertEqual(records[1]["tool"], "find_outcome_datasets")
        self.assertEqual(records[0]["status"], instruments["status"])
        self.assertEqual(records[1]["status"], outcomes["status"])
        self.assertEqual(
            records[0]["data"]["n_exposures"],
            instruments["data"]["n_exposures"],
        )

        secret = token()
        for record in records:
            self.assertEqual(set(record), ENVELOPE_KEYS)
            blob = json.dumps(
                record,
                ensure_ascii = False,
                default      = str,
            )
            self.assertFalse("Bearer" in blob, "the ledger must never carry a header value")
            self.assertFalse(
                secret and secret in blob,
                "the ledger must never carry the JWT",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
