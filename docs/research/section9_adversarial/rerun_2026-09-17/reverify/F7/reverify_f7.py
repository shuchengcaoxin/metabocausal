"""Re-verify original finding F7 on current main (worktree HEAD b056397).

F7: "Unvalidated `metadata.model` text is appended to an otherwise validated section."
Zipeng demonstrated it as probe case M04 (scripts/probe_section9.py, case_id="M04"):
a newline-bearing `metadata["model"]` is interpolated into the Section 9 attestation
sentence after the fields themselves have passed both gates.

This script reproduces M04 on current code WITHOUT running his harness and WITHOUT
writing anything into his bundle. It only reads his committed artifacts for comparison.

Offline. No credential, no network.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import render
import validate_card
from scripts.interpretation_fixtures import demo_runs

HIS_SECTION = REPO_ROOT / "docs/research/section9_adversarial/artifacts/section9_outputs/m04.md"
HIS_CARD = REPO_ROOT / "docs/research/section9_adversarial/artifacts/full_cards/m04.md"

# Verbatim from scripts/probe_section9.py, the M04 construction.
M04_FIELDS = {"headline": "Careful reading is warranted."}
M04_MODEL = "OFFLINE-HARNESS\n\nUnvalidated expert approval."


def _fake(accepted, fields, model):
    return types.SimpleNamespace(
        accepted=accepted,
        fields=fields,
        metadata={"model": model},
    )


def _section(run, interpretation):
    return "\n".join(render._section_reasoning(run, interpretation)).strip() + "\n"


def main() -> int:
    runs = demo_runs()
    run = runs["urate|gout"]

    interpretation = _fake(True, M04_FIELDS, M04_MODEL)

    print("=" * 72)
    print("STEP 1 - gate two on the FIELDS alone (validate_card.validate)")
    print("=" * 72)
    findings = validate_card.validate(M04_FIELDS, run)
    print("fields   :", M04_FIELDS)
    print("findings :", [str(f) for f in findings])
    print("rules    :", sorted({f.rule for f in findings}))

    print()
    print("=" * 72)
    print("STEP 2 - rendered Section 9 on current main")
    print("=" * 72)
    section = _section(run, interpretation)
    print(section)
    printed = render.PENDING_REASONING not in section
    print("outcome  :", "printed" if printed else "blocked")

    print()
    print("=" * 72)
    print("STEP 3 - is the unvalidated metadata text present in the printed section?")
    print("=" * 72)
    injected = "Unvalidated expert approval."
    print("injected literal in section :", injected in section)
    print("injected literal validated  :",
          bool(validate_card.validate({"headline": injected}, run)))
    print("  (empty findings above means the validator was never asked about it;")
    print("   the text never passes through validate() at all - see STEP 5)")

    print()
    print("=" * 72)
    print("STEP 4 - byte comparison against his committed m04.md (baseline bcb32a9)")
    print("=" * 72)
    his = HIS_SECTION.read_text(encoding="utf-8").replace("\r\n", "\n")
    mine = section.replace("\r\n", "\n")
    print("his  m04.md len :", len(his))
    print("mine        len :", len(mine))
    print("identical       :", his == mine)

    print()
    print("=" * 72)
    print("STEP 5 - the code path, quoted from current render.py")
    print("=" * 72)
    src = (REPO_ROOT / "render.py").read_text(encoding="utf-8").split("\n")
    for i in range(1900, 1916):
        print(f"render.py:{i + 1}: {src[i]}")

    print()
    print("=" * 72)
    print("STEP 6 - full card: where the injected text lands")
    print("=" * 72)
    card = render.render_card(run, interpretation)
    lines = card.replace("\r\n", "\n").split("\n")
    for idx, line in enumerate(lines):
        if injected in line or "Written by" in line:
            lo, hi = max(0, idx - 4), min(len(lines), idx + 3)
            for j in range(lo, hi):
                print(f"card:{j + 1}: {lines[j]}")
            break
    his_card = HIS_CARD.read_text(encoding="utf-8").replace("\r\n", "\n")
    print("full card identical to his full_cards/m04.md :",
          his_card == card.replace("\r\n", "\n"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
