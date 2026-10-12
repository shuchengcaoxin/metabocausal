# New probe surface: the Genetic Insights timeline lifecycle

Part of the 2026-09-17 re-run of the Section 9 closed-boundary adversarial study. The
2026-09-16 bundle in the parent directory measured the model-written Section 9 at
baseline `bcb32a9` and never probed a figure. This directory probes the timeline surface
that current `main` (`b056397`) carries, in that study's style: deterministic, offline,
one saved output per case, severity and reachability recorded per finding.

## Two surfaces, one name

| | code under test | how it is reached |
|---|---|---|
| `GI**` | `plots.plot_genetic_insight` and its helpers (`_drug_lanes`, `_lane_markers`, `_phase_text`, `_trial_dates`) | Slack's "Genetic insight 时间线 / timeline" button -> `slack_app.draw_figure(kind="timeline")` |
| `LC**` | `demo/genetic-insights/render_bundle.py` and `viewer.template.html`, as changed by PR #14 (`25defeb`, "fix: cover the full evidence lifecycle in timelines") | the build step that writes `recordings/*/index.html`, and the viewer's own "Open snapshot" file input |

**PR #14 did not touch `plots.py`, `render.py`, `slack_app.py` or `tools/`.** Verified:

```bash
git show 25defeb --stat -- plots.py render.py slack_app.py tools/     # no output
```

So the live per-run figure was neither probed by the September 16 study nor covered by
the lifecycle fix. Every `GI**` finding below is about code that has never been measured.

## Reproduce

Python 3.12 and Node from the repository root. No network, no API credential, no model
call.

```bash
PYTHONIOENCODING=utf-8 python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/timeline/probe_timeline.py
node docs/research/section9_adversarial/rerun_2026-09-17/new_probes/timeline/viewer_stage_probe.cjs
```

The first command regenerates `artifacts/` and exits non-zero if an expected observation
changes; it runs 21 `GI` cases and 10 `LC` cases. The second re-runs the shipped viewer's
own `validate()` and stage-grouping source lines against the bundles the first command
wrote.

### How the boundary is held

* **Offline.** `socket.socket`, `socket.create_connection` and `socket.getaddrinfo` are
  replaced with a raising stub before the first case, so a probe that reached
  ClinicalTrials.gov would fail instead of quietly measuring the internet.
* **Frozen registry.** `tools.trials.get_trial_dates` is replaced per case with a stub
  that answers from the case's own record block **and records the ids it was asked for**.
  `plots._trial_dates` itself - its cap argument, its two exception guards - is still the
  code under test. What the registry was actually asked is evidence, not bookkeeping:
  three findings are about the figure crediting the registry for a value it never gave.
* **The figure read as text.** `plots._save` is wrapped so every `matplotlib.text.Text`
  on the canvas is captured, together with each label's pixel box, before the PNG is
  written. Claims are then checked as strings and geometry rather than by eye. Tick
  labels are excluded from the geometry checks, because matplotlib keeps a `Text` for
  ticks outside the view that are never drawn.
* **The viewer run, not re-implemented.** `viewer_stage_probe.cjs` lifts `esc`, `safeURL`,
  `stageNames`, `stageOrder`, `stages`, the `$("timeline").innerHTML=` line and the whole
  `function validate(b){...}` block out of `viewer.template.html` by literal-text
  extraction and evaluates them. Re-implementing them would have measured the probe.
* **Nothing outside this folder is written.** Figures go to `artifacts/figures/`, never
  to `cards/`. Zipeng's `artifacts/` is untouched; `git status` shows only
  `rerun_2026-09-17/`.

## Contents

- `artifacts/findings.json`: every finding, with severity in the parent study's taxonomy
  (defect / scope_limit / observation), the reachability of each claim, the code line it
  is about and the case ids that produced it. Generated from `FINDINGS` in
  `probe_timeline.py`, so a finding and the cases behind it cannot drift apart.
- `probe_timeline.py`, `viewer_stage_probe.cjs`: the harnesses.
- `expected.json`: the frozen observations the harness re-checks.
- `artifacts/RESULTS.md`: generated result table (do not edit by hand).
- `artifacts/results.json`, `artifacts/results.csv`: machine-readable results.
- `artifacts/canvas_text/GI**.txt`: for each figure case, every string drawn on the
  canvas, every label drawn off the canvas with the pixels lost, every pair of labels
  printed over each other, the stdout line, and the exact NCT ids the registry was asked
  for.
- `artifacts/figures/GI**_genetic_insight.png`: the figure each case produced.
- `artifacts/lifecycle/LC**/`: the mutated bundle, and the Markdown and Slack text
  `render_bundle.py` produced from it.
- `artifacts/viewer_stages.txt`, `artifacts/viewer_stages.json`: what the shipped viewer
  renders for each bundle - which stage groups, which events, which events were dropped.
- `artifacts/manifest.json`: revision, environment, probe hash, the sha256 of every
  measured source file, and the sha256 of every figure.
- `artifacts/run.log`: one line per case.

## Interpretation cautions

The parent study's cautions apply unchanged, with two of its own:

* **"drawn" means a PNG was written**, not that the figure is correct. **"RAISED"** means
  `plot_genetic_insight` propagated an exception and Slack would post
  `FIGURE_FAILED_NOTE` instead of an image.
* **The dossier envelope is not a user input.** A `GI` case that sets
  `clinical_reports[].status` or `why_stopped` is modelling what Open Targets returned,
  not something a Slack user types. Reachability is recorded per finding and must be
  preserved when quoting: most `GI` findings are reachable from ordinary retrieved data,
  three (`GI19`, `GI20`, `LC08`) need no adversarial input at all, and none of them is an
  injection into a deployed text box.
* **The figure carries no model prose.** `plots.py`'s module docstring is right that "the
  only text on a figure is a label, an id, a count or a caveat that came out of the
  envelope". The findings here are about what those labels and counts *claim*, not about
  Section 9 leakage.
