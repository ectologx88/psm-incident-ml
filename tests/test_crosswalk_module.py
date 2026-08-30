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
    outcome_text,
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


@pytest.fixture(scope="module")
def ospec() -> dict:
    from psm.crosswalk import XW_OUTCOME
    return yaml.safe_load(XW_OUTCOME.read_text(encoding="utf-8"))


class TestOutcomeText:
    """The fallback tier for E19's "What was the outcome?".

    The column was 0% filled and coded `blank: extractable` -- a to-do nobody
    could act on. It now fills in two tiers: a verbatim field 17 sentence
    (`src`, 434 records) and this composition (`xw`, 649). These tests guard the
    boundary that keeps the second honest.
    """

    def test_no_atoms_yields_nothing(self, ospec):
        """An outcome sentence built from no outcome data would be fabrication
        carrying an `xw` label. It must return "" so the key is omitted and no
        orphan provenance mark is written."""
        assert outcome_text([], None, ospec) == ""

    def test_absence_of_injury_is_not_rendered_as_no_injuries(self, ospec):
        """BSEE coding omissions are common; the spine's silence is not a claim.
        Reports that genuinely say "no injuries" are caught by the verbatim
        tier, whose cue list leads with exactly that phrasing."""
        got = outcome_text(["Fire"], None, ospec)
        assert "no injur" not in got.lower()

    def test_it_names_rather_than_characterises(self, ospec):
        """The `xw`/`syn_` boundary in one assertion. Translation stays `xw`;
        the moment a phrase judges severity it has become an opinion and the
        column's provenance mark would be a lie."""
        for atoms in (["Fatality"], ["LTA (>3 days)"], ["Explosion"], ["Blowout"],
                      ["Injury"], ["Damaged/Disabled Safety Sys."]):
            got = outcome_text(atoms, None, ospec).lower()
            for word in ("serious", "significant", "severe", "minor", "catastrophic"):
                assert word not in got, f"{atoms} rendered judgement word {word!r}"

    def test_response_is_a_separate_clause_from_harm(self, ospec):
        """"Required Evacuation" must not read as though the evacuation were
        the harm."""
        got = outcome_text(["Required Evacuation", "LTA (>3 days)"], None, ospec)
        assert "resulted in a lost-time accident" in got
        assert "The facility was evacuated" in got
        assert got.index("lost-time") < got.index("evacuated")

    def test_phrase_order_follows_the_rule_file_not_the_atom_string(self, ospec):
        """The atom order comes from a BSEE string and varies between otherwise
        identical rows; rendering in atom order made byte-identical inputs
        produce different sentences.

        The atoms must sit in the SAME group for this to test anything -- an
        earlier version of this test used one atom per group, where the fixed
        group order hid the defect and a mutation check caught the test rather
        than the code.
        """
        a = outcome_text(["Fire", "Explosion", "Pollution"], None, ospec)
        b = outcome_text(["Pollution", "Explosion", "Fire"], None, ospec)
        assert a == b
        assert a == "Reported as a fire, an explosion and a pollution release."

    def test_multiple_injuries_render_in_rule_file_order(self, ospec):
        a = outcome_text(["RW/JT (>3 days)", "Fatality"], None, ospec)
        b = outcome_text(["Fatality", "RW/JT (>3 days)"], None, ospec)
        assert a == b
        assert a.index("fatality") < a.index("restricted work")

    def test_damage_figure_is_appended_verbatim(self, ospec):
        got = outcome_text(["Crane"], "$15,000", ospec)
        assert got.endswith("Estimated property damage $15,000.")

    def test_a_threshold_atom_does_not_become_a_figure(self, ospec):
        """`Incident >$25K` is a threshold, not an amount. Rendering it as a
        damage figure would invent precision BSEE did not record."""
        got = outcome_text(["Incident >$25K"], None, ospec)
        assert "Estimated property damage" not in got

    def test_unknown_atoms_are_ignored_not_guessed(self, ospec):
        assert outcome_text(["Some Future BSEE Code"], None, ospec) == ""


class TestSecondaryElementSidecar:
    """`also_touches` existed in crosswalk.yaml from v1 and was emitted by
    nothing -- the only reference in src/ was a print in evidence.py.

    It is not hedging. Equipment Failure -> 15 (inspection and maintenance) vs
    11 (standards and practices) is the difference between a maintenance finding
    not actioned and a design that was wrong the day it was fitted, and the
    cause text usually says which. Collapsing to the primary discarded that.
    """

    @staticmethod
    def _read(name):
        import csv as _csv
        from psm.crosswalk import DEFAULT_OUT
        _csv.field_size_limit(10 ** 9)
        with (DEFAULT_OUT / name).open(encoding="utf-8", newline="") as fh:
            return list(_csv.DictReader(fh))

    def test_the_sidecar_matches_the_causes_table_row_for_row(self):
        """A sidecar that drifts from its table is worse than no sidecar."""
        c = self._read("causes.csv")
        s = self._read("causes_secondary_element.csv")
        assert len(c) == len(s)
        for a, b in zip(c, s):
            assert (a["Incident Number"], a["Cause number"]) == \
                   (b["Incident Number"], b["Cause number"])

    def test_the_e19_cell_stays_single_valued(self):
        """The reason this is a sidecar at all. The template's picklist takes
        one element per cause; a multi-valued cell would break the byte-exact
        projection guarantee the whole layer exists to provide."""
        c = self._read("causes.csv")
        col = next(k for k in c[0] if "Failed PSM" in k)
        for r in c:
            assert ";" not in (r[col] or ""), f"multi-valued E19 cell: {r[col]!r}"

    def test_a_secondary_exists_exactly_where_a_primary_does(self):
        """Every one of the six categories declares an `also_touches`, so the
        two columns must fill together. A row with a secondary and no primary
        would be an element assignment with no cause category behind it."""
        c = self._read("causes.csv")
        s = self._read("causes_secondary_element.csv")
        col = next(k for k in c[0] if "Failed PSM" in k)
        for a, b in zip(c, s):
            has_p = bool((a[col] or "").strip())
            has_s = bool((b["xw_secondary_elements"] or "").strip())
            assert has_p == has_s, f"{a['Incident Number']}: primary={has_p} secondary={has_s}"

    def test_a_secondary_never_equals_its_primary(self, types):
        """`also_touches` that repeats the primary would add nothing and would
        inflate the apparent element coverage."""
        c = self._read("causes.csv")
        s = self._read("causes_secondary_element.csv")
        col = next(k for k in c[0] if "Failed PSM" in k)
        for a, b in zip(c, s):
            sec = [x for x in (b["xw_secondary_elements"] or "").split(";") if x]
            assert (a[col] or "").strip() not in sec

    def test_the_sidecar_widens_element_coverage(self):
        """The measurable payoff: 6 of 20 elements are reachable from primaries
        alone; the sidecar adds element 11 and makes it 7. Still a hard ceiling
        -- 13 elements this crosswalk can never emit -- and that ceiling is the
        point of measuring it."""
        c = self._read("causes.csv")
        s = self._read("causes_secondary_element.csv")
        col = next(k for k in c[0] if "Failed PSM" in k)
        prim = {(r[col] or "").strip() for r in c} - {""}
        sec = {x for r in s for x in (r["xw_secondary_elements"] or "").split(";") if x}
        assert len(prim) == 6
        assert len(prim | sec) > len(prim)
