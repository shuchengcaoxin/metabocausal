"""Provider-neutral types for the LLM layer: credentials, replies, and failures.

Nothing in this package touches the evidence pipeline. The deterministic chain in
`pipeline.run_pair` is the product; this layer only ever adds prose on top of a run that
has already finished, and every failure here has to leave that run shippable.

THE CREDENTIAL RULE, WHICH IS THE WHOLE POINT OF THIS MODULE. A `Credential` is a value
passed down the call stack, not a setting read from the environment. No adapter reads
`os.environ`, and no adapter writes it. That is what makes two concurrent users with two
different keys safe, and it is the one property that is expensive to retrofit: a client
built from process-wide state works perfectly in local development and silently serves
one user's request on another user's account the first time two arrive at once.

Keys are kept out of `repr`, out of run metadata, and out of the ledger. `Credential`
overrides both `__repr__` and `__str__` because a dataclass would otherwise print the key
into the first traceback that includes a frame holding one.

THE FAILURE TAXONOMY. The errors below are separate classes because the card has to say
different things for each of them, and because "the model was unavailable" must never be
allowed to read as "the evidence was absent". Every one of them is a reason to fall back
to the deterministic card; none of them is a scientific statement.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------- credentials

@dataclass(frozen=True, repr=False)
class Credential:
    """One provider credential, for one request.

    `source` is recorded in non-secret run metadata so a run can say whether it used the
    operator's configured key or a key the user supplied for their own account. `key` is
    never recorded anywhere.
    """

    provider: str
    key:      str
    source:   str = "user_session"

    def __repr__(self) -> str:
        return (
            f"Credential(provider={self.provider!r}, source={self.source!r}, "
            "key=<redacted>)"
        )

    __str__ = __repr__

    def redacted(self) -> dict:
        """What may be written to run metadata, a log line or a ledger entry."""
        return {
            "provider": self.provider,
            "source":   self.source,
        }

    def is_usable(self) -> bool:
        return bool(str(self.key or "").strip())


# ---------------------------------------------------------------- results

@dataclass(frozen=True)
class CheckResult:
    """The outcome of a connection check: can this key reach this model, right now.

    A check is deliberately cheap and costs no generated tokens - every adapter implements
    it by retrieving the model's own record. That validates the credential AND the model
    id in one call, which is what the user actually wants to know before they run."""

    ok:         bool
    provider:   str
    model:      str
    detail:     str
    latency_ms: int | None = None


@dataclass(frozen=True)
class Reply:
    """One completed model response. `usage` is provider-shaped and only ever reported."""

    text:        str
    provider:    str
    model:       str
    stop_reason: str | None = None
    usage:       dict = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not str(self.text or "").strip()


# ---------------------------------------------------------------- failures

class LLMError(Exception):
    """Base for every failure in this package.

    A caller that catches only this still behaves correctly: the deterministic card ships.
    The subclasses exist so the message shown to the user names the actual problem instead
    of a generic one."""

    def __init__(self, message: str, *, provider: str = "", model: str = ""):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.model = model

    def user_message(self) -> str:
        """What a surface may show. Never contains a credential."""
        where = " / ".join(part for part in (self.provider, self.model) if part)
        return f"{self.message} ({where})" if where else self.message


class ProviderNotSupported(LLMError):
    """A provider this build has no adapter for. Naming it is not the same as having it."""


class ModelNotSupported(LLMError):
    """A model that is not in the registry, or is registered as unavailable.

    Raised instead of quietly substituting a model that would work. Changing the model
    name alone never makes another service compatible, and a silent switch can move a
    user onto an account or a price they did not choose."""


class CredentialMissing(LLMError):
    """No key was supplied for the selected provider. Not an error condition of the run."""


class CredentialRejected(LLMError):
    """The provider refused the key: absent, wrong, revoked, or lacking access.

    Deliberately distinct from ProviderUnavailable. One is fixed by the user pasting a
    different key; the other is fixed by waiting."""


class RateLimited(LLMError):
    """The provider is throttling. `retry_after` is seconds when the provider said so."""

    def __init__(self, message: str, *, provider: str = "", model: str = "",
                 retry_after: float | None = None):
        super().__init__(message, provider=provider, model=model)
        self.retry_after = retry_after


class ProviderUnavailable(LLMError):
    """The provider could not be reached, or its client library is not installed.

    A missing package lands here rather than as an ImportError at import time, so one
    uninstalled optional dependency cannot stop the deterministic product from running."""


class ResponseUnusable(LLMError):
    """A response arrived and cannot be used: empty, truncated, malformed, or refused.

    Separate from every transport failure because the request DID succeed. The prose is
    discarded and the deterministic card ships, exactly as for a transport failure, but
    the reason recorded is different and that distinction is worth keeping."""


# ---------------------------------------------------------------- the adapter contract

class Provider:
    """What every adapter implements. Subclasses are constructed without credentials.

    An adapter instance holds no per-user state: the credential arrives with the call, so
    one instance may serve many users concurrently. Adapters import their client library
    lazily, inside the call, so that an uninstalled optional dependency becomes a
    ProviderUnavailable for that one provider rather than an import failure for the app.
    """

    name = ""

    def check(self, model: str, credential: Credential) -> CheckResult:
        raise NotImplementedError

    def complete(
        self,
        messages:    list,
        *,
        model:       str,
        credential:  Credential,
        system:      str = "",
        max_tokens:  int = 4096,
        temperature: float | None = None,
        timeout:     float = 60.0,
    ) -> Reply:
        raise NotImplementedError
