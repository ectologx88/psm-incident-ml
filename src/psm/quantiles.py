"""Integer quantile-table lookup for lognormal day-offset draws.

Tables are COMMITTED artifacts under schema/quantiles/, built once by
scripts/build_quantile_tables.py (the only scipy import in the repo).
The engine does table[hash % 1024] -- pure-integer, cross-platform,
byte-identical on regeneration."""
from __future__ import annotations

import csv
import hashlib
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TABLE_DIR = REPO / "schema" / "quantiles"
BUCKETS = 1024

# (median_days, sigma): union of every lognormal knob across the four
# scenario YAMLs (report_lag, investigation duration, closeout, incl. the
# test-only meridian_nt closeout of 60d).
CONFIGS = ((2, 0.6), (7, 0.5), (10, 0.8), (21, 0.6), (30, 0.7),
           (40, 0.5), (45, 0.6), (60, 0.6), (130, 0.8))


def table_path(median_days: int, sigma: float) -> Path:
    return TABLE_DIR / f"lognormal_m{median_days}_s{round(sigma * 100)}.csv"


@lru_cache(maxsize=None)
def load_table(median_days: int, sigma: float) -> tuple[int, ...]:
    with table_path(median_days, sigma).open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        vals = tuple(int(r["day_offset"]) for r in reader)
    assert len(vals) == BUCKETS, f"{table_path(median_days, sigma)}: {len(vals)} rows"
    return vals


def draw_days(key: str, median_days: int, sigma: float) -> int:
    h = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)
    return load_table(median_days, sigma)[h % BUCKETS]


def analytic_overdue_rate(median_days: int, sigma: float,
                          agreed_min: int, agreed_max: int) -> float:
    """P(completion offset > agreed offset) under the committed table and a
    uniform integer agreed offset -- iterated exactly (1024 x span), no
    sampling. Stored in each manifest; the overdue KPI must land near it."""
    t = load_table(median_days, sigma)
    span = range(agreed_min, agreed_max + 1)
    hits = sum(1 for v in t for o in span if v > o)
    return hits / (len(t) * len(span))
