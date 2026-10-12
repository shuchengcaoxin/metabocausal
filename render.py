"""The full evidence card, built BY CODE from one run's envelopes and its ledger.

    import pipeline, render
    result = pipeline.run_pair("urate", "gout")
    text   = render.render_card(result)          # the 11-section markdown card
    name   = render.card_filename(result)        # "card_urate_gout.md"

THE DIVISION OF LABOUR THIS FILE ENFORCES

    tool envelopes  ->  sections 1, 3, 4, 5, 6, 8, 10, 11      (here, mechanical)
    classify.py     ->  section 2 (state + reason, verbatim)    (a pure function)
    the model (1F)  ->  section 9, and section 9 only           (not wired in yet)

Nothing a model writes can move a number in this card, because no model is in this
path. Section 9 renders one fixed sentence until 1F lands; it never renders invented
prose, and there is no argument to this function through which prose could arrive.

WORDING DISCIPLINE (the same rules slack_app.py is held to, tested in
tests/test_render.py)

  "retrieved", never "computed" - this project retrieves published MR estimates and
  pre-computed instrument counts. It fits nothing. The word "computed" appears on a
  card only inside a denial ("not computed here") or inside "pre-computed".

  an empty arm reads "not available in this snapshot - not evidence of no effect".
  A trait absent from a 2020 snapshot is a gap in what could be retrieved; printing it
  as a negative result is the one failure this project exists to prevent.

  an ERROR is never rendered as a source with no record. "the request failed" and
  "the source holds no row" are different sentences and every arm says which happened.

  every cap and every truncation is printed. A silent truncation is worse than an
  error: it tells a reader 6 datasets were looked at when 22 measure the metabolite.

  nsnp absent from older cached MR-EVE rows renders
  "n/a (not returned by this snapshot)" and never 0.

  moescore is labelled "MR-EVE mixture-of-experts score (0-1), not a p-value" every
  time it is printed, because a number between 0 and 1 next to an effect size is read
  as a p-value by every reader who has not been told otherwise.

  a drug's clinical stage stays attached to the report it came from. A drug approved
  for another disease must never read as approved for the disease that was asked about.

  gnomAD constraint is "population intolerance to loss", never clinical safety.

  effect sizes and standard errors print to 4 significant figures; p-values print in
  scientific notation, and a p that underflowed to 0 in the source prints
  "<1e-300 (reported 0)" - never "0.0", which would read as certainty.

SECTION 11 NEVER DESCRIBES SOMEBODY ELSE'S RUN. Two mentions of one pair share a ledger
filename, so the file a result names can already have been truncated and rewritten by
the next run by the time this renders. A caller that still holds its run lock calls
`snapshot_ledger(result)` and puts the lines in `result["ledger_entries"]`; section 11
renders from that and never opens the file. When it does read a file, it compares the
tools in it against the run's own envelopes and falls back - out loud - if they differ.

NEVER RAISES. slack_app.py renders inside a Bolt listener, and a renderer that throws
takes the whole reply with it. Every section is built inside its own guard: a section
that fails says so, in the one place it failed, and the other ten still print.

STDLIB ONLY. plots.py, slack_app.py and (later) agent.py all import this file; it
imports no tool, no HTTP client and no third-party package, so importing it costs
nothing and contacts nothing.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

LEDGER_SUFFIX = ".ledger.jsonl"

# The key a caller may put in its result to hand this renderer the ledger lines it
# already read, instead of having the file re-opened here. slack_app.py fills it inside
# the run lock: two mentions of the same pair share one ledger filename, so a file read
# after the lock is released can be the NEXT run's file.
LEDGER_ENTRIES_KEY = "ledger_entries"

# This table and the forest plot are sorted the same way (smallest retrieved p-value
# first) and capped at the same number of rows, but they do not always hold the same
# rows: the figure can only draw a row that carries a finite b AND a finite se, and a row
# missing either is printed here and counted under the table as absent from the figure.
# The two artifacts never disagree about a number; when they differ about which rows
# appear, the card says so rather than leaving a reader to notice.
MAX_ESTIMATE_ROWS = 15
MAX_SYNONYMS_SHOWN = 8
MAX_MATCHES_SHOWN = 8
MAX_GENES_SHOWN = 20
MAX_RSIDS_PER_GENE = 4
MAX_DRUGS_SHOWN = 10
MAX_REPORTS_PER_DRUG = 5
MAX_TOP_DISEASES_SHOWN = 5
MAX_MECHANISMS_SHOWN = 5
MAX_GEM_CANDIDATES_SHOWN = 8
MAX_GEM_REACTIONS_SHOWN = 5
# Section 11 prints host + path in full and cuts only the query string.
MAX_QUERY_CHARS = 80

SECTIONS = (
    "Requested pair and resolved IDs",
    "Evidence state and one-line verdict",
    "Metabolite -> disease genetic evidence",
    "Instruments and feasibility",
    "Effector genes by source",
    "Gene dossiers",
    "Via-enzyme protein evidence",
    "Caveats",
    "Reasoning",
    "Next action",
    "Provenance",
)

STATE_LABELS = {
    "A": "retrieved MR",
    "B": "analysis-ready",
    "C": "evidence gap",
}

# 1F writes section 9 and nothing else. Until it lands this exact sentence is what
# stands there: a card that invents a reasoning paragraph is worse than a card with
# an empty one, because the empty one cannot be quoted.
PENDING_REASONING = "Model reasoning pending integration (section 1F)."

EMPTY_ARM = "not available in this snapshot - not evidence of no effect"
NOT_RETRIEVED = "not retrieved"
NSNP_ABSENT = "n/a (not returned by this snapshot)"

# Effect sizes and standard errors print to this many significant figures, here and on
# every figure plots.py draws - plots.fmt_sig calls `format_sig` below.
SIG_FIGURES = 4
# A p that underflowed double precision in the source. The bound is the same string on
# both surfaces; only the card adds what the source actually said.
PVALUE_UNDERFLOW = "<1e-300"
PVALUE_UNDERFLOW_REPORTED = f"{PVALUE_UNDERFLOW} (reported 0)"

MOESCORE_NOTE = (
    "moescore is the MR-EVE mixture-of-experts score (0-1) for how appropriate the "
    "automatically chosen method was. It is NOT a p-value and not a confidence that "
    "the effect is causal."
)
NSNP_NOTE = (
    "nsnp is shown when retrieved from the source; a missing value prints as "
    f"\"{NSNP_ABSENT}\" rather than as a number."
)
SCALE_NOTE = (
    "Effect sizes are per unit of each exposure dataset's OWN scale and are not "
    "comparable across rows; the exposure and outcome dataset ids are printed beside "
    "every number for exactly that reason."
)
F_NOTE = (
    "F = (beta/se)^2 on the retrieved hit, arithmetic on retrieved numbers; weak means "
    "F < 10. It is not the first-stage F of a fitted MR, because no MR was fitted here, "
    "and it may be upward-biased by winner's curse. "
    "These are the feasibility arm's instruments, NOT necessarily the instruments behind "
    "the retrieved MR estimates in section 3; these F statistics do not describe those MR rows."
)
GNOMAD_NOTE = (
    "gnomAD constraint measures population intolerance to loss. It is not clinical "
    "safety and says nothing about tolerance of pharmacological inhibition."
)
DRUG_STAGE_NOTE = (
    "Clinical stage stays attached to the report that carries it. A drug-level maximum "
    "stage is that drug's maximum across every indication it has a report for, and is "
    "never a stage for the disease that was asked about."
)
SECTION_7_SCOPE = (
    "Human-GEM biochemical context was not assessed in this run. This is not evidence "
    "that the metabolite has no reactions, enzymes or transporters."
)

RENDER_FAILURE = (
    "This section could not be rendered ({detail}). That is a failure of the renderer, "
    "not a statement about the biology; the run's envelopes are unchanged and the "
    "ledger named in section 11 still holds everything that was retrieved."
)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
# OpenGWAS stores some author names with its own broken non-ASCII escapes
# ("D<U+00F6>nerta<U+015F> HM"). They are printed exactly as the source wrote them and
# flagged, never silently repaired - the damage is upstream and a reader should see it.
_BROKEN_ESCAPE = re.compile(r"<U\+[0-9A-Fa-f]{4}>|<[0-9a-f]{2}>")


# ---------------------------------------------------------------- small formatters

def _text(value) -> str:
    """One line of plain text. Newlines inside a retrieved string would break both a
    markdown table row and a Slack block, so every value is flattened on the way in."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _cell(value) -> str:
    """`_text`, plus the one escape a markdown table needs. Applied once, by `_table`
    alone: a name carrying a pipe reached the card as `urate\\|gout` while both the
    field formatter and the table escaped it."""
    return _text(value).replace("|", "\\|")


