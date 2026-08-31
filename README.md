# psm-incident-ml

A semi-synthetic process-safety incident dataset built from US federal offshore
incident reports (BSEE MMS Form 2010), projected onto the Energy Institute PSM
Framework **Element 19** (Incident Reporting & Investigation) template.

Every cell records its own origin. Nothing is filled unless the source supplies
it, a versioned rule derives it, or a generator can fabricate it without
asserting something false about a real incident.

## Read this before modelling

Three properties will change what you build. Each is measured, not asserted;
`docs/findings.md` has the method for all of them.

1. **7 of the 20 PSM elements are reachable.** BSEE's six cause categories map to
   elements 3, 6, 8, 9, 15, 17, plus 11 via secondaries. The other 13 cannot
   appear at any coverage. A model scored on "PSM element" is running a 7-class
   problem under a 20-class label.
2. **Expect ~0.55 accuracy on cause-category prediction, and report macro-F1.**
   Logistic regression on TF-IDF, n=503, 5-fold CV: 0.551 accuracy against a
   0.392 majority baseline, macro-F1 0.418. Two categories carry the signal
   (Equipment Failure F1 0.692, Human Performance Error 0.639); three sit near
   F1 0.25 at n≈30. Accuracy alone rewards ignoring four of six classes.
3. **The label vocabulary is non-stationary in four regimes.** Use the shipped
   split in `data/processed/e19/real_only/splits.json`. A random split leaks the
   reporting era and part of any score will be "can you tell the decade".

| regime | years | incidents | cause vocabulary |
|---|---|---|---|
| `free_prose` | ≤2006 | 161 | none; 0% of statements map |
| `human_error` | 2007-2009 | 258 | one head, `Human Error` |
| `ad_hoc` | 2010-2018 | 438 | 68 investigator-invented heads |
| `modern_six` | 2019+ | 321 | the modern six; adoption jumps 5→17 between 2018 and 2019 |

87.1% of labelled cause statements are `modern_six`.

## Tables

`data/processed/e19/enriched/`, byte-exact E19 column labels including the
template's own typos (`Incident Classificatioin`, a leading space on
` Failed PSM Framework Element`).

| table | rows | grain |
|---|---|---|
| `incidents.csv` | 1,214 | one per incident |
| `causes.csv` | 3,572 | one per cause statement |
| `recommendations.csv` | 1,230 | one per recommendation |
| `closeout.csv` | 1,230 | one per recommendation |

Sidecars, all keyed on `Incident Number` (+ `Cause number` where applicable):

| file | contents |
|---|---|
| `provenance.csv`, `causes_provenance.csv` | per-cell `src` / `xw` / `syn` / empty, same shape as the table |
| `causes_confidence.csv` | per-cell confidence where a mapping is graded |
| `causes_secondary_element.csv` | `also_touches` element from `crosswalk.yaml` |
| `bsee_unmapped.csv` | BSEE fields with no E19 counterpart, `bsee_` prefixed |
| `causes_source_field.csv` | whether a statement came from form field 18 or 19 |

`Incident Number` is constructed (`{AREA}-{BLOCK}-{YYYYMMDD}-{HHMM}`) because
BSEE publishes no incident identifier. It is **variable arity**: components are
dropped when the source lacks them. 1,002 keys have four components, 129 have
three, 79 have two, 4 carry a content-hash suffix for colliding groups. 162 carry
no time. All 1,214 are unique.

## Provenance

| mark | meaning |
|---|---|
| `src` | read verbatim from a BSEE PDF or CSV |
| `xw` | derived by a versioned rule in `schema/xw_*.yaml` |
| `llm` | assigned by a language model; never treated as ground truth (`filled/` layer only, written by `src/psm/fill.py`) |
| `syn` | fabricated -- in `enriched/`, by `src/psm/synth.py` under `schema/synth_rules.yaml`; in `filled/`, also by `src/psm/fill.py` under the same rules file |
| empty | not filled; see `gap_policy` in `schema/e19_disposition.yaml` |

Precedence is `src` > `xw` > `syn`. A `syn` value never displaces a real one.
Enforced by `tests/test_conventions.py` for `enriched/` and `tests/test_fill_outputs.py`
for `filled/`.

### The `filled/` layer

`data/processed/e19/filled/` is a second projection on top of `enriched/`,
built by `uv run python -m psm.fill` and turned into an SME-reviewable
workbook by `uv run python -m psm.export_e19` (writes
`deliverables/e19_filled.xlsx` -- gitignored, never commit it). It fills the
remaining gaps in `Work Group`, the two Likelihood columns, and `Cause type`
(all `syn`), plus ` Failed PSM Framework Element` (kept where `enriched/`
already has a crosswalk value, else `llm` from a labelling run, else a
deterministic `syn` fallback). `filled/` carries its own parallel provenance
files, same shape and token convention as `enriched/`'s.

Composition across all four tables: **40.7% real** (`src`+`xw`), 39.0%
fabricated, 20.4% blank by policy.

Incidents table alone: 25.6% `src`, 15.1% `xw`, 30.6% `syn`, 28.7% blank.

Synthetic identities are hash tokens (`SYN-Approver-da5b09`,
`Synthetic Role — Investigation Acceptor`), never plausible names. A test asserts
they stay distinguishable from real values.

## Two artifacts

```bash
uv run python -m psm.ledger --real-only
```

- `data/processed/e19/enriched/` is the full sheet, including synthetic
  scaffolding. Use it to demo the E19 workflow end to end.
