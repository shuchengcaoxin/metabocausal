"""Bounded agent-guided literature search orchestration using Europe PMC only.

The provider adapter retrieves papers. This module inspects those papers and
chooses the next bounded search, so a run is a search loop rather than a fixed
list of queries.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import re
from time import monotonic
from typing import Any

from .europepmc import search_europe_pmc

MR_TERMS = '"Mendelian randomization" OR "Mendelian randomisation" OR MR'


def _values(values: Iterable[str] | None) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in (values or []) if v and v.strip()))


def _terms(values: Iterable[str] | None) -> str:
    """Quote labels and add only safe punctuation-stripped label variants."""
    expanded: list[str] = []
    for value in _values(values):
        expanded.append(value)
        without_parenthetical = re.sub(r"\s*\([^()]*\)", "", value).strip()
        if without_parenthetical and without_parenthetical != value:
            expanded.append(without_parenthetical)
    return " OR ".join(f'"{value}"' for value in dict.fromkeys(expanded))


def build_query(
    metabolites: Iterable[str],
    diseases: Iterable[str],
    *,
    search_kind: str = "metabolome_wide",
) -> str:
    """Build one transparent Europe PMC query for a search-plan kind."""
    exposure = _terms(metabolites) or "metabolite"
    outcome = _terms(diseases) or "disease"
    if search_kind == "metabolome_wide":
        # Keep the broad-study search tied to this pair's disease outcome. The
        # metabolite may not appear in a metabolome-wide paper title/abstract,
        # because the study tests many exposures at once.
        scope = f'("metabolome-wide" OR "metabolome wide" OR metabolomics) AND ({outcome})'
        direction = "causal OR association OR exposure"
    elif search_kind == "pair_specific":
        scope = f"({exposure}) AND ({outcome})"
        direction = "causal OR association OR exposure"
    elif search_kind == "challenge":
        scope = f"({exposure}) AND ({outcome})"
        direction = 'reverse OR bidirectional OR null OR conflicting OR "no association" OR population OR ancestry OR ethnicity OR cohort OR replication'
    else:
        raise ValueError(f"unknown search kind: {search_kind}")
    return f"({scope}) AND ({MR_TERMS}) AND ({direction})"


def _paper_key(paper: Mapping[str, Any]) -> str:
    identifiers = paper.get("identifiers", {})
    return (identifiers.get("doi") or identifiers.get("pmid") or identifiers.get("pmcid") or identifiers.get("id") or paper.get("title") or "").lower()


def _identity_keys(paper: Mapping[str, Any]) -> set[str]:
    return {f"{name}:{value.lower()}" for name, value in paper.get("identifiers", {}).items() if value}


def inspect_results(
    papers: Iterable[Mapping[str, Any]],
    *,
    metabolites: Iterable[str],
    diseases: Iterable[str],
    evidence_gaps: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Inspect discovery output and turn observations into next-search gaps."""
    items = list(papers)
    text = " ".join(f"{p.get('title') or ''} {p.get('abstract') or ''}" for p in items).lower()
    exact_metabolite = any(term.lower() in text for term in _values(metabolites))
    exact_disease = any(term.lower() in text for term in _values(diseases))
    full_text_count = sum(bool(p.get("full_text_urls")) for p in items)
    gaps = list(dict.fromkeys(g for g in (evidence_gaps or []) if g))
    if not items:
        gaps.append("no candidate papers returned")
    if not exact_metabolite or not exact_disease:
        gaps.append("pair-specific metabolite/disease coverage is not yet confirmed")
    if not full_text_count:
        gaps.append("full text or supplement availability is not yet confirmed")
    gaps.append("source full text and supplement acquisition still requires screening")
    return {
        "papers_inspected": len(items),
        "abstracts_available": sum(bool(p.get("abstract_available")) for p in items),
        "full_text_links_available": full_text_count,
        "metabolite_term_seen": exact_metabolite,
        "disease_term_seen": exact_disease,
        "remaining_gaps": gaps,
    }


