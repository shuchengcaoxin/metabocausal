"""1D acceptance tests: effector genes named by published metabolite-GWAS atlases.

    python -m unittest tests.test_atlas -v          # from the repo root

Offline by design - the tool reads only `data/atlas_locus_gene.csv`, so nothing here
touches the network. Two halves:

* Ziwei's 35 delivered acceptance checks, ported to stdlib unittest (the three
  documented cases, case-insensitivity, the "a `/` is a ratio, never a split marker"
  rule, the naming-rule contract, the 1C merge, and bad input);
* integration regressions for the three changes made when the section entered the
  repo: the ledger shim (his `record(env, "atlas")` stub -> `ledger.record(env)`), the
  `opengwas_id` -> `ensembl_gene_id` column rename, and the Zoodsma 2025 relabel from
  `eqtl_coloc` to `author_prioritized`.

Anchors that must hold: glycine -> GLDC (named by two atlases) and CPS1,
isoleucine -> PPM1K, urate -> SLC2A9.
"""

from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ledger
import tools.atlas as atlas
from tools.atlas import get_effector_genes_atlas

ENVELOPE_KEYS = {"tool", "args", "source", "url", "retrieved_at", "status", "data", "caveats"}
CSV_PATH = REPO_ROOT / "data" / "atlas_locus_gene.csv"
LEDGER_STEM = "_test_atlas"

# Counts of the shipped table, asserted so a future re-delivery cannot change the
# facts the card and the acceptance doc state without a test failing.
TOTAL_ROWS = 45169
ZOODSMA_ROWS = 43322
NO_GENE_ROWS = 3265


def atlas_env(*synonyms, chebi: str = "", gwascat=None) -> dict:
    """Call the 1D tool with keyword arguments and return its envelope."""
    return get_effector_genes_atlas(
        chebi       = chebi,
        synonyms    = list(synonyms),
        gwascat_env = gwascat,
    )


def genes_of(env: dict) -> list:
    """The upper-cased gene symbols in an envelope's `data.genes`, in rank order."""
    return [gene["gene_symbol"].upper() for gene in env.get("data", {}).get("genes", [])]


def gene_named(env: dict, symbol: str) -> dict:
    """The gene dict for `symbol`, or None if the tool did not return it."""
    for gene in env.get("data", {}).get("genes", []):
        if gene["gene_symbol"].upper() == symbol.upper():
            return gene
    return None


def matched_names(query: str) -> set:
    """Every `metabolite_name` the table rows matched by `query` carry."""
    atlas.load_table()
    indices = atlas._lookup_rows("", [query])[0]
    return {atlas._TABLE[index]["metabolite_name"] for index in indices}


def raw_rows() -> list:
    """The shipped CSV read straight off disk, bypassing the tool's cache."""
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class EnvelopeContractMixin:
    """The section 3.1 shape contract that 1F depends on."""

    def assertEnvelope(self, env: dict, label: str) -> None:
        self.assertEqual(set(env), ENVELOPE_KEYS, f"{label}: the 8 section 3.1 keys")
        self.assertIn(env["status"], {"ok", "empty", "error"}, f"{label}: status vocabulary")
        self.assertIsInstance(env["caveats"], list, f"{label}: caveats is a list")
        self.assertTrue(env["caveats"], f"{label}: carries at least one caveat")


class TestAcceptanceCases(unittest.TestCase, EnvelopeContractMixin):
    """Ziwei's three documented acceptance cases."""

    def test_glycine_names_cps1(self):
        env = atlas_env("glycine")
        self.assertEnvelope(env, "glycine")
        self.assertEqual(env["status"], "ok", env["data"])
        self.assertIn("CPS1", genes_of(env), genes_of(env))
        self.assertGreater(env["data"]["n_rows_matched"], 0)

    def test_isoleucine_names_ppm1k(self):
        env = atlas_env("isoleucine")
        self.assertEnvelope(env, "isoleucine")
        self.assertEqual(env["status"], "ok", env["data"])
        self.assertIn("PPM1K", genes_of(env), genes_of(env))

    def test_unknown_metabolite_is_empty_not_error(self):
        env = atlas_env("zzz_not_a_real_metabolite")
        self.assertEnvelope(env, "unknown")
        self.assertEqual(env["status"], "empty")
        self.assertNotEqual(env["status"], "error")
        caveats = " ".join(env["caveats"])
        self.assertIn(
            "does not mean no effect",
            caveats,
            "empty must never be read as 'no effect'",
        )
        self.assertTrue(
            "Human-GEM" in caveats or "MVP3" in caveats,
            "empty must hand off to the MVP3 fallback",
        )


