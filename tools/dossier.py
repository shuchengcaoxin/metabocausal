"""Optional deterministic 1E bundler; no MR classification or target ranking."""

from ._evidence import evidence_tool
from .opentargets import get_target_disease_evidence, get_known_drugs
from .chembl import get_chembl_modulators
from .gnomad import get_gnomad_constraint


@evidence_tool("Open Targets; ChEMBL; gnomAD", "", (
    "This bundle describes the supplied candidate gene; it does not establish metabolite causality, nominate an effector gene, or issue a GO/NO-GO verdict.",
))
def get_gene_dossier(gene_symbol: str, disease_efo: str) -> dict:
    """Record four component envelopes then one summary, retaining partial failures."""
    components = {
        "association": get_target_disease_evidence(gene_symbol, disease_efo),
        "clinical": get_known_drugs(gene_symbol),
        "chembl": get_chembl_modulators(gene_symbol),
        "constraint": get_gnomad_constraint(gene_symbol),
    }
    statuses = {key: value["status"] for key, value in components.items()}
    status = "error" if "error" in statuses.values() else (
        "ok" if "ok" in statuses.values() else "empty")
    data = dict(gene=gene_symbol, disease_efo=disease_efo, components=components,
                component_statuses=statuses)
    if status == "error":
        data["error"] = "One or more component tools failed; inspect component_statuses and preserve successful evidence."
    return status, data, []


if __name__ == "__main__":
    import argparse
    import json
    from ._evidence import JsonlRecorder, recording

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gene_symbol")
    parser.add_argument("disease_efo")
    parser.add_argument("--ledger", help="Explicit append-only JSONL path")
    args = parser.parse_args()
    if args.ledger:
        with recording(JsonlRecorder(args.ledger)):
            result = get_gene_dossier(args.gene_symbol, args.disease_efo)
    else:
        result = get_gene_dossier(args.gene_symbol, args.disease_efo)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result["status"] == "error" else 0)
