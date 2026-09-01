# Scenario-Planted E19 Registers + KPI Validation — Design

Status: approved direction (post 5-critic adversarial review, 2026-08-31).
Supersedes nothing; extends the filled/ E19 layer work (plan
2026-08-30-e19-fill-and-export.md).

## Goal

Produce synthetic-company E19 registers with deliberately planted,
ground-truth-documented process pathologies, plus a deterministic KPI layer
that demonstrably recovers them — so a proof-of-concept "incident-management
process health" evaluator has data where the right answer is knowable.

**Honest claim this project makes (and no more):** the KPI layer correctly
recovers planted, large-magnitude process-rate deviations from generated
registers; specificity is checked by negative controls on the healthy
company; sensitivity is checked by a near-threshold test-only variant.
It does NOT claim a fully validated evaluator: sensitivity to marginal
real-world degradation and per-pathology attribution inside bundles are
explicitly out of scope and stated so wherever results are presented.

## Decisions already made

1. PoC goal: validated-by-construction detection (planted pathologies).
2. Evaluator: hybrid; the deterministic KPI layer is in scope, the LLM
   assessment layer is a follow-on project.
3. AWS: none in this plan. The Bedrock text-generation stage was CUT after
   adversarial review (tautology via unspecified read-back classifier,
   reproducibility break, contaminated few-shot pool). The schema keeps the
   column/provenance shape LLM-generation would have used, so the follow-on
   project swaps generation without a schema migration.
4. Scope: Phase 0 repair + dataset + KPI validation. No assessment layer.
5. Corpus facts: 1,214 real BSEE incidents (`real_only/incidents.csv`),
   3,572 cause rows, 601 substantive real recommendations across 425
   incidents; Closeout and owner/agreed-date fields 100% empty in source.

## Phase 0 — repair the existing deliverable (before any new generation)

The current workbook (copied to RELAY 2026-08-31) renders constructed
values as "verbatim from a BSEE source document". Root cause:
`crosswalk.py` marks every non-empty cell `src` (the rule appears twice —
incidents loop and `enrich_causes()`).

1. New module `src/psm/provenance.py`: single source of truth exporting
   `TOKENS` (closed set) and `FILL_COLORS`. `tests/test_conventions.py`,
   `tests/test_fill_outputs.py`, and `export_e19.PROVENANCE_FILLS` all
   import from it; one test asserts they agree.
