"""One figure per run, drawn from the run's own envelopes. No number is typed in here.

    from pipeline import run_pair
    from plots import plot_for_result

    png = plot_for_result(run_pair("urate", "gout"))     # cards/urate_gout_mr_forest.png

Offline, from the frozen snapshot in data/demo_card_inputs.json (no credits, no network):

    python plots.py                       # every demo pair -> cards/
    python plots.py --pair "urate|gout"
    python plots.py --live --metabolite urate --disease gout

WHICH FIGURE, AND WHY ONLY THESE THREE ANSWERS
  State A   forest plot of the RETRIEVED MR estimates. One row per returned row, point at
            b, source CI whiskers (derived fallback labelled), a line at zero.
  State B   instrument-strength chart: genome-wide significant loci per exposure dataset,
            with the weak-instrument count beside each bar. A feasibility report, never an
            effect.
  State C   nothing. There is no retrieved estimate and no analysis-ready dataset, so any
            picture would be a picture of nothing. `plot_for_result` returns None and says
            why on stdout - an absent figure is the honest output, not a failure.

AND ONE FIGURE THAT IS NOT ABOUT THE STATE
  plot_genetic_insight  the genetic-insight timeline: one lane per drug on this run's
            effector genes, each clinical report at the year ClinicalTrials.gov records,
            against the year the exposure GWAS was published. It is drawn on demand - the
            Slack shell has a button for it - because it needs the gene arm AND a drug
            with a dated trial, and it returns None rather than guessing a year when
            either is missing. It is the only figure here that sends a request of its own
            (the registry has the years, and Open Targets does not).

WHAT THE FIGURES REFUSE TO DO
  - MR estimates are retrieved. Source CI is preferred; derived fallback is labelled. The
    point is the b that came back. No meta-analysis, no pooling, no re-weighting.
  - Every cap is printed ON the figure: the 15-row forest cap, the tool's own
    max_datasets cap, and the number of rows dropped for missing b or an unusable interval. A silently
    truncated plot is the visual version of the pagination bug this project was built
    against.
  - MR-EVE returns one row per method AND one row per deposited dataset id, so the same
    study appears several times. The figure prints how many distinct (b, se, p) triples
    its rows actually carry, so nobody reads 15 rows as 15 independent studies.
  - Effect sizes are per unit of each exposure dataset's own scale (ukb-d-30880_raw and
    ukb-d-30880_irnt differ by ~84x), so the x-axis is not comparable across rows and the
    figure says so. The dataset id is on every row for exactly this reason. A row whose
    interval is too narrow to draw at the shared scale gets an OPEN marker and its own
    numbers printed beside it, so a dot resting on the zero line can never be read as a
    null when it is ten standard errors away from one.
  - No label leaves the canvas without saying it was cut: titles are measured against the
    real canvas and axis labels carry a character budget, and both count what they
    shortened in the footer.
  - An empty envelope draws nothing and returns None. It never draws an empty axis with a
    zero on it, which would read as "no effect" when it means "not in this snapshot".

The model writes none of this: the only text on a figure is a label, an id, a count or a
caveat that came out of the envelope.
"""

from __future__ import annotations

import json
import math
import re
import sys
import textwrap
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import matplotlib

matplotlib.use("Agg")                  # a Slack worker on Windows has no display
# Every label on these figures can carry a retrieved string (a drug name, a stopping
# reason, a GWAS dataset id), and matplotlib's default text path parses a balanced pair of
# "$" as TeX-like mathtext: the glyphs drawn stop being the retrieved characters, and an
# unbalanced pair raises at savefig time and denies the whole figure (T8). Nothing here is
# ever meant to render as math, so parsing is turned off - neutralized by disabling the
# parser, never by deleting a character.
#
# This rcParam is PROCESS-WIDE, not module-scoped: importing this module changes the
# default for every matplotlib user in the same interpreter, and any later
# plt.rcdefaults(), plt.style.use(...) or rc_context in that process would put it back.
# So the default is only half of it - NO_MATHTEXT below is passed explicitly on every Text
# this module creates from a retrieved string, so the guarantee travels with the drawing
# call rather than with process state.
matplotlib.rcParams["text.parse_math"] = False
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from matplotlib.transforms import blended_transform_factory

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ledger
import render                            # stdlib only: the card's formatters, shared

CARDS_DIR = REPO_ROOT / "cards"
DEMO_PATH = REPO_ROOT / "data" / "demo_card_inputs.json"

# Spread onto every text call this module makes with a retrieved string in it. See the
# rcParam comment above: the rcParam is the default, this is the guarantee.
NO_MATHTEXT = {"parse_math": False}

# One muted blue for the data, greys for everything that is not data. No colour carries
# meaning that the text does not also carry, so the figures survive a greyscale print.
BLUE = "#31547f"
INK = "#1a1a1a"
GREY = "#57606a"
HAIR = "#bbbbbb"

# 8.0 in x 150 dpi = 1200 px wide, which is what Slack renders without resampling.
FIG_WIDTH_IN = 8.0
DPI = 150
MAX_ROWS = 15

FOREST_SUFFIX = "_mr_forest.png"
INSTRUMENT_SUFFIX = "_instruments.png"

FOREST_TITLE = "{metabolite} -> {disease}: retrieved MR estimates (EpiGraphDB MR-EVE)"
INSTRUMENT_TITLE = "{metabolite}: genome-wide significant instruments per dataset"

FOREST_FOOTER = "Retrieved, not computed. OpenGWAS 2020-10-13 snapshot."
# The figure travels to Slack on its own, so it carries the whole sentence the card
# carries. "0 weak" beside a bare "F=(beta/se)^2" is the most flattering possible reading
# of a statistic that is inflated by the same scan that selected the SNPs.
INSTRUMENT_FOOTER = (
    "F=(beta/se)^2 on feasibility hits; weak = F<10. Potentially upward-biased by winner's curse; "
    "not the F of the original instruments behind retrieved MR estimates."
)

_NOT_IN_SNAPSHOT = "not available in this snapshot"
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

# Label budgets. A y-tick label wider than the axes makes tight_layout give up, the rect
# that was reserving the footer band is ignored, and the figure is still written - with
# the labels sliced off the left edge and the caveats printed over the x-axis. Real
# gwasinfo traits reach 206 characters, so every axis label gets a budget and every
# shortening is counted on the figure.
MAX_TRAIT_CHARS = 48
MAX_ID_CHARS = 28
MAX_METHOD_CHARS = 22
# A footer caveat at 7pt fits about this many characters across the 8-inch canvas.
FOOTER_WRAP_CHARS = 145
ELLIPSIS = "..."

# A title is drawn with fig.text, which does not wrap and does not clip: a long pair name
# simply leaves the canvas, and it is the DISEASE end of the forest title that goes.
TITLE_LEFT = 0.012
TITLE_RIGHT = 0.985
MIN_TITLE_CHARS = 24

# An interval narrower than this fraction of the x-axis cannot be drawn: it renders as a
# bare dot, and a dot on the zero line reads as a null result even when the row carries
# p = 1.46e-15 on a different measurement scale.
NARROW_FRACTION = 0.01


# --------------------------------------------------------------------------------------
# formatting - the same rules the card uses, so a figure and its card never disagree
# --------------------------------------------------------------------------------------

def finite(value):
    """`float(value)` when it is a real, finite number, else None.

    None, "", a string, nan and inf all become None and are handled as missing. A nan
    that reached an axis would draw an invisible row that still took up space and still
    counted towards the cap.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fmt_sig(
    value,
    digits: int = 4,
) -> str:
    """A number for a scientist: exactly `digits` significant figures, or the honest
    phrase when the snapshot did not return one.

    Not "%.4g": that drops trailing zeros, so an se of 0.022697 prints as "0.0227" and
    silently claims three figures where the source gave four. The arithmetic lives in
    `render.format_sig` and the card's own `_effect` calls it too, so a number on this
    figure and the same number in the table beside it cannot differ.
    """
    number = finite(value)
    if number is None:
        return _NOT_IN_SNAPSHOT
    return render.format_sig(number, digits)


def fmt_p(value) -> str:
    """A p-value in scientific notation, never "0.0".

    A p that underflowed to zero in the source is printed as "<1e-300": the source lost
    the exponent, and printing 0.0 would claim a certainty that no test produces. The
    card adds what the source actually said ("<1e-300 (reported 0)"); a tick label has no
    room for the clause, and the bound itself is `render.PVALUE_UNDERFLOW` on both.
    """
    number = finite(value)
    if number is None:
        return "n/a"
    if number <= 0 or number < 1e-300:
        return render.PVALUE_UNDERFLOW
    return f"{number:.2e}"


def elide(
    value,
    budget: int,
) -> tuple:
    """(text, was_shortened) - a label cut to `budget` characters with a trailing "...".

    A figure that loses text off the edge of its own canvas is a silent truncation, and
    this project treats a silent truncation as worse than an error. Every caller counts
    what came back True and prints the count on the figure.
    """
    text = " ".join(str(value or "").split())
    if len(text) <= budget:
        return text, False
    return text[: max(1, budget - len(ELLIPSIS))].rstrip() + ELLIPSIS, True


def _plural(
    count: int,
    noun:  str,
) -> str:
    """"1 row" / "22 rows". A figure that says "1 dataset(s)" looks unread."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _slug(value) -> str:
    """The filesystem-safe half of a stem. A local copy of `pipeline.slug` on purpose:
    importing pipeline here would pull the whole tools package (and requests) into a
    module whose only job is drawing, and would invite a circular import later."""
    text = _SLUG_STRIP.sub("-", str(value or "").strip().lower()).strip("-")
    return text or "unknown"


