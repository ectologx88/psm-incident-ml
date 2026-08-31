"""Fill the remaining gaps in the enriched E19 tables into a filled/ layer.

Reads data/processed/e19/enriched/ (built by psm.crosswalk — never edited in
place, a crosswalk rebuild would wipe in-place fills), the LLM labelling run
(llm_causes.csv), and schema/synth_rules.yaml. Writes a mirror under
data/processed/e19/filled/ with the same byte-exact column labels and the
same parallel per-cell provenance convention (tokens: src/xw/llm/syn).

Fill rules (design locked in docs/superpowers/plans/
2026-08-30-e19-fill-and-export.md):
  - ` Failed PSM Framework Element`: existing xw values kept; empty cells get
    the LLM's element where the run produced one, else a deterministic
    weighted pick over the run's own element distribution (token syn).
  - `Cause type`: cause 1 -> Immediate, later causes hash-weighted
    Underlying/Root. All syn.
  - `Work Group`: hash-pick from an invented generic picklist, all rows.
  - The two empty Likelihood columns: hash-weighted 1-5 mirroring the real
    H&S likelihood distribution, only where the matching Risk Score is
    present and non-zero (a likelihood beside a blank score would read as
    internally inconsistent).

Never overwrites a non-empty enriched cell. Fully deterministic: every choice
is int(sha256(key+salt),16) %-walked over a weight table from
schema/synth_rules.yaml; no randomness, no wall clock.

Run:  uv run python -m psm.fill
"""
from __future__ import annotations

import csv
import hashlib
from collections import Counter  # noqa: F401
from pathlib import Path

import yaml  # noqa: F401

from psm.synth import load_rules  # noqa: F401  (re-exported for callers/tests)

REPO = Path(__file__).resolve().parents[2]
E19 = REPO / "data" / "processed" / "e19"
ENRICHED = E19 / "enriched"
FILLED = E19 / "filled"
LLM_CAUSES = E19 / "llm_causes.csv"
CROSSWALK = REPO / "schema" / "crosswalk.yaml"

ELEMENT_COL = " Failed PSM Framework Element"
CAUSE_TYPE_COL = "Cause type"
WORK_GROUP_COL = "Work Group"
ER_LIKELIHOOD_COL = "Environment & Reputation - Likelihood"
ER_SCORE_COL = "Environment & Reputation - Risk Score"
FIN_LIKELIHOOD_COL = "Financial Cost & Business Interruption - Likelihood"
FIN_SCORE_COL = "Financial Cost & Business Interruption - Risk Score"

csv.field_size_limit(10**9)


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _fieldnames(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as fh:
        return next(csv.reader(fh))


def _hash_int(key: str, salt: str) -> int:
    return int(hashlib.sha256(f"{key}{salt}".encode()).hexdigest(), 16)


def weighted_pick(key: str, salt: str, weights: dict[str, int]) -> str:
    """Deterministic weighted choice: hash % total, walked in sorted-key
    order so dict insertion order can never change the output."""
    total = sum(weights.values())
    roll = _hash_int(key, salt) % total
    for value in sorted(weights):
        roll -= weights[value]
        if roll < 0:
            return value
    raise AssertionError("unreachable: weights walk exhausted")
