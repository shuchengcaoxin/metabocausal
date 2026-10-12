"""L07 - is every kept pair traceable to a search run, and are the identifiers well formed?

  1. coverage: kept unique pairs vs pairs that actually have a search record;
  2. forward traceability: for the searched pair, recompute its pair_id with the
     teammate's own _pair_id and confirm the row it names in new_unique_pairs.csv;
  3. the search-run manifest's own offset/limit claim, checked against the input file;
  4. identifier hygiene on every paper the search returned (pmid / pmcid / doi shape),
     plus the identifiers recorded in each seed's source_record.json;
  5. internal consistency of the pair record: returned ids vs retained papers, and the
     paper_count printed in pair_search_index.csv.

Deterministic, offline, read-only.

Run from the repository root:
    python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/mvp2/probes/probe_L07_ledger.py
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from collections import Counter


def _find_repo_root(start: str) -> str:
    here = os.path.abspath(start)
    while True:
        if (
            os.path.isfile(os.path.join(here, "render.py"))
            and os.path.isfile(os.path.join(here, "classify.py"))
            and os.path.isdir(os.path.join(here, "MVP2"))
        ):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            raise RuntimeError("repository root not found above %s" % start)
        here = parent


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = _find_repo_root(HERE)
OUT_DIR = os.path.abspath(os.path.join(HERE, "..", "outputs"))
sys.path.insert(0, os.path.join(REPO, "MVP2"))
sys.path.insert(0, os.path.join(REPO, "MVP2", "scripts"))

from search_pairs_europepmc import _pair_id, validate_pair  # noqa: E402
from src.pair_screening import read_csv  # noqa: E402

SEARCH_RUNS = os.path.join(REPO, "MVP2", "literature", "search_runs")
KEPT = os.path.join(
    REPO, "MVP2", "data", "extracted", "screened_20260912", "new_unique_pairs.csv"
)

PMID = re.compile(r"^[1-9][0-9]{0,8}$")
PMCID = re.compile(r"^PMC[0-9]+$")
DOI = re.compile(r"^10\.[0-9]{4,9}/\S+$")


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    lines = ["L07 - search-run traceability and identifier hygiene", ""]
    record = {}

    kept = read_csv(KEPT)

    # ---------------------------------------------------------------- 1. coverage
    runs = sorted(
        name
        for name in os.listdir(SEARCH_RUNS)
        if os.path.isdir(os.path.join(SEARCH_RUNS, name))
    )
    pair_files = sorted(glob.glob(os.path.join(SEARCH_RUNS, "*", "pairs", "*.json")))
    lines.append("[1] coverage of the screening ledger by actual searches")
    lines.append("")
    lines.append("  kept unique pairs in new_unique_pairs.csv : %d" % len(kept))
    lines.append("  search_runs directories                   : %d" % len(runs))
    for name in runs:
        manifest_path = os.path.join(SEARCH_RUNS, name, "manifest.json")
        has_pairs = os.path.isdir(os.path.join(SEARCH_RUNS, name, "pairs"))
        count = len(glob.glob(os.path.join(SEARCH_RUNS, name, "pairs", "*.json")))
        lines.append(
            "    %-46s manifest=%s pairs/=%s records=%d"
            % (name, os.path.isfile(manifest_path), has_pairs, count)
        )
    lines.append("  pair search records on disk               : %d" % len(pair_files))
    coverage = len(pair_files) / len(kept) if kept else 0.0
    lines.append(
        "  coverage                                  : %d / %d = %.5f%%"
        % (len(pair_files), len(kept), coverage * 100)
    )
    lines.append(
        "  kept pairs with NO search record          : %d" % (len(kept) - len(pair_files))
    )
    record["coverage"] = {
        "kept_unique_pairs": len(kept),
        "search_run_dirs": runs,
        "pair_records": len(pair_files),
        "fraction": coverage,
        "pairs_without_a_search_record": len(kept) - len(pair_files),
    }

    # ---------------------------------------------------------------- 2. traceability
    lines.append("")
    lines.append("[2] forward traceability of each search record to a kept pair")
    lines.append("    pair_id recomputed with search_pairs_europepmc._pair_id")
    lines.append("")
    kept_by_id = {}
    for index, row in enumerate(kept, 1):
        kept_by_id.setdefault(_pair_id(row), []).append(index)
    trace = []
    for path in pair_files:
        with io.open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        stated = payload.get("pair_id")
        recomputed = _pair_id(payload["input_pair"])
        rows = kept_by_id.get(recomputed, [])
        eligible, reason = validate_pair(payload["input_pair"])
        trace.append(
            {
                "file": os.path.relpath(path, REPO).replace("\\", "/"),
                "pair_id_in_file": stated,
                "pair_id_recomputed": recomputed,
                "matches": stated == recomputed,
                "rows_in_new_unique_pairs": rows,
                "validate_pair": [eligible, reason],
            }
        )
        lines.append("  %s" % os.path.relpath(path, REPO).replace("\\", "/"))
        lines.append("    pair_id in file      : %s" % stated)
        lines.append("    pair_id recomputed   : %s" % recomputed)
        lines.append("    agree                : %s" % (stated == recomputed))
        lines.append("    row(s) in new_unique_pairs.csv : %s" % (rows or "NONE"))
        lines.append("    validate_pair()      : %s / %s" % (eligible, reason))
    record["traceability"] = trace

    # ---------------------------------------------------------------- 3. offset claim
    lines.append("")
    lines.append("[3] the run manifest's offset/limit claim, checked against the input file")
    for name in runs:
        manifest_path = os.path.join(SEARCH_RUNS, name, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        with io.open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        config = manifest.get("config")
        if not config or "offset" not in config:
            lines.append("  %s: no offset/limit config" % name)
            continue
        offset = config["offset"]
        limit = config.get("limit")
        lines.append("  %s" % name)
        lines.append("    config offset=%s limit=%s" % (offset, limit))
        selected = kept[offset : offset + (limit or len(kept))]
        for row in selected:
            lines.append(
                "    row %d of new_unique_pairs.csv: %r x %r  (pair_id %s)"
                % (
                    offset + 1,
                    row.get("metabolite_name"),
                    row.get("disease_trait"),
                    _pair_id(row),
                )
            )
        stated_rows = manifest.get("input", {}).get("rows")
        lines.append(
            "    manifest input.rows=%s vs counted %d -> %s"
            % (stated_rows, len(kept), "OK" if stated_rows == len(kept) else "MISMATCH")
        )
        record.setdefault("offset_claims", {})[name] = {
            "offset": offset,
            "limit": limit,
            "selected_pair_ids": [_pair_id(row) for row in selected],
            "input_rows_claimed": stated_rows,
            "input_rows_counted": len(kept),
        }

    # ---------------------------------------------------------------- 4. identifiers
    lines.append("")
    lines.append("[4] identifier hygiene on every paper returned by the search")
    lines.append("")
    ident = {
        "papers": 0,
        "pmid_present": 0,
        "pmid_malformed": 0,
        "pmcid_present": 0,
        "pmcid_malformed": 0,
        "doi_present": 0,
        "doi_malformed": 0,
        "no_identifier_at_all": 0,
        "title_empty": 0,
        "abstract_empty": 0,
        "year_empty": 0,
    }
    malformed_examples = []
    seen_pmids = Counter()
    for path in pair_files:
        with io.open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        for paper in payload.get("search", {}).get("papers", []):
            ident["papers"] += 1
            ids = paper.get("identifiers", {}) or {}
            pmid = str(ids.get("pmid", "") or "").strip()
            pmcid = str(ids.get("pmcid", "") or "").strip()
            doi = str(ids.get("doi", "") or "").strip()
            if not (pmid or pmcid or doi or ids.get("id")):
                ident["no_identifier_at_all"] += 1
            if pmid:
                ident["pmid_present"] += 1
                seen_pmids[pmid] += 1
                if not PMID.match(pmid):
                    ident["pmid_malformed"] += 1
                    malformed_examples.append(("pmid", pmid, paper.get("title", "")[:60]))
            if pmcid:
                ident["pmcid_present"] += 1
                if not PMCID.match(pmcid):
                    ident["pmcid_malformed"] += 1
                    malformed_examples.append(("pmcid", pmcid, paper.get("title", "")[:60]))
            if doi:
                ident["doi_present"] += 1
                if not DOI.match(doi):
                    ident["doi_malformed"] += 1
                    malformed_examples.append(("doi", doi, paper.get("title", "")[:60]))
            if not str(paper.get("title", "") or "").strip():
                ident["title_empty"] += 1
            if not str(paper.get("abstract", "") or "").strip():
                ident["abstract_empty"] += 1
            if not str(paper.get("publication_year", "") or "").strip():
                ident["year_empty"] += 1
    for field in sorted(ident):
        lines.append("    %-24s %d" % (field, ident[field]))
    duplicate_pmids = {k: v for k, v in seen_pmids.items() if v > 1}
    lines.append("    %-24s %d" % ("duplicate pmids", len(duplicate_pmids)))
    if malformed_examples:
        lines.append("    malformed examples:")
        for kind, value, title in malformed_examples[:10]:
            lines.append("      %-6s %r  %s" % (kind, value, title))
    record["paper_identifiers"] = ident
    record["duplicate_pmids"] = duplicate_pmids

    # seed source records
    lines.append("")
    lines.append("    identifiers recorded in each seed's source_record.json:")
    seed_rows = []
    for path in sorted(glob.glob(os.path.join(REPO, "MVP2", "literature", "seeds", "*", "source_record.json"))):
        with io.open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        blob = json.dumps(payload)
        pmids = sorted(set(re.findall(r'"pmid"\s*:\s*"?([^",}\s]+)', blob)))
        pmcids = sorted(set(re.findall(r"PMC[0-9]+", blob)))
        dois = sorted(set(re.findall(r"10\.[0-9]{4,9}/[^\"\s,}]+", blob)))
        bad = [p for p in pmids if not PMID.match(p)] + [p for p in pmcids if not PMCID.match(p)]
        seed = os.path.basename(os.path.dirname(path))
        seed_rows.append(
            {"seed": seed, "pmids": pmids, "pmcids": pmcids[:5], "dois": dois[:5], "malformed": bad}
        )
        lines.append(
            "      %-20s pmid=%s pmcid=%s doi=%s malformed=%s"
            % (seed, pmids or "-", pmcids[:3] or "-", dois[:2] or "-", bad or "none")
        )
    record["seed_identifiers"] = seed_rows

    # ---------------------------------------------------------------- 5. internal
    lines.append("")
    lines.append("[5] internal consistency of each pair record")
    consistency = []
    for path in pair_files:
        with io.open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        search = payload.get("search", {})
        papers = search.get("papers", [])
        retained = {str((p.get("identifiers") or {}).get("id", "")) for p in papers}
        retained.discard("")
        returned = set()
        for entry in search.get("search_history", []):
            for value in entry.get("returned_ids", []) or []:
                returned.add(str(value))
        index_path = os.path.join(os.path.dirname(os.path.dirname(path)), "pair_search_index.csv")
        index_rows = read_csv(index_path) if os.path.isfile(index_path) else []
        index_row = next(
            (r for r in index_rows if r.get("pair_id") == payload.get("pair_id")), None
        )
        stated_count = int(index_row["paper_count"]) if index_row else None
        stated_rounds = int(index_row["round_count"]) if index_row else None
        entry = {
            "file": os.path.relpath(path, REPO).replace("\\", "/"),
            "papers_retained": len(papers),
            "distinct_retained_ids": len(retained),
            "ids_returned_by_queries": len(returned),
            "returned_but_not_retained": sorted(returned - retained)[:10],
            "retained_but_never_returned": sorted(retained - returned)[:10],
            "index_paper_count": stated_count,
            "index_round_count": stated_rounds,
            "rounds_in_record": len(search.get("rounds", [])),
            "status": search.get("status"),
            "stop_reason": search.get("stop_reason"),
            "remaining_gaps": search.get("remaining_gaps"),
        }
        consistency.append(entry)
        lines.append("  %s" % entry["file"])
        for key in (
            "papers_retained",
            "distinct_retained_ids",
            "ids_returned_by_queries",
            "index_paper_count",
            "index_round_count",
            "rounds_in_record",
            "status",
            "stop_reason",
        ):
            lines.append("    %-28s %s" % (key, entry[key]))
        lines.append("    returned_but_not_retained   %s" % entry["returned_but_not_retained"])
        lines.append("    retained_but_never_returned %s" % entry["retained_but_never_returned"])
        lines.append("    remaining_gaps              %s" % entry["remaining_gaps"])
    record["pair_record_consistency"] = consistency

    text = "\n".join(lines) + "\n"
    with io.open(os.path.join(OUT_DIR, "L07_ledger.txt"), "w", encoding="utf-8") as handle:
        handle.write(text)
    with io.open(os.path.join(OUT_DIR, "L07_ledger.json"), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
