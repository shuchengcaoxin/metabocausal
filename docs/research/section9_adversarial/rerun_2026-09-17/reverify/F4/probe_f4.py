"""Re-verify finding F4 on current main.

F4 (Zipeng, baseline bcb32a9): "Sentence-wide negation/disclaimer exemptions can excuse
a prohibited positive claim in another clause."

This script reproduces his demonstration on the current worktree HEAD without changing
any product code.  Three layers:

  1. direct renderer probe - his harness method: validate_card.validate(fields, run)
     then render._section_reasoning(run, accepted-interpretation).  Covers his four
     committed F4 cases (S10/S11/S12/S14) with their literal controls (S04/S06/S08/S13)
     and the F4 variants from ai_runs/01_semantic_attacks.md (M8/M9/X12/X14/U5/V6-3)
     with their intended-safe controls.
  2. model path - his R01 construction: a fixed offline Reply through the real
     llm.interpret() parser and gate one, then the renderer's gate two.
  3. CLI surface - render.py --interpret with the same offline Reply, to record whether
     the sentence reaches a real card from the deployed entry point.

Offline; no network, no credential, no writes outside this directory except the
gitignored cards/demo_*.ledger.jsonl the render CLI always writes.
"""

from __future__ import annotations

import io
import json
import runpy
import sys
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import render                                            # noqa: E402
import validate_card                                     # noqa: E402
from llm import Credential                               # noqa: E402
from llm import interpret as interpret_module            # noqa: E402
from llm.base import Reply                               # noqa: E402
from scripts.interpretation_fixtures import demo_runs    # noqa: E402

MODEL_NAME = "claude-opus-5"
PROVIDER = "claude"
FAKE_CREDENTIAL = Credential(
    provider = "anthropic",
    key      = "OFFLINE-PROBE-NOT-A-KEY",
)

A_PAIR = "urate|gout"
C_PAIR = "trimethylamine N-oxide|coronary artery disease"

# (case, origin, pair, field, text, expected_2026_09_16)
CASES = [
    # --- his committed harness cases for F4, with the literal controls -----------------
    ("S04", "probe_section9.py control", A_PAIR, "headline",
     "This proves the target works.", "blocked"),
    ("S10", "probe_section9.py F4 (V2)", A_PAIR, "headline",
     "The missing arm was not queried, but the retrieved evidence proves causality.",
     "printed"),
    ("S06", "probe_section9.py control", A_PAIR, "headline",
     "The metabolite acts through the nominated target.", "blocked"),
    ("S11", "probe_section9.py F4 (V3)", A_PAIR, "headline",
     "Colocalisation was not queried, but the target mediates the effect.", "printed"),
    ("S08", "probe_section9.py control", C_PAIR, "headline",
     "There is no effect.", "blocked"),
    ("S12", "probe_section9.py F4 (V4)", C_PAIR, "headline",
     "The source does not mean the estimate is unavailable; there is no effect.",
     "printed"),
    ("S13", "probe_section9.py control", A_PAIR, "headline",
     "Colocalisation upgraded the state.", "blocked"),
    ("S14", "probe_section9.py F4 (V6)", A_PAIR, "headline",
     "Colocalisation was not queried, but it upgraded the state.", "printed"),
    # --- the same defect class in his AI run log, ai_runs/01_semantic_attacks.md -------
    ("M8", "ai_run F4 (V3)", A_PAIR, "reading",
     "Mediation was not tested, but the marker mediates the disease effect.", "printed"),
    ("M9", "ai_run F4 (V3)", A_PAIR, "reading",
     "The marker mediates the disease effect, although mediation was not tested.",
     "printed"),
    ("M10", "ai_run control (two sentences)", A_PAIR, "reading",
     "Mediation was not tested. The marker mediates the disease effect.", "blocked"),
    ("M7", "ai_run intended safe negation", A_PAIR, "limits",
     "Mediation was not tested.", "printed"),
    ("U5", "ai_run F4 (V2)", A_PAIR, "headline",
     "The result cannot prove the effect, but it proves the effect.", "printed"),
    ("U4", "ai_run intended safe negation", A_PAIR, "headline",
     "The result cannot prove the effect.", "printed"),
    ("X12", "ai_run F4 (V4)", C_PAIR, "headline",
     "No causal relationship was retrieved, so there is no causal link.", "printed"),
    ("X14", "ai_run F4 (V4)", C_PAIR, "headline",
     "There is no effect, although this is not evidence of a biological negative.",
     "printed"),
    ("X13", "ai_run intended disclaimer", C_PAIR, "headline",
     "The absence of evidence is not evidence of no effect.", "printed"),
    ("X16", "ai_run intended disclaimer", C_PAIR, "headline",
     "The arm was skipped, not proof of no effect.", "printed"),
    ("V6-1", "ai_run control", A_PAIR, "reading",
     "H4 evidence upgraded the pair to State A.", "blocked"),
    ("V6-2", "ai_run intended safe negation", A_PAIR, "reading",
     "H4 evidence did not upgrade the pair to State A.", "printed"),
    ("V6-3", "ai_run F4 (V6)", A_PAIR, "reading",
     "H4 evidence did not upgrade the pair to State A, but H4 evidence upgraded the "
     "pair to State A.", "printed"),
]

MODEL_PATH_CASES = ["S10", "S11", "S12", "S14"]


