"""OpenAI (ChatGPT) adapter.

Same shape as the Anthropic adapter: lazy import, per-call client built from the passed
credential, SDK exceptions translated into this package's taxonomy. The differences are
OpenAI's own: the system prompt is a message with role "system" rather than a top-level
field, and the response is a choices list rather than a content-block list.

The configured model ids in the registry are NOT verified against a current OpenAI model
list. `check()` is what catches a stale one: it retrieves the model record and turns an
unrecognised id into a clear message before the user spends anything.
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

NAME = "openai"


def _sdk():
    try:
        import openai
    except ImportError as exc:
        raise ProviderUnavailable(
            "The 'openai' package is not installed. Install it to use ChatGPT models; "
            "the deterministic evidence card does not need it.",
            provider = NAME,
        ) from exc
    return openai


def _client(credential, timeout: float):
    if not credential or not credential.is_usable():
        raise CredentialMissing(
            "No OpenAI API key was supplied for this request.",
            provider = NAME,
        )
    openai = _sdk()
    # api_key explicit, never the zero-arg constructor: that one reads OPENAI_API_KEY from
    # the process environment, which is the shared-state failure this layer exists to stop.
    return openai.OpenAI(
        api_key = credential.key,
        timeout = timeout,
    )


def _translate(exc, model: str):
    openai = _sdk()

    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return CredentialRejected(
            "OpenAI rejected this API key, or it lacks access to this model.",
            provider = NAME,
            model    = model,
        )
    if isinstance(exc, openai.NotFoundError):
        return ModelNotSupported(
            f"OpenAI does not recognise the model id {model!r}. The configured id may be "
            "stale, or this account may not have access to it.",
            provider = NAME,
            model    = model,
        )
    if isinstance(exc, openai.RateLimitError):
        return RateLimited(
            "OpenAI is rate limiting this key.",
            provider = NAME,
            model    = model,
        )
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return ProviderUnavailable(
            f"Could not reach OpenAI ({type(exc).__name__}).",
            provider = NAME,
            model    = model,
        )
    if isinstance(exc, openai.APIStatusError):
        return ProviderUnavailable(
            f"OpenAI returned HTTP {getattr(exc, 'status_code', 'an error')}.",
            provider = NAME,
            model    = model,
        )
    return ProviderUnavailable(
        f"Unexpected OpenAI client failure ({type(exc).__name__}: {exc}).",
        provider = NAME,
        model    = model,
    )


class OpenAIProvider(Provider):
    name = NAME

    def check(self, model: str, credential) -> CheckResult:
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
            detail     = f"Reached {getattr(record, 'id', None) or model}.",
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

        # OpenAI carries the system prompt as the first message rather than as its own
        # request field. Translating it here is the adapter's job; the caller passes the
        # same arguments whichever provider is selected.
        payload = ([{"role": "system", "content": system}] if system else []) + list(messages)

        request = {
            "model":       model,
            "messages":    payload,
            "max_tokens":  max_tokens,
        }
        if temperature is not None:
            request["temperature"] = temperature

        try:
            response = client.chat.completions.create(**request)
        except (CredentialMissing, ProviderUnavailable):
            raise
        except Exception as exc:                        # noqa: BLE001 - SDK boundary
            raise _translate(exc, model) from exc

        choices = getattr(response, "choices", None) or []
        if not choices:
            raise ResponseUnusable(
                "OpenAI returned no choices for this request.",
                provider = NAME,
                model    = model,
            )

        choice = choices[0]
        usage = getattr(response, "usage", None)

        return Reply(
            text        = getattr(choice.message, "content", "") or "",
            provider    = NAME,
            model       = model,
            stop_reason = getattr(choice, "finish_reason", None),
            usage       = {
                "input_tokens":  getattr(usage, "prompt_tokens", None),
                "output_tokens": getattr(usage, "completion_tokens", None),
            },
        )
