"""Tests for src/psm/gold_sample.py's statement-grain stratified sampling."""
from __future__ import annotations

import csv

import pytest

from psm.gold_sample import (
    category_by_element,
    incident_year,
    load_statements,
    stratified_statement_sample,
)

CROSSWALK_FIXTURE = """
categories:
  Equipment Failure:
    primary_element: 15
  Human Performance Error:
    primary_element: 3
  Work Environment:
    primary_element: 6
"""


def _write_csv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _causes_row(incident, cause, text, element=""):
    return {
        "Incident Number": incident,
        "Cause number": cause,
        "Cause Description": text,
        "Cause type": "",
        "Risk Management Cause": "",
        "Human Factors  Cause": "",
        " Failed PSM Framework Element": element,
    }


def _incidents_row(incident, date):
    return {"Incident Number": incident, "Date of Incident": date}


def test_category_by_element_inverts_crosswalk(tmp_path):
    cw = tmp_path / "crosswalk.yaml"
    cw.write_text(CROSSWALK_FIXTURE, encoding="utf-8")
    mapping = category_by_element(cw)
    assert mapping == {"15": "Equipment Failure", "3": "Human Performance Error", "6": "Work Environment"}


def test_incident_year_parses_leading_four_digits():
    rows = [_incidents_row("A-1", "2019-03-04"), _incidents_row("A-2", ""), _incidents_row("A-3", "bad-date")]
    years = incident_year(rows)
    assert years == {"A-1": 2019, "A-2": None, "A-3": None}


@pytest.fixture()
def fixture_paths(tmp_path, monkeypatch):
    causes_path = tmp_path / "causes.csv"
    incidents_path = tmp_path / "incidents.csv"
    llm_path = tmp_path / "llm_causes.csv"
    cw_path = tmp_path / "crosswalk.yaml"
    cw_path.write_text(CROSSWALK_FIXTURE, encoding="utf-8")
    monkeypatch.setattr("psm.gold_sample.CROSSWALK", cw_path)

    causes_fields = ["Incident Number", "Cause number", "Cause Description", "Cause type",
                      "Risk Management Cause", "Human Factors  Cause", " Failed PSM Framework Element"]
    _write_csv(causes_path, causes_fields, [
        _causes_row("A-1", "1", "Equipment failure - pump seized.", "15"),
        _causes_row("A-1", "2", "Crew missed the leak entirely.", ""),
        _causes_row("A-2", "1", "Human performance error - inattention.", "3"),
    ])
    _write_csv(incidents_path, ["Incident Number", "Date of Incident"], [
        _incidents_row("A-1", "2020-01-01"),
        _incidents_row("A-2", "2008-05-05"),
    ])
    _write_csv(llm_path, ["incident", "cause", "llm_cause_category"], [
        {"incident": "A-1", "cause": "2", "llm_cause_category": "Work Environment"},
    ])
    return causes_path, incidents_path, llm_path


def test_load_statements_prefers_xw_over_llm(fixture_paths):
    causes_path, incidents_path, llm_path = fixture_paths
    statements = load_statements(causes_path, incidents_path, llm_path)
    by_key = {(s["incident"], s["cause"]): s for s in statements}

    assert by_key[("A-1", "1")]["category"] == "Equipment Failure"
    assert by_key[("A-1", "1")]["category_source"] == "xw"
    # No xw_element for A-1/2 - falls back to the llm_ signal.
    assert by_key[("A-1", "2")]["category"] == "Work Environment"
    assert by_key[("A-1", "2")]["category_source"] == "llm"
    assert by_key[("A-1", "1")]["era"] == "modern_six"
    assert by_key[("A-2", "1")]["era"] == "human_error"


def test_load_statements_no_llm_file_leaves_category_blank(fixture_paths):
    causes_path, incidents_path, _ = fixture_paths
    statements = load_statements(causes_path, incidents_path, incidents_path.parent / "missing.csv")
    by_key = {(s["incident"], s["cause"]): s for s in statements}
    assert by_key[("A-1", "2")]["category"] == ""
    assert by_key[("A-1", "2")]["category_source"] == ""


def _statement(incident, cause, category, era):
    return {"incident": incident, "cause": cause, "text": "x", "category": category,
            "category_source": "xw" if category else "", "era": era}


def test_category_floor_is_capped_by_availability():
    statements = [_statement(f"I{i}", "1", "Equipment Failure", "modern_six") for i in range(5)]
    sample = stratified_statement_sample(statements, target_n=5, category_floor=30, min_per_era=1)
    assert len(sample) == 5


def test_category_floor_does_not_exceed_the_floor_within_its_own_pass():
    # The category pass itself stops at the floor; era-fill (same era, same
    # category here) is what pulls in the rest up to target_n/availability -
    # floor caps a category's *guaranteed* share, not its total representation.
    statements = [_statement(f"I{i}", "1", "Equipment Failure", "modern_six") for i in range(50)]
    sample = stratified_statement_sample(statements, target_n=10, category_floor=10, min_per_era=1)
    assert len(sample) == 10


def test_era_fill_covers_remaining_budget_across_eras():
    statements = []
    for era, n in {"free_prose": 20, "human_error": 20, "ad_hoc": 20, "modern_six": 20}.items():
        statements += [_statement(f"{era}-{i}", "1", "", era) for i in range(n)]
    sample = stratified_statement_sample(statements, target_n=40, category_floor=30, min_per_era=1)
    eras = {s["era"] for s in sample}
    assert eras == {"free_prose", "human_error", "ad_hoc", "modern_six"}
    assert len(sample) == 40


def test_sample_never_duplicates_a_statement():
    statements = [_statement("I1", "1", "Equipment Failure", "modern_six")]
    statements += [_statement(f"I{i}", "1", "", "modern_six") for i in range(2, 10)]
    sample = stratified_statement_sample(statements, target_n=9, category_floor=30, min_per_era=1)
    keys = [(s["incident"], s["cause"]) for s in sample]
    assert len(keys) == len(set(keys))


def test_sample_is_deterministic_across_calls():
    statements = [_statement(f"I{i}", "1", "", "modern_six") for i in range(30)]
    first = stratified_statement_sample(statements, target_n=10, category_floor=30)
    second = stratified_statement_sample(statements, target_n=10, category_floor=30)
    assert [(s["incident"], s["cause"]) for s in first] == [(s["incident"], s["cause"]) for s in second]


def test_sample_selection_is_stable_under_row_reordering():
    statements = [_statement(f"I{i}", "1", "", "modern_six") for i in range(30)]
    sample_a = stratified_statement_sample(statements, target_n=5, category_floor=30)
    sample_b = stratified_statement_sample(list(reversed(statements)), target_n=5, category_floor=30)
    keys_a = {(s["incident"], s["cause"]) for s in sample_a}
    keys_b = {(s["incident"], s["cause"]) for s in sample_b}
    assert keys_a == keys_b
