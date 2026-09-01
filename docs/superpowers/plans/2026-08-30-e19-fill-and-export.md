# E19 Fill & Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a shape-complete, plausible E19 investigation workbook
(`deliverables/e19_filled.xlsx`) for SME evaluation by Tuesday 2026-09-01,
by filling the remaining gaps in the enriched E19 tables (LLM element labels
where available, deterministic synthetic values elsewhere) into a new
`data/processed/e19/filled/` layer, then exporting to xlsx.

**Architecture:** A new `psm.fill` module reads `data/processed/e19/enriched/`
(built by `psm.crosswalk` — never edited in place, since a crosswalk rebuild
would wipe in-place fills) plus `data/processed/e19/llm_causes.csv` and
`schema/synth_rules.yaml`, and writes a `filled/` mirror: same exact column
labels, same parallel per-cell provenance files, every fill deterministic
(sha256 hash-pick, no randomness, no wall clock). A new `psm.export_e19`
module renders `filled/` to one xlsx with provenance-shaded cells and an About
sheet. Pipeline order: `crosswalk → llm_label → fill → export_e19`.

**Tech Stack:** Python 3.11+, `uv`, stdlib `csv`/`hashlib`, `yaml`,
`openpyxl>=3.1` (already in pyproject.toml). Tests with pytest. Lint with ruff.

## Global Constraints

Copied from the repo's CLAUDE.md and the standing session rules — every task
implicitly includes all of these:

- **Never write a value into any `gold_` column, ever.** `gold/gold_labels.csv`
  is untouched by this plan.
- **Never modify `schema/crosswalk.yaml`.** It changes only on human evidence,
  never from LLM output alone.
- **Never overwrite a non-empty cell in the E19 tables.** The existing
  conventions test enforces "xw never overwrote a verbatim value"; this plan
  extends the same principle: `fill` writes only into cells that are empty in
  `enriched/`.
- **E19 column labels are byte-exact**, including irregularities:
  `` ` Failed PSM Framework Element` `` (leading space), `Cause type`,
  `Incident Classificatioin` (sic), `Health & Safety  - Consequence` (double
  space). Copy them from this plan exactly; do not "fix" them.
- **Every non-empty cell in an E19 table needs a provenance token** in the
  parallel file, from the closed set `{"", "src", "xw", "llm", "gold", "syn"}`
  (`tests/test_conventions.py:38`). Provenance files are token-only and
  row-aligned with their value file (row N of provenance = row N of values).
- **Determinism:** all synthetic choices via
  `int(sha256(key + salt).hexdigest(), 16) % N`. Never `random`, never
  `date.today()`. Every threshold/salt/word-list lives in
  `schema/synth_rules.yaml`, not hardcoded (`src/psm/synth.py` docstring rule).
- **Never report a metric scored against `llm_` columns as accuracy.** This
  plan reports fill *counts* only, which is fine.
- **Do not commit** the xlsx deliverable (workbook-shaped output stays out of
  git), `E19 Investigation Report - Rev2.xlsx`, or anything under `data/raw/`
  or `data/interim/`. The `filled/*.csv` tables ARE committed (all <10MB,
  matching the existing `data/processed` contract).
- **Never delete files** — move deletion candidates to a `_Review-for-Deletion/`
  folder instead. **Never force-push.** Commit at each task boundary with the
  exact messages given; no co-author/attribution fields.
- Run everything via `uv run ...` from the repo root
  `/Users/ectologx88/code/ecto/psm-incident-ml`. Do not prefix commands with
  `export PATH=...`.
- `docs/findings.md` is append-only, dated entries. Record what was verified
  and by what method.

## Reference facts (verified 2026-08-30 — re-verify cheaply, don't re-derive)

- `enriched/causes.csv`: 3,572 rows. Columns (exact): `Incident Number`,
  `Cause number`, `Cause Description`, `Cause type`, `Risk Management Cause`,
  `Human Factors  Cause`, ` Failed PSM Framework Element`.
  Element column filled 524/3,572, all provenance `xw`. `Cause type` 0/3,572.
- `enriched/incidents.csv`: 1,214 rows, 43 columns. Fully-empty columns:
  `Work Group`, `Environment & Reputation - Likelihood`,
  `Financial Cost & Business Interruption - Likelihood`.
