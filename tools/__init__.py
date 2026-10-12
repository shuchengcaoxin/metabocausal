"""MetaboCausal tools package - each function is one 'tool' the agent can call.

The function docstring is what the model reads to decide WHEN to call the tool, and
the type hints define the arguments. So: clear docstrings + type hints = better agent.

Status: 1B (get_mr_result / get_mr_outcomes, in epigraphdb.py), all of 1C - the
OpenGWAS half (get_mqtl_instruments / find_outcome_datasets, in opengwas.py) and the
GWAS Catalog supplement (get_gwas_catalog, in gwascat.py), 1D (get_effector_genes_atlas,
in atlas.py), MVP3 Human-GEM biochemical context, and all of 1E (the gene dossier:
opentargets.py, chembl.py, gnomad.py) are implemented; the rest
are signatures whose bodies are written during the official build window. Those
signatures are listed in UNIMPLEMENTED and are NOT in TOOLS - see the note above the
registry at the bottom of this file.
Every function returns the shared envelope:
  {tool, args, source, url, retrieved_at, status: ok|empty|error, data, caveats}

The loop (see team-admin/00_总执行方案):
  ids -> metabolite->disease genetic evidence (EpiGraphDB, literature MR, OpenGWAS)
      -> A/B/C state -> effector genes (atlas, literature, Human-GEM)
      -> gene dossier (Open Targets, ChEMBL, gnomAD) -> card
  and alongside the verdict: retrieved colocalisation (get_colocalisation, in coloc.py),
      an evidence QUALIFIER on the state - never an input to it.
"""

from .atlas import get_effector_genes_atlas
from .chembl import get_chembl_modulators
from .coloc import get_colocalisation
from .epigraphdb import get_mr_outcomes, get_mr_result
from .gem import map_metabolite_to_genes_gem
from .gnomad import get_gnomad_constraint
from .gwascat import get_gwas_catalog
from .ids import resolve_disease, resolve_ids, resolve_metabolite
from .opengwas import find_outcome_datasets, get_mqtl_instruments
from .opentargets import get_known_drugs, get_target_disease_evidence



# ---------------------------------------------------------------- 1A ids (run deterministically before the model)
# resolve_ids lives in tools/ids.py, on top of tools/_ids_disease.py (which also holds
# the shared OLS4 client) and tools/_ids_metabolite.py. It records its own envelope
# through ledger.record, so a dispatcher must not record it a second time. resolve_disease
# and resolve_metabolite are re-exported for the callers that need one half only.


# ---------------------------------------------------------------- 1B / MVP2 / 1C genetic evidence
# get_mr_result and get_mr_outcomes live in tools/epigraphdb.py, get_mqtl_instruments
# and find_outcome_datasets in tools/opengwas.py, and get_gwas_catalog in
# tools/gwascat.py. All five are imported above.


def get_literature_mr(
    metabolite_synonyms: list,
    disease_synonyms:    list,
    max_rounds:          int = 1,
) -> dict:
    """Search Europe PMC for published metabolite -> disease MR papers with Proponent
    queries (support) and Challenger queries (null, reverse direction, other ancestries).
    Extract estimate, method, n_snps, ancestry and genes named, each with a verbatim
    abstract span. Ids are verified against the API; the model never generates them."""
    raise NotImplementedError("build-day implementation")


# ---------------------------------------------------------------- colocalisation (the evidence qualifier)
# get_colocalisation lives in tools/coloc.py and reads Open Targets' own published
# credible-set colocalisations for the disease's GWAS: which of them colocalise with a
# GWAS of this metabolite, and which with a molecular QTL (the gene symbol is what joins
# that row to the 1D effector genes). Every H4, H3 and CLPP is retrieved under the method
# named on its row; nothing is computed here and the source publishes two-way results
# only, so there is no three-way mQTL/eQTL/disease claim anywhere in it.
#
# IT IS NOT A CLASSIFIER INPUT. classify.classify_state stays a pure function of the 1B
# and 1C arms; a retrieved colocalisation qualifies a verdict that was already decided and
# can never move a pair between A, B and C. It records its own envelope through
# ledger.record, so a dispatcher must not record it a second time.


# ---------------------------------------------------------------- 1D / MVP3 gene context
# get_effector_genes_atlas lives in tools/atlas.py and reads data/atlas_locus_gene.csv
# (45,169 rows, offline). It records its own envelope through ledger.record, so a
# dispatcher must not record it a second time. Each gene carries the naming rule its
# source used (author_prioritized / nearest / gwas_catalog_mapped); no row claims eQTL
# colocalization, because none of the three atlases ran one.


# map_metabolite_to_genes_gem lives in tools/gem.py. It reads a pinned local index,
# records one biochemical-context envelope and never changes the A/B/C state. Its
# candidates retain origin="biochemical" and their source GPR pointers; they are not
# effector-gene nominations.


# ---------------------------------------------------------------- 1E gene dossier (the drug-target question, one hop later)
# get_target_disease_evidence and get_known_drugs live in tools/opentargets.py,
# get_chembl_modulators in tools/chembl.py, and get_gnomad_constraint in
# tools/gnomad.py. All four are imported above; they take ontology ids in underscore
# form (EFO_0001645, MONDO_0005010 - see _common.underscore_ontology_id) and they
# record their own envelopes through tools._evidence.recording(ledger.record), so a
# dispatcher must not record them a second time.
#
# tools/dossier.py bundles the four into get_gene_dossier. It is a convenience
# summary, not a registered tool: the agent calls the four itself.
#


# resolve_ids runs before the model and is not in TOOLS. Neither is get_mr_outcomes:
# it is a wildcard sweep (thousands of rows) meant for building candidate lists offline,
# and the agent must not be able to fire it while assembling a card. Nor is
# get_trial_dates (tools/trials.py), which fetches ClinicalTrials.gov start and
# completion years for NCT ids a 1E dossier already holds: it is plumbing for the
# genetic-insight timeline, one request per trial, and a model able to fire it could
# spend an unbounded number of requests on one figure.
#
# TOOLS IS THE EXECUTABLE REGISTRY, AND ONLY IMPLEMENTED FUNCTIONS BELONG IN IT.
# get_literature_mr (MVP2) remains a signature whose build-day implementation has not
# landed. A planned tool advertised as available is a crash, so it stays out of TOOLS.
UNIMPLEMENTED = [
    get_literature_mr,
]

ROUND1_TOOLS = [
    get_mr_result,
    get_mqtl_instruments,
    find_outcome_datasets,
    get_effector_genes_atlas,
]

TOOLS = ROUND1_TOOLS + [
    get_gwas_catalog,
    get_colocalisation,
    map_metabolite_to_genes_gem,
    get_target_disease_evidence,
    get_known_drugs,
    get_chembl_modulators,
    get_gnomad_constraint,
]
