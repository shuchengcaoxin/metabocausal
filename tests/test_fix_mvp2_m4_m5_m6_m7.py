"""Permanent regression tests for the MVP2 data-layer fixes M4, M5, M6, M7.

Adapted from the probe evidence under
docs/research/section9_adversarial/rerun_2026-09-17/new_probes/mvp2/probes/
(probe_L06_extraction.py, probe_L05_records.py, probe_L08_merge.py,
probe_L04_manifests.py). Each test below reproduces the same measurement
those probes made and asserts the FIXED outcome, against the real committed
seed workbook and the real committed MVP2 data-layer artifacts, not a
reimplemented model of them.

TestM4BoundOrderIsNumeric carries the owner's 2026-09-18 ruling on the second
M4 finding: the UKB mapping supplement's two 95% bound columns come out of the
printed header in the impossible order, and the shipped tables now put them in
numeric order, preserve the as-printed pair on the same row and annotate every
row touched. The previous guard asserted the opposite - that the bounds were
kept as printed - and is replaced by that class.

Offline, read-only against the committed seed evidence; the temporary file
M7 writes under MVP2/data/extracted/ is removed in the same test.
"""

import functools
import os
from pathlib import Path
import sys
import tempfile
import unittest
import unittest.mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
MVP2_ROOT = REPO_ROOT / "MVP2"
if str(MVP2_ROOT) not in sys.path:
    sys.path.insert(0, str(MVP2_ROOT))
MVP2_SCRIPTS = MVP2_ROOT / "scripts"
if str(MVP2_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MVP2_SCRIPTS))

import json

from openpyxl import load_workbook

from src.merge_pairs import merge_pair_tables
from src.pair_screening import (
    canonical_pair_key,
    hash_mode,
    normalize,
    read_csv,
    screen_pairs,
    sha256,
)
from screen_seed_papers import bounds_in_numeric_order, extract_ukb, ukb_row_layout_is_shifted


