"""The Slack shell: mention the bot with a pair, get the card back in the same thread.

    @metabocausal urate vs gout
    @metabocausal is glycine causal for coronary artery disease
    @metabocausal "trimethylamine N-oxide" x CAD

Socket Mode, so no public URL and no ngrok: the process opens an outbound WebSocket to
Slack with an app-level token. Two tokens, both read from the .env two levels above the
repo through `_common.load_env`, both read by name only and never printed:

    SLACK_BOT_TOKEN   xoxb-...   OAuth & Permissions; scopes app_mentions:read,
                                 chat:write, files:write
    SLACK_APP_TOKEN   xapp-...   Basic Information -> App-Level Tokens, scope
                                 connections:write

This file is a SHELL. It parses a pair out of the mention text, hands the two names to
`pipeline.run_pair`, and turns the dict that comes back into a Block Kit summary. It
retrieves nothing itself, it decides no state, and there is no model call in it - the
A/B/C state comes from classify.py through pipeline.py, and every number on the card
comes from a tool envelope that is already on disk in the run's ledger.

THE GUIDED FLOW (interactivity is on in slack_manifest.yaml v3)

    mention        the pair is parsed and RESOLVED - the frozen 1A sample first, the live
                   1A resolver for a side the sample does not carry - and the menu goes
                   into the thread: one pre-ticked checkbox per evidence arm and a
                   "generate" button. Nothing is retrieved yet, so nobody waits 100 s for
                   a pair the bot misread; the menu says what it resolved to.
    generate       `run_pair` with the ticked arms, then the summary, the card and the
                   state figure, exactly as before. The retrieved-MR and instrument arms
                   cannot be switched off - the A/B/C state is a pure function of them, so
                   unticking one would produce a state with nothing behind it - and the
                   thread is told when a tick was overruled rather than quietly ignored.
    the buttons    a figure is drawn ON DEMAND: forest, instrument strength, or the
                   genetic-insight timeline. Each button generates once per thread; a
                   second click gets "already generated" instead of a second upload, and a
                   figure with nothing to draw replies WHY rather than posting an empty
                   axis.

The run of one thread is kept in `_THREAD_STATE`, capped at 32 threads and evicted oldest
first. It is memory, not truth: the ledger on disk is the record, and a button that finds
no run says so and asks for the mention again.

THREE THINGS GO INTO THE THREAD, IN THIS ORDER

    1. the Block Kit summary   header / bold verdict / a field per evidence arm /
                               a context footer. `format_card` still builds the
                               fallback `text`, so a client that cannot render blocks
                               and every notification preview still get the whole card
    2. cards/card_<stem>.md    the full 11-section card, rendered BY CODE by render.py
                               from this run's envelopes, uploaded with files_upload_v2
    3. cards/<stem>_*.png      one figure from plots.py: a forest of the retrieved MR
                               estimates (State A) or the instrument counts (State B).
                               State C draws nothing - there is nothing retrieved to
                               draw, which is a gap and not evidence of no effect

Steps 2 and 3 need the `files:write` scope. Until the app is reinstalled with it,
files_upload_v2 fails with `missing_scope`; the shell then posts one line saying the
attachments were skipped and WHY, and the summary still stands. An upload is never
allowed to cost a reader the numbers: no upload failure raises, none is retried, and
the .md and .png are on disk in cards/ either way.

WORDING DISCIPLINE, ENFORCED BY tests/test_slack_format.py
  "retrieved", never "computed"
  an empty MR arm reads "no pre-computed MR found in this snapshot (not evidence of no
  effect)" - never "no effect", never "no association"
  a tool that ERRORED is never rendered as a source that holds no record. "the request
  failed" and "the source has no row" are different sentences and the card must say
  which one happened, on every line including the 1E dossier
  every card ends "every number traceable - N ledger entries - {file}", which is the
  invitation to go and check
  no emojis anywhere

ONE RUN AT A TIME. Bolt dispatches listeners on a thread pool, so two mentions can be
in flight together. `_RUN_LOCK` serialises the whole `run_pair` call, and the shell
passes `stem_prefix="slack"` so a mention writes cards/slack_*.ledger.jsonl and can
never truncate one of the frozen demo ledgers. A second asker waits; nobody gets a
ledger count that belongs to somebody else's pair.

Two mentions of the SAME pair still share one stem, so the lock alone is not enough for
what happens after it: the ledger lines are read INSIDE the lock and carried in the
result (`render.LEDGER_ENTRIES_KEY`), so section 11 renders from this run's own lines
rather than re-opening a file the next run may already have truncated; and the file
writes and uploads are serialised under the same lock, so a card or a figure cannot be
overwritten between being written and being sent.

USER TEXT IS DATA, NOT MARKUP. Slack delivers `<` `>` `&` HTML-escaped and re-parses
what the bot posts, so a name is stripped of angle brackets on the way in and escaped
again on the way out. Otherwise a mention could make the bot broadcast `<!channel>` or
post a link labelled "EpiGraphDB MR-EVE" pointing anywhere - on the one card whose
entire pitch is that every number can be checked at its source.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import threading
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pipeline
import render
from tools import _common, ids

# THE WEBSOCKET IMPLEMENTATION IS A CHOICE, NOT A DETAIL. slack_sdk ships its own
# from-scratch socket client and uses it by default; on a network that interferes with
# long-lived connections it logs a stream of
#
#   Failed to check the state of sock (... ConnectionResetError / SSL: BAD_LENGTH /
#   SSLEOFError: EOF occurred in violation of protocol)
#
# and reconnects. Those three together are not a clean close - they are a connection cut
# or corrupted mid-flight by something in the path, and short TLS handshakes to the same
# hosts can succeed perfectly while this happens. The websocket-client library handles
# that reconnection more robustly, so it is preferred when installed and the built-in
# client remains the fallback. Neither choice changes a single thing about the evidence.
SOCKET_MODE_CLIENT = "none"
try:
    from slack_bolt import App
    try:
        from slack_bolt.adapter.socket_mode.websocket_client import SocketModeHandler

        SOCKET_MODE_CLIENT = "websocket-client"
    except ImportError:
        from slack_bolt.adapter.socket_mode import SocketModeHandler

        SOCKET_MODE_CLIENT = "built-in"
except ImportError:
    App = None
    SocketModeHandler = None

# Guarded the same way slack_bolt is: plots.py imports matplotlib, and a machine without
# it must still be able to answer a mention with the summary and the card. A missing
# figure is a missing figure; it is not a reason to lose the numbers.
try:
    import plots
except Exception:                                        # pragma: no cover - import guard
    plots = None

BOT_TOKEN_VAR = "SLACK_BOT_TOKEN"
APP_TOKEN_VAR = "SLACK_APP_TOKEN"

MAX_LINE_CHARS = 2900
MAX_NAME_CHARS = 120
MAX_OUTCOMES_SHOWN = 3

# Slack's own Block Kit ceilings. A block over the limit is rejected for the WHOLE
# message, so the reply would be lost rather than shortened - every string that goes
# into a block is clipped here first.
MAX_BLOCK_CHARS = 3000
MAX_HEADER_CHARS = 150
MAX_FIELD_CHARS = 2000
MAX_FIELDS = 10
MAX_DOSSIER_FIELDS = 6
MAX_CONTEXT_ELEMENTS = 10
MAX_NOTES_SHOWN = 3

CARDS_DIR = REPO_ROOT / "cards"

STEM_PREFIX = "slack"

# Held across the whole run_pair call. ledger.py carries its active run in a ContextVar
# so two threads cannot overwrite each other's file, but two mentions of the SAME pair
# would still truncate one file twice. One run at a time is the honest answer, and a
# queued reply is better than two ledger counts that belong to nobody.
_RUN_LOCK = threading.Lock()

STATE_LABELS = {
    "A": "retrieved MR",
    "B": "analysis-ready",
    "C": "evidence gap",
}

USAGE = (
    "I could not read a pair out of that. Try `@metabocausal urate vs gout`, "
    "`@metabocausal glycine x coronary artery disease`, `@metabocausal urate -> gout`, "
    "or `@metabocausal is urate causal for gout`. Quote a name that contains the "
    "separator word: `@metabocausal \"trimethylamine N-oxide\" x CAD`."
)

EMPTY_MR = "no pre-computed MR found in this snapshot (not evidence of no effect)"
EMPTY_COLOC = (
    "none retrieved for this pair in Open Targets (not evidence against a shared causal "
    "variant)"
)

ATTACH_PREFIX = "attachments skipped: "
# The one failure that is a setup step rather than a bug, so it names the setup step.
MISSING_SCOPE_NOTE = ATTACH_PREFIX + "app needs files:write (reinstall with manifest v2)"
UPLOAD_FAILED_NOTE = (
    ATTACH_PREFIX + "{what} could not be uploaded ({detail}). That is a failure of this "
    "shell, not a statement about the biology - every number above is unchanged and the "
    "ledger named in the footer still holds everything that was retrieved."
)

CARD_TITLE = "MetaboCausal evidence card - {metabolite} x {disease}"
FIGURE_TITLE = "{metabolite} x {disease} - retrieved, not computed"

# The context footer under the blocks. The mrkdwn card's own footer is a different
# sentence ("every number traceable - ...") and lives in format_card; both end in the
# ledger's filename, which is the invitation to go and check.
BLOCK_FOOTER_PREFIX = "Retrieved, not computed - "

_MENTION = re.compile(r"<[@#!][^>]*>")
_LINK = re.compile(r"<(?:https?://)?([^|>]*)(?:\|([^>]*))?>")
# Double quotes only. A `'...'` branch used to treat the two apostrophes in
# "Alzheimer's vs Parkinson's" as a quoted span and hand the pipeline a name with the
# apostrophes deleted; Slack users type double quotes and only those are documented.
_QUOTED = re.compile("\"([^\"]+)\"|“([^”]+)”")
_LEAD = re.compile(
    r"^(?:please\s+|hey\s+|hi\s+|hello\s+|ok\s+|okay\s+|so\s+|"
    r"is\s+|are\s+|was\s+|were\s+|does\s+|do\s+|did\s+|can\s+|could\s+|would\s+|"
    r"you\s+|u\s+|we\s+|kindly\s+|just\s+|"
    r"what\s+about\s+|how\s+about\s+|check\s+|run\s+|look\s+up\s+|tell\s+me\s+about\s+)+",
    re.IGNORECASE,
)
_SEPARATOR = re.compile(
    r"(?:\s*(?:-->|->|=>|→|×)\s*"
    r"|\s+(?:\bversus\b|\bvs\.?|\bx\b|\bcausal\s+for\b|\bcauses\b|\bcause\b)\s+)",
    re.IGNORECASE,
)
_TRAILING = re.compile(r"[\s\.,;:!?]+$")
# The mirror of _LEAD. Without it "urate vs gout please" queries the disease "gout
# please", which resolves against nothing, degrades to its raw string and comes back
# State C - the flagship State A pair, reported as an evidence gap, because somebody
# was polite.
_TRAILING_COURTESY = re.compile(
    r"(?:[\s,]+(?:please|pls|plz|thanks|thank\s+you|ty|"
    r"for\s+me|for\s+us|now|today|mate|buddy))+$",
    re.IGNORECASE,
)
_ANGLES = re.compile(r"[<>]+")
_PLACEHOLDER = "\x00{index}\x00"
_PLACEHOLDER_BACK = re.compile(r"\x00(\d+)\x00")


# ---------------------------------------------------------------- parsing the mention

def _strip_edges(text: str) -> str:
    """Trailing punctuation, then a trailing courtesy phrase, then punctuation again:
    "urate vs gout, please." and "urate vs gout thanks" both end at "gout"."""
    trimmed = _TRAILING.sub("", text)
    trimmed = _TRAILING_COURTESY.sub("", trimmed)
    return _TRAILING.sub("", trimmed).strip()


def parse_pair(text: str):
    """Pull (metabolite, disease) out of one mention, or return None.

    Understands `a x b`, `a vs b`, `a versus b`, `a -> b`, `a => b`, `is a causal for b`
    and `does a cause b`; the bot mention itself, a leading politeness or question word,
    a trailing courtesy word and trailing punctuation are stripped first. A name that
    contains a separator word must be quoted (`"trimethylamine N-oxide" x CAD`), and a
    quoted name is taken verbatim - the courtesy strip runs while quoted spans are still
    stashed, so a name that really ends in "now" survives quoting. Angle brackets are
    dropped from each name, so no Slack control sequence can reach `run_pair`, the
    ledger args or the card. Anything that does not split into exactly two non-empty
    names is None - the handler answers that with the usage line rather than guessing.
    """
    if not isinstance(text, str):
        return None

    # Unescape FIRST. Slack delivers a user's own `<` `>` `&` HTML-escaped, so stripping
    # markup before unescaping let `&lt;!channel&gt;` walk past both strippers and become
    # the raw broadcast sequence afterwards. Unescaping first means anything that LOOKS
    # like a control sequence is treated as one and removed, which is the safe direction.
    cleaned = html.unescape(text)
    cleaned = _MENTION.sub(" ", cleaned)
    cleaned = _LINK.sub(lambda match: match.group(2) or match.group(1), cleaned)
    cleaned = " ".join(cleaned.split())

    quoted = []

    def _stash(match):
        quoted.append(next(group for group in match.groups() if group is not None))
        return _PLACEHOLDER.format(index=len(quoted) - 1)

    cleaned = _QUOTED.sub(_stash, cleaned)
    cleaned = _LEAD.sub("", cleaned).strip()
    cleaned = _strip_edges(cleaned)
    if not cleaned:
        return None

    parts = _SEPARATOR.split(cleaned)
    if len(parts) != 2:
        return None

    names = []
    for part in parts:
        name = _PLACEHOLDER_BACK.sub(
            lambda match: quoted[int(match.group(1))],
            _strip_edges(part),
        ).strip()
        name = _ANGLES.sub(" ", _TRAILING.sub("", name)).strip("\"“”")
        # A matching PAIR of apostrophes around the whole name is a quote a user meant;
        # a single apostrophe inside it belongs to the disease (Alzheimer's, Graves').
        if len(name) > 2 and name[0] == "'" and name[-1] == "'":
            name = name[1:-1]
        name = " ".join(name.split())
        if not name or len(name) > MAX_NAME_CHARS:
            return None
        names.append(name)

    return names[0], names[1]


# ---------------------------------------------------------------- rendering the card

def _fit(line: str) -> str:
    """Slack renders at most 3000 characters per block. A caveat sentence or a classifier
    reason is never that long, but a card must not be able to lose its footer because one
    upstream string was."""
    text = " ".join(str(line).split())
    if len(text) <= MAX_LINE_CHARS:
        return text
    return text[:MAX_LINE_CHARS] + " ...[truncated]"


def _number(
    value,
    spec: str = "g",
):
    try:
        return format(float(value), spec)
    except (TypeError, ValueError):
        return None


def _count(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _escape(value) -> str:
    """Slack's own rule for text that must be shown, not interpreted. Without it a
    mention carrying `&lt;!channel&gt;` comes back through html.unescape as the raw
    broadcast sequence and the bot fires it, and `<https://.../|EpiGraphDB MR-EVE>`
    becomes a clickable link with a source's name on somebody else's URL."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _status(env) -> str:
    return env.get("status") if isinstance(env, dict) else "not run"


