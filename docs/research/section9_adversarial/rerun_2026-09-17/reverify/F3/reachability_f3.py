"""How far F3 reaches without any synthetic run field, measured on current main.

F3's substance is that the validator's index covers values the model digest and the
rendered sections 1-8 do not carry, so the footer sentence can be false. Case R06 shows
it with a synthetic `_private` field. This script asks the narrower, non-inflated
question: on an UNMODIFIED run, how many genuinely retrieved MR values are trusted by
both gates while being absent, at that precision, from the card a reader sees?

Reader side is measured against a card produced by the real CLI (`python render.py
"urate|gout" --out ...`), which builds its own run from the cached snapshot and renders
sections 1-8 and 10-11 exactly as a user would receive them.

    python docs/research/section9_adversarial/rerun_2026-09-17/reverify/F3/reachability_f3.py <cli_card.md>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import validate_card
from llm import Credential
from llm import interpret as interpret_module
from llm.base import Reply
from llm.interpret import build_digest
from scripts.interpretation_fixtures import demo_runs

MODEL_NAME = "claude-opus-5"
PROVIDER = "claude"
FAKE_CREDENTIAL = Credential(
    provider = "anthropic",
    key      = "OFFLINE-REVERIFY-NOT-A-KEY",
)


def _through_gate_one(run: dict, fields: dict):
    reply = Reply(
        text     = json.dumps(fields),
        provider = "anthropic",
        model    = MODEL_NAME,
    )
    with patch.object(interpret_module, "complete", return_value=reply):
        return interpret_module.interpret(
            run,
            provider   = PROVIDER,
            model      = MODEL_NAME,
            credential = FAKE_CREDENTIAL,
        )


def main(card_path: str) -> int:
    card = Path(card_path).read_text(encoding="utf-8")
    run = demo_runs()["urate|gout"]
    digest_text = json.dumps(build_digest(run), ensure_ascii=False)
    estimates = run["envelopes"]["mr"]["data"]["estimates"]

    print(f"cli card                 : {card_path} ({len(card):,} characters)")
    print(f"card contains section 9  : {'## 9. Reasoning' in card}")
    print(f"retrieved MR rows in run : {len(estimates)}")
    print(f"rows carried by digest   : {len(build_digest(run)['retrieved_estimates'])}")
    print()
    print("b (exact repr)        in digest  in cli card  gate1     gate2      verdict")

    invisible_but_trusted = []
    seen = set()
    for row in estimates:
        literal = repr(row["b"])
        if literal in seen:
            continue
        seen.add(literal)
        in_digest = literal in digest_text
        in_card = literal in card
        interpretation = _through_gate_one(
            run,
            {"headline": f"The retrieved effect size is {literal}."},
        )
        gate_two = validate_card.validate(interpretation.fields, run) if interpretation.accepted else []
        trusted = interpretation.accepted and not gate_two
        if trusted and not in_card and not in_digest:
            invisible_but_trusted.append(literal)
        print(
            f"{literal:<21} {str(in_digest):<9} {str(in_card):<12} "
            f"{interpretation.status:<9} {str([str(f) for f in gate_two] or 'none'):<10} "
            f"{'trusted' if trusted else 'blocked'}"
        )

    print()
    print(f"distinct b values tested                      : {len(seen)}")
    print(f"trusted by both gates, in neither digest nor card : {len(invisible_but_trusted)}")
    for literal in invisible_but_trusted:
        print(f"    {literal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
