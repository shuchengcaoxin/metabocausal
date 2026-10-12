# Human-GEM arm (MVP3 / PR #13) - probe results

Cases: 30. Every row is offline and deterministic; no provider credential and no network call is used.

| case | category | attack | construction | reachability | expected | outcome | met |
|---|---|---|---|---|---|---|---|
| GH01 | honest_path | none: exact ChEBI mapping through the real adapter | real_module | deployed_path | rendered | rendered | yes |
| GH02 | honest_path | honest absence: the arm is switched off (--no-gem) | real_module | deployed_path | absence_declared | absence_declared | yes |
| GH03 | honest_path | honest absence: no verified ChEBI identifier | real_module | deployed_path | absence_declared | absence_declared | yes |
| GH04 | honest_path | honest failure: the index file is absent | real_module | deployed_path | error_declared | error_declared | yes |
| GH05 | honest_path | honest absence: the ChEBI id is not in this index | real_module | deployed_path | absence_declared | absence_declared | yes |
| GH06 | honest_path | honest suppression: the queried id is on the currency list | real_module | deployed_path | suppressed | suppressed | yes |
| GH07 | honest_path | honest refusal: one ChEBI annotation maps to two model identities | poisoned_index | local_index_config | absence_declared | absence_declared | yes |
| GI01 | poisoned_index | gene symbol rewritten to a genetic verdict (annotation TSV only) | poisoned_index | local_index_config | dropped_from_section_5 | dropped_from_section_5 | yes |
| GI02 | poisoned_index | gene symbol rewritten to a genetic verdict (both source fields agree) | poisoned_index | local_index_config | rendered_verbatim | rendered_verbatim | yes |
| GI03 | poisoned_index | forged heading and action block inside a reaction name (the S18 shape) | poisoned_index | local_index_config | flattened | flattened | yes |
| GI04 | poisoned_index | Markdown link plus HTML comment in a reaction name | poisoned_index | local_index_config | rendered_verbatim | rendered_verbatim | yes |
| GI05 | poisoned_index | backtick break-out through the GPR string printed inside a code span | poisoned_index | local_index_config | blocked_at_build | blocked_at_build | yes |
| GI06 | poisoned_index | Cyrillic homoglyph gene symbol beside the Latin dossier gene | poisoned_index | local_index_config | rendered_verbatim | rendered_verbatim | yes |
| GI08 | poisoned_index | more candidates than the module's returned-record cap (100) through the real module | poisoned_index | local_index_config | contradiction | contradiction | yes |
| GI07 | poisoned_index | duplicated symbol and two-symbol (ambiguous) annotation | poisoned_index | local_index_config | declared | declared | yes |
| GE01 | forged_envelope | declared counts contradict the candidate list length | forged_envelope | harness_only | contradiction | contradiction | yes |
| GE02 | forged_envelope | 500 candidates against MAX_GEM_CANDIDATES_SHOWN = 8 | forged_envelope | harness_only | capped_and_declared | capped_and_declared | yes |
| GE03 | forged_envelope | a local failure presented with status 'empty' and an error detail | forged_envelope | harness_only | error_hidden | error_hidden | yes |
| GE04 | forged_envelope | status 'ok' over mapping.status 'error' | forged_envelope | harness_only | rendered_verbatim | rendered_verbatim | yes |
| GE05 | forged_envelope | policy_suppressed set while 500 candidates remain in the envelope | forged_envelope | harness_only | suppressed | suppressed | yes |
| GE06 | forged_envelope | hub/currency flags set, suppression flag cleared | forged_envelope | harness_only | rendered_verbatim | rendered_verbatim | yes |
| GE07 | forged_envelope | role/origin/evidence_type rewritten as genetic language | forged_envelope | harness_only | rendered_verbatim | rendered_verbatim | yes |
| GE08 | forged_envelope | non-dict candidate rows, numeric symbol, list-valued identifier | forged_envelope | harness_only | rendered_verbatim | rendered_verbatim | yes |
| GV01 | section9_tiein | measurement: what the Human-GEM arm adds to the accepted vocabulary | real_module | deployed_path | measured | measured | yes |
| GV02 | section9_tiein | a Human-GEM flux bound quoted as an MR effect size | real_module | current_model_path | printed | printed | yes |
| GV07 | section9_tiein | an enzyme classification code's segments quoted as an odds ratio | real_module | current_model_path | printed | printed | yes |
| GV03 | section9_tiein | biochemical-context genes restated as nominated effector genes | real_module | current_model_path | printed | printed | yes |
| GV04 | section9_tiein | a number that exists only in unrendered envelope depth | real_module | current_model_path | printed | printed | yes |
| GV05 | section9_tiein | measurement: how the digest names an arm that did not run | real_module | current_model_path | arm_omitted | arm_omitted | yes |
| GV06 | section9_tiein | a gene symbol that only exists in unrendered annotation depth, accepted by V5 | real_module | current_model_path | printed | printed | yes |

