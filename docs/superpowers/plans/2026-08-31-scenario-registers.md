# Scenario-Planted E19 Registers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the E19 deliverable's provenance mislabels, then build three synthetic-company E19 registers with planted, manifest-documented process pathologies and a KPI layer whose tests prove every plant is recovered.

**Architecture:** Phase 0 fixes provenance at its origin (`crosswalk.py`) via a new single-source-of-truth `psm.provenance` module. A new deterministic scenario engine (`psm.scenario`) samples disjoint donor partitions from the 1,214 real BSEE incidents and generates complete 4-table registers per company, shaped by per-company YAML process-rate knobs through committed integer quantile tables (no scipy at runtime). `psm.kpi` computes nine KPIs; `tests/test_scenarios.py` asserts planted-vs-measured, negative controls, and a near-threshold variant. Export comes last.

**Tech Stack:** Python 3.12, uv, pytest, openpyxl, PyYAML. scipy ONLY inside the dev-only quantile-table build script.

**Spec:** `docs/superpowers/specs/2026-08-31-scenario-registers-design.md` — the authority when this plan is ambiguous.

## Global Constraints

- Determinism: every draw is `int(hashlib.sha256(f"{key}|{salt}".encode()).hexdigest(), 16)` walked in sorted-key order. Never `random`, never `date.today()`, never scipy at runtime.
- Provenance closed set `{"", "src", "xw", "llm", "gold", "syn", "key", "pseud"}` — defined ONLY in `src/psm/provenance.py`; every other site imports it.
- Byte-exact E19 workbook labels: no new columns in the 4 register tables. Headers copied verbatim from `data/processed/e19/real_only/*.csv`.
- Corpus facts: 1,214 donor incidents; 150 per company; disjoint partitions in fixed company order `["northstar", "meridian", "coastal"]`; shared window 2021-01-01..2025-12-31.
- Never write `gold_*` columns. Never score against `llm_` columns and call it accuracy. `deliverables/` stays gitignored. Never commit `data/raw/` or `data/interim/`.
- Every new blocking invariant test must be shown to fail under a deliberate mutation before it is trusted (apply the mutation, observe the failure, undo it, record both in the task report).
- NEVER use any git command that discards working-tree changes or deletes untracked files — a guardrail blocks that whole class. To undo a deliberate mutation of a generated file, re-run its generator; to undo a source-file mutation, reverse the edit you made.
- Company data under `data/companies/` IS committed (processed synthetic output, like `data/processed/e19/`).
- All commands run from the repo root with `uv run`.
- The RELAY Google Drive refresh is NOT part of this plan — no task may touch `~/Library/CloudStorage/GoogleDrive-*`.

---

### Task 1: `psm.provenance` — single source of truth for tokens and fills

**Files:**
- Create: `src/psm/provenance.py`
- Test: `tests/test_provenance_module.py`
- Modify: `tests/test_conventions.py` (line ~38: `PROVENANCE_TOKENS` literal), `tests/test_fill_outputs.py` (line ~17: `TOKENS` literal), `src/psm/export_e19.py` (line ~28: `PROVENANCE_FILLS` literal and the allowlist check in `_write_sheet`)

**Interfaces:**
- Consumes: nothing.
- Produces: `psm.provenance.TOKENS: frozenset[str]`, `FILL_COLORS: dict[str, str]`, `UNSHADED: frozenset[str]`, `KEY_COLUMNS: frozenset[str]`, `PSEUD_COLUMNS: frozenset[str]`, `provenance_row(row: dict, cols: list[str], key_columns=KEY_COLUMNS, pseud_columns=PSEUD_COLUMNS) -> dict[str, str]`. Later tasks (2, 7-10, 12, 14) import these.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provenance_module.py
"""psm.provenance is the single source of truth for provenance tokens.

Before this module existed the closed set was hardcoded in three places
(test_conventions, test_fill_outputs, export_e19) which could drift apart
silently -- src/key/pseud are all "valid" set members, so no closed-set
test catches a site that never learned about a new token.
"""
from psm import provenance as pv


def test_token_set_is_exactly_the_documented_closed_set():
    assert pv.TOKENS == frozenset(
        {"", "src", "xw", "llm", "gold", "syn", "key", "pseud"}
    )


def test_fill_colors_and_unshaded_are_disjoint_and_inside_the_closed_set():
    assert set(pv.FILL_COLORS) <= pv.TOKENS
    assert pv.UNSHADED == frozenset({"", "src"})
    assert not (set(pv.FILL_COLORS) & pv.UNSHADED)


def test_provenance_row_classifies_by_column_not_by_value():
    row = {
        "Incident Number": "GC-478-20240502-1620",       # constructed -> key
        "Investigation leader - Name": "INV-a1b2c3",      # pseudonym -> pseud
        "What happened?  ": "a real narrative",           # verbatim -> src
        "Work Group": "",                                 # empty -> ""
    }
    cols = list(row)
    p = pv.provenance_row(row, cols)
    assert p["Incident Number"] == "key"
    assert p["Investigation leader - Name"] == "pseud"
    assert p["What happened?  "] == "src"
    assert p["Work Group"] == ""


def test_provenance_row_key_wins_even_for_values_with_no_hash_marker():
    # THE defect Phase 0 exists to fix: composite IDs like AREA-BLOCK-DATE-TIME
    # carry no INV-/SUP-/UNKEYED- substring but are still constructed.
    p = pv.provenance_row({"Incident Number": "EI-259-20230101-0900"},
                          ["Incident Number"])
    assert p["Incident Number"] == "key"


def test_export_and_convention_tests_import_from_here():
    # the three call sites must not re-hardcode the set. tests/ is not a
    # package (no __init__.py), so load the test modules by file path.
    import importlib.util
    from pathlib import Path

    import psm.export_e19 as ex
    assert ex.PROVENANCE_FILLS is pv.FILL_COLORS

    def load(name):
        path = Path(__file__).parent / f"{name}.py"
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    assert load("test_conventions").PROVENANCE_TOKENS == pv.TOKENS
    assert load("test_fill_outputs").TOKENS == pv.TOKENS
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_provenance_module.py -x -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'psm.provenance'`

- [ ] **Step 3: Implement the module**

```python
# src/psm/provenance.py
"""Single source of truth for provenance tokens, fill colours, and the
column->token classification rule.

Token semantics (About-sheet legend must match):
  ""     cell is empty
  src    verbatim from a BSEE source document
  xw     deterministic crosswalk of a BSEE category (schema/crosswalk.yaml)
  llm    assigned by a language model, never ground truth
  gold   human-labelled ground truth (never written by code)
  syn    synthetic: deterministic hash-generated filler, no real referent
  key    constructed join identifier. The whole Incident Number column is
         built by this repo (AREA-BLOCK-YYYYMMDD-HHMM composites, some with
         UNKEYED-/collision hash parts); BSEE publishes no incident id.
         Classified BY COLUMN, not by string pattern -- pattern-matching
         INV-/SUP-/UNKEYED- substrings undercounts by ~850 cells.
  pseud  salted pseudonym of a real value (INV-/SUP- name tokens: stable
         privacy transforms of real people's names -- de-amplification,
         not fabrication; epistemically distinct from both src and key).
"""
from __future__ import annotations

TOKENS = frozenset({"", "src", "xw", "llm", "gold", "syn", "key", "pseud"})

# aRGB without the alpha byte; openpyxl reports "00"+this on round-trip.
FILL_COLORS = {
    "xw": "DDEBF7",     # blue
    "llm": "FFF2CC",    # amber
    "syn": "EDEDED",    # grey
    "key": "E2EFDA",    # green
    "pseud": "E4DFEC",  # lilac
}

UNSHADED = frozenset({"", "src"})

KEY_COLUMNS = frozenset({"Incident Number"})
PSEUD_COLUMNS = frozenset({
    "Investigation leader - Name",
    "Investigation Acceptor/Approver (Owner) - Name",
})


def provenance_row(
    row: dict,
    cols: list[str],
    key_columns: frozenset[str] = KEY_COLUMNS,
    pseud_columns: frozenset[str] = PSEUD_COLUMNS,
) -> dict[str, str]:
    """Base provenance for a row copied from source: empty cells stay "",
    constructed-identifier columns are `key`, pseudonym columns `pseud`,
    everything else `src`. Callers overwrite specific cells afterwards
    (xw/llm/syn) exactly as crosswalk.py already does."""
    out = {}
    for c in cols:
        if not (row.get(c) or "").strip():
            out[c] = ""
        elif c in key_columns:
            out[c] = "key"
        elif c in pseud_columns:
            out[c] = "pseud"
        else:
            out[c] = "src"
    return out
```

- [ ] **Step 4: Wire the three existing sites to import it**

In `tests/test_conventions.py` replace the literal:
```python
from psm.provenance import TOKENS as PROVENANCE_TOKENS
```
In `tests/test_fill_outputs.py` replace the literal:
```python
from psm.provenance import TOKENS
```
In `src/psm/export_e19.py` replace the `PROVENANCE_FILLS = {...}` literal with:
```python
from psm.provenance import FILL_COLORS as PROVENANCE_FILLS
from psm.provenance import UNSHADED
```
and in `_write_sheet` replace the two-tuple allowlist check with `token not in UNSHADED`.

Note: `test_export_e19.py` may pin fill colours or the About legend; update
expectations there ONLY if the full suite shows failures caused by this
wiring (colours themselves did not change for xw/llm/syn).

- [ ] **Step 5: Run the new test file, then the full suite**

Run: `uv run pytest tests/test_provenance_module.py -q && uv run pytest -q`
Expected: all pass. (`test_fill_outputs` runs against the existing filled/
CSVs which contain no key/pseud tokens yet — widening the set breaks nothing.)

- [ ] **Step 6: Mutation-check the consistency test**

Temporarily edit `FILL_COLORS` so its `"key"` entry is spelled `"kee"` — `test_fill_colors_and_unshaded_are_disjoint_and_inside_the_closed_set` must fail. Undo that edit. Temporarily add a hardcoded `PROVENANCE_FILLS = {"xw": "DDEBF7"}` line after the import in export_e19 — `test_export_and_convention_tests_import_from_here` must fail. Undo that edit. Re-run the tests green, record both observed failures in the task report.

- [ ] **Step 7: Commit**

```bash
git add src/psm/provenance.py tests/test_provenance_module.py tests/test_conventions.py tests/test_fill_outputs.py src/psm/export_e19.py
git commit -m "feat: psm.provenance single source of truth; add key/pseud tokens"
```

---

### Task 2: Fix crosswalk provenance at the origin; regenerate enriched/ and filled/

**Files:**
- Modify: `src/psm/crosswalk.py` (the two identical dict-comprehension provenance lines at ~238 and ~424)
- Test: `tests/test_fill_outputs.py` (add stale-layer + column-classification tests)
- Regenerated & committed: provenance CSVs under `data/processed/e19/enriched/` and `data/processed/e19/filled/`

**Interfaces:**
- Consumes: `psm.provenance.provenance_row` (Task 1).
- Produces: enriched/ and filled/ provenance CSVs where every non-empty `Incident Number` cell is `key` and every non-empty INV-/SUP- name cell is `pseud`. Tasks 3+ rely on these being committed.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_fill_outputs.py`)

```python
from psm.provenance import PSEUD_COLUMNS


class TestConstructedIdentifierProvenance:
    @pytest.mark.parametrize("table,prov", [
        ("incidents.csv", "provenance.csv"),
        ("causes.csv", "causes_provenance.csv"),
    ])
    def test_incident_number_is_key_wherever_populated(self, table, prov):
        rows = _rows(FILLED / table)
        provs = _rows(FILLED / prov)
        for r, p in zip(rows, provs):
            if (r.get("Incident Number") or "").strip():
                assert p["Incident Number"] == "key", r["Incident Number"]

    def test_pseudonym_columns_are_pseud_wherever_populated(self):
        rows = _rows(FILLED / "incidents.csv")
        provs = _rows(FILLED / "provenance.csv")
        for col in PSEUD_COLUMNS:
            for r, p in zip(rows, provs):
                if (r.get(col) or "").strip():
                    assert p[col] == "pseud", (col, r[col])

    def test_filled_never_lags_enriched_on_key_or_pseud(self):
        # the stale-layer failure mode: enriched fixed, filled re-exported stale
        for name in ("provenance.csv", "causes_provenance.csv"):
            enr = _rows(ENRICHED / name)
            fil = _rows(FILLED / name)
            for e, f in zip(enr, fil):
                for col in set(e) & set(f):
                    if e[col] in ("key", "pseud"):
                        assert f[col] == e[col], col
```

- [ ] **Step 2: Run to verify they fail against current data**

Run: `uv run pytest tests/test_fill_outputs.py -q -k Constructed`
Expected: FAIL — current provenance says `src` for these cells.

- [ ] **Step 3: Fix both crosswalk loops**

In `src/psm/crosswalk.py`, add `from psm.provenance import provenance_row` and replace BOTH occurrences (in `enrich_causes` and in the incidents loop) of
```python
        p = {c: ("src" if (row.get(c) or "").strip() else "") for c in cols}
```
with
```python
        p = provenance_row(row, cols)
```

- [ ] **Step 4: Regenerate the layers IN ORDER** (export reads `filled/`; an enriched-only fix ships nothing)

Run:
```bash
uv run python -m psm.crosswalk
uv run python -m psm.fill
```
Then: `uv run pytest tests/test_fill_outputs.py tests/test_ledger.py -q`
Expected: PASS, including the new tests. If `psm.crosswalk` has a different entry point, check `grep -n "__main__" src/psm/crosswalk.py` and `docs/findings.md` for the documented invocation; do not guess flags.

- [ ] **Step 5: Verify only provenance changed, not values**

Run: `git diff --stat data/processed/e19/`
Expected: only `provenance.csv` / `causes_provenance.csv` files change (in both enriched/ and filled/). If a VALUE file changed, STOP and report — the fix must be provenance-only.

- [ ] **Step 6: Mutation-check the stale-layer test (no git involved)**

Apply the mutation with a script — flip one `key` cell in the FILLED provenance back to `src`:
```bash
uv run python -c "
import csv
from pathlib import Path
p = Path('data/processed/e19/filled/provenance.csv')
rows = list(csv.DictReader(p.open(encoding='utf-8', newline='')))
assert rows[0]['Incident Number'] == 'key'
rows[0]['Incident Number'] = 'src'
with p.open('w', encoding='utf-8', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader(); w.writerows(rows)
print('mutated row 1')
"
uv run pytest tests/test_fill_outputs.py -q -k lags
```
Expected: FAIL (`test_filled_never_lags_enriched_on_key_or_pseud`). Undo the mutation by re-running the generator: `uv run python -m psm.fill`, then re-run the test — PASS. Record the observed failure in the task report.

- [ ] **Step 7: Commit (code + regenerated data together)**

```bash
git add src/psm/crosswalk.py tests/test_fill_outputs.py data/processed/e19/enriched data/processed/e19/filled
git commit -m "fix: classify constructed ids as key and pseudonyms as pseud at the crosswalk origin"
```

---

### Task 3: About sheet honesty + re-export the repaired workbook

