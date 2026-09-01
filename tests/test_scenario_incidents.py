# tests/test_scenario_incidents.py
"""The incidents builder: exact donor headers, closed provenance subset
{"", src, syn, key}, skip semantics, narrative dates move with the rebase."""
from datetime import date

from psm import scenario as sc


CFG = sc.load_scenario("northstar")


def _plan(donor_id):
    return sc.make_plan("northstar", CFG, donor_id)


def test_fieldnames_are_the_donor_headers_byte_exact():
    cols = sc.incident_fieldnames()
    assert cols[0] == "Incident Number"
    assert "What happened?  " in cols                 # two trailing spaces
    assert "Incident Classificatioin" in cols         # sic, from source
    assert "Investigation Acceptor/Approver (Owner)- Position" in cols  # no space before dash, sic


def test_row_covers_every_column_and_provenance_is_closed_subset():
    donors = sc.donor_partition("northstar")[:20]
    cols = set(sc.incident_fieldnames())
    for d in donors:
        p = _plan(d)
        row, prov = sc.build_incident_row(p, sc.donor_incidents()[d])
        assert set(row) == cols and set(prov) == cols
        assert set(prov.values()) <= {"", "src", "syn", "key"}
        assert prov["Incident Number"] == "key"
        for c in cols:
            assert (prov[c] == "") == (not row[c].strip()), c


def test_date_chain_orders_and_derives_from_the_plan():
    d = sc.donor_partition("northstar")[0]
    p = _plan(d)
    row, _ = sc.build_incident_row(p, sc.donor_incidents()[d])
    doi = date.fromisoformat(row["Date of Incident"])
    rep = date.fromisoformat(row["Date of Report"])
    assert sc.WINDOW_START <= doi <= sc.WINDOW_END
    assert (rep - doi).days == p.report_lag
    if not p.skipped:
        app = date.fromisoformat(row["Approval Date"])
        assert (app - rep).days == p.invest_days


def test_skipped_incident_has_no_leader_no_approval():
    donors = sc.donor_partition("coastal")           # skip_rate 0.20: hits exist
    ccfg = sc.load_scenario("coastal")
    skipped = [d for d in donors
               if sc.make_plan("coastal", ccfg, d).skipped]
    assert skipped, "coastal partition produced zero skips -- investigate"
    p = sc.make_plan("coastal", ccfg, skipped[0])
    row, prov = sc.build_incident_row(p, sc.donor_incidents()[skipped[0]])
    assert row["Investigation leader - Name"] == ""
    assert row["Approval Date"] == ""
    assert row["Close out Date"] == ""


def test_narratives_are_shifted_by_the_rebase_delta():
    donor_row = {
        "Incident Number": "GC-478-20240502-1620",
        "Date of Incident": "2024-05-02",
        "What happened?  ": "On May 2, 2024 the crane boom contacted the rail.",
    }
    p = _plan("GC-478-20240502-1620")
    row, prov = sc.build_incident_row(p, donor_row)
    delta = sc.donor_delta(p)
    shifted = date(2024, 5, 2) + __import__("datetime").timedelta(days=delta)
    assert f"{shifted.strftime('%B')} {shifted.day}, {shifted.year}" in row["What happened?  "]
    assert prov["What happened?  "] == "src"          # shifted text stays src; About discloses


def test_anchor_clamp_reserves_room_for_near_incident_prose_dates():
    # a donor narrating an event 60 days before the incident can never be
    # placed in the window's first 60 days
    donor = "GC-478-20240502-1620"
    look, fwd = sc._narrative_span(donor)
    sid = sc.scenario_incident_number("northstar", donor)
    d = sc.anchored_incident_date("northstar", sid, donor)
    from datetime import timedelta
    assert d >= sc.WINDOW_START + timedelta(days=look)
    assert d <= sc.WINDOW_END - timedelta(days=fwd)


def test_people_columns_are_syn_never_donor_values():
    d = sc.donor_partition("northstar")[1]
    p = _plan(d)
    row, prov = sc.build_incident_row(p, sc.donor_incidents()[d])
    if not p.skipped:
        assert row["Investigation leader - Name"].startswith("SYN-")
        assert prov["Investigation leader - Name"] == "syn"
    assert row["Incident Classified by - Name"].startswith("SYN-")