- `data/processed/e19/real_only/` is the same tables with all `syn` cells
  blanked, plus `splits.json`. Use it to train. Rows are blanked, not dropped,
  so joins hold.

## Why cells are blank

`schema/e19_disposition.yaml` gives every column a `gap_policy`, and every
`leave_blank` column a `blank_reason`.

| reason | columns | rule |
|---|---|---|
| `would_dominate` | 8 | under 50% real; fabrication would be the majority of the column |
| `no_generator` | 13 | no honest way to produce the value. `Date of Incident` is 97.0% real and still unfillable: inventing a date asserts when a real incident happened |
| `degenerate_fill` | 4 | a generator exists and its output carries no information. `syn_hs_risk_score` emits {2,5,9} against a real 1-25 consequence×likelihood product; the value sets are almost disjoint |

This policy governs `enriched/`. The `filled/` layer above deliberately
reverses it for one `would_dominate` column: ` Failed PSM Framework Element`
is filled anyway, to 85.3% non-real (2,008 `llm` + 1,040 `syn` of 3,572) --
precisely the outcome the policy exists to prevent in `enriched/`. The
reversal is scoped to `filled/`, per-cell provenanced, and disclosed in
`schema/e19_disposition.yaml`'s note on that column.

`docs/e19_field_ledger.md` is generated from this file joined to measured
coverage. `tests/test_ledger.py` fails the build if any claim in it stops being
true.

## Validity

Coverage is not correctness. Eight columns declare a shape check; 94.3% of
checked cells pass.

| valid | column | failures |
|---|---|---|
| 69.1% | `Recommendation Description` | truncated 355, form_label 18 |
| 94.6% | `Cause Description` | too_short 186, form_label 6 |
| 96.9% | `Incident Number` | bad_pattern 38 (time with no date) |

Checks are opt-in per column. A global rule fails every code, key and picklist
value in the dataset.

## Known bias

BSEE convenes a panel investigation for the most severe events and publishes
those separately. **54.1% of fatalities in the incident index are panel cases**
and are excluded from this corpus, which is district reports only. Severity is
thinned at the top. Do not read the distribution as representative of offshore
incident severity.

## Pipeline

Python 3.11+, `uv`. Entry points are modules:

```bash
uv run python -m psm.harvest     # index -> data/manifest.csv (1,302 rows, SHA256 per file)
uv run python -m psm.fetch       # manifest -> data/raw/
uv run python -m psm.extract     # PDFs -> data/interim/*.json
uv run python -m psm.project     # interim -> data/processed/e19/  (verbatim only)
uv run python -m psm.crosswalk   # + xw and syn -> enriched/
uv run python -m psm.ledger --real-only
uv run python -m psm.cluster     # the six-category partition check
```

`data/raw/` and `data/interim/` are gitignored. `data/manifest.csv` is committed
with a SHA256 per file, so a fresh clone rebuilds byte-identical inputs.

Extraction is coordinate-aware (`pdfplumber` bounding boxes). Text-stream order
is not visual order on this form; naive `extract_text()` produces confidently
wrong field assignments. Anchors resolve by **label**, not by printed number:
revision B renumbers the form face, and two-column linearisation drops digits
(`13. SEA STATE` arrives as `3. SEA STATE`).

## Rules are data

| file | decides |
|---|---|
| `bsee_form2010.yaml` | field map, furniture, label-bleed patterns, length caps |
| `crosswalk.yaml` | BSEE cause category → PSM element |
| `xw_incident_type.yaml` | accident-type atoms → E19 Type A/B/C/D |
| `xw_consequence_tiers.yaml` | hazard energy, likelihood, risk score |
| `xw_cause_qualifiers.yaml` | subcategory → Risk Management / Human Factors cause |
| `xw_outcome.yaml` | outcome atoms → prose |
| `e19_projection.yaml` | E19 label → BSEE source, or a blank reason |
| `e19_disposition.yaml` | per-column disposition, gap policy, validity checks |
| `synth_rules.yaml` | every synthetic field, with a frozen `reference_date` |

Each carries its reasoning and, where relevant, the alternatives that were
tested and rejected. `crosswalk.yaml` in particular is an opinion and is meant to
be argued with.

## Not validated

`gold/gold_labels.csv` has 100 sampled cause statements and **0 hand labels**.
Nothing in this repo has been scored against an independent human judgement. The
crosswalk's six category→element mappings have never been checked. Any accuracy
number you see elsewhere in these docs is model-vs-model or model-vs-rule.

Also outstanding: ~37 unexplained missing fatalities in the spine join; 145
records where form field 30 is not located because linearisation transposes its
label and number; `e19_schema.py`, `evidence.py`, `fetch.py` and `spine.py` at 0%
test coverage.

## Sources and licensing

Source documents are US federal government works (BSEE), public domain. The
derived tables, schema files and code in this repo are released under the
repository licence. The Energy Institute PSM Framework element *names* are
referenced with attribution; the E19 workbook itself is not included and no
derivative of it is committed.

## Repo layout

```
data/manifest.csv           committed; SHA256 per source PDF
data/processed/e19/         the dataset
gold/                       sampling frame for hand labels (unlabelled)
schema/                     every rule, as data
src/psm/                    pipeline
tests/                      359 tests
docs/findings.md            append-only log: what was verified, by what method
docs/e19_field_ledger.md    generated
```

## Arguing with this

`docs/findings.md` records negative results and reversals as well as successes,
including several cases where a test corrected the rule it was written to
encode. If a mapping looks wrong, the file that decides it is named above and the
reasoning is inline. Open an issue against the schema file, not the CSV.
