"""Small, traceable client for the public Europe PMC search API."""

from __future__ import annotations

from collections.abc import Mapping
from time import monotonic, sleep
from typing import Any

import requests

API_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def _paper(result: Mapping[str, Any], query: str, round_number: int) -> dict[str, Any]:
    """Normalize the useful discovery fields without making scientific claims."""
    identifiers = {key: result.get(key) for key in ("id", "pmid", "pmcid", "doi") if result.get(key)}
    return {
        "identifiers": identifiers,
        "title": result.get("title"),
        "author_string": result.get("authorString"),
        "publication_year": result.get("pubYear"),
        "abstract": result.get("abstractText"),
        "abstract_available": bool(result.get("abstractText")),
        "source": result.get("source"),
        "full_text_urls": [item.get("url") for item in result.get("fullTextUrlList", {}).get("fullTextUrl", []) if item.get("url")],
        "source_urls": [url for url in [
            f"https://doi.org/{result.get('doi')}" if result.get("doi") else None,
            *[item.get("url") for item in result.get("fullTextUrlList", {}).get("fullTextUrl", []) if item.get("url")],
        ] if url],
        "identifier_verification": {"verified_from": "europe_pmc_search_response", "identifiers_present": list(identifiers)},
        "discovery_routes": [{"provider": "europe_pmc", "query": query, "round": round_number}],
    }


def _key(paper: Mapping[str, Any]) -> str:
    identifiers = paper["identifiers"]
    return (identifiers.get("doi") or identifiers.get("pmid") or identifiers.get("pmcid") or identifiers.get("id") or paper["title"] or "").lower()


def _identity_keys(paper: Mapping[str, Any]) -> set[str]:
    identifiers = paper.get("identifiers", {})
    return {f"{name}:{value.lower()}" for name, value in identifiers.items() if value}


def search_europe_pmc(
    query: str,
    *,
    page_size: int = 25,
    max_pages: int = 1,
    timeout: float = 30,
    round_number: int = 1,
    max_requests: int | None = None,
    max_seconds: float | None = None,
    max_retries: int = 2,
    session: Any | None = None,
    endpoint: str = API_URL,
) -> dict[str, Any]:
    """Search Europe PMC and return normalized papers plus an API ledger.

    Failures are represented in the returned result so callers can continue with
    partial coverage. ``session`` is injectable for deterministic tests.
    """
    if not query or page_size < 1 or max_pages < 1 or max_retries < 0 or (max_requests is not None and max_requests < 1) or (max_seconds is not None and max_seconds <= 0):
        raise ValueError("query and positive page/page, request, and time limits are required")
    http = session or requests.Session()
    papers: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    pages: list[dict[str, Any]] = []
    cursor = "*"
    status = "success"
    started = monotonic()
    requests_used = 0
    stop_reason = None
    for page in range(1, max_pages + 1):
        if max_requests is not None and requests_used >= max_requests:
            stop_reason = "configured request limit reached"
            status = "partial"
            break
        if max_seconds is not None and monotonic() - started >= max_seconds:
            stop_reason = "configured time limit reached"
            status = "partial"
            break
        params = {"query": query, "format": "json", "resultType": "core", "pageSize": page_size, "cursorMark": cursor}
        attempts = 0
        payload: Mapping[str, Any] | None = None
        while True:
            if max_requests is not None and requests_used >= max_requests:
                stop_reason = "configured request limit reached during retry"
                status = "partial"
                break
            if max_seconds is not None and monotonic() - started >= max_seconds:
                stop_reason = "configured time limit reached during retry"
                status = "partial"
                break
            try:
                attempts += 1
                requests_used += 1
                response = http.get(endpoint, params=params, timeout=timeout)
                response.raise_for_status()
                payload = response.json()
                break
            except Exception as exc:  # requests and malformed provider responses are partial results
                response_status = getattr(getattr(exc, "response", None), "status_code", None)
                retryable = response_status in {429, 500, 502, 503, 504} or isinstance(exc, (TimeoutError,)) or type(exc).__name__ in {"ReadTimeout", "ConnectTimeout", "ConnectionError"}
                if retryable and attempts <= max_retries:
                    sleep(min(2.0, 0.5 * (2 ** (attempts - 1))))
                    continue
                status = "partial" if papers else "failed"
                pages.append({"page": page, "params": params, "status": "error", "attempts": attempts, "error": f"{type(exc).__name__}: {exc}"})
                break
        if payload is None:
            if stop_reason is not None:
                pages.append({"page": page, "params": params, "status": "stopped", "attempts": attempts, "stop_reason": stop_reason})
            break
        results = payload.get("resultList", {}).get("result", [])
        if isinstance(results, Mapping):
            results = [results]
        for result in results:
            item = _paper(result, query, round_number)
            identity_keys = _identity_keys(item)
            key = next((aliases[identity] for identity in identity_keys if identity in aliases), _key(item))
            if key in papers:
                papers[key]["identifiers"] = {**item["identifiers"], **papers[key]["identifiers"]}
                papers[key]["source_urls"] = list(dict.fromkeys(papers[key].get("source_urls", []) + item.get("source_urls", [])))
                papers[key]["full_text_urls"] = list(dict.fromkeys(papers[key].get("full_text_urls", []) + item.get("full_text_urls", [])))
                papers[key]["discovery_routes"].extend(item["discovery_routes"])
            else:
                papers[key] = item
            for identity in identity_keys:
                aliases[identity] = key
        next_cursor = payload.get("nextCursorMark")
        pages.append({"page": page, "params": params, "status": "success", "hit_count": payload.get("hitCount"), "returned_ids": [r.get("id") for r in results if r.get("id")]})
        if not next_cursor or next_cursor == cursor or not results:
            break
        cursor = next_cursor
    if stop_reason is None and status == "success":
        stop_reason = "provider pagination completed or page limit reached"
    return {
        "papers": list(papers.values()),
        "search_history": [{"provider": "europe_pmc", "query": query, "round": round_number, "pages": pages, "requests_used": requests_used, "stop_reason": stop_reason, "status": status}],
        "status": status,
        "caveats": [] if status == "success" else ["Europe PMC returned partial or failed coverage; results are discovery candidates, not screened MR evidence."],
    }
