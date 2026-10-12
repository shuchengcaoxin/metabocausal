"""1C acceptance tests for tools/gwascat.py. Stdlib unittest, fast by default.

    python -m unittest tests.test_1c_gwascat -v            # from the repo root
    METABOCAUSAL_SLOW_TESTS=1 python -m unittest tests.test_1c_gwascat -v

Almost every test here runs against RECORDED payloads, not the network, because the
associations endpoint cannot be paged and is slow enough to make a live suite useless:
measured 2026-09-10, gout took 113 s for 3.0 MB / 1,420 rows and urate measurement
364 s for 10.4 MB / 4,588 rows. The fixtures below are verbatim excerpts of those real
2026-09-10 payloads with `_links` and the date fields trimmed - the field names, the
underflowed p-values and the two annotation sources are exactly what EBI returned.

Two live tests remain. `TestLiveSmoke` is the cheap one (three small requests, a few
seconds) and proves the shapes this module is built on still hold. `TestLiveSlow` pulls
gout's associations for real and runs only when METABOCAUSAL_SLOW_TESTS=1, because two
minutes in a unit-test suite is two minutes nobody will wait for twice.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ledger
from tools import _common, gwascat
from tools.gwascat import get_gwas_catalog

ENVELOPE_KEYS = {"tool", "args", "source", "url", "retrieved_at", "status", "data", "caveats"}
DATA_KEYS = {
    "efo_short_form",
    "efo_trait",
    "n_associations_total",
    "n_associations_kept",
    "associations",
    "mapped_genes",
    "queries",
}
MAPPED_GENE_KEYS = {"gene", "rsid", "distance", "is_intergenic", "source", "is_closest_gene"}

LEDGER_STEM = "_test_1c_gwascat"
SLOW_TESTS = os.environ.get("METABOCAUSAL_SLOW_TESTS") == "1"

# ---------------------------------------------------------------- recorded fixtures

GOUT_TRAIT = {
    "trait":     "gout",
    "uri":       "http://purl.obolibrary.org/obo/MONDO_0005393",
    "shortForm": "MONDO_0005393",
}
GOUT_SEARCH = {"_embedded": {"efoTraits": [GOUT_TRAIT]}, "page": {}}
EMPTY_SEARCH = {"_embedded": {"efoTraits": []}, "page": {}}


def _association(
    risk_allele,
    pvalue,
    mantissa,
    exponent,
    odds_ratio = None,
    beta       = None,
    beta_unit  = None,
    direction  = None,
    genes      = (),
):
    """One association in the source's own shape. Values are the real ones."""
    return {
        "riskFrequency":      "0.11",
        "pvalueDescription":  None,
        "pvalueMantissa":     mantissa,
        "pvalueExponent":     exponent,
        "multiSnpHaplotype":  False,
        "snpInteraction":     False,
        "snpType":            "known",
        "standardError":      None,
        "range":              None,
        "description":        None,
        "orPerCopyNum":       odds_ratio,
        "betaNum":            beta,
        "betaUnit":           beta_unit,
        "betaDirection":      direction,
        "pvalue":             pvalue,
        "loci": [{
            "haplotypeSnpCount":   None,
            "description":         "Single variant",
            "strongestRiskAlleles": [{"riskAlleleName": risk_allele, "riskFrequency": None}],
            "authorReportedGenes": [{"geneName": gene} for gene in genes],
        }],
    }


