"""Export the filled/ E19 layer to one xlsx for SME review.

Three sheets: About (what this is and is not), Incidents, Causes. Every cell
whose provenance token is xw/llm/syn carries a fill colour so a reviewer can
see at a glance which values are real, mapped, model-assigned, or synthetic
(legend on the About sheet). The workbook is a DELIVERABLE, not a dataset of
record — deliverables/ is gitignored; the committed record is
data/processed/e19/filled/*.csv plus the parallel provenance files.

Run:  uv run python -m psm.export_e19
"""
from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font, PatternFill

from psm.fill import FILLED

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "deliverables" / "e19_filled.xlsx"

# aRGB without the alpha byte; openpyxl reports "00"+this on round-trip.
PROVENANCE_FILLS = {"xw": "DDEBF7", "llm": "FFF2CC", "syn": "EDEDED"}

ABOUT_LINES = [
    "E19 Investigation Register - filled demonstration copy",
    "",
    "Built from public US BSEE offshore incident reports, projected into the",
    "Energy Institute PSM Framework Element 19 register shape. This is not a real",
    "filled E19 worksheet: it demonstrates what an auto-populated register looks",
    "like. Cell colours state where every value came from:",
    "",
    "  no colour  - verbatim from a BSEE source document",
    "  blue       - deterministic crosswalk from a BSEE category (an opinion,",
    "               recorded in schema/crosswalk.yaml)",
    "  amber      - assigned by a language model (3-pass self-consistency,",
    "               Claude Haiku 4.5) - never treated as ground truth",
    "  grey       - synthetic: deterministic hash-generated filler for fields",
    "               BSEE does not publish (names are SYN- tokens, dates are",
    "               offsets, picklist values are invented). Corresponds to",
    "               nothing real.",
    "",
    "Model-assigned labels are unvalidated: agreement with the crosswalk is",
    "25.4% on the 524 statements where both exist, and the corpus skews heavily",
    "to one category. Treat every amber/grey cell as a proposal to evaluate,",
    "not a finding. Full provenance: data/processed/e19/filled/ in the",
    "psm-incident-ml repository.",
]


def _rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def _xlsx_safe(value: str) -> str:
    """Strip characters OOXML text cells cannot hold at all (e.g. stray \\x01
    bytes from PDF extraction — see docs/findings.md, "source data is dirty
    and stays dirty"). This is an xlsx-format compatibility step, not a data
    edit: the CSVs under data/processed/e19/filled/ remain the untouched
    record; only this deliverable's rendering of them is sanitised."""
    return ILLEGAL_CHARACTERS_RE.sub("", value)


def _write_sheet(ws, cols: list[str], rows: list[dict], prov: list[dict]) -> None:
    ws.append(cols)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row, prow in zip(rows, prov):
        ws.append([_xlsx_safe(row[c]) for c in cols])
        for j, c in enumerate(cols, start=1):
            token = prow.get(c, "")
            if token in PROVENANCE_FILLS:
                ws.cell(row=ws.max_row, column=j).fill = PatternFill(
                    "solid", start_color=PROVENANCE_FILLS[token]
                )
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for j, c in enumerate(cols, start=1):
        width = min(max(len(c) + 2, 12), 60)
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = width


def export(filled_dir: Path, out_path: Path) -> None:
    wb = Workbook()
    about = wb.active
    about.title = "About"
    for line in ABOUT_LINES:
        about.append([line])
    about.column_dimensions["A"].width = 90

    icols, irows = _rows(filled_dir / "incidents.csv")
    _, iprov = _rows(filled_dir / "provenance.csv")
    _write_sheet(wb.create_sheet("Incidents"), icols, irows, iprov)

    ccols, crows = _rows(filled_dir / "causes.csv")
    _, cprov = _rows(filled_dir / "causes_provenance.csv")
    _write_sheet(wb.create_sheet("Causes"), ccols, crows, cprov)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


def main() -> int:
    export(FILLED, DEFAULT_OUT)
    print(f"wrote {DEFAULT_OUT}")
    print("deliverable only - never commit; the record is data/processed/e19/filled/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
