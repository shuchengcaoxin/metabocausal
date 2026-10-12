"""pipeline.run_pair as one deterministic call. Network-live, stdlib unittest.

    python -m unittest tests.test_pipeline -v             # from the repo root

test_integration covers the same chain through scripts/end_to_end.py, which takes a
frozen sample entry. This file covers what only the name-in signature can go wrong at:
the synonym lookup that stands in for 1A, the honest degradation when a name is not in
the sample, and the ledger accounting once the 1E dossier is added on top.

WHAT IS ASSERTED, AND WHY EACH ONE IS THE REAL RISK

  urate x gout -> A                 the lookup must find the pair by its input names
                                    and hand the tools the SYNONYM lists, not the two
                                    raw strings; "urate" alone finds nothing in MR-EVE,
                                    whose trait string is "Urate"
  glycine x CAD -> B                the flagship demo, reached through run_pair rather
                                    than through end_to_end.run_pair
  zzz x yyy -> C plus a note        a name neither the frozen sample nor the live 1A
                                    resolver can place must degrade to its raw input
                                    string and SAY SO. Silently returning C for a name
                                    nobody resolved is the failure this whole project
                                    is built against
  betaine x hypertension            the rung between those two: not in the frozen
                                    sample, resolvable live. The ids and the synonym
                                    lists must come from resolve_ids and the note must
                                    name it, because a card that shows a MONDO id nobody
                                    retrieved is worse than a card with none
  the gene stage on glycine x CAD   1D names the genes, the four 1E tools describe each one, and none of it may
                                    move the A/B/C state. Each tool records its own
                                    envelope; if run_pair recorded them too, every
                                    dossier line would appear twice and the traceability
                                    footer would lie

Each pair runs ONCE for the whole file - every run sends real queries and spends
OpenGWAS credits. The ledgers these tests overwrite are saved and put back afterwards,
and the throwaway ledgers are deleted.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
import hashlib

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ledger
import pipeline
import render
from tools import _common

ENVELOPE_KEYS = {"tool", "args", "source", "url", "retrieved_at", "status", "data", "caveats"}

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

# The four gene-side 1E tools.
DOSSIER_TOOLS = (
    "get_target_disease_evidence",
    "get_known_drugs",
    "get_chembl_modulators",
    "get_gnomad_constraint",
)

TOUCHED_STEMS = (
    "urate_gout",
    "glycine_coronary-artery-disease",
    "zzz_yyy",
    "betaine_hypertension",
)

_RESULTS = {}
_SAVED_LEDGERS = {}


def result_for(
    metabolite:    str,
    disease:       str,
    dossier_genes = None,
    skip_genes:    bool = True,
) -> dict:
    """One run per pair per test session, cached. Every call to this would otherwise
    re-send the MR-EVE queries and re-spend OpenGWAS tophits credits.

    `skip_genes` defaults to True here and not in `run_pair`: a class that is about the
    A/B/C verdict has no use for the additional gene-side requests, and the gene stage gets its own
    class below, which runs it once with the real default.
    """
    key = (metabolite, disease, tuple(dossier_genes or ()), skip_genes)
    if key not in _RESULTS:
        # Each cached parameter variant owns its ledger; another variant must not truncate it.
        prefix = "live-test-" + hashlib.sha256(repr(key).encode()).hexdigest()[:12]
        stem = pipeline.stem_for(metabolite, disease, prefix)
        target = ledger.path_for(stem)
        _SAVED_LEDGERS[stem] = target.read_bytes() if target.exists() else None
        _RESULTS[key] = pipeline.run_pair(
            metabolite,
            disease,
            stem_prefix   = prefix,
            skip_genes    = skip_genes,
            dossier_genes = list(dossier_genes or []),
        )
    return _RESULTS[key]


def setUpModule():
    for stem in TOUCHED_STEMS:
        target = ledger.path_for(stem)
        _SAVED_LEDGERS[stem] = target.read_bytes() if target.exists() else None


def tearDownModule():
    for stem, saved in _SAVED_LEDGERS.items():
        target = ledger.path_for(stem)
        if saved is None:
            if target.exists():
                target.unlink()
        else:
            target.write_bytes(saved)


class ResultMixin:
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

    def assert_result_shape(self, result):
        self.assertEqual(set(result), RESULT_KEYS)
        self.assertIsInstance(result["notes"], list)
        self.assertIsInstance(result["envelopes"], dict)
        self.assertIn("mr", result["envelopes"])
        self.assertIn("instruments", result["envelopes"])
        self.assertIn("outcomes", result["envelopes"])


class TestStateA(ResultMixin, unittest.TestCase):
    """urate x gout. A because an estimate was RETRIEVED, not because an effect is real."""

    @classmethod
    def setUpClass(cls):
        cls.result = result_for(
            "urate",
            "gout",
        )

    def test_state_is_a(self):
        self.assertEqual(self.result["state"], "A")

    def test_result_has_the_documented_shape(self):
        self.assert_result_shape(self.result)

    def test_every_envelope_carries_the_eight_keys(self):
        envelopes = self.result["envelopes"]
        self.assert_envelope(envelopes["mr"], "get_mr_result")
        self.assert_envelope(envelopes["instruments"], "get_mqtl_instruments")
        self.assert_envelope(envelopes["outcomes"], "find_outcome_datasets")

    def test_the_catalog_is_skipped_by_default_and_this_run_skipped_the_gene_stage(self):
        self.assertNotIn("catalog", self.result["envelopes"])
        self.assertNotIn("atlas", self.result["envelopes"])
        self.assertNotIn("dossier", self.result["envelopes"])
        self.assertEqual(self.result["effector_genes"], [])

    def test_the_ledger_file_exists_with_at_least_three_entries(self):
        path = Path(self.result["ledger_path"])
        self.assertTrue(path.exists(), f"{path.name} must be on disk after the run")
        self.assertGreaterEqual(self.result["n_ledger_entries"], 3)
        self.assertEqual(self.result["n_ledger_entries"], len(ledger.load(path.stem.split(".")[0])))

    def test_the_synonym_list_and_not_the_raw_string_reached_the_tools(self):
        self.assertTrue(self.result["metabolite"]["resolved"])
        self.assertEqual(self.result["metabolite"]["resolved_from"], "urate|gout")
        sent = self.result["envelopes"]["mr"]["args"]["metabolite_synonyms"]
        self.assertGreater(len(sent), 1, "1A's synonym list must reach 1B, not just 'urate'")

    def test_a_rests_on_a_retrieved_estimate(self):
        env = self.result["envelopes"]["mr"]
        self.assertEqual(env["status"], "ok")
        self.assertGreaterEqual(env["data"]["n_estimates"], 1)

    def test_no_degradation_note_for_a_pair_that_is_in_the_sample(self):
        self.assertEqual(
            [note for note in self.result["notes"]
             if "resolver" in note or "raw input" in note],
            [],
            self.result["notes"],
        )


class TestStateB(ResultMixin, unittest.TestCase):
    """glycine x coronary artery disease: no retrieved estimate, but analysable."""

    @classmethod
    def setUpClass(cls):
        cls.result = result_for(
            "glycine",
            "coronary artery disease",
        )

    def test_state_is_b(self):
        self.assertEqual(self.result["state"], "B")

    def test_b_is_not_a_claim_that_an_estimate_exists(self):
        self.assertIn(self.result["envelopes"]["mr"]["status"], ("empty", "error"))

    def test_b_rests_on_instruments_and_an_outcome_dataset(self):
        exposures = self.result["envelopes"]["instruments"]["data"]["exposures"]
        self.assertTrue([row for row in exposures if (row.get("gws_hits") or 0) >= 3])
        self.assertTrue(self.result["envelopes"]["outcomes"]["data"]["datasets"])


class TestUnknownPairDegradesHonestly(ResultMixin, unittest.TestCase):
    """The pair nobody resolved - not the frozen sample, not OLS4, not PubChem. C is
    allowed; a silent C is not."""

    @classmethod
    def setUpClass(cls):
        cls.result = result_for(
            "zzz",
            "yyy",
        )

    def test_state_is_c_and_nothing_raised(self):
        self.assertEqual(self.result["state"], "C")
        self.assert_result_shape(self.result)

    def test_both_sides_are_marked_unresolved(self):
        self.assertFalse(self.result["metabolite"]["resolved"])
        self.assertFalse(self.result["disease"]["resolved"])
        self.assertEqual(self.result["metabolite"]["synonyms"], ["zzz"])
        self.assertEqual(self.result["disease"]["synonyms"], ["yyy"])

    def test_the_degradation_note_names_both_sides_the_live_resolver_and_1a(self):
        notes = self.result["notes"]
        for side, name in (("metabolite", "zzz"), ("disease", "yyy")):
            matching = [note for note in notes if note.startswith(f"{side} {name!r}")]
            self.assertTrue(matching, f"no note for the {side} side: {notes}")
            self.assertIn("not in the pre-resolved sample", matching[0])
            self.assertIn("raw input string only", matching[0])
            self.assertIn("1A", matching[0])
            self.assertIn("resolve_ids", matching[0])

    def test_the_live_resolver_was_still_asked_and_is_in_the_ledger(self):
        stem = Path(self.result["ledger_path"]).name.replace(ledger.SUFFIX, "")
        names = [line.get("tool") for line in ledger.load(stem)]
        self.assertEqual(names.count("resolve_ids"), 1, names)

    def test_c_is_never_stated_as_no_effect(self):
        self.assertIn("not evidence of no effect", self.result["reason"])


class TestLiveResolutionFallback(ResultMixin, unittest.TestCase):
    """betaine x hypertension: not in the frozen sample, resolvable live.

    This is the rung the pipeline gained tonight. Before it, any pair outside the six
    frozen demo entries ran on its raw input string alone - which is the quietest way
    this project could have failed, because "no MR evidence for betaine" and "no MR
    evidence for the string 'betaine'" print identically.
    """

    @classmethod
    def setUpClass(cls):
        cls.result = result_for(
            "betaine",
            "hypertension",
        )

    def test_both_sides_resolved_through_the_live_resolver(self):
        for side in ("metabolite", "disease"):
            with self.subTest(side=side):
                entity = self.result[side]
                self.assertTrue(entity["resolved"], entity)
                self.assertEqual(entity["resolved_from"], pipeline.LIVE_SOURCE)

    def test_the_ids_are_the_ones_the_override_table_pins(self):
        self.assertEqual(self.result["metabolite"]["id"], "CHEBI:17750")
        self.assertEqual(self.result["disease"]["id"], "MONDO:0005044")

    def test_the_retrieved_synonyms_and_not_the_typed_string_reached_the_tools(self):
        synonyms = self.result["metabolite"]["synonyms"]
        self.assertGreater(len(synonyms), 1, synonyms)
        sent = self.result["envelopes"]["mr"]["args"]["metabolite_synonyms"]
        self.assertEqual(sent, synonyms)

    def test_the_note_names_the_live_resolver_and_the_id_it_returned(self):
        live = [note for note in self.result["notes"] if "resolver ran live" in note]
        self.assertEqual(len(live), 2, self.result["notes"])
        self.assertIn("CHEBI:17750", " ".join(live))
        self.assertIn("MONDO:0005044", " ".join(live))

    def test_the_resolver_envelope_is_the_first_line_of_the_ledger(self):
        stem = Path(self.result["ledger_path"]).name.replace(ledger.SUFFIX, "")
        names = [line.get("tool") for line in ledger.load(stem)]
        self.assertEqual(names[0], "resolve_ids", names)
        self.assertEqual(names.count("resolve_ids"), 1, names)


class TestDossierIsRecordedExactlyOnce(ResultMixin, unittest.TestCase):
    """glycine x CAD with GLDC forced and the atlas off. The gene-side tools record
    themselves; run_pair must not."""

    @classmethod
    def setUpClass(cls):
        cls.result = result_for(
            "glycine",
            "coronary artery disease",
            ["GLDC"],
        )
        cls.lines = ledger.load(Path(cls.result["ledger_path"]).name.replace(".ledger.jsonl", ""))

    def test_the_dossier_envelopes_are_returned_per_gene(self):
        dossier = self.result["envelopes"]["dossier"]
        self.assertEqual(set(dossier), {"GLDC"})
        self.assertEqual(set(dossier["GLDC"]), set(DOSSIER_TOOLS))
        for tool, env in dossier["GLDC"].items():
            self.assert_envelope(env, tool)

    def test_the_ledger_gained_exactly_one_line_per_gene_side_tool(self):
        names = [line.get("tool") for line in self.lines]
        for tool in DOSSIER_TOOLS:
            self.assertEqual(
                names.count(tool),
                1,
                f"{tool} must appear exactly once in the ledger, not {names.count(tool)}",
            )

    def test_the_ledger_holds_the_core_tools_plus_the_four_gene_side_tools(self):
        # Three 1B/1C arms, the colocalisation arm that runs after the verdict, and the
        # four gene-side tools.
        self.assertEqual(len(self.lines), 8, [line.get("tool") for line in self.lines])
        self.assertEqual(self.result["n_ledger_entries"], 8)
        self.assertIn("get_colocalisation", [line.get("tool") for line in self.lines])

    def test_the_dossier_did_not_move_the_state(self):
        self.assertEqual(self.result["state"], "B")

    def test_a_caller_named_gene_is_not_an_effector_gene_this_run_nominated(self):
        self.assertEqual(self.result["effector_genes"], [])


class TestGeneStage(ResultMixin, unittest.TestCase):
    """glycine x CAD: the atlas nominates genes and four 1E tools describe each."""

    @classmethod
    def setUpClass(cls):
        cls.result = result_for(
            "glycine",
            "coronary artery disease",
            skip_genes = False,
        )
        cls.lines = ledger.load(Path(cls.result["ledger_path"]).name.replace(".ledger.jsonl", ""))

    def test_the_atlas_ran_and_named_genes(self):
        env = self.result["envelopes"]["atlas"]
        self.assert_envelope(env, "get_effector_genes_atlas")
        self.assertEqual(env["status"], "ok")
        self.assertGreaterEqual(env["data"]["n_genes"], 2)

    def test_the_top_three_atlas_genes_became_the_effector_gene_list(self):
        genes = self.result["effector_genes"]
        self.assertEqual(len(genes), pipeline.TOP_GENES)
        self.assertEqual(
            [gene["gene_symbol"] for gene in genes],
            [gene["gene_symbol"]
             for gene in self.result["envelopes"]["atlas"]["data"]["genes"][:pipeline.TOP_GENES]],
        )

    def test_the_glycine_anchor_genes_are_among_them(self):
        symbols = {gene["gene_symbol"] for gene in self.result["effector_genes"]}
        self.assertIn("GLDC", symbols, symbols)

    def test_each_gene_dict_still_carries_the_atlas_attribution(self):
        for gene in self.result["effector_genes"]:
            with self.subTest(gene=gene["gene_symbol"]):
                self.assertTrue(gene.get("gene_source"), gene)
                self.assertTrue(gene.get("atlases"), gene)

    def test_every_named_gene_got_the_full_dossier(self):
        dossier = self.result["envelopes"]["dossier"]
        self.assertEqual(
            set(dossier),
            {gene["gene_symbol"] for gene in self.result["effector_genes"]},
        )
        for gene, gene_tools in dossier.items():
            with self.subTest(gene=gene):
                self.assertEqual(set(gene_tools), set(DOSSIER_TOOLS))
                for tool, env in gene_tools.items():
                    self.assert_envelope(env, tool)

    def test_every_gene_side_tool_recorded_itself_exactly_once_per_gene(self):
        names = [line.get("tool") for line in self.lines]
        n_genes = len(self.result["envelopes"]["dossier"])
        for tool in DOSSIER_TOOLS:
            self.assertEqual(names.count(tool), n_genes, f"{tool}: {names.count(tool)}")
        self.assertEqual(names.count("get_effector_genes_atlas"), 1, names)

    def test_the_gene_stage_did_not_move_the_state(self):
        self.assertEqual(self.result["state"], "B")
        without = result_for(
            "glycine",
            "coronary artery disease",
        )
        self.assertEqual(self.result["state"], without["state"])
        self.assertEqual(self.result["reason"], without["reason"])

class TestSynonymLookup(unittest.TestCase):
    """The lookup itself, no network: it stands in for 1A until 1A lands."""

    @classmethod
    def setUpClass(cls):
        cls.sample = pipeline.load_sample()

    def resolve(
        self,
        name,
        side,
    ):
        return pipeline.resolve_entity(
            name,
            side,
            self.sample,
        )

    def test_the_input_name_matches_in_any_case(self):
        self.assertTrue(self.resolve("GLYCINE", "metabolite")["resolved"])
        self.assertTrue(self.resolve("  Coronary   Artery Disease ", "disease")["resolved"])

    def test_a_stored_synonym_matches(self):
        self.assertEqual(self.resolve("CAD", "disease")["resolved_from"],
                         "glycine|coronary artery disease")
        self.assertTrue(self.resolve("uric acid", "metabolite")["resolved"])

    def test_a_metabolite_name_does_not_resolve_on_the_disease_side(self):
        self.assertFalse(self.resolve("glycine", "disease")["resolved"])

    def test_the_ontology_id_comes_back_in_the_underscore_form_1e_needs(self):
        disease = self.resolve("gout", "disease")
        self.assertEqual(disease["id"], "MONDO:0005393")
        self.assertEqual(_common.underscore_ontology_id(disease["id"]), "MONDO_0005393")

    def test_the_stem_is_one_readable_name_per_pair(self):
        self.assertEqual(
            pipeline.stem_for("trimethylamine N-oxide", "coronary artery disease"),
            "trimethylamine-n-oxide_coronary-artery-disease",
        )
        self.assertEqual(pipeline.stem_for("../etc", "passwd"), "etc_passwd")


if __name__ == "__main__":
    unittest.main(verbosity=2)
