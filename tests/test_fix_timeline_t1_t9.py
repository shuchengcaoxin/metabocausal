"""Permanent regression tests for the Genetic Insights timeline figure fixes T1, T2, T3,
T5, T6, T7, T8 and T9.

    python -m unittest tests.test_fix_timeline_t1_t9 -v          # from the repo root

Adapted from the probe evidence under
docs/research/section9_adversarial/rerun_2026-09-17/new_probes/timeline/probe_timeline.py
(cases GI02, GI03, GI04, GI08, GI12, GI13, GI14, GI15, GI17, GI19, GI20, GI21 and the
module's own `mathtext_evidence` check). Each test below rebuilds the same fixture shape
those cases used, through the real `plots.plot_genetic_insight` and its helpers - not a
reimplemented model of them - and asserts the FIXED outcome. The fixture builders
(`report`, `drug`, `known_drugs`, `record`, `TimelineCase`) are the ones
`tests/test_plots.py` already uses for this figure, so a fixture here and a fixture there
are never independently invented.

Offline: `plots._trial_dates` is stubbed per test through `TimelineCase.stub_dates`,
exactly as `tests/test_plots.py` does. No network, no display backend (Agg, set by
plots.py itself on import).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib.text

import plots
from tests.test_plots import (
    PAIR_B,
    TimelineCase,
    drug,
    known_drugs,
    record,
    report,
)


class DrawingCase(TimelineCase):
    """Adds canvas-level capture on top of `TimelineCase`'s header/footer capture, the
    same measurement `probe_timeline.py`'s `install_text_capture` makes: every
    `matplotlib.text.Text` string actually drawn, its pixel box, and the x-axis tick
    labels realised at save time."""

    def setUp(self):
        super().setUp()
        self.canvas_texts = []
        self.tick_labels = []
        self.collisions = []
        real_save = plots._save

        def capturing_save(fig, out_path):
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            # Tick labels (the year axis, the lane names on the y-axis) are excluded from
            # the collision geometry, the same exclusion `probe_timeline.py`'s own capture
            # makes: matplotlib keeps a Text for every tick the locator proposed, and an
            # axis of consecutive year labels legitimately sits close together.
            ticks = set()
            for axes in fig.axes:
                for axis in (axes.xaxis, axes.yaxis):
                    for tick in list(axis.get_major_ticks()) + list(axis.get_minor_ticks()):
                        ticks.add(id(tick.label1))
                        ticks.add(id(tick.label2))
            boxes = []
            for artist in fig.findobj(matplotlib.text.Text):
                value = artist.get_text()
                if not value or not value.strip():
                    continue
                self.canvas_texts.append(value)
                if id(artist) in ticks:
                    continue
                try:
                    boxes.append((value, artist.get_window_extent(renderer)))
                except Exception:
                    continue
            for index, (left_text, left_box) in enumerate(boxes):
                for right_text, right_box in boxes[index + 1:]:
                    if left_box.overlaps(right_box):
                        self.collisions.append((left_text, right_text))
            for axes in fig.axes:
                self.tick_labels.extend(
                    label.get_text() for label in axes.get_xticklabels() if label.get_text()
                )
            return real_save(fig, out_path)

        plots._save = capturing_save
        self.addCleanup(setattr, plots, "_save", real_save)


class TestT1StatusAndReasonAttribution(TimelineCase):
    """T1: a fallback from the registry record to the dossier's own report must say
    which source actually supplied the field - never credited to the registry when the
    registry left it blank (probe GI03, GI04)."""

    def test_registry_status_but_report_supplied_reason_is_attributed_to_each(self):
        """GI03: the registry record carries the TERMINATED status but no why_stopped;
        the dossier report supplies the reason."""
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "torcetrapib",
                    [report(
                        "NCT00134264", 3, why="stopped early for overwhelming benefit",
                    )],
                    stage = 3,
                ),
            ])},
        }
        self.stub_dates([record(
            "NCT00134264",
            start  = 2004,
            primary = 2006,
            status = "TERMINATED",
            why    = None,
        )])
        self.draw(self.result_with(dossier))
        self.assertIn(
            "1 stopped report(s) identified from the registry's own status.",
            self.footer_text,
        )
        self.assertIn(
            "1 stopped report(s) carry a reason from the dossier's own report, not the "
            "registry",
            self.footer_text,
        )
        self.assertNotIn("carry the registry's own reason", self.footer_text)

    def test_report_supplied_both_status_and_reason_are_attributed_to_the_report(self):
        """GI04: the registry record carries no overall_status at all; the dossier
        report alone declares TERMINATED and supplies the reason."""
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "torcetrapib",
                    [report(
                        "NCT00134264", 3, "TERMINATED", "competitor product was safer",
                    )],
                    stage = 3,
                ),
            ])},
        }
        self.stub_dates([record(
            "NCT00134264",
            start  = 2004,
            primary = 2006,
            status = "",
        )])
        self.draw(self.result_with(dossier))
        self.assertIn(
            "1 stopped report(s) identified from the dossier's own report status, not a "
            "registry lookup.",
            self.footer_text,
        )
        self.assertIn(
            "1 stopped report(s) carry a reason from the dossier's own report, not the "
            "registry",
            self.footer_text,
        )
        self.assertNotIn("identified from the registry's own status", self.footer_text)
        self.assertNotIn("carry the registry's own reason", self.footer_text)


class TestT2AnchoredNotSubstringAndNotStrictEquality(DrawingCase):
    """T2: the stopped state is ANCHORED at the start of the status string - neither a
    substring test on free text (which stopped four reports out of two) nor strict
    equality (which silently dropped a retrieved stopping reason on a free-text terminal
    status). Probe GI15.

    The registry records below carry `status=""` on purpose, matching the probe's own
    `registry_record(overall_status="")` default: a non-empty registry status shadows the
    dossier report's free-text status in `_lane_markers`, so a fixture that let the
    default `"COMPLETED"` through would never enter the branch this class is named for.
    """

    def test_a_status_that_merely_contains_a_terminal_word_does_not_stop_the_report(self):
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "torcetrapib",
                    [
                        report(
                            "NCT00134264",
                            3,
                            "recruiting; an earlier study was terminated",
                            "see the earlier study",
                        ),
                        report(
                            "NCT00134290",
                            3,
                            "COMPLETED - no safety signal was terminated early",
                            "none",
                        ),
                    ],
                    stage = 3,
                ),
            ])},
        }
        self.stub_dates([
            record(
                "NCT00134264",
                start   = 2004,
                primary = 2006,
                status  = "",
            ),
            record(
                "NCT00134290",
                start   = 2005,
                primary = 2007,
                status  = "",
            ),
        ])
        self.draw(self.result_with(dossier))
        self.assertNotIn("terminated:", self.canvas_texts_joined)
        self.assertNotIn("stopped report(s)", self.footer_text)

    def test_the_two_undrawn_reasons_are_counted_rather_than_silently_dropped(self):
        """Both reports above carry a retrieved `why_stopped` that is not drawn, because
        neither report is stopped. A retrieved field that leaves the canvas with nothing
        saying so is the one thing this module's footer contract forbids."""
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "torcetrapib",
                    [
                        report(
                            "NCT00134264",
                            3,
                            "recruiting; an earlier study was terminated",
                            "see the earlier study",
                        ),
                        report(
                            "NCT00134290",
                            3,
                            "COMPLETED - no safety signal was terminated early",
                            "none",
                        ),
                    ],
                    stage = 3,
                ),
            ])},
        }
        self.stub_dates([
            record(
                "NCT00134264",
                start   = 2004,
                primary = 2006,
                status  = "",
            ),
            record(
                "NCT00134290",
                start   = 2005,
                primary = 2007,
                status  = "",
            ),
        ])
        self.draw(self.result_with(dossier))
        self.assertIn(
            "2 retrieved stopping reason(s) are not drawn here", self.footer_text
        )

    def test_a_free_text_terminal_status_still_stops_the_report(self):
        """The other half of T2, and the half strict equality broke: the registry copies
        its controlled state into a free-text field, so "Terminated due to futility" is
        the registry saying the study stopped."""
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "torcetrapib",
                    [report(
                        "NCT00134264",
                        3,
                        "Terminated due to futility",
                        "interim analysis",
                    )],
                    stage = 3,
                ),
            ])},
        }
        self.stub_dates([record(
            "NCT00134264",
            start   = 2004,
            primary = 2006,
            status  = "",
        )])
        self.draw(self.result_with(dossier))
        self.assertIn(
            "1 stopped report(s) identified from the dossier's own report status",
            self.footer_text,
        )
        self.assertTrue(any("interim analysis" in text for text in self.canvas_texts))

    def test_the_status_test_is_anchored_on_the_helper_itself(self):
        self.assertTrue(plots._is_terminal_status("TERMINATED"))
        self.assertTrue(plots._is_terminal_status("  terminated  "))
        self.assertTrue(plots._is_terminal_status("Terminated due to futility"))
        self.assertTrue(plots._is_terminal_status("WITHDRAWN_PRE_ENROLLMENT"))
        self.assertFalse(plots._is_terminal_status(""))
        self.assertFalse(plots._is_terminal_status(None))
        self.assertFalse(plots._is_terminal_status("ACTIVE_NOT_RECRUITING"))
        self.assertFalse(plots._is_terminal_status("recruiting; an earlier study was terminated"))
        self.assertFalse(plots._is_terminal_status("COMPLETED - no safety signal was terminated early"))

    @property
    def canvas_texts_joined(self) -> str:
        return "\n".join(self.canvas_texts)


