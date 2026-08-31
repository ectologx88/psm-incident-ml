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
import re
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
    "Exception: Incident Number is unshaded but is not verbatim. BSEE",
    "publishes no incident identifier, so this repo constructs the key; a few",
    "(UNKEYED-6e8704573b22 among them) are content-hash suffixes rather than",
    "values copied from a source field.",
    "",
    "Model-assigned labels are unvalidated. On the 524 statements where the",
    "crosswalk also holds an opinion, the model agreed on 25.4% (133) and",
    "abstained entirely on 109; counting only the 415 where both produced a",
    "label, agreement is 32.0%. The corpus also skews heavily to one category.",
    "Treat every amber/grey cell as a proposal to evaluate, not a finding.",
    "Full provenance: data/processed/e19/filled/ in the psm-incident-ml",
    "repository.",
    "A few cause descriptions contain control characters left by PDF extraction that",
    "xlsx cannot store; each is rendered here as a single space. The committed CSVs in",
    "data/processed/e19/filled/ keep the original bytes.",
]


def _rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


# One or more consecutive illegal characters, collapsed to a single space by
# _xlsx_safe rather than one space per byte (openpyxl's own
# ILLEGAL_CHARACTERS_RE has no quantifier, so it would otherwise match -- and
# get substituted -- one character at a time).
_ILLEGAL_RUN_RE = re.compile(f"(?:{ILLEGAL_CHARACTERS_RE.pattern})+")


def _xlsx_safe(value: str) -> str:
    """Substitute each run of characters OOXML text cells cannot hold at all
    (e.g. stray \\x01 bytes from PDF extraction — see docs/findings.md,
    "source data is dirty and stays dirty") with a single space, rather than
    deleting them. In this corpus a control byte sits at a word boundary
    (e.g. "burn\\x01injury\\x01to"), so deleting it would silently fabricate a
    word ("burninjuryto") that never appeared in the source; a space keeps the
    text truthful. A run of several consecutive control bytes collapses to
    one space, not one space per byte. No other whitespace is touched: no
    stripping, no collapsing of spaces that were already in the source text.

    This is an xlsx-format compatibility step, not a data edit: the CSVs
    under data/processed/e19/filled/ remain the untouched record with the
    original bytes; only this deliverable's rendering of them is sanitised.
    """
    return _ILLEGAL_RUN_RE.sub(" ", value)


def _write_sheet(ws, cols: list[str], rows: list[dict], prov: list[dict]) -> int:
    """Returns the number of cells whose value was sanitised by _xlsx_safe."""
    assert len(rows) == len(prov), "value/provenance row count mismatch"
    ws.append(cols)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    sanitised = 0
    for row, prow in zip(rows, prov):
        values = []
        for c in cols:
            raw = row[c]
            safe = _xlsx_safe(raw)
            if safe != raw:
                sanitised += 1
            values.append(safe)
        ws.append(values)
        for j, c in enumerate(cols, start=1):
            token = prow.get(c, "")
            if token not in PROVENANCE_FILLS and token not in ("", "src"):
                raise ValueError(
                    f"{c!r}: unknown provenance token {token!r} -- "
                    "not in PROVENANCE_FILLS and not '' or 'src'"
                )
            if token in PROVENANCE_FILLS:
                ws.cell(row=ws.max_row, column=j).fill = PatternFill(
                    "solid", start_color=PROVENANCE_FILLS[token]
                )
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for j, c in enumerate(cols, start=1):
        width = min(max(len(c) + 2, 12), 60)
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = width
    return sanitised


def export(filled_dir: Path, out_path: Path) -> int:
    """Builds the workbook and returns the number of cells sanitised by
    _xlsx_safe, so callers can observe (and log/print) how many cells were
    altered instead of that fact being visible only via a print statement."""
    wb = Workbook()
    about = wb.active
    about.title = "About"
    for line in ABOUT_LINES:
        about.append([line])
    about.column_dimensions["A"].width = 90

    icols, irows = _rows(filled_dir / "incidents.csv")
    _, iprov = _rows(filled_dir / "provenance.csv")
    sanitised = _write_sheet(wb.create_sheet("Incidents"), icols, irows, iprov)

    ccols, crows = _rows(filled_dir / "causes.csv")
    _, cprov = _rows(filled_dir / "causes_provenance.csv")
    sanitised += _write_sheet(wb.create_sheet("Causes"), ccols, crows, cprov)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return sanitised


def main() -> int:
    sanitised = export(FILLED, DEFAULT_OUT)
    print(f"wrote {DEFAULT_OUT}")
    print(f"sanitised {sanitised} cells containing control characters unrepresentable in xlsx")
    print("deliverable only - never commit; the record is data/processed/e19/filled/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
