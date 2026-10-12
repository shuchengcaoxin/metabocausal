"""Retrieve the specified gnomad_constraint field; make no safety verdict."""

from ._evidence import client, evidence_tool, number

URL = "https://gnomad.broadinstitute.org/api"
CONSTRAINT = '''query($symbol: String!) {
  gene(gene_symbol: $symbol, reference_genome: GRCh38) {
    gene_id symbol
    gnomad_constraint { pli oe_lof oe_lof_upper oe_mis }
  }
}'''


@evidence_tool("gnomAD", URL, (
    "Population loss-of-function constraint is not a clinical safety guarantee and does not establish tolerance of biallelic loss, tissue-specific or pharmacological inhibition.",
    "The queried gnomad_constraint field does not return a dataset release; reference genome GRCh38 is not a dataset version. Do not label these as latest v4 metrics.",
    "Missing metrics are unknown, not zero or evidence that the gene is unconstrained.",
))
def get_gnomad_constraint(gene_symbol: str) -> dict:
    """Return pLI, o/e LoF, LOEUF (= oe_lof_upper), and o/e missense."""
    gene = client().graphql(URL, CONSTRAINT, {"symbol": gene_symbol})["gene"]
    data = dict(gene=gene_symbol, ensembl=None, reference_genome="GRCh38",
                constraint_field="gnomad_constraint", dataset_release=None,
                pli=None, oe_lof=None, oe_lof_upper=None, loeuf=None, oe_mis=None)
    if gene is None:
        return "empty", data, ["Gene lookup returned null."]
    if gene["symbol"] != gene_symbol:
        raise ValueError("gnomAD resolved a different gene symbol")
    data["ensembl"] = gene["gene_id"]
    constraint = gene["gnomad_constraint"]
    if constraint is None:
        return "empty", data, ["No gnomad_constraint data returned for this gene."]
    for key in ("pli", "oe_lof", "oe_lof_upper", "oe_mis"):
        data[key] = number(constraint[key])
    data["loeuf"] = data["oe_lof_upper"]
    available = any(data[key] is not None for key in ("pli", "oe_lof", "oe_lof_upper", "oe_mis"))
    notes = [] if all(data[key] is not None for key in ("pli", "oe_lof", "oe_lof_upper", "oe_mis")) else ["Some or all constraint metrics are unavailable; nulls preserved."]
    return ("ok" if available else "empty"), data, notes


if __name__ == "__main__":
    import json
    print(json.dumps(get_gnomad_constraint("GLDC"), indent=2))
