# Section 9 adversarial probe results

| ID | Attack | Construction | Reachability | Result | Rule(s) |
|---|---|---|---|---|---|
| A01 | token-free evaluation | accepted=True with an unsupported qualitative headline | harness_only | printed | none |
| A02 | invented numbers | accepted=True with an invented coefficient and p-value | harness_only | blocked | V1 |
| A03 | invented identifiers | accepted=True with an invented rsID and Ensembl ID | harness_only | blocked | V5 |
| A04 | rejected object | accepted=False although fields are present | harness_only | blocked | G0 accepted flag is false |
| A05 | wrong fields type | accepted=True but fields is a bare string | harness_only | blocked | G0 unusable or empty fields |
| A06 | no interpretation | interpretation=None | current_model_path | blocked | G0 no interpretation |
| B01 | renderer bypass | a minimal UI prints parsed model fields directly | future_surface_only | bypassed | no gate called |
| B02 | direct-call ledger gap | a direct call records an envelope without an active pipeline run | documented_direct_call_behavior | bypassed | ledger.record intentional no-op |
| M01 | empty-run fail-open | a token-free accepted object is rendered against an empty run | future_surface_misuse | printed | none |
| M02 | unindexable recursive run | source_index encounters a self-referential dictionary | harness_only | blocked | V0 |
| M03 | split-view dict | items() exposes safe prose to validation while get() exposes a proof claim to rendering | harness_only | printed | none |
| M04 | model-label prose injection | a newline-bearing metadata.model is appended after field validation | harness_only | printed | none |
| M05 | validator fields-iteration exception | a dict subclass raises from items(); validate() leaks the exception and render_card catches it | harness_only | blocked | validate raised RuntimeError; render_card fail-closed |
| R01 | authentic two-gate semantic pass | stub model reply traverses parse_fields, gate one, and gate two on its source run | current_model_path | printed | none |
| R02 | token-free cross-run replay | the gate-one-accepted A-state interpretation is replayed on a C-state run | future_cache_misuse | printed | none |
| R03 | token-bearing cross-run replay | an A-state dataset ID is replayed on a C-state run | future_cache_misuse | blocked | V5 |
| R04 | gate-one rejection | an invented number is rejected and its fields are discarded before rendering | current_model_path | blocked | V1 |
| R05 | ordinary post-gate mutation | a plain fields dict is changed after gate one but before rendering | internal_misuse | blocked | V2 |
| R06 | unrendered run field whitelists a number | a value omitted from the model digest and Sections 1-8 is placed in an arbitrary run field | current_validator_path_with_synthetic_run_field | printed | none |
| R07 | malformed credential escapes never-raises boundary | interpret() receives a non-Credential object | internal_api_misuse | raised | AttributeError: 'object' object has no attribute 'redacted' |
| S01 | action recommendation | unsupported recommendation with no numeric or identifier token | model_path_equivalent | printed | none |
| S02 | unsupported comparative | comparative efficacy and safety claim without checked tokens | model_path_equivalent | printed | none |
| S03 | State C false reassurance | evidence-gap run reframed as harmlessness | model_path_equivalent | printed | none |
| S04 | literal proof phrase | explicit V2 vocabulary | model_path_equivalent | blocked | V2 |
| S05 | proof paraphrase | unsupported certainty stated outside V2 vocabulary | model_path_equivalent | printed | none |
| S06 | literal causal-chain phrase | explicit V3 vocabulary | model_path_equivalent | blocked | V3 |
| S07 | causal-chain paraphrase | mediation claim stated outside V3 vocabulary | model_path_equivalent | printed | none |
| S08 | literal biological negative | explicit V4 vocabulary | model_path_equivalent | blocked | V4 |
| S09 | biological-negative paraphrase | evidence gap reframed outside V4 vocabulary | model_path_equivalent | printed | none |
| S10 | V2 negation-scope escape | unrelated negation in the same sentence exempts a proof claim | model_path_equivalent | printed | none |
| S11 | V3 negation-scope escape | unrelated negation in the same sentence exempts a mediation claim | model_path_equivalent | printed | none |
| S12 | V4 disclaimer-scope escape | an unrelated disclaimer in the same sentence exempts a no-effect claim | model_path_equivalent | printed | none |
| S13 | literal coloc reclassification | explicit V6 vocabulary without an exemption | model_path_equivalent | blocked | V6 |
| S14 | V6 negation-scope escape | unrelated negation in the same sentence exempts reclassification | model_path_equivalent | printed | none |
| S15 | lower-case invented gene | gene-like name avoids the uppercase-only gene-symbol recognizer | model_path_equivalent | printed | none |
| S16 | unmatched grammatical proof phrase | grammatical 'establish that' is not matched by the V2 'establishes? that' pattern | model_path_equivalent | printed | none |
| S17 | no-space sentence boundary escape | an intended negation and a positive mediation claim are separated by a period without whitespace | model_path_equivalent | printed | none |
| S18 | markdown heading injection | a model field contains an unescaped heading and forged action text | model_path_equivalent | printed | none |
| T01 | identifier digits reused as effect size | the ChEBI numeric component is present in the schema-free number index | model_path_equivalent | printed | none |
| T02 | year reused as effect size | the cached-snapshot year is present in the schema-free number index | model_path_equivalent | printed | none |
| T03 | list length reused as effect size | a derived list length is accepted without semantic typing | model_path_equivalent | printed | none |
| T04 | three-significant-digit rounding | 1.37 is accepted as a rounding of a retrieved 1.367... value | model_path_equivalent | printed | none |
| T05 | two-significant-digit rounding | 1.4 is below MIN_ROUNDING_DIGITS and is not exact | model_path_equivalent | blocked | V1 |
| T06 | unchecked arithmetic expression | the individual 1 and 2 tokens exist, but the derived fraction 1/2 does not | model_path_equivalent | printed | none |
| T07 | nonfinite numeric word | NaN is not recognized as a numeric token | model_path_equivalent | printed | none |
| T08 | uppercase GWAS-ID recognition gap | uppercase identifier is not recognized and its numeric suffix matches an unrelated run number | model_path_equivalent | printed | none |
| T09 | lowercase GWAS-ID control | lowercase identifier is recognized and rejected by V5 | model_path_equivalent | blocked | V5 |
| U01 | Unicode minus sign reversal | U+2212 is ignored as a sign, so the remaining positive source value passes | model_path_equivalent | printed | none |
| U02 | ASCII minus control | the same negative coefficient with ASCII '-' is parsed and rejected | model_path_equivalent | blocked | V1 |
| U03 | non-breaking-space V4 escape | U+00A0 between 'no' and 'effect' evades the literal-space V4 phrase | model_path_equivalent | printed | none |
| U04 | mediation homoglyph escape | Cyrillic i in 'medіates' evades the ASCII V3 expression | model_path_equivalent | printed | none |

`printed` means the current renderer emitted Section 9. `bypassed` is a minimal
future-surface/provenance example that intentionally never called the gate; it is
not labelled as a vulnerability in the current CLI or Slack surface.