def _float(value):
    """float(value) or None. Numbers can arrive as strings: ledger.record serialises
    with default=str, so a numpy float comes back from a ledger as "1.3665"."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def format_sig(
    number: float,
    digits: int = SIG_FIGURES,
) -> str:
    """A real, finite number to EXACTLY `digits` significant figures, trailing zeros kept.

    Not `f"{number:.4g}"`: %g strips trailing zeros, so a b of 1.38039018070005 prints as
    "1.38" and an se of 0.022697 as "0.0227" - three figures claimed where the source gave
    four. Rounding happens first (9.9999 -> 10.00) and the switch to exponential notation
    follows %g's own rule, so ordinary numbers still look ordinary.

    The caller has already established that `number` is finite (`_float` here,
    `plots.finite` there). plots.fmt_sig calls this function, so one retrieved number
    cannot print one way on the card and another way on the figure beside it.
    """
    if number == 0:
        return "0"
    rounded = float(f"{number:.{digits - 1}e}")
    exponent = math.floor(math.log10(abs(rounded)))
    if exponent < -4 or exponent >= digits:
        return f"{number:.{digits - 1}e}"
    return f"{number:.{max(digits - 1 - exponent, 0)}f}"


def _effect(value) -> str:
    """An effect size or a standard error, to 4 significant figures."""
    number = _float(value)
    return NOT_RETRIEVED if number is None else format_sig(number)


def _pvalue(value) -> str:
    """A p-value in scientific notation. A p that underflowed to zero in the source is
    the one number this card must never print as 0.0: rendered that way it reads as
    certainty, when all it means is that the source ran out of double precision.

    slack_app.py calls this for the p in its summary, so the thread and the card attached
    to it cannot state two different things about the same retrieved number.
    """
    number = _float(value)
    if number is None:
        return NOT_RETRIEVED
    if number == 0.0:
        return PVALUE_UNDERFLOW_REPORTED
    if number < 1e-300:
        return PVALUE_UNDERFLOW
    return f"{number:.2e}"


def _count(value) -> str:
    number = _float(value)
    if number is None:
        return NOT_RETRIEVED
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:.4g}"


def _nsnp(value) -> str:
    number = _float(value)
    return NSNP_ABSENT if number is None else _count(number)


def _or_unknown(value) -> str:
    """A string field the source may simply not record. "None" is a Python repr, not a
    sentence a reader can act on."""
    text = _text(value)
    return text if text else "not recorded by this source"


def _showing(shown, total) -> str:
    """The cap line. Every list on this card that was cut says so, with both numbers."""
    return f"showing {_count(shown)} of {_count(total)}"


def _table(headers, rows) -> list:
    """One markdown table. Returns [] for no rows, so a caller can print its own
    sentence instead of an empty table."""
    if not rows:
        return []
    lines = [
        "| " + " | ".join(_cell(head) for head in headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(value) for value in row) + " |")
    return lines


def _bullets(items) -> list:
    return [f"- {item}" for item in items if str(item).strip()]


# ---------------------------------------------------------------- envelope access

def _status(envelope) -> str:
    if not isinstance(envelope, dict):
        return "absent"
    status = envelope.get("status")
    return status if isinstance(status, str) and status.strip() else "absent"


def _data(envelope) -> dict:
    data = envelope.get("data") if isinstance(envelope, dict) else None
    return data if isinstance(data, dict) else {}


def _rows(envelope, key) -> list:
    block = _data(envelope).get(key)
    return [row for row in block if isinstance(row, dict)] if isinstance(block, list) else []


def _caveats(envelope) -> list:
    block = envelope.get("caveats") if isinstance(envelope, dict) else None
    return [str(item) for item in block if str(item).strip()] if isinstance(block, list) else []


def _provenance_line(envelope, tool) -> str:
    """The one line that says where an arm's numbers came from and when. Printed at the
    head of every evidence section, so no table on this card floats free of its source."""
    source = _or_unknown(_data(envelope).get("source") or envelope.get("source"))
    stamp = _or_unknown(envelope.get("retrieved_at"))
    return (
        f"Source: {source} - tool `{tool}` - status `{_status(envelope)}` - "
        f"retrieved at {stamp}."
    )


def _error_detail(envelope) -> str:
    detail = _data(envelope).get("error")
    return f" The source reported: {_text(detail)}" if detail else ""


def _core_envelopes(result) -> list:
    """(key, tool name, envelope) for the non-dossier arms, in the order run_pair calls
    them. A key the run never reached is simply absent from the result."""
    envelopes = result.get("envelopes") if isinstance(result.get("envelopes"), dict) else {}
    named = (
        ("mr",          "get_mr_result"),
        ("instruments", "get_mqtl_instruments"),
        ("outcomes",    "find_outcome_datasets"),
        ("catalog",     "get_gwas_catalog"),
        ("coloc",       "get_colocalisation"),
        ("gem",         "map_metabolite_to_genes_gem"),
    )
    found = []
    for key, tool in named:
        envelope = envelopes.get(key)
        if envelope is not None:
            found.append((key, tool, envelope))
    return found


def _dossier(result) -> dict:
    envelopes = result.get("envelopes") if isinstance(result.get("envelopes"), dict) else {}
    dossier = envelopes.get("dossier")
    return dossier if isinstance(dossier, dict) else {}


def _envelope(result, key):
    envelopes = result.get("envelopes") if isinstance(result.get("envelopes"), dict) else {}
    return envelopes.get(key)


def _entity(result, side) -> dict:
    entity = result.get(side)
    return entity if isinstance(entity, dict) else {}


# ---------------------------------------------------------------- 1. requested pair

def _synonym_line(entity, side) -> str:
    synonyms = [str(item) for item in (entity.get("synonyms") or []) if str(item).strip()]
    if not synonyms:
        return f"Synonyms handed to the {side}-side tools: none."
    shown = ", ".join(_text(item) for item in synonyms[:MAX_SYNONYMS_SHOWN])
    tail = ""
    if len(synonyms) > MAX_SYNONYMS_SHOWN:
        tail = f" ({_showing(MAX_SYNONYMS_SHOWN, len(synonyms))})"
    return (
        f"Synonyms handed to the {side}-side tools ({_count(len(synonyms))}): "
        f"{shown}{tail}. Every match in this card is made on these strings, "
        f"case-insensitively, not on the name as it was typed."
    )


def _resolution_cell(entity) -> str:
    if entity.get("resolved"):
        origin = _text(entity.get("resolved_from")) or "the pre-resolved sample"
        return f"resolved from sample entry `{origin}`"
    return (
        "NOT in the pre-resolved sample; matching used the raw input string only "
        "(the 1A resolver lands separately)"
    )


def _section_pair(result) -> list:
    metabolite = _entity(result, "metabolite")
    disease = _entity(result, "disease")
    rows = [
        [
            "Metabolite (exposure)",
            _or_unknown(metabolite.get("query")),
            _or_unknown(metabolite.get("label")),
            _text(metabolite.get("id")) or "no id in the pre-resolved sample",
            _resolution_cell(metabolite),
        ],
        [
            "Disease (outcome)",
            _or_unknown(disease.get("query")),
            _or_unknown(disease.get("label")),
            _text(disease.get("id")) or "no id in the pre-resolved sample",
            _resolution_cell(disease),
        ],
    ]
    headers = ["Side", "Asked for", "Resolved label", "Id", "Resolution"]
    lines = _table(headers, rows)
    lines.append("")
    lines.append(_synonym_line(metabolite, "metabolite"))
    lines.append("")
    lines.append(_synonym_line(disease, "disease"))
    lines.append("")
    lines.append(
        "One direction only: the metabolite is queried as the EXPOSURE and the disease "
        "as the OUTCOME. Nothing on this card is a statement about the reverse direction."
    )
    return lines


# ---------------------------------------------------------------- colocalisation (a qualifier)
#
# A retrieved colocalisation never moves the state. It is appended to the verdict line as
# a qualifier, printed in full under section 3, and joined to the effector genes in
# sections 5 and 6 - and all three places say "retrieved", because Open Targets ran the
# colocalisation and this project read it.

def _coloc(result):
    return _envelope(result, "coloc")


def _coloc_hits(result, key) -> list:
    return _rows(_coloc(result), key)


def _locus(hit) -> str:
    """chr:position, with the credible set's index variant when the source names one."""
    where = f"chr{_text(hit.get('chromosome'))}:{_text(hit.get('position'))}"
    variant = _text(hit.get("variant_id"))
    return f"{where} ({variant})" if variant else where


def _h4(value) -> str:
    """A posterior probability, to 4 significant figures. Never rounded to "1" - an H4 the
    source returned as 1 prints as 1.000, because the reader must see how many figures the
    source actually gave."""
    number = _float(value)
    return NOT_RETRIEVED if number is None else format_sig(number)


def _coloc_hit_sentence(hit) -> str:
    clpp = (
        f", CLPP = {_h4(hit.get('clpp'))}"
        if _float(hit.get("clpp")) is not None else ""
    )
    return (
        f"H4 = {_h4(hit.get('h4'))}{clpp}, {_or_unknown(hit.get('method'))}, {_locus(hit)}, "
        f"{_text(hit.get('locus_study_id'))} x {_text(hit.get('partner_study_id'))} "
        f"({_text(hit.get('partner_trait'))})"
    )


def _coloc_qualifier(result) -> str:
    """The clause appended to the verdict line. One sentence, four possible shapes, and
    none of them is ever "no colocalisation": an arm that did not run, a request that
    failed and a source with no published row are three different statements."""
    envelope = _coloc(result)
    missing_layer = (
        " Any retrieved MR is retained without this additional supporting layer; "
        "colocalisation is not an inclusion requirement."
    )
    if envelope is None:
        return (
            "Colocalisation: not queried in this run, so nothing here says whether the "
            "two GWAS share a causal variant." + missing_layer
        )
    if _status(envelope) == "error":
        return (
            "Colocalisation: the request failed, so nothing was retrieved about a shared "
            f"causal variant - no information, not an absent colocalisation."
            f"{_error_detail(envelope)}" + missing_layer
        )

    hits = _rows(envelope, "metabolite_hits")
    if not hits:
        return (
            "Colocalisation: none retrieved for this pair in Open Targets, which is not "
            "evidence against a shared causal variant." + missing_layer
        )

    best = hits[0]
    total = _count(_data(envelope).get("n_metabolite_hits") or len(hits))
    state = _text(result.get("state"))
    mr_note = " No MR estimate was retrieved in this run." if state == "B" else ""
    support = (
        "Higher source H4 gives greater support for a shared causal signal under the source model. "
        if _float(best.get("h4")) is not None else
        "H4 was not reported; a reported CLPP remains a separate source colocalisation metric. "
    )
    if _float(best.get("clpp")) is not None:
        support += "CLPP is not H4; interpret it under its reported method. "
    return (
        f"Retrieved colocalisation assessment ({_coloc_hit_sentence(best)}); "
        f"{total} retrieved assessment(s) for this pair. {support}"
        f"This is an additional evidence layer, not an MR inclusion requirement; "
        f"retrieval alone does not establish a shared causal variant. Retrieved from Open Targets, "
        f"not computed here, and it did not move the state.{mr_note}"
    )


def _coloc_studies_line(envelope) -> str:
    """Which disease studies were opened, with how much of each was read. A card that
    prints an H4 without naming the study it came from is not auditable."""
    studies = _rows(envelope, "studies_searched")
    if not studies:
        return "No disease study was opened by this arm."
    shown = "; ".join(
        f"{_text(row.get('id'))} ({_text(row.get('trait'))}, "
        f"{_count(row.get('n_cases'))} case(s), "
        f"{_count(row.get('n_sets_examined'))} of "
        f"{_count(row.get('n_sets_in_source'))} credible set(s) read)"
        for row in studies
    )
    data = _data(envelope)
    return (
        f"Disease study(ies) searched ({_count(len(studies))} of "
        f"{_count(data.get('n_candidate_studies'))} mapped to this disease, largest case "
        f"count first): {shown}."
    )


def _coloc_rows_table(hits) -> list:
    headers = [
        "Locus",
        "H4",
        "H3",
        "CLPP",
        "Method",
        "Partner study",
        "Partner trait",
        "Colocalising variants",
    ]
    rows = [
        [
            _locus(hit),
            _h4(hit.get("h4")),
            _h4(hit.get("h3")),
            _effect(hit.get("clpp")),
            _or_unknown(hit.get("method")),
            _text(hit.get("partner_study_id")),
            _or_unknown(hit.get("partner_trait")),
            _count(hit.get("n_coloc_variants")),
        ]
        for hit in hits
    ]
    return _table(headers, rows)


def _coloc_block(result) -> list:
    """The colocalisation block of section 3: the retrieved metabolite colocalisations of
    this pair, the studies they came from, and every cap the retrieval worked under."""
    envelope = _coloc(result)
    lines = ["**Retrieved colocalisation (Open Targets)**", ""]
    if envelope is None:
        lines.append(
            "`get_colocalisation` did not run in this run, so nothing was retrieved about "
            "a shared causal variant. That is a gap in what was queried, not a finding."
        )
        return lines

    lines.append(_provenance_line(envelope, "get_colocalisation"))
    lines.append("")
    if _status(envelope) == "error":
        lines.append(
            "The colocalisation request failed, so nothing was retrieved for this pair: "
            "the request failed, which is not the same statement as the source holding no "
            f"colocalisation.{_error_detail(envelope)}"
        )
        return lines

    data = _data(envelope)
    hits = _rows(envelope, "metabolite_hits")
    total = data.get("n_metabolite_hits")
    total = len(hits) if _float(total) is None else int(_float(total))

    lines.append(_coloc_studies_line(envelope))
    lines.append("")
    if not hits:
        lines.append(
            "Colocalisation with a GWAS of this metabolite: none retrieved in this Open "
            "Targets release within the caps below. An absent colocalisation row is NOT "
            "evidence against a shared causal variant, and it is not a null result."
        )
        lines.append("")
        lines.extend(_bullets(_text(caveat) for caveat in _caveats(envelope)))
        return lines

    lines.append(
        f"{_count(total)} colocalisation(s) retrieved between a credible set of those "
        f"studies and a GWAS of this metabolite, strongest H4 first. Retrieved, not "
        f"computed here."
    )
    lines.append("")
    lines.extend(_coloc_rows_table(hits))
    lines.append("")
    if total > len(hits):
        lines.append(
            f"Table capped: {_showing(len(hits), total)} retrieved colocalisation(s), "
            "sorted by retrieved H4 (largest first). The rest are in the ledger named in "
            "section 11."
        )
    matched = sorted({_text(hit.get("matched_synonym")) for hit in hits if hit.get("matched_synonym")})
    if matched:
        lines.append(
            "Partner traits were matched on these metabolite spellings, as whole words: "
            + ", ".join(matched) + "."
        )
    lines.append("")
    lines.extend(_bullets([
        "H4 is the source's own posterior probability that the two studies share ONE "
        "causal variant at the locus, under the method named on each row. It is not a "
        "p-value, not an effect size and not proof of causality.",
        "Each row is a TWO-WAY colocalisation published by the source. Two rows at one "
        "locus are two two-way statements, never one three-way "
        "mQTL / eQTL / disease claim.",
        "A colocalisation does not establish direction. It says the same variant drives "
        "both signals, not that the metabolite moves the disease.",
    ]))
    return lines


