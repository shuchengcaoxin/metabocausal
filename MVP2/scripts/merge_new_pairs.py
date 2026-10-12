"""Merge verified MVP2 new unique pairs into a copy of the MVP1 pair table."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = ROOT / "archive" / "project_files" / "release-evidence_2026-09-11" / "metabocausal-public" / "data" / "metabolite_disease.csv"
DEFAULT_NEW = ROOT / "MVP2" / "data" / "extracted" / "screened_20260912" / "new_unique_pairs.csv"
DEFAULT_OUTPUT = ROOT / "MVP2" / "data" / "extracted" / "mvp1_plus_mvp2_candidate_metabolite_disease.csv"
sys.path.insert(0, str(ROOT / "MVP2"))

from src.merge_pairs import merge_pair_tables  # noqa: E402
from src.pair_screening import hashed  # noqa: E402


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--new-pairs", type=Path, default=DEFAULT_NEW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    baseline_fields, baseline = read_table(args.baseline)
    _, new_pairs = read_table(args.new_pairs)
    result = merge_pair_tables(baseline, new_pairs, baseline_fields)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    reference_path = args.output.with_name(args.output.stem + ".reference_original_merged.csv")
    if args.output.exists():
        existing_fields, _ = read_table(args.output)
        if existing_fields != result["fields"] and not reference_path.exists():
            shutil.copy2(args.output, reference_path)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=result["fields"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(result["rows"])
    provenance_path = args.output.with_suffix(".provenance.csv")
    with provenance_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=result["provenance_fields"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(result["provenance_rows"])
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "baseline": hashed(args.baseline),
            "new_pairs": hashed(args.new_pairs),
        },
        "outputs": {
            "merged_csv": hashed(args.output),
            "provenance_csv": hashed(provenance_path),
            "reference_original_merged_csv": (hashed(reference_path) if reference_path.exists() else None),
        },
        "summary": result["summary"],
        "rules": [
            "The MVP1 baseline is not modified.",
            "The merged CSV uses exactly the baseline column names and order.",
            "Source-only fields are stored in the provenance sidecar and joined by merged_row_number.",
            "Every appended row must be source-verified, forward metabolite-to-disease, unique within the new file, and absent from the baseline.",
            "Paper metabolite IDs remain source_metabolite_id and are not asserted to be ChEBI IDs.",
            "Appended rows remain published_literature_mr_candidate until scientific validation accepts them.",
            "An appended row's ci_low/ci_upp are the source's own two 95% bounds in numeric order. Where the source printed them in the impossible order (ci_low > ci_upp), the provenance sidecar carries the as-printed pair in ci_low_as_printed/ci_high_as_printed and extraction_note says so; no bound is recomputed.",
        ],
    }
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
