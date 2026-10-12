"""Section 9: a short reading of a finished card, written by a model and checked by code.

    from llm import Credential
    from llm.interpret import interpret

    result = interpret(run, provider="claude", model="claude-opus-5", credential=cred)
    if result.accepted:
        ...render result.fields into section 9
    # otherwise render nothing there; result.reason says why

NO TOOLS, ON PURPOSE. The deterministic pipeline has already retrieved everything by the
time this runs. Giving the model tools here would add a loop, a per-card cost and a class
of failure, and would buy no evidence that is not already in the run. This is one
structured request with one structured answer.

THE CONTRACT THIS FILE KEEPS: `interpret` NEVER RAISES. Every failure - no key, a rejected
key, a timeout, a model that does not exist, malformed JSON, a refusal, a validator finding
- comes back as a result whose `accepted` is False and whose `reason` says which. The
caller renders the deterministic card either way. That is what makes the model an
enhancement rather than a dependency, and it is the property the whole design rests on.

WHAT GETS SENT. A digest, not the run. The run holds raw HTTP envelopes, full estimate
tables and the ledger; a card needs a paragraph. `build_digest` selects the fields a reader
of section 9 would need and caps the estimate rows. Anything the digest omits is a number
the model cannot quote - the validator indexes the WHOLE run, so omitting a field narrows
what the model sees without narrowing what it is allowed to say.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import validate_card

from . import complete, resolve, run_metadata
from .base import LLMError

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = REPO_ROOT / "prompts" / "interpretation.md"

FIELDS = ("headline", "reading", "limits")

# The estimate table on a card can hold dozens of rows. The model is writing a paragraph,
# so it gets the strongest few - enough to quote one accurately, not enough to start
# summarising the table, which is section 3's job and is already done.
MAX_ESTIMATES = 8
MAX_GENES = 12
MAX_CAVEATS = 12

PROMPT_MISSING = (
    "The interpretation prompt is missing from {path}. Section 9 is left empty rather "
    "than written from an improvised prompt."
)


@dataclass(frozen=True)
class Interpretation:
    """The outcome of one interpretation attempt. Always returned, never raised."""

    accepted: bool
    fields:   dict = field(default_factory=dict)
    reason:   str = ""
    status:   str = "unavailable"        # accepted | rejected | unavailable
    findings: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def note(self) -> str:
        """One line for the run's notes and the execution log. Holds no credential."""
        where = self.metadata.get("model") or "no model"
        if self.accepted:
            return f"section 9 written by {where} and accepted by the validator."
        if self.status == "rejected":
            return (
                f"section 9 discarded: {where} produced prose the validator rejected "
                f"({len(self.findings)} finding(s)). {self.reason}"
            )
        return f"section 9 not written: {self.reason}"


# ---------------------------------------------------------------- the digest

def _entity(run: dict, side: str) -> dict:
    entity = run.get(side) or {}
    return {
        "asked_for": entity.get("query") or entity.get("input"),
        "label":     entity.get("label"),
        "id":        entity.get("id"),
        "synonyms":  list(entity.get("synonyms") or [])[:8],
    }


def _envelope_digest(envelope) -> dict:
    if not isinstance(envelope, dict):
        return {"status": "not run"}
    data = envelope.get("data")
    return {
        "tool":    envelope.get("tool"),
        "source":  envelope.get("source"),
        "status":  envelope.get("status"),
        "caveats": list(envelope.get("caveats") or [])[:4],
        "rows":    len(data) if isinstance(data, list) else None,
    }


def build_digest(run: dict) -> dict:
    """What the model is shown. Faithful to the run, and much smaller than it.

    Every value here is copied from the run, never recomputed - so anything the model
    quotes from the digest is by construction a value the validator will find."""
    envelopes = run.get("envelopes") or {}
    mr = envelopes.get("mr") if isinstance(envelopes, dict) else None
    estimates = []
    if isinstance(mr, dict) and isinstance(mr.get("data"), dict):
        rows = mr["data"].get("estimates") or []
        for row in rows[:MAX_ESTIMATES]:
            if not isinstance(row, dict):
                continue
            estimates.append({
                key: row.get(key)
                for key in ("exposure_id", "outcome_id", "exposure_trait", "outcome_trait",
                            "method", "b", "se", "pval", "nsnp")
                if row.get(key) is not None
            })

    digest = {
        "metabolite_exposure": _entity(run, "metabolite"),
        "disease_outcome":     _entity(run, "disease"),
        "state":               run.get("state"),
        "classifier_sentence": run.get("reason"),
        "arms": {
            name: _envelope_digest(envelope)
            for name, envelope in (envelopes.items() if isinstance(envelopes, dict) else [])
        },
        "retrieved_estimates": estimates,
        "colocalisation":      run.get("coloc_summary") or {},
        "effector_genes":      list(run.get("effector_genes") or [])[:MAX_GENES],
        "run_notes":           list(run.get("notes") or [])[:MAX_CAVEATS],
    }
    # Arms that never ran are named rather than omitted: "not queried" and "queried and
    # empty" are different statements and section 9 has to be able to tell them apart.
    for expected in ("mr", "instruments", "outcomes", "catalog", "coloc", "atlas", "dossier"):
        digest["arms"].setdefault(expected, {"status": "not run in this run"})
    return digest


