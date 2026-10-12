"""Has anybody already shown that the metabolite GWAS and the disease GWAS share ONE
causal variant at a locus? Open Targets' own colocalisation table, retrieved.

MR answers "does the exposure move the outcome". It does not answer "is this the same
signal, or two different variants in linkage disequilibrium that a naive instrument
cannot tell apart". Colocalisation is the question MR cannot ask, and this project does
not run it: Open Targets has already run it, pairwise, over every credible set in its
release, and this tool goes and reads the rows for the disease studies of one pair.

    from tools.coloc import get_colocalisation
    env = get_colocalisation(["urate", "uric acid"], ["gout"], "MONDO_0005393")
    env["data"]["metabolite_hits"][0]["h4"]        # 1.0 - retrieved, not computed
    env["data"]["qtl_hits"][0]["gene_symbol"]      # the eQTL/pQTL partner's gene

WHAT IT IS NOT

  It is NOT a classifier input. `classify.classify_state` is a pure function of the 1B
  and 1C arms and nothing here touches it. A retrieved colocalisation is an EVIDENCE
  QUALIFIER appended to a verdict that was already decided: it can corroborate State A
  and it can say of a State B pair that the two GWAS already colocalise while the causal
  estimate has never been computed. It cannot move a pair between states.

  It is NOT a colocalisation this agent ran. Every H4, H3 and CLPP on the card is a
  number Open Targets published, under the method named on its own row.

  It is NOT a three-way mQTL / eQTL / disease colocalisation. The source publishes
  two-way results only, so a metabolite hit and a molecular-QTL hit at the same locus are
  two separate two-way statements that happen to share a credible set - never one
  three-way claim.

HOW A PARTNER IS CLASSIFIED. Each credible set of a disease study carries up to
thousands of colocalisation partners, and all but a handful are noise for this question:

  metabolite    the partner study's traitFromSource contains one of the metabolite's
                synonyms as a WHOLE WORD ("Urate levels", "Serum urate levels",
                "Metabolite levels (urate; cmh_urate; Uric_acid)"). The word boundary is
                the whole rule and it is load-bearing: a plain substring test makes
                "Saturated fatty acids levels" a urate hit, because "sat-URATE-d"
                contains the string, and this project would then print a fatty-acid
                colocalisation as a urate one. Synonyms shorter than four characters are
                dropped before matching for the same reason - PubChem hands 1A "G" and
                "Gly" for glycine, and "G" matches almost every trait ever deposited.
  molecular_qtl the partner is an expression / protein / splicing / transcript QTL study
                (rightStudyType eqtl, pqtl, sqtl, tuqtl and their single-cell forms).
                The partner study's target.approvedSymbol is kept: that symbol is what
                joins this row to the 1D effector genes on the card.
  ignored       everything else. Another disease, a body-mass index GWAS, a lipid panel
                - all real colocalisations, none of them about this pair.

WHAT IS CAPPED, AND WHY IT MATTERS. The source refuses a query whose response would be
too large ("Query is too expensive"), so the work is capped on three axes and every cap
is in the caveats: how many disease studies are searched (`max_studies`, ranked by nCases
then nSamples), how many credible sets per study (`max_sets`), and how many
colocalisation partners are read per credible set (COLOC_PAGE). The third one is the
sharp edge: a credible set at a pleiotropic locus can carry 4,424 partners and the rows
do NOT come back ordered by H4, so a partner past the cap is invisible to this run. That
is a budget, not a finding, and the caveats say so per run.

RETRIEVED, NOT COMPUTED, AND EMPTY IS NOT ZERO. An empty result means no colocalisation
between these studies is published in this Open Targets release, within the caps above.
It is not evidence against a shared causal variant, and it is never printed as one.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from . import _common
except ImportError:                                    # running: python tools/coloc.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _common

import ledger

GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"

SOURCE = (
    "Open Targets Platform GraphQL v4 (credible-set colocalisation) - published "
    "pairwise colocalisation, retrieved here, not computed"
)

# Candidate disease studies are read in pages of this size, at most this many pages. 208
# studies are mapped to coronary artery disorder and 117 to gout, so four pages hold the
# whole candidate list for the pairs this build demonstrates; anything past it is a cap
# and is written into the caveats.
STUDY_PAGE = 50
MAX_STUDY_PAGES = 4

# One credible-set request carries SETS_PAGE sets, each with up to COLOC_PAGE of its GWAS
# colocalisation partners AND up to QTL_PAGE of its molecular-QTL partners - the second
# list in the same request, under a GraphQL alias, because the source's default
# colocalisation list carries GWAS partners ONLY: asked without `studyTypes`, the credible
# set at chr4:9925343 returns 47 partners and calls that 47, while the same field asked
# for eqtl/pqtl/sqtl/tuqtl returns 3 more. A run that never asks would report "no QTL
# colocalisation" for every locus in the release.
#
# Measured against the live API on 2026-09-11: (10, 100, 50) returns ~700 partner rows in
# one response in under a second and is accepted; (60, 200) is refused as too expensive.
# The ladder is walked downwards when the source refuses a rung, so a locus richer than
# the pairs tested here degrades to smaller pages instead of failing.
PAGE_LADDER = (
    (10, 100, 50),
    (5,  50,  25),
    (2,  50,  25),
    (1,  50,  25),
)
SETS_PAGE, COLOC_PAGE, QTL_PAGE = PAGE_LADDER[0]

# Rows kept in the envelope. The counts (n_metabolite_hits / n_qtl_hits) are the true
# totals over everything that was examined; only the lists are cut.
MAX_HITS = 25
MAX_GENES = 20
# Synonyms are capped and short ones dropped before any matching - see the module
# docstring. "TMAO" is four characters and survives; "G", "Gly" and "cit" do not.
MAX_SYNONYMS = 24
MIN_SYNONYM_CHARS = 4

# Disease-side spellings sent to the study search when no ontology id is available.
MAX_SEARCH_SYNONYMS = 3
SEARCH_PAGE = 50

# A public API with no key. The same quarter-second-ish politeness the rest of this
# project uses between remote calls.
SLEEP_SECONDS = 0.3

QTL_STUDY_TYPES = (
    "eqtl",
    "pqtl",
    "sqtl",
    "tuqtl",
    "sceqtl",
    "scpqtl",
    "scsqtl",
    "sctuqtl",
)

STUDIES_QUERY = """query($diseaseIds: [String!], $index: Int!, $size: Int!) {
  studies(diseaseIds: $diseaseIds, page: {index: $index, size: $size}) {
    count
    rows {
      id traitFromSource studyType nCases nSamples hasSumstats
      publicationFirstAuthor publicationDate
    }
  }
}"""

SEARCH_QUERY = """query($queryString: String!, $size: Int!) {
  search(queryString: $queryString, entityNames: ["study"], page: {index: 0, size: $size}) {
    total
    hits {
      id
      object {
        __typename
        ... on Study {
          id traitFromSource studyType nCases nSamples hasSumstats
          publicationFirstAuthor publicationDate
        }
      }
    }
  }
}"""

SETS_QUERY = """query($studyIds: [String!], $index: Int!, $size: Int!,
                      $colocSize: Int!, $qtlSize: Int!) {
  credibleSets(studyIds: $studyIds, page: {index: $index, size: $size}) {
    count
    rows {
      studyLocusId chromosome position finemappingMethod confidence
      variant { id }
      colocalisation(page: {index: 0, size: $colocSize}) {
        count
        rows {
          h4 h3 clpp colocalisationMethod rightStudyType
          numberColocalisingVariants betaRatioSignAverage
          otherStudyLocus {
            studyLocusId
            study { id traitFromSource studyType target { approvedSymbol } }
          }
        }
      }
      qtl: colocalisation(
        studyTypes: [eqtl, pqtl, sqtl, tuqtl, sceqtl, scpqtl, scsqtl, sctuqtl],
        page: {index: 0, size: $qtlSize}
      ) {
        count
        rows {
          h4 h3 clpp colocalisationMethod rightStudyType
          numberColocalisingVariants betaRatioSignAverage
          otherStudyLocus {
            studyLocusId
            study { id traitFromSource studyType target { approvedSymbol } }
          }
        }
      }
    }
  }
}"""

RETRIEVED_CAVEAT = (
    "Colocalisation results are RETRIEVED from Open Targets, not computed here."
)
H4_CAVEAT = (
    "H4 is the posterior probability of one shared causal variant under the coloc model "
    "used by the source (method named per row); it is not a p-value and not proof of "
    "causality."
)
TWO_WAY_CAVEAT = (
    "Only two-way colocalisations published by the source are available - three-way "
    "mQTL/eQTL/disease colocalisation is not something this agent performs."
)
NOT_CLASSIFIER_CAVEAT = (
    "This arm is an evidence qualifier and not a classifier input: the A/B/C state comes "
    "from the MR and instrument arms alone and nothing retrieved here can move it."
)
WORD_BOUNDARY_CAVEAT = (
    "A partner counts as the metabolite only when one of its synonyms appears as a whole "
    "word in the partner trait. A trait this source spells some third way will not match; "
    "that is a limit of the matching rule, not a statement about the metabolite."
)
SHORT_SYNONYM_CAVEAT = (
    "{dropped} metabolite synonym(s) shorter than {chars} characters were dropped before "
    "matching ({examples}), because a one- or two-letter synonym matches almost every "
    "trait. Those spellings were not searched."
)
STUDY_CAP_CAVEAT = (
    "{total} disease study(ies) are mapped to this disease in the source; the "
    "{searched} largest by case count (then sample size) were searched. The rest were "
    "not opened, which is a cap on this call."
)
SET_CAP_CAVEAT = (
    "{study}: {total} credible set(s) in the source, {examined} examined (cap "
    "{cap}). Sets past the cap were not read."
)
COLOC_CAP_CAVEAT = (
    "{truncated} of the {examined} credible set(s) examined carry more GWAS "
    "colocalisation partners than the {cap} read per set ({rows} of {available} partner "
    "rows read in total). Partner rows do not come back ordered by H4, so a partner past "
    "that cap is invisible to this run - a budget, not an absence."
)
QTL_CAP_CAVEAT = (
    "{truncated} of the {examined} credible set(s) examined carry more molecular-QTL "
    "partners than the {cap} read per set ({rows} of {available} QTL partner rows read "
    "in total). A gene past that cap is not in the gene list below."
)
HITS_CAP_CAVEAT = (
    "{total} {kind} colocalisation(s) were retrieved; the {shown} with the highest H4 "
    "are listed. The count, not the list, is the total."
)
EMPTY_CAVEAT = (
    "Disease study(ies) searched: {studies}. No published colocalisation between them "
    "and this metabolite was retrieved within the caps above. Absence of a retrieved "
    "colocalisation is NOT evidence against a shared causal variant."
)
NO_STUDY_CAVEAT = (
    "No disease study was resolved for this pair{detail}, so no credible set and no "
    "colocalisation was read. That is a resolution gap, not an absence of colocalisation."
)
NO_SYNONYM_CAVEAT = (
    "No usable metabolite synonym was given, so metabolite partners could not be "
    "matched: metabolite_hits is empty by construction, not by retrieval."
)
EFO_EMPTY_CAVEAT = (
    "The ontology id {efo} is mapped to no study in this Open Targets release, so the "
    "disease studies were resolved by matching the disease synonyms against study trait "
    "names instead."
)
TRAIT_PREFERENCE_CAVEAT = (
    "{exact} of the studies searched carry a trait name that is exactly one of the "
    "disease synonyms; they were searched before the studies that are only mapped to the "
    "disease id (whose trait may be a combined phenotype). Every searched study's trait "
    "is printed with its row."
)
DEGRADED_CAVEAT = (
    "The source refused the {sets}-set / {coloc}-partner page as too expensive for "
    "{study}, so that study was re-read in smaller pages ({new_sets} sets / {new_coloc} "
    "partners)."
)
PARTIAL_CAVEAT = (
    "{failed} of {total} study(ies) could not be read ({detail}). Treat those as no "
    "information, not as studies without colocalisation."
)
FAILURE_CAVEAT = (
    "The colocalisation request failed, so nothing was retrieved about shared causal "
    "variants for this pair. Treat it as no information, not as an absent colocalisation."
)

_EXPENSIVE = "too expensive"


class _GraphQLFailed(Exception):
    """A GraphQL response that carried `errors`. Held apart from a transport failure so
    a "too expensive" refusal can be answered with smaller pages instead of an error
    envelope."""

    def __init__(
        self,
        message:   str,
        expensive: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.expensive = expensive


# ---------------------------------------------------------------- matching rules

def _boundary(needle: str):
    """A compiled matcher for one normalized synonym, anchored on word boundaries.

    `(?<![0-9a-z])urate(?![0-9a-z])` matches "urate levels" and "(urate; cmh_urate)" and
    refuses "saturated fatty acids levels". The synonym is escaped, so a spelling with
    brackets or a plus sign ("me3n(+)o(-)") is a literal, never a pattern.
    """
    return re.compile(rf"(?<![0-9a-z]){re.escape(needle)}(?![0-9a-z])")


def usable_synonyms(values) -> tuple:
    """`(needles, dropped)` - the normalized metabolite spellings long enough to match on,
    de-duplicated and capped, and the short ones that were thrown away.

    Short spellings are the danger: 1A's PubChem leg hands back "G" and "Gly" for glycine
    and "cit" for citrate, and matching those against a free-text trait name would turn
    most of the GWAS catalogue into a metabolite hit.
    """
    needles, dropped, seen = [], [], set()
    for value in values or []:
        needle = _common.normalize(value)
        if not needle or needle in seen:
            continue
        seen.add(needle)
        if len(needle) < MIN_SYNONYM_CHARS:
            dropped.append(needle)
            continue
        needles.append(needle)
    return needles[:MAX_SYNONYMS], dropped


def match_metabolite(
    trait:    str,
    needles:  list,
    patterns: dict | None = None,
) -> str:
    """The metabolite synonym this partner trait carries as a whole word, or "".

    The two shapes the brief names - "<synonym> levels" and "serum <synonym> levels" -
    are checked first because they are what a metabolite GWAS is almost always called;
    the whole-word rule below catches every other spelling the source uses.
    """
    text = _common.normalize(trait)
    if not text:
        return ""
    for needle in needles:
        if text in (needle, f"{needle} levels", f"serum {needle} levels"):
            return needle
    # A ratio measures a different exposure from either component. Likewise a
    # hyphen-separated conjugate is not its parent molecule. Prefer a missed
    # free-text candidate over claiming colocalisation for the wrong exposure.
    for needle in needles:
        pattern = (patterns or {}).get(needle) or _boundary(needle)
        for match in pattern.finditer(text):
            before, after = text[:match.start()], text[match.end():]
            if re.search(r"\bratio\b|/|\bto\b", before + " " + after):
                continue
            if before.endswith("-"):
                continue
            if after.startswith("-") and not after.startswith("-levels"):
                continue
            return needle
    return ""


def is_qtl(study_type) -> bool:
    """True for a molecular QTL partner (expression, protein, splicing, transcript usage,
    and their single-cell forms). The raw string is kept on every row, so a reader sees
    WHICH molecular layer a hit came from rather than one flattened label."""
    return _common.normalize(study_type).replace(" ", "") in QTL_STUDY_TYPES


# ---------------------------------------------------------------- transport

def _graphql(
    query:     str,
    variables: dict,
    label:     str,
    timeout:   int = 60,
) -> dict:
    """One POST to the Open Targets GraphQL endpoint, or an exception.

    The endpoint answers a malformed or too-expensive query with HTTP 200 and an
    `errors` array, so a caller that only checked the status code would read a refusal
    as an empty result. That is the one failure mode this project treats as worse than a
    crash, hence the explicit check here.
    """
    payload, _sent_url = _common.get_json(
        GRAPHQL_URL,
        method    = "POST",
        json_body = {"query": query, "variables": variables},
        timeout   = timeout,
    )
    if not isinstance(payload, dict):
        raise _GraphQLFailed(f"{label}: the endpoint returned a non-object payload")

    errors = payload.get("errors")
    if errors:
        messages = "; ".join(
            str((item or {}).get("message") or item)
            for item in (errors if isinstance(errors, list) else [errors])
        )[:300]
        raise _GraphQLFailed(
            f"{label}: {messages}",
            expensive = _EXPENSIVE in messages.casefold(),
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        raise _GraphQLFailed(f"{label}: the response carried no data object")
    return data


def _sleep(sent: list) -> None:
    """Politeness between remote calls, and only between them: the first call of a run
    waits for nothing."""
    if sent:
        time.sleep(SLEEP_SECONDS)


# ---------------------------------------------------------------- study resolution

def _study_row(row) -> dict:
    """One candidate study, in the shape `studies_searched` publishes."""
    return {
        "id":           str((row or {}).get("id") or ""),
        "trait":        (row or {}).get("traitFromSource"),
        "study_type":   (row or {}).get("studyType"),
        "n_cases":      (row or {}).get("nCases"),
        "n_samples":    (row or {}).get("nSamples"),
        "has_sumstats": (row or {}).get("hasSumstats"),
        "first_author": (row or {}).get("publicationFirstAuthor"),
        "date":         (row or {}).get("publicationDate"),
    }


def _rank_key(study: dict):
    """Largest case count first, then largest sample size. A study the source records no
    case count for sorts as zero - it is not promoted, and it is not dropped either."""
    cases = study.get("n_cases") or 0
    samples = study.get("n_samples") or 0
    try:
        return (-float(cases), -float(samples))
    except (TypeError, ValueError):
        return (0.0, 0.0)


def _studies_by_efo(
    disease_efo: str,
    queries:     list,
) -> list:
    """Every study the source maps to this ontology id, up to the page cap."""
    found = []
    for index in range(MAX_STUDY_PAGES):
        _sleep(queries)
        queries.append(
            f"POST {GRAPHQL_URL} studies(diseaseIds=[{disease_efo}], "
            f"page={{index:{index}, size:{STUDY_PAGE}}})"
        )
        data = _graphql(
            STUDIES_QUERY,
            {"diseaseIds": [disease_efo], "index": index, "size": STUDY_PAGE},
            f"studies({disease_efo}) page {index}",
            timeout = 45,
        )
        block = data.get("studies") or {}
        rows = [row for row in (block.get("rows") or []) if isinstance(row, dict)]
        found.extend(_study_row(row) for row in rows)
        total = block.get("count")
        if not rows or (isinstance(total, int) and len(found) >= total):
            break
    return [study for study in found if study["id"]]


def _studies_by_trait(
    disease_needles: list,
    queries:         list,
) -> list:
    """Studies whose trait name IS one of the disease synonyms, found through the
    source's own study search.

    Matching is exact after normalization, exactly as the 1B/1C arms match a trait: a
    study the source spells some third way does not match, and that is a retrieval limit
    written into the caveats rather than a guess.
    """
    found, seen = [], set()
    for needle in disease_needles[:MAX_SEARCH_SYNONYMS]:
        _sleep(queries)
        queries.append(
            f"POST {GRAPHQL_URL} search(queryString={needle!r}, entityNames=[study], "
            f"page={{index:0, size:{SEARCH_PAGE}}})"
        )
        data = _graphql(
            SEARCH_QUERY,
            {"queryString": needle, "size": SEARCH_PAGE},
            f"search({needle})",
            timeout = 45,
        )
        hits = [hit for hit in ((data.get("search") or {}).get("hits") or [])
                if isinstance(hit, dict)]
        for hit in hits:
            row = hit.get("object")
            if not isinstance(row, dict) or row.get("__typename") != "Study":
                continue
            study = _study_row(row)
            trait = _common.normalize(study["trait"])
            if not study["id"] or study["id"] in seen or trait not in disease_needles:
                continue
            seen.add(study["id"])
            found.append(study)
    return found


# ---------------------------------------------------------------- credible sets

def _coloc_rows(
    set_row: dict,
    key:     str = "colocalisation",
) -> list:
    """The partner rows of one credible set. `key` is "colocalisation" for the GWAS
    partners the source returns by default, or "qtl" for the molecular-QTL partners the
    aliased field asked for by study type."""
    block = set_row.get(key) if isinstance(set_row, dict) else None
    block = block if isinstance(block, dict) else {}
    return [row for row in (block.get("rows") or []) if isinstance(row, dict)]


def _coloc_count(
    set_row: dict,
    key:     str = "colocalisation",
) -> int:
    """How many partner rows the source says this set has under `key`, falling back to
    the number actually returned when it says nothing."""
    block = set_row.get(key) if isinstance(set_row, dict) else None
    count = (block or {}).get("count") if isinstance(block, dict) else None
    return count if isinstance(count, int) else len(_coloc_rows(set_row, key))


def _partner(coloc_row: dict) -> dict:
    other = coloc_row.get("otherStudyLocus")
    other = other if isinstance(other, dict) else {}
    study = other.get("study")
    study = study if isinstance(study, dict) else {}
    target = study.get("target")
    target = target if isinstance(target, dict) else {}
    return {
        "partner_study_locus_id": other.get("studyLocusId"),
        "partner_study_id":       study.get("id"),
        "partner_trait":          study.get("traitFromSource"),
        "partner_study_type":     study.get("studyType"),
        "gene_symbol":            target.get("approvedSymbol"),
    }


def _hit(
    study_id:  str,
    set_row:   dict,
    coloc_row: dict,
) -> dict:
    """One retrieved colocalisation, flattened: the disease locus on the left, the
    partner on the right, and the source's own posterior probabilities between them."""
    variant = set_row.get("variant")
    variant = variant if isinstance(variant, dict) else {}
    hit = {
        "h4":                coloc_row.get("h4"),
        "h3":                coloc_row.get("h3"),
        "clpp":              coloc_row.get("clpp"),
        "method":            coloc_row.get("colocalisationMethod"),
        "chromosome":        set_row.get("chromosome"),
        "position":          set_row.get("position"),
        "variant_id":        variant.get("id"),
        "locus_study_id":    study_id,
        "study_locus_id":    set_row.get("studyLocusId"),
        "finemapping":       set_row.get("finemappingMethod"),
        "confidence":        set_row.get("confidence"),
        "n_coloc_variants":  coloc_row.get("numberColocalisingVariants"),
        "beta_ratio_sign":   coloc_row.get("betaRatioSignAverage"),
        "right_study_type":  coloc_row.get("rightStudyType"),
    }
    hit.update(_partner(coloc_row))
    return hit


