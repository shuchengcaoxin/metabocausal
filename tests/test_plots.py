"""plots.py against the frozen snapshot. Fully offline - no request, no credit.

    python -m unittest tests.test_plots -v          # from the repo root

Every figure here is drawn from data/demo_card_inputs.json, the cached envelopes of the
three headline pairs, so the suite stays fast and a run of it cannot spend an OpenGWAS
credit or depend on EpiGraphDB being up.

WHAT IS ACTUALLY CHECKED, AND WHY IT IS CHECKED THIS WAY

  the file is a PNG        Pillow arrives with matplotlib, but the assertion here does not
                           need it: a PNG's signature is its first eight bytes and its
                           width is bytes 16-20 of the IHDR chunk, big-endian. Reading
                           them directly checks the bytes on disk rather than what a
                           library says about them, and keeps the test running on a box
                           where Pillow was never installed.

  the caveats reached      A caption is only worth anything if it is ON the figure, and no
  the figure               test can read pixels. So the two functions that put text on a
                           figure - `_draw_header` and `_draw_footer` - are recorded
                           during the real call, and the assertions are made against what
                           the drawing code actually passed them. A caveat that was
                           computed but never drawn fails these tests.

  State C draws nothing    An empty axis with a zero line on it reads as "no effect" and
                           means "not in this snapshot". `plot_for_result` must return
                           None and leave the directory empty.

The three pairs are urate|gout (A), glycine|coronary artery disease (B) and
trimethylamine N-oxide|coronary artery disease (C).
"""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import plots

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MIN_BYTES = 20 * 1024

PAIR_A = "urate|gout"
PAIR_B = "glycine|coronary artery disease"
PAIR_C = "trimethylamine N-oxide|coronary artery disease"

RESULT_KEYS = {
    "state",
    "reason",
    "metabolite",
    "disease",
    "envelopes",
    "ledger_path",
    "n_ledger_entries",
    "notes",
}


def png_width(path) -> int:
    """The width in the IHDR chunk of a PNG, without opening an image library."""
    header = Path(path).read_bytes()[:24]
    return int.from_bytes(header[16:20], "big")


