"""The executable tool registry: everything in TOOLS can actually be called.

Offline. No request is made - the point of this file is structural, not behavioural.

A model given TOOLS may call any entry at any time, so a planned tool listed there is not
a smaller version of that tool, it is a crash in the middle of an otherwise complete run.
get_literature_mr (MVP2) was registered while its body still raised
NotImplementedError. Human-GEM (MVP3) is now implemented and registered. The first test
below still fails if any placeholder appears in the executable registry, because it
looks at what the function body references rather than at a fixed list of names.
"""

from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import tools
from tools import TOOLS, UNIMPLEMENTED


def is_placeholder(function) -> bool:
    """True when the body references NotImplementedError.

    co_names holds the global names a function body actually looks up, so this catches a
    stub whatever it is called and whatever its signature says, without executing it."""
    return "NotImplementedError" in function.__code__.co_names


class RegistryIsExecutable(unittest.TestCase):
    def test_no_registered_tool_is_a_placeholder(self):
        placeholders = [tool.__name__ for tool in TOOLS if is_placeholder(tool)]
        self.assertEqual(
            placeholders,
            [],
            "TOOLS must hold only implemented functions; these raise NotImplementedError",
        )

    def test_the_known_placeholders_are_still_placeholders(self):
        # If a placeholder grows a body, it should MOVE to TOOLS rather than sit in
        # UNIMPLEMENTED being quietly callable, so assert the two lists stay honest.
        for tool in UNIMPLEMENTED:
            with self.subTest(tool=tool.__name__):
                self.assertTrue(
                    is_placeholder(tool),
                    f"{tool.__name__} has a body now - move it into TOOLS",
                )

    def test_registry_and_placeholders_are_disjoint(self):
        registered = {tool.__name__ for tool in TOOLS}
        pending = {tool.__name__ for tool in UNIMPLEMENTED}
        self.assertEqual(registered & pending, set())

    def test_every_registered_tool_has_a_docstring(self):
        # The docstring is what the model reads to decide WHEN to call a tool, so an
        # undocumented entry is a tool the model cannot use correctly.
        undocumented = [tool.__name__ for tool in TOOLS if not (tool.__doc__ or "").strip()]
        self.assertEqual(undocumented, [])

    def test_no_duplicate_entries(self):
        names = [tool.__name__ for tool in TOOLS]
        self.assertEqual(sorted(names), sorted(set(names)))


class DeliberateExclusions(unittest.TestCase):
    """Three implemented functions are kept OUT of TOOLS on purpose. Each one is cheap to
    re-add by accident and expensive to have registered, so each is pinned here."""

    def test_resolve_ids_is_not_registered(self):
        # 1A runs deterministically before the model. A model that could resolve an
        # identity could also invent a synonym, and downstream a thin synonym list reads
        # as an evidence gap rather than as a naming error.
        self.assertNotIn(tools.resolve_ids, TOOLS)
        self.assertNotIn(tools.resolve_metabolite, TOOLS)
        self.assertNotIn(tools.resolve_disease, TOOLS)

    def test_get_mr_outcomes_is_not_registered(self):
        # A wildcard sweep returning thousands of rows, for building candidate lists
        # offline. Not something to fire while assembling one card.
        self.assertNotIn(tools.get_mr_outcomes, TOOLS)

    def test_get_trial_dates_is_not_registered(self):
        # One request per trial. A model able to fire it could spend an unbounded number
        # of requests on a single figure.
        from tools.trials import get_trial_dates

        self.assertNotIn(get_trial_dates, TOOLS)


if __name__ == "__main__":
    unittest.main()
