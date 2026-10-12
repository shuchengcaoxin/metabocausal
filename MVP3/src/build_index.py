"""Build a deterministic JSON lookup from pinned Human-GEM YAML and TSV annotations.

PyYAML is needed only for preparation. Lookup and offline fixture tests use stdlib.
No flux simulation, isotope/stereochemistry merging or causal ranking is performed.
"""

import argparse
import csv
import json
import math
from pathlib import Path
import re

from .common import (SCHEMA_VERSION, asset_url, canonical_bytes, normalise_chebi,
                     sha256, strict_json, unique_dict, utc_now, verify_sources, write_new)
from .gpr import gene_members, parse_gpr


def as_mapping(value):
    # PyYAML's safe !!omap constructor returns [(key, value), ...]. Do not cast
    # blindly with dict(): that would silently hide duplicate source keys.
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return unique_dict(value)
    raise ValueError("Expected a YAML mapping or ordered mapping")


def tsv_records(path, key, required):
    result = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or not set(required).issubset(fields):
            raise ValueError(f"Unexpected TSV header: {Path(path).name}")
        for row_number, row in enumerate(reader, 2):
            if None in row:
                raise ValueError(f"Extra TSV columns in {Path(path).name} record {row_number}")
            identifier = row[key]
            if not identifier or identifier in result:
                raise ValueError(f"Duplicate/empty TSV ID: {identifier}")
            # The pinned source omits trailing annotation columns in some rows.
            # Retain None and its diagnostic; do not invent an annotation or drop the row.
            result[identifier] = {"values": row, "record_number": row_number,
                                  "line_end": reader.line_num,
                                  "omitted_columns": [key for key, value in row.items() if value is None]}
    return result


def read_sources(directory):
    """All source bytes must match the checked-in lock before parsing anything."""
    directory = Path(directory)
    lock = verify_sources(directory)
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("Building the full model requires PyYAML; offline lookup does not") from exc
    raw = (directory / "Human-GEM.yml").read_text(encoding="utf-8")
    model = as_mapping(yaml.load(raw, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)))
    if str(model["metaData"]["version"]) != lock["version"]:
        raise ValueError("YAML model version does not match the source lock")
    lines = {}
    for line_number, line in enumerate(raw.splitlines(), 1):
        match = re.fullmatch(r'\s*- id: "([^"]+)"', line)
        if match:
            if match[1] in lines:
                raise ValueError("Duplicate YAML entity ID")
            lines[match[1]] = line_number
    model["source_lines"] = lines
    annotations = {
        "metabolites": tsv_records(directory / "metabolites.tsv", "mets", ("mets", "metsNoComp", "metChEBIID")),
        "genes": tsv_records(directory / "genes.tsv", "genes", ("genes", "geneSymbols")),
        "reactions": tsv_records(directory / "reactions.tsv", "rxns", ("rxns",)),
    }
    provenance = {
        "dataset_kind": "full_model", "source": "Human-GEM", "version": lock["version"],
        "commit": lock["commit"], "tag": lock["tag"], "license": lock["license"],
        "license_url": lock["license_url"],
        "citation_note": "See the pinned README.md: Human2 (Luo et al., 2026, in press there) and Human1 (Robinson et al., 2020).",
        "sources": {name: {**info, "url": asset_url(lock, name)} for name, info in lock["files"].items()},
        "annotation_diagnostics": {name: {"records": len(rows),
                                          "records_with_omitted_trailing_columns": sum(bool(row["omitted_columns"]) for row in rows.values())}
                                   for name, rows in annotations.items()},
    }
    return model, annotations, provenance


def split_annotations(text):
    return sorted({part.strip() for part in re.split(r"[;|]", text or "") if part.strip()})


def _records(rows):
    result = {}
    for row in rows:
        row = as_mapping(row)
        identifier = row["id"]
        if not isinstance(identifier, str) or not identifier or identifier in result:
            raise ValueError("Duplicate/invalid model ID")
        result[identifier] = row
    return result


