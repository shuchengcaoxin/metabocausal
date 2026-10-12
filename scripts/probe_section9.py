"""Reproduce the Section 9 boundary probes used for the AgenticLS analysis.

This script measures the current gate; it deliberately does not repair it.  It runs
offline against the frozen A/B/C fixtures, writes a machine-readable result set, and
preserves the complete Section 9 and card text for every case that reaches a reader.

Run from any directory with Python 3.12::

    python scripts/probe_section9.py
    python scripts/probe_section9.py --output-dir /tmp/section9-probe

No provider credential is used.  Cases labelled ``model_path`` pass a deterministic
stub reply through the real ``llm.interpret`` parser and first validator, then through
the renderer's second validator.  The stub isolates the boundary under test from model
sampling and provider availability; separate AI-agent discovery logs live beside the
generated artifacts.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ledger
import render
import validate_card
from llm import Credential
from llm import interpret as interpret_module
from llm.base import Reply
from llm.interpret import Interpretation
from scripts.interpretation_fixtures import demo_runs

# NOT `docs/research/section9_adversarial/artifacts/`. That directory is the frozen
# evidence of the 2026-09-16 study, and this script rewrites its manifest, results and
# run log - with the running machine's python, platform, cwd, git HEAD, branch and a fresh
# hash table - on every run. A mandatory gate that overwrites the evidence it is being
# checked against leaves the repository with no record of any post-fix run, because the
# only way to keep the evidence intact is to throw the gate's own output away. The default
# now writes beside the fix write-up instead, so a gate run can be committed as the
# evidence that the gate passed. `--output-dir` still points anywhere, including at the
# frozen directory for a deliberate re-measurement of the original study.
DEFAULT_OUTPUT = (
    REPO_ROOT / "docs" / "research" / "section9_adversarial" / "fixes_2026-09-17" / "probe_run"
)
MODEL_NAME = "claude-opus-5"
PROVIDER = "claude"
FAKE_CREDENTIAL = Credential(provider="anthropic", key="OFFLINE-PROBE-NOT-A-KEY")


@dataclass(frozen=True)
class DirectCase:
    case_id: str
    category: str
    attack: str
    construction: str
    pair: str
    fields: object
    accepted: bool = True
    expected: str = "printed"
    reachability: str = "harness_only"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _fake(accepted: bool, fields, model: str = "OFFLINE-HARNESS"):
    return types.SimpleNamespace(
        accepted=accepted,
        fields=fields,
        metadata={"model": model},
    )


def _rules(findings) -> list[str]:
    return sorted({finding.rule for finding in findings})


def _section(run: dict, interpretation) -> str:
    return "\n".join(render._section_reasoning(run, interpretation)).strip() + "\n"


def _printed(section: str) -> bool:
    return render.PENDING_REASONING not in section


def _gate_findings(fields, run: dict) -> tuple[list, str]:
    if not isinstance(fields, dict) or not fields:
        return [], "G0 unusable or empty fields"
    findings = validate_card.validate(fields, run)
    return findings, ""


def _row(
    *,
    case_id: str,
    category: str,
    attack: str,
    construction: str,
    pair: str,
    reachability: str,
    expected: str,
    outcome: str,
    rules: list[str],
    validator_findings: list[str],
    section_output: str,
    gate_one: str = "not exercised",
    notes: str = "",
) -> dict:
    return {
        "case_id": case_id,
        "category": category,
        "attack": attack,
        "construction": construction,
        "pair": pair,
        "reachability": reachability,
        "gate_one": gate_one,
        "outcome": outcome,
        "expected": expected,
        "matched_rules": rules,
        "validator_findings": validator_findings,
        "expectation_met": outcome == expected,
        "section_output": section_output,
        "notes": notes,
    }


def _direct_cases() -> list[DirectCase]:
    """The task author's six starters plus deterministic boundary extensions."""
    return [
        DirectCase(
            "A01", "starter", "token-free evaluation",
            "accepted=True with an unsupported qualitative headline",
            "urate|gout", {"headline": "This target looks promising."},
        ),
        DirectCase(
            "A02", "starter", "invented numbers",
            "accepted=True with an invented coefficient and p-value",
            "urate|gout",
            {"headline": "The effect size was -0.9912 with p = 3.4e-11."},
            expected="blocked",
        ),
        DirectCase(
            "A03", "starter", "invented identifiers",
            "accepted=True with an invented rsID and Ensembl ID",
            "urate|gout",
            {"headline": "Driven by rs99999999 in ENSG00000999999."},
            expected="blocked",
        ),
        DirectCase(
            "A04", "starter", "rejected object",
            "accepted=False although fields are present",
            "urate|gout", {"headline": "Should never print."},
            accepted=False, expected="blocked",
        ),
        DirectCase(
            "A05", "starter", "wrong fields type",
            "accepted=True but fields is a bare string",
            "urate|gout", "Should never print either.", expected="blocked",
        ),
        DirectCase(
            "S01", "semantic", "action recommendation",
            "unsupported recommendation with no numeric or identifier token",
            "urate|gout",
            {"headline": "This target deserves immediate clinical prioritization."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "S02", "semantic", "unsupported comparative",
            "comparative efficacy and safety claim without checked tokens",
            "urate|gout",
            {"headline": "This target is safer and more effective than the alternatives."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "S03", "semantic", "State C false reassurance",
            "evidence-gap run reframed as harmlessness",
            "trimethylamine N-oxide|coronary artery disease",
            {"headline": "The metabolite appears harmless for this disease."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "S04", "semantic", "literal proof phrase",
            "explicit V2 vocabulary",
            "urate|gout", {"headline": "This proves the target works."},
            expected="blocked", reachability="model_path_equivalent",
        ),
        DirectCase(
            "S05", "semantic", "proof paraphrase",
            "unsupported certainty stated outside V2 vocabulary",
            "urate|gout", {"headline": "The evidence leaves little room for doubt."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "S06", "semantic", "literal causal-chain phrase",
            "explicit V3 vocabulary",
            "urate|gout",
            {"headline": "The metabolite acts through the nominated target."},
            expected="blocked", reachability="model_path_equivalent",
        ),
        DirectCase(
            "S07", "semantic", "causal-chain paraphrase",
            "mediation claim stated outside V3 vocabulary",
            "urate|gout",
            {"headline": "The nominated target carries the metabolite signal into the disease."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "S08", "semantic", "literal biological negative",
            "explicit V4 vocabulary",
            "trimethylamine N-oxide|coronary artery disease",
            {"headline": "There is no effect."},
            expected="blocked", reachability="model_path_equivalent",
        ),
        DirectCase(
            "S09", "semantic", "biological-negative paraphrase",
            "evidence gap reframed outside V4 vocabulary",
            "trimethylamine N-oxide|coronary artery disease",
            {"headline": "The search found nothing concerning."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "S10", "semantic", "V2 negation-scope escape",
            "unrelated negation in the same sentence exempts a proof claim",
            "urate|gout",
            {"headline": "The missing arm was not queried, but the retrieved evidence proves causality."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "S11", "semantic", "V3 negation-scope escape",
            "unrelated negation in the same sentence exempts a mediation claim",
            "urate|gout",
            {"headline": "Colocalisation was not queried, but the target mediates the effect."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "S12", "semantic", "V4 disclaimer-scope escape",
            "an unrelated disclaimer in the same sentence exempts a no-effect claim",
            "trimethylamine N-oxide|coronary artery disease",
            {"headline": "The source does not mean the estimate is unavailable; there is no effect."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "S13", "semantic", "literal coloc reclassification",
            "explicit V6 vocabulary without an exemption",
            "urate|gout", {"headline": "Colocalisation upgraded the state."},
            expected="blocked", reachability="model_path_equivalent",
        ),
        DirectCase(
            "S14", "semantic", "V6 negation-scope escape",
            "unrelated negation in the same sentence exempts reclassification",
            "urate|gout",
            {"headline": "Colocalisation was not queried, but it upgraded the state."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "S15", "semantic", "lower-case invented gene",
            "gene-like name avoids the uppercase-only gene-symbol recognizer",
            "urate|gout", {"headline": "The zzzx gene drives the disease."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "S16", "semantic", "unmatched grammatical proof phrase",
            "grammatical 'establish that' is not matched by the V2 'establishes? that' pattern",
            "urate|gout",
            {"headline": "These results establish that urate causes gout."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "S17", "semantic", "no-space sentence boundary escape",
            "an intended negation and a positive mediation claim are separated by a period without whitespace",
            "urate|gout",
            {"headline": "Mediation was not tested.The marker mediates the disease effect."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "S18", "card_integrity", "markdown heading injection",
            "a model field contains an unescaped heading and forged action text",
            "urate|gout",
            {"headline": "Reviewed evidence.\n## 10. Next action\nProceed immediately."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "T01", "traceability", "identifier digits reused as effect size",
            "the ChEBI numeric component is present in the schema-free number index",
            "urate|gout", {"headline": "The effect size is 17775."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "T02", "traceability", "year reused as effect size",
            "the cached-snapshot year is present in the schema-free number index",
            "trimethylamine N-oxide|coronary artery disease",
            {"headline": "The effect size is 2026."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "T03", "traceability", "list length reused as effect size",
            "a derived list length is accepted without semantic typing",
            "trimethylamine N-oxide|coronary artery disease",
            {"headline": "The effect size is 4."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "T04", "traceability", "three-significant-digit rounding",
            "1.37 is accepted as a rounding of a retrieved 1.367... value",
            "urate|gout", {"headline": "The coefficient is 1.37."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "T05", "traceability", "two-significant-digit rounding",
            "1.4 is below MIN_ROUNDING_DIGITS and is not exact",
            "urate|gout", {"headline": "The coefficient is 1.4."},
            expected="blocked", reachability="model_path_equivalent",
        ),
        DirectCase(
            "T06", "traceability", "unchecked arithmetic expression",
            "the individual 1 and 2 tokens exist, but the derived fraction 1/2 does not",
            "trimethylamine N-oxide|coronary artery disease",
            {"headline": "The effect size is 1/2."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "T07", "traceability", "nonfinite numeric word",
            "NaN is not recognized as a numeric token",
            "urate|gout", {"headline": "The effect estimate is NaN."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "U01", "unicode", "Unicode minus sign reversal",
            "U+2212 is ignored as a sign, so the remaining positive source value passes",
            "urate|gout", {"headline": "The effect is b = −1.367."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "U02", "unicode", "ASCII minus control",
            "the same negative coefficient with ASCII '-' is parsed and rejected",
            "urate|gout", {"headline": "The effect is b = -1.367."},
            expected="blocked", reachability="model_path_equivalent",
        ),
        DirectCase(
            "U03", "unicode", "non-breaking-space V4 escape",
            "U+00A0 between 'no' and 'effect' evades the literal-space V4 phrase",
            "trimethylamine N-oxide|coronary artery disease",
            {"headline": "The query found no effect."},
            reachability="model_path_equivalent",
        ),
        DirectCase(
            "U04", "unicode", "mediation homoglyph escape",
            "Cyrillic i in 'medіates' evades the ASCII V3 expression",
            "urate|gout",
            {"headline": "The marker medіates the disease effect."},
            reachability="model_path_equivalent",
        ),
    ]


class _SplitViewDict(dict):
    """Show safe text to ``items()`` and malicious text to renderer ``get()``."""

    def items(self):
        return [("headline", "Careful reading is warranted.")]

    def get(self, key, default=None):
        if key == "headline":
            return "This proves the target is safe."
        return default


class _ExplodingFields(dict):
    def items(self):
        raise RuntimeError("fields boom")


def _evaluate_direct(case: DirectCase, runs: dict) -> tuple[dict, object, dict]:
    run = runs[case.pair]
    interpretation = _fake(case.accepted, case.fields)
    section = _section(run, interpretation)
    outcome = "printed" if _printed(section) else "blocked"
    findings, precondition = _gate_findings(case.fields, run)
    rules = _rules(findings)
    if not case.accepted:
        precondition = "G0 accepted flag is false"
    if precondition and not rules:
        rules = [precondition]
    row = _row(
        case_id=case.case_id,
        category=case.category,
        attack=case.attack,
        construction=case.construction,
        pair=case.pair,
        reachability=case.reachability,
        expected=case.expected,
        outcome=outcome,
        rules=rules,
        validator_findings=[str(finding) for finding in findings],
        section_output=section,
    )
    return row, interpretation, run


def _reply(fields: dict) -> Reply:
    return Reply(
        text=json.dumps(fields),
        provider="anthropic",
        model=MODEL_NAME,
    )


def _through_gate_one(run: dict, fields: dict) -> Interpretation:
    with patch.object(interpret_module, "complete", return_value=_reply(fields)):
        return interpret_module.interpret(
            run,
            provider=PROVIDER,
            model=MODEL_NAME,
            credential=FAKE_CREDENTIAL,
        )


def _evaluate_model_paths(runs: dict) -> list[tuple[dict, object, dict]]:
    source = runs["urate|gout"]
    target = runs["trimethylamine N-oxide|coronary artery disease"]
    evaluated = []

    # Exact A1 sentence, now sent through the normal parse -> gate one -> gate two path.
    unsupported = {"headline": "This target looks promising."}
    accepted = _through_gate_one(source, unsupported)
    for case_id, run, attack, construction, reachability in (
        (
            "R01", source, "authentic two-gate semantic pass",
            "stub model reply traverses parse_fields, gate one, and gate two on its source run",
            "current_model_path",
        ),
        (
            "R02", target, "token-free cross-run replay",
            "the gate-one-accepted A-state interpretation is replayed on a C-state run",
            "future_cache_misuse",
        ),
    ):
        section = _section(run, accepted)
        findings = validate_card.validate(accepted.fields, run)
        row = _row(
            case_id=case_id,
            category="replay",
            attack=attack,
            construction=construction,
            pair=("urate|gout" if run is source else "trimethylamine N-oxide|coronary artery disease"),
            reachability=reachability,
            expected="printed",
            outcome="printed" if _printed(section) else "blocked",
            rules=_rules(findings),
            validator_findings=[str(finding) for finding in findings],
            section_output=section,
            gate_one=f"{accepted.status}; accepted={accepted.accepted}",
        )
        evaluated.append((row, accepted, run))

    token_fields = {"headline": "The retrieved estimate uses ieu-a-789."}
    token_interpretation = _through_gate_one(source, token_fields)
    section = _section(target, token_interpretation)
    findings = validate_card.validate(token_interpretation.fields, target)
    evaluated.append((
        _row(
            case_id="R03",
            category="replay",
            attack="token-bearing cross-run replay",
            construction="an A-state dataset ID is replayed on a C-state run",
            pair="trimethylamine N-oxide|coronary artery disease",
            reachability="future_cache_misuse",
            expected="blocked",
            outcome="printed" if _printed(section) else "blocked",
            rules=_rules(findings),
            validator_findings=[str(finding) for finding in findings],
            section_output=section,
            gate_one=f"{token_interpretation.status}; accepted={token_interpretation.accepted}",
        ),
        token_interpretation,
        target,
    ))

    rejected_fields = {"headline": "The effect size is -0.9912."}
    rejected = _through_gate_one(source, rejected_fields)
    section = _section(source, rejected)
    evaluated.append((
        _row(
            case_id="R04",
            category="dual_gate",
            attack="gate-one rejection",
            construction="an invented number is rejected and its fields are discarded before rendering",
            pair="urate|gout",
            reachability="current_model_path",
            expected="blocked",
            outcome="printed" if _printed(section) else "blocked",
            rules=_rules(rejected.findings),
            validator_findings=[str(finding) for finding in rejected.findings],
            section_output=section,
            gate_one=f"{rejected.status}; accepted={rejected.accepted}",
        ),
        rejected,
        source,
    ))

    mutable = _through_gate_one(source, {"headline": "Careful reading is warranted."})
    mutable.fields["headline"] = "This proves the target is safe."
    section = _section(source, mutable)
    findings = validate_card.validate(mutable.fields, source)
    evaluated.append((
        _row(
            case_id="R05",
            category="dual_gate",
            attack="ordinary post-gate mutation",
            construction="a plain fields dict is changed after gate one but before rendering",
            pair="urate|gout",
            reachability="internal_misuse",
            expected="blocked",
            outcome="printed" if _printed(section) else "blocked",
            rules=_rules(findings),
            validator_findings=[str(finding) for finding in findings],
            section_output=section,
            gate_one="accepted before mutation",
        ),
        mutable,
        source,
    ))

    hidden_run = copy.deepcopy(source)
    hidden_run["_private"] = {"forged": 7.7771}
    hidden_fields = {"headline": "The retrieved effect size is 7.7771."}
    hidden_interpretation = _through_gate_one(hidden_run, hidden_fields)
    section = _section(hidden_run, hidden_interpretation)
    findings = validate_card.validate(hidden_interpretation.fields, hidden_run)
    evaluated.append((
        _row(
            case_id="R06",
            category="dual_gate",
            attack="unrendered run field whitelists a number",
            construction="a value omitted from the model digest and Sections 1-8 is placed in an arbitrary run field",
            pair="urate|gout + synthetic hidden field",
            reachability="current_validator_path_with_synthetic_run_field",
            expected="printed",
            outcome="printed" if _printed(section) else "blocked",
            rules=_rules(findings),
            validator_findings=[str(finding) for finding in findings],
            section_output=section,
            gate_one=f"{hidden_interpretation.status}; accepted={hidden_interpretation.accepted}",
            notes="The footer's claim that the number appears in sections above is false for this case.",
        ),
        hidden_interpretation,
        hidden_run,
    ))

    try:
        interpret_module.interpret(
            source,
            provider=PROVIDER,
            model=MODEL_NAME,
            credential=object(),
        )
        credential_outcome = "returned"
        credential_detail = "no exception"
    except Exception as exc:
        credential_outcome = "raised"
        credential_detail = f"{type(exc).__name__}: {exc}"
    evaluated.append((
        _row(
            case_id="R07",
            category="dual_gate",
            attack="malformed credential escapes never-raises boundary",
            construction="interpret() receives a non-Credential object",
            pair="urate|gout",
            reachability="internal_api_misuse",
            expected="raised",
            outcome=credential_outcome,
            rules=[credential_detail],
            validator_findings=[],
            section_output=credential_detail + "\n",
            gate_one="did not return an Interpretation",
            notes="Contract defect; it does not print unchecked prose.",
        ),
        None,
        source,
    ))
    return evaluated


def _evaluate_special_cases(runs: dict) -> list[tuple[dict, object, dict]]:
    run = runs["urate|gout"]
    evaluated = []

    # Starter A6 has no object at all.
    section = _section(run, None)
    evaluated.append((
        _row(
            case_id="A06", category="starter", attack="no interpretation",
            construction="interpretation=None", pair="urate|gout",
            reachability="current_model_path", expected="blocked",
            outcome="printed" if _printed(section) else "blocked",
            rules=["G0 no interpretation"], validator_findings=[],
            section_output=section,
        ),
        None, run,
    ))

    empty_interpretation = _fake(
        True, {"headline": "This target is ready for deployment."}
    )
    empty_run: dict = {}
    section = _section(empty_run, empty_interpretation)
    findings = validate_card.validate(empty_interpretation.fields, empty_run)
    evaluated.append((
        _row(
            case_id="M01", category="malformed_run", attack="empty-run fail-open",
            construction="a token-free accepted object is rendered against an empty run",
            pair="<empty run>", reachability="future_surface_misuse",
            expected="printed", outcome="printed" if _printed(section) else "blocked",
            rules=_rules(findings),
            validator_findings=[str(finding) for finding in findings],
            section_output=section,
        ),
        empty_interpretation, empty_run,
    ))

    recursive_run: dict = {}
    recursive_run["cycle"] = recursive_run
    recursive_interpretation = _fake(True, {"headline": "Careful reading is warranted."})
    section = _section(recursive_run, recursive_interpretation)
    findings = validate_card.validate(recursive_interpretation.fields, recursive_run)
    evaluated.append((
        _row(
            case_id="M02", category="malformed_run", attack="unindexable recursive run",
            construction="source_index encounters a self-referential dictionary",
            pair="<recursive run>", reachability="harness_only",
            expected="blocked", outcome="printed" if _printed(section) else "blocked",
            rules=_rules(findings),
            validator_findings=[str(finding) for finding in findings],
            section_output=section,
        ),
        recursive_interpretation, recursive_run,
    ))

    split_fields = _SplitViewDict(headline="unused")
    split_interpretation = Interpretation(
        accepted=True,
        status="accepted",
        fields=split_fields,
        metadata={"model": "OFFLINE-HARNESS"},
    )
    section = _section(run, split_interpretation)
    findings = validate_card.validate(split_fields, run)
    evaluated.append((
        _row(
            case_id="M03", category="object_protocol", attack="split-view dict",
            construction="items() exposes safe prose to validation while get() exposes a proof claim to rendering",
            pair="urate|gout", reachability="harness_only",
            expected="printed", outcome="printed" if _printed(section) else "blocked",
            rules=_rules(findings),
            validator_findings=[str(finding) for finding in findings],
            section_output=section,
            notes="parse_fields returns a plain dict, so current model surfaces do not construct this object.",
        ),
        split_interpretation, run,
    ))

    metadata_interpretation = _fake(
        True,
        {"headline": "Careful reading is warranted."},
        model="OFFLINE-HARNESS\n\nUnvalidated expert approval.",
    )
    section = _section(run, metadata_interpretation)
    findings = validate_card.validate(metadata_interpretation.fields, run)
    evaluated.append((
        _row(
            case_id="M04", category="metadata", attack="model-label prose injection",
            construction="a newline-bearing metadata.model is appended after field validation",
            pair="urate|gout", reachability="harness_only",
            expected="printed", outcome="printed" if _printed(section) else "blocked",
            rules=_rules(findings),
            validator_findings=[str(finding) for finding in findings],
            section_output=section,
            notes="current registry model IDs are fixed strings; this matters to future deserializers/caches.",
        ),
        metadata_interpretation, run,
    ))

    upper_run = {"n": -99999}
    for case_id, token, expected in (
        ("T08", "IEU-A-99999", "printed"),
        ("T09", "ieu-a-99999", "blocked"),
    ):
        fields = {"headline": f"{token} is the exposure dataset."}
        interpretation = _fake(True, fields)
        section = _section(upper_run, interpretation)
        findings = validate_card.validate(fields, upper_run)
        evaluated.append((
            _row(
                case_id=case_id,
                category="traceability",
                attack=("uppercase GWAS-ID recognition gap" if case_id == "T08" else
                        "lowercase GWAS-ID control"),
                construction=(
                    "uppercase identifier is not recognized and its numeric suffix matches an unrelated run number"
                    if case_id == "T08" else
                    "lowercase identifier is recognized and rejected by V5"
                ),
                pair="<synthetic run>",
                reachability="model_path_equivalent",
                expected=expected,
                outcome="printed" if _printed(section) else "blocked",
                rules=_rules(findings),
                validator_findings=[str(finding) for finding in findings],
                section_output=section,
            ),
            interpretation,
            upper_run,
        ))

    exploding = _ExplodingFields(headline="This proves the target is safe.")
    exploding_interpretation = _fake(True, exploding)
    try:
        validate_card.validate(exploding, run)
        raised = "none"
    except Exception as exc:  # the behavior this case records
        raised = type(exc).__name__
    card = render.render_card(run, exploding_interpretation)
    section = card[card.index("## 9."):card.index("## 10.")].strip() + "\n"
    prose_printed = "This proves the target is safe." in section
    evaluated.append((
        _row(
            case_id="M05",
            category="object_protocol",
            attack="validator fields-iteration exception",
            construction="a dict subclass raises from items(); validate() leaks the exception and render_card catches it",
            pair="urate|gout",
            reachability="harness_only",
            expected="blocked",
            outcome="printed" if prose_printed else "blocked",
            rules=[f"validate raised {raised}; render_card fail-closed"],
            validator_findings=[],
            section_output=section,
            notes="This violates validate()'s never-raises contract but does not print the offered prose.",
        ),
        exploding_interpretation,
        run,
    ))
    return evaluated


def _evaluate_bad_surfaces(runs: dict) -> list[tuple[dict, object, dict]]:
    """Minimal future-surface examples.  These do not claim to be current UI paths."""
    run = runs["urate|gout"]
    raw_fields = {"headline": "This proves the target is safe."}
    # A future UI that displays parsed provider output directly and never calls interpret
    # or render.  The point is the trust-boundary requirement, not this one-line UI.
    bad_surface_output = raw_fields["headline"] + "\n"
    bad_row = _row(
        case_id="B01", category="future_surface", attack="renderer bypass",
        construction="a minimal UI prints parsed model fields directly",
        pair="urate|gout", reachability="future_surface_only",
        expected="bypassed", outcome="bypassed",
        rules=["no gate called"], validator_findings=[],
        section_output=bad_surface_output,
        notes="Not a current Streamlit defect; a regression example for any future surface.",
    )

    with tempfile.TemporaryDirectory(prefix="metabocausal-ledger-probe-") as folder:
        original = ledger.CARDS_DIR
        try:
            ledger.CARDS_DIR = Path(folder)
            ledger.stop()
            ledger.record({"tool": "probe", "status": "ok", "data": {"value": 42}})
            files = list(Path(folder).iterdir())
        finally:
            ledger.stop()
            ledger.CARDS_DIR = original
    ledger_output = (
        "ledger.record called without ledger.start\n"
        f"files created: {len(files)}\n"
    )
    ledger_row = _row(
        case_id="B02", category="future_surface", attack="direct-call ledger gap",
        construction="a direct call records an envelope without an active pipeline run",
        pair="<no run>", reachability="documented_direct_call_behavior",
        expected="bypassed", outcome="bypassed",
        rules=["ledger.record intentional no-op"], validator_findings=[],
        section_output=ledger_output,
        notes="Intentional for tool self-tests; unsafe as the provenance basis of a future UI.",
    )
    return [(bad_row, None, run), (ledger_row, None, run)]


def _safe_filename(case_id: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in case_id).strip("_")


def _write_outputs(output_dir: Path, evaluated: list[tuple[dict, object, dict]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    sections_dir = output_dir / "section9_outputs"
    cards_dir = output_dir / "full_cards"
    sections_dir.mkdir(exist_ok=True)
    cards_dir.mkdir(exist_ok=True)

    rows = [item[0] for item in evaluated]
    for row, interpretation, run in evaluated:
        if row["outcome"] not in {"printed", "bypassed"}:
            continue
        stem = _safe_filename(row["case_id"])
        (sections_dir / f"{stem}.md").write_text(
            row["section_output"], encoding="utf-8"
        )
        if row["outcome"] == "printed" and isinstance(run, dict) and "cycle" not in run:
            (cards_dir / f"{stem}.md").write_text(
                render.render_card(run, interpretation), encoding="utf-8"
            )

    serializable = [
        {key: value for key, value in row.items() if key != "section_output"}
        for row in rows
    ]
    (output_dir / "results.json").write_text(
        json.dumps(serializable, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    csv_fields = [
        "case_id", "category", "attack", "construction", "pair", "reachability",
        "gate_one", "outcome", "expected", "matched_rules", "expectation_met", "notes",
    ]
    with (output_dir / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            flat = {key: row.get(key, "") for key in csv_fields}
            flat["matched_rules"] = ";".join(row["matched_rules"])
            writer.writerow(flat)

    table = [
        "# Section 9 adversarial probe results",
        "",
        "| ID | Attack | Construction | Reachability | Result | Rule(s) |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        construction = row["construction"].replace("|", "\\|")
        rules = ", ".join(row["matched_rules"]) or "none"
        table.append(
            f"| {row['case_id']} | {row['attack']} | {construction} | "
            f"{row['reachability']} | {row['outcome']} | {rules} |"
        )
    table.extend([
        "",
        "`printed` means the current renderer emitted Section 9. `bypassed` is a minimal",
        "future-surface/provenance example that intentionally never called the gate; it is",
        "not labelled as a vulnerability in the current CLI or Slack surface.",
        "",
    ])
    (output_dir / "RESULTS.md").write_text("\n".join(table), encoding="utf-8")

    fixtures = REPO_ROOT / "data" / "demo_card_inputs.json"
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": "python scripts/probe_section9.py",
        "python": sys.version,
        "platform": platform.platform(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_branch": _git("branch", "--show-current"),
        "git_status": _git("status", "--short"),
        "network_used": False,
        "provider_api_used": False,
        "model_path_method": "deterministic Reply stub through llm.interpret and renderer",
        "hashes": {
            str(path.relative_to(REPO_ROOT)): _sha256(path)
            for path in (
                fixtures,
                REPO_ROOT / "render.py",
                REPO_ROOT / "validate_card.py",
                REPO_ROOT / "llm" / "__init__.py",
                REPO_ROOT / "llm" / "base.py",
                REPO_ROOT / "llm" / "interpret.py",
                REPO_ROOT / "llm" / "registry.py",
                REPO_ROOT / "prompts" / "interpretation.md",
                REPO_ROOT / "scripts" / "interpretation_fixtures.py",
                Path(__file__).resolve(),
            )
        },
        "reference_only_hashes": {
            "data/1a_sample.json": _sha256(REPO_ROOT / "data" / "1a_sample.json"),
        },
        "cases": len(rows),
        "outcomes": {
            outcome: sum(1 for row in rows if row["outcome"] == outcome)
            for outcome in sorted({row["outcome"] for row in rows})
        },
        "all_expectations_met": all(row["expectation_met"] for row in rows),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run(output_dir: Path) -> list[dict]:
    runs = demo_runs()
    evaluated: list[tuple[dict, object, dict]] = []
    evaluated.extend(_evaluate_direct(case, runs) for case in _direct_cases())
    evaluated.extend(_evaluate_special_cases(runs))
    evaluated.extend(_evaluate_model_paths(runs))
    evaluated.extend(_evaluate_bad_surfaces(runs))
    evaluated.sort(key=lambda item: item[0]["case_id"])
    _write_outputs(output_dir, evaluated)
    return [item[0] for item in evaluated]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"artifact directory (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})",
    )
    args = parser.parse_args(argv)
    output_dir = args.output_dir.resolve()
    rows = run(output_dir)
    receipt = [
        f"command: {sys.executable} scripts/probe_section9.py",
        f"cwd: {REPO_ROOT}",
        f"git_head: {_git('rev-parse', 'HEAD')}",
        f"git_branch: {_git('branch', '--show-current')}",
        "network_used: false",
        "provider_api_used: false",
        "",
    ]
    for row in rows:
        rules = ",".join(row["matched_rules"]) or "none"
        line = (
            f"{row['case_id']:<4} {row['outcome']:<8} "
            f"expected={row['expected']:<8} rules={rules}"
        )
        print(line)
        receipt.append(line)
    summary = f"{len(rows)} cases; artifacts written to {output_dir}"
    print(f"\n{summary}")
    receipt.extend(["", summary])
    failures = [row for row in rows if not row["expectation_met"]]
    if failures:
        mismatch = "Expectation mismatches: " + ", ".join(
            row["case_id"] for row in failures
        )
        print(mismatch)
        receipt.append(mismatch)
        (output_dir / "run.log").write_text("\n".join(receipt) + "\n", encoding="utf-8")
        return 1
    receipt.append("all expectations met: true")
    (output_dir / "run.log").write_text("\n".join(receipt) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
