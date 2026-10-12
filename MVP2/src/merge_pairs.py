"""Build a non-destructive MVP1 + MVP2 candidate metabolite-disease union."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .pair_screening import canonical_pair_key, normalize, pair_keys


PROVENANCE_FIELDS = [
    "merged_row_number",
    "canonical_pair_key",
    "evidence_origin",
    "metabolite_name",
    "disease_trait",
    "literature_study_id",
    "source_path",
    "source_sheet",
    "source_row",
    "source_metabolite_id",
    "source_disease_id",
    "causal_direction",
    "pair_relation_verified",
    "pair_relation_basis",
    "source_record_type",
    # Carried through from the extractor so a reader of the merged table can see that a
    # row's interval was left empty because the source printed it on another scale, and
    # can still read the bounds that were retrieved. An absent value is stated here, not
    # silently dropped between the extraction and the merge.
    "ci_low_beta_scale",
    "ci_high_beta_scale",
    # The same rule for the other direction: where the merged row's ci_low/ci_upp differ
    # from what the source printed, because the source printed the two bounds in the
    # impossible order, the printed values travel with the row rather than being replaced
    # out of sight. Blank on every row whose bounds were shipped as they were read.
    "ci_low_as_printed",
    "ci_high_as_printed",
    "extraction_note",
]


def _is_forward(row: Mapping[str, Any]) -> bool:
    direction = normalize(row.get("direction", ""))
    return direction in {"", "forward", "metabolite disease", "metabolite outcome", "exposure outcome"}


def _require_verified_new_pairs(
    baseline_rows: list[Mapping[str, Any]], new_rows: list[Mapping[str, Any]]
) -> dict[str, int]:
    baseline_keys = {key for row in baseline_rows for key in pair_keys(row)}
    seen: set[str] = set()
    overlaps: list[str] = []
    duplicates: list[str] = []
    invalid: list[int] = []
    for index, row in enumerate(new_rows, 1):
        key = canonical_pair_key(row)
        verified = normalize(row.get("pair_relation_verified")) == "yes"
        if not key or not verified or not _is_forward(row):
            invalid.append(index)
            continue
        if pair_keys(row) & baseline_keys:
            overlaps.append(key)
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    if invalid:
        raise ValueError(f"new-pair input has {len(invalid)} unverified, unresolved, or non-forward row(s); first row: {invalid[0]}")
    if overlaps:
        raise ValueError(f"new-pair input overlaps the MVP1 baseline for {len(set(overlaps))} pair(s); first key: {overlaps[0]}")
    if duplicates:
        raise ValueError(f"new-pair input contains {len(set(duplicates))} duplicate canonical pair(s); first key: {duplicates[0]}")
    return {
        "baseline_key_count": len({canonical_pair_key(row) for row in baseline_rows if canonical_pair_key(row)}),
        "new_key_count": len(seen),
        "intersection_count": 0,
    }


def merge_pair_tables(
    baseline_rows: Iterable[Mapping[str, Any]],
    new_rows: Iterable[Mapping[str, Any]],
    baseline_fields: Iterable[str],
) -> dict[str, Any]:
    """Map verified new pairs to the MVP1 schema and append them.

    The heterogeneous ``metabolite_id`` values supplied by papers are retained
    as ``source_metabolite_id`` rather than being mislabeled as ChEBI IDs.
    """
    baseline_rows = [dict(row) for row in baseline_rows]
    new_rows = [dict(row) for row in new_rows]
    baseline_fields = list(baseline_fields)
    counts = _require_verified_new_pairs(baseline_rows, new_rows)
    fields = baseline_fields
    merged: list[dict[str, Any]] = []
    for source in baseline_rows:
        merged.append({field: source.get(field, "") for field in fields})
    provenance_rows: list[dict[str, Any]] = []
    for new_index, source in enumerate(new_rows, 1):
        row = {field: "" for field in fields}
        row.update({
            "metabolite_name": source.get("metabolite_name", ""),
            "disease_trait": source.get("disease_trait", ""),
            "b": source.get("beta", ""),
            "se": source.get("se", ""),
            "ci_low": source.get("ci_low", ""),
            "ci_upp": source.get("ci_high", ""),
            "pval": source.get("p_value", ""),
            "method": source.get("method", ""),
            "nsnp": source.get("nsnp", ""),
            "representative_rule": "One source-exact row retained for each canonical pair in new_unique_pairs.csv.",
            "supporting_mr_rows": source.get("supporting_source_rows", "1"),
            "source_detail_status": "source_row_verified",
            "record_type": "published_literature_mr_candidate",
        })
        merged.append(row)
        provenance_rows.append({
            "merged_row_number": len(baseline_rows) + new_index,
            "canonical_pair_key": canonical_pair_key(source),
            "evidence_origin": "mvp2_published_literature",
            "metabolite_name": source.get("metabolite_name", ""),
            "disease_trait": source.get("disease_trait", ""),
            "literature_study_id": source.get("study_id", ""),
            "source_path": source.get("source_path", ""),
            "source_sheet": source.get("source_sheet", ""),
            "source_row": source.get("source_row", ""),
            "source_metabolite_id": source.get("metabolite_id", ""),
            "source_disease_id": source.get("disease_id", ""),
            "causal_direction": source.get("direction", "forward"),
            "pair_relation_verified": source.get("pair_relation_verified", ""),
            "pair_relation_basis": source.get("pair_relation_basis", ""),
            "source_record_type": source.get("record_type", ""),
            "ci_low_beta_scale": source.get("ci_low_beta_scale", ""),
            "ci_high_beta_scale": source.get("ci_high_beta_scale", ""),
            "ci_low_as_printed": source.get("ci_low_as_printed", ""),
            "ci_high_as_printed": source.get("ci_high_as_printed", ""),
            "extraction_note": source.get("extraction_note", ""),
        })
    return {
        "fields": fields,
        "rows": merged,
        "provenance_fields": PROVENANCE_FIELDS,
        "provenance_rows": provenance_rows,
        "summary": {
            "baseline_row_count": len(baseline_rows),
            "new_row_count": len(new_rows),
            "merged_row_count": len(merged),
            "baseline_unique_pair_count": counts["baseline_key_count"],
            "new_unique_pair_count": counts["new_key_count"],
            "merged_unique_pair_count": counts["baseline_key_count"] + counts["new_key_count"],
            "baseline_new_intersection_count": counts["intersection_count"],
        },
    }
