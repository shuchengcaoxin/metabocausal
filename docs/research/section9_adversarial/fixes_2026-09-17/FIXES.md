# Fixes for the 2026-09-17 re-run's confirmed defects

This directory is the only writable place under `docs/research/section9_adversarial/`.
Everything else there is evidence and stays byte-identical; the probes under
`rerun_2026-09-17/new_probes/` were read and copied out, never edited.

One section per defect. Each records what was broken, what changed, the before/after
evidence, and what is **not** claimed.

## The gates, measured once, at the branch head

Four gate runs, on Windows with python 3.12.10, re-measured for the 2026-09-18 bound-order
ruling on the tree that ruling produced. These are the only gate numbers in this file;
earlier drafts carried tables that disagreed with each other and did not reproduce, and
they are gone. The one number that moved from the 2026-09-17 measurement at `a881f3f` is
gate 1's total, 1013 → 1022, which is the 9 tests `TestM4BoundOrderIsNumeric` adds.

| Gate | Command | Result |
|---|---|---|
| 0 | `python -m compileall -q .` | **exit 0**, no output. |
| 1 | `python -m unittest discover -s tests -t .` | **Ran 1022 tests**, `FAILED (failures=1, skipped=3)`. The one failure is pre-existing and is the only one; see below. |
| 2 | `python scripts/probe_section9.py` | **exit 0, 51 cases, `all_expectations_met: true`** (31 printed, 17 blocked, 2 bypassed, 1 raised). Zero expectation edits - the table below is empty. `results.csv` came back byte-identical again. |
| 3 | `python tests/_mvp2_pytest_shim.py <one MVP2 test file>`, five invocations | **17 collected, 17 passed, exit 0** on all five, `collection_error: null` on all five. |

The four regression modules were also run one at a time: `test_fix_gem_d2` 24 OK,
`test_fix_timeline_t1_t9` 24 OK, `test_fix_viewer_l2_l3_l6` 27 OK,
`test_fix_mvp2_m4_m5_m6_m7` **34 OK**.

**How to read `probe_run/manifest.json`'s own provenance line.** Gate 2 writes its
manifest from the tree it actually ran against, which is the working tree that the
*following* commit then publishes — a probe run after the commit would produce different
artifacts than the ones the commit contains, so it is run before. Its `git_head`
therefore names the **parent** commit and its `git_status` lists the files the commit
being prepared is about to carry.

- The 2026-09-18 **bound-order** run records `git_head: dea16a1…` and 17 modified paths.
  Those 17 are exactly the 17 files of commit `7793a22`.
