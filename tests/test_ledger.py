"""The disposition ledger, made self-policing.

`schema/e19_disposition.yaml` is not documentation. Each entry is a **claim
about the world** -- that BSEE cannot supply this column, that we chose to leave
that one blank, that this third one carries data. A claim nobody checks decays
into decoration, and a stale audit is worse than none because it reads as
authority while describing a table that no longer exists.

So every claim is tested against the data it describes. If a `not_obtainable`
column starts carrying values, the disposition was wrong and the build says so.
If a `filled` column drops to zero, something upstream broke silently.

These tests are also the guard on the headline number. "65% of obtainable
fields" is only meaningful while the denominator is honest, and the denominator
is exactly this file.
"""

from __future__ import annotations

import pytest
import yaml

from psm.ledger import (
    ALL_DISPOSITIONS,
    OBTAINABLE,
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
        """An undeclared column is a silent hole in the denominator."""
        missing, _ = reconcile(spec, seen)
        assert missing == [], f"columns with no disposition: {missing}"

    def test_no_disposition_describes_a_column_that_is_gone(self, spec, seen):
        _, orphan = reconcile(spec, seen)
        assert orphan == [], f"dispositions for columns not in the data: {orphan}"

    def test_every_disposition_is_from_the_closed_set(self, spec):
        for table, col, entry in _entries(spec):
            assert entry["disposition"] in ALL_DISPOSITIONS, \
                f"{table}.{col!r}: unknown disposition {entry['disposition']!r}"


class TestTheClaimsAreTrue:
    """The point of the whole exercise. Each of these can fail on real data."""

    def test_not_obtainable_columns_are_empty(self, spec, seen):
        """If BSEE cannot supply it, nothing should have appeared in it. A value
        here means either the disposition is wrong or something is inventing
        data without a `syn_` mark."""
        for table, col, entry in _entries(spec):
            if entry["disposition"] != "not_obtainable":
                continue
            n, _ = seen[table][col]
            assert n == 0, (
                f"{table}.{col!r} is marked not_obtainable but carries {n} values")

    def test_deliberate_blanks_are_actually_blank(self, spec, seen):
        """A `deliberate_blank` that fills up has stopped being a decision."""
        for table, col, entry in _entries(spec):
            if entry["disposition"] != "deliberate_blank":
                continue
            n, _ = seen[table][col]
            assert n == 0, (
                f"{table}.{col!r} is marked deliberate_blank but carries {n} values")

    def test_filled_columns_carry_data(self, spec, seen):
        """The regression guard. A column that quietly empties -- an extractor
        keying on a heading that vanished, a join that stopped joining -- is the
        failure mode this repo has already hit twice."""
        empty = [f"{t}.{c!r}" for t, c, e in _entries(spec)
                 if e["disposition"] == "filled" and seen[t][c][0] == 0]
        assert empty == [], f"marked filled but empty: {empty}"

    def test_synthetic_columns_are_not_filled_from_source(self, spec, seen):
        """Until the synth layer is wired these must be empty. When it IS wired,
        this test must be replaced by one asserting a `syn` provenance mark --
        not deleted. Failing here is the reminder."""
        for table, col, entry in _entries(spec):
            if entry["disposition"] != "synthetic":
                continue
            n, _ = seen[table][col]
            assert n == 0, (
                f"{table}.{col!r} is marked synthetic but carries {n} values -- if the "
                "synth layer is now wired, update this test to check provenance == 'syn'")


class TestTheReasonsExist:
    def test_deliberate_blanks_name_a_file_that_exists(self, spec):
        """"We chose not to" is only defensible if the choice is written down
        somewhere a stranger can read."""
        from psm.ledger import REPO
        for table, col, entry in _entries(spec):
            if entry["disposition"] != "deliberate_blank":
                continue
            where = entry.get("reason_recorded_in")
            assert where, f"{table}.{col!r}: deliberate_blank with no reason_recorded_in"
            assert (REPO / where).exists(), f"{table}.{col!r}: {where} does not exist"

    def test_named_generators_exist_in_synth(self, spec):
        """A generator name is a promise that step 5 can keep. `null` is an
        honest admission and is allowed; a wrong name is not."""
        from psm.synth import SYN_COLUMN_MANIFEST
        for table, col, entry in _entries(spec):
            gen = entry.get("generator")
            if entry["disposition"] != "synthetic" or gen is None:
                continue
            assert gen in SYN_COLUMN_MANIFEST, (
                f"{table}.{col!r} names generator {gen!r}, which synth.py does not produce")

    def test_every_synthetic_column_declares_its_generator_key(self, spec):
        """Including as `null`. Omitting the key entirely would hide the four
        risk components that have no generator behind an absence."""
        for table, col, entry in _entries(spec):
            if entry["disposition"] == "synthetic":
                assert "generator" in entry, f"{table}.{col!r}: synthetic with no generator key"


class TestTheHeadlineIsWellFormed:
    def test_denominator_excludes_judgement_and_decisions(self, spec, seen):
        """`needs_human` and `deliberate_blank` must stay out, or the headline
        moves when we take on labelling work -- rewarding us for not doing it."""
        assert set(OBTAINABLE) == {"filled", "synthetic"}
        stats = tally(spec, seen)
        excluded = stats["counts"]["needs_human"] + stats["counts"]["deliberate_blank"] \
            + stats["counts"]["not_obtainable"]
        assert stats["obtainable_fields"] + excluded == stats["total_fields"]

    def test_filled_count_never_exceeds_obtainable(self, spec, seen):
        stats = tally(spec, seen)
        assert stats["obtainable_fields_filled"] <= stats["obtainable_fields"]
        assert stats["obtainable_cells_filled"] <= stats["obtainable_cells"]

    def test_the_headline_is_not_vacuously_perfect(self, spec, seen):
        """A denominator whittled down to only the columns that happen to be
        full would report 100% and mean nothing. 20 unfilled obtainable fields
        are currently in it, and they should stay there until they are filled."""
        stats = tally(spec, seen)
        assert stats["obtainable_fields"] > stats["obtainable_fields_filled"], (
            "every obtainable field is filled -- if that is genuinely true, delete "
            "this test deliberately rather than letting it pass by accident")
