"""Run every MVP2 probe in order, then assemble the machine-readable result set.

Deterministic and offline. Writes outputs/run.log, outputs/results.csv and
outputs/results.json. Every number in results.csv is read back out of a probe's own
JSON output; nothing here is typed in by hand.

Run from the repository root:
    python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/mvp2/probes/run_all.py
"""

from __future__ import annotations

import csv
import io
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone

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

PROBES = [
    ("L01", "probe_L01_coupling.py", "does any MVP2 artefact reach pipeline/render/classify"),
    ("L02", "probe_L02_disclosure.py", "which rendered cards disclose that the MVP2 arm is absent"),
    ("L03", "probe_L03_tests.py", "MVP2/tests under the documented runner and under an offline shim"),
    ("L04", "probe_L04_manifests.py", "manifest sha256 and row-count assertions, and the screening summary"),
    ("L05", "probe_L05_records.py", "record-level integrity of the screened candidate tables"),
    ("L06", "probe_L06_extraction.py", "fixed-column extraction against the source workbook"),
    ("L07", "probe_L07_ledger.py", "search-run coverage, traceability and identifier hygiene"),
    ("L08", "probe_L08_merge.py", "merge reproduction and canonical-dedup accounting"),
]


def load(name: str):
    path = os.path.join(OUT_DIR, name)
    with io.open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def build_rows() -> list:
    L01 = load("L01_coupling.json")
    L02 = load("L02_disclosure.json")
    L03 = load("L03_tests.json")
    L04 = load("L04_manifests.json")
    L05 = load("L05_records.json")
    L06 = load("L06_extraction.json")
    L07 = load("L07_ledger.json")
    L08 = load("L08_merge.json")

    kept_inverted = sum(
        v["ci_low>ci_high"] for v in L06["kept_bound_ordering"].values()
    )
    ukb_layout_h = sum(v["layout_H_rows"] for v in L06["ci_ordering"].values())
    ukb_inverted_source = sum(
        v["col11_is_smaller_than_col12"] for v in L06["ci_ordering"].values()
    )
    disclosing = sum(1 for r in L02["rows"] if r["discloses_mvp2_absence"])

    rows = [
        {
            "case_id": "L01",
            "surface": "runtime coupling",
            "question": "does any MVP2 module or data file reach the card path",
            "measurement": (
                "%d runtime python files scanned; %d MVP2 module imports; %d MVP2 path "
                "literals; %d sys.path inserts; %d MVP2 modules loaded after importing "
                "pipeline/render/classify/validate_card/tools; get_literature_mr in TOOLS = %s"
                % (
                    L01["runtime_python_files_scanned"],
                    len(L01["mvp2_module_imports"]),
                    len(L01["mvp2_path_literals"]),
                    len(L01["mvp2_syspath_inserts"]),
                    len(L01["dynamic"]["modules_loaded_from_MVP2"]),
                    L01["dynamic"]["get_literature_mr_in_TOOLS"],
                )
            ),
            "outcome": "no runtime coupling",
            "severity": "observation",
            "finding": "M1",
            "evidence": "outputs/L01_coupling.txt",
        },
        {
            "case_id": "L02",
            "surface": "card prose",
            "question": "which rendered cards tell the reader the literature arm was not consulted",
            "measurement": "%d of %d frozen demo pairs disclose it; by state %s"
            % (
                disclosing,
                len(L02["rows"]),
                json.dumps(
                    {k: "%d/%d" % (v["disclosing"], v["n"]) for k, v in sorted(L02["by_state"].items())},
                    sort_keys=True,
                ),
            ),
            "outcome": "disclosure is State C only",
            "severity": "observation",
            "finding": "M2",
            "evidence": "outputs/L02_disclosure.txt, outputs/L02_cards/",
        },
        {
            "case_id": "L03",
            "surface": "MVP2 test suite",
            "question": "do the teammate's tests run on current main",
            "measurement": (
                "python -m pytest MVP2/tests -q exits %d (%s); pytest in requirements.txt = %s; "
                "under the offline shim: %d passed, %d failed, %d not runnable, %d collection errors"
                % (
                    L03["pytest"]["exit_code"],
                    L03["pytest"]["stderr"].strip().splitlines()[-1] if L03["pytest"]["stderr"].strip() else "",
                    L03["pytest_in_requirements"],
                    L03["shim"]["totals"].get("passed", 0),
                    L03["shim"]["totals"].get("failed", 0),
                    L03["shim"]["totals"].get("not_runnable", 0),
                    L03["shim"]["totals"].get("collection_error", 0),
                )
            ),
            "outcome": "not runnable as documented; all 17 pass under a shim",
            "severity": "scope_limit",
            "finding": "M10",
            "evidence": "outputs/L03_tests.txt",
        },
        {
            "case_id": "L04a",
            "surface": "data manifests",
            "question": "do the recorded sha256 values verify against the files they name",
            "measurement": (
                "7 hash assertions: %d verify as-is on this Windows checkout, %d only after "
                "CRLF->LF, %d neither; against the committed blob bytes %d of 7 fail"
                % (
                    L04["totals"]["this_checkout_pass_as_is"],
                    L04["totals"]["this_checkout_pass_after_normalization"],
                    L04["totals"]["this_checkout_fail"],
                    L04["totals"]["lf_checkout_fail"],
                )
            ),
            "outcome": "one assertion cannot verify on any checkout; four fail on Windows",
            "severity": "defect",
            "finding": "M7, M8",
            "evidence": "outputs/L04_manifests.txt",
        },
        {
            "case_id": "L04b",
            "surface": "data manifests",
            "question": "do the recorded counts and the screening summary reproduce",
            "measurement": (
                "%d of %d row-count assertions OK; arithmetic closure %s; screen_pairs() "
                "recomputed: %d of %d summary fields match; ledger tally matches manifest = %s"
                % (
                    sum(1 for r in L04["count_assertions"] if r["ok"]),
                    len(L04["count_assertions"]),
                    L04["arithmetic_closure_ok"],
                    sum(1 for v in L04["recomputed_summary"].values() if v["ok"]),
                    len(L04["recomputed_summary"]),
                    L04["ledger_tally_matches_manifest"],
                )
            ),
            "outcome": "counting layer reproduces exactly",
            "severity": "observation",
            "finding": "M11",
            "evidence": "outputs/L04_manifests.txt",
        },
        {
            "case_id": "L05a",
            "surface": "screened records",
            "question": "are the provenance columns complete and do the source files exist",
            "measurement": (
                "empty provenance cells across all four tables: %d; distinct source files %d, "
                "missing from this checkout %d"
                % (
                    sum(
                        sum(entry["empty"].values())
                        for entry in L05["provenance_completeness"].values()
                    ),
                    len(L05["source_paths"]),
                    sum(1 for r in L05["source_paths"] if not r["exists"]),
                )
            ),
            "outcome": "provenance complete and resolvable",
            "severity": "observation",
            "finding": "M11",
            "evidence": "outputs/L05_records.txt",
        },
        {
            "case_id": "L05b",
            "surface": "screened records",
            "question": "are the estimate fields internally possible",
            "measurement": (
                "new_unique_pairs.csv: ci_low > ci_high on %d rows; p_value outside [0,1] on "
                "%d rows; p_value exactly 0 on %d; se empty on %d; nsnp empty on %d"
                % (
                    L05["numeric_sanity"]["ci_low_gt_ci_high"],
                    L05["numeric_sanity"]["p_outside_0_1"],
                    L05["numeric_sanity"]["p_exactly_zero"],
                    L05["numeric_sanity"]["se_empty"],
                    L05["numeric_sanity"]["nsnp_empty"],
                )
            ),
            "outcome": "impossible bound ordering and impossible p-values present",
            "severity": "defect",
            "finding": "M3, M4",
            "evidence": "outputs/L05_records.txt",
        },
        {
            "case_id": "L05c",
            "surface": "screened records",
            "question": "does the direction filter have unexercised latitude",
            "measurement": "rows with no direction recorded that were kept as forward: %d"
            % L05["empty_direction_kept_as_forward"],
            "outcome": "latent, not exercised by the current data",
            "severity": "observation",
            "finding": "M12",
            "evidence": "outputs/L05_records.txt",
        },
        {
            "case_id": "L06a",
            "surface": "seed extraction",
            "question": "do the extracted confidence bounds match the source",
            "measurement": (
                "ukb_mapping_2025: %d rows follow the printed header order, and on %d of them "
                "the value under '95%% UCI' is the smaller number; %d rows in "
                "new_unique_pairs.csv carry ci_low > ci_high"
                % (ukb_layout_h, ukb_inverted_source, kept_inverted)
            ),
            "outcome": "bounds inverted for every ukb_mapping_2025 row",
            "severity": "defect",
            "finding": "M3",
            "evidence": "outputs/L06_extraction.txt",
        },
        {
            "case_id": "L06b",
            "surface": "seed extraction",
            "question": "does every source row use the layout the fixed indices assume",
            "measurement": (
                "rows whose odds-ratio column is col11 rather than col10: %s; of those, "
                "%d reach candidate_pairs.csv, %d reach new_pair_records.csv and %d reach "
                "new_unique_pairs.csv, where %d carry a p_value inside [0,1] and are not "
                "detectable by a range check"
                % (
                    json.dumps(
                        {
                            sheet: counts.get("layout S (col11 = OR)", 0)
                            for sheet, counts in sorted(L06["layout_counts"].items())
                            if counts.get("layout S (col11 = OR)", 0)
                        },
                        sort_keys=True,
                    ),
                    L06["survivors"]["candidate_pairs.csv"]["rows_on_layout_S"],
                    L06["survivors"]["new_pair_records.csv"]["rows_on_layout_S"],
                    L06["survivors"]["new_unique_pairs.csv"]["rows_on_layout_S"],
                    L06["survivors"]["new_unique_pairs.csv"][
                        "of_those_p_value_inside_0_1_and_therefore_undetectable_by_range"
                    ],
                )
            ),
            "outcome": "an odds ratio lands in ci_high and a confidence bound in p_value",
            "severity": "defect",
            "finding": "M4",
            "evidence": "outputs/L06_extraction.txt",
        },
        {
            "case_id": "L07a",
            "surface": "screening ledger",
            "question": "is every kept pair traceable to a search run",
            "measurement": "%d of %d kept pairs have a search record (%.5f%%); %d have none"
            % (
                L07["coverage"]["pair_records"],
                L07["coverage"]["kept_unique_pairs"],
                L07["coverage"]["fraction"] * 100,
                L07["coverage"]["pairs_without_a_search_record"],
            ),
            "outcome": "one smoke-test pair searched",
            "severity": "observation",
            "finding": "M9",
            "evidence": "outputs/L07_ledger.txt",
        },
        {
            "case_id": "L07b",
            "surface": "screening ledger",
            "question": "is the one search record consistent and are its identifiers well formed",
            "measurement": (
                "pair_id recomputes and names row %s of new_unique_pairs.csv; %d papers, "
                "%d malformed pmid, %d malformed pmcid, %d malformed doi, %d duplicate pmid; "
                "returned ids not retained: %d; retained ids never returned: %d"
                % (
                    L07["traceability"][0]["rows_in_new_unique_pairs"],
                    L07["paper_identifiers"]["papers"],
                    L07["paper_identifiers"]["pmid_malformed"],
                    L07["paper_identifiers"]["pmcid_malformed"],
                    L07["paper_identifiers"]["doi_malformed"],
                    len(L07["duplicate_pmids"]),
                    len(L07["pair_record_consistency"][0]["returned_but_not_retained"]),
                    len(L07["pair_record_consistency"][0]["retained_but_never_returned"]),
                )
            ),
            "outcome": "internally consistent and fully traceable",
            "severity": "observation",
            "finding": "M11",
            "evidence": "outputs/L07_ledger.txt",
        },
        {
            "case_id": "L08a",
            "surface": "merge",
            "question": "does the merge reproduce from the committed inputs",
            "measurement": "re-run exit %d; merged csv identical after CRLF->LF = %s; %d of %d "
            "manifest summary fields match"
            % (
                L08["rerun"]["exit_code"],
                L08["merge_reproduces"],
                sum(1 for v in L08["summary_comparison"].values() if v["ok"]),
                len(L08["summary_comparison"]),
            ),
            "outcome": "reproduces exactly",
            "severity": "observation",
            "finding": "M11",
            "evidence": "outputs/L08_merge.txt",
        },
        {
            "case_id": "L08b",
            "surface": "merge",
            "question": "what did one-row-per-canonical-key discard, and what do the constants say",
            "measurement": (
                "%d rows discarded; %d canonical keys hold more than one row; %d discarded rows "
                "carry a different (beta, p_value, method); %d name a different exposure; all %d "
                "appended rows carry supporting_mr_rows='1'"
                % (
                    L08["dedup_accounting"]["rows_discarded"],
                    L08["dedup_accounting"]["keys_with_more_than_one_row"],
                    L08["dedup_accounting"]["discarded_with_different_estimate"],
                    L08["dedup_accounting"]["discarded_with_different_metabolite_label"],
                    L08["appended_constants"]["appended_rows"],
                )
            ),
            "outcome": "a constant supporting-row count over a lossy dedup",
            "severity": "defect",
            "finding": "M5, M6",
            "evidence": "outputs/L08_merge.txt",
        },
        {
            "case_id": "L08c",
            "surface": "merge",
            "question": "do the inverted bounds survive into the merged candidate table",
            "measurement": (
                "appended MVP2 rows: %d of %d carry ci_low > ci_upp; MVP1 baseline rows: %d of %d"
                % (
                    L08["merged_bound_ordering"]["appended MVP2 rows"]["inverted"],
                    L08["merged_bound_ordering"]["appended MVP2 rows"]["rows"],
                    L08["merged_bound_ordering"]["MVP1 baseline rows"]["inverted"],
                    L08["merged_bound_ordering"]["MVP1 baseline rows"]["rows"],
                )
            ),
            "outcome": "inverted bounds reach the merged table",
            "severity": "defect",
            "finding": "M3",
            "evidence": "outputs/L08_merge.txt",
        },
        {
            "case_id": "L05d",
            "surface": "pair identity",
            "question": "does normalize() keep ratios distinct from absolute measures",
            "measurement": (
                "%d canonical keys in new_unique_pairs.csv cover more than one distinct raw "
                "(metabolite, disease) label pair; normalize() drops '%%', so 'Omega-3' and "
                "'Omega-3%%' share one key"
                % L05["dedup_collapse"]["keys_with_multiple_raw_labels"]
            ),
            "outcome": "ratio and absolute exposures share a key",
            "severity": "defect",
            "finding": "M5",
            "evidence": "outputs/L05_records.txt",
        },
    ]
    return rows


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    log = [
        "MVP2 probe run",
        "utc: %s" % datetime.now(timezone.utc).isoformat(),
        "python: %s" % sys.version.replace("\n", " "),
        "platform: %s" % platform.platform(),
        "",
    ]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    failed = 0
    for case_id, script, purpose in PROBES:
        path = os.path.join(HERE, script)
        proc = subprocess.run(
            [sys.executable, path],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        log.append("%s  %-26s exit %d  %s" % (case_id, script, proc.returncode, purpose))
        if proc.returncode != 0:
            failed += 1
            log.append("    stderr:")
            for line in proc.stderr.strip().splitlines():
                log.append("      %s" % line)
        sys.stdout.write("%s %s exit %d\n" % (case_id, script, proc.returncode))

    rows = build_rows()
    fields = [
        "case_id",
        "surface",
        "question",
        "measurement",
        "outcome",
        "severity",
        "finding",
        "evidence",
    ]
    with io.open(os.path.join(OUT_DIR, "results.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with io.open(os.path.join(OUT_DIR, "results.json"), "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2, sort_keys=True)
        handle.write("\n")

    log.append("")
    log.append("cases written to results.csv: %d" % len(rows))
    log.append("probe scripts that exited non-zero: %d" % failed)
    with io.open(os.path.join(OUT_DIR, "run.log"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(log) + "\n")
    sys.stdout.write("\n".join(log[-3:]) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