def _hashed_entries(node, where=""):
    """Every {path, sha256, bytes} entry in a manifest, wherever it sits in it."""
    if isinstance(node, dict):
        if "sha256" in node and "path" in node:
            yield where, node
        for key, value in node.items():
            yield from _hashed_entries(value, where + "/" + str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _hashed_entries(value, f"{where}[{index}]")

UKB_WORKBOOK = MVP2_ROOT / "literature" / "seeds" / "ukb_mapping_2025" / "42255_2025_1371_MOESM3_ESM.xlsx"
SCREENED_DIR = MVP2_ROOT / "data" / "extracted" / "screened_20260912"
MERGED_CSV = MVP2_ROOT / "data" / "extracted" / "mvp1_plus_mvp2_candidate_metabolite_disease.csv"
MERGED_MANIFEST = MVP2_ROOT / "data" / "extracted" / "mvp1_plus_mvp2_candidate_metabolite_disease.manifest.json"
PAIR_BATCH_MANIFEST = (
    MVP2_ROOT / "literature" / "search_runs" / "pair_batch_smoke_glycine_cad_20260912" / "manifest.json"
)
BASELINE_CSV = (
    REPO_ROOT / "archive" / "project_files" / "release-evidence_2026-09-11" /
    "metabocausal-public" / "data" / "metabolite_disease.csv"
)
MERGED_PROVENANCE_CSV = (
    MVP2_ROOT / "data" / "extracted"
    / "mvp1_plus_mvp2_candidate_metabolite_disease.provenance.csv"
)
SCREENED_TABLES = (
    "candidate_pairs.csv",
    "new_pair_records.csv",
    "new_unique_pairs.csv",
    "screening_ledger.csv",
)

# Every bound pair a screened row can ship an interval in. ci_low/ci_high is the
# odds-ratio-scale pair the 2026-09-18 reorder rule acts on. ci_low_beta_scale/
# ci_high_beta_scale is the beta-scale pair a shifted Wald-ratio row carries instead,
# which add() passes through without reordering - it is shipped all the same, so it is
# guarded all the same. ci_low_as_printed/ci_high_as_printed is deliberately absent:
# it is not an interval the tables ship, it is the source's printed pair, and being in
# the impossible order is the entire reason it exists.
SHIPPED_BOUND_PAIRS = (
    ("ci_low", "ci_high"),
    ("ci_low_beta_scale", "ci_high_beta_scale"),
)

# What a shipped row's extraction_note says, spelled out here rather than imported from
# the extractor. A test of the committed tables has to measure what the tables say; one
# that agrees with the writer's own constant would pass even if nothing were written.
SHIFTED_ROW_MARKER = "single-SNP Wald-ratio row"
REORDERED_BOUNDS_MARKER = "95% bounds reordered"


@functools.lru_cache(maxsize=None)
def _table(path):
    """One read per file per process; these tables are 4-11 MB each."""
    return tuple(read_csv(path))


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _inverted(rows, low_field, high_field):
    """Rows whose two bounds are both numeric and in the impossible order."""
    found = []
    for row in rows:
        low, high = _as_float(row.get(low_field)), _as_float(row.get(high_field))
        if low is not None and high is not None and low > high:
            found.append(row)
    return found


class TestM4ExtractorLayoutShift(unittest.TestCase):
    def test_wald_ratio_rows_are_detected_as_shifted(self):
        wb = load_workbook(UKB_WORKBOOK, read_only=True, data_only=True)
        shifted_counts = {}
        for sheet in ("sTable 31", "sTable 32", "sTable 33", "sTable 34", "sTable 35"):
            rows = list(wb[sheet].iter_rows(min_row=4, values_only=True))
            shifted_counts[sheet] = sum(1 for row in rows if ukb_row_layout_is_shifted(row))
        self.assertEqual(shifted_counts["sTable 31"], 0)
        self.assertEqual(shifted_counts["sTable 32"], 0)
        self.assertEqual(shifted_counts["sTable 33"], 18)
        self.assertEqual(shifted_counts["sTable 34"], 0)
        self.assertEqual(shifted_counts["sTable 35"], 480)

    def test_shifted_row_no_longer_writes_an_odds_ratio_into_ci_high(self):
        records = []
        extract_ukb(records)
        row = next(
            r for r in records
            if r["source_sheet"] == "sTable 33" and r["source_row"] == 16
        )
        self.assertEqual(row["method"], "Wald ratio")
        self.assertEqual(row["ci_high"], "")
        self.assertEqual(row["ci_low"], "")
        p_value = float(row["p_value"])
        self.assertGreaterEqual(p_value, 0.0)
        self.assertLessEqual(p_value, 1.0)
        self.assertAlmostEqual(p_value, 1.18185020203274e-08)

    def test_the_interval_the_shifted_row_does_carry_is_kept_and_its_scale_stated(self):
        """The source row holds a real 95% interval in columns 12-13; on a shifted row it
        is on the beta scale, where the same two columns are odds-ratio scale everywhere
        else. Emptying ci_low/ci_high is right; emptying them with nothing recording that
        the source had an interval is the "absence is stated, never silently dropped" rule
        broken on the one code path whose whole premise is that the header lies."""
        records = []
        extract_ukb(records)
        row = next(
            r for r in records
            if r["source_sheet"] == "sTable 33" and r["source_row"] == 16
        )
        self.assertEqual(row["ci_low_beta_scale"], "0.702518316457593")
        self.assertEqual(row["ci_high_beta_scale"], "1.43839044131509")
        self.assertIn("beta scale", row["extraction_note"])
        self.assertIn("Wald-ratio", row["extraction_note"])

    def test_every_shifted_row_carries_the_shift_note_and_no_unshifted_row_does(self):
        records = []
        extract_ukb(records)
        noted = [r for r in records if SHIFTED_ROW_MARKER in r["extraction_note"]]
        self.assertEqual(len(noted), 498)
        for row in records:
            with self.subTest(sheet=row["source_sheet"], source_row=row["source_row"]):
                if row["method"] == "Wald ratio":
                    self.assertIn(SHIFTED_ROW_MARKER, row["extraction_note"])
                    self.assertTrue(row["ci_low_beta_scale"] or row["ci_high_beta_scale"])
                else:
                    self.assertNotIn(SHIFTED_ROW_MARKER, row["extraction_note"])
                    self.assertEqual(row["ci_low_beta_scale"], "")
                    self.assertEqual(row["ci_high_beta_scale"], "")

    def test_the_note_reaches_the_committed_tables_and_the_merge_provenance(self):
        rows = _table(SCREENED_DIR / "new_pair_records.csv")
        self.assertEqual(
            sum(1 for row in rows if SHIFTED_ROW_MARKER in row["extraction_note"]),
            18,
        )
        provenance = _table(MERGED_PROVENANCE_CSV)
        noted = [row for row in provenance if SHIFTED_ROW_MARKER in row["extraction_note"]]
        self.assertTrue(noted)
        self.assertTrue(all(row["ci_low_beta_scale"] for row in noted))

    def test_the_manifest_states_the_shifted_layout_and_the_bound_reordering(self):
        manifest = json.loads((SCREENED_DIR / "manifest.json").read_text(encoding="utf-8"))
        caveats = " ".join(manifest["caveats"])
        self.assertIn("498 extracted UKB row(s) carry a shifted source layout", caveats)
        self.assertIn("16944 extracted row(s) had their two 95% bounds reordered", caveats)
        self.assertIn("preserved in ci_low_as_printed/ci_high_as_printed", caveats)
        self.assertNotIn("kept as printed rather than reordered", caveats)

    def test_unshifted_row_keeps_its_column_mapping_and_ships_bounds_in_order(self):
        """The shift detection is unchanged: this row is not shifted, so its method, beta
        and p value still come from the same physical columns they always did. What
        changed on 2026-09-18 is only the order of the two bound cells, and the printed
        pair travels with the row."""
        records = []
        extract_ukb(records)
        row = next(
            r for r in records
            if r["source_sheet"] == "sTable 33" and r["source_row"] == 4
        )
        self.assertEqual(row["method"], "Inverse variance weighted")
        self.assertEqual(row["beta"], "0.373675401417758")
        self.assertEqual(row["p_value"], "0.000703671218193263")
        self.assertEqual(row["ci_low"], "1.17059104033226")
        self.assertEqual(row["ci_high"], "1.80370344183517")
        self.assertEqual(row["ci_low_as_printed"], "1.80370344183517")
        self.assertEqual(row["ci_high_as_printed"], "1.17059104033226")
        self.assertIn(REORDERED_BOUNDS_MARKER, row["extraction_note"])

    def test_no_extracted_row_carries_an_odds_ratio_shaped_value_in_p_value(self):
        records = []
        extract_ukb(records)
        for row in records:
            if row["method"] != "Wald ratio":
                continue
            p_value = float(row["p_value"])
            self.assertGreaterEqual(p_value, 0.0)
            self.assertLessEqual(p_value, 1.0)
            self.assertEqual(row["ci_high"], "")
            self.assertEqual(row["ci_low"], "")


class TestM4BoundOrderIsNumeric(unittest.TestCase):
    """Owner ruling, 2026-09-18: the swapped 95% bounds are reordered, not re-published.

    What the pipeline detected while extracting: the UKB mapping supplement prints
    "95% UCI" over column 11 and "95% LCI" over column 12 - the extractor's own 0-based
    indices, which open in Excel as columns L and M, the 12th and 13th - and the values
    are the other way round, so reading the two cells under the header's own names produced
    ci_low > ci_high on every UKB row that carries both - 16,944 of them. That is not an
    interpretation of the source; it is an arithmetic impossibility, which is why it can
    be detected without deciding anything about the paper's science.

    The ruling has three parts and each is asserted here: the two numbers are shipped in
    numeric order, the pair exactly as printed is preserved on the same row, and every
    row that was touched says so. Nothing is recomputed, and a row whose bounds already
    ascend is untouched.
    """

    def test_bounds_in_numeric_order_swaps_only_the_impossible_pair(self):
        for ci_low, ci_high, expected in (
            ("1.80370344183517", "1.17059104033226", ("1.17059104033226", "1.80370344183517", True)),
            ("1.17059104033226", "1.80370344183517", ("1.17059104033226", "1.80370344183517", False)),
            ("-0.1", "-0.5", ("-0.5", "-0.1", True)),
            ("1.0", "1.0", ("1.0", "1.0", False)),
            ("", "", ("", "", False)),
            ("", "1.8", ("", "1.8", False)),
            ("1.8", "", ("1.8", "", False)),
            ("n/a", "1.8", ("n/a", "1.8", False)),
        ):
            with self.subTest(ci_low=ci_low, ci_high=ci_high):
                self.assertEqual(bounds_in_numeric_order(ci_low, ci_high), expected)

    def test_no_shipped_table_carries_an_impossible_interval(self):
        """The residue, stated as a number rather than as a hope: zero rows left.

        Both shipped pairs are measured, not only the one the reorder rule touches. The
        498 shifted Wald-ratio rows leave ci_low/ci_high blank and ship the interval they
        do have in ci_low_beta_scale/ci_high_beta_scale, which add() passes through
        untouched. All 498 ascend as the source prints them today; this is what keeps it
        that way. A future row arriving inverted in that pair would otherwise ship
        inverted - no note, no as-printed pair, green suite - which is the state the
        2026-09-18 ruling was issued to end.
        """
        for name in SCREENED_TABLES:
            rows = _table(SCREENED_DIR / name)
            for low_field, high_field in SHIPPED_BOUND_PAIRS:
                with self.subTest(table=name, pair=low_field):
                    self.assertEqual(
                        _inverted(
                            rows,
                            low_field,
                            high_field,
                        ),
                        [],
                    )
        self.assertEqual(
            _inverted(
                _table(MERGED_CSV),
                "ci_low",
                "ci_upp",
            ),
            [],
        )
        self.assertEqual(
            _inverted(
                _table(MERGED_PROVENANCE_CSV),
                "ci_low_beta_scale",
                "ci_high_beta_scale",
            ),
            [],
        )

    def test_the_reordered_row_counts_are_the_measured_ones(self):
        """7,912 of the 10,804 unique pairs and 14,509 of the 17,405 records were the
        measurement that opened this; they are now the count of rows carrying the note."""
        counts = {
            name: sum(
                1 for row in _table(SCREENED_DIR / name)
                if REORDERED_BOUNDS_MARKER in row["extraction_note"]
            )
            for name in SCREENED_TABLES
        }
        self.assertEqual(counts["candidate_pairs.csv"], 16944)
        self.assertEqual(counts["screening_ledger.csv"], 16944)
        self.assertEqual(counts["new_pair_records.csv"], 14509)
        self.assertEqual(counts["new_unique_pairs.csv"], 7912)
        manifest = json.loads((SCREENED_DIR / "manifest.json").read_text(encoding="utf-8"))
        bound_order = manifest["bound_order"]
        self.assertEqual(bound_order["reordered_candidate_rows"], 16944)
        self.assertEqual(bound_order["reordered_new_pair_rows"], 14509)
        self.assertEqual(bound_order["reordered_unique_pair_rows"], 7912)
        self.assertEqual(bound_order["remaining_ci_low_greater_than_ci_high"], 0)

    def test_every_reordered_row_preserves_the_pair_exactly_as_printed(self):
        """The as-printed pair is the shipped pair swapped back, character for character:
        no bound was recomputed, rounded or re-read from the workbook."""
        reordered = [
            row for row in _table(SCREENED_DIR / "new_unique_pairs.csv")
            if REORDERED_BOUNDS_MARKER in row["extraction_note"]
        ]
        self.assertEqual(len(reordered), 7912)
        for row in reordered:
            with self.subTest(sheet=row["source_sheet"], source_row=row["source_row"]):
                self.assertEqual(row["ci_low_as_printed"], row["ci_high"])
                self.assertEqual(row["ci_high_as_printed"], row["ci_low"])
                self.assertGreater(
                    float(row["ci_low_as_printed"]),
                    float(row["ci_high_as_printed"]),
                )
                self.assertLess(float(row["ci_low"]), float(row["ci_high"]))

    def test_a_row_that_was_not_reordered_carries_no_as_printed_value(self):
        for row in _table(SCREENED_DIR / "candidate_pairs.csv"):
            if REORDERED_BOUNDS_MARKER in row["extraction_note"]:
                continue
            with self.subTest(sheet=row["source_sheet"], source_row=row["source_row"]):
                self.assertEqual(row["ci_low_as_printed"], "")
                self.assertEqual(row["ci_high_as_printed"], "")

    def test_the_row_already_in_sane_order_is_untouched(self):
        """Chen 2023's bounds ascend as printed, so this row goes through the extractor
        unchanged - same two numbers, no as-printed columns, no note."""
        row = next(
            r for r in _table(SCREENED_DIR / "candidate_pairs.csv")
            if r["study_id"] == "chen_2023" and r["source_sheet"] == "ST18"
            and r["source_row"] == "4"
        )
        self.assertEqual(row["ci_low"], "0.197586936367467")
        self.assertEqual(row["ci_high"], "0.272951997003324")
        self.assertEqual(row["ci_low_as_printed"], "")
        self.assertEqual(row["ci_high_as_printed"], "")
        self.assertEqual(row["extraction_note"], "")

    def test_every_reordered_row_comes_from_the_ukb_mapping_supplement(self):
        """The note names the UKB supplement's header as where this was observed. That
        sentence is only true while the UKB tables are the only source it fires on, so
        the claim is guarded here rather than assumed: a new source whose bounds arrive
        inverted fails this test, and whoever adds it re-words the note."""
        studies = {
            row["study_id"] for row in _table(SCREENED_DIR / "candidate_pairs.csv")
            if REORDERED_BOUNDS_MARKER in row["extraction_note"]
        }
        self.assertEqual(studies, {"ukb_mapping_2025"})

    def test_no_row_carries_both_the_shift_note_and_the_reorder_note(self):
        """A shifted Wald-ratio row leaves ci_low/ci_high empty, so it has no pair to
        reorder. The two findings do not overlap on any row, and if they ever did the
        joined note would have to be read rather than assumed."""
        for name in SCREENED_TABLES:
            for row in _table(SCREENED_DIR / name):
                note = row["extraction_note"]
                if SHIFTED_ROW_MARKER in note:
                    with self.subTest(table=name, source_row=row["source_row"]):
                        self.assertNotIn(REORDERED_BOUNDS_MARKER, note)

    def test_the_merged_table_and_its_sidecar_carry_the_ruling(self):
        provenance = _table(MERGED_PROVENANCE_CSV)
        self.assertIn("ci_low_as_printed", provenance[0])
        self.assertIn("ci_high_as_printed", provenance[0])
        reordered = [
            row for row in provenance
            if REORDERED_BOUNDS_MARKER in row["extraction_note"]
        ]
        self.assertEqual(len(reordered), 7912)
        self.assertTrue(all(row["ci_low_as_printed"] for row in reordered))
        merged_manifest = json.loads(MERGED_MANIFEST.read_text(encoding="utf-8"))
        self.assertTrue(
            any("numeric order" in rule for rule in merged_manifest["rules"]),
            merged_manifest["rules"],
        )

    def test_the_reader_facing_readme_states_the_reordering(self):
        readme = (MVP2_ROOT / "data" / "README.md").read_text(encoding="utf-8")
        self.assertIn("95% UCI", readme)
        self.assertIn("ci_low_as_printed", readme)
        self.assertIn("numeric order", readme)


class TestM5PercentSurvivesNormalization(unittest.TestCase):
    def test_normalize_keeps_percent(self):
        self.assertNotEqual(normalize("Omega-3"), normalize("Omega-3%"))
        self.assertEqual(normalize("Omega-3%"), "omega 3%")
        self.assertEqual(normalize("Omega-3"), "omega 3")

    def test_ratio_and_absolute_exposures_get_distinct_canonical_keys(self):
        absolute_row = {"metabolite_id": "Omega-3", "disease_id": "AB1_X"}
        ratio_row = {"metabolite_id": "Omega-3%", "disease_id": "AB1_X"}
        self.assertNotEqual(canonical_pair_key(absolute_row), canonical_pair_key(ratio_row))

    def test_screen_pairs_keeps_ratio_and_absolute_as_two_new_pairs(self):
        candidates = [
            {
                "metabolite_id": "Omega-3",
                "metabolite_name": "Omega-3 Fatty Acids",
                "disease_id": "AB1_X",
                "disease_trait": "Infection",
                "direction": "forward",
            },
            {
                "metabolite_id": "Omega-3%",
                "metabolite_name": "Omega-3 Fatty Acids to Total Fatty Acids percentage",
                "disease_id": "AB1_X",
                "disease_trait": "Infection",
                "direction": "forward",
            },
        ]
        result = screen_pairs([], candidates)
        self.assertEqual(result["summary"]["new_pair_key_count"], 2)
        self.assertEqual(len(result["new_unique_pairs"]), 2)

    def test_the_committed_distinct_pair_count_is_the_post_fix_one(self):
        """The count changed, and that IS the fix: 9,801 kept pair keys before, 10,804
        after, because 1,003 ratio exposures stopped collapsing into their absolute
        counterparts. Pinned so the number cannot drift back unnoticed."""
        manifest = json.loads((SCREENED_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["summary"]["new_pair_key_count"], 10804)
        self.assertEqual(len(_table(SCREENED_DIR / "new_unique_pairs.csv")), 10804)
        merged = json.loads(MERGED_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(merged["summary"]["new_unique_pair_count"], 10804)
        self.assertEqual(merged["summary"]["merged_row_count"], 21921)


class TestM6SupportingRowCountIsReal(unittest.TestCase):
    def _candidates(self):
        shared = {
            "metabolite_id": "DHA",
            "metabolite_name": "Docosahexaenoic Acid",
            "disease_id": "AB1_X",
            "disease_trait": "Infection",
            "direction": "forward",
        }
        alone = {
            "metabolite_id": "PUFA",
            "metabolite_name": "Polyunsaturated Fatty Acids",
            "disease_id": "AB1_Y",
            "disease_trait": "Cirrhosis",
            "direction": "forward",
        }
        return [dict(shared), dict(shared), dict(shared), dict(alone)]

    def test_screen_pairs_records_the_true_source_row_count_per_key(self):
        result = screen_pairs([], self._candidates())
        by_key = {canonical_pair_key(row): row for row in result["new_unique_pairs"]}
        shared_key = canonical_pair_key({"metabolite_id": "DHA", "disease_id": "AB1_X"})
        alone_key = canonical_pair_key({"metabolite_id": "PUFA", "disease_id": "AB1_Y"})
        self.assertEqual(by_key[shared_key]["supporting_source_rows"], "3")
        self.assertEqual(by_key[alone_key]["supporting_source_rows"], "1")

    def test_merge_carries_the_real_count_instead_of_a_hardcoded_one(self):
        result = screen_pairs([], self._candidates())
        baseline_fields = [
            "metabolite_name", "metabolite_chebi", "disease_trait", "disease_id",
            "b", "se", "ci_low", "ci_upp", "pval", "method", "nsnp",
            "supporting_mr_rows", "record_type",
        ]
        for row in result["new_unique_pairs"]:
            row["pair_relation_verified"] = "yes"
        merged = merge_pair_tables([], result["new_unique_pairs"], baseline_fields)
        supporting = {row["metabolite_name"]: row["supporting_mr_rows"] for row in merged["rows"]}
        self.assertEqual(supporting["Docosahexaenoic Acid"], "3")
        self.assertEqual(supporting["Polyunsaturated Fatty Acids"], "1")

    def test_committed_merged_table_is_not_a_constant_one(self):
        rows = _table(MERGED_CSV)
        appended = [r for r in rows if r["record_type"] == "published_literature_mr_candidate"]
        self.assertGreater(len(appended), 0)
        values = {row["supporting_mr_rows"] for row in appended}
        self.assertNotEqual(values, {"1"})

    def test_the_committed_counts_add_up_to_the_screened_record_count(self):
        """The count is a real count, so it has to reconcile: every appended row's
        supporting_mr_rows summed must equal new_pair_record_count."""
        manifest = json.loads((SCREENED_DIR / "manifest.json").read_text(encoding="utf-8"))
        appended = [
            row for row in _table(MERGED_CSV)
            if row["record_type"] == "published_literature_mr_candidate"
        ]
        self.assertEqual(len(appended), manifest["summary"]["new_pair_key_count"])
        self.assertEqual(
            sum(int(row["supporting_mr_rows"]) for row in appended),
            manifest["summary"]["new_pair_record_count"],
        )


class TestM7ManifestHashMatchesCommittedBytes(unittest.TestCase):
    def test_pinned_archive_baseline_hashes_as_is(self):
        raw = BASELINE_CSV.read_bytes()
        self.assertGreater(raw.count(b"\r\n"), 0)
        import hashlib
        self.assertEqual(sha256(BASELINE_CSV), hashlib.sha256(raw).hexdigest())

    def test_non_pinned_csv_hash_is_crlf_invariant(self):
        source = SCREENED_DIR / "new_unique_pairs.csv"
        lf_bytes = source.read_bytes().replace(b"\r\n", b"\n")
        crlf_bytes = lf_bytes.replace(b"\n", b"\r\n")
        tmp_dir = MVP2_ROOT / "data" / "extracted"
        lf_copy = crlf_copy = None
        try:
            with tempfile.NamedTemporaryFile(dir=tmp_dir, suffix=".csv", delete=False) as handle:
                handle.write(lf_bytes)
                lf_copy = Path(handle.name)
            with tempfile.NamedTemporaryFile(dir=tmp_dir, suffix=".csv", delete=False) as handle:
                handle.write(crlf_bytes)
                crlf_copy = Path(handle.name)
            self.assertNotEqual(lf_bytes, crlf_bytes)
            self.assertEqual(sha256(lf_copy), sha256(crlf_copy))
        finally:
            for tmp_file in (lf_copy, crlf_copy):
                if tmp_file is not None:
                    tmp_file.unlink(missing_ok=True)

    def test_committed_merged_manifest_hash_matches_the_file_on_disk(self):
        manifest = json.loads(MERGED_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["outputs"]["merged_csv"]["sha256"], sha256(MERGED_CSV))

    def test_committed_pair_batch_manifest_hash_matches_its_input_file(self):
        manifest = json.loads(PAIR_BATCH_MANIFEST.read_text(encoding="utf-8"))
        input_file = SCREENED_DIR / "new_unique_pairs.csv"
        self.assertEqual(manifest["input"]["sha256"], sha256(input_file))
        self.assertEqual(manifest["input"]["rows"], len(_table(input_file)))

    def test_the_recorded_search_run_still_records_the_search_that_happened(self):
        """`search_runs/` is a record of searches that were performed, not a derived
        table. Re-running the batch driver over it to repair a digest would resume rather
        than search and would then overwrite the record with a run that searched nothing.
        Only the input block - the file that WAS regenerated - is re-stated."""
        manifest = json.loads(PAIR_BATCH_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["run_id"], "20260912T184153Z")
        self.assertTrue(manifest["config"]["overwrite"])
        self.assertEqual(manifest["summary"]["searched_count"], 1)
        self.assertEqual(manifest["summary"]["skipped_count"], 0)
        index = read_csv(PAIR_BATCH_MANIFEST.parent / "pair_search_index.csv")
        self.assertEqual([row["status"] for row in index], ["success"])
        self.assertEqual([row["reason"] for row in index], ["search completed"])

    def test_every_recorded_path_is_repo_relative_and_posix(self):
        """A manifest is read on a machine that did not write it. A drive letter, a home
        directory or a backslash in it is a path that machine cannot resolve."""
        for manifest_path in sorted(MVP2_ROOT.rglob("*manifest.json")):
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for where, entry in _hashed_entries(data):
                with self.subTest(manifest=manifest_path.name, entry=where):
                    self.assertNotIn("\\", entry["path"])
                    self.assertFalse(Path(entry["path"]).is_absolute())
                    self.assertTrue((REPO_ROOT / entry["path"]).exists())
        index = read_csv(PAIR_BATCH_MANIFEST.parent / "pair_search_index.csv")
        for row in index:
            self.assertNotIn("\\", row["output_file"])
            self.assertNotIn("\\", row["source_path"])

    def test_every_manifest_in_mvp2_verifies_against_the_files_it_names(self):
        checked = 0
        for manifest_path in sorted(MVP2_ROOT.rglob("*manifest.json")):
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for where, entry in _hashed_entries(data):
                with self.subTest(manifest=manifest_path.name, entry=where):
                    target = REPO_ROOT / entry["path"]
                    self.assertEqual(entry["sha256"], sha256(target))
                    self.assertEqual(entry["bytes"], hash_mode(target))
                    checked += 1
        self.assertEqual(checked, 7)

    def test_the_digest_does_not_depend_on_a_git_binary_being_on_path(self):
        """The hash is evidence about bytes. A bundle verified from a zip export, or in
        an image without git, has the same bytes and must produce the same number - the
        previous `git check-attr` probe failed open there and silently switched the
        archived, CRLF-pinned baseline onto the LF-normalising branch."""
        before = sha256(BASELINE_CSV)
        with unittest.mock.patch.dict(os.environ, {"PATH": ""}, clear=False):
            self.assertEqual(sha256(BASELINE_CSV), before)
            self.assertEqual(hash_mode(BASELINE_CSV), "as-committed")
        self.assertEqual(hash_mode(SCREENED_DIR / "new_unique_pairs.csv"), "lf-normalized")


if __name__ == "__main__":
    unittest.main()
