"""Tests for cause-statement parsing.

Every string here is copied from a real BSEE report in the stratified sample.
The delimiter forms are genuinely inconsistent across years and districts, and
a single-line regex silently drops rows — that is what these tests guard.
"""

import pytest

from psm.causes import (
    candidate_category,
    classify_field,
    normalise_category,
    parse_statement,
    segment_statements,
)


class TestDelimiterForms:
    """All four documented forms, plus the two found during induction."""

    def test_colon_category_dash_subcategory(self):
        s = "Equipment failure: Inadequate preventive maintenance- The pump was not serviced."
        st = parse_statement(s)
        assert normalise_category(st.category) == "equipment failure"
        assert "inadequate preventive maintenance" in st.subcategory.lower()

    def test_dash_category_colon_subcategory(self):
        s = "Human Performance Error- Inadequate knowledge of equipment operation: Engagement of winch."
        st = parse_statement(s)
        assert normalise_category(st.category) == "human performance error"

    def test_colon_category_period_subcategory(self):
        s = "Communication: Inadequate job instructions provided. Danos failed to train the crew."
        st = parse_statement(s)
        assert normalise_category(st.category) == "communication"
        assert st.subcategory.lower().startswith("inadequate job instructions")

    def test_bullet_endash_form(self):
        s = "• Equipment Failure – Inadequate Equipment Inspection: visual only."
        st = parse_statement(s)
        assert normalise_category(st.category) == "equipment failure"

    def test_enumerated_form(self):
        s = "1) Equipment Failure – Inadequate preventative maintenance/Inadequate equipment repair"
        st = parse_statement(s)
        assert normalise_category(st.category) == "equipment failure"

    def test_bare_header_distributes_over_bullets(self):
        text = (
            "Management Systems:\n"
            "• Inadequate job procedures. Crew lacked written steps.\n"
            "• Inadequate hazards analysis. The JSEA was insufficient."
        )
        statements = segment_statements(text)
        assert len(statements) == 2, "header+bullets must yield one statement per bullet"
        for s in statements:
            assert normalise_category(candidate_category(s)[0]) == "management systems"


class TestFalsePositives:
    """Things that must NOT be read as a cause category."""

    def test_hyphenated_compound_is_not_a_separator(self):
        # Regression: `(?<=[a-z])-(?=[A-Z])` split this and invented "The Flexi".
        s = "The Flexi-Coil hose was not secured to anything which would have prevented movement."
        assert candidate_category(s)[0] is None

    def test_long_prose_sentence_is_untyped(self):
        s = ("The BSEE incident investigation team has determined that the probable "
             "causes of the incident was due to the following conditions observed.")
        cat, form = candidate_category(s)
        assert cat is None
        assert form == "untyped_prose"

    def test_mooring_prose_is_untyped(self):
        s = "The mooring chain link fractures initiated from hydrogen embrittlement."
        assert candidate_category(s)[0] is None


class TestCauseStatus:
    """`absent_legitimate` is not a parse failure — conflating them hides bugs."""

    @pytest.mark.parametrize("blank", ["", "   ", "N/A", "None", "n/a"])
    def test_blank_is_absent_legitimate(self, blank):
        assert classify_field(blank) == "absent_legitimate"

    def test_missing_field_is_parse_failed(self):
        assert classify_field(None) == "parse_failed"

    def test_typed(self):
        assert classify_field("Human Performance Error: Inattention to task.") == "typed"

    def test_freetext(self):
        s = ("BSEE's investigation revealed the following contributing causes: "
             "1). Inadequate job briefing; 2). Poor communications between parties.")
        assert classify_field(s) in {"freetext", "typed"}

    def test_untyped_prose_is_freetext_not_failure(self):
        s = "Sea conditions impacted conductor movement, but remained within requirements."
        assert classify_field(s) == "freetext"


class TestNormalisation:
    def test_case_and_spacing_fold(self):
        assert normalise_category("Equipment Failure") == normalise_category("equipment  failure")

    def test_human_error_variants_are_distinguishable(self):
        # We deliberately do NOT fold these in normalise_category; the crosswalk
        # owns that decision, so the raw distinction stays visible in the data.
        assert normalise_category("Human Performance Error") != normalise_category("Human error")
