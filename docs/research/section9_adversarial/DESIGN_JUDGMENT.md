# Design judgment: defects, limits, and things not to “fix” yet

## Findings that should be treated as defects or unsafe claims

- The card-wide attestation overstates a token-membership and regex check as if the prose
  itself had been checked against the evidence.
- Numeric membership is not bound to a field or semantic role. Identifier digits, dates
  and list lengths can be relabelled as scientific quantities.
- Schema-free indexing trusts values that are absent from both the model digest and the
  rendered evidence sections, so the footer can make a literally false visibility claim.
- Sentence-wide negation/disclaimer exemptions can excuse a prohibited positive claim in
  another clause.
- Unicode normalization gaps can change meaning, including the sign of a coefficient,
  without producing a finding.
- Raw Markdown in model fields can create a forged heading/action block within Section 9.
- Unvalidated `metadata.model` text is appended to an otherwise validated section.
- A malicious dict subclass can make `validate()` raise despite its never-raises contract;
  `render_card()` contains the exception, so this is robustness loss rather than prose
  leakage in the tested renderer.

## Scope limitations, not proof that the duplicate gate is useless

- General qualitative truth cannot be established by checking only numbers, identifiers
  and a finite phrase list. Paraphrase penetrations are expected from the documented
  heuristic design, although they still make the strong attestation unsafe.
- The second gate correctly blocks recognized token replay across runs and ordinary
  mutation after gate one. It is valuable defense in depth.
- A recursive/unreadable run produces V0 and fails closed.

## Findings that should not be presented as current deployed exploits

- The original hand-built A1 object is a harness construction. Its semantic behavior is
  reachable through the real model path (`R01`), but arbitrary object injection is not a
  current CLI/Slack input.
- The split-view dictionary and newline-bearing model metadata require an internal,
  cached, or future deserialization boundary that current surfaces do not expose.
- `B01` is deliberately a bad future UI and there is no current Streamlit implementation.
- `ledger.record()` being a no-op without `ledger.start()` is intentional for direct tool
  tests. The defect would be a future product surface treating such a call as a complete
  archived run, not the no-op itself.

## Policy choices not to change from this experiment alone

- Three-significant-digit rounding is explicitly documented in the validator even though
  the prompt asks for digit-for-digit quotation. Aligning prompt and code needs a product
  decision, not a covert test-driven change.
- List lengths are intentionally considered traceable counts. A typed claim system should
  preserve legitimate counts while preventing their reuse as effect sizes.
- A validator cannot prove open-ended scientific prose merely by expanding a regex list.
  Adding every bypass phrase would create a brittle denylist and new false positives.
- No measured behavior was patched on this branch. This preserves the evidence used in
  the paper and avoids invalidating the supplied outputs before review.