def _finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Model coefficient/bound must be finite and numeric")
    return value


def build_index_data(model, annotations, provenance):
    """Pure normalization seam for labelled source excerpts and synthetic fixtures."""
    if provenance.get("dataset_kind") not in ("full_model", "source_fixture", "synthetic_fixture"):
        raise ValueError("Dataset kind must be explicit")
    compartments = as_mapping(model["compartments"])
    metabolites, reactions, genes = {}, {}, {}
    by_chebi, by_name, by_metabolite = {}, {}, {}
    source_lines = model.get("source_lines", {})

    def location(section, identifier, annotation):
        return {"model_asset": "Human-GEM.yml", "section": section, "id": identifier,
                "model_line": source_lines.get(identifier), "annotation_asset": section + ".tsv",
                "annotation_record": annotation.get("record_number"),
                "annotation_line_end": annotation.get("line_end"),
                "omitted_annotation_columns": annotation.get("omitted_columns", [])}

    for identifier, row in _records(model["metabolites"]).items():
        annotation = annotations["metabolites"].get(identifier, {})
        values = annotation.get("values", {})
        compartment = row["compartment"]
        if compartment not in compartments:
            raise ValueError(f"Unknown compartment for {identifier}")
        chebi, invalid_chebi = [], []
        for token in split_annotations(values.get("metChEBIID", "")):
            try:
                chebi.append(normalise_chebi(token if not token.isdigit() else "CHEBI:" + token))
            except ValueError:
                # A malformed optional annotation cannot become a fabricated ID.
                # Keep it visible, but do not discard the source reaction graph.
                invalid_chebi.append(token)
        # Identity is explicit TSV annotation. Never trim a last character or infer
        # that two names/stereoisomers/protonation states are interchangeable.
        base_id = values.get("metsNoComp") or None
        metabolites[identifier] = {
            "id": identifier, "name": row.get("name"), "base_id": base_id,
            "compartment_id": compartment, "compartment": compartments[compartment],
            "formula": row.get("formula"), "charge": row.get("charge"),
            "chebi_ids": sorted(set(chebi)), "invalid_chebi_annotations": invalid_chebi, "annotations": values,
            "source_location": location("metabolites", identifier, annotation),
        }
        for chebi_id in set(chebi):
            by_chebi.setdefault(chebi_id, []).append(identifier)
        if row.get("name"):
            by_name.setdefault(row["name"].strip().casefold(), []).append(identifier)
        by_metabolite[identifier] = []

    for identifier, row in _records(model["genes"]).items():
        annotation = annotations["genes"].get(identifier, {})
        values = annotation.get("values", {})
        symbols = split_annotations(values.get("geneSymbols", ""))
        model_name = row.get("name")
        status = "missing" if not symbols else "unique" if len(symbols) == 1 else "ambiguous"
        if status == "unique" and model_name and model_name != symbols[0]:
            status = "conflicting_source_labels"
        genes[identifier] = {
            "ensembl": identifier, "symbol": symbols[0] if status == "unique" else None,
            "symbols": symbols, "symbol_status": status, "model_gene_name": model_name,
            "annotations": values, "source_location": location("genes", identifier, annotation),
        }

    for identifier, row in _records(model["reactions"]).items():
        annotation = annotations["reactions"].get(identifier, {})
        coefficients = as_mapping(row["metabolites"])
        if not coefficients:
            raise ValueError(f"Reaction {identifier} has no participants")
        participants = []
        for species_id, value in sorted(coefficients.items()):
            coefficient = _finite(value)
            if coefficient == 0 or species_id not in metabolites:
                raise ValueError(f"Zero coefficient or unknown species in {identifier}")
            # Store identity once in metabolites, not once per reaction occurrence.
            # The public lookup joins these exact fields for the returned reactions.
            participants.append({"species_id": species_id, "coefficient": coefficient})
            by_metabolite[species_id].append(identifier)
        lower, upper = row.get("lower_bound"), row.get("upper_bound")
        if lower is not None:
            _finite(lower)
        if upper is not None:
            _finite(upper)
        if lower is not None and upper is not None and lower > upper:
            raise ValueError(f"Inverted flux bounds in {identifier}")
        direction, reversible = "unknown", None
        if lower is not None and upper is not None:
            reversible = lower < 0 < upper
            direction = "reversible" if reversible else "forward" if upper > 0 else "reverse" if lower < 0 else "blocked"
        raw_rule = row.get("gene_reaction_rule", "")
        tree = parse_gpr(raw_rule)
        members = gene_members(tree)
        if set(members) - set(genes):
            raise ValueError(f"Unknown gene in GPR of {identifier}: {sorted(set(members) - set(genes))}")
        values = annotation.get("values", {})
        reactions[identifier] = {
            "id": identifier, "name": row.get("name"), "participants": participants,
            "lower_bound": lower, "upper_bound": upper, "direction": direction, "reversible": reversible,
            "gpr_raw": raw_rule, "gpr": tree, "gene_members": members,
            "subsystem": row.get("subsystem"), "ec_codes": row.get("eccodes"),
            "references": row.get("references"), "annotations": values,
            "source_location": location("reactions", identifier, annotation),
        }
    for lookup in (by_chebi, by_name, by_metabolite):
        for key in lookup:
            lookup[key] = sorted(set(lookup[key]))
    return {"schema_version": SCHEMA_VERSION, "provenance": provenance,
            "model_metadata": model.get("metaData", {}), "compartments": compartments,
            "metabolites": metabolites, "genes": genes, "reactions": reactions,
            "by_chebi": by_chebi, "by_name": by_name, "by_metabolite": by_metabolite,
            "counts": {"metabolite_species": len(metabolites), "reactions": len(reactions),
                       "genes": len(genes), "chebi_ids": len(by_chebi),
                       "species_with_invalid_chebi_annotations": sum(bool(row["invalid_chebi_annotations"]) for row in metabolites.values()),
                       "genes_without_unique_symbol": sum(row["symbol_status"] != "unique" for row in genes.values())}}


