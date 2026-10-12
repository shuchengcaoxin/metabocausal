"""1A: id resolution.

Jingrui's acceptance cases are ported first, class by class, so her contract stays the
contract; the regression classes after them pin each fix from
team-admin/1A_审查发现_2026-09-10.md to a test that fails without it.

Most of the file is offline. The live classes at the end are the ones whose whole point
is that OLS4 really answers this way - metabolic syndrome, L-carnitine and the HP third
class are all cases where a hand-written stub would just re-assert the bug. The live set
is deliberately small: about ten requests, well under a minute.
"""

import http.client
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import _common, _ids_disease, _ids_metabolite
from tools._ids_disease import (
    downstream_synonyms,
    load_overrides,
    pick_best_match,
    resolve_disease,
)
from tools._ids_metabolite import (
    empty_result,
    lookup_pubchem,
    merge_synonyms,
    pick_metabolite_match,
    resolve_metabolite,
)
from tools.ids import resolve_ids

ENVELOPE_KEYS = [
    "tool",
    "args",
    "source",
    "url",
    "retrieved_at",
    "status",
    "data",
    "caveats",
]


def doc(
    obo_id:   str,
    label:    str,
    exact:    list | None = None,
    synonym:  list | None = None,
) -> dict:
    """One OLS4 search doc. `exact` is exact_synonyms (what id CHOICE may see); `synonym`
    is the fuller field (what the DOWNSTREAM list is built from)."""
    return {
        "obo_id":          obo_id,
        "label":           label,
        "exact_synonyms":  list(exact or []),
        "synonym":         list(synonym or []),
    }


def metabolite_result(
    status:       str = "ok",
    ambiguous:    bool = False,
    match_method: str = "exact_label",
) -> dict:
    result = empty_result("glycine", status=status)
    if status == "ok":
        result.update({
            "label":           "glycine",
            "chebi":           "CHEBI:15428",
            "pubchem_cid":     750,
            "pubchem_status":  "ok",
            "synonyms":        ["glycine", "Aminoacetic acid"],
        })
    result.update({
        "match_method": match_method,
        "ambiguous":    ambiguous,
    })
    return result


def disease_result(
    status:       str = "ok",
    ambiguous:    bool = False,
    match_method: str = "exact_label",
    identifier:   str | None = "MONDO:0005393",
) -> dict:
    result = _ids_disease._empty_disease("gout", status=status)
    if status == "ok":
        result.update({
            "label":       "gout",
            "id":          identifier,
            "entity_type": "disease",
            "synonyms":    ["gout", "gouty arthropathy"],
        })
    result.update({
        "match_method": match_method,
        "ambiguous":    ambiguous,
    })
    return result


# ---------------------------------------------------------------- ported: pick_best_match

class PickBestMatchTests(unittest.TestCase):
    """Jingrui's test_resolve_diseases.py, ported verbatim in intent."""

    def test_exact_label(self):
        result = pick_best_match(
            [doc("MONDO:0005393", "gout")],
            "GOUT",
        )
        self.assertEqual(result["match_method"], "exact_label")
        self.assertFalse(result["ambiguous"])

    def test_exact_synonym_and_mondo_preference(self):
        result = pick_best_match(
            [
                doc("HP:1", "CAD phenotype", exact=["CAD"]),
                doc("MONDO:0005010", "coronary artery disorder", exact=["CAD"]),
            ],
            "cad",
        )
        self.assertEqual(result["candidate"]["obo_id"], "MONDO:0005010")
        self.assertEqual(result["match_method"], "exact_synonym")

    def test_mondo_synonym_beats_hp_label(self):
        """Entity class is decided before match quality, so a disease term still wins
        over a phenotype record that happens to hold the word as its label."""
        result = pick_best_match(
            [
                doc("HP:0001297", "stroke"),
                doc("MONDO:0005098", "cerebrovascular disorder", exact=["stroke"]),
            ],
            "stroke",
        )
        self.assertEqual(result["candidate"]["obo_id"], "MONDO:0005098")
        self.assertEqual(result["match_method"], "exact_synonym")

    def test_obsolete_is_filtered(self):
        result = pick_best_match(
            [
                {"label": "obsolete_stroke", "obo_id": "EFO:OLD"},
                {"label": "stroke finding", "obo_id": "EFO:NEW"},
            ],
            "stroke",
        )
        self.assertEqual(result["candidate"]["obo_id"], "EFO:NEW")
        self.assertTrue(result["ambiguous"])

    def test_impaired_fasting_glucose_is_not_glucose_tolerance(self):
        result = pick_best_match(
            [doc("HP:0040270", "Impaired glucose tolerance", exact=["Glucose tolerance impairment"])],
            "impaired fasting glucose",
        )
        self.assertEqual(result["match_method"], "fallback_first")
        self.assertTrue(result["ambiguous"])


