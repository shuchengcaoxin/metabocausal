"""A / B / C evidence state: one pure function over the tool envelopes of one run.

The state is decided here, in code, never by the model. `agent.py` hands over the
envelopes the run produced (None for a tool that never ran); `render.py` puts
`reason` into section 2 of the card and `failed_tools` into section 8.

    A  retrieved MR    >= 1 retrieved estimate carrying a numeric effect size, a
                       numeric uncertainty and a numeric p-value (EpiGraphDB
                       MR-EVE b/se/pval, or a literature paper's value/ci/p).
                       Retrieved from a published or pre-computed source.
    B  analysis-ready  not A, but >= 1 exposure dataset with >= 3 genome-wide
                       significant hits AND >= 1 outcome dataset.
    C  evidence gap    everything else.

C is a statement about what could be retrieved, never about biology. An `empty`
or `error` envelope means the trait may simply be absent from the snapshot, so
every C reason ends by saying so.

ENVELOPE SHAPES READ HERE. All four are the shared 8-key envelope; only `tool`,
`status` and `data` are read, and an envelope whose status is not ok/empty is
treated as absent. THE 1C AUTHOR WRITES TO THE instr_env / outcome_env SHAPES:

    mr_env       1B    tools/epigraphdb.get_mr_result
        data["estimates"] = [{"exposure_id", "exposure_trait", "outcome_id",
                              "outcome_trait", "b", "se", "pval", "method", ...}, ...]

    lit_env      MVP2  tools/litmr.get_literature_mr
        data["supporting"] / data["opposing"] =
            [{..., "estimate": {"type", "value", "ci": [lo, hi], "p"}}, ...]
        data["estimates"] is read too, in case that tool ever normalises to the
        1B shape. A paper with "estimate": None is counted as no estimate.

    instr_env    1C    tools/opengwas.get_mqtl_instruments
        data["exposures"] = [{"id", "trait", "platform", "n", "population",
                              "build", "gws_hits": int, "weak_instruments": int}, ...]
        Only "exposures" and the numeric "gws_hits" on each entry are read.

    outcome_env  1C    tools/opengwas.find_outcome_datasets
        data["datasets"]  = [{"id", "trait", "n", "population", ...}, ...]
        Only whether "datasets" is non-empty is read.

Pure: no I/O, no network, no clock, no randomness, and the arguments are never
mutated. The same envelopes always give the same dict back.
"""

from __future__ import annotations

import math

GWS_HITS_MIN = 3

SLOT_LABELS = {
    "mr_env":      "retrieved MR",
    "lit_env":     "literature MR",
    "instr_env":   "instrument search",
    "outcome_env": "outcome dataset search",
}

ESTIMATE_KEYS = ("estimates", "supporting", "opposing")
EFFECT_FIELDS = ("b", "beta", "value")
UNCERTAINTY_FIELDS = ("se", "std_error", "standard_error")
PVALUE_FIELDS = ("pval", "p", "p_value", "pvalue")

_COMPLETE = "a numeric effect size, uncertainty and p-value"
_NOT_NO_EFFECT = (
    "An empty or failed result is a gap in what could be retrieved, "
    "not evidence of no effect."
)


def _numeric(value) -> bool:
    # ledger.record serialises with default=str, so a numpy float can come back from a
    # ledger as the string "1.3665". A numeric string is still a number.
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, str):
        try:
            return math.isfinite(float(value))
        except ValueError:
            return False
    return False


def _as_float(value):
    return float(value) if _numeric(value) else None


def _tidy(value) -> str:
    number = _as_float(value)
    if number is None:
        return str(value)
    return str(int(number)) if number.is_integer() else str(number)


def _numeric_interval(value) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(_numeric(bound) for bound in value)
    )


def _fields(record) -> dict:
    if not isinstance(record, dict):
        return {}
    nested = record.get("estimate")
    if isinstance(nested, dict):
        return {**record, **nested}
    return record


