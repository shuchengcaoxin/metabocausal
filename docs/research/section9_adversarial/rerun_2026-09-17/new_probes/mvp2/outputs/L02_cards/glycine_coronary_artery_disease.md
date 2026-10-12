# MetaboCausal evidence card - glycine x coronary artery disease

## 1. Requested pair and resolved IDs

| Side | Asked for | Resolved label | Id | Resolution |
|---|---|---|---|---|
| Metabolite (exposure) | glycine | glycine | CHEBI:15428 | NOT in the pre-resolved sample; matching used the raw input string only (the 1A resolver lands separately) |
| Disease (outcome) | coronary artery disease | coronary artery disorder | MONDO:0005010 | NOT in the pre-resolved sample; matching used the raw input string only (the 1A resolver lands separately) |

Synonyms handed to the metabolite-side tools (23): glycine, Aminoacetic acid, Aminoessigsaeure, G, Gly, Glycin, Glycocoll, Glykokoll (showing 8 of 23). Every match in this card is made on these strings, case-insensitively, not on the name as it was typed.

Synonyms handed to the disease-side tools (11): coronary artery disease, coronary artery disorder, CHD (coronary heart disease), coronary arteriosclerosis, disease or disorder of coronary artery, CAD, coronary artery disease or disorder, coronary disease (showing 8 of 11). Every match in this card is made on these strings, case-insensitively, not on the name as it was typed.

One direction only: the metabolite is queried as the EXPOSURE and the disease as the OUTCOME. Nothing on this card is a statement about the reverse direction.

## 2. Evidence state and one-line verdict

**Verdict: State B - analysis-ready.** State B (analysis-ready): no retrieved MR estimate (retrieved MR (get_mr_result) returned no estimate; literature MR not run), but 1 exposure dataset(s) reach 3 or more genome-wide significant hits (best 49) and 3 outcome dataset(s) are available, so this pair could be analysed. Colocalisation: not queried in this run, so nothing here says whether the two GWAS share a causal variant. Any retrieved MR is retained without this additional supporting layer; colocalisation is not an inclusion requirement.

The state and the sentence above come from `classify.classify_state`, a pure function over this run's envelopes. No model wrote them and no model can change them.

The colocalisation clause is an evidence QUALIFIER: `get_colocalisation` runs after the classifier, its envelope is never passed to it, and no H4 on this card can move a pair between states A, B and C.

## 3. Metabolite -> disease genetic evidence

Source: EpiGraphDB MR-EVE - tool `get_mr_result` - status `empty` - retrieved at 2026-09-10T18:13:41.

Retrieved MR estimates: not available in this snapshot - not evidence of no effect.

MR-EVE exposure datasets matched (1): met-a-468 (Glycine).
MR-EVE outcome datasets matched (8): ebi-a-GCST003116 (Coronary artery disease), ebi-a-GCST005195 (Coronary artery disease), ebi-a-GCST005194 (Coronary artery disease), ebi-a-GCST000998 (Coronary heart disease), ieu-a-8 (Coronary heart disease), ieu-a-6 (Coronary heart disease), ieu-a-7 (Coronary heart disease), ieu-a-9 (Coronary heart disease).

**Retrieved colocalisation (Open Targets)**

`get_colocalisation` did not run in this run, so nothing was retrieved about a shared causal variant. That is a gap in what was queried, not a finding.

## 4. Instruments and feasibility

### Exposure datasets (metabolite instruments)

Source: OpenGWAS (gwasinfo index + tophits) - tool `get_mqtl_instruments` - status `ok` - retrieved at 2026-09-10T18:13:42.

| Dataset | Trait | Platform | Unit | Sample size | Population | Sex | Year | Build | GWS hits | Weak (F<10) | F range | Note (from the source) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| met-d-Gly | Glycine | Nightingale NMR (UK Biobank) | not recorded by this source | 114,972 | European | Males and Females | 2020 | HG19/GRCh37 | 49 | 0 | 26.43 to 1.641e+04 | not recorded by this source |
| met-a-468 | Glycine | mass spectrometry (Metabolon-type panel) | log10 units | 7,802 | European | Males and Females | 2014 | HG19/GRCh37 | 1 | 0 | 686.8 to 686.8 | not recorded by this source |

Read the Sex and Note columns before reading any row as an exposure: a sex-stratified deposit and an interaction scan are different datasets from a main-effect GWAS of the same trait, and an interaction beta measures how a SNP effect changes with the modifier, so F = (beta/se)^2 on it is not instrument strength.

All 2 dataset(s) named by these synonyms were queried.

Strongest retrieved hit per dataset (by retrieved p-value):
- met-d-Gly: rs1047891 (chr2:211,540,507, A/C, eaf 0.3150) beta 0.5354, se 0.004179, p <1e-300 (reported 0), F 1.641e+04
- met-a-468: rs715 (chr2:211,543,055, C/T, eaf 0.2920) beta 0.07600, se 0.002900, p 1.58e-147, F 686.8