- `data/processed/e19/llm_causes.csv`: 3,572 rows. Columns: `incident`,
  `cause`, `text`, `xw_element`, `llm_cause_category`, `llm_psm_element`,
  `llm_confidence`, `llm_passes_agreed`, `llm_reason`. Non-empty
  `llm_psm_element`: 2,423 rows (abstentions and the 13 parse failures have
  `""`). Currently **untracked** — Task 1 commits it.
- Risk scores: `Environment & Reputation - Risk Score` non-zero for 186 rows
  (values 2/5/9; 882 rows hold `0`, 146 empty).
  `Financial Cost & Business Interruption - Risk Score` non-empty for 443 rows.
  Real `Health & Safety - Likelihood` distribution (the realism template):
  `5`→265, `2`→193, `3`→177, `1`→10, `4`→0.
- `schema/synth_rules.yaml` is flat top-level keys, currently `version: 1`.
- `schema/crosswalk.yaml` `categories:` entries each carry `primary_element`
  and `confidence` (high/medium/low).

## Design decisions (locked — do not relitigate during execution)

1. **`filled/` layer, not in-place**: `psm.crosswalk` regenerates `enriched/`;
   fills must survive a rebuild, so they live downstream.
2. **Element fill order**: keep `xw` (524) → `llm_psm_element` where non-empty
   (expected 2,008 of the empty rows) → deterministic weighted fallback for
   the rest (expected 1,040), weighted by the LLM run's own element
   distribution so the fallback matches the corpus shape. Tokens `xw`/`llm`/`syn`.
3. **`Cause type`**: cause number `1` → `Immediate`; later causes hash-weighted
   `Underlying`/`Root`. All 3,572 filled, token `syn`.
4. **Incidents**: `Work Group` filled for all 1,214 (a real register assigns
   one everywhere). The two Likelihood columns fill **only where the matching
   Risk Score is present and non-zero** (186 E&R, 443 Financial) — a
   likelihood next to a blank/zero score would read as internally
   inconsistent to an SME, which hurts realism more than a sparse column does.
   Partially-filled real columns (`Detail`, `How did the incident occur`,
   `Health & Safety - Likelihood`, …) are left exactly as they are: partial
   fill is realistic.
5. **Confidence**: new `filled/causes_confidence.csv` keyed
   `Incident Number, Cause number, element_confidence` — crosswalk category
   confidence for `xw` cells, `llm_confidence` (high/low) for `llm` cells,
   empty for `syn`.
6. **xlsx**: one workbook, sheets `About` / `Incidents` / `Causes`, cell
   shading by provenance (xw blue, llm amber, syn grey, src/blank none),
   written to `deliverables/` which is gitignored.

---

### Task 1: Commit the labelling-run inputs

The fill stage reads `llm_causes.csv`; it must be committed first so the
`filled/` layer is reproducible from a fresh clone. Also commits the pending
gold-sample regeneration and findings entries from the labelling session.

**Files:**
- Commit (no edits): `data/processed/e19/llm_causes.csv`,
  `data/processed/e19/llm_disagreements.csv`, `gold/gold_labels.csv`,
  `docs/findings.md`, `src/psm/gold_sample.py`, `src/psm/gold_scaffold.py`,
  `tests/test_gold_sample.py`, `tests/test_gold_scaffold.py`,
  `pyproject.toml`, `uv.lock`, `src/psm/llm_label.py`,
  `data/processed/e19/llm_prompt_example.txt`.

The last four are the rest of the same Bedrock labelling run (the boto3
dependency declaration, the lockfile, the retry/checkpoint hardening, and the
regenerated prompt sample). Without them the run that produced
`llm_causes.csv` is not reproducible from a fresh clone, which is the whole
point of committing it. `data/interim/gold_sample.csv` is deliberately NOT in
the list — `data/interim/` is gitignored (verified `.gitignore:3`).

**Do not `git add -A` or `git add .`** — `data/processed/e19/_pilot_haiku/`,
`_pilot_sonnet/`, and `_smoketest/` are untracked pilot scratch directories
that must stay out of the repo. Use the explicit path list below.

**Interfaces:**
- Produces: committed `data/processed/e19/llm_causes.csv` that Task 3 reads.

- [ ] **Step 1: Check state and sizes**

Run: `git status --short && du -h data/processed/e19/llm_causes.csv`
Expected: the files above listed as `??` or ` M`; llm_causes.csv ~2.0M (<10MB, committable).

- [ ] **Step 2: Verify the full test suite passes before touching anything**

Run: `uv run pytest -q`
Expected: `359 passed, 2 skipped` (or more passed if the count drifted — zero failures is the requirement).

