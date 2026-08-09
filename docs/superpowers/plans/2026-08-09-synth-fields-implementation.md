# Synthetic (`syn_`) Field Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `schema/synth_rules.yaml` + `src/psm/synth.py`, a pure, deterministic function that fills the 28 `syn_` columns the E19 target schema (`schema/e19_target.yaml` v2) needs but BSEE never publishes, exactly per `docs/superpowers/specs/2026-08-09-synth-fields-design.md` (rev 2).

**Architecture:** `synth_rules.yaml` holds every threshold/tier/salt as editable data; `synth.py` is a thin engine of small, independently testable functions (`synth_identity_fields`, `synth_date_fields`, `synth_status_fields`, `synth_severity_fields`, `synth_incident_title`) composed by one public entrypoint, `synthesize_row(row, rules) -> dict`. No hidden randomness, no wall-clock reads — every "random"-looking value is `int(sha256(report_id + salt), 16) % N`, and every age-based rule reads a frozen `reference_date` from the rules file.

**Tech Stack:** Python 3.11+, `uv`, `pyyaml` (already a dependency), `pytest`, `ruff`.

## Global Constraints

- **Column provenance prefixes** (from `psm-incident-ml/CLAUDE.md`): `src_` verbatim from BSEE, `xw_` deterministic crosswalk via `schema/crosswalk.yaml`, `llm_` model output (never ground truth), `gold_` human-assigned (only scoreable target), `syn_` fully generated. A column with no prefix is a bug.
- **`xw_`/`syn_` boundary** (spec Architecture section): every `synth.py` output is `syn_`, even when derived from a real `src_` column — the tier mapping is our own invented judgment, never claimed as externally sourced. Do not cite an external precedent (e.g. "BSEE uses this threshold too") as justification anywhere in code or docs for this module.
- **No wall-clock reads, ever.** Every age-based rule computes against `rules["reference_date"]`, loaded from `schema/synth_rules.yaml`. `datetime.date.today()` / `datetime.now()` must not appear anywhere in `src/psm/synth.py`.
- **No workbook formulas replicated.** Every threshold in `synth_rules.yaml` is invented for this project, never reverse-engineered from `E19 Investigation Report - Rev2.xlsx`.
- **Anomalies are logged, never guessed.** When a real source field can't be resolved (empty/unrecognised `incident_types`, missing `property_damage_usd`), the corresponding `syn_` field is `"Unknown"`/`null` and an anomaly dict (`{"type": ..., "note": ...}`) is returned — matching the `data/interim/anomalies.jsonl` convention already used by `src/psm/spine.py` and `src/psm/extract.py`.
- **Stack conventions:** `from __future__ import annotations` at the top of every new module (matches `causes.py`/`extract.py`/`spine.py`); `ruff` line-length 100; tests run via `uv run pytest tests/test_synth.py tests/test_conventions.py -v`; module-level docstrings explain *why*, not *what*.
- **Scope boundary — read this before starting Task 1.** No module in this repo yet assembles real `src_`/`xw_` fields into a single incident row (`data/processed/incidents.csv` does not exist; `src/psm/crosswalk.py` does not exist). This plan builds `synth.py` as a pure function of an already-normalized row `dict`, tested entirely against fixtures built in `tests/conftest.py`. The exact row contract that a future assembly module must satisfy is defined in Task 1 and must not drift from what `synthesize_row` actually requires.

---

## Row Input Contract (binding for every task below)

`synthesize_row(row: dict, rules: dict) -> dict` requires exactly these keys in `row`:

| Key | Type | Real source (not built in this plan) | Resolved value used in tests |
|---|---|---|---|
| `report_id` | `str` | `src_sha256` from `data/manifest.csv` / `extract_report()`'s `rec["src_sha256"]` — already unique per PDF, no new ID scheme needed | any string |
| `incident_date` | `datetime.date` | parsed from `src_f01_occurred` (Form 2010 field 1) — parser not yet built | a `date` object |
| `incident_types` | `frozenset[str]` | parsed from `src_f07_type` (Form 2010 field 7) checkbox labels, using the vocabulary already in `schema/e19_target.yaml`'s `incident_type` list — parser not yet built. Empty frozenset means unresolved (zero checkboxes, or parse failure — both handled identically per the spec) | e.g. `frozenset({"Fatality"})` |
| `property_damage_usd` | `float \| None` | parsed from `src_f21_property_damaged` (Form 2010 field 21) — parser not yet built. `None` means unresolved (missing or parse-failed — both handled identically) | e.g. `50000.0` or `None` |
| `area_block` | `str` | `src_f04_lease_area_block` or `src_area`+`src_block` from the manifest | e.g. `"MP 298"` |

---

### Task 1: Row contract scaffolding, rules loader, test fixtures

**Blocked by:** nothing — start here.
**Unblocks:** Tasks 2–6 (all depend on `load_rules`, `validate_row`, and the `make_row` fixture built here).

**Files:**
- Create: `schema/synth_rules.yaml`
- Create: `src/psm/synth.py`
- Create: `tests/conftest.py`
- Create: `tests/test_synth.py`

**Interfaces:**
- Produces: `load_rules(path: Path = RULES_PATH) -> dict[str, Any]`, `validate_row(row: dict[str, Any]) -> None` (raises `KeyError` on missing keys), `REQUIRED_ROW_KEYS: set[str]`, `RULES_PATH: Path`, pytest fixture `make_row` (factory, returns a `dict` matching the Row Input Contract above with sensible defaults, overridable via kwargs).

**Definition of Done:** `uv run python -c "from psm.synth import load_rules; print(load_rules()['reference_date'])"` prints `2026-08-09`; `validate_row` tests pass for both a complete and an incomplete fixture row.

- [ ] **Step 1: Write `schema/synth_rules.yaml`**