F = (beta/se)^2 on the retrieved hit, arithmetic on retrieved numbers; weak means F < 10. It is not the first-stage F of a fitted MR, because no MR was fitted here, and it may be upward-biased by winner's curse. These are the feasibility arm's instruments, NOT necessarily the instruments behind the retrieved MR estimates in section 3; these F statistics do not describe those MR rows.

GWS hits are OpenGWAS's own PRE-CLUMPED tophits at p < 5e-8: independent loci, retrieved as a count, not selected or clumped here.

### Outcome datasets (disease)

Source: OpenGWAS (gwasinfo index + tophits) - tool `find_outcome_datasets` - status `ok` - retrieved at 2026-09-10T18:13:42.

| Dataset | Trait | Sample size | Cases | Controls | Population | Year | Author | Consortium | Build |
|---|---|---|---|---|---|---|---|---|---|
| ebi-a-GCST005195 | Coronary artery disease | 547,261 | 122,733 | 424,528 | not recorded by this source | 2017 | van der Harst P | not recorded by this source | HG19/GRCh37 |
| ebi-a-GCST005194 | Coronary artery disease | 296,525 | 34,541 | 261,984 | not recorded by this source | 2017 | van der Harst P | not recorded by this source | HG19/GRCh37 |
| ieu-a-9 | Coronary heart disease | 194,427 | 63,746 | 130,681 | Mixed | 2013 | Deloukas | CARDIoGRAMplusC4D | HG19/GRCh37 |

Capped by the tool: 3 of the 9 matched dataset(s) are returned. The rest are named in the caveats, not hidden.

### GWAS Catalog (context only)

Source: GWAS Catalog (EBI) REST API - tool `get_gwas_catalog` - status `error` - retrieved at 2026-09-10T18:15:42.

`get_gwas_catalog` returned an error envelope, so no association was retrieved: the request failed, which is not the same statement as the Catalog holding no association for this trait. It is not a classifier input, so the A/B/C state did not move. The source reported: GET https://www.ebi.ac.uk/gwas/rest/api/efoTraits/MONDO_0005010/associations exceeded the 120s wall-clock deadline after 120s and 4202496 bytes; the response was still arriving. Partial JSON cannot be parsed, so nothing was retrieved.

## 5. Effector genes by source

GWAS Catalog mapped genes: the request failed, so no gene was retrieved. That is not the same statement as the Catalog naming no gene.

The atlas nomination layer was not queried in this run; the effector mechanism was not assessed.
An unresolved effector mechanism does not remove or invalidate retrieved metabolite MR, colocalisation assessments, or instrument feasibility evidence; those layers remain separate.
No gene dossier is available in this run; see the atlas status above and run-level notes.

Human-GEM biochemical candidates were not assessed in this run.

**Molecular-QTL colocalisation at the disease's credible sets**

`get_colocalisation` did not run in this run, so no QTL colocalisation was retrieved for any gene.

## 6. Gene dossiers

No gene dossier is available in this run. This may reflect an unqueried or unresolved effector layer, or an interrupted dossier stage; consult section 5 and the run notes. It does not mean that these genes have no drugs, and does not invalidate any retrieved metabolite MR, colocalisation assessment, or feasibility evidence.

## 7. Via-enzyme protein evidence

Human-GEM biochemical context was not assessed in this run. This is not evidence that the metabolite has no reactions, enzymes or transporters.

## 8. Caveats

**Run-level notes**

- cached snapshot, not a live run.

**Tools that failed in this run**

- `get_gwas_catalog` (GWAS Catalog (EBI) REST API) returned an error envelope.

A failed request is not a source with no record. Nothing above may be read as an absence of evidence.

**Caveats declared by the tools, verbatim**

`get_mr_result` (EpiGraphDB MR-EVE):
- Retrieved from EpiGraphDB MR-EVE (OpenGWAS 2020-10-13 snapshot); automated MR labelled preliminary by the source. Not computed here. One direction only: the metabolite is queried as the EXPOSURE, never as the outcome, so nothing said here is a statement about the reverse direction.
- Both sides matched (Glycine x Coronary artery disease, Coronary heart disease) but MR-EVE holds no metabolite -> disease estimate for this pair. Only that direction was queried: a metabolite with too few instruments has no MR-EVE row as an exposure at all, while the reverse direction can be fully populated (Glycine returns 0 rows as an exposure; Coronary heart disease -> Glycine returns 5).
- Empty is not evidence of no effect - the trait may be absent from this snapshot (e.g. no met-d datasets).

