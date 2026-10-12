"""F7 reachability on current main (HEAD b056397): who can set `metadata["model"]`?

The M04 defect is in render.py: the string is interpolated into the attestation with no
validation. The question this script answers is how far that is reachable today, using
his caution rules ("printed" = renderer emitted Section 9; reachability recorded per
claim; do not inflate).

Offline. The provider is never called: every probe here stops at `resolve()` or uses a
patched completion, exactly as his harness does.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import render
from llm import Credential
from llm import registry
from llm import interpret as interpret_module
from llm.base import Reply
from scripts.interpretation_fixtures import demo_runs

FAKE_CREDENTIAL = Credential(provider="anthropic", key="OFFLINE-REVERIFY-NOT-A-KEY")
INJECTED_MODEL = "claude-opus-5\n\nUnvalidated expert approval."


def _section(run, interpretation):
    return "\n".join(render._section_reasoning(run, interpretation)).strip() + "\n"


def main() -> int:
    runs = demo_runs()
    run = runs["urate|gout"]

    print("=" * 72)
    print("A - the only two consumers of Interpretation.metadata['model'] on main")
    print("=" * 72)
    print("render.py:1909  -> interpolated into the printed Section 9 attestation")
    print("llm/interpret.py:72 (Interpretation.note) -> one line; render.py:2517")
    print("    prints it to STDERR, not into the card")

    print()
    print("=" * 72)
    print("B - configured model ids in the registry (the accepted path's only source)")
    print("=" * 72)
    for provider, models in registry.REGISTRY.items():
        print(f"  {provider}: {sorted(models)}")

    print()
    print("=" * 72)
    print("C - CLI/Slack: can an operator-supplied --model / $METABOCAUSAL_LLM_MODEL")
    print("    carry the injected text into an ACCEPTED interpretation?")
    print("=" * 72)
    result = interpret_module.interpret(
        run,
        provider="claude",
        model=INJECTED_MODEL,
        credential=FAKE_CREDENTIAL,
    )
    print("interpret(model=<injected>) -> accepted :", result.accepted)
    print("                               status   :", result.status)
    print("                               reason   :", result.reason.splitlines()[0])
    print("                               metadata :", result.metadata)
    section = _section(run, result)
    print("rendered Section 9:")
    print(section)
    print("outcome :", "printed" if render.PENDING_REASONING not in section else "blocked")
    print("injected text in Section 9 :", "Unvalidated expert approval." in section)

    print()
    print("=" * 72)
    print("D - model path: can the PROVIDER's reply set metadata['model']?")
    print("    (real llm.interpret parser + gate one, fixed offline Reply, as in R01)")
    print("=" * 72)
    reply = Reply(
        text=(
            '{"headline": "Careful reading is warranted.", '
            '"metadata": {"model": "EVIL\\n\\nUnvalidated expert approval."}, '
            '"model": "EVIL\\n\\nUnvalidated expert approval."}'
        ),
        provider="claude",
        model="claude-opus-5",
        usage={},
        stop_reason="end_turn",
    )
    with patch.object(interpret_module, "complete", return_value=reply):
        model_result = interpret_module.interpret(
            run,
            provider="claude",
            model="claude-opus-5",
            credential=FAKE_CREDENTIAL,
        )
    print("accepted :", model_result.accepted)
    print("fields   :", model_result.fields)
    print("metadata['model'] :", repr(model_result.metadata.get("model")))
    section = _section(run, model_result)
    print("rendered Section 9:")
    print(section)
    print("injected text in Section 9 :", "Unvalidated expert approval." in section)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