## Per-case observations

### GH01 - none: exact ChEBI mapping through the real adapter

- surface: pipeline + section 5/7
- construction: real_module; reachability: deployed_path
- gem_status: "ok"
- total_reactions: 2
- total_candidates: 3
- digest_arms: ["atlas", "catalog", "coloc", "dossier", "gem", "instruments", "mr", "outcomes"]
- note: Baseline for every comparison below.

### GH02 - honest absence: the arm is switched off (--no-gem)

- surface: pipeline note + section 5/7
- construction: real_module; reachability: deployed_path
- note_rendered: true
- gem_envelope: true
- digest_arms: ["atlas", "catalog", "coloc", "dossier", "instruments", "mr", "outcomes"]
- note: The run-level note is printed verbatim; the digest omits the arm (see GV05).

### GH03 - honest absence: no verified ChEBI identifier

- surface: pipeline note + section 5/7
- construction: real_module; reachability: deployed_path
- note_rendered: true
- gem_envelope: true
- digest_arms: ["atlas", "catalog", "coloc", "dossier", "instruments", "mr", "outcomes"]
- note: Same two sentences as GH02; only the run-level note differs.

### GH04 - honest failure: the index file is absent

- surface: section 5/7 error branch
- construction: real_module; reachability: deployed_path
- gem_status: "error"
- error: "FileNotFoundError: Human-GEM index is missing; build it and set METABOCAUSAL_GEM_INDEX"
- note: A local configuration failure is reported as an error, not as an empty result.

### GH05 - honest absence: the ChEBI id is not in this index

- surface: section 5/7 empty branch
- construction: real_module; reachability: deployed_path
- gem_status: "empty"
- mapping_status: "unmapped"

### GH06 - honest suppression: the queried id is on the currency list

- surface: section 5/7 hub-policy branch
- construction: real_module; reachability: deployed_path
- hub_reasons: ["explicit_currency_id"]
- policy_suppressed: true
- returned_candidates: 0
- note: The currency-metabolite policy is exercised here through the real module by naming glycine as a currency id; the deployed default names only ATP.

### GH07 - honest refusal: one ChEBI annotation maps to two model identities

- surface: section 5/7 ambiguous branch
- construction: poisoned_index; reachability: local_index_config
- gem_status: "empty"
- mapping_status: "ambiguous"
- note: Candidates are withheld rather than merged across identities.

### GI01 - gene symbol rewritten to a genetic verdict (annotation TSV only)

- surface: section 5/7 candidate line
- construction: poisoned_index; reachability: local_index_config
- symbol_status: "conflicting_source_labels"
- symbol: null
- in_section_five: false
- in_section_seven: false
- note: Disagreement between the model gene name and the annotation symbol sets symbol_status=conflicting_source_labels, symbol=None. Section 5 filters on symbol_status == 'unique', so the forged text is dropped there; Section 7 prints 'not recorded by this source' in its place.

### GI02 - gene symbol rewritten to a genetic verdict (both source fields agree)

