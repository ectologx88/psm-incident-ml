"""Tests for src/psm/gold_scaffold.py's statement-grain worksheet assembly."""
from __future__ import annotations

import csv

from psm.gold_scaffold import GOLD_COLUMNS, REFERENCE_COLUMNS, build_rows


def _write_csv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def test_build_rows_never_prefills_gold_columns(tmp_path):
    causes_path = tmp_path / "causes.csv"
    incidents_path = tmp_path / "incidents.csv"
    _write_csv(causes_path, ["Incident Number", "Cause number", "Cause Description"], [
        {"Incident Number": "A-1", "Cause number": "1", "Cause Description": "Pump seized."},
    ])
    _write_csv(incidents_path, ["Incident Number", "Date of Incident", "Site", "Area",
                                 "Incident Classificatioin"], [
        {"Incident Number": "A-1", "Date of Incident": "2020-06-01", "Site": "GC 478",
         "Area": "GC", "Incident Classificatioin": "Very Serious"},
    ])

    rows = build_rows([("A-1", "1")], causes_path, incidents_path)
    assert len(rows) == 1
    row = rows[0]
    for col in GOLD_COLUMNS:
        assert row[col] == ""
    assert row["report_id"] == "A-1-1"
    assert row["incident"] == "A-1"
    assert row["cause"] == "1"
    assert row["effective_year"] == 2020
    assert row["era_regime"] == "modern_six"
    assert row["src_site"] == "GC 478"
    assert row["src_area"] == "GC"
    assert row["src_incident_classification"] == "Very Serious"
    assert row["src_cause_description"] == "Pump seized."


def test_build_rows_never_surfaces_xw_or_llm_signal(tmp_path):
    causes_path = tmp_path / "causes.csv"
    incidents_path = tmp_path / "incidents.csv"
    _write_csv(causes_path, ["Incident Number", "Cause number", "Cause Description",
                              " Failed PSM Framework Element"], [
        {"Incident Number": "A-1", "Cause number": "1", "Cause Description": "Pump seized.",
         " Failed PSM Framework Element": "15"},
    ])
    _write_csv(incidents_path, ["Incident Number", "Date of Incident"], [
        {"Incident Number": "A-1", "Date of Incident": "2020-06-01"},
    ])

    rows = build_rows([("A-1", "1")], causes_path, incidents_path)
    assert set(rows[0]) == set(REFERENCE_COLUMNS) | set(GOLD_COLUMNS)


def test_build_rows_handles_a_key_missing_from_either_table(tmp_path):
    causes_path = tmp_path / "causes.csv"
    incidents_path = tmp_path / "incidents.csv"
    _write_csv(causes_path, ["Incident Number", "Cause number", "Cause Description"], [])
    _write_csv(incidents_path, ["Incident Number", "Date of Incident"], [])

    rows = build_rows([("MISSING-1", "1")], causes_path, incidents_path)
    row = rows[0]
    assert row["src_cause_description"] == ""
    assert row["effective_year"] == ""
    assert row["era_regime"] == "undated"
