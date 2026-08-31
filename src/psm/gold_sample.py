"""Select a deterministic, category-and-era-stratified sample of cause
statements for hand-labelling.

Supersedes the report-level, `data/manifest.csv`-keyed sampler this module
used to contain. docs/findings.md's R5 (2026-08-29) measured why that design
could never be scored: gold keyed on `report_id` = sha256 of the source PDF,
every other table keys on `Incident Number` from the E19 workbook, and the
direct join was 0 of 100. Sampling from `data/processed/e19/enriched/
causes.csv` instead - the same table `psm.llm_label` and `psm.crosswalk`
already key on - makes the join exist by construction.

R5 also measured two more problems this design fixes:
  - year-uniform stratification gave 2003 (3 reports) and 2007 (97 reports)
    equal weight, so any accuracy would be an undisclosed year-balanced
    macro-average.
  - n=100 against `gold_psm_element`'s 20 classes is ~5 rows/class - out by a
    factor of ten for a per-element estimate.

This sampler stratifies on two axes instead of one:
  1. cause category (`schema/crosswalk.yaml`'s six categories), floored so
     every category gets enough rows for its own agreement estimate, not just
     whichever the corpus happens to be full of.
  2. era regime (`psm.ledger.ERA_REGIMES`), filling the remaining budget so
     the pre-2019 majority (crosswalk-typed statements are 87% modern_six -
     see the 2026-08-30 findings.md entry) isn't crowded out.

Grain is one row per (Incident Number, Cause number) - a statement, matching
`psm.llm_label.statements()` exactly, not a report. 90.5% of incidents carry
more than one cause statement and internally conflicting elements are common
(2026-08-30 findings.md entry), so a report-level gold label could not
represent what a report-level `llm_` label already can't.

No hidden randomness: selection within each stratum is by ascending
sha256(incident|cause), the same "deterministic, no stored seed" pattern
src/psm/synth.py uses for its hash offsets and the original report-level
sampler used for sha256(src_url).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from psm.ledger import regime_for

REPO = Path(__file__).resolve().parents[2]
E19 = REPO / "data" / "processed" / "e19"
CAUSES = E19 / "enriched" / "causes.csv"
INCIDENTS = E19 / "enriched" / "incidents.csv"
LLM_CAUSES = E19 / "llm_causes.csv"
CROSSWALK = REPO / "schema" / "crosswalk.yaml"

DEFAULT_SAMPLE_OUT = REPO / "data" / "interim" / "gold_sample.csv"
DEFAULT_TARGET_N = 360
DEFAULT_CATEGORY_FLOOR = 30
DEFAULT_MIN_PER_ERA = 1

csv.field_size_limit(10**9)


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def category_by_element(path: Path | None = None) -> dict[str, str]:
    """element number (as string) -> BSEE cause category name.

    Inverts schema/crosswalk.yaml's primary_element rather than hardcoding the
    mapping a second time - CLAUDE.md: "never bury a mapping in a Python
    dict." If crosswalk.yaml is re-based again (as it was 2026-08-29, v1->v2),
    this follows without a code change.
    """
    path = path or CROSSWALK
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {str(v["primary_element"]): name for name, v in spec["categories"].items()}


def incident_year(incidents: list[dict]) -> dict[str, int | None]:
    """Incident Number -> year. Same parse psm.ledger.real_only() uses for its
    era split, reused rather than re-derived so the two never drift apart."""
    out: dict[str, int | None] = {}
    for r in incidents:
        d = (r.get("Date of Incident") or "").strip()
        out[r["Incident Number"]] = int(d[:4]) if len(d) >= 4 and d[:4].isdigit() else None
    return out


def load_statements(
    causes_path: Path = CAUSES,
    incidents_path: Path = INCIDENTS,
    llm_causes_path: Path = LLM_CAUSES,
) -> list[dict]:
    """One record per cause statement: incident, cause, text, category, era.

    `category` prefers the crosswalk's xw_element-derived category (524/3,572
    statements, high precision) and falls back to `llm_cause_category` only
    when present and not an abstention - this is a sampling aid used to build
    strata, never written to the worksheet, so a wrong llm_ guess here costs
    at most an uneven stratum, not a mislabelled gold row.
    """
    causes = _read_csv(causes_path)
    if not causes:
        return []
    ecol = next(c for c in causes[0] if "Failed PSM" in c)
    cat_by_element = category_by_element()
    year_by_inc = incident_year(_read_csv(incidents_path))

    llm_category: dict[tuple[str, str], str] = {}
    if llm_causes_path.exists():
        for r in _read_csv(llm_causes_path):
            cat = (r.get("llm_cause_category") or "").strip()
            if cat and cat not in ("INSUFFICIENT", "none of these"):
                llm_category[(r.get("incident", ""), r.get("cause", ""))] = cat

    out = []
    for r in causes:
        incident, cause = r["Incident Number"], r["Cause number"]
        xw = (r[ecol] or "").strip()
        xw_category = cat_by_element.get(xw, "")
        source = "xw" if xw_category else ""
        category = xw_category
        if not category:
            llm_cat = llm_category.get((incident, cause), "")
            if llm_cat:
                category, source = llm_cat, "llm"
        year = year_by_inc.get(incident)
        out.append({
            "incident": incident,
            "cause": cause,
            "text": " ".join((r["Cause Description"] or "").split()),
            "category": category,
            "category_source": source,
            "era": regime_for(year) or "undated",
        })
    return out


def _sort_key(s: dict) -> str:
    return hashlib.sha256(f"{s['incident']}|{s['cause']}".encode()).hexdigest()


def _era_stratify(pool: list[dict], budget: int, min_per_era: int) -> list[dict]:
    """Same allocator shape as the original report-level sampler: base share
    per era, floored and capped, remainder to the eras with the most unused
    rows - just keyed on era regime instead of year."""
    by_era: dict[str, list[dict]] = defaultdict(list)
    for s in pool:
        by_era[s["era"]].append(s)
    eras = sorted(e for e in by_era if e != "undated")
    if not eras or budget <= 0:
        return []
    for e in eras:
        by_era[e].sort(key=_sort_key)

    n_eras = len(eras)
    base = max(min_per_era, budget // n_eras)
    alloc = {e: min(base, len(by_era[e])) for e in eras}
    remaining = budget - sum(alloc.values())
    while remaining > 0:
        candidates = [e for e in eras if len(by_era[e]) > alloc[e]]
        if not candidates:
            break
        candidates.sort(key=lambda e: len(by_era[e]) - alloc[e], reverse=True)
        for e in candidates:
            if remaining <= 0:
                break
            alloc[e] += 1
            remaining -= 1

    selected = []
    for e in eras:
        selected.extend(by_era[e][: alloc[e]])
    return selected


def stratified_statement_sample(
    statements: list[dict],
    target_n: int = DEFAULT_TARGET_N,
    category_floor: int = DEFAULT_CATEGORY_FLOOR,
    min_per_era: int = DEFAULT_MIN_PER_ERA,
) -> list[dict]:
    """Two-pass allocation.

    Pass 1 (category floor): up to `category_floor` statements per known
    cause category, so every category gets enough rows for its own agreement
    estimate even though the crosswalk-typed portion is 87% modern_six.

    Pass 2 (era fill): remaining budget spread across era regimes from
    whatever's left (any category, including unknown/freetext), so the
    pre-2019 majority the category pass under-represents still gets covered.

    Deterministic and order-independent: both passes sort candidates by
    sha256(incident|cause).
    """
    by_category: dict[str, list[dict]] = defaultdict(list)
    for s in statements:
        if s["category"]:
            by_category[s["category"]].append(s)
    for group in by_category.values():
        group.sort(key=_sort_key)

    selected: list[dict] = []
    selected_keys: set[tuple[str, str]] = set()
    for cat in sorted(by_category):
        for s in by_category[cat][:category_floor]:
            selected.append(s)
            selected_keys.add((s["incident"], s["cause"]))

    remaining_n = max(0, target_n - len(selected))
    pool = [s for s in statements if (s["incident"], s["cause"]) not in selected_keys]
    selected.extend(_era_stratify(pool, remaining_n, min_per_era))
    return selected


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--causes", type=Path, default=CAUSES)
    ap.add_argument("--incidents", type=Path, default=INCIDENTS)
    ap.add_argument("--llm-causes", type=Path, default=LLM_CAUSES)
    ap.add_argument("--target-n", type=int, default=DEFAULT_TARGET_N)
    ap.add_argument("--category-floor", type=int, default=DEFAULT_CATEGORY_FLOOR)
    ap.add_argument("--min-per-era", type=int, default=DEFAULT_MIN_PER_ERA)
    ap.add_argument("--out", type=Path, default=DEFAULT_SAMPLE_OUT)
    args = ap.parse_args(argv)

    if not args.causes.exists():
        print(f"{args.causes} not found", file=sys.stderr)
        return 1

    statements = load_statements(args.causes, args.incidents, args.llm_causes)
    sample = stratified_statement_sample(
        statements, args.target_n, args.category_floor, args.min_per_era
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    cols = ["incident", "cause", "text", "category", "category_source", "era"]
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sample)

    by_cat: dict[str, int] = defaultdict(int)
    by_era: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    for s in sample:
        by_cat[s["category"] or "(none)"] += 1
        by_era[s["era"]] += 1
        by_source[s["category_source"] or "(none)"] += 1

    print(f"selected {len(sample)} of {len(statements)} statements -> {args.out}")
    print("by category:")
    for c in sorted(by_cat):
        print(f"  {c}: {by_cat[c]}")
    print("by era:")
    for e in sorted(by_era):
        print(f"  {e}: {by_era[e]}")
    print("category signal source:")
    for src in sorted(by_source):
        print(f"  {src}: {by_source[src]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