def _default_planner(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """Choose the next search from observed state, then stop explicitly."""
    completed = {round_info["search_kind"] for round_info in state["rounds"]}
    if "metabolome_wide" not in completed:
        return {"search_kind": "metabolome_wide", "goal": "broad metabolome-wide MR discovery"}
    if "pair_specific" not in completed and state["rounds"][-1]["inspection"]["remaining_gaps"]:
        return {"search_kind": "pair_specific", "goal": "gap-driven pair-specific follow-up"}
    if "challenge" not in completed:
        return {
            "search_kind": "challenge",
            "goal": "deliberate challenge search for null, conflicting, reverse-direction or other-population evidence",
            "challenge_axes": ["null", "conflicting", "reverse_direction", "other_population"],
        }
    return None


def search_literature(
    question: str,
    metabolites: Iterable[str],
    diseases: Iterable[str],
    *,
    evidence_gaps: Iterable[str] | None = None,
    max_rounds: int = 1,
    max_pages: int = 1,
    max_requests: int | None = None,
    max_seconds: float | None = None,
    search_fn: Callable[..., Mapping[str, Any]] = search_europe_pmc,
    planner: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] = _default_planner,
) -> dict[str, Any]:
    """Run an inspect → choose-next-search loop with explicit bounded stopping."""
    if not question.strip() or max_rounds < 1 or max_pages < 1 or (max_requests is not None and max_requests < 1) or (max_seconds is not None and max_seconds <= 0):
        raise ValueError("question must be non-empty and all configured limits must be positive")
    metabolites = _values(metabolites)
    diseases = _values(diseases)
    papers: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    rounds: list[dict[str, Any]] = []
    overall_status = "success"
    stop_reason = "search planner selected stop"
    started = monotonic()
    requests_used = 0
    for number in range(1, max_rounds + 1):
        if max_requests is not None and requests_used >= max_requests:
            stop_reason = "configured request limit reached"
            overall_status = "partial"
            break
        if max_seconds is not None and monotonic() - started >= max_seconds:
            stop_reason = "configured time limit reached"
            overall_status = "partial"
            break
        state = {"question": question, "rounds": rounds, "papers": list(papers.values()), "evidence_gaps": list(evidence_gaps or [])}
        plan = planner(state)
        if not plan:
            stop_reason = "no useful next search selected by planner"
            break
        search_kind = plan["search_kind"]
        query = build_query(metabolites, diseases, search_kind=search_kind)
        remaining_requests = None if max_requests is None else max_requests - requests_used
        remaining_seconds = None if max_seconds is None else max(0.001, max_seconds - (monotonic() - started))
        result = search_fn(query, max_pages=max_pages, max_requests=remaining_requests, max_seconds=remaining_seconds, round_number=number)
        provider_requests = sum(h.get("requests_used", 0) for h in result.get("search_history", []))
        requests_used += provider_requests or max(1, len(result.get("search_history", [])))
        before = set(papers)
        for item in result.get("papers", []):
            identity_keys = _identity_keys(item)
            key = next((aliases[identity] for identity in identity_keys if identity in aliases), _paper_key(item))
            if key in papers:
                papers[key]["identifiers"] = {**item.get("identifiers", {}), **papers[key].get("identifiers", {})}
                papers[key]["source_urls"] = list(dict.fromkeys(papers[key].get("source_urls", []) + item.get("source_urls", [])))
                papers[key]["discovery_routes"] = papers[key].get("discovery_routes", []) + item.get("discovery_routes", [])
            else:
                papers[key] = dict(item)
            for identity in identity_keys:
                aliases[identity] = key
        inspection = inspect_results(papers.values(), metabolites=metabolites, diseases=diseases, evidence_gaps=evidence_gaps)
        round_info = {
            "round": number,
            "search_kind": search_kind,
            "goal": plan.get("goal", search_kind),
            "challenge_axes": plan.get("challenge_axes", []),
            "query": query,
            "returned_count": len(result.get("papers", [])),
            "new_paper_count": len(set(papers) - before),
            "deduplication": {"before": len(before), "after": len(papers), "duplicates_merged": len(before) + len(result.get("papers", [])) - len(papers)},
            "inspection": inspection,
            "provider_history": result.get("search_history", []),
            "status": result.get("status", "success"),
        }
        rounds.append(round_info)
        if result.get("status") in {"failed", "partial"}:
            overall_status = "partial"
        if number == max_rounds:
            stop_reason = "configured maximum round limit reached"
            break
    else:
        stop_reason = "configured maximum round limit reached"
    next_state = {"question": question, "rounds": rounds, "papers": list(papers.values()), "evidence_gaps": list(evidence_gaps or [])}
    next_plan = _default_planner(next_state) if stop_reason == "search planner selected stop" else None
    history = []
    for index, info in enumerate(rounds):
        provider_history = info["provider_history"] or [{"provider": "europe_pmc", "query": info["query"]}]
        round_ids = []
        for provider_record in provider_history:
            round_ids.extend(provider_record.get("returned_ids", []))
            for page in provider_record.get("pages", []):
                round_ids.extend(page.get("returned_ids", []))
        if not round_ids:
            round_ids = [identifier.get("id") or identifier.get("pmid") or identifier.get("pmcid") or identifier.get("doi") for paper in papers.values() for identifier in [paper.get("identifiers", {})] if identifier]
        if index + 1 < len(rounds):
            next_for_round = "run next query: " + rounds[index + 1]["goal"]
        elif next_plan:
            next_for_round = "run next query: " + next_plan["goal"]
        else:
            next_for_round = stop_reason
        for page in provider_history:
            page.update({
            "goal": info["goal"],
            "returned_ids": round_ids,
            "deduplication": info["deduplication"],
            "remaining_gaps": info["inspection"]["remaining_gaps"],
            "next_action": next_for_round,
            })
        history.extend(provider_history)
    caveats = ["Europe PMC results are discovery candidates; screening, source acquisition and source-exact MR extraction are still required."]
    if stop_reason == "configured maximum round limit reached":
        caveats.append("The configured limit stopped the investigation before the planner completed all useful search kinds.")
    return {
        "papers": list(papers.values()),
        "search_history": history,
        "rounds": rounds,
        "status": overall_status,
        "remaining_gaps": rounds[-1]["inspection"]["remaining_gaps"] if rounds else list(evidence_gaps or []),
        "stop_reason": stop_reason,
        "next_action": next_plan,
        "runtime_agent": True,
        "provider_scope": ["europe_pmc"],
        "caveats": caveats,
    }
