"""Anchor resolution and the terminal bound -- Phase 0's two fixes.

Both defects were silent. Neither raised an error, both produced plausible
output, and between them they contaminated 30.4% of `Recommendation
Description` and hid nine form fields on 69% of records while every test passed.

The strings below are real, from named reports in the corpus.
"""

from __future__ import annotations

import pytest

from psm.extract import _terminal_cap, field_for_label, load_schema


@pytest.fixture(scope="module")
def schema() -> dict:
    return load_schema()


class TestAnchorsResolveByLabel:
    """The printed number is not reliable; the label is.

    Revision B renumbers the form face, AND two-column linearisation drops
    digits. A per-revision number map -- the original plan -- handles the first
    and not the second.
    """

    @pytest.mark.parametrize("tail,expected", [
        ("OPERATION:", 8),
        ("CAUSE:", 9),
        ("WATER DEPTH: 23 FT.", 10),
        ("DISTANCE FROM SHORE: 16 MI.", 11),
        ("WIND DIRECTION:", 12),
        ("CURRENT DIRECTION:", 13),
        # Verbatim from ei-100-arena-offshore-01-mar-2014: the leading "1" of
        # "13." is lost in linearisation, so this arrives numbered 3 and would
        # otherwise be read as field 3, OPERATOR/CONTRACTOR.
        ("SEA STATE: FT.", 14),
    ])
    def test_revision_b_form_face_resolves_by_label(self, schema, tail, expected):
        assert field_for_label(tail, schema) == expected

    def test_longer_hint_wins(self, schema):
        """"OPERATOR" is a prefix of "OPERATOR/CONTRACTOR". Shortest-first
        matching would claim field 2 for every field-3 anchor."""
        assert field_for_label("OPERATOR/CONTRACTOR REPRESENTATIVE", schema) == 3
        assert field_for_label("OPERATOR: Arena Offshore, LP", schema) == 2

    def test_cause_hints_do_not_collide(self, schema):
        """"CAUSE" (field 9) sits inside both field 18's and field 19's hints."""
        assert field_for_label("PROBABLE CAUSE(S) OF ACCIDENT:", schema) == 18
        assert field_for_label("CONTRIBUTING CAUSE(S) OF", schema) == 19
        assert field_for_label("CAUSE:", schema) == 9

    def test_a_hint_inside_prose_does_not_open_a_field(self, schema):
        """Anchored at the start of the tail. Otherwise any narrative mentioning
        a water depth would open field 10 mid-sentence."""
        assert field_for_label("the crew measured WATER DEPTH before the lift", schema) is None

    def test_an_unrecognised_label_yields_nothing(self, schema):
        assert field_for_label("SOMETHING BSEE HAS NEVER PRINTED", schema) is None


class TestTerminalCap:
    """Only the LAST anchor needs a cap; every other field is bounded by the
    next one. Before this, two records held the entire document in one field
    (267,928 and 280,537 characters)."""

    def test_structured_kinds_use_their_declared_limit(self, schema):
        assert _terminal_cap(30, schema) == schema["max_length_by_kind"]["text"]
        assert _terminal_cap(27, schema) == schema["max_length_by_kind"]["yesno"]
        assert _terminal_cap(8, schema) == schema["max_length_by_kind"]["checkbox_set"]

    def test_prose_kinds_fall_back_to_the_terminal_cap(self, schema):
        """`prose` and `cause_statements` declare no limit on purpose -- a field
        17 narrative is genuinely long. The longest legitimate one in the corpus
        is 37,050 characters (an 11-page Hess TLP investigation), which is why
        this cap exists to catch runaway absorption rather than to trim prose."""
        assert _terminal_cap(17, schema) == schema["terminal_prose_cap"]
        assert _terminal_cap(18, schema) == schema["terminal_prose_cap"]

    def test_the_cap_is_generous_enough_for_real_narratives(self, schema):
        """Pinned against the measured maximum. If someone lowers this cap to a
        round number that feels tidy, field 17 starts losing real text."""
        assert schema["terminal_prose_cap"] >= 20000


class TestLabelBleedPatterns:
    """Field 22's label spans two visual lines with field 21's block linearising
    between them, so the first line carries no colon and the label survives into
    the body. 30.4% of recommendations began with their own label."""

    @staticmethod
    def _strip(text, schema):
        from psm.extract import _label_bleed
        for pat in _label_bleed(schema):
            text = pat.sub(" ", text)
        return " ".join(text.split())

    def test_the_field_22_label_is_removed(self, schema):
        # Verbatim from ei-338k-arena-offshore-09-aug-2011.
        raw = ("22. RECOMMENDATIONS TO PREVENT RECURRANCE NATURE OF DAMAGE: N/A $ "
               "NARRATIVE: The BSEE Lafayette District office makes no recommendations "
               "to the Regional Office of Safety Management (OSM).")
        got = self._strip(raw, schema)
        assert got.startswith("N/A $")
        for token in ("RECURRANCE", "NARRATIVE", "NATURE OF DAMAGE"):
            assert token not in got

    def test_text_on_both_sides_of_the_interleaved_block_survives(self, schema):
        """Stripping "everything before NARRATIVE:" was the obvious fix and
        would have deleted the first half of this sentence. Verbatim from
        st-28-energy-xxi-oct-11-2017."""
        raw = ("22. RECOMMENDATIONS TO PREVENT RECURRANCE The Houma District has no "
               "recommendation NATURE OF DAMAGE: Ruptured, melted NARRATIVE: for the "
               "Regional Office.")
        got = self._strip(raw, schema)
        assert "The Houma District has no recommendation" in got
        assert "for the Regional Office." in got

    def test_ordinary_prose_is_untouched(self, schema):
        raw = "The district recommends that the operator revise its lift plan."
        assert self._strip(raw, schema) == raw
