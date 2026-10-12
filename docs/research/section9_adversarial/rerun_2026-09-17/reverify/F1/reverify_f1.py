"""Re-verification of original finding F1 against current main (b056397).

F1 (verbatim substance, DESIGN_JUDGMENT.md line 5-6):
    "The card-wide attestation overstates a token-membership and regex check as if the
     prose itself had been checked against the evidence."

Zipeng demonstrated F1 at baseline bcb32a9 by sending a token-free unsupported sentence
through the real `llm.interpret()` path (case R01) and showing the renderer printed it
under the attestation sentence.  This script reproduces that demonstration on current
main and additionally measures what the "check" actually examined.

Read-only with respect to the repository: it imports the modules under test and writes
nothing outside this directory.  Fully offline: the only thing replaced is the provider
transport `llm.interpret.complete`, which is given a fixed `Reply`.

Run from the repository root:
    python docs/research/section9_adversarial/rerun_2026-09-17/reverify/F1/reverify_f1.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(REPO_ROOT))

import render                                                       # noqa: E402
import validate_card                                                # noqa: E402
from llm import interpret as interpret_module                       # noqa: E402
from llm.base import Credential, Reply                              # noqa: E402
from scripts.interpretation_fixtures import demo_runs               # noqa: E402

MODEL_NAME = "claude-opus-5"
PROVIDER = "claude"
FAKE_CREDENTIAL = Credential(
    provider = "anthropic",
    key      = "OFFLINE-REVERIFY-NOT-A-KEY",
)

# The exact A1/R01 sentence from the 2026-09-16 study.
R01_FIELDS = {"headline": "This target looks promising."}

# Same sentence with one invented number appended: the token control.
CONTROL_FIELDS = {"headline": "This target looks promising, with b = 9.871."}

ATTESTATION_HEAD = "from this run's retrieved evidence and checked against it before printing"


def rule(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def offline_reply(fields: dict) -> Reply:
    return Reply(
        text     = json.dumps(fields),
        provider = "anthropic",
        model    = MODEL_NAME,
    )


def through_gate_one(run: dict, fields: dict):
    """The real llm.interpret() call with only the provider transport replaced."""
    with patch.object(
        interpret_module,
        "complete",
        return_value = offline_reply(fields),
    ):
        return interpret_module.interpret(
            run,
            provider   = PROVIDER,
            model      = MODEL_NAME,
            credential = FAKE_CREDENTIAL,
        )


def section_nine(run: dict, interpretation) -> str:
    return "\n".join(render._section_reasoning(run, interpretation)).strip() + "\n"


def main() -> int:
    runs = demo_runs()
    state_a = runs["urate|gout"]

    rule("STEP 0  environment")
    print(f"python          : {sys.version.split()[0]}")
    print(f"repo root       : {REPO_ROOT}")
    print(f"render.py       : {Path(render.__file__).name}")
    print(f"state A pair    : urate|gout   state={state_a['state']}")
    print(f"validate rules  : {[row[0] for row in validate_card.LANGUAGE_RULES]}")

    rule("STEP 1  R01 reproduction - token-free prose through the real model path")
    print(f"model reply text: {offline_reply(R01_FIELDS).text}")
    accepted = through_gate_one(state_a, R01_FIELDS)
    print(f"gate one status : {accepted.status}")
    print(f"gate one accept : {accepted.accepted}")
    print(f"gate one finding: {[str(f) for f in accepted.findings]}")
    print(f"fields returned : {accepted.fields}")
    print(f"metadata.model  : {(accepted.metadata or {}).get('model')}")

    gate_two = validate_card.validate(accepted.fields, state_a)
    print(f"gate two finding: {[str(f) for f in gate_two]}")

    section = section_nine(state_a, accepted)
    printed = render.PENDING_REASONING not in section
    print(f"renderer outcome: {'printed' if printed else 'blocked'}")
    print("--- exact Section 9 emitted by current main ---")
    print(section, end="")
    print("--- end ---")
    print(f"attestation present: {ATTESTATION_HEAD in section}")

    rule("STEP 2  what the attestation asserts, and what was actually checked")
    text = R01_FIELDS["headline"]
    index = validate_card.source_index(state_a)

    masked = validate_card._mask_identifiers(text)
    numbers_in_prose = validate_card.NUMBER.findall(masked)
    print(f"prose under attestation      : {text!r}")
    print(f"numbers V1 found in the prose: {numbers_in_prose}")
    print(f"V1 comparisons performed     : {len(numbers_in_prose)}")

    ident_findings = validate_card._check_identifiers("headline", text, index)
    num_findings = validate_card._check_numbers("headline", text, index)
    lang_findings = validate_card._check_language("headline", text)
    gene_findings = validate_card._check_gene_mediation("headline", text)
    print(f"V1 (numbers)   findings      : {[str(f) for f in num_findings]}")
    print(f"V5 (identifiers) findings    : {[str(f) for f in ident_findings]}")
    print(f"V2/V4/V6 (language) findings : {[str(f) for f in lang_findings]}")
    print(f"V3 (gene mediation) findings : {[str(f) for f in gene_findings]}")

    matched = []
    for rule_id, name, pattern, negatable in validate_card.LANGUAGE_RULES:
        if pattern.search(text.lower()):
            matched.append((rule_id, name))
    print(f"LANGUAGE_RULES regexes tried : {len(validate_card.LANGUAGE_RULES)}")
    print(f"LANGUAGE_RULES regexes hit   : {matched}")

    id_tokens = []
    for kind, pattern in validate_card.IDENTIFIER_PATTERNS.items():
        id_tokens.extend(pattern.findall(text))
    gene_tokens = [
        token for token in validate_card.GENE_SHAPE.findall(masked)
        if token.upper() not in validate_card.NON_GENE_VOCABULARY
    ]
    print(f"identifier tokens V5 found   : {id_tokens}")
    print(f"gene-shaped tokens V5 found  : {gene_tokens}")
    print(f"run values indexed as numbers    : {len(index.numbers)}")
    print(f"run values indexed as identifiers: {len(index.strings)}")
    print("evidence values actually compared against this prose: "
          f"{len(numbers_in_prose)} numeric, {len(id_tokens) + len(gene_tokens)} identifier")

    rule("STEP 3  token control - the same sentence carrying one invented number")
    control = through_gate_one(state_a, CONTROL_FIELDS)
    print(f"model reply text: {offline_reply(CONTROL_FIELDS).text}")
    print(f"gate one status : {control.status}")
    print(f"gate one accept : {control.accepted}")
    print(f"gate one reason : {control.reason}")
    print(f"gate one finding: {[str(f) for f in control.findings]}")
    control_section = section_nine(state_a, control)
    print(f"renderer outcome: "
          f"{'printed' if render.PENDING_REASONING not in control_section else 'blocked'}")

    rule("STEP 4  the attestation literal as it stands in current main's render.py")
    source = Path(render.__file__).read_text(encoding="utf-8")
    start = source.index('f"Written by {model}')
    print(source[start:start + 260].split("    )")[0].rstrip())

    rule("STEP 5  the same prose inside a complete card from render_card()")
    card = render.render_card(state_a, accepted)
    headings = re.findall(
        r"^## .*$",
        card,
        flags = re.MULTILINE,
    )
    print(f"card characters : {len(card)}")
    print(f"card ## headings: {len(headings)}")
    for heading in headings:
        print(f"  {heading}")
    body = card.split("## 9. Reasoning", 1)[1].split("\n## ", 1)[0].strip()
    print("--- Section 9 as it appears in the full card ---")
    print(body)
    print("--- end ---")

    rule("VERDICT INPUTS")
    print(f"token-free unsupported prose accepted by gate one : {accepted.accepted}")
    print(f"same prose accepted by gate two (renderer)        : {not gate_two}")
    print(f"renderer printed it                               : {printed}")
    print(f"printed under the 'checked against it' sentence   : {ATTESTATION_HEAD in section}")
    print(f"evidence comparisons the check actually performed : {len(numbers_in_prose)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