class FigureCase(unittest.TestCase):
    """A throwaway output directory, plus the two text assertions every figure needs."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="metabocausal_plots_")
        self.addCleanup(folder.cleanup)
        self.out = Path(folder.name)
        self.headers = []
        self.footers = []

    def record_text(self):
        """Capture what the drawing code passes to the header and footer helpers, and
        keep drawing: these tests assert on the text that really reached the figure."""
        real_header, real_footer = plots._draw_header, plots._draw_footer

        def header(
            fig,
            title,
            subtitle,
            height,
        ):
            self.headers.append((title, subtitle))
            return real_header(
                fig,
                title,
                subtitle,
                height,
            )

        def footer(
            fig,
            lines,
            height,
        ):
            self.footers.append(list(lines))
            return real_footer(
                fig,
                lines,
                height,
            )

        plots._draw_header, plots._draw_footer = header, footer
        self.addCleanup(setattr, plots, "_draw_header", real_header)
        self.addCleanup(setattr, plots, "_draw_footer", real_footer)

    @property
    def footer_text(self) -> str:
        return "\n".join("\n".join(lines) for lines in self.footers)

    @property
    def subtitle_text(self) -> str:
        return "\n".join(subtitle for _, subtitle in self.headers)

    def assert_is_a_real_png(self, path):
        self.assertIsNotNone(path, "no figure was written")
        target = Path(path)
        self.assertTrue(target.exists(), f"{target} was reported but is not on disk")
        blob = target.read_bytes()
        self.assertTrue(
            blob.startswith(PNG_MAGIC),
            f"{target.name} does not start with the PNG signature: {blob[:8]!r}",
        )
        self.assertGreater(
            len(blob),
            MIN_BYTES,
            f"{target.name} is {len(blob)} bytes - too small to carry a readable figure",
        )
        self.assertGreaterEqual(
            png_width(target),
            1200,
            f"{target.name} is {png_width(target)} px wide; the brief asks for ~1200",
        )
        return target


class TestTheThreeHeadlinePairs(FigureCase):
    """The contract of plot_for_result, one demo pair per state."""

    def test_the_snapshot_still_holds_the_states_these_tests_assume(self):
        states = {key: plots.demo_result(key)["state"] for key in (PAIR_A, PAIR_B, PAIR_C)}
        self.assertEqual(
            states,
            {PAIR_A: "A", PAIR_B: "B", PAIR_C: "C"},
            "the frozen snapshot no longer carries the states these tests are written for",
        )

    def test_state_a_gets_a_forest_png(self):
        path = plots.plot_for_result(
            plots.demo_result(PAIR_A),
            str(self.out),
        )
        target = self.assert_is_a_real_png(path)
        self.assertTrue(target.name.endswith(plots.FOREST_SUFFIX), target.name)

    def test_state_b_gets_an_instrument_png(self):
        path = plots.plot_for_result(
            plots.demo_result(PAIR_B),
            str(self.out),
        )
        target = self.assert_is_a_real_png(path)
        self.assertTrue(target.name.endswith(plots.INSTRUMENT_SUFFIX), target.name)

    def test_state_c_gets_no_figure_at_all(self):
        path = plots.plot_for_result(
            plots.demo_result(PAIR_C),
            str(self.out),
        )
        self.assertIsNone(path, "State C has nothing retrieved to draw")
        self.assertEqual(
            list(self.out.iterdir()),
            [],
            "State C must not leave a file behind - an empty axis reads as 'no effect'",
        )

    def test_the_figure_is_named_after_the_run_s_ledger_stem(self):
        result = plots.demo_result(PAIR_A)
        result["ledger_path"] = str(REPO_ROOT / "cards" / "slack_urate_gout.ledger.jsonl")
        path = plots.plot_for_result(
            result,
            str(self.out),
        )
        self.assertEqual(Path(path).name, f"slack_urate_gout{plots.FOREST_SUFFIX}")

    def test_a_replay_of_the_snapshot_claims_no_ledger_file_of_its_own(self):
        """The cached snapshot and the frozen cards/<stem>.ledger.jsonl are two DIFFERENT
        runs of the same pair. A demo result that named the frozen file would point
        section 11 of the card at a run whose statuses contradict the tables above it."""
        result = plots.demo_result(PAIR_A)
        self.assertEqual(result["ledger_path"], "")
        self.assertTrue(any("names no ledger file" in note for note in result["notes"]))
        path = plots.plot_for_result(
            result,
            str(self.out),
        )
        self.assertEqual(Path(path).name, f"urate_gout{plots.FOREST_SUFFIX}")

    def test_a_missing_output_directory_is_created(self):
        nested = self.out / "figures" / "today"
        path = plots.plot_for_result(
            plots.demo_result(PAIR_B),
            str(nested),
        )
        self.assertEqual(Path(path).parent, nested)


class TestForestPlot(FigureCase):
    def test_source_interval_overrides_normal_approximation_and_labels_nsnp(self):
        rows, dropped, _ = plots._forest_rows([{
            "b": 1.3665, "se": .1068, "ci_low": .5812, "ci_upp": 2.1518, "nsnp": 4,
        }])
        self.assertEqual(dropped, 0)
        self.assertEqual((rows[0]["ci_low"], rows[0]["ci_upp"]), (.5812, 2.1518))
        self.assertIn("nsnp=4; source CI", rows[0]["label"])

    def test_source_interval_needs_no_se_but_invalid_se_is_never_absolutized(self):
        rows, dropped, _ = plots._forest_rows([
            {"b": .2, "se": None, "ci_low": .1, "ci_upp": .3},
            {"b": .2, "se": -.1},
            {"b": .2, "se": .1, "ci_low": .5, "ci_upp": .1},
        ])
        self.assertEqual(dropped, 1)
        self.assertEqual(rows[0]["ci_kind"], "source CI")
        self.assertEqual(rows[1]["ci_kind"], "derived CI")
        self.assertAlmostEqual(rows[1]["ci_low"], .004)
        self.assertIn("nsnp=not reported", rows[1]["label"])

    """What the forest says about its own truncations."""

    def setUp(self):
        super().setUp()
        self.record_text()
        self.result = plots.demo_result(PAIR_A)
        self.mr = self.result["envelopes"]["mr"]

    def draw(
        self,
        env,
        name,
        **kwargs,
    ):
        return plots.plot_forest(
            env,
            "urate -> gout: retrieved MR estimates (EpiGraphDB MR-EVE)",
            self.out / name,
            **kwargs,
        )

    def with_estimates(self, estimates) -> dict:
        env = copy.deepcopy(self.mr)
        env["data"]["estimates"] = estimates
        return env

    def test_the_footer_says_retrieved_not_computed_before_anything_else(self):
        self.draw(self.mr, "a.png")
        self.assertEqual(self.footers[0][0], plots.FOREST_FOOTER)
        self.assertIn("Retrieved, not computed.", self.footer_text)
        self.assertIn("OpenGWAS 2020-10-13 snapshot.", self.footer_text)

    def test_the_cap_is_printed_on_the_figure_when_it_bites(self):
        self.draw(self.mr, "a.png")
        self.assertIn("Showing 15 of 22", self.subtitle_text)

    def test_a_smaller_cap_prints_that_number_instead(self):
        self.draw(
            self.mr,
            "b.png",
            cap = 5,
        )
        self.assertIn("Showing 5 of 22", self.subtitle_text)

    def test_no_truncation_is_claimed_when_nothing_was_truncated(self):
        self.draw(
            self.mr,
            "c.png",
            cap = 50,
        )
        self.assertIn("Showing all 22", self.subtitle_text)
        self.assertNotIn(" of 22", self.subtitle_text)

    def test_repeated_rows_are_declared_as_repeats(self):
        """22 MR-EVE rows carry 13 distinct (b, se, p). A reader must not count 15 rows
        as 15 independent studies."""
        self.draw(self.mr, "a.png")
        self.assertIn("22 rows carry 13 distinct (b, se, p)", self.footer_text)
        self.assertIn("not independent studies", self.footer_text)

    def test_rows_are_sorted_by_p_value_smallest_first(self):
        usable, _, _ = plots._forest_rows(self.mr["data"]["estimates"])
        usable.sort(key=lambda row: row["pval"])
        self.assertEqual(usable[0]["pval"], min(row["pval"] for row in usable))
        self.assertIn("ieu-a-789", usable[0]["label"])

    def test_an_estimate_without_b_or_se_is_dropped_and_counted_on_the_figure(self):
        rows = copy.deepcopy(self.mr["data"]["estimates"][:5])
        rows[1]["se"] = None
        rows[2]["b"] = None
        rows[3]["se"] = float("nan")

        path = self.draw(
            self.with_estimates(rows),
            "dropped.png",
        )
        self.assert_is_a_real_png(path)
        self.assertIn("3 retrieved row(s) dropped", self.footer_text)
        self.assertIn("b or a usable interval not available in this snapshot", self.footer_text)
        self.assertIn("not evidence of no effect", self.footer_text)
        self.assertIn("Showing all 2", self.subtitle_text)

    def test_a_row_with_no_p_value_is_still_drawn_and_said_so(self):
        rows = copy.deepcopy(self.mr["data"]["estimates"][:3])
        rows[0]["pval"] = None
        path = self.draw(
            self.with_estimates(rows),
            "nop.png",
        )
        self.assert_is_a_real_png(path)
        self.assertIn("1 drawn row(s) carry no p-value", self.footer_text)

    def test_an_envelope_with_nothing_drawable_gets_no_figure(self):
        rows = copy.deepcopy(self.mr["data"]["estimates"][:2])
        for row in rows:
            row["b"] = None
        self.assertIsNone(self.draw(
            self.with_estimates(rows),
            "none.png",
        ))
        self.assertIsNone(self.draw(
            self.with_estimates([]),
            "none.png",
        ))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_an_empty_or_broken_envelope_is_a_None_and_not_a_crash(self):
        for env in ({}, None, {"data": None}, {"data": {}}, {"data": {"estimates": None}}):
            with self.subTest(env=env):
                self.assertIsNone(self.draw(
                    env,
                    "none.png",
                ))

    def test_the_row_label_names_both_datasets_and_the_method(self):
        usable, _, _ = plots._forest_rows(self.mr["data"]["estimates"][:1])
        self.assertIn("ieu-a-789 -> ieu-a-1054 [FE IVW]", usable[0]["label"])

    def test_a_missing_id_or_method_is_named_rather_than_left_blank(self):
        usable, _, _ = plots._forest_rows([{
            "exposure_id": None,
            "outcome_id":  "",
            "method":      None,
            "b":           0.1,
            "se":          0.02,
            "pval":        0.5,
        }])
        self.assertEqual(
            usable[0]["label"],
            "id not returned -> id not returned [method not returned]\nnsnp=not reported; derived CI",
        )

    def two_scales(self) -> list:
        """The real shape of urate x gout: ieu-a-* rows on a large-unit scale and the UKB
        raw deposit of the same measurement, whose whole 95% interval is about 0.4% of the
        resulting axis - a dot on the zero line that is 10.1 standard errors from it."""
        return [
            {
                "exposure_id": "ieu-a-789", "outcome_id": "ieu-a-1054", "method": "FE IVW",
                "b": 1.3665151455190399, "se": 0.106814322383297, "pval": 1.79e-37,
            },
            {
                "exposure_id": "ieu-a-795", "outcome_id": "ieu-a-1054", "method": "FE IVW",
                "b": 1.9782650194023, "se": 0.13225660601716, "pval": 6.76e-37,
            },
            {
                "exposure_id": "ukb-d-30880_raw", "outcome_id": "ieu-a-1054",
                "method": "FE IVW",
                "b": 0.0226969500563215, "se": 0.00224804, "pval": 1.46e-15,
            },
        ]

    def test_a_row_too_narrow_to_draw_is_marked_and_never_reads_as_a_null(self):
        """Two incomparable scales on one linear axis: the third row's interval is a
        couple of pixels wide, so it renders as a dot touching the dashed zero line. It is
        a retrieved result shown as a negative one, which is this project's red line."""
        path = self.draw(
            self.with_estimates(self.two_scales()),
            "scales.png",
        )
        self.assert_is_a_real_png(path)
        self.assertIn("1 drawn row(s) marked with an open point", self.footer_text)
        self.assertIn("the point is NOT a null", self.footer_text)
        self.assertIn("read its b and p", self.footer_text)
        self.assertTrue(
            all(len(line) <= plots.FOOTER_WRAP_CHARS for lines in self.footers for line in lines),
            "a caveat wider than the canvas is cut at the edge with nothing saying so",
        )

    def test_nothing_is_marked_when_every_interval_is_drawable(self):
        self.draw(
            self.with_estimates(self.two_scales()[:2]),
            "onescale.png",
        )
        self.assertNotIn("open point", self.footer_text)

    def test_a_title_wider_than_the_canvas_is_cut_and_says_it_was_cut(self):
        """parse_pair accepts a name up to 120 characters, and the DISEASE sits at the end
        of the forest title - so the half that leaves the canvas is the half that says
        what the metabolite was tested against."""
        long_title = plots.FOREST_TITLE.format(
            metabolite = "urate " * 18,
            disease    = "gouty arthropathy of the first metatarsophalangeal joint",
        )
        plots.plot_forest(
            self.mr,
            long_title,
            self.out / "longtitle.png",
        )
        drawn = self.headers[0][0]
        self.assertLess(len(drawn), len(long_title))
        self.assertTrue(drawn.endswith("..."), drawn)
        self.assertIn("title shortened to fit", self.subtitle_text)
        self.assertIn("section 1 of the card", self.subtitle_text)

    def test_a_short_title_is_left_exactly_as_it_was(self):
        self.draw(self.mr, "short.png")
        self.assertEqual(
            self.headers[0][0],
            "urate -> gout: retrieved MR estimates (EpiGraphDB MR-EVE)",
        )
        self.assertNotIn("title shortened", self.subtitle_text)

    def test_a_row_label_too_wide_for_the_axis_is_cut_and_counted(self):
        rows = copy.deepcopy(self.mr["data"]["estimates"][:2])
        rows[0]["exposure_id"] = "ukb-d-" + "30880_raw_" * 8
        self.draw(
            self.with_estimates(rows),
            "longlabel.png",
        )
        self.assertIn("row label(s) shortened to fit the axis", self.footer_text)
        self.assertIn("section 3 of the card", self.footer_text)


