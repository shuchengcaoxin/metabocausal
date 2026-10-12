"""L04 - do the MVP2 data-layer manifests verify against the files they describe?

Three independent questions, each answered against the checked-out bytes:

  (a) every sha256 recorded in an MVP2 manifest, verified as-is and after a
      CRLF -> LF normalisation, with the git end-of-line attribute printed beside it;
  (b) every row count claimed in a manifest, against the CSV it names;
  (c) the screening summary itself, recomputed by re-running the teammate's own
      src.pair_screening.screen_pairs over the committed baseline and candidate table.

Deterministic, offline, read-only. No MVP2 file is written or modified.

Run from the repository root:
    python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/mvp2/probes/probe_L04_manifests.py
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys


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

from src.pair_screening import read_csv, screen_pairs  # noqa: E402

SCREENED = "MVP2/data/extracted/screened_20260912"
MERGED = "MVP2/data/extracted/mvp1_plus_mvp2_candidate_metabolite_disease"
BATCH = "MVP2/literature/search_runs/pair_batch_smoke_glycine_cad_20260912"
BASELINE_IN_REPO = (
    "archive/project_files/release-evidence_2026-09-11/metabocausal-public/data/"
    "metabolite_disease.csv"
)


def read_bytes(rel: str) -> bytes:
    with open(os.path.join(REPO, rel), "rb") as handle:
        return handle.read()


def digests(rel: str) -> dict:
    raw = read_bytes(rel)
    lf = raw.replace(b"\r\n", b"\n")
    return {
        "as_is": hashlib.sha256(raw).hexdigest(),
        "crlf_to_lf": hashlib.sha256(lf).hexdigest(),
        "bytes": len(raw),
        "crlf_lines": raw.count(b"\r\n"),
        "bare_lf_lines": raw.count(b"\n") - raw.count(b"\r\n"),
    }


def index_blob_sha256(rel: str) -> str:
    """sha256 of the bytes git actually stores for this path (what a Linux/macOS
    checkout with core.autocrlf off would put in the working tree)."""
    proc = subprocess.run(
        ["git", "cat-file", "blob", "HEAD:%s" % rel],
        cwd=REPO,
        capture_output=True,
    )
    if proc.returncode != 0:
        return "(git cat-file failed: %s)" % proc.stderr.decode("utf-8", "replace").strip()
    return hashlib.sha256(proc.stdout).hexdigest()


def eol_attr(rel: str) -> str:
    proc = subprocess.run(
        ["git", "ls-files", "--eol", "--", rel],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.stdout.strip() or "(not tracked / git unavailable)"


def load_json(rel: str) -> dict:
    with io.open(os.path.join(REPO, rel), "r", encoding="utf-8") as handle:
        return json.load(handle)


def csv_data_rows(rel: str) -> int:
    return len(read_csv(os.path.join(REPO, rel)))


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    lines = ["L04 - MVP2 data-layer manifest verification", ""]
    record = {"checks": []}

    screened_manifest = load_json("%s/manifest.json" % SCREENED)
    merged_manifest = load_json("%s.manifest.json" % MERGED)
    batch_manifest = load_json("%s/manifest.json" % BATCH)

    # ---------------------------------------------------------------- (a) hashes
    # Every hash assertion in the MVP2 data layer, with the file it points at
    # resolved to a path inside this repository.
    assertions = [
        (
            "screened_20260912/manifest.json :: baseline.sha256",
            screened_manifest["baseline"]["sha256"],
            BASELINE_IN_REPO,
            screened_manifest["baseline"]["path"],
        ),
        (
            "mvp1_plus_mvp2...manifest.json :: inputs.baseline.sha256",
            merged_manifest["inputs"]["baseline"]["sha256"],
            BASELINE_IN_REPO,
            merged_manifest["inputs"]["baseline"]["path"],
        ),
        (
            "mvp1_plus_mvp2...manifest.json :: inputs.new_pairs.sha256",
            merged_manifest["inputs"]["new_pairs"]["sha256"],
            "%s/new_unique_pairs.csv" % SCREENED,
            merged_manifest["inputs"]["new_pairs"]["path"],
        ),
        (
            "mvp1_plus_mvp2...manifest.json :: outputs.merged_csv.sha256",
            merged_manifest["outputs"]["merged_csv"]["sha256"],
            "%s.csv" % MERGED,
            merged_manifest["outputs"]["merged_csv"]["path"],
        ),
        (
            "mvp1_plus_mvp2...manifest.json :: outputs.provenance_csv.sha256",
            merged_manifest["outputs"]["provenance_csv"]["sha256"],
            "%s.provenance.csv" % MERGED,
            merged_manifest["outputs"]["provenance_csv"]["path"],
        ),
        (
            "mvp1_plus_mvp2...manifest.json :: outputs.reference_original_merged_csv.sha256",
            merged_manifest["outputs"]["reference_original_merged_csv"]["sha256"],
            "%s.reference_original_merged.csv" % MERGED,
            merged_manifest["outputs"]["reference_original_merged_csv"]["path"],
        ),
        (
            "pair_batch_smoke.../manifest.json :: input.sha256",
            batch_manifest["input"]["sha256"],
            "%s/new_unique_pairs.csv" % SCREENED,
            batch_manifest["input"]["path"],
        ),
    ]

    lines.append("(a) sha256 assertions, verified against the checked-out bytes")
    lines.append("")
    hash_rows = []
    for label, claimed, rel, recorded_path in assertions:
        got = digests(rel)
        blob = index_blob_sha256(rel)
        as_is = claimed == got["as_is"]
        normalized = claimed == got["crlf_to_lf"]
        verdict = "PASS(as-is)" if as_is else ("PASS(after CRLF->LF)" if normalized else "FAIL")
        lines.append("  %s" % label)
        lines.append("    manifest records path : %s" % recorded_path)
        lines.append("    resolved in this repo : %s" % rel)
        lines.append("    claimed               : %s" % claimed)
        lines.append("    file as-is (this OS)  : %s" % got["as_is"])
        lines.append("    file after CRLF->LF   : %s" % got["crlf_to_lf"])
        lines.append("    committed blob bytes  : %s" % blob)
        lines.append(
            "    line endings on disk  : %d CRLF, %d bare LF"
            % (got["crlf_lines"], got["bare_lf_lines"])
        )
        lines.append("    git ls-files --eol    : %s" % eol_attr(rel))
        lines.append("    VERDICT (this OS)     : %s" % verdict)
        lines.append(
            "    VERDICT (LF checkout) : %s" % ("PASS" if claimed == blob else "FAIL")
        )
        lines.append("")
        hash_rows.append(
            {
                "assertion": label,
                "claimed": claimed,
                "file": rel,
                "manifest_path_field": recorded_path,
                "sha256_as_is": got["as_is"],
                "sha256_crlf_to_lf": got["crlf_to_lf"],
                "sha256_committed_blob": blob,
                "crlf_lines": got["crlf_lines"],
                "bare_lf_lines": got["bare_lf_lines"],
                "verdict_this_checkout": verdict,
                "verdict_lf_checkout": "PASS" if claimed == blob else "FAIL",
            }
        )
    record["hash_assertions"] = hash_rows
    fails = [r for r in hash_rows if r["verdict_this_checkout"] == "FAIL"]
    as_is_pass = [r for r in hash_rows if r["verdict_this_checkout"] == "PASS(as-is)"]
    norm_pass = [
        r for r in hash_rows if r["verdict_this_checkout"] == "PASS(after CRLF->LF)"
    ]
    lf_fail = [r for r in hash_rows if r["verdict_lf_checkout"] == "FAIL"]
    lines.append(
        "  totals on THIS checkout (Windows, w/crlf): %d verify as-is, %d only after "
        "CRLF->LF, %d neither way" % (len(as_is_pass), len(norm_pass), len(fails))
    )
    lines.append(
        "  totals against the COMMITTED blob bytes (an LF checkout): %d of %d fail"
        % (len(lf_fail), len(hash_rows))
    )
    lines.append(
        "  assertions that fail on this checkout but pass on an LF checkout: %d"
        % len([r for r in norm_pass if r["verdict_lf_checkout"] == "PASS"])
    )
    lines.append(
        "  assertions that pass on this checkout but fail on an LF checkout: %d"
        % len([r for r in as_is_pass if r["verdict_lf_checkout"] == "FAIL"])
    )
    record["totals"] = {
        "this_checkout_pass_as_is": len(as_is_pass),
        "this_checkout_pass_after_normalization": len(norm_pass),
        "this_checkout_fail": len(fails),
        "lf_checkout_fail": len(lf_fail),
    }

    # the .gitattributes tiers that decide whether bytes are pinned at all
    lines.append("")
    lines.append("  .gitattributes entries that pin bytes (-text), for context:")
    with io.open(os.path.join(REPO, ".gitattributes"), "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                lines.append("    %s" % line.rstrip())
    record["gitattributes"] = io.open(
        os.path.join(REPO, ".gitattributes"), "r", encoding="utf-8"
    ).read()

    # ---------------------------------------------------------------- (b) counts
    lines.append("")
    lines.append("(b) row counts claimed vs counted (csv.DictReader over the same file)")
    lines.append("")
    count_rows = []
    claims = [
        ("screened manifest summary.candidate_row_count",
         screened_manifest["summary"]["candidate_row_count"],
         "%s/candidate_pairs.csv" % SCREENED),
        ("screened manifest summary.new_pair_record_count",
         screened_manifest["summary"]["new_pair_record_count"],
         "%s/new_pair_records.csv" % SCREENED),
        ("screened manifest summary.new_pair_key_count",
         screened_manifest["summary"]["new_pair_key_count"],
         "%s/new_unique_pairs.csv" % SCREENED),
        ("screened manifest summary.candidate_row_count (vs ledger)",
         screened_manifest["summary"]["candidate_row_count"],
         "%s/screening_ledger.csv" % SCREENED),
        ("merged manifest summary.merged_row_count",
         merged_manifest["summary"]["merged_row_count"],
         "%s.csv" % MERGED),
        ("merged manifest summary.new_row_count (provenance sidecar)",
         merged_manifest["summary"]["new_row_count"],
         "%s.provenance.csv" % MERGED),
        ("merged manifest summary.baseline_row_count",
         merged_manifest["summary"]["baseline_row_count"],
         BASELINE_IN_REPO),
        ("pair_batch manifest input.rows",
         batch_manifest["input"]["rows"],
         "%s/new_unique_pairs.csv" % SCREENED),
    ]
    for label, claimed, rel in claims:
        counted = csv_data_rows(rel)
        ok = counted == claimed
        lines.append(
            "  %-58s claimed %-7d counted %-7d %s"
            % (label, claimed, counted, "OK" if ok else "MISMATCH")
        )
        count_rows.append(
            {"claim": label, "claimed": claimed, "counted": counted, "file": rel, "ok": ok}
        )
    record["count_assertions"] = count_rows

    summ = screened_manifest["summary"]
    total = (
        summ["new_pair_record_count"]
        + summ["already_present_count"]
        + summ["excluded_direction_count"]
        + summ["unresolved_identity_count"]
    )
    lines.append("")
    lines.append(
        "  arithmetic closure: new(%d) + already_present(%d) + excluded_direction(%d) + "
        "unresolved(%d) = %d vs candidate_row_count %d -> %s"
        % (
            summ["new_pair_record_count"],
            summ["already_present_count"],
            summ["excluded_direction_count"],
            summ["unresolved_identity_count"],
            total,
            summ["candidate_row_count"],
            "OK" if total == summ["candidate_row_count"] else "MISMATCH",
        )
    )
    record["arithmetic_closure_ok"] = total == summ["candidate_row_count"]

    # ---------------------------------------------------------------- (c) recompute
    lines.append("")
    lines.append("(c) screening summary recomputed with the teammate's own screen_pairs()")
    lines.append("    baseline  = %s" % BASELINE_IN_REPO)
    lines.append("    candidate = %s/candidate_pairs.csv" % SCREENED)
    baseline_rows = read_csv(os.path.join(REPO, BASELINE_IN_REPO))
    candidate_rows = read_csv(os.path.join(REPO, "%s/candidate_pairs.csv" % SCREENED))
    recomputed = screen_pairs(baseline_rows, candidate_rows)["summary"]
    lines.append("")
    lines.append("    %-32s %-10s %-10s %s" % ("field", "manifest", "recomputed", "verdict"))
    repro = {}
    for field in sorted(summ):
        claimed = summ[field]
        got = recomputed.get(field)
        ok = claimed == got
        repro[field] = {"manifest": claimed, "recomputed": got, "ok": ok}
        lines.append(
            "    %-32s %-10s %-10s %s"
            % (field, claimed, got, "OK" if ok else "MISMATCH")
        )
    record["recomputed_summary"] = repro

    # ledger status tallies, from the file rather than the manifest
    ledger = read_csv(os.path.join(REPO, "%s/screening_ledger.csv" % SCREENED))
    tally = {}
    for row in ledger:
        tally[row["screen_status"]] = tally.get(row["screen_status"], 0) + 1
    lines.append("")
    lines.append("    screening_ledger.csv screen_status tally (counted from the file):")
    for status in sorted(tally):
        lines.append("      %-24s %d" % (status, tally[status]))
    record["ledger_status_tally"] = tally
    ledger_matches = (
        tally.get("new_pair", 0) == summ["new_pair_record_count"]
        and tally.get("already_present", 0) == summ["already_present_count"]
        and tally.get("excluded_direction", 0) == summ["excluded_direction_count"]
        and tally.get("unresolved_identity", 0) == summ["unresolved_identity_count"]
    )
    lines.append("      ledger tally agrees with the manifest summary: %s" % ledger_matches)
    record["ledger_tally_matches_manifest"] = ledger_matches

    text = "\n".join(lines) + "\n"
    with io.open(os.path.join(OUT_DIR, "L04_manifests.txt"), "w", encoding="utf-8") as handle:
        handle.write(text)
    with io.open(os.path.join(OUT_DIR, "L04_manifests.json"), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