- [ ] **Step 3: Commit**

```bash
git add data/processed/e19/llm_causes.csv data/processed/e19/llm_disagreements.csv \
        data/processed/e19/llm_prompt_example.txt \
        gold/gold_labels.csv docs/findings.md \
        src/psm/gold_sample.py src/psm/gold_scaffold.py src/psm/llm_label.py \
        tests/test_gold_sample.py tests/test_gold_scaffold.py \
        pyproject.toml uv.lock
git status --short   # staged list must match the above exactly; the three
                     # _pilot_*/_smoketest/ dirs must still show as untracked
git commit -m "feat: full LLM labelling run outputs, statement-grain gold sample"
```

Also add the plan file itself in the same commit:
`git add docs/superpowers/plans/2026-08-30-e19-fill-and-export.md`

---

### Task 2: Synth rules v2 + deterministic pick helpers

**Files:**
- Modify: `schema/synth_rules.yaml` (append new keys, bump version)
- Create: `src/psm/fill.py` (helpers only in this task)
- Test: `tests/test_fill.py`

**Interfaces:**
- Produces: `psm.fill.weighted_pick(key: str, salt: str, weights: dict[str, int]) -> str`
  and `psm.fill.load_rules() -> dict` (re-exports `psm.synth.load_rules`);
  yaml keys `work_group_weights`, `work_group_salt`, `cause_type_first_cause`,
  `cause_type_weights`, `cause_type_salt`, `likelihood_weights`,
  `er_likelihood_salt`, `fin_likelihood_salt`, `element_fallback_salt`.

- [ ] **Step 1: Append the new rules to `schema/synth_rules.yaml`**

Change `version: 1` to `version: 2` and append at the end of the file:

```yaml
# --- v2 (2026-08-30): fill-stage rules for psm.fill ------------------------
# These fill the E19 columns the SME deliverable needs shape-complete.
# All picks: int(sha256(key + salt), 16) % total_weight, walked over the
# weight table in sorted-key order. See docs/superpowers/plans/
# 2026-08-30-e19-fill-and-export.md for the design decisions.

# Invented picklist — the real workbook's picklist is one company's named
# shift crews (see e19_disposition.yaml "Work Group" note), so nothing real
# can go here. Generic offshore work groups, uniform weights.
work_group_weights:
  "Production Operations": 1
  "Maintenance": 1
  "Drilling": 1
  "Well Services": 1
  "Marine & Logistics": 1
  "Construction": 1
work_group_salt: "work_group"

# Immediate/Underlying/Root. First cause of an incident reads as the
# immediate cause; later causes split Underlying-heavy — invented ratio,
# openly syn.
cause_type_first_cause: "Immediate"
cause_type_weights:
  "Underlying": 3
  "Root": 2
cause_type_salt: "cause_type"

# Mirrors the REAL Health & Safety - Likelihood distribution measured
# 2026-08-30 (5:265, 2:193, 3:177, 1:10, 4 never used) so synthetic
# likelihoods look like the register's own habits.
likelihood_weights:
  "5": 41
  "2": 30
  "3": 27
  "1": 2
er_likelihood_salt: "er_likelihood"
fin_likelihood_salt: "fin_likelihood"

# Salt for the abstention-fallback element pick (weights are NOT frozen
# here — they are the observed llm_psm_element distribution, computed at
# fill time from the committed llm_causes.csv, so they are deterministic
# without being duplicated data).
element_fallback_salt: "element_fallback"
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_fill.py`:

```python
"""Tests for src/psm/fill.py — deterministic fill of the E19 filled/ layer."""
from __future__ import annotations

import csv
from pathlib import Path

from psm.fill import load_rules, weighted_pick


def test_weighted_pick_is_deterministic_and_in_vocab():
    weights = {"A": 1, "B": 3, "C": 6}
    first = weighted_pick("INC-1|1", "salt", weights)
    second = weighted_pick("INC-1|1", "salt", weights)
    assert first == second
    assert first in weights


def test_weighted_pick_varies_with_key_and_respects_weights():
    weights = {"A": 1, "B": 3, "C": 6}
    picks = [weighted_pick(f"INC-{i}|1", "salt", weights) for i in range(500)]
    counts = {v: picks.count(v) for v in weights}
    # C (weight 6/10) must dominate A (weight 1/10); loose bounds, no flake.
    assert counts["C"] > counts["A"]
    assert set(picks) == {"A", "B", "C"}


def test_weighted_pick_zero_weight_value_never_chosen():
    weights = {"A": 1, "B": 0}
    assert all(
        weighted_pick(f"k{i}", "s", weights) == "A" for i in range(50)
    )


def test_synth_rules_v2_keys_present():
    rules = load_rules()
    for key in (
        "work_group_weights", "work_group_salt",
        "cause_type_first_cause", "cause_type_weights", "cause_type_salt",
        "likelihood_weights", "er_likelihood_salt", "fin_likelihood_salt",
        "element_fallback_salt",
    ):
        assert key in rules, key
    assert rules["version"] == 2
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_fill.py -v`
Expected: FAIL / collection error — `No module named 'psm.fill'`.

