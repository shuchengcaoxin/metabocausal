"""1C: OpenGWAS feasibility - can this pair be analysed, with which datasets?

1B asks "has somebody already estimated this?". 1C asks the prior question: does a
genome-wide association study of this metabolite exist, does it carry usable genetic
instruments, and is there an outcome GWAS to run them against. Nothing here fits a
model, harmonises alleles, clumps anything or produces an effect estimate. `gws_hits`
is a count of loci somebody else already found; `F` is arithmetic on a retrieved beta
and se. A card may say "this pair is analysis-ready" and may never say "this
metabolite affects this disease".

Two sources, both live:
  GET  /api/gwasinfo   the dataset index, cached to data/gwasinfo.json by
                       tools._traits.build_opengwas_vocabulary (50,056 datasets)
  POST /api/tophits    that dataset's LD-clumped hits at p < 5e-8, one call per dataset

WHY THE met- PREFIX IS NOT THE FILTER
-------------------------------------
The obvious rule - "a metabolite dataset is one whose id starts with met-" - is wrong
and it fails on the pair this project demos. Urate matches 22 datasets in gwasinfo and
exactly ONE of them is met-* (met-a-345, n=7,819). A met- filter would throw away the
other 21, including the largest by a factor of 56 (ieu-b-5137, n=440,466, category
"Risk factor") and ieu-a-789, the very dataset whose published urate -> gout estimate
1B retrieves. So the filter here is the other way round: keep every matched dataset
EXCEPT the ones that are plainly case/control studies, and say in the caveats which
were dropped and why.

ncase IS NOT THE DISEASE FLAG, ncontrol IS
------------------------------------------
gwasinfo writes ncase == sample_size and ncontrol == 0 on the ukb-e continuous
measurements (ukb-e-30700_CSA: ncase 8,422 of n 8,422, a creatinine level), so a
"has ncase" test calls four blood-chemistry panels a disease. A positive ncontrol
does not do that: of the 50,056 datasets, 10,708 carry both, and every one of the
demo's diseases is among them.

THE SAME METABOLITE IS SEVERAL DATASETS ON SEVERAL PLATFORMS
------------------------------------------------------------
"Glycine" is met-d-Gly (n=114,972, 2020, Nightingale NMR in UK Biobank, unit "NA")
AND met-a-468 (n=7,802, 2014, Metabolon-type MS, unit "log10 units"). Different
assays, different scales, effect sizes not comparable. Every matching dataset is kept
and reported separately with its own platform, unit, n, year and population; they are
never merged into one number.

Platform is inferred ONLY from met-a (Metabolon-type MS), met-c and met-d
(Nightingale NMR). met-b looks like a metabolite batch and is not one: all 150 met-b
datasets are Roederer 2015 immune-cell flow cytometry (PMID 25772697, n=497, units
"%"), so that batch is left with platform null like any other.

SAMPLE OVERLAP IS THE HOLE THIS MODULE CANNOT FILL
--------------------------------------------------
get_mqtl_instruments sees the exposure, find_outcome_datasets sees the outcome, and
neither sees both. glycine|coronary artery disease pairs met-d-Gly - UK Biobank - with
ebi-a-GCST005194, which IS the UK Biobank CAD stage of van der Harst 2017, and with
the meta-analysis that contains it. Overlapping samples bias two-sample MR towards the
observational estimate. Both functions therefore flag the risk in caveats whenever a
UK Biobank deposit or a very large meta-analysis is in hand; neither can confirm or
rule out the overlap, and a card must not print "analysis-ready" without checking it.

Needs OPENGWAS_JWT (from the .env above the repo root, via `_common.load_env`), sent
in the Authorization header and nowhere else. It never reaches a URL, an envelope, a
caveat or the ledger. Absent token -> a clean error envelope, never a crash.

Every public function returns the shared 8-key envelope and records it in the ledger
before returning, on every path including failure.
"""

from __future__ import annotations

import http.client
import math
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from . import _common, _traits
except ImportError:                                    # running: python tools/opengwas.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _common
    import _traits

import ledger

SOURCE = "OpenGWAS (gwasinfo index + tophits)"
GWASINFO_URL = _traits.GWASINFO_URL
TOPHITS_URL = "https://api.opengwas.io/api/tophits"

TOPHITS_PVAL = 5e-8
TOPHITS_CLUMP = 1
TOPHITS_TIMEOUT_SECONDS = 60

JWT_ENV_VAR = "OPENGWAS_JWT"

# Printable ASCII only: what an HTTP header value may hold. See _token().
_HEADER_SAFE = re.compile(r"[!-~]+")

WEAK_INSTRUMENT_F = 10
MAX_EXAMPLE_HITS = 5

# gwasinfo has no platform field, so the batch prefix is the only signal there is.
# met-b is deliberately absent: all 150 met-b datasets are category "Immune system"
# from PMID 25772697 (Roederer 2015, immune-cell subsets by flow cytometry, n=497,
# units "%"), not a metabolite panel at all. An unknown batch reports platform null,
# which is the honest answer.
_PLATFORM_BY_BATCH = {
    "met-a": "mass spectrometry (Metabolon-type panel)",
    "met-c": "Nightingale NMR",
    "met-d": "Nightingale NMR (UK Biobank)",
}