# ---------------------------------------------------------------- ported: metabolite half

class PickMetaboliteMatchTests(unittest.TestCase):
    """Jingrui's test_resolve_metabolites.py, ported."""

    def test_exact_label(self):
        result = pick_metabolite_match(
            [doc("CHEBI:15428", "glycine")],
            "Glycine",
        )
        self.assertEqual(result["candidate"]["obo_id"], "CHEBI:15428")
        self.assertEqual(result["match_method"], "exact_label")
        self.assertFalse(result["ambiguous"])

    def test_exact_synonym(self):
        result = pick_metabolite_match(
            [doc("CHEBI:16977", "L-alanine", exact=["L Alanine"])],
            "L Alanine",
        )
        self.assertEqual(result["match_method"], "exact_synonym")
        self.assertFalse(result["ambiguous"])

    def test_fallback_is_ambiguous(self):
        result = pick_metabolite_match(
            [doc("CHEBI:1", "related compound")],
            "unknown",
        )
        self.assertEqual(result["match_method"], "fallback_first")
        self.assertTrue(result["ambiguous"])

    def test_non_chebi_and_obsolete_are_ignored(self):
        result = pick_metabolite_match(
            [
                {"label": "glycine", "obo_id": "HP:1"},
                {"label": "obsolete_g", "obo_id": "CHEBI:2"},
            ],
            "glycine",
        )
        self.assertIsNone(result)

    def test_synonyms_are_merged_case_insensitively(self):
        self.assertEqual(
            merge_synonyms(["Glycine", "Gly"], ["glycine", "aminoacetic acid"]),
            ["Glycine", "Gly", "aminoacetic acid"],
        )

    @patch("tools._ids_metabolite._pubchem_json")
    def test_pubchem_unique_cid_and_synonyms(self, pubchem_json):
        pubchem_json.side_effect = [
            {"IdentifierList": {"CID": [750]}},
            {"InformationList": {"Information": [{"CID": 750, "Synonym": ["Glycine"]}]}},
        ]
        result = lookup_pubchem("glycine")
        self.assertEqual(result["cid"], 750)
        self.assertFalse(result["ambiguous"])
        self.assertEqual(result["synonyms"], ["Glycine"])

    @patch("tools._ids_metabolite._pubchem_json")
    def test_pubchem_multiple_cids_are_flagged(self, pubchem_json):
        pubchem_json.side_effect = [
            {"IdentifierList": {"CID": [5793, 79025]}},
            {"InformationList": {"Information": [{"CID": 5793, "Synonym": ["glucose"]}]}},
        ]
        result = lookup_pubchem("glucose")
        self.assertEqual(result["cid_candidates"], [5793, 79025])
        self.assertTrue(result["ambiguous"])

    @patch("tools._ids_metabolite.lookup_pubchem")
    @patch("tools._ids_metabolite.resolve_candidates")
    def test_resolver_integrates_pubchem(self, resolve_candidates, lookup_pubchem_mock):
        """Ported with two changes: the OLS4 seam is now `resolve_candidates` (exact
        query first, relevance window second), and the user's own input is the first
        anchor of the synonym list, so 'glycine' leads it."""
        resolve_candidates.return_value = (
            [doc("CHEBI:15428", "glycine", exact=["Gly"])],
            ["https://example.invalid/ols4"],
            True,
        )
        lookup_pubchem_mock.return_value = {
            "cid":            750,
            "cid_candidates": [750],
            "synonyms":       ["Glycine", "Gly", "aminoacetic acid"],
            "ambiguous":      False,
            "status":         "ok",
            "queries":        [],
        }
        result = resolve_metabolite("glycine", overrides={})
        self.assertEqual(result["pubchem_cid"], 750)
        self.assertEqual(result["synonyms"], ["glycine", "Gly", "aminoacetic acid"])


