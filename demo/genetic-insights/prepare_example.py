"""Prepare the selected MVP1 example from saved project evidence and primary-source receipts.
Run from repository root: python demo/genetic-insights/prepare_example.py
No API key, LLM call, or Slack message. This is a curated fixture, not all-pair retrieval.
"""
import sys
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
import csv
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source_root = ROOT / "archive/project_files/release-evidence_2026-09-11/metabocausal-public/data"
    baseline = source_root / "metabolite_disease.csv"
    triples = source_root / "triples.csv.gz"
    atlas = ROOT / "data/atlas_locus_gene.csv"
    if not atlas.exists():
        atlas = ROOT / "archive/project_files/handoff-product_2026-09-11/runtime-data/data/atlas_locus_gene.csv"
    selection = None
    with baseline.open(encoding="utf-8-sig", newline="") as f:
        for line, row in enumerate(csv.DictReader(f), 2):
            if row["metabolite_name"] == "urate" and row["disease_id"] == "ieu-a-1054":
                selection = {"row": row, "line": line}
                break
    assert selection, "Expected baseline pair missing; do not substitute another example silently."
    triple = None
    with gzip.open(triples, "rt", encoding="utf-8-sig", newline="") as f:
        for line, row in enumerate(csv.DictReader(f), 2):
            if row["metabolite_name"] == "urate" and row["disease_id"] == "ieu-a-1054" and row["gene_symbol"] == "SLC2A9":
                triple = {"row": row, "line": line}
                break
    assert triple, "Expected SLC2A9 annotated candidate missing."
    with atlas.open(encoding="utf-8-sig", newline="") as f:
        atlas_rows = [{"line": line, "row": row} for line, row in enumerate(csv.DictReader(f), 2)
                      if row["metabolite_name"] == "urate"]
    source_receipts = {}
    for name in ("trial", "papers", "label"):
        path = HERE / "sources" / (name + ".json")
        source_receipts[name] = json.loads(path.read_text(encoding="utf-8"))
    trial = source_receipts["trial"]["data"]["protocolSection"]
    status = trial["statusModule"]
    label = source_receipts["label"]["data"]["results"][0]
    checked = source_receipts["trial"]["retrieved_at"][:10]
    label_date = label["effective_time"]
    label_date = f"{label_date[:4]}-{label_date[4:6]}-{label_date[6:8]}"
    sources = [
        {"id":"baseline", "title":"MVP1 urate–gout MR record", "url":"https://epigraphdb.org/mr",
         "location":f"metabolite_disease.csv, CSV record {selection['line']} (header = 1)",
         "note":"Exact original row is included in provenance. The web link identifies the database; the saved row establishes this snapshot."},
        {"id":"atlas", "title":"MVP1 SLC2A9 annotation", "url":"https://doi.org/10.1038/ng.2982",
         "location":f"triples.csv.gz, decompressed CSV record {triple['line']} (header = 1); atlas rs938554",
         "note":"Source gene attribution is nearest, Shin 2014. This is a candidate annotation, not confirmed mediation."},
        {"id":"vitart", "title":"Vitart et al., Nature Genetics (2008)", "url":"https://doi.org/10.1038/ng.106",
         "location":"Abstract; online publication 2008-03-09; PMID 18327257",
         "note":"Genetic associations with urate/excretion/gout and experimental urate transport. Added for this curated demo."},
        {"id":"caulfield", "title":"Caulfield et al., PLoS Medicine (2008)", "url":"https://pubmed.ncbi.nlm.nih.gov/18842065/",
         "location":"Abstract; 2008-10 (month precision); DOI 10.1371/journal.pmed.0050197",
         "note":"Functional urate-transport evidence; do not treat a metadata day of 01 as a verified publication day."},
        {"id":"approval", "title":"FDA original febuxostat approval (2009)", "url":"https://www.accessdata.fda.gov/drugsatfda_docs/appletter/2009/021856s000ltr.pdf",
         "location":"NDA 21-856 original approval; February 13, 2009, also referenced in the 2019 supplement letter",
         "note":"US regulatory event; not proof of the SLC2A9 mechanism."},
        {"id":"cares", "title":"ClinicalTrials.gov — CARES", "url":"https://clinicaltrials.gov/study/NCT01101035",
         "location":"protocolSection: identificationModule, statusModule, designModule, eligibilityModule",
         "note":"Gout participants with cardiovascular comorbidities. Cardiovascular safety outcome; not a gout-onset prevention trial."},
        {"id":"cares_paper", "title":"White et al., NEJM (2018)", "url":"https://doi.org/10.1056/NEJMoa1710895",
         "location":"Abstract; published online 2018-03-12; PMID 29527974",
         "note":"Noninferior primary cardiovascular composite; higher cardiovascular and all-cause mortality with febuxostat versus allopurinol in this trial population."},
        {"id":"warning", "title":"FDA label-change approval (2019)", "url":"https://www.accessdata.fda.gov/drugsatfda_docs/appletter/2019/021856Orig1s013ltr.pdf",
         "location":"Pages 1 and 3; signature dated 2019-02-21",
         "note":"CARES-related labeling change, boxed warning and modification of indication."},
        {"id":"label", "title":"FDA labeling record — Uloric", "url":source_receipts["label"]["url"],
         "location":f"label ID {label['id']}; effective_time {label_date}; mechanism_of_action, indications_and_usage, boxed_warning",
         "note":"Retrieved label retains a cardiovascular-death boxed warning and a restricted gout indication. One selected label record; not an exhaustive labeling or global programme search."},
    ]
    events = [
        {"id":"slc2a9-2008","date":"2008-03-09","precision":"day","type":"Genetic evidence","title":"SLC2A9, urate & gout",
         "description":"Human genetic associations and urate-transport experiments connect SLC2A9 with urate handling and gout.",
         "source_ids":["vitart"],"scope":"Gene / metabolite / disease evidence"},
        {"id":"fda-2009","date":"2009-02-13","precision":"day","type":"US approval","title":"Febuxostat approved",
         "description":"FDA approved febuxostat for hyperuricemia in adults with gout. It lowers urate through xanthine oxidase inhibition, a different mechanism from SLC2A9 transport.",
         "source_ids":["approval","label"],"scope":"Direct urate-lowering intervention context"},
        {"id":"cares-start","date":status["startDateStruct"]["date"],"precision":"day","type":"Clinical trial","title":"CARES begins",
         "description":"Randomized febuxostat versus allopurinol cardiovascular-safety study in people with gout and cardiovascular comorbidities. Registry phase: Phase 3; official title: Phase 3B.",
         "source_ids":["cares"],"scope":"Safety in the specified gout population"},
        {"id":"cares-results","date":"2018-03-12","precision":"day","type":"Clinical results","title":"Benefits & risks diverge",
         "description":"The primary cardiovascular composite met noninferiority; cardiovascular and all-cause mortality were higher with febuxostat than allopurinol in CARES.",
         "source_ids":["cares_paper"],"scope":"Trial-specific safety result"},
        {"id":"fda-2019","date":"2019-02-21","precision":"day","type":"Label update","title":"US boxed warning",
         "description":"FDA approved a boxed warning and a narrower indication following CARES. This is a safety-related label change, not a withdrawal of all urate-lowering treatments.",
         "source_ids":["warning"],"scope":"US regulatory update"},
    ]
    sections = [
        {"id":"question","title":"The question","text":"For urate and gout, what genetic evidence is already available, what gene context can we explain, and what can related clinical experience teach a research team?","source_ids":["baseline","atlas"]},
        {"id":"mr","title":"Retrieved genetic evidence","text":"The selected MVP1 record contains a positive pre-computed MR estimate for urate and gout. It was retrieved from MR-EVE, not recomputed here. Method and deposited dataset IDs remain attached to the original values.","source_ids":["baseline"]},
        {"id":"gene","title":"Gene context: SLC2A9","text":"The project atlas nominates SLC2A9 by proximity to rs938554. Separately, the 2008 paper provides human genetic and experimental evidence for urate transport. These are different evidence types and remain separately attributed.","source_ids":["atlas","vitart","caulfield"]},
        {"id":"clinical","title":"Related clinical experience","text":"Febuxostat lowers urate by inhibiting xanthine oxidase. It is included through the direct urate-lowering route, not as an SLC2A9-targeted treatment. CARES adds a cardiovascular-safety question in a specific gout population.","source_ids":["label","cares"]},
        {"id":"decision","title":"What to check next","text":"A molecule-level genetic finding does not settle the safety of a particular drug. Review the MR design and missing diagnostics, then evaluate target mechanism, intended population and clinical endpoints separately.","source_ids":["baseline","atlas","cares_paper"]},
        {"id":"limitations","title":"What remains uncertain","text":"Colocalisation and gene-QTL evidence were not queried in the selected baseline record. Nearest-gene assignment does not prove mediation. MR confidence-interval scale and level are unspecified in the source. This selected chronology is not an exhaustive clinical review.","source_ids":["baseline","atlas"]},
    ]
    bundle = {
        "schema_version":"1.0","snapshot_id":"mvp1-urate-gout-2026-09-12-v1","checked_at":checked,
        "mode":"Curated recording demo · saved evidence",
        "pair":{"metabolite":"Urate","gene":"SLC2A9","disease":"Gout","exposure_id":"ieu-a-789","outcome_dataset_id":"ieu-a-1054"},
        "headline":"From genetic evidence to the next research question.",
        "summary":"Inspect an existing urate–gout finding, the SLC2A9 gene context, and the clinical history of a related urate-lowering treatment.",
        "relationship_note":"Febuxostat acts through xanthine oxidase inhibition. SLC2A9 is the genetic context here, not its drug target. Chronology does not establish that genetics drove the development decision.",
        "sections":sections,"events":events,"sources":sources,
        "current_status":{
            "trial_id":"NCT01101035","trial_phase":", ".join(trial["designModule"]["phases"]),
            "trial_status":status["overallStatus"],"trial_updated_at":status["lastUpdatePostDateStruct"]["date"],
            "trial_description":"CARES cardiovascular-safety study in gout with cardiovascular comorbidities",
            "regulatory":"US approval with a cardiovascular-death boxed warning and restricted indication in the retrieved label.",
            "label_effective_at":label_date,"programme_status":"Not assessed beyond this selected study and label.",
            "source_ids":["cares","label"]
        },
        "modules":[
            {"name":"MVP1","status":"Saved evidence available","detail":"Existing MR record, atlas annotation and archived full report."},
            {"name":"Genetic Insights","status":"Curated example ready","detail":"Five source-linked milestones; automatic all-pair preparation remains integration work."},
            {"name":"Jingrui · MVP2","status":"Awaiting accepted output","detail":"Seed papers and Europe PMC literature evidence."},
            {"name":"Ziwei · MVP2","status":"Awaiting accepted output","detail":"Semantic Scholar evidence, merged by paper identity."},
            {"name":"Zipeng · MVP3","status":"Awaiting accepted output","detail":"Human-GEM biochemical context."},
            {"name":"Slack","status":"Export ready; live delivery unverified","detail":"Same snapshot produces Slack text and attachments; Zhang Hao connects the bot."},
            {"name":"LLM interpretation","status":"No model run for this demo","detail":"The visible summary was prepared for the saved example. OpenAI/Claude code support is separate."},
        ],
        "provenance":{
            "preparation":"Curated primary-source supplement to existing MVP1 data. Not generated by the unfinished MVP2/MVP3 pipeline.",
            "code_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
            "baseline":{"path":baseline.relative_to(ROOT).as_posix(),"sha256":digest(baseline),**selection},
            "triple":{"path":triples.relative_to(ROOT).as_posix(),"sha256":digest(triples),**triple},
            "atlas":{"path":atlas.relative_to(ROOT).as_posix(),"sha256":digest(atlas),"records":atlas_rows},
            "source_receipts":{key:{"file":f"sources/{key}.json","url":value["url"],"retrieved_at":value["retrieved_at"],"sha256":digest(HERE/"sources"/f"{key}.json")} for key,value in source_receipts.items()},
            "note":"CSV record positions include header=1. Outcome dataset IDs are not disease ontology IDs. Do not count repeated methods or dataset aliases as independent studies.",
        },
        "legacy_report":{
            "label":"Archived full MVP1 report · run dated 2026-09-10",
            "text":(ROOT/"examples/urate_gout.md").read_text(encoding="utf-8"),
            "note":"Separate older run with 22 MR rows; do not combine its counts with the selected September 11 baseline row or newly prepared timeline."
        }
    }
    out=HERE/"snapshots"/f"{bundle['snapshot_id']}.json"
    out.parent.mkdir(exist_ok=True)
    text=json.dumps(bundle,ensure_ascii=False,indent=2)+"\n"
    if out.exists() and out.read_text(encoding="utf-8") != text:
        raise SystemExit("Snapshot exists with different contents; create a new version instead of overwriting it.")
    out.write_text(text,encoding="utf-8")
    print(out)
    print("Selected baseline CSV record:",selection["line"],"triple CSV record:",triple["line"])

if __name__ == "__main__":
    main()
