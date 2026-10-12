"""The Slack shell's two pure functions, plus the handler's failure path. Fully offline.

    python -m unittest tests.test_slack_format -v          # from the repo root

Nothing here opens a socket, reads a token or calls a database. `parse_pair` is a
string function and `format_card` is a rendering function over a dict that
`pipeline.run_pair` would have produced, so both are tested on synthetic results - and
the handler is tested with a fake `say` and a `run_pair` that raises, which is the only
way to see the failure reply without breaking Slack on purpose.

WHAT THE WORDING ASSERTIONS ARE PROTECTING

  the verdict line      a reader must see the state and its meaning in the first line,
                        before any number
  the footer            "every number traceable - N ledger entries - {file}" is the
                        invitation to go and check; a card without it is a claim with
                        no receipt
  the empty MR arm      "no pre-computed MR found in this snapshot (not evidence of no
                        effect)". A missing row in a 2020 snapshot is a gap in what was
                        retrieved. The moment a card renders that as "no effect" the
                        project has told a scientist something false
  the error arm         a tool that FAILED and a source that holds no record are two
                        different sentences, and an error envelope that still carries
                        retrieved rows must report those rows, not "nothing found".
                        This holds for the 1E dossier lines too
  the caps              every cap the envelope states must reach the card: the
                        instruments line discloses how many datasets were never opened
  user text is data     `<!channel>` and `<https://evil/|EpiGraphDB MR-EVE>` must come
                        back out escaped, not fired
  3000 characters       Slack renders at most 3000 characters per block. A long
                        classifier reason must not be able to push the footer out of
                        the message
  no emojis             the owner's rule for everything this project writes

WHAT THE BLOCK KIT AND ATTACHMENT ASSERTIONS ARE PROTECTING

  the same sentences    the blocks say what the mrkdwn card says. Every field body is
                        built by the same line function, so a wording rule fixed once is
                        fixed on both surfaces - and these tests check the blocks for the
                        same things they check the card for
  Slack's own limits    a block over 150 / 2000 / 3000 characters is rejected for the
                        WHOLE message, so an over-long name or classifier reason would
                        not shorten the reply, it would delete it. slack_sdk's own block
                        models parse and validate every block this shell builds
  the fallback text     a message with blocks still carries the whole card in `text`,
                        which is what a notification preview and a client that cannot
                        render blocks show
  the upload is not     files:write is a scope the app is still waiting for. A
  the evidence          `missing_scope` costs a reader one line of explanation and
                        nothing else: the summary stands, the card and the figure are on
                        disk in cards/, and nothing is retried
  never crash           an upload failure, a renderer failure, a figure failure and a
                        block-layout failure each degrade to words. The handler always
                        answers
"""

from __future__ import annotations

import contextlib
import inspect
import io
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import render
import slack_app

try:
    from slack_sdk.errors import SlackApiError
except ImportError:                                      # pragma: no cover - import guard
    SlackApiError = None

try:
    from slack_sdk.models.blocks import Block
except ImportError:                                      # pragma: no cover - import guard
    Block = None

# slack_app guards this import itself: a machine without matplotlib answers a mention
# with the summary and the card, and the figure tests below skip rather than fail.
plots = slack_app.plots

SLACK_BLOCK_LIMIT = 3000
SLACK_HEADER_LIMIT = 150
SLACK_FIELD_LIMIT = 2000
SLACK_MAX_FIELDS = 10
SLACK_MAX_CONTEXT_ELEMENTS = 10

NOT_NO_EFFECT = "not evidence of no effect"
# Both footers are written out in full here rather than imported from slack_app: a test
# that reads its expected string out of the module it is testing asserts nothing.
FOOTER_PREFIX = "every number traceable - "
BLOCK_FOOTER_PREFIX = "Retrieved, not computed - "

DEMO_PATH = REPO_ROOT / "data" / "demo_card_inputs.json"
DEMO_A = "urate|gout"
DEMO_B = "glycine|coronary artery disease"
DEMO_C = "trimethylamine N-oxide|coronary artery disease"


def envelope(
    tool:   str,
    status: str,
    data:   dict,
) -> dict:
    return {
        "tool":         tool,
        "args":         {},
        "source":       "synthetic",
        "url":          "https://example.invalid/synthetic",
        "retrieved_at": "2026-09-10T00:00:00",
        "status":       status,
        "data":         data,
        "caveats":      ["Retrieved, not computed here."],
    }


def entity(
    query:    str,
    resolved: bool = True,
):
    return {
        "query":         query,
        "input":         query,
        "label":         query,
        "id":            "MONDO:0005393" if resolved else "",
        "synonyms":      [query],
        "resolved":      resolved,
        "resolved_from": "urate|gout" if resolved else None,
    }


def result_a(reason: str = "State A (retrieved MR): 1 estimate(s) carry a numeric effect size.") -> dict:
    """urate x gout as run_pair would hand it over: one complete retrieved estimate."""
    return {
        "state":      "A",
        "reason":     reason,
        "metabolite": entity("urate"),
        "disease":    entity("gout"),
        "envelopes":  {
            "mr": envelope(
                "get_mr_result",
                "ok",
                {
                    "n_estimates": 2,
                    "estimates": [
                        {
                            "exposure_id":    "ieu-a-789",
                            "exposure_trait": "Urate",
                            "outcome_id":     "ieu-a-1054",
                            "outcome_trait":  "Gout",
                            "b":              1.3665151455190399,
                            "se":             0.106814322383297,
                            "pval":           1.7855974619591198e-37,
                            "method":         "FE IVW",
                        },
                        {
                            "exposure_id":    "ieu-a-788",
                            "exposure_trait": "Urate",
                            "outcome_id":     "ieu-a-1054",
                            "outcome_trait":  "Gout",
                            "b":              0.9,
                            "se":             0.4,
                            "pval":           0.02,
                            "method":         "FE IVW",
                        },
                    ],
                },
            ),
            "instruments": envelope(
                "get_mqtl_instruments",
                "ok",
                {
                    # 22 OpenGWAS datasets measure urate; the cap queried the 2 largest.
                    "matched_datasets": 22,
                    "exposures": [
                        {
                            "id":               "ieu-b-5137",
                            "trait":            "Urate",
                            "gws_hits":         323,
                            "weak_instruments": 0,
                        },
                        {
                            "id":               "ieu-a-788",
                            "trait":            "Urate",
                            "gws_hits":         0,
                            "weak_instruments": 0,
                        },
                    ],
                },
            ),
            "outcomes": envelope(
                "find_outcome_datasets",
                "ok",
                {
                    "n_datasets":           1,
                    "n_matched_before_cap": 4,
                    "datasets": [
                        {
                            "id":          "ebi-a-GCST90038687",
                            "trait":       "Gout",
                            "sample_size": 484598,
                        },
                    ],
                },
            ),
        },
        "ledger_path":      "cards/urate_gout.ledger.jsonl",
        "n_ledger_entries": 3,
        "notes":            [],
    }


def result_c() -> dict:
    """The pair nobody resolved: empty everywhere, two degradation notes, state C."""
    return {
        "state":      "C",
        "reason":     (
            "State C (evidence gap): no retrieved MR estimate and the pair is not shown "
            "to be analysis-ready. An empty or failed result is a gap in what could be "
            f"retrieved, {NOT_NO_EFFECT}."
        ),
        "metabolite": entity("zzz", resolved=False),
        "disease":    entity("yyy", resolved=False),
        "envelopes":  {
            "mr": envelope(
                "get_mr_result",
                "empty",
                {"n_estimates": 0, "estimates": []},
            ),
            "instruments": envelope(
                "get_mqtl_instruments",
                "empty",
                {"exposures": []},
            ),
            "outcomes": envelope(
                "find_outcome_datasets",
                "empty",
                {"datasets": [], "n_datasets": 0, "n_matched_before_cap": 0},
            ),
        },
        "ledger_path":      "cards/zzz_yyy.ledger.jsonl",
        "n_ledger_entries": 3,
        "notes": [
            "metabolite 'zzz': entity not in the pre-resolved sample; matching used the "
            "raw input string only - full resolver (1A) lands separately.",
            "disease 'yyy': entity not in the pre-resolved sample; matching used the raw "
            "input string only - full resolver (1A) lands separately.",
        ],
    }


class Say:
    """Stands in for Bolt's `say`. Records what would have been posted, and to which
    thread, without a Slack client anywhere. `blocks` is captured the same way `text` is
    - the reply now carries both, and a test that only saw `text` could not tell a
    Block Kit summary from the plain card it falls back to."""

    def __init__(self):
        self.calls = []

    def __call__(
        self,
        text      = None,
        thread_ts = None,
        blocks    = None,
        **ignored,
    ):
        self.calls.append({
            "text":      text,
            "thread_ts": thread_ts,
            "blocks":    blocks,
        })


class Client:
    """Stands in for Bolt's WebClient. Records every files_upload_v2 call and, when it
    was built with one, raises the error a real client would have raised."""

    def __init__(
        self,
        error   = None,
        errors  = None,
    ):
        self.uploads = []
        self.error = error
        self.errors = list(errors) if errors else None

    def files_upload_v2(self, **kwargs):
        self.uploads.append(kwargs)
        failure = self.error
        if self.errors is not None:
            failure = self.errors.pop(0) if self.errors else None
        if failure is not None:
            raise failure
        return {"ok": True, "file": {"id": f"F{len(self.uploads)}"}}


class Ack:
    """Stands in for Bolt's `ack`. Slack retries an interaction nobody acknowledged inside
    three seconds, and a retried Generate is a second run of the same pair - so every
    interactive handler is checked for having called this before it does any work."""

    def __init__(self, failure=None):
        self.calls = 0
        self.failure = failure

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.failure is not None:
            raise self.failure


def generate_body(
    pair      = ("urate", "gout"),
    arms      = None,
    thread_ts = "111.222",
    channel   = "C0DEMO",
) -> dict:
    """The block_actions payload Slack posts when the generate button is pressed.

    `arms=None` is the restart case - a payload with no checkbox state at all, which must
    run the menu's own defaults rather than nothing.
    """
    body = {
        "type":      "block_actions",
        "container": {
            "type":       "message",
            "channel_id": channel,
            "thread_ts":  thread_ts,
            "message_ts": "222.333",
        },
        "channel":   {"id": channel},
        "actions":   [{
            "type":      "button",
            "action_id": slack_app.GENERATE_ACTION_ID,
            "value":     slack_app.encode_pair_value(*pair),
        }],
    }
    if arms is not None:
        body["state"] = {"values": {
            slack_app.ARMS_BLOCK_ID: {
                slack_app.ARMS_ACTION_ID: {
                    "type":             "checkboxes",
                    "selected_options": [
                        {"value": value, "text": {"type": "plain_text", "text": value}}
                        for value in arms
                    ],
                },
            },
        }}
    return body


def figure_body(
    kind,
    thread_ts = "111.222",
    channel   = "C0DEMO",
) -> dict:
    """The block_actions payload of one follow-up button."""
    return {
        "type":      "block_actions",
        "container": {
            "type":       "message",
            "channel_id": channel,
            "thread_ts":  thread_ts,
            "message_ts": "333.444",
        },
        "channel":   {"id": channel},
        "actions":   [{
            "type":      "button",
            "action_id": slack_app.FIGURE_ACTION_IDS.get(kind, kind),
            "value":     slack_app.encode_figure_value(kind, thread_ts),
        }],
    }


def slack_error(code: str):
    """The real SlackApiError a real client raises, carrying the real error string."""
    return SlackApiError(
        message  = "files_upload_v2 failed",
        response = {"ok": False, "error": code},
    )


def demo_result(pair_key: str) -> dict:
    """One headline pair rebuilt from data/demo_card_inputs.json - real envelopes from a
    real run, read off disk, with nothing queried. plots.py owns the tool-name ->
    slot-name mapping, so it is read from there rather than copied here."""
    return plots.demo_result(pair_key)


def field_named(
    blocks,
    title: str,
) -> str:
    """The body of the evidence field with this bold title.

    By title rather than by index: the evidence section grows an arm whenever a new
    retrieval lands (colocalisation was the last one), and a test that counted positions
    would start asserting about the wrong sentence the day it does.
    """
    for block in blocks:
        for field in block.get("fields") or []:
            text = str(field.get("text") or "")
            if text.startswith(f"*{title}*"):
                return text
    raise AssertionError(f"no field titled {title!r} in these blocks")


def block_texts(blocks) -> list:
    """Every string a reader can see, from every block, in reading order.

    A context element carries its text as a string; a button carries it as a nested text
    object, and an accessory hangs off the block rather than sitting in `elements`. All
    three are unwrapped here, because "is this escaped?" has to be asked of every string
    that reaches a reader, not only the ones in the summary's shape.
    """
    texts = []

    def add(value):
        if isinstance(value, dict):
            value = value.get("text")
        if isinstance(value, str):
            texts.append(value)

    for block in blocks:
        add(block.get("text"))
        for field in block.get("fields") or []:
            add(field)
        elements = list(block.get("elements") or [])
        if block.get("accessory") is not None:
            elements.append(block["accessory"])
        for element in elements:
            add(element)
            for option in (element.get("options") or []) if isinstance(element, dict) else []:
                add(option)
                add(option.get("description"))
    return texts


