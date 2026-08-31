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
from collections import Counter
from pathlib import Path

import yaml

from psm.synth import load_rules  # re-exported for callers/tests

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

# Fill-stage counterpart to synth.SYN_COLUMN_MANIFEST. Kept separate rather
# than merged into that manifest because SYN_COLUMN_MANIFEST is pinned
# cell-for-cell to synthesize_row's actual output by
# tests/test_synth.py:254 (test_synthesize_row_output_keys_match_manifest) --
# these four generators run in fill_causes/fill_incidents above, never in
# synth.synthesize_row, so they cannot live in that manifest without breaking
# it. tests/test_ledger.py checks generator names against the union of both.
FILL_COLUMN_MANIFEST: dict[str, dict[str, object]] = {
    "syn_work_group": {
        "description": "Hash-pick from an invented generic offshore picklist; "
                        "the real workbook's picklist is one company's named shift crews.",
        "fabricated": True,
    },
    "syn_likelihood_gated_on_score": {
        "description": "Hash-weighted 1-5 mirroring the real H&S likelihood distribution, "
                        "written only beside a present, non-zero risk score.",
        "fabricated": True,
    },
    "syn_cause_type": {
        "description": "Cause 1 is Immediate; later causes hash-weighted Underlying/Root.",
        "fabricated": True,
    },
}

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


def element_confidence_by_number(path: Path = CROSSWALK) -> dict[str, str]:
    """primary_element (as str) -> the crosswalk category's confidence grade."""
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        str(v["primary_element"]): v["confidence"]
        for v in spec["categories"].values()
    }


def element_distribution(llm_rows: list[dict]) -> dict[str, int]:
    """Observed llm_psm_element distribution (non-abstaining rows only).
    Used as the syn-fallback weight table — deterministic because
    llm_causes.csv is committed, without duplicating it into yaml."""
    return dict(Counter(
        r["llm_psm_element"].strip()
        for r in llm_rows if r["llm_psm_element"].strip()
    ))


def fill_causes(
    causes: list[dict], prov: list[dict], llm_rows: list[dict],
    xw_conf: dict[str, str], rules: dict,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (rows, provenance rows, confidence rows). Inputs untouched."""
    assert len(causes) == len(prov), "value/provenance row count mismatch"
    llm_by_key = {(r["incident"], r["cause"]): r for r in llm_rows}
    fallback_weights = element_distribution(llm_rows)

    out_rows, out_prov, out_conf = [], [], []
    for row, prow in zip(causes, prov):
        row, prow = dict(row), dict(prow)
        incident, cause = row["Incident Number"], row["Cause number"]
        key = f"{incident}|{cause}"
        confidence = ""

        existing = row[ELEMENT_COL].strip()
        if existing:
            confidence = xw_conf.get(existing, "")
        else:
            llm = llm_by_key.get((incident, cause), {})
            llm_element = (llm.get("llm_psm_element") or "").strip()
            if llm_element:
                row[ELEMENT_COL] = llm_element
                prow[ELEMENT_COL] = "llm"
                confidence = llm.get("llm_confidence", "")
            else:
                row[ELEMENT_COL] = weighted_pick(
                    key, rules["element_fallback_salt"], fallback_weights
                )
                prow[ELEMENT_COL] = "syn"

        if not row[CAUSE_TYPE_COL].strip():
            if cause.strip() == "1":
                row[CAUSE_TYPE_COL] = rules["cause_type_first_cause"]
            else:
                row[CAUSE_TYPE_COL] = weighted_pick(
                    key, rules["cause_type_salt"], rules["cause_type_weights"]
                )
            prow[CAUSE_TYPE_COL] = "syn"

        out_rows.append(row)
        out_prov.append(prow)
        out_conf.append({
            "Incident Number": incident, "Cause number": cause,
            "element_confidence": confidence,
        })
    return out_rows, out_prov, out_conf


def _score_is_positive(value: str) -> bool:
    value = value.strip()
    return bool(value) and value != "0"


def fill_incidents(
    incidents: list[dict], prov: list[dict], rules: dict,
) -> tuple[list[dict], list[dict]]:
    """Work Group everywhere it's blank; Likelihood only beside a real,
    non-zero Risk Score (a likelihood next to a blank score would read as
    internally inconsistent). Inputs untouched."""
    assert len(incidents) == len(prov), "value/provenance row count mismatch"
    out_rows, out_prov = [], []
    for row, prow in zip(incidents, prov):
        row, prow = dict(row), dict(prow)
        number = row["Incident Number"]

        if not row[WORK_GROUP_COL].strip():
            row[WORK_GROUP_COL] = weighted_pick(
                number, rules["work_group_salt"], rules["work_group_weights"]
            )
            prow[WORK_GROUP_COL] = "syn"

        for score_col, lik_col, salt_key in (
            (ER_SCORE_COL, ER_LIKELIHOOD_COL, "er_likelihood_salt"),
            (FIN_SCORE_COL, FIN_LIKELIHOOD_COL, "fin_likelihood_salt"),
        ):
            if not row[lik_col].strip() and _score_is_positive(row[score_col]):
                row[lik_col] = weighted_pick(
                    number, rules[salt_key], rules["likelihood_weights"]
                )
                prow[lik_col] = "syn"

        out_rows.append(row)
        out_prov.append(prow)
    return out_rows, out_prov


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    rules = load_rules()
    xw_conf = element_confidence_by_number()
    llm_rows = _read_csv(LLM_CAUSES)

    causes = _read_csv(ENRICHED / "causes.csv")
    causes_prov = _read_csv(ENRICHED / "causes_provenance.csv")
    c_rows, c_prov, c_conf = fill_causes(causes, causes_prov, llm_rows, xw_conf, rules)

    incidents = _read_csv(ENRICHED / "incidents.csv")
    incidents_prov = _read_csv(ENRICHED / "provenance.csv")
    i_rows, i_prov = fill_incidents(incidents, incidents_prov, rules)

    FILLED.mkdir(parents=True, exist_ok=True)
    _write_csv(FILLED / "causes.csv", _fieldnames(ENRICHED / "causes.csv"), c_rows)
    _write_csv(FILLED / "causes_provenance.csv", _fieldnames(ENRICHED / "causes.csv"), c_prov)
    _write_csv(FILLED / "causes_confidence.csv",
               ["Incident Number", "Cause number", "element_confidence"], c_conf)
    _write_csv(FILLED / "incidents.csv", _fieldnames(ENRICHED / "incidents.csv"), i_rows)
    _write_csv(FILLED / "provenance.csv", _fieldnames(ENRICHED / "incidents.csv"), i_prov)

    element_tokens = Counter(p[ELEMENT_COL] for p in c_prov)
    print(f"causes: {len(c_rows)} rows, element tokens {dict(element_tokens)}")
    print(f"incidents: {len(i_rows)} rows -> {FILLED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
