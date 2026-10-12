"""1A metabolite half: name -> ChEBI id + PubChem CID + the synonym list 1B/1C match on.

Jingrui's `code/resolve_metabolites.py`, integrated. Her structure survives: the ordered
`pick_metabolite_match` loops (exact label, then exact synonym - the order her disease
picker was missing), `merge_synonyms`, `lookup_pubchem`, `empty_result`,
`resolve_metabolite`, and the shared OLS4 client still imported from the disease module.

Three behaviours are worth stating out loud because all three were silent failures.

PUBCHEM IS A SEPARATE CLAIM AND IT FAILS SEPARATELY. A PubChem outage used to arrive as
`status: ok, ambiguous: False, caveats: []` while the synonym list collapsed from 221
strings to 5 - which downstream reads as 'no MR evidence', i.e. an evidence gap that is
really an outage. Now an outage sets `pubchem_status='error'`, forces ambiguous, and
emits a caveat that names the degradation; a name PubChem simply does not carry (the
lipid fractions) is `empty` with its own caveat and no ambiguity, because the ChEBI id is
still verified. `pubchem_status` is present on EVERY return path.

A CHEBI MISS DOES NOT COST THE PUBCHEM HALF. The OLS4 failure path used to `return`
before PubChem was attempted, throwing away a CID and a whole synonym list that were
sitting there. It now falls through.

A CROSS-REFERENCE IS NOT A SPELLING. PubChem's synonym field is a mixture of names and
database accessions - 'CHEBI:17775', '69-93-2', 'DTXSID3042508', 'MFCD00005712' - and 64
of the 137 entries it returns for uric acid are the second kind. None can ever match a
GWAS trait string, and with MAX_SYNONYMS binding every one of them was displacing a real
spelling. They are dropped (`_ids_disease.is_accession`) before the cap is applied.

Leading underscore = internal module, not a tool. `tools/ids.py` is the entry point.
"""

from __future__ import annotations

import sys
import threading
import time
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from . import _common, _ids_disease
except ImportError:                                    # running: python tools/_ids_metabolite.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _common
    import _ids_disease

normalize = _ids_disease.normalize
merge_synonyms = _ids_disease.merge_synonyms
downstream_synonyms = _ids_disease.downstream_synonyms
normalized_synonyms = _ids_disease.normalized_synonyms
exact_synonyms = _ids_disease.exact_synonyms
all_synonyms = _ids_disease.all_synonyms
search_ols4 = _ids_disease.search_ols4
term_ols4 = _ids_disease.term_ols4
resolve_candidates = _ids_disease.resolve_candidates
note_caveats = _ids_disease.note_caveats
load_overrides = _ids_disease.load_overrides
ontology_id_shape = _ids_disease.ontology_id_shape
is_accession = _ids_disease.is_accession
drop_accessions = _ids_disease.drop_accessions
HANDLED = _ids_disease.HANDLED

DEFAULT_METABOLITE_OVERRIDES = REPO_ROOT / "data" / "synonyms_metabolite.csv"

PUBCHEM_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_MIN_INTERVAL_SECONDS = 0.2                     # PubChem's documented 5 req/s
MAX_ID_CANDIDATES = _ids_disease.MAX_ID_CANDIDATES

# PubChem returns 221 synonyms for glycine. Everything after the ontology block is
# PubChem's own ordering, so a cap keeps the card and the downstream exact-match loops
# finite. Truncation is always declared in the caveats.
MAX_SYNONYMS = 60

_pubchem_lock = threading.Lock()
_last_pubchem_request = 0.0

PUBCHEM_ERROR_CAVEAT = (
    "PubChem did not answer for {input!r} ({detail}), so no CID was retrieved and the "
    "synonym list carries ontology spellings only. This is a lookup failure, not "
    "evidence that the compound is unknown."
)
PUBCHEM_EMPTY_CAVEAT = (
    "PubChem holds no CID for {input!r} (usual for a measured lipid fraction or a "
    "compound class); the ChEBI id stands and the synonym list is the ontology's."
)
PUBCHEM_AMBIGUOUS_CAVEAT = (
    "PubChem name lookup for {input!r} returned {count} CIDs; the first ({cid}) was "
    "used and its synonyms merged. Treat the CID as provisional."
)
SYNONYM_CAP_CAVEAT = (
    "Synonym list for {input!r} truncated to the first {cap} spellings (ontology first, "
    "then PubChem)."
)


