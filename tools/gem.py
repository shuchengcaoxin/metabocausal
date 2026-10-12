"""Team-ledger adapter for the offline Human-GEM biochemical-context module."""

import json

from MVP3.src.common import SOURCE_URL, utc_now
from MVP3.src.gem import CAVEATS, map_metabolite_to_genes_gem as _module_lookup

from ._evidence import finish


_KEYS = {"tool", "args", "source", "url", "retrieved_at", "status", "data", "caveats"}


def _error_envelope(chebi_id, detail):
    try:
        json.dumps(chebi_id, allow_nan=False)
        argument = chebi_id
    except (TypeError, ValueError, OverflowError, RecursionError):
        argument = {"invalid_python_type": type(chebi_id).__name__}
    return {
        "tool": "map_metabolite_to_genes_gem",
        "args": {"chebi_id": argument},
        "source": "Human-GEM",
        "url": SOURCE_URL,
        "retrieved_at": utc_now(),
        "status": "error",
        "data": {"error": detail, "route": "via_enzyme", "evidence_type": "biochemical"},
        "caveats": list(CAVEATS),
    }


def map_metabolite_to_genes_gem(chebi_id: str) -> dict:
    """Return pinned Human-GEM reaction/GPR context for one exact ChEBI identifier.

    This is biochemical context, not an MR result or effector-gene nomination.  The
    underlying lookup makes no network request.  Set ``METABOCAUSAL_GEM_INDEX`` to a
    checksum-bound index built by ``MVP3.src.build_index``.  The returned eight-key
    envelope is appended exactly once to the active team ledger.
    """
    try:
        envelope = _module_lookup(chebi_id)
        if not isinstance(envelope, dict) or set(envelope) != _KEYS:
            raise ValueError("Human-GEM module returned an invalid envelope shape")
        if envelope.get("tool") != "map_metabolite_to_genes_gem":
            raise ValueError("Human-GEM module returned the wrong tool name")
        if envelope.get("status") not in ("ok", "empty", "error"):
            raise ValueError("Human-GEM module returned an invalid status")
        if not isinstance(envelope.get("data"), dict) or not isinstance(envelope.get("caveats"), list):
            raise ValueError("Human-GEM module returned invalid data or caveats")
        json.dumps(envelope, ensure_ascii=False, allow_nan=False)
    except Exception as exc:
        envelope = _error_envelope(chebi_id, f"{type(exc).__name__}: {exc}")
    return finish(envelope)


__all__ = ["map_metabolite_to_genes_gem"]
