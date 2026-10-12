# Final execution and test receipt

- Date: `2026-09-17 UTC`
- Branch: `research/section9-adversarial-probes`
- Product baseline under test: `bcb32a91071b93cacaa62cd7487abb2d991baeb7`
- Python: `3.12.4`
- Alliance modules: `StdEnv/2023`, `python/3.12.4`, `scipy-stack/2024a`
- Isolated environment:
  `/scratch/zpoints/MetaboCausal/venvs/metabocausal-shared-py312`
- Network/provider API used by the probe: no

## Publication probe

```text
python scripts/probe_section9.py
```

Result: exit `0`; 51 cases; 31 `printed`, 17 `blocked`, 2 explicitly labelled
future-surface `bypassed` examples, and 1 `raised` contract case. All declared
expectations matched. The full per-case stdout receipt is
[`../artifacts/run.log`](../artifacts/run.log); source/input hashes and the execution
environment are in [`../artifacts/manifest.json`](../artifacts/manifest.json).

## Regression suite

```text
python -m unittest \
  tests.test_classify tests.test_render tests.test_plots \
  tests.test_pipeline_offline tests.test_slack_format tests.test_coloc \
  tests.test_review_regressions tests.test_1a_ontology_id \
  tests.test_tools_registry tests.test_llm tests.test_validate_card \
  tests.test_interpret tests.test_section_nine tests.test_llm_cli \
  tests.test_mvp3_integration tests.test_probe_section9
```

Result:

```text
Ran 613 tests in 18.936s

OK (skipped=2)
```

The first attempt omitted `scipy-stack/2024a` and failed during collection of
`tests.test_plots` because `matplotlib` was unavailable. This was an environment setup
failure, not a code failure. After loading the documented Alliance module and rerunning
the identical suite, the result above passed.

## Artifact and syntax audit

Checks performed:

- `py_compile` passed for the probe and its regression test.
- 51 results have unique case IDs.
- Every case matched its declared expected outcome.
- 33 exact Section 9 outputs exist (31 renderer penetrations plus 2 labelled bypass
  examples).
- 31 complete card renderings exist, one for every renderer penetration. Each renderer
  generated its standard 11 sections; `S18` additionally contains the deliberately
  injected heading being measured.
- `R06`'s hidden value appears only in Section 9, confirming it was not displayed in the
  deterministic evidence sections.
- `git diff --check` passed.

Observed harmless cluster message during Python startup:

```text
logger: socket /dev/log: No such file or directory
```

It did not change exit status or test results.
