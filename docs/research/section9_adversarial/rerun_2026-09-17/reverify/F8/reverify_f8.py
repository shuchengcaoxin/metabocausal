"""Re-verify original finding F8 against current main (worktree HEAD b056397).

F8 (Zipeng, baseline bcb32a9, DESIGN_JUDGMENT.md): "A malicious dict subclass can make
`validate()` raise despite its never-raises contract; `render_card()` contains the
exception, so this is robustness loss rather than prose leakage in the tested renderer."
Backed by probe case M05 (category object_protocol, expected/outcome `blocked`,
reachability `harness_only`) and by the minimal snippet in
`ai_runs/02_numeric_attacks.md` section 12.

This script reproduces that demonstration independently of `scripts/probe_section9.py`.
It measures; it repairs nothing and writes nothing outside this directory.

Run from the repository root with Python 3.12::

    PYTHONIOENCODING=utf-8 python docs/research/section9_adversarial/rerun_2026-09-17/reverify/F8/reverify_f8.py
"""

from __future__ import annotations

import json
import sys
import traceback
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import render                                   # noqa: E402
import validate_card                            # noqa: E402
from llm import interpret as interpret_module    # noqa: E402
from scripts.interpretation_fixtures import demo_runs  # noqa: E402

PROSE = "This proves the target is safe."


class ExplodingFields(dict):
    """Zipeng's construction, verbatim in substance: a dict subclass whose items() raises."""

    def items(self):
        raise RuntimeError("fields boom")


def header(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    observations: dict[str, object] = {}

    header("STEP 0 - what is under test on this checkout")
    print(f"repo root          : {REPO_ROOT}")
    print(f"python             : {sys.version.split()[0]}")
    print(f"validate_card file : {Path(validate_card.__file__).relative_to(REPO_ROOT)}")
    print(f"render file        : {Path(render.__file__).relative_to(REPO_ROOT)}")
    doc = validate_card.validate.__doc__ or ""
    contract_validate = "Never raises." in doc
    contract_render = "Never raises." in (render.render_card.__doc__ or "")
    print(f'validate() docstring still states "Never raises." : {contract_validate}')
    print(f'render_card() docstring still states "Never raises." : {contract_render}')
    observations["contract_text_validate_never_raises"] = contract_validate
    observations["contract_text_render_card_never_raises"] = contract_render

    header("STEP 1 - his minimal snippet (ai_runs/02_numeric_attacks.md, section 12)")
    print('>>> validate(ExplodingFields({"reading": "safe"}), {})')
    try:
        result = validate_card.validate(ExplodingFields({"reading": "safe"}), {})
        print(f"returned (did NOT raise): {result!r}")
        observations["minimal_snippet_raised"] = None
    except Exception as exc:                     # the behavior under test
        print(f"RAISED {type(exc).__name__}: {exc}")
        print("--- traceback (last 4 frames) ---")
        for line in traceback.format_exc().splitlines()[-9:]:
            print(line)
        observations["minimal_snippet_raised"] = type(exc).__name__
        observations["minimal_snippet_message"] = str(exc)

    header("STEP 2 - probe case M05, on the frozen urate|gout fixture")
    runs = demo_runs()
    run = runs["urate|gout"]
    print(f'fixture pair       : urate|gout   state={run.get("state")!r}')
    exploding = ExplodingFields(headline=PROSE)
    print(f"fields type        : {type(exploding).__name__} "
          f"(isinstance(dict) = {isinstance(exploding, dict)})")
    print(">>> validate_card.validate(exploding, run)")
    try:
        result = validate_card.validate(exploding, run)
        print(f"returned (did NOT raise): {result!r}")
        raised = "none"
    except Exception as exc:
        print(f"RAISED {type(exc).__name__}: {exc}")
        raised = type(exc).__name__
    observations["m05_validate_raised"] = raised

    header("STEP 3 - the same object through render.render_card()")
    interpretation = types.SimpleNamespace(
        accepted=True,
        fields=exploding,
        metadata={"model": "OFFLINE-REVERIFY"},
    )
    card = render.render_card(run, interpretation)
    section = card[card.index("## 9."):card.index("## 10.")].strip() + "\n"
    prose_printed = PROSE in section
    print("render_card() returned normally (no exception escaped).")
    print(f"offered prose printed in Section 9 : {prose_printed}")
    print(f"pending sentence present           : {render.PENDING_REASONING in section}")
    print("--- Section 9 as rendered ---")
    print(section, end="")
    print("--- end Section 9 ---")
    observations["m05_render_card_raised"] = False
    observations["m05_prose_printed"] = prose_printed
    observations["m05_outcome"] = "printed" if prose_printed else "blocked"
    observations["m05_section_text"] = section
    (Path(__file__).parent / "m05_section9.md").write_text(section, encoding="utf-8")

    header("STEP 4 - where exactly does the containment live?")
    print("render_card() wraps every section builder in try/except (render.py:2329-2336).")
    print("Calling the Section 9 builder directly, without that wrapper:")
    print(">>> render._section_reasoning(run, interpretation)")
    try:
        direct = "\n".join(render._section_reasoning(run, interpretation)).strip() + "\n"
        print(f"returned (did NOT raise); identical to card section body: {direct == section}")
        observations["section_builder_raised"] = None
    except Exception as exc:
        print(f"RAISED {type(exc).__name__}: {exc}")
        print("--- traceback (last 6 lines) ---")
        for line in traceback.format_exc().splitlines()[-6:]:
            print(line)
        observations["section_builder_raised"] = type(exc).__name__
    print()
    print("So containment is a property of render_card()'s wrapper, not of the Section 9")
    print("builder and not of validate() itself.")

    header("STEP 5 - reachability: what do the two real validate() callers pass?")
    print("callers of validate_card.validate() outside tests/harness:")
    print("  llm/interpret.py:319   findings = validate_card.validate(fields, run)   [unguarded]")
    print("  render.py:1890         findings = validate_card.validate(fields, result) "
          "[inside render_card's per-section try/except]")
    sample = '{"headline": "h", "reading": "r", "limits": "l"}'
    parsed = interpret_module.parse_fields(sample)
    print()
    print(f">>> llm.interpret.parse_fields({sample!r})")
    print(f"type(parsed) = {type(parsed).__name__}   "
          f"exact builtin dict = {type(parsed) is dict}")
    observations["parse_fields_returns_builtin_dict"] = type(parsed) is dict

    print()
    print(">>> does the exception escape interpret()'s gate-two call site if a subclass "
          "somehow arrives there?")
    escaped = None
    try:
        validate_card.validate(ExplodingFields(headline=PROSE), run)
    except Exception as exc:
        escaped = type(exc).__name__
    print(f"    the call at llm/interpret.py:319 has no try/except around it; the same "
          f"call raises {escaped} when handed a subclass.")
    print("    but parse_fields() above returns an exact builtin dict, so no current "
          "CLI/Slack input reaches this.")
    observations["interpret_call_site_guarded"] = False

    header("VERDICT INPUTS (machine-readable)")
    summary = {k: v for k, v in observations.items() if k != "m05_section_text"}
    print(json.dumps(summary, indent=2, sort_keys=True))
    (Path(__file__).parent / "observations.json").write_text(
        json.dumps(observations, indent=2, sort_keys=True), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