# ---------------------------------------------------------------- ported: the envelope

class ResolveIdsAcceptanceTests(unittest.TestCase):
    """Jingrui's test_resolve_ids.py, ported. The caveat assertions moved from counting
    to naming, because the envelope now always carries the retrieved-not-computed line."""

    @patch("tools.ids.resolve_disease")
    @patch("tools.ids.resolve_metabolite")
    def test_normal_resolution_envelope(self, resolve_metabolite_mock, resolve_disease_mock):
        resolve_metabolite_mock.return_value = metabolite_result()
        resolve_disease_mock.return_value = disease_result()

        result = resolve_ids("glycine", "gout")

        self.assertEqual(list(result), ENVELOPE_KEYS)      # finding 6: eight keys, in order
        self.assertEqual(result["tool"], "resolve_ids")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["url"])
        self.assertTrue(result["retrieved_at"])
        self.assertEqual(result["data"]["metabolite"]["chebi"], "CHEBI:15428")
        self.assertEqual(result["data"]["metabolite"]["pubchem_cid"], 750)
        self.assertEqual(result["data"]["disease"]["id"], "MONDO:0005393")
        self.assertFalse([c for c in result["caveats"] if "could not be resolved" in c])

    @patch("tools.ids.resolve_disease")
    @patch("tools.ids.resolve_metabolite")
    def test_disease_override_is_preserved(self, resolve_metabolite_mock, resolve_disease_mock):
        resolve_metabolite_mock.return_value = metabolite_result()
        resolve_disease_mock.return_value = disease_result(
            match_method = "override_table",
            identifier   = "MONDO:0005010",
        )

        disease = resolve_ids("glycine", "CAD")["data"]["disease"]
        self.assertEqual(disease["id"], "MONDO:0005010")
        self.assertEqual(disease["match_method"], "override_table")
        self.assertFalse(disease["ambiguous"])

    @patch("tools.ids.resolve_disease")
    @patch("tools.ids.resolve_metabolite")
    def test_ambiguous_result_adds_caveat(self, resolve_metabolite_mock, resolve_disease_mock):
        resolve_metabolite_mock.return_value = metabolite_result(ambiguous=True)
        resolve_disease_mock.return_value = disease_result()

        result = resolve_ids("urate", "gout")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["data"]["metabolite"]["ambiguous"])
        self.assertTrue([c for c in result["caveats"] if "could not be resolved confidently" in c])

    @patch("tools.ids.resolve_disease")
    @patch("tools.ids.resolve_metabolite")
    def test_two_empty_inputs_return_empty(self, resolve_metabolite_mock, resolve_disease_mock):
        resolve_metabolite_mock.return_value = metabolite_result(
            status       = "empty",
            ambiguous    = True,
            match_method = "no_match",
        )
        resolve_disease_mock.return_value = disease_result(
            status       = "empty",
            ambiguous    = True,
            match_method = "no_match",
            identifier   = None,
        )

        result = resolve_ids("", "")
        self.assertEqual(result["status"], "empty")
        self.assertEqual(
            len([c for c in result["caveats"] if "could not be resolved confidently" in c]),
            2,
        )

    @patch("tools.ids.resolve_disease")
    @patch("tools.ids.resolve_metabolite")
    def test_upstream_error_returns_error(self, resolve_metabolite_mock, resolve_disease_mock):
        resolve_metabolite_mock.return_value = metabolite_result(
            status       = "error",
            ambiguous    = True,
            match_method = "error",
        )
        resolve_disease_mock.return_value = disease_result()

        result = resolve_ids("glycine", "gout")
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["caveats"])