class TestT3UndatedProvenance(TimelineCase):
    """T3: the undated note may only speak about reports the registry was actually
    asked about; a report with no NCT id at all was never queried (probe GI02, and the
    complementary "asked but no date" half)."""

    def test_reports_with_no_nct_id_are_never_queried_not_undated_in_the_registry(self):
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "torcetrapib",
                    [
                        report("NCT00134264", 3),
                        report(None, 4),
                        report(None, "phase not recorded"),
                        report(None, 2),
                    ],
                    stage = 3,
                ),
            ])},
        }
        self.stub_dates([record("NCT00134264", start=2004, primary=2006)])
        self.draw(self.result_with(dossier))
        self.assertIn("3 retrieved report(s) carry no registry id", self.footer_text)
        self.assertIn("no registry id - not queried", self.footer_text)
        self.assertNotIn("were queried and the registry carries no year", self.footer_text)

    def test_a_report_that_was_queried_and_answered_with_no_date_is_a_different_count(self):
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "torcetrapib",
                    [report("NCT00134264", 3), report("NCT00134290", 2)],
                    stage = 3,
                ),
            ])},
        }
        self.stub_dates([
            record("NCT00134264", start=2004, primary=2006),
            record("NCT00134290"),                          # resolved, no date at all
        ])
        self.draw(self.result_with(dossier))
        self.assertIn(
            "1 retrieved report(s) were queried and the registry carries no year",
            self.footer_text,
        )
        self.assertNotIn("carry no registry id", self.footer_text)

    def test_ids_past_the_lookup_cap_were_never_sent_and_are_not_called_queried(self):
        """GI18's other half, and the reachable one: `get_trial_dates` requests only
        `wanted[:cap]`, so an id past the cap never leaves the process. Saying those
        reports "were queried and the registry carries no year" is the T3 defect on the
        same footer line the split was added to."""
        reports = [report(f"NCT1000{index:04d}", 3) for index in range(6)]
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug("torcetrapib", reports, stage=3),
            ])},
        }
        envelope = self.stub_dates([
            record(
                "NCT10000000",
                start   = 2004,
                primary = 2006,
            ),
            record("NCT10000001"),
        ])
        # Two ids requested of six found: the registry never saw the other four.
        envelope["data"]["n_requested"] = 6
        envelope["data"]["n_looked_up"] = 2
        self.draw(self.result_with(dossier))
        self.assertIn(
            "4 retrieved report(s) carry a registry id that was not requested",
            self.footer_text,
        )
        self.assertIn("not queried", self.footer_text)
        self.assertIn(
            "1 retrieved report(s) were queried and the registry carries no year",
            self.footer_text,
        )

    def test_a_failed_lookup_is_no_information_not_a_registry_answer(self):
        """A failed lookup writes to `data["failed"]`, never to `data["dates"]`. The
        report it belongs to was asked about and nothing came back - which is not the
        same claim as "the registry carries no year for it"."""
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "torcetrapib",
                    [
                        report("NCT00134264", 3),
                        report("NCT00134290", 2),
                    ],
                    stage = 3,
                ),
            ])},
        }
        envelope = self.stub_dates(
            [record(
                "NCT00134264",
                start   = 2004,
                primary = 2006,
            )],
            failed = 1,
        )
        envelope["data"]["failed"] = {"NCT00134290": "HTTP 500"}
        envelope["data"]["n_looked_up"] = 2
        self.draw(self.result_with(dossier))
        self.assertIn(
            "1 retrieved report(s) were queried and the registry lookup failed",
            self.footer_text,
        )
        self.assertNotIn("the registry carries no year", self.footer_text)

    def test_when_the_lookup_cannot_be_made_no_report_is_described_as_queried(self):
        """`_trial_dates` returns None on its import/tools guard: `dates` is then empty
        and nothing was asked. One report carries an Open Targets year of its own, so the
        figure is still drawn - and the other report must not be reported as a registry
        answer (probe GI18)."""
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "torcetrapib",
                    [
                        report("NCT00134264", 3, year=2004),
                        report("NCT00134290", 2),
                    ],
                    stage = 3,
                ),
            ])},
        }
        real = plots._trial_dates
        self.addCleanup(setattr, plots, "_trial_dates", real)
        plots._trial_dates = lambda ids, cap=None: None
        self.draw(self.result_with(dossier))
        self.assertIn(
            "1 retrieved report(s) carry a registry id that was not requested",
            self.footer_text,
        )
        self.assertNotIn("were queried", self.footer_text)