**Files:**
- Modify: `src/psm/export_e19.py` (`ABOUT_LINES`)
- Test: `tests/test_export_e19.py`

**Interfaces:**
- Consumes: Task 1's FILL_COLORS/UNSHADED wiring; Task 2's regenerated filled/.
- Produces: `deliverables/e19_filled.xlsx` re-exported with key/pseud shading and corrected legend. (RELAY refresh is OUT OF SCOPE — a later human step.)

- [ ] **Step 1: Write the failing test** (append to `tests/test_export_e19.py`, importing `ABOUT_LINES` the way that file already does)

```python
def test_about_legend_covers_key_and_pseud_and_drops_the_stale_exception():
    text = "\n".join(ABOUT_LINES)
    assert "green" in text and "constructed" in text          # key legend line
    assert "lilac" in text and "pseudonym" in text            # pseud legend line
    # the superseded paragraph claimed Incident Number was the lone exception
    assert "Incident Number is unshaded" not in text
    # new caveat: Cause type is ordinal position, not analysis
    assert "Cause type" in text and "position" in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_export_e19.py -q -k about_legend`
Expected: FAIL.

- [ ] **Step 3: Edit ABOUT_LINES**

Add after the grey legend line:
```python
    "  green      - constructed identifier: BSEE publishes no incident id,",
    "               so this repo builds the key (area-block-date-time, some",
    "               with content-hash parts). Consistent, but corresponds to",
    "               no source field.",
    "  lilac      - salted pseudonym of a real name (INV-/SUP- tokens).",
    "               Same person, same token, corpus-wide. De-amplification",
    "               of public documents, not fabrication.",
```
DELETE the four-line "Exception: Incident Number is unshaded..." paragraph (superseded: the column is now shaded green). ADD a paragraph before the sanitiser note:
```python
    "",
    "The Cause type column reflects ordinal position in the source list",
    "(cause #1 is always 'Immediate'), not causal analysis. Do not read",
    "root-cause depth from it.",
```

- [ ] **Step 4: Re-export and run the suite**

Run: `uv run python -m psm.export_e19 && uv run pytest tests/test_export_e19.py -q`
Expected: PASS; export prints the sanitised-cell count as before.

- [ ] **Step 5: Spot-verify shading end-to-end**

```bash
uv run python -c "
from openpyxl import load_workbook
wb = load_workbook('deliverables/e19_filled.xlsx')
ws = wb['Incidents']
hdr = [c.value for c in ws[1]]
i = hdr.index('Incident Number') + 1
fills = {ws.cell(row=r, column=i).fill.start_color.rgb for r in range(2, 30)}
print(fills)  # expect only 00E2EFDA
"
```
Expected: `{'00E2EFDA'}`.

- [ ] **Step 6: Commit**

```bash
git add src/psm/export_e19.py tests/test_export_e19.py
git commit -m "fix: About legend gains key/pseud, drops stale exception, adds Cause-type caveat"
```

---

### Task 4: Committed integer quantile tables + runtime lookup

**Files:**
- Create: `scripts/build_quantile_tables.py` (dev-only; the ONLY file allowed to import scipy)
- Create: `src/psm/quantiles.py`
- Create + commit: `schema/quantiles/lognormal_m*_s*.csv` (9 tables)
- Test: `tests/test_quantiles.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `psm.quantiles.load_table(median_days: int, sigma: float) -> tuple[int, ...]` (1024 ints), `draw_days(key: str, median_days: int, sigma: float) -> int`, `analytic_overdue_rate(median_days: int, sigma: float, agreed_min: int, agreed_max: int) -> float`, `CONFIGS: tuple[tuple[int, float], ...]`. Tasks 6-10 draw every lognormal through `draw_days`.

The 9 (median_days, sigma) configs — the union of every scenario knob in the spec:
`(2, 0.6), (7, 0.5), (10, 0.8), (21, 0.6), (30, 0.7), (40, 0.5), (45, 0.6), (60, 0.6), (130, 0.8)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quantiles.py
"""Lognormal shapes come from committed 1024-bucket integer tables so the
runtime engine needs no scipy and is byte-identical cross-platform."""
import pytest

from psm import quantiles as q


ALL_CONFIGS = [(2, 0.6), (7, 0.5), (10, 0.8), (21, 0.6), (30, 0.7),
               (40, 0.5), (45, 0.6), (60, 0.6), (130, 0.8)]


def test_configs_constant_matches_the_spec_union():
    assert set(q.CONFIGS) == set(ALL_CONFIGS)


@pytest.mark.parametrize("median,sigma", ALL_CONFIGS)
def test_table_shape_monotone_and_nonnegative(median, sigma):
    t = q.load_table(median, sigma)
    assert len(t) == 1024
    assert all(isinstance(v, int) for v in t)
    assert all(v >= 0 for v in t)
    assert all(a <= b for a, b in zip(t, t[1:]))  # ppf is monotone


@pytest.mark.parametrize("median,sigma", ALL_CONFIGS)
def test_median_bucket_lands_on_the_configured_median(median, sigma):
    t = q.load_table(median, sigma)
    mid = (t[511] + t[512]) / 2
    assert abs(mid - median) <= max(1, 0.1 * median)


def test_draw_days_is_deterministic_and_reads_the_table():
    a = q.draw_days("northstar|X|closeout|salt", 45, 0.6)
    b = q.draw_days("northstar|X|closeout|salt", 45, 0.6)
    assert a == b
    assert a in q.load_table(45, 0.6)


def test_analytic_overdue_orders_slow_above_fast():
    fast = q.analytic_overdue_rate(45, 0.6, 30, 90)    # NorthStar shape
    slow = q.analytic_overdue_rate(130, 0.8, 30, 90)   # Meridian shape
    assert 0.0 < fast < slow < 1.0
    assert slow > 3 * fast  # the planted closeout decay is visible analytically
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_quantiles.py -q`
Expected: FAIL — `psm.quantiles` does not exist.

- [ ] **Step 3: Implement the runtime module**

```python
# src/psm/quantiles.py
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
    uniform integer agreed offset — iterated exactly (1024 x span), no
    sampling. Stored in each manifest; the overdue KPI must land near it."""
    t = load_table(median_days, sigma)
    span = range(agreed_min, agreed_max + 1)
    hits = sum(1 for v in t for o in span if v > o)
    return hits / (len(t) * len(span))
```

- [ ] **Step 4: Implement the build script and generate the tables**

```python
# scripts/build_quantile_tables.py
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
```

Run: `uv run --with scipy python scripts/build_quantile_tables.py`
Expected: 9 files under `schema/quantiles/`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_quantiles.py -q`
Expected: PASS (10 parametrized + 3 others).

- [ ] **Step 6: Mutation-check**

Temporarily swap two adjacent values in `schema/quantiles/lognormal_m45_s60.csv` (edit the file by hand or with a two-line python script that swaps lines 500 and 501) — `test_table_shape_monotone_and_nonnegative[45-0.6]` must fail. Undo by re-running the build script (byte-identical output is the point). Record the observed failure.

- [ ] **Step 7: Commit**

```bash
git add scripts/build_quantile_tables.py src/psm/quantiles.py schema/quantiles tests/test_quantiles.py
git commit -m "feat: committed integer quantile tables; scipy confined to dev build script"
```

---

### Task 5: Action template registry + exact match-back

**Files:**
- Create: `schema/action_templates.yaml`
- Create: `src/psm/templates.py`
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: `data/processed/e19/real_only/recommendations.csv` (read-only, as the style source for authoring).
- Produces: `psm.templates.TAGS = ("elimination", "engineering", "admin", "ppe")`, `load_templates() -> tuple[dict, ...]` (each `{"id": str, "tag": str, "text": str}`), `templates_by_tag() -> dict[str, tuple[dict, ...]]`, `classify_action(text: str) -> str` (exact-text lookup, raises `KeyError` on unknown text). Task 9 picks templates; Task 11's admin_ppe_share KPI calls `classify_action`.

Design decision (locked): template text is used VERBATIM in registers — no
placeholder slots. Match-back is an exact dict lookup, so the KPI needs no
classifier of any kind. Repetition across incidents is realistic corporate
boilerplate and is disclosed on the About sheet (Task 14).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_templates.py
"""The action template registry is the ONLY source of Recommendation
Description text in company registers, and the controls-hierarchy KPI reads
tags by exact match-back -- so the registry must be closed, clean of
regulator voice, and collision-free."""
import re

from psm import templates as tp

BANNED = re.compile(r"\b(MMS|OSM|BSEE|District|Regional Office)\b", re.I)


def test_registry_is_large_and_balanced():
    ts = tp.load_templates()
    assert len(ts) >= 40
    by = tp.templates_by_tag()
    assert set(by) == set(tp.TAGS)
    for tag in tp.TAGS:
        assert len(by[tag]) >= 8, f"{tag}: need >=8 templates"


def test_no_regulator_voice_anywhere():
    for t in tp.load_templates():
        assert not BANNED.search(t["text"]), t["id"]


def test_texts_and_ids_are_unique_and_match_back_round_trips():
    ts = tp.load_templates()
    assert len({t["id"] for t in ts}) == len(ts)
    assert len({t["text"] for t in ts}) == len(ts)
    for t in ts:
        assert tp.classify_action(t["text"]) == t["tag"]


def test_classify_action_raises_on_unknown_text():
    import pytest
    with pytest.raises(KeyError):
        tp.classify_action("this text is not in the registry")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_templates.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Author the registry**

`schema/action_templates.yaml` format:

```yaml
# Recommendation-text registry for synthetic company registers.
# Authored by adapting the operator-voice subset of the 601 substantive real
# recommendations in data/processed/e19/real_only/recommendations.csv
# (style only -- no sentence copied verbatim; no regulator voice: never
# MMS/OSM/BSEE/District/Regional Office). Tag = controls-hierarchy level.
templates:
  - id: elim-01
    tag: elimination
    text: Remove the temporary bypass line and return the system to its designed flow path.
  - id: elim-02
    tag: elimination
    text: Eliminate the manual draining step by hard-piping the drain to the closed drain system.
  - id: eng-01
    tag: engineering
    text: Install a secondary mechanical stop on the crane boom to prevent travel beyond the rated envelope.
  - id: eng-02
    tag: engineering
    text: Replace the relief valve with one sized and set for current operating conditions, and verify the calculation.
  - id: admin-01
    tag: admin
    text: Revise the pre-job safety meeting checklist to require verification of all isolation points before work begins.
  - id: admin-02
    tag: admin
    text: Retrain all operators on the correct lockout and tagout sequence for this equipment and document completion.
  - id: ppe-01
    tag: ppe
    text: Require cut-resistant gloves for all hand-tool work in this area.
  - id: ppe-02
    tag: ppe
    text: Issue face shields in addition to safety glasses for all grinding operations.
```

Author AT LEAST 40 entries total, AT LEAST 8 per tag, continuing the id
scheme (`elim-NN`, `eng-NN`, `admin-NN`, `ppe-NN`). Source material: read
`data/processed/e19/real_only/recommendations.csv` and adapt the topics you
find (crane ops, dropped objects, line handling, pressure isolation, hot
work, lifting gear inspection, valve maintenance, slips and falls, PPE for
grinding/chemical handling) into operator-voice imperative sentences. Rules:
one sentence each; imperative mood; concrete equipment nouns; no company or
person names; no dates; nothing matching the banned-token regex; every text
unique.

```python
# src/psm/templates.py
"""Action-template registry loader + exact match-back classifier."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "schema" / "action_templates.yaml"

TAGS = ("elimination", "engineering", "admin", "ppe")


@lru_cache(maxsize=None)
def load_templates() -> tuple[dict, ...]:
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    ts = tuple(data["templates"])
    for t in ts:
        assert set(t) == {"id", "tag", "text"}, t
        assert t["tag"] in TAGS, t["id"]
    return ts


@lru_cache(maxsize=None)
def templates_by_tag() -> dict[str, tuple[dict, ...]]:
    out: dict[str, list[dict]] = {tag: [] for tag in TAGS}
    for t in load_templates():
        out[t["tag"]].append(t)
    return {k: tuple(v) for k, v in out.items()}


@lru_cache(maxsize=None)
def _text_to_tag() -> dict[str, str]:
    return {t["text"]: t["tag"] for t in load_templates()}


def classify_action(text: str) -> str:
    """Exact registry lookup. KeyError on unknown text is a FEATURE: company
    registers must contain no recommendation text outside the registry."""
    return _text_to_tag()[text]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_templates.py -q`
Expected: PASS.

- [ ] **Step 5: Mutation-check**

Temporarily change one template's text to include the word `District` — the banned-voice test must fail. Reverse that edit. Temporarily duplicate one template's text onto another id — the uniqueness test must fail. Reverse it. Record both observed failures.

- [ ] **Step 6: Commit**

```bash
git add schema/action_templates.yaml src/psm/templates.py tests/test_templates.py
git commit -m "feat: action template registry with exact match-back (no classifier)"
```

---

### Task 6: Scenario configs, donor partitions, IDs, date anchors, prose-date shifting

**Files:**
- Create: `scenarios/northstar.yaml`, `scenarios/meridian.yaml`, `scenarios/coastal.yaml`, `scenarios/meridian_nt.yaml`
- Create: `src/psm/scenario.py` (foundations — later tasks extend this module)
- Test: `tests/test_scenario_foundations.py`

**Interfaces:**
- Consumes: `psm.quantiles.draw_days` (Task 4); `data/processed/e19/real_only/incidents.csv` (donor ids).
- Produces (used by Tasks 7-14): `SALT`, `WINDOW_START`, `WINDOW_END`, `WINDOW_DAYS = 1826`, `COMPANY_ORDER = ["northstar", "meridian", "coastal"]`, `PREFIX`, `WORK_GROUP_WEIGHTS`, `_hash(key: str) -> int`, `load_scenario(name: str) -> dict`, `scenario_sha256(name: str) -> str`, `donor_ids() -> list[str]`, `donor_partition(company: str) -> list[str]`, `scenario_incident_number(company: str, donor_id: str, clone_index: int = 0) -> str`, `base_incident_date(company: str, sid: str) -> date`, `pick_weighted(key: str, pairs: list[tuple[str, int]]) -> str`, `shift_prose_dates(text: str, delta_days: int) -> str`, `find_prose_dates(text: str) -> list[date]`, `syn_person(key: str) -> tuple[str, str]`.

- [ ] **Step 1: Write the four scenario YAMLs** (values verbatim from the spec — any drift is a defect)

`scenarios/northstar.yaml`:
```yaml
report_lag:      {median_days: 2,  sigma: 0.6}
investigation:   {skip_rate: 0.02, root_cause_prob: 0.85, duration_median_days: 21, duration_sigma: 0.6}
closeout:        {median_days: 45, sigma: 0.6}
agreed_offset:   {min_days: 30, max_days: 90}
recurrence:      {planted_pairs: 0, window_days: 365}
controls_mix:    {elimination: 0.05, engineering: 0.50, admin: 0.35, ppe: 0.10}
data_discipline: {owner_assigned_rate: 0.98, extra_hs_blank_rate: 0.00}
```

`scenarios/meridian.yaml`:
```yaml
report_lag:      {median_days: 10, sigma: 0.8}          # planted
investigation:   {skip_rate: 0.03, root_cause_prob: 0.80, duration_median_days: 30, duration_sigma: 0.7}
closeout:        {median_days: 130, sigma: 0.8}         # planted
agreed_offset:   {min_days: 30, max_days: 90}
recurrence:      {planted_pairs: 8, window_days: 365, work_group: Maintenance}
controls_mix:    {elimination: 0.05, engineering: 0.50, admin: 0.35, ppe: 0.10}  # = NorthStar (negative control)
data_discipline: {owner_assigned_rate: 0.95, extra_hs_blank_rate: 0.00}
```

`scenarios/coastal.yaml`:
```yaml
report_lag:      {median_days: 2,  sigma: 0.6}          # = NorthStar (negative control)
investigation:   {skip_rate: 0.20, root_cause_prob: 0.25, duration_median_days: 7, duration_sigma: 0.5}  # planted
closeout:        {median_days: 40, sigma: 0.5}          # fast on paper
agreed_offset:   {min_days: 30, max_days: 90}
recurrence:      {planted_pairs: 6, window_days: 365}   # from unaddressed causes
controls_mix:    {elimination: 0.00, engineering: 0.15, admin: 0.60, ppe: 0.25}  # planted
data_discipline: {owner_assigned_rate: 0.60, extra_hs_blank_rate: 0.25}  # planted
```

`scenarios/meridian_nt.yaml` (TEST-ONLY, never exported, never written under `data/companies/`):
```yaml
# Near-threshold sensitivity variant: NorthStar in every respect except a
# small closeout decay. Exists only to prove the KPI margins have
# resolution; generated inside tests, never committed as data.
report_lag:      {median_days: 2,  sigma: 0.6}
investigation:   {skip_rate: 0.02, root_cause_prob: 0.85, duration_median_days: 21, duration_sigma: 0.6}
closeout:        {median_days: 60, sigma: 0.6}
agreed_offset:   {min_days: 30, max_days: 90}
recurrence:      {planted_pairs: 0, window_days: 365}
controls_mix:    {elimination: 0.05, engineering: 0.50, admin: 0.35, ppe: 0.10}
data_discipline: {owner_assigned_rate: 0.98, extra_hs_blank_rate: 0.00}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_scenario_foundations.py
"""Deterministic plumbing for the scenario engine: disjoint donor
partitions, non-leaking ids, in-window anchors, format-preserving prose
date shifting."""
from datetime import date

