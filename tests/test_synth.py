"""Tests for src/psm/synth.py — synthetic E19 field generation.

Every synth field is a documented, deterministic function of report_id and a
handful of real fields (see the Row Input Contract in
docs/superpowers/plans/2026-08-09-synth-fields-implementation.md). No
randomness, no wall-clock reads — see schema/synth_rules.yaml's
reference_date for why.
"""
from __future__ import annotations

import re

import pytest

from psm.synth import REQUIRED_ROW_KEYS, load_rules, synth_identity_fields, validate_row

TOKEN_RE = re.compile(r"^SYN-[A-Za-z]+-[0-9a-f]{6}$")


def test_load_rules_returns_expected_top_level_keys():
    rules = load_rules()
    assert rules["reference_date"] == "2026-08-09"
    assert "identity_salts" in rules
    assert "date_offsets" in rules


def test_validate_row_accepts_a_complete_row(make_row):
    validate_row(make_row())  # must not raise


def test_validate_row_rejects_a_row_missing_keys(make_row):
    row = make_row()
    del row["incident_date"]
    with pytest.raises(KeyError):
        validate_row(row)


def test_required_row_keys_matches_the_documented_contract():
    assert REQUIRED_ROW_KEYS == {
        "report_id", "incident_date", "incident_types",
        "property_damage_usd", "area_block",
    }


def test_identity_fields_are_deterministic():
    rules = load_rules()
    first = synth_identity_fields("stable-id", rules)
    second = synth_identity_fields("stable-id", rules)
    assert first == second


def test_identity_name_tokens_match_expected_format_and_positions():
    rules = load_rules()
    out = synth_identity_fields("some-report-id", rules)
    for role in rules["identity_salts"]:
        assert TOKEN_RE.match(out[f"{role}_name"]), out[f"{role}_name"]
        assert out[f"{role}_position"] == rules["identity_positions"][role]


def test_identity_tokens_vary_across_reports():
    rules = load_rules()
    leads = {synth_identity_fields(f"r{i}", rules)["investigation_lead_name"] for i in range(20)}
    assert len(leads) > 1


def test_identity_tokens_do_not_collide_across_roles_in_corpus():
    rules = load_rules()
    for i in range(50):
        out = synth_identity_fields(f"corpus-report-{i}", rules)
        names = [out[f"{role}_name"] for role in rules["identity_salts"]]
        assert len(names) == len(set(names)), f"collision in corpus-report-{i}: {names}"


from datetime import date

from psm.synth import synth_date_fields


def test_date_offsets_are_within_documented_ranges():
    rules = load_rules()
    incident_date = date(2020, 1, 1)
    for report_id in ("r1", "r2", "r3", "r4", "r5"):
        out = synth_date_fields(report_id, incident_date, rules)
        assert 5 <= (out["date_of_report"] - incident_date).days <= 15
        assert 14 <= (out["approval_date"] - out["date_of_report"]).days <= 45
        assert 30 <= (out["close_out_date"] - out["approval_date"]).days <= 90
        assert 30 <= (out["action_due_date"] - out["approval_date"]).days <= 180
        assert 30 <= (out["agreed_completion_date"] - out["approval_date"]).days <= 180


def test_date_offsets_are_deterministic():
    rules = load_rules()
    incident_date = date(2020, 1, 1)
    assert synth_date_fields("stable-id", incident_date, rules) == synth_date_fields(
        "stable-id", incident_date, rules
    )


def test_date_offsets_vary_across_reports():
    rules = load_rules()
    incident_date = date(2020, 1, 1)
    values = {synth_date_fields(f"r{i}", incident_date, rules)["date_of_report"] for i in range(20)}
    assert len(values) > 1, "date_of_report constant across reports — salt or hashing broken"


def test_date_offsets_raise_on_unresolvable_base():
    rules = load_rules()
    broken_rules = dict(rules, date_offsets={"bad_field": {"base": "nonexistent", "low": 1, "high": 2, "salt": "x"}})
    with pytest.raises(ValueError, match="nonexistent"):
        synth_date_fields("r1", date(2020, 1, 1), broken_rules)


from datetime import timedelta

from psm.synth import synth_status_fields


def test_action_status_completed_after_two_years():
    rules = load_rules()
    reference = date.fromisoformat(rules["reference_date"])
    out = synth_status_fields("r1", reference - timedelta(days=731), rules)
    assert out["action_status"] == "Completed"
    assert out["schedule_status"] == "N/A"


def test_action_status_boundary_at_exactly_two_years_is_not_yet_completed():
    rules = load_rules()
    reference = date.fromisoformat(rules["reference_date"])
    out = synth_status_fields("r1", reference - timedelta(days=730), rules)
    assert out["action_status"] == "In Progress"  # age_days == 730 is NOT > 730


def test_action_status_in_progress_between_six_months_and_two_years():
    rules = load_rules()
    reference = date.fromisoformat(rules["reference_date"])
    out = synth_status_fields("r1", reference - timedelta(days=400), rules)
    assert out["action_status"] == "In Progress"
    assert out["schedule_status"] in {"On Schedule", "Behind"}