def display_name(side) -> str:
    """The name to put on a figure for one side of the pair.

    `run_pair` returns each side as the resolver's dict, so prefer what the user actually
    asked for ("urate") over 1A's canonical label, which for urate is
    "7,9-dihydro-1H-purine-2,6,8(3H)-trione" and would own the whole title.
    """
    if isinstance(side, dict):
        for key in ("query", "input", "label"):
            value = str(side.get(key) or "").strip()
            if value:
                return value
        return "unknown"
    return str(side or "").strip() or "unknown"


# --------------------------------------------------------------------------------------
# shared drawing furniture
# --------------------------------------------------------------------------------------

def _style(ax) -> None:
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(HAIR)
    ax.tick_params(colors="#444444", labelsize=8)
    ax.set_facecolor("white")


def _fit_title(
    fig,
    title:  str,
    height: float,
) -> tuple:
    """(title that fits on this canvas, was_shortened).

    `parse_pair` accepts a name up to 120 characters, so a mention can produce a title
    wider than the figure. fig.text neither wraps nor clips, and the disease sits at the
    END of the forest title - so the half that disappears is the half that says what the
    metabolite was tested against, on a figure whose whole point is the direction.

    Measured with a real renderer against a real canvas rather than guessed from a
    character count, because the width of a title depends on which characters are in it.
    """
    probe = fig.text(
        TITLE_LEFT,
        1 - 0.30 / height,
        title,
        fontsize = 12.5,
        color    = INK,
        ha       = "left",
        va       = "top",
        **NO_MATHTEXT,
    )
    body, shortened = str(title), False
    try:
        renderer = fig.canvas.get_renderer()
        limit = fig.get_figwidth() * fig.dpi * (TITLE_RIGHT - TITLE_LEFT)
        while True:
            probe.set_text(body + (ELLIPSIS if shortened else ""))
            if probe.get_window_extent(renderer=renderer).width <= limit:
                break
            if len(body) <= MIN_TITLE_CHARS:
                break
            shortened = True
            body = body[: max(MIN_TITLE_CHARS, int(len(body) * 0.9))].rstrip()
    except Exception:                                    # pragma: no cover - no renderer
        body, shortened = str(title), False
    finally:
        probe.remove()
    return (body + ELLIPSIS if shortened else str(title)), shortened


def _reserve_bands(
    fig,
    ax,
    footer_lines: int,
    height:       float,
) -> None:
    """Give the header and the footer their bands, and never let a long y-label take them.

    fig.tight_layout silently gives up when the tick labels are wider than the axes area
    ("Tight layout not applied") - the rect that was reserving the footer band is ignored
    and the figure is still written, with the caveats printed over the x-axis. So the
    result is checked, and a fixed-margin layout is used whenever tight_layout did not
    leave the bands alone.
    """
    bottom = (0.13 + 0.16 * footer_lines) / height
    top = 1 - 0.72 / height
    fig.tight_layout(rect=[0, bottom, 1, top])
    position = ax.get_position()
    if position.y0 < bottom - 1e-6 or position.y1 > top + 1e-6 or position.width < 0.25:
        fig.subplots_adjust(
            left   = 0.40,
            right  = 0.96,
            bottom = bottom,
            top    = top,
        )


def _draw_header(
    fig,
    title:    str,
    subtitle: str,
    height:   float,
) -> None:
    """Title on the first line, the count of what is drawn on the second. The subtitle is
    where "showing 15 of 22" lands, next to the title rather than in the small print."""
    fig.text(
        0.012,
        1 - 0.30 / height,
        title,
        fontsize = 12.5,
        color    = INK,
        ha       = "left",
        va       = "top",
        **NO_MATHTEXT,
    )
    fig.text(
        0.012,
        1 - 0.54 / height,
        subtitle,
        fontsize = 8.5,
        color    = GREY,
        ha       = "left",
        va       = "top",
        **NO_MATHTEXT,
    )


def wrap_footer(lines: list) -> list:
    """Footer lines split at a word boundary so none can run off the right edge.

    fig.text neither wraps nor clips, so a caveat longer than the canvas is simply cut at
    the edge with nothing saying it was - the same silent truncation the axis labels get a
    budget for. Every caveat this module writes is already inside the budget; this is the
    net under the next one somebody adds.
    """
    wrapped = []
    for line in lines:
        text = " ".join(str(line).split())
        wrapped.extend(textwrap.wrap(text, FOOTER_WRAP_CHARS) or [""])
    return wrapped


def _draw_footer(
    fig,
    lines:  list,
    height: float,
) -> None:
    """Every caveat that belongs to this figure, bottom left, smallest first line last.
    Drawn with fig.text rather than inside the axes so a long caveat never overlaps a
    data point."""
    for index, line in enumerate(reversed(lines)):
        fig.text(
            0.012,
            (0.13 + 0.16 * index) / height,
            line,
            fontsize = 7.0,
            color    = GREY,
            ha       = "left",
            va       = "bottom",
            **NO_MATHTEXT,
        )


def _save(
    fig,
    out_path: Path,
) -> str:
    """Write the PNG and ALWAYS close the figure.

    slack_app runs as a persistent Socket Mode worker. A savefig that raises - a
    read-only cards/, a full disk, an antivirus hold on Windows - used to leave the
    Figure registered in pyplot's manager holding its Agg canvas, so every failed mention
    leaked one and matplotlib eventually started warning about 20 open figures. The
    caller catches the exception, so the symptom was memory rather than a crash.
    """
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(
            out_path,
            dpi        = DPI,
            facecolor  = "white",
        )
    finally:
        plt.close(fig)
    return str(out_path)


# --------------------------------------------------------------------------------------
# State A - the forest plot
# --------------------------------------------------------------------------------------

def _forest_rows(estimates: list) -> tuple:
    """Split the retrieved estimates into what can be drawn and what cannot.

    A row needs finite b plus valid source bounds or a positive finite se; anything else is
    dropped and counted, never drawn at zero. Returns (usable, dropped, missing_p).
    """
    usable, dropped, missing_p = [], 0, 0
    for estimate in estimates:
        if not isinstance(estimate, dict):
            dropped += 1
            continue
        b = finite(estimate.get("b"))
        se = finite(estimate.get("se"))
        low = finite(estimate.get("ci_low"))
        high = finite(estimate.get("ci_upp"))
        source_ci = low is not None and high is not None and low <= high
        if b is None or (not source_ci and (se is None or se <= 0)):
            dropped += 1
            continue
        if not source_ci:
            low, high = b - 1.96 * se, b + 1.96 * se
            if finite(low) is None or finite(high) is None:
                dropped += 1
                continue
        ci_kind = "source CI" if source_ci else "derived CI"
        nsnp = estimate.get("nsnp")
        nsnp_label = str(nsnp) if nsnp is not None else "not reported"
        pval = finite(estimate.get("pval"))
        if pval is None:
            missing_p += 1
        exposure, cut_a = elide(
            estimate.get("exposure_id") or "id not returned",
            MAX_ID_CHARS,
        )
        outcome, cut_b = elide(
            estimate.get("outcome_id") or "id not returned",
            MAX_ID_CHARS,
        )
        method, cut_c = elide(
            estimate.get("method") or "method not returned",
            MAX_METHOD_CHARS,
        )
        usable.append({
            "label":     f"{exposure} -> {outcome} [{method}]\nnsnp={nsnp_label}; {ci_kind}",
            "shortened": bool(cut_a or cut_b or cut_c),
            "b":         b,
            "se":        se,
            "ci_low":    low,
            "ci_upp":    high,
            "ci_kind":   ci_kind,
            "pval":      pval,
        })
    return usable, dropped, missing_p


