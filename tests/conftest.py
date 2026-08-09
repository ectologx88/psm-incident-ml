from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture
def make_row():
    def _make(
        report_id: str = "fixture-report-id",
        incident_date: date = date(2020, 6, 15),
        incident_types: frozenset[str] = frozenset({"Fatality"}),
        property_damage_usd: float | None = 50000.0,
        area_block: str = "MP 298",
    ) -> dict:
        return {
            "report_id": report_id,
            "incident_date": incident_date,
            "incident_types": incident_types,
            "property_damage_usd": property_damage_usd,
            "area_block": area_block,
        }
    return _make