```yaml
# Synthetic (syn_) field generation rules for the E19 target schema.
#
# DATA, NOT CODE — see docs/superpowers/specs/2026-08-09-synth-fields-design.md
# (rev 2) for the design rationale, and docs/_synth.md for a plain-language
# explanation. src/psm/synth.py applies these rules; it must not hardcode a
# threshold, tier, salt, or word-list defined here.

version: 1

# Frozen anchor for every age-based rule (action_status, schedule_status).
# NEVER read wall-clock time — that breaks the byte-identical reproducibility
# contract every time the pipeline reran on a later date. Bump this only
# deliberately, as a new dataset generation, never automatically.
reference_date: "2026-08-09"

# Per-role salts for identity-token hashing:
# token = sha256(report_id + salt).hexdigest()[:identity_token_hex_len]
identity_salts:
  investigation_lead: "lead"
  incident_classified_by: "classified_by"
  investigation_acceptor: "acceptor"
  close_out_approval: "close_out"
  responsible_owner: "owner"

# 6 hex chars = 16.7M-value space. Widened from 4 in rev 2 so expected
# collisions across the full ~1,300-report corpus are negligible (see spec).
identity_token_hex_len: 6

identity_token_labels:
  investigation_lead: "Investigator"
  incident_classified_by: "Classifier"
  investigation_acceptor: "Acceptor"
  close_out_approval: "Approver"
  responsible_owner: "Owner"

identity_positions:
  investigation_lead: "Synthetic Role — Investigation Lead"
  incident_classified_by: "Synthetic Role — Incident Classifier"
  investigation_acceptor: "Synthetic Role — Investigation Acceptor"
  close_out_approval: "Synthetic Role — Close-Out Approver"
  responsible_owner: "Synthetic Role — Responsible Owner"

# offset_days = low + int(sha256(report_id + salt), 16) % (high - low + 1)
# `base` must name a field already computed earlier in this mapping —
# insertion order below IS dependency order (date_of_report before
# approval_date, approval_date before the rest). Do not reorder without
# updating src/psm/synth.py's base-resolution check.
date_offsets:
  date_of_report:         {base: incident_date, low: 5,  high: 15,  salt: "date_of_report"}
  approval_date:           {base: date_of_report, low: 14, high: 45,  salt: "approval_date"}
  close_out_date:           {base: approval_date,   low: 30, high: 90,  salt: "close_out_date"}
  action_due_date:          {base: approval_date,   low: 30, high: 180, salt: "action_due_date"}
  agreed_completion_date:   {base: approval_date,   low: 30, high: 180, salt: "agreed_completion_date"}

action_status_age_days:
  completed_after: 730    # > 2yr -> Completed
  in_progress_after: 183  # 6mo-2yr -> In Progress; <=183 -> Pending

schedule_status_salt: "schedule_status"

# src_f07 checkbox label -> severity tier, highest listed tier wins if an
# incident matches more than one. Any resolved-but-unlisted label falls back
# to "Incident" in code; an empty/unresolved set falls back to "Unknown".
severity_tier_order: ["Very Serious", "Serious", "Incident"]
severity_tiers:
  "Very Serious": [Fatality, Blowout, Explosion]
  "Serious": [Injury, LWC, Fire, Collision]

hs_risk_score_by_tier:
  "Very Serious": 9
  "Serious": 5
  "Incident": 2

fatality_injury_labels: [Fatality, Injury]

pollution_label: "Pollution"

# Ordered low -> high; first entry whose max_usd the amount is <= wins.
# null max_usd = no upper bound. Our own thresholds, not externally sourced —
# see the xw_/syn_ boundary rule in CLAUDE.md.
financial_thresholds_usd:
  - {max_usd: 25000, classification: "Minor"}
  - {max_usd: 500000, classification: "Moderate"}
  - {max_usd: null, classification: "Major"}

financial_score_by_classification:
  "Minor": 2
  "Moderate": 5
  "Major": 9

mitigation_delta: 2
mitigation_floor: 1

incident_title_template: "{incident_type} incident at {area_block}"
```

- [ ] **Step 2: Write failing tests for the loader, validator, and fixture**

```python
# tests/conftest.py
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
```

```python
# tests/test_synth.py
"""Tests for src/psm/synth.py — synthetic E19 field generation.

Every synth field is a documented, deterministic function of report_id and a
handful of real fields (see the Row Input Contract in
docs/superpowers/plans/2026-08-09-synth-fields-implementation.md). No
randomness, no wall-clock reads — see schema/synth_rules.yaml's
reference_date for why.
"""
from __future__ import annotations

import pytest

from psm.synth import REQUIRED_ROW_KEYS, load_rules, validate_row


def test_load_rules_returns_expected_top_level_keys():
    rules = load_rules()
    assert rules["reference_date"] == "2026-08-09"
    assert "identity_salts" in rules
    assert "date_offsets" in rules


def test_validate_row_accepts_a_complete_row(make_row):
    validate_row(make_row())  # must not raise


def test_validate_row_rejects_a_row_missing_keys(make_row):
    row = make_row()
    del row["incident_date"]
    with pytest.raises(KeyError):
        validate_row(row)


def test_required_row_keys_matches_the_documented_contract():
    assert REQUIRED_ROW_KEYS == {
        "report_id", "incident_date", "incident_types",
        "property_damage_usd", "area_block",
    }
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_synth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'psm.synth'`

- [ ] **Step 4: Write the minimal `src/psm/synth.py` scaffolding**

```python
# src/psm/synth.py
"""Generate synthetic (syn_) fields for the E19 target schema.

Fills the 28 columns schema/e19_target.yaml's E19 target shape needs that
BSEE never publishes — see docs/superpowers/specs/2026-08-09-synth-fields-
design.md (rev 2) for the design and docs/_synth.md for the plain-language
version. Every rule here is deterministic: int(sha256(report_id + salt), 16)
% N for anything needing variety, and a frozen reference_date (never
date.today()) for anything age-dependent. schema/synth_rules.yaml holds
every threshold — this module must not hardcode one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
RULES_PATH = REPO / "schema" / "synth_rules.yaml"

REQUIRED_ROW_KEYS = {
    "report_id", "incident_date", "incident_types",
    "property_damage_usd", "area_block",
}


def load_rules(path: Path = RULES_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def validate_row(row: dict[str, Any]) -> None:
    missing = REQUIRED_ROW_KEYS - row.keys()
    if missing:
        raise KeyError(f"row missing required keys: {sorted(missing)}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_synth.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add schema/synth_rules.yaml src/psm/synth.py tests/conftest.py tests/test_synth.py
git commit -m "feat(synth): scaffold synth_rules.yaml, row contract, rules loader"
```

---

### Task 2: Identity fields

**Blocked by:** Task 1.
**Unblocks:** Task 7. (Independent of Tasks 3–6 — safe to build in parallel with them.)

**Files:**
- Modify: `src/psm/synth.py`
- Modify: `tests/test_synth.py`

**Interfaces:**
- Consumes: `load_rules()` from Task 1.
- Produces: `_hash_int(report_id: str, salt: str) -> int`, `synth_identity_fields(report_id: str, rules: dict) -> dict[str, str]` returning 10 bare keys: `{role}_name` and `{role}_position` for each of the 5 roles in `rules["identity_salts"]`.

