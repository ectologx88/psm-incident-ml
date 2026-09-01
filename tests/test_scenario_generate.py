# tests/test_scenario_generate.py
from datetime import date

from psm import scenario as sc
from psm.templates import classify_action


def test_generate_northstar_shape_and_closed_provenance():
    res = sc.generate("northstar")
    t = res["tables"]
    assert set(t) == {"incidents", "causes", "recommendations", "closeout"}
    cols, rows, prov = t["incidents"]
    assert len(rows) == 150 and len(prov) == 150
    for name in t:
        _, rws, prv = t[name]
        assert len(rws) == len(prv)
        for p in prv:
            assert set(p.values()) <= {"", "src", "syn", "key"}, name


def test_every_rec_has_a_closeout_row_and_registry_text():
    res = sc.generate("northstar")
    _, recs, _ = res["tables"]["recommendations"]
    _, close, _ = res["tables"]["closeout"]
    assert len(recs) == len(close)
    keys = {(r["Incident Number"], r["Recommendation Number"]) for r in recs}
    assert {(c["Incident Number"], c["Recommendation Number"])
            for c in close} == keys
    for r in recs:
        classify_action(r["Recommendation Description"])   # KeyError = failure
    for c in close:
        assert c["Schedule Status"] in ("On Schedule", "Behind")
        date.fromisoformat(c["Date Completed"])


def test_schedule_status_matches_the_date_comparison():
    res = sc.generate("northstar")
    _, recs, _ = res["tables"]["recommendations"]
    _, close, _ = res["tables"]["closeout"]
    agreed = {(r["Incident Number"], r["Recommendation Number"]):
              date.fromisoformat(r["Agreed Completion Date"]) for r in recs}
    for c in close:
        done = date.fromisoformat(c["Date Completed"])
        expect = "Behind" if done > agreed[
            (c["Incident Number"], c["Recommendation Number"])] else "On Schedule"
        assert c["Schedule Status"] == expect


def test_meridian_plants_eight_maintenance_pairs_and_detector_finds_them():
    res = sc.generate("meridian")
    pairs = res["planted_pairs"]
    assert len(pairs) == 8
    _, incs, _ = res["tables"]["incidents"]
    _, causes, _ = res["tables"]["causes"]
    by_id = {r["Incident Number"]: r for r in incs}
    for a, b in pairs:
        assert by_id[a]["Work Group"] == by_id[b]["Work Group"] == "Maintenance"
    detected = set(map(tuple, sc.detect_recurrence_pairs(incs, causes, 365)))
    assert set(map(tuple, pairs)) <= detected


def test_planted_pair_ordering_invariants():
    res = sc.generate("meridian")
    _, incs, _ = res["tables"]["incidents"]
    by_id = {r["Incident Number"]: r for r in incs}
    for a, b in res["planted_pairs"]:
        doi_a = date.fromisoformat(by_id[a]["Date of Incident"])
        doi_b = date.fromisoformat(by_id[b]["Date of Incident"])
        close_a = date.fromisoformat(by_id[a]["Close out Date"])
        assert doi_b > close_a
        assert (doi_b - doi_a).days <= 365
        assert sc.WINDOW_START <= doi_b <= sc.WINDOW_END


def test_generate_is_deterministic_in_process():
    a = sc.generate("northstar")
    b = sc.generate("northstar")
    assert a["tables"] == b["tables"]
