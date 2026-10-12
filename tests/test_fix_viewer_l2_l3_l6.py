"""Viewer/lifecycle regression: L2 (silent stage drop), L3 (label-only required-stage
check), L6 (raw-string chronology guard). Surface: demo/genetic-insights/render_bundle.py
and demo/genetic-insights/viewer.template.html, introduced by PR #14 (25defeb).

    python -m unittest tests.test_fix_viewer_l2_l3_l6 -v

WHAT BROKE, per the 2026-09-17 re-run
(docs/research/section9_adversarial/rerun_2026-09-17/RESULTS.md, Table c.1):

  L2  An event whose evidence_stage is not one of timeline_standard.display_order's five
      known stages was silently dropped from the rendered timeline (case LC03: the
      Pfizer safety-stop event relabelled "regulatory_action" vanished; 10 of 11 events
      shown, no notice, while the Markdown/Slack renderings still carried it).
  L3  render_bundle.py's required-stage check, and the matching check in
      viewer.template.html's validate(b), only asked whether each required stage
      STRING was present anywhere among the events' labels; neither looked at which
      event carried it (case LC04: two events swap evidence_stage -- a 2017
      class-outcome event becomes "human_genetics" and the real 1989 human-genetics
      event becomes "clinical" -- and both validators still passed).
  L6  Both chronology guards compared raw date strings. Python's own date parser
      accepts ISO-8601 basic format ("20071105") on day-precision events, and '-'
      sorts below a digit, so a basic-format November date can sort earlier than an
      extended-format January date of the same year: a TRUE chronological order
      (case LC09) was rejected, and a REVERSED order (case LC10) was accepted.

THE FIX (both render_bundle.validate_bundle() and viewer.template.html's validate(b)):
  L6: every event's date is parsed (day/month/year precision, ISO extended or ISO
      basic) into a real, comparable value before the chronology guard compares it,
      instead of comparing the raw strings.
  L3: after confirming every required stage label is present (unchanged), each event's
      stage label is checked against THE ROWS BEHIND IT -- its own type/scope/title --
      using the stage's evidence vocabulary (render_bundle.STAGE_EVIDENCE_TERMS, and
      the matching stageEvidenceTerms inside the viewer's validate()). The check is a
      phrase heuristic, not a proof, and it is deliberately NOT a date-ordering rule:
      evidence stages genuinely overlap in time (the shipped evacetrapib recording has
      a later_genetics event before its first clinical event), so a no-overlap rule
      would reject truthful bundles while accusing their author of mislabelling. It
      runs over every stage the standard declares, required or not, because an event
      does not become honestly labelled by being moved to an optional stage.
      A timeline_standard with an empty required_stages is also rejected outright: a
      standard that requires nothing checks nothing, and the viewer still prints its
      note as if a guarantee had been verified (case LC05).
  viewer.template.html's render() (L2 only -- not a validate() concern): any event
      whose evidence_stage is not one of the known display_order stages is now
      rendered into a visible "Unrecognized stage" bucket instead of being filtered
      out of the stage list before rendering. The bucket is placed at the position its
      own events' chronology implies rather than appended after the last lifecycle
      stage, and its node is drawn hollow and grey so it cannot read as one more
      evidence stage. render_bundle.stage_label() marks the same event the same way in
      the Markdown report and the Slack payloads, so all three renderings say it.

CLOSURE. Each LC case below is one of the lifecycle bundles the 2026-09-17 probe
(docs/research/section9_adversarial/rerun_2026-09-17/new_probes/timeline/probe_timeline.py)
wrote and viewer_stage_probe.cjs measured, copied as static fixtures under
tests/fixtures/lifecycle/ so this file does not depend on that read-only evidence
directory continuing to exist in its current shape. tests/fixtures/viewer_probe_harness.cjs
is an adapted copy of that probe's lifting technique (literal-text extraction of
viewer.template.html's own source, never a re-implementation of it), extended to lift
the fixed render() stage-grouping lines too. Before/after values quoted in each test's
docstring were captured by running the harness, and render_bundle.validate_bundle(),
against demo/genetic-insights/{render_bundle.py,viewer.template.html} at HEAD (before
this commit) and again after.

L6 on the JS side has a documented reachability limit, not a gap in this fix: the
per-event regex in viewer.template.html's validate() (``/^(\\d{4})(-\\d{2})?(-\\d{2})?$/``)
already refuses a basic-format date before the chronology guard ever runs -- on both
LC09 and LC10, before this fix and after it. That regex is unchanged and out of this
phase's scope (the date FORMAT policy is not one of L2/L3/L6; plots.py/figure code
belongs to a different agent). test_lc09_and_lc10_stay_blocked_by_the_unrelated_date_regex
below pins that limit down so a future change to the regex does not silently reopen it
without a test noticing. The reachable demonstration of the L6 fix is
render_bundle.validate_bundle() (what actually writes the shipped bundle.json), and
test_chronology_guard_rejects_a_reversed_same_format_order demonstrates the JS
comparator's own logic directly with an extended-format-only fixture the regex accepts.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GENETIC_INSIGHTS_DIR = REPO_ROOT / "demo" / "genetic-insights"
if str(GENETIC_INSIGHTS_DIR) not in sys.path:
    sys.path.insert(0, str(GENETIC_INSIGHTS_DIR))

import render_bundle  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "lifecycle"
HARNESS = Path(__file__).resolve().parent / "fixtures" / "viewer_probe_harness.cjs"
NODE = shutil.which("node")

EVACETRAPIB_BUNDLE = GENETIC_INSIGHTS_DIR / "recordings" / "cetp-evacetrapib-v2" / "bundle.json"
TORCETRAPIB_BUNDLE = GENETIC_INSIGHTS_DIR / "recordings" / "cetp-torcetrapib-v2" / "bundle.json"


def load_case(case: str) -> dict:
    return json.loads((FIXTURES / (case + ".bundle.json")).read_text(encoding="utf-8"))


def load_bundle(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_viewer_probe(bundle: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="metabocausal-viewerprobe-") as tmp:
        bundle_path = Path(tmp) / "bundle.json"
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        result = subprocess.run(
            [NODE, str(HARNESS), str(bundle_path)],
            capture_output = True,
            text            = True,
            check           = True,
        )
    return json.loads(result.stdout)


class TestPythonValidatorL3AndL6(unittest.TestCase):
    """render_bundle.validate_bundle(): the build-time path that writes bundle.json."""

    def test_lc01_baseline_still_passes(self):
        render_bundle.validate_bundle(load_case("LC01"))

    def test_lc03_unrecognized_stage_is_not_a_validate_bundle_concern(self):
        """L2 is a render() display bug, not a validate_bundle() rejection: the bundle
        is well-formed, it is the viewer's stage grouping that dropped the event.
        Before this fix and after it, validate_bundle() accepts LC03 either way."""
        render_bundle.validate_bundle(load_case("LC03"))

    def test_lc04_swapped_stage_labels_are_now_rejected(self):
        """Before this fix: validate_bundle(load_case('LC04')) returned None (accepted).
        After: raises ValueError naming the event, the stage it was filed under, and the
        type/scope that support neither."""
        with self.assertRaises(ValueError) as failure:
            render_bundle.validate_bundle(load_case("LC04"))
        message = str(failure.exception)
        self.assertIn("not supported by the event's own evidence", message)
        self.assertIn("human-genetics", message)
        self.assertIn("clinical", message)
        self.assertIn("Human genetics", message)

    def test_lc05_empty_required_stages_is_now_rejected(self):
        """L3's other listed case. Before this fix: `required` was [], `missing` was
        empty, the ordering loop never executed, and the bundle could declare a
        lifecycle standard - and print that standard's note claiming the guarantee -
        while nothing whatsoever was checked. After: rejected."""
        with self.assertRaises(ValueError) as failure:
            render_bundle.validate_bundle(load_case("LC05"))
        self.assertIn("declares no required_stages", str(failure.exception))

    def test_an_event_relabelled_to_a_non_required_stage_is_rejected_too(self):
        """A stage inside display_order but outside required_stages was excluded from
        every group the old ordering walk compared, so a Phase 3 trial event relabelled
        `later_genetics` rendered under "Later genetics" and both validators accepted
        it. The evidence check does not care whether a stage is required."""
        bundle = copy.deepcopy(load_case("LC01"))
        trial_start = next(e for e in bundle["events"] if e["id"] == "trial-start")
        self.assertEqual(trial_start["type"], "Phase 3 trial")
        trial_start["evidence_stage"] = "later_genetics"
        with self.assertRaises(ValueError) as failure:
            render_bundle.validate_bundle(bundle)
        self.assertIn("trial-start", str(failure.exception))
        self.assertIn("later_genetics", str(failure.exception))

    def test_a_truthful_bundle_whose_stages_overlap_in_time_is_still_accepted(self):
        """The rule this replaced was a no-overlap date rule wearing a labelling
        accusation. Evidence stages overlap: the shipped evacetrapib recording carries a
        later_genetics event dated before its first clinical event, and it is correctly
        labelled."""
        bundle = load_bundle(EVACETRAPIB_BUNDLE)
        dates = {}
        for event in bundle["events"]:
            dates.setdefault(event["evidence_stage"], []).append(event["date"])
        self.assertLess(min(dates["later_genetics"]), min(dates["clinical"]))
        render_bundle.validate_bundle(bundle)

    def test_a_stage_the_standard_declares_with_no_vocabulary_cannot_be_checked(self):
        """A standard that names a stage this checker has no evidence vocabulary for is
        a standard whose labels cannot be verified. Saying so beats checking nothing."""
        bundle = copy.deepcopy(load_case("LC01"))
        bundle["timeline_standard"]["display_order"].append("post_marketing")
        bundle["events"][-1]["evidence_stage"] = "post_marketing"
        with self.assertRaises(ValueError) as failure:
            render_bundle.validate_bundle(bundle)
        self.assertIn("no evidence vocabulary", str(failure.exception))

    def test_lc06_missing_required_stage_is_still_caught(self):
        """L1's positive verification (PR #14's central check firing correctly) must
        keep working: two required stages are entirely absent from the bundle."""
        with self.assertRaises(ValueError) as failure:
            render_bundle.validate_bundle(load_case("LC06"))
        self.assertIn("silently omits required stages", str(failure.exception))

    def test_lc09_true_chronological_order_is_now_accepted(self):
        """Before this fix: raised 'Events must be chronological' on a TRUE order,
        because '20070115' sorted after '2007-11-05' as raw strings. After: accepted."""
        render_bundle.validate_bundle(load_case("LC09"))

    def test_lc10_reversed_order_is_now_rejected(self):
        """Before this fix: accepted a REVERSED order, for the same string-sort reason.
        After: raises 'Events must be chronological'."""
        with self.assertRaises(ValueError) as failure:
            render_bundle.validate_bundle(load_case("LC10"))
        self.assertIn("chronological", str(failure.exception))

    def test_shipped_evacetrapib_recording_still_validates(self):
        render_bundle.validate_bundle(load_bundle(EVACETRAPIB_BUNDLE))

    def test_shipped_torcetrapib_recording_still_validates(self):
        render_bundle.validate_bundle(load_bundle(TORCETRAPIB_BUNDLE))


class TestOutOfStandardStageInEveryRendering(unittest.TestCase):
    """L2 reaches the Markdown report and the Slack payloads too: one bundle, three
    renderings, and before this change only the HTML viewer knew the stage was outside
    the bundle's own lifecycle standard."""

    def setUp(self):
        self.bundle = load_case("LC03")
        self.event = next(e for e in self.bundle["events"] if e["id"] == "programme-stop")
        self.assertEqual(self.event["evidence_stage"], "regulatory_action")

    def test_the_helper_names_which_stage_is_outside_the_standard(self):
        self.assertTrue(render_bundle.stage_is_outside_standard(self.bundle, self.event))
        self.assertEqual(
            render_bundle.stage_label(self.bundle, self.event),
            "regulatory action (outside this bundle's lifecycle standard)",
        )
        known = next(e for e in self.bundle["events"] if e["id"] == "results")
        self.assertFalse(render_bundle.stage_is_outside_standard(self.bundle, known))
        self.assertEqual(render_bundle.stage_label(self.bundle, known), "clinical")

    def test_the_markdown_report_marks_it(self):
        markdown = render_bundle.summary_markdown(self.bundle)
        self.assertIn(
            "regulatory action (outside this bundle's lifecycle standard)", markdown
        )
        self.assertNotIn("\nregulatory action | ", markdown)

    def test_the_slack_payloads_mark_it(self):
        text = "\n".join(m["text"] for m in render_bundle.slack_payloads(self.bundle))
        self.assertIn(
            "regulatory action (outside this bundle's lifecycle standard)", text
        )

    def test_a_bundle_with_no_standard_marks_nothing(self):
        """Without a declared standard there is no standard to be outside of, and every
        stage must print exactly as it did before."""
        bundle = copy.deepcopy(self.bundle)
        bundle.pop("timeline_standard")
        self.assertFalse(render_bundle.stage_is_outside_standard(bundle, self.event))
        self.assertNotIn("outside this bundle's lifecycle standard",
                         render_bundle.summary_markdown(bundle))


