"""Which route puts T01/T02/T03's claimed 'effect size' into source_index().numbers.

F2 says numeric membership is unbound to field or role.  The probe headlines quote
17775, 2026 and 4.  This script separates the two routes source_index() uses -
scalars/digits-inside-strings versus list lengths - so each probe case can be
attributed to a concrete non-quantity source instead of an unspecified match.

    python docs/research/section9_adversarial/rerun_2026-09-17/reverify/F2/isolate_routes.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import validate_card
from scripts.interpretation_fixtures import demo_runs

PAIR_A = "urate|gout"
PAIR_C = "trimethylamine N-oxide|coronary artery disease"

TARGETS = (
    ("T01", PAIR_A, 17775.0),
    ("T02", PAIR_C, 2026.0),
    ("T03", PAIR_C, 4.0),
)


def string_routes(value, target: float, path="run", out=None):
    """Paths whose STRING content yields `target` via the prose number parser."""
    if out is None:
        out = []
    if isinstance(value, dict):
        for key, item in value.items():
            string_routes(item, target, f"{path}.{key}", out)
    elif isinstance(value, (list, tuple)):
        for position, item in enumerate(value):
            string_routes(item, target, f"{path}[{position}]", out)
    elif value is not None and not isinstance(value, bool):
        if isinstance(value, (int, float)):
            if math.isfinite(value) and float(value) == target:
                out.append(("scalar", path, repr(value)))
        else:
            text = str(value)
            for literal in validate_card.NUMBER.findall(
                validate_card.normalise_notation(text)
            ):
                try:
                    if float(literal) == target:
                        out.append((
                            "digits-in-string",
                            path,
                            text if len(text) <= 90 else text[:87] + "...",
                        ))
                        break
                except ValueError:
                    continue
    return out


def length_routes(value, target: float, path="run", out=None):
    """Paths whose LIST LENGTH equals `target`."""
    if out is None:
        out = []
    if isinstance(value, dict):
        for key, item in value.items():
            length_routes(item, target, f"{path}.{key}", out)
    elif isinstance(value, (list, tuple, set)):
        if float(len(value)) == target:
            out.append(("list-length", path, f"len = {len(value)}"))
        for position, item in enumerate(value):
            length_routes(item, target, f"{path}[{position}]", out)
    return out


def main() -> int:
    runs = demo_runs()
    for case_id, pair, target in TARGETS:
        run = runs[pair]
        strings = string_routes(run, target)
        lengths = length_routes(run, target)

        print(f"=== {case_id}: {target:g} on pair {pair} ===")
        print(f"  routes via scalars / digits inside strings : {len(strings)}")
        for kind, path, sample in strings[:8]:
            print(f"    [{kind}] {path} -> {sample}")
        if len(strings) > 8:
            print(f"    ... {len(strings) - 8} more")
        print(f"  routes via list lengths                    : {len(lengths)}")
        for kind, path, sample in lengths[:8]:
            print(f"    [{kind}] {path} -> {sample}")
        if len(lengths) > 8:
            print(f"    ... {len(lengths) - 8} more")

        has_quantity_route = False
        for kind, path, sample in strings:
            leaf = path.rsplit(".", 1)[-1].split("[")[0]
            if leaf in {"beta", "se", "pval", "p_value", "b", "effect", "estimate",
                        "or", "ci_low", "ci_high", "n", "nsnp"}:
                has_quantity_route = True
                print(f"  NOTE quantity-shaped field also carries it: {path}")
        print(f"  any route through an effect-size-shaped field : {has_quantity_route}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