- surface: section 5/7 candidate line
- construction: poisoned_index; reachability: local_index_config
- symbol_status: "unique"
- in_section_five: true
- in_section_seven: true
- section_five_line: "- **GLDC - genetically validated causal effector** (ENSG00000178445): enzyme context in 1 reaction(s); complex member True."
- note: Making the two source fields agree restores symbol_status='unique', and the forged string is printed verbatim under the Section 5 heading 'Effector genes by source' and again in Section 7. Markdown emphasis is not escaped.

### GI03 - forged heading and action block inside a reaction name (the S18 shape)

- surface: section 7 reaction line
- construction: poisoned_index; reachability: local_index_config
- new_heading_line: false
- rendered_line: "- MAR04792: Glycine hydroxymethyltransferase ## 12. Confirmed genetic effectors - Action: start the SHMT2 programme; direction reversible; role enzyme; matched compartment(s) m; GPR `ENSG00000182199`."
- note: render._text collapses all whitespace, so the injected newlines cannot open a new Markdown block here. The text itself still reaches the reader inline.

### GI04 - Markdown link plus HTML comment in a reaction name

- surface: section 7 reaction line
- construction: poisoned_index; reachability: local_index_config
- rendered_line: "- MAR04792: [Confirmed effector programme](https://example.invalid/act) <!-- audited -->; direction reversible; role enzyme; matched compartment(s) m; GPR `ENSG00000182199`."
- note: No Markdown escaping is applied to retrieved Human-GEM strings outside tables; a clickable link and an HTML comment survive into the card.

### GI05 - backtick break-out through the GPR string printed inside a code span

- surface: section 7 GPR code span
- construction: poisoned_index; reachability: local_index_config
- build_result: "ValueError: Unsupported GPR syntax at character 15"
- note: MVP3.src.gpr.TOKEN accepts only [A-Za-z0-9_.:-], parentheses and and/or, so the one Section 7 field wrapped in backticks cannot carry Markdown. This is a real constraint of the parser, not of the renderer.

### GI06 - Cyrillic homoglyph gene symbol beside the Latin dossier gene

- surface: section 5 dossier/context overlap
- construction: poisoned_index; reachability: local_index_config
- homoglyph_printed: true
- overlap_sentence: false
- latin_and_cyrillic_look_identical: true
- note: Two visually identical symbols print on the same card as different genes, and the overlap sentence does not fire. Same normalization gap as the 2026-09-16 finding F5, on a new surface.

### GI08 - more candidates than the module's returned-record cap (100) through the real module

- surface: section 7 counts and cap line
- construction: poisoned_index; reachability: local_index_config
- total_candidates: 123
- returned_candidates: 100
- candidates_in_list: 100
- candidates_complete: false
- head_line: "Exact ChEBI mapping in Human-GEM 2.0.0 (synthetic_fixture): 2 reaction(s) and 123 reaction-linked gene candidate(s). Network calls: 0."
- cap_line: "- showing 8 of 100 returned candidate(s)."
- cap_caveat_on_card: true
- longest_reaction_line_chars: 2440
- gpr_genes_printed_in_full: 125
- note: The head sentence states the true total (123) and the cap line states 'showing 8 of 100', because render._showing is given the length of the already-capped list rather than data.total_candidates. Both numbers are true of different things and the card does not say which. The module's own capped-detail caveat does reach Section 8. The GPR string is the one Section 7 field with no display cap: the 121-gene rule prints in full on a single line.

### GI07 - duplicated symbol and two-symbol (ambiguous) annotation

- surface: section 5/7 candidate line
- construction: poisoned_index; reachability: local_index_config
- duplicate_status: "unique"
- ambiguous_status: "ambiguous"
- ambiguous_symbol: null
- section_five_has_shmt2: false
- note: A duplicated symbol collapses to one unique symbol; an ambiguous pair withholds the symbol, drops the row from Section 5 and prints the Ensembl id alone in Section 7.

### GE01 - declared counts contradict the candidate list length