# ---------------------------------------------------------------- regression: offline

class EnvelopeContractTests(unittest.TestCase):
    """Finding 6 (url + retrieved_at) and finding 17 (one empty leg is not 'ok')."""

    @patch("tools.ids.resolve_disease")
    @patch("tools.ids.resolve_metabolite")
    def test_one_empty_leg_is_not_ok(self, resolve_metabolite_mock, resolve_disease_mock):
        resolve_metabolite_mock.return_value = metabolite_result()
        resolve_disease_mock.return_value = disease_result(
            status       = "empty",
            ambiguous    = True,
            match_method = "no_match",
            identifier   = None,
        )
        self.assertEqual(resolve_ids("glycine", "zzzqqqnotarealdisease")["status"], "empty")

        resolve_metabolite_mock.return_value = metabolite_result(
            status       = "empty",
            ambiguous    = True,
            match_method = "no_match",
        )
        resolve_disease_mock.return_value = disease_result()
        self.assertEqual(resolve_ids("", "gout")["status"], "empty")

    @patch("tools.ids.resolve_disease")
    @patch("tools.ids.resolve_metabolite")
    def test_a_crashing_half_still_returns_an_envelope(self, resolve_metabolite_mock, resolve_disease_mock):
        """Finding 8's outer catch-all: whatever a resolver does, the agent loop gets an
        envelope, never a traceback."""
        resolve_metabolite_mock.side_effect = RuntimeError("boom")
        resolve_disease_mock.return_value = disease_result()

        result = resolve_ids("glycine", "gout")
        self.assertEqual(list(result), ENVELOPE_KEYS)
        self.assertEqual(result["status"], "error")
        self.assertIn("boom", result["data"]["metabolite"]["error"])
        self.assertTrue([c for c in result["caveats"] if "failed unexpectedly" in c])

    @patch("tools.ids.resolve_disease")
    @patch("tools.ids.resolve_metabolite")
    def test_thin_synonym_list_is_declared(self, resolve_metabolite_mock, resolve_disease_mock):
        """Finding 2: a resolved id with one spelling must not look like a clean answer,
        because downstream that is indistinguishable from 'no effect'."""
        thin = disease_result()
        thin["synonyms"] = ["hyperuricemia"]
        resolve_metabolite_mock.return_value = metabolite_result()
        resolve_disease_mock.return_value = thin

        caveats = resolve_ids("urate", "hyperuricemia")["caveats"]
        self.assertTrue([c for c in caveats if "thin synonym list" in c])


