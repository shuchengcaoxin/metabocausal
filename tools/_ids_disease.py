"""1A disease half: name -> ontology id, plus the OLS4 client the metabolite half reuses.

Jingrui's `code/resolve_diseases.py`, integrated. Her structure survives intact -
`normalize` / `load_disease_overrides` / `search_ols4` / `pick_best_match` /
`resolve_disease`, in that order, with the same names - and the metabolite module still
imports the shared pieces from here, exactly as her `resolve_metabolites.py` did. What
changed is listed in team-admin/1A1D_集成与交互_验收_2026-09-11.md against the review
findings; the three rules worth knowing before reading the code are these.

THE TWO-USE SYNONYM RULE. OLS4 exposes two synonym fields: `exact_synonyms`
(hasExactSynonym only) and `synonym` (the union, including related / narrow / broad).
They are used for two different jobs and must not be mixed.
  * CHOOSING an id: only the term's label and its `exact_synonyms` are ever compared
    locally. A related synonym never decides which entity the user meant - 'stroke' is a
    related synonym of a dozen terms. The server-side `exact=true&queryFields=label,
    synonym` query is what covers the fuller field, and a term that only OLS4's own exact
    matcher can vouch for is recorded as match_method='exact_ols4', never promoted to
    'exact_synonym'.
  * EMITTING the synonym list 1B/1C exact-match against: the union IS included, related
    synonyms and all, because a GWAS trait string is free text and the point of the list
    is to cover its spellings. Entries shorter than MIN_SYNONYM_CHARS are dropped ('G',
    'TG' would match noise), except the user's own input and the ontology label, which
    are always kept as the two anchors.

ENTITY CLASS BEFORE MATCH QUALITY, MATCH QUALITY BEFORE ONTOLOGY PREFIX. A disease
ontology term (MONDO / DOID / EFO) outranks an HP phenotype record whatever matched:
that is what keeps 'stroke' on MONDO:0005098 rather than HP:0001297. Within one class an
exact LABEL hit outranks an exact SYNONYM hit: that is what moves 'metabolic syndrome'
off the rare MONDO:0000816 lipodystrophy and onto EFO:0000195. Only then does the
MONDO/DOID preference break a tie, and only then the id string - and when the id string
is the last thing separating two candidates they are both reported and the result is
ambiguous, because that is a coin flip, not a decision.

HP IS AN ACCEPTED THIRD CLASS. When no MONDO/DOID/EFO term matches exactly, an HP
phenotype record is used rather than nothing (insulin resistance and hypercholesterolemia
have no non-Mendelian disease term in OLS4). The result then carries
entity_type='phenotype' and a caveat saying so, and that caveat reaches the card.

Leading underscore = internal module, not a tool. `tools/ids.py` is the entry point.
"""

from __future__ import annotations

import csv
import http.client
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from . import _common
except ImportError:                                    # running: python tools/_ids_disease.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _common

# One normalization rule for the whole project. `_common.normalize` is character for
# character what Jingrui's `normalize()` did (casefold + collapse whitespace); importing
# it instead of keeping a second copy is what stops 1A and 1B drifting apart.
normalize = _common.normalize

DEFAULT_DISEASE_OVERRIDES = REPO_ROOT / "data" / "synonyms_disease.csv"

OLS4_SEARCH_URL = "https://www.ebi.ac.uk/ols4/api/search"
OLS4_TERMS_URL = "https://www.ebi.ac.uk/ols4/api/ontologies/{ontology}/terms"

# `synonym` is the field the default OLS4 response does NOT include. Without it the
# project sees 210 synonym strings where OLS4 holds 408, and 'L-carnitine' misses
# CHEBI:16347 entirely.
OLS4_FIELD_LIST = (
    "iri,label,obo_id,short_form,ontology_name,description,synonym,exact_synonyms"
)
OLS4_EXACT_QUERY_FIELDS = "label,synonym"
RELEVANCE_ROWS = 50

DISEASE_PREFIXES = ("MONDO:", "DOID:", "EFO:")
PREFERRED_DISEASE_PREFIXES = ("MONDO:", "DOID:")
PHENOTYPE_PREFIXES = ("HP:",)

