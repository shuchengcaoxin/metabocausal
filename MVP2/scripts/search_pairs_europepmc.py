"""Search Europe PMC separately for every verified metabolite-disease pair.

The input is the source-extracted ``new_unique_pairs.csv``. A pair is eligible
only when the extractor marked that the same source row explicitly contained
both endpoints. Each eligible pair gets its own JSON record, including the
deduplicated papers and all round/API history returned by ``search_literature``.

Example:
    python MVP2/scripts/search_pairs_europepmc.py \
        --input MVP2/data/extracted/screened_20260912/new_unique_pairs.csv \
        --output-dir MVP2/literature/search_runs/pair_batch_001 \
        --offset 0 --limit 10 --max-rounds 3 --max-requests-per-pair 9
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "MVP2"))

from src.pair_screening import canonical_pair_key, hashed, read_csv  # noqa: E402
from src.search import search_literature  # noqa: E402


FORWARD_DIRECTIONS = {"", "forward", "metabolite disease", "metabolite outcome", "exposure outcome"}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _pair_id(row: Mapping[str, Any]) -> str:
    key = canonical_pair_key(row) or f"name|{_clean(row.get('metabolite_name'))}|{_clean(row.get('disease_trait'))}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def validate_pair(row: Mapping[str, Any]) -> tuple[bool, str]:
    """Reject rows that do not carry an explicit source-verified pair."""
    metabolite = _clean(row.get("metabolite_name"))
    disease = _clean(row.get("disease_trait"))
    if _clean(row.get("pair_relation_verified")).casefold() != "yes":
        return False, "source pair relation is not verified"
    if not metabolite or not disease:
        return False, "missing metabolite or disease endpoint"
    direction = _clean(row.get("direction")).casefold()
    if direction not in FORWARD_DIRECTIONS:
        return False, "not a forward metabolite-to-disease record"
    return True, "eligible"


def _question(row: Mapping[str, Any]) -> str:
    return f"Is {_clean(row['metabolite_name'])} causally associated with {_clean(row['disease_trait'])}?"


def _index_record(pair: Mapping[str, Any], *, status: str, reason: str, output_file: str = "", result: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "pair_id": _pair_id(pair),
        "metabolite_name": _clean(pair.get("metabolite_name")),
        "metabolite_id": _clean(pair.get("metabolite_id")),
        "disease_trait": _clean(pair.get("disease_trait")),
        "disease_id": _clean(pair.get("disease_id")),
        "source_path": pair.get("source_path", ""),
        "source_sheet": pair.get("source_sheet", ""),
        "source_row": pair.get("source_row", ""),
        "status": status,
        "reason": reason,
        "output_file": output_file,
        "paper_count": len(result.get("papers", [])) if result else 0,
        "round_count": len(result.get("rounds", [])) if result else 0,
        "search_stop_reason": result.get("stop_reason", "") if result else "",
    }


def search_pair_batch(
    rows: Iterable[Mapping[str, Any]],
    output_dir: str | Path,
    *,
    offset: int = 0,
    limit: int | None = None,
    max_rounds: int = 3,
    max_pages: int = 1,
    max_requests_per_pair: int | None = 9,
    max_seconds_per_pair: float | None = None,
    overwrite: bool = False,
    search_fn: Callable[..., Mapping[str, Any]] = search_literature,
) -> dict[str, Any]:
    """Run bounded, resumable pair-specific investigations."""
    if offset < 0 or (limit is not None and limit < 1):
        raise ValueError("offset must be non-negative and limit must be positive")
    selected = list(rows)[offset: offset + limit if limit is not None else None]
    output_dir = Path(output_dir)
    pairs_dir = output_dir / "pairs"
    pairs_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pair in selected:
        pair_key = canonical_pair_key(pair) or f"name|{_clean(pair.get('metabolite_name'))}|{_clean(pair.get('disease_trait'))}"
        if pair_key in seen:
            index.append(_index_record(pair, status="skipped", reason="duplicate pair in input slice"))
            continue
        seen.add(pair_key)
        eligible, reason = validate_pair(pair)
        pair_id = _pair_id(pair)
        output_file = pairs_dir / f"{pair_id}.json"
        if not eligible:
            index.append(_index_record(pair, status="skipped", reason=reason))
            continue
        if output_file.exists() and not overwrite:
            try:
                saved = json.loads(output_file.read_text(encoding="utf-8"))
                index.append(_index_record(
                    pair,
                    status      = "resumed",
                    reason      = "existing pair result retained",
                    output_file = output_file.relative_to(output_dir).as_posix(),
                    result      = saved.get("search", {}),
                ))
            except (OSError, json.JSONDecodeError):
                output_file.unlink()
        if output_file.exists() and not overwrite:
            continue
        question = _question(pair)
        try:
            result = search_fn(
                question,
                [_clean(pair["metabolite_name"])],
                [_clean(pair["disease_trait"])],
                evidence_gaps=["pair-specific source table and direction still require screening"],
                max_rounds=max_rounds,
                max_pages=max_pages,
                max_requests=max_requests_per_pair,
                max_seconds=max_seconds_per_pair,
            )
            record = {
                "schema_version": 1,
                "pair_id": pair_id,
                "input_pair": dict(pair),
                "question": question,
                "search": result,
            }
            output_file.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            index.append(_index_record(
                pair,
                status      = result.get("status", "success"),
                reason      = "search completed",
                output_file = output_file.relative_to(output_dir).as_posix(),
                result      = result,
            ))
        except Exception as exc:  # keep one failed pair from aborting the batch
            index.append(_index_record(pair, status="failed", reason=f"{type(exc).__name__}: {exc}"))
    return {"selected_count": len(selected), "index": index}


def write_index(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    fields = ["pair_id", "metabolite_name", "metabolite_id", "disease_trait", "disease_id", "source_path", "source_sheet", "source_row", "status", "reason", "output_file", "paper_count", "round_count", "search_stop_reason"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--max-requests-per-pair", type=int, default=9)
    parser.add_argument("--max-seconds-per-pair", type=float, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    rows = read_csv(args.input)
    result = search_pair_batch(
        rows,
        args.output_dir,
        offset=args.offset,
        limit=args.limit,
        max_rounds=args.max_rounds,
        max_pages=args.max_pages,
        max_requests_per_pair=args.max_requests_per_pair,
        max_seconds_per_pair=args.max_seconds_per_pair,
        overwrite=args.overwrite,
    )
    index_path = args.output_dir / "pair_search_index.csv"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_index(index_path, result["index"])
    manifest = {
        "schema_version": 1,
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "input": hashed(args.input, rows=len(rows)),
        "scope": "Europe PMC only; one bounded Task 01 investigation per verified forward metabolite-disease pair",
        "config": {"offset": args.offset, "limit": args.limit, "max_rounds": args.max_rounds, "max_pages": args.max_pages, "max_requests_per_pair": args.max_requests_per_pair, "max_seconds_per_pair": args.max_seconds_per_pair, "overwrite": args.overwrite},
        "outputs": {"pair_search_index": index_path.name, "pair_records_directory": "pairs/"},
        "summary": {
            "selected_count": result["selected_count"],
            "searched_count": sum(x["status"] in {"success", "partial", "failed"} for x in result["index"]),
            "skipped_count": sum(x["status"] in {"skipped", "resumed"} for x in result["index"]),
            "failed_count": sum(x["status"] == "failed" for x in result["index"]),
        },
        "caveats": ["Search hits are discovery candidates, not accepted MR evidence.", "Each pair record retains its own queries, returned identifiers, deduplication decisions, remaining gaps and stop reason.", "Semantic Scholar is intentionally not used for this Europe PMC-only workstream."],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["summary"]))
    return 0 if manifest["summary"]["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