def _sort_key(hit: dict):
    """Strongest retrieved H4 first; a row the source left without an H4 sorts last
    rather than being dropped."""
    value = hit.get("h4")
    try:
        return (0, -float(value))
    except (TypeError, ValueError):
        return (1, 0.0)


def _fetch_sets(
    study_id: str,
    max_sets: int,
    queries:  list,
    caveats:  list,
) -> dict:
    """The credible sets of one study, with both partner lists attached to each set.

    Returns {sets, n_sets_in_source, rows_read, rows_available, truncated,
    qtl_rows_read, qtl_rows_available, qtl_truncated} - the read / available pairs are
    what the cap caveat is built from, so a reader is told how much of the locus was
    actually opened.

    Walks PAGE_LADDER downwards: when the source refuses a page as too expensive the
    study is re-read from the start with smaller pages and the degradation is written
    into the caveats. A refusal that is not about cost is raised.
    """
    last_error = None
    for rung, (sets_size, coloc_size, qtl_size) in enumerate(PAGE_LADDER):
        collected, index, total = [], 0, None
        try:
            while len(collected) < max_sets:
                _sleep(queries)
                queries.append(
                    f"POST {GRAPHQL_URL} credibleSets(studyIds=[{study_id}], "
                    f"page={{index:{index}, size:{sets_size}}}) "
                    f"colocalisation(page={{index:0, size:{coloc_size}}}) "
                    f"qtl:colocalisation(studyTypes=[{','.join(QTL_STUDY_TYPES)}], "
                    f"page={{index:0, size:{qtl_size}}})"
                )
                data = _graphql(
                    SETS_QUERY,
                    {
                        "studyIds":  [study_id],
                        "index":     index,
                        "size":      sets_size,
                        "colocSize": coloc_size,
                        "qtlSize":   qtl_size,
                    },
                    f"credibleSets({study_id}) page {index}",
                )
                block = data.get("credibleSets") or {}
                rows = [row for row in (block.get("rows") or []) if isinstance(row, dict)]
                total = block.get("count") if isinstance(block.get("count"), int) else total
                collected.extend(rows)
                index += 1
                if not rows or len(rows) < sets_size:
                    break
                if isinstance(total, int) and len(collected) >= total:
                    break
        except _GraphQLFailed as exc:
            last_error = exc
            if not exc.expensive or rung == len(PAGE_LADDER) - 1:
                raise
            next_sets, next_coloc, _next_qtl = PAGE_LADDER[rung + 1]
            caveats.append(DEGRADED_CAVEAT.format(
                study     = study_id,
                sets      = sets_size,
                coloc     = coloc_size,
                new_sets  = next_sets,
                new_coloc = next_coloc,
            ))
            continue

        kept = collected[:max_sets]
        found = {
            "sets":             kept,
            "n_sets_in_source": total,
            "coloc_page":       coloc_size,
            "qtl_page":         qtl_size,
        }
        for key, prefix in (("colocalisation", ""), ("qtl", "qtl_")):
            read, available, truncated = 0, 0, 0
            for row in kept:
                shown = len(_coloc_rows(row, key))
                count = _coloc_count(row, key)
                read += shown
                available += count
                if count > shown:
                    truncated += 1
            found[f"{prefix}rows_read"] = read
            found[f"{prefix}rows_available"] = available
            found[f"{prefix}truncated"] = truncated
        return found

    raise last_error or _GraphQLFailed(f"credibleSets({study_id}) could not be read")