- [ ] **Step 4: Write the helpers**

Create `src/psm/fill.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_fill.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/psm/fill.py tests/test_fill.py
git add schema/synth_rules.yaml src/psm/fill.py tests/test_fill.py
git commit -m "feat: synth rules v2 + deterministic weighted pick for the fill stage"
```

---

### Task 3: Causes fill (element + Cause type + provenance + confidence)

**Files:**
- Modify: `src/psm/fill.py` (append functions)
- Test: `tests/test_fill.py` (append tests)

**Interfaces:**
- Consumes: `weighted_pick`, `_hash_int`, `_read_csv`, yaml keys from Task 2.
- Produces:
  `element_confidence_by_number(path: Path = CROSSWALK) -> dict[str, str]`,
  `element_distribution(llm_rows: list[dict]) -> dict[str, int]`,
  `fill_causes(causes: list[dict], prov: list[dict], llm_rows: list[dict], xw_conf: dict[str, str], rules: dict) -> tuple[list[dict], list[dict], list[dict]]`
  returning (filled rows, provenance rows, confidence rows). Confidence rows
  have exactly the keys `Incident Number`, `Cause number`, `element_confidence`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_fill.py`)

```python
from psm.fill import (  # noqa: E402  (grouped with the earlier import block in the real file)
    element_confidence_by_number,
    element_distribution,
    fill_causes,
)

RULES_FIXTURE = {
    "cause_type_first_cause": "Immediate",
    "cause_type_weights": {"Underlying": 3, "Root": 2},
    "cause_type_salt": "cause_type",
    "element_fallback_salt": "element_fallback",
}


def _cause(incident, cause, element=""):
    return {
        "Incident Number": incident, "Cause number": cause,
        "Cause Description": "text", "Cause type": "",
        "Risk Management Cause": "", "Human Factors  Cause": "",
        " Failed PSM Framework Element": element,
    }


def _prov(incident_token="src", element_token=""):
    return {
        "Incident Number": incident_token, "Cause number": "src",
        "Cause Description": "src", "Cause type": "",
        "Risk Management Cause": "", "Human Factors  Cause": "",
        " Failed PSM Framework Element": element_token,
    }


def _llm(incident, cause, element, confidence="high"):
    return {
        "incident": incident, "cause": cause,
        "llm_psm_element": element, "llm_confidence": confidence,
    }


def test_fill_causes_keeps_xw_prefers_llm_falls_back_syn():
    causes = [_cause("A", "1", element="15"), _cause("A", "2"), _cause("A", "3")]
    prov = [_prov(element_token="xw"), _prov(), _prov()]
    llm = [
        _llm("A", "1", "8"),      # must NOT overwrite the xw 15
        _llm("A", "2", "17"),
        _llm("A", "3", ""),       # abstained -> syn fallback
    ]
    rows, prov_out, conf = fill_causes(causes, prov, llm, {"15": "high"}, RULES_FIXTURE)

    assert rows[0][" Failed PSM Framework Element"] == "15"
    assert prov_out[0][" Failed PSM Framework Element"] == "xw"
    assert rows[1][" Failed PSM Framework Element"] == "17"
    assert prov_out[1][" Failed PSM Framework Element"] == "llm"
    # fallback drew from the observed llm distribution: {"8": 1, "17": 1}
    assert rows[2][" Failed PSM Framework Element"] in {"8", "17"}
    assert prov_out[2][" Failed PSM Framework Element"] == "syn"
    # every element cell is now non-empty
    assert all(r[" Failed PSM Framework Element"] for r in rows)