class TestInstrumentChart(FigureCase):
    """What the instrument chart says, and what it refuses to imply."""

    def setUp(self):
        super().setUp()
        self.record_text()
        self.b_env = plots.demo_result(PAIR_B)["envelopes"]["instruments"]
        self.capped_env = plots.demo_result(PAIR_A)["envelopes"]["instruments"]

    def draw(
        self,
        env,
        name,
        **kwargs,
    ):
        return plots.plot_instruments(
            env,
            "glycine: genome-wide significant instruments per dataset",
            self.out / name,
            **kwargs,
        )

    def test_the_footer_defines_F_and_the_weak_threshold_first(self):
        self.draw(self.b_env, "b.png")
        normalized = " ".join(" ".join(self.footers[0]).split())
        self.assertTrue(normalized.startswith(plots.INSTRUMENT_FOOTER))
        self.assertIn("F=(beta/se)^2 on feasibility hits; weak = F<10", normalized)
        self.assertTrue(all(len(line) <= plots.FOOTER_WRAP_CHARS for line in self.footers[0]))

    def test_the_footer_distinguishes_feasibility_F_from_retrieved_MR(self):
        """The PNG is uploaded to Slack on its own. "0 weak" beside a bare definition of
        F is the most flattering possible reading of a statistic inflated by the same
        scan that selected the SNPs, and the card's sentence does not travel with it."""
        self.draw(self.b_env, "b.png")
        self.assertIn("winner's curse", self.footer_text)
        self.assertIn("Potentially upward-biased", self.footer_text)
        self.assertIn(
            "not the F of the original instruments behind retrieved MR estimates",
            " ".join(self.footer_text.split()),
        )

    def test_the_chart_refuses_to_read_as_evidence_of_an_effect(self):
        self.draw(self.b_env, "b.png")
        self.assertIn("an instrument count is not an effect estimate", self.footer_text)
        self.assertIn("not evidence that an effect exists", self.footer_text)

    def test_each_bar_carries_its_weak_instrument_count(self):
        rows, _ = plots._instrument_rows(self.b_env["data"]["exposures"])
        annotations = [plots._instrument_annotation(row) for row in rows]
        self.assertEqual(annotations[0], "49 loci  |  0 weak  |  min F 26.43")
        self.assertEqual(annotations[1], "1 locus  |  0 weak  |  min F 686.8")

    def test_a_dataset_with_no_hits_is_drawn_rather_than_hidden(self):
        rows, dropped = plots._instrument_rows(self.capped_env["data"]["exposures"])
        self.assertEqual(dropped, 0)
        self.assertEqual(len(rows), 6)
        self.assertEqual(
            [row["hits"] for row in rows].count(0),
            3,
            "the three urate datasets with zero genome-wide hits must keep their rows",
        )
        self.assertIn("min F n/a", plots._instrument_annotation(rows[-1]))

    def test_the_tools_own_cap_is_printed_on_the_figure(self):
        path = self.draw(
            self.capped_env,
            "capped.png",
        )
        self.assert_is_a_real_png(path)
        self.assertIn("Showing 6 of 22 matched datasets", self.subtitle_text)
        self.assertIn("22 dataset(s) matched, 6 drawn", self.footer_text)
        self.assertIn("max_datasets=6", self.footer_text)

    def test_no_cap_is_claimed_when_every_matched_dataset_is_drawn(self):
        self.draw(self.b_env, "b.png")
        self.assertIn("Showing all 2 matched datasets", self.subtitle_text)
        self.assertNotIn("matched, 2 drawn", self.footer_text)

    def test_the_figures_own_cap_is_never_reported_as_the_tools_cap(self):
        """The two caps are different questions. Saying "22 matched, 3 drawn (tool cap
        max_datasets=6)" tells a reader the tool never returned rows it did return."""
        path = self.draw(
            self.capped_env,
            "figcap.png",
            cap = 3,
        )
        self.assert_is_a_real_png(path)
        self.assertIn("Showing 3 of 6 returned datasets", self.subtitle_text)
        self.assertIn("themselves 6 of 22 matched", self.subtitle_text)
        self.assertIn("22 dataset(s) matched, 6 returned by the tool", self.footer_text)
        self.assertIn("max_datasets=6", self.footer_text)
        self.assertIn("6 dataset(s) returned by the tool, 3 drawn", self.footer_text)
        self.assertIn("this figure caps at 3 row(s)", self.footer_text)
        self.assertIn("its own cut and not the tool's", self.footer_text)
        self.assertNotIn("22 dataset(s) matched, 3 drawn", self.footer_text)

    def test_an_inferred_platform_is_labelled_as_inferred(self):
        self.draw(self.b_env, "b.png")
        self.assertIn("Platform is inferred from the OpenGWAS id batch prefix", self.footer_text)

    def test_a_missing_platform_is_counted_instead_of_repeated_down_the_axis(self):
        self.draw(
            self.capped_env,
            "capped.png",
        )
        self.assertIn("6 drawn dataset(s) carry no platform", self.footer_text)
        label, shortened = plots._instrument_label({
            "id":       "ieu-b-5137",
            "trait":    "Urate",
            "platform": None,
            "n":        440466.0,
            "hits":     323,
            "weak":     0.0,
            "min_f":    24.2,
        })
        self.assertEqual(label, "ieu-b-5137\nUrate, N=440,466")
        self.assertFalse(shortened, "nothing here is long enough to need shortening")

    def test_a_trait_too_long_for_the_axis_is_cut_and_the_cut_is_printed(self):
        """gwasinfo traits reach 206 characters. A label wider than the axes makes
        tight_layout give up, so the rect reserving the footer band is ignored and the
        caveats are drawn over the x-axis - with nothing on the figure saying text was
        lost. A silent truncation is the one thing this project treats as worse than an
        error."""
        env = copy.deepcopy(self.b_env)
        env["data"]["exposures"][0]["trait"] = "Glycine " + "measured by a very long assay name " * 5
        self.draw(env, "long.png")
        label, shortened = plots._instrument_label({
            "id":       "met-d-Gly",
            "trait":    env["data"]["exposures"][0]["trait"],
            "platform": None,
            "n":        115078.0,
            "hits":     49,
            "weak":     0.0,
            "min_f":    26.4,
        })
        self.assertTrue(shortened)
        self.assertIn("...", label)
        self.assertTrue(
            all(len(line) <= plots.MAX_TRAIT_CHARS + 16 for line in label.splitlines()),
            label,
        )
        self.assertIn("axis label(s) shortened to fit", self.footer_text)
        self.assertIn("section 4 of the card", self.footer_text)

    def test_an_empty_or_broken_envelope_is_a_None_and_not_a_crash(self):
        for env in ({}, None, {"data": {"exposures": []}}, {"data": {"exposures": None}}):
            with self.subTest(env=env):
                self.assertIsNone(self.draw(
                    env,
                    "none.png",
                ))
        self.assertEqual(list(self.out.iterdir()), [])


