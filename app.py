"""MetaboCausal - the web app (1G).

WHY MOST OF THIS WORKS WITH NO KEY
-----------------------------------
The evidence card is rendered by code from the tool envelopes (see render.py), not
written by a model - the state, the reason and every number on it come from
`classify.classify_state` and the retrieval tools in `pipeline.py`, most of which need no
key. The one exception is OpenGWAS's mQTL/outcome lookups (1C), which read
`OPENGWAS_JWT` the same way `agent.py` does, through `load_dotenv()` two directory levels
above this worktree; without it that one arm degrades honestly rather than failing the
run, exactly as it does from the CLI or the Slack shell.

The ONLY thing a model ever contributes is section 9 of the card - the verdict paragraph
`llm.interpret.interpret` writes and `validate_card` re-checks against the retrieval
before it is allowed to print. Paste a Gemini key in the sidebar to switch it on; every
other section renders identically with or without one, and a rejected or unavailable
interpretation degrades to the same fixed placeholder sentence the card carries before
1F ever ran.

Run locally:
    streamlit run app.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

import app_data
import pipeline
import plots
from render import render_card

load_dotenv()

try:
    from llm import Credential, default_model

    MODEL_DEFAULT = default_model("google")
except Exception:                                        # noqa: BLE001 - sidebar still renders
    Credential = None
    MODEL_DEFAULT = "gemini-flash-lite-latest"

NO_MODEL_NOTE = (
    "No model was called on this run. Sections 1-8, 10 and 11 are unaffected either way; "
    "section 9 stays the fixed placeholder sentence it carries before 1F runs. Paste a "
    "Gemini key in the sidebar to have a model write it - the validator checks every "
    "sentence against this run's own retrieval before it is allowed onto the card."
)

st.set_page_config(page_title="MetaboCausal", layout="wide")

st.markdown(
    """
