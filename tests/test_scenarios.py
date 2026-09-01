# tests/test_scenarios.py
"""Finish line: every planted pathology recovered, negative controls bounded,
near-threshold resolution proven, registers reproducible and clean.
Companies are auto-discovered from data/companies/ so Task 13 (coastal)
extends coverage by committing data, not by editing this file's core tests."""
import json
import math
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from psm import scenario as sc
from psm.kpi import compute_kpis, load_company
from psm.quantiles import analytic_overdue_rate

ROOT = Path(__file__).resolve().parents[1] / "data" / "companies"
COMPANIES = sorted(p.name for p in ROOT.iterdir()
                   if (p / "manifest.json").exists())


def tol(p: float, n: int, floor: float) -> float:
    return max(floor, 3 * math.sqrt(max(p * (1 - p), 1e-9) / n))


def _mem(company):
    res = sc.generate(company)
    return {name: rows for name, (cols, rows, prov) in res["tables"].items()}


@pytest.fixture(scope="module")
def kpis():
    out = {c: compute_kpis(load_company(ROOT / c)) for c in COMPANIES}
    out["meridian_nt"] = compute_kpis(_mem("meridian_nt"))
    return out


@pytest.fixture(scope="module")
def manifests():
    return {c: json.loads((ROOT / c / "manifest.json").read_text(encoding="utf-8"))
            for c in COMPANIES}


# ---- reproducibility ----------------------------------------------------

@pytest.mark.parametrize("company", COMPANIES)
def test_committed_register_is_byte_identical_to_a_fresh_generate(company, tmp_path):
    res = sc.generate(company)
    out = tmp_path / company
    sc.write_company(res, out)
    (out / "manifest.json").write_text(
        json.dumps(sc.build_manifest(company, res), indent=2, sort_keys=True)
        + "\n", encoding="utf-8")
    for f in sorted((ROOT / company).iterdir()):
        assert (out / f.name).read_bytes() == f.read_bytes(), f.name


def test_engine_has_no_wall_clock_or_random_dependence():
    import psm.kpi, psm.quantiles, psm.scenario, psm.templates
    for mod in (psm.scenario, psm.quantiles, psm.kpi, psm.templates):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        for banned in ("date.today", "datetime.now(", "time.time(",
                       "import random", "from random"):
            assert banned not in src, (mod.__name__, banned)


# ---- planted vs measured: Meridian --------------------------------------

def test_meridian_report_lag_planted(kpis):
    assert kpis["meridian"]["median_report_lag"] > 3 * kpis["northstar"]["median_report_lag"]


def test_meridian_closeout_decay_planted(kpis):
    assert kpis["meridian"]["median_closeout_days"] > 2 * kpis["northstar"]["median_closeout_days"]


def test_meridian_recurrence_planted_and_northstar_bounded(kpis, manifests):
    assert kpis["meridian"]["recurrence_rate"] >= 8
    # NorthStar planted 0: measured count IS the recorded coincidence count
    assert kpis["northstar"]["recurrence_rate"] == \
        manifests["northstar"]["analytic_expectations"]["recurrence_coincidence"]


def test_overdue_is_emergent_and_matches_the_analytic_expectation(kpis, manifests):
    for c in COMPANIES:
        expect = manifests[c]["analytic_expectations"]["overdue_rate"]
        n = len(load_company(ROOT / c)["closeout"])
        assert abs(kpis[c]["overdue_rate"] - expect) <= tol(expect, n, 0.05), c
    # RULING (carry-forward from Task 4, adjudicated two independent ways):
    # the plan's ">3x" assertion is based on the same arithmetic error
    # corrected in tests/test_quantiles.py. Analytic overdue rates are
    # fast~=0.354 (northstar's (45, 0.6) mix) and slow~=0.827 (meridian's
    # (130, 0.8) mix) -- true ratio ~=2.335, so 3x is unsatisfiable by
    # construction (3*0.354 > 1.0). Corrected to 2x per that ruling.
    assert kpis["meridian"]["overdue_rate"] > 2 * kpis["northstar"]["overdue_rate"]