# The batches whose participants come from UK Biobank, which is what makes sample
# overlap with a modern outcome GWAS likely. met-d is the Nightingale UKB release.
_UK_BIOBANK_BATCHES = ("met-d", "ukb-a", "ukb-b", "ukb-d", "ukb-e")
_OVERLAP_SIZE_HINT = 250_000

_CASE_CONTROL_CATEGORIES = {"binary", "disease"}
_PREFERRED_OUTCOME_PREFIXES = ("ebi-", "ieu-", "finn-")

RETRIEVED_CAVEAT = (
    "Retrieved from OpenGWAS: the gwasinfo dataset index plus, per dataset, its "
    "pre-computed tophits. This is a feasibility report - which datasets exist and "
    "whether they carry instruments - and NOT an MR result. No estimate was computed "
    "here and nothing here says an effect exists."
)
PLATFORM_CAVEAT = (
    "gwasinfo carries no platform field, so platform is INFERRED from the id batch "
    "prefix: met-a is the Metabolon-type mass-spectrometry panel (Shin 2014), met-c "
    "and met-d are Nightingale NMR (met-d being the UK Biobank release). Every other "
    "batch - met-b included, which is not a metabolite panel at all but Roederer 2015 "
    "immune-cell flow cytometry - is reported with platform null rather than guessed at."
)
CLUMP_CAVEAT = (
    "gws_hits counts OpenGWAS's own PRE-CLUMPED tophits at p < 5e-8: independent loci, "
    "not SNPs. The independence comes from that pre-computed set, built at OpenGWAS's "
    "own r2/kb defaults, and NOT from the clump flag this tool sends - measured "
    "2026-09-10, met-d-Gly returns the same 49 rows with clump=1, with clump=0 and with "
    "no clump key at all, because preclumped defaults to 1. Clumping on the fly instead "
    "(preclumped=0, clump=1) gives a slightly different set: 52 rows in 6.7 s against "
    "0.1 s. The p-value threshold IS applied on top of the pre-clumped set."
)
F_CAVEAT = (
    "F is the approximate per-SNP F statistic (beta/se)^2, arithmetic on the retrieved "
    "beta and se; weak_instruments counts hits with F < 10. It is NOT the first-stage F "
    "of a fitted MR, because no MR was fitted here, and a hit whose se is missing or "
    "zero gets no F at all. These betas also come from the same scan that selected the "
    "SNPs at p < 5e-8, so every F here is inflated by winner's curse - read it as an "
    "upper bound on instrument strength, not an estimate of it."
)
SCALE_FALLBACK_CAVEAT = (
    "Several datasets of one metabolite are not interchangeable: they are different "
    "assays on different scales, so effect sizes across them are not comparable. Print "
    "platform / unit / sample_size beside every number and never merge them into one."
)
OVERLAP_CAVEAT = (
    "Sample overlap is NOT checked here and it is the first thing a two-sample MR "
    "reviewer asks. This tool sees one side of the pair at a time, so it cannot tell "
    "whether the exposure and outcome GWAS share participants. Overlapping samples bias "
    "two-sample MR towards the confounded observational estimate and inflate type-1 "
    "error. Check the cohort composition of BOTH datasets before any card says "
    "analysis-ready."
)
STRATUM_CAVEAT = (
    "A sex-stratified dataset or an interaction scan is not a main-effect exposure: an "
    "interaction beta measures how the SNP effect changes with the modifier, so "
    "F = (beta/se)^2 on it is not instrument strength. sex and note are reported per "
    "dataset for exactly this reason - three urate datasets (ieu-a-786/787/788) are "
    "otherwise identical rows."
)
ZERO_HITS_CAVEAT = (
    "tophits answers an id it does not recognise with an empty list, exactly as it "
    "answers a real dataset that has no genome-wide hit. So gws_hits = 0 means \"no "
    "LD-clumped hit at p < 5e-8 in this dataset\" and never \"this measurement has no "
    "genetic basis\"."
)
EMPTY_CAVEAT = (
    "Empty is not evidence of no effect and not evidence of no genetic basis - it is a "
    "statement about what this release of OpenGWAS holds."
)
PVAL_ZERO_TEMPLATE = (
    "{ids} report p exactly 0 on at least one hit, which underflowed double precision "
    "in the source. Render those as \"p < 1e-300 (reported 0)\", never as p = 0."
)
CACHE_CAVEAT = (
    f"Dataset metadata is read from the local cache of {GWASINFO_URL} "
    f"(data/gwasinfo.json, 50,056 datasets pulled 2026-09-10). No index request is sent "
    f"per call; refresh it with tools._traits.build_opengwas_vocabulary()."
)
NCASE_CAVEAT = (
    "ncase / ncontrol are reported exactly as gwasinfo wrote them. They are not always "
    "a study design: the ukb-e continuous panels carry ncase == sample_size and "
    "ncontrol == 0 on a blood measurement, and the finn-b datasets carry case and "
    "control counts but no sample_size at all."
)
POPULATION_CAVEAT = (
    "population is reported per dataset because it has to be checked against the "
    "exposure's population before any MR is run; this tool sees only one side of the "
    "pair and cannot check it for you."
)
ENCODING_TEMPLATE = (
    "gwasinfo stores some author / consortium names with broken non-ASCII escapes "
    "({ids}; \"K<c3><b6>ttgen A\" is Kottgen A with an umlaut, \"D<U+00F6>nerta<U+015F> "
    "HM\" is Donertas HM). 1,357 of the 50,056 cached rows carry a \"<U+00xx>\" escape "
    "and 20 carry raw byte tokens. The string is reported exactly as the source wrote "
    "it - the damage is OpenGWAS's, not this tool's - so a renderer that wants a clean "
    "name has to repair it and say it did."
)
COUNT_MISMATCH_TEMPLATE = (
    "gwasinfo's ncase + ncontrol do not add up to sample_size for {details}. At least "
    "one of the three numbers is wrong at the source. They are reported verbatim, not "
    "repaired: do not print a case/control split for these datasets without checking "
    "the publication. 34 of the 50,056 cached datasets are inconsistent by more than 2%."
)
SAME_PUBLICATION_TEMPLATE = (
    "{groups} are deposits from the SAME publication (matching PMID) and are not "
    "independent outcome datasets - one can be a sub-stage of the other, so their "
    "sample sizes differ while the participants do not. Count the study once."
)