class AttachMixin:
    """Any test that can reach the attachment stage points CARDS_DIR at a temp folder
    first - including the ones that expect to write nothing.

    cards/*.md is deliberately NOT gitignored: 1G ships pre-generated example cards out
    of that folder. Every fixture in this file is synthetic, so a card written there from
    one would ship as a real example of a pair nobody ran. Redirecting the folder is one
    line, and it makes that impossible rather than unlikely.
    """

    def use_offline_interpretation(self, interpretation=None, note=""):
        """Stop the handler reaching a real model.

        `write_section_nine` reads the deployment's own key out of .env, so on a machine
        that has one configured these tests would make a live API call - slow, billable,
        and a different answer every run. This file is offline by contract; section 9 has
        its own coverage in SectionNineOnTheOperatorKey and in tests/test_interpret.py."""
        self.addCleanup(setattr, slack_app, "write_section_nine",
                        slack_app.write_section_nine)
        slack_app.write_section_nine = lambda *args, **kwargs: (interpretation, note)

    def use_temp_cards(self):
        self.use_offline_interpretation()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.addCleanup(setattr, slack_app, "CARDS_DIR", slack_app.CARDS_DIR)
        slack_app.CARDS_DIR = Path(folder.name)
        return Path(folder.name)

    def use_fake_plots(self, **kwargs):
        self.addCleanup(setattr, slack_app, "plots", slack_app.plots)
        slack_app.plots = FakePlots(slack_app.CARDS_DIR, **kwargs)
        return slack_app.plots

    def attach(
        self,
        result,
        client,
        channel = "C0DEMO",
    ):
        with contextlib.redirect_stdout(io.StringIO()):
            return slack_app.attach_artifacts(
                result,
                client,
                channel,
                "111.222",
            )

    def press_generate(
        self,
        client,
        say       = None,
        arms      = None,
        pair      = ("urate", "gout"),
        thread_ts = "111.222",
    ):
        """The generate button, pressed. This is what the mention used to do directly, and
        every assertion about the run itself now goes through here."""
        self.addCleanup(slack_app.forget_runs)
        ack = Ack()
        with contextlib.redirect_stdout(io.StringIO()):
            slack_app.handle_generate(
                ack,
                generate_body(
                    pair      = pair,
                    arms      = arms,
                    thread_ts = thread_ts,
                ),
                say if say is not None else self.say,
                None,
                client,
            )
        self.assertEqual(ack.calls, 1, "Slack retries an interaction nobody acknowledged")

    def press_figure(
        self,
        kind,
        client    = None,
        say       = None,
        thread_ts = "111.222",
    ):
        ack = Ack()
        with contextlib.redirect_stdout(io.StringIO()):
            slack_app.handle_figure(
                ack,
                figure_body(
                    kind,
                    thread_ts = thread_ts,
                ),
                say if say is not None else self.say,
                None,
                client,
            )
        self.assertEqual(ack.calls, 1, "Slack retries an interaction nobody acknowledged")

    def summary_call(self):
        """The one reply that carries the card. The running line goes out before it and
        the follow-up buttons after it, so no test should count positions by hand."""
        for call in self.say.calls:
            if call.get("blocks") or str(call.get("text") or "").startswith("*State"):
                return call
        raise AssertionError(f"no summary in {[call['text'] for call in self.say.calls]}")


