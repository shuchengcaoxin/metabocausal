"""1C supplement: curated GWAS Catalog associations and mapped genes for one trait.

The GWAS Catalog is EBI's hand-curated index of published GWAS hits: trait-variant
ASSOCIATIONS, one row per reported signal, with the paper's own effect number. It is
not an MR resource and holds no causal estimate, so nothing this module returns may
be written as "X causes Y". What it is good for is the other half of 1C's job -
naming the loci and the genes at them, which is where 1D starts.

No key needed. Every public function returns the shared 8-key envelope and records it
in the ledger before returning, on every path including failure.

HOW A TRAIT BECOMES A QUERY, AND WHY THE ONTOLOGY ID IS THE GOOD PATH
--------------------------------------------------------------------
Unlike EpiGraphDB and OpenGWAS, this resource is keyed by an ontology term, so 1A's
id reaches it directly: `MONDO:0005393` -> `MONDO_0005393`, the `shortForm` the REST
API uses. Prefer that. The trait-name fallback is an EXACT (case-insensitive) label
match despite living under `/search/`: measured 2026-09-10, "gout" / "Gout" / "GOUT"
all resolve, and "glycine", "coronary artery disease" and "type 2 diabetes" all
resolve to NOTHING. Two consequences a caller has to know:

  - A metabolite is named as a MEASUREMENT here. "glycine" resolves to nothing;
    "glycine measurement" is EFO_0009767, "urate measurement" is EFO_0004531. This
    module does not append that word for you - inventing spellings is exactly what
    the 1A/1B contract forbids - it says so in the caveats and returns empty.
  - The Catalog has moved many terms from EFO to MONDO. EFO_0001645 (coronary artery
    disease) and EFO_0001360 (type 2 diabetes mellitus) both 404 here; the live terms
    are MONDO_0005010 "coronary artery disorder" and MONDO_0005148. So a 404 on an
    ontology id is not "the trait does not exist" - the module falls back to the name
    search and says which path answered.

WHY THIS MODULE STREAMS ITS BIG REQUEST INSTEAD OF USING _common.get_json
-------------------------------------------------------------------------
The associations endpoint ignores `size` and `page` (measured: with and without
size=5&page=0 it returns the identical 575 rows in the identical 41 s, and the `page`
block comes back null), so there is no pagination and the whole set transfers every
time. It is slow in a way an ordinary timeout cannot bound: for urate measurement,
time to first byte was 3.5 s and the remaining 10.4 MB dribbled out over 364 s with a
maximum gap between chunks of 3.1 s. `requests`' timeout is a per-read gap, not a
wall clock, so `_common.get_json(timeout=120)` would sit there for six minutes and
never fire. The pipeline must not hang, so this one call streams through
`_fetch_within_deadline` and aborts at a real elapsed-time deadline. Everything else
here - trait resolution, the SNP endpoint - is small and fast and goes through
`_common.get_json` like every other tool in the project.

THE BETA THE CATALOG GIVES YOU IS UNSIGNED
------------------------------------------
`betaNum` is a magnitude and the sign lives in `betaDirection`. Measured 2026-09-10 on
rs1047891: 0 of 566 betaNum values are negative, while 255 of them say "decrease". A
consumer reading `beta` alone reports the wrong direction on roughly 45% of rows, so
`beta_signed` is derived here beside the source's own two fields and a caveat says so.

MEASURED SIZES, 2026-09-10 (so a reader knows what "slow" means)
  MONDO_0005393  gout                 1,420 associations   3.0 MB   113 s
  EFO_0009767    glycine measurement    575 associations   1.3 MB    41 s
  EFO_0004531    urate measurement    4,588 associations  10.4 MB   364 s  <- deadline
A deadline hit is an `error` envelope saying the resource was too slow. It is never
"this trait has no associations".
"""

from __future__ import annotations

import http.client
import json
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from . import _common
except ImportError:                                    # running: python tools/gwascat.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _common

import ledger

