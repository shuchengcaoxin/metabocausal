# MVP2 — literature discovery and published MR evidence

**Status: build plan and source preparation for September 12, 2026. Tasks are unassigned and will be claimed onsite. This folder does not mean that the literature agent or MR import is implemented.**

MVP2 finds published evidence that the existing database tools may miss. The product's main question is **metabolite exposure → disease outcome**. For broad coverage, start with metabolome-wide MR studies. A study can examine many metabolites and many diseases at the same time. Record reverse MR separately; do not use it as a forward result.

## The process we are building

1. **Plan searches.** Use the question, metabolite synonyms, existing coverage and unanswered questions. Include broad metabolome-wide MR searches and targeted follow-up searches.
2. **Retrieve.** Search Europe PMC; use Semantic Scholar for complementary discovery and citation/reference expansion. Record the actual query, source, time, pagination and failures.
3. **Verify and compare.** Resolve article identities, combine duplicate records, and assess relevance and methods. Keep a reason for include, exclude or unresolved decisions.
4. **Acquire.** Save accessible original articles and supplements with their URLs, versions and hashes. A downloaded file is not yet accepted evidence.
5. **Extract and validate.** Read exact MR results from the source table or passage. Check the metabolite, disease, direction, method, scale and numerical fields before adding a record.
6. **Challenge.** Deliberately search for null findings, conflicting studies, methodological problems and reverse-direction evidence. Null or reverse findings are not automatically proof against the forward hypothesis. An unsuccessful challenge search is reported, not filled with an invented opposing paper.
7. **Refine or stop.** Use remaining gaps to propose another bounded round. Stop at configured request, round or time limits and record what remains unresolved.
8. **Integrate.** Query the accepted result store from the existing product and show the source and limitations in both the report and Slack.

The initial five papers are **seeds**, not a quality-ranked final selection. They help test acquisition and connect existing atlas work to possible MR evidence. The agentic search must be able to discover other relevant studies and reject or limit a seed when its results do not fit.

## Folder map

| Folder | Contents and responsibility |
| --- | --- |
| `literature/seeds/<study_id>/` | Original articles, supplementary assets, retrieval metadata and a per-study source record. |
| `literature/studies/<study_id>/` | Additional studies discovered by the literature task, preserving the same source-record structure. |
| `literature/search_runs/<run_id>/` | Raw search responses and exact queries, once the discovery task runs. |
| `literature/screening/` | Include/exclude/unresolved decisions and scientific quality observations. |
| `data/extracted/` | Source-exact records before acceptance; each links to a source file and location. |
| `data/validated/` | Accepted MR records; reverse MR and incomplete records remain explicitly labelled. |
| `data/index/` | Reproducible product lookup built from a named validated snapshot. |
| `src/` | New discovery, screening and extraction modules developed in the assigned tasks. |
| `scripts/` | Reproducible acquisition and later preparation commands. |
| `tests/` | Small source-backed fixtures and checks added with the implementation. |
| `logs/` | Work and run records; each task/run writes its own file. |

Raw supplementary tables stay with their source paper. Do not make another unexplained copy in `data/`. Extraction records link back to the original asset, sheet and row.

## Read next

- [Onsite task board and integration order](../docs/planning/HACKATHON_BUILD_PLAN.md)
- [Search and scientific screening protocol](literature/SEARCH_PROTOCOL.md)
- [Data contract and counts](data/README.md)
- [Source inventory](literature/README.md)
- [MVP3: build against current examples, then validate against MVP2](../MVP3/README.md)

Credentials belong in each developer's local environment, never in source records or logs.

## Pair-level Europe PMC search

`MVP2/scripts/search_pairs_europepmc.py` consumes the corrected
`MVP2/data/extracted/screened_20260912/new_unique_pairs.csv`. It refuses rows
without `pair_relation_verified=yes`, both endpoints, and forward
metabolite-to-disease direction. It then runs one bounded Europe PMC
investigation per pair: metabolome-wide discovery, pair-specific follow-up,
and a deliberate null/conflicting/reverse/other-population challenge search.

Each pair is saved under `pairs/<pair_id>.json`, with its paper records, exact
queries, returned identifiers, discovery routes, deduplication decisions,
remaining gaps, and stop reason. `pair_search_index.csv` provides a compact
batch ledger. The default budget is three rounds and nine requests per pair;
use `--offset` and `--limit` for resumable batches.

Example:

```bash
python MVP2/scripts/search_pairs_europepmc.py \
  --input MVP2/data/extracted/screened_20260912/new_unique_pairs.csv \
  --output-dir MVP2/literature/search_runs/pair_batch_001 \
  --offset 0 --limit 100 --max-rounds 3 --max-requests-per-pair 9
```
