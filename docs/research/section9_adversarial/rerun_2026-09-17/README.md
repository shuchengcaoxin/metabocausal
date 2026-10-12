# Section 9 adversarial study — re-run against current `main` (`b056397`)

This directory is the reproducibility bundle for the 2026-09-17 re-run of the September 16
AgenticLS study that sits in the parent directory. That study measured development baseline
`bcb32a9`. This one re-measures the same boundary at `b056397`, the then-current
`origin/main`, and extends it to three surfaces the September 16 harness never reached.
Like the study it re-runs, it measures the implementation; it does not repair it.

- Worktree: `<workspace>/metabocausal-rerun`
- Branch: `rerun/section9-adversarial-20260916`, HEAD
  `b05639721b07345612bba4ebf66f989805b9703c`
- Python: `3.12.10`, platform `Windows-11-10.0.26200-SP0`
- Network: not used. No provider credential used. Nothing was pushed.

## Why this re-run exists

His probes measured `bcb32a9`. Current `main` additionally carries four merged pull
requests: #13 (MVP3 Human-GEM section in cards), #14 (Genetic Insights timeline lifecycle
fix), #15 (docs) and #16 (MVP2 literature data layer). Two questions follow. Whether his
findings drifted, and what the three surfaces those PRs added do when they are probed with
the same discipline. The owner ordered both, plus a re-verification of each of his eight
defect findings.

## Method

The September 16 discipline is carried over unchanged. Every case is offline and
deterministic; every claim is stated as a command plus its real output; the reachability of
each claim is recorded with the claim and is not rounded up. `printed` still means the
renderer emitted Section 9, `blocked` still means it fell back to the fixed pending
sentence, and a hand-built object is still a harness construction rather than a deployed
injection surface.

One rule was added for this re-run. **Every claim was independently refuted before it was
included.** After a probe produced a candidate finding, a second pass rebuilt the
measurement from source rather than from the probe, and tried to make the claim fail. A
claim that survived is reported; a claim that did not is listed in
[RESULTS.md](RESULTS.md) Appendix A as rejected, with the measurement that rejected it.
Thirteen candidate claims were rejected that way, including one of his own eight.

Where a finding was reachable on more than one path, the strongest path that was actually
executed is the one recorded. Several of his rows labelled `model_path_equivalent` are
recorded here as `current_model_path` or `current_cli_surface` because this re-run ran them
through `llm.interpret()` or through `render.py --interpret` end to end, with only the
provider transport call replaced by a fixed offline `Reply` — the same isolation his `R01`
used. No reachability label was raised without such a run.

## Coverage map

| Part | What was measured | Cases | Result |
|---|---|---|---|
| Baseline re-run | `scripts/probe_section9.py` unchanged at `b056397` | 51 | 0 of 51 changed outcome; exit 0 |
| Re-verify | his F1–F8, each re-measured rather than inherited | 8 | 7 still hold; 0 fixed; 1 rejected |
| New surface: Genetic Insights timeline | `plots.plot_genetic_insight` and PR #14's lifecycle bundle/viewer | 21 `GI` + 10 `LC` | 18 findings (11 defects, 2 scope limits, 5 observations) |
| New surface: Human-GEM arm | `tools/gem.py`, card Sections 5/7, and the Section 9 tie-in | 30 | 3 findings (1 defect, 1 scope limit, 1 observation) |
| New surface: MVP2 literature layer | runtime coupling, extraction, dedup, manifests, ledger, tests | 16 | 10 findings (4 defects, 1 scope limit, 5 observations) |

Neither `plots.py` nor the MVP3 and MVP2 trees is on the September 16 harness's measured
file set, so none of the three new surfaces had been probed before. The timeline figure in
particular was neither probed by that study nor touched by PR #14, which changed only the
demo bundle and viewer.

## Reproduce

Python 3.12 from the repository root, plus Node for one viewer check. No network and no API
credential. Set `PYTHONIOENCODING=utf-8` on Windows.

```bash
# 1. the September 16 harness, unchanged
python scripts/probe_section9.py
python -m unittest tests.test_probe_section9 tests.test_section_nine \
  tests.test_validate_card tests.test_interpret

# 2. the three new surfaces
python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/timeline/probe_timeline.py
node   docs/research/section9_adversarial/rerun_2026-09-17/new_probes/timeline/viewer_stage_probe.cjs
python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/gem/probe_gem.py
python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/mvp2/probes/run_all.py
```