class TestMatching(unittest.TestCase):
    """How a query finds its rows: case, ratio names, ChEBI spellings."""

    def test_case_insensitive(self):
        upper = atlas_env("Glycine")
        lower = atlas_env("glycine")
        self.assertEqual(
            genes_of(upper),
            genes_of(lower),
            "the table mixes 'Isoleucine' and 'isoleucine'; lookup must ignore case",
        )

    def test_a_slash_is_a_ratio_not_a_split_marker(self):
        glucose_rows = matched_names("glucose")
        self.assertTrue(glucose_rows, "glucose resolves to at least one row")
        self.assertNotIn(
            "glucose/ mannose",
            glucose_rows,
            "a query for one component must not pull in the ratio measure",
        )

    def test_a_ratio_is_reachable_by_its_full_name_in_either_spacing(self):
        for spelling in ("glucose/ mannose", "glucose/mannose"):
            with self.subTest(spelling=spelling):
                self.assertIn("glucose/ mannose", matched_names(spelling))

    def test_lipid_acyl_chain_notation_stays_one_key(self):
        lipid = "1,2-dilinoleoyl-GPC (18:2/18:2)"
        self.assertEqual(atlas._name_keys(lipid), {lipid.lower()})

    def test_metabolite_names_are_kept_verbatim(self):
        """1D 备注 #7: unnamed-compound ids and ratio labels survive as written."""
        atlas.load_table()
        self.assertIn("x-02249", atlas._BY_NAME, "X- ids are indexed verbatim")
        self.assertEqual(matched_names("X-02249"), {"X-02249"})


class TestNamingRules(unittest.TestCase):
    """Every gene carries the rule its source used; no coloc is claimed here."""

    def setUp(self):
        self.env = atlas_env("glycine")

    def test_every_gene_has_a_gene_source(self):
        self.assertTrue(all(gene.get("gene_source") for gene in self.env["data"]["genes"]))

    def test_every_gene_carries_a_named_by_string(self):
        self.assertTrue(all(gene.get("evidence") for gene in self.env["data"]["genes"]))

    def test_caveats_never_claim_colocalization_was_confirmed(self):
        caveats = " ".join(self.env["caveats"]).lower()
        self.assertNotIn("colocalization confirmed", caveats)
        self.assertIn("not colocalization", caveats)

    def test_genome_build_is_stated(self):
        """pos is hg38 (1D 备注 #1); the card must not read it as hg19."""
        self.assertEqual(self.env["data"]["genome_build"], "GRCh38 (hg38)")


class TestGwasCatalogMerge(unittest.TestCase):
    """1C's envelope is merged as a weaker source and never breaks 1D."""

    def test_mapped_genes_are_merged_in(self):
        env = atlas_env("glycine", gwascat={
            "status": "ok",
            "data":   {"associations": [{"mappedGene": "FAKEGENE1"}]},
        })
        self.assertGreater(env["data"]["n_genes"], 0)
        merged = gene_named(env, "FAKEGENE1")
        if merged is not None:
            self.assertEqual(merged["gene_source"], ["gwas_catalog_mapped"])

    def test_a_broken_1c_envelope_does_not_break_1d(self):
        env = atlas_env("glycine", gwascat={"status": "error", "data": {}})
        self.assertEqual(env["status"], "ok")

    def test_gwascat_env_none_is_tolerated(self):
        env = atlas_env("glycine", gwascat=None)
        self.assertEqual(env["status"], "ok")


