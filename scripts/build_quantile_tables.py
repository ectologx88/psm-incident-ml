"""Dev-only: writes the committed integer quantile tables. The ONLY file in
the repo that may import scipy. Run once per config change:
    uv run --with scipy python scripts/build_quantile_tables.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from psm.quantiles import BUCKETS, CONFIGS, TABLE_DIR, table_path
import math


def build(median_days: int, sigma: float) -> list[int]:
    out = []
    for i in range(BUCKETS):
        z = norm.ppf((i + 0.5) / BUCKETS)
        out.append(max(0, round(median_days * math.exp(sigma * z))))
    return out


def main() -> int:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    for median, sigma in CONFIGS:
        path = table_path(median, sigma)
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["day_offset"])
            for v in build(median, sigma):
                w.writerow([v])
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
