"""Behavioural guards for visual-row reconstruction.

`_rows` previously bucketed on `round(top / tol)` -- a fixed bin EDGE, not a
tolerance. Two words on the same baseline landed in different rows whenever an
edge fell between them, producing 47.6% more rows than the page has across 119
of 120 sampled PDFs.

The damage was never cosmetic. It split `BLOCK:` from its value so a downstream
regex read the next field's ordinal (41 wrong block numbers), and split `3.`
from `OPERATOR/CONTRACTOR` so revision detection saw an absent field 3 and
misclassified 33 revision-B documents as A.

These tests use real coordinates from the affected PDFs. They fail if the
quantiser returns, and they fail if the tolerance is loosened enough to chain
adjacent lines -- both directions matter.
"""

from __future__ import annotations

import pytest

from psm.layout import ROW_TOL, _rows


def w(text: str, top: float, x0: float = 0.0) -> dict:
    return {"text": text, "top": top, "x0": x0, "x1": x0 + 10, "bottom": top + 8}


def texts(words) -> list[str]:
    return [" ".join(x["text"] for x in row) for row in _rows(words)]


class TestSameBaselineWordsStayTogether:
    """The exact coordinates from ac-25a-exxon-22-feb-2014.pdf that caused
    41 wrong block numbers and 33 wrong form revisions."""

    def test_block_label_and_value_join(self):
        # 0.5pt apart, straddling a 2.5-wide bin edge at 308.75 under the old code.
        got = texts([w("BLOCK:", 308.8, 10), w("25", 308.3, 60), w("LONGITUDE:", 308.5, 90)])
        assert any("BLOCK: 25" in t for t in got), got

    def test_field_three_anchor_and_label_join(self):
        """Revision detection reads field 3's label. Split, it sees nothing."""
        got = texts([w("3.", 233.1, 10), w("OPERATOR/CONTRACTOR", 234.0, 30)])
        assert got == ["3. OPERATOR/CONTRACTOR"], got

    def test_words_at_identical_top_join(self):
        assert texts([w("A", 100.0, 0), w("B", 100.0, 20)]) == ["A B"]


class TestDistinctLinesStayApart:
    """The opposite failure. Single linkage chains: at tol 2.0 the within-row
    spread on a real form face reached 3.36pt, merging two lines."""

    def test_lines_beyond_tolerance_do_not_merge(self):
        got = texts([w("first", 100.0), w("second", 100.0 + ROW_TOL + 0.5)])
        assert got == ["first", "second"], got

    def test_a_ladder_of_close_words_does_not_chain_without_limit(self):
        """Successive 1.4pt steps are each within tolerance but span 7pt total.
        Chaining would merge six distinct lines into one."""
        rows = texts([w(str(i), 100.0 + i * 1.4) for i in range(6)])
        assert len(rows) > 1, f"chained {6} words spanning 7pt into {rows}"


class TestOrdering:
    def test_rows_are_ordered_top_to_bottom(self):
        assert texts([w("lower", 200.0), w("upper", 100.0)]) == ["upper", "lower"]

    def test_words_within_a_row_are_ordered_left_to_right(self):
        assert texts([w("right", 100.0, 300), w("left", 100.0, 10)]) == ["left right"]

    def test_input_order_does_not_change_output(self):
        words = [w("c", 120.0, 5), w("a", 100.0, 5), w("b", 100.0, 40)]
        assert texts(words) == texts(list(reversed(words)))


class TestToleranceIsAGapNotABinWidth:
    def test_tolerance_is_small_enough_not_to_chain_form_lines(self):
        """2.5 was a bin width (+/-1.25 from a centre). As a gap it chains."""
        assert ROW_TOL <= 2.0, "a gap tolerance above 2.0 merges adjacent form lines"

    def test_tolerance_is_large_enough_to_absorb_baseline_jitter(self):
        """146 of 222 observed same-row gaps are under 1pt."""
        assert ROW_TOL >= 1.0, "below 1.0 splits words that share a baseline"
