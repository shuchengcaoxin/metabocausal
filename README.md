# MetaboCausal

MetaboCausal is an evidence agent for metabolite–disease questions. A user enters a metabolite and a disease, in Slack, a web app or the command line, and gets back an evidence card. Code retrieves and classifies the evidence; an LLM writes only a short summary; a validator checks that summary against the records retrieved in the run.

This repository accompanies the paper *Traceable Is Not Supported: A Layered Metabolite–Disease Evidence Agent and What Its Validator Missed* (Agentic AI for Biological Discovery workshop, NeurIPS 2026). It contains the code, the reference data needed to run it, the tables extracted from published studies, and the test cases and results of the adversarial audit described in the paper.

## What the card contains

1. **Genetic evidence.** Existing Mendelian randomisation (MR) results from EpiGraphDB (MR-EvE estimates, Hemani et al. 2017). The agent does not run MR itself. When no result is found, it checks whether the data needed for MR exist (IEU OpenGWAS, GWAS Catalog). Code assigns one of three evidence states: A (retrieved MR), B (no existing MR result, but analysis-ready) or C (evidence gap). The states describe how far the existing evidence goes, not causal certainty.
2. **Effector genes.** Genes that change the metabolite's level, from a metabolite–locus–gene atlas compiled from published studies.
3. **Drug development** for the top effector genes: links to the disease (Open Targets), drugs and compounds (ChEMBL), and clinical trials (ClinicalTrials.gov) on a timeline.

Two further layers are in the code but are not used to set the evidence state: a literature-screening layer that extracts MR estimates from published studies found through Europe PMC (`MVP2/`), and a background lookup of the enzymes in the metabolite's reactions from Human-GEM (`MVP3/`, a small excerpt is included; see `MVP3/NOTICE.md`).

## Run it

Python 3.12. From the repository root:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt        # Windows: .venv\Scripts\python.exe
.venv/bin/python render.py "urate|gout" --out cards/demo_urate.md
```

The demo uses cached data and needs no API key. Live queries read keys from a local `.env` that follows `.env.example`; never commit it. The LLM summary is optional:

```bash
.venv/bin/python -m llm.cli --list
.venv/bin/python render.py "urate|gout" --interpret --provider claude --out cards/demo_urate.md
```

If the model, the key or the validator rejects the summary, the card is printed without it. `app.py` is the Streamlit web app (`streamlit run app.py`); `slack_app.py` is the Slack bot (Socket Mode, tokens in `.env`).

Core offline tests:

```bash
.venv/bin/python -m unittest tests.test_classify tests.test_render tests.test_plots tests.test_pipeline_offline tests.test_slack_format tests.test_coloc tests.test_review_regressions tests.test_1a_ontology_id tests.test_tools_registry tests.test_llm tests.test_validate_card tests.test_interpret tests.test_section_nine tests.test_llm_cli
```

Some other tests call live databases and can fail when a service is down. A few tests need the publishers' original supplementary files, which are not redistributed here (see below); they error without them.

## Where things are

| Path | Contents |
|---|---|
| `pipeline.py`, `classify.py`, `render.py`, `tools/` | Retrieval, evidence states and card rendering |
| `validate_card.py`, `llm/`, `prompts/` | LLM summary layer and the validator |
| `slack_app.py`, `app.py` | Slack bot and web app |
| `data/` | Cached reference data used at run time |
| `MVP2/` | Literature-screening layer; `MVP2/data/extracted/` holds the MR estimates extracted from published studies |
| `MVP3/` | Human-GEM background lookup |
| `demo/genetic-insights/` | Clinical-trial timeline figures and the demo viewer |
| `docs/research/section9_adversarial/` | Audit test cases, outputs, re-test results (`rerun_2026-09-17/`) and fixes (`fixes_2026-09-17/`) |
| `examples/` | Example cards |

## Source papers for the extracted tables

The tables in `MVP2/data/extracted/` were extracted from the supplementary files of these studies. The original supplements are not included; download them from the publishers.

- Shin et al. An atlas of genetic influences on human blood metabolites. *Nature Genetics* 2014. doi:10.1038/ng.2982
- Chen et al. Genomic atlas of the plasma metabolome prioritizes metabolites implicated in human diseases. *Nature Genetics* 2023. doi:10.1038/s41588-022-01270-1
- Yin et al. Assessing the potential causal effects of 1099 plasma metabolites on 2099 binary disease endpoints. *Nature Communications* 2025. doi:10.1038/s41467-025-58129-2
- Mapping the plasma metabolome to human health and disease in 274,241 adults. *Nature Metabolism* 2025. doi:10.1038/s42255-025-01371-1

## Team

Built at the AI Tinkerers Montréal hackathon (September 2026). Contributions are listed in [CONTRIBUTORS.md](CONTRIBUTORS.md).

## Licence

No licence is granted at this time. The code and data are shared so that readers can inspect and reproduce the paper; please contact the authors before reusing them.