**Definition of Done:** Name tokens match `SYN-<Label>-<6 hex chars>`; positions match `rules["identity_positions"]` exactly; deterministic; varies across `report_id`; no collision across roles within one report, checked over a 50-report fixture corpus.

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_synth.py
import re

from psm.synth import synth_identity_fields

TOKEN_RE = re.compile(r"^SYN-[A-Za-z]+-[0-9a-f]{6}$")


def test_identity_fields_are_deterministic():
    rules = load_rules()
    first = synth_identity_fields("stable-id", rules)
    second = synth_identity_fields("stable-id", rules)
    assert first == second


def test_identity_name_tokens_match_expected_format_and_positions():
    rules = load_rules()
    out = synth_identity_fields("some-report-id", rules)
    for role in rules["identity_salts"]:
        assert TOKEN_RE.match(out[f"{role}_name"]), out[f"{role}_name"]
        assert out[f"{role}_position"] == rules["identity_positions"][role]


def test_identity_tokens_vary_across_reports():
    rules = load_rules()
    leads = {synth_identity_fields(f"r{i}", rules)["investigation_lead_name"] for i in range(20)}
    assert len(leads) > 1


def test_identity_tokens_do_not_collide_across_roles_in_corpus():
    rules = load_rules()
    for i in range(50):
        out = synth_identity_fields(f"corpus-report-{i}", rules)
        names = [out[f"{role}_name"] for role in rules["identity_salts"]]
        assert len(names) == len(set(names)), f"collision in corpus-report-{i}: {names}"
```

(add `from psm.synth import load_rules` to the existing import line if not already present)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_synth.py -k identity -v`
Expected: FAIL with `ImportError: cannot import name 'synth_identity_fields'`

- [ ] **Step 3: Implement**

```python
# append to src/psm/synth.py
import hashlib


def _hash_int(report_id: str, salt: str) -> int:
    return int(hashlib.sha256(f"{report_id}{salt}".encode()).hexdigest(), 16)


def synth_identity_fields(report_id: str, rules: dict[str, Any]) -> dict[str, str]:
    hex_len = rules["identity_token_hex_len"]
    out: dict[str, str] = {}
    for role, salt in rules["identity_salts"].items():
        digest = hashlib.sha256(f"{report_id}{salt}".encode()).hexdigest()
        label = rules["identity_token_labels"][role]
        out[f"{role}_name"] = f"SYN-{label}-{digest[:hex_len]}"
        out[f"{role}_position"] = rules["identity_positions"][role]
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_synth.py -k identity -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/psm/synth.py tests/test_synth.py
git commit -m "feat(synth): identity-field hash tokens (SYN- prefix, 6 hex chars)"
```

---

### Task 3: Workflow-date fields

**Blocked by:** Task 1.
**Unblocks:** Task 7. (Independent of Tasks 2, 4–6.)

**Files:**
- Modify: `src/psm/synth.py`
- Modify: `tests/test_synth.py`

**Interfaces:**
- Consumes: `_hash_int` from Task 2, `load_rules()` from Task 1.
- Produces: `synth_date_fields(report_id: str, incident_date: date, rules: dict) -> dict[str, date]` returning 5 keys: `date_of_report`, `approval_date`, `close_out_date`, `action_due_date`, `agreed_completion_date`.

**Definition of Done:** Every offset lands strictly within its documented `[low, high]` day range (not just non-decreasing); deterministic; varies across `report_id`; raises a clear error if `synth_rules.yaml`'s `date_offsets` ever references a `base` not yet computed (protects the ordering invariant documented in Task 1's YAML comment).

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_synth.py
from datetime import date

from psm.synth import synth_date_fields


def test_date_offsets_are_within_documented_ranges():
    rules = load_rules()
    incident_date = date(2020, 1, 1)
    for report_id in ("r1", "r2", "r3", "r4", "r5"):
        out = synth_date_fields(report_id, incident_date, rules)
        assert 5 <= (out["date_of_report"] - incident_date).days <= 15
        assert 14 <= (out["approval_date"] - out["date_of_report"]).days <= 45
        assert 30 <= (out["close_out_date"] - out["approval_date"]).days <= 90
        assert 30 <= (out["action_due_date"] - out["approval_date"]).days <= 180
        assert 30 <= (out["agreed_completion_date"] - out["approval_date"]).days <= 180


def test_date_offsets_are_deterministic():
    rules = load_rules()
    incident_date = date(2020, 1, 1)
    assert synth_date_fields("stable-id", incident_date, rules) == synth_date_fields(
        "stable-id", incident_date, rules
    )


def test_date_offsets_vary_across_reports():
    rules = load_rules()
    incident_date = date(2020, 1, 1)
    values = {synth_date_fields(f"r{i}", incident_date, rules)["date_of_report"] for i in range(20)}
    assert len(values) > 1, "date_of_report constant across reports — salt or hashing broken"


def test_date_offsets_raise_on_unresolvable_base():
    rules = load_rules()
    broken_rules = dict(rules, date_offsets={"bad_field": {"base": "nonexistent", "low": 1, "high": 2, "salt": "x"}})
    with pytest.raises(ValueError, match="nonexistent"):
        synth_date_fields("r1", date(2020, 1, 1), broken_rules)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_synth.py -k date_offsets -v`
Expected: FAIL with `ImportError: cannot import name 'synth_date_fields'`

- [ ] **Step 3: Implement**

```python
# append to src/psm/synth.py
from datetime import date, timedelta


def synth_date_fields(report_id: str, incident_date: date, rules: dict[str, Any]) -> dict[str, date]:
    computed: dict[str, date] = {"incident_date": incident_date}
    for field, spec in rules["date_offsets"].items():
        base = spec["base"]
        if base not in computed:
            raise ValueError(
                f"date_offsets entry {field!r} references base {base!r} which is not "
                "yet computed — check ordering in schema/synth_rules.yaml"
            )
        span = spec["high"] - spec["low"] + 1
        offset = spec["low"] + _hash_int(report_id, spec["salt"]) % span
        computed[field] = computed[base] + timedelta(days=offset)
    del computed["incident_date"]
    return computed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_synth.py -k date_offsets -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/psm/synth.py tests/test_synth.py