class TestTheFooterBandIsNeverOverprinted(unittest.TestCase):
    """fig.tight_layout silently GIVES UP when the tick labels are wider than the axes
    area - the rect reserving the footer band is ignored and the figure is still written,
    with the caveats drawn over the x tick labels and the x-axis title."""

    def test_a_label_that_defeats_tight_layout_still_leaves_the_footer_its_band(self):
        fig, ax = plots.plt.subplots(
            figsize   = (plots.FIG_WIDTH_IN, 6.0),
            facecolor = "white",
        )
        self.addCleanup(plots.plt.close, fig)
        ax.barh(range(3), [1, 2, 3])
        ax.set_yticks(range(3))
        ax.set_yticklabels(["X" * 400] * 3, fontsize=7.5)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            plots._reserve_bands(
                fig,
                ax,
                4,
                6.0,
            )
            self.assertTrue(
                any("Tight layout not applied" in str(item.message) for item in caught),
                "this fixture no longer reproduces the layout failure it was built for",
            )
        band = (0.13 + 0.16 * 4) / 6.0
        position = ax.get_position()
        self.assertGreaterEqual(position.y0, band - 1e-6)
        self.assertLessEqual(position.y1, 1 - 0.72 / 6.0 + 1e-6)
        self.assertGreater(position.width, 0.25)