# THE ID FAST PATH. A user who types CHEBI:17775 has already done this module's job, so
# the shape test below runs before the override table and before any search: the id goes
# straight to the term endpoint. That removes both ways a name can go wrong - there is no
# relevance window to fall out of and no synonym hit to pick the wrong entity with - and
# it is the only path where `ambiguous` is False by construction.
#
# Case is normalised because the prefix is the ontology's spelling, not the user's, and
# the underscore separator is accepted because that is the form Open Targets URLs and 1E's
# own arguments carry (see _common.underscore_ontology_id): a user pasting one of those
# has still named an entity exactly.
ONTOLOGY_ID_PREFIXES = ("CHEBI", "MONDO", "DOID", "EFO", "HP")
DISEASE_ID_PREFIXES = DISEASE_PREFIXES + PHENOTYPE_PREFIXES
METABOLITE_ID_PREFIXES = ("CHEBI:",)
_ONTOLOGY_ID = re.compile(
    r"^(" + "|".join(ONTOLOGY_ID_PREFIXES) + r")[:_](\d+)$",
    re.IGNORECASE,
)

MIN_SYNONYM_CHARS = 3
MAX_ID_CANDIDATES = 5

# exact_label and exact_synonym are decided here, against label and exact_synonyms only.
# exact_ols4 is OLS4's own verdict from the exact=true query: the string is an exact
# match on the fuller `synonym` field, which this module deliberately never compares
# against locally. Rank order = the order of this tuple.
MATCH_QUALITY = ("exact_label", "exact_synonym", "exact_ols4")

PHENOTYPE_CAVEAT = (
    "{input!r} resolved to {id} ({label}), an HP phenotype, not a disease entity. No "
    "MONDO/DOID/EFO disease term matches this name exactly in OLS4."
)
OVERRIDE_TERM_CAVEAT = (
    "The OLS4 record for the override id {id} could not be retrieved ({detail}), so its "
    "synonyms come from the shipped override table only and may be behind the ontology."
)
OVERRIDE_TABLE_CAVEAT = (
    "The {kind} override table {name} could not be read ({detail}); curated ids are NOT "
    "being applied for this call."
)
THIN_SYNONYM_CAVEAT = (
    "{kind} {input!r} resolved to {id} but only {count} trait spelling(s) are available; "
    "an absence of evidence downstream may reflect a thin synonym list, not an absence "
    "of effect."
)
ID_INPUT_CAVEAT = (
    "{input!r} was read as an ontology id, not as a name: {id} was fetched directly from "
    "OLS4 and no name search ran. Every trait spelling below comes from that one record."
)
ID_WRONG_SIDE_CAVEAT = (
    "{input!r} is not a {kind} identifier ({expected} expected), so it was not resolved. "
    "That is a wrong-side id, not a statement about the entity it names."
)
ID_NOT_FOUND_CAVEAT = (
    "Ontology id {id} was not found in OLS4 ({ontology}). An unknown, withdrawn or "
    "mistyped id is a lookup failure, not an absence of evidence."
)

# urllib is gone - every request goes through _common.get_json, so TLS-intercepting
# proxies, timeouts and the 429/5xx retry behave the same as in every other tool. The
# tuple stays wide anyway: OSError covers URLError/HTTPError/TimeoutError/
# RemoteDisconnected/ConnectionReset, ValueError covers JSONDecodeError and
# UnicodeDecodeError, HTTPException covers IncompleteRead.
HANDLED = (_common.RequestFailed, OSError, ValueError, http.client.HTTPException)

# Override tables are read once per file version, not once per call. The key carries
# mtime and size so a curator editing the CSV mid-session is picked up immediately.
_OVERRIDE_CACHE: dict = {}


# ---------------------------------------------------------------- strings

