"""Re-verify original finding F5 against current main.

F5 (Zipeng, baseline bcb32a9): "Unicode normalization gaps can change meaning, including
the sign of a coefficient, without producing a finding."

His concrete demonstration (ai_runs/01_semantic_attacks.md U8/U9, ai_runs/02_numeric_attacks.md
section 7, probe cases U01-U04):
  U01  headline "The effect is b = -1.367." with U+2212 MINUS SIGN  -> printed, no finding
  U02  the same headline with ASCII '-'                             -> blocked by V1
  U03  "no<U+00A0>effect" evades the literal-space V4 phrase        -> printed
  U04  Cyrillic 'i' in 'mediates' evades the ASCII V3 expression    -> printed

This script re-runs that demonstration on the current worktree (HEAD b056397) and adds the
real-model-path form (llm.interpret gate one + renderer gate two), which his U-cases did not
exercise -- they were DirectCase / renderer-only and labelled model_path_equivalent.

Writes nothing outside this directory. No network. Run from the repo root::

    python docs/research/section9_adversarial/rerun_2026-09-17/reverify/F5/reverify_f5.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import types
import unicodedata
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import render                                     # noqa: E402
import validate_card                              # noqa: E402
from llm import Credential                        # noqa: E402
from llm import interpret as interpret_module     # noqa: E402
from llm.base import Reply                        # noqa: E402
from scripts.interpretation_fixtures import demo_runs  # noqa: E402

BASELINE = "bcb32a9"
MODEL_NAME = "claude-opus-5"
PROVIDER = "claude"
FAKE_CREDENTIAL = Credential(
    provider = "anthropic",
    key      = "OFFLINE-REVERIFY-NOT-A-KEY",
)

U2212 = "−"
NBSP = " "
CYRILLIC_I = "і"

SOURCE_PAIR = "urate|gout"
TARGET_PAIR = "trimethylamine N-oxide|coronary artery disease"


def rule(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd    = REPO_ROOT,
            text   = True,
            stderr = subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def codepoints(text: str) -> str:
    return " ".join(
        f"{char}=U+{ord(char):04X}"
        for char in text
        if ord(char) > 127
    ) or "(all ASCII)"


def fake_interpretation(fields: dict, model: str = "OFFLINE-HARNESS"):
    """The shape render._section_reasoning consumes; identical to probe_section9._fake."""
    return types.SimpleNamespace(
        accepted = True,
        fields   = fields,
        metadata = {"model": model},
    )


def through_gate_one(run: dict, fields: dict):
    """Real llm.interpret() over a fixed offline Reply, exactly as probe R01 does."""
    reply = Reply(
        text     = json.dumps(fields, ensure_ascii=False),
        provider = "anthropic",
        model    = MODEL_NAME,
    )
    with patch.object(interpret_module, "complete", return_value=reply):
        return interpret_module.interpret(
            run        = run,
            provider   = PROVIDER,
            model      = MODEL_NAME,
            credential = FAKE_CREDENTIAL,
        )


def section_text(run: dict, interpretation) -> str:
    return "\n".join(render._section_reasoning(run, interpretation)).strip() + "\n"


def printed(section: str) -> bool:
    return render.PENDING_REASONING not in section


def report_direct(case_id: str, run: dict, fields: dict) -> str:
    findings = validate_card.validate(fields, run)
    section = section_text(run, fake_interpretation(fields))
    outcome = "printed" if printed(section) else "blocked"
    print(f"\n[{case_id}] fields = {fields!r}")
    print(f"[{case_id}] non-ASCII in headline: {codepoints(fields.get('headline', ''))}")
    print(f"[{case_id}] gate-two findings ({len(findings)}): "
          f"{[str(f) for f in findings] or 'none'}")
    print(f"[{case_id}] renderer outcome: {outcome}")
    print(f"[{case_id}] Section 9 text:\n---8<---\n{section}--->8---")
    return outcome


def report_model_path(case_id: str, run: dict, fields: dict) -> str:
    interpretation = through_gate_one(run, fields)
    section = section_text(run, interpretation)
    outcome = "printed" if printed(section) else "blocked"
    gate_two = validate_card.validate(
        getattr(interpretation, "fields", None) or {},
        run,
    )
    print(f"\n[{case_id}] model JSON reply = {json.dumps(fields, ensure_ascii=False)}")
    print(f"[{case_id}] gate one: status={interpretation.status!r} "
          f"accepted={interpretation.accepted} "
          f"findings={[str(f) for f in interpretation.findings] or 'none'}")
    print(f"[{case_id}] gate one returned fields = {interpretation.fields!r}")
    print(f"[{case_id}] gate two findings: {[str(f) for f in gate_two] or 'none'}")
    print(f"[{case_id}] renderer outcome: {outcome}")
    print(f"[{case_id}] Section 9 text:\n---8<---\n{section}--->8---")
    return outcome


def main() -> int:
    rule("STEP 0 - environment and code identity")
    print(f"cwd/repo_root : {REPO_ROOT}")
    print(f"git HEAD      : {git('rev-parse', 'HEAD')}")
    print(f"git branch    : {git('branch', '--show-current')}")
    print(f"python        : {sys.version.split()[0]}")
    print("network_used  : false")
    for name in ("validate_card.py", "render.py", "llm/interpret.py", "data/demo_card_inputs.json"):
        path = REPO_ROOT / name
        head_blob = git("rev-parse", f"HEAD:{name}")
        base_blob = git("rev-parse", f"{BASELINE}:{name}")
        print(f"{name:<32} sha256={sha256(path)[:16]}  "
              f"blob@HEAD={head_blob[:12]}  blob@{BASELINE}={base_blob[:12]}  "
              f"same_as_baseline={head_blob == base_blob}")

    rule("STEP 1 - parser-level fact: does the number parser see U+2212 as a sign?")
    print(f"validate_card.NUMBER.pattern = {validate_card.NUMBER.pattern!r}")
    print(f"U+2212 name = {unicodedata.name(U2212)!r}")
    print(f"U+2212 in SUPERSCRIPTS translate table = "
          f"{ord(U2212) in validate_card.SUPERSCRIPTS}")
    print(f"superscript minus U+207B in SUPERSCRIPTS = "
          f"{ord(chr(0x207B)) in validate_card.SUPERSCRIPTS}")
    for label, text in (
        ("U+2212", f"The effect is b = {U2212}1.367."),
        ("ASCII -", "The effect is b = -1.367."),
    ):
        normalised = validate_card.normalise_notation(text)
        literals = validate_card.NUMBER.findall(validate_card._mask_identifiers(text))
        print(f"  {label:<8} text={text!r}")
        print(f"  {label:<8} normalise_notation -> {normalised!r}")
        print(f"  {label:<8} NUMBER.findall(_mask_identifiers(text)) -> {literals}")

    runs = demo_runs()
    source = runs[SOURCE_PAIR]
    target = runs[TARGET_PAIR]

    rule("STEP 2 - what the source run actually contains")
    index = validate_card.source_index(source)
    near = sorted(value for value in index.numbers if abs(abs(value) - 1.367) < 0.01)
    print(f"run state                       : {source['state']}")
    print(f"values within 0.01 of |1.367|   : {near}")
    print(f"traceable_number('1.367', ...)  : "
          f"{validate_card.traceable_number('1.367', index.numbers)}")
    print(f"traceable_number('-1.367', ...) : "
          f"{validate_card.traceable_number('-1.367', index.numbers)}")
    print(f"is -1.367... present in the run : "
          f"{any(value < 0 and abs(abs(value) - 1.367) < 0.01 for value in index.numbers)}")

    rule("STEP 3 - his U01/U02/U03/U04, reproduced through the renderer gate on current main")
    outcomes = {}
    outcomes["U01"] = report_direct(
        "U01",
        source,
        {"headline": f"The effect is b = {U2212}1.367."},
    )
    outcomes["U02"] = report_direct(
        "U02",
        source,
        {"headline": "The effect is b = -1.367."},
    )
    outcomes["U03"] = report_direct(
        "U03",
        target,
        {"headline": f"The query found no{NBSP}effect."},
    )
    outcomes["U04"] = report_direct(
        "U04",
        source,
        {"headline": f"The marker med{CYRILLIC_I}ates the disease effect."},
    )

    rule("STEP 4 - the same sign flip through the REAL model path (gate one + gate two)")
    outcomes["F5-MP-unicode"] = report_model_path(
        "F5-MP-unicode",
        source,
        {"headline": f"The effect is b = {U2212}1.367."},
    )
    outcomes["F5-MP-ascii"] = report_model_path(
        "F5-MP-ascii",
        source,
        {"headline": "The effect is b = -1.367."},
    )

    rule("STEP 5 - whole card via render.render_card (does Section 9 survive into the card?)")
    interpretation = through_gate_one(
        source,
        {"headline": f"The effect is b = {U2212}1.367."},
    )
    card = render.render_card(source, interpretation)
    marker = f"The effect is b = {U2212}1.367."
    print(f"card length            : {len(card)} chars")
    print(f"card contains U+2212 claim : {marker in card}")
    print(f"card contains PENDING sentence : {render.PENDING_REASONING in card}")
    start = card.find("## 9.")
    if start == -1:
        start = card.find(marker) - 200
    print("--- card excerpt around Section 9 ---")
    print(card[max(start, 0):max(start, 0) + 900])
    print("--- end excerpt ---")
    (HERE.parent / "card_f5_model_path.md").write_text(card, encoding="utf-8")

    rule("VERDICT TABLE (this run, HEAD b056397)")
    expected = {
        "U01": "printed",
        "U02": "blocked",
        "U03": "printed",
        "U04": "printed",
        "F5-MP-unicode": "printed",
        "F5-MP-ascii": "blocked",
    }
    ok = True
    for case_id, outcome in outcomes.items():
        match = outcome == expected[case_id]
        ok = ok and match
        print(f"{case_id:<16} observed={outcome:<8} "
              f"baseline_or_expected={expected[case_id]:<8} match={match}")
    print(f"\nall F5 observations match the 2026-09-16 baseline expectation: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