# ---- negative controls on Meridian (aids attribution) -------------------

def test_meridian_negative_controls(kpis):
    kn, km = kpis["northstar"], kpis["meridian"]
    assert abs(km["skip_rate"] - kn["skip_rate"]) <= tol(0.03, 150, 0.02)
    assert abs(km["root_cause_depth"] - kn["root_cause_depth"]) <= tol(0.85, 150, 0.10)
    assert abs(km["admin_ppe_share"] - kn["admin_ppe_share"]) <= tol(0.45, 180, 0.05)
    # scenario yamls deliberately differ (owner_assigned_rate 0.98 vs 0.95, spec "data discipline"
    # differential); this negative control means "meridian is not owner-pathological
    # (coastal-class ~0.60)", not "identical rates" — bound = designed offset + floor.
    assert abs(km["owner_completeness"] - kn["owner_completeness"]) <= 0.03 + tol(0.95, 180, 0.05)
    assert abs(km["hs_completeness"] - kn["hs_completeness"]) <= tol(0.53, 150, 0.05)


# ---- near-threshold resolution (test-only variant, never on disk) -------

def test_near_threshold_variant_is_still_detected(kpis):
    nt, kn = kpis["meridian_nt"], kpis["northstar"]
    assert nt["median_closeout_days"] > 1.2 * kn["median_closeout_days"]
    # and ONLY the closeout knob moved: report lag stays at baseline
    assert abs(nt["median_report_lag"] - kn["median_report_lag"]) <= 2


def test_meridian_nt_never_exists_on_disk():
    assert not (ROOT / "meridian_nt").exists()


# ---- prose-date window --------------------------------------------------

@pytest.mark.parametrize("company", COMPANIES)
def test_near_incident_prose_dates_land_inside_the_window(company):
    """Every prose date that referenced the incident's own timeline
    (within -365..+90 days of the donor incident) must land inside the
    company window after the shift. Historical/garbage references (the
    real corpus goes up to ~1000 years off) are exempt -- era-plausible
    or already-dirty either way."""
    tables = load_company(ROOT / company)
    partition = sc.donor_partition(company)
    sid_to_donor = {sc.scenario_incident_number(company, d): d
                    for d in partition}
    checked = 0
    for row in tables["incidents"]:
        donor_id = sid_to_donor[row["Incident Number"]]
        donor = sc.donor_incidents()[donor_id]
        try:
            donor_doi = date.fromisoformat(donor["Date of Incident"])
        except ValueError:
            # Real donor corpus has ~3% blank "Date of Incident" cells
            # (repo policy: "source data is dirty and stays dirty" --
            # see project CLAUDE.md). scenario._narrative_span() already
            # guards this identical lookup with the same try/except and
            # treats it as zero near-window prose dates, so there is
            # nothing to check for this donor here either.
            continue
        for col in sc._FREE_TEXT:
            for p in sc.find_prose_dates(row[col]):
                doi = date.fromisoformat(row["Date of Incident"])
                original = p - (doi - donor_doi)     # undo the shift
                off = (donor_doi - original).days
                if 0 <= off <= sc._NEAR_LOOKBACK or -sc._NEAR_FORWARD <= off < 0:
                    assert sc.WINDOW_START <= p <= sc.WINDOW_END, (
                        row["Incident Number"], col, p)
                    checked += 1
    assert checked > 50, "window test exercised too few dates -- investigate"


# ---- text hygiene -------------------------------------------------------

_BANNED = re.compile(r"\b(MMS|OSM|BSEE|District|Regional Office)\b")


@pytest.mark.parametrize("company", COMPANIES)
def test_recommendation_text_is_registry_only_and_regulator_free(company):
    from psm.templates import classify_action
    for r in load_company(ROOT / company)["recommendations"]:
        text = r["Recommendation Description"]
        assert not _BANNED.search(text), text
        classify_action(text)     # KeyError = text outside the registry
    # scope note: donor NARRATIVES legitimately mention MMS/BSEE (they are
    # disclosed real text); the regulator-voice lint applies to the
    # recommendation register only.