def _is_complete_estimate(record) -> bool:
    fields = _fields(record)
    if not fields:
        return False
    has_effect = any(_numeric(fields.get(name)) for name in EFFECT_FIELDS)
    has_spread = (
        any(_numeric(fields.get(name)) for name in UNCERTAINTY_FIELDS)
        or _numeric_interval(fields.get("ci"))
    )
    has_pval = any(_numeric(fields.get(name)) for name in PVALUE_FIELDS)
    return has_effect and has_spread and has_pval


def _entries(env, key) -> list:
    data = env.get("data") if isinstance(env, dict) else None
    if not isinstance(data, dict):
        return []
    block = data.get(key)
    return list(block) if isinstance(block, list) else []


def _estimate_records(env) -> list:
    records = []
    for key in ESTIMATE_KEYS:
        records.extend(_entries(env, key))
    return records


def _gws_hits(entry):
    return _as_float(entry.get("gws_hits")) if isinstance(entry, dict) else None


def _tool_name(env):
    if isinstance(env, dict):
        name = env.get("tool")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _slot_state(env) -> str:
    """absent / malformed / error / empty / ok. Only ok and empty may be read."""
    if env is None:
        return "absent"
    if not isinstance(env, dict):
        return "malformed"
    if env.get("status") == "error":
        return "error"
    if env.get("status") not in ("ok", "empty") or not isinstance(env.get("data"), dict):
        return "malformed"
    return env["status"]


def _label(key, env) -> str:
    name = _tool_name(env)
    return f"{SLOT_LABELS[key]} ({name})" if name else SLOT_LABELS[key]


def _unavailable_clause(
    key,
    env,
    state,
):
    label = _label(key, env)
    if state == "absent":
        return f"{label} not run"
    if state == "error":
        return f"{label} returned an error envelope"
    if state == "malformed":
        return f"{label} returned a malformed envelope"
    return None


def _estimate_clause(
    key,
    env,
    state,
    n_records,
) -> str:
    clause = _unavailable_clause(
        key,
        env,
        state,
    )
    if clause:
        return clause
    label = _label(key, env)
    if state == "empty" or not n_records:
        return f"{label} returned no estimate"
    return f"{label} returned {n_records} row(s), none with {_COMPLETE}"


def _instrument_clause(
    env,
    state,
    hits,
) -> str:
    clause = _unavailable_clause(
        "instr_env",
        env,
        state,
    )
    if clause:
        return clause
    label = _label("instr_env", env)
    if not hits:
        return f"{label} found no exposure dataset with a hit count"
    return (
        f"{label} found no exposure dataset reaching {GWS_HITS_MIN} genome-wide "
        f"significant hits (best {_tidy(max(hits))})"
    )


def _outcome_clause(
    env,
    state,
    outcomes,
) -> str:
    clause = _unavailable_clause(
        "outcome_env",
        env,
        state,
    )
    if clause:
        return clause
    label = _label("outcome_env", env)
    if not outcomes:
        return f"{label} found no outcome dataset"
    return f"{label} found {len(outcomes)} outcome dataset(s)"


