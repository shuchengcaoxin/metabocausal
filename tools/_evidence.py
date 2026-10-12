"""Small, dependency-free transport and envelope/ledger boundary for section 1E."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
try:
    import fcntl
except ImportError:  # Windows has no fcntl; single-process append needs no lock
    fcntl = None
import inspect
import json
import math
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_recorder = ContextVar("metabocausal_1e_recorder", default=None)
TIMEOUT = 20


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _reject_json_constant(value):
    raise ValueError(f"Non-finite JSON constant from source: {value}")


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"JSON number outside finite float range: {value}")
    return result


class JsonlRecorder:
    """Append one complete envelope; suitable for standalone runs on Linux."""

    def __init__(self, path):
        self.path = Path(path)

    def __call__(self, envelope):
        line = json.dumps(envelope, ensure_ascii=False, allow_nan=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            if fcntl is not None:
                fcntl.flock(stream, fcntl.LOCK_EX)
            stream.write(line)
            stream.flush()
            if fcntl is not None:
                fcntl.flock(stream, fcntl.LOCK_UN)


@contextmanager
def recording(recorder):
    """Bind a run's record(envelope) callback; supports nested/async contexts.

    For a team record(envelope, stem), pass functools.partial(record, stem=stem).
    If dispatching tools in threads, propagate context with copy_context().run.
    """
    if not callable(recorder):
        raise TypeError("recorder must be callable")
    token = _recorder.set(recorder)
    try:
        yield
    finally:
        _recorder.reset(token)


def finish(envelope):
    recorder = _recorder.get()
    if recorder is None:
        recorder = JsonlRecorder(os.environ.get(
            "METABOCAUSAL_LEDGER_PATH", "cards/1e.ledger.jsonl"))
    try:
        recorder(envelope)
    except Exception as exc:
        # A failed audit write must never look like fully successful evidence.
        envelope["data"]["retrieval_status"] = envelope["status"]
        envelope["data"]["ledger_error"] = f"{type(exc).__name__}: {exc}"
        envelope["data"]["error"] = "Ledger write failed"
        envelope["status"] = "error"
        envelope["caveats"].append("Envelope was not confirmed persisted; do not render as audited evidence.")
    return envelope


def evidence_tool(source, url, caveats=()):
    """Keep the four public signatures; catch failures and persist once per call."""
    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            env = dict(tool=function.__name__, args={}, source=source, url=url,
                       retrieved_at=utc_now(), status="error", data={},
                       caveats=list(caveats))
            client = Client()
            try:
                bound = signature.bind(*args, **kwargs)
                for name, value in bound.arguments.items():
                    try:
                        json.dumps(value, allow_nan=False)
                        env["args"][name] = value
                    except (TypeError, ValueError, OverflowError, RecursionError):
                        env["args"][name] = {"invalid_python_type": type(value).__name__}
                        env["caveats"].append(f"Non-JSON argument {name} represented by type only.")
                for name, value in bound.arguments.items():
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(f"{name} must be a nonempty string")
                token = _client.set(client)
                try:
                    status, data, notes = function(*args, **kwargs)
                finally:
                    _client.reset(token)
                env.update(status=status, data=data)
                env["caveats"].extend(notes)
            except Exception as exc:
                env["data"]["error"] = f"{type(exc).__name__}: {exc}"
            env["data"]["provenance"] = client.requests
            return finish(env)
        return wrapped
    return decorate


_client = ContextVar("metabocausal_1e_client")


def client():
    return _client.get()


class Client:
    def __init__(self):
        self.requests = []

    def request(self, url, *, params=None, body=None, retry_5xx=False):
        if params:
            url += "?" + urlencode(params)
        for attempt in range(1, 3 if retry_5xx else 2):
            record = dict(url=url, method="POST" if body is not None else "GET",
                          retrieved_at=utc_now(), attempt=attempt)
            if body is not None:
                record["request_body"] = body
            self.requests.append(record)
            request = Request(url, data=None if body is None else json.dumps(body).encode(),
                              headers={"Accept": "application/json",
                                       "Content-Type": "application/json",
                                       "User-Agent": "MetaboCausal-1E/0.1"})
            try:
                with urlopen(request, timeout=TIMEOUT) as response:
                    record["http_status"] = response.status
                    raw = response.read()
                    try:
                        payload = json.loads(raw, parse_constant=_reject_json_constant,
                                             parse_float=_finite_float)
                    except (ValueError, UnicodeError):
                        record["response_text"] = raw[:8192].decode("utf-8", errors="replace")
                        raise
                    record["response"] = payload
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object from source")
                return payload
            except HTTPError as exc:
                record["http_status"] = exc.code
                record["error"] = f"HTTP {exc.code}: {exc.reason}"
                # Preserve GraphQL error bodies on 400 as well as HTTP-200 errors.
                try:
                    record["response_text"] = exc.read(8192).decode("utf-8", errors="replace")
                finally:
                    exc.close()
                if retry_5xx and attempt == 1 and 500 <= exc.code < 600:
                    continue
                raise
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
                raise

    def graphql(self, url, query, variables):
        payload = self.request(url, body={"query": query, "variables": variables})
        if payload.get("errors"):
            raise ValueError("GraphQL errors: " + json.dumps(payload["errors"]))
        data = payload["data"]
        if not isinstance(data, dict):
            raise ValueError("Missing GraphQL data object")
        return data


def rows(value):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("Expected a list of source records")
    return value


def count(value):
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative integer count")
    return value


def number(value):
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ValueError("Expected a finite number or null")
    return value
