# Findings

Running verification log. Dated, append-only. Records what was checked, by what
method, and what came back — including negative results and things that
contradicted our starting assumptions.

---

## 2026-08-02 — Stage 1: acquisition and vocabulary induction

### Summary of what changed relative to the project brief

| Brief said | Actually |
|---|---|
| 2,011 investigations in the structured listing | **2,014** (the site's own pager says `Page 1 of 101 (2014 items)`) |
| 342 PDF links, covering 2018–2026 | **576 unique PDF hrefs**, covering **2014–2026** on the same page |
| Cause vocabulary has 6 categories incl. "Human error" | 6 categories confirmed, but the label is **"Human Performance Error"** |
| Typing standardises around 2023–24 | Boundary is **2021→2022**, and it is a **gradient, not a switch** |
| Typing may be district-specific | **It is not.** Temporal signal is ~3x stronger than district |
| Structured export might carry cause data | **It does not.** Metadata only — the PDF pipeline is required |

---

### Task 2 — does the structured export carry cause data?

**No. Definitively metadata only.** This was the gating question, and the answer
means the PDF pipeline cannot be reduced.

Seven columns: `DATE_OCCURRED`, `MILITARY_TIME`, `LEASE_NUMBER`, `AREA_BLOCK`,
`ACCIDENT_TYPE`, `PANEL_DISTRICT`, `STATUS`. No cause, narrative, findings, or
recommendation field.

Verified three independent ways rather than by inference:
1. Bulk zip export → 7 columns.
2. ASP.NET CSV export driven to completion → same 7 columns.
3. The rendered grid declares exactly 7 filter editors (`DXFREditorcol1`…`col7`)
   and 7 header cells — no hidden column, no detail row, **no link column**.

Row-multiset diff of paths 1 and 2: 2,013 of 2,014 rows identical; the single
difference is an encoding artifact, not data.

`ACCIDENT_TYPE` is the closest thing to causation and is **not** a cause. It is
an incident *classification* (`- Fire`, `- Pollution`, `- Crane`, `- Fatality`)
mirroring the 30 CFR 250.188 reportable-incident thresholds — *what tripped*,
not *why*.

**Retrieval — no browser, no postback, no session required:**

```bash
curl -L -A "Mozilla/5.0" -e "https://www.data.bsee.gov/Main/RawData.aspx" \
  https://www.data.bsee.gov/Other/Files/IncInvRawData.zip -o data/raw/IncInvRawData.zip
```

Verified idempotent across two consecutive runs (byte-identical output).

**Gotchas recorded so nobody re-derives them:**
- The file is **cp1252, not UTF-8** (one `0x96` EN DASH). UTF-8 decode raises;
  latin-1 silently corrupts. The *web CSV export* serves that byte inside a
  `charset=utf-8` response, so the postback path yields mojibake — **the bulk
  zip is the cleaner source**, the opposite of the intuitive assumption.
- The CSV export button sets `useSubmitBehavior: false`, so its `name=` is never
  submitted. Posting `ASPxFormLayout2$btnCsvExport=CSV` returns HTML; the actual
  trigger is `__EVENTTARGET=ASPxFormLayout2$btnCsvExport`.
- The field-definitions page lists `AREA_BLOCK` twice and never names
  `ACCIDENT_TYPE`. This is a **BSEE documentation defect**, not async
  truncation: the phantom row with a blank definition is positionally
  `ACCIDENT_TYPE`. The real column set is 7 and the page does list 7 rows,
  just mislabelled.

**Anomalies logged, not repaired:** 40 rows with a missing hour in
`MILITARY_TIME` (`":15"`, `":0"`, one bare `":"`) — present in *both* retrieval
paths, therefore upstream; 52 blank lease numbers; 265 leases with meaningful
**leading whitespace** (state vs federal — do not `strip()`).

**Join to the district PDFs — viable, but the reverse direction is the problem.**
Key is `(date, minutes-since-midnight)` with area/block as validator, falling
back to `(date, lease_number)`.

| Outcome | n | % |
|---|---|---|
| Tier 1 unique | 1,186 | 94.6% |
| Ambiguous | 0 | 0.0% |
| Tier 2 rescue | 10 | 0.8% |
| **Total unique** | **1,196** | **95.4%** |

Both normalisations are load-bearing — naive string equality on the same fields
scores 36%. **The number that should shape planning:** roughly **818 of 2,014
spine rows (~41%) have no district PDF at all** (the listing starts 2003, the
spine reaches 1995, plus 81 `PANEL` rows and 11 `Pending`). Budget for cause
text on well under two-thirds of rows.

---

### Extraction — text-stream order vs visual order

**Confirmed on real files.** `page.extract_text()` on a 2026 report returns:

```
1. OCCURRED
STRUCTURAL DAMAGE
DATE: 24-MAY-2026 TIME: 1138 HOURS CRANE
```

— two columns interleaved, checkbox `X` marks detached from their labels.

**The fix is cheaper than expected.** Bucketing words into rows by `top`
(tolerance 2.5pt), sorting rows top-to-bottom and words left-to-right, and
splitting the form face at its gutter, fully restores reading order. Field
labels then land *before* their content, so the reported label-after-content
inversion is purely an artifact of stream-order extraction, not a property of
the documents. No OCR needed anywhere in the sample — all 63 files had a text
layer.

Three bugs found and fixed while building this, worth recording because each
produced *plausible but wrong* output rather than an error:

1. **Gutter detection always returned `None`.** The row-crossing test correctly
   identified x≈270–302 as clear, then a second widening step re-measured the
   band against page-wide pixel occupancy — a stricter, contradictory
   criterion. Every page came back single-column. Fix: measure the band with
   the same test that selected it.
2. **Strict ascending field numbers silently dropped fields.** The closing
   admin block is two-column, so the stream reads `25. … 28. …` then
   `26. … 29. …`; requiring ascending numbers discarded fields 4–7, 26, 27 and
   29 on most reports. Fix: accept on label match, suppress duplicates, and
   treat out-of-order as an informational anomaly.
3. **`Flexi-Coil` parsed as a cause category.** A separator alternative
   `(?<=[a-z])-(?=[A-Z])` split ordinary hyphenated compounds, inventing a
   category `The Flexi`. Fix: an ASCII hyphen is a separator only when followed
   by whitespace.

**Extraction rate, n=63 stratified sample:**

| Field | Located | Non-empty |
|---|---|---|
| 17 Investigation Findings | 63/63 | 63/63 |
| **18 Probable Cause(s)** | **63/63** | **63/63** |
| **19 Contributing Cause(s)** | **63/63** | **58/63** |
| 22 Recommendations | 59/63 | 57/63 |
| 4 Lease/Area/Block | 63/63 | 63/63 |

0 parse failures, 0 files without a text layer. Fields 8–16 are missing on 10
reports and field 29 on 40 — a known remaining gap in form-face parsing on
older layouts, not yet chased because fields 17–24 carry the project's payload.

---

### Task 4 — cause vocabulary induction

**Method.** Induction was run **vocabulary-blind**: the parser extracts any
category-like prefix (≤6 words, title-ish, preceding the first `:` / `–` / `- `)
without consulting a category list. Had it matched against the six categories
from the brief, the "induced" vocabulary would just be those six reflected back.

**Sample:** 63 reports, stratified across 2014–2026, all six districts.
82 typed cause statements from fields 18 and 19.

**Result — the vocabulary collapses. 82% onto exactly six categories:**

| n | Category |
|---|---|
| 20 | Equipment Failure |
| 19 | Human Performance Error |
| 11 | Management Systems |
| 7 | Communication |
| 5 | Supervision |
| 5 | Work Environment |

**The remaining 18% is 14 distinct phrases, every one a singleton, and every one
a *subcategory* used without its parent** — `improper hand placement`,
`failure to follow safety protocols`, `lack of job safety analysis`,
`no stop work intervention`, `flawed equipment design`. These are not new
categories; they are level-2 terms appearing bare. That is a strong signal the
taxonomy is real and that authors sometimes skip the top level.

**Correction to the brief:** the dominant label is **"Human Performance Error"**
(19 occurrences), not "Human error" (which appears as a minority variant).
Anything keying on the string `Human error` will miss most of the category.

**Subcategory level is NOT yet shown to be closed.** Observed subcategories are
sparse — mostly 1–4 distinct per category at n=63 — and BSEE wording drifts
(`Inadequate equipment maintenance or equipment repairs` vs
`Inadequate preventative maintenance/Inadequate equipment repair`). Determining
whether level 2 is closed needs a substantially larger sample. **Do not assume
it is.**

### Where the typing boundary actually falls — temporal, not district

Bucketed on the incident date **inside the PDF** (field 1), not the filename —
filename years are unreliable, see below.

| Incident year | n | typed | % typed |
|---|---|---|---|
| 2014 | 4 | 1 | 25% |
| 2016 | 4 | 0 | 0% |
| 2018 | 7 | 3 | 43% |
| 2019 | 2 | 1 | 50% |
| 2020 | 4 | 1 | 25% |
| 2021 | 6 | 1 | 17% |
| **2022** | 6 | 5 | **83%** |
| 2023 | 7 | 6 | 86% |
| 2024 | 8 | 5 | 62% |
| 2025 | 7 | 6 | 86% |
| 2026 | 6 | 4 | 67% |

Collapsed: **2014–2021 = 7/27 typed (26%)**, **2022–2026 = 26/34 typed (76%)**.

| District | n | typed | % typed |
|---|---|---|---|
| New Orleans | 21 | 12 | 57% |
| Houma | 10 | 6 | 60% |
| Lake Charles | 4 | 2 | 50% |
| Lafayette | 13 | 5 | 38% |
| Houston | 2 | 2 | 100% |
| Unknown | 13 | 6 | 46% |

**Verdict: the boundary is temporal.** It falls at **2021→2022**, earlier than
the 2023–24 the brief hypothesised. The district hypothesis is not supported —
the four districts with usable n span 38–60%, a narrow band with no district
near 0% or 100%, while the temporal split is 26% vs 76%.

**Important qualifier: it is a gradient, not a switch.** 2022+ is ~76% typed,
not 100%, and 2018 was already 43%. Typing looks like a **practice that
spread**, not a form revision. Practically: **you cannot filter by year and
assume typed.** Every record needs its `cause_status` checked individually.

Caveats on this table: per-year n is 2–8, so individual years carry wide
intervals; the collapsed 26%-vs-76% split is the load-bearing claim, not any
single year. District was inferred by regex over narrative text and is
`UNKNOWN` for 13 of 63.

---

### Task 3 — corpus scope (harvest)

The "342 links, 2018–2026" figure in the brief understated the corpus in both
directions. `data/manifest.csv` holds **1,303 reports**: **1,241 district** +
**62 panel**.

Coverage reaches back to **2003**, because the district index has a **second
page** — a `district-investigation-reports-archive` — that the brief did not
account for. Split by index page: 591 rows from the main district page, 650
from the archive, 62 from the paginated panel listing.

Per-year counts on the archive side (2003:3, 2004:16, 2005:58, 2006:88,
2007:97, 2008:88, 2009:77, 2010:38, 2011:39, 2012:80, 2013:64, 2014:71,
2015:70, 2016:48, 2017:46) confirm the index's own "since 2005-01-01" claim and
slightly exceed it. 59 rows have no parseable year and carry a
`src_parse_note`; no row was dropped.

28 rows flagged redacted; 11 required URL canonicalisation. 635 of 1,303 rows
carry a non-empty `src_parse_note` — filenames are far more irregular in the
2003–2013 archive than in recent years, so filename-derived area/operator/date
should be treated as a convenience field only. **The authoritative values are
inside the PDF** (form fields 1, 2 and 4).

Spot-checked extraction against five archive-era reports (2006, 2007, 2011,
2017, 2023): all five parsed, all five located field 18 with non-empty content,
and **all five were `freetext`** — an independent confirmation of the temporal
typing finding on documents outside the induction sample.

### Corpus-level gotchas found in passing

**Filename years lie.** `2010` in a BSEE filename is usually the **form
number**, not a year — these are MMS **Form 2010**, and it leaks in as
`EV2010`, `EV2010R`, `2010_Report`, trailing `-2010`. Confirmed examples:
`W_&_T__HI_A_379-B_2010_Report_21-Feb-2024.pdf` is a 2024 report;
`gb-426-31mar19-sanitized-2010.pdf` is 2019. A last-4-digit-year heuristic
produces a spurious 2010 cohort. Parse a **date token**, and fall back to the
in-PDF field 1 date, which is authoritative.

**9 of 576 published PDF links (~1.6%) are dead as published.** They point at
`bsee_prod.opengov.ibmcloud.com`, which does not resolve (SERVFAIL; the
hostname contains an underscore, invalid in DNS). All recover by canonicalising
to `https://www.bsee.gov/sites/bsee.gov/files/<basename>.pdf` — verified
returning HTTP 200 for three of them. Two further links point at
`connect.bsee.gov` and an Acquia staging host. The manifest records both the
as-published href and the canonical fetch URL, because silently rewriting a
broken link would defeat the provenance standard.

**Redactions are undercounted by the obvious test.** 15 of 576 current district
PDFs are redacted, with inconsistent naming (`_Redacted`, ` redacted`,
` Redacted`, mid-filename); `endswith("_Redacted.pdf")` catches about a third.
The 2003–2013 archive has 0 of 656 marked, which is ambiguous between "never
reviewed" and "redacted without the convention" — treated as **unverified for
PII**, not clean.

**Dirty data left dirty**, per convention: BSEE stamps approval dates as
free-floating text that lands *inside* field 18 in visual order (e.g. a stray
`15-JUN-2021` between a category and its description). These are filtered as
page furniture at parse time, and the filter is declared in
`schema/bsee_form2010.yaml` rather than hidden in code.

---

### What is not yet verified

- Whether the level-2 subcategory vocabulary is closed (needs n >> 63).
- Panel-report joinability to the spine — not measured.
- Whether the Xls/Xlsx/Pdf/Rtf grid exports carry a wider column set than CSV.
  They render from the same server-side `ASPxGridView`, so a wider set is
  implausible rather than ruled out.
- Form-face fields 8–16 on ~16% of reports and field 29 on ~63%.
- The 2003–2013 archive has not been extracted, only counted.

## 2026-08-09 — Resolving the coverage fork (labeling vs. free-text handling)

**The fork was a false dichotomy.** Since the vocabulary induction (Task 4,
above) confirmed the extraction premise but left ~68% of the corpus as
free-text prose with no controlled cause vocabulary, the open question was
whether to (a) hand-label the gold set now against the ~32% typed subset, or
(b) first build an LLM-assisted path for the free-text majority. Gold-set
construction does not actually depend on that answer: a human labeller reads
the source PDF directly and assigns `gold_` fields regardless of whether
field 18/19 happened to use the controlled vocabulary. `src_cause_status` is
recorded per report for reference, not as a gate on whether a report is
eligible for the gold set. Building the gold set first is also the right
sequencing on its own merits — it is the fixed yardstick any future
extraction approach (crosswalk-only or LLM-assisted) gets evaluated against;
designing the extraction approach before the eval set exists risks shaping
the eval set around whatever the approach happens to handle well.

**Resolution:** proceed with gold-set construction now, stratified across
the full 2003–2026 corpus (typed and free-text eras alike), not just the
typed subset. The LLM-assisted free-text path is deferred, to be built and
scored against this gold set once it exists — not before.

**What was built**, per Task 5 of the original brief (100 reports,
stratified across years):

- `src/psm/gold_sample.py` — deterministic, year-stratified sampling from
  `data/manifest.csv`. District reports only (`src_report_type ==
  "district"`); panel reports are excluded because they are a structurally
  different, unverified document type (see "not yet verified" below) that
  this project's extraction pipeline was never built against. Selection
  within each year is by ascending `sha256(src_url)` — no stored seed, same
  determinism pattern as `src/psm/synth.py`'s hash offsets. Allocation is
  `target_n // n_years` per year, floored at 1 and capped by that year's
  availability, remainder distributed to the years with the most spare
  capacity. Run against the real manifest: **100 of 1,302 rows selected**,
  every year 2003–2026 represented (2003 capped at 3 — only 3 district
  reports exist for that year), the rest 4–5 each.
- `src/psm/gold_scaffold.py` — assembles `gold/gold_labels.csv` from the
  sampled manifest plus `extract.py`'s per-report JSON: one row per sampled
  report with `src_` reference fields (operator, area/block, date, url,
  field 18/19 raw text) pre-filled, and `gold_cause_category` /
  `gold_psm_element` / `gold_cause_status` / `gold_notes` / `gold_labeler` /
  `gold_label_date` left **blank by design**. This module never writes a
  `gold_` value — doing so would collapse the `gold_`/`llm_` distinction the
  whole provenance convention exists to protect. `src_cause_status` is
  computed per row (typed wins if either field 18 or 19 is typed; freetext
  wins over absent/parse_failed; `absent_legitimate` only when both fields
  are genuinely blank) purely as a reference hint for the labeller, with the
  caveat below.
- Fetched the 100 sampled PDFs (`uv run python -m psm.fetch --manifest
  data/interim/gold_sample_manifest.csv`) — 100/100 downloaded, 0 failures.
  Extracted all of them (`extract.py`) — 104/105 `ok` (105 = 100 sample + 5
  pre-existing dev-sample files already in `data/raw/`), 1 `parse_failed`.
  `gold/gold_labels.csv` now has 100 rows: **29 typed, 70 freetext, 1
  parse_failed** by the automated classifier — see the caveat immediately
  below before treating that split as authoritative.

**Caveat — `src_cause_status` on this sample has a known false-positive
mode, do not cite the 29/70/1 split as clean.** Verifying a 2003 report
flagged `typed` found the actual field-19 text was 100% free prose;
`candidate_category()` (`src/psm/causes.py`) matched on `"NOTE:"` and
`"LIST THE ADDITIONAL INFORMATION:"` — continuation-page furniture bleeding
into the field-19 text run from a multi-page narrative, not real BSEE cause
categories. Reproduced directly:
`candidate_category("NOTE: ABB Vetco has redesigned...")` returns
`("NOTE", "colon")` instead of `(None, "untyped_prose")`. This means the
true free-text share of this sample (and likely the corpus) is **at least
70%, plausibly higher** — the bug only pushes reports *into* `typed`, never
out of it. Flagged as a follow-up task, not fixed here, to keep this session
scoped to resolving the fork rather than re-opening the vocabulary-induction
parser. `gold_cause_status` (human-assigned) is not affected by this bug —
only the `src_cause_status` reference column is.

**Not yet done:** the actual hand-labeling. `gold/gold_labels.csv` is a
scaffold — 100 rows with real reference data and empty `gold_*` columns,
not 100 labelled examples. README's status table has been updated to say so
explicitly rather than implying the file is already labelled.

## 2026-08-09 — Fixing the `candidate_category()` furniture false positive

Follow-up to the caveat immediately above. Root-caused before fixing, per the
project's debugging discipline: scanned every typed statement across the 194
non-empty field-18/19 texts currently cached in `data/interim/` (the 100-report
gold sample plus a few pre-existing dev files) for every head `candidate_category()`
currently accepts. 41 distinct heads matched; two are furniture, not categories:

- `NOTE` (2 occurrences, both in `030521-pdf` — a continuation-page annotation)
- `LIST THE ADDITIONAL INFORMATION` / `LIST THE CONTRIBUTING CAUSE(S) OF ACCIDENT`
  (3 occurrences, `030521-pdf` and `mc-194-enven-20-jan-2020`) — a field's own
  BSEE label bleeding into another field's body text.

The other 39 (Equipment Failure, Human Performance Error, Management Systems,
Communication, Supervision, The IP, The Root Cause, Policy Violation, etc.) are
genuine BSEE cause language and must not be touched. `(Cont.)`-style markers
were already correctly rejected by the existing `head[0].isalpha()` check — no
fix needed there.

**Fix** (`src/psm/causes.py`): added `FURNITURE_HEAD_RE` (`^(?:NOTE|LIST\s+THE\b.*)$`,
case-insensitive) and a check in `candidate_category()` that returns
`(None, "furniture")` for a match, instead of treating it as a typed category.
`LIST\s+THE\b.*` is scoped to BSEE's own field-label phrasing (field 18 is
literally "LIST THE PROBABLE CAUSE(S)") rather than hardcoding field 20's
exact wording, so it generalises to any field's label bleeding into another —
confirmed by the `mc-194-enven` case above, which uses field 19's own label,
not field 20's.