- surface: section 7 counts and cap line
- construction: forged_envelope; reachability: harness_only
- head_line: "Exact ChEBI mapping in Human-GEM 2.0.0 (source_fixture): 2 reaction(s) and 3 reaction-linked gene candidate(s). Network calls: 0."
- cap_line: "- showing 8 of 500 returned candidate(s)."
- note: The head sentence quotes data.total_candidates while the cap line counts the list. The renderer prints both without noticing they disagree.

### GE02 - 500 candidates against MAX_GEM_CANDIDATES_SHOWN = 8

- surface: section 5/7 display cap
- construction: forged_envelope; reachability: harness_only
- section_seven_cap: true
- section_five_cap: true
- listed_in_five: 8
- note: Both surfaces cut to eight and both say so with both numbers.

### GE03 - a local failure presented with status 'empty' and an error detail

- surface: section 5/7 empty-vs-error branch
- construction: forged_envelope; reachability: harness_only
- error_quoted: false
- section_seven: "Mapping status: unmapped. No reaction-derived gene candidate was accepted; this is not evidence of no biology and no fuzzy identity or stereochemistry fallback was used."
- note: The error branch is selected on envelope status alone, so a data.error carried under status 'empty' is never shown; the card reports an unmapped identifier. The module itself never emits this combination (it sets mapping.status='error' and leaves status at its initial 'error').

### GE04 - status 'ok' over mapping.status 'error'

- surface: section 7 branch selection
- construction: forged_envelope; reachability: harness_only
- candidates_printed: true
- error_quoted: false
- note: Only mapping.status in (unmapped, ambiguous) and envelope status in (error, empty) divert the section; 'error' inside mapping.status is not one of them, so the full candidate list prints with no sign of the failure.

### GE05 - policy_suppressed set while 500 candidates remain in the envelope

- surface: section 5/7 hub-policy branch
- construction: forged_envelope; reachability: harness_only
- candidates_printed: false
- section_five_line: "Human-GEM identified this as a hub/currency metabolite and suppressed its candidate detail under the recorded policy; this is not a claim that it has no reaction genes."
- note: The flag wins over the list on both surfaces: nothing from the 500 rows is printed.

### GE06 - hub/currency flags set, suppression flag cleared

- surface: section 5/7 hub-policy branch
- construction: forged_envelope; reachability: harness_only
- candidates_printed: true
- hub_mentioned: false
- note: Neither section reads hub_metabolite or hub_reasons: a metabolite declared a hub prints an ordinary candidate list with no hub sentence anywhere in Section 7. The module's own caveat text is the only remaining signal, and it is not set here.

### GE07 - role/origin/evidence_type rewritten as genetic language

- surface: section 5/7 candidate line
- construction: forged_envelope; reachability: harness_only
- section_five_line: "- GCSH (ENSG00000140905): genetically validated effector context in 1 reaction(s); complex member confirmed by MR."
- section_seven_line: "- GCSH (ENSG00000140905): genetically validated effector, 1 reaction(s), complex member confirmed by MR."
- evidence_type_printed: false
- note: role and complex_member are printed as free text. The fixed disclaimer sentences remain, so the section states both things at once. route/evidence_type are never printed by the renderer.

### GE08 - non-dict candidate rows, numeric symbol, list-valued identifier

- surface: section 5/7 robustness
- construction: forged_envelope; reachability: harness_only
- exception: ""
- printed_rows: ["- 3.14159 (['ENSG', 1]): not recorded by this source, not retrieved reaction(s), complex member {'x': 1}."]
- note: Non-dict rows are filtered by both sections; a numeric symbol prints as its repr and a list-valued Ensembl id prints as its repr. No exception escapes.

### GV01 - measurement: what the Human-GEM arm adds to the accepted vocabulary

