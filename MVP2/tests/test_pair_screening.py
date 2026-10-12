import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from src.pair_screening import pair_keys, screen_pairs


def test_pair_keys_prefer_ids_but_keep_name_key():
    keys = pair_keys({"metabolite_chebi": "CHEBI:1", "metabolite_name": "Glycine", "disease_id": "MONDO:1", "disease_trait": "CAD"})
    assert "id|chebi 1|mondo 1" in keys
    assert "name|glycine|cad" in keys


def test_screening_keeps_only_new_forward_pairs():
    baseline = [{"metabolite_name": "Glycine", "disease_trait": "Coronary artery disease"}]
    candidates = [
        {"metabolite_name": "glycine", "disease_trait": "coronary artery disease", "direction": "forward"},
        {"metabolite_name": "alanine", "disease_trait": "coronary artery disease", "direction": "forward", "source": "paper-a"},
        {"metabolite_name": "glycine", "disease_trait": "stroke", "direction": "reverse"},
        {"metabolite_name": "alanine", "direction": "forward"},
    ]
    result = screen_pairs(baseline, candidates)
    assert result["summary"] == {
        "baseline_pair_key_count": 1,
        "candidate_row_count": 4,
        "new_pair_record_count": 1,
        "new_pair_key_count": 1,
        "already_present_count": 1,
        "excluded_direction_count": 1,
        "unresolved_identity_count": 1,
    }
    assert result["new_pair_records"][0]["source"] == "paper-a"
    assert len(result["new_unique_pairs"]) == 1