2. Two new tokens, split by epistemic category (do NOT conflate):
   - `key` — constructed join identifiers with no real-world referent.
     Applied **by column**, not by string pattern: every `Incident Number`
     cell in every table (incidents, causes, and later recommendations/
     closeout) is a constructed composite (`AREA-BLOCK-YYYYMMDD-HHMM`,
     some with UNKEYED-/collision hash parts). The whole column is `key`.
   - `pseud` — salted pseudonyms of real values (INV-/SUP- name tokens:
     consistent privacy transforms of real people's names, NOT fabricated).
   Token set becomes `{"", src, xw, llm, gold, syn, key, pseud}`.
3. Shared helper `provenance_row(row, cols, key_columns, pseud_columns)`
   used by BOTH crosswalk provenance loops (kills the duplicated one-liner).
4. Ordered execution (export reads `filled/`, so enriched-only fixes ship
   nothing): crosswalk fix → `uv run python -m psm.fill` →
   `uv run python -m psm.export_e19` → commit regenerated
   `enriched/*.csv` + `filled/*.csv` → RELAY refresh (separate explicit
   user confirmation; not automated).
5. About sheet: new legend lines for `key`/`pseud`; DELETE the superseded
   "Incident Number is unshaded" exception paragraph; ADD the
   `Cause type`-is-positional caveat (cause #1 = "Immediate" in
   1,210/1,210 filled rows — ordinal position, not analysis).
6. New test: no cell whose `enriched/` provenance is `key`/`pseud` may be
   `src` in `filled/` provenance (catches the stale-layer failure mode).
   All closed-set and pinned-manifest tests updated; every new invariant
   shown to fail under mutation before trusted (repo standard).

## The companies

Three registers, one shared 5-year window **2021-01-01 .. 2025-12-31**,
**150 incidents each** (30/yr — large-operator scale; the real GOM industry
runs 32–96/yr across ALL operators, so 133/yr per company would be an
instant fabrication tell). Donor pools are **disjoint** deterministic
partitions of the 1,214 real incidents (450 used, no narrative appears in
two companies). Sampling without replacement, exact N=150, hash-ordered.

Build order: NorthStar + Meridian through the FULL pipeline including
validation, then Coastal, then exports.

### scenarios/northstar.yaml (healthy baseline)
```yaml
report_lag:      {median_days: 2,  sigma: 0.6}
investigation:   {skip_rate: 0.02, root_cause_prob: 0.85, duration_median_days: 21, duration_sigma: 0.6}
closeout:        {median_days: 45, sigma: 0.6}
agreed_offset:   {min_days: 30, max_days: 90}
recurrence:      {planted_pairs: 0, window_days: 365}
controls_mix:    {elimination: 0.05, engineering: 0.50, admin: 0.35, ppe: 0.10}
data_discipline: {owner_assigned_rate: 0.98, extra_hs_blank_rate: 0.00}
```

### scenarios/meridian.yaml (closure decay)
```yaml
report_lag:      {median_days: 10, sigma: 0.8}          # planted
investigation:   {skip_rate: 0.03, root_cause_prob: 0.80, duration_median_days: 30, duration_sigma: 0.7} # near-baseline (negative-ish)
closeout:        {median_days: 130, sigma: 0.8}         # planted
agreed_offset:   {min_days: 30, max_days: 90}
recurrence:      {planted_pairs: 8, window_days: 365, work_group: Maintenance}
controls_mix:    {elimination: 0.05, engineering: 0.50, admin: 0.35, ppe: 0.10}  # = NorthStar (negative control, aids attribution)
data_discipline: {owner_assigned_rate: 0.95, extra_hs_blank_rate: 0.00}
```

### scenarios/coastal.yaml (shallow investigation)
```yaml
report_lag:      {median_days: 2,  sigma: 0.6}          # = NorthStar (negative control)
investigation:   {skip_rate: 0.20, root_cause_prob: 0.25, duration_median_days: 7, duration_sigma: 0.5} # planted (shallow = fast)
closeout:        {median_days: 40, sigma: 0.5}          # fast on paper
agreed_offset:   {min_days: 30, max_days: 90}
recurrence:      {planted_pairs: 6, window_days: 365}   # from unaddressed causes
controls_mix:    {elimination: 0.00, engineering: 0.15, admin: 0.60, ppe: 0.25}  # planted
data_discipline: {owner_assigned_rate: 0.60, extra_hs_blank_rate: 0.25}  # planted
```

### scenarios/meridian_nt.yaml (near-threshold; TEST-ONLY, never exported)
As NorthStar except `closeout.median_days: 60` and analytic overdue ~0.10.
Purpose: the margin assertions must still detect direction on a small
deviation — proves the KPI math has resolution, not just that 3x gaps are
visible. (Adversarial-review requirement.)

The prose above and these YAML values are the SAME numbers by construction;
any drift between prose and YAML in later documents is a defect.

## Generation mechanics (module `src/psm/scenario.py`)

- **Determinism:** every draw is `int(sha256(company|incident_key|field|salt),
  16)` in sorted-key order. No `random`, no `date.today()`, no scipy at
  runtime. Lognormal shapes come from **committed integer quantile tables**:
  `scripts/build_quantile_tables.py` (dev-only, uses scipy once) writes
  1024-bucket day-offset tables per (median, sigma) config to
  `schema/quantiles/*.csv`; the engine does pure-integer lookup
  (`bucket = hash % 1024`). Regenerate → byte-identical, cross-platform,
  no scipy pin needed at runtime.
- **IDs:** every row's `Incident Number` is minted fresh:
  `scenario_incident_number(company, donor_id, clone_index, salt)` — donor
  IDs never leak (they embed real dates). Token `key`.
- **Date chain per incident:** Date of Incident (hash-placed in window) →
  Date of Report (+report_lag draw) → Approval Date (+investigation-duration
  draw) → per-recommendation Agreed Completion Date (report + agreed_offset
  draw) and Date Completed (report + closeout draw) → incident Close out
  Date = max(Date Completed). `Schedule Status` derived, existing domain:
  On Schedule (completed ≤ agreed), Behind (completed > agreed), N/A
  (skipped/none). **Overdue is EMERGENT** — no overdue knob: it falls out
  of the closeout distribution vs the agreed-offset distribution. The build
  script computes the analytic expected overdue rate from the quantile
  tables and stores it in the manifest; the KPI must measure it within
  tolerance. This is the deliberately indirect KPI (anti-tautology
  requirement from review).
- **Narrative dates:** 571/1,213 "What happened?" fields embed prose dates.
  Every donor narrative is shifted by the SAME delta as its structured
  rebase (deterministic regex over full-date forms); a test fails if any
  parseable full date in any narrative falls outside the company window.
  Shifted narratives keep token `src`; the About sheet discloses the
  uniform date shift (same precedent as the control-character sanitiser).
- **Cause chains are GENERATED, never inherited from `filled/`'s positional
  artifact.** Investigated incidents get 1–3 cause rows typed
  Immediate → Underlying → Root; `root_cause_prob` gates whether the chain
  reaches Root (Coastal truncates at Immediate). Cause Description text
  comes from the donor's real cause rows (token `src`); `Cause type` is
  engine-assigned (token `syn`).
- **Investigation skip:** the planted fraction of incidents get ZERO cause
  rows AND blank `Investigation leader - Name` / `Approval Date`. Skipped
  incidents are excluded from the root-cause-depth denominator and counted
  by the skip KPI (both stated explicitly to kill the divide-by-zero
  ambiguity).
- **Recurrence — no clones, no duplicated text:** a planted pair is TWO
  DISTINCT donors sharing `Failed PSM Framework Element` code + `Work
  Group`, placed within `window_days` of each other (anchored on `Date of
  Incident`), the second occurring AFTER the first's `Date Completed` —
  recurrence-after-closed-action is the effectiveness-failure signal
  (replaces the unimplementable "verified" concept: real Closeout has no
  verification column and none is added — byte-exact labels preserved).
- **Recommendations:** ~1.2 per investigated incident. `Recommendation
  Description` from a **template registry** (`schema/action_templates.yaml`):
  40–60 phrasings adapted from the operator-voice subset of the 601 real
  recommendations (regulator-voice and "MMS"/"OSM"/"District" items
  filtered out), each tagged elimination/engineering/admin/ppe. Company
  `controls_mix` picks templates by hash; the KPI reads the tag by exact
  registry match-back — no classifier. Template text token `syn`;
  a lint test rejects any register text containing MMS/OSM/District/
  Regional Office. Owners: `Responsible Owner - Name/Position` synthesized
  SYN- names at `owner_assigned_rate` (token `syn`).
- **Work Group:** ONE shared fixed distribution for all companies
  (Production Operations .30, Maintenance .25, Drilling .15, Well Services
  .12, Construction .10, Marine & Logistics .08) — company-specific weights
  were unfalsifiable and are dropped; Meridian's recurrence pairs target
  Maintenance via pair selection, not via distribution skew.
- **Severity fields:** donor-inherited (`src`), with Coastal blanking an
  extra `extra_hs_blank_rate` of populated H&S cells (the only axis with
  real variance — baseline 46.9% blank; Environment/Financial are 100%
  blank in source and are no-ops). The manifest records each partition's
  pre-knob baseline blank rate; the KPI test compares measured vs
  (baseline + knob) — this bounds the donor-composition confound.
- **Provenance:** parallel per-cell files for all 4 tables (recommendations
  and closeout provenance are NET-NEW infrastructure). Company tables use
  only `{src, syn, key}`; anything else fails the closed-set test.

## Manifest schema (pinned now — `data/companies/<co>/manifest.json`)

```json
{
  "company": "meridian",
  "scenario_sha256": "<sha of scenarios/meridian.yaml>",
  "donor_partition": ["<real incident ids>"],
  "window": {"start": "2021-01-01", "end": "2025-12-31"},
  "resolved_knobs": { "...": "verbatim resolved YAML" },
  "plants": [
    {"pathology": "closeout_decay", "kpi": "median_closeout_days",
     "expected": {"op": ">", "ref": "northstar", "factor": 2.0},
     "affected_ids": null},
    {"pathology": "recurrence_after_closure", "kpi": "recurrence_rate",
     "expected": {"op": ">=", "count": 8},
     "affected_ids": [["ID-a1","ID-a2"], ["..."]]}
  ],
  "analytic_expectations": {"overdue_rate": 0.34, "hs_blank_baseline": 0.44},
  "negative_controls": ["report_lag(coastal)", "controls_mix(meridian)", "..."]
}
```
Every KPI appears in every company's manifest as either a plant, an
analytic expectation, or a negative control — nothing unasserted.

## KPI layer (`src/psm/kpi.py`) — nine KPIs, margins for ALL of them

| # | KPI | Definition (exact fields) | Planted in | Assertion vs NorthStar |
|---|-----|---------------------------|-----------|------------------------|
| 1 | median_report_lag | median(Date of Report − Date of Incident) | Meridian | M > 3× N; C within ±30% of N (neg ctl) |
| 2 | skip_rate | share of incidents with 0 cause rows & blank leader | Coastal | C > 5× N; M within ±2 pts of N |
| 3 | root_cause_depth | share of investigated incidents with a Root-typed row | Coastal | C < ½ N; M within ±10 pts of N |
| 4 | median_closeout_days | median(Date Completed − Date of Report) | Meridian | M > 2× N; near-threshold variant > 1.2× N |
| 5 | overdue_rate | share of recs with Date Completed > Agreed (emergent) | Meridian | within ±5 pts of manifest analytic value; M > 3× N |
| 6 | recurrence_rate | pairs same Element+Work Group within window, 2nd after 1st's Date Completed | Meridian, Coastal | measured ≥ planted count; N ≤ manifest coincidence bound |
| 7 | admin_ppe_share | template-tag share admin+ppe | Coastal | C > N + 25 pts; M within ±5 pts of N (neg ctl) |
| 8 | owner_completeness | share recs with Responsible Owner - Name populated | Coastal | C < N − 25 pts |
| 9 | hs_completeness | populated share of H&S Risk Score (baseline-adjusted) | Coastal | C < baseline − 15 pts; M ≈ baseline |

## Validation (`tests/test_scenarios.py`) — the finish line

1. Planted-vs-measured: every manifest plant satisfied, per the table above.
2. **Negative controls:** every pathology KPI bounded on NorthStar (false-
   positive check) and on the explicitly-listed negative-control cells.
3. **Near-threshold:** meridian_nt generated in-test; direction detected
   with tight margin.
4. Determinism: full regenerate → byte-identical (LLM-free, so this is now
   unconditional); re-run under a different injected "build date" input to
   prove no wall-clock dependence (pattern from 2026-08-09 synth spec).
5. Prose-date window test; MMS/regulator-voice lint; provenance closed-set
   over all 4 tables; manifest-consistency (every KPI asserted somewhere).
6. Every invariant mutation-tested (shown to fail on purpose) before trust.
7. Attribution honesty: validation output states bundle-level detection for
   Coastal (its pathologies co-move); per-pathology ablation is parked.

## Deliverables & export (LAST, after tests green)

- `deliverables/companies/<Co>_E19_Register.xlsx` × 3: About + 4 sheets,
  provenance shading (`key`/`pseud` colours added). About discloses:
  synthetic company, planted-pathology framing WITHOUT naming them, date-
  shift disclosure, template-text disclosure. 30/yr large-operator framing.
- `deliverables/companies/comparison.xlsx`: KPI table + planted-vs-measured
  + negative-control results. **Internal validation artifact — never
  distributed alongside the company workbooks** (it is the answer key).
- Phase 0's repaired `e19_filled.xlsx` re-exported; RELAY refresh awaits
  explicit confirmation.

## Parked (recorded, not in this plan)

- Severity-drift / normalization-of-deviance archetype (4th company, v2).
- Per-pathology ablation variants; dev-only multi-salt Monte Carlo to
  empirically justify margins.
- LLM (Bedrock) narrative/action text generation + LLM assessment layer —
  follow-on project; schema kept swap-compatible on purpose.
- Closure-verification/effectiveness-review fields (not in real E19 v1
  shape; effectiveness is proxied by recurrence-after-closure).

## Global constraints (bind every task)

- Determinism idiom: sha256, sorted keys, no random/date.today/scipy at
  runtime; quantile tables committed.
- Never write `gold_*`; never score against `llm_` and call it accuracy;
  deliverables/ gitignored; never commit data/raw|interim; byte-exact E19
  workbook labels (no new columns in the 4 tables).
- Provenance closed set `{"", src, xw, llm, gold, syn, key, pseud}` from
  `psm.provenance` only.
- Counts: 1,214 donors; 150/company; disjoint partitions; window
  2021-01-01..2025-12-31.
- Every blocking invariant live-tested against a real attempted violation.