from psm import scenario as sc


def test_partitions_are_disjoint_exact_150_and_deterministic():
    parts = {c: sc.donor_partition(c) for c in sc.COMPANY_ORDER}
    all_ids = set(sc.donor_ids())
    assert len(all_ids) == 1214
    seen = set()
    for c in sc.COMPANY_ORDER:
        assert len(parts[c]) == 150
        assert set(parts[c]) <= all_ids
        assert not (set(parts[c]) & seen)
        seen |= set(parts[c])
    assert parts["northstar"] == sc.donor_partition("northstar")  # stable
    # the test-only variant reuses northstar's slice (it is never exported,
    # so exported-company disjointness is preserved)
    assert sc.donor_partition("meridian_nt") == parts["northstar"]


def test_scenario_incident_number_never_leaks_the_donor_date():
    sid = sc.scenario_incident_number("northstar", "GC-478-20240502-1620")
    assert sid.startswith("NS-")
    assert "20240502" not in sid and "GC-478" not in sid
    assert sid == sc.scenario_incident_number("northstar", "GC-478-20240502-1620")


def test_base_incident_date_is_inside_the_window():
    for donor in sc.donor_partition("northstar")[:25]:
        sid = sc.scenario_incident_number("northstar", donor)
        d = sc.base_incident_date("northstar", sid)
        assert sc.WINDOW_START <= d <= sc.WINDOW_END


def test_pick_weighted_is_exhaustive_and_deterministic():
    got = {sc.pick_weighted(f"k{i}", sc.WORK_GROUP_WEIGHTS) for i in range(500)}
    assert got == {w for w, _ in sc.WORK_GROUP_WEIGHTS}


def test_load_scenario_has_all_knob_groups():
    for name in ("northstar", "meridian", "coastal", "meridian_nt"):
        cfg = sc.load_scenario(name)
        assert set(cfg) >= {"report_lag", "investigation", "closeout",
                            "agreed_offset", "recurrence", "controls_mix",
                            "data_discipline"}


def test_shift_prose_dates_preserves_format_and_moves_all_forms():
    text = ("On May 2, 2024 the crane failed. Reported 05/02/2024; "
            "memo of 17-OCT-2020 refers; ISO 2024-05-02; also 2 May 2024. "
            "Not a date: 13/45/2020.")
    out = sc.shift_prose_dates(text, 10)
    assert "May 12, 2024" in out
    assert "5/12/2024" in out
    assert "27-OCT-2020" in out
    assert "2024-05-12" in out
    assert "12 May 2024" in out
    assert "13/45/2020" in out          # unparseable stays untouched
    assert "May 2, 2024" not in out


def test_shift_preserves_uppercase_month_names():
    out = sc.shift_prose_dates("OCCURRED ON OCTOBER 17, 2020 DURING LIFT", 30)
    assert "NOVEMBER 16, 2020" in out


def test_find_prose_dates_reports_every_parseable_date():
    got = sc.find_prose_dates("May 2, 2024 and 17-OCT-2020 and junk 13/45/2020")
    assert date(2024, 5, 2) in got and date(2020, 10, 17) in got
    assert len(got) == 2


def test_syn_person_is_deterministic_syn_prefixed():
    name, pos = sc.syn_person("northstar|X|leader")
    assert name.startswith("SYN-")
    assert (name, pos) == sc.syn_person("northstar|X|leader")
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_scenario_foundations.py -q`
Expected: FAIL — `psm.scenario` does not exist.

- [ ] **Step 4: Implement the foundations**

```python
# src/psm/scenario.py
"""Deterministic scenario-register engine: samples disjoint donor partitions
from the real BSEE corpus and generates complete 4-table E19 registers per
synthetic company, shaped by scenarios/<name>.yaml process-rate knobs.

Every draw: int(sha256(f"{key}|{SALT}")) walked in sorted-key order.
No random, no wall clock, no scipy (lognormals via psm.quantiles tables)."""
from __future__ import annotations

import csv
import hashlib
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import yaml

from psm.quantiles import draw_days

REPO = Path(__file__).resolve().parents[2]
REAL = REPO / "data" / "processed" / "e19" / "real_only"
SCENARIO_DIR = REPO / "scenarios"
OUT_ROOT = REPO / "data" / "companies"

SALT = "e19-scenario-v1"
PARTITION_SALT = "e19-scenario-partition-v1"

WINDOW_START = date(2021, 1, 1)
WINDOW_END = date(2025, 12, 31)
WINDOW_DAYS = (WINDOW_END - WINDOW_START).days + 1  # 1826 (2024 is a leap year)

COMPANY_ORDER = ["northstar", "meridian", "coastal"]
PREFIX = {"northstar": "NS", "meridian": "MR", "coastal": "CP",
          "meridian_nt": "MNT"}

# ONE shared distribution for all companies (company-specific weights were
# unfalsifiable -- spec decision). Integer weights sum to 100.
WORK_GROUP_WEIGHTS = [
    ("Production Operations", 30), ("Maintenance", 25), ("Drilling", 15),
    ("Well Services", 12), ("Construction", 10), ("Marine & Logistics", 8),
]

POSITIONS = ["Operations Superintendent", "HSE Advisor",
             "Maintenance Supervisor", "Facility Engineer",
             "Production Foreman", "Marine Coordinator"]


def _hash(key: str) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)