git commit -m "feat(synth): workflow-date offsets, chained through the real incident_date"
```

---

### Task 4: Action/schedule status

**Blocked by:** Task 1 (uses `_hash_int` from Task 2 — do this after Task 2, or merge the `_hash_int` step from Task 2 first if executing out of order).
**Unblocks:** Task 7. (Independent of Tasks 3, 5, 6.)

**Files:**
- Modify: `src/psm/synth.py`
- Modify: `tests/test_synth.py`

**Interfaces:**
- Consumes: `_hash_int` from Task 2.
- Produces: `synth_status_fields(report_id: str, incident_date: date, rules: dict) -> dict[str, str]` returning `{"action_status": ..., "schedule_status": ...}`.

**Definition of Done:** Boundary values (`age_days` exactly 730 and exactly 183) land in the documented bucket; `schedule_status == "N/A"` whenever `action_status == "Completed"`, otherwise one of `{"On Schedule", "Behind"}`; changing only `rules["reference_date"]` (never wall-clock) changes the bucket deterministically — this is the regression test for the wall-clock bug the rev-2 spec review caught.

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_synth.py
from datetime import timedelta

from psm.synth import synth_status_fields


def test_action_status_completed_after_two_years():
    rules = load_rules()
    reference = date.fromisoformat(rules["reference_date"])
    out = synth_status_fields("r1", reference - timedelta(days=731), rules)
    assert out["action_status"] == "Completed"
    assert out["schedule_status"] == "N/A"


def test_action_status_boundary_at_exactly_two_years_is_not_yet_completed():
    rules = load_rules()
    reference = date.fromisoformat(rules["reference_date"])
    out = synth_status_fields("r1", reference - timedelta(days=730), rules)
    assert out["action_status"] == "In Progress"  # age_days == 730 is NOT > 730


def test_action_status_in_progress_between_six_months_and_two_years():
    rules = load_rules()
    reference = date.fromisoformat(rules["reference_date"])
    out = synth_status_fields("r1", reference - timedelta(days=400), rules)
    assert out["action_status"] == "In Progress"
    assert out["schedule_status"] in {"On Schedule", "Behind"}


def test_action_status_pending_under_six_months():
    rules = load_rules()
    reference = date.fromisoformat(rules["reference_date"])
    out = synth_status_fields("r1", reference - timedelta(days=100), rules)
    assert out["action_status"] == "Pending"


def test_status_changes_with_reference_date_not_wall_clock():
    """Regression test for the wall-clock bug the rev-2 review caught: the
    bucket must change only because rules['reference_date'] changed, never
    because of an internal date.today() call."""
    rules = load_rules()
    incident_date = date(2024, 1, 1)
    rules_soon = dict(rules, reference_date="2024-06-01")
    rules_later = dict(rules, reference_date="2026-03-01")
    assert synth_status_fields("r1", incident_date, rules_soon)["action_status"] == "Pending"
    assert synth_status_fields("r1", incident_date, rules_later)["action_status"] == "Completed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_synth.py -k action_status -v`
Expected: FAIL with `ImportError: cannot import name 'synth_status_fields'`

- [ ] **Step 3: Implement**

```python
# append to src/psm/synth.py
def synth_status_fields(report_id: str, incident_date: date, rules: dict[str, Any]) -> dict[str, str]:
    reference_date = date.fromisoformat(rules["reference_date"])
    age_days = (reference_date - incident_date).days
    thresholds = rules["action_status_age_days"]

    if age_days > thresholds["completed_after"]:
        action_status = "Completed"
    elif age_days > thresholds["in_progress_after"]:
        action_status = "In Progress"
    else:
        action_status = "Pending"

    if action_status == "Completed":
        schedule_status = "N/A"
    else:
        tiebreak = _hash_int(report_id, rules["schedule_status_salt"]) % 2
        schedule_status = "On Schedule" if tiebreak == 0 else "Behind"

    return {"action_status": action_status, "schedule_status": schedule_status}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_synth.py -k action_status -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/psm/synth.py tests/test_synth.py
git commit -m "feat(synth): action/schedule status against frozen reference_date"
```

---

### Task 5: Severity & risk classification

**Blocked by:** Task 1.
**Unblocks:** Task 7. (Independent of Tasks 2–4, 6 — the largest single task; consider doing it alone.)

**Files:**
- Modify: `src/psm/synth.py`
- Modify: `tests/test_synth.py`

**Interfaces:**
- Consumes: nothing from other synth tasks (pure function of `incident_types`, `property_damage_usd`, `rules`).
- Produces: `synth_severity_fields(incident_types: frozenset[str], property_damage_usd: float | None, rules: dict) -> tuple[dict[str, Any], list[dict[str, Any]]]` — `(fields, anomalies)`, where `fields` has keys `incident_classification`, `worst_reasonable_outcome`, `involves_fatality_or_injury`, `hs_risk_score`, `environment_reputation_classification`, `environment_reputation_score`, `financial_classification`, `financial_score`, `unmitigated_risk_score`, `mitigated_risk_score`, and `anomalies` is a list of `{"type": str, "note": str}` dicts.

**Definition of Done:** Fatality → Very Serious/9; multiple checkboxes spanning tiers → highest wins; resolved-but-unlisted type → Incident tier (2), not Unknown; empty `incident_types` → `"Unknown"`/`None` + a logged anomaly; missing `property_damage_usd` → `"Unknown"`/`None` + a logged anomaly; financial threshold boundary is exact ($25,000.00 → Minor, $25,000.01 → Moderate); `mitigated_risk_score <= unmitigated_risk_score` always, floored at `rules["mitigation_floor"]`, never negative.

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_synth.py
from psm.synth import synth_severity_fields


def test_fatality_maps_to_very_serious():
    rules = load_rules()
    fields, anomalies = synth_severity_fields(frozenset({"Fatality"}), 50000.0, rules)
    assert fields["incident_classification"] == "Very Serious"
    assert fields["worst_reasonable_outcome"] == "Very Serious"
    assert fields["involves_fatality_or_injury"] is True
    assert fields["hs_risk_score"] == 9
    assert fields["unmitigated_risk_score"] == 9
    assert fields["mitigated_risk_score"] == 7
    assert anomalies == []


def test_multiple_checkboxes_spanning_tiers_takes_highest():
    rules = load_rules()
    fields, _ = synth_severity_fields(frozenset({"Fire", "Fatality"}), 1000.0, rules)
    assert fields["incident_classification"] == "Very Serious"