class SynonymRuleTests(unittest.TestCase):
    """The owner's two-use rule, and findings 5 / 11 / 12."""

    def test_related_synonym_does_not_drive_id_choice(self):
        """A term whose ONLY tie to the query is a related synonym never outranks a term
        that matches on its label, even though OLS4's exact query returned both."""
        result = pick_best_match(
            [
                doc("MONDO:0000001", "something else", synonym=["myquery", "other"]),
                doc("MONDO:0000002", "myquery", synonym=["myquery"]),
            ],
            "myquery",
            exact = True,
        )
        self.assertEqual(result["candidate"]["obo_id"], "MONDO:0000002")
        self.assertEqual(result["match_method"], "exact_label")

    def test_related_only_match_is_labelled_exact_ols4(self):
        """When nothing matches locally, OLS4's own exact verdict is kept - but under its
        own name, never promoted to 'exact_synonym'."""
        result = pick_best_match(
            [doc("CHEBI:15724", "trimethylamine N-oxide", synonym=["TMAO"])],
            "TMAO",
            exact = True,
        )
        self.assertEqual(result["match_method"], "exact_ols4")
        self.assertFalse(result["ambiguous"])

    def test_relevance_window_never_uses_related_synonyms(self):
        """Same candidate, same query, but from the relevance search: not a match at all."""
        result = pick_best_match(
            [doc("CHEBI:15724", "trimethylamine N-oxide", synonym=["TMAO"])],
            "TMAO",
            exact = False,
        )
        self.assertEqual(result["match_method"], "fallback_first")
        self.assertTrue(result["ambiguous"])

    def test_downstream_list_keeps_related_synonyms_and_drops_short_tokens(self):
        synonyms = downstream_synonyms(
            ["TG", "triglyceride"],
            ["G", "TG", "serum triglycerides", "triacylglycerol"],
        )
        self.assertEqual(synonyms[0], "TG")                # an anchor survives its length
        self.assertIn("serum triglycerides", synonyms)
        self.assertIn("triacylglycerol", synonyms)
        self.assertNotIn("G", synonyms)

    def test_input_and_label_are_always_in_the_list(self):
        """Finding 11: the ontology label was missing from its own synonym list in 24 of
        35 project diseases."""
        synonyms = downstream_synonyms(
            ["atherosclerosis", "atherosclerosis of artery"],
            [],
        )
        self.assertEqual(synonyms, ["atherosclerosis", "atherosclerosis of artery"])


class AmbiguityTests(unittest.TestCase):
    """Finding 14: two exact matches separated only by accession number is a coin flip."""

    def test_two_equal_exact_matches_are_ambiguous(self):
        result = pick_best_match(
            [
                doc("MONDO:0005010", "coronary artery disorder", exact=["CAD"]),
                doc("MONDO:0018922", "cold agglutinin disease", exact=["CAD"]),
            ],
            "CAD",
            exact = True,
        )
        self.assertTrue(result["ambiguous"])
        self.assertEqual(
            sorted(result["id_candidates"]),
            ["MONDO:0005010", "MONDO:0018922"],
        )

    def test_a_better_class_breaks_the_tie_without_ambiguity(self):
        result = pick_best_match(
            [
                doc("MONDO:0005393", "gout"),
                doc("HP:0001997", "Gout"),
            ],
            "gout",
            exact = True,
        )
        self.assertEqual(result["candidate"]["obo_id"], "MONDO:0005393")
        self.assertFalse(result["ambiguous"])


class ExactFirstTests(unittest.TestCase):
    """Finding 13: ask OLS4 to match exactly before falling back to 50 relevance rows."""

    @patch("tools._ids_disease.search_ols4")
    def test_exact_query_runs_first_and_short_circuits(self, search):
        search.return_value = ([doc("MONDO:0005010", "coronary artery disorder")], "url-1")
        candidates, urls, exact_used = _ids_disease.resolve_candidates("CAD", "efo")

        self.assertTrue(exact_used)
        self.assertEqual(search.call_count, 1)
        self.assertTrue(search.call_args.kwargs["exact"])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(urls, ["url-1"])

    @patch("tools._ids_disease.search_ols4")
    def test_relevance_search_runs_only_when_exact_finds_nothing(self, search):
        search.side_effect = [([], "url-exact"), ([doc("EFO:1", "noise")], "url-relevance")]
        candidates, urls, exact_used = _ids_disease.resolve_candidates("zzqq", "efo")

        self.assertFalse(exact_used)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(urls, ["url-exact", "url-relevance"])
        self.assertEqual(candidates[0]["obo_id"], "EFO:1")


