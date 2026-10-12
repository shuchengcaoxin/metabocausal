# Discovery, selection and challenge protocol

## Scope

The main product direction is metabolite → disease. Broad acquisition prioritizes metabolome-wide human MR studies with usable results, including studies spanning many disease outcomes. A title containing “metabolome-wide” does not by itself establish MR or direction. Metabolite measurements, ratios and lipoprotein measures retain their source type; do not silently count them all as distinct chemically resolved small molecules.

Disease-specific metabolome-wide MR studies can fill gaps. Targeted single-metabolite papers remain relevant to a user's question or a challenge search. Reverse MR, observational PheWAS and genetic locus/gene annotation can be retained as separate context, but do not become forward MR rows.

## Retrieval duties

| Service | Planned use | Record when unavailable |
| --- | --- | --- |
| Europe PMC | Biomedical search, identifiers, abstracts, available full text and supplements. | Query, status/reason, time, partial coverage and next action. |
| Semantic Scholar | Complementary search, references, citations and related-paper discovery. | Missing key, throttling or unavailable response; continue useful Europe PMC work and report the gap. |

Use locally supplied credentials when required. Never copy API keys into request logs. Honour current service limits with bounded retries. A credential name or provider setting is configuration; the secret value is not project data.

Do not simply intersect the two services and discard papers found by only one. Merge their records by verified identifiers, preserving both discovery paths. A published paper and its preprint belong to one version family. Citation count, journal name, retrieval rank and agreement between search engines are not measures of causal validity.

## Compare evidence on explicit dimensions

For each study record a concise source-backed observation or `not reported` for:

- relevance to the requested metabolite, disease and causal direction;
- population, ancestry, assay and exposure/outcome datasets;
- instrument selection, strength, harmonisation and potential sample overlap;
- MR method, effect scale, uncertainty and multiple-testing approach;
- sensitivity analyses, directionality checks and relevant colocalisation, if provided;
- replication or disagreement, noting shared samples and reused GWAS;
- availability and completeness of the actual results, including whether only selected significant findings are published;
- corrections, retractions and article version where discoverable.

These are separate observations, not an unvalidated composite causal score. Missing optional evidence lowers what can be concluded; it does not erase an otherwise usable MR result. Missing effector genes do not disqualify MR evidence.

The decision ledger records `include`, `exclude` or `unresolved`, with the reason and source location. Review articles can help discovery but do not supply original MR estimates unless their underlying source is retrieved and verified.

## One bounded investigation

Save an explicit run configuration: query scope, synonym limit, request/time budget, maximum rounds and stopping rule. Start with relevance queries and at least one deliberate challenge query. After screening, identify gaps and propose a targeted follow-up. If a second round is not run, say why. Exhausting the budget does not mean the literature has been exhaustively searched.

Table extraction uses source values directly. For prose, preserve a short verified passage and its section/page; do not attach an abstract's estimate to a different pair covered elsewhere in the paper. A source record without usable numbers can remain unresolved rather than becoming a fabricated estimate.

Separate `estimated_direction`, `statistical_support`, `causal_direction` and `agreement_with_other_studies`. A protective estimate is not inherently “supporting” without a defined hypothesis. A non-significant result is not proof of no effect, and reverse MR is not automatically a contradiction of forward MR. Do not force every record into a binary proponent/opponent label.

## Required run outputs

1. Query/API ledger and raw returned records.
2. Deduplicated candidate papers and version families.
3. Screening decisions and evidence-quality observations.
4. Acquisition manifest linking actual source files.
5. Extracted MR records with source locations and validation results.
6. Challenge searches, findings, unresolved gaps and stopping reason.

Use one output file per task or run, then merge through a reproducible step. Several developers must not append to the same live ledger.

## Official service references

- [Europe PMC REST service](https://europepmc.org/RestfulWebService)
- [Europe PMC developer resources](https://europepmc.org/developers)
- [Semantic Scholar API](https://www.semanticscholar.org/product/api)
- [Semantic Scholar API tutorial](https://www.semanticscholar.org/product/api/tutorial)

These services supply discovery and source access. Study selection remains a documented scientific decision.