# ---------------------------------------------------------------- the tool

def get_colocalisation(
    metabolite_synonyms: list,
    disease_synonyms:    list,
    disease_efo:         str = "",
    max_studies:         int = 4,
    max_sets:            int = 60,
) -> dict:
    """Retrieve published colocalisations between this disease's GWAS and this
    metabolite's GWAS, and between this disease's GWAS and molecular QTL studies.

    Use this to ask whether the metabolite signal and the disease signal at a locus are
    ONE shared causal variant rather than two variants in linkage disequilibrium - the
    question an MR estimate cannot answer. Nothing is computed: Open Targets ran the
    colocalisation and this reads its rows. The result is an evidence qualifier on a
    verdict that was already decided elsewhere; it is not a classifier input and it can
    never move a pair between states A, B and C.

    Give it the metabolite and disease synonym lists 1A produced. `disease_efo` is the
    ontology id in underscore form (MONDO_0005393); when it is given the disease studies
    come from the source's own disease mapping, and when it is absent or maps to nothing
    they are found by matching the disease synonyms against study trait names exactly.
    `max_studies` disease studies are searched, largest case count first, and at most
    `max_sets` credible sets are read per study.

    Returns the shared eight-key envelope. `data["metabolite_hits"]` and
    `data["qtl_hits"]` hold the retrieved rows, strongest H4 first; `data["genes"]` holds
    the QTL partners' gene symbols, which is what joins this arm to the 1D effector
    genes. `status` is `ok` when either hit list has a row, `empty` when studies and
    credible sets were searched and nothing matched, `error` when the retrieval failed.
    An `empty` result is not evidence against a shared causal variant.
    """
    needles, dropped = usable_synonyms(metabolite_synonyms)
    patterns = {needle: _boundary(needle) for needle in needles}
    disease_needles = _disease_needles(disease_synonyms)
    efo = _common.underscore_ontology_id(disease_efo)
    studies_cap = max(0, int(max_studies or 0))
    sets_cap = max(0, int(max_sets or 0))

    args = {
        "metabolite_synonyms": list(metabolite_synonyms or [])[:MAX_SYNONYMS],
        "disease_synonyms":    list(disease_synonyms or [])[:MAX_SYNONYMS],
        "disease_efo":         efo,
        "max_studies":         studies_cap,
        "max_sets":            sets_cap,
    }
    data = {
        "metabolite_hits":    [],
        "qtl_hits":           [],
        "studies_searched":   [],
        "n_sets_examined":    0,
        "n_metabolite_hits":  0,
        "n_qtl_hits":         0,
        "best_h4":            None,
        "best_qtl_h4":        None,
        "genes":              [],
        "n_candidate_studies": 0,
        "disease_efo":        efo,
        "searched_synonyms":  needles,
        "dropped_synonyms":   dropped,
        "coloc_rows_read":    0,
        "coloc_rows_available": 0,
        "n_sets_truncated":   0,
        "qtl_rows_read":      0,
        "qtl_rows_available": 0,
        "n_qtl_sets_truncated": 0,
        "caps": {
            "max_studies":        studies_cap,
            "max_sets":           sets_cap,
            "coloc_rows_per_set": COLOC_PAGE,
            "qtl_rows_per_set":   QTL_PAGE,
            "hits_listed":        MAX_HITS,
        },
        "queries":            [],
    }
    caveats = [RETRIEVED_CAVEAT, H4_CAVEAT, TWO_WAY_CAVEAT, NOT_CLASSIFIER_CAVEAT]
    queries = data["queries"]

    try:
        candidates, resolution_caveats = _resolve_studies(
            efo,
            disease_needles,
            queries,
        )
        caveats.extend(resolution_caveats)
        data["n_candidate_studies"] = len(candidates)

        # A study whose own trait name IS one of the disease synonyms is searched before
        # one that is only mapped to the disease id: the id mapping also carries combined
        # phenotypes ("Type 2 diabetes mellitus or coronary artery disease"), and a
        # colocalisation retrieved against a combined phenotype is not a colocalisation
        # with the disease that was asked about. Every searched study's trait is printed
        # beside its row either way.
        exact_ids = {
            study["id"] for study in candidates
            if _common.normalize(study["trait"]) in disease_needles
        }
        exact = [study for study in candidates if study["id"] in exact_ids]
        rest = [study for study in candidates if study["id"] not in exact_ids]
        ranked = sorted(exact, key=_rank_key) + sorted(rest, key=_rank_key)
        searched = ranked[:studies_cap]

        if not searched:
            caveats.append(NO_STUDY_CAVEAT.format(
                detail = f" (ontology id {efo})" if efo else "",
            ))
            return _record(_common.envelope(
                tool    = "get_colocalisation",
                args    = args,
                source  = SOURCE,
                url     = GRAPHQL_URL,
                status  = "empty",
                data    = data,
                caveats = caveats,
            ))

        if len(candidates) > len(searched):
            caveats.append(STUDY_CAP_CAVEAT.format(
                total    = len(candidates),
                searched = len(searched),
            ))
        if exact and rest:
            caveats.append(TRAIT_PREFERENCE_CAVEAT.format(
                exact = len([study for study in searched if study["id"] in exact_ids]),
            ))

        failures = {}
        for study in searched:
            entry = dict(study)
            entry.update(n_sets_in_source=None, n_sets_examined=0)
            data["studies_searched"].append(entry)
            try:
                found = _fetch_sets(
                    study["id"],
                    sets_cap,
                    queries,
                    caveats,
                )
            except (_GraphQLFailed, _common.RequestFailed) as exc:
                failures[study["id"]] = getattr(exc, "message", str(exc))
                continue

            sets = found["sets"]
            total = found["n_sets_in_source"]
            entry["n_sets_in_source"] = total
            entry["n_sets_examined"] = len(sets)
            data["n_sets_examined"] += len(sets)
            data["coloc_rows_read"] += found["rows_read"]
            data["coloc_rows_available"] += found["rows_available"]
            data["n_sets_truncated"] += found["truncated"]
            data["qtl_rows_read"] += found["qtl_rows_read"]
            data["qtl_rows_available"] += found["qtl_rows_available"]
            data["n_qtl_sets_truncated"] += found["qtl_truncated"]
            if isinstance(total, int) and total > len(sets):
                caveats.append(SET_CAP_CAVEAT.format(
                    study    = study["id"],
                    total    = total,
                    examined = len(sets),
                    cap      = sets_cap,
                ))

            # Two lists, two questions. The GWAS partners are searched for the metabolite
            # by trait name; the QTL partners are kept for their gene symbol, which is
            # what joins this arm to the 1D effector genes. A partner that is neither is
            # another disease or another biomarker at the same locus - a real
            # colocalisation, and not one about this pair.
            for set_row in sets:
                for coloc_row in _coloc_rows(set_row):
                    partner = _partner(coloc_row)
                    if is_qtl(partner["partner_study_type"]) or is_qtl(
                            coloc_row.get("rightStudyType")):
                        continue                       # counted once, in the qtl list
                    matched = match_metabolite(
                        partner["partner_trait"],
                        needles,
                        patterns,
                    )
                    if matched:
                        hit = _hit(
                            study["id"],
                            set_row,
                            coloc_row,
                        )
                        hit["matched_synonym"] = matched
                        data["metabolite_hits"].append(hit)

                for coloc_row in _coloc_rows(set_row, "qtl"):
                    hit = _hit(
                        study["id"],
                        set_row,
                        coloc_row,
                    )
                    if hit.get("gene_symbol"):
                        data["qtl_hits"].append(hit)

        if failures:
            data["failed_studies"] = failures
            caveats.append(PARTIAL_CAVEAT.format(
                failed = len(failures),
                total  = len(searched),
                detail = "; ".join(list(failures.values())[:2])[:200],
            ))

        _finish_hits(data, caveats, needles, searched)

        if not data["studies_searched"] or all(
                entry["n_sets_examined"] == 0 for entry in data["studies_searched"]):
            status = "error" if failures else "empty"
        elif data["metabolite_hits"] or data["qtl_hits"]:
            status = "ok"
        else:
            status = "empty"

        return _record(_common.envelope(
            tool    = "get_colocalisation",
            args    = args,
            source  = SOURCE,
            url     = GRAPHQL_URL,
            status  = status,
            data    = data,
            caveats = caveats,
        ))

    except (_GraphQLFailed, _common.RequestFailed) as exc:
        data["error"] = getattr(exc, "message", str(exc))
        caveats.append(FAILURE_CAVEAT)
        return _record(_common.envelope(
            tool    = "get_colocalisation",
            args    = args,
            source  = SOURCE,
            url     = GRAPHQL_URL,
            status  = "error",
            data    = data,
            caveats = caveats,
        ))
    except Exception as exc:                           # noqa: BLE001 - deliberate boundary
        data["error"] = f"{type(exc).__name__}: {exc}"
        caveats.append(FAILURE_CAVEAT)
        return _record(_common.envelope(
            tool    = "get_colocalisation",
            args    = args,
            source  = SOURCE,
            url     = GRAPHQL_URL,
            status  = "error",
            data    = data,
            caveats = caveats,
        ))


