"""Measure whether a provider/model is fit to write section 9, across states and repeats.

    python scripts/interpretation_fixtures.py --provider gemini --model gemini-flash-lite-latest
    python scripts/interpretation_fixtures.py --provider claude --runs 5

THIS IS WHAT 'supported' MEANS. `llm/registry.py` says a model may only be promoted from
`experimental` once it has passed the evidence fixtures - and until this file existed that
sentence could not be acted on, which made the rule decorative. Promotion is now a
measurement someone ran, with a number attached.

WHY REPEATS. A model is not a function. One accepted card says nothing about whether the
next one is accepted, and a model that passes three times in five leaves section 9 blank
on two cards out of five. That is safe - the deterministic card always ships - but it is
not a feature anyone would want shipped. The acceptance RATE is the thing being measured,
so one pass per pair would be the wrong experiment however good it looked.

WHY ALL THREE STATES. State A has retrieved estimates to quote and is the easy case. State
B has feasibility but no estimate, and is where a model is most tempted to fill the gap
with something plausible. State C has almost nothing, and is where 'no evidence retrieved'
most often slides into 'no effect'. A model that only ever sees State A has not been
tested on the cases this project is most careful about.

WHAT A FAILURE HERE MEANS. A rejected run is the validator working, not the product
breaking - the card still ships. A low acceptance rate means this model is not worth
offering for this job, not that the evidence is in doubt.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm.cli import credential_from_env
from llm.interpret import interpret

DEMO = REPO_ROOT / "data" / "demo_card_inputs.json"

# A model that passes fewer than this share of runs is not worth offering: the blank
# section 9 it leaves behind is safe but reads as a broken feature. The threshold is a
# judgement, not a law - it is stated here so that promoting a model is a decision
# someone made against a number, rather than an impression.
PASS_THRESHOLD = 0.9


def demo_runs() -> dict:
    """Every cached pair, in the shape `pipeline.run_pair` returns.

    Built from the frozen snapshot rather than by calling the live pipeline: the point is
    to vary the model, not the evidence, and a live run would move both at once."""
    cached = json.loads(DEMO.read_text(encoding="utf-8"))
    runs = {}
    for pair, entry in cached["pairs"].items():
        sample = entry["inputs_from_1a"]
        envelopes = entry["envelopes"]
        runs[pair] = {
            "state":  entry["classify_state"]["state"],
            "reason": entry["classify_state"]["reason"],
            "metabolite": {
                "query":    sample["metabolite"]["input"],
                "label":    sample["metabolite"]["label"],
                "id":       sample["metabolite"]["chebi"],
                "synonyms": sample["metabolite"]["synonyms"],
            },
            "disease": {
                "query":    sample["disease"]["input"],
                "label":    sample["disease"]["label"],
                "id":       sample["disease"]["id"],
                "synonyms": sample["disease"]["synonyms"],
            },
            "envelopes": {
                "mr":          envelopes.get("get_mr_result"),
                "instruments": envelopes.get("get_mqtl_instruments"),
                "outcomes":    envelopes.get("find_outcome_datasets"),
                "catalog":     envelopes.get("get_gwas_catalog"),
            },
            "coloc_summary":  {},
            "effector_genes": [],
            "notes":          ["cached snapshot, not a live run."],
        }
    return runs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", default="gemini")
    parser.add_argument("--model", default=None)
    parser.add_argument("--runs", type=int, default=3,
                        help="repeats per pair (default 3); a model is not a function")
    parser.add_argument("--pause", type=float, default=2.0,
                        help="seconds between calls, to stay inside free-tier rate limits")
    args = parser.parse_args(argv)

    from llm import default_model

    model = args.model or default_model(args.provider)
    credential = credential_from_env(args.provider)
    runs = demo_runs()

    print(f"provider {args.provider} / model {model} / {args.runs} run(s) per pair\n")
    header = f"{'pair':<46} {'state':<6} {'result':<12} detail"
    print(header)
    print("-" * len(header))

    tally: Counter = Counter()
    findings: Counter = Counter()
    excerpts: dict = {}
    accepted_total = attempts = 0

    for pair, run in sorted(runs.items()):
        for index in range(args.runs):
            result = interpret(run, provider=args.provider, model=model,
                               credential=credential)
            attempts += 1
            tally[result.status] += 1
            accepted_total += 1 if result.accepted else 0
            for finding in result.findings:
                findings[f"{finding.rule} {finding.name}"] += 1

            for finding in result.findings:
                excerpts.setdefault(finding.rule, []).append(finding.excerpt)
            detail = "" if result.accepted else result.reason[:70]
            label = pair if index == 0 else ""
            print(f"{label:<46} {run['state']:<6} {result.status:<12} {detail}")
            if args.pause:
                time.sleep(args.pause)

    # TWO RATES, BECAUSE TWO UNRELATED THINGS CAN GO WRONG AND ONLY ONE IS ABOUT WRITING.
    # A run that never reached the provider - depleted credits, a timeout, a 429 - says
    # nothing about whether this model writes acceptable prose. It says the service was
    # unreachable, and the deterministic card shipped exactly as designed. Folding that
    # into one number lets an outage look like a quality problem, and lets a quality
    # problem hide behind good uptime. The first 10-run measurement read 87% for a model
    # whose prose was accepted 26 times out of the 27 calls that actually arrived.
    reached = tally["accepted"] + tally["rejected"]
    rate = (tally["accepted"] / reached) if reached else 0.0
    availability = (reached / attempts) if attempts else 0.0

    print("\n" + "=" * len(header))
    print(f"prose accepted    {tally['accepted']}/{reached}  ({rate:.0%})   <- gates promotion")
    print(f"provider reached  {reached}/{attempts}  ({availability:.0%})   <- infrastructure, not quality")
    for status, count in sorted(tally.items()):
        print(f"  {status:<14} {count}")
    if findings:
        print("\nvalidator findings seen:")
        for name, count in findings.most_common():
            print(f"  {count:>3}x  {name}")
            for excerpt in excerpts.get(name.split()[0], [])[:3]:
                print(f'         "{excerpt[:150]}"')

    if not reached:
        print("\nNO CALL REACHED THE PROVIDER. This measures nothing about the model; "
              "check credentials, credits and rate limits before reading anything into it.")
        return 1
    if availability < 1.0:
        print(f"\nNote: {attempts - reached} run(s) never reached the provider and are "
              "excluded from the prose rate. They are an availability problem, not a "
              "quality one - the deterministic card shipped for each of them.")

    verdict = "PASS" if rate >= PASS_THRESHOLD else "BELOW THRESHOLD"
    print(f"\n{verdict}: {rate:.0%} of {reached} delivered response(s), "
          f"against a {PASS_THRESHOLD:.0%} threshold.")
    if verdict == "PASS":
        print("This model may be promoted to 'supported' in llm/registry.py.")
        print("Record the date, the model id and this rate alongside the change.")
    else:
        print("Leave this model as 'experimental'. A blank section 9 is safe but is not")
        print("a feature worth offering at this rate.")
    return 0 if rate >= PASS_THRESHOLD else 1


if __name__ == "__main__":
    raise SystemExit(main())
