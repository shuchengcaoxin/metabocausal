"""1B: pre-computed metabolite -> disease MR estimates from EpiGraphDB MR-EVE.

MR-EVE is a published, pre-computed matrix of two-sample MR estimates between the
OpenGWAS datasets. It was computed by Hemani et al. (2017, bioRxiv 10.1101/173682,
"MR-EvE") with an automated mixture-of-experts method, and EpiGraphDB serves it
read-only. This module RETRIEVES rows from it. Nothing here fits a model,
harmonises alleles or computes an estimate, and no wording in a card may say it does.

How a pair becomes a query
--------------------------
1A hands two lists of display strings. `tools._traits.match_datasets` compares them
EXACTLY (after `normalize`) against the 34,494 cached Gwas trait strings, and the
matched datasets' own spellings - `Urate`, `Coronary artery disease` - are what /mr
is asked for. The user's spelling is never sent, and the vocabulary is never
searched loosely: /meta/nodes/Gwas/search does prefix/fuzzy matching that quietly
returns near-misses, so this module does not use it.

Two ways a pair can come back with nothing, and they are different:
  - neither side matched a dataset name -> no request was sent at all
  - both sides matched but MR-EVE holds no row for them -> the pair was not estimated
Both are `status: "empty"`, both say which case it was in `caveats`, and NEITHER is
evidence of no effect. One direction is asked for - metabolite as exposure, disease as
outcome - so "empty" is a fact about that direction only; the reverse can be populated
when this one is not (Glycine: 0 rows as an exposure, 5 rows as an outcome of CHD).

No key needed. Every public function returns the shared 8-key envelope and records
it in the ledger before returning, on every path including failure.
"""

from __future__ import annotations

import http.client
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from . import _common, _traits
except ImportError:                                    # running: python tools/epigraphdb.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _common
    import _traits

import ledger

SOURCE = "EpiGraphDB MR-EVE"
MR_URL = "https://api.epigraphdb.org/mr"
CYPHER_URL = "https://api.epigraphdb.org/cypher"

# One pair can match many datasets (17 for urate), but only a handful of distinct
# trait STRINGS, and the cap is on strings because that is what /mr is keyed by.
MAX_EXPOSURE_TRAITS = 5
MAX_OUTCOME_TRAITS = 5

RETRIEVED_CAVEAT = (
    "Retrieved from EpiGraphDB MR-EVE (OpenGWAS 2020-10-13 snapshot); automated MR "
    "labelled preliminary by the source. Not computed here. One direction only: the "
    "metabolite is queried as the EXPOSURE, never as the outcome, so nothing said here "
    "is a statement about the reverse direction."
)
EMPTY_CAVEAT = (
    "Empty is not evidence of no effect - the trait may be absent from this snapshot "
    "(e.g. no met-d datasets)."
)
NO_NSNP_CAVEAT = (
    "No SNP count was retrieved for these rows; this is missing information, not zero instruments."
)
SCALE_CAVEAT = (
    "Effect sizes are per unit of each exposure dataset's OWN scale and are not "
    "comparable across rows: ukb-d-30880_raw reports b per measured unit and "
    "ukb-d-30880_irnt b per SD of the same UKB measurement, an ~84x difference. This "
    "snapshot carries no `unit` for those datasets, so join exposure_id / outcome_id "
    "to the vocabulary (tools._traits) and print the dataset beside every number."
)
MOESCORE_CAVEAT = (
    "moescore is MR-EVE's mixture-of-experts score (0-1) for how appropriate the "
    "automatically selected MR method was, and selection is its instrument-selection "
    "strategy (DF / HF). Neither is a significance measure, and neither is a "
    "confidence that the effect is causal."
)
PVAL_ZERO_CAVEAT = (
    "p-values reported as exactly 0 underflowed double precision in the source. "
    "Render them as \"p < 1e-300 (reported 0)\", never as p = 0."
)

_ESTIMATE_FIELDS = (
    "exposure_id",
    "exposure_trait",
    "outcome_id",
    "outcome_trait",
    "b",
    "se",
    "pval",
    "method",
    "selection",
    "moescore",
    "nsnp",
    "ci_low",
    "ci_upp",
)