def _coloc_gene_hits(result) -> dict:
    """{gene symbol: [retrieved QTL colocalisations]}, strongest first, from this run's
    colocalisation envelope."""
    grouped = {}
    for hit in _coloc_hits(result, "qtl_hits"):
        symbol = _text(hit.get("gene_symbol"))
        if symbol:
            grouped.setdefault(symbol, []).append(hit)
    return grouped


def _run_gene_symbols(result) -> list:
    """Every gene this run already names: the 1D atlas's effector genes and any gene that
    got a dossier. These are the symbols the QTL colocalisations are joined to."""
    symbols = []
    for row in (result.get("effector_genes") or []):
        symbol = _text(row.get("gene_symbol")) if isinstance(row, dict) else ""
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    for gene in sorted(_dossier(result)):
        symbol = _text(gene)
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _coloc_gene_block(result) -> list:
    """The colocalisation block of section 5: which of this run's genes sit under a
    disease credible set that colocalises with a molecular QTL for that same gene."""
    envelope = _coloc(result)
    lines = ["**Molecular-QTL colocalisation at the disease's credible sets**", ""]
    if envelope is None:
        lines.append(
            "`get_colocalisation` did not run in this run, so no QTL colocalisation was "
            "retrieved for any gene."
        )
        return lines
    if _status(envelope) == "error":
        lines.append(
            "The colocalisation request failed, so no QTL colocalisation was retrieved. "
            "That is not the same statement as the source holding none."
        )
        return lines

    grouped = _coloc_gene_hits(result)
    data = _data(envelope)
    if not grouped:
        lines.append(
            f"No molecular-QTL colocalisation was retrieved for the disease studies "
            f"searched ({_count(data.get('n_sets_examined'))} credible set(s) examined). "
            f"{EMPTY_ARM}."
        )
        return lines

    own = _run_gene_symbols(result)
    rows = []
    for symbol, hits in sorted(grouped.items(), key=lambda item: _sort_h4(item[1])):
        best = hits[0]
        rows.append([
            symbol,
            "yes" if symbol in own else "no",
            _h4(best.get("h4")),
            _or_unknown(best.get("right_study_type")),
            _locus(best),
            _text(best.get("partner_study_id")),
            _count(len(hits)),
        ])
    headers = [
        "Gene",
        "Named by this run's effector genes",
        "Best H4",
        "QTL type",
        "Locus",
        "Partner study",
        "Rows",
    ]
    shared = [symbol for symbol in own if symbol in grouped]
    lines.append(
        f"{_count(data.get('n_qtl_hits'))} molecular-QTL colocalisation(s) retrieved, "
        f"naming {_count(data.get('n_qtl_genes'))} gene(s); the "
        f"{_count(len(_coloc_hits(result, 'qtl_hits')))} row(s) with the highest H4 are "
        f"kept in the envelope and name the {_count(len(grouped))} gene(s) below. "
        + (
            "Shared with this run's effector genes: " + ", ".join(shared) + "."
            if shared else
            "None of them is a gene this run's effector-gene stage named."
        )
    )
    lines.append("")
    lines.extend(_table(headers, rows[:MAX_GENES_SHOWN]))
    lines.append("")
    if len(rows) > MAX_GENES_SHOWN:
        lines.append(
            f"Table capped: {_showing(MAX_GENES_SHOWN, len(rows))} gene(s), ordered by "
            "retrieved H4."
        )
    lines.append(
        "A QTL colocalisation assessment quantifies support for the disease signal and an expression / protein / "
        "splicing signal for that gene sharing one causal variant, as published by the "
        "source. It is a separate two-way result from the metabolite colocalisation in "
        "section 3, even when both sit at the same locus, and it is not a statement that "
        "the gene mediates the metabolite's effect."
    )
    return lines


def _sort_h4(hits) -> tuple:
    value = _float((hits[0] if hits else {}).get("h4"))
    return (value is None, 0.0 if value is None else -value)


def _coloc_gene_lines(result, gene) -> list:
    """One dossier line per gene for the colocalisation arm, in section 6."""
    head = "- Colocalisation (molecular QTL, retrieved):"
    envelope = _coloc(result)
    if envelope is None:
        return [f"{head} not queried in this run."]
    if _status(envelope) == "error":
        return [
            f"{head} the request failed, so nothing is known here about a QTL "
            "colocalisation for this gene."
        ]
    hits = _coloc_gene_hits(result).get(_text(gene)) or []
    if not hits:
        return [
            f"{head} no retrieved colocalisation between this disease's credible sets and "
            "a QTL study for this gene, within the caps this arm worked under. That is a "
            "gap in what was read, not evidence that none exists."
        ]
    best = hits[0]
    return [
        f"{head} {_count(len(hits))} row(s); strongest H4 = {_h4(best.get('h4'))} "
        f"({_or_unknown(best.get('method'))}, {_or_unknown(best.get('right_study_type'))} "
        f"study {_text(best.get('partner_study_id'))}) at {_locus(best)}.",
        "  - Two-way and retrieved: the disease signal and this gene's QTL signal share "
        "one causal variant per the source. It is not a three-way claim with the "
        "metabolite and it does not establish mediation.",
    ]


# ---------------------------------------------------------------- 2. state + verdict

def _section_verdict(result) -> list:
    state = _text(result.get("state")) or "?"
    label = STATE_LABELS.get(state, "state not recognised")
    reason = _text(result.get("reason")) or (
        "the classifier returned no reason for this run"
    )
    qualifier = _coloc_qualifier(result)
    lines = [f"**Verdict: State {state} - {label}.** {reason} {qualifier}".strip(), ""]
    lines.append(
        "The state and the sentence above come from `classify.classify_state`, a pure "
        "function over this run's envelopes. No model wrote them and no model can "
        "change them."
    )
    lines.append("")
    lines.append(
        "The colocalisation clause is an evidence QUALIFIER: `get_colocalisation` runs "
        "after the classifier, its envelope is never passed to it, and no H4 on this card "
        "can move a pair between states A, B and C."
    )
    return lines


# ---------------------------------------------------------------- 3. MR evidence

def _match_line(
    envelope,
    key:  str,
    side: str,
) -> str:
    matches = _rows(envelope, key)
    if not matches:
        return f"MR-EVE matched no {side} dataset by trait name."
    shown = ", ".join(
        f"{_text(row.get('id'))} ({_text(row.get('trait'))})"
        for row in matches[:MAX_MATCHES_SHOWN]
    )
    tail = ""
    if len(matches) > MAX_MATCHES_SHOWN:
        tail = f" ({_showing(MAX_MATCHES_SHOWN, len(matches))})"
    return f"MR-EVE {side} datasets matched ({_count(len(matches))}): {shown}{tail}."


def _estimate_sort_key(row):
    """Smallest retrieved p-value first; a row without a numeric p-value sorts last
    rather than being dropped."""
    value = _float(row.get("pval"))
    return (value is None, 0.0 if value is None else value)


def _drawable_estimates(estimates) -> list:
    """The retrieved rows a forest plot can draw: a point needs finite b and valid source bounds or positive finite
    se. The same rule `plots._forest_rows` applies, kept here so the card can name the
    difference between what it prints and what the figure beside it can show."""
    def usable(row):
        low, high = _float(row.get("ci_low")), _float(row.get("ci_upp"))
        se = _float(row.get("se"))
        return _float(row.get("b")) is not None and (
            (low is not None and high is not None and low <= high)
            or (se is not None and se > 0
                and _float(_float(row.get("b")) - 1.96 * se) is not None
                and _float(_float(row.get("b")) + 1.96 * se) is not None)
        )
    return [row for row in estimates if usable(row)]


def _distinct_triples(drawable) -> int:
    """How many DISTINCT (b, se, p) triples the drawable rows carry.

    MR-EVE returns one row per method AND one row per deposited dataset id, so the same
    study comes back several times: for urate x gout, 22 rows carry 13 distinct triples.
    Counted the same way `plots.plot_forest` counts it for the line it prints on the
    figure, so the card and the picture quote one number.
    """
    return len({
        (_float(row.get("b")), _float(row.get("se")), _float(row.get("pval")))
        for row in drawable
    })


def _source_ci(row) -> str:
    low, high = _float(row.get("ci_low")), _float(row.get("ci_upp"))
    if low is None or high is None:
        return NOT_RETRIEVED
    suffix = " (invalid bounds)" if low > high else ""
    return f"[{_effect(low)}, {_effect(high)}]{suffix}"


def _mr_sensitivity_lines(estimates) -> list:
    """Descriptive agreement only, within dataset pair AND selection strategy.

    Never vote across raw and normalised exposure scales or call agreement a
    sensitivity-test pass. Missing diagnostics cannot be reconstructed from b/se/p.
    """
    lines = ["", "**MR sensitivity and source completeness**", "",
             "Direction agreement below describes retrieved estimates, not independent replication or a passed robustness test. A non-significant p-value is not evidence of no effect.", ""]
    groups = {}
    for row in estimates:
        key = (row.get("exposure_id"), row.get("outcome_id"), row.get("selection"))
        groups.setdefault(key, []).append(row)
    summary = []
    for (exposure, outcome, selection), rows in groups.items():
        methods = sorted({str(r.get("method")) for r in rows if r.get("method")})
        effects = [_float(r.get("b")) for r in rows]
        effects = [b for b in effects if b is not None]
        signs = {1 if b > 0 else -1 if b < 0 else 0 for b in effects}
        if len(methods) < 2:
            agreement = "Only one reported method; cross-method agreement not assessable"
        elif len(effects) != len(rows):
            agreement = "Incomplete effect values; agreement not assessable"
        elif signs == {1} or signs == {-1}:
            agreement = "Same estimated direction across reported methods"
        else:
            agreement = "Mixed directions or zero estimates; inspect individual rows"
        summary.append([_text(exposure), _text(outcome), _or_unknown(selection),
                        ", ".join(methods) or NOT_RETRIEVED, agreement])
    lines.extend(_table(["Exposure", "Outcome", "Selection", "Retrieved methods", "Direction check"], summary))
    single = [r for r in estimates if _float(r.get("nsnp")) == 1
              or "wald" in str(r.get("method") or "").casefold()]
    if single:
        lines.extend(["", f"Single-SNP / Wald-ratio warning: {len(single)} retrieved row(s) report nsnp=1 or a Wald method. Single-instrument Wald ratio — heterogeneity and pleiotropy cannot be assessed. A single instrument cannot support multi-instrument heterogeneity, MR-Egger or leave-one-out sensitivity checks; this is not robust multi-instrument evidence."])
    lines.extend([
        "",
        "Steiger directionality: not reported by this resource. Heterogeneity Q: not reported. "
        "Egger intercept: not reported. LD check: not reported. Colocalisation: see the colocalisation "
        "section (retrieved separately from Open Targets).",
        "MR-PRESSO, leave-one-out and sample overlap diagnostics are also not reported. "
        "Missing diagnostics do not mean these checks passed.",
        "Source CI bounds are printed verbatim when available. Their confidence level, construction "
        "and scale metadata are unspecified. The forest uses valid source bounds first, otherwise "
        "b +/- 1.96 se with positive se, labelled as derived. Source properties and Cypher request "
        "are retained in the ledger; REST fallback and older cached rows may lack these details.",
    ])
    return lines


