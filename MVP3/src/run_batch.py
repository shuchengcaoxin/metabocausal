"""Run checksum-bound Human-GEM lookup for a batch of resolved ChEBI identifiers."""

import argparse
import json
from pathlib import Path

from .common import canonical_bytes, strict_json, utc_now, write_new
from .gem import GemLookup


def load_inputs(path):
    """Return the ChEBI ID list and optional snapshot ID from a small JSON input."""
    payload = strict_json(Path(path).read_bytes())
    if isinstance(payload, list):
        chebi_ids, snapshot_id = payload, None
    elif isinstance(payload, dict):
        chebi_ids = payload.get("chebi_ids")
        snapshot_id = payload.get("snapshot_id")
    else:
        raise ValueError("Batch input must be a JSON list or object")
    if not isinstance(chebi_ids, list):
        raise ValueError("Batch input chebi_ids must be a list")
    if snapshot_id is not None and not isinstance(snapshot_id, str):
        raise ValueError("snapshot_id must be a string or null")
    return chebi_ids, snapshot_id


def run_batch(chebi_ids, *, index_path=None, snapshot_id=None, **lookup_policy):
    """Return per-input diagnostics; duplicate normalized IDs reuse one local lookup."""
    if not isinstance(chebi_ids, list):
        raise ValueError("chebi_ids must be a list")
    lookup = GemLookup(index_path, **lookup_policy)
    result = lookup.map_many(chebi_ids)
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "input_snapshot_id": snapshot_id,
        "lookup_policy": {
            "hub_threshold": lookup.hub_threshold,
            "hub_policy": lookup.hub_policy,
            "currency_ids": sorted(lookup.currency_ids),
            "max_reactions": lookup.max_reactions,
            "max_candidates": lookup.max_candidates,
        },
        "summary": {key: result[key] for key in (
            "input_count", "unique_valid_chebi_count", "mapped", "unmapped",
            "ambiguous", "errors", "count_note"
        )},
        "records": result["records"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--include-hubs", action="store_true")
    parser.add_argument("--hub-threshold", type=int, default=200)
    parser.add_argument("--max-reactions", type=int, default=200)
    parser.add_argument("--max-candidates", type=int, default=100)
    args = parser.parse_args()
    try:
        chebi_ids, snapshot_id = load_inputs(args.input)
        result = run_batch(
            chebi_ids,
            index_path=args.index,
            snapshot_id=snapshot_id,
            hub_policy="include" if args.include_hubs else "suppress",
            hub_threshold=args.hub_threshold,
            max_reactions=args.max_reactions,
            max_candidates=args.max_candidates,
        )
        write_new(args.output, canonical_bytes(result))
    except Exception as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps({"status": "ok", "output": str(args.output), **result["summary"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