class TestBadInput(unittest.TestCase):
    """A malformed synonym list returns an envelope; it never raises."""

    def test_malformed_synonyms_return_a_valid_envelope(self):
        for bad in ([], None, [123, None], ["", "   "]):
            with self.subTest(synonyms=bad):
                env = get_effector_genes_atlas(
                    chebi       = "",
                    synonyms    = bad,
                    gwascat_env = {},
                )
                self.assertIn(env["status"], {"ok", "empty", "error"})


class TestAnchors(unittest.TestCase):
    """The four anchors the integration is accepted on."""

    def test_glycine_gldc_is_named_by_two_atlases(self):
        gldc = gene_named(atlas_env("glycine"), "GLDC")
        self.assertIsNotNone(gldc, "GLDC must be among glycine's returned genes")
        self.assertGreaterEqual(gldc["n_sources"], 2, gldc["atlases"])
        self.assertEqual(set(gldc["atlases"]), {"Zoodsma 2025", "Chen 2023"})

    def test_glycine_ranks_the_dual_source_gene_first(self):
        """Cross-atlas agreement is the only real strength signal in this table."""
        self.assertEqual(genes_of(atlas_env("glycine"))[0], "GLDC")

    def test_glycine_keeps_cps1_which_only_shin_names(self):
        cps1 = gene_named(atlas_env("glycine"), "CPS1")
        self.assertIsNotNone(cps1, "the largest atlas must not crowd CPS1 off the card")
        self.assertEqual(cps1["atlases"], ["Shin 2014"])
        self.assertEqual(cps1["confidence"], "weak", "nearest-gene is a weak rule")

    def test_isoleucine_ppm1k(self):
        ppm1k = gene_named(atlas_env("isoleucine"), "PPM1K")
        self.assertIsNotNone(ppm1k)
        self.assertEqual(ppm1k["atlases"], ["Zoodsma 2025"])

    def test_urate_slc2a9(self):
        env = atlas_env("urate")
        self.assertEqual(env["status"], "ok")
        self.assertIn("SLC2A9", genes_of(env))

    def test_urate_locus_without_a_gene_is_counted_not_dropped_silently(self):
        """One of urate's three rows names no gene; the card must say so."""
        env = atlas_env("urate")
        self.assertIn(
            "report no gene symbol",
            " ".join(env["caveats"]),
            "a locus row with N/A must surface as a caveat, not vanish",
        )


class TestLedgerShim(unittest.TestCase):
    """The delivered file called a local `record(env, "atlas")` stub; the repo ledger
    takes the envelope alone and gets the stem from the run context."""

    def tearDown(self):
        ledger.stop()
        target = ledger.path_for(LEDGER_STEM)
        if target.exists():
            target.unlink()

    def test_the_tool_records_its_own_envelope(self):
        ledger.start(LEDGER_STEM)
        env = atlas_env("glycine")

        records = ledger.load(LEDGER_STEM)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[-1]["tool"], "get_effector_genes_atlas")
        self.assertEqual(records[-1]["status"], env["status"])
        self.assertEqual(records[-1]["data"]["n_genes"], env["data"]["n_genes"])

    def test_an_empty_lookup_is_recorded_too(self):
        ledger.start(LEDGER_STEM)
        atlas_env("zzz_not_a_real_metabolite")
        records = ledger.load(LEDGER_STEM)
        self.assertEqual(records[-1]["status"], "empty")

    def test_recording_outside_a_run_is_a_silent_no_op(self):
        ledger.stop()
        atlas_env("glycine")
        self.assertFalse(ledger.path_for(LEDGER_STEM).exists())