# ---------------------------------------------------------------- PubChem

def _pubchem_url(path: str) -> str:
    return f"{PUBCHEM_BASE_URL}/{path}"


def _pubchem_json(path: str) -> dict:
    """Fetch one PubChem response, respecting the five-requests/second limit.

    Jingrui's throttle, kept, with her urllib call replaced by the project's one HTTP
    path: `_common.get_json` already retries once on 429 and 503 (PubChem's documented
    PUGREST.ServerBusy), and honours the CA-bundle and proxy environment that a
    TLS-intercepting corporate proxy needs."""
    global _last_pubchem_request
    with _pubchem_lock:
        elapsed = time.monotonic() - _last_pubchem_request
        if elapsed < PUBCHEM_MIN_INTERVAL_SECONDS:
            time.sleep(PUBCHEM_MIN_INTERVAL_SECONDS - elapsed)
        try:
            payload, _url = _common.get_json(
                _pubchem_url(path),
                headers = {"User-Agent": "MetaboCausal/1A"},
                retries = 1,
            )
            return payload
        finally:
            _last_pubchem_request = time.monotonic()


def _empty_pubchem(status: str = "empty") -> dict:
    return {
        "cid":            None,
        "cid_candidates": [],
        "synonyms":       [],
        "ambiguous":      True,
        "status":         status,
        "queries":        [],
    }


def lookup_pubchem(name: str) -> dict:
    """Find PubChem CIDs by name and fetch synonyms for the preferred first CID.

    A 404 means PubChem does not know the name - that is `empty`, an answer. Anything
    else is a failure and is raised for the caller to turn into `error`; the two must
    never look the same."""
    encoded_name = urllib.parse.quote(name, safe="")
    cid_path = f"compound/name/{encoded_name}/cids/JSON"
    queries = [_pubchem_url(cid_path)]
    try:
        cid_payload = _pubchem_json(cid_path)
    except _common.RequestFailed as exc:
        if exc.status_code == 404:
            result = _empty_pubchem()
            result["queries"] = queries
            return result
        raise

    identifiers = cid_payload.get("IdentifierList") if isinstance(cid_payload, dict) else None
    if not isinstance(identifiers, dict) or not isinstance(identifiers.get("CID"), list):
        raise ValueError("PubChem returned an invalid CID response; not a no-match result")
    cids = [int(cid) for cid in identifiers["CID"]]
    if not cids:
        result = _empty_pubchem()
        result["queries"] = queries
        return result

    chosen_cid = cids[0]
    synonym_path = f"compound/cid/{chosen_cid}/synonyms/JSON"
    queries.append(_pubchem_url(synonym_path))
    synonym_payload = _pubchem_json(synonym_path)
    block = synonym_payload.get("InformationList") if isinstance(synonym_payload, dict) else None
    if not isinstance(block, dict) or not isinstance(block.get("Information"), list):
        raise ValueError("PubChem returned an invalid synonym response")
    information = block["Information"]
    synonyms = information[0].get("Synonym", []) if information else []
    return {
        "cid":            chosen_cid,
        "cid_candidates": cids,
        "synonyms":       [str(value) for value in synonyms],
        "ambiguous":      len(cids) != 1,
        "status":         "ok",
        "queries":        queries,
    }


# ---------------------------------------------------------------- ChEBI

def load_metabolite_overrides(path: Path = DEFAULT_METABOLITE_OVERRIDES) -> dict:
    """Jingrui's public loader name, kept. Caveats are dropped on this path; the
    resolver calls `load_overrides` so a broken table reaches the card."""
    return load_overrides(
        path     = path,
        kind     = "metabolite",
        id_field = "chebi",
    )[0]


