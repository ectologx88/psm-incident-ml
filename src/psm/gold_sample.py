"""Select a deterministic, year-stratified sample of reports for hand-labelling.

Resolves the coverage fork documented in docs/findings.md (2026-08-09 entry):
gold-labelling was never actually blocked by solving free-text extraction for
the untyped ~68% majority. A human labeller reads the source PDF directly and
assigns gold_ fields regardless of whether field 18/19 happened to use the
controlled vocabulary — src_cause_status is recorded for reference, not as a
gate. So the sample below spans the full 2003-2026 corpus, typed and
free-text eras alike, not just the ~32% that auto-parses cleanly.

Only src_report_type == "district" rows are eligible: panel reports are a
structurally different, unverified document type (see docs/findings.md,
"What is not yet verified" - panel-report joinability to the spine has not
been measured), and this project's extraction pipeline (schema/
bsee_form2010.yaml, src/psm/layout.py, src/psm/extract.py) targets MMS Form
2010 specifically. Panel-report sampling is out of scope here, not silently
dropped - flagged explicitly so it isn't mistaken for an oversight.

No hidden randomness: selection within each year is by ascending
sha256(src_url), the same "deterministic, no stored seed" pattern
src/psm/synth.py uses for its hash offsets. Sorting by URL hash rather than
by e.g. filename avoids any correlation with operator name, district, or
alphabetical clustering.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "data" / "manifest.csv"
DEFAULT_TARGET_N = 100
DEFAULT_MIN_PER_YEAR = 1


def effective_year(row: dict) -> str:
    """The best available year for a row - see docs/findings.md's warning that
    filenames alone are unreliable (MMS Form 2010's own '2010' leaks into
    filenames as a form-number token, not a year)."""
    return row.get("src_year") or row.get("src_index_year") or "unknown"


def _sort_key(row: dict) -> str:
    return hashlib.sha256((row.get("src_url") or "").encode()).hexdigest()


def stratified_sample(
    rows: list[dict],
    target_n: int = DEFAULT_TARGET_N,
    min_per_year: int = DEFAULT_MIN_PER_YEAR,
) -> list[dict]:
    """Pick target_n district rows spread across every year present.

    Base allocation is target_n // n_years per year, floored at min_per_year
    and capped by that year's availability. Any remainder (from integer
    division, or from years too small to absorb their base share) is handed
    out one at a time to the years with the most unused rows, largest first -
    deterministic, not first-come-first-served on iteration order.
    """
    eligible = [r for r in rows if r.get("src_report_type") == "district"]
    by_year: dict[str, list[dict]] = defaultdict(list)
    for r in eligible:
        by_year[effective_year(r)].append(r)

    years = sorted(y for y in by_year if y != "unknown")
    if not years:
        return []
    for y in years:
        by_year[y].sort(key=_sort_key)

    n_years = len(years)
    base = max(min_per_year, target_n // n_years)
    alloc = {y: min(base, len(by_year[y])) for y in years}

    remaining = target_n - sum(alloc.values())
    while remaining > 0:
        candidates = [y for y in years if len(by_year[y]) > alloc[y]]
        if not candidates:
            break
        candidates.sort(key=lambda y: len(by_year[y]) - alloc[y], reverse=True)
        for y in candidates:
            if remaining <= 0:
                break
            alloc[y] += 1
            remaining -= 1

    sample: list[dict] = []
    for y in years:
        sample.extend(by_year[y][: alloc[y]])
    return sample


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--target-n", type=int, default=DEFAULT_TARGET_N)
    ap.add_argument("--min-per-year", type=int, default=DEFAULT_MIN_PER_YEAR)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    with open(args.manifest, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print(f"{args.manifest} is empty", file=sys.stderr)
        return 1

    sample = stratified_sample(rows, args.target_n, args.min_per_year)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(sample)

    by_year: dict[str, int] = defaultdict(int)
    for r in sample:
        by_year[effective_year(r)] += 1
    print(f"selected {len(sample)} of {len(rows)} rows -> {args.out}")
    for y in sorted(by_year):
        print(f"  {y}: {by_year[y]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
