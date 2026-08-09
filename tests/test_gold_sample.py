"""Tests for src/psm/gold_sample.py's stratified sampling."""
from __future__ import annotations

from psm.gold_sample import effective_year, stratified_sample


def _row(url: str, year: str | None, index_year: str = "", report_type: str = "district") -> dict:
    return {
        "src_url": url,
        "src_year": year or "",
        "src_index_year": index_year,
        "src_report_type": report_type,
    }


def test_effective_year_prefers_src_year():
    assert effective_year(_row("u", "2019", index_year="2020")) == "2019"


def test_effective_year_falls_back_to_index_year():
    assert effective_year(_row("u", None, index_year="2020")) == "2020"


def test_effective_year_unknown_when_neither_present():
    assert effective_year(_row("u", None)) == "unknown"


def test_sample_excludes_panel_reports():
    rows = [_row(f"u{i}", "2020", report_type="panel") for i in range(10)]
    rows += [_row(f"d{i}", "2020") for i in range(5)]
    sample = stratified_sample(rows, target_n=5)
    assert all(r["src_report_type"] == "district" for r in sample)
    assert len(sample) == 5


def test_sample_covers_every_year_present():
    rows = []
    for year, n in {"2005": 3, "2010": 50, "2020": 50, "2026": 2}.items():
        rows += [_row(f"{year}-{i}", year) for i in range(n)]
    sample = stratified_sample(rows, target_n=20)
    years = {effective_year(r) for r in sample}
    assert years == {"2005", "2010", "2020", "2026"}


def test_sample_never_exceeds_a_years_availability():
    rows = [_row(f"u{i}", "2003") for i in range(3)]
    rows += [_row(f"v{i}", "2020") for i in range(200)]
    sample = stratified_sample(rows, target_n=20)
    per_year: dict[str, int] = {}
    for r in sample:
        per_year[effective_year(r)] = per_year.get(effective_year(r), 0) + 1
    assert per_year["2003"] == 3  # capped by availability, not by allocation


def test_sample_hits_target_n_when_capacity_allows():
    rows = []
    for year in ("2003", "2010", "2020", "2026"):
        rows += [_row(f"{year}-{i}", year) for i in range(50)]
    sample = stratified_sample(rows, target_n=40)
    assert len(sample) == 40


def test_sample_is_deterministic_across_calls():
    rows = [_row(f"u{i}", "2020") for i in range(30)]
    rows += [_row(f"v{i}", "2021") for i in range(30)]
    first = stratified_sample(rows, target_n=10)
    second = stratified_sample(rows, target_n=10)
    assert [r["src_url"] for r in first] == [r["src_url"] for r in second]


def test_sample_selection_is_stable_under_row_reordering():
    rows = [_row(f"u{i}", "2020") for i in range(30)]
    sample_a = stratified_sample(rows, target_n=5)
    sample_b = stratified_sample(list(reversed(rows)), target_n=5)
    assert {r["src_url"] for r in sample_a} == {r["src_url"] for r in sample_b}
