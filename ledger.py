"""The ledger: every tool envelope of one run, verbatim, one JSON object per line.

This is what makes the card auditable. `render.py` builds the mechanical sections
from these lines, `classify.py` decides A/B/C from them, and `validate_card.py`
checks that every number in the model's two paragraphs appears in one of them. A
number that is not in the ledger did not come from a database.

Usage - `agent.py` calls start/stop, tools only ever call record:

    import ledger
    ledger.start("glycine_coronary-artery-disease")
    ...
    ledger.record(env)          # inside every tool, immediately before returning
    ...
    envelopes = ledger.load("glycine_coronary-artery-disease")
    ledger.stop()

`record()` before `start()` is a deliberate silent no-op, so `python tools/x.py`
and the unit tests can exercise a tool without leaving a stray file behind.

THE ACTIVE RUN IS A ContextVar, NOT A MODULE GLOBAL. slack_bolt dispatches listeners
on a thread pool (App defaults to five listener workers, Socket Mode to ten message
workers), so two mentions can be inside `run_pair` at the same moment. With a module
global the second `start()` would repoint the run for the first one: its remaining
envelopes would land in the second pair's file, and both cards would print a ledger
count that is not theirs. A ContextVar is per-thread and per-task, so each worker
carries its own run - the same reason `tools/_evidence.py` holds its recorder in one.
This does not make two runs of the SAME stem safe: they would truncate one file twice.
`pipeline.run_pair` takes `stem_prefix` and the Slack shell serialises its runs.
"""

from __future__ import annotations

import contextvars
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
CARDS_DIR = REPO_ROOT / "cards"
SUFFIX = ".ledger.jsonl"

_NO_RUN = (None, None)
_active: contextvars.ContextVar = contextvars.ContextVar(
    "metabocausal_ledger_active",
    default = _NO_RUN,
)


def path_for(stem: str) -> Path:
    """Where the ledger of run `stem` lives: cards/{stem}.ledger.jsonl."""
    return CARDS_DIR / f"{stem}{SUFFIX}"


def start(stem: str) -> None:
    """Open the ledger for one run and truncate anything left from a previous run of
    the same pair, so a ledger always describes exactly one run. The run belongs to the
    calling thread or task only."""
    target = path_for(stem)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("", encoding="utf-8")
    _active.set((target, stem))


def record(envelope: dict) -> None:
    """Append one envelope, verbatim, to the active ledger of THIS thread. No-op if
    `start()` has not been called here. Never raises: a tool must not fail because
    logging failed."""
    _active_path, _ = _active.get()
    if _active_path is None:
        return
    try:
        line = json.dumps(
            envelope,
            ensure_ascii = False,
            default      = str,
        )
        with _active_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError) as exc:
        print(f"[ledger] could not record {envelope.get('tool')!r}: {exc}", file=sys.stderr)


def load(stem: str) -> list:
    """Read back every envelope of run `stem`, in call order. Returns [] if that run
    has no ledger. A line that cannot be parsed is reported on stderr and skipped
    rather than silently dropped."""
    target = path_for(stem)
    if not target.exists():
        return []

    envelopes = []
    with target.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                envelopes.append(json.loads(line))
            except ValueError as exc:
                print(f"[ledger] {target.name} line {number} is not JSON: {exc}", file=sys.stderr)
    return envelopes


def stop() -> None:
    """Close this thread's run. Later `record()` calls become no-ops again here, and no
    other thread's run is touched."""
    _active.set(_NO_RUN)


def active_stem() -> str | None:
    """The stem of the run currently being recorded in this thread, or None."""
    return _active.get()[1]


if __name__ == "__main__":
    demo = {
        "tool":         "_selftest",
        "args":         {"metabolite_synonyms": ["urate"], "disease_synonyms": ["gout"]},
        "source":       "EpiGraphDB MR-EVE",
        "url":          "https://api.epigraphdb.org/mr",
        "retrieved_at": "2026-09-10T00:00:00",
        "status":       "ok",
        "data":         {"n_estimates": 1},
        "caveats":      ["Retrieved, not computed here."],
    }

    record(demo)
    print("record() before start() wrote a file:", path_for("_selftest").exists())

    start("_selftest")
    record(demo)
    record({**demo, "status": "empty", "data": {"n_estimates": 0}})
    print("after start(), lines on disk:", len(load("_selftest")))
    print("active stem:", active_stem())

    stop()
    record({**demo, "status": "error"})
    print("after stop(), lines on disk (unchanged):", len(load("_selftest")))

    path_for("_selftest").unlink()
