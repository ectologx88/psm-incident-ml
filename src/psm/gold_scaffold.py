"""Assemble the gold-labelling worksheet from a sampled manifest + extracted JSON.

Produces gold/gold_labels.csv: one row per sampled report, pre-filled with
src_ reference fields (including the raw field 18/19 text so a labeller does
not have to reopen the PDF for the common case) and blank gold_ columns for
a human to fill in by hand, per schema/e19_target.yaml's target section
(cause_category, psm_element, cause_status).

This module never writes a gold_ value itself - doing so would collapse the
gold_/llm_ distinction this project's whole provenance convention exists to
protect (see CLAUDE.md). src_cause_status is included for the labeller's
reference only; it is the automated parser's guess, not a substitute for the
human's own judgment call on gold_cause_status.

Run:  uv run python -m psm.gold_scaffold
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from psm.causes import classify_field
from psm.gold_sample import effective_year

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE_MANIFEST = REPO / "data" / "interim" / "gold_sample_manifest.csv"
DEFAULT_INTERIM = REPO / "data" / "interim"
DEFAULT_OUT = REPO / "gold" / "gold_labels.csv"

GOLD_COLUMNS = ["gold_cause_category", "gold_psm_element", "gold_cause_status", "gold_notes", "gold_labeler", "gold_label_date"]

REFERENCE_COLUMNS = [
    "report_id",
    "src_report_type",
    "effective_year",
    "src_operator",
    "src_area",
    "src_block",
    "src_date_text",
    "src_date_parsed",
    "src_url",
    "src_filename",
    "src_extract_status",
    "src_cause_status",
    "src_f18_probable_cause",
    "src_f19_contributing_cause",
]


def combine_cause_status(f18_text: str | None, f19_text: str | None) -> str:
    """Row-level status from the two per-field statuses classify_field() gives.

    typed wins if either field is typed (a labeller has real vocabulary to
    work from); freetext wins over absent/parse_failed for the same reason;
    absent_legitimate only when *both* fields are genuinely, legitimately
    blank; parse_failed is the fallback when nothing else applies.
    """
    s18 = classify_field(f18_text)
    s19 = classify_field(f19_text)
    statuses = {s18, s19}
    if "typed" in statuses:
        return "typed"
    if "freetext" in statuses:
        return "freetext"
    if statuses == {"absent_legitimate"}:
        return "absent_legitimate"
    return "parse_failed"


def build_row(manifest_row: dict, interim_dir: Path) -> dict:
    stem = Path(manifest_row.get("src_filename", "")).stem
    interim_path = interim_dir / f"{stem}.json"
    rec: dict = {}
    if interim_path.exists():
        rec = json.loads(interim_path.read_text(encoding="utf-8"))

    f18 = rec.get("src_f18_probable_cause")
    f19 = rec.get("src_f19_contributing_cause")
    extract_status = rec.get("src_extract_status", "not_extracted")
    cause_status = (
        combine_cause_status(f18, f19) if extract_status == "ok" else "parse_failed"
    )

    row = {
        "report_id": manifest_row.get("src_sha256") or rec.get("src_sha256", ""),
        "src_report_type": manifest_row.get("src_report_type", ""),
        "effective_year": effective_year(manifest_row),
        "src_operator": manifest_row.get("src_operator", ""),
        "src_area": manifest_row.get("src_area", ""),
        "src_block": manifest_row.get("src_block", ""),
        "src_date_text": manifest_row.get("src_date_text", ""),
        "src_date_parsed": manifest_row.get("src_date_parsed", ""),
        "src_url": manifest_row.get("src_url", ""),
        "src_filename": manifest_row.get("src_filename", ""),
        "src_extract_status": extract_status,
        "src_cause_status": cause_status,
        "src_f18_probable_cause": f18 or "",
        "src_f19_contributing_cause": f19 or "",
    }
    for col in GOLD_COLUMNS:
        row[col] = ""
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample-manifest", type=Path, default=DEFAULT_SAMPLE_MANIFEST)
    ap.add_argument("--interim", type=Path, default=DEFAULT_INTERIM)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    if not args.sample_manifest.exists():
        print(
            f"{args.sample_manifest} not found - run `python -m psm.gold_sample` first",
            file=sys.stderr,
        )
        return 1

    with open(args.sample_manifest, newline="", encoding="utf-8") as fh:
        manifest_rows = list(csv.DictReader(fh))

    rows = [build_row(r, args.interim) for r in manifest_rows]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=REFERENCE_COLUMNS + GOLD_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["src_cause_status"]] = counts.get(r["src_cause_status"], 0) + 1
    print(f"wrote {len(rows)} rows -> {args.out}")
    for status, n in sorted(counts.items()):
        print(f"  src_cause_status={status}: {n}")
    print("gold_* columns are blank by design - hand-label them, never auto-fill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
