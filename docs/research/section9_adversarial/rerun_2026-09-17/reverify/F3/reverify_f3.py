"""Re-verify original finding F3 against current main (worktree HEAD b056397).

F3 (verbatim substance, DESIGN_JUDGMENT.md): "Schema-free indexing trusts values that
are absent from both the model digest and the rendered evidence sections, so the footer
can make a literally false visibility claim."

Zipeng demonstrated it with committed case R06 (scripts/probe_section9.py:543-567):
put 7.7771 into an arbitrary run field `_private`, quote it in model prose, pass the
real llm.interpret() gate one and the renderer's gate two, and read the printed footer.
His discovery notes (ai_runs/04_dual_gate_surface.md) add two further constructions:
an arbitrary hidden scalar under `metadata`, and the demo run's ninth MR estimate,
which build_digest() omits (MAX_ESTIMATES = 8) and section 3 prints only rounded.

This script reproduces all three on current code, offline and deterministically, and
prints only measured values. It writes nothing outside its own directory.

    python docs/research/section9_adversarial/rerun_2026-09-17/reverify/F3/reverify_f3.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import platform
import subprocess
import sys
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
from llm.interpret import build_digest
from scripts.interpretation_fixtures import demo_runs

MODEL_NAME = "claude-opus-5"
PROVIDER = "claude"
FAKE_CREDENTIAL = Credential(
    provider = "anthropic",
    key      = "OFFLINE-REVERIFY-NOT-A-KEY",
)
BASELINE = "bcb32a9"


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd    = REPO_ROOT,
            text   = True,
            stderr = subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _through_gate_one(run: dict, fields: dict):
    """The real parser + first validator, fed a fixed offline reply."""
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


def _section(run: dict, interpretation) -> str:
    return "\n".join(render._section_reasoning(run, interpretation)).strip() + "\n"


def _printed(section: str) -> bool:
    return render.PENDING_REASONING not in section


def _sections_before_nine(card: str) -> str:
    """Everything a reader sees above section 9, i.e. what the footer points at."""
    head, marker, _ = card.partition("## 9. Reasoning")
    if not marker:
        raise AssertionError("card has no section 9 heading")
    return head


def _where(card: str, literal: str) -> list[str]:
    hits = []
    for number, line in enumerate(card.splitlines(), start=1):
        if literal in line:
            hits.append(f"line {number}: {line.strip()[:110]}")
    return hits


def _report(
    *,
    label: str,
    run: dict,
    literal: str,
    fields: dict,
) -> None:
    index = validate_card.source_index(run)
    interpretation = _through_gate_one(run, fields)
    gate_two = validate_card.validate(interpretation.fields, run)
    section = _section(run, interpretation)

    print(f"\n----- {label} -----")
    print(f"prose                       : {json.dumps(fields, ensure_ascii=False)}")
    print(f"float({literal}) in source_index().numbers : {float(literal) in index.numbers}")
    print(f"gate one (llm.interpret)    : status={interpretation.status} accepted={interpretation.accepted}")
    print(f"gate one findings           : {[str(f) for f in interpretation.findings] or 'none'}")
    print(f"gate two (validate_card)    : {[str(f) for f in gate_two] or 'none'}")
    print(f"outcome                     : {'printed' if _printed(section) else 'blocked'}")
    print("section 9 as rendered:")
    for line in section.rstrip().splitlines():
        print(f"    | {line}")

    if not _printed(section):
        return

    card = render.render_card(run, interpretation)
    above = _sections_before_nine(card)
    print(f"occurrences of {literal!r} in sections 1-8 : {above.count(literal)}")
    print(f"occurrences of {literal!r} in whole card   : {card.count(literal)}")
    for hit in _where(card, literal):
        print(f"    {hit}")
    footer = (
        "Every number and identifier above appears in the sections above"
    )
    print(f"footer visibility sentence present         : {footer in card}")
    print(
        "footer claim is true for this number       : "
        f"{above.count(literal) > 0}"
    )
    out = HERE.parent / f"card_{label.split()[0].lower()}.md"
    out.write_text(card, encoding="utf-8")
    print(f"full card written to                       : {out.name}")


def main() -> int:
    print("=" * 78)
    print("F3 re-verification -- schema-free indexing and the footer visibility claim")
    print("=" * 78)
    print(f"cwd                : {Path.cwd()}")
    print(f"repo root          : {REPO_ROOT}")
    print(f"git HEAD           : {_git('rev-parse', 'HEAD')}")
    print(f"git branch         : {_git('rev-parse', '--abbrev-ref', 'HEAD')}")
    print(f"python             : {platform.python_version()} on {platform.system()}")
    for name in ("validate_card.py", "render.py", "llm/interpret.py"):
        path = REPO_ROOT / name
        print(f"sha256 {name:<20}: {_sha256(path)}")
    changed = _git("diff", "--stat", BASELINE, "HEAD", "--", "validate_card.py", "render.py", "llm/")
    print(f"diff {BASELINE}..HEAD for validator/renderer/llm : {changed or '(empty: identical)'}")
    print(f"MAX_ESTIMATES in llm/interpret.py : {interpret_module.MAX_ESTIMATES}")

    runs = demo_runs()
    source = runs["urate|gout"]

    # Control: the same sentence without any hidden field must be blocked by V1.
    _report(
        label   = "CONTROL unmodified run, prose quotes 7.7771",
        run     = copy.deepcopy(source),
        literal = "7.7771",
        fields  = {"headline": "The retrieved effect size is 7.7771."},
    )

    # F3a == his committed case R06.
    hidden_run = copy.deepcopy(source)
    hidden_run["_private"] = {"forged": 7.7771}
    _report(
        label   = "F3a  R06 arbitrary run field _private={'forged': 7.7771}",
        run     = hidden_run,
        literal = "7.7771",
        fields  = {"headline": "The retrieved effect size is 7.7771."},
    )

    # F3b == the arbitrary hidden scalar from ai_runs/04_dual_gate_surface.md.
    meta_run = copy.deepcopy(source)
    meta_run["metadata"] = {"internal_counter": 12345}
    _report(
        label   = "F3b  arbitrary hidden scalar metadata={'internal_counter': 12345}",
        run     = meta_run,
        literal = "12345",
        fields  = {"headline": "The retrieved effect size is 12345."},
    )

    # F3c == the digest-boundary construction: a genuine run value the model never saw
    # and the reader never sees at full precision.
    digest = build_digest(source)
    digest_text = json.dumps(digest, ensure_ascii=False)
    ninth = source["envelopes"]["mr"]["data"]["estimates"][8]["b"]
    print(f"\nninth retrieved MR estimate b      : {ninth!r}")
    print(f"digest carries {len(digest['retrieved_estimates'])} estimate row(s); "
          f"'{ninth}' in digest text: {str(ninth) in digest_text}")
    _report(
        label   = "F3c  digest-omitted ninth MR row 1.10494365635414",
        run     = copy.deepcopy(source),
        literal = "1.10494365635414",
        fields  = {"headline": "The retrieved effect size is 1.10494365635414."},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