def merge_synonyms(*groups: list) -> list:
    """Merge synonym lists while preserving order and ignoring case duplicates.

    Jingrui's function, unchanged: it is the one place that decides two spellings are
    the same string, and both halves of 1A call it."""
    merged: list = []
    seen: set = set()
    for group in groups:
        for value in group or []:
            key = normalize(value)
            if key and key not in seen:
                seen.add(key)
                merged.append(value)
    return merged


def downstream_synonyms(anchors: list, *groups: list) -> list:
    """Build the list 1B/1C exact-match against: the anchors first, then everything else.

    `anchors` are the strings that are kept whatever their length - the user's own input
    and the ontology label. Every other entry shorter than MIN_SYNONYM_CHARS after strip
    is dropped, because a one- or two-character token ('G' for glycine, 'TG' for
    triglycerides) exact-matches GWAS trait text by accident, not by meaning."""
    long_enough = [
        value
        for group in groups
        for value in (group or [])
        if len(str(value).strip()) >= MIN_SYNONYM_CHARS
    ]
    return merge_synonyms(list(anchors), long_enough)


def ontology_id_shape(text: str) -> str | None:
    """'chebi:17775' and 'CHEBI_17775' -> 'CHEBI:17775'. None when this is not an id.

    A shape test only. It says the string is spelled like an ontology id, never that the
    id exists, and never that it belongs on the side it was typed on - `resolve_disease`
    and `resolve_metabolite` each check the prefix against their own side afterwards."""
    match = _ONTOLOGY_ID.match(str(text or "").strip())
    if match is None:
        return None
    return f"{match.group(1).upper()}:{match.group(2)}"


# ---------------------------------------------------------------- accession shapes
#
# A synonym list exists to be exact-matched against free-text GWAS trait strings, so an
# entry that is a database cross-reference rather than a spelling is dead weight: no
# trait field reads 'CHEBI:17775', 'MFCD00005712' or '69-93-2'. PubChem's synonym
# endpoint mixes the two freely - 64 of the 137 'synonyms' it returns for uric acid are
# cross-references - and MAX_SYNONYMS is binding, so each one kept costs a real
# spelling and the loss shows up downstream as 'no MR evidence' rather than as noise.
#
# The patterns are deliberately conservative: an ambiguous string is KEPT. A dropped
# spelling is an invisible miss; a kept accession only wastes one slot. That is why
# nothing here fires on a short all-caps token ('TMAO', 'URC', 'CLR'), on a molecular
# formula ('C5H4N4O3', 'H2N-CH2-COOH'), or on a name carrying a locant or a chain
# notation ('Cholest-5-en-3beta-ol', 'PC aa C36:0'). SMILES strings are not detected
# either: no test for them is safe against real names, and PubChem does not list them
# in this field.
_ACCESSION_SHAPES = (
    # Registry prefix + numeric body, the shape almost every cross-reference takes:
    # CHEBI:17775, HMDB0000289, DTXSID3042508, CHEMBL792, C00366 (KEGG), NSC-3975,
    # bmse000126, KBio1_000351, NCGC00181032-01, SDCCGMLS-0066864.P001. The body must run
    # to three digits, which is what keeps a name whose digits are locants out of it.
    re.compile(r"^[A-Za-z]{1,12}\d{0,2}[-_:.]?\d{3,}(?:[-_.][A-Za-z0-9]{1,10})*$"),
    # The same, spaced, as PubChem writes the older registries: 'NSC 3975', 'HSDB 495',
    # 'CCRIS 5915', 'BRN 3537113', 'EINECS 200-720-7'. An all-caps prefix is required so
    # that a product name - 'Carniking 50', 'Cholesterol 1551' - is not read as a code.
    re.compile(r"^[A-Z]{2,8} \d{2,}(?:[-_.][A-Za-z0-9]{1,10})*$"),
    # Registry prefix + non-numeric body, where the prefix alone settles it:
    # 'UNII-268B43MJ25', 'CAS-107-43-7', 'EC 200-272-2'.
    re.compile(r"^(?:UNII|CAS|EINECS|EC|HMDB|KEGG|PDB|CID|SID|LIPIDMAPS)[-: ]\S+$"),
    # CAS registry number and EC/EINECS number, both of which PubChem also lists bare.
    re.compile(r"^\d{2,7}-\d{2}-\d$"),
    re.compile(r"^\d{3}-\d{3}-\d$"),
    # A bare UNII: ten upper-case alphanumerics. Three digits are required, because that
    # is what separates a real UNII (they are random: 268B43MJ25, TE7660XO1C, 0G389FZZ9M)
    # from a ten-character molecular formula such as NH2CH2COOH.
    re.compile(r"^(?=(?:\D*\d){3})(?=.*[A-Z])[A-Z0-9]{10}$"),
    # ATC code, e.g. A16AA01 for levocarnitine.
    re.compile(r"^[A-Z]\d{2}[A-Z]{2}\d{2}$"),
    # InChI, InChIKey (PubChem truncates the final block often enough to allow for it),
    # and the bare UUIDs some depositors register as names.
    re.compile(r"^InChI=", re.IGNORECASE),
    re.compile(r"^[A-Z]{14}-[A-Z]{10}(?:-[A-Z])?-?$"),
    re.compile(r"^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$"),
)