# Deliberately NOT in p-value order, and rs2728099 sits before rs2231142: both report
# pvalue exactly 0.0, so a sort on the float would keep this order and a sort on the
# reported exponent (-324 vs -1421) must not.
GOUT_ASSOCIATIONS = {"_embedded": {"associations": [
    _association(
        "rs2199936-A",
        3e-23,
        3,
        -23,
        odds_ratio = 1.86,
        genes      = ("ABCG2",),
    ),
    _association(
        "rs2728099-C",
        0.0,
        5,
        -324,
        beta      = 0.44741,
        beta_unit = "unit",
        direction = "increase",
    ),
    _association(
        "rs10480300-?",
        9e-06,
        9,
        -6,
        genes = ("NR",),
    ),
    _association(
        "rs2231142-T",
        0.0,
        1,
        -1421,
        odds_ratio = 1.7349871,
        genes      = ("ABCG2",),
    ),
    _association(
        "chr4:88887327-A",
        1e-323,
        1,
        -323,
        beta      = 0.4228,
        beta_unit = "unit",
        direction = "increase",
    ),
    _association(
        "rs4475146-A",
        4e-26,
        4,
        -26,
        beta      = 0.4682,
        beta_unit = "unit",
        direction = "decrease",
        genes     = ("SLC2A9",),
    ),
]}}


def _context(row: tuple) -> dict:
    """One genomicContexts entry from a recorded row:
    (gene, source, distance, is_intergenic, is_closest_gene)."""
    gene, source, distance, intergenic, closest = row
    return {
        "isIntergenic":   intergenic,
        "isUpstream":     False,
        "isDownstream":   not intergenic,
        "distance":       distance,
        "gene":           {"geneName": gene},
        "source":         source,
        "mappingMethod":  "Ensembl_pipeline",
        "isClosestGene":  closest,
    }


# rs2231142 sits INSIDE ABCG2 (distance 0, not intergenic) and is nonetheless not
# flagged isClosestGene, while three farther genes are - the trap CLOSEST_GENE_CAVEAT
# names. RPL31P24 shows the two sources disagreeing about distance by 40 bp.
_RS2231142_CONTEXTS = [
    ("ABCG2",        "Ensembl", 0,     False, False),
    ("ABCG2",        "NCBI",    0,     False, False),
    ("LOC124900867", "NCBI",    27215, True,  True),
    ("RPL31P24",     "NCBI",    32368, True,  False),
    ("RPL31P24",     "Ensembl", 32408, True,  True),
    ("PKD2",         "Ensembl", 53394, True,  True),
]
_RS2728099_CONTEXTS = [
    ("PKD2",  "Ensembl", 0,     False, False),
    ("PKD2",  "NCBI",    0,     False, False),
    ("ABCG2", "Ensembl", 35564, True,  True),
    ("ABCG2", "NCBI",    35678, True,  True),
]

SNP_PAYLOADS = {
    "rs2231142": {
        "rsId":            "rs2231142",
        "genomicContexts": [_context(row) for row in _RS2231142_CONTEXTS],
    },
    "rs2728099": {
        "rsId":            "rs2728099",
        "genomicContexts": [_context(row) for row in _RS2728099_CONTEXTS],
    },
    # Real behaviour for a positional id: HTTP 200 with nothing annotated.
    "chr4:88887327": {
        "rsId":            "chr4:88887327",
        "genomicContexts": [],
    },
}


# ---------------------------------------------------------------- the fake transport

class Recorder:
    """Stands in for _common.get_json and gwascat._fetch_within_deadline together, so a
    test can assert WHICH endpoints were reached and in what order."""

    def __init__(
        self,
        search       = GOUT_SEARCH,
        associations = GOUT_ASSOCIATIONS,
    ):
        self.search = search
        self.associations = associations
        self.calls = []
        self.snp_error = None

    def get_json(self, url, **kwargs):
        params = kwargs.get("params") or {}
        sent = url
        if params:
            sent = f"{url}?trait={params.get('trait')}"
        self.calls.append(sent)

        if url.startswith(gwascat.TRAIT_SEARCH_URL):
            trait = _common.normalize(params.get("trait"))
            payload = self.search if trait == "gout" else EMPTY_SEARCH
            return payload, sent

        if "/singleNucleotidePolymorphisms/" in url:
            if self.snp_error is not None:
                raise self.snp_error
            variant = url.rsplit("/", 1)[-1]
            if variant not in SNP_PAYLOADS:
                raise _common.RequestFailed(
                    f"HTTP 404 from {url}",
                    status_code = 404,
                    url         = url,
                )
            return SNP_PAYLOADS[variant], sent

        if url.endswith("/efoTraits/MONDO_0005393"):
            return GOUT_TRAIT, sent

        raise _common.RequestFailed(
            f"HTTP 404 from {url}",
            status_code = 404,
            url         = url,
        )

    def fetch(
        self,
        url,
        deadline_seconds,
    ):
        self.calls.append(url)
        return self.associations, url


