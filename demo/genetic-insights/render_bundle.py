"""Render one versioned evidence bundle to portable HTML, Markdown and Slack payloads.
Standard library only; rendering makes no network or model calls.
"""
import argparse
import sys
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
from datetime import date
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent

# L3. A required stage being PRESENT as a label is not evidence that the label is
# correct, and neither is the date it carries: evidence stages genuinely overlap in time
# (human-genetics findings keep accumulating after preclinical work starts, and both
# shipped recordings contain such an overlap), so a no-overlap date rule forbids the
# ordinary case rather than the mislabelled one. What binds a label to the rows behind it
# is the event's own `type` and `scope` - the two fields that say what the evidence IS.
#
# This is a phrase heuristic, in the sense validate_card.py uses for its own language
# rules, and must be described as one: it catches an event filed under a stage nothing in
# its own description supports, and a determined rewording of `type`/`scope` gets past it.
# It is not a proof. It runs over every stage the standard declares in `display_order`,
# required or not, because a relabelled event does not become honest by being moved to an
# optional stage.
STAGE_EVIDENCE_TERMS = {
    "human_genetics": (
        "human genetic", "genetic effect", "genetic association", "gwas",
        "mendelian randomi", "inherited", "carrier", "deficiency",
    ),
    "preclinical": (
        "preclinical", "pre-clinical", "animal", "in vitro", "in vivo", "cell line",
        "mouse", "mice", "rabbit", "rodent", "knockout",
    ),
    "clinical": (
        "clinical", "phase", "trial", "registry", "safety failure", "efficacy failure",
        "programme decision", "program decision", "approval", "label", "regulatory",
        "publication", "results",
    ),
    "later_genetics": (
        "later genetic", "later metabolite", "metabolite-level mr", "metabolite level mr",
        "target-level genetics", "target level genetics", "genetic interpretation",
        "retrospective", "mendelian randomi",
    ),
    "class_status": (
        "class", "programme status", "program status", "current status",
    ),
}


def event_evidence_text(event):
    """The rows behind one event's stage label, as one lower-case string."""
    return " ".join(str(event.get(key, "") or "") for key in ("type", "scope", "title")).casefold()


def known_stages(bundle):
    """The stages this bundle's own lifecycle standard declares."""
    standard = bundle.get("timeline_standard") or {}
    return list(standard.get("display_order") or standard.get("required_stages") or [])


def stage_is_outside_standard(bundle, event):
    """True when this event's stage is not one the bundle's standard declares.

    L2. The viewer, the Markdown report and the Slack message all ask this one question,
    so all three say the same thing about the same event instead of one of them hiding it.
    """
    declared = known_stages(bundle)
    if not declared:
        return False
    return (event.get("evidence_stage") or "unspecified") not in declared


def stage_label(bundle, event):
    """One event's stage, spelled for a reader, marked when it is outside the standard."""
    stage = str(event.get("evidence_stage") or "unspecified").replace("_", " ")
    if stage_is_outside_standard(bundle, event):
        return stage + " (outside this bundle's lifecycle standard)"
    return stage


