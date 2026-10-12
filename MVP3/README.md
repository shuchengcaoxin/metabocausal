# Workstream D — Human-GEM biochemical context

Given a ChEBI identifier, retrieve recorded metabolic reactions and their GPR genes
from a **pinned local Human-GEM index**. Output is biochemical context, not MR,
demonstrated disease mediation, a target ranking or a clinical recommendation.

This folder implements the Human-GEM module described by the repository's Task 05.
The shared adapter is `tools/gem.py`; `pipeline.run_pair()` stores its separate
biochemical envelope and `render.py` presents it without changing A/B/C. See
[HANDOFF.md](HANDOFF.md) for integration boundaries and remaining Gate 2 work.

## Quick start in this workspace

The already prepared full source/index paths and acceptance receipts are documented
in [the work log](logs/gem/WORK_LOG.md). Python 3.10+ is sufficient for lookup and
unit tests. Only the source preparation step requires PyYAML; no COBRA solver,
MATLAB, model API key or GPU is required for this lookup-only task.

From the repository root:

```bash
# Offline module and integration tests. No API calls.
python3 -m unittest -v MVP3.tests.test_gem tests.test_mvp3_integration tests.test_1e

# Query the already built full index, optionally append a standalone ledger.
python3 -m MVP3.src.gem CHEBI:15428 \
  --index /scratch/zpoints/MetaboCausal/human-gem-v2.0.0-UJimLC/human-gem-2.0.0.json \
  --ledger /scratch/zpoints/MetaboCausal/glycine-gem.ledger.jsonl
```

To prepare elsewhere, choose new source/index locations. The following reuses this
workspace's isolated Python 3.12.4 environment (load the same CVMFS stack first):

```bash
module load StdEnv/2023 python/3.12.4
source /scratch/zpoints/MetaboCausal/human-gem-v2.0.0-UJimLC/venv/bin/activate

# Explicit downloads, checksum verified; cached files are reverified, never replaced.
python -m MVP3.src.fetch_model --output-dir /scratch/zpoints/MetaboCausal/my-gem-source

# Use a NEW output path: the builder will not overwrite an existing artifact.
python -m MVP3.src.build_index \
  --source-dir /scratch/zpoints/MetaboCausal/my-gem-source \
  --output /scratch/zpoints/MetaboCausal/my-gem-index.json

# Small source-backed fixture alternative; visibly labelled and NOT full coverage.
python -m MVP3.src.build_index \
  --fixture MVP3/tests/fixtures/gem/source_excerpt.json \
  --output /scratch/zpoints/MetaboCausal/my-gem-fixture-index.json
```

For a new Alliance environment, follow `module spider python` and the matching
module prerequisites, create an isolated venv, check `avail_wheels PyYAML` and use
the wheelhouse first. The source/lookup paths are configuration, not portable
hardcoded defaults to someone else's machine. Full generated files are ignored by Git.

## Public interface

```python
from MVP3.src.gem import map_metabolite_to_genes_gem, GemLookup

# Set METABOCAUSAL_GEM_INDEX to a prepared index path before this call.
envelope = map_metabolite_to_genes_gem("CHEBI:15428")

# Explicit per-instance configuration: no mutation of global credentials/state.
lookup = GemLookup("/path/to/index.json", hub_threshold=200,
                   hub_policy="suppress", max_reactions=200, max_candidates=100)
envelope = lookup.query("CHEBI_15428")
batch = lookup.map_many(["CHEBI:15428", "CHEBI_15428", "CHEBI:17191", "CHEBI:999999999"])

# Optional exact-name diagnostic: offers identities, never nominates genes itself.
choices = lookup.resolve_name("glycine")
```

For a file-based rerun, use `python -m MVP3.src.run_batch` with
`MVP3/examples/batch_input.json`. It writes one diagnostic per original input,
reuses duplicate normalized IDs, preserves the input snapshot ID and refuses to
overwrite an existing output.

Every single lookup returns the shared outer envelope:
`tool, args, source, url, retrieved_at, status, data, caveats`.

| Situation | Status | Important detail |
| --- | --- | --- |
| Exact ChEBI mapping, including a reaction with no GPR | `ok` | Missing gene/role annotations stay unknown |
| Hub/currency policy suppresses detail | `ok` | `hub_metabolite=true`, `policy_suppressed=true`; full source counts retained |
| Valid ChEBI not annotated in this index | `empty` | `mapping.status=unmapped`; not a claim of no biology |
| One ChEBI/name matches multiple explicit model identities | `empty` | `mapping.status=ambiguous`; identities shown, genes withheld |
| Invalid input, missing/corrupt index, schema/configuration failure | `error` | `data.error`; never converted to a biological negative |