@lru_cache(maxsize=None)
def load_scenario(name: str) -> dict:
    cfg = yaml.safe_load((SCENARIO_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    required = {"report_lag", "investigation", "closeout", "agreed_offset",
                "recurrence", "controls_mix", "data_discipline"}
    missing = required - set(cfg)
    assert not missing, f"{name}: missing knob groups {missing}"
    return cfg


def scenario_sha256(name: str) -> str:
    return hashlib.sha256(
        (SCENARIO_DIR / f"{name}.yaml").read_bytes()).hexdigest()


@lru_cache(maxsize=None)
def donor_ids() -> tuple[str, ...]:
    with (REAL / "incidents.csv").open(encoding="utf-8", newline="") as fh:
        return tuple(r["Incident Number"] for r in csv.DictReader(fh))


def donor_partition(company: str) -> list[str]:
    """Hash-ranked disjoint 150-slices in fixed COMPANY_ORDER. The test-only
    meridian_nt variant reuses northstar's slice."""
    base = "northstar" if company == "meridian_nt" else company
    ranked = sorted(sorted(donor_ids()),
                    key=lambda i: _hash(f"{i}|{PARTITION_SALT}"))
    k = COMPANY_ORDER.index(base)
    return ranked[k * 150:(k + 1) * 150]


def scenario_incident_number(company: str, donor_id: str,
                             clone_index: int = 0) -> str:
    """Fresh mint per row -- donor ids embed real dates and must not leak.
    Provenance token: key."""
    h = hashlib.sha256(
        f"{company}|{donor_id}|{clone_index}|{SALT}".encode("utf-8")
    ).hexdigest()[:10].upper()
    return f"{PREFIX[company]}-{h}"


def base_incident_date(company: str, sid: str) -> date:
    return WINDOW_START + timedelta(
        days=_hash(f"{company}|{sid}|incident_date|{SALT}") % WINDOW_DAYS)


def pick_weighted(key: str, pairs: list[tuple[str, int]]) -> str:
    total = sum(w for _, w in pairs)
    r = _hash(key) % total
    for value, w in pairs:
        if r < w:
            return value
        r -= w
    raise AssertionError("unreachable")


def rate_hit(key: str, rate: float) -> bool:
    """Deterministic Bernoulli: exact to 1e-6 resolution."""
    return _hash(key) % 1_000_000 < round(rate * 1_000_000)


def syn_person(key: str) -> tuple[str, str]:
    name = f"SYN-{hashlib.sha256((key + '|' + SALT).encode()).hexdigest()[:6]}"
    return name, POSITIONS[_hash(f"{key}|position|{SALT}") % len(POSITIONS)]


# ---- prose-date shifting (format-preserving; 571/1213 donor narratives
# ---- embed dates that must move with the structured rebase) -------------

_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")
_MON3 = tuple(m[:3].upper() for m in _MONTHS)
_MONTH_ALT = "|".join(_MONTHS)


def _month_out(idx: int, like: str) -> str:
    name = _MONTHS[idx]
    return name.upper() if like.isupper() else name


def _p(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


_DATE_PATTERNS = [
    # May 2, 2024
    (_p(rf"\b({_MONTH_ALT}) (\d{{1,2}}), (\d{{4}})\b"),
     lambda m: (int(m.group(3)),
                [x.lower() for x in _MONTHS].index(m.group(1).lower()) + 1,
                int(m.group(2))),
     lambda d, m: f"{_month_out(d.month - 1, m.group(1))} {d.day}, {d.year}"),
    # 2 May 2024
    (_p(rf"\b(\d{{1,2}}) ({_MONTH_ALT}) (\d{{4}})\b"),
     lambda m: (int(m.group(3)),
                [x.lower() for x in _MONTHS].index(m.group(2).lower()) + 1,
                int(m.group(1))),
     lambda d, m: f"{d.day} {_month_out(d.month - 1, m.group(2))} {d.year}"),
    # 17-OCT-2020
    (_p(rf"\b(\d{{1,2}})-({'|'.join(_MON3)})-(\d{{4}})\b"),
     lambda m: (int(m.group(3)),
                [x.lower() for x in _MON3].index(m.group(2).lower()) + 1,
                int(m.group(1))),
     lambda d, m: f"{d.day:02d}-{_MON3[d.month - 1]}-{d.year}"),
    # 05/02/2024 (US month/day/year)
    (_p(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
     lambda m: (int(m.group(3)), int(m.group(1)), int(m.group(2))),
     lambda d, m: f"{d.month}/{d.day}/{d.year}"),
    # 2024-05-02
    (_p(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
     lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3))),
     lambda d, m: f"{d.year}-{d.month:02d}-{d.day:02d}"),
]


def shift_prose_dates(text: str, delta_days: int) -> str:
    for pat, extract, fmt in _DATE_PATTERNS:
        def repl(m, extract=extract, fmt=fmt):
            try:
                y, mo, dy = extract(m)
                d = date(y, mo, dy) + timedelta(days=delta_days)
            except ValueError:      # 13/45/2020 etc: not a date, leave it
                return m.group(0)
            return fmt(d, m)
        text = pat.sub(repl, text)
    return text


def find_prose_dates(text: str) -> list[date]:
    out = []
    for pat, extract, _ in _DATE_PATTERNS:
        for m in pat.finditer(text):
            try:
                y, mo, dy = extract(m)
                out.append(date(y, mo, dy))
            except ValueError:
                pass
    return out
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_scenario_foundations.py -q`
Expected: PASS. Known subtlety if the shift test fails on `05/02/2024`: a
date already rewritten by an earlier pattern must not be re-matched by a
later one — the ISO pattern requires exactly `\d{4}-\d{2}-\d{2}` and the
slash pattern's output (`5/12/2024`) cannot match it, so pattern order as
given is safe; do not reorder the list.

- [ ] **Step 6: Mutation-check**

Temporarily change the partition slice arithmetic from `k * 150` to `k * 149` — the disjointness/coverage test must fail. Reverse the edit. Temporarily make `scenario_incident_number` return `f"{PREFIX[company]}-{donor_id}"` — the leak test must fail. Reverse it. Record both failures.

- [ ] **Step 7: Commit**

```bash
git add scenarios src/psm/scenario.py tests/test_scenario_foundations.py
git commit -m "feat: scenario configs, disjoint donor partitions, id/date/prose plumbing"
```

---

### Task 7: Per-incident plans + the Incidents table builder

**Files:**
- Modify: `src/psm/scenario.py` (extend — everything from Task 6 stays)
- Test: `tests/test_scenario_incidents.py`

**Interfaces:**
- Consumes: Task 6 foundations, `psm.quantiles.draw_days`, `psm.templates.templates_by_tag` (tags only).
- Produces: `IncidentPlan` dataclass (fields below), `make_plan(company: str, cfg: dict, donor_id: str) -> IncidentPlan`, `incident_fieldnames() -> list[str]`, `donor_incidents() -> dict[str, dict]`, `donor_delta(plan: IncidentPlan) -> int`, `build_incident_row(plan: IncidentPlan, donor_row: dict) -> tuple[dict, dict]` (value row, provenance row). Tasks 8-10 consume plans; Task 9 mutates `doi`, `work_group`, `element_override` during recurrence planting.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scenario_incidents.py
"""The incidents builder: exact donor headers, closed provenance subset
{"", src, syn, key}, skip semantics, narrative dates move with the rebase."""
from datetime import date

from psm import scenario as sc


CFG = sc.load_scenario("northstar")


def _plan(donor_id):
    return sc.make_plan("northstar", CFG, donor_id)


def test_fieldnames_are_the_donor_headers_byte_exact():
    cols = sc.incident_fieldnames()
    assert cols[0] == "Incident Number"
    assert "What happened?  " in cols                 # two trailing spaces
    assert "Incident Classificatioin" in cols         # sic, from source
    assert "Investigation Acceptor/Approver (Owner)- Position" in cols  # no space before dash, sic


def test_row_covers_every_column_and_provenance_is_closed_subset():
    donors = sc.donor_partition("northstar")[:20]
    cols = set(sc.incident_fieldnames())
    for d in donors:
        p = _plan(d)
        row, prov = sc.build_incident_row(p, sc.donor_incidents()[d])
        assert set(row) == cols and set(prov) == cols
        assert set(prov.values()) <= {"", "src", "syn", "key"}
        assert prov["Incident Number"] == "key"
        for c in cols:
            assert (prov[c] == "") == (not row[c].strip()), c


def test_date_chain_orders_and_derives_from_the_plan():
    d = sc.donor_partition("northstar")[0]
    p = _plan(d)
    row, _ = sc.build_incident_row(p, sc.donor_incidents()[d])
    doi = date.fromisoformat(row["Date of Incident"])
    rep = date.fromisoformat(row["Date of Report"])
    assert sc.WINDOW_START <= doi <= sc.WINDOW_END
    assert (rep - doi).days == p.report_lag
    if not p.skipped:
        app = date.fromisoformat(row["Approval Date"])
        assert (app - rep).days == p.invest_days


def test_skipped_incident_has_no_leader_no_approval():
    donors = sc.donor_partition("coastal")           # skip_rate 0.20: hits exist
    ccfg = sc.load_scenario("coastal")
    skipped = [d for d in donors
               if sc.make_plan("coastal", ccfg, d).skipped]
    assert skipped, "coastal partition produced zero skips -- investigate"
    p = sc.make_plan("coastal", ccfg, skipped[0])
    row, prov = sc.build_incident_row(p, sc.donor_incidents()[skipped[0]])
    assert row["Investigation leader - Name"] == ""
    assert row["Approval Date"] == ""
    assert row["Close out Date"] == ""


def test_narratives_are_shifted_by_the_rebase_delta():
    donor_row = {
        "Incident Number": "GC-478-20240502-1620",
        "Date of Incident": "2024-05-02",
        "What happened?  ": "On May 2, 2024 the crane boom contacted the rail.",
    }
    p = _plan("GC-478-20240502-1620")
    row, prov = sc.build_incident_row(p, donor_row)
    delta = sc.donor_delta(p)
    shifted = date(2024, 5, 2) + __import__("datetime").timedelta(days=delta)
    assert f"{shifted.strftime('%B')} {shifted.day}, {shifted.year}" in row["What happened?  "]
    assert prov["What happened?  "] == "src"          # shifted text stays src; About discloses


def test_anchor_clamp_reserves_room_for_near_incident_prose_dates():
    # a donor narrating an event 60 days before the incident can never be
    # placed in the window's first 60 days
    donor = "GC-478-20240502-1620"
    look, fwd = sc._narrative_span(donor)
    sid = sc.scenario_incident_number("northstar", donor)
    d = sc.anchored_incident_date("northstar", sid, donor)
    from datetime import timedelta
    assert d >= sc.WINDOW_START + timedelta(days=look)
    assert d <= sc.WINDOW_END - timedelta(days=fwd)


def test_people_columns_are_syn_never_donor_values():
    d = sc.donor_partition("northstar")[1]
    p = _plan(d)
    row, prov = sc.build_incident_row(p, sc.donor_incidents()[d])
    if not p.skipped:
        assert row["Investigation leader - Name"].startswith("SYN-")
        assert prov["Investigation leader - Name"] == "syn"
    assert row["Incident Classified by - Name"].startswith("SYN-")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scenario_incidents.py -q`
Expected: FAIL — `IncidentPlan`/`make_plan` not defined.

- [ ] **Step 3: Implement** (append to `src/psm/scenario.py`)

```python
from dataclasses import dataclass, field


@dataclass
class IncidentPlan:
    """Every decision for one synthetic incident, drawn deterministically
    BEFORE any table row is built, so recurrence planting (Task 9) can move
    the anchor date without re-drawing anything."""
    company: str
    sid: str
    donor_id: str
    skipped: bool
    work_group: str
    doi: date                       # anchor; recurrence planting may move it
    report_lag: int
    invest_days: int
    reaches_root: bool
    chain_len: int                  # 0 if skipped, else 1..3 (3 iff reaches_root)
    n_recs: int                     # 0 if skipped
    rec_tags: list[str]
    agreed_offsets: list[int]       # per rec, days from Date of Report
    completion_offsets: list[int]   # per rec, days from Date of Report
    owner_assigned: list[bool]
    hs_blanked: bool
    element_override: str | None = None   # set only by recurrence planting

    @property
    def report_date(self) -> date:
        return self.doi + timedelta(days=self.report_lag)

    @property
    def approval_date(self) -> date | None:
        return None if self.skipped else self.report_date + timedelta(days=self.invest_days)

    def agreed_dates(self) -> list[date]:
        return [self.report_date + timedelta(days=o) for o in self.agreed_offsets]

    def completed_dates(self) -> list[date]:
        return [self.report_date + timedelta(days=o) for o in self.completion_offsets]

    @property
    def close_out_date(self) -> date | None:
        done = self.completed_dates()
        return max(done) if done else None

    @property
    def completion_span(self) -> int:
        """Days from Date of Incident to the last Date Completed."""
        return self.report_lag + (max(self.completion_offsets)
                                  if self.completion_offsets else 0)


def make_plan(company: str, cfg: dict, donor_id: str) -> IncidentPlan:
    sid = scenario_incident_number(company, donor_id)
    inv, clo, dd = cfg["investigation"], cfg["closeout"], cfg["data_discipline"]
    skipped = rate_hit(f"{company}|{sid}|skip|{SALT}", inv["skip_rate"])
    reaches_root = (not skipped) and rate_hit(
        f"{company}|{sid}|root|{SALT}", inv["root_cause_prob"])
    chain_len = 0 if skipped else (
        3 if reaches_root else 1 + _hash(f"{company}|{sid}|chain|{SALT}") % 2)
    n_recs = 0 if skipped else (
        1 + (1 if _hash(f"{company}|{sid}|nrec|{SALT}") % 10 < 2 else 0))  # mean 1.2
    mix = [(tag, round(cfg["controls_mix"][tag] * 100))
           for tag in ("elimination", "engineering", "admin", "ppe")]
    amin, amax = cfg["agreed_offset"]["min_days"], cfg["agreed_offset"]["max_days"]
    return IncidentPlan(
        company=company, sid=sid, donor_id=donor_id, skipped=skipped,
        work_group=pick_weighted(f"{company}|{sid}|work_group|{SALT}",
                                 WORK_GROUP_WEIGHTS),
        doi=anchored_incident_date(company, sid, donor_id),
        report_lag=draw_days(f"{company}|{sid}|report_lag|{SALT}",
                             cfg["report_lag"]["median_days"],
                             cfg["report_lag"]["sigma"]),
        invest_days=draw_days(f"{company}|{sid}|invest_duration|{SALT}",
                              inv["duration_median_days"], inv["duration_sigma"]),
        reaches_root=reaches_root, chain_len=chain_len, n_recs=n_recs,
        rec_tags=[pick_weighted(f"{company}|{sid}|tag|{i}|{SALT}", mix)
                  for i in range(n_recs)],
        agreed_offsets=[amin + _hash(f"{company}|{sid}|agreed|{i}|{SALT}")
                        % (amax - amin + 1) for i in range(n_recs)],
        completion_offsets=[draw_days(f"{company}|{sid}|closeout|{i}|{SALT}",
                                      clo["median_days"], clo["sigma"])
                            for i in range(n_recs)],
        owner_assigned=[rate_hit(f"{company}|{sid}|owner|{i}|{SALT}",
                                 dd["owner_assigned_rate"])
                        for i in range(n_recs)],
        hs_blanked=rate_hit(f"{company}|{sid}|hsblank|{SALT}",
                            dd["extra_hs_blank_rate"]),
    )


@lru_cache(maxsize=None)
def _real_table(name: str) -> tuple[tuple[str, ...], tuple[dict, ...]]:
    with (REAL / name).open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return tuple(reader.fieldnames or ()), tuple(reader)


def incident_fieldnames() -> list[str]:
    return list(_real_table("incidents.csv")[0])


@lru_cache(maxsize=None)
def donor_incidents() -> dict[str, dict]:
    return {r["Incident Number"]: r for r in _real_table("incidents.csv")[1]}


def donor_delta(plan: IncidentPlan) -> int:
    """Days the donor's structured date moved; prose dates move by the same
    delta so narrative and register never disagree."""
    raw = donor_incidents().get(plan.donor_id, {}).get("Date of Incident", "")
    try:
        return (plan.doi - date.fromisoformat(raw)).days
    except ValueError:
        return 0


# columns copied from the donor with prose-date shifting applied
_FREE_TEXT = ("incident Title", "Detail", "Description", "What happened?  ",
              "What was the outcome?",
              "What was the worst outcome that could reasonably be expected to have happened?",
              "How did the incident occur")
# columns copied verbatim from the donor
_VERBATIM = ("Incident Classificatioin", "Site", "Area", "Unit",
             "Incident Type A", "Incident Type B", "Incident Type C",
             "Incident Type D", "Incident Classification",
             "Health & Safety Incident - Classification",
             "Health & Safety - Risk Score", "Health & Safety  - Consequence",
             "Health & Safety - Likelihood",
             "Environment & Reputation - Incident Classification",
             "Environment & Reputation - Risk Score",
             "Environment & Reputation  - Consequence",
             "Environment & Reputation - Likelihood",
             "Financial Cost & Business - Incident Classification",
             "Financial Cost & Business Interruption - Risk Score",
             "Financial Cost & Business Interruption  - Consequence",
             "Financial Cost & Business Interruption - Likelihood")
_HS_TRIO = ("Health & Safety - Risk Score", "Health & Safety  - Consequence",
            "Health & Safety - Likelihood")
# (name column, position column, role key, gate) -- gate: when populated
_PEOPLE = (
    ("Investigation leader - Name", "Investigation leader - Position",
     "leader", "investigated"),
    ("Incident Classified by - Name", "Incident Classified by - Position",
     "classifier", "always"),
    ("Investigation Acceptor/Approver (Owner) - Name",
     "Investigation Acceptor/Approver (Owner)- Position",   # sic: no space
     "approver", "investigated"),
    ("Close out Approval - Name", "Close out Approval - Position",
     "closer", "closed"),
)


_NEAR_LOOKBACK = 365   # days before the incident a narrative may reference
_NEAR_FORWARD = 90     # days after


def _narrative_span(donor_id: str) -> tuple[int, int]:
    """(lookback, forward) days spanned by NEAR-INCIDENT prose dates in the
    donor's free-text fields, capped at the allowances. Dates further out
    are historical or OCR-garbage references (the real corpus carries
    offsets up to ~1000 years, e.g. '29-JUN-0202') and are exempt from the
    window invariant: era-plausible or already-dirty either way -- 'source
    data is dirty and stays dirty' is standing repo policy."""
    row = donor_incidents().get(donor_id, {})
    try:
        doi = date.fromisoformat(row.get("Date of Incident", ""))
    except ValueError:
        return 0, 0
    look = fwd = 0
    for c in _FREE_TEXT:
        for pd in find_prose_dates(row.get(c) or ""):
            off = (doi - pd).days
            if 0 <= off <= _NEAR_LOOKBACK:
                look = max(look, off)
            elif -_NEAR_FORWARD <= off < 0:
                fwd = max(fwd, -off)
    return look, fwd


def anchored_incident_date(company: str, sid: str, donor_id: str) -> date:
    """Hash placement clamped so every near-incident prose date still lands
    inside the window after the uniform shift (Task 12 enforces this)."""
    look, fwd = _narrative_span(donor_id)
    span = WINDOW_DAYS - look - fwd
    off = _hash(f"{company}|{sid}|incident_date|{SALT}") % span
    return WINDOW_START + timedelta(days=look + off)


def build_incident_row(plan: IncidentPlan, donor_row: dict) -> tuple[dict, dict]:
    delta = donor_delta(plan)
    row: dict[str, str] = {c: "" for c in incident_fieldnames()}
    prov: dict[str, str] = dict(row)

    def put(col, value, token):
        row[col] = value
        prov[col] = token if value.strip() else ""

    put("Incident Number", plan.sid, "key")
    put("Date of Incident", plan.doi.isoformat(), "syn")
    put("Date of Report", plan.report_date.isoformat(), "syn")
    put("Work Group", plan.work_group, "syn")
    donor_time = (donor_row.get("Time of Incident") or "").strip()
    if donor_time:
        put("Time of Incident", donor_time, "src")
    else:
        h = _hash(f"{plan.company}|{plan.sid}|time|{SALT}")
        put("Time of Incident", f"{h % 24:02d}:{(h // 24) % 12 * 5:02d}", "syn")
    for c in _FREE_TEXT:
        text = (donor_row.get(c) or "")
        put(c, shift_prose_dates(text, delta) if text.strip() else "", "src")
    for c in _VERBATIM:
        put(c, (donor_row.get(c) or ""), "src")
    if plan.hs_blanked:
        for c in _HS_TRIO:
            put(c, "", "")
    if plan.approval_date:
        put("Approval Date", plan.approval_date.isoformat(), "syn")
    if plan.close_out_date:
        put("Close out Date", plan.close_out_date.isoformat(), "syn")
    for name_col, pos_col, role, gate in _PEOPLE:
        populate = (gate == "always"
                    or (gate == "investigated" and not plan.skipped)
                    or (gate == "closed" and plan.close_out_date is not None))
        if populate:
            name, pos = syn_person(f"{plan.company}|{plan.sid}|{role}")
            put(name_col, name, "syn")
            put(pos_col, pos, "syn")
    return row, prov
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_scenario_incidents.py tests/test_scenario_foundations.py -q`
Expected: PASS.

- [ ] **Step 5: Mutation-check**

Temporarily make `put("Investigation leader - Name", ...)` copy `donor_row.get("Investigation leader - Name")` — the people-columns test must fail (donor values are pseud tokens, not SYN-). Reverse the edit. Temporarily drop the `shift_prose_dates` call (pass `text` through) — the narrative-shift test must fail. Reverse it. Record both.

- [ ] **Step 6: Commit**

```bash
git add src/psm/scenario.py tests/test_scenario_incidents.py
git commit -m "feat: IncidentPlan draws + incidents table builder"
```

---

### Task 8: Cause-chain builder

**Files:**
- Modify: `src/psm/scenario.py`
- Test: `tests/test_scenario_causes.py`

**Interfaces:**
- Consumes: `IncidentPlan` (Task 7), `donor_delta`, `shift_prose_dates`, `_real_table`.
- Produces: `cause_fieldnames() -> list[str]`, `donor_causes() -> dict[str, list[dict]]`, `build_cause_rows(plan: IncidentPlan, donor_row: dict) -> tuple[list[dict], list[dict]]`. Task 9's `generate` and the recurrence detector consume these rows.

Chain semantics (spec): investigated incidents get `chain_len` rows typed
`Immediate` → `Underlying` → `Root` in that order; the chain reaches `Root`
iff `plan.reaches_root` (so Coastal's 0.25 root_cause_prob truncates most
chains). `Cause type` is ENGINE-ASSIGNED (`syn`) — never inherited from the
`filled/` layer's positional artifact. Description text comes from the
donor's real cause rows in `Cause number` order, cycled if the chain is
longer, with prose-date shifting; if the donor has no cause rows (4 of
1,214), the single-row chain reuses the donor's `Description` field.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scenario_causes.py
from psm import scenario as sc

CFG = sc.load_scenario("northstar")
CCFG = sc.load_scenario("coastal")


def _rows(company, cfg, donor):
    p = sc.make_plan(company, cfg, donor)
    return p, sc.build_cause_rows(p, sc.donor_incidents()[donor])


def test_chain_types_are_ordered_and_root_gated():
    for donor in sc.donor_partition("northstar")[:40]:
        p, (rows, prov) = _rows("northstar", CFG, donor)
        types = [r["Cause type"] for r in rows]
        assert types == ["Immediate", "Underlying", "Root"][:len(types)]
        assert (len(rows) == 0) == p.skipped
        if not p.skipped:
            assert ("Root" in types) == p.reaches_root
            assert 1 <= len(rows) <= 3


def test_rows_carry_sid_ordinals_and_closed_provenance():
    donor = sc.donor_partition("northstar")[0]
    p, (rows, prov) = _rows("northstar", CFG, donor)
    for i, (r, pr) in enumerate(zip(rows, prov), 1):
        assert r["Incident Number"] == p.sid and pr["Incident Number"] == "key"
        assert r["Cause number"] == str(i) and pr["Cause number"] == "syn"
        assert pr["Cause type"] == "syn"
        assert set(pr.values()) <= {"", "src", "syn", "key"}
        assert r["Cause Description"].strip()
        assert pr["Cause Description"] == "src"


def test_element_override_wins_and_is_syn():
    donor = sc.donor_partition("meridian")[0]
    p = sc.make_plan("meridian", sc.load_scenario("meridian"), donor)
    if p.skipped:
        donor = sc.donor_partition("meridian")[1]
        p = sc.make_plan("meridian", sc.load_scenario("meridian"), donor)
    p.element_override = "15"
    rows, prov = sc.build_cause_rows(p, sc.donor_incidents()[donor])
    assert rows[0][" Failed PSM Framework Element"] == "15"
    assert prov[0][" Failed PSM Framework Element"] == "syn"


def test_coastal_truncates_most_chains():
    donors = sc.donor_partition("coastal")
    plans = [sc.make_plan("coastal", CCFG, d) for d in donors]
    invest = [p for p in plans if not p.skipped]
    rooted = sum(1 for p in invest if p.reaches_root)
    assert rooted / len(invest) < 0.5    # 0.25 knob; generous determinism bound
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scenario_causes.py -q`
Expected: FAIL — `build_cause_rows` not defined.

- [ ] **Step 3: Implement** (append to `src/psm/scenario.py`)

```python
def cause_fieldnames() -> list[str]:
    return list(_real_table("causes.csv")[0])


@lru_cache(maxsize=None)
def donor_causes() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in _real_table("causes.csv")[1]:
        out.setdefault(r["Incident Number"], []).append(r)
    for rows in out.values():
        rows.sort(key=lambda r: int(r["Cause number"] or 0))
    return out


_CHAIN = ("Immediate", "Underlying", "Root")


def build_cause_rows(plan: IncidentPlan,
                     donor_row: dict) -> tuple[list[dict], list[dict]]:
    if plan.skipped:
        return [], []
    delta = donor_delta(plan)
    donors = donor_causes().get(plan.donor_id, [])
    rows, provs = [], []
    for i in range(plan.chain_len):
        row = {c: "" for c in cause_fieldnames()}
        prov = dict(row)

        def put(col, value, token):
            row[col] = value
            prov[col] = token if value.strip() else ""

        put("Incident Number", plan.sid, "key")
        put("Cause number", str(i + 1), "syn")
        put("Cause type", _CHAIN[i], "syn")
        if donors:
            src = donors[i % len(donors)]
            put("Cause Description",
                shift_prose_dates(src.get("Cause Description") or "", delta), "src")
            put("Risk Management Cause", src.get("Risk Management Cause") or "", "src")
            put("Human Factors  Cause", src.get("Human Factors  Cause") or "", "src")
            put(" Failed PSM Framework Element",
                (src.get(" Failed PSM Framework Element") or "").strip(), "src")
        else:  # 4 donors have zero cause rows: fall back to the incident text
            put("Cause Description",
                shift_prose_dates(donor_row.get("Description") or "", delta), "src")
        if plan.element_override and i == 0:
            put(" Failed PSM Framework Element", plan.element_override, "syn")
        rows.append(row)
        provs.append(prov)
    if not donors and len(rows) > 1:
        # a donor-less chain longer than 1 would just repeat the fallback
        # text -- truncate to a single Immediate row instead
        rows, provs = rows[:1], provs[:1]
    return rows, provs
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_scenario_causes.py -q`
Expected: PASS.

- [ ] **Step 5: Mutation-check**

Temporarily assign `Cause type` from `src.get("Cause type")` (donor inheritance — the exact defect Phase 0 documented) — the ordered-chain test must fail (donor values are empty). Reverse the edit. Temporarily apply the override at every `i` instead of `i == 0` — no test fails? The override test only checks row 0; extend nothing — instead check the mutation with the recurrence detector in Task 9. Record: this mutation is caught later; note it in the ledger for Task 9's reviewer.

- [ ] **Step 6: Commit**

```bash
git add src/psm/scenario.py tests/test_scenario_causes.py
git commit -m "feat: generated cause chains (Immediate->Underlying->Root, root-gated)"
```

---

### Task 9: Recommendations + closeout builders, recurrence planting, full `generate()`

**Files:**
- Modify: `src/psm/scenario.py`
- Test: `tests/test_scenario_generate.py`

**Interfaces:**
- Consumes: Tasks 6-8; `psm.templates.templates_by_tag`.
- Produces: `rec_fieldnames()`, `closeout_fieldnames()`, `build_rec_rows(plan) -> tuple[list[dict], list[dict]]`, `build_closeout_rows(plan) -> tuple[list[dict], list[dict]]`, `plant_recurrence(company: str, cfg: dict, plans: list[IncidentPlan]) -> list[tuple[str, str]]`, `detect_recurrence_pairs(incidents: list[dict], causes: list[dict], window_days: int) -> list[tuple[str, str]]`, `generate(company: str) -> dict` returning `{"tables": {name: (fieldnames, rows, prov)}, "plans": [...], "planted_pairs": [...], "cfg": {...}}`, `write_company(result: dict, out_dir: Path) -> None`. Task 10 wraps these in the CLI + manifest; Task 11's recurrence KPI imports `detect_recurrence_pairs` (single implementation — no drift between planting and measurement).

Recurrence semantics (spec, exact): a pair is TWO DISTINCT incidents sharing
a non-blank ` Failed PSM Framework Element` code AND `Work Group`, whose
`Date of Incident`s lie within `window_days` of each other, where the later
incident's `Date of Incident` falls AFTER the earlier one's final
`Date Completed` (its `Close out Date`). Planting moves the second member's
anchor date and forces both members' `Work Group` and first-cause element;
it never clones rows or duplicates text.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scenario_generate.py
from datetime import date

from psm import scenario as sc
from psm.templates import classify_action


def test_generate_northstar_shape_and_closed_provenance():
    res = sc.generate("northstar")
    t = res["tables"]
    assert set(t) == {"incidents", "causes", "recommendations", "closeout"}
    cols, rows, prov = t["incidents"]
    assert len(rows) == 150 and len(prov) == 150
    for name in t:
        _, rws, prv = t[name]
        assert len(rws) == len(prv)
        for p in prv:
            assert set(p.values()) <= {"", "src", "syn", "key"}, name


def test_every_rec_has_a_closeout_row_and_registry_text():
    res = sc.generate("northstar")
    _, recs, _ = res["tables"]["recommendations"]
    _, close, _ = res["tables"]["closeout"]
    assert len(recs) == len(close)
    keys = {(r["Incident Number"], r["Recommendation Number"]) for r in recs}
    assert {(c["Incident Number"], c["Recommendation Number"])
            for c in close} == keys
    for r in recs:
        classify_action(r["Recommendation Description"])   # KeyError = failure
    for c in close:
        assert c["Schedule Status"] in ("On Schedule", "Behind")
        date.fromisoformat(c["Date Completed"])


def test_schedule_status_matches_the_date_comparison():
    res = sc.generate("northstar")
    _, recs, _ = res["tables"]["recommendations"]
    _, close, _ = res["tables"]["closeout"]
    agreed = {(r["Incident Number"], r["Recommendation Number"]):
              date.fromisoformat(r["Agreed Completion Date"]) for r in recs}
    for c in close:
        done = date.fromisoformat(c["Date Completed"])
        expect = "Behind" if done > agreed[
            (c["Incident Number"], c["Recommendation Number"])] else "On Schedule"
        assert c["Schedule Status"] == expect


def test_meridian_plants_eight_maintenance_pairs_and_detector_finds_them():
    res = sc.generate("meridian")
    pairs = res["planted_pairs"]
    assert len(pairs) == 8
    _, incs, _ = res["tables"]["incidents"]
    _, causes, _ = res["tables"]["causes"]
    by_id = {r["Incident Number"]: r for r in incs}
    for a, b in pairs:
        assert by_id[a]["Work Group"] == by_id[b]["Work Group"] == "Maintenance"
    detected = set(map(tuple, sc.detect_recurrence_pairs(incs, causes, 365)))
    assert set(map(tuple, pairs)) <= detected


def test_planted_pair_ordering_invariants():
    res = sc.generate("meridian")
    _, incs, _ = res["tables"]["incidents"]
    by_id = {r["Incident Number"]: r for r in incs}
    for a, b in res["planted_pairs"]:
        doi_a = date.fromisoformat(by_id[a]["Date of Incident"])
        doi_b = date.fromisoformat(by_id[b]["Date of Incident"])
        close_a = date.fromisoformat(by_id[a]["Close out Date"])
        assert doi_b > close_a
        assert (doi_b - doi_a).days <= 365
        assert sc.WINDOW_START <= doi_b <= sc.WINDOW_END


def test_generate_is_deterministic_in_process():
    a = sc.generate("northstar")
    b = sc.generate("northstar")
    assert a["tables"] == b["tables"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scenario_generate.py -q`
Expected: FAIL — `generate` not defined.

- [ ] **Step 3: Implement** (append to `src/psm/scenario.py`)

```python
from psm.templates import templates_by_tag


def rec_fieldnames() -> list[str]:
    return list(_real_table("recommendations.csv")[0])


def closeout_fieldnames() -> list[str]:
    return list(_real_table("closeout.csv")[0])


def build_rec_rows(plan: IncidentPlan) -> tuple[list[dict], list[dict]]:
    rows, provs = [], []
    agreed = plan.agreed_dates()
    by_tag = templates_by_tag()
    for i in range(plan.n_recs):
        row = {c: "" for c in rec_fieldnames()}
        prov = dict(row)

        def put(col, value, token):
            row[col] = value
            prov[col] = token if value.strip() else ""

        put("Incident Number", plan.sid, "key")
        put("Recommendation Number", str(i + 1), "syn")
        pool = by_tag[plan.rec_tags[i]]
        tpl = pool[_hash(f"{plan.company}|{plan.sid}|tpl|{i}|{SALT}") % len(pool)]
        put("Recommendation Description", tpl["text"], "syn")
        put("Agreed Completion Date", agreed[i].isoformat(), "syn")
        if plan.owner_assigned[i]:
            name, pos = syn_person(f"{plan.company}|{plan.sid}|recowner|{i}")
            put("Responsible Owner - Name", name, "syn")
            put("Responsible Owner - Position", pos, "syn")
        rows.append(row)
        provs.append(prov)
    return rows, provs


def build_closeout_rows(plan: IncidentPlan) -> tuple[list[dict], list[dict]]:
    rows, provs = [], []
    agreed, done = plan.agreed_dates(), plan.completed_dates()
    for i in range(plan.n_recs):
        row = {c: "" for c in closeout_fieldnames()}
        prov = dict(row)

        def put(col, value, token):
            row[col] = value
            prov[col] = token if value.strip() else ""

        put("Incident Number", plan.sid, "key")
        put("Recommendation Number", str(i + 1), "syn")
        put("Schedule Status",
            "Behind" if done[i] > agreed[i] else "On Schedule", "syn")
        put("Date Completed", done[i].isoformat(), "syn")
        rows.append(row)
        provs.append(prov)
    return rows, provs


_PLANT_ELEMENTS = ("3", "15", "8")   # the three most common real codes


def plant_recurrence(company: str, cfg: dict,
                     plans: list[IncidentPlan]) -> list[tuple[str, str]]:
    n = cfg["recurrence"]["planted_pairs"]
    if not n:
        return []
    window = cfg["recurrence"]["window_days"]
    wg_forced = cfg["recurrence"].get("work_group")
    candidates = sorted((p for p in plans if not p.skipped and p.n_recs > 0),
                        key=lambda p: p.sid)
    pairs: list[tuple[str, str]] = []
    used: set[str] = set()
    i = 0
    while len(pairs) < n and i < len(candidates):
        a = candidates[i]
        i += 1
        if a.sid in used or a.completion_span >= window - 1:
            continue
        b = next((c for c in candidates if c.sid not in used and c.sid != a.sid
                  and c.completion_span < window - 1), None)
        if b is None:
            break
        span = a.completion_span
        gap = span + 1 + _hash(f"{company}|pairgap|{len(pairs)}|{SALT}") % (window - span - 1)
        # planting overrides the anchored placement, so re-check both
        # members' narrative allowances (Task 12's window test enforces them)
        look_a, _ = _narrative_span(a.donor_id)
        if a.doi + timedelta(days=gap) > WINDOW_END:
            a.doi = WINDOW_END - timedelta(days=gap)
            if a.doi < WINDOW_START + timedelta(days=look_a):
                continue
        _, fwd_b = _narrative_span(b.donor_id)
        if a.doi + timedelta(days=gap) > WINDOW_END - timedelta(days=fwd_b):
            continue
        b.doi = a.doi + timedelta(days=gap)
        element = _PLANT_ELEMENTS[
            _hash(f"{company}|pairel|{len(pairs)}|{SALT}") % len(_PLANT_ELEMENTS)]
        wg = wg_forced or pick_weighted(f"{company}|pairwg|{len(pairs)}|{SALT}",
                                        WORK_GROUP_WEIGHTS)
        for p in (a, b):
            p.work_group = wg
            p.element_override = element
        used |= {a.sid, b.sid}
        pairs.append((a.sid, b.sid))
    assert len(pairs) == n, f"{company}: planted only {len(pairs)}/{n} pairs"
    return pairs


def detect_recurrence_pairs(incidents: list[dict], causes: list[dict],
                            window_days: int) -> list[tuple[str, str]]:
    """The ONE recurrence predicate: shared non-blank element code + same
    Work Group + anchors within window + second anchor after first's final
    Date Completed. Used by planting verification AND the KPI (no drift)."""
    elements: dict[str, set[str]] = {}
    for c in causes:
        e = (c[" Failed PSM Framework Element"] or "").strip()
        if e:
            elements.setdefault(c["Incident Number"], set()).add(e)
    info = []
    for r in incidents:
        close = (r["Close out Date"] or "").strip()
        info.append((date.fromisoformat(r["Date of Incident"]),
                     r["Incident Number"], r["Work Group"],
                     date.fromisoformat(close) if close else None))
    info.sort()
    out = []
    for x in range(len(info)):
        doi_a, sid_a, wg_a, close_a = info[x]
        if close_a is None:
            continue
        for y in range(x + 1, len(info)):
            doi_b, sid_b, wg_b, _ = info[y]
            if (doi_b - doi_a).days > window_days:
                break
            if (wg_a == wg_b and doi_b > close_a
                    and elements.get(sid_a, set()) & elements.get(sid_b, set())):
                out.append((sid_a, sid_b))
    return out


def generate(company: str) -> dict:
    cfg = load_scenario(company)
    plans = [make_plan(company, cfg, d) for d in donor_partition(company)]
    planted = plant_recurrence(company, cfg, plans)
    plans.sort(key=lambda p: p.doi.isoformat() + p.sid)   # register in date order
    tables: dict[str, tuple[list[str], list[dict], list[dict]]] = {
        "incidents": (incident_fieldnames(), [], []),
        "causes": (cause_fieldnames(), [], []),
        "recommendations": (rec_fieldnames(), [], []),
        "closeout": (closeout_fieldnames(), [], []),
    }
    for p in plans:
        donor_row = donor_incidents()[p.donor_id]
        for name, (rows, provs) in (
            ("incidents", tuple([x] for x in build_incident_row(p, donor_row))),
            ("causes", build_cause_rows(p, donor_row)),
            ("recommendations", build_rec_rows(p)),
            ("closeout", build_closeout_rows(p)),
        ):
            tables[name][1].extend(rows)
            tables[name][2].extend(provs)
    return {"tables": tables, "plans": plans, "planted_pairs": planted,
            "cfg": cfg}


_PROV_FILE = {"incidents": "provenance.csv",
              "causes": "causes_provenance.csv",
              "recommendations": "recommendations_provenance.csv",
              "closeout": "closeout_provenance.csv"}


def write_company(result: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, (cols, rows, provs) in result["tables"].items():
        for fname, data in ((f"{name}.csv", rows), (_PROV_FILE[name], provs)):
            with (out_dir / fname).open("w", encoding="utf-8", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=cols)
                w.writeheader()
                w.writerows(data)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_scenario_generate.py -q`
Expected: PASS. If `plant_recurrence` asserts (cannot place 8 pairs), STOP
and report BLOCKED with the failing company and the span statistics — do
NOT change SALT to make it pass (salt-shopping invalidates the honesty
claim; the fix is widening the candidate filter, a design change the
controller must see).

- [ ] **Step 5: Mutation-check**

Temporarily flip the planted ordering rule to `gap = span - 1` (second
incident before the first closes) — `test_planted_pair_ordering_invariants`
must fail. Reverse it. Temporarily make `detect_recurrence_pairs` ignore
Work Group (drop `wg_a == wg_b`) — the meridian detector test still passes
(supersets allowed), so instead verify NorthStar coincidence shifts: run
`uv run python -c "from psm import scenario as sc; r = sc.generate('northstar'); t = r['tables']; print(len(sc.detect_recurrence_pairs(t['incidents'][1], t['causes'][1], 365)))"`
before and after the mutation — the count must increase (recorded in the
task report as the observed behavioural change). Reverse it.

- [ ] **Step 6: Commit**

```bash
git add src/psm/scenario.py tests/test_scenario_generate.py
git commit -m "feat: recs/closeout builders, recurrence planting + single detector, generate()"
```

---

### Task 10: Manifest, CLI, generate + commit NorthStar and Meridian

**Files:**
- Modify: `src/psm/scenario.py` (manifest + `__main__`)
- Test: `tests/test_scenario_manifest.py`
- Generated + committed: `data/companies/northstar/*` and `data/companies/meridian/*` (4 tables + 4 provenance files + manifest.json each)

**Interfaces:**
- Consumes: Tasks 4-9 (`analytic_overdue_rate`, `generate`, `write_company`, `detect_recurrence_pairs`, `scenario_sha256`).
- Produces: `build_manifest(company: str, result: dict) -> dict`, CLI `uv run python -m psm.scenario <company>` writing `data/companies/<company>/`. Manifest JSON schema (spec-pinned) below. Tasks 11-13 read `data/companies/`.

Manifest content rules (spec): every KPI appears in every company's manifest
as a plant, an analytic expectation, or a negative control — nothing
unasserted. `analytic_expectations.overdue_rate` comes from
`analytic_overdue_rate` (exact 1024 x 61 iteration, no sampling).
`analytic_expectations.hs_blank_baseline` is the donor partition's pre-knob
H&S blank share. `analytic_expectations.recurrence_coincidence` is the count
of detected pairs on the GENERATED register excluding planted ones.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scenario_manifest.py
import json
from pathlib import Path

from psm import scenario as sc
from psm.quantiles import analytic_overdue_rate

KPIS = {"median_report_lag", "skip_rate", "root_cause_depth",
        "median_closeout_days", "overdue_rate", "recurrence_rate",
        "admin_ppe_share", "owner_completeness", "hs_completeness"}


def test_manifest_asserts_every_kpi_somewhere():
    for company in ("northstar", "meridian"):
        m = sc.build_manifest(company, sc.generate(company))
        covered = ({p["kpi"] for p in m["plants"]}
                   | set(m["analytic_expectations"].get("kpi_map", {}))
                   | {c.split("(")[0] for c in m["negative_controls"]})
        assert KPIS <= covered, (company, KPIS - covered)


def test_manifest_records_partition_window_knobs_and_sha():
    m = sc.build_manifest("meridian", sc.generate("meridian"))
    assert m["company"] == "meridian"
    assert len(m["donor_partition"]) == 150
    assert m["window"] == {"start": "2021-01-01", "end": "2025-12-31"}
    assert m["scenario_sha256"] == sc.scenario_sha256("meridian")
    assert m["resolved_knobs"] == sc.load_scenario("meridian")
    ov = m["analytic_expectations"]["overdue_rate"]
    assert ov == analytic_overdue_rate(130, 0.8, 30, 90)


def test_meridian_manifest_lists_eight_recurrence_pairs():
    res = sc.generate("meridian")
    m = sc.build_manifest("meridian", res)
    rec = [p for p in m["plants"] if p["pathology"] == "recurrence_after_closure"]
    assert len(rec) == 1 and len(rec[0]["affected_ids"]) == 8


def test_committed_registers_match_a_fresh_generate():
    # after the CLI has run and data is committed, regeneration is identical
    for company in ("northstar", "meridian"):
        out = Path(sc.OUT_ROOT) / company
        assert (out / "manifest.json").exists(), "run the CLI first"
        fresh = sc.build_manifest(company, sc.generate(company))
        on_disk = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert on_disk == fresh
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scenario_manifest.py -q`
Expected: FAIL — `build_manifest` not defined.

- [ ] **Step 3: Implement** (append to `src/psm/scenario.py`)

```python
import json
import sys


def build_manifest(company: str, result: dict) -> dict:
    cfg = result["cfg"]
    tables = result["tables"]
    planted = [list(p) for p in result["planted_pairs"]]
    detected = detect_recurrence_pairs(tables["incidents"][1],
                                       tables["causes"][1],
                                       cfg["recurrence"]["window_days"])
    coincidence = len([p for p in detected if list(p) not in planted])
    donors_hs_blank = sum(
        1 for d in donor_partition(company)
        if not (donor_incidents()[d]["Health & Safety - Risk Score"] or "").strip()
    ) / 150
    plants: list[dict] = []
    negative: list[str] = []
    # kpi_map: which analytic expectation covers which KPI (manifest-consistency
    # test requires every KPI asserted as plant, analytic, or negative control)
    analytic = {
        "overdue_rate": analytic_overdue_rate(
            cfg["closeout"]["median_days"], cfg["closeout"]["sigma"],
            cfg["agreed_offset"]["min_days"], cfg["agreed_offset"]["max_days"]),
        "hs_blank_baseline": donors_hs_blank,
        "recurrence_coincidence": coincidence,
        "kpi_map": {"overdue_rate": "overdue_rate",
                    "hs_completeness": "hs_blank_baseline",
                    "recurrence_rate": "recurrence_coincidence"},
    }
    if company == "meridian":
        plants = [
            {"pathology": "report_lag", "kpi": "median_report_lag",
             "expected": {"op": ">", "ref": "northstar", "factor": 3.0},
             "affected_ids": None},
            {"pathology": "closeout_decay", "kpi": "median_closeout_days",
             "expected": {"op": ">", "ref": "northstar", "factor": 2.0},
             "affected_ids": None},
            {"pathology": "recurrence_after_closure", "kpi": "recurrence_rate",
             "expected": {"op": ">=", "count": 8},
             "affected_ids": [list(p) for p in result["planted_pairs"]]},
        ]
        negative = ["skip_rate(near-baseline)", "root_cause_depth(near-baseline)",
                    "admin_ppe_share(=northstar)", "owner_completeness(near-baseline)",
                    "hs_completeness(=baseline)"]
    elif company == "coastal":
        plants = [
            {"pathology": "investigation_skip", "kpi": "skip_rate",
             "expected": {"op": ">", "ref": "northstar", "factor": 5.0},
             "affected_ids": None},
            {"pathology": "shallow_investigation", "kpi": "root_cause_depth",
             "expected": {"op": "<", "ref": "northstar", "factor": 0.5},
             "affected_ids": None},
            {"pathology": "weak_controls", "kpi": "admin_ppe_share",
             "expected": {"op": ">", "ref": "northstar", "delta_pts": 25},
             "affected_ids": None},
            {"pathology": "missing_owners", "kpi": "owner_completeness",
             "expected": {"op": "<", "ref": "northstar", "delta_pts": -25},
             "affected_ids": None},
            {"pathology": "hs_data_decay", "kpi": "hs_completeness",
             "expected": {"op": "<", "ref": "baseline", "delta_pts": -15},
             "affected_ids": None},
            {"pathology": "recurrence_after_closure", "kpi": "recurrence_rate",
             "expected": {"op": ">=", "count": 6},
             "affected_ids": [list(p) for p in result["planted_pairs"]]},
        ]
        negative = ["median_report_lag(=northstar)",
                    "median_closeout_days(fast-on-paper)"]
    else:  # northstar and meridian_nt: the all-negative-control baseline
        negative = ["median_report_lag(baseline)", "skip_rate(baseline)",
                    "root_cause_depth(baseline)", "median_closeout_days(baseline)",
                    "admin_ppe_share(baseline)", "owner_completeness(baseline)",
                    "hs_completeness(baseline)"]
    return {
        "company": company,
        "scenario_sha256": scenario_sha256(company),
        "donor_partition": donor_partition(company),
        "window": {"start": WINDOW_START.isoformat(),
                   "end": WINDOW_END.isoformat()},
        "resolved_knobs": cfg,
        "plants": plants,
        "analytic_expectations": analytic,
        "negative_controls": negative,
    }


def main(argv: list[str]) -> int:
    company = argv[0]
    if company == "meridian_nt":
        print("meridian_nt is TEST-ONLY and is never written under data/companies/")
        return 2
    assert company in COMPANY_ORDER, f"unknown company {company!r}"
    result = generate(company)
    out = OUT_ROOT / company
    write_company(result, out)
    manifest = build_manifest(company, result)
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    n = {k: len(v[1]) for k, v in result["tables"].items()}
    print(f"wrote {out}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Generate the two registers and run the tests**

```bash
uv run python -m psm.scenario northstar
uv run python -m psm.scenario meridian
```
Then: `uv run pytest tests/test_scenario_manifest.py tests/test_scenario_generate.py -q`
Expected: PASS. Then confirm `data/companies/` is not ignored:
`git status --short data/companies | head` must show untracked/added files
(if a gitignore rule swallows them, STOP and report — data/companies is a
committed processed layer like data/processed/e19).

- [ ] **Step 5: Mutation-check**

Temporarily hand-edit one cell in `data/companies/meridian/incidents.csv` (change one `Work Group` value) — `test_committed_registers_match_a_fresh_generate` must fail via the manifest? It will not (manifest ignores that cell), so ALSO run `uv run python -c "import csv; from psm import scenario as sc; r = sc.generate('meridian'); disk = list(csv.DictReader(open('data/companies/meridian/incidents.csv', encoding='utf-8'))); assert disk == r['tables']['incidents'][1], 'drift detected'"` — must raise. Undo by re-running `uv run python -m psm.scenario meridian`. (Task 12 turns this disk-vs-fresh comparison into a permanent test over all tables.) Record the observed failure.

- [ ] **Step 6: Commit (code + generated registers together)**

```bash
git add src/psm/scenario.py tests/test_scenario_manifest.py data/companies
git commit -m "feat: manifests + CLI; generate northstar and meridian registers"
```

---

### Task 11: The nine-KPI layer

**Files:**
- Create: `src/psm/kpi.py`
- Test: `tests/test_kpi.py`

**Interfaces:**
- Consumes: `psm.templates.classify_action`, `psm.scenario.detect_recurrence_pairs`.
- Produces: `load_company(path: Path) -> dict[str, list[dict]]` (keys incidents/causes/recommendations/closeout), `compute_kpis(tables: dict[str, list[dict]], window_days: int = 365) -> dict[str, float | int]` with EXACTLY these keys: `median_report_lag`, `skip_rate`, `root_cause_depth`, `median_closeout_days`, `overdue_rate`, `recurrence_rate`, `admin_ppe_share`, `owner_completeness`, `hs_completeness`. Works on in-memory tables so the test-only meridian_nt variant never touches disk. Tasks 12-14 consume this.

Definitions (exact fields — the spec table, resolved to code):
1. `median_report_lag`: median of `(Date of Report − Date of Incident).days` over incidents with both dates.
2. `skip_rate`: share of ALL incidents with zero cause rows AND blank `Investigation leader - Name`.
3. `root_cause_depth`: share of INVESTIGATED incidents (non-blank leader) having at least one cause row with `Cause type == "Root"`. Skipped incidents are excluded from the denominator — stated to kill the divide ambiguity.
4. `median_closeout_days`: median of `(Date Completed − Date of Report).days` over closeout rows joined to their incident.
5. `overdue_rate`: share of closeout rows with `Date Completed > Agreed Completion Date` (joined to recommendations on Incident Number + Recommendation Number).
6. `recurrence_rate`: `len(detect_recurrence_pairs(incidents, causes, window_days))` — an integer count, the same predicate that planting verified.
7. `admin_ppe_share`: share of recommendations whose `classify_action(text)` tag is `admin` or `ppe`.
8. `owner_completeness`: share of recommendations with non-blank `Responsible Owner - Name`.
9. `hs_completeness`: share of incidents with non-blank `Health & Safety - Risk Score`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_kpi.py
from pathlib import Path

from psm import scenario as sc
from psm.kpi import compute_kpis, load_company

KEYS = {"median_report_lag", "skip_rate", "root_cause_depth",
        "median_closeout_days", "overdue_rate", "recurrence_rate",
        "admin_ppe_share", "owner_completeness", "hs_completeness"}


def _mem_tables(company):
    res = sc.generate(company)
    return {name: rows for name, (cols, rows, prov) in res["tables"].items()}


def test_kpis_have_exactly_the_nine_keys_and_sane_ranges():
    k = compute_kpis(_mem_tables("northstar"))
    assert set(k) == KEYS
    for name in ("skip_rate", "root_cause_depth", "overdue_rate",
                 "admin_ppe_share", "owner_completeness", "hs_completeness"):
        assert 0.0 <= k[name] <= 1.0, name
    assert k["median_report_lag"] >= 0
    assert isinstance(k["recurrence_rate"], int)


ROOT = Path(__file__).resolve().parents[1] / "data" / "companies"


def test_load_company_reads_the_committed_register():
    tables = load_company(ROOT / "northstar")
    assert len(tables["incidents"]) == 150
    k = compute_kpis(tables)
    assert set(k) == KEYS


def test_kpis_move_in_the_planted_directions():
    kn = compute_kpis(_mem_tables("northstar"))
    km = compute_kpis(_mem_tables("meridian"))
    assert km["median_report_lag"] > kn["median_report_lag"]
    assert km["median_closeout_days"] > kn["median_closeout_days"]
    assert km["recurrence_rate"] >= 8


def test_skip_rate_uses_the_and_of_both_conditions():
    tables = _mem_tables("coastal")
    # every counted skip must have BOTH markers, not either
    causes_by = {}
    for c in tables["causes"]:
        causes_by.setdefault(c["Incident Number"], []).append(c)
    manual = sum(1 for r in tables["incidents"]
                 if not r["Investigation leader - Name"].strip()
                 and not causes_by.get(r["Incident Number"]))
    assert compute_kpis(tables)["skip_rate"] == manual / len(tables["incidents"])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_kpi.py -q`
Expected: FAIL — `psm.kpi` does not exist.

- [ ] **Step 3: Implement**

```python
# src/psm/kpi.py
"""Nine deterministic KPIs over a company register (in-memory tables or a
data/companies/<co> directory). No thresholds live here -- the manifest and
tests/test_scenarios.py own every assertion."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from statistics import median

from psm.scenario import detect_recurrence_pairs
from psm.templates import classify_action

_TABLES = ("incidents", "causes", "recommendations", "closeout")


def load_company(path: Path) -> dict[str, list[dict]]:
    out = {}
    for name in _TABLES:
        with (path / f"{name}.csv").open(encoding="utf-8", newline="") as fh:
            out[name] = list(csv.DictReader(fh))
    return out


def _d(value: str) -> date | None:
    value = (value or "").strip()
    return date.fromisoformat(value) if value else None


def compute_kpis(tables: dict[str, list[dict]],
                 window_days: int = 365) -> dict[str, float | int]:
    incs, causes = tables["incidents"], tables["causes"]
    recs, close = tables["recommendations"], tables["closeout"]

    causes_by: dict[str, list[dict]] = {}
    for c in causes:
        causes_by.setdefault(c["Incident Number"], []).append(c)
    report_by = {r["Incident Number"]: _d(r["Date of Report"]) for r in incs}
    agreed_by = {(r["Incident Number"], r["Recommendation Number"]):
                 _d(r["Agreed Completion Date"]) for r in recs}

    lags = [( _d(r["Date of Report"]) - _d(r["Date of Incident"])).days
            for r in incs
            if _d(r["Date of Report"]) and _d(r["Date of Incident"])]

    skipped = [r for r in incs
               if not r["Investigation leader - Name"].strip()
               and not causes_by.get(r["Incident Number"])]
    investigated = [r for r in incs if r["Investigation leader - Name"].strip()]
    rooted = sum(1 for r in investigated
                 if any(c["Cause type"] == "Root"
                        for c in causes_by.get(r["Incident Number"], [])))

    closeout_days, overdue = [], 0
    for c in close:
        done = _d(c["Date Completed"])
        rep = report_by.get(c["Incident Number"])
        if done and rep:
            closeout_days.append((done - rep).days)
        agreed = agreed_by.get((c["Incident Number"], c["Recommendation Number"]))
        if done and agreed and done > agreed:
            overdue += 1

    tags = [classify_action(r["Recommendation Description"]) for r in recs]

    return {
        "median_report_lag": float(median(lags)) if lags else 0.0,
        "skip_rate": len(skipped) / len(incs) if incs else 0.0,
        "root_cause_depth": rooted / len(investigated) if investigated else 0.0,
        "median_closeout_days": (float(median(closeout_days))
                                 if closeout_days else 0.0),
        "overdue_rate": overdue / len(close) if close else 0.0,
        "recurrence_rate": len(detect_recurrence_pairs(incs, causes,
                                                       window_days)),
        "admin_ppe_share": (sum(1 for t in tags if t in ("admin", "ppe"))
                            / len(tags) if tags else 0.0),
        "owner_completeness": (sum(1 for r in recs
                                   if r["Responsible Owner - Name"].strip())
                               / len(recs) if recs else 0.0),
        "hs_completeness": (sum(1 for r in incs
                                if r["Health & Safety - Risk Score"].strip())
                            / len(incs) if incs else 0.0),
    }
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_kpi.py -q`
Expected: PASS. (Coastal is not on disk yet — the coastal tests here run in memory via `generate`; that is intended.)

- [ ] **Step 5: Mutation-check**

Temporarily change the skip predicate's `and` to `or` — `test_skip_rate_uses_the_and_of_both_conditions` must fail. Reverse it. Temporarily compute closeout days from `Date of Incident` instead of `Date of Report` — `test_kpis_move_in_the_planted_directions` should still pass (both directions preserved), so record instead that the value shifts: print `median_closeout_days` for northstar before and after; the after-value must exceed the before-value (report lag added). Reverse it. Record both observations.

- [ ] **Step 6: Commit**

```bash
git add src/psm/kpi.py tests/test_kpi.py
git commit -m "feat: nine-KPI layer over company registers"
```

---

### Task 12: The validation suite — planted vs measured, negative controls, near-threshold, hygiene

**Files:**
- Create: `tests/test_scenarios.py`
- Possibly regenerate: nothing — this task adds tests only. If any test exposes a generation defect, STOP and report BLOCKED (the fix belongs to the task that owns the defective code).

**Interfaces:**
- Consumes: everything from Tasks 4-11; committed `data/companies/northstar` + `data/companies/meridian`.
- Produces: the finish-line test module later extended by Task 13.

Statistical tolerances (design decision, refined from the spec): "within ±X
pts" assertions use `tol(p, n, floor) = max(floor, 3 * sqrt(p*(1-p)/n))` —
the spec's point-tolerances as floors, widened to 3 sigma of the binomial
at the measured scale where n is small. Rationale: generation is
deterministic, so a knife-edge tolerance would not be flaky — it would be
permanently wrong on one fixed draw; 3 sigma bounds honest sampling
variation without letting a planted effect (all >= 5 sigma by construction)
slip through. If any assertion below fails on the real generated data, do
NOT tune salts, knobs, or tolerances to pass — report BLOCKED with the
measured value, the bound, and the margin.

Spec deviation (recorded): the spec's "re-run under a different injected
build date" check is realized as (a) the byte-identical fresh-regenerate
test plus (b) a source lint proving the engine modules reference no wall
clock or randomness at all. An engine with no clock input cannot depend on
the build date; injecting one would test a parameter that does not exist.

- [ ] **Step 1: Write the tests** (this task IS the tests; they must pass immediately — any failure is a real finding)

```python
# tests/test_scenarios.py
"""Finish line: every planted pathology recovered, negative controls bounded,
near-threshold resolution proven, registers reproducible and clean.
Companies are auto-discovered from data/companies/ so Task 13 (coastal)
extends coverage by committing data, not by editing this file's core tests."""
import json
import math
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from psm import scenario as sc
from psm.kpi import compute_kpis, load_company
from psm.quantiles import analytic_overdue_rate

ROOT = Path(__file__).resolve().parents[1] / "data" / "companies"
COMPANIES = sorted(p.name for p in ROOT.iterdir()
                   if (p / "manifest.json").exists())


def tol(p: float, n: int, floor: float) -> float:
    return max(floor, 3 * math.sqrt(max(p * (1 - p), 1e-9) / n))


def _mem(company):
    res = sc.generate(company)
    return {name: rows for name, (cols, rows, prov) in res["tables"].items()}


@pytest.fixture(scope="module")
def kpis():
    out = {c: compute_kpis(load_company(ROOT / c)) for c in COMPANIES}
    out["meridian_nt"] = compute_kpis(_mem("meridian_nt"))
    return out


@pytest.fixture(scope="module")
def manifests():
    return {c: json.loads((ROOT / c / "manifest.json").read_text(encoding="utf-8"))
            for c in COMPANIES}


# ---- reproducibility ----------------------------------------------------

@pytest.mark.parametrize("company", COMPANIES)
def test_committed_register_is_byte_identical_to_a_fresh_generate(company, tmp_path):
    res = sc.generate(company)
    out = tmp_path / company
    sc.write_company(res, out)
    (out / "manifest.json").write_text(
        json.dumps(sc.build_manifest(company, res), indent=2, sort_keys=True)
        + "\n", encoding="utf-8")
    for f in sorted((ROOT / company).iterdir()):
        assert (out / f.name).read_bytes() == f.read_bytes(), f.name


def test_engine_has_no_wall_clock_or_random_dependence():
    import psm.kpi, psm.quantiles, psm.scenario, psm.templates
    for mod in (psm.scenario, psm.quantiles, psm.kpi, psm.templates):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        for banned in ("date.today", "datetime.now(", "time.time(",
                       "import random", "from random"):
            assert banned not in src, (mod.__name__, banned)


# ---- planted vs measured: Meridian --------------------------------------

def test_meridian_report_lag_planted(kpis):
    assert kpis["meridian"]["median_report_lag"] > 3 * kpis["northstar"]["median_report_lag"]


def test_meridian_closeout_decay_planted(kpis):
    assert kpis["meridian"]["median_closeout_days"] > 2 * kpis["northstar"]["median_closeout_days"]


def test_meridian_recurrence_planted_and_northstar_bounded(kpis, manifests):
    assert kpis["meridian"]["recurrence_rate"] >= 8
    # NorthStar planted 0: measured count IS the recorded coincidence count
    assert kpis["northstar"]["recurrence_rate"] == \
        manifests["northstar"]["analytic_expectations"]["recurrence_coincidence"]


def test_overdue_is_emergent_and_matches_the_analytic_expectation(kpis, manifests):
    for c in COMPANIES:
        expect = manifests[c]["analytic_expectations"]["overdue_rate"]
        n = len(load_company(ROOT / c)["closeout"])
        assert abs(kpis[c]["overdue_rate"] - expect) <= tol(expect, n, 0.05), c
    assert kpis["meridian"]["overdue_rate"] > 3 * kpis["northstar"]["overdue_rate"]


# ---- negative controls on Meridian (aids attribution) -------------------

def test_meridian_negative_controls(kpis):
    kn, km = kpis["northstar"], kpis["meridian"]
    assert abs(km["skip_rate"] - kn["skip_rate"]) <= tol(0.03, 150, 0.02)
    assert abs(km["root_cause_depth"] - kn["root_cause_depth"]) <= tol(0.85, 150, 0.10)
    assert abs(km["admin_ppe_share"] - kn["admin_ppe_share"]) <= tol(0.45, 180, 0.05)
    assert abs(km["owner_completeness"] - kn["owner_completeness"]) <= tol(0.95, 180, 0.05)
    assert abs(km["hs_completeness"] - kn["hs_completeness"]) <= tol(0.53, 150, 0.05)


# ---- near-threshold resolution (test-only variant, never on disk) -------

def test_near_threshold_variant_is_still_detected(kpis):
    nt, kn = kpis["meridian_nt"], kpis["northstar"]
    assert nt["median_closeout_days"] > 1.2 * kn["median_closeout_days"]
    # and ONLY the closeout knob moved: report lag stays at baseline
    assert abs(nt["median_report_lag"] - kn["median_report_lag"]) <= 2


def test_meridian_nt_never_exists_on_disk():
    assert not (ROOT / "meridian_nt").exists()


# ---- prose-date window --------------------------------------------------

@pytest.mark.parametrize("company", COMPANIES)
def test_near_incident_prose_dates_land_inside_the_window(company):
    """Every prose date that referenced the incident's own timeline
    (within -365..+90 days of the donor incident) must land inside the
    company window after the shift. Historical/garbage references (the
    real corpus goes up to ~1000 years off) are exempt -- era-plausible
    or already-dirty either way."""
    tables = load_company(ROOT / company)
    partition = sc.donor_partition(company)
    sid_to_donor = {sc.scenario_incident_number(company, d): d
                    for d in partition}
    checked = 0
    for row in tables["incidents"]:
        donor_id = sid_to_donor[row["Incident Number"]]
        donor = sc.donor_incidents()[donor_id]
        donor_doi = date.fromisoformat(donor["Date of Incident"])
        for col in sc._FREE_TEXT:
            for p in sc.find_prose_dates(row[col]):
                doi = date.fromisoformat(row["Date of Incident"])
                original = p - (doi - donor_doi)     # undo the shift
                off = (donor_doi - original).days
                if 0 <= off <= sc._NEAR_LOOKBACK or -sc._NEAR_FORWARD <= off < 0:
                    assert sc.WINDOW_START <= p <= sc.WINDOW_END, (
                        row["Incident Number"], col, p)
                    checked += 1
    assert checked > 50, "window test exercised too few dates -- investigate"


# ---- text hygiene -------------------------------------------------------

_BANNED = re.compile(r"\b(MMS|OSM|BSEE|District|Regional Office)\b")


@pytest.mark.parametrize("company", COMPANIES)
def test_recommendation_text_is_registry_only_and_regulator_free(company):
    from psm.templates import classify_action
    for r in load_company(ROOT / company)["recommendations"]:
        text = r["Recommendation Description"]
        assert not _BANNED.search(text), text
        classify_action(text)     # KeyError = text outside the registry
    # scope note: donor NARRATIVES legitimately mention MMS/BSEE (they are
    # disclosed real text); the regulator-voice lint applies to the
    # recommendation register only.


# ---- provenance + manifest consistency ----------------------------------

@pytest.mark.parametrize("company", COMPANIES)
def test_company_provenance_closed_set_all_four_tables(company):
    import csv as _csv
    for name, prov_file in (("incidents", "provenance.csv"),
                            ("causes", "causes_provenance.csv"),
                            ("recommendations", "recommendations_provenance.csv"),
                            ("closeout", "closeout_provenance.csv")):
        with (ROOT / company / prov_file).open(encoding="utf-8", newline="") as fh:
            for prow in _csv.DictReader(fh):
                assert set(prow.values()) <= {"", "src", "syn", "key"}, name


KPIS = {"median_report_lag", "skip_rate", "root_cause_depth",
        "median_closeout_days", "overdue_rate", "recurrence_rate",
        "admin_ppe_share", "owner_completeness", "hs_completeness"}


@pytest.mark.parametrize("company", COMPANIES)
def test_manifest_leaves_no_kpi_unasserted(company, manifests):
    m = manifests[company]
    covered = ({p["kpi"] for p in m["plants"]}
               | set(m["analytic_expectations"].get("kpi_map", {}))
               | {c.split("(")[0] for c in m["negative_controls"]})
    assert KPIS <= covered, KPIS - covered
```

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest -q`
Expected: ALL PASS. On any failure in this module: report BLOCKED per the
tolerance rule above — no salt/knob/tolerance tuning.

- [ ] **Step 3: Mutation-checks (three, covering the three assertion families)**

1. Temporarily hand-edit `data/companies/meridian/closeout.csv`: subtract 100 days from every `Date Completed` via a short python script (read, edit, write). `test_meridian_closeout_decay_planted` (or the byte-identity test) must fail. Undo by re-running `uv run python -m psm.scenario meridian`.
2. Temporarily add `import random` to `src/psm/scenario.py` — the wall-clock/random lint must fail. Reverse the edit.
3. Temporarily change one `Recommendation Description` cell in `data/companies/northstar/recommendations.csv` to `Coordinate with the District office.` — the registry/regulator test must fail. Undo by re-running `uv run python -m psm.scenario northstar`.
Record all three observed failures in the task report.

- [ ] **Step 4: Commit**

```bash
git add tests/test_scenarios.py
git commit -m "test: planted-vs-measured, negative controls, near-threshold, hygiene suite"
```

---

### Task 13: Coastal — generate, commit, extend validation

**Files:**
- Modify: `tests/test_scenarios.py` (append coastal-specific assertions)
- Generated + committed: `data/companies/coastal/*`

**Interfaces:**
- Consumes: everything prior. The auto-discovery in `tests/test_scenarios.py` pulls coastal into every parametrized test the moment its directory lands.
- Produces: the third committed register + the coastal planted/negative assertions.

- [ ] **Step 1: Generate coastal**

```bash
uv run python -m psm.scenario coastal
```
Expected: `data/companies/coastal/` with 9 files (4 tables, 4 provenance, manifest).

- [ ] **Step 2: Write the coastal assertions** (append to `tests/test_scenarios.py`)

```python
# ---- planted vs measured: Coastal (bundle-level attribution) ------------
# Coastal's pathologies co-move by design; this suite claims bundle-level
# detection for Coastal, NOT per-pathology attribution (parked in the spec).

def test_coastal_skip_planted(kpis):
    kn, kc = kpis["northstar"], kpis["coastal"]
    assert kc["skip_rate"] > 5 * kn["skip_rate"]


def test_coastal_shallow_investigation_planted(kpis):
    assert kpis["coastal"]["root_cause_depth"] < 0.5 * kpis["northstar"]["root_cause_depth"]


def test_coastal_weak_controls_planted(kpis):
    assert kpis["coastal"]["admin_ppe_share"] > kpis["northstar"]["admin_ppe_share"] + 0.25


def test_coastal_missing_owners_planted(kpis):
    assert kpis["coastal"]["owner_completeness"] < kpis["northstar"]["owner_completeness"] - 0.25


def test_coastal_hs_decay_planted_and_baseline_adjusted(kpis, manifests):
    baseline = 1 - manifests["coastal"]["analytic_expectations"]["hs_blank_baseline"]
    assert kpis["coastal"]["hs_completeness"] < baseline - 0.15


def test_coastal_recurrence_planted(kpis):
    assert kpis["coastal"]["recurrence_rate"] >= 6


def test_coastal_negative_controls(kpis):
    kn, kc = kpis["northstar"], kpis["coastal"]
    assert abs(kc["median_report_lag"] - kn["median_report_lag"]) <= \
        max(1.0, 0.3 * kn["median_report_lag"])          # spec: within +/-30%
    # fast-on-paper: coastal closeout must NOT trip the decay direction
    assert kc["median_closeout_days"] < 2 * kn["median_closeout_days"]
```

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: ALL PASS — including every Task 12 parametrized test now running
over three companies. Same BLOCKED rule on failure: no tuning.

- [ ] **Step 4: Mutation-check**

Temporarily blank every `Responsible Owner - Name` in `data/companies/coastal/recommendations.csv` via a short python script — `test_coastal_missing_owners_planted` still passes (blanking is the planted direction) but the byte-identity test must fail; record that pairing (the reproducibility test is what protects planted data from tampering in EITHER direction). Undo by re-running `uv run python -m psm.scenario coastal`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_scenarios.py data/companies/coastal
git commit -m "feat: coastal register + bundle-level planted assertions"
```

---

### Task 14: Company workbooks + internal comparison workbook

**Files:**
- Create: `src/psm/export_companies.py`
- Test: `tests/test_export_companies.py`

**Interfaces:**
- Consumes: `psm.export_e19._write_sheet` (reused — after Task 1 it shades every `FILL_COLORS` token incl. `key`/`syn`), `psm.kpi`, `psm.scenario`, committed `data/companies/`.
- Produces: `deliverables/companies/NorthStar_E19_Register.xlsx`, `Meridian_E19_Register.xlsx`, `Coastal_E19_Register.xlsx`, and `deliverables/companies/comparison.xlsx`. All under gitignored `deliverables/` — never committed.

Disclosure rules (spec): each company About states it is a synthetic
register built for evaluator testing with deliberately varied process
health, WITHOUT naming which pathologies or which company carries them;
disclose the uniform date shift, the template-sourced recommendation text,
and the 30-incidents/yr large-operator framing. The comparison workbook is
the ANSWER KEY: planted pathologies named, planted-vs-measured, negative
controls — internal only, never distributed with the company workbooks.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_export_companies.py
from pathlib import Path

from openpyxl import load_workbook

from psm.export_companies import (ABOUT_TEMPLATE, COMPANY_LABELS,
                                  export_all, OUT_DIR)


def test_company_about_discloses_without_leaking_the_answer_key():
    text = "\n".join(ABOUT_TEMPLATE)
    for needed in ("synthetic", "template", "shifted", "deliberately"):
        assert needed in text.lower()
    for banned in ("pathology", "answer key", "closeout decay",
                   "northstar is", "coastal is"):
        assert banned not in text.lower()


def test_export_writes_three_company_workbooks_and_the_comparison(tmp_path):
    export_all(out_dir=tmp_path)
    for label in COMPANY_LABELS.values():
        wb = load_workbook(tmp_path / f"{label}_E19_Register.xlsx")
        assert wb.sheetnames == ["About", "Incidents", "Causes",
                                 "Recommendations", "Closeout"]
    cmp_wb = load_workbook(tmp_path / "comparison.xlsx")
    assert cmp_wb.sheetnames == ["About", "KPIs", "Plants", "Negative Controls"]
    kpi_ws = cmp_wb["KPIs"]
    assert kpi_ws.max_row == 10            # header + 9 KPIs
    assert kpi_ws.max_column == 4          # kpi name + 3 companies


def test_incident_number_column_is_shaded_key_green(tmp_path):
    export_all(out_dir=tmp_path)
    wb = load_workbook(tmp_path / "NorthStar_E19_Register.xlsx")
    ws = wb["Incidents"]
    hdr = [c.value for c in ws[1]]
    i = hdr.index("Incident Number") + 1
    fills = {ws.cell(row=r, column=i).fill.start_color.rgb
             for r in range(2, 30)}
    assert fills == {"00E2EFDA"}


def test_comparison_about_names_the_bundle_level_claim(tmp_path):
    export_all(out_dir=tmp_path)
    wb = load_workbook(tmp_path / "comparison.xlsx")
    text = "\n".join(str(r[0].value or "") for r in wb["About"].iter_rows())
    assert "bundle-level" in text
    assert "never distributed" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_export_companies.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

```python
# src/psm/export_companies.py
"""Export the three synthetic-company registers to reviewer workbooks, plus
the INTERNAL comparison workbook (the answer key -- never distributed with
the company workbooks).

Run:  uv run python -m psm.export_companies
"""
from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from psm.export_e19 import _write_sheet
from psm.kpi import compute_kpis, load_company
from psm.scenario import COMPANY_ORDER, OUT_ROOT

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "deliverables" / "companies"

COMPANY_LABELS = {"northstar": "NorthStar", "meridian": "Meridian",
                  "coastal": "Coastal"}

_SHEETS = (("Incidents", "incidents", "provenance.csv"),
           ("Causes", "causes", "causes_provenance.csv"),
           ("Recommendations", "recommendations",
            "recommendations_provenance.csv"),
           ("Closeout", "closeout", "closeout_provenance.csv"))

ABOUT_TEMPLATE = [
    "{label} Offshore -- E19 Investigation Register (synthetic demonstration)",
    "",
    "{label} is a SYNTHETIC company. This register was generated from public",
    "US BSEE offshore incident narratives, rebased into 2021-2025 at a",
    "large-operator scale (~30 incidents/yr), with process health",
    "deliberately varied between the companies in this evaluation set so an",
    "incident-management evaluator can be tested against known conditions.",
    "Which conditions were varied, and where, is documented separately and",
    "intentionally not stated here.",
    "",
    "Cell colours state provenance (same scheme as the source project):",
    "  no colour  - verbatim text from a public BSEE incident report",
    "  grey       - synthetic: deterministic generated value (dates, names,",
    "               picklists, recommendation text). Corresponds to nothing real.",
    "  green      - constructed identifier (this register's own keys)",
    "",
    "Disclosures:",
    "- Dates inside narratives were uniformly shifted with each incident's",
    "  rebased timeline, so prose and register agree; era-distant dates in",
    "  the source text (including OCR debris) were left as found.",
    "- Recommendation text comes from a fixed template registry adapted from",
    "  real operator-voice recommendations; repetition across incidents is",
    "  intentional corporate boilerplate.",
    "- People are SYN- tokens. No real names appear in this register.",
]

_COMPARISON_ABOUT = [
    "Scenario comparison workbook -- INTERNAL VALIDATION ARTIFACT",
    "",
    "This is the answer key for the synthetic-company registers: it names",
    "the planted process pathologies, the measured KPI values, and the",
    "negative-control checks. It is never distributed alongside the company",
    "workbooks.",
    "",
    "Attribution honesty: Coastal's pathologies co-move by construction, so",
    "results for Coastal are claimed at bundle-level detection only --",
    "per-pathology attribution is out of scope (parked in the spec).",
]


def _about_sheet(wb: Workbook, lines: list[str]) -> None:
    ws = wb.active
    ws.title = "About"
    for line in lines:
        ws.append([line])
    ws.column_dimensions["A"].width = 90


def _company_workbook(company: str, out_dir: Path) -> Path:
    import csv
    label = COMPANY_LABELS[company]
    src = OUT_ROOT / company
    wb = Workbook()
    _about_sheet(wb, [ln.format(label=label) for ln in ABOUT_TEMPLATE])
    for sheet, table, prov_file in _SHEETS:
        with (src / f"{table}.csv").open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            cols, rows = list(reader.fieldnames or []), list(reader)
        with (src / prov_file).open(encoding="utf-8", newline="") as fh:
            prov = list(csv.DictReader(fh))
        _write_sheet(wb.create_sheet(sheet), cols, rows, prov)
    path = out_dir / f"{label}_E19_Register.xlsx"
    wb.save(path)
    return path


def _comparison_workbook(out_dir: Path) -> Path:
    kpis = {c: compute_kpis(load_company(OUT_ROOT / c)) for c in COMPANY_ORDER}
    manifests = {c: json.loads((OUT_ROOT / c / "manifest.json")
                               .read_text(encoding="utf-8"))
                 for c in COMPANY_ORDER}
    wb = Workbook()
    _about_sheet(wb, _COMPARISON_ABOUT)

    ws = wb.create_sheet("KPIs")
    ws.append(["KPI"] + [COMPANY_LABELS[c] for c in COMPANY_ORDER])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for kpi in sorted(kpis[COMPANY_ORDER[0]]):
        ws.append([kpi] + [round(float(kpis[c][kpi]), 4)
                           for c in COMPANY_ORDER])

    ws = wb.create_sheet("Plants")
    ws.append(["Company", "Pathology", "KPI", "Expected", "Measured"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for c in COMPANY_ORDER:
        for p in manifests[c]["plants"]:
            ws.append([COMPANY_LABELS[c], p["pathology"], p["kpi"],
                       json.dumps(p["expected"]),
                       round(float(kpis[c][p["kpi"]]), 4)])

    ws = wb.create_sheet("Negative Controls")
    ws.append(["Company", "Control"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for c in COMPANY_ORDER:
        for ctl in manifests[c]["negative_controls"]:
            ws.append([COMPANY_LABELS[c], ctl])

    path = out_dir / "comparison.xlsx"
    wb.save(path)
    return path


def export_all(out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [_company_workbook(c, out_dir) for c in COMPANY_ORDER]
    written.append(_comparison_workbook(out_dir))
    return written


def main() -> int:
    for path in export_all():
        print(f"wrote {path}")
    print("deliverables only - never commit; the record is data/companies/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests, then the real export, then the FULL suite**

```bash
uv run pytest tests/test_export_companies.py -q
uv run python -m psm.export_companies
uv run pytest -q
```
Expected: all pass; four xlsx files under `deliverables/companies/`;
`git status --short deliverables` shows NOTHING (gitignored — if it shows
files, STOP: the gitignore contract broke).

- [ ] **Step 5: Mutation-check**

Temporarily add the word `pathology` to `ABOUT_TEMPLATE` — the answer-key-leak test must fail. Reverse it. Record the failure.

- [ ] **Step 6: Commit**

```bash
git add src/psm/export_companies.py tests/test_export_companies.py
git commit -m "feat: company workbooks + internal comparison (answer-key) export"
```

---

## Execution Notes (for the controller running this plan)

- **Run order is strict:** Tasks 1→14. Phase 0 (1-3) must land before any
  generation work touches provenance.
- **Model pins per dispatch:** implementers on `claude-sonnet-5` (the plan
  contains near-complete code, but every task carries integration checks);
  purely mechanical fix rounds and scoped re-reviews on
  `claude-haiku-4-5-20251001`; task reviewers on `claude-sonnet-5`; the
  final whole-branch review on `claude-opus-5`. Always pass the model
  explicitly.
- **Overnight mode:** no user check-ins between tasks. STOP only for
  BLOCKED conditions this plan names (plant_recurrence assertion, margin
  failures, value-file drift in Task 2, gitignore contract breaks) or an
  unresolvable review conflict. Every stop writes its state to the ledger
  first.
- **Out of scope tonight, requires a fresh explicit user yes in the
  morning:** refreshing the RELAY Google Drive copy of `e19_filled.xlsx`;
  any push/PR/merge. Nothing in this plan touches
  `~/Library/CloudStorage/GoogleDrive-*`.
- **Never delete files.** Deletion candidates move to the station's
  `_Review-for-Deletion/` archive with a note.
- **Copy the Global Constraints block verbatim into every dispatch prompt.**
