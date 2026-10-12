"""L05 - record-level integrity of the screened MVP2 candidate tables.

Measured against MVP2/data/extracted/screened_20260912/ using the teammate's own
identity functions (src.pair_screening.pair_keys / canonical_pair_key / normalize), so
the numbers describe her pipeline's semantics rather than a re-invented one.

  1. provenance column completeness, per file
  2. do the recorded source_path values exist in this repository
  3. how much of the anti-join runs on resolved IDs versus on free-text labels
  4. the `direction` vocabulary, including rows with no direction recorded
  5. duplicate canonical pair keys inside new_unique_pairs.csv
  6. distinct source rows collapsed into one canonical key (what dedup discarded)
  7. numeric field sanity on the kept unique pairs
  8. the outcome vocabulary actually carried into the "disease" column

Deterministic, offline, read-only.

Run from the repository root:
    python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/mvp2/probes/probe_L05_records.py
"""

from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter, defaultdict


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

from src.pair_screening import canonical_pair_key, normalize, pair_keys, read_csv  # noqa: E402

SCREENED = os.path.join(REPO, "MVP2", "data", "extracted", "screened_20260912")
FILES = {
    "candidate_pairs.csv": os.path.join(SCREENED, "candidate_pairs.csv"),
    "new_pair_records.csv": os.path.join(SCREENED, "new_pair_records.csv"),
    "new_unique_pairs.csv": os.path.join(SCREENED, "new_unique_pairs.csv"),
    "screening_ledger.csv": os.path.join(SCREENED, "screening_ledger.csv"),
}
PROVENANCE_COLUMNS = [
    "study_id",
    "source_path",
    "source_sheet",
    "source_row",
    "pair_relation_verified",
    "pair_relation_basis",
    "record_type",
]