def _estimate_rows(estimates) -> list:
    ordered = sorted(estimates, key=_estimate_sort_key)
    return [
        [
            f"{_text(row.get('exposure_id'))} ({_text(row.get('exposure_trait'))})",
            f"{_text(row.get('outcome_id'))} ({_text(row.get('outcome_trait'))})",
            _or_unknown(row.get("method")),
            _effect(row.get("b")),
            _effect(row.get("se")),
            _pvalue(row.get("pval")),
            _nsnp(row.get("nsnp")) + (
                " — single-instrument Wald ratio — heterogeneity and pleiotropy cannot be assessed"
                if _float(row.get("nsnp")) == 1 else ""
            ),
            _effect(row.get("moescore")),
            _or_unknown(row.get("selection")),
            _source_ci(row),
        ]
        for row in ordered[:MAX_ESTIMATE_ROWS]
    ]


def _section_mr(result) -> list:
    envelope = _envelope(result, "mr")
    if envelope is None:
        return [
            "`get_mr_result` did not run in this run, so no MR estimate was retrieved. "
            "That is a gap in what was queried, not a finding."
        ]

    status = _status(envelope)
    data = _data(envelope)
    estimates = _rows(envelope, "estimates")
    lines = [_provenance_line(envelope, "get_mr_result"), ""]

    if not estimates:
        if status == "error":
            lines.append(
                "`get_mr_result` returned an error envelope, so nothing was retrieved "
                "for this pair: the request failed, which is not the same statement as "
                f"the source holding no row.{_error_detail(envelope)}"
            )
        else:
            lines.append(f"Retrieved MR estimates: {EMPTY_ARM}.")
        lines.append("")
        lines.append(_match_line(
            envelope,
            "exposure_matches",
            "exposure",
        ))
        lines.append(_match_line(
            envelope,
            "outcome_matches",
            "outcome",
        ))
        return lines

    reported = data.get("n_estimates")
    total = len(estimates) if _float(reported) is None else int(_float(reported))
    drawable = _drawable_estimates(estimates)
    # "22 estimates" is the number a reader carries away from this card, from the Slack
    # summary and from the verdict line. It is 22 ROWS, not 22 studies, and the row count
    # on its own reads as 22 independent pieces of evidence.
    repeats = (
        f" They carry {_count(_distinct_triples(drawable))} distinct (b, se, p): MR-EVE "
        "returns one row per method and one row per deposited dataset id, so this is not "
        "a count of independent studies."
        if drawable
        else ""
    )
    if status == "error":
        lines.append(
            f"`get_mr_result` failed part way through. The {_count(len(estimates))} "
            "row(s) retrieved before the failure are kept here and in the ledger; the "
            f"sweep is incomplete.{repeats}{_error_detail(envelope)}"
        )
    else:
        lines.append(
            f"{_count(total)} estimate row(s) retrieved from a pre-computed source."
            f"{repeats} Retrieved, not computed here."
        )
    lines.append("")
    lines.append(_match_line(
        envelope,
        "exposure_matches",
        "exposure",
    ))
    lines.append(_match_line(
        envelope,
        "outcome_matches",
        "outcome",
    ))
    lines.append("")

    headers = [
        "Exposure dataset",
        "Outcome dataset",
        "Method",
        "b",
        "se",
        "p",
        "nsnp",
        "moescore",
        "selection",
        "Source CI (level unspecified)",
    ]
    lines.extend(_table(headers, _estimate_rows(estimates)))
    lines.append("")
    if len(estimates) > MAX_ESTIMATE_ROWS:
        lines.append(
            f"Table capped: {_count(MAX_ESTIMATE_ROWS)} of {_count(len(estimates))} "
            "retrieved row(s) are shown, sorted by retrieved p-value (smallest first). "
            "The rows not shown are in the ledger named in section 11."
        )
    else:
        lines.append(
            f"All {_count(len(estimates))} retrieved row(s) are shown, sorted by "
            "retrieved p-value (smallest first)."
        )
    undrawable = len(estimates) - len(drawable)
    if undrawable:
        lines.append(
            f"{_count(undrawable)} of the {_count(len(estimates))} retrieved row(s) "
            "lack b or a usable interval. They are printed in this table and are in the ledger, and "
            "they are NOT on the forest plot, which can only draw a point with an "
            "interval - so the table and the figure hold different rows for this run."
        )
    lines.append("")
    lines.extend(_bullets([NSNP_NOTE, MOESCORE_NOTE, SCALE_NOTE]))
    lines.extend(_mr_sensitivity_lines(estimates))
    return lines


# ---------------------------------------------------------------- 4. instruments

def _f_range(row) -> str:
    low = _float(row.get("min_f"))
    high = _float(row.get("max_f"))
    if low is None and high is None:
        return NOT_RETRIEVED
    return f"{_effect(low)} to {_effect(high)}"


def _strongest_hit(row):
    hits = [hit for hit in (row.get("example_hits") or []) if isinstance(hit, dict)]
    if not hits:
        return None
    scored = [hit for hit in hits if _float(hit.get("p")) is not None]
    if not scored:
        return hits[0]
    return min(scored, key=lambda hit: _float(hit.get("p")))


def _hit_line(row) -> str:
    hit = _strongest_hit(row)
    if hit is None:
        return f"- {_text(row.get('id'))}: no example hit was returned for this dataset."
    return (
        f"- {_text(row.get('id'))}: {_text(hit.get('rsid'))} "
        f"(chr{_text(hit.get('chr'))}:{_count(hit.get('position'))}, "
        f"{_text(hit.get('ea'))}/{_text(hit.get('nea'))}, eaf {_effect(hit.get('eaf'))}) "
        f"beta {_effect(hit.get('beta'))}, se {_effect(hit.get('se'))}, "
        f"p {_pvalue(hit.get('p'))}, F {_effect(hit.get('f'))}"
    )


def _exposure_block(envelope) -> list:
    if envelope is None:
        return [
            "`get_mqtl_instruments` did not run, so no instrument count was retrieved."
        ]
    lines = [_provenance_line(envelope, "get_mqtl_instruments"), ""]
    if _status(envelope) == "error":
        lines.append(
            "`get_mqtl_instruments` returned an error envelope, so no hit count was "
            "retrieved: the request failed, which is not the same statement as the "
            f"source holding no dataset.{_error_detail(envelope)}"
        )
        return lines

    exposures = _rows(envelope, "exposures")
    if not exposures:
        lines.append(
            f"Exposure datasets measuring this metabolite: {EMPTY_ARM}. A dataset that "
            "is absent from this OpenGWAS release is not a measurement without a "
            "genetic basis."
        )
        return lines

    # Sex and Note are the two fields `get_mqtl_instruments` documents as must-print, and
    # they are the only thing separating ieu-a-786 / 787 / 788 - an all-sample BMI-by-SNP
    # interaction scan, the same scan in men, and the same scan in women. Without them
    # those three render as one identical urate GWAS repeated three times, and an
    # interaction beta is not a main-effect exposure at all.
    headers = [
        "Dataset",
        "Trait",
        "Platform",
        "Unit",
        "Sample size",
        "Population",
        "Sex",
        "Year",
        "Build",
        "GWS hits",
        "Weak (F<10)",
        "F range",
        "Note (from the source)",
    ]
    rows = [
        [
            _text(row.get("id")),
            _text(row.get("trait")),
            _or_unknown(row.get("platform")),
            _or_unknown(row.get("unit")),
            _count(row.get("sample_size")),
            _or_unknown(row.get("population")),
            _or_unknown(row.get("sex")),
            _or_unknown(row.get("year")),
            _or_unknown(row.get("build")),
            _count(row.get("gws_hits")),
            _count(row.get("weak_instruments")),
            _f_range(row),
            _or_unknown(row.get("note")),
        ]
        for row in exposures
    ]
    lines.extend(_table(headers, rows))
    lines.append("")
    lines.append(
        "Read the Sex and Note columns before reading any row as an exposure: a "
        "sex-stratified deposit and an interaction scan are different datasets from a "
        "main-effect GWAS of the same trait, and an interaction beta measures how a SNP "
        "effect changes with the modifier, so F = (beta/se)^2 on it is not instrument "
        "strength."
    )
    lines.append("")

    matched = _float(_data(envelope).get("matched_datasets"))
    if matched is not None and matched > len(exposures):
        lines.append(
            f"Capped by the tool: {_count(len(exposures))} of the {_count(matched)} "
            "dataset(s) named by these synonyms were queried, the largest by sample "
            f"size. The other {_count(matched - len(exposures))} were never opened, so "
            "nothing here says anything about them."
        )
    else:
        lines.append(
            f"All {_count(len(exposures))} dataset(s) named by these synonyms were "
            "queried."
        )
    lines.append("")
    lines.append("Strongest retrieved hit per dataset (by retrieved p-value):")
    lines.extend(_hit_line(row) for row in exposures)
    lines.append("")
    lines.append(F_NOTE)
    lines.append("")
    lines.append(
        "GWS hits are OpenGWAS's own PRE-CLUMPED tophits at p < 5e-8: independent loci, "
        "retrieved as a count, not selected or clumped here."
    )
    return lines


def _outcome_block(envelope) -> list:
    if envelope is None:
        return ["`find_outcome_datasets` did not run, so no outcome dataset was retrieved."]
    lines = [_provenance_line(envelope, "find_outcome_datasets"), ""]
    if _status(envelope) == "error":
        lines.append(
            "`find_outcome_datasets` returned an error envelope, so no outcome dataset "
            f"was retrieved: the request failed.{_error_detail(envelope)}"
        )
        return lines

    datasets = _rows(envelope, "datasets")
    if not datasets:
        lines.append(f"Outcome datasets for this disease: {EMPTY_ARM}.")
        return lines

    headers = [
        "Dataset",
        "Trait",
        "Sample size",
        "Cases",
        "Controls",
        "Population",
        "Year",
        "Author",
        "Consortium",
        "Build",
    ]
    rows = [
        [
            _text(row.get("id")),
            _text(row.get("trait")),
            _count(row.get("sample_size")),
            _count(row.get("ncase")),
            _count(row.get("ncontrol")),
            _or_unknown(row.get("population")),
            _or_unknown(row.get("year")),
            _or_unknown(row.get("author")),
            _or_unknown(row.get("consortium")),
            _or_unknown(row.get("build")),
        ]
        for row in datasets
    ]
    lines.extend(_table(headers, rows))
    lines.append("")

    matched = _float(_data(envelope).get("n_matched_before_cap"))
    if matched is not None and matched > len(datasets):
        lines.append(
            f"Capped by the tool: {_count(len(datasets))} of the {_count(matched)} "
            "matched dataset(s) are returned. The rest are named in the caveats, not "
            "hidden."
        )
    else:
        lines.append(f"All {_count(len(datasets))} matched dataset(s) are shown.")

    if any(_BROKEN_ESCAPE.search(str(row.get(key) or ""))
           for row in datasets for key in ("author", "consortium")):
        lines.append("")
        lines.append(
            "One or more author or consortium names above carry the source's own broken "
            "non-ASCII escapes (for example \"D<U+00F6>nerta<U+015F> HM\"). They are "
            "printed exactly as OpenGWAS wrote them and are not repaired here."
        )
    return lines