def _data(env) -> dict:
    data = env.get("data") if isinstance(env, dict) else None
    return data if isinstance(data, dict) else {}


def _best_estimate(estimates: list):
    """The retrieved row a reader should check first: the one with the smallest retrieved
    p-value among rows that carry a full effect size, uncertainty and p-value. A display
    choice over retrieved rows - nothing is recomputed and no row is dropped from the
    ledger."""
    complete = []
    for row in estimates:
        if not isinstance(row, dict):
            continue
        values = [_number(row.get(key)) for key in ("b", "se", "pval")]
        if all(value is not None for value in values):
            complete.append((float(row["pval"]), row))
    if not complete:
        return None
    return min(complete, key=lambda pair: pair[0])[1]


def _mr_line(env) -> str:
    """An error envelope does NOT erase the rows it carries. tools/epigraphdb.py keeps
    every estimate retrieved before a mid-sweep failure and writes them to the ledger
    verbatim; rendering that as "nothing found" would be the project's own red line -
    a retrieval that did return a row reported as absent."""
    if env is None:
        return "retrieved MR: get_mr_result did not run, so nothing was retrieved"

    status = _status(env)
    data = _data(env)
    estimates = [row for row in (data.get("estimates") or []) if isinstance(row, dict)]

    if not estimates:
        if status == "error":
            return f"retrieved MR: get_mr_result returned an error envelope - {EMPTY_MR}"
        return f"retrieved MR: {EMPTY_MR}"

    n_estimates = data.get("n_estimates")
    retrieved = _count(len(estimates) if n_estimates is None else n_estimates)
    lead = (
        f"retrieved MR: the request failed part way through; {retrieved} estimate(s) "
        f"were retrieved before the failure and are in the ledger"
        if status == "error"
        else f"retrieved MR: {retrieved} estimate(s) retrieved"
    )

    best = _best_estimate(estimates)
    if not best:
        return f"{lead}; none carries a full effect size, uncertainty and p-value"
    # render.py owns how a retrieved number is printed, and this line quotes the same row
    # the attached card quotes. Formatting it here was how the summary came to say
    # b=1.3665 beside a card that said 1.367, and how a p that underflowed to 0.0 in
    # MR-EVE reached the thread as "p=0" - certainty, on the one line a room reads first,
    # under a card whose own caveat forbids exactly that rendering.
    return (
        f"{lead}; smallest retrieved p-value {best.get('exposure_id')} -> "
        f"{best.get('outcome_id')} {best.get('method')} b={render._effect(best.get('b'))} "
        f"se={render._effect(best.get('se'))} p={render._pvalue(best.get('pval'))}"
    )


def _queried_text(
    data:      dict,
    n_queried: int,
) -> str:
    """How many datasets were actually queried, against how many the synonyms named.
    The cap is in the envelope's caveats; a card that hides it tells a reader 6 datasets
    were looked at when 22 measure the metabolite and 16 were never opened."""
    matched = data.get("matched_datasets")
    if _number(matched) is None or int(matched) <= n_queried:
        return f"{n_queried} dataset(s) queried"
    return (
        f"{n_queried} of {_count(matched)} dataset(s) named by these synonyms were "
        f"queried (the largest by sample size)"
    )


def _instrument_line(env) -> str:
    if env is None:
        return "instruments: get_mqtl_instruments did not run, so no hit count was retrieved"
    if _status(env) == "error":
        return "instruments: get_mqtl_instruments returned an error envelope, so no hit count was retrieved"

    data = _data(env)
    exposures = [row for row in (data.get("exposures") or []) if isinstance(row, dict)]
    queried = _queried_text(
        data,
        len(exposures),
    )

    scored = [row for row in exposures if _number(row.get("gws_hits")) is not None]
    if not scored:
        return f"instruments: no exposure dataset with a retrieved hit count ({queried})"

    best = max(scored, key=lambda row: float(row["gws_hits"]))
    weak = best.get("weak_instruments")
    weak_text = "weak count not retrieved" if weak is None else f"{_count(weak)} weak (F < 10)"
    return (
        f"instruments: best {best.get('id')} ({best.get('trait')}) "
        f"{_count(best.get('gws_hits'))} genome-wide significant hit(s) retrieved, "
        f"{weak_text}; {queried}"
    )


def _dataset_text(row: dict) -> str:
    """`n=None` is a Python repr, not a sentence. OpenGWAS records no sample_size for
    whole families of datasets (every finn-b row), and "the source does not record one"
    is the true statement there."""
    identifier = row.get("id")
    trait = row.get("trait")
    if _number(row.get("sample_size")) is None:
        return f"{identifier} ({trait}, sample size not recorded by the source)"
    return f"{identifier} ({trait}, n={_count(row.get('sample_size'))})"


def _outcome_line(env) -> str:
    if env is None:
        return "outcome datasets: find_outcome_datasets did not run, so none was retrieved"
    if _status(env) == "error":
        return "outcome datasets: find_outcome_datasets returned an error envelope"

    data = _data(env)
    datasets = [row for row in (data.get("datasets") or []) if isinstance(row, dict)]
    if not datasets:
        return "outcome datasets: none named by these synonyms in this OpenGWAS release"

    shown = ", ".join(_dataset_text(row) for row in datasets[:MAX_OUTCOMES_SHOWN])
    matched = data.get("n_matched_before_cap")
    of_matched = f" of {_count(matched)} matched" if matched else ""
    return f"outcome datasets: {len(datasets)} retrieved{of_matched} - {shown}"


