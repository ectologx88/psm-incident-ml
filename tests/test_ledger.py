"""The disposition ledger, made self-policing.

`schema/e19_disposition.yaml` is not documentation. Each entry is a **claim
about the world** -- that no BSEE report can supply this column, that this other
one carries real values, that fabricating a third one's gaps is acceptable. A
claim nobody checks decays into decoration, and a stale audit is worse than none
because it reads as authority while describing a table that no longer exists.

This matters more here than in most projects. The dataset is dense by
construction: every cell the source cannot supply is fabricated. The only thing
separating a real value from an invented one is the provenance marking, and the
only thing guaranteeing the marking means what it says is this file plus these
tests.
"""

from __future__ import annotations

import pytest

from psm.ledger import (
    ALL_DISPOSITIONS,
    GAP_POLICIES,
    REPO,
    load_disposition,
    measure,
    reconcile,
    tally,
)

pytestmark = pytest.mark.skipif(
    not measure(), reason="run `python -m psm.project` and `python -m psm.crosswalk` first")


@pytest.fixture(scope="module")
def spec() -> dict:
    return load_disposition()


@pytest.fixture(scope="module")
def seen() -> dict:
    return measure()


def _entries(spec):
    for table, cols in spec["fields"].items():
        for col, entry in cols.items():
            yield table, col, entry


class TestTheFileDescribesTheData:
    def test_no_column_lacks_a_disposition(self, spec, seen):
        """An undeclared column is a cell of unknown provenance in a dataset
        whose entire value proposition is known provenance."""
        missing, _ = reconcile(spec, seen)
        assert missing == [], f"columns with no disposition: {missing}"

    def test_no_disposition_describes_a_column_that_is_gone(self, spec, seen):
        _, orphan = reconcile(spec, seen)
        assert orphan == [], f"dispositions for columns not in the data: {orphan}"

    def test_every_disposition_is_from_the_closed_set(self, spec):
        for table, col, entry in _entries(spec):
            assert entry["disposition"] in ALL_DISPOSITIONS, \
                f"{table}.{col!r}: unknown disposition {entry['disposition']!r}"

    def test_every_real_column_declares_a_gap_policy(self, spec):
        """What happens in a real column's empty cells is the whole question.
        Leaving it implicit is how a `syn` value ends up unremarked beside a
        `src` one."""
        for table, col, entry in _entries(spec):
            if entry["disposition"] != "real":
                continue
            assert entry.get("gap_policy") in GAP_POLICIES, \
                f"{table}.{col!r}: real column with gap_policy {entry.get('gap_policy')!r}"


class TestTheClaimsAreTrue:
    def test_real_columns_carry_data(self, spec, seen):
        """The regression guard. A column that quietly empties -- an extractor
        keying on a heading that vanished, a join that stopped joining -- is a
        failure mode this repo has already hit twice, and once the synth layer
        is wired it would be invisible: the column would still look full."""
        empty = [f"{t}.{c!r}" for t, c, e in _entries(spec)
                 if e["disposition"] == "real" and seen[t][c][0] == 0]
        assert empty == [], f"marked real but carrying nothing: {empty}"

    def test_gap_policy_none_means_the_column_really_is_complete(self, spec, seen):
        """`none` asserts there is nothing to fill. If such a column has holes,
        those holes will silently stay empty in a dataset that promises density."""
        for table, col, entry in _entries(spec):
            if entry.get("gap_policy") != "none":
                continue
            n, total = seen[table][col]
            assert n == total, (
                f"{table}.{col!r} claims gap_policy: none but is {n}/{total}")

    def test_synthetic_columns_are_empty_until_the_synth_layer_is_wired(self, spec, seen):
        """When synth IS wired, replace this with an assertion that every cell
        in these columns carries provenance `syn`. Do not delete it -- the
        failure is the reminder, and an unmarked fabricated column is the single
        worst outcome available to this project."""
        for table, col, entry in _entries(spec):
            if entry["disposition"] != "synthetic_column":
                continue
            n, _ = seen[table][col]
            assert n == 0, (
                f"{table}.{col!r} is a synthetic_column but carries {n} values -- "
                "if synth is now wired, rewrite this test to assert provenance == 'syn'")


class TestTheGeneratorPromisesAreKeepable:
    def test_named_generators_exist_in_synth(self, spec):
        """A generator name is a promise. `null` is an honest admission and is
        allowed; a name that does not exist is a to-do disguised as a plan."""
        from psm.synth import SYN_COLUMN_MANIFEST
        for table, col, entry in _entries(spec):
            gen = entry.get("generator")
            if entry["disposition"] != "synthetic_column" or gen is None:
                continue
            assert gen in SYN_COLUMN_MANIFEST, (
                f"{table}.{col!r} names generator {gen!r}, which synth.py does not produce")

    def test_every_synthetic_column_declares_its_generator_key(self, spec):
        """Including as `null`. Omitting the key hides the columns with no
        generator behind an absence rather than naming them."""
        for table, col, entry in _entries(spec):
            if entry["disposition"] == "synthetic_column":
                assert "generator" in entry, \
                    f"{table}.{col!r}: synthetic_column with no generator key"

    def test_reason_files_named_for_declined_judgements_exist(self, spec):
        """Several synthetic columns are synthetic because our method declined
        to estimate, not because the source is silent. That distinction is only
        meaningful while the reasoning is readable."""
        for table, col, entry in _entries(spec):
            where = entry.get("reason_recorded_in")
            if where:
                assert (REPO / where).exists(), f"{table}.{col!r}: {where} does not exist"


class TestModellingTargetsAreFlagged:
    def test_every_cause_label_column_is_a_modelling_target(self, spec):
        """The causes table is the dataset's point: one prose input and four
        labels over it. Forgetting to flag one means --real-only silently ships
        fabricated labels as ground truth."""
        for col, entry in spec["fields"]["causes"].items():
            if col in ("Incident Number", "Cause number", "Cause Description"):
                continue
            assert entry.get("modelling_target"), \
                f"causes.{col!r} is a label over Cause Description but is not flagged"

    def test_the_primary_input_feature_is_not_fabricated(self, spec, seen):
        """If Cause Description were ever fabricated or gap-filled, the dataset
        would have no real input left and nothing downstream would be worth
        modelling."""
        entry = spec["fields"]["causes"]["Cause Description"]
        assert entry["disposition"] == "real"
        assert entry["gap_policy"] == "none"
        n, total = seen["causes"]["Cause Description"]
        assert n == total


class TestTheHeadlineIsWellFormed:
    def test_the_cell_accounting_is_exhaustive(self, spec, seen):
        s = tally(spec, seen)
        assert s["real_cells"] + s["fabricated_cells"] + s["unfilled_cells"] \
            == s["total_cells"]

    def test_the_dataset_is_not_claimed_to_be_all_real(self, spec, seen):
        """A denominator quietly narrowed to the real columns would report 100%
        real and be worthless. If this ever passes vacuously, the ledger has
        stopped counting the fabricated majority."""
        s = tally(spec, seen)
        assert s["fabricated_cells"] > 0
        assert s["real_cells"] < s["total_cells"]

    def test_a_meaningful_share_is_real(self, spec, seen):
        """The other direction. A dataset that drifted to almost entirely
        fabricated would still pass every test above while being useless; this
        is the floor below which the corpus has stopped being the point."""
        s = tally(spec, seen)
        assert s["real_cells"] / s["total_cells"] > 0.25, (
            f"only {100 * s['real_cells'] / s['total_cells']:.1f}% of cells are real")