def get_coloc_for_gene(
    gene_symbol:     str,
    disease_efo:     str = "",
    coloc_envelope:  dict | None = None,
) -> dict:
    """The molecular-QTL colocalisations of ONE gene, filtered out of the same query.

    This is a filter over `qtl_hits`, not a second endpoint: hand it the envelope
    `get_colocalisation` already returned for this pair and it sends no request at all.
    Without one it runs that single query once (disease side only - no metabolite
    synonyms, because the question here is about the gene) and filters the result.

    Returns {gene_symbol, hits, n_hits, best_h4, from_envelope, envelope}; `hits` are
    retrieved rows, strongest H4 first. An empty list means no published colocalisation
    between this disease's credible sets and a QTL study for this gene was retrieved
    within the caps of that call - never that the gene has none.
    """
    symbol = str(gene_symbol or "").strip()
    envelope = coloc_envelope
    from_envelope = isinstance(envelope, dict)
    if not from_envelope:
        envelope = get_colocalisation(
            [],
            [],
            disease_efo,
        )

    rows = (envelope.get("data") or {}).get("qtl_hits") if isinstance(envelope, dict) else []
    needle = _common.normalize(symbol)
    hits = [
        row for row in (rows or [])
        if isinstance(row, dict) and _common.normalize(row.get("gene_symbol")) == needle
    ]
    hits.sort(key=_sort_key)
    best = _best(hits)
    return {
        "gene_symbol":   symbol,
        "hits":          hits,
        "n_hits":        len(hits),
        "best_h4":       best,
        "from_envelope": from_envelope,
        "envelope":      envelope,
    }