def _coloc_line(env) -> str:
    """The colocalisation line, in the same four shapes the card's verdict qualifier has:
    not run, failed, nothing published, or a retrieved H4 with the locus it sits at.

    "none retrieved" and "no colocalisation" are different sentences and only the first
    one is true here - the arm reads a capped slice of a published table, so an absent row
    is a gap, never evidence against a shared causal variant. The H4 is formatted by
    render.py, so the thread and the attached card cannot print one retrieved number two
    different ways.
    """
    if env is None:
        return "colocalisation: not queried in this run"
    if _status(env) == "error":
        return (
            "colocalisation: get_colocalisation returned an error envelope, so nothing "
            "was retrieved - no information, not an absent colocalisation"
        )

    data = _data(env)
    hits = [row for row in (data.get("metabolite_hits") or []) if isinstance(row, dict)]
    if not hits:
        return f"colocalisation: {EMPTY_COLOC}"

    best = hits[0]
    return (
        f"colocalisation: H4 {render._h4(best.get('h4'))} (retrieved) - "
        f"{best.get('locus_study_id')} x {best.get('partner_study_id')} "
        f"({best.get('partner_trait')}) at chr{best.get('chromosome')}:"
        f"{best.get('position')}, {best.get('method')}; "
        f"{_count(data.get('n_metabolite_hits'))} retrieved row(s) for this pair"
    )


def _catalog_line(env) -> str:
    if env is None:
        return "GWAS Catalog: not run; it is not a classifier input, so the state did not move"
    if _status(env) == "error":
        return "GWAS Catalog: returned an error envelope; it is not a classifier input, so the state did not move"
    data = _data(env)
    # mapped_genes is one row per (variant, gene, annotation source), so for urate x gout
    # it is 72 rows naming 14 genes. The envelope's own caveat says so in section 8 of the
    # attached card ("the row count is not a gene count"), and calling 72 a gene count
    # inflates it five-fold in the flattering direction.
    rows = [row for row in (data.get("mapped_genes") or []) if isinstance(row, dict)]
    symbols = {str(row.get("gene")).strip() for row in rows if str(row.get("gene") or "").strip()}
    return (
        f"GWAS Catalog: {_count(data.get('n_associations_kept'))} of "
        f"{_count(data.get('n_associations_total'))} association(s) kept, "
        f"{len(symbols)} distinct mapped gene(s) across {len(rows)} annotation row(s) "
        f"retrieved (not a classifier input)"
    )


def _unresolved_gene(data: dict) -> bool:
    """The 1E tools write `ensembl=None` when no exact symbol matched - that is a lookup
    that failed, not a source with no record. A key that is absent altogether is a
    different thing and must not be read as a failed lookup."""
    return "ensembl" in data and data["ensembl"] is None


def _association_text(env) -> str:
    if _status(env) == "error":
        return "Open Targets association: error envelope, so nothing was retrieved"
    data = _data(env)
    if _unresolved_gene(data):
        return (
            "Open Targets: gene symbol not resolved, so no association record was queried"
        )
    row = data.get("target_disease")
    score = _number(row.get("score"), ".3g") if isinstance(row, dict) else None
    if score is None:
        return "Open Targets: this disease is not on the returned association page"
    return f"Open Targets association score {score}"


def _drugs_text(env) -> str:
    if _status(env) == "error":
        return "known drugs: error envelope, so nothing was retrieved"
    data = _data(env)
    if _unresolved_gene(data):
        return "known drugs: gene symbol not resolved, so no drug record was queried"
    known = data.get("drugs") or []
    if not known:
        return "no known drug or clinical candidate retrieved"
    return f"{len(known)} known drug(s) or clinical candidate(s) retrieved"


def _chembl_text(env) -> str:
    if _status(env) == "error":
        return "ChEMBL: error envelope, so nothing was retrieved"
    data = _data(env)
    target = data.get("target") or {}
    if not target:
        return "no exact human single-protein target in ChEMBL"
    return (
        f"ChEMBL {target.get('target_chembl_id')} "
        f"{len(data.get('mechanisms') or [])} mechanism(s) / "
        f"{_count(data.get('activity_count'))} activity record(s)"
    )


def _gnomad_text(env) -> str:
    if _status(env) == "error":
        return "gnomAD: error envelope, so nothing was retrieved"
    data = _data(env)
    loeuf = _number(data.get("loeuf"), ".4g")
    if loeuf is not None:
        return f"gnomAD LOEUF {loeuf}"
    if _unresolved_gene(data):
        return "gnomAD: gene symbol not resolved, so no constraint record was retrieved"
    return "gnomAD constraint not retrieved for this gene"


_DOSSIER_PARTS = (
    ("get_target_disease_evidence", _association_text),
    ("get_known_drugs",             _drugs_text),
    ("get_chembl_modulators",       _chembl_text),
    ("get_gnomad_constraint",       _gnomad_text),
)


def _dossier_pairs(dossier: dict) -> list:
    """(gene, one-line summary) for every gene in the 1E dossier, with the same status
    guard the four core lines have.

    A dead network, a GraphQL error or a gene symbol Open Targets could not resolve used
    to come out of here as four confident negatives - "this disease is not on the
    returned association page" when no page was fetched. That is a retrieval gap printed
    as a finding, and it is the one card line a reader takes for biology.

    The mrkdwn card and the Block Kit fields both read from here, so the two surfaces
    cannot drift into two different sentences about the same envelope.
    """
    pairs = []
    for gene, tools in (dossier or {}).items():
        parts = [
            render_part(tools[name])
            for name, render_part in _DOSSIER_PARTS
            if tools.get(name) is not None
        ]
        pairs.append((str(gene), "; ".join(parts)))
    return pairs


def _dossier_lines(dossier: dict) -> list:
    return [f"dossier {gene}: {text}" for gene, text in _dossier_pairs(dossier)]


def _side_name(entity) -> str:
    """The name as the asker typed it, escaped, and marked when 1A could not resolve it.
    An unresolved side belongs in the verdict line: a degradation note under the numbers
    is true but it is the last thing read, and the headline is what a room hears."""
    if not isinstance(entity, dict):
        return "?"
    name = _escape(entity.get("query") or "?")
    if entity.get("resolved") is False:
        return f"{name} (unresolved name)"
    return name


def _plain_name(entity) -> str:
    """The asker's name for a file title, where Slack shows text and parses no markup.
    Angle brackets are dropped rather than escaped, so nothing can look like a control
    sequence and a reader is not shown "&lt;" in a filename."""
    if not isinstance(entity, dict):
        return "?"
    return " ".join(_ANGLES.sub(" ", str(entity.get("query") or "?")).split()) or "?"


def _headline(result: dict) -> str:
    """The bold first line: the state, what the state MEANS, and the pair it is about.
    One function, so the mrkdwn card and the Block Kit verdict cannot drift apart."""
    state = _escape(result.get("state") or "?")
    label = STATE_LABELS.get(str(result.get("state") or ""), "state not recognised")
    return (
        f"*State {state} - {label}*  "
        f"{_side_name(result.get('metabolite'))} x {_side_name(result.get('disease'))}"
    )


def format_card(result: dict) -> str:
    """Turn one `pipeline.run_pair` result into the single mrkdwn string posted in the
    thread. Presentation only: it selects and formats numbers that are already in the
    envelopes, and adds no claim that is not in them. Every string that came from the
    asker - the two names, and the names quoted back inside a degradation note - goes
    through `_escape` before it is interpolated, so Slack shows it instead of running
    it."""
    envelopes = result.get("envelopes") or {}

    lines = [
        _headline(result),
        str(result.get("reason") or ""),
        _mr_line(envelopes.get("mr")),
        _coloc_line(envelopes.get("coloc")),
        _instrument_line(envelopes.get("instruments")),
        _outcome_line(envelopes.get("outcomes")),
    ]

    if envelopes.get("catalog") is not None:
        lines.append(_catalog_line(envelopes["catalog"]))
    if envelopes.get("dossier"):
        lines.extend(_dossier_lines(envelopes["dossier"]))

    for note in result.get("notes") or []:
        lines.append(f"note: {_escape(note)}")

    ledger_name = Path(str(result.get("ledger_path") or "")).name or "no ledger written"
    lines.append(
        f"every number traceable - {_count(result.get('n_ledger_entries'))} ledger "
        f"entries - {ledger_name}"
    )

    return "\n".join(_fit(line) for line in lines if str(line).strip())


def _ledger_name(result: dict) -> str:
    return Path(str(result.get("ledger_path") or "")).name or "no ledger written"


# ---------------------------------------------------------------- the Block Kit summary
#
# The same sentences as the mrkdwn card, laid out so the state is read before the
# numbers and the numbers before the caveats. Nothing new is said here: every field body
# comes from the line functions above, so a wording rule fixed in one place is fixed on
# both surfaces and tests/test_slack_format.py protects them together.
#
# Block Kit is a hard-limit API. A header over 150 characters, a field over 2000 or a
# section over 3000 rejects the WHOLE message, so the reply would be lost rather than
# shortened - and a lost reply is a card a reader never sees. Everything is clipped here,
# and a clip always says it clipped.

_ELLIPSIS = " ...[truncated]"


def _clip(
    text:  str,
    limit: int,
) -> str:
    """Cut to Slack's limit and SAY so. The cut never lands inside an HTML entity:
    "&am" is not "&amp;" and would be shown to a reader as the three literal
    characters."""
    text = str(text)
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - len(_ELLIPSIS))]
    head, marker, tail = cut.rpartition("&")
    if marker and ";" not in tail and len(tail) < 6:
        cut = head
    return cut + _ELLIPSIS


def _strip_prefix(
    line:   str,
    prefix: str,
) -> str:
    """The card line without its "retrieved MR:" style label, because in a field the
    label is the field's own bold title."""
    text = str(line)
    if text.startswith(prefix):
        text = text[len(prefix):]
    return text.strip()


def _field(
    title: str,
    body:  str,
) -> dict:
    """One mrkdwn field: a bold title and one sentence under it. The body is escaped on
    the way in - a dataset trait is a string from OpenGWAS, not markup this bot wrote."""
    return {
        "type": "mrkdwn",
        "text": _clip(
            f"*{_escape(title)}*\n{_escape(_fit(body))}",
            MAX_FIELD_CHARS,
        ),
    }


