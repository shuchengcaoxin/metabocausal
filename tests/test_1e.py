"""Synthetic responses test scientific semantics and the audit/error boundary."""

from copy import deepcopy
from functools import partial
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from tools._evidence import JsonlRecorder, recording
from tools.opentargets import get_target_disease_evidence, get_known_drugs
from tools.chembl import get_chembl_modulators
from tools.gnomad import get_gnomad_constraint
from tools.dossier import get_gene_dossier


def search(hits=None):
    return {"data": {"search": {"hits": hits if hits is not None else [
        {"id": "ENSG00000169174", "name": "PCSK9", "entity": "target"}]}}}


def target(**fields):
    return {"data": {"target": {"approvedSymbol": "PCSK9", **fields}}}


def association(disease="EFO_0001645", score=0.8):
    return {"disease": {"id": disease, "name": disease}, "score": score,
            "datatypeScores": [{"id": "genetic_association", "score": score}]}


def report(disease, phase, status, report_id="NCT_TEST"):
    return dict(id=report_id, url=None, type="CLINICAL_TRIAL", trialPhase=phase,
                trialOverallStatus=status, trialWhyStopped=None, year=None,
                source="synthetic", diseases=[dict(disease={"id": disease, "name": disease},
                                                   diseaseFromSource=disease)])


def drug_page(reports, drug=None):
    return target(drugAndClinicalCandidates={"count": 1, "rows": [dict(
        id="candidate-test", drug=drug or {"id": "CHEMBL_TEST", "name": "TEST_DRUG"},
        maxClinicalStage="PHASE_3", clinicalReports=reports)]})


def protein(symbol="PCSK9", tax_id=9606, kind="SINGLE PROTEIN", identifier="CHEMBL2929"):
    return dict(target_type=kind, tax_id=tax_id, organism="Homo sapiens",
                pref_name=symbol, target_chembl_id=identifier,
                target_components=[dict(target_component_synonyms=[
                    {"syn_type": "GENE_SYMBOL", "component_synonym": symbol}])])


def page(key, records, total=None, next_url=None):
    return {key: records, "page_meta": {"total_count": len(records) if total is None else total,
                                      "next": next_url}}


def constraint(values=None):
    return {"data": {"gene": {"gene_id": "ENSG_TEST", "symbol": "GLDC",
                             "gnomad_constraint": values}}}


