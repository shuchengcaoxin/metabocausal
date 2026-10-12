"""Regression checks for the publication-facing Section 9 probe harness.

These tests pin the measurement harness, not a fix to the measured validator.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import probe_section9


class ProbeSectionNine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="section9-probe-test-")
        cls.output = Path(cls.temp.name)
        cls.rows = probe_section9.run(cls.output)
        cls.by_id = {row["case_id"]: row for row in cls.rows}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_every_declared_expectation_is_reproduced(self):
        self.assertTrue(self.rows)
        self.assertTrue(all(row["expectation_met"] for row in self.rows))

    def test_real_two_gate_path_accepts_token_free_unsupported_prose(self):
        row = self.by_id["R01"]
        self.assertEqual(row["gate_one"], "accepted; accepted=True")
        self.assertEqual(row["outcome"], "printed")

    def test_cross_run_tokens_are_blocked_but_token_free_prose_is_not(self):
        self.assertEqual(self.by_id["R02"]["outcome"], "printed")
        self.assertEqual(self.by_id["R03"]["outcome"], "blocked")
        self.assertIn("V5", self.by_id["R03"]["matched_rules"])

    def test_language_and_type_confusion_findings_are_preserved(self):
        for case_id in (
            "S10", "S11", "S12", "S14", "S16", "S17",
            "S18", "T01", "T02", "T03", "T06", "T07", "T08",
            "U01", "U03", "U04",
        ):
            with self.subTest(case_id=case_id):
                self.assertEqual(self.by_id[case_id]["outcome"], "printed")

    def test_unicode_minus_changes_the_validator_result(self):
        self.assertEqual(self.by_id["U01"]["outcome"], "printed")
        self.assertEqual(self.by_id["U02"]["outcome"], "blocked")
        self.assertIn("V1", self.by_id["U02"]["matched_rules"])

    def test_unindexable_run_fails_closed(self):
        row = self.by_id["M02"]
        self.assertEqual(row["outcome"], "blocked")
        self.assertIn("V0", row["matched_rules"])

    def test_validator_exception_is_contained_by_the_renderer(self):
        row = self.by_id["M05"]
        self.assertEqual(row["outcome"], "blocked")
        self.assertIn("RuntimeError", " ".join(row["matched_rules"]))

    def test_hidden_run_value_passes_both_gates_and_malformed_credential_raises(self):
        self.assertEqual(self.by_id["R06"]["outcome"], "printed")
        self.assertEqual(self.by_id["R06"]["gate_one"], "accepted; accepted=True")
        self.assertEqual(self.by_id["R07"]["outcome"], "raised")
        self.assertIn("AttributeError", " ".join(self.by_id["R07"]["matched_rules"]))

    def test_machine_readable_receipts_are_written(self):
        manifest = json.loads((self.output / "manifest.json").read_text(encoding="utf-8"))
        results = json.loads((self.output / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["cases"], len(self.rows))
        self.assertEqual(len(results), len(self.rows))
        self.assertTrue(manifest["all_expectations_met"])
        self.assertFalse(manifest["network_used"])


if __name__ == "__main__":
    unittest.main()