class MockedCase(unittest.TestCase):
    """Every test in a subclass runs against the recorded payloads, never the network."""

    def setUp(self):
        self.recorder = Recorder()
        self._get_json = _common.get_json
        self._fetch = gwascat._fetch_within_deadline
        _common.get_json = self.recorder.get_json
        gwascat._fetch_within_deadline = self.recorder.fetch

    def tearDown(self):
        _common.get_json = self._get_json
        gwascat._fetch_within_deadline = self._fetch

    def assert_envelope(
        self,
        env,
        status = None,
    ):
        self.assertIsInstance(env, dict)
        self.assertEqual(set(env), ENVELOPE_KEYS)
        self.assertEqual(env["tool"], "get_gwas_catalog")
        self.assertEqual(env["source"], gwascat.SOURCE)
        self.assertIn(env["status"], _common.STATUSES)
        self.assertLessEqual(DATA_KEYS, set(env["data"]))
        self.assertEqual(
            set(env["data"]) - DATA_KEYS,
            {"error"} if env["status"] == "error" else set(),
            "an error envelope adds data['error'] and nothing else",
        )
        self.assertIsInstance(env["caveats"], list)
        self.assertTrue(env["caveats"], "every envelope carries the associations-not-causal caveat")
        self.assertIn(
            "not causal estimates",
            " ".join(env["caveats"]),
        )
        for url in env["data"]["queries"]:
            self.assertTrue(url.startswith("https://"), url)
        if status is not None:
            self.assertEqual(env["status"], status)


# ---------------------------------------------------------------- pure helpers

class TestPureHelpers(unittest.TestCase):
    """No I/O at all: the three places where a wrong line would be invisible."""

    def test_ontology_id_becomes_a_short_form(self):
        self.assertEqual(gwascat._short_form("MONDO:0005393"), "MONDO_0005393")
        self.assertEqual(gwascat._short_form("MONDO_0005393"), "MONDO_0005393")
        self.assertEqual(gwascat._short_form(" EFO:0009767 "), "EFO_0009767")
        self.assertEqual(
            gwascat._short_form("http://purl.obolibrary.org/obo/MONDO_0005393"),
            "MONDO_0005393",
        )
        self.assertEqual(gwascat._short_form(""), "")
        self.assertEqual(gwascat._short_form(None), "")

    def test_risk_allele_name_splits_into_variant_and_allele(self):
        self.assertEqual(gwascat._split_risk_allele("rs2199936-A"), ("rs2199936", "A"))
        self.assertEqual(gwascat._split_risk_allele("rs10480300-?"), ("rs10480300", "?"))
        self.assertEqual(
            gwascat._split_risk_allele("chr4:88887327-A"),
            ("chr4:88887327", "A"),
        )
        self.assertEqual(gwascat._split_risk_allele("c.1580C>G-G"), ("c.1580C>G", "G"))
        self.assertEqual(gwascat._split_risk_allele("rs123"), ("rs123", None))

    def test_ranking_uses_the_exponent_not_the_underflowed_float(self):
        """5 of gout's 1,420 rows report pvalue exactly 0.0 with exponents from -324 to
        -1421. Sorting on the float ties them all and loses the strongest."""
        rows = [
            {"pvalue": 0.0,     "pvalue_mantissa": 5, "pvalue_exponent": -324},
            {"pvalue": 0.0,     "pvalue_mantissa": 1, "pvalue_exponent": -1421},
            {"pvalue": 1e-323,  "pvalue_mantissa": 1, "pvalue_exponent": -323},
            {"pvalue": 3e-23,   "pvalue_mantissa": 3, "pvalue_exponent": -23},
            {"pvalue": 3e-23,   "pvalue_mantissa": None, "pvalue_exponent": None},
            {"pvalue": None,    "pvalue_mantissa": None, "pvalue_exponent": None},
        ]
        order = [row["pvalue_exponent"] for row in sorted(rows, key=gwascat._pvalue_key)]
        self.assertEqual(order, [-1421, -324, -323, -23, None, None])
        self.assertIsNone(
            sorted(rows, key=gwascat._pvalue_key)[-1]["pvalue"],
            "a row with no usable p-value sorts last, never first",
        )