def plot_forest(
    mr_env:   dict,
    title:    str,
    out_path,
    cap:      int = MAX_ROWS,
) -> str | None:
    """Draw the retrieved MR estimates of one `get_mr_result` envelope, or return None.

    One row per RETRIEVED row: the point is the b that came back, the whiskers are
    source CI (or labelled b +/- 1.96 x se fallback), and the zero line shows which
    intervals cross it. Nothing is pooled; only fallback intervals are derived.

    Rows are sorted by p-value and cut to `cap`; both the cut and the number of rows
    dropped for missing b or an unusable interval are printed on the figure. Returns the path written, or
    None when the envelope carries no drawable row - an empty envelope gets no figure,
    because an empty axis reads as "no effect" and means "not in this snapshot".

    ROWS ARE NOT ON ONE SCALE. Every row is per unit of its own exposure dataset, and
    ukb-d-30880_raw and ukb-d-30880_irnt differ by about 84x, so a row on a small-unit
    scale can carry an interval a couple of pixels wide next to rows on a large-unit
    scale: a dot touching the zero line that is in fact ten standard errors from it. Any
    row whose interval is narrower than `NARROW_FRACTION` of the axis is drawn as an OPEN
    marker, annotated with its own numbers, and counted in the footer - it must not be
    readable as a null.
    """
    data = mr_env.get("data") if isinstance(mr_env, dict) else None
    estimates = data.get("estimates") if isinstance(data, dict) else None
    estimates = [row for row in (estimates or []) if row is not None]

    usable, dropped, missing_p = _forest_rows(estimates)
    if not usable:
        print(f"[forest] no drawable estimate in this envelope ({len(estimates)} row(s) retrieved) - no figure")
        return None

    usable.sort(key=lambda row: (row["pval"] is None, row["pval"] if row["pval"] is not None else 0.0))
    shown = usable[:max(1, int(cap))]
    rows = shown[::-1]                                   # smallest p at the top of the axis

    distinct = len({(row["b"], row["se"], row["pval"]) for row in usable})
    lows = [row["ci_low"] for row in rows]
    highs = [row["ci_upp"] for row in rows]

    height = 0.52 * len(rows) + 2.75 + 0.16 * 3
    fig, ax = plt.subplots(
        figsize = (FIG_WIDTH_IN, height),
        facecolor = "white",
    )
    ax.axvline(
        0,
        color = "#999999",
        lw    = 1.0,
        ls    = "--",
        zorder = 0,
    )

    # The axis is fixed here rather than left to autoscale, because the narrow-interval
    # test below needs a span to measure against and the annotations need room.
    floor = min(lows + [row["b"] for row in rows] + [0.0])
    ceiling = max(highs + [row["b"] for row in rows] + [0.0])
    span = (ceiling - floor) or 1.0
    ax.set_xlim(floor - 0.06 * span, ceiling + 0.06 * span)
    axis_span = ax.get_xlim()[1] - ax.get_xlim()[0]

    narrow = [
        index for index, row in enumerate(rows)
        if (highs[index] - lows[index]) < NARROW_FRACTION * axis_span
    ]
    for index, row in enumerate(rows):
        ax.plot(
            [lows[index], highs[index]],
            [index, index],
            color          = BLUE,
            lw             = 1.6,
            solid_capstyle = "round",
            zorder         = 2,
        )
    wide = [index for index in range(len(rows)) if index not in set(narrow)]
    if wide:
        ax.scatter(
            [rows[index]["b"] for index in wide],
            wide,
            s      = 30,
            color  = BLUE,
            zorder = 3,
        )
    # An OPEN marker, so a row whose interval cannot be drawn at this scale cannot be
    # mistaken for a filled point sitting on the null line.
    if narrow:
        ax.scatter(
            [rows[index]["b"] for index in narrow],
            narrow,
            s          = 46,
            marker     = "D",
            facecolors = "white",
            edgecolors = BLUE,
            linewidths = 1.3,
            zorder     = 4,
        )
        middle = sum(ax.get_xlim()) / 2.0
        for index in narrow:
            row = rows[index]
            to_the_right = row["b"] <= middle
            ax.text(
                row["b"] + (0.015 if to_the_right else -0.015) * axis_span,
                index,
                "interval too narrow to draw at this scale: "
                f"b {fmt_sig(row['b'])}; {row['ci_kind']} "
                f"[{fmt_sig(row['ci_low'])}, {fmt_sig(row['ci_upp'])}]",
                fontsize = 6.5,
                color    = INK,
                ha       = "left" if to_the_right else "right",
                va       = "center",
                zorder   = 5,
            )

    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([row["label"] for row in rows], fontsize=8)
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_xlabel(
        "retrieved effect estimate b (interval origin labelled per row)",
        fontsize = 9,
        color    = INK,
    )
    _style(ax)

    # The p-value column: the sort order is otherwise invisible, and a reader who cannot
    # see p has no way to tell the top row from the bottom one.
    right = ax.twinx()
    right.set_ylim(ax.get_ylim())
    right.set_yticks(range(len(rows)))
    right.set_yticklabels([fmt_p(row["pval"]) for row in rows], fontsize=7.5, color=GREY)
    right.tick_params(length=0, colors=GREY)
    for spine in right.spines.values():
        spine.set_visible(False)
    right.text(
        1.0,
        1.0,
        "p (retrieved)",
        transform = right.transAxes,
        fontsize  = 7.5,
        color     = GREY,
        ha        = "right",
        va        = "bottom",
    )

    drawn_title, title_cut = _fit_title(
        fig,
        title,
        height,
    )
    subtitle = (
        f"Showing {len(shown)} of {len(usable)} drawable rows, sorted by p-value"
        if len(shown) < len(usable)
        else f"Showing all {_plural(len(usable), 'drawable row')}, sorted by p-value"
    )
    if title_cut:
        subtitle += " (title shortened to fit; the full pair is in section 1 of the card)"
    _draw_header(
        fig,
        drawn_title,
        subtitle,
        height,
    )

    footer = [FOREST_FOOTER]
    footer.append(
        "Source CI: retrieved bounds, confidence level unspecified. Derived CI: b +/- 1.96 x se "
        "only when source bounds are missing or invalid and se > 0; normal approximation."
    )
    if distinct < len(usable):
        footer.append(
            f"{len(usable)} rows carry {distinct} distinct (b, se, p): MR-EVE returns one row per "
            "method and one per deposited dataset id, so rows are not independent studies."
        )
    footer.append(
        "Effect sizes are per unit of each exposure dataset's own scale and are not comparable "
        "across rows - read the dataset id on every row."
    )
    if narrow:
        footer.append(
            f"{len(narrow)} drawn row(s) marked with an open point: the interval is "
            f"under {int(NARROW_FRACTION * 100)}% of this axis, so the point is NOT a null "
            "- read its b and p."
        )
    if dropped:
        footer.append(
            f"{dropped} retrieved row(s) dropped: b or a usable interval {_NOT_IN_SNAPSHOT} - "
            "not evidence of no effect."
        )
    if missing_p:
        footer.append(
            f"{missing_p} drawn row(s) carry no p-value in this snapshot; they sort last."
        )
    shortened = sum(1 for row in rows if row.get("shortened"))
    if shortened:
        footer.append(
            f"{shortened} row label(s) shortened to fit the axis; the full dataset ids and "
            "method names are in section 3 of the card."
        )
    footer = wrap_footer(footer)
    _draw_footer(
        fig,
        footer,
        height,
    )

    _reserve_bands(
        fig,
        ax,
        len(footer),
        height,
    )
    written = _save(
        fig,
        Path(out_path),
    )
    print(f"[forest] wrote {Path(written).name}  ({len(shown)}/{len(usable)} rows, {dropped} dropped)")
    return written


# --------------------------------------------------------------------------------------
# State B - the instrument-strength chart
# --------------------------------------------------------------------------------------

def _instrument_rows(exposures: list) -> tuple:
    """The drawable exposure datasets, plus the count that carried no hit count at all.

    A dataset with gws_hits = 0 IS drawable: zero genome-wide significant loci is the
    result, and hiding that row would flatter the pair.
    """
    rows, dropped = [], 0
    for exposure in exposures:
        if not isinstance(exposure, dict):
            dropped += 1
            continue
        hits = finite(exposure.get("gws_hits"))
        if hits is None:
            dropped += 1
            continue
        rows.append({
            "id":       str(exposure.get("id") or "id not returned"),
            "trait":    str(exposure.get("trait") or "trait not returned"),
            "platform": exposure.get("platform"),
            "n":        finite(exposure.get("sample_size")),
            "hits":     int(hits),
            "weak":     finite(exposure.get("weak_instruments")),
            "min_f":    finite(exposure.get("min_f")),
        })
    return rows, dropped


def _instrument_label(row: dict) -> tuple:
    """(label, was_shortened): id, then trait and sample size, then the platform when the
    snapshot carries one.

    A missing platform gets no line of its own: repeated six times down the axis it would
    read as the loudest fact on the figure. It is counted in the footer instead.

    The trait carries a character budget because gwasinfo traits reach 206 characters:
    a y-tick label wider than the axes makes tight_layout give up, and the figure is then
    written with the labels sliced off the left edge and the caveats over the x-axis.
    """
    size = f"N={int(row['n']):,}" if row["n"] is not None else f"N {_NOT_IN_SNAPSHOT}"
    identifier, cut_id = elide(row["id"], MAX_ID_CHARS)
    trait, cut_trait = elide(row["trait"], MAX_TRAIT_CHARS)
    platform, cut_platform = elide(row["platform"], MAX_TRAIT_CHARS)
    label = f"{identifier}\n{trait}, {size}"
    if platform:
        label = f"{label}\n{platform}"
    return label, bool(cut_id or cut_trait or cut_platform)


def _instrument_annotation(row: dict) -> str:
    loci = f"{row['hits']} locus" if row["hits"] == 1 else f"{row['hits']} loci"
    weak = "weak count n/a" if row["weak"] is None else f"{int(row['weak'])} weak"
    strength = "min F n/a" if row["min_f"] is None else f"min F {fmt_sig(row['min_f'])}"
    return f"{loci}  |  {weak}  |  {strength}"