<style>
#MainMenu, footer, [data-testid="stToolbar"] {visibility: hidden;}
.block-container {padding-top: 1.1rem; max-width: 1200px;}
.mc-hero {background: linear-gradient(90deg, #0B3D2E, #1F6E43); border-radius: 14px;
          padding: 20px 28px; color: #fff; margin-bottom: 10px;}
.mc-hero h1 {color: #fff; font-size: 2.0rem; margin: 0 0 6px 0;}
.mc-hero p  {color: #DCEFE2; margin: 0; font-size: 0.97rem;}
.stTabs [data-baseweb="tab"] {font-size: 1.02rem; font-weight: 600;}
</style>
<div class="mc-hero">
  <h1>MetaboCausal</h1>
  <p>One metabolite &times; one disease &rarr; one evidence card, retrieved and rendered
     by code. No model is needed to build the card; one is optional for the one
     paragraph a model is allowed to write.</p>
</div>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Optional: add a model")
    st.markdown(
        "The card needs no model. A model only writes section 9's verdict paragraph, "
        "and only after `validate_card` has checked it against this run's own "
        "retrieval.\n\n"
        "Paste your own Gemini key to switch that on. It is used for this run only, "
        "kept in this session, and never written to disk."
    )
    api_key = st.text_input(
        "Gemini API key (optional)",
        type = "password",
        help = "Free key: https://aistudio.google.com/apikey",
    )
    model = st.text_input("Model", value=MODEL_DEFAULT)
    st.divider()
    st.caption(
        "OpenGWAS lookups (1C) need OPENGWAS_JWT in the .env two levels above this "
        "worktree, loaded the same way agent.py loads it. Without it that one arm "
        "degrades honestly; the rest of the run is unaffected."
    )

tab_run, tab_examples, tab_library = st.tabs(
    [
        "Run a pair",
        "Example cards",
        "Browse the library",
    ]
)

with tab_run:
    st.caption(
        "Live retrieval through pipeline.run_pair - EpiGraphDB MR-EVE, OpenGWAS "
        "instruments, Open Targets colocalisation, Human-GEM biochemical context and "
        "the effector-gene dossier. Deterministic: no model runs in this call."
    )

    EXAMPLES = [
        ("urate", "gout"),
        ("glycine", "coronary artery disease"),
        ("trimethylamine N-oxide", "coronary artery disease"),
    ]

    st.session_state.setdefault("mc_metabolite_in", "urate")
    st.session_state.setdefault("mc_disease_in", "gout")

    def _set_pair(metabolite: str, disease: str) -> None:
        st.session_state.mc_metabolite_in = metabolite
        st.session_state.mc_disease_in = disease

    cols = st.columns(len(EXAMPLES))
    for col, (metabolite, disease) in zip(cols, EXAMPLES):
        col.button(
            f"{metabolite} × {disease}",
            use_container_width = True,
            on_click            = _set_pair,
            args                = (metabolite, disease),
        )

    c1, c2 = st.columns(2)
    metabolite_in = c1.text_input("Metabolite", key="mc_metabolite_in")
    disease_in = c2.text_input("Disease", key="mc_disease_in")
    include_catalog = st.checkbox(
        "Also query the GWAS Catalog (adds ~100 s; drives the gene stage's evidence base "
        "but never the A/B/C state)",
        value = False,
    )
    go = st.button("Build the evidence card", type="primary", use_container_width=True)

    if go:
        if not metabolite_in.strip() or not disease_in.strip():
            st.error("Give both a metabolite and a disease.")
            st.stop()
        with st.spinner(
            "retrieving MR estimates, instruments, colocalisation and gene context …"
        ):
            result = pipeline.run_pair(
                metabolite_in.strip(),
                disease_in.strip(),
                skip_catalog = not include_catalog,
                stem_prefix  = "app",
            )

        interpretation = None
        if api_key.strip() and Credential is not None:
            with st.spinner("the model is writing section 9 …"):
                try:
                    from llm.interpret import interpret

                    interpretation = interpret(
                        result,
                        provider   = "google",
                        model      = model.strip() or MODEL_DEFAULT,
                        credential = Credential(provider="google", key=api_key.strip()),
                    )
                except Exception as exc:                  # noqa: BLE001
                    st.warning(f"Model call failed — the card renders without it. ({exc})")

        card_md = render_card(
            result,
            interpretation = interpretation if interpretation and interpretation.accepted else None,
        )
        st.session_state["mc_last_run"] = {
            "result":          result,
            "card_md":         card_md,
            "interpretation":  interpretation,
        }

    run = st.session_state.get("mc_last_run")
    if run:
        result = run["result"]
        state = str(result.get("state") or "").strip().upper()
        reason = str(result.get("reason") or "").strip()
        if state == "A":
            st.success(f"State A - {reason}")
        elif state == "B":
            st.info(f"State B - {reason}")
        elif state == "C":
            st.warning(f"State C - {reason}")
        else:
            st.error(f"No state was retrieved for this run. {reason}")

        interpretation = run["interpretation"]
        if interpretation is None:
            st.info(NO_MODEL_NOTE)
        elif interpretation.accepted:
            st.success(interpretation.note())
        else:
            st.warning(interpretation.note())

        with st.expander("Evidence card (11 sections)", expanded=True):
            st.markdown(run["card_md"])

        with st.expander("Figures - drawn from this run's own envelopes", expanded=True):
            fig_dir = Path(tempfile.mkdtemp(prefix="metabocausal_app_"))
            with st.spinner("drawing …"):
                try:
                    state_figure = plots.plot_for_result(result, out_dir=str(fig_dir))
                except Exception as exc:                  # noqa: BLE001
                    state_figure = None
                    st.warning(f"state figure failed to draw: {exc}")
                try:
                    timeline_figure = plots.plot_genetic_insight(result, str(fig_dir))
                except Exception as exc:                  # noqa: BLE001
                    timeline_figure = None
                    st.warning(f"genetics-to-clinic timeline failed to draw: {exc}")

            fc1, fc2 = st.columns(2)
            if state_figure:
                fc1.image(state_figure, use_container_width=True)
            else:
                fc1.caption(
                    "no state figure - state C draws nothing (nothing retrieved), and "
                    "state A/B draws nothing when its own envelope is empty"
                )
            if timeline_figure:
                fc2.image(timeline_figure, use_container_width=True)
            else:
                fc2.caption(
                    "no genetics-to-clinic timeline - no drug in the effector-gene "
                    "dossier carries a clinical report with a retrieved year"
                )

        stem = plots.stem_for_result(result)
        st.download_button(
            "Download this card (Markdown)",
            data      = run["card_md"].encode("utf-8"),
            file_name = f"card_{stem}.md",
            mime      = "text/markdown",
        )
    else:
        st.info(
            "Pick an example above or type your own pair, then press "
            "**Build the evidence card**."
        )

with tab_examples:
    st.caption(
        "The three reviewed cards committed under examples/ - one per state (A, B, C). "
        "Read verbatim from disk, not regenerated. Figures are drawn fresh, offline, "
        "from the committed snapshot data/demo_card_inputs.json."
    )

    pairs = app_data.example_pairs()
    labels = [pair["label"] for pair in pairs]
    choice = st.radio("Pick an example", labels, horizontal=False)
    chosen = next(pair for pair in pairs if pair["label"] == choice)

    card = app_data.example_card(chosen["key"])
    st.caption(f"Source: `{card['path']}` (committed, reviewed markdown)")

    fig_dir = Path(tempfile.mkdtemp(prefix="metabocausal_examples_"))
    figures = app_data.example_figures(chosen["key"], fig_dir)

    fc1, fc2 = st.columns(2)
    if figures["state_figure"]:
        fc1.image(figures["state_figure"], use_container_width=True)
    else:
        fc1.caption("no state figure for this pair's state (see the card's section 2)")
    if figures["timeline_figure"]:
        fc2.image(figures["timeline_figure"], use_container_width=True)
    fc2.caption(figures["timeline_note"])

    with st.expander("Evidence card (11 sections)", expanded=True):
        st.markdown(card["card_md"])

    st.download_button(
        "Download this card (Markdown)",
        data      = card["card_md"].encode("utf-8"),
        file_name = Path(card["path"]).name,
        mime      = "text/markdown",
        key       = f"dl_{chosen['key']}",
    )

with tab_library:
    inventory = app_data.library_inventory()
    summary = app_data.library_summary()

    if not summary["shipped"]:
        st.warning(summary["reason"])
        st.markdown(
            "A full local sweep is not shipped on this branch. To build it:\n\n"
            f"```\n{inventory['regenerate_command']}\n```"
        )
    else:
        st.caption(
            f"Source: `{summary['path']}` - MVP2's screened literature table. These rows "
            "are retrieved from screened publications, not from a live pipeline.run_pair "
            "sweep; state is present only on the rows MVP1/MVP2 merged into an accepted "
            "MR record."
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("rows", f"{summary['n_rows']:,}")
        m2.metric("distinct metabolite x disease pairs", f"{summary['n_distinct_pairs']:,}")
        m3.metric("distinct metabolites", f"{summary['n_metabolites']:,}")
        m4.metric("distinct diseases", f"{summary['n_diseases']:,}")

        st.markdown("**Record type** (retrieved counts):")
        st.table(
            {
                "record_type": list(summary["record_type_counts"].keys()),
                "rows":        list(summary["record_type_counts"].values()),
            }
        )
        st.markdown("**State** (retrieved counts; absence is a screened-not-merged row, not a C):")
        st.table(
            {
                "state": list(summary["state_counts"].keys()),
                "rows":  list(summary["state_counts"].values()),
            }
        )

        st.divider()
        st.markdown("**Browse rows**")
        f1, f2 = st.columns(2)
        metabolite_q = f1.text_input("Filter metabolite", placeholder="e.g. urate, glycine …")
        disease_q = f2.text_input("Filter disease", placeholder="e.g. gout, diabetes …")

        frame = app_data.load_library()
        view = frame
        if metabolite_q.strip():
            view = view[view["metabolite_name"].str.contains(metabolite_q.strip(), case=False, na=False)]
        if disease_q.strip():
            view = view[view["disease_trait"].str.contains(disease_q.strip(), case=False, na=False)]

        st.caption(f"{len(view):,} of {len(frame):,} rows shown (first 500 rendered).")
        st.dataframe(
            view.head(500),
            use_container_width = True,
            hide_index          = True,
            height              = 420,
        )

        st.caption(inventory["page_path_note"])

    st.divider()
    st.markdown("**What is not shipped on this branch**")
    local_ledgers = app_data.frozen_ledgers()
    local_figures = app_data.frozen_figures()
    st.markdown(
        f"- {inventory['validated_note']}\n"
        f"- {inventory['index_note']}\n"
        f"- `cards/` is local run output only (gitignored) - a fresh clone starts with no "
        f"ledgers and no figures there; on this machine right now it holds "
        f"{len(local_ledgers)} ledger(s) and {len(local_figures)} figure(s) from local "
        f"runs, none of them committed."
    )
    st.markdown(f"To build the missing pieces:\n\n```\n{inventory['regenerate_command']}\n```")