_ENCODING_DAMAGE_MARKERS = ("<U+", "<c3>", "<c5>", "<b6>")

_HANDLED = (_common.RequestFailed, OSError, ValueError, http.client.HTTPException)


def _record(env: dict) -> dict:
    ledger.record(env)
    return env


def _as_list(value) -> list:
    # A model calling this tool routinely sends "glycine" where the signature says a
    # list. list("glycine") would shred it into seven one-character synonyms that match
    # nothing, and the tool would then report an honest-looking "absent from OpenGWAS".
    # It also sends a bare number sometimes, and list(42) raises TypeError. This runs
    # while the `args` dict is built, outside the try, so a raise here would escape the
    # tool entirely and record nothing in the ledger. It must be total.
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [str(value)]


def _number(value):
    """A float, or None. gwasinfo writes the literal "NA", tophits writes "" for a
    missing per-SNP n, and EpiGraphDB-style sources write "2115.0" - all of them mean
    absent or mean a number, and none of them may raise."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    text = str(value).strip()
    if not text or text.upper() == "NA":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _count(value):
    number = _number(value)
    return int(round(number)) if number is not None else None


def _text(value):
    if value is None:
        return None
    text = str(value).strip()
    return None if not text or text.upper() == "NA" else text


def _batch(identifier: str) -> str:
    parts = str(identifier or "").split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else str(identifier or "")


def _platform(identifier: str):
    return _PLATFORM_BY_BATCH.get(_batch(identifier))


def _is_uk_biobank(identifier: str) -> bool:
    return _batch(identifier) in _UK_BIOBANK_BATCHES


def _scale_caveat(rows: list) -> str:
    """The scale warning built from the rows actually in this envelope. A hardcoded
    glycine example on a urate card is a caveat about datasets that are not there."""
    described = [
        f"{row['id']} ({row['platform'] or 'platform unknown'}, unit {row['unit']!r}, "
        f"n={row['sample_size']})"
        for row in rows[:3]
    ]
    if len(described) < 2:
        return SCALE_FALLBACK_CAVEAT
    return (
        f"Several datasets of one metabolite are not interchangeable: they are "
        f"different assays on different scales - {' vs '.join(described)}. Effect sizes "
        f"across them are not comparable. Print platform / unit / sample_size beside "
        f"every number and never merge them into one."
    )


def _encoding_damaged(rows: list) -> list:
    """Ids whose author or consortium string carries the source's own mojibake."""
    damaged = []
    for row in rows:
        text = f"{row.get('author') or ''} {row.get('consortium') or ''}"
        if any(marker in text for marker in _ENCODING_DAMAGE_MARKERS):
            damaged.append(row["id"])
    return damaged


def _count_mismatches(rows: list) -> list:
    """`"<id>: ncase + ncontrol vs sample_size"` for every row whose three counts
    cannot all be true. Reported, never repaired."""
    details = []
    for row in rows:
        size, ncase, ncontrol = row.get("sample_size"), row.get("ncase"), row.get("ncontrol")
        if None in (size, ncase, ncontrol) or not size:
            continue
        if abs((ncase + ncontrol) - size) > 0.02 * size:
            details.append(f"{row['id']} ({ncase:,} + {ncontrol:,} vs {size:,})")
    return details


def _size_key(row: dict) -> tuple:
    size = _number(row.get("sample_size"))
    return (size is None, -(size or 0.0), str(row.get("id") or ""))


def _outcome_key(row: dict) -> tuple:
    """Datasets with a recorded sample size first, then the curated repositories, then
    size descending. Size outranks the repository preference because a dataset gwasinfo
    gives no sample_size for (every finn-b row) cannot be compared to one it does."""
    identifier = str(row.get("id") or "")
    preferred = any(identifier.startswith(prefix) for prefix in _PREFERRED_OUTCOME_PREFIXES)
    unsized, negative_size, tiebreak = _size_key(row)
    return (unsized, 0 if preferred else 1, negative_size, tiebreak)


def _is_case_control(row: dict) -> bool:
    """gwasinfo's own category when it commits to one, ncontrol otherwise. NOT ncase:
    ukb-e-30700_CSA is a creatinine level with ncase == sample_size and ncontrol == 0."""
    if _common.normalize(row.get("category")) in _CASE_CONTROL_CATEGORIES:
        return True
    ncontrol = _count(row.get("ncontrol"))
    return ncontrol is not None and ncontrol > 0


