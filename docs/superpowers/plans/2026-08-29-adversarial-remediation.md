# Adversarial review — remediation plan

Findings are in `docs/findings.md`, entry *2026-08-29 — Adversarial review*.
This is what to do about them.

## The organising fact

**One three-line defect in `layout._rows()` causes four of the six problems.**
Fixing it first is not a preference — several other fixes are actively wrong to
apply before it. Patching `RE_BLOCK` without fixing `_rows` converts 41
confidently wrong values into 41 blanks. Applying the P1 per-revision field map
before fixing `_rows` applies the *wrong map* to 32 misclassified documents and
converts missing fields into confidently wrong ones.

## What survived the review

Worth stating, because the review was brutal and the picture is not uniform:

- **Field 17 recovery holds and exceeds its claim** — 1,219/1,219 non-empty, 100%
  in every revision, no silent truncation, verified against page geometry.
- **The narrative fields are reliable** — f17/f18/f19/f22 run ~2–5% error across
  all revisions, and every failure inspected was a boundary artifact.
- **Determinism, provenance and referential integrity are clean** — byte-identical
  reruns, 0 verbatim-overwrite violations, 0 orphans, 0 duplicate keys, 0 illegal
  crosswalk values.
- **The parsing layer is genuinely tested.** `causes.py`, `synth.py`,
  `gold_sample.py` and `harvest.py` have real regression tests drawn from real
  failures.

The failures cluster in the **form-face fields** and the **claims layer**, not in
the narrative extraction or the pipeline mechanics.

---

## R0 — Fix `_rows()` first. Everything else waits.

**The defect.** `buckets.setdefault(round(w["top"] / tol), [])` is fixed-bin
quantisation. Words 0.5pt apart split across bins when an edge falls between them.
**9.84% of all visual rows shattered, 1,274 of 1,289 documents affected.**

**The fix.** Single-linkage clustering on `top`: sort words, start a new row when
the gap to the previous word exceeds the tolerance. Same tolerance constant, same
output shape, no downstream signature change.

**Then re-extract and re-measure all four dependent defects** rather than
assuming they resolved:

| Expected to fix | Verify by |
|---|---|
| `src_form_revision` wrong on ≥45 records | re-run detection; the 32 A→B flips should land |
| 41 `Area == "5"` records | compare against filename-derived block |
| Field 28 label bleed | MAJOR/MINOR should appear clean on ~88 records |
| Field 5 blank on 124/127 rev-A records | fill rate should rise sharply |

**Do not touch `RE_BLOCK` yet.** Re-measure after `_rows` and see what is left.

### R0.1 — `find_gutter` is per-page; the layout is per-region

Separate defect, same area. The admin block sits at the *bottom* of a page whose
upper two-thirds is single-column narrative, so the whole-page gutter test never
fires — **127 of 434 admin pages (29.3%)**. Fix by detecting the gutter per
horizontal band rather than per page. Lower priority than `_rows` and independent
of it.

---

## R1 — Vocabulary constraints in the projection

`e19_projection.yaml` has no concept of a legal value, so a raw text dump lands in
a picklist column: **234 illegal values that block 149 valid crosswalk results.**

1. Add `vocabulary:` to mapping entries whose E19 column is picklist-backed.
2. `psm.project` writes a value only if legal; otherwise blank plus an anomaly.
3. Remap `Incident Classification` / `Incident Classificatioin` — BSEE MAJOR/MINOR
   is **not** the E19 VSI/SI/Incident vocabulary. Either crosswalk it explicitly or
   route field 28 to the sidecar.
4. **Add a legality test over every committed table.** Ten lines. It would have
   caught this, and nothing currently checks values rather than headers.

---

## R2 — Recommendation grain

The blank-line splitter never fires. Find the real separator — the 72 multi-item
cells are enumerated (`1)`, `2)`, `3.`) — and split on that. Treat
`none` / `N/A` / `NO` as `absent_legitimate` per the repo's existing convention
rather than as recommendation text. Then `Recommendation Number` becomes
meaningful and `closeout.csv` inherits a true grain.

---

## R3 — Retract the statistic, re-band the likelihood

**Do not present the lifting claim as written.** The defensible version:

> Among BSEE investigations 2007–2026 — the period in which both the lifting and
> lost-time-injury codes were in use — 24% of investigations tagged Crane or Other
> Lifting Device also record a fatality or lost-time injury (n=264), against 10%
> of those tagged Fire (n=186): a rate ratio of 2.5 (95% CI 1.4–4.5). Explosion is
> indistinguishable from lifting at 26% (n=27). Blowout and Collision cannot be
> compared — their codes were retired before the lifting code came into use. These
> are per-investigated-incident conditional rates, not per-lift or per-exposure
> risks, over incidents BSEE chose to investigate.

