"""Offline, source-bound Human-GEM context. No MR decisions or network calls.

The Workstream A wrapper owns team-ledger recording and tool registration. This
independent module returns the envelope without importing or changing that layer.
"""

import argparse
from copy import deepcopy
from functools import lru_cache
import json
import os
from pathlib import Path
from time import perf_counter

from .common import (MAX_INDEX_BYTES, SCHEMA_VERSION, SOURCE_URL, canonical_bytes,
                     normalise_chebi, sha256, strict_json, utc_now)

DEFAULT_INDEX = Path(__file__).resolve().parents[1] / "data/index/human-gem-2.0.0.json"
DEFAULT_CURRENCY_IDS = frozenset({"CHEBI:15422"})  # explicit ATP policy; not an exhaustive chemical list
CAVEATS = (
    "Biochemical context only (indirect, via enzyme); not MR, genetic effector nomination or demonstrated disease mediation.",
    "Reaction participation can include cofactors and co-substrates; it does not establish direct binding or a drug intervention direction.",
    "GPR AND/OR rules are authoritative for the recorded reaction; a complex member is not independently sufficient.",
    "Flux bounds describe the model, not measured in-vivo flux. No flux simulation was run.",
    "Candidate order is lexical for reproducibility, not a scientific score or target-priority ranking.",
)


@lru_cache(maxsize=2)
def _decode_index(raw):
    index = strict_json(raw)
    if index.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported Human-GEM index schema")
    for key in ("provenance", "metabolites", "reactions", "genes", "by_chebi", "by_name", "by_metabolite", "counts"):
        if not isinstance(index.get(key), dict):
            raise ValueError(f"Missing/invalid index field: {key}")
    if index["provenance"].get("dataset_kind") not in ("full_model", "source_fixture", "synthetic_fixture"):
        raise ValueError("Index dataset kind is missing or invalid")
    return index