SOURCE = "GWAS Catalog (EBI) REST API"
BASE_URL = "https://www.ebi.ac.uk/gwas/rest/api"
TRAIT_SEARCH_URL = f"{BASE_URL}/efoTraits/search/findByEfoTrait"
TRAIT_URL = BASE_URL + "/efoTraits/{short_form}"
ASSOCIATIONS_URL = BASE_URL + "/efoTraits/{short_form}/associations"
SNP_URL = BASE_URL + "/singleNucleotidePolymorphisms/{variant}"

# Small calls: the shared HTTP path, one retry. The big call: a real elapsed-time
# deadline and NO retry - one attempt already costs up to two minutes and a second
# would double the pipeline's worst case for a resource that is only supplementary.
FAST_TIMEOUT_SECONDS = 30
ASSOCIATIONS_DEADLINE_SECONDS = 120
MAX_GENES_FROM_LIMIT = 10

_STREAM_CHUNK_BYTES = 65536
_SESSION = requests.Session()

_HANDLED = (_common.RequestFailed, OSError, ValueError, http.client.HTTPException)

ASSOCIATION_CAVEAT = (
    "GWAS Catalog rows are curated trait-variant ASSOCIATIONS from published GWAS, "
    "not causal estimates: no MR, no instrument, no direction of causation. An odds "
    "ratio or beta here is the reported marginal association of one variant with the "
    "trait in that study's own scale and ancestry. Retrieved, not computed."
)
NO_PAGINATION_CAVEAT = (
    "This endpoint ignores `size` and `page` (measured 2026-09-10: identical 575 rows "
    "with and without size=5&page=0, `page` block null), so the full association set "
    "for the trait is transferred on every call and any cap below is applied here, "
    "after download, not by the server."
)
SLOW_RESOURCE_CAVEAT = (
    f"The associations endpoint is slow and cannot be paged: measured 2026-09-10, gout "
    f"took 113 s for 3.0 MB / 1,420 rows and urate measurement 364 s for 10.4 MB / "
    f"4,588 rows, dribbled out in small chunks so an ordinary read timeout never fires. "
    f"This call therefore aborts at a {ASSOCIATIONS_DEADLINE_SECONDS} s wall-clock "
    f"deadline with an error envelope rather than hanging the pipeline. A deadline hit "
    f"is a limit of the resource, NEVER evidence that the trait has no associations."
)
BETA_SIGN_CAVEAT = (
    "beta is the Catalog's own betaNum, which is an UNSIGNED MAGNITUDE - the direction "
    "lives in beta_direction (\"increase\" / \"decrease\"). Measured 2026-09-10 on "
    "rs1047891: 0 of 566 betaNum values are negative while 255 of them are \"decrease\". "
    "Reading beta alone gets the sign wrong on roughly 45% of rows. beta_signed is "
    "derived here for convenience (beta with the direction applied, null when the "
    "direction is missing); beta and beta_direction are the source's own fields."
)
GENE_DISTANCE_TEMPLATE = (
    "No distance cutoff was applied to mapped genes: rows span {low:,} to {high:,} bp "
    "from their variant ({at_zero} row(s) at distance 0) and include pseudogenes - "
    "rs1165151 returns histone pseudogenes out to 94,826 bp. Sort by distance and state "
    "the range before calling any of these an effector gene. Reported, not filtered."
)
CLOSEST_GENE_CAVEAT = (
    "`is_closest_gene` is the source's own per-source, per-direction flag (nearest "
    "upstream and nearest downstream, once for NCBI and once for Ensembl), so several "
    "genes carry it at one variant and the gene the variant sits INSIDE need not: at "
    "rs1165151 SLC17A1 is distance 0 with is_intergenic false and is_closest_gene "
    "false, while SLC17A3, SLC17A4 and LOC124901285 are all flagged closest. Do not "
    "read it as \"the\" nearest gene."
)
TWO_SOURCES_CAVEAT = (
    "Mapped genes are listed once per annotation source, and the two sources disagree "
    "about distance (rs1165151 SLC17A3: 11,678 bp per Ensembl, 23,468 bp per NCBI). "
    "Both rows are kept exactly as retrieved, so the row count is not a gene count."
)
NOT_REPORTED_CAVEAT = (
    "{count} of the kept association(s) give the author-reported gene as \"NR\", which "
    "means the paper named no gene at that locus. Those entries are kept verbatim and "
    "are counted below as carrying an entry; NR is not a gene called NR."
)
PVAL_ZERO_CAVEAT = (
    "p-values reported as exactly 0 underflowed double precision in the source; the "
    "true exponent survives in pvalue_mantissa / pvalue_exponent (gout's strongest row "
    "is 1e-1421). Render those as \"p ~ {mantissa}e{exponent} (reported 0)\", never as "
    "p = 0, and note that ranking uses the mantissa/exponent pair for exactly this "
    "reason - sorting on the float would tie every underflowed row at the top."
)
EMPTY_CAVEAT = (
    "Empty is not evidence of no association - it means no curated GWAS Catalog row "
    "was retrieved under this trait term, which is a fact about this resource's "
    "curation and naming, not about biology."
)
METABOLITE_NAMING_CAVEAT = (
    "GWAS Catalog names a metabolite trait as a measurement: \"glycine measurement\" "
    "(EFO_0009767) and \"urate measurement\" (EFO_0004531) resolve, while \"glycine\" "
    "and \"urate\" resolve to nothing. This tool does not append that word for you - "
    "call it again with the measurement label, or with the EFO id of the measurement."
)
ONTOLOGY_MOVED_CAVEAT = (
    "The Catalog has migrated many terms from EFO to MONDO, so an id 1A resolved "
    "against OLS can 404 here (EFO_0001645 coronary artery disease and EFO_0001360 "
    "type 2 diabetes mellitus both 404; the live terms are MONDO_0005010 \"coronary "
    "artery disorder\" and MONDO_0005148). A 404 on the id is not a missing trait."
)