def validate_bundle(bundle):
    if bundle.get("schema_version") != "1.0":
        raise ValueError("Unsupported schema_version")
    for key in ("snapshot_id", "checked_at", "mode", "headline", "summary", "relationship_note"):
        if not isinstance(bundle.get(key), str) or not bundle[key].strip():
            raise ValueError("Missing text: " + key)
    date.fromisoformat(bundle["checked_at"])
    for key in ("metabolite", "gene", "disease", "exposure_id", "outcome_dataset_id"):
        if not isinstance(bundle.get("pair", {}).get(key), str):
            raise ValueError("Missing pair field: " + key)
    sources = bundle.get("sources", [])
    if not sources or len({s["id"] for s in sources}) != len(sources):
        raise ValueError("Sources must have unique IDs")
    source_ids = {s["id"] for s in sources}
    for s in sources:
        parsed = urlparse(s["url"])
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            raise ValueError("Source link must use HTTP(S)")
        for key in ("title","location","note"):
            if not isinstance(s.get(key), str):
                raise ValueError("Missing source " + key)
    event_dates = {}
    for collection in ("sections", "events"):
        records = bundle.get(collection, [])
        if not records or len({x["id"] for x in records}) != len(records):
            raise ValueError(collection + " must have unique IDs")
        for item in records:
            if not item.get("source_ids") or not set(item["source_ids"]) <= source_ids:
                raise ValueError("Missing or dangling source reference")
            if not item.get("title"):
                raise ValueError("Missing title")
            if collection == "events":
                precision = item["precision"]
                value = item["date"]
                if precision == "day":
                    event_dates[item["id"]] = date.fromisoformat(value)
                elif precision == "month":
                    if len(value) != 7: raise ValueError("Invalid month")
                    event_dates[item["id"]] = date.fromisoformat(value + "-01")
                elif precision == "year":
                    if len(value) != 4: raise ValueError("Invalid year")
                    event_dates[item["id"]] = date.fromisoformat(value + "-01-01")
                else:
                    raise ValueError("Unsupported date precision")
                for key in ("type","description","scope"):
                    if not isinstance(item.get(key), str): raise ValueError("Missing event " + key)
            elif not isinstance(item.get("text"), str):
                raise ValueError("Missing section text")
    # L6 fix: compare the dates events were parsed into (day/month/year, ISO extended or
    # ISO basic), never the raw date strings, so a basic-format date cannot sort out of
    # place against an extended-format one.
    if [event_dates[e["id"]] for e in bundle["events"]] != sorted(event_dates[e["id"]] for e in bundle["events"]):
        raise ValueError("Events must be chronological")
    standard = bundle.get("timeline_standard")
    if standard:
        required = standard.get("required_stages", [])
        # L3/LC05: a standard that requires nothing verifies nothing, and the viewer still
        # prints its note as if a guarantee had been checked. A standard has to assert
        # something before a bundle may be presented as meeting one.
        if not required:
            raise ValueError(
                "timeline_standard declares no required_stages: a standard that requires "
                "nothing checks nothing and must not be presented as a lifecycle standard"
            )
        present = {e.get("evidence_stage") for e in bundle["events"]}
        missing = [stage for stage in required if stage not in present]
        if missing:
            raise ValueError("Timeline silently omits required stages: " + ", ".join(missing))
        if any(not e.get("evidence_stage") for e in bundle["events"]):
            raise ValueError("Every event needs evidence_stage under the lifecycle standard")
        # L3: bind each stage label to the event rows behind it (see STAGE_EVIDENCE_TERMS).
        # Every stage the standard declares is walked, not only the required ones, and the
        # date order is deliberately NOT part of this: evidence stages overlap in time and
        # a no-overlap rule would reject truthful bundles while accusing their author of
        # mislabelling.
        declared = known_stages(bundle)
        for e in bundle["events"]:
            stage = e["evidence_stage"]
            if stage not in declared:
                continue
            terms = STAGE_EVIDENCE_TERMS.get(stage)
            if terms is None:
                raise ValueError(
                    "Lifecycle standard declares stage '" + stage + "' with no evidence "
                    "vocabulary; its labels cannot be checked against their own evidence"
                )
            evidence = event_evidence_text(e)
            if not any(term in evidence for term in terms):
                raise ValueError(
                    "Stage label is not supported by the event's own evidence: event '"
                    + str(e["id"]) + "' is filed under '" + stage + "', and its type ('"
                    + str(e.get("type", "")) + "') and scope ('" + str(e.get("scope", ""))
                    + "') carry none of that stage's evidence vocabulary: "
                    + ", ".join(terms)
                )
    for m in bundle["modules"]:
        for key in ("name","status","detail"):
            if not isinstance(m.get(key), str): raise ValueError("Missing module " + key)
    st = bundle["current_status"]
    for key in ("trial_id","trial_phase","trial_status","trial_updated_at","trial_description","regulatory","label_effective_at","programme_status"):
        if not isinstance(st.get(key), str): raise ValueError("Missing current status " + key)
    if not set(st["source_ids"]) <= source_ids: raise ValueError("Dangling status reference")
    if not isinstance(bundle.get("legacy_report", {}).get("text"), str):
        raise ValueError("Missing archived report text (an empty string is permitted)")


def summary_markdown(b):
    pair = b["pair"]
    lines = [f"# MetaboCausal — {pair['metabolite']} · {pair['gene']} · {pair['disease']}",
             f"\nSnapshot: {b['snapshot_id']} | Checked: {b['checked_at']}", b["mode"], "", b["summary"]]
    refs = {s["id"]:s for s in b["sources"]}
    def citations(ids):
        return " · ".join(f"[{refs[i]['title']}]({refs[i]['url']})" for i in ids)
    for s in b["sections"]:
        lines += ["", "## " + s["title"], "", s["text"], "", citations(s["source_ids"])]
    lines += ["", "## Genetic Insights", "", b["relationship_note"]]
    for e in b["events"]:
        stage = stage_label(b, e)
        lines += ["", f"### {e['date']} — {e['title']}", f"{stage} | {e['type']} | {e['scope']}", e["description"], citations(e["source_ids"])]
    st = b["current_status"]
    lines += ["", "## Latest retrieved status", "",
              f"{st['trial_id']}: {st['trial_phase']} — {st['trial_status']}",
              st["trial_description"],
              f"Registry last updated: {st['trial_updated_at']}; checked: {b['checked_at']}.",
              st["regulatory"], f"{st.get('context_date_label', 'Retrieved label effective')}: {st['label_effective_at']}.",
              st["programme_status"], citations(st["source_ids"]),
              "", "## Module status"]
    for m in b["modules"]:
        lines += [f"- {m['name']}: {m['status']}. {m['detail']}"]
    lines += ["", "## Sources"]
    for s in b["sources"]:
        lines += [f"- [{s['title']}]({s['url']}) — {s['location']}. {s['note']}"]
    lines += ["", "## Snapshot boundaries", b["provenance"]["preparation"], b["legacy_report"]["note"]]
    return "\n".join(lines) + "\n"


