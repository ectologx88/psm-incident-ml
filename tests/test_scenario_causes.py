from psm import scenario as sc

CFG = sc.load_scenario("northstar")
CCFG = sc.load_scenario("coastal")


def _rows(company, cfg, donor):
    p = sc.make_plan(company, cfg, donor)
    return p, sc.build_cause_rows(p, sc.donor_incidents()[donor])


def test_chain_types_are_ordered_and_root_gated():
    for donor in sc.donor_partition("northstar")[:40]:
        p, (rows, prov) = _rows("northstar", CFG, donor)
        types = [r["Cause type"] for r in rows]
        assert types == ["Immediate", "Underlying", "Root"][:len(types)]
        assert (len(rows) == 0) == p.skipped
        if not p.skipped:
            assert ("Root" in types) == p.reaches_root
            assert 1 <= len(rows) <= 3


def test_rows_carry_sid_ordinals_and_closed_provenance():
    donor = sc.donor_partition("northstar")[0]
    p, (rows, prov) = _rows("northstar", CFG, donor)
    for i, (r, pr) in enumerate(zip(rows, prov), 1):
        assert r["Incident Number"] == p.sid and pr["Incident Number"] == "key"
        assert r["Cause number"] == str(i) and pr["Cause number"] == "syn"
        assert pr["Cause type"] == "syn"
        assert set(pr.values()) <= {"", "src", "syn", "key"}
        assert r["Cause Description"].strip()
        assert pr["Cause Description"] == "src"


def test_element_override_wins_and_is_syn():
    donor = sc.donor_partition("meridian")[0]
    p = sc.make_plan("meridian", sc.load_scenario("meridian"), donor)
    if p.skipped:
        donor = sc.donor_partition("meridian")[1]
        p = sc.make_plan("meridian", sc.load_scenario("meridian"), donor)
    p.element_override = "15"
    rows, prov = sc.build_cause_rows(p, sc.donor_incidents()[donor])
    assert rows[0][" Failed PSM Framework Element"] == "15"
    assert prov[0][" Failed PSM Framework Element"] == "syn"


def test_coastal_truncates_most_chains():
    donors = sc.donor_partition("coastal")
    plans = [sc.make_plan("coastal", CCFG, d) for d in donors]
    invest = [p for p in plans if not p.skipped]
    rooted = sum(1 for p in invest if p.reaches_root)
    assert rooted / len(invest) < 0.5    # 0.25 knob; generous determinism bound
