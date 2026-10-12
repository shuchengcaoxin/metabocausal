"""GEM-D2 regression: Human-GEM reaction context may not stand in for a nomination.

    python -m unittest tests.test_fix_gem_d2 -v          # from the repo root

WHAT BROKE. The 2026-09-17 re-run's case GV03
(``docs/research/section9_adversarial/rerun_2026-09-17/new_probes/gem/probe_gem.py``)
put this headline through both gates on a run whose atlas nomination layer was never
queried:

    "GCSH and GLDC are the effector genes this run nominates for the metabolite."

Both gates accepted it and section 9 printed it, because V5 is set membership against
every string the run carries and a Human-GEM candidate symbol is one of them. Section 5
of the same card said "The atlas nomination layer was not queried in this run", so the
card contradicted itself in two adjacent sections.

WHAT THIS FILE HOLDS. The three closure demonstrations, plus the index-level facts they
rest on:

  1. gem candidates present, no atlas nominations, nomination wording  -> blocked;
  2. a run WITH atlas nominations, nomination wording                  -> printed;
  3. gem candidates present, biochemical-context wording               -> printed.

The end-to-end class is adapted from the probe's ``model_path_case`` /
``through_gate_one`` helpers and from ``tests/test_pipeline_offline.py``'s atlas stub.
It is offline: the three network arms are stubbed, the Human-GEM index is built from the
checked-in source excerpt, and the ledger is redirected to a temporary directory.

The 1D atlas is stubbed rather than called because ``data/atlas_locus_gene.csv`` is not
in this checkout (see DATA_ACCESS.md); the stub envelope is the shape
``tools/atlas.get_effector_genes_atlas`` returns, which is what the validator reads.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ledger
import pipeline
import render
import validate_card
from MVP3.src import build_index
from llm import Credential
from llm import interpret as interpret_module
from llm.base import Reply

SOURCE_FIXTURE = REPO_ROOT / "MVP3/tests/fixtures/gem/source_excerpt.json"
MODEL_NAME = "claude-opus-5"
FAKE_CREDENTIAL = Credential(provider="anthropic", key="OFFLINE-TEST-NOT-A-KEY")

NOMINATION_PROSE = {
    "headline": "GCSH and GLDC are the effector genes this run nominates for the metabolite.",
}
BIOCHEMICAL_PROSE = {
    "headline": "GCSH and GLDC appear in the Human-GEM reaction context retrieved for this "
                "metabolite; reaction membership is not an effector-gene nomination.",
}


def rules(findings) -> set:
    return {finding.rule for finding in findings}


def envelope(tool: str, *, status: str = "empty", data: dict = None) -> dict:
    return {
        "tool":         tool,
        "args":         {},
        "source":       "synthetic",
        "url":          "https://example.invalid/synthetic",
        "retrieved_at": "2026-09-12T00:00:00+00:00",
        "status":       status,
        "data":         data if data is not None else {"estimates": [], "exposures": [], "datasets": []},
        "caveats":      [],
    }


def analysable(tool: str, key: str, rows: list) -> dict:
    """A 1C envelope rich enough for classify_state to say B."""
    data = {"estimates": [], "exposures": [], "datasets": []}
    data[key] = rows
    return envelope(
        tool,
        status = "ok",
        data   = data,
    )


def atlas_envelope(*symbols) -> dict:
    """A 1D atlas envelope naming `symbols`, in the shape tools/atlas.py returns."""
    return envelope(
        "get_effector_genes_atlas",
        status = "ok" if symbols else "empty",
        data   = {
            "matched_on":   "metabolite_name",
            "matched_term": "glycine",
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
        },
    )


def gem_envelope(*symbols) -> dict:
    """A Human-GEM envelope carrying `symbols` as reaction-linked candidates."""
    return {
        "tool":         "map_metabolite_to_genes_gem",
        "args":         {"chebi_id": "CHEBI:15428"},
        "source":       "Human-GEM",
        "url":          "https://github.com/SysBioChalmers/Human-GEM",
        "retrieved_at": "2026-09-12T00:00:00+00:00",
        "status":       "ok",
        "data":         {
            "route":             "via_enzyme",
            "evidence_type":     "biochemical",
            "total_reactions":   1,
            "total_candidates":  len(symbols),
            "reactions":         [{"id": "MAR04792", "direction": "reversible"}],
            "candidates":        [
                {
                    "symbol":         symbol,
                    "ensembl":        f"ENSG0000014090{position}",
                    "symbol_status":  "unique",
                    "role":           "enzyme",
                    "n_reactions":    1,
                    "complex_member": True,
                }
                for position, symbol in enumerate(symbols)
            ],
        },
        "caveats":      [],
    }


def synthetic_run(*, gem=None, atlas=None, effector_genes=()) -> dict:
    envelopes = {"mr": envelope("get_mr_result")}
    if gem is not None:
        envelopes["gem"] = gem
    if atlas is not None:
        envelopes["atlas"] = atlas
    return {
        "state":          "C",
        "reason":         "no MR estimate was retrieved for this pair.",
        "metabolite":     {"label": "glycine", "id": "CHEBI:15428"},
        "disease":        {"label": "coronary artery disease", "id": "EFO:0001645"},
        "envelopes":      envelopes,
        "effector_genes": [
            {
                "gene_symbol": symbol,
                "gene_source": ["author_prioritized"],
                "atlases":     ["Chen 2023"],
            }
            for symbol in effector_genes
        ],
        "notes":          [],
    }


class TestContextOnlyGeneIndex(unittest.TestCase):
    """Which genes the run holds ONLY as reaction context. Set membership, not wording."""

    def test_a_human_gem_only_symbol_is_context_only(self):
        run = synthetic_run(gem=gem_envelope("GCSH", "GLDC"))
        self.assertEqual(
            {"gcsh", "gldc"} & validate_card.context_only_genes(run),
            {"gcsh", "gldc"},
        )

    def test_a_symbol_the_atlas_also_nominated_is_not_context_only(self):
        run = synthetic_run(
            gem            = gem_envelope("GCSH", "GLDC"),
            atlas          = atlas_envelope("GLDC"),
            effector_genes = ("GLDC",),
        )
        context = validate_card.context_only_genes(run)
        self.assertIn("gcsh", context)
        self.assertNotIn("gldc", context, "the atlas nominated GLDC, so V7 has no opinion on it")

    def test_a_run_without_the_arm_has_no_context_only_genes(self):
        run = synthetic_run(atlas=atlas_envelope("GLDC"), effector_genes=("GLDC",))
        self.assertEqual(validate_card.context_only_genes(run), set())
        self.assertEqual(validate_card.source_index(run).context_only_genes, set())

    def test_the_envelope_is_found_wherever_it_sits(self):
        """Structural, not positional: a validator that knew the layout would stop
        restricting anything the day the layout moved."""
        run = synthetic_run()
        run["cached"] = {"replay": [{"envelopes": [gem_envelope("GCSH")]}]}
        self.assertIn("gcsh", validate_card.context_only_genes(run))

    def test_the_ensembl_id_travels_with_the_symbol(self):
        run = synthetic_run(gem=gem_envelope("GCSH"))
        self.assertIn("ensg00000140900", validate_card.context_only_genes(run))


class TestNominationWording(unittest.TestCase):
    """V7. A context-only gene may be quoted as reaction context and as nothing else."""

    def setUp(self):
        self.context_run = synthetic_run(gem=gem_envelope("GCSH", "GLDC"))
        self.nominated_run = synthetic_run(
            gem            = gem_envelope("GCSH", "GLDC"),
            atlas          = atlas_envelope("GLDC"),
            effector_genes = ("GLDC",),
        )

    def test_nomination_wording_on_a_context_only_gene_is_rejected(self):
        findings = validate_card.validate(NOMINATION_PROSE, self.context_run)
        self.assertIn("V7", rules(findings))
        self.assertIn("not an effector-gene nomination", str(findings[0]))

    def test_biochemical_wording_on_a_context_only_gene_is_accepted(self):
        self.assertEqual(validate_card.validate(BIOCHEMICAL_PROSE, self.context_run), [])

    def test_the_cards_own_disclaimer_wording_is_accepted(self):
        text = ("Human-GEM reaction membership does not nominate GCSH as an effector gene "
                "of this metabolite.")
        self.assertEqual(validate_card.validate({"limits": text}, self.context_run), [])

    def test_a_bare_sentence_without_the_context_is_rejected(self):
        text = "GCSH is the gene to look at next for this pair."
        findings = validate_card.validate({"reading": text}, self.context_run)
        self.assertIn("V7", rules(findings))
        self.assertIn("does not say so", str(findings[0]))

    def test_an_ensembl_id_from_the_context_arm_is_bound_too(self):
        text = "ENSG00000140900 is the effector gene this run nominates."
        self.assertIn("V7", rules(validate_card.validate({"headline": text}, self.context_run)))

    def test_a_gene_the_atlas_nominated_still_passes(self):
        text = "GLDC is an effector gene this run nominates for the metabolite."
        self.assertEqual(validate_card.validate({"headline": text}, self.nominated_run), [])

    def test_the_same_sentence_about_a_context_only_gene_still_fails(self):
        text = "GCSH is an effector gene this run nominates for the metabolite."
        self.assertIn("V7", rules(validate_card.validate({"headline": text}, self.nominated_run)))

    def test_a_gene_in_no_arm_at_all_is_still_V5(self):
        """V7 is an extra binding, not a replacement: an invented symbol is V5's business."""
        text = "ZZZX9 is the effector gene this run nominates."
        self.assertIn("V5", rules(validate_card.validate({"headline": text}, self.context_run)))

    def test_a_run_without_the_arm_is_untouched(self):
        run = synthetic_run(atlas=atlas_envelope("GLDC"), effector_genes=("GLDC",))
        text = "GLDC is an effector gene this run nominates for the metabolite."
        self.assertEqual(validate_card.validate({"headline": text}, run), [])

    def test_a_negation_elsewhere_in_the_sentence_does_not_clear_the_nomination(self):
        """The mechanism a sentence-wide NEGATION exemption would have printed: one added
        clause and the same nomination claim went through, denying the reading the
        reaction-context branch then accepted it under."""
        for text in (
            "GCSH and GLDC are the effector genes this run nominates for the metabolite, "
            "not merely a reaction listing.",
            "GCSH and GLDC are the effector genes this run nominates; no other reaction "
            "was retrieved.",
            "Rather than guessing, the Human-GEM reaction context names GCSH and GLDC as "
            "the lead candidates.",
        ):
            with self.subTest(text=text):
                findings = validate_card.validate({"headline": text}, self.context_run)
                self.assertIn("V7", rules(findings))
                self.assertIn("presented as a nomination", findings[0].name)

    def test_a_nomination_written_without_this_projects_vocabulary_still_fails_closed(self):
        """"the genes to take forward" is the same claim as "the genes this run
        nominates". A verb blacklist that fails OPEN on an unlisted verb is not a
        binding."""
        for text in (
            "The Human-GEM reaction context points to GCSH and GLDC as the genes to take "
            "forward for this metabolite.",
            "The Human-GEM reaction for this metabolite makes GCSH and GLDC the genes to "
            "watch.",
            "GCSH and GLDC are the reaction-linked genes we recommend for the next step.",
        ):
            with self.subTest(text=text):
                findings = validate_card.validate({"headline": text}, self.context_run)
                self.assertIn("V7", rules(findings))
                self.assertIn("presented as a nomination", findings[0].name)

    def test_stating_the_absence_is_accepted_even_without_a_biochemistry_word(self):
        """The asymmetry this rule must not have: the sentence whose whole job is to say
        that nothing was nominated is the one sentence V7 may never kill."""
        for text in (
            "The atlas nomination layer was not queried in this run, so GCSH and GLDC "
            "were not nominated as effector genes.",
            "The atlas nomination layer was not queried in this run; nothing here "
            "nominates GCSH or GLDC.",
            "GCSH and GLDC are not effector-gene nominations for this pair.",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    validate_card.validate({"limits": text}, self.context_run),
                    [],
                )


