"""Invariants over the real data/processed/e19/filled/ outputs.

Mirrors the conventions test_conventions.py enforces for enriched/: parallel
provenance shape, closed token set, no un-provenanced fill — plus the fill
contract itself: never overwrite a non-empty enriched value.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
E19 = REPO / "data" / "processed" / "e19"
FILLED, ENRICHED = E19 / "filled", E19 / "enriched"
TOKENS = {"", "src", "xw", "llm", "gold", "syn"}

pytestmark = pytest.mark.skipif(
    not (FILLED / "causes.csv").exists(), reason="filled/ not built"
)


def _rows(path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.mark.parametrize("value_name,prov_name", [
    ("causes.csv", "causes_provenance.csv"),
    ("incidents.csv", "provenance.csv"),
])
def test_provenance_matches_shape_and_closed_set(value_name, prov_name):
    values, prov = _rows(FILLED / value_name), _rows(FILLED / prov_name)
    assert len(values) == len(prov)
    assert values[0].keys() == prov[0].keys()
    bad = {t for p in prov for t in p.values()} - TOKENS
    assert not bad, f"tokens outside closed set: {bad}"


@pytest.mark.parametrize("value_name,prov_name", [
    ("causes.csv", "causes_provenance.csv"),
    ("incidents.csv", "provenance.csv"),
])
def test_fill_never_overwrote_a_non_empty_enriched_value(value_name, prov_name):
    enriched, filled = _rows(ENRICHED / value_name), _rows(FILLED / value_name)
    assert len(enriched) == len(filled)
    for before, after in zip(enriched, filled):
        for col, val in before.items():
            if val.strip():
                assert after[col] == val, (value_name, col, before["Incident Number"])


def test_every_element_cell_is_filled_and_provenanced():
    values = _rows(FILLED / "causes.csv")
    prov = _rows(FILLED / "causes_provenance.csv")
    col = " Failed PSM Framework Element"
    assert all(r[col].strip() for r in values)
    assert all(p[col] in {"xw", "llm", "syn"} for p in prov)


def test_llm_cells_match_the_labelling_run_exactly():
    values = _rows(FILLED / "causes.csv")
    prov = _rows(FILLED / "causes_provenance.csv")
    llm = {(r["incident"], r["cause"]): r["llm_psm_element"].strip()
           for r in _rows(E19 / "llm_causes.csv")}
    col = " Failed PSM Framework Element"
    checked = 0
    for v, p in zip(values, prov):
        if p[col] == "llm":
            key = (v["Incident Number"], v["Cause number"])
            assert v[col] == llm[key], key
            checked += 1
    assert checked > 1500  # the llm fill is the bulk of the layer