def _evidence_fields(result: dict) -> list:
    """Four arms always, then one field per dossier gene. Always four even when a tool
    never ran: "get_mr_result did not run" is information, and a field that vanishes when
    a stage fails silently tells a reader the arm was not relevant.

    Colocalisation sits directly under the MR field because that is the order a reader
    weighs them in - the estimate, then whether the two GWAS are even the same signal -
    and it is a QUALIFIER on the state above, never an input to it.
    """
    envelopes = result.get("envelopes") or {}
    fields = [
        _field(
            "Retrieved MR",
            _strip_prefix(_mr_line(envelopes.get("mr")), "retrieved MR:"),
        ),
        _field(
            "Colocalisation",
            _strip_prefix(_coloc_line(envelopes.get("coloc")), "colocalisation:"),
        ),
        _field(
            "Instruments",
            _strip_prefix(_instrument_line(envelopes.get("instruments")), "instruments:"),
        ),
        _field(
            "Outcomes",
            _strip_prefix(_outcome_line(envelopes.get("outcomes")), "outcome datasets:"),
        ),
    ]

    # Slack refuses a section with more than 10 fields, so the genes are capped - and the
    # cap is worked out from the room left rather than trimmed off the end afterwards. A
    # slice at the end would be a truncation nobody printed, which is the one thing this
    # project treats as worse than an error.
    genes = _dossier_pairs(envelopes.get("dossier"))
    room = MAX_FIELDS - len(fields)
    shown = genes[:min(MAX_DOSSIER_FIELDS, room)]
    if len(genes) > len(shown):
        shown = genes[:min(len(shown), room - 1)]        # one field back for the count

    for gene, text in shown:
        fields.append(_field(f"Dossier {gene}", text))
    if len(genes) > len(shown):
        fields.append(_field(
            "Dossier",
            f"showing {len(shown)} of {len(genes)} gene(s) here; the attached card has "
            f"every one of them",
        ))
    return fields


def _context_elements(result: dict) -> list:
    """The footer first, then the degradation notes. A note is why a number is missing,
    so it must survive into the summary - but it is the last thing read, not the first."""
    elements = [{
        "type": "mrkdwn",
        "text": _clip(
            f"{BLOCK_FOOTER_PREFIX}{_count(result.get('n_ledger_entries'))} ledger entries - "
            f"{_escape(_ledger_name(result))}",
            MAX_BLOCK_CHARS,
        ),
    }]

    notes = [str(note) for note in (result.get("notes") or []) if str(note).strip()]
    room = min(MAX_CONTEXT_ELEMENTS - len(elements), MAX_NOTES_SHOWN)
    for note in notes[:room]:
        elements.append({
            "type": "mrkdwn",
            "text": _clip(f"note: {_escape(_fit(note))}", MAX_BLOCK_CHARS),
        })
    if len(notes) > room:
        elements.append({
            "type": "mrkdwn",
            "text": f"note: showing {room} of {len(notes)} note(s); the attached card "
                    f"has every one of them",
        })
    return elements[:MAX_CONTEXT_ELEMENTS]


def build_blocks(result: dict) -> list:
    """The four blocks of one reply: header, verdict, evidence fields, footer.

    Presentation only, exactly like `format_card` - and `format_card` is still what goes
    in the message's `text`, so the whole card reaches a notification preview and any
    client that cannot render blocks.
    """
    if not isinstance(result, dict):
        result = {}

    metabolite = _side_name(result.get("metabolite"))
    disease = _side_name(result.get("disease"))
    verdict = "\n".join(
        part for part in (
            _headline(result),
            _fit(_escape(result.get("reason") or "")),
        )
        if part.strip()
    )

    return [
        {
            "type": "header",
            "text": {
                "type":  "plain_text",
                "text":  _clip(
                    f"MetaboCausal - {metabolite} x {disease}",
                    MAX_HEADER_CHARS,
                ),
                "emoji": False,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": _clip(verdict, MAX_BLOCK_CHARS),
            },
        },
        {
            "type":   "section",
            "fields": _evidence_fields(result),
        },
        {
            "type":     "context",
            "elements": _context_elements(result),
        },
    ]


# ---------------------------------------------------------------- the two attachments
#
# The summary is the headline; these two are the evidence. render.py builds the full
# 11-section card from the run's own envelopes and plots.py draws the one figure the
# state has, and both are written into cards/ beside the ledger they are justified by
# BEFORE either is uploaded - so a missing scope, a dropped socket or a Slack outage
# costs a reader nothing that is not still on disk.

def write_card(
    result:         dict,
    out_dir        = None,
    interpretation = None,
) -> Path:
    """Render this run's card and put it in cards/ under the run's own stem.

    `interpretation` reaches section 9 and nothing else, and render.render_card
    re-validates it against this run before printing a word of it - so passing a rejected
    one, or none at all, writes exactly the card this shell wrote before 1F landed."""
    folder = Path(out_dir) if out_dir else CARDS_DIR
    folder.mkdir(
        parents  = True,
        exist_ok = True,
    )
    path = folder / Path(render.card_filename(result)).name
    path.write_text(
        render.render_card(result, interpretation),
        encoding = "utf-8",
    )
    return path


# ---------------------------------------------------------------- section 9, on the operator's key

# WHOSE KEY. This shell runs on the OPERATOR's credential - the one in the deployment's
# .env - and never on a reader's. A Slack channel is a shared, logged place and a reader
# must never be asked to paste a secret into one, so per-user keys are not an option here
# and a per-user interface is not a smaller version of this; it is a different design.
# `Credential.source` records 'operator_env' so a card can always say which it was.
#
# WHICH MODEL. The default is the first model the registry marks `supported`, which means
# it has passed the evidence fixtures. A shared surface is exactly where an unvalidated
# model should not be the default, so if nothing is supported this shell writes no section
# 9 at all rather than quietly using an experimental one. Setting both variables below
# overrides that deliberately, for an operator who has made that call themselves.
LLM_PROVIDER_VAR = "METABOCAUSAL_LLM_PROVIDER"
LLM_MODEL_VAR = "METABOCAUSAL_LLM_MODEL"

INTERPRETATION_SKIPPED = (
    "第 9 节未写 / section 9 was not written: {reason} Every number above is unchanged - "
    "this is a limit of the interpretation step, not of the evidence."
)


def interpretation_target() -> tuple:
    """(provider, model, why_not). The configured pair, or the first supported one."""
    provider = os.environ.get(LLM_PROVIDER_VAR, "").strip()
    model = os.environ.get(LLM_MODEL_VAR, "").strip()
    if provider and model:
        return provider, model, ""
    try:
        import llm

        for row in llm.menu():
            if row["status"] == llm.SUPPORTED:
                return row["provider"], row["model"], ""
        return "", "", (
            "no model in this build has passed the evidence fixtures, and a shared "
            f"surface should not default to one that has not. Set {LLM_PROVIDER_VAR} and "
            f"{LLM_MODEL_VAR} to override."
        )
    except ImportError:
        return "", "", "the llm package is not importable in this shell."


def write_section_nine(result: dict, logger = None) -> tuple:
    """(interpretation, note). Never raises, and never delays the evidence.

    Called after the run is complete and the summary is already in the thread, so a model
    that is slow, missing or refused costs a paragraph and nothing else. The note is what
    the thread is told; it is empty when section 9 was written and accepted."""
    # NOT CONFIGURED IS SILENT. A deployment with no model or no key does not do section 9
    # at all, and saying so under every card would put a permanent notice on every run
    # about a feature that was never switched on. The card's own section 9 already reads
    # "pending integration", which is the accurate thing for a reader to see.
    #
    # TRIED AND FAILED IS NOT SILENT. A model that was reached and timed out, or wrote
    # prose the validator rejected, is a different event: something was attempted for this
    # run and did not land, and a silently absent paragraph would be indistinguishable
    # from one nobody asked for.
    provider, model, why_not = interpretation_target()
    if why_not:
        return None, ""

    try:
        from llm.cli import credential_from_env
        from llm.interpret import interpret

        credential = credential_from_env(provider)
        if not credential.is_usable():
            return None, ""
        outcome = interpret(
            result,
            provider   = provider,
            model      = model,
            credential = credential,
        )
    except Exception as exc:                             # noqa: BLE001 - deliberate boundary
        if logger is not None:
            logger.exception("the interpretation step failed")
        return None, INTERPRETATION_SKIPPED.format(
            reason=f"the interpretation step failed ({type(exc).__name__}).",
        )

    if outcome.accepted:
        return outcome, ""
    # A rejected paragraph is the validator working. The thread is told, because a silently
    # absent section 9 is indistinguishable from one nobody asked for.
    return None, INTERPRETATION_SKIPPED.format(reason=outcome.reason)


def _error_code(exc) -> str:
    """Slack's own error string out of a SlackApiError, or "" for anything else. Read
    through `.get`/`.data` rather than by isinstance, so this file needs no import from
    slack_sdk and a fake client in a test can raise the real error class or a stand-in."""
    response = getattr(exc, "response", None)
    if response is None:
        return ""
    code = None
    try:
        code = response.get("error")
    except Exception:
        code = None
    if code is None:
        data = getattr(response, "data", None)
        if isinstance(data, dict):
            code = data.get("error")
    return str(code or "")


def _upload_note(
    exc,
    what: str,
) -> str:
    """One line a reader can act on. `missing_scope` is the expected one until the app is
    reinstalled with manifest v2, so it names the scope and the fix instead of a class
    name nobody can do anything with. Only the exception TYPE is ever quoted - a Slack
    error body is not something this shell re-posts."""
    if _error_code(exc) == "missing_scope":
        return MISSING_SCOPE_NOTE
    return UPLOAD_FAILED_NOTE.format(
        what   = what,
        detail = type(exc).__name__,
    )


def _upload_one(
    client,
    channel:   str,
    thread_ts: str,
    path:      Path,
    title:     str,
) -> None:
    client.files_upload_v2(
        channel   = channel,
        thread_ts = thread_ts,
        file      = str(path),
        filename  = path.name,
        title     = title,
    )


