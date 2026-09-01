# tests/test_scenario_foundations.py
"""Deterministic plumbing for the scenario engine: disjoint donor
partitions, non-leaking ids, in-window anchors, format-preserving prose
date shifting."""
from datetime import date

from psm import scenario as sc


def test_partitions_are_disjoint_exact_150_and_deterministic():
    parts = {c: sc.donor_partition(c) for c in sc.COMPANY_ORDER}
    all_ids = set(sc.donor_ids())
    assert len(all_ids) == 1214
    seen = set()
    for c in sc.COMPANY_ORDER:
        assert len(parts[c]) == 150
        assert set(parts[c]) <= all_ids
        assert not (set(parts[c]) & seen)
        seen |= set(parts[c])
    assert parts["northstar"] == sc.donor_partition("northstar")  # stable
    # the test-only variant reuses northstar's slice (it is never exported,
    # so exported-company disjointness is preserved)
    assert sc.donor_partition("meridian_nt") == parts["northstar"]


def test_scenario_incident_number_never_leaks_the_donor_date():
    sid = sc.scenario_incident_number("northstar", "GC-478-20240502-1620")
    assert sid.startswith("NS-")
    assert "20240502" not in sid and "GC-478" not in sid
    assert sid == sc.scenario_incident_number("northstar", "GC-478-20240502-1620")


def test_base_incident_date_is_inside_the_window():
    for donor in sc.donor_partition("northstar")[:25]:
        sid = sc.scenario_incident_number("northstar", donor)
        d = sc.base_incident_date("northstar", sid)
        assert sc.WINDOW_START <= d <= sc.WINDOW_END


def test_pick_weighted_is_exhaustive_and_deterministic():
    got = {sc.pick_weighted(f"k{i}", sc.WORK_GROUP_WEIGHTS) for i in range(500)}
    assert got == {w for w, _ in sc.WORK_GROUP_WEIGHTS}


def test_load_scenario_has_all_knob_groups():
    for name in ("northstar", "meridian", "coastal", "meridian_nt"):
        cfg = sc.load_scenario(name)
        assert set(cfg) >= {"report_lag", "investigation", "closeout",
                            "agreed_offset", "recurrence", "controls_mix",
                            "data_discipline"}


def test_shift_prose_dates_preserves_format_and_moves_all_forms():
    text = ("On May 2, 2024 the crane failed. Reported 05/02/2024; "
            "memo of 17-OCT-2020 refers; ISO 2024-05-02; also 2 May 2024. "
            "Not a date: 13/45/2020.")
    out = sc.shift_prose_dates(text, 10)
    assert "May 12, 2024" in out
    assert "5/12/2024" in out
    assert "27-OCT-2020" in out
    assert "2024-05-12" in out
    assert "12 May 2024" in out
    assert "13/45/2020" in out          # unparseable stays untouched
    assert "May 2, 2024" not in out


def test_shift_preserves_uppercase_month_names():
    out = sc.shift_prose_dates("OCCURRED ON OCTOBER 17, 2020 DURING LIFT", 30)
    assert "NOVEMBER 16, 2020" in out


def test_find_prose_dates_reports_every_parseable_date():
    got = sc.find_prose_dates("May 2, 2024 and 17-OCT-2020 and junk 13/45/2020")
    assert date(2024, 5, 2) in got and date(2020, 10, 17) in got
    assert len(got) == 2


def test_syn_person_is_deterministic_syn_prefixed():
    name, pos = sc.syn_person("northstar|X|leader")
    assert name.startswith("SYN-")
    assert (name, pos) == sc.syn_person("northstar|X|leader")