def _record(env: dict) -> dict:
    ledger.record(env)
    return env


def _as_text(value) -> str:
    # A model calling this tool sends ["gout"] where the signature says a string often
    # enough to be worth handling: str(["gout"]) would be queried verbatim and come
    # back with an honest-looking "no such trait".
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value).strip()


def _as_int(
    value,
    fallback: int,
    minimum:  int = 1,
) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if number >= minimum else fallback


def _short_form(ontology_id) -> str:
    """1A's id in this API's spelling: `MONDO:0005393` -> `MONDO_0005393`. A full
    purl URI is accepted too, since that is what the API itself hands back."""
    text = _as_text(ontology_id)
    if not text:
        return ""
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text.replace(":", "_")


def _fetch_within_deadline(url: str, deadline_seconds: int):
    """One streamed GET, aborted at a real elapsed-time deadline. See the module
    docstring: the associations body arrives in small chunks over minutes, so a
    per-read timeout cannot bound it and `_common.get_json` cannot be used here.

    Returns `(payload, url_actually_sent)`; raises `_common.RequestFailed`.
    """
    request = requests.Request(
        method  = "GET",
        url     = url,
        headers = {"Accept": "application/json"},
    )
    prepared = _SESSION.prepare_request(request)
    final_url = prepared.url

    # Same reason as _common.get_json: Session.send() skips merge_environment_settings,
    # and behind a TLS-intercepting corporate proxy REQUESTS_CA_BUNDLE is the only way
    # out. `stream` goes in as the third argument because the merged dict carries it
    # back out - passing it to send() as well would be a duplicate keyword.
    environment = _SESSION.merge_environment_settings(
        final_url,
        {},
        True,
        None,
        None,
    )

    started = time.monotonic()
    try:
        response = _SESSION.send(
            prepared,
            timeout = FAST_TIMEOUT_SECONDS,
            **environment,
        )
    except requests.RequestException as exc:
        raise _common.RequestFailed(
            f"GET {final_url} failed: {exc}",
            url = final_url,
        ) from exc

    try:
        if response.status_code >= 400:
            raise _common.RequestFailed(
                f"HTTP {response.status_code} from {final_url}",
                status_code = response.status_code,
                url         = final_url,
            )

        chunks, size = [], 0
        try:
            for chunk in response.iter_content(_STREAM_CHUNK_BYTES):
                chunks.append(chunk)
                size += len(chunk)
                elapsed = time.monotonic() - started
                if elapsed > deadline_seconds:
                    raise _common.RequestFailed(
                        f"GET {final_url} exceeded the {deadline_seconds}s wall-clock "
                        f"deadline after {elapsed:.0f}s and {size} bytes; the response "
                        f"was still arriving. Partial JSON cannot be parsed, so nothing "
                        f"was retrieved.",
                        url = final_url,
                    )
        except requests.RequestException as exc:
            raise _common.RequestFailed(
                f"GET {final_url} broke off after {size} bytes: {exc}",
                url = final_url,
            ) from exc
    finally:
        response.close()

    try:
        return json.loads(b"".join(chunks).decode("utf-8")), final_url
    except (ValueError, UnicodeDecodeError) as exc:
        raise _common.RequestFailed(
            f"{final_url} returned non-JSON: {exc}",
            url = final_url,
        ) from exc


