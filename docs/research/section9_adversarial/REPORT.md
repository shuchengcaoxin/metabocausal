# Adversarial evaluation of the Section 9 boundary

We tested the claim that unchecked model prose cannot reach a MetaboCausal card. The 51
offline cases cover token-free assertions, prohibited-claim paraphrases, cross-run replay,
numeric/identifier traceability, malformed runs, gate consistency, and minimal future
surface failures. Most exercise the renderer directly; decisive cases pass a fixed reply
through `llm.interpret()` and its first validator before renderer revalidation. Frozen
A/B/C fixtures make results deterministic.

**A1 is substantively valid but must be framed narrowly.** The renderer-backed CLI
(`render.py --interpret`) and Slack caller do not accept arbitrary external
`Interpretation` objects, so the original hand-built object is not a deployed
object-injection exploit. The legacy `agent.py` executable is outside the measured
boundary. However, the same unsupported sentence is accepted when returned as model JSON
and then passes gate two. Token-free prose can therefore reach a current card through the
measured model path. It can also be replayed from State A onto State C, while replay
containing an A-specific identifier is correctly blocked by V5.

Three penetration classes matter. First, unsupported recommendations, comparisons,
reassurance, proof and mediation paraphrases pass when they contain no recognized token or
listed phrase. Sentence-wide negation/disclaimer exemptions can suppress V2, V3, V4 and
V6 for a positive claim in another clause. ASCII-oriented parsing also admits punctuation,
homoglyph and whitespace variants. Most notably, U+2212 is not treated as a sign:
`−1.367` is read as the retrieved positive `1.367` and printed, whereas ASCII `-1.367`
is rejected.

Second, numeric traceability is untyped membership. `source_index()` walks identifiers,
dates, notes and list lengths, allowing a ChEBI numeric component, snapshot year, or list
length to be relabelled as an “effect size.” An arbitrary hidden run field also whitelists
a number absent from both the model digest and Sections 1–8, making the footer's “appears
in the sections above” sentence false. Raw Markdown fields can additionally create a
forged heading and action block inside Section 9.

Third, trust-boundary probes clarify scope. An empty run accepts token-free prose; a
split-view dictionary can expose safe text during validation and different text during
rendering; and newline-bearing model metadata is appended unvalidated. These are
harness/future-deserialization risks, not current remote-user paths, because normal parsing
creates a plain dictionary and registry labels are fixed. Conversely, a recursive run
fails closed with V0, ordinary post-gate mutation is caught, and token-bearing replay is
rejected. The duplicate gate therefore provides real defense in depth.

The root cause is that V1/V5 establish token membership, not whether a token supports its
claimed role, while V2, V3, V4 and V6 are explicitly heuristic lexical guards. The
printed attestation can consequently be read as stronger than the check performed.

We did not patch measured behavior. Deterministic fallback, strict rejection of recognized
untraceable tokens, renderer revalidation, and fail-closed rendering are useful.
Three-digit rounding, list-length counts, and direct-call ledger no-op behavior are
documented policy choices, not automatic bugs. A reviewed redesign should bind claims to
typed fields, normalize Unicode, scope negation, sanitize metadata/Markdown, and narrow the
attestation. Prompt-injection susceptibility and stochastic provider behavior remain
unmeasured.
