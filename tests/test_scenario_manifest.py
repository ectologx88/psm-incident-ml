import json
from pathlib import Path

from psm import scenario as sc
from psm.quantiles import analytic_overdue_rate

KPIS = {"median_report_lag", "skip_rate", "root_cause_depth",
        "median_closeout_days", "overdue_rate", "recurrence_rate",
        "admin_ppe_share", "owner_completeness", "hs_completeness"}


def test_manifest_asserts_every_kpi_somewhere():
    for company in ("northstar", "meridian"):
        m = sc.build_manifest(company, sc.generate(company))
        covered = ({p["kpi"] for p in m["plants"]}
                   | set(m["analytic_expectations"].get("kpi_map", {}))
                   | {c.split("(")[0] for c in m["negative_controls"]})
        assert KPIS <= covered, (company, KPIS - covered)


def test_manifest_records_partition_window_knobs_and_sha():
    m = sc.build_manifest("meridian", sc.generate("meridian"))
    assert m["company"] == "meridian"
    assert len(m["donor_partition"]) == 150
    assert m["window"] == {"start": "2021-01-01", "end": "2025-12-31"}
    assert m["scenario_sha256"] == sc.scenario_sha256("meridian")
    assert m["resolved_knobs"] == sc.load_scenario("meridian")
    ov = m["analytic_expectations"]["overdue_rate"]
    assert ov == analytic_overdue_rate(130, 0.8, 30, 90)


def test_meridian_manifest_lists_eight_recurrence_pairs():
    res = sc.generate("meridian")
    m = sc.build_manifest("meridian", res)
    rec = [p for p in m["plants"] if p["pathology"] == "recurrence_after_closure"]
    assert len(rec) == 1 and len(rec[0]["affected_ids"]) == 8


def test_committed_registers_match_a_fresh_generate():
    # after the CLI has run and data is committed, regeneration is identical
    for company in ("northstar", "meridian"):
        out = Path(sc.OUT_ROOT) / company
        assert (out / "manifest.json").exists(), "run the CLI first"
        fresh = sc.build_manifest(company, sc.generate(company))
        on_disk = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert on_disk == fresh
