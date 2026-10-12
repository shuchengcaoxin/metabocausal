"""Does this model-written prose say anything the run does not support.

    import validate_card
    findings = validate_card.validate(prose_fields, run)
    if findings:
        ...discard the prose, ship the deterministic card, record the findings

This is the component that lets model prose onto a card at all. Without it, section 9 is
a paragraph nobody can check sitting underneath ten sections that were built to be
checkable, and the card as a whole stops being quotable.

WHAT IT RETURNS. A list of `Finding`. Empty means the prose may ship. Non-empty means it
may not - there is no severity ladder and no "warning" tier, because a card that prints
prose flagged as questionable has answered the question badly. The findings exist to be
logged and to tell the next person what went wrong, not to be weighed up.

THREE KINDS OF CHECK, AND THEY ARE NOT EQUALLY STRONG. Say so wherever this is documented.

  V1 and V5 are TRACEABILITY checks and they are rigorous. Every number and every
  identifier in the prose is looked up in the run's own values. A model cannot invent a
  dataset id, a gene, an ontology term, a trial number or an effect size and have it pass,
  because the check is set membership against what was actually retrieved.

  V2, V3, V4 and V6 are LANGUAGE checks and they are heuristics. They match phrase
  patterns against the sentence. They will catch the obvious forms of the four claims this
  project most wants to avoid, and a determined paraphrase will get past them. They are
  guardrails, not proofs, and nothing downstream should describe them as proofs.

  V7 is MIXED and must be described as mixed. Its first half is rigorous: which gene
  symbols this run holds only as Human-GEM reaction context is set membership, computed
  structurally from the run. Its second half is a phrase heuristic in the V2/V3/V4/V6
  sense: whether the sentence quoting such a symbol frames it as reaction context, and
  whether it nonetheless claims a nomination. Do not call V7 a proof.

WHY V7 EXISTS. Being in the run and being nominated by the run are not the same fact, and
V5 cannot tell them apart - it is membership against every string the run carries. A
Human-GEM lookup retrieves the genes that sit on a metabolite's reactions; it nominates
nothing, and the card says so in its own words ("reaction membership, not genetic
effectors"). Before V7, a run whose atlas nomination layer was never queried still carried
GCSH and GLDC as strings, so "GCSH and GLDC are the effector genes this run nominates"
passed V5 - while section 5 of the same card said the nomination layer was not queried.
Prose that contradicts the deterministic section above it is the one thing this validator
exists to stop. V7 binds nomination wording to nomination evidence: a gene the run holds
only as reaction context may be quoted only in a sentence that says it is reaction
context, and never as a gene this run nominated.

V7's exemption is a DISCLAIMING CONSTRUCTION (NOMINATION_DISCLAIMER), not a generic
negation. A sentence-wide negation test would excuse "GCSH and GLDC are the effector genes
this run nominates, not merely a reaction list" - the same hole this file's V4 comment
documents, reopened on the newer rule. The negation has to govern the nomination itself, or
to name the layer that was not queried.

WHY UNTRACEABLE NUMBERS ARE REJECTED OUTRIGHT rather than allowed with a derivation
label. A label is only worth anything if something checks it, and checking a claimed
derivation means re-deriving it. The prompt tells the model to compute nothing; a number
that is not in the run is therefore either a computation it was told not to do or an
invention, and both are rejected. Counts are the one accommodation: the length of any list
in the run is treated as traceable, because "22 estimates" is a fact about the run that
the run does not happen to store as a number.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# Rounding a source value is accepted as a faithful quote only from this many significant
# figures up; see traceable_number for why one and two figures are worthless as a check.
MIN_ROUNDING_DIGITS = 3

ENVELOPE_KEYS = {
    "tool", "args", "source", "url", "retrieved_at", "status", "data", "caveats",
}

# Identifier shapes this project actually uses. Each is checked against the run's own
# strings, so the pattern only has to RECOGNISE an identifier - deciding whether it is
# real is set membership, not a regex.
IDENTIFIER_PATTERNS = {
    "GWAS dataset": re.compile(r"\b[a-z]{2,6}-[a-z]-[A-Za-z0-9_.]+\b"),
    "ontology term": re.compile(r"\b(?:CHEBI|MONDO|DOID|EFO|HP|GO|UBERON)[:_]\d+\b", re.I),
    "trial": re.compile(r"\bNCT\d{6,9}\b", re.I),
    "Ensembl gene": re.compile(r"\bENSG\d{6,13}\b", re.I),
    "rsID": re.compile(r"\brs\d{2,12}\b", re.I),
}

# A gene symbol shape, checked only against the run's own strings plus the vocabulary
# below. This is the weakest of the traceability checks because gene symbols and
# scientific acronyms are the same shape; the allowlist is what keeps it usable.
GENE_SHAPE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")

# Words that look like gene symbols and are not. Extend this list rather than loosening
# GENE_SHAPE: a false positive here costs a rejected paragraph, a false negative ships an
# invented gene, and those are not the same size of mistake.
NON_GENE_VOCABULARY = {
    # methods and statistics
    "MR", "IVW", "FE", "RE", "DF", "HF", "WM", "MBE", "SE", "CI", "OR", "RR", "HR",
    "SD", "SEM", "PVE", "AIC", "BIC", "LD", "MAF", "EAF", "QC", "FDR", "BH",
    # data types and sources
    "GWAS", "SNP", "SNPS", "QTL", "EQTL", "PQTL", "MQTL", "SQTL", "CLPP", "PP",
    "EVE", "REST", "API", "URL", "CSV", "JSON", "HTTP", "HTTPS", "ID", "IDS",
    # ontologies and registries, as bare prefixes
    "CHEBI", "MONDO", "DOID", "EFO", "HP", "GO", "NCT", "ENSG", "UKB", "IEU", "EBI",
    "PUBCHEM", "OLS", "GNOMAD", "CHEMBL", "OPENGWAS", "EPIGRAPHDB",
    # the states, and ordinary capitals that survive the shape test
    "A", "B", "C", "H0", "H1", "H2", "H3", "H4", "UK", "US", "EU", "NA", "N",
    "AND", "OR", "NOT", "THE", "ALL", "ONE", "TWO", "NO", "IT", "IS", "AS", "AT",
    "TMAO", "LOEUF", "PLI", "OE", "LOF", "MIS",
}

# ---------------------------------------------------------------- biochemical context
#
# Tools whose genes are reaction membership rather than a nomination. Matched on the tool
# name inside the eight-key envelope shape, the way _envelope_statuses matches statuses,
# so this keeps working wherever in the run the envelope sits.
BIOCHEMICAL_CONTEXT_TOOLS = {"map_metabolite_to_genes_gem"}

# The sentence says it is talking about reaction context. The vocabulary is the card's
# own: section 5 prints "reaction membership, not genetic effectors" and section 7 prints
# "Human-GEM membership is biochemical context only."
BIOCHEMICAL_CONTEXT = re.compile(
    r"\b(?:human[\s-]?gem|biochemical|biochemistry|reaction|reactions|reaction-linked|"
    r"enzyme|enzymes|enzymatic|gpr|gene[\s-]protein[\s-]reaction|"
    r"metabolic (?:network|model|map|reconstruction|pathway)|compartment\w*|"
    r"complex member|via[\s-]enzyme|stoichiometr\w*|catalys\w*|substrate|metabolite of)\b",
    re.I,
)

# The sentence claims the gene was nominated, implicated, prioritised or picked out as
# something to act on. Deliberately wider than the word "nominate": a sentence does not
# have to use this project's own vocabulary to say the thing V7 exists to stop, and
# "the genes to take forward" is the same claim as "the genes this run nominates". This
# half is a phrase heuristic and is described as one everywhere V7 is documented; it fails
# CLOSED (a context-only symbol in a sentence carrying any of these tokens is rejected
# unless the sentence disclaims the nomination itself) rather than open.
NOMINATION_CLAIM = re.compile(
    r"\b(?:effector\s+gene\w*|effector\s+candidate\w*|nominat\w+|implicat\w+|"
    r"causal\s+gene\w*|candidate\s+effector\w*|responsible\s+gene\w*|driver\s+gene\w*|"
    r"prioritis\w+|prioritiz\w+|targets?|"
    r"tak(?:e|es|en|ing)\s+forward|carry\s+forward|carried\s+forward|"
    r"to\s+watch|worth\s+(?:pursuing|testing|following)|follow(?:ed|ing)?\s+up|"
    r"(?:lead|top|best|prime)\s+candidate\w*|most\s+promising|actionable|"
    r"next\s+step\w*|shortlist\w*|short-list\w*|recommend\w*|"
    r"flag(?:s|ged|ging)?\s+for|select(?:s|ed|ion)?\s+for)\b",
    re.I,
)

# V7's exemption, and NEGATION cannot serve as it - for exactly the reason the V4 comment
# below gives about its own rule. A sentence-wide negation test excuses any sentence that
# happens to carry a negated clause, so
#
#   "GCSH and GLDC are the effector genes this run nominates, not merely a reaction list."
#
# would clear the nomination flag and then satisfy the reaction-context branch, printing a
# sentence that is MORE misleading than the one the rule was written for.
#
# What separates a correct sentence from a wrong one is a DISCLAIMING construction: the
# negation has to govern the nomination itself, or to name the layer that was not queried.
# All three of these are sentences the project wants on a card:
#
#   render's own wording: "reaction membership is not an effector-gene nomination"
#   a live model:         "Human-GEM reaction membership does not nominate GCSH..."
#   stating the absence:  "The atlas nomination layer was not queried in this run..."
#
# The third is why the disclaimer also clears the reaction-context requirement: a sentence
# whose whole job is to state that nothing was nominated should not be rejected for failing
# to repeat a biochemistry word.
NOMINATION_DISCLAIMER = re.compile(
    r"\b(?:"
    r"(?:is|are|was|were|has|have|had)\s+(?:never\s+|not\s+)(?:been\s+)?"
    r"(?:an?\s+|the\s+)?(?:[a-z]+[\s-])?"
    r"(?:nominat\w+|nomination\w*|effector[\s-]gene\w*|effector\s+candidate\w*|"
    r"candidate\s+effector\w*)"
    r"|(?:do|does|did)\s+not\s+(?:\w+\s+){0,2}?(?:nominat\w+|implicat\w+|prioriti[sz]\w+)"
    r"|not\s+(?:an?\s+|the\s+)?(?:[a-z]+[\s-])?"
    r"(?:nomination\w*|effector[\s-]gene\w*|candidate\s+effector\w*)"
    r"|(?:nominat\w+|implicat\w+)\s+(?:nothing|no\s+)"
    r"|no\s+(?:effector\s+)?gene\w*\s+(?:was|were|is|are)\s+nominat\w+"
    r"|nothing\s+(?:\w+\s+){0,3}?(?:nominat\w+|implicat\w+)"
    r"|(?:nomination|effector[\s-]gene\w*|atlas)\s+(?:\w+\s+){0,2}?"
    r"(?:was|were|is|are)\s+not\s+(?:queried|run|reached|available|assessed)"
    r"|rather\s+than\s+(?:an?\s+|the\s+)?(?:nomination\w*|effector[\s-]gene\w*|"
    r"candidate\s+effector\w*)"
    r"|instead\s+of\s+(?:an?\s+|the\s+)?(?:nomination\w*|effector[\s-]gene\w*)"
    r")",
    re.I,
)

# ---------------------------------------------------------------- language patterns
#
# Each entry is (rule, human name, pattern, whether a nearby negation excuses it).
# Negation matters: "candidate genes do not prove mediation" is a sentence this project
# WANTS on a card, and a bare match on 'mediation' would reject it.

NEGATION = re.compile(
    r"\b(?:not|never|cannot|can't|no|without|nothing|neither|nor|does not|do not|"
    r"is not|are not|isn't|aren't|doesn't|don't|rather than|instead of|unproven|"
    r"unresolved|untested)\b",
    re.I,
)

# V4 needs its own exemption, and NEGATION cannot serve as it. The phrase being matched -
# "no effect", "null effect" - CONTAINS a negation word, so a generic negation test
# excuses the very sentence the rule exists to catch ("there is no effect" holds "no").
#
# What separates a correct sentence from a wrong one here is not the presence of a
# negation but a DISCLAIMING construction: the writer naming the biological negative in
# order to deny it. Both of these are sentences the project wants:
#
#   render.EMPTY_ARM: "not available in this snapshot - not evidence of no effect"
#   a live model:     "...coverage gaps rather than biological proof of no effect"
#
# The first is the deterministic card's own wording, which an earlier version of this rule
# rejected. A validator that refuses the card it is protecting is wrong about the rule,
# not about the card.
V4_DISCLAIMER = re.compile(
    r"\b(?:not evidence (?:of|for)|not proof (?:of|for)|not a demonstration|"
    r"rather than|instead of|does not mean|do not mean|is not the same as|"
    r"should not be (?:read|taken|understood)|cannot be (?:read|taken)|"
    r"absence of (?:retrieved|evidence)|not a (?:biological|scientific) )"
    # Process framing. "no causal relationship could be EVALUATED" is a statement about
    # whether the analysis happened, not about what it found - and on a State C run that
    # is most of what there is to say. Note these verbs describe the ANALYSIS; "was found"
    # is deliberately absent, because "no effect was found" is a claim about a result.
    r"|(?:could|can) (?:not )?be (?:evaluated|assessed|computed|calculated|tested|"
    r"performed|established|determined|examined|loaded|retrieved|generated|reported)"
    r"|(?:was|were) (?:not )?(?:generated|retrieved|returned|loaded|reported|computed|"
    r"evaluated|assessed|performed|queried|attempted)",
    re.I,
)

LANGUAGE_RULES = [
    (
        "V2", "evidence state presented as proof",
        re.compile(
            r"\b(?:proves?|proven|proof of|confirms?|confirmed|conclusive(?:ly)?|"
            r"definitive(?:ly)?|establishes? that|demonstrates? that|"
            r"certainty (?:of|that)|beyond doubt|settles? (?:the )?question)\b",
            re.I,
        ),
        True,
    ),
    (
        "V3", "independent results joined into a causal chain",
        re.compile(
            r"\b(?:mediat(?:e|es|ed|ing|ion|or|ors)|acts? through|acting through|"
            r"operates? through|causal chain|causal pathway|pathway from|"
            r"explains? the effect|is the mechanism by which)\b",
            re.I,
        ),
        True,
    ),
    (
        "V4", "a missing, skipped or failed source described as a biological negative",
        re.compile(
            # "no effect" is a claim about biology. "no effect ESTIMATE", "no association
            # ROWS", "no association DATA" are claims about retrieval - which is exactly
            # what this project wants a model to say, and what a live State C run says
            # constantly. The lookahead is what separates the two; without it the rule
            # rejects the correct sentence and the incorrect one alike.
            r"\b(?:no (?:causal )?(?:effect|association|relationship|link|influence)"
            r"(?!\s+(?:estimate|estimates|row|rows|data|record|records|entr(?:y|ies)|"
            r"value|values|result|results|statistic|statistics|analys(?:is|es)|"
            r"evidence|information)\b)|"
            r"null (?:effect|result|finding)|rules? out|ruled out|"
            r"shows? there is no|evidence of no |no evidence of an effect|"
            r"is not causal|has no impact)\b",
            re.I,
        ),
        V4_DISCLAIMER,
    ),
    (
        "V6", "colocalisation treated as something that can move the state",
        re.compile(
            r"(?=.*\b(?:H4|H3|CLPP|colocalis|colocaliz)\w*\b)"
            r"(?=.*\b(?:state [ABC]|upgrade[sd]?|downgrade[sd]?|promote[sd]?|"
            r"reclassif\w+|moves? (?:it )?(?:to|from)|raises? (?:it )?to)\b)",
            re.I,
        ),
        True,
    ),
]


@dataclass(frozen=True)
class Finding:
    """One reason this prose may not ship."""

    rule:   str
    name:   str
    detail: str
    field:  str = ""
    excerpt: str = ""

    def __str__(self) -> str:
        where = f" [{self.field}]" if self.field else ""
        return f"{self.rule}{where}: {self.detail}"


# ---------------------------------------------------------------- reading the run

def _walk(value):
    """Every scalar in a nested structure, depth first."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _walk(item)
    else:
        yield value


