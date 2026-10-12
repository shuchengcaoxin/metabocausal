"""Why F4 passes on current main: the rule matches and a same-sentence exemption clears it.

Reads validate_card's live patterns and replays the exemption decision in
`_check_language()` for each F4 sentence, so the pass is attributed to the sentence-wide
exemption rather than to a pattern that failed to match.  Read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import validate_card                                     # noqa: E402

SENTENCES = [
    ("S10", "V2",
     "The missing arm was not queried, but the retrieved evidence proves causality."),
    ("S11", "V3",
     "Colocalisation was not queried, but the target mediates the effect."),
    ("S12", "V4",
     "The source does not mean the estimate is unavailable; there is no effect."),
    ("S14", "V6",
     "Colocalisation was not queried, but it upgraded the state."),
    ("M9", "V3",
     "The marker mediates the disease effect, although mediation was not tested."),
    ("U5", "V2",
     "The result cannot prove the effect, but it proves the effect."),
    ("X14", "V4",
     "There is no effect, although this is not evidence of a biological negative."),
    ("V6-3", "V6",
     "H4 evidence did not upgrade the pair to State A, but H4 evidence upgraded the "
     "pair to State A."),
]

RULES = {rule: (pattern, negatable) for rule, _, pattern, negatable in
         validate_card.LANGUAGE_RULES}


def main() -> int:
    print(f"validate_card.py loaded from {validate_card.__file__}")
    print()
    for case, rule, text in SENTENCES:
        pattern, negatable = RULES[rule]
        parts = validate_card._sentences(text)
        exemption = validate_card.NEGATION if negatable is True else negatable
        hit = pattern.search(text)
        excuse = exemption.search(text) if exemption else None
        findings = validate_card._check_language("headline", text)
        print(f"[{case}] rule {rule}")
        print(f"  sentences after _sentences(): {len(parts)}")
        print(f"  {rule} pattern matches      : {bool(hit)} "
              f"{'-> ' + repr(hit.group(0)) if hit else ''}")
        print(f"  exemption used             : "
              f"{'NEGATION' if negatable is True else 'V4_DISCLAIMER'}")
        print(f"  exemption matches          : {bool(excuse)} "
              f"{'-> ' + repr(excuse.group(0)) if excuse else ''}")
        print(f"  findings from _check_language(): {[f.rule for f in findings]}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