def _embedded(payload, key: str) -> list:
    block = (payload or {}).get("_embedded") or {}
    rows = block.get(key)
    return list(rows) if isinstance(rows, list) else []


def _resolve_by_id(
    short_form: str,
    data:       dict,
    caveats:    list,
):
    """GET /efoTraits/{shortForm}. Returns the trait label, or None on a 404."""
    url = TRAIT_URL.format(short_form=short_form)
    try:
        payload, sent_url = _common.get_json(
            url,
            timeout = FAST_TIMEOUT_SECONDS,
        )
    except _common.RequestFailed as exc:
        data["queries"].append(getattr(
            exc,
            "url",
            None,
        ) or url)
        if exc.status_code == 404:
            caveats.append(
                f"{short_form} is not a GWAS Catalog trait (HTTP 404); falling back to "
                f"the trait-name search. {ONTOLOGY_MOVED_CAVEAT}"
            )
            return None
        raise
    data["queries"].append(sent_url)
    return payload.get("trait") if isinstance(payload, dict) else None


def _resolve_by_name(
    trait_label: str,
    data:        dict,
    caveats:     list,
):
    """GET /efoTraits/search/findByEfoTrait. An EXACT case-insensitive label match
    despite the path; returns `(short_form, trait)` or `(None, None)`."""
    payload, sent_url = _common.get_json(
        TRAIT_SEARCH_URL,
        params  = {"trait": trait_label},
        timeout = FAST_TIMEOUT_SECONDS,
    )
    data["queries"].append(sent_url)

    traits = _embedded(payload, "efoTraits")
    if not traits:
        return None, None

    chosen = traits[0]
    for row in traits:
        if _common.normalize(row.get("trait")) == _common.normalize(trait_label):
            chosen = row
            break
    if len(traits) > 1:
        others = ", ".join(f"{row.get('trait')} ({row.get('shortForm')})" for row in traits[1:6])
        caveats.append(
            f"The name search returned {len(traits)} traits; used "
            f"{chosen.get('trait')} ({chosen.get('shortForm')}). Others: {others}."
        )
    return chosen.get("shortForm"), chosen.get("trait")


def _pvalue_key(association: dict) -> tuple:
    """Strongest first, from the mantissa/exponent pair rather than the float.

    5 of gout's 1,420 rows report pvalue exactly 0.0 - underflow - while their
    exponents are -324, -775, -968, -1400 and -1421. Sorting on the float ties all
    five and then loses the true strongest to whatever order the source used.
    """
    mantissa = association.get("pvalue_mantissa")
    exponent = association.get("pvalue_exponent")
    if isinstance(exponent, (int, float)) and isinstance(mantissa, (int, float)):
        return (0, float(exponent), float(mantissa))

    pvalue = association.get("pvalue")
    if isinstance(pvalue, (int, float)) and pvalue > 0:
        mantissa_text, _, exponent_text = f"{pvalue:e}".partition("e")
        return (0, float(exponent_text), float(mantissa_text))
    return (1, 0.0, 0.0)                               # no usable p-value: sorted last


def _risk_alleles(raw: dict) -> list:
    names = []
    for locus in raw.get("loci") or []:
        for allele in locus.get("strongestRiskAlleles") or []:
            name = allele.get("riskAlleleName")
            if name:
                names.append(name)
    return names


