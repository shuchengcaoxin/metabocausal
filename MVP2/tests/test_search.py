import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from src.europepmc import search_europe_pmc
from src.search import build_query, inspect_results, search_literature


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        return next(self.responses)


def test_europe_pmc_normalizes_and_deduplicates_pages():
    session = Session([
        Response({"hitCount": 2, "nextCursorMark": "next", "resultList": {"result": [{"id": "1", "pmid": "1", "doi": "10/x", "title": "A", "abstractText": "abstract"}]}}),
        Response({"hitCount": 2, "resultList": {"result": [{"id": "1", "pmid": "1", "doi": "10/x", "title": "A"}]}}),
    ])
    result = search_europe_pmc("glycine AND coronary", max_pages=2, session=session)
    assert len(result["papers"]) == 1
    assert len(result["papers"][0]["discovery_routes"]) == 2
    assert len(result["search_history"][0]["pages"]) == 2


def test_europe_pmc_merges_identifier_views_of_one_paper():
    session = Session([
        Response({"resultList": {"result": [
            {"id": "1", "pmid": "1", "doi": "10/x", "title": "A"},
            {"id": "PMC1", "pmcid": "PMC1", "doi": "10/x", "title": "A"},
        ]}}),
    ])
    result = search_europe_pmc("glycine", session=session)
    assert len(result["papers"]) == 1
    assert result["papers"][0]["identifiers"] == {"id": "1", "pmid": "1", "doi": "10/x", "pmcid": "PMC1"}


def test_europe_pmc_returns_explicit_failure():
    class Broken:
        def get(self, *args, **kwargs):
            raise TimeoutError("offline")

    result = search_europe_pmc("glycine", session=Broken(), max_retries=0)
    assert result["status"] == "failed"
    assert result["search_history"][0]["pages"][0]["status"] == "error"


def test_europe_pmc_honours_request_limit():
    session = Session([Response({"nextCursorMark": "next", "resultList": {"result": [{"id": "1", "title": "A"}]}})])
    result = search_europe_pmc("glycine", max_pages=3, max_requests=1, session=session)
    assert len(session.calls) == 1
    assert result["search_history"][0]["requests_used"] == 1
    assert result["search_history"][0]["stop_reason"] == "configured request limit reached"


def test_europe_pmc_retries_transient_provider_error(monkeypatch):
    class Transient(Exception):
        response = type("Response", (), {"status_code": 503})()

        def __str__(self):
            return "temporary outage"

    class Flaky:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise Transient()
            return Response({"resultList": {"result": [{"id": "1", "title": "A"}]}})

    monkeypatch.setattr("src.europepmc.sleep", lambda _: None)
    session = Flaky()
    result = search_europe_pmc("glycine", session=session, max_retries=1)
    assert session.calls == 2
    assert result["status"] == "success"


def test_query_kinds_are_distinct():
    broad = build_query(["glycine"], ["coronary artery disease"], search_kind="metabolome_wide")
    pair = build_query(["glycine"], ["coronary artery disease"], search_kind="pair_specific")
    challenge = build_query(["glycine"], ["coronary artery disease"], search_kind="challenge")
    assert "metabolome-wide" in broad
    assert '"glycine"' in pair and '"coronary artery disease"' in pair
    assert "reverse" in challenge and "null" in challenge


def test_inspection_creates_gap_for_pair_and_sources():
    result = inspect_results([{"title": "Metabolome-wide MR", "abstract_available": True, "full_text_urls": []}], metabolites=["glycine"], diseases=["coronary artery disease"])
    assert "pair-specific metabolite/disease coverage is not yet confirmed" in result["remaining_gaps"]
    assert "full text or supplement availability is not yet confirmed" in result["remaining_gaps"]


def test_orchestrator_inspects_and_chooses_gap_driven_follow_up():
    calls = []

    def fake(query, **kwargs):
        calls.append((query, kwargs))
        return {"papers": [{"identifiers": {"pmid": "1"}, "title": "Metabolome-wide MR", "discovery_routes": [{"provider": "europe_pmc"}]}], "search_history": [{"query": query, "pages": [{"returned_ids": ["1"]}]}], "status": "success"}

    result = search_literature("Does glycine affect CAD?", ["glycine"], ["coronary artery disease"], max_rounds=2, search_fn=fake)
    assert len(calls) == 2
    assert len(result["papers"]) == 1
    assert len(result["search_history"]) == 2
    assert "pair-specific" in result["search_history"][1]["goal"]
    assert result["stop_reason"] == "configured maximum round limit reached"
    assert result["rounds"][0]["inspection"]["remaining_gaps"]
    assert result["search_history"][0]["returned_ids"] == ["1"]
    assert "pair-specific" in result["search_history"][0]["next_action"]
