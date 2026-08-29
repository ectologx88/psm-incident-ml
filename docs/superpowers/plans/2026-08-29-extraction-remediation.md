# Extraction remediation — plan

Diagnosis is in `docs/findings.md`, entry 2026-08-29. This is what to do about it.

## The organising principle

**27 of the 65 E19 fields can only be filled by a human reading the report.** No
extraction work changes that number. `gold/gold_labels.csv` has 100 rows and
zero labels, and that is the critical path for the whole project.

So every item below is ranked by one question: *does this change what a human
labeller sees, or how much of their time we waste?* Work that improves metadata
nobody is blocked on is explicitly deferred, however satisfying it would be to
fix.

The corollary matters more than the ranking: **do not hand anything to a
labeller until P0 lands and the corpus is re-extracted.** A person labelling
rows that are about to change is the most expensive mistake available here.

---

## P0 — unblocks labelling. Do these first, together, then re-extract.

### P0.1 Field 17 label alternates

`schema/bsee_form2010.yaml` carries one `label_hint` for field 17. The pre-2010
revision reads `DESCRIBE IN SEQUENCE HOW ACCIDENT HAPPENED`. Make `label_hint`
accept a list and add the alternate; `_label_matches()` (`src/psm/extract.py:47`)
needs to handle a list.

Roughly a 10-line diff. Already tested against all 105 files during diagnosis:
**22 recovered, 0 regressions, zero change to field 18 text on any file.**

Keeps wording in YAML rather than code, per the project's existing convention.

**Recovers the narrative on 22 of the 48 archive-era gold rows — the single
highest-value change available.**

### P0.2 Length-sanity guard on structured fields

Flag any `checkbox_set` / `composite` / `date` field whose extracted text
exceeds a threshold (a few hundred chars). Emit an anomaly, do not repair.

Both failure modes in the diagnosis — a 2,356-char `f07_type`, a 2,556-char
`f02_operator`, a 6,049-char `f30_district_supervisor` — would have tripped this
immediately instead of producing plausible-looking output. This is the guard
that turns the project's recurring failure mode (silent, plausible, wrong) into
a loud one.

Cheap, and worth more than any single parser fix.

### P0.3 Record `src_form_revision` on every record

Discriminator: which field number carries `WATER DEPTH` (era A/B = 9, era C =
10), with field 3's label (`LEASE` vs `OPERATOR/CONTRACTOR`) as validator.

This does not fix anything on its own. It makes every subsequent fix testable by
era and stops the next person inferring era from filename years, which
`findings.md` already records as unreliable.

### P0.4 Log `090517-pdf` as an upstream defect

BSEE serves a 2008 press release at an incident-report URL. Record in
`data/interim/anomalies.jsonl` and exclude from the gold sample. Do not repair,
do not silently drop.

### P0.5 Re-extract, then regenerate the gold scaffold

`gold/gold_labels.csv` must be regenerated after P0.1. All `gold_*` columns are
currently blank so nothing is at risk today — **this window closes the moment
labelling starts.**

Re-run the era split from the diagnosis afterwards and confirm archive-era f17
fill moves from 54% to ~100%. If it does not, stop and re-diagnose rather than
proceeding.

---

## P1 — per-revision field map. Needed for identification fields, not for labelling.

The form has three numbering eras; the schema encodes one. Fields 3–16 shift by
one across revisions, so `label_hint` correctly rejects them and their content is
absorbed into the previous accepted field.

Add a `revisions:` block to `schema/bsee_form2010.yaml` mapping field numbers per
revision, keyed on the `src_form_revision` from P0.3. Data in YAML, not code.

Fixes together: `f04` lease/area/block (12 era-A files), `f07` type (58%
contaminated, 100% of era B), `f02` operator (whole-form dump on era A), and the
long-standing "fields 8–16 missing on ~16%" gap, which is the same root cause.

Roughly half a day, mostly tests. Touches `segment_fields()`, so it needs the
era-stratified regression suite from P0.3 to be trustworthy.