- The 2026-09-18 **review-correction** run records `git_head: 7793a22…` and three
  modified paths — `MVP2/data/README.md`, `tests/test_fix_mvp2_m4_m5_m6_m7.py`, and this
  file. The two files the probe then writes itself, `probe_run/manifest.json` and
  `probe_run/run.log`, are absent from its own listing because the snapshot is taken
  before they are written; with them the commit that follows `7793a22` is five files.
  (They *do* appear in the earlier run's listing, because that session ran the probe more
  than once and the second run saw the first run's output as already modified.)

The `??` lines in either `git_status` are `__pycache__` directories under `archive/`,
which git does not track and no commit carries. Re-running the probe at a committed head
changes only `generated_at_utc`, `git_head` and `git_status`; `results.csv`,
`results.json` and `RESULTS.md` came back byte-identical each time, which is what makes
the measurement independent of which of the two trees it was taken on.

### Gate 1's single failure is pre-existing, measured rather than asserted

`tests.test_pipeline.TestDossierIsRecordedExactlyOnce.test_the_ledger_holds_the_core_tools_plus_the_four_gene_side_tools`
asserts the ledger holds 8 tools; it holds 9, the extra line being
`get_gnomad_constraint`. Two independent measurements, not one:

- **It reproduces at `caa2d10`.** The base commit was extracted to a scratch directory
  outside this worktree and the single test run there: same assertion, same message,
  `9 != 8 : [… 'get_chembl_modulators', 'get_gnomad_constraint']`. That scratch run had no
  `.env`, no credential and no network, and the live worktree run has all three, so the
  failure is environment-independent as well as pre-existing.
- **No commit on this branch touches anything it exercises.**
  `git log --oneline caa2d10..HEAD -- pipeline.py tools/ ledger.py tests/test_pipeline.py`
  is empty, and so is the corresponding `git diff --stat`.

It was not investigated further - it is outside every defect on this list. Stated plainly:
**gate 1 is not green, it is unchanged.** A full-suite count at `caa2d10` is deliberately
not quoted here: the scratch checkout could not be made credential- and cache-faithful
(several `tests/test_1b`, `test_1c` and `test_integration` cases reach the network), so any
base total measured there would be an artefact of the scratch environment rather than a
baseline.

The four new regression files contribute 24 + 24 + 27 + 34 = 109 tests
(`test_fix_gem_d2.py`, `test_fix_timeline_t1_t9.py`, `test_fix_viewer_l2_l3_l6.py`,
`test_fix_mvp2_m4_m5_m6_m7.py`), each of which passes on its own; `tests/test_plots.py`
runs 84. The 3 skips are pre-existing opt-in live tests
(`METABOCAUSAL_SLOW_TESTS`) in `test_1c_gwascat` and `test_coloc`, unrelated to this round.

### The gate-3 command, stated correctly

`tests/_mvp2_pytest_shim.py` reads `sys.argv[1]` and ignores every later argument, so the
`MVP2/tests/test_*.py` glob an earlier draft of this file recorded silently ran only
`test_merge_pairs.py` and reported 3 tests. The shim is run **once per file**:

```
test_merge_pairs.py       exit=0  collected=3  passed=3
test_pair_screening.py    exit=0  collected=2  passed=2
test_pair_search_batch.py exit=0  collected=2  passed=2
test_search.py            exit=0  collected=8  passed=8
test_seed_extraction.py   exit=0  collected=2  passed=2
                                  TOTAL 17     17
```

This is still the M10 harness substitute, not a claim that the suite passes under pytest.

### Gate 2 no longer overwrites the evidence it is checked against

`scripts/probe_section9.py` used to default its `--output-dir` to
`docs/research/section9_adversarial/artifacts/` and rewrite that directory's
`manifest.json`, `results.csv` and `run.log` on every run, stamping in the running
machine's python, platform, cwd, git HEAD, branch, working-tree status and a fresh hash
table. That directory is the frozen evidence of the 2026-09-16 study, so the only way to
keep it intact was to throw the gate's own output away with `git restore` - which left the
repository with no record that the gate had ever passed after a fix, and left the committed
manifest naming a `validate_card.py` digest that the same commit no longer matched.

The default now writes to `fixes_2026-09-17/probe_run/` instead. `--output-dir` still
points anywhere, including at the frozen directory for a deliberate re-measurement of the
original study. `probe_run/manifest.json`, `probe_run/run.log` and `probe_run/results.csv`
from the head-of-branch run are committed here as the evidence that gate 2 passed; the
per-case card and section-9 dumps that run also writes are not committed, because they
reproduce the frozen evidence's own. The manifest's `git_status` field names the working
tree at the instant of the run, which is the staged content of this commit, and its
`git_head` is this commit's parent - a file inside a commit cannot name that commit.

Those uncommitted dumps left the working tree dirty after every gate-2 run, so
`probe_run/.gitignore` now names them - `RESULTS.md`, `results.json`, `full_cards/`,
`section9_outputs/`, four explicit entries, no wildcard. Running gate 2 is now a clean-tree
operation. Nothing that constitutes evidence is ignored: the manifest, the run log and the
per-case results table are all committed, and `results.csv` from this run came back
**byte-identical** to the committed one, which is the determinism check.

`docs/research/section9_adversarial/` is otherwise byte-identical to `caa2d10`, verified
against the working tree and not only against `HEAD`:

```
$ git diff --stat caa2d10 -- docs/research/section9_adversarial/ \
      ':(exclude)docs/research/section9_adversarial/fixes_2026-09-17/**'
   (no output)
$ git status --porcelain -- docs/research/section9_adversarial/
   (only fixes_2026-09-17/probe_run/ entries)
```

The `rerun_2026-09-17/new_probes/` scripts were **copied out** to a scratch directory and
run there, never in place, precisely so that their `artifacts/` writes could not touch the
evidence bundle.

## Harness expectation changes to `scripts/probe_section9.py`

The gate rule: if a fix legitimately changes a measured outcome of the 51 frozen cases,
the expectation for that case only may be updated, with an in-file one-line justification
naming the fix, and it must be listed here.

| Case | Old expectation | New expectation | Fix | Justification line |
|---|---|---|---|---|
| _(none)_ | | | | |

**GEM-D2 changed no frozen case.** This was expected to be possible and did not happen:
none of the 51 cases carries a Human-GEM envelope, so the new check's gene set is empty on
every one of them and the check returns before looking at any sentence. Measured, not
assumed.

Independently confirmed: `git diff caa2d10 -- scripts/probe_section9.py` changes exactly
one thing, `DEFAULT_OUTPUT`, plus the comment explaining why. No expected outcome, no case
and no rule name in that file was edited.

---

## Closure matrix — the 16 defects

One row per defect. "Probe-after" is the measured outcome at the branch head of the
re-run's own probe, or of the adapted regression test where the probe has no per-defect
row. Every number in this table was re-measured for this document; none is inherited.

| # | ID | Fix commit | Regression test | Probe-before | Probe-after |
|---|---|---|---|---|---|
| 1 | M4 | `ba12088`, `c5e7387` | `tests/test_fix_mvp2_m4_m5_m6_m7.py` (`TestM4…`) | 18 rows of `new_pair_records.csv` carry `ci_high == exp(beta)` (the odds ratio); 8 of them carry `p_value > 1` | all 18 carry `0 <= p_value <= 1`, empty `ci_low`/`ci_high`, the real interval in `ci_low_beta_scale`/`ci_high_beta_scale`, and an `extraction_note`; 14 such rows in `new_unique_pairs.csv` |
| 1b | M4 — bound order | this commit | same file (`TestM4BoundOrderIsNumeric`, 9) | 14,509 of the 17,405 rows in `new_pair_records.csv` and 7,912 of the 10,804 in `new_unique_pairs.csv` carry `ci_low > ci_high`, read as printed under a header whose names are swapped | **0** rows with `ci_low > ci_high` in any shipped table; the 16,944 reordered candidate rows carry the printed pair in `ci_low_as_printed`/`ci_high_as_printed` and an `extraction_note`; rows already ascending byte-identical. Owner ruling 2026-09-18 |
| 2 | M5 | `ba12088`, `c5e7387` | same file (`TestM5…`) | `%` absent from every pair key (0 of 12,303 ledger keys); `new_pair_key_count` 9,801 | 5,931 of 12,303 ledger keys carry `%`; 3,310 keys are new identities and **all 3,310 contain `%`**; `new_pair_key_count` **10,804** (+1,003) |
| 3 | M6 | `ba12088`, `c5e7387` | same file (`TestM6…`) | `supporting_source_rows` absent; the merged table wrote the literal `"1"` on every appended row | `{1: 5,085, 2: 5,278, 4: 441}` over 10,804 appended rows, summing to **17,405 = `new_pair_record_count`** |
| 4 | M7 | `ba12088`, `c5e7387` | same file (`TestM7…`) | **0 of 7** hashed manifest entries verify on a clean LF checkout: 6 name unreachable macOS absolute paths, 1 claims `5e7411e6…` where the committed blob is `f3c7ff09…` | **7 of 7 verify**, every path repo-relative POSIX, every digest carrying the `bytes` rule that produced it |
| 5 | GEM-D2 | `c4df609`, `c5e7387` | `tests/test_fix_gem_d2.py` (24) | `probe_gem.py` `GV03` = **printed** (30 cases, 0 expectation failures) | `GV03` = **blocked**. The probe reports it as an expectation failure, which is the closure: the frozen expectation describes the broken behaviour |
| 6 | T1 | `9464321`, `c5e7387` | `tests/test_fix_timeline_t1_t9.py` (`TestT1…`) | `GI03`/`GI04` footer credits "the registry's own reason" with the registry field empty | `GI03` prints "identified from the registry's own status" **and** a separate "carry a reason from the dossier's own report, not the registry" line; `GI04` attributes both fields to the dossier report |
| 7 | T2 | `9464321`, `c5e7387` | same file (`TestT2…`) | `GI15` draws both reports stopped from a substring hit | `GI15` draws neither stopped, and counts the two retrieved reasons it did not draw; `"Terminated due to futility"` is still caught |
| 8 | T3 | `9464321`, `c5e7387` | same file (`TestT3…`) | `GI02`/`GI18` say "carry no year in the registry" about reports never queried | five-way split; `GI18` with `_trial_dates` unavailable prints `"were queried"` nowhere on the figure |
| 9 | T5 | `9464321`, `c5e7387` | same file (`TestT5…`) | `GI17.overflowing` = one 102-char GWAS id off-canvas; `GI20.collisions` = `[['Phase 2/Phase 3', 'Phase 2b dose finding']]` | `GI17.overflowing` = `[]`; `GI20.collisions` = `[]`. **But see the regression recorded below: `GI01.collisions` went `[]` -> one pair.** |
| 10 | T6 | `9464321`, `c5e7387` | same file (`TestT6…`) | lane label `"max stage 3"`; registry asked for 8 ids, the pair-relevant drug's not among them | label `"max stage 3 (any indication)"`; `GI14.registry_asked` gains `NCT00134264`, and lanes order by drawn evidence |
| 11 | T7 | `9464321`, `c5e7387` | same file (`TestT7…`) | `GI12` draws a completion-year marker solid, like a start-year marker | drawn hollow and counted in a footer line |
| 12 | T8 | `9464321`, `c5e7387` | same file (`TestT8…`) | `GI21.exception` = `ParseFatalException`, `GI21.figure` = `none`; `GI07` renders `$…$` as TeX | `GI21.exception` = `''`, `GI21.figure` = **`drawn`**; no drawn artist has `parse_math` on, inside `rc_context({"text.parse_math": True})` |
| 13 | T9 | `9464321`, `c5e7387` | same file (`TestT9…`) | `GI19` x ticks `2003.76 … 2004.40` | ticks `2003 2004 2005` |
| 14 | L2 | `79332a9`, `c5e7387` | `tests/test_fix_viewer_l2_l3_l6.py` (27) | `LC03` renders 10 of 11 events, the 11th silently dropped | 11 of 11, `events_dropped` `[]`, in a grey "Unrecognized stage" group spliced at its own chronological position, marked in all three renderings |
| 15 | L3 | `79332a9`, `c5e7387` | same file | `LC04.validate_error` = `''` (two swapped labels accepted); `LC05.validate_error` = `''` | `LC04` rejected, naming the event, its stage and the vocabulary it fails; `LC05` rejected ("a standard that requires nothing checks nothing") |
| 16 | L6 | `79332a9`, `c5e7387` | same file | `LC09` (true order) **rejected**, `LC10` (reversed) **accepted** | `LC09` accepted, `LC10` rejected |

### How the probe-before column was measured

Not inherited from `RESULTS.md`. Three independent measurements, all at `caa2d10`:

1. **The bundle's own probes, run against `caa2d10` code from an out-of-tree copy.**
   `probe_gem.py` and `probe_timeline.py` were copied out of
   `rerun_2026-09-17/new_probes/` (never edited in place) into a scratch checkout at the
   same relative depth, so their `artifacts/` land outside this repository.
   - `probe_timeline.py` at `caa2d10`: **exit 0, "21 GI + 10 LC cases, all as expected".**
     Its `expected.json` therefore describes the unfixed behaviour exactly, which is what
     makes the after-run's changed rows evidence rather than noise.
   - `probe_gem.py` at `caa2d10`: **exit 0, 30 cases, 0 expectation failures.**
2. **Each regression file run against the pre-fix source**, swapped into the scratch
   checkout one surface at a time:

   | Regression file | Against `caa2d10` source | Against the branch head |
   |---|---|---|
   | `test_fix_gem_d2.py` (`validate_card.py`) | `FAILED (failures=13, errors=6)` - 19 of 24 | `OK` |
   | `test_fix_timeline_t1_t9.py` (`plots.py`) | `FAILED (failures=21, errors=2)` - **23 of 24**; the one that passes is the per-year-rung soundness check, labelled as such | `OK` |
   | `test_fix_viewer_l2_l3_l6.py` (`render_bundle.py`, `viewer.template.html`) | `FAILED (failures=8, errors=13)` - **21 of 27**; the 6 that pass are the must-not-regress guards (both shipped v2 recordings, the `LC01` baseline, L1's positive verification) | `OK` |
   | `test_fix_mvp2_m4_m5_m6_m7.py` | does not import - `ImportError: cannot import name 'hash_mode' from 'src.pair_screening'` | `OK` |

   The MVP2 file cannot be run against `caa2d10` at all, because the fix adds API the old
   module does not have. That is an honest limit of that file as a before/after
   instrument, and it is why rows 1-4 of the matrix above are measured **at the data
   level** instead - directly against the `caa2d10` tables and the head tables, by a
   throwaway script, with no code from either side in the loop.
3. **`git diff --stat caa2d10 -- <files>`** to confirm which source each measurement moved.

---

## GEM-D2 — the validator's effector-gene-nomination membership accepted Human-GEM context

Source: `docs/research/section9_adversarial/rerun_2026-09-17/RESULTS.md`, section (c.2),
case `GV03` in `rerun_2026-09-17/new_probes/gem/probe_gem.py`.

### What was broken

`validate_card.V5` checks a gene symbol by set membership against every string the run
carries. A Human-GEM lookup retrieves the genes that sit on a metabolite's reactions, and
those symbols are strings in the run, so on a run whose atlas nomination layer was never
queried this headline passed both gates and printed:

> GCSH and GLDC are the effector genes this run nominates for the metabolite.

Section 5 of the same card said "The atlas nomination layer was not queried in this run;
the effector mechanism was not assessed." and listed GCSH/GLDC under "Human-GEM
biochemical candidates (reaction membership, not genetic effectors)". The accepted
sentence contradicted the deterministic section above it.

Being in the run and being nominated by the run are not the same fact, and V5 could not
tell them apart.

### What changed

`validate_card.py` only. One rule, **V7**, and the index it needs. Nothing was loosened;
V1 and V5 are untouched and still run first.

- `BIOCHEMICAL_CONTEXT_TOOLS` — the tools whose genes are reaction membership rather than
  a nomination. Today: `map_metabolite_to_genes_gem`.
- `_context_scopes(run, [])` — finds those envelopes by the eight-key envelope shape plus
  the tool name, wherever they sit in the run. Structural for the same reason
  `_envelope_statuses` is structural: a restriction keyed to a fixed path would silently
  stop applying the day the layout moved.
- `context_only_genes(run)` — the gene tokens (symbols and Ensembl gene ids, read with the
  same two shapes V5 uses) that occur inside those envelopes **and nowhere else in the
  run**. A symbol the atlas nominated, the dossier carried or the Catalog mapped is
  retrieved outside the Human-GEM envelope, so it is not in this set and V7 has no opinion
  on it. A run with no Human-GEM envelope produces an empty set and the walk is skipped.
- `SourceIndex.context_only_genes` / `SourceIndex.is_context_only_gene()`.
- `_check_context_genes(field, text, index)` — V7 itself, sentence by sentence, three
  outcomes in this order:
  - the sentence **disclaims** the nomination itself (`NOMINATION_DISCLAIMER`) -> accepted,
    whether or not it also repeats a biochemistry word;
  - the sentence carries a nomination token (`NOMINATION_CLAIM`) and does not disclaim it
    -> **rejected**, "reaction-context gene presented as a nomination";
  - neither -> the sentence has to say it is talking about reaction context
    (`BIOCHEMICAL_CONTEXT`), or it is **rejected**, "quoted without its context".

#### The exemption is a disclaiming construction, not a generic negation

The first version of V7 cleared the nomination flag whenever `NEGATION` matched anywhere
in the sentence. `NEGATION` matches a bare `not`, `no` or `rather than`, so one added
clause disabled the whole branch and the sentence then satisfied the reaction-context
branch on the word "reaction":

> GCSH and GLDC are the effector genes this run nominates for the metabolite, not merely a
> reaction listing.

That is the F4 mechanism `RESULTS.md` records as "still holds", reimplemented inside the
rule written to close GEM-D2 — and the sentence is worse than the original, because it
explicitly denies the reading the validator accepted it under. `validate_card.py`'s own
comment above `V4_DISCLAIMER` says so in as many words for V4.

V7 now follows the V4 precedent. `NOMINATION_DISCLAIMER` requires the negation to govern
the nomination ("is not an effector-gene nomination", "does not nominate", "nominated no
effector gene") or to name the layer that was not queried ("the atlas nomination layer was
not queried"). `NEGATION` is not consulted by V7 at all.

#### The nomination side fails closed

`NOMINATION_CLAIM` was a verb blacklist, so a claim written without this project's
vocabulary passed outright with no negation needed:

> The Human-GEM reaction context points to GCSH and GLDC as the genes to take forward for
> this metabolite.

It now also matches the forward-looking constructions that say the same thing — *take
forward*, *carry forward*, *to watch*, *worth pursuing*, *lead/top/best candidate*, *most
promising*, *actionable*, *next step*, *shortlist*, *recommend*, *select for*, *flag for*
— so an unlisted phrasing that reads as a nomination is rejected rather than admitted.

#### Stating the absence is never the thing that gets a paragraph killed

Because the disclaimer clears the context requirement as well, the sentences whose whole
job is to say that nothing was nominated print even when they carry no biochemistry word.
The earlier version rejected them: the identical `no` that excused the dishonest sentence
left the honest one exposed to the second branch. Both of these are now must-print cases
in `tests/test_fix_gem_d2.py`:

> The atlas nomination layer was not queried in this run, so GCSH and GLDC were not
> nominated as effector genes.
>
> The atlas nomination layer was not queried in this run; nothing here nominates GCSH or
> GLDC.

### What V7 is, stated accurately

V7 is **mixed**, and the module docstring and `HANDOFF_1F.md` say so. Its first half is
rigorous — which symbols the run holds only as reaction context is set membership computed
from the run. Its second half is a phrase heuristic in the V2/V3/V4/V6 sense. A determined
paraphrase can still get past the second half; what changed is that the two named
mechanisms above are no longer paraphrases, they were one clause and one synonym. V7 is a
guardrail, not a proof.

`llm.interpret.build_digest` shows the model only the Human-GEM envelope's tool, source,
status, caveats and row count — never the candidate symbols. So on the deployed path a
model is not shown the symbols V7 restricts; V7 closes the gate against prose that names
them anyway, which is exactly what case GV03 constructed.

### Closure — the demonstrations

| # | Run | Prose | Before | After |
|---|---|---|---|---|
| 1 | gem candidates, **no** atlas nominations (the GV03 shape) | "GCSH and GLDC are the effector genes this run nominates for the metabolite." | printed | **blocked** (V7, one finding per symbol) |
| 1b | same | the same sentence + ", not merely a reaction listing." | printed (the negation exemption) | **blocked** |
| 1c | same | "The Human-GEM reaction context points to GCSH and GLDC as the genes to take forward for this metabolite." | printed (unlisted verb) | **blocked** |
| 2 | **with** atlas nominations `GLDC, CPS1, AGXT` (state B) | "GLDC is an effector gene this run nominates for the metabolite." | printed | **printed** |
| 3 | gem candidates, no atlas nominations | "GCSH and GLDC appear in the Human-GEM reaction context retrieved for this metabolite; reaction membership is not an effector-gene nomination." | printed | **printed** |
| 4 | gem candidates, no atlas nominations | "The atlas nomination layer was not queried in this run, so GCSH and GLDC were not nominated as effector genes." | **blocked** (V7, no biochemistry word) | **printed** |

On run 2, row 1's sentence is still blocked: `GLDC` left the context-only set the moment
the atlas nominated it, `GCSH` did not, and V7 reports `GCSH` alone. The binding is per
gene, not per run.

### Regression test

`tests/test_fix_gem_d2.py`, 24 tests. Offline, no credential, no network. It holds the
demonstrations end to end through both gates and the renderer, the index-level facts they
rest on, and the guards that V7 did not replace V5 (an invented symbol is still V5) or
touch runs without the arm. It also asserts that section 5 still says "The atlas
nomination layer was not queried in this run" while section 9 holds the pending sentence.

### What is not claimed

- V7 is not a proof and its wording half can be paraphrased past.
- The context-only set is built from gene *shapes* found anywhere inside the Human-GEM
  envelope, not from a named field in it. That is deliberate — it survives a layout change
  — and it means the set also holds acronyms the envelope carries that are not genes.
- Nothing here repairs the other Human-GEM findings the re-run recorded: GEM-O6, GEM-O3,
  GV02, GV04 and GV05 are untouched. **GV06 is not**, and an earlier draft of this file
  said it was; the correction is below.

### GV06 also flipped, and it was not predicted

Re-running `probe_gem.py` against the branch head returns **two** expectation failures,
not one:

```
FAIL GV03  blocked   biochemical-context genes restated as nominated effector genes
FAIL GV06  blocked   a gene symbol that only exists in unrendered annotation depth, accepted by V5
```

At `caa2d10` both are `printed` and the probe exits 0.

This follows from what `context_only_genes` is, and the earlier draft's claim that GV06
was untouched was simply not measured. The set is built from gene-shaped tokens found
**anywhere inside** the Human-GEM envelope, including annotation depth the renderer never
prints - that breadth is written down two bullets above as a deliberate choice. A symbol
that exists only in annotation depth is therefore context-only by construction, and V7
binds it exactly as it binds a candidate symbol. GV06's mechanism (V5 accepts a symbol the
card never showed) is **not** repaired in general: it is F3 claim 2, it is about V5, and
V7 does not touch V5. What changed is that on a run carrying a Human-GEM envelope, V7 now
also has an opinion about that symbol's sentence. Outside the Human-GEM arm GV06's
mechanism is unchanged.

Recorded as a widened blast radius, not as a second fix.

---

## T1, T2, T3, T5, T6, T7, T8, T9 — the Genetic Insights timeline figure (`plots.py`)

Source: `RESULTS.md` section (c.1), cases `GI02 GI03 GI04 GI07 GI08 GI12 GI13 GI14 GI15
GI17 GI18 GI19 GI20 GI21` in `rerun_2026-09-17/new_probes/timeline/probe_timeline.py`.
T4, T10, T11, T12, T13 and A1 are scope_limit/observation findings, not defects, and were
left alone.

### What was broken, what changed, per defect

| ID | Broken | Fixed |
|---|---|---|
| T1 | `plots.py` fell back from the registry record to the dossier's own Open Targets report for `overall_status`/`why_stopped`, then the footer said "carry the registry's own reason" for every stopped marker regardless of which source supplied the field. | `_lane_markers` tags `status_source` and `why_source` (`"registry"` / `"open targets"`) per marker; the footer prints separate, correctly attributed lines. |
| T2 | `any(word in status for word in _TERMINAL_STATUSES)` — a substring test on a retrieval-controlled free-text status, so "recruiting; an earlier study was terminated" drew the stopped glyph. | `_is_terminal_status` normalises the status and matches the registry's controlled states **anchored at the start** of the string. See below: strict equality was the first attempt and was wrong in the other direction. |
| T3 | The undated footer collapsed "no NCT id at all, never queried" and "queried and the registry answered with no date" into one line. | `_lane_markers` returns a five-way count and the footer prints one line per reason. See below. |
| T5 | `trial_phase`, the stop-label's status word and the GWAS dataset id carried no character budget. The marker stagger cycled four fixed offsets, so a lane's 5th report landed its phase label exactly on the 1st's. | `MAX_PHASE_CHARS` / `MAX_STATUS_LABEL_CHARS` budgets added, elided and counted; the GWAS id is elided per-id in `_gwas_years`; the stagger is a bounded per-year ladder. See below. |
| T6 | The lane label printed the drug's cross-indication `max_clinical_stage` as if it were this figure's disease, and that same number ordered and capped the eight lanes shown. | `_drug_lanes` no longer sorts by stage; dates are looked up for every lane BEFORE capping, and lanes are ordered by the figure's own drawn evidence (a lane with a marker first, earliest marker year first). The label reads `"max stage N (any indication)"`. |
| T7 | A report with no retrieved start year, only a completion year, was silently drawn at `x0 = end`. | `start_is_completion` is tagged per marker, drawn hollow, and counted in a footer line. |
| T8 | matplotlib's default parsed a balanced `$...$` pair in a retrieved string as TeX, and an unbalanced pair raised at `savefig` time, denying the whole figure. | Parsing disabled — see below. |
| T9 | `span = (ceiling - floor) or 2.0` left a sub-unit axis window when every drawn year was the same year, and `MaxNLocator(integer=True)` fell back to decimal ticks. | When `ceiling == floor` the window is `floor - 1.0` to `ceiling + 1.0`. |

### T3 — "were queried" now means the registry was asked

Splitting the undated reports on whether a report carries an NCT id was not enough: having
an id is not the same as having been asked about. Three ordinary paths put an
id-carrying report into the "the registry carries no year for them" line without a lookup
ever happening — `tools/trials.get_trial_dates` requests only `wanted[:cap]`, a failed
lookup writes to `data["failed"]` and never to `data["dates"]`, and `plots._trial_dates`
returns `None` on its import/tools guard, leaving `dates` empty with nothing asked at all.
The T6 fix made the first of those strictly more reachable, because the id-collection loop
moved from the eight shown lanes to every lane.

`plot_genetic_insight` now derives the set of ids that were actually sent —
`wanted[:n_looked_up]`, plus every id the registry answered or recorded as failed, because
an answer proves the question — and hands it and the failed set to `_lane_markers`, which
counts an undrawn report under one of five reasons:

| Reason | Footer line |
|---|---|
| `no_id` | "…carry no registry id - not queried, and never placed on a guessed year." |
| `not_queried` | "…carry a registry id that was not requested (this figure sends at most 24 lookups, and sends none at all when the lookup cannot be made) - not queried…" |
| `lookup_failed` | "…were queried and the registry lookup failed - no information, not a trial without dates." |
| `no_record` | "…were queried and no registry record came back for them - no information, not a trial without dates." |
| `no_date` | "…were queried and the registry carries no year for them; NOT drawn - undated, not absent…" |

`RESULTS.md` lists T3 under GI02 **and GI18**. Both are closed:

| Case | Before | After |
|---|---|---|
| GI02 | `"3 retrieved report(s) carry no year in the registry"` though the registry was asked for 1 id | `"3 retrieved report(s) carry no registry id - not queried…"` |
| GI18 | that same "no year in the registry" sentence, beside `"2 registry lookup(s) failed"` | `"1 retrieved report(s) were queried and no registry record came back for them - no information…"`; with `_trial_dates` returning `None`, `"1 retrieved report(s) carry a registry id that was not requested…"` and the string `"were queried"` appears nowhere on the figure |

### T2 — anchored, not equal, and no retrieved reason leaves the figure unstated

Replacing the substring test with `status in _TERMINAL_STATUSES` swapped an over-inclusive
test for an under-inclusive one. Those status strings are free text from Open Targets, so
a genuinely terminated report reading "Terminated due to futility" — or "terminated " with
a trailing space — was drawn as an ordinary completed marker, its `why_stopped` was still
computed onto the marker and then never drawn (the label is gated on
`marker["stopped"] and marker["why"]`) and never counted. A retrieved field vanished with
nothing stating its absence.

`_is_terminal_status` now collapses whitespace, upper-cases, and matches the leading word
against `("TERMINATED", "WITHDRAWN", "SUSPENDED")`. "recruiting; an earlier study was
terminated" and "COMPLETED - no safety signal was terminated early" stay negative;
"Terminated due to futility" and "WITHDRAWN_PRE_ENROLLMENT" stay positive. `MAX_STATUS_LABEL_CHARS`
therefore genuinely bites now, and its cut is counted like every other.

Separately, every retrieved `why_stopped` that is not drawn — because its report's status
is not a stopped state, or because the lane ran out of label rungs — is counted into a new
footer line: *"N retrieved stopping reason(s) are not drawn here; the full retrieved text
is in section 6 of the card."* And the two stopped-reason lines no longer announce "cut to
40 characters" for reasons that were never cut: `_lane_markers` keeps `elide`'s cut flag,
the drawing loop counts it, and a separate line prints only when at least one reason was
actually shortened.

### T5 — the stagger is bounded, and what it cannot draw is counted

`magnitude = 0.20 * (order // 2 + 1)` was unbounded: it reaches ±0.60 at order 4, ±0.80 at
6 and exactly ±1.00 at 8 — the centre line of the adjacent lane. `order` was
`enumerate()` over the whole lane, not over a same-year group, so it fired on any lane
with nine or more reports regardless of their years, and `tools/trials.py`'s own docstring
records 19 clinical reports on a single drug in real Open Targets data. The result would
be one drug's phase label on another drug's row. The old four-offset cycle could not
produce that, so it is a regression of the fix and not a pre-existing limit.

`_staggered(markers)` now counts the rung **within the marker's own start year** — markers
at different years do not collide horizontally, so they are never pushed off their own row
at all — and the ladder is bounded: `LANE_OFFSET_BASE 0.20 + LANE_OFFSET_STEP 0.08 * (rung
// 2)`, capped at `MAX_LANE_OFFSET 0.36`, six rungs per year. Past the ladder the phase
label is not drawn and is counted, the same way every other cut on this figure is counted:
*"N phase label(s) not drawn: too many reports start in one year in one lane to label them
all without the labels reaching another drug's row. Those reports are still drawn as
markers."*

### T8 — the guarantee travels with the drawing call, not with process state

`matplotlib.rcParams["text.parse_math"] = False` at import is the default and stays. But
it is **process-global**, not module-scoped as the comment claimed: importing `plots`
changes text rendering for every other matplotlib user in the same interpreter, and any
later `plt.rcdefaults()`, `plt.style.use(...)` or `rc_context` puts parsing back with no
test noticing, because the committed test asserted the rcParam's value at import time
rather than a drawn artist's.

`NO_MATHTEXT = {"parse_math": False}` is now passed explicitly on every text call this
module makes with a retrieved string in it — the two `ax.text` calls, `set_yticklabels`,
`set_xlabel`, the GWAS-year `fig.text`, and the shared `_fit_title` / `_draw_header` /
`_draw_footer` helpers. The comment says the rcParam is process-wide. The test draws the
figure inside `rc_context({"text.parse_math": True})` and asserts
`get_parse_math() is False` on every drawn `Text` that contains a `$`.

### Closure — before/after

| Case | Before (RESULTS.md / the unfixed code path) | After (this branch, captured canvas/footer text) |
|---|---|---|
| GI03 | footer: `"1 stopped report(s) carry the registry's own reason..."` though the registry's `why_stopped` was empty | `"1 stopped report(s) identified from the registry's own status."` + `"...carry a reason from the dossier's own report, not the registry..."` |
| GI04 | same unconditional "registry's own reason" line though BOTH fields came from the dossier report | `"1 stopped report(s) identified from the dossier's own report status, not a registry lookup."` |
| GI15 | both reports drawn stopped (`"terminated: ..."` labels), footer: `"2 stopped report(s) carry the registry's own reason"` | no `"terminated:"` drawn, no stopped-report line, both markers ordinary `"o"` points, and `"2 retrieved stopping reason(s) are not drawn here..."` |
| GI15 (free-text terminal) | `"Terminated due to futility"` drawn as a completed marker, its reason computed and silently dropped | drawn stopped, `"1 stopped report(s) identified from the dossier's own report status"`, the reason on the canvas |
| GI02 | `"3 retrieved report(s) carry no year in the registry"` | `"3 retrieved report(s) carry no registry id - not queried..."` |
| GI18 | the same sentence beside `"2 registry lookup(s) failed"` | the four-way split above; nothing is called queried that was not |
| GI08 | a 76-character phase drawn in full, no shortened count | `"Phase 4 - approved by the FDA for eve..."` + `"1 phase label(s) shortened to fit..."` |
| GI17 | a 102-character GWAS dataset id drawn in full, 7.0 px off the canvas edge | elided + `"1 exposure GWAS dataset id(s) shortened to fit..."` |
| GI20 | the 5th report's label printed exactly on top of the 1st's | 5 distinct offsets, zero collisions (bounding-box overlap on every non-tick `Text`) |
| 10 same-year reports in one lane | ±1.00 and beyond: a label on the next drug's row | 6 drawn, 4 counted, zero collisions |
| GI13 | lane label `"max stage 4"` on a single-disease figure | `"max stage 4 (any indication)"` |
| GI14 | the pair-relevant drug dropped by the 8-lane cap in favour of 8 higher-stage fillers | `torcetrapib` kept; footer names the evidence ordering |
| GI12 | two solid markers at 2016, one a completion-year fallback, no note | `"1 marker(s) are drawn hollow..."` |
| GI07 | `cost-$5-per-$1 gain` and `$overrun_{total}$` parsed as mathtext | literal characters drawn; no drawn artist has `parse_math` on |
| GI21 | `ParseFatalException` at savefig, no PNG | drawn, `"$1{2 per site$"` literal |
| GI19 | x-axis ticks `2003.76 ... 2004.40` | ticks `2003 2004 2005` |

### Regression test

`tests/test_fix_timeline_t1_t9.py`, 24 tests, one class per defect, built on
`tests/test_plots.py`'s existing `TimelineCase` / `FigureCase` fixture builders. Offline:
`plots._trial_dates` stubbed per test, `plots._save` wrapped to capture drawn text, tick
labels and bounding boxes.

Two of the tests in the first version of this file passed unchanged against
`caa2d10:plots.py`, so they locked in nothing. Both fixtures had drifted from the probe
case they claimed to adapt:

- **TestT2** used `tests/test_plots.record()`, whose `status` defaults to `"COMPLETED"`.
  A non-empty registry status shadows the report's free-text status in `_lane_markers`, so
  the substring path the class is named for was never entered. The records now pass
  `status=""`, matching the probe's `registry_record(overall_status="")` default.
- **TestT9** built its run from `plots.demo_result(PAIR_B)`, whose instruments envelope
  contributes GWAS years 2014 and 2020, so with floor 2004 and ceiling 2020 the
  `ceiling == floor` branch was never reached. The test now empties the exposures list, as
  GI19 had it, and additionally asserts `"2004"` is among the ticks.

Verified by running the whole file against `git show caa2d10:plots.py` swapped into place:
**23 of 24 fail (21 failures, 2 errors)**, including every T2 and T9 test. The one that
passes is `test_reports_at_different_years_are_not_pushed_off_the_lane_at_all`, which is a
soundness check on the per-year rung rather than a defect demonstration and is labelled as
one.

### OPEN — the T5 stagger introduced a label collision on the probe's control case

Found by re-running `probe_timeline.py` against the branch head. **Not fixed in this
round**; recorded here so it is not discovered as a surprise later.

```
GI01.collisions: expected [], observed [['phase 2', 'phase 3']]
```

`GI01` is the probe's control case - "does an honest dossier draw an honest figure" - and
it is not one of T5's cases (`GI08`, `GI15`, `GI17`, `GI20`, all of which do close). At
`caa2d10` the probe measures zero collisions on it. At the branch head two phase labels
print over each other.

**Mechanism, measured directly.** `_staggered` counts the rung within the marker's own
start year, so two markers in one lane at two *different* years both receive rung 0:

```
year 2004  phase 3   rung=0  offset=+0.20
year 2003  phase 2   rung=0  offset=+0.20
```

Identical `y`. The docstring's premise - "markers at different years do not collide
horizontally" - is true of the *markers*, which are points, and false of the *labels*,
which are text several years wide in data units on a 1998-2031 axis. `GI01`'s torcetrapib
lane holds two registry records starting 2003 and 2004, which is ordinary data, not an
adversarial fixture.

The old per-lane `enumerate` stagger did not have this failure, and the new bounded ladder
is what actually fixed T5's real problem (an unbounded offset reaching the neighbouring
drug's row). So the repair is neither "revert" nor "keep": the rung has to be counted over
markers that are close **in x**, not equal in x, with the separation derived from the
label's width in data units rather than from a year being a year. That needs its own
design pass, its own test and a full gate re-run, and it is a legibility defect - no label
on that figure makes a false claim - so it is being handed over rather than patched at the
end of a documentation commit.

`tests/test_fix_timeline_t1_t9.py` does not catch it; the collision assertions there cover
`GI20` and the ten-same-year case, both of which are same-year groups.

### What is not claimed

- T4, T10, T11, T12, T13 and A1 are scope_limit/observation findings and were left exactly
  as `RESULTS.md` measured them.
- T6's guardrail asks to show a per-disease stage where one is derivable from
  `clinical_reports`. It is not derivable: a report in this project's schema carries
  `trial_phase`/`status`/`why_stopped`/`year`/`url`, never a disease or indication field.
  The label states that the number is cross-indication and the ordering no longer uses it.
- `_is_terminal_status` is an anchored match against three controlled states. A free-text
  status that begins with some other word and means "stopped" is not caught; that is a
  vocabulary limit, and such a report's retrieved reason is counted in the not-drawn line
  rather than disappearing.

---

## M4, M5, M6, M7 — the MVP2 data layer

Source: `RESULTS.md` section (c.3). **The derived tables under `MVP2/data/` were
regenerated, and the diff is for Jingrui's review.** A reader-facing copy of this section
is appended to `MVP2/data/README.md`, in Chinese and English, next to the tables
themselves. Nothing under `archive/` was touched; the MVP1 baseline is byte-identical and
still hashes to `af2a44ac…`.

### M4 — the extractor read a shifted source layout through the printed header

sTables 31-35 of the UKB mapping supplement print one
`Beta, Odds ratio, 95% UCI, 95% LCI, p value` header over columns 9-13 for every row, but
a single-SNP `Wald ratio` row carries its values one column to the right of that header.
Reading the fixed indices on such a row put the **odds ratio into `ci_high`** and a
**beta-scale confidence bound into `p_value`**. 498 source rows are affected (18 in
`sTable 33`, 480 in `sTable 35`); 18 of them reach `new_pair_records.csv`. `RESULTS.md`
counted 9 in `new_unique_pairs.csv` on the pre-fix table; on the regenerated one it is 14,
because the M5 fix below changed which representative row survives for some pairs.

`ukb_row_layout_is_shifted(row)` decides per row on an identity the row must satisfy
either way: `exp(beta)` names which physical column holds the odds ratio, independently of
the printed header. On a shifted row the p value is read from column 10, which is where it
is.

The interval those rows carry is **not** discarded. Columns 12-13 hold a real 95%
interval, on the beta scale — where the same two columns are odds-ratio scale on every
unshifted row — so writing them into `ci_low`/`ci_high` would mix two scales in one
column. They are carried in two new columns, `ci_low_beta_scale` / `ci_high_beta_scale`,
blank on every unshifted row, and every shifted row carries an `extraction_note` saying
what happened and why. All three travel into the merge provenance sidecar. Leaving them
empty with nothing recording it was the one option this project's rules exclude.

`sTable 33` row 16, before and after:

| Field | Before | After |
|---|---|---|
| `ci_high` | `2.91670448786792` (that is `exp(1.07045…)`, the odds ratio) | `""` |
| `ci_low` | `0.702518316457593` | `""` |
| `p_value` | `1.43839044131509` (a confidence bound) | `1.18185020203274e-08` |
| `ci_low_beta_scale` | — | `0.702518316457593` |
| `ci_high_beta_scale` | — | `1.43839044131509` |
| `extraction_note` | — | "single-SNP Wald-ratio row: the printed … header does not hold for this row…" |

**Recorded rather than silently re-published, and then repaired — see the owner ruling
below.** On an *unshifted* UKB row the printed header names column 11 "95% UCI" and
column 12 "95% LCI", and the values are the other way round — column 11 holds the lower
bound. Those two numbers are the extractor's own 0-based indices, `text(row, 11)` and
`text(row, 12)`; opening the workbook, they are the columns **Excel labels `L` and `M`**,
the 12th and 13th, with Excel's `K` holding the odds ratio. Every "column 11 / column 12"
below, including the one inside the shipped `extraction_note`, means `L` and `M`
(7,912 of the 10,804 regenerated unique pairs carried `ci_low > ci_high`; 6,914 did
at `caa2d10`, so this is pre-existing and not introduced here). On 2026-09-17 the bounds
were extracted **as printed**, under the header's own names, and deliberately not
reordered, on the reasoning that reordering would be the extractor deciding what the
source meant. **The owner overruled that on 2026-09-18**; the paragraph above describes
the 2026-09-17 tables, and the section below describes the ones in the repository now.

### Owner ruling 2026-09-18 — the swapped bounds are shipped in numeric order

**The finding is the product story.** While extracting a published supplement, the agent
pipeline hit a pair of cells that cannot both be what their header calls them: read under
the printed names, `ci_low` came out larger than `ci_high` on every UKB row that carries
both bounds. No judgement about the paper's science is involved, and none is made here.
A confidence interval whose lower bound exceeds its upper bound is an arithmetic
impossibility, which is why the pipeline could flag it from the numbers alone. What it
found is a **header/typesetting inconsistency in supplementary tables** — the label over
a column does not match what the column holds — and that is the whole claim.

**The ruling.** Reorder into correct numeric order in the shipped tables, preserve the
as-printed values, annotate every affected row.

**The rule, exactly as implemented.** `bounds_in_numeric_order(ci_low, ci_high)` in
`MVP2/scripts/screen_seed_papers.py` swaps a row's two bounds **only** when both parse as
numbers and `ci_low > ci_high`. A row already ascending, a row with equal bounds, and a
row with a blank or non-numeric bound are returned untouched. Nothing is reordered by
re-reading the header; the trigger is the arithmetic, per row. This runs in `add()`, so
every source goes through it, not only the UKB one.

**Preservation.** A reordered row carries the pair exactly as the source prints it in two
new columns, `ci_low_as_printed` / `ci_high_as_printed` — the same convention as
`ci_low_beta_scale` / `ci_high_beta_scale` from the shift fix above, and blank on every
row that was not reordered, exactly as those two are blank on every unshifted row. A test
asserts the as-printed pair is the shipped pair swapped back character for character, so
no bound was recomputed, re-rounded or re-read. With the three columns the shift fix added
on 2026-09-17, the four screened CSVs and the merge provenance sidecar now carry five
source-side columns beyond the original schema.

**Annotation.** Every reordered row's `extraction_note` gains, verbatim:

> 95% bounds reordered: read under the source header's own names this row came out with
> ci_low greater than ci_high, which no confidence interval can satisfy, so the two
> numbers are written to ci_low/ci_high in numeric order. Neither number was recomputed -
> the pair is the source's own - and the values exactly as the source prints them are
> preserved in ci_low_as_printed/ci_high_as_printed. Observed on the UKB mapping
> supplement, whose header prints '95% UCI' over the column holding the lower bound and
> '95% LCI' over the column holding the upper one.

That last sentence is a claim about where this fires, so it is guarded rather than
assumed: a test asserts every reordered row is a `ukb_mapping_2025` row, and a new source
whose bounds arrive inverted fails it and forces the note to be re-worded.

**Before and after, counted:**

| File | Rows | `ci_low > ci_high` before | Reordered | `ci_low > ci_high` after |
|---|---|---|---|---|
| `candidate_pairs.csv` | 20,460 | 16,944 | 16,944 | **0** |
| `screening_ledger.csv` | 20,460 | 16,944 | 16,944 | **0** |
| `new_pair_records.csv` | 17,405 | 14,509 | 14,509 | **0** |
| `new_unique_pairs.csv` | 10,804 | 7,912 | 7,912 | **0** |
| `mvp1_plus_mvp2_candidate_metabolite_disease.csv` (`ci_low`/`ci_upp`) | 21,921 | 7,912 | 7,912 | **0** |
| `…provenance.csv` | 10,804 | — | 7,912 | — |

**The residue is zero, and that is measurable rather than hoped for.** Every row with two
numeric bounds now ascends. The 1,998 candidate rows (1,379 unique pairs) with no bounds
at all break down as `chen_2023 ST23` 72, `yin_2025` 282, `zoodsma_2025 ST14` 1,146 —
reverse or SE-only tables that print no interval in the columns extracted — plus the 498
shifted Wald-ratio rows, which is the M4 fix above and unchanged. No row has equal bounds
and no row has an unparseable one, so there is no third category to explain. The manifest
records the count it measured itself, under
`bound_order.remaining_ci_low_greater_than_ci_high`.

**What did not move.** A field-level diff of every regenerated table against `dea16a1`:
the only changed fields anywhere are `ci_low`, `ci_high` (`ci_upp` in the merged table)
and `extraction_note`, on exactly the reordered rows. Chen 2023's 1,518 bounded rows
already ascended and are byte-identical. Row counts, pair identities, `supporting_mr_rows`,
and every summary count are unchanged: 20,460 candidates, 17,405 records, 10,804 unique
pairs, 21,921 merged rows. `archive/` untouched; the MVP1 baseline still hashes to
`af2a44ac…` and `reference_original_merged.csv` still to `af9b45d8…`.

`MVP2/literature/search_runs/pair_batch_smoke_glycine_cad_20260912/manifest.json` names
`new_unique_pairs.csv` by digest, so its `input` block is re-stated again
(`7b255fd7…` → `80e8a233…`, `rows` still 10,804) and its `input_note` says why. The run's
own history is untouched, and the pair it searched is still the row at its recorded
offset: 2513 is still Glycine → Coronary Artery Disease, a Zoodsma row with no bounds.

**Regression test.** `tests/test_fix_mvp2_m4_m5_m6_m7.py::TestM4BoundOrderIsNumeric`, 9
tests. It replaces `test_unshifted_bounds_are_still_as_printed_and_that_is_recorded`,
which asserted the opposite and would otherwise have passed by asserting the defect.

**Both shipped bound pairs are guarded, not only the reordered one.** A review of this
commit found the zero-inverted-interval assertion covering `ci_low`/`ci_high` alone. The
498 shifted Wald-ratio rows leave that pair blank and ship their interval in
`ci_low_beta_scale`/`ci_high_beta_scale`, which `add()` passes through without
reordering. All 498 ascend as the source prints them — measured, so nothing wrong ships
today and no claim above is affected — but a future row arriving inverted there would
have shipped inverted, with no note and no as-printed pair, on a green suite.
`test_no_shipped_table_carries_an_impossible_interval` now measures both pairs across the
four screened tables, plus `ci_low`/`ci_upp` in the merged table and the beta-scale pair
in the provenance sidecar. The beta-scale pair is guarded by a failing test rather than
reordered in the extractor: the reorder rule was written against a source whose bounds
were measured to be swapped, and a pair nobody has yet seen inverted should stop a human
rather than be silently rearranged. `ci_low_as_printed`/`ci_high_as_printed` is
deliberately excluded from the guard — being in the impossible order is what it is for.

### M5 — `normalize()` erased `%`, so two different exposures became one pair

`re.sub(r"[^a-z0-9]+", " ", …)` deleted `%`, so the ratio exposure `Omega-3%` (omega-3 as a
percentage of total fatty acids) and the absolute exposure `Omega-3` collapsed into one
pair identity. They are different exposures. `%` now survives normalization.

**The distinct-pair count changed, and that is the point:**

| | Before | After |
|---|---|---|
| kept pair keys (`new_pair_key_count`) | 9,801 | **10,804** (+1,003) |
| rows in `new_unique_pairs.csv` | 9,801 | 10,804 |
| merged table rows | 20,918 | **21,921** |
| merged unique pairs | 20,079 | 21,082 |
| `candidate_row_count` | 20,460 | 20,460 (unchanged) |
| `new_pair_record_count` | 17,405 | 17,405 (unchanged) |

No source row was added or removed. 1,003 pairs that were being merged into another
exposure's identity are now counted as their own.

### M6 — every appended row claimed exactly one supporting source row

`merge_pairs.py` wrote the literal string `"1"` into `supporting_mr_rows` for every
appended row, on a table whose representative-row rule explicitly keeps one row per
canonical pair out of several. `screen_pairs` now counts the source rows behind each
canonical key and writes `supporting_source_rows` onto the unique-pair row; the merge
carries that count through.

Distribution over the 10,804 appended rows: **1 → 5,085 pairs, 2 → 5,278, 4 → 441**, and
the counts sum to **17,405 = `new_pair_record_count`**. That reconciliation is asserted as
a test, so the number cannot drift away from the record count it is a count of.

### M7 — manifests hashed CRLF content a clean LF checkout cannot reproduce

Four repairs, all in `MVP2/src/pair_screening.py` and its callers.

1. **The digest is of the committed bytes.** This package writes its CSV/JSON with
   `lineterminator="\n"`, but a Windows checkout with `core.autocrlf` rewrites those bytes
   to CRLF on disk without changing the committed blob. `sha256` normalises CRLF to LF
   before hashing, *except* for a path `.gitattributes` pins to raw bytes (`archive/**`,
   `provenance/**`, `MVP2/literature/seeds/**`, `MVP2/literature/studies/**`, and the
   `binary` suffixes), whose blob genuinely keeps its CRLFs on every platform.
2. **No `git` binary is consulted.** The first version shelled out to `git check-attr` and
   returned `False` on any `OSError`/`SubprocessError` or non-zero exit, so the same bytes
   hashed differently whenever git was absent from PATH or the bundle was verified from a
   zip export with no `.git` — which is exactly the reachability `RESULTS.md` records
   ("anyone verifying the bundle"), and it failed **open**: the archived baseline, with
   11,118 CRLF pairs and named in two manifests, silently took the LF-normalising branch
   and every one of those entries failed. `.gitattributes` is now read directly, in pure
   Python, with `fnmatch` over the repo-relative POSIX path. A test re-hashes the baseline
   with `PATH` emptied and gets the same digest.
3. **The rule is recorded beside the digest.** Every manifest entry this package writes is
   now `{"path", "sha256", "bytes"}` with `bytes` one of `"as-committed"` or
   `"lf-normalized"`, so a verifier can reproduce the number instead of guessing which
   rule produced it.
4. **Paths are repo-relative POSIX, unconditionally.** `record_path()` resolves a path and
   spells it relative to the repository root with forward slashes, so the manifest bytes
   are identical on Windows and Linux. The first version replaced Jingrui's stale macOS
   absolute paths (`/Users/<teammate>/…`) with this throwaway worktree's absolute Windows
   ones (`<workspace>\…\metabocausal-rerun\…`), which resolve on no machine but this
   one, in the same commit whose subject was cross-platform hashing.

**Re-verified: all 7 hashed entries across all 4 MVP2 manifests match the files they name,
and every recorded path is repo-relative with no backslash.** That sweep is a test, not a
one-off check.

`screened_20260912/manifest.json` carries a `run_id` of the regeneration, in a directory
named for the 2026-09-12 screening. A `run_id_note` now says which is which: the directory
records the screening these tables belong to, and re-running the same extractor over the
same workbooks and the same baseline rewrites the files without making it a different
screening.

### `MVP2/literature/search_runs/` is a record, not a derived table

The first version of this fix re-ran the batch driver over
`pair_batch_smoke_glycine_cad_20260912/` to repair its input digest. With
`overwrite=false` the driver **resumed** rather than searched, and then overwrote the
record anyway: `run_id` 20260912T184153Z → 20260917T060435Z, `config.overwrite` true →
false, `searched_count` 1 → 0, `skipped_count` 0 → 1, and the index row's status
`success` → `resumed`. The committed evidence then said a search run happened on
2026-09-17 that searched zero pairs. The same run also turned that manifest's one
repo-relative path into a Windows one.

That directory is restored from `caa2d10` and only its `input` block is re-stated, because
the file it names was regenerated: `sha256` → the new digest, `rows` 9801 → 10804, plus
the `bytes` key the writer now records. An `input_note` says exactly that. The run's own
history — `run_id`, `config`, `summary`, `pair_search_index.csv` — is untouched, and a test
pins it down. The driver itself now writes POSIX paths so a future real run cannot
reintroduce a backslash.

### Regenerated files

`MVP2/data/extracted/screened_20260912/{candidate_pairs,new_pair_records,new_unique_pairs,screening_ledger}.csv`
and its `manifest.json`;
`MVP2/data/extracted/mvp1_plus_mvp2_candidate_metabolite_disease.{csv,provenance.csv,manifest.json}`.
Regenerated by `MVP2/scripts/screen_seed_papers.py` and `MVP2/scripts/merge_new_pairs.py`
from the committed seed workbooks and the committed MVP1 baseline. `archive/` untouched.
`mvp1_plus_mvp2_candidate_metabolite_disease.reference_original_merged.csv` is untouched —
it is the pre-schema-change reference copy and still hashes to `af9b45d8…`.

The same eight files were regenerated a second time on 2026-09-18 for the bound-order
ruling, from the same two scripts, the same workbooks and the same baseline. The
`pair_batch_smoke_glycine_cad_20260912/manifest.json` `input` block was re-stated with
them, for the same reason as on 2026-09-17.

### Regression test

`tests/test_fix_mvp2_m4_m5_m6_m7.py`, 34 tests (25 plus the 9 in
`TestM4BoundOrderIsNumeric`), against the real committed seed workbook and the real
committed artifacts. Offline and read-only apart from two temporary files one M7 test
writes and removes.

### What is not claimed

- This is still source extraction plus an anti-join. No row here is accepted MR evidence,
  and the regenerated tables do not make any pair more or less likely to be real.
- The bound reordering is a statement about two cells' order, not about the study. It
  does not make an interval correct, wide enough, or evidence of anything; it makes the
  pair of numbers readable, keeps the printed pair on the row, and says which rows moved.
- What the pipeline detected is a header/typesetting inconsistency in the supplementary
  tables. Nothing here says the analysis behind those tables is wrong, and nothing here
  checks it.
- The `.gitattributes` reader understands the subset of the pattern language this
  repository uses — a leading-directory glob and a suffix glob — and nothing else. A
  pattern outside that subset would need it extended.

---

## L2, L3, L6 — the lifecycle viewer (`demo/genetic-insights/`)

Source: `RESULTS.md` section (c.1), cases `LC01 LC03 LC04 LC05 LC06 LC09 LC10` in
`rerun_2026-09-17/new_probes/timeline/{probe_timeline.py,viewer_stage_probe.cjs}`.

### L6 — the chronology guard compared raw date strings

`date.fromisoformat` accepts ISO-8601 basic format (`20070115`) on a day-precision event,
and `-` sorts below a digit, so a basic-format November date sorted earlier than an
extended-format January date of the same year. A **true** chronological order (LC09) was
rejected and a **reversed** one (LC10) was accepted. Both guards now parse every event's
date — day/month/year precision, extended or basic — into a comparable value before
comparing. LC09 is accepted, LC10 is rejected.

The JS half has a documented reachability limit that is not a gap in this fix: the
per-event regex in `viewer.template.html`'s `validate()`
(`/^(\d{4})(-\d{2})?(-\d{2})?$/`) refuses a basic-format date before the chronology guard
runs, on both cases, before and after. That regex is the date-*format* policy and is not
one of L2/L3/L6. A test pins the limit down so a future change to the regex cannot
silently reopen it.

### L2 — an event with an unknown stage was dropped from the timeline with no notice

`render()` filtered the stage list to `display_order` before grouping, so an event whose
`evidence_stage` was outside the standard (LC03: a Pfizer safety-stop relabelled
`regulatory_action`) simply vanished — 10 of 11 events shown, nothing saying so. Those
events now render into a visible "Unrecognized stage" group carrying each event's raw
stage string. `events_dropped` is `[]` and `events_rendered` is 11.

Two follow-ups on that bucket:

- **It is placed by its own chronology, not appended.** The timeline is a left-to-right
  grid with an axis line through the nodes, so appending the bucket after the last
  lifecycle stage put LC03's 2006 event to the right of a group ranged 2017-2026, reading
  as the latest point in the programme. `chronologyRank()` splices it at the position its
  own earliest event implies: LC03 now renders
  `human_genetics, preclinical, clinical, unrecognized_stage, later_genetics, class_status`.
  The known stages keep `display_order` — they are not re-sorted, because two shipped
  recordings legitimately have a `later_genetics` event before their first `clinical` one.
- **Its node is not drawn like an evidence stage.** Its markup is a stage group like any
  other and the CSS overrode the node colour only for the four known non-default stages,
  so `.stage-unrecognized_stage` fell back to the same `var(--teal)` as the first real
  stage. It is now a hollow node with a grey ring, and the heading is grey.

**The Markdown report and the Slack payloads say it too.** `render_bundle.render()` writes
`index.html`, the evidence summary, the full report and the Slack payloads from one
bundle, and only the viewer had learned about unrecognized stages; `summary_markdown` and
`slack_payloads` still printed `regulatory action` in exactly the same form as
`human genetics`. `stage_is_outside_standard()` / `stage_label()` are now one shared
helper used by both, and the stage prints as
`regulatory action (outside this bundle's lifecycle standard)` in all three renderings. A
bundle with no declared standard marks nothing. Measured: the renderer's `evidence-summary.md`
and `slack-messages.json` output for **all five** committed recordings is byte-identical
before and after this change, and for the two v2 recordings it also matches the committed
artifacts. (The three v1 recordings' committed artifacts already differed from what the
renderer produces at `caa2d10` — they are an older bundle schema — and are untouched here.)

### L3 — the required-stage check was label-presence, not an evidence check

`validate_bundle` asked only whether each required stage *string* appeared somewhere among
the events' labels. LC04 swaps two labels — a 2017 class-outcome event becomes
`human_genetics` and the real 1989 human-genetics event becomes `clinical` — and both
validators passed.

The first version of this fix replaced that with a date-ordering walk over consecutive
required stages. That was wrong in three ways and is gone:

- It was a **no-overlap rule**, not an evidence check. Evidence stages genuinely overlap —
  human-genetics findings keep accumulating after preclinical work starts, and the shipped
  evacetrapib recording carries a `later_genetics` event dated before its first `clinical`
  event. The rule forbade the ordinary case rather than the mislabelled one, and its error
  text ("Stage label not backed by its evidence") asserted something false about a
  correctly-labelled event.
- It walked only stages in `required_stages`, and only **consecutive** pairs. An event
  relabelled to a stage that is in `display_order` but not required — `later_genetics` or
  `class_status` on the shipped bundles — was excluded from every group it compared. A
  2004 Phase-3 trial-start event relabelled `later_genetics` left the three required
  stages populated and non-overlapping, so both validators accepted it and the viewer
  rendered a Phase 3 trial under "Later genetics".
- It read only the event's date, never its `type`, `scope` or `title` — which is what the
  guardrail asked for.

**What it is now.** Each event's stage label is checked against the rows behind it: the
event's own `type`, `scope` and `title` must carry at least one term from that stage's
evidence vocabulary (`render_bundle.STAGE_EVIDENCE_TERMS`, mirrored as `stageEvidenceTerms`
inside the viewer's `validate()`). It runs over **every** stage the standard declares in
`display_order`, required or not. A stage the standard declares but the vocabulary does
not know is a hard error — saying the labels cannot be checked beats checking nothing.

This is a **phrase heuristic**, in the sense `validate_card.py` uses for its own language
rules, and must be described as one: it catches an event filed under a stage nothing in its
own description supports, and a determined rewording of `type`/`scope` gets past it. It is
not a proof.

`RESULTS.md` lists L3 with cases LC04 **and LC05**; both are closed:

| Case | Before | After |
|---|---|---|
| LC04 (two swapped labels) | both validators passed | both reject: "Stage label is not supported by the event's own evidence: event 'human-genetics' is filed under 'clinical', and its type ('Human genetics') and scope (…) carry none of that stage's evidence vocabulary" |
| LC05 (`required_stages: []`) | `missing` empty, the walk never executed, nothing checked — while the bundle printed that standard's note claiming the guarantee | both reject: a standard that requires nothing checks nothing and must not be presented as a lifecycle standard |
| LC01 relabelled to a non-required stage | accepted; a Phase 3 trial rendered under "Later genetics" | both reject, naming `trial-start` and `later_genetics` |
| LC01 baseline, LC03, both shipped v2 recordings | accepted | accepted |
| a standard declaring a stage with no vocabulary | silently unchecked | rejected, "no evidence vocabulary" |

### Regression test

`tests/test_fix_viewer_l2_l3_l6.py`, 27 tests. The LC bundles are static fixtures under
`tests/fixtures/lifecycle/`, copied from the probe's own outputs.
`tests/fixtures/viewer_probe_harness.cjs` is an adapted copy of
`viewer_stage_probe.cjs`'s lifting technique: `validate(b)` and the stage-grouping lines
are extracted from `viewer.template.html`'s own source as literal text and evaluated, so
the shipped product is what is measured, never a re-implementation of it. The JS tests skip
when `node` is not on PATH.

### What is not claimed

- The evidence check is a phrase heuristic over English `type`/`scope` text, not a proof,
  and the vocabulary is this project's five lifecycle stages and nothing else.
- L2's bucket makes an out-of-standard stage visible and marks it in all three renderings.
  It does not decide whether the stage is correct — that is the bundle author's to fix.
- The per-event date-format regex in the viewer's `validate()` is unchanged and still
  refuses ISO basic format; see L6 above.

---

## MVP2 data regeneration — what Jingrui needs to look at

The derived tables under `MVP2/data/` were regenerated on this branch. **Nothing under
`archive/` was touched**, and the MVP1 baseline still hashes to `af2a44ac…`. A bilingual
reader-facing copy of this list sits in `MVP2/data/README.md`, next to the tables, so it
is found without reading this file.

Four things for her review, in the order they matter:

1. **The distinct-pair count went up on purpose: 9,801 -> 10,804.** 1,003 pairs that were
   being folded into another exposure's identity are now counted as their own, because `%`
   survives normalization and a ratio exposure is not the absolute exposure. If she
   disagrees that `Omega-3%` and `Omega-3` are two exposures, this is the decision to
   reverse, and everything downstream of it moves.
2. **Three new columns** — `ci_low_beta_scale`, `ci_high_beta_scale`, `extraction_note` —
   appear in four CSVs and the merge provenance sidecar, blank on every unshifted row.
   They exist so the interval a shifted Wald-ratio row genuinely carries is not thrown
   away when it cannot go into `ci_low`/`ci_high` without mixing two scales.
3. **`supporting_mr_rows` stopped being the constant `"1"`.** The real distribution is
   `{1: 5,085, 2: 5,278, 4: 441}` and the counts sum to 17,405, the record count.
4. **Repaired on 2026-09-18, by the owner's ruling.** On an *unshifted* UKB row the
   printed header names the two columns **Excel labels `L` and `M`** (the 12th and 13th;
   extractor indices 11 and 12) "95% UCI" and "95% LCI" and the values are the
   other way round: 7,912 of the 10,804 unique pairs came out with `ci_low > ci_high`
   (6,914 did at `caa2d10`, so this is pre-existing, not introduced here). The 2026-09-17
   tables kept them as printed. The tables in the repository now put the two numbers in
   numeric order, preserve the printed pair in `ci_low_as_printed`/`ci_high_as_printed`
   and annotate every row touched; the reorder fires only where `ci_low > ci_high`, never
   by re-reading the header, and 0 rows with `ci_low > ci_high` remain. Full write-up in
   the M4 section above, "Owner ruling 2026-09-18". **Two more columns therefore appear in
   the same five files** — the count in item 2 is now five new columns, not three.

`MVP2/literature/search_runs/` was deliberately left as a record of searches that were
performed. Only the `input` block of `pair_batch_smoke_glycine_cad_20260912/manifest.json`
was re-stated, because the file it names was regenerated; `run_id`, `config`, `summary`
and `pair_search_index.csv` are `caa2d10`'s, and a test pins them.

---

## Streamlit status

`app.py` and `app_data.py` arrived in `a881f3f` (1G), after the four fix commits. They are
a browser over already-shipped cards, figures and the MVP2 library; they fix none of the
16 defects and are recorded here only so the branch is described completely.

Measured at the branch head:

| Check | Result |
|---|---|
| `import app_data` | OK, standalone |
| `python -m streamlit run app.py --server.headless true --server.port 8599` | starts; `GET /_stcore/health` -> **200 `ok`** |
| `streamlit` version present | 1.64.0 |
| `tests/test_app_data.py` | included in gate 1's 1022 and passing |
| secrets | none. The provider key is a runtime `st.text_input(type="password")`; no key, token or credential literal appears anywhere in the branch diff |

`requirements.txt` un-commented `streamlit>=1.30.0` and `pandas>=2.0` for this.

One operational note, not a defect: `--server.headless true` binds all interfaces and
prints an External URL. On a laptop on an untrusted network that is a listening service —
bind to loopback, or do not run it there.

---

## What this round leaves open

- **The `GI01` phase-label collision** the T5 stagger introduced. Full mechanism and
  measurement above; it is a legibility regression on ordinary data, not a false claim.
- **Gate 1 is not green**, and was not green at `caa2d10` either: one pre-existing ledger
  test fails, in a file no commit on this branch touches.
- **The findings this round never aimed at**: F1-F7 of the 2026-09-16 study all still
  hold; T4, T10-T13, L1, L4, A1, GEM-O3, GEM-O6, M1, M2, M9, M11, M12 are
  scope_limit/observation rows and were left as `RESULTS.md` measured them.
- **Every wording rule added here is a phrase heuristic** — V7's second half, L3's
  evidence vocabulary — in the same sense `validate_card.py` already uses for V2/V3/V4/V6.
  They are guardrails. A determined paraphrase gets past them, and neither is a proof.