def is_accession(value) -> bool:
    """True when this string is a database accession rather than a spelling of the name.

    A shape test, like `ontology_id_shape`, and a wider one: that function answers 'did
    the user type an id?' and must stay narrow, because widening it would send new inputs
    down the id fast path. This one answers 'can this string ever be a GWAS trait?' and
    so covers every registry, not just the five ontologies."""
    text = str(value or "").strip()
    if not text:
        return False
    return any(shape.match(text) for shape in _ACCESSION_SHAPES)


def drop_accessions(values: list) -> list:
    """The list without its cross-references. Order is preserved; nothing is normalized."""
    return [value for value in values or [] if not is_accession(value)]


def wrong_side_result(cleaned: str, kind: str, expected: tuple) -> str:
    """The caveat for an id typed on the wrong side, with the prefixes spelled out."""
    return ID_WRONG_SIDE_CAVEAT.format(
        input    = cleaned,
        kind     = kind,
        expected = ", ".join(prefix.rstrip(":") for prefix in expected),
    )


def normalized_synonyms(synonyms: list) -> list:
    """The same list under the project's normalization rule, so 1B never has to guess
    whether to casefold. Display strings stay in `synonyms`; these are what a literal
    `==` against a normalized trait string is meant to use."""
    merged: list = []
    seen: set = set()
    for value in synonyms or []:
        key = normalize(value)
        if key and key not in seen:
            seen.add(key)
            merged.append(key)
    return merged


# ---------------------------------------------------------------- override table

