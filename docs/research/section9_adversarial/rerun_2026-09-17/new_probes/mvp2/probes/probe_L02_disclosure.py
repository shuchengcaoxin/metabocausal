"""L02 - where does a rendered card disclose that the MVP2 literature arm is absent?

L01 established that no MVP2 artefact reaches the card path. This probe asks the
complementary reader-facing question: on the frozen A/B/C fixtures, which rendered
cards actually tell the reader that the literature arm was never consulted?

Deterministic, offline, no credential. Renders every cached demo pair with a
model-free interpretation (interpretation=None), which is the renderer path that
does not depend on a stub reply.

Run from the repository root:
    python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/mvp2/probes/probe_L02_disclosure.py
"""

from __future__ import annotations

import io
import json
import os
import re
import sys


def _find_repo_root(start: str) -> str:
    here = os.path.abspath(start)
    while True:
        if (
            os.path.isfile(os.path.join(here, "render.py"))
            and os.path.isfile(os.path.join(here, "classify.py"))
            and os.path.isdir(os.path.join(here, "MVP2"))
        ):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            raise RuntimeError("repository root not found above %s" % start)
        here = parent


REPO = _find_repo_root(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs"))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import render  # noqa: E402
from scripts.interpretation_fixtures import demo_runs  # noqa: E402

NEEDLE = "literature MR arm (MVP2)"
SOFT_NEEDLES = ["literature", "MVP2"]


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    cards_dir = os.path.join(OUT_DIR, "L02_cards")
    os.makedirs(cards_dir, exist_ok=True)

    runs = demo_runs()
    rows = []
    lines = ["L02 - MVP2-absence disclosure across the frozen demo pairs", ""]
    lines.append("renderer entry point: render.render_card(run, interpretation=None)")
    lines.append("needle: %r" % NEEDLE)
    lines.append("")
    header = "%-34s %-6s %-12s %s" % ("pair", "state", "discloses", "card file")
    lines.append(header)
    lines.append("-" * len(header))

    for pair in sorted(runs):
        run = runs[pair]
        card = render.render_card(run, None)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", pair)
        path = os.path.join(cards_dir, "%s.md" % safe)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(card)
        discloses = NEEDLE in card
        soft = {needle: (needle in card) for needle in SOFT_NEEDLES}
        rows.append(
            {
                "pair": pair,
                "state": run["state"],
                "discloses_mvp2_absence": discloses,
                "soft_token_present": soft,
                "card_chars": len(card),
                "card_file": os.path.relpath(path, OUT_DIR).replace("\\", "/"),
            }
        )
        lines.append(
            "%-34s %-6s %-12s %s"
            % (pair, run["state"], "yes" if discloses else "NO", os.path.basename(path))
        )

    by_state = {}
    for row in rows:
        by_state.setdefault(row["state"], {"n": 0, "disclosing": 0})
        by_state[row["state"]]["n"] += 1
        if row["discloses_mvp2_absence"]:
            by_state[row["state"]]["disclosing"] += 1

    lines.append("")
    lines.append("by state:")
    for state in sorted(by_state):
        entry = by_state[state]
        lines.append(
            "  state %s: %d/%d cards disclose the MVP2 gap" % (state, entry["disclosing"], entry["n"])
        )

    lines.append("")
    lines.append("source of the disclosure string in render.py:")
    with io.open(os.path.join(REPO, "render.py"), "r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if "literature MR arm (MVP2)" in line:
                lines.append("  render.py:%d %s" % (lineno, line.strip()))
    lines.append("  enclosing function, by definition order:")
    with io.open(os.path.join(REPO, "render.py"), "r", encoding="utf-8") as handle:
        current = None
        for lineno, line in enumerate(handle, start=1):
            if line.startswith("def "):
                current = (lineno, line.strip())
            if "literature MR arm (MVP2)" in line and current:
                lines.append("    line %d is inside %s (def at line %d)" % (lineno, current[1], current[0]))

    text = "\n".join(lines) + "\n"
    with io.open(os.path.join(OUT_DIR, "L02_disclosure.txt"), "w", encoding="utf-8") as handle:
        handle.write(text)
    with io.open(os.path.join(OUT_DIR, "L02_disclosure.json"), "w", encoding="utf-8") as handle:
        json.dump({"rows": rows, "by_state": by_state}, handle, indent=2, sort_keys=True)
        handle.write("\n")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