def plot_instruments(
    instr_env: dict,
    title:     str,
    out_path,
    cap:       int = MAX_ROWS,
) -> str | None:
    """Draw the instrument feasibility of one `get_mqtl_instruments` envelope, or None.

    One horizontal bar per exposure dataset, length = gws_hits (OpenGWAS's own pre-clumped
    tophits at p < 5e-8, so independent loci and NOT SNPs), with the weak-instrument count
    and the weakest F beside it. This is a feasibility report: it says an MR could be
    attempted, never that an effect exists, and the figure says so in its own footer.

    TWO DIFFERENT CAPS, NAMED SEPARATELY. The tool's own `max_datasets` decides how many
    of the matched datasets were opened at all; this figure's `cap` decides how many of
    the ones it was handed get a bar. Reporting the second as if it were the first would
    tell a reader the tool never returned rows that it did return, so each cap names
    itself and its own denominator.

    Returns the path written, or None when no dataset came back.
    """
    data = instr_env.get("data") if isinstance(instr_env, dict) else None
    data = data if isinstance(data, dict) else {}
    exposures = [row for row in (data.get("exposures") or []) if row is not None]

    rows, dropped = _instrument_rows(exposures)
    if not rows:
        print(f"[instruments] no exposure dataset in this envelope ({len(exposures)} returned) - no figure")
        return None

    rows.sort(key=lambda row: row["hits"], reverse=True)
    shown = rows[:max(1, int(cap))]
    drawn = shown[::-1]                                  # most hits at the top of the axis

    height = 0.62 * len(drawn) + 2.45 + 0.16 * 3
    fig, ax = plt.subplots(
        figsize = (FIG_WIDTH_IN, height),
        facecolor = "white",
    )
    ax.barh(
        range(len(drawn)),
        [row["hits"] for row in drawn],
        color  = BLUE,
        height = 0.42,
        zorder = 3,
    )

    widest = max([row["hits"] for row in drawn] + [1])
    for index, row in enumerate(drawn):
        ax.text(
            row["hits"] + widest * 0.02,
            index,
            _instrument_annotation(row),
            fontsize = 7.5,
            color    = INK,
            ha       = "left",
            va       = "center",
        )
    ax.set_xlim(0, widest * 1.75)

    labels = [_instrument_label(row) for row in drawn]
    ax.set_yticks(range(len(drawn)))
    ax.set_yticklabels([text for text, _cut in labels], fontsize=7.5)
    ax.set_ylim(-0.6, len(drawn) - 0.4)
    ax.set_xlabel(
        "genome-wide significant loci per dataset (pre-clumped tophits, p<5e-8)",
        fontsize = 9,
        color    = INK,
    )
    _style(ax)
    ax.grid(
        axis   = "x",
        color  = "#e6e6e6",
        lw     = 0.8,
        zorder = 0,
    )

    matched = finite(data.get("matched_datasets"))
    figure_capped = len(shown) < len(rows)
    if figure_capped:
        # Name THIS figure's denominator: the tool handed over len(rows) and this figure
        # drew fewer, which is its own cut and nothing to do with max_datasets.
        subtitle = f"Showing {len(shown)} of {len(rows)} returned datasets"
        if matched is not None and int(matched) > len(rows):
            subtitle += f", themselves {len(rows)} of {int(matched)} matched"
    elif matched is not None and int(matched) > len(shown):
        subtitle = f"Showing {len(shown)} of {int(matched)} matched datasets"
    else:
        subtitle = f"Showing all {_plural(len(shown), 'matched dataset')}"

    drawn_title, title_cut = _fit_title(
        fig,
        title,
        height,
    )
    if title_cut:
        subtitle += " (title shortened to fit; the full name is in section 1 of the card)"
    _draw_header(
        fig,
        drawn_title,
        subtitle,
        height,
    )

    footer = [INSTRUMENT_FOOTER]
    footer.append(
        "Feasibility only: an instrument count is not an effect estimate and is not evidence "
        "that an effect exists."
    )
    args = (instr_env.get("args") if isinstance(instr_env, dict) else None) or {}
    limit = finite(args.get("max_datasets") if isinstance(args, dict) else None)
    if matched is not None and int(matched) > len(rows):
        footer.append(
            f"{int(matched)} dataset(s) matched, "
            + (f"{len(rows)} returned by the tool" if figure_capped else f"{len(shown)} drawn")
            + (f" (tool cap max_datasets={int(limit)})." if limit is not None else ".")
        )
    if figure_capped:
        footer.append(
            f"{len(rows)} dataset(s) returned by the tool, {len(shown)} drawn: this figure "
            f"caps at {max(1, int(cap))} row(s), its own cut and not the tool's - the rest "
            "are in section 4 of the card."
        )
    if any(str(row["platform"] or "").strip() for row in drawn):
        footer.append(
            "Platform is inferred from the OpenGWAS id batch prefix; it is not a field in this "
            "snapshot."
        )
    blank_platform = sum(1 for row in drawn if not str(row["platform"] or "").strip())
    if blank_platform:
        footer.append(
            f"{blank_platform} drawn dataset(s) carry no platform: gwasinfo has no platform field "
            "and the id batch was not one of the known metabolite panels."
        )
    if any(row["min_f"] is None for row in drawn):
        footer.append(
            "min F n/a: that dataset returned no genome-wide significant hit, so there was no F "
            "to read."
        )
    if dropped:
        footer.append(
            f"{dropped} dataset(s) dropped: no hit count {_NOT_IN_SNAPSHOT} - "
            "not evidence of no instrument."
        )
    shortened = sum(1 for _text, cut in labels if cut)
    if shortened:
        footer.append(
            f"{shortened} axis label(s) shortened to fit; the full trait, id and platform "
            "are in section 4 of the card."
        )
    footer = wrap_footer(footer)
    _draw_footer(
        fig,
        footer,
        height,
    )

    _reserve_bands(
        fig,
        ax,
        len(footer),
        height,
    )
    written = _save(
        fig,
        Path(out_path),
    )
    print(f"[instruments] wrote {Path(written).name}  ({len(shown)}/{len(rows)} datasets, {dropped} dropped)")
    return written


# --------------------------------------------------------------------------------------
# the genetic-insight timeline - when the genetics spoke, and when the clinic decided
# --------------------------------------------------------------------------------------
#
# One horizontal lane per drug that the 1E dossier retrieved for an effector gene, drawn
# against the year the exposure GWAS was published. The sentence it exists to let a reader
# check for themselves is "the genetics were on the record in 2020 and this programme was
# stopped in 2016" - and that sentence is only allowed when BOTH years were retrieved.
#
# WHERE EVERY NUMBER COMES FROM
#   the lanes        envelopes["dossier"][gene]["get_known_drugs"] - Open Targets'
#                    drugAndClinicalCandidates, one lane per drug, each report kept whole
#   the years        tools/trials.py -> ClinicalTrials.gov's own start / primary completion
#                    / completion dates for the NCT id the report carries. Open Targets'
#                    own `year` is null on every clinical report this project has seen, so
#                    a year has to be retrieved rather than read off the payload
#   the GWAS year    envelopes["instruments"] - the OpenGWAS `year` of each exposure
#                    dataset that was actually queried
#
# WHAT IT REFUSES TO DO
#   - No year is ever inferred. A report with no retrieved year is counted ON the figure
#     and is not drawn - and it is counted under the reason it has no year, because "the
#     registry carries no year for it" and "the registry was never asked" are different
#     facts and only one of them is about the registry. A marker placed at a guessed year
#     would be the worst thing this project could put on a slide.
#   - A drug's max clinical stage is never redrawn as a stage "for this disease": the
#     markers are per REPORT, each labelled with that report's own phase, and the footer
#     says so.
#   - TERMINATED and WITHDRAWN are marked differently from a completed report and carry the
#     registry's own stopping reason, truncated and counted - never paraphrased.
#   - Every cap (lanes, trial lookups, the truncation of a stopping reason) is printed.

TIMELINE_SUFFIX = "_genetic_insight.png"

TIMELINE_TITLE = "{metabolite} -> {disease}: effector-gene drugs against the GWAS year"

TIMELINE_FOOTER = (
    "Per-report phases; a drug's stage for one disease is never its stage for another. "
    "Years from ClinicalTrials.gov records."
)

# Lanes, capped at eight - tall enough on an 8-inch canvas to carry a phase label over
# every marker. Which eight is decided by the figure's OWN drawn evidence (the earliest
# report this run could put a retrieved year on), never by the drug's cross-indication
# max_clinical_stage: that number is not scoped to the disease this figure names (T6).
MAX_LANES = 8

# At most this many registry lookups for one figure. 0.25 s apart, cached hits free, so a
# button press answers inside a few seconds; the cut is printed like every other cap.
TRIAL_LOOKUP_CAP = 24

MAX_WHY_CHARS = 40
MAX_DRUG_CHARS = 30
# The phase and the exposure-dataset id are free text from the source, same as why_stopped
# above; no label on this figure is exempt from the "every cut is counted" contract (T5).
MAX_PHASE_CHARS = 40
# A status that sets "stopped" is anchored at a terminal state word (T2) but the rest of
# the string is free text ("Terminated due to futility"), so this budget does bite and its
# cut is counted like every other.
MAX_STATUS_LABEL_CHARS = 12

