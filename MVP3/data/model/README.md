# Pinned source assets

`source.lock.json` identifies Human-GEM **2.0.0**, commit
`635f533152dc5f7290ce04d12700eaa882273c3e`, and the SHA-256 of every required file.
The newer 2.0.1 release is not silently substituted. A version upgrade requires a
new lock, regenerated index, fixture check and acceptance report.

Full YAML, three TSV files, README, license and version file are downloaded to an
explicit directory outside Git. In this workspace use `/scratch/zpoints/MetaboCausal`.
Acquisition is an explicit preparation command, never an implicit tool-query action.
Existing files are reused only after their hashes match; mismatches are not overwritten.
Each fetch command writes its own receipt, including failures and verified-cache reuse.

The source's `genes.tsv` supplies symbols. Missing/multiple symbols or disagreement
with the model gene name are kept unresolved; aliases and remembered symbols are not
used to repair them. Missing trailing annotation fields stay null with a diagnostic.
Malformed ChEBI tokens remain in raw annotations but are excluded from lookup keys.
