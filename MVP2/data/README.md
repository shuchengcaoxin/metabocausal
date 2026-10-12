# MR records and versioned data

**Preparation only: no new MR results have been imported by creating these folders.**

`extracted/` holds source-exact candidate records. `validated/` holds a named accepted snapshot, plus clearly separated reverse/incomplete records. `index/` is a reproducible lookup derived from a validated snapshot. Each stage writes a manifest that links its input hashes, code commit, configuration, output files and diagnostic counts.

## Minimum shared record contract to freeze in task 00

| Field group | Required meaning |
| --- | --- |
| Identity | Stable record ID, original exposure/outcome labels, resolved IDs when available, measurement type. |
| Direction | Explicit exposure → outcome; forward metabolite → disease or reverse disease → metabolite. |
| Source | Verified DOI/PMID/PMCID where available, article version, source asset path/hash, sheet and original row or text section/page. |
| Study | Exposure/outcome datasets, cohort/ancestry, method and analysis variant as reported. Missing details stay missing. |
| Estimate | Reported beta/OR/HR and units/scale, SE or CI, p-value, SNP count and multiple-testing details when available. Do not invent missing values. |
| Validation | Pair/direction verification, numeric/scale checks, accepted/incomplete/rejected status and reason. |
| Relationships | Original study/version family, duplicate estimate ID, linked sensitivity/coloc/gene-context records. |

The field names and serialisation are to be agreed at baseline freeze before independent implementation. The existing tool envelope and `HANDOFF_1F.md` remain the integration contract; do not silently change their meaning.

Do not collapse missing to zero. Preserve source precision; record any explicit derived conversion separately. Ratios, inversely coded outcomes and unit differences require visible handling. Retain reported null/non-significant estimates. A source publishing only selected significant results must carry that selection flag.

## Count the right things

- **Unique pair count:** distinct resolved metabolite–disease pairs with accepted forward MR records. Unresolved identities do not inflate this count.
- **Estimate count:** source-specific methods/cohorts/analysis variants; several can belong to one pair.
- **Metabolite coverage:** distinct resolved exposure identities, with ratios/mixtures shown separately.
- **New coverage:** difference from the named pre-import snapshot, not the sum of rows in downloaded tables.

Keep study/cohort overlap visible. The same estimate retrieved through a paper and a database is not independent replication. A gene × outcome expansion is not a new MR result.

## How MVP3 consumes this

MVP3 receives resolved metabolite IDs and a reference to the evidence snapshot. Cache biochemical lookups by metabolite ID and Human-GEM version, not by every disease pair. Join reaction/gene context back to the report without duplicating or changing the MR records. Re-run lookup only for new/changed inputs or model versions; run the agreed end-to-end acceptance cases on the integrated snapshot.

## 2026-09-17 — the derived tables under `extracted/` were regenerated (for Jingrui's review)

给 Jingrui 的说明（中英对照）：下面这些表是我重新跑出来的，**原始档案没有动**。请你过一遍 diff 再决定要不要留。

**What was regenerated, and from what.** Branch `fix/adversarial-16-20260917`, from the
same seed workbooks under `MVP2/literature/seeds/` and the same MVP1 baseline
(`archive/project_files/release-evidence_2026-09-11/.../metabolite_disease.csv`,
sha256 `af2a44ac…`, unchanged). Nothing under `archive/` was touched. The regenerated
files are:

| File | Written by |
| --- | --- |
| `extracted/screened_20260912/candidate_pairs.csv` | `MVP2/scripts/screen_seed_papers.py` |
| `extracted/screened_20260912/new_pair_records.csv` | same |
| `extracted/screened_20260912/new_unique_pairs.csv` | same |
| `extracted/screened_20260912/screening_ledger.csv` | same |
| `extracted/screened_20260912/manifest.json` | same |
| `extracted/mvp1_plus_mvp2_candidate_metabolite_disease.csv` | `MVP2/scripts/merge_new_pairs.py` |
| `extracted/mvp1_plus_mvp2_candidate_metabolite_disease.provenance.csv` | same |
| `extracted/mvp1_plus_mvp2_candidate_metabolite_disease.manifest.json` | same |

