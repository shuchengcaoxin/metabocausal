"""Source-backed examples plus explicitly synthetic edge cases. Entirely offline."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from MVP3.src import build_index, common, fetch_model, gem
from MVP3.src.gpr import gene_members, parse_gpr
from MVP3.tests.fixtures.synthetic import fixture

SOURCE_FIXTURE = Path(__file__).parent / "fixtures/gem/source_excerpt.json"
ENVELOPE_KEYS = {"tool", "args", "source", "url", "retrieved_at", "status", "data", "caveats"}


class GPRTests(unittest.TestCase):
    def test_preserves_nested_boolean_meaning(self):
        tree = parse_gpr("A and (B or C)")
        self.assertEqual(tree, {"op": "and", "children": [
            {"op": "gene", "gene_id": "A"}, {"op": "or", "children": [
                {"op": "gene", "gene_id": "B"}, {"op": "gene", "gene_id": "C"}]}]})
        self.assertEqual(gene_members(tree), {"A": True, "B": True, "C": True})

    def test_and_precedence_and_isoenzyme_independence(self):
        tree = parse_gpr("A or B and C")
        self.assertEqual(tree["op"], "or")
        self.assertEqual(gene_members(tree), {"A": False, "B": True, "C": True})

    def test_empty_rule_stays_missing(self):
        self.assertIsNone(parse_gpr("  "))
        self.assertEqual(gene_members(None), {})

    def test_no_eval_or_silent_partial_parse(self):
        for text in ("A B", "A and", "or A", "(A", "A)", "()", "A && B", "not A",
                     "A; B", "A + B", '__import__("os")', "A or ()", "A and or B"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_gpr(text)

    def test_bounded_depth_and_token_count(self):
        with self.assertRaises(ValueError):
            parse_gpr("(" * 102 + "A" + ")" * 102)
        with self.assertRaises(ValueError):
            parse_gpr(" or ".join(["A"] * 6000))

    def test_repeated_gene_retains_any_complex_context(self):
        self.assertEqual(gene_members(parse_gpr("A or (A and B)")), {"A": True, "B": True})

    def test_case_spacing_and_source_identifiers(self):
        self.assertEqual(gene_members(parse_gpr(" ENSG00000178445 AND\n(ENSG00000140905.1 OR OTHER:1) ")),
                         {"ENSG00000178445": True, "ENSG00000140905.1": True, "OTHER:1": True})


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="metabocausal-gem-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.fixture = fixture()
        self.index_path = self.directory / "index.json"
        self.write(self.fixture, self.index_path)
        self.lookup = gem.GemLookup(self.index_path)

    def write(self, data, path):
        index = build_index.build_index_data(data["model"], data["annotations"], data["provenance"])
        build_index.write_index(index, path)
        return gem.GemLookup(path)

    def changed(self, change):
        data = deepcopy(self.fixture)
        change(data)
        return self.write(data, self.directory / "changed.json")

    def test_standard_envelope_and_strict_json(self):
        result = self.lookup.query("CHEBI:1")
        self.assertEqual(set(result), ENVELOPE_KEYS)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["retrieved_at"].endswith("+00:00"))
        json.dumps(result, allow_nan=False)
        self.assertEqual(result["data"]["network_calls"], 0)
        self.assertEqual(result["data"]["evidence_type"], "biochemical")
        self.assertEqual(result["data"]["route"], "via_enzyme")

    def test_id_normalisation_without_chemical_inference(self):
        for value in ("chebi:1", "CHEBI_1", " CHEBI:0001 "):
            with self.subTest(value=value):
                result = self.lookup.query(value)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["data"]["query_chebi"], "CHEBI:1")
                self.assertEqual(result["args"]["chebi_id"], value)

    def test_invalid_inputs_do_not_crash_or_become_empty(self):
        for value in (None, 1, True, [], {}, object(), float("nan"), "", "glycine", "CHEBI:0", "CHEBI:-1", "1", "CHEBI:1;CHEBI:2"):
            with self.subTest(value=type(value).__name__):
                result = self.lookup.query(value)
                self.assertEqual(result["status"], "error")
                self.assertIn("error", result["data"])
                json.dumps(result, allow_nan=False)

    def test_unmapped_is_not_error_or_biological_negative(self):
        result = self.lookup.query("CHEBI:999999999")
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["data"]["mapping"]["status"], "unmapped")
        self.assertEqual(result["data"]["candidates"], [])
        self.assertIn("not evidence", " ".join(result["caveats"]))

    def test_all_source_compartments_and_unique_reactions(self):
        data = self.lookup.query("CHEBI:1")["data"]
        self.assertEqual({m["compartment_id"] for m in data["mapping"]["species"]}, {"c", "m"})
        self.assertEqual(data["total_reactions"], 3)  # RX2 matches two species but is one reaction
        self.assertEqual(data["total_candidates"], 4)

    def test_gpr_raw_ast_and_complex_member_are_preserved(self):
        data = self.lookup.query("CHEBI:1")["data"]
        reaction = next(r for r in data["reactions"] if r["id"] == "RX1")
        self.assertEqual(reaction["gpr_raw"], "GENEA and (GENEB or GENEC)")
        self.assertEqual(reaction["gpr"]["op"], "and")
        self.assertEqual(reaction["gpr"]["children"][1]["op"], "or")
        for row in data["candidates"]:
            self.assertEqual(row["origin"], "biochemical")
            self.assertEqual(row["complex_member"], row["symbol"] != "GENED")
            self.assertNotIn("rank_score", row)

    def test_reaction_role_uses_explicit_context_and_basis(self):
        rows = {r["id"]: r for r in self.lookup.query("CHEBI:1")["data"]["reactions"]}
        self.assertEqual(rows["RX1"]["role"], "enzyme")
        self.assertEqual(rows["RX2"]["role"], "transporter")
        self.assertIn("inferred context", rows["RX2"]["role_basis"])
        self.assertEqual(rows["RX3"]["role"], "unknown")
        self.assertIsNone(rows["RX3"]["gpr"])

    def test_source_tcdb_is_retained_without_guessing(self):
        lookup = self.changed(lambda data: data["annotations"]["reactions"]["RX1"]["values"].update(rxnTCDBID="source-test-id"))
        row = next(r for r in lookup.query("CHEBI:1")["data"]["reactions"] if r["id"] == "RX1")
        self.assertEqual(row["role"], "transporter")
        self.assertEqual(row["annotations"]["rxnTCDBID"], "source-test-id")

    def test_direction_forward_reverse_reversible_blocked(self):
        data = gem.GemLookup(self.index_path, hub_policy="include").query("CHEBI:2")["data"]
        self.assertEqual(next(r for r in data["reactions"] if r["id"] == "RX4")["direction"], "reverse")
        rows = {r["id"]: r for r in self.lookup.query("CHEBI:1")["data"]["reactions"]}
        self.assertEqual(rows["RX1"]["direction"], "forward")
        self.assertEqual(rows["RX2"]["direction"], "reversible")
        self.assertTrue(rows["RX2"]["reversible"])
        self.assertEqual(rows["RX3"]["direction"], "blocked")

    def test_missing_bounds_stay_unknown(self):
        lookup = self.changed(lambda data: data["model"]["reactions"][0].pop("lower_bound"))
        row = next(r for r in lookup.query("CHEBI:1")["data"]["reactions"] if r["id"] == "RX1")
        self.assertEqual(row["direction"], "unknown")
        self.assertIsNone(row["lower_bound"])
        self.assertIsNone(row["reversible"])

    def test_source_annotation_ambiguity_does_not_merge_identities(self):
        lookup = self.changed(lambda data: data["annotations"]["metabolites"]["QB_c"]["values"].update(metChEBIID="CHEBI:1"))
        result = lookup.query("CHEBI:1")
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["data"]["mapping"]["status"], "ambiguous")
        self.assertEqual(result["data"]["mapping"]["base_ids"], ["QA", "QB"])
        self.assertFalse(result["data"]["candidates"])

    def test_missing_base_identity_not_inferred_from_name_or_suffix(self):
        lookup = self.changed(lambda data: data["annotations"]["metabolites"]["QA_m"]["values"].pop("metsNoComp"))
        self.assertEqual(lookup.query("CHEBI:1")["data"]["mapping"]["status"], "ambiguous")

    def test_diagnostic_name_lookup_reports_ambiguity(self):
        lookup = self.changed(lambda data: data["model"]["metabolites"][2].update(name="test-alpha"))
        result = lookup.resolve_name("TEST-ALPHA")
        self.assertEqual(result["status"], "empty")
        self.assertTrue(result["data"]["mapping"]["ambiguous"])
        self.assertFalse(result["data"]["candidates"])

    def test_name_lookup_is_exact_and_not_gene_nomination(self):
        self.assertEqual(self.lookup.resolve_name("test-alpha")["status"], "ok")
        self.assertEqual(self.lookup.resolve_name("test-alph")["status"], "empty")
        self.assertEqual(self.lookup.resolve_name(None)["status"], "error")

    def test_malformed_optional_chebi_is_retained_but_not_indexed(self):
        lookup = self.changed(lambda data: data["annotations"]["metabolites"]["QB_c"]["values"].update(metChEBIID="G12345;CHEBI:2"))
        result = lookup.query("CHEBI:2")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["mapping"]["species"][0]["invalid_chebi_annotations"], ["G12345"])
        self.assertIn("malformed ChEBI", " ".join(result["caveats"]))

    def test_explicit_currency_policy_not_empty_or_outage(self):
        data = self.lookup.query("CHEBI:15422")["data"]
        self.assertTrue(data["hub_metabolite"])
        self.assertTrue(data["policy_suppressed"])
        self.assertEqual(data["candidates"], [])
        self.assertEqual(data["total_candidates"], 1)
        self.assertEqual(data["total_reactions"], 1)

    def test_degree_policy_is_greater_than_threshold_and_configurable(self):
        self.assertFalse(gem.GemLookup(self.index_path, hub_threshold=3).query("CHEBI:1")["data"]["hub_metabolite"])
        suppressed = gem.GemLookup(self.index_path, hub_threshold=2).query("CHEBI:1")["data"]
        self.assertTrue(suppressed["policy_suppressed"])
        included = gem.GemLookup(self.index_path, hub_threshold=2, hub_policy="include").query("CHEBI:1")["data"]
        self.assertTrue(included["hub_metabolite"])
        self.assertFalse(included["policy_suppressed"])
        self.assertEqual(len(included["candidates"]), 4)

    def test_currency_list_is_configurable(self):
        self.assertFalse(gem.GemLookup(self.index_path, currency_ids=[]).query("CHEBI:15422")["data"]["hub_metabolite"])
        self.assertTrue(gem.GemLookup(self.index_path, currency_ids=["CHEBI_1"]).query("CHEBI:1")["data"]["hub_metabolite"])

    def test_caps_do_not_change_full_counts_or_candidate_membership(self):
        result = gem.GemLookup(self.index_path, max_reactions=1, max_candidates=1).query("CHEBI:1")
        data = result["data"]
        self.assertEqual((data["total_reactions"], data["returned_reactions"]), (3, 1))
        self.assertEqual((data["total_candidates"], data["returned_candidates"]), (4, 1))
        self.assertFalse(data["reactions_complete"])
        self.assertFalse(data["candidates_complete"])

    def test_zero_detail_cap_is_explicit(self):
        data = gem.GemLookup(self.index_path, max_reactions=0, max_candidates=0).query("CHEBI:1")["data"]
        self.assertEqual(data["candidates"], [])
        self.assertEqual(data["total_candidates"], 4)
        self.assertFalse(data["candidates_complete"])

    def test_default_nonhub_reactions_fit_default_detail_cap(self):
        self.assertGreaterEqual(self.lookup.max_reactions, self.lookup.hub_threshold)

    def test_invalid_configuration_rejected(self):
        for kwargs in ({"max_candidates": -1}, {"max_reactions": True}, {"hub_threshold": 1.2},
                       {"hub_policy": "guess"}, {"max_reactions": 10001}, {"currency_ids": ["ATP"]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                gem.GemLookup(self.index_path, **kwargs)

    def test_gene_symbol_missing_does_not_use_a_memory_fallback(self):
        lookup = self.changed(lambda data: data["annotations"]["genes"]["GENEA"]["values"].update(geneSymbols=""))
        row = next(c for c in lookup.query("CHEBI:1")["data"]["candidates"] if c["ensembl"] == "GENEA")
        self.assertIsNone(row["symbol"])
        self.assertEqual(row["symbol_status"], "missing")

    def test_conflicting_gene_symbol_is_not_sent_as_unambiguous(self):
        lookup = self.changed(lambda data: data["annotations"]["genes"]["GENEA"]["values"].update(geneSymbols="WRONG"))
        row = next(c for c in lookup.query("CHEBI:1")["data"]["candidates"] if c["ensembl"] == "GENEA")
        self.assertIsNone(row["symbol"])
        self.assertEqual(row["symbol_status"], "conflicting_source_labels")

    def test_multiple_symbols_not_collapsed(self):
        lookup = self.changed(lambda data: data["annotations"]["genes"]["GENEA"]["values"].update(geneSymbols="GENEA;OTHER"))
        row = next(c for c in lookup.query("CHEBI:1")["data"]["candidates"] if c["ensembl"] == "GENEA")
        self.assertIsNone(row["symbol"])
        self.assertEqual(row["symbols"], ["GENEA", "OTHER"])
        self.assertEqual(row["symbol_status"], "ambiguous")

    def test_fixture_cannot_look_like_a_full_run(self):
        result = self.lookup.query("CHEBI:1")
        self.assertEqual(result["data"]["dataset_kind"], "synthetic_fixture")
        self.assertIn("NOT a full-model run", " ".join(result["caveats"]))

    def test_returned_data_mutation_does_not_poison_cache(self):
        result = self.lookup.query("CHEBI:1")
        result["data"]["candidates"][0]["symbol"] = "WRONG"
        result["data"]["reactions"][0]["gpr"]["op"] = "WRONG"
        result["data"]["provenance"]["counts"]["genes"] = 999
        again = self.lookup.query("CHEBI:1")
        self.assertEqual(again["data"]["candidates"][0]["symbol"], "GENEA")
        self.assertEqual(again["data"]["reactions"][0]["gpr"]["op"], "and")
        self.assertEqual(again["data"]["provenance"]["counts"]["genes"], 4)

    def test_index_corruption_even_after_cache_warmup_is_error(self):
        self.lookup.query("CHEBI:1")
        with self.index_path.open("ab") as stream:
            stream.write(b" ")
        result = self.lookup.query("CHEBI:1")
        self.assertEqual(result["status"], "error")
        self.assertIn("checksum", result["data"]["error"])

    def test_missing_index_or_manifest_is_error_not_empty(self):
        self.assertEqual(gem.GemLookup(self.directory / "absent.json").query("CHEBI:1")["status"], "error")
        Path(str(self.index_path) + ".manifest.json").unlink()
        self.assertEqual(self.lookup.query("CHEBI:1")["status"], "error")

    def test_manifest_provenance_mismatch_rejected(self):
        path = Path(str(self.index_path) + ".manifest.json")
        manifest = common.strict_json(path.read_bytes())
        manifest["provenance"]["version"] = "wrong"
        path.write_bytes(common.canonical_bytes(manifest))
        self.assertEqual(self.lookup.query("CHEBI:1")["status"], "error")

    def test_public_single_argument_function_uses_configured_index(self):
        with patch.dict("os.environ", {"METABOCAUSAL_GEM_INDEX": str(self.index_path)}):
            self.assertEqual(gem.map_metabolite_to_genes_gem("CHEBI:1")["status"], "ok")

    def test_no_network_access_in_query_name_or_batch(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            self.assertEqual(self.lookup.query("CHEBI:1")["status"], "ok")
            self.assertEqual(self.lookup.resolve_name("test-alpha")["status"], "ok")
            self.assertEqual(self.lookup.map_many(["CHEBI:1"])["errors"], 0)

    def test_batch_retains_duplicates_unknowns_and_failures_separately(self):
        report = self.lookup.map_many(["CHEBI:1", "CHEBI_1", "CHEBI:999999999", "invalid", "CHEBI:2"])
        self.assertEqual(report["input_count"], 5)
        self.assertEqual(report["unique_valid_chebi_count"], 3)
        self.assertEqual((report["mapped"], report["unmapped"], report["errors"]), (2, 1, 1))
        self.assertTrue(report["records"][1]["reused"])
        self.assertEqual(report["records"][1]["envelope"]["args"]["chebi_id"], "CHEBI_1")

    def test_concurrent_requests_keep_separate_envelopes(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(self.lookup.query, ["CHEBI:1", "CHEBI:2", "CHEBI:15422", "CHEBI:999999999"] * 3))
        self.assertEqual([r["status"] for r in results], ["ok", "ok", "ok", "empty"] * 3)
        self.assertTrue(all(r["data"].get("query_chebi") == r["args"]["chebi_id"] for r in results))


class BuilderTests(unittest.TestCase):
    def data(self, change=None):
        data = fixture()
        if change:
            change(data)
        return build_index.build_index_data(data["model"], data["annotations"], data["provenance"])

    def test_deterministic_index_bytes_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "one.json", Path(directory) / "two.json"
            build_index.write_index(self.data(), first)
            build_index.write_index(self.data(), second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with self.assertRaises(FileExistsError):
                build_index.write_index(self.data(), first)

    def test_duplicate_model_entities_rejected(self):
        with self.assertRaises(ValueError):
            self.data(lambda d: d["model"]["metabolites"].append(d["model"]["metabolites"][0]))

    def test_unknown_gene_species_and_compartment_rejected(self):
        changes = [lambda d: d["model"]["reactions"][0].update(gene_reaction_rule="ABSENT"),
                   lambda d: d["model"]["reactions"][0].update(metabolites={"ABSENT": -1}),
                   lambda d: d["model"]["metabolites"][0].update(compartment="ABSENT")]
        for change in changes:
            with self.assertRaises(ValueError):
                self.data(change)

    def test_nonfinite_zero_coefficients_and_invalid_bounds_rejected(self):
        changes = [lambda d: d["model"]["reactions"][0].update(metabolites={"QA_c": 0}),
                   lambda d: d["model"]["reactions"][0].update(upper_bound=float("inf")),
                   lambda d: d["model"]["reactions"][0].update(lower_bound=1001),
                   lambda d: d["model"]["reactions"][0].update(metabolites={"QA_c": float("nan")}),
                   lambda d: d["model"]["reactions"][0].update(metabolites={"QA_c": True})]
        for change in changes:
            with self.assertRaises(ValueError):
                self.data(change)

    def test_omap_duplicates_not_silently_discarded(self):
        self.assertEqual(build_index.as_mapping([["a", 1]]), {"a": 1})
        with self.assertRaises(ValueError):
            build_index.as_mapping([["a", 1], ["a", 2]])

    def test_tsv_missing_trailing_columns_are_unknown_not_filled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.tsv"
            path.write_text("id\ta\tb\nX\tvalue\n", encoding="utf-8")
            row = build_index.tsv_records(path, "id", ("id", "a"))["X"]
            self.assertIsNone(row["values"]["b"])
            self.assertEqual(row["omitted_columns"], ["b"])
            self.assertEqual(row["record_number"], 2)

    def test_bad_tsv_shape_or_duplicate_id_rejected(self):
        for text in ("id\tid\nX\tY\n", "id\ta\nX\tY\textra\n", "id\ta\nX\ta\nX\tb\n"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "table.tsv"
                path.write_text(text)
                with self.assertRaises(ValueError):
                    build_index.tsv_records(path, "id", ("id",))

    def test_source_checksum_and_version_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "version.txt"
            path.write_text("test\n")
            lock = {"version": "test", "files": {"version.txt": {"sha256": common.sha256(path.read_bytes())}}}
            self.assertEqual(common.verify_sources(directory, lock), lock)
            path.write_text("changed\n")
            with self.assertRaises(ValueError):
                common.verify_sources(directory, lock)

    def test_strict_json_rejects_duplicate_and_nonfinite_values(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'):
            with self.assertRaises(ValueError):
                common.strict_json(raw)

    def test_json_duplicate_keys_rejected_after_escape_decoding_at_every_depth(self):
        for raw in (r'{"x":null,"\u0078":false}',
                    r'{"nested":[{"x":1,"\u0078":1}]}',
                    '{"x":{},"x":{}}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                common.strict_json(raw)
        self.assertEqual(common.strict_json('{"left":{"x":null},"right":{"x":false}}'),
                         {"left": {"x": None}, "right": {"x": False}})

    def test_future_index_schema_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.json"
            data = self.data()
            data["schema_version"] = 999
            build_index.write_index(data, path)
            self.assertEqual(gem.GemLookup(path).query("CHEBI:1")["status"], "error")


class SourceExcerptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="gem-source-excerpt-")
        cls.index_path = Path(cls.temp.name) / "source.json"
        build_index.build_fixture(SOURCE_FIXTURE, cls.index_path)
        cls.lookup = gem.GemLookup(cls.index_path)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_glycine_source_gene_complex_not_flat_or(self):
        result = self.lookup.query("CHEBI:15428")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["dataset_kind"], "source_fixture")
        rows = {r["id"]: r for r in result["data"]["reactions"]}
        self.assertEqual(rows["MAR08433"]["gpr_raw"], "ENSG00000140905 and ENSG00000178445")
        self.assertEqual(rows["MAR08433"]["gpr"]["op"], "and")
        candidates = {row["symbol"]: row for row in result["data"]["candidates"]}
        self.assertTrue({"GCSH", "GLDC", "SHMT2"}.issubset(candidates))
        self.assertEqual(candidates["GLDC"]["ensembl"], "ENSG00000178445")
        self.assertTrue(candidates["GLDC"]["complex_member"])
        self.assertNotIn("CPS1", candidates)

    def test_isoleucine_exact_source_row(self):
        data = self.lookup.query("CHEBI:17191")["data"]
        self.assertEqual(data["candidates"][0]["symbol"], "BCAT1")
        self.assertEqual(data["reactions"][0]["id"], "MAR03777")

    def test_citrate_transporter_preserves_compartments(self):
        data = self.lookup.query("CHEBI:30769")["data"]
        self.assertEqual(data["candidates"][0]["symbol"], "SLC25A1")
        self.assertEqual(data["candidates"][0]["role"], "transporter")
        self.assertEqual(data["reactions"][0]["id"], "MAR00125")

    def test_tmao_is_source_fmo_or_rule_not_only_expected_fmo3(self):
        data = self.lookup.query("CHEBI:15724")["data"]
        self.assertEqual({c["symbol"] for c in data["candidates"]}, {"FMO1", "FMO2", "FMO3", "FMO4", "FMO5"})
        self.assertEqual(data["reactions"][0]["gpr"]["op"], "or")

    def test_every_output_record_has_source_location(self):
        data = self.lookup.query("CHEBI:15428")["data"]
        for row in data["candidates"] + data["reactions"] + data["mapping"]["species"]:
            location = row["source_location"]
            self.assertGreater(location["model_line"], 0)
            self.assertGreater(location["annotation_record"], 1)
        self.assertEqual(data["provenance"]["provenance"]["commit"], "635f533152dc5f7290ce04d12700eaa882273c3e")

    def test_output_connects_to_existing_1e_without_reinterpreting_origin(self):
        from tools._evidence import recording
        from tools.gnomad import get_gnomad_constraint

        context = self.lookup.query("CHEBI:15428")
        candidate = next(c for c in context["data"]["candidates"] if c["symbol"] == "GLDC")
        raw = {"data": {"gene": {"symbol": "GLDC", "gene_id": candidate["ensembl"],
                                 "gnomad_constraint": None}}}

        class Response(io.BytesIO):
            status = 200

        ledger = []
        with recording(lambda envelope: ledger.append(deepcopy(envelope))):
            with patch("tools._evidence.urlopen", return_value=Response(json.dumps(raw).encode())):
                result = get_gnomad_constraint(candidate["symbol"])
        self.assertEqual(result["status"], "empty")  # a missing constraint is not safe/zero
        self.assertEqual(result, ledger[0])
        self.assertEqual(context["status"], "ok")
        self.assertEqual(candidate["origin"], "biochemical")


class DownloadTests(unittest.TestCase):
    def test_retry_once_for_5xx(self):
        error = HTTPError("https://example.test", 500, "test", {}, io.BytesIO())
        with patch.object(fetch_model, "urlopen", side_effect=[error, io.BytesIO(b"source")]) as request:
            self.assertEqual(fetch_model.download("https://example.test"), b"source")
        self.assertEqual(request.call_count, 2)

    def test_second_failure_or_non_5xx_not_hidden(self):
        for codes in ((500, 503), (429,), (404,)):
            errors = [HTTPError("https://example.test", code, "test", {}, io.BytesIO()) for code in codes]
            with patch.object(fetch_model, "urlopen", side_effect=errors) as request:
                with self.assertRaises(HTTPError):
                    fetch_model.download("https://example.test")
                self.assertEqual(request.call_count, len(codes))

    def test_network_error_is_not_retried_indefinitely(self):
        with patch.object(fetch_model, "urlopen", side_effect=URLError("offline")) as request:
            with self.assertRaises(URLError):
                fetch_model.download("https://example.test")
            self.assertEqual(request.call_count, 1)

    def test_download_and_idempotent_reverification_receipts(self):
        raw = b"test\n"
        lock = {"version": "test", "commit": "test", "files": {"version.txt": {"sha256": common.sha256(raw), "path": "version.txt"}}}
        with tempfile.TemporaryDirectory() as directory, patch.object(fetch_model, "source_lock", return_value=lock):
            with patch.object(fetch_model, "download", return_value=raw) as request:
                first = fetch_model.fetch_model(directory)
                second = fetch_model.fetch_model(directory)
            self.assertEqual(first["status"], "ok")
            self.assertEqual(second["status"], "ok")
            self.assertEqual(request.call_count, 1)
            self.assertEqual(second["assets"][0]["mode"], "verified_existing")
            self.assertEqual(len(list(Path(directory).glob("fetch-*.json"))), 2)

    def test_checksum_mismatch_not_written_or_overwritten(self):
        lock = {"version": "test", "commit": "test", "files": {"version.txt": {"sha256": "0" * 64, "path": "version.txt"}}}
        with tempfile.TemporaryDirectory() as directory, patch.object(fetch_model, "source_lock", return_value=lock):
            with patch.object(fetch_model, "download", return_value=b"bad"):
                result = fetch_model.fetch_model(directory)
            self.assertEqual(result["status"], "error")
            self.assertFalse((Path(directory) / "version.txt").exists())
            (Path(directory) / "version.txt").write_bytes(b"existing-user-file")
            result = fetch_model.fetch_model(directory)
            self.assertEqual(result["status"], "error")
            self.assertEqual((Path(directory) / "version.txt").read_bytes(), b"existing-user-file")


class CommandLineTests(unittest.TestCase):
    def test_fixture_build_query_and_durable_ledger_without_pyyaml(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            index, ledger = Path(directory) / "index.json", Path(directory) / "run.jsonl"
            built = subprocess.run([sys.executable, "-m", "MVP3.src.build_index", "--fixture", str(SOURCE_FIXTURE),
                                    "--output", str(index)], cwd=root, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr + built.stdout)
            result = subprocess.run([sys.executable, "-m", "MVP3.src.gem", "CHEBI:15428", "--index", str(index),
                                     "--ledger", str(ledger)], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            envelope = json.loads(result.stdout)
            self.assertEqual(envelope["status"], "ok")
            self.assertEqual([common.strict_json(line) for line in ledger.read_bytes().splitlines()], [envelope])

    def test_cli_index_error_has_nonzero_exit_and_json_envelope(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-m", "MVP3.src.gem", "CHEBI:1", "--index", str(Path(directory) / "missing.json")],
                                    cwd=root, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["status"], "error")

    def test_cli_ledger_failure_does_not_claim_success(self):
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.json"
            build_index.build_fixture(SOURCE_FIXTURE, index)
            buffer = io.StringIO()
            with patch.object(sys, "argv", ["gem", "CHEBI:15428", "--index", str(index), "--ledger", str(Path(directory) / "ledger.jsonl")]), \
                 patch.object(gem.os, "fsync", side_effect=OSError("injected persistence failure")), redirect_stdout(buffer):
                code = gem.main()
            envelope = json.loads(buffer.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(envelope["status"], "error")
            self.assertEqual(envelope["data"]["retrieval_status"], "ok")
            self.assertIn("ledger_error", envelope["data"])


if __name__ == "__main__":
    unittest.main()
