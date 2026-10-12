"""Explicit full-source acceptance, separate from ordinary offline unit tests.

Requires the pinned source files and built index. --live-1e optionally performs
one GLDC dossier (four component tools), with network timing kept separate.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import tempfile
from time import perf_counter

from .build_index import _records, as_mapping, read_sources
from .common import canonical_bytes, sha256, strict_json, utc_now, write_new
from .gem import GemLookup, _decode_index, load_index
from .source_fixture import source_fixture

CASES = {
    "glycine": {"chebi": "CHEBI:15428", "genes": {"GLDC", "GCSH", "SHMT1", "SHMT2", "GNMT"}},
    "isoleucine": {"chebi": "CHEBI:17191", "genes": {"BCAT1", "BCAT2"}},
    "citrate": {"chebi": "CHEBI:30769", "genes": {"CS", "ACLY", "SLC25A1", "SLC13A5"}},
    "TMAO": {"chebi": "CHEBI:15724", "genes": {"FMO3"}},
    "ATP": {"chebi": "CHEBI:15422", "genes": set()},
}
REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "MVP3/tests/fixtures/gem/source_excerpt.json"


def code_identity():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()
    try:
        return {"commit": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
                "working_tree_status": git("status", "--porcelain")}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "note": "Git identity unavailable; use module file hashes"}


def run_acceptance(source_dir, index_path, output_root, live_1e=False):
    Path(output_root).mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="gem-acceptance-", dir=output_root))
    checks, results, batch = [], {}, None

    def check(name, passed, detail=None):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    code_files = sorted((REPO / "MVP3/src").glob("*.py"))
    report = {"started_at": utc_now(), "code": code_identity(), "checks": checks,
              "code_file_sha256": {str(path.relative_to(REPO)): sha256(path.read_bytes()) for path in code_files},
              "live_1e_requested": live_1e, "artifact_directory": str(directory)}
    try:
        model, annotations, provenance = read_sources(source_dir)
        index, manifest = load_index(index_path)
        report["index_manifest"] = manifest
        check("Index is a full pinned-source build, not a fixture", index["provenance"] == provenance)
        for section in ("metabolites", "genes", "reactions"):
            check(f"Full {section} coverage equals source IDs", set(index[section]) == set(_records(model[section])))
        source_reactions = _records(model["reactions"])
        # Independent cross-check of every raw GPR, participants and bounds. Regex
        # extracts leaves only for this check; production keeps Boolean ASTs.
        differences = []
        for rid, row in source_reactions.items():
            actual = index["reactions"][rid]
            raw_gpr = row.get("gene_reaction_rule", "")
            source_genes = set(re.findall(r"ENSG[0-9]+", raw_gpr))
            if (actual["gpr_raw"] != raw_gpr or set(actual["gene_members"]) != source_genes
                    or {p["species_id"]: p["coefficient"] for p in actual["participants"]} != as_mapping(row["metabolites"])
                    or actual["lower_bound"] != row.get("lower_bound") or actual["upper_bound"] != row.get("upper_bound")):
                differences.append(rid)
        check("Every reaction matches source GPR leaves, raw rule, stoichiometry and bounds", not differences, differences[:20])
        fixture = strict_json(FIXTURE.read_bytes())
        rebuilt_fixture = source_fixture(source_dir, fixture["provenance"]["selected_reaction_ids"])
        # YAML !!omap uses Python tuples; JSON preserves the same structure as
        # arrays. Compare their exact canonical serialization, not Python container types.
        check("Checked-in fixture is exactly reproducible from pinned source records",
              canonical_bytes(fixture) == canonical_bytes(rebuilt_fixture))
        _decode_index.cache_clear()
        report["timing_note"] = "First example includes cold JSON decoding; OS filesystem cache is not purged. Source verification/preparation and downstream network calls are separate."
        lookup = GemLookup(index_path, max_reactions=10000, max_candidates=10000)
        for name, case in CASES.items():
            envelope = lookup.query(case["chebi"])
            results[name] = envelope
            data = envelope["data"]
            check(f"{name}: full-model exact annotation lookup", envelope["status"] == "ok" and data.get("dataset_kind") == "full_model")
            symbols = {row["symbol"] for row in data["candidates"]}
            check(f"{name}: source-backed expected example genes", case["genes"].issubset(symbols), sorted(symbols - {None}))
            check(f"{name}: measured local lookup under 3 seconds", data["local_lookup_ms"] < 3000, data["local_lookup_ms"])
            source_species = {identifier for identifier, row in annotations["metabolites"].items()
                              if case["chebi"] in (row["values"].get("metChEBIID") or "").split(";")}
            actual_species = {row["id"] for row in data["mapping"]["species"]}
            check(f"{name}: all annotated compartments returned", actual_species == source_species, sorted(actual_species))
        atp = results["ATP"]["data"]
        check("ATP suppression is explicit, not empty or zero source counts",
              atp["policy_suppressed"] and not atp["candidates"] and atp["total_reactions"] > 0 and atp["total_candidates"] > 0)
        glycine = results["glycine"]["data"]
        gldc = next(row for row in glycine["candidates"] if row["symbol"] == "GLDC")
        check("GLDC source AND context is not lost", gldc["complex_member"] and "MAR08433" in gldc["reaction_ids"])
        check("Atlas CPS1 is not injected into direct glycine GPR candidates", "CPS1" not in {row["symbol"] for row in glycine["candidates"]})
        unknown = lookup.query("CHEBI:999999999")
        missing = GemLookup(directory / "missing-index.json").query("CHEBI:15428")
        results.update(unknown=unknown, missing_model=missing)
        check("Unknown ChEBI is empty; missing index is error", unknown["status"] == "empty" and missing["status"] == "error")
        batch = lookup.map_many(["CHEBI:15428", "CHEBI_15428", "CHEBI:17191", "CHEBI:999999999", "invalid"])
        write_new(directory / "batch.json", canonical_bytes(batch))
        check("Batch deduplicates identifiers and preserves every diagnostic", batch["input_count"] == 5 and
              batch["unique_valid_chebi_count"] == 3 and batch["mapped"] == 2 and batch["unmapped"] == 1 and batch["errors"] == 1)
        if live_1e:
            from tools._evidence import JsonlRecorder, recording
            from tools.dossier import get_gene_dossier
            before = deepcopy(results["glycine"])
            started = perf_counter()
            with recording(JsonlRecorder(directory / "1e.ledger.jsonl")):
                dossier = get_gene_dossier(gldc["symbol"], "MONDO_0005010")
            report["live_1e_seconds"] = perf_counter() - started
            results["GLDC_live_dossier"] = dossier
            check("Live GLDC four-tool 1E dossier returned without source errors", dossier["status"] in ("ok", "empty"), dossier["data"].get("component_statuses"))
            check("1E result did not modify the biochemical source envelope", results["glycine"] == before)
            lines = [strict_json(line) for line in (directory / "1e.ledger.jsonl").read_bytes().splitlines()]
            check("Live 1E ledger round-trips four components plus summary", len(lines) == 5 and lines[-1] == dossier)
        report["limits"] = ["This verifies Workstream D, not shared-repo Slack/agent Gate 2.",
                            "No final expanded MVP2 index was available; batch coverage here is an explicit small example.",
                            "Lookup timing excludes downstream network calls. Expected gene sets are source-backed examples, not completeness/ranking promises."]
    except Exception as exc:
        check("Acceptance execution completed", False, f"{type(exc).__name__}: {exc}")
    raw = canonical_bytes(results)
    write_new(directory / "results.json", raw)
    recorded = [value for key, value in results.items() if key != "GLDC_live_dossier"]
    if batch:
        recorded.extend(row["envelope"] for row in batch["records"] if not row["reused"])
    ledger_path = directory / "gem.ledger.jsonl"
    write_new(ledger_path, b"".join(canonical_bytes(value) for value in recorded))
    check("GEM ledger round-trips every executed lookup including batch errors",
          [strict_json(line) for line in ledger_path.read_bytes().splitlines()] == recorded)
    report.update(passed=bool(checks) and all(row["passed"] for row in checks), finished_at=utc_now())
    report["results_sha256"] = sha256(raw)
    write_new(directory / "summary.json", canonical_bytes(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--live-1e", action="store_true")
    args = parser.parse_args()
    report = run_acceptance(args.source_dir, args.index, args.output_root, args.live_1e)
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]),
                      "failures": [row for row in report["checks"] if not row["passed"]],
                      "artifacts": report["artifact_directory"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
