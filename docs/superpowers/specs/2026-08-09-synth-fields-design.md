# Design: synthetic (`syn_`) field generation for the E19 target schema

Date: 2026-08-09
Status: approved, not yet implemented

## Problem

The real workbook (`E19 Investigation Report - Rev2.xlsx`, never committed —
see `CLAUDE.md`) defines a much larger field set than public BSEE data can
ever populate: personnel/approval identity, numeric risk-matrix scoring
(Health & Safety, Environment & Reputation, Financial Cost & Business), a
4-axis incident-type classification, and recommendation-tracking metadata
(owner, schedule status, mitigated risk). None of this is published by BSEE
and none of it can be. `schema/e19_target.yaml`'s original `synthetic_fields`
list predates this discovery and is incomplete relative to the real field set.

This spec defines how `src/psm/synth.py` fills those columns so the final
`data/processed/incidents.csv` has the full E19 row shape, without
misrepresenting fabricated values as real, and without reverse-engineering
anything from the workbook we are barred from deriving into a public repo.

## Purpose (locked decision)

Synthetic fields are **ML-plausible correlated targets**: internally
consistent with real fields (a fatality incident gets a high severity tier;
close-out dates follow report dates) so a hackathon participant can practice
a full pipeline against the complete row shape — not pure unconditioned
filler, and not an attempt to recover real risk-assessment signal.

**Resolved tension:** the repo is public and MIT-licensed, so the generation
logic in `synth.py` is readable by anyone. A fully transparent deterministic
rule (`if fatality: severity = high`) makes "predicting" these columns
trivial by reading the source — that's accepted deliberately. The purpose is
pipeline/shape completeness and feature-engineering practice, **not** a
benchmarkable prediction target. This must be stated plainly in docs so no
one mistakes strong agreement with `synth.py`'s output for having learned
something real about industrial risk.

## Architecture

- **`schema/synth_rules.yaml`** — every threshold, tier mapping, and fixed
  word-list, as editable data. Mirrors `crosswalk.yaml`'s existing pattern
  ("the crosswalk is data, not code" — same principle applies here).
- **`src/psm/synth.py`** — the engine: applies `synth_rules.yaml`, plus the
  parts that can't be pure data (deterministic hashing for identity tokens,
  date arithmetic).
- **No hidden randomness.** Any field needing variety with no real signal to
  derive it from uses `int(sha256(report_id + salt), 16) % N` — fully
  deterministic, reproducible with zero stored seed, not presented as
  meaningful. Preserves the existing byte-identical-from-fresh-clone
  reproducibility contract without adding seed management.
- **`xw_` stays reserved for the one crosswalk grounded in an external
  authority** (BSEE cause category → EI PSM element number, via
  `crosswalk.yaml`). Every `synth.py` output is `syn_`, even fields that take
  real BSEE columns as input (e.g. severity tier from incident-type
  checkboxes) — the *mapping* is our own invented judgment, not sourced
  externally. State this explicitly in `CLAUDE.md` so a future contributor
  doesn't "upgrade" a synth rule to `xw_` because it references real columns.

## Field catalog

### Identity fields

Obviously-synthetic tokens, deterministic hash of `report_id` + a per-role
salt so roles never collide on one report. Chosen over plausible-sounding
fake names specifically to prevent a fabricated name being mistaken for a
real person if a row is shared without provenance context.

| Field | Rule |
|---|---|
| `syn_investigation_lead_{name,position}` | `Investigator-{hash4}` (first 4 hex chars of `sha256(report_id + "lead")`) + position from a fixed pool (Senior Safety Engineer, District Investigator, Compliance Officer, Field Supervisor), picked via `hash % len(pool)` |
| `syn_incident_classified_by_{name,position}` | same pattern, different salt |
| `syn_investigation_acceptor_{name,position}` | same pattern, different salt |
| `syn_close_out_approval_{name,position}` | same pattern, different salt |
| `syn_responsible_owner_{name,position}` (recommendations) | same pattern, different salt |