def is_active_chebi(candidate: dict) -> bool:
    """Accept only current ChEBI records."""
    identifier = str(candidate.get("obo_id") or "")
    label = str(candidate.get("label") or "")
    return (
        identifier.startswith("CHEBI:")
        and not label.casefold().startswith("obsolete_")
        and not bool(candidate.get("is_obsolete"))
    )


def pick_metabolite_match(
    candidates: list,
    query:      str,
    exact:      bool = False,
) -> dict | None:
    """Choose an exact ChEBI match, or an explicitly ambiguous fallback.

    Jingrui's ordered tiers, kept - exact label before exact synonym - with two
    additions. When the candidates came from OLS4's `exact=true` query, a term this
    module cannot classify locally is still a real exact match on the full synonym field
    and is taken as `exact_ols4` (that is the tier that finds CHEBI:16347 for
    'L-carnitine' and CHEBI:15724 for 'TMAO'). And when a tier holds more than one term,
    the result is ambiguous: choosing by accession number is a coin flip, not evidence -
    'urate' matches both CHEBI:46819 (urate salt) and CHEBI:17775 that way, which is
    exactly why the override table exists."""
    active = [candidate for candidate in candidates if is_active_chebi(candidate)]
    if not active:
        return None

    wanted = normalize(query)
    tiers = [
        (
            "exact_label",
            [c for c in active if normalize(c.get("label")) == wanted],
        ),
        (
            "exact_synonym",
            [c for c in active if any(normalize(s) == wanted for s in exact_synonyms(c))],
        ),
    ]
    if exact:
        tiers.append(("exact_ols4", list(active)))

    for method, group in tiers:
        if not group:
            continue
        group = sorted(group, key=lambda candidate: str(candidate.get("obo_id") or ""))
        return {
            "candidate":     group[0],
            "match_method":  method,
            "ambiguous":     len(group) > 1,
            "id_candidates": [
                str(candidate.get("obo_id") or "") for candidate in group[:MAX_ID_CANDIDATES]
            ],
        }

    return {
        "candidate":     active[0],
        "match_method":  "fallback_first",
        "ambiguous":     True,
        "id_candidates": [
            str(candidate.get("obo_id") or "") for candidate in active[:MAX_ID_CANDIDATES]
        ],
    }


def empty_result(name: str, status: str = "empty") -> dict:
    """Every key the metabolite result ever has, so nothing downstream can KeyError on
    exactly the degraded inputs it was written to detect."""
    return {
        "input":                  name,
        "label":                  None,
        "chebi":                  None,
        "pubchem_cid":            None,
        "pubchem_cid_candidates": [],
        "pubchem_ambiguous":      True,
        "pubchem_status":         None,
        "synonyms":               [],
        "synonyms_normalized":    [],
        "match_method":           "no_match" if status == "empty" else "error",
        "ambiguous":              True,
        "status":                 status,
        "note":                   "",
        "id_candidates":          [],
        "caveats":                [],
        "queries":                [],
    }


def resolve_metabolite(name: str, overrides: dict | None = None) -> dict:
    """Resolve one metabolite name to ChEBI + PubChem, preserving uncertainty."""
    cleaned = " ".join(str(name or "").split())
    if not cleaned:
        return empty_result(name)

    identifier = ontology_id_shape(cleaned)
    if identifier is not None:
        result = _from_ontology_id(
            name       = name,
            cleaned    = cleaned,
            identifier = identifier,
        )
        # PubChem is asked for the resolved LABEL, never for the id string: its name
        # endpoint knows 'uric acid', not 'CHEBI:17775'. An unresolved id has no label to
        # ask with, so the PubChem half is skipped rather than sent a query that can only
        # come back empty and add a misleading caveat.
        if not result["label"]:
            return result
        return _with_pubchem(
            result  = result,
            cleaned = result["label"],
        )

    caveats: list = []

    if overrides is None:
        overrides, table_caveats = load_overrides(
            path     = DEFAULT_METABOLITE_OVERRIDES,
            kind     = "metabolite",
            id_field = "chebi",
        )
        caveats.extend(table_caveats)

    override = overrides.get(normalize(cleaned))
    if override:
        result = _from_override(
            name     = name,
            cleaned  = cleaned,
            override = override,
        )
    else:
        result = _from_ols4(
            name    = name,
            cleaned = cleaned,
        )

    result["caveats"] = caveats + result["caveats"]
    return _with_pubchem(
        result  = result,
        cleaned = cleaned,
    )


