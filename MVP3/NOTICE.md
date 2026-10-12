# Human-GEM data attribution

The model and annotation data originate from [SysBioChalmers/Human-GEM](https://github.com/SysBioChalmers/Human-GEM/tree/635f533152dc5f7290ce04d12700eaa882273c3e),
release 2.0.0, provided under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The source lock records its exact [license file](https://github.com/SysBioChalmers/Human-GEM/blob/635f533152dc5f7290ce04d12700eaa882273c3e/LICENSE.md)
and [citation instructions](https://github.com/SysBioChalmers/Human-GEM/blob/635f533152dc5f7290ce04d12700eaa882273c3e/README.md).
Retain these notices when redistributing the derived fixture or index. No upstream
endorsement or warranty is implied. This notice does not set a new license for the
user's project code.

The pinned README cites Human2 as Luo et al., *Reconstruction of human metabolic
models with large language models* (2026, in press in that snapshot). It also cites
Human1: Robinson et al., *An atlas of human metabolism*, Science Signaling (2020),
[DOI 10.1126/scisignal.aaz1482](https://doi.org/10.1126/scisignal.aaz1482). Use the
versioned source citation metadata; this implementation does not invent publication
details absent from the pinned release.

Changes made here: YAML ordered mappings and TSV annotations are normalized into a
JSON lookup; derived adjacency lists, Boolean syntax trees, counts and explicit
diagnostics are added. `tests/fixtures/gem/source_excerpt.json` copies selected entity
records into JSON, retaining source row/line references; its graph is deliberately
incomplete. `tests/fixtures/synthetic.py` is wholly invented test data and must never
be presented as a retrieved biological example.