class TestT5CharacterBudgets(DrawingCase):
    """T5: trial_phase, the stop-label status and the GWAS dataset id all carry the same
    character budget every other label on this figure carries, and the marker stagger
    never repeats an offset (probe GI08, GI17, GI20)."""

    def test_a_long_free_text_phase_is_shortened_and_counted(self):
        long_phase = (
            "Phase 4 - approved by the FDA for every indication and recommended first line"
        )
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug("torcetrapib", [report("NCT00134264", long_phase)], stage=3),
            ])},
        }
        self.stub_dates([record("NCT00134264", start=2004, primary=2006)])
        self.draw(self.result_with(dossier))
        self.assertNotIn(long_phase, self.canvas_texts)
        self.assertTrue(any(
            text.startswith(long_phase[: plots.MAX_PHASE_CHARS - 3]) and text.endswith("...")
            for text in self.canvas_texts
        ))
        self.assertIn("phase label(s) shortened to fit", self.footer_text)

    def test_five_reports_in_one_year_get_five_distinct_offsets_not_four(self):
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "torcetrapib",
                    [
                        report("NCT00134261", "Phase 2/Phase 3"),
                        report("NCT00134262", "Phase 4 post-marketing surveillance"),
                        report("NCT00134263", "Phase 1 healthy volunteers"),
                        report("NCT00134264", "Phase 3 pivotal outcomes"),
                        report("NCT00134265", "Phase 2b dose finding"),
                    ],
                    stage = 3,
                ),
            ])},
        }
        self.stub_dates([
            record(f"NCT0013426{i}", start=2004, primary=2008) for i in range(1, 6)
        ])
        self.draw(self.result_with(dossier))
        self.assertEqual(
            self.collisions, [],
            f"two phase labels landed on top of each other: {self.collisions}",
        )

    def test_the_stagger_never_leaves_its_own_lane_and_says_what_it_did_not_draw(self):
        """The replacement stagger must stay inside the lane's own half-row: an offset
        that grows without bound reaches +/-1.00 - the centre line of the adjacent lane -
        by a lane's ninth same-year report, putting one drug's phase label on another
        drug's row. Past the end of the ladder the label is not drawn and is counted."""
        reports = [report(f"NCT002000{index:02d}", f"phase {index}") for index in range(10)]
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug("torcetrapib", reports, stage=3),
                drug("evacetrapib", [report("NCT00134264", 3)], stage=3),
            ])},
        }
        self.stub_dates(
            [
                record(
                    f"NCT002000{index:02d}",
                    start   = 2004,
                    primary = 2008,
                )
                for index in range(10)
            ]
            + [record(
                "NCT00134264",
                start   = 2004,
                primary = 2008,
            )]
        )
        self.draw(self.result_with(dossier))
        self.assertEqual(
            self.collisions, [],
            f"two labels landed on top of each other: {self.collisions}",
        )
        self.assertIn("phase label(s) not drawn", self.footer_text)
        self.assertIn("reaching another drug's row", self.footer_text)

    def test_reports_at_different_years_are_not_pushed_off_the_lane_at_all(self):
        """The rung is counted within the marker's own start year, so ten reports at ten
        different years never exhaust the ladder: they do not collide horizontally, so
        they never needed staggering."""
        reports = [report(f"NCT003000{index:02d}", f"phase {index}") for index in range(10)]
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug("torcetrapib", reports, stage=3),
            ])},
        }
        self.stub_dates([
            record(
                f"NCT003000{index:02d}",
                start   = 2000 + index * 2,
                primary = 2001 + index * 2,
            )
            for index in range(10)
        ])
        self.draw(self.result_with(dossier))
        self.assertNotIn("phase label(s) not drawn", self.footer_text)

    def test_a_long_gwas_dataset_id_is_shortened_and_counted(self):
        long_id = "ebi-a-GCST" + "9" * 60 + "-a-dataset-name-nobody-budgeted"
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug("torcetrapib", [report("NCT00134264", 3)], stage=3),
            ])},
        }
        self.stub_dates([record("NCT00134264", start=2004, primary=2006)])
        result = self.result_with(dossier)
        result["envelopes"]["instruments"]["data"]["exposures"] = [
            {"id": "met-d-HDL", "year": 2020},
            {"id": long_id, "year": 2099},
        ]
        self.draw(result)
        self.assertNotIn(long_id, self.canvas_texts_joined)
        self.assertIn("exposure GWAS dataset id(s) shortened to fit", self.footer_text)

    @property
    def canvas_texts_joined(self) -> str:
        return "\n".join(self.canvas_texts)