class Response(BytesIO):
    status = 200

    def __init__(self, data):
        super().__init__(json.dumps(data).encode())


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.ledger = []
        self.context = recording(lambda envelope: self.ledger.append(deepcopy(envelope)))
        self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def run_tool(self, function, args, responses):
        with patch("tools._evidence.urlopen", side_effect=[
            item if isinstance(item, Exception) else Response(item) for item in responses]) as request:
            envelope = function(*args)
        self.assertEqual(set(envelope), {"tool", "args", "source", "url", "retrieved_at", "status", "data", "caveats"})
        self.assertEqual(envelope, self.ledger[-1])
        self.assertTrue(envelope["retrieved_at"].endswith("+00:00"))
        json.dumps(envelope, allow_nan=False)
        return envelope, request

    def test_exact_search_match_can_be_second(self):
        hits = [{"id": "WRONG", "name": "PCSK9L", "entity": "target"},
                {"id": "ENSG00000169174", "name": "PCSK9", "entity": "target"}]
        env, request = self.run_tool(get_target_disease_evidence, ("PCSK9", "EFO_0001645"), [
            search(hits), target(associatedDiseases={"count": 1, "rows": [association(score=0)]})])
        self.assertEqual(env["status"], "ok")
        self.assertEqual(env["data"]["target_disease"]["score"], 0)
        self.assertEqual(env["data"]["ensembl"], "ENSG00000169174")
        self.assertEqual(request.call_count, 2)

    def test_near_symbol_and_wrong_entity_are_not_accepted(self):
        for hit in [dict(id="WRONG", name="PCSK9L", entity="target"),
                    dict(id="WRONG", name="PCSK9", entity="disease")]:
            with self.subTest(hit=hit):
                env, req = self.run_tool(get_known_drugs, ("PCSK9",), [search([hit])])
                self.assertEqual(env["status"], "empty")
                self.assertEqual(req.call_count, 1)

    def test_ambiguous_exact_match_is_error(self):
        hits = [dict(id=identifier, name="PCSK9", entity="target") for identifier in ["A", "B"]]
        env, _ = self.run_tool(get_known_drugs, ("PCSK9",), [search(hits)])
        self.assertEqual(env["status"], "error")

    def test_disease_outside_page_does_not_mean_no_association(self):
        records = [association(f"EFO_{i}") for i in range(25)]
        env, _ = self.run_tool(get_target_disease_evidence, ("PCSK9", "EFO_0001645"), [
            search(), target(associatedDiseases={"count": 50, "rows": records})])
        self.assertEqual(env["status"], "empty")
        self.assertIsNone(env["data"]["target_disease"])
        self.assertEqual(len(env["data"]["top_diseases"]), 5)
        self.assertIn("page", " ".join(env["caveats"]))

    def test_clinical_reports_keep_indications_phases_nulls_and_ids(self):
        reports = [report("A", "PHASE3", "COMPLETED", "ONE"),
                   report("B", "PHASE2", "TERMINATED", "TWO"),
                   report("C", None, None, "THREE")]
        reports[1]["trialWhyStopped"] = "Funding withdrawn"
        reports[2]["type"] = "DRUG_LABEL"
        reports[2]["diseases"].append(dict(disease=None, diseaseFromSource="Unmapped disease"))
        env, req = self.run_tool(get_known_drugs, ("PCSK9",), [search(), drug_page(reports)])
        self.assertEqual(env["status"], "ok")
        actual = env["data"]["drugs"][0]["clinical_reports"]
        self.assertEqual([r["trial_phase"] for r in actual], ["PHASE3", "PHASE2", None])
        self.assertEqual([r["status"] for r in actual], ["COMPLETED", "TERMINATED", None])
        self.assertEqual(actual[1]["why_stopped"], "Funding withdrawn")
        self.assertEqual(actual[2]["diseases"], reports[2]["diseases"])
        self.assertEqual(actual[0]["report_id"], "ONE")
        self.assertEqual(actual[2]["report_type"], "DRUG_LABEL")
        query = json.loads(req.call_args.args[0].data)["query"]
        self.assertIn("drugAndClinicalCandidates", query)
        self.assertNotIn("knownDrugs", query)

    def test_unknown_drug_object_is_preserved(self):
        payload = drug_page([])
        payload["data"]["target"]["drugAndClinicalCandidates"]["rows"][0]["drug"] = None
        env, _ = self.run_tool(get_known_drugs, ("PCSK9",), [search(), payload])
        self.assertEqual(env["status"], "ok")
        self.assertIsNone(env["data"]["drugs"][0]["drug"])

    def test_empty_clinical_candidates(self):
        env, _ = self.run_tool(get_known_drugs, ("PCSK9",), [search(), target(
            drugAndClinicalCandidates={"count": 0, "rows": []})])
        self.assertEqual(env["status"], "empty")

    def test_missing_or_truncated_drug_page_is_error(self):
        for value in [{"count": 1, "rows": []}, {"count": 0}]:
            env, _ = self.run_tool(get_known_drugs, ("PCSK9",), [search(), target(drugAndClinicalCandidates=value)])
            self.assertEqual(env["status"], "error")

    def test_resolved_symbol_mismatch(self):
        payload = target(drugAndClinicalCandidates={"count": 0, "rows": []})
        payload["data"]["target"]["approvedSymbol"] = "OTHER"
        env, _ = self.run_tool(get_known_drugs, ("PCSK9",), [search(), payload])
        self.assertEqual(env["status"], "error")

    def test_chembl_filters_rna_complex_species_and_near_symbol(self):
        candidates = [protein(kind="NUCLEIC-ACID"), protein(kind="PROTEIN-PROTEIN INTERACTION"),
                      protein(tax_id=10090), protein(symbol="OTHER"), protein()]
        mechanism = {"target_chembl_id": "CHEMBL2929", "molecule_chembl_id": "TEST_MOL"}
        env, req = self.run_tool(get_chembl_modulators, ("PCSK9",), [
            page("targets", candidates), page("mechanisms", [mechanism]), page("activities", [{}], total=1234)])
        self.assertEqual(env["status"], "ok")
        self.assertEqual(env["data"]["target"]["target_chembl_id"], "CHEMBL2929")
        self.assertEqual(env["data"]["activity_count"], 1234)
        self.assertIn("limit=1", req.call_args.args[0].full_url)
        self.assertIn("not unique ligands", " ".join(env["caveats"]))

    def test_chembl_no_eligible_target_stops(self):
        env, req = self.run_tool(get_chembl_modulators, ("FAKE",), [page("targets", [protein()])])
        self.assertEqual(env["status"], "empty")
        self.assertEqual(req.call_count, 1)

    def test_chembl_zero_activities_and_no_mechanisms_is_empty(self):
        env, _ = self.run_tool(get_chembl_modulators, ("PCSK9",), [page("targets", [protein()]),
            page("mechanisms", []), page("activities", [], total=0)])
        self.assertEqual(env["status"], "empty")
        self.assertEqual(env["data"]["activity_count"], 0)

    def test_chembl_mechanism_pagination(self):
        row = {"target_chembl_id": "CHEMBL2929"}
        next_url = "/chembl/api/data/mechanism.json?target_chembl_id=CHEMBL2929&offset=1"
        env, _ = self.run_tool(get_chembl_modulators, ("PCSK9",), [page("targets", [protein()]),
            page("mechanisms", [row], total=2, next_url=next_url),
            page("mechanisms", [row], total=2), page("activities", [], total=0)])
        self.assertEqual(env["status"], "ok")
        self.assertEqual(len(env["data"]["mechanisms"]), 2)

    def test_chembl_search_pagination(self):
        env, _ = self.run_tool(get_chembl_modulators, ("PCSK9",), [
            page("targets", [protein(kind="NUCLEIC-ACID")], total=2,
                 next_url="/chembl/api/data/target/search.json?q=PCSK9&offset=1"),
            page("targets", [protein()], total=2), page("mechanisms", []), page("activities", [{}], total=1)])
        self.assertEqual(env["status"], "ok")

    def test_chembl_unexpected_pagination_host_is_error(self):
        env, req = self.run_tool(get_chembl_modulators, ("PCSK9",), [page("targets", [], total=1,
            next_url="https://other.example/steal")])
        self.assertEqual(env["status"], "error")
        self.assertEqual(req.call_count, 1)

    def test_chembl_retry_5xx_once_and_preserve_attempt(self):
        error = HTTPError("https://www.ebi.ac.uk/test", 500, "temporary", {}, BytesIO(b"down"))
        env, req = self.run_tool(get_chembl_modulators, ("PCSK9",), [error, page("targets", [])])
        self.assertEqual(env["status"], "empty")
        self.assertEqual(req.call_count, 2)
        self.assertEqual(env["data"]["provenance"][0]["http_status"], 500)
        self.assertEqual(env["data"]["provenance"][1]["attempt"], 2)

    def test_two_5xx_are_error_not_empty(self):
        errors = [HTTPError("https://www.ebi.ac.uk/test", 503, "down", {}, BytesIO()) for _ in range(2)]
        env, req = self.run_tool(get_chembl_modulators, ("PCSK9",), errors)
        self.assertEqual(env["status"], "error")
        self.assertEqual(req.call_count, 2)

    def test_429_is_error_without_retry(self):
        env, req = self.run_tool(get_chembl_modulators, ("PCSK9",), [
            HTTPError("https://www.ebi.ac.uk/test", 429, "slow down", {}, BytesIO())])
        self.assertEqual(env["status"], "error")
        self.assertEqual(req.call_count, 1)

    def test_partial_graphql_error_is_not_accepted(self):
        payload = constraint({"pli": 0, "oe_lof": 0.8, "oe_lof_upper": 1.0, "oe_mis": 1.1})
        payload["errors"] = [{"message": "partial failure"}]
        env, _ = self.run_tool(get_gnomad_constraint, ("GLDC",), [payload])
        self.assertEqual(env["status"], "error")
        self.assertIn("errors", env["data"]["provenance"][0]["response"])

    def test_null_gene_constraint_and_all_null_metrics_are_empty(self):
        for payload in [{"data": {"gene": None}}, constraint(),
                        constraint(dict(pli=None, oe_lof=None, oe_lof_upper=None, oe_mis=None))]:
            env, _ = self.run_tool(get_gnomad_constraint, ("GLDC",), [payload])
            self.assertEqual(env["status"], "empty")
            self.assertIsNone(env["data"]["loeuf"])

    def test_constraint_mapping_preserves_zero_and_partial_nulls(self):
        env, _ = self.run_tool(get_gnomad_constraint, ("GLDC",), [
            constraint(dict(pli=0, oe_lof=0.86, oe_lof_upper=1.01, oe_mis=None))])
        self.assertEqual(env["status"], "ok")
        self.assertEqual(env["data"]["pli"], 0)
        self.assertEqual(env["data"]["loeuf"], env["data"]["oe_lof_upper"])
        self.assertIsNone(env["data"]["dataset_release"])

    def test_bad_constraint_metrics_and_schema_drift_are_error(self):
        for payload in [{}, {"data": None}, constraint({}),
                        constraint(dict(pli="0", oe_lof=1, oe_lof_upper=1, oe_mis=1))]:
            env, _ = self.run_tool(get_gnomad_constraint, ("GLDC",), [payload])
            self.assertEqual(env["status"], "error")

    def test_all_public_tools_catch_network_errors_and_record_once(self):
        calls = [(get_target_disease_evidence, ("PCSK9", "EFO_0001645")),
                 (get_known_drugs, ("PCSK9",)), (get_chembl_modulators, ("PCSK9",)),
                 (get_gnomad_constraint, ("GLDC",))]
        for function, args in calls:
            for failure in [TimeoutError("timed out"), URLError("network unavailable")]:
                before = len(self.ledger)
                env, _ = self.run_tool(function, args, [failure])
                self.assertEqual(env["status"], "error")
                self.assertIn("error", env["data"])
                self.assertEqual(len(self.ledger), before + 1)

    def test_malformed_json_is_error(self):
        bad = Response({})
        bad.seek(0)
        bad.write(b"<html>bad")
        bad.seek(0)
        with patch("tools._evidence.urlopen", return_value=bad):
            env = get_gnomad_constraint("GLDC")
        self.assertEqual(env["status"], "error")

    def test_nonfinite_source_json_is_a_serializable_audited_error(self):
        for literal in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(literal=literal):
                response = Response({})
                response.seek(0)
                raw = ('{"data":{"unrelated_metadata":' + literal + '}}').encode()
                response.write(raw)
                response.truncate()
                response.seek(0)
                with patch("tools._evidence.urlopen", return_value=response):
                    env = get_gnomad_constraint("GLDC")
                self.assertEqual(env["status"], "error")
                self.assertNotIn("ledger_error", env["data"])
                self.assertEqual(env, self.ledger[-1])
                self.assertEqual(env["data"]["provenance"][0]["response_text"], raw.decode())
                json.dumps(env, allow_nan=False)

    def test_invalid_input_has_no_network_request(self):
        for args in [("",), (None,), ("   ",)]:
            env, req = self.run_tool(get_known_drugs, args, [])
            self.assertEqual(env["status"], "error")
            req.assert_not_called()

    def test_non_json_python_arguments_still_return_json_error(self):
        cycle = []
        cycle.append(cycle)
        for value in (object(), b"PCSK9", float("nan"), float("inf"), cycle):
            with self.subTest(kind=type(value).__name__):
                env, req = self.run_tool(get_known_drugs, (value,), [])
                self.assertEqual(env["status"], "error")
                self.assertEqual(env["args"]["gene_symbol"],
                                 {"invalid_python_type": type(value).__name__})
                self.assertNotIn("ledger_error", env["data"])
                req.assert_not_called()

    def test_ledger_write_failure_returns_error_without_raising(self):
        def fail(envelope):
            raise OSError("disk full")
        with recording(fail), patch("tools._evidence.urlopen", return_value=Response(search([]))):
            env = get_known_drugs("FAKE")
        self.assertEqual(env["status"], "error")
        self.assertEqual(env["data"]["retrieval_status"], "empty")
        self.assertIn("disk full", env["data"]["ledger_error"])

    def test_jsonl_and_team_stem_adapter_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.ledger.jsonl"
            recorder = JsonlRecorder(path)
            def team_record(envelope, stem):
                self.assertEqual(stem, "one")
                recorder(envelope)
            with recording(partial(team_record, stem="one")), patch(
                    "tools._evidence.urlopen", side_effect=[Response(search([])), Response(search([]))]):
                first = get_known_drugs("FAKE")
                second = get_known_drugs("FAKE")
            self.assertEqual([json.loads(line) for line in path.read_text().splitlines()], [first, second])

    def test_bundle_records_four_tools_and_summary_even_on_failure(self):
        responses = [Response(search([])), Response(search([])),
                     TimeoutError("offline"), Response({"data": {"gene": None}})]
        with patch("tools._evidence.urlopen", side_effect=responses):
            env = get_gene_dossier("FAKE", "EFO_0001645")
        self.assertEqual(len(self.ledger), 5)
        self.assertEqual(env["status"], "error")
        self.assertEqual(env["data"]["component_statuses"]["chembl"], "error")
        self.assertEqual(env["data"]["component_statuses"]["clinical"], "empty")


if __name__ == "__main__":
    unittest.main()
