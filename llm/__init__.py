"""The switchable LLM layer: choose provider, choose model, supply that provider's key.

    from llm import Credential, check, complete, menu

    cred = Credential(provider="anthropic", key=user_supplied_key)
    status = check("claude", "claude-opus-5", cred)      # costs no tokens
    reply  = complete([{"role": "user", "content": "..."}],
                      provider="claude", model="claude-opus-5", credential=cred)

FOUR RULES THIS PACKAGE KEEPS, AND WHY EACH ONE IS LOAD-BEARING.

1. No global state. A credential is an argument, never an environment variable. Two
   concurrent users with two different keys is the case that breaks a process-wide client,
   and it breaks it silently and in production rather than in development.

2. No silent substitution. An unsupported provider or model raises. Changing a model name
   alone never makes another service compatible, and quietly switching can move someone
   onto an account, a price or a capability set they did not choose.

3. No secrets in artifacts. `Credential` redacts itself in `repr`, `run_metadata()`
   records provider/model/source and never the key, and nothing here writes to the ledger.

4. The deterministic card always ships. Every failure in this package is an LLMError, and
   every LLMError means: discard the prose, keep the evidence card, record the reason. A
   model that was unavailable is never allowed to read as evidence that was absent.

WHAT THIS PACKAGE DOES NOT DO. It does not call the pipeline, define tools, write prompts
or validate output. Interpretation and its validator are the next stage; this layer is
only the switchboard they will sit on.
"""

from __future__ import annotations

from .base import (
    CheckResult,
    Credential,
    CredentialMissing,
    CredentialRejected,
    LLMError,
    ModelNotSupported,
    Provider,
    ProviderNotSupported,
    ProviderUnavailable,
    RateLimited,
    Reply,
    ResponseUnusable,
)
from .registry import (
    DISPLAY_NAMES,
    EXPERIMENTAL,
    PROMOTION_RULE,
    SUPPORTED,
    UNAVAILABLE,
    ModelSpec,
    default_model,
    menu,
    models_for,
    provider_key,
    providers,
    resolve,
    run_metadata,
)

__all__ = [
    "CheckResult", "Credential", "CredentialMissing", "CredentialRejected", "LLMError",
    "ModelNotSupported", "ModelSpec", "Provider", "ProviderNotSupported",
    "ProviderUnavailable", "RateLimited", "Reply", "ResponseUnusable",
    "DISPLAY_NAMES", "EXPERIMENTAL", "PROMOTION_RULE", "SUPPORTED", "UNAVAILABLE",
    "default_model", "menu", "models_for", "provider_key", "providers", "resolve",
    "run_metadata", "adapter_for", "check", "complete",
]

# Adapters are stateless, so one instance each is built on first use and reused. The
# credential is never held here - it arrives with every call.
_ADAPTERS: dict = {}


def adapter_for(provider: str):
    """The adapter for one provider. Raises ProviderNotSupported for anything unbuilt."""
    key = provider_key(provider)
    if key not in _ADAPTERS:
        from .adapters import AnthropicProvider, GoogleProvider, OpenAIProvider

        _ADAPTERS.update({
            "anthropic": AnthropicProvider(),
            "openai":    OpenAIProvider(),
            "google":    GoogleProvider(),
        })
    return _ADAPTERS[key]


def check(provider: str, model: str, credential: Credential) -> CheckResult:
    """Can this key reach this model right now.

    Generates no tokens: every adapter implements it by retrieving the model's own record,
    which validates the credential and the model id together. This is the step between
    'enter your key' and 'run', and it is the one that catches a stale configured model id
    before a user spends anything.

    Returns a CheckResult only on success; every failure raises its specific LLMError so
    the caller can say which of the four things went wrong."""
    spec = resolve(provider, model)
    _require_matching_provider(spec, credential)
    return adapter_for(spec.provider).check(spec.model, credential)


def complete(
    messages:    list,
    *,
    provider:    str,
    model:       str,
    credential:  Credential,
    system:      str = "",
    max_tokens:  int = 4096,
    temperature: float | None = None,
    timeout:     float = 60.0,
) -> Reply:
    """One completion, on the selected provider and model, with the supplied credential.

    `max_tokens` defaults to 4096 rather than something larger because this layer's job is
    a verdict paragraph on top of a finished run, not a long document - and a bounded
    ceiling also bounds what one card can cost. Raise it at the call site when a caller
    genuinely needs more.

    Every failure raises an LLMError. There is no retry against a different model and no
    fallback to another provider: that decision belongs to the caller, which owns the
    deterministic card this can always fall back to."""
    spec = resolve(provider, model)
    _require_matching_provider(spec, credential)

    reply = adapter_for(spec.provider).complete(
        messages,
        model       = spec.model,
        credential  = credential,
        system      = system,
        max_tokens  = max_tokens,
        temperature = temperature,
        timeout     = timeout,
    )
    if reply.is_empty():
        raise ResponseUnusable(
            "The model returned an empty response.",
            provider = spec.provider,
            model    = spec.model,
        )
    return reply


def _require_matching_provider(spec: ModelSpec, credential: Credential) -> None:
    """A key belongs to one service. Sending an Anthropic key to Google is a mistake worth
    catching here rather than as a rejected-credential error from the far end - the user
    needs to be told they picked the wrong key, not that their key is invalid."""
    if credential is None or not credential.is_usable():
        raise CredentialMissing(
            f"No API key was supplied for {DISPLAY_NAMES[spec.provider]}.",
            provider = spec.provider,
            model    = spec.model,
        )
    if credential.provider and credential.provider != spec.provider:
        raise CredentialRejected(
            f"This key is registered for {DISPLAY_NAMES.get(credential.provider, credential.provider)} "
            f"but {DISPLAY_NAMES[spec.provider]} was selected. Each provider needs its own key.",
            provider = spec.provider,
            model    = spec.model,
        )
