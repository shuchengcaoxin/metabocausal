# Human-GEM source modules

- `fetch_model.py`: downloads and verifies the pinned Human-GEM source files.
- `build_index.py`: deterministically builds a checksum-bound local JSON index.
- `gem.py`: exact ChEBI lookup, ambiguity/hub handling and batch mapping.
- `gpr.py`: bounded parser preserving Boolean AND/OR gene rules.
- `acceptance.py` and `verify.py`: source cross-check and reproducible verification.
- `run_batch.py`: batch-ready ChEBI input with per-input diagnostics and reuse.

The shared runtime adapter is `tools/gem.py`; this package itself has no dependency
on the agent, Slack, MR classifier or 1E network clients.
