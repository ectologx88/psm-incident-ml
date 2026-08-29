"""Tests for form-revision handling and the integrity guards.

Every string here is taken from a real BSEE report in the sample. The form has
three numbering revisions and two wordings for field 17; an extractor built
against only the modern revision fails *silently* — a rejected anchor's content
is absorbed into the previous accepted field rather than going missing. These
tests guard the loud-failure behaviour, not just the happy path.

See docs/findings.md, entry 2026-08-29.
"""

from __future__ import annotations

import pytest

from psm.extract import (
    ANCHOR_RE,
    _label_matches,
    check_field_lengths,
    detect_form_revision,
    load_schema,
)
from psm.layout import Line


@pytest.fixture(scope="module")
def schema() -> dict:
    return load_schema()


def lines(*texts: str) -> list[Line]:
    return [Line(0, 10.0 * i, 0.0, t, 0) for i, t in enumerate(texts)]


class TestLabelAlternates:
    """`label_hint` may be a string or a list of alternates."""

    def test_modern_field17_wording(self, schema):
        assert _label_matches(17, "INVESTIGATION FINDINGS:", schema)

    def test_pre_2010_field17_wording(self, schema):
        # 0/22 archive-era files located field 17 before this alternate existed.
        assert _label_matches(17, "DESCRIBE IN SEQUENCE HOW ACCIDENT HAPPENED:", schema)

    def test_string_hint_still_works(self, schema):
        assert _label_matches(18, "LIST THE PROBABLE CAUSE(S) OF ACCIDENT:", schema)

    def test_non_matching_tail_is_rejected(self, schema):
        assert not _label_matches(17, "PROPERTY DAMAGED:", schema)

    def test_unknown_field_number_is_rejected(self, schema):
        assert not _label_matches(99, "ANYTHING", schema)


class TestFormRevisionDetection:
    """Revision is read from the raw anchor stream, because on revisions A and B
    the deciding anchors are rejected by the label hints and are gone by the time
    fields exist."""

    def test_revision_c_water_depth_at_10(self, schema):
        got = detect_form_revision(
            lines("3. OPERATOR/CONTRACTOR REPRESENTATIVE/SUPERVISOR",
                  "10. WATER DEPTH: 6200 FT."), schema)
        assert got == "C"

    def test_revision_b_water_depth_at_9_field3_is_operator(self, schema):
        got = detect_form_revision(
            lines("3. OPERATOR/CONTRACTOR REPRESENTATIVE/SUPERVISOR",
                  "9. WATER DEPTH: 194 FT."), schema)
        assert got == "B"

    def test_revision_a_water_depth_at_9_field3_is_lease(self, schema):
        got = detect_form_revision(
            lines("3. LEASE: G01153", "9. WATER DEPTH: 60 FT."), schema)
        assert got == "A"

    def test_no_water_depth_anchor_is_unknown_not_a_guess(self, schema):
        # The press release at 090517-pdf has a text layer and no form anchors.
        assert detect_form_revision(lines("MMS to hold Public Hearings"), schema) == "unknown"

    def test_never_raises_on_empty_input(self, schema):
        assert detect_form_revision([], schema) == "unknown"


class TestLengthGuard:
    """A structured field holding prose means an anchor was rejected upstream.

    Calibrated against revision C, the only era where extraction is known
    correct. A guard that also fires on correct records tells you nothing — an
    earlier 400-char checkbox_set cap tripped all 38 revision-C records.
    """

    def test_absorbed_checkbox_field_is_flagged(self, schema):
        # Real shape: revision-B f07 runs a median of 967 chars.
        out = check_field_lengths({7: "X FIRE " * 200}, schema)
        assert [a["field"] for a in out] == [7]
        assert out[0]["type"] == "field_length_exceeded"
        assert out[0]["kind"] == "checkbox_set"

    def test_legitimate_revision_c_checkbox_field_is_not_flagged(self, schema):
        # Revision-C f07 maxes at 562 chars of genuine checkbox labels.
        assert check_field_lengths({7: "X" * 562}, schema) == []

    def test_unbounded_terminal_field_is_flagged(self, schema):
        # f30 should hold one name; one record holds 6,049 chars of attachment.
        out = check_field_lengths({30: "Larry Williamson " * 400}, schema)
        assert out and out[0]["field"] == 30

    def test_prose_kinds_are_unbounded(self, schema):
        # Fields 17 and 22 are legitimately thousands of characters.
        assert check_field_lengths({17: "x" * 20000, 22: "y" * 9000}, schema) == []

    def test_guard_reports_but_never_repairs(self, schema):
        fields = {7: "X FIRE " * 200}
        before = fields[7]
        check_field_lengths(fields, schema)
        assert fields[7] == before, "dirty data must stay dirty and visible"


class TestAnchorRegexOnRealLines:
    def test_two_column_admin_line_yields_both_anchors(self):
        # The admin block merges columns when gutter detection fails.
        line = "25. DATE OF ONSITE INVESTIGATION: ACCIDENT CLASSIFICATION:"
        assert [int(m.group(1)) for m in ANCHOR_RE.finditer(line)] == [25]

    def test_orphan_bare_number_is_not_an_anchor(self):
        # ROW_TOL bin-edge splits produce 41 orphan "NN." lines across 27 records.
        assert list(ANCHOR_RE.finditer("28.")) == []
