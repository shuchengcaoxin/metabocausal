"""Offline acceptance of the Human-GEM wrapper, pipeline boundary and card rendering."""

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ledger
import pipeline
import render
from MVP3.src import build_index
from MVP3.src.run_batch import run_batch
from tools import _evidence
from tools.gem import map_metabolite_to_genes_gem


SOURCE_FIXTURE = Path(__file__).resolve().parents[1] / "MVP3/tests/fixtures/gem/source_excerpt.json"


def empty_envelope(tool):
    return {
        "tool": tool,
        "args": {},
        "source": "synthetic",
        "url": "https://example.invalid/synthetic",
        "retrieved_at": "2026-09-12T00:00:00+00:00",
        "status": "empty",
        "data": {"estimates": [], "exposures": [], "datasets": []},
        "caveats": [],
    }


class MVP3IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="metabocausal-mvp3-integration-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.index = self.root / "human-gem-fixture.json"
        build_index.build_fixture(SOURCE_FIXTURE, self.index)
        self.environment = patch.dict(
            os.environ,
            {"METABOCAUSAL_GEM_INDEX": str(self.index)},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def run_pair(self, stem, **kwargs):
        with patch.object(ledger, "CARDS_DIR", self.root):
            with patch.object(pipeline, "get_mr_result", return_value=empty_envelope("get_mr_result")), \
                 patch.object(pipeline, "get_mqtl_instruments", return_value=empty_envelope("get_mqtl_instruments")), \
                 patch.object(pipeline, "find_outcome_datasets", return_value=empty_envelope("find_outcome_datasets")):
                result = pipeline.run_pair(
                    "glycine",
                    "coronary artery disease",
                    skip_coloc=True,
                    stem_prefix=stem,
                    **kwargs,
                )
            entries = ledger.load(Path(result["ledger_path"]).name.replace(ledger.SUFFIX, ""))
        return result, entries

    def test_wrapper_records_the_module_envelope_exactly_once(self):
        recorded = []
        with _evidence.recording(lambda envelope: recorded.append(deepcopy(envelope))):
            envelope = map_metabolite_to_genes_gem("CHEBI:15428")
        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(envelope["data"]["network_calls"], 0)
        self.assertEqual(envelope["data"]["model_version"], "2.0.0")
        self.assertEqual(recorded, [envelope])

    def test_batch_reuses_normalized_ids_and_keeps_unmapped_diagnostics(self):
        result = run_batch(
            ["CHEBI:15428", "CHEBI_15428", "CHEBI:17191", "CHEBI:999999999"],
            index_path=self.index,
            snapshot_id="fixture-v1",
        )
        self.assertEqual(result["input_snapshot_id"], "fixture-v1")
        self.assertEqual(result["summary"]["input_count"], 4)
        self.assertEqual(result["summary"]["unique_valid_chebi_count"], 3)
        self.assertEqual(result["summary"]["mapped"], 2)
        self.assertEqual(result["summary"]["unmapped"], 1)
        self.assertTrue(result["records"][1]["reused"])
        self.assertEqual(result["records"][3]["envelope"]["status"], "empty")

    def test_state_c_still_receives_context_without_changing_classification(self):
        with_gem, entries = self.run_pair("mvp3-state-c", skip_genes=True)
        without_gem, _ = self.run_pair("mvp3-state-c-off", skip_genes=True, skip_gem=True)
        self.assertEqual(with_gem["state"], "C")
        self.assertEqual(with_gem["reason"], without_gem["reason"])
        self.assertEqual(with_gem["envelopes"]["gem"]["status"], "ok")
        self.assertEqual([row["tool"] for row in entries].count("map_metabolite_to_genes_gem"), 1)
        self.assertGreater(with_gem["envelopes"]["gem"]["data"]["total_candidates"], 1)
        self.assertTrue(all(
            row["origin"] == "biochemical"
            for row in with_gem["envelopes"]["gem"]["data"]["candidates"]
        ))

    def test_only_explicitly_selected_gene_reaches_1e(self):
        captured = []

        def dossier(genes, disease_efo, disease_synonyms):
            captured.append((list(genes), disease_efo, list(disease_synonyms)))
            return {gene: {} for gene in genes}

        with patch.object(pipeline, "_run_dossier", side_effect=dossier):
            result, _ = self.run_pair(
                "mvp3-bounded-dossier",
                skip_genes=True,
                dossier_genes=["GLDC"],
            )
        self.assertEqual(captured[0][0], ["GLDC"])
        available = {
            row["symbol"] for row in result["envelopes"]["gem"]["data"]["candidates"]
            if row.get("symbol_status") == "unique"
        }
        self.assertIn("GLDC", available)
        self.assertGreater(len(available), len(captured[0][0]))
        card = render.render_card(result)
        self.assertIn("Dossier genes that also occur in the Human-GEM reaction context: GLDC", card)
        self.assertIn("GPR `", card)
        self.assertIn("matched compartment(s)", card)
        self.assertIn("cannot change A/B/C", card)
        self.assertIn("does not demonstrate disease mediation", card)
        self.assertIn("Human-GEM results, when present above, are biochemical context", card)
        self.assertNotIn("via-enzyme arm (MVP3) are not in this build", card)

    def test_missing_index_is_a_context_error_and_does_not_abort_the_pair(self):
        with patch.dict(os.environ, {"METABOCAUSAL_GEM_INDEX": str(self.root / "missing.json")}):
            result, entries = self.run_pair("mvp3-missing-index", skip_genes=True)
        self.assertEqual(result["state"], "C")
        self.assertEqual(result["envelopes"]["gem"]["status"], "error")
        self.assertIn("index is missing", result["envelopes"]["gem"]["data"]["error"])
        self.assertEqual([row["tool"] for row in entries].count("map_metabolite_to_genes_gem"), 1)
        card = render.render_card(result)
        self.assertIn("local model/index lookup failed", card)
        self.assertIn("A/B/C state and genetic evidence are unchanged", card)

    def test_card_preserves_reaction_direction_compartment_and_raw_gpr(self):
        result, _ = self.run_pair("mvp3-render", skip_genes=True)
        card = render.render_card(result)
        self.assertIn("Exact ChEBI mapping in Human-GEM 2.0.0", card)
        self.assertIn("matched compartment(s) m", card)
        self.assertIn("GPR `ENSG", card)
        self.assertIn("complex member True", card)
        self.assertIn("cannot change A/B/C", card)


if __name__ == "__main__":
    unittest.main()