# ---- provenance + manifest consistency ----------------------------------

@pytest.mark.parametrize("company", COMPANIES)
def test_company_provenance_closed_set_all_four_tables(company):
    import csv as _csv
    for name, prov_file in (("incidents", "provenance.csv"),
                            ("causes", "causes_provenance.csv"),
                            ("recommendations", "recommendations_provenance.csv"),
                            ("closeout", "closeout_provenance.csv")):
        with (ROOT / company / prov_file).open(encoding="utf-8", newline="") as fh:
            for prow in _csv.DictReader(fh):
                assert set(prow.values()) <= {"", "src", "syn", "key"}, name


KPIS = {"median_report_lag", "skip_rate", "root_cause_depth",
        "median_closeout_days", "overdue_rate", "recurrence_rate",
        "admin_ppe_share", "owner_completeness", "hs_completeness"}


@pytest.mark.parametrize("company", COMPANIES)
def test_manifest_leaves_no_kpi_unasserted(company, manifests):
    m = manifests[company]
    covered = ({p["kpi"] for p in m["plants"]}
               | set(m["analytic_expectations"].get("kpi_map", {}))
               | {c.split("(")[0] for c in m["negative_controls"]})
    assert KPIS <= covered, KPIS - covered


# ---- planted vs measured: Coastal (bundle-level attribution) ------------
# Coastal's pathologies co-move by design; this suite claims bundle-level
# detection for Coastal, NOT per-pathology attribution (parked in the spec).

def test_coastal_skip_planted(kpis):
    kn, kc = kpis["northstar"], kpis["coastal"]
    assert kc["skip_rate"] > 5 * kn["skip_rate"]


def test_coastal_shallow_investigation_planted(kpis):
    assert kpis["coastal"]["root_cause_depth"] < 0.5 * kpis["northstar"]["root_cause_depth"]


def test_coastal_weak_controls_planted(kpis):
    assert kpis["coastal"]["admin_ppe_share"] > kpis["northstar"]["admin_ppe_share"] + 0.25


def test_coastal_missing_owners_planted(kpis):
    assert kpis["coastal"]["owner_completeness"] < kpis["northstar"]["owner_completeness"] - 0.25


def test_coastal_hs_decay_planted_and_baseline_adjusted(kpis, manifests):
    # ADJUDICATED correction (plan-text error, same class as the 3x->2x ruling):
    # the brief's "< baseline - 0.15" is unsatisfiable IN EXPECTATION -- the
    # coastal donor partition is already 49.33% HS-blank (74/150), and
    # extra_hs_blank_rate (0.25, scenarios/coastal.yaml) is OR-composed on top,
    # so max expected decay = 0.5067 * 0.25 = 12.7pt < 15pt. Claim reduced to
    # (a) consistency with the analytic expectation, (b) a meaningful decay
    # direction floor (absent the plant, decay is exactly 0 -- donors are fixed).
    baseline = 1 - manifests["coastal"]["analytic_expectations"]["hs_blank_baseline"]
    expected = baseline * (1 - 0.25)          # OR-semantics: survivors * (1-extra)
    measured = kpis["coastal"]["hs_completeness"]
    assert abs(measured - expected) <= tol(expected, 150, 0.05)
    assert measured < baseline - 0.05


def test_coastal_recurrence_planted(kpis):
    assert kpis["coastal"]["recurrence_rate"] >= 6


def test_coastal_negative_controls(kpis):
    kn, kc = kpis["northstar"], kpis["coastal"]
    assert abs(kc["median_report_lag"] - kn["median_report_lag"]) <= \
        max(1.0, 0.3 * kn["median_report_lag"])          # spec: within +/-30%
    # fast-on-paper: coastal closeout must NOT trip the decay direction
    assert kc["median_closeout_days"] < 2 * kn["median_closeout_days"]
