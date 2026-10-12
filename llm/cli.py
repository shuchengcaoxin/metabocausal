"""The command-line surface for the LLM layer: list the choices, check a key, read a key.

    python -m llm.cli --list
    python -m llm.cli --check --provider claude
    python -m llm.cli --check --provider gemini --model gemini-flash-latest

THIS MODULE IS WHERE THE ENVIRONMENT IS READ, AND IT IS THE ONLY ONE. Everything under
`llm/` takes a credential as an argument; a surface is what turns a local `.env` into one.
Keeping that split at the boundary is what lets the same layer serve a single developer
from their own file and, later, many users from their own sessions - without the adapters
changing at all. A surface that runs one person's process may read their environment; a
surface that serves several people must not, and the layer below cannot tell the
difference, which is exactly why it never looks.

`.env` is read with python-dotenv when it is installed and by a small parser when it is
not, so a missing optional package cannot stop a developer checking their own key.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm import (
    DISPLAY_NAMES,
    Credential,
    LLMError,
    check,
    default_model,
    menu,
    provider_key,
    resolve,
)

# One environment variable per provider. GEMINI_API_KEY rather than GOOGLE_API_KEY because
# that is the name the project's .env.example and the existing agent.py template already
# use; renaming it would break a developer's working file for no gain.
ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "google":    "GEMINI_API_KEY",
}

INSTALL_HINT = {
    "anthropic": "pip install anthropic",
    "openai":    "pip install openai",
    "google":    "pip install google-genai",
}


def load_env_file(path: Path = REPO_ROOT / ".env") -> dict:
    """`.env` as a dict. Never raises, never logs a value, never mutates os.environ.

    python-dotenv is used when present. The fallback parser handles the only shape this
    project's .env.example has - KEY=value lines and # comments - because a developer
    should be able to check a key without first installing an optional package."""
    try:
        from dotenv import dotenv_values

        return {key: value for key, value in dotenv_values(path).items() if value}
    except ImportError:
        pass

    values: dict = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            values[key.strip()] = value
    return values


def credential_from_env(provider: str, env_path: Path = REPO_ROOT / ".env") -> Credential:
    """The local developer's key for one provider, from `.env` or the real environment.

    The process environment wins over the file, so `ANTHROPIC_API_KEY=... python ...` does
    what it looks like it does. Returns a Credential with an empty key when nothing is
    configured rather than raising - the caller reports that far more helpfully than a
    traceback can, and `Credential.is_usable()` is the check."""
    key = provider_key(provider)
    variable = ENV_VARS[key]
    value = os.environ.get(variable) or load_env_file(env_path).get(variable) or ""
    return Credential(
        provider = key,
        key      = value.strip(),
        source   = "operator_env",
    )


def describe_models() -> str:
    """The provider/model menu, with the status of each spelled out rather than implied."""
    lines = [
        "Configured provider and model choices.",
        "",
        "  'supported'    measured against the evidence fixtures; the note says when and",
        "                 with what result. Re-run them with",
        "                 python scripts/interpretation_fixtures.py --provider <name>",
        "  'experimental' the adapter works and the results have NOT been measured.",
        "                 Usable, but nothing has checked how often its prose is accepted.",
        "",
        f"  {'provider':<20} {'model':<26} {'status':<13} key from",
        f"  {'-' * 20} {'-' * 26} {'-' * 13} {'-' * 20}",
    ]
    for row in menu():
        lines.append(
            f"  {row['provider_name']:<20} {row['model']:<26} {row['status']:<13} "
            f"{ENV_VARS[row['provider']]}"
        )
    notes = [row for row in menu() if row["note"]]
    if notes:
        lines.append("")
        lines.append("Notes:")
        lines.extend(f"  {row['model']}: {row['note']}" for row in notes)
    return "\n".join(lines)


def describe_keys(env_path: Path = REPO_ROOT / ".env") -> str:
    """Which keys are configured. Reports presence and length only, never a value."""
    lines = ["Locally configured keys (presence only - no value is ever printed):", ""]
    for key in sorted(ENV_VARS):
        credential = credential_from_env(key, env_path)
        state = f"set ({len(credential.key)} chars)" if credential.is_usable() else "not set"
        lines.append(f"  {DISPLAY_NAMES[key]:<20} {ENV_VARS[key]:<20} {state}")
    return "\n".join(lines)


def run_check(provider: str, model: str | None, env_path: Path = REPO_ROOT / ".env") -> int:
    """Check one provider/model/key. Returns a process exit code.

    Generates no tokens: the adapter retrieves the model's own record, so this validates
    the credential and the model id together and costs nothing to run."""
    try:
        key = provider_key(provider)
        chosen = model or default_model(key)
        spec = resolve(key, chosen)
    except LLMError as exc:
        print(f"FAILED  {exc.user_message()}")
        return 2

    credential = credential_from_env(key, env_path)
    label = f"{DISPLAY_NAMES[key]} / {spec.model}"

    if not credential.is_usable():
        print(f"FAILED  {label}")
        print(f"        No key found. Set {ENV_VARS[key]} in .env or in the environment.")
        return 2

    try:
        result = check(key, spec.model, credential)
    except LLMError as exc:
        print(f"FAILED  {label}")
        print(f"        {exc.message}")
        hint = INSTALL_HINT.get(key)
        if hint and "not installed" in exc.message:
            print(f"        {hint}")
        return 2

    print(f"OK      {label}  ({result.latency_ms} ms)")
    print(f"        {result.detail}")
    print(f"        status: {spec.status} - not yet validated against the evidence fixtures.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog        = "python -m llm.cli",
        description = "Inspect and check the configured LLM providers and models.",
    )
    parser.add_argument("--list", action="store_true",
                        help="print the configured provider/model choices and exit")
    parser.add_argument("--keys", action="store_true",
                        help="report which provider keys are configured locally")
    parser.add_argument("--check", action="store_true",
                        help="check that a key reaches a model (costs no tokens)")
    parser.add_argument("--provider", default="claude",
                        help="claude | chatgpt | gemini (default: claude)")
    parser.add_argument("--model", default=None,
                        help="model id; defaults to the provider's first configured model")
    args = parser.parse_args(argv)

    if args.list:
        print(describe_models())
        return 0
    if args.keys:
        print(describe_keys())
        return 0
    if args.check:
        return run_check(args.provider, args.model)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
