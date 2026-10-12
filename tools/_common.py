"""Shared plumbing for every MetaboCausal tool: one envelope, one HTTP path, one
string rule.

Nothing here knows about a particular database. Tools import `envelope()` so every
return value has the same eight keys, `get_json()` so every request has the same
timeout and retry behaviour, and `normalize()` so every string comparison in the
project follows a single, written-down rule.

Leading underscore = internal module, not a tool. It is never registered in TOOLS.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# The only three values `status` may take. Anything else is a bug in the caller.
STATUSES = ("ok", "empty", "error")

ENV_FILENAME = ".env"

TIMEOUT_SECONDS = 30
RETRY_BACKOFF_SECONDS = 1.5
# 429 = rate limited, 5xx = the server is having a moment. Both are worth exactly one
# more try; a 4xx that is not 429 means the request itself is wrong and retrying it
# would just be slower.
RETRY_STATUS_CODES = (429, 500, 502, 503, 504)

_ERROR_BODY_CHARS = 300

_SESSION = requests.Session()


class RequestFailed(Exception):
    """The single exception `get_json` raises, after its retries are spent.

    Tool functions catch this (plus a final `except Exception`) and turn it into an
    error envelope. No exception ever leaves a tool.
    """

    def __init__(
        self,
        message:     str,
        status_code: int | None = None,
        url:         str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.url = url


def load_env() -> None:
    """Copy `KEY=VALUE` lines out of any `.env` above this file into `os.environ`.

    python-dotenv is not installed and the real .env sits two levels ABOVE the repo
    root, so this walks `Path(__file__).parents` from nearest to farthest and applies
    every .env it finds with `os.environ.setdefault`: a variable already exported in
    the real environment always wins, and a nearer .env wins over a farther one.
    Blank lines, `#` comments and a leading `export ` are skipped; one pair of matching
    surrounding quotes is stripped.

    Idempotent, and silent when there is no .env anywhere - it never raises, so an
    absent key surfaces where it belongs, as a clean error envelope in the tool that
    needed it, not as a crash at import time. Nothing here prints or logs a value.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ENV_FILENAME
        try:
            if not candidate.is_file():
                continue
            text = candidate.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue

        for line in text.splitlines():
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            if entry.startswith("export "):
                entry = entry[len("export "):].strip()

            key, separator, value = entry.partition("=")
            key = key.strip()
            if not separator or not key:
                continue

            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)


def normalize(s) -> str:
    """Fold a display string to the form used for every exact match in this project:
    casefolded, whitespace collapsed. `" Coronary  Artery Disease "` ->
    `"coronary artery disease"`. Nothing else - no stemming, no punctuation stripping,
    no invented variants."""
    if not s:
        return ""
    return " ".join(str(s).casefold().split())


def underscore_ontology_id(value) -> str:
    """Fold an ontology id to the underscore form the 1E tools send to Open Targets:
    `"MONDO:0005010"` -> `"MONDO_0005010"`. A value already in underscore form comes
    back unchanged, and None or a blank value becomes `""`. Nothing else - no case
    change, no prefix guessing, no check that the id exists."""
    if not value:
        return ""
    return str(value).strip().replace(":", "_")


def envelope(
    tool:    str,
    args:    dict,
    source:  str,
    url:     str,
    status:  str,
    data:    dict,
    caveats: list,
) -> dict:
    """Build the shared return envelope. Exactly eight top-level keys, no others.

    `status` is one of ok / empty / error. `url` is the primary request URL actually
    sent (multi-call tools put every URL in `data["queries"]`). `retrieved_at` is
    filled here so no tool has to remember the format.

    ONE LEDGER, ONE CLOCK. This was a naive local timestamp while `tools/_evidence.py`
    (1E) stamps aware UTC, so at UTC-4 the two halves of a single run read as 23:11 on
    the 10th and 03:11 on the 11th in the same file. Anything that sorts, diffs or
    prints "retrieved on" was comparing two clocks. Aware UTC here matches 1E without
    touching 1E's files.
    """
    if caveats is None:
        caveats = []
    elif isinstance(caveats, str):
        caveats = [caveats]

    return {
        "tool":         tool,
        "args":         args,
        "source":       source,
        "url":          url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status":       status,
        "data":         data,
        "caveats":      list(caveats),
    }


