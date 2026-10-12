"""Google (Gemini) adapter, on the `google-genai` package the project already depends on.

Same shape as the other two adapters. Gemini's own differences: the system prompt travels
in a config object rather than in the message list, message content is a `parts` list
under a `role`, and the SDK does not expose a typed exception per failure class - so the
translation below reads the HTTP status off the error rather than matching classes.

This replaces the process-wide `GEMINI_API_KEY` read in the unfinished agent.py template.
That template is still the only place a key is read from the environment; nothing in this
package does.
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

NAME = "google"


def _sdk():
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise ProviderUnavailable(
            "The 'google-genai' package is not installed. Install it to use Gemini "
            "models; the deterministic evidence card does not need it.",
            provider = NAME,
        ) from exc
    return genai, types


def _client(credential, timeout: float):
    if not credential or not credential.is_usable():
        raise CredentialMissing(
            "No Gemini API key was supplied for this request.",
            provider = NAME,
        )
    genai, _ = _sdk()
    # api_key explicit. genai.Client() with no argument reads GEMINI_API_KEY from the
    # process environment - which is what agent.py does today and what this layer replaces.
    return genai.Client(
        api_key      = credential.key,
        http_options = {"timeout": int(timeout * 1000)},
    )


def _status_of(exc) -> int | None:
    """Best-effort HTTP status from a google-genai error, which has no typed hierarchy."""
    for attribute in ("code", "status_code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _translate(exc, model: str):
    status = _status_of(exc)
    text = str(exc)

    if status in (401, 403) or "API key not valid" in text or "PERMISSION_DENIED" in text:
        return CredentialRejected(
            "Google rejected this API key, or it lacks access to this model.",
            provider = NAME,
            model    = model,
        )
    if status == 404 or "NOT_FOUND" in text:
        return ModelNotSupported(
            f"Google does not recognise the model id {model!r}. The configured id may be "
            "stale, or this account may not have access to it.",
            provider = NAME,
            model    = model,
        )
    if status == 429 or "RESOURCE_EXHAUSTED" in text:
        # Google returns 429 RESOURCE_EXHAUSTED for two conditions that need opposite
        # responses from the user: a per-minute quota, which waiting fixes, and an empty
        # prepaid balance, which waiting never fixes. Reporting the second as rate
        # limiting sends someone off to tune their request rate while the actual problem
        # is billing. Found on the first live call against a real key.
        depleted = any(
            phrase in text.lower()
            for phrase in ("credits are depleted", "prepayment", "billing", "quota exceeded for quota metric")
        )
        if depleted:
            return RateLimited(
                "Google refused the request: this project's prepaid credits are depleted, "
                "or its billing quota is exhausted. Retrying will not help - check the "
                "project's billing and free-tier status at https://ai.studio/projects.",
                provider = NAME,
                model    = model,
            )
        return RateLimited(
            "Google is rate limiting this key. Free-tier Gemini quotas are small; this "
            "one should clear on its own.",
            provider = NAME,
            model    = model,
        )
    if status is not None and status >= 500:
        return ProviderUnavailable(
            f"Google returned HTTP {status}.",
            provider = NAME,
            model    = model,
        )
    return ProviderUnavailable(
        f"Could not complete the Gemini request ({type(exc).__name__}: {exc}).",
        provider = NAME,
        model    = model,
    )


class GoogleProvider(Provider):
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
            record = client.models.get(model=model)
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
        _, types = _sdk()
        client = _client(credential, timeout=timeout)

        # Gemini names the assistant role "model", and carries content as parts. The
        # caller passes the same OpenAI-ish message list for every provider; reshaping it
        # is this adapter's job.
        contents = [
            {
                "role":  "model" if message.get("role") == "assistant" else "user",
                "parts": [{"text": message.get("content", "")}],
            }
            for message in messages
        ]

        # Automatic function calling is switched off explicitly. This layer registers no
        # tools by design - the pipeline has already retrieved everything - and leaving
        # AFC on makes google-genai warn on every single call about a feature that has
        # nothing to drive it.
        config = {
            "max_output_tokens": max_tokens,
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        if system:
            config["system_instruction"] = system
        if temperature is not None:
            config["temperature"] = temperature

        try:
            response = client.models.generate_content(
                model    = model,
                contents = contents,
                config   = types.GenerateContentConfig(**config),
            )
        except (CredentialMissing, ProviderUnavailable):
            raise
        except Exception as exc:                        # noqa: BLE001 - SDK boundary
            raise _translate(exc, model) from exc

        text = getattr(response, "text", None)
        if text is None:
            raise ResponseUnusable(
                "Gemini returned no text for this request. A safety block or an empty "
                "candidate list both land here; neither says anything about the evidence.",
                provider = NAME,
                model    = model,
            )

        usage = getattr(response, "usage_metadata", None)
        candidates = getattr(response, "candidates", None) or []

        return Reply(
            text        = text,
            provider    = NAME,
            model       = model,
            stop_reason = str(getattr(candidates[0], "finish_reason", "")) if candidates else None,
            usage       = {
                "input_tokens":  getattr(usage, "prompt_token_count", None),
                "output_tokens": getattr(usage, "candidates_token_count", None),
            },
        )
