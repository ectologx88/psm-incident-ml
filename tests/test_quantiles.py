"""Lognormal shapes come from committed 1024-bucket integer tables so the
runtime engine needs no scipy and is byte-identical cross-platform."""
import pytest

from psm import quantiles as q


ALL_CONFIGS = [(2, 0.6), (7, 0.5), (10, 0.8), (21, 0.6), (30, 0.7),
               (40, 0.5), (45, 0.6), (60, 0.6), (130, 0.8)]


def test_configs_constant_matches_the_spec_union():
    assert set(q.CONFIGS) == set(ALL_CONFIGS)


@pytest.mark.parametrize("median,sigma", ALL_CONFIGS)
def test_table_shape_monotone_and_nonnegative(median, sigma):
    t = q.load_table(median, sigma)
    assert len(t) == 1024
    assert all(isinstance(v, int) for v in t)
    assert all(v >= 0 for v in t)
    assert all(a <= b for a, b in zip(t, t[1:]))  # ppf is monotone


@pytest.mark.parametrize("median,sigma", ALL_CONFIGS)
def test_median_bucket_lands_on_the_configured_median(median, sigma):
    t = q.load_table(median, sigma)
    mid = (t[511] + t[512]) / 2
    assert abs(mid - median) <= max(1, 0.1 * median)


def test_draw_days_is_deterministic_and_reads_the_table():
    a = q.draw_days("northstar|X|closeout|salt", 45, 0.6)
    b = q.draw_days("northstar|X|closeout|salt", 45, 0.6)
    assert a == b
    assert a in q.load_table(45, 0.6)


def test_analytic_overdue_orders_slow_above_fast():
    fast = q.analytic_overdue_rate(45, 0.6, 30, 90)    # NorthStar shape
    slow = q.analytic_overdue_rate(130, 0.8, 30, 90)   # Meridian shape
    assert 0.0 < fast < slow < 1.0
    # DEVIATION from task-4-brief.md (factor 3): for these exact configs and
    # agreed_offset window the true ratio is ~2.33x (verified both via this
    # 1024-bucket table and independently via scipy's continuous lognormal
    # CDF -- no correct implementation of analytic_overdue_rate can clear
    # 3x here). The brief's "3x" appears to have been carried over from the
    # *measured*, full-pipeline overdue_rate KPI row in
    # docs/superpowers/specs/2026-08-31-scenario-registers-design.md:233,
    # not this isolated two-point analytic check; the neighboring
    # median_closeout_days plant in that same spec (line 211-213) uses
    # factor 2.0, which this ratio clears with margin. See task-4-report.md.
    assert slow > 2 * fast  # the planted closeout decay is visible analytically
