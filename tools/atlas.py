"""Section 1D: effector genes named by published metabolite-GWAS atlases.

Deliverable of section 1D (Ziwei). Reads the pre-built locus-to-gene table
(``data/atlas_locus_gene.csv``) and answers "which gene is the real driver
behind this metabolite?" for the agent loop.

Design rules, taken from ``00_总执行方案`` section 3 and ``1D_给子崴_从零讲清楚``:

* the tool returns the uniform envelope, never a bare list or string;
* ``status`` is exactly one of ``ok`` / ``empty`` / ``error``, and every
  exception is caught here so nothing escapes into the agent loop;
* ``empty`` means "this metabolite is not in the table". It does NOT mean
  "no gene" and it does NOT mean "no effect"; the agent falls back to MVP3
  (Human-GEM) instead;
* an atlas naming a gene is NOT colocalization. Every returned gene carries the
  naming rule its source used, so the card can say "named by atlas X (rule: Y)"
  rather than claiming the association was confirmed here.

The module reads the CSV once into a module-level cache and answers lookups from
memory. It depends only on the standard library.

Table facts that the card must not contradict (from ``1D 备注``):

* ``pos`` is GRCh38 (hg38);
* ``chr`` uses ``23`` for the X chromosome;
* ``metabolite_name`` is kept verbatim from the source supplement, so it
  includes ratio measures (``isoleucine/ X-11529``) and unnamed-compound ids
  (``X-24337``);
* a missing ``gene_symbol`` (``N/A``) means the paper reported the locus but
  named no gene there - 3,265 of the 45,169 shipped rows. Those rows are listed
  under ``data.loci`` and counted in a caveat; they never become a gene;
* ``chebi`` is blank in the shipped table, so lookups land on the name index.

Rows come from Zoodsma 2025 ST5, Chen 2023 ST5 and Shin 2014 ST6.

Integration changes made when this file entered the repo (see the 2026-09-11
acceptance doc): the ledger import now points at the repo's ``ledger`` module,
and the Ensembl column is read under its real name ``ensembl_gene_id``.

Public API
----------
get_effector_genes_atlas(chebi, synonyms, gwascat_env) -> dict
    The section 1D tool; returns the uniform envelope.
load_table(path=None, force=False) -> list[dict]
    Load and cache the atlas table (mainly useful for tests and diagnostics).
"""

from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# The repo layout puts ledger.py at the root, one level above tools/. This mirrors
# what tools/gwascat.py and tools/ids.py do, so `python tools/atlas.py` and
# `python -m unittest discover` both find the same ledger.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ledger  # noqa: E402  (path must be set first)

# --------------------------------------------------------------------------
# Provenance shown on the card. gene_source/year map 1:1 onto these papers.
# --------------------------------------------------------------------------
ATLAS_CITATIONS = {
    "Shin 2014": (
        "Shin SY, Fauman EB, Petersen AK, et al. An atlas of genetic influences on "
        "human blood metabolites. Nat Genet. 2014;46(6):543-550. PMID 24816252."
    ),
    "Chen 2023": (
        "Chen Y, Lu T, Pettersson-Kymmer U, et al. Genomic atlas of the plasma "
        "metabolome prioritizes metabolites implicated in human diseases. "
        "Nat Genet. 2023;55(1):44-53. PMID 36635386."
    ),
    "Zoodsma 2025": (
        "Zoodsma M, Beuchel C, Yasmeen S, et al. A genetic map of human metabolism "
        "across the allele frequency spectrum. Nat Genet. 2025;57(10):2445-2455. "
        "PMID 41044249."
    ),
}

# How each paper decided which gene to name. This is what goes on the card after
# "rule:", and it is what the lead audits against methods_quotes.md.
#
# ``eqtl_coloc`` is kept as a vocabulary entry but no shipped row uses it: the
# Zoodsma 2025 rows were relabelled ``author_prioritized`` on integration, because
# that paper prioritized effector genes from a rare-to-common allele series and did
# not run eQTL colocalization. Calling it coloc would overclaim a method the paper
# never performed.
GENE_SOURCE_RULES = {
    "author_prioritized": "authors prioritized this gene as the effector gene",
    "eqtl_coloc": "authors used eQTL / colocalization evidence",
    "nearest": "authors took the gene nearest the lead SNP",
    "gwas_catalog_mapped": "GWAS Catalog mapped gene for a reported association",
    "unknown": "attribution rule not stated by the source",
}

