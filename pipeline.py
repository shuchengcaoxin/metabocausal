"""One pair in, one deterministic result out. No model call anywhere in this file.

`scripts/end_to_end.py` runs the six frozen demo pairs and prints a report; this is the
same orchestration with the report stripped off and a name-in / dict-out signature, so
a surface can call it. The Slack shell (slack_app.py) calls it today and the 1F Gemini
loop calls the same function later to layer verdict prose on top - the state, the
reason and every number will still come from here, from `classify.classify_state` and
from the tool envelopes, never from the model.

    from pipeline import run_pair
    result = run_pair("urate", "gout")
    result["state"]                                   # "A"
    result["envelopes"]["mr"]["data"]["n_estimates"]  # 22

WHAT RUNS, IN THIS ORDER
  resolve_ids            1A   OLS4 + PubChem, live, only on a miss   -> ledger only
  get_mr_result          1B   EpiGraphDB MR-EVE, no key              -> classify mr_env
  get_mqtl_instruments   1C   OpenGWAS tophits, needs the JWT        -> classify instr_env
  find_outcome_datasets  1C   OpenGWAS gwasinfo cache, no request    -> classify outcome_env
  get_gwas_catalog       1C   EBI GWAS Catalog, ~100 s               -> ledger only,
                                                                        skip_catalog=True
  classify_state              pure function over the three arms above
  get_colocalisation          Open Targets coloc, ~15 s              -> ledger + qualifier,
                                                                        skip_coloc=False
  map_metabolite_to_genes_gem MVP3 pinned local Human-GEM index      -> ledger + biochemical
                                                                       context only
  get_effector_genes_atlas 1D local table, no request                -> ledger only
  the four 1E tools      1E   Open Targets / ChEMBL / gnomAD         -> ledger only

COLOCALISATION IS A QUALIFIER, NOT AN INPUT. `get_colocalisation` runs AFTER
`classify_state` and its envelope is never passed to it: a retrieved colocalisation says
the two GWAS share one causal variant at a locus, which corroborates a State A verdict and
tells a State B pair that the signals already line up while the causal estimate has never
been computed - but it is not an MR estimate and not an instrument count, so it cannot
move a pair between states. `result["coloc_summary"]` is the digest the surfaces print;
`skip_coloc=True` switches the arm off the way `skip_catalog` does.

Neither the GWAS Catalog envelope, the Human-GEM envelope nor any gene-side envelope is
passed to the classifier.
That is the same refusal end_to_end.py makes: an association, a drug record, a constraint
metric or a gene an atlas named is not an MR estimate on
this metabolite and not an instrument count, so none of them may move the A/B/C state.
The gene stage runs AFTER the verdict and cannot reach back into it - a failure inside it
is a note, never a demotion to C.

RESOLUTION, IN TWO STEPS. data/1a_sample.json is tried first: it is the frozen 1A output
for the demo pairs, it costs no request, and it keeps the six demo runs identical every
time. A side the sample does not carry goes to the real resolver, `tools.ids.resolve_ids`,
live - OLS4 for the ontology id, PubChem for the metabolite spellings - and its envelope
is written to the ledger like any other retrieval. Only when THAT returns no id does a
side degrade to its raw input string as its only synonym, and it says so in `notes`. The
two sides are resolved independently, so "glycine x gout" still gets both real lists.

EFFECTOR GENES. When the verdict is A or B, 1D's atlas is asked which genes sit under
this metabolite's mQTL loci; the top three get the 1E dossier.
In state C nothing about the pair was retrieved, so nominating genes would dress a
retrieval gap up as a lead - the stage is skipped and the reason is written into `notes`.
`skip_genes=True` switches the stage off entirely; `dossier_genes` still forces a dossier
for genes the caller names, with or without the atlas.

LEDGER. One run writes one file, cards/{slug(metabolite)}_{slug(disease)}.ledger.jsonl,
truncated at the start of the run. The 1A/1B/1C/1D tools record themselves; the MVP3
adapter and 1E tools record themselves through the recorder bound here with
tools._evidence.recording, so nothing in this file records an envelope a second time.

`stem_prefix` puts a caller's runs in their own namespace - the Slack shell passes
"slack", so a mention can never truncate one of the six frozen demo ledgers, which are
gitignored, cost about 100 s plus OpenGWAS credits each to rebuild, and exist only on
the machine that made them. Each side of the stem is capped and hashed when it is long,
so a 120-character trait name cannot build a path past Windows' 260-character limit.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import classify
import ledger
from tools import _common, _evidence
from tools.atlas import get_effector_genes_atlas
from tools.chembl import get_chembl_modulators
from tools.coloc import get_colocalisation
from tools.epigraphdb import get_mr_result
from tools.gem import map_metabolite_to_genes_gem
from tools.gnomad import get_gnomad_constraint
from tools.gwascat import get_gwas_catalog
from tools.ids import resolve_ids
from tools.opengwas import find_outcome_datasets, get_mqtl_instruments
from tools.opentargets import get_known_drugs, get_target_disease_evidence

SAMPLE_PATH = REPO_ROOT / "data" / "1a_sample.json"

MAX_DATASETS = 6
TOP_N = 3

# How many of the atlas's ranked genes get a dossier. The atlas ranks by cross-atlas
# agreement, not by effect size, and each gene costs five requests, so three is the point
# where a card still reads as a shortlist rather than a dump.
TOP_GENES = 3

# The states in which the gene stage is worth running. In C nothing was retrieved about
# the pair itself, so a gene list would be the only concrete thing on the card - and it
# would be about the metabolite's genetics, not about the disease that was asked about.
GENE_STAGE_STATES = ("A", "B")

# Each slug in a stem is capped here. cards/ plus two capped slugs plus a prefix plus
# ".ledger.jsonl" stays well inside the 260-character MAX_PATH this project's Windows
# box still enforces; 120-character trait names are ordinary in GWAS Catalog strings,
# so the cap belongs on the filename, not on the name a user may type.
MAX_SLUG_CHARS = 40
SLUG_HASH_CHARS = 8

SIDES = ("metabolite", "disease")

# The ontology id lives on the disease side only; the metabolite side carries a ChEBI id,
# which none of the 1E tools take.
ID_FIELD = {"metabolite": "chebi", "disease": "id"}

LIVE_SOURCE = "resolve_ids (live)"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

_NO_NAME_NOTE = "no {side} name was given, so every {side}-side tool ran with an empty synonym list."
_LIVE_RESOLVED_NOTE = (
    "{side} {name!r}: not in the pre-resolved sample, so the 1A resolver ran live and "
    "returned {label!r} ({id}) with {count} synonym spelling(s)."
)
_UNRESOLVED_NOTE = (
    "{side} {name!r}: not in the pre-resolved sample, and the live 1A resolver "
    "(resolve_ids, status {status}) returned no id either, so matching used the raw "
    "input string only. That is a gap in resolution, not a statement about the entity."
)
_SPLIT_PAIR_NOTE = (
    "this pair is not itself in the pre-resolved sample: the metabolite synonyms come "
    "from {metabolite!r} and the disease synonyms from {disease!r}."
)
_NO_SAMPLE_NOTE = (
    "data/1a_sample.json could not be read ({detail}), so both sides went to the live 1A "
    "resolver instead of the frozen sample."
)
_LIVE_FAILURE_NOTE = (
    "the live 1A resolver could not be called ({detail}), so every side the frozen sample "
    "does not carry degraded to its raw input string."
)
_NO_EFO_NOTE = (
    "no ontology id is known for the disease, so get_target_disease_evidence was not "
    "called; only the three gene-only 1E tools ran."
)
_GENES_OFF_NOTE = (
    "the effector-gene stage was switched off for this run, so the 1D atlas was not asked "
    "which genes sit under this metabolite's loci. Any gene named by the caller still got "
    "its dossier; no gene on this card was nominated by a retrieval."
)
_GENES_STATE_NOTE = (
    "the 1D atlas was not asked for effector genes because the state is {state}: this "
    "run did not reach the gene-stage eligibility rule. The mechanism remains unassessed; "
    "any retrieved colocalisation or feasibility evidence is retained separately. "
    "Any gene named by the caller still got its dossier."
)
_GENES_EMPTY_NOTE = (
    "no atlas gene nomination was available for this metabolite (get_effector_genes_atlas returned "
    "{status}), so this run nominated no gene of its own. The effector mechanism remains "
    "unresolved; it does not mean no gene and it does not mean no effect. Retrieved MR, "
    "colocalisation and feasibility evidence remain available independently."
)
_COLOC_OFF_NOTE = (
    "the colocalisation arm was switched off for this run, so Open Targets was not asked "
    "whether the disease's credible sets colocalise with a GWAS of this metabolite. "
    "Nothing on this card may be read as saying they do not."
)
_COLOC_FAILURE_NOTE = (
    "the colocalisation arm raised {detail} and was abandoned. The state above rests on "
    "the 1B/1C arms only and is unchanged by this; a missing colocalisation line is a gap "
    "in what could be retrieved, not evidence against a shared causal variant."
)
_GEM_OFF_NOTE = (
    "the Human-GEM biochemical-context arm was switched off for this run. This means "
    "reaction/GPR context was not assessed, not that the metabolite has no reactions."
)
_GEM_NO_ID_NOTE = (
    "the Human-GEM biochemical-context arm was not called because no verified ChEBI "
    "identifier was resolved for the metabolite. No name or fuzzy fallback was guessed."
)
_GEM_FAILURE_NOTE = (
    "the Human-GEM biochemical-context arm raised {detail} and was abandoned. The A/B/C "
    "state and all previously retrieved evidence are unchanged; this is a mechanism-"
    "context failure, not evidence against the metabolite-disease relationship."
)
_GENE_STAGE_FAILURE_NOTE = (
    "the effector-gene stage raised {detail} and was abandoned. The state above rests on "
    "the 1B/1C arms only and is unchanged by this; whatever gene evidence had already "
    "been retrieved is still shown."
)
_STAGE_FAILURE_NOTE = (
    "the run did not finish: the {stage} stage raised {detail}. Whatever is shown was "
    "retrieved before that point; the rest is a failure of this pipeline and not a "
    "statement about the biology."
)
_STAGE_FAILURE_REASON = (
    "State C (evidence gap): the run did not finish, so this pair was never fully "
    "queried. An unfinished run is a gap in what could be retrieved, not evidence of "
    "no effect."
)


def slug(value) -> str:
    """The filesystem-safe half of a ledger stem: "coronary artery disease" ->
    "coronary-artery-disease". Casefolded, every run of non-alphanumerics becomes one
    hyphen, so the stem of a pair is one readable name and never a path escape."""
    text = _SLUG_STRIP.sub("-", _common.normalize(value)).strip("-")
    return text or "unknown"


def capped_slug(value) -> str:
    """`slug()`, cut to MAX_SLUG_CHARS with a short digest of the full slug appended when
    it was cut. The digest keeps two long names that share a prefix apart, and the
    readable head keeps the file recognisable in cards/."""
    text = slug(value)
    if len(text) <= MAX_SLUG_CHARS:
        return text
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:SLUG_HASH_CHARS]
    return f"{text[:MAX_SLUG_CHARS].rstrip('-')}-{digest}"


def stem_for(
    metabolite: str,
    disease:    str,
    prefix:     str = "",
) -> str:
    """The ledger stem of one run: slug(metabolite)_slug(disease), each side capped.

    `prefix` namespaces the caller's runs - the Slack shell passes "slack", so a mention
    writes cards/slack_urate_gout.ledger.jsonl and the frozen demo ledger of the same
    pair is never the target.
    """
    stem = f"{capped_slug(metabolite)}_{capped_slug(disease)}"
    head = slug(prefix) if prefix else ""
    return f"{head}_{stem}" if head and head != "unknown" else stem


def load_sample(path: Path = SAMPLE_PATH) -> dict:
    """1A's frozen output, or {} if the file is missing or unreadable. Raises nothing:
    an absent sample sends the run to the live resolver, it does not end it."""
    try:
        with Path(path).open(encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _names(block) -> set:
    """Every string this sample entry may be called by, normalized: its input name, its
    label and its synonyms."""
    if not isinstance(block, dict):
        return set()
    names = {_common.normalize(block.get("input")), _common.normalize(block.get("label"))}
    for synonym in block.get("synonyms") or []:
        names.add(_common.normalize(synonym))
    names.discard("")
    return names


def resolve_entity(
    name:   str,
    side:   str,
    sample: dict,
) -> dict:
    """Look one entity up in 1A's frozen output and return what the tools need.

    `side` is "metabolite" or "disease". Matching is exact after `_common.normalize`,
    against the entity's own input name, label and synonyms - no stemming, no invented
    variants. Returns {query, input, label, id, synonyms, resolved, resolved_from};
    `query` is always the caller's raw string, and `resolved` False means the sample does
    not carry this entity, which is what sends `run_pair` to the live resolver.
    """
    query = str(name or "").strip()
    needle = _common.normalize(query)

    for key, entry in (sample or {}).items():
        block = (entry or {}).get(side) or {}
        if needle and needle in _names(block):
            return {
                "query":         query,
                "input":         block.get("input") or query,
                "label":         block.get("label") or query,
                "id":            block.get(ID_FIELD[side]) or "",
                "synonyms":      list(block.get("synonyms") or []),
                "resolved":      True,
                "resolved_from": key,
            }

    return _raw_entity(name, side)


def _live_entity(
    name:   str,
    side:   str,
    result: dict,
) -> dict:
    """One side of a live `resolve_ids` envelope, in the same shape `resolve_entity`
    returns. A leg that came back without an id is NOT accepted: an id is what the 1D and
    1E tools take, and a synonym list with no id behind it would look resolved on the card
    while every id-keyed lookup downstream still missed."""
    query = str(name or "").strip()
    if not isinstance(result, dict):
        return _raw_entity(name, side)

    identifier = str(result.get(ID_FIELD[side]) or "").strip()
    if not identifier:
        return _raw_entity(name, side)

    synonyms = [str(item) for item in (result.get("synonyms") or []) if str(item).strip()]
    return {
        "query":         query,
        "input":         result.get("input") or query,
        "label":         result.get("label") or query,
        "id":            identifier,
        "synonyms":      synonyms or ([query] if query else []),
        "resolved":      True,
        "resolved_from": LIVE_SOURCE,
    }


def _dossier_for_gene(
    gene:             str,
    disease_efo:      str,
    disease_synonyms: list,
) -> dict:
    """The gene-side envelopes of one gene, keyed by tool name.

    get_target_disease_evidence is omitted - not faked, not called with a blank id - when
    no ontology id is known.
    """
    entry = {}
    if disease_efo:
        entry["get_target_disease_evidence"] = get_target_disease_evidence(gene, disease_efo)
    entry["get_known_drugs"] = get_known_drugs(gene)
    entry["get_chembl_modulators"] = get_chembl_modulators(gene)
    entry["get_gnomad_constraint"] = get_gnomad_constraint(gene)
    return entry


def _run_dossier(
    genes:            list,
    disease_efo:      str,
    disease_synonyms: list,
) -> dict:
    """Run the gene-side tools for every gene inside one `recording` binding, so each 1E
    tool writes its own envelope to the active ledger exactly once and this file writes
    none of them."""
    dossier = {}
    with _evidence.recording(ledger.record):
        for gene in genes:
            symbol = str(gene or "").strip()
            if symbol and symbol not in dossier:
                dossier[symbol] = _dossier_for_gene(
                    symbol,
                    disease_efo,
                    disease_synonyms,
                )
    return dossier


def coloc_summary(envelope) -> dict:
    """The four numbers a surface prints about the colocalisation arm, from its envelope.

    `best_h4` is the strongest retrieved H4 among the METABOLITE partners - the number
    that qualifies the verdict line - and is None when no such row was retrieved. `genes`
    are the molecular-QTL partners' gene symbols, which is what section 5 joins to the 1D
    effector genes. An envelope that is absent, failed or empty yields zeros and None, and
    a surface must print that as "none retrieved", never as "no colocalisation".
    """
    empty = {"best_h4": None, "n_metabolite_hits": 0, "n_qtl_hits": 0, "genes": []}
    if not isinstance(envelope, dict):
        return empty
    data = envelope.get("data")
    if not isinstance(data, dict):
        return empty
    genes = [str(symbol) for symbol in (data.get("genes") or []) if str(symbol).strip()]
    return {
        "best_h4":           data.get("best_h4"),
        "n_metabolite_hits": data.get("n_metabolite_hits") or 0,
        "n_qtl_hits":        data.get("n_qtl_hits") or 0,
        "genes":             genes,
    }


def _atlas_genes(envelope) -> list:
    """The atlas's ranked gene dicts, verbatim, capped at TOP_GENES.

    Verbatim matters: `gene_symbol`, `gene_source`, `atlases`, `rules` and `confidence`
    are how 1D says which paper named the gene and under which rule, and rewriting them
    here would be this file making a claim the atlas did not.
    """
    if not isinstance(envelope, dict) or envelope.get("status") != "ok":
        return []
    data = envelope.get("data")
    rows = (data or {}).get("genes") if isinstance(data, dict) else None
    genes = [row for row in (rows or []) if isinstance(row, dict) and row.get("gene_symbol")]
    return genes[:TOP_GENES]


def _raw_entity(
    name: str,
    side: str,
) -> dict:
    """The unresolved shape of one side: its raw input string as its only synonym. A
    caller reads one shape whether the entity was resolved, degraded or never reached."""
    query = str(name or "").strip()
    return {
        "query":         query,
        "input":         query,
        "label":         query,
        "id":            "",
        "synonyms":      [query] if query else [],
        "resolved":      False,
        "resolved_from": None,
    }


def run_pair(
    metabolite:    str,
    disease:       str,
    *,
    skip_catalog:  bool = True,
    skip_coloc:    bool = False,
    skip_genes:    bool = False,
    skip_gem:      bool = False,
    dossier_genes: list | None = None,
    stem_prefix:   str = "",
) -> dict:
    """Retrieve the evidence for one metabolite -> disease pair and classify it.

    Give it two display names in any case ("urate", "Gout"). They are resolved against
    1A's frozen sample first and against the live 1A resolver on a miss; a side neither
    one resolves degrades to its raw input string with a note rather than failing.

    `skip_catalog=False` adds the GWAS Catalog call, which takes about 100 s per disease.
    `skip_coloc=True` switches off the colocalisation arm, which otherwise runs after the
    verdict and costs about 15 s. `skip_genes=True` switches off the effector-gene stage
    (1D atlas -> 1E dossier), which otherwise runs whenever the
    verdict is A or B. Human-GEM runs independently whenever a verified ChEBI id exists,
    including in state C; `skip_gem=True` switches off only that biochemical-context arm.
    `dossier_genes` forces a dossier for an explicitly selected, bounded set of genes with
    or without the atlas. A matching Human-GEM candidate remains biochemical context and
    is never promoted to an effector gene. `stem_prefix` namespaces the ledger file, so a surface that runs
    arbitrary user input never truncates a frozen demo ledger - the Slack shell passes
    "slack".

    Returns {state, reason, metabolite, disease, envelopes, coloc_summary,
    effector_genes, ledger_path, n_ledger_entries, notes}. On a completed run `envelopes`
    holds "mr", "instruments" and "outcomes", plus "catalog" when the catalog ran,
    "coloc" when the colocalisation arm ran, "gem" when biochemical context ran,
    "atlas" when the gene stage ran, and
    "dossier" ({gene: {tool: envelope}}) when any gene got one. Deterministic: no model is
    called here, and the state comes from `classify.classify_state`, which is a pure
    function of the 1B/1C arms alone - the colocalisation envelope is NOT passed to it.

    Never raises, and that is load-bearing for 1F: every tool turns its own failure into
    an error envelope, and anything else that goes wrong - an unwritable cards/, a tool
    that breaks its own contract - comes back as a State C result whose `notes` name the
    stage that failed and whose `envelopes` hold whatever was retrieved before it. The
    gene stage is the exception: it is guarded separately, because a failure there is
    about a gene and must never turn an A into a C - and so is the colocalisation arm, for
    the same reason. The ten keys are always there, and `ledger.stop()` always runs.
    """
    stage = "reading the pre-resolved sample"
    notes = []
    envelopes = {}
    coloc = coloc_summary(None)
    effector_genes = []
    exposure = _raw_entity(metabolite, "metabolite")
    outcome = _raw_entity(disease, "disease")
    stem = ""

    try:
        sample = load_sample()
        if not sample:
            notes.append(_NO_SAMPLE_NOTE.format(detail=f"{SAMPLE_PATH.name} is missing or not JSON"))

        stage = "building the ledger stem"
        stem = stem_for(
            exposure["query"] or "unknown",
            outcome["query"] or "unknown",
            stem_prefix,
        )

        stage = "opening the ledger"
        ledger.start(stem)
        try:
            stage = "resolving the two names"
            entities = {
                side: resolve_entity(
                    name,
                    side,
                    sample,
                )
                for side, name in (("metabolite", metabolite), ("disease", disease))
            }

            named = [side for side in SIDES if entities[side]["query"]]
            if any(not entities[side]["resolved"] for side in named):
                stage = "1A resolve_ids (live)"
                live = _live_resolution(metabolite, disease, notes)
                for side in named:
                    if not entities[side]["resolved"]:
                        entities[side] = _live_entity(
                            entities[side]["query"],
                            side,
                            live.get(side),
                        )

                for side in named:
                    entity = entities[side]
                    if entity["resolved_from"] == LIVE_SOURCE:
                        notes.append(_LIVE_RESOLVED_NOTE.format(
                            side  = side,
                            name  = entity["query"],
                            label = entity["label"],
                            id    = entity["id"],
                            count = len(entity["synonyms"]),
                        ))
                    elif not entity["resolved"]:
                        notes.append(_UNRESOLVED_NOTE.format(
                            side   = side,
                            name   = entity["query"],
                            status = (live.get(side) or {}).get("status") or "not called",
                        ))

            for side in SIDES:
                if not entities[side]["query"]:
                    notes.append(_NO_NAME_NOTE.format(side=side))

            exposure, outcome = entities["metabolite"], entities["disease"]
            if (
                exposure["resolved"]
                and outcome["resolved"]
                and exposure["resolved_from"] != outcome["resolved_from"]
                and LIVE_SOURCE not in (exposure["resolved_from"], outcome["resolved_from"])
            ):
                notes.append(_SPLIT_PAIR_NOTE.format(
                    metabolite = exposure["resolved_from"],
                    disease    = outcome["resolved_from"],
                ))

            disease_efo = _common.underscore_ontology_id(outcome["id"])

            stage = "1B get_mr_result"
            envelopes["mr"] = get_mr_result(
                exposure["synonyms"],
                outcome["synonyms"],
            )

            stage = "1C get_mqtl_instruments"
            envelopes["instruments"] = get_mqtl_instruments(
                exposure["synonyms"],
                MAX_DATASETS,
            )

            stage = "1C find_outcome_datasets"
            envelopes["outcomes"] = find_outcome_datasets(
                outcome["synonyms"],
                TOP_N,
            )

            if not skip_catalog:
                stage = "1C get_gwas_catalog"
                envelopes["catalog"] = get_gwas_catalog(
                    trait_label = outcome["label"] or outcome["query"],
                    ontology_id = outcome["id"],
                )

            stage = "classifying"
            verdict = classify.classify_state(
                mr_env      = envelopes["mr"],
                lit_env     = None,
                instr_env   = envelopes["instruments"],
                outcome_env = envelopes["outcomes"],
            )

            # The colocalisation arm. It runs AFTER the verdict above and its envelope is
            # never handed to the classifier: it qualifies a state that is already decided
            # and cannot move one. Guarded on its own, like the gene stage below, so a
            # refused or slow Open Targets query is a note on the card rather than a
            # demotion of a pair that has 22 retrieved MR estimates.
            try:
                if skip_coloc:
                    notes.append(_COLOC_OFF_NOTE)
                else:
                    stage = "colocalisation (Open Targets)"
                    envelopes["coloc"] = get_colocalisation(
                        exposure["synonyms"],
                        outcome["synonyms"],
                        disease_efo,
                    )
                    coloc = coloc_summary(envelopes["coloc"])
            except Exception as exc:                   # noqa: BLE001 - the coloc arm only
                notes.append(_COLOC_FAILURE_NOTE.format(
                    detail = type(exc).__name__,
                ))

            # Human-GEM is a local biochemical-network lookup. It is deliberately after
            # classification and outside the atlas eligibility rule: useful context can
            # exist for a state-C pair, but it can never promote or demote A/B/C. The
            # adapter records its own envelope through the bound 1E recorder exactly once.
            try:
                if skip_gem:
                    notes.append(_GEM_OFF_NOTE)
                elif not exposure["id"]:
                    notes.append(_GEM_NO_ID_NOTE)
                else:
                    stage = "MVP3 Human-GEM biochemical context"
                    with _evidence.recording(ledger.record):
                        envelopes["gem"] = map_metabolite_to_genes_gem(exposure["id"])
            except Exception as exc:                   # noqa: BLE001 - optional context only
                notes.append(_GEM_FAILURE_NOTE.format(
                    detail = type(exc).__name__,
                ))

            # Everything below is about a GENE. It runs after the verdict, it is never
            # passed to the classifier, and its own failure is a note rather than a
            # demotion - a broken atlas lookup says nothing about the metabolite.
            given = [str(gene or "").strip() for gene in (dossier_genes or [])]
            given = [gene for gene in given if gene]
            try:
                stage = "1D effector-gene atlas"
                genes = list(given)
                if skip_genes:
                    notes.append(_GENES_OFF_NOTE)
                elif verdict["state"] not in GENE_STAGE_STATES:
                    notes.append(_GENES_STATE_NOTE.format(state=verdict["state"]))
                else:
                    envelopes["atlas"] = get_effector_genes_atlas(
                        exposure["id"],
                        exposure["synonyms"],
                        envelopes.get("catalog"),
                    )
                    effector_genes = _atlas_genes(envelopes["atlas"])
                    if not effector_genes:
                        notes.append(_GENES_EMPTY_NOTE.format(
                            status = envelopes["atlas"]["status"],
                        ))
                    for gene in effector_genes:
                        symbol = str(gene.get("gene_symbol") or "").strip()
                        if symbol and symbol not in genes:
                            genes.append(symbol)

                if genes:
                    if not disease_efo:
                        notes.append(_NO_EFO_NOTE)
                    stage = "1E gene dossier"
                    envelopes["dossier"] = _run_dossier(
                        genes,
                        disease_efo,
                        outcome["synonyms"],
                    )
            except Exception as exc:                   # noqa: BLE001 - the gene stage only
                notes.append(_GENE_STAGE_FAILURE_NOTE.format(
                    detail = type(exc).__name__,
                ))
        finally:
            ledger.stop()

        stage = "counting the ledger"
        try:
            n_entries = len(ledger.load(stem))
        except OSError:
            n_entries = 0

        return {
            "state":            verdict["state"],
            "reason":           verdict["reason"],
            "metabolite":       exposure,
            "disease":          outcome,
            "envelopes":        envelopes,
            "coloc_summary":    coloc,
            "effector_genes":   effector_genes,
            "ledger_path":      str(ledger.path_for(stem)),
            "n_ledger_entries": n_entries,
            "notes":            notes,
        }

    except Exception as exc:
        notes.append(_STAGE_FAILURE_NOTE.format(
            stage  = stage,
            detail = type(exc).__name__,
        ))
        try:
            n_entries = len(ledger.load(stem)) if stem else 0
        except OSError:
            n_entries = 0
        return {
            "state":            "C",
            "reason":           _STAGE_FAILURE_REASON,
            "metabolite":       exposure,
            "disease":          outcome,
            "envelopes":        envelopes,
            "coloc_summary":    coloc,
            "effector_genes":   effector_genes,
            "ledger_path":      str(ledger.path_for(stem)) if stem else "",
            "n_ledger_entries": n_entries,
            "notes":            notes,
        }


def _live_resolution(
    metabolite: str,
    disease:    str,
    notes:      list,
) -> dict:
    """Call the live 1A resolver once for the pair and hand back its two legs.

    `resolve_ids` writes its own envelope to the active ledger. It catches its own
    failures, so the guard here is for a break in this package rather than a bad response;
    either way the run continues with the raw strings and says so.
    """
    try:
        env = resolve_ids(metabolite, disease)
    except Exception as exc:                           # noqa: BLE001 - deliberate boundary
        notes.append(_LIVE_FAILURE_NOTE.format(detail=type(exc).__name__))
        return {}
    data = env.get("data") if isinstance(env, dict) else None
    return data if isinstance(data, dict) else {}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description = "Run one pair through 1A -> 1B -> 1C -> classify -> 1D/1E.",
    )
    parser.add_argument("metabolite", nargs="?", default="urate")
    parser.add_argument("disease", nargs="?", default="gout")
    parser.add_argument(
        "--gene",
        action  = "append",
        default = [],
        help    = "force the gene dossier for this gene (repeatable)",
    )
    parser.add_argument(
        "--catalog",
        action = "store_true",
        help   = "also call get_gwas_catalog, which needs ~100 s",
    )
    parser.add_argument(
        "--no-coloc",
        action = "store_true",
        help   = "switch off the Open Targets colocalisation arm (~15 s)",
    )
    parser.add_argument(
        "--no-genes",
        action = "store_true",
        help   = "switch off the atlas / dossier stage",
    )
    parser.add_argument(
        "--no-gem",
        action = "store_true",
        help   = "switch off the local Human-GEM biochemical-context arm",
    )
    args = parser.parse_args()

    result = run_pair(
        args.metabolite,
        args.disease,
        skip_catalog  = not args.catalog,
        skip_coloc    = args.no_coloc,
        skip_genes    = args.no_genes,
        skip_gem      = args.no_gem,
        dossier_genes = args.gene,
    )

    print(f"{args.metabolite} x {args.disease}   ->   STATE {result['state']}")
    print(f"reason : {result['reason']}")
    coloc = result["coloc_summary"]
    print(f"coloc  : best H4 {coloc['best_h4']}  "
          f"{coloc['n_metabolite_hits']} metabolite hit(s), "
          f"{coloc['n_qtl_hits']} molecular-QTL hit(s)  genes {coloc['genes'][:6]}")
    print(f"ledger : {Path(result['ledger_path']).name}  ({result['n_ledger_entries']} entries)")
    for gene in result["effector_genes"]:
        print(f"  gene  {gene.get('gene_symbol'):<10} {'/'.join(gene.get('gene_source') or [])}"
              f"  {'; '.join(gene.get('atlases') or [])}")
    for key, env in result["envelopes"].items():
        if key == "dossier":
            for gene, gene_tools in env.items():
                for name, gene_env in gene_tools.items():
                    print(f"  dossier {gene:<8} {name:<28} {gene_env['status']}")
            continue
        print(f"  {key:<12} {env['tool']:<28} {env['status']}")
    for note in result["notes"]:
        print(f"note : {note}")