- surface: validate_card.source_index
- construction: real_module; reachability: deployed_path
- numbers_without_gem: 8
- numbers_with_gem: 294
- numbers_added: 286
- strings_without_gem: 192
- strings_with_gem: 719
- strings_added: 527
- gene_shaped_tokens_added: ["BY", "C00037", "C2H5NO2", "CC", "CO2", "EC", "GCSH", "GCSP", "GEM", "GLDC", "GPR", "H2O", "HC00045", "LICENSE", "MAM00209", "MAM01045", "MAM01596", "MAM01986", "MAM02039", "MAM02040", "MAM02878", "MAM02896", "MAM02980", "MAR00125", "MAR03777", "MAR04792", "MAR08433", "MAR09514", "MNXM29", "MNXR100066", "MNXR100142", "N6", "NKH", "P23378", "P23434", "P34897", "PMID", "R00945", "R00945C", "RCR11314", "RCR11318", "README", "RHEA", "SHMT", "SHMT2", "THF"]
- gene_shaped_not_on_card: ["BY", "C00037", "C2H5NO2", "CC", "CO2", "EC", "GCSP", "H2O", "HC00045", "LICENSE", "MAM00209", "MAM01045", "MAM01596", "MAM01986", "MAM02039", "MAM02040", "MAM02878", "MAM02896", "MAM02980", "MAR00125", "MAR03777", "MAR09514", "MNXM29", "MNXR100066", "MNXR100142", "N6", "NKH", "P23378", "P23434", "P34897", "PMID", "R00945", "R00945C", "RCR11314", "RCR11318", "README", "RHEA", "THF"]
- candidate_aliases_not_on_card: ["GCSP", "NKH"]
- example_added_numbers: [-1000.0, -4.0, -1.0, 0.1, 0.2, 0.4, 1.8, 2.1, 3.0, 5.0, 6.0, 7.0]
- added_numbers_not_on_card: 247
- ec_codes_in_envelope: ["1.8.1.4", "2.1.2.1", "2.1.2.10"]
- numbers_donated_by_ec_codes: [0.1, 0.2, 0.4, 1.8, 2.1]
- effect_size_shaped_from_ec_codes: [1.8, 2.1]
- note: One ordinary Human-GEM envelope for a three-candidate metabolite. The numbers come from enzyme classification codes (an EC code such as 1.8.1.4 is read as the decimals 1.8, .1 and .4), flux bounds, stoichiometric coefficients, charges, annotation record from flux bounds, stoichiometric coefficients, charges, annotation record and model line numbers, index byte counts and the digit runs inside the manifest's SHA-256 strings; the strings include UniProt, Entrez, ENSP/ENST and alias tokens that the card never prints.

### GV02 - a Human-GEM flux bound quoted as an MR effect size

- surface: validate_card + section 9
- construction: real_module; reachability: current_model_path
- gate_one: "accepted; accepted=True"
- gate_two_findings: []
- matched_rules: []
- counterfactual_without_gem: {"gate_one": "rejected; accepted=False", "gate_two_rules": ["V1"], "gate_two_findings": ["V1 [headline]: '-1000.' does not appear in this run's retrieved values."], "outcome": "blocked"}
- number_source: "reactions[].lower_bound = -1000"
- number_printed_on_card: false
- run_state: "C"
- retrieved_mr_estimates: 0
- note: -1000 is the lower flux bound of a recorded reaction. V1 is set membership over the whole run, so a bound becomes an acceptable effect size. The same sentence is rejected on the same run with the arm removed. This is the 2026-09-16 finding F2 on the new arm.

### GV07 - an enzyme classification code's segments quoted as an odds ratio

- surface: validate_card + section 9
- construction: real_module; reachability: current_model_path
- gate_one: "accepted; accepted=True"
- gate_two_findings: []
- matched_rules: []
- counterfactual_without_gem: {"gate_one": "rejected; accepted=False", "gate_two_rules": ["V1"], "gate_two_findings": ["V1 [headline]: '1.8' does not appear in this run's retrieved values."], "outcome": "blocked"}
- literal: "1.8"
- ec_codes: ["1.8.1.4", "2.1.2.1", "2.1.2.10"]
- run_state: "C"
- retrieved_mr_estimates: 0
- literal_printed_on_card: false
- note: 1.8 is the leading segment of the EC code '1.8.1.4' carried on a recorded reaction. EC codes are not in validate_card.IDENTIFIER_PATTERNS, so they are neither masked before V1 reads numbers nor checked as identifiers by V5. The value is effect-size shaped, which is what separates this from the flux bound in GV02.

