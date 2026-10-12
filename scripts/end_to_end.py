"""1A(sample) -> 1B -> 1C -> classify, run as one chain over the six demo pairs.

Not a tool and not the agent. This is the wiring check: it takes 1A's frozen output
from data/1a_sample.json, calls the four retrieval tools that exist today, writes every
envelope to cards/{stem}.ledger.jsonl through `ledger`, and hands the envelopes to
`classify.classify_state`. It adds no retrieval code of its own and it never decides a
state - the state comes back from classify.py, which is a pure function.

    python scripts/end_to_end.py --skip-catalog
    python scripts/end_to_end.py --pair urate --pair glycine
    python scripts/end_to_end.py                      # includes GWAS Catalog: slow

WHAT RUNS, AND WHAT DOES NOT
  get_mr_result          1B   EpiGraphDB MR-EVE, no key            -> classify mr_env
  get_mqtl_instruments   1C   OpenGWAS tophits, needs the JWT      -> classify instr_env
  find_outcome_datasets  1C   OpenGWAS gwasinfo cache, no request  -> classify outcome_env
  get_gwas_catalog       1C   EBI GWAS Catalog, no key, ~100 s     -> ledger only
  get_literature_mr      MVP2 not built, so lit_env is always None

The GWAS Catalog envelope is recorded in the ledger but is NOT passed to
classify_state: the classifier has four slots and none of them is "associations".
That is deliberate - a GWAS Catalog association is not an MR estimate and not an
instrument count, so letting it move the state would be exactly the overclaim this
project refuses. It is retrieved here because 1D consumes its mapped genes.

CONSEQUENCE FOR `ledger_keys`. classify_state's `ledger_keys` names every envelope
HANDED TO IT, not every tool that ran, so with the catalog on it lists three tools
while the ledger holds four lines. `--skip-catalog` makes the two agree exactly.

Credits: one --skip-catalog run of all six pairs sends 1 to 2 EpiGraphDB queries and
up to `--max-datasets` OpenGWAS tophits POSTs per pair (26 in the measured run).
find_outcome_datasets reads the local gwasinfo cache and sends nothing.

WHAT THE SIX PAIRS ACTUALLY PRODUCED (measured 2026-09-10, defaults, catalog skipped)

  urate|gout                      A   22 MR-EVE rows, ieu-a-789 FE IVW b=1.3665
  creatinine|chronic kidney dis.  A   3 rows; two of them are the SAME UKB measurement
                                      on two scales (ukb-d-30700_irnt b=1.218 and
                                      ukb-d-30700_raw b=0.0878) - 1B's scale caveat
                                      fires, and the card must print the dataset
                                      beside every number
  citrate|ischemic stroke         A   6 rows, four of them null (p = 0.36 to 0.90). A
                                      is "an estimate was retrieved", never "an effect
                                      exists" - this is the pair that proves it
  glycine|coronary artery disease B   met-d-Gly, 49 clumped hits, min F 26.4
  isoleucine|type 2 diabetes      B   met-d-Ile, 10 clumped hits; 24 T2D outcome
                                      datasets capped to 3
  trimethylamine N-oxide|CAD      C   no exposure in either release; the CAD outcome
                                      side still matched, so C here is about TMAO only

Two things worth knowing before a demo. get_gwas_catalog succeeds for gout (1,420
associations, 72 mapped genes led by ABCG2, the urate transporter) but hits its 120 s
deadline for coronary artery disorder at 3.8 MB still arriving, and returns an error
envelope. The run did not stall and the state did not move, because the Catalog is not
a classifier slot. And urate's 6 queried exposures include three (ieu-a-786/787/788,
n=42,741) that return zero clumped hits - "0 hits" is normal for a small dataset and
is not a statement about urate.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import classify
import ledger
from tools import _common
from tools.epigraphdb import get_mr_result
from tools.gwascat import get_gwas_catalog
from tools.opengwas import find_outcome_datasets, get_mqtl_instruments

SAMPLE_PATH = REPO_ROOT / "data" / "1a_sample.json"

MAX_DATASETS = 6
TOP_N = 3

# The order the tools are called in, which is the order their lines appear in a ledger.
TOOL_ORDER = (
    "get_mr_result",
    "get_mqtl_instruments",
    "find_outcome_datasets",
    "get_gwas_catalog",
)

CLASSIFIER_SLOTS = (
    ("mr_env",      "get_mr_result"),
    ("instr_env",   "get_mqtl_instruments"),
    ("outcome_env", "find_outcome_datasets"),
)

_RULE = "=" * 100


def load_sample(path: Path = SAMPLE_PATH) -> dict:
    """1A's frozen output: {"metabolite|disease": {"metabolite": {...}, "disease": {...}}}."""
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def stem_for(key: str) -> str:
    """The ledger stem of one pair: "glycine|coronary artery disease" ->
    "glycine_coronary-artery-disease", so the file is one readable name per pair."""
    parts = [_common.normalize(part).replace(" ", "-") for part in str(key).split("|")]
    return "_".join(part for part in parts if part) or "pair"


