# Spec — Phase 0: extraction validity

Status: proposed, not started.
Supersedes the Phase 0 sketch in `2026-08-29-dataset-completion-plan.md`, which
treated field-22 contamination and the missing fields 8–16 as separate items.
**They are the same defect.**

---

## 1. The diagnosis

### 1.1 What was observed

`Recommendation Description` is 100% populated and marked `real`,
`gap_policy: none` in `schema/e19_disposition.yaml`. Measured against shape:

| | share of 1,244 rows |
|---|---|
| carries BSEE form-label text | 30.8% |
| ends mid-sentence | 31.4% |
| **either** | **51.8%** |

A representative value, verbatim:

> `RECOMMENDATIONS TO PREVENT RECURRANCE NATURE OF DAMAGE: none $ NARRATIVE: The New Orleans District makes no recommendations to the Office of Safety Management.`

### 1.2 The anomaly log already knew

`data/interim/anomalies.jsonl` is written by every extraction run and read by
nobody. Across 1,219 cleanly-extracted records:

| anomaly | records affected |
|---|---|
| `field_length_exceeded` | **899 (73.7%)** |
| `fields_not_located` | **980 (80.4%)** |
| `out_of_order_anchor` | 43 |
| `duplicate_anchor` | 32 |

The integrity guards fire on three quarters of the corpus. Nothing acts on them,
nothing surfaces them, and no test asserts a ceiling. That is the process defect
underneath the data defect.

### 1.3 Root cause

`fields_not_located`, by field:

| field | not located |
|---|---|
| 28 accident classification | 71.8% |
| 15, 16 pictures / statement | 70.0% |
| 9–14 cause checkbox, water depth, distance, wind, current, sea state | ~69.1% |
| 8 operation | 69.0% |
| 27 operator report on file | 62.0% |
| **30 district supervisor** | **13.9%** |

`field_length_exceeded`, by field: **field 7 on 743 records (61%)**, field 30 on
253, field 27 on 76.

Those numbers line up exactly with the form revisions —
**A: 94, B: 747, C: 377** — and with the earlier finding that revision A/B
records carry the strings `water depth`, `wind`, `sea state`, `distance from
shore` at ~100% while having **no `src_f08`–`src_f16` keys at all**.

The chain:

1. On revisions A and B the anchors for fields 8–16 are not accepted (different
   label wording, and the labels sit in interleaved two-column text).
2. `extract.py` slices content **from one accepted anchor to the next**
   (`extract.py:211-224`). With 8–16 missing, field 7's slice runs all the way to
   field 17 — hence 743 records with field 7 over length, holding nine fields'
   worth of checkbox soup.
3. The accepted-anchor stream is short and ragged. When field 30 is not found
   (169 records), the **terminal anchor runs to the end of the document**
   (`extract.py:216-217`: `lj, cj = len(kept) - 1, len(kept[-1].text)`).

Measured consequence of step 3, by which field ends up terminal:

| terminal field | records | that field carries label bleed | median length |
|---|---|---|---|
| 30 | 1,050 | 1.8% | 44 chars |
| 27 | 89 | **95.5%** | 166 |
| 26 | 62 | **100.0%** | 229 |
| 24 | 2 | 100.0% | 889 |
| 5 | 2 | 50.0% | 9,385 |
| **1** | **2** | 0.0% | **280,537** |

Two records have the entire document in field 1.

Field 22's contamination is the same family with a different trigger: fields 21
and 23 interleave across columns, so field 21's `NATURE OF DAMAGE` / `ESTIMATED
AMOUNT` text lands after field 22's anchor in the linearised stream.

**Correction to the completion plan:** it recorded fields 8–16 as "no E19
impact — ML covariates only". True for *coverage*, wrong for *validity*. Their
absence is what makes the anchor stream ragged, and the ragged stream is what
contaminates the E19 text columns.

---

## 2. Scope

**In:** per-revision anchor location; a bound on the terminal anchor; a validity
layer in the ledger; surfacing the anomaly log.

**Out:** re-fetching (corpus is complete); the crosswalk; synth; any modelling.
Explicitly out: "cleaning" contaminated text after the fact with a regex
denylist. That treats the symptom, cannot restore text lost to a neighbouring
field, and would leave the anomaly counts untouched while making the output look
better — the worst available outcome.

---

## 3. Design

### 3.1 Per-revision anchor labels (`P0-A`)

`schema/bsee_form2010.yaml` gains a per-revision `label_hint` override. The
existing `fields:` block stays as revision-C defaults; revisions A and B declare
only where they differ. Rules as data, per CLAUDE.md — no revision logic in
Python beyond selecting the map.

```yaml
form_revisions:
  label_hints:
    A: {8: "OPERATION", 9: "CAUSE", 10: "WATER DEPTH", ...}
    B: {...}