Only colon/underscore/case/leading-zero formatting is normalized. There is no
automatic synonym, stereoisomer, protonation-state, HMDB or fuzzy-name fallback.
All compartments with the exact source annotation are retained. Distinct model
identities are based on the TSV `metsNoComp` field, not guessed from ID suffixes.

## Important output fields

- `mapping.species`: model IDs, base identities, names, compartments, chemical
  annotations and source locations.
- `reactions`: full reaction participants with signed coefficients, recorded bounds,
  derived direction/reversibility, raw GPR plus AND/OR AST, subsystem, EC/TCDB and
  source references. A `source_location` identifies the original YAML entity/line
  and TSV record (one-based, header counts as record 1).
- `candidates`: Ensembl ID, unambiguous symbol when available, symbol status,
  `origin=biochemical`, reaction IDs, roles and `complex_member`. This boolean means
  at least one occurrence is under an AND, not that all reactions require the same
  complex. The original GPR is the actual rule; the flat list is navigation only.
- `total_*`, `returned_*`, `*_complete`: full counts and display caps are distinct.
  Counts/membership use all matching reactions before truncation. Candidate order
  is lexical, not biological importance. A referenced reaction omitted by a display
  cap remains in `reactions[reaction_id]` in the checksum-bound index.
- `provenance`: index hash, source commit/version/URLs/hashes, dataset kind, builder
  hashes and graph counts. `full_model`, `source_fixture`, `synthetic_fixture` are
  distinct. Query `retrieved_at` is local lookup time, not a claim of a fresh API call.
- `local_lookup_ms` and `network_calls=0`: local timing only, not whole-product SLA.

Transport context can be explicitly TCDB-annotated, or derived when the same
annotated metabolite appears on opposite sides in different compartments. The
derivation is labelled in `role_basis`. Enzyme context requires EC and GPR; other
roles stay unknown. These are reaction-context labels, not validated molecular
mechanisms or evidence that a protein directly binds the queried metabolite.

Default hub handling uses distinct reaction degree **greater than 200**, plus an
explicit ATP ChEBI policy. This is a configurable scope heuristic, not a universal
currency-metabolite ontology. `hub_policy="include"` keeps detail while preserving
the hub warning. The default 200-reaction display cap covers every reaction for
non-hub inputs under that default degree policy. An active bound is not measured in-vivo flux; blocked reactions
remain source records with `direction=blocked`, not reported as active pathways.

## Integration with 1E and Workstream A

The standalone D module does not auto-record a team ledger. `tools/gem.py` validates
and records the returned envelope exactly once through the same acknowledged recorder
used by 1E. No silent no-op recorder can establish successful persistence. The optional
standalone CLI ledger reports an error if its append/fsync fails.

To obtain a dossier, select an explicitly reviewed, bounded set of candidates with
`symbol_status="unique"` and pass `candidate["symbol"]` to the existing 1E tools.
Do not send Ensembl IDs as symbols, invent labels, or call four APIs for hundreds
of genes. Preserve origin, source reaction and complex context beside the dossier.
The demo/acceptance deliberately selects source-nominated GLDC; it does not treat
lexical order as target prioritization. No atlas CPS1 row is injected into glycine's
GPR list merely because earlier project examples mention it.

The pipeline attaches context alongside existing MR/coloc results and calls Human-GEM
only after classification. Tests assert that mapped, empty and failed context cannot
move A/B/C. The final expanded-MVP2/Slack Gate 2 review remains a separate milestone.

Batch output retains one record per original input, with `reused` when a normalized
ID was already looked up in that batch. Counts distinguish unique valid IDs,
mapped/unmapped/ambiguous results and errors; they do not count MR pairs. Cross-run
result caching is left to A and must include the index hash AND lookup policy, not
only a disease-pair label. The existing cache only avoids decoding identical bytes.

## Verification commands

```bash
# Full-model source cross-check; requires PyYAML but no network after preparation.
python -m MVP3.src.acceptance \
  --source-dir /scratch/zpoints/MetaboCausal/human-gem-v2.0.0-UJimLC \
  --index /scratch/zpoints/MetaboCausal/human-gem-v2.0.0-UJimLC/human-gem-2.0.0.json \
  --output-root /scratch/zpoints/MetaboCausal

# Add --live-1e only to explicitly run one real GLDC dossier (network calls).
```

Full acceptance cross-checks all model entity IDs, every raw GPR/leaf set,
stoichiometry and flux bound against pinned sources; reproduces the checked-in
fixture; exercises five source-backed examples, missing input/model and a small
batch. `--live-1e` separately checks the existing four tools and their ledger. This
is not a final expanded MVP2 rerun, independent teammate review, model-provider
acceptance or Slack demonstration. See [verification/work log](logs/gem/WORK_LOG.md).

Source attribution and transformation notes: [NOTICE.md](NOTICE.md).
