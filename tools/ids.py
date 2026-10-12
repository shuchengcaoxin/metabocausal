"""1A: the one call that turns two typed names into ids and trait spellings.

Jingrui's `code/resolve_ids.py`, integrated. It runs BEFORE the model - it is not in
TOOLS - and everything after it (1B EpiGraphDB, 1C OpenGWAS / GWAS Catalog, 1D atlas,
1E dossier) consumes its ids and its synonym lists, never the raw input. That is why a
thin or missing synonym list here surfaces downstream as 'no MR evidence' and why every
degradation in this module is written into the envelope instead of being smoothed over.

  from tools.ids import resolve_ids
  env = resolve_ids("glycine", "coronary artery disease")
  env["data"]["metabolite"]["chebi"]     -> 'CHEBI:15428'
  env["data"]["disease"]["synonyms"]     -> display spellings, for the card
  env["data"]["disease"]["synonyms_normalized"] -> what 1B/1C exact-match on

EITHER SIDE ALSO ACCEPTS AN ONTOLOGY ID. `resolve_ids("CHEBI:17775", "MONDO:0005393")`
skips the override table and the name search entirely and fetches each term directly;
`chebi:17775` and `CHEBI_17775` are the same input. That is the one path where
`match_method` is 'ontology_id' and `ambiguous` is False by construction, because the
user has already made the choice this module otherwise has to make for them. An id typed
on the wrong side is refused as a wrong-side id rather than looked up in the other
ontology, so a swapped pair reads as a swapped pair. See `_ids_disease.ontology_id_shape`.

THE MATCH CONTRACT. `synonyms` holds ontology/PubChem casing ('GLYCINE', 'coronary artery
disorder'); GWAS trait fields are Title Case. A literal `==` between the two scores zero
on every demo entity, so the resolver emits `synonyms_normalized` as well -
`_common.normalize` applied to each string - and downstream exact matching uses that
field against a normalized trait string. No tool is left to guess whether to casefold.

STATUS. `ok` only when BOTH legs carry data: an envelope that says ok while
`data.disease.id` is None is how a lookup gap becomes an evidence gap. One empty leg
makes the envelope empty; either leg erroring makes it error. A PubChem outage is
deliberately NOT an error - the ChEBI id still stands - but it forces the metabolite
`ambiguous` flag and writes a caveat naming the degraded synonym list, so nothing reads
as a confident success.

The two halves live in `tools/_ids_disease.py` (which also holds the shared OLS4 client
and the string rules) and `tools/_ids_metabolite.py`, mirroring Jingrui's three-file
split; `resolve_disease` and `resolve_metabolite` are re-exported here.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from . import _common, _ids_disease, _ids_metabolite
except ImportError:                                    # running: python tools/ids.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _common
    import _ids_disease
    import _ids_metabolite

import ledger

resolve_disease = _ids_disease.resolve_disease
resolve_metabolite = _ids_metabolite.resolve_metabolite

SOURCE = "OLS4 (EFO/ChEBI) + PubChem PUG REST"

RETRIEVED_CAVEAT = (
    "Ids and synonyms are retrieved from OLS4 (EFO/ChEBI) and PubChem PUG REST, not "
    "inferred here. Downstream exact matching uses the synonyms_normalized field against "
    "a normalized trait string; synonyms holds the display spellings."
)
UNRESOLVED_CAVEAT = "{kind} {name!r} could not be resolved confidently."
CRASH_CAVEAT = "{kind} lookup for {name!r} failed unexpectedly ({detail})."
THIN_SYNONYM_CAVEAT = _ids_disease.THIN_SYNONYM_CAVEAT
MIN_USEFUL_SYNONYMS = 2


def _record(env: dict) -> dict:
    ledger.record(env)
    return env


def _safe(resolver, name: str, kind: str, empty) -> dict:
    """Run one half. Nothing escapes: `HANDLED` is already caught inside the resolvers,
    and this final catch-all covers a bug in this package the same way, because the
    caller is an agent loop and a traceback there ends the demo."""
    try:
        return resolver(name)
    except Exception as exc:                           # noqa: BLE001 - deliberate boundary
        result = empty(name, status="error")
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["caveats"] = [CRASH_CAVEAT.format(
            kind   = kind,
            name   = name,
            detail = f"{type(exc).__name__}: {exc}",
        )]
        return result


def _empty_disease(name: str, status: str = "error") -> dict:
    return _ids_disease._empty_disease(
        name   = name,
        status = status,
        method = "error" if status == "error" else "no_match",
    )


def resolve_ids(metabolite: str, disease: str) -> dict:
    """Map a metabolite name and a disease name to ChEBI / PubChem and MONDO/DOID/EFO ids
    plus the trait spellings every later tool matches on.

    An input already spelled as an ontology id (CHEBI:17775, MONDO:0005393, either
    separator, any case) is taken as the entity itself: the term is fetched directly and
    no override table or search runs. Everything below describes the name path.

    A hand-curated override table (data/synonyms_metabolite.csv, data/synonyms_disease.csv)
    is consulted first and decides WHICH entity is meant - never how much is known about
    it, so an override still emits the entity's full synonym set. Otherwise OLS4 is asked
    to match exactly, server-side, against label and synonym; only if that finds nothing
    does the relevance search run, so `fallback_first` means no exact match exists.
    Obsolete terms are dropped. A disease ontology term outranks an HP phenotype record,
    an exact label hit outranks an exact synonym hit, and two candidates separated only by
    accession number are reported as ambiguous rather than silently picked. Returns the
    shared eight-key envelope; every later tool uses these ids and synonyms, never the raw
    input."""
    metabolite_result = _safe(
        resolver = resolve_metabolite,
        name     = metabolite,
        kind     = "Metabolite",
        empty    = _ids_metabolite.empty_result,
    )
    disease_result = _safe(
        resolver = resolve_disease,
        name     = disease,
        kind     = "Disease",
        empty    = _empty_disease,
    )

    caveats = [RETRIEVED_CAVEAT]
    caveats.extend(metabolite_result.get("caveats") or [])
    caveats.extend(disease_result.get("caveats") or [])

    for kind, result, id_key in (
        ("Metabolite", metabolite_result, "chebi"),
        ("Disease",    disease_result,    "id"),
    ):
        raw_name = metabolite if kind == "Metabolite" else disease
        if result["ambiguous"]:
            caveats.append(UNRESOLVED_CAVEAT.format(
                kind = kind,
                name = raw_name,
            ))
        if result.get(id_key) and len(result.get("synonyms") or []) < MIN_USEFUL_SYNONYMS:
            caveats.append(THIN_SYNONYM_CAVEAT.format(
                kind  = kind,
                input = raw_name,
                id    = result[id_key],
                count = len(result.get("synonyms") or []),
            ))

    statuses = {metabolite_result["status"], disease_result["status"]}
    if "error" in statuses:
        status = "error"
    elif "empty" in statuses:
        status = "empty"
    else:
        status = "ok"

    queries = list(metabolite_result.get("queries") or []) + list(disease_result.get("queries") or [])

    return _record(_common.envelope(
        tool    = "resolve_ids",
        args    = {
            "metabolite": metabolite,
            "disease":    disease,
        },
        source  = SOURCE,
        url     = queries[0] if queries else _ids_disease.OLS4_SEARCH_URL,
        status  = status,
        data    = {
            "metabolite": metabolite_result,
            "disease":    disease_result,
            "queries":    queries,
        },
        caveats = caveats,
    ))


if __name__ == "__main__":
    import json

    pairs = [
        ("glycine", "coronary artery disease"),
        ("urate", "gout"),
        ("L-carnitine", "metabolic syndrome"),
    ]
    for metabolite_name, disease_name in pairs:
        env = resolve_ids(metabolite_name, disease_name)
        print(json.dumps(
            env,
            indent       = 2,
            ensure_ascii = False,
        ))