def attach_artifacts(
    result:    dict,
    client,
    channel:   str,
    thread_ts: str,
    logger  = None,
    interpretation = None,
) -> list:
    """Write the card and the figure, upload both into the same thread, and return the
    lines the thread still needs to be told. [] means everything landed.

    One line per artifact that failed, deduplicated - the caller posts them as a single
    message. "the card" and "the figure" are not interchangeable to a reader, so each
    names itself; a thread still gets one explanation rather than one per file.

    Never raises and never retries. An upload that fails is reported once, in words, and
    the run is over: a retry loop against a scope that is not installed would hammer
    Slack on every mention and still fail. A `missing_scope` on the first upload skips
    the second - the answer would be identical and the reader already has the reason.

    With no client (a direct call, a test, a CLI) there is nothing to upload to, and that
    is not a failure to report: the function does nothing and says nothing.
    """
    notes = []

    def remember(
        exc,
        what,
    ):
        note = _upload_note(exc, what)
        if note not in notes:
            notes.append(note)
        if logger is not None:
            logger.warning(f"[slack_app] {what} was not uploaded: {type(exc).__name__}")
        return _error_code(exc) == "missing_scope"

    if client is None or not channel:
        return notes

    try:
        metabolite = _plain_name(result.get("metabolite"))
        disease = _plain_name(result.get("disease"))
        blocked = False

        try:
            card_path = write_card(result, interpretation=interpretation)
        except Exception as exc:
            card_path = None
            remember(exc, "the evidence card")

        if card_path is not None:
            try:
                _upload_one(
                    client,
                    channel,
                    thread_ts,
                    card_path,
                    CARD_TITLE.format(
                        metabolite = metabolite,
                        disease    = disease,
                    ),
                )
            except Exception as exc:
                blocked = remember(exc, "the evidence card")

        figure_path = None
        if plots is not None:
            try:
                drawn = plots.plot_for_result(
                    result,
                    str(CARDS_DIR),
                )
                figure_path = Path(drawn) if drawn else None
            except Exception as exc:
                remember(exc, "the figure")

        if figure_path is not None and not blocked:
            try:
                _upload_one(
                    client,
                    channel,
                    thread_ts,
                    figure_path,
                    FIGURE_TITLE.format(
                        metabolite = metabolite,
                        disease    = disease,
                    ),
                )
            except Exception as exc:
                remember(exc, "the figure")
    except Exception as exc:                             # pragma: no cover - last resort
        remember(exc, "the attachments")

    return notes


# ---------------------------------------------------------------- the guided menu
#
# One mention, one menu, one button press per thing a reader actually wants. The point is
# not decoration: the GWAS Catalog arm costs about 100 seconds and the gene arm costs five
# requests per gene, so a reader who only wants the MR arm should not pay for either - and
# a reader who misspelled the metabolite should find that out from the menu's resolution
# line, not after a two-minute wait.
#
# Every label is BILINGUAL, Chinese first and English after the slash, with the database
# in parentheses: the room this was built for reads both, and a database name is what makes
# an arm checkable.

ARMS_BLOCK_ID = "metabocausal_arms"
ARMS_ACTION_ID = "metabocausal_arms_select"
GENERATE_ACTION_ID = "metabocausal_generate"

# (value, label, the parenthetical that does not fit in Slack's 75-character option text)
MENU_ARMS = (
    (
        "mr",
        "现成 MR 因果估计 / retrieved MR (EpiGraphDB)",
        "",
    ),
    (
        "instruments",
        "工具变量可行性 / instruments (OpenGWAS)",
        "",
    ),
    (
        "catalog",
        "疾病关联背景 / associations (GWAS Catalog, note: slow ~100s)",
        "",
    ),
    (
        "genes",
        "effector 基因与成药档案 / genes & target dossier",
        "(atlas + Open Targets/ChEMBL/gnomAD)",
    ),
)

DEFAULT_ARMS = tuple(value for value, _label, _extra in MENU_ARMS)

# The two arms the classifier is a pure function of. A run without them would still print
# a state, and that state would rest on nothing - so they are run whatever the box says,
# and the thread is TOLD, because silently ignoring a tick is worse than refusing it.
LOCKED_ARMS = ("mr", "instruments")

LOCKED_ARMS_NOTE = (
    "the retrieved MR and instrument arms cannot be switched off: the A/B/C state is a "
    "pure function of those two envelopes, so both ran anyway. Nothing else was changed."
)

MENU_PROMPT = "选择要跑的证据臂 / pick the evidence arms, then generate:"
MENU_HEADER = "MetaboCausal - {metabolite} x {disease}"
GENERATE_LABEL = "生成证据卡 / Generate card"

# Slack's own ceilings for a checkbox option and a button.
MAX_OPTION_CHARS = 75
MAX_BUTTON_CHARS = 75
MAX_ACTION_VALUE_CHARS = 2000

RESOLVED_LINE = "{side} {query} -> {label} ({id}), {count} spelling(s) [{source}]"
UNRESOLVED_LINE = (
    "{side} {query} -> 没有解析到 id / no id resolved; the run will match on the raw "
    "string only, which is a gap in resolution and not a statement about the entity"
)
SAMPLE_SOURCE = "frozen 1A sample"
LIVE_SOURCE = "live 1A resolver"

MENU_FOOTER = (
    "Nothing has been retrieved yet. The GWAS Catalog arm adds about 100 s; the gene arm "
    "adds five requests per gene."
)


def _option(arm: tuple) -> dict:
    """One checkbox option. The parenthetical goes in `description` because Slack refuses
    an option whose text is over 75 characters - and refuses the WHOLE message with it."""
    value, label, extra = arm
    option = {
        "text": {
            "type":  "plain_text",
            "text":  _clip(label, MAX_OPTION_CHARS),
            "emoji": False,
        },
        "value": value,
    }
    if extra:
        option["description"] = {
            "type":  "plain_text",
            "text":  _clip(extra, MAX_OPTION_CHARS),
            "emoji": False,
        }
    return option


def menu_line(arm: tuple) -> str:
    """The whole bilingual line of one arm, label and parenthetical together - what a
    reader sees, and what the tests assert against."""
    _value, label, extra = arm
    return f"{label} {extra}".strip()


def encode_pair_value(
    metabolite: str,
    disease:    str,
) -> str:
    """The generate button's payload: the pair itself, not a pointer to it.

    A pointer into `_THREAD_STATE` would stop working the moment the shell restarts or the
    32-thread cap evicts the entry, and the button would then fail on a pair that is
    written in the message right above it.
    """
    return _clip(
        json.dumps(
            {
                "m": str(metabolite or "")[:MAX_NAME_CHARS],
                "d": str(disease or "")[:MAX_NAME_CHARS],
            },
            ensure_ascii = False,
        ),
        MAX_ACTION_VALUE_CHARS,
    )


def decode_pair_value(value) -> tuple | None:
    """(metabolite, disease) out of a generate button, or None. A payload that is not the
    shape this shell wrote is refused rather than guessed at: it is text that arrived from
    outside the process."""
    try:
        loaded = json.loads(str(value or ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(loaded, dict):
        return None
    metabolite = str(loaded.get("m") or "").strip()
    disease = str(loaded.get("d") or "").strip()
    if not metabolite or not disease:
        return None
    if len(metabolite) > MAX_NAME_CHARS or len(disease) > MAX_NAME_CHARS:
        return None
    return metabolite, disease


def _preview_side(
    side:   str,
    entity: dict,
    source: str,
) -> dict:
    return {
        "side":     side,
        "query":    str((entity or {}).get("query") or ""),
        "label":    str((entity or {}).get("label") or ""),
        "id":       str((entity or {}).get("id") or ""),
        "synonyms": list((entity or {}).get("synonyms") or []),
        "resolved": bool((entity or {}).get("id")),
        "source":   source,
    }


def resolve_preview(
    metabolite: str,
    disease:    str,
) -> dict:
    """What 1A makes of the two names, before anything is retrieved.

    The frozen sample first (free, offline); a side the sample does not carry goes to the
    live resolver, which costs one OLS4 lookup and one PubChem lookup. `run_pair` resolves
    again when the button is pressed - this is a preview, and a pair that resolves to
    something the asker did not mean is worth one duplicate lookup to catch here rather
    than after two minutes of retrieval.

    Never raises: a resolver that is down leaves both sides unresolved, and the menu then
    says the run will match on the raw strings.
    """
    sides = {
        "metabolite": _preview_side("metabolite", {"query": metabolite}, ""),
        "disease":    _preview_side("disease", {"query": disease}, ""),
    }
    try:
        sample = pipeline.load_sample()
        for side, name in (("metabolite", metabolite), ("disease", disease)):
            entity = pipeline.resolve_entity(
                name,
                side,
                sample,
            )
            if entity.get("resolved"):
                sides[side] = _preview_side(side, entity, SAMPLE_SOURCE)

        missing = [
            side for side in ("metabolite", "disease")
            if not sides[side]["resolved"] and sides[side]["query"]
        ]
        if missing:
            env = ids.resolve_ids(metabolite, disease)
            data = env.get("data") if isinstance(env, dict) else None
            data = data if isinstance(data, dict) else {}
            for side in missing:
                leg = data.get(side)
                leg = leg if isinstance(leg, dict) else {}
                identifier = leg.get("chebi" if side == "metabolite" else "id")
                if identifier:
                    sides[side] = _preview_side(
                        side,
                        {
                            "query":    sides[side]["query"],
                            "label":    leg.get("label"),
                            "id":       identifier,
                            "synonyms": leg.get("synonyms"),
                        },
                        LIVE_SOURCE,
                    )
    except Exception:                                    # noqa: BLE001 - deliberate boundary
        pass
    return sides


def preview_lines(preview: dict) -> list:
    """One line per side, escaped. A label and an id are retrieved strings, not markup."""
    lines = []
    for side in ("metabolite", "disease"):
        entry = preview.get(side) or {}
        if not entry.get("query"):
            continue
        if entry.get("resolved"):
            lines.append(RESOLVED_LINE.format(
                side   = side,
                query  = _escape(entry["query"]),
                label  = _escape(entry.get("label") or entry["query"]),
                id     = _escape(entry.get("id")),
                count  = len(entry.get("synonyms") or []),
                source = entry.get("source") or "",
            ))
        else:
            lines.append(UNRESOLVED_LINE.format(
                side  = side,
                query = _escape(entry["query"]),
            ))
    return lines


def build_menu_blocks(
    metabolite: str,
    disease:    str,
    preview  = None,
) -> list:
    """The menu: what the pair resolved to, one pre-ticked box per arm, and the button.

    Every box starts ticked, so the default press is the whole card and a reader has to
    choose to retrieve LESS rather than remember to ask for more.
    """
    lines = preview_lines(preview or {})
    head = "*" + _escape(MENU_HEADER.format(
        metabolite = _plain_name({"query": metabolite}),
        disease    = _plain_name({"query": disease}),
    )) + "*"
    if lines:
        head = head + "\n" + "\n".join(lines)

    # Built twice rather than aliased: `initial_options` and `options` are two lists in the
    # payload, and sharing the dicts between them makes one edit change both.
    options = [_option(arm) for arm in MENU_ARMS]
    ticked = [_option(arm) for arm in MENU_ARMS]
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": _clip(head, MAX_BLOCK_CHARS),
            },
        },
        {
            "type":     "section",
            "block_id": ARMS_BLOCK_ID,
            "text":     {
                "type": "mrkdwn",
                "text": MENU_PROMPT,
            },
            "accessory": {
                "type":            "checkboxes",
                "action_id":       ARMS_ACTION_ID,
                "options":         options,
                "initial_options": ticked,
            },
        },
        {
            "type":     "actions",
            "elements": [{
                "type":      "button",
                "action_id": GENERATE_ACTION_ID,
                "style":     "primary",
                "text":      {
                    "type":  "plain_text",
                    "text":  _clip(GENERATE_LABEL, MAX_BUTTON_CHARS),
                    "emoji": False,
                },
                "value": encode_pair_value(
                    metabolite,
                    disease,
                ),
            }],
        },
        {
            "type":     "context",
            "elements": [{
                "type": "mrkdwn",
                "text": MENU_FOOTER,
            }],
        },
    ]


