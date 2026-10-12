"""Which provider/model pairs this build offers, and how honestly each one is labelled.

THE STATUS FIELD IS A CLAIM ABOUT TESTING, NOT ABOUT THE MODEL. A model is `supported`
only once it has been run against the evidence fixtures and the credential-isolation
check and has passed both. Nothing has been, so every entry below ships as
`experimental`. That is not a placeholder to tidy up later - it is the accurate state,
and promoting a row is a deliberate act that follows a passing fixture run.

  supported      validated against the evidence fixtures; offer it plainly
  experimental   the adapter exists and the wiring works; results are not yet validated
  unavailable    named here so the user is told it is not built, rather than silently missing

MODEL IDS GO STALE, AND A WRONG ONE IS CHEAP TO FIND. Providers rename and retire models
faster than this table can be maintained, so `check()` exists: it retrieves the model's
own record from the provider and turns a stale id into a clear message before a user
spends anything. Treat the ids below as a starting list to confirm, not as a guarantee -
their provenance is recorded per block.

WHY A SMALL LIST AT ALL. The 1F contract asks for a configurable list of validated
choices rather than a promise of compatibility with every model a provider publishes.
Offering fewer, checked options is the requirement; an open text box where the user types
any model name is not.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import ModelNotSupported, ProviderNotSupported

SUPPORTED = "supported"
EXPERIMENTAL = "experimental"
UNAVAILABLE = "unavailable"

PROMOTION_RULE = (
    "A model becomes 'supported' when it has passed the evidence fixtures and the "
    "credential-isolation check. Until then it stays 'experimental' whatever it is "
    "capable of."
)


@dataclass(frozen=True)
class ModelSpec:
    provider:  str
    model:     str
    label:     str
    tool_use:  bool
    status:    str
    note:      str = ""

    @property
    def offerable(self) -> bool:
        """Whether this row may be shown to a user as a choice they can run."""
        return self.status in (SUPPORTED, EXPERIMENTAL)


# Anthropic ids are taken from the bundled Claude API reference and are current as of
# this build. claude-opus-5 is the default of the three.
_ANTHROPIC = [
    ModelSpec("anthropic", "claude-opus-5",   "Claude Opus 5",   True, EXPERIMENTAL),
    ModelSpec("anthropic", "claude-sonnet-5", "Claude Sonnet 5", True, EXPERIMENTAL),
    ModelSpec("anthropic", "claude-haiku-4-5", "Claude Haiku 4.5", True, EXPERIMENTAL,
              note="Smallest of the three; use for intake parsing rather than for the verdict."),
]

# Google ids are the ones the existing agent.py template already named, kept so this
# table does not silently disagree with the code it replaces. CONFIRM before promoting.
_GOOGLE = [
    # PROMOTED 2026-09-12. scripts/interpretation_fixtures.py, 10 runs across each of the
    # three demo pairs (states A, B and C): 30/30 prose accepted, 30/30 calls delivered,
    # against a 90% threshold. Reproduce with
    #   python scripts/interpretation_fixtures.py --provider gemini \
    #       --model gemini-flash-lite-latest --runs 10
    # The measurement is of ONE model against THREE cached pairs. It says this model
    # writes section 9 acceptably for the evidence shapes the fixtures cover; it is not a
    # claim about harder pairs, and a fixture set that grows should be re-run.
    ModelSpec("google", "gemini-flash-lite-latest", "Gemini Flash Lite", True, SUPPORTED,
              note="Validated 2026-09-12: 30/30 on the evidence fixtures across states A, B and C."),
    # Flash proper has not been measured. It is the same family and would very likely
    # pass, and 'very likely' is exactly what this status field exists to refuse.
    ModelSpec("google", "gemini-flash-latest",      "Gemini Flash",      True, EXPERIMENTAL,
              note="Not yet measured against the evidence fixtures; run them before promoting."),
]

# OpenAI ids are NOT verified against a current model list - no reference for them was
# available when this table was written. `check()` will reject a stale id with a clear
# message, but confirm these against the provider's own model list before promoting any
# of them past experimental.
_OPENAI = [
    ModelSpec("openai", "gpt-4.1", "GPT-4.1", True, EXPERIMENTAL,
              note="Model id unverified against a current OpenAI model list; run check() first."),
    ModelSpec("openai", "gpt-4o",  "GPT-4o",  True, EXPERIMENTAL,
              note="Model id unverified against a current OpenAI model list; run check() first."),
]

REGISTRY: dict = {
    "anthropic": {spec.model: spec for spec in _ANTHROPIC},
    "openai":    {spec.model: spec for spec in _OPENAI},
    "google":    {spec.model: spec for spec in _GOOGLE},
}

# The name a person uses, mapped to the provider key. Users say "Claude" and "ChatGPT";
# the code says "anthropic" and "openai". Both have to work at the front door.
ALIASES = {
    "claude":    "anthropic",
    "anthropic": "anthropic",
    "chatgpt":   "openai",
    "openai":    "openai",
    "gpt":       "openai",
    "gemini":    "google",
    "google":    "google",
}

DISPLAY_NAMES = {
    "anthropic": "Claude (Anthropic)",
    "openai":    "ChatGPT (OpenAI)",
    "google":    "Gemini (Google)",
}


def provider_key(name: str) -> str:
    """'Claude' -> 'anthropic'. Raises ProviderNotSupported for anything unknown."""
    key = ALIASES.get(str(name or "").strip().casefold())
    if key is None:
        raise ProviderNotSupported(
            f"No adapter for provider {name!r}. Built in: "
            + ", ".join(sorted(DISPLAY_NAMES.values())),
            provider = str(name or ""),
        )
    return key


def providers() -> list:
    """Provider keys, in a stable order for a menu."""
    return sorted(REGISTRY)


def models_for(provider: str, *, offerable_only: bool = True) -> list:
    """Every model of one provider, newest-intent first as listed above."""
    key = provider_key(provider)
    specs = list(REGISTRY[key].values())
    return [spec for spec in specs if spec.offerable] if offerable_only else specs


def resolve(provider: str, model: str) -> ModelSpec:
    """The spec for one provider/model pair.

    Raises rather than falling back to a default model. A caller that wanted a default
    should ask for `default_model()` explicitly: silently running a different model than
    the user picked can move them onto another account, another price, or another set of
    capabilities without telling them."""
    key = provider_key(provider)
    wanted = str(model or "").strip()
    spec = REGISTRY[key].get(wanted)

    if spec is None:
        offered = ", ".join(sorted(REGISTRY[key])) or "none"
        raise ModelNotSupported(
            f"{wanted!r} is not a configured model for {DISPLAY_NAMES[key]}. "
            f"Configured: {offered}",
            provider = key,
            model    = wanted,
        )
    if spec.status == UNAVAILABLE:
        raise ModelNotSupported(
            f"{spec.label} is listed but not built in this version"
            + (f": {spec.note}" if spec.note else "."),
            provider = key,
            model    = wanted,
        )
    return spec


def default_model(provider: str) -> str:
    """The first offerable model of a provider. Used only where a caller asked for one."""
    offerable = models_for(provider)
    if not offerable:
        raise ModelNotSupported(
            f"No offerable model is configured for {provider!r}.",
            provider = provider_key(provider),
        )
    return offerable[0].model


def menu() -> list:
    """Every offerable choice, flattened, for a provider/model picker.

    Carries `status` and `note` so a surface can show them. A picker that renders only the
    labels turns an honest table into an implied endorsement."""
    rows = []
    for key in providers():
        for spec in models_for(key):
            rows.append({
                "provider":      key,
                "provider_name": DISPLAY_NAMES[key],
                "model":         spec.model,
                "label":         spec.label,
                "status":        spec.status,
                "tool_use":      spec.tool_use,
                "note":          spec.note,
            })
    return rows


def run_metadata(spec: ModelSpec, credential, mode: str) -> dict:
    """The non-secret record of what generated a run, for the card and the ledger.

    Takes the credential only to read its `source`. Anything this function returns is safe
    to write to disk; that is the entire reason it exists rather than callers assembling
    the dictionary themselves and one of them reaching for `.key`."""
    record = {
        "provider":       spec.provider,
        "provider_name":  DISPLAY_NAMES[spec.provider],
        "model":          spec.model,
        "model_status":   spec.status,
        "execution_mode": mode,
    }
    if credential is not None:
        record.update(credential.redacted())
    return record
