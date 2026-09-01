# src/psm/scenario.py
"""Deterministic scenario-register engine: samples disjoint donor partitions
from the real BSEE corpus and generates complete 4-table E19 registers per
synthetic company, shaped by scenarios/<name>.yaml process-rate knobs.

Every draw: int(sha256(f"{key}|{SALT}")) walked in sorted-key order.
No random, no wall clock, no scipy (lognormals via psm.quantiles tables)."""
from __future__ import annotations

import csv
import hashlib
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import yaml

from psm.quantiles import draw_days

REPO = Path(__file__).resolve().parents[2]
REAL = REPO / "data" / "processed" / "e19" / "real_only"
SCENARIO_DIR = REPO / "scenarios"
OUT_ROOT = REPO / "data" / "companies"

SALT = "e19-scenario-v1"
PARTITION_SALT = "e19-scenario-partition-v1"

WINDOW_START = date(2021, 1, 1)
WINDOW_END = date(2025, 12, 31)
WINDOW_DAYS = (WINDOW_END - WINDOW_START).days + 1  # 1826 (2024 is a leap year)

COMPANY_ORDER = ["northstar", "meridian", "coastal"]
PREFIX = {"northstar": "NS", "meridian": "MR", "coastal": "CP",
          "meridian_nt": "MNT"}

# ONE shared distribution for all companies (company-specific weights were
# unfalsifiable -- spec decision). Integer weights sum to 100.
WORK_GROUP_WEIGHTS = [
    ("Production Operations", 30), ("Maintenance", 25), ("Drilling", 15),
    ("Well Services", 12), ("Construction", 10), ("Marine & Logistics", 8),
]

POSITIONS = ["Operations Superintendent", "HSE Advisor",
             "Maintenance Supervisor", "Facility Engineer",
             "Production Foreman", "Marine Coordinator"]


def _hash(key: str) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)


@lru_cache(maxsize=None)
def load_scenario(name: str) -> dict:
    cfg = yaml.safe_load((SCENARIO_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    required = {"report_lag", "investigation", "closeout", "agreed_offset",
                "recurrence", "controls_mix", "data_discipline"}
    missing = required - set(cfg)
    assert not missing, f"{name}: missing knob groups {missing}"
    return cfg


def scenario_sha256(name: str) -> str:
    return hashlib.sha256(
        (SCENARIO_DIR / f"{name}.yaml").read_bytes()).hexdigest()


@lru_cache(maxsize=None)
def donor_ids() -> tuple[str, ...]:
    with (REAL / "incidents.csv").open(encoding="utf-8", newline="") as fh:
        return tuple(r["Incident Number"] for r in csv.DictReader(fh))


def donor_partition(company: str) -> list[str]:
    """Hash-ranked disjoint 150-slices in fixed COMPANY_ORDER. The test-only
    meridian_nt variant reuses northstar's slice."""
    base = "northstar" if company == "meridian_nt" else company
    ranked = sorted(sorted(donor_ids()),
                    key=lambda i: _hash(f"{i}|{PARTITION_SALT}"))
    k = COMPANY_ORDER.index(base)
    return ranked[k * 150:(k + 1) * 150]


def scenario_incident_number(company: str, donor_id: str,
                             clone_index: int = 0) -> str:
    """Fresh mint per row -- donor ids embed real dates and must not leak.
    Provenance token: key."""
    h = hashlib.sha256(
        f"{company}|{donor_id}|{clone_index}|{SALT}".encode("utf-8")
    ).hexdigest()[:10].upper()
    return f"{PREFIX[company]}-{h}"


def base_incident_date(company: str, sid: str) -> date:
    return WINDOW_START + timedelta(
        days=_hash(f"{company}|{sid}|incident_date|{SALT}") % WINDOW_DAYS)


def pick_weighted(key: str, pairs: list[tuple[str, int]]) -> str:
    total = sum(w for _, w in pairs)
    r = _hash(key) % total
    for value, w in pairs:
        if r < w:
            return value
        r -= w
    raise AssertionError("unreachable")


def rate_hit(key: str, rate: float) -> bool:
    """Deterministic Bernoulli: exact to 1e-6 resolution."""
    return _hash(key) % 1_000_000 < round(rate * 1_000_000)


def syn_person(key: str) -> tuple[str, str]:
    name = f"SYN-{hashlib.sha256((key + '|' + SALT).encode()).hexdigest()[:6]}"
    return name, POSITIONS[_hash(f"{key}|position|{SALT}") % len(POSITIONS)]


# ---- prose-date shifting (format-preserving; 571/1213 donor narratives
# ---- embed dates that must move with the structured rebase) -------------

_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")
_MON3 = tuple(m[:3].upper() for m in _MONTHS)
_MONTH_ALT = "|".join(_MONTHS)


def _month_out(idx: int, like: str) -> str:
    name = _MONTHS[idx]
    return name.upper() if like.isupper() else name


def _p(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


_DATE_PATTERNS = [
    # May 2, 2024
    (_p(rf"\b({_MONTH_ALT}) (\d{{1,2}}), (\d{{4}})\b"),
     lambda m: (int(m.group(3)),
                [x.lower() for x in _MONTHS].index(m.group(1).lower()) + 1,
                int(m.group(2))),
     lambda d, m: f"{_month_out(d.month - 1, m.group(1))} {d.day}, {d.year}"),
    # 2 May 2024
    (_p(rf"\b(\d{{1,2}}) ({_MONTH_ALT}) (\d{{4}})\b"),
     lambda m: (int(m.group(3)),
                [x.lower() for x in _MONTHS].index(m.group(2).lower()) + 1,
                int(m.group(1))),
     lambda d, m: f"{d.day} {_month_out(d.month - 1, m.group(2))} {d.year}"),
    # 17-OCT-2020
    (_p(rf"\b(\d{{1,2}})-({'|'.join(_MON3)})-(\d{{4}})\b"),
     lambda m: (int(m.group(3)),
                [x.lower() for x in _MON3].index(m.group(2).lower()) + 1,
                int(m.group(1))),
     lambda d, m: f"{d.day:02d}-{_MON3[d.month - 1]}-{d.year}"),
    # 05/02/2024 (US month/day/year)
    (_p(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
     lambda m: (int(m.group(3)), int(m.group(1)), int(m.group(2))),
     lambda d, m: f"{d.month}/{d.day}/{d.year}"),
    # 2024-05-02
    (_p(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
     lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3))),
     lambda d, m: f"{d.year}-{d.month:02d}-{d.day:02d}"),
]


def shift_prose_dates(text: str, delta_days: int) -> str:
    for pat, extract, fmt in _DATE_PATTERNS:
        def repl(m, extract=extract, fmt=fmt):
            try:
                y, mo, dy = extract(m)
                d = date(y, mo, dy) + timedelta(days=delta_days)
            except ValueError:      # 13/45/2020 etc: not a date, leave it
                return m.group(0)
            return fmt(d, m)
        text = pat.sub(repl, text)
    return text


def find_prose_dates(text: str) -> list[date]:
    out = []
    for pat, extract, _ in _DATE_PATTERNS:
        for m in pat.finditer(text):
            try:
                y, mo, dy = extract(m)
                out.append(date(y, mo, dy))
            except ValueError:
                pass
    return out