class TestParsePair(unittest.TestCase):

    def test_the_separators_a_chemist_would_type(self):
        cases = {
            "<@U123ABC> glycine x coronary artery disease": ("glycine", "coronary artery disease"),
            "urate vs gout":                                ("urate", "gout"),
            "urate vs. gout":                               ("urate", "gout"),
            "citrate versus ischemic stroke":               ("citrate", "ischemic stroke"),
            "urate -> gout":                                ("urate", "gout"),
            "urate->gout":                                  ("urate", "gout"),
            "creatinine => chronic kidney disease":         ("creatinine", "chronic kidney disease"),
            "is urate causal for gout":                     ("urate", "gout"),
            "does glycine cause coronary artery disease?":  ("glycine", "coronary artery disease"),
            "<@U1> please check isoleucine x type 2 diabetes.": ("isoleucine", "type 2 diabetes"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(slack_app.parse_pair(text), expected)

    def test_a_quoted_name_may_contain_the_separator_word(self):
        self.assertEqual(
            slack_app.parse_pair('<@U1> "trimethylamine N-oxide" x "coronary artery disease"'),
            ("trimethylamine N-oxide", "coronary artery disease"),
        )
        self.assertEqual(
            slack_app.parse_pair('"vitamin x" vs gout'),
            ("vitamin x", "gout"),
        )

    def test_case_and_spacing_are_preserved_for_the_lookup_to_fold(self):
        self.assertEqual(
            slack_app.parse_pair("<@U1>   Urate    VS    Gout  "),
            ("Urate", "Gout"),
        )

    def test_what_must_not_parse(self):
        for text in (
            "",
            "   ",
            "<@U123ABC>",
            "hello",
            "urate",
            "urate x",
            "x gout",
            "urate x gout x glycine",
            "what is this bot for?",
            None,
            42,
        ):
            with self.subTest(text=text):
                self.assertIsNone(slack_app.parse_pair(text))

    def test_an_absurdly_long_name_is_refused_rather_than_sent_to_the_tools(self):
        self.assertIsNone(slack_app.parse_pair("a" * 400 + " x gout"))

    def test_an_apostrophe_in_a_disease_name_survives(self):
        """Two apostrophes in one mention used to be read as a quoted span, and the
        restoration dropped them: the pipeline was handed a name nobody typed."""
        self.assertEqual(
            slack_app.parse_pair("<@U1> is homocysteine causal for Alzheimer's disease"),
            ("homocysteine", "Alzheimer's disease"),
        )
        self.assertEqual(
            slack_app.parse_pair("<@U1> urate vs Graves' disease"),
            ("urate", "Graves' disease"),
        )
        self.assertEqual(
            slack_app.parse_pair("<@U1> Alzheimer's x Parkinson's"),
            ("Alzheimer's", "Parkinson's"),
        )

    def test_a_trailing_courtesy_word_is_not_part_of_the_disease_name(self):
        """'urate vs gout please' queried the disease 'gout please', which resolves
        against nothing and comes back State C - for the flagship State A pair."""
        cases = {
            "<@U1> urate vs gout please":            ("urate", "gout"),
            "<@U1> urate vs gout, please.":          ("urate", "gout"),
            "<@U1> urate vs gout thanks":            ("urate", "gout"),
            "<@U1> urate x gout thank you":          ("urate", "gout"),
            "<@U1> can you do urate x gout for me":  ("urate", "gout"),
            "<@U1> please run urate -> gout now":    ("urate", "gout"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(slack_app.parse_pair(text), expected)

    def test_a_quoted_name_that_really_ends_in_a_courtesy_word_is_left_alone(self):
        self.assertEqual(
            slack_app.parse_pair('<@U1> urate vs "gout now"'),
            ("urate", "gout now"),
        )

    def test_a_slack_control_sequence_never_reaches_the_pipeline(self):
        """Slack delivers the user's `<` and `>` HTML-escaped, so html.unescape turns
        them back into raw markup AFTER the mention and link strippers have run."""
        pair = slack_app.parse_pair("<@U1> urate vs gout &lt;!channel&gt;")
        self.assertIsNotNone(pair)
        for name in pair:
            self.assertNotIn("<", name)
            self.assertNotIn(">", name)


class CardMixin:
    def assert_card_invariants(self, card):
        self.assertIsInstance(card, str)
        lines = card.split("\n")
        for line in lines:
            self.assertLessEqual(
                len(line),
                SLACK_BLOCK_LIMIT,
                "no line may exceed Slack's 3000-character block limit",
            )
        self.assertTrue(lines[0].startswith("*State "), lines[0])
        self.assertTrue(lines[0].count("*") >= 2, "the verdict line must be bold mrkdwn")
        self.assertTrue(lines[-1].startswith(FOOTER_PREFIX), lines[-1])
        self.assertTrue(
            all(ord(character) < 128 for character in card),
            "the card must stay plain ASCII: no emojis, no smart punctuation",
        )


class TestFormatCardStateA(CardMixin, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.card = slack_app.format_card(result_a())

    def test_invariants(self):
        self.assert_card_invariants(self.card)

    def test_the_verdict_line_names_the_state_and_the_pair(self):
        first = self.card.split("\n")[0]
        self.assertIn("*State A - retrieved MR*", first)
        self.assertIn("urate x gout", first)

    def test_the_reason_sentence_from_classify_is_carried_verbatim(self):
        self.assertIn("State A (retrieved MR): 1 estimate(s) carry", self.card)

    def test_the_mr_line_is_retrieved_and_names_the_dataset_beside_the_number(self):
        line = self.line_with("retrieved MR:")
        self.assertIn("retrieved", line)
        self.assertIn("ieu-a-789 -> ieu-a-1054", line)
        self.assertIn("b=1.367", line)
        self.assertIn("se=0.1068", line)
        self.assertIn("p=1.79e-37", line)

    def test_the_summary_quotes_the_same_number_as_the_card_beside_it(self):
        """The summary used to print b to five significant figures and the attached card
        to four, about the same row of the same envelope, in the same thread."""
        line = self.line_with("retrieved MR:")
        card = render.render_card(result_a())
        for field in ("b", "se"):
            with self.subTest(field=field):
                value = {"b": 1.3665151455190399, "se": 0.106814322383297}[field]
                self.assertIn(f"{field}={render._effect(value)}", line)
                self.assertIn(f"| {render._effect(value)} |", card)
        self.assertNotIn("b=1.3665", line)

    def test_the_instrument_line_reports_hits_and_the_weak_count(self):
        line = self.line_with("instruments:")
        self.assertIn("ieu-b-5137", line)
        self.assertIn("323 genome-wide significant hit(s) retrieved", line)
        self.assertIn("0 weak (F < 10)", line)

    def test_the_instrument_line_discloses_the_datasets_it_never_opened(self):
        line = self.line_with("instruments:")
        self.assertIn("2 of 22 dataset(s) named by these synonyms were queried", line)

    def test_the_outcome_line_reports_what_the_cap_dropped(self):
        line = self.line_with("outcome datasets:")
        self.assertIn("1 retrieved of 4 matched", line)
        self.assertIn("ebi-a-GCST90038687", line)
        self.assertIn("n=484,598", line)

    def test_the_footer_names_the_ledger_file(self):
        self.assertEqual(
            self.card.split("\n")[-1],
            "every number traceable - 3 ledger entries - urate_gout.ledger.jsonl",
        )

    def test_a_populated_card_carries_no_note_lines(self):
        self.assertNotIn("\nnote:", self.card)

    def line_with(self, prefix):
        matching = [line for line in self.card.split("\n") if line.startswith(prefix)]
        self.assertEqual(len(matching), 1, f"expected exactly one {prefix!r} line")
        return matching[0]


class TestFormatCardStateC(CardMixin, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.card = slack_app.format_card(result_c())

    def test_invariants(self):
        self.assert_card_invariants(self.card)

    def test_the_verdict_line_calls_c_an_evidence_gap(self):
        self.assertIn("*State C - evidence gap*", self.card.split("\n")[0])

    def test_the_empty_mr_arm_is_never_rendered_as_no_effect(self):
        self.assertIn(
            "retrieved MR: no pre-computed MR found in this snapshot "
            f"({NOT_NO_EFFECT})",
            self.card,
        )
        self.assertNotIn("no effect on", self.card)
        self.assertNotIn("no association", self.card)

    def test_the_empty_arms_say_what_was_searched_not_what_is_true(self):
        self.assertIn("instruments: no exposure dataset with a retrieved hit count", self.card)
        self.assertIn("outcome datasets: none named by these synonyms", self.card)

    def test_both_degradation_notes_reach_the_reader(self):
        notes = [line for line in self.card.split("\n") if line.startswith("note:")]
        self.assertEqual(len(notes), 2, notes)
        self.assertIn("metabolite 'zzz'", notes[0])
        self.assertIn("disease 'yyy'", notes[1])
        for note in notes:
            self.assertIn("full resolver (1A) lands separately", note)

    def test_a_c_card_still_ends_with_the_traceability_footer(self):
        self.assertEqual(
            self.card.split("\n")[-1],
            "every number traceable - 3 ledger entries - zzz_yyy.ledger.jsonl",
        )


class TestFormatCardEdges(CardMixin, unittest.TestCase):

    def test_a_runaway_reason_is_truncated_and_the_footer_survives(self):
        card = slack_app.format_card(result_a(reason="x" * 9000))
        self.assert_card_invariants(card)
        self.assertIn("...[truncated]", card)
        self.assertTrue(card.split("\n")[-1].startswith(FOOTER_PREFIX))

    def test_an_error_envelope_is_named_not_silently_dropped(self):
        result = result_a()
        result["envelopes"]["mr"] = envelope(
            "get_mr_result",
            "error",
            {"error": "HTTP 500"},
        )
        card = slack_app.format_card(result)
        self.assert_card_invariants(card)
        self.assertIn("returned an error envelope", card)
        self.assertIn(NOT_NO_EFFECT, card)

    def test_the_dossier_lines_render_when_genes_were_requested(self):
        result = result_a()
        result["envelopes"]["dossier"] = {
            "GLDC": {
                "get_target_disease_evidence": envelope(
                    "get_target_disease_evidence",
                    "ok",
                    {
                        "ensembl":        "ENSG00000178445",
                        "target_disease": {"disease": {"id": "MONDO_0005010"}, "score": 0.718},
                    },
                ),
                "get_known_drugs": envelope(
                    "get_known_drugs",
                    "empty",
                    {"ensembl": "ENSG00000178445", "drugs": []},
                ),
                "get_chembl_modulators": envelope(
                    "get_chembl_modulators",
                    "ok",
                    {
                        "target":         {"target_chembl_id": "CHEMBL2929"},
                        "mechanisms":     [{}] * 9,
                        "activity_count": 2460,
                    },
                ),
                "get_gnomad_constraint": envelope(
                    "get_gnomad_constraint",
                    "ok",
                    {"loeuf": 1.0092138740780154},
                ),
            },
        }
        card = slack_app.format_card(result)
        self.assert_card_invariants(card)
        line = [row for row in card.split("\n") if row.startswith("dossier GLDC:")][0]
        self.assertIn("Open Targets association score 0.718", line)
        self.assertIn("no known drug or clinical candidate retrieved", line)
        self.assertIn("ChEMBL CHEMBL2929 9 mechanism(s) / 2,460 activity record(s)", line)
        self.assertIn("gnomAD LOEUF 1.009", line)

    def test_a_failed_dossier_tool_is_not_rendered_as_a_negative_finding(self):
        """A dead network or a GraphQL error used to read as four confident negatives:
        'this disease is not on the returned association page' when no page was fetched,
        'no exact human single-protein target in ChEMBL' when ChEMBL was never reached."""
        result = result_a()
        result["envelopes"]["dossier"] = {
            "GLDC": {
                name: envelope(
                    name,
                    "error",
                    {"error": "URLError: [Errno 11001] getaddrinfo failed"},
                )
                for name in (
                    "get_target_disease_evidence",
                    "get_known_drugs",
                    "get_chembl_modulators",
                    "get_gnomad_constraint",
                )
            },
        }
        card = slack_app.format_card(result)
        self.assert_card_invariants(card)
        line = [row for row in card.split("\n") if row.startswith("dossier GLDC:")][0]
        self.assertEqual(line.count("error envelope"), 4, line)
        self.assertNotIn("no exact human single-protein target in ChEMBL", line)
        self.assertNotIn("this disease is not on the returned association page", line)
        self.assertNotIn("no known drug or clinical candidate retrieved", line)

    def test_a_gene_open_targets_could_not_resolve_says_so(self):
        """opentargets returns status 'empty' with ensembl=None when no exact symbol
        matched - a 1D hand-off of a gene alias produces exactly that. The source was
        never asked about the disease, so the card must not answer for it."""
        result = result_a()
        result["envelopes"]["dossier"] = {
            "ALIAS1": {
                "get_target_disease_evidence": envelope(
                    "get_target_disease_evidence",
                    "empty",
                    {"gene": "ALIAS1", "ensembl": None, "target_disease": None},
                ),
                "get_known_drugs": envelope(
                    "get_known_drugs",
                    "empty",
                    {"gene": "ALIAS1", "ensembl": None, "count": None, "drugs": []},
                ),
            },
        }
        card = slack_app.format_card(result)
        self.assert_card_invariants(card)
        line = [row for row in card.split("\n") if row.startswith("dossier ALIAS1:")][0]
        self.assertEqual(line.count("gene symbol not resolved"), 2, line)
        self.assertNotIn("this disease is not on the returned association page", line)
        self.assertNotIn("no known drug or clinical candidate retrieved", line)

    def test_an_mr_request_that_failed_half_way_still_reports_the_rows_it_retrieved(self):
        """tools/epigraphdb._failure KEEPS the estimates already retrieved and writes
        them to the ledger. Rendering that as 'nothing found' is the red line."""
        result = result_a()
        failed = result["envelopes"]["mr"]
        failed["status"] = "error"
        failed["data"]["n_estimates"] = 1
        failed["data"]["estimates"] = failed["data"]["estimates"][:1]
        card = slack_app.format_card(result)
        self.assert_card_invariants(card)
        line = [row for row in card.split("\n") if row.startswith("retrieved MR:")][0]
        self.assertIn("failed part way through", line)
        self.assertIn("1 estimate(s) were retrieved before the failure", line)
        self.assertIn("ieu-a-789 -> ieu-a-1054", line)
        self.assertNotIn("no pre-computed MR found", line)

    def test_a_dataset_with_no_recorded_sample_size_is_words_not_a_python_repr(self):
        """OpenGWAS records no sample_size for every finn-b row, and its own caveat
        says so; 'n=None' on a card is a leaked repr, not a sentence."""
        result = result_a()
        result["envelopes"]["outcomes"]["data"]["datasets"].append({
            "id":          "finn-b-M13_GOUT",
            "trait":       "Gout",
            "sample_size": None,
        })
        card = slack_app.format_card(result)
        self.assert_card_invariants(card)
        line = [row for row in card.split("\n") if row.startswith("outcome datasets:")][0]
        self.assertIn("finn-b-M13_GOUT (Gout, sample size not recorded by the source)", line)
        self.assertNotIn("n=None", line)

    def test_a_tool_that_never_ran_is_not_rendered_as_an_empty_source(self):
        """run_pair returns partial envelopes when a stage blew up. An absent tool is
        'did not run', never 'the source holds no record'."""
        result = result_a()
        result["envelopes"] = {}
        card = slack_app.format_card(result)
        self.assert_card_invariants(card)
        self.assertIn("get_mr_result did not run", card)
        self.assertIn("get_mqtl_instruments did not run", card)
        self.assertIn("find_outcome_datasets did not run", card)
        self.assertNotIn("no pre-computed MR found", card)


class TestUserTextIsNeverLiveMarkup(CardMixin, unittest.TestCase):
    """Slack re-parses what the bot posts. A card whose whole pitch is that every number
    can be checked at its source must not be able to carry somebody else's link."""

    def card_for(
        self,
        metabolite,
        disease,
    ):
        result = result_a()
        result["metabolite"] = entity(metabolite, resolved=False)
        result["disease"] = entity(disease, resolved=False)
        result["notes"] = [f"metabolite {metabolite!r}: entity not in the pre-resolved sample."]
        return slack_app.format_card(result)

    def test_a_broadcast_sequence_is_shown_not_fired(self):
        card = self.card_for(
            "<!channel>",
            "gout",
        )
        self.assert_card_invariants(card)
        self.assertNotIn("<!channel>", card)
        self.assertIn("&lt;!channel&gt;", card)

    def test_a_fake_source_link_cannot_be_planted_in_the_card(self):
        card = self.card_for(
            "urate",
            "<https://evil.invalid/x|EpiGraphDB MR-EVE>",
        )
        self.assert_card_invariants(card)
        self.assertNotIn("<https://evil.invalid/x|", card)
        self.assertIn("&lt;https://evil.invalid/x|EpiGraphDB MR-EVE&gt;", card)

    def test_a_degradation_note_is_escaped_too(self):
        card = self.card_for(
            "<@U123>",
            "gout",
        )
        self.assert_card_invariants(card)
        note = [line for line in card.split("\n") if line.startswith("note:")][0]
        self.assertNotIn("<@U123>", note)
        self.assertIn("&lt;@U123&gt;", note)

    def test_an_unresolved_side_is_named_in_the_verdict_line_not_only_in_a_note(self):
        card = self.card_for(
            "zzz",
            "yyy",
        )
        self.assertIn("unresolved name", card.split("\n")[0])


class TestHandlerNeverCrashes(AttachMixin, unittest.TestCase):
    """The handler's two non-happy paths, with a fake `say` and no Slack client."""

    def setUp(self):
        self.say = Say()
        # No client here, so the attachment stage does nothing - but these tests call the
        # whole handler, and a handler that ever starts writing cards must not be able to
        # write a synthetic one into the folder 1G ships its examples from.
        self.use_temp_cards()
        self.original = slack_app.pipeline.run_pair
        self.addCleanup(setattr, slack_app.pipeline, "run_pair", self.original)

    def test_an_unparseable_mention_gets_the_usage_line_in_the_same_thread(self):
        slack_app.handle_mention(
            {"text": "<@U1> hello", "ts": "111.222"},
            self.say,
        )
        self.assertEqual(len(self.say.calls), 1)
        self.assertEqual(self.say.calls[0]["thread_ts"], "111.222")
        self.assertIn("could not read a pair", self.say.calls[0]["text"])

    def test_the_menu_goes_to_the_thread_the_mention_was_in(self):
        """A mention retrieves nothing now: it resolves the pair and offers the menu, so
        a misread pair costs a glance instead of two minutes."""
        slack_app.handle_mention(
            {"text": "<@U1> urate vs gout", "ts": "999.000", "thread_ts": "111.222"},
            self.say,
        )
        self.assertEqual(self.say.calls[0]["thread_ts"], "111.222")
        self.assertTrue(self.say.calls[0]["blocks"], "the menu is a Block Kit message")
        self.assertIn("urate x gout", self.say.calls[0]["text"])

    def test_the_reply_goes_to_the_thread_the_generate_button_was_in(self):
        slack_app.pipeline.run_pair = lambda *args, **kwargs: result_a()
        self.press_generate(None)
        summary = self.summary_call()
        self.assertEqual(summary["thread_ts"], "111.222")
        self.assertIn("*State A - retrieved MR*", summary["text"])

    def test_the_shell_writes_to_its_own_ledger_namespace(self):
        """A run must never be able to truncate one of the frozen demo ledgers: they are
        gitignored, cost ~100 s plus OpenGWAS credits each, and exist only on the machine
        that made them."""
        seen = {}

        def capture(
            metabolite,
            disease,
            **kwargs
        ):
            seen.update(kwargs)
            return result_a()

        slack_app.pipeline.run_pair = capture
        self.press_generate(None)
        self.assertEqual(seen.get("stem_prefix"), slack_app.STEM_PREFIX)
        self.assertEqual(slack_app.STEM_PREFIX, "slack")

    def test_a_failing_stage_becomes_a_polite_reply_naming_that_stage(self):
        def explode(*args, **kwargs):
            raise RuntimeError("xoxb-not-a-real-token-but-it-must-not-be-echoed")

        slack_app.pipeline.run_pair = explode
        self.press_generate(None)
        reply = self.say.calls[-1]["text"]
        self.assertIn("the pipeline stage failed", reply)
        self.assertIn("RuntimeError", reply)
        self.assertNotIn("xoxb-", reply)
        self.assertIn("not a statement about the biology", reply)


class TestSetupPointer(unittest.TestCase):
    """A missing prerequisite means a two-line pointer and exit 1, never a traceback and
    never a token value. Exit 1 is what lets a supervisor or a demo-morning
    `python slack_app.py && echo up` tell "connected" from "never started"."""

    def test_missing_tokens_are_reported_by_name_only(self):
        missing = slack_app.missing_tokens()
        self.assertIsInstance(missing, list)
        for name in missing:
            self.assertIn(name, (slack_app.BOT_TOKEN_VAR, slack_app.APP_TOKEN_VAR))

    def test_the_usage_and_pointer_strings_carry_no_emoji(self):
        for text in (slack_app.USAGE, slack_app.EMPTY_MR):
            self.assertTrue(all(ord(character) < 128 for character in text))

    def test_no_slack_bolt_exits_nonzero_with_a_pointer(self):
        self.addCleanup(setattr, slack_app, "App", slack_app.App)
        slack_app.App = None
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            code = slack_app.main()
        self.assertEqual(code, 1)
        self.assertIn("slack-bolt is not installed", captured.getvalue())

    def test_missing_tokens_exit_nonzero_without_printing_a_value(self):
        self.addCleanup(setattr, slack_app, "App", slack_app.App)
        self.addCleanup(setattr, slack_app, "missing_tokens", slack_app.missing_tokens)
        slack_app.App = object
        slack_app.missing_tokens = lambda: [slack_app.BOT_TOKEN_VAR, slack_app.APP_TOKEN_VAR]
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            code = slack_app.main()
        printed = captured.getvalue()
        self.assertEqual(code, 1)
        self.assertIn(slack_app.BOT_TOKEN_VAR, printed)
        self.assertNotIn("xoxb-y", printed)


class FakePlots:
    """plots.py without matplotlib: it writes a byte or two under the name the real one
    would have used and hands back the path. Every attachment test that is not ABOUT the
    figure uses this, so the fast tests stay fast and the drawing is exercised once,
    against the frozen snapshot, in its own class.

    It carries the module-level names `slack_app.draw_figure` reads as well, because the
    follow-up buttons call the three drawing functions by name rather than going through
    `plot_for_result` - the reader chooses the figure there, not the state."""

    FOREST_SUFFIX = "_mr_forest.png"
    INSTRUMENT_SUFFIX = "_instruments.png"
    TIMELINE_SUFFIX = "_genetic_insight.png"
    FOREST_TITLE = "{metabolite} -> {disease}: retrieved MR estimates"
    INSTRUMENT_TITLE = "{metabolite}: instruments"

    def __init__(
        self,
        folder,
        name    = "urate_gout_mr_forest.png",
        drawn   = True,
        failure = None,
    ):
        self.folder = Path(folder)
        self.name = name
        self.drawn = drawn
        self.failure = failure
        self.calls = []
        self.drawn_kinds = []

    def _write(
        self,
        out_path,
    ):
        if self.failure is not None:
            raise self.failure
        if not self.drawn:
            return None
        written = Path(out_path)
        written.parent.mkdir(
            parents  = True,
            exist_ok = True,
        )
        written.write_bytes(b"\x89PNG\r\n\x1a\n")
        return str(written)

    def plot_for_result(
        self,
        result,
        out_dir = None,
    ):
        self.calls.append(out_dir)
        folder = Path(out_dir) if out_dir else self.folder
        return self._write(folder / self.name)

    def stem_for_result(self, result):
        return "urate_gout"

    def display_name(self, side):
        if isinstance(side, dict):
            return str(side.get("query") or "unknown")
        return str(side or "unknown")

    def plot_forest(
        self,
        env,
        title,
        out_path,
        **kwargs,
    ):
        self.drawn_kinds.append("forest")
        return self._write(out_path)

    def plot_instruments(
        self,
        env,
        title,
        out_path,
        **kwargs,
    ):
        self.drawn_kinds.append("instruments")
        return self._write(out_path)

    def plot_genetic_insight(
        self,
        result,
        out_dir = None,
    ):
        self.drawn_kinds.append("timeline")
        folder = Path(out_dir) if out_dir else self.folder
        return self._write(folder / f"urate_gout{self.TIMELINE_SUFFIX}")


class BlocksMixin:
    """Slack's ceilings, checked on every set of blocks any test in this file builds.

    A block over the limit is not shortened by Slack, it is REFUSED - and the whole
    message goes with it. Every one of these assertions is the difference between a
    reader seeing a shortened card and a reader seeing nothing at all."""

    def assert_block_invariants(self, blocks):
        self.assertIsInstance(blocks, list)
        self.assertTrue(blocks, "a reply with no blocks is a reply nobody sees")
        self.assertLessEqual(len(blocks), 50, "Slack renders at most 50 blocks")

        for block in blocks:
            self.assertIsInstance(block, dict)
            self.assertIn(block.get("type"), ("header", "section", "context"), block)

            text = block.get("text")
            if isinstance(text, dict):
                self.assertIn(text.get("type"), ("mrkdwn", "plain_text"), block)
                self.assertTrue(str(text.get("text") or "").strip(), block)

            fields = block.get("fields")
            if fields is not None:
                self.assertTrue(1 <= len(fields) <= SLACK_MAX_FIELDS, len(fields))
                for field in fields:
                    self.assertEqual(field.get("type"), "mrkdwn", field)
                    self.assertLessEqual(len(field["text"]), SLACK_FIELD_LIMIT, field)

            elements = block.get("elements")
            if elements is not None:
                self.assertTrue(1 <= len(elements) <= SLACK_MAX_CONTEXT_ELEMENTS, elements)
                for element in elements:
                    self.assertEqual(element.get("type"), "mrkdwn", element)

        header = blocks[0]
        self.assertEqual(header["type"], "header")
        self.assertEqual(header["text"]["type"], "plain_text")
        self.assertLessEqual(len(header["text"]["text"]), SLACK_HEADER_LIMIT)
        self.assertIs(header["text"].get("emoji"), False, "the owner's no-emoji rule")

        for text in block_texts(blocks):
            self.assertIsInstance(text, str)
            self.assertTrue(text.strip(), "an empty string is not a block Slack accepts")
            self.assertLessEqual(
                len(text),
                SLACK_BLOCK_LIMIT,
                "no text object may exceed Slack's 3000-character limit",
            )
            self.assertTrue(
                all(ord(character) < 128 for character in text),
                "the blocks must stay plain ASCII: no emojis, no smart punctuation",
            )

        if Block is not None:
            for raw in blocks:
                parsed = Block.parse(raw)
                self.assertIsNotNone(parsed, raw)
                parsed.validate_json()


class TestBlockStructure(BlocksMixin, unittest.TestCase):

    def test_the_four_blocks_are_header_verdict_fields_and_footer(self):
        blocks = slack_app.build_blocks(result_a())
        self.assert_block_invariants(blocks)
        self.assertEqual(
            [block["type"] for block in blocks],
            ["header", "section", "section", "context"],
        )
        self.assertIn("MetaboCausal", blocks[0]["text"]["text"])
        self.assertIn("urate x gout", blocks[0]["text"]["text"])
        self.assertIn("fields", blocks[2])
        self.assertIn("elements", blocks[3])

    def test_every_state_produces_blocks_slack_would_accept(self):
        for result in (result_a(), result_c()):
            with self.subTest(state=result["state"]):
                self.assert_block_invariants(slack_app.build_blocks(result))

    def test_every_evidence_field_is_there_even_when_no_tool_ran(self):
        """A field that disappears when a stage failed tells a reader the arm was never
        relevant. 'get_mr_result did not run' is information and belongs on the card."""
        result = result_a()
        result["envelopes"] = {}
        blocks = slack_app.build_blocks(result)
        self.assert_block_invariants(blocks)
        fields = blocks[2]["fields"]
        self.assertEqual(len(fields), 4)
        self.assertIn("*Retrieved MR*", fields[0]["text"])
        self.assertIn("did not run", fields[0]["text"])
        self.assertIn("*Colocalisation*", fields[1]["text"])
        self.assertIn("*Instruments*", fields[2]["text"])
        self.assertIn("*Outcomes*", fields[3]["text"])

    def test_a_dossier_gene_gets_its_own_field(self):
        result = result_a()
        result["envelopes"]["dossier"] = {
            "GLDC": {
                "get_gnomad_constraint": envelope(
                    "get_gnomad_constraint",
                    "ok",
                    {"loeuf": 1.0092138740780154},
                ),
            },
        }
        blocks = slack_app.build_blocks(result)
        self.assert_block_invariants(blocks)
        field = [row for row in blocks[2]["fields"] if "GLDC" in row["text"]][0]
        self.assertIn("*Dossier GLDC*", field["text"])
        self.assertIn("gnomAD LOEUF 1.009", field["text"])

    def test_a_flood_of_genes_is_capped_at_slack_s_ten_fields_and_says_so(self):
        """Slack refuses a section with more than 10 fields, so 1D handing over 9 genes
        must cap - and a cap that is not printed is the truncation this project bans."""
        result = result_a()
        result["envelopes"]["dossier"] = {
            f"GENE{index}": {
                "get_gnomad_constraint": envelope(
                    "get_gnomad_constraint",
                    "ok",
                    {"loeuf": 0.5},
                ),
            }
            for index in range(9)
        }
        blocks = slack_app.build_blocks(result)
        self.assert_block_invariants(blocks)
        fields = blocks[2]["fields"]
        self.assertEqual(len(fields), SLACK_MAX_FIELDS)
        self.assertIn("showing 5 of 9 gene(s)", fields[-1]["text"])
        self.assertIn("the attached card has every one of them", fields[-1]["text"])

    def test_a_flood_of_forty_genes_still_fits_and_still_says_what_it_dropped(self):
        """1D is allowed to hand over any number of genes. However many arrive, the
        section stays inside Slack's ten fields and the count of the ones not shown is
        on the card - never a slice nobody printed."""
        result = result_a()
        result["envelopes"]["dossier"] = {
            f"GENE{index}": {
                "get_gnomad_constraint": envelope(
                    "get_gnomad_constraint",
                    "ok",
                    {"loeuf": 0.5},
                ),
            }
            for index in range(40)
        }
        blocks = slack_app.build_blocks(result)
        self.assert_block_invariants(blocks)
        fields = blocks[2]["fields"]
        self.assertLessEqual(len(fields), SLACK_MAX_FIELDS)
        shown = len([row for row in fields if row["text"].startswith("*Dossier GENE")])
        self.assertIn(f"showing {shown} of 40 gene(s)", fields[-1]["text"])

    def test_the_footer_names_the_ledger_and_counts_its_entries(self):
        blocks = slack_app.build_blocks(result_a())
        footer = blocks[3]["elements"][0]["text"]
        self.assertTrue(footer.startswith(BLOCK_FOOTER_PREFIX), footer)
        self.assertIn("3 ledger entries", footer)
        self.assertIn("urate_gout.ledger.jsonl", footer)

    def test_a_run_that_wrote_no_ledger_says_that_rather_than_naming_nothing(self):
        result = result_a()
        result["ledger_path"] = ""
        blocks = slack_app.build_blocks(result)
        self.assert_block_invariants(blocks)
        self.assertIn("no ledger written", blocks[3]["elements"][0]["text"])

    def test_the_degradation_notes_reach_the_context_block(self):
        blocks = slack_app.build_blocks(result_c())
        self.assert_block_invariants(blocks)
        notes = [
            element["text"]
            for element in blocks[3]["elements"]
            if element["text"].startswith("note:")
        ]
        self.assertEqual(len(notes), 2, notes)
        self.assertIn("metabolite 'zzz'", notes[0])
        self.assertIn("full resolver (1A) lands separately", notes[0])

    def test_a_flood_of_notes_is_capped_and_the_cap_is_printed(self):
        result = result_c()
        result["notes"] = [f"note number {index}" for index in range(9)]
        blocks = slack_app.build_blocks(result)
        self.assert_block_invariants(blocks)
        elements = blocks[3]["elements"]
        self.assertLessEqual(len(elements), SLACK_MAX_CONTEXT_ELEMENTS)
        self.assertIn("showing 3 of 9 note(s)", elements[-1]["text"])

    def test_a_runaway_classifier_reason_cannot_delete_the_reply(self):
        blocks = slack_app.build_blocks(result_a(reason="x" * 9000))
        self.assert_block_invariants(blocks)
        self.assertIn("...[truncated]", blocks[1]["text"]["text"])

    def test_a_pair_of_maximum_length_names_cannot_delete_the_reply(self):
        result = result_a()
        result["metabolite"] = entity("m" * slack_app.MAX_NAME_CHARS)
        result["disease"] = entity("d" * slack_app.MAX_NAME_CHARS)
        blocks = slack_app.build_blocks(result)
        self.assert_block_invariants(blocks)
        self.assertIn("...[truncated]", blocks[0]["text"]["text"])

    def test_a_clip_never_lands_inside_an_escape_sequence(self):
        """"&am" is not "&amp;": a cut in the middle of an entity shows a reader three
        literal characters where the source had one. 56 is the limit that puts the cut
        exactly on the "&" of the entity below."""
        text = "a" * 40 + "&amp;" + "b" * 40
        clipped = slack_app._clip(text, 56)
        self.assertTrue(clipped.endswith(" ...[truncated]"), clipped)
        body = clipped[: -len(" ...[truncated]")]
        self.assertFalse(body.endswith(("&", "&a", "&am", "&amp")), body)
        self.assertEqual(body, "a" * 40)

    def test_a_string_inside_the_limit_is_left_exactly_as_it_was(self):
        self.assertEqual(slack_app._clip("urate x gout", 150), "urate x gout")

    def test_build_blocks_never_raises_on_a_result_that_is_not_one(self):
        """run_pair can return a partial dict when a stage blew up, and agent.py may one
        day hand this something else entirely. A layout crash must not cost the reply."""
        for junk in (None, {}, {"state": "Z"}, {"envelopes": None}, {"notes": "not a list"}):
            with self.subTest(junk=junk):
                blocks = slack_app.build_blocks(junk)
                self.assert_block_invariants(blocks)


class TestTheCatalogLineCountsGenesAndNotRows(unittest.TestCase):
    """get_gwas_catalog lists a mapped gene once per annotation source, and its own
    caveat - printed verbatim in section 8 of the attached card - says "the row count is
    not a gene count". For urate x gout that is 72 rows naming 14 symbols."""

    def catalog(self, rows) -> dict:
        return envelope(
            "get_gwas_catalog",
            "ok",
            {
                "n_associations_kept":  30,
                "n_associations_total": 40,
                "mapped_genes":         rows,
            },
        )

    def test_both_numbers_are_printed_and_the_gene_count_is_the_distinct_one(self):
        rows = [
            {"gene": "ABCG2", "rsid": "rs1", "source": "Ensembl"},
            {"gene": "ABCG2", "rsid": "rs1", "source": "NCBI"},
            {"gene": "SLC2A9", "rsid": "rs2", "source": "Ensembl"},
            {"gene": "SLC2A9", "rsid": "rs2", "source": "NCBI"},
            {"gene": "", "rsid": "rs3", "source": "NCBI"},
        ]
        line = slack_app._catalog_line(self.catalog(rows))
        self.assertIn("2 distinct mapped gene(s) across 5 annotation row(s)", line)
        self.assertNotIn("5 mapped gene(s)", line)
        self.assertIn("not a classifier input", line)

    def test_the_real_snapshot_reports_fourteen_genes_and_not_seventy_two(self):
        if plots is None:                                # pragma: no cover - import guard
            self.skipTest("matplotlib is not installed")
        result = plots.demo_result(DEMO_A)
        line = slack_app._catalog_line(result["envelopes"]["catalog"])
        self.assertIn("14 distinct mapped gene(s) across 72 annotation row(s)", line)
        self.assertIn("14 distinct", render.render_card(result))


class TestAnUnderflowedPValueNeverReadsAsCertainty(BlocksMixin, unittest.TestCase):
    """tools/epigraphdb.py emits PVAL_ZERO_CAVEAT when a row comes back with pval == 0,
    and its text - printed verbatim in section 8 of the attached card - says: render it
    as "p < 1e-300 (reported 0)", never as p = 0. The summary is the surface that quotes
    that row: `_best_estimate` picks the SMALLEST p, so a zero row is the one selected.
    """

    def zero_p_result(self) -> dict:
        result = result_a()
        result["envelopes"]["mr"]["data"]["estimates"][0]["pval"] = 0.0
        return result

    def test_the_summary_prints_the_bound_and_never_p_equals_zero(self):
        line = [
            line for line in slack_app.format_card(self.zero_p_result()).split("\n")
            if line.startswith("retrieved MR:")
        ][0]
        self.assertIn("<1e-300", line)
        self.assertNotRegex(line, r"p=0(?![.\d])")

    def test_the_block_field_prints_the_bound_and_never_p_equals_zero(self):
        blocks = slack_app.build_blocks(self.zero_p_result())
        self.assert_block_invariants(blocks)
        self.assertIn("&lt;1e-300", blocks[2]["fields"][0]["text"])
        for text in block_texts(blocks):
            self.assertNotRegex(text, r"p=0(?![.\d])")

    def test_the_summary_and_the_card_agree_about_that_p(self):
        result = self.zero_p_result()
        line = [
            line for line in slack_app.format_card(result).split("\n")
            if line.startswith("retrieved MR:")
        ][0]
        self.assertIn(render._pvalue(0.0), line)
        self.assertIn(render._pvalue(0.0), render.render_card(result))

    def test_an_ordinary_small_p_is_scientific_notation_and_not_a_decimal(self):
        """'.3g' rendered 0.0028963 as "0.0029" - not scientific notation, and one
        character away from reading as p=0."""
        result = result_a()
        result["envelopes"]["mr"]["data"]["estimates"][0]["pval"] = 0.0028963
        line = [
            line for line in slack_app.format_card(result).split("\n")
            if line.startswith("retrieved MR:")
        ][0]
        self.assertIn("p=2.90e-03", line)
        self.assertNotIn("0.0029", line)


class TestBlockWording(BlocksMixin, unittest.TestCase):
    """The blocks are held to every rule the mrkdwn card is held to. They are built from
    the same line functions, and these tests are what keeps that true."""

    def test_the_a_pair_prints_a_scientific_p_and_never_zero(self):
        blocks = slack_app.build_blocks(result_a())
        self.assert_block_invariants(blocks)
        mr = blocks[2]["fields"][0]["text"]
        self.assertIn("p=1.79e-37", mr)
        self.assertIn("b=1.367", mr)
        for text in block_texts(blocks):
            self.assertNotIn("0.0 ", text, "a p-value rendered 0.0 reads as certainty")
            self.assertNotIn("p=0", text)

    def test_the_verdict_block_carries_the_state_label_and_the_reason_verbatim(self):
        blocks = slack_app.build_blocks(result_a())
        verdict = blocks[1]["text"]["text"]
        self.assertIn("*State A - retrieved MR*", verdict)
        self.assertIn("State A (retrieved MR): 1 estimate(s) carry", verdict)

    def test_state_c_reads_as_a_gap_and_never_as_a_negative_result(self):
        blocks = slack_app.build_blocks(result_c())
        self.assert_block_invariants(blocks)
        self.assertIn("*State C - evidence gap*", blocks[1]["text"]["text"])
        joined = "\n".join(block_texts(blocks))
        self.assertIn(
            f"no pre-computed MR found in this snapshot ({NOT_NO_EFFECT})",
            joined,
        )
        self.assertNotIn("no effect on", joined)
        self.assertNotIn("no association", joined)

    def test_the_word_computed_only_ever_appears_inside_a_denial(self):
        """This project retrieves published estimates. It fits nothing, so "computed"
        may stand only in "pre-computed" or "not computed"."""
        for result in (result_a(), result_c()):
            for text in block_texts(slack_app.build_blocks(result)):
                start = 0
                while True:
                    found = text.find("computed", start)
                    if found < 0:
                        break
                    before = text[:found]
                    self.assertTrue(
                        before.endswith("pre-") or before.endswith("not "),
                        f"bare 'computed' in: {text}",
                    )
                    start = found + 1

    def test_an_error_envelope_is_named_in_its_field_not_silently_dropped(self):
        result = result_a()
        result["envelopes"]["mr"] = envelope(
            "get_mr_result",
            "error",
            {"error": "HTTP 500"},
        )
        blocks = slack_app.build_blocks(result)
        self.assert_block_invariants(blocks)
        mr = blocks[2]["fields"][0]["text"]
        self.assertIn("returned an error envelope", mr)
        self.assertIn(NOT_NO_EFFECT, mr)

    def test_the_instrument_field_still_discloses_the_datasets_never_opened(self):
        blocks = slack_app.build_blocks(result_a())
        instruments = field_named(blocks, "Instruments")
        self.assertIn("2 of 22 dataset(s) named by these synonyms were queried", instruments)

    def test_a_broadcast_sequence_is_escaped_in_every_block(self):
        result = result_a()
        result["metabolite"] = entity("<!channel>", resolved=False)
        result["notes"] = ["metabolite '<!channel>': entity not in the pre-resolved sample."]
        blocks = slack_app.build_blocks(result)
        self.assert_block_invariants(blocks)
        for text in block_texts(blocks):
            self.assertNotIn("<!channel>", text)
        joined = "\n".join(block_texts(blocks))
        self.assertIn("&lt;!channel&gt;", joined)

    def test_a_fake_source_link_cannot_be_planted_in_a_block(self):
        """The one card whose whole pitch is that every number can be checked at its
        source must not be able to carry somebody else's URL under a source's name."""
        result = result_a()
        result["disease"] = entity("<https://evil.invalid/x|EpiGraphDB MR-EVE>", resolved=False)
        blocks = slack_app.build_blocks(result)
        self.assert_block_invariants(blocks)
        for text in block_texts(blocks):
            self.assertNotIn("<https://evil.invalid/x|", text)
        self.assertIn("&lt;https://evil.invalid/x|", "\n".join(block_texts(blocks)))

    def test_a_trait_string_from_a_source_is_escaped_inside_its_field(self):
        """A dataset trait is a string OpenGWAS wrote, not markup this bot wrote. It
        reaches a field body, so a source that ever serves a link-looking trait must not
        be able to put a clickable link into the one card that promises checkable
        numbers."""
        result = result_a()
        result["envelopes"]["outcomes"]["data"]["datasets"][0]["trait"] = (
            "<https://evil.invalid/x|OpenGWAS>"
        )
        blocks = slack_app.build_blocks(result)
        self.assert_block_invariants(blocks)
        outcomes = field_named(blocks, "Outcomes")
        self.assertNotIn("<https://evil.invalid/x|", outcomes)
        self.assertIn("&lt;https://evil.invalid/x|OpenGWAS&gt;", outcomes)

    def test_a_gene_symbol_is_escaped_inside_its_field_title(self):
        """1D hands over gene symbols; a symbol is a bold field title here, and a title
        is as capable of carrying a broadcast sequence as a body is."""
        result = result_a()
        result["envelopes"]["dossier"] = {
            "<!channel>": {
                "get_gnomad_constraint": envelope(
                    "get_gnomad_constraint",
                    "ok",
                    {"loeuf": 0.5},
                ),
            },
        }
        blocks = slack_app.build_blocks(result)
        self.assert_block_invariants(blocks)
        for text in block_texts(blocks):
            self.assertNotIn("<!channel>", text)
        self.assertIn("&lt;!channel&gt;", field_named(blocks, "Dossier &lt;!channel&gt;"))

    def test_an_unresolved_side_is_marked_in_the_header_and_in_the_verdict(self):
        blocks = slack_app.build_blocks(result_c())
        self.assertIn("unresolved name", blocks[0]["text"]["text"])
        self.assertIn("unresolved name", blocks[1]["text"]["text"])


@unittest.skipUnless(plots is not None, "matplotlib is not installed")
class TestBlocksFromTheFrozenSnapshot(BlocksMixin, unittest.TestCase):
    """The three headline pairs, from the real envelopes cached in
    data/demo_card_inputs.json. No query, no credit, no network."""

    def test_the_demo_snapshot_still_holds_the_three_headline_pairs(self):
        pairs = plots.load_demo(DEMO_PATH)
        for key in (DEMO_A, DEMO_B, DEMO_C):
            self.assertIn(key, pairs)

    def test_each_headline_pair_builds_blocks_slack_would_accept(self):
        for key, state in ((DEMO_A, "A"), (DEMO_B, "B"), (DEMO_C, "C")):
            with self.subTest(pair=key):
                result = demo_result(key)
                self.assertEqual(result["state"], state)
                blocks = slack_app.build_blocks(result)
                self.assert_block_invariants(blocks)
                self.assertIn(f"*State {state} - ", blocks[1]["text"]["text"])

    def test_the_real_urate_gout_estimate_prints_its_real_p_value(self):
        blocks = slack_app.build_blocks(demo_result(DEMO_A))
        self.assert_block_invariants(blocks)
        mr = blocks[2]["fields"][0]["text"]
        self.assertIn("22 estimate(s) retrieved", mr)
        self.assertIn("p=1.79e-37", mr)
        self.assertNotIn("0.0", mr)

    def test_the_real_state_b_pair_reports_instruments_and_an_empty_mr_arm(self):
        blocks = slack_app.build_blocks(demo_result(DEMO_B))
        self.assert_block_invariants(blocks)
        self.assertIn(NOT_NO_EFFECT, field_named(blocks, "Retrieved MR"))
        self.assertIn(
            "49 genome-wide significant hit(s)",
            field_named(blocks, "Instruments"),
        )


class TestTheReplyCarriesBothSurfaces(AttachMixin, unittest.TestCase):
    """A message with blocks still carries the whole mrkdwn card in `text`: that is what
    a notification preview shows, what a client that cannot render blocks shows, and
    what a reader searching the channel later finds."""

    def setUp(self):
        self.say = Say()
        self.folder = self.use_temp_cards()
        self.original = slack_app.pipeline.run_pair
        self.addCleanup(setattr, slack_app.pipeline, "run_pair", self.original)
        slack_app.pipeline.run_pair = lambda *args, **kwargs: result_a()

    def test_the_reply_carries_blocks_and_the_whole_card_as_fallback_text(self):
        self.press_generate(None)
        self.assertEqual(list(self.folder.glob("*")), [], "no client, so nothing written")
        call = self.summary_call()
        self.assertEqual(call["thread_ts"], "111.222")
        self.assertTrue(call["blocks"], "the reply must carry Block Kit blocks")
        self.assertEqual(call["text"], slack_app.format_card(result_a()))
        self.assertTrue(call["text"].strip(), "the fallback text must never be empty")

    def test_a_block_layout_failure_still_posts_the_text_card(self):
        """A bug in the layout must cost a reader the layout, never the numbers."""
        self.addCleanup(setattr, slack_app, "build_blocks", slack_app.build_blocks)

        def explode(result):
            raise ValueError("a layout bug")

        slack_app.build_blocks = explode
        self.press_generate(None)
        call = self.summary_call()
        self.assertIsNone(call["blocks"])
        self.assertIn("*State A - retrieved MR*", call["text"])

    def test_the_usage_reply_is_still_plain_text(self):
        slack_app.handle_mention(
            {"text": "<@U1> hello", "ts": "111.222"},
            self.say,
        )
        self.assertEqual(len(self.say.calls), 1)
        self.assertIsNone(self.say.calls[0]["blocks"])
        self.assertIn("could not read a pair", self.say.calls[0]["text"])


@unittest.skipUnless(SlackApiError is not None, "slack_sdk is not installed")
class TestAttachments(AttachMixin, unittest.TestCase):

    def setUp(self):
        self.folder = self.use_temp_cards()
        self.plots = self.use_fake_plots()

    def test_both_files_go_into_the_thread_the_mention_was_in(self):
        client = Client()
        notes = self.attach(result_a(), client)
        self.assertEqual(notes, [])
        self.assertEqual(len(client.uploads), 2)
        for upload in client.uploads:
            self.assertEqual(upload["channel"], "C0DEMO")
            self.assertEqual(upload["thread_ts"], "111.222")
        self.assertEqual(client.uploads[0]["filename"], "card_urate_gout.md")
        self.assertTrue(client.uploads[1]["filename"].endswith(".png"))

    def test_the_card_on_disk_is_the_full_eleven_section_card(self):
        self.attach(result_a(), Client())
        written = (self.folder / "card_urate_gout.md").read_text(encoding="utf-8")
        self.assertEqual(written, render.render_card(result_a()))
        for number in range(1, 12):
            self.assertIn(f"## {number}. ", written)
        self.assertIn(render.PENDING_REASONING, written)

    def test_the_figure_is_drawn_into_the_same_folder_as_the_card(self):
        self.attach(result_a(), Client())
        self.assertEqual(self.plots.calls, [str(self.folder)])

    def test_nothing_is_uploaded_and_nothing_is_said_without_a_client(self):
        """A direct call, a CLI or a unit test has nowhere to upload to. That is not an
        upload failure and must not become a line in somebody's thread."""
        self.assertEqual(self.attach(result_a(), None), [])
        self.assertEqual(list(self.folder.glob("*")), [])

    def test_an_event_with_no_channel_uploads_nothing(self):
        client = Client()
        self.assertEqual(self.attach(result_a(), client, channel=""), [])
        self.assertEqual(client.uploads, [])

    def test_a_state_with_no_figure_still_uploads_the_card(self):
        self.plots.drawn = False
        client = Client()
        notes = self.attach(result_c(), client)
        self.assertEqual(notes, [])
        self.assertEqual(len(client.uploads), 1)
        self.assertEqual(client.uploads[0]["filename"], "card_zzz_yyy.md")

    def test_missing_scope_becomes_one_line_naming_the_scope_and_the_fix(self):
        client = Client(error=slack_error("missing_scope"))
        notes = self.attach(result_a(), client)
        self.assertEqual(
            notes,
            ["attachments skipped: app needs files:write (reinstall with manifest v2)"],
        )
        self.assertEqual(notes[0], slack_app.MISSING_SCOPE_NOTE)

    def test_missing_scope_is_reported_once_and_the_second_file_is_not_attempted(self):
        """A scope that is not installed will refuse the second file for the same reason.
        Asking again is a wasted call and a second identical line in the thread."""
        client = Client(error=slack_error("missing_scope"))
        notes = self.attach(result_a(), client)
        self.assertEqual(len(notes), 1)
        self.assertEqual(len(client.uploads), 1)

    def test_the_card_and_the_figure_are_on_disk_even_when_the_upload_fails(self):
        """The upload is the delivery, not the evidence. A scope this app is still
        waiting for must not cost the run its artifacts."""
        self.attach(result_a(), Client(error=slack_error("missing_scope")))
        self.assertTrue((self.folder / "card_urate_gout.md").exists())
        self.assertTrue((self.folder / "urate_gout_mr_forest.png").exists())

    def test_any_other_upload_failure_is_reported_in_words_and_never_raised(self):
        client = Client(error=RuntimeError("socket went away"))
        notes = self.attach(result_a(), client)
        self.assertTrue(notes)
        for note in notes:
            self.assertTrue(note.startswith(slack_app.ATTACH_PREFIX), note)
            self.assertIn("RuntimeError", note)
            self.assertIn("not a statement about the biology", note)
            self.assertNotEqual(note, slack_app.MISSING_SCOPE_NOTE)

    def test_a_failure_that_is_not_a_scope_still_tries_the_second_file(self):
        """Only a missing scope is known to refuse the next file too. One flaky call is
        not a reason to withhold the other artifact."""
        client = Client(errors=[RuntimeError("one flaky call"), None])
        notes = self.attach(result_a(), client)
        self.assertEqual(len(client.uploads), 2)
        self.assertEqual(len(notes), 1)
        self.assertIn("the evidence card", notes[0])

    def test_each_failed_artifact_names_itself(self):
        """"the card" and "the figure" are not interchangeable to a reader: a thread that
        says only "attachments skipped" leaves them guessing which one to go and find."""
        client = Client(errors=[RuntimeError("x"), RuntimeError("x")])
        notes = self.attach(result_a(), client)
        self.assertEqual(len(client.uploads), 2)
        self.assertEqual(len(notes), 2, notes)
        self.assertIn("the evidence card", notes[0])
        self.assertIn("the figure", notes[1])

    def test_an_identical_line_is_never_repeated(self):
        client = Client(error=slack_error("missing_scope"))
        notes = self.attach(result_a(), client)
        self.assertEqual(len(notes), len(set(notes)))

    def test_a_renderer_that_throws_costs_the_card_and_nothing_else(self):
        self.addCleanup(setattr, slack_app.render, "render_card", render.render_card)
        slack_app.render.render_card = lambda result: (_ for _ in ()).throw(ValueError("x"))
        client = Client()
        notes = self.attach(result_a(), client)
        self.assertEqual(len(notes), 1)
        self.assertIn("the evidence card", notes[0])
        self.assertEqual(len(client.uploads), 1, "the figure still went up")
        self.assertTrue(client.uploads[0]["filename"].endswith(".png"))

    def test_a_figure_that_cannot_be_drawn_costs_the_figure_and_nothing_else(self):
        self.plots.failure = MemoryError("no room for a canvas")
        client = Client()
        notes = self.attach(result_a(), client)
        self.assertEqual(len(notes), 1)
        self.assertIn("the figure", notes[0])
        self.assertEqual(len(client.uploads), 1, "the card still went up")
        self.assertEqual(client.uploads[0]["filename"], "card_urate_gout.md")

    def test_no_matplotlib_still_uploads_the_card(self):
        self.addCleanup(setattr, slack_app, "plots", slack_app.plots)
        slack_app.plots = None
        client = Client()
        self.assertEqual(self.attach(result_a(), client), [])
        self.assertEqual(len(client.uploads), 1)

    def test_every_upload_keyword_exists_on_the_real_web_client(self):
        """The fake client takes **kwargs, so it would swallow a keyword slack_sdk does
        not have and the mistake would only show up in a live thread. This is the one
        test that reads the real signature."""
        from slack_sdk.web.client import WebClient

        accepted = set(inspect.signature(WebClient.files_upload_v2).parameters)
        client = Client()
        self.attach(result_a(), client)
        self.assertTrue(client.uploads)
        for upload in client.uploads:
            for keyword in upload:
                self.assertIn(keyword, accepted, keyword)

    def test_the_note_quotes_an_exception_type_never_a_slack_error_body(self):
        """A Slack error body is not something this shell re-posts: it is the one string
        in the failure path that could carry something a reader should not see."""
        note = slack_app._upload_note(
            RuntimeError("xoxb-not-a-real-token-but-it-must-not-be-echoed"),
            "the evidence card",
        )
        self.assertNotIn("xoxb-", note)
        self.assertIn("RuntimeError", note)

    def test_the_slack_error_code_is_read_off_a_response_object_too(self):
        """slack_sdk hands back a SlackResponse, not a dict. Reading it by `.get` with
        `.data` behind it means neither shape can hide a missing_scope."""

        class Response:
            def __init__(self, data):
                self.data = data

        class Failure(Exception):
            def __init__(self, response):
                self.response = response

        self.assertEqual(
            slack_app._error_code(Failure(Response({"error": "missing_scope"}))),
            "missing_scope",
        )
        self.assertEqual(slack_app._error_code(RuntimeError("no response at all")), "")


@unittest.skipUnless(plots is not None, "matplotlib is not installed")
@unittest.skipUnless(SlackApiError is not None, "slack_sdk is not installed")
class TestAttachmentsDrawForReal(AttachMixin, unittest.TestCase):
    """The one class that draws with matplotlib, against the frozen snapshot, so the
    figure that is uploaded is the figure plots.py actually produces."""

    def setUp(self):
        self.folder = self.use_temp_cards()

    def test_state_a_attaches_the_card_and_the_forest_plot(self):
        client = Client()
        notes = self.attach(demo_result(DEMO_A), client)
        self.assertEqual(notes, [])
        names = [upload["filename"] for upload in client.uploads]
        self.assertEqual(names, ["card_urate_gout.md", "urate_gout_mr_forest.png"])
        for name in names:
            self.assertTrue((self.folder / name).exists())
        self.assertGreater((self.folder / names[1]).stat().st_size, 1000)

    def test_state_b_attaches_the_card_and_the_instrument_chart(self):
        client = Client()
        notes = self.attach(demo_result(DEMO_B), client)
        self.assertEqual(notes, [])
        names = [upload["filename"] for upload in client.uploads]
        self.assertEqual(len(names), 2)
        self.assertTrue(names[1].endswith("_instruments.png"), names[1])

    def test_state_c_attaches_the_card_and_no_figure(self):
        """Nothing was retrieved to draw. An empty figure would be a picture of a gap
        presented as a result."""
        client = Client()
        notes = self.attach(demo_result(DEMO_C), client)
        self.assertEqual(notes, [])
        names = [upload["filename"] for upload in client.uploads]
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].endswith(".md"), names[0])
        self.assertEqual(list(self.folder.glob("*.png")), [])

    def test_the_uploaded_file_title_shows_the_pair_without_markup(self):
        client = Client()
        self.attach(demo_result(DEMO_A), client)
        self.assertIn("urate x gout", client.uploads[0]["title"])
        for upload in client.uploads:
            self.assertNotIn("&lt;", upload["title"])
            self.assertNotIn("<", upload["title"])


@unittest.skipUnless(SlackApiError is not None, "slack_sdk is not installed")
class TestHandlerAttachments(AttachMixin, unittest.TestCase):
    """The whole handler with a fake `say` and a fake client: summary first, then the
    files, then - only if something failed - one line saying what and why."""

    def setUp(self):
        self.say = Say()
        self.folder = self.use_temp_cards()
        self.plots = self.use_fake_plots()
        self.original = slack_app.pipeline.run_pair
        self.addCleanup(setattr, slack_app.pipeline, "run_pair", self.original)
        slack_app.pipeline.run_pair = lambda *args, **kwargs: result_a()

    def mention(self, client):
        """The generate button, which is where the run happens now. The mention itself
        only posts the menu - `TestTheGuidedMenu` covers that."""
        self.press_generate(client)

    def test_the_summary_goes_out_first_and_the_files_follow_it(self):
        client = Client()
        self.mention(client)
        self.assertEqual(
            [call["text"].split()[0] for call in self.say.calls][:1],
            ["跑起来了"],
            "the thread is told a run started before it waits a minute for it",
        )
        self.assertEqual(len(self.say.calls), 3, "running line, summary, follow-up buttons")
        self.assertTrue(self.summary_call()["blocks"])
        self.assertEqual(len(client.uploads), 2)

    def test_missing_scope_leaves_the_summary_standing_and_adds_one_line(self):
        client = Client(error=slack_error("missing_scope"))
        self.mention(client)
        self.assertTrue(self.summary_call()["blocks"], "the numbers went out anyway")
        notes = [call for call in self.say.calls if call["text"] == slack_app.MISSING_SCOPE_NOTE]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["thread_ts"], "111.222")
        self.assertIsNone(notes[0]["blocks"])

    def test_an_upload_that_explodes_never_crashes_the_handler(self):
        """Two files failed, so both are named - in ONE message. A thread gets one
        explanation, not one line per file, and never the generic stage-failure reply."""
        client = Client(error=OSError("the socket closed"))
        self.mention(client)
        notes = [
            call["text"] for call in self.say.calls
            if str(call["text"]).startswith(slack_app.ATTACH_PREFIX)
        ]
        self.assertEqual(len(notes), 1, self.say.calls)
        self.assertIn("the evidence card", notes[0])
        self.assertIn("the figure", notes[0])
        self.assertNotIn(
            "could not finish",
            "\n".join(str(call["text"]) for call in self.say.calls),
        )

    def test_a_handler_with_no_client_posts_the_summary_and_stays_quiet(self):
        self.mention(None)
        self.assertEqual(len(self.say.calls), 3, "running line, summary, follow-up buttons")
        self.assertTrue(self.summary_call()["blocks"])
        self.assertEqual(list(self.folder.glob("*")), [])

    def test_a_failure_after_the_reply_never_claims_nothing_was_retrieved(self):
        """attach_artifacts does not raise, but the `say` that posts its note can. Once
        the summary is in the thread, "Nothing was retrieved for this pair" is false -
        and a false sentence on this card is worse than the failure it is reporting."""
        self.addCleanup(setattr, slack_app, "attach_artifacts", slack_app.attach_artifacts)

        def explode(*args, **kwargs):
            raise RuntimeError("the socket closed while uploading")

        slack_app.attach_artifacts = explode
        self.mention(Client())
        reply = self.say.calls[-1]["text"]
        self.assertIn("the attachments stage failed", reply)
        self.assertIn("The summary above still stands", reply)
        self.assertNotIn("Nothing was retrieved", reply)
        self.assertIn("not a statement about the biology", reply)

    def test_a_pipeline_failure_still_reaches_the_attachment_stage_of_nothing(self):
        """A run that never produced a result has nothing to attach, and the failure
        reply is the only thing that should go out."""
        def explode(*args, **kwargs):
            raise RuntimeError("boom")

        slack_app.pipeline.run_pair = explode
        client = Client()
        self.mention(client)
        self.assertEqual(len(self.say.calls), 2, "the running line, then the failure")
        self.assertIn("the pipeline stage failed", self.say.calls[-1]["text"])
        self.assertIn("Nothing was retrieved for this pair", self.say.calls[-1]["text"])
        self.assertEqual(client.uploads, [])

    def test_a_failure_after_the_run_never_says_nothing_was_retrieved(self):
        """A Slack rate limit, a dropped socket or an invalid_blocks rejection happens
        AFTER run_pair has written its ledger. Telling the thread that nothing was
        retrieved is the one sentence this project treats as a red line."""
        class Refuses(Say):
            def __call__(self, **kwargs):
                if kwargs.get("blocks") or kwargs.get("text", "").startswith("*State"):
                    raise RuntimeError("ratelimited")
                return super().__call__(**kwargs)

        self.say = Refuses()
        self.mention(Client())
        reply = self.say.calls[-1]["text"]
        self.assertIn("the reply stage failed", reply)
        self.assertNotIn("Nothing was retrieved", reply)
        self.assertIn("The retrieval finished and its ledger is on disk", reply)
        self.assertIn("urate_gout.ledger.jsonl", reply)

    def test_slack_refusing_the_blocks_falls_back_to_the_text_card(self):
        """build_blocks succeeding and Slack REJECTING the blocks are different failures.
        The second used to lose the whole card and then print the false sentence."""
        class RefusesBlocks(Say):
            def __call__(self, **kwargs):
                if kwargs.get("blocks"):
                    raise RuntimeError("invalid_blocks")
                return super().__call__(**kwargs)

        self.say = RefusesBlocks()
        self.mention(Client())
        card = self.summary_call()
        self.assertIsNone(card["blocks"])
        self.assertIn("*State A - retrieved MR*", card["text"])
        self.assertNotIn(
            "could not finish",
            "\n".join(str(call["text"]) for call in self.say.calls),
        )
        self.assertIn(
            slack_app.FOLLOW_UP_PROMPT,
            "\n".join(str(call["text"]) for call in self.say.calls),
            "Slack refusing the buttons costs the buttons, not the offer",
        )

    def test_the_ledger_is_snapshotted_inside_the_run_lock(self):
        """Two mentions of the same pair share one stem, so the second run truncates the
        file the first is about to render section 11 from. The lines are read while the
        run still owns them and carried in the result."""
        seen = {}
        original = slack_app.render.snapshot_ledger
        self.addCleanup(setattr, slack_app.render, "snapshot_ledger", original)

        def watched(result):
            seen["locked"] = slack_app._RUN_LOCK.locked()
            return [{"tool": "get_mr_result", "status": "ok"}]

        slack_app.render.snapshot_ledger = watched

        captured = {}
        real_attach = slack_app.attach_artifacts
        self.addCleanup(setattr, slack_app, "attach_artifacts", real_attach)

        def capture(result, *args, **kwargs):
            captured["result"] = result
            return []

        slack_app.attach_artifacts = capture
        self.mention(Client())
        self.assertTrue(seen.get("locked"), "the ledger was read after the lock was let go")
        self.assertEqual(
            captured["result"][render.LEDGER_ENTRIES_KEY],
            [{"tool": "get_mr_result", "status": "ok"}],
        )


class InteractiveMixin:
    """Slack's ceilings for the interactive blocks.

    A separate checker from `assert_block_invariants` on purpose: the menu and the buttons
    use block types the summary never does (`actions`), and their labels are BILINGUAL, so
    the summary's plain-ASCII rule cannot apply to them. The no-emoji rule still does - it
    is the owner's rule for everything this project writes, and Chinese is not an emoji.
    """

    OPTION_LIMIT = 75
    BUTTON_LIMIT = 75
    VALUE_LIMIT = 2000

    def assert_no_emoji(self, text):
        for character in str(text):
            self.assertFalse(
                0x1F300 <= ord(character) <= 0x1FAFF or 0x2600 <= ord(character) <= 0x27BF,
                f"the owner's no-emoji rule: {character!r} in {text!r}",
            )

    def assert_interactive_blocks(self, blocks):
        self.assertIsInstance(blocks, list)
        self.assertTrue(blocks)
        self.assertLessEqual(len(blocks), 50, "Slack renders at most 50 blocks")

        for block in blocks:
            self.assertIn(block.get("type"), ("section", "actions", "context"), block)

            text = block.get("text")
            if isinstance(text, dict):
                self.assertLessEqual(len(text["text"]), SLACK_BLOCK_LIMIT, block)
                self.assert_no_emoji(text["text"])

            elements = list(block.get("elements") or [])
            accessory = block.get("accessory")
            if accessory is not None:
                elements.append(accessory)

            for element in elements:
                if element.get("type") == "button":
                    label = element["text"]["text"]
                    self.assertLessEqual(len(label), self.BUTTON_LIMIT, label)
                    self.assertIs(element["text"].get("emoji"), False, element)
                    self.assertLessEqual(len(element["value"]), self.VALUE_LIMIT, element)
                    self.assert_no_emoji(label)
                if element.get("type") == "checkboxes":
                    options = element["options"]
                    self.assertTrue(1 <= len(options) <= 10, options)
                    for option in options:
                        self.assertLessEqual(
                            len(option["text"]["text"]),
                            self.OPTION_LIMIT,
                            option,
                        )
                        self.assertLessEqual(len(option["value"]), self.OPTION_LIMIT, option)
                        if option.get("description"):
                            self.assertLessEqual(
                                len(option["description"]["text"]),
                                self.OPTION_LIMIT,
                                option,
                            )
                        self.assert_no_emoji(option["text"]["text"])

        if Block is not None:
            for raw in blocks:
                parsed = Block.parse(raw)
                self.assertIsNotNone(parsed, raw)
                parsed.validate_json()


class TestTheGuidedMenu(InteractiveMixin, AttachMixin, unittest.TestCase):
    """The mention now offers a menu instead of spending two minutes on an unasked-for
    card. Every box starts ticked, so the default press is still the whole card."""

    def setUp(self):
        self.say = Say()
        self.use_temp_cards()
        self.original = slack_app.pipeline.run_pair
        self.addCleanup(setattr, slack_app.pipeline, "run_pair", self.original)
        slack_app.pipeline.run_pair = lambda *args, **kwargs: result_a()

    def mention(self, text="<@U1> urate vs gout"):
        slack_app.handle_mention(
            {"text": text, "ts": "111.222", "channel": "C0DEMO"},
            self.say,
        )
        return self.say.calls[0]

    def test_the_four_arm_lines_are_bilingual_chinese_first_english_after_the_slash(self):
        """The exact lines the room reads. Chinese first, English after the slash, and the
        database in parentheses - a name is what makes an arm checkable."""
        self.assertEqual(
            [slack_app.menu_line(arm) for arm in slack_app.MENU_ARMS],
            [
                "现成 MR 因果估计 / retrieved MR (EpiGraphDB)",
                "工具变量可行性 / instruments (OpenGWAS)",
                "疾病关联背景 / associations (GWAS Catalog, note: slow ~100s)",
                "effector 基因与成药档案 / genes & target dossier "
                "(atlas + Open Targets/ChEMBL/gnomAD)",
            ],
        )

    def test_every_box_starts_ticked(self):
        blocks = slack_app.build_menu_blocks("urate", "gout")
        checkboxes = blocks[1]["accessory"]
        self.assertEqual(
            [option["value"] for option in checkboxes["initial_options"]],
            [option["value"] for option in checkboxes["options"]],
        )
        self.assertEqual(
            [option["value"] for option in checkboxes["options"]],
            list(slack_app.DEFAULT_ARMS),
        )

    def test_the_menu_is_blocks_slack_would_accept(self):
        self.assert_interactive_blocks(slack_app.build_menu_blocks("urate", "gout"))

    def test_the_long_gene_arm_keeps_its_database_list_in_the_description(self):
        """Slack refuses an option whose text is over 75 characters - and refuses the
        WHOLE message with it. The parenthetical is what names the four databases, so it
        moves to the description rather than being cut."""
        genes = slack_app.build_menu_blocks("urate", "gout")[1]["accessory"]["options"][3]
        self.assertIn("genes & target dossier", genes["text"]["text"])
        self.assertIn("Open Targets/ChEMBL/gnomAD", genes["description"]["text"])
        self.assertNotIn("pQTL cross-check", genes["description"]["text"])

    def test_the_generate_button_carries_the_pair_and_round_trips(self):
        value = slack_app.build_menu_blocks("urate", "gout")[2]["elements"][0]["value"]
        self.assertEqual(slack_app.decode_pair_value(value), ("urate", "gout"))

    def test_a_payload_this_shell_did_not_write_is_refused_rather_than_guessed_at(self):
        for value in (None, "", "urate|gout", "{}", '{"m": "urate"}', "[1, 2]", "x" * 4000):
            with self.subTest(value=value):
                self.assertIsNone(slack_app.decode_pair_value(value))

    def test_the_menu_says_what_1a_made_of_the_two_names(self):
        """A misread pair must cost a glance, not two minutes. urate and gout are in the
        frozen sample, so this resolves offline."""
        call = self.mention()
        text = call["blocks"][0]["text"]["text"]
        self.assertIn("CHEBI:", text)
        self.assertIn("MONDO:", text)
        self.assertIn("frozen 1A sample", text)
        self.assertIn("spelling(s)", text)

    def test_the_mention_retrieves_nothing(self):
        """Not one request until somebody presses the button. run_pair is replaced with a
        function that would fail the test if it were called."""
        def refuse(*args, **kwargs):
            raise AssertionError("the mention must not run the pipeline")

        slack_app.pipeline.run_pair = refuse
        self.mention()
        self.assertEqual(len(self.say.calls), 1)

    def test_a_name_that_looks_like_markup_comes_back_escaped(self):
        """`parse_pair` drops angle brackets on the way in, so a name can only reach here
        carrying markup if something upstream changes. The menu escapes it anyway: this is
        the message a mention makes the bot post, and it is built from the asker's text."""
        blocks = slack_app.build_menu_blocks("<!channel>", "<https://evil.invalid/x|gout>")
        joined = "\n".join(block_texts(blocks))
        self.assertNotIn("<!channel>", joined)
        self.assertNotIn("<https://evil.invalid/x|", joined)
        self.assertIn("channel", joined)
        self.assert_interactive_blocks(blocks)

    def test_the_fallback_text_carries_the_same_menu(self):
        """A notification preview and a client that cannot render blocks still show the
        four arms and what the pair resolved to."""
        call = self.mention()
        for arm in slack_app.MENU_ARMS:
            self.assertIn(slack_app.menu_line(arm), call["text"])

    def test_a_resolver_that_is_down_still_gets_a_menu(self):
        """1A being unreachable is not a reason to refuse the pair: the menu says the run
        will match on the raw strings, which is a gap in resolution and not a statement
        about the entity. This is also what keeps the suite offline - the two names here
        are not in the frozen sample, so the live resolver is the only other path."""
        self.addCleanup(setattr, slack_app.ids, "resolve_ids", slack_app.ids.resolve_ids)

        def explode(*args, **kwargs):
            raise RuntimeError("OLS4 is down")

        slack_app.ids.resolve_ids = explode
        preview = slack_app.resolve_preview("zzz", "yyy")
        self.assertFalse(preview["metabolite"]["resolved"])
        self.assertFalse(preview["disease"]["resolved"])

        lines = slack_app.preview_lines(preview)
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertIn("no id resolved", line)
            self.assertIn("not a statement about the entity", line)
        self.assert_interactive_blocks(slack_app.build_menu_blocks("zzz", "yyy", preview))

    def test_a_menu_that_cannot_be_built_is_a_polite_line_and_not_a_traceback(self):
        self.addCleanup(setattr, slack_app, "build_menu_blocks", slack_app.build_menu_blocks)

        def explode(*args, **kwargs):
            raise ValueError("a layout bug")

        slack_app.build_menu_blocks = explode
        reply = self.mention()["text"]
        self.assertIn("the menu stage failed", reply)
        self.assertIn("No evidence arm has run", reply)
        self.assertIn("not a statement about the biology", reply)

    def test_an_unparseable_mention_still_gets_the_usage_line(self):
        slack_app.handle_mention(
            {"text": "<@U1> hello", "ts": "111.222"},
            self.say,
        )
        self.assertIsNone(self.say.calls[0]["blocks"])
        self.assertIn("could not read a pair", self.say.calls[0]["text"])


class TestTheArmsActuallyChangeTheRun(AttachMixin, unittest.TestCase):
    """A tick is a promise about what will be retrieved. Two arms can be switched off and
    two cannot, and the two that cannot say so out loud."""

    def setUp(self):
        self.say = Say()
        self.use_temp_cards()
        self.use_fake_plots()
        self.seen = {}
        self.original = slack_app.pipeline.run_pair
        self.addCleanup(setattr, slack_app.pipeline, "run_pair", self.original)

        def capture(metabolite, disease, **kwargs):
            self.seen.update(kwargs)
            return result_a()

        slack_app.pipeline.run_pair = capture

    def test_a_payload_with_no_checkbox_state_runs_the_menu_s_defaults(self):
        """The restart case: Slack sends a button press whose message this process never
        built. Running nothing would be the worst answer to a press of `generate`."""
        self.assertEqual(slack_app.selected_arms({}), set(slack_app.DEFAULT_ARMS))
        self.press_generate(None, arms=None)
        self.assertIs(self.seen["skip_catalog"], False)
        self.assertIs(self.seen["skip_genes"], False)

    def test_an_empty_selection_is_a_real_choice_and_is_honoured(self):
        self.assertEqual(slack_app.selected_arms(generate_body(arms=[])), set())
        self.press_generate(None, arms=[])
        self.assertIs(self.seen["skip_catalog"], True)
        self.assertIs(self.seen["skip_genes"], True)

    def test_the_catalog_box_is_the_only_thing_that_turns_the_100_second_arm_on(self):
        self.press_generate(None, arms=["mr", "instruments"])
        self.assertIs(self.seen["skip_catalog"], True)
        self.press_generate(None, arms=["mr", "instruments", "catalog"])
        self.assertIs(self.seen["skip_catalog"], False)

    def test_the_genes_box_is_what_turns_the_atlas_dossier_stage_on(self):
        self.press_generate(None, arms=["mr"])
        self.assertIs(self.seen["skip_genes"], True)
        self.press_generate(None, arms=["mr", "genes"])
        self.assertIs(self.seen["skip_genes"], False)

    def test_unticking_a_locked_arm_is_refused_in_words_rather_than_ignored(self):
        """The A/B/C state is a pure function of the MR and instrument envelopes. A run
        without them would still print a state, and that state would rest on nothing."""
        self.press_generate(None, arms=["catalog"])
        preamble = self.say.calls[0]["text"]
        self.assertIn(slack_app.LOCKED_ARMS_NOTE, preamble)
        self.assertIn("cannot be switched off", preamble)
        self.assertEqual(slack_app.overruled_arms(["catalog"]), ["mr", "instruments"])

    def test_nothing_is_said_about_locked_arms_when_nobody_unticked_one(self):
        self.press_generate(None, arms=list(slack_app.DEFAULT_ARMS))
        self.assertNotIn(slack_app.LOCKED_ARMS_NOTE, self.say.calls[0]["text"])

    def test_the_thread_is_told_a_run_started_before_it_waits_for_one(self):
        self.press_generate(None, arms=["mr", "instruments", "catalog"])
        first = self.say.calls[0]["text"]
        self.assertIn("running urate x gout", first)
        self.assertIn("about 2 minutes", first, "the catalog arm is the slow one")
        self.assertIn("现成 MR 因果估计", first)


class TestTheFollowUpButtons(InteractiveMixin, AttachMixin, unittest.TestCase):
    """A figure is drawn when somebody asks for it, once, and a figure with nothing to
    draw answers in words instead of posting an empty axis."""

    def setUp(self):
        self.say = Say()
        self.folder = self.use_temp_cards()
        self.plots = self.use_fake_plots()
        self.addCleanup(slack_app.forget_runs)
        slack_app.forget_runs()
        self.original = slack_app.pipeline.run_pair
        self.addCleanup(setattr, slack_app.pipeline, "run_pair", self.original)
        slack_app.pipeline.run_pair = lambda *args, **kwargs: result_a()

    def texts(self) -> str:
        return "\n".join(str(call["text"]) for call in self.say.calls)

    def test_the_three_explainers_are_bilingual_and_say_when_each_figure_applies(self):
        lines = {kind: explainer for kind, _label, explainer in slack_app.FOLLOW_UPS}
        self.assertEqual(
            lines["forest"],
            "每条检索到的 MR 估计的方向与不确定度 / direction & uncertainty of each retrieved "
            "estimate (State A only)",
        )
        self.assertEqual(
            lines["instruments"],
            "有多少强遗传工具 / how many strong instruments (state B focus)",
        )
        self.assertEqual(
            lines["timeline"],
            "基因上的药：遗传证据哪年出现 vs 临床哪年定论 / when genetics spoke vs when the "
            "clinic decided (needs the genes arm)",
        )
        self.assertEqual(lines["skip"], "")

    def test_the_buttons_are_blocks_slack_would_accept(self):
        self.assert_interactive_blocks(slack_app.build_follow_up_blocks("111.222"))

    def test_every_button_carries_its_own_thread_and_round_trips(self):
        blocks = slack_app.build_follow_up_blocks("111.222")
        values = []
        for block in blocks:
            accessory = block.get("accessory")
            if accessory:
                values.append(accessory["value"])
            for element in block.get("elements") or []:
                values.append(element["value"])
        self.assertEqual(
            [slack_app.decode_figure_value(value) for value in values],
            [("forest", "111.222"), ("instruments", "111.222"),
             ("timeline", "111.222"), ("skip", "111.222")],
        )

    def test_a_value_this_shell_did_not_write_decodes_to_nothing(self):
        for value in (None, "", "forest", "|111.222", "forest|", "nope|111.222"):
            with self.subTest(value=value):
                self.assertEqual(slack_app.decode_figure_value(value), (None, None))

    def test_the_buttons_are_posted_after_the_card_and_the_run_is_remembered(self):
        self.press_generate(Client())
        last = self.say.calls[-1]
        self.assertTrue(last["blocks"])
        self.assertIn(slack_app.FOLLOW_UP_PROMPT, last["text"])
        self.assertIsNotNone(slack_app.recall_run("111.222"))

    def test_a_button_draws_the_figure_and_uploads_it_into_the_thread(self):
        client = Client()
        self.press_generate(client)
        uploads_before = len(client.uploads)
        self.press_figure("timeline", client)
        self.assertEqual(self.plots.drawn_kinds[-1], "timeline")
        self.assertEqual(len(client.uploads), uploads_before + 1)
        self.assertEqual(client.uploads[-1]["thread_ts"], "111.222")
        self.assertTrue(client.uploads[-1]["filename"].endswith("_genetic_insight.png"))

    def test_a_second_click_says_already_generated_and_uploads_nothing_twice(self):
        client = Client()
        self.press_generate(client)
        self.press_figure("timeline", client)
        uploads = len(client.uploads)
        self.press_figure("timeline", client)
        self.assertEqual(len(client.uploads), uploads, "a double click is one figure")
        self.assertIn("already generated", self.say.calls[-1]["text"])
        self.assertIn("genetic-insight timeline", self.say.calls[-1]["text"])

    def test_the_figure_the_run_already_posted_is_not_posted_a_second_time(self):
        """State A means the run itself attached the forest. Its button has nothing left
        to add, so it says so rather than putting the same PNG in the thread twice."""
        client = Client()
        self.press_generate(client)
        uploads = len(client.uploads)
        self.press_figure("forest", client)
        self.assertEqual(len(client.uploads), uploads)
        self.assertIn("already generated", self.say.calls[-1]["text"])
        self.assertNotIn("forest", self.plots.drawn_kinds)

    def test_a_state_figure_that_was_never_drawn_is_not_claimed(self):
        """A State A run whose MR envelope had no drawable row posted no forest, and
        "already generated" would then be a false sentence about a missing figure."""
        self.plots.drawn = False
        client = Client()
        self.press_generate(client)
        self.plots.drawn = True
        self.press_figure("forest", client)
        self.assertEqual(self.plots.drawn_kinds[-1], "forest")
        self.assertEqual(len(client.uploads), 2, "the card, then the figure asked for")

    def test_the_timeline_button_says_why_when_there_is_nothing_to_draw(self):
        """The genes arm off, or a dossier with no dated trial, means no timeline - and
        the answer is the reason, never a lane drawn on a guessed year."""
        self.press_generate(Client())
        self.plots.drawn = False
        self.press_figure("timeline", Client())
        reply = self.say.calls[-1]["text"]
        self.assertIn("no 时间线 / no timeline", reply)
        self.assertIn("genes arm must be ticked", reply)
        self.assertIn("guessed year", reply)

    def test_a_figure_with_nothing_to_draw_can_be_asked_for_again(self):
        """Nothing was generated, so "already generated" would be a lie."""
        self.press_generate(Client())
        self.plots.drawn = False
        self.press_figure("timeline", Client())
        self.press_figure("timeline", Client())
        self.assertNotIn("already generated", self.texts())

    def test_a_drawing_failure_is_words_and_the_button_still_works_afterwards(self):
        self.press_generate(Client())
        self.plots.failure = OSError("cards/ is read-only")
        self.press_figure("instruments", Client())
        self.assertIn("could not be drawn", self.say.calls[-1]["text"])
        self.assertIn("not a statement about the biology", self.say.calls[-1]["text"])
        self.plots.failure = None
        client = Client()
        self.press_figure("instruments", client)
        self.assertEqual(len(client.uploads), 1, "the claim was given back")

    def test_skip_changes_nothing_and_says_so(self):
        self.press_generate(Client())
        client = Client()
        self.press_figure("skip", client)
        self.assertIn("skipped", self.say.calls[-1]["text"])
        self.assertEqual(client.uploads, [])

    def test_a_run_the_shell_no_longer_remembers_says_so_rather_than_failing(self):
        self.press_figure("forest", Client(), thread_ts="999.999")
        reply = self.say.calls[-1]["text"]
        self.assertIn("no longer in memory", reply)
        self.assertIn("Mention me with the pair again", reply)

    def test_an_upload_failure_on_a_figure_costs_one_line_and_nothing_else(self):
        self.press_generate(Client())
        self.press_figure("timeline", Client(error=slack_error("missing_scope")))
        self.assertEqual(self.say.calls[-1]["text"], slack_app.MISSING_SCOPE_NOTE)

    def test_a_button_payload_from_nowhere_is_ignored_in_silence(self):
        """An action this shell did not write is text that arrived from outside the
        process. It gets no reply and no run."""
        before = len(self.say.calls)
        slack_app.handle_figure(
            Ack(),
            {"actions": [{"value": "nonsense"}], "container": {"channel_id": "C0DEMO"}},
            self.say,
        )
        self.assertEqual(len(self.say.calls), before)


class TestPerThreadState(unittest.TestCase):
    """A Socket Mode worker runs for days. An unbounded dict of results - each holding
    every envelope of a run - is a slow leak, so it is capped and evicted oldest first."""

    def setUp(self):
        slack_app.forget_runs()
        self.addCleanup(slack_app.forget_runs)

    def test_a_run_comes_back_by_its_thread(self):
        slack_app.remember_run("111.222", result_a())
        self.assertEqual(slack_app.recall_run("111.222")["state"], "A")
        self.assertIsNone(slack_app.recall_run("333.444"))

    def test_the_oldest_thread_is_evicted_past_the_cap(self):
        cap = slack_app.MAX_THREAD_STATE
        for index in range(cap + 1):
            slack_app.remember_run(f"{index}.000", result_a())
        self.assertEqual(len(slack_app._THREAD_STATE), cap)
        self.assertIsNone(slack_app.recall_run("0.000"), "the oldest went first")
        self.assertIsNotNone(slack_app.recall_run(f"{cap}.000"))

    def test_re_running_a_thread_refreshes_it_rather_than_duplicating_it(self):
        slack_app.remember_run("111.222", result_a())
        slack_app.claim_figure("111.222", "forest")
        slack_app.remember_run("111.222", result_c())
        self.assertEqual(len(slack_app._THREAD_STATE), 1)
        self.assertEqual(slack_app.recall_run("111.222")["state"], "C")
        self.assertTrue(
            slack_app.claim_figure("111.222", "forest"),
            "a new run of the thread may draw its own figures",
        )

    def test_a_claim_is_taken_once(self):
        slack_app.remember_run("111.222", result_a())
        self.assertTrue(slack_app.claim_figure("111.222", "timeline"))
        self.assertFalse(slack_app.claim_figure("111.222", "timeline"))
        slack_app.release_figure("111.222", "timeline")
        self.assertTrue(slack_app.claim_figure("111.222", "timeline"))

    def test_a_thread_with_no_run_never_blocks_a_claim(self):
        self.assertTrue(slack_app.claim_figure("nobody.000", "forest"))


class TestEveryInteractiveComponentIsRegistered(unittest.TestCase):
    """An action Slack delivers and nobody listens for is logged as an unhandled request
    and leaves the reader looking at a warning on a menu that worked."""

    def test_build_app_registers_the_mention_the_menu_and_every_button(self):
        registered = []

        class FakeApp:
            def __init__(self, token=None):
                pass

            def event(self, name):
                registered.append(("event", name))
                return lambda handler: handler

            def action(self, action_id):
                registered.append(("action", action_id))
                return lambda handler: handler

        self.addCleanup(setattr, slack_app, "App", slack_app.App)
        slack_app.App = FakeApp
        slack_app.build_app("xoxb-not-a-real-token")

        self.assertIn(("event", "app_mention"), registered)
        for action_id in (
            [slack_app.ARMS_ACTION_ID, slack_app.GENERATE_ACTION_ID]
            + list(slack_app.FIGURE_ACTION_IDS.values())
        ):
            self.assertIn(("action", action_id), registered)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class GenerateRunsOnce(unittest.TestCase):
    """A Generate press that arrives twice must not run the pair twice.

    Reproduces a real incident: one thread, one Generate, two identical cards two minutes
    apart. `_RUN_LOCK` serialises run_pair, so the duplicate did not interleave - it
    simply started when the first finished, which is why the timestamps were exactly one
    run apart.

    The visible symptom was doubled messages. The damage was to the evidence: both runs
    took the ledger stem slack_<pair>, and ledger.start() truncates, so the second run
    deleted the first run's ledger while the first run's card was still in the thread
    citing it by name.
    """

    def setUp(self):
        slack_app.forget_started_runs()
        slack_app.forget_runs()

    tearDown = setUp

    def test_the_same_press_twice_runs_once(self):
        self.assertTrue(slack_app.claim_run("1700000000.1", {"mr", "coloc"}))
        self.assertFalse(slack_app.claim_run("1700000000.1", {"mr", "coloc"}))

    def test_arm_order_does_not_make_it_a_different_run(self):
        self.assertTrue(slack_app.claim_run("1700000000.1", ["mr", "coloc"]))
        self.assertFalse(slack_app.claim_run("1700000000.1", ["coloc", "mr"]))

    def test_a_different_arm_selection_is_a_real_second_request(self):
        # Pressing Generate again with the gene arm added is a new question, not a stutter.
        self.assertTrue(slack_app.claim_run("1700000000.1", {"mr"}))
        self.assertTrue(slack_app.claim_run("1700000000.1", {"mr", "genes"}))

    def test_another_thread_is_unaffected(self):
        self.assertTrue(slack_app.claim_run("1700000000.1", {"mr"}))
        self.assertTrue(slack_app.claim_run("1700000000.2", {"mr"}))

    def test_concurrent_presses_yield_exactly_one_winner(self):
        # Two clicks land on two threads of Bolt's pool at once; a check-then-set would
        # let both through, which is how the incident happened.
        winners = []
        barrier = threading.Barrier(8)

        def press():
            barrier.wait(timeout=5)
            if slack_app.claim_run("1700000000.9", {"mr"}):
                winners.append(1)

        threads = [threading.Thread(target=press) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(len(winners), 1)

    def test_a_finished_run_is_not_released(self):
        # Its card is already posted. A later press should be answered, not re-run.
        self.assertTrue(slack_app.claim_run("1700000000.1", {"mr"}))
        self.assertFalse(slack_app.claim_run("1700000000.1", {"mr"}))

    def test_release_allows_a_retry_after_nothing_reached_the_thread(self):
        self.assertTrue(slack_app.claim_run("1700000000.1", {"mr"}))
        slack_app.release_run("1700000000.1", {"mr"})
        self.assertTrue(slack_app.claim_run("1700000000.1", {"mr"}))

    def test_the_claim_store_is_bounded(self):
        for index in range(slack_app.MAX_STARTED_RUNS + 40):
            slack_app.claim_run(f"ts-{index}", {"mr"})
        self.assertLessEqual(len(slack_app._STARTED_RUNS), slack_app.MAX_STARTED_RUNS)

    def test_the_duplicate_note_says_the_press_was_ignored_not_that_it_failed(self):
        note = slack_app.DUPLICATE_RUN_NOTE
        self.assertIn("already", note.lower())
        self.assertIn("ignored", note.lower())
        # It must not read as an error about the evidence.
        for wrong in ("failed", "error", "no effect"):
            self.assertNotIn(wrong, note.lower())


class SectionNineOnTheOperatorKey(unittest.TestCase):
    """Slack writes section 9 with the DEPLOYMENT's key, never a reader's.

    A Slack channel is a shared, logged place. Asking a reader to paste a secret into one
    is not a smaller version of per-user keys; it is a thing that must not happen. So this
    surface runs on the operator credential and records it as such.
    """

    def setUp(self):
        slack_app.forget_runs()
        for name in (slack_app.LLM_PROVIDER_VAR, slack_app.LLM_MODEL_VAR):
            os.environ.pop(name, None)

    tearDown = setUp

    def test_the_default_is_a_model_that_passed_the_fixtures(self):
        # A shared surface is exactly where an unvalidated model must not be the default.
        import llm

        provider, model, why_not = slack_app.interpretation_target()
        self.assertEqual(why_not, "")
        self.assertEqual(llm.resolve(provider, model).status, llm.SUPPORTED)

    def test_both_variables_together_override_the_default(self):
        os.environ[slack_app.LLM_PROVIDER_VAR] = "claude"
        os.environ[slack_app.LLM_MODEL_VAR] = "claude-opus-5"
        self.assertEqual(
            slack_app.interpretation_target()[:2],
            ("claude", "claude-opus-5"),
        )

    def test_one_variable_alone_does_not_override(self):
        os.environ[slack_app.LLM_PROVIDER_VAR] = "claude"
        provider, _model, _why = slack_app.interpretation_target()
        self.assertEqual(provider, "google")

    def test_with_nothing_supported_it_writes_no_section_nine_at_all(self):
        import llm

        experimental = [
            dict(row, status=llm.EXPERIMENTAL) for row in llm.menu()
        ]
        with patch.object(llm, "menu", return_value=experimental):
            _provider, _model, why_not = slack_app.interpretation_target()
        self.assertIn("evidence fixtures", why_not)
        self.assertIn(slack_app.LLM_PROVIDER_VAR, why_not)

    def test_no_key_configured_is_silent(self):
        # A deployment that never switched section 9 on must not put a notice under every
        # card about it. The card itself already reads "pending integration".
        with patch("llm.cli.credential_from_env") as credential:
            credential.return_value.is_usable.return_value = False
            interpretation, note = slack_app.write_section_nine({"state": "A"})
        self.assertIsNone(interpretation)
        self.assertEqual(note, "")

    def test_no_supported_model_is_silent_too(self):
        import llm

        experimental = [dict(row, status=llm.EXPERIMENTAL) for row in llm.menu()]
        with patch.object(llm, "menu", return_value=experimental):
            interpretation, note = slack_app.write_section_nine({"state": "A"})
        self.assertIsNone(interpretation)
        self.assertEqual(note, "")

    def test_a_rejected_paragraph_is_reported_not_hidden(self):
        # A silently absent section 9 is indistinguishable from one nobody asked for.
        from llm.interpret import Interpretation

        rejected = Interpretation(
            accepted = False,
            status   = "rejected",
            reason   = "validator: 2 finding(s); prose discarded.",
        )
        with patch("llm.interpret.interpret", return_value=rejected), \
             patch("llm.cli.credential_from_env") as credential:
            credential.return_value.is_usable.return_value = True
            interpretation, note = slack_app.write_section_nine({"state": "A"})

        self.assertIsNone(interpretation)
        self.assertIn("prose discarded", note)

    def test_an_accepted_paragraph_returns_it_with_no_note(self):
        from llm.interpret import Interpretation

        accepted = Interpretation(
            accepted = True,
            status   = "accepted",
            fields   = {"headline": "A headline."},
            metadata = {"model": "gemini-flash-lite-latest"},
        )
        with patch("llm.interpret.interpret", return_value=accepted), \
             patch("llm.cli.credential_from_env") as credential:
            credential.return_value.is_usable.return_value = True
            interpretation, note = slack_app.write_section_nine({"state": "A"})

        self.assertIs(interpretation, accepted)
        self.assertEqual(note, "")

    def test_an_exploding_interpretation_step_never_costs_the_run(self):
        with patch("llm.cli.credential_from_env", side_effect=RuntimeError("boom")):
            interpretation, note = slack_app.write_section_nine({"state": "A"})
        self.assertIsNone(interpretation)
        self.assertIn("RuntimeError", note)
        self.assertIn("not of the evidence", note)

    def test_every_skip_note_says_the_evidence_is_unaffected(self):
        # The one thing a reader must never conclude from a blank section 9.
        self.assertIn("not of the evidence", slack_app.INTERPRETATION_SKIPPED)
        self.assertIn("unchanged", slack_app.INTERPRETATION_SKIPPED)


class TheCardCarriesTheInterpretation(unittest.TestCase):
    def test_write_card_passes_it_to_render(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(slack_app.render, "render_card", return_value="card") as render_card:
            slack_app.write_card({"state": "A"}, folder, interpretation="SENTINEL")
        render_card.assert_called_once_with({"state": "A"}, "SENTINEL")

    def test_write_card_without_one_renders_the_card_as_before(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(slack_app.render, "render_card", return_value="card") as render_card:
            slack_app.write_card({"state": "A"}, folder)
        render_card.assert_called_once_with({"state": "A"}, None)
