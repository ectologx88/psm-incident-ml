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


from dataclasses import dataclass, field


@dataclass
class IncidentPlan:
    """Every decision for one synthetic incident, drawn deterministically
    BEFORE any table row is built, so recurrence planting (Task 9) can move
    the anchor date without re-drawing anything."""
    company: str
    sid: str
    donor_id: str
    skipped: bool
    work_group: str
    doi: date                       # anchor; recurrence planting may move it
    report_lag: int
    invest_days: int
    reaches_root: bool
    chain_len: int                  # 0 if skipped, else 1..3 (3 iff reaches_root)
    n_recs: int                     # 0 if skipped
    rec_tags: list[str]
    agreed_offsets: list[int]       # per rec, days from Date of Report
    completion_offsets: list[int]   # per rec, days from Date of Report
    owner_assigned: list[bool]
    hs_blanked: bool
    element_override: str | None = None   # set only by recurrence planting

    @property
    def report_date(self) -> date:
        return self.doi + timedelta(days=self.report_lag)

    @property
    def approval_date(self) -> date | None:
        return None if self.skipped else self.report_date + timedelta(days=self.invest_days)

    def agreed_dates(self) -> list[date]:
        return [self.report_date + timedelta(days=o) for o in self.agreed_offsets]

    def completed_dates(self) -> list[date]:
        return [self.report_date + timedelta(days=o) for o in self.completion_offsets]

    @property
    def close_out_date(self) -> date | None:
        done = self.completed_dates()
        return max(done) if done else None

    @property
    def completion_span(self) -> int:
        """Days from Date of Incident to the last Date Completed."""
        return self.report_lag + (max(self.completion_offsets)
                                  if self.completion_offsets else 0)


def make_plan(company: str, cfg: dict, donor_id: str) -> IncidentPlan:
    sid = scenario_incident_number(company, donor_id)
    inv, clo, dd = cfg["investigation"], cfg["closeout"], cfg["data_discipline"]
    skipped = rate_hit(f"{company}|{sid}|skip|{SALT}", inv["skip_rate"])
    reaches_root = (not skipped) and rate_hit(
        f"{company}|{sid}|root|{SALT}", inv["root_cause_prob"])
    chain_len = 0 if skipped else (
        3 if reaches_root else 1 + _hash(f"{company}|{sid}|chain|{SALT}") % 2)
    n_recs = 0 if skipped else (
        1 + (1 if _hash(f"{company}|{sid}|nrec|{SALT}") % 10 < 2 else 0))  # mean 1.2
    mix = [(tag, round(cfg["controls_mix"][tag] * 100))
           for tag in ("elimination", "engineering", "admin", "ppe")]
    amin, amax = cfg["agreed_offset"]["min_days"], cfg["agreed_offset"]["max_days"]
    return IncidentPlan(
        company=company, sid=sid, donor_id=donor_id, skipped=skipped,
        work_group=pick_weighted(f"{company}|{sid}|work_group|{SALT}",
                                 WORK_GROUP_WEIGHTS),
        doi=anchored_incident_date(company, sid, donor_id),
        report_lag=draw_days(f"{company}|{sid}|report_lag|{SALT}",
                             cfg["report_lag"]["median_days"],
                             cfg["report_lag"]["sigma"]),
        invest_days=draw_days(f"{company}|{sid}|invest_duration|{SALT}",
                              inv["duration_median_days"], inv["duration_sigma"]),
        reaches_root=reaches_root, chain_len=chain_len, n_recs=n_recs,
        rec_tags=[pick_weighted(f"{company}|{sid}|tag|{i}|{SALT}", mix)
                  for i in range(n_recs)],
        agreed_offsets=[amin + _hash(f"{company}|{sid}|agreed|{i}|{SALT}")
                        % (amax - amin + 1) for i in range(n_recs)],
        completion_offsets=[draw_days(f"{company}|{sid}|closeout|{i}|{SALT}",
                                      clo["median_days"], clo["sigma"])
                            for i in range(n_recs)],
        owner_assigned=[rate_hit(f"{company}|{sid}|owner|{i}|{SALT}",
                                 dd["owner_assigned_rate"])
                        for i in range(n_recs)],
        hs_blanked=rate_hit(f"{company}|{sid}|hsblank|{SALT}",
                            dd["extra_hs_blank_rate"]),
    )


@lru_cache(maxsize=None)
def _real_table(name: str) -> tuple[tuple[str, ...], tuple[dict, ...]]:
    with (REAL / name).open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return tuple(reader.fieldnames or ()), tuple(reader)


def incident_fieldnames() -> list[str]:
    return list(_real_table("incidents.csv")[0])


@lru_cache(maxsize=None)
def donor_incidents() -> dict[str, dict]:
    return {r["Incident Number"]: r for r in _real_table("incidents.csv")[1]}


def donor_delta(plan: IncidentPlan) -> int:
    """Days the donor's structured date moved; prose dates move by the same
    delta so narrative and register never disagree."""
    raw = donor_incidents().get(plan.donor_id, {}).get("Date of Incident", "")
    try:
        return (plan.doi - date.fromisoformat(raw)).days
    except ValueError:
        return 0


