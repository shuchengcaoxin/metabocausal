"""Adversarial probes for the Genetic Insights timeline lifecycle.

New surface for the 2026-09-17 re-run of the Section 9 closed-boundary study. Zipeng's
2026-09-16 bundle never probed a figure; this file probes the two timeline surfaces that
current `main` carries:

  GI**  `plots.plot_genetic_insight` - the live per-run figure, drawn from the 1E dossier
        envelope and the ClinicalTrials.gov date lookup, reached from Slack's
        `slack_app.draw_figure(kind="timeline")` button. Never probed before.
  LC**  `demo/genetic-insights/render_bundle.py` + `viewer.template.html` - the curated
        MVP1 lifecycle timeline as FIXED by PR #14 ("fix: cover the full evidence
        lifecycle in timelines", 25defeb). The JS half is probed by the sibling
        `viewer_stage_probe.cjs`, which evaluates the shipped template lines verbatim.

DISCIPLINE. Fully offline and deterministic, like `scripts/probe_section9.py`:

  * `socket.socket` is replaced with a raising stub before any case runs, so a probe that
    reached the network would fail loudly instead of quietly measuring the internet.
  * `tools.trials.get_trial_dates` is replaced with a stub that answers from the case's
    own frozen `registry` block and RECORDS the ids it was asked for. What the registry
    was actually asked is itself evidence: several findings below are about the figure
    claiming registry provenance for a value the registry never supplied.
  * `plots._save` is wrapped so that every `matplotlib.text.Text` string on the canvas is
    captured before the PNG is written. The figure's own claims are then checked as text
    rather than by eye.
  * No clock, no randomness, no model call. Re-running overwrites `artifacts/` with the
    same bytes, and the script exits non-zero when an expected observation changes.

RUN (repository root, python 3.12):

    PYTHONIOENCODING=utf-8 python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/timeline/probe_timeline.py
    node docs/research/section9_adversarial/rerun_2026-09-17/new_probes/timeline/viewer_stage_probe.cjs

NOTHING OUTSIDE THIS FOLDER IS WRITTEN. Figures go to `artifacts/figures/`, not `cards/`.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import socket
import sys
import unicodedata
from contextlib import redirect_stdout
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[5]
ARTIFACTS = HERE / "artifacts"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEMO_DIR = REPO_ROOT / "demo" / "genetic-insights"
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))


# --------------------------------------------------------------------------------------
# the offline boundary
# --------------------------------------------------------------------------------------

class NetworkAttempted(RuntimeError):
    """A probe tried to open a socket. That is off the measured boundary, not a result."""


def seal_network() -> None:
    """Replace every socket entry point with a raising stub.

    Installed after the imports that need no network and before the first case. A probe
    that silently reached ClinicalTrials.gov would make the whole table unreproducible,
    so reaching it is made an exception instead of a slow test.
    """
    def refuse(*args, **kwargs):
        raise NetworkAttempted(
            "this probe suite is offline; something asked for a socket"
        )

    socket.socket = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse


# --------------------------------------------------------------------------------------
# the registry stub - a frozen ClinicalTrials.gov, and a record of what it was asked
# --------------------------------------------------------------------------------------

# Every field `plots._lane_markers` reads off a registry record, so a case can withhold
# exactly one of them. Mirrors the real `tools/trials.py` record shape.
REGISTRY_ASKED: list = []

STUB_RETRIEVED_AT = "2026-09-17T00:00:00+00:00"


def registry_record(
    nct_id:            str,
    start_year         = None,
    completion_year    = None,
    completion_type:   str = "ACTUAL",
    overall_status:    str = "",
    why_stopped:       str = "",
) -> dict:
    """One frozen ClinicalTrials.gov record, in the shape `tools.trials` returns."""
    return {
        "nct_id":                        nct_id,
        "start_year":                    start_year,
        "start_date_type":               "ACTUAL" if start_year is not None else "",
        "primary_completion_year":       completion_year,
        "primary_completion_date_type":  completion_type if completion_year is not None else "",
        "completion_year":               completion_year,
        "completion_date_type":          completion_type if completion_year is not None else "",
        "overall_status":                overall_status,
        "why_stopped":                   why_stopped,
        "retrieved_at":                  STUB_RETRIEVED_AT,
    }


def install_registry_stub(spec: dict) -> None:
    """Point `tools.trials.get_trial_dates` at this case's frozen answer.

    `plots._trial_dates` does `from tools.trials import get_trial_dates` inside the
    function body, so replacing the module attribute is enough and the real
    `_trial_dates` - its cap argument, its two except guards - is still the code under
    test.
    """
    import tools.trials as trials

    def stub(
        nct_ids,
        cap = 24,
    ):
        asked = trials.normalize_nct_ids(nct_ids)[: max(0, int(cap or 0))]
        REGISTRY_ASKED.extend(asked)
        dates = {
            nct_id: record
            for nct_id, record in (spec.get("dates") or {}).items()
            if nct_id in asked
        }
        data = {
            "dates":        dates,
            "n_requested":  len(trials.normalize_nct_ids(nct_ids)),
            "n_looked_up":  len(asked),
            "n_from_cache": 0,
            "n_fetched":    len(dates),
            "n_failed":     int(spec.get("n_failed") or 0),
            "n_undated":    len(asked) - len(dates),
            "cap":          int(cap or 0),
            "failed":       {},
            "queries":      [],
        }
        return {
            "tool":         "get_trial_dates",
            "args":         {"nct_ids": asked, "cap": cap},
            "source":       "ClinicalTrials.gov API v2 (studies) [PROBE STUB]",
            "url":          "",
            "retrieved_at": STUB_RETRIEVED_AT,
            "status":       "ok" if dates else "empty",
            "data":         data,
            "caveats":      [],
        }

    trials.get_trial_dates = stub


# --------------------------------------------------------------------------------------
# reading the figure back as text
# --------------------------------------------------------------------------------------

CAPTURED: dict = {}


def install_text_capture() -> None:
    """Wrap `plots._save` so every string drawn on the canvas is recorded.

    The canvas is drawn once before the real save so that tick labels are realized; the
    second draw inside `savefig` produces identical output, and nothing about the written
    PNG changes.
    """
    import matplotlib.text
    import plots

    real_save = plots._save

    def capturing_save(
        fig,
        out_path,
    ):
        try:
            fig.canvas.draw()
        except Exception as exc:                        # a draw-time failure IS a result
            CAPTURED["draw_error"] = f"{type(exc).__name__}: {exc}"
        # Tick labels are excluded from the geometry checks: matplotlib keeps a Text for
        # every tick the locator proposed, including ticks outside the view that are
        # never drawn, and counting those as overflow would be an artefact of the probe.
        ticks = set()
        for axes in fig.axes:
            for axis in (axes.xaxis, axes.yaxis):
                for tick in list(axis.get_major_ticks()) + list(axis.get_minor_ticks()):
                    ticks.add(id(tick.label1))
                    ticks.add(id(tick.label2))

        renderer = fig.canvas.get_renderer()
        canvas = fig.bbox
        texts = []
        boxes = []
        overflow = []
        for artist in fig.findobj(matplotlib.text.Text):
            value = artist.get_text()
            if not value or not value.strip():
                continue
            if id(artist) not in ticks or artist.get_visible():
                texts.append(value)
            if id(artist) in ticks:
                continue
            try:
                box = artist.get_window_extent(renderer)
            except Exception:                            # a text with no renderer yet
                continue
            boxes.append((value, box))
            # plots.py's contract is that no label leaves the canvas without the figure
            # counting it, so the overflow is measured rather than eyeballed.
            if box.x0 < canvas.x0 - 0.5 or box.x1 > canvas.x1 + 0.5:
                overflow.append({
                    "text":      value,
                    "x0":        round(box.x0, 1),
                    "x1":        round(box.x1, 1),
                    "canvas_x1": round(canvas.x1, 1),
                    "lost_px":   round(
                        max(canvas.x0 - box.x0, 0.0) + max(box.x1 - canvas.x1, 0.0),
                        1,
                    ),
                })

        # Two labels whose ink boxes intersect are printed over each other. The figure
        # counts nothing about this either.
        collisions = []
        for index, (left_text, left_box) in enumerate(boxes):
            for right_text, right_box in boxes[index + 1:]:
                if left_box.overlaps(right_box):
                    collisions.append({
                        "a": left_text,
                        "b": right_text,
                    })

        CAPTURED["texts"] = texts
        CAPTURED["overflow"] = overflow
        CAPTURED["collisions"] = collisions
        return real_save(
            fig,
            out_path,
        )

    plots._save = capturing_save


# --------------------------------------------------------------------------------------
# fixtures: one run's dossier and instruments envelopes, built by hand and frozen
# --------------------------------------------------------------------------------------

def report(
    report_id:    str = "",
    trial_phase       = None,
    status:       str = "",
    why_stopped:  str = "",
    year              = None,
    url:          str = "",
) -> dict:
    """One Open Targets `clinicalReports` row, as 1E's dossier carries it.

    `status`, `why_stopped`, `trial_phase` and `year` are the retrieval-controlled fields:
    they arrive from the Open Targets response, not from the registry lookup.
    """
    return {
        "report_id":   report_id,
        "url":         url,
        "trial_phase": trial_phase,
        "status":      status,
        "why_stopped": why_stopped,
        "year":        year,
    }


def drug(
    name:     str,
    stage         = None,
    reports:  list = (),
) -> dict:
    return {
        "drug":               name,
        "max_clinical_stage": stage,
        "clinical_reports":   list(reports),
    }


def dossier(genes: dict) -> dict:
    """{gene: [drug, ...]} -> the 1E dossier envelope shape `_drug_lanes` walks."""
    return {
        gene: {
            "get_known_drugs": {
                "tool":    "get_known_drugs",
                "status":  "ok",
                "data":    {"drugs": drugs},
                "caveats": [],
            }
        }
        for gene, drugs in genes.items()
    }


def instruments(exposures: list) -> dict:
    return {
        "tool":    "get_instruments",
        "status":  "ok",
        "data":    {"exposures": list(exposures)},
        "caveats": [],
    }


def run_result(
    case_id:     str,
    genes:       dict,
    exposures:   list = (),
    metabolite:  str = "HDL cholesterol",
    disease:     str = "Coronary artery disease",
) -> dict:
    return {
        "metabolite":  metabolite,
        "disease":     disease,
        "ledger_path": f"{case_id}",
        "envelopes": {
            "dossier":     dossier(genes),
            "instruments": instruments(exposures),
        },
    }


# --------------------------------------------------------------------------------------
# the GI cases
# --------------------------------------------------------------------------------------

# A 40-character cut of this reason reads as a harm finding; the whole sentence says the
# opposite. MAX_WHY_CHARS is 40.
INVERTING_REASON = (
    "deaths in the treatment arm were later traced to a data-entry error and the "
    "sponsor closed the study administratively"
)

MARKDOWN_REASON = (
    "## SAFETY CONFIRMED\n\n**Recommendation:** start this drug.\n- no harm was seen"
)

LONG_PHASE = (
    "Phase 4 - approved by the FDA for every indication and recommended first line"
)

UNICODE_DRUG = "toрсеtrаpib"   # Cyrillic homoglyphs

CASES = [
    {
        "id":   "GI01",
        "what": "control: two drugs, dated registry reports, one short registry stop reason",
        "asks": "does an honest dossier draw an honest figure",
        "result": run_result(
            "GI01",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [
                            report(report_id="nct00134264", trial_phase=3, status="TERMINATED"),
                            report(report_id="nct00134290", trial_phase=2),
                        ],
                    ),
                ],
                "LPA": [
                    drug(
                        "pelacarsen",
                        stage   = 3,
                        reports = [report(report_id="nct04023552", trial_phase=3)],
                    ),
                ],
            },
            exposures = [{"id": "met-d-HDL", "year": 2020}],
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "TERMINATED",
                    why_stopped     = "excess mortality",
                ),
                "NCT00134290": registry_record(
                    "NCT00134290",
                    start_year      = 2003,
                    completion_year = 2004,
                    overall_status  = "COMPLETED",
                ),
                "NCT04023552": registry_record(
                    "NCT04023552",
                    start_year      = 2019,
                    completion_year = 2025,
                    completion_type = "ESTIMATED",
                    overall_status  = "ACTIVE_NOT_RECRUITING",
                ),
            },
        },
    },
    {
        "id":   "GI02",
        "what": "undated mix: three reports carry no NCT id at all, one is dated",
        "asks": "is the undated footer's 'carry no year in the registry' true of reports "
                "the registry was never asked about",
        "result": run_result(
            "GI02",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [
                            report(report_id="nct00134264", trial_phase=3),
                            report(report_id="EMA-label-2006", trial_phase=4),
                            report(report_id="FDA-AN-2007", trial_phase="phase not recorded"),
                            report(report_id="registry-entry-jp", trial_phase=2),
                        ],
                    ),
                ],
            },
            exposures = [{"id": "met-d-HDL", "year": 2020}],
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "COMPLETED",
                ),
            },
        },
    },
    {
        "id":   "GI03",
        "what": "why_stopped provenance: registry record carries the stop but NO reason; "
                "the dossier report supplies one",
        "asks": "does the footer credit the registry for a reason the registry never gave",
        "result": run_result(
            "GI03",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [
                            report(
                                report_id   = "nct00134264",
                                trial_phase = 3,
                                why_stopped = "stopped early for overwhelming benefit",
                            ),
                        ],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "TERMINATED",
                    why_stopped     = "",
                ),
            },
        },
    },
    {
        "id":   "GI04",
        "what": "status provenance: the registry record carries no overall_status; the "
                "dossier report declares TERMINATED and supplies the reason",
        "asks": "can a retrieval-controlled field alone produce the stopped marker and a "
                "footer sentence that calls the reason the registry's own",
        "result": run_result(
            "GI04",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [
                            report(
                                report_id   = "nct00134264",
                                trial_phase = 3,
                                status      = "TERMINATED",
                                why_stopped = "competitor product was safer",
                            ),
                        ],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "",
                ),
            },
        },
    },
    {
        "id":   "GI05",
        "what": "truncation inverts the reason: 40 characters of an exonerating sentence "
                "read as a harm finding",
        "asks": "can the drawn stop reason mean the opposite of the retrieved one",
        "result": run_result(
            "GI05",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [report(report_id="nct00134264", trial_phase=3)],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "TERMINATED",
                    why_stopped     = INVERTING_REASON,
                ),
            },
        },
    },
    {
        "id":   "GI06",
        "what": "Markdown / forged heading inside why_stopped",
        "asks": "does a heading survive onto the canvas, and does the newline survive",
        "result": run_result(
            "GI06",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [report(report_id="nct00134264", trial_phase=3)],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "TERMINATED",
                    why_stopped     = MARKDOWN_REASON,
                ),
            },
        },
    },
    {
        "id":   "GI07",
        "what": "dollar signs in the drug name and the stop reason (matplotlib mathtext)",
        "asks": "does an unbalanced or math-like string change or break the rendering",
        "result": run_result(
            "GI07",
            {
                "CETP": [
                    drug(
                        "cost-$5-per-$1 gain",
                        stage   = 3,
                        reports = [report(report_id="nct00134264", trial_phase=3)],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "TERMINATED",
                    why_stopped     = "budget $overrun_{total}$ only",
                ),
            },
        },
    },
    {
        "id":   "GI08",
        "what": "trial_phase outside the enum: a long free-text approval claim",
        "asks": "is the phase label budgeted and counted like every other label on this "
                "module's figures",
        "result": run_result(
            "GI08",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [
                            report(report_id="nct00134264", trial_phase=LONG_PHASE),
                            report(report_id="nct00134290", trial_phase="PHASE1/PHASE2"),
                        ],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "COMPLETED",
                ),
                "NCT00134290": registry_record(
                    "NCT00134290",
                    start_year      = 2005,
                    completion_year = 2007,
                    overall_status  = "COMPLETED",
                ),
            },
        },
    },
    {
        "id":   "GI09",
        "what": "Cyrillic-homoglyph drug name beside the Latin one",
        "asks": "does the figure distinguish two drugs whose names are not the same string",
        "result": run_result(
            "GI09",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [report(report_id="nct00134264", trial_phase=3)],
                    ),
                    drug(
                        UNICODE_DRUG,
                        stage   = 3,
                        reports = [report(report_id="nct00134290", trial_phase=3)],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "COMPLETED",
                ),
                "NCT00134290": registry_record(
                    "NCT00134290",
                    start_year      = 2005,
                    completion_year = 2007,
                    overall_status  = "COMPLETED",
                ),
            },
        },
    },
    {
        "id":   "GI10",
        "what": "absurd years 1850 and 2099 supplied by the dossier's own `year` field",
        "asks": "is there any plausibility floor, and what happens to the real markers",
        "result": run_result(
            "GI10",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [
                            report(report_id="nct00134264", trial_phase=3),
                            report(report_id="OT-ancient", trial_phase=1, year=1850),
                            report(report_id="OT-future", trial_phase=4, year=2099),
                        ],
                    ),
                ],
            },
            exposures = [{"id": "met-d-HDL", "year": 2020}],
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "COMPLETED",
                ),
            },
        },
    },
    {
        "id":   "GI11",
        "what": "year conflict: registry completion year earlier than the start year",
        "asks": "is the impossible interval reported, or silently dropped",
        "result": run_result(
            "GI11",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [report(report_id="nct00134264", trial_phase=3)],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2016,
                    completion_year = 2009,
                    overall_status  = "COMPLETED",
                ),
            },
        },
    },
    {
        "id":   "GI12",
        "what": "completion-only record: the registry carries no start year",
        "asks": "the axis is labelled 'start'; is a completion year marked as such",
        "result": run_result(
            "GI12",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [
                            report(report_id="nct00134264", trial_phase=3),
                            report(report_id="nct00134290", trial_phase=2),
                        ],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = None,
                    completion_year = 2016,
                    overall_status  = "COMPLETED",
                ),
                "NCT00134290": registry_record(
                    "NCT00134290",
                    start_year      = 2016,
                    completion_year = 2018,
                    overall_status  = "COMPLETED",
                ),
            },
        },
    },
    {
        "id":   "GI13",
        "what": "one drug, reports from two different diseases, max stage 4 earned "
                "elsewhere; this run's pair is HDL -> Coronary artery disease",
        "asks": "does the lane label roll a cross-indication stage up onto a figure that "
                "names one disease",
        "result": run_result(
            "GI13",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 4,
                        reports = [
                            report(report_id="nct00134264", trial_phase=1),
                            report(report_id="nct00134290", trial_phase=4),
                        ],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "COMPLETED",
                ),
                "NCT00134290": registry_record(
                    "NCT00134290",
                    start_year      = 2010,
                    completion_year = 2014,
                    overall_status  = "COMPLETED",
                ),
            },
        },
    },
    {
        "id":   "GI14",
        "what": "nine drugs: eight irrelevant ones carry a high cross-indication stage, "
                "the pair-relevant one carries stage 1",
        "asks": "does the eight-lane cap, ordered by cross-indication stage, drop the "
                "drug this pair is about",
        "result": run_result(
            "GI14",
            {
                "CETP": [
                    drug(
                        f"filler-{index}",
                        stage   = 4,
                        reports = [report(report_id=f"nct1000000{index}", trial_phase=4)],
                    )
                    for index in range(1, 9)
                ] + [
                    drug(
                        "torcetrapib",
                        stage   = 1,
                        reports = [
                            report(report_id="nct00134264", trial_phase=3),
                            report(report_id="EMA-no-id-1"),
                            report(report_id="EMA-no-id-2"),
                        ],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                f"NCT1000000{index}": registry_record(
                    f"NCT1000000{index}",
                    start_year      = 2000 + index,
                    completion_year = 2002 + index,
                    overall_status  = "COMPLETED",
                )
                for index in range(1, 9)
            } | {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "COMPLETED",
                ),
            },
        },
    },
    {
        "id":   "GI15",
        "what": "status text that merely contains a terminal word, plus a status the "
                "dossier wrote in full sentences",
        "asks": "is the stopped marker decided by a substring of an uncontrolled string",
        "result": run_result(
            "GI15",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [
                            report(
                                report_id = "nct00134264",
                                trial_phase = 3,
                                status      = "recruiting; an earlier study was terminated",
                                why_stopped = "see the earlier study",
                            ),
                            report(
                                report_id   = "nct00134290",
                                trial_phase = 3,
                                status      = "COMPLETED - no safety signal was terminated early",
                                why_stopped = "none",
                            ),
                        ],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                ),
                "NCT00134290": registry_record(
                    "NCT00134290",
                    start_year      = 2005,
                    completion_year = 2007,
                ),
            },
        },
    },
    {
        "id":   "GI16",
        "what": "the same drug reached through two effector genes",
        "asks": "does one drug become two lanes and two counted reports",
        "result": run_result(
            "GI16",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [report(report_id="nct00134264", trial_phase=3)],
                    ),
                ],
                "LIPC": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [report(report_id="nct00134264", trial_phase=3)],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "COMPLETED",
                ),
            },
        },
    },
    {
        "id":   "GI17",
        "what": "a GWAS 'year' of 2099 and a very long exposure dataset id",
        "asks": "does the dashed genetic-evidence line accept any number, and is its "
                "label budgeted",
        "result": run_result(
            "GI17",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [report(report_id="nct00134264", trial_phase=3)],
                    ),
                ],
            },
            exposures = [
                {"id": "met-d-HDL", "year": 2020},
                {
                    "id":   "ebi-a-GCST" + "9" * 60 + "-a-dataset-name-nobody-budgeted",
                    "year": 2099,
                },
            ],
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "COMPLETED",
                ),
            },
        },
    },
    {
        "id":   "GI18",
        "what": "every registry lookup fails; one report carries an Open Targets year",
        "asks": "what does the figure claim when the registry answered nothing",
        "result": run_result(
            "GI18",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [
                            report(report_id="nct00134264", trial_phase=3, year=2004),
                            report(report_id="nct00134290", trial_phase=2),
                        ],
                    ),
                ],
            },
        ),
        "registry": {
            "dates":    {},
            "n_failed": 2,
        },
    },
    {
        "id":   "GI19",
        "what": "NOT adversarial: one drug, one report, a registry record with a start "
                "year and no completion date",
        "asks": "what does the year axis print when every drawn year is the same year",
        "result": run_result(
            "GI19",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [report(report_id="nct00134264", trial_phase=3)],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = None,
                    overall_status  = "COMPLETED",
                ),
            },
        },
    },
    {
        "id":   "GI20",
        "what": "five reports of one drug all starting in the same year, with free-text "
                "phases; the label stagger has four offsets",
        "asks": "does the fifth label land on the first, and does the figure count it",
        "result": run_result(
            "GI20",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [
                            report(report_id="nct00134261", trial_phase="Phase 2/Phase 3"),
                            report(report_id="nct00134262", trial_phase="Phase 4 post-marketing surveillance"),
                            report(report_id="nct00134263", trial_phase="Phase 1 healthy volunteers"),
                            report(report_id="nct00134264", trial_phase="Phase 3 pivotal outcomes"),
                            report(report_id="nct00134265", trial_phase="Phase 2b dose finding"),
                        ],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                f"NCT0013426{index}": registry_record(
                    f"NCT0013426{index}",
                    start_year      = 2004,
                    completion_year = 2008,
                    overall_status  = "COMPLETED",
                )
                for index in range(1, 6)
            },
        },
    },
    {
        "id":   "GI21",
        "what": "a stopping reason matplotlib parses as malformed mathtext",
        "asks": "can one retrieved string deny the whole figure",
        "result": run_result(
            "GI21",
            {
                "CETP": [
                    drug(
                        "torcetrapib",
                        stage   = 3,
                        reports = [report(report_id="nct00134264", trial_phase=3)],
                    ),
                ],
            },
        ),
        "registry": {
            "dates": {
                "NCT00134264": registry_record(
                    "NCT00134264",
                    start_year      = 2004,
                    completion_year = 2006,
                    overall_status  = "TERMINATED",
                    why_stopped     = "budget $1{2 per site$ exceeded",
                ),
            },
        },
    },
]


# --------------------------------------------------------------------------------------
# running one GI case
# --------------------------------------------------------------------------------------

FOOTER_MARKERS = (
    "Per-report phases",
    "retrieved report(s) carry no year",
    "drug(s) retrieved,",
    "drawn drug(s) had no report",
    "retrieved drug(s) carry no clinical report",
    "registry lookup(s) failed",
    "trial id(s) found,",
    "Some marker(s) use the year Open Targets",
    "bar(s) are dotted",
    "stopped report(s) carry the registry's own reason",
    "lane label(s) shortened",
)


def is_footer(text: str) -> bool:
    return any(marker in text for marker in FOOTER_MARKERS)


def run_gi_case(case: dict) -> dict:
    """Draw one case, capture every string on the canvas, and record what was asked."""
    import plots

    REGISTRY_ASKED.clear()
    CAPTURED.clear()
    install_registry_stub(case["registry"])

    figures = ARTIFACTS / "figures"
    stream = io.StringIO()
    error = ""
    written = None
    try:
        with redirect_stdout(stream):
            written = plots.plot_genetic_insight(
                case["result"],
                str(figures),
            )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    texts = CAPTURED.get("texts") or []
    png_sha = ""
    if written and Path(written).exists():
        png_sha = hashlib.sha256(Path(written).read_bytes()).hexdigest()

    observation = {
        "case":             case["id"],
        "what":             case["what"],
        "asks":             case["asks"],
        "figure":           "drawn" if written else "none",
        "figure_file":      Path(written).name if written else "",
        "figure_sha256":    png_sha,
        "exception":        error,
        "draw_error":       CAPTURED.get("draw_error", ""),
        "stdout":           stream.getvalue().strip(),
        "registry_asked":   list(REGISTRY_ASKED),
        "canvas_texts":     texts,
        "overflowing":      CAPTURED.get("overflow") or [],
        "collisions":       CAPTURED.get("collisions") or [],
        "footer_lines":     [text for text in texts if is_footer(text)],
    }
    return observation


# --------------------------------------------------------------------------------------
# the LC cases: the PR #14 lifecycle standard on the curated bundle
# --------------------------------------------------------------------------------------

BUNDLE_PATH = DEMO_DIR / "snapshots" / "mvp1-cetp-torcetrapib-2026-09-12-v2.json"
EVACETRAPIB_PATH = DEMO_DIR / "snapshots" / "mvp1-cetp-evacetrapib-2026-09-12-v2.json"


def load_bundle(path: Path = None) -> dict:
    return json.loads((path or BUNDLE_PATH).read_text(encoding="utf-8"))


def retime(
    bundle: dict,
    dates:  dict,
) -> dict:
    """Give the named events these dates, leaving the array order alone."""
    for event in bundle["events"]:
        if event["id"] in dates:
            event["date"] = dates[event["id"]]
    return bundle


def lc_basic_before_extended(bundle: dict) -> dict:
    """Two 2007 events in TRUE order: January written 20070115, November written
    2007-11-05. `date.fromisoformat` accepts both; the chronology guard compares the
    strings."""
    return retime(
        bundle,
        {
            "results":            "20070115",
            "genetic-comparison": "2007-11-05",
        },
    )


def lc_basic_after_extended(bundle: dict) -> dict:
    """The same two events in REVERSE order: November listed before January."""
    bundle = lc_basic_before_extended(bundle)
    events = bundle["events"]
    first = next(i for i, e in enumerate(events) if e["id"] == "results")
    second = next(i for i, e in enumerate(events) if e["id"] == "genetic-comparison")
    events[first], events[second] = events[second], events[first]
    return bundle


def lc_drop_standard(bundle: dict) -> dict:
    """The lifecycle standard removed and every evidence_stage stripped."""
    bundle.pop("timeline_standard", None)
    for event in bundle["events"]:
        event.pop("evidence_stage", None)
    return bundle


def lc_forged_stage(bundle: dict) -> dict:
    """One event relabelled to a stage the display order does not know."""
    for event in bundle["events"]:
        if event["id"] == "programme-stop":
            event["evidence_stage"] = "regulatory_action"
    return bundle


def lc_mislabelled_stage(bundle: dict) -> dict:
    """The required human_genetics stage satisfied by a 2017 class-outcome event."""
    for event in bundle["events"]:
        if event["id"] == "human-genetics":
            event["evidence_stage"] = "clinical"
        if event["id"] == "anacetrapib-outcome":
            event["evidence_stage"] = "human_genetics"
    return bundle


def lc_empty_required(bundle: dict) -> dict:
    """The standard kept but its required_stages emptied."""
    bundle["timeline_standard"]["required_stages"] = []
    for event in bundle["events"]:
        event["evidence_stage"] = "clinical"
    return bundle


def lc_missing_required(bundle: dict) -> dict:
    """The human_genetics and preclinical events deleted outright (the case PR #14 names)."""
    drop = {"human-genetics", "preclinical-antisense", "preclinical-inhibitor"}
    bundle["events"] = [event for event in bundle["events"] if event["id"] not in drop]
    return bundle


def lc_basic_iso_date(bundle: dict) -> dict:
    """One day-precision date written in ISO 8601 basic format (no hyphens)."""
    for event in bundle["events"]:
        if event["id"] == "results":
            event["date"] = "20071105"
    return bundle


LC_CASES = [
    {
        "id":       "LC01",
        "what":     "control: the shipped v2 torcetrapib bundle",
        "asks":     "does the lifecycle standard pass on the bundle PR #14 shipped",
        "mutate":   None,
    },
    {
        "id":       "LC02",
        "what":     "timeline_standard removed and every evidence_stage stripped",
        "asks":     "is 'a missing stage must be reported as missing' enforced, or opt-in",
        "mutate":   lc_drop_standard,
    },
    {
        "id":       "LC03",
        "what":     "one event relabelled to a stage absent from display_order",
        "asks":     "does an event with a valid-looking stage survive into the rendered "
                    "timeline, or is it silently omitted",
        "mutate":   lc_forged_stage,
    },
    {
        "id":       "LC04",
        "what":     "a 2017 class-outcome event relabelled human_genetics, and the real "
                    "1989 human-genetics event relabelled clinical",
        "asks":     "does the required-stage check look at anything but the label",
        "mutate":   lc_mislabelled_stage,
    },
    {
        "id":       "LC05",
        "what":     "required_stages emptied, every event marked clinical",
        "asks":     "does the standard still assert anything",
        "mutate":   lc_empty_required,
    },
    {
        "id":       "LC06",
        "what":     "the human-genetics and preclinical events deleted",
        "asks":     "does the check PR #14 added actually fire",
        "mutate":   lc_missing_required,
    },
    {
        "id":       "LC07",
        "what":     "one date written in ISO 8601 basic format (20071105)",
        "asks":     "does the chronology check survive a date format the validator accepts",
        "mutate":   lc_basic_iso_date,
    },
    {
        "id":       "LC08",
        "what":     "control: the shipped v2 evacetrapib bundle, whose later_genetics "
                    "event (2012-05-17) precedes its first clinical event (2012-10)",
        "asks":     "does display_order present a sequence the dates contradict",
        "bundle":   "evacetrapib",
        "mutate":   None,
    },
    {
        "id":       "LC09",
        "what":     "January 2007 written 20070115 listed before November 2007 written "
                    "2007-11-05 - the TRUE chronological order",
        "asks":     "does the chronology guard accept a correctly ordered timeline",
        "mutate":   lc_basic_before_extended,
    },
    {
        "id":       "LC10",
        "what":     "the same two events REVERSED: November 2007 listed before January 2007",
        "asks":     "does the chronology guard reject an out-of-order timeline",
        "mutate":   lc_basic_after_extended,
    },
]


def run_lc_case(case: dict) -> dict:
    import render_bundle

    bundle = load_bundle(
        EVACETRAPIB_PATH if case.get("bundle") == "evacetrapib" else BUNDLE_PATH
    )
    if case["mutate"]:
        bundle = case["mutate"](bundle)

    validate_error = ""
    try:
        render_bundle.validate_bundle(bundle)
    except Exception as exc:
        validate_error = f"{type(exc).__name__}: {exc}"

    markdown_error = ""
    markdown = ""
    slack_error = ""
    slack_text = ""
    if not validate_error:
        try:
            markdown = render_bundle.summary_markdown(bundle)
        except Exception as exc:
            markdown_error = f"{type(exc).__name__}: {exc}"
        try:
            slack_text = "\n\n--- NEXT MESSAGE ---\n\n".join(
                message["text"] for message in render_bundle.slack_payloads(bundle)
            )
        except Exception as exc:
            slack_error = f"{type(exc).__name__}: {exc}"

    folder = ARTIFACTS / "lifecycle" / case["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding = "utf-8",
        newline  = "\n",
    )
    if markdown:
        (folder / "evidence-summary.md").write_text(
            markdown,
            encoding = "utf-8",
            newline  = "\n",
        )
    if slack_text:
        (folder / "slack-text.txt").write_text(
            slack_text + "\n",
            encoding = "utf-8",
            newline  = "\n",
        )

    stages = [event.get("evidence_stage", "<absent>") for event in bundle["events"]]
    return {
        "case":             case["id"],
        "what":             case["what"],
        "asks":             case["asks"],
        "validate_error":   validate_error,
        "markdown_error":   markdown_error,
        "slack_error":      slack_error,
        "event_stages":     stages,
        "dates":            [event["date"] for event in bundle["events"]],
        "markdown_stage_lines": [
            line
            for line in markdown.splitlines()
            if " | " in line and not line.startswith("#")
        ],
    }


# --------------------------------------------------------------------------------------
# GI07 follow-up: what matplotlib decides to do with a dollar sign
# --------------------------------------------------------------------------------------

MATHTEXT_STRINGS = [
    "torcetrapib",
    "cost-$5-per-$1 gain",
    "budget $overrun_{total}$ only",
    "plain $ one dollar",
]


def mathtext_evidence() -> list:
    """Whether matplotlib renders each string as text or as math, and how wide it lands.

    `plots.py` sets no rcParam about mathtext, so matplotlib's default applies: a string
    with a balanced pair of dollar signs is parsed as TeX-like math and the dollars and
    braces are consumed. `Text._preprocess_math` is matplotlib's own decision point, and
    the rendered width beside the width of the same string with its dollars escaped shows
    what the reader sees instead of the retrieved characters.
    """
    import matplotlib.pyplot as plt
    from matplotlib.text import Text

    probe = Text()
    figure = plt.figure(figsize=(8.0, 2.0))
    renderer = figure.canvas.get_renderer()
    rows = []
    for value in MATHTEXT_STRINGS:
        _stripped, is_math = probe._preprocess_math(value)
        literal = value.replace("$", r"\$")
        drawn = figure.text(0.01, 0.5, value, fontsize=6.0)
        escaped = figure.text(0.01, 0.2, literal, fontsize=6.0)
        rows.append({
            "string":          value,
            "matplotlib_math": bool(is_math),
            "width_px":        round(drawn.get_window_extent(renderer).width, 1),
            "escaped_width_px": round(escaped.get_window_extent(renderer).width, 1),
        })
    plt.close(figure)
    return rows


# ------------------------------------------------------------------------------------
# the findings, as data - the taxonomy and reachability of every claim this suite makes
# ------------------------------------------------------------------------------------

FINDINGS = [
    {
        "id":            "T1",
        "title":         "The figure credits the registry for a stopping reason and a status the registry never supplied",
        "severity":      "defect",
        "detail":        "plots.py:1104-1108 falls back from the registry record to the Open Targets report for both overall_status and why_stopped, while plots.py:1385 prints \"stopped report(s) carry the registry's own reason\" unconditionally. The year already has a per-value provenance tag and its own footer line; status and reason do not.",
        "evidence":      "GI03 (registry why_stopped withheld) and GI04 (registry overall_status withheld). artifacts/canvas_text/GI03.txt and GI04.txt; the 'registry asked:' line records exactly what the registry was sent.",
        "reachability":  "Any run whose dossier carries a status or why_stopped the registry record does not. Ordinary retrieved Open Targets data, not a user input.",
        "cases":         ["GI03", "GI04"],
    },
    {
        "id":            "T2",
        "title":         "The stopped state is a substring test on an unanchored, retrieval-controlled status string",
        "severity":      "defect",
        "detail":        "plots.py:1115 uses any(word in status for word in _TERMINAL_STATUSES). A COMPLETED trial whose status text contains the word terminated is drawn with the stopped glyph and its text printed. The status half of that label is also not elided, unlike the reason.",
        "evidence":      "GI15: both reports drawn as stopped, footer claims 2 stopped reports carry the registry's own reason. artifacts/canvas_text/GI15.txt.",
        "reachability":  "Any report whose free-text status contains a terminal word in any position.",
        "cases":         ["GI15"],
    },
    {
        "id":            "T3",
        "title":         "The undated footer asserts something about the registry for reports the registry was never asked about",
        "severity":      "defect",
        "detail":        "plots.py:1344 collapses three different facts - no NCT id, id not looked up, registry carries no date - into 'carry no year in the registry'. _lane_markers' own docstring keeps them distinct.",
        "evidence":      "GI02: the registry was asked for 1 id while the footer claims 3 reports carry no year in the registry. GI18: that sentence sits beside 'registry lookup(s) failed; treat those reports as no information'.",
        "reachability":  "Any dossier with a clinical report lacking an NCT id. Open Targets label and regulatory records carry none, and _nct_id deliberately returns '' for them.",
        "cases":         ["GI02", "GI18"],
    },
    {
        "id":            "T4",
        "title":         "Truncating the stopping reason at 40 characters can invert its meaning",
        "severity":      "scope_limit",
        "detail":        "MAX_WHY_CHARS = 40. The cut is disclosed as a count on the figure; a meaning change is not disclosable as a count.",
        "evidence":      "GI05: the retrieved reason 'deaths in the treatment arm were later traced to a data-entry error and the sponsor closed the study administratively' is drawn as 'terminated: deaths in the treatment arm were late...'.",
        "reachability":  "Any registry why_stopped longer than 40 characters.",
        "cases":         ["GI05"],
    },
    {
        "id":            "T5",
        "title":         "trial_phase, status and the GWAS dataset label carry no character budget, contrary to the module's own contract",
        "severity":      "defect",
        "detail":        "plots.py's module docstring states that no label leaves the canvas without saying it was cut. Drug (30 chars) and gene (28 chars) obey it; the phase label (plots.py:1113), the status half of the stop label (plots.py:1281-1287) and the _gwas_years dataset id do not. The per-marker stagger at plots.py:1270 has four offsets, so the fifth report in one year reuses the first.",
        "evidence":      "GI08 draws a 76-character free-text phase in full with no shortened count. GI17 loses 7.0 px of a 111-character GWAS label off the canvas edge, measured from the label's pixel box. GI20 - five ordinary trials all starting 2004 - prints 'Phase 2b dose finding' exactly on top of 'Phase 2/Phase 3'.",
        "reachability":  "GI20 needs no adversarial input: five trials of one drug starting in the same year. tools/trials.py records 19 reports on one drug in real data.",
        "cases":         ["GI08", "GI15", "GI17", "GI20"],
    },
    {
        "id":            "T6",
        "title":         "The lane label rolls a cross-indication stage onto a figure that names one disease, and the same number decides the eight-lane cap",
        "severity":      "defect",
        "detail":        "plots.py:1301 prints 'max stage N' with no qualifier; render.py:1606 prints the same number as 'across all of its indications'. The figure footer asserts that a drug's stage for one disease is never its stage for another. _drug_lanes does not filter reports by the run's disease, and plots.py:1058 and 1179 order and cut the lanes by that same cross-indication number. undated is accumulated only over drawn lanes (plots.py:1193-1198).",
        "evidence":      "GI13: the lane reads 'max stage 4' on a figure titled HDL cholesterol -> Coronary artery disease while the report drawn for it is phase 1. GI14: the pair-relevant drug is cut by the cap and its two id-less reports contribute 0 to the undated count.",
        "reachability":  "Every run. Open Targets maxClinicalStage is cross-indication by definition.",
        "cases":         ["GI13", "GI14"],
    },
    {
        "id":            "T7",
        "title":         "A marker drawn on a completion year is indistinguishable from one drawn on a start year",
        "severity":      "defect",
        "detail":        "The start-year fallback to the completion year is undisclosed while the x-axis label (plots.py:1308) says 'start'. The module labels derived fallbacks elsewhere, for example the forest plot's derived CI.",
        "evidence":      "GI12: two markers at 2016, one a start year and one a completion year on a record with no start date, drawn identically with no count.",
        "reachability":  "Ordinary registry data - a record with a primary completion date and no start date.",
        "cases":         ["GI12"],
    },
    {
        "id":            "T8",
        "title":         "One retrieved string can deny the whole figure, because matplotlib parses dollar signs as mathtext",
        "severity":      "defect",
        "detail":        "plots.py sets no mathtext rcParam. Text._preprocess_math returns ismath=True for 'cost-$5-per-$1 gain' and 'budget $overrun_{total}$ only'; the rendered widths differ from the same strings with escaped dollars (86.0 vs 77.5 px, 99.0 vs 123.9 px), so the drawn glyphs are not the retrieved characters. A malformed span raises at savefig time.",
        "evidence":      "GI07 (drug name and reason rendered as math). GI21: 'budget $1{2 per site$ exceeded' raises ValueError/ParseFatalException, no figure is written, and slack_app.py:2112-2120 posts FIGURE_FAILED_NOTE. artifacts/results.json -> mathtext.",
        "reachability":  "A retrieved drug name or stopping reason containing a balanced pair of dollar signs; cost figures in a why_stopped are the plausible vector.",
        "cases":         ["GI07", "GI21"],
    },
    {
        "id":            "T9",
        "title":         "A year axis prints two decimal places whenever every drawn year is the same year",
        "severity":      "defect",
        "detail":        "span = (ceiling - floor) or 2.0 collapses to the 2.0 fallback for a single year, giving a 2003.76-2004.40 view. MaxNLocator(integer=True) drops the integer constraint when fewer than min_n_ticks integers fall inside the view.",
        "evidence":      "GI19 tick labels: 2003.76 2003.84 2003.92 2004.00 2004.08 2004.16 2004.24 2004.32 2004.40.",
        "reachability":  "Not adversarial: one drug, one report, a retrieved start year and no completion date.",
        "cases":         ["GI19"],
    },
    {
        "id":            "T10",
        "title":         "No plausibility floor on a year, and an implausible one rescales every real marker",
        "severity":      "observation",
        "detail":        "The footer discloses provenance for an Open Targets year but never implausibility, and the x-axis label still names ClinicalTrials.gov.",
        "evidence":      "GI10: years 1850 and 2099 accepted, axis ticks reach 2160, the real 2004 marker and the 2020 GWAS line compressed. GI17: a GWAS year of 2099 accepted, axis to 2130.",
        "reachability":  "report['year'] and the exposure year. tools/trials.py records that report['year'] is null on every report this project has seen.",
        "cases":         ["GI10", "GI17"],
    },
    {
        "id":            "T11",
        "title":         "An impossible interval is dropped rather than reported",
        "severity":      "observation",
        "detail":        "plots.py:1247 draws the bar only when x1 > x0; a completion year before the start year produces no bar and no note.",
        "evidence":      "GI11: start 2016, completion 2009. The marker is indistinguishable from one whose completion date was never retrieved.",
        "reachability":  "Registry data quality.",
        "cases":         ["GI11"],
    },
    {
        "id":            "T12",
        "title":         "One trial reached through two genes is drawn as two lanes and counted as two reports",
        "severity":      "observation",
        "detail":        "The forest plot has an explicit distinct-triple guard against exactly this reading; the timeline has none.",
        "evidence":      "GI16: the same drug and the same NCT00134264 under two genes. The registry is asked once, and the figure says '2 dated reports drawn'.",
        "reachability":  "Any drug whose target set includes two of the run's effector genes.",
        "cases":         ["GI16"],
    },
    {
        "id":            "T13",
        "title":         "Homoglyph drug names are neither normalized nor distinguished",
        "severity":      "observation",
        "detail":        "The mirror image of the parent study's F5: there a normalization gap changed meaning, here the absence of normalization hides a difference.",
        "evidence":      "GI09: two lanes, 'torcetrapib' and a Cyrillic-homoglyph spelling, visually identical at 7.5 pt. Code points preserved in artifacts/canvas_text/GI09.txt.",
        "reachability":  "Upstream data only; drug names come from Open Targets.",
        "cases":         ["GI09"],
    },
    {
        "id":            "L1",
        "title":         "PR #14's central check does fire - positive verification",
        "severity":      "observation",
        "detail":        "Both validators refuse a bundle missing the required stages, so the claim in prepare_cetp_examples.py is real for the case it names.",
        "evidence":      "LC06: render_bundle.validate_bundle raises 'ValueError: Timeline silently omits required stages: human_genetics, preclinical'; the viewer's own validate() raises 'Error: Timeline silently omits a required lifecycle stage.'",
        "reachability":  "Build time, and the viewer's Open snapshot file input.",
        "cases":         ["LC06"],
    },
    {
        "id":            "L2",
        "title":         "An event whose stage is not in display_order is silently dropped from the rendered timeline",
        "severity":      "defect",
        "detail":        "Neither validator checks evidence_stage against timeline_standard.display_order, and viewer.template.html:143-145 filters the rendered stages by it. The standard's own note says a missing stage must never be silently omitted.",
        "evidence":      "LC03: programme-stop, the Pfizer safety stop, relabelled regulatory_action. Both validators pass; the viewer renders 10 of 11 events and drops it with no notice, while the Markdown and Slack renderings still contain it.",
        "reachability":  "The viewer's Open snapshot file input accepts an arbitrary local bundle and is exercised by qa_viewer.cjs; a bundle author can also write the stage directly.",
        "cases":         ["LC03"],
    },
    {
        "id":            "L3",
        "title":         "The required-stage check is a label-presence check, not an evidence check",
        "severity":      "defect",
        "detail":        "render_bundle.py:68 builds a set of evidence_stage strings and asks only whether each required string is present. Nothing looks at the event the label is attached to.",
        "evidence":      "LC04: the 2017 anacetrapib class outcome relabelled human_genetics and the 1989 CETP-deficiency paper relabelled clinical. Both validators pass; the viewer renders 'Human genetics 2017' and 'Clinical development 1989-2007'. LC05 - required_stages emptied, every event clinical - is the weaker scope_limit version.",
        "reachability":  "Bundle authoring; the loaded-snapshot path accepts the same bundle.",
        "cases":         ["LC04", "LC05"],
    },
    {
        "id":            "L4",
        "title":         "The lifecycle guarantee is opt-in, and no missing-stage display exists",
        "severity":      "scope_limit",
        "detail":        "Both checks are guarded by 'if standard:' and 'if(b.timeline_standard)'. PR #14's reference document asks to show the gap and the retrieval diagnostic; what was implemented is a build-time raise, so a failing bundle produces no page at all. The standard's second clause - target-class and compound-specific evidence must remain distinct - is carried only in free-text scope and is checked by nothing.",
        "evidence":      "LC02: timeline_standard removed and every evidence_stage stripped. Both validators pass; the viewer renders one 'Unspecified 1989-2026' group and the Markdown prints 'unspecified' eleven times.",
        "reachability":  "The viewer's file input; the superseded v1 CETP bundles have exactly this shape.",
        "cases":         ["LC02"],
    },
    {
        "id":            "L5",
        "title":         "The shipped evacetrapib page orders its stage groups against its own dates",
        "severity":      "defect",
        "detail":        "display_order is fixed and not date-aware. PR #14's reference document says not to move genetics before the clinic if the real dates are reversed; the shipped page does the mirror image, moving genetics after the clinic when the dates put it first. The two printed ranges overlap with nothing saying so.",
        "evidence":      "LC08: the shipped bundle's first later_genetics event is 2012-05-17 and its first clinical event is 2012-10, yet the viewer renders 'Clinical development 2012-2017' then 'Later genetics 2012-2017'. recordings/cetp-evacetrapib-v2/bundle.json is byte-identical to the snapshot measured.",
        "reachability":  "The shipped artifact.",
        "cases":         ["LC08"],
    },
    {
        "id":            "L6",
        "title":         "The chronology guard compares date strings, and ISO 8601 basic format inverts it",
        "severity":      "defect",
        "detail":        "render_bundle.py:63 compares the date strings. Python 3.11+ date.fromisoformat accepts basic format, and '2007-11-05' sorts below '20070115' because the hyphen sorts below a digit. The viewer's own regex rejects the format, so render_bundle.py can write a bundle.json the shipped viewer refuses to load. render() also embeds the bundle and calls render() at startup without calling validate() (viewer.template.html:183), so the two validators never check the same bundle.",
        "evidence":      "LC09: the TRUE order, January then November, raises 'Events must be chronological'. LC10: the REVERSED order passes. LC07 isolates the validator divergence.",
        "reachability":  "Bundle authoring.",
        "cases":         ["LC07", "LC09", "LC10"],
    },
    {
        "id":            "A1",
        "title":         "Markdown emphasis in a retrieved why_stopped reaches the card - adjacent surface",
        "severity":      "observation",
        "detail":        "render._text flattens newlines, so a forged '##' does not become a heading, but inline emphasis survives into the section 6 bullet that the timeline footer points readers at. On the figure the same string is merely truncated text (GI06); a PNG has no headings.",
        "evidence":      "render._report_line with why_stopped='## SAFETY CONFIRMED\\n\\n**Recommendation:** start this drug.' returns '... why stopped ## SAFETY CONFIRMED **Recommendation:** start this drug., for ...'.",
        "reachability":  "A retrieved Open Targets field, not model prose. Belongs to the card/dossier surface; recorded here only because the timeline names section 6 as its overflow destination.",
        "cases":         ["GI06"],
    },
]


# --------------------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------------------

def normalize(value):
    """Everything the expectation file compares, with NFC applied to every string.

    A probe about unicode normalization must not itself be the thing that normalizes.
    NFC is applied only to the serialized comparison so that a Windows filesystem round
    trip cannot change a result; the codepoints of every captured label are also written
    verbatim to `artifacts/canvas_text/`.
    """
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    return value


def main() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "figures").mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "canvas_text").mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "lifecycle").mkdir(parents=True, exist_ok=True)

    import matplotlib
    import plots                                          # noqa: F401  (imported for side effects)
    import tools.trials                                   # noqa: F401  (stub target)
    import render_bundle                                  # noqa: F401

    install_text_capture()
    seal_network()

    log = []
    results = []
    for case in CASES:
        observation = run_gi_case(case)
        results.append(observation)
        (ARTIFACTS / "canvas_text" / f"{case['id']}.txt").write_text(
            "\n".join(
                [
                    f"case: {observation['case']}",
                    f"what: {observation['what']}",
                    f"asks: {observation['asks']}",
                    f"figure: {observation['figure']} {observation['figure_file']}",
                    f"stdout: {observation['stdout']}",
                    f"registry asked: {', '.join(observation['registry_asked']) or '(nothing)'}",
                    f"exception: {observation['exception'] or '(none)'}",
                    f"draw error: {observation['draw_error'] or '(none)'}",
                    "",
                    "--- labels drawn off the canvas (px lost) ---",
                ]
                + (
                    [
                        f"{item['lost_px']:>7} px  {item['text']!r}"
                        for item in observation["overflowing"]
                    ]
                    or ["(none)"]
                )
                + [
                    "",
                    "--- label pairs printed over each other ---",
                ]
                + (
                    [
                        f"{item['a']!r}  OVER  {item['b']!r}"
                        for item in observation["collisions"]
                    ]
                    or ["(none)"]
                )
                + [
                    "",
                    "--- every string drawn on the canvas ---",
                ]
                + [repr(text) for text in observation["canvas_texts"]]
            )
            + "\n",
            encoding = "utf-8",
            newline  = "\n",
        )
        log.append(f"{case['id']}  {observation['figure']:6s}  {observation['stdout']}")

    lifecycle = []
    for case in LC_CASES:
        observation = run_lc_case(case)
        lifecycle.append(observation)
        log.append(
            f"{case['id']}  validate: {observation['validate_error'] or 'passed'}"
        )

    payload = {
        "revision":          "b056397",
        "python":            sys.version.split()[0],
        "matplotlib":        matplotlib.__version__,
        "network":           "sealed: socket.socket raises",
        "registry":          "stubbed: tools.trials.get_trial_dates replaced per case",
        "gi_cases":          normalize(results),
        "lc_cases":          normalize(lifecycle),
        "mathtext":          normalize(mathtext_evidence()),
    }

    (ARTIFACTS / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding = "utf-8",
        newline  = "\n",
    )

    with (ARTIFACTS / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case", "surface", "figure_or_validate", "stdout_or_error", "what"])
        for row in results:
            writer.writerow([
                row["case"],
                "plots.plot_genetic_insight",
                row["figure"],
                row["stdout"],
                row["what"],
            ])
        for row in lifecycle:
            writer.writerow([
                row["case"],
                "render_bundle.validate_bundle",
                "raised" if row["validate_error"] else "passed",
                row["validate_error"],
                row["what"],
            ])

    # RESULTS.md is generated from the same observations as results.json so the prose
    # table can never drift from the measurement.
    table = [
        "# Timeline lifecycle probes - result table",
        "",
        "Generated by `probe_timeline.py`. Do not edit by hand.",
        "",
        "## GI - `plots.plot_genetic_insight` (live per-run figure)",
        "",
        "| case | figure | registry asked | what was probed |",
        "|---|---|---|---|",
    ]
    for row in results:
        asked = ", ".join(row["registry_asked"]) or "(nothing)"
        outcome = row["figure"] if not row["exception"] else "RAISED"
        table.append(f"| {row['case']} | {outcome} | {asked} | {row['what']} |")
    table += [
        "",
        "## LC - PR #14 lifecycle standard (`render_bundle.py` + `viewer.template.html`)",
        "",
        "| case | python validate_bundle | what was probed |",
        "|---|---|---|",
    ]
    for row in lifecycle:
        table.append(
            f"| {row['case']} | {row['validate_error'] or 'passed'} | {row['what']} |"
        )
    table += [
        "",
        "The viewer half of every LC case is in `viewer_stages.txt` / `viewer_stages.json`,",
        "produced by `viewer_stage_probe.cjs` from the template's own source lines.",
        "",
    ]
    (ARTIFACTS / "RESULTS.md").write_text(
        "\n".join(table),
        encoding = "utf-8",
        newline  = "\n",
    )

    (ARTIFACTS / "findings.json").write_text(
        json.dumps(
            {
                "revision": "b056397",
                "taxonomy": "defect / scope_limit / observation, per the parent study's DESIGN_JUDGMENT.md",
                "findings": FINDINGS,
            },
            ensure_ascii = False,
            indent       = 2,
        ) + "\n",
        encoding = "utf-8",
        newline  = "\n",
    )

    (ARTIFACTS / "run.log").write_text(
        "\n".join(log) + "\n",
        encoding = "utf-8",
        newline  = "\n",
    )

    # The manifest names exactly which bytes were measured, like Zipeng's
    # artifacts/manifest.json. A finding about plots.py is a finding about this hash.
    measured = [
        "plots.py",
        "tools/trials.py",
        "slack_app.py",
        "render.py",
        "demo/genetic-insights/render_bundle.py",
        "demo/genetic-insights/viewer.template.html",
        "demo/genetic-insights/prepare_cetp_examples.py",
        "demo/genetic-insights/snapshots/mvp1-cetp-torcetrapib-2026-09-12-v2.json",
        "demo/genetic-insights/snapshots/mvp1-cetp-evacetrapib-2026-09-12-v2.json",
    ]
    (ARTIFACTS / "manifest.json").write_text(
        json.dumps(
            {
                "revision":     "b056397",
                "probe":        "docs/research/section9_adversarial/rerun_2026-09-17/new_probes/timeline/probe_timeline.py",
                "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "python":       sys.version.split()[0],
                "matplotlib":   matplotlib.__version__,
                "network":      "sealed",
                "gi_cases":     len(CASES),
                "lc_cases":     len(LC_CASES),
                "sources": {
                    name: hashlib.sha256((REPO_ROOT / name).read_bytes()).hexdigest()
                    for name in measured
                },
                "figures": {
                    row["figure_file"]: row["figure_sha256"]
                    for row in results
                    if row["figure_file"]
                },
            },
            ensure_ascii = False,
            indent       = 2,
        ) + "\n",
        encoding = "utf-8",
        newline  = "\n",
    )

    expected_path = HERE / "expected.json"
    comparable = {
        "gi": {
            row["case"]: {
                "figure":         row["figure"],
                "stdout":         row["stdout"],
                "registry_asked": row["registry_asked"],
                "exception":      row["exception"],
                "draw_error":     row["draw_error"],
                "canvas_texts":   row["canvas_texts"],
                "overflowing":    [item["text"] for item in row["overflowing"]],
                "collisions":     [[item["a"], item["b"]] for item in row["collisions"]],
            }
            for row in normalize(results)
        },
        "lc": {
            row["case"]: {
                "validate_error": row["validate_error"],
                "markdown_error": row["markdown_error"],
                "slack_error":    row["slack_error"],
                "event_stages":   row["event_stages"],
                "dates":          row["dates"],
            }
            for row in normalize(lifecycle)
        },
    }

    if not expected_path.exists():
        expected_path.write_text(
            json.dumps(comparable, ensure_ascii=False, indent=2) + "\n",
            encoding = "utf-8",
            newline  = "\n",
        )
        print(f"[probe] wrote first expected.json ({len(CASES)} GI + {len(LC_CASES)} LC cases)")
        return 0

    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    drift = []
    for family in ("gi", "lc"):
        for case_id, observed in comparable[family].items():
            want = expected.get(family, {}).get(case_id)
            if want is None:
                drift.append(f"{case_id}: no expectation recorded")
                continue
            for key, value in observed.items():
                if want.get(key) != value:
                    drift.append(f"{case_id}.{key}: expected {want.get(key)!r}, observed {value!r}")

    if drift:
        print("[probe] EXPECTED RESULT CHANGED")
        for line in drift[:40]:
            print("  " + line)
        return 1

    print(f"[probe] {len(CASES)} GI + {len(LC_CASES)} LC cases, all as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