_HANDLED = (_common.RequestFailed, OSError, ValueError, http.client.HTTPException)


def _record(env: dict) -> dict:
    ledger.record(env)
    return env


def _as_list(value) -> list:
    # A model calling this tool routinely sends "urate" where the signature says a list.
    # list("urate") would shred it into five one-character synonyms that match nothing,
    # and the tool would then report an honest-looking "absent from the snapshot".
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _estimate(row: dict) -> dict:
    exposure = row.get("exposure") or {}
    outcome = row.get("outcome") or {}
    mr = row.get("mr") or {}
    return {
        "exposure_id":    exposure.get("id"),
        "exposure_trait": exposure.get("trait"),
        "outcome_id":     outcome.get("id"),
        "outcome_trait":  outcome.get("trait"),
        "b":              mr.get("b"),
        "se":             mr.get("se"),
        "pval":           mr.get("pval"),
        "method":         mr.get("method"),
        "selection":      mr.get("selection"),
        "moescore":       mr.get("moescore"),
        "nsnp":           mr.get("nsnp"),
        "ci_low":         mr.get("ci_low"),
        "ci_upp":         mr.get("ci_upp"),
        "source_release": mr.get("_source"),
        "source_properties": dict(mr),
        "detail_retrieval": row.get("detail_retrieval"),
    }


def _estimate_key(estimate: dict) -> tuple:
    # Two datasets of the same trait give different rows, and one dataset pair gives
    # one row per method, so identity is the whole estimate, not the id pair.
    return tuple(estimate.get(field) for field in _ESTIMATE_FIELDS)


def _pval_sort_key(estimate: dict) -> tuple:
    pval = estimate.get("pval")
    return (pval is None, pval if pval is not None else 0.0)


def _quality_caveats(estimates: list) -> list:
    """Everything a reader must know before printing one of these numbers. Each is a
    fact about how MR-EVE rows behave, checked against the rows actually retrieved, so
    the ledger carries it and `validate_card` can hold the model to it."""
    caveats = []

    if all(estimate["nsnp"] is None for estimate in estimates):
        caveats.append(NO_NSNP_CAVEAT)

    distinct = len({(e["b"], e["se"], e["pval"]) for e in estimates})
    if distinct < len(estimates):
        caveats.append(
            f"n_estimates counts retrieved ROWS: {len(estimates)} rows carry {distinct} "
            f"distinct (b, se, pval). MR-EVE returns one row per MR method, and a study "
            f"deposited under several OpenGWAS ids returns one row per id (ieu-a-1054 and "
            f"ebi-a-GCST001790 are both the 2013 gout GWAS, n=69374), so identical numbers "
            f"repeat. Never present this as a count of independent studies."
        )

    wald = [
        estimate for estimate in estimates
        if estimate["se"] is not None and estimate["se"] == estimate["b"]
    ]
    if wald:
        caveats.append(
            f"{len(wald)} of {len(estimates)} rows report se equal to b - MR-EVE "
            f"entries with suspicious uncertainty. This alone does not establish a single-SNP analysis. A negative or "
            f"b-equal se is not a usable uncertainty. The values are kept exactly as "
            f"retrieved; do not present those rows as effect estimates with error bars."
        )

    if len({estimate["exposure_id"] for estimate in estimates}) > 1:
        caveats.append(SCALE_CAVEAT)

    if any(estimate["pval"] == 0 for estimate in estimates if estimate["pval"] is not None):
        caveats.append(PVAL_ZERO_CAVEAT)

    caveats.append(MOESCORE_CAVEAT)
    caveats.append("Source ci_low / ci_upp are preserved verbatim; their confidence level and construction are not supplied here. They are not substituted with b +/- 1.96 se.")
    failures = sorted({e.get("detail_retrieval", {}).get("error", "") for e in estimates
                       if isinstance(e.get("detail_retrieval"), dict)
                       and e["detail_retrieval"].get("status") == "error"})
    if failures:
        caveats.append("Primary Cypher retrieval failed; REST /mr fallback rows retained: " + "; ".join(failures))
    return caveats


