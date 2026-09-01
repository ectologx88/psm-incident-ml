# tests/test_kpi.py
from pathlib import Path

from psm import scenario as sc
from psm.kpi import compute_kpis, load_company

KEYS = {"median_report_lag", "skip_rate", "root_cause_depth",
        "median_closeout_days", "overdue_rate", "recurrence_rate",
        "admin_ppe_share", "owner_completeness", "hs_completeness"}


def _mem_tables(company):
    res = sc.generate(company)
    return {name: rows for name, (cols, rows, prov) in res["tables"].items()}


def test_kpis_have_exactly_the_nine_keys_and_sane_ranges():
    k = compute_kpis(_mem_tables("northstar"))
    assert set(k) == KEYS
    for name in ("skip_rate", "root_cause_depth", "overdue_rate",
                 "admin_ppe_share", "owner_completeness", "hs_completeness"):
        assert 0.0 <= k[name] <= 1.0, name
    assert k["median_report_lag"] >= 0
    assert isinstance(k["recurrence_rate"], int)


ROOT = Path(__file__).resolve().parents[1] / "data" / "companies"


def test_load_company_reads_the_committed_register():
    tables = load_company(ROOT / "northstar")
    assert len(tables["incidents"]) == 150
    k = compute_kpis(tables)
    assert set(k) == KEYS


def test_kpis_move_in_the_planted_directions():
    kn = compute_kpis(_mem_tables("northstar"))
    km = compute_kpis(_mem_tables("meridian"))
    assert km["median_report_lag"] > kn["median_report_lag"]
    assert km["median_closeout_days"] > kn["median_closeout_days"]
    assert km["recurrence_rate"] >= 8


def test_skip_rate_uses_the_and_of_both_conditions():
    tables = _mem_tables("coastal")
    # every counted skip must have BOTH markers, not either
    causes_by = {}
    for c in tables["causes"]:
        causes_by.setdefault(c["Incident Number"], []).append(c)
    manual = sum(1 for r in tables["incidents"]
                 if not r["Investigation leader - Name"].strip()
                 and not causes_by.get(r["Incident Number"]))
    assert compute_kpis(tables)["skip_rate"] == manual / len(tables["incidents"])
