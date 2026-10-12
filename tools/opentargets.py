"""Open Targets association context and uncollapsed clinical reports."""

from ._evidence import client, count, evidence_tool, number, rows

URL = "https://api.platform.opentargets.org/api/v4/graphql"
SEARCH = '''query($q: String!) {
  search(queryString: $q, entityNames: ["target"]) { hits { id name entity } }
}'''
ASSOCIATIONS = '''query($id: String!) {
  target(ensemblId: $id) {
    approvedSymbol
    associatedDiseases(page: {index: 0, size: 25}) {
      count
      rows { disease { id name } score datatypeScores { id score } }
    }
  }
}'''
DRUGS = '''query($id: String!) {
  target(ensemblId: $id) {
    approvedSymbol
    drugAndClinicalCandidates {
      count
      rows {
        id
        maxClinicalStage
        drug { id name }
        clinicalReports {
          id url type
          trialPhase trialOverallStatus trialWhyStopped year source
          diseases { disease { id name } diseaseFromSource }
        }
      }
    }
  }
}'''


def _resolve(symbol):
    hits = rows(client().graphql(URL, SEARCH, {"q": symbol})["search"]["hits"])
    exact = [hit for hit in hits if hit["entity"] == "target" and hit["name"] == symbol]
    ids = {hit["id"] for hit in exact}
    if len(ids) > 1:
        raise ValueError("Ambiguous exact target symbol; multiple Ensembl IDs returned")
    return next(iter(ids), None)


def _target(query, ensembl, symbol):
    target = client().graphql(URL, query, {"id": ensembl})["target"]
    if target is not None and target["approvedSymbol"] != symbol:
        raise ValueError("Resolved target approvedSymbol differs from requested symbol")
    return target


@evidence_tool("Open Targets", URL, (
    "Association scores aggregate evidence types, including clinical evidence; they are not MR estimates or causal probabilities.",
    "Only the first associatedDiseases page (index 0, size 25) is queried; absence is not evidence of no association.",
))
def get_target_disease_evidence(gene_symbol: str, disease_efo: str) -> dict:
    """Target-disease association on the returned page, plus top-5 context."""
    ensembl = _resolve(gene_symbol)
    data = dict(gene=gene_symbol, ensembl=ensembl, disease_efo=disease_efo,
                target_disease=None, top_diseases=[])
    if ensembl is None:
        return "empty", data, ["No exact target symbol in returned Open Targets search hits."]
    target = _target(ASSOCIATIONS, ensembl, gene_symbol)
    if target is None:
        return "empty", data, ["Resolved target returned null."]
    page = target["associatedDiseases"]
    records = rows(page["rows"])
    for row in records:
        row["disease"]["name"]
        row["disease"]["id"]
        number(row["score"])
        for score in rows(row["datatypeScores"]):
            score["id"]
            number(score["score"])
    data["page"] = dict(index=0, size=25, returned_count=len(records),
                        total_count=count(page["count"]))
    data["top_diseases"] = records[:5]
    data["target_disease"] = next((row for row in records
                                    if row["disease"]["id"] == disease_efo), None)
    found = data["target_disease"] is not None
    return ("ok" if found else "empty"), data, ([] if found else [
        "Target disease not present in returned associatedDiseases page; top diseases are context only."])


@evidence_tool("Open Targets", URL, (
    "Clinical phase or maxClinicalStage is not approval, efficacy, or trial success.",
    "Each clinical report retains its own diseases, phase, status and stopping reason; drug-level maximum stage must not be assigned to a requested disease.",
    "Null report fields are unknown. Completed, terminated and withdrawn statuses alone do not establish efficacy or the reason for failure.",
    "clinicalReports includes trials, regulatory records, labels and curated resources; use report_type rather than treating every report as a trial.",
))
def get_known_drugs(gene_symbol: str) -> dict:
    """Retrieve drugAndClinicalCandidates; keep each report and indication intact."""
    ensembl = _resolve(gene_symbol)
    data = dict(gene=gene_symbol, ensembl=ensembl, count=None, drugs=[])
    if ensembl is None:
        return "empty", data, ["No exact target symbol in returned Open Targets search hits."]
    target = _target(DRUGS, ensembl, gene_symbol)
    if target is None:
        return "empty", data, ["Resolved target returned null."]
    candidates = target["drugAndClinicalCandidates"]
    data["count"] = count(candidates["count"])
    for row in rows(candidates["rows"]):
        reports = []
        for report in rows(row["clinicalReports"]):
            # One API report -> one output report; retain multiple diseases and nulls.
            reports.append(dict(
                report_id=report["id"], url=report["url"], report_type=report["type"],
                trial_phase=report["trialPhase"], status=report["trialOverallStatus"],
                why_stopped=report["trialWhyStopped"], year=report["year"],
                source=report["source"], diseases=rows(report["diseases"])))
        drug = row["drug"]
        data["drugs"].append(dict(candidate_id=row["id"],
                                  drug=None if drug is None else drug["name"],
                                  drug_id=None if drug is None else drug["id"],
                                  max_clinical_stage=row["maxClinicalStage"],
                                  clinical_reports=reports))
    data["returned_count"] = len(data["drugs"])
    data["complete"] = data["returned_count"] == data["count"]
    if not data["complete"]:
        raise ValueError("Candidate count differs from returned rows; source has no pagination argument")
    return ("ok" if data["drugs"] else "empty"), data, []


if __name__ == "__main__":
    import json
    print(json.dumps(get_target_disease_evidence("PCSK9", "EFO_0001645"), indent=2))
    print(json.dumps(get_known_drugs("PCSK9"), indent=2))