def _override_rows(path: Path) -> list:
    """Read one override CSV. utf-8-sig, because 'CSV UTF-8' is what Excel writes and a
    BOM turned the first header into '﻿input_synonym' and every call into a bare
    KeyError."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def load_overrides(
    path:      Path,
    kind:      str,
    id_field:  str = "id",
) -> tuple:
    """Return `(mapping, caveats)`.

    The mapping is keyed by the normalized input spelling; each entry carries the
    resolved id and label, the shipped synonym column, the note, and `inputs` - every
    OTHER spelling in the table that resolves to the same id. That reverse index is half
    of the override synonym fix: the table already knows that CAD, CHD, coronary artery
    disease and coronary heart disease are one entity, and hands all four downstream
    instead of echoing the one the user typed.

    A table that cannot be read degrades to an empty mapping plus a caveat naming the
    file - never a traceback out of the tool."""
    key = None
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size, kind, id_field)
        if key in _OVERRIDE_CACHE:
            return _OVERRIDE_CACHE[key]
        rows = _override_rows(path)
    except (OSError, ValueError, csv.Error, UnicodeError) as exc:
        return {}, [OVERRIDE_TABLE_CAVEAT.format(
            kind   = kind,
            name   = path.name,
            detail = f"{type(exc).__name__}: {exc}",
        )]

    inputs_by_id: dict = {}
    try:
        for row in rows:
            inputs_by_id.setdefault(row["resolved_id"], []).append(row["input_synonym"])

        mapping: dict = {}
        for row in rows:
            resolved_id = row["resolved_id"]
            mapping[normalize(row["input_synonym"])] = {
                id_field:   resolved_id,
                "label":    row["resolved_label"],
                "synonyms": [
                    value for value in (row.get("synonyms") or "").split("|") if value.strip()
                ],
                "inputs":   list(inputs_by_id[resolved_id]),
                "note":     (row.get("note") or "").strip(),
            }
    except (KeyError, TypeError, AttributeError) as exc:
        return {}, [OVERRIDE_TABLE_CAVEAT.format(
            kind   = kind,
            name   = path.name,
            detail = f"missing column {exc}",
        )]

    result = (mapping, [])
    if key is not None:
        _OVERRIDE_CACHE[key] = result
    return result


def load_disease_overrides(path: Path = DEFAULT_DISEASE_OVERRIDES) -> dict:
    """Jingrui's public loader name, kept. Caveats are dropped on this path; the
    resolver calls `load_overrides` so a broken table reaches the card."""
    return load_overrides(
        path     = path,
        kind     = "disease",
        id_field = "id",
    )[0]


# ---------------------------------------------------------------- OLS4

def search_ols4(
    name:     str,
    ontology: str = "efo",
    rows:     int = RELEVANCE_ROWS,
    exact:    bool = False,
) -> tuple:
    """One OLS4 search. Returns `(docs, url)` - the URL is returned even on the paths
    that find nothing, because the envelope has to cite the query that was actually sent.

    `exact=True` asks OLS4 to do the matching server-side against label and the full
    synonym field. That is a small, complete answer set; the relevance search is a
    50-row window that put the real 'CAD' match at rank 173."""
    params = {
        "q":         name,
        "ontology":  ontology,
        "rows":      rows,
        "obsoletes": "false",
        "fieldList": OLS4_FIELD_LIST,
    }
    if exact:
        params["exact"] = "true"
        params["queryFields"] = OLS4_EXACT_QUERY_FIELDS

    payload, url = _common.get_json(
        OLS4_SEARCH_URL,
        params  = params,
        headers = {"User-Agent": "MetaboCausal/1A"},
        retries = 1,
    )
    response = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(response, dict) or not isinstance(response.get("docs"), list):
        raise ValueError("OLS4 returned an invalid search response; not a no-match result")
    return response["docs"], url


def term_ols4(obo_id: str, ontology: str) -> tuple:
    """Fetch ONE term by its id. Returns `(record | None, url)`.

    This is the other half of the override synonym fix: the override decides WHICH
    entity, and this call decides how much is known about it. The term endpoint's
    `synonyms` field is the union (exact + related), which is what the downstream list
    wants."""
    payload, url = _common.get_json(
        OLS4_TERMS_URL.format(ontology=ontology),
        params  = {"obo_id": obo_id},
        headers = {"User-Agent": "MetaboCausal/1A"},
        retries = 1,
    )
    terms = payload.get("_embedded", {}).get("terms", []) or []
    return (terms[0] if terms else None), url


def _id(candidate: dict) -> str:
    return str(candidate.get("obo_id") or candidate.get("short_form") or "")


def exact_synonyms(candidate: dict) -> list:
    """hasExactSynonym only. This is the field id CHOICE is allowed to see."""
    values = candidate.get("exact_synonyms") or []
    if isinstance(values, str):
        return [values]
    return [str(value) for value in values]


def all_synonyms(candidate: dict) -> list:
    """exact + related + narrow + broad, as OLS4 returns them. This is the field the
    DOWNSTREAM list is built from - and the search doc and the term record spell it
    differently (`synonym` vs `synonyms`), so both are read."""
    values = candidate.get("synonym")
    if values is None:
        values = candidate.get("synonyms")
    if values is None:
        values = []
    if isinstance(values, str):
        values = [values]
    return merge_synonyms([str(value) for value in values], exact_synonyms(candidate))


def _is_obsolete(candidate: dict) -> bool:
    label = str(candidate.get("label") or "")
    return label.casefold().startswith("obsolete_") or bool(candidate.get("is_obsolete"))


def entity_type_for(identifier: str) -> str:
    """disease / phenotype / other, from the id prefix alone. No claim beyond that."""
    if str(identifier).startswith(DISEASE_PREFIXES):
        return "disease"
    if str(identifier).startswith(PHENOTYPE_PREFIXES):
        return "phenotype"
    return "other"


def _class_rank(identifier: str) -> int:
    kind = entity_type_for(identifier)
    return {"disease": 0, "phenotype": 1}.get(kind, 2)


def _preference(candidate: dict) -> tuple:
    """Jingrui's MONDO/DOID preference, demoted to the tie-break it should always have
    been: it now runs AFTER entity class and match quality, never before them."""
    identifier = _id(candidate)
    return (0 if identifier.startswith(PREFERRED_DISEASE_PREFIXES) else 1, identifier)


def local_match_method(candidate: dict, wanted: str) -> str | None:
    """exact_label, exact_synonym, or None. Related synonyms are not consulted."""
    if normalize(candidate.get("label")) == wanted:
        return "exact_label"
    if any(normalize(synonym) == wanted for synonym in exact_synonyms(candidate)):
        return "exact_synonym"
    return None


def pick_best_match(
    candidates: list,
    query:      str,
    exact:      bool = False,
) -> dict | None:
    """Choose one term, or say plainly that nothing matched.

    `exact=True` means the candidates came from OLS4's exact query, so a candidate this
    module cannot classify locally is still a genuine exact match on the full synonym
    field and is kept as 'exact_ols4'. In the relevance fallback the same candidate is
    not a match at all - there, only label and exact_synonyms count.

    Returns {candidate, match_method, ambiguous, id_candidates}. `ambiguous` is True when
    two candidates survive at the same (class, quality, preference) rank, i.e. when the
    only thing left separating them is the accession number."""
    active = [candidate for candidate in candidates if not _is_obsolete(candidate)]
    if not active:
        return None

    wanted = normalize(query)
    scored = []
    for candidate in active:
        method = local_match_method(candidate, wanted)
        if method is None:
            if not exact:
                continue
            method = "exact_ols4"
        scored.append((
            (
                _class_rank(_id(candidate)),
                MATCH_QUALITY.index(method),
            ) + _preference(candidate),
            candidate,
            method,
        ))

    if not scored:
        return {
            "candidate":     active[0],
            "match_method":  "fallback_first",
            "ambiguous":     True,
            "id_candidates": [_id(candidate) for candidate in active[:MAX_ID_CANDIDATES]],
        }

    scored.sort(key=lambda item: item[0])
    best_rank = scored[0][0][:-1]                      # everything except the id string
    tied = [item for item in scored if item[0][:-1] == best_rank]

    return {
        "candidate":     scored[0][1],
        "match_method":  scored[0][2],
        "ambiguous":     len(tied) > 1,
        "id_candidates": [_id(item[1]) for item in scored[:MAX_ID_CANDIDATES]],
    }


def resolve_candidates(name: str, ontology: str) -> tuple:
    """OLS4's exact query first, the relevance window only if it returns nothing.

    Returns `(candidates, urls, exact_used)`. After this, `fallback_first` genuinely
    means 'no exact match exists anywhere in this ontology', not 'no exact match in the
    first 50 relevance-ranked rows'."""
    urls = []
    candidates, url = search_ols4(
        name     = name,
        ontology = ontology,
        rows     = RELEVANCE_ROWS,
        exact    = True,
    )
    urls.append(url)
    if candidates:
        return candidates, urls, True

    candidates, url = search_ols4(
        name     = name,
        ontology = ontology,
        rows     = RELEVANCE_ROWS,
        exact    = False,
    )
    urls.append(url)
    return candidates, urls, False