def load_prompt(path: Path = PROMPT_PATH) -> str:
    """The system prompt, or "" when the file is missing.

    A missing prompt leaves section 9 empty. Improvising one here would produce prose
    written to rules nobody reviewed, which is the failure this file exists to prevent."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


# ---------------------------------------------------------------- parsing

FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def parse_fields(text: str) -> dict:
    """The model's JSON object, or {} when it did not return one.

    A code fence is stripped because models add them despite instructions; nothing else is
    repaired. Silently rescuing malformed output means shipping prose whose shape nobody
    controlled, and the deterministic card is a better outcome than that."""
    stripped = FENCE.sub("", str(text or "")).strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
    except ValueError:
        # One accommodation: a model that wrapped the object in a sentence. The object is
        # still parsed strictly - this only finds where it starts and ends.
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(stripped[start:end + 1])
        except ValueError:
            return {}

    if not isinstance(parsed, dict):
        return {}
    return {
        key: parsed[key]
        for key in FIELDS
        if isinstance(parsed.get(key), str) and parsed[key].strip()
    }


# ---------------------------------------------------------------- entry point

def interpret(
    run:         dict,
    *,
    provider:    str,
    model:       str,
    credential,
    prompt_path: Path = PROMPT_PATH,
    max_tokens:  int = 1200,
    timeout:     float = 60.0,
) -> Interpretation:
    """Write section 9 for one completed run, or explain why it was not written.

    Never raises. Every path returns an Interpretation, and a caller that renders
    `result.fields` only when `result.accepted` is true cannot be made to print unchecked
    prose by any failure of the model, the network, the credential or the parser."""
    try:
        spec = resolve(provider, model)
        metadata = run_metadata(spec, credential, mode="interpretation")
    except LLMError as exc:
        return Interpretation(
            accepted = False,
            reason   = exc.user_message(),
            status   = "unavailable",
            metadata = {"provider": str(provider), "model": str(model)},
        )

    system = load_prompt(prompt_path)
    if not system.strip():
        return Interpretation(
            accepted = False,
            reason   = PROMPT_MISSING.format(path=prompt_path),
            status   = "unavailable",
            metadata = metadata,
        )

    try:
        return _attempt(
            run,
            spec       = spec,
            credential = credential,
            system     = system,
            metadata   = metadata,
            max_tokens = max_tokens,
            timeout    = timeout,
        )
    except LLMError as exc:
        # Every transport, credential and model failure lands here. The run and its ledger
        # are already complete; nothing about the evidence changes.
        return Interpretation(
            accepted = False,
            reason   = exc.user_message(),
            status   = "unavailable",
            metadata = metadata,
        )
    except Exception as exc:                            # noqa: BLE001 - deliberate boundary
        # Anything that is NOT an LLMError is a bug below this line, and a bug there must
        # not become a traceback in a Slack thread. It is caught for the same reason
        # pipeline.run_pair catches everything: the caller is a surface, and the
        # deterministic card is still perfectly good. The type is named in the reason so
        # the bug stays findable instead of being smoothed over.
        return Interpretation(
            accepted = False,
            reason   = (
                f"The interpretation step failed unexpectedly "
                f"({type(exc).__name__}). This is a defect in the LLM layer, not a "
                "statement about the evidence."
            ),
            status   = "unavailable",
            metadata = metadata,
        )


def _attempt(
    run:        dict,
    *,
    spec,
    credential,
    system:     str,
    metadata:   dict,
    max_tokens: int,
    timeout:    float,
) -> Interpretation:
    """One attempt: build the digest, ask, parse, validate. Raises; `interpret` guards it.

    Split out so that ONE guard in `interpret` covers every step - the request, the parse
    and the validation alike. A guard wrapped around the model call alone would leave a
    broken validator able to reach the caller as a traceback, which is the one thing this
    module promises cannot happen."""
    digest = build_digest(run)
    messages = [{
        "role": "user",
        "content": (
            "Here is the completed run. Write section 9 as the JSON object described.\n\n"
            + json.dumps(digest, indent=2, ensure_ascii=False, default=str)
        ),
    }]

    reply = complete(
        messages,
        provider   = spec.provider,
        model      = spec.model,
        credential = credential,
        system     = system,
        max_tokens = max_tokens,
        timeout    = timeout,
    )

    fields = parse_fields(reply.text)
    metadata = dict(metadata, usage=reply.usage, stop_reason=reply.stop_reason)

    if not fields:
        return Interpretation(
            accepted = False,
            reason   = (
                "The model did not return the expected JSON object, so there was nothing "
                "to validate."
            ),
            status   = "unavailable",
            metadata = metadata,
        )

    findings = validate_card.validate(fields, run)
    if findings:
        return Interpretation(
            accepted = False,
            fields   = {},                  # discarded, not returned for inspection
            reason   = validate_card.summarise(findings).splitlines()[0],
            status   = "rejected",
            findings = findings,
            metadata = metadata,
        )

    return Interpretation(
        accepted = True,
        fields   = fields,
        reason   = "",
        status   = "accepted",
        metadata = metadata,
    )