# The phase label's vertical stagger. Several reports of one drug routinely start in the
# same year, so their labels have to be spread apart - but a lane is one y-unit from the
# next, and an offset that grows without bound puts a lane's later labels onto the
# NEIGHBOURING drug's row (T5). Same-year reports take successive rungs, alternating above
# and below; when the ladder is exhausted the remaining labels are not drawn and are
# counted in the footer, the same way every other cut on this figure is counted.
LANE_OFFSET_BASE = 0.20
LANE_OFFSET_STEP = 0.08
MAX_LANE_OFFSET = 0.36
# How far outside its own phase label a stopped marker's status/reason label sits.
STOP_LABEL_OFFSET = 0.17

# tools/trials.py owns this pattern; it is repeated here (three lines, one regex) so that
# `import plots` still pulls in nothing but matplotlib and the stdlib. A drawing module
# that imported the tools package would drag `requests` into every surface that draws.
_NCT = re.compile(r"NCT\d{8}")

_TERMINAL_STATUSES = ("TERMINATED", "WITHDRAWN", "SUSPENDED")

_LEADING_WORD = re.compile(r"[A-Z]+")


def _is_terminal_status(value) -> bool:
    """Does this status say the study itself stopped.

    ANCHORED at the start of the string, not a substring test and not strict equality
    (T2). Open Targets copies the registry's controlled state into a free-text field, so
    both "TERMINATED" and "Terminated due to futility" are the registry saying the study
    stopped, while "recruiting; an earlier study was terminated" and "COMPLETED - no
    safety signal was terminated early" are a different study's state mentioned in
    passing. A substring test drew the stopped glyph for all four; strict equality drew it
    for one and silently dropped the retrieved stopping reason of the second.
    """
    text = " ".join(str(value or "").split()).upper()
    leading = _LEADING_WORD.match(text)
    return bool(leading) and leading.group(0) in _TERMINAL_STATUSES


def _nct_id(report) -> str:
    """The NCT id of one Open Targets clinical report, or "".

    Read out of the report id and the url only. It is never reconstructed from a
    neighbouring field: a report that is a label or a regulatory record carries no trial id
    and must come out of here empty, so it is counted as undated rather than placed.
    """
    if not isinstance(report, dict):
        return ""
    text = " ".join(str(report.get(key) or "") for key in ("report_id", "url", "nct_id"))
    found = _NCT.findall(text.upper())
    return found[0] if found else ""


def _trial_dates(
    nct_ids: list,
    cap:     int = TRIAL_LOOKUP_CAP,
):
    """The ClinicalTrials.gov envelope for these ids, or None when it could not be called.

    Imported here rather than at module scope on purpose: `tools.trials` pulls in
    `requests`, and a machine that can draw must not need it. None means no year was
    retrieved for anything, which the caller reports as "undated" - never as "no trial".
    """
    if not nct_ids:
        return None
    try:
        from tools.trials import get_trial_dates
    except Exception:                                    # pragma: no cover - import guard
        return None
    try:
        return get_trial_dates(
            list(nct_ids),
            cap,
        )
    except Exception:                                    # pragma: no cover - tools guard
        return None


def _phase_text(value) -> str:
    """The report's own trial phase, as the source recorded it. A null phase is "phase not
    recorded" - a report with no phase is not a phase 0."""
    number = finite(value)
    if number is not None:
        return f"phase {number:g}"
    text = " ".join(str(value or "").split())
    return text or "phase not recorded"


def _drug_lanes(dossier) -> tuple:
    """(lanes, n_genes, n_drugs_without_reports) out of one run's 1E dossier.

    One lane per drug, carrying the gene it came from, the drug's own max clinical stage
    and its clinical reports verbatim. A gene whose `get_known_drugs` errored or came back
    empty contributes no lane - and a lane is never invented to stand for it, because a
    failed retrieval and a gene with no drug are different facts.

    Returned in the dossier's own iteration order, NOT sorted by `max_clinical_stage`: that
    number is the drug's stage across every indication it has ever been trialled for, not
    for the one disease this figure names, so it must never decide which lanes this figure
    shows or where they sit (T6). The caller orders and caps the lanes once it knows which
    of them this run could actually put a retrieved year on.
    """
    lanes, genes, bare = [], 0, 0
    for gene, by_tool in (dossier or {}).items():
        if not isinstance(by_tool, dict):
            continue
        genes += 1
        env = by_tool.get("get_known_drugs")
        data = env.get("data") if isinstance(env, dict) else None
        drugs = (data or {}).get("drugs") if isinstance(data, dict) else None
        for drug in drugs or []:
            if not isinstance(drug, dict):
                continue
            reports = [row for row in (drug.get("clinical_reports") or []) if isinstance(row, dict)]
            if not reports:
                bare += 1
                continue
            lanes.append({
                "gene":    str(gene),
                "drug":    str(drug.get("drug") or "drug not named by the source"),
                "stage":   finite(drug.get("max_clinical_stage")),
                "reports": reports,
            })
    return lanes, genes, bare


UNDATED_REASONS = (
    "no_id",
    "not_queried",
    "lookup_failed",
    "no_record",
    "no_date",
)


def _lane_markers(
    lane:       dict,
    dates:      dict,
    looked_up:  set = None,
    failed_ids: set = None,
) -> tuple:
    """(markers, undated) for one drug lane. `undated` counts the undrawn reports by WHY.

    A marker needs a year that was RETRIEVED: the registry's start year, or its completion
    year when there is no start. Everything else is undated, and the five ways a report
    gets there are five different facts that must never be merged into one sentence (T3).
    Only the last two are anything the registry was actually asked about:

      no_id          the report carries no NCT id, so nothing was ever sent for it.
      not_queried    it carries an id that was not among the ids this figure sent - over
                     `TRIAL_LOOKUP_CAP`, or the lookup could not be made at all.
      lookup_failed  the id was sent and the request failed. No information.
      no_record      the id was sent, the lookup did not fail, and no record came back.
      no_date        a record came back and it carries no year.

    `looked_up` is the set of ids this run actually sent; `failed_ids` the ones whose
    lookup failed. Both default to what the answer itself proves - anything the registry
    answered was obviously asked - so a caller that has neither cannot end up claiming a
    lookup that did not happen.

    `status` and `why` each carry which source actually supplied them - the registry
    record or the dossier's own report - because a fallback from one to the other must
    never be printed as if it came from the registry when it did not (T1). The terminal
    state is ANCHORED at the start of the status string (T2); see `_is_terminal_status`.
    """
    failed_ids = set(failed_ids or ())
    looked_up = set(dates) | failed_ids if looked_up is None else set(looked_up)
    markers = []
    undated = {reason: 0 for reason in UNDATED_REASONS}
    for report in lane["reports"]:
        nct_id = _nct_id(report)
        record = dates.get(nct_id) or {}
        start = finite(record.get("start_year"))
        end = finite(record.get("primary_completion_year"))
        if end is None:
            end = finite(record.get("completion_year"))

        # The registry labels each date ACTUAL or ESTIMATED, and an ESTIMATED completion
        # is the sponsor's projection. Drawn as a solid bar it would be history.
        end_type = str(
            record.get("primary_completion_date_type")
            or record.get("completion_date_type")
            or ""
        ).upper()

        source = "registry"
        # The axis is labelled "start"; a bar with no retrieved start year silently placed
        # at its completion year would be indistinguishable from a real start marker
        # (T7), so the substitution is recorded rather than only performed.
        start_is_completion = False
        if start is None and end is not None:
            start, start_is_completion = end, True
        if start is None and end is None:
            # Open Targets records a `year` of its own on a clinical report. It is null on
            # every report this project has seen, but if it is ever there it is retrieved
            # too - and the figure then says which of its markers did not come from the
            # registry, because the footer promises the registry.
            own = finite(report.get("year"))
            if own is None:
                undated[_undated_reason(
                    nct_id,
                    dates,
                    looked_up,
                    failed_ids,
                )] += 1
                continue
            start, source = own, "open targets"

        registry_status = str(record.get("overall_status") or "").upper()
        report_status = str(report.get("status") or "").upper()
        if registry_status:
            status, status_source = registry_status, "registry"
        elif report_status:
            status, status_source = report_status, "open targets"
        else:
            status, status_source = "", ""

        registry_why = str(record.get("why_stopped") or "").strip()
        report_why = str(report.get("why_stopped") or "").strip()
        if registry_why:
            raw_why, why_source = registry_why, "registry"
        elif report_why:
            raw_why, why_source = report_why, "open targets"
        else:
            raw_why, why_source = "", ""
        why, why_cut = elide(
            raw_why,
            MAX_WHY_CHARS,
        )

        markers.append({
            "x0":                  start,
            "x1":                  end,
            "estimated":           end_type == "ESTIMATED",
            "start_is_completion": start_is_completion,
            "phase":               _phase_text(report.get("trial_phase")),
            "status":              status,
            "status_source":       status_source,
            "stopped":             _is_terminal_status(status),
            "why":                 why,
            "why_cut":             why_cut,
            "why_source":          why_source,
            "source":              source,
        })
    markers.sort(key=lambda marker: marker["x0"])
    return markers, undated


