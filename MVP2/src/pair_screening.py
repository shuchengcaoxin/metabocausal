"""Screen source-extracted paper pairs against an existing MR pair table."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import csv
import fnmatch
import hashlib
from pathlib import Path
import re
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
GITATTRIBUTES = REPO_ROOT / ".gitattributes"


def normalize(value: Any) -> str:
    """Normalize labels for comparison; resolved IDs remain preferred when present.

    ``%`` survives normalization: it distinguishes a ratio exposure such as
    ``Omega-3%`` from the absolute exposure ``Omega-3``.
    """
    return re.sub(r"[^a-z0-9%]+", " ", str(value or "").casefold()).strip()


def _first(row: Mapping[str, Any], names: Iterable[str]) -> str:
    for name in names:
        value = str(row.get(name, "") or "").strip()
        if value:
            return value
    return ""


def pair_keys(row: Mapping[str, Any]) -> set[str]:
    metabolite_id = _first(row, ("metabolite_chebi", "chebi_id", "metabolite_id"))
    metabolite_name = _first(row, ("metabolite_name", "metabolite", "exposure", "exposure_long"))
    disease_id = _first(row, ("disease_id", "outcome_id", "disease_code"))
    disease_name = _first(row, ("disease_trait", "disease", "outcome", "outcome_long"))
    keys = set()
    if metabolite_id and disease_id:
        keys.add(f"id|{normalize(metabolite_id)}|{normalize(disease_id)}")
    if metabolite_name and disease_name:
        keys.add(f"name|{normalize(metabolite_name)}|{normalize(disease_name)}")
    return keys


def canonical_pair_key(row: Mapping[str, Any]) -> str:
    """Return one stable pair identity, preferring resolved IDs over labels."""
    keys = pair_keys(row)
    return sorted(key for key in keys if key.startswith("id|"))[0] if any(key.startswith("id|") for key in keys) else (sorted(keys)[0] if keys else "")


def _is_forward(row: Mapping[str, Any]) -> bool:
    direction = normalize(_first(row, ("direction", "causal_direction", "analysis_direction")))
    return direction in {"", "forward", "metabolite disease", "metabolite outcome", "exposure outcome"}


def screen_pairs(baseline_rows: Iterable[Mapping[str, Any]], candidate_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return all decisions and candidate records absent from the baseline.

    This is an anti-join, not a scientific quality decision. Candidate rows keep
    their source fields and are never silently converted into accepted MR data.
    """
    baseline_rows = list(baseline_rows)
    baseline_keys = {key for row in baseline_rows for key in pair_keys(row)}
    baseline_pair_keys = {canonical_pair_key(row) for row in baseline_rows if canonical_pair_key(row)}
    decisions = []
    new_records = []
    new_pair_records: dict[str, dict[str, Any]] = {}
    supporting_row_counts: dict[str, int] = {}
    for index, source in enumerate(candidate_rows, 1):
        row = dict(source)
        keys = pair_keys(row)
        if not _is_forward(row):
            status, basis = "excluded_direction", "not_forward_metabolite_to_disease"
        elif not keys:
            status, basis = "unresolved_identity", "missing_metabolite_or_disease_identity"
        elif keys & baseline_keys:
            status, basis = "already_present", "baseline_pair_match"
        else:
            status, basis = "new_pair", "anti_join_no_baseline_match"
            new_records.append(row)
            key = canonical_pair_key(row)
            supporting_row_counts[key] = supporting_row_counts.get(key, 0) + 1
            new_pair_records.setdefault(key, row)
        decisions.append({**row, "candidate_row": index, "screen_status": status, "match_basis": basis, "pair_keys": ";".join(sorted(keys))})
    unique_pairs = []
    for key, row in new_pair_records.items():
        unique_row = dict(row)
        unique_row["supporting_source_rows"] = str(supporting_row_counts[key])
        unique_pairs.append(unique_row)
    return {
        "new_pair_records": new_records,
        "new_unique_pairs": unique_pairs,
        "decisions": decisions,
        "summary": {
            "baseline_pair_key_count": len(baseline_pair_keys),
            "candidate_row_count": len(decisions),
            "new_pair_record_count": len(new_records),
            "new_pair_key_count": len(new_pair_records),
            "already_present_count": sum(x["screen_status"] == "already_present" for x in decisions),
            "excluded_direction_count": sum(x["screen_status"] == "excluded_direction" for x in decisions),
            "unresolved_identity_count": sum(x["screen_status"] == "unresolved_identity" for x in decisions),
        },
    }


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def record_path(path: str | Path) -> str:
    """The spelling of a path to write into a manifest: repo-relative, POSIX, always.

    A manifest is read on a machine that is not the one that wrote it, so it may
    not record that machine's drive letter, home directory or separator. This
    returns the same string on Windows and on Linux for the same file. A path
    outside the repository has no repo-relative spelling; it is returned with
    POSIX separators and is machine-specific, which the caller should avoid.
    """
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _gitattributes_patterns() -> list[str]:
    """The path patterns ``.gitattributes`` pins to raw bytes (``-text``/``binary``).

    Read from the file rather than asked of ``git``. The digest a manifest records
    is evidence about bytes, and it may not change depending on whether a ``git``
    binary is on PATH: a bundle verified from a zip export, or in an image without
    git, has the same bytes and must produce the same number.
    """
    if not GITATTRIBUTES.exists():
        return []
    patterns = []
    for line in GITATTRIBUTES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pattern, _, attributes = line.partition(" ")
        if "-text" in attributes.split() or "binary" in attributes.split():
            patterns.append(pattern)
    return patterns