**Why it is P1 and not P0:** it repairs `Site`, `Area`, `Unit` and
`Description` — E19 identification fields. A labeller assigning cause categories
and PSM elements does not read them. It blocks the *deliverable*, not the
*bottleneck*.

---

## P2 — admin block. Affects only pseudonymised name fields.

### P2.1 Gutter detection on the closing admin page

Succeeds on 31/105 admin pages against 104/105 on page 0. Fixing it resolves the
f28→f25 bleed and most of the f25–f30 contamination.

### P2.2 Bound the terminal anchor

`segment_fields()` runs the last anchor to end-of-document, so the 48 reports
with post-admin attachment pages dump them into `f30`. Bound it at the admin
page, or at the first page with no recognised anchor.

### P2.3 Soften `ROW_TOL` into a real tolerance

`round(top/2.5)` is a hard bin edge; words 0.5pt apart split across bins. 41
orphan `NN.` lines across 27 records; those records lose f28 21/27 of the time.
Cluster with a tolerance instead of rounding to a grid.

These three feed `Investigation leader - Name` and
`Investigation Acceptor/Approver - Name` — both of which we pseudonymise anyway.
Real bugs, low stakes.

---

## P3 — intra-box label/value alignment for f04

Field 4's box is internally two-column (AREA/BLOCK left, LATITUDE/LONGITUDE
right) and row reconstruction interleaves them. 97% of f04 values are misaligned;
a positional parse yields `BLOCK="LONGITUDE"`. Meaning-changing, but it only
matters once `Site`/`Area` are being populated for real, and `manifest.csv`
currently carries usable filename-derived values as a fallback.

**Blocking note for `findings.md`:** the 2026-08-02 recommendation that *"the
authoritative values are inside the PDF (fields 1, 2 and 4)"* is not safe to act
on until P1 and P3 land. Today the PDF is the worse source.

---

## Runs in parallel — no dependency on any of the above

The E19 projection layer: `schema/e19_projection.yaml`, `src/psm/project.py`,
and the exactness test asserting output headers equal labels read from the
template. It consumes whatever extraction produces and is unaffected by these
fixes.

Two questions in it need the template author, not us: how to disambiguate
`Description` at E18 vs E23 (a flat table cannot carry two identically named
columns), and whether the irregular labels ship verbatim.

---

## Explicitly not doing

- **Chasing the ~1,140 reports not yet downloaded.** Fix extraction against the
  105 in hand first; re-running the harvest against a broken parser wastes the
  bandwidth and the diagnosis.
- **Using `out_of_order_anchor` for triage.** It is anti-correlated with
  contamination — it fires when the admin columns split *correctly*. Triage
  keyed on it selects the healthiest records.
- **Any level-2 subcategory work.** `findings.md` flags closure as unverified at
  n=63. It needs a larger sample, and it is downstream of labelling, not
  upstream.
- **Re-drawing the gold sample.** The narrative is recoverable; the sample is
  sound.

---

## Sequencing

```
P0.1 ─┬─ P0.5 re-extract ── regenerate gold scaffold ── HAND TO LABELLER
P0.2 ─┤                                                        │
P0.3 ─┤                                                        │
P0.4 ─┘                                                        │
                                                               │
P1 per-revision map ── re-extract ── (metadata improves) ──────┤
P2 admin block ───────────────────────────────────────────────┤
P3 f04 alignment ─────────────────────────────────────────────┘

projection layer ──────────── runs throughout, independent
author questions ──────────── sent now, answered whenever
```

Labelling starts after P0. It does not wait for P1–P3, because those fields are
not what a labeller reads.

## Definition of done for P0

- Archive-era f17 fill ≥95%, measured by the same era split used in the diagnosis
- Length guard fires on the three known cases and is quiet on modern records
- Every record carries `src_form_revision`
- `090517-pdf` in `anomalies.jsonl`, excluded from the gold sample
- `gold/gold_labels.csv` regenerated, `gold_*` still blank
- Full test suite green