def _split_risk_allele(name: str) -> tuple:
    """`rs2199936-A` -> `("rs2199936", "A")`. The variant is not always an rsid: the
    Catalog also writes `chr4:88887327-A` and `c.1580C>G-G`, and the allele is
    sometimes `?`. Whatever it is, it is returned as the source wrote it."""
    variant, separator, allele = str(name).rpartition("-")
    if not separator:
        return str(name), None
    return variant, (allele or None)


def _author_genes(raw: dict) -> list:
    genes = []
    for locus in raw.get("loci") or []:
        for gene in locus.get("authorReportedGenes") or []:
            name = gene.get("geneName")
            if name and name not in genes:
                genes.append(name)
    return genes


def _signed_beta(raw: dict):
    """betaNum with betaDirection applied, or None. The Catalog stores the magnitude and
    the direction in two fields; a consumer reading only `beta` would report an increase
    for every one of the 255-in-566 rows that decrease."""
    beta = raw.get("betaNum")
    if not isinstance(beta, (int, float)) or isinstance(beta, bool):
        return None
    direction = str(raw.get("betaDirection") or "").strip().lower()
    if direction == "decrease":
        return -abs(float(beta))
    if direction == "increase":
        return abs(float(beta))
    return None


def _association(raw: dict) -> dict:
    names = _risk_alleles(raw)
    variant, allele = _split_risk_allele(names[0]) if names else (None, None)
    return {
        "rsid":             variant,
        "risk_allele":      allele,
        "risk_alleles":     names,
        "pvalue":           raw.get("pvalue"),
        "pvalue_mantissa":  raw.get("pvalueMantissa"),
        "pvalue_exponent":  raw.get("pvalueExponent"),
        "or_per_copy":      raw.get("orPerCopyNum"),
        "beta":             raw.get("betaNum"),
        "beta_signed":      _signed_beta(raw),
        "beta_unit":        raw.get("betaUnit"),
        "beta_direction":   raw.get("betaDirection"),
        "standard_error":   raw.get("standardError"),
        "author_reported_genes": _author_genes(raw),
    }


def _genomic_contexts(variant: str, data: dict) -> list:
    """The SNP resource's genomicContexts, flattened. Mapped genes are NOT on the
    association object, which is why this costs one request per variant."""
    url = SNP_URL.format(variant=variant)
    try:
        payload, sent_url = _common.get_json(
            url,
            timeout = FAST_TIMEOUT_SECONDS,
        )
    except _common.RequestFailed as exc:
        data["queries"].append(getattr(
            exc,
            "url",
            None,
        ) or url)
        if exc.status_code == 404:
            return []
        raise
    data["queries"].append(sent_url)

    rows = []
    for context in (payload or {}).get("genomicContexts") or []:
        gene = (context.get("gene") or {}).get("geneName")
        if not gene:
            continue
        rows.append({
            "gene":            gene,
            "rsid":            variant,
            "distance":        context.get("distance"),
            "is_intergenic":   context.get("isIntergenic"),
            "source":          context.get("source"),
            "is_closest_gene": context.get("isClosestGene"),
        })
    rows.sort(key=lambda row: (row["distance"] is None, row["distance"] or 0, row["gene"]))
    return rows


def _mapped_genes(
    associations: list,
    limit:        int,
    data:         dict,
    caveats:      list,
) -> list:
    """Mapped genes for the strongest `limit` variants, in that order. Capped because
    each variant is its own request; the cap is always stated in caveats."""
    variants, seen = [], set()
    for association in associations:
        if len(variants) >= limit:
            break
        variant = association.get("rsid")
        if variant and variant not in seen:
            seen.add(variant)
            variants.append(variant)

    genes, keys, missing = [], set(), []
    for variant in variants:
        rows = _genomic_contexts(variant, data)
        if not rows:
            missing.append(variant)
        for row in rows:
            key = (row["rsid"], row["gene"], row["source"])
            if key in keys:
                continue
            keys.add(key)
            genes.append(row)

    caveats.append(
        f"Mapped genes come from the SNP resource, one request per variant, and are "
        f"capped at the strongest {limit} variant(s) by p-value: {len(variants)} "
        f"variant(s) queried out of {len(associations)} kept association(s), "
        f"{len(genes)} gene row(s) returned."
    )
    if missing:
        caveats.append(
            f"{len(missing)} of the {len(variants)} queried variant(s) returned no "
            f"genomic context ({', '.join(missing[:5])}): the Catalog also writes "
            f"positional ids such as chr4:88887327 and HGVS strings, which carry no "
            f"gene annotation, and an unknown rsid answers 404."
        )
    if genes:
        distances = [row["distance"] for row in genes if isinstance(row["distance"], int)]
        if distances:
            caveats.append(GENE_DISTANCE_TEMPLATE.format(
                low      = min(distances),
                high     = max(distances),
                at_zero  = sum(1 for distance in distances if distance == 0),
            ))
        caveats.append(TWO_SOURCES_CAVEAT)
        caveats.append(CLOSEST_GENE_CAVEAT)
    return genes


