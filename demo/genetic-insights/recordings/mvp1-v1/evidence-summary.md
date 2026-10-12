# MetaboCausal — Urate · SLC2A9 · Gout

Snapshot: mvp1-urate-gout-2026-09-12-v1 | Checked: 2026-09-12
Curated recording demo · saved evidence

Inspect an existing urate–gout finding, the SLC2A9 gene context, and the clinical history of a related urate-lowering treatment.

## The question

For urate and gout, what genetic evidence is already available, what gene context can we explain, and what can related clinical experience teach a research team?

[MVP1 urate–gout MR record](https://epigraphdb.org/mr) · [MVP1 SLC2A9 annotation](https://doi.org/10.1038/ng.2982)

## Retrieved genetic evidence

The selected MVP1 record contains a positive pre-computed MR estimate for urate and gout. It was retrieved from MR-EVE, not recomputed here. Method and deposited dataset IDs remain attached to the original values.

[MVP1 urate–gout MR record](https://epigraphdb.org/mr)

## Gene context: SLC2A9

The project atlas nominates SLC2A9 by proximity to rs938554. Separately, the 2008 paper provides human genetic and experimental evidence for urate transport. These are different evidence types and remain separately attributed.

[MVP1 SLC2A9 annotation](https://doi.org/10.1038/ng.2982) · [Vitart et al., Nature Genetics (2008)](https://doi.org/10.1038/ng.106) · [Caulfield et al., PLoS Medicine (2008)](https://pubmed.ncbi.nlm.nih.gov/18842065/)

## Related clinical experience

Febuxostat lowers urate by inhibiting xanthine oxidase. It is included through the direct urate-lowering route, not as an SLC2A9-targeted treatment. CARES adds a cardiovascular-safety question in a specific gout population.

[FDA labeling record — Uloric](https://api.fda.gov/drug/label.json?search=openfda.brand_name%3A%22ULORIC%22&limit=1) · [ClinicalTrials.gov — CARES](https://clinicaltrials.gov/study/NCT01101035)

## What to check next

A molecule-level genetic finding does not settle the safety of a particular drug. Review the MR design and missing diagnostics, then evaluate target mechanism, intended population and clinical endpoints separately.

[MVP1 urate–gout MR record](https://epigraphdb.org/mr) · [MVP1 SLC2A9 annotation](https://doi.org/10.1038/ng.2982) · [White et al., NEJM (2018)](https://doi.org/10.1056/NEJMoa1710895)

## What remains uncertain

Colocalisation and gene-QTL evidence were not queried in the selected baseline record. Nearest-gene assignment does not prove mediation. MR confidence-interval scale and level are unspecified in the source. This selected chronology is not an exhaustive clinical review.

[MVP1 urate–gout MR record](https://epigraphdb.org/mr) · [MVP1 SLC2A9 annotation](https://doi.org/10.1038/ng.2982)

## Genetic Insights

Febuxostat acts through xanthine oxidase inhibition. SLC2A9 is the genetic context here, not its drug target. Chronology does not establish that genetics drove the development decision.

### 2008-03-09 — SLC2A9, urate & gout
Genetic evidence | Gene / metabolite / disease evidence
Human genetic associations and urate-transport experiments connect SLC2A9 with urate handling and gout.
[Vitart et al., Nature Genetics (2008)](https://doi.org/10.1038/ng.106)

### 2009-02-13 — Febuxostat approved
US approval | Direct urate-lowering intervention context
FDA approved febuxostat for hyperuricemia in adults with gout. It lowers urate through xanthine oxidase inhibition, a different mechanism from SLC2A9 transport.
[FDA original febuxostat approval (2009)](https://www.accessdata.fda.gov/drugsatfda_docs/appletter/2009/021856s000ltr.pdf) · [FDA labeling record — Uloric](https://api.fda.gov/drug/label.json?search=openfda.brand_name%3A%22ULORIC%22&limit=1)

### 2010-04-23 — CARES begins
Clinical trial | Safety in the specified gout population
Randomized febuxostat versus allopurinol cardiovascular-safety study in people with gout and cardiovascular comorbidities. Registry phase: Phase 3; official title: Phase 3B.
[ClinicalTrials.gov — CARES](https://clinicaltrials.gov/study/NCT01101035)

### 2018-03-12 — Benefits & risks diverge
Clinical results | Trial-specific safety result
The primary cardiovascular composite met noninferiority; cardiovascular and all-cause mortality were higher with febuxostat than allopurinol in CARES.
[White et al., NEJM (2018)](https://doi.org/10.1056/NEJMoa1710895)

### 2019-02-21 — US boxed warning
Label update | US regulatory update
FDA approved a boxed warning and a narrower indication following CARES. This is a safety-related label change, not a withdrawal of all urate-lowering treatments.
[FDA label-change approval (2019)](https://www.accessdata.fda.gov/drugsatfda_docs/appletter/2019/021856Orig1s013ltr.pdf)

## Latest retrieved status

NCT01101035: PHASE3 — COMPLETED
CARES cardiovascular-safety study in gout with cardiovascular comorbidities
Registry last updated: 2018-06-14; checked: 2026-09-12.
US approval with a cardiovascular-death boxed warning and restricted indication in the retrieved label.
Retrieved label effective date: 2025-12-24.
Not assessed beyond this selected study and label.
[ClinicalTrials.gov — CARES](https://clinicaltrials.gov/study/NCT01101035) · [FDA labeling record — Uloric](https://api.fda.gov/drug/label.json?search=openfda.brand_name%3A%22ULORIC%22&limit=1)

## Module status
- MVP1: Saved evidence available. Existing MR record, atlas annotation and archived full report.
- Genetic Insights: Curated example ready. Five source-linked milestones; automatic all-pair preparation remains integration work.
- Jingrui · MVP2: Awaiting accepted output. Seed papers and Europe PMC literature evidence.
- Ziwei · MVP2: Awaiting accepted output. Semantic Scholar evidence, merged by paper identity.
- Zipeng · MVP3: Awaiting accepted output. Human-GEM biochemical context.
- Slack: Export ready; live delivery unverified. Same snapshot produces Slack text and attachments; Zhang Hao connects the bot.
- LLM interpretation: No model run for this demo. The visible summary was prepared for the saved example. OpenAI/Claude code support is separate.

## Sources
- [MVP1 urate–gout MR record](https://epigraphdb.org/mr) — metabolite_disease.csv, CSV record 8815 (header = 1). Exact original row is included in provenance. The web link identifies the database; the saved row establishes this snapshot.
- [MVP1 SLC2A9 annotation](https://doi.org/10.1038/ng.2982) — triples.csv.gz, decompressed CSV record 843481 (header = 1); atlas rs938554. Source gene attribution is nearest, Shin 2014. This is a candidate annotation, not confirmed mediation.
- [Vitart et al., Nature Genetics (2008)](https://doi.org/10.1038/ng.106) — Abstract; online publication 2008-03-09; PMID 18327257. Genetic associations with urate/excretion/gout and experimental urate transport. Added for this curated demo.
- [Caulfield et al., PLoS Medicine (2008)](https://pubmed.ncbi.nlm.nih.gov/18842065/) — Abstract; 2008-10 (month precision); DOI 10.1371/journal.pmed.0050197. Functional urate-transport evidence; do not treat a metadata day of 01 as a verified publication day.
- [FDA original febuxostat approval (2009)](https://www.accessdata.fda.gov/drugsatfda_docs/appletter/2009/021856s000ltr.pdf) — NDA 21-856 original approval; February 13, 2009, also referenced in the 2019 supplement letter. US regulatory event; not proof of the SLC2A9 mechanism.
- [ClinicalTrials.gov — CARES](https://clinicaltrials.gov/study/NCT01101035) — protocolSection: identificationModule, statusModule, designModule, eligibilityModule. Gout participants with cardiovascular comorbidities. Cardiovascular safety outcome; not a gout-onset prevention trial.
- [White et al., NEJM (2018)](https://doi.org/10.1056/NEJMoa1710895) — Abstract; published online 2018-03-12; PMID 29527974. Noninferior primary cardiovascular composite; higher cardiovascular and all-cause mortality with febuxostat versus allopurinol in this trial population.
- [FDA label-change approval (2019)](https://www.accessdata.fda.gov/drugsatfda_docs/appletter/2019/021856Orig1s013ltr.pdf) — Pages 1 and 3; signature dated 2019-02-21. CARES-related labeling change, boxed warning and modification of indication.
- [FDA labeling record — Uloric](https://api.fda.gov/drug/label.json?search=openfda.brand_name%3A%22ULORIC%22&limit=1) — label ID 16c36a5a-2f72-4df7-aa6f-1ca27a39404f; effective_time 2025-12-24; mechanism_of_action, indications_and_usage, boxed_warning. Retrieved label retains a cardiovascular-death boxed warning and a restricted gout indication. One selected label record; not an exhaustive labeling or global programme search.

## Snapshot boundaries
Curated primary-source supplement to existing MVP1 data. Not generated by the unfinished MVP2/MVP3 pipeline.
Separate older run with 22 MR rows; do not combine its counts with the selected September 11 baseline row or newly prepared timeline.