class TestNumbersAreFormattedForAScientist(unittest.TestCase):

    def test_a_p_value_is_scientific_and_never_zero(self):
        self.assertEqual(plots.fmt_p(1.7855974619591198e-37), "1.79e-37")
        self.assertEqual(plots.fmt_p(0.0), "<1e-300")
        self.assertEqual(plots.fmt_p(1e-320), "<1e-300")
        self.assertEqual(plots.fmt_p(0.029369372), "2.94e-02")

    def test_a_p_value_that_is_not_there_says_so_rather_than_printing_zero(self):
        for value in (None, "", "n/a", float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assertEqual(plots.fmt_p(value), "n/a")

    def test_an_effect_size_is_four_significant_figures(self):
        self.assertEqual(plots.fmt_sig(1.3665151455190399), "1.367")
        self.assertEqual(plots.fmt_sig(0.106814322383297), "0.1068")
        self.assertEqual(plots.fmt_sig(0.002248), "0.002248")
        self.assertEqual(plots.fmt_sig(26.426363525031647), "26.43")
        self.assertEqual(plots.fmt_sig(686.8014268727705), "686.8")

    def test_a_trailing_zero_that_is_a_real_figure_is_kept(self):
        """%.4g would print 0.0227 and quietly claim three figures, not four."""
        self.assertEqual(plots.fmt_sig(0.022697), "0.02270")
        self.assertEqual(plots.fmt_sig(1.2000004), "1.200")

    def test_a_number_too_big_or_too_small_goes_exponential_like_g_does(self):
        self.assertEqual(plots.fmt_sig(440466.0), "4.405e+05")
        self.assertEqual(plots.fmt_sig(0.0000123456), "1.235e-05")
        self.assertEqual(plots.fmt_sig(0), "0")

    def test_a_missing_number_renders_as_the_honest_phrase(self):
        self.assertEqual(plots.fmt_sig(None), "not available in this snapshot")
        self.assertEqual(plots.fmt_sig(float("nan")), "not available in this snapshot")

    def test_finite_refuses_everything_that_cannot_sit_on_an_axis(self):
        self.assertEqual(plots.finite("2.5"), 2.5)
        self.assertEqual(plots.finite(3), 3.0)
        for value in (None, "", "many", float("nan"), float("inf"), float("-inf"), [1]):
            with self.subTest(value=value):
                self.assertIsNone(plots.finite(value))


class TestPlotForResultNeverTakesTheHandlerDown(unittest.TestCase):
    """A figure is an extra. It must never be the reason a Slack reply fails."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="metabocausal_plots_")
        self.addCleanup(folder.cleanup)
        self.out = Path(folder.name)

    def test_a_result_that_is_not_a_result_is_a_None(self):
        for result in (None, {}, {"state": "A"}, {"state": None, "envelopes": None}, "A"):
            with self.subTest(result=result):
                self.assertIsNone(plots.plot_for_result(
                    result,
                    str(self.out),
                ))

    def test_an_envelope_that_is_not_a_dict_is_a_None_and_not_an_AttributeError(self):
        """`(env or {}).get("data")` let a non-empty non-dict through: a string and a list
        are both truthy and neither has `.get`. The docstring promises this never raises,
        and slack_app's try/except was the only thing making that look true."""
        for state, slot in (("A", "mr"), ("B", "instruments")):
            for broken in ("an envelope", [1, 2, 3], 7, ("mr",)):
                with self.subTest(state=state, broken=broken):
                    self.assertIsNone(plots.plot_for_result(
                        {
                            "state":      state,
                            "envelopes":  {slot: broken},
                            "metabolite": "urate",
                            "disease":    "gout",
                        },
                        str(self.out),
                    ))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_a_figure_that_cannot_be_saved_is_closed_rather_than_leaked(self):
        """slack_app is a persistent Socket Mode worker. A savefig that raises - a
        read-only cards/, a full disk, an antivirus hold - used to leave the Figure in
        pyplot's manager holding its canvas, one per failed mention."""
        real_savefig = plots.plt.Figure.savefig
        self.addCleanup(setattr, plots.plt.Figure, "savefig", real_savefig)

        def refuse(self, *args, **kwargs):
            raise OSError("cards/ is read-only")

        plots.plt.Figure.savefig = refuse
        before = set(plots.plt.get_fignums())
        with self.assertRaises(OSError):
            plots.plot_forest(
                plots.demo_result(PAIR_A)["envelopes"]["mr"],
                "urate -> gout",
                self.out / "unwritable.png",
            )
        self.assertEqual(set(plots.plt.get_fignums()), before)

    def test_a_state_a_result_with_an_empty_mr_envelope_draws_nothing(self):
        result = plots.demo_result(PAIR_C)
        result["state"] = "A"                       # the state says A, the envelope is empty
        self.assertIsNone(plots.plot_for_result(
            result,
            str(self.out),
        ))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_a_state_b_result_with_an_empty_instrument_envelope_draws_nothing(self):
        result = plots.demo_result(PAIR_C)
        result["state"] = "B"
        self.assertIsNone(plots.plot_for_result(
            result,
            str(self.out),
        ))

    def test_an_unknown_state_draws_nothing(self):
        result = plots.demo_result(PAIR_A)
        result["state"] = "Z"
        self.assertIsNone(plots.plot_for_result(
            result,
            str(self.out),
        ))

    def test_a_pair_with_no_ledger_path_still_gets_a_readable_filename(self):
        result = plots.demo_result(PAIR_A)
        result["ledger_path"] = ""
        path = plots.plot_for_result(
            result,
            str(self.out),
        )
        self.assertEqual(Path(path).name, f"urate_gout{plots.FOREST_SUFFIX}")

    def test_the_title_uses_the_name_that_was_asked_for(self):
        """1A's canonical label for urate is 7,9-dihydro-1H-purine-2,6,8(3H)-trione. A
        title is for a reader, so the requested name wins."""
        result = plots.demo_result(PAIR_A)
        self.assertEqual(plots.display_name(result["metabolite"]), "urate")
        self.assertEqual(plots.display_name(result["disease"]), "gout")
        self.assertEqual(plots.display_name("Gout"), "Gout")
        self.assertEqual(plots.display_name(None), "unknown")


# --------------------------------------------------------------------------------------
# the genetic-insight timeline
# --------------------------------------------------------------------------------------
#
# The dossier of a real run costs five requests per gene and the years cost one request
# per trial, so the fixtures here are synthetic - built in the shape 1E and
# tools/trials.py really return, on top of the same frozen State B result the other
# offline tests draw from. The one test that goes through the real `get_trial_dates`
# answers entirely from a stubbed cache, with `get_json` replaced by something that fails
# the test if it is ever called.

def report(
    nct    = None,
    phase  = None,
    status = None,
    why    = None,
    year   = None,
) -> dict:
    """One Open Targets clinical report, in the shape get_known_drugs returns."""
    return {
        "report_id":   (nct or "").lower() or "ema-label-1",
        "url":         f"https://clinicaltrials.gov/study/{nct}" if nct else "https://ema.invalid/x",
        "report_type": "trial" if nct else "label",
        "trial_phase": phase,
        "status":      status,
        "why_stopped": why,
        "year":        year,
        "source":      "ClinicalTrials.gov" if nct else "EMA",
        "diseases":    [],
    }


def drug(
    name,
    reports,
    stage = None,
) -> dict:
    return {
        "candidate_id":     f"CHEMBL{abs(hash(name)) % 100000}",
        "drug":             name,
        "drug_id":          f"CHEMBL{abs(hash(name)) % 100000}",
        "max_clinical_stage": stage,
        "clinical_reports": list(reports),
    }


def known_drugs(
    gene,
    drugs,
    status = "ok",
) -> dict:
    return {
        "tool":         "get_known_drugs",
        "args":         {"gene_symbol": gene},
        "source":       "Open Targets",
        "url":          "https://api.platform.opentargets.org/api/v4/graphql",
        "retrieved_at": "2026-09-11T12:00:00+00:00",
        "status":       status,
        "data":         {"gene": gene, "ensembl": "ENSG00000000001",
                         "count": len(drugs), "drugs": list(drugs)},
        "caveats":      [],
    }


def record(
    nct,
    start      = None,
    primary    = None,
    completion = None,
    status     = "COMPLETED",
    why        = None,
    estimated  = False,
) -> dict:
    """One ClinicalTrials.gov record, in the shape tools/trials.py returns. A year that is
    not here is None, exactly as the registry leaves it; `estimated` is the registry's own
    date type for a completion the sponsor has projected but not reached."""
    kind = "ESTIMATED" if estimated else "ACTUAL"
    return {
        "nct_id":                       nct,
        "brief_title":                  f"a trial called {nct}",
        "overall_status":               status,
        "why_stopped":                  why,
        "retrieved_at":                 "2026-09-11T12:00:00+00:00",
        "start_date":                   f"{start}-01-01" if start else None,
        "start_date_type":              "ACTUAL" if start else None,
        "start_year":                   start,
        "primary_completion_date":      f"{primary}-01-01" if primary else None,
        "primary_completion_date_type": kind if primary else None,
        "primary_completion_year":      primary,
        "completion_date":              f"{completion}-01-01" if completion else None,
        "completion_date_type":         kind if completion else None,
        "completion_year":              completion,
    }


def dates_envelope(
    records,
    failed = 0,
) -> dict:
    return {
        "tool":         "get_trial_dates",
        "args":         {},
        "source":       "ClinicalTrials.gov API v2 (studies)",
        "url":          "https://clinicaltrials.gov/api/v2/studies/",
        "retrieved_at": "2026-09-11T12:00:00+00:00",
        "status":       "ok" if records else "empty",
        "data":         {
            "dates":        {row["nct_id"]: row for row in records},
            "n_requested":  len(records) + failed,
            "n_looked_up":  len(records) + failed,
            "n_from_cache": len(records),
            "n_fetched":    0,
            "n_failed":     failed,
            "n_undated":    sum(
                1 for row in records
                if not any(row.get(key) for key in
                           ("start_year", "primary_completion_year", "completion_year"))
            ),
            "cap":          plots.TRIAL_LOOKUP_CAP,
            "failed":       {},
            "queries":      [],
        },
        "caveats":      [],
    }


class TimelineCase(FigureCase):
    """A State B run from the frozen snapshot with a synthetic 1E dossier bolted on - the
    same demo_result path the other offline tests use, plus the envelopes the gene stage
    would have written."""

    def setUp(self):
        super().setUp()
        self.record_text()

    def result_with(
        self,
        dossier,
        pair_key = PAIR_B,
    ) -> dict:
        result = plots.demo_result(pair_key)
        result["envelopes"]["dossier"] = dossier
        return result

    def stub_dates(
        self,
        records,
        failed = 0,
    ):
        """Answer the registry lookup from a fixture. No request, and no import of the
        tools package into a drawing test."""
        real = plots._trial_dates
        self.addCleanup(setattr, plots, "_trial_dates", real)
        envelope = dates_envelope(records, failed)
        plots._trial_dates = lambda ids, cap=None: envelope
        return envelope

    def draw(
        self,
        result,
    ):
        return plots.plot_genetic_insight(
            result,
            str(self.out),
        )


class TestTheGeneticInsightTimeline(TimelineCase):

    def dossier(self):
        return {
            "CPS1": {
                "get_known_drugs": known_drugs("CPS1", [
                    drug(
                        "CARGLUMIC ACID",
                        [
                            report("NCT00000001", 2),
                            report("NCT00000002", 3, "TERMINATED",
                                   "insufficient enrollment and a reason far longer than the label"),
                            report(),                        # a label: no trial id, undated
                        ],
                        stage = 4,
                    ),
                ]),
            },
            "GLDC": {
                "get_known_drugs": known_drugs("GLDC", [], status="empty"),
            },
        }

    def records(self):
        return [
            record("NCT00000001", start=2008, primary=2018),
            record(
                "NCT00000002",
                start   = 2012,
                primary = 2015,
                status  = "TERMINATED",
                why     = "insufficient enrollment and a reason far longer than the label",
            ),
        ]

    def test_a_dated_dossier_gets_a_png_named_after_the_run(self):
        self.stub_dates(self.records())
        path = self.draw(self.result_with(self.dossier()))
        target = self.assert_is_a_real_png(path)
        self.assertTrue(target.name.endswith(plots.TIMELINE_SUFFIX), target.name)

    def test_the_footer_carries_the_owners_sentence_first(self):
        self.stub_dates(self.records())
        self.draw(self.result_with(self.dossier()))
        self.assertEqual(self.footers[0][0], plots.TIMELINE_FOOTER)
        self.assertIn("a drug's stage for one disease is never its stage for another",
                      self.footer_text)
        self.assertIn("Years from ClinicalTrials.gov records.", self.footer_text)

    def test_an_undated_report_is_counted_on_the_figure_and_placed_nowhere(self):
        """A report with no trial id was never sent to the registry at all - it is
        "no registry id, not queried", a different fact from a report the registry WAS
        asked about and answered with no date (T3). Either way it is counted in words ON
        the figure; a marker at a guessed year would be an invention on the one figure
        whose whole claim is chronology."""
        self.stub_dates(self.records())
        self.draw(self.result_with(self.dossier()))
        self.assertIn("1 retrieved report(s) carry no registry id", self.footer_text)
        self.assertIn("no registry id - not queried", self.footer_text)
        self.assertIn("never placed on a guessed year", self.footer_text)
        self.assertIn("2 dated reports drawn", self.subtitle_text)

    def test_a_registry_record_with_no_date_at_all_is_undated_too(self):
        """The id resolved, the record came back, and it carries no date. That is undated
        because the registry WAS asked (T3) - not "this year" and not the year of the
        trial beside it, and not the same fact as the third report, which carries no
        trial id at all and so was never queried."""
        self.stub_dates([
            record("NCT00000001", start=2008, primary=2018),
            record("NCT00000002"),
        ])
        self.draw(self.result_with(self.dossier()))
        self.assertIn("1 retrieved report(s) carry no registry id", self.footer_text)
        self.assertIn(
            "1 retrieved report(s) were queried and the registry carries no year",
            self.footer_text,
        )
        self.assertIn("1 dated report drawn", self.subtitle_text)

    def test_a_failed_lookup_is_no_information_and_says_so(self):
        self.stub_dates(self.records(), failed=1)
        self.draw(self.result_with(self.dossier()))
        self.assertIn("1 registry lookup(s) failed", self.footer_text)
        self.assertIn("no information rather than as trials without dates", self.footer_text)

    def test_the_exposure_gwas_years_are_marked_from_the_instruments_envelope(self):
        """The whole sentence this figure exists for - "the genetics were on the record in
        2020 and this programme stopped in 2016" - needs BOTH years retrieved."""
        self.stub_dates(self.records())
        self.draw(self.result_with(self.dossier()))
        self.assertIn("2 exposure GWAS years marked", self.subtitle_text)

    def test_a_year_open_targets_recorded_itself_is_named_as_not_a_registry_lookup(self):
        """Open Targets carries `year: null` on every clinical report this project has
        seen. If one ever arrives it is retrieved too - and the footer promises the
        registry, so the figure says which markers did not come from it."""
        self.stub_dates([])
        dossier = {
            "CPS1": {"get_known_drugs": known_drugs("CPS1", [
                drug("A DRUG", [report("NCT00000009", 2, year=1999)], stage=2),
            ])},
        }
        self.draw(self.result_with(dossier))
        self.assertIn("not a ClinicalTrials.gov lookup", self.footer_text)

    def test_a_projected_completion_is_drawn_as_a_projection_and_said_to_be_one(self):
        """The registry labels each date ACTUAL or ESTIMATED. A bar drawn solid to an
        ESTIMATED completion is a sponsor's plan drawn as history."""
        self.stub_dates([
            record("NCT00000001", start=2008, primary=2032, estimated=True),
            record("NCT00000002", start=2012, primary=2015),
        ])
        self.draw(self.result_with(self.dossier()))
        self.assertIn("1 bar(s) are dotted", self.footer_text)
        self.assertIn("the sponsor's projection", self.footer_text)
        self.assertIn("not a milestone that happened", self.footer_text)

    def test_nothing_is_said_about_projections_when_every_date_is_actual(self):
        self.stub_dates(self.records())
        self.draw(self.result_with(self.dossier()))
        self.assertNotIn("dotted", self.footer_text)

    def test_the_lane_cap_is_printed_when_it_bites(self):
        self.stub_dates([record(f"NCT0000000{index}", start=2000 + index) for index in range(9)])
        dossier = {
            "CPS1": {"get_known_drugs": known_drugs("CPS1", [
                drug(
                    f"DRUG {index}",
                    [report(f"NCT0000000{index}", 2)],
                    stage = index,
                )
                for index in range(9)
            ])},
        }
        self.draw(self.result_with(dossier))
        self.assertIn("9 drug(s) retrieved, 8 drawn", self.footer_text)
        self.assertIn("a lane with a drawn dated report first, earliest report first", self.footer_text)
        self.assertIn("8 drug lane(s)", self.subtitle_text)

    def test_a_drug_with_no_clinical_report_is_counted_rather_than_given_a_lane(self):
        self.stub_dates(self.records())
        dossier = self.dossier()
        dossier["CPS1"]["get_known_drugs"]["data"]["drugs"].append(
            drug("A CANDIDATE WITH NO REPORT", [], stage=1)
        )
        self.draw(self.result_with(dossier))
        self.assertIn("1 retrieved drug(s) carry no clinical report at all", self.footer_text)

    def test_no_drug_with_a_dated_report_draws_nothing_at_all(self):
        """No lane, no figure. An axis of years with nothing on it reads as "no trials"
        and means "no date was retrieved"."""
        self.stub_dates([])
        path = self.draw(self.result_with(self.dossier()))
        self.assertIsNone(path)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_a_run_with_no_dossier_at_all_draws_nothing(self):
        self.stub_dates(self.records())
        self.assertIsNone(self.draw(plots.demo_result(PAIR_B)))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_a_broken_dossier_is_a_None_and_not_a_crash(self):
        """A figure is an extra. It must never be the reason a Slack reply fails."""
        self.stub_dates(self.records())
        for broken in (None, "a dossier", [1, 2, 3], {"CPS1": "not a dict"},
                       {"CPS1": {"get_known_drugs": "not an envelope"}},
                       {"CPS1": {"get_known_drugs": {"data": {"drugs": [None, 7]}}}}):
            with self.subTest(broken=broken):
                result = plots.demo_result(PAIR_B)
                result["envelopes"]["dossier"] = broken
                self.assertIsNone(self.draw(result))
        for broken in (None, {}, "a result", {"envelopes": None}):
            with self.subTest(result=broken):
                self.assertIsNone(plots.plot_genetic_insight(
                    broken,
                    str(self.out),
                ))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_the_lookup_cannot_be_reached_and_the_figure_still_refuses_to_guess(self):
        """`_trial_dates` returns None when tools/trials.py cannot be imported or called.
        Every report is then undated, and undated draws nothing."""
        real = plots._trial_dates
        self.addCleanup(setattr, plots, "_trial_dates", real)
        plots._trial_dates = lambda ids, cap=None: None
        self.assertIsNone(self.draw(self.result_with(self.dossier())))


class TestTheTimelinePartsOnTheirOwn(unittest.TestCase):
    """The four pure helpers, where the assertions can be about the exact string rather
    than about a picture of it."""

    def test_an_nct_id_is_read_out_of_the_report_and_never_reconstructed(self):
        self.assertEqual(plots._nct_id(report("NCT01968967")), "NCT01968967")
        self.assertEqual(
            plots._nct_id({"report_id": "nct01968967", "url": None}),
            "NCT01968967",
        )
        self.assertEqual(
            plots._nct_id({"url": "https://clinicaltrials.gov/study/NCT02100514"}),
            "NCT02100514",
        )
        for empty in (None, {}, {"report_id": "EMA/12345"}, {"report_id": "NCT123"}, "a string"):
            with self.subTest(empty=empty):
                self.assertEqual(plots._nct_id(empty), "")

    def test_a_stopping_reason_is_the_registrys_own_cut_to_the_label_budget(self):
        markers, undated = plots._lane_markers(
            {
                "gene":    "CPS1",
                "drug":    "A DRUG",
                "stage":   3.0,
                "reports": [report("NCT00000002", 3, "TERMINATED", "x" * 90), report()],
            },
            {"NCT00000002": record(
                "NCT00000002",
                start  = 2012,
                status = "TERMINATED",
                why    = "insufficient enrollment because the sponsor could not recruit",
            )},
        )
        self.assertEqual(undated["no_id"], 1, "the label carries no trial id")
        self.assertEqual(undated["no_date"], 0)
        self.assertEqual(len(markers), 1)
        self.assertTrue(markers[0]["stopped"])
        self.assertEqual(markers[0]["status_source"], "registry")
        self.assertEqual(markers[0]["why_source"], "registry")
        self.assertLessEqual(len(markers[0]["why"]), plots.MAX_WHY_CHARS)
        self.assertTrue(markers[0]["why"].endswith("..."))
        self.assertTrue(markers[0]["why"].startswith("insufficient enrollment"))

    def test_a_free_text_status_that_merely_contains_a_terminal_word_is_not_stopped(self):
        """T2: the terminal state is an EXACT match against the registry's controlled
        vocabulary, not a substring test on whatever free text the report carries."""
        markers, _undated = plots._lane_markers(
            {
                "gene":    "CPS1",
                "drug":    "A DRUG",
                "stage":   3.0,
                "reports": [report(
                    "NCT00000002",
                    3,
                    "recruiting; an earlier study was terminated",
                )],
            },
            {"NCT00000002": record("NCT00000002", start=2012, status="")},
        )
        self.assertEqual(len(markers), 1)
        self.assertFalse(markers[0]["stopped"])

    def test_status_and_reason_are_each_attributed_to_their_own_source(self):
        """T1: a fallback from the registry record to the dossier's own report must say
        which one actually supplied the field - never credited to the registry when the
        registry left it blank."""
        markers, _undated = plots._lane_markers(
            {
                "gene":    "CPS1",
                "drug":    "A DRUG",
                "stage":   3.0,
                "reports": [report(
                    "NCT00000002",
                    3,
                    "TERMINATED",
                    "competitor product was safer",
                )],
            },
            {"NCT00000002": record("NCT00000002", start=2012, status="")},
        )
        self.assertEqual(len(markers), 1)
        self.assertTrue(markers[0]["stopped"])
        self.assertEqual(markers[0]["status_source"], "open targets")
        self.assertEqual(markers[0]["why_source"], "open targets")

    def test_no_start_year_falls_back_to_completion_and_says_so(self):
        """T7: a marker silently placed on a completion year would be indistinguishable
        from a real start-year marker on an axis labelled "start"."""
        markers, _undated = plots._lane_markers(
            {
                "gene":    "CPS1",
                "drug":    "A DRUG",
                "stage":   3.0,
                "reports": [report("NCT00000002", 3)],
            },
            {"NCT00000002": record("NCT00000002", start=None, primary=2016)},
        )
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["x0"], 2016)
        self.assertTrue(markers[0]["start_is_completion"])

    def test_a_phase_the_source_did_not_record_is_not_a_phase_zero(self):
        self.assertEqual(plots._phase_text(3), "phase 3")
        self.assertEqual(plots._phase_text(2.0), "phase 2")
        self.assertEqual(plots._phase_text(0.5), "phase 0.5")
        self.assertEqual(plots._phase_text(None), "phase not recorded")
        self.assertEqual(plots._phase_text(""), "phase not recorded")
        self.assertEqual(plots._phase_text("PHASE_III"), "PHASE_III")

    def test_one_dashed_line_per_distinct_gwas_year_naming_the_datasets(self):
        env = plots.demo_result(PAIR_B)["envelopes"]["instruments"]
        years, shortened = plots._gwas_years(env)
        self.assertTrue(years)
        for year, label in years:
            self.assertIsInstance(year, int)
            self.assertIn("genetic evidence:", label)
            self.assertIn(str(year), label)
        self.assertEqual(len(years), len({year for year, _label in years}))
        self.assertEqual(shortened, 0)

    def test_three_datasets_in_one_year_are_one_line_that_counts_them(self):
        env = {"data": {"exposures": [
            {"id": "met-d-Gly", "year": 2020},
            {"id": "met-d-Ala", "year": 2020},
            {"id": "met-d-Val", "year": 2020},
            {"id": "no-year", "year": None},
        ]}}
        years, shortened = plots._gwas_years(env)
        self.assertEqual(len(years), 1)
        self.assertIn("+1 more", years[0][1])
        self.assertIn("2020", years[0][1])
        self.assertEqual(shortened, 0)

    def test_a_gwas_dataset_id_over_budget_is_shortened_and_counted(self):
        """T5: the exposure-dataset id is retrieved text like any other and carries the
        same character budget every other label on this figure carries."""
        env = {"data": {"exposures": [{"id": "ebi-a-GCST" + "9" * 60, "year": 2020}]}}
        years, shortened = plots._gwas_years(env)
        self.assertEqual(shortened, 1)
        self.assertIn("...", years[0][1])
        self.assertLessEqual(len(years[0][1]), len(f"genetic evidence: {'x' * plots.MAX_ID_CHARS} 2020") + 1)

    def test_lanes_preserve_dossier_order_and_do_not_prejudge_by_cross_indication_stage(self):
        """T6: max_clinical_stage is a cross-indication number, so _drug_lanes must not
        sort by it - ordering by drawn evidence is the caller's job, once it knows which
        lanes actually have a retrieved year."""
        lanes, genes, bare = plots._drug_lanes({
            "A": {"get_known_drugs": known_drugs("A", [
                drug("EARLY", [report("NCT00000001")], stage=1),
                drug("LATE", [report("NCT00000002")], stage=4),
                drug("NO STAGE", [report("NCT00000003")], stage=None),
                drug("NO REPORT", [], stage=4),
            ])},
            "B": {"get_known_drugs": known_drugs("B", [], status="empty")},
        })
        self.assertEqual([lane["drug"] for lane in lanes], ["EARLY", "LATE", "NO STAGE"])
        self.assertEqual(genes, 2)
        self.assertEqual(bare, 1)


