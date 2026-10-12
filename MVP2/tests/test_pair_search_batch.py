import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from search_pairs_europepmc import search_pair_batch, validate_pair


def test_batch_rejects_unverified_pair():
    ok, reason = validate_pair({"metabolite_name": "glycine", "disease_trait": "CAD"})
    assert not ok
    assert "not verified" in reason


def test_batch_keeps_each_pair_separate(tmp_path):
    rows = [
        {"metabolite_name": "glycine", "disease_trait": "CAD", "pair_relation_verified": "yes", "direction": "forward"},
        {"metabolite_name": "alanine", "disease_trait": "stroke", "pair_relation_verified": "yes", "direction": "forward"},
    ]

    def fake_search(question, metabolites, diseases, **kwargs):
        return {
            "status": "success",
            "papers": [{"identifiers": {"pmid": metabolites[0] + "-1"}, "title": question}],
            "rounds": [{"round": 1}],
            "search_history": [{"query": question, "returned_ids": [metabolites[0] + "-1"]}],
            "stop_reason": "test stop",
        }

    result = search_pair_batch(rows, tmp_path, max_rounds=1, max_requests_per_pair=1, search_fn=fake_search)
    assert result["selected_count"] == 2
    assert [x["status"] for x in result["index"]] == ["success", "success"]
    assert len(list((tmp_path / "pairs").glob("*.json"))) == 2
