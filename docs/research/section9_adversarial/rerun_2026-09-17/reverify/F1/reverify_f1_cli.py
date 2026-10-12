"""F1 reachability check on the deployed CLI surface: `render.py --interpret`.

Zipeng's R01 called `llm.interpret()` in process.  This driver instead runs render.py's
own `__main__` block - argparse, the cached snapshot loader, `credential_from_env`,
`llm.interpret.interpret`, `render_card` - with exactly one substitution: the provider
transport `llm.interpret.complete` returns a fixed offline `Reply` instead of calling a
network API.  Nothing else is patched and no source file is edited.

This answers "is F1 reachable on a real surface, not only in a harness" for current main.

Run from the repository root:
    python docs/research/section9_adversarial/rerun_2026-09-17/reverify/F1/reverify_f1_cli.py
"""

from __future__ import annotations

import json
import os
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(REPO_ROOT))

from llm import interpret as interpret_module                       # noqa: E402
from llm.base import Reply                                          # noqa: E402

MODEL_NAME = "claude-opus-5"
R01_FIELDS = {"headline": "This target looks promising."}

OFFLINE_REPLY = Reply(
    text     = json.dumps(R01_FIELDS),
    provider = "anthropic",
    model    = MODEL_NAME,
)

OUT = Path(__file__).resolve().parent / "cli_card_urate_gout.md"


def main() -> int:
    # credential_from_env() reads this; the key is never used because `complete` is
    # replaced below, but an empty credential would short-circuit before the model call.
    os.environ["ANTHROPIC_API_KEY"] = "OFFLINE-REVERIFY-NOT-A-KEY"

    argv = [
        "render.py",
        "urate|gout",
        "--interpret",
        "--provider", "claude",
        "--model", MODEL_NAME,
        "--out", str(OUT),
    ]
    print("command simulated : " + " ".join(argv))
    print(f"patched symbol    : llm.interpret.complete -> fixed Reply({OFFLINE_REPLY.text})")
    print()

    saved_argv = sys.argv
    sys.argv = argv
    try:
        with patch.object(
            interpret_module,
            "complete",
            return_value = OFFLINE_REPLY,
        ):
            runpy.run_path(str(REPO_ROOT / "render.py"), run_name="__main__")
    finally:
        sys.argv = saved_argv

    card = OUT.read_text(encoding="utf-8")
    section = card.split("## 9. Reasoning", 1)[1].split("\n## ", 1)[0].strip()
    print()
    print("--- Section 9 of the card the CLI wrote ---")
    print(section)
    print("--- end ---")
    print()
    print(f"card written to   : {OUT}")
    print(f"card characters   : {len(card)}")
    print(f"prose printed     : {R01_FIELDS['headline'] in section}")
    print("attestation printed: "
          + str("checked against it before printing" in section))
    print("pending sentence   : "
          + str("Model reasoning pending integration" in section))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
