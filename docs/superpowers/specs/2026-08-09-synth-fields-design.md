# Design: synthetic (`syn_`) field generation for the E19 target schema

Date: 2026-08-09 (rev. 2026-08-09b — revised after adversarial review)
Status: revised, pending user re-approval

**Revision note:** Rev 2 incorporates fixes from four adversarial spec-critic
passes (internal consistency, scope/YAGNI, misleading-data risk,
testability). Every change below traces to a specific finding; see inline
callouts. No new scope was added — every change either fixes a
self-contradiction, closes a labeling/safety gap, or *removes* scope that the
review showed didn't earn its complexity.

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

**Added in rev 2:** because real BSEE incident rows include fatalities and
injuries, fabricated severity/risk numbers sitting next to a real death are a
sharper mislabeling risk than the same numbers next to property damage. This
spec now treats that adjacency as a first-class case, not an afterthought —
see the fatality-adjacency flag below and the Labeling & docs section.

## Architecture

- **`schema/synth_rules.yaml`** — every threshold, tier mapping, fixed
  word-list, and the **frozen `reference_date`** (see Workflow dates below),
  as editable data. Mirrors `crosswalk.yaml`'s existing pattern ("the
  crosswalk is data, not code" — same principle applies here).
- **`src/psm/synth.py`** — the engine: applies `synth_rules.yaml`, plus the
  parts that can't be pure data (deterministic hashing for identity tokens,
  date arithmetic).
- **No hidden randomness, and no hidden wall-clock dependency.** Any field
  needing variety with no real signal to derive it from uses
  `int(sha256(report_id + salt), 16) % N` — fully deterministic, reproducible
  with zero stored seed. *(Fix for consistency-review finding #1 / testability
  finding #1: the earlier draft's "report age" rule silently depended on
  `date.today()`, which would have made output drift every time the pipeline
  reran on a later date — a direct violation of the byte-identical
  reproducibility contract this section claims. Every age-based rule in this
  spec now computes age against `synth_rules.yaml`'s frozen `reference_date`,
  never wall-clock time.)*
- **`xw_` vs `syn_` boundary — revised test.** `xw_` requires an external,
  independently published crosswalk table (today: BSEE cause category → EI
  PSM element number, via `crosswalk.yaml`). A `synth.py` rule may take real
  BSEE conventions as *inspiration* for a threshold's shape (e.g. picking a
  round dollar figure in the same order of magnitude BSEE itself uses)
  without qualifying as `xw_` — inspiration is not sourcing. Every
  `synth.py` output is `syn_`, full stop, even fields derived from real BSEE
  columns, because the *mapping* (which tier a value falls into) is our own
  invented judgment. State this explicitly in `CLAUDE.md`. *(Fix for
  consistency-review finding #2: the original financial-field rule justified
  itself by citing "BSEE's own field 7 already uses a $25K threshold as
  precedent" — which is exactly the "sourced externally" language the
  boundary rule was written to exclude. That justification is removed below;
  the field keeps its threshold but the doc no longer claims external
  grounding for it.)*
- **Machine-readable provenance manifest — new in rev 2.**
  `data/processed/incidents.columns.json` ships in the same directory as
  `incidents.csv`: `{column_name: {prefix, provenance, description,
  fabricated: bool}}` for every column. *(Fix for misleading-data-review
  finding #1/#2: the original plan's only safeguard was the `syn_` prefix
  plus prose in the README and `docs/_synth.md` — both live outside the CSV,
  and neither survives a downstream `df.rename()`, a dashboard label, or a
  participant who downloads only the CSV via a raw-file link. The prefix
  string is still the primary signal; the manifest is the machine-checkable
  fallback that `tests/test_conventions.py` can enforce stays complete.)*

## Field catalog

### Identity fields

*Revised in rev 2.* Tokens now carry an unambiguous `SYN-` marker rather than
a bare `Investigator-{hash}` pattern, and job-title text is a fixed
placeholder per role rather than a pool of ordinary-sounding real titles.
*(Fix for misleading-data-review finding #4/#8: `Investigator-a3f2` reads
structurally identical to real-world anonymized-ID conventions — badge
numbers, redacted-witness IDs — used by agencies and journalists for actual
people, which is precisely the confusion this field exists to prevent,
especially sitting next to a real fatality record. The position pool of
plausible real job titles carried the same risk with no synthetic marker at
all. Fix for scope-review finding #2: the position pool's hash-selection
machinery existed only to add variety a shape-completeness field doesn't
need — a fixed placeholder removes that machinery entirely.)*