# ---------------------------------------------------------------- resolution paths

class TestOntologyIdPath(MockedCase):
    """1A's id reaches this resource directly. That is the whole reason 1C prefers it."""

    def test_short_form_is_used_directly_and_the_name_is_not_searched(self):
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_associations = 200,
            max_genes_from   = 0,
        )
        self.assert_envelope(env, "ok")
        self.assertEqual(env["data"]["efo_short_form"], "MONDO_0005393")
        self.assertEqual(env["data"]["efo_trait"], "gout")
        self.assertEqual(
            self.recorder.calls[0],
            "https://www.ebi.ac.uk/gwas/rest/api/efoTraits/MONDO_0005393",
        )
        self.assertIn("/efoTraits/MONDO_0005393/associations", env["url"])
        self.assertFalse(
            [url for url in self.recorder.calls if "findByEfoTrait" in url],
            "with a resolvable ontology id the trait name must not be searched",
        )
        self.assertIn(
            "Resolved through the ontology id",
            " ".join(env["caveats"]),
        )

    def test_a_label_that_disagrees_with_the_id_is_reported_not_silently_dropped(self):
        """1A's own label for MONDO:0005010 is "coronary artery disorder" while the user
        typed "coronary artery disease". The id wins, and the card must be told."""
        env = get_gwas_catalog(
            "gouty arthropathy",
            "MONDO:0005393",
            max_genes_from = 0,
        )
        self.assert_envelope(env, "ok")
        self.assertEqual(env["data"]["efo_trait"], "gout")
        self.assertIn(
            "The caller's label 'gouty arthropathy' is not this resource's own label "
            "'gout' for MONDO_0005393",
            " ".join(env["caveats"]),
        )

    def test_underscored_id_and_purl_uri_reach_the_same_trait(self):
        for identifier in ("MONDO_0005393", "http://purl.obolibrary.org/obo/MONDO_0005393"):
            env = get_gwas_catalog(
                "",
                identifier,
                max_genes_from = 0,
            )
            self.assert_envelope(env, "ok")
            self.assertEqual(env["data"]["efo_short_form"], "MONDO_0005393")


class TestTraitNameFallback(MockedCase):
    """No id, or an id this resource no longer knows."""

    def test_name_search_is_used_when_no_ontology_id_is_given(self):
        env = get_gwas_catalog(
            "gout",
            max_genes_from = 0,
        )
        self.assert_envelope(env, "ok")
        self.assertEqual(env["data"]["efo_short_form"], "MONDO_0005393")
        self.assertTrue(
            self.recorder.calls[0].startswith(gwascat.TRAIT_SEARCH_URL),
            self.recorder.calls,
        )
        self.assertIn(
            "Resolved through the trait-name search",
            " ".join(env["caveats"]),
        )

    def test_the_search_is_case_insensitive_like_the_real_endpoint(self):
        env = get_gwas_catalog(
            "GOUT",
            max_genes_from = 0,
        )
        self.assert_envelope(env, "ok")
        self.assertEqual(env["data"]["efo_trait"], "gout")

    def test_a_404_on_the_ontology_id_falls_back_to_the_name(self):
        """The Catalog moved many terms from EFO to MONDO, so 1A's id can 404 here.
        A 404 must not become an error envelope."""
        env = get_gwas_catalog(
            "gout",
            "EFO:0001645",
            max_genes_from = 0,
        )
        self.assert_envelope(env, "ok")
        self.assertEqual(env["data"]["efo_short_form"], "MONDO_0005393")
        caveats = " ".join(env["caveats"])
        self.assertIn("EFO_0001645 is not a GWAS Catalog trait (HTTP 404)", caveats)
        self.assertIn("migrated many terms from EFO to MONDO", caveats)

    def test_a_bare_string_where_a_list_was_sent_is_not_stringified(self):
        env = get_gwas_catalog(["gout"])
        self.assert_envelope(env, "ok")
        self.assertEqual(env["args"]["trait_label"], "gout")