def test_fill_causes_confidence_rows():
    causes = [_cause("A", "1", element="15"), _cause("A", "2"), _cause("A", "3")]
    prov = [_prov(element_token="xw"), _prov(), _prov()]
    llm = [_llm("A", "1", "8"), _llm("A", "2", "17", "low"), _llm("A", "3", "")]
    _, _, conf = fill_causes(causes, prov, llm, {"15": "high"}, RULES_FIXTURE)
    by_key = {(c["Incident Number"], c["Cause number"]): c["element_confidence"] for c in conf}
    assert by_key[("A", "1")] == "high"   # crosswalk grade for the xw cell
    assert by_key[("A", "2")] == "low"    # llm_confidence for the llm cell
    assert by_key[("A", "3")] == ""       # syn has no confidence


def test_fill_causes_cause_type_first_is_immediate_rest_weighted():
    causes = [_cause("A", "1"), _cause("A", "2"), _cause("B", "1")]
    prov = [_prov(), _prov(), _prov()]
    llm = [_llm("A", "1", "8"), _llm("A", "2", "8"), _llm("B", "1", "8")]
    rows, prov_out, _ = fill_causes(causes, prov, llm, {}, RULES_FIXTURE)
    assert rows[0]["Cause type"] == "Immediate"
    assert rows[2]["Cause type"] == "Immediate"
    assert rows[1]["Cause type"] in {"Underlying", "Root"}
    assert all(p["Cause type"] == "syn" for p in prov_out)


def test_fill_causes_never_mutates_inputs():
    causes = [_cause("A", "2")]
    prov = [_prov()]
    fill_causes(causes, prov, [_llm("A", "2", "17")], {}, RULES_FIXTURE)
    assert causes[0][" Failed PSM Framework Element"] == ""
    assert prov[0][" Failed PSM Framework Element"] == ""


def test_element_distribution_counts_only_non_empty():
    llm = [_llm("A", "1", "8"), _llm("A", "2", "8"), _llm("A", "3", "")]
    assert element_distribution(llm) == {"8": 2}


def test_element_confidence_by_number_reads_crosswalk(tmp_path):
    cw = tmp_path / "cw.yaml"
    cw.write_text(
        "categories:\n"
        "  Equipment Failure: {primary_element: 15, confidence: high}\n"
        "  Supervision: {primary_element: 17, confidence: low}\n",
        encoding="utf-8",
    )
    assert element_confidence_by_number(cw) == {"15": "high", "17": "low"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fill.py -v`
Expected: the 6 new tests FAIL with ImportError; the 4 from Task 2 still pass.

- [ ] **Step 3: Implement** (append to `src/psm/fill.py`)

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fill.py -v`
Expected: 10 PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/psm/fill.py tests/test_fill.py
git add src/psm/fill.py tests/test_fill.py
git commit -m "feat: causes fill - element llm/syn fallback, cause type, confidence"
```

---

### Task 4: Incidents fill (Work Group + gated Likelihoods)

**Files:**
- Modify: `src/psm/fill.py` (append)
- Test: `tests/test_fill.py` (append)

**Interfaces:**
- Consumes: `weighted_pick`, column constants, rules keys from Task 2.
- Produces: `fill_incidents(incidents: list[dict], prov: list[dict], rules: dict) -> tuple[list[dict], list[dict]]`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_fill.py`)

```python
from psm.fill import fill_incidents  # noqa: E402

INCIDENT_RULES = {
    "work_group_weights": {"Maintenance": 1, "Drilling": 1},
    "work_group_salt": "work_group",
    "likelihood_weights": {"5": 4, "2": 3, "3": 3},
    "er_likelihood_salt": "er_likelihood",
    "fin_likelihood_salt": "fin_likelihood",
}


def _incident(number, work_group="", er_score="", fin_score=""):
    return {
        "Incident Number": number,
        "Work Group": work_group,
        "Environment & Reputation - Risk Score": er_score,
        "Environment & Reputation - Likelihood": "",
        "Financial Cost & Business Interruption - Risk Score": fin_score,
        "Financial Cost & Business Interruption - Likelihood": "",
    }


def _iprov(number_token="src"):
    return {k: ("" if k != "Incident Number" else number_token)
            for k in _incident("x")}


def test_fill_incidents_work_group_everywhere_likelihood_gated_on_score():
    incidents = [
        _incident("A", er_score="5", fin_score="2"),
        _incident("B", er_score="0"),            # zero score -> no ER likelihood
        _incident("C"),                          # empty scores -> no likelihoods
    ]
    prov = [_iprov(), _iprov(), _iprov()]
    rows, prov_out = fill_incidents(incidents, prov, INCIDENT_RULES)

    assert all(r["Work Group"] in {"Maintenance", "Drilling"} for r in rows)
    assert all(p["Work Group"] == "syn" for p in prov_out)

    assert rows[0]["Environment & Reputation - Likelihood"] in {"5", "2", "3"}
    assert prov_out[0]["Environment & Reputation - Likelihood"] == "syn"
    assert rows[0]["Financial Cost & Business Interruption - Likelihood"] in {"5", "2", "3"}

    assert rows[1]["Environment & Reputation - Likelihood"] == ""
    assert rows[2]["Environment & Reputation - Likelihood"] == ""
    assert rows[2]["Financial Cost & Business Interruption - Likelihood"] == ""
    assert prov_out[2]["Environment & Reputation - Likelihood"] == ""


def test_fill_incidents_never_overwrites_existing_work_group():
    incidents = [_incident("A", work_group="Night Crew 7")]
    prov = [_iprov()]
    rows, prov_out = fill_incidents(incidents, prov, INCIDENT_RULES)
    assert rows[0]["Work Group"] == "Night Crew 7"
    assert prov_out[0]["Work Group"] == ""   # untouched -> token unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fill.py -v`