`get_mqtl_instruments` (OpenGWAS (gwasinfo index + tophits)):
- Retrieved from OpenGWAS: the gwasinfo dataset index plus, per dataset, its pre-computed tophits. This is a feasibility report - which datasets exist and whether they carry instruments - and NOT an MR result. No estimate was computed here and nothing here says an effect exists.
- Dataset metadata is read from the local cache of https://api.opengwas.io/api/gwasinfo (data/gwasinfo.json, 50,056 datasets pulled 2026-09-10). No index request is sent per call; refresh it with tools._traits.build_opengwas_vocabulary().
- gwasinfo carries no platform field, so platform is INFERRED from the id batch prefix: met-a is the Metabolon-type mass-spectrometry panel (Shin 2014), met-c and met-d are Nightingale NMR (met-d being the UK Biobank release). Every other batch - met-b included, which is not a metabolite panel at all but Roederer 2015 immune-cell flow cytometry - is reported with platform null rather than guessed at.
- gws_hits counts OpenGWAS's own PRE-CLUMPED tophits at p < 5e-8: independent loci, not SNPs. The independence comes from that pre-computed set, built at OpenGWAS's own r2/kb defaults, and NOT from the clump flag this tool sends - measured 2026-09-10, met-d-Gly returns the same 49 rows with clump=1, with clump=0 and with no clump key at all, because preclumped defaults to 1. Clumping on the fly instead (preclumped=0, clump=1) gives a slightly different set: 52 rows in 6.7 s against 0.1 s. The p-value threshold IS applied on top of the pre-clumped set.
- F is the approximate per-SNP F statistic (beta/se)^2, arithmetic on the retrieved beta and se; weak_instruments counts hits with F < 10. It is NOT the first-stage F of a fitted MR, because no MR was fitted here, and a hit whose se is missing or zero gets no F at all. These betas also come from the same scan that selected the SNPs at p < 5e-8, so every F here is inflated by winner's curse - read it as an upper bound on instrument strength, not an estimate of it.
- Several datasets of one metabolite are not interchangeable: they are different assays on different scales - met-d-Gly (Nightingale NMR (UK Biobank), unit None, n=114972) vs met-a-468 (mass spectrometry (Metabolon-type panel), unit 'log10 units', n=7802). Effect sizes across them are not comparable. Print platform / unit / sample_size beside every number and never merge them into one.
- met-d-Gly is drawn from UK Biobank, and most large modern outcome GWAS include UK Biobank too. Sample overlap is NOT checked here and it is the first thing a two-sample MR reviewer asks. This tool sees one side of the pair at a time, so it cannot tell whether the exposure and outcome GWAS share participants. Overlapping samples bias two-sample MR towards the confounded observational estimate and inflate type-1 error. Check the cohort composition of BOTH datasets before any card says analysis-ready.
- example_hits is the 5 strongest hits by p-value per dataset, not the whole instrument set; gws_hits is the full count.
- met-d-Gly report p exactly 0 on at least one hit, which underflowed double precision in the source. Render those as "p < 1e-300 (reported 0)", never as p = 0.
- tophits answers an id it does not recognise with an empty list, exactly as it answers a real dataset that has no genome-wide hit. So gws_hits = 0 means "no LD-clumped hit at p < 5e-8 in this dataset" and never "this measurement has no genetic basis".

`find_outcome_datasets` (OpenGWAS (gwasinfo index + tophits)):
- Retrieved from OpenGWAS: the gwasinfo dataset index plus, per dataset, its pre-computed tophits. This is a feasibility report - which datasets exist and whether they carry instruments - and NOT an MR result. No estimate was computed here and nothing here says an effect exists.
- Dataset metadata is read from the local cache of https://api.opengwas.io/api/gwasinfo (data/gwasinfo.json, 50,056 datasets pulled 2026-09-10). No index request is sent per call; refresh it with tools._traits.build_opengwas_vocabulary().
- These synonyms matched 2 different trait spellings ('Coronary artery disease', 'Coronary heart disease'); matching is exact after casefolding, so a spelling no synonym carries was never reachable.
- Ranking: datasets with a recorded sample_size first, then the curated repositories (ebi-, ieu-, finn-) ahead of the rest, then sample size descending. So this list is not a pure size ranking - a large dataset from another batch can sit below a smaller curated one - and the datasets gwasinfo records no sample_size for (every finn-b row) come last however big they are.
- Capped: 9 outcome dataset(s) match these synonyms, only the top 3 are returned (ebi-a-GCST005195, ebi-a-GCST005194, ieu-a-9); not returned: ieu-a-7, ebi-a-GCST003116, ebi-a-GCST000998, ieu-a-8, ieu-a-6, bbj-a-159. Raise top_n to see them.
- ebi-a-GCST005195 and ebi-a-GCST005194 (PMID 29212778) are deposits from the SAME publication (matching PMID) and are not independent outcome datasets - one can be a sub-stage of the other, so their sample sizes differ while the participants do not. Count the study once.
- ebi-a-GCST005195, ebi-a-GCST005194: a UK Biobank deposit or a meta-analysis large enough (>= 250,000) that it very likely contains UK Biobank. gwasinfo records no cohort list, so this is a size-based flag, not a verified overlap. Sample overlap is NOT checked here and it is the first thing a two-sample MR reviewer asks. This tool sees one side of the pair at a time, so it cannot tell whether the exposure and outcome GWAS share participants. Overlapping samples bias two-sample MR towards the confounded observational estimate and inflate type-1 error. Check the cohort composition of BOTH datasets before any card says analysis-ready.
- gwasinfo records no population for ebi-a-GCST005195, ebi-a-GCST005194 (it writes the literal "NA"), so the ancestry match against the exposure cannot be checked for those datasets from this envelope alone.
- ncase / ncontrol are reported exactly as gwasinfo wrote them. They are not always a study design: the ukb-e continuous panels carry ncase == sample_size and ncontrol == 0 on a blood measurement, and the finn-b datasets carry case and control counts but no sample_size at all.
- population is reported per dataset because it has to be checked against the exposure's population before any MR is run; this tool sees only one side of the pair and cannot check it for you.

