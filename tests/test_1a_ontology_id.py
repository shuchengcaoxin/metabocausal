"""1A: the ontology-id fast path.

Fully offline - every OLS4 and PubChem call is patched, so this file belongs in the
offline smoke suite.

A user who types CHEBI:17775 has already made the choice this module otherwise makes for
them, so the id goes straight to the term endpoint: no override table, no search, no
relevance window to fall out of. The three properties worth pinning are that the record
still supplies the label and synonyms (an id says WHICH entity, never how much is known
about it), that the id string never becomes a trait spelling, and that a lookup failure
stays distinguishable from a scientific null.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools._ids_disease import ontology_id_shape, resolve_disease
from tools._ids_metabolite import resolve_metabolite

URL = "https://www.ebi.ac.uk/ols4/api/ontologies/efo/terms?obo_id=MONDO%3A0005393"


def term(label: str, synonyms: list | None = None) -> dict:
    """One OLS4 term record, as the terms endpoint returns it."""
    return {
        "label":           label,
        "obo_id":          "ignored - the caller already knows the id",
        "synonyms":        list(synonyms or []),
        "exact_synonyms":  list(synonyms or []),
    }


class Shape(unittest.TestCase):
    def test_canonicalises_case_and_separator(self):
        for typed in ("CHEBI:17775", "chebi:17775", "ChEBI_17775", "  CHEBI:17775  "):
            with self.subTest(typed=typed):
                self.assertEqual(ontology_id_shape(typed), "CHEBI:17775")

    def test_every_supported_prefix(self):
        for typed, expected in (
            ("MONDO:0005393", "MONDO:0005393"),
            ("DOID:13189",    "DOID:13189"),
            ("EFO:0000195",   "EFO:0000195"),
            ("HP:0001297",    "HP:0001297"),
        ):
            with self.subTest(typed=typed):
                self.assertEqual(ontology_id_shape(typed), expected)

    def test_names_are_not_ids(self):
        # A name that merely CONTAINS an id, or an unknown prefix, is still a name: the
        # fast path must not swallow anything the search would have handled correctly.
        for typed in (
            "urate",
            "gout",
            "CHEBI:17775 gout",
            "urate CHEBI:17775",
            "CHEBI:",
            "CHEBI:abc",
            "UBERON:0002107",
            "",
            None,
        ):
            with self.subTest(typed=typed):
                self.assertIsNone(ontology_id_shape(typed))


class DiseaseById(unittest.TestCase):
    def resolve(self, typed, record):
        with patch("tools._ids_disease.term_ols4", return_value=(record, URL)) as fetch, \
             patch("tools._ids_disease.search_ols4") as search, \
             patch("tools._ids_disease.load_overrides") as overrides:
            result = resolve_disease(typed)
        return result, fetch, search, overrides

    def test_resolves_and_skips_search_and_overrides(self):
        result, fetch, search, overrides = self.resolve(
            "MONDO:0005393",
            term("gout", ["gouty arthropathy", "tophaceous gout"]),
        )

        self.assertEqual(result["id"], "MONDO:0005393")
        self.assertEqual(result["label"], "gout")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["match_method"], "ontology_id")
        self.assertEqual(result["entity_type"], "disease")
        fetch.assert_called_once_with("MONDO:0005393", "efo")
        search.assert_not_called()
        overrides.assert_not_called()

    def test_ambiguous_is_false_by_construction(self):
        result, _, _, _ = self.resolve("MONDO:0005393", term("gout"))
        self.assertFalse(result["ambiguous"])
        self.assertEqual(result["id_candidates"], ["MONDO:0005393"])

    def test_record_supplies_the_synonyms_and_the_id_string_is_not_one(self):
        result, _, _, _ = self.resolve(
            "mondo_0005393",
            term("gout", ["gouty arthropathy", "tophaceous gout"]),
        )

        self.assertIn("gout", result["synonyms"])
        self.assertIn("gouty arthropathy", result["synonyms"])
        # The id is what the user typed, and it is exactly what no GWAS trait field ever
        # reads. Keeping it out is what stops the card advertising a spelling that can
        # never match anything downstream.
        self.assertNotIn("MONDO:0005393", result["synonyms"])
        self.assertNotIn("mondo_0005393", result["synonyms"])
        self.assertNotIn("mondo:0005393", result["synonyms_normalized"])

    def test_says_it_read_an_id_rather_than_a_name(self):
        result, _, _, _ = self.resolve("MONDO:0005393", term("gout"))
        self.assertTrue([c for c in result["caveats"] if "read as an ontology id" in c])

    def test_phenotype_caveat_still_fires(self):
        result, _, _, _ = self.resolve("HP:0001297", term("Stroke"))

        self.assertEqual(result["entity_type"], "phenotype")
        self.assertTrue([c for c in result["caveats"] if "HP phenotype" in c])

    def test_a_chebi_id_on_the_disease_side_is_refused(self):
        # Refused as a wrong-side id, NOT looked up in efo: a swapped pair has to read as
        # a swapped pair, not as a disease that does not exist.
        result, fetch, _, _ = self.resolve("CHEBI:17775", term("should not be fetched"))

        self.assertIsNone(result["id"])
        self.assertEqual(result["status"], "empty")
        fetch.assert_not_called()
        self.assertTrue([c for c in result["caveats"] if "not a disease identifier" in c])

    def test_unknown_id_is_a_lookup_failure_not_a_null(self):
        result, _, _, _ = self.resolve("MONDO:9999999", None)

        self.assertIsNone(result["id"])
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["queries"], [URL])
        self.assertTrue([c for c in result["caveats"] if "not an absence of evidence" in c])

    def test_network_failure_is_an_error_not_an_empty(self):
        with patch("tools._ids_disease.term_ols4", side_effect=OSError("timed out")):
            result = resolve_disease("MONDO:0005393")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["match_method"], "error")
        self.assertIn("timed out", result["error"])


class MetaboliteById(unittest.TestCase):
    def resolve(self, typed, record, pubchem=None):
        payload = pubchem if pubchem is not None else {
            "cid":            1175,
            "cid_candidates": [1175],
            "ambiguous":      False,
            "status":         "ok",
            "synonyms":       ["uric acid", "2,6,8-trioxopurine"],
            "queries":        ["https://pubchem"],
        }
        with patch("tools._ids_metabolite.term_ols4", return_value=(record, URL)) as fetch, \
             patch("tools._ids_metabolite.resolve_candidates") as search, \
             patch("tools._ids_metabolite.load_overrides") as overrides, \
             patch("tools._ids_metabolite.lookup_pubchem", return_value=payload) as pug:
            result = resolve_metabolite(typed)
        return result, fetch, search, overrides, pug

    def test_resolves_and_skips_search_and_overrides(self):
        result, fetch, search, overrides, _ = self.resolve(
            "CHEBI:17775",
            term("uric acid", ["urate", "2,6,8-trioxopurine"]),
        )

        self.assertEqual(result["chebi"], "CHEBI:17775")
        self.assertEqual(result["label"], "uric acid")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["match_method"], "ontology_id")
        self.assertFalse(result["ambiguous"])
        fetch.assert_called_once_with("CHEBI:17775", "chebi")
        search.assert_not_called()
        overrides.assert_not_called()

    def test_pubchem_is_asked_for_the_label_not_the_id(self):
        # PubChem's name endpoint knows 'uric acid'. Sending it 'CHEBI:17775' would come
        # back empty and add a caveat saying the metabolite was not found.
        _, _, _, _, pug = self.resolve("CHEBI:17775", term("uric acid"))
        pug.assert_called_once_with("uric acid")

    def test_id_string_is_not_a_synonym(self):
        result, _, _, _, _ = self.resolve(
            "chebi_17775",
            term("uric acid", ["urate"]),
        )

        self.assertIn("uric acid", result["synonyms"])
        self.assertIn("urate", result["synonyms"])
        self.assertNotIn("CHEBI:17775", result["synonyms"])
        self.assertNotIn("chebi:17775", result["synonyms_normalized"])

    def test_a_disease_id_on_the_metabolite_side_is_refused(self):
        result, fetch, _, _, pug = self.resolve("MONDO:0005393", term("never fetched"))

        self.assertIsNone(result["chebi"])
        self.assertEqual(result["status"], "empty")
        fetch.assert_not_called()
        pug.assert_not_called()
        self.assertTrue([c for c in result["caveats"] if "not a metabolite identifier" in c])

    def test_unknown_id_skips_pubchem(self):
        # No label to ask PubChem with, so the half is skipped rather than sent a query
        # that can only come back empty and add a second, misleading caveat.
        result, _, _, _, pug = self.resolve("CHEBI:9999999", None)

        self.assertIsNone(result["chebi"])
        self.assertEqual(result["status"], "empty")
        pug.assert_not_called()
        self.assertTrue([c for c in result["caveats"] if "not an absence of evidence" in c])

    def test_network_failure_is_an_error_not_an_empty(self):
        with patch("tools._ids_metabolite.term_ols4", side_effect=OSError("timed out")), \
             patch("tools._ids_metabolite.lookup_pubchem") as pug:
            result = resolve_metabolite("CHEBI:17775")

        self.assertEqual(result["status"], "error")
        self.assertIn("timed out", result["error"])
        pug.assert_not_called()


class NamePathIsUntouched(unittest.TestCase):
    """The fast path must be invisible to every input that is not an id."""

    def test_a_plain_name_still_goes_through_the_override_table_and_search(self):
        with patch("tools._ids_disease.term_ols4") as fetch, \
             patch("tools._ids_disease.load_overrides", return_value=({}, [])) as overrides, \
             patch("tools._ids_disease.resolve_candidates",
                   return_value=([], ["https://ols4"], True)) as search:
            result = resolve_disease("gout")

        overrides.assert_called_once()
        search.assert_called_once()
        fetch.assert_not_called()
        self.assertEqual(result["match_method"], "no_match")


if __name__ == "__main__":
    unittest.main()