def _f_statistic(beta, se):
    beta_value = _number(beta)
    se_value = _number(se)
    if beta_value is None or se_value is None or se_value == 0:
        return None
    return (beta_value / se_value) ** 2


def _hit(row: dict) -> dict:
    return {
        "rsid":     _text(row.get("rsid")),
        "chr":      _text(row.get("chr")),
        "position": _count(row.get("position")),
        "ea":       _text(row.get("ea")),
        "nea":      _text(row.get("nea")),
        "eaf":      _number(row.get("eaf")),
        "beta":     _number(row.get("beta")),
        "se":       _number(row.get("se")),
        "p":        _number(row.get("p")),
        "n":        _count(row.get("n")),
        "f":        _f_statistic(row.get("beta"), row.get("se")),
    }


def _p_sort_key(hit: dict) -> tuple:
    p = hit.get("p")
    return (p is None, p if p is not None else 0.0)


def _query_tophits(dataset_id: str) -> tuple:
    """One POST /api/tophits for one dataset. Returns `(hits, url_actually_sent)`.

    The token goes in the Authorization header and nowhere else; `url_actually_sent`
    is a bare endpoint with no query string, so it is safe to put in the envelope.
    """
    payload, final_url = _common.get_json(
        TOPHITS_URL,
        method    = "POST",
        headers   = _auth_headers(),
        json_body = {
            "id":    [dataset_id],
            "pval":  TOPHITS_PVAL,
            "clump": TOPHITS_CLUMP,
        },
        timeout   = TOPHITS_TIMEOUT_SECONDS,
    )
    if isinstance(payload, list):
        return payload, final_url
    return [], final_url


def _token() -> str:
    """The JWT, or "" - never printed, logged, returned in an envelope or compared to
    anything but emptiness.

    A value carrying an interior CR/LF or any other non-printable character is treated
    as absent rather than sent: `requests` validates a header value while PREPARING the
    request, before `_common.get_json`'s try block, and its InvalidHeader message quotes
    the offending value in full - which would put the credential into data["error"], a
    caveat, the ledger file and stdout. "" routes to the clean no-token envelope instead.
    """
    _common.load_env()
    value = (os.environ.get(JWT_ENV_VAR) or "").strip()
    return value if _HEADER_SAFE.fullmatch(value) else ""


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Content-Type":  "application/json",
    }


def _no_token_envelope(
    tool:    str,
    args:    dict,
    data:    dict,
    caveats: list,
) -> dict:
    data["error"] = f"{JWT_ENV_VAR} is absent, empty or not usable as a header value"
    return _record(_common.envelope(
        tool    = tool,
        args    = args,
        source  = SOURCE,
        url     = "",
        status  = "error",
        data    = data,
        caveats = [
            *caveats,
            f"No request was sent: {JWT_ENV_VAR} is absent, empty, or carries a "
            f"character that cannot go in an HTTP header (a stray line break from a "
            f"copy-paste does this), and every api.opengwas.io endpoint answers 401 "
            f"without a usable token. Put the token in the .env above the repo root "
            f"(see .env.example) and re-run. This is a missing credential, not a "
            f"missing dataset - nothing at all was looked up. The value itself is never "
            f"quoted here.",
            EMPTY_CAVEAT,
        ],
    ))