class TestGemD2Closure(unittest.TestCase):
    """The three demonstrations, end to end through both gates and the renderer."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="metabocausal-gemd2-")
        cls.root = Path(cls.temp.name)
        cls.index = cls.root / "human-gem-fixture.json"
        build_index.build_fixture(SOURCE_FIXTURE, cls.index)
        cls.environment = patch.dict(
            os.environ,
            {"METABOCAUSAL_GEM_INDEX": str(cls.index)},
        )
        cls.environment.start()
        cls.context_run = cls.run_pair("gemd2ctx")
        cls.nominated_run = cls.run_pair(
            "gemd2nom",
            analysable_arms = True,
            atlas           = atlas_envelope("GLDC", "CPS1", "AGXT"),
        )

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    @classmethod
    def run_pair(cls, stem: str, *, analysable_arms: bool = False, atlas=None) -> dict:
        instruments = (
            analysable("get_mqtl_instruments", "exposures", [{"id": "met-a-000", "gws_hits": 4}])
            if analysable_arms else envelope("get_mqtl_instruments")
        )
        outcomes = (
            analysable("find_outcome_datasets", "datasets", [{"id": "ieu-a-000"}])
            if analysable_arms else envelope("find_outcome_datasets")
        )
        patches = [
            patch.object(ledger, "CARDS_DIR", cls.root),
            patch.object(pipeline, "get_mr_result", return_value=envelope("get_mr_result")),
            patch.object(pipeline, "get_mqtl_instruments", return_value=instruments),
            patch.object(pipeline, "find_outcome_datasets", return_value=outcomes),
        ]
        if atlas is not None:
            patches.append(patch.object(pipeline, "get_effector_genes_atlas", return_value=atlas))
            patches.append(patch.object(pipeline, "_run_dossier", return_value={}))
        for entered in patches:
            entered.start()
        try:
            return pipeline.run_pair(
                "glycine",
                "coronary artery disease",
                skip_coloc  = True,
                stem_prefix = stem,
            )
        finally:
            for entered in reversed(patches):
                entered.stop()

    def section_nine(self, run: dict, fields: dict) -> str:
        reply = Reply(
            text     = json.dumps(fields),
            provider = "anthropic",
            model    = MODEL_NAME,
        )
        with patch.object(interpret_module, "complete", return_value=reply):
            interpretation = interpret_module.interpret(
                run,
                provider   = "claude",
                model      = MODEL_NAME,
                credential = FAKE_CREDENTIAL,
            )
        return "\n".join(render._section_reasoning(run, interpretation)).strip()

    def test_the_run_under_test_is_the_gv03_shape(self):
        self.assertEqual(self.context_run["state"], "C")
        self.assertIn("gem", self.context_run["envelopes"])
        self.assertNotIn("atlas", self.context_run["envelopes"])
        self.assertEqual(self.context_run["effector_genes"], [])

    def test_one_nomination_prose_is_blocked(self):
        section = self.section_nine(self.context_run, NOMINATION_PROSE)
        self.assertIn(render.PENDING_REASONING, section)
        self.assertNotIn("are the effector genes this run nominates", section)

    def test_one_the_validator_says_why(self):
        findings = validate_card.validate(NOMINATION_PROSE, self.context_run)
        self.assertEqual(rules(findings), {"V7"})
        self.assertEqual(
            sorted(finding.detail.split("'")[1] for finding in findings),
            ["GCSH", "GLDC"],
        )

    def test_two_a_run_with_atlas_nominations_still_prints(self):
        self.assertEqual(
            [gene["gene_symbol"] for gene in self.nominated_run["effector_genes"]],
            ["GLDC", "CPS1", "AGXT"],
        )
        fields = {"headline": "GLDC is an effector gene this run nominates for the metabolite."}
        section = self.section_nine(self.nominated_run, fields)
        self.assertNotIn(render.PENDING_REASONING, section)
        self.assertIn("GLDC is an effector gene this run nominates", section)

    def test_three_biochemical_context_wording_still_prints(self):
        section = self.section_nine(self.context_run, BIOCHEMICAL_PROSE)
        self.assertNotIn(render.PENDING_REASONING, section)
        self.assertIn("Human-GEM reaction context", section)

    def test_section_five_and_section_nine_no_longer_contradict(self):
        """The finding as RESULTS.md states it: the accepted sentence contradicted the
        deterministic section above it."""
        section_five = "\n".join(render._section_genes_evidence(self.context_run))
        self.assertIn("The atlas nomination layer was not queried in this run", section_five)
        self.assertIn(render.PENDING_REASONING, self.section_nine(self.context_run, NOMINATION_PROSE))

    def test_the_arm_is_switched_off_and_nothing_changes_for_other_prose(self):
        without_gem = copy.deepcopy(self.context_run)
        without_gem["envelopes"].pop("gem")
        self.assertEqual(validate_card.context_only_genes(without_gem), set())


if __name__ == "__main__":
    unittest.main()
