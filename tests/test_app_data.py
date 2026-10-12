"""app_data.py's data-loading helpers for app.py (1G). Fully offline, no network, no
model, no Streamlit import - this file never imports app.py itself, so it can run
without a browser and without streamlit installed at all.

    python -m unittest tests.test_app_data -v          # from the repo root

WHAT IS ASSERTED, AND WHY

  the three example pairs        app.py's "Example cards" tab is built from exactly
                                 these three keys and their state labels; a rename in
                                 data/demo_card_inputs.json must fail this test, not
                                 surface as a KeyError inside a running app

  example cards come from        examples/*.md are the reviewed, committed cards -
  examples/, verbatim            app_data must read them unmodified, not regenerate a
                                 lookalike from the cached snapshot

  example figures are honest     the cached snapshot carries no gene dossier, so the
  about what the snapshot lacks  genetics-to-clinic timeline must always come back None
                                 here, and the note must say why rather than staying
                                 silent about the absence

  the library table's shape      MVP2's screened candidate table is large (>20k rows);
                                 this checks the columns, counts and state/record_type
                                 breakdown are the ones actually on disk, not assumed

  "not shipped" is reported,     library_inventory() must say validated/ and index/
  not guessed                   are empty exactly when they hold nothing but .gitkeep
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app_data

EXPECTED_PAIR_KEYS = [
    "urate|gout",
    "glycine|coronary artery disease",
    "trimethylamine N-oxide|coronary artery disease",
]
EXPECTED_STATES = {
    "urate|gout":                                      "A",
    "glycine|coronary artery disease":                 "B",
    "trimethylamine N-oxide|coronary artery disease":  "C",
}


class TestExamplePairs(unittest.TestCase):

    def test_the_three_frozen_pairs_in_file_order_with_their_states(self):
        pairs = app_data.example_pairs()
        self.assertEqual([pair["key"] for pair in pairs], EXPECTED_PAIR_KEYS)
        for pair in pairs:
            self.assertEqual(pair["state"], EXPECTED_STATES[pair["key"]])

    def test_every_pair_has_a_non_empty_label(self):
        for pair in app_data.example_pairs():
            self.assertTrue(pair["label"].strip())


class TestExampleCard(unittest.TestCase):

    def test_each_pair_resolves_to_its_committed_file(self):
        expected = {
            "urate|gout":                                      "urate_gout.md",
            "glycine|coronary artery disease":                 "glycine_cad.md",
            "trimethylamine N-oxide|coronary artery disease":  "tmao_cad.md",
        }
        for key, filename in expected.items():
            path = app_data.example_card_path(key)
            self.assertEqual(path, REPO_ROOT / "examples" / filename)
            self.assertTrue(path.is_file(), f"{path} is not on disk")

    def test_card_text_matches_the_file_on_disk_verbatim(self):
        for key in EXPECTED_PAIR_KEYS:
            card = app_data.example_card(key)
            on_disk = (REPO_ROOT / card["path"]).read_text(encoding="utf-8")
            self.assertEqual(card["card_md"], on_disk)

    def test_each_card_names_its_own_state_on_the_page(self):
        for key, state in EXPECTED_STATES.items():
            card = app_data.example_card(key)
            self.assertIn(f"State {state}", card["card_md"])

    def test_an_unknown_pair_key_raises_keyerror(self):
        with self.assertRaises(KeyError):
            app_data.example_card("not-a-real-pair|nope")


class TestExampleFigures(unittest.TestCase):

    def test_state_a_draws_a_forest_and_no_timeline(self):
        import tempfile
        out = Path(tempfile.mkdtemp())
        figures = app_data.example_figures("urate|gout", out)
        self.assertIsNotNone(figures["state_figure"])
        self.assertTrue(Path(figures["state_figure"]).is_file())
        self.assertIsNone(figures["timeline_figure"])
        self.assertIn("no gene dossier", figures["timeline_note"])

    def test_state_c_draws_nothing_and_says_so(self):
        import tempfile
        out = Path(tempfile.mkdtemp())
        figures = app_data.example_figures(
            "trimethylamine N-oxide|coronary artery disease",
            out,
        )
        self.assertIsNone(figures["state_figure"])
        self.assertIsNone(figures["timeline_figure"])
        self.assertEqual(len(list(out.iterdir())), 0)


class TestLibrary(unittest.TestCase):

    def test_the_shipped_csv_is_on_disk(self):
        self.assertTrue(app_data.library_available())
        self.assertTrue(app_data.LIBRARY_CSV.is_file())

    def test_load_library_returns_the_expected_columns(self):
        frame = app_data.load_library(nrows=50)
        self.assertEqual(set(frame.columns), set(app_data.LIBRARY_COLUMNS))
        self.assertEqual(len(frame), 50)

    def test_summary_counts_are_internally_consistent(self):
        summary = app_data.library_summary()
        self.assertTrue(summary["shipped"])
        self.assertGreater(summary["n_rows"], 20_000)
        self.assertGreater(summary["n_distinct_pairs"], 0)
        self.assertLessEqual(summary["n_distinct_pairs"], summary["n_rows"])
        record_total = sum(summary["record_type_counts"].values())
        state_total = sum(summary["state_counts"].values())
        self.assertEqual(record_total, summary["n_rows"])
        self.assertEqual(state_total, summary["n_rows"])

    def test_no_state_rows_are_labelled_as_a_gap_not_a_blank_key(self):
        summary = app_data.library_summary()
        self.assertIn(app_data.LIBRARY_NO_STATE_LABEL, summary["state_counts"])
        for key in summary["state_counts"]:
            self.assertTrue(key.strip())


class TestLibraryInventory(unittest.TestCase):

    def test_extracted_is_shipped_validated_and_index_are_not(self):
        inventory = app_data.library_inventory()
        self.assertTrue(inventory["extracted_shipped"])
        self.assertFalse(inventory["validated_shipped"])
        self.assertFalse(inventory["index_shipped"])

    def test_absence_notes_name_the_gitkeep_only_directories(self):
        inventory = app_data.library_inventory()
        self.assertIn("validated", inventory["validated_note"])
        self.assertIn("index", inventory["index_note"])

    def test_regenerate_command_names_the_two_mvp2_scripts(self):
        inventory = app_data.library_inventory()
        self.assertIn("screen_seed_papers.py", inventory["regenerate_command"])
        self.assertIn("merge_new_pairs.py", inventory["regenerate_command"])


class TestFrozenCardsDirectory(unittest.TestCase):

    def test_helpers_never_raise_when_cards_is_empty_or_missing(self):
        missing = REPO_ROOT / "cards-that-does-not-exist"
        self.assertEqual(
            app_data._dir_has_content(missing),
            False,
        )

    def test_frozen_ledgers_and_figures_return_lists_not_none(self):
        self.assertIsInstance(app_data.frozen_ledgers(), list)
        self.assertIsInstance(app_data.frozen_figures(), list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