# ---------------------------------------------------------------- internals

def _best(hits: list):
    """The largest retrieved H4 among these rows, or None when none carries one."""
    values = []
    for hit in hits or []:
        try:
            values.append(float(hit.get("h4")))
        except (TypeError, ValueError):
            continue
    return max(values) if values else None


def _disease_needles(disease_synonyms) -> list:
    """The disease spellings, normalized and de-duplicated. No length floor: the disease
    side is matched EXACTLY against a trait name, where "CAD" is safe and a substring
    rule would not be."""
    needles, seen = [], set()
    for value in disease_synonyms or []:
        needle = _common.normalize(value)
        if needle and needle not in seen:
            seen.add(needle)
            needles.append(needle)
    return needles[:MAX_SYNONYMS]


def _resolve_studies(
    efo:             str,
    disease_needles: list,
    queries:         list,
) -> tuple:
    """`(candidate studies, caveats)` - the disease mapping first, trait names second."""
    caveats = []
    if efo:
        found = _studies_by_efo(
            efo,
            queries,
        )
        if found:
            return found, caveats
        caveats.append(EFO_EMPTY_CAVEAT.format(efo=efo))
    if not disease_needles:
        return [], caveats
    return _studies_by_trait(
        disease_needles,
        queries,
    ), caveats