Drop "7× more than a blowout" — the interval spans 1.7 to 29 on two events. Drop
"the dramatic hazards damage plant; the routine ones hurt people" — the comparable
explosion data contradicts it.

**Then re-measure `observed_rates` on the 2007+ window and re-band.** Expect
Explosion 4→5, Fire 2→3, and Blowout/Collision to become unestimable — which must
be recorded as `null` with a reason, not defaulted. Every Section 3 score changes.
Record in the rule file that the rates are window-restricted and why.

---

## R4 — Make the test suite able to fail

1. **Delete or demote the 13 prose-assertion tests.** A test that asserts
   `"ASSUMED" in a_string` is documentation with an `assert` around it. Keep the
   seven that cross-check `crosswalk.yaml` against machine-generated
   `e19_labels.yaml` — those are the ones that would have caught the v1 bug.
2. **Add the missing behavioural test**: swapping two categories' element numbers
   must turn something red. Cross-check `primary_element` against the element
   *name* and the entry's own `matched_on` phrase.
3. **Test `psm.crosswalk`.** 243 statements, 0%. At minimum: `resolve_types`
   precedence, the verbatim-wins invariant, `section3` banding, determinism.
4. **Rename** `tests/test_crosswalk.py` → `test_crosswalk_schema.py`. The name
   collision with `psm.crosswalk` is the likely reason the gap went unseen.
5. **Rewrite `tests/test_conventions.py`** to enforce the provenance rule on the
   shipped tables, or amend CLAUDE.md to describe the parallel-provenance-file
   design that actually shipped. Currently the doc and the data disagree and
   nothing tests either.

---

## R5 — Make one number reportable

Nothing here can be scored. In order:

1. **Fix the gold join** — one hop through `bsee_unmapped.csv` recovers 99/100.
   Document it, test it.
2. **Write the scoring script.** None exists.
3. **Label the typed subset, n=28.** An afternoon: these already carry a
   controlled category, so the labeller adjudicates rather than reads full PDFs.
4. **Report exactly one number**: crosswalk element-assignment accuracy on the
   typed subset, n=28, in-sample, single annotator, ±18pp — with all four
   qualifiers in the same sentence as the number.

Do **not** attempt the 20-class PSM-element metric at n=100. It is out by a factor
of ten.

**Declare the leak.** Four sites are already documented in the rule files: the
vocabulary was induced on all 3,462 statements, the likelihood rates measured on
the same 2,014 rows they label, the banding chosen by inspecting the resulting
distribution, the qualifier patterns fit to the observed subcategories. Any number
from this corpus is **in-sample**. Say so in the same breath, or hold out a slice
of reports from future rule induction so a genuine out-of-sample number becomes
possible.

---

## R6 — README

Three contradictions between the front page and the data:

1. It lists risk scores as `syn_`; provenance says `xw`. **Reconcile or
   re-prefix.** The reviewer's argument that they fail the repo's own `xw_` bar —
   "an external, independently published source" — is strong: the EEI SCL model
   supplies the *concept*, every tier letter is ours.
2. **Add the panel severity bias.** 54% of fatality incidents are panel
   investigations and excluded; 3 fatalities reach the output against 86 in the
   spine. `findings.md` says this belongs in the README. It still is not there.
3. **Document the provenance-file design** — that E19 columns carry exact template
   labels and provenance lives in a parallel file.

## R7 — Resolve the missing fatalities

3 in the output, 86 in the spine, 46 explained by panel exclusion. **~37
unexplained.** Flagged twice in `findings.md` as unverified and still open. No
severity-weighted claim should be made from this corpus until it is closed.

---

## Sequencing

```
R0 _rows fix ── re-extract ── re-measure R0(a)-(d) ──┐
                                                     ├─ R1 vocabulary constraints
R0.1 gutter per band ────────────────────────────────┤
                                                     ├─ R2 recommendation grain
R3 re-band likelihood on 2007+ ──────────────────────┤
                                                     └─ re-project, re-crosswalk
R4 tests ──────── independent, do alongside
R5 gold set ───── independent, needs a human
R6 README ─────── independent, one hour
R7 fatalities ─── independent investigation
```

R0 gates R1 and R2 because both operate on fields `_rows` currently corrupts. R3,
R4, R6 and R7 are independent and can run in any order.

## Definition of done

- Row shattering under 1% of visual rows, measured the same way
- `src_form_revision` agrees with an independent field-3 read on ≥99%
- Zero illegal values in any picklist-backed column, enforced by test
- `Recommendation Number` takes more than one distinct value
- Coverage on `psm.crosswalk` above 60%, and swapping two element numbers fails a test
- One accuracy number reported with n, CI, annotator count and in-sample caveat
- README states the panel bias and the true provenance of the risk columns