class OverrideTableTests(unittest.TestCase):
    """Findings 1 / 4 / 9 (the table feeds the synonym list), 15 (the note is evidence),
    18 / 21 (an Excel re-save must not take the tool down)."""

    def test_reverse_index_groups_every_spelling_of_one_id(self):
        overrides, caveats = load_overrides(
            path     = _ids_disease.DEFAULT_DISEASE_OVERRIDES,
            kind     = "disease",
            id_field = "id",
        )
        self.assertEqual(caveats, [])
        row = overrides["cad"]
        self.assertEqual(row["id"], "MONDO:0005010")
        for spelling in ("CAD", "CHD", "coronary artery disease", "coronary heart disease"):
            self.assertIn(spelling, row["inputs"])
        self.assertIn("coronary heart disease", row["synonyms"])

    def test_shipped_tables_carry_a_synonym_column(self):
        for path, kind, id_field in (
            (_ids_disease.DEFAULT_DISEASE_OVERRIDES, "disease", "id"),
            (_ids_metabolite.DEFAULT_METABOLITE_OVERRIDES, "metabolite", "chebi"),
        ):
            overrides, caveats = load_overrides(path=path, kind=kind, id_field=id_field)
            self.assertEqual(caveats, [])
            self.assertTrue(overrides)
            for key, row in overrides.items():
                self.assertTrue(row["synonyms"], f"{path.name}: {key} has no synonyms column")

    def test_excel_bom_degrades_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synonyms_disease.csv"
            path.write_bytes(
                b"\xef\xbb\xbf"
                + _ids_disease.DEFAULT_DISEASE_OVERRIDES.read_bytes()
            )
            overrides, caveats = load_overrides(path=path, kind="disease", id_field="id")
            self.assertEqual(caveats, [])
            self.assertIn("cad", overrides)                # utf-8-sig reads it fine

    def test_unreadable_table_returns_a_caveat_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "not_here.csv"
            overrides, caveats = load_overrides(path=missing, kind="disease", id_field="id")
            self.assertEqual(overrides, {})
            self.assertTrue(caveats)
            self.assertIn("not_here.csv", caveats[0])

            broken = Path(folder) / "broken.csv"
            broken.write_text("wrong_header,another\na,b\n", encoding="utf-8")
            overrides, caveats = load_overrides(path=broken, kind="disease", id_field="id")
            self.assertEqual(overrides, {})
            self.assertIn("broken.csv", caveats[0])

    def test_provisional_note_forces_ambiguous_and_reaches_the_card(self):
        overrides = {
            "urate": {
                "chebi":    "CHEBI:46818",
                "label":    "urate anion",
                "synonyms": ["urate anion"],
                "inputs":   ["urate"],
                "note":     "PROVISIONAL: confirm whether the project expects urate(1-) or uric acid",
            }
        }
        with patch("tools._ids_metabolite.term_ols4", return_value=(None, "url")), \
             patch("tools._ids_metabolite.lookup_pubchem") as pubchem:
            pubchem.return_value = {
                "cid": 1175, "cid_candidates": [1175], "synonyms": [],
                "ambiguous": False, "status": "ok", "queries": [],
            }
            result = resolve_metabolite("urate", overrides=overrides)

        self.assertTrue(result["ambiguous"])
        self.assertIn("PROVISIONAL", result["note"])
        self.assertTrue([c for c in result["caveats"] if "PROVISIONAL" in c])