def _finish_hits(
    data:     dict,
    caveats:  list,
    needles:  list,
    searched: list,
) -> None:
    """Sort, count and cap the two hit lists, and add the caveats that describe what the
    counts mean. The counts are the totals over everything examined; only the lists are
    cut, and the cut is stated."""
    data["metabolite_hits"].sort(key=_sort_key)
    data["qtl_hits"].sort(key=_sort_key)
    data["n_metabolite_hits"] = len(data["metabolite_hits"])
    data["n_qtl_hits"] = len(data["qtl_hits"])
    data["best_h4"] = _best(data["metabolite_hits"])
    data["best_qtl_h4"] = _best(data["qtl_hits"])

    genes, seen = [], set()
    for hit in data["qtl_hits"]:
        symbol = str(hit.get("gene_symbol") or "").strip()
        if symbol and symbol not in seen:
            seen.add(symbol)
            genes.append(symbol)
    data["genes"] = genes[:MAX_GENES]

    data["n_qtl_genes"] = len(genes)
    if data["n_metabolite_hits"] > MAX_HITS:
        data["metabolite_hits"] = data["metabolite_hits"][:MAX_HITS]
        caveats.append(HITS_CAP_CAVEAT.format(
            total = data["n_metabolite_hits"],
            shown = MAX_HITS,
            kind  = "metabolite",
        ))
    if data["n_qtl_hits"] > MAX_HITS:
        data["qtl_hits"] = data["qtl_hits"][:MAX_HITS]
        caveats.append(HITS_CAP_CAVEAT.format(
            total = data["n_qtl_hits"],
            shown = MAX_HITS,
            kind  = "molecular QTL",
        ))

    if not needles:
        caveats.append(NO_SYNONYM_CAVEAT)
    else:
        caveats.append(WORD_BOUNDARY_CAVEAT)
    if data["dropped_synonyms"]:
        caveats.append(SHORT_SYNONYM_CAVEAT.format(
            dropped  = len(data["dropped_synonyms"]),
            chars    = MIN_SYNONYM_CHARS,
            examples = ", ".join(data["dropped_synonyms"][:6]),
        ))
    if data["n_sets_truncated"]:
        caveats.append(COLOC_CAP_CAVEAT.format(
            truncated = data["n_sets_truncated"],
            examined  = data["n_sets_examined"],
            cap       = COLOC_PAGE,
            rows      = data["coloc_rows_read"],
            available = data["coloc_rows_available"],
        ))
    if data["n_qtl_sets_truncated"]:
        caveats.append(QTL_CAP_CAVEAT.format(
            truncated = data["n_qtl_sets_truncated"],
            examined  = data["n_sets_examined"],
            cap       = QTL_PAGE,
            rows      = data["qtl_rows_read"],
            available = data["qtl_rows_available"],
        ))
    if not data["metabolite_hits"] and data["n_sets_examined"]:
        caveats.append(EMPTY_CAVEAT.format(
            studies = "; ".join(
                f"{entry['id']} ({entry.get('trait')})" for entry in searched
            )[:400],
        ))


