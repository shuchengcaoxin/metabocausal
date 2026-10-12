"""Data-loading helpers for app.py (1G), kept import-light so tests never start Streamlit.

`app.py` imports this module for everything that is not a live pipeline call or a
Streamlit widget. Every function here reads what already ships on disk and is
git-tracked - MVP2's screened literature table, the three frozen demo pairs committed in
data/demo_card_inputs.json, the three reviewed cards committed under examples/ - and
returns plain dicts, lists or a DataFrame. `cards/` is entirely gitignored (a fresh clone
starts with it empty; see .gitignore's "Local run output; reviewed examples live under
examples/."), so nothing here treats a file under it as shipped. Nothing here calls a
network API or a model, so tests/test_app_data.py exercises the whole module offline.

Wording discipline matches render.py and plots.py: "retrieved", never "computed"; an
absent file or an absent column is stated, never silently dropped.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import plots

REPO_ROOT       = Path(__file__).resolve().parent
CARDS_DIR       = REPO_ROOT / "cards"
EXAMPLES_DIR    = REPO_ROOT / "examples"
LIBRARY_CSV     = REPO_ROOT / "MVP2" / "data" / "extracted" / "mvp1_plus_mvp2_candidate_metabolite_disease.csv"
VALIDATED_DIR   = REPO_ROOT / "MVP2" / "data" / "validated"
INDEX_DIR       = REPO_ROOT / "MVP2" / "data" / "index"

EXAMPLE_CARD_FILES = {
    "urate|gout":                                      "urate_gout.md",
    "glycine|coronary artery disease":                 "glycine_cad.md",
    "trimethylamine N-oxide|coronary artery disease":  "tmao_cad.md",
}

LIBRARY_COLUMNS = [
    "metabolite_name",
    "disease_trait",
    "state",
    "record_type",
    "b",
    "pval",
    "method",
    "nsnp",
    "coloc_h4",
    "supporting_mr_rows",
    "page_path",
]

LIBRARY_NO_STATE_LABEL = "(no state - screened literature candidate, not yet merged into an MR row)"

EXAMPLE_PAIR_LABELS = {
    "urate|gout": (
        "urate x gout - state A, a published MR estimate"
    ),
    "glycine|coronary artery disease": (
        "glycine x coronary artery disease - state B, instruments retrieved, no MR estimate"
    ),
    "trimethylamine N-oxide|coronary artery disease": (
        "trimethylamine N-oxide x coronary artery disease - state C, nothing retrieved"
    ),
}


def example_pairs() -> list:
    """The frozen demo pairs shipped in data/demo_card_inputs.json, file order preserved."""
    pairs = plots.load_demo()
    return [
        {
            "key":   key,
            "label": EXAMPLE_PAIR_LABELS.get(key, key),
            "state": str(pair.get("state") or "").strip(),
        }
        for key, pair in pairs.items()
    ]


def example_card_path(pair_key: str) -> Path:
    """The committed, reviewed card for one frozen demo pair. Raises KeyError for an
    unknown key - a typo must not quietly fall through to a different pair."""
    if pair_key not in EXAMPLE_CARD_FILES:
        raise KeyError(f"{pair_key!r} has no committed example card: {sorted(EXAMPLE_CARD_FILES)}")
    return EXAMPLES_DIR / EXAMPLE_CARD_FILES[pair_key]


def example_card(pair_key: str) -> dict:
    """The committed markdown card for one frozen demo pair, read verbatim from
    examples/ - the reviewed, shipped version, not a regeneration. Raises KeyError for an
    unknown key or FileNotFoundError if the committed file is missing."""
    path = example_card_path(pair_key)
    return {
        "path":    str(path.relative_to(REPO_ROOT)),
        "card_md": path.read_text(encoding="utf-8"),
    }


def example_figures(
    pair_key: str,
    out_dir:  str | Path,
) -> dict:
    """The state figure and the genetics-to-clinic timeline, both drawn now, offline,
    from the committed snapshot data/demo_card_inputs.json - not read from cards/, which
    is entirely gitignored and empty on a fresh clone.

    The snapshot carries only the 1B/1C envelopes, no gene dossier, so
    plot_genetic_insight always returns None here; that absence is reported, not hidden.
    """
    result = plots.demo_result(pair_key)
    stem = plots.stem_for_result(result)
    state_figure = plots.plot_for_result(result, out_dir=str(out_dir))
    timeline_figure = plots.plot_genetic_insight(result, str(out_dir))
    timeline_note = (
        timeline_figure
        if timeline_figure else
        "no genetics-to-clinic timeline: the shipped snapshot carries no gene dossier for "
        "this pair (that stage runs only on a live pipeline.run_pair call, see the "
        "'Run a pair' tab)"
    )
    return {
        "stem":             stem,
        "state_figure":     state_figure,
        "timeline_figure":  timeline_figure,
        "timeline_note":    timeline_note,
    }


def _dir_has_content(path: Path) -> bool:
    if not path.exists():
        return False
    return any(entry.name != ".gitkeep" for entry in path.iterdir())


def library_available() -> bool:
    return LIBRARY_CSV.exists()


def load_library(nrows: int | None = None) -> "pd.DataFrame":
    """MVP2's screened metabolite-disease candidate table - retrieved from literature
    screening, not a live pipeline sweep. Raises FileNotFoundError when the file is not
    on disk; callers check library_available() first, which is what library_summary()
    and the app's library tab do."""
    return pd.read_csv(
        LIBRARY_CSV,
        usecols    = LIBRARY_COLUMNS,
        low_memory = False,
        nrows      = nrows,
    )