class TestHonestEmpty(MockedCase):
    """Nothing found is labelled empty, with the reason, and never as "no association"."""

    def test_nonsense_trait_is_empty_with_an_honest_caveat(self):
        env = get_gwas_catalog("zzqx-not-a-trait")

        self.assert_envelope(env, "empty")
        self.assertEqual(env["data"]["associations"], [])
        self.assertEqual(env["data"]["n_associations_total"], 0)
        self.assertIsNone(env["data"]["efo_short_form"])

        caveats = " ".join(env["caveats"])
        self.assertIn("No GWAS Catalog trait is named 'zzqx-not-a-trait'", caveats)
        self.assertIn("Empty is not evidence of no association", caveats)
        self.assertFalse(
            [url for url in self.recorder.calls if "/associations" in url],
            "an unresolved trait must not trigger the expensive pull",
        )

    def test_a_metabolite_by_its_bare_name_says_what_to_call_it_instead(self):
        env = get_gwas_catalog("glycine")
        self.assert_envelope(env, "empty")
        self.assertIn("glycine measurement", " ".join(env["caveats"]))

    def test_no_trait_and_no_id_sends_no_request_at_all(self):
        env = get_gwas_catalog("")
        self.assert_envelope(env, "empty")
        self.assertEqual(env["data"]["queries"], [])
        self.assertEqual(
            env["url"],
            "",
            "url is the URL actually sent, and none was",
        )

    def test_a_resolved_trait_with_no_associations_is_empty_not_ok(self):
        self.recorder.associations = {"_embedded": {"associations": []}}
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
        )
        self.assert_envelope(env, "empty")
        self.assertEqual(env["data"]["n_associations_total"], 0)
        caveats = " ".join(env["caveats"])
        self.assertIn("holds no curated association under it", caveats)
        self.assertIn("Empty is not evidence of no association", caveats)


# ---------------------------------------------------------------- parsing and caps

class TestAssociationParsing(MockedCase):
    @classmethod
    def setUpClass(cls):
        cls.maxDiff = None

    def setUp(self):
        super().setUp()
        self.env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_associations = 200,
            max_genes_from   = 0,
        )

    def test_every_recorded_row_is_parsed(self):
        self.assert_envelope(self.env, "ok")
        self.assertEqual(self.env["data"]["n_associations_total"], 6)
        self.assertEqual(self.env["data"]["n_associations_kept"], 6)
        self.assertEqual(
            len(self.env["data"]["associations"]),
            self.env["data"]["n_associations_kept"],
        )

    def test_odds_ratio_row(self):
        row = self.env["data"]["associations"][0]
        self.assertEqual(row["rsid"], "rs2231142")
        self.assertEqual(row["risk_allele"], "T")
        self.assertEqual(row["or_per_copy"], 1.7349871)
        self.assertIsNone(row["beta"])
        self.assertEqual(row["author_reported_genes"], ["ABCG2"])
        self.assertEqual(row["pvalue"], 0.0)
        self.assertEqual(row["pvalue_mantissa"], 1)
        self.assertEqual(row["pvalue_exponent"], -1421)

    def test_beta_row_keeps_unit_and_direction(self):
        rows = {row["rsid"]: row for row in self.env["data"]["associations"]}
        row = rows["rs4475146"]
        self.assertEqual(row["beta"], 0.4682)
        self.assertEqual(row["beta_unit"], "unit")
        self.assertEqual(row["beta_direction"], "decrease")
        self.assertIsNone(row["or_per_copy"])
        self.assertEqual(row["author_reported_genes"], ["SLC2A9"])

    def test_a_positional_variant_id_is_kept_as_written(self):
        rows = {row["rsid"]: row for row in self.env["data"]["associations"]}
        self.assertIn("chr4:88887327", rows)
        self.assertEqual(rows["chr4:88887327"]["risk_allele"], "A")

    def test_rows_are_sorted_strongest_first_by_reported_exponent(self):
        order = [row["rsid"] for row in self.env["data"]["associations"]]
        self.assertEqual(
            order,
            [
                "rs2231142",
                "rs2728099",
                "chr4:88887327",
                "rs4475146",
                "rs2199936",
                "rs10480300",
            ],
        )

    def test_underflow_and_not_reported_genes_are_flagged(self):
        caveats = " ".join(self.env["caveats"])
        self.assertIn("underflowed double precision", caveats)
        self.assertIn(
            "1 of the kept association(s) give the author-reported gene as \"NR\"",
            caveats,
        )
        self.assertIn(
            "4 of the 6 kept association(s) carry an author-reported gene entry",
            caveats,
        )