**Why the numbers moved.** `normalize()` used to delete `%`, so a ratio exposure
(`Omega-3%`) and the absolute exposure (`Omega-3`) collapsed into one pair identity.
They are two different exposures. Keeping `%` splits them, and the distinct-pair count
went **9,801 → 10,804** (+1,003); the merged table went 20,918 → 21,921 rows. The count
going up is the point, not a side effect.

**What else changed in the rows.** 498 UKB source rows are single-SNP `Wald ratio` rows
whose values sit one column right of the printed header, so the old extractor wrote an
odds ratio into `ci_high` and a beta-scale bound into `p_value` (18 of them reach
`new_pair_records.csv`). Those rows now read the p value from the column that holds it,
leave `ci_low`/`ci_high` empty, and carry the interval that IS there in two new columns,
`ci_low_beta_scale`/`ci_high_beta_scale`, plus an `extraction_note` saying why. Three new
columns therefore appear in `candidate_pairs.csv`, `new_pair_records.csv`,
`new_unique_pairs.csv`, `screening_ledger.csv` and the merge provenance sidecar.

`supporting_mr_rows` in the merged table used to be the constant `"1"` on every appended
row. It is now the real count of source rows behind each pair (1, 2 or 4; they sum to
17,405 = `new_pair_record_count`).

**What is NOT claimed.** This is still source extraction plus an anti-join, not
scientific validation. On an unshifted UKB row the printed header names the two columns
**Excel labels `L` and `M`** (the 12th and 13th; extractor indices 11 and 12) "95% UCI"
and "95% LCI", and the values are the other way round. On 2026-09-17
the bounds were extracted **as printed**, under the header's own names, and left in the
order the header produced — which meant `ci_low > ci_high` on 7,912 of the 10,804 unique
pairs. **That decision was superseded on 2026-09-18; see the next section.** The tables
in this folder are the 2026-09-18 ones.

**Manifests.** Every manifest under `MVP2/` now records a repo-relative POSIX path, and
records beside each digest which rule produced it (`"bytes": "as-committed"` for a path
`.gitattributes` pins, `"lf-normalized"` otherwise), so a digest can be reproduced from
the bytes without a `git` binary. `MVP2/literature/search_runs/` is a record of searches
that were performed, not a derived table: only the input block of
`pair_batch_smoke_glycine_cad_20260912/manifest.json` was re-stated, and the run's own
history is untouched.

Full write-up: `docs/research/section9_adversarial/fixes_2026-09-17/FIXES.md`.

## 2026-09-18 — the swapped 95% bounds are now shipped in numeric order

给 Jingrui 的说明（中英对照）：**上一节说"按原样保留、不重排"的那条，现在改了。**
UKB 那份补充材料的表头把"95% UCI"印在实际存放下界的那一列上，"95% LCI"印在存放上界
的那一列上。照表头读出来的结果是下界比上界大——这不是对论文结论的判断，任何置信区间
都不可能下界大于上界，所以这是一个可以纯靠算术查出来的排版/表头不一致。现在表里
`ci_low`/`ci_high` 按数值大小排好，**原样印出来的那两个数一个没丢**，存在同一行的
`ci_low_as_printed`/`ci_high_as_printed` 两列里，并且每一条改动过的行都在
`extraction_note` 里写明了原因。本来就从小到大的行一个字节都没动。

**What changed.** `ci_low`/`ci_high` in the shipped tables now hold the source's own two
numbers **in numeric order**. Nothing was recomputed and nothing was discarded: on a row
whose bounds were reordered, the pair exactly as the source prints it is preserved on the
same row in two new columns, `ci_low_as_printed` / `ci_high_as_printed`, and
`extraction_note` says what happened and why. With the three columns added on 2026-09-17
that makes five source-side columns beyond the original schema, in the four screened CSVs
and the merge provenance sidecar.