def select_pairs(sample: dict, wanted: list) -> list:
    """The (key, entry) pairs to run. No --pair means all six; each --pair value is
    matched as a casefolded substring of the key, so "urate" and "urate|gout" both work."""
    keys = list(sample)
    if not wanted:
        return [(key, sample[key]) for key in keys]

    chosen = []
    for term in wanted:
        needle = _common.normalize(term)
        hits = [key for key in keys if needle in _common.normalize(key)]
        if not hits:
            print(f"[end_to_end] no pair in {SAMPLE_PATH.name} matches {term!r}", file=sys.stderr)
        for key in hits:
            if key not in [existing for existing, _ in chosen]:
                chosen.append((key, sample[key]))
    return chosen


def run_pair(
    key:          str,
    entry:        dict,
    skip_catalog: bool = False,
    max_datasets: int = MAX_DATASETS,
    top_n:        int = TOP_N,
) -> dict:
    """Run the four tools for one pair, record them, and classify. Returns the envelopes,
    the classifier verdict and the ledger lines that were written, for a caller to print
    or assert on. Never raises: every tool already turns its own failures into an error
    envelope, and `ledger.stop()` runs even if one of them somehow does not."""
    metabolite = entry.get("metabolite") or {}
    disease = entry.get("disease") or {}
    stem = stem_for(key)

    ledger.start(stem)
    try:
        mr_env = get_mr_result(
            metabolite.get("synonyms") or [],
            disease.get("synonyms") or [],
        )
        instr_env = get_mqtl_instruments(
            metabolite.get("synonyms") or [],
            max_datasets,
        )
        outcome_env = find_outcome_datasets(
            disease.get("synonyms") or [],
            top_n,
        )
        catalog_env = None
        if not skip_catalog:
            catalog_env = get_gwas_catalog(
                trait_label = disease.get("label") or disease.get("input") or "",
                ontology_id = disease.get("id") or "",
            )
    finally:
        ledger.stop()

    verdict = classify.classify_state(
        mr_env      = mr_env,
        lit_env     = None,
        instr_env   = instr_env,
        outcome_env = outcome_env,
    )

    return {
        "key":          key,
        "stem":         stem,
        "state":        verdict["state"],
        "verdict":      verdict,
        "mr_env":       mr_env,
        "instr_env":    instr_env,
        "outcome_env":  outcome_env,
        "catalog_env":  catalog_env,
        "ledger_lines": ledger.load(stem),
    }


def _status(env) -> str:
    return env["status"] if isinstance(env, dict) else "skipped"


def _detail(name: str, env) -> str:
    """One line of evidence per tool, in that tool's own numbers."""
    if not isinstance(env, dict):
        return "not run"
    data = env.get("data") or {}

    if name == "get_mr_result":
        return (f"n_estimates={data.get('n_estimates')}  "
                f"exposure_matches={len(data.get('exposure_matches') or [])}  "
                f"outcome_matches={len(data.get('outcome_matches') or [])}  "
                f"queries={len(data.get('queries') or [])}")

    if name == "get_mqtl_instruments":
        exposures = data.get("exposures") or []
        with_hits = [row for row in exposures if (row.get("gws_hits") or 0) > 0]
        return (f"matched={data.get('matched_datasets')}  queried={len(exposures)}  "
                f"with hits={len(with_hits)}  "
                f"best gws_hits={max((row.get('gws_hits') or 0) for row in exposures) if exposures else 0}")

    if name == "find_outcome_datasets":
        return (f"n_datasets={data.get('n_datasets')} of "
                f"{data.get('n_matched_before_cap')} matched")

    if name == "get_gwas_catalog":
        return (f"efo={data.get('efo_short_form')}  "
                f"kept {data.get('n_associations_kept')} of "
                f"{data.get('n_associations_total')} association(s)  "
                f"mapped_genes={len(data.get('mapped_genes') or [])}")

    return ""


