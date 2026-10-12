"""pipeline.run_pair's contract without a single request. Fully offline.

    python -m unittest tests.test_pipeline_offline -v      # from the repo root

tests/test_pipeline.py covers the same function against the live databases and spends
OpenGWAS credits doing it. This file covers what is about the plumbing rather than the
biology, and what a live run would never reach - the failure paths, the degradations and
the two new tool modules' refusals:

  two runs at once          slack_bolt dispatches listeners on a thread pool (App
                            defaults to five listener workers, Socket Mode to ten
                            message workers), so two mentions can be inside run_pair
                            together. While ledger.py kept the active run in a module
                            global, the second start() repointed it and the first run's
                            remaining envelopes were appended to the SECOND pair's file
                            - and both cards printed "every number traceable - N ledger
                            entries" with an N that was nobody's. That footer is the
                            one promise this project makes
  the ledger stem           a mention must not be able to truncate a frozen demo
                            ledger, and a 120-character trait name must not build a
                            path past the 260-character limit this Windows box still
                            enforces
  "Never raises"            run_pair's docstring promises 1F it can call this without
                            a try. A tool that breaks its own contract must come back
                            as a State C result naming the stage, not as an exception
  the resolution ladder     sample -> live resolve_ids -> raw string. Each rung must be
                            reached only when the one above it missed, and the rung that
                            was used must be named in `notes`. A silent raw-string
                            degradation is the failure this project is built against
  the gene stage            it runs after the verdict and must never move it: a state C
                            pair is not given a gene list, and a gene stage that raises
                            leaves an A an A with a note rather than demoting it
  trials.py's id and year   an NCT id is never reconstructed and a year is never
                            inferred. A registry record with no date must come back
                            undated and be counted, not be given a plausible year

Every tool is stubbed here - including the live 1A resolver, which a name outside the
frozen sample would otherwise send to OLS4 - so nothing opens a socket and no ledger of a
real pair is touched: the stems these tests write are prefixed and deleted afterwards.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ledger
import pipeline
from tools import _common, _evidence, trials
from unittest.mock import patch

PREFIX = "offlinetest"

RESULT_KEYS = {
    "state",
    "reason",
    "metabolite",
    "disease",
    "envelopes",
    "coloc_summary",
    "effector_genes",
    "ledger_path",
    "n_ledger_entries",
    "notes",
}


def envelope(
    tool: str,
    mark: str,
) -> dict:
    """The eight shared keys, with the run's own marker in data so a line that landed in
    the wrong file is visible rather than merely miscounted."""
    return {
        "tool":         tool,
        "args":         {"mark": mark},
        "source":       "synthetic",
        "url":          "https://example.invalid/synthetic",
        "retrieved_at": "2026-09-10T00:00:00+00:00",
        "status":       "empty",
        "data":         {"mark": mark, "estimates": [], "exposures": [], "datasets": []},
        "caveats":      ["Retrieved, not computed here."],
    }


def stub(
    tool:  str,
    pause: float = 0.0,
):
    """Stand in for one 1B/1C tool: record an envelope the way the real tool does, wait
    long enough for the other thread to be inside its own run, and return."""
    def call(synonyms, *args, **kwargs):
        mark = str((list(synonyms) or [""])[0])
        env = envelope(tool, mark)
        if pause:
            time.sleep(pause)
        ledger.record(env)
        return env
    return call


def ids_envelope(
    chebi:      str = "",
    ontology_id: str = "",
    synonyms:   tuple = (),
) -> dict:
    """What a live `resolve_ids` call would have returned, without the two requests it
    would have sent. Both legs carry the same synonym list, which is enough: the tests
    below check which rung of the resolution ladder was used, not what OLS4 says."""
    leg = {
        "input":     "stub",
        "label":     "stub label",
        "synonyms":  list(synonyms),
        "status":    "ok" if (chebi or ontology_id) else "empty",
        "ambiguous": False,
    }
    return {
        "tool":         "resolve_ids",
        "args":         {},
        "source":       "synthetic",
        "url":          "https://example.invalid/ols4",
        "retrieved_at": "2026-09-11T00:00:00+00:00",
        "status":       "ok",
        "data":         {
            "metabolite": {**leg, "chebi": chebi},
            "disease":    {**leg, "id": ontology_id, "entity_type": "disease"},
            "queries":    [],
        },
        "caveats":      [],
    }


def resolve_stub(envelope: dict):
    """Stand in for tools.ids.resolve_ids: record the envelope the way the real one does
    and hand back the same shape, without opening a socket."""
    def call(metabolite, disease):
        ledger.record(envelope)
        return envelope
    return call


class StubbedToolsMixin:
    """Swap the tool functions pipeline imported, and put them back afterwards.

    The 1A resolver is stubbed too: every name these tests use is outside the frozen
    sample, so an unstubbed run_pair would go to OLS4 and PubChem for real and this file
    would stop being offline."""

    PAUSE = 0.0
    IDS_ENVELOPE = None

    def stub_tools(self):
        # get_colocalisation is stubbed with the others, and it has to be: it is the one
        # arm that runs on every pair by default and would otherwise reach Open Targets
        # for real, which would make this file's first promise - fully offline - false.
        for name, tool in (
            ("get_mr_result",        "get_mr_result"),
            ("get_mqtl_instruments", "get_mqtl_instruments"),
            ("find_outcome_datasets", "find_outcome_datasets"),
            ("get_colocalisation",   "get_colocalisation"),
        ):
            self.addCleanup(setattr, pipeline, name, getattr(pipeline, name))
            setattr(pipeline, name, stub(tool, self.PAUSE))

        self.addCleanup(setattr, pipeline, "resolve_ids", pipeline.resolve_ids)
        pipeline.resolve_ids = resolve_stub(self.IDS_ENVELOPE or ids_envelope())

    def stub_gene_stage(self, atlas=None, dossier=None):
        """Swap the 1D atlas and the gene-side dossier runner."""
        self.addCleanup(setattr, pipeline, "get_effector_genes_atlas",
                        pipeline.get_effector_genes_atlas)
        self.addCleanup(setattr, pipeline, "_run_dossier", pipeline._run_dossier)
        pipeline.get_effector_genes_atlas = atlas or (lambda *a, **k: envelope("get_effector_genes_atlas", "atlas"))
        pipeline._run_dossier = dossier or (lambda *a, **k: {})

    def forget_ledger(self, stem):
        target = ledger.path_for(stem)
        self.addCleanup(lambda: target.exists() and target.unlink())


class TestTwoRunsAtOnce(StubbedToolsMixin, unittest.TestCase):

    PAUSE = 0.05

    def setUp(self):
        self.stub_tools()

    def run_pair(self, name):
        return pipeline.run_pair(
            f"{name}-metabolite",
            f"{name}-disease",
            stem_prefix = PREFIX,
        )

    def test_each_concurrent_run_keeps_its_own_ledger(self):
        names = ("alpha", "beta")
        for name in names:
            self.forget_ledger(pipeline.stem_for(
                f"{name}-metabolite",
                f"{name}-disease",
                PREFIX,
            ))

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.run_pair, names))

        for name, result in zip(names, results):
            with self.subTest(name=name):
                stem = Path(result["ledger_path"]).name.replace(ledger.SUFFIX, "")
                lines = ledger.load(stem)
                self.assertEqual(
                    len(lines),
                    5,
                    f"{stem} must hold this run's resolver line plus its four tool "
                    f"envelopes, and nobody else's",
                )
                self.assertEqual(result["n_ledger_entries"], 5)
                self.assertEqual(
                    [line["tool"] for line in lines],
                    ["resolve_ids", "get_mr_result", "get_mqtl_instruments",
                     "find_outcome_datasets", "get_colocalisation"],
                )
                marks = {line["data"]["mark"] for line in lines if "mark" in line["data"]}
                self.assertEqual(
                    marks,
                    {f"{name}-metabolite", f"{name}-disease"},
                    f"{stem} carries a line from the other run: {marks}",
                )

    def test_the_two_runs_did_not_share_one_file(self):
        stems = {
            pipeline.stem_for(
                f"{name}-metabolite",
                f"{name}-disease",
                PREFIX,
            )
            for name in ("alpha", "beta")
        }
        self.assertEqual(len(stems), 2, stems)


class TestNeverRaises(StubbedToolsMixin, unittest.TestCase):

    def setUp(self):
        self.stub_tools()

    def test_a_tool_that_breaks_its_contract_becomes_a_state_c_result(self):
        def explode(*args, **kwargs):
            raise RuntimeError("a tool must never do this, but run_pair must survive it")

        pipeline.get_mqtl_instruments = explode
        stem = pipeline.stem_for(
            "boom-metabolite",
            "boom-disease",
            PREFIX,
        )
        self.forget_ledger(stem)

        result = pipeline.run_pair(
            "boom-metabolite",
            "boom-disease",
            stem_prefix = PREFIX,
        )

        self.assertEqual(set(result), RESULT_KEYS)
        self.assertEqual(result["state"], "C")
        self.assertIn("not evidence of no effect", result["reason"])
        failure = [note for note in result["notes"] if "did not finish" in note]
        self.assertTrue(failure, result["notes"])
        self.assertIn("get_mqtl_instruments", failure[0])
        self.assertIn("RuntimeError", failure[0])

    def test_what_was_retrieved_before_the_failure_is_still_returned(self):
        def explode(*args, **kwargs):
            raise RuntimeError("failed after the first tool")

        pipeline.find_outcome_datasets = explode
        stem = pipeline.stem_for(
            "partial-metabolite",
            "partial-disease",
            PREFIX,
        )
        self.forget_ledger(stem)

        result = pipeline.run_pair(
            "partial-metabolite",
            "partial-disease",
            stem_prefix = PREFIX,
        )

        self.assertIn("mr", result["envelopes"])
        self.assertIn("instruments", result["envelopes"])
        self.assertNotIn("outcomes", result["envelopes"])
        # The resolver line plus the two tools that ran before the one that exploded.
        self.assertEqual(result["n_ledger_entries"], 3)
        self.assertIsNone(ledger.active_stem(), "the run must be closed either way")


class TestStemNamespaceAndLength(unittest.TestCase):
    """No network, no ledger written: stem_for is a string function."""

    def test_a_prefix_keeps_a_mention_off_the_frozen_demo_ledgers(self):
        self.assertEqual(
            pipeline.stem_for(
                "urate",
                "gout",
                "slack",
            ),
            "slack_urate_gout",
        )
        self.assertEqual(pipeline.stem_for("urate", "gout"), "urate_gout")

    def test_two_names_at_the_documented_limit_stay_inside_max_path(self):
        long_name = "a" * 120
        stem = pipeline.stem_for(
            long_name,
            long_name.replace("a", "b"),
            "slack",
        )
        full = ledger.path_for(stem)
        self.assertLess(
            len(str(full)),
            260,
            f"{len(str(full))} characters is past this machine's MAX_PATH",
        )
        self.assertTrue(full.name.startswith("slack_aaa"), full.name)

    def test_two_long_names_that_share_a_prefix_stay_distinct(self):
        head = "chronic obstructive pulmonary disease with acute exacerbation "
        first = pipeline.stem_for(
            "urate",
            head + "one",
        )
        second = pipeline.stem_for(
            "urate",
            head + "two",
        )
        self.assertNotEqual(first, second)

    def test_a_short_name_is_left_exactly_as_it_was(self):
        self.assertEqual(
            pipeline.stem_for("trimethylamine N-oxide", "coronary artery disease"),
            "trimethylamine-n-oxide_coronary-artery-disease",
        )
        self.assertEqual(pipeline.stem_for("../etc", "passwd"), "etc_passwd")


def analysable_stub(tool: str):
    """A 1C stub whose envelope is enough for classify_state to say B: one exposure with
    four genome-wide significant hits and one outcome dataset."""
    def call(synonyms, *args, **kwargs):
        env = envelope(tool, str((list(synonyms) or [""])[0]))
        env["status"] = "ok"
        env["data"]["exposures"] = [{"id": "met-a-000", "gws_hits": 4}]
        env["data"]["datasets"] = [{"id": "ieu-a-000"}]
        ledger.record(env)
        return env
    return call


def atlas_envelope(*symbols) -> dict:
    """A 1D atlas envelope naming `symbols`, ranked in the order given."""
    env = envelope("get_effector_genes_atlas", "atlas")
    env["status"] = "ok" if symbols else "empty"
    env["data"] = {
        "matched_on":   "metabolite_name",
        "matched_term": "stub",
        "n_genes":      len(symbols),
        "genes":        [
            {
                "gene_symbol": symbol,
                "gene_source": ["author_prioritized"],
                "atlases":     ["Chen 2023"],
                "confidence":  "moderate",
            }
            for symbol in symbols
        ],
    }
    return env


class TestResolutionLadder(StubbedToolsMixin, unittest.TestCase):
    """sample -> live resolve_ids -> raw string, in that order and no other.

    The rung that was used has to be named in `notes`: a run that quietly matched on the
    raw input string looks exactly like a run that resolved, right up until the card says
    "no MR evidence" about a trait spelling nobody ever searched for.
    """

    def setUp(self):
        self.stub_tools()

    def test_a_pair_in_the_frozen_sample_never_calls_the_live_resolver(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("the frozen sample carries this pair; resolve_ids must "
                                 "not be called")

        pipeline.resolve_ids = forbidden
        self.forget_ledger(pipeline.stem_for("urate", "gout", PREFIX))

        result = pipeline.run_pair(
            "urate",
            "gout",
            stem_prefix = PREFIX,
        )

        self.assertTrue(result["metabolite"]["resolved"])
        self.assertTrue(result["disease"]["resolved"])
        self.assertEqual(result["metabolite"]["resolved_from"], "urate|gout")
        # The stubs give a state C, which writes its own gene-stage note; what must not
        # be there is any note about resolution.
        self.assertEqual(
            [note for note in result["notes"] if "resolver" in note or "raw input" in note],
            [],
            result["notes"],
        )

    def test_a_miss_goes_live_and_the_note_names_the_resolver_and_the_id(self):
        pipeline.resolve_ids = resolve_stub(ids_envelope(
            chebi       = "CHEBI:17750",
            ontology_id = "MONDO:0005044",
            synonyms    = ("betaine", "glycine betaine", "trimethylglycine"),
        ))
        self.forget_ledger(pipeline.stem_for("betaine", "hypertension", PREFIX))

        result = pipeline.run_pair(
            "betaine",
            "hypertension",
            stem_prefix = PREFIX,
        )

        self.assertTrue(result["metabolite"]["resolved"])
        self.assertEqual(result["metabolite"]["resolved_from"], pipeline.LIVE_SOURCE)
        self.assertEqual(result["metabolite"]["id"], "CHEBI:17750")
        self.assertEqual(result["disease"]["id"], "MONDO:0005044")
        self.assertEqual(len(result["metabolite"]["synonyms"]), 3)

        live = [note for note in result["notes"] if "resolver ran live" in note]
        self.assertEqual(len(live), 2, result["notes"])
        self.assertIn("CHEBI:17750", " ".join(live))
        self.assertIn("MONDO:0005044", " ".join(live))

        sent = result["envelopes"]["mr"]["args"]["mark"]
        self.assertEqual(sent, "betaine", "the retrieved synonyms must reach the tools")

    def test_the_live_envelope_reaches_the_ledger_like_any_other_retrieval(self):
        pipeline.resolve_ids = resolve_stub(ids_envelope(
            chebi       = "CHEBI:17750",
            ontology_id = "MONDO:0005044",
            synonyms    = ("betaine",),
        ))
        stem = pipeline.stem_for("betaine", "hypertension", PREFIX)
        self.forget_ledger(stem)

        pipeline.run_pair(
            "betaine",
            "hypertension",
            stem_prefix = PREFIX,
        )

        self.assertEqual(
            [line["tool"] for line in ledger.load(stem)][0],
            "resolve_ids",
            "1A's envelope is retrieved evidence and belongs in the ledger, first",
        )

    def test_a_live_leg_with_no_id_degrades_to_the_raw_string_and_says_so(self):
        pipeline.resolve_ids = resolve_stub(ids_envelope(synonyms=("whatever",)))
        self.forget_ledger(pipeline.stem_for("zzz", "yyy", PREFIX))

        result = pipeline.run_pair(
            "zzz",
            "yyy",
            stem_prefix = PREFIX,
        )

        self.assertFalse(result["metabolite"]["resolved"])
        self.assertEqual(result["metabolite"]["synonyms"], ["zzz"])
        self.assertEqual(result["disease"]["synonyms"], ["yyy"])
        for side, name in (("metabolite", "zzz"), ("disease", "yyy")):
            matching = [note for note in result["notes"] if note.startswith(f"{side} {name!r}")]
            self.assertTrue(matching, result["notes"])
            self.assertIn("not in the pre-resolved sample", matching[0])
            self.assertIn("raw input string only", matching[0])
            self.assertIn("1A", matching[0])

    def test_a_resolver_that_breaks_its_contract_does_not_end_the_run(self):
        def explode(*args, **kwargs):
            raise RuntimeError("resolve_ids must never do this")

        pipeline.resolve_ids = explode
        self.forget_ledger(pipeline.stem_for("zzz", "yyy", PREFIX))

        result = pipeline.run_pair(
            "zzz",
            "yyy",
            stem_prefix = PREFIX,
        )

        self.assertEqual(set(result), RESULT_KEYS)
        self.assertEqual(result["metabolite"]["synonyms"], ["zzz"])
        self.assertTrue(
            [note for note in result["notes"] if "could not be called" in note],
            result["notes"],
        )


class TestGeneStage(StubbedToolsMixin, unittest.TestCase):
    """The atlas -> dossier stage runs after the verdict and never moves it."""

    def setUp(self):
        self.stub_tools()
        pipeline.get_mqtl_instruments = analysable_stub("get_mqtl_instruments")
        pipeline.find_outcome_datasets = analysable_stub("find_outcome_datasets")
        self.calls = []

        def record_dossier(genes, disease_efo, disease_synonyms):
            self.calls.append((list(genes), disease_efo, list(disease_synonyms)))
            return {gene: {"get_known_drugs": envelope("get_known_drugs", gene)}
                    for gene in genes}

        self.stub_gene_stage(
            atlas    = lambda *a, **k: atlas_envelope("GLDC", "CPS1", "AGXT", "SHMT1"),
            dossier  = record_dossier,
        )

    def run_pair(self, **kwargs):
        self.forget_ledger(pipeline.stem_for("glycine", "coronary artery disease", PREFIX))
        return pipeline.run_pair(
            "glycine",
            "coronary artery disease",
            stem_prefix = PREFIX,
            **kwargs,
        )

    def test_state_b_runs_the_atlas_and_takes_the_top_three_genes(self):
        result = self.run_pair()
        self.assertEqual(result["state"], "B")
        self.assertIn("atlas", result["envelopes"])
        self.assertEqual(
            [gene["gene_symbol"] for gene in result["effector_genes"]],
            ["GLDC", "CPS1", "AGXT"],
            f"the cap is pipeline.TOP_GENES = {pipeline.TOP_GENES}",
        )
        self.assertEqual(set(result["envelopes"]["dossier"]), {"GLDC", "CPS1", "AGXT"})

    def test_the_gene_dicts_are_the_atlas_rows_verbatim(self):
        gene = self.run_pair()["effector_genes"][0]
        self.assertEqual(gene["gene_source"], ["author_prioritized"])
        self.assertEqual(gene["atlases"], ["Chen 2023"])

    def test_the_disease_identifiers_reach_the_dossier(self):
        self.run_pair()
        _genes, disease_efo, synonyms = self.calls[0]
        self.assertEqual(disease_efo, "MONDO_0005010")
        self.assertIn("coronary heart disease", [item.lower() for item in synonyms])

    def test_skip_genes_switches_the_atlas_off_and_says_so(self):
        result = self.run_pair(skip_genes=True)
        self.assertNotIn("atlas", result["envelopes"])
        self.assertNotIn("dossier", result["envelopes"])
        self.assertEqual(result["effector_genes"], [])
        self.assertTrue(
            [note for note in result["notes"] if "switched off" in note],
            result["notes"],
        )

    def test_a_caller_named_gene_still_gets_a_dossier_with_the_atlas_off(self):
        result = self.run_pair(
            skip_genes    = True,
            dossier_genes = ["SLC2A9"],
        )
        self.assertEqual(set(result["envelopes"]["dossier"]), {"SLC2A9"})
        self.assertEqual(result["effector_genes"], [])

    def test_state_c_is_not_given_a_gene_list(self):
        pipeline.get_mqtl_instruments = stub("get_mqtl_instruments")
        pipeline.find_outcome_datasets = stub("find_outcome_datasets")
        result = self.run_pair()
        self.assertEqual(result["state"], "C")
        self.assertNotIn("atlas", result["envelopes"])
        self.assertTrue(
            [note for note in result["notes"] if "because the state is C" in note],
            result["notes"],
        )

    def test_a_gene_stage_that_raises_leaves_the_verdict_alone(self):
        def explode(*args, **kwargs):
            raise RuntimeError("the atlas must never do this")

        pipeline.get_effector_genes_atlas = explode
        result = self.run_pair()

        self.assertEqual(result["state"], "B", "a broken atlas says nothing about the pair")
        self.assertNotIn("not evidence of no effect", result["reason"])
        failure = [note for note in result["notes"] if "was abandoned" in note]
        self.assertTrue(failure, result["notes"])
        self.assertIn("RuntimeError", failure[0])

    def test_the_gene_stage_never_reaches_the_classifier(self):
        with_genes = self.run_pair()
        without = self.run_pair(skip_genes=True)
        self.assertEqual(with_genes["state"], without["state"])
        self.assertEqual(with_genes["reason"], without["reason"])


class TestDossierLedgerBinding(unittest.TestCase):
    """Exercise the real 1E decorators and recording binding without network access."""

    def test_every_gene_side_tool_recorded_itself_exactly_once_per_gene(self):
        genes = ["GLDC", "CPS1", "AGXT"]
        names = ("get_target_disease_evidence", "get_known_drugs",
                 "get_chembl_modulators", "get_gnomad_constraint")
        with tempfile.TemporaryDirectory() as directory, patch.object(ledger, "CARDS_DIR", Path(directory)):
            ledger.start("three-genes")
            self.addCleanup(ledger.stop)
            # Stub only the transport-facing function body; keep the real envelope
            # decorator, ContextVar binding, and disk ledger recording.
            from contextlib import ExitStack
            with ExitStack() as patches:
                for name in names:
                    def body(gene, disease=None):
                        return "ok", {"gene": gene}, []
                    body.__name__ = name
                    decorated = _evidence.evidence_tool("synthetic", "https://example.invalid")(body)
                    patches.enter_context(patch.object(pipeline, name, decorated))
                dossier = pipeline._run_dossier(genes, "MONDO_0005010", ["coronary artery disease"])
            lines = ledger.load("three-genes")
            self.assertEqual(len(lines), 12)
            self.assertEqual(set(dossier), set(genes))
            for gene in genes:
                self.assertEqual(set(dossier[gene]), set(names))
                for name in names:
                    matches = [row for row in lines if row["tool"] == name and row["args"]["gene"] == gene]
                    self.assertEqual(len(matches), 1, (gene, name, lines))
                    self.assertEqual(matches[0], dossier[gene][name])

class TestTrialDatesOffline(unittest.TestCase):
    """trials.py's two refusals: an NCT id is never reconstructed, a year is never
    inferred."""

    def test_every_shape_1e_hands_over_yields_the_same_ids(self):
        self.assertEqual(
            trials.normalize_nct_ids([
                "NCT01968967",
                "nct01968967",                                  # the same trial, folded
                {"report_id": "nct01968980", "url": None},
                {"url": "https://clinicaltrials.gov/study/NCT02100514"},
                "d03djt/chronic obstructive pulmonary disease",  # a curated record
                None,
            ]),
            ["NCT01968967", "NCT01968980", "NCT02100514"],
        )

    def test_an_id_is_never_reconstructed_from_something_that_is_not_one(self):
        self.assertEqual(trials.normalize_nct_ids(["NCT123", "nct 01968967", "CT01968967"]), [])

    def test_a_year_comes_from_the_date_or_not_at_all(self):
        self.assertEqual(trials._year("2013-10-29"), 2013)
        self.assertEqual(trials._year("2016-07"), 2016)
        self.assertIsNone(trials._year(None))
        self.assertIsNone(trials._year(""))
        self.assertIsNone(trials._year("soon"))

    def test_a_record_with_no_dates_is_counted_undated_and_given_no_year(self):
        record = trials._record_from_payload(
            "NCT00000000",
            {"protocolSection": {"statusModule": {"overallStatus": "UNKNOWN"}}},
        )
        self.assertFalse(trials._has_year(record))
        for name, _key in trials._DATE_FIELDS:
            self.assertIsNone(record[f"{name}_year"])
            self.assertIsNone(record[f"{name}_date"])

    def test_the_registry_date_type_survives(self):
        record = trials._record_from_payload(
            "NCT00000001",
            {"protocolSection": {"statusModule": {
                "completionDateStruct": {"date": "2030-01-01", "type": "ESTIMATED"}}}},
        )
        self.assertEqual(record["completion_date_type"], "ESTIMATED")
        self.assertEqual(record["completion_year"], 2030)

    def test_no_usable_id_asks_nothing_and_says_so(self):
        env = trials.get_trial_dates(
            ["not-an-id"],
            cap = 12,
        )
        self.assertEqual(env["status"], "empty")
        self.assertEqual(env["data"]["queries"], [])
        self.assertIn(trials.NO_ID_CAVEAT, env["caveats"])

    def test_the_cap_is_written_into_the_caveats(self):
        env = trials.get_trial_dates(
            [f"NCT0000000{n}" for n in range(5)],
            cap = 0,
        )
        self.assertEqual(env["data"]["n_requested"], 5)
        self.assertEqual(env["data"]["n_looked_up"], 0)
        self.assertTrue([c for c in env["caveats"] if "the first 0 were requested" in c])

    def test_a_cached_id_costs_no_request(self):
        cache = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = cache / "nct_dates_cache.json"
        path.write_text(json.dumps({"NCT01968967": {
            "nct_id": "NCT01968967", "start_date": "2013-10-29", "start_year": 2013,
            "primary_completion_year": 2016, "completion_year": 2017,
        }}), encoding="utf-8")

        self.addCleanup(setattr, trials, "CACHE_PATH", trials.CACHE_PATH)
        trials.CACHE_PATH = path

        def forbidden(url, **kwargs):
            raise AssertionError("a cached id must not be requested again")
        self.addCleanup(setattr, _common, "get_json", _common.get_json)
        _common.get_json = forbidden

        env = trials.get_trial_dates(
            ["NCT01968967"],
            cap = 12,
        )
        self.assertEqual(env["status"], "ok")
        self.assertEqual(env["data"]["n_from_cache"], 1)
        self.assertEqual(env["data"]["n_fetched"], 0)
        self.assertEqual(env["data"]["dates"]["NCT01968967"]["start_year"], 2013)

    def test_an_unreadable_cache_degrades_with_a_caveat_instead_of_failing(self):
        cache = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = cache / "nct_dates_cache.json"
        path.write_text("{not json", encoding="utf-8")
        self.addCleanup(setattr, trials, "CACHE_PATH", trials.CACHE_PATH)
        trials.CACHE_PATH = path

        loaded, caveats = trials.load_cache(path)
        self.assertEqual(loaded, {})
        self.assertTrue([c for c in caveats if "could not be read" in c])


if __name__ == "__main__":
    unittest.main(verbosity=2)
