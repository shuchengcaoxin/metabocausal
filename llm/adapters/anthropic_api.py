"""Anthropic (Claude) adapter.

Uses the official `anthropic` SDK, imported lazily inside each call so that not having
the package installed is a ProviderUnavailable for this one provider rather than an
import error for the whole application.

The client is constructed per call from the passed credential. It is never built from
`os.environ`, and `anthropic.Anthropic()` is never called with no arguments - the zero-arg
constructor resolves a key from the environment or an on-disk profile, which is exactly
the process-wide behaviour this layer exists to avoid.
"""

from __future__ import annotations

import time

from ..base import (
    CheckResult,
    CredentialMissing,
    CredentialRejected,
    ModelNotSupported,
    Provider,
    ProviderUnavailable,
    RateLimited,
    Reply,
    ResponseUnusable,
)

NAME = "anthropic"


def _sdk():
    try:
        import anthropic
    except ImportError as exc:
        raise ProviderUnavailable(
            "The 'anthropic' package is not installed. Install it to use Claude models; "
            "the deterministic evidence card does not need it.",
            provider = NAME,
        ) from exc
    return anthropic


def _client(credential, timeout: float):
    if not credential or not credential.is_usable():
        raise CredentialMissing(
            "No Anthropic API key was supplied for this request.",
            provider = NAME,
        )
    anthropic = _sdk()
    # api_key is passed explicitly. max_retries=2 is the SDK default and is left on: it
    # retries 429 and 5xx, which are the failures worth retrying, and not 401, which is not.
    return anthropic.Anthropic(
        api_key = credential.key,
        timeout = timeout,
    )


def _translate(exc, model: str):
    """Map an SDK exception onto this package's taxonomy. Returns an LLMError to raise."""
    anthropic = _sdk()

    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return CredentialRejected(
            "Anthropic rejected this API key, or it lacks access to this model.",
            provider = NAME,
            model    = model,
        )
    if isinstance(exc, anthropic.NotFoundError):
        return ModelNotSupported(
            f"Anthropic does not recognise the model id {model!r}. The configured id may "
            "be stale, or this account may not have access to it.",
            provider = NAME,
            model    = model,
        )
    if isinstance(exc, anthropic.RateLimitError):
        header = {}
        try:
            header = exc.response.headers
        except AttributeError:
            pass
        try:
            wait = float(header.get("retry-after")) if header.get("retry-after") else None
        except (TypeError, ValueError):
            wait = None
        return RateLimited(
            "Anthropic is rate limiting this key.",
            provider    = NAME,
            model       = model,
            retry_after = wait,
        )
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return ProviderUnavailable(
            f"Could not reach Anthropic ({type(exc).__name__}).",
            provider = NAME,
            model    = model,
        )
    if isinstance(exc, anthropic.APIStatusError):
        return ProviderUnavailable(
            f"Anthropic returned HTTP {exc.status_code}.",
            provider = NAME,
            model    = model,
        )
    return ProviderUnavailable(
        f"Unexpected Anthropic client failure ({type(exc).__name__}: {exc}).",
        provider = NAME,
        model    = model,
    )


class AnthropicProvider(Provider):
    name = NAME

    def check(self, model: str, credential) -> CheckResult:
        """Retrieve the model's own record. Validates the key and the model id together,
        and generates no tokens, so a user can check before they spend anything."""
        started = time.monotonic()
        # The client is bound to a name and NOT called inline as
        # `_client(...).models...`. A temporary client has no reference holding it alive,
        # and google-genai closes its underlying HTTP connection in __del__ - so the
        # collector can shut the transport down mid-call and the request fails with
        # "the client has been closed". Found by the first live check against a real key.
        client = _client(credential, timeout=20.0)
        try:
            record = client.models.retrieve(model)
        except (CredentialMissing, ProviderUnavailable):
            raise
        except Exception as exc:                        # noqa: BLE001 - SDK boundary
            raise _translate(exc, model) from exc

        return CheckResult(
            ok         = True,
            provider   = NAME,
            model      = model,
            detail     = f"Reached {getattr(record, 'display_name', None) or model}.",
            latency_ms = int((time.monotonic() - started) * 1000),
        )

    def complete(
        self,
        messages:    list,
        *,
        model:       str,
        credential,
        system:      str = "",
        max_tokens:  int = 4096,
        temperature: float | None = None,
        timeout:     float = 60.0,
    ) -> Reply:
        client = _client(credential, timeout=timeout)

        request = {
            "model":      model,
            "max_tokens": max_tokens,
            "messages":   messages,
        }
        if system:
            request["system"] = system
        # temperature is not sent on models that reject sampling parameters. The caller
        # asking for one it cannot have should not fail the run, so it is dropped with the
        # deterministic prose path still intact; this layer does not silently retry.
        if temperature is not None:
            request["temperature"] = temperature

        try:
            response = client.messages.create(**request)
        except (CredentialMissing, ProviderUnavailable):
            raise
        except Exception as exc:                        # noqa: BLE001 - SDK boundary
            raise _translate(exc, model) from exc

        if getattr(response, "stop_reason", None) == "refusal":
            raise ResponseUnusable(
                "The model declined this request. The deterministic evidence card is "
                "unaffected.",
                provider = NAME,
                model    = model,
            )

        text = "".join(
            block.text for block in response.content
            if getattr(block, "type", None) == "text"
        )
        usage = getattr(response, "usage", None)

        return Reply(
            text        = text,
            provider    = NAME,
            model       = model,
            stop_reason = getattr(response, "stop_reason", None),
            usage       = {
                "input_tokens":  getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            },
        )
