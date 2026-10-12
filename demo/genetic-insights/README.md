# Genetic Insights recording demonstrator

**Start with [the filled MVP1 timeline table](MVP1_TIMELINE_TABLE.md).**

This folder supplies two existing-MVP1, target-matched examples plus a portable HTML viewer, a reusable renderer, and Slack exports. Its purpose is immediate recording and a concrete handoff to Zhang Hao.

## Open a demonstration

1. [Torcetrapib — full evidence lifecycle and safety failure](recordings/cetp-torcetrapib-v2/index.html#insights)
2. [Evacetrapib — full evidence lifecycle and insufficient efficacy](recordings/cetp-evacetrapib-v2/index.html#insights)

Use the v2 examples. The v1 CETP pages are retained as superseded recording history; they began at Phase 3 and do not meet the required human-genetics → preclinical → clinical lifecycle.

Download/open the HTML file in a browser. A GitHub file page displays code; it does not execute the HTML. No server, package installation or model key is required for viewing. Original-source links require internet access.

Both have Evidence card, Genetic Insights, Slack preview, and What's next tabs. The timeline groups selectable events into human genetics, preclinical evidence, clinical development, later genetics and current class status. Presentation mode hides the sidebar. Open snapshot loads another compatible JSON locally; generating a new recording folder also preserves the corresponding Slack artifacts.

The urate–SLC2A9–gout example is retained under `recordings/mvp1-v1` as an earlier supporting example. Its febuxostat link is direct urate-lowering context, not a target-matched SLC2A9 drug. The two CETP cases are the primary recording examples.

## Contents

- [Filled timeline table](MVP1_TIMELINE_TABLE.md): read this with Zhang Hao.
- [Implementation handoff](ZHANG_HAO_START_HERE.md): what is ready and what he owns next.
- [Recording script and current-MVP copy](RECORDING_AND_COPY.md): no unresolved scientific placeholders.
- `tables/`: case, event and source tables in CSV and JSON.
- `snapshots/`: immutable reviewed example inputs.
- `sources/`: saved public API responses with retrieval timestamps. They are supporting receipts for the figures.
- `recordings/`: versioned HTML, summaries, raw selected evidence and Slack exports.
- `render_bundle.py`: one bundle → HTML + Markdown + Slack content; no retrieval.
- `slack_adapter.py`: optional sender for the existing bot client; never runs on import.
- `prepare_example.py`, `prepare_cetp_examples.py`: construction of these curated fixtures.
- `export_tables.py`: deterministic tables from the two CETP bundles.

## Scope and versioning

This is **MVP1 evidence plus a curated timeline demonstration**. It is not the completed automatic timeline search, an implemented MVP2/MVP3 pipeline, or a deployed Slack service. Clinical states are latest retrieved records with their original update dates, not a global guarantee of status today.

Keep one recording folder per accepted result version. Reusing the layout makes the next video straightforward; it does not automatically generate or verify new scientific evidence.