Hash tokens widened from 4 to 6 hex chars (16.7M-value space) so expected
identity-token collisions across the full ~1,300-report corpus are
negligible — documented as an empirical property, not claimed as a
mathematical guarantee. *(Fix for testability-review finding #6: 4 hex chars
gave a non-negligible expected collision count at corpus scale, and the
original spec asserted "never collide" without any collision-avoidance
mechanism to back it.)*

| Field | Rule |
|---|---|
| `syn_investigation_lead_name` | `SYN-Investigator-{hash6}` (first 6 hex chars of `sha256(report_id + "lead")`) |
| `syn_investigation_lead_position` | fixed string `"Synthetic Role — Investigation Lead"` |
| `syn_incident_classified_by_name` | `SYN-Classifier-{hash6}`, salt `"classified_by"` |
| `syn_incident_classified_by_position` | fixed string `"Synthetic Role — Incident Classifier"` |
| `syn_investigation_acceptor_name` | `SYN-Acceptor-{hash6}`, salt `"acceptor"` |
| `syn_investigation_acceptor_position` | fixed string `"Synthetic Role — Investigation Acceptor"` |
| `syn_close_out_approval_name` | `SYN-Approver-{hash6}`, salt `"close_out"` |
| `syn_close_out_approval_position` | fixed string `"Synthetic Role — Close-Out Approver"` |
| `syn_responsible_owner_name` (recommendations) | `SYN-Owner-{hash6}`, salt `"owner"` |
| `syn_responsible_owner_position` | fixed string `"Synthetic Role — Responsible Owner"` |

`Incident Number` is **not** synthetic — already a real field from the spine
index. This corrects `e19_target.yaml`'s original list, written before the
spine work existed.

### Workflow dates

