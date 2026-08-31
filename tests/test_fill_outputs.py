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
def test_every_non_empty_cell_has_a_provenance(value_name, prov_name):
    """The filled/ counterpart of test_conventions.py's enriched/ check of the
    same name. A value with no provenance is exactly what the prefix rule
    prevents everywhere else in this repo; here the parallel file has to do
    that job, and fill.py is one more place it could quietly fail to."""
    values, prov = _rows(FILLED / value_name), _rows(FILLED / prov_name)
    missing = sum(1 for d, p in zip(values, prov) for c in d
                  if (d[c] or "").strip() and not p[c])
    assert missing == 0, f"{value_name}: {missing} non-empty cells carry no provenance"


@pytest.mark.parametrize("value_name,prov_name", [
    ("causes.csv", "causes_provenance.csv"),
    ("incidents.csv", "provenance.csv"),
])
def test_no_provenance_without_a_value(value_name, prov_name):
    """The other direction: a provenance token with no cell behind it."""
    values, prov = _rows(FILLED / value_name), _rows(FILLED / prov_name)
    orphan = sum(1 for d, p in zip(values, prov) for c in d
                 if p[c] and not (d[c] or "").strip())
    assert orphan == 0, f"{value_name}: {orphan} provenance marks with no value"


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


def test_fill_column_manifest_matches_columns_actually_marked_syn():
    """Drift guard for FILL_COLUMN_MANIFEST / SYN_FALLBACK_COLUMNS, checked
    against the real committed filled/ provenance files (this module's
    skipif is false when they exist, so this genuinely executes on real
    data, not a fixture).

    Scope: a column counts here only if FILL.PY itself stamped a `syn` token
    that was not already `syn` in enriched/ -- i.e. a cell where fill wrote
    a new value into a blank. enriched/ already carries plenty of `syn`
    cells of its own (synth.py's incident-workflow columns, wired long
    before fill.py existed and audited separately by
    test_ledger.py::test_synthetic_columns_carry_syn_provenance); fill.py
    never touches those, so they must not count as fill-introduced drift.

    Two directions:
    - every column some manifest entry's `columns` list names must actually
      carry a fill-introduced `syn` token in the real data -- a declared
      column that turns out never to be filled is as stale a claim as an
      undeclared one;
    - every column that carries any fill-introduced `syn` token must be
      named by some manifest entry or listed in SYN_FALLBACK_COLUMNS. This
      is the direction with teeth: it turns a future syn-filled column
      nobody documented into a failing test instead of a silent gap.
    """
    from psm.fill import FILL_COLUMN_MANIFEST, SYN_FALLBACK_COLUMNS

    declared = {
        col for entry in FILL_COLUMN_MANIFEST.values() for col in entry["columns"]
    }

    syn_columns = set()
    for prov_name in ("causes_provenance.csv", "provenance.csv"):
        enriched_prov = _rows(ENRICHED / prov_name)
        filled_prov = _rows(FILLED / prov_name)
        for col in filled_prov[0]:
            for e_row, f_row in zip(enriched_prov, filled_prov):
                if f_row[col] == "syn" and e_row[col] != "syn":
                    syn_columns.add(col)
                    break

    missing_syn = declared - syn_columns
    assert not missing_syn, (
        f"FILL_COLUMN_MANIFEST declares these columns but fill.py never "
        f"stamps a new syn token into them in filled/: {missing_syn}")

    known = declared | SYN_FALLBACK_COLUMNS
    undeclared = syn_columns - known
    assert not undeclared, (
        f"fill.py stamps a new syn token into these columns but they are "
        f"declared in neither FILL_COLUMN_MANIFEST nor SYN_FALLBACK_COLUMNS: "
        f"{undeclared}")