def _undated_reason(
    nct_id:     str,
    dates:      dict,
    looked_up:  set,
    failed_ids: set,
) -> str:
    """Which of `UNDATED_REASONS` this undrawn report belongs under."""
    if not nct_id:
        return "no_id"
    if nct_id not in looked_up:
        return "not_queried"
    if nct_id in failed_ids:
        return "lookup_failed"
    if nct_id in dates:
        return "no_date"
    return "no_record"


def _staggered(markers: list):
    """(rung, marker) for every marker, the rung counted within its own start year.

    Two markers only need separating when they sit at the same x, so the ladder is per
    year rather than per lane: a lane's ninth report no longer has its label pushed a
    whole lane-unit away because eight others happened to precede it at other years (T5).
    """
    rungs = {}
    for marker in markers:
        year = marker["x0"]
        rungs[year] = rungs.get(year, -1) + 1
        yield rungs[year], marker


def _gwas_years(instr_env) -> tuple:
    """([(year, label)], shortened) for every exposure dataset that came back with a year.

    One line per distinct year: several Nightingale datasets share 2020, and four dashed
    lines on top of each other would read as four independent pieces of evidence. Each
    named dataset id is under the same character budget as every other label on this
    figure (T5): an OpenGWAS id is retrieved text like any other, and this module's own
    contract is that no label leaves the canvas without saying it was cut.
    """
    data = instr_env.get("data") if isinstance(instr_env, dict) else None
    exposures = (data or {}).get("exposures") if isinstance(data, dict) else None

    by_year = {}
    for row in exposures or []:
        if not isinstance(row, dict):
            continue
        year = finite(row.get("year"))
        if year is None:
            continue
        by_year.setdefault(int(year), []).append(str(row.get("id") or "id not returned"))

    lines, shortened = [], 0
    for year in sorted(by_year):
        ids = by_year[year]
        shown_ids = []
        for raw_id in ids[:2]:
            text, cut = elide(raw_id, MAX_ID_CHARS)
            shown_ids.append(text)
            shortened += 1 if cut else 0
        named = ", ".join(shown_ids) + (f" +{len(ids) - 2} more" if len(ids) > 2 else "")
        lines.append((year, f"genetic evidence: {named} {year}"))
    return lines, shortened