def selected_arms(body) -> set:
    """Which boxes were ticked when the button was pressed.

    A payload with no checkbox state at all means the menu's own defaults - that is the
    restart case, and it must run the whole card rather than nothing. An EMPTY selection is
    a real choice and is honoured: the locked arms still run, and nothing else does.
    """
    state = ((body or {}).get("state") or {}).get("values")
    block = (state or {}).get(ARMS_BLOCK_ID) if isinstance(state, dict) else None
    element = (block or {}).get(ARMS_ACTION_ID) if isinstance(block, dict) else None
    if not isinstance(element, dict) or "selected_options" not in element:
        return set(DEFAULT_ARMS)
    chosen = element.get("selected_options") or []
    return {
        str(option.get("value"))
        for option in chosen
        if isinstance(option, dict) and option.get("value")
    }


def overruled_arms(arms) -> list:
    """The locked arms a reader unticked. They ran anyway, and the thread is told."""
    return [arm for arm in LOCKED_ARMS if arm not in set(arms or ())]


def running_line(
    pair: tuple,
    arms,
) -> str:
    """The one line that goes out BEFORE a run that can take two minutes.

    Silence for 100 s reads as a bot that died. This says what is about to be retrieved,
    names the arm that makes it slow, and repeats the pair as it was understood.
    """
    chosen = set(arms or ())
    running = [menu_line(arm).split(" / ")[0] for arm in MENU_ARMS if arm[0] in chosen]
    wait = "约 2 分钟 / about 2 minutes" if "catalog" in chosen else "约 30-60 秒 / about 30-60 s"
    return (
        f"跑起来了 / running {_escape(pair[0])} x {_escape(pair[1])}: "
        f"{', '.join(running) or '只有被锁定的两臂 / the two locked arms only'}. {wait}."
    )


# ---------------------------------------------------------------- the follow-up buttons
#
# A figure is an answer to a question somebody asked, so it is drawn when somebody asks.
# Each button carries the thread it belongs to, generates once, and says why when there is
# nothing to draw - an empty axis would read as "no effect" and mean "not retrieved".

FIGURE_ACTION_IDS = {
    "forest":      "metabocausal_figure_forest",
    "instruments": "metabocausal_figure_instruments",
    "timeline":    "metabocausal_figure_timeline",
    "skip":        "metabocausal_figure_skip",
}

FOLLOW_UPS = (
    (
        "forest",
        "Forest 图 / Forest plot",
        "每条检索到的 MR 估计的方向与不确定度 / direction & uncertainty of each retrieved "
        "estimate (State A only)",
    ),
    (
        "instruments",
        "工具强度图 / Instruments",
        "有多少强遗传工具 / how many strong instruments (state B focus)",
    ),
    (
        "timeline",
        "Genetic insight 时间线 / timeline",
        "基因上的药：遗传证据哪年出现 vs 临床哪年定论 / when genetics spoke vs when the "
        "clinic decided (needs the genes arm)",
    ),
    (
        "skip",
        "跳过 / Skip",
        "",
    ),
)

FOLLOW_UP_PROMPT = "要哪张图？按一次生成一张 / want a figure? one press, one figure:"

FIGURE_NAMES = {
    "forest":      "forest plot",
    "instruments": "instrument-strength chart",
    "timeline":    "genetic-insight timeline",
}

ALREADY_NOTE = (
    "已经生成过了 / already generated: the {what} for this run is already in this thread."
)
SKIPPED_NOTE = (
    "好 / skipped. The summary, the card and this run's ledger are unchanged; press "
    "another button whenever you want a figure."
)
NO_RUN_NOTE = (
    "这个 thread 的那次运行已经不在内存里了 / this thread's run is no longer in memory "
    "(the shell keeps the last {cap}). Mention me with the pair again and it will re-run - "
    "the ledger of the old run is still on disk."
)
NO_PLOTS_NOTE = (
    "matplotlib is not installed in this shell, so no figure can be drawn. Every number is "
    "still in the summary and in the attached card."
)
NOTHING_TO_DRAW = {
    "forest": (
        "no forest 图 / no forest plot: no retrieved MR estimate in this run carries an "
        "effect size AND its uncertainty, so there is no interval to draw. That is a gap in "
        "what was retrieved, not evidence of no effect."
    ),
    "instruments": (
        "no 工具强度图 / no instrument chart: no exposure dataset came back with a hit "
        "count, so there is no bar to draw. Not evidence that no instrument exists."
    ),
    "timeline": (
        "no 时间线 / no timeline: no drug on this run's effector genes has a clinical report "
        "with a year this project could retrieve. The genes arm must be ticked, the dossier "
        "must hold a drug, and that drug must have a trial ClinicalTrials.gov carries a date "
        "for - a lane drawn on a guessed year would be an invention."
    ),
}
FIGURE_FAILED_NOTE = (
    "the {what} could not be drawn ({detail}). That is a failure of this shell, not a "
    "statement about the biology - every number above is unchanged."
)

# How many threads keep their run in memory. A Socket Mode worker runs for days, and an
# unbounded dict of results (each holding every envelope of a run) is a slow leak.
MAX_THREAD_STATE = 32

_THREAD_STATE = OrderedDict()
_STATE_LOCK = threading.Lock()

# Which (thread, arms) combinations have already been started. Bounded for the same reason
# MAX_THREAD_STATE is: a Socket Mode worker runs for days.
MAX_STARTED_RUNS = 256

_STARTED_RUNS = OrderedDict()

DUPLICATE_RUN_NOTE = (
    "这次已经在跑了 / that run is already under way in this thread - the same arms were "
    "started a moment ago, so this press was ignored rather than run twice. The result "
    "will arrive above."
)


def remember_run(
    thread_ts: str,
    result:    dict,
) -> None:
    """Keep this thread's run, evicting the oldest thread over the cap."""
    key = str(thread_ts or "")
    if not key:
        return
    with _STATE_LOCK:
        _THREAD_STATE.pop(key, None)
        _THREAD_STATE[key] = {
            "result":  result,
            "figures": {},
        }
        while len(_THREAD_STATE) > MAX_THREAD_STATE:
            _THREAD_STATE.popitem(last=False)


def recall_run(thread_ts: str):
    """This thread's run, or None when it was never kept or has been evicted."""
    with _STATE_LOCK:
        entry = _THREAD_STATE.get(str(thread_ts or ""))
        return (entry or {}).get("result")


def forget_runs() -> None:
    """Drop every remembered run AND every start claim.

    A clean slate means both: a caller that clears remembered runs but leaves the claims
    behind would find the next Generate for that thread silently refused. That is also
    what keeps the existing tests honest - each one starts with no claim held."""
    with _STATE_LOCK:
        _THREAD_STATE.clear()
        _STARTED_RUNS.clear()


def claim_run(thread_ts: str, arms) -> bool:
    """True when this press may start a run, False when the same one is already going.

    WHY THIS EXISTS. A Generate press that arrives twice - a double click, a duplicate
    delivery, a retried event - ran the pair twice. `_ACK` is prompt, so Slack's own
    three-second retry is not the usual cause; a second human click is enough. The two
    runs do not interleave, because `_RUN_LOCK` serialises `run_pair`, so the second
    simply starts when the first ends and the thread gets two of everything about two
    minutes apart.

    THE PART THAT IS NOT COSMETIC. Both runs take the same ledger stem, and
    `ledger.start()` truncates: the second run DELETES the first run's evidence file while
    the first run's card is still in the thread pointing at it. A card whose ledger
    describes a different run is exactly what this project's traceability rules exist to
    prevent, so the duplicate has to be stopped before `run_pair`, not tidied up after.

    Keyed on the arms as well as the thread, because pressing Generate again with a
    DIFFERENT set of arms ticked is a real second request, not a stutter.

    Claimed under the lock: two clicks land on two threads of Bolt's pool at once, and a
    check-then-set would let both through."""
    key = (str(thread_ts or ""), tuple(sorted(str(arm) for arm in (arms or ()))))
    with _STATE_LOCK:
        if key in _STARTED_RUNS:
            return False
        _STARTED_RUNS[key] = True
        while len(_STARTED_RUNS) > MAX_STARTED_RUNS:
            _STARTED_RUNS.popitem(last=False)
        return True


def release_run(thread_ts: str, arms) -> None:
    """Let this (thread, arms) be started again.

    Called when a run ends in a way that leaves nothing in the thread - a crash before any
    reply. A finished run is deliberately NOT released: its card is already posted, and a
    second press should be answered rather than silently re-run."""
    key = (str(thread_ts or ""), tuple(sorted(str(arm) for arm in (arms or ()))))
    with _STATE_LOCK:
        _STARTED_RUNS.pop(key, None)


def forget_started_runs() -> None:
    """Drop every claim. For a test, and for a shell that wants a clean slate."""
    with _STATE_LOCK:
        _STARTED_RUNS.clear()


def claim_figure(
    thread_ts: str,
    kind:      str,
) -> bool:
    """True when this caller may draw `kind` for this thread, False when somebody already
    has. Two clicks on one button land on two threads of Bolt's pool at once, so the claim
    is taken under the lock - a check-then-set would upload the same figure twice."""
    with _STATE_LOCK:
        entry = _THREAD_STATE.get(str(thread_ts or ""))
        if entry is None:
            return True
        figures = entry.setdefault("figures", {})
        if figures.get(kind):
            return False
        figures[kind] = True
        return True


