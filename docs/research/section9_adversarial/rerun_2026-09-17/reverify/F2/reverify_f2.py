"""Re-verify original finding F2 against current main.

F2 (DESIGN_JUDGMENT.md): "Numeric membership is not bound to a field or semantic role.
Identifier digits, dates and list lengths can be relabelled as scientific quantities."

Zipeng demonstrated F2 with probe cases T01/T02/T03 (RESULTS.md) plus the inline
reproductions in ai_runs/02_numeric_attacks.md sections 1, 2 and 10.

This script reproduces that demonstration on the current worktree HEAD.  It is
read-only with respect to product code and writes nothing outside this directory.
Run from the repository root::

    python docs/research/section9_adversarial/rerun_2026-09-17/reverify/F2/reverify_f2.py
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import render
import validate_card
from llm import Credential
from llm import interpret as interpret_module
from llm.base import Reply
from scripts.interpretation_fixtures import demo_runs

MODEL_NAME = "claude-opus-5"
PROVIDER = "claude"
FAKE_CREDENTIAL = Credential(
    provider = "anthropic",
    key      = "OFFLINE-REVERIFY-NOT-A-KEY",
)

PAIR_A = "urate|gout"
PAIR_C = "trimethylamine N-oxide|coronary artery disease"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def fake_interpretation(fields, model: str = "OFFLINE-HARNESS"):
    """The harness object shape probe_section9._fake() builds for DirectCase rows."""
    return types.SimpleNamespace(
        accepted = True,
        fields   = fields,
        metadata = {"model": model},
    )


def section_text(run: dict, interpretation) -> str:
    return "\n".join(render._section_reasoning(run, interpretation)).strip() + "\n"


def printed(section: str) -> bool:
    return render.PENDING_REASONING not in section


def through_gate_one(run: dict, fields: dict):
    """Real parse_fields + gate one, with the provider call stubbed offline."""
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


# ------------------------------------------------------- provenance of the numbers

def walk_paths(value, path="run"):
    """Every scalar in the run, with the dotted path it was found at."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk_paths(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for position, item in enumerate(value):
            yield from walk_paths(item, f"{path}[{position}]")
    else:
        yield path, value


