# Baseline drift: Zipeng's Section 9 harness re-run against current `main`

Scope: re-run `scripts/probe_section9.py` unchanged against `b056397` (current `origin/main`,
including PR #17) and measure what moved relative to the artifacts he produced at `bcb32a9`
on 2026-09-16. This file reports measurement only. Interpretation of the eight defect findings
belongs to the Reverify phase.

- Worktree: `<workspace>/metabocausal-rerun`
- Branch: `rerun/section9-adversarial-20260916`, HEAD `b05639721b07345612bba4ebf66f989805b9703c`
- Python: `3.12.10 (tags/v3.12.10:0cc8128, Apr  8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]`
- Platform: `Windows-11-10.0.26200-SP0`
- Network: not used. No provider credential used.

---

## 1. Headline result

**0 of the 51 cases changed outcome. No `printed`/`blocked`/`bypassed`/`raised` flag moved, no
`expectation_met` moved, no matched rule set moved, and no rendered Section 9 or full-card byte
changed.** The harness exited `0` with `all_expectations_met: true`.

| Metric | Expected (`bcb32a9`) | Observed (`b056397`) | Same |
|---|---|---|---|
| cases | 51 | 51 | yes |
| printed | 31 | 31 | yes |
| blocked | 17 | 17 | yes |
| bypassed | 2 | 2 | yes |
| raised | 1 | 1 | yes |
| all_expectations_met | true | true | yes |
| exit code | 0 | 0 | yes |

---

## 2. Command and receipts

### 2.1 Harness

```
$ cd <workspace>/metabocausal-rerun
$ export PYTHONIOENCODING=utf-8
$ python scripts/probe_section9.py
EXIT_CODE=0
```

stdout tail (last 10 of 53 lines — 51 case lines, a blank, and the summary; the complete capture is in
`observed_b056397/probe_stdout.txt`, and every one of the 51 result lines is byte-identical to
`observed_b056397/run.log` and to Zipeng's committed `run.log`):

```
T06  printed  expected=printed  rules=none
T07  printed  expected=printed  rules=none
T08  printed  expected=printed  rules=none
T09  blocked  expected=blocked  rules=V5
U01  printed  expected=printed  rules=none
U02  blocked  expected=blocked  rules=V1
U03  printed  expected=printed  rules=none
U04  printed  expected=printed  rules=none

51 cases; artifacts written to <workspace>/metabocausal-rerun\docs\research\section9_adversarial\artifacts
```

stderr was empty. No "Expectation mismatches:" line was printed, which is why the exit code is `0`.

### 2.2 Restoration of Zipeng's bundle

The run rewrote three tracked files in his bundle (`manifest.json`, `results.csv`, `run.log`).
After copying the new outputs into `observed_b056397/`:

```
$ git restore docs/research/section9_adversarial
$ git status --porcelain docs/research/section9_adversarial
?? docs/research/section9_adversarial/rerun_2026-09-17/
$ git diff --stat HEAD -- docs/research/section9_adversarial
(empty)
```

The only entry is this rerun directory. His bundle is byte-identical to `HEAD` again. The same
check was repeated after the unittest run (section 5) with the same output.

---

## 3. Case-by-case diff — 51/51 unchanged

Comparison method: parse `git show HEAD:docs/research/section9_adversarial/artifacts/results.json`
(his committed 51 rows) against this run's `results.json`, and diff every field of every row.

```
expected cases: 51  observed cases: 51
same case-id set: True
cases with ANY field difference: 0
```

Fields compared per row: `case_id`, `category`, `attack`, `construction`, `pair`, `reachability`,
`gate_one`, `outcome`, `expected`, `matched_rules`, `expectation_met`, `notes`.

Because the count of changed cases is zero, the "old outcome / new outcome / which PR explains it"
table this section was to contain has no rows. The per-PR reading that explains the absence of
drift is in section 6.

### 3.1 Rendered output diff — 64/64 unchanged

| Directory | Files expected | Files observed | Same file set | Files differing (raw bytes) | Files differing (LF-normalized) |
|---|---|---|---|---|---|
| `artifacts/section9_outputs/` | 33 | 33 | yes | 0 | 0 |
| `artifacts/full_cards/` | 31 | 31 | yes | 0 | 0 |

This includes the renderer's card-wide attestation sentence (F1/F3 surface) and `s18.md`, the
forged-heading case (F6). No attestation wording and no forged-heading placement moved.

---

## 4. The only two files that changed, and why

`HASHES.tsv` in this directory records all 69 artifact files with LF-normalized SHA-256 for both
revisions. 67 are identical; 2 differ.

### 4.1 `run.log` — environment fields only

`git diff` against his committed copy shows exactly two hunks, both outside the 51 result lines:

```
-command: /scratch/zpoints/MetaboCausal/venvs/metabocausal-shared-py312/bin/python scripts/probe_section9.py
-cwd: /project/aip-cpsmcgil/zpoints/metabocausal-shared
-git_head: bcb32a91071b93cacaa62cd7487abb2d991baeb7
-git_branch: research/section9-adversarial-probes
+command: <home>\AppData\Local\Programs\Python\Python312\python.exe scripts/probe_section9.py
+cwd: <workspace>/metabocausal-rerun
+git_head: b05639721b07345612bba4ebf66f989805b9703c
+git_branch: rerun/section9-adversarial-20260916
...
-51 cases; artifacts written to /project/aip-cpsmcgil/zpoints/metabocausal-shared/docs/research/section9_adversarial/artifacts
+51 cases; artifacts written to <workspace>\...\docs\research\section9_adversarial\artifacts
+all expectations met: true
```

Reading: interpreter path, working directory, revision and branch. Not attributable to #13/#14/#16.

### 4.2 `manifest.json` — environment fields, plus ten hashes that differ for a checkout reason

Changed keys: `generated_at_utc`, `python`, `platform`, `git_head`, `git_branch`, `git_status`,
all ten entries under `hashes` / `reference_only_hashes`, and the path separators in the `hashes`
keys (`data/demo_card_inputs.json` → `data\demo_card_inputs.json`, because the manifest builds
keys with `Path.relative_to` and this run is on Windows).

`cases`, `outcomes`, `all_expectations_met`, `network_used`, `provider_api_used`, `command` and
`model_path_method` are unchanged.

**The ten hash differences are not code changes.** Every one of the ten measured inputs is
byte-identical at the Git blob level between `bcb32a9` and `b056397`:

```
path                                 bcb32a9 vs b056397 (git blob)   his manifest hash == bcb32a9 blob
data/demo_card_inputs.json           raw=SAME     eolnorm=SAME       True
render.py                            raw=SAME     eolnorm=SAME       True
validate_card.py                     raw=SAME     eolnorm=SAME       True
llm/__init__.py                      raw=SAME     eolnorm=SAME       True
llm/base.py                          raw=SAME     eolnorm=SAME       True
llm/interpret.py                     raw=SAME     eolnorm=SAME       True
llm/registry.py                      raw=SAME     eolnorm=SAME       True
prompts/interpretation.md            raw=SAME     eolnorm=SAME       True
scripts/interpretation_fixtures.py   raw=SAME     eolnorm=SAME       True
data/1a_sample.json (reference-only) raw=SAME     eolnorm=SAME       True
```

and independently:

```
$ git diff --name-only bcb32a9..HEAD -- data/ prompts/ llm/ render.py validate_card.py ledger.py
(empty)
```

The harness script itself is also the exact one he ran:

```
probe_section9.py HEAD blob sha256      : a1cb309bcfb984f104dc2bbb55b46f8bb2a076074a1377942d27e396a9915854
his manifest recorded                   : a1cb309bcfb984f104dc2bbb55b46f8bb2a076074a1377942d27e396a9915854
HEAD blob == his recorded hash          : True
worktree(eol-normalized) == HEAD blob   : True
```

The manifest hashes differ because `core.autocrlf=true` in this worktree (measured) and
`.gitattributes` does not mark these paths `-text`, so Git checks the files out with CRLF while
`_sha256()` hashes the on-disk bytes. Same source, different line endings, different digest. See
`expected_bcb32a9/NOTE.md` for the measured byte counts.

Reading: Windows checkout, not #13/#14/#16.

---

## 5. Reproduce test modules

```
$ python -m unittest tests.test_probe_section9 tests.test_section_nine \
      tests.test_validate_card tests.test_interpret
EXIT_CODE=0
.............................................................................................
----------------------------------------------------------------------
Ran 93 tests in 10.783s

OK
```

93 tests, 0 failures, 0 errors, 0 skips. These tests write to a temporary directory;
`git status --porcelain` after the run still showed only
`?? docs/research/section9_adversarial/rerun_2026-09-17/`.

Note on comparability: this is the four-module command from his `README.md` §Reproduce. His
`logs/FINAL_TESTS.md` receipt does not record a separate count for that four-module subset — it
records a broader 16-module regression suite (`Ran 613 tests ... OK (skipped=2)`) at `bcb32a9`,
which needs `matplotlib`/`scipy-stack` and is outside the scope assigned to this baseline task.
So the 93 above is a same-command figure on `b056397`, not a figure differenced against a
recorded `bcb32a9` value.

Full capture: `observed_b056397/tests_output.txt`.

---

## 6. Why nothing drifted — per-PR reading

One line each, from `git diff --name-only <merge>^1..<merge>`:

| PR | Commit | Files touched | Touches the measured set? | One-line reading |
|---|---|---|---|---|
| #13 MVP3 Human-GEM | `79eff72` | 36, all under `MVP3/` plus `.gitignore` | No | **Already present at his baseline** — `git diff --name-only bcb32a9 79eff72` returns 0 files, i.e. `bcb32a9` *is* the `feature/mvp3-human-gem-integration` tip ("MVP3: integrate pinned Human-GEM context") and its tree is identical to the merge commit, so #13 is not new relative to his run. |
| #14 timeline lifecycle | `25defeb` | 37, all under `demo/genetic-insights/` and `docs/planning/` | No | Touches the Genetic Insights demo viewer and its recordings; no file on the card/renderer/validator path. |
| #15 docs | `b6f6f3d` | 1: `docs/communications/VIDEO_2MIN.md` | No | Documentation only. |
| #16 MVP2 literature | `55bd8e0` | 32, all under `MVP2/` plus `requirements.txt` | No | Adds a Europe PMC search/screening layer under `MVP2/`; its only root-level effect is one added dependency line (`openpyxl>=3.1`, commit `b4536be`). |

The complete set of changes outside the research bundle, `MVP2/` and `demo/`:

```
$ git diff --name-status bcb32a9..HEAD -- . ':(exclude)docs/research/section9_adversarial' \
      ':(exclude)MVP2' ':(exclude)demo'
M	docs/communications/VIDEO_2MIN.md
M	docs/planning/GENETIC_INSIGHTS_TIMELINE_HANDOFF.md
M	docs/planning/GENETIC_INSIGHTS_TIMELINE_REFERENCE.md
M	requirements.txt
A	scripts/probe_section9.py
A	tests/test_probe_section9.py
```

(The two added files are his own harness, landed by PR #17.)

Reading: the four merged PRs and the measured file set are disjoint, so the absence of drift is
consistent with the code. Stated the other way — and this is a coverage fact, not an
interpretation of it — **the harness's measured boundary as it stands does not reach any file
that #13, #14 or #16 added.** What that implies for the three uncovered surfaces is for the
Reverify and new-probe phases.

---

## 7. Carry-forward for the Reverify phase

Measured facts only:

1. Every artifact Zipeng's eight findings (F1–F8) cite is reproduced byte-for-byte on
   `b056397`. The `section9_outputs/` and `full_cards/` text backing F1, F3, F6 and F7 is
   unchanged; the `raised` outcome backing F8 (`R07`,
   `AttributeError: 'object' object has no attribute 'redacted'`) reproduced identically; the
   `V0`–`V6` rule matches backing F2, F4 and F5 are unchanged.
2. `R01` reproduced as `printed`, `rules=none`, so the reachable form of the A1 result
   (token-free model prose through the real parser and both gates) still holds on current `main`.
   The README's reachability caution therefore still applies verbatim; nothing in this re-run
   licenses restating A1 as object injection.
3. No observation in this baseline re-run contradicts his report. No number in his report needed
   to be restated.