def test_action_status_pending_under_six_months():
    rules = load_rules()
    reference = date.fromisoformat(rules["reference_date"])
    out = synth_status_fields("r1", reference - timedelta(days=100), rules)
    assert out["action_status"] == "Pending"


def test_status_changes_with_reference_date_not_wall_clock():
    """Regression test for the wall-clock bug the rev-2 review caught: the
    bucket must change only because rules['reference_date'] changed, never
    because of an internal date.today() call."""
    rules = load_rules()
    incident_date = date(2024, 1, 1)
    rules_soon = dict(rules, reference_date="2024-06-01")
    rules_later = dict(rules, reference_date="2026-03-01")
    assert synth_status_fields("r1", incident_date, rules_soon)["action_status"] == "Pending"
    assert synth_status_fields("r1", incident_date, rules_later)["action_status"] == "Completed"


from psm.synth import synth_severity_fields


def test_fatality_maps_to_very_serious():
    rules = load_rules()
    fields, anomalies = synth_severity_fields(frozenset({"Fatality"}), 50000.0, rules)
    assert fields["incident_classification"] == "Very Serious"
    assert fields["worst_reasonable_outcome"] == "Very Serious"
    assert fields["involves_fatality_or_injury"] is True
    assert fields["hs_risk_score"] == 9
    assert fields["unmitigated_risk_score"] == 9
    assert fields["mitigated_risk_score"] == 7
    assert anomalies == []


def test_multiple_checkboxes_spanning_tiers_takes_highest():
    rules = load_rules()
    fields, _ = synth_severity_fields(frozenset({"Fire", "Fatality"}), 1000.0, rules)
    assert fields["incident_classification"] == "Very Serious"


def test_resolved_but_unlisted_type_falls_back_to_incident_tier():
    rules = load_rules()
    fields, anomalies = synth_severity_fields(frozenset({"Crane"}), 1000.0, rules)
    assert fields["incident_classification"] == "Incident"
    assert fields["hs_risk_score"] == 2
    assert fields["mitigated_risk_score"] == 1  # floored, not negative
    assert anomalies == []


def test_empty_incident_types_is_unknown_and_logged():
    rules = load_rules()
    fields, anomalies = synth_severity_fields(frozenset(), 1000.0, rules)
    assert fields["incident_classification"] == "Unknown"
    assert fields["hs_risk_score"] is None
    assert fields["unmitigated_risk_score"] is None
    assert fields["mitigated_risk_score"] is None
    assert any(a["type"] == "unresolved_incident_classification" for a in anomalies)


def test_pollution_gates_environment_score():
    rules = load_rules()
    with_pollution, _ = synth_severity_fields(frozenset({"Fatality", "Pollution"}), 1000.0, rules)
    without_pollution, _ = synth_severity_fields(frozenset({"Fatality"}), 1000.0, rules)
    assert with_pollution["environment_reputation_classification"] == "Very Serious"
    assert with_pollution["environment_reputation_score"] == 9
    assert without_pollution["environment_reputation_classification"] == "None"
    assert without_pollution["environment_reputation_score"] == 0


def test_financial_thresholds_are_boundary_exact():
    rules = load_rules()
    at_25000, _ = synth_severity_fields(frozenset({"Crane"}), 25000.0, rules)
    just_over, _ = synth_severity_fields(frozenset({"Crane"}), 25000.01, rules)
    assert at_25000["financial_classification"] == "Minor"
    assert just_over["financial_classification"] == "Moderate"


def test_missing_property_damage_is_unknown_and_logged():
    rules = load_rules()
    fields, anomalies = synth_severity_fields(frozenset({"Crane"}), None, rules)
    assert fields["financial_classification"] == "Unknown"
    assert fields["financial_score"] is None
    assert any(a["type"] == "unresolved_property_damage" for a in anomalies)


def test_mitigated_never_exceeds_unmitigated():
    rules = load_rules()
    for types in (frozenset({"Fatality"}), frozenset({"Injury"}), frozenset({"Crane"})):
        fields, _ = synth_severity_fields(types, 1000.0, rules)
        assert fields["mitigated_risk_score"] <= fields["unmitigated_risk_score"]


from psm.synth import synth_incident_title


def test_incident_title_happy_path():
    rules = load_rules()
    assert synth_incident_title(frozenset({"Fatality"}), "MP 298", rules) == "Fatality incident at MP 298"


def test_incident_title_multiple_types_sorted_for_determinism():
    rules = load_rules()
    assert synth_incident_title(frozenset({"Fire", "Crane"}), "MP 298", rules) == "Crane, Fire incident at MP 298"


def test_incident_title_empty_types_uses_fallback():
    rules = load_rules()
    assert synth_incident_title(frozenset(), "MP 298", rules) == "Unspecified incident at MP 298"