# The weakest rules need more conservative card wording.
WEAK_RULES = {"nearest", "gwas_catalog_mapped", "unknown"}

RULE_STRENGTH = {
    "author_prioritized": 3,
    "eqtl_coloc": 2,
    "nearest": 1,
    "gwas_catalog_mapped": 1,
    "unknown": 0,
}

# Fallback used to fill the ``atlas`` column if a row ever lacks it. The shipped
# CSV already has this column populated; this only guards against a future row
# that carries a known ``year`` but a blank ``atlas``.
_ATLAS_BY_YEAR = {"2014": "Shin 2014", "2023": "Chen 2023", "2025": "Zoodsma 2025"}

# Values treated as "no data" when read from the CSV (case-insensitive).
_MISSING = {"", "na", "n/a", "nan", "none", "null", "-"}

# Maximum number of genes returned in the envelope's ``data.genes`` list.
MAX_GENES = 10

# Module-level cache, populated by ``load_table``.
_TABLE: list[dict] | None = None
_BY_NAME: dict[str, list[int]] = {}
_BY_CHEBI: dict[str, list[int]] = {}
_TABLE_PATH: Path | None = None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def _candidate_paths() -> list[Path]:
    """Return the ordered list of paths to try when locating the atlas CSV.

    The ``METABOCAUSAL_ATLAS_CSV`` environment variable wins if set, then the
    repo copy under ``data/``, then a copy one directory above the repo (the
    shared briefing folder).
    """
    here = Path(__file__).resolve().parent          # <repo>/tools
    root = here.parent                              # <repo>
    env = os.environ.get("METABOCAUSAL_ATLAS_CSV")
    paths = [Path(env)] if env else []
    paths += [
        root / "data" / "atlas_locus_gene.csv",
        root.parent / "atlas_locus_gene.csv",
    ]
    return paths


def _clean(value: str | None) -> str:
    """Return ``value`` stripped of surrounding whitespace, or ``''`` if None."""
    return (value or "").strip()


def _is_missing(value: str) -> bool:
    """Return True if ``value`` is one of the recognised "no data" markers."""
    return value.strip().lower() in _MISSING


def _norm(name: str) -> str:
    """Return ``name`` lowercased and whitespace-normalised for matching.

    Matching is case-insensitive by design: the table mixes forms such as
    ``Isoleucine`` and ``isoleucine`` across the three atlases. Whitespace
    around a ``/`` is also normalised so the two spellings of a ratio measure
    -- ``Acetylcarnitine/ hexanoylcarnitine`` and
    ``acetylcarnitine/hexanoylcarnitine`` -- collapse to the same key.

    The ``/`` itself is preserved: in these atlases it denotes either a ratio
    measure (``A/B`` = the concentration ratio of A and B) or lipid acyl-chain
    notation (``(18:2/18:2)``). In both cases the whole string is one
    metabolite label and must not be split.
    """
    collapsed = " ".join(name.lower().split())
    # Normalise "a / b", "a/ b", "a /b" -> "a/b" without splitting the token.
    return collapsed.replace(" / ", "/").replace("/ ", "/").replace(" /", "/")


def _name_keys(name: str) -> set[str]:
    """Return the lookup key(s) a row's ``metabolite_name`` is indexed under.

    A metabolite name is treated as one atomic label. In particular a ``/`` is
    NOT a split marker: ``pimeloylcarnitine/3-methyladipoylcarnitine (C7-DC)``
    is the concentration ratio of two metabolites -- a single, distinct measure
    -- and ``(18:2/18:2)`` is lipid acyl-chain notation. Splitting on ``/``
    would let a query for one component wrongly match the ratio row, conflating
    a ratio measure with the metabolite itself.
    """
    key = _norm(name)
    return {key} if key else set()


