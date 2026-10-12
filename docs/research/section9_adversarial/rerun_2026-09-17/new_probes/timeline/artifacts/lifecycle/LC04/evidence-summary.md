# MetaboCausal — HDL cholesterol · CETP · Coronary artery disease

Snapshot: mvp1-cetp-torcetrapib-2026-09-12-v2 | Checked: 2026-09-12
Curated recording demo · saved evidence

Follow CETP from human genetics and preclinical evidence into clinical testing, failure, later interpretation and the target class's current status.

## The question

If a drug improves HDL cholesterol, will it protect patients from coronary events? And if it fails, is the problem the blood marker, the target, or the particular drug?

[ILLUMINATE results (2007)](https://doi.org/10.1056/NEJMoa0706628) · [HDL cholesterol and heart attack MR (2012)](https://doi.org/10.1016/S0140-6736(12)60312-2)

## Retrieved MR: inspect the design

The selected MVP1 HDL–CAD row has a negative pre-computed estimate. It remains visible beside the later curated literature. Different instruments, populations and endpoints can lead to different conclusions; a source p-value does not resolve these differences.

[MVP1 HDL cholesterol–CAD record](https://epigraphdb.org/mr) · [HDL cholesterol and heart attack MR (2012)](https://doi.org/10.1016/S0140-6736(12)60312-2)

## A target-matched example: CETP

CETP is an author-prioritized HDL gene in the project atlas. Torcetrapib and evacetrapib inhibit the CETP protein. This gives a real gene-to-drug link, while the atlas annotation alone does not prove mediation.

[MVP1 CETP annotation / Zoodsma 2025](https://doi.org/10.1038/s41588-025-02355-3) · [ILLUMINATE results (2007)](https://doi.org/10.1056/NEJMoa0706628) · [ACCELERATE results (2017)](https://doi.org/10.1056/NEJMoa1609581)

## What failed?

Torcetrapib was stopped after excess mortality and cardiovascular events. Evacetrapib was stopped for insufficient efficacy. These are different failure modes and are shown as separate drug histories.

[Pfizer programme stop (2006)](https://www.sec.gov/Archives/edgar/data/78003/000007800306000334/ex991202.htm) · [Lilly programme stop (2015)](https://investor.lilly.com/node/24656)

## What genetics adds

Comparing CETP gene variants with torcetrapib helped distinguish lipid changes from the drug's blood-pressure effect. HDL-focused MR also challenged the assumption that raising this marker must prevent heart attacks.

[CETP genetics versus torcetrapib (2009 online)](https://pubmed.ncbi.nlm.nih.gov/20026784/) · [HDL cholesterol and heart attack MR (2012)](https://doi.org/10.1016/S0140-6736(12)60312-2)

## Keep the counterevidence

This is not proof that genetic analysis would have predicted every failure, or that CETP is an invalid target. REVEAL found benefit with anacetrapib, and target-specific genetic analyses point to apoB-related effects.

[REVEAL anacetrapib results (2017)](https://doi.org/10.1056/NEJMoa1706444) · [CETP/HMGCR genetic analysis (2017)](https://doi.org/10.1001/jama.2017.11467)

## The target's story continues

A retrieved PREVAIL record lists obicetrapib as Phase 3, active not recruiting; its last update is June 2024. A January 2026 sponsor update discusses continued development. Neither record is a completed cardiovascular-outcome result.

[Obicetrapib PREVAIL registry](https://clinicaltrials.gov/study/NCT05202509) · [NewAmsterdam 2026 programme update](https://ir.newamsterdampharma.com/news-releases/news-release-details/newamsterdam-pharma-highlights-2025-achievements-and-outlines)

## What remains unresolved

The selected baseline has no queried colocalisation or gene-QTL evidence. Source CI bounds include zero despite a small reported p-value; the CI level and scale are unspecified, so these fields are flagged rather than silently repaired. No claim of causal confidence is made from State A.

[MVP1 HDL cholesterol–CAD record](https://epigraphdb.org/mr) · [MVP1 CETP annotation / Zoodsma 2025](https://doi.org/10.1038/s41588-025-02355-3)

## Genetic Insights

This timeline starts with human genetics and target-level preclinical evidence, then follows the compound into clinical trials and later genetic reinterpretation. Early evidence supported CETP's effect on HDL and the target rationale; it did not establish torcetrapib safety or clinical benefit.

### 1989-11-23 — Inherited CETP deficiency
clinical | Human genetics | Human genetic effect on CETP and HDL; not coronary-outcome evidence
A CETP splice-site mutation was linked to CETP deficiency and markedly higher HDL in a family.
[Inherited CETP deficiency (1989)](https://pubmed.ncbi.nlm.nih.gov/2586614/)

### 1998-02-27 — Target suppression lowers lesions
preclinical | Preclinical evidence | Target-level animal evidence; not torcetrapib-specific
Suppressing CETP reduced atherosclerotic lesions in cholesterol-fed rabbits.
[CETP suppression in rabbits (1998)](https://pubmed.ncbi.nlm.nih.gov/9478952/)

### 2000-07-13 — A CETP inhibitor helps rabbits
preclinical | Preclinical evidence | Target-class animal evidence; not torcetrapib-specific
A different CETP inhibitor improved lipids and attenuated atherosclerosis in rabbits.
[CETP inhibitor in rabbits (2000)](https://pubmed.ncbi.nlm.nih.gov/10910363/)

### 2004-03 — Torcetrapib raises HDL
clinical | Phase 1 publication | Compound-specific early human evidence; publication month
A short multidose study showed that torcetrapib inhibited CETP and raised HDL in healthy participants.
[Torcetrapib Phase 1 study (2004)](https://pubmed.ncbi.nlm.nih.gov/14739125/)

### 2004-07 — ILLUMINATE begins
clinical | Phase 3 trial | Trial record; start date has month precision
Trial of torcetrapib plus atorvastatin versus atorvastatin in a coronary-risk population.
[ILLUMINATE registry](https://clinicaltrials.gov/study/NCT00134264)

### 2006-12-02 — Development stopped
clinical | Safety failure | Drug-specific safety / programme decision
Pfizer announced termination of ILLUMINATE and the compound's development after a mortality and cardiovascular-event imbalance.
[Pfizer programme stop (2006)](https://www.sec.gov/Archives/edgar/data/78003/000007800306000334/ex991202.htm)

### 2007-11-05 — Higher HDL, more harm
clinical | Trial results | Specific drug and trial population
Published trial results showed improved lipid levels alongside higher mortality and cardiovascular morbidity.
[ILLUMINATE results (2007)](https://doi.org/10.1056/NEJMoa0706628)

### 2009-12-21 — Target or drug effect?
later genetics | Later genetic interpretation | Retrospective target-versus-drug comparison
CETP genetic variants resembled the drug's lipid effects but not its blood-pressure rise, supporting an off-target explanation of that effect.
[CETP genetics versus torcetrapib (2009 online)](https://pubmed.ncbi.nlm.nih.gov/20026784/)

### 2012-05-17 — HDL assumption questioned
later genetics | Later metabolite MR | Related later evidence; not a 2006 prediction
Some genetic mechanisms raising HDL did not lower heart-attack risk. This challenges HDL elevation as a sufficient rationale; it is not a CETP-specific negative result.
[HDL cholesterol and heart attack MR (2012)](https://doi.org/10.1016/S0140-6736(12)60312-2)

### 2017-08-29 — Another CETP drug shows benefit
human genetics | Class outcome | Different compound; necessary counterevidence
REVEAL found fewer major coronary events with anacetrapib, showing that torcetrapib's failure did not invalidate the whole target class.
[REVEAL anacetrapib results (2017)](https://doi.org/10.1056/NEJMoa1706444)

### 2026-01-09 — CETP development continues
class status | Current class status | Different compound; dated programme status
A sponsor update described continued obicetrapib development; this is not a completed cardiovascular-outcome result.
[Obicetrapib PREVAIL registry](https://clinicaltrials.gov/study/NCT05202509) · [NewAmsterdam 2026 programme update](https://ir.newamsterdampharma.com/news-releases/news-release-details/newamsterdam-pharma-highlights-2025-achievements-and-outlines)

## Latest retrieved status

NCT00134264: PHASE3 — TERMINATED
A Study Examining Torcetrapib/Atorvastatin And Atorvastatin Effects On Clinical CV Events In Patients With Heart Disease
Registry last updated: 2012-02-03; checked: 2026-09-12.
Safety stop announced by Pfizer after excess deaths and cardiovascular events.
Sponsor decision: 2006-12-02.
Latest programme decision retrieved for this example; no exhaustive global revival/approval search.
[ILLUMINATE registry](https://clinicaltrials.gov/study/NCT00134264) · [Pfizer programme stop (2006)](https://www.sec.gov/Archives/edgar/data/78003/000007800306000334/ex991202.htm)

## Module status
- MVP1: Saved evidence available. Selected original HDL–CAD MR row and CETP atlas annotation.
- Genetic Insights: Curated example ready. Two target-matched failure histories with dated sources; all-pair automatic preparation remains integration work.
- Jingrui · MVP2: Awaiting accepted output. Seed papers and Europe PMC literature evidence.
- Ziwei · MVP2: Awaiting accepted output. Semantic Scholar evidence, merged by paper identity.
- Zipeng · MVP3: Awaiting accepted output. Human-GEM biochemical context.
- Slack: Export ready; live delivery unverified. Same snapshot produces Slack text and attachments; Zhang Hao connects the bot.
- LLM interpretation: No model run for this demo. The visible summary was prepared for the saved example. OpenAI/Claude code support is separate.

## Sources
- [MVP1 HDL cholesterol–CAD record](https://epigraphdb.org/mr) — metabolite_disease.csv record 4145; header = 1. Selected pre-computed estimate, not a target-specific MR analysis. Original source values are in the evidence bundle.
- [MVP1 CETP annotation / Zoodsma 2025](https://doi.org/10.1038/s41588-025-02355-3) — triples.csv.gz decompressed record 328106; atlas rs821840 and rs189866004. Author-prioritized gene annotation for HDL cholesterol, ENSG00000087237. The present atlas is not evidence available to a 2006 decision-maker.
- [Inherited CETP deficiency (1989)](https://pubmed.ncbi.nlm.nih.gov/2586614/) — Nature paper; published 1989-11-23; PMID 2586614. A CETP splice-site mutation caused inherited CETP deficiency and markedly increased HDL. This establishes human genetic effects on the biomarker, not protection from coronary disease.
- [CETP suppression in rabbits (1998)](https://pubmed.ncbi.nlm.nih.gov/9478952/) — Journal paper; published 1998-02-27; PMID 9478952. Target-level preclinical evidence: CETP antisense treatment reduced atherosclerotic lesions in cholesterol-fed rabbits. This was not a torcetrapib experiment.
- [CETP inhibitor in rabbits (2000)](https://pubmed.ncbi.nlm.nih.gov/10910363/) — Nature paper; published 2000-07-13; PMID 10910363. A different CETP inhibitor, JTT-705, improved lipids and attenuated rabbit atherosclerosis. It supports the target class, not torcetrapib-specific safety or efficacy.
- [Torcetrapib Phase 1 study (2004)](https://pubmed.ncbi.nlm.nih.gov/14739125/) — Phase 1 multidose study; published 2004-03; PMID 14739125. Early human proof of mechanism: torcetrapib increased HDL over 14 days. Publication date is shown; the study began earlier, but no verified start date is asserted here.
- [ILLUMINATE registry](https://clinicaltrials.gov/study/NCT00134264) — protocolSection identification, status, design and eligibility. Phase 3 torcetrapib/atorvastatin versus atorvastatin. Population includes coronary heart disease or high-risk diabetes; broader than the exact CAD GWAS population.
- [Pfizer programme stop (2006)](https://www.sec.gov/Archives/edgar/data/78003/000007800306000334/ex991202.htm) — Pfizer release, 2006-12-02, filed with SEC. Sponsor stopped trials and compound development after the mortality/cardiovascular-event imbalance.
- [ILLUMINATE results (2007)](https://doi.org/10.1056/NEJMoa0706628) — Abstract and discussion; published online 2007-11-05; PMID 17984165. Torcetrapib increased HDL but increased mortality and cardiovascular morbidity. This does not isolate CETP inhibition as the cause of harm.
- [CETP genetics versus torcetrapib (2009 online)](https://pubmed.ncbi.nlm.nih.gov/20026784/) — Abstract; online 2009-12-21, journal issue 2010; DOI 10.1161/CIRCULATIONAHA.109.865444. Genetic lipid effects resembled treatment; blood-pressure effects did not. Supports an off-target interpretation of the hypertensive effect, not proof of every cause of death.
- [HDL cholesterol and heart attack MR (2012)](https://doi.org/10.1016/S0140-6736(12)60312-2) — Abstract / interpretation; 2012-05-17; PMID 22607825. Some genetic mechanisms raising HDL did not lower myocardial-infarction risk. HDL-level evidence is not a CETP-specific verdict; MI is related to, but not identical to, the CAD dataset outcome.
- [ACCELERATE registry](https://clinicaltrials.gov/study/NCT01687998) — protocolSection identification, status, design and eligibility. Phase 3, terminated for insufficient efficacy. High-risk vascular population and composite endpoint, not an exact reproduction of the CAD GWAS.
- [Lilly programme stop (2015)](https://investor.lilly.com/node/24656) — Sponsor release, 2015-10-12. Development for high-risk ASCVD discontinued due to insufficient efficacy; the stated stop was not for safety findings.
- [ACCELERATE results (2017)](https://doi.org/10.1056/NEJMoa1609581) — Abstract and trial results; 2017-05 (month precision); PMID 28514624. Favorable lipid changes did not translate into fewer cardiovascular events in this trial.
- [CETP/HMGCR genetic analysis (2017)](https://doi.org/10.1001/jama.2017.11467) — Abstract / conclusions; JAMA online 2017-08-28; PMID 28846118. Cardiovascular associations tracked apoB reduction in the joint genetic analysis. Do not reduce CETP effects to HDL elevation alone.
- [REVEAL anacetrapib results (2017)](https://doi.org/10.1056/NEJMoa1706444) — Abstract; NEJM online 2017-08-29; PMID 28847206. Anacetrapib reduced major coronary events in REVEAL. Necessary counterexample to a claim that all CETP inhibition fails.
- [Obicetrapib PREVAIL registry](https://clinicaltrials.gov/study/NCT05202509) — protocolSection status and design; source update 2024-06-04. Retrieved Phase 3 ACTIVE_NOT_RECRUITING record. Old registry update, not proof of current recruitment or programme-wide regulatory status.
- [NewAmsterdam 2026 programme update](https://ir.newamsterdampharma.com/news-releases/news-release-details/newamsterdam-pharma-highlights-2025-achievements-and-outlines) — Sponsor release 2026-01-09; PREVAIL section. Reports continuing obicetrapib development. Projections are not achieved outcomes; no global approval status is established here.

## Snapshot boundaries
Curated lifecycle example spanning human genetics, preclinical evidence, clinical development, later interpretation and current class status. Built from existing MVP1 records and explicitly retrieved primary sources. No automatic all-pair timeline search, no MVP2/MVP3 completion, and no live Slack deployment is claimed.
These are original table records, not a new full pipeline run. The urate report belongs to a different example and is not included.