Expected: 2 new FAIL (ImportError on `fill_incidents`), 10 pass.

- [ ] **Step 3: Implement** (append to `src/psm/fill.py`)

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fill.py -v`
Expected: 12 PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/psm/fill.py tests/test_fill.py
git add src/psm/fill.py tests/test_fill.py
git commit -m "feat: incidents fill - work group, score-gated likelihoods"
```

---

### Task 5: CLI, real-data run, disposition bookkeeping, integration test

**Files:**
- Modify: `src/psm/fill.py` (append `main`)
- Modify: `schema/e19_disposition.yaml` (generator bookkeeping)
- Test: `tests/test_fill_outputs.py` (new — real-data invariants)
- Output: `data/processed/e19/filled/` (5 CSVs, committed)

**Interfaces:**
- Consumes: everything from Tasks 2–4.
- Produces: `data/processed/e19/filled/{incidents,provenance,causes,causes_provenance,causes_confidence}.csv` — the exact inputs Task 6 reads.

- [ ] **Step 1: Append `main` to `src/psm/fill.py`**

```python
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
```

- [ ] **Step 2: Run on real data**

Run: `uv run python -m psm.fill`
Expected: `causes: 3572 rows, element tokens {'xw': 524, 'llm': 2008, 'syn': 1040}` (or very close; these were pre-computed 2026-08-30 as 524 xw + 2,423 total llm labels − 415 llm labels on already-xw rows = 2,008, remainder 1,040). **If llm/syn differ by more than ±5, stop and investigate the filter logic — do not shrug it off.**

- [ ] **Step 3: Write the real-data invariant tests**

Create `tests/test_fill_outputs.py`:

```python
"""Invariants over the real data/processed/e19/filled/ outputs.

Mirrors the conventions test_conventions.py enforces for enriched/: parallel
provenance shape, closed token set, no un-provenanced fill — plus the fill
contract itself: never overwrite a non-empty enriched value.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
E19 = REPO / "data" / "processed" / "e19"
FILLED, ENRICHED = E19 / "filled", E19 / "enriched"
TOKENS = {"", "src", "xw", "llm", "gold", "syn"}

pytestmark = pytest.mark.skipif(
    not (FILLED / "causes.csv").exists(), reason="filled/ not built"
)


def _rows(path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.mark.parametrize("value_name,prov_name", [
    ("causes.csv", "causes_provenance.csv"),
    ("incidents.csv", "provenance.csv"),
])
def test_provenance_matches_shape_and_closed_set(value_name, prov_name):
    values, prov = _rows(FILLED / value_name), _rows(FILLED / prov_name)
    assert len(values) == len(prov)
    assert values[0].keys() == prov[0].keys()
    bad = {t for p in prov for t in p.values()} - TOKENS
    assert not bad, f"tokens outside closed set: {bad}"


@pytest.mark.parametrize("value_name,prov_name", [
    ("causes.csv", "causes_provenance.csv"),
    ("incidents.csv", "provenance.csv"),
])
def test_fill_never_overwrote_a_non_empty_enriched_value(value_name, prov_name):
    enriched, filled = _rows(ENRICHED / value_name), _rows(FILLED / value_name)
    assert len(enriched) == len(filled)
    for before, after in zip(enriched, filled):
        for col, val in before.items():
            if val.strip():
                assert after[col] == val, (value_name, col, before["Incident Number"])


def test_every_element_cell_is_filled_and_provenanced():
    values = _rows(FILLED / "causes.csv")
    prov = _rows(FILLED / "causes_provenance.csv")
    col = " Failed PSM Framework Element"
    assert all(r[col].strip() for r in values)
    assert all(p[col] in {"xw", "llm", "syn"} for p in prov)


def test_llm_cells_match_the_labelling_run_exactly():
    values = _rows(FILLED / "causes.csv")
    prov = _rows(FILLED / "causes_provenance.csv")
    llm = {(r["incident"], r["cause"]): r["llm_psm_element"].strip()
           for r in _rows(E19 / "llm_causes.csv")}
    col = " Failed PSM Framework Element"
    checked = 0
    for v, p in zip(values, prov):
        if p[col] == "llm":
            key = (v["Incident Number"], v["Cause number"])
            assert v[col] == llm[key], key
            checked += 1
    assert checked > 1500  # the llm fill is the bulk of the layer
```