*Revised in rev 2.* The hash-to-offset formula is now spelled out explicitly
for every field (previously only the identity fields had a fully specified
algorithm), and `syn_action_status`/`syn_schedule_status` are split into two
independently defined value domains driven off the frozen `reference_date`.
*(Fix for consistency-review finding #4 and testability-review finding
#2/#3.)*

**Offset formula (applies to every row in this table):**
`offset_days = low + int(sha256(report_id + salt), 16) % (high - low + 1)`,
with a distinct `salt` string per field (listed below) so offsets don't
degenerate into a single shared draw across fields.

| Field | Rule | Salt |
|---|---|---|
| `syn_date_of_report` | `incident_date + offset_days`, range 5–15 | `"date_of_report"` |
| `syn_approval_date` | `date_of_report + offset_days`, range 14–45 | `"approval_date"` |
| `syn_close_out_date` | `approval_date + offset_days`, range 30–90 | `"close_out_date"` |
| `syn_action_due_date` | `approval_date + offset_days`, range 30–180 | `"action_due_date"` |
| `syn_agreed_completion_date` | `approval_date + offset_days`, range 30–180 | `"agreed_completion_date"` |

**`syn_action_status`** — domain `{Pending, In Progress, Completed}`, derived
from `age_days = reference_date - incident_date`:
- `age_days > 730` (>2yr) → `Completed`
- `183 < age_days ≤ 730` (6mo–2yr) → `In Progress`
- `age_days ≤ 183` (<6mo) → `Pending`

**`syn_schedule_status`** — domain `{On Schedule, Behind, N/A}`:
- If `syn_action_status == Completed` → `N/A` (nothing left to be on/behind
  schedule for)
- Else → hash tiebreak: `int(sha256(report_id + "schedule_status"), 16) % 2`
  → `On Schedule` or `Behind`

Note: `syn_action_due_date`/`syn_agreed_completion_date` are **not**
constrained to fall before `syn_close_out_date` — a recommendation can
legitimately remain open past the report's own close-out. This is
intentional, not an oversight; stated here so the testing section doesn't
under- or over-constrain it.

### Severity & risk classification

*Substantially reduced in rev 2.* The original draft built three independent
consequence × likelihood × score formulas (one each for H&S, Environment &
Reputation, Financial) — a real risk-matrix *model*, not shape-completeness
filler, and it sat on the same "no real basis, our own invented formula"
footing the non-goals section used to exclude the 4-axis incident-type
scheme without applying that same test to itself. *(Fix for scope-review
finding #1/#3.)* All scores now derive from **one** severity tier, reused
directly rather than recomputed per category — a single rule applied three
times instead of three independent formulas. This also resolves
consistency-review finding #5 (which score "mirrors incident's own severity
score" was ambiguous) by removing the ambiguity: there is now exactly one
severity source. The low-confidence, untestable `syn_hs_likelihood` axis
flagged by testability-review finding #5 is dropped entirely rather than kept
as a field nothing could meaningfully test.

| Field | Derived from | Rule |
|---|---|---|
| `syn_incident_classification` | `src_f07` type checkboxes | Fatality/Blowout/Explosion → `Very Serious`; Injury/LWC/Fire/Collision → `Serious`; else → `Incident`. If multiple checkboxes span tiers, highest tier wins. If no checkbox is resolvable (none set, or `src_f07` extraction `parse_failed`), value = `Unknown` and the row is logged to `data/interim/anomalies.jsonl` per the project's existing `src_cause_status` convention — never guessed. |
| `syn_worst_reasonable_outcome` | mirrors `syn_incident_classification` | same tier, no independent signal to diverge |
| `syn_involves_fatality_or_injury` | `src_f07` | boolean, true iff a Fatality or Injury checkbox is set. **New in rev 2** — a machine-readable flag so any downstream loader/dashboard can apply extra caution (e.g. a stronger visual disclaimer) when a fabricated score sits next to a real fatality/injury record. Fix for misleading-data-review finding #3. |
| `syn_hs_risk_score` | `syn_incident_classification` | fixed numeric encoding of the tier: `Very Serious → 9`, `Serious → 5`, `Incident → 2`, `Unknown → null`. A direct encoding, not an independently computed consequence×likelihood formula. |
| `syn_environment_reputation_classification/score` | Pollution checkbox + `syn_incident_classification` | same tier mapping as `syn_hs_risk_score`, gated by whether the Pollution checkbox is set (unset → `None`/`0`) |
| `syn_financial_classification/score` | real `src_f21` | dollar-threshold table (documented in `synth_rules.yaml`), classified `Unknown` and logged to `anomalies.jsonl` if `src_f21` is missing or `parse_failed` — never defaulted to the lowest tier. The threshold values are our own choice; no claim of external sourcing (see Architecture, `xw_`/`syn_` boundary). |
| `syn_unmitigated_risk_score` | `syn_hs_risk_score` | equals `syn_hs_risk_score` exactly — the one named source, not an aggregate. Resolves prior ambiguity over which of several scores "unmitigated" referred to. |
| `syn_mitigated_risk_score` | `syn_unmitigated_risk_score` | `max(syn_unmitigated_risk_score - 2, 1)` if `syn_unmitigated_risk_score` is not null, else `null`. A fixed point subtraction with an explicit floor, representing "recommendations reduce risk but don't zero it out." |

### Cheap extras

`syn_incident_title` — templated from real fields
(`f"{incident_type} incident at {area_block}"`). This is a *reformatting* of
real fields, not a fabrication, and is documented as such in `docs/_synth.md`
so it doesn't inherit the same caution level as the genuinely invented
severity/identity fields despite sharing the `syn_` prefix (the project's
5-prefix convention doesn't have a sixth tier for "template of real data,"
so this is called out explicitly in prose instead).

## Explicit non-goals

- **Incident Type A/B/C/D axis is out of scope for v1.** BSEE's single-axis
  type checkboxes don't decompose into the workbook's 4-axis scheme (loss-
  event type × H&S/Env/Business area × injury type × department) with any
  real basis. Logged in `docs/findings.md` as a known gap, not fabricated —
  same policy as `crosswalk.yaml`'s `orphan_subcategory_policy:
  leave_unmapped`.
- **The full multi-axis risk-matrix model (independent consequence ×
  likelihood formulas per category) is also out of scope for v1** — added in
  rev 2, applying the same "no real basis to invent this" test uniformly
  instead of only to the 4-axis scheme. Severity/risk fields derive from one
  tier, reused, per the Field Catalog above.
- **No workbook formulas are replicated.** Every scoring rule above is
  designed from scratch, never reverse-engineered from the actual workbook,
  consistent with the standing rule against deriving anything into the
  public repo from it.

## Labeling & docs

- README's real-vs-generated table names every `syn_` column and links to
  `synth_rules.yaml` as the exact recipe. The table is a human-readable
  rendering of `data/processed/incidents.columns.json` (below); if they
  diverge, the JSON manifest is the enforced source of truth.
- **`data/processed/incidents.columns.json`** (new in rev 2) — machine-
  readable sidecar manifest, one entry per column:
  `{prefix, provenance, description, fabricated: bool}`. Ships alongside the
  CSV specifically so a participant who downloads only the CSV (e.g. via a
  raw-file link, never cloning the repo or opening the README) still has a
  co-located, parseable disclosure. `tests/test_conventions.py` asserts it's
  present and lists every column in the live table.
- `docs/_synth.md` (same pattern as `docs/_harvest.md`): plain-language
  statement that these columns are a documented deterministic function of
  real fields, not measured or observed data — useful for full-pipeline
  practice, never eligible to be scored as if `gold_`. Rev 2 additions:
  explains the frozen `reference_date`, the `syn_involves_fatality_or_injury`
  flag and why it exists, and the `Unknown`/anomaly-log policy for
  unresolvable source fields.

## Testing (`tests/test_synth.py`)

*Rewritten in rev 2 — the original four categories each turned out to miss
specific bug classes the review surfaced; see inline notes.*

- **Determinism across time, not just across calls.** Generate the same row
  at two different simulated `reference_date` values that straddle a 6-month
  and a 2-year age boundary → output must differ *only* in the fields whose
  rule is explicitly age-dependent (`syn_action_status`,
  `syn_schedule_status`), and must be byte-identical for everything else.
  *(The original "run twice in the same process" version would have passed
  even with the wall-clock bug this rev fixes — it never varied "now.")*
- **Range-exact date invariants**, not just ordering: for every date field,
  assert the day-delta falls inside its documented `[low, high]` range (e.g.
  `5 ≤ (date_of_report − incident_date).days ≤ 15`), extended to cover
  `approval_date ≤ syn_action_due_date` and `approval_date ≤
  syn_agreed_completion_date` (previously excluded from the invariant
  entirely).
- **Distributional/variety check** (new): over a fixture of ≥20 distinct
  `report_id`s, every hash-derived field takes more than one distinct value.
  Catches a dead or duplicated salt that would otherwise pass determinism,
  ordering, and traceability checks while silently producing the same
  fabricated value on every row.
- **Boundary-value check** (new): rows placed exactly at each documented
  threshold (730-day age, 183-day age, each dollar cutoff) land in the
  documented bucket per the stated inclusive/exclusive edge.
- **Missing/ambiguous source-input check** (new): zero-checkbox,
  multiple-checkbox, and `parse_failed` states for `src_f07` and `src_f21`
  each produce `Unknown` plus an `anomalies.jsonl` entry — never a guessed
  tier.
- **Cross-field consistency**: `syn_mitigated_risk_score ≤
  syn_unmitigated_risk_score` (respecting the floor) holds for every row.
- **Identity-token collision**: no collision across the 5 roles within a
  report, checked empirically against the full generated corpus (documented
  as an empirical result at the widened 6-hex-char space, not asserted as a
  guarantee the algorithm structurally can't provide).
- **Rule traceability — split into two things**, since "every column traces
  to a rule, no unexplained literals" isn't a single mechanical check:
  1. A real, automatable test: an AST-based scan of `synth.py` asserting
     every value assigned to a `syn_` column flows from a name loaded out of
     `synth_rules.yaml` or from an explicit small allowlist of literals
     (e.g. day-count bounds already covered by the range check above).
  2. A PR-template checklist item (not a pytest assertion) for a human
     reviewer to confirm any new rule is accurately described in
     `docs/_synth.md`. Labeled explicitly as human review, not automated
     coverage.

## Convention enforcement

`tests/test_conventions.py` (not yet written, already on the backlog) is
extended rather than built twice:
- every column in the final assembled table must start with `src_`, `xw_`,
  `llm_`, `gold_`, or `syn_`, and specifically no `synth.py` output may carry
  `xw_` — enforcing the architecture rule mechanically instead of only
  documenting it;
- `data/processed/incidents.columns.json` is present and its key set exactly
  matches the live column set of `incidents.csv` (new in rev 2 — closes the
  gap where a new `syn_` column could ship without ever being disclosed
  anywhere machine-checkable).