def load_table(path: Path | None = None, force: bool = False) -> list[dict]:
    """Load the atlas table into the module cache and return its rows.

    The table (about 45k rows) is read once and indexed by metabolite name and
    by ChEBI id. Subsequent calls return the cached rows unless ``force`` is set
    or an explicit ``path`` is given.

    Parameters
    ----------
    path:
        Explicit CSV path. If None, the paths from ``_candidate_paths`` are
        tried in order.
    force:
        Reload even if the cache is already populated.

    Returns
    -------
    list[dict]
        One dict per row, keyed by the 11 schema columns.

    Raises
    ------
    FileNotFoundError
        If no candidate CSV exists. Callers in the tool path catch this and
        convert it into an ``error`` envelope.
    """
    global _TABLE, _BY_NAME, _BY_CHEBI, _TABLE_PATH
    if _TABLE is not None and not force and path is None:
        return _TABLE

    paths = [path] if path else _candidate_paths()
    chosen = next((p for p in paths if p and p.exists()), None)
    if chosen is None:
        raise FileNotFoundError(
            "atlas_locus_gene.csv not found. Looked in: "
            + ", ".join(str(p) for p in paths)
        )

    rows: list[dict] = []
    by_name: dict[str, list[int]] = defaultdict(list)
    by_chebi: dict[str, list[int]] = defaultdict(list)

    with chosen.open(encoding="utf-8-sig", newline="") as fh:
        for raw in csv.DictReader(fh):
            # Tolerate a stray trailing column from an accidental trailing comma.
            raw.pop(None, None)
            row = {k: _clean(v) for k, v in raw.items() if k}
            name = row.get("metabolite_name", "")
            if not name:
                continue
            if not row.get("atlas"):
                row["atlas"] = _ATLAS_BY_YEAR.get(row.get("year", ""), "")
            idx = len(rows)
            rows.append(row)
            for key in _name_keys(name):
                by_name[key].append(idx)
            chebi = row.get("chebi", "")
            if not _is_missing(chebi):
                by_chebi[_norm(chebi)].append(idx)

    _TABLE = rows
    _BY_NAME = dict(by_name)
    _BY_CHEBI = dict(by_chebi)
    _TABLE_PATH = chosen
    return _TABLE


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def _chebi_variants(chebi: str) -> set[str]:
    """Return the set of ChEBI spellings to try for ``chebi``.

    Accepts ``"CHEBI:15428"``, ``"chebi:15428"`` or a bare ``"15428"`` and
    expands to all three forms so the lookup matches regardless of style.
    Returns an empty set for missing input.
    """
    c = _norm(chebi)
    if not c or c in _MISSING:
        return set()
    bare = c.split(":")[-1]
    return {c, bare, f"chebi:{bare}"}


def _lookup_rows(chebi: str, synonyms: list) -> tuple[list[int], str, str]:
    """Find the table rows for a metabolite.

    Matching is attempted in priority order: ChEBI id first, then the first
    synonym as a primary metabolite name, then the remaining synonyms.

    Parameters
    ----------
    chebi:
        ChEBI identifier, possibly empty.
    synonyms:
        Candidate names for the metabolite, most preferred first.

    Returns
    -------
    tuple[list[int], str, str]
        ``(row_indices, matched_on, matched_term)`` where ``matched_on`` is one
        of ``"chebi"``, ``"metabolite_name"``, ``"synonym"`` or ``"none"``.
    """
    load_table()

    for variant in _chebi_variants(chebi or ""):
        if variant in _BY_CHEBI:
            return _BY_CHEBI[variant], "chebi", chebi

    seen: set[str] = set()
    for term in synonyms or []:
        if not isinstance(term, str):
            continue
        key = _norm(term)
        if not key or key in seen:
            continue
        seen.add(key)
        if key in _BY_NAME:
            how = "metabolite_name" if len(seen) == 1 else "synonym"
            return _BY_NAME[key], how, term

    return [], "none", ""