**Why.** Reading the two cells under the printed header's own names produced
`ci_low > ci_high`, which no confidence interval can satisfy. Detecting that needs no
opinion about the paper's science — it is arithmetic — and the agent pipeline flagged it
while extracting. It is a header/typesetting inconsistency in a published supplementary
table, and it is recorded here as exactly that.

**Where to check it in the workbook.**
`MVP2/literature/seeds/ukb_mapping_2025/42255_2025_1371_MOESM3_ESM.xlsx`, sheets
`sTable 31`–`sTable 35`, header row 3: `95% UCI` sits in the column **Excel labels `L`**
(the 12th) and `95% LCI` in **`M`** (the 13th); Excel's column `K` is the odds ratio, not
a bound. The shipped `extraction_note` and the write-up call the same two cells
"column 11" and "column 12" because those are the extractor's own 0-based indices —
`text(row, 11)` and `text(row, 12)` — for `L` and `M`.
核对位置：上面那个 xlsx 的 `sTable 31`–`sTable 35`，第 3 行表头，Excel 的 **L 列**
（第 12 列）印的是 `95% UCI`、**M 列**（第 13 列）印的是 `95% LCI`；K 列是 odds ratio，
不是区间端点。表里 `extraction_note` 写的"column 11 / column 12"是程序自己的从 0 数起
的列号，指的就是 L 列和 M 列，别按 Excel 的列号去数。

**The rule, precisely.** A row is reordered **only** when both of its bounds are numeric
and `ci_low > ci_high`. Rows already ascending, rows with equal bounds, and rows with a
blank or non-numeric bound are written exactly as they were read. Nothing is reordered by
reading the header rather than the values.

| Table | Rows | Reordered | `ci_low > ci_high` left |
| --- | --- | --- | --- |
| `extracted/screened_20260912/candidate_pairs.csv` | 20,460 | 16,944 | 0 |
| `extracted/screened_20260912/screening_ledger.csv` | 20,460 | 16,944 | 0 |
| `extracted/screened_20260912/new_pair_records.csv` | 17,405 | 14,509 | 0 |
| `extracted/screened_20260912/new_unique_pairs.csv` | 10,804 | 7,912 | 0 |
| `extracted/mvp1_plus_mvp2_candidate_metabolite_disease.csv` (`ci_low`/`ci_upp`) | 21,921 | 7,912 | 0 |
| `extracted/mvp1_plus_mvp2_candidate_metabolite_disease.provenance.csv` | 10,804 | 7,912 | — |

Every reordered row is a `ukb_mapping_2025` row; Chen 2023's bounds already ascend and
are byte-identical. No row count, no pair identity, no `supporting_mr_rows` value and no
summary count changed: 10,804 unique pairs and 21,921 merged rows, as before. The only
fields that moved are `ci_low`, `ci_high` (`ci_upp` in the merged table) and
`extraction_note`, plus the two new columns.

**One row, before and after** (`sTable 33` row 4, M-LDL-TG% → other bacterial intestinal
infections):

| Field | 2026-09-17 | 2026-09-18 |
| --- | --- | --- |
| `ci_low` | `1.80370344183517` | `1.17059104033226` |
| `ci_high` | `1.17059104033226` | `1.80370344183517` |
| `ci_low_as_printed` | — | `1.80370344183517` |
| `ci_high_as_printed` | — | `1.17059104033226` |
| `extraction_note` | *(empty)* | "95% bounds reordered: … preserved in `ci_low_as_printed`/`ci_high_as_printed`." |

The run manifest carries the same rule and the same counts under `bound_order`, and
`tests/test_fix_mvp2_m4_m5_m6_m7.py::TestM4BoundOrderIsNumeric` asserts all of it.