def _from_override(name: str, cleaned: str, override: dict) -> dict:
    """The override is authoritative for the ChEBI id and the label, and for nothing
    else: the synonym list is still the union of the user's input, the label, every other
    spelling in the table that maps to this id, the table's synonyms column and the live
    OLS4 record."""
    caveats: list = []
    queries: list = []
    identifier = override["chebi"]

    record = None
    try:
        record, url = term_ols4(identifier, "chebi")
        queries.append(url)
    except HANDLED as exc:
        caveats.append(_ids_disease.OVERRIDE_TERM_CAVEAT.format(
            id     = identifier,
            detail = f"{type(exc).__name__}: {exc}",
        ))

    label = override["label"]
    ontology_synonyms: list = []
    if record is not None:
        label = record.get("label") or label
        ontology_synonyms = all_synonyms(record)

    note_lines, note_forces = note_caveats(
        note    = override.get("note", ""),
        subject = f"{cleaned!r} -> {identifier}",
    )
    caveats.extend(note_lines)

    result = empty_result(name, status="ok")
    result.update({
        "label":         label,
        "chebi":         identifier,
        "synonyms":      downstream_synonyms(
            [cleaned, label or ""],
            override.get("inputs") or [],
            override.get("synonyms") or [],
            ontology_synonyms,
        ),
        "match_method":  "override_table",
        "ambiguous":     note_forces,
        "status":        "ok",
        "note":          override.get("note", ""),
        "id_candidates": [identifier],
        "caveats":       caveats,
        "queries":       queries,
    })
    return result


def _from_ontology_id(name: str, cleaned: str, identifier: str) -> dict:
    """Build a metabolite result from a ChEBI id the user typed.

    Same rule as the override table: the id decides WHICH entity and nothing else, so the
    ontology record still supplies the label and the synonyms. The id string is not an
    anchor - no GWAS trait field reads 'CHEBI:17775'.

    A disease id here is a wrong-side id and is refused rather than looked up in chebi, so
    a swapped pair fails as a swapped pair instead of as an unknown metabolite."""
    if not identifier.startswith(_ids_disease.METABOLITE_ID_PREFIXES):
        result = empty_result(name)
        result["caveats"] = [_ids_disease.wrong_side_result(
            cleaned,
            "metabolite",
            _ids_disease.METABOLITE_ID_PREFIXES,
        )]
        return result

    try:
        record, url = term_ols4(identifier, "chebi")
    except HANDLED as exc:
        result = empty_result(name, status="error")
        failed_url = getattr(exc, "url", None)
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["queries"] = [failed_url] if failed_url else []
        return result

    if record is None:
        result = empty_result(name)
        result["caveats"] = [_ids_disease.ID_NOT_FOUND_CAVEAT.format(
            id       = identifier,
            ontology = "chebi",
        )]
        result["queries"] = [url]
        return result

    label = record.get("label")
    synonyms = downstream_synonyms([label or ""], all_synonyms(record))

    result = empty_result(name, status="ok")
    result.update({
        "label":         label,
        "chebi":         identifier,
        "synonyms":      synonyms,
        "match_method":  "ontology_id",
        "ambiguous":     False,
        "status":        "ok",
        "id_candidates": [identifier],
        "caveats":       [_ids_disease.ID_INPUT_CAVEAT.format(
            input = cleaned,
            id    = identifier,
        )],
        "queries":       [url],
    })
    return result


