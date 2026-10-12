"""Anti-join extracted paper pairs against the existing metabolite-disease table.

Example:
    python MVP2/scripts/screen_new_pairs.py \
        --baseline archive/project_files/release-evidence_2026-09-11/metabocausal-public/data/metabolite_disease.csv \
        --candidates MVP2/data/extracted/paper_pairs.csv \
        --output-dir MVP2/data/extracted/screened_20260912
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "MVP2"))

from src.pair_screening import read_csv, screen_pairs, sha256  # noqa: E402


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    baseline = read_csv(args.baseline)
    candidates = read_csv(args.candidates)
    screened = screen_pairs(baseline, candidates)
    write_csv(args.output_dir / "new_pair_records.csv", screened["new_pair_records"])
    write_csv(args.output_dir / "new_unique_pairs.csv", screened["new_unique_pairs"])
    write_csv(args.output_dir / "screening_ledger.csv", screened["decisions"])
    manifest = {
        "schema_version": 1,
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "baseline": {"path": str(args.baseline), "sha256": sha256(args.baseline), "row_count": len(baseline)},
        "candidates": {"path": str(args.candidates), "sha256": sha256(args.candidates), "row_count": len(candidates)},
        "outputs": {"new_pair_records": "new_pair_records.csv", "new_unique_pairs": "new_unique_pairs.csv", "screening_ledger": "screening_ledger.csv"},
        "summary": screened["summary"],
        "caveats": ["This anti-join identifies coverage absent from the baseline; it does not validate MR quality or accept evidence.", "Reverse-direction and unresolved-identity rows remain in the ledger but are excluded from new_pair_records.csv."],
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