def release_figure(
    thread_ts: str,
    kind:      str,
) -> None:
    """Give the claim back after a failure, so a reader can press the button again. A
    figure that was never drawn must not answer "already generated"."""
    with _STATE_LOCK:
        entry = _THREAD_STATE.get(str(thread_ts or ""))
        if entry is not None:
            (entry.get("figures") or {}).pop(kind, None)


STATE_FIGURES = {
    "A": "forest",
    "B": "instruments",
}


def claim_state_figure(
    result:    dict,
    thread_ts: str,
) -> None:
    """The run posts the figure its own state has. Claim that one here, so pressing its
    button answers "already generated" instead of uploading a second copy of the same PNG.

    Claimed only when the file is actually on disk: a State A run whose MR envelope had no
    drawable row posted no forest, and "already generated" would then be false.
    """
    kind = STATE_FIGURES.get(str((result or {}).get("state") or "").strip().upper())
    if not kind or plots is None:
        return
    suffix = {
        "forest":      plots.FOREST_SUFFIX,
        "instruments": plots.INSTRUMENT_SUFFIX,
    }[kind]
    try:
        drawn = (CARDS_DIR / f"{plots.stem_for_result(result)}{suffix}").exists()
    except Exception:                                    # pragma: no cover - odd stem
        return
    if drawn:
        claim_figure(thread_ts, kind)


def encode_figure_value(
    kind:      str,
    thread_ts: str,
) -> str:
    """A follow-up button's payload: which figure, and which thread's run it is about."""
    return _clip(
        f"{kind}|{thread_ts}",
        MAX_ACTION_VALUE_CHARS,
    )


def decode_figure_value(value) -> tuple:
    """(kind, thread_ts), or (None, None) for anything this shell did not write."""
    text = str(value or "")
    kind, separator, thread_ts = text.partition("|")
    if not separator or kind not in FIGURE_ACTION_IDS or not thread_ts.strip():
        return None, None
    return kind, thread_ts.strip()


def build_follow_up_blocks(thread_ts: str) -> list:
    """One section per figure - the explainer on the left, the button on the right - and
    the skip on its own row. The explainer is the whole point: a reader should know what a
    figure will say before spending a click on it."""
    blocks = [{
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": FOLLOW_UP_PROMPT,
        },
    }]

    for kind, label, explainer in FOLLOW_UPS:
        button = {
            "type":      "button",
            "action_id": FIGURE_ACTION_IDS[kind],
            "text":      {
                "type":  "plain_text",
                "text":  _clip(label, MAX_BUTTON_CHARS),
                "emoji": False,
            },
            "value": encode_figure_value(
                kind,
                thread_ts,
            ),
        }
        if explainer:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": _clip(explainer, MAX_BLOCK_CHARS),
                },
                "accessory": button,
            })
        else:
            blocks.append({
                "type":     "actions",
                "elements": [button],
            })
    return blocks


def draw_figure(
    kind:   str,
    result: dict,
) -> str | None:
    """Draw one on-demand figure and return its path, or None when there is nothing to
    draw. Which figure is asked for is the READER's choice, not the state's - a State B
    run may be asked for a forest, and the honest answer is then "no drawable estimate"
    rather than an empty axis."""
    envelopes = (result or {}).get("envelopes") or {}
    stem = plots.stem_for_result(result)
    metabolite = plots.display_name((result or {}).get("metabolite"))
    disease = plots.display_name((result or {}).get("disease"))

    if kind == "forest":
        return plots.plot_forest(
            envelopes.get("mr") or {},
            plots.FOREST_TITLE.format(
                metabolite = metabolite,
                disease    = disease,
            ),
            CARDS_DIR / f"{stem}{plots.FOREST_SUFFIX}",
        )
    if kind == "instruments":
        return plots.plot_instruments(
            envelopes.get("instruments") or {},
            plots.INSTRUMENT_TITLE.format(metabolite=metabolite),
            CARDS_DIR / f"{stem}{plots.INSTRUMENT_SUFFIX}",
        )
    if kind == "timeline":
        return plots.plot_genetic_insight(
            result,
            str(CARDS_DIR),
        )
    return None


# ---------------------------------------------------------------- the Slack handler

def _thread_of(body) -> str:
    """The thread an interaction happened in. The menu is posted INTO the mention's
    thread, so its container carries that thread_ts; the message's own ts is the fallback
    for a menu that somehow landed at top level."""
    container = (body or {}).get("container") or {}
    message = (body or {}).get("message") or {}
    for value in (
        container.get("thread_ts"),
        message.get("thread_ts"),
        container.get("message_ts"),
        message.get("ts"),
    ):
        if str(value or "").strip():
            return str(value).strip()
    return ""


def _channel_of(body) -> str:
    container = (body or {}).get("container") or {}
    channel = (body or {}).get("channel") or {}
    return str(container.get("channel_id") or channel.get("id") or "")


def _ack(ack) -> None:
    """Slack retries an interaction that is not acknowledged within three seconds, and a
    retried Generate is a second run of the same pair. Acked first, always, and a broken
    ack never costs the work that follows it."""
    if ack is None:
        return
    try:
        ack()
    except Exception:                                    # pragma: no cover - Bolt's own ack
        pass


def handle_mention(
    event,
    say,
    logger = None,
    client = None,
) -> None:
    """One app_mention -> the resolution of the pair and the menu, in the same thread.

    Nothing is retrieved here. The pair is parsed, 1A is asked what the two names mean, and
    the menu goes out with every arm pre-ticked - so a misread pair costs a glance instead
    of two minutes, and a reader who only wants one arm can untick the rest before paying
    for them.

    No exception escapes and no token is ever part of a reply. A resolver that is down
    still gets a menu: the lines then say the run will match on the raw strings.
    """
    thread_ts = (event or {}).get("thread_ts") or (event or {}).get("ts")
    stage = "parse"
    try:
        pair = parse_pair((event or {}).get("text") or "")
        if pair is None:
            say(
                text      = USAGE,
                thread_ts = thread_ts,
            )
            return

        stage = "1A resolution"
        preview = resolve_preview(
            pair[0],
            pair[1],
        )

        stage = "menu"
        blocks = build_menu_blocks(
            pair[0],
            pair[1],
            preview,
        )
        text = "\n".join(
            [MENU_HEADER.format(
                metabolite = _plain_name({"query": pair[0]}),
                disease    = _plain_name({"query": pair[1]}),
            )]
            + preview_lines(preview)
            + [MENU_PROMPT]
            + [menu_line(arm) for arm in MENU_ARMS]
        )
        say(
            blocks    = blocks,
            text      = _fit(text),
            thread_ts = thread_ts,
        )
    except Exception as exc:
        detail = type(exc).__name__
        if logger is not None:
            logger.exception(f"app_mention failed at the {stage} stage")
        try:
            say(
                text      = (
                    f"MetaboCausal could not finish: the {stage} stage failed ({detail}). "
                    "No evidence arm has run for this pair - the menu is what starts one - "
                    "so this is a failure of this shell and not a statement about the "
                    "biology. Mention me again to try."
                ),
                thread_ts = thread_ts,
            )
        except Exception:
            print(f"[slack_app] could not reply after a {stage} failure", file=sys.stderr)


def handle_generate(
    ack    = None,
    body   = None,
    say    = None,
    logger = None,
    client = None,
) -> None:
    """The generate button: run the ticked arms and reply exactly as the mention used to.

    The pair comes out of the button's own payload rather than out of memory, so the button
    still works after a restart. A payload this shell did not write is refused - it is text
    that arrived from outside the process.
    """
    _ack(ack)
    thread_ts = _thread_of(body)
    channel = _channel_of(body)
    try:
        action = ((body or {}).get("actions") or [{}])[0]
        pair = decode_pair_value(action.get("value"))
        if pair is None:
            if say is not None:
                say(
                    text      = USAGE,
                    thread_ts = thread_ts or None,
                )
            return

        arms = selected_arms(body)
        # Claimed BEFORE run_pair, not after. A duplicate press that got this far would
        # truncate the first run's ledger while its card is still in the thread citing it.
        if not claim_run(thread_ts, arms):
            if say is not None:
                say(
                    text      = DUPLICATE_RUN_NOTE,
                    thread_ts = thread_ts or None,
                )
            return

        try:
            run_and_reply(
                pair,
                say,
                thread_ts,
                channel,
                arms,
                logger,
                client,
            )
        except BaseException:
            # Nothing reached the thread, so the press should be repeatable. run_and_reply
            # handles its own failures and returns normally; this is for the case where it
            # could not even do that.
            release_run(thread_ts, arms)
            raise
    except Exception as exc:                             # pragma: no cover - last resort
        if logger is not None:
            logger.exception("the generate button failed")
        if say is not None:
            try:
                say(
                    text      = (
                        f"MetaboCausal could not start that run ({type(exc).__name__}), "
                        "which is a failure of this shell and not a statement about the "
                        "biology."
                    ),
                    thread_ts = thread_ts or None,
                )
            except Exception:
                print("[slack_app] could not reply after a button failure", file=sys.stderr)


def handle_arms(
    ack  = None,
    body = None,
    **ignored,
) -> None:
    """Ticking a box changes nothing until Generate is pressed - but Slack still needs the
    acknowledgement, or it shows the reader a warning triangle on a menu that is fine."""
    _ack(ack)