def _failure(
    args:    dict,
    data:    dict,
    caveats: list,
    exc:     Exception,
) -> dict:
    """Error envelope that keeps whatever was already retrieved, the way 1B does: the
    trait resolved and 40 associations parsed before the SNP endpoint fell over is
    still evidence, and throwing it away would turn a real locus list into a gap."""
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
    ) or (data["queries"][-1] if data.get("queries") else BASE_URL)

    notes = []
    # The deadline and the association pull are the failures a reader must not mistake
    # for absence, so those - and only those - carry the slow-resource explanation.
    if "deadline" in message or "/associations" in str(url):
        notes.append(SLOW_RESOURCE_CAVEAT)

    kept = len(data.get("associations") or [])
    if kept:
        notes.append(
            f"The GWAS Catalog request failed after {len(data['queries'])} request(s): "
            f"{message}. The {kept} association(s) already parsed are kept in "
            f"data['associations'] and are real."
        )
    else:
        notes.append(
            f"The GWAS Catalog request failed before any association was retrieved, so "
            f"this trait has no retrieved association either way: {message}"
        )
    notes.append(EMPTY_CAVEAT)

    return _record(_common.envelope(
        tool    = "get_gwas_catalog",
        args    = args,
        source  = SOURCE,
        url     = url,
        status  = "error",
        data    = data,
        caveats = [*caveats, *notes],
    ))