def _list_lengths(value) -> set:
    """The length of every list in the run.

    'retrieved 22 estimates' is true of a run that nowhere stores the number 22. Treating
    list lengths as traceable is the one place derived arithmetic is allowed, and it is
    allowed because counting what came back is not computing a new scientific quantity."""
    found = set()
    if isinstance(value, dict):
        for item in value.values():
            found |= _list_lengths(item)
    elif isinstance(value, (list, tuple)):
        found.add(len(value))
        for item in value:
            found |= _list_lengths(item)
    return found


NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")

# Models write p-values the way a person would: 1.8x10^-37 with a multiplication sign and
# Unicode superscripts. Left alone, NUMBER pulls '1.8' and '10' out of that and silently
# drops the exponent that gives the value its meaning - so a faithful quote is checked as
# a bare 1.8 and a wildly wrong one would be too. Normalising first is a parsing fix, not
# a loosening: the whole value reaches the matcher and is judged as one number.
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
SCIENTIFIC = re.compile(
    r"(\d(?:[.,]\d+)?)\s*[×x*]\s*10\s*\^?\s*([-+]?\d+)",
    re.I,
)


def normalise_notation(text: str) -> str:
    """Rewrite human scientific notation into the form NUMBER can read.

    '1.8x10^-37', '1.8 x 10^-37' and the Unicode superscript spelling all become
    '1.8e-37'. Nothing else about the text changes."""
    converted = str(text).translate(SUPERSCRIPTS)
    # A superscript run sits directly after '10' once translated, with no caret.
    converted = re.sub(r"(10)\s*([-+]\d+)\b", r"\1^\2", converted)
    return SCIENTIFIC.sub(lambda m: f"{m.group(1).replace(',', '.')}e{m.group(2)}", converted)


