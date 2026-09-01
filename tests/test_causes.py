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

    def test_note_marker_is_not_a_category(self):
        # Regression: report 030521-pdf (2003 EAC riser-insert failure,
        # entirely free prose) — "NOTE:" is a continuation-page annotation,
        # not a typed BSEE cause category.
        s = "NOTE: ABB Vetco has redesigned the connector to prevent this failure."
        cat, form = candidate_category(s)
        assert cat is None
        assert form == "furniture"

    def test_field_label_bleed_is_not_a_category(self):
        # Regression: field 20's own label ("LIST THE ADDITIONAL
        # INFORMATION:") bled into field 19's body text on the same report
        # and was misread as a typed category.
        s = "LIST THE ADDITIONAL INFORMATION: "
        cat, form = candidate_category(s)
        assert cat is None
        assert form == "furniture"

    def test_field_label_bleed_generalises_across_fields(self):
        # "LIST THE ..." is BSEE's own field-label phrasing (field 18 is
        # literally "LIST THE PROBABLE CAUSE(S)"), so the guard must not be
        # scoped to field 20's wording alone.
        s = "LIST THE CONTRIBUTING CAUSE(S) OF ACCIDENT: The crane was not used to control the free load."
        assert candidate_category(s)[0] is None

    def test_real_category_named_list_is_still_typed(self):
        # The furniture guard must stay narrow: a genuine category should
        # never collide with it just because it starts with "List".
        s = "Listing errors: The manifest was not checked before departure."
        cat, _ = candidate_category(s)
        assert cat == "Listing errors"

    def test_wrapped_field_label_tail_is_not_a_category(self):
        """The test above passes only while the label is intact.

        In two-column soup BSEE's own label wraps and the tail lands alone,
        carrying the colon -- short, title-ish, colon-separated, i.e. every
        test for a cause category. 24 statements corpus-wide became a category
        called "ACCIDENT", the third most common head in the corpus. Verbatim
        from 090401-pdf and MC 759 Beacon Growtco 20-Feb-26.
        """
        assert candidate_category("ACCIDENT: The crane boom contacted the derrick.")[0] is None
        assert candidate_category("OF ACCIDENT: Failure to secure the load.")[0] is None

    def test_all_caps_is_not_by_itself_furniture(self):
        """The tempting general rule is wrong and this pins why.

        Six of the corpus's eleven all-caps heads are legitimate categories.
        A guard that swallowed them would silently delete 13 statements.
        """
        for head in ("HUMAN ERROR", "COMMUNICATION", "SUPERVISION",
                     "EQUIPMENT FAILURE", "MANAGEMENT SYSTEM", "WORK ENVIRONMENT"):
            cat, _ = candidate_category(f"{head}: some description of the cause.")
            assert cat == head, f"{head!r} was wrongly treated as furniture"

    def test_furniture_list_matches_only_in_caps(self):
        """Title Case wins: a real statement about damaged property survives."""
        cat, _ = candidate_category("Property damaged: the swivel housing cracked.")
        assert cat == "Property damaged"


class TestSpacedHyphenSeparator:
    """`Category - Subcategory` was not a separator until 2026-08-29.

    The letter-lookbehind required the hyphen to touch the preceding word, so
    the spaced form ran on to the next qualifying separator and produced a head
    too long to survive MAX_CATEGORY_WORDS. Silent: it lost mappings rather
    than creating wrong ones, so nothing downstream complained.
    """

    def test_spaced_hyphen_splits_category_from_subcategory(self):
        # Verbatim from BM 3 Cantium 5-Aug-2025, which names four canonical
        # categories in its text and previously mapped to none of them.
        s = ("Equipment Failure - Inadequate preventative maintenance/Inadequate "
             "equipment repair- the crane's aux hoist system was operated with "
             "documented mechanical deficiencies")
        assert candidate_category(s)[0] == "Equipment Failure"

    def test_unspaced_hyphen_still_compounds(self):
        """The regression this separator was originally narrowed to avoid:
        an earlier rule split "Flexi-Coil hose" and invented "The Flexi"."""
        assert candidate_category("The Flexi-Coil hose parted under pressure.")[0] is None

    def test_tight_hyphen_form_still_parses(self):
        s = "Human Performance Error- Inattention to task: torch stored away"
        assert candidate_category(s)[0] == "Human Performance Error"

    def test_a_mid_sentence_dash_does_not_invent_a_category(self):
        """Widening the separator opened this hole; the title-ish guard closes
        it. Without the isupper() check the head here is 'a well-known issue'."""
        s = "a well-known issue - the valve stuck open - caused the release"
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

    def test_furniture_only_field_is_freetext_not_typed(self):
        # Regression: report 030521-pdf's field 19 is entirely free prose
        # apart from a "NOTE:" continuation annotation and a bled-in field-20
        # label, both of which previously satisfied the category heuristic
        # and flipped the whole field to "typed".
        s = (
            "Three conditions must exist for EAC to propagate: the material "
            "must be stressed, susceptible to EAC, and in an environment "
            "with a hydrogen source.\n"
            "LIST THE ADDITIONAL INFORMATION: \n"
            "NOTE: ABB Vetco has redesigned the connector to prevent this failure."
        )
        assert classify_field(s) == "freetext"


class TestNormalisation:
    def test_case_and_spacing_fold(self):
        assert normalise_category("Equipment Failure") == normalise_category("equipment  failure")

    def test_human_error_variants_are_distinguishable(self):
        # We deliberately do NOT fold these in normalise_category; the crosswalk
        # owns that decision, so the raw distinction stays visible in the data.
        assert normalise_category("Human Performance Error") != normalise_category("Human error")