```

The revision is already detected (`src_form_revision`, 99.3% coverage) so the
map can be selected before anchor acceptance.

### 3.2 Bound the terminal anchor (`P0-B`)

Today the last accepted anchor takes everything to end-of-document. Replace with:
run to the next accepted anchor, or to the **first line matching a
`furniture_patterns` entry**, or to a `max_length_by_kind` ceiling — whichever
comes first. Overflow is not discarded; it goes to `src_unassigned_tail` so the
loss is visible and measurable rather than silent.

### 3.3 A validity layer in the ledger (`P0-C`)

`psm.ledger` currently answers "is this cell non-empty". It gains a second,
independent question: "does this cell's content pass a shape check for its
kind". Checks are declared per column in `e19_disposition.yaml`:

```yaml
validity:
  no_form_label: true      # must not contain BSEE stationery
  min_words: 4
  terminal_punctuation: true
```

Reported as a third headline number beside real/fabricated. **`real` must stop
meaning `non-empty`.**

### 3.4 Surface the anomaly log (`P0-D`)

`anomalies.jsonl` gets a summary in the ledger and a test asserting ceilings on
each anomaly type. A guard that fires on 73.7% of the corpus and blocks nothing
is decoration.

---

## 4. Acceptance criteria

Each is measured before and after, and recorded in `docs/findings.md`.

| # | criterion | now | target |
|---|---|---|---|
| A1 | records with `src_f08`–`src_f16` present | 30.9% | **≥ 90%** |
| A2 | `field_length_exceeded` on field 7 | 743 | **≤ 100** |
| A3 | records where field 30 is not located | 169 | **≤ 40** |
| A4 | `Recommendation Description` rows with form-label bleed | 30.8% | **≤ 5%** |
| A5 | `Cause Description` rows unusable (bleed or <5 words) | 7.6% | **≤ 3%** |
| A6 | records with any `field_length_exceeded` | 899 | **≤ 200** |
| A7 | longest single field value | 280,537 chars | **≤ 20,000** |
| A8 | E19 columns whose fill rate *decreases* | — | **0** |

A8 is the regression guard and the one most likely to fail: correctly bounding
the terminal anchor **will** remove text that currently inflates some columns.
A fill-rate drop with a validity rise is a pass; a drop in both is a bug.

Explicit non-goal: A1 does not fill any E19 column. It is prerequisite plumbing.

---

## 5. Test plan

Every test must be shown to fail against the pre-fix code, by reverting the
specific guard rather than by copying the source tree — the source-copy method
was tried in S2 and produced import errors rather than failures, which is not a
check.

1. **Per-revision anchors** — a revision-B fixture with real coordinates;
   assert fields 8–16 are located and field 7 is under its length ceiling.
2. **Terminal bound** — a fixture whose last anchor is field 26; assert the
   field stops at furniture and that `src_unassigned_tail` is non-empty.
3. **Field 1 catastrophe** — the two 280KB records, by SHA; assert under ceiling.
4. **Validity checks** — that a known-contaminated value fails `no_form_label`
   and a known-good one passes.
5. **Anomaly ceilings** — parametrised over the counts in §1.2, so any
   regression that reintroduces them fails the build.
6. **Mutation check** on 4 and 5, since both are the kind of assertion that can
   pass vacuously.

---

## 6. Risks

| risk | mitigation |
|---|---|
| Per-revision hints are wrong for revision A (n=94, least sampled) | Report A and B separately in every measurement; do not let B's 747 records mask A |
| Bounding the terminal anchor drops real trailing content | `src_unassigned_tail` keeps it; A8 catches fill-rate loss |
| Validity checks reject legitimately terse values | `min_words` is per column, not global; BSEE genuinely writes "None." |
| The 2010–14 label trough (0.6% vs 4.4% and 7.7% either side) is a symptom of something not yet found | One hour of diagnosis **before** starting, not after. If it is another revision artifact it belongs in this spec's scope |

---

## 7. Sequence after Phase 0

Unchanged from the completion plan, except that Phase 3's methods now have clean
text to run on, which was the point.

* **Phase 1 — schema decisions.** Gap-fill policy for the 16 modelling-target
  columns (17,221 cells, still undecided); single- vs multi-label (48.3% of
  incidents carry multiple categories); `--real-only`; era-stratified splits
  shipped with the data.
* **Phase 2 — completeness.** Wire synth; add `syn` to the provenance closed
  set; TSTR as a test. **Goal met at the end of this phase.**
* **Phase 3 — soundness.** Clustering to test the six-category assumption; weak
  supervision label model; active-learning gold sample; publish the
  non-random-missingness challenge.

Phase 1 can proceed in parallel with Phase 0 — the decisions are independent of
the extraction work and both are prerequisites for Phase 2.