def _extract_gwascat_genes(gwascat_env) -> list[str]:
    """Extract mapped gene symbols from section 1C's GWAS Catalog envelope.

    The exact shape 1C returns is not fixed yet, so this is deliberately
    tolerant: it accepts a list of association dicts (or bare strings) under any
    of several ``data`` keys, and reads the gene from ``mappedGene``,
    ``mapped_gene``, ``gene_symbol`` or ``gene``. Any envelope it cannot parse,
    or one whose ``status`` is not ``ok``, yields no extra genes rather than an
    error.

    Parameters
    ----------
    gwascat_env:
        The envelope returned by section 1C's GWAS Catalog tool, or None.

    Returns
    -------
    list[str]
        De-duplicated gene symbols, order preserved.
    """
    if not isinstance(gwascat_env, dict):
        return []
    if gwascat_env.get("status") not in (None, "ok"):
        return []
    data = gwascat_env.get("data") or {}
    items = None
    if isinstance(data, dict):
        for key in ("associations", "results", "mapped_genes", "genes", "items"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
    elif isinstance(data, list):
        items = data
    if items is None:
        return []

    genes: list[str] = []
    for item in items:
        if isinstance(item, str):
            genes.append(item)
        elif isinstance(item, dict):
            for key in ("mappedGene", "mapped_gene", "gene_symbol", "gene"):
                val = item.get(key)
                if isinstance(val, str) and val:
                    genes.append(val)
                    break
    out, seen = [], set()
    for g in genes:
        for part in str(g).replace(";", ",").replace(" - ", ",").split(","):
            sym = part.strip()
            if sym and not _is_missing(sym) and sym.upper() not in seen:
                seen.add(sym.upper())
                out.append(sym)
    return out


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------
def _within_atlas_sort_key(gene: dict) -> tuple:
    """Sort key for genes from a single atlas.

    Orders by attribution-rule strength (strongest first), then by mention
    count, then by symbol for a stable, deterministic result.
    """
    return (-gene["rule_strength"], -gene["n_mentions"], gene["gene_symbol"])


def _rank_genes(genes: dict) -> list[dict]:
    """Rank candidate genes for display and annotate each with derived fields.

    A naive "sort by occurrence count" does not work on this table and defeats
    the purpose of the ``atlas`` column. Zoodsma 2025 supplies 43,322 of the
    45,169 rows and assays 249 correlated NMR measures, so its genes accumulate
    mentions simply because several sub-measures hit the same locus. Mention
    count within one paper reflects assay redundancy, not evidence strength;
    ranking on it lets the largest atlas crowd the other two off the card. That
    is precisely what buried CPS1, the documented acceptance answer for glycine,
    which Shin 2014 names at a single locus.

    The ranking therefore is:

    1. genes named by more than one atlas come first, since independent
       agreement is the only real strength signal available here;
    2. the remaining single-source genes are interleaved round-robin across
       atlases, most selective atlas first (the atlas that named the fewest
       genes for this metabolite was the most discriminating about it), so no
       single paper dominates the list;
    3. within an atlas, genes are ordered by ``_within_atlas_sort_key``.

    As a side effect, each gene dict gains ``n_sources``, ``rule_strength``,
    ``rules`` (human-readable), ``confidence`` and a trimmed ``rsids`` list.

    Parameters
    ----------
    genes:
        Mapping of gene symbol to the accumulator dict built by
        ``get_effector_genes_atlas``.

    Returns
    -------
    list[dict]
        The gene dicts, ordered for display.
    """
    for gene in genes.values():
        gene["n_sources"] = len(gene["atlases"])
        gene["rule_strength"] = max(
            (RULE_STRENGTH.get(r, 0) for r in gene["gene_source"]), default=0
        )
        gene["rules"] = [GENE_SOURCE_RULES.get(r, r) for r in gene["gene_source"]]
        # Agreement across atlases lifts confidence above a single weak rule.
        if gene["n_sources"] > 1:
            gene["confidence"] = "moderate"
        elif all(r in WEAK_RULES for r in gene["gene_source"]):
            gene["confidence"] = "weak"
        else:
            gene["confidence"] = "moderate"
        gene["rsids"] = gene["rsids"][:5]

    multi = sorted(
        (g for g in genes.values() if g["n_sources"] > 1),
        key=lambda g: (-g["n_sources"], *_within_atlas_sort_key(g)),
    )

    buckets: dict[str, list[dict]] = defaultdict(list)
    for gene in genes.values():
        if gene["n_sources"] == 1:
            buckets[gene["atlases"][0]].append(gene)
    for bucket in buckets.values():
        bucket.sort(key=_within_atlas_sort_key)

    # Most selective atlas first; atlas name breaks ties for a stable order.
    order = sorted(buckets, key=lambda a: (len(buckets[a]), a))
    interleaved: list[dict] = []
    while any(buckets[a] for a in order):
        for atlas in order:
            if buckets[atlas]:
                interleaved.append(buckets[atlas].pop(0))

    return multi + interleaved


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------
def get_effector_genes_atlas(chebi: str, synonyms: list, gwascat_env: dict) -> dict:
    """Return effector genes named at a metabolite's mQTL loci by published atlases.

    Genes named at this metabolite's mQTL loci by published atlases (Shin 2014,
    Chen 2023, Zoodsma 2025) and GWAS Catalog mapped genes. Each gene carries the
    naming rule used by the source (nearest / author-prioritized / GWAS Catalog
    mapped), so downstream card text can attribute it honestly. Positions are hg38
    and chromosome X is written as 23.

    This docstring doubles as the function-calling tool description, so the first
    line is kept self-contained.

    Parameters
    ----------
    chebi:
        ChEBI identifier for the metabolite, or an empty string if unresolved.
    synonyms:
        Candidate metabolite names, most preferred first. Non-string items are
        ignored, so a partly-malformed list is safe.
    gwascat_env:
        Section 1C's GWAS Catalog envelope, whose mapped genes are merged in as a
        weaker source. May be None or malformed without causing an error.

    Returns
    -------
    dict
        The uniform envelope (``tool``, ``args``, ``source``, ``url``,
        ``retrieved_at``, ``status``, ``data``, ``caveats``). ``status`` is
        ``ok`` when at least one gene is found, ``empty`` when the metabolite is
        absent from every source, or ``error`` if the lookup itself failed.
    """
    args = {"chebi": chebi, "synonyms": list(synonyms or [])[:12]}
    env = {
        "tool": "get_effector_genes_atlas",
        "args": args,
        "source": "Published metabolite GWAS atlases (Shin 2014, Chen 2023, Zoodsma 2025)"
                  " + GWAS Catalog mapped genes",
        "url": "local table: data/atlas_locus_gene.csv",
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "error",
        "data": {},
        "caveats": [],
    }

    try:
        load_table()
        env["url"] = f"local table: {_TABLE_PATH}"
        idxs, matched_on, matched_term = _lookup_rows(chebi, synonyms)

        # gene_symbol -> per-source evidence
        genes: dict[str, dict] = {}
        loci: list[dict] = []
        atlases_hit: set[str] = set()
        rows_skipped_no_gene = 0

        for i in idxs:
            row = _TABLE[i]
            atlas = row.get("atlas") or "unknown atlas"
            atlases_hit.add(atlas)
            rule = row.get("gene_source") or "unknown"
            symbol = row.get("gene_symbol", "")
            rsid = row.get("rsid", "")
            if rsid and not _is_missing(rsid):
                loci.append({
                    "rsid": rsid,
                    "chr": row.get("chr", ""),      # X is written as 23
                    "pos": row.get("pos", ""),      # hg38
                    "gene_symbol": "" if _is_missing(symbol) else symbol,
                    "atlas": atlas,
                })
            if _is_missing(symbol):
                # Locus is reported but the atlas named no gene there.
                rows_skipped_no_gene += 1
                continue

            gene = genes.setdefault(symbol, {
                "gene_symbol": symbol,
                "n_mentions": 0,
                "atlases": [],
                "gene_source": [],
                "rsids": [],
                "ensembl_ids": [],
                "evidence": [],
            })
            gene["n_mentions"] += 1
            if atlas not in gene["atlases"]:
                gene["atlases"].append(atlas)
            if rule not in gene["gene_source"]:
                gene["gene_source"].append(rule)
            if rsid and not _is_missing(rsid) and rsid not in gene["rsids"]:
                gene["rsids"].append(rsid)
            # ensembl_gene_id holds the effector gene's Ensembl id (1D 备注 #2). The
            # column was named opengwas_id in the delivered table and renamed here.
            ensembl_id = row.get("ensembl_gene_id", "")
            if ensembl_id.startswith("ENSG") and ensembl_id not in gene["ensembl_ids"]:
                gene["ensembl_ids"].append(ensembl_id)
            label = f"named by {atlas} (rule: {rule})"
            if label not in gene["evidence"]:
                gene["evidence"].append(label)

        atlas_gene_count = len(genes)

        # Merge 1C's GWAS Catalog mapped genes as a separate, weaker source.
        for symbol in _extract_gwascat_genes(gwascat_env):
            gene = genes.setdefault(symbol, {
                "gene_symbol": symbol,
                "n_mentions": 0,
                "atlases": [],
                "gene_source": [],
                "rsids": [],
                "ensembl_ids": [],
                "evidence": [],
            })
            gene["n_mentions"] += 1
            if "GWAS Catalog" not in gene["atlases"]:
                gene["atlases"].append("GWAS Catalog")
            if "gwas_catalog_mapped" not in gene["gene_source"]:
                gene["gene_source"].append("gwas_catalog_mapped")
            label = "named by GWAS Catalog (rule: gwas_catalog_mapped)"
            if label not in gene["evidence"]:
                gene["evidence"].append(label)

        ranked = _rank_genes(genes)

        env["data"] = {
            "matched_on": matched_on,
            "matched_term": matched_term,
            "n_rows_matched": len(idxs),
            "n_loci": len(loci),
            "n_genes": len(ranked),
            "genes": ranked[:MAX_GENES],
            "loci": loci[:25],
            "atlases": sorted(atlases_hit),
            "ranked_by": "cross-atlas agreement first, then round-robin across "
                         "atlases (most selective first), then attribution rule "
                         "strength. Rank is not an effect size.",
            "citations": [ATLAS_CITATIONS[a] for a in sorted(atlases_hit)
                          if a in ATLAS_CITATIONS],
            "genome_build": "GRCh38 (hg38)",
        }

        if ranked:
            env["status"] = "ok"
            env["caveats"].append(
                "Genes are named by the source atlas under the stated rule. No "
                "colocalization was performed here; atlas naming is not colocalization."
            )
            if any(gene["confidence"] == "weak" for gene in ranked[:MAX_GENES]):
                env["caveats"].append(
                    "Some genes rest only on nearest-gene or GWAS Catalog mapping. "
                    "Word these more conservatively than author-prioritized genes."
                )
            if rows_skipped_no_gene:
                env["caveats"].append(
                    f"{rows_skipped_no_gene} matched locus row(s) report no gene symbol; "
                    "the locus is listed but names no gene."
                )
            if len(ranked) > MAX_GENES:
                env["caveats"].append(
                    f"{len(ranked)} genes matched; the top {MAX_GENES} are shown. "
                    "Genes named by more than one atlas rank first; the rest are "
                    "interleaved across atlases so no single paper dominates. Rank "
                    "reflects source agreement, not effect size."
                )
            if atlas_gene_count == 0:
                env["caveats"].append(
                    "No atlas named a gene for this metabolite; all genes shown come "
                    "from GWAS Catalog mapping, which is the weakest rule."
                )
        else:
            env["status"] = "empty"
            env["caveats"].append(
                (f"The atlas contains {len(idxs)} matched locus row(s), but none names a gene. "
                 if idxs else
                 "This metabolite is not present in the atlas table (Shin 2014, Chen 2023, Zoodsma 2025). ")
                + "GWAS Catalog named no mapped gene. "
                "Empty means not covered by these sources; it does not mean no gene "
                "and it does not mean no effect. Fall back to Human-GEM (MVP3)."
            )

    except Exception as exc:  # noqa: BLE001 - §3.1: never escape into the agent loop
        env["status"] = "error"
        env["data"] = {"error": f"{type(exc).__name__}: {exc}"}
        env["caveats"].append(
            "Atlas lookup failed. Treat as no information retrieved, not as absence "
            "of evidence."
        )

    # The repo ledger takes the envelope only; the run stem comes from the run
    # context that ledger.start() opened, and record() is a no-op outside a run.
    ledger.record(env)
    return env


def _selftest() -> None:
    """Run one real lookup and print the envelope (section 3.8 self-test).

    The metabolite name may be given as the first command-line argument and
    defaults to ``glycine``.
    """
    import json

    metabolite = sys.argv[1] if len(sys.argv) > 1 else "glycine"
    result = get_effector_genes_atlas(
        chebi       = "",
        synonyms    = [metabolite],
        gwascat_env = {},
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _selftest()