def load_index(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError("Human-GEM index is missing; build it and set METABOCAUSAL_GEM_INDEX")
    if path.stat().st_size > MAX_INDEX_BYTES:
        raise ValueError("Index exceeds the size limit")
    with path.open("rb") as stream:
        raw = stream.read(MAX_INDEX_BYTES + 1)
    if len(raw) > MAX_INDEX_BYTES:
        raise ValueError("Index exceeds the size limit")
    manifest = strict_json(Path(str(path) + ".manifest.json").read_bytes())
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported index manifest schema")
    if sha256(raw) != manifest.get("index_sha256") or len(raw) != manifest.get("index_bytes"):
        raise ValueError("Index checksum/size mismatch; do not use this artifact")
    index = _decode_index(raw)
    if index["provenance"] != manifest.get("provenance") or index["counts"] != manifest.get("counts"):
        raise ValueError("Index and manifest disagree")
    return index, manifest


def _json_argument(value):
    try:
        canonical_bytes(value)
        return value
    except (TypeError, ValueError, OverflowError, RecursionError):
        return {"invalid_python_type": type(value).__name__}


def _participants(reaction, index):
    result = []
    for row in reaction["participants"]:
        metabolite = index["metabolites"][row["species_id"]]
        result.append({"species_id": row["species_id"], "coefficient": row["coefficient"],
                       "side": "reactant" if row["coefficient"] < 0 else "product",
                       "base_id": metabolite["base_id"], "name": metabolite["name"],
                       "compartment_id": metabolite["compartment_id"]})
    return result


def _role(reaction, matched_species, participants):
    """Conservative reaction-level context with its exact source/derivation basis."""
    if reaction["annotations"].get("rxnTCDBID"):
        return "transporter", "source reaction TCDB annotation"
    selected = [p for p in participants if p["species_id"] in matched_species]
    for left in selected:
        for right in selected:
            if (left["base_id"] and left["base_id"] == right["base_id"]
                    and left["side"] != right["side"]
                    and left["compartment_id"] != right["compartment_id"]):
                return "transporter", "inferred context: same annotated metabolite on opposite sides in distinct compartments"
    if reaction["ec_codes"] and reaction["gpr"]:
        return "enzyme", "source reaction EC annotation plus GPR; role applies to reaction context"
    return "unknown", "no explicit EC/TCDB or matched transport context; role not guessed"


class GemLookup:
    """Configurable local lookup; instantiate once for batch use.

    Limits cap returned detail only. Distinct reaction counts and candidate membership
    are computed from ALL matched reactions before any display cap is applied.
    """

    def __init__(self, index_path=None, *, hub_threshold=200, hub_policy="suppress",
                 currency_ids=DEFAULT_CURRENCY_IDS, max_reactions=200, max_candidates=100):
        self.index_path = Path(index_path if index_path is not None else
                               os.environ.get("METABOCAUSAL_GEM_INDEX", DEFAULT_INDEX))
        for name, value in (("hub_threshold", hub_threshold), ("max_reactions", max_reactions),
                            ("max_candidates", max_candidates)):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if max_reactions > 10000 or max_candidates > 10000:
            raise ValueError("Returned-record cap exceeds 10000")
        if hub_policy not in ("suppress", "include"):
            raise ValueError("hub_policy must be suppress or include")
        self.currency_ids = frozenset(normalise_chebi(value) for value in currency_ids)
        self.hub_threshold, self.hub_policy = hub_threshold, hub_policy
        self.max_reactions, self.max_candidates = max_reactions, max_candidates

    def _envelope(self, value, tool="map_metabolite_to_genes_gem", argument="chebi_id"):
        return {"tool": tool, "args": {argument: _json_argument(value)}, "source": "Human-GEM",
                "url": SOURCE_URL, "retrieved_at": utc_now(), "status": "error",
                "data": {"route": "via_enzyme", "evidence_type": "biochemical",
                         "mapping": {"status": "not_evaluated"}, "candidates": [], "reactions": [],
                         "network_calls": 0}, "caveats": list(CAVEATS)}

    def query(self, chebi_id):
        started = perf_counter()
        envelope = self._envelope(chebi_id)
        data = envelope["data"]
        try:
            chebi_id = normalise_chebi(chebi_id)
            data["query_chebi"] = chebi_id
            index, manifest = load_index(self.index_path)
            data["provenance"] = deepcopy(manifest)
            provenance = index["provenance"]
            data["model_version"] = provenance.get("version")
            data["dataset_kind"] = provenance["dataset_kind"]
            if index["counts"].get("species_with_invalid_chebi_annotations", 0):
                envelope["caveats"].append("The source contains malformed ChEBI annotations; raw values and diagnostics are retained in the index, but malformed IDs are not searchable.")
            if provenance.get("commit"):
                envelope["url"] = SOURCE_URL + "/blob/" + provenance["commit"] + "/model/Human-GEM.yml"
            if provenance["dataset_kind"] != "full_model":
                envelope["caveats"].append("Labelled fixture/subset, NOT a full-model run; counts and missing mappings describe only this fixture.")
            species_ids = index["by_chebi"].get(chebi_id, [])
            species = [index["metabolites"][sid] for sid in species_ids]
            bases = sorted({row["base_id"] or row["id"] for row in species})
            data["mapping"] = {"status": "mapped" if species else "unmapped", "method": "exact_source_chebi_annotation",
                               "base_ids": bases, "species": deepcopy(species), "ambiguous": len(bases) > 1}
            data["policy"] = {"hub_threshold": self.hub_threshold, "hub_policy": self.hub_policy,
                              "currency_ids": sorted(self.currency_ids), "max_reactions": self.max_reactions,
                              "max_candidates": self.max_candidates, "candidate_order": "symbol_then_ensembl_lexical"}
            if not species:
                envelope["status"] = "empty"
                envelope["caveats"].append("ChEBI annotation not found in this index; not evidence of no biology. No fuzzy or stereochemistry fallback was attempted.")
                return envelope
            if len(bases) > 1:
                data["mapping"]["status"] = "ambiguous"
                envelope["status"] = "empty"
                envelope["caveats"].append("One ChEBI annotation maps to multiple model identities; candidates withheld for explicit upstream resolution.")
                return envelope
            reaction_ids = sorted({rid for sid in species_ids for rid in index["by_metabolite"][sid]})
            hub_reasons = []
            if chebi_id in self.currency_ids:
                hub_reasons.append("explicit_currency_id")
            if len(reaction_ids) > self.hub_threshold:
                hub_reasons.append("distinct_reaction_degree_exceeds_threshold")
            suppressed = bool(hub_reasons) and self.hub_policy == "suppress"
            data.update(hub_metabolite=bool(hub_reasons), hub_reasons=hub_reasons,
                        policy_suppressed=suppressed, total_reactions=len(reaction_ids))
            candidates = {}
            selected_species = set(species_ids)
            reaction_details = []
            for rid in reaction_ids:
                reaction = index["reactions"][rid]
                participants = _participants(reaction, index)
                role, basis = _role(reaction, selected_species, participants)
                if not suppressed and len(reaction_details) < self.max_reactions:
                    detail = deepcopy(reaction)
                    detail["participants"] = participants
                    detail.update(role=role, role_basis=basis,
                                  matched_species_ids=sorted(selected_species & {p["species_id"] for p in reaction["participants"]}))
                    reaction_details.append(detail)
                for gene_id, complex_member in reaction["gene_members"].items():
                    if gene_id not in candidates:
                        candidates[gene_id] = {**deepcopy(index["genes"][gene_id]), "origin": "biochemical",
                                               "reaction_ids": [], "roles": [], "complex_member": False}
                    candidate = candidates[gene_id]
                    candidate["reaction_ids"].append(rid)
                    candidate["roles"].append(role)
                    candidate["complex_member"] |= complex_member
            all_candidates = sorted(candidates.values(), key=lambda row: (row["symbol"] is None, row["symbol"] or "", row["ensembl"]))
            for candidate in all_candidates:
                candidate["n_reactions"] = len(candidate["reaction_ids"])
                candidate["roles"] = sorted(set(candidate["roles"]))
                candidate["role"] = candidate["roles"][0] if len(candidate["roles"]) == 1 else "mixed"
                candidate["gpr_pointer"] = "reactions[reaction_id].gpr in the checksum-bound index; do not interpret this flattened candidate as a standalone enzyme"
            data.update(total_candidates=len(all_candidates), returned_candidates=0 if suppressed else min(len(all_candidates), self.max_candidates),
                        candidates=[] if suppressed else all_candidates[:self.max_candidates],
                        reactions=reaction_details, returned_reactions=len(reaction_details),
                        reactions_complete=len(reaction_details) == len(reaction_ids),
                        candidates_complete=not suppressed and len(all_candidates) <= self.max_candidates)
            if suppressed:
                envelope["caveats"].append("Hub/currency policy suppressed candidate and reaction detail; this is a deliberate scope limit, not absent reactions or genes.")
            elif not data["reactions_complete"] or not data["candidates_complete"]:
                envelope["caveats"].append("Returned detail is capped; full counts and GPR records remain in the identified local index. Counts are not confidence scores.")
            if any(row["symbol_status"] != "unique" for row in all_candidates):
                envelope["caveats"].append("Some gene symbols are missing/ambiguous/conflicting; retain Ensembl IDs and do not send these to symbol-only 1E tools.")
            if any(row["role"] == "unknown" for row in reaction_details):
                envelope["caveats"].append("Some reaction roles lack decisive annotations; unknown roles were not guessed.")
            envelope["status"] = "ok"
        except Exception as exc:
            # Local configuration/corruption/parse failures are not biological empty results.
            data["error"] = f"{type(exc).__name__}: {exc}"
            data["mapping"]["status"] = "error"
        finally:
            data["local_lookup_ms"] = (perf_counter() - started) * 1000
        return envelope

    def resolve_name(self, name):
        """Diagnostic exact-name lookup only. Never silently replaces ChEBI resolution."""
        envelope = self._envelope(name, "resolve_metabolite_name_gem", "name")
        try:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Name must be a nonempty string")
            index, manifest = load_index(self.index_path)
            species = [deepcopy(index["metabolites"][sid]) for sid in index["by_name"].get(name.strip().casefold(), [])]
            bases = sorted({row["base_id"] or row["id"] for row in species})
            ambiguous = len(bases) > 1
            envelope["data"].update(provenance=deepcopy(manifest), mapping={
                "status": "ambiguous" if ambiguous else "mapped" if species else "unmapped",
                "method": "exact_name_diagnostic_only", "species": species, "base_ids": bases,
                "ambiguous": ambiguous})
            envelope["status"] = "ok" if species and not ambiguous else "empty"
            envelope["caveats"].append("Name lookup offers source identities only; choose a verified ChEBI ID upstream before gene nomination.")
        except Exception as exc:
            envelope["data"]["error"] = f"{type(exc).__name__}: {exc}"
            envelope["data"]["mapping"]["status"] = "error"
        return envelope

    def map_many(self, chebi_ids):
        """One diagnostic per input, one lookup per distinct normalized valid identifier."""
        cache, records = {}, []
        for value in chebi_ids:
            try:
                key = normalise_chebi(value)
            except (ValueError, TypeError):
                key = None
            if key is not None and key in cache:
                envelope, reused = deepcopy(cache[key]), True
                envelope["args"] = {"chebi_id": _json_argument(value)}
            else:
                envelope, reused = self.query(value), False
                if key is not None:
                    cache[key] = deepcopy(envelope)
            records.append({"input": _json_argument(value), "reused": reused, "envelope": envelope})
        unique = list(cache.values())
        return {"input_count": len(records), "unique_valid_chebi_count": len(cache),
                "mapped": sum(e["data"]["mapping"]["status"] == "mapped" for e in unique),
                "unmapped": sum(e["data"]["mapping"]["status"] == "unmapped" for e in unique),
                "ambiguous": sum(e["data"]["mapping"]["status"] == "ambiguous" for e in unique),
                "errors": sum(e["status"] == "error" for e in unique) + sum(r["envelope"]["status"] == "error" and r["envelope"]["data"].get("query_chebi") is None for r in records),
                "records": records,
                "count_note": "Unique valid IDs are metabolite identifiers, not new MR pairs. Invalid-input errors are counted per input."}


def map_metabolite_to_genes_gem(chebi_id: str) -> dict:
    """Return checksum-bound Human-GEM biochemical context for an exact ChEBI ID.

    Set METABOCAUSAL_GEM_INDEX to a prepared index path. Does not record a team
    ledger itself: the integration wrapper records this returned envelope once.
    """
    try:
        return GemLookup().query(chebi_id)
    except Exception as exc:
        return {"tool": "map_metabolite_to_genes_gem", "args": {"chebi_id": _json_argument(chebi_id)},
                "source": "Human-GEM", "url": SOURCE_URL, "retrieved_at": utc_now(), "status": "error",
                "data": {"error": f"{type(exc).__name__}: {exc}"}, "caveats": list(CAVEATS)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chebi_id")
    parser.add_argument("--index", type=Path)
    parser.add_argument("--include-hubs", action="store_true")
    parser.add_argument("--ledger", type=Path, help="Append the one returned envelope; no network calls")
    args = parser.parse_args()
    envelope = GemLookup(args.index, hub_policy="include" if args.include_hubs else "suppress").query(args.chebi_id)
    if args.ledger:
        try:
            args.ledger.parent.mkdir(parents=True, exist_ok=True)
            with args.ledger.open("ab") as stream:
                stream.write(canonical_bytes(envelope))
                stream.flush()
                os.fsync(stream.fileno())
        except Exception as exc:
            envelope["data"].update(retrieval_status=envelope["status"], ledger_error=f"{type(exc).__name__}: {exc}")
            envelope["status"] = "error"
            envelope["caveats"].append("Ledger persistence failed; this envelope is not confirmed audited.")
    print(json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False))
    return 1 if envelope["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