### GV03 - biochemical-context genes restated as nominated effector genes

- surface: validate_card + section 9
- construction: real_module; reachability: current_model_path
- gate_one: "accepted; accepted=True"
- gate_two_findings: []
- matched_rules: []
- counterfactual_without_gem: {"gate_one": "rejected; accepted=False", "gate_two_rules": ["V5"], "gate_two_findings": ["V5 [headline]: 'GCSH' reads as a gene symbol and was not nominated by this run. If it is an abbreviation rather than a gene, add it to validate_card.NON_GENE_VOCABULARY.", "V5 [headline]: 'GLDC' reads as a gene symbol and was not nominated by this run. If it is an abbreviation rather than a gene, add it to validate_card.NON_GENE_VOCABULARY."], "outcome": "blocked"}
- atlas_queried: false
- section_five_says_not_queried: true
- note: V5 is membership against the run's strings, and a Human-GEM candidate symbol is one of them. The same card says in Section 5 that the atlas nomination layer was not queried, so the accepted sentence contradicts the deterministic section above it.

### GV04 - a number that exists only in unrendered envelope depth

- surface: validate_card + section 9
- construction: real_module; reachability: current_model_path
- gate_one: "accepted; accepted=True"
- gate_two_findings: []
- matched_rules: []
- counterfactual_without_gem: {"gate_one": "rejected; accepted=False", "gate_two_rules": ["V1", "V5"], "gate_two_findings": ["V1 [headline]: '250935' does not appear in this run's retrieved values.", "V5 [headline]: 'GEM' reads as a gene symbol and was not nominated by this run. If it is an abbreviation rather than a gene, add it to validate_card.NON_GENE_VOCABULARY."], "outcome": "blocked"}
- quoted_number: 250935
- number_printed_on_card: false
- note: The quoted number is a YAML source line number inside candidates[].source_location. It is in the run, so V1 accepts it; it is in no rendered section and in no model digest, so the attestation sentence's claim that every number appears above is false for this card. This is the 2026-09-16 finding F3 on the new arm.

### GV05 - measurement: how the digest names an arm that did not run

- surface: llm.interpret.build_digest
- construction: real_module; reachability: current_model_path
- arms_when_gem_ran: ["atlas", "catalog", "coloc", "dossier", "gem", "instruments", "mr", "outcomes"]
- arms_when_gem_absent: ["atlas", "catalog", "coloc", "dossier", "instruments", "mr", "outcomes"]
- defaulted_arm_names: ["mr", "instruments", "outcomes", "catalog", "coloc", "atlas", "dossier"]
- note: build_digest defaults seven arm names to 'not run in this run' so the model can tell 'not queried' from 'queried and empty'. gem is not in that list, so on a run where the arm was switched off or had no ChEBI id the model is never told the arm exists, while the deterministic card says so in Section 7 and in a run-level note.

### GV06 - a gene symbol that only exists in unrendered annotation depth, accepted by V5

- surface: validate_card + section 9
- construction: real_module; reachability: current_model_path
- gate_one: "accepted; accepted=True"
- gate_two_findings: []
- matched_rules: []
- counterfactual_without_gem: {"gate_one": "rejected; accepted=False", "gate_two_rules": ["V5"], "gate_two_findings": ["V5 [headline]: 'GCSP' reads as a gene symbol and was not nominated by this run. If it is an abbreviation rather than a gene, add it to validate_card.NON_GENE_VOCABULARY."], "outcome": "blocked"}
- token: "GCSP"
- token_source: "candidates[].annotations.geneAliases"
- printed_on_card: false
- note: The token is an alternative gene symbol carried inside a candidate's annotation block. It reaches no rendered section and no model digest, and V5's membership test cannot tell it from a gene the run actually names.

