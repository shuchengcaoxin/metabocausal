"""L08 - reproduce the MVP2 merge, and measure what canonical dedup discarded.

  1. re-run MVP2/scripts/merge_new_pairs.py into a scratch directory and compare its
     output with the committed merged CSV (content compared after CRLF -> LF, because
     L04 established the working tree carries CRLF while the writer emits LF);
  2. count what the one-row-per-canonical-key rule dropped: how many source rows were
     collapsed, and how many of those carried an estimate different from the row kept;
  3. check the two provenance fields the merge writes as constants against that count.

No MVP2 file is written: the merge runs with --output inside this probe's outputs/
directory. Deterministic, offline.

Run from the repository root:
    python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/mvp2/probes/probe_L08_merge.py
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from collections import defaultdict


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
SCRATCH = os.path.join(OUT_DIR, "L08_merge_rerun")
sys.path.insert(0, os.path.join(REPO, "MVP2"))

from src.pair_screening import canonical_pair_key, read_csv  # noqa: E402

SCREENED = os.path.join(REPO, "MVP2", "data", "extracted", "screened_20260912")
COMMITTED_MERGED = os.path.join(
    REPO, "MVP2", "data", "extracted", "mvp1_plus_mvp2_candidate_metabolite_disease.csv"
)
BASELINE = os.path.join(
    REPO,
    "archive",
    "project_files",
    "release-evidence_2026-09-11",
    "metabocausal-public",
    "data",
    "metabolite_disease.csv",
)


def lf_digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read().replace(b"\r\n", b"\n")).hexdigest()


def main() -> int:
    os.makedirs(SCRATCH, exist_ok=True)
    lines = ["L08 - merge reproduction and dedup accounting", ""]
    record = {}

    # ---------------------------------------------------------------- 1. reproduce
    output = os.path.join(SCRATCH, "merged.csv")
    cmd = [
        sys.executable,
        os.path.join("MVP2", "scripts", "merge_new_pairs.py"),
        "--baseline",
        os.path.relpath(BASELINE, REPO),
        "--new-pairs",
        os.path.relpath(os.path.join(SCREENED, "new_unique_pairs.csv"), REPO),
        "--output",
        output,
    ]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", env=env
    )
    lines.append("[1] re-running the merge into a scratch output")
    lines.append("    command: python MVP2/scripts/merge_new_pairs.py --output <scratch>/merged.csv")
    lines.append("    exit code: %d" % proc.returncode)
    if proc.stdout.strip():
        lines.append("    stdout: %s" % proc.stdout.strip())
    if proc.stderr.strip():
        for line in proc.stderr.strip().splitlines():
            lines.append("    stderr: %s" % line)
    record["rerun"] = {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}

    if proc.returncode == 0:
        fresh = lf_digest(output)
        committed = lf_digest(COMMITTED_MERGED)
        lines.append("")
        lines.append("    sha256 after CRLF->LF, re-run merged csv   : %s" % fresh)
        lines.append("    sha256 after CRLF->LF, committed merged csv: %s" % committed)
        lines.append("    byte-identical (normalised): %s" % (fresh == committed))
        record["merge_reproduces"] = fresh == committed
        record["rerun_digest"] = fresh
        record["committed_digest"] = committed

        with io.open(
            os.path.join(SCRATCH, "merged.manifest.json"), "r", encoding="utf-8"
        ) as handle:
            fresh_manifest = json.load(handle)
        with io.open(
            os.path.join(
                REPO,
                "MVP2",
                "data",
                "extracted",
                "mvp1_plus_mvp2_candidate_metabolite_disease.manifest.json",
            ),
            "r",
            encoding="utf-8",
        ) as handle:
            committed_manifest = json.load(handle)
        lines.append("")
        lines.append("    summary block, re-run vs committed manifest:")
        lines.append(
            "      %-34s %-12s %-12s %s" % ("field", "committed", "re-run", "verdict")
        )
        summary_cmp = {}
        for field in sorted(committed_manifest["summary"]):
            a = committed_manifest["summary"][field]
            b = fresh_manifest["summary"].get(field)
            summary_cmp[field] = {"committed": a, "rerun": b, "ok": a == b}
            lines.append(
                "      %-34s %-12s %-12s %s" % (field, a, b, "OK" if a == b else "MISMATCH")
            )
        record["summary_comparison"] = summary_cmp

        # The two re-run CSVs are ~13 MB of bytes already present in the repository;
        # their digests are recorded above, so the copies are removed and only the
        # re-run manifest is kept.
        for name in ("merged.csv", "merged.provenance.csv"):
            try:
                os.remove(os.path.join(SCRATCH, name))
            except OSError:
                pass
        lines.append("")
        lines.append(
            "    the two re-run CSVs were deleted after hashing; "
            "L08_merge_rerun/merged.manifest.json is kept"
        )

    # ---------------------------------------------------------------- 2. dedup accounting
    lines.append("")
    lines.append("[2] what the one-row-per-canonical-key rule discarded")
    lines.append("")
    all_new = read_csv(os.path.join(SCREENED, "new_pair_records.csv"))
    kept = read_csv(os.path.join(SCREENED, "new_unique_pairs.csv"))
    kept_by_key = {}
    for row in kept:
        kept_by_key[canonical_pair_key(row)] = row
    grouped = defaultdict(list)
    for row in all_new:
        grouped[canonical_pair_key(row)].append(row)

    collapsed_rows = 0
    keys_with_extras = 0
    differing_estimate = 0
    differing_label = 0
    examples = []
    for key, rows in grouped.items():
        if len(rows) <= 1:
            continue
        keys_with_extras += 1
        representative = kept_by_key.get(key)
        if representative is None:
            continue
        rep = (
            str(representative.get("beta", "")),
            str(representative.get("p_value", "")),
            str(representative.get("method", "")),
        )
        rep_label = str(representative.get("metabolite_name", ""))
        for row in rows:
            if row is representative:
                continue
            collapsed_rows += 1
            other = (
                str(row.get("beta", "")),
                str(row.get("p_value", "")),
                str(row.get("method", "")),
            )
            if other != rep:
                differing_estimate += 1
            if str(row.get("metabolite_name", "")) != rep_label:
                differing_label += 1
                if len(examples) < 8:
                    examples.append(
                        {
                            "canonical_key": key,
                            "kept": {
                                "metabolite_name": rep_label,
                                "metabolite_id": representative.get("metabolite_id"),
                                "beta": representative.get("beta"),
                                "p_value": representative.get("p_value"),
                                "sheet": representative.get("source_sheet"),
                                "row": representative.get("source_row"),
                            },
                            "discarded": {
                                "metabolite_name": row.get("metabolite_name"),
                                "metabolite_id": row.get("metabolite_id"),
                                "beta": row.get("beta"),
                                "p_value": row.get("p_value"),
                                "sheet": row.get("source_sheet"),
                                "row": row.get("source_row"),
                            },
                        }
                    )

    lines.append("    new_pair_records.csv rows                    : %d" % len(all_new))
    lines.append("    new_unique_pairs.csv rows (one per key)      : %d" % len(kept))
    lines.append("    rows discarded by dedup                      : %d" % (len(all_new) - len(kept)))
    lines.append("    canonical keys holding more than one row     : %d" % keys_with_extras)
    lines.append("    discarded rows counted in those groups       : %d" % collapsed_rows)
    lines.append(
        "    ... whose (beta, p_value, method) differs from the kept row : %d"
        % differing_estimate
    )
    lines.append(
        "    ... whose metabolite_name differs from the kept row         : %d"
        % differing_label
    )
    record["dedup_accounting"] = {
        "new_pair_records": len(all_new),
        "new_unique_pairs": len(kept),
        "rows_discarded": len(all_new) - len(kept),
        "keys_with_more_than_one_row": keys_with_extras,
        "discarded_rows_in_those_groups": collapsed_rows,
        "discarded_with_different_estimate": differing_estimate,
        "discarded_with_different_metabolite_label": differing_label,
        "examples": examples,
    }
    lines.append("")
    lines.append("    examples where the discarded row names a different exposure:")
    for example in examples:
        lines.append("      key %s" % example["canonical_key"])
        lines.append("        kept      %s" % json.dumps(example["kept"], sort_keys=True))
        lines.append("        discarded %s" % json.dumps(example["discarded"], sort_keys=True))

    # ---------------------------------------------------------------- 3. constant fields
    lines.append("")
    lines.append("[3] the constants the merge writes into every appended row")
    provenance = read_csv(
        os.path.join(
            REPO,
            "MVP2",
            "data",
            "extracted",
            "mvp1_plus_mvp2_candidate_metabolite_disease.provenance.csv",
        )
    )
    merged = read_csv(COMMITTED_MERGED)
    appended = [r for r in merged if r.get("record_type") == "published_literature_mr_candidate"]
    supporting = defaultdict(int)
    rule = defaultdict(int)
    for row in appended:
        supporting[str(row.get("supporting_mr_rows", ""))] += 1
        rule[str(row.get("representative_rule", ""))] += 1
    lines.append("    appended rows in the merged csv: %d" % len(appended))
    lines.append("    supporting_mr_rows values:")
    for value in sorted(supporting):
        lines.append("      %-6r %d rows" % (value, supporting[value]))
    lines.append("    representative_rule values:")
    for value in sorted(rule):
        lines.append("      %d rows: %s" % (rule[value], value))
    lines.append("")
    lines.append(
        "    measured: %d of those %d appended pairs stand for more than one source row"
        % (keys_with_extras, len(appended))
    )
    lines.append("    provenance sidecar rows: %d" % len(provenance))
    record["appended_constants"] = {
        "appended_rows": len(appended),
        "supporting_mr_rows_values": dict(supporting),
        "representative_rule_values": dict(rule),
        "pairs_standing_for_more_than_one_source_row": keys_with_extras,
        "provenance_rows": len(provenance),
    }

    # ---------------------------------------------------------------- 4. bounds carried through
    lines.append("")
    lines.append("[4] do the inverted bounds survive into the merged candidate table")
    lines.append("    (merge maps ci_low -> ci_low and ci_high -> ci_upp)")
    lines.append("")
    baseline_rows = [
        r for r in merged if r.get("record_type") != "published_literature_mr_candidate"
    ]
    bounds = {}
    for label, group in (("MVP1 baseline rows", baseline_rows), ("appended MVP2 rows", appended)):
        inverted = ordered = absent = 0
        for row in group:
            try:
                low = float(row.get("ci_low"))
                upp = float(row.get("ci_upp"))
            except (TypeError, ValueError):
                absent += 1
                continue
            if low > upp:
                inverted += 1
            else:
                ordered += 1
        bounds[label] = {"rows": len(group), "inverted": inverted, "ordered": ordered, "no_bounds": absent}
        lines.append(
            "    %-22s rows %-7d ci_low>ci_upp %-7d ordered %-7d no bounds %d"
            % (label, len(group), inverted, ordered, absent)
        )
    record["merged_bound_ordering"] = bounds

    text = "\n".join(lines) + "\n"
    with io.open(os.path.join(OUT_DIR, "L08_merge.txt"), "w", encoding="utf-8") as handle:
        handle.write(text)
    with io.open(os.path.join(OUT_DIR, "L08_merge.json"), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
