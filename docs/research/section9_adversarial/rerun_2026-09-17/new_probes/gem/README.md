# Human-GEM arm probes (MVP3 / PR #13)

New-surface probes added by the 2026-09-17 re-run. The 2026-09-16 study never measured
the Human-GEM biochemical-context arm, because that arm was merged after its baseline
`bcb32a9`. Everything here measures `b056397`; nothing here repairs measured behaviour.

## Surface

- `tools/gem.py` `map_metabolite_to_genes_gem` over `MVP3/src/gem.py`.
- `pipeline.run_pair` wiring and its honest-absence notes `_GEM_OFF_NOTE`,
  `_GEM_NO_ID_NOTE`, `_GEM_FAILURE_NOTE`.
- Card Section 7 "Via-enzyme protein evidence" and the Human-GEM block inside card
  Section 5 "Effector genes by source" (`render.MAX_GEM_CANDIDATES_SHOWN` = 8,
  `render.MAX_GEM_REACTIONS_SHOWN` = 5).
- Whether Human-GEM values widen what `validate_card.validate` accepts in the
  model-written Section 9.

## Reproduce

Python 3.12, from any directory. No network and no provider credential.

```bash
python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/gem/probe_gem.py
```

The script regenerates `artifacts/` and exits non-zero if any case's outcome or any of
its per-case assertions changes. 30 deterministic cases. It writes only inside this
directory: the pipeline's ledger directory is redirected to a temporary directory and
every index it builds is temporary, so no repository file is touched.

Re-running is byte-identical apart from `manifest.json`'s `started_at` / `finished_at`.

## Contents

- `probe_gem.py`: the harness. Its module docstring defines the three constructions.
- `artifacts/RESULTS.md`: result table plus every per-case observation.
- `artifacts/results.csv`, `artifacts/results.json`: machine-readable, one row per case,
  each row carrying its own construction and reachability.
- `artifacts/section_outputs/<case>.md`: the exact rendered Section 5 / Section 7 /
  Section 9 text for each case.
- `artifacts/full_cards/<case>.md`: the complete card for each case.
- `artifacts/envelopes/<case>.json`: the gem envelope each case rendered.
- `artifacts/manifest.json`: revision, environment, code and input hashes, outcome
  counts and the list of expectation failures (empty on a passing run).

## Reading the rows

`construction` says how the input was obtained and is the reachability claim:

- `real_module` - the real adapter over an index built by `MVP3.src.build_index.build_fixture`
  from the checked-in source excerpt. A deployed path.
- `poisoned_index` - the real adapter over an index built from a MODIFIED source fixture.
  `write_index` computes the manifest checksum from the bytes it is handed, so the
  checksum binds index to manifest, not index to upstream Human-GEM; whoever can write
  the index pair or set `METABOCAUSAL_GEM_INDEX` chooses what Section 7 prints. The
  pinned full-model path is different - it verifies source bytes against
  `MVP3/data/model/source.lock.json`. `MVP3/data/index/README.md` states this limit.
- `forged_envelope` - a hand-edited envelope placed in `result["envelopes"]["gem"]`.
  A harness construction, like A1 in the 2026-09-16 study, not a deployed input. These
  rows say what the renderer does with a field combination the current module cannot
  emit; they are not claims about a reachable exploit.

`outcome` vocabulary, alongside the 2026-09-16 study's `printed` / `blocked` (which keep
their meanings there: the renderer emitted Section 9, or it left the fixed pending
sentence):

| outcome | meaning |
|---|---|
| `rendered` | the honest mapped path printed its section |
| `absence_declared` | the card stated the arm did not run, or the id did not map |
| `error_declared` | the card stated the lookup failed and quoted the reported detail |
| `suppressed` | the hub/currency policy branch withheld candidate detail |
| `rendered_verbatim` | the injected string reached the card unchanged |
| `dropped_from_section_5` | the row was filtered out before Section 5 printed |
| `flattened` | whitespace was collapsed, so no new Markdown block was created |
| `blocked_at_build` | the index build refused the input |
| `declared` | a source-annotation defect was labelled rather than smoothed over |
| `contradiction` | the card printed two numbers about the same list without saying which is which |
| `capped_and_declared` | the list was cut to eight and the cut was stated with both numbers |
| `error_hidden` | an error detail present in the envelope never reached the reader |
| `measured` / `arm_omitted` | a measurement row, not a penetration |

## Normalisation

Saved artifacts replace ISO timestamps with `<timestamp>` and `data.local_lookup_ms`
with `<local_lookup_ms>`. Assertions run on the raw text. The one counting case (GV01)
additionally removes wall-clock stamps, the elapsed-milliseconds field and the dated
ledger path from the run before indexing it, because those digits would otherwise change
the totals between runs; `probe_gem.stabilise` is that function and no other case uses it.
