"""Emit a small, explicitly labelled source excerpt as JSON on stdout.

Every included model entity and TSV record is copied from checksum-verified files.
This is a partial graph, not evidence of full model coverage. No invented reactions.
"""

import argparse
import json

from .build_index import _records, as_mapping, read_sources
from .gpr import gene_members, parse_gpr


def source_fixture(source_dir, reaction_ids):
    model, annotations, provenance = read_sources(source_dir)
    reactions = _records(model["reactions"])
    selected = [reactions[rid] for rid in sorted(set(reaction_ids))]
    if not selected:
        raise ValueError("Select at least one source reaction")
    metabolites = {sid for row in selected for sid in as_mapping(row["metabolites"])}
    genes = {gene for row in selected for gene in gene_members(parse_gpr(row.get("gene_reaction_rule", "")))}
    metabolite_rows = _records(model["metabolites"])
    gene_rows = _records(model["genes"])
    retained = {"metabolites": metabolites, "genes": genes, "reactions": {row["id"] for row in selected}}
    return {"provenance": {**provenance, "dataset_kind": "source_fixture",
                           "fixture_note": "Unmodified entity/annotation records selected from the pinned full source; graph deliberately incomplete.",
                           "selected_reaction_ids": sorted(retained["reactions"])},
            "model": {"metaData": model["metaData"], "compartments": model["compartments"],
                      "metabolites": [metabolite_rows[sid] for sid in sorted(metabolites)],
                      "genes": [gene_rows[gene] for gene in sorted(genes)], "reactions": selected,
                      "source_lines": {identifier: line for identifier, line in model["source_lines"].items()
                                       if any(identifier in ids for ids in retained.values())}},
            "annotations": {kind: {identifier: annotations[kind][identifier] for identifier in sorted(ids)
                                    if identifier in annotations[kind]} for kind, ids in retained.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--reactions", nargs="+", required=True)
    args = parser.parse_args()
    print(json.dumps(source_fixture(args.source_dir, args.reactions), sort_keys=True, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
