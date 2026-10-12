# expected_bcb32a9/ — provenance and line-ending note

These files are Zipeng Zhou's committed baseline artifacts, snapshotted from
`docs/research/section9_adversarial/artifacts/` **before** the 2026-09-17 harness run.

## Line endings

This worktree has `core.autocrlf=true` (measured: `git config --get core.autocrlf` → `true`),
and the repository's `.gitattributes` does not mark `docs/research/**` as `-text`. Git therefore
checks these text files out with CRLF on Windows, while the committed blobs use LF.

Consequence: the raw bytes in this directory are **not** identical to the committed blobs for
files that Git converted on checkout. Example measured for `results.csv`:

```
HEAD blob                      len= 10084 CRLF=   0 bareLF=  52 sha=3d7338bfd053f05d
worktree(new run)              len= 10084 CRLF=   0 bareLF=  52 sha=3d7338bfd053f05d
my snapshot(pre-run checkout)  len= 10136 CRLF=  52 bareLF=   0 sha=ee8f7e8e9cde9dde
blob == worktree(new run): True
```

All comparisons in `../DRIFT.md` and `../HASHES.tsv` are therefore made **LF-normalized**, and
the authoritative "expected" bytes are taken from the `HEAD` blobs (which equal Zipeng's
`bcb32a9` blobs for every file in this bundle — the bundle was merged unmodified by PR #17).

Line endings are a checkout artifact of this Windows worktree. They are not a study result.
