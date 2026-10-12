"""Export machine-readable case/event tables from the reviewed MVP1 bundles."""
import csv
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent

def main():
    cases=[]; events=[]; sources={}
    for path in sorted((HERE/"snapshots").glob("mvp1-cetp-*-v2.json"),reverse=True):
        b=json.loads(path.read_text(encoding="utf-8"));p=b["pair"];st=b["current_status"]
        drug="torcetrapib" if "torcetrapib" in b["snapshot_id"] else "evacetrapib"
        stop_ref="pfizer" if drug=="torcetrapib" else "lilly"
        refs={s["id"]:s for s in b["sources"]}
        cases.append({
            "case_id":drug+"-cad","snapshot_id":b["snapshot_id"],
            "metabolite":p["metabolite"],"gene_symbol":p["gene"],"ensembl_gene_id":"ENSG00000087237",
            "disease":p["disease"],"outcome_dataset_id":p["outcome_dataset_id"],
            "drug":drug,"drug_type":"small_molecule","drug_target":"CETP","action":"inhibition",
            "drug_target_source":refs["torce_paper" if drug=="torcetrapib" else "evace_paper"]["url"],
            "indication_match":"related_population_and_cardiovascular_endpoint",
            "match_note":refs["torce_trial" if drug=="torcetrapib" else "evace_trial"]["note"],
            "trial_id":st["trial_id"],"phase":st["trial_phase"],"trial_status":st["trial_status"],
            "trial_source":"https://clinicaltrials.gov/study/"+st["trial_id"],
            "trial_last_updated":st["trial_updated_at"],"checked_at":b["checked_at"],
            "programme_status":"discontinued_for_this_indication",
            "failure_type":"safety" if drug=="torcetrapib" else "insufficient_efficacy",
            "programme_decision_date":st["label_effective_at"],"programme_source":refs[stop_ref]["url"],
            "coverage_status":"curated_timeline_available","event_count":len(b["events"]),
            "baseline_csv_record":b["provenance"]["baseline"]["line"],
            "triple_csv_record":b["provenance"]["triple"]["line"],
            "baseline_path":b["provenance"]["baseline"]["path"],
            "triple_path":b["provenance"]["triple"]["path"],
            "bundle_path":"snapshots/"+path.name,
            "html_path":"recordings/cetp-"+drug+"-v2/index.html",
            "preparation":"curated MVP1 example; not automatic corpus coverage",
        })
        for e in b["events"]:
            events.append({
                "case_id":drug+"-cad","snapshot_id":b["snapshot_id"],"event_id":e["id"],
                "event_date":e["date"],"date_precision":e["precision"],
                "evidence_stage":e["evidence_stage"],
                "event_type":e["type"],"title":e["title"],"description":e["description"],
                "evidence_scope":e["scope"],"source_ids":";".join(e["source_ids"]),
                "source_urls":";".join(refs[i]["url"] for i in e["source_ids"]),
                "interpretation_timing":"after_programme_stop" if e["date"]>st["label_effective_at"] else "at_or_before_programme_stop",
                "checked_at":b["checked_at"],
            })
        sources.update(refs)
    out=HERE/"tables";out.mkdir(exist_ok=True)
    for name,rows in [("mvp1_timeline_cases",cases),("mvp1_timeline_events",events),("mvp1_timeline_sources",list(sources.values()))]:
        with (out/(name+".csv")).open("w",encoding="utf-8-sig",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        (out/(name+".json")).write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["# MVP1 timelines — ready example table","",
           "Two reviewed candidate examples from the existing MVP1 table; not an all-pair coverage scan. These v2 timelines replace the incomplete v1 examples.",
           "Both use HDL cholesterol · CETP · coronary artery disease. HDL cholesterol is a lipid measure, not a single chemically defined metabolite.",
           "Baseline CSV record **4145**; expanded candidate CSV record **328106** (header = 1).",
            "","Each v2 case covers human genetics, preclinical evidence, clinical development and later interpretation. Target-class evidence is labelled separately from compound-specific evidence.",
            "","| Case | Target-matched drug | Phase / latest registry state | Programme outcome | Recording |",
           "| --- | --- | --- | --- | --- |"]
    for c in cases:
        lines.append(f"| {c['case_id']} | CETP inhibitor: {c['drug']} | [{c['phase']} / {c['trial_status']}]({c['trial_source']}) | [{c['failure_type']}, {c['programme_decision_date']}]({c['programme_source']}) | [Open HTML]({c['html_path']}#insights) |")
    lines+=["","The trial population and endpoint are related to the CAD question, not identical. Status is a dated source report; the retrieval date is not a scientific event.",
            "","## Torcetrapib — record this first",
            "",
            "| Date | Stage | Event | What to say | Source |",
            "| --- | --- | --- | --- | --- |"]
    for e in events:
        if e["case_id"]=="torcetrapib-cad":
            lines.append(f"| {e['event_date']} | {e['evidence_stage'].replace('_',' ')} | {e['title']} | {e['description']} | [Record]({e['source_urls'].split(';')[0]}) |")
    lines+=["","## Evacetrapib — second recording example","",
            "| Date | Stage | Event | What to say | Source |","| --- | --- | --- | --- | --- |"]
    for e in events:
        if e["case_id"]=="evacetrapib-cad":
            lines.append(f"| {e['event_date']} | {e['evidence_stage'].replace('_',' ')} | {e['title']} | {e['description']} | [Record]({e['source_urls'].split(';')[0]}) |")
    lines+=["","## Why this is useful, without rewriting history","",
            "The torcetrapib timeline now begins with 1989 human genetics and 1998/2000 target-level preclinical evidence, then shows the compound's clinical development. The 2009 genetic comparison and 2012 HDL MR paper came after the 2006 failure and cannot be presented as advance predictions.",
            "",
            "Evacetrapib is a separate efficacy failure. The 2012 HDL MR evidence preceded ACCELERATE, but did not by itself predict the outcome of this specific CETP inhibitor.",
            "",
            "Do not conclude that CETP is invalid: [REVEAL showed benefit with anacetrapib](https://doi.org/10.1056/NEJMoa1706444). [CETP/HMGCR genetic analyses](https://doi.org/10.1001/jama.2017.11467) also refine the mechanism toward apoB-related effects.",
            "",
            "## A later candidate, not yet a complete recording timeline","",
            "[Obicetrapib / PREVAIL](https://clinicaltrials.gov/study/NCT05202509): retrieved Phase 3 ACTIVE_NOT_RECRUITING; registry last updated 2024-06-04. A [2026-01-09 sponsor update](https://ir.newamsterdampharma.com/news-releases/news-release-details/newamsterdam-pharma-highlights-2025-achievements-and-outlines) discusses continued development. Keep it as a separate drug story and verify newer records before presenting a current programme verdict.",
            "",
            "## Files for integration","",
            "- [Cases CSV](tables/mvp1_timeline_cases.csv): one row per drug–indication story.",
            "- [Events CSV](tables/mvp1_timeline_events.csv): one row per milestone, joined by case_id.",
            "- [Sources CSV](tables/mvp1_timeline_sources.csv): original sources and precise claim boundaries.",
            "- Matching JSON files are alongside the CSVs; the full bundles retain original MR and atlas records.",
            "- [Zhang Hao's first implementation steps](ZHANG_HAO_START_HERE.md).",
            ""]
    (HERE/"MVP1_TIMELINE_TABLE.md").write_text("\n".join(lines),encoding="utf-8")
    print(f"Prepared {len(cases)} cases, {len(events)} events, {len(sources)} sources.")
if __name__=="__main__":main()
