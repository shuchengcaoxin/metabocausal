"""What role does the quoted number actually play in the rendered card?

F2's substance is that V1 checks membership, not role.  Part A renders the full card
for each F2 probe case on current HEAD and prints every line of Sections 1-8 that
contains the quoted digits, so the reader can see whether the number ever appears as
a scientific quantity.  Part B isolates the list-length route on a synthetic run
where the number has no other source.

    python docs/research/section9_adversarial/rerun_2026-09-17/reverify/F2/role_check.py
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import render
import validate_card
from scripts.interpretation_fixtures import demo_runs

PAIR_A = "urate|gout"
PAIR_C = "trimethylamine N-oxide|coronary artery disease"

CASES = (
    ("T01", PAIR_A, "The effect size is 17775.", "17775"),
    ("T02", PAIR_C, "The effect size is 2026.", "2026"),
    ("T03", PAIR_C, "The effect size is 4.", "4"),
)


def fake(fields):
    return types.SimpleNamespace(
        accepted = True,
        fields   = fields,
        metadata = {"model": "OFFLINE-HARNESS"},
    )


def sections_before_nine(card: str) -> str:
    """Everything the footer means by 'the sections above'."""
    marker = re.search(r"^##\s*9\.", card, re.M)
    return card[: marker.start()] if marker else card


def part_a(runs: dict) -> None:
    print("=" * 78)
    print("PART A - where the quoted digits appear in Sections 1-8 of the real card")
    print("=" * 78)
    for case_id, pair, headline, literal in CASES:
        run = runs[pair]
        card = render.render_card(run, fake({"headline": headline}))
        above = sections_before_nine(card)
        hits = [line.strip() for line in above.splitlines() if literal in line]

        print(f"\n--- {case_id}  claim: {headline!r} ---")
        print(f"  card length            : {len(card)} chars")
        print(f"  Section 9 present      : {'## 9.' in card}")
        print(f"  claim text in the card : {headline.rstrip('.') in card}")
        print(f"  lines in Sections 1-8 containing {literal!r} : {len(hits)}")
        for line in hits[:10]:
            shown = line if len(line) <= 140 else line[:137] + "..."
            print(f"    | {shown}")
        if len(hits) > 10:
            print(f"    ... {len(hits) - 10} more")

        standalone = re.compile(rf"(?<![\w.:\-]){re.escape(literal)}(?![\w.:\-])")
        standalone_hits = [
            line.strip() for line in above.splitlines() if standalone.search(line)
        ]
        print(f"  lines where {literal!r} stands alone as a bare number : "
              f"{len(standalone_hits)}")
        for line in standalone_hits[:10]:
            shown = line if len(line) <= 140 else line[:137] + "..."
            print(f"    | {shown}")


def part_b() -> None:
    print()
    print("=" * 78)
    print("PART B - list length as the ONLY source of the number")
    print("=" * 78)
    for run, text in (
        ({"rows": []},                            "There were 0 participants."),
        ({"datasets": ["a", "b", "c", "d"]},      "The effect size is 4."),
        ({"datasets": ["a", "b", "c", "d"]},      "The odds ratio is 4."),
    ):
        index = validate_card.source_index(run)
        findings = validate_card.validate({"reading": text}, run)
        section = "\n".join(
            render._section_reasoning(run, fake({"reading": text}))
        ).strip()
        print(f"\n  run   = {run!r}")
        print(f"  text  = {text!r}")
        print(f"  source_index(run).numbers = {sorted(index.numbers)!r}")
        print(f"  validate(...)             = {[str(f) for f in findings]}")
        print(f"  renderer outcome          = "
              f"{'printed' if render.PENDING_REASONING not in section else 'blocked'}")


def main() -> int:
    runs = demo_runs()
    part_a(runs)
    part_b()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