def write_index(index, output):
    output = Path(output)
    manifest_path = Path(str(output) + ".manifest.json")
    if output.exists() or manifest_path.exists():
        raise FileExistsError("Index/manifest already exists; choose a new versioned output path")
    raw = canonical_bytes(index)
    code_hashes = {name: sha256((Path(__file__).parent / name).read_bytes())
                   for name in ("build_index.py", "gpr.py", "common.py")}
    manifest = {"schema_version": SCHEMA_VERSION, "index_sha256": sha256(raw), "index_bytes": len(raw),
                "provenance": index["provenance"], "counts": index["counts"],
                "builder_code_sha256": code_hashes, "built_at": utc_now()}
    # Exclusive writes: interruption can leave an unusable incomplete pair, but the
    # loader refuses it and no earlier valid index is ever overwritten.
    write_new(output, raw)
    write_new(manifest_path, canonical_bytes(manifest))
    return manifest


def build_full_model(source_dir, output):
    return write_index(build_index_data(*read_sources(source_dir)), output)


def build_fixture(fixture_path, output):
    fixture_path = Path(fixture_path)
    raw = fixture_path.read_bytes()
    fixture = strict_json(raw)
    provenance = {**fixture["provenance"], "fixture_sha256": sha256(raw)}
    if provenance["dataset_kind"] not in ("source_fixture", "synthetic_fixture"):
        raise ValueError("Fixture cannot be labelled as a full model")
    return write_index(build_index_data(fixture["model"], fixture["annotations"], provenance), output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--source-dir", type=Path)
    sources.add_argument("--fixture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_full_model(args.source_dir, args.output) if args.source_dir else build_fixture(args.fixture, args.output)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