def test_resolved_but_unlisted_type_falls_back_to_incident_tier():
    rules = load_rules()
    fields, anomalies = synth_severity_fields(frozenset({"Crane"}), 1000.0, rules)
    assert fields["incident_classification"] == "Incident"
    assert fields["hs_risk_score"] == 2
    assert fields["mitigated_risk_score"] == 1  # floored, not negative
    assert anomalies == []


def test_empty_incident_types_is_unknown_and_logged():
    rules = load_rules()
    fields, anomalies = synth_severity_fields(frozenset(), 1000.0, rules)
    assert fields["incident_classification"] == "Unknown"
    assert fields["hs_risk_score"] is None
    assert fields["unmitigated_risk_score"] is None
    assert fields["mitigated_risk_score"] is None
    assert any(a["type"] == "unresolved_incident_classification" for a in anomalies)


def test_pollution_gates_environment_score():
    rules = load_rules()
    with_pollution, _ = synth_severity_fields(frozenset({"Fatality", "Pollution"}), 1000.0, rules)
    without_pollution, _ = synth_severity_fields(frozenset({"Fatality"}), 1000.0, rules)
    assert with_pollution["environment_reputation_classification"] == "Very Serious"
    assert with_pollution["environment_reputation_score"] == 9
    assert without_pollution["environment_reputation_classification"] == "None"
    assert without_pollution["environment_reputation_score"] == 0


def test_financial_thresholds_are_boundary_exact():
    rules = load_rules()
    at_25000, _ = synth_severity_fields(frozenset({"Crane"}), 25000.0, rules)
    just_over, _ = synth_severity_fields(frozenset({"Crane"}), 25000.01, rules)
    assert at_25000["financial_classification"] == "Minor"
    assert just_over["financial_classification"] == "Moderate"


def test_missing_property_damage_is_unknown_and_logged():
    rules = load_rules()
    fields, anomalies = synth_severity_fields(frozenset({"Crane"}), None, rules)
    assert fields["financial_classification"] == "Unknown"
    assert fields["financial_score"] is None
    assert any(a["type"] == "unresolved_property_damage" for a in anomalies)