class PubchemDegradationTests(unittest.TestCase):
    """Finding 7: an outage used to arrive as a confident success with five synonyms."""

    def _resolve_with_pubchem_failure(self, exc):
        with patch("tools._ids_metabolite.resolve_candidates") as candidates, \
             patch("tools._ids_metabolite._pubchem_json", side_effect=exc):
            candidates.return_value = (
                [doc("CHEBI:15428", "glycine", exact=["Gly"], synonym=["Aminoacetic acid"])],
                ["url"],
                True,
            )
            return resolve_metabolite("glycine", overrides={})

    def test_pubchem_outage_is_ambiguous_and_declared(self):
        result = self._resolve_with_pubchem_failure(
            _common.RequestFailed("HTTP 503 PUGREST.ServerBusy", status_code=503)
        )
        self.assertEqual(result["pubchem_status"], "error")
        self.assertTrue(result["ambiguous"])
        self.assertTrue([c for c in result["caveats"] if "PubChem did not answer" in c])
        self.assertEqual(result["chebi"], "CHEBI:15428")   # the ChEBI half still stands
        self.assertIn("glycine", result["synonyms"])

    def test_pubchem_404_is_empty_not_an_outage(self):
        result = self._resolve_with_pubchem_failure(
            _common.RequestFailed("HTTP 404", status_code=404)
        )
        self.assertEqual(result["pubchem_status"], "empty")
        self.assertFalse(result["ambiguous"])
        self.assertTrue([c for c in result["caveats"] if "holds no CID" in c])

    def test_pubchem_status_is_present_on_every_path(self):
        self.assertIn("pubchem_status", empty_result("x"))
        self.assertIn("pubchem_status", empty_result("x", status="error"))

    @patch("tools._ids_metabolite.lookup_pubchem")
    @patch("tools._ids_metabolite.resolve_candidates")
    def test_an_ols4_failure_does_not_cost_the_pubchem_half(self, candidates, pubchem):
        """Finding 22: the OLS4 error path used to return before PubChem was tried."""
        candidates.side_effect = _common.RequestFailed("OLS4 down", status_code=500)
        pubchem.return_value = {
            "cid": 750, "cid_candidates": [750], "synonyms": ["Aminoacetic acid"],
            "ambiguous": False, "status": "ok", "queries": [],
        }
        result = resolve_metabolite("glycine", overrides={})

        self.assertEqual(result["status"], "error")        # the ChEBI id is genuinely missing
        self.assertEqual(result["pubchem_cid"], 750)
        self.assertIn("Aminoacetic acid", result["synonyms"])


class TransportFailureTests(unittest.TestCase):
    """Finding 8: the three exception classes that escaped the old tuple. All requests go
    through `_common.get_json` now, which normalizes them to RequestFailed - the tuple is
    kept wide anyway, because a resolver that raises ends the demo."""

    ESCAPEES = (
        http.client.RemoteDisconnected("Remote end closed connection without response"),
        http.client.IncompleteRead(b"43 bytes"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        ConnectionResetError("connection reset by peer"),
        _common.RequestFailed("HTTP 500", status_code=500),
    )

    def test_no_transport_failure_escapes_the_disease_resolver(self):
        for exc in self.ESCAPEES:
            with self.subTest(exc=type(exc).__name__):
                with patch("tools._ids_disease.search_ols4", side_effect=exc):
                    result = resolve_disease("gout", overrides={})
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["match_method"], "error")
                self.assertIn(type(exc).__name__, result["error"])

    def test_no_transport_failure_escapes_the_metabolite_resolver(self):
        for exc in self.ESCAPEES:
            with self.subTest(exc=type(exc).__name__):
                with patch("tools._ids_metabolite.resolve_candidates", side_effect=exc), \
                     patch("tools._ids_metabolite._pubchem_json", side_effect=exc):
                    result = resolve_metabolite("glycine", overrides={})
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["pubchem_status"], "error")
                self.assertTrue([c for c in result["caveats"] if "PubChem did not answer" in c])


# ---------------------------------------------------------------- regression: live OLS4