def _catalog_block(envelope) -> list:
    if envelope is None:
        return [
            "`get_gwas_catalog` did not run in this run (it costs about 100 s per "
            "disease and is skipped by default). It is not a classifier input, so the "
            "A/B/C state is unaffected either way."
        ]
    lines = [_provenance_line(envelope, "get_gwas_catalog"), ""]
    if _status(envelope) == "error":
        lines.append(
            "`get_gwas_catalog` returned an error envelope, so no association was "
            "retrieved: the request failed, which is not the same statement as the "
            "Catalog holding no association for this trait. It is not a classifier "
            f"input, so the A/B/C state did not move.{_error_detail(envelope)}"
        )
        return lines

    data = _data(envelope)
    kept = _float(data.get("n_associations_kept"))
    total = _float(data.get("n_associations_total"))
    lines.append(
        f"Trait {_or_unknown(data.get('efo_short_form'))} "
        f"({_or_unknown(data.get('efo_trait'))}): "
        f"{_count(data.get('n_associations_kept'))} of "
        f"{_count(data.get('n_associations_total'))} curated association(s) kept, "
        f"{_count(len(_rows(envelope, 'mapped_genes')))} mapped-gene row(s) retrieved."
    )
    if kept is not None and total is not None and total > kept:
        lines.append("")
        lines.append(
            f"Capped by the tool: {_count(kept)} of the {_count(total)} retrieved "
            f"association(s) are kept in the envelope; {_count(total - kept)} weaker "
            "row(s) were dropped after download."
        )
    lines.append("")
    lines.append(
        "Catalog rows are curated trait-variant ASSOCIATIONS from published GWAS: no MR, "
        "no instrument, no direction of causation. They are context, and they are not a "
        "classifier input - an association can never move the A/B/C state."
    )
    return lines


def _section_instruments(result) -> list:
    lines = ["### Exposure datasets (metabolite instruments)", ""]
    lines.extend(_exposure_block(_envelope(result, "instruments")))
    lines.append("")
    lines.append("### Outcome datasets (disease)")
    lines.append("")
    lines.extend(_outcome_block(_envelope(result, "outcomes")))
    lines.append("")
    lines.append("### GWAS Catalog (context only)")
    lines.append("")
    lines.extend(_catalog_block(_envelope(result, "catalog")))
    return lines


# ---------------------------------------------------------------- 5. effector genes

def _gene_rule(rows) -> str:
    """How the Catalog named this gene, from the fields it returned. Every clause is a
    mapping rule, never a claim that the gene does anything."""
    distances = [_float(row.get("distance")) for row in rows]
    distances = [value for value in distances if value is not None]
    nearest = min(distances) if distances else None
    intergenic = all(bool(row.get("is_intergenic")) for row in rows)
    parts = []
    if nearest is not None and nearest == 0 and not intergenic:
        parts.append("variant inside the gene body")
    elif nearest is not None:
        parts.append(f"intergenic, nearest variant {_count(nearest)} bp away")
    else:
        parts.append("distance not recorded by the source")
    if any(bool(row.get("is_closest_gene")) for row in rows):
        parts.append("closest gene to at least one variant")
    sources = sorted({_text(row.get("source")) for row in rows if _text(row.get("source"))})
    if sources:
        parts.append("mapped by " + ", ".join(sources))
    return "; ".join(parts)


def _gene_variants(entries) -> list:
    """The DISTINCT rsIDs that named one gene, sorted. The Catalog lists a gene once per
    annotation source, so the row count for a gene is not its variant count."""
    return sorted({_text(entry.get("rsid")) for entry in entries if _text(entry.get("rsid"))})


def _catalog_genes(envelope) -> list:
    if envelope is None:
        return [
            "GWAS Catalog mapped genes: `get_gwas_catalog` did not run in this run, so "
            "no gene was retrieved from it."
        ]
    if _status(envelope) == "error":
        return [
            "GWAS Catalog mapped genes: the request failed, so no gene was retrieved. "
            "That is not the same statement as the Catalog naming no gene."
        ]
    mapped = _rows(envelope, "mapped_genes")
    if not mapped:
        return [f"GWAS Catalog mapped genes: {EMPTY_ARM}."]

    grouped = {}
    for row in mapped:
        symbol = _text(row.get("gene"))
        if symbol:
            grouped.setdefault(symbol, []).append(row)

    # Sorted on the quantity the Variants column shows - DISTINCT rsIDs - not on the
    # annotation-row count. Ensembl and NCBI each contribute a row, so a gene named by 2
    # variants through both sources carries 4 rows and used to sort above a gene named by
    # 3 variants through one, which made the table look arbitrarily ordered and made the
    # cap sentence below describe an order the code did not use.
    ordered = sorted(grouped.items(), key=lambda item: (-len(_gene_variants(item[1])), item[0]))
    rows = []
    for symbol, entries in ordered[:MAX_GENES_SHOWN]:
        rsids = _gene_variants(entries)
        shown = ", ".join(rsids[:MAX_RSIDS_PER_GENE])
        if len(rsids) > MAX_RSIDS_PER_GENE:
            shown += f" ({_showing(MAX_RSIDS_PER_GENE, len(rsids))})"
        rows.append([symbol, _count(len(rsids)), shown, _gene_rule(entries)])

    lines = [
        f"GWAS Catalog mapped genes for the disease trait: {_count(len(grouped))} "
        f"distinct gene symbol(s) across {_count(len(mapped))} mapped-gene row(s).",
        "",
    ]
    headers = ["Gene", "Variants", "rsIDs", "How the Catalog named it"]
    lines.extend(_table(headers, rows))
    lines.append("")
    if len(grouped) > MAX_GENES_SHOWN:
        lines.append(
            f"Table capped: {_showing(MAX_GENES_SHOWN, len(grouped))} gene symbol(s), "
            "ordered by how many variants name them."
        )
    lines.append(
        "These are the DISEASE's mapped genes, and Catalog mapping is proximity-based. "
        "A gene named here is a positional annotation of a variant, not an effector gene "
        "of the metabolite and not a target."
    )
    return lines


def _section_genes(result) -> list:
    lines = _catalog_genes(_envelope(result, "catalog"))
    lines.append("")
    atlas = _envelope(result, "atlas")
    nominated = [
        row for row in (result.get("effector_genes") or [])
        if isinstance(row, dict) and row.get("gene_symbol")
    ]
    if nominated:
        lines.append("Atlas-nominated effector candidates (source naming, not proven mediation):")
        for row in nominated:
            lines.append(
                f"- {_text(row['gene_symbol'])}: named by "
                f"{', '.join(_text(value) for value in (row.get('atlases') or [])) or NOT_RETRIEVED}; "
                f"rule: {', '.join(_text(value) for value in (row.get('gene_source') or [])) or NOT_RETRIEVED}."
            )
    elif atlas is None:
        lines.append("The atlas nomination layer was not queried in this run; the effector mechanism was not assessed.")
    elif _status(atlas) == "error":
        lines.append("The atlas lookup failed; the effector mechanism remains unresolved in this run.")
    else:
        lines.append("No effector gene was nominated by the retrieved atlas lookup; the mechanism remains unresolved.")
    lines.append(
        "An unresolved effector mechanism does not remove or invalidate retrieved metabolite MR, "
        "colocalisation assessments, or instrument feasibility evidence; those layers remain separate."
    )
    nominated_symbols = {str(row["gene_symbol"]) for row in nominated}
    genes = sorted(_dossier(result))
    if genes:
        lines.append(
            "Genes carried into the 1E dossier in section 6: "
            + ", ".join(_text(gene) for gene in genes)
            + "."
        )
        caller_genes = [gene for gene in genes if gene not in nominated_symbols]
        if caller_genes:
            lines.append(
                ", ".join(_text(gene) for gene in caller_genes)
                + " were supplied to this run by its caller; they are not atlas nominations in this run."
            )
    else:
        lines.append("No gene dossier is available in this run; see the atlas status above and run-level notes.")
    lines.append("")
    gem = _envelope(result, "gem")
    gem_data = _data(gem)
    gem_candidates = [
        row for row in (gem_data.get("candidates") or [])
        if isinstance(row, dict) and row.get("symbol_status") == "unique" and row.get("symbol")
    ]
    if gem is None:
        lines.append("Human-GEM biochemical candidates were not assessed in this run.")
    elif _status(gem) == "error":
        lines.append("The Human-GEM lookup failed; no biochemical candidate list was accepted from it.")
    elif gem_data.get("policy_suppressed"):
        lines.append(
            "Human-GEM identified this as a hub/currency metabolite and suppressed its candidate "
            "detail under the recorded policy; this is not a claim that it has no reaction genes."
        )
    elif gem_candidates:
        lines.append("Human-GEM biochemical candidates (reaction membership, not genetic effectors):")
        for row in gem_candidates[:MAX_GEM_CANDIDATES_SHOWN]:
            lines.append(
                f"- {_text(row.get('symbol'))} ({_text(row.get('ensembl'))}): "
                f"{_or_unknown(row.get('role'))} context in {_count(row.get('n_reactions'))} "
                f"reaction(s); complex member {_or_unknown(row.get('complex_member'))}."
            )
        if len(gem_candidates) > MAX_GEM_CANDIDATES_SHOWN:
            lines.append(f"- {_showing(MAX_GEM_CANDIDATES_SHOWN, len(gem_candidates))} biochemical candidate(s).")
    else:
        mapping = gem_data.get("mapping") if isinstance(gem_data.get("mapping"), dict) else {}
        lines.append(
            "No usable Human-GEM gene candidate is shown (mapping status "
            f"{_or_unknown(mapping.get('status'))}); this is a lookup/context gap, not a genetic null."
        )

    biochemical_symbols = {str(row.get("symbol")) for row in gem_candidates}
    matched_dossiers = sorted(set(genes) & biochemical_symbols)
    if matched_dossiers:
        lines.append(
            "Dossier genes that also occur in the Human-GEM reaction context: "
            + ", ".join(_text(gene) for gene in matched_dossiers)
            + ". Their 1E records remain target/drug/constraint evidence; the Human-GEM match "
              "does not demonstrate disease mediation."
        )
    return lines


# ---------------------------------------------------------------- 6. gene dossiers

def _unresolved_gene(data) -> bool:
    """The 1E tools write ensembl=None when no exact symbol matched: a lookup that
    failed. A key that is absent altogether is a different thing entirely."""
    return "ensembl" in data and data["ensembl"] is None


def _association_lines(envelope) -> list:
    if envelope is None:
        return ["- Open Targets association: not queried in this run."]
    head = f"- Open Targets association (`get_target_disease_evidence`, status `{_status(envelope)}`):"
    if _status(envelope) == "error":
        return [
            f"{head} the request failed, so no association record was retrieved."
            f"{_error_detail(envelope)}"
        ]
    data = _data(envelope)
    if _unresolved_gene(data):
        return [f"{head} the gene symbol was not resolved, so no association was queried."]

    page = data.get("page") if isinstance(data.get("page"), dict) else {}
    row = data.get("target_disease")
    lines = []
    if isinstance(row, dict):
        disease = row.get("disease") if isinstance(row.get("disease"), dict) else {}
        scores = [
            f"{_text(item.get('id'))} {_effect(item.get('score'))}"
            for item in (row.get("datatypeScores") or [])
            if isinstance(item, dict)
        ]
        lines.append(
            f"{head} overall score {_effect(row.get('score'))} for "
            f"{_text(disease.get('name'))} ({_text(disease.get('id'))})"
            + (f"; by datatype: {', '.join(scores)}" if scores else "")
            + "."
        )
    else:
        lines.append(
            f"{head} the requested disease is not on the returned association page "
            f"(page {_count(page.get('index'))}, size {_count(page.get('size'))} of "
            f"{_count(page.get('total_count'))} associated diseases) - {EMPTY_ARM}."
        )
    top = [item for item in (data.get("top_diseases") or []) if isinstance(item, dict)]
    if top:
        shown = "; ".join(
            f"{_text((item.get('disease') or {}).get('name'))} "
            f"({_text((item.get('disease') or {}).get('id'))}) "
            f"{_effect(item.get('score'))}"
            for item in top[:MAX_TOP_DISEASES_SHOWN]
        )
        cap = ""
        if len(top) > MAX_TOP_DISEASES_SHOWN:
            cap = f" ({_showing(MAX_TOP_DISEASES_SHOWN, len(top))})"
        lines.append(
            f"  - Highest-scoring diseases on that page, as context only{cap}: {shown}."
        )
    lines.append(
        "  - An Open Targets score aggregates evidence types including clinical "
        "evidence. It is not an MR estimate and not a causal probability."
    )
    return lines