def _pinned_bytes_by_gitattributes(path: str | Path) -> bool:
    """True when ``.gitattributes`` pins this path's bytes (never line-converted).

    ``fnmatch`` against the repo-relative POSIX path. This understands the subset
    of the gitattributes pattern language this repository actually uses - a
    leading-directory glob (``archive/**``) and a suffix glob (``*.xlsx``) - and
    nothing else; a pattern outside that subset would need extending here.
    """
    relative = record_path(path)
    return any(
        fnmatch.fnmatch(relative, pattern)
        or fnmatch.fnmatch(relative, pattern.rstrip("/*") + "/*")
        for pattern in _gitattributes_patterns()
    )


# What the two hash modes are called in a manifest entry, so a verifier can reproduce
# the digest from the bytes alone instead of guessing which rule produced it.
BYTES_AS_COMMITTED = "as-committed"
BYTES_LF_NORMALIZED = "lf-normalized"


def hash_mode(path: str | Path) -> str:
    """Which of the two rules ``sha256`` applies to this path."""
    return BYTES_AS_COMMITTED if _pinned_bytes_by_gitattributes(path) else BYTES_LF_NORMALIZED


def sha256(path: str | Path) -> str:
    """Hash the committed blob bytes, not whatever this checkout put on disk.

    This package writes its own CSV/JSON artifacts with ``lineterminator="\\n"``,
    but a Windows checkout with ``core.autocrlf`` on rewrites those bytes to
    CRLF on disk without changing the committed blob; normalizing CRLF to LF
    before hashing keeps the digest reproducible across platforms. A path
    ``.gitattributes`` pins to raw bytes (for example the archived evidence under
    ``archive/**``) is the opposite case: its committed blob keeps whatever
    line endings it was checked in with, on every platform, so it is hashed
    as-is. ``hash_mode`` names which of the two applied, and every manifest this
    package writes records it beside the digest.
    """
    raw = Path(path).read_bytes()
    if hash_mode(path) == BYTES_AS_COMMITTED:
        return hashlib.sha256(raw).hexdigest()
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def hashed(path: str | Path, **extra: Any) -> dict[str, Any]:
    """One manifest entry for a file: where it is, its digest, and by which rule."""
    return {
        "path": record_path(path),
        "sha256": sha256(path),
        "bytes": hash_mode(path),
        **extra,
    }