class LiveResolutionTests(unittest.TestCase):
    """These hit OLS4 and PubChem. They are the cases where the bug was in what the API
    actually returns, so a stub would only re-assert the mistake."""

    def test_metabolic_syndrome_is_the_common_trait(self):
        """Finding 3 / 10: match quality outranks the MONDO prefix, so the rank-1 exact
        LABEL hit wins instead of the rare inherited lipodystrophy MONDO:0000816."""
        result = resolve_disease("metabolic syndrome")
        self.assertEqual(result["id"], "EFO:0000195")
        self.assertEqual(result["match_method"], "exact_label")
        self.assertFalse(result["ambiguous"])
        self.assertIn("mets", result["synonyms_normalized"])

    def test_l_carnitine_resolves_to_the_real_metabolite(self):
        """Finding 5 / 13: 'L-carnitine' is in CHEBI:16347's `synonym` field but not its
        exact_synonyms, so only the server-side exact query finds it - and the spelling
        the user typed comes back in the downstream list."""
        result = resolve_metabolite("L-carnitine")
        self.assertEqual(result["chebi"], "CHEBI:16347")
        self.assertEqual(result["match_method"], "exact_ols4")
        self.assertIn("l-carnitine", result["synonyms_normalized"])
        self.assertIn("(r)-carnitine", result["synonyms_normalized"])

    def test_cad_override_emits_the_full_synonym_set(self):
        """Findings 1 / 4 / 9: the override decides the id, never how much is known."""
        result = resolve_disease("CAD")
        self.assertEqual(result["id"], "MONDO:0005010")
        self.assertEqual(result["match_method"], "override_table")
        self.assertGreaterEqual(len(result["synonyms"]), 5)
        self.assertIn("coronary heart disease", result["synonyms_normalized"])
        self.assertIn("coronary artery disease", result["synonyms_normalized"])
        self.assertIn("cad", result["synonyms_normalized"])

    def test_hyperuricemia_synonyms_are_not_empty(self):
        """Finding 2: the one project disease that used to return zero spellings."""
        result = resolve_disease("hyperuricemia")
        self.assertEqual(result["id"], "EFO:0009104")
        self.assertTrue(result["synonyms"])
        self.assertIn("hyperuricemia", result["synonyms_normalized"])

    def test_hp_is_the_accepted_third_class_and_says_so(self):
        """Owner ruling: HP is used when no MONDO/DOID/EFO term matches, and the card is
        told what it got."""
        result = resolve_disease("insulin resistance")
        self.assertEqual(result["id"], "HP:0000855")
        self.assertEqual(result["entity_type"], "phenotype")
        self.assertTrue([c for c in result["caveats"] if "not a disease entity" in c])

        env = resolve_ids("glucose", "insulin resistance")
        self.assertTrue([c for c in env["caveats"] if "not a disease entity" in c])

    def test_betaine_is_the_metabolite_not_the_surfactant(self):
        """Finding 23, shipped as the new override row."""
        result = resolve_metabolite("betaine")
        self.assertEqual(result["chebi"], "CHEBI:17750")
        self.assertEqual(result["label"], "glycine betaine")
        self.assertIn("trimethylglycine", result["synonyms_normalized"])

    def test_urate_is_uric_acid(self):
        """The PROVISIONAL row, resolved: CHEBI:17775 is the only one of the three with
        an HMDB/KEGG xref, and it agrees with the PubChem half (CID 1175)."""
        result = resolve_metabolite("urate")
        self.assertEqual(result["chebi"], "CHEBI:17775")
        self.assertEqual(result["pubchem_cid"], 1175)
        self.assertIn("urate", result["synonyms_normalized"])

    def test_live_envelope_is_the_shared_shape(self):
        env = resolve_ids("glycine", "coronary artery disease")

        self.assertEqual(list(env), ENVELOPE_KEYS)
        self.assertEqual(env["status"], "ok")
        self.assertEqual(env["args"], {"metabolite": "glycine", "disease": "coronary artery disease"})
        self.assertTrue(env["url"].startswith("https://"))
        self.assertEqual(env["data"]["metabolite"]["chebi"], "CHEBI:15428")
        self.assertEqual(env["data"]["disease"]["id"], "MONDO:0005010")
        self.assertTrue(env["data"]["queries"])
        self.assertTrue([c for c in env["caveats"] if "not inferred here" in c])


if __name__ == "__main__":
    unittest.main()