def _report_line(report) -> str:
    diseases = []
    for entry in (report.get("diseases") or []):
        if not isinstance(entry, dict):
            continue
        disease = entry.get("disease") if isinstance(entry.get("disease"), dict) else {}
        name = _text(disease.get("name")) or _text(entry.get("diseaseFromSource"))
        if name:
            diseases.append(name)
    return (
        f"    - report {_or_unknown(report.get('report_id'))} "
        f"({_or_unknown(report.get('report_type'))}, source "
        f"{_or_unknown(report.get('source'))}, year {_or_unknown(report.get('year'))}): "
        f"phase {_or_unknown(report.get('trial_phase'))}, status "
        f"{_or_unknown(report.get('status'))}, why stopped "
        f"{_or_unknown(report.get('why_stopped'))}, for "
        f"{'; '.join(diseases) if diseases else 'no disease recorded on this report'}"
    )


def _drug_lines(envelope) -> list:
    if envelope is None:
        return ["- Known drugs and clinical candidates: not queried in this run."]
    head = f"- Known drugs and clinical candidates (`get_known_drugs`, status `{_status(envelope)}`):"
    if _status(envelope) == "error":
        return [
            f"{head} the request failed, so no drug record was retrieved."
            f"{_error_detail(envelope)}"
        ]
    data = _data(envelope)
    if _unresolved_gene(data):
        return [f"{head} the gene symbol was not resolved, so no drug record was queried."]

    drugs = [row for row in (data.get("drugs") or []) if isinstance(row, dict)]
    if not drugs:
        return [
            f"{head} no drug or clinical candidate is recorded against this target - "
            f"{EMPTY_ARM}."
        ]

    lines = [f"{head} {_count(data.get('count'))} recorded against this target."]
    for drug in drugs[:MAX_DRUGS_SHOWN]:
        reports = [row for row in (drug.get("clinical_reports") or []) if isinstance(row, dict)]
        lines.append(
            f"  - {_or_unknown(drug.get('drug'))} ({_or_unknown(drug.get('drug_id'))}) - "
            f"drug-level maxClinicalStage {_or_unknown(drug.get('max_clinical_stage'))} "
            f"across all of its indications; {_count(len(reports))} clinical report(s)."
        )
        lines.extend(_report_line(report) for report in reports[:MAX_REPORTS_PER_DRUG])
        if len(reports) > MAX_REPORTS_PER_DRUG:
            lines.append(
                f"    - {_showing(MAX_REPORTS_PER_DRUG, len(reports))} report(s) for "
                "this drug; the rest are in the ledger."
            )
    if len(drugs) > MAX_DRUGS_SHOWN:
        lines.append(f"  - {_showing(MAX_DRUGS_SHOWN, len(drugs))} drug(s).")
    lines.append(f"  - {DRUG_STAGE_NOTE}")
    return lines


def _chembl_lines(envelope) -> list:
    if envelope is None:
        return ["- ChEMBL modulators: not queried in this run."]
    head = f"- ChEMBL modulators (`get_chembl_modulators`, status `{_status(envelope)}`):"
    if _status(envelope) == "error":
        return [
            f"{head} the request failed, so no mechanism was retrieved."
            f"{_error_detail(envelope)}"
        ]
    data = _data(envelope)
    target = data.get("target") if isinstance(data.get("target"), dict) else {}
    if not target:
        return [
            f"{head} no human SINGLE PROTEIN target carries this exact gene symbol in "
            f"the search results - {EMPTY_ARM}."
        ]
    mechanisms = [row for row in (data.get("mechanisms") or []) if isinstance(row, dict)]
    lines = [
        f"{head} target {_text(target.get('target_chembl_id'))} "
        f"({_or_unknown(target.get('pref_name'))}, {_or_unknown(target.get('organism'))}), "
        f"{_count(len(mechanisms))} mechanism annotation(s), "
        f"{_count(data.get('activity_count'))} activity record(s)."
    ]
    for row in mechanisms[:MAX_MECHANISMS_SHOWN]:
        lines.append(
            f"  - {_or_unknown(row.get('mechanism_of_action'))} "
            f"(action {_or_unknown(row.get('action_type'))}, molecule "
            f"{_or_unknown(row.get('molecule_chembl_id'))})"
        )
    if len(mechanisms) > MAX_MECHANISMS_SHOWN:
        lines.append(f"  - {_showing(MAX_MECHANISMS_SHOWN, len(mechanisms))} mechanism(s).")
    lines.append(
        "  - Activity records count assay rows, not unique ligands, and not potency or "
        "efficacy. A mechanism annotation is a source record, not evidence of benefit "
        "for the disease that was asked about."
    )
    return lines


def _gnomad_lines(envelope) -> list:
    if envelope is None:
        return ["- gnomAD constraint: not queried in this run."]
    head = f"- gnomAD constraint (`get_gnomad_constraint`, status `{_status(envelope)}`):"
    if _status(envelope) == "error":
        return [
            f"{head} the request failed, so no constraint metric was retrieved."
            f"{_error_detail(envelope)}"
        ]
    data = _data(envelope)
    if _unresolved_gene(data):
        return [f"{head} the gene lookup returned null, so no metric was retrieved."]
    values = [
        f"pLI {_effect(data.get('pli'))}",
        f"o/e LoF {_effect(data.get('oe_lof'))}",
        f"LOEUF {_effect(data.get('loeuf'))}",
        f"o/e missense {_effect(data.get('oe_mis'))}",
    ]
    if all(_float(data.get(key)) is None
           for key in ("pli", "oe_lof", "oe_lof_upper", "oe_mis")):
        return [f"{head} no constraint metric is recorded for this gene - {EMPTY_ARM}."]
    return [
        f"{head} " + ", ".join(values)
        + f" (reference genome {_or_unknown(data.get('reference_genome'))}, dataset "
          f"release {_or_unknown(data.get('dataset_release'))}).",
        f"  - {GNOMAD_NOTE}",
    ]


_DOSSIER_PARTS = (
    ("get_target_disease_evidence", _association_lines),
    ("get_known_drugs",             _drug_lines),
    ("get_chembl_modulators",       _chembl_lines),
    ("get_gnomad_constraint",       _gnomad_lines),
)


def _section_dossiers(result) -> list:
    dossier = _dossier(result)
    if not dossier:
        return [
            "No gene dossier is available in this run. This may reflect an unqueried or unresolved "
            "effector layer, or an interrupted dossier stage; consult section 5 and the run notes. "
            "It does not mean that these genes have no drugs, and does not invalidate any retrieved "
            "metabolite MR, colocalisation assessment, or feasibility evidence."
        ]
    lines = []
    for gene in sorted(dossier):
        tools = dossier[gene] if isinstance(dossier[gene], dict) else {}
        lines.append(f"### {_text(gene)}")
        lines.append("")
        for name, builder in _DOSSIER_PARTS:
            lines.extend(builder(tools.get(name)))
        lines.append("")
    lines.append(
        "A dossier describes a candidate gene that was handed to this run. It does not "
        "establish that the metabolite is causal, does not nominate an effector gene, "
        "and is not a go / no-go verdict."
    )
    return lines


# ---------------------------------------------------------------- 7. via-enzyme

def _section_via_enzyme(result) -> list:
    envelope = _envelope(result, "gem")
    if envelope is None:
        return [SECTION_7_SCOPE]
    head = (
        "Source: Human-GEM - tool `map_metabolite_to_genes_gem` - "
        f"status `{_status(envelope)}` - retrieved at {_or_unknown(envelope.get('retrieved_at'))}."
    )
    if _status(envelope) == "error":
        return [
            head,
            "The local model/index lookup failed, so no biochemical context was retrieved."
            + _error_detail(envelope),
            "The A/B/C state and genetic evidence are unchanged by this optional failure.",
        ]

    data = _data(envelope)
    mapping = data.get("mapping") if isinstance(data.get("mapping"), dict) else {}
    if mapping.get("status") in ("unmapped", "ambiguous") or _status(envelope) == "empty":
        return [
            head,
            f"Mapping status: {_or_unknown(mapping.get('status'))}. No reaction-derived gene "
            "candidate was accepted; this is not evidence of no biology and no fuzzy identity "
            "or stereochemistry fallback was used.",
        ]

    lines = [
        head,
        f"Exact ChEBI mapping in Human-GEM {_or_unknown(data.get('model_version'))} "
        f"({_or_unknown(data.get('dataset_kind'))}): {_count(data.get('total_reactions'))} "
        f"reaction(s) and {_count(data.get('total_candidates'))} reaction-linked gene "
        f"candidate(s). Network calls: {_count(data.get('network_calls'))}.",
    ]
    if data.get("policy_suppressed"):
        lines.append(
            "Candidate/reaction detail was suppressed by the recorded hub/currency policy. "
            "The full source counts above are retained and are not confidence scores."
        )
        return lines

    reactions = [row for row in (data.get("reactions") or []) if isinstance(row, dict)]
    if reactions:
        lines.append("Selected recorded reactions (source GPR retained):")
        for row in reactions[:MAX_GEM_REACTIONS_SHOWN]:
            matched_ids = set(row.get("matched_species_ids") or [])
            compartments = sorted({
                str(participant.get("compartment_id"))
                for participant in (row.get("participants") or [])
                if isinstance(participant, dict)
                and participant.get("species_id") in matched_ids
                and participant.get("compartment_id") is not None
            })
            lines.append(
                f"- {_text(row.get('id'))}: {_or_unknown(row.get('name'))}; direction "
                f"{_or_unknown(row.get('direction'))}; role {_or_unknown(row.get('role'))}; "
                f"matched compartment(s) {', '.join(_text(value) for value in compartments) or NOT_RETRIEVED}; "
                f"GPR `{_text(row.get('gpr_raw')) or NOT_RETRIEVED}`."
            )
        if len(reactions) > MAX_GEM_REACTIONS_SHOWN:
            lines.append(f"- {_showing(MAX_GEM_REACTIONS_SHOWN, len(reactions))} returned reaction(s).")

    candidates = [row for row in (data.get("candidates") or []) if isinstance(row, dict)]
    if candidates:
        lines.append("Selected reaction-linked genes (navigation only, not a target ranking):")
        for row in candidates[:MAX_GEM_CANDIDATES_SHOWN]:
            symbol = row.get("symbol") if row.get("symbol_status") == "unique" else None
            lines.append(
                f"- {_or_unknown(symbol)} ({_or_unknown(row.get('ensembl'))}): "
                f"{_or_unknown(row.get('role'))}, {_count(row.get('n_reactions'))} reaction(s), "
                f"complex member {_or_unknown(row.get('complex_member'))}."
            )
        if len(candidates) > MAX_GEM_CANDIDATES_SHOWN:
            lines.append(f"- {_showing(MAX_GEM_CANDIDATES_SHOWN, len(candidates))} returned candidate(s).")
    lines.append(
        "Human-GEM membership is biochemical context only. It does not show that changing a "
        "gene changes the circulating metabolite or the selected disease, and it cannot change A/B/C."
    )
    return lines


# ---------------------------------------------------------------- 8. caveats

def _all_envelopes(result) -> list:
    """(heading, envelope) for every core/context envelope, then every 1E envelope."""
    found = [
        (f"`{tool}` ({_or_unknown(envelope.get('source'))})", envelope)
        for _key, tool, envelope in _core_envelopes(result)
    ]
    dossier = _dossier(result)
    for gene in sorted(dossier):
        tools = dossier[gene] if isinstance(dossier[gene], dict) else {}
        for name in sorted(tools):
            envelope = tools.get(name)
            if isinstance(envelope, dict):
                found.append((f"`{name}` for {_text(gene)}", envelope))
    return found