def _record(env: dict) -> dict:
    """Self-record, 1B/1C style: the tool writes its own envelope to the active run and
    the dispatcher writes none. A no-op outside a run, so `python tools/coloc.py` and the
    unit tests leave no stray file."""
    ledger.record(env)
    return env


if __name__ == "__main__":
    import json

    _common.load_env()
    cases = (
        ("urate x gout",
         ["urate", "uric acid", "urate levels"], ["gout"], "MONDO_0005393"),
        ("glycine x coronary artery disease",
         ["glycine"], ["coronary artery disease", "coronary heart disease"],
         "MONDO_0005010"),
    )
    for title, metabolite, disease, efo in cases:
        start = time.time()
        env = get_colocalisation(
            metabolite,
            disease,
            efo,
        )
        block = env["data"]
        print("=" * 78)
        print(f"{title}: status={env['status']}  {time.time() - start:.1f}s  "
              f"{len(block['queries'])} request(s)")
        print(f"  studies searched   : "
              + "; ".join(f"{row['id']} ({row['trait']}, nCases {row['n_cases']}, "
                          f"{row['n_sets_examined']}/{row['n_sets_in_source']} sets)"
                          for row in block["studies_searched"]))
        print(f"  sets examined      : {block['n_sets_examined']}  "
              f"partner rows read {block['coloc_rows_read']} of "
              f"{block['coloc_rows_available']}")
        print(f"  metabolite hits    : {block['n_metabolite_hits']}  "
              f"best H4 {block['best_h4']}")
        for hit in block["metabolite_hits"][:5]:
            print(f"    H4 {hit['h4']}  CLPP {hit['clpp']}  {hit['method']}  "
                  f"chr{hit['chromosome']}:{hit['position']} ({hit['variant_id']})  "
                  f"{hit['locus_study_id']} x {hit['partner_study_id']} "
                  f"'{hit['partner_trait']}'  nvar {hit['n_coloc_variants']}")
        print(f"  molecular QTL hits : {block['n_qtl_hits']}  genes {block['genes'][:8]}")
        for hit in block["qtl_hits"][:3]:
            print(f"    H4 {hit['h4']}  {hit['gene_symbol']} ({hit['right_study_type']})  "
                  f"chr{hit['chromosome']}:{hit['position']}  {hit['partner_trait']}")
        for caveat in env["caveats"]:
            print("  caveat:", caveat)
        print(json.dumps(
            block["metabolite_hits"][:1],
            indent       = 2,
            ensure_ascii = False,
        ))