Each probe regenerates its own `artifacts/` (or `outputs/`) and exits non-zero if any
expected observation changes. The F1–F8 re-verification scripts under `reverify/` are run
individually and each saves its own output next to itself.

**The first command rewrites three tracked files inside his bundle** (`manifest.json`,
`results.csv`, `run.log`, all environment fields). Copy what you need, then
`git restore docs/research/section9_adversarial` so his bundle stays byte-identical to
`HEAD`. That is what was done here, and it was re-checked after the unittest run.

## Contents

- [RESULTS.md](RESULTS.md): the three result tables and Appendix A, the rejected claims.
- [results.json](results.json): machine-readable mirror of RESULTS.md.
- `baseline/`: the 51-case re-run. `DRIFT.md` is the measurement write-up, `HASHES.tsv`
  records all 69 artifact files at both revisions, `expected_bcb32a9/` is his committed
  output and `observed_b056397/` is this run's.
- `reverify/F1` … `reverify/F8`: one directory per finding, each with the script, its saved
  output, and the rendered cards or Section 9 text it produced.
- `new_probes/timeline/`, `new_probes/gem/`, `new_probes/mvp2/`: the three new-surface
  harnesses, each with its own README, manifest and per-case artifacts.
- `verify_scratch/`: the independent refutation runs, one directory per candidate claim.
  This is the largest part of the bundle because several refutations had to regenerate a
  probe's full artifact tree to compare against it. It is kept because Appendix A cites it.

## Correction to the baseline bundle's repository note

The parent [README.md](../README.md) records, under *Repository baseline note*, that on
2026-09-16 `origin/main` had been force-replaced by an unrelated-root static public demo at
`3359f1d` that no longer contained `render.py`, `validate_card.py` or `llm/`. Re-checked
against the remote this branch is attached to, that is not the state of `main`
today, and the corrected facts should be used when the bundle is quoted:

```
$ git remote -v
origin  <team repository> (fetch)

$ git log -1 --format='%H %ci %s' origin/main
b05639721b07345612bba4ebf66f989805b9703c 2026-09-16 23:55:57 -0400 Merge pull request #17 from shuchengcaoxin/research/section9-adversarial-probes

$ git rev-list --count origin/main
38

$ git rev-list --max-parents=0 origin/main
efd56df1351988e8b5de7fccff99e6f0fd50124e

$ git merge-base --is-ancestor bcb32a9 origin/main && echo "bcb32a9 is an ancestor of origin/main"
bcb32a9 is an ancestor of origin/main

$ git ls-tree -r --name-only origin/main | grep -E '^(render|validate_card|ledger|plots|slack_app)\.py$'
ledger.py
plots.py
render.py
slack_app.py
validate_card.py

$ git cat-file -t 3359f1d
fatal: Not a valid object name 3359f1d
```

Read strictly: the then-current `origin/main` is `b056397`, it has a single root commit and
38 commits of continuous history, his baseline `bcb32a9` is an ancestor of it rather than
an orphan beside it, and every file the study measures is present on it. The commit
`3359f1d` is not an object in this clone at all.

What this does **not** establish: what `origin/main` pointed at on 2026-09-16, whether the
note described this remote or another one, and whether a force-push happened and
was later reverted. None of that is observable from here, so none of it is claimed. The
narrow correction is that a reader of his bundle should not conclude that the code named in
the assignment is missing from `main` — on the remote this branch tracks, it is present,
and `b056397` is the revision every measurement in this directory was taken on.

## Interpretation cautions

The parent bundle's cautions apply unchanged and are not restated here. Four carry-forwards
are specific to this re-run.

- **Reachability is per claim, not per finding.** Several findings hold on more than one
  path at different strengths; RESULTS.md records the strongest executed path and names the
  weaker ones separately. Quoting a finding without its reachability column inflates it.
- **The hand-built `A1` object is still not a deployed injection surface.** Nothing in this
  re-run licenses restating it as one. `R01` and the `render.py --interpret` runs recorded
  under F1 and F4 are the reachable forms.
- **Stubbing the provider is not stubbing a gate.** Where a card was produced end to end,
  only `llm.interpret.complete` was replaced with a fixed offline `Reply`. Argument parsing,
  `interpret()`, both validators and `render_card()` ran unmodified. What remains unmeasured
  is whether a live provider would emit the sentence in the first place; prompt-injection
  susceptibility and stochastic provider behaviour are still out of the measured boundary,
  exactly as his REPORT.md says.
- **The Slack surface was not executed.** It needs Slack tokens and a live provider. Where
  it appears in RESULTS.md it is a code-reading of an unchanged file, labelled as such.