def plot_genetic_insight(
    result:  dict,
    out_dir: str = "cards",
) -> str | None:
    """Draw the drug timeline of this run's effector genes against the exposure GWAS year.

    One horizontal lane per drug the 1E dossier retrieved, capped at `MAX_LANES` by this
    figure's OWN drawn evidence - lanes with a retrieved year first, earliest first, never
    by the drug's cross-indication `max_clinical_stage` (T6). One marker per clinical
    report at the year the registry records, labelled with that report's own phase, with a
    TERMINATED or WITHDRAWN report marked differently and carrying its stopping reason.
    Dashed vertical lines mark the year each exposure GWAS was published.

    Returns the path written, or None when no drug has a single report this project could
    put a retrieved year on - there is then nothing to draw, and a lane of markers at
    guessed years would be an invention on the one figure whose whole claim is chronology.
    """
    result = result if isinstance(result, dict) else {}
    envelopes = result.get("envelopes")
    envelopes = envelopes if isinstance(envelopes, dict) else {}
    dossier = envelopes.get("dossier")
    dossier = dossier if isinstance(dossier, dict) else {}

    lanes, n_genes, bare = _drug_lanes(dossier)
    if not lanes:
        print(
            f"[timeline] no drug with a clinical report in this run's dossier "
            f"({n_genes} gene(s)) - no figure"
        )
        return None

    # Every lane's ids are looked up BEFORE the eight-lane cap is applied: which lanes get
    # shown is decided by what this figure can actually draw, so the dates have to be known
    # first. TRIAL_LOOKUP_CAP still bounds the total number of registry requests.
    wanted = []
    for lane in lanes:
        for report in lane["reports"]:
            nct_id = _nct_id(report)
            if nct_id and nct_id not in wanted:
                wanted.append(nct_id)

    trial_env = _trial_dates(wanted)
    trial_data = (trial_env or {}).get("data") or {}
    dates = trial_data.get("dates") if isinstance(trial_data.get("dates"), dict) else {}
    failed = trial_data.get("failed") if isinstance(trial_data.get("failed"), dict) else {}

    # Which ids this run actually SENT. `get_trial_dates` requests `wanted[:cap]` and
    # reports how many that was, so the prefix names them; the ids it answered or recorded
    # as failed are added because an answer proves the question. When `_trial_dates`
    # returned None - no tools package, or the call raised - this is empty and no report
    # can be described as queried at all (T3).
    n_looked_up = int(finite(trial_data.get("n_looked_up")) or 0)
    failed_ids = {str(key) for key in failed}
    looked_up = set(wanted[:n_looked_up]) | set(dates) | failed_ids

    undated = {reason: 0 for reason in UNDATED_REASONS}
    for lane in lanes:
        lane["markers"], lane_undated = _lane_markers(
            lane,
            dates,
            looked_up,
            failed_ids,
        )
        for reason, count in lane_undated.items():
            undated[reason] += count
    n_undated = sum(undated.values())

    # Order by the figure's own drawn evidence, not by an unrelated cross-indication
    # number: lanes with a retrieved year sort first, earliest year first; a lane with no
    # drawable marker at all sorts last. Python's sort is stable, so lanes tied on this key
    # keep the dossier's own order (T6).
    ordered = sorted(
        lanes,
        key = lambda lane: (
            0 if lane["markers"] else 1,
            min((marker["x0"] for marker in lane["markers"]), default=0.0),
        ),
    )
    shown = ordered[:MAX_LANES]

    drawable = [lane for lane in shown if lane["markers"]]
    if not drawable:
        print(
            f"[timeline] {len(shown)} drug lane(s), {n_undated} "
            "report(s) with no retrieved year - no figure"
        )
        return None

    rows = drawable[::-1]                    # earliest-evidence lane at the bottom
    years = [marker["x0"] for lane in rows for marker in lane["markers"]]
    years += [marker["x1"] for lane in rows for marker in lane["markers"] if marker["x1"]]
    gwas, gwas_cut = _gwas_years(envelopes.get("instruments"))
    years += [year for year, _label in gwas]

    floor, ceiling = min(years), max(years)
    if ceiling == floor:
        # Every drawn year is the same year. A fractional pseudo-span here ("or 2.0") used
        # to leave an axis a fraction of a year wide, and MaxNLocator(integer=True) cannot
        # find an integer tick to lock onto inside it - the axis then fell back to two
        # decimal places on a year (T9). A full year of padding on each side keeps the
        # locator's integer constraint satisfiable without moving `floor`/`ceiling`
        # themselves, which still name the true earliest and latest drawn year.
        left, right = floor - 1.0, ceiling + 1.0
    else:
        span = ceiling - floor
        left, right = floor - 0.12 * span, ceiling + 0.20 * span

    # Room for the title and subtitle, and a
    # band above the axes for the GWAS-year labels: a label drawn down INTO the axes would
    # cross the very lanes it is there to be compared against.
    height = 0.78 * len(rows) + 3.15 + 0.16 * 3
    fig, ax = plt.subplots(
        figsize   = (FIG_WIDTH_IN, height),
        facecolor = "white",
    )
    ax.set_xlim(left, right)

    for year, _label in gwas:
        ax.axvline(
            year,
            color  = "#999999",
            lw     = 1.1,
            ls     = "--",
            zorder = 1,
        )

    stopped_reason_registry, stopped_reason_report = 0, 0
    stopped_status_registry, stopped_status_report = 0, 0
    projected, start_from_completion = 0, 0
    phase_shortened, status_label_shortened, why_shortened = 0, 0, 0
    phase_not_drawn, why_not_drawn = 0, 0
    for index, lane in enumerate(rows):
        ax.plot(
            ax.get_xlim(),
            [index, index],
            color  = "#e6e6e6",
            lw     = 0.9,
            zorder = 0,
        )
        for order, marker in _staggered(lane["markers"]):
            if marker["x1"] and marker["x1"] > marker["x0"]:
                # Dotted when the completion date is the registry's ESTIMATED type: that
                # is the sponsor's projection, and a solid bar would draw it as history.
                projected += 1 if marker["estimated"] else 0
                ax.plot(
                    [marker["x0"], marker["x1"]],
                    [index, index],
                    color          = BLUE,
                    lw             = 1.6,
                    ls             = ":" if marker["estimated"] else "-",
                    solid_capstyle = "round",
                    zorder         = 2,
                )
            if marker["start_is_completion"]:
                # The axis is labelled "start"; a marker silently sitting on a completion
                # year would be indistinguishable from a real start marker (T7), so it is
                # drawn hollow rather than filled, on top of being counted in the footer.
                start_from_completion += 1
            ax.scatter(
                [marker["x0"]],
                [index],
                s          = 46 if marker["stopped"] else 34,
                marker     = "X" if marker["stopped"] else "o",
                facecolors = "none" if marker["start_is_completion"] else BLUE,
                edgecolors = BLUE,
                linewidths = 1.3,
                zorder     = 3,
            )
            if marker["stopped"]:
                if marker["status_source"] == "registry":
                    stopped_status_registry += 1
                else:
                    stopped_status_report += 1
            # `order` is the marker's rung within its own SAME-YEAR group, and the ladder
            # is bounded: markers at different years never collide horizontally, so they
            # never need to be pushed off their own lane's row, and no label may reach the
            # lane above or below (T5). A rung past the end of the ladder is not drawn and
            # is counted instead.
            magnitude = LANE_OFFSET_BASE + LANE_OFFSET_STEP * (order // 2)
            if magnitude > MAX_LANE_OFFSET:
                phase_not_drawn += 1
                why_not_drawn += 1 if marker["why"] else 0
                continue
            offset = magnitude if order % 2 == 0 else -magnitude
            above = offset > 0
            phase_text, phase_cut = elide(marker["phase"], MAX_PHASE_CHARS)
            phase_shortened += 1 if phase_cut else 0
            ax.text(
                marker["x0"],
                index + offset,
                phase_text,
                fontsize = 6.5,
                color    = INK,
                ha       = "center",
                va       = "bottom" if above else "top",
                zorder   = 4,
                **NO_MATHTEXT,
            )
            if marker["why"] and not marker["stopped"]:
                # A retrieved stopping reason on a report whose status is not one of the
                # registry's stopped states. The label is not drawn - the marker is not a
                # stopped marker - but the reason WAS retrieved, so its absence from the
                # canvas is stated rather than silent.
                why_not_drawn += 1
            if marker["stopped"] and marker["why"]:
                # Stacked directly outside this marker's own phase label, so the reason a
                # trial stopped stays attached to the report it belongs to.
                if marker["why_source"] == "registry":
                    stopped_reason_registry += 1
                else:
                    stopped_reason_report += 1
                why_shortened += 1 if marker["why_cut"] else 0
                status_label, status_cut = elide(marker["status"].lower(), MAX_STATUS_LABEL_CHARS)
                status_label_shortened += 1 if status_cut else 0
                ax.text(
                    marker["x0"],
                    index + offset + (STOP_LABEL_OFFSET if above else -STOP_LABEL_OFFSET),
                    f"{status_label}: {marker['why']}",
                    fontsize = 6.0,
                    color    = GREY,
                    ha       = "center",
                    va       = "bottom" if above else "top",
                    zorder   = 4,
                    **NO_MATHTEXT,
                )

    labels = []
    for lane in rows:
        drug, cut_drug = elide(lane["drug"], MAX_DRUG_CHARS)
        gene, cut_gene = elide(lane["gene"], MAX_ID_CHARS)
        # "any indication" is not an aside: a drug's max_clinical_stage is Open Targets'
        # number across every indication it has ever been trialled for, and this figure
        # names one disease. render.py's card prose carries the same qualifier for the
        # same number (T6) - clinical_reports carries no per-report indication field to
        # derive a disease-scoped stage from instead.
        stage = (
            "max stage not recorded"
            if lane["stage"] is None
            else f"max stage {lane['stage']:g} (any indication)"
        )
        labels.append((f"{drug}\n{gene}, {stage}", bool(cut_drug or cut_gene)))

    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(
        [text for text, _cut in labels],
        fontsize = 7.5,
        **NO_MATHTEXT,
    )
    ax.set_ylim(-0.6, len(rows) - 0.35)
    ax.set_xlabel(
        "year (ClinicalTrials.gov record: start, and the bar to primary completion)",
        fontsize = 9,
        color    = INK,
        **NO_MATHTEXT,
    )
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    _style(ax)

    metabolite = display_name(result.get("metabolite"))
    disease = display_name(result.get("disease"))
    drawn_title, title_cut = _fit_title(
        fig,
        TIMELINE_TITLE.format(
            metabolite = metabolite,
            disease    = disease,
        ),
        height,
    )
    n_markers = sum(len(lane["markers"]) for lane in rows)
    subtitle = (
        f"{len(rows)} drug lane(s) from the dossier of {_plural(n_genes, 'effector gene')}, "
        f"{_plural(n_markers, 'dated report')} drawn, "
        f"{_plural(len(gwas), 'exposure GWAS year')} marked"
    )
    if title_cut:
        subtitle += " (title shortened to fit; the full pair is in section 1 of the card)"
    _draw_header(
        fig,
        drawn_title,
        subtitle,
        height,
    )


    footer = [TIMELINE_FOOTER]
    # One line per WAY a retrieved report failed to get a year, because "the registry has
    # no year for it" and "the registry was never asked" are different facts and only one
    # of them is about the registry (T3). None of them is ever placed on a guessed year.
    if undated["no_id"]:
        footer.append(
            f"{undated['no_id']} retrieved report(s) carry no registry id - not queried, "
            "and never placed on a guessed year."
        )
    if undated["not_queried"]:
        footer.append(
            f"{undated['not_queried']} retrieved report(s) carry a registry id that was "
            f"not requested (this figure sends at most {TRIAL_LOOKUP_CAP} lookups, and "
            "sends none at all when the lookup cannot be made) - not queried, and never "
            "placed on a guessed year."
        )
    if undated["lookup_failed"]:
        footer.append(
            f"{undated['lookup_failed']} retrieved report(s) were queried and the registry "
            "lookup failed - no information, not a trial without dates."
        )
    if undated["no_record"]:
        footer.append(
            f"{undated['no_record']} retrieved report(s) were queried and no registry "
            "record came back for them - no information, not a trial without dates."
        )
    if undated["no_date"]:
        footer.append(
            f"{undated['no_date']} retrieved report(s) were queried and the registry "
            "carries no year for them; NOT drawn - undated, not absent, and never placed "
            "on a guessed year."
        )
    if len(lanes) > len(shown):
        footer.append(
            f"{len(lanes)} drug(s) retrieved, {len(shown)} drawn: this figure caps at "
            f"{MAX_LANES} lane(s), a lane with a drawn dated report first, earliest report "
            "first - the rest are in section 6 of the card."
        )
    if len(drawable) < len(shown):
        footer.append(
            f"{len(shown) - len(drawable)} drawn drug(s) had no report with a retrieved "
            "year and carry no lane here."
        )
    if bare:
        footer.append(
            f"{bare} retrieved drug(s) carry no clinical report at all and have no lane."
        )
    if finite(trial_data.get("n_failed")):
        footer.append(
            f"{int(trial_data['n_failed'])} registry lookup(s) failed; treat those reports "
            "as no information rather than as trials without dates."
        )
    if len(wanted) > int(trial_data.get("n_looked_up") or len(wanted)):
        footer.append(
            f"{len(wanted)} trial id(s) found, {int(trial_data.get('n_looked_up') or 0)} "
            f"looked up (cap {TRIAL_LOOKUP_CAP}); the rest were not requested."
        )
    if any(marker["source"] != "registry" for lane in rows for marker in lane["markers"]):
        footer.append(
            "Some marker(s) use the year Open Targets itself recorded on the report, not a "
            "ClinicalTrials.gov lookup."
        )
    if start_from_completion:
        footer.append(
            f"{start_from_completion} marker(s) are drawn hollow: no start year was "
            "retrieved, so they sit on the registry's completion year instead - not a "
            "start date."
        )
    if projected:
        footer.append(
            f"{projected} bar(s) are dotted: they end on the registry's ESTIMATED "
            "completion date, which is the sponsor's projection and not a milestone that "
            "happened."
        )
    if stopped_status_registry:
        footer.append(
            f"{stopped_status_registry} stopped report(s) identified from the registry's "
            "own status."
        )
    if stopped_status_report:
        footer.append(
            f"{stopped_status_report} stopped report(s) identified from the dossier's own "
            "report status, not a registry lookup."
        )
    if stopped_reason_registry:
        footer.append(
            f"{stopped_reason_registry} stopped report(s) carry the registry's own reason. "
            "A stopping reason is not a statement about efficacy."
        )
    if stopped_reason_report:
        footer.append(
            f"{stopped_reason_report} stopped report(s) carry a reason from the dossier's "
            "own report, not the registry. A stopping reason is not a statement about "
            "efficacy."
        )
    if why_not_drawn:
        # A reason that was retrieved and is not on the canvas. Either its report's status
        # is not one of the registry's stopped states, or the lane ran out of label rungs.
        footer.append(
            f"{why_not_drawn} retrieved stopping reason(s) are not drawn here; the full "
            "retrieved text is in section 6 of the card."
        )
    if why_shortened:
        footer.append(
            f"{why_shortened} stopping reason(s) shortened to {MAX_WHY_CHARS} characters "
            "to fit; the full retrieved text is in section 6 of the card."
        )
    if phase_not_drawn:
        footer.append(
            f"{phase_not_drawn} phase label(s) not drawn: too many reports start in one "
            "year in one lane to label them all without the labels reaching another "
            "drug's row. Those reports are still drawn as markers."
        )
    if phase_shortened:
        footer.append(
            f"{phase_shortened} phase label(s) shortened to fit; the full retrieved phase "
            "text is in section 6 of the card."
        )
    if status_label_shortened:
        footer.append(
            f"{status_label_shortened} status label(s) shortened to fit."
        )
    if gwas_cut:
        footer.append(
            f"{gwas_cut} exposure GWAS dataset id(s) shortened to fit; the full id is in "
            "section 4 of the card."
        )
    shortened = sum(1 for _text, cut in labels if cut)
    if shortened:
        footer.append(
            f"{shortened} lane label(s) shortened to fit; the full drug and gene names are "
            "in section 6 of the card."
        )
    footer = wrap_footer(footer)
    _draw_footer(
        fig,
        footer,
        height,
    )

    _reserve_bands(
        fig,
        ax,
        len(footer),
        height,
    )
    # The shared band leaves room for two header lines; this figure has three and two rows
    # of GWAS-year labels above the axes, so the top is pushed down afterwards. Only `top`
    # moves - whatever _reserve_bands settled on for the y-labels is left alone.
    fig.subplots_adjust(top=1 - 1.12 / height)

    # Drawn last, and in inches from the top of the CANVAS rather than as a fraction of the
    # axes: the axes is 2 inches tall for one lane and 8 for eight, so an axes-fraction
    # offset that clears the label on a short figure walks into the header on a tall one.
    # Two alternating rows, because two GWAS years a few years apart are closer together
    # than their labels are wide.
    blend = blended_transform_factory(ax.transData, fig.transFigure)
    for order, (year, label) in enumerate(gwas):
        where = (year - left) / ((right - left) or 1.0)
        fig.text(
            year,
            1 - (1.09 - 0.12 * (order % 2)) / height,
            label,
            transform = blend,
            fontsize  = 6.5,
            color     = GREY,
            ha        = "left" if where < 0.33 else ("right" if where > 0.67 else "center"),
            va        = "bottom",
            **NO_MATHTEXT,
        )

    folder = Path(out_dir) if out_dir else CARDS_DIR
    if not folder.is_absolute():
        folder = REPO_ROOT / folder
    written = _save(
        fig,
        folder / f"{stem_for_result(result)}{TIMELINE_SUFFIX}",
    )
    print(
        f"[timeline] wrote {Path(written).name}  ({len(rows)}/{len(lanes)} drug lanes, "
        f"{n_undated} undated report(s))"
    )
    return written


# --------------------------------------------------------------------------------------
# the one entry point a surface calls
# --------------------------------------------------------------------------------------

def stem_for_result(result: dict) -> str:
    """The filename stem of a run: the ledger's own stem, so the figure sits in cards/
    beside the ledger that justifies every number on it."""
    name = Path(str((result or {}).get("ledger_path") or "").strip()).name
    if name.endswith(ledger.SUFFIX):
        name = name[: -len(ledger.SUFFIX)]
    if name:
        return name
    return "{metabolite}_{disease}".format(
        metabolite = _slug(display_name((result or {}).get("metabolite"))),
        disease    = _slug(display_name((result or {}).get("disease"))),
    )


def plot_for_result(
    result:  dict,
    out_dir: str = "cards",
) -> str | None:
    """The one figure for one `pipeline.run_pair` result, or None when there is none.

        State A + at least one drawable estimate   -> {stem}_mr_forest.png
        State B + at least one exposure dataset    -> {stem}_instruments.png
        State C, or an empty envelope either way   -> None

    Never raises for a missing key, an empty envelope or an odd state: a surface calls
    this next to `run_pair`, and a figure must not be able to take a Slack reply down.
    A None return is a result, not an error - say "no figure for this state" and post the
    text.
    """
    result = result if isinstance(result, dict) else {}
    state = str(result.get("state") or "").strip().upper()
    envelopes = result.get("envelopes")
    envelopes = envelopes if isinstance(envelopes, dict) else {}

    folder = Path(out_dir) if out_dir else CARDS_DIR
    if not folder.is_absolute():
        folder = REPO_ROOT / folder
    stem = stem_for_result(result)

    metabolite = display_name(result.get("metabolite"))
    disease = display_name(result.get("disease"))

    if state == "A":
        return plot_forest(
            envelopes.get("mr") or {},
            FOREST_TITLE.format(
                metabolite = metabolite,
                disease    = disease,
            ),
            folder / f"{stem}{FOREST_SUFFIX}",
        )

    if state == "B":
        return plot_instruments(
            envelopes.get("instruments") or {},
            INSTRUMENT_TITLE.format(metabolite=metabolite),
            folder / f"{stem}{INSTRUMENT_SUFFIX}",
        )

    print(
        f"[plots] state {state or '(none)'} for {metabolite} -> {disease}: no figure. "
        "Nothing was retrieved to draw, which is a gap in this snapshot and not evidence "
        "of no effect."
    )
    return None


# --------------------------------------------------------------------------------------
# the frozen snapshot - how the figures are exercised without spending a credit
# --------------------------------------------------------------------------------------
#
# data/demo_card_inputs.json holds the real envelopes of the three headline pairs, keyed
# by TOOL NAME. `run_pair` keys the same envelopes by SLOT ("mr", "instruments", ...), so
# the two names are mapped here once, in the module the tests import, rather than copied
# into every caller.

DEMO_SLOTS = {
    "get_mr_result":         "mr",
    "get_mqtl_instruments":  "instruments",
    "find_outcome_datasets": "outcomes",
    "get_gwas_catalog":      "catalog",
}

DEMO_NOTE = (
    "envelopes read from data/demo_card_inputs.json, a cached snapshot of a real run - "
    "not a live query."
)
# The cached snapshot and the frozen cards/<stem>.ledger.jsonl on disk are two DIFFERENT
# runs of the same pair. A demo result that named the frozen file would point section 11
# of the card at a run whose statuses and timestamps contradict the tables above it, so
# it names no ledger at all and section 11 digests these envelopes instead - the honest
# fallback render.py already has. The figure's filename is unaffected: stem_for_result
# rebuilds the same stem from the two names.
DEMO_LEDGER_NOTE = (
    "this replay names no ledger file: the frozen cards/ ledger of this pair belongs to a "
    "different run, so section 11 digests the snapshot's own envelopes instead."
)


def load_demo(demo_path=DEMO_PATH) -> dict:
    """The frozen snapshot's `pairs` block: {"urate|gout": {...}, ...}."""
    with Path(demo_path).open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    return loaded.get("pairs") or {}


def demo_result(
    pair_key:  str,
    demo_path = DEMO_PATH,
) -> dict:
    """Rebuild `run_pair`'s return shape for one frozen pair, so a figure can be drawn
    offline from the same keys a live run produces. Raises KeyError for an unknown pair -
    a typo must not quietly become an empty result."""
    pairs = load_demo(demo_path)
    if pair_key not in pairs:
        raise KeyError(f"{pair_key!r} is not in {Path(demo_path).name}: {sorted(pairs)}")
    pair = pairs[pair_key]

    envelopes = {}
    for tool, slot in DEMO_SLOTS.items():
        envelope = (pair.get("envelopes") or {}).get(tool)
        if envelope:
            envelopes[slot] = envelope

    inputs = pair.get("inputs_from_1a") or {}
    sides = {}
    for side, id_field in (("metabolite", "chebi"), ("disease", "id")):
        block = inputs.get(side) or {}
        name = str(block.get("input") or "").strip()
        sides[side] = {
            "query":         name,
            "input":         name,
            "label":         block.get("label") or name,
            "id":            block.get(id_field) or "",
            "synonyms":      list(block.get("synonyms") or []),
            "resolved":      bool(block),
            "resolved_from": pair_key,
        }

    verdict = pair.get("classify_state") or {}
    return {
        "state":            pair.get("state") or verdict.get("state") or "",
        "reason":           verdict.get("reason") or "",
        "metabolite":       sides["metabolite"],
        "disease":          sides["disease"],
        "envelopes":        envelopes,
        "ledger_path":      "",
        "n_ledger_entries": len(envelopes),
        "notes":            [DEMO_NOTE, DEMO_LEDGER_NOTE],
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description = "Draw the figure for one pair. Offline from the frozen snapshot by default.",
    )
    parser.add_argument(
        "--pair",
        action  = "append",
        default = [],
        help    = 'a demo pair key, e.g. "urate|gout" (repeatable; default: all of them)',
    )
    parser.add_argument("--out-dir", default="cards")
    parser.add_argument(
        "--live",
        action = "store_true",
        help   = "call pipeline.run_pair instead of reading the snapshot (spends credits)",
    )
    parser.add_argument("--metabolite", default="urate", help="--live only")
    parser.add_argument("--disease", default="gout", help="--live only")
    args = parser.parse_args()

    if args.live:
        from pipeline import run_pair                    # imported here: drawing needs no tool

        results = [run_pair(
            args.metabolite,
            args.disease,
        )]
    else:
        keys = args.pair or list(load_demo())
        results = [demo_result(key) for key in keys]

    written = []
    for result in results:
        path = plot_for_result(
            result,
            args.out_dir,
        )
        if path:
            written.append(path)

    print(f"[plots] {len(written)} figure(s) written of {len(results)} pair(s)")
    for path in written:
        print(f"  {path}  ({Path(path).stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