- [ ] **Step 4: Run the new tests**

Run: `uv run pytest tests/test_fill_outputs.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Update `schema/e19_disposition.yaml` bookkeeping**

Edit these entries (they exist; find each by its quoted label). Change only
the `generator:` value and append to the note — keep everything else:

- `"Work Group"` (line ~310): `generator: null` → `generator: syn_work_group`
- `"Environment & Reputation - Likelihood"` (line ~332): `generator: null` → `generator: syn_likelihood_gated_on_score`
- `"Financial Cost & Business Interruption - Likelihood"` (line ~347): `generator: null` → `generator: syn_likelihood_gated_on_score`
- `"Cause type"` (line ~399): `generator: null` → `generator: syn_cause_type`

Append one line to each entry's `note:` block:
`Generator implemented 2026-08-30 in src/psm/fill.py (filled/ layer only; enriched/ untouched).`

Do NOT touch `"Health & Safety - Likelihood"` (disposition `real`,
`leave_blank` — its partial fill stays as-is by design decision 4).

- [ ] **Step 6: Full suite, lint, commit**

```bash
uv run pytest -q
uv run ruff check src tests
git add src/psm/fill.py tests/test_fill_outputs.py schema/e19_disposition.yaml \
        data/processed/e19/filled/
git commit -m "feat: filled/ E19 layer - shape-complete causes and incidents"
```
Expected: zero test failures (skips OK).

---

### Task 6: xlsx export

**Files:**
- Create: `src/psm/export_e19.py`
- Test: `tests/test_export_e19.py`
- Modify: `.gitignore` (add `deliverables/`)

**Interfaces:**
- Consumes: the five `filled/` CSVs from Task 5 (paths via `psm.fill.FILLED`).
- Produces: `deliverables/e19_filled.xlsx` and
  `export(filled_dir: Path, out_path: Path) -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_export_e19.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_export_e19.py -v`
Expected: FAIL — `No module named 'psm.export_e19'`.

- [ ] **Step 3: Implement**

Create `src/psm/export_e19.py`:

```python
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


def _write_sheet(ws, cols: list[str], rows: list[dict], prov: list[dict]) -> None:
    ws.append(cols)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row, prow in zip(rows, prov):
        ws.append([row[c] for c in cols])
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_export_e19.py -v`
Expected: PASS. If the fill-colour assertion fails on the `"00"` prefix,
inspect `cell.fill.start_color.rgb` in the failure output and adjust the
test's expected prefix to what openpyxl actually round-trips (`00` vs `FF`) —
the colour hex itself must match `PROVENANCE_FILLS`.

- [ ] **Step 5: Gitignore the deliverables directory, then build the real workbook**

Append to `.gitignore`:

```
deliverables/
```

Run: `uv run python -m psm.export_e19`
Expected: `wrote .../deliverables/e19_filled.xlsx`. Open-check:

```bash
uv run python -c "
from openpyxl import load_workbook
wb = load_workbook('deliverables/e19_filled.xlsx')
print(wb.sheetnames)
print('incidents rows:', wb['Incidents'].max_row - 1)
print('causes rows:', wb['Causes'].max_row - 1)
"
```
Expected: `['About', 'Incidents', 'Causes']`, 1214 incidents, 3572 causes.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/psm/export_e19.py tests/test_export_e19.py
git add src/psm/export_e19.py tests/test_export_e19.py .gitignore
git status --short   # confirm deliverables/ does NOT appear
git commit -m "feat: xlsx export of the filled E19 layer with provenance shading"
```