def library_summary() -> dict:
    """Row/pair/state counts over the full shipped table, honestly labelled as retrieved
    counts over a literature table - not evidence that any pair's causal state was
    computed. Returns shipped=False, with the missing path named, when the file is not
    on this branch."""
    if not library_available():
        return {
            "shipped": False,
            "reason":  f"{LIBRARY_CSV.relative_to(REPO_ROOT)} is not on disk on this branch.",
        }
    frame = load_library()
    pairs = frame[["metabolite_name", "disease_trait"]].drop_duplicates()
    state_counts = {}
    for key, count in frame["state"].value_counts(dropna=False).items():
        label = LIBRARY_NO_STATE_LABEL if pd.isna(key) else str(key)
        state_counts[label] = int(count)
    return {
        "shipped":            True,
        "path":               str(LIBRARY_CSV.relative_to(REPO_ROOT)),
        "n_rows":             int(len(frame)),
        "n_distinct_pairs":   int(len(pairs)),
        "n_metabolites":      int(frame["metabolite_name"].nunique()),
        "n_diseases":         int(frame["disease_trait"].nunique()),
        "record_type_counts": {
            str(key): int(count)
            for key, count in frame["record_type"].value_counts(dropna=False).items()
        },
        "state_counts":       state_counts,
    }


def library_inventory() -> dict:
    """What MVP2/data actually ships on this branch, and the command that would build
    what is missing. `validated/` and `index/` hold only `.gitkeep` today - nothing here
    claims a validated snapshot or a reproducible index exists."""
    return {
        "extracted_shipped": library_available(),
        "validated_shipped": _dir_has_content(VALIDATED_DIR),
        "index_shipped":     _dir_has_content(INDEX_DIR),
        "validated_note": (
            "MVP2/data/validated/ holds no accepted snapshot on this branch (only "
            ".gitkeep)."
        ),
        "index_note": (
            "MVP2/data/index/ holds no reproducible lookup on this branch (only "
            ".gitkeep) - it is built from a validated snapshot, which does not exist yet."
        ),
        "page_path_note": (
            "the page_path column in the library table names per-metabolite pages "
            "(e.g. data/metabolites/*.md) that are not shipped in this repository - the "
            "column is shown as retrieved, and the pages themselves are not claimed to "
            "exist here."
        ),
        "regenerate_command": (
            "python MVP2/scripts/screen_seed_papers.py "
            "&& python MVP2/scripts/merge_new_pairs.py"
        ),
    }


def frozen_ledgers() -> list:
    """The ledger files sitting under cards/ on THIS machine right now - local run
    output only, not git-tracked, empty on a fresh clone. Never surfaced as a library."""
    if not CARDS_DIR.exists():
        return []
    return sorted(path.name for path in CARDS_DIR.glob("*.ledger.jsonl"))


def frozen_figures() -> list:
    """The PNG figures sitting under cards/ on THIS machine right now - same caveat as
    frozen_ledgers()."""
    if not CARDS_DIR.exists():
        return []
    return sorted(path.name for path in CARDS_DIR.glob("*.png"))
