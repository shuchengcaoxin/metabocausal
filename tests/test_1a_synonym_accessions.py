"""1A: database cross-references never reach the synonym list.

Fully offline - every OLS4 and PubChem call is patched, so this file belongs in the
offline smoke suite.

PubChem's PUG REST synonym field is a mixture of two kinds of string: spellings of the
compound, and accessions in other databases. For uric acid it returns 137 entries and 64
of them are the second kind ('CHEBI:17775', '69-93-2', 'DTXSID3042508', 'MFCD00005712').
No GWAS trait field ever reads as an accession, so those entries can never match; and
because MAX_SYNONYMS binds - the urate list came back at exactly the cap - each one kept
was displacing a real spelling that 1B/1C could have matched on. A thin list surfaces
downstream as 'no MR evidence' rather than as a naming problem, which is the failure mode
this project exists to avoid.

The two properties pinned here are that accession-shaped strings do not reach `synonyms`
or `synonyms_normalized`, and that the filter runs BEFORE the cap, so the freed slots go
to spellings instead of being lost with the truncation.

The tables below are verbatim PubChem output, collected from the synonym lists for urate,
glycine, L-carnitine, TMAO, cholesterol, creatinine, betaine, phenylalanine, citrate and
alanine. The SPELLINGS table matters more than the ACCESSIONS one: the filter is
deliberately conservative, because a dropped spelling is an invisible miss downstream
while a kept accession only costs a slot.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import _ids_metabolite
from tools._ids_disease import is_accession
from tools._ids_metabolite import resolve_metabolite

URL = "https://www.ebi.ac.uk/ols4/api/ontologies/chebi/terms?obo_id=CHEBI%3A17775"

ACCESSIONS = [
    "CHEBI:17775", "CHEBI:46823", "CHEBI:27226",       # the three that started this
    "HMDB0000289", "LMST01010001", "C00366",           # HMDB, LIPID MAPS, KEGG
    "DTXSID3042508", "DTXCID1022508",                  # DSSTox
    "CHEMBL792", "SCHEMBL7933", "GTPL4731",
    "MFCD00005712", "NSC-3975", "NSC 3975", "NSC3975",
    "AI3-15432", "CCRIS 5915", "HSDB 495", "BRN 3537113",
    "69-93-2", "56-40-6", "CAS-107-43-7",              # CAS, bare and prefixed
    "200-720-7", "EINECS 200-720-7", "EC 200-272-2",   # EC / EINECS
    "268B43MJ25", "TE7660XO1C", "UNII-FLD0K1SJ1A",     # UNII, bare and prefixed
    "A16AA01",                                         # ATC
    "bmse000126", "orb1224199", "STL185577", "AKOS015917746",
    "NCGC00181032-01", "SDCCGMLS-0066864.P001", "KBio1_000351",
    "Spectrum2_000764", "Pharmakon1600-01600300", "AB00052404_03",
    "InChI=1/C3H9NO/c1-4(2,3)5/h1-3H3",
    "UYPYRKYUKCHHIB-UHFFFAOYSA-",                      # PubChem truncates these
    "565FF3AF-8AFA-4EE9-9FC4-6B119784A5BB",
]

SPELLINGS = [
    "uric acid", "urate", "Lithic acid", "2,6,8-trioxypurine",
    "7,9-Dihydro-1H-purine-2,6,8(3H)-trione", "1H-Purine-2,6,8-triol",
    "8-hydroxyxanthine", "Uricum acidum", "uric-acid",
    "TMAO", "TMANO", "TMA-oxide", "URC", "8HX", "CLR",  # short all-caps are NOT codes
    "C5H4N4O3", "C27H46O", "H2N-CH2-COOH", "NH2CH2COOH", "(CH3)3NO", "Me3N(+)O(-)",
    "Cholest-5-en-3beta-ol", "5:6-Cholesten-3beta-ol", "3beta-Hydroxycholest-5-ene",
    "L-Phe", "H-Gly-OH", "[14C]glycine", "L-Glycine", "Glycine [INN]",
    "Carniking 50", "Cholesterol 1551", "Nimco cholesterol base No. 712",
    "vitamin BT", "Coenzyme Q10", "PC aa C36:0", "SM C16:0", "HDL2",  # the 1B spellings
    "2-Aminoacetic acid", "Levocarnitine", "Trimethylglycine",
]


class Shape(unittest.TestCase):
    def test_accessions_are_recognised(self):
        for value in ACCESSIONS:
            with self.subTest(value=value):
                self.assertTrue(is_accession(value))

    def test_spellings_are_not(self):
        for value in SPELLINGS:
            with self.subTest(value=value):
                self.assertFalse(is_accession(value))

    def test_empty_input_is_not_an_accession(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                self.assertFalse(is_accession(value))


class ResolverDropsThem(unittest.TestCase):
    """The filter has to sit on the resolver's path, not only in a helper."""

    def resolve_by_name(self, pubchem_synonyms: list, ontology_synonyms: list = None):
        candidate = {
            "obo_id":         "CHEBI:17775",
            "label":          "uric acid",
            "synonyms":       list(ontology_synonyms or []),
            "exact_synonyms": list(ontology_synonyms or []),
        }
        with patch("tools._ids_metabolite.resolve_candidates") as candidates, \
             patch("tools._ids_metabolite.lookup_pubchem") as pubchem:
            candidates.return_value = ([candidate], ["url"], True)
            pubchem.return_value = {
                "cid":            1175,
                "cid_candidates": [1175],
                "synonyms":       list(pubchem_synonyms),
                "ambiguous":      False,
                "status":         "ok",
                "queries":        [],
            }
            return resolve_metabolite("urate", overrides={})

    def test_no_accession_reaches_the_synonym_list(self):
        result = self.resolve_by_name(["uric acid"] + ACCESSIONS + ["Lithic acid"])

        self.assertEqual(result["chebi"], "CHEBI:17775")
        self.assertIn("Lithic acid", result["synonyms"])
        self.assertEqual([s for s in result["synonyms"] if is_accession(s)], [])

    def test_no_accession_reaches_the_normalized_list(self):
        """1B matches on `synonyms_normalized`, so that is the list that must be clean."""
        result = self.resolve_by_name(["uric acid", "CHEBI:17775", "Lithic acid"])

        self.assertNotIn("chebi:17775", result["synonyms_normalized"])
        self.assertIn("lithic acid", result["synonyms_normalized"])

    def test_the_cap_spends_its_slots_on_spellings(self):
        """The point of the fix. With the cap binding, an accession kept is a spelling
        lost: before the filter ran first, 'Lithate' fell off the end of the urate list
        while three CHEBI ids sat inside it."""
        pubchem = [
            "uric acid", "CHEBI:17775", "69-93-2", "DTXSID3042508",
            "Lithate", "hypoxanthinediol",
        ]
        with patch.object(_ids_metabolite, "MAX_SYNONYMS", 3):
            result = self.resolve_by_name(pubchem)

        # Unfiltered, the same three slots would have gone to two accessions and one
        # spelling, and 'Lithate' would have been truncated away.
        self.assertEqual(result["synonyms"], ["urate", "uric acid", "Lithate"])
        # The cap still truncates, and still says so: the filter removes noise, it does
        # not hide a loss of spellings.
        self.assertTrue([c for c in result["caveats"] if "truncated" in c])

    def test_the_ontology_id_path_is_filtered_too(self):
        """`resolve_metabolite('CHEBI:17775')` skips the search but still runs the
        PubChem half, so it needs the same filter - and it was equally polluted."""
        record = {
            "label":          "uric acid",
            "obo_id":         "CHEBI:17775",
            "synonyms":       ["Urate"],
            "exact_synonyms": ["Urate"],
        }
        with patch("tools._ids_metabolite.term_ols4", return_value=(record, URL)), \
             patch("tools._ids_metabolite.lookup_pubchem") as pubchem:
            pubchem.return_value = {
                "cid":            1175,
                "cid_candidates": [1175],
                "synonyms":       ["Lithic acid"] + ACCESSIONS,
                "ambiguous":      False,
                "status":         "ok",
                "queries":        [],
            }
            result = resolve_metabolite("CHEBI:17775")

        self.assertEqual(result["match_method"], "ontology_id")
        self.assertIn("Lithic acid", result["synonyms"])
        self.assertEqual([s for s in result["synonyms"] if is_accession(s)], [])


if __name__ == "__main__":
    unittest.main()