class TestTheTimelineReadsRealRegistryRecordsWithoutARequest(TimelineCase):
    """One test through the REAL tools/trials.py, answering from a stubbed cache with the
    HTTP call replaced by something that fails the test if it is ever reached."""

    def test_a_cached_record_costs_no_request_and_reaches_the_figure(self):
        from tools import _common, trials

        self.addCleanup(setattr, trials, "load_cache", trials.load_cache)
        self.addCleanup(setattr, _common, "get_json", _common.get_json)

        def refuse(*args, **kwargs):
            raise AssertionError("this test must not send a request")

        _common.get_json = refuse
        cached = {row["nct_id"]: row for row in [
            record("NCT00000001", start=2008, primary=2018),
            record("NCT00000002", start=2012, primary=2015,
                   status="WITHDRAWN", why="Lack of funding"),
        ]}
        trials.load_cache = lambda *args, **kwargs: (dict(cached), [])

        path = self.draw(self.result_with({
            "CPS1": {
                "get_known_drugs": known_drugs("CPS1", [
                    drug(
                        "CARGLUMIC ACID",
                        [report("NCT00000001", 2), report("NCT00000002", 3, "WITHDRAWN",
                                                          "Lack of funding")],
                        stage = 4,
                    ),
                ]),
            },
        }))
        self.assert_is_a_real_png(path)
        self.assertIn("2 dated reports drawn", self.subtitle_text)
        self.assertNotIn("carry no year in the registry", self.footer_text)


class TestTheFrozenSnapshotLoader(unittest.TestCase):

    def test_demo_result_has_exactly_run_pair_s_keys(self):
        self.assertEqual(set(plots.demo_result(PAIR_A)), RESULT_KEYS)

    def test_the_envelopes_are_keyed_the_way_run_pair_keys_them(self):
        envelopes = plots.demo_result(PAIR_A)["envelopes"]
        self.assertEqual(
            set(envelopes),
            {"mr", "instruments", "outcomes", "catalog"},
        )
        self.assertEqual(envelopes["mr"]["tool"], "get_mr_result")
        self.assertEqual(envelopes["instruments"]["tool"], "get_mqtl_instruments")

    def test_the_result_says_it_is_a_snapshot_and_not_a_live_run(self):
        self.assertIn("cached snapshot", " ".join(plots.demo_result(PAIR_B)["notes"]))

    def test_a_pair_that_is_not_in_the_file_raises_rather_than_returning_empty(self):
        with self.assertRaises(KeyError):
            plots.demo_result("urate|a disease nobody cached")


if __name__ == "__main__":
    unittest.main(verbosity=2)