def classify_state(
    mr_env:      dict | None = None,
    lit_env:     dict | None = None,
    instr_env:   dict | None = None,
    outcome_env: dict | None = None,
) -> dict:
    """Decide the A/B/C evidence state of one run from its tool envelopes.

    Pass the envelope each tool returned, or None for a tool that never ran; an
    `error` envelope counts as absent evidence and is named in `failed_tools`.
    Returns {"state", "reason", "ledger_keys", "failed_tools"}: `ledger_keys` are
    the tool names of every envelope handed in (the ledger lines needed to
    re-check this verdict), `failed_tools` the subset that could not be read.
    """
    slots = (
        ("mr_env",      mr_env),
        ("lit_env",     lit_env),
        ("instr_env",   instr_env),
        ("outcome_env", outcome_env),
    )

    ledger_keys = []
    failed_tools = []
    states = {}
    for key, env in slots:
        state = _slot_state(env)
        states[key] = state
        name = _tool_name(env)
        if name and name not in ledger_keys:
            ledger_keys.append(name)
        if state in ("error", "malformed") and name and name not in failed_tools:
            failed_tools.append(name)

    readable = {key: env for key, env in slots if states[key] in ("ok", "empty")}

    mr_records = _estimate_records(readable.get("mr_env"))
    lit_records = _estimate_records(readable.get("lit_env"))
    mr_complete = sum(1 for record in mr_records if _is_complete_estimate(record))
    lit_complete = sum(1 for record in lit_records if _is_complete_estimate(record))

    if mr_complete or lit_complete:
        found = []
        if mr_complete:
            found.append(f"{_label('mr_env', mr_env)}: {mr_complete}")
        if lit_complete:
            found.append(f"{_label('lit_env', lit_env)}: {lit_complete}")
        reason = (
            f"State A (retrieved MR): {mr_complete + lit_complete} estimate(s) carry "
            f"{_COMPLETE} ({'; '.join(found)}). Retrieved from a published or "
            "pre-computed source, not computed here."
        )
        return {
            "state":        "A",
            "reason":       reason,
            "ledger_keys":  ledger_keys,
            "failed_tools": failed_tools,
        }

    no_a = "; ".join([
        _estimate_clause(
            "mr_env",
            mr_env,
            states["mr_env"],
            len(mr_records),
        ),
        _estimate_clause(
            "lit_env",
            lit_env,
            states["lit_env"],
            len(lit_records),
        ),
    ])

    exposures = _entries(readable.get("instr_env"), "exposures")
    hits = [count for count in map(_gws_hits, exposures) if count is not None]
    strong = [count for count in hits if count >= GWS_HITS_MIN]
    outcomes = _entries(readable.get("outcome_env"), "datasets")

    if strong and outcomes:
        reason = (
            f"State B (analysis-ready): no retrieved MR estimate ({no_a}), but "
            f"{len(strong)} exposure dataset(s) reach {GWS_HITS_MIN} or more genome-wide "
            f"significant hits (best {_tidy(max(strong))}) and {len(outcomes)} outcome "
            "dataset(s) are available, so this pair could be analysed."
        )
        return {
            "state":        "B",
            "reason":       reason,
            "ledger_keys":  ledger_keys,
            "failed_tools": failed_tools,
        }

    not_ready = "; ".join([
        _instrument_clause(
            instr_env,
            states["instr_env"],
            hits,
        ),
        _outcome_clause(
            outcome_env,
            states["outcome_env"],
            outcomes,
        ),
    ])
    reason = (
        f"State C (evidence gap): no retrieved MR estimate ({no_a}) and the pair is "
        f"not shown to be analysis-ready ({not_ready})."
    )
    if all(state == "absent" for state in states.values()):
        reason += " No tool result reached the classifier."
    if failed_tools:
        reason += f" Failed tools: {', '.join(failed_tools)}."
    reason += f" {_NOT_NO_EFFECT}"

    return {
        "state":        "C",
        "reason":       reason,
        "ledger_keys":  ledger_keys,
        "failed_tools": failed_tools,
    }


if __name__ == "__main__":
    import json

    def _demo(title, **envelopes):
        print(title)
        print(json.dumps(
            classify_state(**envelopes),
            indent       = 2,
            ensure_ascii = False,
        ))
        print()

    _demo(
        "A - one retrieved EpiGraphDB estimate (Urate -> Gout):",
        mr_env = {
            "tool":         "get_mr_result",
            "args":         {},
            "source":       "EpiGraphDB MR-EVE",
            "url":          "https://api.epigraphdb.org/mr",
            "retrieved_at": "2026-09-10T00:00:00",
            "status":       "ok",
            "data":         {"estimates": [{"b": 1.3665, "se": 0.1068, "pval": 1.79e-37}]},
            "caveats":      [],
        },
    )

    _demo(
        "B - no MR, but instruments and an outcome dataset:",
        instr_env   = {
            "tool":   "get_mqtl_instruments",
            "status": "ok",
            "data":   {"exposures": [{"id": "met-a-468", "gws_hits": 4}]},
        },
        outcome_env = {
            "tool":   "find_outcome_datasets",
            "status": "ok",
            "data":   {"datasets": [{"id": "ieu-a-7"}]},
        },
    )

    _demo("C - nothing ran:")
