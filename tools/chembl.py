"""ChEMBL single-protein mechanisms and assay-record counts."""

from urllib.parse import urljoin, urlsplit
from ._evidence import client, count, evidence_tool, rows

URL = "https://www.ebi.ac.uk/chembl/api/data"


def _pages(endpoint, key, params):
    records = []
    url = URL + endpoint
    seen = set()
    total = None
    for _ in range(100):
        if url in seen:
            raise ValueError("ChEMBL repeated a pagination URL")
        seen.add(url)
        page = client().request(url, params=params, retry_5xx=True)
        meta = page["page_meta"]
        current_total = count(meta["total_count"])
        if total is not None and total != current_total:
            raise ValueError("ChEMBL total_count changed during pagination")
        total = current_total
        records.extend(rows(page[key]))
        if not meta["next"]:
            if len(records) != total:
                raise ValueError("ChEMBL page counts do not match returned records")
            return records
        next_url = urljoin(url, meta["next"])
        parsed = urlsplit(next_url)
        if (parsed.scheme != "https" or parsed.netloc != "www.ebi.ac.uk"
                or parsed.path != urlsplit(URL + endpoint).path):
            raise ValueError("Unexpected ChEMBL pagination destination")
        url, params = next_url, None
    raise ValueError("ChEMBL pagination exceeded 100 pages; retrieval incomplete")


@evidence_tool("ChEMBL", URL, (
    "activity_count counts assay records, not unique ligands, potency, efficacy, or target quality.",
    "Mechanism annotations are source records, not evidence of benefit for the requested disease.",
))
def get_chembl_modulators(gene_symbol: str) -> dict:
    """Resolve an exact human single protein, retrieve mechanisms and activity count."""
    targets = _pages("/target/search.json", "targets", {"q": gene_symbol, "limit": 100})
    eligible = []
    for target in targets:
        if target["target_type"] != "SINGLE PROTEIN" or target["tax_id"] != 9606:
            continue
        # Keyword relevance alone can still select another human protein.
        symbols = [syn["component_synonym"]
                   for component in rows(target["target_components"])
                   for syn in rows(component["target_component_synonyms"])
                   if syn["syn_type"] == "GENE_SYMBOL"]
        if gene_symbol in symbols:
            eligible.append(target)
    data = dict(gene=gene_symbol, target=None, mechanisms=[], activity_count=None)
    if not eligible:
        return "empty", data, ["No exact gene-symbol human SINGLE PROTEIN target in ChEMBL search results."]
    target = eligible[0]  # Preserve ChEMBL relevance order among eligible records.
    target_id = target["target_chembl_id"]
    data["target"] = {key: target[key] for key in (
        "target_chembl_id", "target_type", "pref_name", "organism", "tax_id")}
    data["selection"] = "First human SINGLE PROTEIN with exact GENE_SYMBOL annotation in source search order"
    mechanisms = _pages("/mechanism.json", "mechanisms", {"target_chembl_id": target_id, "limit": 100})
    if any(row["target_chembl_id"] != target_id for row in mechanisms):
        raise ValueError("ChEMBL returned a mechanism for a different target")
    data["mechanisms"] = mechanisms
    activity = client().request(URL + "/activity.json", params={
        "target_chembl_id": target_id, "limit": 1}, retry_5xx=True)
    rows(activity["activities"])
    data["activity_count"] = count(activity["page_meta"]["total_count"])
    notes = []
    if len(eligible) > 1:
        notes.append("Multiple eligible protein targets; selected first in ChEMBL search order.")
    if len(client().requests) > 3:
        notes.append("Additional requests reflect pagination or one retry per transient HTTP 5xx failure.")
    return ("ok" if mechanisms or data["activity_count"] else "empty"), data, notes


if __name__ == "__main__":
    import json
    print(json.dumps(get_chembl_modulators("PCSK9"), indent=2))
