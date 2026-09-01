# src/psm/kpi.py
"""Nine deterministic KPIs over a company register (in-memory tables or a
data/companies/<co> directory). No thresholds live here -- the manifest and
tests/test_scenarios.py own every assertion."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from statistics import median

from psm.scenario import detect_recurrence_pairs
from psm.templates import classify_action

_TABLES = ("incidents", "causes", "recommendations", "closeout")


def load_company(path: Path) -> dict[str, list[dict]]:
    out = {}
    for name in _TABLES:
        with (path / f"{name}.csv").open(encoding="utf-8", newline="") as fh:
            out[name] = list(csv.DictReader(fh))
    return out


def _d(value: str) -> date | None:
    value = (value or "").strip()
    return date.fromisoformat(value) if value else None


def compute_kpis(tables: dict[str, list[dict]],
                 window_days: int = 365) -> dict[str, float | int]:
    incs, causes = tables["incidents"], tables["causes"]
    recs, close = tables["recommendations"], tables["closeout"]

    causes_by: dict[str, list[dict]] = {}
    for c in causes:
        causes_by.setdefault(c["Incident Number"], []).append(c)
    report_by = {r["Incident Number"]: _d(r["Date of Report"]) for r in incs}
    agreed_by = {(r["Incident Number"], r["Recommendation Number"]):
                 _d(r["Agreed Completion Date"]) for r in recs}

    lags = [( _d(r["Date of Report"]) - _d(r["Date of Incident"])).days
            for r in incs
            if _d(r["Date of Report"]) and _d(r["Date of Incident"])]

    skipped = [r for r in incs
               if not r["Investigation leader - Name"].strip()
               and not causes_by.get(r["Incident Number"])]
    investigated = [r for r in incs if r["Investigation leader - Name"].strip()]
    rooted = sum(1 for r in investigated
                 if any(c["Cause type"] == "Root"
                        for c in causes_by.get(r["Incident Number"], [])))

    closeout_days, overdue = [], 0
    for c in close:
        done = _d(c["Date Completed"])
        rep = report_by.get(c["Incident Number"])
        if done and rep:
            closeout_days.append((done - rep).days)
        agreed = agreed_by.get((c["Incident Number"], c["Recommendation Number"]))
        if done and agreed and done > agreed:
            overdue += 1

    tags = [classify_action(r["Recommendation Description"]) for r in recs]

    return {
        "median_report_lag": float(median(lags)) if lags else 0.0,
        "skip_rate": len(skipped) / len(incs) if incs else 0.0,
        "root_cause_depth": rooted / len(investigated) if investigated else 0.0,
        "median_closeout_days": (float(median(closeout_days))
                                 if closeout_days else 0.0),
        "overdue_rate": overdue / len(close) if close else 0.0,
        "recurrence_rate": len(detect_recurrence_pairs(incs, causes,
                                                       window_days)),
        "admin_ppe_share": (sum(1 for t in tags if t in ("admin", "ppe"))
                            / len(tags) if tags else 0.0),
        "owner_completeness": (sum(1 for r in recs
                                   if r["Responsible Owner - Name"].strip())
                               / len(recs) if recs else 0.0),
        "hs_completeness": (sum(1 for r in incs
                                if r["Health & Safety - Risk Score"].strip())
                            / len(incs) if incs else 0.0),
    }