def _section_caveats(result) -> list:
    lines = []
    notes = [str(note) for note in (result.get("notes") or []) if str(note).strip()]
    lines.append("**Run-level notes**")
    lines.append("")
    if notes:
        lines.extend(_bullets(_text(note) for note in notes))
    else:
        lines.append("- The run recorded no degradation note.")
    lines.append("")

    failed = [
        heading for heading, envelope in _all_envelopes(result)
        if _status(envelope) == "error"
    ]
    lines.append("**Tools that failed in this run**")
    lines.append("")
    if failed:
        lines.extend(_bullets(f"{heading} returned an error envelope." for heading in failed))
        lines.append("")
        lines.append(
            "A failed request is not a source with no record. Nothing above may be read "
            "as an absence of evidence."
        )
    else:
        lines.append("- No tool returned an error envelope.")
    lines.append("")

    lines.append("**Caveats declared by the tools, verbatim**")
    lines.append("")
    printed = False
    for heading, envelope in _all_envelopes(result):
        caveats = _caveats(envelope)
        if not caveats:
            continue
        printed = True
        lines.append(f"{heading}:")
        lines.extend(_bullets(_text(caveat) for caveat in caveats))
        lines.append("")
    if not printed:
        lines.append("- No tool in this run declared a caveat.")
    return lines


# ---------------------------------------------------------------- 9. reasoning

def _section_reasoning(result, interpretation=None) -> list:
    """The one section a model writes, and the last gate before its prose is printed.

    THE PROSE IS RE-VALIDATED HERE, against this run, even though llm.interpret already
    validated it and set `accepted`. That is deliberate duplication: it makes "no unchecked
    prose reaches a card" a property of this function rather than a promise about every
    caller. A hand-built object with accepted=True, a cached interpretation rendered
    against a different run, or a future surface that forgets the check all fail here
    instead of printing.

    Anything unusable leaves the fixed pending sentence in place. A card with an empty
    section 9 is worse than one with a good paragraph and far better than one with a
    paragraph nobody can quote."""
    if interpretation is None:
        return [PENDING_REASONING]

    fields = getattr(interpretation, "fields", None)
    if not getattr(interpretation, "accepted", False) or not isinstance(fields, dict) or not fields:
        return [PENDING_REASONING]

    import validate_card

    findings = validate_card.validate(fields, result)
    if findings:
        return [
            PENDING_REASONING,
            "",
            f"(A model interpretation was offered and rejected here by the validator: "
            f"{len(findings)} finding(s). The evidence above is unaffected.)",
        ]

    lines = []
    for key in ("headline", "reading", "limits"):
        text = fields.get(key)
        if isinstance(text, str) and text.strip():
            lines.append(text.strip())
            lines.append("")

    if not lines:
        return [PENDING_REASONING]

    model = (getattr(interpretation, "metadata", None) or {}).get("model") or "a model"
    lines.append(
        f"Written by {model} from this run's retrieved evidence and checked against it "
        "before printing. Every number and identifier above appears in the sections "
        "above; no model wrote or changed any of them."
    )
    return lines


# ---------------------------------------------------------------- 10. next action

def _best_estimate(estimates):
    complete = [
        row for row in estimates
        if all(_float(row.get(key)) is not None for key in ("b", "se", "pval"))
    ]
    if not complete:
        return None
    return min(complete, key=lambda row: _float(row.get("pval")))


def _next_action_a(result) -> list:
    best = _best_estimate(_rows(_envelope(result, "mr"), "estimates"))
    lines = []
    if best is not None:
        lines.append(
            "Open the retrieved row at its source before quoting it. The smallest "
            f"retrieved p-value is {_text(best.get('exposure_id'))} -> "
            f"{_text(best.get('outcome_id'))} ({_or_unknown(best.get('method'))}): "
            f"b {_effect(best.get('b'))}, se {_effect(best.get('se'))}, "
            f"p {_pvalue(best.get('pval'))}, nsnp {_nsnp(best.get('nsnp'))}."
        )
    else:
        lines.append(
            "Open the retrieved rows at their source before quoting them; no single row "
            "carries a full effect size, uncertainty and p-value."
        )
    lines.append("")
    lines.extend(_bullets([
        "Confirm what one unit of the exposure dataset means before repeating the "
        "effect size: raw and rank-inverse-normalised deposits of one measurement "
        "differ by orders of magnitude and this snapshot carries no unit for some of them.",
        "Treat repeated rows as one study: MR-EVE returns one row per method, and one "
        "study deposited under several OpenGWAS ids returns one row per id.",
        "No formal sensitivity analysis is retrieved with these MR rows - no heterogeneity "
        "or pleiotropy test. Read the source completeness block in section 3; SNP counts "
        "are shown where retrieved, and colocalisation is a separate evidence arm.",
        "This is one direction only. Nothing here is a statement about the disease "
        "acting on the metabolite.",
    ]))
    return lines


def _next_action_b(result) -> list:
    exposures = _rows(_envelope(result, "instruments"), "exposures")
    scored = [row for row in exposures if _float(row.get("gws_hits")) is not None]
    datasets = _rows(_envelope(result, "outcomes"), "datasets")
    lines = []
    if scored and datasets:
        best = max(scored, key=lambda row: _float(row.get("gws_hits")))
        outcome = datasets[0]
        lines.append(
            "No MR estimate was retrieved, but the pair is analysis-ready in this "
            f"snapshot: exposure dataset {_text(best.get('id'))} "
            f"({_text(best.get('trait'))}, {_or_unknown(best.get('platform'))}, "
            f"n {_count(best.get('sample_size'))}) carries "
            f"{_count(best.get('gws_hits'))} genome-wide significant hit(s), and "
            f"outcome dataset {_text(outcome.get('id'))} "
            f"({_text(outcome.get('trait'))}, n {_count(outcome.get('sample_size'))}) "
            "is available. Running the MR is the next step, and it is a step this "
            "build does not take."
        )
    else:
        lines.append(
            "No MR estimate was retrieved. The classifier read this pair as "
            "analysis-ready; the datasets behind that call are in section 4."
        )
    lines.append("")
    lines.extend(_bullets([
        "Check ancestry: the exposure and outcome populations are printed per dataset "
        "in section 4 and must match before a two-sample MR means anything.",
        "Check sample overlap. It is not checked anywhere in this build, it is the "
        "first thing a reviewer asks, and UK Biobank sits on both sides of many pairs.",
        "Check the unit and the assay platform of the exposure dataset before "
        "interpreting any effect size you get.",
        "Analysis-ready is a statement about data availability. It is not a prior that "
        "an effect exists.",
    ]))
    return lines


def _next_action_c(result) -> list:
    actions = [
        "Nothing sufficient was retrieved for this pair, so there is no estimate to "
        "check and no analysis to run yet. State C is a statement about what could be "
        "retrieved from these releases, never about the biology.",
        "",
    ] + _bullets([
        "Read the caveats in section 8 first: they name which arm was empty and which "
        "arm failed, and those are different problems.",
        "Widen the metabolite synonyms. A metabolite absent from this OpenGWAS release "
        "under one name can be present under another.",
        "A failed request (an error envelope) should simply be retried before anything "
        "is concluded from it.",
    ])
    if _envelope(result, "gem") is None:
        actions.extend(_bullets([
            "The literature MR arm (MVP2) is not integrated in this build, and Human-GEM "
            "biochemical context was not assessed in this run. Neither omission is a "
            "negative biological finding.",
        ]))
    else:
        actions.extend(_bullets([
            "The literature MR arm (MVP2) is not integrated in this build. Human-GEM "
            "results, when present above, are biochemical context and cannot supply the "
            "missing metabolite-disease causal evidence or change State C.",
        ]))
    return actions


def _section_next_action(result) -> list:
    state = _text(result.get("state"))
    if state == "A":
        return _next_action_a(result)
    if state == "B":
        return _next_action_b(result)
    if state == "C":
        return _next_action_c(result)
    return [
        "The run returned no recognised evidence state, so no next action is derived "
        "here. Read section 8 for what the run did record."
    ]


# ---------------------------------------------------------------- 11. provenance

def _url_digest(url) -> str:
    """Host and path in full; the query string, which is where a 6,000-character synonym
    sweep ends up, cut to MAX_QUERY_CHARS. A reader still sees which endpoint was hit."""
    text = str(url or "").strip()
    if not text:
        return "no URL recorded by this tool"
    parts = urlsplit(text)
    head = (parts.netloc + parts.path) if parts.netloc else text.split("?")[0]
    if not parts.query:
        return head or text
    query = parts.query
    if len(query) > MAX_QUERY_CHARS:
        query = query[:MAX_QUERY_CHARS] + "…"
    return f"{head}?{query}"


def _ledger_path(result) -> Path | None:
    raw = str(result.get("ledger_path") or "").strip()
    return Path(raw) if raw else None


def _read_ledger(path) -> list:
    """Every envelope of this run, in call order, from the file the RESULT names - not
    from a path rebuilt out of a stem. A line that will not parse is skipped here and
    counted in the line that follows the table."""
    entries = []
    unreadable = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                unreadable += 1
    return [entries, unreadable]


def snapshot_ledger(result: dict) -> list:
    """This run's ledger lines, read ONCE, for a caller that still holds the run lock.

    Two mentions of the same pair share one ledger filename, so a file re-opened after
    the lock is released can be the next run's file, half written. A caller reads the
    lines while it still owns the run and puts them in the result under
    `LEDGER_ENTRIES_KEY`; section 11 then renders from that list and never touches disk.
    It also makes `render_card` reproducible from a saved result.

    Never raises: a provenance section is not worth a reply.
    """
    try:
        path = _ledger_path(result if isinstance(result, dict) else {})
        if path is None:
            return []
        entries, _unreadable = _read_ledger(path)
        return [entry for entry in entries if isinstance(entry, dict)]
    except Exception:
        return []


def _ledger_snapshot(result):
    """The caller's own ledger lines when it carried them, else None."""
    block = result.get(LEDGER_ENTRIES_KEY) if isinstance(result, dict) else None
    if not isinstance(block, list):
        return None
    return [entry for entry in block if isinstance(entry, dict)]


def _tool_tally(entries) -> Counter:
    return Counter(
        _or_unknown(entry.get("tool")) for entry in entries if isinstance(entry, dict)
    )


def _tally_text(tally: Counter) -> str:
    if not tally:
        return "nothing"
    return ", ".join(
        name if count == 1 else f"{name} x{count}"
        for name, count in sorted(tally.items())
    )


def _digest_rows(entries) -> list:
    rows = []
    for index, entry in enumerate(entries, start=1):
        envelope = entry if isinstance(entry, dict) else {}
        rows.append([
            str(index),
            _or_unknown(envelope.get("tool")),
            _status(envelope),
            _url_digest(envelope.get("url")),
            _or_unknown(envelope.get("retrieved_at")),
        ])
    return rows


