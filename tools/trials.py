"""When did a trial actually happen? ClinicalTrials.gov's own dates, for the reports 1E
already retrieved.

Open Targets' `clinicalReports` carries the phase, the status and the stopping reason of
every trial report - and `year: null` on every single one of them. Verified against
PCSK9 on 2026-09-11: 19 reports on BOCOCIZUMAB alone, all with a null year, while the
report id is `nct01968967` and the url is the ClinicalTrials.gov study page. The year is
one request away and nowhere in the payload, so anything that wants a timeline has to go
and get it. This module is that request and nothing more.

It exists for the genetic-insight timeline: a lane per drug, x = year, against the year
the exposure GWAS was published. "Genetics said it in 2020, the clinic decided in 2016"
is only a sentence anybody may write if both years are retrieved. A year this registry
does not carry is absent here, is counted, and is never inferred from a neighbouring
field.

NOT A REGISTERED TOOL. Like `get_mr_outcomes`, this is plumbing the surfaces call, not a
tool the model may fire while assembling a card: it answers a question about a record the
card already holds, and a model that could call it would be able to spend an unbounded
number of requests on one figure.

    from tools.trials import get_trial_dates
    env = get_trial_dates(["NCT01968967", "nct01968980"])
    env["data"]["dates"]["NCT01968967"]["start_year"]                  # 2013
    env["data"]["dates"]["NCT01968967"]["primary_completion_year"]     # 2016

CACHE. Every resolved record is appended to data/nct_dates_cache.json, keyed by NCT id.
A cached id costs no request and no delay, so re-drawing the same timeline is free and
the demo does not depend on the registry being up twice. The cache is re-read immediately
before it is written, so two runs finishing at once merge instead of overwriting; a
cache file that cannot be read or written is a degradation written into the caveats, not
a failure - the dates were still retrieved.

ACTUAL vs ESTIMATED. The registry labels each date `ACTUAL` or `ESTIMATED`; an estimated
completion date is the sponsor's projection, not a milestone that happened. Both the date
and its type come back, so a figure can mark the difference instead of drawing a
projection as history.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from . import _common
except ImportError:                                    # running: python tools/trials.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _common

STUDY_URL = "https://clinicaltrials.gov/api/v2/studies/{nct_id}"
SOURCE = "ClinicalTrials.gov API v2 (studies)"

CACHE_PATH = REPO_ROOT / "data" / "nct_dates_cache.json"

# The registry is a public service with no key; a quarter second between calls keeps a
# twelve-trial timeline polite and still finishes inside three seconds.
SLEEP_SECONDS = 0.25

DEFAULT_CAP = 12

# NCT ids are the literal registry format: NCT + 8 digits. Open Targets lower-cases them
# in `report_id` ("nct01968967") and keeps the canonical form in the url, so both are
# folded to upper case here and anything else is dropped rather than guessed at.
_NCT = re.compile(r"NCT\d{8}")

_DATE_FIELDS = (
    ("start",              "startDateStruct"),
    ("primary_completion", "primaryCompletionDateStruct"),
    ("completion",         "completionDateStruct"),
)

RETRIEVED_CAVEAT = (
    "Dates are the ClinicalTrials.gov record's own start / primary completion / "
    "completion dates, retrieved per trial. A date the registry does not carry is absent "
    "here and is never inferred."
)
ESTIMATED_CAVEAT = (
    "Each date carries the registry's own ACTUAL / ESTIMATED type. An ESTIMATED date is "
    "the sponsor's projection, not a milestone that happened."
)
CAP_CAVEAT = (
    "{total} NCT id(s) were given; the first {cap} were requested. The rest were not "
    "looked up, which is a cap on this call and not an absence of records."
)
CACHE_HIT_CAVEAT = (
    "{hits} of {total} record(s) came from data/nct_dates_cache.json and were not "
    "re-requested; each cached record carries the date it was retrieved."
)
CACHE_READ_CAVEAT = (
    "The date cache could not be read ({detail}), so every id was requested fresh."
)
CACHE_WRITE_CAVEAT = (
    "The date cache could not be written ({detail}); the dates above are unaffected, but "
    "the next run will request them again."
)
FAILED_CAVEAT = (
    "{failed} trial record(s) could not be retrieved ({ids}). Treat those as no "
    "information, not as trials without dates."
)
NO_ID_CAVEAT = (
    "No usable NCT id was given (an id must be the registry's NCT + 8 digits), so nothing "
    "was requested."
)
NO_DATE_CAVEAT = (
    "{undated} retrieved record(s) carry no date at all in the registry. They are counted "
    "here and must be shown as undated rather than placed on a year."
)


def normalize_nct_ids(values) -> list:
    """Every NCT id in `values`, upper-cased and de-duplicated, order preserved.

    Accepts whatever 1E hands over: a bare id, a lower-cased `report_id`, a
    ClinicalTrials.gov url, or a report dict with either. Anything with no NCT id in it
    contributes nothing - the id is never reconstructed from a neighbouring field.
    """
    out, seen = [], set()
    for value in values or []:
        if isinstance(value, dict):
            text = " ".join(
                str(value.get(key) or "")
                for key in ("report_id", "url", "nct_id", "id")
            )
        else:
            text = str(value or "")
        for found in _NCT.findall(text.upper()):
            if found not in seen:
                seen.add(found)
                out.append(found)
    return out


def _year(value):
    """The four-digit year of a registry date string ("2013-10-29", "2016-07"), or None.

    None means the registry did not give a parsable date. It never means "this year".
    """
    text = str(value or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def load_cache(path: Path | None = None) -> tuple:
    """`(cache, caveats)`. An unreadable or non-dict cache is an empty cache plus a
    caveat - it costs requests, it does not end the call."""
    try:
        with Path(CACHE_PATH if path is None else path).open(encoding="utf-8") as handle:
            loaded = json.load(handle)
    except FileNotFoundError:
        return {}, []
    except (OSError, ValueError) as exc:
        return {}, [CACHE_READ_CAVEAT.format(detail=f"{type(exc).__name__}: {exc}")]
    if not isinstance(loaded, dict):
        return {}, [CACHE_READ_CAVEAT.format(detail="the file is not a JSON object")]
    return {key: value for key, value in loaded.items() if isinstance(value, dict)}, []


def _save_cache(
    fetched: dict,
    path:    Path | None = None,
) -> list:
    """Merge `fetched` into the cache on disk and write it back. Re-reads first, so a
    concurrent run's records survive instead of being overwritten by this one's."""
    if not fetched:
        return []
    try:
        target = Path(CACHE_PATH if path is None else path)
        target.parent.mkdir(parents=True, exist_ok=True)
        on_disk, _ = load_cache(target)
        on_disk.update(fetched)
        target.write_text(
            json.dumps(
                dict(sorted(on_disk.items())),
                indent       = 1,
                ensure_ascii = False,
            ) + "\n",
            encoding = "utf-8",
        )
    except (OSError, ValueError, TypeError) as exc:
        return [CACHE_WRITE_CAVEAT.format(detail=f"{type(exc).__name__}: {exc}")]
    return []


def _record_from_payload(
    nct_id:  str,
    payload: dict,
) -> dict:
    """The few fields a timeline rests on, pulled out of one study payload."""
    protocol = payload.get("protocolSection") if isinstance(payload, dict) else None
    protocol = protocol if isinstance(protocol, dict) else {}
    status = protocol.get("statusModule")
    status = status if isinstance(status, dict) else {}
    identification = protocol.get("identificationModule")
    identification = identification if isinstance(identification, dict) else {}

    record = {
        "nct_id":        nct_id,
        "brief_title":   identification.get("briefTitle"),
        "overall_status": status.get("overallStatus"),
        "why_stopped":   status.get("whyStopped"),
        # The same aware-UTC clock _common.envelope stamps, so a cached record and the
        # envelope that carries it can be compared without converting between two clocks.
        "retrieved_at":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    for name, key in _DATE_FIELDS:
        block = status.get(key)
        block = block if isinstance(block, dict) else {}
        record[f"{name}_date"] = block.get("date")
        record[f"{name}_date_type"] = block.get("type")
        record[f"{name}_year"] = _year(block.get("date"))
    return record


def _has_year(record) -> bool:
    return any(record.get(f"{name}_year") is not None for name, _key in _DATE_FIELDS)


def get_trial_dates(
    nct_ids: list,
    cap:     int = DEFAULT_CAP,
) -> dict:
    """Retrieve the registry dates of the named ClinicalTrials.gov studies.

    `nct_ids` may be bare ids, Open Targets `report_id` strings, study urls, or the
    report dicts themselves; every NCT id found in them is requested once. At most `cap`
    ids are looked up and the cap is written into the caveats. Ids already in
    data/nct_dates_cache.json cost no request.

    Returns the shared eight-key envelope. `data["dates"]` maps NCT id to
    {start_date, start_date_type, start_year, primary_completion_*, completion_*,
    overall_status, why_stopped, brief_title, retrieved_at}; a year the registry does not
    carry is None and must stay None on any figure drawn from it. `status` is `ok` when
    at least one record came back, `empty` when no usable id was given or none resolved,
    `error` when every requested id failed.
    """
    requested = normalize_nct_ids(nct_ids)
    limit = max(0, int(cap or 0))
    wanted = requested[:limit]

    data = {
        "dates":         {},
        "n_requested":   len(requested),
        "n_looked_up":   len(wanted),
        "n_from_cache":  0,
        "n_fetched":     0,
        "n_failed":      0,
        "n_undated":     0,
        "cap":           limit,
        "failed":        {},
        "queries":       [],
    }
    caveats = [RETRIEVED_CAVEAT, ESTIMATED_CAVEAT]

    if len(requested) > len(wanted):
        caveats.append(CAP_CAVEAT.format(
            total = len(requested),
            cap   = limit,
        ))

    if not wanted:
        caveats.append(NO_ID_CAVEAT)
        return _common.envelope(
            tool    = "get_trial_dates",
            args    = {"nct_ids": requested[:25], "cap": limit},
            source  = SOURCE,
            url     = STUDY_URL.format(nct_id=""),
            status  = "empty",
            data    = data,
            caveats = caveats,
        )

    cache, cache_caveats = load_cache()
    caveats.extend(cache_caveats)

    fetched = {}
    first_url = ""
    sent_any = False
    for nct_id in wanted:
        cached = cache.get(nct_id)
        if isinstance(cached, dict) and cached.get("nct_id") == nct_id:
            data["dates"][nct_id] = cached
            data["n_from_cache"] += 1
            continue

        if sent_any:
            time.sleep(SLEEP_SECONDS)
        url = STUDY_URL.format(nct_id=nct_id)
        sent_any = True
        try:
            payload, sent_url = _common.get_json(
                url,
                timeout = 30,
            )
        except _common.RequestFailed as exc:
            data["failed"][nct_id] = exc.message
            data["n_failed"] += 1
            data["queries"].append(exc.url or url)
            first_url = first_url or (exc.url or url)
            continue
        except Exception as exc:                       # noqa: BLE001 - deliberate boundary
            data["failed"][nct_id] = f"{type(exc).__name__}: {exc}"
            data["n_failed"] += 1
            data["queries"].append(url)
            first_url = first_url or url
            continue

        data["queries"].append(sent_url)
        first_url = first_url or sent_url
        record = _record_from_payload(
            nct_id,
            payload,
        )
        data["dates"][nct_id] = record
        fetched[nct_id] = record
        data["n_fetched"] += 1

    caveats.extend(_save_cache(fetched))

    data["n_undated"] = sum(
        1 for record in data["dates"].values() if not _has_year(record)
    )

    if data["n_from_cache"]:
        caveats.append(CACHE_HIT_CAVEAT.format(
            hits  = data["n_from_cache"],
            total = len(wanted),
        ))
    if data["n_failed"]:
        caveats.append(FAILED_CAVEAT.format(
            failed = data["n_failed"],
            ids    = ", ".join(sorted(data["failed"])[:8]),
        ))
    if data["n_undated"]:
        caveats.append(NO_DATE_CAVEAT.format(undated=data["n_undated"]))

    if data["dates"]:
        status = "ok"
    elif data["n_failed"]:
        status = "error"
    else:
        status = "empty"

    return _common.envelope(
        tool    = "get_trial_dates",
        args    = {"nct_ids": requested[:25], "cap": limit},
        source  = SOURCE,
        url     = first_url or STUDY_URL.format(nct_id=wanted[0]),
        status  = status,
        data    = data,
        caveats = caveats,
    )


if __name__ == "__main__":
    _common.load_env()
    env = get_trial_dates(
        ["NCT01968967", "nct01968980", "https://clinicaltrials.gov/study/NCT02100514", "not-an-id"],
        cap = 12,
    )
    print(f"status={env['status']}  requested={env['data']['n_requested']} "
          f"cache={env['data']['n_from_cache']} fetched={env['data']['n_fetched']} "
          f"failed={env['data']['n_failed']} undated={env['data']['n_undated']}")
    for nct_id, record in env["data"]["dates"].items():
        print(f"  {nct_id}  start {record['start_date']} ({record['start_date_type']}) "
              f"-> primary completion {record['primary_completion_date']} "
              f"({record['primary_completion_date_type']})  years "
              f"{record['start_year']} / {record['primary_completion_year']} / "
              f"{record['completion_year']}  status {record['overall_status']}")
    for caveat in env["caveats"]:
        print("  caveat:", caveat)