def get_gwas_catalog(
    trait_label:      str,
    ontology_id:      str = "",
    max_associations: int = 200,
    max_genes_from:   int = 10,
) -> dict:
    """Retrieve curated GWAS Catalog associations for one trait, with mapped genes.

    Give it 1A's ontology id when there is one (`MONDO:0005393`, with or without the
    colon) - it reaches this resource directly and is the reliable path. `trait_label`
    is the fallback and must be the Catalog's own label, matched exactly except for
    case: "gout" works, "glycine" does not because the term is "glycine measurement",
    and "coronary artery disease" does not because the term moved to MONDO as
    "coronary artery disorder". No spelling is invented for you.

    The strongest `max_associations` rows by p-value are kept (ranked on the reported
    mantissa/exponent, because the strongest p-values underflow to 0.0), and the top
    `max_genes_from` variants - at most 10, one request each - are enriched with the
    genes mapped to them, which is what 1D consumes. Mapped genes carry no distance
    cutoff; the range in hand is stated in a caveat, because a row 90 kb away is still
    a row.

    `beta` is the source's UNSIGNED magnitude and `beta_direction` carries the sign;
    read `beta_signed` if you want one number, never `beta` alone.

    `status` is "empty" when the trait term does not resolve OR resolves with no
    curated association; the caveats say which, and neither is evidence that no
    association exists. Associations, never causal estimates. The associations
    endpoint cannot be paged and is slow, so it aborts at a wall-clock deadline and
    returns an "error" envelope rather than hanging the pipeline.
    """
    args = {
        "trait_label":      _as_text(trait_label),
        "ontology_id":      _as_text(ontology_id),
        "max_associations": _as_int(max_associations, 200),
        # 0 is a legitimate answer here: "associations only, do not spend a request per
        # variant". It is not a bad value to be replaced by the default.
        "max_genes_from":   _as_int(
            max_genes_from,
            MAX_GENES_FROM_LIMIT,
            minimum = 0,
        ),
    }
    data = {
        "efo_short_form":        None,
        "efo_trait":             None,
        "n_associations_total":  0,
        "n_associations_kept":   0,
        "associations":          [],
        "mapped_genes":          [],
        "queries":               [],
    }
    caveats = [ASSOCIATION_CAVEAT]

    gene_limit = args["max_genes_from"]
    if gene_limit > MAX_GENES_FROM_LIMIT:
        caveats.append(
            f"max_genes_from={gene_limit} was clamped to {MAX_GENES_FROM_LIMIT}: mapped "
            f"genes cost one request per variant and this resource is supplementary."
        )
        gene_limit = MAX_GENES_FROM_LIMIT

    try:
        short_form = _short_form(args["ontology_id"])
        trait = None
        if short_form:
            trait = _resolve_by_id(
                short_form,
                data,
                caveats,
            )
            if trait is None:
                short_form = ""
            else:
                caveats.append(
                    f"Resolved through the ontology id: {args['ontology_id']!r} -> "
                    f"{short_form} ({trait!r}). The trait name was not searched."
                )
                if (
                    args["trait_label"]
                    and _common.normalize(args["trait_label"]) != _common.normalize(trait)
                ):
                    caveats.append(
                        f"The caller's label {args['trait_label']!r} is not this "
                        f"resource's own label {trait!r} for {short_form}. The id "
                        f"decided; print the Catalog's spelling beside these rows."
                    )

        if not short_form:
            if not args["trait_label"]:
                caveats.append(
                    "No ontology id resolved and no trait_label was given, so no "
                    "association query was sent."
                )
                caveats.append(EMPTY_CAVEAT)
                return _record(_common.envelope(
                    tool    = "get_gwas_catalog",
                    args    = args,
                    source  = SOURCE,
                    url     = data["queries"][-1] if data["queries"] else "",
                    status  = "empty",
                    data    = data,
                    caveats = caveats,
                ))

            short_form, trait = _resolve_by_name(
                args["trait_label"],
                data,
                caveats,
            )
            if short_form:
                caveats.append(
                    f"Resolved through the trait-name search: {args['trait_label']!r} -> "
                    f"{short_form} ({trait!r})."
                )

        if not short_form:
            caveats.append(
                f"No GWAS Catalog trait is named {args['trait_label']!r}. That search is "
                f"an exact label match despite living under /search/, so a near miss "
                f"returns nothing at all. {METABOLITE_NAMING_CAVEAT}"
            )
            caveats.append(EMPTY_CAVEAT)
            return _record(_common.envelope(
                tool    = "get_gwas_catalog",
                args    = args,
                source  = SOURCE,
                url     = data["queries"][-1] if data["queries"] else "",
                status  = "empty",
                data    = data,
                caveats = caveats,
            ))

        data["efo_short_form"] = short_form
        data["efo_trait"] = trait

        payload, sent_url = _fetch_within_deadline(
            ASSOCIATIONS_URL.format(short_form=short_form),
            ASSOCIATIONS_DEADLINE_SECONDS,
        )
        data["queries"].append(sent_url)
        caveats.append(NO_PAGINATION_CAVEAT)

        raw_rows = _embedded(payload, "associations")
        data["n_associations_total"] = len(raw_rows)

        associations = sorted(
            (_association(row) for row in raw_rows),
            key = _pvalue_key,
        )
        if len(associations) > args["max_associations"]:
            dropped = len(associations) - args["max_associations"]
            associations = associations[:args["max_associations"]]
            caveats.append(
                f"Capped: {data['n_associations_total']} association(s) were retrieved "
                f"and the strongest {args['max_associations']} by p-value are kept; "
                f"{dropped} weaker row(s) were dropped after download."
            )

        data["associations"] = associations
        data["n_associations_kept"] = len(associations)

        if not associations:
            caveats.append(
                f"{short_form} ({trait!r}) resolved, but the Catalog holds no curated "
                f"association under it."
            )
            caveats.append(EMPTY_CAVEAT)
            return _record(_common.envelope(
                tool    = "get_gwas_catalog",
                args    = args,
                source  = SOURCE,
                url     = sent_url,
                status  = "empty",
                data    = data,
                caveats = caveats,
            ))

        if any(row["beta"] is not None for row in associations):
            caveats.append(BETA_SIGN_CAVEAT)
        if any(row["pvalue"] == 0 for row in associations if row["pvalue"] is not None):
            caveats.append(PVAL_ZERO_CAVEAT)
        not_reported = sum(1 for row in associations if "NR" in row["author_reported_genes"])
        if not_reported:
            caveats.append(NOT_REPORTED_CAVEAT.format(count=not_reported))
        named = sum(1 for row in associations if row["author_reported_genes"])
        caveats.append(
            f"{named} of the {len(associations)} kept association(s) carry an "
            f"author-reported gene entry; the rest name none, which is why mapped genes "
            f"are fetched from the SNP resource separately."
        )

        data["mapped_genes"] = _mapped_genes(
            associations,
            gene_limit,
            data,
            caveats,
        )

        return _record(_common.envelope(
            tool    = "get_gwas_catalog",
            args    = args,
            source  = SOURCE,
            url     = sent_url,
            status  = "ok",
            data    = data,
            caveats = caveats,
        ))

    except _HANDLED as exc:
        return _failure(
            args,
            data,
            caveats,
            exc,
        )
    except Exception as exc:                           # nothing escapes a tool
        return _failure(
            args,
            data,
            caveats,
            exc,
        )