def _cap(
    traits:  list,
    limit:   int,
    side:    str,
    caveats: list,
) -> list:
    if len(traits) <= limit:
        return traits
    caveats.append(
        f"Capped: {len(traits)} matched {side} trait names, only the first {limit} "
        f"were queried ({', '.join(traits[:limit])}); dropped {', '.join(traits[limit:])}."
    )
    return traits[:limit]


def _failure(
    tool:    str,
    args:    dict,
    data:    dict,
    caveats: list,
    exc:     Exception,
    planned: int | None = None,
) -> dict:
    """Error envelope that KEEPS whatever was already retrieved. A pair can need several
    queries (urate|gout sends two), and the rows the earlier ones returned are evidence
    that exists - discarding them would silently turn a State A pair into State C."""
    message = getattr(
        exc,
        "message",
        None,
    ) or f"{type(exc).__name__}: {exc}"
    data["error"] = message

    url = getattr(
        exc,
        "url",
        None,
    ) or (data["queries"][-1] if data.get("queries") else MR_URL)

    retrieved = data.get("estimates") or []
    sent = len(data.get("queries") or [])
    if retrieved:
        of_planned = f" of {planned}" if planned else ""
        note = (
            f"The EpiGraphDB request failed after {sent}{of_planned} planned query(ies): "
            f"{message}. The {len(retrieved)} estimate(s) already retrieved are kept in "
            f"data['estimates'] and are real; the queries never sent may hold more."
        )
    else:
        note = (
            f"The EpiGraphDB request failed before any estimate was retrieved, so this "
            f"pair has no retrieved evidence either way: {message}"
        )

    return _record(_common.envelope(
        tool    = tool,
        args    = args,
        source  = SOURCE,
        url     = url,
        status  = "error",
        data    = data,
        caveats = [*caveats, note],
    ))


class _RetrievedRows(list):
    """Keep request provenance even when a successful fallback returns zero rows."""

    def __init__(self, rows, detail):
        super().__init__(rows)
        self.detail = detail