def _from_ols4(name: str, cleaned: str) -> dict:
    """OLS4 chebi lookup. An OLS4 failure returns an error result but does NOT return
    early: the caller still runs the PubChem half."""
    try:
        candidates, queries, exact_used = resolve_candidates(cleaned, "chebi")
    except HANDLED as exc:
        failed_url = getattr(exc, "url", None)
        result = empty_result(name, status="error")
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["queries"] = [failed_url] if failed_url else []
        return result

    match = pick_metabolite_match(
        candidates = candidates,
        query      = cleaned,
        exact      = exact_used,
    )
    if match is None:
        result = empty_result(name)
        result["queries"] = queries
        return result

    candidate = match["candidate"]
    label = candidate.get("label")
    result = empty_result(name, status="ok")
    result.update({
        "label":         label,
        "chebi":         candidate.get("obo_id"),
        "synonyms":      downstream_synonyms(
            [cleaned, label or ""],
            all_synonyms(candidate),
        ),
        "match_method":  match["match_method"],
        "ambiguous":     match["ambiguous"],
        "status":        "ok",
        "id_candidates": match["id_candidates"],
        "queries":       queries,
    })
    return result


def _with_pubchem(result: dict, cleaned: str) -> dict:
    """Run the PubChem half and merge it in, then apply the synonym cap.

    PubChem's status is its own: it never overwrites the ChEBI leg's status, and it never
    passes silently."""
    try:
        pubchem = lookup_pubchem(cleaned)
    except HANDLED as exc:
        result.update({
            "pubchem_cid":            None,
            "pubchem_cid_candidates": [],
            "pubchem_ambiguous":      True,
            "pubchem_status":         "error",
            "pubchem_error":          f"{type(exc).__name__}: {exc}",
            "ambiguous":              True,
        })
        result["caveats"] = result["caveats"] + [PUBCHEM_ERROR_CAVEAT.format(
            input  = cleaned,
            detail = f"{type(exc).__name__}: {exc}",
        )]
        result["synonyms_normalized"] = normalized_synonyms(result["synonyms"])
        return result

    caveats = list(result["caveats"])
    if pubchem["status"] == "empty":
        caveats.append(PUBCHEM_EMPTY_CAVEAT.format(input=cleaned))
    elif pubchem["ambiguous"]:
        caveats.append(PUBCHEM_AMBIGUOUS_CAVEAT.format(
            input = cleaned,
            count = len(pubchem["cid_candidates"]),
            cid   = pubchem["cid"],
        ))

    # Cross-references are dropped BEFORE the cap, not after: PubChem's synonym field
    # carries CHEBI / CAS / DTXSID / UNII / NSC accessions among the spellings, 64 of the
    # 137 entries for uric acid, and MAX_SYNONYMS binds. A slot spent on 'CHEBI:17775' is
    # a spelling that never reaches 1B, and no GWAS trait string it could have matched
    # will ever read as an accession. The ontology half is not filtered: OLS4 records
    # hold names, not xrefs.
    synonyms = merge_synonyms(
        result["synonyms"],
        [
            value
            for value in drop_accessions(pubchem["synonyms"])
            if len(str(value).strip()) >= _ids_disease.MIN_SYNONYM_CHARS
        ],
    )
    if len(synonyms) > MAX_SYNONYMS:
        synonyms = synonyms[:MAX_SYNONYMS]
        caveats.append(SYNONYM_CAP_CAVEAT.format(
            input = cleaned,
            cap   = MAX_SYNONYMS,
        ))

    result.update({
        "pubchem_cid":            pubchem["cid"],
        "pubchem_cid_candidates": pubchem["cid_candidates"],
        "pubchem_ambiguous":      pubchem["ambiguous"],
        "pubchem_status":         pubchem["status"],
        "synonyms":               synonyms,
        "synonyms_normalized":    normalized_synonyms(synonyms),
        "caveats":                caveats,
        "queries":                list(result["queries"]) + pubchem["queries"],
    })
    return result


if __name__ == "__main__":
    import json

    for query in ("glycine", "urate", "L-carnitine", "HDL cholesterol"):
        print(json.dumps(
            resolve_metabolite(query),
            indent       = 2,
            ensure_ascii = False,
        ))