# ---------------------------------------------------------------- note convention

def note_caveats(note: str, subject: str) -> tuple:
    """A curator's note is evidence, not decoration. Returns `(caveats, force_ambiguous)`.

    A note beginning PROVISIONAL says the curator is not sure: it reaches the card AND
    forces ambiguous=True. A note beginning CAVEAT: is a known, accepted approximation:
    it reaches the card and nothing else. Every other note is kept verbatim in the result
    (`note`) but not pushed onto the card, so four routine 'Verified override' lines do
    not bury the two that matter."""
    text = (note or "").strip()
    if not text:
        return [], False
    if text.upper().startswith("PROVISIONAL"):
        return [f"{subject}: {text}"], True
    if text.upper().startswith("CAVEAT:"):
        return [f"{subject}: {text}"], False
    return [], False


# ---------------------------------------------------------------- the resolver

def _empty_disease(
    name:   str,
    status: str = "empty",
    method: str = "no_match",
) -> dict:
    return {
        "input":               name,
        "label":               None,
        "id":                  None,
        "entity_type":         None,
        "synonyms":            [],
        "synonyms_normalized": [],
        "match_method":        method,
        "ambiguous":           True,
        "status":              status,
        "note":                "",
        "id_candidates":       [],
        "caveats":             [],
        "queries":             [],
    }