class TestCaps(MockedCase):
    def test_only_the_strongest_survive_and_a_caveat_says_so(self):
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_associations = 3,
            max_genes_from   = 0,
        )
        self.assert_envelope(env, "ok")
        self.assertEqual(env["data"]["n_associations_total"], 6)
        self.assertEqual(env["data"]["n_associations_kept"], 3)
        self.assertEqual(
            [row["rsid"] for row in env["data"]["associations"]],
            ["rs2231142", "rs2728099", "chr4:88887327"],
        )
        self.assertIn(
            "Capped: 6 association(s) were retrieved and the strongest 3 by p-value are "
            "kept; 3 weaker row(s) were dropped after download.",
            env["caveats"],
        )

    def test_no_cap_caveat_when_the_cap_did_not_bite(self):
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_associations = 200,
            max_genes_from   = 0,
        )
        self.assertNotIn(
            "Capped:",
            " ".join(env["caveats"]),
        )

    def test_the_no_pagination_fact_is_always_stated(self):
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_genes_from = 0,
        )
        self.assertIn(
            "ignores `size` and `page`",
            " ".join(env["caveats"]),
        )


class TestMappedGenes(MockedCase):
    def test_enrichment_is_capped_and_the_shape_is_stable(self):
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_associations = 200,
            max_genes_from   = 2,
        )
        self.assert_envelope(env, "ok")

        queried = [url for url in self.recorder.calls if "singleNucleotidePolymorphisms" in url]
        self.assertEqual(
            len(queried),
            2,
            "one request per variant, capped at max_genes_from",
        )
        self.assertTrue(queried[0].endswith("/rs2231142"), queried)
        self.assertTrue(queried[1].endswith("/rs2728099"), queried)

        genes = env["data"]["mapped_genes"]
        self.assertEqual(len(genes), 10)
        for row in genes:
            self.assertEqual(set(row), MAPPED_GENE_KEYS)
        self.assertEqual(
            {row["rsid"] for row in genes},
            {"rs2231142", "rs2728099"},
        )
        self.assertIn("ABCG2", {row["gene"] for row in genes})

        self.assertIn(
            "capped at the strongest 2 variant(s) by p-value: 2 variant(s) queried out "
            "of 6 kept association(s), 10 gene row(s) returned.",
            " ".join(env["caveats"]),
        )

    def test_both_annotation_sources_are_kept_with_their_own_distance(self):
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_genes_from = 1,
        )
        rows = [row for row in env["data"]["mapped_genes"] if row["gene"] == "RPL31P24"]
        self.assertEqual(
            sorted((row["source"], row["distance"]) for row in rows),
            [("Ensembl", 32408), ("NCBI", 32368)],
            "the two sources disagree; neither is silently dropped",
        )
        caveats = " ".join(env["caveats"])
        self.assertIn("the row count is not a gene count", caveats)
        self.assertIn("is_closest_gene", caveats)

    def test_the_gene_the_variant_sits_in_is_reported_even_though_it_is_not_flagged_closest(self):
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_genes_from = 1,
        )
        inside = [
            row for row in env["data"]["mapped_genes"]
            if row["distance"] == 0 and row["is_intergenic"] is False
        ]
        self.assertTrue(inside, "ABCG2 contains rs2231142")
        self.assertEqual({row["gene"] for row in inside}, {"ABCG2"})
        self.assertTrue(
            all(row["is_closest_gene"] is False for row in inside),
            "this is the trap the caveat warns about; if it ever changes, re-check it",
        )

    def test_a_variant_with_no_annotation_is_reported_not_hidden(self):
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_genes_from = 3,
        )
        self.assertIn(
            "1 of the 3 queried variant(s) returned no genomic context (chr4:88887327)",
            " ".join(env["caveats"]),
        )

    def test_max_genes_from_above_ten_is_clamped_and_said_so(self):
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_genes_from = 50,
        )
        self.assert_envelope(env, "ok")
        self.assertIn(
            "max_genes_from=50 was clamped to 10",
            " ".join(env["caveats"]),
        )

    def test_zero_means_associations_only(self):
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_genes_from = 0,
        )
        self.assertEqual(env["data"]["mapped_genes"], [])
        self.assertFalse([url for url in self.recorder.calls if "singleNucleotide" in url])


