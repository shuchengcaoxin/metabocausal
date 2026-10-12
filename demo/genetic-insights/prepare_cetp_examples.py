"""Prepare two target-matched failure examples; reads saved sources only."""
import copy
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys
if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(name): return json.loads((HERE/"sources"/name).read_text(encoding="utf-8"))
def source(id,title,url,location,note):
    return dict(id=id,title=title,url=url,location=location,note=note)
def event(id,date,precision,type,title,description,refs,scope,evidence_stage):
    return dict(id=id,date=date,precision=precision,type=type,title=title,description=description,source_ids=refs,scope=scope,evidence_stage=evidence_stage)

def main():
    base=json.loads((HERE/"snapshots/mvp1-urate-gout-2026-09-12-v1.json").read_text(encoding="utf-8"))
    data=ROOT/"archive/project_files/release-evidence_2026-09-11/metabocausal-public/data"
    baseline=data/"metabolite_disease.csv"; triples=data/"triples.csv.gz"
    atlas=ROOT/"archive/project_files/handoff-product_2026-09-11/runtime-data/data/atlas_locus_gene.csv"
    def matches(r):
        return r["metabolite_name"].lower()=="hdl cholesterol" and r["disease_id"]=="ebi-a-GCST005194"
    with baseline.open(encoding="utf-8-sig",newline="") as f:
        selected=next({"line":i,"row":r} for i,r in enumerate(csv.DictReader(f),2) if matches(r))
    with gzip.open(triples,"rt",encoding="utf-8-sig",newline="") as f:
        triple=next({"line":i,"row":r} for i,r in enumerate(csv.DictReader(f),2) if matches(r) and r["gene_symbol"]=="CETP")
    with atlas.open(encoding="utf-8-sig",newline="") as f:
        ar=[{"line":i,"row":r} for i,r in enumerate(csv.DictReader(f),2) if r["metabolite_name"].lower()=="hdl cholesterol" and r["gene_symbol"]=="CETP"]
    sources=[
        source("baseline","MVP1 HDL cholesterol–CAD record","https://epigraphdb.org/mr",
               f"metabolite_disease.csv record {selected['line']}; header = 1",
               "Selected pre-computed estimate, not a target-specific MR analysis. Original source values are in the evidence bundle."),
        source("atlas","MVP1 CETP annotation / Zoodsma 2025","https://doi.org/10.1038/s41588-025-02355-3",
               f"triples.csv.gz decompressed record {triple['line']}; atlas rs821840 and rs189866004",
               "Author-prioritized gene annotation for HDL cholesterol, ENSG00000087237. The present atlas is not evidence available to a 2006 decision-maker."),
        source("cetp_deficiency","Inherited CETP deficiency (1989)","https://pubmed.ncbi.nlm.nih.gov/2586614/",
               "Nature paper; published 1989-11-23; PMID 2586614",
               "A CETP splice-site mutation caused inherited CETP deficiency and markedly increased HDL. This establishes human genetic effects on the biomarker, not protection from coronary disease."),
        source("cetp_antisense","CETP suppression in rabbits (1998)","https://pubmed.ncbi.nlm.nih.gov/9478952/",
               "Journal paper; published 1998-02-27; PMID 9478952",
               "Target-level preclinical evidence: CETP antisense treatment reduced atherosclerotic lesions in cholesterol-fed rabbits. This was not a torcetrapib experiment."),
        source("cetp_inhibitor_rabbit","CETP inhibitor in rabbits (2000)","https://pubmed.ncbi.nlm.nih.gov/10910363/",
               "Nature paper; published 2000-07-13; PMID 10910363",
               "A different CETP inhibitor, JTT-705, improved lipids and attenuated rabbit atherosclerosis. It supports the target class, not torcetrapib-specific safety or efficacy."),
        source("torce_phase1","Torcetrapib Phase 1 study (2004)","https://pubmed.ncbi.nlm.nih.gov/14739125/",
               "Phase 1 multidose study; published 2004-03; PMID 14739125",
               "Early human proof of mechanism: torcetrapib increased HDL over 14 days. Publication date is shown; the study began earlier, but no verified start date is asserted here."),
        source("torce_trial","ILLUMINATE registry","https://clinicaltrials.gov/study/NCT00134264",
               "protocolSection identification, status, design and eligibility",
               "Phase 3 torcetrapib/atorvastatin versus atorvastatin. Population includes coronary heart disease or high-risk diabetes; broader than the exact CAD GWAS population."),
        source("pfizer","Pfizer programme stop (2006)","https://www.sec.gov/Archives/edgar/data/78003/000007800306000334/ex991202.htm",
               "Pfizer release, 2006-12-02, filed with SEC",
               "Sponsor stopped trials and compound development after the mortality/cardiovascular-event imbalance."),
        source("torce_paper","ILLUMINATE results (2007)","https://doi.org/10.1056/NEJMoa0706628",
               "Abstract and discussion; published online 2007-11-05; PMID 17984165",
               "Torcetrapib increased HDL but increased mortality and cardiovascular morbidity. This does not isolate CETP inhibition as the cause of harm."),
        source("offtarget","CETP genetics versus torcetrapib (2009 online)","https://pubmed.ncbi.nlm.nih.gov/20026784/",
               "Abstract; online 2009-12-21, journal issue 2010; DOI 10.1161/CIRCULATIONAHA.109.865444",
               "Genetic lipid effects resembled treatment; blood-pressure effects did not. Supports an off-target interpretation of the hypertensive effect, not proof of every cause of death."),
        source("hdl_mr","HDL cholesterol and heart attack MR (2012)","https://doi.org/10.1016/S0140-6736(12)60312-2",
               "Abstract / interpretation; 2012-05-17; PMID 22607825",
               "Some genetic mechanisms raising HDL did not lower myocardial-infarction risk. HDL-level evidence is not a CETP-specific verdict; MI is related to, but not identical to, the CAD dataset outcome."),
        source("evace_trial","ACCELERATE registry","https://clinicaltrials.gov/study/NCT01687998",
               "protocolSection identification, status, design and eligibility",
               "Phase 3, terminated for insufficient efficacy. High-risk vascular population and composite endpoint, not an exact reproduction of the CAD GWAS."),
        source("lilly","Lilly programme stop (2015)","https://investor.lilly.com/node/24656",
               "Sponsor release, 2015-10-12",
               "Development for high-risk ASCVD discontinued due to insufficient efficacy; the stated stop was not for safety findings."),
        source("evace_paper","ACCELERATE results (2017)","https://doi.org/10.1056/NEJMoa1609581",
               "Abstract and trial results; 2017-05 (month precision); PMID 28514624",
               "Favorable lipid changes did not translate into fewer cardiovascular events in this trial."),
        source("cetp_mr","CETP/HMGCR genetic analysis (2017)","https://doi.org/10.1001/jama.2017.11467",
               "Abstract / conclusions; JAMA online 2017-08-28; PMID 28846118",
               "Cardiovascular associations tracked apoB reduction in the joint genetic analysis. Do not reduce CETP effects to HDL elevation alone."),
        source("reveal","REVEAL anacetrapib results (2017)","https://doi.org/10.1056/NEJMoa1706444",
               "Abstract; NEJM online 2017-08-29; PMID 28847206",
               "Anacetrapib reduced major coronary events in REVEAL. Necessary counterexample to a claim that all CETP inhibition fails."),
        source("prevail","Obicetrapib PREVAIL registry","https://clinicaltrials.gov/study/NCT05202509",
               "protocolSection status and design; source update 2024-06-04",
               "Retrieved Phase 3 ACTIVE_NOT_RECRUITING record. Old registry update, not proof of current recruitment or programme-wide regulatory status."),
        source("sponsor2026","NewAmsterdam 2026 programme update","https://ir.newamsterdampharma.com/news-releases/news-release-details/newamsterdam-pharma-highlights-2025-achievements-and-outlines",
               "Sponsor release 2026-01-09; PREVAIL section",
               "Reports continuing obicetrapib development. Projections are not achieved outcomes; no global approval status is established here."),
    ]
    base.update({
        "pair":{"metabolite":"HDL cholesterol","gene":"CETP","disease":"Coronary artery disease","exposure_id":selected["row"]["exposure_id"],"outcome_dataset_id":selected["row"]["disease_id"]},
        "headline":"The blood marker improved. The trial failed.",
        "summary":"Follow CETP from human genetics and preclinical evidence into clinical testing, failure, later interpretation and the target class's current status.",
        "source_groups":["Human genetics","Preclinical studies","ClinicalTrials.gov","Trial papers & sponsor records","Later genetic interpretation"],
        "case_navigation":True,"sources":sources,
        "relationship_note":"This timeline starts with human genetics and target-level preclinical evidence, then follows the compound into clinical trials and later genetic reinterpretation. Early evidence supported CETP's effect on HDL and the target rationale; it did not establish torcetrapib safety or clinical benefit.",
        "timeline_standard":{
            "required_stages":["human_genetics","preclinical","clinical"],
            "display_order":["human_genetics","preclinical","clinical","later_genetics","class_status"],
            "note":"A missing stage must be reported as missing, never silently omitted. Target-class evidence and compound-specific evidence must remain distinct."
        },
        "sections":[
            {"id":"question","title":"The question","text":"If a drug improves HDL cholesterol, will it protect patients from coronary events? And if it fails, is the problem the blood marker, the target, or the particular drug?","source_ids":["torce_paper","hdl_mr"]},
            {"id":"mr","title":"Retrieved MR: inspect the design","text":"The selected MVP1 HDL–CAD row has a negative pre-computed estimate. It remains visible beside the later curated literature. Different instruments, populations and endpoints can lead to different conclusions; a source p-value does not resolve these differences.","source_ids":["baseline","hdl_mr"]},
            {"id":"gene","title":"A target-matched example: CETP","text":"CETP is an author-prioritized HDL gene in the project atlas. Torcetrapib and evacetrapib inhibit the CETP protein. This gives a real gene-to-drug link, while the atlas annotation alone does not prove mediation.","source_ids":["atlas","torce_paper","evace_paper"]},
            {"id":"clinical","title":"What failed?","text":"Torcetrapib was stopped after excess mortality and cardiovascular events. Evacetrapib was stopped for insufficient efficacy. These are different failure modes and are shown as separate drug histories.","source_ids":["pfizer","lilly"]},
            {"id":"decision","title":"What genetics adds","text":"Comparing CETP gene variants with torcetrapib helped distinguish lipid changes from the drug's blood-pressure effect. HDL-focused MR also challenged the assumption that raising this marker must prevent heart attacks.","source_ids":["offtarget","hdl_mr"]},
            {"id":"limits","title":"Keep the counterevidence","text":"This is not proof that genetic analysis would have predicted every failure, or that CETP is an invalid target. REVEAL found benefit with anacetrapib, and target-specific genetic analyses point to apoB-related effects.","source_ids":["reveal","cetp_mr"]},
            {"id":"current-class","title":"The target's story continues","text":"A retrieved PREVAIL record lists obicetrapib as Phase 3, active not recruiting; its last update is June 2024. A January 2026 sponsor update discusses continued development. Neither record is a completed cardiovascular-outcome result.","source_ids":["prevail","sponsor2026"]},
            {"id":"limitations","title":"What remains unresolved","text":"The selected baseline has no queried colocalisation or gene-QTL evidence. Source CI bounds include zero despite a small reported p-value; the CI level and scale are unspecified, so these fields are flagged rather than silently repaired. No claim of causal confidence is made from State A.","source_ids":["baseline","atlas"]},
        ],
        "provenance":{
            "preparation":"Curated lifecycle example spanning human genetics, preclinical evidence, clinical development, later interpretation and current class status. Built from existing MVP1 records and explicitly retrieved primary sources. No automatic all-pair timeline search, no MVP2/MVP3 completion, and no live Slack deployment is claimed.",
            "baseline":{"path":baseline.relative_to(ROOT).as_posix(),"sha256":sha(baseline),**selected},
            "triple":{"path":triples.relative_to(ROOT).as_posix(),"sha256":sha(triples),**triple},
            "atlas":{"path":atlas.relative_to(ROOT).as_posix(),"sha256":sha(atlas),"records":ar},
            "source_receipts":{p.name:{"path":"sources/"+p.name,"sha256":sha(p),"retrieved_at":json.loads(p.read_text(encoding="utf-8"))["retrieved_at"]} for p in (HERE/"sources").glob("*.json") if p.name.startswith(("NCT","cetp-"))},
            "note":"Original fields preserved, including the source CI/p discrepancy. This selected MR estimate is not CETP-target MR. Annotation is a candidate link. Year of the current atlas must not be backdated to the historical drug decision.",
        },
        "legacy_report":{
            "label":"Selected original MVP1 records",
            "note":"These are original table records, not a new full pipeline run. The urate report belongs to a different example and is not included.",
            "text":"# Selected original MVP1 evidence\n\n## MR record\n\n"+json.dumps(selected,indent=2)+"\n\n## CETP annotated candidate\n\n"+json.dumps(triple,indent=2)+"\n\n## Atlas records\n\n"+json.dumps(ar,indent=2)
        },
    })
    # Reuse module labels; the primary demo contains curated source records, not a claimed agent result.
    base["modules"][1]["detail"]="Two target-matched failure histories with dated sources; all-pair automatic preparation remains integration work."
    base["modules"][0]["detail"]="Selected original HDL–CAD MR row and CETP atlas annotation."
    configs=[
      ("torcetrapib","NCT00134264","torce_trial","pfizer","2006-12-02",
       "Development discontinued","Safety stop announced by Pfizer after excess deaths and cardiovascular events.",
       [
        event("human-genetics","1989-11-23","day","Human genetics","Inherited CETP deficiency","A CETP splice-site mutation was linked to CETP deficiency and markedly higher HDL in a family.",["cetp_deficiency"],"Human genetic effect on CETP and HDL; not coronary-outcome evidence","human_genetics"),
        event("preclinical-antisense","1998-02-27","day","Preclinical evidence","Target suppression lowers lesions","Suppressing CETP reduced atherosclerotic lesions in cholesterol-fed rabbits.",["cetp_antisense"],"Target-level animal evidence; not torcetrapib-specific","preclinical"),
        event("preclinical-inhibitor","2000-07-13","day","Preclinical evidence","A CETP inhibitor helps rabbits","A different CETP inhibitor improved lipids and attenuated atherosclerosis in rabbits.",["cetp_inhibitor_rabbit"],"Target-class animal evidence; not torcetrapib-specific","preclinical"),
        event("phase1","2004-03","month","Phase 1 publication","Torcetrapib raises HDL","A short multidose study showed that torcetrapib inhibited CETP and raised HDL in healthy participants.",["torce_phase1"],"Compound-specific early human evidence; publication month","clinical"),
        event("trial-start","2004-07","month","Phase 3 trial","ILLUMINATE begins","Trial of torcetrapib plus atorvastatin versus atorvastatin in a coronary-risk population.",["torce_trial"],"Trial record; start date has month precision","clinical"),
        event("programme-stop","2006-12-02","day","Safety failure","Development stopped","Pfizer announced termination of ILLUMINATE and the compound's development after a mortality and cardiovascular-event imbalance.",["pfizer"],"Drug-specific safety / programme decision","clinical"),
        event("results","2007-11-05","day","Trial results","Higher HDL, more harm","Published trial results showed improved lipid levels alongside higher mortality and cardiovascular morbidity.",["torce_paper"],"Specific drug and trial population","clinical"),
        event("genetic-comparison","2009-12-21","day","Later genetic interpretation","Target or drug effect?","CETP genetic variants resembled the drug's lipid effects but not its blood-pressure rise, supporting an off-target explanation of that effect.",["offtarget"],"Retrospective target-versus-drug comparison","later_genetics"),
        event("hdl-mr","2012-05-17","day","Later metabolite MR","HDL assumption questioned","Some genetic mechanisms raising HDL did not lower heart-attack risk. This challenges HDL elevation as a sufficient rationale; it is not a CETP-specific negative result.",["hdl_mr"],"Related later evidence; not a 2006 prediction","later_genetics"),
        event("anacetrapib-outcome","2017-08-29","day","Class outcome","Another CETP drug shows benefit","REVEAL found fewer major coronary events with anacetrapib, showing that torcetrapib's failure did not invalidate the whole target class.",["reveal"],"Different compound; necessary counterevidence","class_status"),
        event("obicetrapib-status","2026-01-09","day","Current class status","CETP development continues","A sponsor update described continued obicetrapib development; this is not a completed cardiovascular-outcome result.",["prevail","sponsor2026"],"Different compound; dated programme status","class_status"),
       ]),
      ("evacetrapib","NCT01687998","evace_trial","lilly","2015-10-12",
       "Development discontinued","Lilly discontinued the high-risk ASCVD programme for insufficient efficacy, not a stated safety finding.",
       [
        event("human-genetics","1989-11-23","day","Human genetics","Inherited CETP deficiency","A CETP splice-site mutation was linked to CETP deficiency and markedly higher HDL in a family.",["cetp_deficiency"],"Human genetic effect on CETP and HDL; not coronary-outcome evidence","human_genetics"),
        event("preclinical-antisense","1998-02-27","day","Preclinical evidence","Target suppression lowers lesions","Suppressing CETP reduced atherosclerotic lesions in cholesterol-fed rabbits.",["cetp_antisense"],"Target-level animal evidence; not evacetrapib-specific","preclinical"),
        event("preclinical-inhibitor","2000-07-13","day","Preclinical evidence","A CETP inhibitor helps rabbits","A different CETP inhibitor improved lipids and attenuated atherosclerosis in rabbits.",["cetp_inhibitor_rabbit"],"Target-class animal evidence; not evacetrapib-specific","preclinical"),
        event("hdl-mr","2012-05-17","day","Metabolite-level MR","HDL assumption questioned","HDL-raising genetic mechanisms did not uniformly reduce heart-attack risk; this evidence preceded the trial start.",["hdl_mr"],"Related metabolite evidence; not a target-specific prediction","later_genetics"),
        event("trial-start","2012-10","month","Phase 3 trial","ACCELERATE begins","Evacetrapib, a CETP inhibitor, entered this large cardiovascular-outcomes study in high-risk vascular disease.",["evace_trial"],"Trial population is broader than CAD alone","clinical"),
        event("programme-stop","2015-10-12","day","Efficacy failure","Programme discontinued","The sponsor stopped the study and development for this indication because the emerging evidence suggested insufficient efficacy.",["lilly"],"Programme decision for high-risk ASCVD","clinical"),
        event("results","2017-05","month","Trial results","Marker gains, no benefit","Despite favorable lipid changes, evacetrapib did not reduce cardiovascular events in ACCELERATE.",["evace_paper"],"Trial-specific clinical outcome","clinical"),
        event("target-mr","2017-08-28","day","Target-level genetics","Look beyond HDL alone","CETP/HMGCR genetic analyses related cardiovascular risk changes to apoB changes, refining the target hypothesis.",["cetp_mr"],"Later target-specific context; not proof of why this trial failed","later_genetics"),
        event("anacetrapib-outcome","2017-08-29","day","Class outcome","Another CETP drug shows benefit","REVEAL found fewer major coronary events with anacetrapib, so one failed compound did not invalidate the target class.",["reveal"],"Different compound; necessary counterevidence","class_status"),
        event("obicetrapib-status","2026-01-09","day","Current class status","CETP development continues","A sponsor update described continued obicetrapib development; this is not a completed cardiovascular-outcome result.",["prevail","sponsor2026"],"Different compound; dated programme status","class_status"),
       ])
    ]
    for drug,nct,trial_ref,programme_ref,decision,title,description,events in configs:
        b=copy.deepcopy(base)
        receipt=read(nct+".json"); t=receipt["data"]["protocolSection"];st=t["statusModule"]
        b["snapshot_id"]="mvp1-cetp-"+drug+"-2026-09-12-v2"
        b["checked_at"]=receipt["retrieved_at"][:10]
        b["timeline_title"]="CETP · "+drug.capitalize()+" — coronary / cardiovascular outcomes"
        b["events"]=events
        b["current_status"]={
            "trial_id":nct,"trial_phase":", ".join(t["designModule"]["phases"]),
            "trial_status":st["overallStatus"],"trial_updated_at":st["lastUpdatePostDateStruct"]["date"],
            "trial_description":t["identificationModule"]["briefTitle"],
            "regulatory":description,"label_effective_at":decision,
            "programme_status":"Latest programme decision retrieved for this example; no exhaustive global revival/approval search.",
            "source_ids":[trial_ref,programme_ref],
            "context_label":"Programme outcome","context_title":title,"context_date_label":"Sponsor decision",
        }
        path=HERE/"snapshots"/(b["snapshot_id"]+".json")
        payload=json.dumps(b,ensure_ascii=False,indent=2)+"\n"
        if path.exists() and path.read_text(encoding="utf-8")!=payload:
            raise SystemExit("Snapshot differs; version it instead of overwriting: "+str(path))
        path.write_text(payload,encoding="utf-8")
        print(path.name)
    print("Baseline record",selected["line"],"triple record",triple["line"])

if __name__=="__main__": main()
