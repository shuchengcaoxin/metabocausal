"""The colocalisation arm: partner matching, the envelope contract, and the wording the
three surfaces print.

Everything here runs offline against synthetic payloads except the two tests at the
bottom, which are the ONE live check per headline pair the build asks for and only run
with METABOCAUSAL_SLOW_TESTS=1 - the same switch the live GWAS Catalog test uses.

The matching tests are the ones that matter most. "Saturated fatty acids levels" contains
the letters of "urate" (sat-URATE-d), so a substring rule turns a fatty-acid
colocalisation into a urate one, and PubChem hands 1A "G" and "Gly" for glycine, which a
substring rule matches against most of the GWAS catalogue. Both are tested here as
NEGATIVES, because both were real behaviours of the first draft.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import pipeline
import render
import slack_app
from tools import coloc

SLOW_TESTS = os.environ.get("METABOCAUSAL_SLOW_TESTS") == "1"

ENVELOPE_KEYS = {
    "tool",
    "args",
    "source",
    "url",
    "retrieved_at",
    "status",
    "data",
    "caveats",
}


# ---------------------------------------------------------------- synthetic payloads

def study(
    identifier: str,
    trait:      str,
    cases:      int = 1000,
    samples:    int = 100000,
) -> dict:
    return {
        "id":                    identifier,
        "traitFromSource":       trait,
        "studyType":             "gwas",
        "nCases":                cases,
        "nSamples":              samples,
        "hasSumstats":           True,
        "publicationFirstAuthor": "Tester A",
        "publicationDate":       "2026-01-01",
    }


def partner(
    identifier: str,
    trait:      str,
    study_type: str = "gwas",
    gene:       str = "",
) -> dict:
    return {
        "studyLocusId": f"locus-{identifier}",
        "study": {
            "id":              identifier,
            "traitFromSource": trait,
            "studyType":       study_type,
            "target":          {"approvedSymbol": gene} if gene else None,
        },
    }


def coloc_row(
    h4:         float,
    identifier: str,
    trait:      str,
    study_type: str = "gwas",
    gene:       str = "",
) -> dict:
    return {
        "h4":                        h4,
        "h3":                        round(1 - h4, 6),
        "clpp":                      h4 / 2,
        "colocalisationMethod":      "COLOC_PIP_ECAVIAR",
        "rightStudyType":            study_type,
        "numberColocalisingVariants": 1,
        "betaRatioSignAverage":      1,
        "otherStudyLocus": partner(
            identifier,
            trait,
            study_type,
            gene,
        ),
    }


def credible_set(
    gwas_rows:  list,
    qtl_rows:   list = (),
    gwas_total: int = None,
    qtl_total:  int = None,
    position:   int = 9925343,
) -> dict:
    return {
        "studyLocusId":     f"set-{position}",
        "chromosome":       "4",
        "position":         position,
        "finemappingMethod": "SuSiE-inf",
        "confidence":       "SuSiE fine-mapped credible set",
        "variant":          {"id": f"4_{position}_T_G"},
        "colocalisation": {
            "count": len(gwas_rows) if gwas_total is None else gwas_total,
            "rows":  list(gwas_rows),
        },
        "qtl": {
            "count": len(qtl_rows) if qtl_total is None else qtl_total,
            "rows":  list(qtl_rows),
        },
    }


def fake_source(
    studies: list = None,
    sets:    list = None,
    hits:    list = None,
):
    """A stand-in for `coloc._graphql` that answers each of the three queries."""
    studies = [study("STUDY1", "Gout")] if studies is None else studies
    sets = [credible_set(hits or [])] if sets is None else sets

    def answer(
        query,
        variables,
        label,
        timeout = 60,
    ):
        if query is coloc.STUDIES_QUERY:
            index = variables["index"]
            page = studies if index == 0 else []
            return {"studies": {"count": len(studies), "rows": page}}
        if query is coloc.SEARCH_QUERY:
            return {"search": {
                "total": len(studies),
                "hits":  [{"id": row["id"], "object": dict(row, __typename="Study")}
                          for row in studies],
            }}
        if query is coloc.SETS_QUERY:
            index = variables["index"]
            page = sets if index == 0 else []
            return {"credibleSets": {"count": len(sets), "rows": page}}
        raise AssertionError(f"unexpected query in {label}")

    return answer


def run(
    metabolite = ("urate", "uric acid"),
    disease    = ("gout",),
    efo        = "MONDO_0005393",
    **kwargs,
):
    with patch.object(coloc, "SLEEP_SECONDS", 0), \
            patch.object(coloc, "_graphql", fake_source(**kwargs)):
        return coloc.get_colocalisation(
            list(metabolite),
            list(disease),
            efo,
        )


# ---------------------------------------------------------------- partner matching

class SynonymFilter(unittest.TestCase):

    def test_short_synonyms_are_dropped_and_reported(self):
        needles, dropped = coloc.usable_synonyms(["glycine", "G", "Gly", "Glycin"])
        self.assertEqual(needles, ["glycine", "glycin"])
        self.assertEqual(dropped, ["g", "gly"])

    def test_synonyms_are_normalized_and_deduplicated(self):
        needles, _dropped = coloc.usable_synonyms(["Urate", "  urate ", "URIC ACID"])
        self.assertEqual(needles, ["urate", "uric acid"])

    def test_blank_and_none_are_ignored(self):
        needles, dropped = coloc.usable_synonyms(["", None, "  ", "urate"])
        self.assertEqual(needles, ["urate"])
        self.assertEqual(dropped, [])


class PartnerMatching(unittest.TestCase):

    NEEDLES = ["urate", "uric acid"]

    def match(self, trait):
        return coloc.match_metabolite(trait, self.NEEDLES)

    def test_levels_shapes_match(self):
        self.assertEqual(self.match("Urate levels"), "urate")
        self.assertEqual(self.match("Serum urate levels"), "urate")
        self.assertEqual(self.match("Uric acid levels"), "uric acid")

    def test_whole_word_inside_a_longer_trait_matches(self):
        self.assertEqual(
            self.match("Metabolite levels (urate; cmh_urate; Uric_acid)"),
            "urate",
        )
        self.assertEqual(
            self.match("Urate levels (UKB data field 30880)"),
            "urate",
        )

    def test_substring_inside_another_word_does_not_match(self):
        # sat-URATE-d. This is the whole reason the boundary rule exists.
        self.assertEqual(self.match("Saturated fatty acids levels"), "")
        self.assertEqual(self.match("Monounsaturated fatty acid levels"), "")

    def test_glycine_does_not_match_a_conjugate(self):
        self.assertEqual(coloc.match_metabolite("Glycine levels", ["glycine"]), "glycine")
        self.assertEqual(coloc.match_metabolite("N-acetylglycine levels", ["glycine"]), "")
        self.assertEqual(coloc.match_metabolite("N-acetyl-glycine levels", ["glycine"]), "")

    def test_ratio_is_not_either_component(self):
        for trait in ("Glycine to alanine ratio", "Glycine/alanine", "Ratio of glycine to alanine"):
            self.assertEqual(coloc.match_metabolite(trait, ["glycine"]), "")
        self.assertEqual(coloc.match_metabolite("Glycine/alanine levels", ["glycine/alanine"]),
                         "glycine/alanine")
        lipid = "phosphatidylcholine (18:2/18:2)"
        self.assertEqual(coloc.match_metabolite(f"plasma {lipid} levels", [lipid]), lipid)

    def test_hyphen_and_bracket_are_word_boundaries(self):
        self.assertEqual(coloc.match_metabolite("Glycine-levels", ["glycine"]), "glycine")
        self.assertEqual(coloc.match_metabolite("TMAO (plasma)", ["tmao"]), "tmao")

    def test_a_synonym_with_regex_characters_is_a_literal(self):
        self.assertEqual(coloc.match_metabolite("Me3N(+)O(-) levels", ["me3n(+)o(-)"]),
                         "me3n(+)o(-)")
        self.assertEqual(coloc.match_metabolite("anything at all", ["u.ate"]), "")

    def test_empty_inputs_match_nothing(self):
        self.assertEqual(coloc.match_metabolite("", self.NEEDLES), "")
        self.assertEqual(coloc.match_metabolite("Urate levels", []), "")


class QtlClassification(unittest.TestCase):

    def test_molecular_qtl_types(self):
        for value in ("eqtl", "pqtl", "sqtl", "tuqtl", "sceqtl", "SCPQTL", " scsqtl "):
            self.assertTrue(coloc.is_qtl(value), value)

    def test_gwas_is_not_a_qtl(self):
        for value in ("gwas", "", None, "GWAS"):
            self.assertFalse(coloc.is_qtl(value), value)


class Flattening(unittest.TestCase):

    def test_partner_fields_survive_a_null_target(self):
        flat = coloc._partner(coloc_row(0.9, "GCST1", "Urate levels"))
        self.assertEqual(flat["partner_study_id"], "GCST1")
        self.assertEqual(flat["partner_trait"], "Urate levels")
        self.assertIsNone(flat["gene_symbol"])

    def test_hit_carries_the_locus_and_the_posteriors(self):
        hit = coloc._hit(
            "STUDY1",
            credible_set([]),
            coloc_row(0.91, "GCST1", "Glycine levels"),
        )
        self.assertEqual(hit["locus_study_id"], "STUDY1")
        self.assertEqual(hit["chromosome"], "4")
        self.assertEqual(hit["position"], 9925343)
        self.assertEqual(hit["variant_id"], "4_9925343_T_G")
        self.assertEqual(hit["h4"], 0.91)
        self.assertEqual(hit["method"], "COLOC_PIP_ECAVIAR")
        self.assertEqual(hit["n_coloc_variants"], 1)


# ---------------------------------------------------------------- the envelope

class Envelope(unittest.TestCase):

    def test_ok_when_a_metabolite_partner_matches(self):
        env = run(hits=[
            coloc_row(0.87, "GCST_A", "Urate levels"),
            coloc_row(0.99, "GCST_B", "Serum urate levels"),
            coloc_row(1.00, "GCST_C", "Saturated fatty acids levels"),
        ])
        self.assertEqual(set(env), ENVELOPE_KEYS)
        self.assertEqual(env["status"], "ok")
        self.assertEqual(env["tool"], "get_colocalisation")
        data = env["data"]
        self.assertEqual(data["n_metabolite_hits"], 2)
        self.assertEqual(data["best_h4"], 0.99)
        # Strongest H4 first, and the fatty-acid row is not in the list at all.
        self.assertEqual([hit["partner_study_id"] for hit in data["metabolite_hits"]],
                         ["GCST_B", "GCST_A"])

    def test_qtl_partners_come_from_the_aliased_list_and_keep_their_gene(self):
        env = run(sets=[credible_set(
            [coloc_row(0.95, "GCST_A", "Urate levels")],
            [coloc_row(0.99, "eqtl_study", "ENSG000001", "eqtl", "SLC2A9"),
             coloc_row(0.40, "pqtl_study", "PROT", "pqtl", "ABCG2")],
        )])
        data = env["data"]
        self.assertEqual(data["n_qtl_hits"], 2)
        self.assertEqual(data["genes"], ["SLC2A9", "ABCG2"])
        self.assertEqual(data["qtl_hits"][0]["gene_symbol"], "SLC2A9")
        self.assertEqual(data["qtl_hits"][0]["right_study_type"], "eqtl")
        self.assertEqual(data["best_qtl_h4"], 0.99)
        # A QTL partner is never also counted as a metabolite partner.
        self.assertEqual(data["n_metabolite_hits"], 1)

    def test_empty_when_nothing_matches_and_the_caveat_names_the_studies(self):
        env = run(hits=[coloc_row(0.99, "GCST_X", "Body mass index")])
        self.assertEqual(env["status"], "empty")
        self.assertEqual(env["data"]["n_metabolite_hits"], 0)
        self.assertIsNone(env["data"]["best_h4"])
        text = " ".join(env["caveats"])
        self.assertIn("STUDY1", text)
        self.assertIn("NOT evidence against a shared causal variant", text)

    def test_empty_when_the_disease_resolves_to_no_study(self):
        env = run(studies=[], disease=())
        self.assertEqual(env["status"], "empty")
        self.assertEqual(env["data"]["studies_searched"], [])
        self.assertIn(
            "resolution gap",
            " ".join(env["caveats"]),
        )

    def test_mandatory_caveats_are_always_present(self):
        for env in (run(hits=[coloc_row(0.99, "GCST_A", "Urate levels")]),
                    run(hits=[]),
                    run(studies=[])):
            text = " ".join(env["caveats"])
            self.assertIn("RETRIEVED from Open Targets, not computed here", text)
            self.assertIn("posterior probability of one shared causal variant", text)
            self.assertIn("three-way", text)

    def test_caps_are_declared_in_the_data_and_the_caveats(self):
        env = run(
            studies = [study(f"STUDY{n}", "Gout", cases=n) for n in range(1, 9)],
            sets    = [credible_set(
                [coloc_row(0.99, "GCST_A", "Urate levels")],
                gwas_total = 4424,
            )],
        )
        data = env["data"]
        self.assertEqual(data["caps"]["max_studies"], 4)
        self.assertEqual(data["caps"]["max_sets"], 60)
        self.assertEqual(data["caps"]["coloc_rows_per_set"], coloc.COLOC_PAGE)
        self.assertEqual(len(data["studies_searched"]), 4)
        # Ranked by nCases, largest first.
        self.assertEqual(data["studies_searched"][0]["id"], "STUDY8")
        text = " ".join(env["caveats"])
        self.assertIn("8 disease study(ies) are mapped to this disease", text)
        # One set per study, each claiming 4,424 partners of which 100 may be read.
        self.assertIn(f"more GWAS colocalisation partners than the {coloc.COLOC_PAGE} "
                      f"read per set", text)
        self.assertIn(str(4 * 4424), text)

    def test_hits_are_capped_and_the_count_stays_the_total(self):
        env = run(hits=[
            coloc_row(0.5 + n / 1000, f"GCST_{n}", "Urate levels")
            for n in range(coloc.MAX_HITS + 7)
        ])
        data = env["data"]
        self.assertEqual(data["n_metabolite_hits"], coloc.MAX_HITS + 7)
        self.assertEqual(len(data["metabolite_hits"]), coloc.MAX_HITS)
        self.assertIn("The count, not the list, is the total.", " ".join(env["caveats"]))

    def test_short_synonyms_are_reported_and_never_matched(self):
        env = run(
            metabolite = ("glycine", "G", "Gly"),
            hits       = [coloc_row(0.99, "GCST_G", "Gout severity in G population")],
        )
        self.assertEqual(env["data"]["dropped_synonyms"], ["g", "gly"])
        self.assertEqual(env["data"]["n_metabolite_hits"], 0)
        self.assertIn("shorter than 4 characters were dropped", " ".join(env["caveats"]))

    def test_no_metabolite_synonym_says_so(self):
        env = run(metabolite=(), hits=[coloc_row(0.99, "GCST_A", "Urate levels")])
        self.assertEqual(env["data"]["n_metabolite_hits"], 0)
        self.assertIn("empty by construction, not by retrieval", " ".join(env["caveats"]))

    def test_the_trait_search_is_used_when_the_ontology_id_maps_to_nothing(self):
        calls = []
        answer = fake_source(
            studies = [study("STUDY1", "Gout")],
            hits    = [coloc_row(0.99, "GCST_A", "Urate levels")],
        )

        def watched(query, variables, label, timeout=60):
            calls.append(label)
            if query is coloc.STUDIES_QUERY:
                return {"studies": {"count": 0, "rows": []}}
            return answer(query, variables, label, timeout)

        with patch.object(coloc, "SLEEP_SECONDS", 0), \
                patch.object(coloc, "_graphql", watched):
            env = coloc.get_colocalisation(
                ["urate"],
                ["gout"],
                "MONDO_0005393",
            )
        self.assertEqual(env["status"], "ok")
        self.assertTrue(any(label.startswith("search(") for label in calls))
        self.assertIn("mapped to no study", " ".join(env["caveats"]))

    def test_ontology_id_is_folded_to_underscore_form(self):
        seen = {}
        answer = fake_source(hits=[coloc_row(0.99, "GCST_A", "Urate levels")])

        def watched(query, variables, label, timeout=60):
            if query is coloc.STUDIES_QUERY:
                seen["diseaseIds"] = variables["diseaseIds"]
            return answer(query, variables, label, timeout)

        with patch.object(coloc, "SLEEP_SECONDS", 0), \
                patch.object(coloc, "_graphql", watched):
            coloc.get_colocalisation(
                ["urate"],
                ["gout"],
                "MONDO:0005393",
            )
        self.assertEqual(seen["diseaseIds"], ["MONDO_0005393"])

    def test_a_failed_request_is_an_error_envelope_and_never_an_exception(self):
        def boom(query, variables, label, timeout=60):
            raise coloc._GraphQLFailed(f"{label}: the endpoint fell over")

        with patch.object(coloc, "SLEEP_SECONDS", 0), patch.object(coloc, "_graphql", boom):
            env = coloc.get_colocalisation(
                ["urate"],
                ["gout"],
                "MONDO_0005393",
            )
        self.assertEqual(set(env), ENVELOPE_KEYS)
        self.assertEqual(env["status"], "error")
        self.assertIn("the endpoint fell over", env["data"]["error"])
        self.assertIn("Treat it as no information", " ".join(env["caveats"]))

    def test_an_unexpected_exception_is_also_an_error_envelope(self):
        def boom(query, variables, label, timeout=60):
            raise ZeroDivisionError("not a network problem")

        with patch.object(coloc, "SLEEP_SECONDS", 0), patch.object(coloc, "_graphql", boom):
            env = coloc.get_colocalisation(
                ["urate"],
                ["gout"],
                "MONDO_0005393",
            )
        self.assertEqual(env["status"], "error")
        self.assertIn("ZeroDivisionError", env["data"]["error"])

    def test_a_too_expensive_refusal_degrades_to_smaller_pages(self):
        answer = fake_source(hits=[coloc_row(0.99, "GCST_A", "Urate levels")])
        sizes = []

        def watched(query, variables, label, timeout=60):
            if query is coloc.SETS_QUERY:
                sizes.append(variables["size"])
                if variables["size"] == coloc.PAGE_LADDER[0][0]:
                    raise coloc._GraphQLFailed(
                        "Query is too expensive. The response size is likely to be too "
                        "large",
                        expensive = True,
                    )
            return answer(query, variables, label, timeout)

        with patch.object(coloc, "SLEEP_SECONDS", 0), \
                patch.object(coloc, "_graphql", watched):
            env = coloc.get_colocalisation(
                ["urate"],
                ["gout"],
                "MONDO_0005393",
            )
        self.assertEqual(env["status"], "ok")
        self.assertEqual(sizes[0], coloc.PAGE_LADDER[0][0])
        self.assertEqual(sizes[1], coloc.PAGE_LADDER[1][0])
        self.assertIn("too expensive", " ".join(env["caveats"]))

    def test_the_tool_records_itself_exactly_once(self):
        recorded = []
        with patch.object(coloc.ledger, "record", recorded.append):
            run(hits=[coloc_row(0.99, "GCST_A", "Urate levels")])
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["tool"], "get_colocalisation")


class GeneFilter(unittest.TestCase):

    def test_get_coloc_for_gene_is_a_pure_filter_over_an_envelope(self):
        env = run(sets=[credible_set(
            [],
            [coloc_row(0.99, "eqtl_a", "ENSG1", "eqtl", "SLC2A9"),
             coloc_row(0.55, "eqtl_b", "ENSG2", "eqtl", "SLC2A9"),
             coloc_row(0.98, "pqtl_a", "PROT", "pqtl", "ABCG2")],
        )])
        with patch.object(coloc, "_graphql", side_effect=AssertionError("no request")):
            found = coloc.get_coloc_for_gene(
                "SLC2A9",
                coloc_envelope = env,
            )
        self.assertTrue(found["from_envelope"])
        self.assertEqual(found["n_hits"], 2)
        self.assertEqual(found["best_h4"], 0.99)
        self.assertEqual({hit["gene_symbol"] for hit in found["hits"]}, {"SLC2A9"})

    def test_a_gene_with_no_retrieved_row_comes_back_empty(self):
        env = run(sets=[credible_set([], [])])
        found = coloc.get_coloc_for_gene(
            "SLC2A9",
            coloc_envelope = env,
        )
        self.assertEqual(found["hits"], [])
        self.assertIsNone(found["best_h4"])


# ---------------------------------------------------------------- the surfaces

def result_with(
    envelope,
    state = "A",
    **extra,
):
    base = {
        "state":            state,
        "reason":           f"State {state}: the classifier's own sentence.",
        "metabolite":       {"query": "urate", "label": "urate", "id": "CHEBI:17775",
                             "synonyms": ["urate"], "resolved": True, "resolved_from": "s"},
        "disease":          {"query": "gout", "label": "gout", "id": "MONDO:0005393",
                             "synonyms": ["gout"], "resolved": True, "resolved_from": "s"},
        "envelopes":        {} if envelope is None else {"coloc": envelope},
        "coloc_summary":    pipeline.coloc_summary(envelope),
        "effector_genes":   [],
        "ledger_path":      "cards/urate_gout.ledger.jsonl",
        "n_ledger_entries": 4,
        "notes":            [],
    }
    base.update(extra)
    return base


class RenderQualifier(unittest.TestCase):

    def test_state_a_reads_as_corroboration(self):
        env = run(hits=[coloc_row(0.999, "GCST000818", "Urate levels")])
        line = render._coloc_qualifier(result_with(env, "A"))
        self.assertIn("Retrieved colocalisation assessment", line)
        self.assertIn("H4 = 0.9990", line)
        self.assertIn("COLOC_PIP_ECAVIAR", line)
        self.assertIn("chr4:9925343", line)
        self.assertIn("did not move the state", line)

    def test_state_b_says_the_estimate_was_never_computed(self):
        env = run(
            metabolite = ("glycine",),
            hits       = [coloc_row(0.9159, "GCST90497315", "Glycine levels")],
        )
        line = render._coloc_qualifier(result_with(env, "B"))
        self.assertIn("chr4:9925343", line)
        self.assertIn("H4 = 0.9159", line)
        self.assertIn("No MR estimate was retrieved in this run", line)

    def test_nothing_retrieved_is_not_a_negative_result(self):
        env = run(hits=[coloc_row(0.99, "GCST_X", "Body mass index")])
        line = render._coloc_qualifier(result_with(env, "A"))
        self.assertIn("none retrieved for this pair in Open Targets", line)
        self.assertIn("not evidence against a shared causal variant", line)

    def test_an_arm_that_never_ran_says_so(self):
        line = render._coloc_qualifier(result_with(None))
        self.assertIn("not queried in this run", line)

    def test_a_failed_request_is_not_an_absent_colocalisation(self):
        line = render._coloc_qualifier(result_with(
            {"status": "error", "data": {"error": "HTTP 500"}, "caveats": []},
        ))
        self.assertIn("the request failed", line)
        self.assertIn("not an absent colocalisation", line)

    def test_the_qualifier_reaches_the_verdict_line(self):
        env = run(hits=[coloc_row(0.999, "GCST000818", "Urate levels")])
        text = "\n".join(render._section_verdict(result_with(env, "A")))
        self.assertIn("**Verdict: State A - retrieved MR.**", text)
        self.assertIn("Retrieved colocalisation assessment", text)
        self.assertIn("evidence QUALIFIER", text)

    def test_the_card_carries_the_block_and_the_table(self):
        env = run(hits=[coloc_row(0.999, "GCST000818", "Urate levels")])
        card = render.render_card(result_with(env, "A"))
        self.assertIn("**Retrieved colocalisation (Open Targets)**", card)
        self.assertIn("| Locus | H4 | H3 | CLPP | Method |", card)
        self.assertIn("chr4:9925343 (4_9925343_T_G)", card)
        self.assertIn("GCST000818", card)
        self.assertIn("Disease study(ies) searched", card)
        # And the arm's own caveats reach section 8.
        self.assertIn("RETRIEVED from Open Targets, not computed here.", card)

    def test_the_gene_block_joins_qtl_hits_to_this_run_s_genes(self):
        env = run(sets=[credible_set(
            [],
            [coloc_row(0.97, "eqtl_a", "ENSG1", "eqtl", "SLC2A9")],
        )])
        result = result_with(
            env,
            "A",
            effector_genes = [{"gene_symbol": "SLC2A9"}],
        )
        text = "\n".join(render._coloc_gene_block(result))
        self.assertIn("SLC2A9", text)
        self.assertIn("Shared with this run's effector genes: SLC2A9.", text)
        self.assertIn("not a statement that the gene mediates", text)

    def test_the_dossier_line_names_the_qtl_row_or_its_absence(self):
        env = run(sets=[credible_set(
            [],
            [coloc_row(0.97, "eqtl_a", "ENSG1", "eqtl", "SLC2A9")],
        )])
        result = result_with(env, "A")
        found = "\n".join(render._coloc_gene_lines(result, "SLC2A9"))
        self.assertIn("strongest H4 = 0.9700", found)
        self.assertIn("Two-way and retrieved", found)
        missing = "\n".join(render._coloc_gene_lines(result, "ABCG2"))
        self.assertIn("no retrieved colocalisation", missing)
        self.assertIn("not evidence that none exists", missing)

    def test_the_card_never_raises_on_a_broken_envelope(self):
        card = render.render_card(result_with({"status": "ok", "data": None}))
        self.assertIn("MetaboCausal evidence card", card)


class SlackWording(unittest.TestCase):

    def test_the_field_carries_the_retrieved_h4(self):
        env = run(hits=[coloc_row(0.999, "GCST000818", "Urate levels")])
        line = slack_app._coloc_line(env)
        self.assertTrue(line.startswith("colocalisation: H4 0.9990 (retrieved)"))
        self.assertIn("GCST000818", line)

    def test_empty_and_error_and_absent_read_differently(self):
        self.assertIn("not queried in this run", slack_app._coloc_line(None))
        self.assertIn(
            "none retrieved",
            slack_app._coloc_line({"status": "empty", "data": {"metabolite_hits": []}}),
        )
        self.assertIn(
            "no information, not an absent colocalisation",
            slack_app._coloc_line({"status": "error", "data": {}}),
        )

    def test_the_summary_has_a_colocalisation_field(self):
        env = run(hits=[coloc_row(0.999, "GCST000818", "Urate levels")])
        blocks = slack_app.build_blocks(result_with(env, "A"))
        fields = blocks[2]["fields"]
        titles = [field["text"].split("\n")[0] for field in fields]
        self.assertIn("*Colocalisation*", titles)
        self.assertLessEqual(len(fields), slack_app.MAX_FIELDS)
        body = fields[titles.index("*Colocalisation*")]["text"]
        self.assertIn("H4 0.9990 (retrieved)", body)

    def test_the_thread_card_and_the_evidence_card_quote_one_number(self):
        env = run(hits=[coloc_row(0.9158816469902322, "GCST90497315", "Urate levels")])
        result = result_with(env, "A")
        self.assertIn("H4 0.9159", slack_app.format_card(result))
        self.assertIn("H4 = 0.9159", render._coloc_qualifier(result))


class PipelineSummary(unittest.TestCase):

    def test_summary_digests_the_envelope(self):
        env = run(sets=[credible_set(
            [coloc_row(0.99, "GCST_A", "Urate levels")],
            [coloc_row(0.97, "eqtl_a", "ENSG1", "eqtl", "SLC2A9")],
        )])
        summary = pipeline.coloc_summary(env)
        self.assertEqual(summary["best_h4"], 0.99)
        self.assertEqual(summary["n_metabolite_hits"], 1)
        self.assertEqual(summary["n_qtl_hits"], 1)
        self.assertEqual(summary["genes"], ["SLC2A9"])

    def test_an_absent_or_broken_envelope_digests_to_zeros(self):
        for value in (None, {}, {"data": None}, "not an envelope"):
            summary = pipeline.coloc_summary(value)
            self.assertIsNone(summary["best_h4"])
            self.assertEqual(summary["n_metabolite_hits"], 0)
            self.assertEqual(summary["genes"], [])


# ---------------------------------------------------------------- live (one per pair)

@unittest.skipUnless(
    SLOW_TESTS,
    "set METABOCAUSAL_SLOW_TESTS=1 (each pair costs ~15 s against the live API)",
)
class LiveHeadlinePairs(unittest.TestCase):
    """The two pairs the demo rests on, retrieved for real. Each asserts only what the
    build claims: a metabolite colocalisation exists with H4 > 0.8."""

    def assert_pair(
        self,
        metabolite,
        disease,
        efo,
    ):
        env = coloc.get_colocalisation(
            metabolite,
            disease,
            efo,
        )
        self.assertEqual(env["status"], "ok", env["data"].get("error"))
        hits = env["data"]["metabolite_hits"]
        self.assertTrue(hits, "no metabolite colocalisation was retrieved")
        self.assertGreater(env["data"]["best_h4"], 0.8)
        self.assertGreater(hits[0]["h4"], 0.8)
        self.assertTrue(hits[0]["method"])
        self.assertTrue(hits[0]["partner_study_id"])
        self.assertTrue(env["data"]["studies_searched"])
        return env

    def test_urate_gout(self):
        env = self.assert_pair(
            ["urate", "uric acid"],
            ["gout"],
            "MONDO_0005393",
        )
        traits = {hit["partner_trait"].casefold() for hit in env["data"]["metabolite_hits"]}
        self.assertTrue(
            any("urate" in trait or "uric acid" in trait for trait in traits),
            traits,
        )

    def test_glycine_coronary_artery_disease(self):
        env = self.assert_pair(
            ["glycine"],
            ["coronary artery disease", "coronary heart disease"],
            "MONDO_0005010",
        )
        traits = {hit["partner_trait"].casefold() for hit in env["data"]["metabolite_hits"]}
        self.assertTrue(any("glycine" in trait for trait in traits), traits)


if __name__ == "__main__":
    unittest.main(verbosity=2)