# ---------------------------------------------------------------- failure paths

class TestFailures(MockedCase):
    def test_the_deadline_becomes_an_error_envelope_with_the_slow_caveat(self):
        """The associations body dribbles out over minutes, so the module aborts on
        elapsed time. That abort must never look like "this trait has no associations"."""
        def too_slow(url, deadline_seconds):
            raise _common.RequestFailed(
                f"GET {url} exceeded the {deadline_seconds}s wall-clock deadline after "
                f"{deadline_seconds}s and 4194304 bytes; the response was still arriving. "
                f"Partial JSON cannot be parsed, so nothing was retrieved.",
                url = url,
            )

        gwascat._fetch_within_deadline = too_slow
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
        )

        self.assert_envelope(env, "error")
        self.assertIn("wall-clock deadline", env["data"]["error"])
        caveats = " ".join(env["caveats"])
        self.assertIn("aborts at a 120 s wall-clock deadline", caveats)
        self.assertIn("NEVER evidence that the trait has no associations", caveats)
        self.assertIn("no retrieved association either way", caveats)
        self.assertEqual(env["data"]["associations"], [])

    def test_an_http_failure_on_the_snp_endpoint_keeps_the_associations(self):
        """The expensive half succeeded. Throwing it away because the cheap half fell
        over would turn a real locus list into an evidence gap."""
        self.recorder.snp_error = _common.RequestFailed(
            "HTTP 503 from the SNP endpoint",
            status_code = 503,
            url         = "https://www.ebi.ac.uk/gwas/rest/api/singleNucleotidePolymorphisms/rs2231142",
        )
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_genes_from = 2,
        )

        self.assert_envelope(env, "error")
        self.assertEqual(env["data"]["n_associations_kept"], 6)
        self.assertEqual(len(env["data"]["associations"]), 6)
        caveats = " ".join(env["caveats"])
        self.assertIn("already parsed are kept", caveats)
        self.assertNotIn("no retrieved association either way", caveats)
        self.assertNotIn(
            "aborts at a 120 s wall-clock deadline",
            caveats,
            "this failure was not the slow endpoint; do not blame it",
        )

    def test_a_failure_on_the_trait_search_becomes_an_error_envelope(self):
        def boom(url, **kwargs):
            raise _common.RequestFailed(
                "simulated outage",
                status_code = 503,
                url         = url,
            )

        _common.get_json = boom
        env = get_gwas_catalog("gout")

        self.assert_envelope(env, "error")
        self.assertEqual(env["data"]["error"], "simulated outage")

    def test_an_unexpected_exception_does_not_escape(self):
        def explode(url, **kwargs):
            raise RuntimeError("something nobody planned for")

        _common.get_json = explode
        env = get_gwas_catalog("gout")

        self.assert_envelope(env, "error")
        self.assertIn("something nobody planned for", env["data"]["error"])