def resolve_disease(name: str, overrides: dict | None = None) -> dict:
    """Resolve one disease name to a MONDO/DOID/EFO id, or to an HP phenotype when the
    disease ontologies have nothing, preserving every uncertainty on the way."""
    cleaned = " ".join(str(name or "").split())
    if not cleaned:
        return _empty_disease(name)

    identifier = ontology_id_shape(cleaned)
    if identifier is not None:
        return _from_ontology_id(
            name       = name,
            cleaned    = cleaned,
            identifier = identifier,
            ontology   = "efo",
        )

    caveats: list = []
    queries: list = []

    if overrides is None:
        overrides, table_caveats = load_overrides(
            path     = DEFAULT_DISEASE_OVERRIDES,
            kind     = "disease",
            id_field = "id",
        )
        caveats.extend(table_caveats)

    override = overrides.get(normalize(cleaned))
    if override:
        result = _from_override(
            name     = name,
            cleaned  = cleaned,
            override = override,
            ontology = "efo",
        )
        result["caveats"] = caveats + result["caveats"]
        return result

    try:
        candidates, queries, exact_used = resolve_candidates(cleaned, "efo")
    except HANDLED as exc:
        result = _empty_disease(
            name   = name,
            status = "error",
            method = "error",
        )
        failed_url = getattr(exc, "url", None)
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["caveats"] = caveats
        result["queries"] = [failed_url] if failed_url else []
        return result

    match = pick_best_match(
        candidates = candidates,
        query      = cleaned,
        exact      = exact_used,
    )
    if match is None:
        result = _empty_disease(name)
        result["caveats"] = caveats
        result["queries"] = queries
        return result

    candidate = match["candidate"]
    identifier = _id(candidate) or None
    label = candidate.get("label")
    synonyms = downstream_synonyms(
        [cleaned, label or ""],
        all_synonyms(candidate),
    )
    entity_type = entity_type_for(identifier or "")

    if entity_type == "phenotype":
        caveats.append(PHENOTYPE_CAVEAT.format(
            input = cleaned,
            id    = identifier,
            label = label,
        ))

    return {
        "input":               name,
        "label":               label,
        "id":                  identifier,
        "entity_type":         entity_type,
        "synonyms":            synonyms,
        "synonyms_normalized": normalized_synonyms(synonyms),
        "match_method":        match["match_method"],
        "ambiguous":           match["ambiguous"],
        "status":              "ok" if identifier else "empty",
        "note":                "",
        "id_candidates":       match["id_candidates"],
        "caveats":             caveats,
        "queries":             queries,
    }


