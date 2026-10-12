"""Run the MVP2 Europe PMC-only literature investigation from a terminal.

Example:
    python MVP2/scripts/search_europepmc.py \
        --question "Does glycine affect coronary artery disease?" \
        --metabolite glycine \
        --disease "coronary artery disease" \
        --max-rounds 3 \
        --output MVP2/literature/search_runs/my_glycine_cad_run.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "MVP2"))

from src.search import search_literature  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", required=True)
    parser.add_argument("--metabolite", action="append", required=True, dest="metabolites")
    parser.add_argument("--disease", action="append", required=True, dest="diseases")
    parser.add_argument("--evidence-gap", action="append", default=[])
    parser.add_argument("--max-rounds", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--max-requests", type=int, default=None)
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = search_literature(
        args.question,
        args.metabolites,
        args.diseases,
        evidence_gaps=args.evidence_gap,
        max_rounds=args.max_rounds,
        max_pages=args.max_pages,
        max_requests=args.max_requests,
        max_seconds=args.max_seconds,
    )
    encoded = json.dumps(result, indent=2, ensure_ascii=False)
    print(encoded)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(f"\nSaved result to {args.output}", file=sys.stderr)
    return 0 if result["status"] in {"success", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