@dataclass
class SourceIndex:
    """Everything the prose is allowed to say, derived from the run alone."""

    strings:  set
    numbers:  set
    statuses: dict
    context_only_genes: set = field(default_factory=set)

    def has_string(self, text: str) -> bool:
        return _normalise_id(text) in self.strings

    def is_context_only_gene(self, text: str) -> bool:
        """Does the run hold this gene ONLY as biochemical reaction context.

        True means the run retrieved the symbol from a Human-GEM lookup and from nowhere
        else, so nothing in the run nominates it. False means either that the run does not
        carry it at all - V5's business, not V7's - or that some other arm carries it too,
        in which case V7 has no opinion and the prose stands on that other arm."""
        return _normalise_id(text) in self.context_only_genes


def _normalise_id(text: str) -> str:
    """Identifier comparison ignores case and the ':' / '_' split, because the same term
    is written both ways across this project's sources (MONDO:0005393, MONDO_0005393)."""
    return str(text).strip().casefold().replace("_", ":")


def _envelope_statuses(value, found: dict) -> dict:
    """Every envelope's tool -> status, found structurally rather than by key name.

    Reading these by walking for the eight-key shape means this validator keeps working
    when a caller passes the pipeline's run, the cached demo's run, or a subset."""
    if isinstance(value, dict):
        if ENVELOPE_KEYS.issubset(value.keys()):
            found[str(value.get("tool") or "?")] = str(value.get("status") or "?")
        for item in value.values():
            _envelope_statuses(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _envelope_statuses(item, found)
    return found


def _context_scopes(value, found: list) -> list:
    """Every Human-GEM envelope in the run, found by the eight-key shape and the tool name.

    Structural, not positional, for the same reason _envelope_statuses is: a validator
    that knew where the pipeline parks this envelope would stop restricting anything the
    day the layout moved, and a restriction that silently stops applying is worse than one
    that was never written."""
    if isinstance(value, dict):
        if ENVELOPE_KEYS.issubset(value.keys()) and str(value.get("tool") or "") in BIOCHEMICAL_CONTEXT_TOOLS:
            found.append(value)
        for item in value.values():
            _context_scopes(item, found)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _context_scopes(item, found)
    return found


def _gene_mentions(text: str) -> list:
    """Every gene symbol and Ensembl gene id written in one piece of text.

    The same two shapes V5 checks, read the same way, so a symbol V5 would look up is a
    symbol V7 can place."""
    tokens = list(IDENTIFIER_PATTERNS["Ensembl gene"].findall(str(text)))
    tokens.extend(
        token for token in GENE_SHAPE.findall(_mask_identifiers(str(text)))
        if token.upper() not in NON_GENE_VOCABULARY
    )
    return tokens


def _gene_tokens(value, skip=()) -> set:
    """Every gene token in a structure, skipping the subtrees in `skip` by identity."""
    for item in skip:
        if value is item:
            return set()
    tokens = set()
    if isinstance(value, dict):
        for key, item in value.items():
            tokens |= _gene_tokens(key, skip)
            tokens |= _gene_tokens(item, skip)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            tokens |= _gene_tokens(item, skip)
    elif value is not None and not isinstance(value, (bool, int, float)):
        tokens |= {_normalise_id(token) for token in _gene_mentions(str(value))}
    return tokens


def context_only_genes(run: dict) -> set:
    """Gene tokens this run holds only as Human-GEM reaction context.

    A symbol the atlas nominated, the dossier carried or the Catalog mapped is retrieved
    somewhere outside the Human-GEM envelope, so it is not in this set and V7 leaves it
    alone. A run with no Human-GEM envelope produces an empty set and costs nothing."""
    scopes = _context_scopes(run, [])
    if not scopes:
        return set()
    inside = set()
    for scope in scopes:
        inside |= _gene_tokens(scope)
    return inside - _gene_tokens(run, skip=scopes)


def source_index(run: dict) -> SourceIndex:
    """Build the set of values the prose may refer to.

    Deliberately schema-free: it walks whatever it is given. A validator that knew the
    envelope layout would start passing prose the day the layout changed."""
    strings: set = set()
    numbers: set = set()

    for scalar in _walk(run):
        if scalar is None or isinstance(scalar, bool):
            continue
        if isinstance(scalar, (int, float)):
            if math.isfinite(scalar):
                numbers.add(float(scalar))
            continue
        text = str(scalar)
        if not text.strip():
            continue
        strings.add(_normalise_id(text))
        # Numbers quoted inside a source string count: the classifier's reason sentence
        # is where '22 estimates' actually lives.
        for literal in NUMBER.findall(normalise_notation(text)):
            try:
                value = float(literal)
            except ValueError:
                continue
            if math.isfinite(value):
                numbers.add(value)
        # Identifiers embedded in longer strings have to be findable on their own.
        for pattern in IDENTIFIER_PATTERNS.values():
            for match in pattern.findall(text):
                strings.add(_normalise_id(match))
        for word in re.findall(r"[A-Za-z0-9:_.\-]+", text):
            strings.add(_normalise_id(word))

    numbers |= {float(length) for length in _list_lengths(run)}

    return SourceIndex(
        strings            = strings,
        numbers            = numbers,
        statuses           = _envelope_statuses(run, {}),
        context_only_genes = context_only_genes(run),
    )


# ---------------------------------------------------------------- number matching

def _significant(value: float, digits: int) -> float:
    """`value` rounded to `digits` significant figures."""
    if value == 0 or not math.isfinite(value):
        return 0.0
    return round(value, -int(math.floor(math.log10(abs(value)))) + (digits - 1))


def _sig_digits(literal: str) -> int:
    """How many significant figures the written form claims."""
    mantissa = literal.lower().split("e")[0].lstrip("+-")
    digits = mantissa.replace(".", "").lstrip("0")
    return max(len(digits), 1)


def traceable_number(literal: str, numbers: set) -> bool:
    """Is this written number one of the run's own values, at the precision it is written.

    The card prints effect sizes to four significant figures, so prose that quotes a
    printed value has fewer digits than the source. Comparing at the precision the PROSE
    claims accepts a faithful quotation and still rejects a number that was made up: an
    invention has to land on a real value's significant figures to pass."""
    try:
        value = float(literal)
    except ValueError:
        return False
    if not math.isfinite(value):
        return False

    digits = _sig_digits(literal)
    for source in numbers:
        if source == value:
            return True
        if source != 0 and abs(source - value) <= abs(source) * 1e-9:
            return True
        # Rounding is only accepted from three significant figures up. Below that the
        # match is too cheap to mean anything: at two figures '1.4' matches 1.3672, and at
        # one figure '5' matches everything between 4.5 and 5.5, so a made-up number would
        # pass by landing anywhere near a real one. Short literals must be exact - and the
        # short numbers that legitimately appear in prose are counts, which are exact.
        if digits >= MIN_ROUNDING_DIGITS and _significant(source, digits) == _significant(value, digits):
            return True
    return False


def _mask_identifiers(text: str) -> str:
    """Blank out identifiers before pulling numbers out of a sentence.

    'ieu-a-789' holds 789 and 'MONDO:0005393' holds 5393; neither is a quantity, and both
    are checked as identifiers by V5. Masking them first is what stops V1 reporting the
    digits inside an identifier it has no opinion about."""
    masked = normalise_notation(text)
    for pattern in IDENTIFIER_PATTERNS.values():
        masked = pattern.sub(" ", masked)
    return masked


# ---------------------------------------------------------------- the rules

def _check_numbers(field: str, text: str, index: SourceIndex) -> list:
    findings = []
    for literal in NUMBER.findall(_mask_identifiers(text)):
        if literal in {"+", "-", "."}:
            continue
        if not traceable_number(literal, index.numbers):
            findings.append(Finding(
                rule    = "V1",
                name    = "number not traceable to the run",
                detail  = f"{literal!r} does not appear in this run's retrieved values.",
                field   = field,
                excerpt = _excerpt(text, literal),
            ))
    return findings


def _check_identifiers(field: str, text: str, index: SourceIndex) -> list:
    findings = []
    seen = set()

    for kind, pattern in IDENTIFIER_PATTERNS.items():
        for token in pattern.findall(text):
            key = _normalise_id(token)
            if key in seen:
                continue
            seen.add(key)
            if not index.has_string(token):
                findings.append(Finding(
                    rule    = "V5",
                    name    = f"{kind} not present in the run",
                    detail  = f"{token!r} was not retrieved by this run.",
                    field   = field,
                    excerpt = _excerpt(text, token),
                ))

    # Masked: a gene-shaped fragment INSIDE an identifier (the GCST001790 of
    # ebi-a-GCST001790) is part of that identifier and was already checked as one above.
    for token in GENE_SHAPE.findall(_mask_identifiers(text)):
        key = _normalise_id(token)
        if key in seen or token.upper() in NON_GENE_VOCABULARY:
            continue
        seen.add(key)
        if not index.has_string(token):
            findings.append(Finding(
                rule    = "V5",
                name    = "gene symbol not present in the run",
                detail  = (
                    f"{token!r} reads as a gene symbol and was not nominated by this run. "
                    "If it is an abbreviation rather than a gene, add it to "
                    "validate_card.NON_GENE_VOCABULARY."
                ),
                field   = field,
                excerpt = _excerpt(text, token),
            ))
    return findings


def _check_context_genes(field: str, text: str, index: SourceIndex) -> list:
    """V7. A gene the run holds only as reaction context, quoted as something more.

    Sentence-local on purpose. A paragraph that names Human-GEM once and then lists the
    symbols in a bare sentence is rejected, and that is the cheaper mistake: a false
    positive costs a paragraph, a false negative ships a nomination the run never made.

    Three outcomes per sentence, and the order matters:

      the sentence disclaims the nomination itself (NOMINATION_DISCLAIMER) -> accepted,
        whether or not it also repeats a biochemistry word. This is the branch the card's
        own wording and every honest statement of the absence take.
      the sentence carries a nomination token and does NOT disclaim it -> rejected. A
        negation somewhere else in the sentence does not clear this; see the comment on
        NOMINATION_DISCLAIMER for the sentence that mechanism would have printed.
      neither -> the sentence has to say it is talking about reaction context."""
    if not index.context_only_genes:
        return []

    findings = []
    for sentence in _sentences(text):
        seen = set()
        disclaims_nomination = NOMINATION_DISCLAIMER.search(sentence) is not None
        claims_nomination = (
            NOMINATION_CLAIM.search(sentence) is not None
            and not disclaims_nomination
        )
        for token in _gene_mentions(sentence):
            key = _normalise_id(token)
            if key in seen or not index.is_context_only_gene(token):
                continue
            seen.add(key)
            if claims_nomination:
                findings.append(Finding(
                    rule    = "V7",
                    name    = "reaction-context gene presented as a nomination",
                    detail  = (
                        f"{token!r} is in this run only as Human-GEM reaction context, which is "
                        "reaction membership and not an effector-gene nomination. This run "
                        "nominated no effector gene under that symbol."
                    ),
                    field   = field,
                    excerpt = sentence,
                ))
            elif not disclaims_nomination and BIOCHEMICAL_CONTEXT.search(sentence) is None:
                findings.append(Finding(
                    rule    = "V7",
                    name    = "reaction-context gene quoted without its context",
                    detail  = (
                        f"{token!r} is in this run only as Human-GEM reaction context, and this "
                        "sentence does not say so. Name the reaction context in the same "
                        "sentence, or quote a gene this run retrieved from another arm. If it "
                        "is an abbreviation rather than a gene, add it to "
                        "validate_card.NON_GENE_VOCABULARY."
                    ),
                    field   = field,
                    excerpt = sentence,
                ))
    return findings


# "urate causes gout through SLC2A9" is a mediation claim that never says 'mediate'. This
# is checked in code rather than by regex because the test is 'the word after through is a
# GENE', and telling a gene symbol from a method abbreviation needs the vocabulary list -
# otherwise 'estimated via IVW' would be rejected as a causal chain.
GENE_ROUTE = re.compile(
    r"\b(?:through|via|by way of|by means of)\s+(?:the\s+)?([A-Z][A-Z0-9]{1,9})\b"
)


def _check_gene_mediation(field: str, text: str) -> list:
    findings = []
    for sentence in _sentences(text):
        if NEGATION.search(sentence):
            continue
        for symbol in GENE_ROUTE.findall(sentence):
            if symbol.upper() in NON_GENE_VOCABULARY:
                continue
            findings.append(Finding(
                rule    = "V3",
                name    = "independent results joined into a causal chain",
                detail  = (
                    f"routes the effect through {symbol!r}. A nominated gene and a "
                    "disease association are separate retrieved facts; this run tested no "
                    "gene-to-metabolite-to-disease chain."
                ),
                field   = field,
                excerpt = sentence,
            ))
    return findings


def _sentences(text: str) -> list:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", str(text)) if part.strip()]


def _check_language(field: str, text: str) -> list:
    findings = []
    for sentence in _sentences(text):
        for rule, name, pattern, negatable in LANGUAGE_RULES:
            match = pattern.search(sentence)
            if not match:
                continue
            # A negated form is usually this project's own house wording - "candidate
            # genes do not prove mediation" is a sentence the card should be able to say.
            # Most rules test that with NEGATION; V4 carries its own pattern, because the
            # phrase it matches contains a negation word itself.
            exemption = NEGATION if negatable is True else negatable
            if exemption is not False and exemption is not None and exemption.search(sentence):
                continue
            findings.append(Finding(
                rule    = rule,
                name    = name,
                detail  = f"{name}: {sentence!r}",
                field   = field,
                excerpt = sentence,
            ))
    return findings


def _excerpt(text: str, token: str, width: int = 60) -> str:
    position = text.find(token)
    if position < 0:
        return text[:width]
    start = max(0, position - width // 2)
    return text[start:position + len(token) + width // 2].strip()


# ---------------------------------------------------------------- entry point

def validate(fields, run: dict) -> list:
    """Every reason this prose may not ship. Empty list means it may.

    `fields` is the model's output: a dict of named prose blocks, or a single string.
    `run` is the completed run the prose is about.

    Never raises. A validator that can throw is a validator that can take down the
    deterministic card it exists to protect."""
    try:
        index = source_index(run)
    except Exception as exc:                            # noqa: BLE001 - deliberate boundary
        return [Finding(
            rule   = "V0",
            name   = "run could not be indexed",
            detail = f"The run could not be read for validation ({type(exc).__name__}: {exc}).",
        )]

    if isinstance(fields, str):
        fields = {"text": fields}
    if not isinstance(fields, dict):
        return [Finding(
            rule   = "V0",
            name   = "prose was not usable",
            detail = f"Expected named prose blocks or a string, got {type(fields).__name__}.",
        )]

    findings = []
    for name, text in fields.items():
        if text is None:
            continue
        if not isinstance(text, str):
            findings.append(Finding(
                rule   = "V0",
                name   = "prose block was not text",
                detail = f"Field {name!r} is {type(text).__name__}, not text.",
                field  = str(name),
            ))
            continue
        try:
            findings.extend(_check_numbers(str(name), text, index))
            findings.extend(_check_identifiers(str(name), text, index))
            findings.extend(_check_context_genes(str(name), text, index))
            findings.extend(_check_language(str(name), text))
            findings.extend(_check_gene_mediation(str(name), text))
        except Exception as exc:                        # noqa: BLE001 - deliberate boundary
            findings.append(Finding(
                rule   = "V0",
                name   = "check failed",
                detail = f"A check raised on field {name!r} ({type(exc).__name__}: {exc}).",
                field  = str(name),
            ))
    return findings


def summarise(findings: list) -> str:
    """One line per finding, for a log or a ledger note. Never includes a credential."""
    if not findings:
        return "validator: no findings; prose may ship."
    lines = [f"validator: {len(findings)} finding(s); prose discarded."]
    lines.extend(f"  - {finding}" for finding in findings)
    return "\n".join(lines)