def get_json(
    url,
    *,
    params    = None,
    headers   = None,
    method    = "GET",
    json_body = None,
    timeout   = TIMEOUT_SECONDS,
    retries   = 1,
):
    """Send one JSON request and return `(payload, final_url)`.

    `final_url` is the fully built URL including the query string, so a tool can put
    the URL it actually sent into its envelope even when the call failed. Timeouts,
    429 and 5xx get `retries` more attempts with a short backoff; everything else
    fails immediately. Raises `RequestFailed` - callers wrap it.
    """
    request = requests.Request(
        method  = str(method).upper(),
        url     = url,
        params  = params,
        headers = {"Accept": "application/json", **(headers or {})},
        json    = json_body,
    )
    prepared = _SESSION.prepare_request(request)
    final_url = prepared.url

    # Session.send() skips merge_environment_settings, so REQUESTS_CA_BUNDLE /
    # CURL_CA_BUNDLE / proxy env vars would be ignored - fatal behind a TLS-intercepting
    # corporate proxy, where that variable is the only way in.
    environment = _SESSION.merge_environment_settings(
        prepared.url,
        {},
        None,
        None,
        None,
    )

    attempts = max(1, int(retries) + 1)
    for attempt in range(attempts):
        is_last = attempt == attempts - 1
        try:
            response = _SESSION.send(
                prepared,
                timeout = timeout,
                **environment,
            )
        except requests.Timeout as exc:
            if is_last:
                raise RequestFailed(
                    f"{prepared.method} {final_url} timed out after {timeout}s "
                    f"({attempts} attempt(s))",
                    url = final_url,
                ) from exc
            time.sleep(RETRY_BACKOFF_SECONDS)
            continue
        except requests.RequestException as exc:
            raise RequestFailed(
                f"{prepared.method} {final_url} failed: {exc}",
                url = final_url,
            ) from exc

        if response.status_code in RETRY_STATUS_CODES and not is_last:
            time.sleep(RETRY_BACKOFF_SECONDS)
            continue

        if response.status_code >= 400:
            body = response.text or ""
            detail = body[:_ERROR_BODY_CHARS]
            if len(body) > _ERROR_BODY_CHARS:
                detail += " ...[error body truncated]"
            raise RequestFailed(
                f"HTTP {response.status_code} from {final_url}: {detail}",
                status_code = response.status_code,
                url         = final_url,
            )

        try:
            return response.json(), final_url
        except ValueError as exc:
            raise RequestFailed(
                f"{final_url} returned non-JSON: {exc}",
                status_code = response.status_code,
                url         = final_url,
            ) from exc

    raise RequestFailed(f"{final_url} exhausted {attempts} attempt(s)", url=final_url)


if __name__ == "__main__":
    import json

    load_env()
    load_env()                                         # idempotent: same result twice
    # Length only. The value of a key is never printed, logged or written anywhere.
    for name in ("OPENGWAS_JWT", "GEMINI_API_KEY"):
        value = os.environ.get(name)
        print(f"load_env: {name} {'present (%d chars)' % len(value) if value else 'ABSENT'}")

    print("normalize:", repr(normalize("  Coronary   ARTERY  disease ")))
    print("normalize:", repr(normalize(None)))

    env = envelope(
        tool    = "_selftest",
        args    = {"exposure_trait": "Urate", "outcome_trait": "Gout"},
        source  = "EpiGraphDB MR-EVE",
        url     = "https://api.epigraphdb.org/mr",
        status  = "ok",
        data    = {"n_estimates": 0},
        caveats = "Retrieved, not computed here.",
    )
    print("envelope keys:", list(env))
    print(json.dumps(
        env,
        indent       = 2,
        ensure_ascii = False,
    ))

    try:
        payload, sent_url = get_json(
            "https://api.epigraphdb.org/mr",
            params  = {"exposure_trait": "Urate", "outcome_trait": "Gout", "pval_threshold": 1},
            timeout = 30,
        )
        print("live GET ok:", sent_url)
        print("rows:", len(payload.get("results", [])))
    except RequestFailed as exc:
        print("live GET failed (this is the error-envelope path)")
        print("  status:", exc.status_code)
        print("  message:", exc.message)
