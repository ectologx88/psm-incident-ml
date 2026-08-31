"""Round-trip test for the xlsx export over a tiny synthetic filled/ dir."""
from __future__ import annotations

import csv

from openpyxl import load_workbook

from psm.export_e19 import PROVENANCE_FILLS, export


def _write(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def test_export_builds_three_sheets_with_provenance_shading(tmp_path):
    filled = tmp_path / "filled"
    filled.mkdir()
    icols = ["Incident Number", "Work Group"]
    _write(filled / "incidents.csv", icols, [{"Incident Number": "A-1", "Work Group": "Drilling"}])
    _write(filled / "provenance.csv", icols, [{"Incident Number": "src", "Work Group": "syn"}])
    ccols = ["Incident Number", "Cause number", " Failed PSM Framework Element"]
    _write(filled / "causes.csv", ccols,
           [{"Incident Number": "A-1", "Cause number": "1", " Failed PSM Framework Element": "17"}])
    _write(filled / "causes_provenance.csv", ccols,
           [{"Incident Number": "src", "Cause number": "src", " Failed PSM Framework Element": "llm"}])
    _write(filled / "causes_confidence.csv",
           ["Incident Number", "Cause number", "element_confidence"],
           [{"Incident Number": "A-1", "Cause number": "1", "element_confidence": "high"}])

    out = tmp_path / "out.xlsx"
    export(filled, out)

    wb = load_workbook(out)
    assert wb.sheetnames == ["About", "Incidents", "Causes"]
    inc = wb["Incidents"]
    assert inc["A1"].value == "Incident Number"
    assert inc["B2"].value == "Drilling"
    assert inc["B2"].fill.start_color.rgb == "00" + PROVENANCE_FILLS["syn"]
    causes = wb["Causes"]
    assert causes["C2"].value == "17"
    assert causes["C2"].fill.start_color.rgb == "00" + PROVENANCE_FILLS["llm"]
    assert "not a real" in str(wb["About"]["A4"].value).lower()