def slack_payloads(b):
    """Complete text in bounded messages. No truncation of evidence or source links."""
    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    src = {s["id"]:s for s in b["sources"]}
    def refs(ids):
        return "\n".join(f"<{src[i]['url']}|{esc(src[i]['title'])}>" for i in ids)
    p=b["pair"]; st=b["current_status"]
    parts=[f"*MetaboCausal | {esc(p['metabolite'])} · {esc(p['gene'])} · {esc(p['disease'])}*\n"
           f"{esc(b['snapshot_id'])} | Checked {esc(b['checked_at'])}\n{esc(b['mode'])}\n{esc(b['summary'])}"]
    parts += [f"*{esc(s['title'])}*\n{esc(s['text'])}\n{refs(s['source_ids'])}" for s in b["sections"]]
    parts += [f"*Genetic Insights*\n{esc(b['relationship_note'])}"]
    parts += [f"*{esc(e['date'])} — {esc(e['title'])}*\n{esc(stage_label(b, e))} | {esc(e['type'])} | {esc(e['scope'])}\n{esc(e['description'])}\n{refs(e['source_ids'])}" for e in b["events"]]
    parts += [f"*Latest retrieved status*\n{esc(st['trial_id'])}: {esc(st['trial_phase'])} · {esc(st['trial_status'])}\n"
              f"{esc(st['trial_description'])}\nRegistry updated {esc(st['trial_updated_at'])}; checked {esc(b['checked_at'])}.\n"
              f"{esc(st['regulatory'])}\n{esc(st.get('context_date_label', 'Label effective'))} {esc(st['label_effective_at'])}.\n{esc(st['programme_status'])}\n{refs(st['source_ids'])}"]
    parts += [f"*Module status*\n" + "\n".join(f"{esc(m['name'])}: {esc(m['status'])}. {esc(m['detail'])}" for m in b["modules"])]
    parts += [f"*Source detail: {esc(s['title'])}*\n{esc(s['location'])}\n{esc(s['note'])}\n<{s['url']}|Open source>" for s in b["sources"]]
    parts += [f"*Snapshot boundaries*\n{esc(b['provenance']['preparation'])}\n{esc(b['legacy_report']['note'])}"]
    blocks=[]
    for part in parts:
        # Plain text fallback is never silently truncated; huge sections need editorial splitting.
        if len(part)>2900: raise ValueError("Slack section exceeds limit; split this section in the bundle.")
        blocks.append({"type":"section","text":{"type":"mrkdwn","text":part}})
    messages=[]
    for offset in range(0,len(blocks),8):
        batch=blocks[offset:offset+8]
        messages.append({"text":"\n\n".join(x["text"]["text"] for x in batch),
                         "blocks":batch,"unfurl_links":False,"unfurl_media":False})
    return messages


def render(bundle_path, out_dir):
    b=json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    validate_bundle(b)
    encoded=json.dumps(b,ensure_ascii=False,indent=2)
    safe=encoded.replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
    template=(HERE/"viewer.template.html").read_text(encoding="utf-8")
    html=template.replace("__BUNDLE_JSON__",safe)
    payloads=slack_payloads(b)
    artifacts={
        "index.html":html,
        "bundle.json":encoded+"\n",
        "evidence-summary.md":summary_markdown(b),
        "full-mvp1-report.md":b["legacy_report"]["text"],
        "slack-messages.json":json.dumps(payloads,ensure_ascii=False,indent=2)+"\n",
        "slack-text.txt":"\n\n--- NEXT MESSAGE ---\n\n".join(m["text"] for m in payloads)+"\n",
    }
    artifacts["manifest.json"]=json.dumps({
        "snapshot_id":b["snapshot_id"],
        "bundle_sha256":hashlib.sha256(Path(bundle_path).read_bytes()).hexdigest(),
        "renderer_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "template_sha256":hashlib.sha256((HERE/"viewer.template.html").read_bytes()).hexdigest(),
        "files":{name:hashlib.sha256(body.encode("utf-8")).hexdigest() for name,body in artifacts.items()},
        "network_calls":0,"llm_calls":0,"slack_delivery":"not attempted"
    },indent=2)+"\n"
    out_dir=Path(out_dir)
    for name, body in artifacts.items():
        path=out_dir/name
        if path.exists() and path.read_text(encoding="utf-8")!=body:
            raise ValueError(f"{path} differs. Choose a new --out folder to preserve the recording version.")
    out_dir.mkdir(parents=True,exist_ok=True)
    for name, body in artifacts.items(): (out_dir/name).write_text(body,encoding="utf-8",newline="\n")
    print(out_dir/"index.html")
    return artifacts


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--bundle",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    render(args.bundle,args.out)
