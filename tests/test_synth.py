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