def test_mitigated_never_exceeds_unmitigated():
    rules = load_rules()
    for types in (frozenset({"Fatality"}), frozenset({"Injury"}), frozenset({"Crane"})):
        fields, _ = synth_severity_fields(types, 1000.0, rules)
        assert fields["mitigated_risk_score"] <= fields["unmitigated_risk_score"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_synth.py -k severity -v`
Expected: FAIL with `ImportError: cannot import name 'synth_severity_fields'`

- [ ] **Step 3: Implement**

```python
# append to src/psm/synth.py
def synth_severity_fields(
    incident_types: frozenset[str],
    property_damage_usd: float | None,
    rules: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    anomalies: list[dict[str, Any]] = []

    checkbox_tiers = [t for t in rules["severity_tier_order"] if t in rules["severity_tiers"]]
    tier: str | None = None
    for candidate in checkbox_tiers:
        if incident_types & set(rules["severity_tiers"][candidate]):
            tier = candidate
            break
    if tier is None and incident_types:
        tier = "Incident"
    if tier is None:
        anomalies.append({
            "type": "unresolved_incident_classification",
            "note": "incident_types empty or contains no recognised label",
        })

    hs_score = rules["hs_risk_score_by_tier"][tier] if tier else None
    pollution = rules["pollution_label"] in incident_types
    if tier is None:
        env_class, env_score = "Unknown", None
    elif pollution:
        env_class, env_score = tier, hs_score
    else:
        env_class, env_score = "None", 0

    if property_damage_usd is None:
        fin_class, fin_score = "Unknown", None
        anomalies.append({
            "type": "unresolved_property_damage",
            "note": "property_damage_usd is None",
        })
    else:
        fin_class = next(
            t["classification"]
            for t in rules["financial_thresholds_usd"]
            if t["max_usd"] is None or property_damage_usd <= t["max_usd"]
        )
        fin_score = rules["financial_score_by_classification"][fin_class]

    mitigated = (
        max(hs_score - rules["mitigation_delta"], rules["mitigation_floor"])
        if hs_score is not None else None
    )

    fields = {
        "incident_classification": tier or "Unknown",
        "worst_reasonable_outcome": tier or "Unknown",
        "involves_fatality_or_injury": bool(set(rules["fatality_injury_labels"]) & incident_types),
        "hs_risk_score": hs_score,
        "environment_reputation_classification": env_class,
        "environment_reputation_score": env_score,
        "financial_classification": fin_class,
        "financial_score": fin_score,
        "unmitigated_risk_score": hs_score,
        "mitigated_risk_score": mitigated,
    }
    return fields, anomalies
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_synth.py -k severity -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/psm/synth.py tests/test_synth.py
git commit -m "feat(synth): severity/risk classification, single tier reused across categories"
```

---

### Task 6: Incident title (cheap extra)

**Blocked by:** Task 1.
**Unblocks:** Task 7. (Independent of Tasks 2–5 — smallest task, good for a quick win.)

**Files:**
- Modify: `src/psm/synth.py`
- Modify: `tests/test_synth.py`

**Interfaces:**
- Consumes: nothing from other synth tasks.
- Produces: `synth_incident_title(incident_types: frozenset[str], area_block: str, rules: dict) -> str`.

**Definition of Done:** Templates real `incident_types` + `area_block` via `rules["incident_title_template"]`; empty `incident_types` produces a legible fallback, never `"None incident at ..."`.

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_synth.py
from psm.synth import synth_incident_title


def test_incident_title_happy_path():
    rules = load_rules()
    assert synth_incident_title(frozenset({"Fatality"}), "MP 298", rules) == "Fatality incident at MP 298"


def test_incident_title_multiple_types_sorted_for_determinism():
    rules = load_rules()
    assert synth_incident_title(frozenset({"Fire", "Crane"}), "MP 298", rules) == "Crane, Fire incident at MP 298"


def test_incident_title_empty_types_uses_fallback():
    rules = load_rules()
    assert synth_incident_title(frozenset(), "MP 298", rules) == "Unspecified incident at MP 298"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_synth.py -k incident_title -v`
Expected: FAIL with `ImportError: cannot import name 'synth_incident_title'`

- [ ] **Step 3: Implement**

```python
# append to src/psm/synth.py
def synth_incident_title(incident_types: frozenset[str], area_block: str, rules: dict[str, Any]) -> str:
    label = ", ".join(sorted(incident_types)) if incident_types else "Unspecified"
    return rules["incident_title_template"].format(incident_type=label, area_block=area_block)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_synth.py -k incident_title -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/psm/synth.py tests/test_synth.py
git commit -m "feat(synth): templated incident title (reformatting, not fabrication)"
```

---

### Task 7: `synthesize_row()` — public entrypoint + column manifest

**Blocked by:** Tasks 2, 3, 4, 5, 6 (composes all of them — the integration point).
**Unblocks:** Tasks 8, 9.

**Files:**
- Modify: `src/psm/synth.py`
- Modify: `tests/test_synth.py`

**Interfaces:**
- Consumes: `validate_row`, `synth_identity_fields`, `synth_date_fields`, `synth_status_fields`, `synth_severity_fields`, `synth_incident_title` — all from Tasks 1–6.
- Produces: `synthesize_row(row: dict, rules: dict) -> dict[str, Any]` — every key `syn_`-prefixed except a bare `anomalies` meta-key (list of anomaly dicts, matching `extract.py`'s `rec["anomalies"]` convention; not a `data/processed/incidents.csv` column, stripped/redirected to `data/interim/anomalies.jsonl` by whatever future module assembles that CSV). Also produces `SYN_COLUMN_MANIFEST: dict[str, dict[str, Any]]`, one entry per `syn_` column, `{"description": str, "fabricated": True}`.

**Definition of Done:** `set(synthesize_row(row, rules)) - {"anomalies"} == set(SYN_COLUMN_MANIFEST)` (mechanical proof the manifest can't silently drift from the real output — this is the fix for the "manifest goes stale" finding from the misleading-data review); fully deterministic; the composed date chain holds; a row missing a required key raises `KeyError` via `validate_row`.

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_synth.py
from psm.synth import SYN_COLUMN_MANIFEST, synthesize_row


def test_synthesize_row_output_keys_match_manifest(make_row):
    rules = load_rules()
    out = synthesize_row(make_row(), rules)
    data_keys = set(out) - {"anomalies"}
    assert data_keys == set(SYN_COLUMN_MANIFEST)


def test_synthesize_row_is_fully_deterministic(make_row):
    rules = load_rules()
    row = make_row()
    assert synthesize_row(row, rules) == synthesize_row(row, rules)


def test_synthesize_row_validates_input(make_row):
    rules = load_rules()
    bad_row = make_row()
    del bad_row["area_block"]
    with pytest.raises(KeyError):
        synthesize_row(bad_row, rules)


def test_synthesize_row_date_chain_is_internally_consistent(make_row):
    rules = load_rules()
    out = synthesize_row(make_row(), rules)
    assert out["syn_approval_date"] >= out["syn_date_of_report"]
    assert out["syn_close_out_date"] >= out["syn_approval_date"]
    assert out["syn_action_due_date"] >= out["syn_approval_date"]
    assert out["syn_agreed_completion_date"] >= out["syn_approval_date"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_synth.py -k synthesize_row -v`
Expected: FAIL with `ImportError: cannot import name 'synthesize_row'`

- [ ] **Step 3: Implement**

```python
# append to src/psm/synth.py
SYN_COLUMN_MANIFEST: dict[str, dict[str, Any]] = {
    "syn_investigation_lead_name": {"description": "Hash-token identity placeholder (SYN-Investigator-<hex6>)", "fabricated": True},
    "syn_investigation_lead_position": {"description": "Fixed placeholder role title", "fabricated": True},
    "syn_incident_classified_by_name": {"description": "Hash-token identity placeholder (SYN-Classifier-<hex6>)", "fabricated": True},
    "syn_incident_classified_by_position": {"description": "Fixed placeholder role title", "fabricated": True},
    "syn_investigation_acceptor_name": {"description": "Hash-token identity placeholder (SYN-Acceptor-<hex6>)", "fabricated": True},
    "syn_investigation_acceptor_position": {"description": "Fixed placeholder role title", "fabricated": True},
    "syn_close_out_approval_name": {"description": "Hash-token identity placeholder (SYN-Approver-<hex6>)", "fabricated": True},
    "syn_close_out_approval_position": {"description": "Fixed placeholder role title", "fabricated": True},
    "syn_responsible_owner_name": {"description": "Hash-token identity placeholder (SYN-Owner-<hex6>)", "fabricated": True},
    "syn_responsible_owner_position": {"description": "Fixed placeholder role title", "fabricated": True},
    "syn_date_of_report": {"description": "incident_date + 5-15 days (deterministic hash offset)", "fabricated": True},
    "syn_approval_date": {"description": "date_of_report + 14-45 days", "fabricated": True},
    "syn_close_out_date": {"description": "approval_date + 30-90 days", "fabricated": True},
    "syn_action_due_date": {"description": "approval_date + 30-180 days", "fabricated": True},
    "syn_agreed_completion_date": {"description": "approval_date + 30-180 days", "fabricated": True},
    "syn_action_status": {"description": "Pending/In Progress/Completed by age vs. frozen reference_date", "fabricated": True},
    "syn_schedule_status": {"description": "On Schedule/Behind/N-A, hash tiebreak unless Completed", "fabricated": True},
    "syn_incident_classification": {"description": "Very Serious/Serious/Incident/Unknown from real incident_types", "fabricated": True},
    "syn_worst_reasonable_outcome": {"description": "Mirrors incident_classification", "fabricated": True},
    "syn_involves_fatality_or_injury": {"description": "Boolean from real incident_types", "fabricated": True},
    "syn_hs_risk_score": {"description": "9/5/2/null encoding of incident_classification", "fabricated": True},
    "syn_environment_reputation_classification": {"description": "Tier name / None / Unknown, gated on Pollution checkbox", "fabricated": True},
    "syn_environment_reputation_score": {"description": "Reuses hs_risk_score value when Pollution set, else 0/null", "fabricated": True},
    "syn_financial_classification": {"description": "Minor/Moderate/Major from real property_damage_usd", "fabricated": True},
    "syn_financial_score": {"description": "2/5/9 encoding of financial_classification", "fabricated": True},
    "syn_unmitigated_risk_score": {"description": "Equals hs_risk_score", "fabricated": True},
    "syn_mitigated_risk_score": {"description": "max(unmitigated - mitigation_delta, mitigation_floor)", "fabricated": True},
    "syn_incident_title": {"description": "Templated from real incident_types + area_block", "fabricated": True},
}


def synthesize_row(row: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    validate_row(row)
    report_id = row["report_id"]

    fields: dict[str, Any] = {}
    fields.update(synth_identity_fields(report_id, rules))
    fields.update(synth_date_fields(report_id, row["incident_date"], rules))
    fields.update(synth_status_fields(report_id, row["incident_date"], rules))
    severity_fields, anomalies = synth_severity_fields(
        row["incident_types"], row["property_damage_usd"], rules
    )
    fields.update(severity_fields)
    fields["incident_title"] = synth_incident_title(row["incident_types"], row["area_block"], rules)

    out = {f"syn_{key}": value for key, value in fields.items()}
    out["anomalies"] = anomalies
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_synth.py -v`
Expected: all tests pass (Tasks 1–7 combined)

- [ ] **Step 5: Commit**

```bash
git add src/psm/synth.py tests/test_synth.py
git commit -m "feat(synth): synthesize_row entrypoint + SYN_COLUMN_MANIFEST"
```

---

### Task 8: Rule-traceability check + `tests/test_conventions.py`

**Blocked by:** Task 7 (needs the finished module and `SYN_COLUMN_MANIFEST`).
**Unblocks:** nothing further in this plan (leaf task; can run in parallel with Task 9).

**Files:**
- Create: `tests/test_conventions.py`
- Modify: `tests/test_synth.py`

**Interfaces:**
- Consumes: `SYN_COLUMN_MANIFEST`, `load_rules`, `synthesize_row` from Task 7.
- Produces: nothing new consumed elsewhere — this task is pure verification.

**Definition of Done:** A bare numeric literal added to `synth.py` outside the documented allowlist fails the traceability test (verify by temporarily adding `+ 7` to a return value, confirming the test catches it, then reverting); every `synthesize_row` output key carries a valid provenance prefix; `synth.py` never emits an `xw_`-prefixed key.

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_synth.py
import ast

REPO = Path(__file__).resolve().parents[1]
ALLOWED_LITERALS = {0, 1, 2}  # % 2 tiebreak in synth_status_fields; 0 default in synth_severity_fields


def _numeric_literals_in(source: str) -> set[float]:
    tree = ast.parse(source)
    found: set[float] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            found.add(node.value)
    return found


def test_no_unexplained_numeric_literals_in_synth():
    """Mechanical half of 'every syn_ column traces to a rule' — scoped
    honestly to numeric literals only. String literals (role names, tier
    names) are traced by convention + code review, not by this test; see
    docs/superpowers/specs/2026-08-09-synth-fields-design.md Testing section."""
    source = (REPO / "src" / "psm" / "synth.py").read_text()
    found = _numeric_literals_in(source)
    unexplained = found - ALLOWED_LITERALS
    assert not unexplained, (
        f"numeric literal(s) {unexplained} in synth.py not in ALLOWED_LITERALS — "
        "move to schema/synth_rules.yaml, or extend ALLOWED_LITERALS with justification"
    )
```

(add `from pathlib import Path` to the top of `tests/test_synth.py` if not already present)

```python
# tests/test_conventions.py
"""Column-provenance convention checks for src/psm/synth.py's output.

Scope note: this only covers synth.py's own syn_-prefixed output. No module
yet assembles the full src_/xw_/llm_/gold_/syn_ table — data/processed/
incidents.csv and src/psm/crosswalk.py do not exist yet (see
docs/superpowers/plans/2026-08-09-synth-fields-implementation.md, Scope
Boundary). Extend this file to check the assembled table's columns once that
module exists.
"""
from __future__ import annotations

from psm.synth import load_rules, synthesize_row

VALID_PREFIXES = ("src_", "xw_", "llm_", "gold_", "syn_")


def test_every_synth_output_column_has_a_valid_prefix(make_row):
    rules = load_rules()
    out = synthesize_row(make_row(), rules)
    data_keys = set(out) - {"anomalies"}
    for key in data_keys:
        assert key.startswith(VALID_PREFIXES), f"{key!r} carries no provenance prefix"


def test_synth_never_emits_xw_columns(make_row):
    rules = load_rules()
    out = synthesize_row(make_row(), rules)
    assert not any(k.startswith("xw_") for k in out), (
        "synth.py must never emit xw_ — see the xw_/syn_ boundary rule in CLAUDE.md"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_synth.py -k literals tests/test_conventions.py -v`
Expected: FAIL — `test_conventions.py` not collected / `ModuleNotFoundError` style failure since the file didn't exist before this step; the literals test should actually already PASS at this point since Task 5–7's implementation was written literal-free by design — if it fails, that's real signal to go fix `synth.py` before continuing, not to loosen the allowlist without justification.

- [ ] **Step 3: Confirm implementation (no synth.py changes expected)**

No new production code — Tasks 1–7's implementation was written to already satisfy these checks. If `test_no_unexplained_numeric_literals_in_synth` fails, find the offending literal, either move its value into `schema/synth_rules.yaml` or add it to `ALLOWED_LITERALS` with a one-line comment justifying why it's structural rather than a tunable threshold.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_synth.py tests/test_conventions.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add tests/test_synth.py tests/test_conventions.py
git commit -m "test(synth): rule-traceability + provenance-prefix convention checks"
```

---

### Task 9: Docs — `docs/_synth.md`, README, CLAUDE.md

**Blocked by:** Task 7 (needs the final field list to describe accurately).
**Unblocks:** nothing further in this plan (leaf task; can run in parallel with Task 8).

**Files:**
- Create: `docs/_synth.md`
- Modify: `README.md`
- Modify: `psm-incident-ml/CLAUDE.md` (i.e. `CLAUDE.md` at the repo root)

**Interfaces:** none (docs only, no code).

**Definition of Done:** `docs/_synth.md` explains purpose, the frozen `reference_date`, the fatality-adjacency flag, and the Unknown/anomaly-log policy in plain language; README's real-vs-generated table and "why any synthetic data" paragraph match the actual (now much larger) field set instead of the stale "administrative wrapper fields" description; `CLAUDE.md` states the `xw_`/`syn_` boundary rule the spec promised it would.

- [ ] **Step 1: Write `docs/_synth.md`**

```markdown
# Synthetic fields — what they are and are not

`src/psm/synth.py` fills 28 columns that the E19 target schema
(`schema/e19_target.yaml`) expects but that BSEE's public reports never
contain — investigator names, approval dates, risk-matrix scores,
recommendation-tracking status. Every one of them is prefixed `syn_` and
generated by a documented, deterministic rule in `schema/synth_rules.yaml`.
See `docs/superpowers/specs/2026-08-09-synth-fields-design.md` (rev 2) for
the full design rationale.

## What these columns are for

Pipeline and feature-engineering practice — so a hackathon participant can
run a complete E19-shaped row through a full ML pipeline, not just the
subset BSEE happens to publish. They are **never** eligible to be scored as
if they were `gold_` (human-labelled) data, and no metric should ever be
reported against them as if predicting a `syn_` column meant something about
real industrial risk. The generation rules are public and readable in
`schema/synth_rules.yaml` — "predicting" them by reading the source is
expected, not a finding.

## Why some rows carry more caution than others

`syn_involves_fatality_or_injury` is a machine-readable flag, sourced from
the real `src_f07_type` checkboxes, that any downstream tool can check
before displaying a `syn_` score next to a row. A fabricated risk number
sitting next to a real fatality is a sharper mislabeling risk than the same
number next to property damage only — this flag exists so that risk can be
handled programmatically instead of relying on a reader noticing the prefix.

## The frozen reference date

`syn_action_status` and `syn_schedule_status` depend on how old a report is.
That age is computed against `reference_date` in `schema/synth_rules.yaml` —
a fixed, committed date, never the wall clock. Regenerating the dataset next
year reproduces byte-identical output, because "now" is a value in a file,
not a call to `date.today()`. Bump `reference_date` only deliberately, as a
new dataset generation.

## When a real field can't be resolved

If `src_f07_type` has no checkbox the extractor could resolve, or the
extracted property-damage figure could not be parsed, the corresponding
`syn_` fields are `"Unknown"` / `null` — never guessed — and the row is
logged with an anomaly entry, matching the `data/interim/anomalies.jsonl`
convention used elsewhere in this project. Multiple checkboxes spanning
severity tiers resolve to the highest tier, not an average or a random pick.

## Provenance manifest

`data/processed/incidents.columns.json` (once the full assembly pipeline
exists) will carry a machine-readable `{column: {prefix, provenance,
description, fabricated}}` entry for every column, including these, so a
participant who downloads only the CSV still has a co-located, parseable
disclosure — the `syn_` prefix on the header row is the first signal, not
the only one.
```

- [ ] **Step 2: Update `README.md`**

Replace this row (currently line 38):

```
| Administrative wrapper fields (reporter names, internal IDs, sign-offs) | **Synthetic** (`syn_`) — the E19 template needs them; BSEE does not publish them |
```

with:

```
| Administrative + risk-matrix fields (reporter names, approval chain, incident severity/risk scores, recommendation tracking) | **Synthetic** (`syn_`) — the E19 template needs them; BSEE does not publish them. See [`docs/_synth.md`](docs/_synth.md) |
```

Replace this paragraph (currently lines 40–44):

```
**Why any synthetic data at all?** The E19 investigation-report structure
includes administrative fields (who reported it, internal tracking IDs,
sign-off chains) that BSEE reports do not contain and that no public source
provides. Those are generated so the schema is complete and demonstrable. They
are never used as features or labels, and they are always `syn_`-prefixed.
```

with:

```
**Why any synthetic data at all?** The E19 investigation-report structure
includes administrative and risk-scoring fields (who reported it, internal
tracking IDs, sign-off chains, severity/risk-matrix scores) that BSEE reports
do not contain and that no public source provides. Those are generated by
[`src/psm/synth.py`](src/psm/synth.py) from documented, deterministic rules in
[`schema/synth_rules.yaml`](schema/synth_rules.yaml) — see
[`docs/_synth.md`](docs/_synth.md) for the plain-language version. They are
never used as features or labels, and they are always `syn_`-prefixed.
```

- [ ] **Step 3: Update `CLAUDE.md`**

Insert this new section immediately after the existing `## The crosswalk is data, not code` section:

```markdown
## The `xw_`/`syn_` boundary

`xw_` requires an external, independently published source (today:
`schema/crosswalk.yaml`'s BSEE-category -> EI element mapping). A `synth.py`
rule may take a real BSEE convention as *inspiration* for a threshold's shape
(e.g. picking a round dollar figure BSEE itself uses as an order-of-magnitude
reference) without qualifying as `xw_` — inspiration is not sourcing. Every
`src/psm/synth.py` output is `syn_`, full stop, even when it's derived from a
real `src_` column, because the *mapping* (which tier a value falls into) is
our own invented judgment, not an external authority's.
```

- [ ] **Step 4: Verify docs render and links resolve**

Run: `grep -c "syn_" docs/_synth.md` (expect > 0) and manually confirm every relative link in the three edited files (`docs/_synth.md`, `schema/synth_rules.yaml`, `src/psm/synth.py`) points to a file that exists in the repo after Task 7.

- [ ] **Step 5: Commit**

```bash
git add docs/_synth.md README.md CLAUDE.md
git commit -m "docs(synth): add docs/_synth.md, update README + CLAUDE.md xw_/syn_ boundary"
```

---

## Self-Review Notes

- **Spec coverage:** every field in the rev-2 spec's catalog (10 identity, 5+2 date/status, 10 severity/risk, 1 title = 28) has a task, a manifest entry, and a test. The manifest sidecar JSON file itself (`data/processed/incidents.columns.json`) is explicitly deferred to the future assembly module per the Scope Boundary — `SYN_COLUMN_MANIFEST` (Task 7) is the in-code source that module will read from, so no work is lost, just sequenced correctly.
- **Placeholder scan:** no TBD/TODO; every code block is complete and runnable as written.
- **Type consistency:** `report_id: str`, `incident_date: date`, `incident_types: frozenset[str]`, `property_damage_usd: float | None`, `area_block: str` are used identically across Tasks 1–7; `rules: dict[str, Any]` threaded consistently; `synth_severity_fields` returning `tuple[dict, list[dict]]` is the one two-value return in the module and is documented as such everywhere it's called (Task 5's Interfaces block, Task 7's Interfaces block and implementation).
- **Real gap surfaced, not hidden:** `report_id` does not exist as a named column anywhere in the current codebase (`spine.py`, `harvest.py`, `extract.py` all checked) — this plan resolves it to `src_sha256`, already unique per PDF in both `data/manifest.csv` and `extract_report()`'s output, rather than inventing a new ID scheme. Flagged explicitly in the Row Input Contract table so it isn't silently assumed.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-09-synth-fields-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Tasks 2, 3, 4, 5, 6 are mutually independent once Task 1 lands, so several can run in parallel before Task 7 integrates them.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