class TestT6EvidenceOrderedLanesNotCrossIndicationStage(DrawingCase):
    """T6: the lane label names the cross-indication stage explicitly, and it no longer
    orders or caps the lanes - the figure's own drawn evidence does (probe GI13, GI14)."""

    def test_the_lane_label_says_any_indication(self):
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "torcetrapib",
                    [report("NCT00134264", 1), report("NCT00134290", 4)],
                    stage = 4,
                ),
            ])},
        }
        self.stub_dates([
            record("NCT00134264", start=2004, primary=2006),
            record("NCT00134290", start=2010, primary=2014),
        ])
        self.draw(self.result_with(dossier))
        self.assertTrue(
            any("max stage 4 (any indication)" in text for text in self.canvas_texts)
        )

    def test_the_pair_relevant_drug_survives_the_cap_against_higher_stage_filler_drugs(self):
        """Eight filler drugs each carry a high cross-indication stage and a report dated
        after the pair-relevant drug's own report; the pair-relevant drug carries the
        LOWEST stage. The old stage-sorted cap dropped exactly this drug."""
        fillers = [
            drug(
                f"filler-{index}",
                [report(f"NCT1000000{index}", 4)],
                stage = 4,
            )
            for index in range(1, 9)
        ]
        dossier = {
            "CETP": {"get_known_drugs": known_drugs(
                "CETP",
                fillers + [drug("torcetrapib", [report("NCT00134264", 3)], stage=1)],
            )},
        }
        self.stub_dates(
            [
                record(f"NCT1000000{index}", start=2000 + index, primary=2002 + index)
                for index in range(1, 9)
            ] + [record("NCT00134264", start=2004, primary=2006)]
        )
        self.draw(self.result_with(dossier))
        self.assertIn("9 drug(s) retrieved, 8 drawn", self.footer_text)
        self.assertNotIn("highest max clinical stage first", self.footer_text)