**Regression tests** added to `tests/test_causes.py`: the two furniture
patterns, a cross-field generalisation case, a field-level
`classify_field()` case reproducing the full `030521-pdf` false positive, and
a negative case (`"Listing errors: ..."`) confirming the guard doesn't
collide with real categories. Full suite: 142/142 pass.

**`gold/gold_labels.csv` regenerated** (`uv run python -m psm.gold_scaffold`;
no hand-labels existed yet, all `gold_*` columns were blank, so nothing was
at risk). Exactly one row changed — `030521-pdf` (report
`d34a71a29a8cf864f4c8af727bc4249954300d2f0e7c640162aa04dc4851a9fe`), whose
`src_cause_status` flips from `typed` to `freetext`, matching the diagnosis.
New split: **28 typed, 71 freetext, 1 parse_failed** (was 29/70/1).

**Effect on the two corpus-wide numbers flagged for review:**

- **"82% of typed statements collapse to 6 categories" (Task 4, n=63,
  above).** Not reproducibly affected — none of its reported categories or
  the 14 singleton subcategories look like furniture, and the fix is scoped
  to two patterns neither of which appears in that table. But this could not
  be fully re-verified: the original n=63 file set for Task 4 was not
  preserved separately from the current `data/interim/` cache, so it is
  unclear whether it is a subset of the 194 texts scanned above. Treat the
  82% figure as **unaffected but unverified against this specific fix** —
  re-running Task 4's induction against its original file list, if
  recoverable, is a follow-up, not done here.
- **"~32% typed subset" (fork-resolution entry, above).** This was
  approximate framing, not a precise citation of the pre-fix 29/100=29%
  gold-sample figure. Post-fix it is **28/100 = 28%** typed by the automated
  classifier. Read this as a **soft ceiling, not a clean number**: only two
  furniture patterns were confirmed and fixed from one 100-report sample —
  other BSEE field-label fragments (e.g. from fields 17, 21–24) could still
  be bleeding into 18/19 undetected on reports outside this sample. The
  true typed share is `<= 28%`, direction unchanged from the original
  caveat (the bug only ever pushes reports *into* `typed`).
