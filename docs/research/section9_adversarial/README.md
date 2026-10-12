# Section 9 closed-boundary adversarial study

This directory is the reproducibility bundle for the September 16 AgenticLS study of
MetaboCausal's model-written Section 9. It measures the implementation as found at
development baseline `bcb32a9`; it does not repair the measured behavior.

## A1 decision

The hand-built `accepted=True` object is **not directly injectable through the
renderer-backed CLI (`render.py --interpret`) or Slack entry point**. Both measured
surfaces obtain their object from `llm.interpret()`. The legacy `agent.py` executable is
outside this study's measured boundary and must not be included in claims about the two
gates. The underlying A1 finding is nevertheless reachable: case `R01` passes a
deterministic model reply through the real parser and first validator, and the same
unsupported token-free recommendation is accepted by the renderer's second validator.
The paper should retain the result as **token-free model prose accepted by both gates**,
not describe it as object injection into a deployed interface.

## Reproduce

Use Python 3.12 from the repository root. No network or API credential is required.

```bash
python scripts/probe_section9.py
python -m unittest tests.test_probe_section9 tests.test_section_nine \
  tests.test_validate_card tests.test_interpret
```

The first command regenerates `artifacts/` and exits non-zero if an expected result
changes. It exercises 51 deterministic cases over the frozen A/B/C fixtures. Cases
`R01`–`R07` exercise the real `llm.interpret()` and/or renderer paths with an offline fixed
`Reply`; this removes provider availability and model sampling from the boundary test.

## Contents

- [REPORT.md](REPORT.md): short paper-facing English analysis.
- [DESIGN_JUDGMENT.md](DESIGN_JUDGMENT.md): what is a defect, a scope limitation, or
  behavior that should not be “fixed” on the evidence of this experiment alone.
- [artifacts/RESULTS.md](artifacts/RESULTS.md): human-readable result table.
- `artifacts/results.csv` and `artifacts/results.json`: machine-readable results.
- `artifacts/section9_outputs/`: exact output for every penetration, including the
  renderer's attestation sentence.
- `artifacts/full_cards/`: complete renderer output for every penetration. The renderer
  generates eleven sections; case `S18` deliberately inserts an additional Markdown
  heading inside Section 9, which is the measured behavior rather than a twelfth system
  section.
- `artifacts/manifest.json`: revision, environment, input/code hashes and outcome counts.
- `ai_runs/`: exact prompts and reports from four independent Luna xhigh discovery
  reviews plus an Astra low final delivery review. The deterministic harness independently
  rechecks the selected claims. Interim case counts reflect when each parallel review
  finished; `artifacts/manifest.json` is authoritative for the final 51-case suite.
- `logs/`: command and test receipts from the final run.

## Repository baseline note

On 2026-09-16, `origin/main` had been force-replaced by an unrelated-root, static public
demo at `3359f1d`; it no longer contained `render.py`, `validate_card.py`, or `llm/`.
This research branch therefore starts from the last integrated development baseline
`bcb32a9`, which contains the code named in the assignment. The exact source hashes in
`artifacts/manifest.json` are the authority for the tested implementation.

## Interpretation cautions

`printed` means the current renderer emitted Section 9. `blocked` means it fell back to
the fixed pending sentence. `bypassed` is reserved for minimal future-surface examples
that intentionally do not call the gate; those rows are not claims about a deployed
Streamlit interface. Reachability is recorded per row and must be preserved when quoting
the results.