@unittest.skipUnless(NODE, "node is not on PATH; cannot exercise the shipped viewer JS")
class TestViewerJsL2L3L6(unittest.TestCase):
    """viewer.template.html's own validate(b) and stage-grouping render() lines, run
    exactly as shipped (literal-text extraction, no re-implementation)."""

    def test_lc03_dropped_event_is_now_a_visible_unrecognized_bucket(self):
        """Before this fix: events_dropped == ["programme-stop"], events_rendered ==
        10 (of 11), no bucket named it. After: events_dropped == [], events_rendered
        == 11, and an "unrecognized_stage" group carries it."""
        probe = run_viewer_probe(load_case("LC03"))
        self.assertEqual(probe["stages"]["events_dropped"], [])
        self.assertEqual(probe["stages"]["events_rendered"], 11)
        unrecognized = [g for g in probe["stages"]["groups"] if g["stage"] == "unrecognized_stage"]
        self.assertEqual(len(unrecognized), 1)
        self.assertEqual(unrecognized[0]["events"], ["programme-stop"])
        self.assertEqual(unrecognized[0]["heading"], "Unrecognized stage")

    def test_the_unrecognized_bucket_is_placed_by_its_own_chronology_not_appended(self):
        """The timeline is a left-to-right chronological grid. Appended after the last
        lifecycle stage, LC03's 2006 event rendered to the right of a group ranged
        2017-2026: visible, but reading as the latest point in the programme."""
        probe = run_viewer_probe(load_case("LC03"))
        order = [group["stage"] for group in probe["stages"]["groups"]]
        self.assertEqual(
            order,
            ["human_genetics", "preclinical", "clinical", "unrecognized_stage",
             "later_genetics", "class_status"],
        )
        self.assertNotEqual(order[-1], "unrecognized_stage")

    def test_the_unrecognized_node_is_not_drawn_like_an_evidence_stage(self):
        """Its markup is a stage group like any other, so the only thing separating a
        stage the standard does not know from one it does is how the node is drawn."""
        template = (GENETIC_INSIGHTS_DIR / "viewer.template.html").read_text(encoding="utf-8")
        self.assertIn(".stage-unrecognized_stage .stage-node{", template)
        self.assertIn("box-shadow:0 0 0 1px var(--muted)", template)

    def test_lc03_still_passes_validate_because_l2_is_a_render_concern(self):
        probe = run_viewer_probe(load_case("LC03"))
        self.assertEqual(probe["validate"], "passed")

    def test_lc04_validate_now_rejects_swapped_stage_labels(self):
        """Before this fix: probe['validate'] == 'passed'. After: throws naming the
        event, the stage it was filed under, and that its own rows support neither."""
        probe = run_viewer_probe(load_case("LC04"))
        self.assertIn("not supported by the event's own evidence", probe["validate"])
        self.assertIn("human-genetics", probe["validate"])
        self.assertIn("clinical", probe["validate"])

    def test_lc05_validate_now_rejects_a_standard_that_requires_nothing(self):
        probe = run_viewer_probe(load_case("LC05"))
        self.assertIn("no required stages", probe["validate"])

    def test_an_event_relabelled_to_a_non_required_stage_is_rejected_by_the_viewer_too(self):
        bundle = copy.deepcopy(load_case("LC01"))
        next(e for e in bundle["events"] if e["id"] == "trial-start")["evidence_stage"] = "later_genetics"
        probe = run_viewer_probe(bundle)
        self.assertIn("not supported by the event's own evidence", probe["validate"])
        self.assertIn("trial-start", probe["validate"])

    def test_lc09_and_lc10_stay_blocked_by_the_unrelated_date_regex(self):
        """Reachability limit, not a gap: viewer.template.html's per-event date regex
        (unchanged, out of L2/L3/L6 scope) refuses basic-format dates before the
        chronology guard runs, on both cases, unchanged by this fix."""
        for case in ("LC09", "LC10"):
            probe = run_viewer_probe(load_case(case))
            self.assertEqual(probe["validate"], "Error: Invalid event.")

    def test_chronology_guard_rejects_a_reversed_same_format_order(self):
        """Basic soundness of the new parsed-date comparator, not a bug demonstration:
        within pure extended-ISO input (all the per-event regex above ever admits),
        raw string order and true date order already agreed, so this case passed
        before this fix too. What it pins down is that the rewritten comparator did
        not regress the ordinary case while fixing the basic-format one. Swaps two
        adjacent, correctly-formatted event dates in the real LC01 baseline into
        reversed order."""
        reversed_bundle = copy.deepcopy(load_case("LC01"))
        events = reversed_bundle["events"]
        antisense = next(e for e in events if e["id"] == "preclinical-antisense")
        inhibitor = next(e for e in events if e["id"] == "preclinical-inhibitor")
        antisense["date"], inhibitor["date"] = inhibitor["date"], antisense["date"]
        probe = run_viewer_probe(reversed_bundle)
        self.assertIn("Events must be chronological", probe["validate"])

    def test_shipped_evacetrapib_recording_still_validates(self):
        probe = run_viewer_probe(load_bundle(EVACETRAPIB_BUNDLE))
        self.assertEqual(probe["validate"], "passed")

    def test_shipped_torcetrapib_recording_still_validates(self):
        probe = run_viewer_probe(load_bundle(TORCETRAPIB_BUNDLE))
        self.assertEqual(probe["validate"], "passed")


if __name__ == "__main__":
    unittest.main()