def handle_figure(
    ack    = None,
    body   = None,
    say    = None,
    logger = None,
    client = None,
) -> None:
    """One follow-up button: draw that figure once, upload it into the thread, or say why
    there is nothing to draw.

    Three answers and no fourth: the figure, "already generated" (a second click never
    posts a second copy), or the sentence that says what was missing. A figure that cannot
    be drawn is never replaced by an empty one.
    """
    _ack(ack)
    thread_ts = _thread_of(body)
    channel = _channel_of(body)

    def reply(text):
        if say is not None:
            say(
                text      = text,
                thread_ts = thread_ts or None,
            )

    try:
        action = ((body or {}).get("actions") or [{}])[0]
        kind, key = decode_figure_value(action.get("value"))
        if kind is None:
            return
        if kind == "skip":
            reply(SKIPPED_NOTE)
            return

        result = recall_run(key)
        if result is None:
            reply(NO_RUN_NOTE.format(cap=MAX_THREAD_STATE))
            return
        if plots is None:
            reply(NO_PLOTS_NOTE)
            return
        if not claim_figure(key, kind):
            reply(ALREADY_NOTE.format(what=FIGURE_NAMES.get(kind, kind)))
            return

        try:
            with _RUN_LOCK:
                path = draw_figure(
                    kind,
                    result,
                )
        except Exception as exc:
            release_figure(key, kind)
            if logger is not None:
                logger.exception(f"the {kind} figure could not be drawn")
            reply(FIGURE_FAILED_NOTE.format(
                what   = FIGURE_NAMES.get(kind, kind),
                detail = type(exc).__name__,
            ))
            return

        if not path:
            release_figure(key, kind)
            reply(NOTHING_TO_DRAW.get(kind, NOTHING_TO_DRAW["forest"]))
            return

        if client is None or not channel:
            return
        try:
            with _RUN_LOCK:
                _upload_one(
                    client,
                    channel,
                    thread_ts,
                    Path(path),
                    FIGURE_TITLE.format(
                        metabolite = _plain_name(result.get("metabolite")),
                        disease    = _plain_name(result.get("disease")),
                    ),
                )
        except Exception as exc:
            if logger is not None:
                logger.warning(f"[slack_app] the {kind} figure was not uploaded: {type(exc).__name__}")
            reply(_upload_note(exc, f"the {FIGURE_NAMES.get(kind, kind)}"))
    except Exception as exc:                             # pragma: no cover - last resort
        if logger is not None:
            logger.exception("a follow-up button failed")
        try:
            reply(
                f"MetaboCausal could not draw that ({type(exc).__name__}), which is a "
                "failure of this shell and not a statement about the biology."
            )
        except Exception:
            print("[slack_app] could not reply after a figure failure", file=sys.stderr)


def run_and_reply(
    pair,
    say,
    thread_ts,
    channel = None,
    arms    = None,
    logger  = None,
    client  = None,
) -> None:
    """One pair -> one summary, one card, (State A or B) one figure and the follow-up
    buttons, all in the same thread. Every stage is named, so a failure says which stage
    failed instead of dying silently or leaking a traceback into the channel. No exception
    escapes, and no token is ever part of a reply.

    `client` is Bolt's WebClient, injected by name like `say` and `logger`. It is what
    uploads the two files; without it the summary still goes out, which is why it has a
    default and why the attachment stage is the last thing this does. The summary is posted
    BEFORE either upload is attempted, so the numbers are in the thread before anything
    that can fail on a scope.

    `_RUN_LOCK` is held across the whole pipeline call: Bolt runs listeners on a thread
    pool, and one run at a time is what keeps each card's ledger count its own."""
    stage = "arms"
    result = None
    arms = set(arms if arms is not None else DEFAULT_ARMS)
    try:
        preamble = [running_line(pair, arms)]
        if overruled_arms(arms):
            preamble.append(LOCKED_ARMS_NOTE)
        say(
            text      = "\n".join(preamble),
            thread_ts = thread_ts,
        )

        stage = "pipeline"
        with _RUN_LOCK:
            # Only two arms are switchable. The MR and instrument arms are what
            # classify_state is a pure function of, so they always run - and `arms` is
            # reported back to the thread above rather than silently reinterpreted here.
            result = pipeline.run_pair(
                pair[0],
                pair[1],
                skip_catalog = "catalog" not in arms,
                skip_genes   = "genes" not in arms,
                stem_prefix  = STEM_PREFIX,
            )
            # Read the ledger while this run still owns it. Two mentions of the SAME pair
            # get the same stem, so the moment the lock is released the next run's
            # `ledger.start` truncates the file this card's section 11 is about to be
            # rendered from - and the digest would then describe somebody else's run under
            # a sentence promising it was rendered from the envelopes above.
            if isinstance(result, dict):
                result[render.LEDGER_ENTRIES_KEY] = render.snapshot_ledger(result)

        stage = "formatting"
        card = format_card(result)
        try:
            blocks = build_blocks(result)
        except Exception:
            # A layout bug must never cost a reader the numbers. The card still holds
            # every one of them, so fall back to the text-only reply this shell shipped
            # with rather than posting nothing.
            blocks = None
            if logger is not None:
                logger.exception("block layout failed; replying with the text card only")

        stage = "reply"
        posted = False
        if blocks:
            try:
                say(
                    blocks    = blocks,
                    text      = card,
                    thread_ts = thread_ts,
                )
                posted = True
            except Exception:
                # Slack REJECTING the blocks is a different failure from building them
                # badly, and it used to lose the whole card. One text-only retry, then the
                # error line - never silence over a run that finished.
                if logger is not None:
                    logger.exception("Slack refused the blocks; retrying with text only")
        if not posted:
            say(
                text      = card,
                thread_ts = thread_ts,
            )

        stage = "attachments"
        # One message, however many attachments failed. Each failure names its own file,
        # because "the card" and "the figure" are not interchangeable to a reader - but a
        # thread gets one explanation, not one per file.
        #
        # Serialised for the same reason the run is: two mentions of one pair write the
        # same cards/card_<stem>.md and cards/<stem>_*.png, so a file must not be
        # overwritten between being written and being uploaded.
        stage = "section 9"
        # AFTER the summary is already in the thread. The evidence does not wait on a
        # model: a reader has the verdict and every number before this is even attempted,
        # and a slow or missing model costs a paragraph rather than the answer.
        interpretation, section_nine_note = write_section_nine(result, logger)

        stage = "attachments"
        with _RUN_LOCK:
            notes = attach_artifacts(
                result,
                client,
                channel,
                thread_ts,
                logger,
                interpretation,
            )
        if notes:
            say(
                text      = "\n".join(notes),
                thread_ts = thread_ts,
            )
        # Said separately, and deliberately NOT folded into `notes`. Those are artifact
        # failures, and an empty `notes` is what tells the next step that every file
        # landed, so the state figure may be marked as already posted. An interpretation
        # that did not land says nothing about whether the card and the figure uploaded -
        # putting it in that list made a missing paragraph suppress the figure claim, and
        # the button then posted a second copy of a figure the run had already attached.
        if section_nine_note:
            say(
                text      = section_nine_note,
                thread_ts = thread_ts,
            )

        stage = "follow-up"
        # Remembered BEFORE the buttons are posted: a reader who clicks the instant the
        # message lands must find the run, not an empty slot.
        remember_run(thread_ts, result)
        if not notes:
            claim_state_figure(result, thread_ts)
        follow_up_text = "\n".join(
            [FOLLOW_UP_PROMPT]
            + [f"{label} - {explainer}".strip(" -") for _kind, label, explainer in FOLLOW_UPS]
        )
        try:
            say(
                blocks    = build_follow_up_blocks(thread_ts),
                text      = follow_up_text,
                thread_ts = thread_ts,
            )
        except Exception:
            # The buttons are an offer, not the evidence. Slack refusing them costs the
            # offer and nothing else, so this never becomes "MetaboCausal could not
            # finish" over a run whose card is already in the thread.
            if logger is not None:
                logger.exception("Slack refused the follow-up buttons; offering them as text")
            try:
                say(
                    text      = follow_up_text,
                    thread_ts = thread_ts,
                )
            except Exception:
                if logger is not None:
                    logger.exception("the follow-up offer could not be posted at all")
    except Exception as exc:
        detail = type(exc).__name__
        if logger is not None:
            logger.exception(f"the {stage} stage failed")
        # "Nothing was retrieved for this pair" is the one sentence this project treats as
        # a red line, and it is FALSE the moment run_pair has returned: a Slack rate limit
        # or a rejected block at the formatting or reply stage costs the delivery, not the
        # retrieval, and the ledger is already on disk. Only parse and pipeline may say
        # nothing was retrieved.
        if stage in ("attachments", "follow-up"):
            aftermath = "The summary above still stands and every number in it is unchanged"
        elif result is not None:
            aftermath = (
                "The retrieval finished and its ledger is on disk "
                f"(cards/{_ledger_name(result)}); this shell could not deliver it"
            )
        else:
            aftermath = "Nothing was retrieved for this pair"
        try:
            say(
                text      = (
                    f"MetaboCausal could not finish: the {stage} stage failed "
                    f"({detail}). {aftermath}, which is a failure of this shell "
                    f"and not a statement about the biology."
                ),
                thread_ts = thread_ts,
            )
        except Exception:
            print(f"[slack_app] could not reply after a {stage} failure", file=sys.stderr)


def build_app(bot_token: str):
    """The Bolt app with the mention, the menu and the four buttons registered. Built here
    rather than at import time so `import slack_app` needs no token and contacts nothing.

    Every interactive component is registered: an action Slack delivers and nobody listens
    for is logged as an unhandled request and leaves the reader looking at a warning on a
    menu that worked."""
    app = App(token=bot_token)
    app.event("app_mention")(handle_mention)
    app.action(ARMS_ACTION_ID)(handle_arms)
    app.action(GENERATE_ACTION_ID)(handle_generate)
    for action_id in FIGURE_ACTION_IDS.values():
        app.action(action_id)(handle_figure)
    return app


def missing_tokens() -> list:
    """Which of the two token variables are not set. Names only - a value is never read
    into a message, a log line or a return value."""
    _common.load_env()
    return [name for name in (BOT_TOKEN_VAR, APP_TOKEN_VAR) if not os.environ.get(name)]


def main() -> int:
    """0 only when the shell actually connected. Both refusal paths return 1, so a
    supervisor, a Makefile or a demo-morning `python slack_app.py && echo up` can tell
    "connected" from "never started"."""
    if App is None:
        print("slack-bolt is not installed, so the Socket Mode shell cannot start.")
        print("Install it with: python -m pip install slack-bolt")
        return 1

    missing = missing_tokens()
    if missing:
        print(f"{' and '.join(missing)} not set, so the Socket Mode shell cannot start.")
        print(
            "Put both in the .env two levels above this repo - SLACK_BOT_TOKEN=xoxb-... "
            "(scopes app_mentions:read, chat:write, files:write) and "
            "SLACK_APP_TOKEN=xapp-... (scope connections:write) - then run: "
            "python slack_app.py"
        )
        return 1

    app = build_app(os.environ[BOT_TOKEN_VAR])
    print(
        f"MetaboCausal Slack shell: connecting over Socket Mode "
        f"({SOCKET_MODE_CLIENT} websocket). Ctrl-C to stop."
    )
    if SOCKET_MODE_CLIENT == "built-in":
        print(
            "  Note: slack_sdk's built-in websocket client is in use. On a network that "
            "cuts long-lived connections it logs repeated 'Failed to check the state of "
            "sock' warnings and reconnects. `pip install websocket-client` switches to "
            "the more robust implementation."
        )
    SocketModeHandler(app, os.environ[APP_TOKEN_VAR]).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())

