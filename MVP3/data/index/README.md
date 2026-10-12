# Generated lookup artifacts

Build an index in scratch and set `METABOCAUSAL_GEM_INDEX` to its exact path. If no
environment variable is supplied, lookup checks `MVP3/data/index/human-gem-2.0.0.json`.
Missing files return an error envelope; the module does not silently use test fixtures.

Each index has a sibling `<index>.manifest.json` with its SHA-256, byte count, source
manifest, schema, graph counts and builder file hashes. Query verifies hash and size
on every read. JSON decoding is cached for up to two byte-identical indexes; outputs
are copied, so caller mutation cannot change future results. Replacement/corruption
cannot hide behind a stale filename/mtime cache.

The index bytes are deterministic for fixed input/model/parser behavior. Creation
timestamps belong to the sidecar, not the index. Builder refuses to overwrite either
file. Interrupted creation can leave an incomplete pair, which lookup refuses; create
a new versioned path instead of overwriting an old valid artifact.

This checksum identifies an artifact; it is not a cryptographic signature establishing
that an arbitrary third-party manifest is trustworthy. Use the committed source lock
and the supplied builder, or an independently reviewed artifact with a recorded hash.