# columns copied from the donor with prose-date shifting applied
_FREE_TEXT = ("incident Title", "Detail", "Description", "What happened?  ",
              "What was the outcome?",
              "What was the worst outcome that could reasonably be expected to have happened?",
              "How did the incident occur")
# columns copied verbatim from the donor
_VERBATIM = ("Incident Classificatioin", "Site", "Area", "Unit",
             "Incident Type A", "Incident Type B", "Incident Type C",
             "Incident Type D", "Incident Classification",
             "Health & Safety Incident - Classification",
             "Health & Safety - Risk Score", "Health & Safety  - Consequence",
             "Health & Safety - Likelihood",
             "Environment & Reputation - Incident Classification",
             "Environment & Reputation - Risk Score",
             "Environment & Reputation  - Consequence",
             "Environment & Reputation - Likelihood",
             "Financial Cost & Business - Incident Classification",
             "Financial Cost & Business Interruption - Risk Score",
             "Financial Cost & Business Interruption  - Consequence",
             "Financial Cost & Business Interruption - Likelihood")
_HS_TRIO = ("Health & Safety - Risk Score", "Health & Safety  - Consequence",
            "Health & Safety - Likelihood")
# (name column, position column, role key, gate) -- gate: when populated
_PEOPLE = (
    ("Investigation leader - Name", "Investigation leader - Position",
     "leader", "investigated"),
    ("Incident Classified by - Name", "Incident Classified by - Position",
     "classifier", "always"),
    ("Investigation Acceptor/Approver (Owner) - Name",
     "Investigation Acceptor/Approver (Owner)- Position",   # sic: no space
     "approver", "investigated"),
    ("Close out Approval - Name", "Close out Approval - Position",
     "closer", "closed"),
)


_NEAR_LOOKBACK = 365   # days before the incident a narrative may reference
_NEAR_FORWARD = 90     # days after


def _narrative_span(donor_id: str) -> tuple[int, int]:
    """(lookback, forward) days spanned by NEAR-INCIDENT prose dates in the
    donor's free-text fields, capped at the allowances. Dates further out
    are historical or OCR-garbage references (the real corpus carries
    offsets up to ~1000 years, e.g. '29-JUN-0202') and are exempt from the
    window invariant: era-plausible or already-dirty either way -- 'source
    data is dirty and stays dirty' is standing repo policy."""
    row = donor_incidents().get(donor_id, {})
    try:
        doi = date.fromisoformat(row.get("Date of Incident", ""))
    except ValueError:
        return 0, 0
    look = fwd = 0
    for c in _FREE_TEXT:
        for pd in find_prose_dates(row.get(c) or ""):
            off = (doi - pd).days
            if 0 <= off <= _NEAR_LOOKBACK:
                look = max(look, off)
            elif -_NEAR_FORWARD <= off < 0:
                fwd = max(fwd, -off)
    return look, fwd


def anchored_incident_date(company: str, sid: str, donor_id: str) -> date:
    """Hash placement clamped so every near-incident prose date still lands
    inside the window after the uniform shift (Task 12 enforces this)."""
    look, fwd = _narrative_span(donor_id)
    span = WINDOW_DAYS - look - fwd
    off = _hash(f"{company}|{sid}|incident_date|{SALT}") % span
    return WINDOW_START + timedelta(days=look + off)


def build_incident_row(plan: IncidentPlan, donor_row: dict) -> tuple[dict, dict]:
    delta = donor_delta(plan)
    row: dict[str, str] = {c: "" for c in incident_fieldnames()}
    prov: dict[str, str] = dict(row)

    def put(col, value, token):
        row[col] = value
        prov[col] = token if value.strip() else ""

    put("Incident Number", plan.sid, "key")
    put("Date of Incident", plan.doi.isoformat(), "syn")
    put("Date of Report", plan.report_date.isoformat(), "syn")
    put("Work Group", plan.work_group, "syn")
    donor_time = (donor_row.get("Time of Incident") or "").strip()
    if donor_time:
        put("Time of Incident", donor_time, "src")
    else:
        h = _hash(f"{plan.company}|{plan.sid}|time|{SALT}")
        put("Time of Incident", f"{h % 24:02d}:{(h // 24) % 12 * 5:02d}", "syn")
    for c in _FREE_TEXT:
        text = (donor_row.get(c) or "")
        put(c, shift_prose_dates(text, delta) if text.strip() else "", "src")
    for c in _VERBATIM:
        put(c, (donor_row.get(c) or ""), "src")
    if plan.hs_blanked:
        for c in _HS_TRIO:
            put(c, "", "")
    if plan.approval_date:
        put("Approval Date", plan.approval_date.isoformat(), "syn")
    if plan.close_out_date:
        put("Close out Date", plan.close_out_date.isoformat(), "syn")
    for name_col, pos_col, role, gate in _PEOPLE:
        populate = (gate == "always"
                    or (gate == "investigated" and not plan.skipped)
                    or (gate == "closed" and plan.close_out_date is not None))
        if populate:
            name, pos = syn_person(f"{plan.company}|{plan.sid}|{role}")
            put(name_col, name, "syn")
            put(pos_col, pos, "syn")
    return row, prov
