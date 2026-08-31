"""Assemble the gold-labelling worksheet from a sampled statement list.

Produces gold/gold_labels.csv: one row per sampled cause statement (Incident
Number + Cause number - see psm.gold_sample's module docstring for why
statement grain, not report grain, and why this reads `data/processed/e19/
enriched/causes.csv` rather than `data/manifest.csv`), pre-filled with `src_`
reference fields and blank `gold_` columns for a human to fill in by hand, per
schema/e19_target.yaml's target section (cause_category, psm_element,
cause_status).

This module never writes a `gold_` value itself - doing so would collapse the
gold_/llm_ distinction this project's whole provenance convention exists to
protect (see CLAUDE.md). It also never surfaces `xw_element` or
`llm_cause_category` on the worksheet: either would anchor the human labeller
on a machine guess, which is exactly what an independent gold label is for.
psm.gold_sample uses both signals internally to build its strata; this module
reads only the (incident, cause) keys that sampling selected.

Run:  uv run python -m psm.gold_scaffold
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from psm.gold_sample import CAUSES, DEFAULT_SAMPLE_OUT, INCIDENTS, incident_year
from psm.ledger import regime_for

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "gold" / "gold_labels.csv"

GOLD_COLUMNS = [
    "gold_cause_category",
    "gold_psm_element",
    "gold_cause_status",
    "gold_notes",
    "gold_labeler",
    "gold_label_date",
]

REFERENCE_COLUMNS = [
    "report_id",
    "incident",
    "cause",
    "effective_year",
    "era_regime",
    "src_site",
    "src_area",
    "src_incident_classification",
    "src_cause_description",
]

csv.field_size_limit(10**9)


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def build_rows(
    sample_keys: list[tuple[str, str]], causes_path: Path, incidents_path: Path
) -> list[dict]:
    causes_by_key = {
        (r["Incident Number"], r["Cause number"]): r for r in _read_csv(causes_path)
    }
    incidents = _read_csv(incidents_path)
    incidents_by_id = {r["Incident Number"]: r for r in incidents}
    year_by_inc = incident_year(incidents)

    rows = []
    for incident, cause in sample_keys:
        c = causes_by_key.get((incident, cause), {})
        inc = incidents_by_id.get(incident, {})
        year = year_by_inc.get(incident)
        row = {
            "report_id": f"{incident}-{cause}",
            "incident": incident,
            "cause": cause,
            "effective_year": year if year is not None else "",
            "era_regime": regime_for(year) or "undated",
            "src_site": inc.get("Site", ""),
            "src_area": inc.get("Area", ""),
            "src_incident_classification": inc.get("Incident Classificatioin", ""),
            "src_cause_description": " ".join((c.get("Cause Description") or "").split()),
        }
        for col in GOLD_COLUMNS:
            row[col] = ""
        rows.append(row)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE_OUT)
    ap.add_argument("--causes", type=Path, default=CAUSES)
    ap.add_argument("--incidents", type=Path, default=INCIDENTS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    if not args.sample.exists():
        print(
            f"{args.sample} not found - run `python -m psm.gold_sample` first",
            file=sys.stderr,
        )
        return 1

    sample_rows = _read_csv(args.sample)
    keys = [(r["incident"], r["cause"]) for r in sample_rows]
    rows = build_rows(keys, args.causes, args.incidents)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=REFERENCE_COLUMNS + GOLD_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    print(f"wrote {len(rows)} rows -> {args.out}")
    print("gold_* columns are blank by design - hand-label them, never auto-fill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
