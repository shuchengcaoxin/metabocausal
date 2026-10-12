"""Optional sender for Zhang Hao's existing Slack client. Importing sends nothing.
Caller owns access checks, pair matching, acknowledgement, job claiming and retries.
"""
import json
from pathlib import Path


def send_recording_snapshot(client, *, channel, thread_ts, artifact_dir):
    """Explicit call only, in the authorized originating thread; never broadcasts.
    Returns per-operation diagnostics. Does not automatically retry ambiguous sends.
    """
    if not channel or not thread_ts:
        raise ValueError("The originating channel and thread_ts are required.")
    folder=Path(artifact_dir)
    payloads=json.loads((folder/"slack-messages.json").read_text(encoding="utf-8"))
    diagnostics=[]
    for i,payload in enumerate(payloads):
        try:
            response=client.chat_postMessage(channel=channel,thread_ts=thread_ts,**payload)
            diagnostics.append({"kind":"message","index":i,"status":"sent","ts":response.get("ts")})
        except Exception as exc:
            diagnostics.append({"kind":"message","index":i,"status":"failed","error_type":type(exc).__name__})
            # Delivery may be ambiguous. Let the owner check receipt before retrying.
            break
    for name in ("timeline.png","evidence-summary.md","full-mvp1-report.md","bundle.json","index.html"):
        path=folder/name
        if not path.exists():
            diagnostics.append({"kind":"file","name":name,"status":"not_available"})
            continue
        try:
            client.files_upload_v2(channel=channel,thread_ts=thread_ts,file=str(path),
                                   filename=name,title="MetaboCausal saved example — "+name)
            diagnostics.append({"kind":"file","name":name,"status":"sent"})
        except Exception as exc:
            diagnostics.append({"kind":"file","name":name,"status":"failed","error_type":type(exc).__name__})
    return diagnostics