def _from_ontology_id(
    name:       str,
    cleaned:    str,
    identifier: str,
    ontology:   str,
) -> dict:
    """Build a disease result from an id the user typed.

    An explicit id is authoritative about WHICH entity and says nothing about how much is
    known about it - exactly the override table's rule - so the ontology record still
    supplies the label and every trait spelling. The id string itself is deliberately NOT
    an anchor: no GWAS trait field reads 'MONDO:0005393', and putting it in the synonym
    list would only pad the card with a string that can never match.

    A CHEBI id here is a wrong-side id: it is refused rather than looked up in efo, so a
    swapped pair fails as a swapped pair instead of as a missing disease."""
    if not identifier.startswith(DISEASE_ID_PREFIXES):
        result = _empty_disease(name)
        result["caveats"] = [wrong_side_result(cleaned, "disease", DISEASE_ID_PREFIXES)]
        return result

    try:
        record, url = term_ols4(identifier, ontology)
    except HANDLED as exc:
        result = _empty_disease(
            name   = name,
            status = "error",
            method = "error",
        )
        failed_url = getattr(exc, "url", None)
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["queries"] = [failed_url] if failed_url else []
        return result

    if record is None:
        result = _empty_disease(name)
        result["caveats"] = [ID_NOT_FOUND_CAVEAT.format(
            id       = identifier,
            ontology = ontology,
        )]
        result["queries"] = [url]
        return result

    label = record.get("label")
    synonyms = downstream_synonyms([label or ""], all_synonyms(record))
    entity_type = entity_type_for(identifier)

    caveats = [ID_INPUT_CAVEAT.format(
        input = cleaned,
        id    = identifier,
    )]
    if entity_type == "phenotype":
        caveats.append(PHENOTYPE_CAVEAT.format(
            input = cleaned,
            id    = identifier,
            label = label,
        ))

    return {
        "input":               name,
        "label":               label,
        "id":                  identifier,
        "entity_type":         entity_type,
        "synonyms":            synonyms,
        "synonyms_normalized": normalized_synonyms(synonyms),
        "match_method":        "ontology_id",
        "ambiguous":           False,
        "status":              "ok",
        "note":                "",
        "id_candidates":       [identifier],
        "caveats":             caveats,
        "queries":             [url],
    }


def _from_override(
    name:     str,
    cleaned:  str,
    override: dict,
    ontology: str,
) -> dict:
    """Build a disease result from an override row.

    The override is authoritative for the id and the label and for NOTHING else. The
    synonym list is the union of: the user's input, the override label, every other input
    spelling in the table that maps to this id, the table's own synonyms column, and the
    live OLS4 record of the id. An override fixes which entity is chosen; it must never
    shrink how much is known about it."""
    caveats: list = []
    queries: list = []
    identifier = override["id"]

    record = None
    try:
        record, url = term_ols4(identifier, ontology)
        queries.append(url)
    except HANDLED as exc:
        caveats.append(OVERRIDE_TERM_CAVEAT.format(
            id     = identifier,
            detail = f"{type(exc).__name__}: {exc}",
        ))

    label = override["label"]
    ontology_synonyms: list = []
    if record is not None:
        label = record.get("label") or label
        ontology_synonyms = all_synonyms(record)

    synonyms = downstream_synonyms(
        [cleaned, label or ""],
        override.get("inputs") or [],
        override.get("synonyms") or [],
        ontology_synonyms,
    )

    note_lines, note_forces = note_caveats(
        note    = override.get("note", ""),
        subject = f"{cleaned!r} -> {identifier}",
    )
    caveats.extend(note_lines)

    entity_type = entity_type_for(identifier)
    if entity_type == "phenotype":
        caveats.append(PHENOTYPE_CAVEAT.format(
            input = cleaned,
            id    = identifier,
            label = label,
        ))

    return {
        "input":               name,
        "label":               label,
        "id":                  identifier,
        "entity_type":         entity_type,
        "synonyms":            synonyms,
        "synonyms_normalized": normalized_synonyms(synonyms),
        "match_method":        "override_table",
        "ambiguous":           note_forces,
        "status":              "ok",
        "note":                override.get("note", ""),
        "id_candidates":       [identifier],
        "caveats":             caveats,
        "queries":             queries,
    }


if __name__ == "__main__":
    import json

    for query in ("coronary artery disease", "metabolic syndrome", "insulin resistance"):
        print(json.dumps(
            resolve_disease(query),
            indent       = 2,
            ensure_ascii = False,
        ))