if __name__ == "__main__":
    def show(
        env,
        genes = 6,
        rows  = 3,
    ):
        print(f"  status        : {env['status']}")
        print(f"  url           : {env['url']}")
        print(f"  queries       : {len(env['data']['queries'])}")
        print(f"  efo           : {env['data']['efo_short_form']} {env['data']['efo_trait']!r}")
        print(f"  associations  : {env['data']['n_associations_kept']} kept of "
              f"{env['data']['n_associations_total']}")
        for row in env["data"]["associations"][:rows]:
            effect = (f"OR={row['or_per_copy']}" if row["or_per_copy"] is not None
                      else f"beta={row['beta']} {row['beta_direction']}")
            print(f"    {str(row['rsid']):<18} {row['pvalue_mantissa']}e{row['pvalue_exponent']:<6} "
                  f"(pvalue={row['pvalue']}) {effect} genes={row['author_reported_genes']}")
        print(f"  mapped_genes  : {len(env['data']['mapped_genes'])} row(s)")
        for row in env["data"]["mapped_genes"][:genes]:
            print(f"    {row['gene']:<16} {row['rsid']:<14} d={row['distance']} "
                  f"intergenic={row['is_intergenic']} src={row['source']} "
                  f"closest={row['is_closest_gene']}")
        for caveat in env["caveats"]:
            print(f"  caveat        : {caveat}")

    print("This self-test really pulls from a resource that cannot be paged: expect")
    print("about two minutes for gout and another forty seconds for glycine.\n")

    print("1) gout by 1A's ontology id (MONDO:0005393) - the good path")
    started = time.monotonic()
    show(get_gwas_catalog(
        "gout",
        "MONDO:0005393",
        max_associations = 25,
        max_genes_from   = 3,
    ))
    print(f"  elapsed       : {time.monotonic() - started:.0f}s")

    print("\n2) a metabolite by trait name only - no ontology id, and the Catalog's own")
    print("   label is a measurement. rs1047891 sits in CPS1, the known glycine gene.")
    started = time.monotonic()
    show(
        get_gwas_catalog(
            "glycine measurement",
            max_associations = 5,
            max_genes_from   = 1,
        ),
        genes = 4,
        rows  = 2,
    )
    print(f"  elapsed       : {time.monotonic() - started:.0f}s")

    print("\n3) the same metabolite by its bare name - the honest-empty path")
    env = get_gwas_catalog("glycine")
    print(f"  status={env['status']} queries={len(env['data']['queries'])}")
    for caveat in env["caveats"][1:]:
        print(f"  caveat        : {caveat}")

    print("\n4) a trait nobody named that way")
    env = get_gwas_catalog("zzqx-not-a-trait", "ZZZZ:9999999")
    print(f"  status={env['status']} queries={len(env['data']['queries'])}")
    for caveat in env["caveats"][1:]:
        print(f"  caveat        : {caveat}")
