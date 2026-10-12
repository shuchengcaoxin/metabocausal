# Re-run results — Section 9 adversarial study at `b056397`

Measured on `b05639721b07345612bba4ebf66f989805b9703c` (the then-current `origin/main`,
post #13/#14/#15/#16/#17), Python 3.12.10, Windows-11-10.0.26200-SP0. No network, no
provider credential. Every row below is backed by a saved command output in this directory.
Claims that did not survive independent refutation are in Appendix A, not in these tables.

---

## Table (a) — Harness drift, per changed case

**Zero of the 51 cases changed outcome.** `python scripts/probe_section9.py` exited `0`
with `all_expectations_met: true`. This table therefore has no rows, and the summary that
replaces it is below. Full write-up: [baseline/DRIFT.md](baseline/DRIFT.md).

| case | outcome at `bcb32a9` | outcome at `b056397` | which PR explains it |
|---|---|---|---|
| *(none)* | — | — | — |

| Metric | `bcb32a9` (his committed artifacts) | `b056397` (this run) | Same |
|---|---|---|---|
| cases | 51 | 51 | yes |
| printed | 31 | 31 | yes |
| blocked | 17 | 17 | yes |
| bypassed | 2 | 2 | yes |
| raised | 1 | 1 | yes |
| `all_expectations_met` | true | true | yes |
| exit code | 0 | 0 | yes |
| rows differing in **any** field | — | 0 of 51 | yes |
| `artifacts/section9_outputs/` differing | — | 0 of 33 | yes |
| `artifacts/full_cards/` differing | — | 0 of 31 | yes |

Fields diffed per row: `case_id`, `category`, `attack`, `construction`, `pair`,
`reachability`, `gate_one`, `outcome`, `expected`, `matched_rules`, `expectation_met`,
`notes`. Method: parse
`git show HEAD:docs/research/section9_adversarial/artifacts/results.json` against this run's
`results.json` and compare every field of every row.

Of the 69 artifact files, 67 are identical under LF normalisation and 2 differ. Neither is
a case outcome.

| File | What differs | Reading |
|---|---|---|
| `run.log` | two hunks only: the command/cwd/`git_head`/`git_branch` header and the output-path footer. All 51 result lines byte-identical to his. | interpreter path and revision |
| `manifest.json` | `generated_at_utc`, `python`, `platform`, `git_head`, `git_branch`, `git_status`, Windows backslashes in the `hashes` keys, and all 10 input hashes. `cases`, `outcomes`, `all_expectations_met`, `network_used`, `provider_api_used`, `command`, `model_path_method` unchanged. | Windows checkout |

`results.csv` needs one line of its own: this run's output is byte-identical to the `HEAD`
blob (`3d7338bfd053f05d…`). The 52-byte delta against the pre-run snapshot is CRLF-vs-LF
from `core.autocrlf=true` on checkout, proven by byte counts (blob len 10084, CRLF 0, bare
LF 52; snapshot len 10136, CRLF 52, bare LF 0).

The ten hash differences are not code changes. Every measured input is byte-identical at
Git-blob level between `bcb32a9` and `b056397` — `data/demo_card_inputs.json`, `render.py`,
`validate_card.py`, `llm/__init__.py`, `llm/base.py`, `llm/interpret.py`, `llm/registry.py`,
`prompts/interpretation.md`, `scripts/interpretation_fixtures.py` and reference-only
`data/1a_sample.json` — and each matches the hash his manifest recorded. Independently,
`git diff --name-only bcb32a9..HEAD -- data/ prompts/ llm/ render.py validate_card.py ledger.py`
returns empty. The harness itself is the one he ran: `HEAD` blob sha256 `a1cb309bcf…`,
equal to his recorded value.

The four PRs and the harness's measured file set are disjoint, which is why nothing drifted.
Stated the other way, and this is the coverage fact that motivates Table (c): **the
September 16 harness does not reach any file that #13, #14 or #16 added.**

Also re-run: `python -m unittest tests.test_probe_section9 tests.test_section_nine
tests.test_validate_card tests.test_interpret` → `Ran 93 tests … OK`, exit 0.

---

## Table (b) — His F1–F8, re-measured

Every verdict below is a fresh measurement on `b056397`, not an inheritance from his report.
"Reachability" is the strongest path that was **executed** in this re-run; weaker or
unexecuted paths are named in the notes column so they cannot be quoted as the headline.

| ID | Finding at `bcb32a9` (2026-09-16 bundle) | Verdict at `b056397` | Reachability recorded this run | Notes and limits | Evidence |
|---|---|---|---|---|---|
| **F1** | The card-wide attestation overstates a token-membership and regex check as if the prose itself had been checked against the evidence. | **still holds** | `current_cli_surface` — new this re-run | `render.py urate\|gout --interpret --provider claude --model claude-opus-5`, run end to end through the CLI's own `__main__` with only `llm.interpret.complete` replaced by a fixed offline `Reply`, wrote a 32,141-character card whose Section 9 is the unsupported sentence followed by the attestation. He inferred this surface; here it is executed. `R01` (token-free prose through the real parser and both gates) reproduced. `S01/S02/S03/S05/S09`, which he labelled `model_path_equivalent`, were sent through gate one as well and all five are accepted and printed under the attestation, so they are recorded on the model path; `S03/S09` are State C, so the attestation also prints on an evidence-gap run. `slack_app.py` calls the same `llm.interpret.interpret` and `render.render_card` (`slack_app.py:996-1008`, `:926`) and its blob is unchanged from `bcb32a9`, but it needs Slack tokens and a live provider and was **not executed** — unchanged code path, not a measured surface. `A01` remains `harness_only` and is not claimed as an injection surface. Not measured: prompt-injection susceptibility and stochastic provider behaviour. | `reverify/F1/` |
| **F2** | Numeric membership is not bound to a field or semantic role: identifier digits, dates and list lengths can be relabelled as scientific quantities. | **still holds** | `current_model_path` | `T01/T02/T03` as he ran them stay `model_path_equivalent`. The same three claims serialised as model JSON into a fixed offline `Reply`, through the real `llm.interpret.interpret()` (parse_fields + gate one) and then the renderer: `T01` `accepted=True`, `fields={'headline': 'The effect size is 17775.'}`, gate-one findings `[]`, **printed**; `T02` the same with `2026.`; `T03` the same with `4.`. The footer then carries the real model label. This is the code both deployed surfaces run (`render.py:2502-2519`; `slack_app.py:926`). The precondition is that the model itself writes the sentence; nothing external injects it. The `ai_runs/02` inline snippets and the synthetic list-length runs are direct `validate_card.validate()` calls on hand-written run dicts — `harness_only` mechanism evidence, cited as mechanism, not as a reachable path. | `reverify/F2/` |
| **F3** | Schema-free indexing trusts values absent from both the model digest and the rendered evidence sections, so the footer can make a literally false visibility claim. | **still holds**, and splits into two claims of different strength | claim 1 `current_validator_path_with_synthetic_run_field` (unchanged from his label); claim 2 `current_cli_surface` | **Claim 1** (a hidden run field whitelists a number and the footer then lies, his `R06`): both gates are the real deployed code, only the provider call stubbed; what is synthetic is the extra run key. `render.py --interpret` (`render.py:2440-2519`) builds the run itself and hands the same dict to `interpret()` and `render_card()`, and the Slack caller likewise — neither accepts an externally supplied run field. Internal / future-deserialization surface, **not** a current CLI or Slack injection point; the TOCTOU variant is internal misuse only. **Claim 2** (the validator trusts values absent from both the digest and the rendered sections) needs no synthetic field: on the real CLI run, `validate_card.source_index()` walks the whole run (22 MR rows at full precision, caveats, keys, notes), `llm/interpret.build_digest()` shows the model 8 rows, and Section 3 prints a capped table rounded to 3–4 significant digits. **9 of 13 distinct retrieved `b` values are trusted by both gates while appearing in neither the digest nor anywhere in the rendered card.** Limit: with a live provider the model only receives `build_digest()`, so emitting one of those hidden values needs chance or prompt injection, neither measured. The validator/renderer defect is reachable on the current CLI; the end-to-end exploit with a real model is not demonstrated. | `reverify/F3/` |
| **F4** | Sentence-wide negation/disclaimer exemptions can excuse a prohibited positive claim in another clause. | **still holds** | `current_cli_surface` — stronger than his label, newly measured | The four F4 payloads returned as model JSON pass `llm.interpret()`'s parser and gate one (`status=accepted`, `accepted=True`, 0 findings) and then gate two, and Section 9 prints with the full attestation. The same `S10` sentence then reached a real card through `python render.py "urate\|gout" --interpret --provider claude --model claude-opus-5`; only `llm.interpret.complete` was replaced, while argument parsing, `credential_from_env`, `interpret()`, `render_card()` and both gates ran unmodified. CLI stderr reported "section 9 written by claude-opus-5 and accepted by the validator". He recorded `S10/S11/S12/S14` as `model_path_equivalent`; that is upgraded here. Slack path: same code statically (`slack_app.py:996-1001`, `:926`), **not executed**. Not demonstrated: that a live provider spontaneously emits such a sentence. The defect is that the validator accepts it. | `reverify/F4/` |
| **F5** | Unicode normalization gaps can change meaning, including the sign of a coefficient, without producing a finding. | **still holds** | `current_model_path` for the sign flip — upgraded from his `model_path_equivalent`; `U03`/`U04` unchanged | `render.py:2501-2519` calls `llm.interpret.interpret(run, provider, model, credential)` and then `render_card(run, interpretation)`. The `F5-MP-unicode` case exercises that chain with only `llm.interpret.complete` replaced by a fixed offline `Reply`: gate one `status='accepted'` with zero findings, gate two zero findings, and the renderer printed the sign-reversed sentence into a full card. `llm/interpret.py` `parse_fields` does no Unicode normalization — it strips a code fence and calls `json.loads`; grep shows no `unicodedata`/`normalize` call. Trigger condition stated honestly: the model must write U+2212 MINUS SIGN instead of ASCII hyphen-minus. That is ordinary typographic behaviour in LLM prose, not attacker-controlled input, and no external injection channel is claimed. `U03` (NBSP) and `U04` (Cyrillic homoglyph) stay renderer-only. No hand-built `Interpretation` object is needed for the sign flip, so his `A1` caution does not apply to it. Slack: same call sites, not executed. | `reverify/F5/` |
| **F6** | Raw Markdown in model fields can create a forged heading/action block within Section 9 (his `S18`). | **still holds** | `current_model_path` — his `model_path_equivalent` label is now backed by a measured run | His `S18` row is by itself a `DirectCase`: a hand-built `SimpleNamespace` with `accepted=True`, gate one "not exercised". The identical payload serialised as model JSON was parsed by the real `llm.interpret.parse_fields`/`interpret()` and passed gate one ("gate one accepted: True", 0 findings), then re-validated and printed by `render.render_card` (gate two, printed). The JSON round trip preserves the embedded newline ("newline survived the parser: True"), so the forged heading comes out of the real parser, not a hand-built object. Both consuming surfaces emit the card as Markdown text — `render.py --interpret` (`render.py:2502-2519`) and the Slack shell (`slack_app.py:909-927`, which writes the same Markdown into `cards/` before upload) — so the forged heading lands in the artifact a reader opens. Limit that must stay attached: only the provider call is stubbed; whether a live provider can be induced to emit `\n## ` inside a field is prompt-injection susceptibility, which his REPORT.md records as unmeasured. No CLI/Slack object-injection claim is made. | `reverify/F6/` |
| **F7** | Unvalidated `metadata.model` text is appended to an otherwise validated section. | **still holds** | `harness_only` / future-deserialization boundary — **unchanged** from his label, and re-measured rather than inherited | The accepted path's only source of `metadata["model"]` is `llm/registry.py` `run_metadata()` → `spec.model`, and `resolve()` (`llm/registry.py:145-171`) looks the id up in a fixed `REGISTRY` dict (measured contents: anthropic `claude-haiku-4-5`, `claude-opus-5`, `claude-sonnet-5`; openai `gpt-4.1`, `gpt-4o`; google `gemini-flash-latest`, `gemini-flash-lite-latest`). Probed with an injected id, `interpret(model='claude-opus-5\n\nUnvalidated expert approval.')` returns `accepted: False`, `status: unavailable`; metadata does carry the raw string, but `accepted=False`, so the renderer emits "Model reasoning pending integration (section 1F)." — outcome **blocked**, injected text in Section 9 `False`. On the model path, a reply carrying both `metadata.model` and a top-level `model` key gives `accepted True`, `metadata['model'] == 'claude-opus-5'`: `parse_fields` drops unknown keys and `interpret.py:306` only adds usage/stop_reason, so the provider cannot set the label. Consumers on current `main` are exactly two: `render.py:1909` (into the card) and `llm/interpret.py:72` `Interpretation.note()`, which `render.py:2517` prints to stderr. So: printed in the harness form, blocked on every measured deployed surface. Do not describe it as a deployed injection. | `reverify/F7/` |
| **F8** | A malicious dict subclass can make `validate()` raise despite its never-raises contract; `render_card()` contains the exception (robustness loss, not prose leakage). | **not carried forward** — rejected at verification | — | The mechanism reproduces (see Appendix A.1), but the finding as stated does not survive: both real call sites contain the exception, and `parse_fields()` returns an exact builtin `dict`, so no deployed input can deliver a subclass. Full measurement in Appendix A.1. | `reverify/F8/`, `verify_scratch/F8/` |

**Summary: 7 of 8 still hold on current `main`. 0 were fixed by #13, #14 or #16. 1 (F8) was
rejected at verification.** Three findings had their recorded reachability raised on
evidence (F1, F4, F5 — and F6's existing label is now backed by a run); F7's was left
unchanged at his own weaker label; F3's split into a weaker and a stronger claim rather
than being quoted at its strongest.

---

## Table (c) — New-surface findings

Severity uses the parent study's taxonomy: **defect**, **scope_limit**, **observation**.
Reachability is recorded per finding and must be preserved when quoting.

### (c.1) Genetic Insights timeline — `plots.plot_genetic_insight` and PR #14's lifecycle bundle

21 `GI` figure cases and 10 `LC` lifecycle cases. 20 of 21 figures drew; one (`GI21`) raised.
The figure carries no model prose — these findings are about what its labels and counts
*claim*. PR #14 did not touch `plots.py`, `render.py`, `slack_app.py` or `tools/`
(`git show 25defeb --stat -- plots.py render.py slack_app.py tools/` produces no output), so
the live per-run figure was neither probed in September nor covered by the lifecycle fix.

| ID | Severity | Finding | Reachability | Cases |
|---|---|---|---|---|
| T1 | defect | The timeline credits the registry for a stopping reason and a status the registry never supplied. | Any run whose dossier carries a status or `why_stopped` the registry record does not. Ordinary retrieved Open Targets data reaching the Slack timeline button — not a user-typed input and not object injection. | GI03, GI04 |
| T2 | defect | The stopped/terminated state is an unanchored substring test on a retrieval-controlled status string. | Any report whose free-text status contains a terminal word in any position. Open Targets status strings are free text: retrieval-controlled, not user-controlled. | GI15 |
| T3 | defect | The undated-count note asserts something about the registry for reports the registry was never asked about. | Any dossier with a clinical report lacking an NCT id. Open Targets label and regulatory records carry none, and `_nct_id` deliberately returns `""` for them, so this fires on ordinary data. | GI02, GI18 |
| T5 | defect | `trial_phase`, `status` and the GWAS dataset label carry no character budget, contradicting `plots.py`'s own stated contract. | `GI20` needs **no** adversarial input: five trials of one drug starting in the same year. `tools/trials.py`'s own docstring records 19 clinical reports on one drug in real Open Targets data. | GI08, GI15, GI17, GI20 |
| T6 | defect | The lane label rolls a cross-indication max stage onto a figure that names one disease, and that same number orders and cuts the lanes. | Every run. Open Targets `maxClinicalStage` is cross-indication by definition; no adversarial input needed. | GI13, GI14 |
| T7 | defect | A marker drawn on a completion year is indistinguishable from one drawn on a start year. | Ordinary registry data: a record with a primary completion date and no start date. | GI12 |
| T8 | defect | One retrieved string changes the drawn glyphs, and a malformed one denies the whole figure, because matplotlib parses dollar signs as mathtext. | A retrieved drug name or registry stopping reason containing a balanced pair of dollar signs; cost figures in a `why_stopped` are the plausible vector. Robustness loss in the F8 sense, not prose leakage. Not a user-typed input. | GI07, GI21 |
| T9 | defect | The year axis prints two decimal places whenever every drawn year is the same year. | Not adversarial at all: one drug, one report, a retrieved start year and no completion date. A plain defect on a never-probed surface. | GI19 |
| L2 | defect | An event whose stage is not in `display_order` is silently dropped from the rendered timeline. | The viewer's "Open snapshot" file input accepts an arbitrary local bundle and is exercised by `qa_viewer.cjs`; a bundle author can also write the stage directly. Not a network-reachable injection. | LC03 |
| L3 | defect | PR #14's required-stage check is a label-presence check, not an evidence check. | Bundle authoring, and the loaded-snapshot path accepts the same bundle. | LC04, LC05 |
| L6 | defect | The chronology guard compares date strings; ISO 8601 basic format rejects a correct order and accepts a reversed one. | Bundle authoring. The viewer's file-input path rejects the date format, so this does not reach a loaded snapshot. | LC07, LC09, LC10 |
| T4 | scope_limit | Truncating the stopping reason at 40 characters can invert its meaning. | Any registry `why_stopped` longer than 40 characters. | GI05 |
| L4 | scope_limit | The lifecycle guarantee is opt-in, and there is no missing-stage display at all. | The viewer's file input; the superseded v1 CETP bundles that PR #14 replaced have exactly this shape. | LC02 |
| T10 | observation | No plausibility floor on a year; an implausible one rescales every real marker. | `report['year']` and the exposure year. `tools/trials.py` records that `report['year']` is null on every report this project has seen, so this needs upstream data that has not been observed. | GI10, GI17 |
| T11 | observation | An impossible interval is dropped rather than reported. | Registry data quality; not an injection. | GI11 |
| T12 | observation | One trial reached through two effector genes is drawn as two lanes and counted as two reports. | Any drug whose target set includes two of the run's effector genes. | GI16 |
| L1 | observation | PR #14's central lifecycle check does fire — positive verification. | Build time, and the viewer's "Open snapshot" file input. | LC06 |
| A1 | observation | Markdown emphasis in a retrieved `why_stopped` reaches the card — adjacent surface, recorded not claimed. | A retrieved Open Targets field, not model prose. | GI06 |

Rejected on this surface: T13, L5 (Appendix A.2, A.3).

### (c.2) Human-GEM arm — MVP3 / PR #13

30 cases, `expectation_failures: []`. `construction` is the reachability claim: `real_module`
is a deployed path, `poisoned_index` is the real adapter over a modified source fixture
(`local_index_config`), and `forged_envelope` is a harness construction in the `A1` sense.

| ID | Severity | Finding | Reachability | Cases |
|---|---|---|---|---|
| GEM-D2 | defect | Human-GEM candidate symbols let V5 accept effector-gene nominations on runs that nominated no genes. | `current_model_path` — the real adapter's own output through the same two gates. Gate one `accepted=True`, gate two findings `[]`, printed; the counterfactual without the gem envelope is `rejected` and blocked by V5 on `GCSH`/`GLDC`. The same card says in Section 5 that the atlas nomination layer was not queried, so the accepted sentence contradicts the deterministic section above it. | GV03 |
| GEM-O6 | scope_limit | No Human-GEM index ships in the repository, so a fresh checkout renders the Section 7 error branch on every card. | `deployed_path` — the default state of a fresh checkout. `MVP3/data/index` contains only `.gitkeep` and `README.md`; `MVP3/data/model` has no `Human-GEM.yml`. | GH04 |
| GEM-O3 | observation | A Cyrillic homoglyph gene symbol prints beside the Latin dossier gene and the overlap sentence does not fire. | `local_index_config` — the same trust boundary as a poisoned index, not a deployed input. | GI06 (gem probe) |

Rejected on this surface: GEM-D1, GEM-D3, GEM-D4, GEM-D5, GEM-O1, GEM-O2, GEM-O4, GEM-O5
(Appendix A.4–A.11). Eight of eleven candidate claims did not survive; the three above did.

### (c.3) MVP2 literature data layer — PR #16

16 probe cases across runtime coupling, card prose, tests, manifests, records, extraction,
ledger and merge. All eight probe scripts exited 0.

| ID | Severity | Finding | Reachability | Case(s) |
|---|---|---|---|---|
| M4 | defect | On shifted source rows the extractor writes an odds ratio into `ci_high` and a confidence bound into `p_value`. | Data layer only (see M1): 9 rows in `new_unique_pairs.csv` and 18 in `new_pair_records.csv`. | L05b, L06b |
| M5 | defect | `normalize()` erases `%`, so ratio and absolute exposures collapse into one pair identity. | Data layer only: affects 1,003 of the 9,801 kept pair keys and every downstream count derived from them. | L05d, L08b |
| M6 | defect | Every appended row in the merged candidate table claims exactly one supporting source row. | Data layer only; the merged candidate table is the artefact a future integration would read. | L08b |
| M7 | defect | A search-run manifest records a sha256 the repository cannot produce for the file it names. | Anyone verifying the bundle; it fails on an LF checkout, which is what a clean clone on Linux or macOS produces. Measured: the `pair_batch` manifest claims `5e7411e6…`, which is the CRLF hash; the committed blob is `f3c7ff09…`. | L04a |
| M10 | scope_limit | `MVP2/tests` cannot run with the documented runner in this environment; under an offline shim all 17 pass. | Any contributor in this environment. The shim result is a harness substitute and is **not** presented as "the suite passes under pytest". | L03 |
| M1 | observation | No MVP2 output reaches the card path — zero runtime coupling. | None: there is no runtime path from MVP2 to `pipeline`/`render`/`classify` on `b056397`. 93 runtime Python files scanned; 0 MVP2 imports, 0 MVP2 path literals, 0 `sys.path` inserts, `get_literature_mr in TOOLS = False`. | L01 |
| M2 | observation | The "MVP2 is not integrated" disclosure is printed on State C cards only. | Printed on every State C card rendered from the frozen fixtures; absent from every State A and State B card (by state: A 0/1, B 0/1, C 1/1). | L02 |
| M9 | observation | One of 9,801 kept pairs has a search record (0.0102% coverage); that one record is sound. | Not a reachability claim — a coverage fact about the screening ledger. | L07a |
| M11 | observation | The counting and merging layer reproduces exactly — positive result. | n/a — a positive reproduction result. | L04b, L05a, L07b, L08a |
| M12 | observation | An unset direction counts as forward. | Latent: 0 rows in the current data exercise it. | L05c |

Rejected on this surface: M3, M8 (Appendix A.12, A.13).

### New-surface totals

| Surface | defects | scope limits | observations | confirmed | rejected |
|---|---|---|---|---|---|
| Genetic Insights timeline | 11 | 2 | 5 | 18 | 2 |
| Human-GEM arm | 1 | 1 | 1 | 3 | 8 |
| MVP2 literature layer | 4 | 1 | 5 | 10 | 2 |
| **Total** | **16** | **4** | **11** | **31** | **12** |

---

## Appendix A — Rejected claims

Thirteen candidate claims were produced by the probes and then failed independent
refutation. They are recorded here so that nobody re-derives them, and so the ratio between
what was proposed and what survived is visible. **None of these is a finding.** Where part
of a claim reproduced, that part is stated, because a half-true claim is the kind most
likely to be quoted whole.

**A.1 — F8: "a malicious dict subclass makes `validate()` raise despite its never-raises
contract; `render_card()` contains it."** What reproduced: `validate()` does raise on a dict
subclass whose `items()` raises (`validate_card.py:546`), both docstrings do say "Never
raises.", and `render_card()` does contain it, printing the render-failure sentence instead
of the prose (`prose_printed: false`). What refutes the finding: the second real call site
contains it too. `llm/interpret.py:319` sits inside `_attempt()`, and `interpret()` wraps
`_attempt()` in `try/except Exception` at `llm/interpret.py:233-267`, so forcing the input
into the real path returns rather than raises — `accepted=False`, `status=unavailable`,
reason "The interpretation step failed unexpectedly (ValueError)", and the card prints the
pending sentence. And `parse_fields()` returns an exact builtin `dict`
(`exact builtin dict = True`), so no CLI or Slack input can deliver a subclass in the first
place. There is no reachable input and no uncontained failure; what remains is a docstring
that overstates one function in isolation. Evidence: `verify_scratch/F8/independent_run.log`,
`reverify/F8/run.log`.

**A.2 — T13: "homoglyph drug names are neither normalized nor distinguished."** The
"not normalized" half reproduces. The "not distinguished" half does not, and the fixture
itself is mis-specified: in `toрсеtrаpib` the substitute at position 2 is U+0440 CYRILLIC
SMALL LETTER ER, whose closest Latin shape is `p` (0.0% mismatch against `p`, 57.3% against
the `r` it replaced) — so a reader sees `topcetrapib`, not the same word. Even with a
corrected fixture using only genuine homoglyphs (U+0441, U+0435, U+0430), the rendered lane
labels differ: 386 differing pixels, 26.5% ink moved. Evidence:
`verify_scratch/T13/glyphs_t13_stdout.txt`, `corrected_fixture_stdout.txt`, and the saved
crops.

**A.3 — L5: "the shipped evacetrapib page orders its stage groups against its own dates,
which PR #14's own spec forbids."** The page renders its groups in exactly the declared
`display_order` (`human_genetics, preclinical, clinical, later_genetics, class_status`), and
that order is thematic, not chronological. The `later_genetics` range (2012–2017)
overlapping `clinical` (2012–2017) is the declared design, and the bundle says so in the
event text ("this evidence preceded the trial start"). Nothing measured shows the page
violating a spec. Evidence: `verify_scratch/L5/repro_l5.out.txt` (page sha256
`f3edc738a038…`), `byte_identity_check.txt`.

**A.4 — GEM-D1: "the Human-GEM arm multiplies the Section 9 validator's accepted number set
by ~24x, including effect-size-shaped decimals taken from EC codes."** The mechanism is
real and is already a measured probe row, but the quantifier is wrong: measured, the
accepted number set goes from 8 to 294, a factor of about 37, not 24. The EC-code clause is
also a different case (`GV07`), which stands on its own. A wrong multiplier in a headline is
worse than no multiplier. Evidence: `new_probes/gem/artifacts/RESULTS.md` `GV01`
(`numbers_without_gem: 8`, `numbers_with_gem: 294`), `verify_scratch/GEM-D1/`.

**A.5 — GEM-D3: "the card-wide attestation is false on any card whose Section 9 quotes a
Human-GEM value from unrendered envelope depth."** The mechanism reproduced — the value is
accepted by both gates and printed — but the universal claim does not. In the reproduction,
the quoted number does appear on the full card (`lines of the FULL card containing the
number: 1`), so "false on any such card" is not what was measured. The measurable statement
is the narrower one already carried as F3 claim 2. Evidence:
`verify_scratch/GEM-D3/run1.txt`.

**A.6 — GEM-D4: "`build_digest` omits the gem arm from its 'arms that did not run' defaults,
so the model is never told the Human-GEM arm exists when it was switched off."** The first
clause is true: the tuple at `llm/interpret.py:144` is
`("mr", "instruments", "outcomes", "catalog", "coloc", "atlas", "dossier")` and does not
contain `"gem"`. The conclusion is false: `pipeline.py:617` appends `_GEM_OFF_NOTE` to the
run's notes, and `build_digest` copies `run_notes` from `run["notes"]`
(`llm/interpret.py:140`), so the model *is* told, by a different field. Evidence:
`verify_scratch/GEM-D4/`, `new_probes/gem/artifacts/RESULTS.md` `GH02`, `GV05`.

**A.7 — GEM-D5: "Section 7's cap line reports the tool's internal 100-record cap as if it
were the total, contradicting the count printed two lines above."** Both numbers print, and
the wording distinguishes them: the head line says "123 reaction-linked gene candidate(s)"
and the cap line says "showing 8 of 100 **returned** candidate(s)". 100 is presented as what
the tool returned, which is accurate. That the two numbers sit two lines apart without an
explanation is already carried as the `GI08` `contradiction` outcome; the "as if it were the
total" reading is not what the text says. Evidence: `verify_scratch/GEM-D5/section7_gi08.md`.

**A.8 — GEM-O1: "the GPR string is the one Section 7 field with no display cap."** It is not
the one. Measured on the same section: a 2,006-character `model_version` printed in full
(head line 2,130 characters) and a 1,205-character gene symbol printed in full (candidate
line 1,271 characters). `_text()` and `_or_unknown()` return 5,000 characters for a 5,000
character input. The only caps in Section 7 are `MAX_GEM_REACTIONS_SHOWN = 5` and
`MAX_GEM_CANDIDATES_SHOWN = 8`, which cap list length, not field length. Evidence:
`verify_scratch/GEM-O1/refute_output.txt`.

**A.9 — GEM-O2: "retrieved Human-GEM strings are not Markdown-escaped, but the S18-style
heading forgery and the GPR code-span break-out are both blocked."** The two "blocked" halves
reproduce — `GI03`'s newline is flattened, so `## 12. Confirmed genetic effectors` lands
inline inside a list item rather than as a heading, and `GI05` is refused at index build with
`ValueError: Unsupported GPR syntax at character 15`. The framing does not survive, because
the same surface does pass other Markdown through unchanged (`GI04`: a Markdown link plus an
HTML comment, `rendered_verbatim`). Reporting "both blocked" as the finding would state a
reassurance the evidence does not support. The three underlying outcomes are already rows in
the probe's own table. Evidence: `verify_scratch/GEM-O2/gi03_section7.md`,
`gi05_build_result.txt`, `gi04_section7.md`.

**A.10 — GEM-O4: "the honest-absence paths render exactly as written, and Section 7 itself
never reads as genetic evidence on honest input."** The first half is a positive
reproduction and is kept as part of the `GH01`–`GH07` rows. The second half is a universal
negative about how prose reads, which is not a measurable property, and the independent run
shows the honest branches depend on a modified source fixture in at least one case (`GH07`
rewrites a model species' `metChEBIID` and rebuilds the index). Evidence:
`verify_scratch/GEM-O4/opus_indep_check.out.txt`.

**A.11 — GEM-O5: "Section 5/7 branch selection reads two fields and cross-checks nothing,
but the field combinations that exploit this are harness constructions."** The exploit half
is already conceded in the claim, and the reachable half was re-tested and failed: the same
combination can be produced from the real module and from the deployed CLI's own
`--include-hubs` flag, where it is a documented operator choice, not an unchecked branch.
All eight assertions pass on the real-module reproduction and the section text is
byte-identical to the forged-envelope case after timestamp scrubbing, which makes the
"harness construction" framing wrong in the other direction. Evidence:
`verify_scratch/GEM-O5/repro_ge06_real_module.out.txt`,
`repro_ge06_shipped_flag.out.txt`.

**A.12 — M3: "every extracted `ukb_mapping_2025` confidence interval is inverted
(`ci_low > ci_high`)."** The mechanism and the three cited counts reproduce; the "every"
does not. Measured: `candidate_pairs.csv` 16,944 inverted and **498 not inverted** of 17,442
`ukb_mapping_2025` rows; `new_pair_records.csv` 14,509 inverted and 18 not, of 14,527;
`new_unique_pairs.csv` 6,914 inverted and 9 not, of 6,923. The row-level observation stands
as the probe rows `L06a` and `L08c`; it is not carried into Table (c.3) as a finding,
because the quantifier is the whole of what the claim asserted. The neighbouring
column-shift defect, which does survive, is M4. Evidence:
`verify_scratch/M3/independent_refutation_check.out`.

**A.13 — M8: "`MVP2/data/**` is the one evidence tier whose bytes `.gitattributes` does not
pin."** It is not the one. The root `.gitattributes` pins `archive/**`, `provenance/**`,
`MVP2/literature/seeds/**` and `MVP2/literature/studies/**`; everything else is
`text: unspecified`, including `MVP3` (30 files), `data` (2 files), `docs` (111 files),
`llm` (9 files) and every root-level Python module. The verifiable consequence — one of
seven manifest hashes failing on an LF checkout — is carried by M7. Evidence:
`verify_scratch/M8/pin_survey.txt`, `m8_repro_out.txt`.

---

## What was deliberately not done

- Nothing was pushed, and no measured behaviour was patched, on the same reasoning his
  DESIGN_JUDGMENT.md gives: patching invalidates the evidence the paper cites.
- His bundle was not modified. Where the harness rewrote his tracked files, the outputs were
  copied into `baseline/observed_b056397/` and `git restore` put his bytes back.
- The Slack surface was not executed; it needs tokens and a live provider. It appears in
  Table (b) only as a code-reading of an unchanged file.
- No network call was made and no provider credential was used, so no claim here depends on
  what a live model would actually write.