`Incident Number` is **not** synthetic — already a real field from the spine
index. This corrects `e19_target.yaml`'s original list, written before the
spine work existed.

### Workflow dates

Deterministic offsets from the real incident date; hash trick supplies
variety without inventing meaning.

| Field | Rule |
|---|---|
| `syn_date_of_report` | incident date + 5–15 days (hash-picked in range) |
| `syn_approval_date` | date_of_report + 14–45 days |
| `syn_close_out_date` | approval_date + 30–90 days |
| `syn_action_due_date` / `syn_agreed_completion_date` | approval_date + 30–180 days |
| `syn_action_status` / `syn_schedule_status` | rule on report age: >2yr → Completed; 6mo–2yr → On Schedule / Behind (hash tiebreak); <6mo → Pending |

### Severity & risk classification

The part meant to feel like a real target — built only from real fields
already extracted (`src_f07` type checkboxes, `src_f21` property damage).

| Field | Derived from | Rule |
|---|---|---|
| `syn_incident_classification` | `src_f07` type checkboxes | Fatality/Blowout/Explosion → Very Serious; Injury/LWC/Fire/Collision → Serious; else → Incident |
| `syn_worst_reasonable_outcome` | mirrors classification | documented as "same tier, no independent signal to diverge" |
| `syn_hs_consequence` / `syn_hs_likelihood` / `syn_hs_risk_score` | incident type (consequence); activity/operation field (likelihood — weaker, flagged low-confidence like `crosswalk.yaml`'s tiers) | risk_score = consequence_tier × likelihood_tier — our own formula, not reverse-engineered from the workbook |
| `syn_environment_reputation_classification/score` | Pollution checkbox + damage tier | documented threshold table |
| `syn_financial_classification/score` | real `src_f21` | dollar-threshold table — cleanest mapping; BSEE's own field 7 already uses a $25K threshold as precedent |
| `syn_unmitigated_risk_score` | mirrors incident's own severity score | — |
| `syn_mitigated_risk_score` | unmitigated score − one fixed tier | represents "recommendations reduce risk," transparent |

### Cheap extras

`syn_incident_title` — templated from real fields
(`f"{incident_type} incident at {area_block}"`), a formatted label more than
a fabrication, included since it's free.

## Explicit non-goals

- **Incident Type A/B/C/D axis is out of scope for v1.** BSEE's single-axis
  type checkboxes don't decompose into the workbook's 4-axis scheme (loss-
  event type × H&S/Env/Business area × injury type × department) with any
  real basis. Logged in `docs/findings.md` as a known gap, not fabricated —
  same policy as `crosswalk.yaml`'s `orphan_subcategory_policy:
  leave_unmapped`.
- **No workbook formulas are replicated.** Every scoring rule above is
  designed from scratch, never reverse-engineered from the actual workbook,
  consistent with the standing rule against deriving anything into the
  public repo from it.

## Labeling & docs

- README's real-vs-generated table names every `syn_` column and links to
  `synth_rules.yaml` as the exact recipe.
- `docs/_synth.md` (same pattern as `docs/_harvest.md`): plain-language
  statement that these columns are a documented deterministic function of
  real fields, not measured or observed data — useful for full-pipeline
  practice, never eligible to be scored as if `gold_`.

## Testing (`tests/test_synth.py`)

- Determinism: same input row run twice → byte-identical output.
- Date-ordering invariant: `incident_date ≤ date_of_report ≤ approval_date ≤
  close_out_date` holds for every generated row.
- Every `syn_` column traces to a `synth_rules.yaml` entry or a documented
  pure function — no unexplained literals in `synth.py`.
- Identity tokens never collide across roles on the same report.

## Convention enforcement

`tests/test_conventions.py` (not yet written, already on the backlog) is
extended rather than built twice: every column in the final assembled table
must start with `src_`, `xw_`, `llm_`, `gold_`, or `syn_`, and specifically no
`synth.py` output may carry `xw_` — enforcing the architecture rule
mechanically instead of only documenting it.
