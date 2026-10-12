"""The trait vocabulary layer: one interface over two GWAS metadata sources.

EpiGraphDB and OpenGWAS both name their datasets with free text, not with any
identifier 1A can resolve to. So the only honest way to go from "the user typed
glycine" to "this database's dataset" is: take 1A's synonym list, and compare it
EXACTLY (after `normalize`) against the real trait strings the database stores.
That is what `match_datasets` does, and it is the whole contract between 1A and
1B/1C.

Two sources, one shape:
  epigraphdb  data/epigraphdb_traits.json  34,494 Gwas nodes, no key needed (1B)
  opengwas    data/gwasinfo.json           50,056 datasets, needs OPENGWAS_JWT (1C)

`load_vocabulary` returns the same list-of-dicts for either, so nothing downstream
changes when 1C plugs OpenGWAS in.

WHY 1C RE-PULLS A VOCABULARY 1B ALREADY HAS
-------------------------------------------
They are not the same list. EpiGraphDB serves a frozen 2020-10-13 snapshot; gwasinfo
is the live index, 50,056 datasets against 34,494, and it holds all 249 met-d
(Nightingale NMR, UK Biobank) datasets that the 2020 snapshot never saw. Glycine is
the case in point: EpiGraphDB has only met-a-468 (Shin 2014, n=7,802, Metabolon MS,
unit "log10 units"), gwasinfo has that AND met-d-Gly (n=114,972, 2020, NMR, unit
"NA"). Two platforms, two scales, one trait string - keep both, never merge them.
Batches here: met-a 452, met-b 150, met-c 123, met-d 249.

THE TWO SOURCES DIFFER IN TYPES AS WELL AS IN CONTENT
-----------------------------------------------------
EpiGraphDB returns numbers as STRINGS ('2115.0'); gwasinfo returns ints, or omits
the key entirely - only author, build, category, group_name, id, population, sex,
subcategory and trait are present on all 50,056 rows, and sample_size is missing on
3,995. gwasinfo also writes the literal string "NA" where there is no value (unit,
subcategory, consortium, ontology), which is not None and not "". So: read every
field with .get(), coerce before comparing, and treat "NA" as missing.

WHY THE CACHE IS BUILT WITH /cypher AND NOT /meta/nodes/Gwas/list
-----------------------------------------------------------------
The REST list endpoint caps `limit` at 2000 (limit=5000 -> HTTP 422), so a full pull
of the 34,494 Gwas nodes is 18 paged requests against 7 by /cypher. It is also not
dependable: on 2026-09-09 it returned HTTP 500 past offset 10000, exposing only 29%
of the vocabulary (the first 10,000 rows) and hiding the other 71% with no error;
re-tested on 2026-09-10 it returned HTTP 200 at every offset. A truncation you cannot
see is worse than an error, and an endpoint that truncates only sometimes is worse
than either, so the pull goes through /cypher, which pages cleanly to the end.
Glycine (met-a-468) sits at position 29,674 - inside the range that was hidden.

Leading underscore = internal module, not a tool. It is never registered in TOOLS.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

try:
    from ._common import RequestFailed, get_json, load_env, normalize
except ImportError:                                    # running: python tools/_traits.py
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _common import RequestFailed, get_json, load_env, normalize

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"

VOCABULARY_PATHS = {
    "epigraphdb": DATA_DIR / "epigraphdb_traits.json",
    "opengwas":   DATA_DIR / "gwasinfo.json",
}

# The canonical field names. EpiGraphDB's cypher aliases already use them; OpenGWAS's
# gwasinfo uses longer names and is mapped onto them on load.
VOCABULARY_FIELDS = ("id", "trait", "n", "pop", "cat", "sub", "year", "ncase", "ncontrol", "unit")

_OPENGWAS_FIELD_MAP = {
    "id":       "id",
    "trait":    "trait",
    "n":        "sample_size",
    "pop":      "population",
    "cat":      "category",
    "sub":      "subcategory",
    "year":     "year",
    "ncase":    "ncase",
    "ncontrol": "ncontrol",
    "unit":     "unit",
}

SNAPSHOT = "EpiGraphDB Gwas nodes (OpenGWAS 2020-10-13 snapshot)"
OPENGWAS_SNAPSHOT = "OpenGWAS gwasinfo (live dataset index)"

GWASINFO_URL = "https://api.opengwas.io/api/gwasinfo"
GWASINFO_TIMEOUT_SECONDS = 180

CYPHER_URL = "https://api.epigraphdb.org/cypher"
CYPHER_PAGE_SIZE = 5000
CYPHER_QUERY = (
    "MATCH (n:Gwas) RETURN n.id AS id, n.trait AS trait, n.sample_size AS n, "
    "n.population AS pop, n.category AS cat, n.subcategory AS sub, n.year AS year, "
    "n.ncase AS ncase, n.ncontrol AS ncontrol, n.unit AS unit "
    "SKIP {skip} LIMIT {limit}"
)

_CACHE: dict[str, list] = {}


def _canonical(row: dict, field_map: dict) -> dict:
    return {name: row.get(field_map[name]) for name in VOCABULARY_FIELDS}


def _opengwas_row(row: dict) -> dict:
    """The canonical ten fields, over the top of the raw gwasinfo record kept whole.

    The shared ten do not carry `build`, `author`, `consortium` or `nsnp`, and 1C has
    to report those per dataset, so nothing is thrown away here: the canonical names
    win, every other gwasinfo field survives under its own name. `n` and `sample_size`
    therefore hold the same value - by design, so both spellings work.
    """
    return {**row, **_canonical(row, _OPENGWAS_FIELD_MAP)}


def load_vocabulary(source: str = "epigraphdb") -> list:
    """Load the cached trait vocabulary for one source and cache it in memory.

    Returns a list of dicts with keys id, trait, n, pop, cat, sub, year, ncase,
    ncontrol, unit - the same shape for either source, so `match_datasets` and
    `unique_traits` work on both unchanged. Raises FileNotFoundError if that source
    has not been cached yet.

    "opengwas" rows carry those ten PLUS every other raw gwasinfo field (build,
    author, consortium, nsnp, pmid, sex, ...), because 1C reports them per dataset.
    Values are kept exactly as the source wrote them: gwasinfo omits keys rather than
    nulling them and writes the literal "NA" for absent text, EpiGraphDB returns its
    numbers as strings.
    """
    key = str(source).strip().lower()
    if key in _CACHE:
        return _CACHE[key]

    if key not in VOCABULARY_PATHS:
        raise ValueError(
            f"Unknown vocabulary source {source!r}; expected one of {sorted(VOCABULARY_PATHS)}"
        )

    path = VOCABULARY_PATHS[key]
    if not path.exists():
        if key == "opengwas":
            raise FileNotFoundError(
                f"{path} does not exist yet. Rebuild it with "
                f"tools._traits.build_opengwas_vocabulary(), which pulls "
                f"GET {GWASINFO_URL} and needs OPENGWAS_JWT in the .env above the repo "
                f"root. Until then use load_vocabulary('epigraphdb')."
            )
        raise FileNotFoundError(
            f"{path} does not exist. Rebuild it with "
            f"tools._traits.build_epigraphdb_vocabulary() (a few minutes, no key needed)."
        )

    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    rows = list(payload.values()) if isinstance(payload, dict) else list(payload)

    if key == "opengwas":
        vocabulary = [_opengwas_row(row) for row in rows]
    else:
        vocabulary = [{name: row.get(name) for name in VOCABULARY_FIELDS} for row in rows]

    _CACHE[key] = vocabulary
    return vocabulary


def build_epigraphdb_vocabulary(path=VOCABULARY_PATHS["epigraphdb"]) -> int:
    """Pull every EpiGraphDB Gwas node through /cypher, write it to `path` as JSON,
    and return how many rows were written.

    Pages by SKIP/LIMIT until a short page comes back, so the count is a true total,
    not a lower bound. No key needed. Run this to refresh the snapshot; day to day,
    `load_vocabulary` just reads the file.
    """
    target = Path(path)
    rows, skip = [], 0

    while True:
        payload, _ = get_json(
            CYPHER_URL,
            method    = "POST",
            json_body = {"query": CYPHER_QUERY.format(skip=skip, limit=CYPHER_PAGE_SIZE)},
            headers   = {"Content-Type": "application/json"},
            timeout   = 120,
        )
        page = payload.get("results", []) or []
        rows.extend({name: row.get(name) for name in VOCABULARY_FIELDS} for row in page)
        if len(page) < CYPHER_PAGE_SIZE:
            break
        skip += CYPHER_PAGE_SIZE

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(
            rows,
            handle,
            ensure_ascii = False,
        )

    _CACHE.pop("epigraphdb", None)
    return len(rows)


def build_opengwas_vocabulary(path=VOCABULARY_PATHS["opengwas"]) -> int:
    """Pull the whole OpenGWAS dataset index through GET /api/gwasinfo, write it to
    `path` as JSON, and return how many rows were written.

    One request, no paging - the endpoint hands back the entire index (~19 MB, 50,056
    datasets on 2026-09-10), and it answers with a DICT KEYED BY DATASET ID, not a
    list, so it is converted here. Every raw field is kept; `load_vocabulary` maps the
    ten canonical names on top when it reads the file back.

    Needs OPENGWAS_JWT, taken from the environment or from the .env above the repo
    root via `_common.load_env()`, and sent in the Authorization header only. The token
    never reaches the URL, the file, the return value or an exception message. Raises
    RuntimeError when it is absent, RequestFailed when the pull fails.
    """
    load_env()
    token = (os.environ.get("OPENGWAS_JWT") or "").strip()
    # Printable ASCII only. requests validates a header value while PREPARING the
    # request and its InvalidHeader message quotes the value in full, so a token
    # carrying an interior line break would print itself in the traceback.
    if not token or not re.fullmatch(r"[!-~]+", token):
        raise RuntimeError(
            "OPENGWAS_JWT is not set, or carries a character that cannot go in an HTTP "
            "header. Put it in the .env above the repo root (see .env.example); every "
            "api.opengwas.io endpoint answers 401 without a usable token. Nothing was "
            "written, and the value is never quoted here."
        )

    payload, _ = get_json(
        GWASINFO_URL,
        headers = {"Authorization": f"Bearer {token}"},
        timeout = GWASINFO_TIMEOUT_SECONDS,
    )
    rows = list(payload.values()) if isinstance(payload, dict) else list(payload or [])

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(
            rows,
            handle,
            ensure_ascii = False,
        )

    _CACHE.pop("opengwas", None)
    return len(rows)


def match_datasets(synonyms: list, vocabulary: list) -> list:
    """Match 1A's synonym list against a vocabulary by EXACT normalized trait string.

    `normalize(synonym) == normalize(row["trait"])` and nothing looser - no substring,
    no fuzzy, no invented spellings. One synonym can hit several datasets (different
    cohorts measuring the same thing); a dataset is returned once, under the first
    synonym that hit it. Each returned row carries the vocabulary fields plus
    `matched_synonym`, so a card can say WHICH spelling matched.

    An empty list means "no dataset in this snapshot is named any of these strings".
    It does NOT mean the trait was never studied.
    """
    index: dict[str, list] = {}
    for row in vocabulary or []:
        key = normalize(row.get("trait"))
        if key:
            index.setdefault(key, []).append(row)

    matches, seen = [], set()
    for synonym in synonyms or []:
        for row in index.get(normalize(synonym), ()):
            identifier = row.get("id")
            if identifier in seen:
                continue
            seen.add(identifier)
            matches.append({**row, "matched_synonym": synonym})
    return matches


def unique_traits(matches: list) -> list:
    """The distinct trait spellings in `match_datasets` output, in order of first
    appearance. These are the exact strings to send as exposure_trait / outcome_trait -
    the database's own spelling, never the user's."""
    traits, seen = [], set()
    for row in matches or []:
        trait = row.get("trait")
        if trait and trait not in seen:
            seen.add(trait)
            traits.append(trait)
    return traits


if __name__ == "__main__":
    PROBES = [
        ("glycine",                 ["glycine", "Gly", "aminoacetic acid"]),
        ("urate",                   ["urate", "uric acid"]),
        ("coronary artery disease", ["coronary artery disease", "CAD", "coronary heart disease"]),
        ("nonsense",                ["zzz not a trait zzz"]),
    ]

    for source, snapshot in (("epigraphdb", SNAPSHOT), ("opengwas", OPENGWAS_SNAPSHOT)):
        try:
            vocabulary = load_vocabulary(source)
        except FileNotFoundError as exc:
            print(f"\n=== {source} not cached: {exc}")
            continue

        print(f"\n=== {source}: {len(vocabulary)} rows  ({snapshot})")
        print("first row keys:", sorted(vocabulary[0]))

        for label, synonyms in PROBES:
            matched = match_datasets(synonyms, vocabulary)
            print(f"\n{label}: {len(matched)} dataset(s) -> {unique_traits(matched)}")
            for row in matched[:5]:
                print(f"   {row['id']:<18} {row['trait']!r:<32} n={row['n']} "
                      f"cat={row['cat']} via {row['matched_synonym']!r}")

    # The reason 1C re-pulls a vocabulary 1B already has: met-d is not in the 2020
    # snapshot, so this metabolite has one dataset there and two here.
    both = match_datasets(["glycine"], load_vocabulary("opengwas"))
    print("\nglycine in gwasinfo, one row per platform:")
    for row in both:
        print(f"   {row['id']:<12} n={row['n']:<8} year={row['year']} unit={row['unit']!r} "
              f"author={row.get('author')!r} build={row.get('build')!r}")
