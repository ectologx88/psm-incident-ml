"""Tests for src/psm/gold_scaffold.py's row-level cause_status combination."""
from __future__ import annotations

from psm.gold_scaffold import GOLD_COLUMNS, build_row, combine_cause_status


def test_typed_wins_if_either_field_is_typed():
    assert combine_cause_status("Equipment failure: pump not serviced.", None) == "typed"
    assert combine_cause_status(None, "Human Performance Error- inattention.") == "typed"


def test_freetext_wins_over_absent_when_no_field_is_typed():
    assert combine_cause_status("The crew failed to notice the leak.", None) == "freetext"


def test_absent_legitimate_only_when_both_fields_are_blank():
    assert combine_cause_status("N/A", "") == "absent_legitimate"
    assert combine_cause_status("", "N/A") == "absent_legitimate"


def test_parse_failed_when_one_field_is_not_located_and_other_is_blank():
    # None means "field not located" (a real parse failure), distinct from ""
    # meaning "field located and empty" (absent_legitimate) - see
    # psm.causes.classify_field's docstring.
    assert combine_cause_status(None, "N/A") == "parse_failed"


def test_parse_failed_when_nothing_else_applies():
    assert combine_cause_status(None, None) == "parse_failed"


def test_build_row_never_prefills_gold_columns(tmp_path):
    manifest_row = {
        "src_sha256": "abc123",
        "src_report_type": "district",
        "src_year": "2020",
        "src_operator": "Test Operator",
        "src_area": "MP",
        "src_block": "298",
        "src_date_text": "01-JAN-2020",
        "src_date_parsed": "2020-01-01",
        "src_url": "https://example.invalid/report.pdf",
        "src_filename": "report.pdf",
    }
    row = build_row(manifest_row, tmp_path)  # no interim JSON present
    assert row["src_extract_status"] == "not_extracted"
    assert row["src_cause_status"] == "parse_failed"
    for col in GOLD_COLUMNS:
        assert row[col] == ""