def report_pair(result: dict) -> None:
    print()
    print(_RULE)
    print(f"{result['key']}   ->   STATE {result['state']}")
    print(_RULE)

    lines = result["ledger_lines"]
    print(f"ledger : cards/{result['stem']}.ledger.jsonl  "
          f"({len(lines)} line(s): {', '.join(line.get('tool', '?') for line in lines)})")
    print("reason :")
    for line in textwrap.wrap(
        result["verdict"]["reason"],
        width             = 94,
        initial_indent    = "  ",
        subsequent_indent = "  ",
        break_long_words  = False,
        break_on_hyphens  = False,
    ):
        print(line)

    print("\ntools")
    envelopes = {
        "get_mr_result":         result["mr_env"],
        "get_mqtl_instruments":  result["instr_env"],
        "find_outcome_datasets": result["outcome_env"],
        "get_gwas_catalog":      result["catalog_env"],
    }
    for name in TOOL_ORDER:
        env = envelopes[name]
        print(f"  {name:<24} {_status(env):<8} {_detail(name, env)}")

    exposures = ((result["instr_env"].get("data") or {}).get("exposures") or [])
    print(f"\nexposures ({len(exposures)} queried; gws_hits = LD-clumped loci at p < 5e-8)")
    if not exposures:
        print("  none")
    for row in exposures:
        f_range = "F n/a"
        if row.get("min_f") is not None:
            f_range = f"F {row['min_f']:.1f}..{row['max_f']:.1f}"
        print(f"  {str(row.get('id')):<20} {str(row.get('trait'))[:22]:<22} "
              f"n={str(row.get('sample_size')):<9} hits={str(row.get('gws_hits')):<5} "
              f"weak={str(row.get('weak_instruments')):<4} {f_range:<22} "
              f"{str(row.get('population'))}")

    datasets = ((result["outcome_env"].get("data") or {}).get("datasets") or [])
    print(f"\noutcome datasets ({len(datasets)} returned)")
    if not datasets:
        print("  none")
    for row in datasets:
        print(f"  {str(row.get('id')):<20} {str(row.get('trait'))[:22]:<22} "
              f"n={str(row.get('sample_size')):<9} ncase={str(row.get('ncase')):<8} "
              f"{str(row.get('population'))}")

    failed = result["verdict"]["failed_tools"]
    if failed:
        print(f"\nfailed tools (seen by the classifier) : {', '.join(failed)}")

    # Every non-ok tool explains itself here, error included. get_gwas_catalog is not a
    # classifier slot, so its failure never reaches `failed_tools` - and a tool that
    # returned nothing without saying why is the failure mode this project refuses.
    for name in TOOL_ORDER:
        status = _status(envelopes[name])
        if status not in ("empty", "error"):
            continue
        print(f"\nwhy {name} is {status}")
        for caveat in (envelopes[name].get("caveats") or [])[-2:]:
            for line in textwrap.wrap(
                caveat,
                width             = 94,
                initial_indent    = "  ",
                subsequent_indent = "  ",
                break_long_words  = False,
                break_on_hyphens  = False,
            ):
                print(line)


def summary_table(results: list) -> None:
    print()
    print(_RULE)
    print("SUMMARY")
    print(_RULE)
    header = (f"{'pair':<46} {'state':<6} {'mr':<7} {'instr':<7} {'outc':<7} {'cat':<8} "
              f"{'n_est':>6} {'hits':>6} {'n_out':>6}")
    print(header)
    print("-" * len(header))

    for result in results:
        mr_data = result["mr_env"].get("data") or {}
        exposures = (result["instr_env"].get("data") or {}).get("exposures") or []
        datasets = (result["outcome_env"].get("data") or {}).get("datasets") or []
        best = max((row.get("gws_hits") or 0) for row in exposures) if exposures else 0
        print(f"{result['key'][:46]:<46} {result['state']:<6} "
              f"{_status(result['mr_env']):<7} {_status(result['instr_env']):<7} "
              f"{_status(result['outcome_env']):<7} {_status(result['catalog_env']):<8} "
              f"{str(mr_data.get('n_estimates')):>6} {best:>6} {len(datasets):>6}")

    counts = {}
    for result in results:
        counts[result["state"]] = counts.get(result["state"], 0) + 1
    print("-" * len(header))
    print("states : " + "  ".join(f"{state}={counts[state]}" for state in sorted(counts)))
    print("A = a retrieved MR estimate exists. B = no retrieved estimate, but the pair could "
          "be analysed.")
    print("C = neither could be retrieved. C is a gap in what these releases hold, never a "
          "claim of no effect.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description = "Run 1A(sample) -> 1B -> 1C -> classify over the demo pairs.",
    )
    parser.add_argument(
        "--pair",
        action  = "append",
        default = [],
        metavar = "SUBSTRING",
        help    = "run only pairs whose key contains this (repeatable); default is all of them",
    )
    parser.add_argument(
        "--skip-catalog",
        action = "store_true",
        help   = "skip get_gwas_catalog, which needs ~100 s per disease",
    )
    parser.add_argument(
        "--max-datasets",
        type    = int,
        default = MAX_DATASETS,
        help    = f"exposure datasets get_mqtl_instruments may query per pair (default {MAX_DATASETS})",
    )
    parser.add_argument(
        "--top-n",
        type    = int,
        default = TOP_N,
        help    = f"outcome datasets find_outcome_datasets returns per pair (default {TOP_N})",
    )
    args = parser.parse_args()

    sample = load_sample()
    selected = select_pairs(
        sample,
        args.pair,
    )
    if not selected:
        print("[end_to_end] nothing to run", file=sys.stderr)
        return 1

    print(f"{len(selected)} pair(s) from {SAMPLE_PATH.name}; "
          f"max_datasets={args.max_datasets} top_n={args.top_n}; "
          f"GWAS Catalog {'SKIPPED' if args.skip_catalog else 'included (slow)'}")

    results = []
    for key, entry in selected:
        result = run_pair(
            key,
            entry,
            skip_catalog = args.skip_catalog,
            max_datasets = args.max_datasets,
            top_n        = args.top_n,
        )
        report_pair(result)
        results.append(result)

    summary_table(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