`get_gwas_catalog` (GWAS Catalog (EBI) REST API):
- GWAS Catalog rows are curated trait-variant ASSOCIATIONS from published GWAS, not causal estimates: no MR, no instrument, no direction of causation. An odds ratio or beta here is the reported marginal association of one variant with the trait in that study's own scale and ancestry. Retrieved, not computed.
- Resolved through the ontology id: 'MONDO:0005010' -> MONDO_0005010 ('coronary artery disorder'). The trait name was not searched.
- The associations endpoint is slow and cannot be paged: measured 2026-09-10, gout took 113 s for 3.0 MB / 1,420 rows and urate measurement 364 s for 10.4 MB / 4,588 rows, dribbled out in small chunks so an ordinary read timeout never fires. This call therefore aborts at a 120 s wall-clock deadline with an error envelope rather than hanging the pipeline. A deadline hit is a limit of the resource, NEVER evidence that the trait has no associations.
- The GWAS Catalog request failed before any association was retrieved, so this trait has no retrieved association either way: GET https://www.ebi.ac.uk/gwas/rest/api/efoTraits/MONDO_0005010/associations exceeded the 120s wall-clock deadline after 120s and 4202496 bytes; the response was still arriving. Partial JSON cannot be parsed, so nothing was retrieved.
- Empty is not evidence of no association - it means no curated GWAS Catalog row was retrieved under this trait term, which is a fact about this resource's curation and naming, not about biology.

## 9. Reasoning

Model reasoning pending integration (section 1F).

## 10. Next action

No MR estimate was retrieved, but the pair is analysis-ready in this snapshot: exposure dataset met-d-Gly (Glycine, Nightingale NMR (UK Biobank), n 114,972) carries 49 genome-wide significant hit(s), and outcome dataset ebi-a-GCST005195 (Coronary artery disease, n 547,261) is available. Running the MR is the next step, and it is a step this build does not take.

- Check ancestry: the exposure and outcome populations are printed per dataset in section 4 and must match before a two-sample MR means anything.
- Check sample overlap. It is not checked anywhere in this build, it is the first thing a reviewer asks, and UK Biobank sits on both sides of many pairs.
- Check the unit and the assay platform of the exposure dataset before interpreting any effect size you get.
- Analysis-ready is a statement about data availability. It is not a prior that an effect exists.

## 11. Provenance

This run wrote no ledger file, so the digest below is built from the envelopes carried in the run's own result.

| # | Tool | Status | Source URL (query cut at 80 characters) | Retrieved at |
|---|---|---|---|---|
| 1 | get_mr_result | empty | api.epigraphdb.org/mr?exposure_trait=Glycine&pval_threshold=1.0&outcome_trait=Coronary+artery+disease | 2026-09-10T18:13:41 |
| 2 | get_mqtl_instruments | ok | api.opengwas.io/api/tophits | 2026-09-10T18:13:42 |
| 3 | find_outcome_datasets | ok | no URL recorded by this tool | 2026-09-10T18:13:42 |
| 4 | get_gwas_catalog | error | www.ebi.ac.uk/gwas/rest/api/efoTraits/MONDO_0005010/associations | 2026-09-10T18:15:42 |

Sections 1 and 3 to 8, 10 and this one are rendered by code from the envelopes above; section 2's state and reason come from `classify.classify_state`, a pure function. No model wrote any of them, and no MR estimate was retrieved for this pair in this snapshot, so section 3 quotes none.