class TestT7StartFromCompletionIsMarkedNotSilent(DrawingCase):
    """T7: a marker with no retrieved start year, sitting on the registry's completion
    year instead, must not be indistinguishable from a real start marker (probe GI12)."""

    def test_a_completion_only_record_is_disclosed_not_drawn_as_a_start(self):
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "torcetrapib",
                    [report("NCT00134264", 3), report("NCT00134290", 2)],
                    stage = 3,
                ),
            ])},
        }
        self.stub_dates([
            record("NCT00134264", start=None, completion=2016),
            record("NCT00134290", start=2016, primary=2018),
        ])
        self.draw(self.result_with(dossier))
        self.assertIn("1 marker(s) are drawn hollow", self.footer_text)
        self.assertIn("not a start date", self.footer_text)


class TestT8MathtextIsNeutralizedNotDeleted(DrawingCase):
    """T8: a retrieved string containing a balanced pair of "$" must draw its own literal
    characters, not matplotlib mathtext glyphs, and an unbalanced pair must not deny the
    figure (probe GI07, GI21)."""

    def test_a_balanced_dollar_pair_draws_the_literal_characters(self):
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "cost-$5-per-$1 gain",
                    [report("NCT00134264", 3)],
                    stage = 3,
                ),
            ])},
        }
        self.stub_dates([record(
            "NCT00134264",
            start  = 2004,
            primary = 2006,
            status = "TERMINATED",
            why    = "budget $overrun_{total}$ only",
        )])
        path = self.draw(self.result_with(dossier))
        self.assert_is_a_real_png(path)
        self.assertIn("cost-$5-per-$1 gain\nCETP, max stage 3 (any indication)", self.canvas_texts)
        self.assertTrue(any("$overrun_{total}$" in text for text in self.canvas_texts))

    def test_an_unbalanced_dollar_pair_does_not_deny_the_figure(self):
        """This exact string, `matplotlib.text.Text._preprocess_math` parsed as malformed
        mathtext and raised at savefig time before the fix - no figure, no undrawn-report
        note, nothing."""
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug("torcetrapib", [report("NCT00134264", 3)], stage=3),
            ])},
        }
        self.stub_dates([record(
            "NCT00134264",
            start  = 2004,
            primary = 2006,
            status = "TERMINATED",
            why    = "budget $1{2 per site$ exceeded",
        )])
        path = self.draw(self.result_with(dossier))
        self.assert_is_a_real_png(path)
        self.assertTrue(any("$1{2 per site$" in text for text in self.canvas_texts))

    def test_no_artist_actually_drawn_by_this_figure_parses_mathtext(self):
        """Asserted on the DRAWN artists, not on the rcParam: the rcParam is
        process-global and any later `plt.rcdefaults()`, `plt.style.use(...)` or
        `rc_context` in the same interpreter would put parsing back with nothing
        noticing. The guarantee has to travel with the drawing call."""
        import matplotlib

        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug(
                    "cost-$5-per-$1 gain",
                    [report("NCT00134264", 3)],
                    stage = 3,
                ),
            ])},
        }
        self.stub_dates([record(
            "NCT00134264",
            start  = 2004,
            primary = 2006,
            status = "TERMINATED",
            why    = "budget $overrun_{total}$ only",
        )])
        drawn = []
        real_save = plots._save

        def recording_save(fig, out_path):
            fig.canvas.draw()
            drawn.extend(
                artist for artist in fig.findobj(matplotlib.text.Text)
                if artist.get_text() and artist.get_text().strip()
            )
            return real_save(fig, out_path)

        plots._save = recording_save
        self.addCleanup(setattr, plots, "_save", real_save)
        with matplotlib.rc_context({"text.parse_math": True}):
            self.draw(self.result_with(dossier))
        self.assertTrue(drawn, "no Text artist was drawn")
        parsing = [
            artist.get_text() for artist in drawn
            if artist.get_parse_math() and "$" in artist.get_text()
        ]
        self.assertEqual(parsing, [], f"these retrieved strings would parse as math: {parsing}")

    def test_the_process_wide_default_is_also_off(self):
        import matplotlib
        self.assertFalse(matplotlib.rcParams["text.parse_math"])


class TestT9IntegerYearAxisOnASingleYear(DrawingCase):
    """T9: the year axis must print whole years even when every drawn year is the same
    year (probe GI19)."""

    def test_a_single_repeated_year_gets_integer_tick_labels(self):
        """GI19 as the probe had it: ONE drug, ONE report, one retrieved start year and
        nothing else dated. The instruments envelope is emptied because
        `plots.demo_result(PAIR_B)` carries exposure years of its own (2014, 2020) and a
        fixture that kept them would never reach the `ceiling == floor` branch."""
        dossier = {
            "CETP": {"get_known_drugs": known_drugs("CETP", [
                drug("torcetrapib", [report("NCT00134264", 3)], stage=3),
            ])},
        }
        self.stub_dates([record("NCT00134264", start=2004, completion=None)])
        result = self.result_with(dossier)
        result["envelopes"]["instruments"]["data"]["exposures"] = []
        self.draw(result)
        self.assertTrue(self.tick_labels, "no x-axis tick labels were captured")
        for label in self.tick_labels:
            self.assertNotIn(".", label, f"non-integer year tick: {label!r}")
        self.assertIn("2004", self.tick_labels)


if __name__ == "__main__":
    unittest.main()
