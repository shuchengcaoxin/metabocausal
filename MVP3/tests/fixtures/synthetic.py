"""Invented graph solely for unit tests; no fixture metric is biological evidence."""


def fixture():
    metabolites = [
        {"id": "QA_c", "name": "test-alpha", "compartment": "c"},
        {"id": "QA_m", "name": "test-alpha", "compartment": "m"},
        {"id": "QB_c", "name": "test-beta", "compartment": "c"},
        {"id": "ATP_c", "name": "test-ATP", "compartment": "c"},
    ]
    genes = [{"id": name, "name": name} for name in ("GENEA", "GENEB", "GENEC", "GENED")]
    reactions = [
        {"id": "RX1", "name": "synthetic complex reaction", "metabolites": {"QA_c": -1, "QB_c": 1},
         "gene_reaction_rule": "GENEA and (GENEB or GENEC)", "lower_bound": 0, "upper_bound": 1000,
         "eccodes": "test-EC", "subsystem": "synthetic"},
        {"id": "RX2", "name": "synthetic transport", "metabolites": {"QA_c": -1, "QA_m": 1},
         "gene_reaction_rule": "GENED", "lower_bound": -1000, "upper_bound": 1000},
        {"id": "RX3", "name": "synthetic unannotated sink", "metabolites": {"QA_c": -1},
         "gene_reaction_rule": "", "lower_bound": 0, "upper_bound": 0},
        {"id": "RX4", "name": "synthetic ATP reaction", "metabolites": {"ATP_c": -1, "QB_c": 1},
         "gene_reaction_rule": "GENEA", "lower_bound": -10, "upper_bound": 0},
    ]
    annotations = {
        "metabolites": {row["id"]: {"values": {"mets": row["id"], "metsNoComp": row["id"].split("_")[0],
                                               "metChEBIID": "CHEBI:1" if row["id"].startswith("QA") else
                                                              "CHEBI:15422" if row["id"].startswith("ATP") else "CHEBI:2"},
                                      "record_number": n, "line_end": n}
                        for n, row in enumerate(metabolites, 2)},
        "genes": {row["id"]: {"values": {"genes": row["id"], "geneSymbols": row["name"]},
                               "record_number": n, "line_end": n} for n, row in enumerate(genes, 2)},
        "reactions": {row["id"]: {"values": {"rxns": row["id"]}, "record_number": n, "line_end": n}
                      for n, row in enumerate(reactions, 2)},
    }
    return {"model": {"metaData": {"version": "synthetic-test"}, "metabolites": metabolites,
                       "genes": genes, "reactions": reactions, "compartments": {"c": "test cytosol", "m": "test mitochondria"}},
            "annotations": annotations,
            "provenance": {"dataset_kind": "synthetic_fixture", "source": "invented unit-test graph",
                           "version": "synthetic-test", "fixture_note": "Not scientific evidence"}}