def _failure(
    tool:    str,
    args:    dict,
    data:    dict,
    caveats: list,
    exc:     Exception,
    planned: int | None = None,
) -> dict:
    """Error envelope that KEEPS whatever was already retrieved, exactly as 1B does. One
    call can query several datasets, and the ones that answered are real evidence -
    discarding them would turn a State B pair into a State C pair on a hiccup."""
    message = getattr(
        exc,
        "message",
        None,
    ) or f"{type(exc).__name__}: {exc}"
    # Belt and braces: no exception text from any library may carry the credential into
    # data["error"], a caveat, the ledger file or stdout.
    secret = _token()
    if secret:
        message = message.replace(secret, "<redacted>")
    data["error"] = message

    url = getattr(
        exc,
        "url",
        None,
    ) or (data["queries"][-1] if data.get("queries") else "")

    retrieved = data.get("exposures") or data.get("datasets") or []
    sent = len(data.get("queries") or [])
    if retrieved:
        of_planned = f" of {planned}" if planned else ""
        note = (
            f"The OpenGWAS request failed after {sent}{of_planned} planned query(ies): "
            f"{message}. The {len(retrieved)} dataset(s) already retrieved are kept in the "
            f"envelope and are real; the queries never sent may hold more."
        )
    else:
        note = (
            f"The OpenGWAS request failed before anything was retrieved, so this side of "
            f"the pair has no retrieved evidence either way: {message}"
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


def get_mqtl_instruments(metabolite_synonyms: list, max_datasets: int = 6) -> dict:
    """Find the OpenGWAS datasets that measure this metabolite and count their genetic
    instruments, to answer "could an MR be run for this pair?".

    Give it 1A's metabolite synonym list (display strings, any case). They are
    exact-matched against the cached gwasinfo trait strings; every matched dataset is
    kept except plain case/control studies (the met- prefix is NOT the filter - urate's
    largest dataset is ieu-b-5137), the largest `max_datasets` by sample size are
    queried, and each one reports platform, unit, sample_size, population, year, build,
    its count of LD-clumped genome-wide significant loci (`gws_hits`), how many of them
    are weak (F < 10) and up to five example hits.

    `status` is "empty" when no dataset is named by those synonyms, or when every
    queried dataset returned zero hits - the caveats say which. Empty means "not in this
    release" or "no clumped hit at p < 5e-8", NEVER "no genetic basis" and never "no
    effect". Nothing here is an MR estimate. Needs OPENGWAS_JWT; without it the envelope
    is a clean error saying so.
    """
    args = {
        "metabolite_synonyms": _as_list(metabolite_synonyms),
        "max_datasets":        max_datasets,
    }
    data = {
        "exposures":         [],
        "n_exposures":       0,
        "matched_datasets":  0,
        "dropped_datasets":  [],
        "queries":           [],
    }
    caveats = [RETRIEVED_CAVEAT, CACHE_CAVEAT]
    planned = None

    try:
        if not _token():
            return _no_token_envelope(
                "get_mqtl_instruments",
                args,
                data,
                caveats,
            )

        vocabulary = _traits.load_vocabulary("opengwas")
        matches = _traits.match_datasets(args["metabolite_synonyms"], vocabulary)
        data["matched_datasets"] = len(matches)

        candidates = []
        for row in matches:
            identifier = str(row.get("id") or "")
            if identifier.startswith("met-") or not _is_case_control(row):
                candidates.append(row)
            else:
                data["dropped_datasets"].append({
                    "id":     identifier,
                    "trait":  row.get("trait"),
                    "reason": (
                        f"case/control study (category {row.get('category')!r}, "
                        f"ncontrol {row.get('ncontrol')!r}), not a measurement of the "
                        f"metabolite"
                    ),
                })

        if not candidates:
            if matches:
                caveats.append(
                    f"All {len(matches)} dataset(s) named by these synonyms are "
                    f"case/control studies, not measurements of the metabolite: "
                    f"{', '.join(row['id'] for row in data['dropped_datasets'])}. No "
                    f"tophits request was sent."
                )
            else:
                caveats.append(
                    f"No dataset in this OpenGWAS release is named by any of the "
                    f"{len(args['metabolite_synonyms'])} metabolite synonym(s), so no "
                    f"tophits request was sent. The metabolite may simply never have been "
                    f"measured in a published GWAS - Nightingale NMR and Metabolon panels "
                    f"between them cover a few hundred metabolites, not the metabolome."
                )
            caveats.append(EMPTY_CAVEAT)
            return _record(_common.envelope(
                tool    = "get_mqtl_instruments",
                args    = args,
                source  = SOURCE,
                url     = "",
                status  = "empty",
                data    = data,
                caveats = caveats,
            ))

        if data["dropped_datasets"]:
            caveats.append(
                f"Dropped {len(data['dropped_datasets'])} of {len(matches)} matched "
                f"dataset(s) as case/control studies rather than measurements: "
                f"{', '.join(row['id'] for row in data['dropped_datasets'])}. Everything "
                f"else was kept regardless of its id prefix."
            )

        candidates.sort(key=_size_key)
        cap = max(1, int(max_datasets))
        if len(candidates) > cap:
            dropped = candidates[cap:]
            caveats.append(
                f"Capped: {len(candidates)} dataset(s) measure this metabolite, only the "
                f"{cap} largest by sample size were queried "
                f"({', '.join(row['id'] for row in candidates[:cap])}); not queried: "
                f"{', '.join(row['id'] for row in dropped)}. Raise max_datasets to see them."
            )
            candidates = candidates[:cap]

        planned = len(candidates)

        # Seeded BEFORE the first request, not after the loop: these three are
        # unconditional statements about what the fields mean, and a mid-sweep failure
        # keeps the exposures already retrieved. An error envelope carrying gws_hits,
        # min_f and an inferred platform with none of them explained is worse than the
        # failure itself.
        caveats.extend([PLATFORM_CAVEAT, CLUMP_CAVEAT, F_CAVEAT])

        exposures = data["exposures"]
        p_zero_ids = []
        no_f = 0
        for row in candidates:
            identifier = str(row.get("id") or "")
            hits, sent_url = _query_tophits(identifier)
            data["queries"].append(sent_url)

            parsed = [_hit(hit) for hit in hits]
            parsed.sort(key=_p_sort_key)
            f_values = [hit["f"] for hit in parsed if hit["f"] is not None]
            no_f += len(parsed) - len(f_values)
            if any(hit["p"] == 0 for hit in parsed):
                p_zero_ids.append(identifier)

            exposures.append({
                "id":               identifier,
                "trait":            row.get("trait"),
                "matched_synonym":  row.get("matched_synonym"),
                "platform":         _platform(identifier),
                "batch":            _batch(identifier),
                "unit":             _text(row.get("unit")),
                "sample_size":      _count(row.get("sample_size")),
                "n":                _count(row.get("sample_size")),
                "population":       _text(row.get("population")),
                # Without sex and note, ieu-a-786/787/788 are byte-identical apart from
                # the id - and their note says all three are BMI-by-SNP interaction
                # scans, i.e. the betas are not main-effect urate associations at all.
                "sex":              _text(row.get("sex")),
                "note":             _text(row.get("note")),
                "year":             _count(row.get("year")),
                "build":            _text(row.get("build")),
                "author":           _text(row.get("author")),
                "consortium":       _text(row.get("consortium")),
                "category":         _text(row.get("category")),
                "subcategory":      _text(row.get("subcategory")),
                "gws_hits":         len(parsed),
                "weak_instruments": sum(1 for value in f_values if value < WEAK_INSTRUMENT_F),
                "min_f":            min(f_values) if f_values else None,
                "max_f":            max(f_values) if f_values else None,
                "example_hits":     parsed[:MAX_EXAMPLE_HITS],
            })
            data["n_exposures"] = len(exposures)

        with_hits = [exposure for exposure in exposures if exposure["gws_hits"] > 0]
        if len(exposures) > 1:
            caveats.append(_scale_caveat(exposures))

        strata = [
            exposure for exposure in exposures
            if (exposure["sex"] and exposure["sex"] != "Males and Females")
            or "interaction" in (exposure["note"] or "").lower()
        ]
        if strata:
            described = "; ".join(
                f"{exposure['id']} (sex {exposure['sex']!r}, note {exposure['note']!r})"
                for exposure in strata
            )
            caveats.append(f"{STRATUM_CAVEAT} In this envelope: {described}.")

        uk_biobank = [exposure["id"] for exposure in exposures if _is_uk_biobank(exposure["id"])]
        if uk_biobank:
            caveats.append(
                f"{', '.join(uk_biobank)} is drawn from UK Biobank, and most large modern "
                f"outcome GWAS include UK Biobank too. {OVERLAP_CAVEAT}"
            )

        damaged = _encoding_damaged(exposures)
        if damaged:
            caveats.append(ENCODING_TEMPLATE.format(ids=", ".join(damaged)))

        if any(exposure["gws_hits"] > MAX_EXAMPLE_HITS for exposure in exposures):
            caveats.append(
                f"example_hits is the {MAX_EXAMPLE_HITS} strongest hits by p-value per "
                f"dataset, not the whole instrument set; gws_hits is the full count."
            )
        if no_f:
            caveats.append(
                f"{no_f} retrieved hit(s) carry no usable se, so they have no F and are "
                f"counted in gws_hits but not in weak_instruments, min_f or max_f."
            )
        if p_zero_ids:
            caveats.append(PVAL_ZERO_TEMPLATE.format(ids=", ".join(p_zero_ids)))
        caveats.append(ZERO_HITS_CAVEAT)

        if not with_hits:
            caveats.append(
                f"All {len(exposures)} queried dataset(s) "
                f"({', '.join(exposure['id'] for exposure in exposures)}) returned zero "
                f"LD-clumped hits at p < {TOPHITS_PVAL}. The datasets exist and were "
                f"reached; they carry no instrument strong enough at that threshold, which "
                f"is a fact about their power, not about the biology."
            )
            caveats.append(EMPTY_CAVEAT)

        return _record(_common.envelope(
            tool    = "get_mqtl_instruments",
            args    = args,
            source  = SOURCE,
            url     = data["queries"][0] if data["queries"] else "",
            status  = "ok" if with_hits else "empty",
            data    = data,
            caveats = caveats,
        ))

    except _HANDLED as exc:
        return _failure(
            "get_mqtl_instruments",
            args,
            data,
            caveats,
            exc,
            planned,
        )
    except Exception as exc:                           # nothing escapes a tool
        return _failure(
            "get_mqtl_instruments",
            args,
            data,
            caveats,
            exc,
            planned,
        )


def find_outcome_datasets(disease_synonyms: list, top_n: int = 3) -> dict:
    """Find candidate outcome GWAS in OpenGWAS for a disease, sized datasets from the
    curated repositories first.

    Give it 1A's disease synonym list. They are exact-matched against the cached
    gwasinfo trait strings and met-* metabolite batches are excluded; the remaining
    datasets are ranked - those with a recorded sample_size first, then the curated
    repositories (ebi-, ieu-, finn-) ahead of the rest, then sample size descending -
    and the top `top_n` are returned with id, trait, sample_size, ncase, ncontrol,
    population, sex, note, pmid, year, author/consortium and genome build. The ranking
    is stated in a caveat, because it is not a pure size ordering.

    Caveats flag what a card must not print unchecked: two deposits of one publication
    (matching pmid), counts that cannot all be true (ncase + ncontrol far from
    sample_size), sex strata and interaction scans, the source's own broken author
    encodings, and the sample overlap this tool cannot check because it sees only the
    outcome side.

    `status` is "empty" when no dataset is named by those synonyms - which means "not
    in this release", never "this disease has no GWAS". Reads the local gwasinfo cache,
    so it sends no request and needs no token; the caveats name every dataset the cap
    dropped, because one disease can match two dozen (type 2 diabetes matches 24).
    """
    args = {
        "disease_synonyms": _as_list(disease_synonyms),
        "top_n":            top_n,
    }
    data = {
        "datasets":             [],
        "n_datasets":           0,
        "n_matched_before_cap": 0,
        "queries":              [],
    }
    caveats = [RETRIEVED_CAVEAT, CACHE_CAVEAT]

    try:
        vocabulary = _traits.load_vocabulary("opengwas")
        matches = _traits.match_datasets(args["disease_synonyms"], vocabulary)

        metabolite_batches, candidates = [], []
        for row in matches:
            is_batch = str(row.get("id") or "").startswith("met-")
            (metabolite_batches if is_batch else candidates).append(row)
        data["n_matched_before_cap"] = len(candidates)

        if metabolite_batches:
            caveats.append(
                f"Excluded {len(metabolite_batches)} met-* metabolite dataset(s) "
                f"({', '.join(row['id'] for row in metabolite_batches)}): this tool looks "
                f"for OUTCOME GWAS, and a metabolite panel is not one."
            )

        if not candidates:
            caveats.append(
                f"No outcome dataset in this OpenGWAS release is named by any of the "
                f"{len(args['disease_synonyms'])} disease synonym(s). Matching is exact on "
                f"the source's own trait spelling, so a disease studied under a name none "
                f"of the synonyms carries will look absent here."
            )
            caveats.append(EMPTY_CAVEAT)
            return _record(_common.envelope(
                tool    = "find_outcome_datasets",
                args    = args,
                source  = SOURCE,
                # Nothing was sent: the index is read from the local cache.
                url     = "",
                status  = "empty",
                data    = data,
                caveats = caveats,
            ))

        matched_traits = sorted({row["trait"] for row in candidates if row.get("trait")})
        if len(matched_traits) > 1:
            caveats.append(
                f"These synonyms matched {len(matched_traits)} different trait spellings "
                f"({', '.join(repr(trait) for trait in matched_traits)}); matching is exact "
                f"after casefolding, so a spelling no synonym carries was never reachable."
            )

        candidates.sort(key=_outcome_key)
        caveats.append(
            "Ranking: datasets with a recorded sample_size first, then the curated "
            "repositories (ebi-, ieu-, finn-) ahead of the rest, then sample size "
            "descending. So this list is not a pure size ranking - a large dataset from "
            "another batch can sit below a smaller curated one - and the datasets gwasinfo "
            "records no sample_size for (every finn-b row) come last however big they are."
        )

        cap = max(1, int(top_n))
        if len(candidates) > cap:
            caveats.append(
                f"Capped: {len(candidates)} outcome dataset(s) match these synonyms, only "
                f"the top {cap} are returned "
                f"({', '.join(row['id'] for row in candidates[:cap])}); not returned: "
                f"{', '.join(row['id'] for row in candidates[cap:])}. Raise top_n to see them."
            )
            candidates = candidates[:cap]

        for row in candidates:
            identifier = str(row.get("id") or "")
            data["datasets"].append({
                "id":              identifier,
                "trait":           row.get("trait"),
                "matched_synonym": row.get("matched_synonym"),
                "batch":           _batch(identifier),
                "sample_size":     _count(row.get("sample_size")),
                "n":               _count(row.get("sample_size")),
                "ncase":           _count(row.get("ncase")),
                "ncontrol":        _count(row.get("ncontrol")),
                "population":      _text(row.get("population")),
                "sex":             _text(row.get("sex")),
                "note":            _text(row.get("note")),
                "year":            _count(row.get("year")),
                "pmid":            _count(row.get("pmid")),
                "author":          _text(row.get("author")),
                "consortium":      _text(row.get("consortium")),
                "build":           _text(row.get("build")),
                "category":        _text(row.get("category")),
                "subcategory":     _text(row.get("subcategory")),
            })
        data["n_datasets"] = len(data["datasets"])

        duplicates = {}
        for row in data["datasets"]:
            key = (row["sample_size"], row["ncase"], row["ncontrol"])
            if key != (None, None, None):
                duplicates.setdefault(key, []).append(row["id"])
        repeated = [ids for ids in duplicates.values() if len(ids) > 1]
        if repeated:
            caveats.append(
                "Some of these are the SAME study deposited under more than one id "
                f"({'; '.join(' = '.join(ids) for ids in repeated)}): identical n, ncase "
                "and ncontrol. Count them once."
            )

        # The count triple cannot see two deposits of one paper that report different
        # analyses: ebi-a-GCST005195 and ebi-a-GCST005194 are both van der Harst 2017
        # (PMID 29212778) and the second is a stage of the first, so n differs.
        by_pmid = {}
        for row in data["datasets"]:
            if row["pmid"] is not None:
                by_pmid.setdefault(row["pmid"], []).append(row["id"])
        shared = [
            f"{' and '.join(ids)} (PMID {pmid})"
            for pmid, ids in by_pmid.items()
            if len(ids) > 1
        ]
        if shared:
            caveats.append(SAME_PUBLICATION_TEMPLATE.format(groups="; ".join(shared)))

        mismatched = _count_mismatches(data["datasets"])
        if mismatched:
            caveats.append(COUNT_MISMATCH_TEMPLATE.format(details="; ".join(mismatched)))

        uk_biobank = [row["id"] for row in data["datasets"] if _is_uk_biobank(row["id"])]
        large = [
            row["id"] for row in data["datasets"]
            if row["id"] not in uk_biobank
            and row["sample_size"] is not None
            and row["sample_size"] >= _OVERLAP_SIZE_HINT
        ]
        if uk_biobank or large:
            named = ", ".join(uk_biobank + large)
            caveats.append(
                f"{named}: a UK Biobank deposit or a meta-analysis large enough "
                f"(>= {_OVERLAP_SIZE_HINT:,}) that it very likely contains UK Biobank. "
                f"gwasinfo records no cohort list, so this is a size-based flag, not a "
                f"verified overlap. {OVERLAP_CAVEAT}"
            )

        damaged = _encoding_damaged(data["datasets"])
        if damaged:
            caveats.append(ENCODING_TEMPLATE.format(ids=", ".join(damaged)))

        strata = [
            row for row in data["datasets"]
            if (row["sex"] and row["sex"] != "Males and Females")
            or "interaction" in (row["note"] or "").lower()
        ]
        if strata:
            described = "; ".join(
                f"{row['id']} (sex {row['sex']!r}, note {row['note']!r})" for row in strata
            )
            caveats.append(f"{STRATUM_CAVEAT} In this envelope: {described}.")

        unknown_population = [row["id"] for row in data["datasets"] if row["population"] is None]
        if unknown_population:
            caveats.append(
                f"gwasinfo records no population for {', '.join(unknown_population)} (it "
                f"writes the literal \"NA\"), so the ancestry match against the exposure "
                f"cannot be checked for those datasets from this envelope alone."
            )

        caveats.extend([NCASE_CAVEAT, POPULATION_CAVEAT])

        return _record(_common.envelope(
            tool    = "find_outcome_datasets",
            args    = args,
            source  = SOURCE,
            url     = "",
            status  = "ok",
            data    = data,
            caveats = caveats,
        ))

    except _HANDLED as exc:
        return _failure(
            "find_outcome_datasets",
            args,
            data,
            caveats,
            exc,
            None,
        )
    except Exception as exc:
        return _failure(
            "find_outcome_datasets",
            args,
            data,
            caveats,
            exc,
            None,
        )


if __name__ == "__main__":
    import json

    def show_exposures(env):
        print(f"  status           : {env['status']}")
        print(f"  url              : {env['url']}")
        print(f"  queries sent     : {len(env['data'].get('queries', []))}")
        print(f"  matched_datasets : {env['data'].get('matched_datasets')}")
        print(f"  n_exposures      : {env['data'].get('n_exposures')}")
        for exposure in env["data"].get("exposures", []):
            print(f"    {exposure['id']:<18} n={exposure['sample_size']!s:<8} "
                  f"{exposure['platform']!s:<38} unit={exposure['unit']!r:<16} "
                  f"hits={exposure['gws_hits']:<4} weak={exposure['weak_instruments']}")
            if exposure["min_f"] is not None:
                print(f"      F {exposure['min_f']:.1f} .. {exposure['max_f']:.1f}   "
                      f"pop={exposure['population']} year={exposure['year']}")
            if exposure["sex"] and exposure["sex"] != "Males and Females":
                print(f"      sex={exposure['sex']!r}")
            if exposure["note"]:
                print(f"      note={exposure['note']!r}")
            for hit in exposure["example_hits"][:2]:
                print(f"      {hit['rsid']} chr{hit['chr']}:{hit['position']} "
                      f"beta={hit['beta']:+g} se={hit['se']:g} p={hit['p']:g} "
                      f"F={hit['f']:.1f}")
        for caveat in env["caveats"]:
            print(f"  caveat           : {caveat}")

    def show_datasets(env):
        print(f"  status           : {env['status']}")
        print(f"  matched (pre-cap): {env['data'].get('n_matched_before_cap')}")
        print(f"  n_datasets       : {env['data'].get('n_datasets')}")
        for dataset in env["data"].get("datasets", []):
            print(f"    {dataset['id']:<20} n={dataset['sample_size']!s:<8} "
                  f"ncase={dataset['ncase']!s:<8} ncontrol={dataset['ncontrol']!s:<8} "
                  f"{dataset['population']} {dataset['year']} pmid={dataset['pmid']} "
                  f"{dataset['author']}")
        for caveat in env["caveats"]:
            print(f"  caveat           : {caveat}")

    if not _token():
        print(f"{JWT_ENV_VAR} is absent, so the live half of this self-test cannot run.")
        print("Put the token in the .env above the repo root (see .env.example).")
        print("\nThe no-token path still returns a clean envelope:")
        show_exposures(get_mqtl_instruments(["glycine"]))
        sys.exit(0)

    print(f"{JWT_ENV_VAR} present ({len(_token())} chars); the value is never printed.\n")

    print("1) glycine instruments - two platforms, one trait string")
    show_exposures(get_mqtl_instruments(
        ["glycine", "Gly", "aminoacetic acid"],
        max_datasets = 6,
    ))

    print("\n2) coronary artery disease outcome datasets")
    show_datasets(find_outcome_datasets(
        ["coronary artery disease", "coronary heart disease", "CAD"],
        top_n = 3,
    ))

    print("\n3) a metabolite nobody named that way")
    show_exposures(get_mqtl_instruments(["zzqx-not-a-metabolite"]))

    print("\n4) urate - the pair where a met- prefix filter would drop 21 of 22 datasets")
    urate = get_mqtl_instruments(
        ["urate", "URIC ACID"],
        max_datasets = 3,
    )
    show_exposures(urate)
    print("  ids kept:", [exposure["id"] for exposure in urate["data"]["exposures"]])
    print("  of which met-*:",
          [exposure["id"] for exposure in urate["data"]["exposures"]
           if exposure["id"].startswith("met-")])

    print("\n5) the envelope, verbatim (first exposure only)")
    trimmed = {**urate, "data": {**urate["data"], "exposures": urate["data"]["exposures"][:1]}}
    print(json.dumps(
        trimmed,
        indent       = 2,
        ensure_ascii = False,
    )[:1800])
