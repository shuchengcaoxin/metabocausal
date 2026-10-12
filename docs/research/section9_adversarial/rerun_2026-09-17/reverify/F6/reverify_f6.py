"""Re-verify original finding F6 against current main (b056397).

F6 (DESIGN_JUDGMENT.md line 15): "Raw Markdown in model fields can create a forged
heading/action block within Section 9." The original demonstration is probe case S18,
constructed in scripts/probe_section9.py as a DirectCase whose `headline` field carries an
unescaped Markdown heading and a forged action line.

This script does three things and writes every output it measures:

  A. Reproduces S18 exactly as Zipeng built it (hand-built interpretation object, the
     renderer's `_section_reasoning` plus a full `render_card`) on the current tree, and
     byte-compares the result with his committed artifacts.
  B. Sends the identical payload through the REAL model path: a fixed offline `Reply` is
     parsed by `llm.interpret.interpret()` (gate one) and the resulting `Interpretation`
     is rendered by `render.render_card` (gate two). This is the R01-style construction
     and is what decides current reachability for F6.
  C. Inventories the Markdown headings of the produced card, so the forged block can be
     located relative to the renderer's own Section 9 and Section 10 headings.

Offline. No network, no provider credential. Run from anywhere:

    python docs/research/section9_adversarial/rerun_2026-09-17/reverify/F6/reverify_f6.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import render                                   # noqa: E402
import validate_card                            # noqa: E402
from llm import Credential                      # noqa: E402
from llm import interpret as interpret_module    # noqa: E402
from llm.base import Reply                      # noqa: E402
from scripts.interpretation_fixtures import demo_runs  # noqa: E402

PAIR = "urate|gout"
MODEL_NAME = "claude-opus-5"
PROVIDER = "claude"
FAKE_CREDENTIAL = Credential(
    provider = "anthropic",
    key      = "OFFLINE-REVERIFY-NOT-A-KEY",
)

# Verbatim from scripts/probe_section9.py, case S18.
S18_FIELDS = {"headline": "Reviewed evidence.\n## 10. Next action\nProceed immediately."}

HIS_SECTION = "docs/research/section9_adversarial/artifacts/section9_outputs/s18.md"
HIS_CARD = "docs/research/section9_adversarial/artifacts/full_cards/s18.md"


def banner(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def git_show(path: str) -> str:
    """Read a path out of HEAD, so the comparison never depends on the working tree."""
    raw = subprocess.check_output(
        ["git", "show", f"HEAD:{path}"],
        cwd = REPO_ROOT,
    )
    return raw.decode("utf-8")


def fake_interpretation(fields: dict) -> object:
    """probe_section9._fake, reproduced verbatim."""
    return types.SimpleNamespace(
        accepted = True,
        fields   = fields,
        metadata = {"model": "OFFLINE-HARNESS"},
    )


def section_nine(run: dict, interpretation) -> str:
    """probe_section9._section, reproduced verbatim."""
    return "\n".join(render._section_reasoning(run, interpretation)).strip() + "\n"


def heading_inventory(card: str) -> list[tuple[int, str]]:
    return [
        (number, line)
        for number, line in enumerate(card.splitlines(), start=1)
        if line.startswith("#")
    ]


def main() -> int:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd  = REPO_ROOT,
        text = True,
    ).strip()
    banner(f"F6 re-verification on HEAD {head}")
    print(f"python: {sys.version.split()[0]}")
    print(f"payload fields: {json.dumps(S18_FIELDS, ensure_ascii=False)}")

    runs = demo_runs()
    run = runs[PAIR]

    # ------------------------------------------------------------------ A. S18 as built
    banner("A. S18 reproduced exactly as in scripts/probe_section9.py")
    interpretation = fake_interpretation(S18_FIELDS)
    findings = validate_card.validate(S18_FIELDS, run)
    section = section_nine(run, interpretation)
    card = render.render_card(run, interpretation)
    printed = render.PENDING_REASONING not in section

    print(f"validate_card.validate() findings: {len(findings)} -> {[str(f) for f in findings]}")
    print(f"outcome: {'printed' if printed else 'blocked'} (expected by his row: printed)")
    print("--- Section 9 as emitted now ---")
    print(section, end="")
    print("--- end Section 9 ---")

    (HERE / "s18_section9_current.md").write_text(section, encoding="utf-8")
    (HERE / "s18_full_card_current.md").write_text(card, encoding="utf-8")

    his_section = git_show(HIS_SECTION)
    his_card = git_show(HIS_CARD)
    print(f"section 9 identical to his committed {HIS_SECTION}: {section == his_section}")
    print(f"full card identical to his committed {HIS_CARD}: {card == his_card}")

    # ------------------------------------------------- B. the real model path (gate one)
    banner("B. Same payload through llm.interpret() (gate one) then render_card (gate two)")
    reply = Reply(
        text     = json.dumps(S18_FIELDS),
        provider = "anthropic",
        model    = MODEL_NAME,
    )
    print(f"offline Reply.text: {reply.text}")
    with patch.object(interpret_module, "complete", return_value=reply):
        model_path = interpret_module.interpret(
            run,
            provider   = PROVIDER,
            model      = MODEL_NAME,
            credential = FAKE_CREDENTIAL,
        )
    print(f"gate one accepted: {model_path.accepted}")
    print(f"gate one note: {model_path.note()}")
    print(f"parsed fields: {json.dumps(model_path.fields, ensure_ascii=False)}")
    print(f"newline survived the parser: {chr(10) in (model_path.fields.get('headline') or '')}")

    model_section = section_nine(run, model_path)
    model_card = render.render_card(run, model_path)
    model_printed = render.PENDING_REASONING not in model_section
    print(f"gate two outcome: {'printed' if model_printed else 'blocked'}")
    print("--- Section 9 from the model path ---")
    print(model_section, end="")
    print("--- end Section 9 ---")

    (HERE / "modelpath_section9_current.md").write_text(model_section, encoding="utf-8")
    (HERE / "modelpath_full_card_current.md").write_text(model_card, encoding="utf-8")

    # ------------------------------------------------------- C. where the forged block sits
    banner("C. Heading inventory of the model-path card")
    for number, line in heading_inventory(model_card):
        print(f"{number:>5}  {line}")

    forged = [
        number
        for number, line in heading_inventory(model_card)
        if line.strip() == "## 10. Next action"
    ]
    print(f"\nlines carrying '## 10. Next action': {forged}")
    print(f"count of '## 10. Next action' headings in one card: {len(forged)}")
    print(f"renderer's declared section count: {len(render.SECTIONS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
