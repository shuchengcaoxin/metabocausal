import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from src.merge_pairs import merge_pair_tables


BASELINE_FIELDS = ["metabolite_name", "metabolite_chebi", "disease_trait", "disease_id", "b", "se", "ci_low", "ci_upp", "pval", "method", "nsnp", "record_type"]


def test_merge_maps_new_pair_without_overwriting_baseline_schema():
    baseline = [{"metabolite_name": "glycine", "disease_trait": "stroke", "b": "0.1", "record_type": "metabolite_disease_evidence"}]
    new = [{
        "metabolite_name": "alanine", "metabolite_id": "source-1", "disease_trait": "CAD", "disease_id": "source-disease-1",
        "direction": "forward", "beta": "0.2", "se": "0.03", "ci_low": "0.1", "ci_high": "0.3", "p_value": "0.001",
        "method": "IVW", "nsnp": "5", "study_id": "paper-a", "source_path": "paper.xlsx", "source_sheet": "ST1", "source_row": "4",
        "pair_relation_verified": "yes", "pair_relation_basis": "same source row", "record_type": "paper_screening_candidate",
    }]
    result = merge_pair_tables(baseline, new, BASELINE_FIELDS)
    assert result["summary"]["merged_row_count"] == 2
    appended = result["rows"][1]
    assert appended["b"] == "0.2"
    assert appended["ci_upp"] == "0.3"
    assert appended["metabolite_chebi"] == ""
    assert appended["disease_id"] == ""
    assert result["fields"] == BASELINE_FIELDS
    provenance = result["provenance_rows"][0]
    assert provenance["source_metabolite_id"] == "source-1"
    assert provenance["source_disease_id"] == "source-disease-1"
    assert provenance["evidence_origin"] == "mvp2_published_literature"
    assert provenance["merged_row_number"] == 2


def test_merge_rejects_baseline_overlap():
    baseline = [{"metabolite_name": "glycine", "disease_trait": "CAD"}]
    new = [{"metabolite_name": "Glycine", "disease_trait": "cad", "direction": "forward", "pair_relation_verified": "yes"}]
    with pytest.raises(ValueError, match="overlaps"):
        merge_pair_tables(baseline, new, BASELINE_FIELDS)


def test_merge_rejects_unverified_pair():
    new = [{"metabolite_name": "alanine", "disease_trait": "CAD", "direction": "forward", "pair_relation_verified": "no"}]
    with pytest.raises(ValueError, match="unverified"):
        merge_pair_tables([], new, BASELINE_FIELDS)
