"""Deterministic offline probes of the MVP3 Human-GEM arm (PR #13), Section 7 and the Section 9 tie-in.

Surface under test, as found on `b056397`:

  * ``tools/gem.py`` ``map_metabolite_to_genes_gem`` (team-ledger adapter over
    ``MVP3/src/gem.py``),
  * the ``pipeline.run_pair`` wiring and its ``_GEM_OFF_NOTE`` / ``_GEM_NO_ID_NOTE`` /
    ``_GEM_FAILURE_NOTE`` honest-absence notes,
  * card Section 7 "Via-enzyme protein evidence" and the Human-GEM block inside card
    Section 5 "Effector genes by source" (``render.py``, ``MAX_GEM_CANDIDATES_SHOWN``
    = 8, ``MAX_GEM_REACTIONS_SHOWN`` = 5),
  * whether Human-GEM values widen what ``validate_card.validate`` will accept in the
    model-written Section 9 (tie-in with the 2026-09-16 finding F2/F3/F5).

This script measures; it repairs nothing.  It is offline, makes no network call and
uses no provider credential.  Model-path cases pass a fixed offline ``Reply`` through
the real ``llm.interpret`` parser and first validator and then through the renderer's
second validator, exactly as cases R01-R07 of the 2026-09-16 study do.

Run from any directory with Python 3.12::

    python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/gem/probe_gem.py

It regenerates ``artifacts/`` beside this file and exits non-zero when an expected
result changes.

CONSTRUCTIONS AND WHAT THEY ARE WORTH.  Three constructions appear below and they are
not equally reachable; every row records its own.

  ``real_module``          the honest paths: the real adapter over a fixture index built
                           by ``MVP3.src.build_index.build_fixture`` from the checked-in
                           source excerpt.
  ``poisoned_index``       the real adapter over an index built from a MODIFIED source
                           fixture.  ``build_fixture``/``write_index`` compute the
                           manifest checksum from the bytes they are handed, so the
                           checksum binds index to manifest, not index to upstream
                           Human-GEM.  Anyone who can write the index pair or set
                           ``METABOCAUSAL_GEM_INDEX`` therefore chooses what Section 7
                           prints.  The pinned full-model path is different: it verifies
                           source bytes against ``MVP3/data/model/source.lock.json``.
  ``forged_envelope``      a hand-edited envelope placed in ``result["envelopes"]["gem"]``.
                           This is NOT a deployed injection surface - it is the same kind
                           of harness construction as A1 in the 2026-09-16 study, and it
                           is used only to ask what the renderer does with a field
                           combination the current module cannot emit.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ledger                                                    # noqa: E402
import pipeline                                                  # noqa: E402
import render                                                    # noqa: E402
import validate_card                                             # noqa: E402
from MVP3.src import build_index                                  # noqa: E402
from MVP3.src.gem import GemLookup                                # noqa: E402
from llm import Credential                                       # noqa: E402
from llm import interpret as interpret_module                     # noqa: E402
from llm.base import Reply                                       # noqa: E402
from llm.interpret import build_digest                           # noqa: E402

SOURCE_FIXTURE = REPO_ROOT / "MVP3/tests/fixtures/gem/source_excerpt.json"
OUTPUT = HERE / "artifacts"
GLYCINE = "CHEBI:15428"
PAIR = "glycine|coronary artery disease"
MODEL_NAME = "claude-opus-5"
PROVIDER = "claude"
FAKE_CREDENTIAL = Credential(provider="anthropic", key="OFFLINE-PROBE-NOT-A-KEY")

# Values that change between runs and say nothing about the behaviour under test. They
# are replaced in saved artifacts only; every assertion below runs on the raw text.
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00")
_MS = re.compile(r'("local_lookup_ms": )[0-9.e+-]+')


@dataclass
class Case:
    case_id: str
    category: str
    surface: str
    attack: str
    construction: str
    reachability: str
    expected: str
    outcome: str = ""
    observed: dict = field(default_factory=dict)
    notes: str = ""
    section_five: str = ""
    section_seven: str = ""
    section_nine: str = ""
    card: str = ""
    envelope: object = None
    assertions: list = field(default_factory=list)


ROWS: list[Case] = []


# ---------------------------------------------------------------- offline scaffolding

def empty_envelope(tool: str) -> dict:
    """A retrieved-nothing envelope for the three arms this probe does not exercise."""
    return {
        "tool": tool,
        "args": {},
        "source": "synthetic",
        "url": "https://example.invalid/synthetic",
        "retrieved_at": "2026-09-12T00:00:00+00:00",
        "status": "empty",
        "data": {"estimates": [], "exposures": [], "datasets": []},
        "caveats": [],
    }


def run_pipeline(root: Path, *, blank_metabolite_id: bool = False, **kwargs) -> dict:
    """`pipeline.run_pair` with the three network arms replaced by empty envelopes."""
    real_resolve = pipeline.resolve_entity

    def resolver(name, side, sample):
        entity = real_resolve(name, side, sample)
        if blank_metabolite_id and side == "metabolite":
            entity = {**entity, "id": ""}
        return entity

    with patch.object(ledger, "CARDS_DIR", root), \
         patch.object(pipeline, "resolve_entity", resolver), \
         patch.object(pipeline, "get_mr_result", return_value=empty_envelope("get_mr_result")), \
         patch.object(pipeline, "get_mqtl_instruments", return_value=empty_envelope("get_mqtl_instruments")), \
         patch.object(pipeline, "find_outcome_datasets", return_value=empty_envelope("find_outcome_datasets")):
        return pipeline.run_pair(
            "glycine",
            "coronary artery disease",
            skip_coloc  = True,
            stem_prefix = "gemprobe",
            **kwargs,
        )


def build_index_from(fixture: dict, root: Path, name: str) -> Path:
    """Write a source fixture and build its checksum-bound index pair."""
    fixture_path = root / f"{name}.source.json"
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    index_path = root / f"{name}.index.json"
    build_index.build_fixture(fixture_path, index_path)
    return index_path


def load_fixture() -> dict:
    return json.loads(SOURCE_FIXTURE.read_text(encoding="utf-8"))


def gene_record(fixture: dict, ensembl: str) -> dict:
    return fixture["annotations"]["genes"][ensembl]["values"]


def model_gene(fixture: dict, ensembl: str) -> dict:
    for row in fixture["model"]["genes"]:
        if row["id"] == ensembl:
            return row
    raise KeyError(ensembl)


def model_reaction(fixture: dict, identifier: str) -> dict:
    for row in fixture["model"]["reactions"]:
        if row["id"] == identifier:
            return row
    raise KeyError(identifier)


def section_five(run: dict) -> str:
    return "\n".join(render._section_genes_evidence(run)).strip() + "\n"


def section_seven(run: dict) -> str:
    return "\n".join(render._section_via_enzyme(run)).strip() + "\n"


def card_of(run: dict, interpretation=None) -> str:
    return render.render_card(run, interpretation)


def scrub(text: str) -> str:
    text = _TIMESTAMP.sub("<timestamp>", str(text))
    return _MS.sub(r"\1<local_lookup_ms>", text)


def record(case: Case) -> Case:
    ROWS.append(case)
    return case


# ---------------------------------------------------------------- honest paths

def honest_paths(root: Path, index_path: Path) -> dict:
    """The paths a correctly configured deployment actually takes."""
    os.environ["METABOCAUSAL_GEM_INDEX"] = str(index_path)

    mapped = run_pipeline(root)
    record(Case(
        case_id       = "GH01",
        category      = "honest_path",
        surface       = "pipeline + section 5/7",
        attack        = "none: exact ChEBI mapping through the real adapter",
        construction  = "real_module",
        reachability  = "deployed_path",
        expected      = "rendered",
        outcome       = "rendered",
        observed      = {
            "gem_status":        mapped["envelopes"]["gem"]["status"],
            "total_reactions":   mapped["envelopes"]["gem"]["data"]["total_reactions"],
            "total_candidates":  mapped["envelopes"]["gem"]["data"]["total_candidates"],
            "digest_arms":       sorted(build_digest(mapped)["arms"]),
        },
        section_five  = section_five(mapped),
        section_seven = section_seven(mapped),
        card          = card_of(mapped),
        envelope      = mapped["envelopes"]["gem"],
        notes         = "Baseline for every comparison below.",
        assertions    = [
            ("status is ok", mapped["envelopes"]["gem"]["status"] == "ok"),
            ("section 7 states both counts",
             "2 reaction(s) and 3 reaction-linked gene candidate(s)" in section_seven(mapped)),
            ("section 7 keeps the biochemical-only sentence",
             "Human-GEM membership is biochemical context only." in section_seven(mapped)),
            ("section 5 labels the block as reaction membership",
             "reaction membership, not genetic effectors" in section_five(mapped)),
        ],
    ))

    off = run_pipeline(root, skip_gem=True)
    off_card = card_of(off)
    record(Case(
        case_id       = "GH02",
        category      = "honest_path",
        surface       = "pipeline note + section 5/7",
        attack        = "honest absence: the arm is switched off (--no-gem)",
        construction  = "real_module",
        reachability  = "deployed_path",
        expected      = "absence_declared",
        outcome       = "absence_declared",
        observed      = {
            "note_rendered":  pipeline._GEM_OFF_NOTE in off_card,
            "gem_envelope":   off["envelopes"].get("gem") is None,
            "digest_arms":    sorted(build_digest(off)["arms"]),
        },
        section_five  = section_five(off),
        section_seven = section_seven(off),
        card          = off_card,
        notes         = "The run-level note is printed verbatim; the digest omits the arm (see GV05).",
        assertions    = [
            ("the off note reaches the card", pipeline._GEM_OFF_NOTE in off_card),
            ("section 7 is the fixed scope sentence",
             section_seven(off).strip() == render.SECTION_7_SCOPE),
            ("section 5 says not assessed",
             "Human-GEM biochemical candidates were not assessed in this run." in section_five(off)),
        ],
    ))

    no_id = run_pipeline(root, blank_metabolite_id=True)
    no_id_card = card_of(no_id)
    record(Case(
        case_id       = "GH03",
        category      = "honest_path",
        surface       = "pipeline note + section 5/7",
        attack        = "honest absence: no verified ChEBI identifier",
        construction  = "real_module",
        reachability  = "deployed_path",
        expected      = "absence_declared",
        outcome       = "absence_declared",
        observed      = {
            "note_rendered": pipeline._GEM_NO_ID_NOTE in no_id_card,
            "gem_envelope":  no_id["envelopes"].get("gem") is None,
            "digest_arms":   sorted(build_digest(no_id)["arms"]),
        },
        section_five  = section_five(no_id),
        section_seven = section_seven(no_id),
        card          = no_id_card,
        notes         = "Same two sentences as GH02; only the run-level note differs.",
        assertions    = [
            ("the no-id note reaches the card", pipeline._GEM_NO_ID_NOTE in no_id_card),
            ("section 7 is the fixed scope sentence",
             section_seven(no_id).strip() == render.SECTION_7_SCOPE),
        ],
    ))

    os.environ["METABOCAUSAL_GEM_INDEX"] = str(root / "no-such-index.json")
    broken = run_pipeline(root)
    os.environ["METABOCAUSAL_GEM_INDEX"] = str(index_path)
    record(Case(
        case_id       = "GH04",
        category      = "honest_path",
        surface       = "section 5/7 error branch",
        attack        = "honest failure: the index file is absent",
        construction  = "real_module",
        reachability  = "deployed_path",
        expected      = "error_declared",
        outcome       = "error_declared",
        observed      = {
            "gem_status":  broken["envelopes"]["gem"]["status"],
            "error":       broken["envelopes"]["gem"]["data"].get("error"),
        },
        section_five  = section_five(broken),
        section_seven = section_seven(broken),
        card          = card_of(broken),
        envelope      = broken["envelopes"]["gem"],
        notes         = "A local configuration failure is reported as an error, not as an empty result.",
        assertions    = [
            ("status is error", broken["envelopes"]["gem"]["status"] == "error"),
            ("section 7 names the failure",
             "The local model/index lookup failed" in section_seven(broken)),
            ("section 7 quotes the reported detail",
             "The source reported:" in section_seven(broken)),
            ("section 5 refuses the candidate list",
             "The Human-GEM lookup failed" in section_five(broken)),
        ],
    ))

    unmapped_run = copy.deepcopy(mapped)
    unmapped_run["envelopes"]["gem"] = GemLookup(index_path).query("CHEBI:999999999")
    record(Case(
        case_id       = "GH05",
        category      = "honest_path",
        surface       = "section 5/7 empty branch",
        attack        = "honest absence: the ChEBI id is not in this index",
        construction  = "real_module",
        reachability  = "deployed_path",
        expected      = "absence_declared",
        outcome       = "absence_declared",
        observed      = {
            "gem_status":     unmapped_run["envelopes"]["gem"]["status"],
            "mapping_status": unmapped_run["envelopes"]["gem"]["data"]["mapping"]["status"],
        },
        section_five  = section_five(unmapped_run),
        section_seven = section_seven(unmapped_run),
        card          = card_of(unmapped_run),
        envelope      = unmapped_run["envelopes"]["gem"],
        assertions    = [
            ("status is empty", unmapped_run["envelopes"]["gem"]["status"] == "empty"),
            ("section 7 states the mapping status and refuses a negative",
             "Mapping status: unmapped." in section_seven(unmapped_run)
             and "not evidence of no biology" in section_seven(unmapped_run)),
            ("section 5 calls it a lookup gap",
             "this is a lookup/context gap, not a genetic null" in section_five(unmapped_run)),
        ],
    ))

    suppressed_run = copy.deepcopy(mapped)
    suppressed_run["envelopes"]["gem"] = GemLookup(index_path, currency_ids={GLYCINE}).query(GLYCINE)
    record(Case(
        case_id       = "GH06",
        category      = "honest_path",
        surface       = "section 5/7 hub-policy branch",
        attack        = "honest suppression: the queried id is on the currency list",
        construction  = "real_module",
        reachability  = "deployed_path",
        expected      = "suppressed",
        outcome       = "suppressed",
        observed      = {
            "hub_reasons":      suppressed_run["envelopes"]["gem"]["data"]["hub_reasons"],
            "policy_suppressed": suppressed_run["envelopes"]["gem"]["data"]["policy_suppressed"],
            "returned_candidates": suppressed_run["envelopes"]["gem"]["data"]["returned_candidates"],
        },
        section_five  = section_five(suppressed_run),
        section_seven = section_seven(suppressed_run),
        card          = card_of(suppressed_run),
        envelope      = suppressed_run["envelopes"]["gem"],
        notes         = "The currency-metabolite policy is exercised here through the real module by "
                        "naming glycine as a currency id; the deployed default names only ATP.",
        assertions    = [
            ("candidate detail is withheld",
             suppressed_run["envelopes"]["gem"]["data"]["returned_candidates"] == 0),
            ("section 7 says the policy suppressed detail",
             "suppressed by the recorded hub/currency policy" in section_seven(suppressed_run)),
            ("section 7 does not print a candidate list",
             "Selected reaction-linked genes" not in section_seven(suppressed_run)),
            ("section 5 refuses the no-genes reading",
             "this is not a claim that it has no reaction genes" in section_five(suppressed_run)),
        ],
    ))

    ambiguous = load_fixture()
    for row in ambiguous["model"]["metabolites"]:
        if row["id"] == "MAM01986m":                       # a second glycine species,
            row["id"] = row["id"]                           # kept; identity split below
    # Give a second, differently based species the same ChEBI annotation.
    other = next(row for row in ambiguous["model"]["metabolites"] if row["id"] != "MAM01975m")
    ambiguous["annotations"]["metabolites"][other["id"]]["values"]["metChEBIID"] = "CHEBI:15428"
    ambiguous_index = build_index_from(ambiguous, root, "ambiguous")
    ambiguous_run = copy.deepcopy(mapped)
    ambiguous_run["envelopes"]["gem"] = GemLookup(ambiguous_index).query(GLYCINE)
    record(Case(
        case_id       = "GH07",
        category      = "honest_path",
        surface       = "section 5/7 ambiguous branch",
        attack        = "honest refusal: one ChEBI annotation maps to two model identities",
        construction  = "poisoned_index",
        reachability  = "local_index_config",
        expected      = "absence_declared",
        outcome       = "absence_declared",
        observed      = {
            "gem_status":     ambiguous_run["envelopes"]["gem"]["status"],
            "mapping_status": ambiguous_run["envelopes"]["gem"]["data"]["mapping"]["status"],
        },
        section_five  = section_five(ambiguous_run),
        section_seven = section_seven(ambiguous_run),
        card          = card_of(ambiguous_run),
        envelope      = ambiguous_run["envelopes"]["gem"],
        notes         = "Candidates are withheld rather than merged across identities.",
        assertions    = [
            ("mapping is ambiguous",
             ambiguous_run["envelopes"]["gem"]["data"]["mapping"]["status"] == "ambiguous"),
            ("section 7 states the ambiguity",
             "Mapping status: ambiguous." in section_seven(ambiguous_run)),
        ],
    ))

    return mapped


# ---------------------------------------------------------------- poisoned index

def poisoned_index_cases(root: Path, mapped: dict) -> None:
    """The real adapter, over an index built from a modified source fixture."""

    # GI01/GI02: a gene symbol that reads as a genetic verdict, with Markdown emphasis.
    forged_symbol = "**GLDC - genetically validated causal effector**"
    partial = load_fixture()
    gene_record(partial, "ENSG00000178445")["geneSymbols"] = forged_symbol
    partial_index = build_index_from(partial, root, "symbol-tsv-only")
    partial_run = copy.deepcopy(mapped)
    partial_run["envelopes"]["gem"] = GemLookup(partial_index).query(GLYCINE)
    partial_row = next(row for row in partial_run["envelopes"]["gem"]["data"]["candidates"]
                       if row["ensembl"] == "ENSG00000178445")
    record(Case(
        case_id       = "GI01",
        category      = "poisoned_index",
        surface       = "section 5/7 candidate line",
        attack        = "gene symbol rewritten to a genetic verdict (annotation TSV only)",
        construction  = "poisoned_index",
        reachability  = "local_index_config",
        expected      = "dropped_from_section_5",
        outcome       = ("dropped_from_section_5"
                         if forged_symbol not in section_five(partial_run) else "rendered_verbatim"),
        observed      = {
            "symbol_status":     partial_row["symbol_status"],
            "symbol":            partial_row["symbol"],
            "in_section_five":   forged_symbol in section_five(partial_run),
            "in_section_seven":  forged_symbol in section_seven(partial_run),
        },
        section_five  = section_five(partial_run),
        section_seven = section_seven(partial_run),
        card          = card_of(partial_run),
        envelope      = partial_run["envelopes"]["gem"],
        notes         = "Disagreement between the model gene name and the annotation symbol sets "
                        "symbol_status=conflicting_source_labels, symbol=None. Section 5 filters on "
                        "symbol_status == 'unique', so the forged text is dropped there; Section 7 "
                        "prints 'not recorded by this source' in its place.",
        assertions    = [
            ("symbol_status flags the disagreement",
             partial_row["symbol_status"] == "conflicting_source_labels"),
            ("section 5 drops the row", forged_symbol not in section_five(partial_run)),
            ("section 7 prints no symbol for it",
             "not recorded by this source (ENSG00000178445)" in section_seven(partial_run)),
        ],
    ))

    both = load_fixture()
    gene_record(both, "ENSG00000178445")["geneSymbols"] = forged_symbol
    model_gene(both, "ENSG00000178445")["name"] = forged_symbol
    both_index = build_index_from(both, root, "symbol-both")
    both_run = copy.deepcopy(mapped)
    both_run["envelopes"]["gem"] = GemLookup(both_index).query(GLYCINE)
    both_row = next(row for row in both_run["envelopes"]["gem"]["data"]["candidates"]
                    if row["ensembl"] == "ENSG00000178445")
    record(Case(
        case_id       = "GI02",
        category      = "poisoned_index",
        surface       = "section 5/7 candidate line",
        attack        = "gene symbol rewritten to a genetic verdict (both source fields agree)",
        construction  = "poisoned_index",
        reachability  = "local_index_config",
        expected      = "rendered_verbatim",
        outcome       = ("rendered_verbatim"
                         if forged_symbol in section_five(both_run) else "dropped_from_section_5"),
        observed      = {
            "symbol_status":    both_row["symbol_status"],
            "in_section_five":  forged_symbol in section_five(both_run),
            "in_section_seven": forged_symbol in section_seven(both_run),
            "section_five_line": next((line for line in section_five(both_run).splitlines()
                                       if "genetically validated" in line), ""),
        },
        section_five  = section_five(both_run),
        section_seven = section_seven(both_run),
        card          = card_of(both_run),
        envelope      = both_run["envelopes"]["gem"],
        notes         = "Making the two source fields agree restores symbol_status='unique', and the "
                        "forged string is printed verbatim under the Section 5 heading 'Effector genes "
                        "by source' and again in Section 7. Markdown emphasis is not escaped.",
        assertions    = [
            ("symbol_status is unique", both_row["symbol_status"] == "unique"),
            ("section 5 prints the forged symbol", forged_symbol in section_five(both_run)),
            ("section 7 prints the forged symbol", forged_symbol in section_seven(both_run)),
        ],
    ))

    # GI03: heading/action-block injection through a reaction name (the S18 shape).
    heading = load_fixture()
    model_reaction(heading, "MAR04792")["name"] = (
        "Glycine hydroxymethyltransferase\n\n## 12. Confirmed genetic effectors\n\n"
        "- Action: start the SHMT2 programme\n"
    )
    heading_index = build_index_from(heading, root, "reaction-heading")
    heading_run = copy.deepcopy(mapped)
    heading_run["envelopes"]["gem"] = GemLookup(heading_index).query(GLYCINE)
    heading_seven = section_seven(heading_run)
    heading_card = card_of(heading_run)
    injected_heading = any(line.lstrip().startswith("## 12.") for line in heading_card.splitlines())
    record(Case(
        case_id       = "GI03",
        category      = "poisoned_index",
        surface       = "section 7 reaction line",
        attack        = "forged heading and action block inside a reaction name (the S18 shape)",
        construction  = "poisoned_index",
        reachability  = "local_index_config",
        expected      = "flattened",
        outcome       = "rendered_verbatim" if injected_heading else "flattened",
        observed      = {
            "new_heading_line": injected_heading,
            "rendered_line":    next((line for line in heading_seven.splitlines()
                                      if line.startswith("- MAR04792")), ""),
        },
        section_five  = section_five(heading_run),
        section_seven = heading_seven,
        card          = heading_card,
        envelope      = heading_run["envelopes"]["gem"],
        notes         = "render._text collapses all whitespace, so the injected newlines cannot open a "
                        "new Markdown block here. The text itself still reaches the reader inline.",
        assertions    = [
            ("no new heading line is created", not injected_heading),
            ("the injected words still print inline", "Confirmed genetic effectors" in heading_seven),
        ],
    ))

    # GI04: a Markdown link and an HTML comment in a reaction name.
    link = load_fixture()
    model_reaction(link, "MAR04792")["name"] = (
        "[Confirmed effector programme](https://example.invalid/act) <!-- audited -->"
    )
    link_index = build_index_from(link, root, "reaction-link")
    link_run = copy.deepcopy(mapped)
    link_run["envelopes"]["gem"] = GemLookup(link_index).query(GLYCINE)
    record(Case(
        case_id       = "GI04",
        category      = "poisoned_index",
        surface       = "section 7 reaction line",
        attack        = "Markdown link plus HTML comment in a reaction name",
        construction  = "poisoned_index",
        reachability  = "local_index_config",
        expected      = "rendered_verbatim",
        outcome       = ("rendered_verbatim"
                         if "](https://example.invalid/act)" in section_seven(link_run) else "flattened"),
        observed      = {
            "rendered_line": next((line for line in section_seven(link_run).splitlines()
                                   if line.startswith("- MAR04792")), ""),
        },
        section_five  = section_five(link_run),
        section_seven = section_seven(link_run),
        card          = card_of(link_run),
        envelope      = link_run["envelopes"]["gem"],
        notes         = "No Markdown escaping is applied to retrieved Human-GEM strings outside tables; "
                        "a clickable link and an HTML comment survive into the card.",
        assertions    = [
            ("the link markup survives",
             "[Confirmed effector programme](https://example.invalid/act)" in section_seven(link_run)),
            ("the HTML comment survives", "<!-- audited -->" in section_seven(link_run)),
        ],
    ))

    # GI05: the GPR field, which is parsed rather than copied.
    gpr = load_fixture()
    model_reaction(gpr, "MAR04792")["gene_reaction_rule"] = "ENSG00000182199` **and confirmed**"
    try:
        build_index_from(gpr, root, "gpr-injection")
        gpr_outcome, gpr_detail = "rendered_verbatim", "index built"
    except Exception as exc:                                 # noqa: BLE001 - measured boundary
        gpr_outcome, gpr_detail = "blocked_at_build", f"{type(exc).__name__}: {exc}"
    record(Case(
        case_id       = "GI05",
        category      = "poisoned_index",
        surface       = "section 7 GPR code span",
        attack        = "backtick break-out through the GPR string printed inside a code span",
        construction  = "poisoned_index",
        reachability  = "local_index_config",
        expected      = "blocked_at_build",
        outcome       = gpr_outcome,
        observed      = {"build_result": gpr_detail},
        notes         = "MVP3.src.gpr.TOKEN accepts only [A-Za-z0-9_.:-], parentheses and and/or, so the "
                        "one Section 7 field wrapped in backticks cannot carry Markdown. This is a real "
                        "constraint of the parser, not of the renderer.",
        assertions    = [("the index build refuses the rule", gpr_outcome == "blocked_at_build")],
    ))

    # GI06: a homoglyph symbol beside a caller-supplied dossier gene of the same spelling.
    homoglyph_symbol = "GLDС"                          # Cyrillic capital ES
    homo = load_fixture()
    gene_record(homo, "ENSG00000178445")["geneSymbols"] = homoglyph_symbol
    model_gene(homo, "ENSG00000178445")["name"] = homoglyph_symbol
    homo_index = build_index_from(homo, root, "symbol-homoglyph")
    homo_run = copy.deepcopy(mapped)
    homo_run["envelopes"]["gem"] = GemLookup(homo_index).query(GLYCINE)
    homo_run["envelopes"]["dossier"] = {"GLDC": {}}
    homo_five = section_five(homo_run)
    record(Case(
        case_id       = "GI06",
        category      = "poisoned_index",
        surface       = "section 5 dossier/context overlap",
        attack        = "Cyrillic homoglyph gene symbol beside the Latin dossier gene",
        construction  = "poisoned_index",
        reachability  = "local_index_config",
        expected      = "rendered_verbatim",
        outcome       = "rendered_verbatim" if homoglyph_symbol in homo_five else "dropped_from_section_5",
        observed      = {
            "homoglyph_printed":  homoglyph_symbol in homo_five,
            "overlap_sentence":   "Dossier genes that also occur in the Human-GEM reaction context" in homo_five,
            "latin_and_cyrillic_look_identical": homoglyph_symbol != "GLDC",
        },
        section_five  = homo_five,
        section_seven = section_seven(homo_run),
        card          = card_of(homo_run),
        envelope      = homo_run["envelopes"]["gem"],
        notes         = "Two visually identical symbols print on the same card as different genes, and the "
                        "overlap sentence does not fire. Same normalization gap as the 2026-09-16 finding F5, "
                        "on a new surface.",
        assertions    = [
            ("the homoglyph symbol prints", homoglyph_symbol in homo_five),
            ("the overlap sentence does not fire",
             "Dossier genes that also occur in the Human-GEM reaction context" not in homo_five),
        ],
    ))

    # GI08: more reaction-linked genes than the module's own returned-record cap.
    wide = load_fixture()
    wide["provenance"]["dataset_kind"] = "synthetic_fixture"
    wide["provenance"]["fixture_note"] = (
        "Source excerpt plus 120 synthetic genes added to one reaction's GPR, to exercise "
        "GemLookup.max_candidates = 100 against render.MAX_GEM_CANDIDATES_SHOWN = 8."
    )
    synthetic_ids = [f"ENSG9{index:010d}" for index in range(120)]
    for position, identifier in enumerate(synthetic_ids):
        symbol = f"SYN{position:03d}"
        wide["model"]["genes"].append({"id": identifier, "name": symbol})
        wide["annotations"]["genes"][identifier] = {
            "line_end": 900000 + position,
            "omitted_columns": [],
            "record_number": 900000 + position,
            "values": {"genes": identifier, "geneSymbols": symbol},
        }
    reaction = model_reaction(wide, "MAR04792")
    reaction["gene_reaction_rule"] = " or ".join([reaction["gene_reaction_rule"], *synthetic_ids])
    wide_index = build_index_from(wide, root, "over-cap")
    wide_run = copy.deepcopy(mapped)
    wide_run["envelopes"]["gem"] = GemLookup(wide_index).query(GLYCINE)
    wide_data = wide_run["envelopes"]["gem"]["data"]
    wide_seven = section_seven(wide_run)
    wide_card = card_of(wide_run)
    cap_line = next((line for line in wide_seven.splitlines() if "returned candidate(s)" in line), "")
    record(Case(
        case_id       = "GI08",
        category      = "poisoned_index",
        surface       = "section 7 counts and cap line",
        attack        = "more candidates than the module's returned-record cap (100) through the real module",
        construction  = "poisoned_index",
        reachability  = "local_index_config",
        expected      = "contradiction",
        outcome       = "contradiction",
        observed      = {
            "total_candidates":    wide_data["total_candidates"],
            "returned_candidates": wide_data["returned_candidates"],
            "candidates_in_list":  len(wide_data["candidates"]),
            "candidates_complete": wide_data["candidates_complete"],
            "head_line":           next((line for line in wide_seven.splitlines()
                                         if "reaction-linked gene candidate" in line), ""),
            "cap_line":            cap_line,
            "cap_caveat_on_card":  "Returned detail is capped" in wide_card,
            "longest_reaction_line_chars": max(len(line) for line in wide_seven.splitlines()),
            "gpr_genes_printed_in_full":   wide_seven.count("ENSG9"),
        },
        section_five  = section_five(wide_run),
        section_seven = wide_seven,
        card          = wide_card,
        envelope      = wide_run["envelopes"]["gem"],
        notes         = "The head sentence states the true total (123) and the cap line states 'showing 8 of "
                        "100', because render._showing is given the length of the already-capped list rather "
                        "than data.total_candidates. Both numbers are true of different things and the card "
                        "does not say which. The module's own capped-detail caveat does reach Section 8. "
                        "The GPR string is the one Section 7 field with no display cap: the 121-gene rule "
                        "prints in full on a single line.",
        assertions    = [
            ("the module caps its own list at 100", len(wide_data["candidates"]) == 100),
            ("the head sentence states the true total",
             f"{wide_data['total_candidates']:,} reaction-linked gene candidate(s)" in wide_seven),
            ("the cap line states the capped length, not the total",
             "showing 8 of 100 returned candidate(s)" in cap_line),
            ("the module's capped-detail caveat reaches the card",
             "Returned detail is capped" in wide_card),
        ],
    ))

    # GI07: duplicate and ambiguous symbol lists.
    dupes = load_fixture()
    gene_record(dupes, "ENSG00000140905")["geneSymbols"] = "GCSH;GCSH"
    gene_record(dupes, "ENSG00000182199")["geneSymbols"] = "SHMT2;SHMT1"
    dupes_index = build_index_from(dupes, root, "symbol-dupes")
    dupes_run = copy.deepcopy(mapped)
    dupes_run["envelopes"]["gem"] = GemLookup(dupes_index).query(GLYCINE)
    rows = {row["ensembl"]: row for row in dupes_run["envelopes"]["gem"]["data"]["candidates"]}
    record(Case(
        case_id       = "GI07",
        category      = "poisoned_index",
        surface       = "section 5/7 candidate line",
        attack        = "duplicated symbol and two-symbol (ambiguous) annotation",
        construction  = "poisoned_index",
        reachability  = "local_index_config",
        expected      = "declared",
        outcome       = "declared",
        observed      = {
            "duplicate_status": rows["ENSG00000140905"]["symbol_status"],
            "ambiguous_status": rows["ENSG00000182199"]["symbol_status"],
            "ambiguous_symbol": rows["ENSG00000182199"]["symbol"],
            "section_five_has_shmt2": "SHMT2" in section_five(dupes_run),
        },
        section_five  = section_five(dupes_run),
        section_seven = section_seven(dupes_run),
        card          = card_of(dupes_run),
        envelope      = dupes_run["envelopes"]["gem"],
        notes         = "A duplicated symbol collapses to one unique symbol; an ambiguous pair withholds the "
                        "symbol, drops the row from Section 5 and prints the Ensembl id alone in Section 7.",
        assertions    = [
            ("duplicate collapses to unique", rows["ENSG00000140905"]["symbol_status"] == "unique"),
            ("two symbols are ambiguous", rows["ENSG00000182199"]["symbol_status"] == "ambiguous"),
            ("the ambiguous row keeps no symbol", rows["ENSG00000182199"]["symbol"] is None),
            ("section 5 drops the ambiguous row", "SHMT2" not in section_five(dupes_run)),
        ],
    ))


# ---------------------------------------------------------------- forged envelopes

def forged_envelope_cases(mapped: dict) -> None:
    """Field combinations the current module cannot emit. Harness constructions only."""
    base = copy.deepcopy(mapped["envelopes"]["gem"])

    def run_with(mutate) -> dict:
        run = copy.deepcopy(mapped)
        envelope = copy.deepcopy(base)
        mutate(envelope)
        run["envelopes"]["gem"] = envelope
        return run

    def padded(envelope, total: int) -> None:
        template = envelope["data"]["candidates"][0]
        envelope["data"]["candidates"] = [
            {**copy.deepcopy(template),
             "symbol": f"GEM{index:03d}",
             "ensembl": f"ENSG9{index:010d}"}
            for index in range(total)
        ]

    # GE01: counts that contradict the list they describe.
    def mismatch(envelope):
        padded(envelope, 500)
        envelope["data"]["total_candidates"] = 3
        envelope["data"]["returned_candidates"] = 3
    mismatch_run = run_with(mismatch)
    mismatch_seven = section_seven(mismatch_run)
    record(Case(
        case_id       = "GE01",
        category      = "forged_envelope",
        surface       = "section 7 counts and cap line",
        attack        = "declared counts contradict the candidate list length",
        construction  = "forged_envelope",
        reachability  = "harness_only",
        expected      = "contradiction",
        outcome       = "contradiction",
        observed      = {
            "head_line":  next((line for line in mismatch_seven.splitlines()
                                if "reaction-linked gene candidate" in line), ""),
            "cap_line":   next((line for line in mismatch_seven.splitlines()
                                if "returned candidate(s)" in line), ""),
        },
        section_five  = section_five(mismatch_run),
        section_seven = mismatch_seven,
        card          = card_of(mismatch_run),
        envelope      = mismatch_run["envelopes"]["gem"],
        notes         = "The head sentence quotes data.total_candidates while the cap line counts the list. "
                        "The renderer prints both without noticing they disagree.",
        assertions    = [
            ("head sentence quotes the declared count",
             "3 reaction-linked gene candidate(s)" in mismatch_seven),
            ("cap line counts the actual list", "showing 8 of 500 returned candidate(s)" in mismatch_seven),
        ],
    ))

    # GE02: an honestly-counted 500-candidate list, for the cap note.
    def big(envelope):
        padded(envelope, 500)
        envelope["data"]["total_candidates"] = 500
        envelope["data"]["returned_candidates"] = 500
        envelope["data"]["candidates_complete"] = True
    big_run = run_with(big)
    big_seven = section_seven(big_run)
    big_five = section_five(big_run)
    record(Case(
        case_id       = "GE02",
        category      = "forged_envelope",
        surface       = "section 5/7 display cap",
        attack        = "500 candidates against MAX_GEM_CANDIDATES_SHOWN = 8",
        construction  = "forged_envelope",
        reachability  = "harness_only",
        expected      = "capped_and_declared",
        outcome       = "capped_and_declared",
        observed      = {
            "section_seven_cap": "showing 8 of 500 returned candidate(s)" in big_seven,
            "section_five_cap":  "showing 8 of 500 biochemical candidate(s)" in big_five,
            "listed_in_five":    sum(1 for line in big_five.splitlines() if line.startswith("- GEM")),
        },
        section_five  = big_five,
        section_seven = big_seven,
        card          = card_of(big_run),
        envelope      = big_run["envelopes"]["gem"],
        notes         = "Both surfaces cut to eight and both say so with both numbers.",
        assertions    = [
            ("section 7 declares the cut", "showing 8 of 500 returned candidate(s)" in big_seven),
            ("section 5 declares the cut", "showing 8 of 500 biochemical candidate(s)" in big_five),
            ("section 5 prints exactly eight rows",
             sum(1 for line in big_five.splitlines() if line.startswith("- GEM")) == 8),
        ],
    ))

    # GE03: an empty status carrying an error detail.
    def empty_with_error(envelope):
        envelope["status"] = "empty"
        envelope["data"]["error"] = "OSError: index volume disconnected"
        envelope["data"]["mapping"]["status"] = "unmapped"
    empty_run = run_with(empty_with_error)
    empty_seven = section_seven(empty_run)
    record(Case(
        case_id       = "GE03",
        category      = "forged_envelope",
        surface       = "section 5/7 empty-vs-error branch",
        attack        = "a local failure presented with status 'empty' and an error detail",
        construction  = "forged_envelope",
        reachability  = "harness_only",
        expected      = "error_hidden",
        outcome       = "error_hidden",
        observed      = {
            "error_quoted":  "The source reported:" in empty_seven,
            "section_seven": empty_seven.strip().splitlines()[-1],
        },
        section_five  = section_five(empty_run),
        section_seven = empty_seven,
        card          = card_of(empty_run),
        envelope      = empty_run["envelopes"]["gem"],
        notes         = "The error branch is selected on envelope status alone, so a data.error carried "
                        "under status 'empty' is never shown; the card reports an unmapped identifier. "
                        "The module itself never emits this combination (it sets mapping.status='error' "
                        "and leaves status at its initial 'error').",
        assertions    = [
            ("the error detail is not printed", "The source reported:" not in empty_seven),
            ("the reader is told the id was unmapped", "Mapping status: unmapped." in empty_seven),
        ],
    ))

    # GE04: status ok over a mapping that says error.
    def ok_with_mapping_error(envelope):
        envelope["status"] = "ok"
        envelope["data"]["mapping"]["status"] = "error"
        envelope["data"]["error"] = "ValueError: index and manifest disagree"
    ok_run = run_with(ok_with_mapping_error)
    ok_seven = section_seven(ok_run)
    record(Case(
        case_id       = "GE04",
        category      = "forged_envelope",
        surface       = "section 7 branch selection",
        attack        = "status 'ok' over mapping.status 'error'",
        construction  = "forged_envelope",
        reachability  = "harness_only",
        expected      = "rendered_verbatim",
        outcome       = "rendered_verbatim",
        observed      = {
            "candidates_printed": "Selected reaction-linked genes" in ok_seven,
            "error_quoted":       "The source reported:" in ok_seven,
        },
        section_five  = section_five(ok_run),
        section_seven = ok_seven,
        card          = card_of(ok_run),
        envelope      = ok_run["envelopes"]["gem"],
        notes         = "Only mapping.status in (unmapped, ambiguous) and envelope status in (error, empty) "
                        "divert the section; 'error' inside mapping.status is not one of them, so the full "
                        "candidate list prints with no sign of the failure.",
        assertions    = [
            ("the candidate list still prints", "Selected reaction-linked genes" in ok_seven),
            ("the failure is never mentioned", "The source reported:" not in ok_seven),
        ],
    ))

    # GE05: suppression flag set with a full list behind it.
    def suppressed_with_list(envelope):
        padded(envelope, 500)
        envelope["data"]["policy_suppressed"] = True
        envelope["data"]["hub_metabolite"] = True
        envelope["data"]["hub_reasons"] = ["explicit_currency_id"]
    suppressed_run = run_with(suppressed_with_list)
    suppressed_seven = section_seven(suppressed_run)
    record(Case(
        case_id       = "GE05",
        category      = "forged_envelope",
        surface       = "section 5/7 hub-policy branch",
        attack        = "policy_suppressed set while 500 candidates remain in the envelope",
        construction  = "forged_envelope",
        reachability  = "harness_only",
        expected      = "suppressed",
        outcome       = "suppressed",
        observed      = {
            "candidates_printed": "Selected reaction-linked genes" in suppressed_seven,
            "section_five_line":  next((line for line in section_five(suppressed_run).splitlines()
                                        if "hub/currency" in line), ""),
        },
        section_five  = section_five(suppressed_run),
        section_seven = suppressed_seven,
        card          = card_of(suppressed_run),
        envelope      = suppressed_run["envelopes"]["gem"],
        notes         = "The flag wins over the list on both surfaces: nothing from the 500 rows is printed.",
        assertions    = [
            ("section 7 prints no candidates", "Selected reaction-linked genes" not in suppressed_seven),
            ("section 5 prints no candidates",
             "Human-GEM biochemical candidates (reaction membership" not in section_five(suppressed_run)),
        ],
    ))

    # GE06: the same hub metabolite with the suppression flag cleared.
    def hub_without_suppression(envelope):
        envelope["data"]["policy_suppressed"] = False
        envelope["data"]["hub_metabolite"] = True
        envelope["data"]["hub_reasons"] = ["explicit_currency_id",
                                           "distinct_reaction_degree_exceeds_threshold"]
    hub_run = run_with(hub_without_suppression)
    hub_seven = section_seven(hub_run)
    record(Case(
        case_id       = "GE06",
        category      = "forged_envelope",
        surface       = "section 5/7 hub-policy branch",
        attack        = "hub/currency flags set, suppression flag cleared",
        construction  = "forged_envelope",
        reachability  = "harness_only",
        expected      = "rendered_verbatim",
        outcome       = "rendered_verbatim",
        observed      = {
            "candidates_printed": "Selected reaction-linked genes" in hub_seven,
            "hub_mentioned":      "hub" in hub_seven.lower(),
        },
        section_five  = section_five(hub_run),
        section_seven = hub_seven,
        card          = card_of(hub_run),
        envelope      = hub_run["envelopes"]["gem"],
        notes         = "Neither section reads hub_metabolite or hub_reasons: a metabolite declared a hub "
                        "prints an ordinary candidate list with no hub sentence anywhere in Section 7. The "
                        "module's own caveat text is the only remaining signal, and it is not set here.",
        assertions    = [
            ("the candidate list prints", "Selected reaction-linked genes" in hub_seven),
            ("no hub sentence appears in section 7", "hub" not in hub_seven.lower()),
        ],
    ))

    # GE07: free-text role and origin.
    def forged_role(envelope):
        for row in envelope["data"]["candidates"]:
            row["role"] = "genetically validated effector"
            row["origin"] = "genetic"
            row["complex_member"] = "confirmed by MR"
        envelope["data"]["evidence_type"] = "genetic"
        envelope["data"]["route"] = "direct_genetic"
    role_run = run_with(forged_role)
    role_five = section_five(role_run)
    role_seven = section_seven(role_run)
    record(Case(
        case_id       = "GE07",
        category      = "forged_envelope",
        surface       = "section 5/7 candidate line",
        attack        = "role/origin/evidence_type rewritten as genetic language",
        construction  = "forged_envelope",
        reachability  = "harness_only",
        expected      = "rendered_verbatim",
        outcome       = "rendered_verbatim",
        observed      = {
            "section_five_line": next((line for line in role_five.splitlines()
                                       if line.startswith("- GCSH")), ""),
            "section_seven_line": next((line for line in role_seven.splitlines()
                                        if line.startswith("- GCSH")), ""),
            "evidence_type_printed": "direct_genetic" in card_of(role_run),
        },
        section_five  = role_five,
        section_seven = role_seven,
        card          = card_of(role_run),
        envelope      = role_run["envelopes"]["gem"],
        notes         = "role and complex_member are printed as free text. The fixed disclaimer sentences "
                        "remain, so the section states both things at once. route/evidence_type are never "
                        "printed by the renderer.",
        assertions    = [
            ("the forged role prints in section 5",
             "genetically validated effector context in" in role_five),
            ("the forged complex_member prints", "complex member confirmed by MR" in role_five),
            ("the disclaimer sentence survives",
             "Human-GEM membership is biochemical context only." in role_seven),
            ("route/evidence_type are not printed", "direct_genetic" not in card_of(role_run)),
        ],
    ))

    # GE08: rows that are not dictionaries and a numeric symbol.
    def malformed(envelope):
        envelope["data"]["candidates"] = [
            "GCSH",
            None,
            {"symbol": 3.14159, "ensembl": ["ENSG", 1], "symbol_status": "unique",
             "role": None, "n_reactions": "many", "complex_member": {"x": 1}},
        ]
        envelope["data"]["reactions"] = ["MAR04792", None]
    malformed_run = run_with(malformed)
    try:
        malformed_seven = section_seven(malformed_run)
        malformed_card = card_of(malformed_run)
        malformed_outcome = "rendered_verbatim"
        detail = ""
    except Exception as exc:                                 # noqa: BLE001 - measured boundary
        malformed_seven, malformed_card = "", ""
        malformed_outcome, detail = "renderer_raised", f"{type(exc).__name__}: {exc}"
    record(Case(
        case_id       = "GE08",
        category      = "forged_envelope",
        surface       = "section 5/7 robustness",
        attack        = "non-dict candidate rows, numeric symbol, list-valued identifier",
        construction  = "forged_envelope",
        reachability  = "harness_only",
        expected      = "rendered_verbatim",
        outcome       = malformed_outcome,
        observed      = {
            "exception":     detail,
            "printed_rows":  [line for line in malformed_seven.splitlines() if line.startswith("- ")],
        },
        section_five  = section_five(malformed_run) if malformed_outcome != "renderer_raised" else "",
        section_seven = malformed_seven,
        card          = malformed_card,
        envelope      = malformed_run["envelopes"]["gem"],
        notes         = "Non-dict rows are filtered by both sections; a numeric symbol prints as its repr "
                        "and a list-valued Ensembl id prints as its repr. No exception escapes.",
        assertions    = [
            ("the renderer does not raise", malformed_outcome == "rendered_verbatim"),
            ("the string row is dropped", "- GCSH" not in malformed_seven),
            ("the numeric symbol prints as text", "3.14159" in malformed_seven),
        ],
    ))


# ---------------------------------------------------------------- section 9 tie-in

def _reply(fields: dict) -> Reply:
    return Reply(text=json.dumps(fields), provider="anthropic", model=MODEL_NAME)


def through_gate_one(run: dict, fields: dict):
    with patch.object(interpret_module, "complete", return_value=_reply(fields)):
        return interpret_module.interpret(
            run,
            provider   = PROVIDER,
            model      = MODEL_NAME,
            credential = FAKE_CREDENTIAL,
        )


def section_nine(run: dict, interpretation) -> str:
    return "\n".join(render._section_reasoning(run, interpretation)).strip() + "\n"


def printed(section: str) -> bool:
    return render.PENDING_REASONING not in section


def model_path_case(
    *,
    case_id: str,
    run: dict,
    fields: dict,
    attack: str,
    construction: str,
    reachability: str,
    expected: str,
    notes: str,
    counterfactual: dict = None,
    extra: dict = None,
    assertions: list = None,
) -> Case:
    interpretation = through_gate_one(run, fields)
    findings = validate_card.validate(interpretation.fields, run)
    section = section_nine(run, interpretation)
    observed = {
        "gate_one":            f"{interpretation.status}; accepted={interpretation.accepted}",
        "gate_two_findings":   [str(finding) for finding in findings],
        "matched_rules":       sorted({finding.rule for finding in findings}),
    }
    if counterfactual is not None:
        # The same prose against the same run with the Human-GEM envelope removed. This is
        # what attributes the result to the new arm rather than to the rest of the run.
        control = through_gate_one(counterfactual, fields)
        control_findings = validate_card.validate(fields, counterfactual)
        control_section = section_nine(counterfactual, control)
        observed["counterfactual_without_gem"] = {
            "gate_one": f"{control.status}; accepted={control.accepted}",
            "gate_two_rules": sorted({finding.rule for finding in control_findings}),
            "gate_two_findings": [str(finding) for finding in control_findings],
            "outcome": "printed" if printed(control_section) else "blocked",
        }
    observed.update(extra or {})
    outcome = "printed" if printed(section) else "blocked"
    return record(Case(
        case_id       = case_id,
        category      = "section9_tiein",
        surface       = "validate_card + section 9",
        attack        = attack,
        construction  = construction,
        reachability  = reachability,
        expected      = expected,
        outcome       = outcome,
        observed      = observed,
        section_nine  = section,
        section_five  = section_five(run),
        section_seven = section_seven(run),
        card          = card_of(run, interpretation),
        notes         = notes,
        assertions    = list(assertions or []) + [("outcome matches expectation", outcome == expected)],
    ))


def stabilise(value):
    """A copy with the per-run volatile values removed, for the counting case only.

    Wall-clock stamps, the elapsed-milliseconds field and the dated ledger path all carry
    digits into `source_index`, so counting on the raw run would report a different total
    every time. Every other case below runs on the unmodified run.
    """
    if isinstance(value, dict):
        return {
            key: ("<stabilised>" if key in ("local_lookup_ms", "ledger_path", "built_at")
                  else stabilise(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [stabilise(item) for item in value]
    if isinstance(value, str):
        return _TIMESTAMP.sub("<timestamp>", value)
    return value


def section_nine_cases(mapped: dict) -> None:
    without_gem = copy.deepcopy(mapped)
    without_gem["envelopes"].pop("gem")

    with_index = validate_card.source_index(stabilise(mapped))
    without_index = validate_card.source_index(stabilise(without_gem))
    added_numbers = sorted(with_index.numbers - without_index.numbers)
    added_strings = sorted(with_index.strings - without_index.strings)
    # The deterministic card, with wall-clock stamps normalised: a digit pair that happens
    # to fall inside an ISO timestamp is not this card printing that quantity, and leaving
    # the stamps in would make these counts differ between runs.
    card_text = scrub(card_of(mapped))

    def on_card(value: str) -> bool:
        return str(value) in card_text

    # Gene-shaped tokens are collected from the envelope's own text, with its case intact:
    # validate_card.GENE_SHAPE is an uppercase pattern, and testing the casefolded index
    # would count ordinary English words as gene symbols.
    def gene_shaped_tokens(value) -> set:
        found = set()
        for scalar in validate_card._walk(value):
            if isinstance(scalar, str):
                for token in validate_card.GENE_SHAPE.findall(scalar):
                    if token.upper() not in validate_card.NON_GENE_VOCABULARY:
                        found.add(token)
        return found

    gene_shaped = sorted(gene_shaped_tokens(stabilise(mapped["envelopes"]["gem"]))
                         - gene_shaped_tokens(stabilise(without_gem)))
    unprinted_gene_shaped = [token for token in gene_shaped if not on_card(token)]
    # Prefer a token that is an alternative symbol for a candidate gene: it is the form a
    # reader is least able to tell from a nominated gene.
    aliases = sorted({
        alias
        for row in mapped["envelopes"]["gem"]["data"]["candidates"]
        for alias in str((row.get("annotations") or {}).get("geneAliases") or "").split(";")
        if alias and alias in unprinted_gene_shaped
    })
    unprinted_numbers = [
        number for number in added_numbers
        if number == int(number) and not on_card(f"{int(number):,}") and not on_card(str(int(number)))
    ]

    # Enzyme classification codes are not one of validate_card.IDENTIFIER_PATTERNS, so they
    # are not masked before numbers are pulled out of prose, and their dotted segments are
    # read as ordinary decimals.
    ec_codes = sorted({
        str(code)
        for row in mapped["envelopes"]["gem"]["data"]["reactions"]
        for code in (row.get("ec_codes") if isinstance(row.get("ec_codes"), list)
                     else [row.get("ec_codes")])
        if code
    })
    ec_numbers = sorted({
        float(literal)
        for code in ec_codes
        for literal in validate_card.NUMBER.findall(validate_card.normalise_notation(code))
        if literal not in {"+", "-", "."}
    } - without_index.numbers)
    effect_shaped = [value for value in ec_numbers if 1 <= abs(value) < 10 and value != int(value)]

    record(Case(
        case_id      = "GV01",
        category     = "section9_tiein",
        surface      = "validate_card.source_index",
        attack       = "measurement: what the Human-GEM arm adds to the accepted vocabulary",
        construction = "real_module",
        reachability = "deployed_path",
        expected     = "measured",
        outcome      = "measured",
        observed     = {
            "numbers_without_gem":       len(without_index.numbers),
            "numbers_with_gem":          len(with_index.numbers),
            "numbers_added":             len(added_numbers),
            "strings_without_gem":       len(without_index.strings),
            "strings_with_gem":          len(with_index.strings),
            "strings_added":             len(added_strings),
            "gene_shaped_tokens_added":  gene_shaped,
            "gene_shaped_not_on_card":   unprinted_gene_shaped,
            "candidate_aliases_not_on_card": aliases,
            "example_added_numbers":     added_numbers[:12],
            "added_numbers_not_on_card": len(unprinted_numbers),
            "ec_codes_in_envelope":      ec_codes,
            "numbers_donated_by_ec_codes": ec_numbers,
            "effect_size_shaped_from_ec_codes": effect_shaped,
        },
        notes        = "One ordinary Human-GEM envelope for a three-candidate metabolite. The numbers come "
                       "from enzyme classification codes (an EC code such as 1.8.1.4 is read as the decimals "
                       "1.8, .1 and .4), flux bounds, stoichiometric coefficients, charges, annotation record "
                       "from flux bounds, stoichiometric coefficients, charges, annotation record and model "
                       "line numbers, index byte counts and the digit runs inside the manifest's SHA-256 "
                       "strings; the strings include UniProt, Entrez, ENSP/ENST and alias tokens that the "
                       "card never prints.",
        assertions   = [
            ("the arm widens the accepted number set", len(added_numbers) > 0),
            ("most added numbers are never printed on the card", len(unprinted_numbers) > 0),
            ("gene-shaped strings are added that the card never prints", len(unprinted_gene_shaped) > 0),
        ],
    ))

    model_path_case(
        case_id        = "GV02",
        run            = mapped,
        fields         = {"headline": "The retrieved effect size for this pair is -1000."},
        attack         = "a Human-GEM flux bound quoted as an MR effect size",
        construction   = "real_module",
        reachability   = "current_model_path",
        expected       = "printed",
        counterfactual = without_gem,
        notes          = "-1000 is the lower flux bound of a recorded reaction. V1 is set membership over "
                         "the whole run, so a bound becomes an acceptable effect size. The same sentence is "
                         "rejected on the same run with the arm removed. This is the 2026-09-16 finding F2 "
                         "on the new arm.",
        extra          = {"number_source": "reactions[].lower_bound = -1000",
                          "number_printed_on_card": "-1000" in card_of(mapped),
                          "run_state": mapped.get("state"),
                          "retrieved_mr_estimates":
                              len(mapped["envelopes"]["mr"]["data"].get("estimates") or [])},
    )

    if effect_shaped:
        value = effect_shaped[0]
        literal = f"{value:g}"
        donor = next(code for code in ec_codes if code.startswith(literal))
        model_path_case(
            case_id        = "GV07",
            run            = mapped,
            fields         = {"headline":
                              f"The retrieved odds ratio for this pair is {literal}."},
            attack         = "an enzyme classification code's segments quoted as an odds ratio",
            construction   = "real_module",
            reachability   = "current_model_path",
            expected       = "printed",
            counterfactual = without_gem,
            notes          = f"{literal} is the leading segment of the EC code {donor!r} carried on a "
                             "recorded reaction. EC codes are not in validate_card.IDENTIFIER_PATTERNS, so "
                             "they are neither masked before V1 reads numbers nor checked as identifiers by "
                             "V5. The value is effect-size shaped, which is what separates this from the flux "
                             "bound in GV02.",
            extra          = {"literal": literal,
                              "ec_codes": ec_codes,
                              "run_state": mapped.get("state"),
                              "retrieved_mr_estimates":
                                  len(mapped["envelopes"]["mr"]["data"].get("estimates") or []),
                              "literal_printed_on_card": on_card(literal)},
            assertions     = [("the quoted value is not printed on the card", not on_card(literal))],
        )

    model_path_case(
        case_id        = "GV03",
        run            = mapped,
        fields         = {"headline":
                          "GCSH and GLDC are the effector genes this run nominates for the metabolite."},
        attack         = "biochemical-context genes restated as nominated effector genes",
        construction   = "real_module",
        reachability   = "current_model_path",
        expected       = "printed",
        counterfactual = without_gem,
        notes          = "V5 is membership against the run's strings, and a Human-GEM candidate symbol is one "
                         "of them. The same card says in Section 5 that the atlas nomination layer was not "
                         "queried, so the accepted sentence contradicts the deterministic section above it.",
        extra          = {"atlas_queried": "atlas" in mapped["envelopes"],
                          "section_five_says_not_queried":
                              "The atlas nomination layer was not queried in this run" in section_five(mapped)},
        assertions     = [
            ("the atlas arm did not run", "atlas" not in mapped["envelopes"]),
        ],
    )

    model_line = mapped["envelopes"]["gem"]["data"]["candidates"][0]["source_location"]["model_line"]
    model_path_case(
        case_id        = "GV04",
        run            = mapped,
        fields         = {"headline":
                          f"This run's Human-GEM context rests on {model_line} recorded reaction entries."},
        attack         = "a number that exists only in unrendered envelope depth",
        construction   = "real_module",
        reachability   = "current_model_path",
        expected       = "printed",
        counterfactual = without_gem,
        notes          = "The quoted number is a YAML source line number inside candidates[].source_location. "
                       "It is in the run, so V1 accepts it; it is in no rendered section and in no model "
                       "digest, so the attestation sentence's claim that every number appears above is false "
                       "for this card. This is the 2026-09-16 finding F3 on the new arm.",
        extra        = {"quoted_number": model_line,
                        "number_printed_on_card": on_card(model_line)},
        assertions   = [
            ("the number is absent from the deterministic sections", not on_card(model_line)),
        ],
    )

    off_digest = build_digest(copy.deepcopy(without_gem))
    on_digest = build_digest(mapped)
    record(Case(
        case_id      = "GV05",
        category     = "section9_tiein",
        surface      = "llm.interpret.build_digest",
        attack       = "measurement: how the digest names an arm that did not run",
        construction = "real_module",
        reachability = "current_model_path",
        expected     = "arm_omitted",
        outcome      = "arm_omitted" if "gem" not in off_digest["arms"] else "arm_named",
        observed     = {
            "arms_when_gem_ran":     sorted(on_digest["arms"]),
            "arms_when_gem_absent":  sorted(off_digest["arms"]),
            "defaulted_arm_names":   ["mr", "instruments", "outcomes", "catalog", "coloc", "atlas", "dossier"],
        },
        notes        = "build_digest defaults seven arm names to 'not run in this run' so the model can tell "
                       "'not queried' from 'queried and empty'. gem is not in that list, so on a run where the "
                       "arm was switched off or had no ChEBI id the model is never told the arm exists, while "
                       "the deterministic card says so in Section 7 and in a run-level note.",
        assertions   = [
            ("gem is absent from the digest when the arm did not run", "gem" not in off_digest["arms"]),
            ("every other arm is named", all(name in off_digest["arms"] for name in
                                             ("mr", "instruments", "outcomes", "catalog", "coloc",
                                              "atlas", "dossier"))),
        ],
    ))

    token = (aliases or unprinted_gene_shaped or [""])[0]
    if token:
        model_path_case(
            case_id        = "GV06",
            run            = mapped,
            fields         = {"headline":
                              f"{token} is one of the genes this run retrieved for the metabolite."},
            attack         = "a gene symbol that only exists in unrendered annotation depth, accepted by V5",
            construction   = "real_module",
            reachability   = "current_model_path",
            expected       = "printed",
            counterfactual = without_gem,
            notes          = "The token is an alternative gene symbol carried inside a candidate's annotation "
                             "block. It reaches no rendered section and no model digest, and V5's membership "
                             "test cannot tell it from a gene the run actually names.",
            extra          = {"token": token,
                              "token_source": "candidates[].annotations.geneAliases",
                              "printed_on_card": on_card(token)},
            assertions     = [("the token is not printed anywhere on the card", not on_card(token))],
        )


# ---------------------------------------------------------------- artifacts

def write_artifacts(started: str) -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name in ("section_outputs", "full_cards", "envelopes"):
        (OUTPUT / name).mkdir(parents=True, exist_ok=True)

    failures = []
    for case in ROWS:
        for label, held in case.assertions:
            if not held:
                failures.append(f"{case.case_id}: {label}")

        stem = case.case_id.lower()
        blocks = [f"# {case.case_id} - {case.attack}", ""]
        if case.section_five:
            blocks += ["## Section 5 (Effector genes by source)", "", "```", case.section_five.rstrip(), "```", ""]
        if case.section_seven:
            blocks += ["## Section 7 (Via-enzyme protein evidence)", "", "```", case.section_seven.rstrip(), "```", ""]
        if case.section_nine:
            blocks += ["## Section 9 (Reasoning)", "", "```", case.section_nine.rstrip(), "```", ""]
        (OUTPUT / "section_outputs" / f"{stem}.md").write_text(
            scrub("\n".join(blocks)) + "\n", encoding="utf-8")
        if case.card:
            (OUTPUT / "full_cards" / f"{stem}.md").write_text(scrub(case.card), encoding="utf-8")
        if case.envelope is not None:
            (OUTPUT / "envelopes" / f"{stem}.json").write_text(
                scrub(json.dumps(case.envelope, ensure_ascii=False, indent=2, default=str)) + "\n",
                encoding="utf-8")

    rows = [
        {
            "case_id":        case.case_id,
            "category":       case.category,
            "surface":        case.surface,
            "attack":         case.attack,
            "construction":   case.construction,
            "reachability":   case.reachability,
            "pair":           PAIR,
            "expected":       case.expected,
            "outcome":        case.outcome,
            "expectation_met": case.outcome == case.expected,
            "assertions_held": all(held for _label, held in case.assertions),
            "observed":       case.observed,
            "notes":          case.notes,
        }
        for case in ROWS
    ]

    (OUTPUT / "results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    with (OUTPUT / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "case_id", "category", "surface", "attack", "construction", "reachability",
            "pair", "expected", "outcome", "expectation_met", "assertions_held", "notes",
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in writer.fieldnames})

    lines = [
        "# Human-GEM arm (MVP3 / PR #13) - probe results",
        "",
        f"Cases: {len(rows)}. Every row is offline and deterministic; no provider credential and no "
        "network call is used.",
        "",
        "| case | category | attack | construction | reachability | expected | outcome | met |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case_id']} | {row['category']} | {row['attack']} | {row['construction']} | "
            f"{row['reachability']} | {row['expected']} | {row['outcome']} | "
            f"{'yes' if row['expectation_met'] and row['assertions_held'] else 'NO'} |"
        )
    lines += ["", "## Per-case observations", ""]
    for case in ROWS:
        lines.append(f"### {case.case_id} - {case.attack}")
        lines.append("")
        lines.append(f"- surface: {case.surface}")
        lines.append(f"- construction: {case.construction}; reachability: {case.reachability}")
        for key, value in case.observed.items():
            lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False, default=str)}")
        if case.notes:
            lines.append(f"- note: {case.notes}")
        lines.append("")
    (OUTPUT / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _git(*args: str) -> str:
        try:
            return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True,
                                           stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return "unavailable"

    manifest = {
        "probe":      "Human-GEM biochemical-context arm (MVP3, PR #13): tool, pipeline wiring, "
                      "card sections 5 and 7, and the Section 9 validator tie-in",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "revision":   _git("rev-parse", "HEAD"),
        "branch":     _git("rev-parse", "--abbrev-ref", "HEAD"),
        "python":     platform.python_version(),
        "platform":   platform.platform(),
        "network":    "none; the Human-GEM lookup is local and the three remote arms are replaced by "
                      "empty envelopes",
        "cases":      len(rows),
        "outcomes":   {outcome: sum(1 for row in rows if row["outcome"] == outcome)
                       for outcome in sorted({row["outcome"] for row in rows})},
        "expectation_failures": failures,
        "code_sha256": {
            name: _sha(REPO_ROOT / name)
            for name in ("tools/gem.py", "MVP3/src/gem.py", "MVP3/src/build_index.py",
                         "MVP3/src/gpr.py", "MVP3/src/common.py", "render.py",
                         "validate_card.py", "pipeline.py", "llm/interpret.py")
        },
        "input_sha256": {
            "MVP3/tests/fixtures/gem/source_excerpt.json": _sha(SOURCE_FIXTURE),
            "probe_gem.py": _sha(Path(__file__)),
        },
        "normalisation": "Saved artifacts replace ISO timestamps with <timestamp> and "
                         "data.local_lookup_ms with <local_lookup_ms>; assertions run on raw text.",
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for row in rows:
        flag = "ok " if row["expectation_met"] and row["assertions_held"] else "FAIL"
        print(f"{flag} {row['case_id']:5} {row['outcome']:24} {row['attack']}")
    print(f"\n{len(rows)} cases; {len(failures)} expectation failure(s).")
    for failure in failures:
        print(f"  FAILED: {failure}")
    return 1 if failures else 0


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix="metabocausal-gem-probe-") as name:
        root = Path(name)
        index_path = build_index_from(load_fixture(), root, "baseline")
        mapped = honest_paths(root, index_path)
        poisoned_index_cases(root, mapped)
        forged_envelope_cases(mapped)
        section_nine_cases(mapped)
        return write_artifacts(started)


if __name__ == "__main__":
    raise SystemExit(main())