---

### Task 7: Verification sweep, findings entry, handoff

**Files:**
- Modify: `docs/findings.md` (append entry)

- [ ] **Step 1: Full suite + rebuild determinism check**

```bash
uv run pytest -q
uv run python -m psm.fill && git diff --stat data/processed/e19/filled/
```
Expected: zero failures; `git diff` shows **no changes** (a second fill run is
byte-identical — if it isn't, something nondeterministic crept in: stop and
find it before delivering).

- [ ] **Step 2: Spot-check the workbook like an SME would**

Open 5 arbitrary causes rows and their incident rows; confirm: element
present on every cause, Cause type present, first cause of an incident is
`Immediate`, no likelihood sits beside an empty/zero risk score, shading
matches the provenance CSVs for the same cells. Do this by script, not by
assertion:

```bash
uv run python -c "
import csv, itertools
rows = list(csv.DictReader(open('data/processed/e19/filled/causes.csv')))
prov = list(csv.DictReader(open('data/processed/e19/filled/causes_provenance.csv')))
for r, p in itertools.islice(zip(rows, prov), 0, 3500, 700):
    print(r['Incident Number'], r['Cause number'], '| type:', r['Cause type'],
          '| element:', r[' Failed PSM Framework Element'], f\"({p[' Failed PSM Framework Element']})\")
"
```

- [ ] **Step 3: Append the findings entry**

Append to `docs/findings.md` (fill the bracketed counts from the actual
Task 5 Step 2 output — do not leave brackets in the committed text):

```markdown
---

## 2026-08-31 — filled/ E19 layer + xlsx deliverable for SME review

`psm.fill` (new) fills the enriched tables' remaining gaps into
`data/processed/e19/filled/` — same byte-exact labels, same parallel
provenance files, every fill deterministic (sha256 picks, rules in
schema/synth_rules.yaml v2). `psm.export_e19` (new) renders it to
`deliverables/e19_filled.xlsx` (gitignored) with per-cell provenance shading.

Element column: 3,572/3,572 filled — 524 xw (kept), [N] llm, [N] syn
fallback weighted by the run's own element distribution. Cause type:
3,572 syn (first cause Immediate, rest hash-weighted). Work Group: 1,214 syn
from an invented picklist. Likelihoods: syn only beside a present, non-zero
risk score ([N] E&R, [N] Financial) — internal consistency beats column
completeness for realism.

Verified: fill is idempotent (second run byte-identical, git diff clean);
never overwrites a non-empty enriched value (tests/test_fill_outputs.py, run
against the real outputs); llm cells match llm_causes.csv exactly; provenance
tokens closed-set. The workbook's About sheet states, in plain language, that
this is a demonstration of an auto-populated register — model labels
unvalidated (25.4% crosswalk agreement, n=524), synthetic cells correspond to
nothing real. It is a proposal for SMEs to evaluate, not a finding.
```

- [ ] **Step 4: Commit and hand off**

```bash
git add docs/findings.md
git commit -m "docs: findings entry for the filled E19 layer and SME deliverable"
```

Final message to the user must include: the path
`deliverables/e19_filled.xlsx`, the element token counts actually observed,
the test-suite result, and the reminder that the About sheet is the framing
the SME sees first (worth a 60-second read before sending).

---

## Self-review (done at plan-writing time)

- **Spec coverage:** shape-complete causes (element, Cause type) ✓ Tasks 3/5;
  incidents empty columns ✓ Task 4 (Likelihoods deliberately score-gated,
  decision 4); xlsx deliverable ✓ Task 6; Tuesday deadline — ~6–8h of
  execution across Tasks 1–7, one working day.
- **Placeholder scan:** the findings entry's `[N]` brackets are explicit
  fill-from-measured-output instructions, not placeholders; no TBDs remain.
- **Type consistency:** `weighted_pick(key, salt, weights)` used identically
  in Tasks 2–4; `fill_causes` returns 3-tuple / `fill_incidents` 2-tuple,
  consumed with matching arity in Task 5's `main`; `PROVENANCE_FILLS` and
  `export(filled_dir, out_path)` match between Task 6's test and module.
- **Known risk:** openpyxl's round-tripped colour string prefix (`00` vs
  `FF`) varies by version — Task 6 Step 4 tells the executor how to resolve
  it against observed behaviour rather than guessing.