def _section_provenance(result) -> list:
    path = _ledger_path(result)
    counted = result.get("n_ledger_entries")
    own = [envelope for _heading, envelope in _all_envelopes(result)]
    lines = []
    entries = []
    unreadable = 0
    fallback = False

    snapshot = _ledger_snapshot(result)
    if snapshot is not None:
        entries = snapshot
        lines.append(
            f"Ledger: `{_text(path.name) if path is not None else 'no file named by this run'}`"
            f" - {_count(counted)} entry(ies) counted by the run, {_count(len(entries))} "
            "carried in this run's own result and rendered from there. The file was not "
            "re-opened at render time, so this digest cannot belong to another run of the "
            "same pair."
        )
    elif path is None:
        lines.append(
            "This run wrote no ledger file, so the digest below is built from the "
            "envelopes carried in the run's own result."
        )
        fallback = True
    else:
        try:
            entries, unreadable = _read_ledger(path)
            lines.append(
                f"Ledger: `{_text(path.name)}` - {_count(counted)} entry(ies) counted by "
                f"the run, {_count(len(entries))} read back at render time."
            )
        except OSError as exc:
            lines.append(
                f"Ledger `{_text(path.name)}` could not be read at render time "
                f"({type(exc).__name__}), so the digest below is built from the "
                "envelopes carried in the run's own result instead."
            )
            fallback = True

    # The digest must never silently describe a DIFFERENT run. Two mentions of one pair
    # share a ledger filename, so the file this result names can have been truncated and
    # rewritten by the next run before it was read here; the count line flags a mismatch
    # in numbers, but the rows themselves would carry no warning at all.
    if entries and own:
        found, expected = _tool_tally(entries), _tool_tally(own)
        if found != expected:
            lines.append(
                "The entries above do not match the envelopes this run carries "
                f"(ledger: {_tally_text(found)}; run: {_tally_text(expected)}), so they "
                "describe a different run of this pair. The digest below is built from "
                "the run's own envelopes instead."
            )
            fallback = True

    if fallback or not entries:
        if not fallback:
            lines.append(
                "No readable ledger entry reached this renderer, so the digest below is "
                "built from the envelopes carried in the run's own result instead."
            )
        entries = own

    lines.append("")
    headers = ["#", "Tool", "Status", "Source URL (query cut at 80 characters)", "Retrieved at"]
    rows = _digest_rows(entries)
    if rows:
        lines.extend(_table(headers, rows))
    else:
        lines.append("No envelope was recorded for this run.")
    lines.append("")
    if unreadable:
        lines.append(
            f"{_count(unreadable)} ledger line(s) could not be parsed and are not in the "
            "table above. They are still in the file."
        )
        lines.append("")
    # The closing clause used to assert that section 3 holds estimates. On a State B or
    # State C card section 3 says the opposite, so the last sentence of the card
    # contradicted the card.
    closing = (
        "Sections 1 and 3 to 8, 10 and this one are rendered by code from the envelopes "
        "above; section 2's state and reason come from `classify.classify_state`, a pure "
        "function. No model wrote any of them, and "
    )
    if _rows(_envelope(result, "mr"), "estimates"):
        closing += (
            "the estimates in section 3 are retrieved from a pre-computed source and are "
            "not computed here."
        )
    else:
        closing += (
            "no MR estimate was retrieved for this pair in this snapshot, so section 3 "
            "quotes none."
        )
    lines.append(closing)
    return lines


# ---------------------------------------------------------------- the card
#
# Three sections carry a colocalisation block, and each one is built by composing the
# existing section builder with a coloc builder rather than by editing it. Two retrievals,
# two blocks, one section: the MR block and the gene blocks stay exactly what they were,
# and the colocalisation block beside them is unmistakably a different retrieval.

def _section_mr_evidence(result) -> list:
    """Section 3: the retrieved MR estimates, then the retrieved colocalisation for the
    same pair."""
    lines = list(_section_mr(result))
    lines.append("")
    lines.extend(_coloc_block(result))
    return lines


def _section_genes_evidence(result) -> list:
    """Section 5: the genes this run names, then the QTL colocalisations joined to them by
    symbol."""
    lines = list(_section_genes(result))
    lines.append("")
    lines.extend(_coloc_gene_block(result))
    return lines


def _section_dossiers_evidence(result) -> list:
    """Section 6: each gene's dossier, with its colocalisation line appended under it."""
    dossier = _dossier(result)
    lines = list(_section_dossiers(result))
    if not dossier:
        return lines
    lines.append("")
    lines.append("**Colocalisation by gene (retrieved from Open Targets)**")
    lines.append("")
    for gene in sorted(dossier):
        lines.append(f"### {_text(gene)}")
        lines.append("")
        lines.extend(_coloc_gene_lines(result, gene))
        lines.append("")
    return lines


_BUILDERS = (
    _section_pair,
    _section_verdict,
    _section_mr_evidence,
    _section_instruments,
    _section_genes_evidence,
    _section_dossiers_evidence,
    _section_via_enzyme,
    _section_caveats,
    _section_reasoning,
    _section_next_action,
    _section_provenance,
)


def _title(result) -> str:
    metabolite = _or_unknown(_entity(result, "metabolite").get("query"))
    disease = _or_unknown(_entity(result, "disease").get("query"))
    return f"# MetaboCausal evidence card - {metabolite} x {disease}"


def render_card(result: dict, interpretation=None) -> str:
    """The full 11-section markdown card for one `pipeline.run_pair` result.

    Every number comes from an envelope in `result["envelopes"]` or from a line of the
    ledger the result names; the state and the verdict sentence come from
    `classify.classify_state` through `result["state"]` and `result["reason"]`.

    `interpretation` is an `llm.interpret.Interpretation` and is the ONLY argument through
    which model-written prose can arrive. It reaches section 9 and nothing else, and
    section 9 re-validates it against this run before printing a word of it - so omitting
    the argument, passing a rejected result, or passing a fabricated one all produce the
    same card as before 1F landed. No model can move a number here, because no number here
    comes from a model.

    Never raises. A section that cannot be built prints why, in its own place, and the
    other ten still render - slack_app.py calls this inside a Bolt listener, where an
    exception would take the whole reply with it.
    """
    if not isinstance(result, dict):
        result = {}

    lines = [_title(result), ""]
    for number, (heading, builder) in enumerate(zip(SECTIONS, _BUILDERS), start=1):
        lines.append(f"## {number}. {heading}")
        lines.append("")
        try:
            body = (
                builder(result, interpretation)
                if builder is _section_reasoning
                else builder(result)
            )
        except Exception as exc:
            body = [RENDER_FAILURE.format(detail=type(exc).__name__)]
        lines.extend(str(line) for line in body)
        lines.append("")

    text = "\n".join(lines)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.rstrip() + "\n"


def card_stem(result: dict) -> str:
    """The run's stem: the ledger filename without its suffix, which is the name
    `pipeline.stem_for` already chose for this run. Only when the run wrote no ledger is
    a stem rebuilt here from the two names, by the same rule - the ledger name is the
    authority whenever there is one."""
    if not isinstance(result, dict):
        return "unknown"
    path = _ledger_path(result)
    if path is not None and path.name.endswith(LEDGER_SUFFIX):
        stem = path.name[: -len(LEDGER_SUFFIX)]
        if stem:
            return stem
    sides = []
    for side in ("metabolite", "disease"):
        text = _SLUG_STRIP.sub("-", str(_entity(result, side).get("query") or "").lower())
        sides.append(text.strip("-") or "unknown")
    return "_".join(sides)


def card_filename(result: dict) -> str:
    """The filename this card is written and uploaded under: "card_<stem>.md"."""
    return f"card_{card_stem(result)}.md"


def _default_model_for(provider: str) -> str:
    """The provider's first configured model, or the name itself so the error names it.

    Resolving badly here would raise inside argument handling; letting the unusable value
    through means `llm.interpret` reports it through the same path as every other failure,
    and the card still renders."""
    try:
        from llm import default_model

        return default_model(provider)
    except Exception:                                   # noqa: BLE001 - reported downstream
        return str(provider)


if __name__ == "__main__":
    import argparse
    import sys

    REPO_ROOT = Path(__file__).resolve().parent
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    parser = argparse.ArgumentParser(
        description = "Render one pair's card from the cached demo envelopes, or live.",
    )
    parser.add_argument(
        "pair",
        nargs   = "?",
        default = "urate|gout",
    )
    parser.add_argument(
        "--live",
        action = "store_true",
        help   = "call pipeline.run_pair instead of reading data/demo_card_inputs.json",
    )
    parser.add_argument(
        "--out",
        default = None,
        help    = "write the card here instead of stdout",
    )
    # Section 9 only. Without --interpret the card is byte for byte what it was before the
    # LLM layer existed, and that is the default on purpose: the model is an enhancement.
    parser.add_argument(
        "--interpret",
        action = "store_true",
        help   = "ask a model to write section 9, then validate it against this run",
    )
    parser.add_argument(
        "--provider",
        default = "claude",
        help    = "claude | chatgpt | gemini (with --interpret; default: claude)",
    )
    parser.add_argument(
        "--model",
        default = None,
        help    = "model id (with --interpret; default: the provider's first configured)",
    )
    args = parser.parse_args()

    metabolite, _, disease = args.pair.partition("|")

    if args.live:
        import pipeline

        run = pipeline.run_pair(
            metabolite,
            disease or "gout",
        )
    else:
        cached = json.loads(
            (REPO_ROOT / "data" / "demo_card_inputs.json").read_text(encoding="utf-8")
        )
        entry = cached["pairs"][args.pair]
        envelopes = entry["envelopes"]
        sample = entry["inputs_from_1a"]
        # The cached snapshot and the frozen cards/<stem>.ledger.jsonl on disk are two
        # different runs of the same pair, so pointing section 11 at the frozen file
        # would show a status the tables above disagree with. This writes the snapshot's
        # own four envelopes to a `demo_`-prefixed ledger instead - the same namespacing
        # rule the Slack shell uses, so no frozen ledger is ever truncated here.
        demo_stem = f"demo_{entry['ledger_stem']}"
        demo_ledger = REPO_ROOT / "cards" / f"{demo_stem}{LEDGER_SUFFIX}"
        demo_ledger.parent.mkdir(parents=True, exist_ok=True)
        recorded = [
            envelopes[name] for name in (
                "get_mr_result",
                "get_mqtl_instruments",
                "find_outcome_datasets",
                "get_gwas_catalog",
            )
            if envelopes.get(name) is not None
        ]
        demo_ledger.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in recorded) + "\n",
            encoding = "utf-8",
        )
        run = {
            "state":            entry["classify_state"]["state"],
            "reason":           entry["classify_state"]["reason"],
            "metabolite":       {
                "query":         sample["metabolite"]["input"],
                "input":         sample["metabolite"]["input"],
                "label":         sample["metabolite"]["label"],
                "id":            sample["metabolite"]["chebi"],
                "synonyms":      sample["metabolite"]["synonyms"],
                "resolved":      True,
                "resolved_from": args.pair,
            },
            "disease":          {
                "query":         sample["disease"]["input"],
                "input":         sample["disease"]["input"],
                "label":         sample["disease"]["label"],
                "id":            sample["disease"]["id"],
                "synonyms":      sample["disease"]["synonyms"],
                "resolved":      True,
                "resolved_from": args.pair,
            },
            "envelopes":        {
                "mr":          envelopes["get_mr_result"],
                "instruments": envelopes["get_mqtl_instruments"],
                "outcomes":    envelopes["find_outcome_datasets"],
                "catalog":     envelopes["get_gwas_catalog"],
            },
            "ledger_path":      str(demo_ledger),
            "n_ledger_entries": len(recorded),
            "notes":            [
                "rendered from data/demo_card_inputs.json, a CACHED SNAPSHOT of these "
                "envelopes taken 2026-09-10, not a live run.",
            ],
        }

    interpretation = None
    if args.interpret:
        # The surface reads the environment and hands the layer a credential; nothing
        # under llm/ reaches for a key itself. See llm/cli.py for why that split is here.
        from llm.cli import credential_from_env
        from llm.interpret import interpret as write_section_nine

        interpretation = write_section_nine(
            run,
            provider   = args.provider,
            model      = args.model or _default_model_for(args.provider),
            credential = credential_from_env(args.provider),
        )
        # Printed to stderr so it never lands inside a card redirected to a file. The
        # outcome is always reported - a silently missing section 9 would be indis-
        # tinguishable from one that was never asked for.
        print(interpretation.note(), file=sys.stderr)

    card = render_card(run, interpretation)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(card, encoding="utf-8")
        print(f"wrote {target} ({len(card):,} characters) as {card_filename(run)}")
    else:
        print(card)