def _fake_interpretation(fields: dict, model: str = "OFFLINE-HARNESS"):
    """His harness shape: an accepted interpretation object handed to the renderer."""
    return types.SimpleNamespace(
        accepted = True,
        fields   = fields,
        metadata = {"model": model},
    )


def _section(run: dict, interpretation) -> str:
    return "\n".join(render._section_reasoning(run, interpretation)).strip() + "\n"


def _printed(section: str) -> bool:
    return render.PENDING_REASONING not in section


def _reply(fields: dict) -> Reply:
    return Reply(
        text     = json.dumps(fields),
        provider = "anthropic",
        model    = MODEL_NAME,
    )


def _through_gate_one(run: dict, fields: dict):
    with patch.object(
        interpret_module,
        "complete",
        return_value = _reply(fields),
    ):
        return interpret_module.interpret(
            run,
            provider   = PROVIDER,
            model      = MODEL_NAME,
            credential = FAKE_CREDENTIAL,
        )


def _rules(findings) -> str:
    return ",".join(sorted({finding.rule for finding in findings})) or "-"


def main() -> int:
    runs = demo_runs()
    out_dir = HERE.parent
    sections = {}
    drift = []

    print("=" * 78)
    print("LAYER 1 - direct renderer probe (his harness method)")
    print("=" * 78)
    print(f"{'case':<6} {'origin':<32} {'gate findings':<16} {'outcome':<8} "
          f"{'2026-09-16':<10} match")
    for case, origin, pair, field, text, expected in CASES:
        run = runs[pair]
        fields = {field: text}
        findings = validate_card.validate(fields, run)
        section = _section(run, _fake_interpretation(fields))
        outcome = "printed" if _printed(section) else "blocked"
        same = outcome == expected
        if not same:
            drift.append((case, expected, outcome))
        sections[case] = section
        print(f"{case:<6} {origin:<32} {_rules(findings):<16} {outcome:<8} "
              f"{expected:<10} {'same' if same else 'CHANGED'}")
        (out_dir / f"section9_{case.lower().replace('-', '')}.md").write_text(
            section,
            encoding = "utf-8",
        )

    print()
    print("=" * 78)
    print("LAYER 2 - real model path (his R01 construction: offline Reply -> "
          "llm.interpret -> renderer)")
    print("=" * 78)
    for case in MODEL_PATH_CASES:
        entry = next(item for item in CASES if item[0] == case)
        _, _, pair, field, text, expected = entry
        run = runs[pair]
        interpretation = _through_gate_one(run, {field: text})
        section = _section(run, interpretation)
        outcome = "printed" if _printed(section) else "blocked"
        same = outcome == expected
        if not same:
            drift.append((f"{case}/model-path", expected, outcome))
        print(f"{case:<6} status={interpretation.status:<10} "
              f"accepted={str(interpretation.accepted):<6} "
              f"gate-one findings={len(interpretation.findings):<3} "
              f"renderer={outcome:<8} {'same' if same else 'CHANGED'}")
        print(f"       fields returned by interpret(): "
              f"{json.dumps(interpretation.fields, ensure_ascii=False)}")
        (out_dir / f"modelpath_section9_{case.lower()}.md").write_text(
            section,
            encoding = "utf-8",
        )

    print()
    print("=" * 78)
    print("LAYER 3 - deployed CLI surface: render.py --interpret with the same "
          "offline Reply")
    print("=" * 78)
    entry = next(item for item in CASES if item[0] == "S10")
    payload = {entry[3]: entry[4]}
    argv = [
        str(REPO_ROOT / "render.py"),
        A_PAIR,
        "--interpret",
        "--provider",
        PROVIDER,
        "--model",
        MODEL_NAME,
    ]
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.dict(
        "os.environ",
        {"ANTHROPIC_API_KEY": "OFFLINE-PROBE-NOT-A-KEY"},
    ):
        with patch.object(
            interpret_module,
            "complete",
            return_value = _reply(payload),
        ):
            with patch.object(sys, "argv", argv):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    runpy.run_path(
                        str(REPO_ROOT / "render.py"),
                        run_name = "__main__",
                    )
    card = stdout.getvalue()
    note = stderr.getvalue().strip()
    (out_dir / "cli_card_s10.md").write_text(
        card,
        encoding = "utf-8",
    )
    head, _, tail = card.partition("## 9. Reasoning")
    cli_section = ("## 9. Reasoning" + tail).split("\n## ")[0].strip()
    print(f"CLI stderr note: {note}")
    print(f"sentence in card: {entry[4] in card}")
    print(f"pending sentence in card: {render.PENDING_REASONING in card}")
    print("--- Section 9 as the CLI printed it ---")
    print(cli_section)
    print("--- end ---")

    print()
    print("=" * 78)
    print("BYTE COMPARISON against his committed section9_outputs/")
    print("=" * 78)
    committed = REPO_ROOT / "docs" / "research" / "section9_adversarial" / "artifacts"
    for case in ("S10", "S11", "S12", "S14"):
        path = committed / "section9_outputs" / f"{case.lower()}.md"
        mine = sections[case]
        his = path.read_text(encoding="utf-8")
        print(f"{case:<6} identical={mine == his}")

    print()
    print(f"cases with a changed outcome vs 2026-09-16: {len(drift)}")
    for case, expected, outcome in drift:
        print(f"  {case}: was {expected}, now {outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
