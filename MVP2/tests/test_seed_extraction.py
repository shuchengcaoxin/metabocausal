import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from screen_seed_papers import add, text

SOURCE = Path(__file__)


def test_blank_excel_cells_do_not_become_textual_none():
    assert text((None,), 0) == ""
    assert text(("None",), 0) == ""


def test_extraction_requires_both_endpoints_and_records_relation_basis():
    records = []
    add(
        records,
        study_id="fixture",
        path=SOURCE,
        sheet="MR results",
        row_number=4,
        metabolite_name="glycine",
        disease_trait="",
        direction="forward",
    )
    assert records == []

    add(
        records,
        study_id="fixture",
        path=SOURCE,
        sheet="MR results",
        row_number=5,
        metabolite_name="glycine",
        disease_trait="coronary artery disease",
        direction="forward",
        method="IVW",
        beta="0.1",
        p_value="0.01",
    )
    assert records[0]["pair_relation_verified"] == "yes"
    assert "same source row" in records[0]["pair_relation_basis"]
