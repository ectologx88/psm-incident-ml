"""Behavioural tests for `psm.crosswalk` -- the module, not its YAML.

Coverage measured during the adversarial review: **243 statements, 0%**. No test
imported it, while 28 tests in a similarly-named file exercised the rule files.
It writes every enriched table.

These use real atoms and real coordinates from the corpus, and each targets a
defect that actually occurred rather than a happy path.
"""

from __future__ import annotations

import pytest
import yaml

from psm.crosswalk import (
    SEV,
    XW_TIERS,
    XW_TYPE,
    _band,
    _rank,
    minutes,
    resolve_types,
    section3,
    spine_index,
)


@pytest.fixture(scope="module")
def types() -> dict:
    return yaml.safe_load(XW_TYPE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tiers() -> dict:
    return yaml.safe_load(XW_TIERS.read_text(encoding="utf-8"))


class TestTypeAResolution:
    def test_a_mechanism_alone_is_a_loss_event(self, types):
        """A record tagged only 'Fire' had NO Type A: an earlier version counted
        outcome and scale atoms only. A fire is a loss event."""
        assert resolve_types(["Fire"], types)["Incident Type A"] == "Loss Event"

    def test_response_atoms_alone_are_a_near_hit(self, types):
        got = resolve_types(["Required Muster"], types)
        assert got["Incident Type A"] == "Near Hit"

    def test_response_plus_outcome_is_a_loss_event(self, types):
        got = resolve_types(["Required Evacuation", "LTA (>3 days)"], types)
        assert got["Incident Type A"] == "Loss Event"

    def test_no_atoms_yields_nothing(self, types):
        assert resolve_types([], types) == {}


class TestDeliberateNullsAreNotBackfilled:
    """A null in the rule file is a decision. An atom that maps to null must not
    fall through to a lower-precedence atom that happens to have a value -- that
    reinstates the guess the null was chosen to avoid."""

    def test_crane_does_not_receive_a_type_d(self, types):
        """Crane names equipment, not mechanism: 151 narratives showed boom
        failures, inspection injuries and lost-overboard, not just dropped loads."""
        assert "Incident Type D" not in resolve_types(["Crane"], types)

    def test_bare_injury_does_not_receive_a_type_c(self, types):
        """135 of 148 carry no severity atom and co-occur with Fatality 12 times.
        Defaulting to Injury Minor would under-rate them."""
        got = resolve_types(["Injury"], types)
        assert "Incident Type C" not in got
        assert got.get("Incident Type B") == "Health & Safety"

    def test_a_null_atom_does_not_borrow_from_a_lower_one(self, types):
        """Injury outranks Pollution. Injury's type_c is null, so the record gets
        no Type C -- it must NOT silently take 'Loss of Containment'."""
        got = resolve_types(["Injury", "Pollution"], types)
        assert got.get("Incident Type C") != "Loss of Containment"


class TestPrecedence:
    def test_fatality_outranks_pollution(self, types):
        got = resolve_types(["Pollution", "Fatality"], types)
        assert got["Incident Type C"] == "Injury Fatality"

    def test_injury_outranks_a_dollar_threshold(self, types):
        got = resolve_types(["Incident >$25K", "LTA (>3 days)"], types)
        assert got["Incident Type B"] == "Health & Safety"

    def test_rank_orders_scale_last(self, types):
        order = types["precedence"]["order"]
        assert _rank("Fatality", order) < _rank("Incident >$25K", order)


class TestSection3:
    def test_hazard_energy_rates_an_incident_that_hurt_nobody(self, tiers):
        """The whole point: actual-outcome-only leaves 61% blank with zero at
        consequence D. A fire with no injury must still be rated."""
        got = section3(["Fire"], [], None, tiers)
        assert got["Health & Safety  - Consequence"] == "D"

    def test_crewed_operation_raises_consequence_by_one(self, tiers):
        plain = section3(["Fire"], [], None, tiers)
        crewed = section3(["Fire"], ["X DRILLING"], None, tiers)
        assert SEV.index(crewed["Health & Safety  - Consequence"]) == \
            SEV.index(plain["Health & Safety  - Consequence"]) + 1

    def test_the_exposure_bump_caps_at_E(self, tiers):
        got = section3(["Explosion"], ["X WORKOVER"], None, tiers)
        assert got["Health & Safety  - Consequence"] == "E"

    def test_actual_outcome_is_a_floor(self, tiers):
        """A fatality is at least E whatever the energy analysis says."""
        got = section3(["Pollution", "Fatality"], [], None, tiers)
        assert got["Health & Safety  - Consequence"] == "E"

    def test_an_unestimable_mechanism_gets_consequence_but_no_score(self, tiers):
        """Blowout's code was retired in 2013, before the outcome codes existed.
        Borrowing a pooled rate would reinstate the era artifact."""
        got = section3(["Blowout"], [], None, tiers)
        assert got["Health & Safety  - Consequence"] == "E"
        assert "Health & Safety - Risk Score" not in got
        assert "Health & Safety Incident - Classification" not in got

    def test_an_estimable_mechanism_gets_the_full_set(self, tiers):
        got = section3(["Crane"], [], None, tiers)
        for col in ("Health & Safety - Likelihood", "Health & Safety - Risk Score",
                    "Health & Safety Incident - Classification"):
            assert col in got, col

    def test_risk_score_is_consequence_times_likelihood(self, tiers):
        got = section3(["Crane"], [], None, tiers)
        c = SEV.index(got["Health & Safety  - Consequence"]) + 1
        assert int(got["Health & Safety - Risk Score"]) == c * int(
            got["Health & Safety - Likelihood"])

    def test_financial_consequence_comes_from_the_dollar_figure(self, tiers):
        col = "Financial Cost & Business Interruption  - Consequence"
        assert section3(["Fire"], [], 5_000.0, tiers)[col] == "A"
        assert section3(["Fire"], [], 50_000_000.0, tiers)[col] == "E"

    def test_no_recognised_mechanism_yields_no_section_3(self, tiers):
        assert section3(["Required Muster"], [], None, tiers) == {}


class TestBanding:
    def test_at_least_bands_pick_the_first_match(self, tiers):
        bands = tiers["likelihood"]["bands"]
        assert _band(0.25, bands, "at_least") == 5
        assert _band(0.10, bands, "at_least") == 4
        assert _band(0.0, bands, "at_least") == 1

    def test_under_bands_handle_the_open_top(self, tiers):
        bands = tiers["financial_consequence"]["bands"]
        assert _band(10.0, bands, "under") == "A"
        assert _band(1e12, bands, "under") == "E"


class TestSpineJoin:
    def test_minutes_parses_both_forms(self):
        assert minutes("10:30") == 630
        assert minutes("1030") == 630
        assert minutes("") is None

    def test_spine_index_builds_both_keys(self):
        rows = [{"src_date_occurred": "06/06/2022", "src_military_time": "10:30",
                 "src_area_block": "MC 778", "src_accident_type": "Fire"}]
        by_time, by_ab = spine_index(rows)
        assert ("2022-06-06", 630) in by_time
        assert ("MC", "778", "2022-06-06") in by_ab

    def test_spine_index_keeps_the_first_of_a_colliding_key(self):
        rows = [{"src_date_occurred": "06/06/2022", "src_military_time": "10:30",
                 "src_area_block": "MC 778", "src_accident_type": "Fire"},
                {"src_date_occurred": "06/06/2022", "src_military_time": "10:30",
                 "src_area_block": "MC 778", "src_accident_type": "Pollution"}]
        by_time, _ = spine_index(rows)
        assert by_time[("2022-06-06", 630)]["src_accident_type"] == "Fire"