class TestLedger(MockedCase):
    def tearDown(self):
        super().tearDown()
        ledger.stop()
        target = ledger.path_for(LEDGER_STEM)
        if target.exists():
            target.unlink()

    def test_every_return_path_is_recorded(self):
        ledger.start(LEDGER_STEM)
        get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_genes_from = 0,
        )
        get_gwas_catalog("zzqx-not-a-trait")

        records = ledger.load(LEDGER_STEM)
        self.assertEqual(len(records), 2)
        self.assertEqual([row["tool"] for row in records], ["get_gwas_catalog"] * 2)
        self.assertEqual([row["status"] for row in records], ["ok", "empty"])


# ---------------------------------------------------------------- live

class TestLiveSmoke(unittest.TestCase):
    """Three small live requests. If EBI changes any of these shapes, gwascat.py is
    wrong and every mocked test above is testing a fiction."""

    def test_the_shapes_the_module_is_built_on_still_hold(self):
        trait, url = _common.get_json(
            gwascat.TRAIT_URL.format(short_form="MONDO_0005393"),
            timeout = 30,
        )
        self.assertEqual(trait["shortForm"], "MONDO_0005393")
        self.assertEqual(trait["trait"], "gout")

        payload, url = _common.get_json(
            gwascat.TRAIT_SEARCH_URL,
            params  = {"trait": "gout"},
            timeout = 30,
        )
        traits = payload["_embedded"]["efoTraits"]
        self.assertEqual([row["shortForm"] for row in traits], ["MONDO_0005393"])

        payload, url = _common.get_json(
            gwascat.SNP_URL.format(variant="rs1165151"),
            timeout = 30,
        )
        contexts = payload["genomicContexts"]
        self.assertTrue(contexts)
        genes = {context["gene"]["geneName"] for context in contexts}
        self.assertIn(
            "SLC17A3",
            genes,
            "rs1165151 is the urate transporter locus; SLC17A3 is the anchor",
        )
        for context in contexts:
            for field in ("distance", "isIntergenic", "source", "isClosestGene"):
                self.assertIn(field, context)

    def test_a_metabolite_is_named_as_a_measurement_here(self):
        """The single most useful thing a caller can know about this resource."""
        bare, _ = _common.get_json(
            gwascat.TRAIT_SEARCH_URL,
            params  = {"trait": "glycine"},
            timeout = 30,
        )
        measurement, _ = _common.get_json(
            gwascat.TRAIT_SEARCH_URL,
            params  = {"trait": "glycine measurement"},
            timeout = 30,
        )
        self.assertEqual(bare["_embedded"]["efoTraits"], [])
        self.assertEqual(
            measurement["_embedded"]["efoTraits"][0]["shortForm"],
            "EFO_0009767",
        )


@unittest.skipUnless(SLOW_TESTS, "set METABOCAUSAL_SLOW_TESTS=1 (this pulls 3 MB over ~2 minutes)")
class TestLiveSlow(unittest.TestCase):
    """The real thing, end to end, on the pair 1B anchors on."""

    def test_gout_by_ontology_id(self):
        started = time.monotonic()
        env = get_gwas_catalog(
            "gout",
            "MONDO:0005393",
            max_associations = 20,
            max_genes_from   = 2,
        )
        elapsed = time.monotonic() - started

        self.assertEqual(set(env), ENVELOPE_KEYS)
        self.assertEqual(env["status"], "ok")
        self.assertLess(
            elapsed,
            gwascat.ASSOCIATIONS_DEADLINE_SECONDS + 30,
            "the deadline must bound this call",
        )
        self.assertGreater(env["data"]["n_associations_total"], 1000)
        self.assertEqual(env["data"]["n_associations_kept"], 20)

        genes = {row["gene"] for row in env["data"]["mapped_genes"]}
        self.assertTrue(
            {"ABCG2", "SLC2A9"} & genes,
            f"gout's strongest loci are ABCG2 and SLC2A9; got {sorted(genes)}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