def list_paths(value, path="run"):
    """Every list/tuple/set in the run, with its length."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from list_paths(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set)):
        yield path, len(value)
        for position, item in enumerate(value):
            yield from list_paths(item, f"{path}[{position}]")


def provenance(run: dict, literal: str, limit: int = 6) -> None:
    """Show WHERE in the run the claimed quantity actually lives."""
    target = float(literal)
    print(f"  provenance of {literal} in the run:")
    hits = 0

    for path, scalar in walk_paths(run):
        if scalar is None or isinstance(scalar, bool):
            continue
        if isinstance(scalar, (int, float)):
            if math.isfinite(scalar) and float(scalar) == target:
                print(f"    numeric scalar   {path} = {scalar!r}")
                hits += 1
        else:
            text = str(scalar)
            for found in validate_card.NUMBER.findall(
                validate_card.normalise_notation(text)
            ):
                try:
                    if float(found) == target:
                        print(f"    digits in string {path} = {text!r}")
                        hits += 1
                        break
                except ValueError:
                    continue
        if hits >= limit:
            print("    ... (truncated)")
            return

    for path, length in list_paths(run):
        if float(length) == target:
            print(f"    list length      len({path}) = {length}")
            hits += 1
            if hits >= limit:
                print("    ... (truncated)")
                return

    if hits == 0:
        print("    NOT FOUND anywhere in the run")


# ----------------------------------------------------------------- the F2 cases

CASES = (
    ("T01", PAIR_A, "The effect size is 17775.", "17775",
     "identifier digits reused as effect size"),
    ("T02", PAIR_C, "The effect size is 2026.", "2026",
     "year reused as effect size"),
    ("T03", PAIR_C, "The effect size is 4.", "4",
     "list length reused as effect size"),
)


def replay_probe_cases(runs: dict) -> None:
    print("=" * 78)
    print("PART 1 - probe cases T01/T02/T03 replayed on current HEAD")
    print("=" * 78)

    committed = (
        REPO_ROOT
        / "docs" / "research" / "section9_adversarial"
        / "artifacts" / "section9_outputs"
    )

    for case_id, pair, headline, literal, attack in CASES:
        run = runs[pair]
        fields = {"headline": headline}

        print(f"\n--- {case_id}  ({attack}) ---")
        print(f"  pair     : {pair}")
        print(f"  state    : {run['state']}")
        print(f"  fields   : {fields!r}")

        provenance(run, literal)

        index = validate_card.source_index(run)
        print(f"  {literal} in source_index(run).numbers : "
              f"{float(literal) in index.numbers}")
        print(f"  traceable_number({literal!r}, index.numbers) : "
              f"{validate_card.traceable_number(literal, index.numbers)}")

        findings = validate_card.validate(fields, run)
        print(f"  validate(fields, run) -> {[str(f) for f in findings]}")

        harness = fake_interpretation(fields)
        section = section_text(run, harness)
        outcome = "printed" if printed(section) else "blocked"
        print(f"  renderer outcome (harness object) : {outcome}")
        print("  Section 9 emitted:")
        for line in section.rstrip("\n").split("\n"):
            print(f"    | {line}")

        blob = committed / f"{case_id.lower()}.md"
        if blob.exists():
            same = blob.read_text(encoding="utf-8") == section
            print(f"  identical to his committed {blob.name} : {same}")


def real_model_path(runs: dict) -> None:
    """Reachability check: same three headlines as a model JSON reply through gate one."""
    print()
    print("=" * 78)
    print("PART 2 - same three claims through the real model path "
          "(parse_fields -> gate one -> renderer gate two)")
    print("=" * 78)

    for case_id, pair, headline, literal, attack in CASES:
        run = runs[pair]
        fields = {"headline": headline}

        accepted = through_gate_one(run, fields)
        print(f"\n--- {case_id} via llm.interpret() ---")
        print(f"  interpret().accepted : {accepted.accepted}")
        print(f"  interpret().fields   : {accepted.fields!r}")
        print(f"  gate-one findings    : "
              f"{[str(f) for f in getattr(accepted, 'findings', [])]}")

        if accepted.fields:
            section = section_text(run, accepted)
            outcome = "printed" if printed(section) else "blocked"
            print(f"  renderer outcome     : {outcome}")
            print("  Section 9 emitted:")
            for line in section.rstrip("\n").split("\n"):
                print(f"    | {line}")
        else:
            print("  gate one discarded the fields; nothing to render")


def inline_snippets() -> None:
    """The exact inline reproductions from ai_runs/02_numeric_attacks.md."""
    print()
    print("=" * 78)
    print("PART 3 - inline reproductions from ai_runs/02_numeric_attacks.md")
    print("=" * 78)

    print("\n#1 identifier digits leak into numeric evidence")
    for run, text in (
        ({"id": "NCT12345678"},   "There were 12345678 participants."),
        ({"id": "MONDO:0005393"}, "The effect size is 5393."),
        ({"id": "rs123456"},      "The effect size is 123456."),
        ({"id": "ieu-a-789"},     "The effect size is -789."),
    ):
        index = validate_card.source_index(run)
        findings = validate_card.validate({"reading": text}, run)
        print(f"  run={run!r}")
        print(f"    text={text!r}")
        print(f"    source_index(run).numbers = "
              f"{sorted(index.numbers)!r}")
        print(f"    validate(...) = {[str(f) for f in findings]}")

    print("\n#2 unrelated source values are accepted by the schema-free index")
    for run, text in (
        ({"notes": ["not returned: rs999999"]}, "Variant rs999999 was associated."),
        ({"notes": ["retrieved_at 2026-09-16"]}, "The effect size is 2026."),
    ):
        findings = validate_card.validate({"reading": text}, run)
        print(f"  run={run!r}")
        print(f"    text={text!r}")
        print(f"    validate(...) = {[str(f) for f in findings]}")

    print("\n#10 list-length behaviour")
    for run, text in (
        ({"rows": []},                "There were 0 participants."),
        ({"x": [[1, 2], [3]]},        "There were 2 groups and 1 row."),
        ({"values": [True]},          "The effect size is 1."),
    ):
        index = validate_card.source_index(run)
        findings = validate_card.validate({"reading": text}, run)
        print(f"  run={run!r}")
        print(f"    text={text!r}")
        print(f"    source_index(run).numbers = {sorted(index.numbers)!r}")
        print(f"    validate(...) = {[str(f) for f in findings]}")

    print("\n  control: bool scalars are excluded")
    print(f"    source_index({{'value': True}}).numbers = "
          f"{validate_card.source_index({'value': True}).numbers!r}")
    print(f"    validate({{'reading': '1'}}, {{'value': True}}) = "
          f"{[str(f) for f in validate_card.validate({'reading': '1'}, {'value': True})]}")


def negative_control(runs: dict) -> None:
    """A number that is in NO field of the run must still be rejected."""
    print()
    print("=" * 78)
    print("PART 4 - negative control (an untraceable number must still be blocked)")
    print("=" * 78)

    run = runs[PAIR_A]
    for headline in ("The effect size is 17776.", "The effect size is 90210."):
        fields = {"headline": headline}
        findings = validate_card.validate(fields, run)
        section = section_text(run, fake_interpretation(fields))
        print(f"\n  fields={fields!r}")
        print(f"    validate(...) = {[str(f) for f in findings]}")
        print(f"    renderer outcome = "
              f"{'printed' if printed(section) else 'blocked'}")


def main() -> int:
    print("Re-verification of F2 (numeric membership unbound to field/role)")
    print(f"  repo root      : {REPO_ROOT}")
    print(f"  git HEAD       : {git('rev-parse', 'HEAD')}")
    print(f"  git branch     : {git('rev-parse', '--abbrev-ref', 'HEAD')}")
    print(f"  python         : {platform.python_version()}")
    print(f"  validate_card.py sha256 : {sha256(REPO_ROOT / 'validate_card.py')}")
    print(f"  render.py sha256        : {sha256(REPO_ROOT / 'render.py')}")
    print(f"  MIN_ROUNDING_DIGITS     : {validate_card.MIN_ROUNDING_DIGITS}")

    runs = demo_runs()
    print(f"  fixture pairs  : {sorted(runs)!r}")

    replay_probe_cases(runs)
    real_model_path(runs)
    inline_snippets()
    negative_control(runs)

    print()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