def _query_mr(
    exposure_trait,
    outcome_trait  = None,
    pval_threshold = 1.0,
):
    """Retrieve complete source relationships, with REST fallback on failure."""
    query = (
        "MATCH (exposure:Gwas)-[mr:MR_EVE_MR]->(outcome:Gwas) WHERE "
        f"exposure.trait = {json.dumps(exposure_trait)} "
        f"AND mr.pval <= {float(pval_threshold)} "
    )
    if outcome_trait is not None:
        query += f"AND outcome.trait = {json.dumps(outcome_trait)} "
    query += "RETURN exposure {.id,.trait}, outcome {.id,.trait}, properties(mr) AS mr"
    detail = {"url": CYPHER_URL, "query": query, "status": "ok"}
    try:
        payload, final_url = _common.get_json(
            CYPHER_URL,
            method    = "POST",
            json_body = {"query": query},
            timeout   = _common.TIMEOUT_SECONDS,
            retries   = 0,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise ValueError("EpiGraphDB returned an invalid source-detail response")
        rows = payload["results"]
        for row in rows:
            if not isinstance(row, dict) or not all(
                isinstance(row.get(key), dict) for key in ("exposure", "outcome", "mr")
            ):
                raise ValueError("EpiGraphDB returned an invalid source relationship")
            row["detail_retrieval"] = dict(detail)
        return _RetrievedRows(rows, detail), final_url
    except Exception as exc:
        detail = {**detail, "status": "error", "error": str(exc)}
    params = {
        "exposure_trait": exposure_trait,
        "pval_threshold": pval_threshold,
    }
    if outcome_trait is not None:
        params["outcome_trait"] = outcome_trait

    payload, final_url = _common.get_json(
        MR_URL,
        params  = params,
        timeout = _common.TIMEOUT_SECONDS,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("EpiGraphDB returned an invalid MR response; not an empty result")
    rows = list(payload["results"])
    for row in rows:
        row["detail_retrieval"] = dict(detail)
    return _RetrievedRows(rows, detail), final_url


def _retrieval_note(
    rows,
    data,
    caveats,
):
    detail = getattr(rows, "detail", None)
    if detail:
        data.setdefault("source_requests", []).append(detail)
        if detail.get("status") == "error":
            caveats.append(
                "Primary Cypher retrieval failed; REST fallback was used and may omit source "
                "CI and SNP counts. " + detail.get("error", "")
            )


def get_mr_result(metabolite_synonyms: list, disease_synonyms: list) -> dict:
    """Retrieve pre-computed metabolite -> disease MR estimates from EpiGraphDB MR-EVE.

    Give it 1A's two synonym lists (display strings, any case). They are exact-matched
    against the cached GWAS trait vocabulary, and every matched exposure trait is
    queried against every matched outcome trait with no significance filter, so the
    card sees null results too.

    `status` is "empty" when no dataset is named by those synonyms OR when MR-EVE holds
    no metabolite -> disease row for the pair. Empty means "not in this snapshot", never
    "no effect" - the caveats say which of the two happened. Only that one direction is
    queried. Estimates are retrieved, never computed here.
    """
    args = {
        "metabolite_synonyms": _as_list(metabolite_synonyms),
        "disease_synonyms":    _as_list(disease_synonyms),
    }
    data = {
        "exposure_matches": [],
        "outcome_matches":  [],
        "estimates":        [],
        "n_estimates":      0,
        "queries":          [],
    }
    caveats = [RETRIEVED_CAVEAT]
    planned = None

    try:
        vocabulary = _traits.load_vocabulary("epigraphdb")
        data["exposure_matches"] = _traits.match_datasets(args["metabolite_synonyms"], vocabulary)
        data["outcome_matches"] = _traits.match_datasets(args["disease_synonyms"], vocabulary)

        exposure_traits = _traits.unique_traits(data["exposure_matches"])
        outcome_traits = _traits.unique_traits(data["outcome_matches"])

        unmatched = []
        if not exposure_traits:
            unmatched.append("metabolite")
        if not outcome_traits:
            unmatched.append("disease")
        if unmatched:
            caveats.append(
                f"No dataset in this snapshot is named by any of the "
                f"{' or '.join(unmatched)} synonyms, so no MR query was sent."
            )
            caveats.append(EMPTY_CAVEAT)
            return _record(_common.envelope(
                tool    = "get_mr_result",
                args    = args,
                source  = SOURCE,
                # No request was sent, so there is no URL to report. `url` is the URL
                # actually sent; a bare /mr would 422 if a reader followed it.
                url     = "",
                status  = "empty",
                data    = data,
                caveats = caveats,
            ))

        exposure_traits = _cap(
            exposure_traits,
            MAX_EXPOSURE_TRAITS,
            "exposure",
            caveats,
        )
        outcome_traits = _cap(
            outcome_traits,
            MAX_OUTCOME_TRAITS,
            "outcome",
            caveats,
        )

        planned = len(exposure_traits) * len(outcome_traits)

        # `estimates` IS data["estimates"], so a query that fails half way through the
        # cross product leaves the rows the earlier queries returned in the envelope.
        estimates, seen = data["estimates"], set()
        for exposure_trait in exposure_traits:
            for outcome_trait in outcome_traits:
                rows, sent_url = _query_mr(
                    exposure_trait,
                    outcome_trait,
                    1.0,
                )
                data["queries"].append(sent_url)
                _retrieval_note(
                    rows,
                    data,
                    caveats,
                )
                for row in rows:
                    estimate = _estimate(row)
                    key = _estimate_key(estimate)
                    if key in seen:
                        continue
                    seen.add(key)
                    estimates.append(estimate)
                data["n_estimates"] = len(estimates)

        if estimates:
            caveats.extend(_quality_caveats(estimates))
            status = "ok"
        else:
            caveats.append(
                f"Both sides matched ({', '.join(exposure_traits)} x "
                f"{', '.join(outcome_traits)}) but MR-EVE holds no metabolite -> disease "
                f"estimate for this pair. Only that direction was queried: a metabolite "
                f"with too few instruments has no MR-EVE row as an exposure at all, while "
                f"the reverse direction can be fully populated (Glycine returns 0 rows as "
                f"an exposure; Coronary heart disease -> Glycine returns 5)."
            )
            caveats.append(EMPTY_CAVEAT)
            status = "empty"

        return _record(_common.envelope(
            tool    = "get_mr_result",
            args    = args,
            source  = SOURCE,
            url     = data["queries"][0] if data["queries"] else MR_URL,
            status  = status,
            data    = data,
            caveats = caveats,
        ))

    except _HANDLED as exc:
        return _failure(
            "get_mr_result",
            args,
            data,
            caveats,
            exc,
            planned,
        )
    except Exception as exc:                           # nothing escapes a tool
        return _failure(
            "get_mr_result",
            args,
            data,
            caveats,
            exc,
            planned,
        )


def get_mr_outcomes(metabolite_trait: str, pval_threshold: float = 1e-5) -> dict:
    """Sweep every outcome MR-EVE has estimated for one exposure trait.

    `metabolite_trait` must already be a vocabulary spelling (the output of
    `tools._traits.unique_traits`), because /mr matches trait strings exactly. The
    outcome is left wildcard, which is thousands of rows, hence the 1e-5 default
    threshold. Each row carries `outcome_cat`, `outcome_sub`, `outcome_n` and
    `outcome_ncase`, joined from the cached vocabulary.

    TO KEEP ONLY DISEASE OUTCOMES, FILTER ON `outcome_ncase`, NOT ON `outcome_cat`.
    `outcome_cat` is the source's own category label and is not a disease flag: it
    takes eight values, is null for 20,826 of the 34,494 datasets (every ebi-a-* row
    included, so the largest CAD and T2D GWAS are null), and the diseases this project
    demos are labelled 'Disease' - Gout ieu-a-1054 is 'Disease', so a cat=="Binary"
    filter drops the pair the whole demo rests on while keeping UKB admin variables.
    `outcome_ncase` is the case count: non-null for the 4,780 case/control datasets,
    non-null for every demo disease, null for every metabolite dataset.

    Library entry point for building candidate lists offline. Deliberately NOT in
    TOOLS: the agent must not be able to trigger a 4,000-row sweep mid-card.
    """
    args = {
        "metabolite_trait": metabolite_trait,
        "pval_threshold":   pval_threshold,
    }
    data = {
        "estimates":   [],
        "n_estimates": 0,
        "queries":     [],
    }
    caveats = [RETRIEVED_CAVEAT]

    try:
        vocabulary = _traits.load_vocabulary("epigraphdb")
        by_id = {row.get("id"): row for row in vocabulary}

        rows, sent_url = _query_mr(
            metabolite_trait,
            None,
            pval_threshold,
        )
        data["queries"].append(sent_url)
        _retrieval_note(
            rows,
            data,
            caveats,
        )

        estimates, seen, unknown, null_cat = data["estimates"], set(), 0, 0
        for row in rows:
            estimate = _estimate(row)
            key = _estimate_key(estimate)
            if key in seen:
                continue
            seen.add(key)
            outcome = by_id.get(estimate["outcome_id"])
            if outcome is None:
                outcome = {}
                unknown += 1
            estimate["outcome_cat"] = outcome.get("cat")
            estimate["outcome_sub"] = outcome.get("sub")
            estimate["outcome_n"] = outcome.get("n")
            estimate["outcome_ncase"] = outcome.get("ncase")
            if outcome and outcome.get("cat") is None:
                null_cat += 1
            estimates.append(estimate)
            data["n_estimates"] = len(estimates)

        estimates.sort(key=_pval_sort_key)

        caveats.append(
            f"Outcome wildcard: every trait MR-EVE estimated from {metabolite_trait!r} "
            f"at pval < {pval_threshold}. No cap - all {len(estimates)} rows are here."
        )
        if unknown:
            caveats.append(
                f"{unknown} outcome dataset id(s) are not in the cached vocabulary, so "
                f"outcome_cat / outcome_n / outcome_ncase are null for them."
            )
        if null_cat:
            caveats.append(
                f"{null_cat} of {len(estimates)} rows joined to the vocabulary but carry "
                f"outcome_cat = null, which is normal (60% of the snapshot, including every "
                f"ebi-a-* dataset). Select diseases with outcome_ncase, never with cat."
            )
        if estimates:
            caveats.extend(_quality_caveats(estimates))
        if not estimates:
            caveats.append(
                f"No MR-EVE row from {metabolite_trait!r} at this threshold. Check the "
                f"spelling against the vocabulary before reading anything into it."
            )
            caveats.append(EMPTY_CAVEAT)

        return _record(_common.envelope(
            tool    = "get_mr_outcomes",
            args    = args,
            source  = SOURCE,
            url     = sent_url,
            status  = "ok" if estimates else "empty",
            data    = data,
            caveats = caveats,
        ))

    except _HANDLED as exc:
        return _failure(
            "get_mr_outcomes",
            args,
            data,
            caveats,
            exc,
            1,
        )
    except Exception as exc:
        return _failure(
            "get_mr_outcomes",
            args,
            data,
            caveats,
            exc,
            1,
        )


if __name__ == "__main__":
    def show(env, limit=3):
        print(f"  status      : {env['status']}")
        print(f"  url         : {env['url']}")
        print(f"  queries     : {len(env['data'].get('queries', []))}")
        print(f"  n_estimates : {env['data'].get('n_estimates')}")
        for estimate in env["data"].get("estimates", [])[:limit]:
            print(f"    {estimate['exposure_id']} -> {estimate['outcome_id']:<20} "
                  f"b={estimate['b']:+.4f} se={estimate['se']:.4f} "
                  f"pval={estimate['pval']:.3g} {estimate['method']}")
        for caveat in env["caveats"]:
            print(f"  caveat      : {caveat}")

    print("1) urate x gout, from synonym lists")
    show(get_mr_result(
        ["urate", "URIC ACID", "Lithic acid"],
        ["gout", "gouty arthropathy"],
    ))

    print("\n2) sweep: every outcome of 'Urate' at pval < 1e-5")
    sweep = get_mr_outcomes("Urate")
    show(sweep)
    # The disease filter. NOT outcome_cat: Gout ieu-a-1054 is cat='Disease' and
    # ebi-a-GCST001790 is cat=None, so cat=='Binary' would drop the demo's own outcome.
    diseases = [e for e in sweep["data"]["estimates"] if e.get("outcome_ncase") is not None]
    print(f"  of which report a case count (case/control study): {len(diseases)}")
    gout = [e for e in sweep["data"]["estimates"] if e["outcome_id"] == "ieu-a-1054"]
    kept = [e for e in gout if e in diseases]
    by_cat = [e for e in gout if e.get("outcome_cat") == "Binary"]
    print(f"    ieu-a-1054 Gout: {len(gout)} row(s), cat={gout[0]['outcome_cat']!r} "
          f"ncase={gout[0]['outcome_ncase']!r}")
    print(f"    kept by outcome_ncase is not None : {len(kept)} of {len(gout)}")
    print(f"    kept by outcome_cat == 'Binary'   : {len(by_cat)} of {len(gout)}  <- the wrong filter")

    print("\n3) a metabolite nobody named that way")
    show(get_mr_result(
        ["zzqx-not-a-trait"],
        ["gout"],
    ))

    print("\n4) a bare string where the signature says a list")
    shredded = get_mr_result("urate", "gout")
    print(f"  status      : {shredded['status']}")
    print(f"  n_estimates : {shredded['data']['n_estimates']}")
    print(f"  args        : {shredded['args']}")

    print("\n5) rows whose reported se equals b (single-SNP Wald ratio)")
    show(get_mr_result(
        ["tyrosine"],
        ["celiac disease"],
    ), limit=2)