def is_float(value: str):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    lines = ["L05 - record-level integrity of screened_20260912", ""]
    record = {}

    tables = {name: read_csv(path) for name, path in FILES.items()}
    for name in sorted(tables):
        lines.append("  %-24s %d data rows" % (name, len(tables[name])))

    # -------------------------------------------------- 1. provenance completeness
    lines.append("")
    lines.append("[1] provenance column completeness (count of rows with an empty value)")
    lines.append("")
    completeness = {}
    header = "  %-24s " % "file" + " ".join("%-22s" % c for c in PROVENANCE_COLUMNS)
    lines.append(header)
    for name in sorted(tables):
        rows = tables[name]
        empties = {
            column: sum(1 for row in rows if not str(row.get(column, "") or "").strip())
            for column in PROVENANCE_COLUMNS
        }
        completeness[name] = {"rows": len(rows), "empty": empties}
        lines.append(
            "  %-24s " % name + " ".join("%-22d" % empties[c] for c in PROVENANCE_COLUMNS)
        )
    record["provenance_completeness"] = completeness

    # -------------------------------------------------- 2. source_path resolvability
    lines.append("")
    lines.append("[2] recorded source_path values, resolved against this repository")
    paths = Counter()
    for row in tables["candidate_pairs.csv"]:
        paths[str(row.get("source_path", "") or "").strip()] += 1
    path_rows = []
    missing = 0
    for path in sorted(paths):
        exists = os.path.isfile(os.path.join(REPO, path.replace("/", os.sep)))
        if not exists:
            missing += 1
        path_rows.append({"source_path": path, "rows": paths[path], "exists": exists})
        lines.append(
            "    %-6s %7d rows  %s" % ("OK" if exists else "MISSING", paths[path], path)
        )
    lines.append("    distinct source files: %d, missing from this checkout: %d" % (len(paths), missing))
    record["source_paths"] = path_rows

    # -------------------------------------------------- 3. identity resolution
    lines.append("")
    lines.append("[3] resolved identities vs free-text labels (what the anti-join matched on)")
    lines.append("")
    identity = {}
    for name in ("candidate_pairs.csv", "new_unique_pairs.csv"):
        rows = tables[name]
        met_id = sum(1 for r in rows if str(r.get("metabolite_id", "") or "").strip())
        dis_id = sum(1 for r in rows if str(r.get("disease_id", "") or "").strip())
        id_keyed = sum(1 for r in rows if any(k.startswith("id|") for k in pair_keys(r)))
        name_only = sum(
            1
            for r in rows
            if pair_keys(r) and not any(k.startswith("id|") for k in pair_keys(r))
        )
        no_key = sum(1 for r in rows if not pair_keys(r))
        identity[name] = {
            "rows": len(rows),
            "metabolite_id_present": met_id,
            "disease_id_present": dis_id,
            "rows_with_an_id_key": id_keyed,
            "rows_keyed_on_name_only": name_only,
            "rows_with_no_key": no_key,
        }
        lines.append("  %s (%d rows)" % (name, len(rows)))
        lines.append("    metabolite_id non-empty : %d" % met_id)
        lines.append("    disease_id non-empty    : %d" % dis_id)
        lines.append("    rows carrying an id|... key : %d" % id_keyed)
        lines.append("    rows keyed on name|... only : %d" % name_only)
        lines.append("    rows with no usable key     : %d" % no_key)
    record["identity_resolution"] = identity

    # -------------------------------------------------- 4. direction vocabulary
    lines.append("")
    lines.append("[4] `direction` vocabulary in candidate_pairs.csv, and how each was screened")
    lines.append("")
    ledger = tables["screening_ledger.csv"]
    direction_status = defaultdict(Counter)
    for row in ledger:
        direction_status[str(row.get("direction", "") or "").strip()][row["screen_status"]] += 1
    dir_rows = []
    for direction in sorted(direction_status, key=lambda d: -sum(direction_status[d].values())):
        counts = dict(direction_status[direction])
        dir_rows.append({"direction": direction or "(empty)", "by_screen_status": counts})
        lines.append("    %-22s %s" % (direction or "(empty)", json.dumps(counts, sort_keys=True)))
    record["direction_vocabulary"] = dir_rows
    empty_forward = direction_status.get("", Counter()).get("new_pair", 0)
    lines.append("")
    lines.append(
        "    rows with NO direction recorded that were kept as a new forward pair: %d"
        % empty_forward
    )
    lines.append(
        "    (src/pair_screening.py:_is_forward treats the empty string as forward:"
    )
    with io.open(os.path.join(REPO, "MVP2", "src", "pair_screening.py"), "r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if 'direction in {""' in line or "direction in {\"\"" in line:
                lines.append("     src/pair_screening.py:%d %s" % (lineno, line.strip()))
    lines.append("    )")
    record["empty_direction_kept_as_forward"] = empty_forward

    # -------------------------------------------------- 5. duplicate canonical keys
    lines.append("")
    lines.append("[5] duplicate canonical pair keys inside new_unique_pairs.csv")
    unique_rows = tables["new_unique_pairs.csv"]
    key_counts = Counter(canonical_pair_key(row) for row in unique_rows)
    dupes = {k: v for k, v in key_counts.items() if v > 1 and k}
    empty_keys = key_counts.get("", 0)
    lines.append("    distinct canonical keys : %d" % len([k for k in key_counts if k]))
    lines.append("    keys appearing twice+   : %d" % len(dupes))
    lines.append("    rows with an empty key  : %d" % empty_keys)
    record["unique_pairs_duplicate_keys"] = {
        "distinct_keys": len([k for k in key_counts if k]),
        "duplicate_keys": len(dupes),
        "rows_with_empty_key": empty_keys,
        "examples": sorted(dupes)[:10],
    }

    # -------------------------------------------------- 6. dedup collapse
    lines.append("")
    lines.append("[6] what canonical-key dedup collapsed: distinct source label pairs per key")
    collapse = defaultdict(set)
    for row in tables["new_pair_records.csv"]:
        key = canonical_pair_key(row)
        if key:
            collapse[key].add(
                (
                    str(row.get("metabolite_name", "") or "").strip(),
                    str(row.get("disease_trait", "") or "").strip(),
                )
            )
    multi = {k: v for k, v in collapse.items() if len(v) > 1}
    lines.append("    canonical keys built from new_pair_records.csv : %d" % len(collapse))
    lines.append(
        "    keys covering more than one distinct raw (metabolite, disease) label pair: %d"
        % len(multi)
    )
    examples = []
    for key in sorted(multi, key=lambda k: -len(multi[k]))[:10]:
        variants = sorted(multi[key])
        examples.append({"canonical_key": key, "raw_label_pairs": variants})
        lines.append("      %s" % key)
        for variant in variants[:6]:
            lines.append("        %r" % (variant,))
        if len(variants) > 6:
            lines.append("        ... %d more" % (len(variants) - 6))
    record["dedup_collapse"] = {
        "keys": len(collapse),
        "keys_with_multiple_raw_labels": len(multi),
        "examples": examples,
    }

    # -------------------------------------------------- 7. numeric sanity
    lines.append("")
    lines.append("[7] numeric field sanity on new_unique_pairs.csv (%d rows)" % len(unique_rows))
    numeric = {
        "beta_empty": 0,
        "beta_unparseable": 0,
        "se_empty": 0,
        "se_unparseable": 0,
        "se_not_positive": 0,
        "p_empty": 0,
        "p_unparseable": 0,
        "p_outside_0_1": 0,
        "p_exactly_zero": 0,
        "ci_pair_empty": 0,
        "ci_low_gt_ci_high": 0,
        "nsnp_empty": 0,
        "nsnp_unparseable": 0,
        "nsnp_lt_1": 0,
        "no_estimate_at_all": 0,
        "method_empty": 0,
    }
    offenders = defaultdict(list)
    for index, row in enumerate(unique_rows, 1):
        beta = str(row.get("beta", "") or "").strip()
        se = str(row.get("se", "") or "").strip()
        pval = str(row.get("p_value", "") or "").strip()
        lo = str(row.get("ci_low", "") or "").strip()
        hi = str(row.get("ci_high", "") or "").strip()
        nsnp = str(row.get("nsnp", "") or "").strip()
        if not str(row.get("method", "") or "").strip():
            numeric["method_empty"] += 1
        if not beta:
            numeric["beta_empty"] += 1
        elif is_float(beta) is None:
            numeric["beta_unparseable"] += 1
            offenders["beta_unparseable"].append((index, beta))
        if not se:
            numeric["se_empty"] += 1
        else:
            value = is_float(se)
            if value is None:
                numeric["se_unparseable"] += 1
                offenders["se_unparseable"].append((index, se))
            elif value <= 0:
                numeric["se_not_positive"] += 1
                offenders["se_not_positive"].append((index, se))
        if not pval:
            numeric["p_empty"] += 1
        else:
            value = is_float(pval)
            if value is None:
                numeric["p_unparseable"] += 1
                offenders["p_unparseable"].append((index, pval))
            else:
                if value < 0 or value > 1:
                    numeric["p_outside_0_1"] += 1
                    offenders["p_outside_0_1"].append((index, pval))
                if value == 0:
                    numeric["p_exactly_zero"] += 1
                    offenders["p_exactly_zero"].append((index, pval))
        if not lo or not hi:
            numeric["ci_pair_empty"] += 1
        else:
            a, b = is_float(lo), is_float(hi)
            if a is not None and b is not None and a > b:
                numeric["ci_low_gt_ci_high"] += 1
                offenders["ci_low_gt_ci_high"].append((index, "%s > %s" % (lo, hi)))
        if not nsnp:
            numeric["nsnp_empty"] += 1
        else:
            value = is_float(nsnp)
            if value is None:
                numeric["nsnp_unparseable"] += 1
                offenders["nsnp_unparseable"].append((index, nsnp))
            elif value < 1:
                numeric["nsnp_lt_1"] += 1
                offenders["nsnp_lt_1"].append((index, nsnp))
        if not beta and not se and not pval and not lo and not hi:
            numeric["no_estimate_at_all"] += 1
            offenders["no_estimate_at_all"].append((index, row.get("study_id", "")))
    for field in sorted(numeric):
        lines.append("    %-22s %d" % (field, numeric[field]))
    lines.append("")
    lines.append("    first offending rows (1-based row number within new_unique_pairs.csv):")
    for field in sorted(offenders):
        sample = offenders[field][:5]
        lines.append("      %-22s %s" % (field, sample))
    record["numeric_sanity"] = numeric
    record["numeric_offender_samples"] = {k: v[:20] for k, v in offenders.items()}

    # -------------------------------------------------- 8. outcome vocabulary
    lines.append("")
    lines.append("[8] outcome vocabulary carried in disease_trait (new_unique_pairs.csv)")
    traits = Counter(str(r.get("disease_trait", "") or "").strip() for r in unique_rows)
    normalized_traits = Counter(normalize(t) for t in traits)
    lines.append("    distinct disease_trait strings          : %d" % len(traits))
    lines.append("    distinct after normalize()              : %d" % len(normalized_traits))
    lines.append("    20 most frequent disease_trait values:")
    for trait, count in traits.most_common(20):
        lines.append("      %7d  %s" % (count, trait))
    collisions = defaultdict(set)
    for trait in traits:
        collisions[normalize(trait)].add(trait)
    colliding = {k: v for k, v in collisions.items() if len(v) > 1}
    lines.append(
        "    normalize() collisions (distinct raw strings sharing one normalized form): %d"
        % len(colliding)
    )
    for key in sorted(colliding)[:10]:
        lines.append("      %-40s <- %s" % (key, sorted(colliding[key])))
    record["outcome_vocabulary"] = {
        "distinct_raw": len(traits),
        "distinct_normalized": len(normalized_traits),
        "top_20": traits.most_common(20),
        "normalize_collisions": {k: sorted(v) for k, v in sorted(colliding.items())[:50]},
        "normalize_collision_count": len(colliding),
    }

    metabolites = Counter(str(r.get("metabolite_name", "") or "").strip() for r in unique_rows)
    met_collisions = defaultdict(set)
    for name in metabolites:
        met_collisions[normalize(name)].add(name)
    met_colliding = {k: v for k, v in met_collisions.items() if len(v) > 1}
    lines.append("")
    lines.append("    distinct metabolite_name strings        : %d" % len(metabolites))
    lines.append(
        "    normalize() collisions on metabolite_name: %d" % len(met_colliding)
    )
    for key in sorted(met_colliding)[:10]:
        lines.append("      %-40s <- %s" % (key, sorted(met_colliding[key])))
    record["metabolite_vocabulary"] = {
        "distinct_raw": len(metabolites),
        "normalize_collisions": {k: sorted(v) for k, v in sorted(met_colliding.items())[:50]},
        "normalize_collision_count": len(met_colliding),
    }

    text = "\n".join(lines) + "\n"
    with io.open(os.path.join(OUT_DIR, "L05_records.txt"), "w", encoding="utf-8") as handle:
        handle.write(text)
    with io.open(os.path.join(OUT_DIR, "L05_records.json"), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