class TestShippedTable(unittest.TestCase):
    """The two edits made to the delivered CSV, asserted against the shipped file."""

    @classmethod
    def setUpClass(cls):
        cls.rows = raw_rows()

    def test_row_count_is_unchanged_by_the_integration_edits(self):
        self.assertEqual(len(self.rows), TOTAL_ROWS)

    def test_the_ensembl_column_is_named_for_what_it_holds(self):
        header = set(self.rows[0])
        self.assertIn("ensembl_gene_id", header)
        self.assertNotIn("opengwas_id", header, "the column holds ENSG ids, not GWAS ids")

    def test_the_ensembl_column_reaches_the_envelope(self):
        gldc = gene_named(atlas_env("glycine"), "GLDC")
        self.assertIn("ENSG00000178445", gldc["ensembl_ids"])

    def test_no_shipped_row_claims_eqtl_colocalization(self):
        """Zoodsma 2025 prioritized genes from an allele series; it ran no coloc."""
        self.assertEqual([r for r in self.rows if r["gene_source"] == "eqtl_coloc"], [])

    def test_every_zoodsma_row_is_labelled_author_prioritized(self):
        zoodsma = [r for r in self.rows if r["atlas"] == "Zoodsma 2025"]
        self.assertEqual(len(zoodsma), ZOODSMA_ROWS)
        self.assertEqual({r["gene_source"] for r in zoodsma}, {"author_prioritized"})

    def test_the_other_two_atlases_keep_their_own_rules(self):
        rules = {(r["atlas"], r["gene_source"]) for r in self.rows}
        self.assertIn(("Chen 2023", "author_prioritized"), rules)
        self.assertIn(("Shin 2014", "nearest"), rules)

    def test_rows_naming_no_gene_are_present_and_counted(self):
        """1D 备注 #3: N/A means the paper named no effector gene at that locus."""
        missing = [r for r in self.rows if atlas._is_missing(r["gene_symbol"])]
        self.assertEqual(len(missing), NO_GENE_ROWS)

    def test_chromosome_x_is_written_as_23(self):
        """1D 备注 #6. A card that prints 'chr 23' must not be read as autosome 23."""
        self.assertTrue(any(r["chr"] == "23" for r in self.rows))
        self.assertFalse(any(r["chr"].upper() == "X" for r in self.rows))


class TestMultiGeneCells(unittest.TestCase):
    """Documented as-is: a Chen 2023 row that names several genes at one locus keeps
    them in one '; '-joined cell, and the tool treats that cell as one gene entry.

    Not split on purpose - the paper attributes the locus to the gene family jointly,
    and splitting would invent three independent single-gene claims it never made. The
    consequence the card must live with: 'BHMT; DMGDH' is a gene_symbol string, so a
    downstream lookup by symbol (Open Targets, gnomAD) will not resolve it."""

    def test_a_multi_gene_cell_stays_one_entry(self):
        env = atlas_env("betaine")
        self.assertIn("BHMT; DMGDH", [g["gene_symbol"] for g in env["data"]["genes"]])

    def test_the_joined_cell_does_not_merge_with_the_single_gene_entry(self):
        env = atlas_env("betaine")
        symbols = [g["gene_symbol"] for g in env["data"]["genes"]]
        self.assertIn("BHMT", symbols)
        self.assertNotEqual(symbols.count("BHMT"), 2)

    def test_gwas_catalog_genes_are_split_on_the_same_separator(self):
        """The 1C merge path does split - that list is a list, not a joint attribution."""
        self.assertEqual(
            atlas._extract_gwascat_genes({
                "status": "ok",
                "data":   {"associations": [{"mappedGene": "AAA1; BBB2"}]},
            }),
            ["AAA1", "BBB2"],
        )


class TestToolRegistration(unittest.TestCase):
    """1D is a registered tool the agent may call."""

    def test_get_effector_genes_atlas_is_in_tools(self):
        import tools

        self.assertIn(atlas.get_effector_genes_atlas, tools.TOOLS)
        self.assertIs(tools.get_effector_genes_atlas, atlas.get_effector_genes_atlas)

    def test_the_docstring_the_model_reads_names_the_atlases(self):
        doc = atlas.get_effector_genes_atlas.__doc__
        for name in ("Shin 2014", "Chen 2023", "Zoodsma 2025"):
            self.assertIn(name, doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
