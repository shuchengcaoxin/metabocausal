"""Provider adapters. One module per service, all behind `llm.base.Provider`.

Named `adapters`, not `providers`, because `llm.providers` is already the function that
lists provider keys. A module and a function of the same name on one package resolve
differently depending on whether the submodule has been imported yet, which is a bug that
only appears once something else imports it first.

Adapters are constructed without credentials and hold no per-user state, so one instance
is safe to share across concurrent requests; the credential arrives with the call.

Each module imports its client library lazily, inside the call. That is deliberate: the
SDKs are optional dependencies, and an uninstalled one must become a ProviderUnavailable
for that single provider rather than an ImportError that stops the deterministic product
from starting.
"""

from .anthropic_api import AnthropicProvider
from .google_api import GoogleProvider
from .openai_api import OpenAIProvider

__all__ = ["AnthropicProvider", "GoogleProvider", "OpenAIProvider"]
